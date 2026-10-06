# M9-g2 stop review: why g2-s1 ended NULL, what it costs to continue, and a g3 design (2026-10-06)

**Status: stop review and design only.** No native process was launched and no native tick was consumed. Nothing was trained, implemented, committed, pushed
or branched. No existing file, no `runs/` tree and no file outside the repository was changed. The only computations were read-only scratch scripts in the
session scratchpad, outside the repository (appendix A). They read preserved JSON and JSONL records, imported no repository module and loaded no checkpoint
weights. This document is the only file added, and nothing in it is authorised.

| item | state |
| --- | --- |
| checkout | `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, `main`, HEAD = origin/main = `8b7462e`, working tree clean at the start and at the end |
| external guide | `Smash_pc_port/guide.md` (M9 = robustification since 2026-10-04); not edited |
| read | `CLAUDE.md`; the guide; `rl_m8_rd4_results_2026-10-03.md`; `rl_m8_rd_continuation_proposal_2026-10-02.md` (sections 2.5, 7, 10; its "shorter L wins" replacement rule is the only passage about shorter trajectories; the shorter-clears alternative itself is section 10 of the g2 proposal); `rl_m9_policy_proposal_2026-10-03.md`; every `rl_m9_g1_*` document; `rl_m9_g2_proposal_2026-10-04.md`; `rl_m9_g2_decisions_2026-10-05.md`; `rl_m9_g2_implementation.md`; `rl_m9_g2_s1_results_2026-10-06.md`; `rl_m9_g2_s1_approval.json` |
| preserved records analysed | `runs/m9_g2/s1/training/{episodes,rollouts,windows,attempts,probes,moves,stale,withdrawn}.jsonl`, `runs/m9_g2/s1/session/*.json`, `runs/m9_g2/s1/audit/episodes.jsonl`; `runs/m9_g1/training/{episodes,rollouts}.jsonl`, `runs/m9_g1/eval/episodes.jsonl`; `runs/m8_rd_rd4/archive/cells.jsonl`; the tracked `rl/m9_tests.py`, `rl/m9_eval_tests.py`, `rl/m9_g2_contract.py`, `rl/m9_g2_rule.py`, `rl/m9_g2_frontier.py`, `rl/m8_rd4_select.py` (read only) |

## Short answer

1. **Diagnosis (section 1).** The NULL was produced by the mechanism, not by the policy. The pointer moved once (2,300 to 2,280 at training-wall 324 s), three
   frozen strip tests then failed at training-wall 378, 507 and 676 s, and the per-session bound held the pointer for the remaining 4,128 s (68.8 min; 73.8 min
   counted from the first failure). The live clear rate at the held strip rose from 0.39 to 0.91; a 50-outcome rolling rate first reached 0.50 at training-wall
   about 670 s, 0.60 at about 756 s, 0.80 at about 2,100 s. The policy never trained from any state before tick 2,280, and the deciding audit at 2,128 lies 152
   ticks before the first trained state: 0 of 20 there (every episode fell into the pit, mean 514 policy ticks, no target) measures untrained territory. "Inability
   to learn at 2,128" is neither shown nor refuted; "the strip 2,280 was learned" is shown.
   - **The trigger-to-test gap** is selection bias plus small-sample noise. The trigger displays at least 8 of 20 by construction; the live rate around the three
     failed attempts was 0.22 to 0.50; the tests read 0.27, 0.35 and 0.27. Policy change between trigger and test runs the other way (the snapshot is one update
     newer and the rate was rising), sticky draws are identical by construction, and start offsets within the strip explain part of attempt 4 only (it drew none
     of the three easy starts 2,297 to 2,299, probability 8.7 %).
   - A Monte Carlo of the registered mechanism against the observed learning curve gives **a 54 % chance of exactly this outcome** (three failures before the first
     move, then HELD for the session). The rule did what it was designed to do; the design put a hard cap on a resource consumed by a weak screen during the
     one phase where every strip must pass through it, the climb from 30 % to 50 %.
   - **"s1 NULL ends the line"** was registered in the proposal (section 6.5 table and section 7), implemented in `rl/m9_g2_rule.py` (`apply_line`, line rule
     digest `d10d2ad8...` named by the approval) and self-tested as "s1 NULL ends the line". The decisions record accepted "the line budget as proposed" (decision 6,
     which enumerates N = 3, the two-session floor, the cap of 8 and END_SUCCESS) and "the s1 rule as proposed" (decision 7). **Neither decision names
     END_NULL_S1, and open question 9 of the proposal did not list it.** It was accepted by "as proposed", not explicitly.
2. **Throughput (section 2).** 63.1 native ticks per transition = 2,302 prefix ticks and 37.9 policy ticks per episode (5,038 episodes), plus the probes. Staging
   is the bottleneck: 5.56 s per staged start (boot 2.81 s, prefix 2.08 s at 1,109 ticks/s, build 0.44 s) on six slots is 1.08 starts/s, and the session consumed
   1.06 episodes/s; the four playing slots waited 1,383 s (29 %) for starts. A calibrated model projects **232 / 346 / 466 / 551 transitions/s** at pointers 2,128 /
   1,966 / 1,694 / 1,473 (9.5 / 5.9 / 3.9 / 3.0 native ticks per transition), against 59 at 2,280 and g1's measured 442 median. The one strip g2-s1 learned cost
   about 25 to 36 k transitions to reach a live rate of 0.5 to 0.6; with 40 / 80 / 150 k transitions per strip and 15 % probe overhead, the pointer reaches 1,680
   in **1.2 / 2.5 / 4.6 sessions** and tick 0 in **2.4 / 4.8 / 8.9 sessions** of 80 minutes, before any stall. Within the contract, the only free lever is moving the
   pointer promptly (deeper starts amortise the prefix); the one real lever, a batched prefix-submission protocol operation, is a native change outside this scope.
3. **g3 (section 3): one change, attempts that replenish with training progress.** The cap of 3 per session and 6 per line is replaced by a spacing rule: after
   f consecutive failed attempts at a pointer, the next attempt needs 20 x 2^(f-1) further counted strip outcomes (cap 320) and a fresh trigger. No HELD, no
   STALLED. Error rates on the observed curve: P(move in the session) 1.00 (median after 191 outcomes, about 7 minutes at the 2,280 rate) against 0.46 for the
   registered rule; false move per session at a strip stuck at p = 0.20 / 0.25: 1.1 % / 9.4 % (registered rule 0.9 % / 4.0 %; g1's block rule 100 %). A sustained
   trigger (12 of 20) would cut the false-move rate to 0.2 % at p = 0.25 but keeps an 8.5 % deadlock probability on the observed curve and the deadlock class
   itself. **g3-s1 starts fresh** (seed 0): the line contract digest covers the frontier rule, so a resume is refused by the registered compatibility rule, and a
   warm start would be a second change. The line budget is progress- and time-based only: D <= 2,128 by s2, 1,966 by s4, 1,694 by s6, success at 1,473, cap 8;
   no outcome ends the line through an attempt count.
4. **Test-suite fix (section 4).** g1's two source-guard tests scan every `rl/m9_*.py` except `m9_tests.py`; the tracked `rl/m9_eval_tests.py` (added by the
   checkpoint evaluation) spells six forbidden literals in its own guard at lines 557 and 559. Minimal fix: assemble those literals from fragments in
   `rl/m9_eval_tests.py`, as `rl/m9_g2_tests.py` already does. Two lines, no behaviour change; to be applied in an authorised preparation session.
5. **Speed search (section 5).** The archive already holds the material: its shortest level-9 arrival (targets 6 and 8 broken, only target 1 left) is at tick
   **1,898**, 168 ticks ahead of the trunk's 2,066; 57 level-9 cells arrive by 1,960, all airborne left of the wall and falling toward target 1's depth, and 30 of
   them were never dispatched (35 dispatches in all). Nothing in the archive is faster than the trunk on the right side (level 7 at 1,339) or at the crossing. A
   one-session time-directed continuation (about 1 hour, 6 M ticks) has, subjectively, a 65 to 80 % chance of a verified clear shorter than 2,315 and 40 to 55 %
   of one at least 10 % shorter; a 2x shorter clear is near 0 by this method. It does not advance the learning agent; it would shorten M9's route and offer a
   second ending lineage. **Recommendation: g3 first, the speed session second**; the direction is yours.
6. **Metadata (section 6).** Every artifact of anything designed here carries the top-level task block and `created_utc` at the source; the writer refuses without
   them.

---

## 1. Diagnosis

### 1.1 The timeline, from the records

Training-wall seconds are measured from the training phase's start (05:10:06 UTC; the first rollout record at 287.5 s was written 05:15:00 UTC).

| training wall | event | evidence |
| ---: | --- | --- |
| 0 | pointer 2,300; four playing + six preparing slots | `rollouts.jsonl` r1 |
| 30 | window 0 triggers: 8 clears of 8 at 2,300 | `windows.jsonl` |
| about 290 | attempt 1 at the first rollout boundary (5,120 transitions): strip test 10 of 12 (`ccccccxcxccc`); **MOVED 2,300 -> 2,280** at 324 s | `attempts.jsonl` n1, `moves.jsonl` |
| 361 | window 1 triggers at 2,280: 8 of 18 | `windows.jsonl` |
| about 378 | attempt 2 (10,240 transitions): 4 of 15; FAILED_STRIP | n2 |
| 440, 471 | windows 2, 3 void (13 non-clears before 8 clears) | `windows.jsonl` |
| about 507 | attempt 3 (20,480): 6 of 17; FAILED_STRIP | n3 |
| 579 | window 5 void | |
| about 676 | attempt 4 (30,720): 4 of 15; FAILED_STRIP; **HELD** (3 failed attempts at 2,280 in the session) | n4 |
| 732 | first `held_trigger` (8 clears in a window of 16) | `windows.jsonl` |
| about 670 / 756 / 1,098 / 2,102 / 2,625 | the 50-outcome rolling clear rate at 2,280 first reaches 0.50 / 0.60 / 0.70 / 0.80 / 0.90 | `episodes.jsonl`, strip starts at pointer 2,280 in completion order |
| 4,782 | the 213th and last `held_trigger` (8 of 9) | `windows.jsonl` |
| 4,804 | training wall cap: 190,696 transitions, 37 updates, pointer 2,280 | `training_summary.json` |

Counted strip outcomes at 2,280: 2,361. Clear rate per 200 in completion order: 0.390, 0.525, 0.660, 0.695, 0.710, 0.815, 0.840, 0.840, 0.895, 0.880, 0.905,
0.913. The 213 held triggers imply window rates (8 / window size) of 0.62 over the first 20 and 0.92 over the last 50. The near window (starts 2,300 to 2,324)
cleared 0.93 to 0.99 throughout.

### 1.2 Attempt exhaustion, or inability to learn

**Confirmed: the NULL was caused by attempt exhaustion during early training.**

- The pointer was held from 676 s to 4,804 s. During the hold the live strip rate at 2,280 went from about 0.4 to 0.91, i.e. the policy learned the only strip
  it was allowed to train on, past any bar the frozen test applies (P(pass) at p = 0.9 is 1.0000; at 0.8, 0.9994). Had an attempt been permitted after the rate
  crossed 0.6 (about 756 s), the move would have come with probability 0.87 per attempt.
- Every training start lay at tick 2,280 or later (strip 2,280 to 2,299, near window 2,300 to 2,324; the rehearsal region is empty at these pointers). The
  deciding audit at 2,128 is 152 ticks before the first trained state, on the second left-floor landing with target 8 broken and target 1 standing. The frozen
  final policy fell in 20 of 20 sticky episodes there (policy ticks 166 to 1,033, mean 514; every episode ended below y = -9,600; none broke target 1), in 20 of 20
  unperturbed and in the deterministic episode. The open-loop tape clears 49 % from the same state. This is the behaviour of a policy that has never seen that
  state as a start, not evidence about what it could learn there.
- What the records do not show: that the policy would have reached 10 of 20 at 2,128 had the pointer moved. g1 is the only evidence on that point (9 of 20 at
  2,128 after 409,600 transitions with its pointer at 2,040); it is one run under another rule and does not transfer.

**Disputed: "inability to learn".** No record supports it. The policy's learning at the one strip it trained on was monotone and fast (0.39 to 0.66 within 20
minutes, 0.9 within 44 minutes); the critic's explained variance rose from -0.03 to 0.84; entropy fell from 99.8 % to 86.6 % of maximum, which is the sharpening
one expects, not collapse.

### 1.3 The trigger-to-test gap, quantified

The strip test and the trigger measure the same thing (sticky p = 0.25, keyed starts uniform over the strip, sampled actions) from two different samples. The
components the request names, with the records:

| attempt | trigger window | live rate before the attempt (counted strip outcomes at 2,280) | frozen test | live rate after (next 60) | snapshot V at the handover / realised mean return |
| ---: | --- | --- | --- | --- | --- |
| 2 | 8 of 18 = 0.44 | 9 of 29 = 0.31 (all that existed) | 4 of 15 = 0.27 | 15 of 60 = 0.25 | -0.42 / -0.88 |
| 3 | 8 of 20 = 0.40 | last 60: 13 of 60 = 0.22 | 6 of 17 = 0.35 | 23 of 60 = 0.38 | -2.38 / +0.53 |
| 4 | 8 of 17 = 0.47 | last 60: 30 of 60 = 0.50 | 4 of 15 = 0.27 | 28 of 60 = 0.47 | -1.41 / -0.88 |

1. **Sampling mode: identical.** Both use sampled actions under sticky p = 0.25 from keyed draws (training: SB3's sampler on the live policy; test: keyed
   inverse-CDF on the frozen snapshot). The decisions record R1 and R4 fix this; the diagnosis of g1 (H2) already showed no mode mismatch. No contribution.
2. **Selection bias of the trigger (the main component).** The window fires at the 8th clear before the 13th non-clear, so its displayed rate is at least
   8 / 20 = 0.40 whatever the true rate, and when the true rate is 0.3 to 0.45 it fires in 23 to 75 % of windows (table in 1.5) while the frozen test passes in
   5 to 41 %. Attempts 2 and 3 fired on windows of 18 and 20 drawn from a process whose live rate was 0.22 to 0.31: the windows were upward-selected samples.
   The tests (0.27, 0.35) sit inside the live rate's sampling band; there is nothing to explain beyond the trigger's optimism.
3. **Policy change between trigger and test: wrong sign.** The snapshot is taken at the rollout boundary after the PPO update that follows the trigger
   (approx_kl 0.006 to 0.011 per update), so the tested policy is newer than the one that produced the window, and the live rate was rising by about 0.07 per
   100 outcomes. If anything this favours the test. No contribution to a shortfall.
4. **Start offsets within the strip: a real but small component, attempt 4 only.** In the first 600 strip outcomes the starts 2,280 to 2,296 cleared 214 of
   491 (0.44) while 2,297 to 2,299 cleared 101 of 109 (0.93): the last three ticks of the strip inherit the drop and are nearly free. Probe starts are keyed
   uniform over the same 20 ticks, so the distributions match in expectation, but a 15-episode test draws 2.25 easy starts on average; attempt 2 drew one
   (cleared), attempt 3 two (both cleared), attempt 4 **none** (probability 0.087), so its expected clears were about 15 x 0.44 = 6.7 against the 10 needed, and it
   drew 4 (P(<= 4 of 15 | p = 0.47) about 0.09).
5. **Sticky draws: no causal contribution.** The draw rate is 0.25 by construction in both. The recorded `sticky_hits` of a clear (about 18 policy ticks) is
   4 to 5 and of a fall (about 200 ticks) 50; the apparent "100 % clears at 0 to 10 hits, 10 to 18 % at 11 or more" is episode length, not a cause. Probe
   episodes averaged 31 to 39 hits and the training strip episodes around them 30 to 37, consistent with their clear rates.

In one line: with a true strip rate of 0.3 to 0.5, the registered trigger fires often and the registered test fails often, and each failure consumed one third of
the session's attempts.

### 1.4 Where "s1 NULL ends the line" was registered, and what the decisions accepted

| where | text |
| --- | --- |
| `docs/rl_m9_g2_proposal_2026-10-04.md`, section 6.5 (the line rule table) | `END_NULL_S1`: "g2-s1's outcome is NULL (section 7)" |
| the same, section 7 ("What s1's outcome leads to") | "NULL -> END_NULL_S1, a review" |
| `rl/m9_g2_rule.py`, `apply_line` | `if k == 1 and outcome == "NULL": END_NULL_S1`; self-test "s1 NULL ends the line"; line rule digest `d10d2ad84f399891...` |
| `docs/rl_m9_g2_s1_approval.json`, `rules` | names `m9_g2_line_rule_v1` with that digest |
| `runs/m9_g2/s1/session/line.json` | outcome END_NULL_S1, `s2_permitted: false` |

The decisions record (`docs/rl_m9_g2_decisions_2026-10-05.md`): decision 6, "Progress measure and budget. D_k as proposed; line stop if D has not reached 1,966
after N = 3 sessions; from session 4 one new landing per two sessions; a cap of 8 sessions; g2 complete at D <= 1,473", and decision 7, "g2-s1 rule as proposed.
PASS ... INCONCLUSIVE ... NULL: D_1 = none; INCOMPLETE and INVALID as in g1". **END_NULL_S1 is in neither.** The proposal's open question 9 ("Line budget. N = 3;
one new landing per two sessions from s4; cap 8 sessions; END_SUCCESS at D <= 1,473 ... Accept?") did not list it either. The rule was therefore registered and
implemented as part of "the line budget as proposed", and the approval pinned its digest, but it was never named in a decision the user wrote. The approval
statement's "NO s2" is the authorised scope of that session, not a judgement on the rule.

### 1.5 The registered mechanism, replayed against the observed learning curve

A seeded Python-side Monte Carlo (appendix A, `f_mc.py`; it touches nothing native) replays each mechanism against the clear-rate curve g2-s1 actually produced at
2,280 (section 1.1, a step function of the counted-outcome index, starting at 0.31) and against strips stuck at a constant rate for a whole session (2,400 counted
outcomes, about what one session yields). Per-test and per-trigger probabilities are exact binomials.

| true rate p | P(frozen test passes: 10 before 11) | P(trigger 8 before 13) | P(trigger 10 before 11) | P(trigger 12 before 9) |
| ---: | ---: | ---: | ---: | ---: |
| 0.20 | 0.003 | 0.032 | 0.003 | 0.0001 |
| 0.25 | 0.014 | 0.102 | 0.014 | 0.001 |
| 0.30 | 0.048 | 0.228 | 0.048 | 0.005 |
| 0.35 | 0.122 | 0.399 | 0.122 | 0.020 |
| 0.40 | 0.245 | 0.584 | 0.245 | 0.057 |
| 0.45 | 0.409 | 0.748 | 0.409 | 0.131 |
| 0.50 | 0.588 | 0.868 | 0.588 | 0.252 |
| 0.60 | 0.873 | 0.979 | 0.873 | 0.596 |
| 0.70 | 0.983 | 0.999 | 0.983 | 0.887 |

| mechanism (test unchanged: 10 before 11, frozen snapshot) | on the observed curve: P(move in the session) | P(HELD for the rest of the session) | move at counted outcome (median, p10, p90) | stuck p = 0.20 / 0.25 / 0.30: false move per session | competent p = 0.50 / 0.60: P(no move in a session) |
| --- | ---: | ---: | --- | --- | --- |
| **registered g2** (trigger 8 of 20, cap 3 per session) | 0.46 | **0.54** | 97, 38, 157 | 0.9 % / 4.0 % / 13 % | 7.6 % / 0.2 % |
| aligned trigger (10 of 20, cap 3) | 0.71 | 0.29 | 173, 87, 250 | 0.1 % / 2.6 % / 13 % | 6.7 % / 0.2 % |
| sustained trigger (12 of 20, cap 3) | 0.92 | 0.085 | 266, 163, 355 | 0.0 % / 0.2 % / 4.5 % | 6.7 % / 0.3 % |
| sustained trigger (24 of 40, cap 3) | 0.995 | 0.005 | 373, 271, 461 | about 0 | not run |
| **replenishing attempts** (trigger 8 of 20, spacing 20 x 2^(f-1) outcomes, cap 320, no HELD) | **1.00** | **0** | 191, 68, 411 | 1.1 % / 9.4 % / 37 % | 0 / 0 |
| g1's block rule (3 of 10, retried without limit; for reference) | 1.00 | 0 | 10, 10, 30 | 100 % / 100 % / 100 % | 0 / 0 |

About 150 counted strip outcomes took 6 minutes at the 2,280 throughput, 600 about 20 minutes. Spacing sensitivity for the replenishing variant: with a unit of
40 outcomes the stuck-strip false-move rate at p = 0.25 is 7.3 % per session (5.6 attempts) and the median move on the observed curve comes at outcome 217; with
80, 6.6 % (4.8 attempts) and 292. Over three sessions at a strip stuck at p = 0.25 the chance of a false move is 27 % (unit 20) or 21 % (unit 40).

Reading: the registered mechanism had about even odds of producing exactly g2-s1's record on this learning curve. The curve itself is the policy's; the outcome is
the rule's.

---

## 2. Throughput

### 2.1 The 63 native ticks per transition

| quantity | value | source |
| --- | ---: | --- |
| native ticks in the training phase | 12,036,120 = prefix 11,661,851 + probes 183,573 + policy 190,696 | `training_summary.json` |
| per policy transition | **63.1** (prefix alone 61.2) | |
| episodes | 5,038; mean prefix 2,302 words; mean policy phase 37.9 ticks (strip starts 61.4: clears 17.9, falls 199.7; near starts 14.3) | `episodes.jsonl` |
| one staged start | boot 2.81 s, prefix replay 2.08 s (1,109 ticks/s per process, transport-bound at about 0.9 ms per tick), v3 build 0.44 s: **5.56 s** median wall | `episodes.jsonl` `stage` |
| staging capacity | 6 slots / 5.56 s = 1.08 starts/s; consumed 5,066 / 4,800 s = 1.06 episodes/s | |
| playing-slot starvation | the arena waited 1,383 s for a ready start (29 % of the training wall), 2,281 waits | `training_summary.json` |
| transitions/s per rollout | 17.8 (fill), 58 to 99 while falls were common, **22 to 30 at the end** as clears shortened the policy phase | `rollouts.jsonl` |
| g1 for comparison | 1,396,160 transitions, 7,938,755 ticks: 5.7 ticks per transition, median 442/s, mean start 2,135, mean policy phase 456 ticks | `runs/m9_g1` |

Every episode is one fresh process plus a full prefix replay, by contract; the policy phase at pointer 2,280 is 20 to 50 ticks for a clear. The ratio is the
geometry of the end of the route, not a defect: it falls as the pointer moves back and as the policy phase lengthens. Note the paradox the records show: the
*better* the policy at a late strip, the *lower* the transitions per second, because clears are short and the staging cost is fixed.

### 2.2 Projection at the landings

Model (calibrated on g1's per-pointer medians and g2-s1): transitions/s = L / (0.95 s + L / 2,000), capped at 1,100/s by the four playing slots, where L is the
mean policy phase in ticks and 0.95 s is the staging-bound wall per episode (5.6 s / 6 slots). Calibration: (L, observed, model) = (38, 40, 39), (175, 150, 169),
(292, 253, 266), (493, 430, 412), (604, 486, 482), (904, 688, 645). L at a pointer is modelled for a competent policy as 60 % clears of 1.1 x the remaining route
plus 40 % non-clears of about 400 ticks (g1's falls ran 300 to 750).

| pointer | L (ticks) | transitions/s | native ticks per transition | prefix share of native ticks |
| ---: | ---: | ---: | ---: | ---: |
| 2,280 (measured 22 to 66) | 58 | 59 | 40 | 0.98 |
| **2,128** | 249 | **232** | 9.5 | 0.90 |
| **1,966** | 398 | **346** | 5.9 | 0.83 |
| **1,694** | 577 | **466** | 3.9 | 0.75 |
| **1,473** | 723 | **551** | 3.0 | 0.67 |
| 1,248 | 871 | 629 | 2.4 | 0.59 |
| 0 | about 1,700 | about 940 | 1.0 | 0 |

### 2.3 Revised budget

**Transitions per strip, from the records.** g2-s1's one learned strip (2,280 to 2,299, inherited-motion end of the route): the live rolling rate reached 0.5 at
about 25 to 31 k transitions after the move, 0.6 at about 36 k, 0.7 at about 56 to 61 k, 0.8 at about 100 k. g1's thirteen early strips averaged about 31 k
transitions each to leave 2,128 at a 45 % sticky rate. The frozen test passes a 0.55 to 0.60 strip with probability 0.75 to 0.87, so **about 40 k transitions per
easy strip** is the measured figure, and the proposal's 80 k is a reasonable middle; the drop toward target 1 (2,189 to 2,249, g1 moves 3 to 5), the climb to
target 8 and above all the 174-tick crossing flight (an up-B at the right moment from the rising platform; M7m's W2 stall was exactly this kind of two-part
input) are the candidates for 150 k or far more, and the records cannot bound a stall.

| pointer reached from 2,280 | strips | 40 k per strip | 80 k per strip | 150 k per strip |
| ---: | ---: | --- | --- | --- |
| 2,120 (then 2,128 audited) | 8 | 45 min, 0.6 sessions | 90 min, 1.3 sessions | 169 min, 2.4 sessions |
| 1,960 (1,966) | 16 | 63 min, 0.9 | 126 min, 1.8 | 237 min, 3.4 |
| 1,680 (1,694) | 30 | 86 min, 1.2 | 172 min, 2.5 | 323 min, 4.6 |
| 1,460 (1,473) | 41 | 101 min, 1.4 | 201 min, 2.9 | 377 min, 5.4 |
| 0 | 114 | 165 min, 2.4 | 331 min, 4.8 | 621 min, 8.9 |

Minutes are training wall from the model's throughput at each pointer; sessions are 80-minute training phases with 15 % probe and re-check overhead. The first
eight strips are the expensive ones (9 to 40 ticks per transition); the right side is cheap per transition and expensive per strip only if it stalls. Compared
with the diagnosis's estimate (2 to 5 hours to 1,694; 15 to 30 M transitions and "days" for tick 0): the per-transition cost at deep pointers is lower than the
diagnosis assumed, the per-strip cost is the same, and the stall risk is unchanged and unquantified. **Honest range: 1,694 in 2 to 5 sessions; tick 0 in 3 to 9
sessions without a stall, unbounded with one.**

### 2.4 Reducing the prefix cost within the contract

The contract fixes: process restart is the reset; no save state, no in-process reset; exact replay from tick 0 only; one submitted word consumes one tick. Within
it:

| lever | effect | status |
| --- | --- | --- |
| **Move the pointer as soon as competence is demonstrated** | the only free lever: at 2,128 a transition costs 9.5 ticks against 40 at 2,280; a mechanism that holds a learned strip for 69 minutes pays 40 ticks per transition for nothing | this is section 3 |
| More staging slots (2 + 8) | g1's P3 measured 2 + 8 at 1.012 x 4 + 6: the machine, not the slot count, bounds staging (ten processes on six cores; boot and prefix are CPU-heavy) | not a lever on this machine |
| Python-side pipelining of the per-tick checks | the prefix replay is bound by 2,302 transport round trips at about 0.9 ms each, not by the Python checks (build 0.44 s is separate) | marginal |
| Prefix replay without the diagnostic flags | the v3 handover observation needs every prefix reply's spatial and entity data, and the flags are process-level | not available |
| Longer policy phases per prefix (start mix, strip width) | changes curriculum constants: a second change; and the policy phase is set by the game (a clear or a fall ends the episode) | not proposed |
| **A batched prefix-submission protocol operation** (submit N words; the native side consumes one tick per word, captures every per-tick observation and returns them; no hidden state; the same words, consumed ticks and digests) | would cut the 2.08 s prefix replay toward the game's own cost (about 0.07 ms per update plus capture), roughly 5.6 s -> 3.9 s per start (-30 %), about +40 % transitions/s at 2,280 and +15 % at 2,128; it preserves the submit / consume / input-tick semantics tick by tick but is a **native and protocol change** (version bump, rebuilt executable), which under the guide suspends every lineage and archive exactness claim until re-verified from tick 0 | out of this scope; a separate proposal if wanted |

---

## 3. g3: a controlled frontier whose attempts replenish with training progress

### 3.1 The one primary change: `m9_g3_frontier_v1`

Everything in `m9_g2_frontier_v1` stays except the attempt bounds:

- **Trigger unchanged:** 8 clears among the first 20 counted strip outcomes of a window (fires at the 8th clear, void at the 13th non-clear; windows restart at the
  session open, after every move and after every attempt).
- **Test unchanged:** a frozen snapshot at the next rollout boundary, up to 20 keyed sticky episodes from the strip, pass at the 10th clear, fail at the 11th
  non-clear; then the same test from the trunk's own state at every landing the frontier has passed, in parallel, fail-fast; the pointer moves 20 ticks iff
  everything passes; never forward; training pauses on the four playing slots, the six preparing slots run the attempt.
- **Bounds replaced by a spacing rule.** Let f be the number of consecutive failed attempts at the current pointer since the last move (f = 0 after a move).
  An attempt may run only if at least **20 x 2^(f-1) counted strip outcomes** (f >= 1; cap 320) have completed at this pointer since the last failed attempt,
  and the trigger has fired. A trigger inside the spacing is logged `deferred_trigger`, no attempt runs, and the window restarts. There is **no HELD and no
  STALLED**; the per-pointer attempt counts are recorded and reported.
- **Why counted strip outcomes, not rollouts or wall time:** an attempt is a test of a policy; what makes repeated tests dangerous is testing a nearly unchanged
  policy at a strip it has not practised. Counted strip outcomes at the pointer are the amount of new practice at that strip, the same at 2,280 (where a rollout
  is 50 to 120 outcomes) and at 1,694 (where a rollout is 4 to 5). They also make the spacing rebuildable from the episode records alone (`verify-run`).
- **Why geometric:** each failure is evidence that the strip is below the bar; the schedule tests a stuck strip less and less often (attempts per session at a
  stuck strip: about 7 at unit 20, against unlimited under g1 and 3 under g2) while a strip that becomes competent is re-tested within one or two windows.

**Error rates** (section 1.5): on g2-s1's observed curve the move comes with probability 1.00, at a median of 191 counted outcomes (about 7 minutes at the 2,280
rate, p90 411); the chance of a session with no move at a competent strip is 0. False move per session at a strip stuck for the whole session: 1.1 % at p = 0.20,
9.4 % at 0.25, 37 % at 0.30, 71 % at 0.35 (the registered rule: 0.9 / 4.0 / 13 / 32 %; g1's block rule 100 % everywhere). Over three sessions at p = 0.25: 27 %.
Two things bound the damage of such a move: the next strip's test demands the whole remainder, so a move made at a 30 % strip makes the following trigger rare
(P 0.23 per window) and the following test unlikely (P 0.05), and the re-checks hold every passed landing; the g1 failure (three successive moves at 4 to 12 %) has
probability below 0.1 % per move under the frozen test regardless of the attempt schedule. An "early" move at 30 to 45 % shifts half of the starts twenty ticks
earlier while the near window keeps the previous strip in training; it is recoverable. A deadlock is not.

**The candidates not chosen, by principle:**

| candidate | what it fixes | what it keeps | verdict |
| --- | --- | --- | --- |
| sustained trigger (12 of 20, cap 3) | wastes far fewer attempts (0.9 failed per session on the curve; false move 0.2 % at p = 0.25) | the cap, hence the deadlock class: 8.5 % HELD on the observed curve, 6.7 % on a p = 0.5 strip; and about 170 outcomes (6 minutes) more delay per strip, 30 strips to 1,694 | strongest luck control; does not remove the artifact the line ended on |
| sustained trigger (24 of 40) | deadlock 0.5 % | 373 outcomes (about 12 minutes) per strip of pure waiting, about 6 hours to 1,694 | too slow |
| aligning the trigger with the test (10 of 20) | halves the wasted attempts | the cap: 29 % HELD on the curve | insufficient |
| replenishing attempts | the deadlock class, by construction | a weaker luck control at 25 to 35 % (recoverable, see above) | **chosen** |

If the user prefers the luck control of the sustained trigger, the trigger bar is a single registered constant and can be raised in a later line; combining it with
replenishment now would be two changes against g2.

### 3.2 g3-s1 starts fresh

- **A resume of g2-s1's pinned state is refused by the registered rule.** The line contract digest (`1aadc7a6...`) includes `frontier_description()`, which carries
  `attempts.per_session` and `per_line`; decision R14 and the proposal (6.2) make a resume refuse any change to it. A changed frontier rule is a new line by the
  project's own compatibility logic (M7b's rule, applied to the line).
- **A warm start from g2-s1's final weights would be a second change** (initialisation) and a poor one: that policy spent 190,696 transitions on one 46-tick
  strip, its critic reads -2.51 at 2,128 against a realised -5.51, and M7m's warm starts carried anti-aligned priors. The cost of starting fresh is the time to
  re-pass 2,300 and reach the bar at 2,280: about 6 to 8 minutes by g2-s1's own curve.
- Fresh means the M7n v3 network, seed 0, entropy coefficient 0.01, as g1 and g2; the untrained `policy.pth` member should again equal
  `eb592c887fc66aaba038e0b35986463bf03153bd7fe78a3f5d80357fa517ceb0` (reported, never deciding), which makes g3-s1 against g2-s1 a comparison with one changed
  mechanism from identical initial weights.

### 3.3 The g3-s1 rule, `m9_g3_s1_rule_v1`

Evaluated in order; the first that holds is the outcome.

| outcome | condition |
| --- | --- |
| INVALID | as g2, with "more attempts at a pointer than the bounds" replaced by **"an attempt inside its spacing"** (rebuilt from the records by `verify-run`) and "a pointer move without a recorded passing attempt" kept |
| INCOMPLETE | as g2 (P1, P2 or T0 not passed; training ended before a valid end: the 80-minute wall, the tick cap or the transition cap, STALLED no longer exists; the audit incomplete where D_1 or R_1 needs it; B unpinned where it could matter; an unverified audit clear that could change D_1 or R_1) |
| PASS | R_1 <= 1,966 |
| INCONCLUSIVE | D_1 <= 2,128 |
| NULL | D_1 = none |

**Reported, never deciding:** the pointer trace; every attempt with its trigger window, spacing state, strip result and re-checks; deferred triggers; the attempt
yield (moves per attempt); the trigger-to-test gap per attempt (window rate, live rate over the preceding 60 counted outcomes, test rate); FRONTIER_BACKED; the
entropy, calibration and handover readings of g2; throughput with the native-tick split; the untrained-weights equality.

### 3.4 The line budget and stop rule, `m9_g3_line_rule_v1`

Checked at every session close, in order. **Every END is a progress or time condition; no outcome depends on an attempt count, and a NULL s1 does not end the
line by itself.**

| outcome | condition |
| --- | --- |
| SUSPENDED (review) | the session is INVALID; or two consecutive sessions are INCOMPLETE |
| END_SUCCESS | D_k <= 1,473 ("crossing learned"; g4 = the right side and the claim, a separate proposal) |
| END_BUDGET_2128 | k = 2 and D_2 = none (not even 10 of 20 at the last landing after two sessions, about 160 minutes of training: at 40 to 150 k per strip the pointer reaches 2,120 in 0.6 to 2.4 sessions, section 2.3) |
| END_BUDGET_1966 | k = 4 and D_4 later than 1,966 (model: 0.9 to 3.4 sessions) |
| END_BUDGET_1694 | k = 6 and D_6 later than 1,694 (model: 1.2 to 4.6 sessions; the crossing flight is not inside this bar, 1,694 is the wall-top landing) |
| END_NO_PROGRESS | k >= 4 and D_k not earlier than D_{k-2} |
| END_CAP | k = 8 without END_SUCCESS |
| CONTINUE | otherwise; session k + 1 is proposable with its own approval |

An INCOMPLETE session counts toward k only if its training reached 50 % of its wall cap (as g2). Sessions resume g3's own pinned state under g2's resume
machinery (R14), with the spacing state (f and the outcomes since the last failed attempt at the pointer) carried in `curriculum_state.json`.

**Odds (subjective, for planning):** g3-s1 INCONCLUSIVE or better 55 to 70 %; PASS in s1 10 to 15 %; END_SUCCESS within 8 sessions 20 to 30 %. The crossing
flight remains the main risk, unchanged from the g2 proposal.

### 3.5 Unchanged, and the implementation outline

Unchanged from g2: observation v3, reward v2, PPO (ent_coef 0.01), sticky p = 0.25 everywhere, the two rd4 routes as start states only, pointer 2,300, strips
of 20, the 50 / 30 / 20 start mix, the stale rule, the trigger, the frozen test and curtailment, the re-checks of every passed landing, the fixed 4 + 6 slots, the
tape baseline procedure (T0 re-measured in g3-s1 under `m9|g3|reach|<landing>|<k>` keys, 200 at 2,128 and 40 elsewhere, every counted tape clear replayed, the bar
`max(10, ceil(20 p_hat) + 5)`; reusing g2-s1's pinned table by digest would save 7.5 minutes and is open question 6), the close audit, verification tiers, the
80-minute training wall under a 145-minute cap, the memory caps, at most 10 game processes, the write guard, the D: increment at every close, the metadata
requirement. Keys move to the `m9|g3|...` family.

New files only (`rl/m9_g3_*.py`): a contract module that imports `rl/m9_g2_contract` and replaces the attempt bounds by the spacing constants (unit 20, cap 320) and
computes the g3 digests; a frontier module with the spacing rule, `deferred_trigger`, and the history rebuild; a rule module (`m9_g3_s1_rule_v1`,
`m9_g3_line_rule_v1`, self-test); thin session, run and report wrappers; a test suite with a synthetic two-session line that exercises a deferred trigger, a
spaced attempt, a move after failures, and a resume carrying the spacing state. Whether `rl/m9_g2_probe.run_attempt` and `rl/m9_g2_train` can take the g3
frontier object unchanged (duck typing) or must be copied is a preparation reading, recorded in the g3 decisions record. No inherited file is edited except the
test-suite fix of section 4, which is its own item.

---

## 4. The two failing g1 source-guard tests

**Cause.** `rl/m9_tests.py` line 1325, `_m9_sources()`, scans `rl/m9_*.py` and excludes only `m9_tests.py`. `source_guard_no_fixtures_tas_or_recordings` (line
1331) asserts that no scanned file contains any of nine literals (`rl/fixtures`, `fixtures/m7g`, `tas_input`, `mario_743`, `.btti`, `btti_replay`,
`m7g_capture`, `m7g_fixture`, `crossing_fixture`); `source_guard_no_rng_and_no_native_randomness` (line 1345) asserts the same for eight RNG literals. The
tracked `rl/m9_eval_tests.py`, added by the M9-g1 checkpoint evaluation (commit `4a778b4`), contains its own guard whose forbidden tuples spell the literals out:
line 557 (`"tas_input"`, `".btti"`, `"fixtures/m7g"`, `"m7g_capture"`) and line 559 (`"rng_seed"`, `"native_rng"`). A read-only replication of both tests over
the 40 scanned files (appendix A, `e_guard.py`) finds exactly these six hits and no other file: the g2 files pass because `rl/m9_g2_tests.py` assembles its
fragments (`"tas_" + "input"`, line 1092). The failures are test-on-test collisions; no production file is affected.

**Minimal fix (recommended, option a).** In `rl/m9_eval_tests.py`, rewrite the two tuples with assembled fragments, as its own line 50 already does for
`FORBIDDEN_PATH_PREFIXES`: for example `"tas_" + "input"`, `".bt" + "ti"`, `"fixtures/" + "m7g"`, `"m7g_" + "capture"`, `"rng_" + "seed"`, `"native_" + "rng"`.
Two lines change; the eval suite's own guard compares the assembled strings at run time and keeps its meaning; g1's two tests pass again on the tracked tree. It
changes the fingerprint of `rl/m9_eval_*.py` (the closed evaluation recorded `125c848591c41d14`); the evaluation's source snapshot on D: holds the original, and the
preparation record should note the new fingerprint.

**Alternative (option b).** Exclude every `*_tests.py` in `_m9_sources()`. One line in `rl/m9_tests.py`, but it weakens g1's guard (test files would no longer be
scanned) and edits a g1 file whose fingerprint is pinned by the g1 approval. Not recommended.

Either fix belongs to a later authorised preparation session, with the three consecutive unit-suite passes repeated; nothing is edited now.

---

## 5. The speed-search alternative: archive search for shorter clears

### 5.1 What the rd4 archive already holds (read-only census, `d_archive.py`, `d2_archive.py`)

The archive keeps one trajectory per cell and replaces it only by a strictly shorter arrival ("shorter L wins"), so each cell's L is the shortest known arrival at
that cell. 37,312 cells.

| level (targets broken) | cells | shortest arrival L | the trunk's arrival | note |
| ---: | ---: | ---: | ---: | --- |
| 7 (all right targets) | 5,107 | **1,339** | 1,339 (target 2) | no cell is faster than the trunk; 1 % of level-7 cells arrive by 1,410 |
| 8 | 2,342 | **1,838** | 1,838 (target 6) | the trunk's own |
| 9 (only target 1 left) | 2,901 | **1,898** | 2,066 (target 8) | **168 ticks ahead of the trunk**; 57 cells by 1,960, 187 by 2,000 |
| 10 (clear) | 4 | 2,315 | 2,315 / 2,326 | the two verified routes and two unreplayed endings (2,324, 2,348) |

The 57 fast level-9 cells (L <= 1,960) are all class A1, airborne left of the wall at x -2,250 to -3,757 and y -940 to +1,036, falling at about -44 units per tick,
descendants of two level-8 cells (27,443 and 27,463) created in rd4; target 1 is at (-3,450, -2,550), 2,500 to 3,500 units below them. **30 of the 57 were never
dispatched; the 57 received 35 dispatches in all** (the 2,901 level-9 cells received 996). The wall-top cells are the one lineage at L 1,694; the left-of-wall
cells with L below 1,694 are rd3's under-stage falls (y -5,883 and below), not crossings. So: the right side and the crossing have no faster known material; the
left side after target 6 does, and it is almost unexplored.

### 5.2 A concrete first session, "M8-sd1" (speed discovery; new files `rl/m8_sd1_*`, separately authorised)

- **Archive:** a continuation of `m8_rd_a1` with rd4 as closed (resume protocol of rd2 to rd4; P1 and identity replays as rd4).
- **Selection `m8_rd_select_v4` = `m8_rd_select_v3` with exactly one change: the length factor's scale.** v3's cell weight is
  `(1 + seen)^-1/2 x 900 / (900 + L - L_min(level)) x w_res`; at the fast level-9 cells (L - L_min up to 168) the length factor is 0.84 or more, so v3 barely
  prefers them. v4 sets the scale to **100**: a cell at the level's shortest arrival keeps weight 1 and the median level-9 cell (L - L_min about 290) falls to
  0.26. Eligibility (E1 to E6, X1), the level draw (level 9 is the top eligible level, since level-10 cells are terminal), the explorer, the burst length, the
  replacement rule, the keys (a `_sd1` suffix) and every check stay v3's.
- **Rule `m8_sd1_rule_v1`:** FASTER_CLEAR iff a candidate clear verified by exact replay from tick 0 has `completion_input_tick` < 2,315 (the best known), with
  both clocks reported and never collapsed; tiers reported: at least 1 % shorter (<= 2,291), 5 % (<= 2,199), 10 % (<= 2,083); otherwise NO_FASTER_CLEAR; INVALID and
  INCOMPLETE as rd4; the verification plan replays the fastest claimed clear first. The TAS's 446 is a number to compare against, never words, starts or segments.
- **Budget as rd4:** exploration 50 minutes / 6,000,000 ticks (rd4: 3,480 returns, 5.59 M ticks in 50 minutes, 93.6 % prefix replay), verification 400,000 ticks /
  6 minutes, the rd4 memory caps, at most 10 game processes, a 60-minute hard cap. Under v4 about a third of dispatches go to level 9 and most of those to its
  fast tail: several hundred bursts from the fast cells against 35 so far.
- **Odds (subjective):** a verified clear shorter than 2,315 in one session **65 to 80 %** (the trunk's own ending from 2,066 took 260 ticks; the fast cells are
  60 to 80 ticks of falling from target 1's depth, but target 1 sits 600 units below the left floor's surface, so the explorer must pass beside the floor or drop
  off it); at least 10 % shorter **40 to 55 %**; at least 2x shorter (<= 1,160) **about 0** (the right side alone is 1,339 ticks in every known lineage and the
  crossing has one lineage; that is M11's raw-word polishing or a different right-side order, neither of which this method reaches).

### 5.3 Comparison

| | g3 line (section 3) | M8-sd1 speed session |
| --- | --- | --- |
| track | Track 1: a policy, toward the tick-0 claim | Track 2: a trajectory, toward faster verified clears |
| preparation | one zero-tick session: new `rl/m9_g3_*` files, tests, three passes, snapshot, approval; plus the section 4 fix | one zero-tick session: `rl/m8_sd1_*` files, tests, three passes, snapshot, approval |
| first answer | g3-s1: about 2 hours 20 minutes (145-minute cap); INCONCLUSIVE or better 55 to 70 % | about 1 hour; a verified shorter clear 65 to 80 % |
| meaningful result | 1,694 in 2 to 5 sessions, 1,473 (END_SUCCESS) in 3 to 6 without a stall; 20 to 30 % within the cap of 8 | one to two sessions; 10 % shorter 40 to 55 % |
| what it means for a genuine learning agent | the direct test: whether a controlled backward curriculum robustifies the agent's own clear; nothing else in the project does this | nothing directly; it shortens M9's route by the same fraction (fewer strips; staging cost per transition falls little, since boot dominates), and a second verified ending adds lineage diversity below about tick 1,840 only |
| main risk | a stall at the crossing flight; one crossing lineage | the gain stays below the floor's edge geometry; no new crossing lineage; no effect on the policy question |

### 5.4 Recommendation

Run **g3 first**. The evidence of this review is that the policy learned what it was allowed to learn and the line ended on a mechanism artifact; the cheapest
informative act is to remove the artifact and rerun, from identical initial weights, so that g3-s1 against g2-s1 isolates the mechanism. The speed session is
cheaper and likelier to produce a verified number soon, and its material is real (section 5.1), but it answers a Track 2 question; its best use for M9 is as a
second ending lineage once the g3 line shows whether robustification progresses at all. If a visible result within one hour matters more than the policy question
right now, the order reverses. The direction is yours.

---

## 6. Artifact metadata (requirement carried)

Every record of anything designed here, g3 and M8-sd1 alike, records at its source the top-level task block
`{"id": "ssb64_us_mario_btt_v1", "character": "mario", "stage": "btt_mario"}` and `created_utc` (ISO 8601, seconds, `Z`, the first write, never a file time, never
rewritten by a copy, backup or re-verification), through the unchanged writers of `rl/m9_artifacts.py` (M9) and the rd4 writers (M8), which refuse to write
without them; the close audit and `verify-run` audit the whole tree. Existing trees are not back-filled.

## 7. Compliance of everything designed here

| constraint | g3 | M8-sd1 |
| --- | --- | --- |
| no native RNG seed inspection, logging, control, comparison or hashing | every draw is a Python-side keyed sha256 uniform (`m9\|g3\|...`); SB3's seed is a Python-side training seed | keyed draws `m8_rd\|m8_rd_a1\|select\|<iteration>` with the `_sd1` suffix, as rd2 to rd4 |
| process restart resets the episode | one fresh process per episode, prefix included, for training, probes, re-checks, tape and audit; a parked process consumes nothing; no save state | one fresh process per return |
| exact submit / consume / input-tick contract | unchanged: prefix word i consumes tick i, the policy's first word consumes tick tau | unchanged |
| canonical controller words as replay truth, no hidden actions | the submitted word is the record; sampled words and sticky masks are metadata | Track 1 words 0 to 71 |
| human recordings, fixtures and the TAS validation-only | never read; the static source guard kept; 446 appears only as a number | the same |
| no hardcoded routes or waypoints | start states are prefixes of the agent's own verified routes; the landing states are computed from the trunk's grounded segments and decide only when the start window moves | cells are agent-generated; the length factor is a generic time preference, not a route |
| non-PORT decomp and byte-matching behaviour preserved | no native, decomp or submodule change; executable `30a3913b...` with its existing read-only diagnostics | the same |
| a rebuilt executable | suspends every lineage claim and the tape table until re-verified from tick 0 | suspends the archive's exactness claim until every carried cell is re-verified |
| metadata | section 6 | section 6 |

---

## 8. Open questions

1. **g3's one change.** Replenishing attempts with geometric spacing (unit 20 counted strip outcomes, cap 320, no HELD, no STALLED), as recommended; or the
   sustained trigger (12 of 20) with the cap kept; or a different spacing unit (40 lowers the stuck-strip false-move rate from 9.4 % to 7.3 % per session at
   p = 0.25 and delays the median move by about one minute)?
2. **Fresh start.** g3-s1 from the fresh seed-0 policy (recommended), accepting the 6 to 8 minutes to re-learn the end strips, or a warm start from g2-s1's final
   weights as a declared second change?
3. **Line budget.** D <= 2,128 by s2, 1,966 by s4, 1,694 by s6, END_SUCCESS at 1,473, END_NO_PROGRESS from s4, cap 8 sessions; no END on a NULL s1 and no END on
   attempt counts. Accept, or tighten the budgets toward the 80 k-per-strip middle (2,128 by s2, 1,966 by s3, 1,694 by s4)?
4. **Session envelope.** Keep 80 minutes of training under the 145-minute cap (recommended: the envelope is proven), or lengthen the training wall now that the
   first eight strips are known to be the slow ones?
5. **Reported diagnostics.** Add the trigger-to-test gap per attempt and the attempt yield to the reported readings (recommended), or report g2's set only?
6. **Tape baseline.** Re-measure T0 in g3-s1 under `m9|g3|reach` keys (recommended, 7.5 minutes), or reuse g2-s1's pinned table by digest with its `m9|g2|reach`
   labels?
7. **Test-suite fix.** Option a (fragment assembly in `rl/m9_eval_tests.py`, two lines) in the g3 preparation session, or option b (exclude `*_tests.py` in g1's
   scanner), or leave the two known failures documented?
8. **Speed search.** Authorise the design of M8-sd1 now (a separate proposal with its own rule, caps and tests), after g3-s1, or not at all?
9. **The batched prefix-submission operation.** Out of scope here. Do you want a separate native-change proposal that weighs the roughly 30 % staging saving
   against the re-verification of every lineage and archive claim, or is the contract's current reading (the existing executable) to stand?
10. **The g2 line record.** g2-s1's END_NULL_S1 stands as registered; this review proposes g3 as a new line rather than an amendment of g2. Accept that framing?

---

## Appendix A. Scratch analyses (read-only; session scratchpad `...\scratchpad\g2rev\`; not preserved)

| script | input | used in |
| --- | --- | --- |
| `a_g2.py` | `runs/m9_g2/s1/training/{episodes,rollouts,windows,attempts,probes}.jsonl` | 1.1, 1.2, 1.3, 2.1 |
| `b_g1.py` | `runs/m9_g1/training/{episodes,rollouts}.jsonl` | 2.2 (calibration), 2.3 |
| `c_proj.py` | none: the throughput model and the strip-budget integration | 2.2, 2.3 |
| `d_archive.py`, `d2_archive.py` | `runs/m8_rd_rd4/archive/cells.jsonl` | 5.1 |
| `e_guard.py` | the tracked `rl/m9_*.py` files (a replication of g1's two guard tests without importing the repository) | 4 |
| `f_mc.py` (and one inline spacing-sensitivity run) | none: exact binomials and a seeded Python-side Monte Carlo of the mechanisms against the observed curve | 1.5, 3.1 |
| inline one-liners | `runs/m9_g2/s1/audit/episodes.jsonl`, `runs/m9_g1/eval/episodes.jsonl`, `docs/rl_m9_g2_s1_approval.json` | 1.2, 1.4 |

No script imported a repository module or loaded model weights; none launched a game process; the Monte Carlo's pseudo-random draws are Python's `random`
seeded in the scratch script and have nothing to do with the game's RNG.

## Appendix B. Sources

- `docs/rl_m9_g2_s1_results_2026-10-06.md`, `docs/rl_m9_g2_decisions_2026-10-05.md`, `docs/rl_m9_g2_implementation.md`, `docs/rl_m9_g2_proposal_2026-10-04.md`.
- `docs/rl_m9_g1_results_2026-10-04.md`, `docs/rl_m9_g1_diagnosis_2026-10-04.md`, `docs/rl_m9_g1_decisions_2026-10-04.md`, `docs/rl_m9_g1_implementation.md`,
  `docs/rl_m9_g1_checkpoint_eval_plan_2026-10-04.md`, `docs/rl_m9_policy_proposal_2026-10-03.md`.
- `docs/rl_m8_rd4_results_2026-10-03.md`, `docs/rl_m8_rd4_decisions_2026-10-03.md`, `docs/rl_m8_rd_continuation_proposal_2026-10-02.md`.
- T. Salimans, R. Chen, *Learning Montezuma's Revenge from a Single Demonstration*, arXiv:1812.03381 (2018); A. Ecoffet et al., *First return, then explore*,
  Nature 590 (2021): the backward algorithm and the count-based cell weight the archive uses.
