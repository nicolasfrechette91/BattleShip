# Hybrid PPO-to-planner proposal: a composite controller from tick 0 aimed at the wall top (2026-10-01)

**Status: read-only analysis plus this proposal.** Nothing was launched, collected, trained, committed or pushed. No
native process ran. No optimizer was constructed and no backward pass was run. The only model computations were forward
passes of the pinned dynamics models: the frozen M7u1 model throughout, and P_refit / P_retrain for two cross-checks.
Every file and parameter digest was verified before and after each script. No PPO policy was loaded; its checkpoint files
were only hashed. Scratch scripts and outputs live outside the repository (appendix A). This document is the only file
added.

**Unchanged:**
- Every registered M7u1 / M7u2 / M7u3 outcome.
- M7u3's registered NULL and its `MODEL_REGRESSION` reading stand as recorded. The M7u4 diagnosis (its §1.7) shows that
  the reading measured the ensemble-mean trajectory, which the planner does not use; it is cited here, not reinterpreted.
- M7u4 is parked, not rejected; nothing here runs or redesigns it.
- Selected baseline: **M7n v3 + reward v2** (Track 1 `btt_s9_b8_v1`, PPO).
- Planner and model: frozen M7u1 model, 64 candidates, H = 64, replan every 4 ticks, unchanged.

**Short answer.**
1. **Part 0: no registered figure or decision depends on AUROC orientation.** Registered code uses `auroc` for one
   thing only: calibration of the ensemble spread against block error > 150. That is 3 call sites and 6 reported figures.
   All six reproduce bit-exactly with an independent pairwise count, in the documented orientation, and none enters a
   rule. The other ordering statistics (planner argmin, sign tests, model reading) are oriented as documented.
2. **The frozen model cannot represent a wall-top landing, nor the wall-top airspace with useful accuracy** (§2.3):
   - floor line 0 (L0) is outside its floor / contact vocabulary;
   - no training row lies above y 2,659 or within 1,000 units of the wall top;
   - even on its own training data it mispredicts the rise of an up-B by a median 553 units;
   - an L0 arrival is decided by margins of 9–150 units (M7p).
3. **A route-free handover exists, and PPO leaves a narrow opening** (§2.5). The condition "within the model's own 128-tick
   reach of the goal and not in a committed status" fires in 29 of 100 episodes of the M7p seed-1 checkpoint:
   - at those states PPO alone lands on L0 within 96 ticks in 2 (6.9 %);
   - along PPO's own paths, 7 passed a point from which a well-timed up-B would clear the ledge height;
   - Mario's only remaining lever there is the up-B, which is the manoeuvre the model predicts worst.
4. **A complete gate design `h1` is given** (§2.6–2.10):
   - four paired arms, an exact registered rule, 48 handovers;
   - ≈ 47 min expected against a 60 min cap, ≤ 1,421,984 native ticks;
   - it detects an L0 rate of ≈ 0.29 against PPO's 0.069 with 80 % power.
5. **Recommendation: do not launch `h1` with the frozen M7u1 model** (§4). Its expected outcome is NULL. The binding
   constraint is the dynamics model (support near the wall top, up-B prediction), not the hybrid structure.

## 0. Verified state and what was read

| item | state |
| --- | --- |
| checkout | `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, branch `main`. `HEAD` = `origin/main` = `c46f09e` (the commit that added the M7u4 proposal). Working tree clean before and after this analysis, apart from this document. Remotes: `origin` = the user's fork; `upstream` (JRickey) is reference only |
| guide and instructions | external `..\guide.md` (revised 2026-09-22; narrative stops at M7g), `CLAUDE.md`, `docs/rl_handoff_2026-09-28.md` |
| results read | M7n implementation report §9–10 and results; M7p results, crossing addendum, wall-top census, flight comparison, counterfactual, jump audit; M7r results |
| M7u records read | every `docs/rl_model_planning_m7u_*`, `m7u2_*` and `m7u3_*` document and approval record; `docs/rl_model_planning_m7u4_offline_proposal_2026-10-01.md` (Parts 1, 2 and 4 closely) |
| code read | `rl/m7u_{analysis,model,state,planner,goals,rule,gate}.py`, `rl/m7u2_{gate,rule,goals}.py`, `rl/m7u3_{rule,analysis,gate,refit}.py`, `rl/m7q_equivalence.py` |
| frozen M7u1 | `runs/m7u/gate/_gate/model.pt` `a4bd30e5…`, parameters `0e70af78…`, vocabulary S 61 / V3 16 / V4 28, 3 members |
| P_refit, P_retrain | `runs/m7u3/gate/_gate/model_refit.pt` `3888d747…` / `74c8861e…`; `logs/m7u3_prep/p_retrain.pt` `47d51b1b…` / `13fa9cdb…` |
| artifacts read | M7u1 `collection.json` + 92 sidecars, `state.json`, 120 trial files; M7u2 `state.json` + 72 trial files; M7u3 `state.json` + 96 trial files; the M7p wall-top census (98 traces) and crossing addendum (2 traces), `census.json`; the M7n v3 and M7p geo4 evaluation records (`evaluation.json`, 2,955 + 100 episode summaries) |

## 1. Part 0: AUROC and ranking-orientation integrity check

### 1.1 The function

`rl/m7u_analysis.py:80-95`, `auroc(scores, labels)`:
- ranks the scores ascending, averaging ties;
- returns `(R_pos − n_pos(n_pos+1)/2) / (n_pos · n_neg)` = **P(score_pos > score_neg) + ½ P(tie)**.

So a value above ½ means the positive class has the **higher** score. For a lower-is-better score such as the planner
score, the planning-relevant AUROC is `1 − auroc(score, label)`. That is the trap the M7u4 scratch work fell into twice.

No unit test in `m7u_tests.py`, `m7u2_tests.py` or `m7u3_tests.py` mentions or exercises the function.

### 1.2 Every registered use

In every registered use, the score is the **ensemble spread** after 4 executed words (max of the member x / y position
std; `m7u_analysis.block_errors`). The label is **"the realised ensemble-mean block error exceeds the ±150 box"**. The
value therefore reads P(spread is higher on blocks that missed the box). That is what each results document calls the
"AUROC of the spread for / against error > 150".

| gate | call site | blocks (> 150) | registered value | recomputed: `ua.auroc` / independent pairwise count | inverted, it would read | enters a rule? |
| --- | --- | --- | ---: | --- | ---: | --- |
| M7u1 executed P + S | `m7u_gate.py:919` | 1,582 (56) | 0.6441795 | 0.6441795 / 0.6441795 | 0.356 | no |
| M7u1 held-out behaviour | `m7u_gate.py:919` | 494 (19) | 0.7195568 | 0.7195568 / 0.7195568 | 0.280 | no |
| M7u2 executed P + S | `m7u2_gate.py:832` | 1,446 (52) | 0.8455055 | 0.8455055 / 0.8455055 | 0.155 | no |
| M7u3 executed PF (frozen) | `m7u3_analysis.py:178` via `m7u3_gate.py:1083` | 695 (23) | 0.7481237 | 0.7481237 / 0.7481237 | 0.252 | no |
| M7u3 executed PR (refit) | same | 690 (26) | 0.7509268 | 0.7509268 / 0.7509268 | 0.249 | no |
| M7u3 executed SR (refit) | same | 768 (37) | 0.7413761 | 0.7413761 / 0.7413761 | 0.259 | no |

**How it was recomputed:**
1. The registered blocks were rebuilt with the gates' own `block_errors` from the preserved trial files and M7u1 sidecars
   (forward passes of the frozen model, and of P_refit for PR / SR).
2. The value was recomputed with `ua.auroc` and with an independent count of all positive / negative pairs.
3. All six equal the values in `state.json` to every printed digit.
4. The reported wording matches the orientation: M7u1 results line 74, M7u2 results line 130, M7u3 results line 150.

### 1.3 Every other ranking or ordering statistic in the registered code

| statistic | site | orientation | check |
| --- | --- | --- | --- |
| planner choice | `m7u_gate.py:396`, `m7u2_gate.py:299`; decision reproduction `m7u2_gate.py:253`, `m7u3_gate.py:413` | `argmin` of `m7u_planner.score` | consistent: the score is a cost (Chebyshev / 150 + grounded + time, or the fall cost), lower is better |
| m7u1 / m7u2 rules | `m7u_rule.paired`, `m7u2_rule.paired` | b = P only, c = control only; PASS needs b − c ≥ threshold | consistent with the registered tables (M7u1 21 / 14, M7u2 7 / 7) |
| m7u3 rule | `m7u3_rule.paired`, `p_exact`, `significant` | b = PR only; p = P(Bin(b + c, ½) ≥ b), the upper tail that favours the treatment; integer arithmetic | consistent: the self-test pins 5–0 passing (p 0.031) and 4–0 failing; recorded p 0.828 / 0.109 / 0.031 recompute from b, c |
| m7u3 model reading | `m7u3_rule.model_reading` | reduction = 1 − median(model) / median(frozen), positive = lower error; "better" = a < b | consistent: 819.3 / 669.4 = 1.224 ≥ 1.20 → `MODEL_REGRESSION` |
| m7u3 paired strict errors | `m7u3_analysis.paired_strict` | d = a − b; a better if d < 0 | consistent |
| goal orderings | `m7u_goals`, `m7u2_goals`, `m7u3_goals` | sha orders (no statistic); M7u1's fallback fills by ascending q (rarer first) | consistent; the fallback was never used (all 40 goals q ≤ 0.0171) |
| replication readout | `m7u3_rule.replication_readout` | b = P_frozen only | consistent with "PF 7 / RC 1, b − c = 6" |

### 1.4 Findings

- **No registered figure or decision is affected by orientation.** The six AUROCs are correctly oriented and exact.
  No rule reads any calibration quantity: the code and the rule docstrings say so, and `apply()` takes only outcomes.
- **Not orientation, recorded for completeness:**
  1. The M7u proposal §5.3 described "AUROC of the std term". The implemented and reported quantity is the members'
     **position** spread after 4 executed words, not the std term of the planner score. The results documents say
     "spread", which matches the code.
  2. Nothing tests the orientation of `auroc`. Any future gate that ranks by a lower-is-better score should invert it
     explicitly and pin that in a test.
- **Outside the registered set:** M7u4's AUROC figures were not re-verified here. Nothing below relies on them.

## 2. Part 1: the hybrid composite controller

### 2.1 What runs, in one process from tick 0

- **Native side.** One fresh BattleShip process per arm-trial, from the non-consuming tick-0 reset, with an empty
  prefix. No recorded prefix, archived start, save state or in-process reset is used.
- **Python side.** One driver process holds the preserved PPO policy and the frozen M7u1 model.
- **Control.** PPO acts live from tick 0. After every returned observation the driver evaluates the handover condition
  (§2.5). From the first tick it holds, the arm's post-handover controller supplies every word until the trial window
  ends.
- **Words.** Every submitted word is a Track 1 word recorded as a canonical native action from tick 0, whoever chose it
  (PPO, planner or RC). The handover inserts no tick.
- **Tick contract.** The handover is decided on the reply with `input_tick = k`, i.e. after native tick k − 1 was
  consumed. The first post-handover word is the word for tick k. Each submitted word for tick T is consumed at T and
  returns `input_tick = T + 1`; k = words submitted = `input_tick` at every row.

### 2.2 The goal: an L0 landing, commanded through the wall-top box

**Geometry** (pinned stage table, `m7g_spatial.EXPECTED_LINES`):
- the wall block spans x −2,100…−1,800 from y −2,850 to 3,000;
- **L0** (line 0) is its top, extended right as a ledge: x −2,100…−1,200 at y 3,000;
- the ledge's right face is line 12 (x −1,200, y 2,700…3,000) and its underside line 9 (y 2,700, x −1,800…−1,200);
- **L1** (line 1) is the raised right step, x 2,100…3,300 at y −450;
- L2 (line 2, pass-through) is x 1,200…2,100 at y −1,500;
- the main floor L4 is at y −2,550 and the left floor L3 at y −1,950;
- the moving platform is line 19.

**Why the wall top.**
- A clear needs the three left targets (IDs 1, 6, 8).
- The wall is a single block from below the main floor to y 3,000, so every route to them passes over L0's airspace.
- Every recorded left entry did: 2 in the seed-1 geo4 final, and 1 unqualified entry in the 2,955 preserved v3
  evaluation episodes.
- The project's only qualified crossing landed on L0 first.

**Candidates:**

| candidate goal | expressible by the unchanged planner cost (airborne point, ±150)? | inside the model's training support? | crossing relevance |
| --- | --- | --- | --- |
| landing on L0 (grounded, floor line 0) | no: the cost rewards *airborne* reach and has no floor-line term | no (§2.3) | direct: first segment of the only recorded crossing |
| **wall-top box** WT = (−1,350, 3,150) ± 150, i.e. x −1,500…−1,200, y 3,000…3,300 | **yes** | no (0 training rows) | every recorded L0 arrival passed through it |
| moving target 2 or right target 3 | no: a break needs an attack at the target's position and time | target 2 partly (y ≤ 2,721) | needed for a clear, but not a crossing |
| a "launch point" before the up-B (e.g. the landings' up-B starts) | no: a box cannot require the up-B to be still available | no (0 rows within ±150) | indirect |

**Choice.**
- **Commanded goal** g = the WT-box centre (−1,350, 3,150): the ±150 box whose right and lower edges are L0's right end
  and its surface. The planner cost is unchanged.
- **Primary native success:** the first grounded tick on floor line 0 inside the trial window (valid fighter, not the
  fatal-fall tick).
- **Secondary success, reported:** valid airborne reach of the WT box (M7u semantics).

**Why this split.**
1. The landing is the crossing-relevant event the user asked for. It is measured natively, so the model does not need
   to represent it for the outcome to be read.
2. The box is the only representation of it that the unchanged cost can express.
3. Both recorded L0 arrivals crossed the box and landed 8–12 ticks later:
   - seed-1 geo4 `…44619208` entered the box at tick 2,426 at (−1,226, 3,151);
   - `…85c10043` entered at tick 856 at (−1,200, 3,029);
   - no other census episode ever entered it.

### 2.3 Item 3: can the frozen model represent the goal? No, not with useful accuracy

**(a) Vocabulary: a grounded state on L0 is unrepresentable.**
- H3 (floor line × contact bits) has 16 combinations, over floor lines −1, 1, 2 and 4 only.
- Lines **0 (L0)**, 3 (L3) and 19 (moving platform) never occur. No combination carries the ceiling bit.
- The H3 mask allows a grounded state only on lines 1, 2 or 4. An imagined landing at y 3,000 would therefore be forced
  onto the wrong line.
- The landing *status* exists (`LandingFallSpecial` 59, `FallSpecial` 58, up-B 225 / 226 are in the 61-status
  vocabulary). The *place* does not.

**(b) Support: no training data within about 340 units of the goal's height.**

| M7u1 training data (80 episodes, 241,044 valid rows) | value |
| --- | --- |
| y quantiles 50 / 90 / 99 / 99.9 %, maximum | −2,501 / −559 / 710 / 1,866; max **2,659** (held-out max 2,721) |
| rows with y ≥ 2,000 / ≥ 2,500 / ≥ 2,800 | 156 (6 episodes) / 18 (2) / **0** |
| rows in the WT box; rows with x ≤ −1,200 and y ≥ 2,000 | **0 / 0** |
| rows within ±150 of the landings' up-B start points (34, 1,790) and (−418, 1,765) | **0** |
| rows with x ≤ 0 and y ≥ 1,500 | 23 |
| grounded rows on L1 / L2 / L4 / L0 | 7,135 (45 episodes) / 14,818 / 114,346 / **0** |
| L1 takeoffs | 78 in 45 episodes; apex median 907, max 2,659; one flight reached x < 0 (min x −1,597) |
| targets remaining 5 / 6 (the handover states have 5 in 13 of 29 and 6 in 11) | 0.6 % / 20.7 % of rows |

The model's inputs include absolute x and y (÷ 2,000), the clock and targets remaining. A wall-top state is therefore an
extrapolation in its raw inputs, not only in its geometry.

**(c) Accuracy on the manoeuvre that reaches the goal: poor even inside the support.**
- After takeoff from L1, an L0 arrival is decided by the up-B. Its launch adds a fixed native rise of +1,361.3; the
  stick has no effect after the launch.
- It reaches y 3,000 only from a start height of at least 1,638.7. The recorded failures missed by **8.6** units at the
  up-B start; their apexes were 9–111 below the top. The landings cleared it by 126–151 (M7p flight comparison).
- The frozen model's open loop from every up-B onset in its data, with the recorded words, gives:

| up-B onsets, horizon 48 ticks | held-out (55; 40 air, 15 grounded; 35 angled) | in-sample (300 sampled) |
| --- | --- | --- |
| native rise from onset, median | 1,666 | 1,440 |
| member \|rise error\|, median (p25) | **586** (274) | **553** (233) |
| onsets with all 3 members within 100 units of the true rise | **0 / 55** | 0.3 % |
| onsets where a majority of members predicts any rise ≥ 1,000 (all true rises are ≥ 1,000) | **52.7 %** | 54.7 % |
| member spread of the predicted rise, median | 738 | 657 |
| member position error 8 / 16 ticks after the onset, median | 443 / 1,029 | — |
| angled vs vertical launch, member \|rise error\| | 412 vs 868 | 445 vs 785 |

**The deficiency is recipe-level, not specific to the frozen model.** On the same held-out onsets:
- P_refit: member error 689, majority launch 43.6 %;
- P_retrain: member error 590, majority launch 61.8 %;
- all three have 0 / 55 onsets with every member within 100 units.

**For scale:**
- the registered generic open loop (held-out, all states) reproduces exactly at 121 / 290 / 645 units at 16 / 32 / 64
  ticks;
- airborne starts alone give 181–235 units at 16 ticks, at every height inside the support (233 at y ≥ 1,500).

The planner scores each candidate by the member mean **plus 1.0 × the member std**, in units of 150. Three members whose
predictions span about 650–740 units have a population std of about 2 cost units (1.8–2.3). The whole goal box is 1 cost
unit wide, so any plan that contains an up-B carries a large penalty. The planner is biased *against* the one manoeuvre
the goal needs.

**(d) What was not done.** The M7p census traces cover the real L1 flights, but they predate v4. They lack three fields
the model reads (`anim_frame`, `anim_speed`, `motion_flag1`; v4 `INPUT` only), so rolling the model over them would need
surrogate inputs. The exact in-support evidence above already decides the question, so no surrogate probe was run.

**Verdict.**
- The **landing** is not representable.
- The **WT box** is representable in form only: it lies outside the support, and the decisive manoeuvre is mispredicted
  by one to two orders of magnitude more than the margin that decides it.
- The other candidates are not expressible by the unchanged cost.
- **The hybrid is therefore not viable with this model for a crossing-relevant goal.** The rest of Part 1 is the complete
  design the user asked for. It is registered-ready in form, so it can be judged on its merits, and §4 recommends
  against launching it.

### 2.4 Item 1: which PPO checkpoint

| checkpoint | digests (`model.zip` / `vecnormalize.pkl` / `checkpoint.json`) | contract | measured base rates from preserved data |
| --- | --- | --- | --- |
| **M7p seed-1 geo4 final** `runs/m7p/campaign/m7p_geo4_s1/final` | `f7d11d76…` / `822386f6…` / `676feb0e…` | `btt_policy_obs_v3_geo4` (`2b984528…`), `norm_obs` false, 3,072,000 transitions, trained on exe `748dbad9…` | 100 final stochastic tick-0 episodes (wall-top census, exact replays): 4.93 targets / episode; grounded on L1 in 52 (first L1 tick q10 / 50 / 90 = 278 / 1,361 / 2,947); 74 L1 flights, 7 above y 2,800; **WT box 2 / 100, L0 landing 2 / 100** (95 % CI 0.002–0.070); left entries 2, qualified crossing 1; falls 2. At the handover of §2.5: **29 / 100 handovers, PPO's own L0 landing within 96 ticks 2 / 29** |
| M7n v3 seed 0 final | `588ac013…` / `cc585434…` / `dc3d3bed…` | `btt_policy_obs_v3_entities` | 5.52 targets; left entries 0 / 100; min live x ≤ −1,600 in 17; target 7 in 100, target 2 in 0 |
| M7n v3 seed 1 final | `0af46b8a…` / `3192805e…` / `2df2735a…` | same | 5.53; 0 / 100; 32; 59; 7; falls 13 |
| M7n v3 seed 2 final | `68ced00b…` / `8b3b7fe2…` / `91cecc11…` | same | 5.59; 0 / 100; 3; 80; 1 |

**What is missing for v3.** The preserved v3 evaluations store canonical actions and per-episode summaries only. There
are no per-tick traces, so their L1, flight, WT-box and L0 rates **cannot be measured read-only**. The evidence that does
exist:
- 1 left entry in all 2,955 preserved v3 evaluation episodes (seed 2, curve point 1,536,000, unqualified, no landing);
- M7n's prefix-feasibility continuations went to the wall foot (50 / 225) and never over the ledge (0 / 225).

**Choice: the seed-1 geo4 final.**
- It is the only preserved checkpoint with measured, non-zero handover and goal rates. Every other candidate would make
  the gate size a guess.
- It comes from a rejected recipe (M7p `failure_regression` on targets). Using it as a frozen diagnostic component
  changes nothing about the selected baseline.
- Using v3 would first need a zero-training native census of its 300 preserved final artifacts with `SSB64_RL_SPATIAL`
  (≈ 1.08 M ticks, ≈ 20–40 min; the M7p census replayed 352,800 ticks in 12.5 min one process at a time). That is not
  proposed here (open question 3).

**Runtime identity.** The policy was trained on executable `748dbad9…`. The model needs the v4 `INPUT` reply of
`30a3913b…`. M7q's V1 check showed that the v3 entity / spatial objects are identical with `INPUT` on (12 / 12 traces),
so the policy's observation is unchanged. `h1` re-verifies this on one census episode (§2.9).

### 2.5 Item 2: the handover condition

**Definition (`h1_handover_v1`).** Hand over at the first input tick k that meets all four conditions:
1. Mario is live (`btt_active`, `fighter_valid`);
2. the Chebyshev distance from his position to g is at most **D = 2,280**;
3. his status is not in the committed / helpless set {`SpecialHi` 225, `SpecialAirHi` 226, `FallSpecial` 58,
   `LandingFallSpecial` 59};
4. k ≤ 3,440.

**Where D and the cutoff come from.**
- D is the 90th percentile of the frozen model's own **128-tick displacement envelope**: the maximum Chebyshev
  displacement within 128 ticks, over its 80 training episodes. It is fixed by the model's data, not by the stage.
- The cutoff keeps imagination inside the clock track. The frozen track covers input ticks 0…3,600 (3,601 / 3,601 rows,
  measured), and k + 96 + 64 ≤ 3,600. The M7u gates checked coverage only to 192; `h1` must check it to 3,600.

**Why it is not a hardcoded route.**
- It names no surface, takeoff, manoeuvre, waypoint, target or time. It uses only the distance to the commanded goal and
  whether Mario is in a status he cannot act out of.
- It would fire the same way for an approach from the moving platform, from target 7 or from L1.
- In the census, the last grounded surface before the handover was L2 in 16, L1 in 9 and the main floor in 4.
- By contrast, "Mario grounded on L1" would select states by the route.

**Measured on the seed-1 geo4 census** (100 episodes, native positions and statuses):

| quantity | value |
| --- | --- |
| episodes with a handover | **29 / 100** (95 % CI 0.20–0.39) |
| handover tick q10 / 25 / 50 / 75 / 90 | 728 / 1,256 / 2,079 / 3,144 / 3,397 (mean 2,135) |
| state at the handover | airborne in 29 / 29; double jump already used in 29 / 29; up-B unused in 29 / 29 |
| targets remaining at the handover | 5 in 13, 6 in 11, other 5 |
| PPO's own outcome within 96 ticks | **L0 landing 2 / 29** (+67, +79 ticks; 95 % CI 0.008–0.228); WT box 2 (+59, +67) |
| indicative re-timing headroom | 7 / 29 (the 2 successes included): along PPO's own path, after the handover and before any commitment, Mario passed x ≤ 60 with y ≥ 1,638.7 while the up-B was unused. A launch there would clear the ledge height. This ignores the 6–11-tick startup sag and the ledge face, so it is an indication, not a bound |

**What the planner would control.** By the handover, PPO has already fixed the double-jump height, which M7p found
decisive. The planner's lever is the up-B (timing, launch angle) and the drift and aerials before it. That is exactly the
manoeuvre §2.3 (c) shows the model cannot predict.

**Why not the alternatives:**
- *Distance alone with a wide radius* (D = 3,702, the envelope's 99th percentile, 64 ticks): fires in 100 / 100 episodes
  at a median tick of 98, airborne at y ≈ −520, nowhere near a decision that matters.
- *Distance alone with a tight radius* (D ≤ 1,787): fires only after PPO has committed. At the first entry Mario is
  already in the up-B with both jumps used in 62 / 69, 51 / 56 and 33 / 33 episodes for D = 1,787 / 1,500 / 1,200. The
  trajectory is then fixed by native physics.
- *Time-based*: does not select states; L1 groundings span ticks 278–2,947 (q10–q90).
- *Model-based* ("the planner predicts a reach"): depends on predictions outside the support (§2.3) and costs a planning
  decision per check.
- *Sensitivity, recorded:* D = 2,400 gives 49 / 100 handovers, because the L1 first-jump apex (y ≈ 900) sits on the
  boundary. D must be registered exactly.

### 2.6 Item 4: arms

All arms are paired by trial. Trial i uses one PPO sampling key in every arm, so the prefix up to the handover is
identical by construction and verified field by field.

| arm | after the handover | isolates |
| --- | --- | --- |
| **PO** (PPO-only, the key control) | PPO continues with the same sampling key | what PPO itself does from the same native state. This arm is the screening run, so its prefix is the reference |
| **H** (hybrid) | frozen planner P commanded g, unchanged (64 candidates, H = 64, replan every 4, cost and score as `m7u_planner`) | the treatment |
| **RC** (PPO + RC) | the same candidate machinery and stream, candidate 0 at every decision, no model evaluated | whether *any* switch to the planner's random segments helps (e.g. PPO behaving badly after this point). RC is the M7u1 behaviour policy |
| **S** (PPO + S) | planner P commanded g_S = (−450, 3,150), scored on g | whether H's effect follows the command. g_S has the same height but lies 900 to the right: over open air, not over L0, and disjoint from the WT box. A model that merely sends Mario high and left whatever the command cannot pass |

- H and S share the planner's candidate stream (keyed by trial and decision index); RC takes candidate 0 of it, as in
  M7u.
- **The set is unchanged from the user's list.** An arm with PPO switched to argmax after the handover was considered and
  rejected: it is not a control for the planner, and it would add 48 runs.

### 2.7 Item 5: registered decision rule `hybrid_h1_rule_v1`

**Unit.** A handover trial: a PO run whose handover occurred at k ≤ 3,440. Trials without a handover are recorded once,
in PO, which stops at tick 3,440 (a recorded Python truncation: no later handover is possible). They would be identical in
every arm by construction, so they are not run again and count neither way; their number is the reported handover rate.

**Trial window.** Ticks k … k + 95 (96 words). The trial ends at the primary success or at the window end.

**Outcome.** Y_arm,i = 1 iff a native grounded tick on floor line 0 occurs inside the window.

**Paired counts and test.** For X in {PO, RC, S}:
- b_X = #(H ∧ ¬X), c_X = #(¬H ∧ X);
- p_X = Σ_{j = b_X}^{b_X + c_X} C(b_X + c_X, j) / 2^(b_X + c_X), the exact one-sided sign probability (1 when b + c = 0);
- the comparison with 0.05 is done in integer arithmetic, as in `m7u3_rule`.

| outcome | condition |
| --- | --- |
| **INVALID** | any integrity failure (§2.9), including a prefix mismatch at the handover in any arm of any trial |
| **INCOMPLETE** | any cap; or fewer than **N_min = 32** handover trials after **K_max = 220** screened trials; or a success that cannot be replayed within the replay cap. Not a performance result: no retry, extension or relaxation |
| **PASS** | p_PO ≤ 0.05 **and** p_RC ≤ 0.05 **and** p_S ≤ 0.05 (an intersection–union test, no multiplicity correction) |
| **NULL** | b_PO − c_PO ≤ 1 |
| **INCONCLUSIVE** | otherwise; the record names each blocker |

**Disjointness and timing.** PASS and NULL cannot both hold, because p ≤ 0.05 needs b − c ≥ 5 (smallest passing (b, c):
5–0, 7–1, 9–2, 10–3, 12–4, 13–5, 15–6). The rule is applied once, to complete paired outcomes, after every success has
been replayed. No diagnostic quantity enters it.

**Sizing.** The target is **N_h = 48** handover trials, the largest number that fits the 60-minute cap at the measured
stack throughput (§2.8). Screening proceeds in trial order until 48 handovers or K_max.

| assumed rates (independent arms), RC 0.03, S 0.05, PO **0.069** (= 2 / 29) | P(PASS), N = 48 | P(NULL), N = 48 | P(PASS), N = 32 |
| --- | ---: | ---: | ---: |
| H = 0.069 (no effect) | **0.003** | 0.74 | 0.002 |
| H = 0.15 | 0.14 | 0.22 | 0.06 |
| H = 0.20 | 0.37 | 0.07 | 0.18 |
| H = 0.25 | 0.64 | 0.02 | 0.36 |
| H = 0.30 | **0.84** | < 0.01 | 0.57 |
| H = 0.35 | 0.94 | < 0.01 | 0.76 |

**Minimum detectable effect.** At 80 % power and N = 48, the MDE is **p_H ≈ 0.29 against p_PO ≈ 0.069**, a gain of about
+0.22, or about 4×. If H succeeds wherever PPO would have (concordant pairs), the MDE is ≈ 0.25. At N = 32 it is ≈ 0.37.

**Supply.** At the census handover rate (0.29), P(N_h ≥ 48 within 220) = 0.99 and the expected number screened is 166.
At 0.20, P(N_h ≥ 32) = 0.98.

**Read against the headroom.** The indicative re-timing headroom of §2.5 is about 7 / 29 = 0.24. **Even a perfect up-B
timer would sit at about the MDE.** A model that mispredicts the up-B by hundreds of units is expected well below it.

**Readings, reported only and never deciding:**
- **no lever:** the re-timing indicator, computed on each PO run, is small, so even perfect timing could not have passed;
- **model-blind:** in at least half of the H trials, no decision had a majority-predicted WT reach;
- **rollout error:** the MODEL share of H failures is at least ½ (M7u attribution, with g as the goal);
- **undirected:** b_S − c_S ≤ 0;
- **PPO already does it:** c_PO ≥ b_PO.

Also reported: WT-box reach per arm, up-B onset ticks against PO, the handover state classes, and PO's rate against the
census's 2 / 29.

### 2.8 Item 6: budget

**Basis (measured):**
- the M7u recording stack runs at ≈ 110 ticks / s per worker (≈ 545 aggregate with 5 workers; M7u1 collection, M7u2 and
  M7u3 pools) plus 2.24 s per restart. A PPO forward pass for 5 observations adds about 1 ms per vector step;
- planning costs 0.27–0.35 s per decision amortised (M7u2 / M7u3 evaluation), and 0.32 s is used;
- the readiness probe p95 was 0.33–0.40 s.

| phase | native ticks: expected (cap) | wall: expected (cap) |
| --- | ---: | ---: |
| preflight (outside the clock, as in M7u3): unit suite, rule self-test, readiness, zero-tick checks | 0 | ≈ 5 min |
| P1: M7u identity (2 m7u1 artifacts, 354), PPO-stack identity (1 census episode, 3,600), sampler determinism probe (2 × 512) | ≈ 5,000 (6,000) | ≈ 60 s (180) |
| screening = PO arm: ≈ 166 trials; no-handover episodes stop at tick 3,440, handover episodes at k + 96 | ≈ 513,000 (756,800 = 220 × 3,440) | ≈ 1,100 s (1,600) |
| H, RC, S on 48 handover trials, from tick 0 | ≈ 321,000 (509,184 = 3 × 48 × 3,536) | ≈ 1,445 s (1,700), of which ≈ 740 s planning (2,304 decisions) |
| replays of every success (expected 13–30 × ≈ 2,231) + analysis | ≈ 30,000–67,000 (150,000) | ≈ 210 s (500) |
| **total** | **≈ 0.87–0.91 M (1,421,984)** | **≈ 2,815 s ≈ 47 min (global hard cap 3,600 s from P1)** |

**Caps and memory.**
- Any cap stops the run as **INCOMPLETE**; there is no extension.
- If the handover rate is only 0.20, screening reaches K_max with ≈ 44 handovers (≈ 704,000 ticks, ≈ 1,510 s), and the
  run totals ≈ 3,100 s, still under the cap.
- **Memory** (M7u3's sampler and caps):
  - main-process private ≤ 3,072 MB (M7u3 peaked at 1,622 MB while also refitting);
  - whole tree sampled every 5 s over all descendants (workers, BattleShip, standbys): private ≤ 9,216 MB, working set
    ≤ 4,096 MB;
  - system available ≥ 1,024 MB and free commit ≥ 2,048 MB, else stop;
  - readiness: ≥ 4,096 MB available, ≥ 10,240 MB free commit, planning p95 ≤ 0.5 s, no BattleShip process.

### 2.9 Item 7: integrity

**Tick 0, empty prefix.**
- Every arm-trial and every replay starts at the non-consuming tick-0 reset. The reset row equals the pinned tick-0
  record (`0bf8dbd7…`) in every field and is checked **before the first word**; m7u1's probe never checked t = 0.
- k = words = `input_tick` at every row.
- No recorded prefix, archived start or hidden neutral step exists in any entry.

**Prefix identity.**
- In every handover trial, H, RC and S must reproduce PO's words 0 … k − 1 and every stored row field 0 … k exactly, and
  must hand over at the same k. Any mismatch is INVALID.
- PPO sampling is keyed per (trial, tick): two uniforms from sha256(`h1|ppo|<trial>|<tick>`), inverse-CDF over the
  float64 softmax of the stick and button logits, with a fixed policy-forward batch shape and thread count. There is no
  stateful generator whose state could depend on batching.

**Digests.**
- Frozen model file and parameters are checked at preflight, run start, before and after the arms phase, and after the
  analysis.
- The clock track is rebuilt and must cover 0 … 3,600.
- PPO `model.zip` / `vecnormalize.pkl` / `checkpoint.json` plus a policy state-dict digest are checked at the same
  points.
- The `no_optimizer` guard (`m7u2_gate.no_optimizer`) is active for the whole run, and a source scan rejects training
  calls in the driver.

**PPO-stack identity (P1).**
- One census episode's recorded words are replayed through the `h1` stack (spatial + entity + input).
- Every v3 / geo4 observation field must equal the census trace's raw replies, ignoring only the additive `input`
  object.
- The policy's action distributions on both must be identical.

**Exact replay of every success** (any arm), from tick 0:
- action digest, words, every row field, and the L0 tick (and WT tick) must be equal;
- the replay cap is sized for the expected count. Exceeding it is INCOMPLETE, never a skipped replay.

**Contracts.**
- Exact submit / consume / input tick contract.
- Canonical controller words are replay truth; PPO, planner and RC words are recorded alike.
- No hidden actions.
- Track 1 `btt_s9_b8_v1` (all 72 combinations) unchanged.
- No native RNG inspection, logging, control, comparison or hashing; seeds are Python-side only.
- No human recording, TAS or crossing fixture in any role.
- No native, decomp or submodule change, so non-PORT byte-matching behaviour is untouched.

**Preservation (the M7u3 procedure).**
- *Source snapshot* to `D:\BattleShip_source_snapshots\<date>_h1`, using a snapshot tool of the M7u3 kind: hash in the
  repo, read back from D:, re-hash the repo. It is followed by tool `verify` and an independent PowerShell re-hash, and
  re-verified after the run.
- *Approval record* `docs/rl_hybrid_h1_gate_approval.json`, written from a freshly printed template, must carry every
  identity key (rule, handover and goal digests, models, policy, code hashes, budgets, caps, seeds). Preflight refuses
  for exactly one reason without it, then passes with it.
- *D: coverage before:* 0 uncovered `runs/` files over the base plus every increment.
- *D: increment after:* `rl/tools/runs_backup.py backup --source runs/h1 --dest D:\BattleShip_runs_backup\<date>_incr_h1`
  plus `verify`, an independent PowerShell re-hash (`increment_check.json`) and combined coverage. Reparse points are
  listed, never followed.

**Gotchas carried over.**
- Use short temp paths (Windows MAX_PATH).
- Approval tests must run on isolated temp records.
- Repository-state tests break preflight once the approval exists.
- Memory readiness is judged on working set.
- Preparation output goes under `logs/`, never `runs/`.

### 2.10 Implementation outline (new files only; for completeness, not requested)

| file | contents |
| --- | --- |
| `rl/h1_policy.py` | loads the pinned geo4 checkpoint; keyed inverse-CDF sampler; geo4 observation from replies via the existing `m7p_obs_geo4` path |
| `rl/h1_handover.py` | `h1_handover_v1` (radius, committed set, cutoff) and its digest |
| `rl/h1_rule.py` | `hybrid_h1_rule_v1` with self-test (boundaries, disjointness, INCOMPLETE paths) |
| `rl/h1_gate.py` | preflight, screening, arms, prefix-identity checks, replays, ledger, clock, tree sampler, approval, verify-run; reuses `m7u_*`, `m7u2_gate.load_frozen` / `no_optimizer` and `m7u3_gate`'s sampler unchanged |
| `rl/h1_tests.py` | synthetic-world tests, sampler determinism, handover purity (no surface argument), rule self-test |

The M7u1 / M7u2 / M7u3 files would stay byte-identical (hash-checked). A per-tick PPO controller inside the M7u worker
stack may need one additive wrapper.

## 3. Part 2: what PASS and NULL would and would not demonstrate

### PASS

**Would demonstrate**, on one PPO checkpoint, one frozen model and one seed:
- switching from PPO to the frozen planner, at a route-free handover reached from a normal tick-0 start, produced more
  native L0 landings within 96 ticks than PPO continuing, random segments, or the planner commanded elsewhere;
- every success was replayed exactly from tick 0.

That would be the first evidence that a learned-model planner adds a capability PPO lacks *in the crossing region*.

**Would not demonstrate:**
- a crossing, a left entry, a left-target break or a clear;
- anything about the selected v3 baseline;
- repeatability across PPO seeds or checkpoints;
- full-episode improvement;
- any learning;
- that the model predicts the wall top. The diagnostics would show how successes arose: unpredicted successes would
  mean closed-loop luck or local correction, not model competence.

**Next steps it would motivate** (none authorised here):
1. Replication with the selected v3 seeds, after the read-only-impossible census (§2.4).
2. Chaining: a second handover from L0 toward the left region (left entry, then an L3 landing or target 6). The left
   region is also outside the support, so this needs model-side data first.
3. Using the hybrid's own L0 arrivals as model data, which is a model change and a separate decision.

### NULL

**Would demonstrate** that the frozen planner did not improve on PPO at these states. That matches the read-only
prediction of §2.3: no support at the goal, and the decisive manoeuvre mispredicted.

**Would not demonstrate:**
- that hybrids cannot work: a model with support near the wall top and accurate up-B arcs might succeed;
- anything about v3.

**Next steps it would motivate:**
1. Stop the frozen-model hybrid line.
2. Recognise the constraint as model-side: data in the corridor and at the wall top, and a recipe that predicts the up-B
   launch. All three existing models fail that in support (§2.3 (c)).
3. Pursue that with the parked M7u4 question or with PPO-side levers, as a new decision.

### Other outcomes

- **INCONCLUSIVE:** revise, not rerun.
- **INCOMPLETE:** read the supply and caps; no extension.
- **INVALID:** repair, then a new approval.

## 4. Recommendation

**Do not authorise `h1` with the frozen M7u1 model.**
- The opening PPO leaves is real but narrow: about 7 of 29 handover states had a usable launch point, against 2 that PPO
  converted.
- Using it requires predicting the up-B rise to within tens of units at heights the model has never seen. The model
  misses that rise by a median 553–586 units even where it has data, and penalises it through the std term.
- The design's MDE (≈ 0.29) is at or above the optimistic re-timing headroom (≈ 0.24). Even a perfect planner would be
  near the edge of detection in 60 minutes.
- The expected result is NULL, and it would add little to what §2.3 already shows read-only.

**If you want the empirical check anyway:** the design above is complete. It costs about 47 minutes and about 0.9 M
native ticks, and needs a separate zero-native-tick preparation first (code, unit tests, the policy and model pin checks).
The P1 identity checks of §2.9 then run inside the gate.

**The new fact worth carrying forward, without redesigning M7u4:** none of the three existing dynamics models predicts
the up-B launch reliably, even in-sample (a member-majority launch prediction in 44–62 % of real up-Bs). Any future
planner-side approach to the wall top depends on that.

## 5. Open questions for you

1. **Verdict.** Accept "not viable with the frozen M7u1 model" and stop here? Or authorise preparing `h1` as a cheap
   falsification?
2. **Goal.** Command the WT box but score the L0 landing (proposed), or score the WT-box reach?
3. **PPO component.** Seed-1 geo4 (measured, from a rejected recipe; proposed)? Or the selected v3 seeds, which first
   need a native census of their preserved artifacts (≈ 1.08 M ticks, no training)?
4. **Handover.** Radius D = 2,280, the frozen model's 128-tick envelope q90 (proposed), given the 2,280 → 2,400
   sensitivity (29 → 49 handovers)? Committed set {225, 226, 58, 59}? Cutoff k ≤ 3,440?
5. **S command** g_S = (−450, 3,150)?
6. **Window** of 96 ticks (PPO's own landings came at +67 and +79)? A window of 128 moves the cutoff to 3,408.
7. **Sizing.** N_h = 48 and N_min = 32, with K_max = 220, α 0.05 IUT and NULL at b − c ≤ 1? N_h = 48 is what 60 minutes
   allows. A 75-minute cap would allow about 60 handovers (MDE ≈ 0.25).
8. **Budget.** A 3,600 s hard cap from P1, 1,421,984 native ticks, and the M7u3 memory caps and sampler?
9. **Record keeping.** Should the up-B launch finding (§2.3 (c)) be noted beside the parked M7u4 proposal? It would
   change nothing there.
10. **Naming.** A milestone label (e.g. M7v) and file prefix for any follow-on.

## Appendix A. Scratch analyses (outside the repository; not evidence)

**Location.** `%TEMP%\claude\…\scratchpad\hy\`.
- Scripts that imported repository modules ran with `python -B` and `PYTHONDONTWRITEBYTECODE=1`.
- The `rl/__pycache__` folders predate this session and were not modified.

| script | what it did |
| --- | --- |
| `common.py` | pinned loader (`m7u2_gate.load_m7u1_sources` / `load_frozen`) and the before / after digest check |
| `s1_vocab.py` | frozen vocabulary (statuses, H3 combinations and masks), clock-track coverage, stage line table |
| `s2_coverage.py` | M7u1 training / held-out coverage by height, surface, region and targets remaining; L1 takeoffs |
| `s3_upb.py`, `s3b_sanity.py`, `s3c_upb_split.py` | up-B open-loop accuracy (held-out, in-sample, angled / vertical); indexing sanity (reproduces the registered 121.35 / 289.52 / 644.63) |
| `s3d_models.py` | the same up-B metric for P_refit and P_retrain (digests checked before and after) |
| `s4_auroc.py` | Part 0: rebuilt the six registered calibration block sets; `ua.auroc` versus an independent pairwise count versus the stored values |
| `s5_census.py`, `s5b_radius.py`, `s5c_uncommitted.py`, `s5d_final_trigger.py`, `s5e_resources.py` | census-trace base rates, the 64 / 128-tick displacement envelopes and every handover variant of §2.5 |
| `s6_power.py`, `s6b_power.py` | exact smallest passing (b, c), Monte Carlo power of the rule, supply and budget arithmetic |
| `s7_headroom.py` | the indicative re-timing headroom (7 / 29) |
| `s8_height.py` | airborne open-loop error by height |

**Digests.** Every script that loaded a model checked the file and parameter digests before and after. All were
unchanged: frozen `a4bd30e5…` / `0e70af78…`, P_refit `3888d747…` / `74c8861e…`, P_retrain `47d51b1b…` / `13fa9cdb…`.

**Disclosure.** `s5_census.py` wrote its output (`census_handover.json`) into the repository root, because the helper
changes directory there. I noticed it in `git status` minutes later and moved it to the scratchpad. The working tree was
clean again before this document was written.
