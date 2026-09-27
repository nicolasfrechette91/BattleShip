# RL M7n: `btt_policy_obs_v3_entities` and `btt_entity_v1` — implementation and bounded validation

Status (2026-09-26, third pass): **implemented; bounded no-training validation done; capped integration pilot PASSED (8 / 8, third attempt, section 4); campaign driver and rule implemented (section 8); the user reviewed the rule and AUTHORISED the bounded campaign after three narrow corrections (section 9): rule v2 (`m7n_decision_rule_v2`) with the replay-verified gate-2 criterion `btt_qualified_crossing_v1`, the corrected gate-1 explanation and null-safe T / D / G; the manifest re-frozen with the approval record; the control reproduction repeated on the final fingerprint (R1–R4); the campaign RAN to completion 2026-09-27 and decided gate 3 better_targets → success, v3 selected (section 10).** Nothing was committed, pushed or branched. No native RNG state was inspected. Design and review resolutions: [`rl_observation_v3_proposal_m7n.md`](rl_observation_v3_proposal_m7n.md) (sections 3 and 7). Decision rule: [`rl_observation_v3_m7n_decision_rule_v2.json`](rl_observation_v3_m7n_decision_rule_v2.json) (the superseded v1 stays byte-identical at [`rl_observation_v3_m7n_decision_rule.json`](rl_observation_v3_m7n_decision_rule.json)). Machine-readable contract: [`rl_observation_v3_m7n.schema.json`](rl_observation_v3_m7n.schema.json).

Identity at the end of this step:

| item | value |
| --- | --- |
| parent HEAD | `1373710` (clean before this step; every change below is uncommitted) |
| submodules | `decomp 3c7fd5d0` (rl-main; one PORT-only working-tree edit, see section 1), `libultraship 805f1950`, `torch 3aa9c97` unchanged |
| executable before / after | `1e7c62a0…` (preserved runnable at `runs/m7n/_exe/pre_m7n/`) / `748dbad9…` |
| v3 contract digest | `4ddc2933a41410ecf2009b464a706fc0e6e6de4fbad300608d04bd1d1f7b3297` (flat size 606) |
| action-class table | `btt_action_class_table_v1`, sha256 `97db115242c58c2a18b70c03adcdf4f2556728e501fe87858f9f7b1c83229ea4` |

## 1. What was built

### 1.1 Native: opt-in, read-only diagnostic `btt_entity_v1` (`SSB64_RL_ENTITY=1`)

Same pattern as M7f / M7g, and nothing else changed in the game:
- `port/rl/rl.h`: `RLEntityDiag` (fighter extras: `status_total_tics`, `hitlag_tics`, `jumps_max`, attack-active /
  cliff-hold / shield / fast-fall / hitstun bits; up to 8 weapons with `serial, kind, owned, lr, ga, lifetime,
  attack_state, translate, velocity`), anomaly bits, declarations.
- `decomp/src/sc/sc1pmode/sc1pbonusstage.c` (inside the existing `#ifdef PORT` block): `rlGameFillEntity()` walks
  `gGCCommonLinks[nGCCommonLinkIDWeapon]`, reads typed `WPStruct` / `DObj` / `FTStruct` fields, assigns a PORT-only
  per-process spawn serial per weapon (matched by GObj handle + kind + non-increasing lifetime, so a pooled GObj reused
  by a new weapon gets a new serial) and writes only `*out` and its own table. One PORT-only `#include <wp/weapon.h>`.
- `port/rl/rl_entity.{h,cpp}`: JSON rendering. `rl_boot.cpp`: the flag (requires effective stepping, like the spatial
  one). `rl_observation.cpp`: captured in the same `GamePostUpdateEvent` callback and handed over under the same lock
  as the observation (the M7g / M7f / M1b branches are unchanged when the flag is off). `rl_step.cpp`: latched exactly
  like the M7f / M7g snapshots (`rlStepOnObservationDiag2`, `rlStepGetLatestObservationEntity`, `rlStepGetLastEntity`).
  `rl_transport.cpp`: `"entity_diag": true` in status, `"entity"` in observe / step replies, additive.

Semantics measured on the game (section 3): `status_total_tics` is 0 on the first update of every status change,
including re-entry of the same status, and advances by exactly 1 per update otherwise; weapon lifetimes only
decrement; serials are unique and persistent; Mario reaches at most 4 simultaneous fireballs in random play.

### 1.2 Python: contract, builder, wrapper, stack, hooks

| file | role |
| --- | --- |
| `rl/m7n_entity.py` | strict parser of `btt_entity_v1`, typed snapshot, invariants (`check_snapshot`) |
| `rl/m7n_status_table.py`, `rl/data/m7n_action_classes_v1.json` | the action-class table derived from `ftdef.h` and the 12 `ft<char>.h` enums; 20 classes with the explicit `unmapped` fallback; `ActionClassifier(table, character)` |
| `rl/m7n_obs.py` | `btt_policy_obs_v3_entities`: builder, `EntityObsV3Wrapper` (above `Track1PolicyWrapper`, one extra non-consuming observe per reset), v3 worker stack `build_worker_env_v3` / `M7nWorkerFactory`, contracts, schema |
| `rl/m7n_policy.py` | network identity `btt_policy_net_v3_multiinput_mlp64`, `VecNormalize(norm_obs=False)`, checkpoint refusal |
| `rl/experiment_config.py`, `rl/m7_trainer.py`, `rl/m7_evaluation.py`, `rl/m7d_run.py` | route-A opt-in hooks (v1 / v2 branches untouched; v3 requires `normalize_observations = false`; statistics-free VecNormalize handled by the digest / record / identity / verifier helpers) |
| `rl/configs/m7n/pilot/m7n_pilot_s0.toml`, `rl/configs/m7n/m7n_s{0,1,2}_v3.toml` | the pilot (cap 40,960) and the three prepared campaign profiles (not launched) |
| `rl/m7n_tests.py`, `rl/m7n_equivalence.py`, `rl/m7n_control_check.py`, `rl/m7n_pilot.py` | tests, native equivalence, the R1–R3 control reproduction, the registered pilot |
| `rl/m7g_k_tests.py` | one line: `m7n` added to the later-milestone profile exclusion (as M7l / M7m did) |

### 1.3 The final contract (Dict, sorted key order = SB3 concatenation order; flat 606)

| key | shape | content | scale | mask column |
| --- | --- | --- | --- | --- |
| `action_class` | (20,) | one-hot class of the status id: idle_ground, dash_run, jump_squat, airborne, landing, crouch_pass, shield, roll, damage, cliff, attack_ground, attack_air, special_n, special_hi, special_lw, item, appear_entry, dead, other, **unmapped** | 0 / 1 | — |
| `agent` | (28,) | pos_x, pos_y, disp_x, disp_y, air_vel_x, air_vel_y, ground_vel_x, carry_x, carry_y, facing, grounded, contact floor / ceil / lwall / rwall, floor_dist (signed native convention, negative = floor below), jumps_left, status_id / 256, status_tics, hitlag, attack_active, cliff_hold, shield_active, fastfall, time, targets_left, diamond_top, diamond_width | lengths / 2,000; velocities and displacement / 50; progress and hitlag / 60 (caps 240 / 60); time / 3,600 | — |
| `projectiles` | (4, 7) | own weapons, sticky slots in spawn-serial order: present, dx, dy, vx, vy (native `vel_air`), hitbox_active, life (/140, clipped) | as above | 0 |
| `segment_geometry` | (32, 8) | v2 rows: endpoints, closest point, velocity, agent-relative | / 2,000; velocity / 50 | — |
| `segment_kind` | (32, 7) | v2 binary columns: present, floor, ceiling, wall +x, wall −x, one-way, moving | 0 / 1 | 0 |
| `targets` | (10, 5) | stable M7f ID: dx, dy, vx, vy (reply-to-reply), live | / 2,000; / 50 | 4 |

Rules: no running normalisation; a masked row is exactly zero at the network input; stale rule = native `live = 0`
or fighter invalid (the terminal reply of a fall) repeats the last observation with `info["v3_stale"]`; displacement
and target velocities are 0 at reset, on a row's first live reply and on a stale reply; the character enters only
through `jumps_max`, the diamond, its own action-class table and its projectile kinds. Nothing names a location,
tick, period, order or route.

**Remaining cross-character limitations.** Only Mario's action-class mapping is validated against replayed traces;
the other 11 tables are derived by the same name rule but unreviewed (`validated: false`; Donkey Kong's cargo-throw
states and the stage-hazard states fall in `other`). A new character must be onboarded through the M10 gate
(boot, baseline, its traces through `unit_offline_traces`-style checks, `jumps_max`, diamond, projectile kinds,
anomaly threshold). Fixed scaling gives feature meanings a common definition; it establishes nothing about
checkpoint transfer, which is not claimed. The stage contract accepts ≤ 32 collision segments and 10 targets (every
Break the Targets stage has 10); a stage with more segments needs a new version.

## 2. Native invariance (established validation fixtures)

Capture sets with the new executable (`rl/m7n_equivalence.py capture`): the TAS in three host modes, the eight pinned
historical Track 1 artifacts (3,361–3,600 actions; falls, horizons, double breaks, a collapse, random play), and the
native 468-row replay; 12 traces per set; five sets.

| comparison | result |
| --- | --- |
| flags unset vs M7g `post_off` (executable `1e7c62a0`), **strict** (every key, JSON type, status, result, `host_frame`) | **12/12 identical** |
| `SSB64_RL_SPATIAL=1 + SSB64_RL_TARGET_DIAG=1` vs M7g `post_spatial_diag`, **strict** | **12/12 identical** (the M7f / M7g objects unchanged) |
| `SSB64_RL_ENTITY=1` alone vs `post_off`, ignoring only the additive `entity` object and status key | **12/12 identical** |
| all three diagnostics vs `post_spatial_diag`, ignoring only `entity` | **12/12 identical** |
| all three diagnostics, repeat vs first capture, strict | **12/12 identical** (deterministic) |
| native 468-row replay, all five sets | exit 0, `COMPLETE input_tick=447 time_passed=446`, checksum `0x93E9EFB4`, no leftover process, user config byte-identical |
| entity streams (`validate`, 3 sets × 28,873 replies) | 0 invariant problems; 92 spawn serials per set, max 4 simultaneous weapons, kind 0 only, reset value of `status_total_tics` always 0 |
| non-PORT view of the edited decomp file | token view identical to HEAD (sha `98bbf64d…`, 1,281 lines); MSVC `cl /EP` translation unit identical (`fa4c7346…`, 18,123 lines) |
| `git diff --check` | clean |

## 3. Bounded no-training validation

| suite | command | result |
| --- | --- | --- |
| M7n unit (contract, parser, builder, offline traces, SB3 dummy, config, inference timing, isolation) | `python rl/m7n_tests.py unit` | **8/8 PASS** (`runs/m7n/_tests/m7n_unit4`, final code) |
| M7n game (wrapper vs raw on a horizon and a fall artifact, standby, real-game SB3, N=5 bench) | `python rl/m7n_tests.py game` | **4/4 PASS** on the final contract (`runs/m7n/_tests/m7n_game2`) |
| Phase K readiness (v1 / v2 profiles, fingerprints, rejections, checkpoint identity) | `python rl/m7g_k_tests.py unit` | **6/6 PASS** on the final code (`runs/m7n/_tests/m7g_k_unit4`; needs `m7n` in its later-milestone exclusion, one line) |
| v2 observation | `python rl/m7g_obs_tests.py unit` | **8/8 PASS** (v2 digest `dcfd14b2…` unchanged) |
| configuration | `python rl/m7b_config_tests.py` | **16/16 PASS** |
| action-class table | `python rl/m7n_status_table.py check` | IDENTICAL to a fresh derivation |

Offline v3 over every capture reply (`unit_offline_traces`): 23 traces (the probe TAS plus the two `entity_all` sets),
every reply parses, 0 spatial / entity invariant problems, every observation inside the space and finite, every
masked row exactly zero, no unmapped status id, no projectile overflow, identical digest chains across the three host
modes and the repeat (7 TAS traces, 2 per historical artifact), largest absolute input 6.67, 0 stale replies (no
teardown reply is observed on this path: the M5 stack does not detect falls and the M7 stack terminates a fall from
the observation, so the hold-last rule is exercised synthetically only, as v2's was).

Configuration rejections (TOML and `M7Config`): v3 with observation normalisation on, v3 with `MlpPolicy`, another
`net_arch`, `relu`, an `entity` flag written in the TOML, reward normalisation, an unknown `btt_policy_obs_v3`; v3
without its native flags; v1 / v2 profiles keep their flags and identity blocks; the four M7n profiles resolve
(pilot 40,960; campaign 3 × 3,072,000, seeds 0–2).

Timing / step behaviour verified: reset observation at `input_tick = 0`, `step_count = 0` (the extra observe is
non-consuming); first step consumes tick 0 in cold and standby-promoted episodes; cold and promoted episodes give
identical v3 chains; wrapper observations equal the offline rebuild from a second process's raw trace.

**Throughput and memory** (N = 5 workers with one standby each, ≤ 10 game processes, random Track 1 actions, no
learning; two arms per observation, 40,000 transitions each):

| | v1 | v3 | v3 / v1 |
| --- | --- | --- | --- |
| environment transitions / s | 1,803 | 1,536 | **0.852** (v2 measured 0.85–0.90) |
| worker native round trip per step | 1.033 ms | 1.204 ms | +0.17 ms (larger JSON reply: spatial + entity) |
| worker Python wrappers per step | 0.147 ms | 0.356 ms | +0.21 ms (full spatial parse, entity parse, builder) |
| policy forward, batch 5 (rollout step), 1 thread | 0.663 ms | 0.784 ms | |
| policy forward, batch 512 (minibatch) | 1.711 ms | 2.825 ms | |
| parameters | 11,538 | 87,186 | |
| rollout-buffer observations (5,120 transitions) | 0.29 MiB | 11.8 MiB | |

## 4. The capped integration pilot

Registered before launch in [`rl_observation_v3_m7n_pilot_registration.json`](rl_observation_v3_m7n_pilot_registration.json)
(cap **40,960** transitions = 8 rollouts, expected 80 optimizer passes, checkpoint sets `ckpt_000000000` /
`ckpt_000020480` / `final`, smoke 5 + 5 episodes at seed 12345, launch gate 10 GiB commit / 4 GiB physical, the
profile's, code's and executable's identity, the fresh-construction digests). Profile
`rl/configs/m7n/pilot/m7n_pilot_s0.toml`; outputs under `runs/m7n/pilot` (separate from any campaign tree).

**Three attempts, reported in full.** Attempt 1 (registration `…_attempt1.json`, `runs/m7n/pilot_attempt1_failed`)
stopped at the trainer's first update-boundary snapshot: `copy.deepcopy(vn.obs_rms)` on a VecNormalize without
statistics forwards the lookup to the vector env (`AttributeError`). Attempt 2 (`…_attempt2.json`,
`runs/m7n/pilot_attempt2_verifier_defect`) trained to completion (40,960 transitions, 80 updates, leak-free) and
failed in the post-run verifier: `getattr(vn, "obs_rms", None)` on an *unpickled* VecNormalize recurses inside SB3's
wrapper `__getattr__` (`RecursionError`). Both are infrastructure defects of the statistics-free wrapper, not of the
observation; the fix reads the instance dictionary (`vars(vn).get("obs_rms")`) in the trainer, the evaluator's
digest / record / identity helpers and the verifier, and was first proven offline on attempt 2's three saved
`vecnormalize.pkl` files. Each attempt's registration was retired and a new one frozen on the fixed code before
relaunch; the cap and the checks never changed. Nothing from any attempt was used to tune anything.

**Attempt 3 (the registered pilot, code fingerprint `09bb2f68…`, the final code): PASSED, 8 / 8.**

| check | result |
| --- | --- |
| P1 exit clean | trainer exit 0 under the guard, no stop, no leftover process, user configuration byte-identical |
| P2 accounting | `sb3_num_timesteps` 40,960; `n_updates` 80; sets `ckpt_000000000`, `ckpt_000020480`, `final`, hash-verified; every set `norm_obs` False, `norm_reward` False, no statistics |
| P3 fresh initial | `ckpt_000000000` policy digest `c43eb58b…` and statistics digest `bca6216b…` equal the fresh construction |
| P4 rows | 11 training episodes (5 falls, 6 horizons; 5 cold starts, 6 standby promotions, 0 cold fallbacks), 0 row problems under `btt_reward_v2` |
| P5 updates | final policy digest `d63ce80c…` ≠ initial; every parameter finite; 8 rollouts logged |
| P6 contracts | `btt_policy_obs_v3_entities` with this code's digest, table digest, flags `SSB64_RL_NO_RENDER / RAPHNET_DISABLE / RL_SPATIAL / RL_ENTITY = 1`, network `btt_policy_net_v3_multiinput_mlp64`, 87,186 parameters |
| P7 resources | at most 10 game processes and 10 listeners, 0 hard alerts, 0 lifecycle failures; system commit drawn 5.10 GiB; lowest available commit 13.1 GiB, lowest available physical 6.07 GiB; 0 probe samples below the physical gate |
| P8 evaluation smoke | 5 + 5 episodes of the final set, frozen, metrics on: verifier OK, every preserved artifact's first action consumed tick 0, workers closed cleanly, 54 s wall |

Descriptive, never a check: training throughput 908 transitions / s end-to-end for the whole 55 s run (collection
1,225 / s; per-rollout collect 4.3 s + optimize 0.86 s at steady state); mean 3.18 targets over 11 training
episodes; smoke targets 0–4.

## 5. Historical control reproduction (R1 / R2 / R3 on the final code and executable)

`python rl/m7n_control_check.py` (the M7l R1 / R2 / R3 procedure reused unchanged through `rl/m7h_run.py` and
`rl/m7l_campaign.py`; the M7h runner's executable pin is pointed at the final executable at runtime and the actual
hash is recorded). Record: `runs/m7n/_control/control_check.json`, raw outputs under
`runs/m7n/_control/code_09bb2f68a5b4__20260926T153441Z/`. Code fingerprint `09bb2f68…` (111 files: every non-test
`rl/*.py`, `rl/data`, the M7n / Phase K / R1 profiles) = the final code of this step; executable `748dbad9…`.
**PASS in 37.3 min, 0 problems.** Two earlier launches of the check were aborted by me before completing (they had
started while the pilot's verifier defects were being fixed, so they were not on the final code); their partial
trees are preserved under `runs/m7n/_control/_aborted_*` and nothing from them was used.

| check | result |
| --- | --- |
| R1 s0 / s1 / s2 (curriculum-off `btt_reward_v2`, 102,400 transitions on the new executable) | final policy + statistics digests `5cec5fc4…` / `56241d22…` / `5177b527…` = the pinned Phase K = M7e `ckpt_000102400`; 30 / 27 / 29 episode rows equal the registered rows (and their sha256); no curriculum trace; learn 92 / 87 / 88 s |
| R1 vs the M7l manifest's Phase K pins | equal (digests, row counts, row hashes) |
| R2 s0 / s1 / s2 (100 deterministic + 100 stochastic of each historical final, seed 12345, frozen, metrics on) | **600 / 600** episodes equal in native action digest, targets, end reason and `btt_eval_metrics_v1`; leak-free; 10.3 / 10.5 / 11.1 min |
| R3 decision inputs from R2 and from the historical records | equal to each other and to the registered control values: T = 118/25, 19/4, 427/100; falls 1, 1, 0; target 2 in 1, 0, 2 episodes; L 0, 0, 1; R 0; deterministic facts equal |

So the historical Phase K v1 runs (`runs/m7g_k/m7g_s{0,1,2}_v1`, bit-exact to M7e) are a valid control on the
final code and executable. This check binds the control to fingerprint `09bb2f68…`; any later edit of the
fingerprinted files requires re-running it before the control is used.

## 6. Runtime and memory estimate for the comparison

From the pilot's steady-state rollout (5,120 transitions in about 4.3 s collection + 0.86 s optimisation) and the
Phase K measurements (v1 33 min training / 36 min evaluation per run; v2 42 / 41 min):

| item | estimate |
| --- | --- |
| v3 training, one run of 3,072,000 | 600 rollouts × ≈ 5.2 s ≈ **52 min** (range 45–55; Phase K v2 was 42) |
| v3 post-hoc evaluation, one run (985 episodes, M7e protocol) | ≈ **45 min** (v2: 41; environment throughput 0.85 of v1) |
| three v3 runs, training + evaluation | ≈ **4.9 h** |
| control reproduction check (R1 ×3, R2 ×3, R3) | ≈ 35 min (M7l: 31) |
| campaign total with the control reused | ≈ **5.5 h** wall, sequential runs |
| if the control had to be retrained (a separate decision, never automatic) | + 3 × (34 + 36) min ≈ 3.5 h |
| memory | commit drawn ≈ 5.1 GiB per run at N = 5 standby (Phase K v2 5.2–5.6); launch gate 10 GiB commit / 4 GiB physical stands; rollout buffer 11.8 MiB, parameters + Adam ≈ 1 MiB |
| disk | ≈ 1.7 GiB per v3 run (checkpoints + 31 sets ≈ 11 MiB, artifacts as Phase K) |

## 7. Blockers, open items, recommendation

**Genuine blockers: none.** Everything the campaign needs exists and is verified on the final code: the
observation and its native diagnostic, the trainer / evaluator wiring, the three prepared profiles, the pilot, the
control reproduction, the proposed rule.

**Open items, none blocking:**
- The rule and manifest are *proposed*, not frozen: launching the campaign means freezing
  `rl_observation_v3_m7n_decision_rule.json` (sha256 recorded), the three profiles, the code fingerprint
  `09bb2f68…`, the executable hash, the control-check record and the evaluation plan in a manifest, then `train`
  under the guard (launch gate 10 GiB commit / 4 GiB physical; the Phase K post-hoc evaluation afterwards).
- A campaign driver in the style of `rl/m7l_campaign.py` (manifest, drift check, train, evaluate, verify-clears,
  census, analyze) is not written yet; Phase K's `rl/m7g_k_run.py` machinery covers evaluation and clear
  verification, and `m7n_decision_rule_v1` needs its `decide()` implemented and unit-tested before the first launch.
- The M7l / M7m campaign drivers now report code drift (their manifests pin the pre-M7n fingerprints); their frozen
  evidence, rules and analyses are byte-unchanged. This is the expected consequence of any code change, as in M7l.
- Cross-character: only Mario's action-class table is validated (section 1.3).
- The stale (teardown) path of the v3 builder is exercised synthetically only, exactly as v2's was.
- Three pilot attempts were needed (section 4); the two defects were in the statistics-free VecNormalize handling
  of inherited helpers, both fixed and re-proven; the cap and the checks never changed.

**Recommendation.** The full comparison is ready to be registered and launched as a separate decision: fresh v3
models (profiles `rl/configs/m7n/m7n_s{0,1,2}_v3.toml`, 3 × 3,072,000 transitions, reward v2, Track 1, tick-0 starts,
Phase K PPO and evaluation) against the reproduced Phase K v1 control, decided by `m7n_decision_rule_v1` with tick-0
evaluation as the only success path and target-2 metrics as supporting diagnostics. Estimated cost about 5.5 h wall
and 5.1 GiB commit per run. Before launch, the remaining engineering is the campaign driver with the frozen manifest
and the rule's `decide()` (about one focused session), plus re-running the control check if any fingerprinted file
changes.

## 8. Campaign preparation (2026-09-26, second pass): driver, rule, manifest, control binding

**Scope.** The observation contract, the native diagnostic, the trainer / evaluator hooks and the executable are
unchanged since section 1. This pass added the campaign driver and the rule implementation, froze the manifest and
re-ran the control reproduction on the final fingerprint. Nothing was trained beyond the R1 reproduction runs.

### 8.1 New files

| file | role |
| --- | --- |
| `rl/m7n_analysis.py` | `m7n_decision_rule_v1`: `decide()` on exact integers / Fractions over `rl/m7l_analysis.label_inputs` quantities; `self-test` with 27 synthetic cases |
| `rl/m7n_matrix.py` | the matrix (three fresh v3 runs, seeds 0–2), registered values (`arm_checks`), the Phase K proof, the code fingerprint, the evaluation plan (11 labels, 985 episodes per run), the directory plan, the manifest builder |
| `rl/m7n_campaign.py` | `manifest`, `control-check`, `train` / `preflight`, `evaluate`, `verify-clears`, `census`, `analyze`, `status`, `all` (modelled on `rl/m7l_campaign.py`; reuses the Phase K evaluation settings, `verify_metrics`, `verify_clears_in`, `verify_eval_tick0`) |
| `docs/rl_observation_v3_m7n_decision_rule.json` | the rule, machine-readable (`schema`, `parameters`, `gates_in_order`, `integrity_gate`, `incomplete`, `control_clear_guard`, `tie_handling`, `supporting_diagnostics_never_gating`) |
| `docs/rl_observation_v3_m7n_manifest.json` | the frozen manifest (section 8.4) |
| `rl/m7n_tests.py` | + `unit_rule`, `unit_matrix` (10 / 10 PASS) |

### 8.2 The decision rule (`m7n_decision_rule_v1`, sha256 `9f5c0fd9…`)

**Inputs, per seed s in {0, 1, 2}, paired by seed number** (all from `btt_eval_metrics_v1` records of frozen
checkpoints evaluated from tick 0, computed by `rl/m7l_analysis.label_inputs`):

| symbol | definition | denominator |
| --- | --- | --- |
| K[a][s] | verified clears: a native clear whose canonical actions, replayed from tick 0 on a fresh process, reproduce `completion_time_passed` and `completion_input_tick` exactly | the 200 final episodes of the run (100 stochastic + 100 deterministic) |
| T[a][s] | mean targets broken (exact Fraction) | the 100 final stochastic episodes that are not verified clears |
| X[a][s] | 1 if any final stochastic episode entered the left region (live x < -2100) or broke target 1, 6 or 8 | the 100 final stochastic episodes |
| D[s] | T[v3][s] - T[v1][s] | |
| G[s] | T of v3's final label - T of v3's own initial label (`ckpt_000000000`, 100 stochastic) | |

**Order of evaluation** (the first gate whose condition holds decides; every later gate is still evaluated and
reported, never used):

| step | name | condition | outcome | action |
| --- | --- | --- | --- | --- |
| 0 | integrity | the control check missing / failed / bound to another fingerprint or executable; a v3 run not verified; an evaluation label of either arm failing its verification; a native clear not reproduced; manifest drift; a control label incomplete or changed | **invalid** | stop; no decision recorded; diagnose |
| - | incomplete | fewer than three verified v3 runs; a v3 final label without 100 + 100 episodes or an initial label without 100 stochastic; a stopped / failed / partial v3 run | **incomplete** | no decision; reported as incomplete, never as failure or inconclusive |
| 1 | first_clear | (sum K[v3] >= 1 and sum K[v1] = 0) or K[v3][s] > K[v1][s] for every seed | **success** | clears and checkpoints preserved permanently; v3 becomes the Track 1 observation |
| guard | control-clear guard | sum K[v1] >= 1 and sum K[v3] = 0: gates 2 and 3 cannot select v3 | | gates 4-6 still apply |
| 2 | ceiling_broken | X[v3][s] = 1 in >= 2 seeds and X[v1][s] = 0 in every seed | **success** | v3 selected; crossing episodes replayed and documented |
| 3 | better_targets | D[s] >= 1/2 in every seed | **success** | v3 selected |
| 4 | worse | D[s] <= -1/2 in every seed | **failure** | v1 stays; v3 recorded as worse at this budget |
| 5 | no_learning | G[s] <= 0 in >= 2 seeds | **failure** | v1 stays; the representation is re-examined before any further v3 run |
| 6 | no_benefit | anything else | **inconclusive** | v1 stays the default; v3 stays available; no extension |

**Ties and boundaries.** Every comparison is inclusive on exact integers or Fractions; equal clear counts
(including 0 = 0) are not gate 1; the per-seed clear comparison is strict; D = 1/2 counts for gate 3 and D = -1/2 for
gate 4; G = 0 counts as no learning; X ties are not gate 2. **Label precedence:** integrity, then incompleteness,
then gates 1-6 in order. **Improvement over the control** is measured per seed (no pooling, no averaging across
seeds) against the reproduced v1 finals: event counts for gates 1-2, a symmetric paired threshold of half a target
per episode for gates 3-4. **Progress toward a tick-0 clear:** K is the clear itself, X is the ceiling (the three
targets no tick-0 policy has reached), D the ordinary count; a gate 2 or 3 success is progress, never a clear.

**Supporting diagnostics, never gating:** target-2 breaks per seed and pooled (control 1, 0, 2 = 3 / 300) with tick
and the M7l L / R context; deterministic play targets and collapse share; falls; first-left-entry ticks;
per-checkpoint curves of both arms; seven-right episodes; training episodes, falls, throughput; evaluation wall,
peak processes, memory minima.

**Self-test** (`python rl/m7n_analysis.py self-test`, also `unit_rule`): 27 synthetic cases PASS, covering integrity
first, three incompleteness forms, a changed control label, the clear tie, per-seed clear dominance, the v1-only
clear (guard blocks gates 2 and 3, still allows gate 4), left entry in 1 / 2 seeds and in both arms, D exactly
+1/2 and -1/2 and 49/100 short, sign disagreement, G = 0 and G <= 0 in 1 / 2 seeds, precedence of gates 1, 3 and 4
over 5, identical arms, another rule schema refused, fractions and the rule digest carried in the report.

### 8.3 Pilot accounting (all attempts preserved)

| attempt | registration (code fingerprint) | transitions consumed | PPO updates | outcome | directory |
| --- | --- | --- | --- | --- | --- |
| 1 | `..._attempt1.json` (`47412284...`) | 0 (crashed at `on_training_start`) | 0 | trainer `AttributeError`: `copy.deepcopy(vn.obs_rms)` on a statistics-free VecNormalize forwarded to the vector env | `runs/m7n/pilot_attempt1_failed` |
| 2 | `..._attempt2.json` (`34582b08...`) | 40,960 | 80 (8 rollouts x 10 epochs) | training completed, leak-free; verifier `RecursionError`: `getattr(vn, "obs_rms", None)` on an unpickled VecNormalize recurses in SB3's wrapper lookup | `runs/m7n/pilot_attempt2_verifier_defect` |
| 3 (registered) | `..._pilot_registration.json` (`09bb2f68...`) | 40,960 | 80 | **PASSED 8 / 8** on the code that also carries the campaign (only driver / analysis / test files were added afterwards; no trainer, observation or evaluator file changed) | `runs/m7n/pilot` |

Fixes: the trainer's boundary snapshot, the evaluator's digest / record / identity helpers and the verifier read the
instance dictionary (`vars(vn).get("obs_rms")`) instead of attribute lookup; proven first on attempt 2's three saved
`vecnormalize.pkl` files, then by attempt 3. The cap (40,960) and the eight checks never changed. **No pilot
checkpoint, optimizer state or normalisation state initialises the campaign:** every campaign run starts from a fresh
construction, verified by the untrained-set digests pinned in the manifest. The seed-0 campaign run's expected
untrained digest (`c43eb58b...`) equals the pilot's untrained set because both are the deterministic fresh
construction for seed 0 with the same network; nothing is loaded from the pilot. Pilot performance was not used for
anything. The pilot was not re-run in this pass: no change touched a file its checks depend on (the added files are
the driver, the analysis module, the matrix and tests; the observation, trainer, evaluator and executable are
byte-identical to attempt 3's).

### 8.4 The frozen manifest (`docs/rl_observation_v3_m7n_manifest.json`)

| identity | value |
| --- | --- |
| code fingerprint (`code.sha256`) | `b3566971...` over 101 files: every non-test `rl/*.py`, `rl/data/*.json`, the four M7n profiles, the three Phase K v1 profiles, the three R1 profiles, the rule |
| control-check fingerprint (`code.control_check_sha256`, the set `rl/m7n_control_check.py` records) | `42e73428...` (114 files) |
| executable | `748dbad9...` (`build-us/Release/BattleShip.exe`) |
| revisions | parent HEAD `1373710` (dirty: the uncommitted M7n work), `decomp 3c7fd5d0` (one PORT-only working-tree edit), `libultraship 805f1950`, `torch 3aa9c97` |
| observation | `btt_policy_obs_v3_entities` digest `4ddc2933...`, flat 606, network `btt_policy_net_v3_multiinput_mlp64`, table `97db1152...` |
| decision rule | `9f5c0fd9...` |
| runs | `m7n_s{0,1,2}_v3`: profile source / semantic / compatibility fingerprints, every `arm_checks` value True, Phase K proof OK (compatibility views differ exactly in `contracts.observation`, `ppo.policy`, `ppo.vecnormalize.normalize_observations`, `environment.extra_env`; values also in name / notes / output_root), expected untrained digests |
| historical control | per seed: final / initial / 102,400 digests, row hashes, final evaluation file hashes, decision inputs; the control-check binding rule |
| pilot | registration and report hashes, the three attempts' accounting |
| authority | `approval: PENDING` - `train` is blocked until the user's authorisation replaces it (a deliberate block in the driver) |

`manifest_drift` compares all of these on every command; `train --dry-run` is the preflight.

### 8.5 Control reproduction on the final fingerprint

`python rl/m7n_campaign.py control-check` (rl/m7n_control_check.py bound to the frozen manifest): **PASS in 38.9 min,
0 problems**, record `runs/m7n/_control/control_check.json`, raw outputs `runs/m7n/_control/code_42e73428ce19__20260926T194458Z/`.
Code fingerprint `42e73428...` = the manifest's `code.control_check_sha256`; executable `748dbad9...` = the manifest's.
R1 s0 / s1 / s2: final digests equal the pinned Phase K = M7e `ckpt_000102400` (`5cec5fc4...`, `56241d22...`,
`5177b527...`), 30 / 27 / 29 rows equal the registered rows and hashes. R2: 600 / 600 episodes equal (native action
digest, targets, end reason, metrics). R3: decision inputs equal the registered control values (T = 118/25, 19/4,
427/100; falls 1, 1, 0; target 2 in 1, 0, 2; L 0, 0, 1; R 0). The earlier PASS on fingerprint `09bb2f68...` (section 5)
remains on record; this pass supersedes it because the driver files changed the fingerprint.

`python rl/m7n_campaign.py train --dry-run` (the preflight) after the check: manifest drift none; control bound;
every profile's `arm_checks` True; directory plan clean (15 planned, 0 existing); launch gate passing (18.2 GiB
commit, 6.9 GiB physical, CPU 0.3 %, no game process); **exactly one blocking problem: `authority.approval` is
PENDING**, the deliberate block until the user authorises the launch.

### 8.6 Budget and runtime

| item | value |
| --- | --- |
| policy transitions | 3 x 3,072,000 = 9,216,000 (hard maximum; no extension, no extra seed) |
| evaluation episodes | 3 x 985 = 2,955 (740 stochastic + 245 deterministic per run) + clear replays |
| v3 training per run | about 52 min (pilot steady state 5.2 s per 5,120-transition rollout; range 45-55) |
| v3 evaluation per run | about 45 min |
| three v3 runs | about 4.9 h |
| control | reused (reproduction check on the final fingerprint, section 8.5) |
| campaign wall, sequential | about **5.5 h** including preflight, census and analysis |
| memory / disk | about 5.1 GiB commit drawn per run; launch gate 10 GiB commit / 4 GiB physical; about 1.7 GiB disk per run |

### 8.7 Scope and limitations (unchanged)

The campaign tests the complete v3 observation package against v1; it cannot attribute an effect to geometry, action
progress, projectiles or normalisation. Cross-character transfer is unproven; Mario is the only validated action-class
mapping. The omitted ledge column is a stage-coverage limitation of this contract, not evidence that ledge
information is unnecessary. The stale (teardown) path is exercised synthetically only. The M7l / M7m drivers report
drift against their own manifests (their frozen evidence is byte-unchanged).

## 9. Pre-launch corrections and launch (2026-09-26, user review)

The user reviewed section 8's rule and authorised the bounded campaign subject to three narrow corrections, extra
synthetic cases, preservation of the previous rule, a re-frozen manifest, a repeated control verification on the new
fingerprint and the approval recorded through the supported mechanism. Nothing else changed: the observation
contract (`4ddc2933…`), the native diagnostic, the executable (`748dbad9…`), the trainer / evaluator hooks, the
profiles, the pilot and the M7l / M7m evidence are byte-identical to section 8.

### 9.1 The three corrections (rule `m7n_decision_rule_v2`, `docs/rl_observation_v3_m7n_decision_rule_v2.json`)

| # | gate | before (v1) | after (v2) | code |
| --- | --- | --- | --- | --- |
| 1 | 2 | X = 1 on any live x < −2100 entry or left-target break in the final stochastic episodes (raw `btt_eval_metrics_v1`) | X = 1 only on a **replay-verified qualified wall crossing with a valid left-side landing** or a **replay-verified left-target break** (criterion `btt_qualified_crossing_v1`, section 9.2); the same criterion and code path on every control seed (R4 of the control check and the campaign's `verify-crossings`); the control-clear guard unchanged | new `rl/m7n_crossing.py`; `rl/m7n_analysis.py` (`x_of` over `CrossingInputs`); `rl/m7n_campaign.py` (`verify-crossings`, report cross-checks); `rl/m7n_control_check.py` (R4) |
| 2 | 1 | the explanation said no single seed can carry a decision | one native-verified v3 clear with no control clear legitimately decides gate 1 on its own; the no-pooling / no-single-seed statement applies to gates 2–5 only | rule text (`improvement_over_control`); the condition itself was already `sum K[v3] >= 1 and sum K[v1] == 0` |
| 3 | 3–5 | `decide()` raised when T was undefined | T is **null** (never 0) when every stochastic episode of a label is a verified clear; D / G are null when an operand is; gates 3 and 4 are **inapplicable** unless D is defined in every seed; a seed with undefined G never counts toward gate 5 (inapplicable when fewer than 2 seeds have G defined); an inapplicable gate never decides and evaluation continues; gate 1 depends on K only, so clear-first precedence needs no exception and no fabricated number; a null T without an all-clear label is refused as a defect | `rl/m7n_analysis.py` (`quantities`, `decide`, `inapplicable` in the report) |

The superseded v1 rule stays **byte-identical** at `docs/rl_observation_v3_m7n_decision_rule.json` (sha256
`9f5c0fd9eeb33e971148e6774e1d12140dc3318141c164a2829631d629001574`, never used for a decision); v2 records it under
`supersedes` with the three corrections and the added synthetic cases. The pre-launch manifest built on v1 is kept
byte-identical at `docs/rl_observation_v3_m7n_manifest_prelaunch_rule_v1.json` (sha256 `b5a9b61b…`).

### 9.2 Gate 2: the registered crossing criterion and procedure (`btt_qualified_crossing_v1`, `rl/m7n_crossing.py`)

Why: M7h's training-only entry s2 `56a1af09` was an off-stage fall (y −8412) that satisfied the raw left-region rule.

| step | definition |
| --- | --- |
| candidates | every final **stochastic** episode whose `btt_eval_metrics_v1` record has a `first_left_entry` or a left target (1, 6, 8) in `broken_ids`; the deterministic play stays diagnostic (as for T) |
| replay | the candidate's canonical native actions from tick 0 on a fresh process (`rl/m7f_trace.run_stepping_trace`); v3 labels under the run's evaluation flags + `SSB64_RL_TARGET_DIAG=1`, control labels under the M6 flags + `SSB64_RL_TARGET_DIAG=1`; read-only diagnostics, native gameplay authoritative |
| exact | no consumed-tick mismatch, every action consumed, replayed native action digest = recorded, replayed break table (id, tick) = recorded `target_breaks`, replayed first-left-entry tick = recorded, target count = recorded; an inexact candidate is **gate 0 (integrity)**, never counted and never ignored |
| entry | a live step E whose immediately preceding live step P has x_P ≥ −2100 > x_E (the tick-0 observation is step 0's predecessor; `btt_reward_v3`'s pairing); class by `btt_reward_v3.classify_entry`: `over_wall` iff y interpolated at x = −2100 ≥ 3000 − 1; `under_stage` / `through_face` / `unpaired` are off-stage falls or anomalies, never crossings |
| qualified wall crossing | entry class `over_wall` AND `btt_crossing_evidence_v1` path `over_ledge` (Mario at or above the wall top over the ledge span between the grounded takeoff and the first left step) AND a grounded takeoff (`approach_surface` present) AND a **valid left-side landing inside the same left visit** (before the next exit x ≥ −2100) |
| valid left-side landing | a live step with `ground_air_state` 0 that `m7g_fixture.classify_ground` matches (tolerance 1.0) to a decoded left-side floor line (`left_side_floor_lines` = [3]: y −1950, x −3900..−2700, decoded from `124_GRBonus1MarioFile2.c`) and that is not the native-failure step itself |
| left-target break | the exact replay's break table contains target 1, 6 or 8 |
| X | 1 iff the label has ≥ 1 qualified-crossing episode or ≥ 1 verified left-target-break episode; the document `crossing_verification.json` is **always** written, a label with zero candidates records X = 0 by the same criterion |
| recorded, never required | the route label `btt_route_rule_v1` (`lower_precision` / `upper_moving_platform` / `unclassified`; the M7g-a decision that the classifier proposes and never gates), whether the right sweep was complete at the entry (the M7j reward's own qualification, not a gate-2 requirement: gate 2 measures the ceiling, not route timing), the class and boundary height of every unqualified entry, its landing surface if any |

Control seeds: **R4** of `rl/m7n_control_check.py` enumerates the candidates of the historical final labels and of the
R2 re-evaluation labels (they must be identical sets), replays every candidate and records X[v1][s]; the campaign's
`verify-crossings` repeats the historical finals with the same code path and `analyze` cross-checks both (a
disagreement is integrity). The registered control has no `first_left_entry` and no left-target break in any of its
300 final stochastic episodes (`left_entries` 0, `left_target_episodes` 0 per seed, R3), so the corrected criterion
gives zero candidates and X[v1][s] = 0 by the same procedure the v3 finals get.

### 9.3 Synthetic cases

`python rl/m7n_analysis.py self-test`: **46 cases PASS** (the 27 of section 8 plus): incomplete when a v3 crossing
verification is missing; integrity when the control's is missing, when a v3 or control candidate is inexact; the
single-seed first clear in seed 1 with worse targets elsewhere; the all-clear v3 label (T null, D null) with no control
clear → gate 1; all-clear labels in both arms with equal clears → inconclusive tie with gates 3–5 inapplicable; an
all-clear v3 seed against a control clear in that seed → not gate 1 per seed, gates 3–4 inapplicable; undefined G in
two seeds → gate 5 inapplicable; undefined G in one seed with G = 0 in the other two → no learning; an off-stage left
entry in every seed (exact, unqualified) → not gate 2; raw left-entry counts never gate; a qualified landing in 2 seeds
→ gate 2; a left-target break in 2 seeds → gate 2; one crossing + one break → gate 2; one seed only → not gate 2; a
control candidate that does not qualify does not block gate 2; a control qualified crossing or left-target break blocks
gate 2; gate 2 takes precedence over worse; a null T without an all-clear label is refused.

`python rl/m7n_crossing.py self-test`: **15 cases PASS** on synthetic traces over the decoded geometry: the
fixture-like lower crossing (L1 takeoff, over the ledge, landing on L3) qualifies with sweep recorded incomplete; the
M7h off-stage fall (`under_stage`, failure step) is a left entry, not qualified; an over-wall entry without a landing
is not qualified; a landing on the failure step does not count; a landing belongs to its own visit; grounded off any
decoded left floor is not a landing; no entry; candidates in label order with reasons; missing document → pending;
inputs from a complete document; an inexact candidate is integrity with X 0; a candidate set differing from the rows;
zero candidates → X 0. `rl/m7n_tests.py unit`: 11 / 11 (new `unit_crossing`; `unit_rule` checks the v1 preservation
and the corrections; `unit_matrix` checks the v2 rule is fingerprinted and an approval for another digest is PENDING).
`rl/m7g_k_tests.py unit`: 6 / 6.

### 9.4 The approval mechanism

`docs/rl_observation_v3_m7n_approval.json` (`m7n_launch_approval_v1`): the user's authorisation text, the conditions
it required, what it applies to (rule v2 sha256, observation contract digest, executable, matrix, budget), the stop
policy, what is not authorised, what is preserved and what the final report must contain. `rl/m7n_matrix.approval_status`
accepts it only when it names the current rule digest, observation contract and executable; the manifest pins the
record's sha256 under `authority.approval_record`; `manifest_drift` reports a changed or missing record (and a record
that exists while the manifest pins none); `train` refuses unless the frozen manifest's approval starts with APPROVED
**and** the record on disk is the pinned one. No check was bypassed.

### 9.5 Control reproduction on the final fingerprint (R1–R4)

`python rl/m7n_control_check.py` on the final code fingerprint `c5f31d7bc174…` (115 files) and executable `748dbad9…`:
**PASS in 36.9 min, 0 problems**; record `runs/m7n/_control/control_check.json` (schema `m7n_control_check_v2`), raw
outputs `runs/m7n/_control/code_c5f31d7bc174__20260926T221228Z/`. R1 s0 / s1 / s2: final digests equal the pinned
Phase K = M7e `ckpt_000102400`, 30 / 27 / 29 rows equal. R2: 100 + 100 episodes equal per seed (600 / 600). R1 vs
Phase K pins: equal. R3: decision inputs equal the registered control values. **R4 (corrected gate-2 inputs):** the
historical final labels and the R2 re-evaluation labels have identical candidate sets, 0 candidates in every seed
(100 stochastic episodes each, no `first_left_entry`, no left-target break), X[v1][s] = 0, 0, 0 by criterion
`btt_qualified_crossing_v1`; documents `.../r4/m7g_s{0,1,2}_v1_{historical,r2}_final/crossing_verification.json`.
The earlier PASS records (`09bb2f68…`, `42e73428…`) remain under `runs/m7n/_control/`; the control was never
retrained or substituted. `python rl/m7n_campaign.py control-check --record-only` bound this record to the campaign
state.

### 9.6 Manifest freeze, preflight and launch

`python rl/m7n_campaign.py manifest` (2026-09-26 22:49 UTC) rebuilt `docs/rl_observation_v3_m7n_manifest.json`: ok,
code fingerprint `e9f6adcfdded…` (103 files, now including both rule versions), control-check fingerprint `c5f31d7bc174…`,
executable `748dbad9…`, rule v2 `bd00ff0abc68…` (supersedes `9f5c0fd9…`), approval APPROVED (record `47442c9579c7…`),
control bound (R1–R4), gate-2 control inputs (0 candidates, X 0 per seed), HEAD `1373710`, submodules `decomp 3c7fd5d0`
/ `libultraship 805f1950` / `torch 3aa9c97`. `python rl/m7n_campaign.py train --dry-run`: drift none, control check
none, profiles clean, directory plan clean (0 existing), launch gate passing, **0 blocking problems**
(`runs/m7n/train_dry_run2.log`). `python rl/m7n_campaign.py all` was launched (`runs/m7n/campaign_launch_utc.txt`,
log `runs/m7n/campaign_all.log`); `train` froze the manifest at `runs/m7n/campaign/_matrix/manifest.json`. Result:
section 10.

## 10. Campaign result (n = 3, decided 2026-09-27 04:30 UTC)

`python rl/m7n_campaign.py all` ran 2026-09-26 22:50 → 2026-09-27 04:30 UTC (5 h 40 min) without a stop: three fresh v3
runs trained and verified, 33 / 33 evaluation labels verified (2,955 / 2,955 episodes, census complete), clear
verification (0 candidates), crossing verification of both arms' finals, and one application of the frozen rule v2.
Record: `runs/m7n/campaign/_matrix/analysis_n3.json` (rule `bd00ff0abc68…`, frozen manifest `4bad4d53…`); state
`runs/m7n/campaign/_matrix/state.json`; log `runs/m7n/campaign_all.log`. No drift before or after; the frozen manifest
equals the docs copy; no hard alert, no soft alert, no process leak, no provenance refusal; every `verify_training_run`
passed (fresh construction equal to the pinned untrained digests; nothing loaded from the pilot).

### 10.1 Decision: **gate 3 `better_targets` → success; v3 selected for the next milestone**

Gate 0: no integrity problem. Incomplete: none. Gates in order: 1 first_clear **false** (K = 0 in every seed of both
arms), 2 ceiling_broken **false** (X = 0 in every seed of both arms), **3 better_targets true**, 4 false, 5 false,
6 false; control-clear guard not engaged; no inapplicable gate (no undefined quantity).

| seed | K v1 / v3 | X v1 / v3 | T v1 | T v3 | D = T v3 − T v1 | T v3 initial | G |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 0 / 0 | 0 / 0 | 118/25 = 4.72 | 138/25 = 5.52 | **+4/5 = +0.80** | 33/10 = 3.30 | +111/50 = +2.22 |
| 1 | 0 / 0 | 0 / 0 | 19/4 = 4.75 | 553/100 = 5.53 | **+39/50 = +0.78** | 333/100 = 3.33 | +11/5 = +2.20 |
| 2 | 0 / 0 | 0 / 0 | 427/100 = 4.27 | 559/100 = 5.59 | **+33/25 = +1.32** | 327/100 = 3.27 | +58/25 = +2.32 |

D ≥ 1/2 in every seed (threshold 1/2 per episode, paired by seed, no pooling). This is progress by target count, **not
a clear**: no verified clear, no qualified crossing and no left-target break exists in either arm's finals.

### 10.2 Gate-2 inputs (criterion `btt_qualified_crossing_v1`, both arms, same code path)

Every final stochastic label of both arms had **0 candidates** (no `first_left_entry`, no left-target break in any of the
600 final stochastic episodes), so X = 0, 0, 0 / 0, 0, 0 by the corrected criterion; documents under
`runs/m7n/campaign/_clears/{m7n_s*_v3,control/m7g_s*_v1}/final/crossing_verification.json`; the control's inputs equal
R4's (candidates 0, X 0 per seed). Nothing was replayed for gate 2 because nothing qualified as a candidate.

**Supporting diagnostic (never gating): one left entry at a curve point.** Seed 2's 1,536,000-transition checkpoint
(a 60-episode curve label) produced one tick-0 stochastic episode (`…c350b44b`) with a left-region entry. Replayed
exactly through the same analyser (`_clears/m7n_s2_v3/curve_t001536000_diagnostic/`): grounded takeoff from the raised
right step L1 at tick 1738, path over the ledge, entry class `over_wall` at exactly y 3000 on tick 2391 (route label
`lower_precision`), right sweep not complete (5 targets: 5, 7, 0, 9, 4), **no landing** on any decoded left floor,
352 airborne left-region steps, native failure at tick 2742 (min y −8665). By the corrected criterion it is an
unqualified over-wall entry (a fall on the far side), not a crossing; under rule v1's raw criterion it would have
counted as a left entry. It occurred in an intermediate label, not in a final, and in no case gates.

### 10.3 Paired per-seed diagnostics (final stochastic 100 episodes; deterministic 100)

| seed | arm | targets mean | 7-target eps | target 2 (ticks) | L / R | falls | det. targets | det. collapse share |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | v1 | 4.72 | 0 | 1 (2907, fell) | 0 / 0 | 1 | 2 | 0.507 (collapsed) |
| 0 | v3 | 5.52 | 0 | 0 | 0 / 0 | 0 | 4 | 0.022 |
| 1 | v1 | 4.75 | 0 | 0 | 0 / 0 | 1 | 2 | 0.250 |
| 1 | v3 | 5.53 | 3 | 7 (815, 1171, 1678, 1816, 2307, 2631, 3011; 2 fell) | 4 / 1 | 13 | 1 | 0.023 |
| 2 | v1 | 4.27 | 0 | 2 (1134, 2033) | 1 / 0 | 0 | 3 | 0.341 |
| 2 | v3 | 5.59 | 1 | 1 (1692) | 1 / 1 | 1 | 0 | 0.986 (collapsed) |

Target 2 pooled: v1 3 / 300, v3 8 / 300 (every break policy-initiated from tick 0; L = 5 of 8 by the deadline with ≥ 5
static right targets). Seven-right episodes (all of 0, 2, 3, 4, 5, 7, 9): v3 s1 three (`907d762b` fell at 2976 after
target 2 at 1678; `8857b614` and `b3c4696a` ran to the horizon, sweeps at 3392 and 3011), v3 s2 one (`e404fde0`, sweep
at 1692, horizon); v1 none. R (a seven-right sweep by tick 2699): v3 s1 1, s2 1. Left targets 1, 6, 8: never broken by
either arm. Deterministic play: v3 s0 / s1 are not collapsed (0.02), v3 s2 is collapsed (one action for 3,548 of 3,600
ticks, 0 targets) as v1 s0 was (0.507); the stochastic finals decide, the deterministic play is reported.

Curves (stochastic mean targets at initial → final, 11 labels): v3 3.30 → 5.52 / 3.33 → 5.53 / 3.27 → 5.59, v1
3.19 → 4.72 / 3.30 → 4.75 / 3.23 → 4.27; the v3 curves lie above the v1 curves from the 921,600 point onward in every
seed (`per_seed.*.v3.curve` in the record).

### 10.4 Training behaviour (never evaluation)

| run | episodes | falls | mean targets | native clears | end-to-end tr/s | learn wall | commit drawn | min avail. commit / phys. | game procs max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| m7n_s0_v3 | 860 | 24 | 4.42 | 0 | 1,058 | 48.4 min | 5.13 GiB | 13.4 / 6.2 GiB | 10 |
| m7n_s1_v3 | 888 | 85 | 4.57 | 0 | 1,038 | 49.3 min | 5.33 GiB | 13.3 / 6.2 GiB | 10 |
| m7n_s2_v3 | 860 | 23 | 4.34 | 0 | 1,026 | 49.9 min | 5.19 GiB | 13.4 / 6.3 GiB | 10 |

Each run: exactly 3,072,000 policy transitions, 600 rollouts, 6,000 PPO updates, 0 hard / soft alerts, 0 lifecycle
failures, leak-free close, no training clear (so nothing to replay). Training left entries are not instrumented
(no target diagnostic in training, by design); training targets are unverified tracker counts. Evaluation: 189 min
for 2,955 episodes, all labels leak-free, ≤ 10 game processes. Whole chain 5 h 40 min (estimate was 5.5 h).

### 10.5 Scope of the claim

The complete v3 package (geometry, agent state, action classes, target motion, projectiles, fixed scaling, wider
input) learned more targets from tick 0 than v1 at the same budget in every seed; nothing attributes the effect to a
component, nothing transfers to other characters (Mario only), the ledge column remains a stage-coverage limitation,
no policy cleared the stage or reached the left side with a landing, and the one over-wall entry is a diagnostic from an
intermediate checkpoint. The rule unlocks no extension; the next step is a separate decision.
