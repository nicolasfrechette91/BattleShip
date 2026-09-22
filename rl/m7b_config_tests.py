#!/usr/bin/env python3
"""M7b ROM-independent tests: experiment configuration, fingerprints, resume compatibility, reward contracts.

    python rl/m7b_config_tests.py            # every case
    python rl/m7b_config_tests.py <case>...  # selected cases

No BattleShip process is launched by any case here (the game-backed cases
live in rl/m7b_smoke.py). Outputs go under runs/_m7b_tests_<utc>/
(git-ignored). Cases that need PyTorch / Stable-Baselines3 import them
inside the case only.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import experiment_config as ec  # noqa: E402
from btt_rewards import (  # noqa: E402
    REWARD_V1,
    REWARD_V2,
    RewardContract,
    RewardContractError,
    custom_reward_id,
    expected_return,
    make_reward_contract,
    reward_contract_from_json,
    reward_step,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
V1_TOML = REPO_ROOT / "rl" / "configs" / "m7_mario_us_reward_v1.toml"
V2_TOML = REPO_ROOT / "rl" / "configs" / "m7_mario_us_reward_v2.toml"
PILOT_CHECKPOINT = REPO_ROOT / "runs" / "m7a_pilot_n5" / "final" / "checkpoint.json"
TAS_STEPS = 447          # steps of the authoritative 7.43 replay (10 targets, clear)
TAS_TARGET_TICKS = (51, 87, 142, 163, 275, 316, 358, 368, 432, 446)   # consumed ticks of the target breaks (M5)
FALL_STEPS = 432         # the known scripted fall: 432 steps, 0 targets (M7a fall_regression)
LEGACY_PILOT_ARGS = {"n_envs": 5, "run_id": "m7a_pilot_n5", "seed": 0, "horizon": 3600, "periodic_episodes": 10,
                     "eval_workers": None, "eval_seed": 12345, "eval_stochastic_episodes": 20,
                     "eval_deterministic_episodes": 2, "checkpoint_interval": None, "runs_dir": None, "exe": None}


class CaseFailure(AssertionError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CaseFailure(message)


def expect_error(fn: Callable[[], Any], *needles: str) -> str:
    """fn must raise ConfigError / RewardContractError / ValueError whose message contains every needle."""
    try:
        fn()
    except (ec.ConfigError, RewardContractError, ValueError) as exc:
        text = str(exc)
        for n in needles:
            check(n in text, f"error message lacks {n!r}: {text[:400]}")
        return text
    raise CaseFailure(f"no error raised (expected {needles})")


class Suite:
    def __init__(self, root: Path):
        self.root = root
        self.results: Dict[str, Any] = {}

    def dir(self, name: str) -> Path:
        d = self.root / name
        d.mkdir(parents=True, exist_ok=False)
        return d


def v1_values() -> Dict[str, Any]:
    return dict(ec.load_experiment(V1_TOML).values)


def variant(values: Dict[str, Any], **changes: Any) -> ec.Experiment:
    """Re-parse the schema values with dotted-path changes (None deletes the key)."""
    v = dict(values)
    for k, val in changes.items():
        if val is None:
            v.pop(k, None)
        else:
            v[k] = val
    return ec.parse_toml_text(ec.to_toml_text(v))


def raw_variant(values: Dict[str, Any], extra: Dict[str, Any]) -> ec.Experiment:
    """Build from a nested raw dict (for unknown keys / tables)."""
    raw = {"schema": ec.SCHEMA_ID, **ec._nest(values)}
    for path, val in extra.items():
        node = raw
        parts = path.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = val
    return ec.build_experiment(raw, source=ec.SourceInfo("toml", None, "0" * 64, 0), toml_text="")


# -- cases ------------------------------------------------------------------------------------------------------


def valid_profiles(suite: Suite) -> Dict[str, Any]:
    v1, v2 = ec.load_experiment(V1_TOML), ec.load_experiment(V2_TOML)
    check(v1.reward == REWARD_V1 and v2.reward == REWARD_V2, "profiles do not resolve to the canonical contracts")
    check(v1.reward.canonical and v2.reward.canonical, "canonical flag")
    for exp in (v1, v2):
        v = exp.values
        check((exp.process_count, v["ppo.rollout_size"], v["ppo.n_steps"], v["ppo.batch_size"], v["ppo.n_epochs"],
               v["ppo.gamma"], v["ppo.gae_lambda"], v["ppo.learning_rate"], v["ppo.clip_range"], v["ppo.net_arch"],
               v["ppo.activation"], v["ppo.device"], v["ppo.torch_threads"], v["ppo.vecnormalize.normalize_observations"],
               v["ppo.vecnormalize.normalize_rewards"], v["ppo.vecnormalize.clip_obs"])
              == (5, 5120, 1024, 512, 10, 0.999, 0.995, 3e-4, 0.2, [64, 64], "tanh", "cpu", 1, True, False, 10.0),
              f"{exp.name}: resolved PPO values differ from the M7a pilot")
        check(v["environment.horizon"] == 3600 and v["environment.position_delta_threshold"] == 300.0
              and v["run.total_transitions"] == 1_024_000 and v["checkpoint.interval"] == 51200
              and v["evaluation.interval"] == 102400 and v["evaluation.random_baseline_episodes"] == 100
              and dict(exp.extra_env) == {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1"}, f"{exp.name}: environment")
        check(exp.task["id"] == "ssb64_us_mario_btt_v1" and exp.executable.name == "BattleShip.exe", "task")
        check(exp.executable == REPO_ROOT / "build-us" / "Release" / "BattleShip.exe", "executable path resolution")
        check(exp.run_dir == REPO_ROOT / "runs" / exp.name, "run dir resolution")
        check(len(exp.semantic_fingerprint) == 64 and len(exp.source.sha256) == 64, "fingerprint shape")
        resolved = exp.resolved_json()
        check(resolved["resolved"]["reward"] == exp.reward.to_json() and resolved["config"]["ppo"]["gamma"] == 0.999, "resolved json")
        json.dumps(resolved)  # serialisable
    diff = {k for k in v1.values if v1.values[k] != v2.values[k]}
    check(diff == {"run.name", "run.notes", "contracts.reward", "reward.failure_penalty"}, f"v1/v2 differ in {diff}")
    check(v1.semantic_fingerprint != v2.semantic_fingerprint and v1.compatibility_fingerprint != v2.compatibility_fingerprint,
          "reward change must change both fingerprints")
    return {"v1": v1.summary(), "v2": v2.summary()}


def validation_errors(suite: Suite) -> Dict[str, Any]:
    base = v1_values()
    out = {}
    out["unknown_key"] = expect_error(lambda: raw_variant(base, {"ppo.learning_rat": 0.1}), "ppo.learning_rat", "unknown key")
    out["unknown_table"] = expect_error(lambda: raw_variant(base, {"curriculum.stage": 1}), "curriculum.stage", "unknown key")
    out["missing"] = expect_error(lambda: variant(base, **{"ppo.gamma": None}), "ppo.gamma", "missing required key")
    out["bad_type_int"] = expect_error(lambda: variant(base, **{"ppo.batch_size": 512.0}), "ppo.batch_size = 512.0", "expected an integer")
    out["bad_type_bool"] = expect_error(lambda: variant(base, **{"environment.no_render": 1}), "environment.no_render = 1", "expected a boolean")
    out["bad_type_str"] = expect_error(lambda: variant(base, **{"run.name": 5}), "run.name = 5", "expected a string")
    out["bad_type_list"] = expect_error(lambda: variant(base, **{"ppo.net_arch": [64.0, 64]}), "ppo.net_arch", "list of integers")
    out["enum"] = expect_error(lambda: variant(base, **{"ppo.activation": "gelu"}), "ppo.activation = \"gelu\"", "must be one of")
    out["range_low"] = expect_error(lambda: variant(base, **{"ppo.gamma": 0.0}), "ppo.gamma = 0.0", "must be > 0.0")
    out["range_high"] = expect_error(lambda: variant(base, **{"ppo.clip_range": 1.5}), "ppo.clip_range = 1.5", "must be <= 1.0")
    out["non_finite"] = expect_error(lambda: ec.parse_toml_text(ec.to_toml_text(base).replace("gamma = 0.999", "gamma = inf")),
                                     "ppo.gamma = inf", "finite")
    out["nan"] = expect_error(lambda: ec.parse_toml_text(ec.to_toml_text(base).replace("clip_obs = 10.0", "clip_obs = nan")),
                              "ppo.vecnormalize.clip_obs", "finite")
    out["schema"] = expect_error(lambda: ec.parse_toml_text(ec.to_toml_text(base).replace(ec.SCHEMA_ID, "other_v9")),
                                 "schema = \"other_v9\"")
    out["syntax"] = expect_error(lambda: ec.parse_toml_text("schema = [unterminated"), "TOML syntax error")
    out["process_count_zero"] = expect_error(lambda: variant(base, **{"environment.process_count": 0}),
                                             "environment.process_count = 0", "must be >= 1")
    out["process_count_high"] = expect_error(lambda: variant(base, **{"environment.process_count": 33}),
                                             "environment.process_count = 33", "<= 32")
    out["seed_negative"] = expect_error(lambda: variant(base, **{"run.base_seed": -1}), "run.base_seed = -1")
    out["reward_norm"] = expect_error(lambda: variant(base, **{"ppo.vecnormalize.normalize_rewards": True}),
                                      "ppo.vecnormalize.normalize_rewards = True")
    out["device"] = expect_error(lambda: variant(base, **{"ppo.device": "cuda"}), "ppo.device = \"cuda\"")
    out["mode"] = expect_error(lambda: variant(base, **{"run.mode": "evaluate"}), "run.mode = \"evaluate\"")
    out["run_name_slash"] = expect_error(lambda: variant(base, **{"run.name": "a/b"}), "run.name = \"a/b\"")
    out["run_name_empty"] = expect_error(lambda: variant(base, **{"run.name": ""}), "run.name = \"\"")
    out["resume_without_source"] = expect_error(lambda: variant(base, **{"run.mode": "resume"}), "resume.source_checkpoint = \"\"")
    out["source_without_resume"] = expect_error(lambda: variant(base, **{"resume.source_checkpoint": "runs/x/final"}),
                                                "resume.source_checkpoint = \"runs/x/final\"", "run.mode")
    out["eval_without_episodes"] = expect_error(lambda: variant(base, **{"evaluation.deterministic_episodes": 0,
                                                                          "evaluation.stochastic_episodes": 0}),
                                                "evaluation.stochastic_episodes = 0")
    # Every message names the field path and the offending value; several problems are reported together.
    multi = expect_error(lambda: variant(base, **{"ppo.gamma": 2.0, "ppo.n_epochs": 0, "task.player": 9}),
                         "ppo.gamma = 2.0", "ppo.n_epochs = 0", "task.player = 9")
    out["multiple"] = multi
    return {k: v.splitlines()[1][:160] if "\n" in v else v[:160] for k, v in out.items()}


def path_resolution(suite: Suite) -> Dict[str, Any]:
    base = v1_values()
    rel = variant(base, **{"run.output_root": "runs/sub", "environment.executable": "build-us/Release/BattleShip.exe"})
    check(rel.output_root == REPO_ROOT / "runs" / "sub", f"relative output root resolves against the repo root: {rel.output_root}")
    absolute = str(REPO_ROOT / "runs" / "abs")
    ab = variant(base, **{"run.output_root": absolute})
    check(ab.output_root == Path(absolute), "absolute output root kept")
    check(variant(base, **{"environment.worker_runtime_root": "runs/workers_elsewhere"}).worker_runtime_root
          == REPO_ROOT / "runs" / "workers_elsewhere", "worker root resolution")
    # Path safety: the repository root, its parents, the executable directory, source directories, the same dir twice.
    out = {}
    out["repo_root"] = expect_error(lambda: variant(base, **{"run.output_root": "."}), "run.output_root = \".\"", "repository root")
    out["parent"] = expect_error(lambda: variant(base, **{"run.output_root": ".."}), "run.output_root = \"..\"")
    out["exe_dir"] = expect_error(lambda: variant(base, **{"run.output_root": "build-us/Release/runs"}),
                                  "run.output_root = \"build-us/Release/runs\"", "executable directory")
    out["source_dir"] = expect_error(lambda: variant(base, **{"run.output_root": "rl/configs/out"}), "source directory")
    out["whitespace"] = expect_error(lambda: variant(base, **{"run.output_root": "runs "}), "whitespace")
    out["tilde"] = expect_error(lambda: variant(base, **{"run.output_root": "~/runs"}), "'~'")
    out["wildcard"] = expect_error(lambda: variant(base, **{"environment.executable": "build-us/Release/BattleShip*.exe"}),
                                   "environment.executable", "wildcard")
    out["empty_exe"] = expect_error(lambda: variant(base, **{"environment.executable": ""}), "environment.executable = \"\"")
    out["jp_exe"] = expect_error(lambda: variant(base, **{"environment.executable": "build-jp/Release/BattleShip-JP.exe"}),
                                 "environment.executable", "BattleShip.exe")
    out["same_roots"] = expect_error(lambda: variant(base, **{"environment.worker_runtime_root": "runs"}),
                                     "environment.worker_runtime_root", "equals run.output_root")
    return {"relative_output_root": str(rel.output_root), **{k: v.splitlines()[1][:160] for k, v in out.items()}}


def fingerprints(suite: Suite) -> Dict[str, Any]:
    v1 = ec.load_experiment(V1_TOML)
    text = V1_TOML.read_text(encoding="utf-8")
    # Formatting and comments only: the source fingerprint changes, the semantic fingerprint does not.
    reformatted = ("# a new leading comment\n" + text.replace("gamma = 0.999", "gamma   =   0.999   # inline comment")
                   .replace("learning_rate = 3e-4", "learning_rate = 0.0003").replace("\n[ppo]\n", "\n\n[ppo]\n"))
    r = ec.parse_toml_text(reformatted)
    check(r.source.sha256 != v1.source.sha256, "source fingerprint must change with the bytes")
    check(r.semantic_fingerprint == v1.semantic_fingerprint, "semantic fingerprint must ignore comments and formatting")
    check(r.compatibility_fingerprint == v1.compatibility_fingerprint, "compatibility fingerprint must ignore formatting")
    # Key order does not matter either.
    lines = text.splitlines()
    i = lines.index("gamma = 0.999")
    j = lines.index("gae_lambda = 0.995")
    lines[i], lines[j] = lines[j], lines[i]
    reordered = ec.parse_toml_text("\n".join(lines) + "\n")
    check(reordered.semantic_fingerprint == v1.semantic_fingerprint, "key order must not change the semantic fingerprint")
    # Output-only and operational fields do not change the semantic fingerprint.
    ops = variant(v1.values, **{"run.name": "other", "run.notes": "x", "run.output_root": "runs/elsewhere",
                                "checkpoint.interval": 25600, "evaluation.interval": 51200, "evaluation.workers": 3,
                                "environment.request_timeout_s": 12.0, "ppo.torch_threads": 2,
                                "artifacts.retain_failed_cap": 5})
    check(ops.semantic_fingerprint == v1.semantic_fingerprint, "operational/output fields leaked into the semantic fingerprint")
    check(ops.source.sha256 != v1.source.sha256, "source changed")
    # Behaviour changes do change it (and the compatibility fingerprint for immutable fields only).
    changed = {}
    for path, value in (("ppo.gamma", 0.99), ("ppo.net_arch", [128, 128]), ("environment.horizon", 1800),
                        ("run.base_seed", 1), ("run.total_transitions", 2_048_000), ("evaluation.seed", 7),
                        ("environment.position_delta_threshold", 250.0), ("artifacts.periodic_episodes", 5),
                        ("ppo.vecnormalize.clip_obs", 5.0), ("environment.raphnet_disable", False)):
        e = variant(v1.values, **{path: value})
        changed[path] = {"semantic_changed": e.semantic_fingerprint != v1.semantic_fingerprint,
                         "compat_changed": e.compatibility_fingerprint != v1.compatibility_fingerprint}
        check(changed[path]["semantic_changed"], f"{path}: semantic fingerprint unchanged")
        expect_compat = ec.FIELD_BY_PATH[path].cls == "immutable"
        check(changed[path]["compat_changed"] == expect_compat, f"{path}: compat change {changed[path]} vs class")
    # Custom reward: noncanonical identity referencing its own value fingerprint; never v1/v2.
    custom = variant(v1.values, **{"contracts.reward": "custom", "reward.failure_penalty": -2.0})
    check(custom.reward.contract == custom_reward_id(custom.reward.values()) and custom.reward.contract.startswith("btt_reward_custom_"),
          f"custom id {custom.reward.contract}")
    check(not custom.reward.canonical and custom.semantic_fingerprint != v1.semantic_fingerprint, "custom must not look canonical")
    same_values_as_v2 = variant(v1.values, **{"contracts.reward": "custom", "reward.failure_penalty": -5.0})
    check(same_values_as_v2.reward.contract != REWARD_V2.contract, "custom with v2 values must not be called v2")
    # Fingerprint determinism across processes (canonical JSON).
    code = ("import sys; sys.path.insert(0, r'%s'); import experiment_config as ec; "
            "print(ec.load_experiment(r'%s').semantic_fingerprint)" % (REPO_ROOT / "rl", V1_TOML))
    other = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=True).stdout.strip()
    check(other == v1.semantic_fingerprint, "semantic fingerprint differs across interpreter processes")
    return {"v1_source": v1.source.sha256, "v1_semantic": v1.semantic_fingerprint, "v1_compat": v1.compatibility_fingerprint,
            "reformatted_source": r.source.sha256, "changed": changed, "custom_id": custom.reward.contract}


def rollout_geometry(suite: Suite) -> Dict[str, Any]:
    base = v1_values()
    out = {}
    out["batch"] = expect_error(lambda: variant(base, **{"ppo.batch_size": 500}), "ppo.batch_size = 500", "must divide")
    out["batch_large"] = expect_error(lambda: variant(base, **{"ppo.batch_size": 10240}), "ppo.batch_size = 10240")
    out["n_steps"] = expect_error(lambda: variant(base, **{"ppo.n_steps": 1000}), "ppo.rollout_size = 5120", "1000 * 5")
    out["process_count"] = expect_error(lambda: variant(base, **{"environment.process_count": 4}), "ppo.rollout_size", "1024 * 4")
    out["total"] = expect_error(lambda: variant(base, **{"run.total_transitions": 1_024_001}), "run.total_transitions = 1024001")
    out["checkpoint"] = expect_error(lambda: variant(base, **{"checkpoint.interval": 5000}), "checkpoint.interval = 5000")
    out["eval_vs_ckpt"] = expect_error(lambda: variant(base, **{"evaluation.interval": 51200, "checkpoint.interval": 102400}),
                                       "evaluation.interval = 51200", "checkpoint.interval")
    out["eval_no_ckpt"] = expect_error(lambda: variant(base, **{"checkpoint.interval": 0}), "evaluation.interval = 102400")
    ok4 = variant(base, **{"environment.process_count": 4, "ppo.n_steps": 1280})
    check(ok4.rollout_size == 5120 and ok4.values["ppo.n_steps"] == 1280, "N=4 geometry")
    # Port blocks: overlap with the dynamic range or 16-bit overflow.
    out["ports_dynamic"] = expect_error(lambda: variant(base, **{"environment.port_block_base": 49000}),
                                        "environment.port_block_base = 49000", "dynamic port range")
    out["ports_overflow"] = expect_error(lambda: variant(base, **{"environment.port_block_base": 65000,
                                                                  "environment.port_block_size": 4096}),
                                         "environment.port_block_size = 4096", "65535")
    return {k: v.splitlines()[1][:160] for k, v in out.items()}


def canonical_reward_enforcement(suite: Suite) -> Dict[str, Any]:
    base = v1_values()
    out = {}
    out["v1_with_penalty"] = expect_error(lambda: variant(base, **{"reward.failure_penalty": -5.0}),
                                          "contracts.reward = \"btt_reward_v1\"", "frozen values", "failure_penalty")
    out["v1_target_value"] = expect_error(lambda: variant(base, **{"reward.target_broken": 2.0}), "btt_reward_v1", "target_broken")
    out["v2_without_penalty"] = expect_error(lambda: variant(base, **{"contracts.reward": "btt_reward_v2"}),
                                             "btt_reward_v2", "failure_penalty")
    out["v3_unknown"] = expect_error(lambda: variant(base, **{"contracts.reward": "btt_reward_v3"}), "contracts.reward = \"btt_reward_v3\"")
    out["custom_wrong_id"] = expect_error(lambda: make_reward_contract("btt_reward_custom_000000000000",
                                                                       {"target_broken": 1.0, "per_step": -0.001,
                                                                        "clear_bonus": 10.0, "failure_penalty": -2.0}),
                                          "does not match its values")
    out["custom_range"] = expect_error(lambda: variant(base, **{"contracts.reward": "custom", "reward.failure_penalty": 1.0}),
                                       "reward.failure_penalty = 1.0", "must be <= 0.0")
    out["custom_nan"] = expect_error(lambda: make_reward_contract("custom", {"target_broken": float("nan"), "per_step": -0.001,
                                                                             "clear_bonus": 10.0, "failure_penalty": 0.0}),
                                     "finite")
    ok = variant(base, **{"contracts.reward": "custom", "reward.per_step": -0.002})
    check(ok.reward.per_step == -0.002 and ok.reward.contract == custom_reward_id(ok.reward.values()), "custom contract values")
    reparsed = make_reward_contract(ok.reward.contract, ok.reward.values())
    check(reparsed == ok.reward, "a derived custom id round-trips with its values")
    # Stored records: legacy v1 without failure_penalty is v1 (0.0); a v2 record needs its values; never reinterpreted.
    legacy = reward_contract_from_json({"contract": "btt_reward_v1", "target_broken": 1.0, "per_step": -0.001, "clear_bonus": 10.0})
    check(legacy == REWARD_V1, "legacy v1 record normalisation")
    out["legacy_v2_missing"] = expect_error(lambda: reward_contract_from_json({"contract": "btt_reward_v2", "target_broken": 1.0,
                                                                               "per_step": -0.001, "clear_bonus": 10.0}),
                                            "lacks failure_penalty")
    out["v2_wrong_stored"] = expect_error(lambda: reward_contract_from_json(dict(REWARD_V2.to_json(), failure_penalty=-1.0)),
                                          "btt_reward_v2", "frozen")
    out["id_disagreement"] = expect_error(lambda: reward_contract_from_json(REWARD_V1.to_json(), contract_id="btt_reward_v2"),
                                          "disagrees")
    check(reward_contract_from_json(None) == REWARD_V1 and reward_contract_from_json(None, contract_id="btt_reward_v1") == REWARD_V1,
          "missing record defaults to v1 only for v1")
    out["missing_v2_record"] = expect_error(lambda: reward_contract_from_json(None, contract_id="btt_reward_v2"), "no reward_constants")
    return {k: (v.splitlines()[1] if "\n" in v else v)[:160] for k, v in out.items()} | {"custom_ok": ok.reward.to_json()}


def task_contract_rejection(suite: Suite) -> Dict[str, Any]:
    base = v1_values()
    out = {}
    out["task_id"] = expect_error(lambda: variant(base, **{"task.id": "ssb64_us_fox_btt_v1"}), "task.id = \"ssb64_us_fox_btt_v1\"")
    out["jp"] = expect_error(lambda: variant(base, **{"task.game_version": "jp"}), "task.game_version = \"jp\"", "requires \"us\"")
    out["character"] = expect_error(lambda: variant(base, **{"task.character": "fox"}), "task.character = \"fox\"", "requires \"mario\"")
    out["stage"] = expect_error(lambda: variant(base, **{"task.stage": "btp_mario"}), "task.stage = \"btp_mario\"")
    out["player"] = expect_error(lambda: variant(base, **{"task.player": 1}), "task.player = 1", "requires 0")
    out["costume"] = expect_error(lambda: variant(base, **{"task.costume": 3}), "task.costume = 3")
    out["unknown_character"] = expect_error(lambda: variant(base, **{"task.character": "waluigi"}), "task.character = \"waluigi\"", "one of")
    out["observation"] = expect_error(lambda: variant(base, **{"contracts.observation": "btt_policy_obs_v2"}),
                                      "contracts.observation = \"btt_policy_obs_v2\"")
    out["action"] = expect_error(lambda: variant(base, **{"contracts.action": "btt_raw_b8_s161_v1"}),
                                 "contracts.action = \"btt_raw_b8_s161_v1\"")
    out["protocol"] = expect_error(lambda: variant(base, **{"contracts.protocol_version": 2}), "contracts.protocol_version = 2")
    out["artifact"] = expect_error(lambda: variant(base, **{"contracts.artifact_schema": 2}), "contracts.artifact_schema = 2")
    out["policy"] = expect_error(lambda: variant(base, **{"ppo.policy": "CnnPolicy"}), "ppo.policy = \"CnnPolicy\"")
    return {k: v.splitlines()[1][:160] for k, v in out.items()}


def _tree_snapshot(root: Path) -> Dict[str, Any]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            out[str(p.relative_to(root))] = (st.st_size, st.st_mtime_ns)
        else:
            out[str(p.relative_to(root)) + "/"] = None
    return out


def dry_run_non_mutation(suite: Suite) -> Dict[str, Any]:
    d = suite.dir("dry_run")
    cwd = d / "cwd"
    cwd.mkdir()
    runs = REPO_ROOT / "runs"
    before_runs = {p.name: p.stat().st_mtime_ns for p in runs.iterdir()} if runs.exists() else {}
    before_cfg = _tree_snapshot(REPO_ROOT / "rl" / "configs")
    outputs = {}
    for label, argv in (("toml_v1", ["--config", str(V1_TOML), "--dry-run"]),
                        ("toml_v2_overrides", ["--config", str(V2_TOML), "--dry-run", "--run-id", "m7b_dry", "--output-root",
                                               "runs/dry"]),
                        ("legacy_pilot", ["pilot", "--n-envs", "5", "--run-id", "m7a_pilot_n5", "--dry-run"]),
                        ("legacy_train", ["train", "--n-envs", "2", "--total-timesteps", "10240", "--horizon", "600", "--dry-run"])):
        r = subprocess.run([sys.executable, str(REPO_ROOT / "rl" / "train_m7.py"), *argv], cwd=str(cwd), capture_output=True,
                           text=True, timeout=300, check=False)
        check(r.returncode == 0, f"{label}: exit {r.returncode}: {r.stderr[-800:]} {r.stdout[-800:]}")
        check("dry run: no process launched, no file written" in r.stdout, f"{label}: no dry-run confirmation")
        check("semantic " in r.stdout and "compatibility-affecting fields" in r.stdout and "resolved configuration (JSON)" in r.stdout,
              f"{label}: dry-run output incomplete")
        check("torch" not in r.stderr.lower(), f"{label}: stderr {r.stderr[-300:]}")
        outputs[label] = [ln for ln in r.stdout.splitlines() if ln.startswith(("experiment", "reward", "fingerprints", "              semantic"))]
    check(not any(cwd.iterdir()), f"dry run wrote into the cwd: {list(cwd.iterdir())}")
    after_runs = {p.name: p.stat().st_mtime_ns for p in runs.iterdir()} if runs.exists() else {}
    check(before_runs == after_runs, "dry run changed runs/")
    check(_tree_snapshot(REPO_ROOT / "rl" / "configs") == before_cfg, "dry run changed rl/configs")
    check(not (REPO_ROOT / "runs" / "m7_mario_us_reward_v1").exists() and not (REPO_ROOT / "runs" / "dry").exists(),
          "dry run created a run directory")
    # Invalid configuration: exit 2 with the field path.
    bad = d / "bad.toml"
    bad.write_text(V1_TOML.read_text(encoding="utf-8").replace("batch_size = 512", "batch_size = 500"), encoding="utf-8")
    r = subprocess.run([sys.executable, str(REPO_ROOT / "rl" / "train_m7.py"), "--config", str(bad), "--dry-run"], cwd=str(cwd),
                       capture_output=True, text=True, timeout=300, check=False)
    check(r.returncode == 2 and "ppo.batch_size = 500" in r.stdout, f"invalid config: exit {r.returncode} {r.stdout[-400:]}")
    # Explicit --dry-run-output writes exactly that file and nothing else.
    out_file = d / "resolved.json"
    r = subprocess.run([sys.executable, str(REPO_ROOT / "rl" / "train_m7.py"), "--config", str(V2_TOML), "--dry-run",
                        "--dry-run-output", str(out_file)], cwd=str(cwd), capture_output=True, text=True, timeout=300, check=False)
    check(r.returncode == 0 and out_file.is_file(), "dry-run output file missing")
    written = json.loads(out_file.read_text(encoding="utf-8"))
    check(written["resolved"]["reward"]["contract"] == "btt_reward_v2" and written["fingerprints"]["semantic_fingerprint"]
          == ec.load_experiment(V2_TOML).semantic_fingerprint, "dry-run output content")
    check(sorted(p.name for p in d.iterdir()) == ["bad.toml", "cwd", "resolved.json"], f"unexpected files: {list(d.iterdir())}")
    return outputs


def legacy_parity(suite: Suite) -> Dict[str, Any]:
    v1 = ec.load_experiment(V1_TOML)
    legacy = ec.from_legacy_arguments("pilot", LEGACY_PILOT_ARGS, argv=["pilot", "--n-envs", "5", "--run-id", "m7a_pilot_n5"])
    check(legacy.semantic_fingerprint == v1.semantic_fingerprint, "legacy pilot arguments != checked-in v1 profile (semantic)")
    check(legacy.compatibility_fingerprint == v1.compatibility_fingerprint, "compat fingerprint differs")
    diff = {k: (v1.values[k], legacy.values[k]) for k in v1.values if v1.values[k] != legacy.values[k]}
    check(set(diff) <= {"run.name", "run.notes"}, f"legacy translation differs beyond name/notes: {diff}")
    check(legacy.source.kind == "legacy_cli" and legacy.source.argv == ["pilot", "--n-envs", "5", "--run-id", "m7a_pilot_n5"], "source")
    again = ec.parse_toml_text(legacy.toml_text)
    check(again.semantic_fingerprint == legacy.semantic_fingerprint and again.values == legacy.values,
          "generated legacy TOML does not reparse identically")
    check(ec.sha256_bytes(legacy.toml_text.encode("utf-8")) == legacy.source.sha256, "legacy source sha256 is of the generated text")
    # The pilot report on disk (if present) records exactly the values the legacy path resolves to.
    pilot_json = REPO_ROOT / "docs" / "rl_parallel_training_m7_pilot.json"
    on_disk = None
    if pilot_json.is_file():
        p = json.loads(pilot_json.read_text(encoding="utf-8"))
        cfg, ppo = p["config"], p["ppo"]
        v = legacy.values
        pairs = [(cfg["n_envs"], v["environment.process_count"]), (cfg["total_timesteps"], v["run.total_transitions"]),
                 (cfg["n_steps"], v["ppo.n_steps"]), (cfg["batch_size"], v["ppo.batch_size"]), (cfg["n_epochs"], v["ppo.n_epochs"]),
                 (cfg["gamma"], v["ppo.gamma"]), (cfg["gae_lambda"], v["ppo.gae_lambda"]), (cfg["learning_rate"], v["ppo.learning_rate"]),
                 (cfg["clip_range"], v["ppo.clip_range"]), (cfg["ent_coef"], v["ppo.ent_coef"]), (cfg["vf_coef"], v["ppo.vf_coef"]),
                 (cfg["max_grad_norm"], v["ppo.max_grad_norm"]), (cfg["base_seed"], v["run.base_seed"]),
                 (cfg["horizon"], v["environment.horizon"]), (cfg["checkpoint_interval"], v["checkpoint.interval"]),
                 (cfg["eval_interval"], v["evaluation.interval"]), (cfg["eval_initial"], v["evaluation.initial"]),
                 (cfg["eval_final"], v["evaluation.final"]), (cfg["eval_deterministic_episodes"], v["evaluation.deterministic_episodes"]),
                 (cfg["eval_stochastic_episodes"], v["evaluation.stochastic_episodes"]), (cfg["eval_seed"], v["evaluation.seed"]),
                 (cfg["periodic_episodes"], v["artifacts.periodic_episodes"]), (cfg["retain_failed_cap"], v["artifacts.retain_failed_cap"]),
                 (cfg["position_delta_threshold"], v["environment.position_delta_threshold"]),
                 (cfg["startup_attempts"], v["environment.startup_attempts"]), (cfg["startup_timeout"], v["environment.startup_timeout_s"]),
                 (cfg["ready_timeout"], v["environment.ready_timeout_s"]), (cfg["request_timeout"], v["environment.request_timeout_s"]),
                 (cfg["exit_timeout"], v["environment.exit_timeout_s"]), (cfg["step_timeout"], v["environment.step_timeout_s"]),
                 (cfg["torch_threads"], v["ppo.torch_threads"]), (cfg["device"], v["ppo.device"]), (cfg["clip_obs"], v["ppo.vecnormalize.clip_obs"]),
                 (cfg["extra_env"], dict(legacy.extra_env)), (ppo["net_arch"], "{'pi': [64, 64], 'vf': [64, 64]}"),
                 (ppo["activation_fn"], "Tanh"), (p["contracts"]["reward_contract"], legacy.reward.contract)]
        bad = [(a, b) for a, b in pairs if a != b]
        check(not bad, f"pilot report values differ from the legacy translation: {bad}")
        on_disk = {"pilot_report_values_checked": len(pairs), "all_equal": True}
    # A legacy train translation.
    train = ec.from_legacy_arguments("train", {**LEGACY_PILOT_ARGS, "n_envs": 4, "total_timesteps": 51200, "run_id": "t",
                                               "eval_interval": 0, "eval_initial": False, "eval_final": False})
    check(train.values["ppo.n_steps"] == 1280 and train.values["checkpoint.interval"] == 51200
          and train.values["evaluation.interval"] == 0 and train.mode == "train", "legacy train defaults")
    resume = ec.from_legacy_arguments("resume", {**LEGACY_PILOT_ARGS, "n_envs": 2, "total_timesteps": 5120, "run_id": "r",
                                                 "source": "runs/x/checkpoints/ckpt_000005120"})
    check(resume.mode == "resume" and resume.cli_overrides["legacy_resume_additional_transitions"] == 5120, "legacy resume translation")
    total, add = ec.resume_total_transitions(resume, 5120)
    check((total, add) == (10240, 5120), f"legacy resume total {total} additional {add}")
    return {"semantic": v1.semantic_fingerprint, "legacy_source": legacy.source.sha256, "pilot_report": on_disk}


def _m7a_shaped_meta(reward: RewardContract = REWARD_V1, *, legacy_record: bool = False, **changes: Any) -> Dict[str, Any]:
    """A checkpoint.json shaped like the M7a pilot's (no experiment block)."""
    rc = reward.to_json()
    if legacy_record:
        rc = {k: v for k, v in rc.items() if k != "failure_penalty"}
    meta = {
        "checkpoint_schema": 1, "num_timesteps": 51200, "n_updates": 100,
        "contracts": {"policy_observation_contract": "btt_policy_obs_v1", "track1_contract": "btt_s9_b8_v1",
                      "reward_contract": reward.contract, "reward_constants": rc, "horizon_native_ticks": 3600},
        "ppo": {"policy": "MlpPolicy", "learning_rate": 0.0003, "n_steps": 1024, "n_envs": 5, "rollout_size": 5120,
                "batch_size": 512, "n_epochs": 10, "gamma": 0.999, "gae_lambda": 0.995, "clip_range": 0.2, "ent_coef": 0.0,
                "vf_coef": 0.5, "max_grad_norm": 0.5, "net_arch": "{'pi': [64, 64], 'vf': [64, 64]}", "activation_fn": "Tanh",
                "device": "cpu"},
        "vecnormalize": {"norm_obs": True, "norm_reward": False, "clip_obs": 10.0},
        "m6_flags": {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1"},
        "executable": {"sha256": "abc"},
    }
    for path, value in changes.items():
        node = meta
        parts = path.split(".")
        for p in parts[:-1]:
            node = node[p]
        node[parts[-1]] = value
    return meta


def checkpoint_compatibility(suite: Suite) -> Dict[str, Any]:
    v1, v2 = ec.load_experiment(V1_TOML), ec.load_experiment(V2_TOML)
    view_v1 = ec.compatibility_view_from_values(v1.values, v1.reward, dict(v1.extra_env))
    view_v2 = ec.compatibility_view_from_values(v2.values, v2.reward, dict(v2.extra_env))
    m7a = _m7a_shaped_meta(legacy_record=True)
    cv = ec.checkpoint_compatibility_view(m7a)
    check(cv["contracts.reward_resolved"] == REWARD_V1.to_json() and cv["ppo.net_arch"] == [64, 64] and cv["ppo.activation"] == "tanh",
          f"M7a-shaped view: {cv}")
    check(ec.compare_compatibility(cv, view_v1) == {}, "an M7a v1 checkpoint must be compatible with the v1 profile")
    d = ec.compare_compatibility(cv, view_v2)
    check(list(d) == ["contracts.reward_resolved"], f"a v1 checkpoint vs the v2 profile must differ only in the reward: {d}")
    # The v1 checkpoint is never reinterpreted: the stored legacy record resolves to v1 (0.0), and a v2 profile
    # cannot claim it.
    out = {"m7a_view": cv, "v1_vs_v2_diffs": d}
    # Real pilot checkpoint, when present on this machine.
    if PILOT_CHECKPOINT.is_file():
        meta = json.loads(PILOT_CHECKPOINT.read_text(encoding="utf-8"))
        real = ec.checkpoint_compatibility_view(meta)
        check(ec.compare_compatibility(real, view_v1) == {}, "the real M7a pilot checkpoint is not compatible with the v1 profile")
        check(list(ec.compare_compatibility(real, view_v2)) == ["contracts.reward_resolved"], "real pilot vs v2")
        out["real_pilot_checkpoint"] = {"num_timesteps": meta["num_timesteps"], "compatible_with_v1": True,
                                        "rejected_by_v2": True}
    # M7b-shaped meta with an experiment block: its stored view wins.
    m7b = dict(_m7a_shaped_meta(REWARD_V2), experiment={"compatibility_view": view_v2})
    check(ec.checkpoint_compatibility_view(m7b) == view_v2, "M7b experiment block view not used")
    # Tampered / inconsistent reward records are refused (read path).
    out["inconsistent"] = expect_error(lambda: ec.checkpoint_compatibility_view(
        _m7a_shaped_meta(**{"contracts.reward_constants": dict(REWARD_V1.to_json(), clear_bonus=11.0)})), "btt_reward_v1", "frozen")
    out["v2_legacy_shape"] = expect_error(lambda: ec.checkpoint_compatibility_view(_m7a_shaped_meta(REWARD_V2, legacy_record=True)),
                                          "lacks failure_penalty")
    # Resume transition accounting.
    exp_resume = variant(v1.values, **{"run.mode": "resume", "resume.source_checkpoint": "runs/x/final",
                                       "run.total_transitions": 1_075_200})
    total, add = ec.resume_total_transitions(exp_resume, 1_024_000)
    check((total, add) == (1_075_200, 51_200), "resume accounting")
    out["resume_not_larger"] = expect_error(lambda: ec.resume_total_transitions(
        variant(v1.values, **{"run.mode": "resume", "resume.source_checkpoint": "runs/x/final"}), 1_024_000),
        "run.total_transitions = 1024000", "exceed")
    out["resume_not_multiple"] = expect_error(lambda: ec.resume_total_transitions(
        variant(v1.values, **{"run.mode": "resume", "resume.source_checkpoint": "runs/x/final",
                              "run.total_transitions": 1_024_000 + 10240}), 1_024_000 + 100), "multiple")
    return out


def resume_changes(suite: Suite) -> Dict[str, Any]:
    v1 = ec.load_experiment(V1_TOML)
    ckpt_view = ec.checkpoint_compatibility_view(_m7a_shaped_meta())
    allowed = {"run.name": "continued", "run.notes": "more", "run.output_root": "runs/other", "run.base_seed": 3,
               "run.total_transitions": 2_048_000, "checkpoint.interval": 102400, "evaluation.interval": 204800,
               "evaluation.stochastic_episodes": 40, "evaluation.seed": 99, "environment.request_timeout_s": 20.0,
               "environment.startup_attempts": 5, "ppo.torch_threads": 2, "artifacts.periodic_episodes": 20,
               "artifacts.retain_failed_cap": 0, "environment.position_delta_threshold": 250.0, "evaluation.workers": 2,
               "environment.port_block_base": 32000}
    e = variant(v1.values, **{"run.mode": "resume", "resume.source_checkpoint": "runs/x/final", **allowed})
    diffs = ec.compare_compatibility(ckpt_view, ec.compatibility_view_from_values(e.values, e.reward, dict(e.extra_env)))
    check(diffs == {}, f"permitted operational changes were rejected: {diffs}")
    for path in allowed:
        check(path in ec.RESUME_PERMITTED_PATHS, f"{path} not classified as permitted")
    rejected = {"task.id": None, "environment.horizon": 1800, "environment.process_count": None, "ppo.gamma": 0.99,
                "ppo.gae_lambda": 0.9, "ppo.learning_rate": 1e-4, "ppo.batch_size": 256, "ppo.n_epochs": 5, "ppo.clip_range": 0.1,
                "ppo.ent_coef": 0.01, "ppo.vf_coef": 1.0, "ppo.max_grad_norm": 1.0, "ppo.net_arch": [128, 128],
                "ppo.activation": "relu", "ppo.vecnormalize.clip_obs": 5.0, "ppo.vecnormalize.normalize_observations": False,
                "environment.no_render": False, "environment.raphnet_disable": False,
                "contracts.reward": ("btt_reward_v2", {"reward.failure_penalty": -5.0}),
                "custom_reward": ("custom", {"reward.per_step": -0.002})}
    results = {}
    for path, value in rejected.items():
        changes: Dict[str, Any] = {"run.mode": "resume", "resume.source_checkpoint": "runs/x/final"}
        key = path
        if path == "task.id":
            continue  # only one task id exists; a different id is rejected at validation (task_contract_rejection)
        if path == "environment.process_count":
            changes.update({"environment.process_count": 4, "ppo.n_steps": 1280})
            key = "environment.process_count"
        elif isinstance(value, tuple):
            changes["contracts.reward"] = value[0]
            changes.update(value[1])
            key = "contracts.reward_resolved"
        else:
            changes[path] = value
            if path in ("environment.no_render", "environment.raphnet_disable"):
                key = "environment.extra_env"   # the flags are compared as the resolved child environment
        e = variant(v1.values, **changes)
        diffs = ec.compare_compatibility(ckpt_view, ec.compatibility_view_from_values(e.values, e.reward, dict(e.extra_env)))
        check(key in diffs, f"{path}: change not rejected ({diffs})")
        results[path] = list(diffs)
    check(all(p in ec.IMMUTABLE_PATHS for p in ("environment.horizon", "ppo.gamma", "ppo.net_arch", "ppo.vecnormalize.clip_obs",
                                                 "contracts.reward", "reward.failure_penalty", "task.character",
                                                 "environment.process_count")), "immutable classification")
    return {"allowed": sorted(allowed), "rejected": results}


class _ScriptedM3:
    """Emits M3-shaped transitions: (targets_remaining, terminated, truncated, reason). No game."""

    def __init__(self, script):
        import gymnasium as gym
        from gymnasium import spaces

        self.script = script
        self.i = 0
        self.observation_space = spaces.Dict({})
        self.action_space = spaces.Discrete(1)
        self.unwrapped = self
        self.metadata = {}
        self.spec = None
        self.render_mode = None
        self._gym = gym

    def reset(self, *, seed=None, options=None):
        self.i = 0
        return {"btt_active": 1, "targets_remaining": np.array(10, np.uint32)}, {}

    def step(self, action):
        targets, term, trunc, reason = self.script[self.i]
        self.i += 1
        info = {}
        if reason:
            info["termination_reason" if term else "truncation_reason"] = reason
        return {"btt_active": 1, "targets_remaining": np.array(targets, np.uint32)}, 0.0, term, trunc, info

    def close(self):
        pass


def _run_script(script, contract: RewardContract):
    import gymnasium as gym

    from btt_parallel import M7RewardWrapper

    class Base(gym.Env):
        def __init__(self):
            self.inner = _ScriptedM3(script)
            self.observation_space = self.inner.observation_space
            self.action_space = self.inner.action_space

        def reset(self, *, seed=None, options=None):
            return self.inner.reset(seed=seed, options=options)

        def step(self, action):
            return self.inner.step(action)

    env = M7RewardWrapper(Base(), contract)
    _obs, info = env.reset()
    check(info["reward_contract"] == contract.contract, "reset info reward_contract")
    rewards, infos = [], []
    for _ in script:
        _o, r, term, trunc, info = env.step(0)
        rewards.append(r)
        infos.append(info)
        if term or trunc:
            break
    return rewards, infos, env


def _tas_script():
    """447 steps: the target breaks at the M5-verified consumed ticks, the clear on the last step."""
    script = []
    remaining = 10
    for tick in range(TAS_STEPS):
        if tick in TAS_TARGET_TICKS:
            remaining -= 1
        last = tick == TAS_STEPS - 1
        script.append((remaining, last, False, "native_clear" if last else None))
    check(remaining == 0, "script must end with 0 targets")
    return script


def reward_arithmetic(suite: Suite) -> Dict[str, Any]:
    out = {}
    tas = _tas_script()
    fall = [(10, False, False, None)] * (FALL_STEPS - 1) + [(10, True, False, "native_failure")]
    for contract in (REWARD_V1, REWARD_V2):
        r, infos, env = _run_script(tas, contract)
        total = math.fsum(r)
        check(len(r) == TAS_STEPS and abs(total - 19.553) < 1e-9, f"{contract.contract}: TAS return {total} != 19.553")
        check(infos[-1]["reward_terms"]["clear_term"] == 10.0 and infos[-1]["reward_terms"]["failure_term"] == 0.0
              and env.episode_failure_terms == 0, f"{contract.contract}: clear terms")
        check(abs(expected_return(10, TAS_STEPS, cleared=True, contract=contract) - 19.553) < 1e-9, "closed form clear")
        r2, infos2, env2 = _run_script(fall, contract)
        total2 = math.fsum(r2)
        want = -0.432 + contract.failure_penalty
        check(len(r2) == FALL_STEPS and abs(total2 - want) < 1e-9, f"{contract.contract}: fall return {total2} != {want}")
        check(infos2[-1]["reward_terms"]["failure_term"] == contract.failure_penalty
              and env2.episode_failure_terms == (1 if contract.failure_penalty else 0), f"{contract.contract}: failure term")
        check(abs(expected_return(0, FALL_STEPS, cleared=False, native_failure=True, contract=contract) - want) < 1e-9, "closed form fall")
        out[contract.contract] = {"tas_return": round(total, 9), "fall_return": round(total2, 9)}
    check(out["btt_reward_v1"]["fall_return"] == -0.432 and out["btt_reward_v2"]["fall_return"] == -5.432, str(out))
    # Horizon bound: the step cost at 3600 ticks (-3.6) is smaller in magnitude than the v2 penalty (-5.0).
    check(3600 * 0.001 < 5.0, "penalty must dominate the maximal step cost")
    # Same-tick target on the fall step, and a fall after targets.
    r3, _i, _e = _run_script([(9, False, False, None), (8, True, False, "native_failure")], REWARD_V2)
    check([round(x, 9) for x in r3] == [0.999, -4.001], f"v2 fall with a same-tick target: {r3}")
    # info keys: reward_v1 only under v1, reward_terms always.
    r4, i4, _ = _run_script([(10, False, False, None)], REWARD_V1)
    r5, i5, _ = _run_script([(10, False, False, None)], REWARD_V2)
    check("reward_v1" in i4[0] and "reward_v1" not in i5[0] and "reward_terms" in i5[0], "info keys")
    # Custom contract arithmetic.
    custom = make_reward_contract("custom", {"target_broken": 2.0, "per_step": -0.01, "clear_bonus": 5.0, "failure_penalty": -1.0})
    r6, _, _ = _run_script([(9, False, False, None), (9, True, False, "native_failure")], custom)
    check([round(x, 9) for x in r6] == [1.99, -1.01], f"custom arithmetic {r6}")
    return out


def penalty_once(suite: Suite) -> Dict[str, Any]:
    # A wrapper instance over two consecutive episodes: exactly one failure term per fall, reset clears the counter.
    import gymnasium as gym

    from btt_parallel import M7RewardWrapper

    script = [(10, False, False, None), (10, True, False, "native_failure")]

    class Base(gym.Env):
        def __init__(self):
            self.inner = _ScriptedM3(script)
            self.observation_space = self.inner.observation_space
            self.action_space = self.inner.action_space

        def reset(self, *, seed=None, options=None):
            return self.inner.reset()

        def step(self, action):
            return self.inner.step(action)

    env = M7RewardWrapper(Base(), REWARD_V2)
    totals = []
    for _episode in range(3):
        env.reset()
        check(env.episode_failure_terms == 0, "counter not reset")
        rs = []
        for _ in script:
            _o, r, term, trunc, info = env.step(0)
            rs.append(r)
            if term or trunc:
                break
        check(env.episode_failure_terms == 1 and sum(1 for x in rs if x <= -5.0) == 1, f"penalty count {rs}")
        check(abs(math.fsum(rs) - (-5.002)) < 1e-9, f"episode return {math.fsum(rs)}")
        totals.append(math.fsum(rs))
    # Direct arithmetic: the failure term appears only when native_failure is flagged; clear + failure is a violation.
    t = reward_step(10, 10, clear=False, native_failure=True, contract=REWARD_V2)
    check(t.failure_term == -5.0 and abs(t.total - (-5.001)) < 1e-12, "reward_step failure")
    check(reward_step(10, 10, clear=False, native_failure=False, contract=REWARD_V2).failure_term == 0.0, "no flag, no term")
    expect_error(lambda: reward_step(0, 0, clear=True, native_failure=True, contract=REWARD_V2), "both")
    return {"episode_returns": totals}


def no_penalty_elsewhere(suite: Suite) -> Dict[str, Any]:
    out = {}
    # Native clear: bonus, no penalty.
    r, infos, env = _run_script([(1, False, False, None), (0, True, False, "native_clear")], REWARD_V2)
    check([round(x, 9) for x in r] == [8.999, 10.999] and env.episode_failure_terms == 0, f"clear {r}")
    out["clear"] = r
    # Horizon truncation (max_episode_steps): no terminal term.
    r, infos, env = _run_script([(10, False, False, None), (10, False, True, "max_episode_steps")], REWARD_V2)
    check([round(x, 9) for x in r] == [-0.001, -0.001] and infos[-1]["reward_terms"]["failure_term"] == 0.0, f"truncation {r}")
    out["horizon_truncation"] = r
    # Any other truncation reason (lifecycle 'episode_failure' shape) carries no penalty either.
    r, infos, env = _run_script([(10, False, True, "episode_failure")], REWARD_V2)
    check(r == [-0.001] and infos[-1]["reward_terms"]["failure_term"] == 0.0, f"other truncation {r}")
    out["other_truncation"] = r
    # Infrastructure failure: an EpisodeFailure raised by the environment propagates through the reward wrapper
    # (no reward is produced), and Track1PolicyWrapper turns it into a truncated step with reward 0.0.
    import gymnasium as gym

    from battleship_process import EpisodeFailure, EpisodeOutcome
    from btt_learning import POLICY_FIELDS, Track1PolicyWrapper
    from btt_parallel import M7RewardWrapper

    class Failing(gym.Env):
        def __init__(self):
            self.observation_space = _ScriptedM3([]).observation_space
            self.action_space = _ScriptedM3([]).action_space
            self.calls = 0

        def reset(self, *, seed=None, options=None):
            obs = {name: 0 for name in POLICY_FIELDS}
            obs.update({"btt_active": 1, "targets_remaining": np.array(10, np.uint32)})
            return obs, {}

        def step(self, action):
            self.calls += 1
            raise EpisodeFailure(EpisodeOutcome.TRANSPORT_FAILURE, "simulated transport failure")

    rewarded = M7RewardWrapper(Failing(), REWARD_V2)
    rewarded.reset()
    try:
        rewarded.step(0)
        raise CaseFailure("EpisodeFailure did not propagate")
    except EpisodeFailure:
        pass
    check(rewarded.episode_return == 0.0 and rewarded.episode_failure_terms == 0, "reward produced on an infrastructure failure")
    stack = Track1PolicyWrapper(M7RewardWrapper(Failing(), REWARD_V2))
    stack.reset()
    obs, reward, terminated, truncated, info = stack.step(np.array([0, 0]))
    check(reward == 0.0 and truncated and not terminated and info["truncation_reason"] == "episode_failure"
          and info["failure_outcome"] == "transport_failure", f"lifecycle failure step {reward} {info}")
    out["infrastructure_failure"] = {"reward": reward, "truncated": truncated, "truncation_reason": info["truncation_reason"]}
    # The M7a fall rule itself is unchanged (unit_fall_rule in rl/m7_smoke.py); a clear observation is never a failure.
    return out


def policy_kwargs_parity(suite: Suite) -> Dict[str, Any]:
    """Explicit policy_kwargs from the v1 profile build the same network (same parameters) as M7a's implicit defaults."""
    import torch
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    from m7_smoke import FakeBTTEnv, FakeSpec
    from m7_trainer import M7PPO, M7Config, policy_kwargs, resolved_ppo_params

    v1 = ec.load_experiment(V1_TOML)
    cfg = M7Config(run_id="parity", n_envs=2, total_timesteps=5120, net_arch=tuple(v1.values["ppo.net_arch"]),
                   activation=v1.values["ppo.activation"])
    kwargs = policy_kwargs(cfg)
    check(kwargs == {"net_arch": {"pi": [64, 64], "vf": [64, 64]}, "activation_fn": torch.nn.Tanh}, str(kwargs))
    digests = []
    for kw in (None, kwargs):
        spec = FakeSpec(rank=0, marker_dir=str(suite.root), episode_length=16)
        venv = VecNormalize(DummyVecEnv([lambda: FakeBTTEnv(spec)] * 2), norm_obs=True, norm_reward=False, clip_obs=10.0)
        model = M7PPO("MlpPolicy", venv, n_steps=64, batch_size=64, n_epochs=1, gamma=0.999, gae_lambda=0.995, seed=0,
                      device="cpu", verbose=0, **({"policy_kwargs": kw} if kw else {}))
        params = resolved_ppo_params(model)
        check(params["net_arch"] == "{'pi': [64, 64], 'vf': [64, 64]}" and params["activation_fn"] == "Tanh"
              and params["ortho_init"] is True, f"resolved {params['net_arch']} {params['activation_fn']}")
        import hashlib

        h = hashlib.sha256()
        for name, t in sorted(model.policy.state_dict().items()):
            h.update(name.encode())
            h.update(t.detach().cpu().numpy().tobytes())
        digests.append(h.hexdigest())
        venv.close()
    check(digests[0] == digests[1], "explicit policy_kwargs changed the initial parameters vs SB3 defaults")
    # M7Config validation against its experiment; a disagreeing config is refused.
    from m7_trainer import config_from_experiment

    c = config_from_experiment(v1)
    c.validate()
    check(c.reward == REWARD_V1 and c.n_envs == 5 and c.n_steps == 1024 and c.experiment_summary()["semantic_fingerprint"]
          == v1.semantic_fingerprint, "config_from_experiment")
    check(ec.compare_compatibility(v1.compatibility_view(), c.compatibility_view()) == {}, "views agree")
    bad = config_from_experiment(v1)
    bad.gamma = 0.9
    expect_error(bad.validate, "disagrees")
    return {"parameter_digest": digests[0][:16], "policy_kwargs": {"net_arch": kwargs["net_arch"], "activation_fn": "Tanh"}}


def checkpoint_metadata(suite: Suite) -> Dict[str, Any]:
    """checkpoint.json + model.zip carry the reward contract and experiment block; v1/v2 sets are not interchangeable."""
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    from btt_parallel import RunCoordinator, initial_coordination_state, m7_contracts
    from m7_evaluation import CheckpointError, checkpoint_reward_contract, read_checkpoint_set
    from m7_smoke import FakeBTTEnv, FakeSpec
    from m7_trainer import M7PPO, resolved_ppo_params, save_checkpoint_set

    tmp = suite.dir("checkpoint_metadata")
    v2 = ec.load_experiment(V2_TOML)
    spec = FakeSpec(rank=0, marker_dir=str(tmp), episode_length=16)
    venv = VecNormalize(DummyVecEnv([lambda: FakeBTTEnv(spec)] * 2), norm_obs=True, norm_reward=False, clip_obs=10.0)
    model = M7PPO("MlpPolicy", venv, n_steps=64, batch_size=64, n_epochs=1, gamma=0.999, gae_lambda=0.995, seed=0,
                  device="cpu", verbose=0)
    model.learn(128)
    model.m7_reward_contract = REWARD_V2.to_json()
    model.m7_experiment = v2.summary()
    coord = RunCoordinator.create(tmp / "coord", initial_coordination_state("unit", "training", 10))
    run_meta = {"run_id": "unit", "purpose": "test", "lineage": [], "contracts": m7_contracts(3600, REWARD_V2), "horizon": 3600,
                "n_envs": 2, "ppo": resolved_ppo_params(model), "seeds": {"base_seed": 0}, "executable": {"path": "x", "sha256": "y"},
                "revisions": {"head": "h"}, "m6_flags": dict(v2.extra_env), "versions": {}, "torch_threads": {"requested": 1},
                "experiment": dict(v2.summary(), compatibility_view=v2.compatibility_view())}
    ck = tmp / "ckpt_v2"
    save_checkpoint_set(ck, model, venv, run_meta=run_meta, coordinator=coord, label="unit", rollouts=2)
    meta = json.loads((ck / "checkpoint.json").read_text(encoding="utf-8"))
    check(meta["reward_contract"] == REWARD_V2.to_json() and meta["experiment"]["reward_contract"] == "btt_reward_v2"
          and meta["experiment"]["semantic_fingerprint"] == v2.semantic_fingerprint
          and meta["contracts"]["reward_contract"] == "btt_reward_v2"
          and meta["contracts"]["reward_constants"]["failure_penalty"] == -5.0, "checkpoint.json lacks the v2 identity")
    check(checkpoint_reward_contract(meta) == REWARD_V2, "checkpoint_reward_contract")
    loaded = M7PPO.load(str(ck / "model.zip"), device="cpu")
    check(getattr(loaded, "m7_reward_contract", None) == REWARD_V2.to_json()
          and getattr(loaded, "m7_experiment", {}).get("semantic_fingerprint") == v2.semantic_fingerprint,
          "model.zip does not carry the reward contract / experiment block")
    # Verification with the matching contracts passes; with v1 contracts it is refused; with legacy-shaped v1 meta OK.
    read_checkpoint_set(ck, expected_contracts=m7_contracts(3600, REWARD_V2))
    try:
        read_checkpoint_set(ck, expected_contracts=m7_contracts(3600, REWARD_V1))
        raise CaseFailure("a v2 checkpoint was accepted under v1 contracts")
    except CheckpointError as exc:
        refused_v1 = str(exc)[:200]
    check("reward" in refused_v1, refused_v1)
    legacy_dir = tmp / "ckpt_legacy_v1"
    shutil.copytree(ck, legacy_dir)
    m = json.loads((legacy_dir / "checkpoint.json").read_text(encoding="utf-8"))
    m["contracts"]["reward_contract"] = "btt_reward_v1"
    m["contracts"]["reward_constants"] = {"contract": "btt_reward_v1", "target_broken": 1.0, "per_step": -0.001, "clear_bonus": 10.0}
    m.pop("reward_contract")
    m.pop("experiment")
    (legacy_dir / "checkpoint.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
    meta_legacy = read_checkpoint_set(legacy_dir, expected_contracts=m7_contracts(3600, REWARD_V1))
    check(meta_legacy["contracts"]["reward_constants"] == REWARD_V1.to_json(), "legacy record normalised to v1 with 0.0")
    derived_v2 = ec.checkpoint_compatibility_view({**meta, "experiment": None})   # derived from contracts/ppo, not the block
    check(ec.compare_compatibility(ec.checkpoint_compatibility_view(meta_legacy), derived_v2) == {"contracts.reward_resolved": {
              "checkpoint": REWARD_V1.to_json(), "requested": REWARD_V2.to_json()}}, "legacy vs v2 view diff")
    check(ec.checkpoint_compatibility_view(meta) == v2.compatibility_view(), "the stored M7b block is used when present")
    venv.close()
    return {"checkpoint_reward": meta["reward_contract"], "experiment_in_checkpoint": meta["experiment"]["name"],
            "model_reward": loaded.m7_reward_contract, "refused_under_v1": refused_v1}


# -- runner --------------------------------------------------------------------------------------------------------

CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "valid_profiles": valid_profiles,
    "validation_errors": validation_errors,
    "path_resolution": path_resolution,
    "fingerprints": fingerprints,
    "rollout_geometry": rollout_geometry,
    "canonical_reward_enforcement": canonical_reward_enforcement,
    "task_contract_rejection": task_contract_rejection,
    "dry_run_non_mutation": dry_run_non_mutation,
    "legacy_parity": legacy_parity,
    "checkpoint_compatibility": checkpoint_compatibility,
    "resume_changes": resume_changes,
    "reward_arithmetic": reward_arithmetic,
    "penalty_once": penalty_once,
    "no_penalty_elsewhere": no_penalty_elsewhere,
    "policy_kwargs_parity": policy_kwargs_parity,
    "checkpoint_metadata": checkpoint_metadata,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cases", nargs="*")
    parser.add_argument("--root", default=None)
    args = parser.parse_args(argv)
    names = list(args.cases or CASES)
    unknown = [n for n in names if n not in CASES]
    if unknown:
        parser.error(f"unknown case(s) {unknown}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = (Path(args.root) if args.root else REPO_ROOT / "runs" / f"_m7b_tests_{stamp}").resolve()
    root.mkdir(parents=True, exist_ok=False)
    suite = Suite(root)
    failures = 0
    for name in names:
        t0 = time.perf_counter()
        try:
            details = CASES[name](suite)
            ok, error = True, None
        except Exception as exc:  # noqa: BLE001
            ok, error, details = False, f"{type(exc).__name__}: {exc}", {"traceback": traceback.format_exc()[-4000:]}
        failures += 0 if ok else 1
        suite.results[name] = {"ok": ok, "error": error, "wall_s": round(time.perf_counter() - t0, 2), "details": details}
        print(f"{'PASS' if ok else 'FAIL'} {name} ({suite.results[name]['wall_s']} s)" + (f": {error}" if error else ""), flush=True)
        with open(root / "m7b_config_tests_results.json", "w", encoding="utf-8", newline="\n") as fp:
            json.dump({"cases": suite.results}, fp, indent=2, default=str)
    print(f"M7b config tests: {len(names) - failures}/{len(names)} PASS; results {root / 'm7b_config_tests_results.json'}", flush=True)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
