# M7u3 proposal: refitting the M7u model with own tick-0 data, against the frozen model (2026-10-01)

**Status: proposal for review.** This session authorised one new document and nothing else.
- **Not done:** nothing was implemented, launched, collected, trained, committed or pushed.
- **Not edited:** no existing document, evidence file or M7u1 / M7u2 file.
- **Read-only analysis:** three analyses informed this proposal (§1.2, §3.4, appendix A). They read preserved `runs/m7u` and `runs/m7u2` evidence, ran forward passes of the frozen model only, and wrote nothing in the repository.

**Unchanged:**
- M7u2's registered PASS (P 7 / RC 0 / S 0 of 24, one seed) and its scope;
- the selected baseline, **M7n v3 + reward v2** (Track 1 PPO).

**The one question.** Compared with the frozen M7u1 model, on fresh goals that are independent by construction: does refitting the same M7u architecture on M7u1's data plus a newly collected tick-0 own-behaviour training pool
- reduce from-rest model failures, and
- increase tick-0 goal reach?

**Scope label**, carried by every record: *refit-versus-frozen test of planner-controlled reach of rare behaviour-drawn
airborne points from the normal tick-0 reset (one seed, one refit, 24 non-overlapping goals); not a landing, wall-top
reach, crossing, target result or clear.*

## 0. Verified state (read-only, 2026-10-01)

| item | state |
| --- | --- |
| parent | `main` = `origin/main` = `1a68a7b`. The ten untracked M7u2 files (`docs/rl_model_planning_m7u2_*` × 6, `rl/m7u2_{gate,goals,rule,tests}.py`) are untouched. This document is the only file added |
| submodules | `decomp e4f06348` (rl-main), `libultraship 805f1950` (m6/raphnet-bypass), `torch 3aa9c97`, as pinned. No native change is proposed |
| guide | the external `guide.md` (parent directory, revised 2026-09-22; its milestone narrative stops at M7g) and `docs/rl_handoff_2026-09-28.md` were read. §8 applies their absolute constraints |
| frozen model | `runs/m7u/gate/_gate/model.pt`: `a4bd30e5…`, parameter digest `0e70af78…`, vocabulary 61 / 16 / 28, 3 members, clock track `16318edf…`. The read-only analysis loader re-checked every pin |
| M7u2 evidence | `runs/m7u2/gate/_gate/pool.json` `b6f3a444…`, `goals.json` `f16ac74a…`, `state.json` `f1fc4458…`; approval `4802bf32…` |
| D: | Present: base `2026-09-28`; increments `_incr_m7r`, `_incr_m7s`, `_incr_m7t_logs`, `_incr_m7u`, `_incr_m7u_logs`, `_incr_m7u2`; snapshots `2026-09-30_m7u1`, `_m7u1_r2`, `_m7u2`. The M7u2 record states combined coverage of 398,054 `runs/` files, 0 uncovered. **Not re-walked in this session** |

## 1. What the record says, and what this proposal measured

### 1.1 M7u2 (registered PASS, one seed)

- **Outcome:** P 7, RC 0, S 0 of 24 from the normal tick-0 reset; b − c = 7 against both controls.
- **Correlation:** the 24 goals formed **13 independent units** (21 overlapping pairs, 5 groups).
  - P reached 4 units; RC and S reached none.
  - The exact one-sided sign probability is 2⁻⁴ = 0.0625 at the unit level, against 2⁻⁷ at the goal level.
- **Failures:** 17 P failures, 12 MODEL and 5 PLAN (MODEL share 0.71).
- **Witness:** the ensemble accepted the pool episode's own recorded path from tick 0 for **1 of 24** goals.

### 1.2 Open-loop error from the reset row, measured strictly

**What M7u2 measured.** M7u2's results give "open-loop error from tick 0" as 106 / 298 / 559.
- The figure comes from `m7u_analysis.heldout_accuracy` applied to the pool: 200 sha-ordered start ticks drawn from input ticks 0–64 of the pool episodes.
- It is therefore an **early-window** figure. Few of those starts are the reset row itself.

**What this proposal measured.** The strict figure, computed offline:
- frozen model, forward passes only, parameter digest unchanged;
- one rollout per M7u2 pool episode, from its reset row, over its own recorded words.

| measure (frozen m7u1 model; median Chebyshev error of the ensemble-mean position) | starts | 16 ticks | 32 | 64 | 96 |
| --- | --- | ---: | ---: | ---: | ---: |
| m7u1 held-out, mid-episode (m7u1 results) | 200 sha starts in 12 episodes | 121 | 290 | 645 | — |
| M7u2 pool, early window (M7u2 results) | 200 sha starts at input ticks 0–64 | 106 | 298 | 559 | — |
| **M7u2 pool, strict from reset (this proposal)** | the reset row of all 360 episodes | **153** | **333** | **714** | **908** |
| strict: p90 | | 680 | 989 | 1,632 | 2,038 |
| strict: share of rollouts outside the ±150 box | | 0.50 | 0.72 | 0.90 | 0.94 |

Reading:
- **Drift is largest from the exact reset row.** It is the largest of the three measures: +26 % at 16 ticks, +15 % at 32 and +11 % at 64 over the
  mid-episode figure.
- **Consistent with the witness result.** Goals lie at τ 32–96, so a typical recorded path ends 700–900 units from where the model puts it. That fits the 1 / 24 witness acceptance.
- **Support is modest.** This supports the premise that from-rest prediction is the main limit, but only for one model on one seed.

### 1.3 Why tick-0 data, and what this test cannot separate

**Why.**
- M7u1 trained on 80 behaviour episodes: **80 reset starts**, one per episode, and about 15,000 transitions in input ticks 0–192.
- Every M7u2 / M7u3 trial starts at that reset row and stays inside input ticks 0–192 (128 controlled + 64 imagined).
- The refit adds 360 own reset starts (§3.1). Its training set then holds 440 reset starts and about 84,000 transitions in that window.

**Not separable by this design** (stated now, and carried into §9):
1. **Tick-0-specific data versus more data of any kind.**
2. **The data versus a changed training trajectory.** Any change to the data alters every batch, so retrain variance and the data effect are confounded.

The design narrows (2) without removing it:
- same seed;
- same pipeline;
- a preparation check that the refit pipeline with an empty pool reproduces the frozen parameters (§3.2).

Removing (2) would need a third arm (open question 4).

## 2. Arms

| arm | model | commanded | scored on | role |
| --- | --- | --- | --- | --- |
| **P_frozen** | M7u1 ensemble, digest-checked (`a4bd30e5…` / `0e70af78…`) | g | g | reference: the M7u2 machinery on fresh independent goals |
| **P_refit** | the refit (§3.2) | g | g | treatment |
| **RC** | none: candidate 0 at every decision; no model is evaluated | — | g | no-model control. It is also the behaviour policy of both pools |
| **S_refit** | the refit | π(g) = goal (k + 12) mod 24 | g | command control for P_refit |

**Planner, unchanged for every model arm:**
- N = 64 candidates, H = 64, execute 4 words then replan;
- 15 mutants, 64 refill segments, 48 fresh plans;
- segments uniform over stick 9 × button 8 × tap / hold × length {1, 2, 4, 8, 16, 32}, so all 72 Track 1 combinations stay available;
- the m7u1 cost and score (mean + 1.0 · std over the 3 members).

**Common random numbers:** the four arms of goal k share the stream `m7u3|3|goal|k`.

**Why S uses the refit, and only the refit:**
- **Matched control.** The registered secondary compares P_refit with S. A matched command control holds P_refit's model fixed and changes only the command; S_frozen would change both the model and the command.
- **Not M7u3's question.** Whether P_frozen is command-specific is M7u2's question, already measured there (S 0 / 24).
- **Cleaner than M7u2.** Goals are non-overlapping by construction, so π(g)'s box never overlaps g's box.

**Not added** (each costs about 4–10 min; open questions 4 and 5):
- S_frozen;
- P_retrain: M7u1 data only, another training seed. It would separate the data effect from retrain variance.

## 3. Data: two separate pools and the refit

### 3.1 Training pool (Python seed 1)

- **Size and length:** 360 episodes, `t000`..`t359`, 72 per worker, from the normal reset. Each is truncated in Python after **192 words**, or ends earlier by a fall.
- **Behaviour:** candidate 0 of the fixed-draw stream `m7u3|1|train|t###` (N = 64). This is exactly the m7u1 / m7u2 behaviour policy, and RC's.
- **Why 192 words:** a 128-word trial imagines up to input tick 128 + 64, so 192 covers every clock tick the planner can imagine. The extra 64 words cost 23,040 ticks and about 40 s of pool wall time; restarts dominate the wall time.
- **Dose** (open question 1 asks whether 540 or 720 episodes are wanted instead):

  | quantity | M7u1 | refit |
  | --- | ---: | ---: |
  | transitions | 240,964 | 310,084 (+69,120, +29 %) |
  | reset starts | 80 | 440 |
  | transitions in input ticks 0–192 | about 15,000 | about 84,000 (about 27 % of the refit's data) |

- **Checks:**
  - each reset row equals the tick-0 record;
  - each word stream equals its offline regeneration;
  - each sidecar equals the streamed rows;
  - the platform equals the pinned clock track on every live row;
  - the entry set is exactly `t000..t359`.
- **Role: fitting only.**
  - Goal selection takes no training-pool argument; a test pins its signature.
  - Per-goal coverage is computed only after selection, and only reported (D8).

### 3.2 The refit

**Same as M7u1:**
- E = 3, trunk 370 → 256 → 256 (SiLU), heads H1–H7, vocabulary caps 160 / 128 / 64;
- Adam 3e-4, batch 1,024 per member, **S = 6,000 steps**;
- one-step teacher-forced loss;
- no early stopping and no checkpoint choice: the step-6,000 parameters are the model.

**From scratch, not warm-started.** A warm start would test "M7u1 plus extra steps on new data" and change the effective step count.

**Training seed 0.** This is M7u1's `GATE_SEED`, used for initialisation, the bootstrap and the batch generators. The only intended difference from M7u1 is the data.

**Data, by manifest:**
- **Included:** M7u1's 80 training episodes and the 360 training-pool episodes.
  - The M7u1 episodes are the `train_ids` of the pinned `collection.json`, read from their preserved sidecars.
  - They are indexed first, in M7u1's order.
- **Excluded, and checked:**
  - M7u1's 12 held-out episodes;
  - all 360 M7u2 pool episodes. M7u2 accepted that pool on the condition that it never trains a model;
  - every goal-pool episode. None exists until training has ended.

**Vocabulary and masks:**
- derived from the refit's own training split and frozen before training;
- recorded and compared with 61 / 16 / 28;
- exceeding a cap is INVALID, as in m7u1.

**Clock track:**
- rebuilt from all training episodes;
- must equal `16318edf…`. The pool episodes only add rows for ticks 0..192, and those must agree.

**Stratified episode bootstrap.** A new function; m7u1's `bootstrap_indices` is unchanged.
- **How it draws:** member m's generator (`SeedSequence([0, 7919, m])`) first draws 80 of the 80 M7u1 episodes exactly as M7u1 did, then 360 of the 360 pool episodes.
- **Why not plain:** a plain bootstrap over all 440 episodes would let the number of long M7u1 episodes per member vary as Binomial(440, 80/440), sd 8.1. That is about ±10 % of the bulk data.
- **Empty pool:** the draws reduce exactly to M7u1's.

**Sampling.** Uniform over each member's bootstrapped transitions, as in M7u1. Tick-0 data are not up-weighted.

**Logging.** The training loss on M7u1's held-out set is logged every 1,000 steps. It decides nothing.

**Pipeline identity** (preparation, zero native ticks; needs authorisation):
- The m7u3 refit function, run on M7u1's 80 episodes with an empty pool, must reproduce parameter digest `0e70af78…`.
- That makes P_frozen exactly "the refit pipeline without the pool".
- **If CPU training is not bitwise reproducible:** the preparation reports the maximum |Δparameter| and the 32-decision reproduction on the retrained model, and the user decides (open question 8).
- The check is not repeated inside the gate.

**After training:**
- the refit's file sha256 and parameter digest are written to the state record before the goal-pool phase starts;
- gradients are switched off and the model is set to eval mode;
- the optimizer is released, and the rest of the gate runs under `no_optimizer()`.

### 3.3 Goal pool (Python seed 2) and goals

**Pool.**
- **540 episodes**, `g000`..`g539`, 108 per worker, at most 128 words, stream `m7u3|2|pool|g###`, the same behaviour policy.
- Collected **after** the refit is frozen, so it cannot reach fitting, tuning or model selection.
- The same checks as §3.1.

**Eligibility, unchanged from M7u2:**
- τ ∈ [32, 96];
- the row at τ is valid and airborne, and is not the fatal-fall tick;
- y_τ − y_spawn ≥ 300;
- at most 1 of the 92 m7u1 reference episodes makes a valid airborne reach of the ±150 box within input ticks 1..128
  (reference `4337cc35…`).

**Selection `m7u3_tick0_goal_v1`.** Deterministic, from the goal pool and the reference only. It takes no outcome, model or training-pool argument.
1. **Order.** Episodes are taken in the order sha256(`m7u3|goal|<entry>`). Within an episode, its eligible τ are tried in the order sha256(`m7u3|goal|<entry>|<τ>`).
2. **Non-overlap.** The first τ whose ±150 box overlaps **no** registered goal's box is registered: max(|dx|, |dy|) > 300 against every registered goal. This is M7u2's overlap definition, so exact duplicates are excluded as a special case.
3. **Skips.** An episode with no such τ is skipped. The record keeps every skipped episode and every passed-over τ, with the goal it overlapped.
4. **Stop at 24,** one goal per episode. Fewer is **INCOMPLETE**: no fill, no relaxation, no second pool.
5. **Scramble.** π(k) = (k + 12) mod 24.

**Independence by construction.**
- The registered set's overlap graph has no edges.
- A brute-force check over all 276 pairs confirms it, and the minimum pairwise Chebyshev distance is recorded.
- So **24 goals = 24 independent units**, and every count in the rule is a unit count.
- Some dependence is inherent and is not removed: one model, one reset state, one seed.

### 3.4 Supply estimate (read-only, from the preserved M7u2 pool)

**Sanity check first.** M7u2's own selection was re-run on its stored pool sidecars and reproduced its goal digest `1af171cc…`. The rule above was then applied offline to the same 360 episodes. Eligibility gave 63 episodes and 823 points, as recorded.

| selection on the M7u2 pool | non-overlapping goals |
| --- | ---: |
| M7u2's registered goals, counted as overlap units | 13 |
| this rule, M7u2 sha order, sha-first τ only (no fallback) | 20 |
| **this rule, M7u2 sha order, with τ fallback** | **29** |
| this rule, 2,000 random episode and τ orders: mean (5th–95th percentile) | 26.4 (24–29); P(≥ 24) = 0.969 |

**Growth with the number m of eligible episodes** (600 random subsets each). The supply grows sublinearly:

| m | 40 | 47 | 50 | 55 | 60 | 63 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| mean goals | 21.2 | 23.1 | 23.6 | 24.9 | 25.8 | 26.4 |
| P(≥ 24) | 0.08 | 0.39 | 0.53 | 0.82 | 0.93 | 0.96 |

**For a fresh pool of G episodes:**
- m ~ Binomial(G, p), with p either the measured 63 / 360 = 0.175 or its Wilson 95 % lower bound, 0.139;
- P(≥ 24 | m) comes from the table above for m ≤ 63, and is **floored at the m = 63 value** for larger m.

| goal pool G | E[m] at p = 0.139 / 0.175 | P(≥ 24 goals), estimated |
| --- | --- | --- |
| 360 | 50 / 63 | 0.54 / 0.90 |
| 450 | 63 / 79 | 0.89 / 0.96 |
| **540 (proposed)** | **75 / 95** | **≥ 0.96 / ≥ 0.96 (floor)** |
| 720 | 100 / 126 | ≥ 0.96 / ≥ 0.96 (floor) |

**Choice: G = 540.**
- It keeps the INCOMPLETE risk small even at the lower-bound yield.
- It costs +123 s of wall time over 360.
- These figures are estimates (one prior pool, a binomial model, a conservative floor), not a guarantee.

**Why N = 24, not 30.**
- P(≥ 30) is only 0.035 at m = 63.
- The eligible points occupy 67 distinct 300-unit grid cells. A cell can hold at most one non-overlapping goal, so a 360-episode pool cannot supply more than 67.
- N = 30 would need G ≥ 720, and its supply would rest on an uncertain extrapolation (open question 6).
- N = 24 also keeps π and the arm counts comparable with M7u2.

**Rarity is a coarse screen (reported, not changed).**
- Each registered M7u2 goal's box was reached within 128 ticks by a median of **15 of the other 359 pool episodes** (range 0–27; one goal by none).
- "≤ 1 of 92" selects low binomial draws, so typical true behaviour rates are near 4 %. RC still reached 0 / 24.
- **For M7u3:** the 360-episode training pool will likely contain about a dozen early passes through a typical goal box. M7u1's training data held at most one each.
- That is the intended dose, not goal-pool leakage: the passes come from different episodes.
- It does bound what a PASS shows (§9). D8 reports the coverage per goal.

## 4. Trials

- **Start:** a fresh process and the non-consuming reset (input_tick 0, step_count 0).
  - The reset row is checked against the tick-0 record (`0bf8dbd7…`) **before the first word**.
  - A mismatch is INVALID, with zero ticks consumed.
- **Entries:** t = 0, an empty prefix, a 128-word budget, scored goal g. Any other entry raises before launch, as in M7u2's
  tests.
- **Per step:** consumed tick T → exactly one native update → input_tick T + 1. The driver checks that input_tick equals the number of words submitted.
- **Success:** the first valid reach (±150 per axis, airborne, valid, not the fatal-fall tick). It ends the trial as a Python truncation; no further word is submitted. Otherwise the trial ends at the budget or at a fall.
- **Dispatch:** 96 entries (24 goals × 4 arms, in a fixed arm order) over 5 workers with standby.
- **Determinism:** outcomes are deterministic functions of the model, the stream and the native state, with one known exception.
  - Batched and unbatched scoring differ by up to about 1e-4. M7u2's reproduction check: 32 / 32 choices identical, max |Δscore| 3.5e-5.
  - Such a difference can flip a near-tie between candidates.
  - The recorded words remain replay truth either way.

## 5. Rule `m7u3_refit_rule_v1` (N = 24 independent goals, one seed)

**Notation.** For each comparison X ∈ {F = P_frozen, R = RC, S = S_refit}:
- b_X = #(P_refit ∧ ¬X) and c_X = #(¬P_refit ∧ X);
- d = b_X + c_X;
- p_X = Σ_{i=b}^{d} C(d, i) / 2^d, the **exact one-sided sign probability**; p_X = 1 when d = 0.

| outcome | condition |
| --- | --- |
| INVALID | any integrity failure (§8). The rule never sees a partial run |
| INCOMPLETE | any tick, wall or memory cap, or fewer than 24 non-overlapping goals. Not a result; no retry |
| **PASS** | p_F ≤ 0.05 ∧ p_R ≤ 0.05 ∧ p_S ≤ 0.05 |
| **NULL** | b_F − c_F ≤ 1 |
| INCONCLUSIVE | otherwise; the record names each blocker (below) |

Each blocker an INCONCLUSIVE record can name:
- *primary not significant*: b_F − c_F ≥ 2 and p_F > 0.05;
- *not model-attributable*: p_R > 0.05;
- *undirected*: p_S > 0.05.

Properties:
- **Disjointness.** PASS and NULL cannot both hold: p_F ≤ 0.05 requires b_F − c_F ≥ 5.
- **Error control.** PASS requires all three exact tests (an intersection-union test). So P(PASS) ≤ 0.05 whenever any one of the three nulls is true, with no multiplicity correction. Under the primary null at p = 0.30, the false-PASS rate is ≤ 0.024.
- **Applied once.** The rule is applied once, to complete paired outcomes, after every success replay has been verified. No diagnostic quantity enters it.

**Smallest passing results** (one-sided α = 0.05):

| discordant pairs d | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| minimum b : maximum c | 5:0 | 6:0 | 7:0 | 7:1 | 8:1 | 9:1 | 9:2 | 10:2 | 10:3 | 11:3 |
| exact p | 0.031 | 0.016 | 0.008 | 0.035 | 0.020 | 0.011 | 0.033 | 0.019 | 0.046 | 0.029 |

**Minimum detectable effect.**
- **Smallest possible PASS:** a net gain of +5 goals with no reversal.
- **At 80 % power** for the primary, N = 24, one-sided 0.05:
  - **P_frozen at 0.30** (M7u2's unit rate was 4 / 13 = 0.31): P_refit must reach **0.57 to 0.70**, a gain of **+0.27 to +0.40**, about +7 to +10 goals of 24.
  - **P_frozen at 0.20 or 0.40:** the same gain range, +0.27 to +0.39.
- **The range** runs from "monotone" (the refit keeps every frozen success; the low end) to "independent arms" (the high end). The shared streams put the truth in between.
- **Other N, for comparison** (P_frozen 0.30): N = 30 needs a gain of +0.22 to +0.35; N = 36 needs +0.18 to +0.32.

**Operating characteristics of the primary condition** (P_frozen = 0.30, N = 24, ranges over the same two models):

| P_refit | P(PASS) | P(NULL) | P(INCONCLUSIVE) |
| --- | --- | --- | --- |
| 0.30 (no effect) | 0.00–0.02 | 0.68–1.00 | 0.00–0.29 |
| 0.50 | 0.30–0.54 | 0.03–0.16 | 0.43–0.54 |
| 0.60 | 0.56–0.89 | 0.00–0.04 | 0.11–0.39 |
| 0.70 | 0.81–0.99 | 0.00–0.01 | 0.01–0.18 |

**What these numbers mean.**
- M7u3 can detect only a **large** improvement. A moderate one (0.30 → 0.50) most likely ends INCONCLUSIVE.
- The secondaries rarely bind once the primary passes, as long as RC and S_refit stay near M7u2's 0 / 24.

## 6. Diagnostics (reported only; never an input of the rule)

**D1. Witness acceptance from tick 0.**
- For each goal, the goal-pool episode's recorded words 0..τ−1 are rolled from the reset row through each model, padded to 96 as in M7u2.
- A witness is accepted when ≥ 2 of 3 members predict a valid reach within τ.
- Reported: W_F, W_R and the paired 2 × 2 table (M7u2: W_F = 1 / 24).

**D2. Strict from-rest open-loop error** at 16 / 32 / 64 (and 96) ticks.
- One rollout per episode, from the reset row, over its recorded words, through both models.
- **Two data sets, both never fitted by either model:**
  - (a) the 540 goal-pool episodes;
  - (b) the 360 preserved M7u2 pool episodes. They are used for forward passes only, which M7u2's acceptance condition allows.
- **Reported:** medians, p90, the share > 150, and the per-episode paired differences (median difference; share where the refit is better).
- **Cross-check:** the frozen figures on (b) must reproduce §1.2 (153 / 333 / 714 / 908). A mismatch is reported as an analysis defect.

**D3. Failure attribution**, with M7u2's definitions (`m7u_analysis.trial_attribution`).
- Per P arm, with its own model: MODEL / PLAN for failures, PREDICTED / UNPREDICTED for successes.
- Reported over all failures and over failures without an ambiguity flag.

**D4. Cross-attribution** (new; forward passes only).
- Each P_frozen MODEL failure's executed words are re-rolled from the same decision states through the refit, and vice versa.
- Reported: the share of false reaches that the other model no longer predicts.
- This is the most direct same-input measure of "fewer from-rest model failures".

**D5. Continuity and regression.** For both models:
- M7u2's early-window measure (200 sha starts in ticks 0–64 of the goal pool);
- M7u1's mid-episode measure (its 12 held-out episodes, 200 sha starts). The frozen model must reproduce 121 / 290 / 645;
- one-step position and status accuracy on the goal pool.

**D6. As in M7u2:**
- executed-block calibration: median block error, blocks > 150, AUROC of the spread;
- ambiguity flags;
- the movement census, counting double jumps only from JumpAerialF/B entries.

**D7. P_frozen vs RC on the 24 independent goals**, with its exact sign probability.
- This is the unit-level check of M7u2's direction that M7u2 itself could not make.
- Descriptive only: it is not registered and decides nothing (open question 9).

**D8. Coverage per goal.**
- How many training-pool episodes, and how many M7u1 training episodes, make a valid airborne reach of the goal's box within input ticks 1..128.
- Computed only after selection. Reach outcomes are tabulated by coverage, descriptively.

**D9. Refit training record:** train and M7u1 held-out losses every 1,000 steps, vocabulary, transitions and wall time.

**Readings if the outcome is NULL or INCONCLUSIVE.** The wording is pre-registered, and no reading ever changes an outcome. Notation:
- O = the relative change of the median strict 64-tick from-rest error on the goal pool, refit vs frozen (D2a);
- ΔW = W_R − W_F.

| reading | condition | meaning |
| --- | --- | --- |
| no model gain from rest | O > −0.20 ∧ ΔW ≤ 1 | At this dose, the added data did not materially reduce from-rest rollout error. The limit lies in the model or its training form (one-step teacher-forced loss, capacity, unexported state), not in how densely the data cover the reset neighbourhood |
| model gain, no reach gain | (O ≤ −0.20 ∨ ΔW ≥ 3) ∧ b_F − c_F ≤ 1 | Prediction from rest improved, but reach did not. Search or the remaining error is binding; the PLAN share of P_refit's failures is expected to rise (D3) |
| regression | c_F − b_F ≥ 2 | The refit reached fewer goals. D8 shows whether the lost goals lie outside the training pool's coverage |
| not model-attributable | p_F ≤ 0.05 ∧ p_R > 0.05 | RC also reaches the points the refit gained |
| undirected | p_F ≤ 0.05 ∧ p_S > 0.05 | The refit sends the planner to more airborne points whatever the command |

## 7. Budgets

**Phase order:** P1 → training pool → refit → goal pool → goal selection → evaluation → diagnostics → success replays →
rule.

### 7.1 Native updates

The ledger refuses any request that would exceed a phase cap or the total, before it is sent.

| phase | native ticks (cap) |
| --- | ---: |
| P1 identity: exact from-tick-0 replays of m7u1 `g26_P` (171) and `g14_P` (183), and M7u2 `g14_P` (49) and `g03_P` (60) | 463 |
| training pool, 360 × 192 | 69,120 |
| refit training | 0 |
| goal pool, 540 × 128 | 69,120 |
| goal selection | 0 |
| evaluation, 24 goals × 4 arms × 128 | 12,288 |
| success replays from tick 0: every success of every arm, ≤ 96 × 128 | 12,288 |
| **total** | **163,279** |

- **Earlier gates:** m7u1 used 337,042 ticks of a 431,201 cap; M7u2 used 55,745 of 56,930.
- **Replays can never be cut by the tick cap:** it equals the number of trials × 128.

### 7.2 Wall time

The clock starts at P1; the zero-tick preflight precedes it, as in M7u2.

**Per-episode model.** Per worker, an episode costs a 2.24 s restart plus its ticks at 108.9 ticks per second. This was fitted to two records, and reproduces both within 0.3 s:
- M7u1 collection: 92 episodes, 272,145 ticks, 541.3 s;
- the M7u2 pool: 360 × 128 ticks, 246.0 s.

**Pessimistic column:**
- pools +35 %;
- training at the readiness probe ceiling;
- planning at 0.5 s per decision, unbatched;
- 48 success replays.

| phase | projected | pessimistic | cap |
| --- | ---: | ---: | ---: |
| P1: 4 single-env replays (M7u2's 2 took 8.6 s) | 20 s | 40 s | 120 s |
| training pool: 72 × (2.24 + 192 / 108.9) | 288 s | 400 s | 600 s |
| refit training: 6,000 steps × 58 ms (the m7u1 gate's measured 348 s), plus building about 310k transitions and loading | 385 s | 600 s | 900 s |
| goal pool: 108 × (2.24 + 128 / 108.9) | 369 s | 500 s | 750 s |
| goal selection | 1 s | 5 s | 120 s |
| evaluation: ≤ 2,304 planning decisions (3 planning arms × 24 × 32) at M7u2's effective 0.266 s, plus restarts | 613 s | 1,220 s | 1,500 s |
| diagnostics (forward passes) + success replays (about 8 s each; about 20 expected) | 280 s | 534 s | 900 s |
| **global** | **1,956 s (32.6 min)** | **3,299 s (55.0 min)** | **3,600 s** |

- **Caps:** reaching a phase cap or the 60-minute global cap ends the run INCOMPLETE. There is no extension.
- **After the run:** the D: increment is made outside the clock, as for m7u1 and M7u2.

### 7.3 Memory

The driver samples memory every 5 s; any breach is INCOMPLETE. M7u2 sampled the main process only; M7u3 also writes the whole-tree series to the run's memory log.

| quantity | cap | basis |
| --- | ---: | --- |
| main process, private | 3,072 MB | m7u1 peaked at 1,471 MB with 241k training transitions. The refit's about 310k projects to about 1.9 GB |
| whole tree (main, workers, every BattleShip and standby process), private | 9,216 MB | m7u1 measured 6,100 MB with the same 5 + 5 layout |
| whole tree, working set | 4,096 MB | m7u1 measured 2,483 MB |
| system: available memory / free commit during the run | ≥ 1,024 / ≥ 2,048 MB | protects the machine |

### 7.4 Readiness

Checked at the end of preflight, with zero ticks. A refusal consumes nothing and is not a result.
- at least 4,096 MB available and 10,240 MB free commit;
- a 40-decision timing probe from the tick-0 row with the frozen model: p95 ≤ 0.5 s;
- a 20-step training probe on a throwaway synthetic model (never the frozen model or the refit): median ≤ 0.10 s;
- no BattleShip process running;
- `runs/m7u3` absent.

## 8. Integrity, source, backups and absolute constraints

### 8.1 Integrity (the run is INVALID if any check fails)

**Identity and reproduction.**
- **Code hashes:**
  - the new m7u3 files and every reused file;
  - the m7u1 files must equal HEAD;
  - the M7u2 files must equal the hashes in `docs/rl_model_planning_m7u2_gate_approval.json`.
- **Environment and contracts:** environment profile `121e1d48…`, executable `30a3913b…`, world `ca1ac287…`, the state and planner contracts.
- **Record pins:**
  - m7u1 records: `29f0d70f…`, `8e14e9f8…`, `46d17d50…`;
  - M7u2 records: `b6f3a444…`, `f16ac74a…`, `f1fc4458…`;
  - reference `4337cc35…`;
  - tick-0 row `0bf8dbd7…`.
- **Frozen-model pins:** file, parameters, vocabulary, members, clock track, and track coverage of ticks 0..192.
- **Preflight decision reproduction.** Two sets must each give the identical choice with |Δscore| ≤ 1e-3:
  - 32 recorded m7u1 decisions, as in M7u2;
  - 32 recorded M7u2 tick-0 decisions: 8 goals × P / S × first / middle.
- **P1:** all four replays exact: words, every stored row field, reach tick, action digest.

**Tick 0 and contracts.**
- **Reset rows:** every reset row (both pools, every trial, every replay) equals the tick-0 record before the first word.
- **Entries:** every evaluation entry has t = 0, an empty prefix and a budget of at most 128 words, and is scored on g.
- **Tick count:** after every step, input_tick equals the number of words submitted.
- **Streams:**
  - pool word streams equal their offline regeneration;
  - the stream keys of the training pool (seed 1), the goal pool (seed 2) and evaluation (seed 3) are pairwise disjoint, and disjoint from every m7u1 and M7u2 key.
- **Records:** every sidecar equals its streamed rows, and the platform equals the frozen clock track on every live row.

**Models.**
- **Refit data manifest:** exactly M7u1's 80 training episodes plus `t000..t359`. It contains no M7u1 held-out, M7u2 pool or goal-pool episode.
- **Refit pipeline:** its clock track is `16318edf…` and its vocabulary stays within the caps.
- **Refit digest:** recorded before the goal pool, and unchanged before evaluation, after evaluation and after analysis.
- **Frozen digest:** unchanged throughout.
- **Optimizer:** exactly one exists in the run, inside the refit phase, over the refit's parameters only. After training, constructing any optimizer is guarded, and a source scan backs the guard.

**Goals and replays.**
- **Goals:** re-derived after the run with an identical digest. The re-derivation must show:
  - 0 overlapping pairs, by brute force;
  - one goal per episode;
  - a selection with no outcome, model or training-pool argument.
- **Replays:** every success of every arm is replayed exactly from tick 0: words, every row field, reach tick, action digest.

**Run hygiene.**
- the ledger stays within its caps;
- no BattleShip process is left running;
- outputs are written only under the Git-ignored `runs/m7u3`.

### 8.2 Source, approval and backups

- **Final source snapshot.** After preparation, all code (new and reused) and the approval template are copied to `D:\BattleShip_source_snapshots\<date>_m7u3`.
  - It is verified by the tool (`snapshot`, `verify`) and by an independent PowerShell re-hash.
  - No code changes after the snapshot.
- **Fresh approval identity.** `docs/rl_model_planning_m7u3_gate_approval.json` is written from a freshly printed template.
  - It names the snapshot.
  - It pins every identity, budget, cap and seed above, plus the rule digest and the goal-contract digest.
  - Nothing is carried over from M7u2's approval.
- **D: before.** Preflight verifies two things:
  - combined coverage of every `runs/` file over the base and every increment, with 0 uncovered;
  - the earlier D: records and manifests are byte-identical.
- **D: after.** A new increment, `D:\BattleShip_runs_backup\<date>_incr_m7u3`:
  - the tool's backup and verify both PASS;
  - an independent PowerShell re-hash covers every file (copy vs source vs manifest);
  - combined coverage is then 0 uncovered.

### 8.3 Absolute constraints (guide and handoff), all kept

- **No native RNG** inspection, logging, control, comparison or hashing. Seeds exist only as Python-side stream keys.
- **The exact submit / consume / input contract:**
  - the reset is non-consuming (input_tick 0, step_count 0);
  - one submitted word = one native update;
  - consumed_tick T → input_tick T + 1;
  - no hidden neutral step at reset, at a reach or at a pool truncation.
- **Replay truth:** canonical native controller words (buttons, stick_x, stick_y, consumed_tick), recorded from tick 0 by the unchanged M4 recorder. Track 1 indices are metadata only.
- **Track 1 `btt_s9_b8_v1` unchanged:** all 72 combinations stay reachable, as the m7u1 test of all 576 segment options checks.
- **No native or submodule change:** executable `30a3913b…`. Non-PORT decomp and byte matching are untouched.
- **No human recording, TAS or fixture in any role.** P1 replays only the project's own planner artifacts.

## 9. What each outcome would and would not demonstrate

### PASS

**Demonstrates**, on one seed, one refit and one set of 24 independent goals:
- refitting the M7u architecture on M7u1's data plus own tick-0 behaviour raised planner-controlled reach of rare airborne points from the normal reset, compared with the frozen model;
- the gain is model-attributable (against RC) and command-specific (against S_refit);
- every success replays exactly.

**Does not demonstrate:**
- that tick-0-specific data caused the gain, rather than more data or a different training trajectory (§1.3);
- replication across seeds, refits or pools;
- reach of points the training pool never passed through early (D8);
- goals beyond 128 ticks, or sequences of goals;
- a landing, the wall top, a crossing, targets or a clear;
- any advantage over PPO;
- any change to the selected baseline.

**Would motivate:** a separately designed attribution and replication step, for example P_retrain plus an equal-size non-tick-0 data control, or another seed. Not planned here.

### NULL (b_F − c_F ≤ 1)

**Demonstrates:** at this dose (360 reset starts, +29 % transitions), refitting did not raise reach on independent goals by an amount this test can detect. The §6 readings say where the limit lies.

**Does not demonstrate:**
- that no amount or form of tick-0 data helps;
- anything about other seeds.

It does not reverse M7u2's registered PASS.

**Would motivate:** stopping this configuration. Depending on the reading, the next question would be a change of model or training form ("no model gain") or a search-side question ("model gain, no reach gain"). Each would be a new decision.

### INCONCLUSIVE

**Demonstrates** only the named blocker. At N = 24, a moderate effect lands here most often (§5).

**Would motivate:** revising the design (more goals, replicate streams or a larger pool), not rerunning it.

### INCOMPLETE or INVALID

Not results. There is no retry, extension, extra pool, relaxed eligibility or post-approval repair. Any follow-on is a new decision.

## 10. Implementation outline and decision requested

**New files.**

| file | contents |
| --- | --- |
| `rl/m7u3_goals.py` | non-overlap selection, its records, coverage (D8). NumPy only |
| `rl/m7u3_refit.py` | data manifest, stratified bootstrap, and a training loop identical to `m7u_model.train` except for the bootstrap. Loss, optimizer, batch generators and step count are reused unchanged. It is the only training path |
| `rl/m7u3_rule.py` | the rule, readings, wording check, self-test |
| `rl/m7u3_gate.py` | driver: phases, ledger, clock, tree-memory sampler, readiness, approval |
| `rl/m7u3_tests.py` | the offline tests below |

**Reused unchanged** (imports only, hash-pinned):
- `rl/m7u_{state,model,planner,analysis,worker,gate}.py`;
- from `rl/m7u2_{gate,goals}.py`: the loaders, the frozen-model pins, the tick-0 drive loop and the replay check.

No m7u1 or M7u2 file is edited.

**Offline tests:**
- **Rule:** self-test with thresholds equal to the §5 table; disjointness over every count triple; the intersection-union structure.
- **Goal selection:**
  - non-overlap by brute force;
  - order and permutation invariance;
  - the skip and pass-over records;
  - INCOMPLETE without fill;
  - a signature with no outcome, model or training-pool input.
- **Streams:** stream-key disjointness.
- **Refit:**
  - the stratified bootstrap equals m7u1's bootstrap when the pool is empty;
  - the data-manifest exclusions;
  - the optimizer confined to the refit phase, and the guard after training.
- **Evaluation:**
  - tick-0 entries only;
  - 4-arm dispatch, with S scored on g;
  - every success replayed.
- **Caps:** ledger, wall and tree-memory caps, including a cap one tick short stopping first.
- **Readiness:** each refusal case.
- **Approval refusal and acceptance:**
  - run on isolated temporary records (the m7u1 lesson);
  - with short temporary paths, because of Windows MAX_PATH.
- **The production-count e2e** on the synthetic stand-in. Its outcome is meaningless.

**Preparation also produces** (zero native ticks):
- the pipeline-identity retrain (§3.2);
- the frozen strict from-rest figures on the M7u2 pool, through the production diagnostic code. They must equal §1.2;
- a preflight;
- the approval template.

**Decision requested, in order.** None of these is authorised by this document.
1. The design, including the answers to §11.
2. The zero-native-tick preparation. It includes the pipeline-identity training run on recorded M7u1 data: about 6 min of CPU, no native tick.
3. Then, separately, gate `m7u3`:
   - ≤ 163,279 native updates;
   - a 60-minute global cap and the phase caps of §7;
   - memory caps of 3 GB for the main process and 9 GB for the whole tree.

## 11. Open questions

1. **Training-pool dose.** 360 × 192 (proposed), or 540 or 720 episodes (+144 s / +288 s)? A larger dose makes a NULL more informative.
2. **Secondaries.** Should they gate PASS (proposed: intersection-union), or only be reported?
3. **NULL threshold.** b_F − c_F ≤ 1 (proposed), or ≤ 2? With no effect, ≤ 1 gives NULL 68–100 % and INCONCLUSIVE up to 29 %.
4. **P_retrain arm.** Add one (M7u1 data only, training seed 1) to separate the data effect from retrain variance? It costs about +6 min of training and +4 min of evaluation, for a projection of about 43 min.
5. **S_frozen arm.** Add one, for about +4 min? It is not needed for the registered comparisons.
6. **N.** 24 (proposed) or 30? N = 30 needs G ≥ 720 and an extrapolated supply, and still carries a material INCOMPLETE risk.
7. **Replicate streams.** Two streams per goal per arm would raise per-goal resolution. They double evaluation (about +10–20 min), and the rule would move to per-goal success counts.
8. **Pipeline identity.** If the identity retrain is not bitwise reproducible: proceed on code identity plus the 32-decision check, or stop?
9. **P_frozen vs RC.** Register it as a secondary (the unit-level check of M7u2's direction), or keep it descriptive (proposed, D7)?
10. **Non-overlap margin.** Chebyshev > 300 (the M7u2 definition, proposed), or a stricter margin such as > 450? A stricter margin means less residual correlation but lower supply.

## Appendix A. Read-only analyses behind this proposal

Three scripts in the session scratchpad, outside the repository and not preserved as evidence. They:
- loaded the pinned M7u1 sources (pins checked) and the preserved M7u2 pool sidecars;
- re-ran M7u2's `select_goals` and reproduced its goal digest `1af171cc…`;
- simulated the §3.3 rule: 2,000 orders per pool size, and 600 subsets per value of m;
- computed the exact sign-test tables and the multinomial operating characteristics of §5;
- rolled the frozen model from the reset row of all 360 M7u2 pool episodes (§1.2), with the parameter digest unchanged.

**Nothing else ran or changed:**
- no native process and no training;
- no write under the repository: `git status` was identical before and after, and Python bytecode writing was disabled.
