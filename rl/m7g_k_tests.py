"""M7g Phase K readiness tests: observation-v2 wiring of the trainer, the strict configuration and the evaluator.

btt_policy_obs_v1 stays the default everywhere; btt_policy_obs_v2_spatial is selected explicitly by
contracts.observation + ppo.policy (rl/configs/m7g/m7g_s{0,1,2}_{v1,v2}.toml). Nothing here trains a game policy: no
learn(), no rollout of the game feeds an update. The only optimizer steps are unit_update_path's three timed PPO
updates per arm on one synthetic rollout (throwaway models, never saved, no game data), which exercise the Dict rollout
buffer and backward pass and measure the update cost.

Unit cases (no game):
    unit_existing_profiles   every pre-existing profile keeps the source / semantic / compatibility fingerprints pinned
                             before the hooks, its native flags, its v1 trainer config and contracts; the untrained v1
                             policy and statistics built by the trainer helpers keep the M7d digests; M7Run uses the
                             helpers
    unit_phase_k_profiles    the six Phase K profiles: v1 arm == the M7e profile of its seed (semantic + compatibility
                             fingerprints), v2 arm differs only in contracts.observation + ppo.policy (+ the derived
                             native flag), identity blocks, trainer configs valid, dry runs exit 0
    unit_config_rejections   strict rejection of inconsistent observation / policy / normalisation / network choices (TOML
                             and M7Config); a v2 run cannot resume from a v1 checkpoint (refused before any file exists)
    unit_checkpoint_identity offline checkpoint sets of both arms via save_checkpoint_set: metadata identity (v1
                             checkpoint.json keys == the M7e ones), save / reload digests and predictions, frozen per-key
                             statistics, binary keys raw, cross-arm loading refused by contracts, model, statistics and
                             the evaluator before any directory or worker exists; a historical M7e checkpoint still reads
                             as v1 (read-only)
    unit_update_path         three timed PPO updates per arm on one synthetic rollout at the Phase K geometry (5,120
                             transitions, batch 512, 10 epochs): Dict rollout buffer + backward pass work, losses finite;
                             measured update / inference / minibatch timings
    unit_isolation           the Phase K profiles and hooked modules never reference the crossing fixtures; this suite
                             never calls learn()
Game cases (no training; fresh BattleShip processes, at most 10 at a time, one case at a time):
    game_v1_historical_eval  the hooked evaluator on runs/m7e/m7e_s0_v2/final reproduces the recorded deterministic
                             episode and the first five stochastic episodes (seed 12345, 5 workers, standby)
    game_wiring_smoke        per arm, the exact Phase K seed-0 profile (N=5, standby): the trainer helpers build the
                             workers, VecNormalize and the untrained model; 200 vector steps of the untrained stochastic
                             policy (statistics only, no optimizer step); an initial checkpoint set is saved and evaluated
                             through eval_m7.py --config (1 deterministic + 2 stochastic, frozen); a cross-arm --config is
                             refused
    game_target_diag_probe   both smoke checkpoints evaluate cleanly with SSB64_RL_TARGET_DIAG=1 added (the Phase K
                             evaluation instrumentation flag)

Usage: python rl/m7g_k_tests.py [unit|game|<case> ...] [--root runs/_tests/m7g_k_<utc>]
(the default root is outside the archived Phase K tree runs/m7g_k)
Exit 0 all pass, 1 any failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import gymnasium as gym  # noqa: E402
import numpy as np  # noqa: E402

import experiment_config as ec  # noqa: E402
import m7g_obs as mo  # noqa: E402

REPO_ROOT = RL_DIR.parent
EXE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
M6_FLAGS = (("SSB64_RL_NO_RENDER", "1"), ("SSB64_RAPHNET_DISABLE", "1"))
V1 = "btt_policy_obs_v1"
V2 = "btt_policy_obs_v2_spatial"
ARMS = ("v1", "v2")
PHASE_K = {(s, a): RL_DIR / "configs" / "m7g" / f"m7g_s{s}_{a}.toml" for s in (0, 1, 2) for a in ARMS}
M7E = {s: RL_DIR / "configs" / "m7e" / f"m7e_s{s}_v2.toml" for s in (0, 1, 2)}
V2_CONTRACT_SHA256 = "dcfd14b276c3d9f38f180888c132febb67ace39797bdef2aefb185e024c8c0cb"
HISTORICAL_CKPT = REPO_ROOT / "runs" / "m7e" / "m7e_s0_v2" / "final"
HISTORICAL_EVAL = REPO_ROOT / "runs" / "m7e" / "_eval" / "m7e_s0_v2" / "final" / "evaluation_summary.json"

# Recorded 2026-09-23 immediately BEFORE the Phase K hooks (runs of rl/experiment_config.py at afa42fc): every
# pre-existing profile must keep (source sha256, semantic fingerprint, compatibility fingerprint).
PINNED_PROFILES: Dict[str, Tuple[str, str, str]] = {
    "rl/configs/m7_mario_us_reward_v1.toml": ("617bb32ac283281f6f9b90a8fd8326853c22dd6bfd5869fb3f7a7dfbfc94f029",
        "c93faaf9800f654b4f2843002baf677197f020164dff44568f074e7d2fbacd26",
        "1c99cc42408a83ea844c43aa31f0b2d730b7568c809a049004e3c5298506c2a2"),
    "rl/configs/m7_mario_us_reward_v1_standby.toml": ("bbee55d964e484557eba3657b841164dfcc3964f5191b9b7163a31d9cdfb0010",
        "71c3d35615cae6d66b76ce1ce1d9158322e7debacea346e34ff7924640855876",
        "df5206324f6e2c6241d9c1438b8cd8a64e64dfed5602826e547b0b7b019f176f"),
    "rl/configs/m7_mario_us_reward_v2.toml": ("065e9ae44957c398922e9be13c51531a98edb104e4d0dac46a895109a0894611",
        "13df42f7835de6afae02e366597569c116437f5dd389c4ac039ce55ef208ed3f",
        "a71aab16201679fa0bd8f93b115f6179820fc13fe8753c9263305ec88e817221"),
    "rl/configs/m7_mario_us_reward_v2_standby.toml": ("736d0df0aefb9c5af9db1d49a2fb09f30e5bcd1e62cdee246fb1fe0affd95be6",
        "79cb0264d04956e84ebc5aceaaae723872c0dac4598787e435688ec8c68d9d45",
        "ac622dfa7b3a5d781a5a4c9147811495a0a2839a3edfe2c5a47ea98d370cb660"),
    "rl/configs/m7d/m7d_s0_v1.toml": ("467c4329edb2181eb16effc7b04f59fc0477255404d805ee1f5f012e2d889314",
        "71c3d35615cae6d66b76ce1ce1d9158322e7debacea346e34ff7924640855876",
        "df5206324f6e2c6241d9c1438b8cd8a64e64dfed5602826e547b0b7b019f176f"),
    "rl/configs/m7d/m7d_s0_v2.toml": ("5499378da9326ee1a2a89ceea5aa6dbe3c8e191108519c7bcb9dae036b7233fa",
        "79cb0264d04956e84ebc5aceaaae723872c0dac4598787e435688ec8c68d9d45",
        "ac622dfa7b3a5d781a5a4c9147811495a0a2839a3edfe2c5a47ea98d370cb660"),
    "rl/configs/m7d/m7d_s1_v1.toml": ("794a9cd54bab60cc454d2a8bf3589c8d6a8d0c5c45c56c7ab2c76f3d6aa6340c",
        "13cf2546ce66d45b374fd460daa5e7ccaad644a817719c600bea5bbac3c77759",
        "df5206324f6e2c6241d9c1438b8cd8a64e64dfed5602826e547b0b7b019f176f"),
    "rl/configs/m7d/m7d_s1_v2.toml": ("a1fb865e45956444d4e98fe1eca15a202957655b98fa57ccdbc609e6529b6bf0",
        "cbf09b0c39c0963a13facc37cd7cb55ea6d8d685848d9ca788637768103f77d9",
        "ac622dfa7b3a5d781a5a4c9147811495a0a2839a3edfe2c5a47ea98d370cb660"),
    "rl/configs/m7d/m7d_s2_v1.toml": ("791b4943bcd98c1b45c738e52774afa5578546c1994b071136792aa3ff493d26",
        "0a899c3451dbbc6222e8e115d7a27664cd78792e13758014b156860c5a0e9c1b",
        "df5206324f6e2c6241d9c1438b8cd8a64e64dfed5602826e547b0b7b019f176f"),
    "rl/configs/m7d/m7d_s2_v2.toml": ("0ad1f51278a0eecbb61917cfeb92afd2bed5cc52b12c680b89de0311f98e1e40",
        "03e8d04e35c1e490036d4cc5b2bc74a39f816bf0a4a1d516641c0ff5957b2291",
        "ac622dfa7b3a5d781a5a4c9147811495a0a2839a3edfe2c5a47ea98d370cb660"),
    "rl/configs/m7e/m7e_s0_v2.toml": ("35c57a7a2a1b7bf612c6e501dca31cd59ea0b47f2c1ef646e213d564fca5e453",
        "d8d993eaacf7ee72d3f8c98787bafa8a2a4f583e42746827b2862c5f5941fd8b",
        "ac622dfa7b3a5d781a5a4c9147811495a0a2839a3edfe2c5a47ea98d370cb660"),
    "rl/configs/m7e/m7e_s1_v2.toml": ("f3cb95fedf9050c8718c05c8447ea0c24f2f23396bce41a25aa4042567e4bc0f",
        "dd87c6c044691af15d3d9a5f8237f0ffca86bad7046f96a7b0318341de62ffc7",
        "ac622dfa7b3a5d781a5a4c9147811495a0a2839a3edfe2c5a47ea98d370cb660"),
    "rl/configs/m7e/m7e_s2_v2.toml": ("7becf7103c0eda95f73817822f99b7339dcc9a70efc5af5a90ab68aab7591b83",
        "684dc27abebbc9f4de00f984c3f90607049a6c289fbfe44249273d2579c57bb8",
        "ac622dfa7b3a5d781a5a4c9147811495a0a2839a3edfe2c5a47ea98d370cb660"),
}
# Untrained policy / statistics digests of m7d_s0_v2 (M7d manifest; unchanged since M7d).
PINNED_INITIAL_M7D_S0_V2 = ("68155f41065d243fed9bcdc9e0be71bb0b583595bd1da02f7d9d7cbf42054fa2",
                            "06b1b3703f44e9ef5ac7f68a9751c18e1ea0d32eca22e594695fbceb8b87d251")
# checkpoint.json keys written by the M7e trainer (runs/m7e/m7e_s0_v2/final): a v1 set must keep exactly these.
V1_CHECKPOINT_KEYS = ["checkpoint_schema", "milestone", "label", "created_utc", "num_timesteps", "n_updates",
                      "rollouts_completed", "policy_note", "vecnormalize", "run_id", "purpose", "lineage", "contracts",
                      "horizon", "n_envs", "ppo", "seeds", "executable", "revisions", "m6_flags", "versions",
                      "torch_threads", "lifecycle", "reward_contract", "experiment", "files"]
V1_VECNORM_KEYS = ["norm_obs", "norm_reward", "clip_obs", "clip_reward", "epsilon", "obs_rms_count", "load_rule"]
PARAMETERS = {"v1": 11538, "v2": 76818}


class CaseFailure(AssertionError):
    pass


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise CaseFailure(msg)


class Suite:
    def __init__(self, root: Path):
        self.root = root

    def dir(self, name: str) -> Path:
        d = self.root / name
        d.mkdir(parents=True, exist_ok=False)
        return d


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _experiment(seed: int, arm: str, root: Path, name: str) -> ec.Experiment:
    """The Phase K profile with only the permitted output overrides (run name, output root)."""
    return ec.load_experiment(PHASE_K[(seed, arm)]).with_overrides({"run.name": name, "run.output_root": str(root)})


def _dummy_spec() -> Any:
    from btt_parallel import WorkerSpec

    return WorkerSpec(rank=0, run_id="x", role="test", worker_dir="x", coordination_dir="x", executable="x")


class _V1Env(gym.Env):
    """In-memory env with the btt_policy_obs_v1 space (real policy vectors of synthetic positions). No game."""

    metadata: Dict[str, Any] = {}

    def __init__(self, seed: int = 0):
        from btt_learning import make_policy_observation_space, make_track1_action_space

        self.observation_space = make_policy_observation_space()
        self.action_space = make_track1_action_space()
        self.rng = np.random.default_rng(seed)
        self.t = 0

    def _obs(self) -> np.ndarray:
        import m7g_obs_tests as mot

        state, _ = mot.v1_state(float(self.rng.uniform(-3000, 3000)), float(self.rng.uniform(-2500, 3000)), tick=self.t)
        return state

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        super().reset(seed=seed)
        self.t = 0
        return self._obs(), {}

    def step(self, action):
        self.t += 1
        return self._obs(), 0.0, False, self.t >= 40, {}


def _offline_venv(arm: str, n: int) -> Any:
    from stable_baselines3.common.vec_env import DummyVecEnv

    import m7g_obs_tests as mot

    if arm == "v2":
        return DummyVecEnv([lambda: mot.SyntheticV2Env(horizon=40) for _ in range(n)])
    return DummyVecEnv([(lambda i=i: _V1Env(seed=i)) for i in range(n)])


def _run_meta(cfg: Any, model: Any, *, executable_sha: Optional[str] = None) -> Dict[str, Any]:
    """The run_meta keys save_checkpoint_set copies, built as M7Run.run builds them."""
    import m7_trainer as tr

    exp = cfg.experiment
    return {"run_id": cfg.run_id, "purpose": "test", "lineage": [], "contracts": tr.run_contracts(cfg),
            "horizon": cfg.horizon, "n_envs": cfg.n_envs, "ppo": tr.resolved_ppo_params(model, cfg.policy),
            "seeds": {"base_seed": cfg.base_seed, "scope": "Python / NumPy / PyTorch / SB3 only; never reaches the game"},
            "executable": {"path": str(cfg.executable), "sha256": executable_sha}, "revisions": {},
            "m6_flags": dict(cfg.extra_env), "versions": tr.versions(),
            "torch_threads": {"requested": cfg.torch_threads}, "lifecycle": cfg.lifecycle_json(),
            "experiment": None if exp is None else dict(exp.summary(), compatibility_view=exp.compatibility_view()),
            "policy_network": tr.policy_network_identity(cfg, model)}


def _no_battleship() -> bool:
    from m7_runtime import list_processes_named

    return not list_processes_named()


# -- unit ---------------------------------------------------------------------------------------------------------


def unit_existing_profiles(s: Suite) -> Dict[str, Any]:
    import inspect

    import torch

    import m7_trainer as tr
    import m7d_matrix as mm
    from btt_parallel import WorkerFactory, m7_contracts
    from m7_evaluation import obs_rms_digest, policy_parameter_digest

    found = sorted(p.relative_to(REPO_ROOT).as_posix() for p in (RL_DIR / "configs").rglob("*.toml")
                   if not {"m7g", "m7h", "m7j", "m7k", "m7l", "m7m"} & set(p.relative_to(RL_DIR / "configs").parts))   # M7h/M7j/M7k/M7l/M7m: later
    check(found == sorted(PINNED_PROFILES), f"pre-existing profile set changed: {found}")
    for rel, pinned in PINNED_PROFILES.items():
        exp = ec.load_experiment(REPO_ROOT / rel)
        got = (exp.source.sha256, exp.semantic_fingerprint, exp.compatibility_fingerprint)
        check(got == pinned, f"{rel}: fingerprints {got} != pinned {pinned}")
        check(exp.values["contracts.observation"] == V1 and exp.values["ppo.policy"] == "MlpPolicy", f"{rel}: v1 values")
        check(exp.policy_observation() is None and "policy_observation" not in exp.summary()
              and "policy_observation" not in exp.resolved_json()["resolved"], f"{rel}: gained a v2 identity block")
        check(mo.ms.SPATIAL_ENV not in dict(exp.extra_env) and set(dict(exp.extra_env)) <= set(dict(M6_FLAGS)),
              f"{rel}: native flags {exp.extra_env}")
        check("observation :" not in ec.describe(exp), f"{rel}: the v1 dry run gained the v2 line")
        cfg = tr.config_from_experiment(exp)
        cfg.validate()
        check(cfg.observation == V1 and cfg.policy == tr.POLICY == "MlpPolicy" and not cfg.observation_v2, f"{rel}: cfg")
        check(tr.run_contracts(cfg) == m7_contracts(cfg.horizon, cfg.reward), f"{rel}: run contracts")
        check(type(tr.worker_factory(cfg, _dummy_spec())) is WorkerFactory, f"{rel}: worker factory")
    # The untrained v1 policy and statistics built by the trainer helpers == the M7d manifest digests.
    exp = ec.load_experiment(RL_DIR / "configs" / "m7d" / "m7d_s0_v2.toml")
    cfg = tr.config_from_experiment(exp)
    threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        venv = mm_zero_venv(cfg.n_envs)
        vecnorm = tr.make_vecnormalize(cfg, venv)
        model = tr.make_model(cfg, vecnorm)
        helpers = (policy_parameter_digest(model), obs_rms_digest(vecnorm))
        vecnorm.close()
    finally:
        torch.set_num_threads(threads)
    via_mm = mm.expected_initial_policy_digest(exp, return_obs_rms=True)
    check(helpers == PINNED_INITIAL_M7D_S0_V2 == tuple(via_mm), f"untrained v1 digests {helpers} / {via_mm}")
    src = inspect.getsource(tr.M7Run.run)
    # the fresh-run VecNormalize literal is pinned by the M7d / M7e guards; its v2 keys come from vecnormalize_keys()
    uses = {h: h in src for h in ("worker_factory(c, s)", "VecNormalize(self.venv, training=True, norm_obs=c.norm_obs, "
                                  "norm_reward=False", "**vecnormalize_keys(c)", "make_model(c, self.vecnorm)",
                                  "annotate_model(c, self.model)", "run_contracts(c)",
                                  "resolved_ppo_params(self.model, c.policy)")}
    stale = [t for t in ("WorkerFactory(s)", "M7PPO(POLICY", "m7_contracts(") if t in src]
    check(all(uses.values()) and not stale, f"M7Run.run bypasses the helpers: {uses} stale {stale}")
    check("**vecnormalize_keys(c)" in inspect.getsource(tr.make_vecnormalize), "make_vecnormalize diverged from M7Run")
    check("m7_contracts(" not in inspect.getsource(tr.M7Run._source_checkpoint)
          and "m7_contracts(" not in inspect.getsource(tr.M7Run._evaluate), "resume / evaluation bypass run_contracts")
    return {"profiles": len(PINNED_PROFILES), "untrained_v1": {"policy": helpers[0][:16], "obs_rms": helpers[1][:16]}}


def mm_zero_venv(n: int) -> Any:
    """The offline v1 spaces env of m7d_matrix.expected_initial_policy_digest (zeros; Box(15) + MultiDiscrete)."""
    from stable_baselines3.common.vec_env import DummyVecEnv

    from btt_learning import make_policy_observation_space, make_track1_action_space

    class _Spaces(gym.Env):
        def __init__(self) -> None:
            self.observation_space = make_policy_observation_space()
            self.action_space = make_track1_action_space()

        def reset(self, *, seed=None, options=None):
            super().reset(seed=seed)
            return np.zeros(self.observation_space.shape, dtype=np.float32), {}

        def step(self, action):
            return np.zeros(self.observation_space.shape, dtype=np.float32), 0.0, False, False, {}

    return DummyVecEnv([_Spaces for _ in range(n)])


def unit_phase_k_profiles(s: Suite) -> Dict[str, Any]:
    import m7_trainer as tr
    from btt_parallel import WorkerFactory

    output = {"run.name", "run.notes", "run.output_root"}
    table: Dict[str, Any] = {}
    for seed in (0, 1, 2):
        e1, e2 = ec.load_experiment(PHASE_K[(seed, "v1")]), ec.load_experiment(PHASE_K[(seed, "v2")])
        m7e = ec.load_experiment(M7E[seed])
        check((e1.semantic_fingerprint, e1.compatibility_fingerprint) == (m7e.semantic_fingerprint,
                                                                         m7e.compatibility_fingerprint),
              f"seed {seed}: the v1 control is not the M7e seed-{seed} experiment")
        d1 = {p for p in e1.values if e1.values[p] != m7e.values[p]}
        check(d1 == output, f"seed {seed}: v1 vs M7e differs in {sorted(d1)}")
        d2 = {p for p in e1.values if e1.values[p] != e2.values[p]}
        check(d2 == {"run.name", "run.notes", "contracts.observation", "ppo.policy"}, f"seed {seed}: v2 vs v1 {sorted(d2)}")
        check(e2.values["contracts.observation"] == V2 and e2.values["ppo.policy"] == "MultiInputPolicy", "v2 values")
        check(dict(e2.extra_env) == {**dict(e1.extra_env), "SSB64_RL_SPATIAL": "1"} and
              dict(e1.extra_env) == dict(M6_FLAGS), f"seed {seed}: flags {e1.extra_env} / {e2.extra_env}")
        cd = ec.compare_compatibility(e1.compatibility_view(), e2.compatibility_view())
        check(set(cd) == {"contracts.observation", "ppo.policy", "environment.extra_env"} and not ec.lifecycle_only_diffs(cd),
              f"seed {seed}: compatibility differences {sorted(cd)}")
        po = e2.policy_observation()
        check(po is not None and po["contract_sha256"] == V2_CONTRACT_SHA256 == mo.contract_digest()
              and po["norm_obs_keys"] == list(mo.NORMALIZED_KEYS) and po["network_id"] == "btt_policy_net_v2_multiinput_mlp64"
              and e2.summary()["policy_observation"] == po and e2.resolved_json()["resolved"]["policy_observation"] == po,
              f"seed {seed}: v2 identity {po}")
        check(e1.policy_observation() is None and "policy_observation" not in e1.summary(), "v1 identity block")
        for e in (e1, e2):
            v = e.values
            check(e.reward.contract == "btt_reward_v2" and v["run.total_transitions"] == 3_072_000
                  and v["environment.process_count"] == 5 and e.standby_count == 1 and e.max_game_processes == 10
                  and v["run.base_seed"] == seed and v["checkpoint.interval"] == 102_400 and v["evaluation.interval"] == 0
                  and not v["evaluation.initial"] and not v["evaluation.final"] and v["environment.horizon"] == 3600
                  and v["ppo.net_arch"] == [64, 64] and v["ppo.activation"] == "tanh" and v["run.mode"] == "train"
                  and v["run.output_root"] == "runs/m7g_k", f"{e.name}: frozen Phase K values")
        c1, c2 = tr.config_from_experiment(e1), tr.config_from_experiment(e2)
        c1.validate()
        c2.validate()
        check(not c1.observation_v2 and c2.observation_v2 and c2.policy == "MultiInputPolicy", "trainer configs")
        check(tr.run_contracts(c2) == mo.m7g_contracts(3600, e2.reward), "v2 run contracts")
        check(type(tr.worker_factory(c1, _dummy_spec())) is WorkerFactory
              and type(tr.worker_factory(c2, _dummy_spec())) is mo.M7gWorkerFactory, "worker factories")
        table[f"s{seed}"] = {a: {"semantic": e.semantic_fingerprint[:16], "compatibility": e.compatibility_fingerprint[:16],
                                 "source": e.source.sha256[:16]} for a, e in (("v1", e1), ("v2", e2))}
        table[f"s{seed}"]["m7e"] = {"semantic": m7e.semantic_fingerprint[:16]}
    sems = {v[a]["semantic"] for v in table.values() for a in ARMS}
    comps = {a: {v[a]["compatibility"] for v in table.values()} for a in ARMS}
    check(len(sems) == 6 and all(len(c) == 1 for c in comps.values()) and comps["v1"] != comps["v2"],
          f"fingerprint structure {sems} {comps}")
    dry: Dict[str, int] = {}
    for (seed, arm), path in sorted(PHASE_K.items()):
        rc = subprocess.run([sys.executable, str(RL_DIR / "train_m7.py"), "--config", str(path), "--dry-run"],
                            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=600, check=False)
        line = [x for x in rc.stdout.splitlines() if x.startswith("observation :")]
        check(rc.returncode == 0 and ((arm == "v2") == bool(line)) and "no process launched" in rc.stdout,
              f"{path.name} dry run exit {rc.returncode}: {rc.stdout[-400:]}{rc.stderr[-400:]}")
        dry[path.name] = rc.returncode
    return {"fingerprints": table, "dry_runs": dry}


def unit_config_rejections(s: Suite) -> Dict[str, Any]:
    import m7_trainer as tr
    from m7_evaluation import CheckpointError

    base2 = PHASE_K[(0, "v2")].read_text(encoding="utf-8")
    base1 = PHASE_K[(0, "v1")].read_text(encoding="utf-8")
    mutations = {
        "v2_with_MlpPolicy": (base2, 'policy = "MultiInputPolicy"', 'policy = "MlpPolicy"', "ppo.policy"),
        "v1_with_MultiInputPolicy": (base1, 'policy = "MlpPolicy"', 'policy = "MultiInputPolicy"', "ppo.policy"),
        "unknown_observation": (base2, 'observation = "btt_policy_obs_v2_spatial"', 'observation = "btt_policy_obs_v3"',
                                "contracts.observation"),
        "observation_wrong_case": (base2, 'observation = "btt_policy_obs_v2_spatial"',
                                   'observation = "BTT_POLICY_OBS_V2_SPATIAL"', "contracts.observation"),
        "unknown_policy": (base2, 'policy = "MultiInputPolicy"', 'policy = "CnnPolicy"', "ppo.policy"),
        "v2_without_observation_normalisation": (base2, "normalize_observations = true", "normalize_observations = false",
                                                 "normalize_observations"),
        "v2_other_net_arch": (base2, "net_arch = [64, 64]", "net_arch = [128, 128]", "ppo.net_arch"),
        "v2_relu": (base2, 'activation = "tanh"', 'activation = "relu"', "ppo.activation"),
        "v2_norm_obs_keys_in_toml": (base2, "[ppo.vecnormalize]", '[ppo.vecnormalize]\nnorm_obs_keys = ["state"]',
                                     "unknown key"),
        "v2_spatial_flag_in_toml": (base2, "[environment]", "[environment]\nspatial = true", "unknown key"),
        "v2_reward_normalisation": (base2, "normalize_rewards = false", "normalize_rewards = true", "normalize_rewards"),
    }
    rejected: Dict[str, str] = {}
    for name, (base, old, new, needle) in mutations.items():
        # anchored at a line start: the profiles' header comments quote some of these key lines
        check(base.count("\n" + old) == 1, f"{name}: {old!r} is not one TOML line of the profile")
        text = base.replace("\n" + old, "\n" + new, 1)
        try:
            ec.parse_toml_text(text, source_path=f"<{name}>")
            raise CaseFailure(f"{name}: accepted")
        except ec.ConfigError as exc:
            check(needle in str(exc), f"{name}: message lacks {needle!r}: {exc}")
            rejected[name] = str(exc).splitlines()[1].strip()[:160]
    # M7Config (raw trainer configurations, as tests and the legacy path build them)
    e1, e2 = ec.load_experiment(PHASE_K[(0, "v1")]), ec.load_experiment(PHASE_K[(0, "v2")])
    c1, c2 = tr.config_from_experiment(e1), tr.config_from_experiment(e2)
    bad = {
        "v2_without_spatial_flag": replace(c2, extra_env=M6_FLAGS, experiment=None),
        "v2_MlpPolicy": replace(c2, policy="MlpPolicy", experiment=None),
        "v1_MultiInputPolicy": replace(c1, policy="MultiInputPolicy", experiment=None),
        "v2_norm_obs_false": replace(c2, norm_obs=False, experiment=None),
        "v2_net_arch_128": replace(c2, net_arch=(128, 128), experiment=None),
        "unknown_observation": replace(c2, observation="btt_policy_obs_v3", experiment=None),
        "v1_config_on_v2_profile": replace(c2, observation=V1, policy="MlpPolicy", extra_env=M6_FLAGS),
    }
    for name, cfg in bad.items():
        try:
            cfg.validate()
            raise CaseFailure(f"M7Config {name}: accepted")
        except ValueError as exc:
            rejected[f"M7Config.{name}"] = str(exc)[:160]
    default = tr.M7Config(run_id="default", n_envs=5, total_timesteps=5120)
    default.validate()
    check(default.observation == V1 and default.policy == "MlpPolicy" and dict(default.extra_env) == dict(M6_FLAGS),
          "M7Config defaults are not v1")
    # A v2 run can never resume from a v1 checkpoint (the historical M7e final set): refused before any file exists.
    resume: Dict[str, Any] = {"skipped": "runs/m7e not present"}
    if (HISTORICAL_CKPT / "checkpoint.json").is_file():
        before = {p.name: _sha(p) for p in sorted(HISTORICAL_CKPT.iterdir()) if p.is_file()}
        d = s.root / "unit_config_rejections"
        cfg = replace(c2, run_id="resume_v2_from_v1", runs_dir=d, resume_from=HISTORICAL_CKPT, experiment=None)
        run = tr.M7Run(cfg)
        try:
            run._source_checkpoint()
            raise CaseFailure("a v2 configuration accepted a v1 checkpoint as resume source")
        except CheckpointError as exc:
            msg = str(exc)
        check("policy_observation_contract" in msg and not run.layout.root.exists(), f"resume refusal: {msg[:300]}")
        after = {p.name: _sha(p) for p in sorted(HISTORICAL_CKPT.iterdir()) if p.is_file()}
        check(before == after, "historical checkpoint files changed")
        resume = {"refused": msg[:200], "run_dir_created": run.layout.root.exists()}
    return {"rejected": rejected, "resume_v2_from_v1": resume}


def unit_checkpoint_identity(s: Suite) -> Dict[str, Any]:
    import torch
    from stable_baselines3.common.vec_env import VecNormalize

    import m7_trainer as tr
    from btt_parallel import RunCoordinator, initial_coordination_state, m7_contracts
    from m7_evaluation import (CheckpointError, EvaluationSettings, check_model_identity, check_vecnormalize_identity,
                               checkpoint_observation_contract, evaluate_checkpoint, obs_rms_digest, obs_rms_record,
                               policy_parameter_digest, read_checkpoint_set)

    torch.set_num_threads(1)
    d = s.dir("unit_checkpoint_identity")
    sets: Dict[str, Path] = {}
    cfgs: Dict[str, Any] = {}
    out: Dict[str, Any] = {}
    for arm in ARMS:
        exp = _experiment(0, arm, d, f"ckpt_{arm}")
        cfg = tr.config_from_experiment(exp)
        cfg.validate()
        cfgs[arm] = cfg
        vecnorm = tr.make_vecnormalize(cfg, _offline_venv(arm, cfg.n_envs))
        model = tr.make_model(cfg, vecnorm)
        tr.annotate_model(cfg, model)
        params = int(sum(p.numel() for p in model.policy.parameters()))
        check(params == PARAMETERS[arm], f"{arm}: {params} parameters")
        obs = vecnorm.reset()
        rng = np.random.default_rng(1)
        for _ in range(30):   # statistics only (VecNormalize training mode); no optimizer step
            obs, _r, _d, _i = vecnorm.step(np.stack([rng.integers(0, 9, cfg.n_envs), rng.integers(0, 8, cfg.n_envs)], 1))
        if arm == "v2":
            check(isinstance(vecnorm.obs_rms, dict) and sorted(vecnorm.obs_rms) == sorted(mo.NORMALIZED_KEYS),
                  f"v2 statistics keys {list(vecnorm.obs_rms)}")
            raw = vecnorm.get_original_obs()
            check(all(np.array_equal(obs[k], raw[k]) for k in mo.BINARY_KEYS), "binary keys normalised")
            check(all(not np.array_equal(obs[k], raw[k]) for k in mo.NORMALIZED_KEYS), "continuous keys raw")
        coord = RunCoordinator.create(d / f"coord_{arm}", initial_coordination_state(cfg.run_id, "test", None))
        policy_before, rms_before = policy_parameter_digest(model), obs_rms_digest(vecnorm)
        tr.save_checkpoint_set(d / f"set_{arm}", model, vecnorm, run_meta=_run_meta(cfg, model), coordinator=coord,
                               label="ckpt_test", rollouts=0)
        sets[arm] = d / f"set_{arm}"
        meta = read_checkpoint_set(sets[arm], expected_contracts=tr.run_contracts(cfg))
        check(checkpoint_observation_contract(meta) == cfg.observation, f"{arm}: recorded observation")
        if arm == "v1":
            check(list(meta) == V1_CHECKPOINT_KEYS and list(meta["vecnormalize"]) == V1_VECNORM_KEYS,
                  f"v1 checkpoint.json shape changed: {list(meta)} / {list(meta['vecnormalize'])}")
        else:
            vn = meta["vecnormalize"]
            pn = meta["policy_network"]
            check(list(meta) == V1_CHECKPOINT_KEYS + ["policy_network"] and vn["norm_obs_keys"] == list(mo.NORMALIZED_KEYS)
                  and sorted(vn["obs_rms_counts"]) == sorted(mo.NORMALIZED_KEYS) and vn["obs_rms_count"] > 30,
                  f"v2 metadata {list(meta)} {vn}")
            check(pn["parameters"] == PARAMETERS["v2"] and pn["network_id"] == "btt_policy_net_v2_multiinput_mlp64"
                  and pn["features_dim"] == mo.FLAT_SIZE and pn["policy_class"] == "MultiInputActorCriticPolicy"
                  and pn["observation"]["contract_sha256"] == V2_CONTRACT_SHA256, f"v2 network identity {pn}")
            check(meta["contracts"]["policy_observation_contract_sha256"] == V2_CONTRACT_SHA256
                  and meta["ppo"]["policy"] == "MultiInputPolicy", "v2 contracts / ppo block")
        # reload: identical parameters, statistics, deterministic actions and values
        reloaded = tr.M7PPO.load(str(sets[arm] / "model.zip"), device="cpu")
        check_model_identity(reloaded, cfg.observation)
        check(policy_parameter_digest(reloaded) == policy_before, f"{arm}: parameters changed on reload")
        frozen = VecNormalize.load(str(sets[arm] / "vecnormalize.pkl"), _offline_venv(arm, cfg.n_envs))
        frozen.training, frozen.norm_reward = False, False
        check_vecnormalize_identity(frozen, cfg.observation)
        check(obs_rms_digest(frozen) == rms_before and obs_rms_record(frozen) == obs_rms_record(vecnorm),
              f"{arm}: statistics changed on reload")
        o = frozen.normalize_obs(vecnorm.get_original_obs())
        a1, _ = model.predict(o, deterministic=True)
        a2, _ = reloaded.predict(o, deterministic=True)
        with torch.no_grad():
            v1_ = model.policy.predict_values(model.policy.obs_to_tensor(o)[0]).numpy()
            v2_ = reloaded.policy.predict_values(reloaded.policy.obs_to_tensor(o)[0]).numpy()
        check(np.array_equal(a1, a2) and np.array_equal(v1_, v2_), f"{arm}: predictions differ after reload")
        o2 = frozen.reset()
        for _ in range(10):
            act, _ = reloaded.predict(o2, deterministic=False)
            o2, _r, _d, _i = frozen.step(act)
        check(obs_rms_digest(frozen) == rms_before, f"{arm}: frozen statistics changed while stepping")
        out[arm] = {"parameters": params, "policy": policy_before[:16], "obs_rms": rms_before[:16],
                    "model_zip_bytes": (sets[arm] / "model.zip").stat().st_size,
                    "vecnormalize_bytes": (sets[arm] / "vecnormalize.pkl").stat().st_size,
                    "vecnormalize_record": obs_rms_record(frozen)}
        vecnorm.close()
        frozen.close()
    # cross-arm refusals: contracts, model, statistics
    refusals: Dict[str, str] = {}

    def refused(name: str, fn: Callable[[], Any]) -> None:
        try:
            fn()
        except (CheckpointError, ValueError) as exc:
            refusals[name] = str(exc)[:160]
            return
        raise CaseFailure(f"{name}: accepted")

    refused("contracts_v1_set_as_v2", lambda: read_checkpoint_set(sets["v1"], expected_contracts=tr.run_contracts(cfgs["v2"])))
    refused("contracts_v2_set_as_v1", lambda: read_checkpoint_set(sets["v2"], expected_contracts=tr.run_contracts(cfgs["v1"])))
    refused("model_v1_as_v2", lambda: check_model_identity(tr.M7PPO.load(str(sets["v1"] / "model.zip"), device="cpu"), V2))
    refused("model_v2_as_v1", lambda: check_model_identity(tr.M7PPO.load(str(sets["v2"] / "model.zip"), device="cpu"), V1))
    import pickle

    for a, b in (("v1", V2), ("v2", V1)):
        with open(sets[a] / "vecnormalize.pkl", "rb") as fp:
            stats = pickle.load(fp)
        refused(f"statistics_{a}_as_{b}", lambda: check_vecnormalize_identity(stats, b))
    # evaluator refusals: nothing created, no process launched
    settings = EvaluationSettings(executable=str(EXE), horizon=3600, n_workers=1, extra_env=M6_FLAGS)
    ev_out = d / "eval_must_not_exist"
    refused("evaluate_v1_set_with_v2_settings", lambda: evaluate_checkpoint(sets["v1"], ev_out, settings=replace(
        settings, observation=V2), deterministic_episodes=1, stochastic_episodes=0))
    refused("evaluate_v2_set_with_v1_settings", lambda: evaluate_checkpoint(sets["v2"], ev_out, settings=replace(
        settings, observation=V1), deterministic_episodes=1, stochastic_episodes=0))
    refused("evaluate_v2_set_with_v1_contracts", lambda: evaluate_checkpoint(
        sets["v2"], ev_out, settings=settings, deterministic_episodes=1, stochastic_episodes=0,
        expected_contracts=m7_contracts(3600, cfgs["v2"].reward)))
    # tampered sets: v2 contracts but a v1 model (or v1 statistics), hashes re-recorded -> second line of defence
    import shutil

    for swapped in ("model.zip", "vecnormalize.pkl"):
        t = d / f"tampered_{swapped.split('.')[0]}"
        shutil.copytree(sets["v2"], t)
        shutil.copyfile(sets["v1"] / swapped, t / swapped)
        m = json.loads((t / "checkpoint.json").read_text(encoding="utf-8"))
        m["files"][swapped] = _sha(t / swapped)
        (t / "checkpoint.json").write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
        refused(f"evaluate_v2_contracts_with_v1_{swapped}", lambda t=t: evaluate_checkpoint(
            t, ev_out, settings=settings, deterministic_episodes=1, stochastic_episodes=0))
    check(not ev_out.exists() and _no_battleship(), "a refused evaluation created its directory or launched a process")
    # historical v1 checkpoint (read-only): still v1 through the new identity checks
    hist: Dict[str, Any] = {"skipped": "runs/m7e not present"}
    if (HISTORICAL_CKPT / "checkpoint.json").is_file():
        before = {p.name: _sha(p) for p in sorted(HISTORICAL_CKPT.iterdir()) if p.is_file()}
        meta = read_checkpoint_set(HISTORICAL_CKPT, expected_contracts=m7_contracts(3600, cfgs["v1"].reward))
        check(checkpoint_observation_contract(meta) == V1 and list(meta) == V1_CHECKPOINT_KEYS, "historical metadata")
        model = tr.M7PPO.load(str(HISTORICAL_CKPT / "model.zip"), device="cpu")
        check_model_identity(model, V1)
        refused("historical_model_as_v2", lambda: check_model_identity(model, V2))
        with open(HISTORICAL_CKPT / "vecnormalize.pkl", "rb") as fp:
            stats = pickle.load(fp)
        check_vecnormalize_identity(stats, V1)
        check(obs_rms_record(stats) == {"obs_rms_count": meta["vecnormalize"]["obs_rms_count"]}, "historical record")
        after = {p.name: _sha(p) for p in sorted(HISTORICAL_CKPT.iterdir()) if p.is_file()}
        check(before == after, "historical checkpoint files changed")
        hist = {"checkpoint": "runs/m7e/m7e_s0_v2/final", "observation": V1, "files_unchanged": True}
    return {"arms": out, "refusals": refusals, "historical": hist}


def _fill_synthetic_rollout(model: Any, arm: str, rng: np.random.Generator) -> Dict[str, Any]:
    """Fill the model's rollout buffer with synthetic observations (normalised scale) and the model's own actions /
    values / log-probabilities, exactly as collect_rollouts stores them. Returns the measured inference cost."""
    import torch
    from gymnasium import spaces

    buf = model.rollout_buffer
    buf.reset()
    n = model.n_envs
    space = model.observation_space

    def sample() -> Any:
        if isinstance(space, spaces.Dict):
            return {k: (rng.integers(0, 2, (n,) + sub.shape).astype(np.float32) if k in mo.BINARY_KEYS
                        else rng.normal(0.0, 1.0, (n,) + sub.shape).astype(np.float32)) for k, sub in space.spaces.items()}
        return rng.normal(0.0, 1.0, (n,) + space.shape).astype(np.float32)

    starts = np.ones(n, dtype=np.float32)
    t_inf = 0.0
    for _ in range(model.n_steps):
        obs = sample()
        t0 = time.perf_counter()
        with torch.no_grad():
            actions, values, log_probs = model.policy(model.policy.obs_to_tensor(obs)[0])
        t_inf += time.perf_counter() - t0
        rewards = rng.normal(0.0, 0.1, n).astype(np.float32)
        buf.add(obs, actions.numpy(), rewards, starts, values, log_probs)
        starts = (rng.random(n) < 0.001).astype(np.float32)
    with torch.no_grad():
        last = model.policy.predict_values(model.policy.obs_to_tensor(sample())[0])
    buf.compute_returns_and_advantage(last_values=last, dones=np.zeros(n, dtype=bool))
    obs_bytes = sum(a.nbytes for a in buf.observations.values()) if isinstance(buf.observations, dict) \
        else buf.observations.nbytes
    return {"inference_ms_per_vector_step": round(1e3 * t_inf / model.n_steps, 4), "buffer_observation_bytes": int(obs_bytes)}


def unit_update_path(s: Suite) -> Dict[str, Any]:
    import torch
    from stable_baselines3.common.logger import Logger

    import m7_trainer as tr
    from m7_evaluation import policy_parameter_digest

    torch.set_num_threads(1)   # the Phase K profiles' ppo.torch_threads
    out: Dict[str, Any] = {}
    reps = 3
    for arm in ARMS:
        cfg = tr.config_from_experiment(ec.load_experiment(PHASE_K[(0, arm)]))
        vecnorm = tr.make_vecnormalize(cfg, _offline_venv(arm, cfg.n_envs))
        model = tr.make_model(cfg, vecnorm)   # throwaway: never saved, never stepped on the game
        model.set_logger(Logger(folder=None, output_formats=[]))
        check(type(model.rollout_buffer).__name__ == ("DictRolloutBuffer" if arm == "v2" else "RolloutBuffer"),
              f"{arm}: rollout buffer {type(model.rollout_buffer).__name__}")
        rng = np.random.default_rng(7)
        fill = _fill_synthetic_rollout(model, arm, rng)
        before = policy_parameter_digest(model)
        times = []
        for _ in range(reps):
            model.train()
            times.append(model.m7_train_s[-1])
        metrics = model.m7_train_metrics[-1]
        check(policy_parameter_digest(model) != before and all(np.isfinite(v) for v in metrics.values())
              and {"train/policy_gradient_loss", "train/value_loss", "train/approx_kl"} <= set(metrics),
              f"{arm}: update did not run cleanly: {metrics}")
        # minibatch forward (evaluate_actions on 512 samples), the update's inner cost
        batch = next(model.rollout_buffer.get(cfg.batch_size))
        t0 = time.perf_counter()
        for _ in range(20):
            with torch.no_grad():
                model.policy.evaluate_actions(batch.observations, batch.actions.long())
        fwd = (time.perf_counter() - t0) / 20
        out[arm] = {"parameters": int(sum(p.numel() for p in model.policy.parameters())),
                    "rollout": cfg.rollout_size, "batch": cfg.batch_size, "epochs": cfg.n_epochs,
                    "gradient_steps_per_update": (cfg.rollout_size // cfg.batch_size) * cfg.n_epochs,
                    "update_s": [round(t, 4) for t in times], "update_s_median": round(float(np.median(times)), 4),
                    "minibatch_forward_ms": round(1e3 * fwd, 3), **fill,
                    "final_metrics": {k: round(float(v), 6) for k, v in metrics.items()}}
        vecnorm.close()
        del model
    out["v2_over_v1"] = {"update": round(out["v2"]["update_s_median"] / out["v1"]["update_s_median"], 3),
                         "inference": round(out["v2"]["inference_ms_per_vector_step"]
                                            / out["v1"]["inference_ms_per_vector_step"], 3),
                         "minibatch_forward": round(out["v2"]["minibatch_forward_ms"] / out["v1"]["minibatch_forward_ms"], 3)}
    out["note"] = ("synthetic observations, throwaway models (never saved): PPO update code path and its CPU cost at the "
                   "Phase K geometry, torch threads 1; not a game policy")
    return out


def unit_isolation(s: Suite) -> Dict[str, Any]:
    pattern = re.compile(r"m7g_(fixture|capture|crossing)|FIXTURE_DIR|fixtures['\"\s,/\\()]*m7g|lower_precision|"
                         r"upper_moving_platform|crossing_fixture", re.IGNORECASE)
    files = sorted((RL_DIR / "configs" / "m7g").glob("*.toml")) + [RL_DIR / f for f in (
        "experiment_config.py", "m7_trainer.py", "m7_evaluation.py", "eval_m7.py", "train_m7.py")]
    offenders = [p.name for p in files if pattern.search(p.read_text(encoding="utf-8"))]
    # 6 comparison + 4 extension profiles (campaign step) + the 5 modules; the pilot profiles are checked by
    # rl/m7g_k_campaign_tests.py unit_isolation
    check(len(files) == 15 and not offenders, f"Phase K files reference the crossing fixtures: {offenders}")
    me = Path(__file__).read_text(encoding="utf-8")
    check(not re.search(r"\.learn\(", me), "this suite calls PPO learn()")
    return {"checked": [p.name for p in files]}


# -- game ---------------------------------------------------------------------------------------------------------


def game_v1_historical_eval(s: Suite) -> Dict[str, Any]:
    from btt_parallel import m7_contracts
    from btt_rewards import REWARD_V2
    from m7_evaluation import EvaluationSettings, evaluate_checkpoint

    if not HISTORICAL_EVAL.is_file() or not (HISTORICAL_CKPT / "checkpoint.json").is_file():
        return {"skipped": "runs/m7e (historical M7e evaluation) not present"}
    hist = json.loads(HISTORICAL_EVAL.read_text(encoding="utf-8"))
    hd, hs = hist["modes"]["deterministic"], hist["modes"]["stochastic"]
    check(hd["seed"] == hs["seed"] == 12345 and hs["workers"] == 5 and hist["lifecycle"]["standby_preboot"],
          "historical settings")
    before = {p.name: _sha(p) for p in sorted(HISTORICAL_CKPT.iterdir()) if p.is_file()}
    d = s.dir("game_v1_historical_eval")
    settings = EvaluationSettings(executable=str(EXE), horizon=3600, n_workers=5, seed=12345, extra_env=M6_FLAGS,
                                  standby_preboot=True, standby_count=1)
    res = evaluate_checkpoint(HISTORICAL_CKPT, d / "eval", settings=settings, deterministic_episodes=1,
                              stochastic_episodes=5, expected_contracts=m7_contracts(3600, REWARD_V2),
                              label="m7e_s0_v2_final_recheck")
    keys = ("native_action_digest", "targets_broken", "length", "end_reason", "rank", "worker_episode")
    det = res["modes"]["deterministic"]["episodes"][0]
    check(all(det[k] == hd["episodes"][0][k] for k in keys[:4]), f"deterministic episode differs: {det} vs {hd['episodes'][0]}")
    sto = [{k: e[k] for k in keys} for e in res["modes"]["stochastic"]["episodes"]]
    ref = [{k: e[k] for k in keys} for e in hs["episodes"][:5]]
    check(sto == ref, f"first five stochastic episodes differ: {sto} vs {ref}")
    for m, r in res["modes"].items():
        check(all(r["frozen_check"][k] for k in ("policy_parameters_unchanged", "obs_rms_unchanged"))
              and r["workers_closed_cleanly"] and "policy_observation_contract" not in r, f"{m}: {r['frozen_check']}")
    check("policy_observation_contract" not in res and _no_battleship(), "v1 summary shape / leftover process")
    after = {p.name: _sha(p) for p in sorted(HISTORICAL_CKPT.iterdir()) if p.is_file()}
    check(before == after, "historical checkpoint files changed")
    return {"deterministic": {k: det[k] for k in keys[:4]}, "stochastic_first5": sto,
            "wall_s": res["wall_s"], "historical_executable_note": "M7e ran before the M7f/M7g native diagnostics"}


def _smoke_arm(s: Suite, d: Path, arm: str) -> Dict[str, Any]:
    import torch

    import m7_trainer as tr
    from btt_parallel import RunCoordinator, initial_coordination_state
    from m7_evaluation import read_checkpoint_set
    from m7_runtime import list_processes_named, prepare_worker_runtime, sha256_file, wait_until_no_process
    from m7_vec_env import M7SubprocVecEnv

    torch.set_num_threads(1)
    exp = _experiment(0, arm, d, f"smoke_{arm}")
    cfg = tr.config_from_experiment(exp)
    run = tr.M7Run(cfg)                      # validates the configuration against its profile
    run.layout.create()
    specs = run._specs()
    coord = RunCoordinator.create(run.layout.coordination,
                                  initial_coordination_state(cfg.run_id, "training", cfg.periodic_episodes))
    for spec in specs:
        prepare_worker_runtime(spec.paths()["runtime"], Path(cfg.executable))
    check(dict(specs[0].extra_env).get("SSB64_RL_SPATIAL") == ("1" if arm == "v2" else None), f"{arm}: worker flags")
    t0 = time.perf_counter()
    venv = M7SubprocVecEnv([tr.worker_factory(cfg, sp) for sp in specs], step_timeout=cfg.step_timeout)
    vecnorm = None
    peak = 0
    episodes = 0
    try:
        vecnorm = tr.make_vecnormalize(cfg, venv)
        model = tr.make_model(cfg, vecnorm)
        tr.annotate_model(cfg, model)
        check(type(model.policy).__name__ == ("MultiInputActorCriticPolicy" if arm == "v2" else "ActorCriticPolicy")
              and sum(p.numel() for p in model.policy.parameters()) == PARAMETERS[arm], f"{arm}: model")
        obs = vecnorm.reset()
        raw = vecnorm.get_original_obs()
        if arm == "v2":
            check(sorted(obs) == sorted(mo.KEY_ORDER) and all(obs[k].shape == (cfg.n_envs,) + mo.SHAPES[k] for k in obs)
                  and all(np.array_equal(obs[k], raw[k]) for k in mo.BINARY_KEYS)
                  and float(raw["target_live"].sum()) == 10.0 * cfg.n_envs, f"v2 reset observation {list(obs)}")
        else:
            check(obs.shape == (cfg.n_envs, 15), f"v1 reset observation {obs.shape}")
        for i in range(200):   # untrained stochastic policy; VecNormalize statistics only, no optimizer step
            act, _ = model.predict(obs, deterministic=False)
            obs, _r, dones, _infos = vecnorm.step(act)
            episodes += int(dones.sum())
            if i % 20 == 0:
                peak = max(peak, len(list_processes_named() or []))
        check(model.num_timesteps == 0 and model._n_updates == 0, "the model learned")
        counts = ({k: float(v.count) for k, v in vecnorm.obs_rms.items()} if arm == "v2"
                  else {"box": float(vecnorm.obs_rms.count)})
        check(all(c > 200 * cfg.n_envs for c in counts.values()), f"{arm}: statistics {counts}")
        meta_in = _run_meta(cfg, model, executable_sha=sha256_file(Path(cfg.executable)))
        tr.save_checkpoint_set(run.layout.checkpoint(0), model, vecnorm, run_meta=meta_in, coordinator=coord,
                               label="ckpt_000000000", rollouts=0)
    finally:
        if vecnorm is not None:
            vecnorm.close()
        else:
            venv.close()
    wall = time.perf_counter() - t0
    left = wait_until_no_process(timeout=20.0)
    check(peak <= cfg.lifecycle_json()["max_game_processes"] == 10 and not left, f"{arm}: processes peak {peak} left {left}")
    ckpt = run.layout.checkpoint(0)
    meta = read_checkpoint_set(ckpt, expected_contracts=tr.run_contracts(cfg))
    # evaluation through the CLI with the Phase K profile (its compatibility check included)
    ev = d / f"eval_{arm}"
    rc = subprocess.run([sys.executable, str(RL_DIR / "eval_m7.py"), "checkpoint", str(ckpt), "--out", str(ev),
                         "--config", str(PHASE_K[(0, arm)]), "--deterministic-episodes", "1", "--stochastic-episodes", "2"],
                        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=1800, check=False)
    check(rc.returncode == 0, f"{arm}: eval_m7.py exit {rc.returncode}: {rc.stdout[-800:]}{rc.stderr[-800:]}")
    summ = json.loads((ev / "evaluation_summary.json").read_text(encoding="utf-8"))
    for m, r in summ["modes"].items():
        check(r["frozen_check"]["policy_parameters_unchanged"] and r["frozen_check"]["obs_rms_unchanged"]
              and r["workers_closed_cleanly"] and r["aggregate"]["episodes"] == (1 if m == "deterministic" else 2),
              f"{arm} {m}: {r['frozen_check']} closed {r['workers_closed_cleanly']}")
        check((r.get("policy_observation_contract") == V2 and r["extra_env"].get("SSB64_RL_SPATIAL") == "1")
              if arm == "v2" else "policy_observation_contract" not in r, f"{arm} {m}: observation record")
    if arm == "v2":
        check(summ["policy_observation_contract"] == V2 and summ["policy_network"]["parameters"] == PARAMETERS["v2"],
              "v2 evaluation summary identity")
    else:
        check("policy_observation_contract" not in summ, "v1 evaluation summary gained a key")
    check(_no_battleship(), f"{arm}: leftover BattleShip after evaluation")
    return {"checkpoint": str(ckpt), "vector_steps": 200, "episodes_finished": episodes, "peak_processes": peak,
            "statistics_counts": counts, "wall_s": round(wall, 1), "checkpoint_meta_keys": list(meta),
            "evaluation": {m: {k: r["aggregate"][k] for k in ("episodes", "targets_mean", "falls", "horizon_truncations")}
                           for m, r in summ["modes"].items()}}


def game_wiring_smoke(s: Suite) -> Dict[str, Any]:
    d = s.dir("game_wiring_smoke")
    out = {arm: _smoke_arm(s, d, arm) for arm in ARMS}
    # cross-arm --config: the v2 checkpoint with the v1 profile (and vice versa) is refused before anything runs
    refusals = {}
    for arm, other in (("v2", "v1"), ("v1", "v2")):
        ev = d / f"cross_{arm}_with_{other}"
        rc = subprocess.run([sys.executable, str(RL_DIR / "eval_m7.py"), "checkpoint", out[arm]["checkpoint"], "--out",
                             str(ev), "--config", str(PHASE_K[(0, other)]), "--deterministic-episodes", "1",
                             "--stochastic-episodes", "0"], cwd=str(REPO_ROOT), capture_output=True, text=True,
                            timeout=600, check=False)
        check(rc.returncode == 2 and "not compatible" in rc.stdout and "contracts.observation" in rc.stdout
              and not ev.exists(), f"cross {arm}/{other}: exit {rc.returncode} {rc.stdout[-400:]}")
        refusals[f"{arm}_checkpoint_with_{other}_profile"] = rc.stdout.strip().splitlines()[-1][:200]
    check(_no_battleship(), "leftover BattleShip")
    return {"arms": out, "cross_refusals": refusals}


def game_target_diag_probe(s: Suite) -> Dict[str, Any]:
    from m7_evaluation import EvaluationSettings, evaluate_checkpoint

    smoke = s.root / "game_wiring_smoke"
    if not smoke.is_dir():
        game_wiring_smoke(s)
    d = s.dir("game_target_diag_probe")
    out = {}
    for arm in ARMS:
        ckpt = smoke / f"smoke_{arm}" / "checkpoints" / "ckpt_000000000"
        settings = EvaluationSettings(executable=str(EXE), horizon=3600, n_workers=2, seed=12345,
                                      extra_env=M6_FLAGS + (("SSB64_RL_TARGET_DIAG", "1"),),
                                      standby_preboot=True, standby_count=1)
        res = evaluate_checkpoint(ckpt, d / f"eval_{arm}", settings=settings, deterministic_episodes=0,
                                  stochastic_episodes=2, preserve_all=True)
        r = res["modes"]["stochastic"]
        check(r["aggregate"]["episodes"] == 2 and r["workers_closed_cleanly"] and r["frozen_check"]["obs_rms_unchanged"]
              and not r["aggregate"].get("lifecycle_failures"), f"{arm}: {r['aggregate']}")
        out[arm] = {"aggregate": {k: r["aggregate"][k] for k in ("episodes", "targets_mean", "falls", "horizon_truncations",
                                                                 "lifecycle_failures")},
                    "extra_env": dict(settings.extra_env) if arm == "v1" else r.get("extra_env")}
    check(_no_battleship(), "leftover BattleShip")
    return out


UNIT_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "unit_existing_profiles": unit_existing_profiles, "unit_phase_k_profiles": unit_phase_k_profiles,
    "unit_config_rejections": unit_config_rejections, "unit_checkpoint_identity": unit_checkpoint_identity,
    "unit_update_path": unit_update_path, "unit_isolation": unit_isolation,
}
GAME_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "game_v1_historical_eval": game_v1_historical_eval, "game_wiring_smoke": game_wiring_smoke,
    "game_target_diag_probe": game_target_diag_probe,
}
ALL_CASES = {**UNIT_CASES, **GAME_CASES}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cases", nargs="*", help="case names, 'unit' or 'game' (default: all)")
    ap.add_argument("--root", default=None)
    args = ap.parse_args(argv)
    names: List[str] = []
    for c in args.cases or list(ALL_CASES):
        names += list(UNIT_CASES) if c == "unit" else list(GAME_CASES) if c == "game" else [c]
    unknown = [n for n in names if n not in ALL_CASES]
    if unknown:
        ap.error(f"unknown cases {unknown}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = (Path(args.root) if args.root else REPO_ROOT / "runs" / "_tests" / f"m7g_k_{stamp}").resolve()
    root.mkdir(parents=True, exist_ok=True)
    if any(n in GAME_CASES for n in names):
        from m7_runtime import install_kill_on_close_job

        leaked = sorted(k for k in os.environ if k.upper().startswith("SSB64_"))
        if leaked:
            raise SystemExit(f"SSB64_* variables in the environment would leak into every child: {leaked}")
        if not _no_battleship():
            raise SystemExit("BattleShip already running; the game cases need a quiet machine")
        install_kill_on_close_job()
    suite = Suite(root)
    results: Dict[str, Any] = {}
    for name in names:
        t0 = time.perf_counter()
        try:
            details = ALL_CASES[name](suite)
            results[name] = {"status": "PASS", "seconds": round(time.perf_counter() - t0, 1), "details": details}
        except Exception as exc:
            results[name] = {"status": "FAIL", "seconds": round(time.perf_counter() - t0, 1),
                             "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-2500:]}
        print(f"{results[name]['status']}  {name}  ({results[name]['seconds']} s)"
              + (f"  {results[name].get('error')}" if results[name]["status"] != "PASS" else ""), flush=True)
    ok = all(r["status"] == "PASS" for r in results.values())
    with open(root / "m7g_k_tests_results.json", "w", encoding="utf-8", newline="\n") as fp:
        json.dump({"schema": "battleship_m7g_k_tests_v1", "utc": stamp, "results": results, "ok": ok}, fp, indent=1,
                  default=str)
        fp.write("\n")
    print(f"m7g_k_tests: {sum(r['status'] == 'PASS' for r in results.values())}/{len(results)} PASS -> {root}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
