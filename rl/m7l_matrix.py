"""M7l campaign matrix: the runs, their order, the registered settings, the historical control, the evaluation plan,
the directories and the manifest. Reads only; the driver is rl/m7l_campaign.py.

Arms (proposal docs/rl_target2_m7k.md section 10; rule docs/rl_target2_m7l_decision_rule.json):
    T   m7l_t2_s{0,1,2}: v1 + btt_reward_v3_t2 + Track 1, fresh untrained models, 3,072,000 policy transitions each;
        order T0, T1, T2
    C   the historical Phase K runs runs/m7g_k/m7g_s{0,1,2}_v1 (btt_reward_v2), reused only while the control check
        passes on the frozen campaign code; there is no retrain branch in this milestone (a failed check stops it)

Everything the campaign writes lives below runs/m7l/campaign (redirectable for tests); the historical control and every
other run tree are read only.
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
import m7l_analysis as la

REPO_ROOT = ec.REPO_ROOT
MILESTONE = "M7l"
CAMPAIGN = "target2_credit_v1"
MANIFEST_SCHEMA = "battleship_m7l_campaign_manifest_v1"
CONFIG_DIR = REPO_ROOT / "rl" / "configs" / "m7l"
PHASE_K_CONFIG_DIR = REPO_ROOT / "rl" / "configs" / "m7g"
R1_PROFILES = [REPO_ROOT / "rl" / "configs" / "m7h" / "gate" / f"m7h_r1_s{s}.toml" for s in (0, 1, 2)]
MANIFEST_DOC = REPO_ROOT / "docs" / "rl_target2_m7l_manifest.json"
RULE_DOC = la.RULE_DOC
PROPOSAL_DOC = REPO_ROOT / "docs" / "rl_target2_m7k.md"
DEFAULT_ROOT = REPO_ROOT / "runs" / "m7l" / "campaign"
HISTORICAL = hm.HISTORICAL                                     # runs/m7g_k (control arm C, read only)
M7E_RUNS = REPO_ROOT / "runs" / "m7e"
RUNS = REPO_ROOT / "runs"
MAX_GAME_PROCESSES = hm.MAX_GAME_PROCESSES                     # 10

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
DIAG_FLAG = dict(hm.EVAL_METRICS_FLAG)            # SSB64_RL_TARGET_DIAG=1: derived from v3_t2 in training, metrics in evaluation
PERIODIC_EPISODES = 10
REWARD_V3_T2_SHA256 = "fa74d7d7edf88936fcb63e1c65cc5751dddc0bc6b1c974a70af232160b9def99"
REWARD_V3_SHA256_PREFIX = "d9447d47"
R1_ROWS = dict(hm.R_CONDITIONS["R1"]["m7e_rows_at_102400"])     # {"0": 30, "1": 27, "2": 29}
LAUNCH_GATE_READINGS = 5                          # a failed reading is re-measured after 60 s, at most 5 readings
LAUNCH_GATE_RETRY_S = 60.0


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


def replays_root() -> Path:
    return _ROOT / "_replays"


def control_root() -> Path:
    return _ROOT / "_control"


def partial_root() -> Path:
    return _ROOT / "_partial"


def guard_root() -> Path:
    return _ROOT / "_guard"


# -- runs ------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunSpec:
    seed: int
    order_index: int
    arm: str = "T"
    curriculum: bool = False     # m7h checkpoint-provenance helpers read it; never a curriculum here

    @property
    def name(self) -> str:
        return f"m7l_t2_s{self.seed}"

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

    @property
    def replays_dir(self) -> Path:
        return replays_root() / self.name


def matrix() -> List[RunSpec]:
    return [RunSpec(s, i) for i, s in enumerate(ORDER, 1)]


def run_by_name(name: str) -> RunSpec:
    for s in matrix():
        if s.name == name:
            return s
    raise MatrixError(f"{name!r} is not an M7l campaign run")


def load_run(spec: RunSpec) -> ec.Experiment:
    exp = ec.load_experiment(spec.config_path)
    if _ROOT != DEFAULT_ROOT:
        exp = exp.with_overrides({"run.output_root": str(spec.run_dir.parent)})
    return exp


def phase_k_profile(seed: int) -> Path:
    return PHASE_K_CONFIG_DIR / f"m7g_s{seed}_v1.toml"


HistoricalControl = hm.HistoricalControl


# -- the historical control (arm C) ----------------------------------------------------------------------------------


def control_rows_at(seed: int, t: int) -> List[Dict[str, Any]]:
    import m7d_run as dr

    rows, _ = dr.jsonl_rows(HistoricalControl(seed).run_dir / "metrics" / "episodes.jsonl")
    return [r for r in rows if int(r.get("sb3_num_timesteps_seen") or 0) <= t]


def historical_identity(seed: int) -> Dict[str, Any]:
    """What arm C seed s is, byte for byte, and its M7l decision inputs: final set, untrained set, the 102,400 set and
    rows (R1's reference), the final evaluation files (R2's reference) and the rule inputs (R3's reference)."""
    import m7d_run as dr

    h = HistoricalControl(seed)
    out: Dict[str, Any] = {"run": h.name, "run_dir": ec.repo_relative(h.run_dir), "eval_dir": ec.repo_relative(h.eval_dir)}
    problems: List[str] = []
    fin = h.run_dir / "final"
    if not (fin / "checkpoint.json").is_file():
        return dict(out, problems=[f"{ec.repo_relative(fin)} missing"], ok=False)
    out["final_checkpoint_json_sha256"] = sha256_file(fin / "checkpoint.json")
    out["final_digests"] = list(dr.checkpoint_digests(fin))
    out["initial_digests"] = list(dr.checkpoint_digests(h.run_dir / "checkpoints" / "ckpt_000000000"))
    out["ckpt_000102400_digests"] = list(dr.checkpoint_digests(h.run_dir / "checkpoints" / "ckpt_000102400"))
    m7e = dr.checkpoint_digests(M7E_RUNS / f"m7e_s{seed}_v2" / "checkpoints" / "ckpt_000102400")
    if tuple(out["ckpt_000102400_digests"]) != tuple(m7e):
        problems.append("Phase K ckpt_000102400 differs from M7e ckpt_000102400 (R1's reference)")
    rows = control_rows_at(seed, 102_400)
    out["rows_at_102400"] = len(rows)
    out["rows_at_102400_sha256"] = canonical_sha256([[r.get(k) for k in hm.R_CONDITIONS["R1"]["row_keys"]] for r in rows])
    if len(rows) != int(R1_ROWS[str(seed)]):
        problems.append(f"{len(rows)} control rows at 102,400 != registered {R1_ROWS[str(seed)]}")
    files = {}
    for mode in ("stochastic", "deterministic"):
        f = h.eval_dir / "final" / mode / "evaluation.json"
        files[mode] = sha256_file(f) if f.is_file() else None
        if files[mode] is None:
            problems.append(f"{ec.repo_relative(f)} missing")
    out["final_evaluation_sha256"] = files
    clear_doc = h.clears_dir / "final" / "clear_verification.json"
    rule = la.load_rule()
    arm, p = la.label_inputs(h.eval_dir / "final", read_json(clear_doc) if clear_doc.is_file() else None, la.params(rule))
    problems += p
    out["decision_inputs"] = arm.to_json()
    known = rule.get("known_control_values") or {}
    got = {"t2": arm.t2, "S": arm.S, "L": arm.L, "R": arm.R, "T_incomplete": str(arm.T), "falls": arm.falls}
    want = {k: (known.get(k) or {}).get(str(seed)) for k in got}
    if got != want:
        problems.append(f"decision inputs {got} != the registered control values {want}")
    pk_state = HISTORICAL / "_matrix" / "state.json"
    status = ((read_json(pk_state).get("runs") or {}).get(h.name) or {}).get("status") if pk_state.is_file() else None
    out["phase_k_status"] = status
    if status != "verified":
        problems.append(f"Phase K status {status}")
    out["problems"] = problems
    out["ok"] = not problems
    return out


# -- identity and checks ---------------------------------------------------------------------------------------------


def arm_checks(spec: RunSpec, exp: ec.Experiment) -> Dict[str, bool]:
    from btt_rewards import REWARD_V3_T2

    v = exp.values
    return {
        "name": exp.name == spec.name,
        "seed": v["run.base_seed"] == spec.seed,
        "mode_train_fresh": exp.mode == "train" and exp.resume_source is None,
        "observation_v1": v["contracts.observation"] == "btt_policy_obs_v1" and exp.policy_observation() is None,
        "policy": v["ppo.policy"] == "MlpPolicy",
        "native_flags": dict(exp.extra_env) == dict(M6_FLAGS, **DIAG_FLAG),
        "network": (v["ppo.net_arch"], v["ppo.activation"]) == ([64, 64], "tanh"),
        "task": v["task.id"] == "ssb64_us_mario_btt_v1",
        "action_contract": v["contracts.action"] == "btt_s9_b8_v1",
        "reward_v3_t2_registered": exp.reward.contract == "btt_reward_v3_t2" and exp.reward.canonical
        and exp.reward.to_json() == REWARD_V3_T2.to_json()
        and canonical_sha256(REWARD_V3_T2.to_json()) == REWARD_V3_T2_SHA256,
        "reward_base_values": (v["reward.target_broken"], v["reward.per_step"], v["reward.clear_bonus"],
                               v["reward.failure_penalty"]) == (1.0, -0.001, 10.0, -5.0),
        "no_reward_normalisation": (v["ppo.vecnormalize.normalize_observations"],
                                    v["ppo.vecnormalize.normalize_rewards"]) == (True, False),
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
        "no_curriculum": exp.curriculum is None,
        "run_dir": exp.run_dir == spec.run_dir,
        "no_fixture_or_tas_path": not hm._forbidden_in(spec.config_path.read_text(encoding="utf-8")),
    }


def phase_k_proof(spec: RunSpec, exp: ec.Experiment) -> Dict[str, Any]:
    """The profile against the Phase K v1 profile of its seed: the compatibility views differ exactly in the reward
    and the reward-derived diagnostic flag (the registered single change)."""
    base = ec.load_experiment(phase_k_profile(spec.seed))
    diff = sorted(ec.compare_compatibility(exp.compatibility_view(), base.compatibility_view()))
    want = ["contracts.reward_resolved", "environment.extra_env"]
    va, vb = exp.values, base.values
    values = sorted(k for k in set(va) | set(vb) if va.get(k) != vb.get(k))
    want_values = ["contracts.reward", "run.name", "run.notes", "run.output_root"]
    flags = dict(exp.extra_env)
    ok = diff == want and values == want_values and dict(base.extra_env) == M6_FLAGS and \
        flags == dict(M6_FLAGS, **DIAG_FLAG)
    return {"base": ec.repo_relative(phase_k_profile(spec.seed)), "compatibility_differences": diff,
            "expected_compatibility_differences": want, "value_differences": values,
            "expected_value_differences": want_values, "ok": ok}


def code_files() -> List[Path]:
    """Every non-test rl/*.py module, the M7l profiles, the Phase K control profiles, the R1 profiles and the rule."""
    files = sorted(p for p in (REPO_ROOT / "rl").glob("*.py") if not p.name.endswith(("_tests.py", "_smoke.py")))
    files += sorted(CONFIG_DIR.rglob("*.toml")) + [phase_k_profile(s) for s in SEEDS] + list(R1_PROFILES) + [RULE_DOC]
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


def expected_initial_digests(exp: ec.Experiment) -> Tuple[str, str]:
    import m7g_k_matrix as km

    return km.expected_initial_digests(exp)


def current_identity() -> Dict[str, Any]:
    profiles = {}
    for s in matrix():
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
        p.append("the Python code, an M7l / control / R1 profile or the decision rule changed since the manifest")
    if cur["rule_sha256"] != (manifest.get("decision_rule") or {}).get("sha256"):
        p.append("the decision rule differs from the manifest")
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
    initial and final, 5 deterministic + 60 stochastic in between; seed 12345; frozen statistics; every episode
    preserved; the evaluation-only metrics recorder on; the checkpoint's own reward contract (v3_t2)."""
    v = exp.values
    total = int(v["run.total_transitions"])
    if total != TOTAL_TRANSITIONS:
        raise MatrixError(f"{spec.name}: total_transitions {total}")
    common = {"seed": int(v["evaluation.seed"]), "workers": exp.eval_workers, "horizon": int(v["environment.horizon"]),
              "extra_env": dict(exp.extra_env, **DIAG_FLAG), "standby_preboot": exp.standby_preboot,
              "standby_count": exp.standby_count, "frozen_vecnormalize": True, "preserve_all": True,
              "eval_metrics": True, "observation": "btt_policy_obs_v1", "reward_contract": exp.reward.contract,
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
                          "replays_root": replays_root(), "control": control_root(), "partial": partial_root(),
                          "guard": guard_root()}
    for s in matrix():
        d[f"run:{s.name}"] = s.run_dir
        d[f"eval:{s.name}"] = s.eval_dir
        d[f"clears:{s.name}"] = s.clears_dir
        d[f"replays:{s.name}"] = s.replays_dir
    for s in SEEDS:
        d[f"replays:{HistoricalControl(s).name}"] = replays_root() / HistoricalControl(s).name
    return d


def check_directory_plan() -> Dict[str, Any]:
    """Unique, pairwise-disjoint leaves, all below the campaign root; the root never inside or around another run tree
    (the historical control, M7e, M7h, M7k, M7j, ...)."""
    dirs = planned_directories()
    p: List[str] = []
    norm = {k: Path(os.path.normpath(str(v))) for k, v in dirs.items()}
    if len(set(norm.values())) != len(norm):
        p.append("two planned directories resolve to the same path")
    leaves = sorted((k, v) for k, v in norm.items() if k.split(":")[0] in ("run", "eval", "clears", "replays")
                    or k in ("state", "control", "partial", "guard"))
    for i, (ka, pa) in enumerate(leaves):
        for kb, pb in leaves[i + 1:]:
            if within(pa, pb) or within(pb, pa):
                p.append(f"{ka} and {kb} overlap")
    r = norm["root"]
    for k, v in norm.items():
        if not within(v, r):
            p.append(f"{k} lies outside the campaign root")
    protected = [HISTORICAL, M7E_RUNS, RUNS / "m7h", RUNS / "m7k", RUNS / "m7j", RUNS / "m7g", RUNS / "m7f", RUNS / "m7d"]
    for h in protected:
        if within(r, h) or within(h, r):
            p.append(f"the campaign root overlaps {ec.repo_relative(h)}")
    for s in matrix():
        exp = load_run(s)
        if exp.run_dir != s.run_dir or exp.name != s.name:
            p.append(f"{s.name}: profile resolves to {exp.name} / {exp.run_dir}")
    existing = sorted(k for k, v in norm.items() if k.split(":")[0] in ("run", "eval", "clears", "replays") and v.exists())
    return {"root": ec.repo_relative(r), "planned": len(dirs), "existing": existing, "problems": p, "ok": not p}


# -- the manifest ----------------------------------------------------------------------------------------------------


def registered_settings() -> Dict[str, Any]:
    from dataclasses import asdict

    return {
        "reward": {"experimental": "btt_reward_v3_t2", "canonical_sha256": REWARD_V3_T2_SHA256,
                   "control": "btt_reward_v2", "unchanged": ["btt_reward_v3 (d9447d47...)", "btt_reward_v2"],
                   "credit": "2.0 * (3600 - n) / 3600 once, on the step that first shows native target ID 2 broken"},
        "launch_gate": {"available_commit_gib_min": g.LAUNCH_COMMIT_GIB, "available_physical_gib_min": g.LAUNCH_PHYSICAL_GIB,
                        "free_disk_gib_min": g.LAUNCH_DISK_GIB, "system_cpu_pct_max": g.LAUNCH_MAX_CPU_PCT,
                        "boundaries": "inclusive; a missing reading fails; commit and physical evaluated separately",
                        "when": "before every training launch (control check R1 and campaign runs)",
                        "readings": f"a failed reading is re-measured after {LAUNCH_GATE_RETRY_S:.0f} s, at most "
                                    f"{LAUNCH_GATE_READINGS} readings; the run launches only on a passing reading; "
                                    f"otherwise the campaign stops"},
        "in_run_memory_policy": dict(asdict(g.REGISTERED_POLICY), watches="available system commit only",
                                     physical="recorded and reported, never a stop trigger"),
        "monitor": "m7d Monitor: hard alerts stop the run (an episode row that violates its btt_reward_v3_t2 closed form, "
                   "more than 10 game processes or listeners in two samples, a changed user config, low disk)",
        "budget": {"policy_transitions_per_run": TOTAL_TRANSITIONS, "hard_maximum": True},
        "stop_conditions": ["a failed launch gate", "a monitor hard alert", "the in-run memory policy (a resource stop)",
                            "a provenance mismatch", "a process leak (leak_free false or a leftover BattleShip process)",
                            "a training verification failure", "a manifest drift"],
        "after_a_stop": "the campaign stops and reports; the stopped run directory is moved to _partial by the guard and "
                        "preserved (never deleted, never resumed); nothing is relaunched in this milestone",
        "evaluation": "post hoc, frozen statistics, tick-0 starts only (Phase K protocol), btt_eval_metrics_v1 with "
                      "SSB64_RL_TARGET_DIAG=1, clear verification of every native clear, census; then exact spatial "
                      "replays (SSB64_RL_SPATIAL=1, read-only) of every final stochastic episode of both arms "
                      "(approach zone, secondary)",
        "training_inputs": "tick-0 episodes of the run itself only; never the crossing fixtures, the TAS, feasibility "
                           "traces, capture recordings, other runs or hand-written routes",
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
            same = [pol, obs] == control[str(s.seed)].get("initial_digests")
            r["initial_model_equals_control_untrained_model"] = same
            if not same:
                problems.append(f"{s.name}: the fresh model differs from the control's untrained model")
        runs[s.name] = r
    rule = la.load_rule()
    exe = executable_identity()
    dplan = check_directory_plan()
    problems += dplan["problems"]
    if dplan["existing"]:
        problems.append(f"campaign directories already exist: {dplan['existing']}")
    plans = {s.name: evaluation_plan(s, load_run(s)) for s in matrix()}
    from btt_rewards import REWARD_V2, REWARD_V3, REWARD_V3_T2

    contracts = {c.contract: {"canonical_sha256": canonical_sha256(c.to_json()), "json": c.to_json()}
                 for c in (REWARD_V2, REWARD_V3, REWARD_V3_T2)}
    if contracts["btt_reward_v3_t2"]["canonical_sha256"] != REWARD_V3_T2_SHA256 or \
            not contracts["btt_reward_v3"]["canonical_sha256"].startswith(REWARD_V3_SHA256_PREFIX):
        problems.append("a reward contract differs from its registration (v3 d9447d47..., v3_t2 fa74d7d7...)")
    man = {
        "schema": MANIFEST_SCHEMA, "milestone": MILESTONE, "campaign": CAMPAIGN, "created_utc": utc_now(),
        "authority": {"proposal": ec.repo_relative(PROPOSAL_DOC) + " section 10",
                      "approval": "user, 2026-09-25: run the controlled three-seed target-2 reward experiment if its "
                                  "registration and control checks pass; no pause between passing checks and training"},
        "question": "Does btt_reward_v3_t2 (a one-time, time-sensitive credit of up to +2.0 for native target 2) make fresh "
                    "v1 policies break the moving target 2 more often at 3,072,000 transitions than the historical "
                    "btt_reward_v2 control, without losing static targets, and is the gain early enough to matter for a "
                    "first clear (L, R)?",
        "arms": {"T": "m7l_t2_s{0,1,2}: fresh models, btt_reward_v3_t2, otherwise the Phase K v1 profile of the seed",
                 "C": "historical runs/m7g_k/m7g_s{0,1,2}_v1 (btt_reward_v2), reused only while the control check passes"},
        "only_experimental_change": "the reward contract (btt_reward_v3_t2 instead of btt_reward_v2) and the native "
                                    "diagnostic flag it derives (SSB64_RL_TARGET_DIAG=1, read-only, gameplay-neutral)",
        "order": [s.name for s in matrix()],
        "sequencing": "strictly sequential, one run at a time, in the order T0, T1, T2; the launch gate before each",
        "registered_settings": registered_settings(),
        "reward_contracts": contracts,
        "executable": {"path": ec.repo_relative(Path(exe.get("path") or "")) if exe.get("path") else None,
                       "sha256": exe.get("sha256"), "size": exe.get("size")},
        "revisions": revisions(), "code": code_fingerprint(),
        "decision_rule": {"path": ec.repo_relative(RULE_DOC), "sha256": rule["_sha256"], "schema": rule["schema"]},
        "runs": runs,
        "historical_control": {
            "seeds": control,
            "control_check": {
                "R1": {"what": "curriculum-off btt_reward_v2 runs of 102,400 transitions (rl/configs/m7h/gate/m7h_r1_s{s}"
                               ".toml = the Phase K v1 profile, bounded) on the frozen code",
                       "must_equal": "the pinned policy / statistics digests (Phase K = M7e ckpt_000102400) and every "
                                     "episode row up to 102,400 (rank, worker episode, end, steps, targets, native "
                                     "action digest), 30 / 27 / 29 rows",
                       "implementation": "rl/m7h_run.py cmd_r1 into the campaign's _control tree, plus an M7l comparison "
                                         "against the Phase K checkpoint and rows"},
                "R2": {"what": "re-evaluation of the three historical final checkpoints (100 deterministic + 100 "
                               "stochastic each, 600 episodes) on the frozen code",
                       "must_equal": "native action digest, targets, end reason and btt_eval_metrics_v1 of every "
                                     "registered Phase K evaluation episode",
                       "implementation": "rl/m7h_run.py cmd_r2"},
                "R3": {"what": "the M7l decision inputs recomputed from the R2 records and from the historical records",
                       "must_equal": "each other and the rule's known_control_values",
                       "implementation": "rl/m7l_campaign.py"}},
            "verification": "python rl/m7l_campaign.py control-check (bound to the code fingerprint and executable)"},
        "evaluation_protocol": {"plan": plans, "census": census_plan(),
                                "tick0_check": "rl/m7h_verify.verify_eval_tick0 on every label",
                                "route_rows": "every evaluation row equals its btt_reward_v3_t2 closed form (reward_v3 "
                                              "record) and its moving-target tick equals btt_eval_metrics_v1's",
                                "clear_verification": "rl/m7g_k_run.verify_clears_in on every T label",
                                "spatial_replays": "every final stochastic episode of both arms (600), exact, "
                                                   "rl/m7k_target2.replay_one; descriptive"},
        "directory_plan": dplan,
        "limits": {"runs": len(matrix()), "transitions": len(matrix()) * TOTAL_TRANSITIONS,
                   "max_game_processes": MAX_GAME_PROCESSES, "extension": "none", "extra_seeds": "none"},
        "problems": problems, "ok": not problems,
    }
    return man
