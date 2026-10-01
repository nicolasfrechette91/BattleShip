# M7u3 gate `m7u3`: results (run 2026-10-01 20:37Z-21:11Z)

**Registered decision: NULL (rule `m7u3_refit_rule_v1`, unchanged), one seed, one refit, scope-limited.** The refit model
(P_refit) reached **5 of 24** goals; the frozen M7u1 model (P_frozen) reached **7**; the no-model control (RC) **1**; the
scrambled-command refit (S_refit) **0**. P_refit's net paired gain over P_frozen is **-2** (NULL requires <= +1).

**Scope, in the only words this result supports:** refit-versus-frozen test of planner-controlled reach of rare
behaviour-drawn airborne points from the normal tick-0 reset (one seed, one refit, 24 non-overlapping goals). It is **not** a
landing, wall-top reach, crossing, target result or clear. No trial cleared the stage. The selected baseline remains
**M7n v3 with reward v2**; nothing here changes it. M7u1's and M7u2's registered results are unchanged.

## 1. What was authorised and what was done

- **Amendment 1** (before any native tick; `docs/rl_model_planning_m7u3_amendment_2026-10-01.md`): global hard wall cap
  3,600 s -> **4,500 s**, and the replication-readout label (output wording only). Nothing else changed (thresholds, tick
  budget 197,839, phase caps, memory caps, eligibility, arms, rule digest `e56d9fed…`). The pre-amendment files are kept in the
  D: snapshot (`prepared_reference/`).
- **Verified unchanged before the amendment:** HEAD = origin/main = `1a68a7b`, no tracked change, proposal `4590c0b4…` and
  decisions record `aa5773a7…` unchanged, nine m7u1 files equal HEAD, four M7u2 files equal the hashes in M7u2's approval,
  `m7u3_refit.py` `73bbda05…` equal to its attestation, P_retrain digest `13fa9cdb…`, `runs/m7u3` absent.
- **Re-verification on the amended code:** rule self-test clean; unit suite 22 / 22 (twice: after the cap edit and on the final
  code); full preflight refused for **exactly one reason, the missing approval** (readiness passed: 8.1 GB available, planning
  p95 0.367 s), then passed with the approval record present (unit 22 / 22, 6.9 GB available, p95 0.368 s).
- **Evidence preserved before the run:** `logs/m7u3_prep/` -> `D:\BattleShip_runs_backup\2026-10-01_m7u3_prep` (section 9);
  source snapshot `D:\BattleShip_source_snapshots\2026-10-01_m7u3` (section 9).
- **Approval** `docs/rl_model_planning_m7u3_gate_approval.json`, written from a freshly printed template (only fields added:
  authorisation, amendment, snapshot, coverage, preflight).
- **Launched once**, detached, 2026-10-01T20:32:53Z (`python rl/m7u3_gate.py run`). No retry, extension, extra pool, relaxed
  eligibility, threshold change or post-approval repair occurred. The code was not modified after the snapshot (re-verified
  after the run: 66 / 66 files, 0 mismatches). I did not close any application.

## 2. Per-arm goal counts, paired wins / losses and exact sign probabilities

| arm | goals reached of 24 | goals (registered index k) |
| --- | ---: | --- |
| **P_frozen** (PF) | **7** | 7, 8, 11, 14, 18, 19, 21 |
| **P_refit** (PR) | **5** | 0, 3, 5, 8, 23 |
| RC (candidate 0, no model) | **1** | 4 |
| S_refit (SR, commanded pi(g)) | **0** | none |

b = first only, c = second only (one unit = one goal; the 24 goals are independent by construction). p = exact one-sided
sign probability that the first arm is better, `P(X >= b)`, `X ~ Binomial(b + c, 1/2)`; "n" is neither.

| comparison | b | c | both | neither | b - c | exact p | registered role |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| **P_refit vs P_frozen** | 4 | 6 | 1 | 13 | **-2** | **0.828** (not significant) | primary; NULL if b - c <= 1 |
| P_refit vs RC | 5 | 1 | 0 | 18 | +4 | 0.109 (not significant) | attribution to the model |
| P_refit vs S_refit | 5 | 0 | 0 | 19 | +5 | 0.031 (significant) | direction |
| *(reported, not registered)* P_frozen vs P_refit | 6 | 4 | 1 | 13 | +2 | 0.377 | the reverse test: no significant advantage either way |
| *(reported, not registered)* P_frozen vs RC | 7 | 1 | 0 | 16 | +6 | 0.035 | the replication readout (section 5) |

**Reading by the rule:** PASS needs P_refit to beat P_frozen, RC and S_refit each at p <= 0.05; it beat only S_refit. NULL
holds because b - c = -2 <= 1; the PASS and NULL conditions are disjoint, no blocker is recorded. The proposal's §6
readings of this outcome, as recorded in the run: *"no model gain from rest: at this dose the added data did not materially
reduce from-rest rollout error; the limit lies in the model or its training form, not in how densely the data cover the
reset neighbourhood"* and *"regression: the refit reached fewer goals than the frozen model"*. The sample cannot separate
a real regression from noise (p = 0.377 for the reverse comparison); it shows no benefit.

Reach ticks (all inside the 128-word budget): PF 114, 72, 81, 75, 103, 108, 63 (goals 7, 8, 11, 14, 18, 19, 21); PR 49, 81, 58,
95, 53 (goals 0, 3, 5, 8, 23); RC 105 (goal 4). Only goal 8 was reached by both P arms. **No trial of any arm fell (0 of 96); none
cleared; 0 targets were checked by this gate.**

## 3. Goal supply from the 540-episode goal pool, with an independent re-derivation

- **Pool:** exactly `g000..g539`, 540 episodes x 128 words (69,120 ticks, 0 falls), collected after the refit was frozen.
- **Eligibility** (the m7u2 definitions, unchanged): 328 of 540 episodes had a candidate point; **1,026 eligible points in 84
  episodes (15.6 % yield**; M7u2's pool: 17.5 %). Selection took episodes in sha order and used the first **47** of the 84 to
  register 24 goals: **236 overlapping taus were passed over** and **23 episodes skipped** (every eligible tau within 300 of a
  registered goal). Non-overlap is therefore binding, which is why a larger pool than M7u2's was needed.
- **Independence:** 276 pairs checked by brute force, **0 overlapping**, minimum pairwise Chebyshev distance **302.5**
  (> 300), 24 independent units, one goal per source episode. Goal digest `062075a0…`.
- **Re-derivation 1 (the gate's `verify-run`):** the goals re-derive from the stored goal-pool sidecars with an identical
  digest; `select_goals` has no outcome, model or training-pool argument. ok.
- **Re-derivation 2 (independent, `tools/indep_goals.py` in the launch folder):** my own episode / tau sha ordering, greedy
  overlap test and counts, on the same sidecars: **the same 24 (entry, tau) pairs and coordinates**, and identical counts
  (328 / 1,026 / 84 / 236 / 23). (It shares only the m7u2 eligibility primitives `candidates` and the reference with the
  gate.)
- **Goal properties against the added data:** the training pool passed through the goals' boxes in a median of 8.5 episodes
  per goal against 1.0 for M7u1's own training episodes (D8): the added pool did cover the goal neighbourhoods.
  By coverage of the training pool, goals / PF / PR / RC reached: 1-5 passes: 8 goals, 2 / 0 / 0; 6-15 passes: 11 goals,
  2 / 3 / 1; >= 16 passes: 5 goals, 3 / 2 / 0. P_refit did not gain on the covered goals.

## 4. Registered model diagnostic

### 4.1 Strict from-reset open-loop error (the goal pool, 540 episodes, nothing fitted on them)

The episode's own recorded words from its reset row; Chebyshev error of the ensemble-mean position. Median (p90) in game
units:

| horizon | P_frozen | P_refit | P_retrain |
| ---: | ---: | ---: | ---: |
| 16 | 132.0 (722) | 161.4 (695) | 152.5 (763) |
| 32 | 292.4 (1,107) | 400.7 (1,134) | 338.4 (1,180) |
| 64 | 669.4 (1,887) | 819.3 (1,973) | 613.9 (1,570) |
| 96 | 949.7 (2,294) | 1,063.8 (2,376) | 852.5 (1,943) |

Share of episodes above the +-150 box: frozen 0.485 / 0.683 / 0.882 / 0.957; refit 0.539 / 0.854 / 0.980 / 0.991; retrain
0.506 / 0.746 / 0.911 / 0.970.

**Paired differences** (median over episodes of error(model) - error(frozen); negative = the model is better; share of
episodes where the model is better):

| horizon | refit - frozen | refit better | retrain - frozen | retrain better |
| ---: | ---: | ---: | ---: | ---: |
| 16 | +29.1 | 0.389 | +13.2 | 0.413 |
| 32 | +81.9 | 0.343 | +31.0 | 0.437 |
| 64 | **+167.6** | **0.356** | +5.0 | 0.491 |
| 96 | +226.4 | 0.348 | **-25.7** | 0.517 |

### 4.2 Pre-declared interpretation (decisions record §2.3, fixed before any native data): `MODEL_REGRESSION`

At h = 64 the refit's median error is **22.4 % higher** than the frozen model's (reduction -0.224) against a 20 % regression
threshold; the retrain's reduction is **+0.083** (it is slightly better than the frozen model at 64 and 96 and worse at 16
and 32: -0.156, -0.157). FLOOR (a >= 20 % reduction) is not met; the refit is worse than the frozen model at **all four
horizons**, and in the adverse direction by more than the one observed retrain difference at every horizon. The refit
beats the retrain's reduction at 0 of 4 horizons. One retrain is one draw of retrain variation, not an interval, so the label
means "worse by more than the one observed retrain difference".

Cross-check on the preserved M7u2 pool (360 episodes; forward passes only; not fitted on): frozen **153 / 333 / 714 / 908**
(reproduces the proposal's §1.2 exactly), refit 181 / 409 / 808 / 1,132, retrain 161 / 358 / 665 / 865. The label there is
`NO_MODEL_GAIN` (the refit is 13 % worse at 64, below the 20 % regression threshold), with the same ordering: the refit is the
worst of the three at all four horizons, and the retrain is the best at 64 and 96.

Other model figures (D5, goal pool, early window, one step): position error median 2.09 (frozen) vs 2.19 (refit); status
accuracy 0.955 vs 0.964. So the refit predicts the next state and status about as well, or marginally better on status, and
is worse over the long open loop from reset. The refit trained to a held-out total loss of 0.978 (train 0.776) in 6,000 steps
on 344,644 transitions (80 M7u1 + 540 pool episodes), with exactly one optimizer over its own 23 parameter tensors; its
vocabulary has 63 status classes (frozen 61), inside the cap.

### 4.3 Path acceptance (witness test from the reset row)

The ensemble accepts the pool episode's own recorded path to the goal from the reset state for **0 of 24 goals for every model**
(W_frozen = 0, W_refit = 0, W_retrain = 0; paired frozen-vs-refit: 0 / 0 / 0 / 24 neither). M7u2's frozen figure was 1 of 24.
The decision's dW = 0, so the proposal's "model gain, no reach gain" reading cannot apply.

### 4.4 Model / planning failure attribution (the M7u2 definitions; reported, not part of the rule)

| arm | failures | MODEL | PLAN | MODEL share | without an ambiguity flag: failures, MODEL, share | successes (all PREDICTED) |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| P_frozen | 17 | 7 | 10 | 0.41 | 7, 4, 0.57 | 7 |
| P_refit | 19 | 8 | 11 | 0.42 | 13, 6, 0.46 | 5 |

Both arms fail more often because no decision ever predicted a reaching plan (PLAN, 10 and 11) than because the model
over-predicted one (MODEL, 7 and 8). The M7u2 figure for the frozen model was 12 MODEL / 5 PLAN of 17; here it is 7 / 10, so the
attribution is not stable across goal sets.
Cross-attribution (the same executed words from the same decision states through the other model): 6 of P_frozen's 7 MODEL
failures (0.86 of trials, 1.00 of predicted decisions) are no longer predicted as reaching by the refit; 4 of P_refit's 8 (0.50
of trials, 0.76 of decisions) are no longer predicted by the frozen model. The models disagree on which plans reach, which
is consistent with the diagnostics above: two different but similarly inaccurate rollout predictors.
Calibration of executed plan blocks (median error in units / blocks over the +-150 box / AUROC of the spread against
error): PF 23.0 / 23 of 695 / 0.75; PR 23.9 / 26 of 690 / 0.75; SR 23.7 / 37 of 768 / 0.74.

## 5. Replication readout of M7u2: **partial replication (S condition not evaluable)**

P_frozen versus RC on these 24 independent goals, applying only the two **evaluable** M7u2 PASS conditions. The third M7u2
condition (`b_S - c_S >= 5` against a scrambled-command control of the *frozen* model) is **not evaluable** because decision 5
removed S_frozen. This readout never alters the M7u3 decision.

| quantity | value | M7u2 threshold | met |
| --- | ---: | ---: | :-: |
| n_P_frozen | 7 | >= 6 | yes |
| P_frozen only (b) / RC only (c) | 7 / 1 | | |
| b - c | **6** | >= 6 | yes (exactly at the threshold) |
| exact one-sided p | 0.035 | | |
| S condition | not evaluable | b_S - c_S >= 5 | n/a |

Recorded label `MEETS_EVALUABLE_M7U2_PASS_CONDITIONS`, reading label **"partial replication (S condition not evaluable)"**:
the frozen model again reached 7 of 24 goals, and in independent units (the M7u2 result counted 4 of 13 independent units).
The margin is the thinnest the rule allows: RC reached one goal (goal 4) where M7u2's RC reached none, and one more RC success
would have failed the b - c condition. It is a replication of two of M7u2's three conditions, on one seed.

## 6. Integrity

- **Frozen model:** parameter digest `0e70af78…` equal to the pin at the start, before and after evaluation and after analysis;
  model file `a4bd30e5…` verified. **P_retrain:** digest `13fa9cdb…` and file `47d51b1b…` unchanged (re-hashed after the run).
  Neither was trained further (no optimizer was constructed after the refit).
- **P_refit:** exactly one optimizer, over the refit's own parameters; digest `74c8861e…`, file `3888d747…`. Both pins were
  written to `state.json` and the file saved at 20:49:51Z; the goal pool was collected after (goal pool file 20:56:30Z). It
  differs from the frozen model and from P_retrain; `verify-run` re-hashes the file against its record.
- **Tick 0:** all 96 trial files (checked by `verify-run` and again by an independent script) start at the non-consuming tick-0
  record (`t = 0`, empty prefix, first row equal to the record in every field), `input_tick` equal to the number of words at every
  row, at most 128 words, the registered stream key; no archived start, prefix or hidden neutral step in any entry. The training
  and goal pools likewise start from reset (reset row equal to the record before the first word; the pool checks passed).
  Arm-to-model labels in the files: PF frozen, PR refit, SR refit, RC none.
- **Identity replays (P1):** 4 of 4 exact (m7u1 `g26_P` 171, `g14_P` 183; M7u2 `g14_P` 49, `g03_P` 60 words; words, every stored
  row field, reach tick, action digest).
- **Success replays:** **13 of 13 exact from tick 0** (PF 7, PR 5, RC 1; S_refit had no success): same words, rows and reach tick
  (1,057 replay ticks, inside the 12,288-tick allowance).
- **Integrity problems recorded: none.** Contracts as in the guide: reset consumed no update; action tick T executed one native
  update; consumed_tick = T and input_tick = T + 1; no native RNG was inspected, logged, compared, controlled or hashed; no human
  recording or TAS entered the run; Track 1 `btt_s9_b8_v1` (all 72 combinations) unchanged; no native, decomp or submodule
  change (executable `30a3913b…`).

## 7. Resources

| phase | native ticks used (cap) | wall (cap) |
| --- | ---: | ---: |
| P1 identity | 463 (463) | 18.7 s (120) |
| training pool, 540 x 192 | 103,680 (103,680) | 431.1 s (750) |
| refit, 6,000 steps | 0 | 267.3 s (900) |
| goal pool, 540 x 128 | 69,120 (69,120) | 398.1 s (750) |
| goal selection | 0 | 0.5 s (120) |
| evaluation, 96 trials | 11,681 (12,288) | 766.2 s (1,500) |
| replays + analysis | 1,057 (12,288) | 120.9 s (900) |
| **total** | **186,001 (197,839)** | **2,002.9 s = 33.4 min (4,500)** |

Launch to finished state: 20:32:53Z-21:11:17Z, 38.4 min, including the driver's own internal preflight (about 5 min, with the unit
suite). The pessimistic projection (3,516 s) was not approached; the run took 2,003 s against the projected 2,103 s. The cap
amendment was not needed in the event.

**Memory** (whole-tree sampler, every 5 s, 398 samples, no breach): main process private peak **1,622 MB** (cap 3,072); whole tree
private peak **7,020 MB** (cap 9,216); whole tree working set peak **3,218 MB** (cap 4,096); 26 processes at the peak; system
available memory minimum **3,834 MB** (floor 1,024) and free commit minimum **8,687 MB** (floor 2,048). The run clock's own
main-process peak was 1,597 MB.

## 8. What this does and does not establish

**Establishes (one seed, one refit, the registered rule):** adding 540 tick-0 behaviour episodes (103,680 ticks, the goal
neighbourhoods covered about eight times as often as in M7u1's data) to the M7u1 training set and refitting the same
architecture from scratch did **not** improve planner-controlled reach of rare airborne points from the normal reset (5 of 24
vs 7 of 24, net -2, p = 0.83) and did **not** improve, but worsened, the strict from-reset open-loop error (22 % worse at 64
ticks, worse at all four horizons, beyond the one observed retrain difference). The frozen model's 7 of 24 reproduced on a fresh,
independent goal set (a partial replication).

**Does not establish:** that more tick-0 data cannot help (one dose, one seed, one refit; tick-0-specific data versus more data
of any kind or a changed training trajectory is not separable), a real regression versus noise (reverse p = 0.38), anything
about a landing, wall-top reach, crossing, targets, a clear, goals beyond 128 ticks or sequences of goals, or any advantage over
PPO. It does not change the selected baseline. The proposal's design limit stands: a net gain of at least +5 goals was
detectable; effects below that were not.

## 9. Evidence and backups

- **`runs/m7u3/gate/`** (Git-ignored, 11,022 files, 384.5 MB): `_gate/state.json` (the decision, ledger, clock, memory, every
  diagnostic), `goals.json`, `train_pool.json`, `goal_pool.json`, `refit.json`, `model_refit.pt`, `model_inputs_trials_{frozen,refit}.npz`,
  `memory_tree.jsonl`, `trials/*.npz` (96: native rows, canonical words from tick 0, per-decision candidates), worker artifacts
  and sidecars for P1, both pools, evaluation and replays, and `_gate/launch/` (stdout / stderr, both preflight outputs, the
  template, an approval copy, a snapshot copy, the final unit log, and the snapshot / verification / independent-check tools).
  The copy of this report under `_gate/report/` is the version made before the backup section below was filled in.
- **Preparation outputs:** `D:\BattleShip_runs_backup\2026-10-01_m7u3_prep` (8 files, 2,759,295 bytes): tool `backup` + `verify`
  PASS (0 mismatches, manifest `f567f73c…`), and an independent PowerShell re-hash of all 8 files (source vs D: copy), 0
  mismatches, plus a separate Python manifest cross-check, `increment_check.json`.
- **Source snapshot:** `D:\BattleShip_source_snapshots\2026-10-01_m7u3`, 66 files + 3 prepared_reference files; tool `snapshot` PASS,
  tool `verify` PASS (before the launch and again after the run), independent PowerShell re-hash 69 checked / 0 bad, executable
  `30a3913b…` equal; `snapshot.json` `97c085f7…`.
- **`runs/m7u3` increment** `D:\BattleShip_runs_backup\2026-10-01_incr_m7u3`: `rl/tools/runs_backup.py backup --source runs/m7u3`:
  11,023 files, 384,563,216 bytes (this includes the pre-backup copy of this report); `verify` PASS (0 hash mismatches, inventories
  equal); manifest `b6a32722…`. An independent PowerShell re-hash of every regular file (source vs D: copy), `increment_check.json`:
  11,023 / 11,023, 0 mismatches, PASS. 1,222 reparse points were skipped by design; all are per-worker `.tcc` links to the build
  tree (checked), not evidence.
- **Coverage afterwards:** **409,077 `runs/` files, 0 uncovered**, over the base and 5 verified increments (m7r, m7s, m7u, m7u2, m7u3).
  Earlier D: records and increments were not touched. The approval record still matches the code identity; its pinned D: records
  digest (`d3f176ba…`, which included the prep folder) is now superseded by the added increment folder, as expected.

## 10. Working tree

No tracked file was modified. New untracked files: `rl/m7u3_{goals,refit,rule,analysis,gate,tests}.py`, the m7u3 proposal,
decisions record, implementation record, amendment record, approval record and this report (plus the M7u2 untracked files that
were already present). Nothing was committed or pushed; no branch was created; no video was made; no follow-on run is authorised.
