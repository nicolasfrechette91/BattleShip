# M7u proposal: learned dynamics model + short-horizon planning (revision 2, 2026-09-29)

Status: **proposal for review.** Nothing was launched, replayed, trained, implemented or committed for it. Observation
v3 + reward v2 (Track 1 PPO) stays the selected baseline and v4 stays opt-in. M7t remains stopped before final
acceptance and is not revived: no quasimetric, distance head, goal node or set readout appears below. Every registered
outcome (M7o, M7p, M7r, M7s, M7t) stands.

**Revision 2** follows the user's review of revision 1 (same day). Revision 1 was overwritten; this list is its record.

| # | review point | change |
| --- | --- | --- |
| 1 | learning-signal argument | Exact replay is now cited only for reproducibility. A source-backed table (§3) gives each piece of hidden native state its coverage condition. **Withdrawn:** "3 words cover jump squat and turn" |
| 2 | model specification | Exact recursive state, input, heads, losses and rollout step. Learned parts are separated from deterministic featurisation, with the consistency mechanism for each (§4) |
| 3 | no-learning control | **Withdrawn:** "RC = the planner with an untrained model". RC is now the same machinery selecting candidate 0 without evaluating any model (§5.2) |
| 4 | prefix scope | Stated as a diagnostic after own recorded prefixes; prefix ticks are itemised in the ledger and kept in replay truth (§6.1) |
| 5 | gate length | One capability, one seed, 40 goals, ≤ 432,000 native ticks, **60 min hard cap**. The 90,000-tick pilot is replaced by a zero-tick benchmark (§6, §7) |
| 6 | compute | Exact FLOP accounting, plus the offline benchmark that must set the runtime figures. **Withdrawn:** revision 1's runtime estimates (§7) |
| 7 | pass and null | A pass must beat both controls natively. Readings of a null are listed, and prediction accuracy never decides (§6.5) |

## 0. Verified state (read-only, 2026-09-29)

| item | state |
| --- | --- |
| parent | `main` at `4122981` = `origin/main`. `d97d128` committed the M7r / M7s / M7t code and documents. Working tree: `replay/*.py`, `replay/README.md` modified and `replay/replay_history.py` untracked since this session began. That is the user's replay work, left untouched. This document is the only file this proposal adds |
| submodules | `decomp e4f06348` (rl-main = origin), `libultraship 805f1950` (m6/raphnet-bypass = origin), `torch 3aa9c97` (detached), all unchanged |
| D: preservation | Base `2026-09-28` PASS: 377,359 files. `_incr_m7r` PASS: 5,163. `_incr_m7s` PASS: 9,103. Together these are all 391,625 regular files under `runs/` (junctions excluded; newest file 2026-09-29 00:32). `_incr_m7t_logs` PASS covers all 50 `logs/m7t_*` files. Every copy is on another disk of the same machine |
| stale items | `rl/m7s_gate.py` `BACKUP_INCREMENTS` lists only M7r. The external `guide.md` stops at M7g |

## 1. The learning signal, corrected

**What exact replay does and does not show.** Exact replay shows **reproducibility**: from tick 0, the native state is
a deterministic function of the submitted words. It does **not** show that v4, or v4 plus any word window, determines
the next state. The game keeps state the diagnostics do not export (§3).

The case for a forward model is therefore narrower:

- **Supervision.** Its target, the next native fields, is observed on every tick under any behaviour, in native units
  and with no horizon. The supervision does not depend on the behaviour reaching anything.
- **What its input cannot determine:**
  - hidden native state, which the source audit confines to named statuses and conditions (§3);
  - finite-data error;
  - approximation error at discontinuities.

  Over a 64-tick rollout these compound.
- **Whether that residue still permits control** is empirical, and m7u1 tests exactly that.

The M7s measurements concern inverse (action) labels, whose goal information from near-uniform behaviour was ≈ 0 beyond
h ≈ 64. They say nothing about the forward residue in either direction.

## 2. Candidates

| | **A. dynamics ensemble + MPC (primary)** | **B. goal-conditioned PPO on the same goals (strongest simpler alternative)** |
| --- | --- | --- |
| learns | p(next native fields \| model state, word) | π(word \| state, goal), dense potential-based progress reward, γ 0.99 |
| a rare outcome is learnable if | its pieces are well sampled (random data jumps, double jumps and up-Bs constantly; only their timed composition is rare; M7f: 14 of 3,074 sequences reached wall-top height) and the hidden-state residue is small in the statuses involved | its own rollouts already make progress toward it; progress shaping is myopic exactly where timing matters (an immediate double jump gains height now but lowers the apex; M7p: double-jump timing sets the up-B start height) |
| data | off-policy, reused every epoch | on-policy |
| a failure is | attributable: realized error on executed words vs search (§5.3) | low success, not attributable |
| risk | untried here, compounding, discontinuities, §3 residue, planning compute | project record: PPO never produced a first event it did not already sample (0 left entries in 360 M7r episodes) |

A stays primary. B is the recorded alternative if A's gate is null.

## 3. Hidden native state and remaining uncertainty (item 1)

The model's recursive state (§4.1) carries:
- the last 4 submitted words;
- the 5-level tap counters of the last 3 ticks;
- the previous status id and the facing at status start;
- ticks in the current status;
- the last grounded floor line;
- a tornado bit.

Coverage below is judged against exactly that state. Sources: `decomp e4f06348`.

| native state | set and read | lives | covered? |
| --- | --- | --- | --- |
| KneeBend `input_source` | at entry: STICK if stick_y ≥ 53 (from Run: > 44) and `tap_stick_y` ≤ 3, otherwise BUTTON on a C-button tap edge; stick has priority (`ftcommonkneebend.c` GetInputType*, SetStatusParam). It selects the jump-velocity formula and short-hop eligibility | 3 ticks (anim length 3, speed 1) | **Yes, conditionally.** A KneeBend state was entered within the last 3 ticks (status tics ≤ 2), so the entry word and the entry tick's tap level are in the state. Since entry happened, the source is STICK iff the entry word has stick y 80 (≥ 53) and that tap level is ≤ 3, otherwise BUTTON, so the pre-entry word (the edge) is not needed; it can lie outside the window. It holds while Mario's `kneebend_anim_length` is 3 and no hitlag occurs in the squat (true on BTT, where nothing hits Mario) |
| KneeBend `jump_force`, `is_shorthop` | stick_y at entry, then max with stick_y each interrupt unless up-B or up-smash fires; short hop = BUTTON source ∧ kneebend frame ≤ 3 ∧ C release edge (`:19-27, 38-49`) | same | yes: words since entry, same condition |
| Turn `button_mask` | A / B taps accumulated from Turn's interrupt until the flip (motion flag1), then OR-ed into `button_tap` once (`ftcommonturn.c:34-37, 104-114`) | entry → flip | **Only if the flip is ≤ 3 ticks after entry.** The audit reports the first update; not re-verified here |
| Turn `lr_dash`, `lr_turn`, `attacks4_buffer` | set at entry from the entering path; the buffer counts per interrupt (`:47-52, 120-133`) | whole Turn | yes: previous status id, facing at status start, ticks in status |
| Squat `is_allow_pass`, `pass_wait`, `unk_0x8` | a pass-eligible entry sets TRUE / 3 / 3; the countdown drops through at 0 (`ftcommonsquat.c:77-93, 138-150`) | first 3 ticks | likely: the entry path was not traced; covered if it is decided by the entry tick's tap level and floor line |
| FallSpecial `drift`, `landing_lag`, pass / interrupt flags | passed by the entering move (up-B: 0.6, …, 0.28; `ftmariospecialhi.c:14`) | whole helpless fall | yes: previous status id |
| Mario `specialhi.is_air_bool` | FALSE for SpecialHi, TRUE for SpecialAirHi (`ftmariospecialhi.c:148, 161`) | whole move | yes: status id |
| `coll_data.ignore_line_id` | the floor line at Pass start (`ftcommonpass.c:29`); reset by every status change (`ftmain.c:4759`) | Pass only | yes: last grounded floor line |
| Mario `is_expend_tornado` | set when the **air** tornado's script flag2 fires (`ftmariospeciallw.c:36-42`); cleared on landing (`mpcommon.c:449`) and at spawn (`ftmanager.c:644, 665`); read by the B-tap rise (`:85, 176`) | a whole airtime | **Conditionally.** A bookkeeping bit "an air tornado ended since the last grounded tick" covers earlier tornadoes; within a tornado, (status, anim_frame) covers it only if flag2 fires at a fixed frame (script not audited) |
| motion-script cursors, loop counters, flags 0 / 2 / 3 | the script clock steps with the animation: `script_wait -= anim_speed`, with absolute waits against `anim_frame` (`ftmain.c:790-830, 196`) | within a status | **Likely:** (status id, anim_frame) determine them unless a script used on BTT branches on something other than time (not audited) |
| Attack1 `is_goto_followup`, `interrupt_catch_timer`; AttackLw3 `is_goto_attacklw3` | A taps during the move | the move | partly: only taps inside the 4-word window |
| Guard `release_lag`, `shield_decay_wait`, `slide_tics`, `is_release` | shield statuses (`ftcommon.h:606-621`) | the shield | not audited; partly |
| `shield_health` (55), `shield_heal_wait` | −1 per decay cycle while shielding (`ftcommonguard1.c:87`); +1 per 10 ticks off shield (`ftmain.c:3983-3991`) | whole episode | **No.** It affects bubble size, and a break at 0 (FuraFura) needs long cumulative shielding |
| moving platform translate / speed; moving target (id 2) position | stage and item animation | episode | treated as an exogenous clock track (§4.1), valid only if verified action-independent |
| `hold_stick_x/y` | read only on item-throw paths (`ftcommonattackair.c:125-151`, `ftcommonitemthrow.c:177`) | — | irrelevant: no items on BTT |
| fireball position, `vel_air`, lifetime | `wpmariofireball.c:98-202` | the projectile | exported, but outside the m7u1 model (§4.4) |

**What prediction uncertainty remains** (all of it measured and reported, none of it deciding):

1. **Structural residue**, confined to where the table's coverage is conditional or absent: Turn (flip timing), Squat,
   air tornado, jab and down-tilt follow-ups, shield.
2. **The exogenous-track assumption.** It is verified before training; if it fails, the run is invalid.
3. **Epistemic error** in states or combinations that 80 behaviour episodes sample rarely (long runs, heights near
   the wall).
4. **Approximation error at discontinuities** (landing tick, animation-end tick).
5. **Compounding.** A wrong discrete choice (landing a tick late) persists through the rollout.
6. **Optimizer's curse.** The planner prefers plans whose predicted cost is optimistically wrong.

Measured:
- held-out one-step error per status;
- 64-tick open-loop error on held-out behaviour sequences;
- realized error on executed blocks;
- the witness test (§5.3).

## 4. Model specification (item 2)

### 4.1 Recursive state Z_t

- **Native fields N_t** (stored every tick from the existing `SSB64_RL_SPATIAL` / `ENTITY` / `INPUT` replies; no
  native change):
  - Mario continuous: x, y, `vel_air` x / y, `vel_ground` x, floor distance, carry x / y, collision-diamond top and
    width, `anim_frame`, `anim_speed`;
  - Mario discrete: status id, ground/air, facing, `jumps_used`, fast fall, `floor_line_id`, contact bits (floor,
    ceil, lwall, rwall, edge), `hitlag_tics`, attack active, shield active, `motion_flag1 != 0`, `tap_stick_x`,
    `tap_stick_y` (5 levels: 1 / 2 / 3 / 4-253 / 254), `tics_since_last_z` (12 levels: 0-10, 11+);
  - the target live mask.

  Stored but **not** in Z: button echo and stick echo (verification only), native `status_total_tics`, projectiles.
- **History fields** — one bookkeeping function, applied identically to observed and imagined sequences:
  - words a_{t-1}, a_{t-2}, a_{t-3};
  - tap levels at t-1 and t-2;
  - previous status id and facing at status start;
  - ticks in the current status run (cap 240);
  - last grounded floor line;
  - tornado bit;
  - position at t-1 (for v4 displacement);
  - moving-target position at t-1.
- **Exogenous track E(t):** moving-group translate / speed and moving-target position, from a clock-indexed table
  built from the training episodes.
  - Use requires every training episode to hold exactly equal values at every live tick.
  - Before registration, the same check is run read-only on existing captures.
  - A mismatch makes the run **invalid**; it is never silently learned.

### 4.2 Learned vs deterministic

| component | kind |
| --- | --- |
| next Mario discrete and continuous fields, target breaks, fatal fall | **learned** (heads below) |
| status vocabulary; allowed-combination masks | data-derived from the training split, frozen before training |
| word window | exact (the plan's own words) |
| history fields | deterministic bookkeeping over the state sequence, identical in training and imagination |
| clock | +1 per tick (the step contract) |
| E(t) | recorded, verified table |
| input encoding: v4 scalings, class table v2, nearest-segment geometry from position + the reset line table + E(t), target relative positions | deterministic featurisation (observation-contract code); a torch port must equal `rl/m7q_obs.py` on recorded replies (max \|Δ\| ≤ 1e-5) |
| **absent by design** | gravity, drift, friction, collision tests, landing snaps, the R → A+Z fold, stick-band logic, status-transition rules. The planner module imports no transport code |

### 4.3 Input x_t = F(Z_t, a_t): 356 values

| block | values |
| --- | ---: |
| words a_t, a_{t-1}, a_{t-2}, a_{t-3} (stick one-hot 9 + button one-hot 8 each) | 68 |
| v4 agent block without its 9 echo fields and without `cliff_hold` (always 0 on BTT). Status tics come from bookkeeping | 35 |
| `motion_flag1 != 0`; tap levels at t-1, t-2 (x, y); current and previous status embeddings (16 + 16, learned); facing at status start; last grounded floor line (one-hot 21); tornado bit | 60 |
| class v2 one-hot | 23 |
| the 8 segments nearest to Mario (v4 geometry 8 + kind 7, sorted by closest-point distance) | 120 |
| targets (v4 encoding: relative position, displacement, live) | 50 |

### 4.4 Heads, losses and consistency

- **Trunk:** 356 → 256 → 256 (SiLU).
- **Heads**, decoded in this order; a conditional head receives embeddings of the values already chosen:

| head | output | conditioned on | loss (weight) |
| --- | --- | --- | --- |
| H1 status id | \|S\| ≤ 160 (statuses seen in training + "unseen") | trunk | CE (2) |
| H2 (ground/air, facing, jumps used, fast fall) | 24-way, **masked to combinations observed with the chosen status** | status emb 16 | CE (1) |
| H3 (floor line id, 5 contact bits) | joint over observed combinations (≤ 128), **masked to those observed with the chosen ground/air** | + H2 emb 8 | CE (2) |
| H4 (hitlag 0-8, attack active, shield, motion_flag1) | joint over observed combinations (≤ 64) | status emb | CE (1) |
| H5 controller counters | tap x (5), tap y (5), Z (12) | status emb | CE (1 each) |
| H6 continuous (12) | Δx, Δy (÷ 50), `vel_air` x / y, `vel_ground` (÷ 50), floor distance (÷ 2000, cap 8000), carry x / y (÷ 50), diamond top / width (÷ 2000), next `anim_frame` (÷ 60), `anim_speed` (÷ 2) | + H3 emb 8 (MLP 288 → 64 → 12) | Huber δ 1 (4 on Δx, Δy; 1 otherwise) |
| H7 target breaks (10) + H8 fatal fall (1) | Bernoulli; breaks only for live targets | trunk | BCE (1) |

Training uses **teacher forcing** (conditional heads receive the true values) and one-step loss only. There is no
unrolled loss in m7u1; this is a declared limitation, and §6.5 says how it shows. Ensemble: E = 3 members, different
initialisation and episode-level bootstrap. Adam 3e-4, batch 1,024 per member, S = 6,000 steps (the benchmark may lower
this, §7).

**Consistency of the imagined state:**
- **Controller edges** are never predicted. The model sees the exact word window, so an imagined press, hold or
  release is exactly what the plan submits. Game effects on inputs (forced 254 resets, Z-counter resets, hitlag
  accumulation, the hit tick clearing edges) reach the model only through learned heads (H4 hitlag, H5 counters).
- **Statuses and ground/air** can only take combinations seen in the training data (H1 → H2 masks). For example,
  "LandingLight while airborne" cannot be imagined unless it was recorded. Consequence: an unrecorded combination
  cannot be imagined either, which is a stated limit.
- **Contacts:** floor line and contact bits take only combinations recorded with the chosen ground/air (H3 mask).
  Position is **not** snapped to a line (that would be collision code). Instead, the distance from a grounded imagined
  position to its predicted floor line (static table) is reported as a contact residual.
- **Targets:** only break events are predicted. A broken target stays broken and targets-left is derived, so live flags
  are monotone as the task contract requires. Static target positions come from the reset reply; the moving target
  comes from E(t).
- **Moving geometry** comes from E(t). Every imagined state's segment features therefore match the clock exactly.
- **Projectiles** are neither input nor predicted in m7u1. Rising-point goals do not depend on them; their only effect
  on Mario is through targets they break, which is second order here.
  - Later stages add them with the v3 sticky-slot rule as bookkeeping: a predicted spawn takes the lowest free slot
    (`rl/m7n_obs.py`), and a slot keeps its identity until a predicted despawn.

### 4.5 Rollout step (per member, per candidate)

x = F(Z_τ, a_τ). The discrete heads are decoded by masked argmax in the order H1 → H2 → H3 → H4 → H5. H7 / H8 fire at
p > 0.5; a predicted fall freezes the rollout. H6 is decoded conditioned on the chosen values.
Z_{τ+1} = bookkeeping(Z_τ, predictions, a_τ) with E(clock + 1). Members roll independently; states are never averaged.
The same bookkeeping, applied to the recorded sequence, gives the start state of every rollout, prefix included.

## 5. Planner, controls and model error (items 3 and 4)

### 5.1 Planner P (no learned parameters)

- **When and what:** every 4 ticks, N = 64 candidate plans of H = 64 words.
- **Candidates:**
  - 0 = the current plan shifted by 4 ticks and refilled with fresh segments;
  - 1-15 = candidate 0 with one segment resampled;
  - 16-63 = fresh plans.
- **Segments** are uniform over the M7r option space (stick 9 × button 8 × tap / hold × length {1, 2, 4, 8, 16, 32}),
  expanded by `rl/m7r_commit.py` `tick_word`.
- **Cost per member m:** C_m = min over τ ≤ min(H, remaining budget) of [max(|x̂ − x*|, |ŷ − y*|) / 150 +
  1 · (not airborne) + 0.1 · τ / H], or 10 if a fall is predicted first.
- **Choice:** score = mean_m C_m + 1.0 · std_m C_m; argmin, ties to the lowest index. Its first 4 words are
  submitted, one native tick each.
- **Randomness:** the candidate stream is drawn from a Python generator keyed by (seed, trial, decision index), so
  every arm draws the same stream.

### 5.2 Controls

| arm | machinery | choice | what the comparison with P isolates |
| --- | --- | --- | --- |
| **RC** | identical generator, stream, candidate construction and 4-word execution cadence | always candidate 0; **no model is evaluated** | the effect of choosing and switching among candidates **by learned predictions**, with the proposal distribution and execution fixed. RC's executed stream is a continuous flow of full random segments. By construction this is also the behaviour policy that produced the training data and the goals (unit test: collection words equal RC regenerated offline from its seed). RC therefore measures each goal's chance from its exact start |
| **S** | identical to P, including the trained ensemble | P's rule, commanded π(g) = the goal (k + 20) mod 40 in registered order, scored on g | the effect of **the command itself**, with learned-model-driven switching and "energy" held fixed. A model that makes the planner jump more whatever the goal cannot pass |

Not chosen: a uniformly random candidate index. It chops executed segments after 4 ticks, which shifts the behaviour
away from the training distribution and confounds the comparison with a distribution change.

### 5.3 Model error and support

- **Ground truth.** On every executed tick, the ensemble-mean prediction for the submitted word is compared with the
  native reply, and every 4-word block open-loop from its decision state.
- **Disagreement** enters **only** the planner score (the std term). It never labels, filters or re-scores realized
  behaviour. There is no state-feature support metric (the M7t lesson). A rare purposeful trajectory that the ensemble
  predicts and native confirms is simply correct.
- **Attribution of each failed P trial** (forward passes on the frozen model, after the trial):
  - **MODEL:** from some decision, rolling the words actually executed through the model predicts a reach;
  - **PLAN:** otherwise.
- **Witness test** (forward passes only): does the ensemble (2 of 3 members) predict that the goal's recorded
  continuation reaches it from the same start?
- **Calibration** (reported): AUROC of the std term for realized block error > 150 units.

## 6. Gate `m7u1`, revision 2 (items 4, 5 and 7)

### 6.1 The one capability, and the scope

**Capability: composition.** Learned one-tick predictions, searched by a fixed planner, must produce a timed
multi-move aerial manoeuvre that reaches a commanded **rising airborne point about 64 ticks away** from a native
state, where the behaviour distribution rarely does. Jump, double jump near the apex, up-B, drift: this is what a
wall-top landing needs, and every later stage needs it. Nothing else in the approach matters if it fails.

**Scope: a diagnostic after the agent's own recorded prefix.** It is **not** policy-controlled reach from tick 0.
- **Every trial** is a fresh process with a non-consuming tick-0 reset. The held-out behaviour episode's own words
  0 … t−1 are submitted one per native tick (the M7h recorded-prefix mechanism), and then the arm controls.
- **Prefix ticks** are native ticks: itemised in the ledger (§6.4) and recorded as canonical words from tick 0. Exact
  replays resubmit prefix + controlled words from tick 0.
- **Prefixes come only from this run's own RC episodes**, never from human recordings, the TAS or fixtures.

**Why it must precede normal-start evaluation:**
- Each goal has an exact feasibility witness: the recorded continuation reaches it in 64 ticks from the identical
  state. A miss is a control failure, not an infeasible goal.
- P, RC and S face the identical native state, so the comparison is paired per goal.
- From tick 0, every episode starts in one identical state, so tail goals from there are few and alike. Normal-start
  control also mixes "cannot control locally" with "drives itself into states it cannot control". A null there could
  not be read.
- If control fails at feasible, paired starts, it cannot succeed from tick 0. So this is the cheapest falsifier of the
  whole approach.

### 6.2 Data and goals (one seed)

- **Collection:** 92 RC episodes (horizon 3,600; falls end early). 80 train the model; 12, chosen by sha256 of the
  episode id, are held out.
- **Candidate starts:** (e, t) in held-out episodes with t ∈ [60, 600], ticks t … t+64 live, and t+64 not the
  fatal-fall tick.
- **Goal g** = the recorded state at t+64. It must be airborne with y* − y_t ≥ 300, and the start must not already
  satisfy it.
- **Pooled chance q:** among training-split pairs (t', 64) with the same start ground/air, the fraction ending airborne
  with a displacement within ±150 per axis of g's. Keep q ≤ 0.02.
- **Selection:** 40 goals by ascending sha256("m7u1|goal|e|t"), at most 4 per episode, starts ≥ 32 ticks apart.
  - If fewer than 40 qualify, fill by the next-lowest q (recorded).
  - If fewer than 30 rising airborne candidates exist at all, the run is **incomplete**.
- Goals and π are frozen before training.

### 6.3 Trials

- **Budget:** B = 96 controlled ticks.
- **Success** = the first valid reach: |x − x*| ≤ 150 ∧ |y − y*| ≤ 150 ∧ airborne ∧ live ∧ not the fatal-fall tick
  (M7s semantics). It ends the trial as a Python truncation.
- **Start check:** the native state at tick t must equal the held-out record in every stored field, or the run is
  invalid.
- **Arms:** P, RC and S each play all 40 goals, with trials run concurrently across 5 workers.

### 6.4 Native budget and hard caps

| phase | native ticks (cap) |
| --- | ---: |
| P1 identity: the two shortest pinned Track 1 artifacts through the m7u stack | 5,921 |
| collection 92 × 3,600 | 331,200 |
| storage check: 1 training episode replayed, stored rows equal re-captured | 3,600 |
| evaluation prefixes 40 × 3 × ≤ 600 | 72,000 |
| evaluation controlled ticks 40 × 3 × 96 | 11,520 |
| success replays (≤ 6 P + 2 RC + 2 S) × 696 | 6,960 |
| **total** | **431,201** |

**Wall-time cap: 60 min from launch to the decision record**, per phase:

| phase | cap |
| --- | ---: |
| preflight + P1 | 3 min |
| collection | 10 min |
| storage check | 2 min |
| featurisation + training | 15 min |
| goals + evaluation | 25 min |
| replays + analysis | 5 min |

- Main-process private memory ≤ 3 GB.
- Any cap reached: **INCOMPLETE**, stop, report. No extension, retry or rerun without a new decision.
- The verified D: increment for `runs/m7u` follows the decision record, outside the cap.

### 6.5 Rule `m7u1_control_rule_v2` (n = 40, one seed)

Paired counts:
- b_R = #(P ∧ ¬RC), c_R = #(¬P ∧ RC), so n_P − n_RC = b_R − c_R;
- b_S, c_S likewise against S.

| outcome | condition |
| --- | --- |
| invalid / incomplete | any integrity failure (§6.6) or cap |
| **PASS** | n_P ≥ 10 ∧ b_R − c_R ≥ 8 ∧ b_S − c_S ≥ 6 |
| **NULL** | b_R − c_R ≤ 2 ∨ b_S − c_S ≤ 0 |
| INCONCLUSIVE | otherwise; the record names the blocking condition |

- PASS and NULL are disjoint.
- **No accuracy, calibration or attribution quantity enters the rule.** Prediction accuracy cannot select the
  approach.

**What a NULL distinguishes** (reported diagnostics; M = share of P failures attributed MODEL, W = share whose witness
the ensemble accepts):

| reading | condition | meaning |
| --- | --- | --- |
| rollout error | M ≥ ½ | the model predicted reaching plans that native did not follow: one-step predictions do not compose over ≤ 64 ticks at this data, capacity and training |
| search | M < ½, W ≥ ½ | the model accepts known-feasible continuations, but 64 random-segment candidates with 4-tick replanning did not find or keep them |
| false negatives | M < ½, W < ½ | the model rejects known-feasible continuations |
| undirected | b_S − c_S ≤ 0 with b_R − c_R ≥ 3 | the learned model changes behaviour, but not toward the command |

**What stays unresolved after any null:**
- data volume vs capacity vs one-step-only training vs H / N;
- seed variance (one seed);
- other goal families;
- normal starts.

A NULL stops this configuration, and any change needs a new decision. An INCONCLUSIVE means revise, not rerun.

### 6.6 Integrity

The run is invalid unless all of these hold:
- P1 identity;
- the storage check;
- the exogenous-track check;
- per-trial start-state identity;
- RC ≡ behaviour (offline regeneration);
- parameter digests unchanged through evaluation;
- every replayed success exact: native action digest, per-tick positions and first-reach tick, from tick 0;
- the ledger within caps;
- no BattleShip process left;
- outputs under Git-ignored `runs/m7u`;
- preflight coverage over the D: base and **every** increment (not `m7s_gate`'s stale list).

No native RNG is inspected; seeds are Python-side only.

## 7. Computational accounting and the offline benchmark (item 6)

**Per-transition cost of the §4 model** (matrix multiplies only, vocabularies at their caps):
- trunk 356·256 + 256·256 = 156,672 MACs;
- heads: H1 40,960, H2 6,528, H3 35,840, H4 17,408, H5 5,984, H6 19,200, H7 / H8 2,816 MACs;
- total **285,408 MACs ≈ 0.571 MFLOP forward**.

Featurisation adds about 10³ FLOP per transition, but its real cost is framework overhead, so it is measured, not
counted.

| quantity | revision 1 | revision 2 |
| --- | --- | --- |
| transitions per decision | 5 × 128 × 64 = **40,960** | 3 × 64 × 64 = **12,288** |
| transitions per controlled native tick (replan every 4) | 10,240 | 3,072 |
| forward FLOP per decision | ≈ 15.5 G (≈ 0.38 MFLOP model) | **≈ 7.0 G** |
| planning decisions in the gate (maximum) | 3 × 60 × 2 × 192 / 4 = 17,280 | 40 × 2 × 96 / 4 = **1,920** |
| planning FLOP in the gate | ≈ 268 T | **≈ 13.5 T** |
| training FLOP (forward + backward ≈ 3 × forward) | not stated | 3 × 1,024 × 1.71 MFLOP ≈ **5.3 GFLOP per step**; × 6,000 ≈ **31.6 T** |

FLOP counts do not give wall time on this CPU: small rollout batches, masking and featurisation make overhead
dominate. Revision 1's "~40 min evaluation" was unfounded.

**Benchmark `m7u_bench_v1`** (before registration; zero native ticks; no training on data; ≤ 20 min):
- **Model:** the pinned architecture with seeded random weights. Throughput does not depend on the weight values.
- **Inputs:** 1,000 real replies read (not replayed) from existing captures (`runs/m7q/_equiv/input_all`), plus the
  stage line table from their reset reply.
- **Measures,** on 6 threads, each after 20 warm-up iterations:
  1. planner decision latency (generation, featurisation, E × N × H rollouts, scoring): median and p95 over 200
     decisions, at concurrency 1 and batched 5;
  2. featurisation-only latency;
  3. training step time at batch 1,024 × E = 3 on cached-input shapes, median over 200 steps;
  4. peak private memory;
  5. featurisation equivalence against `rl/m7q_obs.py`, max |Δ| ≤ 1e-5 (a correctness test in the same run).
- **Projections:**
  - planning = p95 batched latency × 1,920 / 5;
  - training = median step × S.
- **Pinned adjustments** (the only permitted ones):
  - S = the largest of {6,000, 4,500, 3,000} whose projection is ≤ 720 s;
  - N = the largest of {64, 32} whose projection is ≤ 720 s;
  - if nothing fits, the gate is not proposed for launch and the benchmark is reported.
- **Never changed by the benchmark:** goals, thresholds, E, H, the data budget, the caps.
- The benchmark JSON (Git-ignored, under `logs/`) enters the registration record.

## 8. What a result establishes, and the next decision

**A PASS establishes, on one seed:**
- a learned one-step model, trained on ≤ 288,000 of the agent's own behaviour ticks and searched by a fixed planner;
- reached rare rising airborne points 64 ticks away, from own-prefix native states;
- more often than the same machinery choosing without predictions, and more often than the same planner commanded
  elsewhere;
- with exact replays.

**It does not establish:**
- reach from a normal tick-0 start, or replication across seeds;
- ground or longer goals;
- frontier expansion, a crossing, targets, a clear or speed;
- superiority over B or PPO.

**Next decision after a PASS:** a stage-1b test (separately designed and authorised).
- **Normal starts:** from tick 0 with no prefix, P / RC / S pursue rising goals defined relative to their own current
  state.
- **Replication:** on new seeds.

**After a NULL:** stop, with the §6.5 reading recorded; B or any revision is a new decision.

## 9. Beyond the gate (hypotheses; none tested by m7u1)

| stage | mechanism | hypothesis |
| --- | --- | --- |
| 1b | normal-start local control and replication | H1': m7u1's composition holds when the controller chooses its own states |
| 2 | iterated rounds from tick 0 with a generic novelty objective (inverse visit count of cell × contact over own data) plus ensemble optimism; each round retrains the model; projectiles added (§4.4) | H2: the frontier reaches the wall top and the left side without a route term. Specific risk: landings on a line never touched are mispredicted until data arrives |
| 3 | predicted target breaks within H + a learned terminal value (TD on reward v2 over planner data); order emerges from the value | H3 |
| 4 | time cost; distilling the planner into a policy; final frame polish in M8 on native words | H4 |
| other characters | same code; per-character vocabularies and tables; models retrained from scratch (M10) | untested |

## 10. Implementation outline and decision requested

Files (all new; no native change; nothing existing edited except additive hooks if needed):

| file | contents |
| --- | --- |
| `rl/m7u_state.py` | fields, bookkeeping, E(t) table and check, torch featurisation |
| `rl/m7u_model.py` | heads, masks, losses, training |
| `rl/m7u_planner.py` | generator, candidates, scoring; torch / numpy only |
| `rl/m7u_worker.py` | recorded prefix, state recorder, reach probe |
| `rl/m7u_goals.py` | goal selection |
| `rl/m7u_gate.py` | preflight, phases, ledger, caps, attribution, rule |
| `rl/tools/m7u_bench.py` | the benchmark |
| `rl/m7u_tests.py` | tests (below) |

Tests:
- RC ≡ behaviour;
- featurisation equivalence;
- bookkeeping identity on recorded sequences;
- mask construction;
- rule self-test;
- planner import isolation;
- the exogenous-track check on existing captures.

**Decision requested — approve, amend or decline, in order:**
1. the zero-native-tick preparation (implementation, unit tests, `m7u_bench_v1`, the read-only track check);
2. then, on the benchmark's projections, gate `m7u1` (≤ 431,201 native ticks, 60 min hard cap).

Neither is authorised by this document.
