# RL M7g Phase K readiness: observation-v2 wiring, identity, decision rule and cost

Status (2026-09-23): **wired and validated without training; Phase K not launched.** No model was trained or
fine-tuned, no `learn()` ran, no PPO run was started. The pre-registered design and the tightened decision rule
(revision 2) are in [`rl_obs_v2_experiment_proposal_m7g.md`](rl_obs_v2_experiment_proposal_m7g.md); the observation
contract is [`rl_observation_v2_m7g.md`](rl_observation_v2_m7g.md). Machine-readable record:
[`rl_obs_v2_phase_k_readiness_m7g.json`](rl_obs_v2_phase_k_readiness_m7g.json).

Legend: **[M]** measured in this task or recorded by an earlier milestone (source named), **[E]** estimate.

## 0. Summary

- **Wiring (route A, no duplicated trainer).** `contracts.observation = "btt_policy_obs_v2_spatial"` with
  `ppo.policy = "MultiInputPolicy"` now selects the v2 worker stack, VecNormalize over the three continuous keys,
  the v2 run contracts and a recorded network identity. `btt_policy_obs_v1` stays the default of every profile,
  `M7Config` and evaluation.
- **Two concrete v2 defects found and fixed before any training** (both would have hit the first v2 run):
  1. the trainer built `VecNormalize` without `norm_obs_keys`, so SB3 would have normalised *all five* keys,
     including the binary `segment_kind` and `target_live` (reproduced: both keys came back transformed);
  2. `save_checkpoint_set` and the evaluator's statistics digest read `vecnorm.obs_rms.count`, which raises
     `AttributeError` for a Dict observation (`obs_rms` is a dict): the first v2 checkpoint would have crashed the run.
- **Identity.** Checkpoints, `model.zip`, `run.json` and evaluation records carry the observation contract (and, for v2,
  its digest and the measured network); a v1 set is never loaded, resumed or evaluated as v2 or vice versa — refused
  by contracts, stored model space / policy class, and statistics keys, before any directory or process exists.
- **v1 unchanged.** All 13 existing profiles keep their source, semantic and compatibility fingerprints, summaries,
  resolved JSON, dry-run text and contracts; the trainer helpers rebuild the pinned untrained-policy digest; the hooked
  evaluator reproduces a recorded M7e evaluation (1 deterministic + 5 stochastic episodes) exactly; a v1
  `checkpoint.json` has exactly the M7e key set.
- **Decision rule tightened** (proposal section 6, revision 2): both-arm clears, exact `D` / `D̄` definitions and
  inclusive thresholds, single-seed events, and one extension of exactly seeds 3 and 4 in both arms with a hard
  maximum of 10 runs / 30,720,000 transitions / 9,950 evaluation episodes.
- **Not ready to launch yet:** the recorder for metrics 4–7 (left-region entry, IDs 1/6/8), the Phase K orchestration,
  and the two training prerequisites (control reproduction, v2 pilot) are open (section 7).

## 1. State confirmed before editing

| item | finding |
| --- | --- |
| parent working tree | clean at `afa42fc` (`main`) |
| M7g commit state | **already committed and pushed**, contrary to the task brief: decomp `3c7fd5d05` on `rl-main` equals `origin/rl-main`; parent `afa42fc` equals `origin/main` (local tracking refs; nothing was fetched). `afa42fc` contains the decomp gitlink **together with** every M7g-a and M7g-b file, not the gitlink alone as intended. That history was left untouched |
| decomp | clean on `rl-main` at `3c7fd5d05`; `libultraship` `805f1950` (`m6/raphnet-bypass`), `torch` `3aa9c973`: unchanged |
| executable | `build-us/Release/BattleShip.exe` sha256 `1e7c62a0…` = the M7g-b build recorded in `rl_observation_v2_m7g_validation.json` |
| crossing fixtures | `rl/fixtures/m7g/lower_precision_2ad7b1da89d8.json` sha256 `18446e2b…`, `upper_moving_platform_8b9ecf2b967f.json` sha256 `adfd9eda…`, committed in `afa42fc`, unmodified before and after this task; `m7g_tests unit` 9/9 (incl. `unit_fixture_files`, `unit_training_isolation`) before editing |
| observation v2 | `m7g_obs_tests unit` 8/8 before editing (incl. `unit_sb3_dummy`, `unit_offline_traces`) |
| frozen contracts | Track 1 `btt_s9_b8_v1` MultiDiscrete [9, 8], `btt_policy_obs_v1` (15 float32), rewards v1 / v2 with normalisation off: untouched; guarded by `m7g_obs_tests unit_contract`, `m7b_config_tests` and the suites in section 4 |

## 2. Completed wiring

| file | change (all opt-in; v1 defaults) |
| --- | --- |
| `rl/experiment_config.py` | `contracts.observation` ∈ {`btt_policy_obs_v1`, `btt_policy_obs_v2_spatial`}; `ppo.policy` ∈ {`MlpPolicy`, `MultiInputPolicy`}; cross-field rules: observation ↔ policy, v2 requires `normalize_observations = true` and the validated network (`[64, 64]`, `tanh`); v2 derives `SSB64_RL_SPATIAL=1` in `extra_env`; v2-only `policy_observation` identity block in `summary()`, `resolved_json()` and the dry run |
| `rl/m7_trainer.py` | `M7Config.observation` / `.policy` (+ validation); helpers `run_contracts`, `worker_factory`, `vecnormalize_keys`, `make_vecnormalize`, `make_model`, `annotate_model`, `policy_network_identity`; `M7Run` uses them for fresh runs (keeping the literal `VecNormalize(self.venv, training=True, norm_obs=c.norm_obs, norm_reward=False, …)` that the M7d / M7e source guards pin, plus `**vecnormalize_keys(c)`), resume (contracts compared, then statistics and model identity checked) and in-training evaluation; per-key statistics record in `checkpoint.json`; v2-only `policy_network` in `run.json` / `checkpoint.json` and `m7_policy_observation` in `model.zip` |
| `rl/m7_evaluation.py` | dict-aware `obs_rms_digest` (v1 bytes unchanged) and `obs_rms_record`; `EvaluationSettings.observation` (None = the checkpoint's own); `checkpoint_observation_contract`, `check_model_identity`, `check_vecnormalize_identity`; `evaluate_checkpoint` evaluates under the checkpoint's own observation, adds the spatial flag for v2, and checks contract, model and statistics before creating its directory; v2 worker factory in `_prepare_workers`; v2-only record keys |
| `rl/configs/m7g/m7g_s{0,1,2}_{v1,v2}.toml` | the six Phase K profiles: body of `rl/configs/m7e/m7e_s{s}_v2.toml`; v1 arm changes only output fields; v2 arm also `contracts.observation`, `ppo.policy` |
| `rl/m7g_k_tests.py` | the readiness suite (6 unit + 3 game cases, no training) |
| docs | this report + JSON; proposal revision 2; short status notes in `rl_observation_v2_m7g.md` and `rl_experiment_configuration_m7b.md` |

**What a v1 record looks like now.** Identical to before except `M7Config.to_json()` (the `config` block of `run.json` /
`training_summary.json` and `m7d_matrix.trainer_view`) gains two descriptive keys, `"observation": "btt_policy_obs_v1"`
and `"policy": "MlpPolicy"`. No fingerprint, contract, `checkpoint.json` key, `model.zip` attribute, VecNormalize
file or evaluation row changes. A refused evaluation now fails before its output directory is created (previously a
failing model load left an empty directory).

**Why v2 needs no TOML key for the flag or the keys.** `SSB64_RL_SPATIAL=1` and
`norm_obs_keys = [segment_geometry, state, target_geometry]` are part of the v2 observation contract (digest
`dcfd14b2…`), so they are derived, recorded and compared, never configured: a TOML key for either is rejected as
unknown.

## 3. Coverage audit (task step 3)

| property | covered before this task (M7g-b) | gap | now covered by |
| --- | --- | --- | --- |
| v2 SB3 initialisation | `unit_sb3_dummy`, `game_sb3_real` via `m7g_policy.make_model` | never through the trainer | `unit_checkpoint_identity`, `unit_update_path`, `game_wiring_smoke` via `m7_trainer.make_model` (76,818 / 11,538 parameters) |
| save / reload | plain `PPO.save` / `VecNormalize.save` | **`save_checkpoint_set` and `obs_rms_digest` crashed on Dict statistics** | fixed; `unit_checkpoint_identity` (digests, predictions, values, frozen statistics), `game_wiring_smoke` (real checkpoint set, CLI evaluation) |
| normalisation of continuous keys only | `m7g_policy.make_vecnormalize` with `norm_obs_keys` | **the trainer passed no `norm_obs_keys` → binary keys normalised** | fixed (`make_vecnormalize`); checked offline and on the real N=5 standby stack |
| PPO update on the Dict buffer | none ("no backward pass was run") | backward pass / `DictRolloutBuffer` untested | `unit_update_path` (synthetic data, throwaway models) |
| v2 evaluation | offline frozen evaluation only | evaluator ran the v1 stack only | `game_wiring_smoke` (`eval_m7.py --config`), `game_target_diag_probe` |
| cross-contract refusal | `assert_v2_checkpoint`, SB3 space check | not at resume / evaluation / CLI level | `unit_config_rejections`, `unit_checkpoint_identity` (incl. tampered sets), `game_wiring_smoke` cross `--config` |

## 4. Validation (commands and outcomes)

Final verification pass, run on the final code, sequentially, from the repository root; output under
`runs/m7g_k/_final_20260924T000212Z/`:

| suite | command | result |
| --- | --- | --- |
| Phase K readiness | `python rl/m7g_k_tests.py` | **9/9 PASS** (6 unit + 3 game), 189 s |
| M7b configuration | `python rl/m7b_config_tests.py` | 16/16 PASS |
| M7e unit | `python rl/m7e_tests.py unit` | 10/10 PASS |
| M7d unit | `python rl/m7d_tests.py unit` | 9/9 PASS |
| M7c standby unit | `python rl/m7c_standby_tests.py unit` | 4/4 PASS |
| M7 smoke unit | `python rl/m7_smoke.py unit` | 8/8 PASS |
| M7g-a fixtures unit | `python rl/m7g_tests.py unit` | 9/9 PASS (both fixture files validated) |
| observation v2 unit | `python rl/m7g_obs_tests.py unit` | 8/8 PASS |
| profile identity snapshot | before / after comparison of all profiles (scratch script) | only the 6 new profiles and the two `trainer_view` keys per existing profile differ |
| `git diff --check` | parent and decomp | clean |

What the readiness cases establish (task step 7):

| requirement | case(s) | evidence |
| --- | --- | --- |
| strict config rejection | `unit_config_rejections` | 11 TOML mutations rejected with the offending field named (v2 + `MlpPolicy`, v1 + `MultiInputPolicy`, unknown / wrong-case observation, unknown policy, v2 without observation normalisation, other net_arch, relu, `norm_obs_keys` or a spatial flag written in the TOML, reward normalisation); 7 inconsistent `M7Config`s rejected; a v2 configuration resuming from the historical v1 M7e final set is refused before any file is created |
| v1 default behaviour | `unit_existing_profiles`, `game_v1_historical_eval` | 13/13 pinned fingerprints; untrained digests `68155f41…` / `06b1b370…` via the new helpers; `M7Config()` defaults to v1; the evaluator reproduces M7e seed 0's final deterministic episode (`868152fa…`, 2 targets, horizon) and its first five stochastic episodes (digests, ranks, targets) exactly, with frozen statistics |
| explicit v2 selection | `unit_phase_k_profiles` | pair proofs per seed, v2 identity blocks, v2 trainer config, v2 worker factory, six dry runs exit 0 |
| save / reload, normalisation | `unit_checkpoint_identity` | per arm: parameters, statistics digest and deterministic actions / values identical after reload; statistics frozen while stepping; v2 binary keys raw and continuous keys normalised |
| evaluator compatibility and identity | `unit_checkpoint_identity`, `game_wiring_smoke` | 12 refusals (contracts, model space, statistics keys, evaluator settings, tampered sets whose hashes were re-recorded) with no directory created and no process launched; `eval_m7.py --config` evaluates each arm's checkpoint (frozen), and a cross-arm `--config` exits 2 before creating output |
| no-training smoke | `game_wiring_smoke`, `game_target_diag_probe` | exact seed-0 profiles, N=5 with standby: 200 vector steps of the untrained stochastic policy, `num_timesteps` 0, `_n_updates` 0, peak 10 processes, none left; evaluation with `SSB64_RL_TARGET_DIAG=1` added runs for both arms |
| update path | `unit_update_path` | `DictRolloutBuffer` for v2, three updates per arm, finite losses, parameters changed (throwaway models, never saved) |

Also confirmed after the pass: fixture sha256 unchanged, executable `1e7c62a0…` unchanged, user configuration
`BattleShip.cfg.json` sha256 `1b29d91b…` (as recorded by M7g-b), zero BattleShip processes.

Not run, by scope: any PPO training (so neither the control reproduction nor the pilot), the full M1–M7f regression
chain (no native, decomp, stepping, reward or observation-v1 change; the risk was confined to the three Python modules,
covered by the suites above), and a C++ build (no C or C++ file changed).

## 5. Measured evidence [M]

**Identity and network.**

| | v1 arm | v2 arm |
| --- | --- | --- |
| observation / policy | `btt_policy_obs_v1` / `MlpPolicy` (`ActorCriticPolicy`) | `btt_policy_obs_v2_spatial` / `MultiInputPolicy` (`MultiInputActorCriticPolicy`, `CombinedExtractor`, 525 features) |
| parameters | 11,538 | 76,818 |
| native flags | `SSB64_RL_NO_RENDER=1`, `SSB64_RAPHNET_DISABLE=1` | the same + `SSB64_RL_SPATIAL=1` |
| VecNormalize | one Box statistic (15) | `segment_geometry`, `state`, `target_geometry`; binary keys raw |
| untrained policy digest, seed 0 | `68155f41…` (= M7d / M7e seed 0) | `a968777d…` |
| `model.zip` / `vecnormalize.pkl` | ≈ 67 KB / 2.5 KB | ≈ 336 KB / 23.5 KB |
| `checkpoint.json` keys | exactly the 26 keys of M7e's | the same 26 + `policy_network` |
| compatibility fingerprint (all seeds) | `ac622dfa…` = M7e's | `7b9cfd18…` |
| semantic fingerprints, seeds 0 / 1 / 2 | `d8d993ea…` / `dd87c6c0…` / `684dc27a…` (= `m7e_s{0,1,2}_v2`) | `7ebf0694…` / `c9bdb636…` / `b9286221…` |

**Profiles.** The v1 profile of each seed has the semantic and compatibility fingerprints of `m7e_s{seed}_v2`; it
differs from it only in `run.name`, `run.notes` and `run.output_root`. The v2 profile differs from the v1 profile of
the same seed only in `run.name`, `run.notes`, `contracts.observation` and `ppo.policy`; its compatibility view differs
in exactly `contracts.observation`, `ppo.policy` and the derived `environment.extra_env` (not a lifecycle-only
difference, so `resume.allow_lifecycle_change` cannot bridge it). Six distinct semantic fingerprints, one
compatibility fingerprint per arm.

**Compute (this task, single torch thread, synthetic inputs, throwaway models; two runs of `unit_update_path`, the
second being the final verification run).**

| | v1 | v2 | v2 / v1 |
| --- | --- | --- | --- |
| rollout inference per vector step (5 observations) | 0.80 ms | 0.88–0.90 ms | 1.10–1.13 |
| PPO update per rollout (5,120 transitions, 10 epochs × 10 minibatches), median of 3 | 0.489–0.494 s | 0.736–0.745 s | 1.50–1.51 |
| minibatch forward (512 samples, `evaluate_actions`, no gradient) | 1.42–1.52 ms | 2.36–2.66 ms | 1.56–1.88 |
| rollout-buffer observations | 0.29 MiB | 10.25 MiB | 35 |

Cross-check against real training: M7e's in-training v1 update was 0.466–0.478 s per rollout and its inference
0.855–0.874 ms per vector step, both within a few percent of the synthetic v1 figures, which is why the synthetic v2
figures are used as the basis of the v2 estimates. The timing is one machine at one moment; the `final_metrics` of the
synthetic update are finite by assertion and carry no meaning.

**Environment and runs (earlier milestones).**
- M7g-b N=5 standby environment bench (random actions, no policy): v2 = 89.5 % and 85.4 % of v1 in two runs.
- M7e v1 training, 3,072,000 transitions: 35.3–36.0 min of `learn()`, 1,424–1,452 tr/s end to end, 3.05–3.11 s
  collection + 0.466–0.478 s update per rollout; working set 1.59 GiB, commit 4.96 GiB (campaign drew 5.46 GiB).
- M7e evaluation: 2,955 episodes in 1.76 h of session wall, **2.145 s per episode** (revision 1 of the proposal quoted
  M7d's 2.71 s as "M7e").
- M7e disk per seed: run directory 41–42 MiB; evaluation 347–715 MiB.
- Smoke (this task): the exact seed-0 profiles at N=5 with standby peaked at 10 BattleShip processes per arm and left
  none; eval with `SSB64_RL_TARGET_DIAG=1` ran cleanly for both arms (2 stochastic episodes each, no lifecycle failure).

## 6. Estimates [E]

The full table is proposal section 8. Headline figures, all **estimates**:

| item | v1 arm | v2 arm |
| --- | --- | --- |
| one 3,072,000-transition run | ≈ 36 min (M7e-measured) | ≈ 41–45 min (≈ 1,150–1,250 tr/s, 79–87 % of v1) |
| training, 3 seeds | ≈ 1.8 h | ≈ 2.1–2.3 h |
| evaluation, 2,955 episodes | ≈ 1.8 h | ≈ 2.0–2.1 h |
| memory | 1.59 GiB WS / 4.96 GiB commit (M7e-measured) | ≈ 1.61 GiB / ≈ 5.0 GiB; gate each run on ≥ 6.0 GiB available commit |
| disk | ≈ 1.5 GiB | ≈ 1.6 GiB |

Whole experiment, 3 seeds per arm + 100 random: **≈ 7.6–7.9 h** sequential plus orchestration, clear verification and
the metric recorder. Gate-6 extension (seeds 3 and 4, both arms): **≈ +5.0–5.2 h**, experiment maximum ≈ 12.7–13.1 h,
10 runs, 30,720,000 transitions, 9,950 evaluation episodes. Worker-side v2 memory and v2 end-to-end throughput are not
measured; the pilot (proposal 7.5) measures them.

## 7. Open prerequisites and unresolved risks

*Update 2026-09-24:*
- Items 1 (metric recorder) and 2 (orchestration) below are done: see
  [`rl_obs_v2_phase_k_campaign_m7g.md`](rl_obs_v2_phase_k_campaign_m7g.md).
- Item 3 is prepared as `python rl/m7g_k_run.py pilot`, which still needs the user's go-ahead because it trains.
- Item 8 still applies to `eval_m7.py`, but the Phase K driver passes the standby settings.

**Blocking the launch (proposal section 7):**
1. **Metric recorder for metrics 4–7.** The evaluator records `target_break_ticks` but not target IDs or left-region
   entry, so gates 4 and the ceiling metrics cannot be computed from evaluation output today. Both arms were shown to
   run with `SSB64_RL_TARGET_DIAG=1`; the recorder itself (worker-side, additive, or post-hoc M7f replays) must be
   chosen, built and validated.
2. **Phase K orchestration**: manifest with pair proofs, run / evaluation drivers with the resource monitor, clear
   verification, and an analysis that implements revision 2 of section 6.
3. **Control reproduction** (102,400 v1 transitions at seed 0 against M7e) and the **v2 pilot** (204,800 transitions):
   both need training, which this task excluded.

**Wired but not exercised on the game** (each needs a training step to reach):
4. In-training evaluation of a v2 run (`evaluation.interval > 0`): the Phase K profiles keep it off; the path shares
   `evaluate_checkpoint`, which was exercised.
5. Resuming a v2 run from a v2 checkpoint: identity checks are in place and the cross-contract refusal was tested; a
   genuine v2 → v2 resume needs a trained v2 checkpoint.
6. A full PPO rollout + update on the real v2 environment: the update path ran only on synthetic data; the pilot is
   the first real one.

**Risks and notes:**
7. v2 end-to-end throughput and worker-side memory are estimates; the pilot measures them. If v2 falls below 50 % of
   v1, the proposal flags a blocker for longer runs.
8. `eval_m7.py --config` still does not pass the standby settings (a pre-existing M7d finding): CLI evaluations run
   cold. A Phase K evaluation driver should pass them, as M7e's did; results are identical either way by the M7c
   equivalence.
9. The teardown hold-last path of the v2 builder is still exercised only synthetically (M7g-b limitation).
10. `guide.md` (outside the repository) was not updated by this task.
11. History: `afa42fc` bundles the decomp gitlink with the M7g files (not the intended gitlink-alone commit). Nothing
    was rewritten. This task changes no submodule, so its eventual commit is parent-only.

## 8. Working-tree state

Nothing was committed, pushed, branched or fetched.

- **Parent** (`main` at `afa42fc`):
  - modified: `rl/experiment_config.py`, `rl/m7_trainer.py`, `rl/m7_evaluation.py`,
    `docs/rl_obs_v2_experiment_proposal_m7g.md`, `docs/rl_observation_v2_m7g.md`,
    `docs/rl_experiment_configuration_m7b.md`;
  - new: `rl/configs/m7g/m7g_s{0,1,2}_{v1,v2}.toml` (6), `rl/m7g_k_tests.py`,
    `docs/rl_obs_v2_phase_k_readiness_m7g.md`, `docs/rl_obs_v2_phase_k_readiness_m7g.json`.
- **decomp**: clean on `rl-main` at `3c7fd5d05` (= `origin/rl-main`); **libultraship**, **torch**: unchanged.
- **Untouched**: native code, the executable (`1e7c62a0…`), the M7g-a fixtures, gameplay, rewards, Track 1 actions,
  stepping, `btt_policy_obs_v1`, every existing profile.
- Test output lives under `runs/m7g_k/` (git-ignored).
