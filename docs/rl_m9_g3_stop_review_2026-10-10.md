# M9-g3 stop review (2026-10-10)

**Status: read-only stop review of the ended g3 line. Zero native ticks; no training, evaluation, preflight or launch; no tracked file modified;
nothing written under `runs/`, under any `logs/m9_g3_*` directory of a snapshot set, or on D:; no commit, push, branch or pull request.** The only
new files are this record and the working files under `logs/m9_g3_stop_review/` (section 11). Every registered outcome stands as recorded: s6
**NULL**, line **END_BUDGET_1694**, the g3 line ended by `m9_g3_line_rule_v1`. This review changes nothing and reopens nothing.

| item | value |
| --- | --- |
| checkout | `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, branch `main`; HEAD = `origin/main` = `f0f17ca5d805983ab13b6b6d57cdbbdbed4d8a16` ("Add the results of the sixth training session: the policy collapsed during training"), which is the commit carrying `docs/rl_m9_g3_s6_approval.json` and `docs/rl_m9_g3_s6_results_2026-10-10.md`; `git status` clean at the start |
| evidence read | `runs/m9_g3/s5` and `runs/m9_g3/s6` (training, probe, attempt, audit and session records, the pinned checkpoints), `runs/m8_rd_rd4/routes/T_clear/trace.json.gz` (the agent's own rd4 route, recorded replies), the six approvals and six results records, the runbook, the progression-fix and resume-k records, the g1 diagnosis; nothing under `tas_input_2/`, no human recording, no fixture |
| method | offline Python (`python -B -X utf8`) on saved artifacts only; policies loaded weight-only from their pinned `model.zip` members and `snapshot_policy.pth` files with the optimizer constructor replaced by a function that raises; no RNG seed inspected, logged, controlled, compared or hashed |

## 1. Verdict

The s6 collapse was a policy-level drift into horizon-waiting that began within the first five to seven minutes of the session, before and
around the single move to 1,760 at 128.9 s, deepened to a trough at 570-680 s (clear rate 11.6 %, 73 % of the bin's transitions inside
3,600-tick horizon episodes), recovered partly at 833-1,194 s (37-46 %), and then declined a second time from about 1,800 s to the end (3.4 %
in the last 102,400 transitions). Every start region decayed together, the new 20 ticks of the strip were not where the episodes failed, and
the later segments kept being visited but stopped being traversed successfully. The optimizer, the schedules, the Adam state and every PPO
setting were identical across s1-s6 and behaved normally (approx_kl 0.010-0.012, clip fraction 0.08-0.17, entropy 86-90 % of maximum, policy
drift about 0.2 nats per 102,400 transitions in s5 and s6 alike); candidate (b) is ruled out and no implementation defect (e) was found. The
evidence supports (c), the value and advantage dynamics, as the proximate mechanism: after the move the critic stayed optimistic while returns
fell (78 % of start-state advantages negative at 285-427 s), then tracked the collapsed returns down to about zero, after which, under reward
v2 with gamma 0.999 and the 3,600-tick horizon, waiting on the left floor (discounted return about 0) beat attempting (clear about +6.5 to +8,
fall about -1.7 to -2.1) once the clear probability fell under roughly 20 %, and the policy settled into that attractor. Candidate (a) holds
as a description of the data (the strip was mostly failures and supplied 54 % of the transitions) but not as the mechanism (the failures were
on the floor and at the final drop, not in the new ticks, and s5's 1,800 strip started at the same 0.23 rate and recovered). Candidate (d)
cannot be decided from this evidence (the entropy coefficient and the sticky probability never varied). s5 showed the same dip after its move
to 1,800 (clear rate 65 -> 40 %, 65 % negative advantages) and recovered within about 500 s; s6 did not recover. The pattern shares g1's end
state (horizon-waiting, negative late values, loss of the final drop while the segment is still visited) but not g1's trigger: s6's move was
passed on a frozen strip test with both re-checks, and no skill grew while another was lost.

## 2. Collapse timeline

Source: `runs/m9_g3/s6/training/rollouts.jsonl` (per-rollout `update_metrics_of_the_previous_rollout`: `entropy_loss`, `approx_kl`,
`clip_fraction`, `value_loss`, `explained_variance`, `learning_rate`, `clip_range`; `ep_return_mean_recent` over SB3's 100-episode window) and
`runs/m9_g3/s6/training/episodes.jsonl` (per episode: `start.region`, `tau`, `end_reason`, `policy_ticks`, `return`, `reward_terms`, `breaks`,
`first.left_floor`, `t`), joined by training wall time; bins of 20 rollouts = 102,400 transitions = the checkpoint cadence. The advantage
proxy is the exact discounted return of the recorded reward events (gamma 0.999, no horizon bootstrap) minus V(tau) of the latest pinned
checkpoint at or before the rollout, computed offline (section 5, question 4). Working tables: `logs/m9_g3_stop_review/out/q1_timeline.md`.

**Advantage mean and standard deviation are not logged** by the training driver (SB3 normalises advantages per minibatch and logs neither);
the proxy below is the closest reading the evidence allows.

| bin | train wall s | clear % | falls | horizon | mean R | target / step / clear / failure | mean len | R_recent | H % | approx_kl | clip | v_loss | EV | strip / near / reh % | horizon tr % | adv proxy (mean, % < 0) |
| ---: | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |
| 1 | 16-277 | 44.2 | 51 | 12 | 3.22 | 1.88 / -0.83 / 4.42 / -2.26 | 825 | 2.81 | 87.6 | 0.0115 | 0.119 | 2.41 | 0.64 | 38 / 39 / 68 | 23 | +0.66, 59 |
| 2 | 285-427 | 29.8 | 48 | 25 | 1.27 | 1.62 / -1.02 / 2.98 / -2.31 | 1,018 | 0.80 | 87.3 | 0.0114 | 0.112 | 1.72 | 0.62 | 21 / 24 / 57 | 42 | -2.68, 78 |
| 3 | 433-565 | 24.4 | 49 | 19 | 0.12 | 1.50 / -1.11 / 2.44 / -2.72 | 1,107 | 0.63 | 86.8 | 0.0113 | 0.108 | 1.52 | 0.58 | 6 / 26 / 55 | 35 | -0.31, 67 |
| 4 | 570-680 | 11.6 | 20 | 41 | -0.51 | 1.23 / -1.45 / 1.16 / -1.45 | 1,449 | 0.33 | 86.6 | 0.0117 | 0.126 | 0.51 | 0.62 | 10 / 6 / 21 | 73 | -1.20, 78 |
| 5 | 686-823 | 19.8 | 43 | 30 | 0.09 | 1.62 / -1.14 / 1.98 / -2.36 | 1,138 | 0.12 | 86.9 | 0.0104 | 0.093 | 1.43 | 0.50 | 14 / 22 / 45 | 52 | +0.32, 69 |
| 6 | 833-990 | 37.4 | 54 | 18 | 2.18 | 1.71 / -0.92 / 3.74 / -2.35 | 919 | 2.42 | 87.3 | 0.0108 | 0.099 | 2.08 | 0.67 | 27 / 46 / 48 | 30 | +0.54, 61 |
| 7 | 999-1,194 | 46.1 | 53 | 9 | 3.42 | 2.00 / -0.88 / 4.61 / -2.30 | 880 | 3.20 | 86.1 | 0.0114 | 0.110 | 2.43 | 0.71 | 36 / 51 / 65 | 16 | +0.33, 56 |
| 8 | 1,234-1,402 | 31.2 | 72 | 14 | 1.11 | 1.70 / -0.83 / 3.12 / -2.88 | 830 | 1.05 | 87.1 | 0.0116 | 0.106 | 2.47 | 0.64 | 30 / 28 / 40 | 25 | -0.33, 66 |
| 9 | 1,412-1,584 | 40.6 | 75 | 10 | 2.58 | 1.85 / -0.70 / 4.06 / -2.62 | 704 | 2.64 | 87.4 | 0.0118 | 0.112 | 3.27 | 0.55 | 32 / 45 / 52 | 18 | +0.39, 62 |
| 10 | 1,593-1,793 | 37.2 | 66 | 15 | 2.13 | 1.77 / -0.80 / 3.72 / -2.56 | 801 | 2.34 | 88.4 | 0.0114 | 0.110 | 3.27 | 0.49 | 34 / 29 / 58 | 26 | -1.85, 66 |
| 11 | 1,802-1,933 | 23.2 | 56 | 17 | -0.11 | 1.59 / -1.07 / 2.32 / -2.95 | 1,071 | -0.13 | 88.8 | 0.0109 | 0.107 | 2.17 | 0.45 | 17 / 29 / 25 | 30 | -1.63, 77 |
| 12 | 1,940-2,078 | 23.0 | 58 | 19 | -0.08 | 1.54 / -1.02 / 2.30 / -2.90 | 1,022 | 0.04 | 88.8 | 0.0116 | 0.114 | 1.62 | 0.54 | 12 / 21 / 62 | 34 | -0.73, 77 |
| 13 | 2,084-2,228 | 23.6 | 68 | 13 | -0.24 | 1.58 / -0.97 / 2.36 / -3.21 | 974 | -0.57 | 87.8 | 0.0117 | 0.108 | 1.94 | 0.54 | 15 / 23 / 45 | 23 | -0.30, 75 |
| 14 | 2,235-2,377 | 19.6 | 69 | 17 | -0.85 | 1.36 / -0.95 / 1.96 / -3.22 | 947 | -0.79 | 88.5 | 0.0109 | 0.108 | 1.83 | 0.52 | 18 / 14 / 32 | 30 | +0.86, 55 |
| 15 | 2,383-2,526 | 28.0 | 45 | 27 | 0.93 | 1.43 / -1.05 / 2.80 / -2.25 | 1,048 | 1.38 | 88.8 | 0.0109 | 0.099 | 1.71 | 0.50 | 19 / 24 / 52 | 45 | +2.10, 36 |
| 16 | 2,532-2,688 | 30.8 | 64 | 17 | 1.06 | 1.57 / -0.85 / 3.08 / -2.74 | 851 | 1.04 | 88.4 | 0.0107 | 0.096 | 2.24 | 0.59 | 20 / 37 / 44 | 31 | -0.83, 71 |
| 17 | 2,694-2,838 | 17.4 | 68 | 22 | -0.91 | 1.42 / -0.96 / 1.74 / -3.12 | 957 | -0.97 | 89.5 | 0.0112 | 0.103 | 1.59 | 0.52 | 12 / 14 / 31 | 38 | -0.51, 81 |
| 18 | 2,846-2,967 | 15.9 | 41 | 28 | -0.75 | 1.37 / -1.20 / 1.59 / -2.50 | 1,198 | -1.18 | 90.3 | 0.0113 | 0.115 | 1.19 | 0.31 | 15 / 14 / 25 | 51 | +1.88, 26 |
| 19 | 2,974-3,112 | 22.8 | 45 | 33 | 0.47 | 1.48 / -1.06 / 2.28 / -2.23 | 1,058 | 0.58 | 90.2 | 0.0098 | 0.084 | 1.51 | 0.49 | 23 / 19 / 28 | 55 | +0.40, 66 |
| 20 | 3,119-3,259 | 16.7 | 61 | 24 | -0.99 | 1.32 / -0.99 / 1.67 / -2.99 | 992 | -1.05 | 89.9 | 0.0115 | 0.108 | 1.46 | 0.35 | 9 / 19 / 33 | 42 | -0.94, 77 |
| 21 | 3,265-3,404 | 18.0 | 60 | 22 | -0.87 | 1.37 / -1.04 / 1.80 / -3.00 | 1,044 | -1.16 | 90.2 | 0.0116 | 0.103 | 1.42 | 0.40 | 13 / 7 / 53 | 38 | -1.14, 80 |
| 22 | 3,411-3,553 | 15.0 | 78 | 13 | -1.76 | 1.32 / -0.93 / 1.50 / -3.64 | 928 | -1.13 | 89.3 | 0.0111 | 0.107 | 1.54 | 0.35 | 14 / 9 / 25 | 24 | +0.32, 66 |
| 23 | 3,562-3,696 | 20.6 | 53 | 24 | -0.09 | 1.64 / -1.06 / 2.06 / -2.73 | 1,058 | -0.11 | 88.4 | 0.0108 | 0.097 | 1.75 | 0.56 | 21 / 18 / 27 | 42 | -0.06, 70 |
| 24 | 3,707-3,853 | 30.3 | 60 | 16 | 0.87 | 1.53 / -0.94 / 3.03 / -2.75 | 936 | 0.75 | 88.2 | 0.0109 | 0.091 | 2.07 | 0.45 | 22 / 36 / 35 | 28 | +0.30, 66 |
| 25 | 3,860-4,000 | 22.1 | 65 | 16 | -0.44 | 1.46 / -0.99 / 2.21 / -3.12 | 985 | -0.50 | 88.5 | 0.0108 | 0.102 | 1.48 | 0.55 | 16 / 16 / 56 | 28 | +1.57, 43 |
| 26 | 4,007-4,127 | 9.9 | 36 | 37 | -0.90 | 1.59 / -1.25 / 0.99 / -2.22 | 1,254 | -0.95 | 89.3 | 0.0118 | 0.119 | 0.63 | 0.42 | 11 / 4 / 33 | 66 | +0.39, 58 |
| 27 | 4,133-4,250 | 7.7 | 33 | 39 | -1.44 | 1.22 / -1.32 / 0.77 / -2.12 | 1,316 | -1.46 | 90.0 | 0.0111 | 0.109 | 0.51 | 0.54 | 5 / 4 / 20 | 68 | -0.31, 74 |
| 28 | 4,257-4,383 | 13.6 | 43 | 33 | -0.89 | 1.39 / -1.19 / 1.36 / -2.44 | 1,193 | -0.78 | 89.0 | 0.0104 | 0.095 | 1.15 | 0.29 | 8 / 9 / 32 | 56 | +0.41, 48 |
| 29 | 4,389-4,512 | 9.5 | 47 | 29 | -1.53 | 1.48 / -1.16 / 0.95 / -2.80 | 1,163 | -1.26 | 88.5 | 0.0112 | 0.106 | 0.85 | 0.24 | 7 / 15 / 6 | 53 | -0.98, 75 |
| 30 | 4,519-4,638 | 3.4 | 51 | 33 | -2.62 | 1.25 / -1.28 / 0.34 / -2.93 | 1,285 | -2.66 | 88.0 | 0.0117 | 0.121 | 0.45 | 0.43 | 0 / 0 / 16 | 52 | +0.31, 46 |

Columns: clear % and falls / horizon over the bin's finished episodes; mean R = mean undiscounted return; the four reward terms are means per
episode (target +1 per break, step -0.001 per policy tick, clear +10, failure -5, exactly as recorded: every episode's return equals the sum
of its terms to 1e-15); mean len = mean policy ticks; R_recent = `ep_return_mean_recent` at the bin's end; H % = policy entropy as a
percentage of ln 72 = 4.2767; strip / near / reh = clear rates by start region (n per bin in the working table); horizon tr % = share of the
bin's policy transitions spent in episodes that ended at the horizon; adv proxy = mean discounted-return-minus-V(tau) and the share of
episodes with a negative value. For comparison, s5's last four bins (rollouts 321-387, pointer 1,800 -> 1,780): clear 54.7-62.5 %, mean R
4.85-5.89, horizon transition share 5-19 %, strip 51-53 %, rehearsal 65-91 %.

**The first rollouts individually** (`q1_timeline.md`, "the first 30 rollouts"): rollouts 2-6 at pointer 1,780 (23-59 s, before the move)
cleared 5/6, 3/7, 3/7, 3/7, 2/6 (16 of 33, 48 %); the trigger fired at 65.1 s (8 of 18), the frozen strip test passed 10/19 with the re-checks
10/12 at 2,128 and 10/17 at 1,966, and the pointer moved at 128.9 s; rollouts 7-12 (140-181 s) cleared 17 of 36 (47 %); rollouts 13-30
(224-352 s) 31 of 100 (31 %); `ep_return_mean_recent` 5.20 -> 4.42 (59 s) -> 2.81 (277 s) -> 0.96 (352 s). The strip at 1,760 ran at 0.23
over its first 100 outcomes (149-495 s) and **0.08 over its second 100 (500-793 s), with 48 of those 100 episodes ending at the horizon** (26
on the floor with target 8 standing, 22 after target 8); then 0.30, 0.34, 0.32 (794-1,742 s), then 0.17, 0.16, 0.18, 0.16, 0.17, 0.11, 0.24,
0.13, 0.08 and 0.03 over the last 94. The rolling-100 strip rate peaked at 0.36 (1,333 s), was last at or above 0.30 at 1,882 s, 0.20 at
3,973 s, 0.10 at 4,238 s.

## 3. Answers to questions 1-5

### Question 1: the collapse timeline and the s5 warning signs

* **When the decline started relative to the move at 128.9 s.** The return and clear rate were already lower than s5's close in the first
  minute at pointer 1,780 (48 % against 55-62 %; small samples), the move did not produce a visible step, and the sustained decline is dated
  by the strip's second hundred (500-793 s) and by bins 2-4 (285-680 s): the horizon transition share went 23 -> 42 -> 35 -> 73 %, the clear
  rate 44 -> 30 -> 24 -> 12 %, the near region 39 -> 6 %, the rehearsal region 68 -> 21 %. So the decline began about 150-400 s after the move
  (within the first 0.15-0.4 M of the session's 3.07 M transitions) and reached its first trough 440-550 s after it.
* **Where episodes ended.** Non-clears by what they had achieved (the "fall A/B/C" and "hor A/B/C" columns of `q1_timeline.md`): falls before
  reaching the left floor (the new part of the route from 1,760) were rare throughout (0-5 per bin until bin 19, at most 11 per bin after);
  falls split about evenly between "on the floor with target 8 standing" (the 1,966 segment) and "after target 8, before target 1" (the 2,128
  segment); horizon endings were on the floor in both phases (bin 4: 23 with 8 standing, 18 after 8). The left floor was reached in 80-99 %
  of episodes in every bin, target 6 broken in 37-60 %, target 8 in 54-81 %, **target 1 in 61-70 % in bins 1 and 7 and in 7-20 % in bins
  26-30**. The mean end tick of falls stayed at 2,520-2,930 (the agent's own clock, not the trunk's). The skill lost first and most was the
  final drop to target 1, the same skill g1 lost.
* **Entropy, KL, clip fraction, value loss, explained variance.** Entropy 87.0 % after the first update, minimum 83.9 % (rollout 133),
  maximum 92.3 % (rollout 535), 87.5 % at the end (s5 ended at 85.2 %): a slow rise of 2-5 points, no spike. approx_kl 0.0098-0.0118 per bin
  (median 0.0110; s5 0.0109), clip fraction 0.084-0.126 (s5 0.093-0.120): the updates were of the same size as in every earlier session. Value
  loss fell from 2.4 to 0.45 as the returns became low-variance (mostly falls and horizons); explained variance 0.24-0.71, median 0.52
  (s5 median 0.57). Nothing in the optimizer's own readings marks the collapse; the collapse is visible only in the outcomes.
* **Reward components.** The clear term fell from 4.42 per episode (bin 1) to 0.34 (bin 30); the failure term stayed at -2.1 to -3.6 (42-73 %
  of episodes fell in every bin); the target term 1.2-2.0 (6 and 8 kept being broken); the step term grew from -0.83 to -1.28 as episodes
  lengthened (825 -> 1,285 policy ticks) with the horizon share.
* **Warning signs in s5.** After s5's move to 1,800 at 2,125.9 s (bins 7-8, 2,006-2,493 s): clear rate 62.8 -> 49.3 -> 40.1 %, mean return
  6.02 -> 3.75 -> 2.30, the strip at 1,800 at 0.23 over its first 100 (mean return -0.25), the failure term -1.35 -> -2.20 -> -2.80, falls
  with target 8 standing 5 -> 18 -> 27 per bin, the advantage proxy -1.35 / -1.73 with 57-65 % of episodes negative (bins 1-6: -0.2 to +0.3,
  42-56 %). s5 then recovered from bin 9 (2,501 s): 50-63 %, the strip 0.38 -> 0.51, the advantage proxy back around 0. **The same dip,
  shallower, with recovery.** Two slower signs in s5: the horizon transition share rose from 16-19 % (bins 1-2) to 31-34 % (bins 12-14) and
  22 % over the session, and the fall-with-8-standing count never returned to the 5-8 per bin of the first 1,800 s. After the move to 1,780
  at 4,770.6 s only 22 s of training remained (4 strip episodes, 2 clears): no reading. s5's audit also showed pessimistic start values
  (V(2,128) +5.68 against a realised +8.45; V(1,966) +1.74 against +4.88), i.e. the critic had not caught up with the policy's late competence.

### Question 2: the training distribution

Source: `runs/m9_g3/s{5,6}/training/episodes.jsonl` (`start.region`, `tau`, `policy_ticks`, `end_reason`, `breaks`); working file
`logs/m9_g3_stop_review/out/q2_distribution.json`.

| reading | s5 | s6 |
| --- | ---: | ---: |
| episodes / policy transitions / training wall | 2,623 / 1,981,440 / 4,792 s | 3,048 / 3,072,000 / 4,638 s |
| start regions, share of episodes (strip / near / rehearsal) | 50.7 / 30.5 / 18.8 % | 49.7 / 30.9 / 19.4 % |
| start regions, share of transitions | 56.4 / 31.0 / 12.5 % | 54.5 / 32.2 / 13.3 % |
| clear rate by region (strip / near / rehearsal) | 47.6 / 59.6 / 71.3 % | 18.4 / 23.8 / 40.8 % |
| episodes ending by clear / fall / horizon | 55.7 / 34.8 / 9.5 % | 24.4 / 53.5 / 22.1 % |
| transitions in episodes ending by clear / fall / horizon | 43.5 / 34.8 / 21.7 % | 16.0 / 44.8 / 39.2 % |
| mean policy ticks of clear / fall / horizon episodes | 589 / 755 / 1,724 | 661 / 842 / 1,791 |
| starts within 60 ticks of the final pointer (1,800-1,859 / 1,760-1,819) | 1,374 + 4 (52.5 %) | 1,997 + 488 (81.5 %) |
| starts at or after landing 1,966 / at or after 2,128 | 719 (27.4 %) / 208 (7.9 %) | 416 (13.6 %) / 199 (6.5 %) |
| episodes alive at tick 2,128 (started at or before it) | 2,201 | 2,600 |
| of which cleared / fell / horizon | 1,133 (51 %) / 822 / 246 | 529 (20 %) / 1,417 / 654 |
| episodes alive at tick 1,966 | 1,897 | 2,618 |
| of which cleared / fell / horizon | 963 (51 %) / 724 / 210 | 541 (21 %) / 1,446 / 631 |
| episodes that broke target 8 (entered the 2,128 phase) | 2,100: 1,377 cleared, 589 fell, 134 horizon | 2,306: 707 cleared, 1,144 fell, 455 horizon |
| successful traversals of 2,128 per 1 M transitions / per training hour | 572 / 851 | 172 / 411 |
| successful traversals of 2,128 by thirds of the session | 364 / 343 / 424 | 219 / 188 / 122 |
| rehearsal clear rate by thirds | 73.9 / 72.1 / 68.6 % | 51.9 / 41.3 / 30.5 % |

Answers: the region mix was the registered 50 / 30 / 20 in both sessions; **the frontier strip was not more dominant in s6 by share**, but the
whole start distribution was: because s6's pointer moved once and s5's twelve times, 81.5 % of s6's starts lay within 60 ticks of 1,760
against 52.5 % of s5's within 60 ticks of 1,800, and starts at or after the 1,966 landing halved (27 % -> 14 %). The later segments were
visited **more** often in s6 (2,600 episodes alive at 2,128 against 2,201) and traversed successfully **far less** (529 against 1,133; 172
against 572 per million transitions), with the count falling across s6's thirds (219 -> 188 -> 122) while s5's did not (364 -> 343 -> 424).
Horizon episodes, 22 % of s6's episodes, held 39 % of its transitions; s6 also hit the transition cap for the first time (its five attempts
paused training for 188 s against s5's 1,094 s), so it took 55 % more gradient steps than s5 in the same wall time, most of them on this data.

### Question 3: settings across the six resumes

Sources: `docs/rl_m9_g3_s{1..6}_approval.json` (`ppo`), each session's `training/checkpoints/final/{model.zip, curriculum_state.json,
checkpoint.json}` (the `data` member's fields, the `policy.optimizer.pth` member's `param_groups` and per-parameter `step`, `curriculum_state.ppo`,
`checkpoint.json.ppo`), `training/checkpoints.json` (initial and final members), `session/{final_state,training_summary}.json`, every
`training/rollouts.jsonl` row; working file `logs/m9_g3_stop_review/out/q3_settings.json`.

| setting | s1 | s2 | s3 | s4 | s5 | s6 | source |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PPO dict in the approval | identical in all six: `learning_rate` 3e-4, `batch_size` 512, `n_epochs` 10, `gamma` 0.999, `gae_lambda` 0.995, `clip_range` 0.2, `ent_coef` 0.01, `vf_coef` 0.5, `max_grad_norm` 0.5, net [64, 64] tanh, seed 0, rollout 5,120, no normalisation | | | | | | approvals; equal to `curriculum_state.ppo` and `checkpoint.json.ppo` of every final checkpoint |
| learning rate logged at every update | 3e-4 (only value) | 3e-4 | 3e-4 | 3e-4 | 3e-4 | 3e-4 | 137 / 224 / 368 / 387 / 386 / 599 rollout rows |
| clip range logged at every update | 0.2 | 0.2 | 0.2 | 0.2 | 0.2 | 0.2 | same rows |
| `learning_rate` in model `data` | float 3e-4 (constant, no schedule) | | | | | | `model.zip` `data` |
| `clip_range` in model `data` | `FloatSchedule` (constant 0.2); `clip_range_vf` None; `target_kl` None; `normalize_advantage` True | | | | | | same |
| Adam param group | lr 3e-4, betas (0.9, 0.999), eps 1e-5, weight_decay 0, 12 parameters | | | | | | `policy.optimizer.pth` |
| Adam step count (all 12 parameters) at the close | 13,800 | 36,300 | 73,200 | 112,000 | 150,700 | 210,700 | = 10 x `_n_updates` in every session |
| `_n_updates` at the close | 1,380 | 3,630 | 7,320 | 11,200 | 15,070 | 21,070 | + 10 per rollout (138 / 225 / 369 / 388 / 387 / 600 rollouts) |
| initial checkpoint members = predecessor's final members | - | yes | yes | yes | yes | yes | `checkpoints.json`; H12 byte check at the training start |
| training seed (`set_random_seed`) | 0 (fresh) | 1002 | 1003 | 1004 | 1005 | 1006 | `training_summary.resumed_seed` |
| `_num_timesteps_at_start` / `_total_timesteps` | 0 / 3,072,000 | 708,712 / 3,780,712 | 1,864,900 / 4,936,900 | 3,754,660 / 6,826,660 | 5,745,536 / 8,817,536 | 7,726,976 / 10,798,976 | model `data` |
| progress_remaining at the session start | 1.000 | 0.813 | 0.622 | 0.450 | 0.348 | 0.284 | 1 - start / total, as SB3 computes it with `reset_num_timesteps=False` |
| sticky p (curriculum state) / measured sticky rate | 0.25 / - | 0.25 | 0.25 | 0.25 | 0.25 / 0.2502 | 0.25 / 0.2501 | `curriculum_state.sticky_p`; `sticky_hits` / `policy_ticks` |

Findings: every learning setting was identical across s1-s6; the learning rate and the clip range are constants (no schedule), so the one
quantity that does change with the cumulative count and the number of resumes, SB3's `progress_remaining` (1.000 -> 0.284 at the session
starts), is consumed by nothing. The Adam state was carried bit for bit (the initial checkpoint's optimizer member equals the predecessor's
final member in every resume) and its step counts are continuous and exactly 10 per update. The only per-session differences are the
training seed (1000 + k, by design) and the restart of SB3's 100-episode return window at each `learn()`. The policy drift per 102,400
transitions, KL between consecutive checkpoints averaged over the trunk's 1,760-1,779 states, was 0.03-0.75 (median about 0.18) in s5 and
0.07-0.32 (median about 0.21) in s6: no acceleration with the resume count. The Adam second-moment estimates of the policy network's
parameters were about 3.3-3.9 times larger at s6's close than at s5's (and the value network's about half), i.e. the policy gradients were
larger and more consistent in direction late in s6; Adam normalises the step by them, so this changes nothing about the step size, and it is
reported as an observation, not a cause.

### Question 4: policy drift across the s6 checkpoints

**What observations exist.** Episode records keep actions (`submitted_hex`, `sampled_hex`, `sticky_mask_hex`) and a 17-number end summary,
and artifacts keep actions only (`initial_observation` and `final_observation` are null): **the per-tick observations of the agent's own s5
and s6 episodes are not saved**, and they were not reconstructed (no game run). What is saved is the v3 observation of every tick of the
agent's own verified rd4 route: the recorded replies in `runs/m8_rd_rd4/routes/T_clear/trace.json.gz` (sha256 equal to the registration's
pin) rebuilt offline with the repository's own builder into 2,327 observations whose digests equal the registered table
`runs/m9_g3/s6/lineages/T_clear/v3.bin` (and s5's) with 0 mismatches. Every training, probe and audit episode's **first** policy observation
is exactly that table's entry at its start tick (the recorded `stage.handover_v3` digests equal `v3.bin[tau]`), so the policies were compared
at the handover states of every saved episode and along the whole route; nothing past the handover is claimed. Validation of the offline
network: it reproduces the recorded `start_value` and `start_entropy` of the s5 and s6 audits at 2,128, 1,966 and 1,694 to four decimals,
the recorded first word of every deterministic audit episode, and the recorded `start_value` of 6 probe episodes of every one of the 26 s5
and s6 attempt snapshots (max difference 0.0001); s6's initial checkpoint gives bit-identical outputs to s5's final. 78 policies were loaded
(s5: 21 checkpoints + 21 attempt snapshots; s6: 31 checkpoints + 5 snapshots). Working file `logs/m9_g3_stop_review/out/q4_drift.json`.

| s6 checkpoint (j x 102,400 after the start) | KL from s5 final, mean per segment: 1694-1759 / strip 1760-1779 / 1780-1819 / 1820-1965 / 1966-2127 / 2128-2325 | V(1,760) | V(1,966) | V(2,128) | V(2,300) | H % at 2,128 | geometric-mean p of the first word of s5's 1,451 clears |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| j = 0 (= s5 final) | 0 / 0 / 0 / 0 / 0 / 0 | 3.19 | 1.74 | 5.68 | 11.62 | 91.4 | 0.0148 |
| 1 (the move made) | 0.18 / 0.24 / 0.16 / 0.22 / 0.15 / 0.16 | 2.13 | 0.34 | 5.50 | 11.50 | 88.2 | 0.0139 |
| 2 | 0.52 / 0.27 / 0.19 / 0.32 / 0.25 / 0.31 | -0.08 | 2.37 | 3.63 | 1.08 | 91.4 | 0.0130 |
| 3 | 0.38 / 0.41 / 0.29 / 0.49 / 0.42 / 0.49 | 0.27 | 0.38 | 6.46 | 11.20 | 89.3 | 0.0143 |
| 4 (the trough) | 0.64 / 0.58 / 0.37 / 0.54 / 0.43 / 0.61 | 0.21 | 0.18 | 0.18 | -3.51 | 80.8 | 0.0154 |
| 6 (the recovery) | 0.49 / 0.61 / 0.35 / 0.54 / 0.40 / 0.58 | -0.94 | 1.28 | 5.88 | 11.43 | 86.6 | 0.0148 |
| 7 (= snapshot of attempt 71) | 0.85 / 1.42 / 0.88 / 0.77 / 0.54 / 0.62 | -0.17 | 1.94 | 5.61 | 10.85 | 83.3 | 0.0136 |
| 9 | 0.74 / 1.10 / 0.79 / 0.85 / 0.62 / 0.78 | 3.64 | 1.46 | 5.25 | 7.31 | 90.8 | 0.0132 |
| 12 | 0.66 / 1.19 / 1.11 / 0.99 / 0.68 / 0.77 | 0.34 | 2.16 | 5.25 | 10.69 | 89.9 | 0.0109 |
| 14 | 1.02 / 1.58 / 1.24 / 1.22 / 0.81 / 0.90 | -1.28 | -1.79 | -1.22 | 2.80 | 93.1 | 0.0118 |
| 18 | 1.36 / 1.74 / 1.46 / 1.07 / 1.05 / 1.07 | -0.77 | -0.49 | -0.20 | 0.07 | 90.3 | 0.0105 |
| 20 | 1.15 / 1.35 / 1.10 / 1.07 / 0.90 / 1.39 | 0.93 | -1.07 | 8.30 | 13.74 | 94.0 | 0.0096 |
| 24 | 0.90 / 1.26 / 0.97 / 0.89 / 1.04 / 1.60 | -2.15 | -0.56 | 4.59 | 0.02 | 88.9 | 0.0097 |
| 26 | 0.86 / 1.30 / 1.04 / 0.94 / 0.97 / 1.50 | 0.56 | -0.38 | -0.85 | -3.97 | 82.6 | 0.0089 |
| 29 | 1.10 / 1.38 / 0.99 / 1.11 / 0.98 / 1.41 | -0.13 | -1.41 | -2.52 | -3.61 | 83.0 | 0.0074 |
| final (j = 30) | 0.99 / 1.07 / 0.79 / 1.02 / 1.00 / 1.55 | -1.08 | -2.45 | -2.75 | -4.96 | 91.9 | 0.0075 |
| uniform policy | - | - | - | - | - | 100 | 0.0139 |

Readings:

* **Magnitude.** s6's final policy sits at KL 0.8-1.6 nats per state from s5's final. That magnitude alone is not the collapse: s5's own
  final policy sits at KL 0.9-2.3 from s5's start (s4's final) after fewer transitions, and s5 improved. The per-interval drift was the same
  in both sessions (about 0.2 nats per 102,400 transitions). What differs is the direction and the outcomes along it.
* **Where the drift concentrates.** Over the whole session the strip 1,760-1,779 drifted most (1.07-1.79 from j = 7 on) together with the
  1,694-1,759 states beyond the pointer (never trained); from j = 20 on the **2,128-2,325 segment** (the drop to target 1) overtook every
  other segment (1.39-1.60) while the 1,780-1,819 and 1,966-2,127 segments stayed at 0.8-1.1. The segment that drifted most late is the
  one whose skill the audit found lost (1 of 20 at 2,128), and its entropy rose from 76 % to 85 % of maximum (s5 final -> s6 final).
* **The first taken actions of the agent's own successful episodes.** Under s5's final policy the first sampled word of s5's 1,451 clears
  had a geometric-mean probability of 0.0148 (uniform 0.0139); under s6's final policy 0.0075, about half of uniform. The same shift applies
  to the first words of s5's falls (0.0146 -> 0.0082) and horizon episodes (0.0162 -> 0.0080): the policy moved away from all of s5's
  start actions, not selectively from the clearing ones. The first words of s6's own clears had 0.0119 under s5 final, rose to 0.0165-0.0171
  at j = 6-11 (the recovery), and fell to 0.0105-0.0114 at the end, while s6's own falls' first words ended higher (0.0122) than its clears'.
  One word of 72 at the handover is a weak discriminator; the reading is consistent with a general shift, and it does not locate the loss
  in the first action.
* **The critic.** V(1,760), the start the policy saw most, fell from 3.19 (s5 final) to about 0 from j = 2 onward and stayed within -2.2 to
  +1.2 for 28 checkpoints: the critic learned that a strip start was worth nothing, which was true of the collapsed policy (the strip's mean
  return per 100 ran -1.9 to +1.8). V(2,128) and V(2,300) swung by up to 14 between neighbouring checkpoints (8.30 / 13.74 at j = 20,
  -0.85 / -3.97 at j = 26), as g1's late values did: rarely visited states with a poorly pinned critic. The final values are negative
  everywhere (V(1,966) -2.45, V(2,128) -2.75, V(2,300) -4.96), the critic having fitted the collapsed policy (the audit's gaps were +0.21,
  +1.41, +0.51; s5's were -2.78, -3.14, -0.46).
* **The attempt snapshots.** Attempt 68's snapshot (MOVED, at 6 rollouts) was within KL 0.03-0.09 of s5 final; attempt 69's (8/19 at
  182 s) already had V(1,760) = -0.47 at KL 0.11-0.21; attempts 70-72 (4/15, 4/15, 3/14 at 1,017-1,650 s) were at KL 0.43-1.42 and sat
  inside the partial recovery (the live strip rate 0.32-0.37), so the frozen tests sampled a policy that had recovered at the landings
  (V(2,128) 4.7-5.6) but not at the strip.

### Question 5: comparison with g1's "lucky moves, then forgetting"

| aspect | g1 (`docs/rl_m9_g1_diagnosis_2026-10-04.md`) | s6 (this review) |
| --- | --- | --- |
| trigger | 9 of 16 moves unbacked; the last three into a strip at 3.5-11.7 % success; the block rule had no repeated-testing control | one move, passed on a frozen strip test 10/19 with re-checks 10/12 (2,128) and 10/17 (1,966); the strip's first 100 ran at 0.23, the same as s5's 1,800 strip |
| start distribution | 85 % of starts on the first left-floor segment where 85-90 % fell | 81.5 % of starts within 60 ticks of 1,760; falls were on the floor and at the final drop, not in the new ticks |
| what grew, what was lost | the climb to target 8 grew while the final drop to target 1 was lost | nothing grew: the strip, the near window and the rehearsal region all decayed (38 -> 0 %, 39 -> 0 %, 68 -> 16 %) |
| later segments still visited | yes (about 200 practice episodes per 500) and still decayed | yes (2,600 episodes alive at 2,128) and still decayed (clears after reaching 2,128: 219 -> 188 -> 122 by thirds) |
| horizon-waiting | horizon endings 1 -> 55 per 500 episodes; 66 % of the transitions of the last 64 episodes | 672 horizon episodes, 39 % of all transitions; 52-73 % of the transitions of the trough and the final bins |
| entropy | 90 %+ of maximum throughout | 84-92 %, a slow rise |
| late values | collapsed (V(2,300) -3.96 at the end; swings of up to 14 between checkpoints) | collapsed (V(2,300) -4.96; the same swings) |
| optimizer readings | normal | normal (same KL, clip fraction, per-interval drift as s5) |
| best state reachable | the 409,600 checkpoint (9/20 at 2,128) would not have passed the gate | s5's final (17/12/10 of 20) is the line's best registered state; the first s6 checkpoint was within KL 0.15-0.24 of it |

Same end state and the same sign (loss of the final drop while it is still being visited, growth of horizon-waiting, negative late values),
different trigger. g1's chain began with a frontier that measured persistence, not competence; the g3 frontier removed that (the move was
earned and re-checked), and the collapse happened anyway. The shared ingredient is what the two have in common downstream of the trigger:
under reward v2 with gamma 0.999 and a 3,600-tick horizon, once the clear probability from a start is low, waiting beats attempting.

## 4. Candidate explanations

Computed from the recorded reward events with gamma 0.999: a clear from the 1,760-1,819 starts was worth +6.1 to +8.1 in discounted return
(mean per bin, `G_clear`), a fall -1.5 to -2.1 (`G_fall`; the -5 arrives 500-900 ticks after the handover), a horizon episode -0.4 to +0.3
(`G_horizon`; one or two targets broken, 1,800 ticks of -0.001). The expected discounted return of attempting is therefore about
p x 7 + (1 - p) x (-1.8), and of waiting about 0: **attempting beats waiting only while p, the clear probability, exceeds about 0.2.**

| candidate | evidence for | evidence against | verdict |
| --- | --- | --- | --- |
| (a) the 1,760 strip was mostly failures, so training data was dominated by failure and later segments were forgotten | the strip ran at 0.08-0.34 per 100 and 0.184 over the session; 50 % of starts and 54.5 % of transitions came from it; the later segments' successful traversals fell 1,133 -> 529 and the rehearsal clear rate 74 -> 31 % by thirds; 81.5 % of starts lay within 60 ticks of the pointer | the failures were not in the new 20 ticks (falls before the left floor 0-5 per bin until bin 19; the floor was reached in 80-99 % of episodes), so the strip episodes themselves were traversals of the later segments; every region decayed in the same bins, the strip included; s5's 1,800 strip also started at 0.23 and recovered within 500 s; the share of strip starts was the registered 50 % in both sessions | **true as a description, not supported as the mechanism**: the failure-dominated data is the symptom the mechanism produced |
| (b) optimizer or schedule state across many resumes | none: lr and clip constant in every logged update; no schedule consumes `progress_remaining`; Adam moments and step counts carried bit for bit; the drift per 102,400 transitions was the same in s5 and s6 | all of the above (section 3, question 3) | **ruled out** |
| (c) value and advantage dynamics (critic fitting failures well, negative advantages everywhere, entropy rising) | after the move the critic kept s5's optimism (mean V(tau) 3.84 in bin 2) while returns fell (mean G 1.16): 78 % of start-state advantages negative in bins 2 and 4; the critic then followed the returns down (V(1,760) about 0 from j = 2 on, V(tau) 0.6-1.4 by bins 3-5), after which falls carried negative advantages (-1.2 to -5.6), horizon episodes about zero or slightly positive (+0.3 to +1.9 in bins 14-30), and clears, rare (1-15 % of episodes per bin late), large positive ones; with 5,120-transition rollouts holding only 4-8 episode endings, 0-2 of them clears, the per-update signal was dominated by "falling is bad"; the policy moved toward the safe behaviour (horizon share 52-73 % in the worst bins), which lowered p further; entropy rose 2-5 points; value loss fell to 0.45 as the returns became predictable | the critic's explained variance never collapsed (0.24-0.71) and its final start values were well calibrated to the collapsed policy; the critic was not the origin of the first dip (it reacted to lower returns) | **supported as the proximate mechanism**, together with the reward structure that makes waiting the better discounted choice once p < 0.2; what first pushed p below the threshold at 1,760 (and not at 1,800 in s5) is not decided by this evidence: the first 100 strip outcomes were identical (0.23) in both cases |
| (d) the entropy coefficient or sticky actions interacting with a harder strip | the policy stayed at 84-92 % of maximum entropy, so most sampled words at the handover are near-uniform draws, and sticky actions repeat a quarter of them; a harder start could tip p below the threshold at the same entropy | neither quantity varied across s1-s6 (0.01 and 0.25 everywhere, measured 0.2501), so no contrast exists; falls before the left floor stayed rare, so the new ticks were not measurably harder to survive | **cannot be decided** from this evidence |
| (e) an implementation defect: a discrepancy between logged behaviour and the line contract | none found: reward constants exact (+1, -0.001, +10, -5) and every return equal to its terms; sticky rate 0.2501; regions 49.7 / 30.9 / 19.4 against 50 / 30 / 20; the horizon is signalled as a truncation and bootstrapped as the contract says; 600 rollouts x 5,120 = 3,072,000 = the cap; Adam +60,000 steps; the spacing and trigger history rebuilt from the records by verify-run; the attempt-71 snapshot is bit-identical in outputs to the checkpoint written at the same boundary; the offline network reproduces every recorded start value, entropy and deterministic first word; 0 lifecycle failures | - | **no defect found**; two contract properties shaped the data without being defects: the 3,600-tick horizon makes a waiting episode 1,800 transitions long, and the transition cap let s6 take 55 % more updates than s5 in the same wall time |

What the evidence supports: (c) with the reward-structure threshold. What it rules out: (b), and (e) as far as the records can show. What it
cannot decide: (d), and the initial cause of the first dip at 1,760 (the dip itself, 0.23 over the first 100 strip outcomes, is identical to
s5's at 1,800; s6's did not recover, s5's did). No cause beyond these is claimed.

## 5. A checkpoint evaluation that would locate the collapse (design only; not run, not authorised)

**Purpose.** Measure, with the registered audit procedure, when the landing competence of s5's final policy was lost during s6, whether the
partial recovery at 833-1,194 s restored it, and whether the loss was of the perturbed skill only or of the unperturbed one too.

**Policies** (every one pinned by the sha256 of its `model.zip` recorded in `runs/m9_g3/s6/training/checkpoints.json`, loaded weight-only
as `rl/m9_eval_policy.PinnedPolicy` does, no optimizer): s5 final = `ckpt_007726976` (the reference; its audit is already recorded, so it is
re-measured only to pair the keys), `ckpt_007829376` (j = 1, the move made), `ckpt_007931776` (j = 2), `ckpt_008136576` (j = 4, the trough),
`ckpt_008443776` (j = 7, the recovery and the attempt-71 snapshot), `ckpt_008853376` (j = 11, the second decline begins), `ckpt_009160576`
(j = 14), `ckpt_009672576` (j = 19), `ckpt_010184576` (j = 24), `ckpt_010696576` (j = 29) and `final`: 11 policies. A trimmed variant: j = 1,
4, 7, 14, 24 and final (6 policies).

**Starts.** The three audited landings 2,128, 1,966, 1,694 (paired with the s1-s6 audits and the tape by the same `m9|g2|reach|<landing>|<k>`
keys), plus the strip 1,760-1,779 and the strip 1,780-1,799 with keyed starts as `rl/m9_g3_frontier.strip_start` draws them (so the frozen
strip tests of attempts 68-72 are comparable). **Modes.** 20 sticky (p = 0.25, the training and decision mode) and 20 unperturbed episodes per
cell with common keyed draws across policies (as the g1 evaluation did: the action key names the start and the index, not the policy), plus
1 deterministic episode. **Cells.** 11 x 5 x (20 + 20 + 1) = 2,255 episodes; trimmed 6 x 5 x 41 = 1,230.

**Cost.** s6's audit ran 144 episodes in 460,529 ticks (3,198 per episode, prefix included) and 230.9 s, about 2,000 ticks per second with
10 processes; the g1 evaluation ran 675 episodes in 1,145 s. Full design: about 7.2 M native ticks and 60-70 minutes of evaluation wall, plus
verification replays of every claimed clear (2,100-2,350 ticks each; with 300-600 clears, 0.7-1.4 M ticks and 6-12 minutes), plus P1 and the
preflight suites (zero ticks, about 30 minutes). Trimmed: about 3.9 M ticks and 35-40 minutes of evaluation. Memory as the s6 session (peak
tree private 6.8 GB, 10 BattleShip processes).

**What each result would tell.** (i) j = 1 already below s5's final at 2,128 / 1,966 / 1,694 (17 / 12 / 10): the loss began within the first
102,400 transitions, 5 minutes after the move, before the strip's second hundred; j = 1 equal to s5's final and j = 2 or 4 low: the loss
coincides with the horizon-waiting onset of bins 2-4. (ii) j = 7 back at or near s5's levels: the collapse was reversible by continued
training at that point and the line's rule (final policy only) measured an unlucky end state; j = 7 still low while its strip cells are at
the frozen tests' 4/15: the recovery at the strip did not restore the landings. (iii) A monotone decline from j = 1 to the final: one drift
with no recovery, and keep-best selection (section 6) would have selected the first checkpoint. (iv) Sticky far below unperturbed in the same
cell: the loss is of robustness under perturbation first (as g1's 2,250 cell); both low: the skill itself is gone. (v) The 1,760 and 1,780
strip cells across policies date the loss of the frontier skill relative to the landing skills.

**Why it cannot change a registered g3 outcome.** `m9_g3_s1_rule_v1` audits the final policy of a session and nothing else; `m9_g3_line_rule_v1`
consumed the six recorded rows and registered END_BUDGET_1694, which permits no s7; the runbook's rule 9 and section 10 of the s6 record make
every diagnostic "reported, never deciding". The evaluation would be its own tree (a new `runs/m9_g3_eval/` or similar) with its own
approval, snapshot and increment, writing nothing under `runs/m9_g3/s6` (a protected tree) and reading the checkpoints by pin only. It would
inform a future line's design; it would not reopen this one.

## 6. Options for a future robustification line (not decisions; generic and stage-agnostic)

| option | what it is | what it would have changed in s6 | cost | risk |
| --- | --- | --- | --- | --- |
| 1. rehearsal of passed landings during training | a fixed share of starts drawn at each landing the line has passed (for example 10 % per passed landing), in addition to the pointer's strip, near and rehearsal regions | more successful traversals of 2,128 and 1,966 early (the rehearsal region still cleared 50-70 % in bins 1-7); it would not by itself remove the horizon attractor at the frontier starts, and the landing starts would decay with the rest if the policy entered it | fewer frontier transitions per session (slower pointer progress); a contract change (the start distribution is in the registered frontier contract), hence a new line | masks a weak frontier without fixing it; if the policy enters the attractor the rehearsal starts become horizon episodes too (s6's rehearsal starts ended at the horizon 86 times) |
| 2. regression-triggered rollback under a registered rule | every N rollouts a registered statistic is read (the trailing clear rate of near + rehearsal starts, or a frozen probe at the last passed landing); below a registered floor for two consecutive windows, the session restores the last checkpoint that was above the floor (model and optimizer) and un-moves the pointer by one strip | the trigger would have fired at bins 3-4 (rehearsal 55 -> 21 %, clear rate 24 -> 12 %, two windows below any floor near 40 %): rollback to `ckpt_007829376` or s5's final and the pointer back to 1,780 at about 600 s; s5's dip at 1,800 (bins 7-8) would also have fired under a one-window rule and would not under a two-window rule, since s5 recovered in bin 9 | probe episodes or none (training statistics are free but non-paired); lost training between the breach and the detection (one or two windows, 100-200 k transitions); a rule to register (statistic, floor, persistence, what is restored) | oscillation (repeated rollbacks at a hard strip consume the session); rolling back a transient that would have recovered; the "pointer never moves forward" invariant of the registered frontier is broken, so the depth measure changes meaning |
| 3. keep-best with a pre-registered selection rule | the session's audited policy and the state the next session resumes from is the checkpoint with the best registered selection score (a frozen probe at the passed landings run at every checkpoint, or the trailing training clear rate), not the final | by training clear rate the selected checkpoint would have been `ckpt_008443776` (bin 7, 46 %) or the initial one; D_6 might have been 1,694 again (CONTINUE under END_BUDGET_1694, no progress) rather than NULL; the line would have continued without advancing | a probe per checkpoint (30 x about 60 episodes, about 1,800 episodes, roughly a quarter of a session's ticks) or none with training statistics; the per-session rule changes from "final policy" to "selected policy" | selection on noisy 20-episode probes is optimistic (winner's curse), so the selected state's measured competence overstates it; resuming from a mid-session checkpoint also resumes its optimizer state and discards the later frontier state, which must be registered |
| 4. learning-rate or update-size changes | a smaller learning rate (1e-4), fewer epochs per rollout (10 -> 3 or 4), a `target_kl` stop, or larger rollouts (5,120 -> 20,480 so that each update sees about 20 episode endings instead of 4-8) | slower drift per transition (the collapse took about 0.4 M transitions to its trough; a three-times smaller step would have delayed, not prevented, it if the gradient's direction is the same); larger rollouts lower the variance of the per-update advantage signal, which in s6 was built from 0-2 clears among 4-8 endings | slower learning per transition (s5's 12 moves took 2 M transitions; the line's budget is per session); a PPO value change is refused by the resume by design, hence a new line | may be too slow to reach a milestone within the line budget; does not change the sign of the attractor (waiting still beats attempting once p < 0.2) |
| 5. a start-tick budget instead of the fixed 3,600-tick horizon | end a policy phase after a registered number of policy ticks from the handover (for example 900, against the 566 ticks the trunk needs from 1,760 to its clear), bootstrapped as a truncation as now | a waiting episode would hold 900 transitions instead of 1,800 and could not dilute the data to 39-73 % of the transitions; the discounted value of waiting stays about 0, so the attractor's sign is unchanged but its data share halves | a change to the registered horizon (`m9_contract.HORIZON` is part of every line contract), hence a new line; the tape baseline and the audits would need re-measuring under the new horizon | an episode budget that is too tight truncates slow clears (the agent's own clears took 589-661 policy ticks on average, up to much longer) |
| 6. a two-sided, re-checked frontier | the strip test is re-run at the current pointer after a registered number of failed attempts or windows; on repeated failure the pointer moves forward one strip (to the last strip that passed) and the spacing resets | after attempts 70-71 (1,017-1,201 s, 4/15 and 4/15) the pointer would have returned to 1,780, where the policy had passed 10/19; the second decline (1,800 s onward) might still have occurred at 1,780 | a frontier contract change, hence a new line; probe episodes as now | the pointer oscillates between two strips; the depth D stops being monotone, so the line budget's "D_k earlier than D_j" clauses need redefining |

Options 1-4 are the ones asked for; 5 and 6 follow from the mechanism in section 4. None is recommended here; every one changes a registered
contract or rule and is therefore a new line with a fresh approval, and every one would be judged against the same question: does it keep
the clear probability from the active starts above the attractor's threshold while the pointer moves back.

## 7. The s5 final state (read-only confirmation)

`runs/m9_g3/s5/training/checkpoints/final/model.zip` sha256 `382dde881fb6618bbcedc9bc68e0fcce4f9f050167fd6910cb32d930fee0028a` (1,111,718 bytes),
members `policy.pth` `f3e0dc3257e03ed2ea1dbba0d68ffb53e7b85dd9606538b44f1d896203e76ffc` and `policy.optimizer.pth`
`e3a78f5b4f6792639f50c80bd5ec4dd3f187330f3001464c514e4c579dbcd861`; `curriculum_state.json` `147467caec3847b922026ea943f4b72c1893aec0a2c6e998a45e12624a1e3400`
(14,948 bytes; pointer 1,780; f 0 / need 0 / have 4; sessions [1..5]; num_timesteps 7,726,976; next_episode 17,100; attempt_counter 67);
`session/final_state.json` `5849fbd382240741a9a8acd57a64f4ce4adff3f833c4ced84ade0d552b0f87e8` (counters 7,726,976 / 15,070 / Adam 150,700 on 12
parameters; next session seed 1006; line CONTINUE); `input/tape_baseline.json` `81fa52c21078b2c2...`. Each of the four files hashes to the
same value in `runs/m9_g3/s5`, in the increment `D:\BattleShip_runs_backup\2026-10-09_incr_m9_g3_s5\runs\...` and in the increment's
`manifest.tsv.gz` row (4,302 rows; manifest sha256 `2e632bbfcc09f6f1c66b945d0276dbed813e6966275c130d158ac6925bda28ef`, equal to the recorded
one; the increment's `verification.json` PASS, 4,302 files, 504,067,346 bytes, 0 hash mismatches). The two model members equal the recorded
digests in both copies. **Present and matching: PASS** (`logs/m9_g3_stop_review/out/s5_state_check.json`, `s5_manifest_rows.txt`). It is the
line's best registered state (17 / 12 / 10 of 20 at 2,128 / 1,966 / 1,694) and the first s6 checkpoint's members are byte-identical to it.

## 8. Open questions only the owner can answer

1. Is the checkpoint evaluation of section 5 worth its cost (about 4-8 M native ticks, 1.5-2 hours with the preflight), given that it can
   inform a future line but cannot change this one?
2. May a future line change a registered contract value (reward v2, the 3,600-tick horizon, the start distribution, a PPO value), or must
   it keep the s1-s6 recipe and change only the session procedure (rollback, keep-best, selection)?
3. If keep-best or rollback is used, is a rule that audits a selected or restored policy instead of the final one acceptable, and what is the
   registered selection statistic (frozen probes, which are paired but costly, or training statistics, which are free but biased)?
4. Should a future line warm-start from s5's final state (the best registered state, pointer 1,780) or from a fresh seed, and in the former
   case does the frontier resume at 1,780 or further back toward the end?
5. Is the END_BUDGET structure (D at or before 2,128 / 1,966 / 1,694 at k = 2 / 4 / 6) to be kept, and what counts as progress when a
   session only has to hold a depth already reached?
6. What per-session probe budget is acceptable (s5 spent 23 % of its training wall on 21 attempts; a per-checkpoint probe would cost about as
   much again)?
7. Should the speed-search proposal (`docs/rl_m8_sd1_proposal_2026-10-07.md`) take priority over another robustification line?
8. Does the owner want the attractor hypothesis tested offline further before any design (for example, by recomputing the discounted returns
   under alternative horizons from the recorded events, which needs no game run)?

## 9. What this review does and does not say

* It says: the collapse began early in s6, across every start region, as a drift into horizon-waiting; the optimizer and the settings were
  identical to the five earlier sessions and show no anomaly; the proximate mechanism in the evidence is the value and advantage dynamics
  under a reward structure in which waiting beats attempting once the clear probability from the active starts falls below about 0.2; s5 had
  the same dip after its last hard move and recovered; g1 ended in the same state by a different trigger.
* It does not say what first pushed the 1,760 starts below the threshold when the 1,800 starts had recovered from the same first-hundred
  rate; it does not evaluate any checkpoint (none was run); it claims nothing about other seeds, budgets or recipes; it changes no registered
  outcome and authorises nothing.
* Constraints kept: zero native ticks; no tracked file modified; nothing written under `runs/`, D:, or any directory of a snapshot set; no
  RNG seed inspected, logged, controlled, compared or hashed; no human recording, TAS or fixture used in any form; the trunk observations
  were rebuilt from the agent's own recorded route, not by running the game.

## 10. git status at the end

HEAD = `origin/main` = `f0f17ca5d805983ab13b6b6d57cdbbdbed4d8a16`; no commit, push, branch or pull request; nothing staged; `git diff --check`
clean; `git status --porcelain --untracked-files=all` shows only the new file `docs/rl_m9_g3_stop_review_2026-10-10.md`
(`logs/m9_g3_stop_review/` is Git-ignored).

## 11. Files read and created

**Read (tracked):** `CLAUDE.md`; `docs/rl_runbook.md`; `docs/rl_m9_g3_progression_fix_2026-10-08.md`; `docs/rl_m9_g3_resume_k_prep_decisions_2026-10-08.md`;
`docs/rl_m9_g3_s1_results_2026-10-07.md`, `docs/rl_m9_g3_s2_results_2026-10-08.md`, `docs/rl_m9_g3_s3_results_2026-10-09.md`,
`docs/rl_m9_g3_s4_results_2026-10-09.md`, `docs/rl_m9_g3_s5_results_2026-10-09.md`, `docs/rl_m9_g3_s6_results_2026-10-10.md`;
`docs/rl_m9_g3_s{1..6}_approval.json`; `docs/rl_m9_g1_diagnosis_2026-10-04.md`; `rl/m9_g3_train.py`, `rl/m9_g3_frontier.py`, `rl/m9_g3_contract.py`
(constants), `rl/m9_g2_train.py`, `rl/m9_g2_resume.py`, `rl/m9_g2_policy.py` (part), `rl/m9_eval_policy.py`, `rl/m9_obs.py`, `rl/m9_vec.py` (the reward
and termination code), `rl/btt_rewards.py` (the v2 constants), `rl/m9_curriculum.py` and `rl/m9_contract.py` (constants), `rl/m9_g3_probe.py` (grep).

**Read (evidence, Git-ignored):** `runs/m9_g3/s5` and `runs/m9_g3/s6`: `training/{rollouts,episodes,windows,moves,attempts,probes,stale,withdrawn}.jsonl`,
`training/checkpoints.json`, every `training/checkpoints/*/{model.zip,curriculum_state.json,checkpoint.json}` (21 and 31 checkpoints, read-only, pins
checked), `training/attempts/a*/snapshot_policy.pth` (26 snapshots), `audit/episodes.jsonl`, `session/{open,final_state,training_summary,line,rule}.json`,
`lineages/{registry.json,T_clear/*}`, one artifact directory; `runs/m9_g3/s{1..4}/training/{rollouts,checkpoints}.json(l)` and the final checkpoints
(settings only); `runs/m9_g1/training/episodes.jsonl` (the g1 comparison); `runs/m9_g1_eval/derived/part_a/part_a_values.py` (the g1 method);
`runs/m8_rd_rd4/routes/T_clear/trace.json.gz`; `D:\BattleShip_runs_backup\2026-10-09_incr_m9_g3_s5\{verification.json,manifest.tsv.gz}` and the four
backed-up state files.

**Created (new files only):** this record; `logs/m9_g3_stop_review/a_timeline.py` (question 1), `b_distribution.py` (question 2), `c_settings.py`
(question 3), `d_drift.py` (question 4 and the advantage proxy), `e_s5_state.py` (section 7); outputs under `logs/m9_g3_stop_review/out/`:
`q1_timeline.md`, `timeline_s5.json`, `timeline_s6.json`, `q2_distribution.json`, `q2_distribution_stdout.txt`, `q3_settings.json`, `q4_drift.json`,
`q4_drift_stdout.txt`, `s5_state_check.json`, `s5_state_check_stdout.txt`, `s5_manifest_rows.txt`. No compiled module was written under `rl/`
(every run `python -B -X utf8`).
