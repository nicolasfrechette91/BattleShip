# M9: robustifying the discovered clear into a tick-0 policy (proposal, 2026-10-03)

**Status: design only.** No native process was launched and no native tick was consumed. Nothing was trained,
implemented, committed, pushed or branched. No tracked file and no `runs/` tree was changed. The only computations were
read-only scratch scripts in the session scratchpad, outside the repository (appendix A), over preserved
`runs/m8_rd_rd4/` and `runs/m7n/` records. They imported no repository module. This document is the only file added,
and nothing in it is authorised.

| item | state |
| --- | --- |
| checkout | `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, branch `main`, HEAD = origin/main = `2cb3e70` (remote confirmed by `git ls-remote`), working tree clean |
| external guide | `Smash_pc_port/guide.md` (outside the repository; revised 2026-10-02, M8 re-scoped) |
| executable the discovered routes are verified on | `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee` with rd1's frozen runtime configuration (`BattleShip.cfg.json` `1b29d91b…`) |
| read | `CLAUDE.md`; the guide; `rl_handoff_2026-09-28.md`; `rl_mechanics_observation_audit_2026-09-28.md`; M7h results; M7m design, results and W2 diagnosis; M7n prefix feasibility and sweeps addendum (M7n's consolidation records); M7p results; M7r results (for v4's only training use); every `rl_m8_rd*` document, ending with `rl_m8_rd4_results_2026-10-03.md`; `replay/README.md` and `replay/replay_task.py` (for section 7) |

**Naming.** The guide's milestone table still calls M9 "deterministic replay visualization" and describes this work as
"M8 phase 2 — robustification". This document follows your request and calls robustification **M9**. The guide is not
edited (open question 1).

## Short answer

1. **Method: the backward algorithm (Go-Explore's robustification), adapted to the project's no-save-state contract.**
   - Train PPO from start states late on the agent's own verified clear, replayed as exact prefixes in fresh processes.
   - Move the start point back in 20-tick strips, but only when the policy succeeds from the newly exposed strip.
   - Continue until the start is tick 0.
   - This is the right tool here: every earlier consolidation attempt failed for a reason this method addresses
     directly (section 2.3). It is also the method with the strongest published record for turning a found trajectory
     into a policy.
   - It is **not** a sure thing. The published runs needed billions of frames and several demonstrations, and this
     project has one crossing lineage and replay-bound throughput (section 2.4).
2. **What the agent discovered is narrower than "two clears".**
   - The archive holds **one trunk with five endings**. All five clear sequences share their first 2,213 ticks or more.
     Two are replay-verified; three are registered clear candidates that were never replayed.
   - **Every one of the 4,932 left-of-wall cells that came over the wall descends from the same lineage**, branching
     at or after tick 1,631 (mid up-B). The other 16 left-of-wall cells are off-stage falls under the stage.
   - The other agent-generated crossings (M7p seed 1, M7h seed 1) cannot finish a clear within the 3,600-tick horizon.
   - So M9 starts single-lineage for the crossing, the condition under which Go-Explore's backward algorithm was least
     reliable (40 % of runs). This is the main risk.
3. **Baseline: observation v3 + reward v2, a fresh policy, PPO settings unchanged.**
   - The records do not show v4 doing better than v3: the two were never compared.
   - v4 has one M9-specific argument: the input-edge state at the prefix handover. That is registered as a measured
     diagnostic and as the first fallback, not as the default (section 2.5).
4. **Success is defined now, before any training** (section 4).
   - **Claim:** from the ordinary tick-0 reset, with no prefix and no idle words, the frozen policy clears at least
     50 of 100 stochastic episodes. Every counted clear is verified by exact replay.
   - **Robustness test:** it also clears at least 50 of 100 episodes under **sticky actions at p = 0.25 per tick**. The
     perturbation uses Python-side keyed draws and the submitted word is recorded, so native RNG is never touched. On
     the same draws, the agent's own route replayed as an open-loop tape must do at least 25 clears worse.
   - **Secondary, reported only:** random idle offsets of 0–299 ticks, one full period of the moving platform.
5. **Gate M9-g1** (section 5).
   - **Run:** one fresh run, 60 minutes of training wall time. Caps: 15,000,000 native training ticks and 3,072,000
     policy transitions. At most 10 BattleShip processes, using rd4's memory caps.
   - **Start states:** a new staging pool, in which processes are booted and prefix-replayed while other episodes run.
   - **Measure:** the **reliable reach** R. This is the earliest *landing state* of the trunk from which the frozen
     final policy clears at least 10 of 20 sticky episodes, from it and from every later landing state, and beats the
     paired tape control by at least 5 of 20.
   - **Rule:** PASS if R ≤ 1,694, i.e. the whole left side is learned from the wall-top landing. INCONCLUSIVE if R is
     1,966 or 2,128. NULL if there is no reach. INCOMPLETE and INVALID as usual. A reach of the platform (R ≤ 1,473) is
     reported as "crossing learned".
6. **Beyond the gate (nothing authorised; section 6):** the crossing (g2), then tick 0 and the claim (g3); then faster
   clears through archive search for shorter completions plus re-robustification, and M11 polishing; then other
   characters through M10 onboarding, M8 discovery and M9.
7. **Artifact metadata (section 7).** Every M9 artifact and every future M8 artifact records a top-level
   `"task": {"id": "ssb64_us_mario_btt_v1", "character": "mario", "stage": "btt_mario"}` and a `created_utc` at the
   source. A writer refuses to write an artifact that lacks either field.

---

## 1. The material: what the agent actually discovered

All facts below come from the preserved rd4 routes (`runs/m8_rd_rd4/routes/T_clear`, `T_t`: `trace.json.gz` holds
every reply of the verifying replay), the rd4 candidate registry (`sessions/rd4/candidates_T.jsonl.gz`) and the rd4
closing archive (`archive/`). Ticks are **input ticks of the observation** (the observation after consumed tick t − 1),
unless marked "consumed".

### 1.1 The verified clear (cid 194, 2,326 words; `completion_time_passed` 2,325, `completion_input_tick` 2,326)

**Target breaks** (ID @ input tick):
- Right of the wall: 0@43, 4@120, 9@399, 5@609, 3@880, 7@982, then the moving target 2@1,339.
- Left of the wall: 6@1,838, 8@2,066, 1@2,326.

**The moving platform** (collision group 2, line 19) has period 300. Its low points are at input ticks 239 + 300k
(y 1,500) and its range is y 1,500–3,300. This matches M7m's "low points at 238 + 300k" in consumed ticks. Target 2 was
broken 200 ticks after a low point, and the crossing launch came 80 ticks after one (section 1.2). **The route depends
on the platform phase at two points**, and these are the only time-varying elements the policy must time.

**Segments from the moving target on** (G = grounded on line n, A = airborne):

| ticks | state | what happens |
| --- | --- | --- |
| 1,248–1,257 | G line 1 (raised right step L1) | landing |
| 1,258–1,368 | A | rise from L1; aerial up-B (SpecialAirHi) breaks target 2 at 1,339 |
| 1,369–1,396 | G line 19 (moving platform) | first platform contact |
| 1,397–1,472 | A | |
| 1,473–1,519 | G line 19 | rides the platform up (shield, KneeBend at 1,518); platform rising at about 18 units/tick |
| **1,520–1,693** | **A, 174 ticks: the crossing flight** | jump off the rising platform with its carry; back-air; fall; aerial double jump at 1,576; up-air; **up-B input on consumed tick 1,624** at (−206, 4,194); apex (−1,468, 5,556) at 1,647; FallSpecial from 1,664 |
| 1,694–1,721 | G line 0 (wall top) | wall-top landing at (−1,724, 3,000), LandingFallSpecial |
| 1,722–1,965 | A | left of x = −2,100 from 1,739; target 6 at 1,838 |
| 1,966–2,020 | G line 3 (left floor) | first left-floor landing |
| 2,021–2,127 | A | target 8 at 2,066 |
| 2,128–2,188 | G line 3 | |
| 2,189–2,326 | A | drop below the left floor; target 1 at 2,326; clear |

Before 1,248 there are 22 alternating segments on the main floor (line 4) and the right ledge (line 2), with the six
static right targets.

**The words** are canonical Track 1 indices (`stick × 8 + button`), so the policy's action space contains the route
exactly.
- There are 2,326 words with 407 changes. The mean hold is 5.7 ticks, and holds of 1, 2, 4, 8 and 16 dominate: the
  explorer's hold set.
- Changes per stretch: 227 in ticks 0–1,258, 45 in 1,258–1,520, 28 in the crossing flight, 50 in 1,694–1,966 and 57 in
  1,966–2,326.
- The route is noisy: it is full of presses that change nothing, as expected from a random-burst explorer. A policy is
  free to find cleaner behaviour.

### 1.2 Lineage census of the closing archive (37,312 cells, 13,886 bursts)

Words of every cell were reconstructed by the archive's own `(burst, offset)` → `start_rep` walk and compared with the
verified clear.

| question | answer |
| --- | --- |
| distinct clear sequences | **5**: T_clear (2,326 words), T_t (2,315; clear, `completion_time_passed` 2,314, ≈ 38.6 s), and candidates 656 (2,348), 849 (2,324) and 979 (2,341). They diverge from T_clear at ticks 2,298, 2,213, 2,287 and 2,282. **Only T_clear and T_t are replay-verified**: the rd4 plan stopped at the first verified claim of each level |
| shared trunk | all five share ticks 0–2,212; every landing state used in section 5 lies on the shared trunk |
| left-of-wall cells (x bin ≤ −7) | 4,948. **4,932 descend from the trunk and branch at or after tick 1,631**, mid up-B. The other 16 (rd3) branch at 1,174 and lie 6,000–9,600 units below the floor: off-stage falls under the stage, not crossings |
| wall-top cells | 18,318 (branches at 1,631), 18,767 (1,694), 26,944 (1,631): one lineage |
| level-7 cells (all right targets broken) | 5,107. They branch from the trunk between ticks 907 and 1,781 (median 1,397), so alternative right-side sweeps exist, but none has a known continuation over the wall |
| other agent-generated crossings | M7p seed-1 geo4 final episode `…44619208`: L1 lower route, left entry at 3,001, target 6 at 3,008, four targets still standing, fall at 3,444. M7h seed-1 training episode `83112a8c`: over-wall entry at row 2,816, four targets standing. **Neither can finish a clear before tick 3,600** |

**Consequence.**
- For a clear-based success criterion there is **one lineage family**: one trunk through tick 2,212 and five endings
  on the left floor.
- "Several lineages" can add diversity only in the last 110 ticks.
- Go-Explore's own robustification used ten demonstrations from independent runs, so this difference is recorded as
  the main risk (section 2.4).

---

## 2. Method

### 2.1 What Go-Explore's robustification is (published facts)

| source | what it did |
| --- | --- |
| Salimans & Chen 2018, *Learning Montezuma's Revenge from a Single Demonstration* (the **backward algorithm**) | Each rollout worker starts from a demonstration state drawn uniformly from {τ − D, …, τ} around a reset point τ. τ starts at the demonstration's end and moves back once more than ρ = 20 % of workers score at least the demonstration's return from their start. Plain PPO with an entropy bonus whose coefficient needed careful tuning. **No imitation loss.** 1,024 workers, about 50 billion frames. Under sticky actions the policy, trained without them, scored about 10,000 against 74,500 deterministic. Failures: Gravitar and Pitfall, where the agent could not reach the demonstration's later states from earlier ones |
| Ecoffet et al. 2019, *Go-Explore* | Robustified Go-Explore's own trajectories with the backward algorithm. A single demonstration robustified in **40 %** of runs; the authors therefore learned from **10 demonstrations at once**, which succeeded in 5 of 5 Montezuma runs. Robustification and all tests used random no-ops (up to 30) and sticky actions. It cost about 4.35 billion frames per Montezuma run, more than the exploration phase. Full-length Pitfall trajectories did not robustify. A network can diverge after finding a solution, so the last checkpoint is not necessarily good |
| Ecoffet et al. 2021, *First return, then explore* (Nature) | Modified backward algorithm with 10 + 1 demonstrations, **self-imitation learning added**, sticky actions in robustification and evaluation, an "allowed lag" of 50 frames behind the demonstration, and termination after a success rate above 98.5 % for 150 iterations. Robotics: 2 of 200 runs failed after more than 3 billion frames |

Two consequences shape this proposal:
- **Robustness comes from training under perturbation.** The policy that never saw sticky actions collapsed under them.
- **Diversity of demonstrations is what made robustification reliable.**

### 2.2 What this project's records say

**In favour:**
- **Restarting from the agent's own states is the only thing that ever produced left-side events.**
  - M7h's archive-prefix starts produced every left-region entry, including the seed-1 crossing that landed on the left
    floor.
  - The 1,876 tick-0 starts of the same runs produced none.
  - In M7m, anchored starts taught the policy the steps it had to complete itself from inherited states: 123 of 523
    successes from cuts where only target 7 remained.
- **The route is inside the Track 1 action space,** and every start state is reproduced exactly.
  - M8 recorded 3,480 + 4,194 + 4,037 + 2,175 returns with zero mismatches.
  - M7f, M7h and M7m add more than 5,000 exact replays.
- **Reward v2 pays along the late route.** Seen from a start state, the next reward is near:
  - from the wall-top landing, +1 at 144 ticks, then +1, +1 and +10;
  - discounted at γ = 0.999, the clear bonus is worth 5.3 from the wall top against 0.98 from tick 0.
  - M7n's diagnosis, "before the first left-target break there is no positive signal at all", is the exact gap a
    backward curriculum closes.

**Against, or unresolved:**
- **M7m's backward curriculum did stall,** at W2, on a precise two-part motor sub-skill: up-B at a spot, then holding
  up through the four startup ticks.
- **The project's binding problem is the zero first-event rate under per-tick sampling** (learning-setup review). The
  backward algorithm attacks it only if each strip is short enough for local exploration to bridge.
- **Throughput is replay-bound.**
  - There is no save state, by contract: every start at τ costs a fresh boot plus τ prefix ticks.
  - M8 spent 90.3–93.6 % of its native ticks on prefix replay.
  - The gate's budget is 4–5 orders of magnitude below the published frame counts (section 2.4).

### 2.3 Why this should succeed where M7h, M7m, M7n and M7p did not consolidate

| line | what was tried | why it did not consolidate (from its own record) | what M9 does differently |
| --- | --- | --- | --- |
| **M7h** (gate 4 `discovered_not_consolidated`) | PPO, v1, p0 = 1/2 tick-0 starts; the other half from archive cells chosen by **novelty** | Starts went to rarely visited cells with **no known path to reward**. The three genuine left entries in 9.2 M transitions were one-offs, never followed by repeated practice from just before them; all 18 seed-1 left episodes fell. Half of the starts were tick-0 starts that never reached the left | Starts lie on a **complete, verified route**: every start has a known continuation to +10. The frontier moves **only** when the newly exposed strip is mastered, so a discovery is practised hundreds of times from just before it. No tick-0 starts until the frontier reaches tick 0 |
| **M7m** (`null`, stalled at W2 in 3 of 3 runs) | Backward curriculum on a **7-right-target sweep** (not a clear), v1, **warm-started** from Phase K finals, 120-tick windows, pass = 5 of 10 pooled outcomes, p0 = 1/2, about 250 anchored episodes per run | (i) **Window pooling:** W1 passes came from cuts that inherited the up-B or needed target 7 only, so the pointer reached W2 with 0 of 80 successes from cuts that needed the up-B input. (ii) **Anti-aligned priors:** P(up-B at the spot) in the finals was 0.04 / 0.009 / 0.005, entropy 0.74–1.17 nats. (iii) v1 aliased target identity and showed the platform phase only through the clock. (iv) No completion bonus inside the window's success. (v) Half the budget went to tick-0 starts | (i) **The pointer statistic counts only starts from the newly exposed 20-tick strip;** inherited-motion starts behind it never pass a block. (ii) **A fresh policy at maximum entropy** (4.28 nats). (iii) **v3**: a live flag and position per stable target ID, and the moving platform as a moving segment with velocity. (iv) Success is the **native clear**, worth +10. (v) **All starts sit at the frontier window** (80 %), with 20 % rehearsal behind it. About 2,300–4,500 frontier episodes per hour against about 250 per M7m run (section 5.4) |
| **M7n** (feasibility: 0 of 225, frozen v3 finals, nine post-sweep starts) | No training; frozen policies continued from good right-side states | Frozen policies; starts **before** the crossing; v2 pays nothing before the first left target. 50 approaches to the wall foot, 0 passages | **Training, backward from after the crossing.** The left side is learned first, so when the frontier reaches the crossing the critic already values the wall top and the left floor. The crossing segment then sits between a start state and states the policy already completes |
| **M7p** (one qualified crossing, 2 of 100 wall-top landings, one seed) | Tick-0 PPO, geo4 | A 2 % event over a manoeuvre of about 100 ticks with no reward until the left target. Tick-0 PPO samples it too rarely to reinforce, and the episode then fell | Each strip is practised from its exact start states until it succeeds at 30 % or better. Rare success is the strip's problem, not the episode's |

### 2.4 What it does not fix (risks stated now)

1. **One crossing lineage.** Go-Explore needed 10 demonstrations for reliable robustification; single demonstrations
   succeeded in 40 % of runs. Sticky actions and the start window give off-trajectory states, but not alternative
   routes.
2. **Budget.**
   - Robustifying one Montezuma run cost about 4.35 billion frames. The gate gets about 5–11 million native ticks and
     0.4–1.6 million policy transitions.
   - The offset is a compact structured state and a small MLP (76,818 parameters in M7g's v2 network; the v3 network is
     similar in size) instead of pixels.
   - The likely outcome of a 60-minute gate is partial reach, which is why the gate measures depth.
3. **Pitfall-type failure.** The policy's own arrival at a later state can differ from the trunk's exact state. The
   20 % rehearsal share, the 60-tick window and sticky actions in training are the mitigations; the reach evaluation
   tests this directly.
4. **Clock-keyed tapes.** v3 contains the clock, so a network could memorise action = f(tick). Sticky actions break the
   tape (section 4.2). The platform still requires real use of time or of the moving segment's state.
5. **Precision under perturbation.** Sticky actions at p = 0.25 may make some manoeuvres unreliable even for a perfect
   closed-loop policy. The trunk's up-B apex clears the wall top by 2,556 units, so the crossing itself has a large
   margin; the target-2 up-B and the platform launch have untested tolerance.
6. **`ent_coef = 0.0`.** Salimans & Chen needed a tuned entropy bonus. The selected profile has none. The gate monitors
   entropy per rollout (open question 7).
7. **Divergence after success.** Go-Explore observed it, so the decision uses the frozen *final* checkpoint and also
   reports the best checkpoint by reach.

### 2.5 Observation and reward: v3 + v2, the v4 question

**Reward `btt_reward_v2`, frozen and rebased at the start.**
- +1 per target broken after the start, +10 on the native clear, −5 on a fall, −0.001 per policy tick.
- Prefix breaks earn nothing, as in M7m.
- No shaping, no waypoint and no route distance.

**Observation `btt_policy_obs_v3_entities` (606 values, fixed scaling), the selected baseline.**
- The v3 builder is fed every prefix reply, so the handover observation is exactly what the policy would have seen
  had it played the prefix (displacement, sticky projectile slots).
- This path is already proven: the M7n prefix feasibility harness used it for 225 episodes.

**Does the evidence argue for v4 (`btt_policy_obs_v4_input`, 626 values)?**
- **Not on the record.** v4 has never been compared with v3. Its only training (M7r F arm, 3 × 307,200 ticks) reached
  3.23–3.73 targets, in the range of v3's own curves at that budget (3.25–3.57), and neither had any left-side event.
- **One mechanism specific to M9 favours v4.** At a prefix handover the previous controller word is the explorer's,
  not the policy's. 82.5 % of trunk ticks are mid-hold (407 changes in 2,325 transitions), so a uniformly drawn start
  usually hands over during a hold. Whether the policy's chosen button produces a **press** then depends on a word v3
  does not show; v4 shows it through `button_hold`, the tap counters, `tics_since_last_z` and the previous action.
- **The same ambiguity exists in v3's own tick-0 play.** v3 has no previous action, yet PPO learned more targets under
  v3 than under v1.

**Recommendation.**
- Use v3 for g1; change one thing, the method.
- **Register a handover diagnostic:** the strip failure rate for starts drawn mid-hold against starts drawn at a word
  change.
- If g1 is NULL or INCONCLUSIVE and mid-hold failures are at least twice as frequent at the stalled strip, v4 is the
  first fallback. This is evidence-triggered, not assumed.

### 2.6 Alternatives considered and not proposed

| alternative | why not |
| --- | --- |
| Plain tick-0 PPO, longer | M7d, M7e, M7n and M7p: no clear in 20,000+ episodes; M7p's crossing appeared in 2 of 100 episodes and was not reinforced |
| Novelty-frontier restarts (M7h-style) | Gate 4: discovered, not consolidated |
| Goal-conditioned returns (M7s) | Inconclusive; not functional in 3 of 3 runs |
| Model-based planning (M7u line) | The frozen models cannot represent the wall top (hybrid proposal, part 0) |
| **Imitation of the agent's own trajectories** (behaviour cloning or SIL, as in Go-Explore 2021) | It would likely speed learning, and the trajectories are the agent's own. But the project has only ever authorised them as **start states**; M7m explicitly forbade supervised targets. **Not used**; open question 9 |
| Save states / in-process reset to cut the prefix cost | Excluded by the contract ("process restart resets the episode"). Not proposed |

---

## 3. Compliance

| constraint | how M9 satisfies it |
| --- | --- |
| discovered trajectories are the agent's own | Start states come only from the five clear sequences of archive `m8_rd_a1`. They were generated by keyed sticky-random Track 1 bursts, registered by words digest, and verified by exact replay before use (P1). They are **start states and a backward curriculum only**: never action targets, never a source of weights, optimizer state or statistics |
| human recordings, fixtures, TAS | Validation-only and **never read** by any M9 module. A static source guard refuses references to `tas_input_2`, `.btti`, `rl/fixtures/m7g`, and the replay-viewer recordings, as M8's guard does. The 7.43 s TAS appears only as a number to compare against (section 6) |
| **the final claim uses no prefix** | The claim evaluator has **no prefix code path**: a separate entry point that only accepts the ordinary non-consuming tick-0 reset (`input_tick 0`, `step_count 0`). Every claim artifact must show `prefix_rows: 0`, the first policy word consumed at tick 0, no idle words, and a stored tick-0 record equal to the pin. A static test asserts that the claim entry point cannot import the staging module |
| no hardcoded routes or waypoints | The training curriculum is generic (strips of ticks along the agent's own trajectory). The "landing states" in section 5 are computed from the trunk's own grounded segments and are used **only** by the evaluation and the rule, never by training, reward or observation |
| exact submit / consume / input-tick contract | Prefix word i consumes tick i. The policy's first word consumes tick τ and its observation is `o_τ` (`input_tick τ`). A staged process waits frozen at `WaitingForAction` (`can_step`, `step_count τ`) exactly as a standby waits at tick 0; no tick passes while it is parked |
| process restart resets the episode | One fresh process per episode, prefix included. A process is never reused for a second episode. No in-process reset, no save state |
| canonical words, no hidden actions | Every episode is stored as canonical words from tick 0: prefix words, then the **submitted** policy-phase words. Under sticky actions the submitted word is the recorded one; the policy's sampled word and the sticky flag are metadata. Replay uses the submitted words |
| no native RNG seed inspection, logging, control, comparison or hashing | Start draws and sticky draws are Python-side keyed sha256 uniforms (`m9|<gate>|<purpose>|<episode>|<tick>`). PPO and SB3 seeds are Python-side training seeds, as in M7b |
| non-PORT decomp, byte-matching | No native, decomp or submodule change. The existing executable `30a3913b…` with existing read-only diagnostics (`SSB64_RL_SPATIAL`, `SSB64_RL_ENTITY`, plus `SSB64_RL_TARGET_DIAG` in evaluation and verification) |
| rebuilt executable | Suspends every lineage claim until each lineage is re-verified from tick 0 on the new executable. A mismatch stops for review; nothing is dropped or re-pinned silently (guide §10) |

---

## 4. What counts as success, fixed before any training

### 4.1 The M9 claim (final, for g3 or later)

All of the following evaluate the frozen final policy from the **ordinary tick-0 reset with no prefix and no idle
words**, under the claim evaluator of section 3. Every counted clear must reproduce exactly in a fresh process from tick
0: native action digest, every consumed tick 0..N−1, break table, the four clear facts, and both completion clocks, never
collapsed.

| tier | condition | role |
| --- | --- | --- |
| **M9-first** | at least one replay-verified clear among 100 stochastic episodes, unperturbed | a milestone, not the claim |
| **M9 claim, part A** | at least **50 of 100** stochastic episodes clear, unperturbed | the policy clears from tick 0 |
| **M9 claim, part B (robustness)** | at least **50 of 100** stochastic episodes clear under **sticky actions p = 0.25 per tick**, **and** at least 25 more clears than the open-loop **tape control** on the same 100 draw keys | a policy, not a memorised tape |
| reported | deterministic argmax, unperturbed (one trajectory) and sticky (100); clear-time distribution; falls; targets | |
| reported, secondary | idle offset k drawn uniformly from 0..299 neutral words before the policy's first action, then sticky p = 0.25, 100 episodes; clear rate | a check on platform-phase adaptation |

**The tape control.**
- It replays the **trunk's** words (T_clear) from tick 0 as a fixed open-loop tape, under the identical keyed sticky
  draws: at a draw below p the previous submitted word repeats; otherwise the tape's word for that tick is submitted.
- The pairing makes "B beats the tape by 25" a paired comparison on identical perturbations.

### 4.2 The robustness test: sticky actions, and why

**Definition.** At every policy-phase tick t > first, with a keyed uniform u_t below 0.25, the word submitted is the word
submitted at t − 1; otherwise it is the policy's sampled word. The first policy word after a prefix may repeat the
prefix's last word, which is still the agent's own lineage word. The same rule applies in training, the reach
evaluation, the tape control and the claim.

**Why sticky actions, rather than random idle ticks, as the gating test:**

1. **It defeats tapes everywhere, not at one point.**
   - Idle offsets perturb the start only; after it the game is deterministic again, so k + 1 offsets can be memorised as
     k + 1 tapes, or as one tape plus "wait for the platform". This is Machado et al.'s (2018) argument for introducing
     sticky actions in place of no-op starts.
   - Under sticky p = 0.25 each of the trunk's 407 word changes is delayed by at least one tick with probability 0.25,
     about 100 delayed changes per episode, so an open-loop tape should essentially never clear. P4 measures this
     before training.
2. **It can be trained by the backward curriculum, and idle offsets cannot.**
   - Mid-route starts are often airborne, and "idle" words mid-air are not neutral.
   - Prepending k idle words to a prefix shifts the platform phase, which breaks every prefix after tick 1,339.
   - So an idle-offset test could only be trained once the frontier is before the first platform-dependent event, and
     the policy would face an untrained perturbation at the claim. Sticky actions apply identically at every start, so
     training, reach evaluation and claim see the same MDP.
3. **It matches the published standard at this project's resolution.**
   - ALE's sticky actions (p = 0.25) act per emulator frame; one BattleShip tick is one frame.
   - Unlike an Atari agent behind frameskip 4, this policy observes every tick and can re-press on the next tick, so the
     setting is no harsher than ALE's.
   - Go-Explore robustified and tested under sticky actions.
4. **It keeps the replay contract.** The submitted word is the canonical record, so replays are exact without
   re-drawing anything.

**Why idle offsets are still reported.**
- Under sticky actions alone a policy's arrival at the platform drifts only by its accumulated delays.
- The uniform 0–299 offset covers the platform's full period. It is a direct check that the policy reads the moving
  segment or the clock instead of assuming one phase.
- It is fair by construction: from any offset, waiting for the platform restores the trunk's phase.

**Cost of the choice, stated.**
- Sticky actions change the effective MDP: a perfect closed-loop policy may still lose some clears at precise
  manoeuvres.
- The 50 % thresholds and p itself are open questions 2 and 3. A lower p (for example 0.1) would be easier and still
  tape-breaking: about 41 delayed changes per tape episode.

---

## 5. The first bounded gate: M9-g1

**Question.** In this project's cost regime (no save state, fresh process per episode, replay-bound starts), does the
backward algorithm under v3 + reward v2 + PPO + sticky actions learn the discovered route closed-loop, and how far back?

### 5.1 Lineages, start states and the curriculum

**Lineage set Ł: the five clear sequences** (section 1.2).
- All are registered by words sha256 and native action digest before the session.
- P1 replays each from tick 0 three times, once through a standby promotion, with all four diagnostics. It checks the
  digest, every consumed tick, the break table, the clear facts and both clocks, and writes the per-tick v3 handover
  table once.
- **Any P1 mismatch stops the session before training.** Nothing is dropped silently.
- Only two of the five are verified today (open question 5).

**Start τ (prefix rows 0..τ−1).**
- If τ ≤ 2,212 the start state is shared by all five lineages.
- Above that, the lineage is drawn uniformly among those longer than τ + 1.

**Frontier pointer τ\*.**
- It starts at τ\*₀ = 2,300, which is calibration: the first strips are partly inherited motion and pass quickly.
- It moves back in strips of Δ = 20 ticks and never moves forward.

**Start distribution** (keyed draws; staged in advance, section 5.2):

| share | region |
| --- | --- |
| 50 % | **the strip** [τ\*, τ\* + 20) |
| 30 % | the near window [τ\* + 20, τ\* + 60) |
| 20 % | rehearsal, uniform over [τ\* + 60, end of the lineage) |

**Pointer rule** (the M7m fix).
- Only strip starts drawn under the **current** pointer count; outcomes from starts drawn under an earlier pointer are
  logged as stale and still used for PPO.
- They are grouped in blocks of B = 10, in completion order.
- A block with **at least 3 clears** (ρ = 0.3; Salimans & Chen used 0.2 over a whole window) moves τ\* back by 20.
  Otherwise a new block starts at the same pointer.
- At τ\* = 0 the strip contains true tick-0 starts.

**Episode success** is a native clear (end record `clear`, `cleared`, ten targets, completion clock) before the
3,600-tick horizon, counted from the reset. There is no lag constraint: the slack is 1,274 ticks, about four platform
periods.

**Accounting.**
- Prefix ticks never enter a PPO rollout and `num_timesteps` counts policy transitions only.
- The horizon counts from the reset.
- A fall ends the episode at −5 (`btt_native_failure_v1`).

**PPO: the M7n profile unchanged except the vector width and a fresh initialisation.**
- MultiInputPolicy [64, 64] tanh, lr 3e-4, rollout 5,120 (4 envs × 1,280), batch 512, 10 epochs.
- γ 0.999, λ 0.995, clip 0.2, `ent_coef` 0.0, vf 0.5, grad-norm 0.5, one torch thread, CPU.
- No observation or reward normalisation; base seed 0.
- Checkpoints every 102,400 transitions plus final.

### 5.2 The staging pool (new code; keeps every contract)

A synchronous vector env stalls whenever an episode needs a fresh boot plus a long prefix. M7h measured 543–670 s of
dispatch stalls per run with prefixes up to 3,000 ticks, and M9's late starts make it worse. So:

- **Process slots.** There are 10 BattleShip process slots: N = 4 hold active episodes and K = 6 stage the next
  starts.
- **Staging one start.**
  1. Launch a fresh process.
  2. Check the non-consuming tick-0 `observe` against the pinned record.
  3. Submit prefix words one per tick, checking each consumed tick and the per-tick chain digest against the P1
     registration.
  4. Build the v3 observation from every prefix reply.
  5. Check the handover observation against the registered table.
  6. Park at `input_tick τ`.
- **Use.** When an active episode ends, its env takes the oldest ready staged start, so promotion is instant. If none
  is ready, the env waits; the wait is recorded.
- **Default split, chosen by measurement.** The split is 4 active + 6 staging by default; P3 measures it against
  2 + 8 and picks the higher measured policy transitions per second by a registered rule. The split changes no
  semantics: staging time is invisible to the MDP.

### 5.3 Phases, caps and stops (one session process; approval required)

| phase | content | native ticks cap | wall cap |
| --- | --- | ---: | ---: |
| S0, before the clock | unit suite (fake game; no non-deterministic test, as rd4 decision 10), rule self-test, static guards, preflight, approval check | 0 | — |
| **P1** lineage verification | 5 lineages × 3 replays, v3 tables written once | 60,000 | 4 min |
| **P2** staging equivalence | 12 keyed starts: the staged handover equals the table; the first policy-word reply equals a cold replay's | 40,000 | 2 min |
| **P3** split measurement | 2 min each for 4+6 and 2+8, random policy in the 2,250–2,310 window, no learning | 600,000 | 5 min |
| **P4** tape control | paired-draw tape at the six landing states 2,128–1,248 and at tick 0: 20 episodes each, p = 0.25, keys equal to the evaluation's. The tape at any deeper landing state the evaluation needs runs in the evaluation phase with the same keys | 600,000 | 6 min |
| **Training** | the backward curriculum of 5.1 | **15,000,000** (expected 5–11 M); **policy transitions ≤ 3,072,000** | **60 min** |
| **Evaluation** | section 5.5, frozen final; the checkpoint nearest 30 min, descriptive | 3,000,000 | 25 min |
| **Verification** | every counted clear of the reach evaluation and P4, and the first 20 training clears | 1,500,000 | 15 min |
| close | identity of the executable and frozen config, write guard, D: increment and independent re-hash | 0 | 5 min |
| **session hard cap** | | | **130 min** |

**Resources, as rd4.**
- Main process ≤ 3,072 MB private; process tree ≤ 9,216 MB private and ≤ 4,096 MB working set.
- System available ≥ 1,024 MB; commit free ≥ 2,048 MB; sampled every 5 s.
- **At most 10 BattleShip processes.**

**Stops.**
- Any memory or process breach; any prefix, chain or handover mismatch, which is INVALID.
- Executable or frozen-config drift; a job in flight for more than 900 s; any write outside `runs/m9_g1/`.
- A stop keeps everything written and relaunches nothing.

**Valid training** ends by its 60-minute wall cap, the native-tick cap or the transition cap. Any earlier stop is
INCOMPLETE.

### 5.4 Expected throughput (measured basis; a model, not a promise)

| input | value | source |
| --- | --- | --- |
| boot to ready, v3 diagnostics | about 3.2 s | M7n foothold: 225 episodes, linear fit of prefix wall time against τ for nine cuts 1,679–2,813 |
| prefix replay, v3 diagnostics | about 1,060 ticks/s per process | same fit (slope 0.94 ms/tick) |
| policy step, single env | about 2.8 ms | same records |
| PPO end to end, v3, N = 5 standby | 1,051–1,065 transitions/s | M7p and M7n training |
| M8 return cycle, five workers, spatial only | 1.16–1.35 returns/s, 1,560–1,861 ticks/s, 90–94 % prefix | rd1–rd4 results |

**Staging cycle c(τ) = boot + τ / r.**
- At τ = 2,250: 5.3 s optimistic, about 9 s pessimistic (10 processes on six cores roughly halve r).
- With K = 6 staging slots: 0.65–1.15 starts/s, about 2,300–4,100 episodes per hour.
- Policy phases grow from about 150 ticks (frontier near 2,250) to about 650 (frontier near 1,700).
- Expected yield: about 0.4–1.6 M policy transitions and 5–11 M native ticks in 60 minutes.
- The strip rule needs at least about 20 episodes per move (10 counted strip outcomes at a 50 % strip share), so
  2,300 → 1,694 is at least 31 moves and at least about 600 episodes **if every block passed first time**.
- Reaching the wall top in 60 minutes therefore leaves room for several failed blocks per strip, but not for a long
  stall.

### 5.5 Measures

**Landing states (the reach scale).**
- The landing states are the first tick of every grounded segment of the shared trunk (section 1.1), computed from
  the trunk itself. They are the decision states where no motion is inherited.
- From the end backwards: **2,128 · 1,966 · 1,694 (wall top) · 1,473 (platform, before the launch) · 1,369
  (platform) · 1,248 (L1)**, then the 22 earlier landings, then tick 0.

**Reach evaluation, frozen final policy.** At each landing state from 2,128 down to 1,248 and at tick 0:
- 20 stochastic episodes with sticky p = 0.25 (evaluation keys, never training keys);
- the paired tape-control episodes (P4);
- one deterministic, unperturbed episode.

Below 1,248 a landing state is evaluated only if the training frontier went below it. A descriptive fine grid
(10 episodes every 25 ticks from 2,300 to 50 below the final frontier, at most 40 points) gives R_fine.

**Reliable reach R.**
- R is the earliest landing state λ such that, at λ **and at every later landing state**, the clear count is at least
  10 of 20, every counted clear is replay-verified, and the count exceeds the paired tape control by at least 5 of 20.
- R = none if 2,128 fails.
- Route mastered = 2,326 − R ticks.

**Reported, never deciding.**
- R_fine; the best checkpoint by reach; and the pointer trace τ\*(t) with time per strip and block pass rates.
- The backward rate: route ticks mastered per training hour, with a linear projection to tick 0 marked as an
  extrapolation.
- Training clears by start region; the tape-control table; deterministic reach.
- Tick-0 behaviour: 20 sticky episodes plus one deterministic. Any clear is replayed and reported as a discovery; none
  is expected.
- Policy entropy and explained variance per rollout.
- The handover diagnostic (section 2.5).
- Throughput (starts/s, staging waits, transitions/s); native ticks split by prefix and policy; memory; process counts.

### 5.6 The registered decision rule `m9_g1_rule_v1`

Evaluated in this order; the first that holds is the outcome.

| outcome | condition |
| --- | --- |
| **INVALID** | Any integrity or compliance failure: a prefix, chain or handover mismatch; a counted clear that fails exact replay; executable or frozen-config drift; a start drawn from outside Ł; any read of fixtures or the TAS; a sticky or start draw not reproducible from its key; a claim-mode artifact with a prefix; a write outside `runs/m9_g1/`; approval or snapshot identity mismatch. *Repair and a new approval; never a retry* |
| **INCOMPLETE** | P1–P4 not passed; training stopped before its wall, tick or transition cap; any landing state from 2,128 to 1,248 not fully evaluated; or an unverified clear (verification cap) that could change R. *Not a performance result* |
| **PASS** | R ≤ 1,694: from the wall-top landing the policy reliably completes the whole left side (three targets no policy had broken from its own control at tick 0, two landings and the under-floor drop), beating the tape. If also R ≤ 1,473, the record adds **"crossing learned"** |
| **INCONCLUSIVE** | R ∈ {1,966, 2,128}: the backward process works over part of the left side but did not reach the wall top in 60 min |
| **NULL** | R = none: no reliable clear even from the last landing state, 198 ticks before the end |

**What each outcome leads to.** Nothing follows automatically: every next step needs your authorisation.

| outcome | proposed next step |
| --- | --- |
| PASS | g2 becomes proposable: resume from g1's final checkpoint and pointer, with the crossing as its bar |
| INCONCLUSIVE | a review using the per-strip records: entropy, handover diagnostic, stalled strip |
| NULL | stop the line for review; no budget extension |

**Odds (subjective, for planning only).**
- PASS 35–50 %, INCONCLUSIVE 30–40 %, NULL 15–25 %.
- "Crossing learned" inside g1: 10–20 %.

### 5.7 Integrity (as M8, adapted)

1. **Preparation, zero ticks.**
   - New files only (section 8).
   - Unit suite on the fake game; rule self-test covering every boundary and the precedence; static guards.
   - No non-deterministic test (rd2's launch refusal came from one).
2. **Source snapshot** `D:\BattleShip_source_snapshots\<date>_m9_g1`, with tool verify and an independent PowerShell
   re-hash.
3. **Approval** `docs/rl_m9_g1_approval.json`, written from the freshly computed identity **after** the snapshot. It
   names the snapshot digest, the executable, the frozen runtime config, the five lineage words digests, the rule
   digest, the code fingerprint and every cap.
4. **Pre-launch conditions.**
   - `runs/` backup coverage is 0 uncovered and no BattleShip process is running.
   - Free memory and commit are above the caps; rd1–rd4 trees are byte-unchanged.
5. **Replay checks.** Every staged start checks the tick-0 record, consumed ticks, the chain and the handover. Every
   counted clear is replayed exactly from tick 0. Draws are recomputed from keys at verification.
6. **Close.**
   - Identity of the executable and frozen config.
   - Write-guard record: nothing written under `runs/m8_rd*` or any other tree.
   - D: increment `D:\BattleShip_runs_backup\<date>_incr_m9_g1`, tool verify PASS, an independent PowerShell
     re-hash, and coverage of `runs/` back to 0 uncovered.
   - Leftover BattleShip processes = 0.
7. **Artifacts.**
   - Every episode is kept as a compact canonical record: lineage, τ, prefix digest, submitted policy words as hex,
     sticky mask, end record, task, `created_utc`.
   - Full M4-form artifacts are kept for every clear, every evaluation and tape episode, and a keyed 2 % sample of
     training episodes.

---

## 6. The road beyond (nothing authorised)

### 6.1 Full tick-0 clears

1. **g2: the crossing.**
   - Resume g1's final checkpoint, pointer and lineage registration under the same contracts. A resume is a new
     directory with lineage, as M7b.
   - The bar is R ≤ 1,473 (the platform before the launch). Budget: one or two 60-minute sessions.
   - If the frontier stalls at a strip of the crossing, choose **one** lever per decision, in this order of evidence:
     - **v4**, if the handover diagnostic fired;
     - an **entropy coefficient**, if the policy's entropy collapsed before the stall;
     - **lineage diversity**: further M8 sessions aimed at independent crossings, so that robustification gets
       Go-Explore's multiple demonstrations. M8-rd5 is permitted by the line but unstarted; a diversity-directed
       session would be a new design;
     - **SIL** on the agent's own trajectories, only if you authorise trajectories as action targets.
2. **g3: the right side to tick 0.**
   - 1,248 ticks with seven targets, the moving target 2 and the platform phase. Then the M9 claim evaluation of
     section 4.1.
   - Projection after g1: g1's measured backward rate decides the budget request. At a constant rate, mastering
     2,326 ticks would take about 2,326 / (g1's mastered ticks per hour) hours.
   - Low confidence: the right side has denser rewards but the platform-timed target 2.

### 6.2 Faster clears, toward the 7.43 s TAS without using it

- **From the policy's own clears.**
  - Reward v2's −0.001 per tick barely rewards speed: +10 against −1 per 1,000 ticks.
  - A speed contract (for example, a clear bonus that falls with completion ticks) would be a **new, separately named
    reward**, ranked only on objective completion ticks (guide §9: no reward may rank a slower or incomplete run
    above a faster verified clear).
- **Search, then robustify.**
  - Seed an archive from the policy's own verified clears: agent-generated, as M8 requires.
  - Keep the shortest trajectory per cell (M8 already prefers short prefixes) and look for shorter completions.
  - Then run M9 again, backward from the faster clear. Each faster route is a found trajectory until robustified.
- **M11 polishing.**
  - Frame-perfect optimisation of verified complete routes on raw native words, beyond Track 1's nine stick states.
  - The TAS stays a validation-only reference: its 446-tick `completion_time_passed` is the bar to compare against,
    never a source of words, starts or segments.
  - Note the scale: the best discovered clear is 2,314 against 446, 5.2 times slower, so the first gains are routing,
    not frames.

### 6.3 Other characters

1. **M10 onboarding** (guide §12): a task id `ssb64_us_<character>_btt_v1`, boot and stepping validation, observation
   fields, a character-specific anomaly threshold, and completion clocks. Mario's 300-unit threshold and 446 / 447
   clocks are not copied.
2. **M8 discovery** from tick 0 on the character's own stage, with a fresh archive.
   - The cell key's resource class needs the character's jump and special table.
   - Mario-specific labels (wall top, left region, qualified crossing, landing landmarks) do not transfer; milestones
     fall back to targets broken and the clear.
3. **M9** with the same machinery, a fresh policy, and no Mario transfer unless a separately labelled transfer
   experiment is approved.
4. **Prerequisite.** M8 and M9 code must stop hard-coding Mario. The replay browser shows M8 routes as character "?"
   today because nothing in them names the character, which is why section 7 is a requirement.

---

## 7. Requirement: task and creation time in every artifact, at the source

**Applies to** every artifact M9 writes and every artifact of any future M8 continuation.

**Required fields, at the top level of the JSON object:**

```json
"task": {"id": "ssb64_us_mario_btt_v1", "character": "mario", "stage": "btt_mario"},
"created_utc": "2026-10-03T18:32:46Z"
```

**Where.** In every:
- episode `metadata.json` (training records, full artifacts, reach evaluation, tape control, claim evaluation,
  verification replays);
- route `metadata.json` (M9's registered lineage copies; any M8 route);
- archive-level meta (`archive_meta.json` of any M8 continuation; M9's lineage registry and staging-pool meta);
- run-level record (`run.json`, `checkpoint.json`, the rule, decision, approval and close records).

**Rules.**
- `task` comes from the run's single task identity (the `rl/experiment_config` registry), never inferred from stage
  geometry or a file path. The writer refuses an unregistered id and refuses to write any artifact without both fields
  (unit test).
- `created_utc` is the UTC time when that artifact was first written: ISO 8601, seconds, `Z`.
  - It is never a file modification time.
  - It is never rewritten by a copy, backup or re-verification; a re-verification writes its own record with its own
    time and a pointer to its source.
  - A route may add `discovered_utc` (the ingest time of the burst or episode that produced it), or `null` when
    unknown. It is never guessed.
- For M8 continuations, burst-index rows may gain `created_utc` (the ingest time). The field is **additive**: it is
  excluded from the cell key, selection, digests and the ledger-rebuild equality, so it changes no registered measure.
- Existing artifacts are not back-filled: `runs/` trees are immutable.

**Effect on the replay browser.**
- `replay/replay_task.py` reads the character today from `labels.experiment.compatibility_view`,
  `labels.experiment.task_id` or `labels.contracts.action_class_character`, and the date from
  `diagnostics.created_utc` or the file time. It does not yet read a top-level `task`.
- One format-independent rule ("top-level `task` first; top-level `created_utc` first") would let it show character
  and date for every new artifact without per-format rules. That is a small, separate replay-tool change, not part of
  M9 (open question 11).
- M9's standard episode artifacts also keep the existing `labels.experiment` block, so today's browser already reads
  them.

---

## 8. Implementation outline (new files only; a separate authorisation)

| file | contents | about |
| --- | --- | ---: |
| `rl/m9_lineages.py` | Ł: registration, words and native digests, per-tick chain and v3 handover tables, P1 | 350 |
| `rl/m9_stage.py` | the staging pool: fresh process, tick-0 check, prefix replay with chain and handover checks, v3 builder fed the prefix replies, parking, promotion | 500 |
| `rl/m9_curriculum.py` | pointer, strips, start distribution, blocks, stale accounting, keyed draws | 250 |
| `rl/m9_sticky.py` | keyed sticky actions, recorded masks, tape control | 120 |
| `rl/m9_vec.py` | the VecEnv over staged starts: reward rebasing, horizon from reset, fall termination | 350 |
| `rl/m9_train.py` | SB3 PPO driver, checkpoints, rollout metrics, entropy and handover diagnostics | 300 |
| `rl/m9_eval.py` | reach evaluation, fine grid, the **separate claim evaluator with no prefix path** | 400 |
| `rl/m9_verify.py`, `rl/m9_rule.py` | replays; `m9_g1_rule_v1` and its self-test | 450 |
| `rl/m9_artifacts.py` | compact records, full artifacts, the section 7 metadata and its refusals | 200 |
| `rl/m9_session.py` | CLI: status, preflight, approval template, run, verify-run; caps, sampler, write guard, snapshot and backup calls | 700 |
| `rl/m9_tests.py` | fake-game tests, guards, rule, metadata, determinism | 700 |

**Reused read-only.** `battleship_process`, `battleship_client`, `m7_standby`, `m7_runtime`, `m7n_obs`, `m7n_policy`,
`m7f_trace`, the M8 chain digest and clear-facts code, `rl/tools/runs_backup.py`, the snapshot tool and the tree
sampler.

**No inherited file is edited.** M7 trainer, experiment config and M8 fingerprints stay unchanged.

---

## 9. Open questions

1. **Name.** Adopt "M9 = robustification" and move replay visualization (largely delivered by `replay/`) to another
   label in the guide? The guide was not edited.
2. **Perturbation.** Sticky actions at **p = 0.25 per tick** in training and every evaluation, with idle offsets only as
   a secondary reading, or a lower p such as 0.1?
3. **Thresholds.** For g1's reach: 10 of 20 at every later landing state and a tape margin of 5 of 20. For the M9
   claim: 50 of 100 unperturbed and 50 of 100 under sticky actions, with a tape margin of 25. Go-Explore ran to
   98.5 %. Accept, or raise?
4. **g1's PASS depth.** The wall-top landing (1,694; recommended for a 60-minute gate) or the platform before the
   launch (1,473)?
5. **Lineages.** All five clear sequences, where P1 must verify the three never-replayed candidates and any mismatch
   stops the session? Or only the two verified routes? The M7p and M7h crossings stay excluded, because they cannot
   clear within the horizon.
6. **Initialisation.** A fresh policy (recommended), or a warm start from an M7n v3 final? M7m's warm starts carried
   anti-aligned priors.
7. **PPO.** Unchanged, including `ent_coef = 0.0` (recommended for g1, with entropy monitored), or an entropy bonus
   from the start, which Salimans & Chen found essential?
8. **Observation.** v3 for g1, with v4 as the evidence-triggered first fallback (handover diagnostic ratio of 2 or
   more at the stalled strip)?
9. **Imitation.** Keep the agent's trajectories strictly as start states (no BC, no SIL) as recommended, or authorise
   SIL on them as Go-Explore 2021 did?
10. **Process split.** Default 4 active + 6 staging, with P3 choosing between 4+6 and 2+8 by measured transitions per
    second?
11. **Metadata.** Confirm the top-level `task` + `created_utc` placement, the optional burst-row `created_utc` for M8
    continuations, and a later small replay-tool change to read the top-level fields.
12. **M8-rd5.** Hold it, or keep it as the lineage-diversity lever if g1 or g2 stalls at the crossing?
13. **Envelope.** 60 minutes of training inside a session hard cap of 130 minutes, with 15 M native training ticks.
    Acceptable as g1's budget?

---

## Appendix A. Scratch analyses (read-only; not preserved)

The scripts lived in the session scratchpad
(`…\scratchpad\m9\timeline.py`, `lineage.py` and inline one-liners) and imported no repository module.

| analysis | input | output used here |
| --- | --- | --- |
| route timeline: segments, statuses, breaks, platform phase | `runs/m8_rd_rd4/routes/T_clear/trace.json.gz` (2,326 replies, all four diagnostics) | section 1.1 |
| status names | `python replay/replay_status.py mario` (reads the decomp headers) | section 1.1 |
| word statistics, crossing decode | `routes/T_clear/metadata.json` `track1_words_hex` | sections 1.1, 2.5, 4.2 |
| clear candidates and divergence | `sessions/rd4/candidates_T.jsonl.gz` (1,486 candidates) | section 1.2 |
| lineage census | `archive/{cells.jsonl, bursts.idx.jsonl, bursts.bin}`; every selected cell's words were rebuilt and their length checked against the stored L | section 1.2 |
| staging cost basis | `runs/m7n/feasibility/prefix/foothold/results.jsonl` (225 episodes) | section 5.4 |

## Appendix B. Sources

- T. Salimans, R. Chen, *Learning Montezuma's Revenge from a Single Demonstration*, arXiv:1812.03381 (2018).
- A. Ecoffet, J. Huizinga, J. Lehman, K. O. Stanley, J. Clune, *Go-Explore: a New Approach for Hard-Exploration
  Problems*, arXiv:1901.10995 (2019).
- A. Ecoffet, J. Huizinga, J. Lehman, K. O. Stanley, J. Clune, *First return, then explore*, Nature 590 (2021);
  arXiv:2004.12919.
- M. C. Machado et al., *Revisiting the Arcade Learning Environment: Evaluation Protocols and Open Problems for General
  Agents*, JAIR 61 (2018): sticky actions instead of no-op starts.
