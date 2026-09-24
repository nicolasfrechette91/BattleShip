# RL M7g Phase K: controlled learning comparison, `btt_policy_obs_v1` vs `btt_policy_obs_v2_spatial`

Status (2026-09-23): **proposed and pre-registered; not run.** No model has been trained on either contract for this
comparison, and no training data of it exists. This document fixes the design and the decision rule before any
exists. The observation is specified and validated in [`rl_observation_v2_m7g.md`](rl_observation_v2_m7g.md).

**Revision 2 (2026-09-23, still before any training or evaluation data):** the decision rule (section 6) is tightened
(both-arm clears, exact definitions of every quantity and threshold, the one permitted seed extension with its exact
seed count and maximum budget); the prerequisites (section 7) record the completed trainer / config / evaluator
integration and what remains before launch; the cost table (section 8) separates measurements from estimates and
corrects the per-episode evaluation figure. Revision 1 is commit `afa42fc`. The readiness evidence is in
[`rl_obs_v2_phase_k_readiness_m7g.md`](rl_obs_v2_phase_k_readiness_m7g.md).

**Campaign preparation (2026-09-24, still before any training):**
- The evaluation metrics recorder, the manifest, the run and evaluation drivers and the analysis implementing section 6
  now exist and were tested without training
  ([`rl_obs_v2_phase_k_campaign_m7g.md`](rl_obs_v2_phase_k_campaign_m7g.md)).
- One wording in 6.1 was corrected before any data: the threshold arithmetic is exact (rational), not float64.
- No gate, threshold, seed, budget or response changed.

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
  - *Revision 2 note:* every evaluation episode of both arms and the random baseline carries a `btt_eval_metrics_v1`
    record (section 7, item 2). The record holds the first native left entry, target IDs with first-break ticks, the
    seven-target flag, the target-2 break, the native clear with both clocks and the termination reason. The
    `SSB64_RL_TARGET_DIAG=1` flag is set in evaluation workers only.
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

Evaluated at the `final` point, after all runs and evaluations have completed.

*Revision 2 replaces the revision-1 table (commit `afa42fc`) with the definitions and gates below. The questions it
answers explicitly: what happens when both arms clear (gate 2), what a single-seed clear or crossing means (gates 3 and
4d), exactly how D and its +0.5 threshold are computed (6.1), and the exact seed count and maximum budget of the one
permitted extension (gate 6). Reward totals remain diagnostic only and never enter a gate.*

#### 6.1 Definitions

All quantities are computed at `final` (3,072,000 transitions) unless stated. `n` is the number of seeds per arm:
3 at first, 5 only after the one permitted extension (gate 6). "Arm" means v1 or v2; "the other arm" is the other one.

| symbol | definition |
| --- | --- |
| final evaluation | 100 stochastic + 100 deterministic episodes of the `final` checkpoint set; evaluation seed 12345; frozen statistics; the first 100 episodes collected per mode in the evaluator's collection order (section 4) |
| verified clear | an episode with end reason `clear` whose canonical native actions, replayed on a fresh process from tick 0, reproduce `completion_time_passed` **and** `completion_input_tick` exactly (two values, never collapsed or decremented). A clear that does not reproduce is a gate-0 integrity failure, not a clear |
| clear seed; `K_a` | a seed whose final evaluation (all 200 episodes) contains ≥ 1 verified clear; `K_a` = number of clear seeds of arm `a` |
| `c_{a,s}` | verified clears among the 100 final **stochastic** episodes of arm `a`, seed `s`, divided by 100 |
| `B_{a,s}` | the minimum `completion_time_passed` over the verified clears of that final evaluation (undefined without a clear) |
| crossing episode | an episode with at least one native post-update observation whose `position_x < −2100` (evaluation metric only; never an observation or reward term) |
| left break | a break of stable target ID 1, 6 or 8 (`btt_target_identity_v1`, M7f) |
| ceiling seed; `X_a` | a seed whose 100 final stochastic episodes contain ≥ 1 crossing episode or ≥ 1 left break; `X_a` = number of ceiling seeds of arm `a` |
| `x_{a,s}` | fraction of the 100 final stochastic episodes that are crossing episodes or contain a left break |
| `T_{a,s}` | mean `targets_broken` over the final stochastic episodes of arm `a`, seed `s` that are **not** verified clears. Undefined if all 100 are verified clears; a seed with an undefined `T` in either arm is decided by the clear gates only and excluded from gate 5 |
| `D_s` | `T_{v2,s} − T_{v1,s}`, in targets per episode, computed **exactly (rational arithmetic) from the integer counts**, never rounded before comparison |
| `D̄` | the unweighted mean of the seed-level `D_s` over the `n` seeds (each seed weight 1; episodes are never pooled across seeds) |
| majority `m(n)` | 2 when `n = 3`; 3 when `n = 5` |

Every threshold is inclusive (`D̄ ≥ +0.5` is met by exactly +0.5). Every quantity that meets a threshold (`D_s`, `D̄`,
the clear-rate and crossing-rate differences) is computed in exact rational arithmetic from the integer episode
counts, and floating point is used only for reporting. *(Corrected before any data, while implementing the rule: the
first wording said "float64", under which an exact tie can fail. For example, T = 4.02 against 3.52 differs by exactly
+0.5 but by 0.49999999999999956 in float64. rl/m7g_k_analysis.py tests this case.)* Bootstrap intervals are reported
and never gate.

#### 6.2 Gates

Gate 0 pre-empts all others. Gates 1–7 are applied in order; the first whose condition holds decides.

| gate | condition | pre-registered response |
| --- | --- | --- |
| **0: integrity** | any lifecycle or replay regression: process count > 10, port or process leak, a preserved artifact that does not reproduce, a clear that fails verification, a changed user-configuration sha256, `git diff --check` failure; any run that did not reach exactly 3,072,000 transitions; any planned evaluation episode missing; or the v1 control does not reproduce the M7e run of the same seed (section 7.2) | Stop. No gameplay conclusion from either arm. Diagnose, document under `docs/bugs/`, fix, re-verify, then rerun. |
| **1: reproduced clear, one arm** | `K_a ≥ m(n)` and `K_other = 0` | Arm `a` is preferred. If `a` = v2: v2 becomes the Track 1 observation. If `a` = v1: v1 stays the default and v2 is recorded as *worse on clears*. Every verified clear and its checkpoint are preserved permanently. |
| **2: both arms clear** | `K_v1 ≥ 1` and `K_v2 ≥ 1` | Decided by the first of these that holds: **(a)** `K_v2 − K_v1 ≥ 2` → v2 preferred; `K_v1 − K_v2 ≥ 2` → v1 preferred. **(b)** paired clear rate: `mean_s(c_{v2,s} − c_{v1,s}) ≥ +0.05` with `c_{v2,s} ≥ c_{v1,s}` in every seed → v2 preferred (mirror → v1 preferred). **(c)** clear time: over the seeds where both arms have a verified clear (at least one such seed), `B_{v2,s} < B_{v1,s}` in every one → v2 preferred (mirror → v1 preferred). **(d)** otherwise a tie: v1 stays the default (the cheaper observation), v2 stays available, and the single fastest verified clear of either arm is the starting point of the next (clear-time) milestone. A preference under (a)–(c) has the consequences of gate 1. Every verified clear is preserved. |
| **3: single-seed clear** | exactly one arm has `1 ≤ K_a < m(n)` and `K_other = 0` | `n = 3`: run the gate-6 extension, then re-apply the table at `n = 5`. `n = 5`: recorded "cleared, not reproduced (K of 5 seeds)"; no adoption on clears; the clears are preserved; continue with gate 4. |
| **4: ceiling** | no gate above decided | **(a)** `X_v2 ≥ m(n)` and `X_v1 = 0` → v2 is adopted for Track 1; the ceiling is shown to be at least partly a perception limitation; the frontier curriculum (M7f category D) is redesigned on v2. **(b)** `X_v1 ≥ m(n)` and `X_v2 = 0` → v1 stays the default; v2 is recorded as *worse at the ceiling*. **(c)** `X_v1 ≥ 1` and `X_v2 ≥ 1` → paired crossing rate: `mean_s(x_{v2,s} − x_{v1,s}) ≥ +0.05` with `x_{v2,s} ≥ x_{v1,s}` in every seed → v2 adopted as in (a); the mirror → v1 as in (b); otherwise continue with gate 5, recording "ceiling broken by both arms". **(d)** exactly one arm has `1 ≤ X_a < m(n)` and `X_other = 0` → `n = 3`: gate-6 extension; `n = 5`: recorded "crossing not reproduced", continue with gate 5. **(e)** `X_v1 = X_v2 = 0` → continue with gate 5. |
| **5: targets** | computed over the seeds with `T` defined in both arms (all `n` if no clear) | **(a)** `D_s > 0` in every such seed and `D̄ ≥ +0.5` → v2 is preferred on objective rank 2 and becomes the base observation of the next milestone; unless gate 4(c) recorded crossings in both arms, the ceiling still needs an exploration intervention (category D). **(b)** `D_s < 0` in every such seed and `D̄ ≤ −0.5` → v2 is recorded as *worse* for this architecture; v1 stays the default. |
| **6: seed disagreement → one extension** | `n = 3` and at least one seed has `D_s ≥ +0.5` and at least one has `D_s ≤ −0.5` (or gate 3 / 4(d) sent the decision here) | No aggregate claim. Train **exactly two additional seeds, 3 and 4, in both arms** with profiles identical except `run.name`, `run.notes` and `run.base_seed`, at the same 3,072,000 transitions and the same evaluation protocol: 4 more runs, **12,288,000 more transitions** and **3,940 more evaluation episodes** (4 × 985). Then re-apply gates 0–7 **once** at `n = 5`. There is no second extension, no budget extension and no additional seed. **Maximum budget of the whole experiment: 10 training runs = 30,720,000 transitions, and 9,850 policy evaluation episodes + 100 random-baseline episodes = 9,950.** |
| **7: no benefit / inconclusive** | none of 1–6 (at `n = 5` gate 6 no longer applies, so a remaining disagreement ends here) | v1 stays the default. v2 stays available, unchanged and documented. Record "no measurable benefit of structured perception at 3.072M transitions" (`n = 3`) or "inconclusive after 5 seeds" (`n = 5`). The next milestone proceeds with category D on v1. |

**Reported with every gate, never gating on its own:**
- metrics 4–12;
- deterministic collapse per arm (`collapse_share ≥ 0.5` in ≥ 2 seeds is reported as an evaluation-mode property);
- the throughput cost;
- diagnostic returns under `btt_reward_v2` (never used to rank arms or checkpoints).

If v2's end-to-end throughput falls below 50 % of v1's, the cost is flagged as a blocker for longer v2 runs, whatever
gate applies.

**Statistics:**
- per seed, the paired difference in episode means with a 95 % bootstrap interval over episodes (reported only);
- across seeds, the seed-level differences themselves (seed is the unit of replication; no pooled episode-level test
  decides a gate);
- no p-value thresholds beyond the pre-registered effect sizes and sign-agreement rules above.

## 7. Prerequisites (each verified before any training starts)

Status per item as of revision 2 (details and evidence: [`rl_obs_v2_phase_k_readiness_m7g.md`](rl_obs_v2_phase_k_readiness_m7g.md)).

1. **Trainer / config / evaluator integration — done (route A), validated without training.**
   - `rl/experiment_config.py`: `btt_policy_obs_v2_spatial` and `MultiInputPolicy` as explicit choices, cross-field
     rules tying observation, policy, observation normalisation and the validated network together; v2 derives
     `SSB64_RL_SPATIAL=1`.
   - `rl/m7_trainer.py`: `run_contracts`, `worker_factory`, `make_vecnormalize` (`norm_obs_keys` for v2),
     `make_model`, `annotate_model`, per-key statistics bookkeeping, v2 network identity in `run.json` /
     `checkpoint.json` / `model.zip`, identity checks on resume.
   - `rl/m7_evaluation.py`: per-key statistics digest, the v2 worker factory, a checkpoint always evaluated under its
     own observation contract, model / statistics / contract identity checked before anything is created.
   - Profiles `rl/configs/m7g/m7g_s{0,1,2}_{v1,v2}.toml`.
   - Proof: every existing profile's source, semantic and compatibility fingerprints unchanged (13 of 13); the v1
     construction path reproduces the pinned untrained-policy and statistics digests; the hooked evaluator reproduces
     a recorded M7e evaluation exactly; the new suite `rl/m7g_k_tests.py` and the affected inherited unit suites pass.
2. **Metric recorder for metrics 4–7 — done (campaign step, 2026-09-24).** It is `btt_eval_metrics_v1`
   (`rl/m7g_eval_metrics.py`), an additive worker-side recorder used by evaluation workers only (`SSB64_RL_TARGET_DIAG=1`
   is set in evaluation, never in training). For every evaluation episode it records:
   - the first native left-region entry (the M7g-a rule);
   - target IDs and their first-break ticks (the M7f `check_trace` derivation, one reply at a time, proved equivalent);
   - seven-target occurrence and the target-2 break;
   - the native clear with both completion clocks;
   - the termination reason.

   It was validated on both M7g-a fixtures (as validation evidence only), on the TAS (entry at consumed tick 359,
   clear 446 / 447) and on non-crossing random and untrained play. Evidence:
   [`rl_obs_v2_phase_k_campaign_m7g.md`](rl_obs_v2_phase_k_campaign_m7g.md).
3. **Phase K orchestration — done (campaign step).** The pieces:
   - `rl/m7g_k_matrix.py`: manifest `docs/rl_obs_v2_phase_k_manifest_m7g.json` with field-by-field proofs;
   - `rl/m7g_k_run.py`: manifest, resource gate, preflight / dry runs, pilot, training, evaluation, clear verification,
     census and analysis;
   - `rl/m7g_k_analysis.py`: this section's rule, literally.

   Sequencing is registered in the matrix. Runs are strictly sequential in the counterbalanced order s0 v1, s0 v2,
   s1 v2, s1 v1, s2 v1, s2 v2, and the extension order is s3 v1, s3 v2, s4 v2, s4 v1. Partial runs follow the explicit
   policy in the campaign document:
   - default: move the partial run aside intact and restart from scratch with the same seed;
   - an explicit own-lineage resume is allowed, but it is recorded as a protocol deviation.
4. **Control reproduction — pending (needs training); prepared as the v1 pilot.** Before the full runs, the v1
   control's first 102,400 transitions at seed 0 must reproduce the M7e seed-0 run exactly:
   - the final set's policy and statistics digests against `runs/m7e/m7e_s0_v2/checkpoints/ckpt_000102400`;
   - every finished training episode row.

   Seeded reproducibility has held since M7c. The profile is `rl/configs/m7g/pilot/m7g_pilot_s0_v1.toml`. If the
   control reproduces, the M7e runs *may* stand in for the control arm to save about 3.6 h (training + evaluation,
   section 8). The pre-registered default is nevertheless a **fresh control on the same build**, so both arms share
   code, executable and evaluation tooling. The v1 profiles have the same semantic and compatibility fingerprints as
   the M7e profiles of their seeds; only the executable differs (M7e predates the M7f / M7g PORT-only diagnostics).
5. **v2 pilot — pending (needs training); prepared.** The profile is `rl/configs/m7g/pilot/m7g_pilot_s0_v2.toml`: seed 0,
   204,800 transitions. It measures end-to-end throughput, memory and stability, and it runs a small post-hoc
   evaluation of its final set (5 deterministic + 20 stochastic episodes with the recorder) with clear verification.
   No claim is drawn from it. Run both pilots with `python rl/m7g_k_run.py pilot`.
6. **Resource gate — both memory figures are gated, separately.** Available system commit (commit limit − commit charge,
   `GlobalMemoryStatusEx.ullAvailPageFile`) must be ≥ 6.0 GiB AND available physical memory (`ullAvailPhys`) must be
   ≥ 2.5 GiB. Also required: free disk ≥ 10 GiB, system CPU ≤ 40 %, no BattleShip process, no listener in the M7 port
   blocks and no `SSB64_*` variable. A missing reading fails its gate. `python rl/m7g_k_run.py resources` reads the
   gate and launches nothing.

## 8. Cost: measurements [M] and estimates [E]

Revision 1's figures used M7d's end-to-end throughput (1,168.6 transitions/s) and M7d's evaluation rate (2.71 s per
episode) where it said "M7e". The M7e measurements are used below.

**Measured [M]:**

| item | v1 | v2 | source |
| --- | --- | --- | --- |
| parameters | 11,538 | 76,818 | real game environment (M7g-b) and the Phase K readiness suite |
| rollout inference per vector step (5 observations) | 0.80 ms | 0.88–0.90 ms | readiness suite (two runs), synthetic inputs; M7e in training: 0.855–0.874 ms (v1) |
| PPO update per rollout (5,120 transitions, 100 minibatch steps) | 0.489–0.494 s | 0.736–0.745 s | readiness suite, synthetic data, median of 3 per run; M7e in training: 0.466–0.478 s (v1) |
| minibatch forward (512, no gradient) | 1.42–1.52 ms | 2.36–2.66 ms | readiness suite |
| environment throughput, N=5 standby, random actions | 2,046 / 1,736 tr/s | 1,832 / 1,483 tr/s | M7g-b bench, two runs: v2 = 89.5 % / 85.4 % of v1 |
| rollout-buffer observations | 0.29 MiB | 10.25 MiB | readiness suite |
| `model.zip` / `vecnormalize.pkl` | 67 KB / 2.5 KB | 336 KB / 23.5 KB | readiness suite |
| training run, 3,072,000 transitions | 35.3–36.0 min learn, 1,424–1,452 tr/s end to end | — | M7e seeds 0–2 (v1 observation, reward v2) |
| evaluation | 2.145 s per episode (session wall, 2,955 episodes, 1.76 h) | — | M7e post-hoc evaluation |
| memory, N=5 standby | 1.59 GiB working set, 4.96 GiB commit (campaign drew 5.46 GiB) | — | M7e (see its report) |
| disk per seed | run 41–42 MiB + evaluation 347–715 MiB | — | M7e |
| game processes | ≤ 10 | ≤ 10 | M7e; readiness smoke peak 10 per arm |

**Estimated [E] (v2 unless stated):**

| item | estimate | basis |
| --- | --- | --- |
| rollout collection | 3.4–3.7 s per rollout (v1 measured 3.05–3.11 s) | the non-inference part scaled by the measured 85.4–89.5 % environment ratio, inference × 1.10–1.13 |
| update | 0.71–0.75 s per rollout | M7e's 0.472 s × the measured 1.50–1.51 ratio; the synthetic 0.736–0.745 s directly |
| end-to-end | ≈ 1,150–1,250 tr/s (≈ 79–87 % of v1); 41–45 min per 3,072,000-transition run | 600 rollouts × (collection + update) |
| training, 3 seeds per arm | v1 ≈ 1.8 h [M-based]; v2 ≈ 2.1–2.3 h | sequential, one run at a time |
| evaluation, 2,955 episodes per arm + 100 random | v1 ≈ 1.8 h [M-based]; v2 ≈ 2.0–2.1 h; random ≈ 0.1 h | 2.145 s/episode; v2 ÷ 0.854–0.895 |
| **total wall, 3 seeds** | **≈ 7.6–7.9 h**, plus orchestration, clear-verification and metric-recorder overhead | sequential; ≈ 3.6 h less if M7e stands in for the control |
| gate-6 extension (if triggered) | ≈ +5.0–5.2 h (4 runs ≈ 2.6–2.7 h + 3,940 episodes ≈ 2.5–2.6 h) | same rates; maximum experiment ≈ 12.7–13.1 h plus overheads |
| memory | working set ≈ 1.61 GiB; commit ≈ 5.0 GiB; gate ≥ 6.0 GiB available | M7e + ~12 MiB parent (buffer, parameters, Adam); worker-side v2 parsing unmeasured |
| disk | v1 arm ≈ 1.5 GiB; v2 arm ≈ 1.6 GiB (checkpoints +9 MiB per run); ≈ 3.1 GiB total, ≈ 5.2 GiB with the extension | M7e per-seed sizes |
| metric recorder (item 7.2) | worker-side: negligible; post-hoc replay: several hours for ~6,010 replays | not measured; decided with item 7.2 |

## 9. What this experiment cannot show

- **One stage only.** Mario's stage, so no claim about generalisation across stages. v2's static geometry is constant
  here.
- **One network.** A null result does not rule out richer encoders, such as a set encoder or a CNN over a grid.
- **Perception only.** A null result does not show perception is irrelevant: the ceiling may be an exploration problem
  that perception alone cannot solve at this budget, which is why gate 7 routes to category D.
