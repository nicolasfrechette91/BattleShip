#!/usr/bin/env python3
"""M7b: strict TOML experiment configuration for BattleShip Mario Break the Targets training.

    python rl/train_m7.py --config rl/configs/m7_mario_us_reward_v1.toml --dry-run

One TOML profile is the authoritative source of every behavioural setting
of a training run (task, contracts, reward values, environment behaviour,
PPO, VecNormalize, evaluation protocol). The command line only selects the
profile and operational things that cannot change what the experiment
means (dry run, run name, output root, resume checkpoint).

Schema (schema = "battleship_experiment_v1"); every key below is required
unless a default is listed in FIELDS:

    [run]          name, mode, base_seed, total_transitions, output_root, notes
    [task]         id, game_version, character, stage, player, costume
    [contracts]    protocol_version, observation, action, reward, artifact_schema
    [reward]       target_broken, per_step, clear_bonus, failure_penalty
    [environment]  executable, horizon, process_count, no_render, raphnet_disable, startup_attempts,
                   startup_timeout_s, ready_timeout_s, request_timeout_s, exit_timeout_s, step_timeout_s,
                   worker_runtime_root, port_block_base, port_block_size, position_delta_threshold,
                   standby_preboot, standby_count, standby_wait_timeout_s (M7c lifecycle; defaults = off)
    [ppo]          policy, net_arch, activation, learning_rate, rollout_size, n_steps, batch_size, n_epochs,
                   gamma, gae_lambda, clip_range, ent_coef, vf_coef, max_grad_norm, torch_threads, device
    [ppo.vecnormalize]  normalize_observations, normalize_rewards, clip_obs
    [checkpoint]   interval, initial
    [evaluation]   interval, initial, final, deterministic_episodes, stochastic_episodes,
                   random_baseline_episodes, seed, workers
    [artifacts]    periodic_episodes, retain_failed_cap
    [resume]       source_checkpoint, allow_executable_change, allow_lifecycle_change

Field classes (FIELDS[...].cls):

    immutable    behaviour-affecting AND compatibility-affecting: a resume must not change it
    semantic     behaviour-affecting, permitted to change on resume (seed, transition target,
                 evaluation protocol, artifact policy)
    lifecycle    M7c process-lifecycle mode (standby preboot): by contract it changes no
                 trajectory, reward, artifact or seed, but it is recorded in both fingerprints and
                 compared on resume like an immutable field; a resume across lifecycle modes is
                 refused unless resume.allow_lifecycle_change = true (then recorded in the lineage)
    operational  timeouts, cadence, retention, threads, ports, paths: never change what the
                 experiment means; recorded as run metadata only
    output       names, notes, output locations

Fingerprints:

    source_sha256             sha256 of the exact TOML bytes (comments and formatting included)
    semantic_fingerprint      sha256 of the canonical JSON of every immutable + semantic resolved value,
                              the resolved reward contract and the task table entry
    compatibility_fingerprint sha256 of the canonical JSON of the immutable values only (what a resume
                              compares, together with the executable sha256)

Changing a comment or the formatting changes source_sha256 and nothing
else. Unknown keys, missing keys, wrong types, invalid enum values,
non-finite numbers, out-of-range values, inconsistent rollout geometry,
unsupported tasks/contracts, canonical reward ids with altered values,
reward normalisation, invalid port blocks, invalid process counts,
inconsistent resume settings and unsafe paths are rejected with the full
field path and the offending value. Nothing is corrected silently.

Relative paths resolve against the repository root (the parent of rl/),
never against the current working directory, because game processes run
with a private working directory. Standard library + rl/btt_rewards.py
(which needs Gymnasium/NumPy through rl/btt_learning.py) + the M7g v2
observation identity (rl/m7g_obs.py, rl/m7g_policy.py; NumPy only at import)
only: no PyTorch or Stable-Baselines3 import here, so spawn workers and dry
runs stay light.

M7g Phase K: contracts.observation selects btt_policy_obs_v1 (default of every
existing profile) or btt_policy_obs_v2_spatial; ppo.policy must be the policy
class that observation requires (MlpPolicy / MultiInputPolicy), and v2 adds
SSB64_RL_SPATIAL=1 to the derived native flags. A v1 profile resolves to
exactly the values and fingerprints it had before.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m7g_obs  # noqa: E402  (M7g: v2 observation identity; NumPy/Gymnasium only, no PyTorch)
import m7g_policy  # noqa: E402
from btt_learning import POLICY_OBSERVATION_CONTRACT, TRACK1_CONTRACT  # noqa: E402
from btt_rewards import (  # noqa: E402
    REWARD_CUSTOM_PREFIX,
    REWARD_CUSTOM_REQUEST,
    REWARD_V1_ID,
    REWARD_V2_ID,
    REWARD_VALUE_FIELDS,
    RewardContract,
    RewardContractError,
    make_reward_contract,
    reward_contract_from_json,
)
from run_artifacts import ARTIFACT_SCHEMA  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_ID = "battleship_experiment_v1"
CONFIG_MODULE_VERSION = 2   # 2 (M7c): lifecycle fields (standby preboot) in the schema and both fingerprints
MAX_STANDBY_COUNT = 1       # M7c: exactly one standby per worker at most
LIFECYCLE_PATHS_DEFAULTS: Dict[str, Any] = {"environment.standby_preboot": False, "environment.standby_count": 0}
PROTOCOL_VERSION = 1            # M1d loopback NDJSON protocol
M7_POLICY = "MlpPolicy"
IANA_DYNAMIC_PORT_START = 49152  # static upper bound for port blocks; the live OS range is checked at run time
PORT_BLOCK_MAX_RANKS = 32
MAX_SEED = 2 ** 31 - 1
IS_WINDOWS = platform.system() == "Windows"

# -- task identity -----------------------------------------------------------------------------------------

KNOWN_GAME_VERSIONS = ("us", "jp")
KNOWN_CHARACTERS = ("mario", "fox", "donkey_kong", "samus", "luigi", "link", "yoshi", "captain_falcon", "kirby",
                    "pikachu", "jigglypuff", "ness")
KNOWN_STAGES = tuple(f"btt_{c}" for c in KNOWN_CHARACTERS) + tuple(f"btp_{c}" for c in KNOWN_CHARACTERS)
# The only implemented task. Values come from the native boot (port/rl/rl_boot.cpp rlBootApply: player port 0,
# Mario, costume 0, Bonus 1 Break the Targets) and the US build. Other combinations are rejected until implemented.
SUPPORTED_TASKS: Dict[str, Dict[str, Any]] = {
    "ssb64_us_mario_btt_v1": {
        "game_version": "us",
        "character": "mario",
        "stage": "btt_mario",
        "player": 0,
        "costume": 0,
        "executable_basename": "BattleShip.exe" if IS_WINDOWS else "BattleShip",
        "targets_total": 10,
        "native_boot": "SSB64_RL_BTT=1 -> rlBootApply (scene Bonus 1 Break the Targets, port 0, Mario, costume 0)",
    },
}

# M7g Phase K: btt_policy_obs_v2_spatial (rl/m7g_obs.py) is selectable explicitly; btt_policy_obs_v1 stays the default
# of every existing profile. The observation contract fixes the SB3 policy class (SB3 rejects a Dict space under
# MlpPolicy) and the native flags its observation needs (the read-only btt_spatial_v1 diagnostic); v1 adds nothing, so
# every v1 profile keeps its values, extra_env and fingerprints.
OBS_V2_SPATIAL = m7g_obs.OBS_CONTRACT
SUPPORTED_OBSERVATION_CONTRACTS = (POLICY_OBSERVATION_CONTRACT, OBS_V2_SPATIAL)
SUPPORTED_POLICIES = (M7_POLICY, m7g_policy.POLICY)
OBSERVATION_POLICY: Dict[str, str] = {POLICY_OBSERVATION_CONTRACT: M7_POLICY, OBS_V2_SPATIAL: m7g_policy.POLICY}
OBSERVATION_EXTRA_ENV: Dict[str, Tuple[Tuple[str, str], ...]] = {POLICY_OBSERVATION_CONTRACT: (),
                                                                   OBS_V2_SPATIAL: m7g_obs.SPATIAL_EXTRA_ENV}
SUPPORTED_ACTION_CONTRACTS = (TRACK1_CONTRACT,)
SUPPORTED_REWARD_REQUESTS = (REWARD_V1_ID, REWARD_V2_ID, REWARD_CUSTOM_REQUEST)
RUN_MODES = ("train", "pilot", "resume")
ACTIVATIONS = ("tanh", "relu")
DEVICES = ("cpu",)   # M7a trains on the CPU only; other devices are rejected as unsupported

RUN_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


class ConfigError(ValueError):
    """Invalid configuration. The message names every offending field path and value."""

    def __init__(self, problems: Sequence[str] | str):
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("invalid experiment configuration:\n  - " + "\n  - ".join(self.problems))


# -- field table -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Field:
    path: str
    kind: str                       # str | int | float | bool | int_list
    cls: str                        # immutable | semantic | operational | output
    required: bool = True
    default: Any = None
    choices: Optional[Tuple[Any, ...]] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    exclusive_minimum: bool = False
    doc: str = ""


_F = Field
FIELDS: Tuple[Field, ...] = (
    _F("run.name", "str", "output", doc="run identity; the run directory is <output_root>/<name>, never overwritten"),
    _F("run.mode", "str", "output", choices=RUN_MODES, doc="train | pilot (same behaviour, recorded purpose) | resume"),
    _F("run.base_seed", "int", "semantic", minimum=0, maximum=MAX_SEED,
       doc="Python / NumPy / PyTorch / SB3 seed; workers use base_seed + rank; never reaches the game"),
    _F("run.total_transitions", "int", "semantic", minimum=1,
       doc="cumulative transition target of the lineage (a resume trains the difference)"),
    _F("run.output_root", "str", "output", doc="parent of run directories; relative to the repository root"),
    _F("run.notes", "str", "output", required=False, default="", doc="free text"),
    _F("task.id", "str", "immutable", choices=tuple(SUPPORTED_TASKS)),
    _F("task.game_version", "str", "immutable", choices=KNOWN_GAME_VERSIONS),
    _F("task.character", "str", "immutable", choices=KNOWN_CHARACTERS),
    _F("task.stage", "str", "immutable", choices=KNOWN_STAGES),
    _F("task.player", "int", "immutable", minimum=0, maximum=3, doc="native controller port index"),
    _F("task.costume", "int", "immutable", minimum=0, maximum=7),
    _F("contracts.protocol_version", "int", "immutable", choices=(PROTOCOL_VERSION,)),
    _F("contracts.observation", "str", "immutable", choices=SUPPORTED_OBSERVATION_CONTRACTS,
       doc="policy observation: btt_policy_obs_v1 (15 float32) or btt_policy_obs_v2_spatial (Dict, 525 values)"),
    _F("contracts.action", "str", "immutable", choices=SUPPORTED_ACTION_CONTRACTS),
    _F("contracts.reward", "str", "immutable", choices=SUPPORTED_REWARD_REQUESTS,
       doc="canonical id (values frozen) or 'custom' (id derived from the values)"),
    _F("contracts.artifact_schema", "int", "immutable", choices=(ARTIFACT_SCHEMA,)),
    _F("reward.target_broken", "float", "immutable", minimum=0.0, maximum=100.0, exclusive_minimum=True),
    _F("reward.per_step", "float", "immutable", minimum=-1.0, maximum=0.0),
    _F("reward.clear_bonus", "float", "immutable", minimum=0.0, maximum=100.0),
    _F("reward.failure_penalty", "float", "immutable", minimum=-100.0, maximum=0.0),
    _F("environment.executable", "str", "operational", doc="BattleShip executable; its sha256 is compatibility-affecting"),
    _F("environment.horizon", "int", "immutable", minimum=1, maximum=1_000_000, doc="Python-owned bound in native ticks"),
    _F("environment.process_count", "int", "immutable", minimum=1, maximum=PORT_BLOCK_MAX_RANKS),
    _F("environment.no_render", "bool", "immutable", doc="SSB64_RL_NO_RENDER=1 for every game process"),
    _F("environment.raphnet_disable", "bool", "immutable", doc="SSB64_RAPHNET_DISABLE=1 for every game process"),
    _F("environment.startup_attempts", "int", "operational", minimum=1, maximum=10),
    _F("environment.startup_timeout_s", "float", "operational", minimum=0.0, maximum=3600.0, exclusive_minimum=True),
    _F("environment.ready_timeout_s", "float", "operational", minimum=0.0, maximum=3600.0, exclusive_minimum=True),
    _F("environment.request_timeout_s", "float", "operational", minimum=0.0, maximum=3600.0, exclusive_minimum=True),
    _F("environment.exit_timeout_s", "float", "operational", minimum=0.0, maximum=3600.0, exclusive_minimum=True),
    _F("environment.step_timeout_s", "float", "operational", minimum=0.0, maximum=86400.0, exclusive_minimum=True),
    _F("environment.worker_runtime_root", "str", "operational", required=False, default="",
       doc="'' = <run directory>/workers; otherwise worker directories go to <root>/<run.name>/wNN"),
    _F("environment.port_block_base", "int", "operational", minimum=1024, maximum=65535),
    _F("environment.port_block_size", "int", "operational", minimum=1, maximum=4096),
    _F("environment.position_delta_threshold", "float", "semantic", minimum=0.0, maximum=1_000_000.0,
       exclusive_minimum=True, doc="M4 anomaly detector threshold in units per native tick (Mario: 300)"),
    _F("environment.standby_preboot", "bool", "lifecycle", required=False, default=False,
       doc="M7c: boot the next BattleShip process in the background while the active episode runs and promote it at reset"),
    _F("environment.standby_count", "int", "lifecycle", required=False, default=0, choices=(0, MAX_STANDBY_COUNT),
       doc="standby processes per worker: 0 (off) or 1; must agree with standby_preboot"),
    _F("environment.standby_wait_timeout_s", "float", "operational", required=False, default=120.0, minimum=0.0,
       maximum=3600.0, exclusive_minimum=True,
       doc="M7c: bound on waiting at reset for a standby still booting; then it is cancelled and a cold fallback launch runs"),
    _F("ppo.policy", "str", "immutable", choices=SUPPORTED_POLICIES,
       doc="MlpPolicy for btt_policy_obs_v1, MultiInputPolicy for btt_policy_obs_v2_spatial (cross-field rule)"),
    _F("ppo.net_arch", "int_list", "immutable", doc="hidden layer widths shared by the pi and vf heads"),
    _F("ppo.activation", "str", "immutable", choices=ACTIVATIONS),
    _F("ppo.learning_rate", "float", "immutable", minimum=0.0, maximum=1.0, exclusive_minimum=True),
    _F("ppo.rollout_size", "int", "immutable", minimum=1, doc="transitions per rollout = n_steps * process_count"),
    _F("ppo.n_steps", "int", "immutable", minimum=1),
    _F("ppo.batch_size", "int", "immutable", minimum=1),
    _F("ppo.n_epochs", "int", "immutable", minimum=1, maximum=1000),
    _F("ppo.gamma", "float", "immutable", minimum=0.0, maximum=1.0, exclusive_minimum=True),
    _F("ppo.gae_lambda", "float", "immutable", minimum=0.0, maximum=1.0),
    _F("ppo.clip_range", "float", "immutable", minimum=0.0, maximum=1.0, exclusive_minimum=True),
    _F("ppo.ent_coef", "float", "immutable", minimum=0.0, maximum=10.0),
    _F("ppo.vf_coef", "float", "immutable", minimum=0.0, maximum=10.0),
    _F("ppo.max_grad_norm", "float", "immutable", minimum=0.0, maximum=1000.0, exclusive_minimum=True),
    _F("ppo.torch_threads", "int", "operational", minimum=1, maximum=64),
    _F("ppo.device", "str", "immutable", choices=DEVICES),
    _F("ppo.vecnormalize.normalize_observations", "bool", "immutable"),
    _F("ppo.vecnormalize.normalize_rewards", "bool", "immutable", choices=(False,),
       doc="reward normalisation is not allowed: returns must stay in contract units"),
    _F("ppo.vecnormalize.clip_obs", "float", "immutable", minimum=0.0, maximum=1e6, exclusive_minimum=True),
    _F("checkpoint.interval", "int", "operational", minimum=0, doc="0 = only initial/final sets; else a multiple of rollout_size"),
    _F("checkpoint.initial", "bool", "operational", doc="save the untrained policy as ckpt_000000000 (fresh runs)"),
    _F("evaluation.interval", "int", "operational", minimum=0, doc="0 = none; else a multiple of checkpoint.interval"),
    _F("evaluation.initial", "bool", "operational", doc="evaluate the untrained policy (fresh runs)"),
    _F("evaluation.final", "bool", "operational"),
    _F("evaluation.deterministic_episodes", "int", "semantic", minimum=0, maximum=10_000),
    _F("evaluation.stochastic_episodes", "int", "semantic", minimum=0, maximum=10_000),
    _F("evaluation.random_baseline_episodes", "int", "semantic", minimum=1, maximum=100_000),
    _F("evaluation.seed", "int", "semantic", minimum=0, maximum=MAX_SEED),
    _F("evaluation.workers", "int", "operational", required=False, default=0, minimum=0, maximum=PORT_BLOCK_MAX_RANKS,
       doc="0 = process_count"),
    _F("artifacts.periodic_episodes", "int", "semantic", minimum=0, maximum=1_000_000,
       doc="global periodic milestone artifact every N finished episodes (0 = none)"),
    _F("artifacts.retain_failed_cap", "int", "operational", minimum=0, maximum=100_000,
       doc="lifecycle-failure episode directories kept per worker"),
    _F("resume.source_checkpoint", "str", "operational", required=False, default="",
       doc="checkpoint-set directory; required when run.mode = 'resume', must be empty otherwise"),
    _F("resume.allow_executable_change", "bool", "operational", required=False, default=False,
       doc="accept a different executable sha256 on resume (recorded in the lineage)"),
    _F("resume.allow_lifecycle_change", "bool", "operational", required=False, default=False,
       doc="M7c: accept a different standby lifecycle mode on resume (recorded in the lineage)"),
)
FIELD_BY_PATH: Dict[str, Field] = {f.path: f for f in FIELDS}
TABLES: Tuple[str, ...] = tuple(dict.fromkeys(p.rsplit(".", 1)[0] for p in FIELD_BY_PATH))
LIFECYCLE_PATHS = tuple(f.path for f in FIELDS if f.cls == "lifecycle")
IMMUTABLE_PATHS = tuple(f.path for f in FIELDS if f.cls in ("immutable", "lifecycle"))
SEMANTIC_PATHS = tuple(f.path for f in FIELDS if f.cls in ("immutable", "lifecycle", "semantic"))
OPERATIONAL_PATHS = tuple(f.path for f in FIELDS if f.cls == "operational")
OUTPUT_PATHS = tuple(f.path for f in FIELDS if f.cls == "output")
# Operational fields a resume may change freely (documented in docs/rl_experiment_configuration_m7b.md).
RESUME_PERMITTED_PATHS = tuple(f.path for f in FIELDS if f.cls in ("semantic", "operational", "output"))

# M7h: the optional [curriculum] table (docs/rl_frontier_curriculum_m7h_proposal.md, revision 2). All or nothing: a
# profile without the table resolves exactly as before (no key in values, views, fingerprints or records); with the
# table every key is required and pinned to the registered M7h settings. Kept outside FIELDS on purpose.
CURRICULUM_CONTRACT = "btt_curriculum_frontier_v1"
CURRICULUM_FIELDS: Tuple[Field, ...] = (
    _F("curriculum.contract", "str", "immutable", choices=(CURRICULUM_CONTRACT,),
       doc="frontier-restart curriculum: training-only prefix phase after automatic resets"),
    _F("curriculum.tick0_probability", "float", "immutable", choices=(0.5,),
       doc="probability that an automatic reset keeps its tick-0 start (registered 50/50 selection)"),
    _F("curriculum.max_prefix_ticks", "int", "immutable", choices=(3000,), doc="longest selectable archived prefix"),
    _F("curriculum.pre_fall_exclusion_ticks", "int", "immutable", choices=(60,),
       doc="a cell reached this close before its source's native failure is never selected"),
    _F("curriculum.cell_size", "int", "immutable", choices=(300,),
       doc="M7f cell key (floor(x/300), floor(y/300), targets_remaining) on live steps"),
)
CURRICULUM_BY_PATH: Dict[str, Field] = {f.path: f for f in CURRICULUM_FIELDS}
CURRICULUM_PATHS: Tuple[str, ...] = tuple(CURRICULUM_BY_PATH)


# -- helpers ---------------------------------------------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(data: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, shortest round-trip floats, ASCII only."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def fingerprint(data: Any) -> str:
    return sha256_bytes(canonical_json(data).encode("ascii"))


def _flatten(table: Mapping[str, Any], prefix: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in table.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(_flatten(value, path))
        else:
            out[path] = value
    return out


def _nest(flat: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for path, value in flat.items():
        node = out
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return out


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v: Any) -> bool:
    return (isinstance(v, (int, float))) and not isinstance(v, bool)


def _repr_value(v: Any) -> str:
    return repr(v) if not isinstance(v, str) else json.dumps(v)


def repo_relative(path: Path) -> str:
    p = Path(path)
    try:
        return p.resolve().relative_to(REPO_ROOT).as_posix()
    except (ValueError, OSError):
        return str(p)


def resolve_repo_path(value: str) -> Path:
    """Absolute path; a relative value is taken from the repository root (never the cwd)."""
    p = Path(value)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return Path(os.path.normpath(str(p)))


def _path_problems(path: str, value: str, *, allow_empty: bool = False) -> List[str]:
    problems = []
    if not isinstance(value, str):
        return [f"{path} = {value!r}: expected a path string"]
    shown = _repr_value(value)
    if value == "":
        return [] if allow_empty else [f"{path} = {shown}: must not be empty"]
    if value != value.strip():
        problems.append(f"{path} = {shown}: leading or trailing whitespace is ambiguous")
    if "\x00" in value:
        problems.append(f"{path} = {shown}: contains NUL")
    if value.startswith("~"):
        problems.append(f"{path} = {shown}: '~' expansion is not supported (ambiguous per user)")
    if any(ch in value for ch in "*?\"<>|"):
        problems.append(f"{path} = {shown}: wildcard or reserved characters")
    return problems


def _within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def policy_observation_identity(observation: str) -> Optional[Dict[str, Any]]:
    """M7g Phase K: what a btt_policy_obs_v2_spatial run is bound to (contract digest, network, VecNormalize keys,
    native flag). None for btt_policy_obs_v1, so no v1 record gains a key."""
    if observation != OBS_V2_SPATIAL:
        return None
    return {"contract": m7g_obs.OBS_CONTRACT, "schema_version": m7g_obs.OBS_SCHEMA_VERSION,
            "contract_sha256": m7g_obs.contract_digest(), "flat_size": m7g_obs.FLAT_SIZE,
            "key_order": list(m7g_obs.KEY_ORDER), "policy": m7g_policy.POLICY, "network_id": m7g_policy.NETWORK_ID,
            "norm_obs_keys": list(m7g_obs.NORMALIZED_KEYS), "unnormalized_keys": list(m7g_obs.BINARY_KEYS),
            "native_flags": dict(m7g_obs.SPATIAL_EXTRA_ENV)}


# -- the resolved experiment -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceInfo:
    kind: str                    # toml | legacy_cli
    path: Optional[str]          # repo-relative or absolute path of the TOML (toml) / None
    sha256: str                  # of the exact TOML bytes (for legacy_cli: of the generated TOML text)
    size: int
    argv: Optional[List[str]] = None   # legacy_cli only


@dataclass(frozen=True)
class Experiment:
    """A validated, fully resolved configuration. Immutable; derive variants with with_overrides()."""

    source: SourceInfo
    toml_text: str                     # exact source text (toml) or the generated text (legacy_cli)
    values: Dict[str, Any]             # flat path -> resolved value for every schema field
    reward: RewardContract
    cli_overrides: Dict[str, Any] = field(default_factory=dict)

    # -- accessors --------------------------------------------------------------------------------------

    def __getitem__(self, path: str) -> Any:
        return self.values[path]

    @property
    def name(self) -> str:
        return self.values["run.name"]

    @property
    def mode(self) -> str:
        return self.values["run.mode"]

    @property
    def task(self) -> Dict[str, Any]:
        return dict(SUPPORTED_TASKS[self.values["task.id"]], id=self.values["task.id"])

    @property
    def process_count(self) -> int:
        return int(self.values["environment.process_count"])

    @property
    def rollout_size(self) -> int:
        return int(self.values["ppo.rollout_size"])

    @property
    def executable(self) -> Path:
        return resolve_repo_path(self.values["environment.executable"])

    @property
    def output_root(self) -> Path:
        return resolve_repo_path(self.values["run.output_root"])

    @property
    def run_dir(self) -> Path:
        return self.output_root / self.name

    @property
    def worker_runtime_root(self) -> Optional[Path]:
        v = self.values["environment.worker_runtime_root"]
        return resolve_repo_path(v) if v else None

    @property
    def resume_source(self) -> Optional[Path]:
        v = self.values["resume.source_checkpoint"]
        return resolve_repo_path(v) if v else None

    @property
    def extra_env(self) -> Tuple[Tuple[str, str], ...]:
        flags = []
        if self.values["environment.no_render"]:
            flags.append(("SSB64_RL_NO_RENDER", "1"))
        if self.values["environment.raphnet_disable"]:
            flags.append(("SSB64_RAPHNET_DISABLE", "1"))
        flags.extend(OBSERVATION_EXTRA_ENV[self.values["contracts.observation"]])   # M7g: v2 only (v1 adds none)
        return tuple(flags)

    def policy_observation(self) -> Optional[Dict[str, Any]]:
        """M7g: the v2 observation / network identity block (None for btt_policy_obs_v1, whose records stay as before)."""
        return policy_observation_identity(self.values["contracts.observation"])

    @property
    def eval_workers(self) -> int:
        return int(self.values["evaluation.workers"]) or self.process_count

    @property
    def standby_preboot(self) -> bool:
        return bool(self.values["environment.standby_preboot"])

    @property
    def standby_count(self) -> int:
        return int(self.values["environment.standby_count"])

    @property
    def max_game_processes(self) -> int:
        """Upper bound on simultaneous BattleShip processes of a training run (active + standby per worker)."""
        return self.process_count * (1 + self.standby_count)

    def lifecycle(self) -> Dict[str, Any]:
        return {"standby_preboot": self.standby_preboot, "standby_count": self.standby_count,
                "standby_wait_timeout_s": float(self.values["environment.standby_wait_timeout_s"]),
                "max_processes_per_worker": 1 + self.standby_count, "max_game_processes": self.max_game_processes,
                "eval_max_game_processes": self.eval_workers * (1 + self.standby_count)}

    def nested(self) -> Dict[str, Any]:
        return _nest(self.values)

    @property
    def curriculum(self) -> Optional[Dict[str, Any]]:
        """M7h: the [curriculum] table as {key: value} (short keys), or None when the profile has no curriculum."""
        if not any(p in self.values for p in CURRICULUM_PATHS):
            return None
        return {p.split(".", 1)[1]: self.values[p] for p in CURRICULUM_PATHS}

    # -- fingerprints -----------------------------------------------------------------------------------------

    def semantic_view(self) -> Dict[str, Any]:
        view = {p: self.values[p] for p in SEMANTIC_PATHS}
        view.update({p: self.values[p] for p in CURRICULUM_PATHS if p in self.values})   # M7h: only when present
        view["contracts.reward_resolved"] = self.reward.to_json()
        view["task.table"] = self.task
        view["schema"] = SCHEMA_ID
        return view

    def compatibility_view(self) -> Dict[str, Any]:
        view = {p: self.values[p] for p in IMMUTABLE_PATHS}
        view.update({p: self.values[p] for p in CURRICULUM_PATHS if p in self.values})   # M7h: only when present
        view["contracts.reward_resolved"] = self.reward.to_json()
        view["environment.extra_env"] = dict(self.extra_env)
        view["schema"] = SCHEMA_ID
        return view

    @property
    def semantic_fingerprint(self) -> str:
        return fingerprint(self.semantic_view())

    @property
    def compatibility_fingerprint(self) -> str:
        return fingerprint(self.compatibility_view())

    def executable_fingerprint(self) -> Dict[str, Any]:
        exe = self.executable
        if not exe.is_file():
            return {"path": repo_relative(exe), "exists": False, "sha256": None}
        return {"path": repo_relative(exe), "exists": True, "sha256": sha256_file(exe), "size": exe.stat().st_size}

    def summary(self) -> Dict[str, Any]:
        """The compact block recorded in run.json, checkpoint.json, model.zip, artifacts, evaluations, reports."""
        s = {
            "schema": SCHEMA_ID,
            "config_module_version": CONFIG_MODULE_VERSION,
            "name": self.name,
            "mode": self.mode,
            "task_id": self.values["task.id"],
            "reward_contract": self.reward.contract,
            "reward_values": self.reward.values(),
            "reward_canonical": self.reward.canonical,
            "source": {"kind": self.source.kind, "path": self.source.path, "sha256": self.source.sha256},
            "semantic_fingerprint": self.semantic_fingerprint,
            "compatibility_fingerprint": self.compatibility_fingerprint,
            "cli_overrides": dict(self.cli_overrides),
            "lifecycle": self.lifecycle(),
        }
        if self.policy_observation() is not None:
            s["policy_observation"] = self.policy_observation()
        if self.curriculum is not None:      # M7h: a profile without a curriculum records nothing new
            s["curriculum"] = self.curriculum
        return s

    def resolved_json(self) -> Dict[str, Any]:
        """The canonical resolved configuration written as experiment_resolved.json."""
        r = {
            "schema": SCHEMA_ID,
            "config_module_version": CONFIG_MODULE_VERSION,
            "source": {"kind": self.source.kind, "path": self.source.path, "sha256": self.source.sha256,
                       "size": self.source.size, "argv": self.source.argv},
            "cli_overrides": dict(self.cli_overrides),
            "config": self.nested(),
            "resolved": {
                "reward": self.reward.to_json(),
                "task": self.task,
                "executable": repo_relative(self.executable),
                "output_root": repo_relative(self.output_root),
                "run_dir": repo_relative(self.run_dir),
                "worker_runtime_root": repo_relative(self.worker_runtime_root) if self.worker_runtime_root else None,
                "resume_source": repo_relative(self.resume_source) if self.resume_source else None,
                "extra_env": dict(self.extra_env),
                "rollouts": self.values["run.total_transitions"] // self.rollout_size,
                "minibatches_per_epoch": self.rollout_size // self.values["ppo.batch_size"],
                "eval_workers": self.eval_workers,
                "lifecycle": self.lifecycle(),
                "port_blocks": {r: [self.values["environment.port_block_base"] + r * self.values["environment.port_block_size"],
                                    self.values["environment.port_block_base"] + (r + 1) * self.values["environment.port_block_size"] - 1]
                                for r in range(self.process_count)},
            },
            "fingerprints": {"source_sha256": self.source.sha256, "semantic_fingerprint": self.semantic_fingerprint,
                             "compatibility_fingerprint": self.compatibility_fingerprint},
            "field_classes": {p: (FIELD_BY_PATH.get(p) or CURRICULUM_BY_PATH[p]).cls for p in self.values},
        }
        if self.policy_observation() is not None:
            r["resolved"]["policy_observation"] = self.policy_observation()
        return r

    # -- variants ---------------------------------------------------------------------------------------------

    def with_overrides(self, overrides: Mapping[str, Any]) -> "Experiment":
        """Apply command-line overrides (run.name, run.output_root, resume.*); revalidated as a whole."""
        for path in overrides:
            if path not in ("run.name", "run.output_root", "run.mode", "resume.source_checkpoint", "run.notes"):
                raise ConfigError(f"{path}: not a permitted command-line override (behavioural settings live in the TOML only)")
        merged = dict(self.values)
        merged.update(overrides)
        raw = {"schema": SCHEMA_ID, **_nest(merged)}
        exp = build_experiment(raw, source=self.source, toml_text=self.toml_text,
                               cli_overrides={**self.cli_overrides, **overrides})
        return exp


# -- validation --------------------------------------------------------------------------------------------------


def _check_field(f: Field, value: Any, problems: List[str]) -> Any:
    """Type / enum / range check of one field. Returns the normalised value (ints stay int, floats become float)."""
    p = f.path
    if f.kind == "str":
        if not isinstance(value, str):
            problems.append(f"{p} = {_repr_value(value)}: expected a string")
            return value
    elif f.kind == "bool":
        if not isinstance(value, bool):
            problems.append(f"{p} = {_repr_value(value)}: expected a boolean")
            return value
    elif f.kind == "int":
        if not _is_int(value):
            problems.append(f"{p} = {_repr_value(value)}: expected an integer")
            return value
    elif f.kind == "float":
        if not _is_number(value):
            problems.append(f"{p} = {_repr_value(value)}: expected a number")
            return value
        value = float(value)
        if not math.isfinite(value):
            problems.append(f"{p} = {_repr_value(value)}: must be finite")
            return value
    elif f.kind == "int_list":
        if not isinstance(value, list) or not value or not all(_is_int(v) for v in value):
            problems.append(f"{p} = {_repr_value(value)}: expected a non-empty list of integers")
            return value
        if len(value) > 8 or any(not 1 <= v <= 4096 for v in value):
            problems.append(f"{p} = {_repr_value(value)}: at most 8 layers of 1..4096 units")
        return [int(v) for v in value]
    if f.choices is not None and value not in f.choices:
        problems.append(f"{p} = {_repr_value(value)}: must be one of {list(f.choices)}")
        return value
    if f.minimum is not None:
        if value < f.minimum or (f.exclusive_minimum and value == f.minimum):
            op = ">" if f.exclusive_minimum else ">="
            problems.append(f"{p} = {_repr_value(value)}: must be {op} {f.minimum}")
    if f.maximum is not None and value > f.maximum:
        problems.append(f"{p} = {_repr_value(value)}: must be <= {f.maximum}")
    return value


def _structural(raw: Mapping[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    problems: List[str] = []
    if not isinstance(raw, Mapping):
        return {}, ["the document must be a TOML table"]
    if raw.get("schema") != SCHEMA_ID:
        problems.append(f"schema = {_repr_value(raw.get('schema'))}: expected {SCHEMA_ID!r}")
    flat = _flatten({k: v for k, v in raw.items() if k != "schema"})
    for path, value in flat.items():
        if path not in FIELD_BY_PATH and path not in CURRICULUM_BY_PATH:
            if isinstance(value, dict) and not value:
                problems.append(f"{path}: unknown or empty table")
            else:
                problems.append(f"{path} = {_repr_value(value)}: unknown key")
    for key, value in raw.items():
        if key != "schema" and not isinstance(value, dict):
            problems.append(f"{key} = {_repr_value(value)}: top-level values other than 'schema' are not allowed")
    values: Dict[str, Any] = {}
    for f in FIELDS:
        if f.path in flat:
            values[f.path] = _check_field(f, flat[f.path], problems)
        elif f.required:
            problems.append(f"{f.path}: missing required key")
        else:
            values[f.path] = f.default
    if "curriculum" in raw and not raw["curriculum"]:
        problems.append("curriculum: empty table (the [curriculum] table is all-or-nothing; remove it for no curriculum)")
    if any(p in CURRICULUM_BY_PATH for p in flat):     # M7h: the optional table, all keys required once present
        for f in CURRICULUM_FIELDS:
            if f.path in flat:
                values[f.path] = _check_field(f, flat[f.path], problems)
            else:
                problems.append(f"{f.path}: missing required key (the [curriculum] table is all-or-nothing)")
    return values, problems


def _cross_field(v: Dict[str, Any], problems: List[str]) -> Optional[RewardContract]:
    def g(path: str) -> Any:
        return v.get(path)

    # Task identity: every field must match the single implemented task table entry.
    task = SUPPORTED_TASKS.get(g("task.id"))
    if task is not None:
        for key in ("game_version", "character", "stage", "player", "costume"):
            if g(f"task.{key}") != task[key]:
                problems.append(f"task.{key} = {_repr_value(g(f'task.{key}'))}: task {g('task.id')!r} requires "
                                f"{_repr_value(task[key])} (other combinations are not implemented)")
        exe = g("environment.executable")
        if isinstance(exe, str) and exe and Path(exe).name.lower() != task["executable_basename"].lower():
            problems.append(f"environment.executable = {_repr_value(exe)}: task {g('task.id')!r} ({task['game_version']}) "
                            f"needs the executable {task['executable_basename']!r}")
    # Reward: canonical ids enforce their values; custom ids derive their identity.
    reward: Optional[RewardContract] = None
    if all(isinstance(g(f"reward.{k}"), float) for k in REWARD_VALUE_FIELDS) and isinstance(g("contracts.reward"), str):
        try:
            reward = make_reward_contract(g("contracts.reward"), {k: g(f"reward.{k}") for k in REWARD_VALUE_FIELDS})
        except RewardContractError as exc:
            problems.append(f"contracts.reward = {_repr_value(g('contracts.reward'))}: {exc}")
    # M7g Phase K: the observation contract decides the policy class; v2's continuous keys have no fixed scaling and
    # rely on VecNormalize observation statistics (binary keys excluded by the contract's norm_obs_keys).
    obs, pol = g("contracts.observation"), g("ppo.policy")
    if obs in OBSERVATION_POLICY and pol in SUPPORTED_POLICIES and OBSERVATION_POLICY[obs] != pol:
        problems.append(f"ppo.policy = {_repr_value(pol)}: contracts.observation = {_repr_value(obs)} requires "
                        f"ppo.policy = {_repr_value(OBSERVATION_POLICY[obs])}")
    if obs == OBS_V2_SPATIAL and g("ppo.vecnormalize.normalize_observations") is False:
        problems.append(f"ppo.vecnormalize.normalize_observations = false: contracts.observation = {OBS_V2_SPATIAL!r} "
                        f"requires observation normalisation of {list(m7g_obs.NORMALIZED_KEYS)} (no fixed scaling)")
    if obs == OBS_V2_SPATIAL and (g("ppo.net_arch") != list(m7g_policy.NET_ARCH)
                                  or g("ppo.activation") != m7g_policy.ACTIVATION):
        problems.append(f"ppo.net_arch = {_repr_value(g('ppo.net_arch'))}, ppo.activation = {_repr_value(g('ppo.activation'))}: "
                        f"contracts.observation = {OBS_V2_SPATIAL!r} is validated only with network "
                        f"{m7g_policy.NETWORK_ID!r} (net_arch {list(m7g_policy.NET_ARCH)}, {m7g_policy.ACTIVATION}); "
                        "another network needs its own identity")
    # Rollout geometry.
    n, ns, rs, bs, tt =(g("environment.process_count"), g("ppo.n_steps"), g("ppo.rollout_size"), g("ppo.batch_size"),
                         g("run.total_transitions"))
    if all(_is_int(x) for x in (n, ns, rs, bs, tt)):
        if ns * n != rs:
            problems.append(f"ppo.rollout_size = {rs}: must equal ppo.n_steps * environment.process_count = {ns} * {n} = {ns * n}")
        if rs % bs != 0:
            problems.append(f"ppo.batch_size = {bs}: must divide ppo.rollout_size ({rs})")
        if bs > rs:
            problems.append(f"ppo.batch_size = {bs}: larger than ppo.rollout_size ({rs})")
        if tt % rs != 0:
            problems.append(f"run.total_transitions = {tt}: must be a positive multiple of ppo.rollout_size ({rs})")
        ci, ei = g("checkpoint.interval"), g("evaluation.interval")
        if _is_int(ci) and ci and ci % rs != 0:
            problems.append(f"checkpoint.interval = {ci}: must be 0 or a multiple of ppo.rollout_size ({rs})")
        if _is_int(ei) and ei:
            if not ci:
                problems.append(f"evaluation.interval = {ei}: needs checkpoint.interval > 0 (evaluations use saved sets)")
            elif _is_int(ci) and ei % ci != 0:
                problems.append(f"evaluation.interval = {ei}: must be 0 or a multiple of checkpoint.interval ({ci})")
    ev_any = bool(g("evaluation.interval")) or g("evaluation.initial") is True or g("evaluation.final") is True
    if ev_any and _is_int(g("evaluation.deterministic_episodes")) and _is_int(g("evaluation.stochastic_episodes")) \
            and g("evaluation.deterministic_episodes") + g("evaluation.stochastic_episodes") == 0:
        problems.append("evaluation.stochastic_episodes = 0: evaluations are scheduled but no episodes are configured")
    # Port blocks: disjoint by construction; must stay below the dynamic (ephemeral) range and inside 16 bits.
    base, size = g("environment.port_block_base"), g("environment.port_block_size")
    if _is_int(base) and _is_int(size) and _is_int(n):
        last = base + size * n - 1
        if last > 65535:
            problems.append(f"environment.port_block_size = {size}: {n} blocks from {base} end at {last} > 65535")
        elif last >= IANA_DYNAMIC_PORT_START:
            problems.append(f"environment.port_block_base = {base}: {n} blocks of {size} ports end at {last}, inside the "
                            f"OS dynamic port range (>= {IANA_DYNAMIC_PORT_START}); loopback ports would collide")
    # Resume consistency.
    src = g("resume.source_checkpoint")
    if g("run.mode") == "resume" and src == "":
        problems.append("resume.source_checkpoint = \"\": run.mode = \"resume\" requires a checkpoint-set directory")
    if g("run.mode") in ("train", "pilot") and src:
        problems.append(f"resume.source_checkpoint = {_repr_value(src)}: only allowed with run.mode = \"resume\"")
    if g("resume.allow_executable_change") is True and g("run.mode") != "resume":
        problems.append("resume.allow_executable_change = true: only meaningful with run.mode = \"resume\"")
    if g("resume.allow_lifecycle_change") is True and g("run.mode") != "resume":
        problems.append("resume.allow_lifecycle_change = true: only meaningful with run.mode = \"resume\"")
    # M7h: the frontier curriculum is registered for observation v1 only, and a curriculum run is never resumed.
    if g("curriculum.contract") is not None:
        if obs != POLICY_OBSERVATION_CONTRACT:
            problems.append(f"curriculum.contract = {_repr_value(g('curriculum.contract'))}: registered for "
                            f"contracts.observation = {POLICY_OBSERVATION_CONTRACT!r} only, not {_repr_value(obs)}")
        if g("run.mode") == "resume":
            problems.append("curriculum.contract: a curriculum run is never resumed (a partial run is restarted)")
    # M7c lifecycle: the two standby fields must agree (explicit, never inferred).
    sp, sc = g("environment.standby_preboot"), g("environment.standby_count")
    if isinstance(sp, bool) and _is_int(sc):
        if sp and sc != 1:
            problems.append(f"environment.standby_count = {sc}: standby_preboot = true requires standby_count = 1")
        if not sp and sc != 0:
            problems.append(f"environment.standby_count = {sc}: standby_preboot = false requires standby_count = 0")
    # Names and paths.
    name = g("run.name")
    if isinstance(name, str) and not RUN_NAME_RE.match(name):
        problems.append(f"run.name = {_repr_value(name)}: must match {RUN_NAME_RE.pattern} (no path separators)")
    notes = g("run.notes")
    if isinstance(notes, str) and len(notes) > 4000:
        problems.append(f"run.notes: {len(notes)} characters, at most 4000")
    for path, allow_empty in (("environment.executable", False), ("run.output_root", False),
                              ("environment.worker_runtime_root", True), ("resume.source_checkpoint", True)):
        if isinstance(g(path), str):
            problems.extend(_path_problems(path, g(path), allow_empty=allow_empty))
    if not problems:
        exe_dir = resolve_repo_path(v["environment.executable"]).parent
        out_root = resolve_repo_path(v["run.output_root"])
        for path, p in (("run.output_root", out_root),
                        ("environment.worker_runtime_root", resolve_repo_path(v["environment.worker_runtime_root"])
                         if v["environment.worker_runtime_root"] else None)):
            if p is None:
                continue
            if p == REPO_ROOT or _within(REPO_ROOT, p):
                problems.append(f"{path} = {_repr_value(v[path])}: resolves to the repository root or one of its parents")
            elif _within(p, exe_dir):
                problems.append(f"{path} = {_repr_value(v[path])}: resolves inside the executable directory "
                                f"({repo_relative(exe_dir)}); worker files would sit next to the user's configuration")
            elif _within(p, REPO_ROOT / "rl") or _within(p, REPO_ROOT / "docs") or _within(p, REPO_ROOT / "decomp") \
                    or _within(p, REPO_ROOT / "port"):
                problems.append(f"{path} = {_repr_value(v[path])}: resolves inside a source directory")
        if v["environment.worker_runtime_root"] and resolve_repo_path(v["environment.worker_runtime_root"]) == out_root:
            problems.append("environment.worker_runtime_root: equals run.output_root (ambiguous layout)")
    return reward


def build_experiment(raw: Mapping[str, Any], *, source: SourceInfo, toml_text: str,
                     cli_overrides: Optional[Mapping[str, Any]] = None) -> Experiment:
    values, problems = _structural(raw)
    if not problems:
        reward = _cross_field(values, problems)
    else:
        reward = None
    if problems:
        raise ConfigError(problems)
    assert reward is not None
    return Experiment(source=source, toml_text=toml_text, values=values, reward=reward,
                      cli_overrides=dict(cli_overrides or {}))


def parse_toml_text(text: str, *, source_path: Optional[str] = None, source_kind: str = "toml") -> Experiment:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{source_path or '<text>'}: TOML syntax error: {exc}") from exc
    data = text.encode("utf-8")
    return build_experiment(raw, source=SourceInfo(kind=source_kind, path=source_path, sha256=sha256_bytes(data),
                                                   size=len(data)), toml_text=text)


def load_experiment(path: os.PathLike | str) -> Experiment:
    """Parse and validate a TOML profile. The path itself may be relative to the cwd (it is a CLI argument)."""
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"--config {str(p)!r}: file not found")
    data = p.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"--config {str(p)!r}: not UTF-8: {exc}") from exc
    exp = parse_toml_text(text, source_path=repo_relative(p))
    if exp.source.sha256 != sha256_bytes(data):  # defensive: the text round trip must be byte-exact
        raise ConfigError(f"--config {str(p)!r}: source fingerprint mismatch after decoding")
    return exp


# -- TOML writer (for the legacy compatibility path and tests) --------------------------------------------------


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConfigError(f"cannot write non-finite float {value!r}")
        s = repr(value)
        return s if ("." in s or "e" in s or "E" in s) else s + ".0"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)  # JSON basic-string escapes are valid TOML basic strings
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise ConfigError(f"cannot write TOML value {value!r}")


def to_toml_text(values: Mapping[str, Any], *, header: Optional[str] = None) -> str:
    """Render flat schema values as a TOML document in schema order."""
    lines = []
    if header:
        lines += [f"# {line}" for line in header.splitlines()]
    lines.append(f"schema = {_toml_value(SCHEMA_ID)}")
    for table in TABLES:
        lines.append("")
        lines.append(f"[{table}]")
        for f in FIELDS:
            if f.path.rsplit(".", 1)[0] == table and f.path in values:
                lines.append(f"{f.path.rsplit('.', 1)[1]} = {_toml_value(values[f.path])}")
    return "\n".join(lines) + "\n"


# -- legacy M7a command line -> schema (compatibility path) ---------------------------------------------------

M7A_ROLLOUT_SIZE = 5120
M7A_PILOT_TOTAL = 1_024_000
M7A_PILOT_CHECKPOINT = 51_200
M7A_PILOT_EVAL = 102_400
M7A_DEFAULTS: Dict[str, Any] = {
    "task.id": "ssb64_us_mario_btt_v1", "task.game_version": "us", "task.character": "mario", "task.stage": "btt_mario",
    "task.player": 0, "task.costume": 0,
    "contracts.protocol_version": PROTOCOL_VERSION, "contracts.observation": POLICY_OBSERVATION_CONTRACT,
    "contracts.action": TRACK1_CONTRACT, "contracts.reward": REWARD_V1_ID, "contracts.artifact_schema": ARTIFACT_SCHEMA,
    "reward.target_broken": 1.0, "reward.per_step": -0.001, "reward.clear_bonus": 10.0, "reward.failure_penalty": 0.0,
    "environment.no_render": True, "environment.raphnet_disable": True, "environment.startup_attempts": 3,
    "environment.startup_timeout_s": 20.0, "environment.ready_timeout_s": 60.0, "environment.request_timeout_s": 10.0,
    "environment.exit_timeout_s": 30.0, "environment.step_timeout_s": 900.0, "environment.worker_runtime_root": "",
    "environment.port_block_base": 30000, "environment.port_block_size": 250, "environment.position_delta_threshold": 300.0,
    "ppo.policy": M7_POLICY, "ppo.net_arch": [64, 64], "ppo.activation": "tanh", "ppo.learning_rate": 3e-4,
    "ppo.rollout_size": M7A_ROLLOUT_SIZE, "ppo.batch_size": 512, "ppo.n_epochs": 10, "ppo.gamma": 0.999,
    "ppo.gae_lambda": 0.995, "ppo.clip_range": 0.2, "ppo.ent_coef": 0.0, "ppo.vf_coef": 0.5, "ppo.max_grad_norm": 0.5,
    "ppo.torch_threads": 1, "ppo.device": "cpu",
    "ppo.vecnormalize.normalize_observations": True, "ppo.vecnormalize.normalize_rewards": False,
    "ppo.vecnormalize.clip_obs": 10.0,
    "checkpoint.initial": True, "evaluation.workers": 0, "artifacts.retain_failed_cap": 20,
    "resume.source_checkpoint": "", "resume.allow_executable_change": False,
    # M7c: the legacy M7a path never had a standby process
    "environment.standby_preboot": False, "environment.standby_count": 0, "environment.standby_wait_timeout_s": 120.0,
    "resume.allow_lifecycle_change": False,
}


def from_legacy_arguments(command: str, args: Mapping[str, Any], *, argv: Optional[Sequence[str]] = None,
                          n_envs: Optional[int] = None, run_name: Optional[str] = None) -> Experiment:
    """Translate the M7a `train_m7.py train|pilot|resume|compare` arguments into the schema.

    The mapping reproduces rl/train_m7.py's M7a defaults exactly (rollout
    5120, n_steps = 5120 // n_envs, pilot cadence, SB3 defaults recorded by
    M7a, both M6 flags). `args` is the argparse namespace as a mapping."""
    if command not in ("train", "pilot", "resume", "compare"):
        raise ConfigError(f"legacy command {command!r}: unknown")
    n = int(n_envs if n_envs is not None else args["n_envs"])
    if n < 1:
        raise ConfigError(f"--n-envs = {n}: must be >= 1")
    v = dict(M7A_DEFAULTS)
    v["run.name"] = run_name or args.get("run_id") or args.get("compare_id") or f"m7_{command}"
    v["run.mode"] = {"train": "train", "pilot": "pilot", "resume": "resume", "compare": "train"}[command]
    v["run.base_seed"] = int(args.get("seed", 0))
    v["run.output_root"] = args.get("runs_dir") or "runs"
    v["run.notes"] = f"translated from legacy M7a arguments: train_m7.py {command}"
    v["environment.executable"] = args.get("exe") or "build-us/Release/BattleShip.exe"
    v["environment.horizon"] = int(args.get("horizon", 3600))
    v["environment.process_count"] = n
    v["ppo.n_steps"] = M7A_ROLLOUT_SIZE // n
    v["ppo.rollout_size"] = v["ppo.n_steps"] * n
    if command == "pilot":
        v["run.total_transitions"] = M7A_PILOT_TOTAL
        ckpt_default, ev_int, ev_init, ev_final = M7A_PILOT_CHECKPOINT, M7A_PILOT_EVAL, True, True
    elif command == "compare":
        v["run.total_transitions"] = int(args.get("total_timesteps", 51200))
        ckpt_default, ev_int, ev_init, ev_final = 25600, 0, False, False
    else:
        v["run.total_transitions"] = int(args["total_timesteps"])
        ckpt_default = 51200
        ev_int = int(args.get("eval_interval") or 0) if command == "train" else 0
        ev_init = bool(args.get("eval_initial")) if command == "train" else False
        ev_final = bool(args.get("eval_final")) if command == "train" else False
    ci = args.get("checkpoint_interval")
    v["checkpoint.interval"] = int(ci) if ci is not None else ckpt_default
    v["evaluation.interval"] = ev_int
    v["evaluation.initial"] = ev_init
    v["evaluation.final"] = ev_final
    v["evaluation.deterministic_episodes"] = int(args.get("eval_deterministic_episodes", 2))
    v["evaluation.stochastic_episodes"] = int(args.get("eval_stochastic_episodes", 20))
    v["evaluation.random_baseline_episodes"] = 100
    v["evaluation.seed"] = int(args.get("eval_seed", 12345))
    v["evaluation.workers"] = int(args.get("eval_workers") or 0)
    v["artifacts.periodic_episodes"] = int(args.get("periodic_episodes", 10))
    if command == "resume":
        v["resume.source_checkpoint"] = str(args["source"])
    text = to_toml_text(v, header=f"generated by rl/experiment_config.py from legacy M7a arguments: "
                                  f"train_m7.py {' '.join(argv or [])}".rstrip())
    data = text.encode("utf-8")
    raw = tomllib.loads(text)
    exp = build_experiment(raw, source=SourceInfo(kind="legacy_cli", path=None, sha256=sha256_bytes(data), size=len(data),
                                                  argv=list(argv) if argv is not None else None), toml_text=text)
    if command == "resume":
        # The legacy argument means ADDITIONAL transitions; the schema stores the cumulative lineage target.
        # Callers resolve it once the checkpoint's num_timesteps is known (see resume_total_transitions()).
        exp = Experiment(source=exp.source, toml_text=exp.toml_text,
                         values=dict(exp.values, **{"run.total_transitions": int(args["total_timesteps"])}),
                         reward=exp.reward, cli_overrides={"legacy_resume_additional_transitions": int(args["total_timesteps"])})
    return exp


# -- resume compatibility ----------------------------------------------------------------------------------------

# checkpoint.json (M7a or M7b) -> compatibility view keys. M7a checkpoints have no `experiment` block; their view is
# derived from `contracts`, `ppo`, `vecnormalize`, `m6_flags` and the task M7a exclusively ran.
COMPAT_KEYS: Tuple[str, ...] = (
    "task.id", "contracts.observation", "contracts.action", "contracts.reward_resolved", "contracts.artifact_schema",
    "contracts.protocol_version", "environment.horizon", "environment.process_count", "environment.extra_env",
    "ppo.policy", "ppo.net_arch", "ppo.activation", "ppo.learning_rate", "ppo.rollout_size", "ppo.n_steps",
    "ppo.batch_size", "ppo.n_epochs", "ppo.gamma", "ppo.gae_lambda", "ppo.clip_range", "ppo.ent_coef", "ppo.vf_coef",
    "ppo.max_grad_norm", "ppo.device", "ppo.vecnormalize.normalize_observations", "ppo.vecnormalize.normalize_rewards",
    "ppo.vecnormalize.clip_obs",
    # M7c lifecycle keys: compared on resume; a checkpoint written before M7c had no standby (defaults below)
    "environment.standby_preboot", "environment.standby_count",
)
LIFECYCLE_COMPAT_KEYS: Tuple[str, ...] = ("environment.standby_preboot", "environment.standby_count")
_ACTIVATION_NAMES = {"Tanh": "tanh", "ReLU": "relu"}


def lifecycle_only_diffs(diffs: Mapping[str, Any]) -> bool:
    """True when every compatibility difference is a lifecycle key (resumable with resume.allow_lifecycle_change)."""
    return bool(diffs) and all(k in LIFECYCLE_COMPAT_KEYS for k in diffs)


def _parse_m7a_net_arch(text: Any) -> Any:
    """resolved_ppo_params records str(policy.net_arch), e.g. "{'pi': [64, 64], 'vf': [64, 64]}"."""
    if isinstance(text, dict):
        pi, vf = text.get("pi"), text.get("vf")
    else:
        m = re.fullmatch(r"\{'pi': \[([0-9, ]*)\], 'vf': \[([0-9, ]*)\]\}", str(text).strip())
        if not m:
            return text
        pi = [int(x) for x in m.group(1).split(",") if x.strip()]
        vf = [int(x) for x in m.group(2).split(",") if x.strip()]
    return pi if pi == vf else {"pi": pi, "vf": vf}


def checkpoint_compatibility_view(meta: Mapping[str, Any]) -> Dict[str, Any]:
    """The compatibility view of a checkpoint set's checkpoint.json (M7b block if present, else derived from M7a)."""
    exp_block = meta.get("experiment") or {}
    if isinstance(exp_block, Mapping) and isinstance(exp_block.get("compatibility_view"), Mapping):
        view = dict(exp_block["compatibility_view"])
        for key, default in LIFECYCLE_PATHS_DEFAULTS.items():   # M7b checkpoints: no standby existed
            view.setdefault(key, default)
        return view
    contracts = meta.get("contracts") or {}
    ppo = meta.get("ppo") or {}
    vn = meta.get("vecnormalize") or {}
    reward = reward_contract_from_json(contracts.get("reward_constants"), contract_id=contracts.get("reward_contract"))
    view: Dict[str, Any] = {
        "task.id": "ssb64_us_mario_btt_v1",
        "contracts.observation": contracts.get("policy_observation_contract"),
        "contracts.action": contracts.get("track1_contract"),
        "contracts.reward_resolved": reward.to_json(),
        "contracts.artifact_schema": ARTIFACT_SCHEMA,
        "contracts.protocol_version": PROTOCOL_VERSION,
        "environment.horizon": contracts.get("horizon_native_ticks"),
        "environment.process_count": ppo.get("n_envs", meta.get("n_envs")),
        "environment.extra_env": dict(meta.get("m6_flags") or {}),
        "ppo.policy": ppo.get("policy"),
        "ppo.net_arch": _parse_m7a_net_arch(ppo.get("net_arch")),
        "ppo.activation": _ACTIVATION_NAMES.get(ppo.get("activation_fn"), ppo.get("activation_fn")),
        "ppo.learning_rate": ppo.get("learning_rate"),
        "ppo.rollout_size": ppo.get("rollout_size"),
        "ppo.n_steps": ppo.get("n_steps"),
        "ppo.batch_size": ppo.get("batch_size"),
        "ppo.n_epochs": ppo.get("n_epochs"),
        "ppo.gamma": ppo.get("gamma"),
        "ppo.gae_lambda": ppo.get("gae_lambda"),
        "ppo.clip_range": ppo.get("clip_range"),
        "ppo.ent_coef": ppo.get("ent_coef"),
        "ppo.vf_coef": ppo.get("vf_coef"),
        "ppo.max_grad_norm": ppo.get("max_grad_norm"),
        "ppo.device": ppo.get("device"),
        "ppo.vecnormalize.normalize_observations": vn.get("norm_obs"),
        "ppo.vecnormalize.normalize_rewards": vn.get("norm_reward"),
        "ppo.vecnormalize.clip_obs": vn.get("clip_obs"),
    }
    lifecycle = meta.get("lifecycle") or {}
    for key, default in LIFECYCLE_PATHS_DEFAULTS.items():   # M7a checkpoints: no standby existed
        view[key] = lifecycle.get(key.rsplit(".", 1)[1], default)
    return view


def compatibility_view_from_values(values: Mapping[str, Any], reward: RewardContract,
                                   extra_env: Mapping[str, str]) -> Dict[str, Any]:
    """The same view built from resolved schema values (used by the trainer for TOML and legacy runs alike)."""
    view = {k: values[k] for k in COMPAT_KEYS if k in values}
    view["contracts.reward_resolved"] = reward.to_json()
    view["environment.extra_env"] = dict(extra_env)
    return view


def compare_compatibility(checkpoint_view: Mapping[str, Any], requested_view: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Field-by-field differences (empty when a resume is allowed on these grounds)."""
    diffs: Dict[str, Dict[str, Any]] = {}
    for key in COMPAT_KEYS:
        a, b = checkpoint_view.get(key), requested_view.get(key)
        if isinstance(a, float) or isinstance(b, float):
            same = _is_number(a) and _is_number(b) and float(a) == float(b)
        else:
            same = a == b
        if not same:
            diffs[key] = {"checkpoint": a, "requested": b}
    return diffs


def resume_total_transitions(exp: Experiment, checkpoint_num_timesteps: int) -> Tuple[int, int]:
    """(cumulative target, additional transitions) of a resumed run; validates the geometry."""
    legacy_add = exp.cli_overrides.get("legacy_resume_additional_transitions")
    if legacy_add is not None:
        total = int(checkpoint_num_timesteps) + int(legacy_add)
    else:
        total = int(exp.values["run.total_transitions"])
    additional = total - int(checkpoint_num_timesteps)
    rs = exp.rollout_size
    if additional < rs:
        raise ConfigError(f"run.total_transitions = {total}: must exceed the checkpoint's num_timesteps "
                          f"({checkpoint_num_timesteps}) by at least one rollout ({rs})")
    if additional % rs != 0:
        raise ConfigError(f"run.total_transitions = {total}: the additional {additional} transitions must be a multiple "
                          f"of ppo.rollout_size ({rs})")
    return total, additional


# -- dry run ---------------------------------------------------------------------------------------------------------


def describe(exp: Experiment, *, checkpoint_meta: Optional[Mapping[str, Any]] = None) -> str:
    """Human-readable dry-run report: resolved values, contract identities, fingerprints, compatibility fields."""
    v = exp.values
    lines = [
        f"experiment  : {exp.name}  (mode {exp.mode})",
        f"source      : {exp.source.kind} {exp.source.path or ''}  sha256 {exp.source.sha256}",
        f"task        : {v['task.id']}  ({v['task.game_version']}, {v['task.character']}, {v['task.stage']}, "
        f"port {v['task.player']}, costume {v['task.costume']})",
        f"contracts   : protocol {v['contracts.protocol_version']}  observation {v['contracts.observation']}  "
        f"action {v['contracts.action']}  artifact_schema {v['contracts.artifact_schema']}",
        f"reward      : {exp.reward.contract}  {exp.reward.values()}  canonical={exp.reward.canonical}",
        f"executable  : {exp.executable_fingerprint()}",
        f"environment : horizon {v['environment.horizon']}  N={exp.process_count}  flags {dict(exp.extra_env)}  "
        f"anomaly threshold {v['environment.position_delta_threshold']}",
        f"ppo         : {v['ppo.policy']} net_arch {v['ppo.net_arch']} {v['ppo.activation']}  lr {v['ppo.learning_rate']}  "
        f"rollout {v['ppo.rollout_size']} = n_steps {v['ppo.n_steps']} x N  batch {v['ppo.batch_size']}  "
        f"epochs {v['ppo.n_epochs']}  gamma {v['ppo.gamma']}  lambda {v['ppo.gae_lambda']}  clip {v['ppo.clip_range']}  "
        f"ent {v['ppo.ent_coef']}  vf {v['ppo.vf_coef']}  grad_norm {v['ppo.max_grad_norm']}  device {v['ppo.device']}  "
        f"threads {v['ppo.torch_threads']}",
        f"vecnormalize: obs {v['ppo.vecnormalize.normalize_observations']}  reward {v['ppo.vecnormalize.normalize_rewards']}  "
        f"clip_obs {v['ppo.vecnormalize.clip_obs']}",
        f"run         : seed {v['run.base_seed']}  total {v['run.total_transitions']} "
        f"({v['run.total_transitions'] // exp.rollout_size} rollouts)  output {repo_relative(exp.run_dir)}",
        f"checkpoint  : every {v['checkpoint.interval']}  initial {v['checkpoint.initial']}",
        f"evaluation  : every {v['evaluation.interval']}  initial {v['evaluation.initial']}  final {v['evaluation.final']}  "
        f"det {v['evaluation.deterministic_episodes']}  stoch {v['evaluation.stochastic_episodes']}  "
        f"random {v['evaluation.random_baseline_episodes']}  seed {v['evaluation.seed']}  workers {exp.eval_workers}",
        f"artifacts   : periodic {v['artifacts.periodic_episodes']}  retain_failed_cap {v['artifacts.retain_failed_cap']}",
        f"lifecycle   : standby_preboot {v['environment.standby_preboot']}  standby_count {v['environment.standby_count']}  "
        f"standby_wait_timeout_s {v['environment.standby_wait_timeout_s']}  max processes per worker "
        f"{1 + exp.standby_count}  expected maximum game processes {exp.max_game_processes} (training, N={exp.process_count}) / "
        f"{exp.eval_workers * (1 + exp.standby_count)} (evaluation, {exp.eval_workers} workers)",
        f"fingerprints: source {exp.source.sha256}",
        f"              semantic {exp.semantic_fingerprint}",
        f"              compatibility {exp.compatibility_fingerprint}",
        "compatibility-affecting fields (immutable on resume):",
    ]
    po = exp.policy_observation()
    if po is not None:   # M7g: v2 only; a v1 dry run prints exactly what it printed before
        lines.insert(4, f"observation : {po['contract']} schema {po['schema_version']} sha256 {po['contract_sha256']}  "
                        f"{po['policy']} ({po['network_id']}, {po['flat_size']} inputs)  norm_obs_keys "
                        f"{po['norm_obs_keys']}  unnormalised {po['unnormalized_keys']}  native flags {po['native_flags']}")
    for p in IMMUTABLE_PATHS:
        lines.append(f"    {p} = {_repr_value(v[p])}")
    lines.append("    executable sha256 (unless resume.allow_executable_change)")
    lines.append("    lifecycle fields (" + ", ".join(LIFECYCLE_PATHS) + ") unless resume.allow_lifecycle_change")
    lines.append("behaviour-affecting, permitted on resume: " + ", ".join(p for p in SEMANTIC_PATHS if p not in IMMUTABLE_PATHS))
    lines.append("operational: " + ", ".join(OPERATIONAL_PATHS))
    lines.append("output only: " + ", ".join(OUTPUT_PATHS))
    if exp.cli_overrides:
        lines.append(f"command-line overrides: {exp.cli_overrides}")
    if exp.mode == "resume":
        lines.append(f"resume      : from {repo_relative(exp.resume_source) if exp.resume_source else None}")
        if checkpoint_meta is not None:
            diffs = compare_compatibility(checkpoint_compatibility_view(checkpoint_meta),
                                          compatibility_view_from_values(v, exp.reward, dict(exp.extra_env)))
            lines.append(f"              checkpoint num_timesteps {checkpoint_meta.get('num_timesteps')}  "
                         f"compatibility diffs {diffs or 'none'}")
    return "\n".join(lines)
