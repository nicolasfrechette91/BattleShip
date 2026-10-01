# M7u2 proposal: frozen-model control from the normal tick-0 reset (2026-09-30)

**Status: proposal for review.** This turn authorised read-only analysis and this document only. Nothing was
implemented, launched, replayed, trained, committed or pushed.

The analysis used only preserved `runs/m7u` records and forward passes of the frozen model, and its scripts live
outside the repository. The m7u1 decision (PASS; local control after self-generated supplied prefixes, one seed)
stands unchanged.

## 0. Verified state (read-only)

| item | state |
| --- | --- |
| parent | `main` = `origin/main` = remote `main` at `1a68a7b` (the M7u commit). Working tree clean |
| submodules | `decomp e4f06348`, `libultraship 805f1950`, `torch 3aa9c97`, as pinned |
| D: evidence | coverage of all 393,911 `runs/` files: 0 uncovered (base + `_incr_m7r` + `_incr_m7s` + `_incr_m7u`). The 30 earlier records and manifests are byte-identical. `_incr_m7u` is PASS (2,286 files, manifest `f14c1b97` intact; independent re-hash PASS). Both source snapshots are intact (`f45de49d`, `91752bb5`) |
| frozen model | `runs/m7u/gate/_gate/model.pt`, sha256 `a4bd30e5…`, parameter digest `0e70af78…`, vocabulary 61 / 16 / 28. The clock track rebuilt from the 80 training sidecars equals the recorded `16318edf…` |

## 1. The 40 m7u1 trials by controller-start state

**Method.**
- The start state is the recorded row at tick t. It is identical for P, RC and S: natively 120 / 120, and re-checked
  offline.
- Movement means status entries after t. The first controller word is consumed tick t, so it first shows at input
  tick t + 1.
- A **double jump is counted only from an entry into JumpAerialF/B**, never from `jumps_used`, which is a capacity
  counter. The three airborne starts at 2 / 2 each contain a JumpAerial entry earlier in the same airtime (at −7, −62
  and −89 ticks).

| start group | goals | P | RC | S | P vs RC (b / c) | P vs S (b / c) |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| **all** | 40 | 22 | 1 | 8 | 21 / 0 | 16 / 2 |
| grounded | 27 | 12 | 0 | 5 | 12 / 0 | 8 / 1 |
| grounded, free (arms' states diverge within 4 ticks) | 9 | **2** | 0 | 1 | 2 / 0 | 2 / 1 |
| grounded, locked in an action for 5-24 ticks | 14 | 8 | 0 | 4 | 8 / 0 | 4 / 0 |
| grounded, locked ≥ 25 ticks | 4 | 2 | 0 | 0 | 2 / 0 | 2 / 0 |
| airborne, rising | 7 | 6 | 0 | 1 | 6 / 0 | 5 / 0 |
| airborne, falling | 6 | 4 | 1 | 2 | 3 / 0 | 3 / 1 |
| airborne, double jump still available | 10 | **9** | 1 | 2 | 8 / 0 | 8 / 1 |
| airborne, no jump left | 3 | 1 | 0 | 1 | 1 / 0 | 0 / 0 |
| rise needed < 500 / 500-999 / ≥ 1,000 | 14 / 13 / 13 | 10 / 8 / 4 | 1 / 0 / 0 | 4 / 4 / 0 | | |

**Movement underway at t** (status class; P reached / goals):
- aerial attack 5 / 8;
- tornado 4 / 8 (6 of them on the ground);
- landing lag 2 / 7;
- fireball 4 / 4;
- ground attack 3 / 4;
- idle or taunt 2 / 4;
- light landing 1 / 2;
- dash 0 / 1, shield 0 / 1, roll 1 / 1.

P leads RC in every row of the table, and leads S in every row but one: airborne with no jump left, tied 1-1 on 3
goals.

**Initiated vs inherited.**
- **Every P success initiated its own rise after t (22 / 22).** No reach rode only on a movement already underway.
  - Ground jump: 16.
  - Double jump (a JumpAerial entry): 12.
  - Up-B: 2.
  - Air tornado: 1.
  - Combinations: ground jump only 7, double jump only 6, ground jump + double jump 6, ground jump + up-B 2, ground
    jump + air tornado 1.
- **Timing.** The first initiated rise came at median +26 ticks (range +1 to +89); the reach at median +54. Only 2
  initiations came within 3 ticks of t, where prefix tap counters could still contribute.
- **Own compositions.** Only 7 of the 22 used the same rise composition as the goal's recorded witness. P found its
  own compositions; it did not copy a route.
- **What was inherited:**
  - **Airborne starts:** the prefix had already jumped. 10 successes started airborne. 6 stayed airborne and added a
    double jump; 4 landed and jumped again. This is the easiest group: P 9 / 10 when the double jump was still
    available.
  - **Grounded starts:** at the 12 grounded successes all rise was initiated. The prefix supplied only position and a
    lockout. Starts locked in an action for 5 ticks or more did better (10 / 18) than free ones (2 / 9).
- **All 18 P failures also initiated rises.** The planner acted but mistimed or misdirected.

**Implication.** Tick 0 is a grounded, free, idle start. That is the group where the m7u1 evidence is thinnest: 2 / 9,
small n, and 7 of those 9 goals needed 694-1,650 units of horizontal travel. So a tick-0 test is a genuinely new test,
not a repeat of m7u1.

## 2. What tick 0 offers, and the missing prerequisite

**Tick 0.**
- All 92 m7u1 behaviour episodes share one tick-0 row, in every field: Mario in Wait at (0, −2550), velocity 0, jumps
  0 / 2.
- There is no entry animation: the episodes diverge from input tick 1.
- A single ground jump from reset rises at most 1,360 units (median 660).

**The m7u1 held-out episodes cannot supply the goals.** Rare goals here means airborne, ≥ 300 above the spawn, and
reached by at most 1 of the 80 training episodes within the budget.

| goal ticks and budget | rare points | from held-out episodes |
| --- | ---: | ---: |
| τ ∈ [16, 64], budget 96 | 24 | 2 of 12 |
| τ ∈ [32, 96], budget 128 | 26 | 3 of 12 |

The points are consecutive ticks of those trajectories. This confirms the m7u1 proposal's warning (§6.1) that tick-0
goals are "few and alike". **The m7u1 held-out set alone cannot support an interpretable test.**

**The missing prerequisite** is a goal-source pool of tick-0 behaviour episodes that the model never trained on, large
enough to give 24 rare goals from distinct episodes.
- **Yield per episode:** leave-one-out over all 92 episodes (reference: the other 91; τ ∈ [32, 96]; budget 128; at
  most 1 reference reaches the box): **12 of 92 episodes (13 %, Wilson 95 % 7.6-21.4 %)** yield a goal.
- **What those goals look like** (one per episode):
  - rises of 315-2,547 above the spawn;
  - x from −1,650 to +1,715;
  - 9 of 12 witnesses composite: ground jump + double jump 6, with up-B or air tornado 3. The other 3 are a single
    up-B, and two single ground jumps with about 1,600 units of horizontal travel;
  - only 2 of 66 goal pairs with overlapping boxes.
- **Cost:** only the first 128 ticks of an episode matter, so the pool is cheap.

**The frozen model supports the test** (offline, forward passes only):
- identity: file, parameters and clock track all match;
- 32 of 32 recorded m7u1 decisions re-scored with the same choice: 26 bitwise-equal, max |Δscore| 3.5e-5 (m7u1
  batched some decisions);
- one-step accuracy in the first 128 ticks equals later ticks: position error median 2.42 vs 2.29, p99 58 vs 52;
- **open-loop drift from tick 0** is comparable to mid-episode or worse:

  | open-loop horizon | from tick 0 (held-out median error) | mid-episode (median error) |
  | --- | ---: | ---: |
  | 16 ticks | 273 | 108 |
  | 32 ticks | 488 | 274 |
  | 64 ticks | 878 | 682 |

  m7u1 passed at similar open-loop error through 4-tick replanning, so this is a risk, not a blocker.

**Reading proposed.** The test collects its own goal-source pool as its first phase, with no model update. Those are
this run's own held-out behaviour episodes. If the intended source was only m7u1's 12 held-out episodes, then no
interpretable tick-0 test exists, and this pool is the specific prerequisite.

## 3. Gate `m7u2` (proposed; not authorised)

**Capability.** The frozen m7u1 ensemble with the unchanged planner, starting from the normal tick-0 reset with no
prefix, reaches a commanded rare airborne point within 128 ticks more often than both controls.

**Scope label**, carried by every record: *planner-controlled reach of behaviour-drawn airborne points from the normal
tick-0 reset (frozen m7u1 model, one seed); not a landing, crossing, target or clear.*

### 3.1 Frozen model
- **Identity** as in §0: file, parameter digest, vocabulary, clock track rebuilt from the preserved m7u1 training
  sidecars, pinned world `ca1ac287…`.
- **Frozen by construction:** no optimizer is constructed, and the gate imports no training function (an import test
  checks this). The parameter digest is checked at preflight, after evaluation and after analysis.
- **Preflight reproduction:** 32 fixed recorded m7u1 decisions are re-scored; the chosen candidate must be identical
  and |Δscore| ≤ 1e-3.

### 3.2 Goal-source pool: this run's own held-out behaviour
- **360 behaviour episodes from the normal reset.** Each uses candidate 0 of stream `m7u2|0|collect|c###`, with the
  same fixed-draw generator, N = 64.
- **Length:** each is truncated in Python after 128 words, or ends earlier by a fall.
- **Checks:** each reset row equals the m7u1 tick-0 row in every field, and each word stream equals its offline RC
  regeneration.
- **Held out by construction:** no pool episode ever reaches a model update.

### 3.3 Goal eligibility and selection
- **Candidate (e, τ):**
  - τ ∈ [32, 96];
  - the row at τ is valid and airborne, and is not the fatal-fall tick;
  - y_τ − y_spawn ≥ 300.
- **Rarity:** q = the share of the 92 preserved m7u1 behaviour episodes that make a valid airborne reach of the ±150
  box at any input tick 1..128. They are read-only, from the same reset under the same behaviour. **Eligible when
  q ≤ 1 / 92.**
- **Selection:**
  - one goal per episode: the eligible τ with the smallest sha256(`m7u2|goal|e|τ`);
  - episodes ordered by sha256(`m7u2|goal|e`);
  - the first **24** are registered as k = 0..23, frozen before evaluation, with π(k) = (k + 12) mod 24.
- **Availability:** fewer than 24 goals makes the run **INCOMPLETE**. The chance of at least 24 is 1.00 at the
  measured 13 % yield, 0.95 at 9 % and 0.78 at the 7.6 % lower bound.
- **Why these goals test meaningful movement initiated from reset:**
  - at reset Mario stands in Wait with no velocity, both jumps, and nothing underway;
  - every goal is airborne and ≥ 300 above, so every success includes a controller-initiated jump;
  - rarity excludes what the behaviour does by default;
  - τ ≥ 32 excludes the first moments.
- **No route, movement type or target order is required.** The witness's composition is only reported.

### 3.4 Trials
- **Start:** a fresh process and the non-consuming reset (input_tick 0, step_count 0). The reset row must equal the
  recorded tick-0 row in every field, or the run is INVALID.
- **Control:** the arm controls from consumed tick 0 for at most 128 words. There is no prefix and no archived start.
- **Success:** the first valid reach (±150 per axis, airborne, valid, not the fatal-fall tick) ends the trial as a
  Python truncation. Otherwise the trial ends at the budget or at a fall.
- **Arms**, the unchanged m7u1 machinery:
  - **P:** commanded g.
  - **RC:** always candidate 0; no model is evaluated.
  - **S:** P's rule commanded π(g), scored on g.

  The three arms share stream `m7u2|0|goal|k`, which is never a pool episode's stream.
- **Planner settings:** N = 64, H = 64, execute 4 words then replan, 15 mutants, 64 refill segments, 48 fresh plans,
  the m7u1 cost and score.

### 3.5 Native ticks and caps

| phase | native ticks (cap) | wall cap |
| --- | ---: | ---: |
| P1: exact replay from tick 0 of m7u1's `g26_P` (171 words) and `g14_P` (183): words, every stored row field and the reach tick equal to their m7u1 sidecars. A stack-identity check only; no trial starts from them | 354 | 120 s |
| goal-source pool, 360 × 128 | 46,080 | 600 s |
| goal selection | 0 | 120 s |
| evaluation, 24 × 3 × 128 | 9,216 | 1,200 s |
| success replays from tick 0, ≤ (6 P + 2 RC + 2 S) × 128, plus analysis | 1,280 | 300 s |
| **total** | **56,930** (m7u1: 431,201 cap, 337,042 used) | **2,400 s** |

- **Projection:** about 19 min. It uses m7u1's measured rates: about 560 native ticks/s over 5 workers with the M7u
  wrappers, about 3 s per restart, and ≤ 1,536 planning decisions at 0.40 s p95.
- **Memory:** main process ≤ 3 GB (projected under 1 GB).
- **Launch readiness** (zero ticks; a refusal consumes nothing and is not a result): at least 4 GB available and
  10 GB free commit, and a 40-decision timing probe with p95 ≤ 0.5 s.
- **Stops:** any cap is **INCOMPLETE**, with no retry or extension. Any integrity failure is **INVALID**.

### 3.6 Rule `m7u2_tick0_rule_v1` (N = 24, one seed)

Paired counts: b_R = #(P ∧ ¬RC) and c_R = #(¬P ∧ RC); b_S and c_S likewise against S.

| outcome | condition |
| --- | --- |
| **PASS** | n_P ≥ 6 ∧ b_R − c_R ≥ 6 ∧ b_S − c_S ≥ 5 |
| **NULL** | b_R − c_R ≤ 1 ∨ b_S − c_S ≤ 0 |
| INCONCLUSIVE | otherwise; the record names the blocking condition |
| INVALID / INCOMPLETE | integrity failure / cap or goal availability |

- **Strength of the thresholds:** at minimal discordance, the exact one-sided sign test gives p = 1/64 against RC and
  1/32 against S.
- PASS and NULL are disjoint. No accuracy, attribution or calibration quantity enters the rule.
- **Reference points** (not predictions):
  - at m7u1's overall grounded rates (P 12/27, S 5/27), the expected b_S − c_S is about 6, so a PASS is likely but not
    certain;
  - at the grounded-free rate (2/9), the outcome would be NULL or INCONCLUSIVE.

### 3.7 Integrity (INVALID if any fails)
- identity of code, profile, executable `30a3913b…` and the frozen model, plus the preflight decision reproduction;
- P1 exact;
- every reset row equal to the tick-0 record;
- pool words equal to the RC regeneration;
- the platform equal to the frozen clock track on every live row;
- the parameter digest unchanged, and no optimizer constructed;
- every replayed success exact from tick 0;
- the ledger within caps;
- no BattleShip process left;
- outputs only under Git-ignored `runs/m7u2`;
- D: coverage over the base and every increment before launch.

No native RNG is inspected or controlled. Human recordings and the TAS are not used.

### 3.8 Evidence and reported diagnostics
- **Kept, as in m7u1:**
  - per-tick native rows and model inputs;
  - canonical words from tick 0;
  - every decision's candidates, scores and member predictions;
  - goals with their witness words and q;
  - the pool manifest;
  - phase ledgers and memory samples.
- **Reported only:**
  - an initiated-movement census per arm: status entries, with double jumps only from JumpAerialF/B entries, the
    first initiated rise, and the reach tick;
  - outcomes by witness composition and by |dx|;
  - MODEL / PLAN attribution;
  - the witness test from tick 0;
  - calibration and ambiguity flags;
  - the contrast with m7u1's grounded-free group.

## 4. What a result establishes

**A PASS establishes, on one seed and one frozen model:**
- from the normal tick-0 reset, with no prefix, archived start or model update;
- the planner reached rare airborne points drawn from its own behaviour, within 128 ticks;
- more often than the same machinery without the model, and than the same planner commanded elsewhere;
- with exact replays from tick 0.

This is **planner-controlled tick-0 reach of commanded local points**. It is the capability m7u1 could not establish.

**It does not establish:**
- a landing, a wall-top, a crossing, targets, a clear or speed;
- goals beyond 128 ticks, or sequences of goals;
- goals not drawn from behaviour;
- replication across seeds or retrained models;
- superiority over PPO.

**Readings of a NULL** (M = the MODEL share of P failures; W = the share of witnesses the ensemble accepts from tick 0):

| reading | condition | meaning |
| --- | --- | --- |
| rollout error from rest | M ≥ ½ | predicted reaching plans fail natively from the reset state |
| search | M < ½, W ≥ ½ | feasible continuations exist in the model, but 64 random-segment candidates do not find them from rest |
| false negatives | M < ½, W < ½ | the model rejects feasible continuations |
| undirected | b_S − c_S ≤ 0 with b_R − c_R ≥ 2 | the model changes behaviour, but not toward the command |

With m7u1's PASS, a NULL would localise the limit to control from free idle starts. That is the group m7u1 sampled
least and did worst on.

## 5. Implementation outline and decision requested

**New files:** `rl/m7u2_goals.py`, `rl/m7u2_rule.py`, `rl/m7u2_gate.py`, `rl/m7u2_tests.py`.

**Reused unchanged:**
- `rl/m7u_model.py`, only its load, rollout and score paths;
- `rl/m7u_planner.py`, `rl/m7u_state.py`, `rl/m7u_analysis.py` and `rl/m7u_worker.py`.

**Possible additive change:** a per-entry word limit for pool episodes. Whether trial entries with t = 0 already work
is verified first.

**Tests:**
- import isolation (no optimizer, no training);
- frozen-decision reproduction;
- reset identity;
- goal eligibility re-computed on the preserved m7u1 data, which must reproduce §2's counts;
- rule self-test;
- the offline e2e on the synthetic stand-in.

The planner is unchanged, so no new benchmark is needed; the readiness probe covers timing.

**Decision requested, in order:**
1. **The goal source.** Accept this run's own 360-episode pool, or treat the prerequisite as unmet.
2. **Zero-tick preparation:** implementation, tests and the offline checks.
3. **Then, separately, gate `m7u2`:** ≤ 56,930 native ticks, 40 min.

None of these is authorised by this document.
