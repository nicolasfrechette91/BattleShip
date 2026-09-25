# RL M7i: consolidating the agent's own wall crossing — proposal

Status (2026-09-25): **proposal, revision 2, for review.** Nothing is implemented, registered, trained, committed or
pushed.
- Revision 2 adds a no-training feasibility check (section 3), changes the warm start to `ckpt_001536000`
  (section 6.1), and inserts a small pre-registered signal pilot before any campaign (section 7).
- Review evidence lives in two git-ignored places: `runs/review/m7i_proposal_evidence/` (revision 1) and
  `runs/review/m7i_feasibility/` (revision 2).
- The M7h results are now recorded in the tracked, uncommitted
  [`rl_frontier_curriculum_m7h_results.md`](rl_frontier_curriculum_m7h_results.md).

This is the registered gate-4 response of M7h: "a separately registered consolidation proposal built on F and the
agent's own verified discoveries (never the fixtures), with no budget extension". It neither extends nor re-decides
M7h.

## 0. Summary

- **What seed 1 discovered.**
  - A chain: an air up-B from about (−300, 1,800) onto the ledge top (y 3,000), a leftward exit from the ledge, then a
    landing on the only left-side floor (y −1,950).
  - All 18 seed-1 left-region training episodes then fell, with returns of about −5.
- **Feasibility, without training.** 558 fresh-process episodes, 5 validation runs and a 3,221-row anchor replay.
  Each episode is an exact canonical prefix of that crossing followed by normal policy actions, run at 9 pre-declared
  cut points.
  - **`ckpt_001536000`** (the checkpoint nearest the discovery) **can sustain the crossing, but only greedily.**
    - Its deterministic policy crosses, lands and survives to the horizon from the ledge top (cuts 2,703 and 2,790).
      From the post-crossing cuts it lands and survives in 2 of 3 (2,817 and 3,000; it falls from 2,900).
    - Sampled, it crosses from the ledge in 57 of 60 episodes, but lands in only 4 and stays ≥ 60 ticks in none.
    - At the first backward window (cut 3,000) its outcomes vary: 13 of 30 schedule successes, 12 stable landings,
      2 survivals (return −0.60 against −5.19 for a fall), and **target 1 broken 3 times**, the first ever.
  - **`final`** (3,072,000) **cannot.**
    - Greedy, it falls or stays on the ledge.
    - Sampled, it makes 0 stable landings in 150 left-side or ledge episodes.
    - At cut 3,000 every one of its 30 episodes is the same: 24 floor ticks, then a fall (return spread 0.03).
  - The M7h continuation from 1,536,000 to 3,072,000 under the frontier rule is effectively one unregistered run of
    the control arm, and **it lost** that ability.
- **The PPO signal.**
  - Left-target breaks are common from left-air starts: 13–16 of 30.
  - **Surviving on the left is the bottleneck.** A survivor scores about +4.6 over a faller.
  - Before the up-B, staying right returns −0.46 to −1.22, which beats crossing and falling. So the crossing can only
    gain a positive advantage after left survival has been learned. That is exactly the order a backward schedule
    trains in (section 5).
- **Warm start: `ckpt_001536000`** for both arms. `final` is not viable: its first window gives PPO no signal to act on.
- **Before the nine-hour campaign:** the proof-of-mechanics checks, plus a **~2.5-hour, single-seed signal pilot**
  (arm E only, +409,600 transitions) with a registered go/no-go (section 7). The campaign runs only on "go".
- **Campaign (unchanged in form):**
  - arm E, anchored backward starts;
  - arm C, the matched control: M7h frontier continuation from the same checkpoint and archive;
  - 3 paired seeds, +2,048,000 transitions each, tick-0 evaluation, and the registered rule (section 9).
  - It remains a **single-source feasibility test** (section 6.6).
- **Unchanged:**
  - the native game, the process restart and the non-consuming tick-0 reset;
  - Track 1 and canonical inputs, obs v1, reward v2, PPO settings and accounting;
  - the evaluator and the tick-0 protocol;
  - no native RNG handling; no TAS or fixture data;
  - the feasibility evidence never enters training or any decision metric.

## 1. Verified starting point

| Item | Value | How verified |
| --- | --- | --- |
| Parent `main` | `15f7850`, pushed | `git ls-remote origin refs/heads/main` |
| decomp | `3c7fd5d0` on `rl-main`, pushed | `git ls-remote` |
| libultraship | `805f1950` on `m6/raphnet-bypass`, pushed | `git ls-remote` |
| torch | `3aa9c97`, detached | in `origin/agent/issue-batch`; pin unchanged |
| Executable | `1e7c62a0…` | equals the M7h manifest |
| M7h code in `15f7850` | fingerprint `fd61fcae…`, which is the amended code (76 files) | `m7h_matrix.code_fingerprint()` on the committed tree |
| M7h decision | gate 4, `discovered_not_consolidated`; record `73e13aa2…` | `runs/m7h/campaign/_matrix/analysis_n3.json`; byte-identical copy in `docs/` |

- **Uncommitted new files:**
  - `docs/rl_frontier_curriculum_m7h_results.{md,json}`;
  - `docs/rl_frontier_curriculum_m7h_analysis_n3.json`;
  - this proposal.
  - Everything else is git-ignored.
- **The feasibility scripts live outside `rl/`**, in `runs/review/m7i_feasibility/scripts/`. The M7h code fingerprint
  covers every non-test `rl/*.py`, so a new module there would drift M7h's recorded identity.
- **M7i will change that fingerprint.** Its `rl/m7i_*.py` modules will make `code_fingerprint()` differ from
  `fd61fcae`. M7h stays verifiable from a checkout of `15f7850`.

## 2. The discovery (revision 1 findings, unchanged)

- **Geometry** (native; `decomp/src/relocData/124_GRBonus1MarioFile2.c`):

  | Feature | Value |
  | --- | --- |
  | Wall (main solid left face) | x = −2,100, for y ∈ [−2,850, 3,000] |
  | Ledge top | y = 3,000, x ∈ [−2,100, −1,200] |
  | Main solid underside | y = −2,850 |
  | Only left floor (line 3) | y = −1,950, x ∈ [−3,900, −2,700] |
  | Left targets | 1 (−3,450, −2,550); 6 (−3,300, 3,300); 8 (−3,300, 600) |

- **Anchor `83112a8c`** (`m7h_f_s1`, 3,221 rows, digest `18169979…`).
  - Its start state comes from five own-run episodes; ticks 0–2,271 came from the first ~36,000 transitions of
    training.
  - The route:
    - it breaks target 7 at 2,634;
    - an air up-B (status 226) lands it on the ledge top at 2,702;
    - it jumps with an air fireball (224) and crosses at 2,816 (interpolated height about 4,114);
    - it lands on line 3 at 3,004 (x −2,783, 23 units from the floor's right end) and stays 24 grounded ticks;
    - at 3,028 it jumps right into the wall face, slides under the stage and falls at 3,220.
- **The other seed-1 left episodes.**
  - Ground up-B (225) from the ledge top leaves Mario helpless (status 58), a fatal fall in 2 of 2 episodes.
  - Two prefix-reproduced episodes broke target 8 and target 6, and fell.
  - All 18 fell, with returns between −5.32 and −4.23, against +0.565 for tick-0 episodes of the same period.
- **Tick-0 heights.** No final tick-0 policy of any seed rose above y 2,811; seed 1 never above 2,272.
- **Seed 2's entry is under the stage** (y −8,412), and seed 0 has none.

## 3. Feasibility check without training (revision 2)

### 3.1 Method

- **Harness.** `runs/review/m7i_feasibility/scripts/feasibility.py`, outside `rl/`.
- **Each episode is one fresh BattleShip process:**
  1. the ordinary non-consuming tick-0 `observe` (input_tick 0);
  2. an explicit prefix: the first τ Track 1 actions of `83112a8c`, sent as canonical native triples;
     - every row must consume tick i and stay `WaitingForAction`;
     - o_τ must equal the anchor replay's observation after row τ−1 in every field except `host_frame`;
  3. normal policy actions: `model.zip` plus frozen VecNormalize statistics, exactly as the evaluator applies them,
     until the native clear, the native failure (`btt_native_failure_v1`) or the step consuming tick 3,599.
- **Rewards.** btt_reward_v2, computed by the project's own `reward_step()`. It is rebased on o_τ, so prefix breaks
  earn nothing, as the M7h worker does.
- **Flags.** `SSB64_RL_NO_RENDER`, `SSB64_RAPHNET_DISABLE` and `SSB64_RL_TARGET_DIAG`. The target diagnostic is used
  for identity only; Phase K showed it does not change play.
- **Fidelity checks, all passed before any feasibility episode ran** (`validation.json`):
  - the anchor's 3,221 rows replay with digest equal to the recorded one;
  - **replay mode** reproduces three recorded M7h training rows exactly: return, policy steps, end reason, policy
    breaks and full digest (`83112a8c` −4.616, `79be8064` −4.343, `438d5fcb` −5.28);
  - **deterministic policy mode from tick 0** reproduces M7h's deterministic evaluation digest and return for both
    checkpoints: `final` `2abd30e0…` (0.4) and `ckpt_001536000` `3caf806d…` (−2.6).
- **Design, pre-declared before the first feasibility episode:**
  - cuts τ ∈ {3,000, 2,900, 2,817, 2,790, 2,703, 2,672, 2,605, 2,400, 2,160}. They cover six of the first eight
    pointer windows of revision 1, plus landmarks.
  - per cut and checkpoint: 1 deterministic episode and 30 stochastic episodes, seeded by
    `sha256("m7i_feasibility|ckpt|τ|k")`.
  - checkpoints: `final` and `ckpt_001536000`. The crossing episode ended at 1,525,760 transitions, so this is the
    nearest set; the previous one, 1,433,600, is 92,160 transitions earlier.
- **Replay verification: 155 / 155 exact.** Every episode with a landing, a left-target break or a clear, plus the
  first stochastic episode of each (checkpoint, cut), was replayed from tick 0 in a fresh process through `m7f_trace`.
  All consumed ticks matched and every digest was equal (`verify.json`).
- **Exclusion.** This evidence is **never** an input to training, the anchor, the archive or any registered decision
  metric. The M7i source guard forbids `runs/review`. The signal pilot (section 7) re-measures its own baseline instead
  of reusing these numbers.

### 3.2 Results (stochastic 30 episodes per cell; deterministic outcome in brackets)

Column key:
- cross: over-wall entries;
- land: a left-floor landing;
- stable: ≥ 60 floor ticks;
- succ: the schedule success of section 5 (a policy-row landing at least 60 ticks after τ);
- LB: episodes with a left-target break (target IDs);
- fall / hor: episodes ending in a fall / at the horizon;
- R̄: mean return.

**`ckpt_001536000`:**

| τ | o_τ | cross | land | stable | succ | LB (IDs) | fall / hor | R̄ | [det] |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3,000 | airborne over the left floor, 4 ticks before the anchor lands | — | 30 | **12** | **13** | 3 (**1**) | 28 / 2 | −4.88 | **lands, survives, −0.60** |
| 2,900 | airborne far left (−4,197, 4,526) | — | 1 | 0 | 1 | **16** (1, 6, 8) | 30 / 0 | −4.60 | falls, −5.32 |
| 2,817 | just crossed (−2,119, 4,136) | — | 5 | 2 | 5 | 9 (6, 8) | 30 / 0 | −5.07 | **lands, survives, −0.78** |
| 2,790 | on the ledge top, before the jump | 29 | 2 | 0 | 2 | 6 (6, 8) | 29 / 1 | −4.93 | **crosses, lands, survives, −0.81** |
| 2,703 | just landed on the ledge top | 28 | 2 | 0 | 2 | 7 (6, 8) | 28 / 2 | −4.80 | **crosses, lands, survives, −0.90** |
| 2,672 | falling at (−225, 1,778), jumps spent | 1 | 0 | 0 | 0 | 0 | 1 / 29 | −1.08 | stays right, −0.93 |
| 2,605 | M7h's delivered start (1,497, 820) | 0 | 0 | 0 | 0 | 0 | 0 / 30 | −0.46 | stays right, −0.99 |
| 2,400 | grounded on the right step | 0 | 0 | 0 | 0 | 0 | 0 / 30 | −0.93 | −1.20 |
| 2,160 | airborne (677, −1,787) | 0 | 0 | 0 | 0 | 0 | 0 / 30 | −0.67 | −1.44 |

**`final`:**

| τ | cross | land | stable | succ | LB (IDs) | fall / hor | R̄ | [det] |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3,000 | — | 30 (**every episode exactly 24 floor ticks**) | 0 | 0 | 0 | 30 / 0 | −5.22 (sd 0.03) | falls, −5.21 |
| 2,900 | — | 1 | 0 | 1 | 13 (6, 8) | 30 / 0 | −4.82 | falls |
| 2,817 | — | 0 | 0 | 0 | 5 (6, 8) | 30 / 0 | −5.22 | falls |
| 2,790 | 29 | 0 | 0 | 0 | 4 (6) | 29 / 1 | −5.03 | crosses, falls |
| 2,703 | 29 | 0 | 0 | 0 | 7 (6) | 29 / 1 | −4.95 | stays on the ledge, −0.90 |
| 2,672 | 2 | 0 | 0 | 0 | 0 | 2 / 28 | −1.22 | stays right |
| 2,605 | 1 | 0 | 0 | 0 | 0 | 1 / 29 | −0.74 | stays right |
| 2,400 | 0 | 0 | 0 | 0 | 0 | 0 / 30 | −0.83 | stays right |
| 2,160 | 0 | 0 | 0 | 0 | 0 | 0 / 30 | −0.51 | stays right |

**Totals.** 558 episodes, with 0 `through_face` entries, 0 under-stage entries and 0 clears. At cut 2,817, "cross"
counts re-entries after drifting back.

**Critic value V(o_τ).**

| Checkpoint | τ = 3,000 | τ = 2,817 | τ = 2,790 | τ = 2,703 | τ = 2,605 |
| --- | --- | --- | --- | --- | --- |
| `final` | −2.94 | −1.68 | −1.35 | −1.73 | −1.08 |
| `ckpt_001536000` | −1.79 | −1.25 | −0.77 | −0.73 | −0.64 |

The critic is optimistic about the left side compared with the realized −4.6 to −5.2.

### 3.3 What it shows

1. **The crossing itself is not the obstacle.** From the ledge top, both checkpoints cross in 28–29 of 30 episodes,
   mostly by jumping. Ground up-B from the ledge happens in 9–16 of 30.
2. **The left side is the obstacle.**
   - The anchor lands 23 units from the floor's right end, in the middle of a fireball.
   - `final` walks off that edge in 30 of 30 episodes, the moment it regains control.
   - `ckpt_001536000` sometimes stays: 12 of 30 are stable, and 2 survive 600 ticks.
3. **Left targets are within reach.** From left-air states, 13–16 of 30 episodes break target 6 or 8, and
   `ckpt_001536000` also breaks target 1.
4. **The approach is the rare link.** From just before the up-B (cut 2,672), only 1–2 of 30 episodes reach the ledge.
   Earlier cuts almost never do.
5. **Continued frontier training erased a capability.** Between 1,536,000 and 3,072,000 transitions, the greedy
   policy lost the ability to land and survive; `ckpt_001536000` has it and `final` does not.
6. **Neither checkpoint sustains the crossing under sampling from the ledge.** `ckpt_001536000` lands in 4 of 60
   episodes and `final` in 0 of 60; none stays ≥ 60 ticks. A campaign therefore needs PPO to amplify a rare success;
   section 7 tests that cheaply first.

## 4. Outcome measures (unchanged except (1))

The geometry constants are those of section 2. A test checks them against `m7g_fixture.decode_stage_geometry()`.
Training modules hard-code them.

- **(1) Valid wall crossing.**
  - An entry event is a pair of consecutive live steps (P, E) with x_P ≥ −2,100 > x_E.
  - y_c is the height at x = −2,100, linearly interpolated between P and E.
  - The classes:
    - `over_wall`: y_c ≥ 3,000;
    - `under_stage`: y_c ≤ −2,850;
    - `through_face`: otherwise, and treated as an integrity problem;
    - `unpaired`: the predecessor is not live; reported only.
  - **Policy-controlled** *(revision 2 wording)*: step E is produced by a policy action, that is, E's row is ≥ τ.
    Every tick-0 evaluation step qualifies.
- **(2a) Left landing:** a live grounded step on line 3 (|y + 1,950| ≤ 1, −3,901 ≤ x ≤ −2,699) after an over-wall
  entry, or on a policy row when the start is already left of the wall.
- **(2b) Stable presence:** at least 60 such ticks.
- **(3a) Left-target break after crossing:** IDs 1, 6 or 8, after an over-wall entry in the same episode.
- **(3b) Any left-target break:** reported.
- **(4) Tick-0 reproduction:** (1)–(3) on the normal tick-0 evaluation (unchanged evaluator, Phase K protocol).
  - Every episode whose `btt_eval_metrics_v1` shows a left entry or a left-target break is replayed exactly from tick 0
    and classified.
- **(5) Verified clears and completion times:** Phase K clear verification; `completion_time_passed` in frames and
  seconds, against the TAS's 446 frames (7.43 s).

## 5. How PPO can receive a useful signal despite the −5 returns

- **The −5 is the fall penalty, not a crossing penalty.**
  - PPO's advantage is relative to the critic's baseline V(o).
  - Among episodes that start in the same anchored window, what separates good from bad is survival:

    | Outcome, from `ckpt_001536000` | Return |
    | --- | --- |
    | Survive (cut 3,000) | −0.60 |
    | Fall (cut 3,000) | −5.19 |
    | Fall with a left target | −4.2 |
    | Each further left target | +1 |

  - The realized spread at τ = 3,000 is 1.18 (sd), so PPO gets a directional signal there. At `final` the same window
    is degenerate (sd 0.03): every episode is the same fall.
- **Why the backward order matters for the crossing's sign.**
  - From the pre-up-B states, staying right returns −0.46 to −1.22, which is better than crossing and falling.
  - A policy trained on these states *before* it can survive on the left learns to avoid the crossing. The M7h
    continuation from 1,536,000 to `final` is consistent with that: it lost its greedy landing.
  - Anchored starts first train states where the choice is only fall versus survive (cuts ≥ 2,817), which raises
    V(left side).
  - The crossing's advantage at the ledge turns positive once E[return | on the left] exceeds staying right (about
    −0.5 to −0.9).
  - Break-even: survive 600 ticks (−0.6) and break about 0.3 left targets on average. The current break rate from
    left-air starts is 0.4–0.5.
- **Credit reaches the relevant decisions.** With γ = 0.999 and λ = 0.995, a fall 140–260 ticks after a landing
  decision is weighted 0.77–0.87.
- **Prefix ticks earn nothing and are not transitions.** This is unchanged, so the signal is carried only by
  policy-controlled steps.
- **What would kill the signal.** If PPO drove the post-crossing success rate to 0 before learning survival, the
  pointer would stall at the first window, which is gate 5 or 6. The signal pilot (section 7) measures exactly this
  before any campaign.

## 6. The experiment

### 6.1 Warm start (revision 2): `ckpt_001536000` for both arms

**The set** is `runs/m7h/campaign/m7h_f_s1/checkpoints/ckpt_001536000`:
- `checkpoint.json` `7804e4d0…`;
- 1,536,000 transitions;
- policy and optimizer, VecNormalize, and a curriculum archive of 3,350 cells (2,324 eligible). The archive already
  holds 97 cells first reached by `83112a8c`, 54 left cells and 2 ledge cells.

It is loaded through the existing resume path with a lineage record. The model is re-seeded with
`set_random_seed(base_seed)`.

**Why not `final`:**
- its first window is degenerate;
- it has 0 stable landings in 150 sampled left or ledge episodes;
- its greedy policy never survives.

A warm start from `final` would very likely stall the pointer at cut 3,000 and end at gate 6. It would measure
forgetting, not consolidation.

**The cost of `ckpt_001536000`:**
- Its tick-0 play is weaker: T 4.08 at the 1,536,000 curve label, against 4.36 at `final`, with a greedy return of
  −2.6.
- Choosing it also uses post-hoc information: section 6.6 applies to it exactly as to the seed.

### 6.2 Arms

| | E: `btt_curriculum_anchor_backward_v1` | C: `btt_curriculum_frontier_v1_warm` |
| --- | --- | --- |
| Tick-0 starts | p0 = 1/2 | p0 = 1/2 |
| Other starts | a cut τ on the registered anchor, from the backward window (section 6.3) | the M7h frontier rule unchanged, over the archive loaded from the warm start; ingestion continues |
| Start delivery | M7h's prefix phase after the non-consuming reset: prefix rows unrewarded, rebase on o_τ, artifact contiguous from tick 0, o_τ checked against the registered anchor observation | identical |
| Curriculum generator | `sha256("btt_curriculum_anchor_backward_v1", seed)` | `sha256("btt_curriculum_frontier_v1", seed)`, re-seeded |
| Everything else | M7e PPO settings (`ent_coef` 0), obs v1, reward v2, Track 1, N = 5 with M7c standby, no-render, Raphnet bypass, diagnostics off in training | identical |

**The anchor** is registered by `m7i_campaign.py register-anchor` into `runs/m7i/_anchor/anchor.json`, with its own
sha256. It holds:
- the source: run `m7h_f_s1`, episode `83112a8c`, from `curriculum/left_episodes.jsonl`;
- the Track 1 bytes and the digest `18169979…`;
- the M7h entry verification record;
- the lineage;
- the observation after every row, from a registration replay;
- the landmarks by rule: E_A = 2,816, G_A = 3,004, H_A = 3,027.

Training reads only this file.

### 6.3 The backward schedule (arm E, unchanged from revision 1)

- **Cuts.** τ ∈ [1, 3,000]. The pointer τ* starts at 3,000, and each start draws τ uniformly from
  [max(1, τ* − 119), τ*].
- **Success.** A policy row r ≥ τ + 60 that is a left-floor landing, with a policy-controlled `over_wall` entry first
  if o_τ is not left. Under-stage recoveries never count.
- **Moving the pointer.** Take blocks of the next 10 completed anchored episodes under the current τ*. If at least 5
  succeed, τ* ← max(120, τ* − 120). The pointer never moves forward, and its state is saved in every set.
- **Measured baseline for the first window** (`ckpt_001536000`, stochastic): 13 of 30 at τ = 3,000 and 1 of 30 at
  τ = 2,900.
  - A block therefore succeeds about 20 % of the time before any training, so the pointer needs PPO to raise the rate
    to 1/2.
  - This baseline is design evidence only. It is not registered as a threshold.

### 6.4 Seeds, budget, checkpoints, evaluation

- **Continuation seeds:** 1001, 1002 and 1003, in pairs (E_j, C_j).
- **Budget:** +2,048,000 policy transitions per run, taking the cumulative total from 1,536,000 to 3,584,000. This is
  a hard maximum; prefix ticks are not budgeted.
- **Checkpoints:** every 102,400 transitions, plus `final`.
- **Evaluation:** tick-0 only, with the unchanged evaluator, the Phase K protocol and `SSB64_RL_TARGET_DIAG=1` in the
  evaluation workers only.
  - `start`: `ckpt_001536000` gets a new 100 + 100 evaluation. Before that, the new code must re-evaluate the
    existing 65-episode M7h label for this checkpoint with every episode equal.
  - curve at +409,600, +819,200, +1,228,800 and +1,638,400: 60 + 5 each;
  - `final`: 100 + 100;
  - outcome replays per section 4 (4).
- **Order:** E1, C1, E2, C2, E3, C3. Each launch passes the M7h launch gate and runs under the memory stop.

### 6.5 Why the matched frontier-continuation control is fair

1. **Same state.**
   - Both arms start from one checkpoint set: identical policy and optimizer state, VecNormalize statistics and
     archive.
   - The archive already contains the crossing: 97 of its cells come from `83112a8c`. C is not denied the
     discovery; it chooses among its states by visit count, E by the backward pointer.
2. **Same knowledge.** E draws only from one trajectory that C's archive also holds. What E adds is the *selection
   rule*, which is the treatment.
3. **Same accounting.**
   - Both arms use the same p0, PPO settings, seeds, policy-transition budget, tick-0 evaluation, verification and
     rule.
   - The comparison is equal in policy transitions, not in wall-clock time. E replays longer prefixes, and prefix
     ticks are reported for both arms and budgeted for neither.
4. **Not a strawman.**
   - C is the registered method that made the discovery, run exactly as registered, with no retuning.
   - Its one realized continuation from this checkpoint (M7h 1,536,000 → 3,072,000) produced no tick-0 crossing and
     lost the greedy landing. Re-running it with fresh paired seeds gives that observation a proper matched,
     replicated test instead of an anecdote.
5. **The asymmetry is stated.**
   - E's registration (anchor, warm start, windows) uses seed-1 observations made after the fact; C's rule predates
     them.
   - The rule guards against that: gate 2 needs X_E ≥ 10 out of 100 *and* X_E > X_C in at least 2 of 3 pairs. The
     result is labelled single-source.

### 6.6 Selection risk: seed and checkpoint

- **What was chosen after seeing results.** Seed 1, the anchor and now the warm-start checkpoint were all chosen after
  seeing outcomes.
- **What M7i can show:** that PPO, from this checkpoint, can or cannot turn this self-generated crossing into tick-0
  behavior better than the frontier rule. Paired seeds replicate *training noise*, not *the discovery* or *the
  checkpoint choice*.
- **What it cannot show:** reproducibility across seeds, or the rate at which a seed discovers a usable anchor. M7h
  saw 1 of 3.
- **Stage C (separately registered, only after gate 1 or 2)** is the route to generality:
  - fresh, never-observed seeds;
  - the M7h frontier rule from scratch until a registered, automatic rule selects each seed's own first verified
    over-wall crossing with a landing;
  - the anchor's checkpoint chosen by a rule fixed in advance (for example, the first set after the anchor episode);
  - the same matched comparison;
  - seeds without an anchor count as failures.

## 7. Pilot before the campaign (revision 2)

**P1–P7: proof of mechanics, as in revision 1.** No learning claims; pass/fail.

| # | Check |
| --- | --- |
| P1 | unit tests |
| P2 | anchor registration replay |
| P3 | 200 exact cut replays through `run_prefix_phase` |
| P4 | warm-start accounting smoke on pilot seed 999 |
| P5 | determinism |
| P6 | R1 curriculum-off reproduction, plus the equality re-evaluation of the 1,536,000 label |
| P7 | timing and the stop drill |

**P8: the signal pilot.** A proof of mechanism, not evidence of tick-0 learning. It has no control, uses one pilot
seed, and never counts toward the rule.

- **Run:** arm E only, seed 999, warm start `ckpt_001536000`, +409,600 transitions (80 rollouts). About 25–35 min,
  including the prefix stall of about 150–250 anchored starts.
- **Measurement:**
  - The anchored harness is re-implemented inside M7i as `rl/m7i_anchored_eval.py`: fresh processes, exact prefixes,
    frozen statistics.
  - It runs at the five post-up-B cuts {3,000, 2,900, 2,817, 2,790, 2,703}: 30 stochastic episodes with fixed seeds
    plus 1 deterministic, on **both** the warm start (re-measured, not taken from section 3) and the pilot's final set.
  - About 310 episodes, 15–20 min on 3 processes.
- **GO** requires P1–P7 passed, and at least one of:
  - (a) the pilot's training pointer moved at least one step (τ* ≤ 2,880);
  - (b) stochastic schedule successes over the five cuts at least **doubled** against the re-measured warm-start
    baseline (a ratio ≥ 2, with at least 10 more successes).
- **NO-GO:** stop and report. No campaign. The next step is the user's decision; nothing adapts automatically.
- **Reported, never gating:** stable landings, left-target breaks by ID, falls, reward terms, tick-0 T of the pilot
  final (60 + 5 episodes, harm check), and the pointer log.
- **Total before the campaign:** about 2.5 h (P1–P7 about 1.5–2 h, P8 about 1 h).

## 8. Resources

| Step | Estimate |
| --- | --- |
| P1–P8 | ≈ 2.5 h |
| Campaign on GO: E runs | 35–50 min each; many early anchored starts cost about 2.1 s of prefix dispatch each |
| Campaign on GO: C runs | ≈ 37 min each |
| Campaign on GO: evaluation | ≈ 25 min per run, + about 10 min for the `start` label |
| **Campaign total on GO** | **≈ 7–7.5 h** |

Commit draw is expected to stay at or below 6 GiB (M7h measured 5.14–5.84 GiB), with at most 10 game processes and
about 0.5 GB of disk per run.

## 9. Decision rule (unchanged; registered before any campaign run)

This rule is applied once, after all six runs and replays. First gate fires.

**Definitions** (the 100 final stochastic tick-0 episodes of pair j):

| Symbol | Definition |
| --- | --- |
| X_{a,j} | episodes with a verified over-wall entry |
| Λ_{a,j} | episodes that land after an entry |
| Θ_{a,j} | episodes with a left-target break after an entry |
| k_{a,j} | 1 if any of the 200 final episodes is a verified clear |
| π_j | E_j's lowest pointer |

| Gate | Condition | Response |
| --- | --- | --- |
| 0 integrity | anything unverified, not tick-0, or with bad provenance; a prefix mismatch; a reset violation; `through_face`; an incomplete census; P1–P8 not passed (or NO-GO) | no decision |
| 1 clears | Σ_j k_{E,j} ≥ 2 and Σ_j k_{C,j} = 0 | clears reached (single source) → Stage C |
| 2 consolidated | #{j : X_{E,j} ≥ 10 and X_{E,j} > X_{C,j}} ≥ 2 | crossing consolidated from tick 0 (single source); sub-labels *with landing* (#{j : Λ_{E,j} ≥ 1} ≥ 2) and *with left target* (#{j : Θ_{E,j} ≥ 1} ≥ 2) → Stage C |
| 3 continuation reproduces | #{j : X_{C,j} ≥ 1} ≥ 2 | anchored effect not established |
| 4 reproduced | #{j : X_{E,j} ≥ 1} ≥ 2 | reproduced, not consolidated |
| 5 anchored only | #{j : π_j ≤ E_A − 600 = 2,216} ≥ 2 | consolidated from anchored starts only |
| 6 null | — | no consolidation at +2,048,000; no extension |

**Reported, never gating:** Λ, Θ, (3b), stable presence, clears and times, T_E − T_C, falls, deterministic results,
curves, pointer and training classes.

## 10. The smallest implementation plan

Nothing in `m7h_*.py`, the evaluator, the base environment, the worker protocol or native code changes.

**New files:**

| File | Content | Estimated lines |
| --- | --- | --- |
| `rl/m7i_anchor.py` | geometry and classification, anchor record, backward schedule, `AnchorSource` | 400–500 |
| `rl/m7i_worker.py` | a subclass of `CurriculumWorkerWrapper`: anchor contract identity, and a trace subclass with entry and landing fields | 150–220 |
| `rl/m7i_vec.py` | a subclass of `CurriculumVecEnv`: E's source; C's warm-start archive with a re-seeded selector; state in the sets | 120–180 |
| `rl/m7i_anchored_eval.py` (new in revision 2) | the P8 measurement, promoted from the review harness, with its validation checks: replay-mode equality and tick-0 deterministic equality | 250–350 |
| `rl/m7i_campaign.py` | `register-anchor`, freeze, `preflight` (P1–P8 with the registered go/no-go), `train`, `evaluate`, `verify-outcomes`, `analyze` | 750–950 |
| `rl/m7i_tests.py` | tests | 550–750 |
| `rl/configs/m7i/*.toml` | 6 campaign profiles and 2 pilot profiles | 8 files |

**Inherited edits** (about 100–160 lines):
- `rl/experiment_config.py`: the two M7i contracts, resume only from the registered source set;
- `rl/m7_trainer.py`: the attach under the flag, plus the archive and pointer in sets.

**Totals:** about 2,250–3,050 lines.

**Order:**
1. I1: pure modules and P1.
2. I2: integration and P2–P5.
3. I3: P6–P8, freeze, report; **stop for the campaign's approval, which requires GO.**

## 11. Fixed and non-goals

- **Fixed:** everything in M7h section 1.
- **Non-goals:**
  - native RNG handling;
  - TAS or fixture data;
  - route hints beyond the registered own-run anchor;
  - reward or loss changes;
  - non-tick-0 evaluation of the registered outcomes;
  - an M7h extension;
  - a silent budget extension.
- **The fixtures stay validation evidence only;** no design element reads them.

## 12. Open decisions

1. **Warm start.** `ckpt_001536000` is recommended; `final` is shown non-viable.
2. **Signal pilot P8.** Its budget (+409,600) and its GO criterion (pointer move, or success doubled with at least 10
   more).
3. **Control.** The M7h-rule continuation is recommended, per section 6.5. A tick-0-only continuation is cheaper but
   changes p0.
4. **Campaign budget.** +2,048,000 or +1,024,000.
5. **Schedule and thresholds.** A window of 120, block of 10, ρ = 1/2, step of 120; X ≥ 10; the gate-5 distance of
   600.
6. **Seeds.** 1001–1003 for the campaign, 999 for the pilots.
7. **Committing.** Whether to commit the M7h results files; the user commits.

## Revision history

- **Revision 1 (2026-09-25):**
  - the anchored backward design with a frontier-continuation control;
  - warm start `final`.
- **Revision 2 (2026-09-25):**
  - the no-training feasibility check (section 3);
  - the warm start changed to `ckpt_001536000`, with the reason;
  - the fairness argument (section 6.5) and the PPO-signal analysis (section 5);
  - the P8 signal pilot with a registered go/no-go before the campaign;
  - the policy-controlled wording of (1);
  - the fingerprint note;
  - the M7h results summary written.
