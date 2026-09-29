# Goal-conditioned exploration after M7r: design (2026-09-28, revision 5)

Status: **revision 5 = revision 4 (first valid reach; the 120-tick rule a non-decisive diagnostic) plus the pre-gate
corrections of section 13: the user's four confirmed contract choices, the goal-blind safeguard (rule
`m7s1_return_rule_v2`), a goal-on live identity check in P1, and exact native replay of any claimed clear.** Stage 1
(learned return, gate `m7s1`) is implemented as opt-in Python (implementation record
`docs/rl_gcsl_return_m7s_implementation.md`). **The gate was approved and run once on 2026-09-29. Registered outcome:
3, inconclusive (learner not functional in 3 of 3 seeds; all three R goal-blind; no clear). Report:
`docs/rl_gcsl_return_m7s_results.md`. Stage 2 is not authorised.** The text below is the design as registered before
the run. Revision 1's
9,432,000-tick G gate, its 600-tick random tail, its own-trajectory subgoal chains and its `+20 cells` threshold are
withdrawn. Baseline unchanged: observation v3 + reward v2 (Track 1 per-tick PPO, M7n settings) stays selected; v4 and
the commitment contract `btt_commit_s9_b8_m2_d6_v1` stay opt-in. Inputs: `docs/rl_commit_m7r_results.md`,
`docs/rl_temporal_control_design_2026-09-28.md`, `docs/rl_exploration_credit_m7o_assessment.md`,
`docs/rl_geometry_scale_m7p_*.md`.

## 0. Evidence preservation (done; retained)

- Base `D:\BattleShip_runs_backup\2026-09-28`: `verification.json` `16b25bbe…` PASS (377,359 files, 16,968,155,612
  bytes), untouched.
- Increment `D:\BattleShip_runs_backup\2026-09-28_incr_m7r` (its `runs\` = source `runs\m7r\`): 5,163 files,
  209,454,870 bytes, verified by re-hashing the copies on D: → PASS, 0 mismatches (`verification.json` `620c9926…`).
- **Retained** base-plus-increment record `combined_coverage.json` (`ff16972c…`): all 382,522 regular files under
  `runs/` covered, 0 uncovered → PASS. Same machine only.
- Approved (decision U7): before any later native run, coverage must be verified across the base and every
  increment; the stage-1 driver enforces it (section 8) and its own outputs need a new dated increment afterwards.

## 1. Established findings (M7r registered result + post-hoc aggregates, never decision inputs)

Registered: M7r outcome 5 (inconclusive); PR1 learned in 3 / 3 seeds, ST1 in 0 / 3, no discovery, no regression.

Aggregates over the 360 M7r gate traces (300-unit cells of the stage box x ∈ [−3900, 3300], y ∈ [−4050, 3600] from the
`btt_spatial_v1` geometry; live ticks; off-stage positions excluded):

| # | finding | numbers |
| --- | --- | --- |
| F1 | No left-side progress | 0 / 360 entered x < −2100 or touched line 0 (ledge, y 3000) or line 3; floors touched: 1, 2, 4 only (M7n / M7o: 0 left entries at 3,072,000 ticks) |
| F2 | Reach is bounded below the ledge | column right of the overhang edge (x −1200…−600) max y 1,543; anywhere 2,684 |
| F3 | The rare frontier is the high band | y ≥ 1500: 36 cells, 18 singletons (50 %), 34 reached by ≤ 3 of 360; below: 1–7 % singletons |
| F4 | Reward-driven training narrows it | y ≥ 1500 reached by 7 / 60 untrained episodes per arm, 8 / 90 (C) and 4 / 90 (F) stochastic finals; 20-episode unions −9…−31 % |
| F5 | High cells are reached late | first tick at y ≥ 1500: p10 792, p50 2,272, p90 2,864 |
| F6 | Unused time | 56–58 % of the horizon follows the last target break in the finals |
| F7 | Untrained random play reaches as widely as trained play | unions: C untrained 245, F untrained 229, C final 227, F final 219 |
| F8 | Run-unique cells (60 episodes per run) | 0–18 per run; C arm-unique 38 / 26 / 18 vs F 9 / 8 / 0 (valid only at 60 episodes) |
| F9 | Rare achievements are lost by training | target 2 broken only in untrained labels |
| F10 | Chance return of an untrained per-tick policy (recomputed with the section 4.1 validity) | phase-A proxy = one F-untrained run's 20 episodes, held-out = the other two runs' 40: cells validly reached by 1–2 of 20 ("rare"): 42–51 per run, first reached at median tick 1,354 (p75 2,140), held-out chance rate 0.055 pooled (0.041 / 0.038 / 0.092 per run, p90 0.125); 3–9 of 20 ("mid"): 0.29; ≥ 10 ("common"): 0.69. (Revision 3's figures, 26–41 / 0.059 / median 1,772, used the withdrawn 120-tick exclusion.) |
| F11 | Per-tick credit over those intervals | γ = 0.999, λ = 0.995: at 1,354 ticks γ^t = 0.26, (γλ)^t = 2.9 × 10⁻⁴; at the high band's 2,272 ticks 0.10 and 1.2 × 10⁻⁶; GAE horizon ≈ 167 ticks |

## 2. Two hypotheses, two stages

- **H1 learned return.** From normal tick-0 starts, a goal-conditioned policy can learn to reach, reliably and above
  a matched untrained policy, rare states that its own autonomous episodes have already reached.
- **H2 frontier expansion.** Once return is reliable, exploring beyond the returned-to states discovers new, relevant
  states faster than an equally resourced control.

Stage 1 (gate `m7s1`) tests H1 only: no random tail, no novelty outcome; newly found cells cannot pass. Stage 2 is a
separately authorised later design, contingent on a stage-1 pass (section 10).

## 3. Algorithm (approved: GCSL; section 11 correction 1)

On-policy PPO with a goal reward is not plausible here: a rare goal is reached in about 5–6 % of untrained episodes
(F10), and GAE passes (γλ)^t ≈ 10⁻⁴–10⁻⁶ of a reward 1,350–2,300 ticks back (F11). Distance shaping would make "get
closer" the objective, and own-trajectory subgoal chains are an implicit route. **Chosen: goal-conditioned supervised
learning (GCSL-style iterated hindsight relabelling) on the seed's own tick-0 episodes.** No reward, no discount.

**Tick convention (every M7s document, contract text and record; revision 5 clarification).** An M7s tick index k
(written "tick k" or "consumed tick k", k = 1…T) is the **ordinal of a native update** in the episode: after the k-th
update the native `step_count` is k and the returned observation reports `input_tick = k`, while that update's native
`consumed_tick` field is **k − 1**. The reset observation is tick 0 (`input_tick` 0, `step_count` 0) and consumes no
tick. The action a_t (t = 0…T−1) is submitted while the observation reads `input_tick = t`, is consumed as native
`consumed_tick = t`, and produces the state of tick t + 1. A count of "native ticks" is a count of updates. The probe's
`reach_tick`, the sidecar's `set_tick` / `reach_tick` / `ticks`, the tracker's `steps` and `max_episode_steps` all use k;
only artifact action rows and the tracker digest carry the 0-based native `consumed_tick`.

**Supervised example** (`btt_gcsl_return_v1`). For one own episode with consumed ticks k = 1…T: o_t is the policy
observation before the native action a_t (t = 0…T−1; o_0 = the normal tick-0 reset observation), and c_k the valid
achieved cell of the state after consumed tick k (section 4.1; "none" when not valid). An example is

    (o_t, a_t, g = c_{t+h}, h)        with h ≥ 1 the first k − t > 0 at which c_k = g, and t + h ≤ T,

presented to the policy as (o_t, goal features of g at the position of o_t, remaining-horizon input b / H) with target
a_t (the Track 1 stick and button indices of the recorded native word), H = 3,600. **Remaining-horizon input**: b is
the tick budget within which g is to be reached. Because an episode that reached g at t + h also reached it within any
larger budget, every b ∈ [h, H − t] is a correct label ("within" semantics): b = h with probability ½, otherwise b
uniform over the integers [h, H − t]. **Sampling**: episode uniform over the seed's own training episodes (phase A and
R's completed phase-B episodes), t uniform over the ticks of that episode that have a valid future cell, g uniform
over the distinct valid cells occurring after t. **Recorded prefix only**: t < T and t + h ≤ T always, T = the
episode's recorded ticks; a phase-B episode cut by the tick quota supplies pairs only when both the action and its
achieved future lie inside its recorded prefix (nothing after the cut exists in the data). Cross-entropy on both heads; 100 Adam steps (batch 512, 3 × 10⁻⁴,
gradient norm ≤ 0.5) after every 5,120 collected native ticks, matching PPO's per-rollout optimiser exposure.

**Evaluation (and collection) horizon**: b = H − t, the episode's own remaining time, computed from the tick counter
alone. No per-goal timing, no archive timing, no route and no information from the future of the evaluation episode
enters; the value b = H − t is within every training example's support by construction.

**Intermediate states are learning targets, not a route.** Every state an own episode reached after t is a hindsight
goal for a_t during training only. At execution the policy receives only the commanded goal and b: no waypoint list,
no subgoal reward, no action replay, no reset state, no start other than normal tick 0. Training material is only the
seed's own tick-0 episodes; no human or TAS action or state, fixture, archived expert route, M7r / M7p record or
reset state is ever training material, a goal or a start. M7r aggregates are used only offline, to calibrate this
design.

## 4. Stage 1 specification (section 11 corrections 1 and 3)

### 4.1 Goal cells (`btt_goal_cell_v1`) and provenance

- Box x ∈ [−3900, 3300], y ∈ [−4050, 3600]: the bounding box of the static `btt_spatial_v1` vertices together with the
  moving platform's derived surface range; cell side 300 → 24 × 26 bins. Cell = (i, j, contact), contact = `air`, or
  the grounded `floor_line_id` when `ground_air_state` is 0 and the id is ≥ 0 (floor lines here: 0, 1, 2, 3, 4, 19;
  any other grounded id is `other`).
- **Valid** tick (one definition for success, archive and labels): `btt_active` 1, `fighter_valid` 1, position inside
  the box, and not the tick on which a native-failure (fatal) fall ends the episode. Nothing else is excluded; the
  120-tick survival rule is only a non-decisive diagnostic (section 4.4).
- **Provenance**: per seed, phase A = the seed's initial network (section 4.3) running 20 normal tick-0 episodes with
  the null goal. Its valid cells after consumed ticks (k ≥ 1) form the frozen archive A. E is frozen from A before
  any update: E_rare = the first 10 cells reached by 1–2 of the 20 episodes, E_mid = the first 5 reached by 3–9, in
  the order of sha256("m7s1|E|seed|cell"), i.e. with no position preference. Every E goal records its phase-A witness
  episodes (episode id, artifact, native action digest, first-reach tick); nothing else can supply a goal.

### 4.2 Goal features (`btt_goal_obs_v3_v1`)

The v3 observation (606 values) is unchanged. A separate 14-value goal vector: has-goal (1); goal-cell centre scaled
to [−1, 1] by the box (2); goal centre − current position, same scale, clipped to [−2, 2] (2); contact one-hot over
air, lines 0 / 1 / 2 / 3 / 4 / 19, other (8); b / H (1). The null goal (phase A) is all zeros. The same function
computes the vector in the worker and in the relabelling learner.

### 4.3 Matched arms: weights, goal branch, archive access, schedule, sampling

- **Initial weights**: per seed one parameter set, drawn once from `torch.Generator` seeded with
  sha256("m7s1|init|seed"), orthogonal gains √2 (v3 trunk 606 → 64, goal branch 14 → 32, joint 96 → 64), 0.01
  (heads 64 → 9 and 64 → 8), zero biases. It is saved as `init.pt`; its parameter digest is recorded. **R** starts from
  it; **U** loads the same file and is never updated (digest re-checked after every U phase and evaluation).
- **Goal branch** (approved: separate, bounded): 14 → 32 tanh units, concatenated with the 64 tanh units of the v3
  trunk. It is bounded by the tanh and by a fixed gain κ = 1.0 on its weights (orthogonal gain √2 · κ; fixed, not
  tuned). Registered initialisation check (section 7): the goal / state sensitivity ratio of the joint layer on real
  v3 observations must lie in [0.1, 10], and trunk and branch saturation are reported.
- **Archive access and goal schedule**: both arms command goals only from E and the frozen phase-A archive A, through
  one schedule pre-generated per seed with a registered seed. Schedule entry (worker rank r, worker episode k) = up to
  8 goals: each drawn with probability ½ uniformly from E (approved: goals from E in half of the draws), otherwise
  from A with weight (1 + n)^(−½), n = phase-A episodes that reached the cell. The next entry goal is commanded after
  the tick of a valid reach and first applies to the next action tick (section 4.4). R and U use the identical schedule (its digest is recorded). R's phase-B achieved cells are used
  **only** for relabelling (approved: only the agent's own achieved futures); U's only for its chance statistics.
- **Action sampling**: stochastic, from per-episode numpy generators seeded by (seed, phase, rank, worker episode) in
  collection and by (seed, evaluation entry) in evaluation, identical for R and U (common random numbers).
- **Evaluation plan**: 30 entries per seed, E_rare × 2 and E_mid × 2, ordered by sha256("m7s1|eval|seed|goal|repeat"),
  entry e run by worker e mod 5, identical for R and U.

### 4.4 Successful return: the first valid reach

**Decisive success** is the first valid reach of the commanded cell: the fighter occupies the commanded cell (i, j,
contact) on a valid tick (section 4.1) of an episode that started at normal tick 0, before the end of the 3,600-tick
horizon. The reach tick is recorded. An evaluation episode **ends on that tick** as a Python-side truncation with
`truncation_reason = goal_reached`, also when the reach falls on the native horizon tick (the reason then overrides
`max_episode_steps`); its native words are preserved. A valid first reach requires no future survival period. A cell
occupied on the fatal-fall tick is not valid; a cell occupied on the tick of a native clear (termination) is a clear,
not a return: the episode ends `terminated` with `native_clear`, never truncated, and records no reach (also on the
horizon tick). Any claimed clear needs an exact native replay (section 5). In collection a reach does not end the
episode: after the update of reach tick k the next schedule goal is commanded; it enters the observation o_k
(`input_tick` k) and first applies to action a_k, which is native `consumed_tick` k and produces tick k + 1. No action is
inserted on the reach tick, and the next goal can first be reached at tick k + 1 (sidecar `set_tick = k`).

The tracker labels every truncation `end_reason = horizon`. Every consumer (the evaluation rows, the rule, the
replays, the reported statistics) distinguishes a return (`goal_reached`) from a worker quota cut (`tick_quota`) and
the native horizon (`max_episode_steps`) by `truncation_reason` only, and cross-checks it against the sidecar: a
return has its reach on the last recorded tick; any other end has no reach; an evaluation episode ending by
`tick_quota` or an unknown reason is an integrity failure.

**Non-decisive diagnostic `survival_120`**, collection only: for every reach, `True` when no fatal fall ends the
episode within the next 120 consumed ticks, `False` when one does, `None` when the episode ends otherwise first
(censored; always the case in evaluation, which ends on the reach). It is reported only. It never changes a return
outcome, the archive or a supervised label.

### 4.5 Exact replay: a tested property, not a general claim

What is tested: replaying the recorded native words of an episode on a fresh process from normal tick 0 reproduced
that episode in every case checked (M7r: the eight pinned artifacts word for word through the live commit stack and
12 / 12 gate episodes with equal digests and equal per-tick trace rows; earlier M1e / M6 / M7 regressions). What is
**not** claimed: that every native episode is deterministic. Processes differ in timing, OS scheduling and standby
promotion, and no RNG is inspected or controlled. GCSL does not need a determinism guarantee to learn from what
actually happened; the "own episode = valid demonstration" argument holds exactly only where replay is exact. The gate
therefore re-tests exact replay for the evidence it claims (the first two R and first two U rare returns per seed).
A replay is attempted only for a `goal_reached` row whose reach is its last recorded tick; it must show an equal action
digest, per-tick cells equal to the sidecar's, and the goal first validly occupied on the recorded reach tick. Any
mismatch makes the gate invalid.

## 5. Stage 1 gate `m7s1`: arms, budget

| item | value |
| --- | --- |
| arms | **R** (GCSL learner) and **U** (identical initial parameters, goal branch, E, archive, schedule and sampling seeds; never updated), per seed |
| seeds | 0, 1, 2; fresh; normal tick-0 starts only; horizon 3,600; N = 5 workers + 1 standby each (M7n environment) |
| P1 live identity check (before any training) | (a) the eight pinned Track 1 artifacts driven through the goal worker stack with the null goal reproduce every word; (b) the goal-on check of section 5.1 |
| phase A (shared) | 20 episodes per seed (4 per worker) |
| phase B | **R: 358,400 native ticks per seed** (5 workers × 71,680; 70 chunks of 5,120, 7,000 gradient steps); **U: the same 358,400 ticks without updates** (approved matched budget) |
| held-out evaluation | 30 episodes per arm per seed, identical goals, order and sampling seeds |
| exact replays | ≤ 4 returns per seed; ≤ 2 claimed clears per seed |

Budget arithmetic (upper bounds, every episode ≤ 3,600 ticks):

| item | computation | native ticks |
| --- | --- | ---: |
| P1 (a) null-goal identity | 3,361 + 2,560 + 6 × 3,600 | 27,521 |
| P1 (b) goal-on identity | 2 repetitions × 774 updates (native `consumed_tick` 0–773 each; resets consume none; no word after the reach update) | 1,548 |
| **P1 cap** | | **29,069** |
| phase A | 3 seeds × 20 × 3,600 | 216,000 |
| phase B | 3 seeds × 2 arms × 358,400 | 2,150,400 |
| evaluation | 3 seeds × 2 arms × 30 × 3,600 | 648,000 |
| exact return replays | 3 seeds × 4 × 3,600 | 43,200 |
| exact clear replays | 3 seeds × 2 × 3,600 | 21,600 |
| **total cap** | | **3,108,269** |

M7r's comparable total was 3,139,200: the cap is 30,931 below it (revision 4: 3,085,121; +1,548 for P1 (b), +21,600
for clear replays). Runtime is not claimed.

### 5.1 P1 goal-on identity check (revision 5)

P1 must also exercise a goal-on `goal_reached` end before any training. Registered (in `rl/m7s_gate.py` `GOAL_ON`, pinned
by the approval record):

- **Trace**: `runs/m7q/_equiv/input_all/fx_m7e_s2_best6.json.gz` (sha256 `856c0e8d…`), a normal tick-0 episode of the
  M7e seed-2 PPO policy (its recorded raw replies; the words come from its artifact). Validation evidence only: never
  training material, a goal of E, an archive cell or a start.
- **Goal** `(17, 8, floor line 2)`, first validly occupied at M7s tick **774** (`reach_tick` 774): the state after the
  774th update, whose native `consumed_tick` is 773 and whose returned `input_tick` and `step_count` are 774. The same
  bin is occupied in the air from tick 771 (native `consumed_tick` 770), so a probe that ignored the contact class would
  end three ticks early.
- **Expectations** recomputed from the trace at preflight and at run time, each checked against its registered value:
  word-prefix digest `8821b2ad…` (774 Track 1 words, native `consumed_tick` 0–773); v3 block digest `c9000896…` (775 ×
  606 float32 for ticks 0–774, the reset observation plus one per update, built by the unchanged v3 wrapper from the
  recorded replies; equal to the builder applied directly).
- **Run**: one real goal worker (the M7n v3 environment with its standby) in evaluation mode (`plan`, `end_on_success`),
  commanding that goal, fed the recorded words, **twice** (a cold start, then the normal lifecycle: promotion or cold
  fallback). No word after the 774th (native `consumed_tick` 773) is ever sent.
- **Tick accounting, identical for each repetition** (each starts from a fresh process frozen at tick 0):

  | quantity | value |
  | --- | --- |
  | reset observation (launch or promotion, plus the v3 wrapper's non-consuming `observe`) | `input_tick` 0, `step_count` 0, no update |
  | first submitted word: at `input_tick` / native `consumed_tick` | 0 / 0 |
  | last submitted word: at `input_tick` / native `consumed_tick` | 773 / 773 |
  | final native `consumed_tick` | 773 |
  | returned next `input_tick` (= `step_count` = `reach_tick`) | 774 |
  | native updates | 774 |

  Two repetitions: 1,548 updates, exactly the P1 (b) cap.
- **Every repetition must show**: the recorded artifact words (native `consumed_tick` 0–773) and tracker digest equal
  to the pinned prefix; the v3 block bit-identical at every tick 0–774; the goal vector exact; the first valid reach at
  tick 774 and no earlier; the episode ending there as a truncation with `truncation_reason = goal_reached` (tracker
  `end_reason = horizon`, 774 steps, not cleared, preserved, normal tick-0 start mode; sidecar commanded / reach /
  cells / end agree).
- **Clean process termination**: the process alive and parked after the Python-side truncation, then ended by
  `terminate()` when retired by the next reset or by close (never killed, never exited on its own); after close the
  worker owns no live process, its standby closed with the launcher thread joined and no cleanup failure, and no
  BattleShip process remains on the machine.
- Any mismatch (or a raised check) stops the check and the gate before phase A; the null-goal part runs first and a
  failure there skips the goal-on part.

## 6. Pre-registered comparison and rule (section 11 correction 2; exploratory)

The 20 rare-goal evaluation episodes are 10 goals × 2, so episodes are not independent trials. **The goal is the unit
of analysis and R is compared with U on the same goals.** Per seed s and goal g ∈ E_rare: r_g, u_g ∈ {0, 1, 2}
successes in the two evaluation episodes of each arm, d_g = r_g − u_g, T_s = Σ_g d_g. Under H0 (R and U have the
same success probability on every goal, the two arms' episodes independent), each d_g is symmetric about 0, so the
**exact one-sided sign-flip p** = #{ε ∈ {±1}^10 : Σ ε_g |d_g| ≥ T_s} / 2^10 is valid conditional on the |d_g|. With
10 goals the smallest p is 1 / 1024, and p ≤ 0.05 needs R ahead on at least 5 goals net of reversals.

- **Rare pass (seed s)**: T_s ≥ 5, R succeeds on ≥ 3 distinct E_rare goals, and p ≤ 0.05.
- **Functional learner (seed s)**: R succeeds in ≥ 7 of its 10 E_mid episodes and Σ_{E_mid} d_g ≥ 3.
- **Data present (seed s)**: D ≥ 6, where D = the number of E_rare goals validly reached by ≥ 2 of R's own phase-B
  episodes (demonstrations beyond the phase-A witnesses).
- r_g and u_g count **returns only**: evaluation episodes whose `truncation_reason` is `goal_reached` (section 4.4). A
  native clear is never a return.
- **Goal-blind safeguard (revision 5)**: a seed whose trained R is goal-blind — R's post-training goal-swap action TV
  (section 7) below **0.01**, strictly — is **never a rare pass**, whatever its success counts; generic behaviour that
  visits several goals is not learned return. The threshold is the existing 0.01, registered before any live run and
  never tuned (pinned in the policy contract, the rule digest and the approval record). A missing, non-finite or
  inconsistent goal-sensitivity record makes the gate invalid.

**Rule `m7s1_return_rule_v2`** (applied once; v2 = v1 plus the goal-blind safeguard; v1 was never applied):

| # | outcome | condition |
| --- | --- | --- |
| 0 | invalid / incomplete | an integrity failure (P1 identity check, word or sidecar mismatch, accounting, a U parameter change, a claimed return or clear that does not replay, a missing or inconsistent goal-sensitivity record) / a crashed seed |
| 1 | **pass: return learned (exploratory)** | rare pass in ≥ 2 seeds, each with a goal-sighted R |
| 2 | **fail: return not learned** (for this learner at this budget) | in ≥ 2 seeds: functional **and** data present **and** T_s ≤ 1 |
| 3 | inconclusive | otherwise; the record names the blocking condition |

A null is **inconclusive, not a rejection**, when:

- the learner was not functional (method or implementation not working);
- D < 6 (its own data held too few demonstrations);
- 1 < T_s < 5, or p > 0.05 with T_s ≥ 5;
- the rare criteria were met by a goal-blind R (the record reports R's and U's rare and mid success counts, the distinct
  goals, T_s, p and both goal-swap TVs);
- seeds disagree.

Reported, never deciding: U's phase-B chance visit rate per goal (about 100 episodes), commanded-goal reaches of R and
U in collection with their `survival_120` diagnostic, the goal-sensitivity diagnostics other than the goal-blind flag
(section 7), targets, new cells and clears (verified or not). **The gate is exploratory**: three seeds, ten goals,
two episodes per goal and arm.

## 7. Goal-input scaling risk and the initialisation check

v3's actor saturates at layer 1 (M7p: 0.77–0.82, driven by the segment-geometry block). A goal appended to the 606
inputs would be dominated (a goal-blind policy); scaling it up would add to the saturation. The goal therefore enters
through its own bounded branch. At initialisation, on real v3 observations built from the recorded native replies of
the eight pinned traces and goals drawn from their own cells, the implementation measures:

- trunk and branch saturation (the fraction of |tanh| > 0.95);
- the **goal / state sensitivity ratio**: the mean joint-layer change for a goal swap divided by that for a state swap
  (registered range [0.1, 10]);
- the action-distribution change for a goal swap (total variation; small by construction with 0.01 head gains).

The gain is fixed at κ = 1.0. **After training**, on 4,000 states from R's own episodes and the frozen E cells, the
same measurement is reported for R and for U (= the initial parameters) so that a goal-blind policy is visible:

- R's goal-swap action TV next to U's;
- their ratio;
- a `goal_blind_flag` when R's goal-swap TV is below 0.01. **Revision 5: this flag is decisive for a pass** (section
  6: a goal-blind R cannot pass); the threshold stays 0.01 and is not tuned after results.

The trainer also records trunk / branch saturation and a goal-shuffle action TV after every chunk. These, and every
other sensitivity number, are reported only.

Results are in the implementation record.

## 8. Stops

- **Launch is refused unless:**
  - the offline tests pass;
  - coverage PASSes over the D: base and every increment;
  - no game process is running;
  - the executable is present;
  - no gate directory exists;
  - an approval record matches the code, contracts, rule, P1 registration, tick caps and executable;
  - the pinned P1 goal-on expectations recompute without a problem (no game).
- **During the run:**
  - P1 (the null-goal and the goal-on identity checks, section 5.1) must pass before phase A; any mismatch stops the
    gate with no training started.
  - Any integrity failure stops the gate, including a claimed clear that does not replay.
  - A crash leaves that seed incomplete.
  - There is no automatic retry, extension, retune or performance-based early stop.
  - Per-phase tick caps are enforced by the driver.

## 9. What a pass establishes (section 11 correction 4)

**A pass establishes only learned return to previously achieved goals**: at this small budget, from normal tick-0
starts, a GCSL policy trained on its own episodes reached rare cells its own untrained episodes had reached more often
than the identical untrained policy on the same goals. It does **not**:

- select GCSL as the full BTT agent;
- change the selected baseline (v3 + reward v2);
- establish frontier expansion (H2), crossings or target performance;
- authorise stage 2.

A fail is specific to this learner, representation and budget.

## 10. Stage 2 (frontier expansion): separately authorised, only after a stage-1 pass

Outline only:

- **Treatment:** a learned return, then an exploration tail.
- **Control:** the **same tail process and length**, started at the matched tick without the learned return, so
  novelty cannot come from extra random actions.
- **Progress:** only a native-replay-verified qualified crossing, left-target break or clear counts as progress.
- **Newly reached cells elsewhere** are exploratory evidence with a null calibrated inside that gate at the same
  episode counts; no threshold is carried over from a different number of episodes.

## 11. Decisions recorded (2026-09-28)

**Approved:**

- GCSL over goal-conditioned DQN.
- 300-unit cells × contact, and a frozen set of 10 rare + 5 mid goals, for this exploratory gate.
- A separate, bounded goal branch.
- Goals from E in half of the draws; relabelling only on the agent's own achieved futures.
- R and U evaluated stochastically on identical frozen goals and order.
- U's matched 358,400-tick collection.
- Coverage verified across the D: base and increments before any later native run.
- Every episode starts at normal tick 0; no human or TAS trace, archived expert route, reset state or waypoint
  sequence may enter training.

**Corrections applied:**

1. The supervised example (o_t, a_t, g = c_{t+h}, h) and the remaining-horizon input, with evaluation b = H − t
   (section 3).
2. A goal-level paired sign-flip comparison of R with U on the same goals replaces the independent-trial p; the
   distinct-goal requirement is kept; the gate is labelled exploratory (section 6).
3. Matched initial weights, goal-branch initialisation, archive access, schedule and sampling seeds; exact replay
   stated as a tested property (section 4).
4. The scope of a pass (section 9).

The gate itself is not authorised.

## 12. Contract correction (2026-09-28): first valid reach restored

**Registered decisive rule**, restored: success is the first valid reach of the commanded cell, and an evaluation
episode ends on that tick. The 120-tick survival rule is only the diagnostic `survival_120` of section 4.4, and it
never changes a return outcome, the archive or a supervised label.

**Why the 120-tick rule appeared:**

1. For the chance-return calibration (F10) I excluded the last 120 ticks before a fatal fall, as a "terminal plunge"
   filter. The M7a fall sequence takes about 96 ticks from leaving the stage to the native failure, and I did not want
   cells passed while falling to death to count as reached.
2. Revision 2 carried that filter into "eligible", unregistered, so it quietly became part of the goal archive and
   the labels.
3. When the implementation had to end evaluation at success, the filter could not be evaluated on the reach tick,
   because it depends on the future. I turned it into a 120-tick confirmation window that voided a reach followed by a
   fall.
4. That made the decisive rule differ from the registered first valid reach: it depended on the future and delayed
   evaluation termination. The labels had also been built from a different validity.

It is now removed from every decisive path. Validity excludes only the fatal-fall tick itself, and F10 / F11 are
recomputed with that validity.

**Also recorded:**

- `end_reason = horizon` for Python truncations is accepted on the condition that every consumer uses
  `truncation_reason` (section 4.4); a test covers it.
- κ stays fixed at 1.0, and goal-swap sensitivity is reported after training (section 7).
- Phase-B quota-cut episodes supply pairs from their recorded prefix only (section 3).

## 13. Pre-gate corrections (2026-09-28, revision 5)

**Contract choices confirmed by the user** (now explicit in the goal contract description, digest `22b0919e…`):

1. A valid first reach requires no future survival period.
2. `goal_reached` takes precedence over `max_episode_steps` when a valid reach occurs on the horizon tick.
3. A simultaneous native clear is recorded as a clear, not an ordinary return, and any claimed clear needs exact native
   replay. The gate replays the first two clear candidates per seed (evaluation R, evaluation U, phase B R, phase B U,
   phase A; deduplicated by native action digest) with the project's clear verifier (`m7d_run.replay_one`: fresh
   process from tick 0, native clear, `completion_time_passed` and `completion_input_tick` equal to the recorded pair,
   never collapsed). Only a verified clear is claimed; a candidate beyond the cap is reported and never claimed; a
   replayed clear that does not verify makes the gate invalid. A clear row is accepted by the evaluation analysis
   only when its four recorded facts agree (clear with `native_clear`, the cleared flag, ten targets, both clocks).
4. A new collection goal selected after a reach applies to the next action tick; no action is inserted on the reach
   tick (section 4.4).

**Safeguards added before gate approval:**

1. **Goal-blind safeguard** (section 6, rule `m7s1_return_rule_v2`, digest `bea670ce…`): a trained R with
   `goal_blind_flag = true` (post-training goal-swap action TV < 0.01) cannot register a rare pass; the seed is
   inconclusive and its success counts are reported. The 0.01 threshold is the existing registered value, unchanged
   and not to be tuned after results. Confirmed by the user (2026-09-28): goal blindness blocks a pass only; a
   goal-blind seed that independently meets the registered failure conditions still counts toward outcome 2.
2. **P1 goal-on identity check** (section 5.1): the exact controller-word prefix, the unchanged v3 observation block,
   the first valid reach tick, `truncation_reason = goal_reached` and clean process termination, on a pinned normal
   tick-0 trace, before any training; its 1,548 ticks are inside the P1 cap (29,069) and the total cap (3,108,269).

**Tick-accounting reconciliation (2026-09-28, read-only; no code change).** "Reach tick 774" names the M7s tick
ordinal (the returned `input_tick` / `step_count` 774), not the native `consumed_tick` field, which is 773 on that
update (verified on the pinned trace's recorded replies: `steps[773]` has `consumed_tick` 773, `input_tick` 774,
`step_count` 774 and is the first reply in cell `17,8,2`; the artifact rows used are `consumed_tick` 0–773). Each
repetition therefore makes exactly 774 native updates and the 1,548 cap is correct; the null-goal part counts the
same way (N recorded words = N updates). The tick convention is now stated in section 3 and applied in sections 4.4, 5
and 5.1. Two pinned code strings use the ordinal wording and were left unchanged so that no approval identity moves:
the `GOAL_ON` comment in `rl/m7s_gate.py` ("first validly occupied on consumed tick 774") and the goal contract's
`next_goal` text ("first applies to action a_k (consumed tick k + 1)"); both read correctly under the section 3
convention.

All of this is implemented and tested offline (`docs/rl_gcsl_return_m7s_implementation.md`); nothing was launched,
trained or approved. **The gate itself is not authorised.**
