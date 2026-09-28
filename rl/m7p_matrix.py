"""M7p campaign matrix: the runs, the registered settings, the matched control (the M7n v3 runs), the evaluation plan,
the offline measurement plan, the directories and the manifest. Reads only; the driver is rl/m7p_campaign.py.

Arms (rule docs/rl_geometry_scale_m7p_decision_rule.json):
    exp  m7p_geo4_s{0,1,2}: btt_policy_obs_v3_geo4 (= v3 with only the segment_geometry block scaled by 1/4) + btt_reward_v2,
         fresh untrained models, 3,072,000 policy transitions each; order s0, s1, s2
    ctl  the M7n v3 runs runs/m7n/campaign/m7n_s{0,1,2}_v3 (same profiles except contracts.observation), reused only while
         the R1 reproduction check AND the record verification pass on the frozen campaign code and executable

Everything the campaign writes lives below runs/m7p/campaign (redirectable for tests); runs/m7n, runs/m7p/diag and every
other run tree are read only. Adapted from rl/m7o_matrix.py (the exploration table replaced by the observation contract).
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import experiment_config as ec
import m7e_matrix as em
import m7h_guard as g
import m7h_matrix as hm
import m7l_matrix as lm
import m7n_crossing as xc
import m7n_obs as mn
import m7n_policy as mnp
import m7n_status_table as st
import m7p_analysis as pa
import m7p_obs_geo4 as mg

REPO_ROOT = ec.REPO_ROOT
MILESTONE = "M7p"
CAMPAIGN = "geometry_scale_geo4_v1"
MANIFEST_SCHEMA = "battleship_m7p_campaign_manifest_v1"
CONFIG_DIR = REPO_ROOT / "rl" / "configs" / "m7p"
M7N_CONFIG_DIR = REPO_ROOT / "rl" / "configs" / "m7n"
MANIFEST_DOC = REPO_ROOT / "docs" / "rl_geometry_scale_m7p_manifest.json"
RULE_DOC = pa.RULE_DOC
HANDOFF_DOC = REPO_ROOT / "docs" / "rl_geometry_scale_m7p_handoff.md"
DIAG_REGISTRATION = REPO_ROOT / "docs" / "rl_geometry_scale_diag_registration.json"
DIAG_DECISION = REPO_ROOT / "docs" / "rl_geometry_scale_diag_decision.json"
DIAG_REPORT_DOC = REPO_ROOT / "docs" / "rl_geometry_scale_diag_2026-09-28.md"
DIAG_ROOT = REPO_ROOT / "runs" / "m7p" / "diag"
INVESTIGATION_DOC = REPO_ROOT / "docs" / "rl_v3_saturation_investigation_2026-09-28.md"
DEFAULT_ROOT = REPO_ROOT / "runs" / "m7p" / "campaign"
CONTROL_CHECK = DEFAULT_ROOT / "_control" / "control_check.json"
CONTROL_VERIFY = DEFAULT_ROOT / "_control" / "control_verify.json"
M7N_ROOT = REPO_ROOT / "runs" / "m7n" / "campaign"
M7N_ANALYSIS = M7N_ROOT / "_matrix" / "analysis_n3.json"
RUNS = REPO_ROOT / "runs"
MAX_GAME_PROCESSES = hm.MAX_GAME_PROCESSES

SEEDS: Tuple[int, ...] = (0, 1, 2)
ORDER: Tuple[int, ...] = (0, 1, 2)
TOTAL_TRANSITIONS = em.TOTAL_TRANSITIONS          # 3,072,000
CHECKPOINT_INTERVAL = em.CHECKPOINT_INTERVAL      # 102,400
HORIZON = em.HORIZON
PROCESS_COUNT = em.PROCESS_COUNT
FINAL_EPISODES = dict(em.FINAL_EPISODES)
CURVE_EPISODES = dict(em.CURVE_EPISODES)
EVAL_SEED = em.EVAL_SEED
M6_FLAGS = dict(hm.M6_FLAGS)
V3_FLAGS = dict(M6_FLAGS, **dict(mn.ENTITY_EXTRA_ENV))      # identical for geo4 (same two read-only diagnostics)
DIAG_FLAG = dict(hm.EVAL_METRICS_FLAG)
PERIODIC_EPISODES = 10
LAUNCH_GATE_READINGS, LAUNCH_GATE_RETRY_S = lm.LAUNCH_GATE_READINGS, lm.LAUNCH_GATE_RETRY_S
EXPECTED_VALUE_DIFF = ["contracts.observation", "run.name", "run.notes", "run.output_root"]
EXPECTED_COMPAT_DIFF = ["contracts.observation"]
# the offline measurement plan (supporting diagnostics, never gating): the fixed sample of the geo4 diagnostic
SAMPLE_SOURCES = [REPO_ROOT / "runs" / "m7n" / "feasibility" / "prefix" / "traces" / "907d762b.json.gz",
                  REPO_ROOT / "runs" / "m7n" / "feasibility" / "prefix" / "traces" / "e404fde0.json.gz"] + \
                 [REPO_ROOT / "runs" / "probes" / "action_hold" / "episodes" / "k01" / f"ep{i:03d}.json.gz" for i in range(8)]

read_json = hm.read_json
write_json = hm.write_json
sha256_file = hm.sha256_file
within = hm.within
canonical_sha256 = lm.canonical_sha256


class MatrixError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# -- roots ------------------------------------------------------------------------------------------------------------

_ROOT = DEFAULT_ROOT


def configure_root(root: Optional[Path]) -> Path:
    global _ROOT
    _ROOT = Path(root).resolve() if root is not None else DEFAULT_ROOT
    return _ROOT


def root() -> Path:
    return _ROOT


def state_dir() -> Path:
    return _ROOT / "_matrix"


def eval_root() -> Path:
    return _ROOT / "_eval"


def clears_root() -> Path:
    return _ROOT / "_clears"


def partial_root() -> Path:
    return _ROOT / "_partial"


def guard_root() -> Path:
    return _ROOT / "_guard"


def control_check_path() -> Path:
    return _ROOT / "_control" / "control_check.json"


def control_verify_path() -> Path:
    return _ROOT / "_control" / "control_verify.json"


# -- runs -------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunSpec:
    seed: int
    order_index: int
    arm: str = "exp"

    @property
    def name(self) -> str:
        return f"m7p_geo4_s{self.seed}"

    @property
    def config_path(self) -> Path:
        return CONFIG_DIR / f"{self.name}.toml"

    @property
    def run_dir(self) -> Path:
        return _ROOT / self.name

    @property
    def eval_dir(self) -> Path:
        return eval_root() / self.name

    @property
    def clears_dir(self) -> Path:
        return clears_root() / self.name


@dataclass(frozen=True)
class ControlRun:
    """The matched control: the M7n v3 run of the seed (read only)."""

    seed: int

    @property
    def name(self) -> str:
        return f"m7n_s{self.seed}_v3"

    @property
    def run_dir(self) -> Path:
        return M7N_ROOT / self.name

    @property
    def eval_dir(self) -> Path:
        return M7N_ROOT / "_eval" / self.name

    @property
    def clears_dir(self) -> Path:
        return M7N_ROOT / "_clears" / self.name

    @property
    def config_path(self) -> Path:
        return M7N_CONFIG_DIR / f"{self.name}.toml"


def matrix() -> List[RunSpec]:
    return [RunSpec(s, i) for i, s in enumerate(ORDER, 1)]


def run_by_name(name: str) -> RunSpec:
    for s in matrix():
        if s.name == name:
            return s
    raise MatrixError(f"{name!r} is not an M7p campaign run")


def load_run(spec: RunSpec) -> ec.Experiment:
    exp = ec.load_experiment(spec.config_path)
    if _ROOT != DEFAULT_ROOT:
        exp = exp.with_overrides({"run.output_root": str(spec.run_dir.parent)})
    return exp


# -- identity and checks -----------------------------------------------------------------------------------------------


def arm_checks(spec: RunSpec, exp: ec.Experiment) -> Dict[str, bool]:
    from btt_rewards import REWARD_V2

    v = exp.values
    ident = exp.policy_observation() or {}
    return {
        "name": exp.name == spec.name,
        "seed": v["run.base_seed"] == spec.seed,
        "mode_train_fresh": exp.mode == "train" and exp.resume_source is None,
        "observation_geo4": v["contracts.observation"] == mg.OBS_CONTRACT and ident.get("contract") == mg.OBS_CONTRACT
        and ident.get("contract_sha256") == mg.contract_digest() and ident.get("flat_size") == mg.FLAT_SIZE
        and ident.get("derived_from") == mn.OBS_CONTRACT and ident.get("derived_from_sha256") == mn.contract_digest(),
        "action_class_table": ident.get("action_class_table_sha256") == st.load_table()["sha256"],
        "policy": v["ppo.policy"] == mnp.POLICY and ident.get("network_id") == mnp.NETWORK_ID,
        "native_flags": dict(exp.extra_env) == V3_FLAGS,
        "no_exploration": exp.exploration is None,
        "task": v["task.id"] == "ssb64_us_mario_btt_v1",
        "action_contract": v["contracts.action"] == "btt_s9_b8_v1",
        "reward_v2": exp.reward.contract == "btt_reward_v2" and exp.reward.canonical and exp.reward.to_json() == REWARD_V2.to_json(),
        "no_normalisation": (v["ppo.vecnormalize.normalize_observations"], v["ppo.vecnormalize.normalize_rewards"]) == (False, False),
        "process_count_5_standby": exp.process_count == PROCESS_COUNT and exp.standby_preboot and exp.standby_count == 1
        and exp.max_game_processes == MAX_GAME_PROCESSES,
        "horizon": v["environment.horizon"] == HORIZON,
        "budget": v["run.total_transitions"] == TOTAL_TRANSITIONS,
        "rollout_geometry": (v["ppo.rollout_size"], v["ppo.n_steps"], v["ppo.batch_size"], v["ppo.n_epochs"]) == (5120, 1024, 512, 10),
        "ppo": (v["ppo.learning_rate"], v["ppo.gamma"], v["ppo.gae_lambda"], v["ppo.clip_range"], v["ppo.ent_coef"], v["ppo.vf_coef"],
                v["ppo.max_grad_norm"]) == (3e-4, 0.999, 0.995, 0.2, 0.0, 0.5, 0.5),
        "network": (list(v["ppo.net_arch"]), v["ppo.activation"]) == (list(mnp.NET_ARCH), mnp.ACTIVATION),
        "no_in_process_evaluation": (v["evaluation.interval"], v["evaluation.initial"], v["evaluation.final"]) == (0, False, False),
        "checkpoint_cadence": (v["checkpoint.interval"], v["checkpoint.initial"]) == (CHECKPOINT_INTERVAL, True),
        "no_curriculum": exp.curriculum is None and exp.anchor_curriculum is None,
        "run_dir": exp.run_dir == spec.run_dir,
        "no_fixture_or_tas_path": not hm._forbidden_in(spec.config_path.read_text(encoding="utf-8")),
    }


def m7n_proof(spec: RunSpec, exp: ec.Experiment) -> Dict[str, Any]:
    """The profile against the M7n v3 profile of its seed: the compatibility keys differ exactly in contracts.observation, the
    value differences are exactly the observation plus name / notes / output root, flags and reward equal, fingerprints differ."""
    base = ec.load_experiment(ControlRun(spec.seed).config_path)
    diff = sorted(ec.compare_compatibility(exp.compatibility_view(), base.compatibility_view()))
    va, vb = exp.values, base.values
    values = sorted(k for k in set(va) | set(vb) if va.get(k) != vb.get(k))
    ok = diff == EXPECTED_COMPAT_DIFF and values == EXPECTED_VALUE_DIFF and dict(base.extra_env) == V3_FLAGS and dict(exp.extra_env) == V3_FLAGS \
        and exp.reward.to_json() == base.reward.to_json() and exp.semantic_fingerprint != base.semantic_fingerprint \
        and exp.compatibility_fingerprint != base.compatibility_fingerprint \
        and vb["contracts.observation"] == mn.OBS_CONTRACT and va["contracts.observation"] == mg.OBS_CONTRACT
    return {"base": ec.repo_relative(ControlRun(spec.seed).config_path), "compatibility_key_differences": diff,
            "expected_compatibility_key_differences": EXPECTED_COMPAT_DIFF, "value_differences": values,
            "expected_value_differences": EXPECTED_VALUE_DIFF, "same_reward": exp.reward.to_json() == base.reward.to_json(), "ok": ok}


def code_files() -> List[Path]:
    files = sorted(p for p in (REPO_ROOT / "rl").glob("*.py") if not p.name.endswith(("_tests.py", "_smoke.py")))
    files += sorted((REPO_ROOT / "rl" / "data").glob("*.json"))
    files += sorted(CONFIG_DIR.rglob("*.toml")) + [ControlRun(s).config_path for s in SEEDS] + [RULE_DOC]
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


def control_check_fingerprint() -> Dict[str, Any]:
    import m7p_control_check as cc

    return cc.code_fingerprint()


def revisions() -> Dict[str, Any]:
    return lm.revisions()


def executable_identity() -> Dict[str, Any]:
    return load_run(matrix()[0]).executable_fingerprint()


def expected_initial_digests(exp: ec.Experiment) -> Tuple[str, str]:
    import m7n_pilot as npi

    return npi.fresh_digests(exp)


def observation_identity() -> Dict[str, Any]:
    table = st.load_table()
    return {"experimental": {"contract": mg.OBS_CONTRACT, "contract_sha256": mg.contract_digest(), "flat_size": mg.FLAT_SIZE,
                             "only_change": {"key": mg.CHANGED_KEY, "length_columns": list(mg.CHANGED_LENGTH_COLUMNS),
                                             "length_scale": [mn.LENGTH_SCALE, mg.SEGMENT_LENGTH_SCALE],
                                             "velocity_columns": list(mg.CHANGED_VELOCITY_COLUMNS),
                                             "velocity_scale": [mn.VELOCITY_SCALE, mg.SEGMENT_VELOCITY_SCALE], "factor": mg.GEOMETRY_SCALE_FACTOR},
                             "derived_from": mn.OBS_CONTRACT, "derived_from_sha256": mn.contract_digest()},
            "control": {"contract": mn.OBS_CONTRACT, "contract_sha256": mn.contract_digest(), "flat_size": mn.FLAT_SIZE},
            "network_id": mnp.NETWORK_ID, "policy": mnp.POLICY, "action_class_table_sha256": table["sha256"],
            "native_flags": dict(mn.ENTITY_EXTRA_ENV), "selected_default": mn.OBS_CONTRACT}


def diagnostic_identity() -> Dict[str, Any]:
    """The geo4 diagnostic that made this comparison eligible (read only; nothing of it is reused by the campaign)."""
    out: Dict[str, Any] = {}
    for key, p in (("registration", DIAG_REGISTRATION), ("decision", DIAG_DECISION), ("report_doc", DIAG_REPORT_DOC),
                   ("investigation_doc", INVESTIGATION_DOC), ("run_report", DIAG_ROOT / "diag_report.json"), ("analysis", DIAG_ROOT / "analysis.json")):
        out[key] = {"path": ec.repo_relative(p) if p.is_file() else None, "sha256": sha256_file(p) if p.is_file() else None}
    if DIAG_DECISION.is_file():
        out["outcome"] = (read_json(DIAG_DECISION).get("decision") or {}).get("outcome")
    out["never_reused"] = "no campaign run loads the diagnostic's checkpoint, optimizer state or statistics; every run starts from the fresh construction"
    return out


def measurement_plan() -> Dict[str, Any]:
    pts = em.evaluated_points()
    return {"purpose": "supporting diagnostics only; never gating; never used to select checkpoints or alter training",
            "sample": {"sources": [{"path": ec.repo_relative(p), "sha256": sha256_file(p) if p.is_file() else None} for p in SAMPLE_SOURCES],
                       "states": 33997, "population_A": "the two M7n final-episode traces (policy play; 6,578 states)",
                       "population_B": "eight action-hold-probe k = 1 episodes (random play; 27,419 states)",
                       "rebuild": "exact 606-value inputs rebuilt from the raw replies under EACH arm's own contract (v3 for the control, geo4 for "
                                  "the experimental arm); nothing scaled is fed to the other arm's network"},
            "checkpoints": {"labels": ["initial"] + [f"curve_t{t:09d}" for t in pts if t not in (0, TOTAL_TRANSITIONS)] + ["final"],
                            "num_timesteps": pts, "arms": "both"},
            "measurements": ["actor and critic layer 1: sat95 (abs tanh > 0.95), sat99, mean derivative 1 - h^2, units saturated in > 90 % of "
                             "states, of which stuck at one sign, two-sided, effectively constant (std < 0.05); on the whole sample and separately "
                             "on populations A and B; layer 2 sat95",
                             "recorded pairs (identical indices in both arms): target break pairs (43) vs consecutive no-break controls (3,000): "
                             "median abs dV, median KL, hidden distances; up-B early-vs-late (587) vs early-vs-early controls (800); jump-squat "
                             "tic 0 vs 2 (140) vs tic 0 vs 0 (174)", "block ablation KL: agent, targets, segment_geometry zeroed",
                             "policy entropy on the sample; first-layer weight norms; per-interval weight-row change"],
            "procedure": "rl/m7p_measure.py (the functions of rl/m7p_geo4_diag.py) after training and evaluation are verified; read only",
            "reading": "a persisting saturation reduction with retained margins is reported as such; it is not a success and selects nothing"}


def control_identity(seed: int) -> Dict[str, Any]:
    """What the control seed is, byte for byte (hashes only; the verifiers ran in rl/m7p_control_verify.py)."""
    import m7d_run as dr

    c = ControlRun(seed)
    out: Dict[str, Any] = {"run": c.name, "run_dir": ec.repo_relative(c.run_dir), "eval_dir": ec.repo_relative(c.eval_dir)}
    problems: List[str] = []
    for name, p in (("final_checkpoint_json_sha256", c.run_dir / "final" / "checkpoint.json"),
                    ("rows_sha256", c.run_dir / "metrics" / "episodes.jsonl"),
                    ("rollouts_sha256", c.run_dir / "metrics" / "rollouts.jsonl"),
                    ("crossing_doc_sha256", c.clears_dir / "final" / "crossing_verification.json")):
        out[name] = sha256_file(p) if p.is_file() else None
        if out[name] is None:
            problems.append(f"{ec.repo_relative(p)} missing")
    try:
        out["final_digests"] = list(dr.checkpoint_digests(c.run_dir / "final"))
        out["initial_digests"] = list(dr.checkpoint_digests(c.run_dir / "checkpoints" / "ckpt_000000000"))
        out["curve_checkpoint_digests"] = {f"ckpt_{t:09d}": list(dr.checkpoint_digests(c.run_dir / "checkpoints" / f"ckpt_{t:09d}"))
                                           for t in em.evaluated_points() if t not in (0, TOTAL_TRANSITIONS)}
    except Exception as exc:  # noqa: BLE001
        problems.append(f"checkpoint sets: {exc}")
    files = {}
    for label in ["final", "initial"] + [f"curve_t{t:09d}" for t in em.evaluated_points() if t not in (0, TOTAL_TRANSITIONS)]:
        for mode in ("stochastic", "deterministic"):
            f = c.eval_dir / label / mode / "evaluation.json"
            files[f"{label}/{mode}"] = sha256_file(f) if f.is_file() else None
            if files[f"{label}/{mode}"] is None:
                problems.append(f"{ec.repo_relative(f)} missing")
    out["evaluation_sha256"] = files
    if M7N_ANALYSIS.is_file():
        an = read_json(M7N_ANALYSIS)
        out["m7n_inputs"] = {"final": an["per_seed"][str(seed)]["v3"]["stochastic"], "initial": an["per_seed"][str(seed)]["v3_initial"]["stochastic"],
                             "X": an["per_seed"][str(seed)]["v3"]["X"]}
    else:
        problems.append("the M7n analysis record is missing")
    out["problems"] = problems
    out["ok"] = not problems
    return out


def current_identity() -> Dict[str, Any]:
    profiles = {}
    for s in matrix():
        e = load_run(s)
        profiles[s.name] = (e.source.sha256, e.semantic_fingerprint, e.compatibility_fingerprint)
    return {"executable_sha256": executable_identity().get("sha256"), "revisions": revisions(),
            "code_sha256": code_fingerprint()["sha256"], "control_code_sha256": control_check_fingerprint()["sha256"],
            "rule_sha256": sha256_file(RULE_DOC), "observation_sha256": mg.contract_digest(), "v3_sha256": mn.contract_digest(),
            "table_sha256": st.load_table()["sha256"],
            "sample_sha256": canonical_sha256([sha256_file(p) if p.is_file() else None for p in SAMPLE_SOURCES]), "profiles": profiles}


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
        p.append("the Python code, rl/data, an M7p / M7n profile or the rule changed since the manifest")
    if cur["control_code_sha256"] != (manifest.get("code") or {}).get("control_check_sha256"):
        p.append("the control-check code fingerprint changed since the manifest")
    if cur["rule_sha256"] != (manifest.get("decision_rule") or {}).get("sha256"):
        p.append("the decision rule differs from the manifest")
    obs = manifest.get("observation") or {}
    if cur["observation_sha256"] != (obs.get("experimental") or {}).get("contract_sha256") or cur["v3_sha256"] != (obs.get("control") or {}).get("contract_sha256") \
            or cur["table_sha256"] != obs.get("action_class_table_sha256"):
        p.append("an observation contract or the action-class table differs from the manifest")
    if cur["sample_sha256"] != (manifest.get("measurement_plan") or {}).get("sample_sha256"):
        p.append("the fixed observation sample changed since the manifest")
    for name, triple in cur["profiles"].items():
        r = (manifest.get("runs") or {}).get(name)
        if r is None or (r["source_sha256"], r["semantic_fingerprint"], r["compatibility_fingerprint"]) != tuple(triple):
            p.append(f"{name}: profile source / fingerprints differ from the manifest")
    return p


def changed_files(manifest: Mapping[str, Any]) -> List[str]:
    before, now = (manifest.get("code") or {}).get("per_file") or {}, code_fingerprint()["per_file"]
    return sorted(k for k in set(before) | set(now) if before.get(k) != now.get(k))


# -- evaluation plan and census -----------------------------------------------------------------------------------------


def evaluation_plan(spec: RunSpec, exp: ec.Experiment) -> List[Dict[str, Any]]:
    """The M7n protocol (Phase K post hoc), tick-0 starts only, every checkpoint under its own observation contract (geo4)."""
    v = exp.values
    total = int(v["run.total_transitions"])
    if total != TOTAL_TRANSITIONS:
        raise MatrixError(f"{spec.name}: total_transitions {total}")
    common = {"seed": int(v["evaluation.seed"]), "workers": exp.eval_workers, "horizon": int(v["environment.horizon"]),
              "extra_env": dict(exp.extra_env, **DIAG_FLAG), "standby_preboot": exp.standby_preboot, "standby_count": exp.standby_count,
              "frozen_vecnormalize": True, "preserve_all": True, "eval_metrics": True, "observation": mg.OBS_CONTRACT,
              "reward_contract": exp.reward.contract, "starts": "tick0_only", "run": spec.name, "arm": spec.arm}
    plan = [dict(common, label="initial", checkpoint=f"{spec.name}/checkpoints/ckpt_000000000", num_timesteps=0,
                 deterministic_episodes=FINAL_EPISODES["deterministic"], stochastic_episodes=FINAL_EPISODES["stochastic"])]
    for t in em.evaluated_points():
        if t in (0, total):
            continue
        plan.append(dict(common, label=f"curve_t{t:09d}", checkpoint=f"{spec.name}/checkpoints/ckpt_{t:09d}", num_timesteps=t,
                         deterministic_episodes=CURVE_EPISODES["deterministic"], stochastic_episodes=CURVE_EPISODES["stochastic"]))
    plan.append(dict(common, label="final", checkpoint=f"{spec.name}/final", num_timesteps=total,
                     deterministic_episodes=FINAL_EPISODES["deterministic"], stochastic_episodes=FINAL_EPISODES["stochastic"]))
    return plan


def census_plan() -> Dict[str, Any]:
    per = em.evaluation_census_plan()["per_seed"]
    runs = len(matrix())
    return {"runs": runs, "per_run": per, "episodes": runs * per, "arithmetic": f"{runs} runs x {per} = {runs * per}",
            "labels_per_run": len(em.evaluated_points()), "control_reused": True}


# -- directories ---------------------------------------------------------------------------------------------------------


def planned_directories() -> Dict[str, Path]:
    d: Dict[str, Path] = {"root": _ROOT, "state": state_dir(), "eval_root": eval_root(), "clears_root": clears_root(),
                          "partial": partial_root(), "guard": guard_root(), "control": _ROOT / "_control"}
    for s in matrix():
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
    leaves = sorted((k, v) for k, v in norm.items() if k.split(":")[0] in ("run", "eval", "clears") or k in ("state", "partial", "guard", "control"))
    for i, (ka, pa_) in enumerate(leaves):
        for kb, pb in leaves[i + 1:]:
            if within(pa_, pb) or within(pb, pa_):
                p.append(f"{ka} and {kb} overlap")
    r = norm["root"]
    for k, v in norm.items():
        if not within(v, r):
            p.append(f"{k} lies outside the campaign root")
    protected = [hm.HISTORICAL, RUNS / "m7e", RUNS / "m7h", RUNS / "m7k", RUNS / "m7j", RUNS / "m7l", RUNS / "m7m", RUNS / "m7g",
                 RUNS / "m7f", RUNS / "m7d", RUNS / "m7n", RUNS / "m7o", DIAG_ROOT, RUNS / "probes"]
    for h in protected:
        if within(r, h) or within(h, r):
            p.append(f"the campaign root overlaps {ec.repo_relative(h)}")
    for s in matrix():
        exp = load_run(s)
        if exp.run_dir != s.run_dir or exp.name != s.name:
            p.append(f"{s.name}: profile resolves to {exp.name} / {exp.run_dir}")
    existing = sorted(k for k, v in norm.items() if k.split(":")[0] in ("run", "eval", "clears") and v.exists())
    return {"root": ec.repo_relative(r), "planned": len(dirs), "existing": existing, "problems": p, "ok": not p}


# -- control records (read only) ---------------------------------------------------------------------------------------------


def control_check_record() -> Optional[Dict[str, Any]]:
    return read_json(control_check_path()) if control_check_path().is_file() else None


def control_verify_record() -> Optional[Dict[str, Any]]:
    return read_json(control_verify_path()) if control_verify_path().is_file() else None


# -- the manifest ----------------------------------------------------------------------------------------------------------


def registered_settings() -> Dict[str, Any]:
    from dataclasses import asdict

    return {
        "observation": {"exp": mg.OBS_CONTRACT, "ctl": mn.OBS_CONTRACT, "only_difference": "segment_geometry block scaled by 1/4 (lengths / 8,000, "
                        "velocities / 200); every other key, flag and rule identical; each checkpoint evaluated under its own contract"},
        "reward": {"both_arms": "btt_reward_v2 (frozen values); no exploration credit, no curriculum"},
        "launch_gate": {"available_commit_gib_min": g.LAUNCH_COMMIT_GIB, "available_physical_gib_min": g.LAUNCH_PHYSICAL_GIB,
                        "free_disk_gib_min": g.LAUNCH_DISK_GIB, "system_cpu_pct_max": g.LAUNCH_MAX_CPU_PCT, "when": "before every training launch",
                        "readings": f"a failed reading is re-measured after {LAUNCH_GATE_RETRY_S:.0f} s, at most {LAUNCH_GATE_READINGS} readings"},
        "in_run_memory_policy": dict(asdict(g.REGISTERED_POLICY), watches="available system commit only"),
        "monitor": "m7d Monitor: hard alerts stop the run (a row violating its btt_reward_v2 closed form, more than 10 game processes or listeners "
                   "in two samples, a changed user config, low disk)",
        "budget": {"policy_transitions_per_run": TOTAL_TRANSITIONS, "hard_maximum": True, "runs": len(matrix())},
        "stop_conditions": ["a failed launch gate", "a monitor hard alert", "the in-run memory policy", "a provenance mismatch", "a process leak",
                            "a training verification failure", "a manifest drift", "a failed control check or record verification"],
        "after_a_stop": "the campaign stops and reports; a stopped run is moved to _partial and preserved; nothing is fixed or relaunched by this driver",
        "evaluation": "post hoc, frozen parameters, tick-0 starts only (the M7n protocol), btt_eval_metrics_v1, the checkpoint's own observation "
                      "contract, clear verification, crossing verification (btt_qualified_crossing_v1), census",
        "measurement": "offline supporting diagnostics after evaluation (measurement_plan); read only; never gating",
        "training_inputs": "tick-0 episodes of the run itself only; never fixtures, TAS, traces, recordings, the diagnostic checkpoint, other runs",
        "initialisation": "fresh models only: ckpt_000000000 must equal the fresh construction AND the M7n run's initial set of the seed; nothing "
                          "loaded from the geo4 diagnostic",
        "never": "native RNG state is never inspected, logged, validated, controlled, compared or hashed",
    }


def build_manifest(*, with_digests: bool = True) -> Dict[str, Any]:
    problems: List[str] = []
    runs: Dict[str, Any] = {}
    control = {str(s): control_identity(s) for s in SEEDS}
    for s, h in control.items():
        if not h["ok"]:
            problems.append(f"control seed {s}: {h['problems'][:3]}")
    for s in matrix():
        exp = load_run(s)
        checks = arm_checks(s, exp)
        proof = m7n_proof(s, exp)
        bad = [k for k, ok in checks.items() if not ok]
        if bad:
            problems.append(f"{s.name}: identity / frozen values violated: {bad}")
        if not proof["ok"]:
            problems.append(f"{s.name} vs M7n v3: {proof}")
        r = {"seed": s.seed, "arm": s.arm, "order": s.order_index, "config": ec.repo_relative(s.config_path),
             "source_sha256": exp.source.sha256, "semantic_fingerprint": exp.semantic_fingerprint,
             "compatibility_fingerprint": exp.compatibility_fingerprint, "reward": exp.reward.to_json(), "observation": exp.values["contracts.observation"],
             "extra_env": dict(exp.extra_env), "run_dir": ec.repo_relative(s.run_dir), "eval_dir": ec.repo_relative(s.eval_dir),
             "control": ControlRun(s.seed).name, "checks": checks, "m7n_proof": proof}
        if with_digests:
            pol, obs = expected_initial_digests(exp)
            r["expected_initial_policy_digest"], r["expected_initial_obs_rms_digest"] = pol, obs
            ci = control[str(s.seed)].get("initial_digests")
            if ci and [pol, obs] != ci:
                problems.append(f"{s.name}: fresh construction {pol[:12]}/{obs[:12]} != the M7n initial set {ci}")
        runs[s.name] = r
    rule = pa.load_rule()
    exe = executable_identity()
    dplan = check_directory_plan()
    problems += dplan["problems"]
    if dplan["existing"]:
        problems.append(f"campaign directories already exist: {dplan['existing']}")
    plans = {s.name: evaluation_plan(s, load_run(s)) for s in matrix()}
    from btt_rewards import REWARD_V2

    code = code_fingerprint()
    ccode = control_check_fingerprint()
    code["control_check_sha256"] = ccode["sha256"]
    code["control_check_files"] = ccode["files"]
    cc, cv = control_check_record(), control_verify_record()
    bound_cc = bool(cc and cc.get("ok") and (cc.get("code") or {}).get("sha256") == ccode["sha256"] and cc.get("executable_sha256") == exe.get("sha256"))
    bound_cv = bool(cv and cv.get("ok") and cv.get("rule_sha256") == rule["_sha256"])
    control_status = {"check_record": ec.repo_relative(control_check_path()) if cc else None, "check_sha256": sha256_file(control_check_path()) if cc else None,
                      "check_ok": bool(cc and cc.get("ok")), "check_code_sha256": (cc or {}).get("code", {}).get("sha256"),
                      "check_executable_sha256": (cc or {}).get("executable_sha256"),
                      "verify_record": ec.repo_relative(control_verify_path()) if cv else None, "verify_sha256": sha256_file(control_verify_path()) if cv else None,
                      "verify_ok": bool(cv and cv.get("ok")), "verify_rule_sha256": (cv or {}).get("rule_sha256"),
                      "bound_to_this_manifest": bound_cc and bound_cv,
                      "required": "a PASSED R1 record on code.control_check_sha256 and executable.sha256 AND a PASSED record verification on this rule; "
                                  "otherwise train is blocked; replacement controls are never trained by this driver"}
    diag = diagnostic_identity()
    if diag.get("outcome") != "diagnostic_pass":
        problems.append(f"the geo4 diagnostic decision is {diag.get('outcome')!r}, not diagnostic_pass")
    mp = measurement_plan()
    mp["sample_sha256"] = canonical_sha256([s["sha256"] for s in mp["sample"]["sources"]])
    if any(s["sha256"] is None for s in mp["sample"]["sources"]):
        problems.append("a fixed-sample source file is missing")
    man = {
        "schema": MANIFEST_SCHEMA, "milestone": MILESTONE, "campaign": CAMPAIGN, "created_utc": utc_now(),
        "authority": {"diagnostic": ec.repo_relative(DIAG_REPORT_DOC), "investigation": ec.repo_relative(INVESTIGATION_DOC),
                      "approval": "APPROVED 2026-09-28 by the user (repository owner), in the Claude Code session: one bounded three-seed comparison "
                                  "of btt_policy_obs_v3_geo4 against the matched M7n v3 controls, after final registration and verification "
                                  "(frozen manifest, profiles and rule; all-three-seed control compatibility on the final code; the M7n 10/11 "
                                  "unit result resolved; the offline sample and measurement procedure pinned). No further approval between "
                                  "preparation, passing preflight and launch. Stop after the registered three-seed decision. Original v3 stays "
                                  "selected until the registered comparison decides otherwise.",
                      "approval_record": "the user's message of 2026-09-28 (quoted in docs/rl_geometry_scale_m7p_handoff.md); no separate approval file"},
        "question": rule["question"], "only_difference": rule["only_difference"],
        "arms": {"exp": f"m7p_geo4_s{{0,1,2}}: fresh models, {mg.OBS_CONTRACT} + btt_reward_v2",
                 "ctl": "runs/m7n/campaign/m7n_s{0,1,2}_v3 (the M7n v3 runs), reused only while the R1 reproduction and the record verification pass"},
        "order": [s.name for s in matrix()], "sequencing": "strictly sequential, one run at a time, s0, s1, s2; the launch gate before each",
        "registered_settings": registered_settings(), "observation": observation_identity(), "diagnostic": diag, "measurement_plan": mp,
        "reward_contract": {"canonical_sha256": canonical_sha256(REWARD_V2.to_json()), "json": REWARD_V2.to_json()},
        "executable": {"path": ec.repo_relative(Path(exe.get("path") or "")) if exe.get("path") else None, "sha256": exe.get("sha256"), "size": exe.get("size")},
        "revisions": revisions(), "code": code,
        "decision_rule": {"path": ec.repo_relative(RULE_DOC), "sha256": rule["_sha256"], "schema": rule["schema"]},
        "runs": runs,
        "control": {"seeds": control, "status": control_status,
                    "procedure": "rl/m7p_control_check.py (R1: 3 x 102,400 fresh M7n-profile runs vs the M7n ckpt_000102400 digests and rows) + "
                                 "rl/m7p_control_verify.py (identity, evaluation verifiers, clear / crossing candidates, rule inputs vs the M7n analysis); "
                                 "rerun whenever the control-check fingerprint, the executable or the rule changes"},
        "evaluation_protocol": {"plan": plans, "census": census_plan(), "tick0_check": "rl/m7h_verify.verify_eval_tick0 on every label",
                                "metrics_check": "rl/m7g_k_run.verify_metrics on every label", "clear_verification": "rl/m7g_k_run.verify_clears_in",
                                "crossing_verification": f"rl/m7n_crossing.verify_crossings_in ({xc.CRITERION}) on the experimental finals; the control's "
                                                         "M7n documents re-verified by crossing_inputs",
                                "own_contract": "every checkpoint is evaluated under the observation contract recorded in its checkpoint.json (geo4 for "
                                                "the experimental arm); the evaluator refuses any other",
                                "inputs": "rl/m7l_analysis.label_inputs on both arms' finals and the experimental initials; rl/m7n_crossing.crossing_inputs"},
        "directory_plan": dplan,
        "limits": {"runs": len(matrix()), "transitions": len(matrix()) * TOTAL_TRANSITIONS, "max_game_processes": MAX_GAME_PROCESSES,
                   "extension": "none", "extra_seeds": "none", "scale_tuning": "none", "relaunch_after_stop": "none"},
        "not_evidence_of_success": rule["not_evidence_of_success"],
        "selection": rule["selection"],
        "problems": problems, "ok": not problems,
    }
    return man
