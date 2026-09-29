# M7s gate `m7s1`: offline failure analysis (2026-09-29)

The registered outcome is unchanged: **3, inconclusive** (`docs/rl_gcsl_return_m7s_results.md`). This analysis ran
with **zero native ticks**: no game was launched, no optimizer step was taken, and nothing was retrained. It uses only
this run's records and the pinned source. No human recording, TAS, fixture or archived crossing was used.

**Bottom line.** No implementation or update defect was found. Every audited link of the update path works: relabelling,
goal and horizon inputs, action labels, collector storage, optimizer, and propagation of updates to the acting policy.
The supervised labels, however, carry almost no goal information that the learner could have used. With 81 % of
relabels more than 64 ticks ahead, the recorded action carries no information about the relabelled goal at the
coarse state measurable offline (resolution ±0.4–0.6 millinats per head). Where information exists (h ≤ 64), it is
about 1 millinat per head, below the 2.6–3.3 millinat noise of one training batch. The observed near-uniform loss,
noise-scale parameter drift and small goal sensitivity are what a working learner fitting these labels would show.
**Weak labels** is the best-supported explanation. It is not proven: the v3 observations the learner saw were never
stored, so information at finer state and held-out generalization cannot be measured offline (section 5).

Reproduce (about 5 minutes; writes a parse cache and `m7s_failure_analysis.json` to `<dir>`, which the tool refuses
to place under `runs/`):

    python rl/tools/m7s_failure_analysis.py --out <dir>

Inputs are `runs/m7s/gate/s{0,1,2}/{phase_a,R_phase_b,U_phase_b,R_eval,U_eval}` (per episode: native words,
the goal sidecar's per-tick cell and contact, labels), `init.pt`, `R_final.pt` and `R_train_chunks.json`. Units:
**mnat** = 10⁻³ nats per row. ln 72 = 4.2767 nats is the loss of a uniform policy.

## 1. The update path (question 1)

| link | code | evidence | verdict |
| --- | --- | --- | --- |
| relabelled example (o_t, a_t, g = c_(t+h), h = first valid visit, b ∈ [h, H − t], label = recorded action, inside the recorded prefix) | `rl/m7s_goal.py:355-388` | each seed's final dataset (phase A + R phase B: 139 / 142 / 135 episodes, 424k / 416k / 422k ticks) rebuilt from the artifacts and sidecars; 20,000 draws per seed through the unchanged `sample_examples` | **0 violations in 60,000**; b = h in 49–51 % |
| relabel horizon | same | h mean 590–624 (logged 598–616); median 352–387; h ≤ 16: 9–10 %, h ≤ 64: 17–19 %, h > 256: 58–61 %; goal airborne in 80–82 % | as registered |
| sampling weights | `:364-366` (episode-uniform, then tick-uniform) | per-tick effective sample share 0.22 / 0.58 / 0.82, driven by the 7-tick (seed 0) and 52-tick (seed 1) quota-cut stubs. Every worker reaches its quota on the same final step, so the stubs exist only in the last chunk's dataset (100 of 7,000 steps) | registered quirk, not a cause |
| goal and horizon inputs | `m7s_goal.py:139,155`; acting `m7s_worker.py:150` | the same feature function at training and acting time; acting b = H − t lies inside the training support | OK |
| collector storage: o_t before a_t, label a_t, next cell c_(t+1) | `m7s_collect.py:170-191` | new check (`collector` section): the real `run_phase(store=True)` over the synthetic in-process workers of `rl/m7s_tests.py`, whose observations encode the known position at every tick | **0 mismatches** in 1,070 ticks / 20 episodes |
| batch and loss | `m7s_policy.py:143-148` | 512 i.i.d. relabels per step; CE(stick) + CE(button) on the heads that act | OK |
| optimizer | `m7s_policy.py:133,151` | Adam 3 × 10⁻⁴ (default betas, eps), grad-norm clip 0.5 (no effect under Adam's per-parameter normalization), 100 steps per 5,120 ticks; `R_final.pt` records 7,000 steps in each seed | OK |
| updates reach the acting policy | `m7s_gate.py:873-875` (trainer and actor share `r_pol`) | common random numbers: in all **15** first episodes (5 workers × 3 seeds), R and U emit the same words up to consumed tick 1023. They diverge at ticks 1026–1089, just after R's first update at worker tick 1024. **0 of 345** phase-B pairs diverge before that update, and cells are equal before divergence in every pair | OK: updates change behaviour at once |
| observation scaling | — | M7s feeds raw v3 (no VecNormalize, unlike M7n PPO); the registered initialization check was made on raw v3 | design property, not a defect |

**Parameter change init → final** (per-parameter RMS of the change). A pure-noise gradient under Adam moves each
parameter by about lr·√steps = **0.025**; a consistently signed gradient could move it by up to lr·steps = 2.1.

| layer | seed 0 | seed 1 | seed 2 |
| --- | ---: | ---: | ---: |
| trunk (606 → 64) weights | 0.029 | 0.029 | 0.026 |
| goal branch (14 → 32) weights | 0.023 | 0.022 | 0.025 |
| joint (96 → 64) weights | 0.019 | 0.020 | 0.020 |
| stick / button heads | 0.012 / 0.013 | 0.012 / 0.011 | 0.011 / 0.010 |

Every layer changed, including the goal branch. The joint layer's goal columns changed by norm 0.86–0.94, against
1.22–1.33 for its trunk columns. The head weights grew 7.6–10.3× from their 0.01-gain initialization. The size of the change
matches a noise-driven random walk, not a coherent signal. Its functional effect is real but small in the goal
direction: R's post-training goal-swap action TV is 0.003–0.006 (12–14× U's), while R's behaviour differs from U's
on visited states often enough that paired evaluation episodes diverge within a median 8 ticks (hazard 0.07–0.10 per
tick).

**Reconciling the "flat" loss.** In the last 10 chunks the logged loss sits **1.4 / 2.4 / 2.1 mnat below ln 72**
(seeds 2 / 1 / 0). That loss is **in-sample**: every batch is drawn from the dataset being fitted, with about 8.5
draws per tick over training, and no held-out loss was logged.

Offline-measurable sources of reduction:
- action imbalance: KL of the data's marginals from uniform is **0.01 (stick) + 0.02 (button) mnat**;
- dependence of the behaviour policy on coarse state: about **0.1 mnat per head** (section 2);
- goal information in the actual labels: **indistinguishable from 0** (section 3).

The remaining 1–2 mnat is either behaviour structure at finer state or in-sample fitting of noise; the records
cannot separate the two. For scale: one training batch's loss fluctuates with sd **2.6–3.3 mnat**, so goal signal of
≤ 1 mnat on the ~16 % of labels where it exists gives a per-step signal-to-noise ratio of about 0.1. That fits the
noise-scale parameter drift. The same code learned in the synthetic positive control (preflight 2026-09-29: 7 → 32 and
4 → 35 reaches of 40, goal-swap TV 0.130) with a loss only **32 mnat** below ln 72, but at a mean relabel horizon of
6 ticks. So a near-uniform loss alone says nothing about a defect.

## 2. Label ambiguity at comparable states (question 2)

**Estimator.** Plug-in conditional mutual information I(X; G | S) against an **exact within-stratum permutation** of X
(10 permutations). The estimate is observed − null mean; z = estimate / null sd. X is always exchangeable across
rows:
- per-tick actions (drawn with fresh uniforms every tick);
- one relabelled example per (episode, tick);
- non-overlapping action segments.

Duplicated rows or overlapping windows would give the observed statistic a larger bias than the null's (section 5).
Every row keeps its episode, and the null never mixes strata.

States:
- **S_small** = the 300-unit cell with its contact class (the goal contract's own state);
- **S_full** = S_small × 8-tick motion sign × time bucket (0–299 / 300–899 / 900–1799 / 1800–3600);
- relabel strata also include the h bucket.

Data: the learner's own training data, phase A + R phase B of all seeds, **1,228,946 action rows in 416 episodes**.
Validation of the estimator on synthetic data with known answers:
- an independent X in strata of about 5 rows gives excess −0.45 (z −1.2) against a raw plug-in bias of 1,208 mnat;
- runs of 50 autocorrelated goal values give −0.13 (z −0.3);
- a 5 % real dependence gives +8.8 (z +12.8).

| control | what it measures | result |
| --- | --- | --- |
| action imbalance | KL(marginal of the data ‖ uniform) | stick 0.010, button 0.022 mnat (U's phase B: 0.004, 0.007) |
| state dependence of the data's actions (unconditional control) | I(a_t; S) | S_small: stick +0.10 (z 3.0), button +0.14 (z 5.9); S_full: +0.17 / +0.15 (z < 2) |
| stationary stretches | share of ticks whose cell and contact have not changed for ≥ 60 ticks | **29 %** of rows |

The behaviour policy is uniform to within 0.03 mnat and depends on coarse state by about 0.1 mnat. There is no
imbalance a learner could exploit, and nothing masquerades as goal dependence.

**Action-lock proxies** (the stick × jump choice at t versus the cell offset 16 ticks later, given S_small). There is
no per-tick status in the records, so contexts are built from recorded contact transitions:

| context | share of rows | information (mnat) | z |
| --- | ---: | ---: | ---: |
| grounded, < 16 ticks after landing (landing-lag window) | 7.8 % | +0.20 | 0.7 |
| grounded, 16–47 ticks after landing | 10.9 % | +1.30 | 5.1 |
| grounded, ≥ 48 ticks after landing (or never airborne) | 42.3 % | +0.70 | 9.7 |
| airborne, < 32 ticks after take-off | 17.3 % | +1.83 | 5.0 |
| airborne, ≥ 32 ticks after take-off | 21.6 % | +2.73 | 8.5 |
| same cell for ≥ 60 ticks | 28.8 % | +0.57 | 7.2 |
| all rows | 100 % | +1.33 | 17.4 |

The landing-lag window carries no measurable action information, consistent with locked states. The rest of the
grounded time carries 0.6–1.3 mnat. The action matters most in the air.

## 3. Information of actions and segments about later goal reach (question 3)

**(a) Per tick, fixed horizon (the GCSL direction).** What it predicts: the recorded stick or button at t from the
sign of the cell offset of tick t + h (x, y) and that cell's contact (air or ground), given the state. The table shows
excess mnat per head, stick / button, with z in brackets. Rows: 1.23M (h = 1) to 0.82M (h = 1,024), 385–416 episodes.

| h | S_small | S_full |
| ---: | --- | --- |
| 1 | +0.33 (7.5) / +0.46 (7.7) | +0.12 (1.6) / +0.38 (7.8) |
| 4 | +0.75 (10.4) / +0.95 (13.0) | +0.60 (4.1) / +1.31 (6.5) |
| 16 | **+1.13 (19.4)** / +0.56 (6.0) | +1.33 (8.9) / +0.75 (4.1) |
| 64 | +0.46 (7.3) / +0.24 (2.7) | +0.36 (1.8) / +0.30 (2.1) |
| 256 | −0.01 (−0.1) / +0.03 (0.7) | −0.15 (−0.6) / +0.37 (1.6) |
| 1,024 | +0.01 (0.2) / +0.07 (1.2) | +0.46 (1.8) / −0.42 (−1.5) |

**(b) The actual GCSL labels.** 600,000 draws with the unchanged sampler over the final datasets, reduced to
**452,882** examples (one per episode and tick); mean h 642. What it predicts: the recorded action from the
relabelled goal, coded either as the 18-class offset or as the exact goal cell, given the state and h bucket.

| goal coding | S_small: stick / button | S_full: stick / button |
| --- | --- | --- |
| offset (18 classes) | −0.12 (±0.44) / +0.13 (±0.35) | +0.14 (±0.56) / −0.03 (±0.39) |
| exact goal cell | +0.20 (±0.37) / −0.22 (±0.31) | +0.91 (±0.58) / −1.02 (±0.55) |

The table shows excess mnat with the null sd in brackets; every |z| < 2.

By relabel h bucket (S_small, offset coding; rows 37k–179k per bucket), every |z| < 2:

| h bucket | share of labels | stick | button |
| --- | ---: | --- | --- |
| 1–16 | 8.1 % | −0.6 ± 1.6 | −1.5 ± 1.4 |
| 17–64 | 8.2 % | +2.0 ± 1.1 | +0.2 ± 1.9 |
| 65–256 | 21.8 % | +0.2 ± 0.7 | −0.2 ± 0.6 |
| 257–1,024 | 39.6 % | −0.6 ± 0.4 | +0.7 ± 0.5 |
| 1,025–3,600 | 22.4 % | −0.4 ± 0.8 | −0.3 ± 0.6 |

Weighting the fixed-horizon curve by this h distribution predicts about 0.1–0.2 mnat per head, below the resolution of
the label-level test. The two agree: the labels GCSL was given contain no goal information at the coarse state
beyond about ±1 mnat per head (2 sd).

**(c) Short action segments** (non-overlapping windows). What it predicts: the cell offset class of tick t + h from
the summary of actions t … t + k − 1, given S_small. The summary is the direction of the summed stick vector (dead
zone 0.2 k) × whether any jump button was pressed (C-up / C-left).

| h \ k | 1 | 4 | 16 | 64 |
| ---: | --- | --- | --- | --- |
| 16 | +1.33 (17.4), 1.22M rows | +3.31 (10.0), 305k | +3.80 (3.9), 76k | — |
| 64 | +0.59 (5.9) | +0.82 (2.3) | +3.08 (3.8), 75k | +1.73 (1.5), 19k |
| 256 | +0.04 (0.3) | +0.25 (0.7) | +1.26 (1.8) | −0.14 (−0.1) |
| 1,024 | +0.02 (0.1) | +0.95 (2.1) | +2.53 (2.5), 51k | +0.85 (0.4), 13k |

The table shows excess mnat with z in brackets; the summary entropy is 2.76 nats for k ≤ 4 and 1.65 for k = 16.

Segments of 4–16 ticks carry roughly 3–4× more information than a single tick at h ≤ 64. At h ≥ 256 they carry at
most about 1–2.5 mnat, with z ≤ 2.5 across 15 tests (not robust to multiple comparisons). These are correlations in
data from a near-random policy. They do not show that a segment-level policy would learn to return, and they do not
establish causation.

## 4. Conclusion (question 4)

| possibility | evidence for | evidence against | status |
| --- | --- | --- | --- |
| **A. implementation / update defect** | none found | every audited link passes (section 1); updates reach acting at the first chunk boundary; every layer, the goal branch included, changed; the same code learns when labels are informative (synthetic control) | not supported. The links not verified on real data are the live storage of real v3 tensors and any generalization, because neither observations nor a held-out loss were recorded |
| **B. functioning learner, weak or conflicting labels** | goal information in the actual labels is ≈ 0 ± 0.5 mnat per head; per-tick information vanishes beyond h ≈ 64 while 81 % of relabels lie beyond it; batch noise is ≥ 3× the largest per-label signal and > 10× its label-weighted average; parameter drift is at the noise scale; the lock proxy shows dead windows; the same code learns at short horizons | cannot exclude that the v3 state (velocity, action status, jumps left) holds more goal information than cells do | **best supported** |
| **C. insufficient evidence to distinguish** | the state is coarse (300-unit cells, contact); the logged loss is in-sample, so memorization and generalization are not separable | a diffusive argument (one random tick's effect on the position reached h ticks later falls roughly as 1/h) predicts little long-horizon information even at full state, consistent with the 16 → 64 decay measured here. That argument is a model, not a measurement | open; this is the residual uncertainty around B |

**The single most informative next bounded check for each case** (none performed; each needs separate
authorization):

- **A (defect):** a replay-backed storage and held-out-loss check.
  - Re-step 5 preserved R phase-B episodes from their recorded words (≤ 18,000 native ticks, no training) through the
    live `M7SubprocVecEnv` + `run_phase(store=True)` path.
  - Assert that the stored o_t equal the replayed v3, and that the actions and cells equal the records.
  - Evaluate the relabel cross-entropy of `init.pt` and `R_final.pt` on those episodes (forward passes only).
  - A storage mismatch would be a defect.
- **B (weak labels):** a synthetic GCSL control with matched label statistics.
  - Zero native ticks, but optimizer steps on synthetic data only.
  - Use the same trainer, network, 7,000 steps and batch 512, on a world with a near-uniform behaviour policy, a mean
    relabel horizon of about 600, and per-tick information shaped like the section 3 (a) curve.
  - If it also stays goal-blind while the h ≈ 6 control learns, the label statistics alone suffice to explain m7s1.
- **C (insufficient evidence):** a fine-state information re-estimate.
  - Replay about 40 preserved own phase-B episodes (≤ 144,000 native ticks, no training) while recording per-tick
    native observations and v3.
  - Recompute I(a; G | S) with velocity, action status and jumps-left strata, using the same exact permutation test,
    at h = 16, 64, 256, 1,024 and on the relabel distribution.
  - Information at h ≥ 256 staying near 0 confirms B; a material rise means the coarse state hid it.
  - The same replay also gives R_final's held-out cross-entropy against `init.pt`, forward passes only.

## 5. Limits and discarded estimators

- **State is coarse** (cell + contact, optionally 8-tick motion sign and time bucket). Every information number is
  conditional on that state. "No detectable information" means within ±0.4–0.6 mnat per head at this state, not zero
  at the learner's state.
- **Action-lock contexts are proxies** from contact transitions; there is no per-tick status.
- **The information measures are statistical dependence, not causal effects,** and a segment result does not show
  that a segment policy would learn.
- **Pooling:** the data pools three seeds of R's own training data. R's policy drifted slightly during collection
  (section 1), and U's phase B was not re-analysed here.
- **Two estimators were tried and discarded before the one reported:**
  - A held-out backoff-count predictor (Dirichlet smoothing, β = 50): adding even an independent but skewed variable
    "gained" +11.5 mnat, because it undid over-smoothing of the state-only level.
  - A cross-episode with-replacement null: small strata lost category diversity, and duplicated relabel rows and
    overlapping segments made the observed bias larger than the null's. This produced flat, spurious +2 to +64 mnat
    values at every horizon. The exact within-stratum permutation, with exchangeable rows, removed both.
  - Early numbers from those passes were not used.
- **Nothing changed in the evidence:** `runs/` was only read, the D: backups were not touched, and the registered
  outcome, rule and records are unchanged.
