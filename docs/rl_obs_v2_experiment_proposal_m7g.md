# RL M7g Phase K: controlled learning comparison, `btt_policy_obs_v1` vs `btt_policy_obs_v2_spatial`

Status (2026-09-23): **proposed and pre-registered; not run.** No model has been trained on either contract for this
comparison, and no training data of it exists. This document fixes the design and the decision rule before any
exists. The observation is specified and validated in [`rl_observation_v2_m7g.md`](rl_observation_v2_m7g.md).

## 1. Question

Does giving the policy structured perception of the stage change what it learns, at the M7e budget and with
everything else held constant? The structured perception is v2: the collision segments, the live targets by stable
ID, and the moving platform's position and velocity, all Mario-relative.

The concrete target is the M7f ceiling. No v1 policy has ever entered the left region or broken target 1, 6 or 8
(3,074 replayed sequences). v2 is the first input that tells the policy *which* targets remain and *where* they and the
platform are.

## 2. Arms

| | control | experimental |
| --- | --- | --- |
| observation | `btt_policy_obs_v1` (15 float32) | `btt_policy_obs_v2_spatial` (Dict, 525 values; `state` = the v1 vector) |
| policy | SB3 `MlpPolicy`, `net_arch [64, 64]`, tanh | SB3 `MultiInputPolicy` (CombinedExtractor = flatten), `net_arch [64, 64]`, tanh |
| VecNormalize | `norm_obs=True` (the Box), `norm_reward=False`, clip 10 | `norm_obs=True`, `norm_obs_keys = [segment_geometry, state, target_geometry]`, `norm_reward=False`, clip 10 |
| native flags | `SSB64_RL_NO_RENDER=1`, `SSB64_RAPHNET_DISABLE=1` | the same + `SSB64_RL_SPATIAL=1` (read-only; proven gameplay-neutral) |

**The only architecture adjustment is documented and strictly required.** SB3 rejects a Dict space under
`MlpPolicy`. `MultiInputPolicy` with the default `CombinedExtractor` flattens the keys (0 parameters), feeding the
same two 64-unit tanh layers per head. The only differences are the input width (15 → 525; parameters 11,538 →
76,818) and the per-key normalisation (binary keys are not normalised). Fresh models only.

## 3. Held constant

Everything is identical to the M7e v2-reward runs (`rl/configs/m7e/m7e_s{0,1,2}_v2.toml`):

- **Reward:** `btt_reward_v2` (+1 per target, −0.001 per step, +10 clear, −5 native failure), unchanged.
- **Actions:** Track 1 `btt_s9_b8_v1`, MultiDiscrete [9, 8].
- **PPO:**
  - learning rate 3e-4, rollout 5,120 (N=5 × n_steps 1,024), batch 512, 10 epochs;
  - γ 0.999, λ 0.995, clip 0.2, entropy 0.0, value 0.5, max grad norm 0.5;
  - `torch_threads 1`, CPU.
- **Seeds:** 0, 1, 2 (base seeds; Python / SB3 only, never the game).
- **Budget:** **3,072,000 transitions per run, hard maximum**, with no extension inside this experiment.
- **Lifecycle:** N = 5 workers, standby on (one active + one standby per worker, ≤ 10 BattleShip processes), job
  object, isolated worker directories.
- **Episodes:** horizon 3,600 native ticks; full task from tick 0 (non-consuming reset observation; the first action
  consumes tick 0); no curriculum, no prefix, no start-state manipulation.
- **Checkpoints:** every 102,400 transitions (30 + final).
- **Evaluation:** post-hoc only (section 4), identical for both arms.
- **Artifacts:** canonical native actions preserved per the M7e policy; every evaluation episode preserved.

**Excluded in any form:**
- route hints, target order, TAS demonstrations;
- the M7g-a crossing fixtures (as demonstrations, prefixes, start states, shaping, labels or archive seeds);
- reward v3, reward normalisation, RNG seed checking.

## 4. Evaluation protocol (both arms, identical)

- **Points:** `initial`, then every 307,200 transitions (9 intermediate), then `final` (3,072,000).
- **Episodes:**
  - stochastic: 100 at `initial` and `final`, 60 at each intermediate point;
  - deterministic: 100 at `initial` and `final`, 5 at each intermediate point.

  That is 985 per seed per arm, plus one shared 100-episode random baseline, **5,910 + 100 evaluation episodes**.
- **Frozen normalisation:** statistics loaded from the evaluated checkpoint, `training=False`, never updated.
- **Metric instrumentation:**
  - both arms are evaluated with `SSB64_RL_TARGET_DIAG=1` (`btt_target_identity_v1`, proven gameplay-neutral), so
    target identity comes from one identical source;
  - the v2 arm also sets `SSB64_RL_SPATIAL=1`, which its observation requires;
  - left-region entry is computed from native positions against the geometry-derived boundary `position_x < −2100`.
    It is an evaluation metric only, never part of any observation or reward.
- **Clear verification:** every clear is natively re-validated by replaying its canonical actions on a fresh process
  from tick 0 (the M7e §6.5 procedure). `completion_time_passed` and `completion_input_tick` are reported as two
  separate values, never collapsed and never decremented.

## 5. Metrics

Reward is diagnostic only. All metrics are per seed and per evaluated point, with seed-cluster statistics across
seeds.

| # | metric | definition |
| --- | --- | --- |
| 1 | verified clears | clears that reproduce natively (section 4) |
| 2 | targets for incomplete runs | mean targets broken over stochastic episodes that did not clear |
| 3 | faster completion among clears | `completion_time_passed` of verified clears (and `completion_input_tick`, separately) |
| 4 | first native left-region entry | first evaluated checkpoint with any episode reaching `position_x < −2100`; per episode, the first entry tick |
| 5 | first break of IDs 1, 6 or 8 | first evaluated checkpoint with any such break (M7f break records) |
| 6 | frequency of left-region entry | fraction of stochastic episodes with an entry, per point |
| 7 | frequency of each left target | break rate of IDs 1, 6 and 8 separately |
| 8 | seven-target episodes | count and rate of episodes breaking ≥ 7 targets |
| 9 | moving-target ID 2 break rate | per point |
| 10 | cross-seed reproducibility | per-seed curves; sign agreement of the arm difference across seeds |
| 11 | deterministic collapse | `collapse_share` of the deterministic play (M7e definition) |
| 12 | throughput and resource cost | end-to-end transitions/s, wall time, peak memory, process count, disk |

## 6. Pre-registered decision rule

Evaluated at the `final` point, after all runs and evaluations have completed. D is the seed-paired difference v2 −
v1 in metric 2, i.e. mean targets for incomplete stochastic runs (100 episodes per arm per seed). Gate 0 pre-empts all
others. Gates 1–5 are mutually exclusive and are applied in order: the first that matches decides.

| gate | condition (all measured at `final` unless stated) | pre-registered response |
| --- | --- | --- |
| **0: integrity** | any lifecycle or replay regression: process count > 10, port or process leak, a preserved artifact that does not reproduce, a changed user-configuration sha256, `git diff --check` failure. Or the v1 control does not reproduce the M7e run of the same seed (section 7.2) | Stop. No gameplay conclusion from either arm. Diagnose, document under `docs/bugs/`, fix, re-verify, then rerun. |
| **1: clear** | ≥ 1 verified clear in the v2 arm and none in the v1 arm | v2 becomes the Track 1 observation. Preserve the clear and its checkpoint permanently; reproduce the clear at a second seed before any other change. |
| **2: ceiling broken** | the v2 arm shows a native left-region entry in the `final` stochastic evaluation of ≥ 2 of 3 seeds, **or** breaks ≥ 1 of IDs 1/6/8 in ≥ 2 of 3 seeds; and the v1 arm shows neither in any seed | v2 is adopted for Track 1. The ceiling is shown to be a perception limitation, at least in part. The frontier curriculum (M7f category D) is redesigned on top of v2, not v1. |
| **3: better targets, ceiling intact** | D > 0 in all 3 seeds and mean D ≥ +0.5 targets, with no left-region entry in either arm | v2 is preferred on objective rank 2 and becomes the base observation for the next milestone. The ceiling needs an exploration intervention (category D) regardless. |
| **4: seed disagreement** | at least one seed has D ≥ +0.5 and at least one has D ≤ −0.5 | No aggregate claim. Add seeds 3 and 4 to **both** arms at the same budget before any conclusion; decide on five seeds with this same table. |
| **5: no benefit / worse** | none of 1–4 | v1 stays the default. v2 stays available, unchanged and documented. Record "no measurable benefit of structured perception at 3.072M transitions". If D ≤ −0.5 in all 3 seeds, record v2 as *worse* for this architecture. The next milestone proceeds with category D on v1. |

**Reported with every gate, never gating on its own:**
- metrics 4–12;
- deterministic collapse per arm (`collapse_share ≥ 0.5` in ≥ 2 seeds is reported as an evaluation-mode property);
- the throughput cost.

If v2's end-to-end throughput falls below 50 % of v1's, the cost is flagged as a blocker for longer v2 runs, whatever
gate applies.

**Statistics:**
- per seed, the paired difference in episode means with a 95 % bootstrap interval over episodes;
- across seeds, the three seed-level differences themselves (seed is the unit of replication; no pooled episode-level
  test decides a gate);
- no p-value thresholds beyond the pre-registered effect size and sign-agreement rules above.

## 7. Prerequisites (each verified before any training starts)

1. **Trainer / config / evaluator integration** (the unresolved Phase I choice).
   - Recommended: small behaviour-preserving hooks, route A.
     - `rl/experiment_config.py`: `btt_policy_obs_v2_spatial` as an observation choice; `MultiInputPolicy` as a policy
       choice; a cross-field rule tying them together.
     - `rl/m7_trainer.py`: the worker factory, `norm_obs_keys`, the policy name, dict-aware `obs_rms` bookkeeping, the
       contracts.
     - `rl/m7_evaluation.py`: dict-aware statistics digest and the v2 worker factory.
   - New profiles `rl/configs/m7g/m7g_s{0,1,2}_{v1,v2}.toml`.
   - Required proof:
     - every existing profile's semantic and compatibility fingerprints are unchanged;
     - the v1 path is byte-identical;
     - the M7b / M7c / M7d / M7e / M7f / M7g test suites pass.
2. **Control reproduction.** Before the full runs, the v1 control's first 102,400 transitions at seed 0 must reproduce
   the M7e seed-0 run's episode statistics exactly (seeded reproducibility has held since M7c). If it does, the M7e
   runs *may* stand in for the control arm to save about 4.5 h (training + evaluation). The pre-registered default is
   nevertheless a **fresh control on the same build**, so both arms share code, executable and evaluation tooling.
3. **Pilot.** One v2 seed for 204,800 transitions, to measure end-to-end throughput, memory and stability, with no
   evaluation claims.

## 8. Estimated cost [E]

| item | estimate | basis |
| --- | --- | --- |
| v1 training, 3 seeds | ≈ 2.2 h | M7e: 3.072M / 1,168.6 transitions/s ≈ 44 min per seed |
| v2 training, 3 seeds | ≈ 2.5–2.9 h | environment side measured at 85–90 % of v1, and update compute ≈ 1.4× v1 (estimate) |
| evaluation, 6,010 episodes | ≈ 4.5–5 h | M7e: 2.71 s per episode; v2 episodes slightly slower |
| **total wall** | **≈ 9.5–10 h** (≈ 5 h if M7e stands in for the control) | sequential, one run at a time, ≤ 10 game processes |
| peak memory | ≈ 1.7 GB | M7e measurement; the v2 rollout buffer adds about 10 MiB |
| disk | ≈ 2.8 GB | M7e: about 1.4 GB per arm including preserved evaluation episodes |

## 9. What this experiment cannot show

- **One stage only.** Mario's stage, so no claim about generalisation across stages. v2's static geometry is constant
  here.
- **One network.** A null result does not rule out richer encoders, such as a set encoder or a CNN over a grid.
- **Perception only.** A null result does not show perception is irrelevant: the ceiling may be an exploration problem
  that perception alone cannot solve at this budget, which is why gate 5 routes to category D.
