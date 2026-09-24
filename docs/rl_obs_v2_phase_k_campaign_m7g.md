# RL M7g Phase K: evaluation metrics and campaign orchestration

Status (2026-09-24): **prepared and tested without training. Stopped for review.** No PPO run was launched, no model
was trained or fine-tuned, nothing was committed or pushed. The design and the pre-registered rule are in
[`rl_obs_v2_experiment_proposal_m7g.md`](rl_obs_v2_experiment_proposal_m7g.md) (revision 2). The trainer, config and
evaluator wiring is in [`rl_obs_v2_phase_k_readiness_m7g.md`](rl_obs_v2_phase_k_readiness_m7g.md). The resolved
matrix is in [`rl_obs_v2_phase_k_manifest_m7g.json`](rl_obs_v2_phase_k_manifest_m7g.json), and the machine-readable
record of this step is [`rl_obs_v2_phase_k_campaign_m7g.json`](rl_obs_v2_phase_k_campaign_m7g.json).

## 0. Summary

- **Per-episode evaluation metrics (`btt_eval_metrics_v1`).** Every evaluation episode of both arms and of the random
  baseline now records:
  - the native first left-region entry;
  - target IDs with their first-break ticks;
  - seven-target occurrence and the moving-target (ID 2) break;
  - the native clear with `completion_time_passed` and `completion_input_tick` kept separate;
  - the termination reason.

  The record uses the M7f diagnostic in evaluation workers only, and nothing is added to either policy observation or
  either reward.
- **Validated on the fixtures.** On both M7g-a fixtures (validation evidence only), through the v1 and v2 worker stacks,
  the recorder reproduces their stored left entries (ticks 1093 and 464) and target IDs and ticks (0/7/6/8/1 and 8)
  exactly. Cold and standby-promoted episodes give identical records.
- **Validated on the TAS.** The TAS gives entry at tick 359, a clear at 446 / 447 with ten targets, and target 2 broken
  at tick 163.
- **Orchestration.** The Phase K tooling is a matrix module, a run driver and an analysis module:
  - `rl/m7g_k_matrix.py`: the manifest, proofs and census;
  - `rl/m7g_k_run.py`: the gate, preflight / dry runs, pilot, training, evaluation, clear verification and census;
  - `rl/m7g_k_analysis.py`: revision 2 of the rule, in exact arithmetic.

  Before anything launches, the driver verifies arm, seed, profile, observation and network identity, executable,
  parent and submodule revisions, code fingerprint, checkpoint provenance, resources and output isolation. Resume and
  partial runs are handled explicitly.
- **Defects fixed before any training:**
  - `m7d_run.inspect_vecnormalize` would have crashed the post-run verification of every v2 run;
  - revision 2's "float64" wording could fail an exact +0.5 tie.
- **Next step (needs the user's go-ahead: it trains):** the pilot in section 5, about 8–12 minutes [E].
  - **Update 2026-09-24: done, both pilot runs passed.**
  - The v1 control reproduces M7e exactly, and the v2 pilot verifies end to end.
  - Results are in [`rl_obs_v2_phase_k_pilot_m7g.md`](rl_obs_v2_phase_k_pilot_m7g.md).
  - **Update 2026-09-24: the six-run comparison is complete.** The decision is gate 7, `no_benefit`, and the extension
    is not unlocked. See [`rl_obs_v2_phase_k_comparison_m7g.md`](rl_obs_v2_phase_k_comparison_m7g.md).

## 1. `btt_eval_metrics_v1` (rl/m7g_eval_metrics.py)

| field | definition | source |
| --- | --- | --- |
| `first_left_entry` | the first live step (`fighter_valid` 1, `btt_active` 1) whose post-update `position_x < −2100.0`. Fields: step index, consumed tick, input tick, time_passed, x, y, ground/air state and fighter status, the same keys as the M7g-a crossing evidence | the M7g-a derived left boundary (the test asserts equality with `derive_regions()`), which equals M7f's `WALL_LEFT_FACE_X` |
| `left_region_steps`, `min_live_x` | live steps left of the boundary; minimum live x | native observations |
| `target_breaks`, `broken_ids`, `first_break_tick` | every break in native order, with the consumed tick, the input tick (= consumed + 1), break order and the native break clocks | `btt_target_identity_v1` (`SSB64_RL_TARGET_DIAG=1`); M7f `check_trace` derivation, one reply at a time |
| `left_targets_broken` | broken IDs among {1, 6, 8} | as above |
| `seven_or_more_targets` | `targets_broken ≥ 7` | episode summary |
| `moving_target_broken`, `moving_target_break_tick` | whether ID 2 broke, and its consumed tick | diagnostic |
| `cleared_native`, `completion_time_passed`, `completion_input_tick` | two separate clocks, never collapsed | M4 recorder terminal |
| `clear_verified` | `None` until `verify-clears` replays the canonical actions on a fresh process | Phase K driver |
| `end_reason`, `termination_reason`, `truncation_reason`, `last_consumed_tick` | as the worker summary | episode summary |
| `consistency` | cross-checks against the worker's own summary (see below) | — |
| `ok` | diagnostic valid and every consistency check true | — |

The `consistency` block checks:
- steps and last consumed tick;
- `targets_broken` against the number of breaks;
- M7d's `target_break_ticks` against the break ticks;
- clear ⇔ all ten targets;
- for a clear: `completion_input_tick = last consumed tick + 1`, and both clocks equal the final break record. A collapsed
  446 / 446 clock fails.

**Where it runs.** It is opt-in: `EvaluationSettings.eval_metrics`, which the Phase K driver always sets.
- `EvalMetricsWorkerFactory` inserts the recorder between `EpisodeStatsWrapper` and `M7WorkerWrapper` of each
  evaluation worker, on the v1 or the v2 stack.
- The recorder passes observations, rewards, actions and infos through unchanged.
- It reads raw step replies through an instance-level shadow of the episode client (the M7g-b v2-wrapper pattern) and
  issues one extra non-consuming `observe` per reset for the tick-0 target table.
- It adds one summary key through the new additive tracker hook `M7EpisodeTracker.extend_pending_summary`.

No training profile sets the diagnostic flag, and the trainer never enables the recorder; both facts are tested. With
metrics off, evaluation rows are unchanged.

## 2. Orchestration

**Matrix and manifest** (`python rl/m7g_k_run.py manifest` → `docs/rl_obs_v2_phase_k_manifest_m7g.json`, ok):

| runs | order | identity proof |
| --- | --- | --- |
| 6 comparison runs (seeds 0–2 × v1 / v2) | s0 v1, s0 v2, s1 v2, s1 v1, s2 v1, s2 v2 (strictly sequential, counterbalanced) | v1 = the M7e profile of its seed except output fields (same semantic and compatibility fingerprints); v2 = the v1 profile of its seed except `contracts.observation`, `ppo.policy` and their derived identity |
| 4 extension runs (seeds 3, 4 × both arms), new profiles | s3 v1, s3 v2, s4 v2, s4 v1; only after an n = 3 decision that requires the extension | the seed-0 profile of the arm except `run.name`, `run.notes`, `run.base_seed` |
| 2 pilot runs (`rl/configs/m7g/pilot/`), new profiles | v1 102,400 then v2 204,800 transitions, before everything | the seed-0 profile except name, mode, notes, budget, output root |

The six existing profiles are byte-identical to the readiness task (sha256 pinned in the tests). Each run also
records:
- the untrained policy and statistics digests, built with the trainer's own helpers (v1 seeds 0–2 reproduce M7d's
  recorded `68155f41…`, `1dd753ae…`, `9fa632c6…`);
- the executable sha256;
- the parent HEAD and the three submodule commits;
- a code fingerprint over the non-test `rl/*.py` modules and every Phase K profile.

The census is 6 × 985 + 100 = **6,010** episodes, and **9,950** with the extension.

**Before anything launches** (`preflight` / `train --dry-run` / `pilot --dry-run` / `evaluate --dry-run` launch
nothing and write nothing):
- no drift from the frozen manifest: executable, HEAD, submodules, code fingerprint, every profile. Changing any Python
  module or profile requires `manifest` again, and the tests proved the gate blocks until then;
- per run: the arm and seed identity checks (observation, policy, flags, v2 contract digest and network,
  reward v2, N = 5 with standby, horizon, budget, PPO, cadence, protocol, run directory);
- output isolation: planned directories unique and disjoint, all under `runs/m7g_k`, never around a historical tree;
- the resource gate (below);
- no BattleShip process, no listener, no `SSB64_*` variable;
- order: only the next run in the registered order can train, and `--only` for any other run is refused;
- extension: refused unless the recorded n = 3 decision requires it;
- evaluation: **checkpoint provenance** for every point:
  - run id in the run's lineage;
  - `num_timesteps` equal to the planned point;
  - experiment fingerprints equal to the profile's;
  - seed, manifest executable and revisions;
  - policy class and network identity of the arm;
  - standby lifecycle;
  - the contracts of the arm.

  A historical M7e set and every tampered variant are refused.

**Resource gate.** It checks BOTH memory figures, separately:
- available system **commit** ≥ 6.0 GiB (commit limit − commit charge, `GlobalMemoryStatusEx.ullAvailPageFile`,
  system-wide);
- available **physical** memory ≥ 2.5 GiB (`ullAvailPhys`).

It also requires free disk ≥ 10 GiB and system CPU ≤ 40 %, and it refuses any BattleShip process, port-block listener
or `SSB64_*` variable. A missing reading fails its gate. `python rl/m7g_k_run.py resources` reads it and launches
nothing. At the time of testing it read 17.06 GiB commit and 5.23 GiB physical available: both passed.

**Resume and partial runs:**

| situation | behaviour |
| --- | --- |
| a run directory without a completed `training_summary.json` | `train` stops and names the two options |
| `--restart-partial RUN` (pre-registered default) | the directory moves intact to `runs/m7g_k/_partial/RUN__<utc>` (never deleted) and RUN trains again from scratch with the same seed |
| `--resume RUN` | continues RUN's own lineage from its latest checkpoint set as `RUN_r<k>`. The M7d resume guard applies (own directories, run id, semantic fingerprint, seed, reward, compatibility), and the event is recorded as a protocol deviation that the analysis reports |
| a completed but unverified directory | verified, never retrained |
| an evaluation label | atomic: a complete `evaluation_summary.json` is reused; a partial label is renamed `__incomplete_<utc>` and re-run |
| a recorded decision | never re-decided (`analyze` refuses a second n = 3 or n = 5 decision) |

**Post-run verification** consists of:
- M7d's `verify_training_run` (now Dict-aware);
- the untrained digests against the manifest;
- Phase K identity from `run.json` and the final set: observation, policy class, v2 network block and contract
  digest, VecNormalize keys, executable and revisions;
- the historical `runs/` fingerprint, leaks and the user configuration.

**Evaluation** is M7e's protocol for both arms. Every episode is preserved and carries a metrics record; every result
must pass `verify_evaluation` plus the metric checks (flags, one record per episode, every record `ok`).

**Clear verification** (`verify-clears`): every cleared episode, deduplicated by native action digest, is replayed with
`m7d_run.replay_one` on a fresh process. It is verified only if the replay reproduces the native clear and **both**
clocks as recorded.

**Analysis** (`analyze`): `decide()` implements section 6.2 in exact rational arithmetic and returns every
intermediate quantity. Gate 0 comes from recorded facts:
- training not verified;
- more than 10 processes;
- the pilot's control reproduction not passed;
- a failed evaluation verification;
- a missing or unverified clear;
- a missing episode;
- `git diff --check`.

Metrics 4–12 are reported beside the decision and never gate. A recorded n = 3 decision that requires the extension
unlocks `train --extension`.

## 3. Tests (commands and outcomes)

Final pass on the final code, sequential, from the repository root; output under
`runs/m7g_k/_campaign_final_20260924T004703Z/`:

| suite | command | result |
| --- | --- | --- |
| Phase K campaign | `python rl/m7g_k_campaign_tests.py` | **16/16 PASS** (12 unit + 4 game), 150 s |
| Phase K readiness (previous task) | `python rl/m7g_k_tests.py` | 9/9 PASS (6 unit + 3 game, incl. the M7e evaluation reproduction) |
| recorder self-test | `python rl/m7g_eval_metrics.py --self-test` | PASS (9 equivalence variants + 8 record checks) |
| decision rule self-test | `python rl/m7g_k_analysis.py --self-test` | PASS (27 checks) |
| M7f target identity | `python rl/m7f_targets.py --self-test` | PASS (26 cases) |
| M7b configuration | `python rl/m7b_config_tests.py` | 16/16 PASS |
| M7e unit | `python rl/m7e_tests.py unit` | 10/10 PASS |
| M7d unit | `python rl/m7d_tests.py unit` | 9/9 PASS |
| M7c standby unit | `python rl/m7c_standby_tests.py unit` | 4/4 PASS |
| M7 smoke unit | `python rl/m7_smoke.py unit` | 8/8 PASS |
| M7g-a fixtures unit | `python rl/m7g_tests.py unit` | 9/9 PASS (both fixture files validated, isolation intact) |
| observation v2 unit | `python rl/m7g_obs_tests.py unit` | 8/8 PASS |
| profile snapshot | before (readiness task) vs now, every profile | the 13 earlier profiles identical (fingerprints, summaries, resolved JSON, dry-run text, contracts, untrained digest) except the two descriptive trainer-view keys added in the readiness task |
| `git diff --check` | parent, decomp | clean |

After the pass:
- fixture sha256 unchanged (`18446e2b…`, `adfd9eda…`);
- executable unchanged (`1e7c62a0…`);
- user configuration unchanged (`1b29d91b…`);
- zero BattleShip processes;
- no campaign directory created.

Not run, by scope: any PPO training (so neither pilot), the full M1–M7f regression chain and a C++ build. No native,
decomp, stepping, reward, action or observation-v1 code changed. The inherited Python changes (a tracker method, an
opt-in evaluator path, a Dict branch in the M7d inspector) are covered by the suites above.

What each new case establishes:

| requirement | case | evidence |
| --- | --- | --- |
| metrics against the fixtures (validation evidence only) | `game_metrics_fixtures` | v1 and v2 stacks, both fixtures. Lower: entry 1093 and breaks (0, 603), (7, 995), (6, 1189), (8, 1246), (1, 1394), fall. Upper: entry 464, break (8, 592), horizon at 681. The recorded first-entry dict equals the fixture's stored evidence and `crossing_evidence` on the raw trace; breaks equal the stored evidence and `check_trace`. The cold and standby-promoted records are identical |
| clear path, 446 / 447 | `game_metrics_tas_clear` | 447 actions, 21 rows unsent; clocks 446 / 447 with `completion_input_tick = last consumed + 1`; ten targets; target 2 at tick 163; entry at 359 |
| clear verification | `game_clear_verification` | the TAS clear re-validated natively (1 / 1, duplicates verified once); a collapsed 446 / 446 record is refused (0 / 1) |
| evaluation path end to end | `game_eval_end_to_end` | untrained checkpoint sets of both arms through provenance → evaluator → metrics → verification (reduced counts); a complete label is reused; random baseline with metrics |
| recorder = M7f derivation | `unit_recorder` | 9 synthetic variants (clean, resurrection, pairing, count, anomaly, native tick, parse failure mid-episode, missing initial object, same-tick order) identical to `check_trace`; boundary = M7g-a derived −2100 |
| evaluator opt-in; training never records | `unit_recorder_wiring` | default settings and factories unchanged; the v1 / v2 metric factories; the flag check; rows; the tracker hook; no profile sets the flag; the trainer never mentions it |
| manifest, proofs, census, digests | `unit_manifest`, `unit_drift_detection` | ok and current; six profiles pinned; 14 proofs; 6,010 / 9,950; M7d v1 digests; each of 6 drift kinds detected |
| resource gate | `unit_resource_gate` | inclusive boundaries (6.0 / 2.5 pass); commit-only, physical-only, both and missing readings fail the right gate; disk, CPU, processes, ports, env; one real reading, nothing launched |
| dry runs | `unit_dry_runs` | the plan starts with s0 v1 and the rest wait; out-of-order refused in the plan; extension refused (exit 2); pilot and evaluate dry runs; `runs/m7g_k` unchanged |
| partial / restart / resume | `unit_partial_and_resume` | a partial run stops `train` (no launch); restart moves it aside hash-identical and relaunches from scratch; resume launches `m7g_s0_v1_r1` from the own checkpoint and records the deviation; a foreign-seed checkpoint is refused by the guard |
| provenance | `unit_checkpoint_provenance` | clean sets of both arms pass; wrong point, arm, seed, run id and executable, plus the historical M7e set, are refused |
| rule revision 2 | `unit_analysis` | 27-check self-test (every gate and branch, exact-½ boundary incl. the float64 counterexample, undefined T, gate 6 only at n = 3, seed sets); synthetic trees end to end: gate 5a recorded once, gate 6 unlocks exactly seeds 3 / 4 in the registered order, an unverified clear and a missing episode are gate 0 |
| census | `unit_census` | planned versus executed on a synthetic tree, with and without the extension |
| v1 verification unchanged | `unit_historical_verify` | `runs/m7e/m7e_s0_v2` still verifies (31 checkpoint sets) with the Dict-aware inspector; the v1 report has the same shape |
| isolation | `unit_isolation` | no new module references a fixture; only the evaluator imports the recorder; no PPO `learn()` |

## 4. What is proven, and what a real v2 PPO run has not yet exercised

**Proven without training:**
- **The metrics recorder is correct:**
  - on native traces of both fixtures (two stacks, cold and promoted), the TAS clear and untrained / random play;
  - it matches the validated M7f and M7g-a derivations;
  - it keeps 446 / 447 apart.
- **Evaluation orchestration end to end:** provenance, the v1 / v2 worker stacks with metrics, verification, atomic
  labels, clear verification and census.
- **Training orchestration up to the launch:** preflight, gate, order, partial / restart / resume and the extension
  lock, with a stand-in launcher.
- **The decision rule:** every branch, and the report on synthetic trees.
- **v1 behaviour:** unchanged (previous task plus the re-verified M7e run).

**Not yet exercised by any real v2 PPO run.** Update 2026-09-24: the pilot exercised items 1–5 and 7; items 6 and 8
remain (see [`rl_obs_v2_phase_k_pilot_m7g.md`](rl_obs_v2_phase_k_pilot_m7g.md) section 5).
1. A PPO rollout and update on real v2 observations: the Dict rollout buffer with game data, the evolution of the
   per-key statistics, numerical stability.
2. End-to-end v2 throughput and memory under training, including the worker-side spatial parsing [E only].
3. The real trainer's v2 checkpoint cadence (`ckpt_000102400` mid-run + `final`), and M7d's `verify_training_run` on
   a real v2 run. Only synthetic v2 sets have gone through the Dict-aware inspector.
4. `train_once` driving `train_m7.py` for a v2 profile under the live monitor (only a stand-in launcher was used).
5. The metrics recorder on a trained policy's episodes, and the deterministic identical-episode property of a trained
   v2 argmax policy.
6. A genuine v2 → v2 resume (only the guard and the launch arguments were tested).
7. The v1 control's exact reproduction of M7e on the current executable (the pilot's first gate).
8. Clear verification of a real Track 1 clear. None exists; the TAS stands in.

## 5. The smallest safe game-backed pilot before the full comparison

`python rl/m7g_k_run.py manifest` (only if code changed since) → `resources` → `pilot --dry-run` → `pilot`.
It trains; that is the user's decision.

**Status 2026-09-24: run; both steps passed.** It ran as `pilot --arm v1`, then `pilot --arm v2`. Results are in
[`rl_obs_v2_phase_k_pilot_m7g.md`](rl_obs_v2_phase_k_pilot_m7g.md).

| step | profile | budget | passes when | estimate [E] |
| --- | --- | --- | --- | --- |
| P1 control reproduction | `m7g_pilot_s0_v1` | 102,400 transitions (20 rollouts, the first M7e checkpoint) | the final set's policy **and** statistics digests equal `runs/m7e/m7e_s0_v2/checkpoints/ckpt_000102400`; every finished training episode row equals M7e's; the run verifies; its small evaluation (5 deterministic + 20 stochastic, metrics) verifies | ≈ 1.5 min training + ≈ 1 min evaluation + boots |
| P2 v2 pilot | `m7g_pilot_s0_v2` | 204,800 transitions (40 rollouts: one mid-run set + final) | the run verifies (v2 identity, per-key statistics, untrained digest, cadence, ≤ 10 processes, no lifecycle failure, leak-free); throughput and memory recorded (a blocker below 50 % of v1); the small evaluation and clear verification pass | ≈ 3 min training + ≈ 1–2 min evaluation + boots |

Why this is the minimum:
- 102,400 is the smallest point where an M7e reference checkpoint exists, which gives an exact, bit-level reproduction
  gate (gate 0 depends on it).
- 204,800 is the pre-registered v2 pilot and the smallest budget that exercises a mid-run checkpoint set as well as
  `final`. 102,400 would skip that path.
- Both pilots are outside the comparison: `runs/m7g_k/_pilot`, never evaluated as, resumed into or substituted for a
  comparison run.

If P1 fails, the rule is gate 0: stop, diagnose, document, fix, rerun.

## 6. Defects found and fixed in this step (all before any training)

1. **`m7d_run.inspect_vecnormalize` read `obs_rms.mean` directly.** For a v2 run, `obs_rms` is a dict over three keys,
   so M7d's `verify_training_run` (reused for every Phase K run) would have raised on the first checkpoint set.
   - Fix: a Dict branch (per-key counts and finiteness, `norm_obs_keys`); the v1 output is unchanged.
   - Proof: the M7e seed-0 run re-verifies, and synthetic v2 sets pass.
2. **Proposal 6.1 said "float64".** An exact +0.5 can fail in float64 (4.02 − 3.52 = 0.49999999999999956).
   - Fix: the wording now says exact rational arithmetic.
   - `decide()` uses `fractions.Fraction` and tests that very case.
3. **Caught by the new tests during development, never in any campaign code path:** the first provenance check treated
   a recorded `num_timesteps` of 0 as missing.

## 7. Working-tree state

Nothing was committed, pushed, branched or fetched.

- **Parent** (`main` at `afa42fc`). Modified tracked files:
  - `rl/experiment_config.py`, `rl/m7_trainer.py` (both from the readiness task, unchanged in this step);
  - `rl/m7_evaluation.py` (readiness + this step);
  - `rl/btt_parallel.py`, `rl/m7d_run.py` (this step);
  - the docs `rl_obs_v2_experiment_proposal_m7g.md`, `rl_observation_v2_m7g.md`, `rl_experiment_configuration_m7b.md`.

  Untracked files:
  - `rl/configs/m7g/` (6 comparison + 4 extension profiles + `pilot/` with 2);
  - `rl/m7g_k_tests.py`, `rl/m7g_eval_metrics.py`, `rl/m7g_k_matrix.py`, `rl/m7g_k_run.py`, `rl/m7g_k_analysis.py`,
    `rl/m7g_k_campaign_tests.py`;
  - the docs `rl_obs_v2_phase_k_readiness_m7g.{md,json}`, `rl_obs_v2_phase_k_manifest_m7g.json`,
    `rl_obs_v2_phase_k_campaign_m7g.{md,json}`.
- **decomp**: clean on `rl-main` at `3c7fd5d05` (= `origin/rl-main`). **libultraship**, **torch**: unchanged. No
  submodule change, so an eventual commit is parent-only.
- **Untouched:** native code and the executable (`1e7c62a0…`), the M7g-a fixtures, gameplay, rewards, Track 1 actions,
  stepping, `btt_policy_obs_v1`, the six comparison profiles, every earlier profile.
- Test output lives under `runs/m7g_k/` (git-ignored). The campaign directories themselves (runs, `_eval`, `_clears`,
  `_matrix`, `_pilot`) do not exist yet.
