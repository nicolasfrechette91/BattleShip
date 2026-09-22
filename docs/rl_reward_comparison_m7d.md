# RL M7d: controlled `btt_reward_v1` versus `btt_reward_v2` comparison

M7d answers one question with gameplay, not reward: does `btt_reward_v2`
(v1 plus a one-time `-5.0` on the `native_failure` fall termination) produce
better Mario Break the Targets behaviour than `btt_reward_v1` under an
otherwise identical training contract? Six fresh PPO runs - three paired
seeds x two reward contracts, 1,024,000 transitions each, N=5 with the M7c
standby lifecycle - were trained in a counterbalanced order and evaluated
after training with frozen normalisation statistics.

**Result under the pre-registered rule: v2 preferred - and therefore
`btt_reward_v2` is *provisionally* selected for the next milestone.** Across
the three seeds the final stochastic policy of v2 broke **+0.230 targets per
episode** (seed-stratified 95 % CI `[0.110, 0.350]`, significant in 2 of 3
seeds) and fell in **76.7 percentage points fewer episodes** (CI
`[-0.810, -0.720]`, significant in 3 of 3 seeds).

v2 qualifies through exactly one of the rule's paths: the **target path**,
`v2_more_targets` - "significantly more targets per episode, in at least 2 of
3 seeds". It does **not** qualify through the fall-reduction path
(`v2_fewer_falls_non_inferior`): that path additionally requires no
significant increase in idle episodes, and the idle increase is significant
(`CI(I)` lower bound `+0.370`), so the no-idling condition failed. The fall
reduction is reported as a large, consistent secondary effect, not as the
reason for the classification.

Neither contract ever cleared the stage: **0 verified clears in all 6,108
episodes M7d played** - 2,420 training and 3,688 evaluation episodes, counted
category by category in the census below.

Four honest qualifications, stated up front:

- **No clears under either reward.** The primary objective of the ranking
  (a verified clear) was never reached, so the decision rests on the
  secondary criterion (targets). The best episode anywhere broke 6 of 10.
- The seed-cluster interval for targets, `[-0.330, 0.660]`, includes zero:
  with three seeds the *direction* of the target effect is not established
  beyond these seeds. Seed 0 in fact went the other way (`-0.36` targets).
- v2's advantage on targets is partly the mechanical consequence of not
  dying: its episodes run the full 3,600 ticks, so it has more time to find
  targets. Per 1,000 ticks alive v2 is *less* efficient than v1 everywhere
  (1.10-1.30 versus 1.72-3.79 targets per 1,000 ticks).
- v2 idles significantly more: 45-54 % of its final episodes reach the
  horizon with at least 1,800 ticks (half the episode) after their last
  target break, against 0-22 % under v1 (`I = +0.433`, CI
  `[0.370, 0.497]`; 73-100 % of its episodes reach the horizon). It
  survives, and then stops making progress. Its per-episode target count is
  not lower (it is higher in 2 of 3 seeds), so this is not the full "idle
  instead of playing" failure mode - but it is exactly the condition that
  disqualified the fall-reduction path of the decision rule, and it is the
  behaviour to attack in the next milestone.

Everything below is reproducible from `docs/rl_reward_comparison_m7d.json`
(machine-readable results), `docs/rl_reward_comparison_m7d_manifest.json`
(the resolved comparison manifest and the decision rule, written before any
training) and the run directories under `runs/m7d/`.

## Scope and frozen contracts

Unchanged: native code, the decomp and all three submodules; M1c one action
per native tick (reset returns the tick-0 observation without consuming an
action); Track 1 `btt_s9_b8_v1` = `MultiDiscrete([9, 8])` (the 7.43 TAS is
never approximated through it); `btt_policy_obs_v1` (15 float32) with
observation-only VecNormalize; both reward contracts and their exact values;
process restart as reset with the M7c standby lifecycle (N=5, at most one
active and one standby BattleShip per worker, promotion returns the verified
cached tick-0 observation, the first action after promotion consumes tick 0);
the M4 artifact format; the 300-unit anomaly detector. No native RNG
inspection, logging, validation, control, comparison or hashing exists
anywhere in M7d; seeds are Python / NumPy / PyTorch / SB3 only and never
reach the game.

Authoritative replay, re-validated in the regression chain below: 468 source
rows, 10 targets, displayed time 7.43 s, `completion_time_passed = 446`,
`completion_input_tick = 447` (never collapsed, never decremented), 447
interactive actions, last `consumed_tick` 446, final `step_count` 447, 21
rows unsubmitted, native checksum `0x93E9EFB4`.

## Phase A: preflight (read-only)

| Check | Result |
| --- | --- |
| `git status --short` | clean |
| `git log -5 --oneline` | `0bd6f2d` complete standby process lifecycle optimization, `0223839` added experiment configuration and reward v2, `9e6de81` added parallel PPO training and validate training baseline, `20ab62e` added Raphnet bypass, `1868008` added no-render RL mode and validate throughput |
| `git submodule status` | decomp `91d7b6b7` (heads/rl-main), libultraship `805f1950` (heads/m6/raphnet-bypass), torch `3aa9c973`; no pointer modified; all three submodule working trees clean |
| `git diff --check` | exit 0 |
| M7c committed | yes: HEAD `0bd6f2d3bd59da4adfb4b022244be1cc60e73003` contains all 19 M7c files |
| leftover processes | zero `BattleShip.exe`, zero `python.exe` |
| executable | `build-us/Release/BattleShip.exe` sha256 `57d61fe0b2a602659e0a1685a58266f652e8ce2ad35f767ace54943da23fc56b`, 23,510,016 bytes (the M6 / M7a-M7c build) |
| user configuration | `build-us/Release/BattleShip.cfg.json` sha256 `1b29d91b80051a135352bc7aaf26b49c749d7efee49fe71177396ffce2348409`, 36,885 bytes, mtime 2026-09-22 10:53:51 (last rewritten byte-identically by the M7c regression chain, by design) |
| source TOML hashes | v1 `617bb32a...`, v2 `065e9ae4...`, v1_standby `bbee55d9...`, v2_standby `736d0df0...` (all LF) |
| standby profiles resolve | both dry runs exit 0: N=5, standby on, expected maximum 10 game processes (training) / 10 (evaluation); v1_standby semantic `71c3d35615cae6d6...` / compatibility `df5206324f6e2c62...`; v2_standby `79cb0264d04956e8...` / `ac622dfa7b3a5d78...`; of 191 resolved keys the pair differs in exactly `contracts.reward`, `reward.failure_penalty`, `run.name`, `run.notes` (plus derived hashes and paths) |
| configuration resolution unchanged | the historical v1 profile still resolves to semantic `c93faaf9...`, the value M7c recorded |
| dependency versions | Python 3.13.2, Gymnasium 1.3.0, Stable-Baselines3 2.9.0, PyTorch 2.14.0+cpu, NumPy 2.5.3 |
| machine | Intel i5-9600K (6 cores / 6 threads), 15.9 GiB RAM, Windows 11 Home 10.0.26200, Balanced power plan, system-managed pagefile, 144.6 GiB free disk |
| historical results preserved | all M7a-M7c directories present; byte fingerprint of every historical file taken before any M7d work: 6,500 files, 125.8 MB, aggregate `9958bbc0...` (the 530 `.tcc` junctions deliberately not followed) |
| seeds | canonical `base_seed = 0`; the schema requires `base_seed >= 0`, so the adjacent valid seeds are 1 and 2 |
| estimated cost | about 1.6 h training + 2.6 h evaluation + about 1 h verification; about 1.5 GB of run output |

Findings that shaped the design (each approved before implementation):

1. **The canonical evaluation cadence breaks the 10-process bound.**
   `evaluation.interval = 102400` evaluates *inside* `learn()`
   (`M7Run._boundary`, called from the rollout-start callback) while the five
   training workers still hold their active and standby games: up to **20**
   BattleShip processes and about 7.4 GiB of extra private commit. M7c never
   exercised this (its comparison runs had no evaluation; its smoke evaluated
   only after the training workers closed).
2. **In-process evaluation reseeds the trainer's global RNGs.**
   `m7_evaluation.run_episodes` calls `set_random_seed(evaluation seed)`, and
   SB3's `PPO.load` calls `_setup_model() -> set_random_seed(model seed)`.
   PPO's action sampling (torch) and its minibatch permutation (NumPy global)
   draw from exactly those generators, so the evaluation cadence - classified
   `operational` and therefore outside the semantic fingerprint - changes the
   training trajectory. Documented, not changed (schema contract); M7d runs no
   evaluation inside the trainer. This also explains why `m7d_s0_v1` does not
   reproduce the M7a pilot episode for episode although both are seed 0 under
   v1: the pilot's in-training evaluations reseeded its stream.
3. **Ports 30000-30001** (rank 0's block) were held by IntelliJ IDEA; the
   exclusive-bind probe skips busy ports, and the user closed IntelliJ,
   EmuHawk, ChatGPT, Steam and NintendoSpy before Phase C, so every M7d run
   had its full block.
4. **SB3 detail:** VecNormalize updates `ret_rms` whenever `training=True`,
   even with `norm_reward=False` (it is never applied). "No reward
   normalisation" is therefore proven by the flag in every saved set plus a
   pass-through test, never by untouched return statistics.
5. Derived per-rank seeds overlap across base seeds (0-4, 1-5, 2-6); they seed
   only worker-side Python / NumPy / Gymnasium generators that never influence
   actions or gameplay (the game is deterministic and receives no seed).

## Experiment matrix

| order | run | seed | reward | profile | source sha256 | semantic fingerprint | untrained policy digest |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `m7d_s0_v1` | 0 | `btt_reward_v1` | `rl/configs/m7d/m7d_s0_v1.toml` | `467c4329...` | `71c3d35615cae6d6...` | `68155f41065d243f...` |
| 2 | `m7d_s0_v2` | 0 | `btt_reward_v2` | `rl/configs/m7d/m7d_s0_v2.toml` | `5499378d...` | `79cb0264d04956e8...` | `68155f41065d243f...` |
| 3 | `m7d_s1_v2` | 1 | `btt_reward_v2` | `rl/configs/m7d/m7d_s1_v2.toml` | `a1fb865e...` | `cbf09b0c39c0963a...` | `1dd753aeda5f450e...` |
| 4 | `m7d_s1_v1` | 1 | `btt_reward_v1` | `rl/configs/m7d/m7d_s1_v1.toml` | `794a9cd5...` | `13cf2546ce66d45b...` | `1dd753aeda5f450e...` |
| 5 | `m7d_s2_v1` | 2 | `btt_reward_v1` | `rl/configs/m7d/m7d_s2_v1.toml` | `791b4943...` | `0a899c3451dbbc62...` | `9fa632c6ffeb559d...` |
| 6 | `m7d_s2_v2` | 2 | `btt_reward_v2` | `rl/configs/m7d/m7d_s2_v2.toml` | `0ad1f512...` | `03e8d04e35c1e490...` | `9fa632c6ffeb559d...` |

Compatibility fingerprints: `df5206324f6e2c62...` for every v1 run and
`ac622dfa7b3a5d78...` for every v2 run - identical to the canonical M7c
standby profiles, because the seed is a permitted semantic field and the
evaluation cadence is operational. The seed-0 runs even keep the canonical
profiles' semantic fingerprints.

Counterbalancing as specified: seed 0 v1 then v2, seed 1 v2 then v1, seed 2
v1 then v2 (v1 at positions 1, 4, 5; v2 at 2, 3, 6). Runs were strictly
sequential; no two PPO experiments ever ran at the same time. The existing
tooling offers no safer equivalent order.

Resolved values shared by all six runs: task `ssb64_us_mario_btt_v1`; N=5
with standby (at most 10 BattleShip processes); horizon 3,600 native ticks;
1,024,000 transitions = 200 rollouts of 5,120 (`n_steps` 1,024); batch 512;
10 epochs; gamma 0.999; GAE lambda 0.995; learning rate 3e-4; clip 0.2;
`ent_coef` 0.0; `vf_coef` 0.5; `max_grad_norm` 0.5; `MlpPolicy` 64x64 tanh;
CPU; one Torch thread; observation-only VecNormalize (clip 10) with reward
normalisation disabled; checkpoint every 51,200 plus the untrained set (21
sets + `final`); periodic artifact every 10 finished episodes; both M6 flags;
port blocks `30000 + 250 * rank`; fresh initialisation; separate immutable
directories `runs/m7d/<run>/`.

## Proof of paired configuration equivalence

`python rl/m7d_run.py manifest` wrote
`docs/rl_reward_comparison_m7d_manifest.json` **before** any training
(`ok: true`, no problems). For every seed it contains the field-by-field diff
of the two resolved configurations, of the configurations the trainer
receives, and of the post-hoc evaluation plans, each classified against an
explicit allow-list; anything else would appear as `unexpected`:

| comparison | differing paths | categories | unexpected |
| --- | --- | --- | --- |
| resolved configuration, seed pair (x3) | 13 | reward identity and definition (`contracts.reward`, `reward.failure_penalty`, `resolved.reward.contract`, `resolved.reward.failure_penalty`); run identity (`run.name`, `run.notes`); output paths (`run_dir`, `source.path`); derived hashes (source sha256 and size, semantic and compatibility fingerprints) | none |
| trainer configuration, seed pair (x3) | 10 | reward (`reward.contract`, `reward.failure_penalty`, `experiment.reward_contract`, `experiment.reward_values.failure_penalty`); identity (`run_id`, `experiment.name`); path; hashes | none |
| evaluation plan, seed pair (x3) | 4 | `reward_contract`, `run`, `checkpoint`, `out_dir` | none |
| run vs its canonical M7c standby profile (x6) | 11-14 | seed (seeds 1 and 2 only), run identity, output root and paths, post-hoc evaluation (`evaluation.interval/initial/final`), derived hashes; compatibility fingerprint identical | none |
| same reward across seeds (x6 pairs) | seed, identity, paths, hashes; compatibility fingerprint identical | | none |

The compatibility views of a pair differ in exactly
`contracts.reward_resolved`; both runs of a pair carry the same `base_seed`;
and the untrained policy - built offline exactly as `M7Run` builds a fresh
model - has identical parameter and `obs_rms` digests within each pair and
different parameters across seeds. Every run's real `ckpt_000000000` was
verified against that offline digest after training.

## Tooling

| File | Role |
| --- | --- |
| `rl/configs/m7d/m7d_s{0,1,2}_v{1,2}.toml` (new) | the six explicit profiles: the canonical standby profile with seed, run identity, `output_root = "runs/m7d"` and no in-process evaluation |
| `rl/m7d_matrix.py` (new) | matrix, resolved comparison manifest with the pair proofs and the expected untrained-policy digests, directory / historical-tree / resume-lineage guards, post-hoc evaluation plan, pre-registered decision rule |
| `rl/m7d_run.py` (new) | `manifest`, `train` (one `train_m7.py` process per run under a live monitor, post-run verification, historical-tree re-fingerprint), `train --resume <run>` (own lineage only), `evaluate`, `replay`, `status` |
| `rl/m7d_analysis.py` (new) | per-episode metrics, bootstrap intervals, effect sizes, the decision rule, the episode census (`episode_census`, `clear_witnesses`), the machine-readable report |
| `rl/m7d_tests.py` (new) | 9 ROM-independent + 4 game-backed preflight cases |
| `rl/btt_parallel.py` (additive, 8 lines) | the worker episode summary carries `target_break_ticks` (consumed tick of every target break); artifacts and artifact labels unchanged |
| `rl/m7_evaluation.py` (additive, 30 lines) | `run_episodes` / `evaluate_checkpoint` accept `preserve_all` (default behaviour unchanged); evaluation rows carry `target_break_ticks`, `last_consumed_tick`, `startup_mode`, `failure_penalty_terms` |
| `docs/rl_reward_comparison_m7d_manifest.json`, `docs/rl_reward_comparison_m7d.json`, this document (new) | manifest, results, report |

No native, decomp, submodule or M0-M6 file changed; no action, observation,
stepping, lifecycle, reward, artifact, replay or anomaly contract changed; no
dependency added.

## Live monitoring and post-run verification

Every run was launched as `python rl/train_m7.py --config
rl/configs/m7d/<run>.toml` (its own kill-on-close job object) while a monitor
sampled the machine every 15 s into `runs/m7d/_matrix/monitor/<run>.jsonl`:
live BattleShip processes (Toolhelp32, threads > 0) and whether each belongs
to the trainer's tree, worker thread counts, BattleShip listeners in the M7
port blocks, memory and commit, system CPU, free disk, the user
configuration's sha256 and mtime, and every new `episodes.jsonl` row (reward
closed form under the run's contract, one-time v2 penalty, target and tick
ranges, break ticks, startup mode, anomalies, lifecycle failures, cold
fallbacks). Hard stops: more than 10 live BattleShip processes or listeners
in two consecutive samples, a user-configuration change, free disk below
5 GiB, or any episode invariant violated. **No hard alert fired in any run or
evaluation.** The only soft notes were low available commit (0.35-1.0 GiB;
the system-managed pagefile grew as needed) and, once, a BattleShip process
outside the monitored tree during the preflight.

After each run `verify_training_run` checked status, leak-free close, user
configuration identity, 1,024,000 transitions, empty lineage, seed, reward
contract, experiment provenance (TOML bytes and semantic fingerprint), all 21
checkpoint sets + `final` (file hashes, `norm_reward = False` in
`checkpoint.json` and in the unpickled `vecnormalize.pkl`, `norm_obs = True`,
`clip_obs = 10`, finite `obs_rms`), `ckpt_000000000` against the offline
fresh construction, every episode row, every preserved artifact (canonical
contract, consumed ticks exactly 0..n-1, tick-0 initial observation, reward
label, unique ids), lifecycle bounds and launcher-thread balance - then
re-fingerprinted the historical run tree.

## Phase B: preflight tests

`python rl/m7d_tests.py` - 9 unit cases (42 s; `unit_episode_census` was added
during the final accounting review and re-run afterwards, 9/9 PASS) and 4
game-backed cases (441 s), all PASS, zero `BattleShip.exe` after every case:

| case | evidence |
| --- | --- |
| `unit_matrix_profiles` | manifest `ok`; the pair proofs above; seeds 0/1/2; the counterbalanced order; every required value; six dry runs exit 0 showing "expected maximum game processes 10" and "evaluation : every 0 initial False final False" |
| `unit_fresh_paired_init` | untrained policy digests equal within each seed pair (`68155f41...`, `1dd753ae...`, `9fa632c6...`), different across seeds, reproducible; one shared `obs_rms` digest (VecNormalize defaults) |
| `unit_reward_normalization` | the trainer still constructs VecNormalize with `norm_reward=False`; for all six configurations a scripted reward sequence passes through unchanged (`ret_rms` grows to 105 samples and is never applied); `normalize_rewards = true` is refused by the schema |
| `unit_directory_guards` | planned directories unique, disjoint, outside history, absent; `M7Layout.create` refuses an existing directory; the snapshot comparison detects content, mtime, removal and addition |
| `unit_resume_guard` | a resume is accepted only inside a run's own lineage; other-seed, other-reward, tampered-seed and the M7a pilot checkpoint are refused; the generic M7b layer refuses a reward change but *permits* a seed change, which is why the matrix adds its own guard |
| `unit_validators` | seven invalid episode shapes detected (v2 fall without penalty, v1 fall with penalty, wrong closed form, short horizon, clear without completion facts, break-tick mismatch, unknown startup mode) |
| `unit_instrumentation` | `target_break_ticks` accumulates correctly (including two targets on one tick); `preserve_all` present on both entry points; the four new evaluation-row keys present |
| `unit_decision_rule` | the pre-registered rule returns the expected class on eight synthetic scenarios (identical, more targets, fewer targets, fewer falls with equal targets, survival bought with targets, fewer falls with idling, more clears, fewer clears) |
| `unit_episode_census` | a clear is counted only when its end reason, `cleared` flag, ten broken targets and completion clock all agree (each of the four removed in turn is detected and flips `witnesses_agree`); the census rows sum to the reported totals, every category's executed episodes equal its planned episodes with one uniform per-evaluation count, the primary endpoint is the final stochastic set, and `protocol_complete` holds with no missing evaluation. Verified to bite: stubbing one run's `final` summary away reports `500` of `600` final stochastic episodes, names both missing modes and sets `protocol_complete` false |
| `paired_bounded_training` | two bounded twins (25,600 transitions, seed 0, v1 and v2) through the orchestrator path: both `ckpt_000000000` equal to the offline construction; identical gameplay until the first fall rollout with the return differing by exactly `-5.0`; checkpoint sets identical before the first differing update (5,120 and 10,240) and divergent after (15,360, 20,480); v2 penalty terms equal to its falls, v1 zero; promotions > 0; at most 10 processes; leak-free |
| `bounded_posthoc_evaluation` | four evaluation sets: frozen statistics (parameters and `obs_rms` unchanged, `training=False`, `norm_reward=False`), paired untrained evaluations identical, every episode preserved with consumed tick 0 (including 7 standby-promoted episodes per set), a second evaluation into the same directory refused |
| `bounded_replay` | three artifacts (two falls, one horizon) replayed through native interactive stepping: every consumed tick, the targets, the terminal state and the full final observation equal, break ticks equal to the summary |
| `existing_suites` | `rl/m7b_config_tests.py` 16/16; `rl/m7c_standby_tests.py unit cold_vs_standby_replay terminal_paths_promotion` 6/6; `rl/m7b_smoke.py tas_v1_v2 fall_v1_v2 truncation_v2` 3/3 |

## Phase C: training results

Six runs, 2026-09-22 12:20-13:55 local, sequential and counterbalanced.

| run | order | wall min | e2e tr/s | collect tr/s | transitions | started | finished | clears / falls / horizon / lifecycle | targets mean | max | penalty terms | promotions / cold fallbacks / exposed wait s | threads | max BattleShip | CPU | min free commit GiB | anomalies | artifacts | ckpt sets |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| m7d_s0_v1 | 1 | 14.2 | 1212.7 | 1412.4 | 1024000 | 301 | 296 | 0 / 59 / 237 / 0 | 3.78 | 6 | 0 | 296 / 0 / 0.0 | 301/301 | 10 | 0.70 | 0.57 | 0 | 34 | 21 |
| m7d_s0_v2 | 2 | 14.7 | 1174.0 | 1357.8 | 1024000 | 296 | 291 | 0 / 19 / 272 / 0 | 3.45 | 6 | 19 | 291 / 0 / 0.8 | 296/296 | 10 | 0.71 | 1.02 | 0 | 33 | 21 |
| m7d_s1_v2 | 3 | 14.6 | 1177.3 | 1364.1 | 1024000 | 289 | 284 | 0 / 6 / 278 / 0 | 3.79 | 6 | 6 | 284 / 0 / 0.7 | 289/289 | 10 | 0.70 | 0.84 | 0 | 32 | 21 |
| m7d_s1_v1 | 4 | 16.9 | 1018.5 | 1173.4 | 1024000 | 567 | 562 | 0 / 487 / 75 / 0 | 3.17 | 6 | 0 | 562 / 0 / 4.5 | 567/567 | 10 | 0.80 | 0.37 | 0 | 61 | 21 |
| m7d_s2_v1 | 5 | 17.9 | 959.3 | 1097.4 | 1024000 | 686 | 681 | 0 / 609 / 72 / 0 | 3.38 | 6 | 0 | 681 / 0 / 2.5 | 686/686 | 10 | 0.83 | 0.39 | 0 | 72 | 21 |
| m7d_s2_v2 | 6 | 14.9 | 1154.4 | 1339.8 | 1024000 | 311 | 306 | 0 / 45 / 261 / 0 | 3.42 | 6 | 45 | 306 / 0 / 1.4 | 311/311 | 10 | 0.73 | 0.35 | 0 | 32 | 21 |

Every run: completed, leak-free, user configuration byte-identical and
unmoved, 21 checkpoint sets + `final` with `norm_reward = False` everywhere,
`ckpt_000000000` equal to the offline fresh construction, empty lineage (no
resume anywhere in M7d), zero lifecycle failures, zero startup failures or
retries, zero request timeouts, zero position-delta anomalies at the 300-unit
threshold, zero cold fallbacks, every launcher thread joined, at most 2
processes per worker and 10 in total, every preserved artifact canonical with
consumed ticks 0..n-1, and the historical run tree byte-identical afterwards.

**No training episode cleared the stage** (0 of 2,420 finished episodes).
Penalty bookkeeping is exact: 19, 6 and 45 `-5.0` terms in the v2 runs (one
per fall) and none in the v1 runs.

Training target distribution (all finished episodes):

| run | training target-count distribution (targets:episodes) |
| --- | --- |
| m7d_s0_v1 | 1:1 2:4 3:95 4:159 5:33 6:4 |
| m7d_s0_v2 | 0:3 1:4 2:11 3:141 4:106 5:24 6:2 |
| m7d_s1_v1 | 0:4 1:22 2:87 3:242 4:177 5:28 6:2 |
| m7d_s1_v2 | 1:2 2:6 3:89 4:142 5:43 6:2 |
| m7d_s2_v1 | 1:5 2:47 3:334 4:273 5:21 6:1 |
| m7d_s2_v2 | 0:1 1:5 2:19 3:132 4:137 5:11 6:1 |

### Common random numbers

With one seed both runs start from the same untrained policy and consume the
same PPO sampling stream, so they play identical episodes until the first
rollout whose reward can differ - the first rollout containing a fall:

| seed | first fall rollout | episodes compared | same episode set | identical gameplay | falls among them | v2 - v1 raw return |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 3 | 1 | True | 1 | 1 | [-5.0] |
| 1 | 2 | 1 | True | 1 | 1 | [-5.0] |
| 2 | 3 | 1 | True | 1 | 1 | [-5.0] |

Same actions, same targets, same lengths; the returns differ by exactly
`-5.0` on the fall and by nothing elsewhere. This is the tightest available
evidence that the reward contract is the only intentional difference.

## Phase D: evaluation results

Protocol (registered in the manifest before training): after training, in a
separate process, on saved checkpoint sets, through the same worker stack
(fresh processes, both M6 flags, standby lifecycle, 3,600-tick horizon, at
most 10 game processes), with frozen statistics (`training = False`,
`norm_reward = False`; policy parameters and `obs_rms` hashed before and
after and unchanged in **all 132 evaluation sessions**, 3,588 episodes, plus
the 100-episode random baseline), the same action seed 12345 for
every model and mode, 5 workers, one Torch thread, each checkpoint evaluated
under its own reward contract, and every episode's canonical artifact
preserved. Per run: `ckpt_000000000` and `final` with 100 deterministic + 100
stochastic episodes, and the nine intermediate checkpoints (every 102,400
transitions) with the canonical 2 + 20. One shared uniform-random Track 1
baseline (100 episodes, seed 12345).

### Evaluation episode census (exact accounting)

Every approved evaluation set was executed in full. The table is generated by
`m7d_analysis.episode_census()` (`episode_census` in the report JSON) from the
per-episode rows on disk - every M7d evaluation ran with `preserve_all`, so a
session's rows are its complete record - and the planned column comes from
`m7d_matrix.evaluation_plan`, so a set that had not been run would appear as a
shortfall rather than disappear. `protocol_complete` is `true` and
`missing_evaluations` is empty: **3,688 of 3,688 planned evaluation episodes
ran.**

| evaluation set | models / checkpoints | mode | episodes per evaluation | evaluations | episodes planned | episodes run | in the decision endpoint | verified clears |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Initial checkpoint `ckpt_000000000` | 6 models x 1 = 6 | stochastic | 100 | 6 | 600 | 600 | no (pairing proof + learning-evidence denominator) | **0** |
| Initial checkpoint `ckpt_000000000` | 6 models x 1 = 6 | deterministic | 100 | 6 | 600 | 600 | no (pairing proof) | **0** |
| Intermediate checkpoints, every 102,400 transitions | 6 models x 9 = 54 | stochastic | 20 | 54 | 1,080 | 1,080 | no (learning curve) | **0** |
| Intermediate checkpoints, every 102,400 transitions | 6 models x 9 = 54 | deterministic | 2 | 54 | 108 | 108 | no (learning curve) | **0** |
| Final model | 6 models x 1 = 6 | stochastic | 100 | 6 | 600 | 600 | **yes - the primary endpoint** | **0** |
| Final model | 6 models x 1 = 6 | deterministic | 100 | 6 | 600 | 600 | no (secondary endpoint) | **0** |
| Random Track-1 baseline (no model) | 1 policy | random | 100 | 1 | 100 | 100 | no (floor + M7a cross-check) | **0** |
| **All evaluation episodes** | 133 sessions | - | - | **133** | **3,688** | **3,688** | - | **0** |
| Training (not an evaluation) | 6 runs | on-policy | - | 6 | - | 2,420 | no | **0** |
| **Every episode M7d played** | - | - | - | - | - | **6,108** | - | **0** |

A clear is counted only when four independently recorded facts agree: the end
reason is `clear`, the `cleared` flag is set, ten targets are broken and a
completion clock (`completion_time_passed`) exists. All four agree in every
category (`witnesses_agree` true throughout): across all 6,108 episodes the
end reasons are only `fall` (958 evaluation + 1,225 training) and `horizon`
(2,730 + 1,195), no row carries a completion clock, and the maximum targets
broken anywhere is 6.

Two accounting corrections to earlier drafts of this document, made here for
the record: the total of the final evaluation sets is **1,200** episodes (600
stochastic + 600 deterministic), not "1,200 final stochastic plus 600
deterministic"; and the complete evaluation total is **3,688**, not 1,800.
The mis-stated figures never entered the analysis - the decision rule reads
only the 600 final stochastic episodes, and that number was always correct -
but the narrative counts were wrong and are now generated rather than typed.

Training episodes: 2,450 started and 2,420 finished across the six runs; the
30-episode difference is the five episodes still in flight in each run when it
reached its 1,024,000-transition budget (they are discarded, never truncated
into a result).

**Random baseline:** 3.23 targets `[3.03, 3.43]`, max 6, 30 falls, 70 horizon
truncations, mean length 3,050.7. It reproduced the M7a cold-lifecycle random
baseline **exactly - 100 of 100 episodes identical** (same action digests,
targets, lengths and end reasons), which re-confirms that the standby
lifecycle changes no trajectory.

### Untrained policies (paired identity)

| seed | mode | compared | identical gameplay | v2 - v1 raw return values |
| --- | --- | --- | --- | --- |
| 0 | deterministic | 100 | 100 | [0.0] |
| 0 | stochastic | 100 | 100 | [-5.0, 0.0] |
| 1 | deterministic | 100 | 100 | [0.0] |
| 1 | stochastic | 100 | 100 | [-5.0, 0.0] |
| 2 | deterministic | 100 | 100 | [0.0] |
| 2 | stochastic | 100 | 100 | [-5.0, 0.0] |

The two runs of a seed evaluate their untrained checkpoints to the same 100
deterministic and 100 stochastic episodes, differing only in the diagnostic
return (`-5.0` exactly on falls). The untrained argmax policy idles to the
horizon with 0 targets at seeds 0 and 1 and 1 target at seed 2; the untrained
stochastic policy scores 3.19-3.30 targets, i.e. random-level.

### Final policy, stochastic (100 episodes per model)

| run | eps | clears (rate) | targets | CI95 | median | max | falls (rate) | fall CI95 | horizon (rate) | idle (rate) | idle tail | 1st target tick | len mean | len range | distinct plays | return (diag.) | lifecycle fail | frozen |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| m7d_s0_v1 | 100 | 0 (0.00) | 4.31 | [4.14, 4.48] | 4.0 | 6 | 58 (0.58) | [0.48, 0.68] | 42 (0.42) | 22 (0.22) | 1383 | 73 | 2830 | 740-3600 | 100 | 1.480 | 0 | yes |
| m7d_s0_v2 | 100 | 0 (0.00) | 3.95 | [3.82, 4.08] | 4.0 | 6 | 0 (0.00) | [0.00, 0.00] | 100 (1.00) | 54 (0.54) | 1745 | 41 | 3600 | 3600-3600 | 100 | 0.350 | 0 | yes |
| m7d_s1_v1 | 100 | 0 (0.00) | 3.51 | [3.37, 3.65] | 3.5 | 5 | 99 (0.99) | [0.97, 1.00] | 1 (0.01) | 0 (0.00) | 620 | 34 | 1554 | 777-3600 | 100 | 1.956 | 0 | yes |
| m7d_s1_v2 | 100 | 0 (0.00) | 4.16 | [4.04, 4.28] | 4.0 | 5 | 0 (0.00) | [0.00, 0.00] | 100 (1.00) | 45 (0.45) | 1654 | 111 | 3600 | 3600-3600 | 100 | 0.560 | 0 | yes |
| m7d_s2_v1 | 100 | 0 (0.00) | 3.27 | [3.13, 3.41] | 3.0 | 5 | 100 (1.00) | [1.00, 1.00] | 0 (0.00) | 0 (0.00) | 324 | 56 | 917 | 481-1831 | 100 | 2.353 | 0 | yes |
| m7d_s2_v2 | 100 | 0 (0.00) | 3.67 | [3.48, 3.85] | 4.0 | 6 | 27 (0.27) | [0.19, 0.36] | 73 (0.73) | 53 (0.53) | 1950 | 49 | 3092 | 402-3600 | 100 | -0.772 | 0 | yes |

| run | targets:episodes | best incomplete | clears (ctp / cit) |
| --- | --- | --- | --- |
| m7d_s0_v1 | 1:1 3:13 4:48 5:29 6:9 | {'targets': 6, 'steps': 2042, 'end_reason': 'fall'} | - |
| m7d_s0_v2 | 3:22 4:63 5:13 6:2 | {'targets': 6, 'steps': 3600, 'end_reason': 'horizon'} | - |
| m7d_s1_v1 | 2:5 3:45 4:44 5:6 | {'targets': 5, 'steps': 1044, 'end_reason': 'fall'} | - |
| m7d_s1_v2 | 2:1 3:9 4:63 5:27 | {'targets': 5, 'steps': 3600, 'end_reason': 'horizon'} | - |
| m7d_s2_v1 | 1:1 2:11 3:50 4:36 5:2 | {'targets': 5, 'steps': 562, 'end_reason': 'fall'} | - |
| m7d_s2_v2 | 0:1 1:3 2:3 3:26 4:56 5:10 6:1 | {'targets': 6, 'steps': 3600, 'end_reason': 'horizon'} | - |

### Final policy, deterministic argmax (100 episodes per model)

All 100 episodes of every model are identical by construction, and the check
held everywhere: **all 66 deterministic sessions produced exactly one
distinct action digest**. This is therefore one behaviour sample plus a
determinism check, not 100 independent samples.

| run | eps | clears (rate) | targets | CI95 | median | max | falls (rate) | fall CI95 | horizon (rate) | idle (rate) | idle tail | 1st target tick | len mean | len range | distinct plays | return (diag.) | lifecycle fail | frozen |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| m7d_s0_v1 | 100 | 0 (0.00) | 2.00 | [2.00, 2.00] | 2.0 | 2 | 100 (1.00) | [1.00, 1.00] | 0 (0.00) | 0 (0.00) | 699 | 2635 | 3361 | 3361-3361 | 1 | -1.361 | 0 | yes |
| m7d_s0_v2 | 100 | 0 (0.00) | 2.00 | [2.00, 2.00] | 2.0 | 2 | 0 (0.00) | [0.00, 0.00] | 100 (1.00) | 100 (1.00) | 3508 | 34 | 3600 | 3600-3600 | 1 | -1.600 | 0 | yes |
| m7d_s1_v1 | 100 | 0 (0.00) | 2.00 | [2.00, 2.00] | 2.0 | 2 | 0 (0.00) | [0.00, 0.00] | 100 (1.00) | 100 (1.00) | 3508 | 34 | 3600 | 3600-3600 | 1 | -1.600 | 0 | yes |
| m7d_s1_v2 | 100 | 0 (0.00) | 3.00 | [3.00, 3.00] | 3.0 | 3 | 0 (0.00) | [0.00, 0.00] | 100 (1.00) | 0 (0.00) | 1647 | 70 | 3600 | 3600-3600 | 1 | -0.600 | 0 | yes |
| m7d_s2_v1 | 100 | 0 (0.00) | 0.00 | [0.00, 0.00] | 0.0 | 0 | 0 (0.00) | [0.00, 0.00] | 100 (1.00) | 100 (1.00) | 3600 | - | 3600 | 3600-3600 | 1 | -3.600 | 0 | yes |
| m7d_s2_v2 | 100 | 0 (0.00) | 1.00 | [1.00, 1.00] | 1.0 | 1 | 0 (0.00) | [0.00, 0.00] | 100 (1.00) | 100 (1.00) | 3549 | 50 | 3600 | 3600-3600 | 1 | -2.600 | 0 | yes |

The argmax policy is weak under both contracts (0-3 targets). Under v2 it
never falls; under v1 it falls at seed 0. It idles for most of the episode in
five of six runs - the M7a observation that the argmax policy collapses while
the sampled policy plays reasonably still holds.

### Learning evidence (the fixed M7a rule)

Learning is claimed only when the final stochastic mean exceeds both the
run's own untrained policy and the random baseline with the 95 % bootstrap CI
of each difference above zero:

| run | final - initial targets | CI95 | final - random | CI95 | learning supported |
| --- | --- | --- | --- | --- | --- |
| m7d_s0_v1 | 1.12 | [0.88, 1.37] | 1.08 | [0.81, 1.35] | True |
| m7d_s0_v2 | 0.76 | [0.54, 0.99] | 0.72 | [0.48, 0.97] | True |
| m7d_s1_v1 | 0.21 | [-0.02, 0.45] | 0.28 | [0.04, 0.53] | False |
| m7d_s1_v2 | 0.86 | [0.63, 1.09] | 0.93 | [0.70, 1.17] | True |
| m7d_s2_v1 | 0.04 | [-0.19, 0.27] | 0.04 | [-0.21, 0.29] | False |
| m7d_s2_v2 | 0.44 | [0.18, 0.69] | 0.44 | [0.17, 0.72] | True |

**All three v2 runs show supported learning; only one of three v1 runs does.**
At seeds 1 and 2 the v1 policy ends statistically indistinguishable from
random on targets while falling in 99-100 % of its episodes.

## Phase E: analysis

### Per-seed paired comparison (final stochastic, v2 - v1)

| seed | targets v1 -> v2 | D_s | CI95 | fall rate v1 -> v2 | F_s | CI95 | clears | I_s | CI95 | horizon diff | Cohen h (falls) | Cohen d (targets) | Cliff delta (targets) | Cliff delta (objective) | targets % | fall rate % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 4.31 -> 3.95 | -0.36 | [-0.57, -0.15] | 0.58 -> 0.00 | -0.58 | [-0.68, -0.48] | 0 -> 0 | +0.32 | [0.19, 0.45] | +0.58 | -1.7315 | -0.4622 | -0.2511 | -0.2511 | -8.35 | -100.0 |
| 1 | 3.51 -> 4.16 | +0.65 | [0.47, 0.83] | 0.99 -> 0.00 | -0.99 | [-1.00, -0.97] | 0 -> 0 | +0.45 | [0.36, 0.55] | +0.99 | -2.9413 | 0.9954 | 0.481 | 0.481 | 18.52 | -100.0 |
| 2 | 3.27 -> 3.67 | +0.40 | [0.17, 0.63] | 1.00 -> 0.27 | -0.73 | [-0.81, -0.64] | 0 -> 0 | +0.53 | [0.43, 0.63] | +0.73 | -2.0488 | 0.483 | 0.3106 | 0.3106 | 12.23 | -73.0 |

### Aggregate

| statistic (v2 - v1) | estimate | seed-stratified CI95 | seed-cluster CI95 |
| --- | --- | --- | --- |
| D (targets) | +0.230 | [0.110, 0.350] | [-0.330, 0.660] |
| F (fall rate) | -0.767 | [-0.810, -0.720] | [-0.990, -0.583] |
| I (idle rate) | +0.433 | [0.370, 0.497] | [0.310, 0.540] |
| horizon rate | +0.767 | [0.723, 0.810] | - |
| C (clears) | 0 | - | - |

pooled: {'targets_mean': {'v1': 3.6967, 'v2': 3.9267}, 'fall_rate': {'v1': 0.8567, 'v2': 0.09}, 'cohen_h_fall': -1.7557, 'cohen_d_targets': 0.2772, 'cliffs_delta_targets': 0.1831}
sign consistency: {'targets_up': 2, 'falls_down': 3, 'seeds': 3}
decision: {"classification": "v2 preferred", "conditions": {"v1_fewer_clears_aggregate": false, "v1_significantly_fewer_targets": false, "v1_targets_for_survival": false, "v2_more_clears": false, "v2_more_targets": true, "v2_fewer_falls_non_inferior": false}, "counts": {"seeds_with_significant_target_gain": 2, "seeds_with_significant_fall_reduction": 3}, "rule_id": "m7d_decision_rule_v1", "margin_targets": 0.5}

### The seven questions

1. **Does v2 reduce the fall rate?** Yes, decisively and consistently:
   0.58 -> 0.00, 0.99 -> 0.00, 1.00 -> 0.27; aggregate `-0.767`, CI
   `[-0.810, -0.720]`, significant in 3 of 3 seeds, Cohen's h -1.73 to -2.94
   (pooled -1.76). This is the effect v2 was designed to produce.
2. **Does v2 retain or improve target collection?** On average yes, but not
   uniformly: `+0.65` and `+0.40` targets at seeds 1 and 2, `-0.36` at seed
   0 (each individually significant). Aggregate `+0.230`, stratified CI
   `[0.110, 0.350]`; the seed-cluster CI `[-0.330, 0.660]` includes zero.
3. **Does v2 produce more verified clears?** No: **zero clears under either
   contract, in every episode either one ever played** - 0 of 2,420 training
   episodes and 0 of 3,688 evaluation episodes (600 final stochastic, 600
   final deterministic, 600 + 600 at the untrained checkpoints, 1,080 + 108
   on the learning curve, 100 random baseline; see the census). The best
   episode anywhere broke 6 of 10 targets. On the objective ranking both
   contracts remain in the incomplete class.
4. **Does deterministic performance improve?** Slightly and inconsistently:
   2 vs 2 targets (seed 0), 2 vs 3 (seed 1), 0 vs 1 (seed 2); v2's argmax
   policy never falls, v1's falls at seed 0. Both remain far below their own
   sampled policies.
5. **Does v2 become excessively conservative or idle?** It becomes markedly
   more idle by the pre-registered definition (`I = +0.433`, CI
   `[0.370, 0.497]`): 45-54 % of v2's final episodes spend at least half the
   horizon after their last target break, against 0-22 % under v1. Per 1,000
   ticks alive v2 collects 1.10-1.30 targets against v1's 1.72-3.79. But its
   *per-episode* target count is not lower (higher in 2 of 3 seeds), so this
   is conservatism without a target cost, not the "idles instead of playing"
   failure mode. Part of the idle-rate gap is mechanical: a v1 episode that
   ends in a fall after 900-2,800 ticks cannot accumulate an idle tail.
6. **Is the effect consistent across paired seeds?** The fall reduction is
   (3/3). The target effect is not (2 of 3 positive, seed 0 negative), which
   is why the seed-cluster interval spans zero.
7. **Could the apparent improvement come from lifecycle, throughput, episode
   counts or evaluation differences?** No. Both arms ran the identical
   lifecycle (N=5 standby, 0 cold fallbacks anywhere), the identical
   evaluation protocol with the same seed and episode counts (100 + 100 per
   model at both the untrained and the final checkpoint, 20 + 2 at each of
   the nine intermediate checkpoints; all 132 model evaluation sessions
   frozen and verified), and identical episode counts per evaluation - the
   census shows the two arms matching set for set. Throughput differed (v1 1,063.5 vs v2 1,168.6 mean
   transitions/s) only because v1 fell more and therefore restarted more
   often - a consequence of the learned behaviour, not a cause: gameplay is
   deterministic given the seed and independent of wall-clock timing.

### Decision (pre-registered rule `m7d_decision_rule_v1`)

`v1 retained` conditions - all false:

| condition | value | met |
| --- | --- | --- |
| `v1_fewer_clears_aggregate` (`C < 0`) | `C = 0`, no clears either way | no |
| `v1_significantly_fewer_targets` (`CI(D)` upper `< 0`) | upper `+0.350` | no |
| `v1_targets_for_survival` (`D < -0.5` with a significant fall reduction) | `D = +0.230` | no |

`v2 preferred` conditions - exactly one true:

| condition | value | met |
| --- | --- | --- |
| `v2_more_clears` | no clears anywhere (0 of 6,108 episodes) | no |
| **`v2_more_targets`** (`CI(D)` lower `> 0` **and** significant in >= 2 of 3 seeds) | lower `+0.110`; significant in 2 of 3 seeds (seeds 1 and 2; seed 0 is significantly negative) | **YES** |
| `v2_fewer_falls_non_inferior` (non-inferior targets **and** `CI(F)` upper `< 0` in >= 2 seeds **and** `CI(I)` lower `<= 0`) | targets non-inferior (yes), falls significant in 3 of 3 (yes), **idle `CI(I)` lower `+0.370 > 0` (no)** | **no** |

**Classification: v2 preferred, and it qualifies through the target path
`v2_more_targets` only** - "significantly more targets per episode, in at
least two of three seeds".

**v2 does not qualify through the fall-reduction path.** That path requires
no significant increase in idle episodes, and the no-idling condition failed:
the idle rate rose by `+0.433` with a 95 % CI of `[0.370, 0.497]`, entirely
above zero. The fall reduction (`-0.767`, 3 of 3 seeds) is large, consistent
and reported as a secondary effect, but under the rule as registered it did
**not** contribute to the classification. Had the target path also failed,
the registered verdict would have been `inconclusive - more evidence
required`, not `v2 preferred`.

### Learning curves by transitions

Stochastic evaluation of each saved checkpoint (mean targets / fall rate),
never wall-clock:

| checkpoint | s0_v1 | s0_v2 | s1_v1 | s1_v2 | s2_v1 | s2_v2 |
| --- | --- | --- | --- | --- | --- | --- |
| initial | 3.19 / 0.32 | 3.19 / 0.32 | 3.30 / 0.27 | 3.30 / 0.27 | 3.23 / 0.25 | 3.23 / 0.25 |
| curve_t000102400 | 3.40 / 0.10 | 3.15 / 0.25 | 3.55 / 0.05 | 3.10 / 0.05 | 3.35 / 0.25 | 3.15 / 0.25 |
| curve_t000204800 | 3.70 / 0.25 | 3.55 / 0.00 | 3.30 / 0.40 | 3.85 / 0.00 | 3.55 / 0.35 | 3.45 / 0.10 |
| curve_t000307200 | 3.90 / 0.05 | 3.55 / 0.00 | 2.90 / 0.90 | 3.25 / 0.00 | 3.90 / 0.85 | 3.40 / 0.10 |
| curve_t000409600 | 3.90 / 0.10 | 3.00 / 0.05 | 3.25 / 0.95 | 3.50 / 0.05 | 3.85 / 0.95 | 3.50 / 0.40 |
| curve_t000512000 | 3.75 / 0.05 | 3.60 / 0.00 | 3.35 / 1.00 | 4.05 / 0.00 | 3.30 / 1.00 | 3.60 / 0.00 |
| curve_t000614400 | 3.70 / 0.35 | 3.70 / 0.10 | 3.55 / 0.95 | 3.90 / 0.05 | 3.35 / 1.00 | 3.45 / 0.10 |
| curve_t000716800 | 3.90 / 0.25 | 4.05 / 0.05 | 3.60 / 0.95 | 4.15 / 0.00 | 3.25 / 1.00 | 2.90 / 0.30 |
| curve_t000819200 | 3.95 / 0.15 | 3.40 / 0.05 | 3.45 / 1.00 | 4.05 / 0.00 | 3.50 / 1.00 | 3.85 / 0.00 |
| curve_t000921600 | 4.10 / 0.50 | 3.90 / 0.00 | 2.95 / 1.00 | 4.45 / 0.00 | 3.20 / 1.00 | 3.65 / 0.10 |
| final | 4.31 / 0.58 | 3.95 / 0.00 | 3.51 / 0.99 | 4.16 / 0.00 | 3.27 / 1.00 | 3.67 / 0.27 |

Deterministic argmax at the same checkpoints (targets and end: H horizon,
F fall):

| checkpoint | s0_v1 | s0_v2 | s1_v1 | s1_v2 | s2_v1 | s2_v2 |
| --- | --- | --- | --- | --- | --- | --- |
| initial | 0 H | 0 H | 0 H | 0 H | 1 H | 1 H |
| curve_t000102400 | 3 H | 2 H | 0 H | 1 H | 2 H | 0 H |
| curve_t000204800 | 0 H | 0 H | 0 H | 0 H | 1 H | 2 H |
| curve_t000307200 | 0 H | 3 H | 0 H | 2 H | 3 H | 0 H |
| curve_t000409600 | 2 H | 1 H | 2 H | 1 H | 2 H | 2 H |
| curve_t000512000 | 3 H | 1 H | 2 H | 1 H | 1 H | 1 F |
| curve_t000614400 | 1 H | 2 H | 1 H | 1 H | 1 H | 3 H |
| curve_t000716800 | 1 H | 2 H | 2 H | 0 H | 1 H | 0 H |
| curve_t000819200 | 3 H | 1 H | 2 F | 1 H | 2 F | 1 H |
| curve_t000921600 | 3 H | 2 H | 2 H | 3 H | 1 H | 2 F |
| final | 2 F | 2 H | 2 H | 3 H | 0 H | 1 H |

Training-side windows of 102,400 transitions (mean targets / fall rate),
independent of the evaluation protocol:

```text
m7d_s0_v1: 102k 3.50/0.12, 204k 3.33/0.07, 307k 3.67/0.00, 409k 3.67/0.00, 512k 3.67/0.20, 614k 3.93/0.13, 716k 3.93/0.13, 819k 3.92/0.31, 921k 4.00/0.38, 1024k 3.94/0.38
m7d_s0_v2: 102k 3.35/0.18, 204k 3.41/0.18, 307k 3.23/0.00, 409k 3.53/0.00, 512k 3.53/0.00, 614k 3.47/0.27, 716k 4.07/0.00, 819k 3.67/0.00, 921k 3.33/0.00, 1024k 3.92/0.00
m7d_s1_v1: 102k 3.62/0.19, 204k 3.40/0.13, 307k 3.48/0.74, 409k 3.14/0.93, 512k 3.42/1.00, 614k 3.32/0.82, 716k 3.28/1.00, 819k 3.03/0.97, 921k 2.95/1.00, 1024k 3.25/1.00
m7d_s1_v2: 102k 3.07/0.07, 204k 3.40/0.00, 307k 3.47/0.00, 409k 3.27/0.00, 512k 3.80/0.00, 614k 4.13/0.00, 716k 4.23/0.00, 819k 4.13/0.00, 921k 4.07/0.00, 1024k 4.09/0.00
m7d_s2_v1: 102k 3.29/0.00, 204k 3.88/0.19, 307k 3.75/0.56, 409k 3.58/0.96, 512k 3.36/1.00, 614k 3.33/1.00, 716k 3.28/1.00, 819k 3.33/1.00, 921k 3.31/0.98, 1024k 3.36/1.00
m7d_s2_v2: 102k 3.00/0.24, 204k 3.59/0.18, 307k 3.36/0.00, 409k 3.43/0.07, 512k 3.80/0.07, 614k 3.60/0.00, 716k 3.29/0.24, 819k 3.53/0.07, 921k 3.50/0.12, 1024k 3.87/0.33
```

The v1 fall rate climbs to 0.9-1.0 at seeds 1 and 2 within the first third of
training and never recovers, while its target count stagnates; v2 holds its
fall rate near zero throughout and keeps improving slowly. Seed 0 is the
exception: its v1 run kept falls moderate (0.38 by the end) and reached the
highest target count of any run.

### Idle and conservativeness detail (final stochastic)

| run | targets per 1000 ticks | idle episodes (rate) | idle tail mean | 1st target tick (median) | zero-target episodes | length mean | length p10-p90 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| m7d_s0_v1 | 1.7166 | 22 (0.22) | 1383 | 73.0 | 0 | 2830 | 1461-3600 |
| m7d_s0_v2 | 1.0972 | 54 (0.54) | 1745 | 41.0 | 0 | 3600 | 3600-3600 |
| m7d_s1_v1 | 2.4853 | 0 (0.00) | 620 | 34.0 | 0 | 1554 | 925-2287 |
| m7d_s1_v2 | 1.1556 | 45 (0.45) | 1654 | 111.0 | 0 | 3600 | 3600-3600 |
| m7d_s2_v1 | 3.7918 | 0 (0.00) | 324 | 56.0 | 0 | 917 | 639-1221 |
| m7d_s2_v2 | 1.2969 | 53 (0.53) | 1950 | 49 | 1 | 3092 | 1379-3600 |

### Objective-rank comparison

Cliff's delta over objective keys (verified clear, then targets, then
completion time): `-0.251` (seed 0), `+0.481` (seed 1), `+0.311` (seed 2).
The best episode of each contract is 6 targets at seed 0 (both), 5 at seed 1
(both) and 5 (v1) versus 6 (v2) at seed 2. No clear exists on either side, so
no completion clock can be compared.

### Diagnostic reward comparison (not evidence)

**v1 and v2 returns are not comparable**: a v2 fall carries an extra `-5.0`,
and the `-0.001` per-tick cost punishes exactly the long episodes that not
falling produces.

| run | final stochastic return (own contract) | same episodes scored as v1 | falls |
| --- | --- | --- | --- |
| m7d_s0_v1 | 1.4799 | 1.4799 | 58 |
| m7d_s0_v2 | 0.35 | 0.35 | 0 |
| m7d_s1_v2 | 0.56 | 0.56 | 0 |
| m7d_s1_v1 | 1.956 | 1.956 | 99 |
| m7d_s2_v1 | 2.3528 | 2.3528 | 100 |
| m7d_s2_v2 | -0.7725 | 0.5775 | 27 |

The v1 runs post the higher numbers (1.48, 1.96, 2.35) while breaking fewer
targets in two of three seeds; re-scoring v2's episodes under v1's constants
(third column) leaves them lower still, because v2 survives to 3,600 ticks
and pays `-3.6` in step cost where a v1 episode that dies at tick 917 pays
`-0.917`. Under `btt_reward_v1` dying early is worth about 1.5 reward points,
which is the incentive `btt_reward_v2` removes. This is exactly why the
decision uses gameplay only.

## Phase F: verification

### Native replay of preserved artifacts

The best preserved artifact of every run (by objective ranking over all
training and evaluation artifacts) was replayed through interactive native
stepping on a fresh process (raw M1d client, one action per native tick):

| run | artifact | role | end | targets (label) | actions sent | last tick | final state | targets (replay) | final obs equal | host_frame equal | break ticks = summary | ok |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| m7d_s0_v1 | episode_20260922T181114Z_ff91f858 | evaluation | horizon | 6 | 3600 | 3599 | WaitingForAction | 6 | True | True | True | True |
| m7d_s0_v2 | episode_20260922T183354Z_8266619a | evaluation | horizon | 6 | 3600 | 3599 | WaitingForAction | 6 | True | True | True | True |
| m7d_s1_v1 | episode_20260922T170812Z_760c4a00 | training | horizon | 6 | 3600 | 3599 | WaitingForAction | 6 | True | True | None | True |
| m7d_s1_v2 | episode_20260922T190643Z_2872d97a | evaluation | horizon | 6 | 3600 | 3599 | WaitingForAction | 6 | True | True | True | True |
| m7d_s2_v1 | episode_20260922T172620Z_8c69ac64 | training | fall | 6 | 3354 | 3353 | WaitingForAction | 6 | True | True | None | True |
| m7d_s2_v2 | episode_20260922T203009Z_5d22867e | evaluation | horizon | 6 | 3600 | 3599 | WaitingForAction | 6 | True | True | True | True |

Every replay reproduced the recorded run exactly: fresh process
(`WaitingForAction`, `step_count 0`), the initial observation equal, every
submitted action's `consumed_tick` equal to the recorded one, the targets
equal, the terminal state as labelled, the full final observation equal
(`host_frame` included) and the target-break ticks equal to the episode
summary. **No clear exists in M7d**, so no clear needed native re-validation;
the clear path itself is exercised by the authoritative replay below.

### Regression chain

Sequential, one suite at a time, zero `BattleShip.exe` required before and
after each, with the user configuration fingerprinted around every suite
(`runs/_m7d_regressions/results.json`):

| suite | exit | wall (s) | processes left | note |
| --- | --- | --- | --- | --- |
| `rl/m7d_tests.py unit` | 1 -> **0 on re-run** | 35.7 / 32.4 | 0 | 7/8 in the chain: `unit_directory_guards` asserted that the M7d directories do not exist yet, which stopped being true once the matrix had run. The case now asserts the guard's behaviour in both states (absent before the matrix, refused afterwards); re-run **8/8 PASS** |
| `rl/m7c_standby_tests.py` (4 unit + 17 game) | 1 -> **0 on re-run of the case** | 347.6 / 41.2 | 0 | 20/21 in the chain; `cold_vs_standby_replay` failed its cleanup assertion (the runtime directory of the generation cancelled at close was still present, together with its episode directory). Re-running the case alone **PASSED** with 11 generation directories and the cancelled one removed, so the deletion is timing-dependent on Windows (a transient lock on freshly written files, the same class this repository already retries around in `replace_with_retry`), not an M7d regression: all six M7d training runs recorded **0** episode-directory delete errors |
| `rl/m7b_config_tests.py` | 0 | 12.4 | 0 | 16/16 |
| `rl/m7b_smoke.py` | 0 | 197.9 | 0 | 7/7 |
| `rl/m7_smoke.py` | 0 | 232.3 | 0 | 20/20 |
| `rl/m6_equivalence_regression.py` | 0 | 35.7 | 0 | normal vs no-render vs no-render + bypass identical |
| `rl/m6_raphnet_bypass_regression.py` | 0 | 129.2 | 0 | 8/8 |
| `rl/m5_smoke.py --child-env SSB64_RL_NO_RENDER=1 --child-env SSB64_RAPHNET_DISABLE=1` | 0 | 40.0 | 0 | 8/8 |
| `rl/m5_smoke.py` | 0 | 95.9 | 0 | 8/8 |
| `rl/m4_smoke.py` | 0 | 69.5 | 0 | 5/5 |
| `rl/m3_gym_smoke.py` | 0 | 107.2 | 0 | 9/9 |
| `rl/m2_restart_regression.py` | 0 | 57.5 | 0 | 3/3 episodes, 447 actions, 446/447 |
| `rl/m2_lifecycle_smoke.py` | 0 | 24.4 | 0 | 6/6 |
| `rl/m1e_replay_regression.py --port 52101` (hand-launched process, cwd `build-us/Release`) | 0 | - | 0 | game exit 0; result JSON clear, 10 targets, `completion_time_passed` 446, `completion_input_tick` 447, host_frames 511 |
| native replay (`SSB64_BTT_INPUT`, `SSB64_MAX_FRAMES=1500`, cwd `build-us/Release`) | 0 | - | 0 | `SSB64 BTT Replay: COMPLETE input_tick=447 time_passed=446`; `input exhausted frames=468 actual_checksum=0x93E9EFB4`; result clear 10 / 446 / 447 |
| `git diff --check` | 0 | - | - | clean |

The authoritative native replay is therefore revalidated exactly: **468
source rows, checksum `0x93E9EFB4`, `completion_time_passed = 446`,
`completion_input_tick = 447`** - the two clocks reported separately, neither
collapsed nor decremented. The user's `BattleShip.cfg.json` sha256 was
identical at the start and the end of the whole chain; its mtime changes
inside the M1-M6 suites, the hand-launched M1e process and the native replay,
which run in `build-us/Release` by design and rewrite the file with identical
bytes (the M7c chain records the same behaviour). No M7d worker ever opens
that file.

### Cleanup and integrity

Measured after training, evaluation, replay and the regression chain:

| check | result |
| --- | --- |
| `BattleShip.exe` processes | **0** (and at most 10 at any monitored sample during every run and evaluation; 0 exited-but-unreleased entries) |
| listening sockets in the M7 port blocks (30000-31249) | **none** |
| leaked Python processes | none (only the integrity checker itself) |
| launcher threads | started == joined in every run (301, 296, 289, 567, 686, 311), none alive at close |
| `SSB64_*` variables in the orchestrator environment | none |
| user configuration | sha256 `1b29d91b80051a13...` **unchanged** (byte-identical to Phase A); mtime changed only through the M1-M6 / M1e / native-replay suites that run in `build-us/Release` by design |
| historical results (M7a-M7c and all earlier trees) | **untouched**: of the 6,500 files fingerprinted before any M7d work, 0 changed, 0 moved (mtime), 0 removed; per-directory zero for `m7a_pilot_n5`, `m7a_compare`, `m7a_random_baseline`, `m7c_stage1`, `m7c_stage1b`, `m7c_stage2`, `_m7c_v2_n5`, `_m7c_v2_n5b`, `_m7c_regressions`, `_m7b_smoke_final`, `_m7_smoke_final1`, `m0`, `m1a`. Additions are only the new `runs/m7d/`, `runs/_m7d_preflight_*` and `runs/_m7d_regressions*` trees |
| native and submodule state | HEAD `0bd6f2d3...` unchanged; decomp `91d7b6b7`, libultraship `805f1950`, torch `3aa9c973` unchanged and clean; no native, decomp or submodule file touched |
| `git diff --check` | exit 0 |
| storage | `runs/m7d` 1.24 GiB; 149.6 GiB free |

## Limitations

- Three seeds. The aggregate intervals are seed-stratified (conditional on
  these three seeds); the seed-cluster interval beside them is honest but
  crude with three clusters. The target effect's direction is **not**
  established beyond these seeds; the fall effect is large and consistent
  enough that it plausibly generalises, but three seeds cannot prove it.
- One task, one horizon, one process count, one PPO configuration, 1,024,000
  transitions. Nothing here says how either contract behaves with a longer
  budget or a different setup.
- Neither contract clears the stage - 0 verified clears in all 6,108
  episodes (2,420 training, 3,688 evaluation) - so the primary objective is
  untested by this comparison and the ranking fell back to targets.
- Seed 0 favoured v1 on targets (`-0.36`, individually significant), so the
  qualifying target effect holds in 2 of 3 seeds, not 3 of 3.
- v2 qualified through one path only (`v2_more_targets`). The fall path was
  blocked by its no-idling condition, so the fall reduction - the effect v2
  was designed to produce - carries no weight in the classification.
- The idle metric is confounded with survival: an episode that ends in a fall
  cannot accumulate an idle tail, so v2's higher idle rate is partly
  mechanical.
- The deterministic sessions are 100 identical episodes per model.
- The M7a pilot is historical context only, not a fourth v1 sample (different
  effective RNG stream and lifecycle).
- Throughput and lifecycle figures depend on the policy and on background
  load; they are diagnostics, never evidence about a reward contract.
- Windows only, one machine, one executable build (`57d61fe0...`).

## Recommendation

**`btt_reward_v2` is provisionally selected** as the reward contract for the
next training milestone. "Provisionally" is the accurate word: the contract
won the pre-registered comparison on a secondary criterion, through a single
qualifying path, on three seeds, in an experiment where neither contract ever
reached the primary objective. It is the better of the two on the evidence
available, not an established result.

Why it is selected:

- it qualifies under the registered rule through the target path
  (`v2_more_targets`: `+0.230` targets, CI `[0.110, 0.350]`, significant in 2
  of 3 seeds) - and through that path only;
- it is the only contract whose runs all show supported learning (3/3 against
  both the untrained policy and the random baseline; v1: 1/3);
- it removes the dominant failure mode (falls: 58-100 episodes per 100 under
  v1, 0-27 under v2) that ends v1's episodes before they can progress - a
  large secondary effect that did not, by itself, satisfy its path.

Limitations that travel with the selection and must be restated wherever it
is relied on:

1. **No clears under either reward.** 0 verified clears in all 6,108 M7d
   episodes; the primary objective of the ranking is untested and the
   decision fell back to targets.
2. **Seed 0 favoured v1 on targets** (`-0.36`, individually significant). The
   target effect is not uniform across seeds.
3. **The seed-cluster target interval includes zero** (`[-0.330, 0.660]`):
   the direction of the target effect is not established beyond these three
   seeds.
4. **v2 substantially increases idle and horizon behaviour**
   (`I = +0.433`, CI `[0.370, 0.497]`; 45-54 % of its final episodes idle for
   at least half the horizon, against 0-22 % under v1; 73-100 % of its
   episodes reach the horizon). This is the condition that disqualified the
   fall path, and it is a real behavioural cost, not a reporting artefact.

If the next run ends without a clear again, the idle tail - not the fall rate
- is the behaviour to attack (exploration, shaping toward the remaining
targets, or a horizon that stops paying for survival), and any such change
belongs in a new contract identity, never in an edit to v1 or v2. If a longer
run under v2 still produces no clear and the idle tail grows, revisiting this
selection is the expected outcome, not a reversal of a settled decision.

## Commands

```text
python rl/m7d_run.py manifest                       # resolved comparison manifest (before training)
python rl/m7d_tests.py                              # 9 unit + 4 game-backed preflight cases
python rl/m7d_tests.py unit_episode_census          # the evaluation accounting on its own
python rl/m7d_run.py train                          # the six runs, sequential, counterbalanced, monitored
python rl/m7d_run.py train --resume <run>           # continue one run's own lineage (never used in M7d)
python rl/m7d_run.py evaluate                       # random baseline + 11 evaluation sets per run
python rl/m7d_run.py replay                         # native replay of the best preserved artifact per run
python rl/m7d_run.py status
python rl/m7d_analysis.py --out docs/rl_reward_comparison_m7d.json
```

## Working-tree status (nothing committed, pushed, branched or merged)

`git status --short` at the end of M7d:

```text
 M rl/btt_parallel.py
 M rl/m7_evaluation.py
?? docs/rl_reward_comparison_m7d.json
?? docs/rl_reward_comparison_m7d.md
?? docs/rl_reward_comparison_m7d_manifest.json
?? rl/configs/m7d/
?? rl/m7d_analysis.py
?? rl/m7d_matrix.py
?? rl/m7d_run.py
?? rl/m7d_tests.py
```

`git diff --stat`: `rl/btt_parallel.py` 8 lines (+6/-2), `rl/m7_evaluation.py`
30 lines (+23/-7); `git diff --check` exit 0. `rl/configs/m7d/` holds the six
profiles. HEAD is still `0bd6f2d3...` and no submodule pointer moved.
Generated output (`runs/m7d/`, 1.24 GiB; `runs/_m7d_preflight_*`;
`runs/_m7d_regressions*`) stays git-ignored under `runs/`.
