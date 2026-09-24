# RL M7b: TOML experiment configuration and reward-contract versioning

M7b adds two things to the M7a parallel PPO stack without changing its
behaviour: a strict, reproducible TOML experiment configuration whose
checked-in profile resolves to exactly the M7a pilot, and a separately
versioned reward contract `btt_reward_v2` (v1 plus a one-time `-5.0`
native-failure penalty). No native, decomp, libultraship or torch change; no
M0-M6 file changed; Track 1, the observation fields, the M3 environment, the
M4 artifact format and the 300-unit anomaly threshold are unchanged. No
native RNG inspection, logging, validation, control, comparison or hashing
exists. The next long training experiment was NOT started, no standby
process exists, and v1 vs v2 learning quality was NOT compared.

M7c (`docs/rl_standby_lifecycle_m7c.md`) later added the standby-process
lifecycle on top of this configuration layer: three `[environment]` keys
(`standby_preboot`, `standby_count`, `standby_wait_timeout_s`), one
`[resume]` key (`allow_lifecycle_change`), a `lifecycle` field class, and
`CONFIG_MODULE_VERSION = 2`. The historical profiles below still resolve to
no standby, but because the lifecycle keys are part of the semantic and
compatibility views their fingerprints computed by module version 2 differ
from the module-version-1 values quoted in this document (the resolved
values, the reward contracts and the resume rules are unchanged; a resume
compares views key by key, never fingerprints, and treats a checkpoint
without a lifecycle record as standby-off).

```text
rl/configs/*.toml  --tomllib-->  experiment_config.Experiment (validated, resolved, fingerprinted)
                                     |  config_from_experiment()
                                     v
                               m7_trainer.M7Config  -->  M7Run (unchanged M7a machinery; reward contract, net_arch,
                                                          ports, provenance now explicit)
                                     |
                worker: Track 1 -> M4 recorder -> M7RewardWrapper(RewardContract) -> M3/M2 -> BattleShip
```

## Files

| File | Role |
| --- | --- |
| `rl/experiment_config.py` (new) | schema (`FIELDS`), `tomllib` parsing, validation, path resolution, fingerprints, resume-compatibility views, legacy M7a argument translation, TOML writer, dry-run description |
| `rl/btt_rewards.py` (new) | `RewardContract`, canonical `btt_reward_v1` / `btt_reward_v2`, custom identities, `reward_step()` (M5 `reward_v1()` + failure term), `expected_return()`, legacy record normalisation |
| `rl/configs/m7_mario_us_reward_v1.toml` (new) | the M7a pilot, reproduced exactly |
| `rl/configs/m7_mario_us_reward_v2.toml` (new) | identical except `btt_reward_v2` |
| `rl/train_m7.py` | `--config` / `--dry-run` / `--run-id` / `--output-root` / `--resume-from`; legacy subcommands kept as a marked compatibility path through the same schema |
| `rl/eval_m7.py` | `--config` for `checkpoint` and `random`; a checkpoint is evaluated under its own reward contract |
| `rl/m7_trainer.py` | `M7Config` gains `reward`, `net_arch`, `activation`, `norm_obs`, port-block settings, `worker_runtime_root`, `allow_executable_change`, `experiment`; `config_from_experiment()`, `policy_kwargs()`; run directories get `experiment.toml` + `experiment_resolved.json`; `run.json`, `checkpoint.json`, `model.zip` and `training_summary.json` carry the reward contract and the experiment block; resume compares the full compatibility view and the executable sha256 |
| `rl/btt_parallel.py` | `M7RewardWrapper(env, contract)`, `m7_contracts(horizon, reward)`, `WorkerSpec.reward_contract` / `.experiment`, tracker labels and summaries record the contract, `failure_penalty_applied` / `_terms` / `_total` |
| `rl/m7_evaluation.py` | `EvaluationSettings.reward` / `.experiment` / port blocks; `read_checkpoint_set()` normalises legacy v1 records; `checkpoint_reward_contract()`; evaluation results record the contract and the experiment block |
| `rl/m7_report.py` | pilot report carries `experiment` and `reward_contract` |
| `rl/m7b_config_tests.py` (new) | 16 ROM-independent cases |
| `rl/m7b_smoke.py` (new) | 7 game-backed cases |
| `docs/rl_experiment_configuration_m7b.md` (new) | this document |

`rl/requirements.txt` is unchanged: TOML is read with Python 3.13's
standard-library `tomllib`; no dependency was added.

## Phase A inventory (what M7a actually recorded)

`run.json`: milestone, run_id, purpose, created_utc, lineage, contracts,
horizon, n_envs, seeds, executable {path, sha256}, revisions, m6_flags,
versions, torch_threads, port_blocks, job_object, config
(`M7Config.to_json`), worker_runtime, ppo (`resolved_ppo_params`).
`checkpoint.json`: the same run keys plus checkpoint_schema, label,
created_utc, num_timesteps, n_updates, rollouts_completed, vecnormalize
{norm_obs, norm_reward, clip_obs, clip_reward, epsilon, obs_rms_count},
files {sha256}. Comparison report: equal_workload {rollout_size,
total_transitions, rollouts, horizon, batch_size, n_epochs, gamma,
gae_lambda, base_seed, checkpoint_interval, periodic_episodes, m6_flags}.
Evaluation results: evaluation_schema, label, checkpoint,
checkpoint_num_timesteps, horizon, per-mode seed / workers / aggregate /
episode rows (raw_return). Artifact labels: milestone, role, run_id, rank,
worker_episode, checkpoint_label, contracts (full `m7_contracts` including
`reward_constants`), startup, end labels.

Classification: immutable (behaviour and compatibility): horizon, n_envs,
n_steps, batch_size, n_epochs, gamma, gae_lambda, learning_rate,
clip_range, ent_coef, vf_coef, max_grad_norm, contracts, clip_obs,
VecNormalize mode, m6_flags, device. Behaviour-affecting but permitted to
change: base_seed, total_timesteps, eval_seed, evaluation episode counts,
periodic_episodes, position_delta_threshold. Output or location: run_id,
runs_dir, executable path, purpose. Operational or diagnostic: checkpoint
and evaluation cadence, eval_workers, retain_failed_cap, startup_attempts,
timeouts, torch_threads, port blocks, job_object, revisions, versions, test
hooks. Implicit M7a values now explicit: rollout 5120 with
`n_steps = 5120 // n_envs`, `MlpPolicy` with SB3's default 64x64 tanh,
VecNormalize `norm_obs=True, norm_reward=False, clip_obs=10`, both M6
flags, port blocks `30000 + 250 * rank`, the pilot cadence, and the task
identity (US build, Mario, Break the Targets, native port 0, costume 0)
that only existed in `port/rl/rl_boot.cpp`.

Gaps closed by M7b: resume did not compare net_arch, activation, clip_obs,
executable sha256, m6_flags or device; evaluation did not record the reward
contract and always used the v1 constants; `model.zip` carried no reward
identity; no run stored its source configuration or a fingerprint.

## Schema and checked-in profiles

`schema = "battleship_experiment_v1"`; every key is required unless a
default is listed.

| Table | Keys |
| --- | --- |
| `[run]` | `name`, `mode` (`train` / `pilot` / `resume`), `base_seed`, `total_transitions` (cumulative lineage target), `output_root`, `notes` (default `""`) |
| `[task]` | `id` (`ssb64_us_mario_btt_v1` only), `game_version` (`us` / `jp`), `character` (12 fighters), `stage` (`btt_*` / `btp_*`), `player` (native port), `costume`; every field must match the task table entry, so every other combination is rejected until implemented |
| `[contracts]` | `protocol_version` (1), `observation` (`btt_policy_obs_v1`; M7g Phase K also `btt_policy_obs_v2_spatial`), `action` (`btt_s9_b8_v1`), `reward` (`btt_reward_v1` / `btt_reward_v2` / `custom`), `artifact_schema` (1) |
| `[reward]` | `target_broken`, `per_step`, `clear_bonus`, `failure_penalty` (canonical ids enforce their exact values) |
| `[environment]` | `executable`, `horizon`, `process_count`, `no_render`, `raphnet_disable`, `startup_attempts`, `startup_timeout_s`, `ready_timeout_s`, `request_timeout_s`, `exit_timeout_s`, `step_timeout_s`, `worker_runtime_root` (default `""` = `<run>/workers`), `port_block_base`, `port_block_size`, `position_delta_threshold` (300 for Mario) |
| `[ppo]` | `policy` (`MlpPolicy`; `MultiInputPolicy` with observation v2), `net_arch`, `activation` (`tanh` / `relu`), `learning_rate`, `rollout_size`, `n_steps`, `batch_size`, `n_epochs`, `gamma`, `gae_lambda`, `clip_range`, `ent_coef`, `vf_coef`, `max_grad_norm`, `torch_threads`, `device` (`cpu`) |
| `[ppo.vecnormalize]` | `normalize_observations`, `normalize_rewards` (must be `false`), `clip_obs` |
| `[checkpoint]` | `interval`, `initial` |
| `[evaluation]` | `interval`, `initial`, `final`, `deterministic_episodes`, `stochastic_episodes`, `random_baseline_episodes`, `seed`, `workers` (default 0 = `process_count`) |
| `[artifacts]` | `periodic_episodes`, `retain_failed_cap` |
| `[resume]` | `source_checkpoint` (default `""`; required with `mode = "resume"`, forbidden otherwise), `allow_executable_change` (default `false`) |

Deeper SB3 values that M7a never varied (clip_range_vf None,
normalize_advantage True, target_kl None, no SDE, orthogonal init, Adam eps
1e-5) are not configurable; they are recorded as resolved values as before.

`rl/configs/m7_mario_us_reward_v1.toml` resolves to N=5, rollout 5120,
`n_steps` 1024, batch 512, 10 epochs, gamma 0.999, GAE lambda 0.995,
learning rate 3e-4, clip 0.2, MLP 64x64 tanh, CPU, one Torch thread,
observation normalisation on, reward normalisation off, clip_obs 10,
horizon 3600, 1,024,000 transitions, checkpoint every 51,200, evaluation
every 102,400 with initial and final sets (2 deterministic + 20 stochastic
episodes, seed 12345, random baseline 100), periodic artifact every 10
episodes, anomaly threshold 300. `m7_mario_us_reward_v2.toml` differs only
in `contracts.reward`, `reward.failure_penalty`, `run.name` and `run.notes`
(`valid_profiles` proves the set of differing keys is exactly that).

Relative paths resolve against the repository root, never the current
working directory (game processes run with private working directories).

## Validation behaviour

Rejected, with the full field path and the offending value in the message
(several problems are reported together):

- unknown keys and tables, missing required keys, wrong types (an integer
  field refuses `512.0`, a boolean refuses `1`), invalid enum values,
  non-finite numbers (`inf`, `nan`), out-of-range values;
- rollout geometry: `rollout_size != n_steps * process_count`, a batch that
  does not divide the rollout, a batch larger than the rollout, a
  transition target that is not a multiple of the rollout, a checkpoint
  interval that is not a multiple of the rollout, an evaluation interval
  that is not a multiple of the checkpoint interval or has no checkpoints,
  evaluations scheduled with zero episodes;
- unsupported task ids and any task field that disagrees with the task
  table (JP, other fighters, BTP stages, other ports or costumes), an
  executable whose basename is not the task's (`BattleShip-JP.exe`);
- unsupported observation / action / protocol / artifact-schema values,
  policies other than `MlpPolicy` / `MultiInputPolicy`, devices other than `cpu`;
- M7g Phase K observation rules: `btt_policy_obs_v1` requires `MlpPolicy` and
  `btt_policy_obs_v2_spatial` requires `MultiInputPolicy`; v2 also requires
  `normalize_observations = true` and the validated network (`net_arch = [64, 64]`,
  `tanh`). v2's native flag (`SSB64_RL_SPATIAL=1`) and VecNormalize keys are
  derived from the observation contract, never written in the TOML. Every v1
  profile resolves to exactly its previous values and fingerprints
  ([`rl_obs_v2_phase_k_readiness_m7g.md`](rl_obs_v2_phase_k_readiness_m7g.md));
- canonical reward ids with altered values (`btt_reward_v1` with a
  penalty, `btt_reward_v2` without it), unknown reward ids, custom ids that
  do not match their values, reward normalisation enabled;
- port blocks that reach into the OS dynamic range (static bound 49152; the
  live `netsh` range is checked again at run time) or past 65535, process
  counts outside 1..32;
- resume inconsistencies (`mode = "resume"` without a source, a source
  with another mode, `allow_executable_change` outside resume), and later
  incompatible checkpoints (see below);
- unsafe or ambiguous paths: empty, whitespace-padded, `~`, wildcards or
  reserved characters, an output root that is the repository root or one of
  its parents, inside the executable directory (worker files would sit next
  to the user's `BattleShip.cfg.json`), inside a source directory, or equal
  to the worker runtime root.

Nothing is corrected silently; a configuration either resolves completely
or raises `ConfigError`.

## Dry run

```text
python rl/train_m7.py --config rl/configs/m7_mario_us_reward_v1.toml --dry-run
python rl/train_m7.py --config rl/configs/m7_mario_us_reward_v2.toml --dry-run --run-id x --output-root runs/x
python rl/train_m7.py --config rl/configs/m7_mario_us_reward_v1.toml --resume-from runs/m7a_pilot_n5/final --run-id r --dry-run
python rl/train_m7.py pilot --n-envs 5 --run-id m7a_pilot_n5 --dry-run        # legacy path, same output
```

A dry run parses and validates the whole file, resolves defaults and
paths, prints the resolved configuration (text and JSON), the contract
identities, the executable fingerprint, the three fingerprints, the
compatibility-affecting field list, the permitted-on-resume and operational
lists, the command-line overrides and, for a resume, the checkpoint's
`num_timesteps` and the compatibility diffs. It launches nothing, imports
neither PyTorch nor SB3, and writes nothing unless `--dry-run-output <file>`
names a file for the resolved JSON. `dry_run_non_mutation` runs four dry
runs from an empty working directory and checks that the working directory,
`runs/` and `rl/configs/` are untouched, that an invalid profile exits 2
naming `ppo.batch_size = 500`, and that `--dry-run-output` writes exactly
that one file.

Excerpt of the v1 dry run (2026-09-22):

```text
experiment  : m7_mario_us_reward_v1  (mode pilot)
source      : toml rl/configs/m7_mario_us_reward_v1.toml  sha256 617bb32ac283281f6f9b90a8fd8326853c22dd6bfd5869fb3f7a7dfbfc94f029
task        : ssb64_us_mario_btt_v1  (us, mario, btt_mario, port 0, costume 0)
contracts   : protocol 1  observation btt_policy_obs_v1  action btt_s9_b8_v1  artifact_schema 1
reward      : btt_reward_v1  {'target_broken': 1.0, 'per_step': -0.001, 'clear_bonus': 10.0, 'failure_penalty': 0.0}  canonical=True
executable  : {'path': 'build-us/Release/BattleShip.exe', 'exists': True, 'sha256': '57d61fe0b2a60265...', 'size': 23510016}
ppo         : MlpPolicy net_arch [64, 64] tanh  lr 0.0003  rollout 5120 = n_steps 1024 x N  batch 512  epochs 10  gamma 0.999 ...
fingerprints: source 617bb32a...  semantic d49c320d77e8f2c76b458170ade1df00f6dafd0a5a763e7615f5b98a02b88d19  compatibility 73de304c...
dry run: no process launched, no file written
```

## Command-line ownership

The TOML is the only source of behavioural settings. `train_m7.py` accepts
`--config`, `--dry-run`, `--dry-run-output`, `--run-id` (`run.name`),
`--output-root` (`run.output_root`) and `--resume-from` (`run.mode =
resume` + `resume.source_checkpoint`); every override is re-validated as a
whole and recorded in the experiment block (`cli_overrides`). A request to
override any other field raises `ConfigError`. `eval_m7.py` accepts
`--config` (operational settings, the random baseline's episode count /
seed / reward) plus its evaluation selection arguments.

The M7a subcommands `train`, `compare`, `pilot`, `resume` still work. They
are a marked compatibility path: `experiment_config.from_legacy_arguments`
translates them into the same schema (a generated TOML with a header
naming the original arguments becomes the run's `experiment.toml`,
`source.kind = "legacy_cli"`), so there is exactly one resolved
representation. `compare` places its runs under
`<runs>/<compare_id>/run<k>_n<N>` as before, each with its own experiment
block (run ids are the leaf names).

## Fingerprints and saved provenance

| Fingerprint | Over | Changes when |
| --- | --- | --- |
| `source_sha256` | the exact TOML bytes | any byte, including comments and formatting |
| `semantic_fingerprint` | canonical JSON (sorted keys, no whitespace, shortest float repr) of every `immutable` + `semantic` resolved value, the resolved reward contract and the task table entry | behaviour changes only |
| `compatibility_fingerprint` | the `immutable` values, the resolved reward and the resolved child flags | what a resume must not change |

`fingerprints` proves: a reformatted copy of the v1 profile (new comment,
inline comment, `3e-4` spelled `0.0003`, extra blank line, swapped key
order) has a different source sha256 and the same semantic and
compatibility fingerprints; changing every output/operational field keeps
the semantic fingerprint; changing gamma, net_arch, horizon, seed,
transition target, evaluation seed, anomaly threshold, periodic cadence,
clip_obs or a flag changes it, and only the immutable ones among them
change the compatibility fingerprint; the fingerprint is identical across
interpreter processes.

Every real run directory holds `experiment.toml` (byte-exact source copy,
sha256 re-checked against the source fingerprint at run start),
`experiment_resolved.json` (config, resolved values, fingerprints, field
classes), and `run.json` / `training_summary.json` / every
`checkpoint.json` carry the experiment block (name, mode, task, reward id
and values, source kind/path/sha256, both fingerprints, overrides,
compatibility view, file hashes) next to the existing executable sha256,
parent HEAD + dirty files + submodule commits and dependency versions.
`model.zip` stores `m7_reward_contract` and `m7_experiment` as SB3 model
attributes (restored on load and cross-checked against `checkpoint.json` by
the evaluator). Every artifact label carries `reward_contract`,
`reward_constants`, `experiment`, `failure_penalty_applied` and
`failure_penalty_total`; every episode summary carries the contract and the
penalty counts; every evaluation result carries `reward_contract`,
`experiment`, `model_reward_contract`; the pilot report carries
`experiment` and `reward_contract`.

Custom rewards: `contracts.reward = "custom"` resolves to the identity
`btt_reward_custom_<12 hex of sha256(canonical reward values)>` (the
reward component of the semantic fingerprint), recorded everywhere with the
run's semantic fingerprint beside it. A custom contract can never present
itself as v1 or v2, even with v2's values.

## Checkpoint and resume compatibility

A resume (`--resume-from` or `[resume]`) verifies the set (file hashes,
contracts including the horizon) and then compares the checkpoint's
compatibility view with the requested one BEFORE any directory exists. M7a
checkpoints (no experiment block) get their view derived from `contracts`,
`ppo`, `vecnormalize`, `m6_flags` and the one task M7a ran; a legacy
`reward_constants` record without `failure_penalty` is `btt_reward_v1`
with 0.0 and is never reinterpreted as v2.

| Field | On resume |
| --- | --- |
| task id, game version, character, stage, player, costume | immutable |
| observation / action / protocol / artifact contracts | immutable |
| reward id and all four values (custom identity included) | immutable |
| horizon, process_count (and therefore n_steps), no_render, raphnet_disable | immutable |
| policy, net_arch, activation, learning_rate, rollout_size, batch_size, n_epochs, gamma, gae_lambda, clip_range, ent_coef, vf_coef, max_grad_norm, device | immutable |
| VecNormalize: normalize_observations, normalize_rewards, clip_obs (also re-checked against the loaded `vecnormalize.pkl`) | immutable |
| executable sha256 | immutable unless `resume.allow_executable_change = true`; the accepted change is recorded in the lineage |
| run name, mode, output root, notes | new run directory, new identity |
| total_transitions | must exceed the checkpoint's `num_timesteps` by a positive multiple of the rollout (the difference is trained) |
| base_seed, checkpoint cadence, evaluation cadence / counts / seed / workers, periodic_episodes, retain_failed_cap, position_delta_threshold, timeouts, startup attempts, torch threads, port blocks, worker runtime root | permitted, recorded |

Every resumed run creates a new directory, records the lineage (source run,
checkpoint, timesteps, files, reward contract, experiment block, executable
change, versions at the checkpoint) and never touches the source run
(`resume_allowed`: all 571 source files byte-identical afterwards).

The real M7a pilot set `runs/m7a_pilot_n5/final` is compatible with the v1
profile (no diffs) and rejected by the v2 profile with exactly one diff,
`contracts.reward_resolved` (`checkpoint_compatibility`, `--dry-run`
resume).

## Reward contracts

`btt_reward_v1` (M5, frozen): `+1.0` per newly broken target, `-0.001` per
consumed native tick, `+10.0` once on the native clear, no failure penalty.
`btt_reward_v2` (M7b): the same plus `-5.0` exactly once on the terminal
step whose `termination_reason` is `native_failure` (M7's
`btt_native_failure_v1`). The target, step and clear terms are the unchanged
M5 `reward_v1()`; `rl/btt_rewards.reward_step()` adds the failure term.
Nothing else was added: no survival bonus, route hint, curriculum,
remaining-target penalty or shaping.

The penalty cannot apply to a successful clear (`native_clear`), a horizon
truncation (`max_episode_steps`), an interruption (no step is produced), a
startup failure, a transport or protocol failure, a worker exception,
process cleanup or an administrative cancellation: those never carry the
`native_failure` reason, and a lifecycle failure reaches the learner as a
Track 1 truncation with reward 0.0 (`no_penalty_elsewhere`,
`request_timeout_cleanup` in the M7a smoke).

Rationale: under v1 a fall ends the `-0.001` per tick cost with no penalty,
and the M7a pilot's sampled policy fell in 19 of 20 final episodes. At the
3600-tick horizon the accumulated step cost is at most `-3.6`, so with
`-5.0` an early fall can never outscore surviving to the horizon with the
same number of targets. Whether that improves learning is NOT established
by M7b.

Verified returns (game-backed, `rl/m7b_smoke.py`, and scripted,
`rl/m7b_config_tests.py`):

| Episode | v1 | v2 |
| --- | --- | --- |
| 447-step TAS clear (`tas_input_2/mario_743.btti`, native clear, 10 targets) | 19.553 | 19.553 |
| known 432-step no-target fall (hold right, C-up every 40 ticks; consumed tick 431) | -0.432 | -5.432 (terminal step -5.001) |
| 300-tick horizon truncation, neutral input, 0 targets | -0.3 | -0.3 (no terminal term) |

The fall's episode summary and artifact labels record
`failure_penalty_applied = true`, `failure_penalty_terms = 1`,
`failure_penalty_total = -5.0` under v2 and `false / 0 / 0.0` under v1;
the artifact's `contracts.reward_contract` names the contract.

## M7a parity evidence

- `legacy_parity`: the legacy `pilot --n-envs 5 --run-id m7a_pilot_n5`
  arguments and the checked-in v1 profile have identical semantic and
  compatibility fingerprints; the only differing resolved values are
  `run.name` and `run.notes`; 37 value pairs read from
  `docs/rl_parallel_training_m7_pilot.json` (config, resolved PPO values,
  contracts) equal the translation; the generated legacy TOML re-parses to
  identical values.
- `policy_kwargs_parity`: the explicit `policy_kwargs` derived from the
  profile (pi/vf 64x64, Tanh) build a policy whose parameter digest is
  identical to SB3's implicit defaults with the same seed, and
  `resolved_ppo_params` records the same `net_arch` / `activation_fn` /
  `ortho_init` as the pilot.
- `config_parity` (game-backed): the v1 profile with bounded operational
  overrides (N=2, `n_steps` 2560, 10,240 transitions, horizon 600,
  checkpoint every 5120, periodic 4) and a raw M7a `M7Config` with the same
  values produced 16 finished episodes with identical rank, episode index,
  end reason, length, targets, return and native-action digest, identical
  rollout statistics and identical resolved PPO values; the derived TOML's
  semantic fingerprint equals the legacy `train` translation of the same
  arguments. End-to-end throughput 256.8 vs 253.3 transitions/s (short
  horizon, N=2).
- The real pilot checkpoint is compatible with the v1 profile (see above).

## Bounded v2 integration smoke (`v2_ppo_smoke`, 2026-09-22)

Derived from the v2 profile: N=2, `n_steps` 2560, 15,360 transitions (3
rollouts, 30 optimizer updates), horizon 3600, checkpoint every 5120,
final evaluation with 1 deterministic + 2 stochastic episodes, seed 0.

| | |
| --- | --- |
| status | completed, leak-free, user config byte-identical, 4 checkpoint sets (`ckpt_000000000`, `ckpt_000005120`, `ckpt_000010240`, `final`) each with `vecnormalize.pkl` |
| episodes | 7 started, 5 finished: 2 falls, 3 horizon, 0 clears; targets mean 2.2, max 3 |
| falls with penalty | rank 1 episode 1: 832 steps, 1 target, return -4.832; rank 1 episode 2: 2061 steps, 2 targets, return -5.061; every finished return equals the v2 closed form; `failure_penalty_applied` true exactly for the falls |
| rewards reaching PPO | rollout return means -4.832, -2.8305, -1.1 (Monitor-compatible episode returns); explained variance 0.71 at the last update |
| throughput | 437 transitions/s end to end |
| reload and inference | the final set's `model.zip` restores `m7_reward_contract = btt_reward_v2` and the experiment block; the final evaluation (frozen statistics, parameters and `obs_rms` unchanged) ran 1 deterministic (0 targets, horizon) and 2 stochastic episodes (mean 3.0 targets, 1 fall, raw returns equal the v2 closed form) |
| provenance | `experiment.toml` sha256 equals the source; `run.json`, every `checkpoint.json`, `training_summary.json`, 4 training artifacts and 3 evaluation artifacts carry `btt_reward_v2` and the semantic fingerprint |

This proves initialisation, reward plumbing, penalty recording,
checkpointing, reload and labelling. It says nothing about learning
quality; no v1 vs v2 comparison was run and none is claimed.

## Validation (2026-09-22)

`python rl/m7b_config_tests.py`: 16/16 PASS (valid_profiles,
validation_errors, path_resolution, fingerprints, rollout_geometry,
canonical_reward_enforcement, task_contract_rejection,
dry_run_non_mutation, legacy_parity, checkpoint_compatibility,
resume_changes, reward_arithmetic, penalty_once, no_penalty_elsewhere,
policy_kwargs_parity, checkpoint_metadata); no game launched.

`python rl/m7b_smoke.py`: 7/7 PASS (`runs/_m7b_smoke_final`), zero
`BattleShip.exe` after every case, user config sha256 `1b29d91b...` and
mtime unchanged after every case.

| Case | Evidence |
| --- | --- |
| `tas_v1_v2` | 447 steps, native clear, return 19.553 under v1 and v2, clear term 10.0, no failure term |
| `fall_v1_v2` | 432 steps, `native_failure`, -0.432 / -5.432, terminal step -0.001 / -5.001, summary and artifact labels as above, 432 canonical rows |
| `truncation_v2` | 300 steps, `max_episode_steps`, -0.3, no penalty flag |
| `config_parity` | see "M7a parity evidence" |
| `v2_ppo_smoke` | see above |
| `resume_allowed` | resume of `ckpt_000005120` with a new name, cumulative target 10,240, checkpoint cadence 10,240, notes and request timeout changed: 5120 additional transitions, timesteps 5120 -> 10240, lineage recorded (reward v2, source experiment, no executable change), 571 source files unchanged, provenance files present |
| `resume_rejected` | v1 profile, gamma 0.99, horizon 1800, net_arch [32, 32], clip_obs 5, N=1, custom reward, a flag change and a different executable sha256 all refused before any directory exists; the executable override is accepted only with `resume.allow_executable_change = true` and is recorded |

`python rl/m7_smoke.py`: **20/20 PASS** (`runs/_m7b_m7a_smoke_final`, the
unchanged M7a suite on the modified stack), zero processes after every
case, user config unchanged.

Existing regressions, sequential (`runs/_m7b_regressions.log`), zero
`BattleShip.exe` after each step, user config sha256 `1b29d91b...` identical
before and after each step:

| Suite | Result |
| --- | --- |
| `python rl/m6_equivalence_regression.py` | exit 0 (34.6 s) |
| `python rl/m6_raphnet_bypass_regression.py` | exit 0 (127.3 s) |
| `python rl/m5_smoke.py --child-env SSB64_RL_NO_RENDER=1 --child-env SSB64_RAPHNET_DISABLE=1` | exit 0 (37.7 s) |
| `python rl/m5_smoke.py` | exit 0 (93.4 s) |
| `python rl/m4_smoke.py` | exit 0 (68.4 s) |
| `python rl/m3_gym_smoke.py` | exit 0 (105.4 s) |
| `python rl/m2_restart_regression.py` | exit 0 (56.4 s) |
| `python rl/m2_lifecycle_smoke.py` | exit 0 (23.2 s) |
| `python rl/m1e_replay_regression.py --port 52101` (hand-launched process, cwd `build-us/Release`) | exit 0, game exit 0, result clear 10 / 446 / 447, host_frames 511 |
| native replay (`SSB64_BTT_INPUT`, `SSB64_MAX_FRAMES=1500`, cwd `build-us/Release`) | `COMPLETE input_tick=447 time_passed=446`, `frames=468 actual_checksum=0x93E9EFB4`, result clear 10 / 446 / 447 |

Evaluation CLI with `--config` (game-backed, 2026-09-22): `eval_m7.py random
--config <v2> --episodes 2 --workers 2` records `btt_reward_v2`;
`eval_m7.py checkpoint <v2 smoke final> --config <derived v2 profile>`
evaluates under the checkpoint's contract with frozen statistics (parameters
and `obs_rms` unchanged); the v1 profile against the v2 checkpoint is refused
with the `contracts.reward_resolved` diff. `git diff --check` clean on the
tracked changes; every new file free of trailing whitespace.

## Known limitations

- The `mode` field distinguishes `train`, `pilot` and `resume` only as a
  recorded purpose; `pilot` and `train` behave identically (the cadence is
  explicit in the profile). The `compare` workflow exists only on the
  legacy path.
- Only `ssb64_us_mario_btt_v1` is accepted; the task fields for other
  fighters, BTP stages and the JP build are validated but rejected.
- Deeper SB3 values (clip_range_vf, normalize_advantage, target_kl, SDE,
  orthogonal init, Adam eps) are fixed, not configurable.
- Dependency versions are recorded in every checkpoint but a resume does
  not reject a version change (the loaded pickles decide); the versions at
  the checkpoint are copied into the lineage.
- A resume with a legacy checkpoint derives its task id from the fact that
  M7a ran one task only.
- `worker_runtime_root` moves the whole worker directory (runtime, M2
  episode directories, artifacts) and is validated but was not exercised by
  a game run.
- The v2 integration smoke observed two falls with the penalty; it is not a
  learning result and the profile's 1,024,000-transition budget was not
  run.

## Rollback

The reward and configuration layers are additive. To return to M7a
behaviour without deleting files: run the legacy subcommands (they resolve
to the M7a values) or the v1 profile; every v1 run remains byte-compatible
with M7a checkpoints. To remove M7b entirely: delete
`rl/experiment_config.py`, `rl/btt_rewards.py`, `rl/configs/`,
`rl/m7b_config_tests.py`, `rl/m7b_smoke.py`, this document, and restore
`rl/train_m7.py`, `rl/eval_m7.py`, `rl/m7_trainer.py`, `rl/btt_parallel.py`,
`rl/m7_evaluation.py`, `rl/m7_report.py` from commit 9e6de81. Checkpoints
written by M7b differ from M7a's only by the added `reward_contract` and
`experiment` keys in `checkpoint.json`, the `failure_penalty` key in
`reward_constants`, and two extra attributes in `model.zip`; M7a code
ignores the extra keys but would report a contract mismatch on the
`reward_constants` dictionary, so keep M7b code for M7b checkpoints.

## Recommended next step

Attack the dominant cost before any long run: the standby (pre-booted)
BattleShip process per worker that M7a identified (restart steps were 56 %
of collection wall time), measured with `train_m7.py compare` semantics
under a TOML profile. Only after that, run the v1 and v2 profiles as two
full pilots with the fixed evaluation protocol and compare them by the
learning-evidence rule; never by training reward.

## Commands

```text
python rl/m7b_config_tests.py
python rl/m7b_smoke.py
python rl/train_m7.py --config rl/configs/m7_mario_us_reward_v1.toml --dry-run
python rl/train_m7.py --config rl/configs/m7_mario_us_reward_v2.toml --run-id <run name>
python rl/train_m7.py --config rl/configs/m7_mario_us_reward_v2.toml --resume-from runs/<id>/checkpoints/ckpt_<t> --run-id <new name>
python rl/eval_m7.py random --config rl/configs/m7_mario_us_reward_v2.toml --out runs/<dir>/random_baseline
python rl/eval_m7.py checkpoint runs/<id>/final --config rl/configs/m7_mario_us_reward_v2.toml --out runs/<id>/evaluations/manual
```
