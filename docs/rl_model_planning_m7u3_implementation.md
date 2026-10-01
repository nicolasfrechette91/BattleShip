# M7u3 preparation: implementation record (2026-10-01)

**Status: zero-native-tick preparation only, as authorised.**
- **Implemented:** the isolated driver, the refit pipeline, goal selection with a non-overlap rule, the rule and the pre-declared
  readings, the diagnostics, the offline tests, the accounting and the approval template.
- **Run offline (CPU, zero native ticks):** the identity retrain on recorded M7u1 data, the training of P_retrain, the
  strict from-reset figures on the preserved M7u2 pool (forward passes only), the production-count synthetic end-to-end and the
  preflight.
- **Not done:** nothing launched BattleShip, collected a pool, replayed an episode or consumed a native tick. No approval record, no
  source snapshot, no D: write. Nothing was committed or pushed, no branch was created.
- **Unchanged:** `docs/rl_model_planning_m7u3_proposal_2026-10-01.md` (sha256 `4590c0b4…`, byte-identical), every M7u1 and M7u2 file,
  doc, evidence file and record, M7u2's registered PASS and its scope, and the selected baseline (M7n v3 + reward v2, Track 1 PPO).

The user's decisions are recorded in `docs/rl_model_planning_m7u3_decisions_2026-10-01.md`; this record says how they and the
proposal were implemented and what was measured.

**Scope label**, carried by every M7u3 record: *refit-versus-frozen test of planner-controlled reach of rare behaviour-drawn
airborne points from the normal tick-0 reset (one seed, one refit, 24 non-overlapping goals); not a landing, wall-top reach,
crossing, target result or clear.*

## 0. Summary of the results

| item | result |
| --- | --- |
| **Identity retrain** (decision 6) | **bit-exact.** The refit pipeline on M7u1's 80 training episodes with an empty pool reproduces the frozen parameter digest `0e70af78…`; max \|Δparameter\| = 0.0, 0 of 685,092 elements differ |
| **P_retrain** (decision 4) | trained (seed 1, 6,000 steps, M7u1 data only); file sha256 `47d51b1b…`, parameter digest `13fa9cdb…` |
| **Offline tests** | **22 / 22 unit cases** and the **production-count synthetic end-to-end** pass (§5) |
| **Budgets** (decision 1) | 197,839 native ticks; pessimistic wall projection **3,516 s of the unchanged 3,600 s cap** (margin 84 s); projected 2,103 s (§4) |
| **Preflight** | passes every check except **(i) no approval record** (expected) and **(ii) machine readiness**: 2,138 MB available memory and 6,511 MB free commit against minimums of 4,096 / 10,240 MB. The memory shortfall is the machine's state (other applications), not a defect; see §6 |

## 1. State

| item | value |
| --- | --- |
| parent | `main` = `origin/main` = `1a68a7b`. New untracked files only (§2); no tracked file modified |
| submodules | `decomp e4f06348`, `libultraship 805f1950`, `torch 3aa9c97`; no native change (executable `30a3913b…`) |
| reused unchanged | `rl/m7u_{state,model,planner,goals,rule,analysis,worker,gate,tests}.py` (equal to HEAD), `rl/m7u2_{goals,rule,gate,tests}.py` (equal to the hashes in M7u2's approval) |
| compute | torch 2.14.0+cpu, 6 threads, 6 cores, Python 3.13.2, NumPy 2.5.3 |

## 2. Files (all new)

| file | role |
| --- | --- |
| `rl/m7u3_goals.py` | training-pool and goal-pool registration (`t000..t539`, `g000..g539`), the `m7u3_tick0_goal_v1` selection with the non-overlap rule, the brute-force independence report, per-goal coverage (D8). NumPy only; m7u2's eligibility, rarity and reach semantics are imported unchanged |
| `rl/m7u3_refit.py` | the refit pipeline: stratified episode bootstrap, `train_loop` (m7u1's `train` with the bootstrap injected), `refit`, the optimizer registry, the identity-retrain and P_retrain commands |
| `rl/m7u3_rule.py` | `m7u3_refit_rule_v1`, the proposal's readings, the pre-declared model reading, the M7u2 replication readout, self-test. No NumPy, no torch |
| `rl/m7u3_analysis.py` | diagnostics (forward passes only): strict from-reset open-loop error, witness acceptance, attribution, cross-attribution, calibration, and `accuracy`, a bounded-memory, batched re-implementation of `m7u_analysis.heldout_accuracy` (§5). A sixth file relative to the proposal's list, so the driver does not carry them |
| `rl/m7u3_gate.py` | driver: pins and identity, approval, preflight, readiness, whole-process-tree memory sampler, the drive loop, pools, refit phase, evaluation, diagnostics, replays, rule, `verify-run`, `attest-prep` |
| `rl/m7u3_tests.py` | 22 unit cases and the production-count `e2e` |
| `docs/rl_model_planning_m7u3_decisions_2026-10-01.md` | the decisions and the pre-declared interpretations |
| this record | |

Outputs of the preparation live under `logs/m7u3_prep/` (Git-ignored; the preflight requires `runs/m7u3` absent and walks every
`runs/` file against the D: backup, so nothing is written under `runs/`):

| file | content |
| --- | --- |
| `identity_retrain.json` | the identity retrain's full record |
| `p_retrain.pt`, `p_retrain.json` | P_retrain and its record. **A single copy** until a later session snapshots it to D: |
| `prep_attestation.json` | sha256 of `m7u3_refit.py` and of the three outputs above; written by `python rl/m7u3_gate.py attest-prep` after it checked that the identity retrain was bit-exact, that P_retrain was trained as specified and that `m7u3_refit.py` was last modified before either run started |

`rl/m7u3_refit.py` must not change after the attestation (sha256 `73bbda05…`); the preflight re-checks it.

## 3. The two preparation trainings (CPU, recorded M7u1 data only)

**Identity retrain** (`python rl/m7u3_refit.py identity`, 340 s: 14.6 s building, 318.1 s training; 6 threads, as m7u1's gate).
The refit pipeline (`refit(base, [], held, seed=0, steps=6000)`), from scratch, on M7u1's 80 training episodes in
`collection.json` order, with an empty pool:

| check | result |
| --- | --- |
| parameter digest | `0e70af78f1bec21039fa65f6f35ed180d69b31a02dd482480b946aced1bc0156` = the frozen model's |
| \|Δparameter\| | maximum **0.0**; 0 of 685,092 elements differ |
| rebuilt transitions | 240,964; dense features, status indices, every target and the episode index **array-equal** to M7u1's saved `model_inputs_train.npz` |
| vocabulary / clock track | 61 / 16 / 28, track `16318edf…`, both equal to the pins |
| training loss (step 6,000) | 0.770 train, 1.002 held-out, as in M7u1's record |
| optimizer registry | exactly one optimizer, over the model's own parameters |

Nothing was worked around and nothing needed to be: CPU training with the same torch build and thread count is bitwise
reproducible. The check is not repeated inside the gate.

**P_retrain** (`python rl/m7u3_refit.py retrain`, 328 s): the same pipeline, M7u1's training data only, training seed 1, 6,000
steps. File sha256 `47d51b1b17a9461413c250e56e6c8f3c0bb0b5edba0debc5658ea5b6998ed62b`, parameter digest
`13fa9cdbd143249a90c57b576b131c7ebd0edbbc0141f9cbbec19d4f58c916d7`, vocabulary 61 / 16 / 28 (the same data). Training loss at step
6,000 0.916, held-out 1.112 (the frozen model's: 0.770 / 1.002). It differs from the frozen model. It is an offline diagnostic
model: the gate loads it with both pins checked and uses forward passes only; no arm and no planner trial uses it (a test pins
this), and its digest is checked before the goal pool, before and after evaluation and after analysis.

**Strict from-reset figures on the preserved M7u2 pool** (360 episodes of 128 words, forward passes only, through the production
diagnostic `m7u3_analysis.strict_open_loop`; the unit case `unit_strict_from_reset_on_m7u2_pool` re-runs them):

| model | h = 16 | 32 | 64 | 96 |
| --- | ---: | ---: | ---: | ---: |
| frozen, median Chebyshev error | 152.6 | 333.4 | 713.9 | 907.6 |
| frozen, p90 | 679.9 | 988.9 | 1,632.1 | 2,038.4 |
| frozen, share above ±150 | 0.503 | 0.722 | 0.900 | 0.942 |
| P_retrain, median | 160.8 | 357.8 | 665.0 | 865.2 |
| P_retrain vs frozen, median paired difference | +6.6 | +43.4 | −54.7 | −42.8 |
| P_retrain vs frozen, share of episodes where P_retrain is better | 0.458 | 0.428 | 0.453 | 0.478 |

- **Reproduction:** the frozen figures equal the proposal's §1.2 (153 / 333 / 714 / 908; p90 680 / 989 / 1,632 / 2,038; share
  0.50 / 0.72 / 0.90 / 0.94). The gate repeats the cross-check and records a mismatch as an analysis defect.
- **Scale of retrain variation (for the pre-declared reading, §2.3 of the decisions record):** one retrain moves the 64-tick
  median by 6.9 % (a reduction) and the 16- and 32-tick medians the other way by 5 % and 7 %. The 20 % floor of the
  pre-declared model reading is therefore about three times the one observed retrain difference. The decisions record's
  thresholds were fixed **before** these retrain figures were read.

**Supply of non-overlapping goals on the M7u2 pool** (`unit_selection_on_m7u2_pool`): the m7u3 rule applied to the preserved M7u2
pool registers 24 goals from its 63 eligible episodes (823 eligible points), minimum pairwise Chebyshev distance 304.3, 259
passed-over overlapping taus, 31 episodes skipped. That is a sanity check of the supply, not a goal set: goals for the run come only
from its own goal pool.

## 4. Design as implemented, and the recomputed budgets

The proposal's design stands as amended by the decisions record. The points that matter for review:

- **Phases:** P1 → training pool → refit → goal pool → goal selection → evaluation → diagnostics → success replays → rule. The refit's
  file and parameter digests are written to `state.json` before the goal pool starts; the goal pool is collected after the refit
  is frozen, so it cannot reach fitting, tuning or model selection.
- **Optimizer:** one, inside `m7u3_refit.train_loop`, registered; the gate asserts exactly one over the refit's own parameters, then
  enters `no_optimizer()`, under which constructing any torch optimizer (including a second `train_loop`) raises an integrity stop.
  A source scan rejects `um.train(`, `.backward(`, `um.losses(`, `optim.Adam`, `optim.SGD`, `.step()` and `torch.optim` in the
  driver and in the analysis module. The readiness training probe builds optimizers on a throwaway synthetic model before the run.
- **Arms:** PF (frozen, commanded g), PR (refit, commanded g), RC (candidate 0, no model), SR (refit, commanded π(g), scored on g).
  Each model arm plans with its own model, batched per model. The four arms of goal k share the stream `m7u3|3|goal|k`. Stream
  keys of the training pool (`m7u3|1|train|t###`), the goal pool (`m7u3|2|pool|g###`) and evaluation are pairwise disjoint and
  disjoint from every m7u1 / M7u2 key (a test).
- **Goal selection:** from the goal pool and the m7u1 reference only; Chebyshev distance > 300 between every pair (brute force over
  276 pairs, the minimum recorded); an overlapping tau is passed over and recorded with the goal it overlapped; an episode with no
  free tau is skipped and recorded; fewer than 24 is INCOMPLETE with no fill. `select_goals` has no outcome, model or training-pool
  parameter (a test pins its signature, and `verify-run` re-checks it).
- **Tick contract:** every pool and evaluation entry starts at the non-consuming tick-0 reset; the reset row must equal the tick-0
  record before the first word (a mismatch is INVALID with zero ticks consumed); after every step `input_tick` and the record's `k`
  equal the number of words submitted; no hidden neutral step.

**Native-tick ledger** (refuses any request that would exceed a phase cap or the total, before it is sent):

| phase | cap | | phase | cap |
| --- | ---: | --- | --- | ---: |
| P1 (171 + 183 + 49 + 60) | 463 | | evaluation, 24 × 4 × 128 | 12,288 |
| training pool, 540 × 192 | 103,680 | | success replays, ≤ 96 × 128 | 12,288 |
| goal pool, 540 × 128 | 69,120 | | **total** | **197,839** |

**Wall time** (decisions record §3 has the full table): projected **2,103 s (35.1 min)**, pessimistic **3,516 s (58.6 min)** against
the unchanged 3,600 s global cap, per-phase caps p1 120 / training pool 750 / refit 900 / goal pool 750 / goals 120 /
evaluation 1,500 / replays + analysis 900 s. The pessimistic stack fits with an **84 s margin**.

**Memory.**
- **Caps:** main process 3,072 MB private; whole tree 9,216 MB private and 4,096 MB working set; system ≥ 1,024 MB available and
  ≥ 2,048 MB free commit. The sampler (`TreeSampler`, every 5 s) logs the whole process tree (main, workers, every BattleShip and
  standby) to `runs/m7u3/gate/_gate/memory_tree.jsonl` and any breach is INCOMPLETE. The tree walk was tested against a real
  child and grandchild process.
- **Main-process projection** (scratchpad measurement, no write under the repository): the refit's transition tensors for 344,644
  transitions (240,964 + 103,680) held **1.2 GB** private (process after imports 0.37 GB; after loading the m7u1 sources 0.48 GB;
  tiled real transition set 1.75 GB at its transient peak, 1.22 GB after freeing the source set; 1.32 GB after eight training
  steps).
- **A finding that changed the code.** The first two production-count end-to-end runs peaked at **2,184 MB and 2,616 MB**
  main-process private, in the diagnostics phase, not the refit: `m7u_analysis.heldout_accuracy` forwards a whole transition set
  through the ensemble at once (+0.9 GB transient on the 46,000-transition M7u2 pool, and about 41 s per call), and the gate calls it
  seven times (goal pool and m7u1 held-out for three models, and the M7u2 early-window reproduction). I replaced the call with
  `m7u3_analysis.accuracy` (chunked forward pass, one batched open-loop rollout; same definitions and the same sha-ordered start
  ticks), after checking that it equals `heldout_accuracy` and the recorded figures on recorded data (§5). The final end-to-end
  peaked at **1,716 MB**, and the replays-and-analysis phase fell from 180 s to 47 s.
- **Projected production peak about 1.6-2.1 GB against the 3,072 MB cap** (the end-to-end process also carries about 0.9 GB of test
  fixtures, and its refit set is 124,480 transitions against 344,644 in production, about 0.35 GB more): a margin of about
  30 %. The heaviest remaining phase is the refit itself.

## 5. Tests

`python rl/m7u3_tests.py unit`: **22 / 22 passed**. Approval is tested on isolated temporary records, so the suite stays
valid after a real approval exists.

| case | covers | result |
| --- | --- | --- |
| `unit_rule` | rule self-test, the proposal's §5 table of smallest passing results (boundaries), each of the three tests blocking PASS alone (RC → *not model-attributable*, SR → *undirected*), NULL threshold 1 (not 2), exact sign tests never exceed their level | pass |
| `unit_model_reading_and_replication` | the four pre-declared model labels, the exact 20 % floor (19 % no, 20 % yes, not float-sensitive), the replication readout's boundaries, the rule never consults a diagnostic | pass |
| `unit_goal_selection_rules` | brute-force reference of the rule, span boundary (300 overlaps, 300.5 does not), pass-over / skip records, permutation invariance, INCOMPLETE without fill, missing / duplicate entry, 129 words, reset row off the record, **signature has no outcome, model or training-pool input**, production constants, π a derangement, coverage | pass |
| `unit_selection_on_m7u2_pool` | m7u2's selection still reproduces its goal digest; the m7u3 rule yields 24 non-overlapping goals from the preserved pool | pass |
| `unit_streams` | stream-key disjointness (pairwise and against m7u1 / M7u2), seeds 1 / 2 / 3, determinism | pass |
| `unit_refit_pipeline` | stratified bootstrap equals m7u1's with an empty pool, strata sizes exact per member, `train_loop` equals `um.train` (identical parameters), optimizer registry, guard after training, source scans, vocabulary cap | pass |
| `unit_refit_manifest` | exactly m7u1's 80 + `t000..t539`; held-out, m7u1-training, M7u2-pool, non-registered and goal-pool episodes each refused | pass |
| `unit_prep_records` | attestation, bit-exact identity record, P_retrain pins; a tampered file, wrong digest pin, wrong file pin and missing pins refused | pass |
| `unit_frozen_and_records` | 32 / 32 recorded m7u1 and 32 / 32 recorded M7u2 tick-0 decisions reproduce (max \|Δ\| 3.5e-5 / 3.9e-5); a wrong M7u2 pin refused; the four P1 entries (463 ticks) | pass |
| `unit_strict_from_reset_on_m7u2_pool` | the strict figures of §3 equal the proposal's §1.2 | pass |
| `unit_accuracy_equals_m7u1_analysis` | `m7u3_analysis.accuracy` equals `m7u_analysis.heldout_accuracy` on recorded data (m7u1's 12 held-out episodes and the 360 M7u2 pool episodes: transitions, position error, status accuracy, per-class accuracy, open-loop medians and p90 within 0.05) **and reproduces the recorded figures exactly** (m7u1 held-out 121.35 / 289.52 / 644.63, M7u2 early window 106.15 / 298.45 / 559.36); 4.7 s → 1.8 s and 40.8 s → 3.8 s | pass |
| `unit_tree_memory_and_clock` | the real tree snapshot counts a child and a grandchild, every cap one at a time (at the cap is allowed), sampler log and breach, the clock stops the run on a tree breach, a live sampler thread | pass |
| `unit_readiness` | slow planning, low memory, low commit, unknown memory and a slow training step each refused; a ready machine accepted; the real timing and training probes run | pass |
| `unit_tick0_drive` | four arms from the tick-0 reset, **each planned with its own model**, RC never reaches a model, the four arms share one stream, SR commanded π(g), the evaluation tick cap one tick short stops first, a reset row off the record stops with 0 ticks, prefix / archived start / longer budget / other scored goal / unregistered arm refused before launch | pass |
| `unit_scrambled_scoring` | words through π(g)'s box end only at the budget when scored on g, and at the first reach when scored on π(g) | pass |
| `unit_pools_and_caps` | production pool configurations (540 × 108 per worker), ≤ 192 / ≤ 128 words, behaviour streams regenerated, entries other than plain registered episodes refused, pool caps one tick short, wall, memory and 60-minute caps | pass |
| `unit_replay_accounting` | every success of every arm, budget = trials × 128 (replays can never be cut), differing row / reach tick / digest / short replay rejected | pass |
| `unit_gate_stops` | P1 mismatch, refit-manifest violation, vocabulary overrun and an optimizer constructed after the refit are INVALID; too few goals (18 of 24) is INCOMPLETE with exactly the pools consumed; the training-pool and refit wall caps are INCOMPLETE | pass |
| `unit_diagnostics_wiring` | strict open loop deterministic and per-horizon episode sets, witness, paired tables, attribution, cross-attribution, no training call in the analysis module | pass |
| `unit_approval_refusal_and_acceptance` | missing, PENDING and each of 18 altered identity entries (tick budget, candidates, goals, frozen / retrain / refit entries, caps, rule, pools, span, seeds, arms, M7u2 sources, a code hash, the D: records) refused; unreadable raises; valid accepted; the repository path untouched | pass |
| `unit_accounting` | the ledger, the caps, readiness constants, and the wall projection inside every phase cap and the global cap | pass |
| `unit_import_isolation` | goal / rule modules import no torch or transport; m7u1 files equal HEAD; M7u2 files equal their approved hashes; no tracked file modified | pass |

`python rl/m7u3_tests.py e2e` (production counts, synthetic stand-in; see the table in the section "Production-count end-to-end").
It runs `run_gate` through **every phase at production counts**: P1, 540 training-pool episodes × ≤ 192 words, the **real refit
pipeline** on 80 synthetic base + 540 pool episodes (a reduced step count of 60: the step time is independent of the data size and
was measured at 318 s for 6,000 steps in the identity retrain), 540 goal-pool episodes × ≤ 128 words, 24 goals, 96 trials
(N = 17 candidates for speed; the real frozen ensemble and P_retrain plan and roll over a clock track rebuilt from synthetic
episodes), every success replayed, every diagnostic, the rule, and then `verify-run` on its own output (including detection of a
tampered goal digest and a tampered refit file). **The world is synthetic, so the outcome says nothing about Mario.**

**Production-count end-to-end, final code** (`python rl/m7u3_tests.py e2e`; run at below-normal priority on a loaded machine, 1,178 s;
two earlier runs on near-final code took 925 s and gave the same decision, ledger and goals):

| item | result |
| --- | --- |
| phases | P1 → training pool → refit → goal pool → goals → evaluation → diagnostics → replays → rule, all reached |
| decision (synthetic world) | PASS (PF 1, PR 7, RC 1, SR 0 of 24). Meaningless; it exercises the PASS path, the readings and the readouts |
| ledger | P1 171 · training pool **103,680** (540 × 192) · goal pool **69,120** (540 × 128) · evaluation 11,831 of 12,288 · replays 695 (9 exact) |
| refit | 80 + 540 episodes, 124,480 transitions (60 steps), **exactly one optimizer over the refit's own parameters**, its digests recorded before the goal pool |
| goals | 24 registered from 2,307 eligible points in 202 episodes; 10 overlapping taus passed over, 1 episode skipped; 276 pairs, **0 overlapping**, minimum pairwise Chebyshev 302.4; re-derived from the stored goal-pool sidecars with an identical digest |
| evidence | 96 trial files, every one from the tick-0 record with `t = 0`, `input_tick` = words and a model label (PF frozen, PR / SR refit) |
| diagnostics | D1, D2a, D2b, D3, D4, D5, D6, D8, D9 all present, **0 errors**; readings, model reading and replication readout in the decision |
| `verify-run` | passes on the output; a tampered goal digest and a tampered refit file are each detected |
| digests | the frozen model's and P_retrain's parameter digests unchanged throughout |
| memory | main-process peak 1,716 MB private (cap 3,072), 208 samples every 5 s, no breach. The machine-wide minimums were relaxed for this glue test (the machine was under memory pressure from other applications; its observed minimum was 424 MB available) and are tested in `unit_tree_memory_and_clock` |
| wall | training pool 117 s, refit 27 s (60 steps), goal pool 125 s, evaluation 752 s (N = 17 candidates), replays and analysis 47 s |

## 6. Preflight (zero native ticks, before any approval record exists)

`python rl/m7u3_gate.py preflight` on the **final code** (2026-10-01 16:39Z) launched nothing and consumed zero native ticks, before any
approval record existed. Everything passed except two things:

| check | result |
| --- | --- |
| unit suite and rule self-test | **22 / 22**, rule `e56d9fed…` |
| frozen model, records and decisions | pins ok; 32 / 32 recorded m7u1 and 32 / 32 recorded M7u2 tick-0 decisions reproduce (max \|Δ\| 3.5e-5 / 3.9e-5) |
| P_retrain | pins ok (`13fa9cdb…`) |
| preparation attestation | attested (identity retrain bit-exact; refit code, records and P_retrain file unchanged since) |
| code identity | the nine m7u1 files equal HEAD; every M7u2 file equals the hash in M7u2's approval |
| stream keys | pairwise disjoint and disjoint from every m7u1 / M7u2 key |
| D: coverage | all 398,054 `runs/` files covered over the base and 4 increments, 0 uncovered; the 7 D: record folders digest `d825cda1…` |
| processes, executable, `runs/m7u3` | no BattleShip process; executable `30a3913b…`; `runs/m7u3` absent |
| readiness: planning probe | median 0.355 s, p95 **0.363 s** (limit 0.5 s): pass |
| readiness: training-step probe (throwaway synthetic model) | median **0.041 s** (limit 0.10 s): pass |
| **approval record** | **refused: none exists** (expected) |
| **readiness: memory** | **refused: 2,138 MB available (minimum 4,096) and 6,511 MB free commit (minimum 10,240)** |

**The preflight therefore does not refuse for the missing approval alone.** The second refusal is the machine's state, not a code
or evidence problem: at that moment the machine's memory was occupied by other applications (an IDE, a browser, a video editor
and the desktop client; the earlier preflight run saw 2,883 MB, M7u2's saw 6,134 MB and M7u1's 6,280 MB). I closed no application and did
not touch the thresholds. The readiness check is a launch precondition, evaluated again at the start of the run; with the memory
freed it uses the same code path as the passing timing and training probes above. The same shortage also made the machine-wide
caps (1,024 MB available) trip once in a test run, which is why the end-to-end test records those minimums instead of enforcing
them (they are tested separately).

## 7. Remaining risks

- **Wall-time margin is thin:** the pessimistic projection leaves 84 s of the 3,600 s cap (decisions record §3). It is a stack of
  pessimistic assumptions at once, but a run slower than it ends INCOMPLETE; evaluation results would be saved and the rule not
  applied. Nothing was trimmed to widen it (decision 1).
- **Main-process memory margin is moderate:** projected peak 2.2–2.5 GB against 3,072 MB; the heaviest transient is the
  diagnostics (`m7u_analysis.heldout_accuracy` forwards a whole pool at once and is reused unchanged).
- **Machine readiness:** the preflight's available-memory minimum (4,096 MB) was not met when it ran (§6). The tree cap of
  1,024 MB available protects the machine and was sized from a start of about 6 GB; a start near 3 GB would breach it.
- **Native paths not yet exercised by M7u3** (as for M7u2): the 192-step horizon, t = 0 entries from a standby promotion in the
  m7u3 drive loop, 108 restarts per worker per pool, and the four-arm dispatch. P1 replays pinned artifacts through the same
  stack but covers none of them; the first native contact is the gate itself and any mismatch is INVALID.
- **Single copy of P_retrain** under `logs/m7u3_prep/`; a loss is recoverable by rerunning `rl/m7u3_refit.py retrain` (the CPU run is
  bit-reproducible, as the identity retrain shows) but the pin would then need the same digest.
- **Design limits carried from the proposal (§1.3, §9):** tick-0-specific data versus more data of any kind cannot be separated;
  a PASS shows nothing about replication, landing, wall-top reach, crossing, targets or a clear. Detectable effect: a net gain of at
  least +5 goals, about +7 to +10 for 80 % power.
- **Replication readout is partial** (decisions record §2.2): M7u2's third condition needs S_frozen, which decision 5 removed.

## 8. Approval template and what remains for the run session

`python rl/m7u3_gate.py approval-template` prints the record a reviewer would write; it never writes it. **No approval record, no
source snapshot and no D: write exist.** The template pins every identity, budget, cap and seed above; its entries that a
later change would invalidate are:

| entry | value |
| --- | --- |
| rule / goal contract | `m7u3_refit_rule_v1` `e56d9fed…` / `m7u3_tick0_goal_v1` `b068dfdc…` |
| planner / state / world / executable | `e1f9bc8f…` / `7c291133…` / `ca1ac287…` / `30a3913b…` (all unchanged from m7u1 / M7u2) |
| frozen model | file `a4bd30e5…`, parameters `0e70af78…`, vocabulary 61 / 16 / 28, 3 members, track `16318edf…` |
| P_retrain | file `47d51b1b…`, parameters `13fa9cdb…`, seed 1, 6,000 steps, offline diagnostic only |
| refit | seed 0, 6,000 steps, batch 1,024, lr 3e-4, 3 members, from scratch, stratified bootstrap; refit code `73bbda05…` |
| pools / goals / budget | training pool 540 × 192, goal pool 540 × 128, 24 goals, span 300, budget 128; 197,839 ticks; caps as in the decisions record |
| D: records | the 7 folders' top-level records, digest `d825cda1…` |
| m7u3 code | `m7u3_goals` `2f92c5e7…`, `m7u3_refit` `73bbda05…`, `m7u3_rule` `d09e2330…`, `m7u3_analysis` `0e017eac…`, `m7u3_gate` `4aca3e60…`, `m7u3_tests` `26a44633…` |

**What the run session would still have to do** (none of it is requested or started here): write the approval record from a freshly
printed template; copy and verify the source snapshot to `D:\BattleShip_source_snapshots\<date>_m7u3`; confirm the machine
meets the readiness minimums; run `python rl/m7u3_gate.py run` once; verify with `python rl/m7u3_gate.py verify-run` and an
independent check; make the verified D: increment for `runs/m7u3`; and copy `logs/m7u3_prep/` (P_retrain and the preparation records,
currently a single copy) to D:.
