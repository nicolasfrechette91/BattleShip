# Temporal-control design for Mario Break the Targets (2026-09-28, revision 3)

Status: **approved design (user decisions of 2026-09-28, section 9); the gate has not run.** The Python implementation
and the `runs/` backup are recorded separately in
[`rl_commit_m7r_implementation.md`](rl_commit_m7r_implementation.md). No game process ran for this design; native RNG
was not touched. Human crossings, the TAS and the geo4 crossing checkpoint were not used for any design parameter;
they stay validation evidence only.

Revision 3 (user decisions on section 9 of revision 2): C and its control approved, M7n v3 a historical baseline only;
the contract details approved with explicit equivalence tests; discounting stated with its limit; native-tick
accounting with decision and optimizer-exposure logging; evaluation reduced to 20 + 30 + 10 episodes per run with the
total-tick arithmetic; ST1 and PR1 decisive, RE1 supporting, exact formulas and denominators; the backup to D: made a
prerequisite. Sections 4-9 are rewritten; sections 0-3 are revision 2 apart from section 3.1's approval note.

Revision 2 (user review of revision 1): the button-on-first-tick-only contract is replaced by one with explicit tap and
hold modes (section 3); measured facts are separated from hypotheses and two over-claims are withdrawn (sections 1-2);
the seed-0 futility gate is removed (section 6); the 4.5 h pilot and 12 h campaign are replaced by a short
control-learning gate (section 5); semi-Markov discounting and native-tick accounting are specified (section 4); an
independently verified backup of `runs/` becomes a launch prerequisite (section 7).

Sources: `../guide.md` (outside the repository, last revised 2026-09-22; its next-steps list predates Phase K),
`CLAUDE.md`, [`rl_handoff_2026-09-28.md`](rl_handoff_2026-09-28.md),
[`rl_mechanics_observation_audit_2026-09-28.md`](rl_mechanics_observation_audit_2026-09-28.md) (authoritative for
mechanics; "audit §" below), [`rl_observation_v4_proposal_2026-09-28.md`](rl_observation_v4_proposal_2026-09-28.md),
[`rl_observation_v4_m7q_implementation.md`](rl_observation_v4_m7q_implementation.md), the M7n / M7o / M7p records,
[`rl_learning_setup_review_2026-09-27.md`](rl_learning_setup_review_2026-09-27.md) ("review §"),
[`rl_action_hold_probe_2026-09-27.md`](rl_action_hold_probe_2026-09-27.md), and the code (`rl/battleship_client.py`,
`rl/btt_learning.py`, `rl/m7_trainer.py`, `rl/m7n_obs.py`, `rl/m7q_obs.py`, `rl/configs/m7n/*.toml`).

## 0. Verified state

| item | state |
| --- | --- |
| parent | `HEAD = origin/main = 48ea181` ("add mechanics-aware Mario BTT observation v4"), clean apart from this untracked report. M7q is committed and pushed; its report's "HEAD ee96fe2, uncommitted" is historical |
| `decomp` | `e4f06348` on `rl-main` = `origin/rl-main` (the user's fork), containing the M7q PORT-only edit |
| `libultraship` / `torch` | `805f1950` on `m6/raphnet-bypass` = origin; `3aa9c97` detached = `origin/agent/issue-batch`; unchanged |
| selected configuration | `btt_policy_obs_v3_entities` + `btt_reward_v2` + Track 1 `btt_s9_b8_v1` + PPO of `rl/configs/m7n/*.toml`. v4 `btt_policy_obs_v4_input` is opt-in and **has never been trained** |
| `runs/` | Git-ignored (`.gitignore:120`); **377,359 files, 16.97 GB**, plus 46,773 directory junctions into `build-us/Release/.tcc` that are runtime links, not evidence. The M7p manifest re-hashed today: 3,233 / 3,233 present, 0 mismatches, 176.0 MB. That proves the **single local copy** is intact; it is **not a backup**. No other copy was found on C: or D: |
| disks | C: = disk 0 (480 GB SATA SSD, holds the repository); D: = disk 1 (2 TB SATA HDD, 1.78 TB free), a separate physical device in the same machine |
| Python | SB3 2.9.0, Gymnasium 1.3.0, torch 2.14.0; `sb3-contrib` not installed |
| native buttons | `A 0x8000, B 0x4000, Z 0x2000, L 0x0020, R 0x0010, C-up 0x0008, C-left 0x0002` (`rl/battleship_client.py`); a native word carries at most one of them; R is folded to R+A+Z by the game, not by Python (audit §1) |

## 1. Why per-tick control struggles: facts first, hypotheses separately

### 1.1 Native facts (source-audited, audit §1-§3, §7)

- One Track 1 action = one controller word = one native tick. A **press** is a button present now and absent on the
  previous tick; holding the button again is not a press. R becomes R+A+Z before edge detection.
- A **stick tap** is entry into `|v| >= 20` (including a sign reversal); jump / double jump need `stick_y >= 53` with the
  tap at most 3 ticks old, or a fresh C press; the game forces `tap_stick_y = 254` when a jump, fast fall or
  drop-through fires, so holding up never produces a second jump. Fast fall needs a fresh down tap while falling.
- **Locks**: aerials, fireball, up-B, tornado and every lagged landing have `proc_interrupt = NULL` (no new jump,
  attack or special); helpless (after up-B) allows steering, fast fall and drop-through only; hitlag freezes everything
  and a press on the hit tick itself is lost. During aerials, the aerial fireball and helpless the stick still drifts
  the fighter (Mario: air velocity changes by up to 2 units/tick each tick at full deflection, capped at 30).
- **Holds that matter**: shield needs Z *held*; a C jump is a short hop if C is released within the first 3 squat
  frames and a full hop if held; a stick jump's height is the maximum stick y held over the squat; Kirby and
  Jigglypuff take their 3rd-5th jumps from a *held* stick-up or *held* C (audit §2.2).
- What a word in a lock still does: drift, and it becomes the previous word against which the first free tick's press
  edge and stick tap are computed.

### 1.2 Measured on the selected v3 policies (review §2, final stochastic episodes, 100 per seed)

- Action changes on 75-81 % of ticks; modal joint action probability 0.41-0.54 (two rebuilt trajectories); median run
  length 1 tick.
- 63 % of inter-break gaps exceed the 167-tick GAE horizon; on two rebuilt trajectories 62-67 % of a break's value
  arrives as TD surprise (bounded evidence, two trajectories).
- Zero left-side events in every v3 final; the best tick-0 result on record is 5.52-5.59 targets per episode.

### 1.3 Illustrative only: eight selected observation-v1 traces (`runs/m7q/_equiv/input_all`)

These are pinned M7d / M7e artifacts chosen as best, fall or double-jump examples, from **observation-v1** policies,
n = 8. They illustrate the mechanisms; they are not estimates for v3 or v4 policies. Definitions: a tick is locked when
the status its input meets (the previous reply's) is in class `attack_air`, `special_n/hi/lw`, `landing_lag`,
`helpless`, `air_lock`, `attack_ground` or `roll` (table v2), or hitlag was running; drift coherence is
|mean sign(stick_x)| over airborne segments of at least 40 ticks (1.0 = one direction held). The script stayed in the
session scratchpad.

| episodes | locked ticks | press edges made while locked | drift coherence | free ticks holding a button without an edge |
| --- | --- | --- | --- | --- |
| 5 stochastic | 72-94 % | 70-93 % (tornado B presses, the one lock where they act: 0-64 of 960-2,487) | 0.07-0.34 | 92-377 |
| 2 deterministic | 16 % / 10 % | 41 % / 26 % of only 29 / 74 edges | 0.75 / 0.15 | 2,804 / 3,185 |
| 1 uniform random | 76 % | 76 % | 0.07 | 115 |

### 1.4 One checkpoint, seven flights (M7p geo4 seed 1 final)

In all seven L1 flights the double jump fired on the first actionable tick after the first-jump move's lock; its
timing was therefore set by the move thrown 1-10 ticks after takeoff (early aerial about 39 ticks of lock, fireball
about 45), which set the up-B start height (at least 1,639 needed; the up-B rise is a fixed +1,361). In the landing
episode that choice preceded the first reward it led to (target 6) by about 690 ticks, where the GAE weight is
(γλ)^690 ≈ 0.016. Two landings in 100 episodes of one checkpoint; not a rate for any other policy.

### 1.5 What v4 changes, and hypotheses that are not yet evidence

v4 **exposes** the input state: held bits (is the next press an edge), tap counters with the game's forced resets,
animation frame and speed with the `helpless` / `landing_lag` / `air_lock` classes (lock progress, lagged landing),
Z-cancel age. The previous stick and buttons are now part of every observation, so even a memoryless per-tick policy
can condition on its own last word. That is a fact about the contract. **How a v4 policy will behave is unknown**:
v4 has never been trained. The following are hypotheses, each mapped to the gate measurement that tests it
(section 5):

| id | hypothesis | tested by |
| --- | --- | --- |
| H1 | a per-tick v4 policy keeps placing many presses in locks and holding buttons into free ticks, because a lock-period button choice has almost no consequence and so almost no gradient | PR1 / PR2 on arm F |
| H2 | per-tick sampling limits sustained drift even though v4 shows the previous stick | ST1 on F vs C |
| H3 | decisions aligned with native input-effect boundaries produce more accepted presses at lock exits | PR1, PR3 on C vs F |
| H4 | committed manoeuvres widen the states reached from tick 0 early in training | RE1, RE2 on C vs F |
| H5 | better control raises the discovery rate of left-side events | **not** testable by the gate; only by a later campaign |

## 2. Approaches compared (revised)

Two revision-1 claims are withdrawn:

- **"Recurrence leaves exploration unchanged" was too strong.** At initialisation a recurrent policy, like an MLP,
  samples each tick given its inputs, so early exploration is not coherent by construction. After learning, its
  sampled action at tick t changes its hidden state and so its later actions: one sampled deviation can propagate as a
  coherent multi-tick change, a known mechanism for learned, temporally extended exploration. Recurrence *can*
  improve exploration; whether it does here is unmeasured. (Under v4 an MLP has the same feedback path with one tick
  of memory, through the observed previous word.)
- **The hold-k probe does not count against learned persistence.** It held *uniform random* words for fixed k ticks,
  buttons included (so a held A gave one aerial per hold and held buttons blocked edges), without regard to lock
  boundaries and without learning. It shows only that unlearned correlated inputs did not reach the over-ledge region
  from tick 0; its own report says it says nothing about a learned policy.

| | A. recurrent PPO (per tick) | B. learned duration (no events) | **C. commitment with tap / hold and native-event decision points** | D. hierarchical goal-conditioned |
| --- | --- | --- | --- | --- |
| holds, releases, edges | learnable per tick | learnable if the contract has tap and hold | explicit per decision (section 3) | delegated to a motor layer |
| steering in locks | sampled every tick | held stick for the chosen length | held stick until the chosen length or an input-effect boundary | delegated |
| credit assignment | per-tick horizons; recurrent critic harder to fit | fewer decisions per game second | fewer decisions, placed where the effective input set changes | dense worker signal; short manager horizon |
| exploration from tick 0 | not coherent at init; can learn coherent exploration | coherent at init; must predict lock ends | coherent at init; lock ends are guaranteed decision points | directed, if goals come from the agent's own reached states |
| routes and target order | learned | learned | learned (events are generic state changes) | learned, if goals are never waypoints |
| cross-character | generic | generic | generic; hold mode covers multi-jump holds | best |
| cost / attribution | new dependency or custom LSTM PPO; one variable | small; one variable | Python only; **reduces exactly to Track 1 per-tick PPO at duration 1**; one variable | two learners, a goal reward and an archive: several variables |

**Choice: C (primary), F = v4 per-tick PPO (control).** C is chosen because it expresses the native edge / hold /
tap rules directly, it reduces exactly to the control when every duration is 1 (so the comparison isolates the
decision process), and it needs no native change. The advantage of event alignment over B is hypothesis H3, not
evidence; B stays a later ablation of C, A a later composition (a recurrent policy over C's decisions) if C's decision
logs show intent aliasing, and D the later layer if C improves control without improving reach.

## 3. Action contract `btt_commit_s9_b8_m2_d6_v1` (proposed id)

### 3.1 Definition (approved 2026-09-28, decision 2)

Policy action `MultiDiscrete([9, 8, 2, 6])`:

| component | values |
| --- | --- |
| stick `s` | the Track 1 stick table, unchanged (neutral and 8 directions at magnitude 80) |
| button `b` | the Track 1 button table, unchanged: none, A, B, C-up, C-left, L, R, Z. **R stays a Track 1 button; no combined A+Z action**; the game's own R fold produces A+Z |
| mode `m` | `tap`: `b` on the option's first tick, none on its later ticks. `hold`: `b` on every tick of the option |
| max length `d` | {1, 2, 4, 8, 16, 32} ticks (binary steps covering Mario's 3-49-tick locks, audit §7.1) |

Per tick i = 1..τ of an option the executor submits one Track 1 action to the existing `Track1PolicyWrapper` path:
stick `s` on every tick; button `b` on tick 1 and, in hold mode, on every later tick. The option ends after tick i when
`i = d`; or, for `i >= 2`, when tick i's native reply shows an **input-effect boundary**: the table-v2 class of
`fighter_status_id` changed, `ground_air_state` changed, the fighter is airborne and `air_velocity_y` went from > 0 to
<= 0 (apex; fast fall becomes possible), `hitlag_tics` went from > 0 to 0, or `targets_remaining` decreased; or when the
episode ends; or, in training only, when the environment's rollout tick quota is reached (section 4). Tick-1 changes
are the option's own intended effect and never end it. **Ending an option never changes the controller word by
itself**: the next decision's first tick follows immediately, with no gap, no hidden tick and no inserted release.

- **Duration 1 is Track 1 exactly.** With `d = 1` both modes emit the single word `(TRACK1_BUTTON_TABLE[b],
  TRACK1_STICK_TABLE[s])` through the same wrapper, and the option returns that tick's observation and reward; any
  Track 1 sequence is a sequence of `d = 1` decisions, and the semi-Markov learner with every τ = 1 is the per-tick
  learner (section 4). The mode head is inert at `d = 1` (the two modes give the same word; recorded, not merged).
- **Holds are kept**: shield, a full C hop, R held, a held C or stick-up for later multi-jump characters, all as one
  decision. **Releases are explicit**: a tap releases after one tick; a hold releases when a later decision chooses
  another button or none; the maximum press rate (press, release, press) is a chain of `tap, d = 2` decisions.
- **Persistent steering**: the stick is held on every tick of the option, locks included; changing direction between
  decisions is a fresh native stick tap; choosing the same direction continues the hold.
- Nothing is masked; no Python rule decides what is actionable; boundaries are native reply fields mapped through
  the v2 class table (validated for Mario; other characters need the onboarding audit).
- **Replay truth unchanged**: `EpisodeRecordingWrapper`, below the executor, records one canonical native word per
  consumed tick; replay and verification use only those. Option metadata (decision index, `(s, b, m, d)`, realised τ,
  ending reason, first and last consumed tick) goes to a sidecar `decisions.jsonl`; an **expansion check** re-derives
  the per-tick words from the sidecar and the recorded replies and must match exactly.

### 3.2 Exact native words (canonical `buttons, stick_x, stick_y` per consumed tick)

Effects in the last column are native input processing (exact) or the cited native rule under the stated condition.

| example | decision(s) | tick: native word | native consequence |
| --- | --- | --- | --- |
| short hop, Wait | `(neutral, C-up, tap, 8)` | 1: `0x0008, 0, 0`; 2-4: `0x0000, 0, 0` | tick 1 C-up edge → jump squat; C released inside the first 3 squat frames → short hop (audit §2.2); option ends at the squat → airborne class change (tick 4 with the recorded 3-tick squat) |
| full hop, then steer | `(neutral, C-up, hold, 8)`, then `(left, none, tap, 32)` | 1-4: `0x0008, 0, 0`; 5…: `0x0000, -80, 0` | C held through the squat → full hop; the next decision releases C and drifts left until the next boundary (the apex) |
| shield held, released | `(neutral, Z, hold, 16)` twice, then `(neutral, none, tap, 8)` | 1-32: `0x2000, 0, 0`; 33…: `0x0000, 0, 0` | tick 1 Z edge with Z held → shield (needs the hold, audit §2.6); ticks 2-32 Z held, no further edge; tick 33 release → shield off after the release lag. With `tap` instead, Z is released on tick 2 |
| R on the ground | `(neutral, R, tap, 4)` | 1: `0x0010, 0, 0`; 2-4: `0x0000, 0, 0` | the game folds tick 1 to held R+A+Z (`0xA010`) with three edges → grab (Z held + A press, audit §2.5); all released on tick 2 |
| R held | `(neutral, R, hold, 4)` | 1-4: `0x0010, 0, 0` | native `button_hold = 0xA010` every tick, edges only on tick 1; A and Z stay held, so whatever the game's chains read from held Z applies natively; the contract adds nothing |
| double jump while steering | in the air, jumps left: `(left, none, tap, 32)`, then `(up-left, none, tap, 8)` | …: `0x0000, -80, 0`; next tick 1: `0x0000, -80, 80` | stick y enters the band → tap counter 1 → double jump if the status allows (audit §2.2); the game forces the counter to 254, x stays -80 (drift continues). Holding up-left since takeoff would not double-jump |
| double jump by C | `(left, C-left, tap, 8)` | 1: `0x0002, -80, 0`; 2…: `0x0000, -80, 0` | fresh C press → double jump; C released at once, so a later C press is again an edge |
| Z-cancel while drifting | in an aerial, before landing: `(left, Z, tap, 8)` | 1: `0x2000, -80, 0`; 2…: `0x0000, -80, 0` | Z edge sets the Z counter to 0 (valid only after the aerial started); lag-free landing if the landing comes within 10 ticks (audit §2.3); the landing ends the option |
| B presses at the maximum rate | `(neutral, B, tap, 2)` repeated | `0x4000, 0, 0`; `0x0000, 0, 0`; `0x4000, 0, 0`; … | one fresh B press every 2 ticks (e.g. the tornado's rise presses, audit §2.4) |
| later characters' multi-jump | Kirby / Jigglypuff, airborne: `(neutral, C-up, hold, 32)` or `(up, none, tap, 32)` | `0x0008, 0, 0` or `0x0000, 0, 80` every tick | a held C or held stick-up satisfies their 3rd-5th jump rule (audit §2.2); to be verified at onboarding |
| Track 1 identity | any `(s, b, m, 1)` | one tick: the Track 1 word of `(s, b)` | identical to Track 1 |

### 3.3 Observation and reward

Observation `btt_policy_obs_v4_input` exactly (626 values, digest `c3d461de…`), built on every tick (its sticky state
needs every reply) and returned at decision points; no option-context feature, so both arms see identical inputs.
Reward `btt_reward_v2` per tick, unchanged. No event, reward term, observation field, termination or goal refers to a
route, a region or a target order; target order and routes stay learned.

## 4. Semi-Markov discounting and native-tick accounting (approved, decisions 3-4)

Per-tick reward `r_t` (v2), `γ = 0.999` and `λ = 0.995` per native tick (the M7n values). Decision j starts at tick
`t_j` and lasts τ_j ticks.

- Decision reward: `R_j = Σ_{i=0}^{τ_j−1} γ^i r_{t_j+i}`.
- Return: `G_j = R_j + γ^{τ_j} G_{j+1} = Σ_k γ^k r_{t_j+k}`, i.e. exactly the per-tick return from tick `t_j`: a
  32-tick option is discounted as 32 ticks, not as one step, so the objective in game time is unchanged.
- TD error: `δ_j = R_j + γ^{τ_j} V(s_{j+1}) (1 − terminated_j) − V(s_j)`; a native fall is a termination (no
  bootstrap); the 3,600-tick horizon and a rollout cut are truncations, bootstrapped with `γ^{τ_j} V` of the next
  observation (SB3's time-limit handling, applied with the option's own discount).
- Advantage: `A_j = δ_j + (γλ)^{τ_j} (1 − done_j) A_{j+1}`; value target `A_j + V(s_j)`.
- **Reduction**: every τ_j = 1 gives SB3's per-tick PPO exactly (tested numerically against SB3's own buffer).

**What this does and does not do.** Converting the per-tick constants keeps the baseline's credit horizon in game time
unchanged: discount horizon 1/(1 − γ) = 1,000 ticks and GAE horizon 1/(1 − γλ) ≈ 167 ticks, as in M7n. It therefore
**does not by itself solve delayed credit across a long crossing**: a choice made about 690 ticks before the reward it
leads to still receives (γλ)^690 ≈ 0.016 of that reward through GAE, whether the ticks between were 690 per-tick
decisions or 30 options. Fewer decisions reduce the number of sampled choices along a chain (and so the variance they
add), not the tick distance the credit must travel. Any change of horizon would be a separate, separately reviewed
variable.

**Rollout accounting in native ticks (equal budgets by construction).** Both arms collect exactly 1,024 native ticks
per environment per rollout (5 environments, 5,120 ticks, as M7n). F collects 1,024 one-tick decisions. C collects as
many decisions as fit; the option that would cross the quota is ended at it (reason `rollout_boundary`, training only,
recorded in the sidecar, bootstrapped as above); an environment that has reached its quota answers further vector
steps without consuming a tick until every environment has (an `idle` reply: no native request is sent, nothing is
stored). Both arms take 10 minibatches × 10 epochs = **100 gradient steps per rollout** (C's minibatch size =
ceil(decisions / 10)). Budgets, checkpoints (every 102,400 ticks) and evaluation points are at identical native-tick
counts. **Equal native ticks are not equal decisions**: every rollout record logs, for both arms, native ticks (must be
5,120), policy decisions (total and per environment), idle replies (C), the realised option-length histogram (1..32),
`d` and mode usage, ending reasons, minibatch size, gradient steps (must be 100) and optimizer exposure (decisions ×
epochs samples, cumulative decisions). Evaluation episodes have no rollout boundary and are compared at equal episode
counts.

## 5. The short control-learning gate (approved, decisions 5-6; exploratory)

| item | value |
| --- | --- |
| arms | C (section 3) and F (v4 per-tick PPO with the M7n settings exactly). M7n v3 is a historical baseline only: not trained, not evaluated, not an arm |
| seeds | 0, 1, 2; fresh construction; normal tick-0 starts only; no warm start, prefix, curriculum, fixture, TAS or geo4 checkpoint |
| training | **307,200 native ticks per run** (60 rollouts × 5,120); 6 runs = **1,843,200 ticks**; no extension |
| evaluation | post-hoc on frozen checkpoints, fresh process per episode, tick 0, seed 12345, 5 workers + standby, spatial / entity / input / target diagnostics on, a per-tick gate trace per episode. Per run: untrained checkpoint **20 stochastic**; final checkpoint **30 stochastic + 10 deterministic** = 60 episodes; 6 runs = 360 episodes, at most 3,600 ticks each = **at most 1,296,000 ticks** |
| **total native ticks** | **1,843,200 training + ≤ 1,296,000 evaluation = ≤ 3,139,200** for the six runs |
| verification replays (separate, bounded) | before training: the live `d = 1` identity check drives the eight pinned Track 1 artifacts through C (exactly 27,521 ticks: 3,361 + 2,560 + 6 × 3,600). After evaluation: exact tick-0 replay of the first 2 final stochastic episodes per run (≤ 12 × 3,600 = 43,200) and of every discovery candidate (≤ 3,600 each, at most 20 = 72,000). Cap ≤ 142,721 ticks |
| runtime | **not claimed.** The driver records the measured wall time of every phase (each run's training, each evaluation label, each replay) and writes them to the gate record; a measured estimate is reported separately after the gate. Backup time is separate from gate runtime |
| built-in engineering checks | before training: the unit suite and the live `d = 1` identity check. During the gate: the expansion check on every C episode (training artifacts and evaluation), every rollout exactly 5,120 ticks and 100 gradient steps in both arms, no hidden tick, no leaked process, exact replays above |
| stops | an integrity failure → **invalid** (fix and rerun; no conclusion). A crashed run → **incomplete** (that run is rerun; never read as a failure). No performance-based early stop: a run is short, and a run that learns badly is judged by the rule |

### 5.1 Measures (native records only; exact definitions)

Notation for one evaluation episode: consumed ticks `t = 0..L−1`; `w_t` the native word consumed on tick t (buttons,
`x_t`, `y_t`); `R_t` the native reply after tick t and `R_{−1}` the tick-0 observe reply. From a reply: status id `σ`,
table-v2 class `κ`, `g` (`ground_air_state`, 1 airborne), hitlag `h` (`entity.fighter.hitlag_tics`), `tap` (input
diagnostic `button_tap`: the edges tick t produced), floor line `f` (spatial `fighter.floor_line_id`). A tick is
**live** when `R_{t−1}` and `R_t` both have `btt_active = 1`, `fighter_valid = 1` and a valid input object.

| measure | per-episode formula | episode included when | role |
| --- | --- | --- | --- |
| **ST1** sustained steering | airborne-input ticks `A = {t live : g(R_{t−1}) = 1}`; segments = maximal runs of consecutive ticks in A; `S` = segments of at least 40 ticks; `coh(G) = abs(Σ_{t∈G} sgn(x_t)) / abs(G)` with `sgn(0) = 0`; **ST1 = mean over G ∈ S of coh(G)** | S non-empty | decisive |
| **PR1** effective press rate | move buttons `M = {A, B, C-up, C-left, L}` (an R press is counted through its folded A bit; Z is excluded); press ticks `P = {t live : h(R_{t−1}) = 0 and tap(R_t) ∩ M ≠ ∅}`, excluding ticks whose only move bit is B while `κ(R_{t−1}) = special_lw` (tornado presses); a press is **effective** when `σ(R_t) ≠ σ(R_{t−1})`; **PR1 = effective / abs(P)** | P non-empty | decisive |
| RE1 floors reached | `abs({f(R_t) : t live, g(R_t) = 0, f ≥ 0})` | always | supporting only |
| T targets | 10 − `targets_remaining` of the last reply | always | guardrail |

What PR1 does and does not measure: it looks only at ticks carrying a **new press** of a move-starting button and asks
whether the status changed on that tick. Ticks that steer, hold, release a hold or prepare a later edge (a release tick,
a stick change that arms a tap) carry no new move press and are **never in the denominator**, so they are not
penalised. Z presses (Z-cancel timer, shield) and tornado B presses act without a status change and are excluded
rather than scored. Known limits: a press accepted a tick later (the Turn status re-injects a first-frame A / B, audit;
hitlag delivers presses after it) counts as not effective; a status change caused on the same tick by an animation end
counts as effective. PR1 is therefore a measure of *timing* of move presses, not of input usefulness in general.

### 5.2 Rule (applied once; exploratory)

Per seed s and decisive measure M ∈ {ST1, PR1}: over included episodes, `Δ_F = mean(C final) − mean(F final)` and
`Δ_U = mean(C final) − mean(C untrained)`, each with a **90 % percentile bootstrap** interval (10,000 resamples of
episodes with replacement within each group, a registered NumPy generator seed per seed and measure; Python-side only).
**M improves in seed s** when both lower bounds are above 0. A group with fewer than 5 included episodes leaves M
undefined in that seed (never counted as improved).

| # | outcome | condition |
| --- | --- | --- |
| 0 | invalid / incomplete | as in the stops row |
| 1 | **pass (discovery)** | a native-verified clear, replay-verified qualified crossing (`btt_qualified_crossing_v1`) or replay-verified left-target break in any C final evaluation episode of any seed |
| 2 | **fail: no learning** | mean T of C final ≤ mean T of C untrained in ≥ 2 seeds |
| 3 | **fail: regression** (guardrail) | mean T of C final ≤ mean T of F final − ½ in ≥ 2 seeds |
| 4 | **pass (control learned)** | at least 2 seeds in each of which **both** ST1 and PR1 improve |
| 5 | inconclusive | otherwise |

RE1 never decides; it is reported with the same intervals. A discovery in an untrained label or in F is preserved and
reported, never a pass for C. **A pass is exploratory evidence that the contract changes what is learned early; it is
not proof of long-run superiority** (geo4 led at 307,200 ticks and finished 0.6 targets behind). It makes a larger
campaign eligible for a separate decision and selects nothing.

**What the gate can establish**: that the contract executes correctly under learning (replay truth, Track 1 identity
at `d = 1`, equal native ticks, no hidden input); and whether, at an equal small budget from normal tick-0 starts, PPO
learns measurably more sustained steering and better-timed move presses with the contract than without it,
attributable to learning (vs its own untrained policy) and replicated in at least two of three seeds.

**What it cannot establish**: clears, crossings, final target counts or long-run superiority; that better control
causes discovery (H5); v4 against v3; rare-event rates (30 stochastic episodes per final); anything about other
characters or stages.

## 6. Later campaign (separate decision after the gate result, decision 9)

Not designed further here. Its standing constraints: equal native-tick budgets, interleaved seeds, joint futility only
(an arm stops early only if all seeds meet the registered futility condition and none has produced a verified clear,
crossing, left-target break or over-ledge state), a clear preserved at once without stopping other seeds, more
right-side targets never sufficient to select C, and v4 selection only from a per-tick v4 vs v3 comparison registered
for that campaign. Until then v3 + reward v2 stays selected and v4 opt-in.

## 7. Backup prerequisite (decision 7)

- **Scope**: every regular file under `runs/`; the 46,773 runtime junctions into `build-us/Release/.tcc` (and any
  other reparse point) are neither followed nor copied, only listed.
- **Destination**: `D:\BattleShip_runs_backup\2026-09-28\` on the separate physical disk 1: `runs\` (the copy),
  `manifest.tsv.gz` (relative path, size, mtime, SHA-256 of every source file), `junctions.tsv.gz`, and
  `verification.json` (PASS / FAIL).
- **Verification**: the source inventory is walked again after the copy; every source file is re-hashed from the
  source, every backup file is hashed by reading D:, and the three (copy-time manifest, source re-hash, backup hash)
  must agree for every path, with identical path sets, sizes and byte totals and no extra file in the backup. The
  source is only read.
- **Enforcement**: the gate driver refuses to launch unless `verification.json` says PASS and every regular file under
  `runs/` at launch time appears in its manifest with the same size and mtime. New outputs are backed up the same way
  (the tool is incremental) before any later run.
- **Limit**: D: is in the same machine. The copy protects against the loss of disk 0, **not against the loss of the
  whole machine**; an off-machine copy can follow later.

## 8. Rejection criteria for the primary

C is rejected (not retried as is) on gate outcome 2 or 3. Outcome 5 means revise, not rerun: a new contract version,
B or A would need its own review. An invalid or incomplete gate is fixed and rerun; it rejects nothing.

## 9. Decisions recorded (2026-09-28)

1. C `btt_commit_s9_b8_m2_d6_v1` is the primary approach and v4 per-tick PPO its control; M7n v3 is a historical
   baseline, not a third trained arm.
2. Tap and hold modes, durations `{1, 2, 4, 8, 16, 32}`, the five event boundaries with tick-1 suppression; tests must
   show that duration 1 reproduces every Track 1 native controller word and that an option boundary never inserts a
   release or other hidden input; R is kept, no A+Z action.
3. Per-tick `γ = 0.999`, `λ = 0.995` applied as `γ^τ` and `(γλ)^τ`; stated to preserve the baseline credit horizon and
   not to solve delayed credit across a long crossing (section 4).
4. 1,024 native ticks per environment per rollout in both arms, C's option cut at the training quota, 100 gradient
   steps per rollout in both arms, with decision counts, option lengths and optimizer exposure logged.
5. 3 seeds × 307,200 training ticks per arm; evaluation 20 untrained + 30 final stochastic + 10 final deterministic
   per run; total ≤ 3,139,200 native ticks; runtime measured, not claimed; backup time separate.
6. ST1 and PR1 decisive (C must improve over its trained per-tick control and its own untrained behaviour in at least
   two seeds; implemented as both measures in the same seed), half-target regression guardrail, RE1 supporting only,
   discovery in any seed passes, 90 % bootstrap, the gate described as exploratory.
7. A verified independent backup of all regular files under `runs/` to D: before any future game run (section 7).
8. The Python-only, opt-in implementation is authorised; no native or decomp change; only Python unit tests and
   read-only checks of existing records; no game launch, no gate.
9. Any larger campaign is a separate decision after the gate result is reviewed.
