# M7u4 proposal: why the M7u3 refit regressed, which offline metric to trust, and a bounded offline model study (2026-10-01)

**Status: read-only diagnosis plus this proposal.** Nothing was launched, collected, trained, committed or pushed. No
optimizer was constructed and no backward pass was run; the only model computations were forward passes of the three
pinned models (frozen M7u1, P_refit, P_retrain), with every file and parameter digest verified before and after each
script. Scratch scripts and outputs live outside the repository (appendix A). This document is the only file added.

**Unchanged:** every registered M7u1 / M7u2 / M7u3 outcome (M7u3 = NULL, label `MODEL_REGRESSION`); the selected
baseline **M7n v3 + reward v2** (Track 1 `btt_s9_b8_v1`, PPO); the planner; every contract.

**Short answer.**
1. The refit's *members* are as accurate as M7u1-recipe members; they are less diverse. The registered regression is a
   property of the ensemble-mean trajectory, which the planner never uses (§1.7).
2. Open-loop error tracks per-goal reach only through goal difficulty. Within a goal it did not pick the better model.
   A planning-faithful tick-0 ranking metric separates models offline, but its link to native reach is unvalidated at
   gate resolution (§2).
3. The proposed study: four recipes × five seeds, zero native ticks, about 6.2 CPU-hours, decided once on the M7u3 goal
   pool (§3).
4. A wall-top landing from tick 0 within two or three gates of this line alone is implausible. The evidence favours a
   hybrid with the PPO line (§4).

## 0. Verified state and what was read

| item | state |
| --- | --- |
| checkout | `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`. `HEAD` = `origin/main` = remote `main` (`git ls-remote`) = `79591aa`. Working tree clean before and after (0 entries); no file under `rl/`, `runs/m7u*` or `logs/m7u3_prep/` was modified during the session |
| guide and instructions | external `..\guide.md` (revised 2026-09-22; narrative stops at M7g), `CLAUDE.md`, `docs/rl_handoff_2026-09-28.md` |
| M7u records read | every `docs/rl_model_planning_m7u_*`, `m7u2_*` and `m7u3_*` document and approval record, including `docs/rl_model_planning_m7u3_gate_results_2026-10-01.md` |
| frozen M7u1 | `runs/m7u/gate/_gate/model.pt` `a4bd30e5…`, parameters `0e70af78…` |
| P_refit | `runs/m7u3/gate/_gate/model_refit.pt` `3888d747…`, parameters `74c8861e…` |
| P_retrain | `logs/m7u3_prep/p_retrain.pt` `47d51b1b…`, parameters `13fa9cdb…` |
| artifacts read | M7u1 `collection.json`, sidecars, `model_inputs_*`, `state.json`, `goals.json`, 120 trial files. M7u2 `pool.json` + 360 pool sidecars, `goals.json`, `state.json`, 72 trial files. M7u3 `refit.json`, `train_pool.json` + 540 training-pool sidecars, `state.json` (the gate's registered diagnostics), `goals.json` (24 goals with their recorded witness words), 96 trial files. `logs/m7u3_prep/{identity_retrain,p_retrain}.json` |

**Goal-pool exposure, disclosed.** The M7u3 goal pool is the proposed final test (§3.4). This diagnosis read it only
through:
- the gate's own registered diagnostics (D2a / D5, already on record);
- the 24 registered goals' coordinates and recorded witness words, rolled through the three existing models.

The other 516 goal-pool sequences, their reach labels and any ranking metric on the goal pool were **not** read or
computed. The held-out from-reset data used here are the 360 M7u2 pool episodes, which no model was fitted on.

## 1. Part 1: why the refit regressed

### 1.1 Loss curves and final losses

**Logged curves.** The logged training loss is one minibatch. The logged "held-out" loss is only the **first 4,096**
M7u1 held-out transitions (`train_loop` uses `heldout[:4096]`), which is about one episode. The frozen curve is the
identity retrain, which is bit-exact to M7u1.

| step | frozen train / held | P_retrain train / held | P_refit train / held |
| ---: | --- | --- | --- |
| 1,000 | 2.242 / 2.486 | 2.198 / 2.446 | 2.274 / 2.505 |
| 2,000 | 1.699 / 1.903 | 1.721 / 1.861 | 1.674 / 1.890 |
| 3,000 | 1.417 / 1.616 | 1.431 / 1.555 | 1.403 / 1.600 |
| 4,000 | 1.163 / 1.379 | 1.172 / 1.373 | 1.102 / 1.354 |
| 5,000 | 0.899 / 1.172 | 1.046 / 1.235 | 0.953 / 1.148 |
| 6,000 | 0.770 / 1.002 | 0.916 / 1.112 | 0.776 / 0.978 |

**Not converged.** All three runs were still falling steeply when they stopped. The held loss fell 14.5 / 10.0 / 14.8 %
in the last 1,000 steps. The controller-counter heads (tap x / y, Z) were still dropping fastest.

**Full-data teacher-forced losses** (my forward passes, no backward). The table covers transitions every model can
represent; vocabulary-infeasible transitions are counted in §1.2.

| data | role | frozen | P_retrain | P_refit |
| --- | --- | ---: | ---: | ---: |
| M7u1 train, 240,964 | in-sample for all | 0.836 | 0.976 | **0.836** |
| M7u1 held-out, 31,181 | held out for all | 1.019 | 1.138 | **0.981** |
| M7u3 training pool, 103,680 | in-sample for the refit only | 0.873 | 1.004 | **0.756** |
| M7u2 pool, 46,080 (from reset) | held out for all | 0.911 | 1.024 | **0.801** |
| member totals on the M7u2 pool | | 1.026 / 0.842 / 0.866 | 0.883 / 1.112 / 1.076 | 0.853 / 0.843 / 0.708 |

**The refit has the lowest one-step loss on every held-out set,** and it fits M7u1's own training transitions as well as
the frozen model does, despite 30 % fewer draws per transition (§1.3).

**What dominates the loss** (M7u2 pool, weighted):

| term | share of the total |
| --- | ---: |
| status H1 | ≈ 35 % |
| controller counters and masks | ≈ 34 % |
| hitlag / flags H4 | ≈ 23 % |
| continuous dynamics H6 (Δx, Δy, velocities …) | **≈ 1.4 %** |

### 1.2 Input / target normalization statistics

**There are none to compare.** The model has no fitted normalization. Inputs use fixed constants:
- lengths ÷ 2,000, velocities ÷ 50, clock ÷ 3,600, progress ÷ 60, status id ÷ 256 (`rl/m7u_state.py`);
- H6 targets ÷ `H6_SCALE` (`rl/m7u_model.py`).

Neither model rescales anything from data.

**What the added data shift.** Measured on the training sets, in M7u1 standard-deviation units:

| feature | shift |
| --- | ---: |
| targets remaining | +1.81 |
| clock | −1.53 |
| facing | −0.51 |
| every other agent feature | ≤ 0.29 |

H6 target spreads agree within about 10 %, except floor distance (−13 %) and animation speed (−21 %). The airborne share
is 43 % in M7u1 against 38 % in the pool.

**The only data-derived element is the vocabulary:**
- **Statuses.** The refit adds `RunBrake` (17) and `TurnRun` (19), with 2 and 12 pool rows.
- **Masks.** Four extra H2 combinations on shared statuses; the H3 mask differs. The H3 / H4 combination lists are equal.
- **Coverage.** The frozen vocabulary cannot represent 114 of 46,080 M7u2-pool transitions (0.25 %), 163 of the training
  pool (plus 14 rows whose status it has never seen) and 14 of M7u1 held-out. The refit vocabulary represents all of
  them.

### 1.3 Data composition and effective passes

| | M7u1 (frozen, P_retrain) | refit |
| --- | ---: | ---: |
| transitions | 240,964 (80 episodes) | 344,644 (80 + 540; pool share **30.1 %**) |
| rows at input ticks 0–191 (from-reset window) | 6.4 % | **34.5 %** |
| rows at tick 0 (reset rows) | 80 (0.03 %) | 620 (0.18 %) |
| bootstrap size per member | 241,416 / 263,098 / 240,489 | 345,096 / 366,778 / 344,169 |
| draws per drawn transition (6,000 × 1,024) | 25.5 / 23.4 / 25.6 | 17.8 / 16.8 / 17.9 |
| expected draws per M7u1 transition | 25.5 | **17.8–18.3 (−30 %)** |
| early-window samples per member | ≈ 0.36–0.39 M | **≈ 2.0–2.1 M (×5.4)** |
| distinct M7u1 transitions per member | 164,262 / 165,410 / 150,621 | identical (stratified bootstrap) |

### 1.4 One-step versus multi-step error on held-out from-reset data

**One step.** Decoded one-step position error is the ensemble mean, with the heads free-running from the true state.
On the M7u2 pool:
- **position error:** frozen 2.08, P_retrain **1.84**, P_refit 2.19;
- **status accuracy:** 0.959 / 0.959 / **0.964**;
- **by tick window**, total loss: 0–31 at 0.769 / 0.858 / **0.608**; 32–95 at 0.961 / 1.067 / 0.839; 96–191 at 0.955 /
  1.101 / 0.919.

**Multi-step** (ensemble-mean Chebyshev error over the recorded words, median). The strict figures reproduce the M7u3
cross-check exactly.

| starts | frozen 16 / 32 / 64 / 96 | P_retrain | P_refit |
| --- | --- | --- | --- |
| M7u2 pool, reset row (360) | 153 / 333 / 714 / 908 | 161 / 358 / **665 / 865** | 181 / 409 / 808 / 1,132 |
| M7u2 pool, from t = 32 (360) | 112 / 319 / 576 / 790 | 139 / 329 / 591 / 733 | 154 / 379 / 748 / 1,016 |
| M7u2 pool, from t = 64 (360) | 113 / 271 / 609 / – | 103 / 283 / 595 / – | 128 / 325 / 722 / – |
| M7u3 training pool, reset (540; **refit in-sample**) | 137 / 303 / 626 / 850 | 133 / 299 / 569 / 801 | 168 / 399 / **746** / 1,048 |
| M7u1 train, mid-episode grid (801; in-sample for all) | 93 / 269 / 616 / 786 | 85 / 242 / 607 / 796 | 123 / 322 / **734** / 1,003 |
| M7u1 held-out, mid-episode grid (298) | 102 / 285 / 658 / 936 | 95 / 312 / 615 / 887 | 132 / 353 / 778 / 1,148 |

**Short horizons from reset** (h = 1 / 4 / 8): frozen 1.8 / 13.1 / 63; P_retrain 1.2 / 11.6 / 57; P_refit 2.4 / 15.5 / 66.

**Bootstrap 95 % CI over episodes** (M7u2 reset), difference of medians against the frozen model:

| model | h16 | h32 | h64 | h96 |
| --- | --- | --- | --- | --- |
| P_refit | +29 [−14, +66] | +76 [+20, +128] | +94 [+4, +205] | +225 [+106, +345] |
| P_retrain | +8 [−33, +41] | +25 [−20, +77] | −49 [−124, +36] | −42 [−155, +68] |

**Reading.** The refit's ensemble-mean open loop is worse **everywhere**: mid-episode as well as from reset, and **on its
own training episodes too** (training pool 746 against 626 at h64). So the regression is not a from-reset coverage
problem, and not overfitting.

### 1.5 Error by state class and by early versus later ticks

**By the true ground / air state at the horizon** (M7u2 reset, ensemble mean):

| | frozen | P_retrain | P_refit |
| --- | ---: | ---: | ---: |
| h16 grounded (231) | 71 | 94 | 131 |
| h16 airborne (129) | 274 | 292 | 285 |
| h64 grounded (231) | 459 | 574 | 699 |
| h64 airborne (129) | 1,002 | 868 | 1,239 |

Airborne futures carry about twice the error in every model. One-step position error is also about twice as large
airborne (3.4 / 2.8 / 3.1) as grounded (1.7 / 1.5 / 1.8).

**Discrete divergence from reset.** The first predicted-status mismatch comes at a median per member of:
- frozen 15 / 5 / 14 ticks; P_retrain 12.5 / 15 / 15; **P_refit 20 / 16 / 32**;
- on the training pool, frozen 15 / 8 / 15 against P_refit 32 / 30.5 / 32.

So the refit tracks the *status sequence* from reset longer.

**Takeoff.** 238 of the 360 M7u2-pool episodes take off within 96 ticks (median tick 5).
- **Exact takeoff tick predicted:** 0.45–0.50 / 0.30–0.48 / 0.44–0.53 of members.
- **Takeoff never predicted:** 16–34 % / 17–31 % / 16–26 %.

The takeoff is the dominant discrete error mode from rest in every model.

**Early versus later starts.** Errors from t = 32 / 64 and mid-episode are 4–36 % below the reset-row figures at
h16–h64 for every model, and the refit stays the worst at h64 in every start set.

### 1.6 One-step quantities that do and do not track rollout error

Spearman correlation across the nine members (3 per model) between a one-step quantity and that member's own median
h64 rollout error:

| one-step quantity | M7u2 pool | training pool | M7u1 train | M7u1 held-out |
| --- | ---: | ---: | ---: | ---: |
| total training loss | 0.05 | −0.08 | −0.23 | −0.48 |
| H6 loss (the trained continuous objective) | 0.38 | 0.30 | 0.10 | −0.08 |
| **decoded one-step position error (median)** | **0.65** | **0.67** | **0.87** | **0.75** |

The quantity the optimizer minimises does not track rollout quality. The median per-tick displacement error does.

### 1.7 Training-seed variation, measured with the members that already exist

**Why members are independent draws.** Each member is independently initialised, bootstrapped and batched, and the
loss decomposes per member (Adam is per parameter). That makes frozen m0–m2 and P_retrain m0–m2 **six draws of the M7u1
recipe**, and refit m0–m2 three draws of the refit recipe. I recombined them into all 84 three-member pseudo-ensembles.

**Member h64 error from reset** (M7u2 pool, each member's own rollout):

| model | members |
| --- | --- |
| frozen | 1,135 / 733 / 1,096 |
| P_retrain | 1,074 / 800 / 723 |
| P_refit | 856 / 772 / 1,028 |

Within one recipe, members differ by up to **1.57×**. The refit members rank **3, 5 and 6 of 9**.

**Ensemble-mean h64 error of the 20 M7u1-recipe triples:**

| start set | 20 triples min / median / max | refit triple | refit rank of 21 |
| --- | --- | ---: | ---: |
| M7u2 pool, reset | 548 / 670 / 839 | 808 | 20 |
| training pool, reset | 477 / 605 / 793 | 746 | 20 |
| M7u1 train grid | 564 / 612 / 676 | 734 | 21 |
| M7u1 held-out grid | 597 / 639 / 700 | 778 | 21 |

**Mean member error versus member spread** at h64 (median over starts; spread = largest pairwise member distance):

| start set | mean member error: frozen / P_retrain / P_refit | member spread: frozen / P_retrain / P_refit |
| --- | --- | --- |
| M7u2 reset | 996 / 991 / **935** | 1,779 / 1,534 / **1,123** |
| training pool | 971 / 820 / 874 | 1,866 / 1,302 / **995** |
| M7u1 train grid | 898 / 854 / 917 | 1,313 / 1,064 / **1,022** |
| M7u1 held-out grid | 903 / 864 / 971 | 1,356 / 1,126 / **1,050** |

The ensemble-mean error jumps when all three members of a triple are refit members. Medians at h64, M7u2 reset, by 0 /
1 / 2 / 3 refit members: 670 / 701 / 712 / 808.

**The mechanism.**
- **No accuracy loss.** The refit's members are, individually, as accurate as M7u1-recipe members, within the seed
  spread: slightly better from reset on the M7u2 pool, between the two on the training pool, slightly worse
  mid-episode.
- **Correlated errors.** Their spread is 22–47 % smaller than the frozen model's and 4–27 % smaller than P_retrain's, so
  their errors are correlated. The ensemble mean, an average of three wrong trajectories, loses the cancellation that
  makes the frozen ensemble mean better than any of its members. The refit's ensemble mean (808) is worse than its best
  member (772).
- **More data narrowed the members' disagreement without reducing their error.** The residual error is therefore shared
  (systematic) rather than epistemic.
- **The planner never uses the ensemble-mean trajectory.** It scores each member's own trajectory (mean of member costs
  + 1.0 × std, `m7u_planner.score`).

**Scale of seed variation.** The registered reading used one retrain draw (−16 % to +10 %). The 20 triples span
**−18 % to +25 %** around their median at h64, and single members span 723–1,135.

### 1.8 Verdict per candidate explanation

| explanation | verdict | evidence |
| --- | --- | --- |
| **undertraining per sample** (−30 % draws per M7u1 transition) | **contradicted** as the cause | equal full-data one-step loss on M7u1's own training transitions (0.836 vs 0.836); lower on every held-out set; per-member rollouts within the seed spread. (All three runs are undertrained *in absolute terms*, §1.1; that applies to every model, not to the refit) |
| **normalization shift** | **contradicted** | no fitted statistics exist; the vocabulary change is two rare statuses and a few mask entries, and it *removes* 0.25 % infeasible transitions |
| **data reweighting** (from-reset window 6 % → 35 %) | **contradicted** as a cause of worse accuracy; **can't decide** for the diversity effect | mid-episode one-step fit unchanged (tick ≥ 192: 0.835 vs 0.838); mid-episode member rollouts within the seed range. Whether the narrower member spread comes from *more* data or from *reweighted* data cannot be separated here |
| **one-step / rollout mismatch** | **supported** | lowest one-step loss but no per-member rollout gain; total loss uncorrelated or anti-correlated with member rollout error (−0.48 to +0.05); the trained continuous term is ≈ 1.4 % of the loss and its Huber mean does not track rollouts (−0.08 to 0.38) |
| **training-seed variation** | **supported** for per-member accuracy and for native reach; **not sufficient** for the ensemble-mean label | refit members rank 3 / 5 / 6 of 9; native 5 vs 7 has reverse p = 0.38; but the refit triple is at the edge or outside all 20 M7u1-recipe triples on the registered metric |
| **reduced member diversity** (added) | **supported**, and it explains the registered label | on all four sets the spread is 22–47 % below the frozen model's and 4–27 % below P_retrain's; ensemble-mean error jumps when a triple has three refit members |

## 2. Part 2: is open-loop error the right proxy?

### 2.1 Per goal and per arm

**What was tested.** For every goal with native trial outcomes:
- M7u1: 40 goals, P frozen;
- M7u2: 24 goals, P frozen;
- M7u3: 24 goals, PF frozen and PR refit.

Each goal got model-quality metrics from the arm's own model, and each metric was tested as a predictor of whether the
arm reached that goal. AUROC is the probability that reached goals have the better metric (0.5 = no relation). Exact
permutation p values (one-sided) are in brackets.

| metric (quality orientation) | M7u2 P (7/24) | M7u3 PF (7/24) | M7u3 PR (5/24) | M7u1 P (22/40) |
| --- | --- | --- | --- | --- |
| open-loop error of the goal's recorded witness at τ | 0.61 (.21) | 0.69 (.08) | 0.82 (.015) | 0.63 (.09) |
| witness closest predicted distance to the goal | 0.73 (.11) | 0.63 (.21) | 0.76 (.05) | 0.71 (.04) |
| open-loop error along the executed trial words, 16 / 32 | 0.66 / 0.71 | 0.56 / 0.48 | 0.42 / 0.48 | 0.42 / 0.51 |
| executed 4-word block error | 0.42 | 0.40 | 0.52 | 0.46 |
| tick-0 ranking AUROC@64 (§2.3) | 0.56 | 0.61 | **0.17** (reversed, two-sided p .035) | n/a |
| tick-0 top-1-of-64 hit rate | 0.45 | 0.82 (.003) | 0.51 | n/a |
| **model-free difficulty**: behaviour reach rate (q for M7u1) | 0.60 (.24) | **0.80 (.011)** | **0.76 (.04)** | 0.63 (.09) |

**Witness error correlates with goal difficulty.** For M7u2 frozen / M7u3 frozen / M7u3 refit, its Spearman correlation
with τ is 0.27 / 0.30 / 0.38, and with the behaviour reach rate −0.08 / −0.25 / −0.59.

**Within the same goal (difficulty held fixed),** on the 10 discordant M7u3 goals (PF-only 6, PR-only 4), the arm whose
model had:

| criterion | won |
| --- | --- |
| the lower witness error | 6 of 10 (p = 0.38) |
| the closer predicted witness | 5 of 9 |
| the higher ranking AUROC@64 | 4 of 10 |

### 2.2 Reading

- **Across goals:** open-loop (witness) error points the expected way in all four arm sets. Model-free difficulty does
  as well or better. The two are correlated: a shorter, easier goal has both a smaller open-loop error and a higher reach
  rate.
- **Within goals:** lower open-loop error did not identify the model that reached the goal.
- **Conclusion:** **I find no evidence that open-loop error predicts native reach beyond goal difficulty.** No other
  metric does so consistently either. The one nominal hit (top-1-of-64 for PF, p = .003) does not replicate on M7u2 (same
  model and machinery) or for PR, and it is partly difficulty. One metric reverses for PR. About 40 relation tests were
  run, so isolated p ≈ .003–.05 values are expected by chance.
- **At the model level** only two models have native outcomes on the same goals (PF 7, PR 5; not significant either way),
  so no offline metric can be validated or refuted against native reach with existing data.
- **The registered metric measures something the planner does not use.** It is the ensemble-*mean* trajectory error,
  and its "regression" is the diversity effect of §1.7. Per-member open-loop error shows no refit regression.

### 2.3 Proposed planning-relevant metric: tick-0 plan-ranking AUROC

**Definition.**
1. **Candidates.** Take every held-out recorded sequence from the shared reset row; all episodes start from the identical
   tick-0 state.
2. **Score.** Roll its first 64 words through the model (all members) and score it for goal g with the planner's own
   `m7u_planner.score`: horizon 64, the m7u1 cost, mean + 1.0 · std over members.
3. **Label.** Native valid airborne reach of g's ±150 box within input ticks 1..64.
4. **Per-goal AUROC.** P(score of a reaching sequence < score of a non-reaching one), ties ½.
5. **Model metric.** The mean over goals with at least 3 reaching candidates (the goal's own source sequence excluded).

**Why it is planning-relevant.** It grades the exact computation of the planner's first decision (same horizon, same
score, same member rule) against native ground truth for every candidate. That is possible only at tick 0, where all
recorded sequences share one state. It is computable from preserved data for any model.

**What it shows** (candidates = the 360 M7u2-pool sequences, held out for every model):

| | frozen | P_retrain | P_refit |
| --- | ---: | ---: | ---: |
| M7u2 goals (15 included): AUROC@64 | 0.712 | 0.729 | **0.826** |
| member AUROC@64 | 0.635 / 0.747 / 0.715 | 0.766 / 0.719 / 0.681 | **0.796 / 0.805 / 0.813** |
| M7u3 goals (6 included): AUROC@64 | 0.821 | 0.824 | 0.871 |
| AUROC@128 (M7u2 21 / M7u3 18 goals) | 0.647 / 0.661 | 0.645 / 0.648 | 0.685 / 0.693 |
| top-1-of-64 hit rate @64, M7u2 / M7u3 goals (behaviour base 0.016 / 0.012) | 0.119 / 0.077 | 0.034 / 0.029 | 0.089 / 0.150 |

**Against seed variation.**
- **M7u2 goals.** The refit triple beats all 20 M7u1-recipe triples (0.652–0.805, median 0.744). Its three members are
  the top three of nine (exchangeable probability 1/84 = 0.012). It is better on 13 of 15 goals (sign p = 0.004).
- **M7u3 goals.** Only 6 goals qualify; the refit triple ranks 2 of 21 but wins only 2 of 6 goals.
- **Seed spread.** The M7u1-recipe member SD is 0.047.

**The two offline metrics disagree about the refit.**
- **Ensemble-mean open loop:** worse.
- **Tick-0 ranking at the planner's horizon:** better, beyond seed variation on M7u2 goals.

At 128 ticks the ranking metric follows open-loop accuracy (member ρ = 0.62–0.63), and the refit's advantage shrinks.
At 64 ticks it does not (ρ = 0.15–0.32). The refit's gain is concentrated where its added data are, the first ~64 ticks
from rest, consistent with its later status divergence (§1.5).

### 2.4 What the data can and cannot establish at their resolution

**Can establish.** Offline differences between models beyond seed variation, at member and ensemble level (§1.7, §2.3).
Per-goal reach is strongly shaped by goal difficulty.

**Cannot establish.**
- **That any offline metric predicts native reach.** With 24 goals and 5–7 successes, a per-goal predictor needs AUROC ≳
  0.72–0.76 to reach one-sided p ≤ 0.05. Moderate predictors (0.6–0.7) can be neither shown nor excluded.
- **Whether the refit is natively better or worse.** The M7u3 design detected only a net +5 goals; the observed −2 is
  compatible with a modest gain or loss.
- **Model-level validity.** There are only two models with native outcomes on shared goals.

**So the proposed metric is chosen on construct grounds, not demonstrated predictive validity.** A native gate remains
the arbiter, and any later validation needs within-goal (paired) designs with many more goals than 24.

## 3. Part 3: proposed bounded offline model study `m7u4` (zero native ticks)

### 3.1 Question and scope

**Question.** Does any of three training recipes, chosen from Part 1's supported explanations, improve the
planning-relevant metric of §2.3 over the frozen M7u1 recipe by more than seed variation, without a rollout-accuracy
regression?

**Scope.**
- **What runs:** offline training and forward-pass evaluation only. Zero native ticks; no BattleShip process; no
  transport import.
- **What stays fixed:** the algorithm (learned dynamics ensemble + the unchanged planner), Track 1 `btt_s9_b8_v1`, and
  M7n v3 + reward v2 as the selected baseline.

### 3.2 Recipes

All recipes keep the M7u1 architecture and the stratified episode bootstrap:
- E = 3, trunk 370 → 256 → 256, heads H1–H7, vocabulary caps 160 / 128 / 64;
- Adam 3e-4, batch 1,024 per member, one-step teacher-forced loss;
- trained from scratch, no early stopping, the last step is the model.

| recipe | data | steps | loss | tests | Part 1 basis |
| --- | --- | ---: | --- | --- | --- |
| **R0** `m7u1_recipe` (baseline) | M7u1 80 training episodes | 6,000 | M7u1 weights | reference | — |
| **R1** `refit_recipe` | M7u1 80 + M7u3 training pool 540 | 6,000 | M7u1 weights | is the refit's tick-0 ranking gain a recipe effect beyond seeds? | §2.3: only lever with an offline planning gain |
| **R2** `refit_long` | as R1 | **34,400** (≈ 102 draws per transition, 4 × M7u1's 25.5) | M7u1 weights | does training nearer convergence help? | §1.1: every run unconverged |
| **R3** `refit_long_dyn` | as R1 | 34,400 | **H6 Δx / Δy weight 4 → 40**, nothing else changed | does weighting the per-tick displacement help? | §1.6: the trained objective misses the one-step quantity that tracks rollouts (ρ 0.65–0.87). The least supported treatment for ranking (member ρ 0.15 at 64 ticks) |

**The ladder.** Each recipe adds one change to the previous one: data, then length, then objective. Every treatment is
tested against R0. Adjacent contrasts (R2 − R1, R3 − R2) are reported for attribution only.

**Not proposed:**
- *per-sample matching*, *normalization* and *reweighting* recipes (contradicted, §1.8);
- a multi-step unrolled loss (open question 3);
- a larger ensemble, because it changes the planner's score statistics.

### 3.3 Seeds

**Five per recipe**, all of them used:

| recipe | seeds |
| --- | --- |
| R0 | 0 = the frozen M7u1 model and 1 = P_retrain (both reused, digest-verified); new 2, 3, 4 |
| R1 | 0 = P_refit (reused after an identity retrain reproduces `74c8861e…`; otherwise stop and report, as M7u3 decision 6); new 1–4 |
| R2, R3 | new 0–4 |

That is 17 new trainings. A seed sets the initialisation, the bootstrap and the batch streams; CPU training at 6
threads is bit-reproducible (M7u3 identity retrain). A failed run is not replaced by another seed.

### 3.4 Data roles

- **Training:** M7u1's 80 training episodes (all recipes); the M7u3 training pool `t000..t539` (R1–R3).
- **Tuning / validation:** **M7u1's 12 held-out episodes only.** They serve training-health checks (non-finite loss,
  vocabulary caps) and a reported validation table (one-step loss, mid-episode and reset-row open loop, per member).
  **No hyperparameter is selected.** Every value above is fixed in this document, so the training pool is used in full
  and R1 seed 0 can be P_refit. A training-pool validation split is the alternative (open question 4).
- **Final test, exactly once,** after all 20 models are trained and pinned: the **M7u3 goal pool** `g000..g539`.
  - The driver refuses to open goal-pool sidecars before the final phase.
  - **Goals:** the M7u3 non-overlap selection `m7u3_tick0_goal_v1`, continued past 24 until the pool is exhausted. It is
    prefix-stable, so the first 24 are the registered M7u3 goals; the 24-only figure is reported as a subset.
  - **Candidates:** all 540 sequences, minus each goal's own source.
- **No role:** the M7u2 pool (read in this diagnosis); human recordings, the TAS and crossing fixtures (never, in any
  role).

### 3.5 Registered decision rule `m7u4_offline_rule_v1` (fixed before any training)

**Metric M (per model).** Tick-0 ranking AUROC@64 (§2.3) on the final test, as the mean over included goals. A goal is
included when ≥ 3 of its candidates natively reach it within 64 ticks; this is model-independent.

**Fallbacks.**
- If fewer than 12 goals qualify at 64, the pre-declared fallback is AUROC@128 with labels within 128.
- If fewer than 12 qualify there too, the test is **INSUFFICIENT** and no decision is made.

**Per treatment r ∈ {R1, R2, R3} against R0** (5 seeds each):

| condition | requirement |
| --- | --- |
| significance | exact one-sided Mann–Whitney p_r for M(r) > M(R0), Holm-adjusted over the three treatments at family α = 0.05. With 5 vs 5: U ≥ 23 (p = 0.016) at the first two Holm steps, U ≥ 21 (p = 0.048) at the third |
| effect | median M(r) − median M(R0) ≥ **0.05** (≈ 1.1–1.3 seed SDs) |
| guard | median strict from-reset **per-member** open-loop error at h64 on the goal pool, over the recipe's 15 members ≤ **1.15 ×** R0's; no vocabulary overflow, no non-finite loss, every digest pinned |

**Outcomes.**

| outcome | condition | meaning |
| --- | --- | --- |
| **GATE_JUSTIFIED** | some r meets all three conditions | the designated recipe is the passing r with the largest median M; its designated model is its **median-M seed** (pre-declared, no best-seed pick) |
| **NO_GATE** | otherwise | readings, by the condition that failed: `SMALL_GAIN` (significant, effect < 0.05), `GAIN_WITH_ROLLOUT_REGRESSION` (guard), `NO_GAIN` |
| **INSUFFICIENT** | too few goals, a missing seed, a cap, or a digest problem | no result |

**Power.** Under a normal shift of 1.5 / 2 / 2.5 seed SDs, the significance condition holds with probability ≈ 0.43 /
0.68 / 0.86. The refit's apparent gain on M7u2 goals was ≈ 2 SDs above the M7u1-recipe triple median.

**Reported, never deciding:**
- AUROC@128 and the top-1-of-64 lift;
- the 24-goal subset;
- ensemble-mean open loop (the M7u3 metric, for continuity) and member spread;
- one-step losses per head;
- adjacent contrasts;
- per-goal relations to the 24 M7u3 native outcomes.

### 3.6 What each outcome would and would not justify

**GATE_JUSTIFIED** justifies *proposing* a native gate: the designated model's planner arm against P_frozen on fresh
non-overlapping goals from a fresh pool, with the unchanged M7u3 machinery.
- **Why it must be powered for moderate effects** (open question 9): the offline metric has no demonstrated link to
  reach, and N = 24 detects only +5 goals.
- **If the only passing recipe is R1:** M7u3 already tested one R1 seed natively (5 vs 7). A native gate is worth running
  only at a size that could detect the effect the offline gain implies.

**NO_GATE** justifies no native gate on model grounds. These recipes do not improve the planner's tick-0 decision
quality beyond seed variation. The next step would be §4's direction, not more planner gates.

**Neither outcome** changes the selected baseline or establishes reach, landing, crossing, targets or a clear.

### 3.7 Budget and caps

**Compute basis.** CPU, 6 torch threads, one process. Measured step time: 53 ms (identity retrain 318 s / 6,000 steps)
and 42 ms (gate refit); 53 ms is used.

| phase | work | projected |
| --- | --- | ---: |
| preparation (separate authorisation) | code, unit tests, synthetic e2e; identity retrain of R1 seed 0 | ≈ 6 min CPU + tests |
| R0 | 3 new × 6,000 steps | ≈ 17 min |
| R1 | 4 new × 6,000 steps | ≈ 22 min |
| R2 | 5 × 34,400 steps | ≈ 153 min |
| R3 | 5 × 34,400 steps | ≈ 153 min |
| validation | 20 models, M7u1 held-out, forward only | ≈ 10 min |
| final test | 20 models × (540 × 64 and × 128 rollouts, strict open loop 540 × 96) + rule | ≈ 15 min |
| **total** | | **≈ 6.2 CPU-hours** |

**Caps.**
- **Per run:** 600 s for a 6,000-step run, 3,000 s for a 34,400-step run.
- **Study:** **9 h** global wall cap, summed over at most 3 sessions.
- **Interruptions:** an interrupted run may be restarted from scratch, because training is bit-reproducible, so a restart
  selects nothing. A completed run is never rerun. A cap reached means **INSUFFICIENT**, with no extension.

**Memory.**
- main-process private ≤ **3,072 MB** (the M7u3 gate's main process, which ran the refit on 344,644 transitions, peaked
  at 1,622 MB);
- ≥ 4,096 MB available at session start;
- stop if system available memory falls below 1,024 MB;
- no worker processes.

**Outputs.** Git-ignored `runs/m7u4/`, then a verified D: increment.

### 3.8 Integrity and absolute constraints

**Integrity.**
- **Pins.** Model file and parameter digests are pinned per run before the final phase; the three reused models are
  verified before and after.
- **Optimizers.** Exactly one optimizer per training run, none in the evaluation process (the M7u2 / M7u3
  `no_optimizer` guard).
- **Unchanged code.** m7u1 / M7u2 / M7u3 files stay unchanged (hash checks).
- **Evaluation check.** Before any training, the evaluation code must reproduce the gate's recorded D5 M7u1-held-out
  figures for the three existing models (frozen 121.35 / 289.52 / 644.63 …).
- **Single access.** The final-test goal set and labels are derived once, in the final phase, after every model is
  pinned.

**Constraints (guide and handoff).**
- No native RNG inspection, logging, control, comparison or hashing (seeds are Python-side).
- The submit / consume / input contract is untouched (no native step at all).
- Canonical controller words remain replay truth.
- No native, decomp or submodule change.
- No human recording, TAS or fixture in any role.
- Nothing is committed or pushed by the study.

### 3.9 Implementation outline (new files only) and decisions needed

**Code.**

| file | contents |
| --- | --- |
| `rl/m7u4_train.py` | recipe table; `m7u3_refit.refit` / `train_loop` reused, plus a loss wrapper whose H6 weights are a parameter. A test checks bit-equality with `um.losses` at default weights |
| `rl/m7u4_metric.py` | ranking AUROC, top-1-of-64, per-member open loop |
| `rl/m7u4_rule.py` | rule + self-test |
| `rl/m7u4_study.py` | driver: phases, caps, pins, goal-pool access guard |
| `rl/m7u4_tests.py` | tests on synthetic worlds and recorded M7u1 held-out data |

**Decisions requested, in order.** None is authorised by this document.
1. The design, with answers to §5.
2. The zero-native-tick preparation, including one identity retrain.
3. The study run.

## 4. Part 4: can this line reach a wall-top landing or one real target from tick 0 within two or three gates?

**What the line has shown.**
- **M7u1:** local reach of rare rising points after own prefixes, 22 / 40.
- **M7u2 / M7u3:** from tick 0, 7 / 24 rare airborne points within 128 ticks, twice (4 of 13 units, then 7 of 24
  independent goals). Goals lie within about 1,800 units of the spawn horizontally and 3,000 vertically.
- **Model limits:** half of all 16-tick open-loop predictions miss the ±150 box; witness acceptance from reset is 0–1 of
  24; more own data did not improve native reach detectably.

**One real target from tick 0 is plausible within one or two gates, but only with a change this study excludes.** The
planner's cost would have to aim at a target break; H7 already predicts breaks.
- **Feasibility:** central targets are broken routinely by random play and PPO, and the TAS breaks ID 9 at tick 51.
- **Value:** it would show nothing new for the project. Only a left-side target (IDs 1, 6, 8) would.

**A wall-top landing from tick 0 is implausible within two or three gates of this line alone.**
- **Horizon.** The TAS reaches the left targets at ticks 368–446, and PPO's only qualified crossing took off from L1 at
  tick 2,318. The demonstrated competence is single goals within 128 ticks at ≈ 0.3 success. Chaining three or four such
  waypoints at 0.3 gives ≈ 1–3 %.
- **Data.** Random tick-0 behaviour never passed x = −1,650 (M7f), and L0 contact lines are absent from every training
  set. The proposal itself flags that "landings on a line never touched are mispredicted until data arrives".
- **Precision.** The landing needs a narrow double-jump / up-B timing window: a start ≥ 1,639 with a +1,361 rise (M7p).
  That is exactly where open-loop errors of hundreds of units after 32–64 ticks matter.

**What would have to be true:**
1. M7u4 returns GATE_JUSTIFIED with a large effect, **and** a powered native gate confirms reach well above 0.3.
2. A frontier data-collection round puts the model on L1, the wall face and L0 (native ticks).
3. Waypoint chaining reaches per-waypoint success ≥ 0.6–0.7.
4. The planner composes the L1 → L0 manoeuvre inside its 64-tick horizon.

That is at least three gates even if each succeeds.

**What argues for stepping back and combining the lines.**
- **Each line has the strength the other lacks.** The planner's best evidence is *local* control after supplied
  prefixes, and it composes timed aerial moves that PPO has never produced. The PPO line (M7n v3 + reward v2) has the
  long-horizon competence (5.5 targets per episode). PPO episodes do reach L1 and attempt the flight: the seed-1 geo4
  final (a rejected recipe) left L1 in 52 of 100 episodes, with 74 flights and two L0 landings (M7p wall-top census).
  The L1 rate of the selected v3 models was not measured.
- **A hybrid uses the strongest evidence of both.** PPO-recorded prefixes would bring the game to L1, and the planner
  would control the final 64–128-tick L1 → L0 manoeuvre. That is exactly M7u1's validated "after own prefix" scope, and
  the M7p flight comparison isolates the timing the planner would search.
- **Its prerequisite is model data in that region.** Native replay of PPO artifacts supplies it; that is a gate.
- **The deciding consideration.** If M7u4 returns NO_GATE, the hybrid is the better next decision than further
  from-tick-0 planner gates. Even after GATE_JUSTIFIED it deserves comparison.

## 5. Open questions for you

1. **Metric.** Register tick-0 ranking AUROC@64 as the decision metric, knowing its link to native reach is unvalidated
   (§2.4)? Or prefer AUROC@128 (tracks open-loop accuracy) or the top-1-of-64 hit rate?
2. **Recipe ladder.** Data → length → objective (R1–R3)? Or swap in "long training on M7u1 data only" to separate length
   from data?
3. **R3's change.** The Δx / Δy loss weight 40, fixed a priori? Or a multi-step (unrolled, continuous-feedback) loss? I
   treated the latter as an objective change rather than an algorithm switch, but did not propose it; please rule.
4. **Validation split.** Train on the full training pool (keeps R1 seed 0 = P_refit, no tuning)? Or hold out 108
   training-pool episodes as a from-reset validation split, which allows one pre-declared selection but changes R1's data?
5. **M7u2 pool.** No role (proposed)? Or a reported-only replication set beside the final test?
6. **Seeds.** Five per recipe with three reused (proposed)? Three seeds per recipe cannot pass a Holm-adjusted 5 % test
   (3 vs 3 minimum p = 0.05).
7. **Thresholds.** Effect 0.05, guard 1.15 ×, ≥ 3 positives per goal, ≥ 12 goals, the AUROC@128 fallback, Holm at 0.05?
8. **Test goal set.** The extended non-overlap goal set from the goal pool (proposed, for resolution)? Or the 24
   registered goals only?
9. **A later native gate after GATE_JUSTIFIED.** Size it for moderate effects (≥ 48 goals or replicate streams), not
   N = 24?
10. **Budget.** ≈ 6.2 CPU-hours, a 9 h wall cap over at most 3 sessions, 3 GB memory: acceptable?
11. **Direction (§4).** Run M7u4 first? Go directly to designing the PPO-prefix / planner-suffix hybrid? Or both in
    sequence?

## Appendix A. Scratch analyses (outside the repository; not preserved as evidence)

**Location.** `%TEMP%\claude\…\scratchpad\m7u4\`. All scripts were run with `python -B` and a bytecode-free
environment.

| script | what it did |
| --- | --- |
| `common.py` | pinned loaders: `m7u2_gate.load_frozen`, `m7u3_gate.load_retrain`, and the refit with both pins checked |
| `s1_composition.py` | data composition, bootstrap passes, vocabulary diff (no forward pass) |
| `s2_losses.py` | full-data teacher-forced losses per model / member / head / tick window, decoded one-step accuracy. Sanity: the decomposition reproduces `um.losses` on the logged 4,096 held-out transitions (1.001854) |
| `s3_openloop.py` | open loop from reset, from t = 32 / 64 and on mid-episode grids; divergence, takeoff, bootstrap CIs. It reproduces the M7u3 strict M7u2-pool figures exactly |
| `s4_reach_relation.py` | per-goal witness and trial metrics for M7u1 / M7u2 / M7u3 |
| `s5_members.py` | member recombination (84 triples), spread and mean member error |
| `s6_ranking.py` | the tick-0 ranking metric, members and triples, top-1-of-64, relations |
| `s7_inputs.py` | input / target distribution shift (no forward pass) |
| `s8_relation_fixed.py` | all Part 2 relations recomputed with one orientation, plus difficulty confounds |

**Digests.** Every script that loaded the models checked all three file and parameter digests before and after; all
were unchanged.

**Two orientation errors corrected in my scratch work.** `m7u_analysis.auroc` returns P(score_pos > score_neg), and a
lower planner score is better. Two first-pass computations therefore had inverted AUROCs:
- the ranking metric in `s4`;
- the relation tests in `s4`.

Every figure in §2 comes from the corrected `s6` / `s8`, which use one stated orientation throughout.
