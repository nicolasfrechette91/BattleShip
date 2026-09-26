# M7m W2 stall: diagnosis without training

Date: 2026-09-26.

- **Scope.** A diagnosis only. The M7m decision stays **`null`** (recorded; never re-decided), and nothing was trained or re-evaluated.
- **Evidence** is in `runs/review/m7m_w2_diagnosis/` (git-ignored; `summary.json` lists the hashes):
  - M7m training rows and curriculum logs;
  - the registered source sweep and its start-state table;
  - offline policy and critic outputs of nine frozen checkpoints (`network.json`);
  - 34 registered, exact, read-only native replays of preserved artifacts (`registered_replays.json`, sha `4adf94ea…`, written before any replay ran; 34/34 exact).
- **Code location.** The scripts live outside `rl/`, so the frozen M7m code fingerprint is unchanged.
- **Status names** come from the decomp enums (`ftdef.h`, `ftmario.h`).

## The source maneuver, and what a cut inherits

The source's input sequence is:

1. fireball (SpecialN, status 223) input at tick 739, which breaks **target 3 at tick 800**;
2. shield (152) at 784, then back roll (EscapeB, 157) from 785 to 815, ending grounded at x 2117.92;
3. a one-tick wait (Wait, 10) at 816;
4. **grounded up-B (SpecialHi, 225) input at 817**, with ground startup at 818–821 while the stick is held **up**;
5. airborne at 822, and **target 2 broken at tick 837**, which is platform phase 299, one tick before a platform low point.

Phase K traces (300 episodes) show that the platform height and speed are **identical in every episode at every tick**: period 300, low points at 238 + 300k.

| cut τ | inherited from the prefix | the policy must | target 2 by the policy (training) | successes |
|---|---|---|---|---|
| ≤ 739 | nothing of the maneuver | fireball, roll to the spot, up-B, steer | (in W2: 4 of 127) | 0 |
| 740–785 | the fireball (all 42 W2 target-3 breaks at tick 800 come from τ ≥ 740) | shield and roll to the spot, up-B, steer | (in W2) | 0 |
| 786–816 | the fireball and the roll (arriving at the spot at tick 816) | wait, up-B at 817, steer | 3 of 58 | 0 |
| 818–822 | the up-B input (ground startup) | steer during the startup | **1 of 27** | 1 |
| 823–837 | the airborne up-B | nothing for target 2; target 7 afterwards | **39 of 39** | 13 of 39 |
| ≥ 838 | targets 3 and 2 | target 7 only | — | 123 of 523 (τ 838–1020) |

## 1. Behavior: the earliest meaningful divergence

**Observations** (34 exact replays; representative IDs are episode suffixes in `divergence.json`).

- **The policy reaches the spot but does not up-B.** 13 replays from cuts 752–812 followed the source exactly (grounded, x 2117.92, same status) until **tick 816** and diverged there. The source waits and then inputs up-B; the policy instead did Turn (18) ×4, KneeBend (20) ×2, Squat (28) ×2 or GuardStart (152) ×5.
  - Examples: E0 `7ec725b0` (τ 795), E1 `f5725080` (τ 791), E2 `d96ccc53` (τ 812).
  - Only 2 of the 13 input a grounded up-B within 5 ticks (`0b4150a1` at 817 from KneeBend, `81f7fea8` at 821). Neither broke target 2.
- **With the up-B already input, the policy steers it away.** Both replays from cuts 819 and 822 (`618d1968`, `af3cd751`) leave the source at **tick 823 at x 1985 instead of 2117**: the startup input angled the up-B left, and target 2 was missed. The training rows agree: 1 of 27 from cuts 818–822.
- **Earlier cuts diverge earlier.** From cuts ≤ 785 the divergence is at 696, 738, 784 or 785: no fireball, or no shield-and-roll to the spot.
- **Target 2 initiated after takeover.** Of 11 such training breaks (cut ≤ 817; 9 in E0, 2 in E2):
  - ticks 784, 815, 817, 842, 845, 850, 855, 895, 921, 1258 and 2620;
  - none was followed by target 7 by tick 2699 (0 successes); 2 ended in falls;
  - only one has a preserved artifact (`1ff051cd`, τ 808). That break came from an **aerial** up-B (226) from above (x 2286, y 2868), at platform phase 83 with the platform high, not from the source's grounded route.
- **Normal tick-0 target-2 breaks** (final evaluation, all 7 replayed; E 6, K 1):
  - E2's three were grounded up-Bs at phases 295, 5 and 8 (the platform low point, at x 2365–2684);
  - E1's was aerial at phase 2; E0's two and K0's one were aerial at phases 20, 248 and 250;
  - none was part of a seven-right sweep.
- **These are descriptive observations, not established improvement.** E had 6 target-2 breaks and L = 4 against K's 1 and 0. The relevant outcomes (tick-0 R, native-verified clears) are 0 in both arms.

**Hypotheses** consistent with these observations:

- the decisive sub-skills are the up-B input at the spot and holding the stick up during the four startup ticks;
- hits depend on arriving near a platform low point; the grounded hits land within about ±8 ticks of one.

## 2. Observation sufficiency (btt_policy_obs_v1, 15 fields)

- **Platform phase.** Not hidden, but only implicit. The phase is a deterministic function of `input_tick` (and `time_passed`), so v1 carries it exactly, but only as (tick − 238) mod 300 of a linearly normalized input.
  - **Observation:** in every checkpoint (warm starts, E and K finals), P(up-B) at the source's up-B state changes **monotonically** by less than 0.04 when the tick fields are shifted by up to ±150 ticks. No checkpoint's up-B choice depends on the platform phase.
  - This shows what the policies learned. It does not show whether v1 can support phase timing.
- **Movement state during the up-B startup.** The observations for ticks 818–822 differ **only** in `input_tick` and `time_passed`. The startup frame is visible only through the time fields.
  - The source's startup inputs were not constant (U+B, U+B, U+B, UL+A, DR+B). The records don't show whether distinct per-frame inputs are required; a constant "up" might suffice. That is untested.
- **Target identity is aliased at the decision state.** In the warm-start policies' own tick-0 play (Phase K traces), "grounded within 100 of x 2118 with 5 targets left" corresponds to three different target sets:

  | targets still standing | situation | states |
  |---|---|---|
  | 1, 2, 3, 6, 8 | target 3 standing | 914 |
  | 1, 2, 6, 7, 8 | the source's set | 385 |
  | 1, 3, 6, 7, 8 | target 2 already broken, so an up-B for it is useless | 80 |

  v1 exposes only the count, so the same observation calls for different useful actions. This is concrete evidence of aliasing where the policies act. It is **not** shown to cause the W2 failures, which all start from the source's own set.
- **Phase K's v2 `no_benefit` result** is not treated as evidence either way.

## 3. Learning signal

- **Saved diagnostics.** Only rollout aggregates were saved (`metrics/rollouts.jsonl`).
  - Explained variance was 0.89–0.96 and policy entropy about 0.74–1.17 nats (maximum 4.28), similar in E and K.
  - **Per-state values and advantages were not saved**, so the PPO advantage at any specific attempt cannot be recovered.
- **Offline critic** (frozen checkpoints evaluated on the registered source states; not the training-time signal):
  - every checkpoint's TD error along the successful source path is about 0 at the up-B input (817) and startup (818–821);
  - it jumps only at the target-2 break (tick 837: +0.47 to +0.78);
  - so no critic anticipates target 2 before it breaks, even along the successful path.
- **The policy's own up-B choice at the spot**, P(up-B | the source state at tick 817):

  | pair | warm start | E final | K final |
  |---|---|---|---|
  | 0 | 0.785 | 0.042 | 0.982 |
  | 1 | 0.001 | 0.009 | 0.002 |
  | 2 | 0.004 | 0.005 | 0.0002 |

  - The most likely startup stick in every final is left or down-left; the source held up.
- **Hypothesis (not established):** E0's up-B attempts at the spot were steered left, missed, and cost time before target 7, so PPO moved away from them.
- **Rewards.** Reward v2 credits target 2 with +1, like any target. Missed up-Bs from the spot caused no falls in the replays (1 fall in 127 W2 episodes). The 11 policy-initiated target-2 episodes returned −0.79 to −4.27, with 2 falls, both after aerial routes.

## 4. The curriculum transition

- **W1 blocks.** Every W1 block that passed, in all three E runs, took its successes from cuts 823–837 (airborne up-B inherited) or ≥ 838 (target 7 only). In the whole of W1 there were 0 successes from the 80 draws at cuts ≤ 817, and 1 from cuts 818–822.
- **W2** (cuts 661–780) contains none of those easy cuts. It went 0/127 in all 3 runs.

The W1 → W2 move therefore removed the entire foothold: the pointer advanced without the policy acquiring either the up-B at the spot or the upward steering.

**Assessment.**

- **Schedule problem: supported.** A 120-tick window mixed five sub-skill regimes, and a 5/10 block could pass on the inherited-motion and target-7-only cuts.
- **Exploration problem: supported.** Among E finals, P(up-B at the spot) is at most 0.04; every final steers the startup left; policy-initiated hits are not phase-aligned.
- **Observation problem: possible, not demonstrated.** The phase is only implicit, and target-identity aliasing is real at the decision state; neither is shown to be the cause.
- **Reward problem: not distinguishable** from exploration with these records. Reward v2 is sparse (+1 per target), and there is no evidence of a sign problem.
- The evidence does not single out one explanation. It does locate the failure precisely: **a two-part motor sub-skill** (up-B input at the spot, then holding up through the startup) that no window required in isolation.

## Recommendation: a sub-skill learnability test before any new end-to-end campaign

**Single main change.** The anchored start distribution becomes a **fixed registered cut set S = [786, 822]**: the spot is reached by the inherited roll, but the up-B is not yet airborne. It replaces M7m's moving 120-tick windows; there is no pointer and no blocks.

**Everything else as in M7m:**

- reward v2, observation v1, Track 1, the PPO settings;
- p0 = 1/2 tick-0 starts;
- warm starts from the pinned Phase K finals, base seeds 100–102;
- +1,536,000 policy transitions per run;
- the tick-0 evaluation protocol.

**What it tests.** Can this sub-skill be learned under v2, v1 and Track 1 once it is practiced in isolation? If yes, the stall was exposure/schedule, and a sub-skill-aligned backward schedule becomes the next end-to-end candidate. If not, despite a foothold and hundreds of attempts, the question shifts to exploration, representation or credit assignment for this maneuver.

**What it cannot do.** It is not expected to produce tick-0 sweeps by itself. Normal tick-0 sweeps and native-verified clears are still reported as the relevant outcomes, and nothing else is claimed as improvement.

**Feasibility test (no training; registered before running):**

- **Part 1, controllability** (33 scripted native probes, fresh process each).
  - Steering: the source prefix through row 817 (up-B input), then each of the 9 sticks, with and without B, held for rows 818–822, then neutral to tick 845. That is 18 probes.
  - Timing: the prefix through row 815, then neutral, then U+B input at tick u ∈ 816..830, holding up through the startup. That is 15 probes.
  - Recorded: the native target-2 break by tick 845.
- **Part 2, foothold** (frozen Phase K warm starts, stochastic, evaluator semantics).
  - Cuts {786, 791, 796, 801, 806, 811, 816, 818, 820, 822} × 4 episodes = 40 per seed, 120 in total, run to tick 900.
  - Recorded: target 2 broken by the policy.

**Outcomes:**

| outcome | condition | action |
|---|---|---|
| Success (GO) | Part 1 shows tolerance: at least 2 stick patterns hit from the startup, and at least 2 consecutive input ticks hit from the spot. Part 2 has at least 1 target-2 break in at least 2 of 3 seeds, at least 3/120 pooled, and at most 90 % | proceed to training |
| Failure (NO-GO) | exactly one input pattern or one input tick works, or Part 2 is 0/120 | the maneuver is out of reach of Track 1 stochastic exploration from these starts; no training |
| Inconclusive | anything else | report only |

**Budget, only if GO.** 3 focused runs × 1,536,000 = 4,608,000 policy-controlled transitions, warm-started from the pinned Phase K finals.

- **Control:** the verified M7m K runs, reused only after a control-identity check; otherwise 3 more K runs.
- **Evaluation:** the registered sub-skill measure (Part 2 re-run on each final) plus the tick-0 final protocol (100 + 100 per run).
- **Proposed primary sub-skill rule** (to be frozen before training): at least 2 seeds where the final policy's target-2 rate from S is ≥ 25 % and at least 3× its warm start's rate.
