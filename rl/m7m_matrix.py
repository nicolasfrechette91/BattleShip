"""M7m campaign matrix: runs, order, registered settings, warm starts, evaluation plan, directories and the manifest.
Reads only; the driver is rl/m7m_campaign.py.

Arms (docs/rl_sweep_consolidation_m7m_design.md; rule docs/rl_sweep_consolidation_m7m_decision_rule.json):
    E   m7m_e_s{0,1,2}: anchored backward starts (tick0_probability 1/2 until the schedule completes)
    K   m7m_k_s{0,1,2}: the same machinery with tick0_probability 1.0 (normal tick-0 starts only)
Both arms of pair j are warm-started from the pinned Phase K reward-v2 final runs/m7g_k/m7g_s{j}_v1/final and train
+1,536,000 policy-controlled transitions (cumulative 4,608,000). Order E0, K0, E1, K1, E2, K2, strictly sequential.

The integration pilot (m7m_pilot_{e,k}_s0, +40,960 transitions each, below runs/m7m/pilot) runs first; its outputs stay
separate, it is never an input of the campaign or the rule, and every campaign run starts again from its pinned Phase K
checkpoint.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import experiment_config as ec
import m7h_guard as g
import m7h_matrix as hm
import m7m_analysis as mn
import m7m_anchor as ma

REPO_ROOT = ec.REPO_ROOT
MILESTONE = "M7m"
CAMPAIGN = "anchored_sweep_consolidation_v1"
MANIFEST_SCHEMA = "battleship_m7m_campaign_manifest_v1"
CONFIG_DIR = REPO_ROOT / "rl" / "configs" / "m7m"
PILOT_CONFIG_DIR = CONFIG_DIR / "pilot"
PHASE_K_CONFIG_DIR = REPO_ROOT / "rl" / "configs" / "m7g"
MANIFEST_DOC = REPO_ROOT / "docs" / "rl_sweep_consolidation_m7m_manifest.json"
RULE_DOC = mn.RULE_DOC
DESIGN_DOC = REPO_ROOT / "docs" / "rl_sweep_consolidation_m7m_design.md"
FEASIBILITY_DOC = REPO_ROOT / "docs" / "rl_sweep_consolidation_m7m_feasibility.md"
PLAN_DOC = REPO_ROOT / "docs" / "rl_sweep_consolidation_m7m_feasibility_plan.json"
FEASIBILITY_SUMMARY = REPO_ROOT / "runs" / "m7m" / "feasibility" / "summary.json"
DEFAULT_ROOT = REPO_ROOT / "runs" / "m7m" / "campaign"
PILOT_ROOT = REPO_ROOT / "runs" / "m7m" / "pilot"
HISTORICAL = REPO_ROOT / "runs" / "m7g_k"
RUNS = REPO_ROOT / "runs"
MAX_GAME_PROCESSES = hm.MAX_GAME_PROCESSES                     # 10
M6_FLAGS = dict(hm.M6_FLAGS)
DIAG_FLAG = dict(ec.ANCHOR_CURRICULUM_EXTRA_ENV)

SEEDS: Tuple[int, ...] = (0, 1, 2)
ARMS: Tuple[str, ...] = ("E", "K")
ORDER: Tuple[Tuple[int, str], ...] = ((0, "E"), (0, "K"), (1, "E"), (1, "K"), (2, "E"), (2, "K"))
BASE_SEED_OFFSET = 100
WARM_START_T = 3_072_000
ADDITIONAL = 1_536_000                     # policy-controlled transitions per campaign run (hard maximum)
TOTAL = WARM_START_T + ADDITIONAL          # 4,608,000 cumulative
ROLLOUT = 5_120
N_EPOCHS, MINIBATCHES = 10, 10
CHECKPOINT_INTERVAL = 102_400
CURVE_POINTS: Tuple[int, ...] = (WARM_START_T + 512_000, WARM_START_T + 1_024_000)
FINAL_EPISODES = {"deterministic": 100, "stochastic": 100}
CURVE_EPISODES = {"deterministic": 5, "stochastic": 60}
EVAL_SEED = 12345
PILOT_SEED, PILOT_TRANSITIONS = 0, 40_960  # 8 rollouts per pilot arm, registered before launch
PILOT_EVAL_EPISODES = {"deterministic": 1, "stochastic": 5}
OBS_TABLE_SHA256 = "8880607470e23a36bf99b934b7cc5b0eee33f87ba382817f14fe59016955ab27"
WARM_ADAM_STEP, WARM_N_UPDATES = 60_000, 6_000
M7L_EVIDENCE = [REPO_ROOT / "docs" / n for n in ("rl_target2_m7l_decision_rule.json", "rl_target2_m7l_manifest.json",
                                                 "rl_target2_m7l_analysis_n3.json", "rl_target2_m7l_results.md")] + \
    [REPO_ROOT / "runs" / "m7l" / "campaign" / "_matrix" / n for n in ("manifest.json", "analysis_n3.json")]
LAUNCH_GATE_READINGS, LAUNCH_GATE_RETRY_S = 5, 60.0


class MatrixError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


read_json = hm.read_json
write_json = hm.write_json
sha256_file = hm.sha256_file
within = hm.within


def canonical_sha256(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# -- roots (redirectable for tests) --------------------------------------------------------------------------------

_ROOT, _PILOT = DEFAULT_ROOT, PILOT_ROOT


def configure_root(root: Optional[Path], pilot_root: Optional[Path] = None) -> None:
    global _ROOT, _PILOT
    _ROOT = Path(root).resolve() if root is not None else DEFAULT_ROOT
    _PILOT = Path(pilot_root).resolve() if pilot_root is not None else PILOT_ROOT


def root(pilot: bool = False) -> Path:
    return _PILOT if pilot else _ROOT


def state_dir() -> Path:
    return _ROOT / "_matrix"


def guard_root(pilot: bool = False) -> Path:
    return root(pilot) / "_guard"


def partial_root(pilot: bool = False) -> Path:
    return root(pilot) / "_partial"


# -- runs ------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunSpec:
    seed: int
    arm: str
    pilot: bool = False

    @property
    def name(self) -> str:
        return f"m7m_{'pilot_' if self.pilot else ''}{self.arm.lower()}_s{self.seed}"

    @property
    def config_path(self) -> Path:
        return (PILOT_CONFIG_DIR if self.pilot else CONFIG_DIR) / f"{self.name}.toml"

    @property
    def run_dir(self) -> Path:
        return root(self.pilot) / self.name

    @property
    def eval_dir(self) -> Path:
        return root(self.pilot) / "_eval" / self.name

    @property
    def clears_dir(self) -> Path:
        return root(self.pilot) / "_clears" / self.name

    @property
    def base_seed(self) -> int:
        return BASE_SEED_OFFSET + self.seed

    @property
    def warm_start(self) -> Path:
        return HISTORICAL / f"m7g_s{self.seed}_v1" / "final"

    @property
    def tick0_probability(self) -> float:
        return ma.TICK0_PROBABILITY_E if self.arm == "E" else ma.TICK0_PROBABILITY_K

    @property
    def additional(self) -> int:
        return PILOT_TRANSITIONS if self.pilot else ADDITIONAL

    @property
    def total(self) -> int:
        return WARM_START_T + self.additional

    @property
    def order_index(self) -> int:
        return (ORDER.index((self.seed, self.arm)) if not self.pilot else ARMS.index(self.arm))


def matrix() -> List[RunSpec]:
    return [RunSpec(s, a) for s, a in ORDER]


def pilot_matrix() -> List[RunSpec]:
    return [RunSpec(PILOT_SEED, a, pilot=True) for a in ARMS]


def run_by_name(name: str) -> RunSpec:
    for s in matrix() + pilot_matrix():
        if s.name == name:
            return s
    raise MatrixError(f"unknown run {name}")


def load_run(spec: RunSpec) -> ec.Experiment:
    return ec.load_experiment(spec.config_path)


def phase_k_profile(seed: int) -> Path:
    return PHASE_K_CONFIG_DIR / f"m7g_s{seed}_v1.toml"


def value_diff(a: ec.Experiment, b: ec.Experiment) -> List[str]:
    return sorted(p for p in set(a.values) | set(b.values) if a.values.get(p) != b.values.get(p))


def arm_checks(spec: RunSpec, exp: ec.Experiment) -> Dict[str, bool]:
    v = exp.values
    return {
        "name": exp.name == spec.name and exp.run_dir == spec.run_dir,
        "warm_start_mode": exp.mode == "resume" and exp.resume_source == spec.warm_start.resolve(),
        "total_transitions": int(v["run.total_transitions"]) == spec.total,
        "base_seed": int(v["run.base_seed"]) == spec.base_seed,
        "anchor_table": exp.anchor_curriculum == ma.registered_table(tick0_probability=spec.tick0_probability,
                                                                     observation_table_sha256=OBS_TABLE_SHA256),
        "no_m7h_curriculum": exp.curriculum is None,
        "reward_v2": exp.reward.contract == "btt_reward_v2" and exp.reward.canonical,
        "observation_v1": v["contracts.observation"] == "btt_policy_obs_v1" and v["ppo.policy"] == "MlpPolicy",
        "track1": v["contracts.action"] == "btt_s9_b8_v1",
        "flags": dict(exp.extra_env) == dict(M6_FLAGS, **DIAG_FLAG),
        "horizon_n5_standby": (int(v["environment.horizon"]) == 3600 and exp.process_count == 5
                               and exp.standby_preboot and exp.standby_count == 1),
        "checkpoint_interval": int(v["checkpoint.interval"]) == CHECKPOINT_INTERVAL,
        "post_hoc_evaluation": int(v["evaluation.interval"]) == 0 and not v["evaluation.initial"] and not v["evaluation.final"],
    }


def phase_k_proof(spec: RunSpec, exp: ec.Experiment) -> Dict[str, Any]:
    """Against the Phase K v1 profile of the seed, only run.*, the warm-start source and the anchor table differ."""
    base = ec.load_experiment(phase_k_profile(spec.seed))
    diff = value_diff(exp, base)
    ok = all(p.startswith(("run.", "anchor_curriculum.")) or p in ("resume.source_checkpoint",) for p in diff)
    return {"base": ec.repo_relative(phase_k_profile(spec.seed)), "value_differences": diff, "ok": ok}


def pair_proof(e: RunSpec, k: RunSpec) -> Dict[str, Any]:
    diff = value_diff(load_run(e), load_run(k))
    return {"pair": [e.name, k.name], "value_differences": diff,
            "ok": diff == ["anchor_curriculum.tick0_probability", "run.name", "run.notes"]}


def warm_start_identity(seed: int) -> Dict[str, Any]:
    """The pinned Phase K final equals its feasibility registration (file hashes, policy and statistics digests)."""
    import pickle

    import m7_evaluation as me
    from m7_trainer import M7PPO

    d = RunSpec(seed, "E").warm_start
    reg = next(w for w in read_json(PLAN_DOC)["warm_starts"] if int(w["seed"]) == seed)
    files = {n: sha256_file(d / n) for n in ("checkpoint.json", "model.zip", "vecnormalize.pkl")}
    model = M7PPO.load(str(d / "model.zip"), device="cpu")
    with open(d / "vecnormalize.pkl", "rb") as fp:
        vn = pickle.load(fp)
    steps = sorted({int(v["step"]) for v in model.policy.optimizer.state_dict()["state"].values()})
    meta = read_json(d / "checkpoint.json")
    cur = {"files_sha256": files, "policy_parameter_digest": me.policy_parameter_digest(model),
           "obs_rms_digest": me.obs_rms_digest(vn), "num_timesteps": meta.get("num_timesteps"),
           "n_updates": meta.get("n_updates"), "adam_steps": steps, "obs_rms_count": float(vn.obs_rms.count),
           "checkpoint_files": meta.get("files")}
    p = [k for k in ("files_sha256", "policy_parameter_digest", "obs_rms_digest", "num_timesteps") if cur[k] != reg.get(k)]
    if cur["n_updates"] != WARM_N_UPDATES or steps != [WARM_ADAM_STEP]:
        p.append(f"n_updates {cur['n_updates']} / Adam steps {steps}")
    return {"path": ec.repo_relative(d), **cur, "problems": p, "ok": not p}


# -- code identity ---------------------------------------------------------------------------------------------------


def evidence_files() -> List[Path]:
    return [ma.ANCHOR_FILE, ma.OBS_TABLE_FILE, PLAN_DOC, RULE_DOC]


def code_files() -> List[Path]:
    """Every non-test rl/*.py module, the M7m profiles (pilot included), the Phase K profiles, the anchor, the start-state
    table, the feasibility plan and the rule."""
    files = sorted(p for p in (REPO_ROOT / "rl").glob("*.py") if not p.name.endswith(("_tests.py", "_smoke.py")))
    files += sorted(CONFIG_DIR.rglob("*.toml")) + [phase_k_profile(s) for s in SEEDS] + evidence_files()
    return files


def code_fingerprint() -> Dict[str, Any]:
    agg = hashlib.sha256()
    per: Dict[str, str] = {}
    for p in code_files():
        h = sha256_file(p)
        rel = p.relative_to(REPO_ROOT).as_posix()
        per[rel] = h
        agg.update(f"{rel}\0{h}\n".encode("utf-8"))
    return {"files": len(per), "sha256": agg.hexdigest(), "per_file": per}


def revisions() -> Dict[str, Any]:
    import m7g_k_matrix as km

    return km.revisions()


def executable_identity() -> Dict[str, Any]:
    return load_run(matrix()[0]).executable_fingerprint()


def current_identity() -> Dict[str, Any]:
    profiles = {}
    for s in matrix() + pilot_matrix():
        e = load_run(s)
        profiles[s.name] = (e.source.sha256, e.semantic_fingerprint, e.compatibility_fingerprint)
    return {"executable_sha256": executable_identity().get("sha256"), "revisions": revisions(),
            "code_sha256": code_fingerprint()["sha256"], "rule_sha256": sha256_file(RULE_DOC), "profiles": profiles}


def manifest_drift(manifest: Mapping[str, Any], cur: Optional[Mapping[str, Any]] = None) -> List[str]:
    cur = cur or current_identity()
    p: List[str] = []
    if not manifest.get("ok"):
        p.append(f"the manifest reports problems: {manifest.get('problems')}")
    if cur["executable_sha256"] != (manifest.get("executable") or {}).get("sha256"):
        p.append("executable sha256 differs from the manifest")
    rev, mrev = cur["revisions"], manifest.get("revisions") or {}
    if rev.get("head") != mrev.get("head"):
        p.append(f"parent HEAD {rev.get('head')} != manifest {mrev.get('head')}")
    if rev.get("submodules") != mrev.get("submodules"):
        p.append(f"submodule revisions {rev.get('submodules')} != manifest {mrev.get('submodules')}")
    if rev.get("submodules_differ_from_index"):
        p.append(f"submodules differ from the recorded gitlinks: {rev['submodules_differ_from_index']}")
    if cur["code_sha256"] != (manifest.get("code") or {}).get("sha256"):
        p.append("the Python code, an M7m / Phase K profile, the anchor, the table, the plan or the rule changed")
    if cur["rule_sha256"] != (manifest.get("decision_rule") or {}).get("sha256"):
        p.append("the decision rule differs from the manifest")
    for name, triple in cur["profiles"].items():
        r = ((manifest.get("runs") or {}).get(name) or (manifest.get("pilot") or {}).get("runs", {}).get(name))
        if r is None or (r["source_sha256"], r["semantic_fingerprint"], r["compatibility_fingerprint"]) != tuple(triple):
            p.append(f"{name}: profile source / fingerprints differ from the manifest")
    return p


def changed_files(manifest: Mapping[str, Any]) -> List[str]:
    before, now = (manifest.get("code") or {}).get("per_file") or {}, code_fingerprint()["per_file"]
    return sorted(k for k in set(before) | set(now) if before.get(k) != now.get(k))


# -- evaluation plan -------------------------------------------------------------------------------------------------


def evaluation_plan(spec: RunSpec, exp: ec.Experiment) -> List[Dict[str, Any]]:
    """Tick-0 starts only, frozen statistics, seed 12345, every episode preserved, btt_eval_metrics_v1 on: curve points at
    +512,000 and +1,024,000 (5 deterministic + 60 stochastic), final (100 + 100). The pilot: its final, 1 + 5 (smoke)."""
    v = exp.values
    if int(v["run.total_transitions"]) != spec.total:
        raise MatrixError(f"{spec.name}: total_transitions {v['run.total_transitions']}")
    common = {"seed": int(v["evaluation.seed"]), "workers": exp.eval_workers, "horizon": int(v["environment.horizon"]),
              "extra_env": dict(exp.extra_env), "standby_preboot": exp.standby_preboot,
              "standby_count": exp.standby_count, "frozen_vecnormalize": True, "preserve_all": True,
              "eval_metrics": True, "observation": "btt_policy_obs_v1", "reward_contract": exp.reward.contract,
              "starts": "tick0_only", "run": spec.name, "arm": spec.arm}
    if spec.pilot:
        return [dict(common, label="final", checkpoint=f"{spec.name}/final", num_timesteps=spec.total,
                     deterministic_episodes=PILOT_EVAL_EPISODES["deterministic"],
                     stochastic_episodes=PILOT_EVAL_EPISODES["stochastic"])]
    plan = [dict(common, label=f"curve_t{t:09d}", checkpoint=f"{spec.name}/checkpoints/ckpt_{t:09d}", num_timesteps=t,
                 deterministic_episodes=CURVE_EPISODES["deterministic"], stochastic_episodes=CURVE_EPISODES["stochastic"])
            for t in CURVE_POINTS]
    plan.append(dict(common, label="final", checkpoint=f"{spec.name}/final", num_timesteps=spec.total,
                     deterministic_episodes=FINAL_EPISODES["deterministic"], stochastic_episodes=FINAL_EPISODES["stochastic"]))
    return plan


def census_plan() -> Dict[str, Any]:
    per = sum(CURVE_EPISODES.values()) * len(CURVE_POINTS) + sum(FINAL_EPISODES.values())
    return {"runs": len(matrix()), "per_run": per, "episodes": len(matrix()) * per,
            "arithmetic": f"{len(matrix())} runs x ({len(CURVE_POINTS)} x 65 + 200) = {len(matrix()) * per}"}


# -- directories -----------------------------------------------------------------------------------------------------


def planned_directories() -> Dict[str, Path]:
    d: Dict[str, Path] = {"root": _ROOT, "pilot_root": _PILOT, "state": state_dir(), "guard": guard_root(),
                          "partial": partial_root(), "pilot_guard": guard_root(True), "pilot_partial": partial_root(True)}
    for s in matrix() + pilot_matrix():
        d[f"run:{s.name}"] = s.run_dir
        d[f"eval:{s.name}"] = s.eval_dir
        d[f"clears:{s.name}"] = s.clears_dir
    return d


def check_directory_plan() -> Dict[str, Any]:
    dirs = planned_directories()
    p: List[str] = []
    norm = {k: Path(os.path.normpath(str(v))) for k, v in dirs.items()}
    if len(set(norm.values())) != len(norm):
        p.append("two planned directories resolve to the same path")
    leaves = sorted((k, v) for k, v in norm.items() if k.split(":")[0] in ("run", "eval", "clears")
                    or k in ("state", "guard", "partial", "pilot_guard", "pilot_partial"))
    for i, (ka, pa) in enumerate(leaves):
        for kb, pb in leaves[i + 1:]:
            if within(pa, pb) or within(pb, pa):
                p.append(f"{ka} and {kb} overlap")
    if within(norm["root"], norm["pilot_root"]) or within(norm["pilot_root"], norm["root"]):
        p.append("the pilot root and the campaign root overlap")
    protected = [HISTORICAL, RUNS / "m7l", RUNS / "m7h", RUNS / "m7k", RUNS / "m7j", RUNS / "m7e",
                 RUNS / "m7m" / "feasibility"]
    for r in (norm["root"], norm["pilot_root"]):
        for h in protected:
            if within(r, h) or within(h, r):
                p.append(f"{ec.repo_relative(r)} overlaps {ec.repo_relative(h)}")
    for s in matrix() + pilot_matrix():
        exp = load_run(s)
        if exp.run_dir != s.run_dir or exp.name != s.name:
            p.append(f"{s.name}: profile resolves to {exp.name} / {exp.run_dir}")
    existing = sorted(k for k, v in norm.items() if k.split(":")[0] in ("run", "eval", "clears") and v.exists())
    return {"root": ec.repo_relative(norm["root"]), "pilot_root": ec.repo_relative(norm["pilot_root"]),
            "planned": len(dirs), "existing": existing, "problems": p, "ok": not p}


# -- the manifest ----------------------------------------------------------------------------------------------------


def registered_settings() -> Dict[str, Any]:
    from dataclasses import asdict

    return {
        "contracts": {"reward": "btt_reward_v2 (unchanged)", "observation": "btt_policy_obs_v1",
                      "action": "btt_s9_b8_v1 (Track 1)", "horizon_ticks": 3600,
                      "native_flags": dict(M6_FLAGS, **DIAG_FLAG),
                      "diagnostic_flag": "SSB64_RL_TARGET_DIAG=1, read-only and gameplay-neutral, in both arms and in "
                                         "every evaluation; never part of the policy observation"},
        "warm_start": ("both arms of pair j load runs/m7g_k/m7g_s{j}_v1/final: policy parameters and Adam optimizer "
                       "state (step 60,000) from model.zip, VecNormalize statistics continuing (training=True, "
                       "observations only), num_timesteps continuing from 3,072,000 (reset_num_timesteps=False), "
                       "constant learning rate 3e-4 and clip range 0.2, set_random_seed(base_seed) at load with the same "
                       "base seed (100 + j) in E_j and K_j; the one accepted compatibility difference is the diagnostic "
                       "flag (recorded in the lineage); a checkpoint trained with any curriculum is refused"),
        "budget": {"policy_transitions_per_run": ADDITIONAL, "cumulative_target": TOTAL, "rollouts": ADDITIONAL // ROLLOUT,
                   "hard_maximum": True, "prefix_ticks": "never counted as transitions; reported separately"},
        "schedule": {"E": ("anchored starts drawn after automatic resets with probability 1/2 (tick0_probability 0.5) "
                           "until the schedule completes; then tick-0 starts only"),
                     "K": "tick0_probability 1.0: normal tick-0 starts only (the same worker, vector wrapper and logs)",
                     "windows": [list(w) for w in ma.WINDOWS], "block": ma.BLOCK, "block_successes": ma.BLOCK_SUCCESSES,
                     "cut_semantics": ma.registered_plan()["cut_semantics"],
                     "success": ma.registered_plan()["success"],
                     "in_flight_outcomes": mn.rule_document()["in_flight_outcomes"]},
        "launch_gate": {"available_commit_gib_min": g.LAUNCH_COMMIT_GIB, "available_physical_gib_min": g.LAUNCH_PHYSICAL_GIB,
                        "free_disk_gib_min": g.LAUNCH_DISK_GIB, "system_cpu_pct_max": g.LAUNCH_MAX_CPU_PCT,
                        "readings": f"a failed reading is re-measured after {LAUNCH_GATE_RETRY_S:.0f} s, at most "
                                    f"{LAUNCH_GATE_READINGS} readings; the run launches only on a passing reading",
                        "when": "before every training launch (pilot and campaign runs)"},
        "in_run_memory_policy": dict(asdict(g.REGISTERED_POLICY), watches="available system commit only"),
        "monitor": "m7d Monitor: hard alerts stop the run (an episode row violating its prefix-aware btt_reward_v2 "
                   "closed form, more than 10 game processes or listeners in two samples, a changed user config, low disk)",
        "stop_conditions": ["a failed launch gate", "a monitor hard alert", "the in-run memory policy", "manifest drift",
                            "a provenance mismatch", "a process leak", "a training or evaluation verification failure "
                            "(an evaluation label may be re-run once)", "a failed pilot check"],
        "after_a_stop": "the campaign stops and reports; a stopped run directory is moved to _partial by the guard and "
                        "preserved; nothing is resumed, relaunched or extended",
        "training_inputs": "the run's own episodes and the registered anchor's start states only; never supervised "
                           "targets, other runs' weights, the crossing fixtures, TAS, feasibility or pilot outputs",
        "never": "native RNG state is never inspected, logged, validated, controlled, compared or hashed; no training "
                 "videos",
    }


def pilot_registration() -> Dict[str, Any]:
    runs = {}
    for s in pilot_matrix():
        exp = load_run(s)
        runs[s.name] = {"arm": s.arm, "config": ec.repo_relative(s.config_path), "source_sha256": exp.source.sha256,
                        "semantic_fingerprint": exp.semantic_fingerprint,
                        "compatibility_fingerprint": exp.compatibility_fingerprint, "checks": arm_checks(s, exp),
                        "run_dir": ec.repo_relative(s.run_dir)}
    return {
        "runs": runs, "transition_cap_per_run": PILOT_TRANSITIONS, "rollouts_per_run": PILOT_TRANSITIONS // ROLLOUT,
        "warm_start": "the seed-0 Phase K final, as the campaign pair 0", "outputs": ec.repo_relative(PILOT_ROOT),
        "evaluation_smoke": dict(PILOT_EVAL_EPISODES, label="final", note="pipeline check only"),
        "checks": ["actual PPO updates: n_updates +80, Adam step +800 on every parameter, policy digest changed",
                   "continuation: num_timesteps 3,112,960; 8 rollout records; obs_rms count = warm + 5 + 40,960",
                   "policy-only accounting: finished-episode policy steps <= 40,960 and >= 40,960 - 5 x 3,600; prefix "
                   "ticks only in the selection log; row prefix_length = outcome tau; rows = prefix + policy",
                   "E: at least one anchored start delivered equal to the table in W0, its outcome ingested; K: no "
                   "anchored draw, no prefix tick",
                   "schedule state = blocks recomputed from the logged outcomes (in-flight rule)",
                   "training verification (m7d, warm-start segment), lineage = the pinned Phase K final, leak-free",
                   "the evaluation smoke: tick-0 starts, metrics clean, rows verified"],
        "never": "pilot performance is never used to tune the curriculum, reward or budget; pilot outputs are never "
                 "campaign inputs; each campaign run starts again from its pinned Phase K checkpoint",
    }


def build_manifest() -> Dict[str, Any]:
    problems: List[str] = []
    runs: Dict[str, Any] = {}
    warm = {str(s): warm_start_identity(s) for s in SEEDS}
    for s, w in warm.items():
        if not w["ok"]:
            problems.append(f"warm start s{s}: {w['problems']}")
    for s in matrix():
        exp = load_run(s)
        checks = arm_checks(s, exp)
        proof = phase_k_proof(s, exp)
        bad = [k for k, ok in checks.items() if not ok]
        if bad:
            problems.append(f"{s.name}: frozen values violated: {bad}")
        if not proof["ok"]:
            problems.append(f"{s.name} vs Phase K: {proof}")
        runs[s.name] = {"seed": s.seed, "arm": s.arm, "order": s.order_index, "base_seed": s.base_seed,
                        "config": ec.repo_relative(s.config_path), "source_sha256": exp.source.sha256,
                        "semantic_fingerprint": exp.semantic_fingerprint,
                        "compatibility_fingerprint": exp.compatibility_fingerprint,
                        "anchor_curriculum": exp.anchor_curriculum, "extra_env": dict(exp.extra_env),
                        "warm_start": ec.repo_relative(s.warm_start), "run_dir": ec.repo_relative(s.run_dir),
                        "eval_dir": ec.repo_relative(s.eval_dir), "checks": checks, "phase_k_proof": proof}
    pairs = [pair_proof(RunSpec(j, "E"), RunSpec(j, "K")) for j in SEEDS] + \
        [pair_proof(*pilot_matrix())]
    problems += [f"pair {p['pair']}: {p['value_differences']}" for p in pairs if not p["ok"]]
    pilot = pilot_registration()
    for name, r in pilot["runs"].items():
        bad = [k for k, ok in r["checks"].items() if not ok]
        if bad:
            problems.append(f"{name}: frozen values violated: {bad}")
    rule = mn.load_rule()
    exe = executable_identity()
    dplan = check_directory_plan()
    problems += dplan["problems"]
    if dplan["existing"]:
        problems.append(f"campaign directories already exist: {dplan['existing']}")
    feas = read_json(FEASIBILITY_SUMMARY)
    if feas.get("decision") != "GO":
        problems.append(f"the feasibility gate is {feas.get('decision')}")
    if sha256_file(ma.OBS_TABLE_FILE) != OBS_TABLE_SHA256:
        problems.append("the start-state table differs from its registration")
    ma.load_anchor()
    from btt_rewards import REWARD_V2

    man = {
        "schema": MANIFEST_SCHEMA, "milestone": MILESTONE, "campaign": CAMPAIGN, "created_utc": utc_now(),
        "authority": {"design": ec.repo_relative(DESIGN_DOC), "design_sha256": sha256_file(DESIGN_DOC),
                      "approval": "user, 2026-09-26: implement the campaign, run one capped integration pilot and the "
                                  "six campaign runs if every launch and integrity gate passes; no pause between them"},
        "question": rule["question"],
        "arms": {"E": "m7m_e_s{0,1,2}: anchored backward starts from the registered anchor, p0 = 1/2",
                 "K": "m7m_k_s{0,1,2}: matched control, the same machinery, tick-0 starts only"},
        "order": [s.name for s in matrix()],
        "sequencing": "pilot E then K; then strictly sequential E0, K0, E1, K1, E2, K2, the launch gate before each",
        "registered_settings": registered_settings(),
        "reward_contract": {"contract": "btt_reward_v2", "canonical_sha256": canonical_sha256(REWARD_V2.to_json()),
                            "json": REWARD_V2.to_json()},
        "evidence": {
            "anchor": {"path": ec.repo_relative(ma.ANCHOR_FILE), "sha256": sha256_file(ma.ANCHOR_FILE),
                       "source": f"{ma.ANCHOR_SOURCE_RUN} {ma.ANCHOR_EPISODE_ID}",
                       "discovered_under": ma.ANCHOR_SOURCE_REWARD, "native_action_digest": ma.ANCHOR_NATIVE_DIGEST},
            "start_state_table": {"path": ec.repo_relative(ma.OBS_TABLE_FILE), "sha256": OBS_TABLE_SHA256,
                                  "note": "durable evidence: kept in docs, never discarded (it can be regenerated by F1, "
                                          "which is not a reason to drop it)"},
            "feasibility_plan": {"path": ec.repo_relative(PLAN_DOC), "sha256": sha256_file(PLAN_DOC)},
            "feasibility_result": {"path": ec.repo_relative(FEASIBILITY_SUMMARY),
                                   "sha256": sha256_file(FEASIBILITY_SUMMARY), "decision": feas.get("decision"),
                                   "doc": ec.repo_relative(FEASIBILITY_DOC), "doc_sha256": sha256_file(FEASIBILITY_DOC),
                                   "classification": "feasibility evidence only (never a training input or a result)"},
            "m7l_preserved": {ec.repo_relative(p): sha256_file(p) for p in M7L_EVIDENCE if p.is_file()},
        },
        "executable": {"path": ec.repo_relative(Path(exe.get("path") or "")) if exe.get("path") else None,
                       "sha256": exe.get("sha256"), "size": exe.get("size")},
        "revisions": revisions(), "code": code_fingerprint(),
        "decision_rule": {"path": ec.repo_relative(RULE_DOC), "sha256": rule["_sha256"], "schema": rule["schema"]},
        "warm_starts": warm, "runs": runs, "pairs": pairs, "pilot": pilot,
        "evaluation_protocol": {"plan": {s.name: evaluation_plan(s, load_run(s)) for s in matrix()},
                                "census": census_plan(),
                                "tick0_check": "rl/m7h_verify.verify_eval_tick0 on every label",
                                "clear_verification": "every native clear in evaluation (m7g_k_run.verify_clears_in) and "
                                                      "in training (exact artifact replay from tick 0)",
                                "warm_start_reference": "the Phase K final evaluations runs/m7g_k/_eval/m7g_s{j}_v1/final "
                                                        "(read only; reported as the common starting point)"},
        "directory_plan": dplan,
        "limits": {"runs": len(matrix()), "transitions": len(matrix()) * ADDITIONAL,
                   "pilot_transitions": len(pilot_matrix()) * PILOT_TRANSITIONS, "max_game_processes": MAX_GAME_PROCESSES,
                   "extension": "none", "extra_seeds": "none", "reward_changes": "none"},
        "problems": problems, "ok": not problems,
    }
    return man
