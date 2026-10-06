# M9-g2: a statistically controlled frontier, run as a line of resumable sessions (proposal, 2026-10-04)

**Status: design only.** No native process was launched and no native tick was consumed. Nothing was trained, implemented,
committed, pushed or branched. No existing file and no `runs/` tree was changed. The only computations were read-only scratch
scripts in the session scratchpad, outside the repository (appendix A). They read preserved JSON records only, imported no
repository module and loaded no checkpoint weights. This document is the only file added, and nothing in it is authorised.

| item | state |
| --- | --- |
| checkout | `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, `main`, HEAD = origin/main = `4a778b4` (remote confirmed by `git ls-remote`), working tree clean |
| external guide | `Smash_pc_port/guide.md` (M9 = robustification since 2026-10-04) |
| read | `CLAUDE.md`; the guide; M7h results; M7m results; M8-rd4 results; `rl_m9_policy_proposal_2026-10-03.md`; every `rl_m9_g1_*` document (decisions, implementation, results, checkpoint-evaluation plan, diagnosis) |
| preserved records analysed | `runs/m9_g1/training/{rollouts,episodes,blocks}.jsonl`, `runs/m9_g1/{eval,p4}/episodes.jsonl`, `runs/m9_g1_eval/eval/episodes.jsonl`, `runs/m9_g1_eval/derived/part_a/part_a_values.json` (the diagnosis's per-state values and entropies), `runs/m7n/campaign/m7n_s{0,1,2}_v3/metrics/rollouts.jsonl` |

## Short answer

1. **Primary change, and the only one: a controlled frontier rule** (`m9_g2_frontier_v1`, section 2).
   - Training outcomes only *trigger* a test: at least 8 clears in 20 fresh counted strip outcomes.
   - The test runs on a **frozen snapshot** of the policy: 20 sticky episodes from the strip, pass at **10 clears**,
     curtailed. Every landing state behind the frontier is then **re-checked** with the same test.
   - The pointer moves back 20 ticks only if the strip and every re-check pass.
   - **Attempts are bounded:** at most 3 per pointer per session and 6 per pointer over the line. Exhausting 6 is a
     stop condition.
   - **Error rates per attempt:**
     - At g1's unbacked strip rates (4-12 %), a false move has probability below 0.0001. At a true 25 %, it is 1.4 %;
       across all 6 attempts at one pointer, at most 8 %.
     - A strip at 60 % passes 87 % of the time, and fails all 3 attempts of a session with probability 0.2 %.
     - A later landing that has decayed to 20 % passes its re-check with probability 0.26 %.
   - **Cost:** 14-17 probe episodes per strip test plus about 14 per later landing. That is about 500 probe episodes to
     reach 1,966, 1,200 to 1,694 and 1,900 to 1,473, roughly 15-25 % of the training wall time.
2. **Entropy coefficient 0.01: the evidence cannot decide** (section 3).
   - The coefficient plausibly held rollout entropy near 90 %. g1 plateaued at 90.7-94.8 % while its pointer stood
     still; M7n's v3 runs without the bonus fell to 50-58 % at the same transition count.
   - It did not cause the NULL. Competence at 2,128 existed at 97 % entropy, and the forgetting was the policy becoming
     *sharper* and wrong.
   - **Recommendation: keep 0.01** for the whole g2 line, so the frontier rule is the only change. Reverting to 0.0
     stays your call; it would be the removal of your addition, not a second change.
3. **Value collapse** (section 4).
   - At 2,128 and 1,966 the critic was mostly *right*: it tracked the policy's real decline (final V(2,128) −2.28
     against a realised −3.49).
   - At 2,300 it was wrong (−3.96 against +10.98). That state was almost absent from late training data. The critic
     regressed it toward its abundant neighbours: the post-target-8 states, 81-90 % of whose ticks belonged to failing
     episodes, at about −3 to −4 under reward v2's −5 fall penalty.
   - Neither the horizon nor reward v2's definition is the cause.
   - g2's change is expected to remove the cause. **No second change**; a calibration diagnostic is reported.
4. **Tape baseline** (section 5).
   - g1's two 20-key tape samples at 2,128 (13/20 and 6/20) are consistent with one rate near 0.475 (Fisher p = 0.056).
   - g2 measures the tape once, in g2-s1, on 200 keys at 2,128 and 40 at each other landing, and pins the result.
   - The margin test becomes `c ≥ max(10, ⌈20·p̂_tape⌉ + 5)`: about 15 of 20 at 2,128 and 10 of 20 elsewhere.
5. **Resumable line** (section 6).
   - Sessions g2-s1, s2, … of about 2 hours each: 80 minutes of training, a 145-minute hard cap.
   - Continuity of the model, the optimizer and the curriculum state; pinned digests; a D: increment at every session
     close.
   - Progress measure: the **sustained frontier depth D_k**, measured by the close audit of the frozen final policy.
   - **Stop budget:** the line ends if D has not reached 1,966 after **N = 3 sessions**. From session 4, D must gain a
     landing every two sessions. The cap is 8 sessions, and g2 completes at D ≤ 1,473.
6. **g2-s1 rule** (section 7):
   - PASS if R₁ ≤ 1,966 (the reliable reach, with the pinned tape margin);
   - INCONCLUSIVE if D₁ ≤ 2,128;
   - NULL if D₁ = none;
   - INCOMPLETE and INVALID as in g1.
7. **Everything else is unchanged from g1** (section 8), except three operational items, each justified: P3 is dropped
   (4 + 6 was already measured), evaluation keys are reused across sessions for pairing, and verification is sampled
   for probe clears.
8. **Alternative: archive search for shorter clears** (section 10).
   - It is cheaper and likelier to produce *something* soon: a verified clear at least 10 % shorter, 60-75 %
     subjectively, in one or two one-hour sessions.
   - It does not move the Track 1 policy claim, and by this method it essentially cannot approach 446 ticks.
   - g2 is the only one of the two that advances M9. Odds of reaching 1,473 within 8 sessions: 15-25 %, subjective.

---

## 1. What g1 established (from the diagnosis; nothing re-decided)

- **Registered outcome NULL.** The final policy cleared 0 of 20 sticky episodes at every landing state. The tape cleared
  13 of 20 at 2,128.
- **H3, lucky moves.** The g1 rule was "3 clears in a block of 10 moves the pointer; a failed block is retried without
  limit".
  - 9 of the 16 moves were never backed by a 30 % strip rate.
  - The last three moves had pooled rates of 3.5-11.7 % and took 49 % of training.
- **H1, forgetting.** Paired episodes on identical keys:
  - at 2,128, 9 of 20 at 409,600 transitions against 0 of 20 at the final (p = 0.002);
  - at 2,250, 5 of 20 against 0 of 20 (p = 0.031).
- **H2, a train/evaluation action-mode mismatch, is contradicted.**
- The two are linked. The pointer outran competence (H3); 85 % of starts then lay on a floor where 85-90 % of episodes
  fell; and the frontier's gradient overwrote the final drop (H1).

How easily g1's block rule passes on luck (pure arithmetic, appendix A):

| true strip rate | P(a block of 10 has ≥ 3 clears) | P(some block passes within 20 blocks) | within 50 blocks |
| ---: | ---: | ---: | ---: |
| 4 % | 0.62 % | 11.7 % | 26.8 % |
| 10 % | 7.0 % | 76.7 % | 97.4 % |
| 20 % | 32.2 % | ≈ 100 % | ≈ 100 % |

The rule measured persistence, not competence. Two further facts constrain any repair:
- the block outcomes came from a policy that changed every 5,120 transitions, so they were never i.i.d. draws of one
  policy;
- nothing re-tested the sections behind the pointer.

---

## 2. The primary change: the controlled frontier rule `m9_g2_frontier_v1`

### 2.1 Definitions (unchanged from g1 unless marked **new**)

- **Pointer τ\*.** Starts at 2,300, moves back in steps of 20 ticks, and never moves forward.
- **Strip.** The strip is [τ\*, τ\* + 20).
- **Start mix.** 50 / 30 / 20 % from the strip, the near window and rehearsal, as g1 (R2).
- **Counted strip outcome.** A completed training episode whose start was drawn from the strip under the *current*
  pointer, as g1. Stale outcomes are logged and still used by PPO, as g1.
- **Landing states.** L = {2,128, 1,966, 1,694, 1,473, 1,369, 1,248}: the first ticks of the trunk's grounded segments,
  as registered in g1.
  - **New:** L is now also used by the re-check.
  - L never enters reward, observation or action (section 9).

### 2.2 The rule

**Trigger (screening, new).**
- The trigger fires when, among the first 20 counted strip outcomes since the latest of (the last move, the last attempt
  at this pointer, the session open), at least 8 are clears (40 %).
- These outcomes come from a changing policy, so the trigger is **not** part of the error control. It only decides when
  a test is worth running.
- It also makes "sustained" concrete: 20 outcomes span several PPO updates (in g1, 20 counted outcomes took 1-20+
  rollouts).

**Attempt (new).** At the next rollout boundary after the trigger (right after the PPO update):
1. **Freeze a snapshot.** The current policy's weights become the snapshot; their digest is recorded. Training
   pauses:
   - the four in-flight training episodes stay parked at `WaitingForAction`, so no tick passes;
   - the six other slots run the attempt;
   - any staged training starts in those slots are withdrawn and recorded. Their keys are never reused.
2. **Strip test.**
   - Up to 20 probe episodes, starts keyed uniformly over the strip's 20 ticks (lineage as g1 R2).
   - Sticky p = 0.25. Actions sampled from the snapshot by keyed inverse-CDF, as in the M9-g1 checkpoint evaluation.
   - **Pass at the 10th clear; fail at the 11th non-clear** (curtailed: same error rates as "≥ 10 of 20", fewer
     episodes).
3. **Re-check of every later landing.** Only if the strip test passes.
   - For every λ ∈ L with λ ≥ τ\* + 20 (every landing the frontier has fully passed), the same test from the trunk's
     own state at λ: up to 20 sticky episodes, pass at the 10th clear.
   - The landings run in parallel. The attempt fails at the first landing that fails.
4. **Move iff** the strip test and every re-check pass: τ\* ← τ\* − 20. The trigger window restarts at the new strip.
5. **Resume training.** Probe transitions never enter PPO; the probe's wall time counts toward the training wall cap.

**Bounds (new).** Every attempt counts, pass or fail.
- **HELD.** After 3 failed attempts at one pointer in one session, no further attempt is made at that pointer in that
  session. Training continues; the pointer stays.
- **STALLED.** After 6 failed attempts at one pointer over the whole line, the pointer is stalled. Training ends as a
  registered valid end, the close audit runs, and the line ends (section 6.5).

**Keys (Python-side sha256 uniforms; no native RNG anywhere).**
- Probe start: `m9|g2|probe|<τ*>|<a>|<part>|<k>`, where a is the line-wide attempt index at that pointer and part is
  `strip` or the landing λ.
- Sticky draw: the same key extended by `|<tick>`.
- Action sampling: `m9|g2|probeact|<τ*>|<a>|<part>|<k>|<tick>|<stick or button>`.

### 2.3 Error rates (exact binomial; appendix A)

**Per test (strip test or re-check), 20 episodes, pass at 10 clears:**

| true clear rate p | 0.10 | 0.15 | 0.20 | 0.25 | 0.30 | 0.40 | 0.50 | 0.60 | 0.70 | 0.80 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| P(pass) | < 0.0001 | 0.0002 | 0.0026 | 0.0139 | 0.048 | 0.245 | 0.588 | 0.873 | 0.983 | 0.9994 |
| expected episodes (curtailed) | 12.2 | 12.9 | 13.7 | 14.6 | 15.5 | 17.0 | 17.3 | 16.1 | 14.2 | 12.5 |
| P(trigger), 8 of 20 (screening only) | 0.0004 | 0.006 | 0.032 | 0.10 | 0.23 | 0.58 | 0.87 | 0.98 | 0.999 | 1.0 |

**What the bounds buy:**

| question | value |
| --- | --- |
| false move at a strip whose true rate stays at p, across all **6** attempts of the line | p = 0.25: ≤ 8.0 %; p = 0.20: 1.6 %; p = 0.15: 0.15 %; g1's unbacked rates (≤ 12 %): ≤ 0.03 % |
| the same, within one session's 3 attempts | p = 0.25: 4.1 %; p = 0.20: 0.8 % |
| a competent strip held back for a whole session (3 failed attempts) | p = 0.5: 7.0 %; p = 0.6: 0.2 %; p = 0.7: < 0.001 % |
| all re-checks pass, k later landings each at p | p = 0.6: k = 1, 2, 3 → 0.87, 0.76, 0.66; p = 0.7: 0.98, 0.97, 0.95; p = 0.8: ≥ 0.998 |
| a later landing that has decayed to 20 % passes its re-check | 0.26 % per attempt |

**How to read these numbers:**
- The bar is the gate's own: 10 of 20 sticky clears, i.e. 50 %.
- Moves happen at strips that clear about 50-60 % or more, and almost never at the 3.5-12 % strips that g1 passed.
- Bounding the attempts is what turns a per-test error into a per-move error. g1 had no bound.
- The re-checks are deliberately strict when later landings are only at about 60 %: the frontier then waits for the
  late route to consolidate. "The pointer means reach" costs that time.
- The strip test already includes the whole later route as the policy itself traverses it, because a strip episode
  counts only if it clears. A move therefore cannot hide forgetting of the policy's own completion. The re-checks add
  the trunk's own landing states, which are what the reach measure uses.

### 2.4 Cost in episodes

**Cost model.**
- When the trigger fires, the strip is at about 55 %: P(pass) ≈ 0.73, about 1.4 attempts per move, about 16.7
  episodes per strip test.
- Later landings are at about 75 %: about 13.4 episodes per re-check, run only after a strip pass.
- k(τ\*) = the number of landings ≥ τ\* + 20: 0 for τ\* ≥ 2,120, then 1, 2, 3 as 2,128, 1,966 and 1,694 fall behind.
- Probe throughput is about 0.5 episodes/s on six slots (g1: 0.70 episodes/s on ten slots in the checkpoint
  evaluation, 0.74 in P4).

| frontier reaches | moves | expected probe episodes (cumulative) | probe wall time (cumulative) | pessimistic (strip at 45 % when triggered) |
| --- | ---: | ---: | ---: | ---: |
| 1,966 (pointer 1,960) | 17 | ≈ 500 | ≈ 15 min | ≈ 850 episodes |
| 1,694 (pointer 1,680) | 31 | ≈ 1,200 | ≈ 40 min | ≈ 2,000 |
| 1,473 (pointer 1,460) | 42 | ≈ 1,900 | ≈ 60 min | ≈ 3,200 |

That is roughly 15-25 % of the training wall time over the line. Strip tests at the first, inherited-motion strips are
nearly free (about 11 episodes at p ≈ 0.9).

**Considered and rejected.**
- *Testing on training outcomes only* costs nothing, but those outcomes are not i.i.d. draws of one policy. That is
  exactly g1's flaw.
- *A cheaper re-check*: 10 episodes, pass at 4. A 20 % landing would then pass with probability 0.12 per attempt, so
  repeated attempts could still hide a decayed landing.
- *A freshness window* (skip a landing re-checked within the last 25,600 transitions) would cut the re-check cost by
  about half. It is left as open question 3.

### 2.5 What the rule does not do

- No retreat: a failed re-check blocks the move but never moves the pointer forward.
- No change to the 50 / 30 / 20 start mix.
- No sampling across all exposed points (the diagnosis's natural *second* lever).
- No tick-0 starts unless the pointer reaches 0, which is outside g2.

When moves are blocked mostly by re-checks, the session record says so: `BLOCKED_BY_RECHECK`, with the landings named.
That is the evidence a later decision about the second lever would need.

---

## 3. Entropy check (coefficient 0.01, your addition to the M7n profile's 0.0)

### 3.1 Magnitudes in the g1 logs (271 PPO updates, `training/rollouts.jsonl`)

| training span | `0.01 × entropy_loss` (mean) | `policy_gradient_loss` (median of the absolute value) | ratio of the two values (median) | rollout entropy (fraction of 4.277) | `value_loss` median (σ_A ≈ √) |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0-205 k | −0.0417 | 0.0056 | 7.6 | 0.976 | 2.90 (1.70) |
| 205-460 k | −0.0401 | 0.0076 | 5.3 | 0.939 | 5.85 (2.42) |
| 460-700 k | −0.0398 | 0.0090 | 4.5 | 0.931 | 1.13 (1.06) |
| 700 k-1.0 M | −0.0393 | 0.0084 | 4.7 | 0.920 | 0.91 (0.96) |
| 1.0-1.4 M | −0.0397 | 0.0107 | 3.7 | 0.927 | 0.32 (0.57) |
| all | −0.0400 | 0.0083 | 4.8 (p10 3.2, p90 7.6) | min 0.903 at 486,400; final 0.916 | 1.42 (1.19) |

**These are loss values, not gradients.**
- The policy-gradient loss value is near zero by construction: advantages are normalised per minibatch (SB3's default)
  and the probability ratio starts at 1.
- The entropy value is about the entropy itself.
- "The entropy term is about 5 times the policy-gradient term" therefore says nothing about which term moved the
  weights.

**The comparison that matters, at the gradient.**
- At one state, for one action head, the expected policy-gradient push on the logits is π_a·(Â_a − Ā). The entropy
  push is −c·π_a·(log π_a + H).
- They balance at **π ∝ exp(Â / c)**, with Â the *normalised* advantage.
- g1's rollout-average entropy of 90-92 % is a KL from uniform of 0.34-0.43 nats. At equilibrium that corresponds to an
  action-advantage spread of about c × 0.9 ≈ **0.009 normalised units**.
- In return units (× σ_A ≈ 0.6-1.2), that is about **0.005-0.011**: below 0.1 % of the clear-versus-fall difference
  (about 16).

So, in expectation, the bonus can only keep near-uniform the ticks where one action's effect on the return is below
about 0.01. Any decisive tick (a jump, an up-B, the drop off the floor) carries an effect orders of magnitude larger,
where the bonus is negligible. The bonus holds the many low-stakes ticks diffuse.

### 3.2 What the records show

| evidence | reading |
| --- | --- |
| g1's rollout entropy fell 99.8 → 90.3 % by 486,400 transitions, then **stayed at 90.7-94.8 %** from 700,000 to the end, while the pointer stood at 2,000 / 1,980 (the same states) | a plateau, consistent with the bonus setting a floor at the visited states |
| M7n's v3 runs, same network, same normalisation, entropy coefficient 0: 82-88 % at 409,600; 61-72 % at 1,024,000; **50-58 % at 1,396,160**; 32-46 % at 3,072,000. g1 at the same points: 94 %, 94 %, 92 % | with no bonus, the same architecture kept sharpening. Confounded: tick-0 starts, denser right-side rewards, no sticky actions |
| g1 per-segment entropy at the final checkpoint (`part_a_values.json`): the never-trained segments 0-1,247 and 1,248-1,693 drifted to 78 % and 84 %, while the trained left-side segments stayed at 90 % | only where the bonus acts (visited states) does the entropy stay at 90 % |
| at 2,128, the checkpoint that cleared **9 of 20** (409,600) had handover entropy **97 %** and a top-word probability of 4.0 % (uniform: 1.4 %) | near-maximum entropy did **not** prevent the skill |
| the final checkpoint at 2,128 had 88 % and top word 12.9 %; at 2,250, 78 % / 17.2 % (from 96 % / 4.8 %); both at **0 of 20** | the forgetting was the policy becoming **sharper and wrong**, which the bonus resists rather than causes |
| per-update policy movement: g1 median approx_kl 0.0084, clip fraction 0.064; M7n 0.0098-0.0100 and 0.10 | g1's updates moved the policy slightly less; consistent with a weaker signal, not decisive |
| argmax episodes failed in every cell where the sticky policy cleared 5 or more (diagnosis, H2 premise) | the g1 policy's competence lived in a diffuse distribution, not in its mode |

### 3.3 Verdict and recommendation

- **Did the bonus plausibly keep the policy near random?** In the average-entropy sense, yes. A floor near 90 % at
  visited states is the most economical reading of the plateau and of the M7n contrast.
- **Was that why g1 failed?** No. The NULL is explained by H3 → H1. Competence existed at 97 % entropy, and the loss
  happened while the late states became sharper.
- **Was the budget simply too small?** Partly. g1 trained 1.4 M transitions; M7n's sharpening ran over 3 M. The gate
  needed 18 of 20 at 2,128, and the best checkpoint had 9.
- **Can the records decide whether 0.01 helps or hurts the reliability g2 needs** (about 15 of 20 at 2,128 against the
  tape, and eventually 50 of 100 from tick 0)? **No.** Nothing in g1 varies the coefficient.

**Recommendation: keep 0.01, fixed for the whole g2 line.** Reasons:
- It keeps g2 at exactly one change against g1, so the frontier rule's effect can be attributed.
- The controlled frontier makes the policy **dwell** much longer at each strip. That is where a bonus-free policy is
  most likely to sharpen prematurely. The project's own M7m stall was linked to low-entropy, anti-aligned priors at the
  frontier (0.74-1.17 nats). Salimans & Chen also needed an entropy bonus for the backward algorithm.
- g1 shows no harm.

**If you prefer to revert anyway,** that is the removal of your addition, back to the M7n profile's 0.0, not a second
change. It must be decided before g2-s1, because resume refuses any PPO change mid-line (M7b's rule, kept for the line).

**Registered reading (never deciding):** per checkpoint, the entropy and top-word probability at the strip's trunk
states and at every landing, computed as the diagnosis computed them.

---

## 4. Value collapse: why V(2,300) = −3.96 when the policy clears 10 of 10 there

### 4.1 The critic was mostly right

Critic value at the trunk state against the realised mean return of the 20 sticky episodes from that state, both read
from preserved records:

| start | checkpoint | V(trunk state) | realised mean return | outcomes |
| ---: | --- | ---: | ---: | --- |
| 2,128 | 409,600 | +1.73 | +2.05 | 9 clears, 10 falls, 1 horizon |
| 2,128 | 614,400 | −2.69 | −2.72 | 3 / 14 / 3 |
| 2,128 | final | −2.28 | −3.49 | 0 / 9 / 11 |
| 2,250 | final | −2.44 | −4.38 | 0 / 15 / 5 |
| 2,275 | final (fine grid, 10 episodes) | −3.76 | −1.98 | 2 clears of 10 |
| **2,300** | final (fine grid, 10 episodes) | **−3.96** | **+10.98** | **10 of 10** |

- At the landings the critic tracked the policy's **real** decline (H1). The values of −2 to −3 at 2,128-1,966 are not
  a critic failure.
- The gross error is at the very end. There the last 26 ticks are inherited motion: the **untrained** policy also
  cleared the 2,300 strip 10 of 10 (g1 block 0), and from 2,275 the final clears only 2 of 10.
- The policy's choices at 2,300 barely matter.

### 4.2 Why 2,300 is wrong: data, plus generalisation

- **Late training data was dominated by failing post-target-8 episodes.** In g1's windows 3-5 (457 k-1.33 M
  transitions), policy ticks after target 8's break (8 broken, 1 standing) were 32-39 % of all policy ticks. **81-90 %
  of them belonged to episodes that did not clear** (window 2: 77 %).
- **Near-terminal states were nearly absent.** About 4 in 500 starts at or after 2,300 in window 5, and 43-56
  arrivals per 500 episodes.
- **So the critic regressed them toward the neighbourhood mean.** It shares one 64×64 network across all start
  points. It regressed the nearly unseen near-terminal states toward their abundant neighbours: same live-target mask,
  the same side of the stage, a nearby clock, and a realised return of about −3 to −4.
- **Late values were unconstrained.** V(2,300) swung by up to 14 between neighbouring checkpoints (9.52 at 1,331,200,
  then −3.96 at the final).

### 4.3 The candidate causes the request names

| candidate | role |
| --- | --- |
| reward v2 terms | sets the **level** of the neighbourhood mean: the −5 fall dominates it. Not the mechanism; the target at 2,300 (+10.97) is unambiguous |
| interference across start points | **yes**, in the function-approximation sense above. The critic is shared and late states were rare |
| the time horizon | not at 2,300. Noted for completeness: v3 observes the clock (`time_passed / 3,600`), yet horizon endings are bootstrapped (`TimeLimit.truncated`, SB3 adds γ·V(terminal observation)). That is inherited M7 behaviour, and it touches only horizon endings (30 of g1's last 64 episodes, on the floor). Left unchanged (open question 13) |
| γ / λ | with γ 0.999 and λ 0.995 the advantage is nearly the Monte Carlo return minus V(s_t). A wrong late V is therefore mostly a **wrong baseline**: added variance, not bias. The value collapse is a symptom of the data distribution, not a separate cause of the forgetting |

### 4.4 Does g2's primary change fix it?

**Expected to remove the cause, not guaranteed.**
- The pointer cannot advance until the strip clears about 50 % on a frozen probe, and every attempt re-checks the later
  landings. So post-target-8 practice should stay mostly in successful episodes, the opposite of g1's 81-90 %
  failures.
- **No second change is proposed.** Nothing in g1 shows g2 cannot work without one.

**Registered diagnostic (never deciding):** at every attempt, the snapshot's V at each tested start state against that
test's realised mean return (the calibration gap), per landing; and the share of post-target-8 ticks in clearing
episodes per 100 training episodes.

---

## 5. A steadier tape baseline, `m9_g2_tape_baseline_v1`

**What g1 showed.**
- The tape is a deterministic function of the words and the keyed sticky mask. Its clear rate at a landing is a fixed
  property, and 20 keys measure it poorly.
- At 2,128: 13 of 20 under P4's keys and 6 of 20 under the evaluation's.
  - Fisher's exact test: p = 0.056, consistent with one rate.
  - Pooled: 19 of 40 = 0.475 (Wilson 95 %: 0.33-0.63).
- Under g1's rule, the bar at 2,128 (tape + 5) would have been anywhere from **11 to 18** depending on the key set.
- At the five deeper landings the tape cleared 0 of 20 everywhere.
- **Pairing buys little.** In the checkpoint evaluation (identical keys), joint policy-and-tape clears at 2,128 were 4
  against 2.7 expected under independence for the best checkpoint, and none for the others.

**The baseline.**
1. **Measured once, in g2-s1, before training** (phase T0).
   - Keys `m9|g2|reach|<λ>|<k>`: k = 0..199 at 2,128 and k = 0..39 at each of 1,966, 1,694, 1,473, 1,369 and 1,248.
     That is 400 tape episodes, T_clear's words, sticky p = 0.25.
   - The per-key outcomes and their digest are pinned in a table that every later session reads by digest.
   - With 200 keys, the standard error at 0.475 is 0.035. With 0 of 40, the 95 % upper bound is 7.2 %.
2. **Claimed tape clears count**, the strict side, as g1 R11. A keyed sample of 10 tape clears is replayed in s1; an
   inexact one is INVALID.
3. **Every later session re-runs 5 keyed tape episodes at 2,128** at the open and requires identical outcomes and record
   digests. This is a drift check; the baseline itself is never re-measured while the executable, the T_clear words and
   the sticky rule are unchanged.
4. **The policy side uses the same key family.** The close audit evaluates the policy at keys k = 0..19 of
   `m9|g2|reach|<λ>|<k>` in **every** session. Sessions are therefore paired with each other, and the first 20 tape keys
   with the policy's 20.

**The margin test.** Decision 3 is kept, "at least 10 of 20, and at least 5 more than the tape", with the tape's count
replaced by its pinned expectation on 20 episodes:

```text
B(λ) = max(10, ceil(20 · p̂_tape(λ)) + 5)        landing λ counts for R iff c_policy(λ) ≥ B(λ) (verified sticky clears of 20)
```

- At 2,128 with p̂ ≈ 0.475, **B = 15**. With 200 keys, B lies in 14..16 over p̂'s 95 % range.
- A policy no better than the tape passes there with probability **1.2 %**. A policy at 75 % passes with 62 %; at
  85 %, with 93 %.
- At landings whose tape rate is at most 25 %, B = 10.

**Cost.** Up to 400 episodes, about 9-12 minutes (P4 ran 140 tape episodes in 190 s). The T0 cap is 15 minutes,
1,500,000 native ticks. It runs in s1 only.

---

## 6. Resumable training: the g2 line

### 6.1 The session envelope (every session needs its own approval)

| phase | content | wall cap | native ticks cap |
| --- | --- | ---: | ---: |
| S0 (before the clock) | unit suite (three consecutive passes when the code is new or changed), rule self-tests, static guards, preflight, approval | | 0 |
| open | identities; for s ≥ 2, the input checkpoint and curriculum-state digests named by the approval; every earlier g2 session tree equal to its D: increment | 1 min | 0 |
| P1 | both routes replayed 3 times each, as g1; chain and v3 tables equal to the pinned registration | 4 min | 60,000 |
| P2 | 12 keyed staging-equivalence starts, as g1; for s ≥ 2, also the 5-key tape drift check | 2 min | 60,000 |
| T0 (s1 only) | the tape baseline (section 5) | 15 min | 1,500,000 |
| **training** | PPO with the controlled frontier; attempts pause training at rollout boundaries and **count toward this wall** | **80 min** | 20,000,000; ≤ 3,072,000 transitions |
| close audit | frozen final policy at every landing from 2,128 to one landing beyond the frontier, each with 20 sticky, 20 unperturbed (diagnostic) and 1 deterministic; tick 0 with 20 sticky and 1 deterministic (descriptive) | 20 min | 3,000,000 |
| verification | every close-audit clear; the first 20 training clears; one keyed clear per passed test of every move; in s1, 10 keyed tape clears | 10 min | 1,500,000 |
| close | executable and frozen-config identity, write guard, metadata audit, earlier trees unchanged, no leftover process | 5 min | 0 |
| **session hard cap** | | **145 min** | |

**Wall time and throughput.**
- The sum of the caps is 137 minutes in s1 and 122 minutes later. Expected: about 125 minutes in s1 and 110 minutes
  later.
- P3 is dropped (section 8).
- Training transitions per session: g1 ran at 283, 447 and 574 transitions/s as the frontier moved back. Expect about
  1.6-2.2 M per session after probe pauses.
- **Resources:** rd4's and g1's memory caps; at most 10 BattleShip processes; 4 + 6 slots.
- **Stops:** as g1. A stop keeps everything written and relaunches nothing.
- **Backup.** At every session close, after the session clock as in g1: the D: increment
  `D:\BattleShip_runs_backup\<date>_incr_m9_g2_s<k>`, tool backup and verify, an independent PowerShell re-hash, and
  `runs/` coverage back to 0 uncovered. The next session's approval refuses to be written until this is recorded.

### 6.2 Checkpoint, optimizer and curriculum continuity

**Saved at every checkpoint** (every 102,400 transitions and at the end of training):
- `model.zip`: SB3 policy weights **and the Adam state**, including step counts (`policy.optimizer.pth`).
- `curriculum_state.json` (new):
  - the pointer, the move history and the attempt history with both counters per pointer;
  - HELD and STALLED flags;
  - the global episode and attempt counters;
  - the tape-baseline and contract digests;
  - the task block and `created_utc`.
- `checkpoint.json`: pins the sha256 of `model.zip`, of its optimizer member and of the curriculum state.

**Resume (session k ≥ 2).**
- The approval names s_{k−1}'s final digests. The session copies those files into `runs/m9_g2/s<k>/input/` and checks
  them.
- It loads with `PPO.load` (no fresh initialisation) and asserts that `num_timesteps`, `n_updates` and every
  parameter's Adam step count equal the saved values.
- It continues with `learn(reset_num_timesteps=False)`.
- The Python/SB3 training seed is `1000 + k` (recorded; a Python-side training seed, as in M7b). The action-sampling
  stream is not continuous across sessions, and nothing depends on it being so.

**Carried / not carried.**
- **Carried:** weights, optimizer state, pointer, attempt counters, flags, global counters, the pinned tape table.
- **Not carried:**
  - in-flight episodes, which are abandoned at the end of training: neither outcomes nor transitions; the partial
    rollout is discarded, as in g1;
  - staged starts;
  - the trigger window, which restarts at each session open: conservative, about one minute.
- **Keys never repeat:** training starts are keyed by the global episode number, and probe keys by the line-wide attempt
  index.

**Compatibility.** The line's contract digest is fixed in s1: observation, reward, action, PPO values, sticky p,
curriculum constants and the frontier rule. A resume refuses any change to it, or to the executable. This is M7b's rule,
applied to the line. A code-defect fix between sessions is allowed only if the contract digest is unchanged; it reruns
the unit suite three times and takes a new snapshot, and it is recorded in the session's decisions record.

**Zero-tick tests (new).**
- A save/load round trip is bit-equal: weights, Adam moments and step counts.
- One update on a fixed synthetic batch after a reload equals the same update without the reload (CPU, one thread). The
  M7m pilot showed the analogous property: Adam step 60,000 → 60,800 on every parameter.
- The curriculum-state round trip is exact.
- Resume refuses a changed contract digest, executable, PPO value or input digest.
- A synthetic two-session line rebuilds the whole pointer and attempt history from the records alone (`verify-run`).

### 6.3 Pinned identities per session

The approval names:
- the source snapshot digest;
- the executable, the frozen runtime config and the two route digests;
- the line contract digest, the frontier rule and the rule digests (`m9_g2_s1_rule_v1`, `m9_g2_line_rule_v1`);
- the code fingerprint;
- for s ≥ 2, the input `model.zip`, optimizer-member and curriculum-state digests, the tape-table digest, and the
  earlier sessions' D: manifest digests.

Each session writes only `runs/m9_g2/s<k>/`, and the write guard covers every other tree, including earlier g2 sessions.

### 6.4 The per-session progress measure

Both measures come from the close audit of session k's frozen final policy on the fixed keys, counting replay-verified
sticky clears of 20:

| measure | definition | role |
| --- | --- | --- |
| **D_k, sustained frontier depth** (registered progress measure) | the earliest λ ∈ L such that, at λ and at every later landing, the policy clears **≥ 10 of 20** | what the frontier demonstrably holds at the session's end, on the trunk's own states |
| **R_k, reliable reach** (g1's measure) | the same, with **≥ B(λ)** (section 5) | "a policy, not a tape"; decides s1 PASS and is reported every session |

- R_k is never earlier than D_k.
- **Reported: `FRONTIER_BACKED`** if every landing ≥ τ\*_k + 20 passes the 10-of-20 bar at the close, else
  `FRONTIER_AHEAD`. FRONTIER_AHEAD is the signature of a move that hid forgetting by the session's end, the failure the
  rule exists to prevent.

### 6.5 The stop budget, `m9_g2_line_rule_v1` (checked at every session close, in order)

| line outcome | condition |
| --- | --- |
| **SUSPENDED (review)** | the session is INVALID; or two consecutive sessions are INCOMPLETE. No next session until repaired and re-approved |
| **END_NULL_S1** | g2-s1's outcome is NULL (section 7) |
| **END_STALLED** | some pointer has 6 failed attempts |
| **END_SUCCESS** | D_k ≤ 1,473: "crossing learned", g2 complete. The right side and the claim (g3) need a separate proposal |
| **END_BUDGET_1966** | k = 3 and D_3 is later than 1,966 (none, or 2,128): no sustained progress through the first left-floor landing after **N = 3** sessions |
| **END_NO_PROGRESS** | k ≥ 4 and D_k is not earlier than D_{k−2}: no new landing in two sessions |
| **END_CAP** | k = 8 without END_SUCCESS |
| CONTINUE | otherwise: session k + 1 is proposable, with its own approval |

**Counting INCOMPLETE sessions.** An INCOMPLETE session counts toward k only if its training reached at least 50 % of
its wall cap.

**Why N = 3 (and the later rules), from the diagnosis's budget estimate:**

| target | route ticks from the end | at the diagnosis's measured rate (≈ 200 ticks to 45 % in 0.41 M) | doubled for the controlled 50 % bar | sessions at 1.6-2.2 M per session |
| ---: | ---: | ---: | ---: | ---: |
| 2,128 | 198 | 0.4 M | 0.8 M | within s1 |
| **1,966** | 360 | 0.7 M | 1.4 M | **s1 (s2 if the target-8 climb is harder)** |
| 1,694 | 632 | 1.3 M (the diagnosis: 1.5-3 M) | 2.5-6 M | s2-s4 |
| 1,473 | 853 | 1.7 M, plus the crossing flight | 4-8 M | s3-s5 or later |

- **N = 3** gives 1,966 two to three times its estimated time. Missing it means a rate below a third of the estimate,
  which projects tick 0 (2,326 route ticks, with the platform twice) to weeks.
- **"A new landing every two sessions"** is a floor of about 80-136 route ticks per session. The landings are 104-272
  ticks apart; at that floor, tick 0 is still about 20-30 sessions away, consistent with the diagnosis's "days".
- **The cap of 8** is about 1.5-2.5 times the estimate for 1,473. The crossing flight (an up-B at the right moment) is
  the strongest stall candidate on the evidence of M7m's W2.

**What each line outcome leads to.** Nothing follows automatically.
- END_SUCCESS → a g3 proposal.
- Any other END → a review. The candidates are: the second lever (start sampling across exposed points) if the record
  shows `BLOCKED_BY_RECHECK` or `FRONTIER_AHEAD`; lineage diversity (M8-rd5) if the stall is at the crossing; or a stop.

**Odds (subjective, for planning only):**
- D ≤ 1,966 by s3: 50-65 %;
- D ≤ 1,694 by s5: 30-45 %;
- END_SUCCESS within 8 sessions: 15-25 %.

---

## 7. The first session's rule, `m9_g2_s1_rule_v1`

g2-s1 trains a **fresh** policy: seed 0, the M7n v3 network, ent_coef 0.01. With the same code path its untrained
weights should equal g1's `ckpt_000000000` (`16dc29c9…`); that equality is reported, never deciding. s1 runs the full
envelope of 6.1, including T0. It is evaluated in this order; the first that holds is the outcome.

| outcome | condition |
| --- | --- |
| **INVALID** | any integrity or compliance failure (list below). *Repair and a new approval; never a retry* |
| **INCOMPLETE** | P1, P2 or T0 not passed; training ended before a valid end (80-minute wall including probes, the tick cap, the transition cap, or STALLED); the close audit is incomplete at any landing D₁ or R₁ needs; T0 is incomplete at a landing whose B(λ) is needed; an unverified close-audit clear could change D₁ or R₁. *Not a performance result* |
| **PASS** | **R₁ ≤ 1,966**: from the first left-floor landing, the frozen policy reliably completes the target-8 climb, the second floor and the final drop, at ≥ 10 of 20 at 1,966 and ≥ B(2,128) (about 15 of 20) at 2,128 |
| **INCONCLUSIVE** | not PASS, and **D₁ ≤ 2,128**: sustained competence of at least 10 of 20 at the last landing (g1's final had 0, its best checkpoint 9), short of the PASS reach |
| **NULL** | **D₁ = none**: not even 10 of 20 at 2,128. g1's failure repeats under the controlled rule |

**INVALID conditions:**
- a prefix, chain, handover or v3 mismatch;
- a verified-sample or counted clear that fails exact replay;
- executable or frozen-config drift;
- a start outside the two routes;
- any read of fixtures, the TAS or recordings;
- a sticky, start, action-sampling or probe draw not reproducible from its key;
- **a pointer move without a recorded passing attempt** (strip and every re-check, rebuilt by `verify-run` from the
  records);
- **more attempts at a pointer than the bounds**;
- a tape-table digest mismatch;
- a write outside `runs/m9_g2/s1/`;
- an approval or snapshot identity mismatch.

**What s1's outcome leads to:**
- PASS or INCONCLUSIVE → s2 is proposable: resume from s1's final under 6.2.
- NULL → END_NULL_S1, a review.

**Reported, never deciding:**
- the pointer trace and every attempt (cause of failure: strip or re-check, with the landing named); HELD / STALLED;
  FRONTIER_BACKED;
- R_unperturbed, deterministic results, tick 0;
- the entropy readings (3.3), the critic calibration gap and the post-target-8 success share (4.4);
- the handover diagnostic;
- throughput, including the probe share; native ticks split into prefix, policy and probe.

**Odds (subjective):** PASS 20-30 %, INCONCLUSIVE 45-55 %, NULL 20-30 %.

---

## 8. Unchanged from g1, and the few operational differences

| item | g1 | g2 | why |
| --- | --- | --- | --- |
| observation / reward | v3 entities / v2 rebased at the handover | same | — |
| policy | fresh, seed 0 | fresh in s1, then resumed | the line |
| PPO | M7n profile + ent_coef 0.01 | same (recommended, section 3) | — |
| sticky actions | p = 0.25 in training and every evaluation | same | — |
| routes | the two verified rd4 clears, start states only, no imitation | same | — |
| curriculum constants | pointer 2,300, strips of 20, mix 50 / 30 / 20, stale rule, never forward | same | — |
| **frontier move rule** | ≥ 3 of 10 per block, unlimited retries | **controlled, section 2** | **the change** |
| process split | P3 measured 4 + 6 against 2 + 8 (1.012×, below the 1.10 rule) | **fixed 4 + 6; no P3** | the answer is known; P3 cost 4 minutes and 549,000 ticks |
| landing states | evaluation and rule only | also the re-check | section 2.1; compliance, section 9 |
| reach thresholds | 10 of 20, tape + 5 (20-key tape, paired) | same thresholds, **pinned tape** (section 5) | a steadier control |
| evaluation keys | fresh per gate | **identical across sessions** | pairing across sessions |
| verification | every reach and P4 clear; first 20 training clears | every close-audit clear; first 20 training clears; one keyed clear per passed test of a move; 10 tape clears in s1 | probe clears are too many to replay all (about 2,000 ticks each); every staged tick is chain-checked anyway |
| session | one 130-minute session, 60 minutes of training | a line of sessions: 145-minute cap, 80 minutes of training | item 5 |
| final claim | defined (50 / 100 unperturbed, 50 / 100 sticky, tape + 25), not tested | same, not tested | — |
| metadata | top-level task block and `created_utc` at the source; the writer refuses without them | same, including probe records and `curriculum_state.json` | — |
| v4 fallback | evidence-triggered (handover ratio ≥ 2 at a stall) | not triggered (g1: about 1.0); stays a fallback | — |

---

## 9. Compliance

| constraint | how g2 meets it |
| --- | --- |
| no native RNG seed inspection, logging, control, comparison or hashing | every draw (start, sticky, probe, evaluation action sampling, tape keys) is a Python-side keyed sha256 uniform. PPO / SB3 seeds are Python-side training seeds, as in M7b |
| process restart resets the episode | one fresh process per episode: training, probe, re-check, tape and audit, prefix included; never reused. Pausing training parks processes at `WaitingForAction`; nothing is reset in-process, and there is no save state |
| the exact submit / consume / input-tick contract | unchanged: prefix word i consumes tick i, and the policy's first word consumes tick τ. A process parked during an attempt consumes nothing until its next word |
| canonical controller words, no hidden actions | every episode (probes included) is stored as canonical words from tick 0: prefix words, then the **submitted** words. Sampled words and sticky masks are metadata |
| human crossing recordings and the TAS are validation-only | never read. The static source guard of g1 is kept. The TAS appears only as the number 446 in section 10 |
| no hardcoded routes or waypoints | start states are prefixes of the agent's own verified routes, as in g1. **New:** the landing states now gate pointer moves. They are computed from the agent's own trunk by a generic rule (the first tick of each grounded segment), never authored, and never enter reward, observation or action. They decide only *when* the start window moves, not where the agent goes. Open question 5 offers fixed-spacing re-check points instead |
| non-PORT decomp and byte-matching behaviour preserved | no native, decomp or submodule change. Executable `30a3913b…` with the existing read-only diagnostics |
| rebuilt executable | suspends every lineage claim and the tape table until re-verified from tick 0; a mismatch stops for review |

---

## 10. The alternative next step: archive search for shorter clears (short)

**What it would be.** A time-directed continuation of archive `m8_rd_a1` (37,312 cells, one trunk, best clear 2,314
ticks):
- keep the **earliest-arriving** trajectory per cell;
- select cells by time saved against the best known arrival, plus progress;
- the candidate rule is a verified clear with a smaller `completion_input_tick`.

The 7.43 s TAS stays a number to beat (446 ticks), never words, starts or segments. This is a new design: rd4's rule
targets milestones, not speed, and rd5 is permitted but unstarted.

| | M9-g2 line | archive search for shorter clears |
| --- | --- | --- |
| track it serves | Track 1: a policy, eventually the tick-0 claim | Track 2: trajectories, faster verified clears |
| first answer | g2-s1: about 2 hours plus preparation | one M8-style session: about 1 hour, 3-6 M native ticks (rd4: 55 minutes, 5.65 M) |
| total to a meaningful result | to 1,473: 3-8 sessions (about 6-19 hours); tick 0: days | 1-3 sessions |
| odds (subjective) | D ≤ 1,966 by s3 50-65 %; D ≤ 1,473 in 8 sessions 15-25 %; the eventual M9 claim on this single lineage about 10-15 % | a verified clear ≥ 10 % shorter within 2 sessions 60-75 % (the route has 407 word changes, many of them no-ops; the right side alone spans 11 grounded segments before tick 1,248); ≤ 1,160 ticks (2× faster) 15-30 % (needs a different right-side order or crossing); **446 ticks: about 0 by this method** (Track 1's nine stick states and random bursts; that is M11's raw-word polishing) |
| what it does to the other | g2 does not shorten the route | a shorter clear shortens every M9 prefix (staging cost ∝ τ) and the route to robustify. An independent crossing would address M9's main risk (one lineage), but the archive's history (every over-wall cell descends from one trunk) makes that unlikely without a diversity objective |
| main risk | a stall at the crossing; one lineage; forgetting surfacing as BLOCKED_BY_RECHECK | gains stay on the right side; no new crossing lineage |

In one line: g2 is the only one of the two that advances the M9 claim. The archive search is cheaper, likelier to
produce a verified result soon, and would make later robustification cheaper. You decide the direction.

---

## 11. Implementation outline (new files only; a separate authorisation)

| file | contents |
| --- | --- |
| `rl/m9_g2_contract.py` | constants, keys, bounds, caps, the line contract digest |
| `rl/m9_g2_frontier.py` | trigger window, attempts, HELD / STALLED, the move decision, rebuild from records |
| `rl/m9_g2_probe.py` | frozen-snapshot test runner on six slots (reuses `rl/m9_eval_policy.py` keyed sampling and the g1 staging and free-running runner, read-only) |
| `rl/m9_g2_train.py` | the PPO driver with the attempt hook at rollout boundaries, checkpoints with `curriculum_state.json` |
| `rl/m9_g2_resume.py` | save / load / continuity assertions |
| `rl/m9_g2_tape.py` | T0, the pinned table, the drift check, B(λ) |
| `rl/m9_g2_rule.py` | `m9_g2_s1_rule_v1`, `m9_g2_line_rule_v1`, D_k, R_k, the self-tests |
| `rl/m9_g2_session.py`, `rl/m9_g2_tests.py` | CLI (preflight, approval, run, verify-run, report); deterministic unit suite and a synthetic two-session end-to-end run |

- `rl/m9_*.py` and `rl/m9_eval_*.py` are imported unchanged. No inherited file is edited, and g1's trees are read-only.
- **First-contact risks:**
  - parking four training processes during an attempt, typically 30-90 s; M7c standbys wait frozen far longer;
  - the probe's slot sharing with withdrawn staged starts;
  - resume equivalence on the real machine, tested synthetically and asserted at every open.

---

## 12. Open questions

1. **Bar and bounds.** Strip test and re-checks at 10 of 20 (the gate's own bar), with the 8-of-20 trigger; 3 attempts
   per pointer per session, 6 per line, with STALLED ending the line. Accept, or a stricter bar (for example 12 of 20)?
2. **Attempt mechanics.** Pause training at a rollout boundary and run the attempt on six slots (proposed), or probe
   concurrently and accept slower training staging?
3. **Re-check cost.** Every later landing on every attempt (proposed, strict), or a freshness window (skip a landing
   re-checked within the last 25,600 transitions) at about half the re-check cost?
4. **Re-check failure.** Block the move only (proposed), or also move the pointer forward? Retreat would be a second
   mechanism.
5. **Landing states in the frontier rule.** Acceptable as computed decision points (proposed), or fixed-spacing
   re-check points (for example every 100 ticks behind the frontier)?
6. **Entropy.** Keep 0.01 for the whole line (recommended; the evidence cannot decide), or revert to 0.0 now? A revert
   is the removal of your addition, not a second change.
7. **Tape baseline.** 200 keys at 2,128, 40 at the other five landings, measured once in s1; the bar
   `max(10, ⌈20·p̂⌉ + 5)` (about 15 of 20 at 2,128). Accept, or redefine the margin where the tape is strong?
8. **Stop bar naming.** You called 1,966 "the crossing landing". On the trunk, 1,966 is the first *left-floor* landing.
   The crossing flight ends at the wall-top landing, 1,694, and 1,473 is the platform before the launch. Keep the N = 3
   bar at D ≤ 1,966 (proposed), or put it at 1,694?
9. **Line budget.** N = 3; one new landing per two sessions from s4; cap 8 sessions; END_SUCCESS at D ≤ 1,473 with g3 a
   separate proposal. Accept?
10. **Session envelope.** 80 minutes of training (probes included) under a 145-minute hard cap, with T0 in s1. Accept?
11. **Verification sampling.** One keyed clear per passed test, rather than every probe clear?
12. **P3.** Dropped, with 4 + 6 fixed from g1's measurement?
13. **Horizon bootstrapping with an observed clock.** Leave the inherited M7 behaviour unchanged in g2 (proposed), and
    consider it only in a later line?
14. **Direction.** g2, the archive search for shorter clears, or both in sequence (for example one archive session
    first, to shorten every prefix)?

---

## Appendix A. Scratch analyses (read-only; session scratchpad; not preserved)

The scripts lived in the session scratchpad (`…\scratchpad\g2\`). They read preserved JSON and JSONL only, imported
no repository module and loaded no model weights. Per-state entropies and values come from the diagnosis's preserved
`part_a_values.json`.

| script | input | used in |
| --- | --- | --- |
| `logs.py` | `runs/m9_g1/training/rollouts.jsonl` (271 updates); `runs/m7n/campaign/m7n_s{0,1,2}_v3/metrics/rollouts.jsonl`; `runs/m9_g1_eval/eval/episodes.jsonl` (per-key policy / tape pairing); `runs/m9_g1/p4/episodes.jsonl`; `runs/m9_g1/training/episodes.jsonl` (post-target-8 tick shares per 500-episode window) | 3.1, 3.2, 4.2, 5 |
| `ent2.py` | the same rollouts; `part_a_values.json` (entropy and top-word probability at the landings) | 3.2, 6.1 throughput |
| `ret.py` | `runs/m9_g1_eval/eval/episodes.jsonl`, `runs/m9_g1/eval/episodes.jsonl` (fine grid), `part_a_values.json` | 4.1 |
| `oc.py` | none: exact binomial arithmetic (curtailed tests, triggers, attempt bounds, g1's block rule, the 2,128 bar, Fisher's test, Wilson intervals) | 1, 2.3, 2.4, 5 |

## Appendix B. Sources

- T. Salimans, R. Chen, *Learning Montezuma's Revenge from a Single Demonstration*, arXiv:1812.03381 (2018): the
  backward algorithm, and an entropy bonus that needed tuning.
- A. Ecoffet et al., *Go-Explore*, arXiv:1901.10995 (2019), and *First return, then explore*, Nature 590 (2021):
  robustification under sticky actions; single demonstrations robustified in 40 % of runs.
- F. Pardo et al., *Time Limits in Reinforcement Learning*, ICML (2018): with time in the observation, a time limit is
  part of the task (section 4.3, recorded only).
- Project records: `docs/rl_m9_g1_diagnosis_2026-10-04.md`, `docs/rl_m9_g1_results_2026-10-04.md`,
  `docs/rl_m9_g1_decisions_2026-10-04.md`, `docs/rl_m9_policy_proposal_2026-10-03.md`,
  `docs/rl_sweep_consolidation_m7m_results.md`, `docs/rl_m8_rd4_results_2026-10-03.md`.
