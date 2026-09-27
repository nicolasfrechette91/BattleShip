"""M7n campaign matrix: the runs, their order, the registered settings, the historical control, the evaluation plan,
the directories and the manifest. Reads only; the driver is rl/m7n_campaign.py.

Arms (proposal docs/rl_observation_v3_proposal_m7n.md; rule docs/rl_observation_v3_m7n_decision_rule.json):
    v3  m7n_s{0,1,2}_v3: btt_policy_obs_v3_entities + btt_reward_v2 + Track 1, fresh untrained models,
        3,072,000 policy transitions each; order s0, s1, s2
    v1  the historical Phase K runs runs/m7g_k/m7g_s{0,1,2}_v1 (btt_policy_obs_v1, btt_reward_v2), reused only while
        the control reproduction check passes on the frozen campaign code and executable; a failed check stops the
        campaign (never a retrain branch)

Everything the campaign writes lives below runs/m7n/campaign (redirectable for tests); the historical control, the
pilot trees and every other run tree are read only.
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
import m7e_matrix as em
import m7h_guard as g
import m7h_matrix as hm
import m7l_matrix as lm
import m7n_analysis as na
import m7n_crossing as xc
import m7n_obs as mn
import m7n_policy as mnp
import m7n_status_table as st

REPO_ROOT = ec.REPO_ROOT
MILESTONE = "M7n"
CAMPAIGN = "observation_v3_entities_v1"
MANIFEST_SCHEMA = "battleship_m7n_campaign_manifest_v1"
CONFIG_DIR = REPO_ROOT / "rl" / "configs" / "m7n"
PHASE_K_CONFIG_DIR = REPO_ROOT / "rl" / "configs" / "m7g"
R1_PROFILES = list(lm.R1_PROFILES)
MANIFEST_DOC = REPO_ROOT / "docs" / "rl_observation_v3_m7n_manifest.json"
RULE_DOC = na.RULE_DOC
PROPOSAL_DOC = REPO_ROOT / "docs" / "rl_observation_v3_proposal_m7n.md"
IMPLEMENTATION_DOC = REPO_ROOT / "docs" / "rl_observation_v3_m7n_implementation.md"
PILOT_REGISTRATION = REPO_ROOT / "docs" / "rl_observation_v3_m7n_pilot_registration.json"
PILOT_REPORT = REPO_ROOT / "runs" / "m7n" / "pilot" / "pilot_report.json"
CONTROL_RECORD = REPO_ROOT / "runs" / "m7n" / "_control" / "control_check.json"
APPROVAL_DOC = REPO_ROOT / "docs" / "rl_observation_v3_m7n_approval.json"
APPROVAL_SCHEMA = "m7n_launch_approval_v1"
DEFAULT_ROOT = REPO_ROOT / "runs" / "m7n" / "campaign"
HISTORICAL = hm.HISTORICAL
M7E_RUNS = REPO_ROOT / "runs" / "m7e"
RUNS = REPO_ROOT / "runs"
MAX_GAME_PROCESSES = hm.MAX_GAME_PROCESSES

SEEDS: Tuple[int, ...] = (0, 1, 2)
ORDER: Tuple[int, ...] = (0, 1, 2)
TOTAL_TRANSITIONS = em.TOTAL_TRANSITIONS          # 3,072,000 policy transitions, hard maximum per run
CHECKPOINT_INTERVAL = em.CHECKPOINT_INTERVAL      # 102,400
HORIZON = em.HORIZON                              # 3,600
PROCESS_COUNT = em.PROCESS_COUNT                  # 5
FINAL_EPISODES = dict(em.FINAL_EPISODES)          # 100 + 100 at initial and final
CURVE_EPISODES = dict(em.CURVE_EPISODES)          # 5 + 60 at each intermediate point
EVAL_SEED = em.EVAL_SEED
M6_FLAGS = dict(hm.M6_FLAGS)
V3_FLAGS = dict(M6_FLAGS, **dict(mn.ENTITY_EXTRA_ENV))    # + SSB64_RL_SPATIAL=1 + SSB64_RL_ENTITY=1 (read-only)
DIAG_FLAG = dict(hm.EVAL_METRICS_FLAG)                     # SSB64_RL_TARGET_DIAG=1: evaluation metrics only
PERIODIC_EPISODES = 10
LAUNCH_GATE_READINGS, LAUNCH_GATE_RETRY_S = lm.LAUNCH_GATE_READINGS, lm.LAUNCH_GATE_RETRY_S
EXPECTED_COMPAT_DIFF = ["contracts.observation", "environment.extra_env", "ppo.policy",
                        "ppo.vecnormalize.normalize_observations"]
EXPECTED_VALUE_DIFF = ["contracts.observation", "ppo.policy", "ppo.vecnormalize.normalize_observations", "run.name",
                       "run.notes", "run.output_root"]


class MatrixError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


read_json = hm.read_json
write_json = hm.write_json
sha256_file = hm.sha256_file
within = hm.within
canonical_sha256 = lm.canonical_sha256
HistoricalControl = hm.HistoricalControl
historical_identity = lm.historical_identity     # the same reproduced control, read only

# -- roots (redirectable for tests) --------------------------------------------------------------------------------

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


# -- runs ------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunSpec:
    seed: int
    order_index: int
    arm: str = "v3"
    curriculum: bool = False
    pilot: bool = False

    @property
    def name(self) -> str:
        return f"m7n_s{self.seed}_v3"

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


def matrix() -> List[RunSpec]:
    return [RunSpec(s, i) for i, s in enumerate(ORDER, 1)]


def run_by_name(name: str) -> RunSpec:
    for s in matrix():
        if s.name == name:
            return s
    raise MatrixError(f"{name!r} is not an M7n campaign run")


def load_run(spec: RunSpec) -> ec.Experiment:
    exp = ec.load_experiment(spec.config_path)
    if _ROOT != DEFAULT_ROOT:
        exp = exp.with_overrides({"run.output_root": str(spec.run_dir.parent)})
    return exp


def phase_k_profile(seed: int) -> Path:
    return PHASE_K_CONFIG_DIR / f"m7g_s{seed}_v1.toml"


# -- identity and checks ---------------------------------------------------------------------------------------------


def arm_checks(spec: RunSpec, exp: ec.Experiment) -> Dict[str, bool]:
    from btt_rewards import REWARD_V2

    v = exp.values
    ident = exp.policy_observation() or {}
    return {
        "name": exp.name == spec.name,
        "seed": v["run.base_seed"] == spec.seed,
        "mode_train_fresh": exp.mode == "train" and exp.resume_source is None,
        "observation_v3": v["contracts.observation"] == mn.OBS_CONTRACT and ident.get("contract") == mn.OBS_CONTRACT
        and ident.get("contract_sha256") == mn.contract_digest() and ident.get("flat_size") == mn.FLAT_SIZE,
        "action_class_table": ident.get("action_class_table_sha256") == st.load_table()["sha256"],
        "policy": v["ppo.policy"] == mnp.POLICY and ident.get("network_id") == mnp.NETWORK_ID,
        "native_flags": dict(exp.extra_env) == V3_FLAGS,
        "network": (v["ppo.net_arch"], v["ppo.activation"]) == (list(mnp.NET_ARCH), mnp.ACTIVATION),
        "task": v["task.id"] == "ssb64_us_mario_btt_v1",
        "action_contract": v["contracts.action"] == "btt_s9_b8_v1",
        "reward_v2": exp.reward.contract == "btt_reward_v2" and exp.reward.canonical
        and exp.reward.to_json() == REWARD_V2.to_json(),
        "reward_values": (v["reward.target_broken"], v["reward.per_step"], v["reward.clear_bonus"],
                          v["reward.failure_penalty"]) == (1.0, -0.001, 10.0, -5.0),
        "no_normalisation": (v["ppo.vecnormalize.normalize_observations"],
                             v["ppo.vecnormalize.normalize_rewards"]) == (False, False),
        "process_count_5_standby": exp.process_count == PROCESS_COUNT and exp.standby_preboot and exp.standby_count == 1
        and exp.max_game_processes == MAX_GAME_PROCESSES,
        "horizon": v["environment.horizon"] == HORIZON,
        "budget": v["run.total_transitions"] == TOTAL_TRANSITIONS,
        "rollout_geometry": (v["ppo.rollout_size"], v["ppo.n_steps"], v["ppo.batch_size"], v["ppo.n_epochs"])
        == (5120, 1024, 512, 10),
        "ppo": (v["ppo.learning_rate"], v["ppo.gamma"], v["ppo.gae_lambda"], v["ppo.clip_range"], v["ppo.ent_coef"],
                v["ppo.vf_coef"], v["ppo.max_grad_norm"]) == (3e-4, 0.999, 0.995, 0.2, 0.0, 0.5, 0.5),
        "cpu_one_thread": (v["ppo.device"], v["ppo.torch_threads"]) == ("cpu", 1),
        "no_in_process_evaluation": (v["evaluation.interval"], v["evaluation.initial"], v["evaluation.final"])
        == (0, False, False),
        "checkpoint_cadence": (v["checkpoint.interval"], v["checkpoint.initial"]) == (CHECKPOINT_INTERVAL, True),
        "evaluation_protocol": (v["evaluation.deterministic_episodes"], v["evaluation.stochastic_episodes"],
                                v["evaluation.seed"]) == (CURVE_EPISODES["deterministic"],
                                                          CURVE_EPISODES["stochastic"], EVAL_SEED),
        "artifacts_as_control": v["artifacts.periodic_episodes"] == PERIODIC_EPISODES,
        "no_curriculum": exp.curriculum is None and exp.anchor_curriculum is None,
        "run_dir": exp.run_dir == spec.run_dir,
        "no_fixture_or_tas_path": not hm._forbidden_in(spec.config_path.read_text(encoding="utf-8")),
    }


def phase_k_proof(spec: RunSpec, exp: ec.Experiment) -> Dict[str, Any]:
    """The profile against the Phase K v1 profile of its seed: the compatibility views differ exactly in the
    observation contract, the policy class it requires, the observation normalisation switch and the derived native
    flags (the registered single change: the observation package)."""
    base = ec.load_experiment(phase_k_profile(spec.seed))
    diff = sorted(ec.compare_compatibility(exp.compatibility_view(), base.compatibility_view()))
    va, vb = exp.values, base.values
    values = sorted(k for k in set(va) | set(vb) if va.get(k) != vb.get(k))
    ok = diff == EXPECTED_COMPAT_DIFF and values == EXPECTED_VALUE_DIFF and dict(base.extra_env) == M6_FLAGS \
        and dict(exp.extra_env) == V3_FLAGS and exp.reward.to_json() == base.reward.to_json()
    return {"base": ec.repo_relative(phase_k_profile(spec.seed)), "compatibility_differences": diff,
            "expected_compatibility_differences": EXPECTED_COMPAT_DIFF, "value_differences": values,
            "expected_value_differences": EXPECTED_VALUE_DIFF, "same_reward": exp.reward.to_json() == base.reward.to_json(),
            "ok": ok}


def code_files() -> List[Path]:
    """Every non-test rl/*.py module, rl/data, the M7n profiles (campaign and pilot), the Phase K control profiles,
    the R1 profiles and the decision rule."""
    files = sorted(p for p in (REPO_ROOT / "rl").glob("*.py") if not p.name.endswith(("_tests.py", "_smoke.py")))
    files += sorted((REPO_ROOT / "rl" / "data").glob("*.json"))
    files += sorted(CONFIG_DIR.rglob("*.toml")) + [phase_k_profile(s) for s in SEEDS] + list(R1_PROFILES)
    files += [na.RULE_DOC_V1, RULE_DOC]        # the superseded v1 rule (byte-preserved) and the corrected v2 rule
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
    """The fingerprint rl/m7n_control_check.py records (its own file set); the manifest pins both."""
    import m7n_control_check as cc

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
    return {"contract": mn.OBS_CONTRACT, "schema_version": mn.OBS_SCHEMA_VERSION, "contract_sha256": mn.contract_digest(),
            "flat_size": mn.FLAT_SIZE, "key_order": list(mn.KEY_ORDER), "shapes": {k: list(v) for k, v in mn.SHAPES.items()},
            "network_id": mnp.NETWORK_ID, "policy": mnp.POLICY, "normalization": "fixed scaling; VecNormalize norm_obs False",
            "action_class_table": table["table_id"], "action_class_table_sha256": table["sha256"],
            "validated_characters": list(st.VALIDATED), "native_flags": dict(mn.ENTITY_EXTRA_ENV),
            "schema_doc": ec.repo_relative(REPO_ROOT / "docs" / "rl_observation_v3_m7n.schema.json")}


def current_identity() -> Dict[str, Any]:
    profiles = {}
    for s in matrix():
        e = load_run(s)
        profiles[s.name] = (e.source.sha256, e.semantic_fingerprint, e.compatibility_fingerprint)
    return {"executable_sha256": executable_identity().get("sha256"), "revisions": revisions(),
            "code_sha256": code_fingerprint()["sha256"], "control_code_sha256": control_check_fingerprint()["sha256"],
            "rule_sha256": sha256_file(RULE_DOC), "observation_sha256": mn.contract_digest(),
            "table_sha256": st.load_table()["sha256"], "profiles": profiles}


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
        p.append("the Python code, rl/data, an M7n / control / R1 profile or the decision rule changed since the manifest")
    if cur["control_code_sha256"] != (manifest.get("code") or {}).get("control_check_sha256"):
        p.append("the control-check code fingerprint changed since the manifest")
    if cur["rule_sha256"] != (manifest.get("decision_rule") or {}).get("sha256"):
        p.append("the decision rule differs from the manifest")
    appr = (manifest.get("authority") or {}).get("approval_record")
    if appr:
        if not APPROVAL_DOC.is_file() or sha256_file(APPROVAL_DOC) != appr.get("sha256"):
            p.append("the approval record differs from the manifest or is missing")
    elif APPROVAL_DOC.is_file():
        p.append("an approval record exists but the manifest pins none: rebuild the manifest")
    obs = manifest.get("observation") or {}
    if cur["observation_sha256"] != obs.get("contract_sha256") or cur["table_sha256"] != obs.get("action_class_table_sha256"):
        p.append("the observation contract or the action-class table differs from the manifest")
    for name, triple in cur["profiles"].items():
        r = (manifest.get("runs") or {}).get(name)
        if r is None or (r["source_sha256"], r["semantic_fingerprint"], r["compatibility_fingerprint"]) != tuple(triple):
            p.append(f"{name}: profile source / fingerprints differ from the manifest")
    return p


def changed_files(manifest: Mapping[str, Any]) -> List[str]:
    before, now = (manifest.get("code") or {}).get("per_file") or {}, code_fingerprint()["per_file"]
    return sorted(k for k in set(before) | set(now) if before.get(k) != now.get(k))


# -- evaluation plan and census --------------------------------------------------------------------------------------


def evaluation_plan(spec: RunSpec, exp: ec.Experiment) -> List[Dict[str, Any]]:
    """The Phase K post-hoc protocol, tick-0 starts only: initial, every 307,200 transitions, final; 100 + 100 at
    initial and final, 5 deterministic + 60 stochastic in between; seed 12345; frozen parameters; every episode
    preserved; the evaluation-only metrics recorder on; the checkpoint's own observation (v3 flags added)."""
    v = exp.values
    total = int(v["run.total_transitions"])
    if total != TOTAL_TRANSITIONS:
        raise MatrixError(f"{spec.name}: total_transitions {total}")
    common = {"seed": int(v["evaluation.seed"]), "workers": exp.eval_workers, "horizon": int(v["environment.horizon"]),
              "extra_env": dict(exp.extra_env, **DIAG_FLAG), "standby_preboot": exp.standby_preboot,
              "standby_count": exp.standby_count, "frozen_vecnormalize": True, "preserve_all": True,
              "eval_metrics": True, "observation": mn.OBS_CONTRACT, "reward_contract": exp.reward.contract,
              "starts": "tick0_only", "run": spec.name, "arm": spec.arm}
    plan = [dict(common, label="initial", checkpoint=f"{spec.name}/checkpoints/ckpt_000000000", num_timesteps=0,
                 deterministic_episodes=FINAL_EPISODES["deterministic"], stochastic_episodes=FINAL_EPISODES["stochastic"])]
    for t in em.evaluated_points(total)[1:-1]:
        plan.append(dict(common, label=f"curve_t{t:09d}", checkpoint=f"{spec.name}/checkpoints/ckpt_{t:09d}",
                         num_timesteps=t, deterministic_episodes=CURVE_EPISODES["deterministic"],
                         stochastic_episodes=CURVE_EPISODES["stochastic"]))
    plan.append(dict(common, label="final", checkpoint=f"{spec.name}/final", num_timesteps=total,
                     deterministic_episodes=FINAL_EPISODES["deterministic"], stochastic_episodes=FINAL_EPISODES["stochastic"]))
    return plan


def census_plan() -> Dict[str, Any]:
    per = em.evaluation_census_plan()["per_seed"]                     # 985 = 740 stochastic + 245 deterministic
    runs = len(matrix())
    return {"runs": runs, "per_run": per, "episodes": runs * per, "arithmetic": f"{runs} runs x {per} = {runs * per}",
            "labels_per_run": len(em.evaluated_points()), "historical_control_reused": True}


# -- directories -----------------------------------------------------------------------------------------------------


def planned_directories() -> Dict[str, Path]:
    d: Dict[str, Path] = {"root": _ROOT, "state": state_dir(), "eval_root": eval_root(), "clears_root": clears_root(),
                          "partial": partial_root(), "guard": guard_root()}
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
    leaves = sorted((k, v) for k, v in norm.items() if k.split(":")[0] in ("run", "eval", "clears")
                    or k in ("state", "partial", "guard"))
    for i, (ka, pa) in enumerate(leaves):
        for kb, pb in leaves[i + 1:]:
            if within(pa, pb) or within(pb, pa):
                p.append(f"{ka} and {kb} overlap")
    r = norm["root"]
    for k, v in norm.items():
        if not within(v, r):
            p.append(f"{k} lies outside the campaign root")
    protected = [HISTORICAL, M7E_RUNS, RUNS / "m7h", RUNS / "m7k", RUNS / "m7j", RUNS / "m7l", RUNS / "m7m",
                 RUNS / "m7g", RUNS / "m7f", RUNS / "m7d", RUNS / "m7n" / "pilot", RUNS / "m7n" / "_control",
                 RUNS / "m7n" / "_equiv"]
    for h in protected:
        if within(r, h) or within(h, r):
            p.append(f"the campaign root overlaps {ec.repo_relative(h)}")
    for s in matrix():
        exp = load_run(s)
        if exp.run_dir != s.run_dir or exp.name != s.name:
            p.append(f"{s.name}: profile resolves to {exp.name} / {exp.run_dir}")
    existing = sorted(k for k, v in norm.items() if k.split(":")[0] in ("run", "eval", "clears") and v.exists())
    return {"root": ec.repo_relative(r), "planned": len(dirs), "existing": existing, "problems": p, "ok": not p}


# -- the pilot and control records (read only) -------------------------------------------------------------------------


def pilot_identity() -> Dict[str, Any]:
    """The registered pilot (attempt 3) and the preserved earlier attempts: what ran, what was consumed, what passed.
    Nothing of any attempt initialises a campaign run (every campaign model is fresh; verified by the untrained-set
    digest)."""
    out: Dict[str, Any] = {"registration": None, "report": None, "attempts": []}
    if PILOT_REGISTRATION.is_file():
        reg = read_json(PILOT_REGISTRATION)
        out["registration"] = {"path": ec.repo_relative(PILOT_REGISTRATION), "sha256": sha256_file(PILOT_REGISTRATION),
                               "cap_transitions": reg.get("cap_transitions"), "code_sha256": reg["identity"]["code"]["sha256"],
                               "executable_sha256": reg["identity"]["executable_sha256"]}
    if PILOT_REPORT.is_file():
        rep = read_json(PILOT_REPORT)
        out["report"] = {"path": ec.repo_relative(PILOT_REPORT), "sha256": sha256_file(PILOT_REPORT), "status": rep.get("status"),
                         "ok": rep.get("ok"), "problems": rep.get("problems")}
    for label, d, regp in (("attempt1", RUNS / "m7n" / "pilot_attempt1_failed",
                            REPO_ROOT / "docs" / "rl_observation_v3_m7n_pilot_registration_attempt1.json"),
                           ("attempt2", RUNS / "m7n" / "pilot_attempt2_verifier_defect",
                            REPO_ROOT / "docs" / "rl_observation_v3_m7n_pilot_registration_attempt2.json"),
                           ("attempt3_registered", RUNS / "m7n" / "pilot", PILOT_REGISTRATION)):
        summ = d / "m7n_pilot_s0" / "training_summary.json"
        rec: Dict[str, Any] = {"attempt": label, "dir": ec.repo_relative(d), "exists": d.is_dir()}
        if summ.is_file():
            s = read_json(summ)
            rec.update(status=s.get("status"), transitions=(s.get("timesteps") or {}).get("sb3_num_timesteps"),
                       n_updates=(s.get("timesteps") or {}).get("n_updates"), rollouts=(s.get("timesteps") or {}).get("rollouts"),
                       learn_s=(s.get("wall") or {}).get("learn_s"), leak_free=(s.get("cleanup") or {}).get("leak_free"))
        if regp.is_file():
            rec["registration_code_sha256"] = read_json(regp)["identity"]["code"]["sha256"]
        out["attempts"].append(rec)
    return out


def control_record() -> Optional[Dict[str, Any]]:
    return read_json(CONTROL_RECORD) if CONTROL_RECORD.is_file() else None


def approval_record() -> Optional[Dict[str, Any]]:
    return read_json(APPROVAL_DOC) if APPROVAL_DOC.is_file() else None


def approval_status(rule_sha: str) -> Dict[str, Any]:
    """The supported authorisation mechanism: docs/rl_observation_v3_m7n_approval.json (schema m7n_launch_approval_v1),
    written at the user's instruction, approving exactly one rule digest, observation contract and executable. The
    manifest pins the record's sha256 (manifest_drift checks it) and `train` refuses unless the status is APPROVED
    and the pinned record is unchanged. Anything else leaves the launch PENDING."""
    rec = approval_record()
    if rec is None:
        return {"approval": f"PENDING: no approval record ({ec.repo_relative(APPROVAL_DOC)})", "record": None,
                "problems": ["no approval record"]}
    ap = rec.get("applies_to") or {}
    p: List[str] = []
    if rec.get("schema") != APPROVAL_SCHEMA:
        p.append(f"schema {rec.get('schema')!r}")
    if rec.get("approved") is not True:
        p.append("approved is not true")
    if ap.get("rule_sha256") != rule_sha:
        p.append(f"the record approves rule {str(ap.get('rule_sha256'))[:12]}, the rule is {str(rule_sha)[:12]}")
    if ap.get("rule_path") != ec.repo_relative(RULE_DOC):
        p.append(f"the record names rule path {ap.get('rule_path')!r}")
    if ap.get("observation_contract_sha256") != mn.contract_digest():
        p.append("the record names another observation contract")
    if ap.get("executable_sha256") != executable_identity().get("sha256"):
        p.append("the record names another executable")
    record = {"path": ec.repo_relative(APPROVAL_DOC), "sha256": sha256_file(APPROVAL_DOC), "schema": rec.get("schema"),
              "approved_utc": rec.get("approved_utc"), "approved_by": rec.get("approved_by"),
              "rule_sha256": ap.get("rule_sha256")}
    if p:
        return {"approval": "PENDING: the approval record does not apply: " + "; ".join(p), "record": record, "problems": p}
    return {"approval": f"APPROVED {rec.get('approved_utc')} by {rec.get('approved_by')} (record {record['sha256'][:12]}, "
                        f"rule {rule_sha[:12]})", "record": record, "problems": []}


# -- the manifest ----------------------------------------------------------------------------------------------------


def registered_settings() -> Dict[str, Any]:
    from dataclasses import asdict

    return {
        "observation": {"experimental": mn.OBS_CONTRACT, "control": "btt_policy_obs_v1",
                        "unchanged": ["btt_policy_obs_v1", "btt_policy_obs_v2_spatial"]},
        "reward": {"both_arms": "btt_reward_v2 (frozen values)"},
        "launch_gate": {"available_commit_gib_min": g.LAUNCH_COMMIT_GIB, "available_physical_gib_min": g.LAUNCH_PHYSICAL_GIB,
                        "free_disk_gib_min": g.LAUNCH_DISK_GIB, "system_cpu_pct_max": g.LAUNCH_MAX_CPU_PCT,
                        "boundaries": "inclusive; a missing reading fails; commit and physical evaluated separately",
                        "when": "before every training launch",
                        "readings": f"a failed reading is re-measured after {LAUNCH_GATE_RETRY_S:.0f} s, at most "
                                    f"{LAUNCH_GATE_READINGS} readings; the run launches only on a passing reading"},
        "in_run_memory_policy": dict(asdict(g.REGISTERED_POLICY), watches="available system commit only",
                                     physical="recorded and reported, never a stop trigger"),
        "monitor": "m7d Monitor: hard alerts stop the run (a row that violates its btt_reward_v2 closed form, more than 10 "
                   "game processes or listeners in two samples, a changed user config, low disk)",
        "budget": {"policy_transitions_per_run": TOTAL_TRANSITIONS, "hard_maximum": True, "runs": len(matrix())},
        "stop_conditions": ["a failed launch gate", "a monitor hard alert", "the in-run memory policy (a resource stop)",
                            "a provenance mismatch", "a process leak", "a training verification failure", "a manifest drift",
                            "a failed control reproduction check"],
        "after_a_stop": "the campaign stops and reports; a stopped run directory is moved to _partial by the guard and "
                        "preserved (never deleted, never resumed); nothing is relaunched by this driver",
        "evaluation": "post hoc, frozen parameters, tick-0 starts only (Phase K protocol), btt_eval_metrics_v1 with "
                      "SSB64_RL_TARGET_DIAG=1, clear verification of every native clear, census",
        "training_inputs": "tick-0 episodes of the run itself only; never the crossing fixtures, the TAS, feasibility "
                           "traces, capture recordings, pilot checkpoints, other runs or hand-written routes",
        "initialisation": "fresh models only: ckpt_000000000 must equal the fresh construction from the profile (policy "
                          "and statistics digests); no pilot checkpoint, optimizer state or normalisation state is loaded",
        "never": "native RNG state is never inspected, logged, validated, controlled, compared or hashed",
    }


def build_manifest(*, with_digests: bool = True) -> Dict[str, Any]:
    problems: List[str] = []
    runs: Dict[str, Any] = {}
    control = {str(s): historical_identity(s) for s in SEEDS}
    for s, h in control.items():
        if not h["ok"]:
            problems.append(f"historical control seed {s}: {h['problems'][:3]}")
    for s in matrix():
        exp = load_run(s)
        checks = arm_checks(s, exp)
        proof = phase_k_proof(s, exp)
        bad = [k for k, ok in checks.items() if not ok]
        if bad:
            problems.append(f"{s.name}: identity / frozen values violated: {bad}")
        if not proof["ok"]:
            problems.append(f"{s.name} vs Phase K v1: {proof}")
        r = {"seed": s.seed, "arm": s.arm, "order": s.order_index, "config": ec.repo_relative(s.config_path),
             "source_sha256": exp.source.sha256, "semantic_fingerprint": exp.semantic_fingerprint,
             "compatibility_fingerprint": exp.compatibility_fingerprint, "reward": exp.reward.to_json(),
             "extra_env": dict(exp.extra_env), "run_dir": ec.repo_relative(s.run_dir),
             "eval_dir": ec.repo_relative(s.eval_dir), "control": HistoricalControl(s.seed).name,
             "checks": checks, "phase_k_proof": proof}
        if with_digests:
            pol, obs = expected_initial_digests(exp)
            r["expected_initial_policy_digest"], r["expected_initial_obs_rms_digest"] = pol, obs
        runs[s.name] = r
    rule = na.load_rule()
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
    rec = control_record()
    control_status = {"record": ec.repo_relative(CONTROL_RECORD) if rec else None,
                      "record_sha256": sha256_file(CONTROL_RECORD) if rec else None,
                      "ok": bool(rec and rec.get("ok")), "code_sha256": rec.get("code", {}).get("sha256") if rec else None,
                      "executable_sha256": rec.get("executable_sha256") if rec else None,
                      "r4_gate2_inputs_ok": bool(rec and (rec.get("r4") or {}).get("ok")),
                      "bound_to_this_manifest": bool(rec and rec.get("ok") and rec.get("code", {}).get("sha256") == ccode["sha256"]
                                                     and rec.get("executable_sha256") == exe.get("sha256")
                                                     and (rec.get("r4") or {}).get("ok")),
                      "required": "a PASSED record (R1-R4) whose code fingerprint equals code.control_check_sha256 and whose "
                                  "executable equals executable.sha256; otherwise train is blocked"}
    r4 = ((rec or {}).get("r4") or {})
    gate2 = {"criterion": xc.CRITERION, "source": "R4 of the control check (historical finals and the R2 re-evaluation, "
                                                 "identical candidate sets, every candidate replayed); repeated by the "
                                                 "campaign's verify-crossings and cross-checked at analysis",
             "per_seed": {s: {k: v.get(k) for k in ("candidates", "exact", "qualified_crossings",
                                                     "verified_left_target_episodes", "unqualified_left_entries", "X")}
                          for s, v in (r4.get("per_seed") or {}).items()},
             "registered": (rule.get("known_control_values_gate2") or {})}
    appr = approval_status(rule["_sha256"])
    pilot = pilot_identity()
    if not (pilot.get("report") or {}).get("ok"):
        problems.append("the registered integration pilot has not passed")
    man = {
        "schema": MANIFEST_SCHEMA, "milestone": MILESTONE, "campaign": CAMPAIGN, "created_utc": utc_now(),
        "authority": {"proposal": ec.repo_relative(PROPOSAL_DOC), "implementation": ec.repo_relative(IMPLEMENTATION_DOC),
                      "approval": appr["approval"], "approval_record": appr["record"],
                      "mechanism": f"{ec.repo_relative(APPROVAL_DOC)} ({APPROVAL_SCHEMA}) naming this rule's sha256, this "
                                   "observation contract and this executable; pinned here by sha256, checked by manifest_drift; "
                                   "train refuses unless approval starts with APPROVED and the pinned record is unchanged"},
        "question": rule["question"], "not_isolated": rule["not_isolated"],
        "arms": {"v3": f"m7n_s{{0,1,2}}_v3: fresh models, {mn.OBS_CONTRACT}, otherwise the Phase K v1 profile of the seed "
                       "(reward v2, PPO, N = 5 standby, 3,072,000 transitions)",
                 "v1": "historical runs/m7g_k/m7g_s{0,1,2}_v1 (btt_policy_obs_v1), reused only while the reproduction "
                       "check passes; never replaced by new runs by this driver"},
        "only_experimental_change": "the observation package (contract, policy class, normalisation switch and the two "
                                    "read-only native flags it derives); see phase_k_proof per run",
        "order": [s.name for s in matrix()],
        "sequencing": "strictly sequential, one run at a time, s0, s1, s2; the launch gate before each",
        "registered_settings": registered_settings(),
        "observation": observation_identity(),
        "reward_contract": {"canonical_sha256": canonical_sha256(REWARD_V2.to_json()), "json": REWARD_V2.to_json()},
        "executable": {"path": ec.repo_relative(Path(exe.get("path") or "")) if exe.get("path") else None,
                       "sha256": exe.get("sha256"), "size": exe.get("size")},
        "revisions": revisions(), "code": code,
        "decision_rule": {"path": ec.repo_relative(RULE_DOC), "sha256": rule["_sha256"], "schema": rule["schema"],
                          "supersedes": {"path": ec.repo_relative(na.RULE_DOC_V1), "sha256": sha256_file(na.RULE_DOC_V1),
                                         "schema": "m7n_decision_rule_v1", "preserved": "byte-identical; never used"}},
        "runs": runs,
        "historical_control": {"seeds": control, "control_check": control_status, "gate2_inputs": gate2,
                               "procedure": "rl/m7n_control_check.py: R1 (3 x 102,400 curriculum-off reward-v2 runs vs the "
                                            "pinned Phase K = M7e ckpt_000102400 digests and rows), R2 (600 historical "
                                            "final evaluation episodes), R3 (decision inputs), R4 (corrected gate-2 inputs: "
                                            "crossing candidates of the control finals, replayed); rerun whenever the "
                                            "control-check fingerprint or the executable changes"},
        "pilot": pilot,
        "evaluation_protocol": {"plan": plans, "census": census_plan(),
                                "tick0_check": "rl/m7h_verify.verify_eval_tick0 on every label",
                                "metrics_check": "rl/m7g_k_run.verify_metrics on every label",
                                "clear_verification": "rl/m7g_k_run.verify_clears_in on every v3 label",
                                "crossing_verification": "rl/m7n_crossing.verify_crossings_in on both arms' final labels "
                                                         f"({xc.CRITERION}); the gate-2 inputs",
                                "inputs": "rl/m7l_analysis.label_inputs on both arms' final labels and v3's initial label"},
        "directory_plan": dplan,
        "limits": {"runs": len(matrix()), "transitions": len(matrix()) * TOTAL_TRANSITIONS,
                   "max_game_processes": MAX_GAME_PROCESSES, "extension": "none", "extra_seeds": "none"},
        "scope_and_limitations": rule["not_claims"],
        "problems": problems, "ok": not problems,
    }
    return man
