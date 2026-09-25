"""M7h campaign matrix: the runs, their order, the registered settings, the historical control, the evaluation plan,
the directories and the manifest. Reads only; the driver is rl/m7h_campaign.py.

Arms (docs/rl_frontier_curriculum_m7h_proposal.md revision 2, section 6.1):
    F   m7h_f_s{0,1,2}: v1 + reward v2 + Track 1 + btt_curriculum_frontier_v1 (registered settings), fresh untrained
        models, 3,072,000 policy transitions each; order F0, F1, F2
    C   the historical Phase K runs runs/m7g_k/m7g_s{0,1,2}_v1, reused only while the R1-R3 control check passes on the
        frozen campaign code; otherwise (a recorded user decision) m7h_c_s{0,1,2} in the order C0, F0, F1, C1, C2, F2
    extension (only after gate 3 at n = 3): C3, F3, F4, C4 (m7h_c_s{3,4} and m7h_f_s{3,4})

Everything the campaign writes lives below runs/m7h/campaign (redirectable for tests); the historical control and every
other run tree are read only.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import experiment_config as ec
import m7e_matrix as em
import m7h_analysis as ma
import m7h_curriculum as mc
import m7h_guard as g

REPO_ROOT = ec.REPO_ROOT
MILESTONE = "M7h"
CAMPAIGN = "frontier_restart_v1"
MANIFEST_SCHEMA = "battleship_m7h_campaign_manifest_v1"
CONFIG_DIR = REPO_ROOT / "rl" / "configs" / "m7h"
PHASE_K_CONFIG_DIR = REPO_ROOT / "rl" / "configs" / "m7g"
MANIFEST_DOC = REPO_ROOT / "docs" / "rl_frontier_curriculum_m7h_manifest.json"
RULE_DOC = ma.RULE_DOC
PROPOSAL_DOC = REPO_ROOT / "docs" / "rl_frontier_curriculum_m7h_proposal.md"
GATE_DOC = REPO_ROOT / "docs" / "rl_frontier_curriculum_m7h_gate.md"
DEFAULT_ROOT = REPO_ROOT / "runs" / "m7h" / "campaign"
HISTORICAL = REPO_ROOT / "runs" / "m7g_k"                      # the Phase K tree (control arm C, read only)
M7E_RUNS = REPO_ROOT / "runs" / "m7e"
RUNS = REPO_ROOT / "runs"
MAX_GAME_PROCESSES = 10

SEEDS: Tuple[int, ...] = (0, 1, 2)
EXTENSION_SEEDS: Tuple[int, ...] = (3, 4)
ORDER: Tuple[Tuple[int, str], ...] = ((0, "F"), (1, "F"), (2, "F"))
ORDER_CONTROL_RETRAINED: Tuple[Tuple[int, str], ...] = ((0, "C"), (0, "F"), (1, "F"), (1, "C"), (2, "C"), (2, "F"))
EXTENSION_ORDER: Tuple[Tuple[int, str], ...] = ((3, "C"), (3, "F"), (4, "F"), (4, "C"))
TOTAL_TRANSITIONS = em.TOTAL_TRANSITIONS          # 3,072,000 policy transitions, hard maximum per run
CHECKPOINT_INTERVAL = em.CHECKPOINT_INTERVAL      # 102,400
HORIZON = em.HORIZON                              # 3,600 native ticks (prefix + policy)
PROCESS_COUNT = em.PROCESS_COUNT                  # 5
FINAL_EPISODES = dict(em.FINAL_EPISODES)          # 100 deterministic + 100 stochastic at initial and final
CURVE_EPISODES = dict(em.CURVE_EPISODES)          # 5 + 60 at each intermediate point
EVAL_SEED = em.EVAL_SEED
M6_FLAGS = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1"}
EVAL_METRICS_FLAG = {"SSB64_RL_TARGET_DIAG": "1"}  # evaluation and verification replays only
PERIODIC_EPISODES = 10                             # as the control: every 10th finished training episode preserved

# The R1-R3 conditions accepted at the gate (docs/rl_frontier_curriculum_m7h_gate.md section 2); re-verified at launch.
R_CONDITIONS = {
    "R1": {"transitions": 102_400, "m7e_rows_at_102400": {"0": 30, "1": 27, "2": 29},
           "reference": "runs/m7e/m7e_s{s}_v2/checkpoints/ckpt_000102400 (policy + statistics digests) and its rows",
           "row_keys": ["rank", "worker_episode", "end_reason", "steps", "targets_broken", "native_action_digest"],
           "control_path": "no curriculum component, record or file"},
    "R2": {"episodes": 600, "compare": ["native_action_digest", "targets_broken", "end_reason", "eval_metrics"],
           "reference": "runs/m7g_k/_eval/m7g_s{s}_v1/final"},
    "R3": {"k": 0, "chi": 0, "T": {"0": "472/100", "1": "475/100", "2": "427/100"}, "falls": {"0": 1, "1": 1, "2": 0}},
}


class MatrixError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(p: Path) -> Any:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(p: Path, data: Any) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fp:
        json.dump(data, fp, indent=1, default=str)
        fp.write("\n")
    os.replace(tmp, p)


def sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def within(child: Path, parent: Path) -> bool:
    try:
        Path(os.path.normpath(str(child))).relative_to(Path(os.path.normpath(str(parent))))
        return True
    except ValueError:
        return False


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


def entries_root() -> Path:
    return _ROOT / "_entries"


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
    arm: str                     # "F" (curriculum) or "C" (curriculum off)
    order_index: int
    extension: bool = False

    @property
    def name(self) -> str:
        return f"m7h_{self.arm.lower()}_s{self.seed}"

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
    def entries_dir(self) -> Path:
        return entries_root() / self.name

    @property
    def curriculum(self) -> bool:
        return self.arm == "F"


def matrix(*, control: str = "historical", include_extension: bool = False) -> List[RunSpec]:
    if control not in ("historical", "retrained"):
        raise MatrixError(f"control {control!r}")
    order = ORDER if control == "historical" else ORDER_CONTROL_RETRAINED
    specs = [RunSpec(s, a, i) for i, (s, a) in enumerate(order, 1)]
    if include_extension:
        specs += [RunSpec(s, a, len(order) + i, extension=True) for i, (s, a) in enumerate(EXTENSION_ORDER, 1)]
    return specs


def extension_specs(control: str = "historical") -> List[RunSpec]:
    return [s for s in matrix(control=control, include_extension=True) if s.extension]


def all_specs() -> List[RunSpec]:
    """Every registered profile (F and C, seeds 0-4), for identity and the manifest."""
    return [RunSpec(s, a, 0, extension=s in EXTENSION_SEEDS) for a in ("F", "C") for s in SEEDS + EXTENSION_SEEDS]


def run_by_name(name: str) -> RunSpec:
    for s in all_specs():
        if s.name == name:
            return s
    raise MatrixError(f"{name!r} is not an M7h campaign run")


def load_run(spec: RunSpec) -> ec.Experiment:
    exp = ec.load_experiment(spec.config_path)
    if _ROOT != DEFAULT_ROOT:
        exp = exp.with_overrides({"run.output_root": str(spec.run_dir.parent)})
    return exp


def phase_k_profile(seed: int) -> Path:
    return PHASE_K_CONFIG_DIR / f"m7g_s{seed}_v1.toml"


# -- the historical control (arm C, seeds 0-2) ----------------------------------------------------------------------


@dataclass(frozen=True)
class HistoricalControl:
    seed: int

    @property
    def name(self) -> str:
        return f"m7g_s{self.seed}_v1"

    @property
    def run_dir(self) -> Path:
        return HISTORICAL / self.name

    @property
    def eval_dir(self) -> Path:
        return HISTORICAL / "_eval" / self.name

    @property
    def clears_dir(self) -> Path:
        return HISTORICAL / "_clears" / self.name

    @property
    def config_path(self) -> Path:
        return phase_k_profile(self.seed)


def historical_identity(seed: int) -> Dict[str, Any]:
    """What arm C seed s is, byte for byte: the final set, the final evaluation files and their rule inputs."""
    import m7d_run as dr

    h = HistoricalControl(seed)
    out: Dict[str, Any] = {"run": h.name, "run_dir": ec.repo_relative(h.run_dir), "eval_dir": ec.repo_relative(h.eval_dir)}
    problems: List[str] = []
    fin = h.run_dir / "final"
    if not (fin / "checkpoint.json").is_file():
        return dict(out, problems=[f"{ec.repo_relative(fin)} missing"], ok=False)
    out["final_checkpoint_json_sha256"] = sha256_file(fin / "checkpoint.json")
    out["final_digests"] = list(dr.checkpoint_digests(fin))
    files = {}
    for mode in ("stochastic", "deterministic"):
        f = h.eval_dir / "final" / mode / "evaluation.json"
        files[mode] = sha256_file(f) if f.is_file() else None
        if files[mode] is None:
            problems.append(f"{ec.repo_relative(f)} missing")
    out["final_evaluation_sha256"] = files
    clear_doc = h.clears_dir / "final" / "clear_verification.json"
    arm, p = ma.rule_inputs(h.eval_dir / "final", read_json(clear_doc) if clear_doc.is_file() else None)
    problems += p
    out["rule_inputs"] = arm.to_json()
    want = R_CONDITIONS["R3"]
    got = {"k": arm.k, "chi": arm.chi, "T": str(arm.T), "falls": arm.phi}
    reg = {"k": want["k"], "chi": want["chi"], "T": str(Fraction(want["T"][str(seed)])), "falls": want["falls"][str(seed)]}
    if got != reg:
        problems.append(f"rule inputs {got} != the registered Phase K values {reg}")
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
    v = exp.values
    return {
        "name": exp.name == spec.name,
        "seed": v["run.base_seed"] == spec.seed,
        "mode_train_fresh": exp.mode == "train" and exp.resume_source is None,
        "observation_v1": v["contracts.observation"] == "btt_policy_obs_v1" and exp.policy_observation() is None,
        "policy": v["ppo.policy"] == "MlpPolicy",
        "native_flags": dict(exp.extra_env) == M6_FLAGS,
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
        "curriculum": (exp.curriculum == mc.REGISTERED) if spec.curriculum else (exp.curriculum is None),
        "run_dir": exp.run_dir == spec.run_dir,
        "no_fixture_or_tas_path": not _forbidden_in(spec.config_path.read_text(encoding="utf-8")),
    }


FORBIDDEN_INPUTS = ("rl/fixtures", "fixtures/m7g", "m7g/capture", "tas_input", "mario_743", "runs/m7f", "crossing_fixture",
                    "lower_precision", "upper_moving_platform", ".btti")


def _forbidden_in(text: str) -> List[str]:
    t = text.replace("\\", "/")
    return [f for f in FORBIDDEN_INPUTS if f in t]


def phase_k_proof(spec: RunSpec, exp: ec.Experiment) -> Dict[str, Any]:
    """The profile against the Phase K v1 profile of its seed: F differs exactly by the registered curriculum keys;
    C by nothing (same semantic and compatibility fingerprints)."""
    base = ec.load_experiment(phase_k_profile(spec.seed))
    a, b = exp.compatibility_view(), base.compatibility_view()
    diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    want = sorted(f"curriculum.{k}" for k in mc.REGISTERED) if spec.curriculum else []
    same_semantic = exp.semantic_fingerprint == base.semantic_fingerprint
    ok = diff == want and (spec.curriculum or same_semantic) and (not spec.curriculum or not same_semantic)
    return {"base": ec.repo_relative(phase_k_profile(spec.seed)), "compatibility_differences": diff,
            "expected_differences": want, "same_semantic_fingerprint": same_semantic, "ok": ok}


def code_fingerprint() -> Dict[str, Any]:
    """sha256 over every non-test rl/*.py module, every M7h profile (campaign and gate, which R1 uses) and the
    registered decision rule: the exact code, settings and rule the campaign runs with."""
    files = sorted(p for p in (REPO_ROOT / "rl").glob("*.py") if not p.name.endswith(("_tests.py", "_smoke.py")))
    files += sorted(CONFIG_DIR.rglob("*.toml")) + [RULE_DOC]
    agg = hashlib.sha256()
    per: Dict[str, str] = {}
    for p in files:
        h = sha256_file(p)
        rel = p.relative_to(REPO_ROOT).as_posix()
        per[rel] = h
        agg.update(f"{rel}\0{h}\n".encode("utf-8"))
    return {"files": len(files), "sha256": agg.hexdigest(), "per_file": per}


def revisions() -> Dict[str, Any]:
    import m7g_k_matrix as km

    return km.revisions()


def executable_identity() -> Dict[str, Any]:
    return load_run(matrix()[0]).executable_fingerprint()


def expected_initial_digests(exp: ec.Experiment) -> Tuple[str, str]:
    """(policy, statistics) digests of the untrained model a fresh run of this profile must save as ckpt_000000000."""
    import m7g_k_matrix as km

    return km.expected_initial_digests(exp)


def current_identity() -> Dict[str, Any]:
    profiles = {}
    for s in all_specs():
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
        p.append("the Python code, an M7h profile or the decision rule changed since the manifest (code fingerprint)")
    if cur["rule_sha256"] != (manifest.get("decision_rule") or {}).get("sha256"):
        p.append("the decision rule differs from the manifest")
    for name, triple in cur["profiles"].items():
        r = (manifest.get("runs") or {}).get(name)
        if r is None or (r["source_sha256"], r["semantic_fingerprint"], r["compatibility_fingerprint"]) != tuple(triple):
            p.append(f"{name}: profile source / fingerprints differ from the manifest")
    return p


# -- evaluation plan and census --------------------------------------------------------------------------------------


def evaluation_plan(spec: RunSpec, exp: ec.Experiment) -> List[Dict[str, Any]]:
    """The Phase K post-hoc protocol, tick-0 starts only: initial, every 307,200 transitions, final; 100 + 100 at initial
    and final, 5 deterministic + 60 stochastic in between; seed 12345; frozen statistics; every episode preserved; the
    evaluation-only metrics recorder on. Evaluation never constructs the curriculum."""
    v = exp.values
    total = int(v["run.total_transitions"])
    if total != TOTAL_TRANSITIONS:
        raise MatrixError(f"{spec.name}: total_transitions {total}")
    common = {"seed": int(v["evaluation.seed"]), "workers": exp.eval_workers, "horizon": int(v["environment.horizon"]),
              "extra_env": dict(exp.extra_env, **EVAL_METRICS_FLAG), "standby_preboot": exp.standby_preboot,
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


def census_plan(*, control: str = "historical", include_extension: bool = False) -> Dict[str, Any]:
    per = em.evaluation_census_plan()["per_seed"]                     # 985 = 740 stochastic + 245 deterministic
    runs = len(matrix(control=control, include_extension=include_extension))
    return {"runs": runs, "per_run": per, "episodes": runs * per, "arithmetic": f"{runs} runs x {per} = {runs * per}",
            "labels_per_run": len(em.evaluated_points()), "historical_control_reused": control == "historical"}


# -- directories -----------------------------------------------------------------------------------------------------


def planned_directories() -> Dict[str, Path]:
    d: Dict[str, Path] = {"root": _ROOT, "state": state_dir(), "eval_root": eval_root(), "clears_root": clears_root(),
                          "entries_root": entries_root(), "control": control_root(), "partial": partial_root(),
                          "guard": guard_root()}
    for s in all_specs():
        d[f"run:{s.name}"] = s.run_dir
        d[f"eval:{s.name}"] = s.eval_dir
        d[f"clears:{s.name}"] = s.clears_dir
        d[f"entries:{s.name}"] = s.entries_dir
    return d


def check_directory_plan() -> Dict[str, Any]:
    """Unique, pairwise-disjoint leaves, all below the campaign root; the root never inside or around another run
    tree (the historical control, the gate, Phase K, M7e, ...)."""
    dirs = planned_directories()
    p: List[str] = []
    norm = {k: Path(os.path.normpath(str(v))) for k, v in dirs.items()}
    if len(set(norm.values())) != len(norm):
        p.append("two planned directories resolve to the same path")
    leaves = sorted((k, v) for k, v in norm.items() if k.split(":")[0] in ("run", "eval", "clears", "entries")
                    or k in ("state", "control", "partial", "guard"))
    for i, (ka, pa) in enumerate(leaves):
        for kb, pb in leaves[i + 1:]:
            if within(pa, pb) or within(pb, pa):
                p.append(f"{ka} and {kb} overlap")
    r = norm["root"]
    for k, v in norm.items():
        if not within(v, r):
            p.append(f"{k} lies outside the campaign root")
    protected = [HISTORICAL, M7E_RUNS, RUNS / "m7h" / "_gate", RUNS / "m7g", RUNS / "m7f", RUNS / "m7d"]
    for h in protected:
        if within(r, h) or within(h, r):
            p.append(f"the campaign root overlaps {ec.repo_relative(h)}")
    for s in all_specs():
        exp = load_run(s)
        if exp.run_dir != s.run_dir or exp.name != s.name:
            p.append(f"{s.name}: profile resolves to {exp.name} / {exp.run_dir}")
    existing = sorted(k for k, v in norm.items() if k.split(":")[0] in ("run", "eval", "clears", "entries") and v.exists())
    return {"root": ec.repo_relative(r), "planned": len(dirs), "existing": existing, "problems": p, "ok": not p}


# -- the manifest ----------------------------------------------------------------------------------------------------


def registered_settings() -> Dict[str, Any]:
    return {
        "curriculum": dict(mc.REGISTERED, cell_key="(floor(x/300), floor(y/300), targets_remaining) on live steps",
                           selection="after automatic resets only; u1 < 1/2 -> tick0, else a visit-weighted eligible cell "
                                     "w = 1/sqrt(1 + visits); an empty archive -> tick0_archive_empty",
                           initial_episode="every worker's first episode is an ordinary tick-0 start",
                           reset_contract="every exposed reset() returns the tick-0 observation and consumes nothing"),
        "launch_gate": {"available_commit_gib_min": g.LAUNCH_COMMIT_GIB, "available_physical_gib_min": g.LAUNCH_PHYSICAL_GIB,
                        "free_disk_gib_min": g.LAUNCH_DISK_GIB, "system_cpu_pct_max": g.LAUNCH_MAX_CPU_PCT,
                        "boundaries": "inclusive; a missing reading fails; commit and physical evaluated separately",
                        "when": "before every training launch"},
        "in_run_memory_policy": dict(asdict(g.REGISTERED_POLICY), watches="available system commit only",
                                     physical="recorded and reported, never a stop trigger"),
        "atomic_checkpoint_sets": True,
        "budget": {"policy_transitions_per_run": TOTAL_TRANSITIONS, "prefix_ticks": "reported, not budgeted",
                   "hard_maximum": True},
        "stop_conditions": ["a hard failure or alert (prefix mismatch or precondition failure, more than 3 prefix-phase "
                            "lifecycle failures, a leak, more than 10 game processes, a changed user config, low disk)",
                            "the in-run memory policy", "a manifest drift", "the budget cap"],
        "restart_policy": "a stopped or partial run is moved to _partial (never deleted) and restarted from scratch after "
                          "the launch gate passes again; a curriculum run is never resumed; no early stop on results",
        "evaluation": "post hoc, frozen statistics, tick-0 starts only (Phase K protocol), btt_eval_metrics_v1 with "
                      "SSB64_RL_TARGET_DIAG=1, clear verification, census",
        "training_inputs": "the run's own finished training episodes only; never the crossing fixtures, the TAS, capture "
                           "recordings, other runs or hand-written routes",
    }


def build_manifest(*, with_digests: bool = True) -> Dict[str, Any]:
    problems: List[str] = []
    runs: Dict[str, Any] = {}
    for s in all_specs():
        exp = load_run(s)
        checks = arm_checks(s, exp)
        proof = phase_k_proof(s, exp)
        bad = [k for k, ok in checks.items() if not ok]
        if bad:
            problems.append(f"{s.name}: identity / frozen values violated: {bad}")
        if not proof["ok"]:
            problems.append(f"{s.name} vs Phase K v1: {proof['compatibility_differences']}")
        r = {"seed": s.seed, "arm": s.arm, "extension": s.extension, "config": ec.repo_relative(s.config_path),
             "source_sha256": exp.source.sha256, "semantic_fingerprint": exp.semantic_fingerprint,
             "compatibility_fingerprint": exp.compatibility_fingerprint, "curriculum": exp.curriculum,
             "run_dir": ec.repo_relative(s.run_dir), "eval_dir": ec.repo_relative(s.eval_dir),
             "checks": checks, "phase_k_proof": proof}
        if with_digests:
            pol, obs = expected_initial_digests(exp)
            r["expected_initial_policy_digest"], r["expected_initial_obs_rms_digest"] = pol, obs
        runs[s.name] = r
    if with_digests:
        for s in SEEDS + EXTENSION_SEEDS:
            f, c = runs[f"m7h_f_s{s}"], runs[f"m7h_c_s{s}"]
            if (f["expected_initial_policy_digest"], f["expected_initial_obs_rms_digest"]) != \
                    (c["expected_initial_policy_digest"], c["expected_initial_obs_rms_digest"]):
                problems.append(f"seed {s}: F and C untrained models differ")
    control = {str(s): historical_identity(s) for s in SEEDS}
    for s, h in control.items():
        if not h["ok"]:
            problems.append(f"historical control seed {s}: {h['problems'][:3]}")
    rule = ma.load_rule()
    exe = executable_identity()
    dplan = check_directory_plan()
    problems += dplan["problems"]
    plans = {s.name: evaluation_plan(s, load_run(s)) for s in matrix(include_extension=True)}
    man = {
        "schema": MANIFEST_SCHEMA, "milestone": MILESTONE, "campaign": CAMPAIGN, "created_utc": utc_now(),
        "authority": {"proposal": ec.repo_relative(PROPOSAL_DOC) + " (revision 2)", "gate": ec.repo_relative(GATE_DOC),
                      "approval": "user, 2026-09-24: the E1-E7 / R1-R3 gate accepted; campaign readiness only"},
        "question": "Do frontier restarts from the run's own archived states (arm F) improve the tick-0 policy over plain "
                    "v1 (arm C) at 3,072,000 policy transitions?",
        "arms": {"F": "m7h_f_s{s}: v1 + reward v2 + Track 1 + btt_curriculum_frontier_v1",
                 "C": "historical runs/m7g_k/m7g_s{0,1,2}_v1 while R1-R3 pass on the frozen code; otherwise m7h_c_s{0,1,2}"},
        "order": {"historical_control": [s.name for s in matrix()],
                  "control_retrained": [s.name for s in matrix(control="retrained")],
                  "extension": [s.name for s in extension_specs()]},
        "sequencing": "strictly sequential, one run at a time; the launch gate before each run; the extension only after "
                      "a recorded n = 3 decision that requires it; the control-retrain branch only after a recorded "
                      "user decision",
        "registered_settings": registered_settings(),
        "executable": {"path": ec.repo_relative(Path(exe.get("path") or "")) if exe.get("path") else None,
                       "sha256": exe.get("sha256"), "size": exe.get("size")},
        "revisions": revisions(), "code": {k: v for k, v in code_fingerprint().items()},
        "decision_rule": {"path": ec.repo_relative(RULE_DOC), "sha256": rule["_sha256"], "schema": rule["schema"]},
        "runs": runs,
        "historical_control": {"seeds": control, "reuse_conditions": R_CONDITIONS,
                               "verification": "python rl/m7h_campaign.py control-check (R1-R3 re-run on the frozen "
                                               "code; bound to its code fingerprint and executable)"},
        "evaluation_protocol": {"plan": plans, "census": census_plan(), "census_with_extension":
                                census_plan(include_extension=True),
                                "census_control_retrained": census_plan(control="retrained"),
                                "tick0_check": "every evaluation artifact: no m7h_start label, initial observation tick "
                                               "0, first row tick 0; every row: no m7h key"},
        "directory_plan": dplan,
        "limits": {"runs_planned": len(matrix()), "runs_max": len(matrix(control="retrained", include_extension=True)),
                   "transitions_planned": len(matrix()) * TOTAL_TRANSITIONS,
                   "transitions_max": len(matrix(control="retrained", include_extension=True)) * TOTAL_TRANSITIONS,
                   "max_game_processes": MAX_GAME_PROCESSES},
        "problems": problems, "ok": not problems,
    }
    return man
