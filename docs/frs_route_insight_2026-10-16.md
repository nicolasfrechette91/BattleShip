# Route-insight report 1: what the agent has explored and found (2026-10-16)

Offline design-study record. Zero native ticks: no game, lab command, suite, launcher or build was run. Everything below is
read from existing lab records under `C:/BattleShip_lab/` (read-only) and from the per-tick caches that the anomaly inventory
built under `logs/frs_anomaly/cache/` (read-only). Working files are under `logs/frs_route/` (Git-ignored). Git: `main` at
`5047fba`, working tree clean apart from this record; nothing committed, pushed, branched or stashed.

**What this record is.** The first route-insight report asked for in `docs/rl_decisions_2026-10-16_addendum.md`, part 4 (c):
the target orders the agent used, a segment map, arrival times at moving geometry, and the design of a timing-robustness check.
It has two readers: the owner, who wants to know whether the agent found anything new about routes, and the design of tier 1
stage 2 (`docs/rl_decisions_2026-10-16.md`, the order-diverse right-side arm), which needs to know how concentrated the search
has been on one target order.

**What this record is not.** It describes data. It proposes no route. Target ids, ticks, classes and coordinates appear only as
descriptions of the agent's own trajectories, and nothing in this record may be used as a hint, waypoint, target order,
selection weight or threshold in any rule. No RNG state or seed was read, logged, compared or discussed. No TAS, human recording,
owner time or external time was read, mentioned or used. The record decides nothing and launches nothing.

**Reading key.** A "trajectory" is one burst: one dispatch of the lab runs, one ledger burst of the imported archive, or one
seed replay of the frontier search. Ticks are input ticks (the tick at which the state shows the break; the archive's `L`,
the dispatch rows' `breaks_after_start` and the traces' `break_input_tick` all use this convention). "Level" is the number of
targets broken. A "class" is the archive's resource class at a tick (G grounded; A2 airborne with double jump and up-B; A1
airborne, up-B only; A0 airborne without up-B, that is up-B in progress or helpless; X damage, dead, appear or other), as
defined by the committed classifier `rl/m8_rd_cells.py`, read-only.

## 0. Summary

- **Coverage.** The catalogue covers all 133,004 trajectories the lab has records of: the 21,323 ledger bursts of the sd2
  archive import (sessions rd1 to sd2), the smoke run's 383, the trail probe's 3,960, the frontier search's 37,330 (37,194
  bursts and 136 seed replays), crossing run 1's 30,699 and run 2's 39,309. Their histories were rebuilt with zero link
  mismatches (section 1.1). The verified clears come from 312 verification rows and replays (304 lab verifications, the splice
  probe's 9 twice-replayed clears, the reference). The M7 learning runs and the M9 curriculum have no break-sequence records in
  the lab and are not covered.
- **One macro-order, three order families.** By target set the search has explored one family: at levels 6 and 7, 94.9 %
  and 99.5 % of all trajectories have broken the same targets ({0,3,4,5,7,9}, then {0,2,3,4,5,7,9}); at levels 8 and 9 the
  sets differ only in which of the last three targets came first. The orders differ only in the permutation of the first five
  targets and in the order of the last three. By order, three families hold
  98.2 % of the level-7 trajectories (4-5-9-7-0-3-2: 34,526; 4-0-5-7-9-3-2: 30,112; 0-4-9-5-3-7-2: 10,845) and 98.3 % of the
  bursts started at level 7 or deeper. Of the 120 permutations of the first five targets, 10 were ever played and 2 of them
  carry 97.9 % of that set's trajectories. Targets 1, 6, 7 and 8 were never broken first; 23 of the 90 ordered pairs were never
  played although both targets were live together, several with more than 100,000 such opportunities (section 2).
- **Four verified full orders, 180 distinct prefixes.** 312 verified clears fall into 4 full orders; their best verified clocks
  are 1,245, 1,352, 1,588 and 1,884 input ticks. A fifth full order exists only as 46 unverified claims (best claimed 1,280),
  never replayed because the lab replays a claim only when it is faster than the best verified clear (section 1.3).
- **Segment map.** 54 ordered pairs were observed in 9,358 instances; the class at the previous break is recorded for 97.3 % of
  them. For 13 pairs the fastest instance comes from a class that holds at most a quarter of that pair's instances and beats the
  most common class's fastest (section 3.3).
- **Moving geometry.** The records hold one moving collision group (line 19 of the recorded geometry; translation y between
  1,500 and 3,300, x constant). Its translation at a tick is the same in every record that holds that tick, and it turns every
  150 ticks. In the 186,652 unique per-tick states (0.42 % of the 44.1 M burst ticks), 5,336 ticks (2.9 %) have the fighter's
  floor on that line; they form 36 distinct landings, 27 of them while the line moves down. Landings used 12 of the 19 hundred-unit
  translation bins; the top bins (3,000 to 3,300) and three middle bins were never landed on, although contact ticks (riding the
  line after a landing) occur in every bin. Every one of the 321 clear traces touches the moving line at least once (section 4).
- **Timing robustness** is designed, not run (section 5): about 1,236 single-boundary variants for the 1,245 clear, about ten
  minutes of native time in standby mode, needs the owner's authorisation.
- **Replay-browser shortlist**: ten trajectories (section 6). **Open questions**: seven (section 7).

## 1. Target-order catalogue

### 1.1 Records and method

Every record that holds a sequence of breaks was used:

- **Live-target mask by level in cell keys** (`import/archive/cells.jsonl`, 49,928 cells; the smoke run's archive copy, 728 more).
  The key's fourth element is the live mask (1,023 at tick 0; bit i set = target i live). Along a ledger burst, the masks of the
  cells it reached, in reach-tick order, give the targets it broke; the tick of the first reach with the new mask is the
  break tick, marked "(reach)" below because the archive records airborne cells by design (746 grounded cells of 49,928), so a
  break while grounded can appear a few ticks late. No reach ever regained a bit and no history repeats a target (checked).
- **Break events in dispatch rows** (`breaks_after_start` [tick, target], exact): trail probe 404 events, frontier 6,727 (plus
  the seed replays), run 1 544, run 2 587.
- **Break tables of verified clears** (`verifications.jsonl` `breaks_r1` / `breaks_r2`, equal in all 303 rows; the splice
  probe's `results.jsonl` `breaks` for its 9 clears replayed twice with the same clock; the reference clear's trace).
- **End records and cells** of the lab runs supply the links only: the archive by (burst, offset) of the start representative,
  the trail probe by (pair, arm) with the lead arm starting from an import cell and the control arm from the reference route's
  prefix, the frontier by (round, sid, k) with seeds from trail-probe dispatches, runs 1 and 2 by the prefix digest in each
  cell's `origin.parent_digest` and each dispatch's `draw_id` (run 2 continues run 1's cell ids). This is the linkage the strategy
  review's working script `logs/frs_strategy/scripts/s2_lineage.py` established; this report re-implements it in
  `logs/frs_route/r1_catalogue.py`, adds the smoke run, and counts differently (below). The two agree on the 180 orders and 54 pairs.

Consistency checks, all zero: dispatch `prefix_breaks` against the rebuilt prefix length (111,162 lab dispatches), parent-digest
mismatches, seed histories beyond the seed's tick, duplicated targets in a history, archive reaches with a regained mask bit,
verification rows whose two replays disagree on breaks. The smoke archive copy differs from the import in 1,270 cells, all
replacements with the same key (a shorter arrival) and none with a different key, so the mask sequences are unaffected.

Counts per node of the order tree (a node = an order prefix):

- **through**: trajectories whose full history passes the node, counting the replayed prefix (a burst started at level 7 passes
  the seven nodes of its prefix) and the burst's own breaks. This is the budget view: how many bursts experienced that prefix.
- **own**: trajectories that performed the node's last break themselves. This is the discovery view.
- **started**, **burst ticks**: bursts whose start prefix is exactly the node, and the new words they played (one word per tick).
- **earliest**: the earliest own break tick observed, with the trajectory that did it; "(reach)" marks an archive reach tick.
- **clear below**: whether a verified clear's full order has this prefix ("verified"), or only an unverified clear claim ("claim only").

### 1.2 How much of the agent's experience the records cover

| source | record | trajectories | burst ticks (new words) | prefix ticks replayed |
|---|---|---|---|---|
| rd1 | `import/archive/bursts.idx.jsonl` (session rd1) | 2,175 | 237,209 | 2,198,454 |
| rd2 | same, rd2 | 4,037 | 466,895 | 4,525,745 |
| rd3 | same, rd3 | 4,194 | 483,852 | 4,687,034 |
| rd4 | same, rd4 | 3,480 | 358,840 | 5,231,544 |
| sd1 | same, sd1 | 3,668 | 373,985 | 5,624,991 |
| sd2 | same, sd2 | 3,769 | 399,969 | 5,474,960 |
| smk | `smoke_2026-10-14/run/archive/bursts.idx.jsonl` (ids >= 21,323) | 383 | 53,389 | 541,616 |
| trail | `trail_probe_2026-10-14/run/dispatches.jsonl` | 3,960 | 548,237 | 3,021,410 |
| fro | `frontier_2026-10-14/run/dispatches.jsonl` (kind burst) | 37,194 | 6,984,353 | 14,256,600 |
| fro-seed | same (kind seed) | 136 | 9,751 | 46,634 |
| run1 | `crossing_2026-10-15/run/dispatches.jsonl` | 30,699 | 2,830,407 | 44,557,614 |
| run2 | `crossing_2026-10-15_run2/run/dispatches.jsonl` | 39,309 | 3,568,728 | 46,603,859 |
| total | | 133,004 | 16,315,615 | 136,770,461 |

"Burst ticks" are the new words each burst played (`n` in the ledger, `words_played` in the dispatch rows); "prefix ticks" are
the ticks replayed to reach each burst's start. The anomaly inventory's 44,058,343 "burst ticks" counts the ledger's `ticks` field
(prefix plus burst) for the import, which is why its total is larger; the lab-run figures (trail 548,237; frontier 6,994,104;
run 1 2,830,407; run 2 3,568,728; smoke 53,389) agree exactly.

### 1.3 Distinct full orders of the verified clears

| full order (first to last break) | verified clears | best verified clock (input ticks) | where the best is | records |
|---|---|---|---|---|
| 4-0-5-7-9-3-2-6-8-1 | 2 | 1,245 | crossing_2026-10-15_run2 n36236_c8692_k0 | crossing_2026-10-15_run2 2 |
| 4-5-9-7-0-3-2-6-8-1 | 90 | 1,352 | crossing_2026-10-15_run2 n813_c9709_k1 | crossing_2026-10-15 89, crossing_2026-10-15_run2 1 |
| 4-5-9-7-0-3-2-6-1-8 | 209 | 1,588 | crossing_2026-10-15 n25467_c23988_k1 | crossing_2026-10-15 209 |
| 0-4-9-5-3-7-2-6-8-1 | 11 | 1,884 | splice_probe_2026-10-14 c073_cid2290 | import/reference 1, splice_probe_2026-10-14 9, trail_probe_2026-10-14 1 |

Verified means two exact fresh-process replays from tick 0 (the lab's verdict), the splice probe's r1 and r2 pairs with equal
clocks, or the registered reference. The 1,261 clear shares the 1,245's order; the 1,429 shares the 1,352's. Clear claims by
order, including the ones never replayed:

| full order | clear claims (dispatch outcome clear, archive end reason clear) | verified |
|---|---|---|
| 4-5-9-7-0-3-2-6-1-8 | 209 | yes |
| 4-5-9-7-0-3-2-6-8-1 | 157 | yes |
| 4-0-5-7-9-3-2-6-1-8 | 46 | no |
| 0-4-9-5-3-7-2-6-8-1 | 22 | yes |
| 4-0-5-7-9-3-2-6-8-1 | 22 | yes |

The fifth order (…-6-1-8 after the 4-0-5-7-9-3-2 prefix) has 46 claims and no verification: the lab replays a claim only when it
is faster than the best verified clear at the time of the decision, and its best claim (1,280, run 2 dispatch n 38159) was slower
than the 1,245.

First breaks: target 0: 106 trajectories, fastest 43, target 4: 56 trajectories, fastest 26, target 9: 39 trajectories, fastest 36, target 5: 29 trajectories, fastest 66, target 3: 9 trajectories, fastest 261, target 2: 2 trajectories, fastest 258. Targets 1, 6, 7 and 8 were never the first break.

### 1.4 The order tree (all 180 prefixes)

Sorted by level, then by through-count. "next targets broken" lists the children observed, with the number of targets still live.
Sources are abbreviated: rd1 to sd2 = the imported ledger by session, smk = smoke run, trail = trail probe, fro = frontier search
(fro-seed = its seed replays), run1 / run2 = crossing runs. Main sources show the three largest only.

| level | order prefix | through | own | started | burst ticks | earliest break | main sources | next targets broken | clear below |
|---|---|---|---|---|---|---|---|---|---|
| 0 | (root) | 133,004 | 0 | 935 | 111,526 |  | run2 39,309, fro 37,194, run1 30,699 | 0,2,3,4,5,9 (live 10) | verified |
| 1 | 4 | 105,372 | 56 | 590 | 77,580 | 26 (reach) (rd1 burst 19) | run2 39,309, fro 34,234, run1 30,699 | 0,2,3,5,9 (live 9) | verified |
| 1 | 0 | 26,045 | 106 | 340 | 42,868 | 43 (reach) (rd1 burst 8) | rd3 3,693, rd2 3,664, trail 3,526 | 4,5,9 (live 9) | verified |
| 1 | 9 | 636 | 39 | 102 | 13,440 | 36 (trail pair 0 control k9) | trail 164, rd3 96, sd2 94 | 0,3,4,5 (live 9) | no |
| 1 | 5 | 203 | 29 | 89 | 10,680 | 66 (trail pair 1 lead k8) | rd3 50, sd2 47, rd4 44 | 0,4,9 (live 9) | no |
| 1 | 3 | 51 | 9 | 40 | 4,859 | 261 (reach) (rd3 burst 9395) | sd2 22, sd1 16, rd4 9 | 9 (live 9) | no |
| 1 | 2 | 3 | 2 | 1 | 120 | 258 (reach) (rd4 burst 12783) | rd4 1, sd1 1, sd2 1 | none (live 9) | no |
| 2 | 4-5 | 57,527 | 19 | 1,116 | 217,143 | 78 (frontier round 76 sid 4 k17) | run1 26,087, fro 22,938, run2 8,370 | 0,7,9 (live 8) | verified |
| 2 | 4-0 | 45,873 | 96 | 1,085 | 172,998 | 78 (frontier round 197 sid 2 k33) | run2 30,939, fro 9,913, run1 4,612 | 3,5,9 (live 8) | verified |
| 2 | 0-4 | 24,045 | 61 | 1,045 | 133,433 | 93 (trail pair 4 lead k2) | rd3 3,384, rd2 3,337, sd2 3,128 | 3,5,7,9 (live 8) | verified |
| 2 | 4-9 | 1,463 | 35 | 233 | 39,572 | 93 (frontier round 13 sid 2 k3) | fro 1,320, sd2 30, rd3 29 | 0,5 (live 8) | no |
| 2 | 0-9 | 1,353 | 25 | 198 | 24,178 | 124 (trail pair 4 lead k6) | trail 386, rd3 197, rd2 160 | 3,4,5,7 (live 8) | no |
| 2 | 9-4 | 496 | 22 | 40 | 4,800 | 122 (frontier round 13 sid 3 k0) | trail 150, sd2 74, rd3 71 | 0,5 (live 8) | no |
| 2 | 0-5 | 301 | 14 | 141 | 16,700 | 155 (reach) (rd4 burst 13089) | rd2 72, rd4 60, rd3 57 | 3,4,9 (live 8) | no |
| 2 | 5-4 | 75 | 25 | 49 | 6,120 | 101 (reach) (rd2 burst 5140) | rd3 21, sd2 19, rd4 18 | 0,9 (live 8) | no |
| 2 | 5-0 | 33 | 17 | 11 | 1,320 | 223 (reach) (rd3 burst 8367) | rd3 12, rd4 9, sd1 5 | 4 (live 8) | no |
| 2 | 9-0 | 31 | 10 | 10 | 1,200 | 219 (reach) (rd3 burst 9154) | trail 10, rd3 8, sd1 5 | 4 (live 8) | no |
| 2 | 5-9 | 23 | 4 | 13 | 1,560 | 164 (trail pair 1 lead k8) | sd2 12, sd1 7, rd2 1 | 3 (live 8) | no |
| 2 | 4-2 | 13 | 4 | 9 | 1,418 | 246 (reach) (rd3 burst 9973) | rd4 5, sd2 3, sd1 2 | none (live 8) | no |
| 2 | 4-3 | 12 | 8 | 4 | 427 | 318 (reach) (sd2 burst 20273) | sd2 4, rd4 3, rd3 2 | none (live 8) | no |
| 2 | 3-9 | 4 | 2 | 2 | 240 | 474 (reach) (sd2 burst 20519) | sd2 4 | none (live 8) | no |
| 2 | 9-3 | 1 | 1 | 0 | 0 | 237 (frontier round 196 sid 3 k6) | fro 1 | none (live 8) | no |
| 2 | 9-5 | 1 | 1 | 0 | 0 | 250 (reach) (sd1 burst 13977) | sd1 1 | none (live 8) | no |
| 3 | 4-5-9 | 49,725 | 53 | 5,563 | 844,873 | 217 (frontier round 175 sid 183 k250) | run1 26,087, fro 15,255, run2 8,370 | 0,3,7 (live 7) | verified |
| 3 | 4-0-5 | 42,281 | 26 | 2,056 | 378,020 | 153 (frontier round 136 sid 593 k15) | run2 30,939, fro 6,720, run1 4,612 | 3,7,9 (live 7) | verified |
| 3 | 0-4-9 | 19,549 | 111 | 1,262 | 152,143 | 252 (reach) (rd2 burst 3187) | rd2 3,127, rd3 3,024, sd1 2,796 | 3,5,7 (live 7) | verified |
| 3 | 4-5-0 | 6,963 | 244 | 3,959 | 709,119 | 170 (frontier round 183 sid 592 k259) | fro 6,898, rd3 17, rd2 15 | 3,7,9 (live 7) | no |
| 3 | 0-4-5 | 3,446 | 37 | 641 | 119,787 | 152 (reach) (rd4 burst 12664) | fro 1,921, trail 452, sd2 285 | 3,7,9 (live 7) | no |
| 3 | 4-0-9 | 2,525 | 90 | 2,083 | 320,157 | 120 (frontier round 207 sid 1243 k0) | fro 2,404, trail 75, fro-seed 18 | 3,5 (live 7) | no |
| 3 | 4-9-0 | 1,123 | 36 | 311 | 45,767 | 174 (frontier round 188 sid 590 k42) | fro 1,079, trail 10, rd2 8 | 3,5,7 (live 7) | no |
| 3 | 0-9-4 | 857 | 44 | 304 | 36,357 | 204 (reach) (sd1 burst 14613) | trail 380, fro 148, rd3 76 | 3,5,7 (live 7) | no |
| 3 | 9-4-5 | 441 | 8 | 164 | 19,537 | 193 (reach) (rd2 burst 3664) | trail 150, sd2 62, sd1 57 | 0,2,3 (live 7) | no |
| 3 | 0-9-5 | 239 | 4 | 216 | 25,523 | 400 (reach) (rd1 burst 236) | rd3 74, rd2 64, rd4 44 | 3,4 (live 7) | no |
| 3 | 0-5-4 | 139 | 23 | 110 | 12,929 | 202 (reach) (rd4 burst 13089) | rd2 35, rd3 34, rd4 32 | 9 (live 7) | no |
| 3 | 4-9-5 | 112 | 4 | 76 | 9,960 | 175 (frontier round 169 sid 590 k28) | fro 111, sd1 1 | 0 (live 7) | no |
| 3 | 0-4-3 | 85 | 4 | 67 | 7,971 | 437 (reach) (rd2 burst 2204) | rd3 24, sd1 20, sd2 18 | 5,9 (live 7) | no |
| 3 | 0-9-7 | 84 | 2 | 30 | 3,840 | 445 (reach) (rd3 burst 6496) | sd2 25, rd4 24, sd1 19 | 4 (live 7) | no |
| 3 | 0-5-9 | 43 | 13 | 25 | 3,000 | 309 (reach) (rd3 burst 7763) | rd4 11, rd3 9, sd1 9 | 4 (live 7) | no |
| 3 | 0-4-7 | 17 | 6 | 11 | 1,320 | 442 (reach) (rd1 burst 317) | rd3 4, sd1 4, rd4 3 | none (live 7) | no |
| 3 | 9-0-4 | 12 | 1 | 11 | 1,440 | 271 (reach) (rd4 burst 12354) | trail 10, rd4 1, sd1 1 | none (live 7) | no |
| 3 | 5-0-4 | 11 | 6 | 5 | 600 | 330 (reach) (rd3 burst 7835) | rd4 5, rd3 4, sd1 2 | 9 (live 7) | no |
| 3 | 5-4-0 | 10 | 9 | 1 | 120 | 214 (reach) (rd4 burst 13848) | rd4 5, rd3 3, sd2 2 | 9 (live 7) | no |
| 3 | 5-9-3 | 8 | 2 | 6 | 720 | 460 (reach) (sd1 burst 15810) | sd2 6, sd1 2 | 2 (live 7) | no |
| 3 | 9-4-0 | 8 | 7 | 1 | 120 | 270 (reach) (rd2 burst 4381) | rd2 2, rd3 2, sd1 2 | none (live 7) | no |
| 3 | 4-0-3 | 4 | 2 | 2 | 158 | 399 (frontier round 127 sid 594 k24) | rd3 3, fro 1 | none (live 7) | no |
| 3 | 5-4-9 | 4 | 4 | 0 | 0 | 310 (reach) (rd4 burst 11656) | rd4 3, sd1 1 | none (live 7) | no |
| 3 | 0-9-3 | 2 | 2 | 0 | 0 | 524 (reach) (sd2 burst 19856) | sd1 1, sd2 1 | none (live 7) | no |
| 3 | 4-5-7 | 2 | 1 | 0 | 0 | 504 (reach) (sd2 burst 20862) | sd2 2 | 0 (live 7) | no |
| 3 | 0-5-3 | 1 | 1 | 0 | 0 | 813 (reach) (sd2 burst 18401) | sd2 1 | none (live 7) | no |
| 4 | 4-0-5-7 | 41,188 | 1,413 | 976 | 244,776 | 184 (frontier round 21 sid 212 k13) | run2 30,939, fro 5,637, run1 4,612 | 3,9 (live 6) | verified |
| 4 | 4-5-9-7 | 40,577 | 4 | 972 | 251,650 | 303 (frontier round 26 sid 227 k48) | run1 26,072, run2 8,369, fro 6,136 | 0,2,3 (live 6) | verified |
| 4 | 0-4-9-5 | 17,766 | 70 | 1,251 | 151,354 | 350 (frontier round 5 sid 72 k1) | rd2 2,928, rd3 2,832, sd1 2,718 | 2,3,7 (live 6) | verified |
| 4 | 4-5-0-9 | 3,522 | 1,010 | 2,400 | 397,087 | 253 (frontier round 185 sid 1144 k21) | fro 3,517, rd2 2, rd3 2 | 3,7 (live 6) | no |
| 4 | 4-5-9-0 | 3,440 | 1,728 | 1,712 | 295,993 | 267 (frontier round 162 sid 929 k185) | fro 3,439, rd3 1 | none (live 6) | no |
| 4 | 4-5-9-3 | 1,828 | 4 | 360 | 90,913 | 396 (frontier round 106 sid 712 k60) | fro 1,812, run1 15, run2 1 | 0,7 (live 6) | no |
| 4 | 0-4-5-7 | 1,817 | 9 | 431 | 65,887 | 223 (frontier round 23 sid 172 k69) | trail 440, fro 348, sd2 278 | 3,9 (live 6) | no |
| 4 | 0-4-5-9 | 828 | 76 | 712 | 112,600 | 232 (frontier round 63 sid 172 k341) | fro 822, rd2 1, rd3 1 | 2 (live 6) | no |
| 4 | 4-0-9-5 | 638 | 374 | 264 | 46,320 | 232 (frontier round 65 sid 500 k5) | fro 632, trail 3, fro-seed 3 | none (live 6) | no |
| 4 | 4-9-0-7 | 577 | 1 | 240 | 43,920 | 553 (frontier round 17 sid 195 k4) | fro 577 | 5 (live 6) | no |
| 4 | 0-9-4-5 | 504 | 49 | 371 | 55,657 | 254 (reach) (rd2 burst 2384) | trail 262, fro 132, rd3 26 | 3,7 (live 6) | no |
| 4 | 4-0-5-9 | 486 | 62 | 408 | 58,579 | 284 (frontier round 177 sid 1103 k37) | fro 484, trail 1, fro-seed 1 | 3 (live 6) | no |
| 4 | 0-4-9-3 | 469 | 13 | 449 | 50,922 | 539 (reach) (rd4 burst 11192) | rd3 134, rd2 96, rd4 95 | 2,5 (live 6) | no |
| 4 | 9-4-5-0 | 276 | 19 | 204 | 28,986 | 331 (reach) (sd2 burst 18147) | trail 150, fro 48, sd1 24 | 3,7 (live 6) | no |
| 4 | 4-5-0-3 | 235 | 3 | 100 | 25,053 | 535 (reach) (sd2 burst 19957) | fro 233, sd2 1, smk 1 | 2,9 (live 6) | no |
| 4 | 0-4-5-3 | 209 | 1 | 80 | 21,137 | 475 (frontier round 32 sid 172 k135) | fro 209 | 9 (live 6) | no |
| 4 | 4-9-0-3 | 170 | 2 | 88 | 18,933 | 339 (frontier round 193 sid 1190 k6) | fro 170 | 2,5 (live 6) | no |
| 4 | 4-0-9-3 | 96 | 8 | 67 | 15,075 | 282 (frontier round 3 sid 82 k8) | fro 79, sd2 13, sd1 3 | 5,7 (live 6) | no |
| 4 | 0-9-7-4 | 62 | 10 | 52 | 6,240 | 560 (reach) (rd3 burst 7686) | sd2 19, rd4 17, sd1 16 | none (live 6) | no |
| 4 | 0-9-5-4 | 41 | 25 | 16 | 1,920 | 514 (reach) (rd3 burst 8927) | rd2 17, rd3 11, sd1 5 | none (live 6) | no |
| 4 | 4-9-5-0 | 38 | 6 | 32 | 4,320 | 395 (frontier round 210 sid 1239 k19) | fro 38 | 7 (live 6) | no |
| 4 | 4-9-0-5 | 36 | 4 | 32 | 6,000 | 301 (frontier round 193 sid 1179 k13) | fro 36 | none (live 6) | no |
| 4 | 0-9-4-7 | 33 | 3 | 30 | 3,600 | 518 (reach) (rd3 burst 10366) | sd1 13, rd4 7, rd3 6 | none (live 6) | no |
| 4 | 0-9-4-3 | 31 | 7 | 24 | 3,260 | 500 (reach) (sd1 burst 16991) | fro 16, rd3 8, sd1 2 | none (live 6) | no |
| 4 | 0-4-9-7 | 25 | 1 | 24 | 5,640 | 443 (frontier round 14 sid 179 k3) | fro 25 | 5 (live 6) | no |
| 4 | 4-5-0-7 | 17 | 1 | 16 | 3,120 | 423 (frontier round 121 sid 830 k24) | fro 17 | none (live 6) | no |
| 4 | 0-4-3-5 | 13 | 3 | 10 | 1,200 | 719 (reach) (rd4 burst 13333) | sd2 9, sd1 3, rd4 1 | 9 (live 6) | no |
| 4 | 9-4-5-2 | 13 | 1 | 12 | 1,424 | 568 (reach) (rd4 burst 13094) | sd2 10, rd4 1, sd1 1 | none (live 6) | no |
| 4 | 0-4-3-9 | 9 | 5 | 4 | 480 | 733 (reach) (rd3 burst 7145) | rd3 3, sd1 3, sd2 2 | none (live 6) | no |
| 4 | 0-5-4-9 | 9 | 3 | 6 | 720 | 503 (reach) (rd2 burst 2517) | rd2 4, rd3 3, sd1 1 | none (live 6) | no |
| 4 | 0-5-9-4 | 9 | 4 | 5 | 600 | 401 (reach) (sd1 burst 14654) | sd1 4, rd4 2, sd2 2 | none (live 6) | no |
| 4 | 0-9-5-3 | 4 | 1 | 3 | 349 | 880 (reach) (rd3 burst 8499) | rd3 1, rd4 1, sd1 1 | none (live 6) | no |
| 4 | 4-0-5-3 | 2 | 2 | 0 | 0 | 642 (frontier round 3 sid 79 k13) | fro 2 | none (live 6) | no |
| 4 | 4-5-7-0 | 2 | 1 | 1 | 120 | 524 (reach) (sd2 burst 20862) | sd2 2 | none (live 6) | no |
| 4 | 5-0-4-9 | 2 | 2 | 0 | 0 | 460 (reach) (sd1 burst 17091) | rd4 1, sd1 1 | none (live 6) | no |
| 4 | 9-4-5-3 | 2 | 2 | 0 | 0 | 671 (reach) (sd1 burst 14249) | sd1 2 | none (live 6) | no |
| 4 | 5-4-0-9 | 1 | 1 | 0 | 0 | 399 (reach) (rd4 burst 11880) | rd4 1 | none (live 6) | no |
| 4 | 5-9-3-2 | 1 | 1 | 0 | 0 | 484 (reach) (sd2 burst 19319) | sd2 1 | none (live 6) | no |
| 5 | 4-0-5-7-9 | 37,920 | 283 | 1,764 | 395,722 | 280 (frontier round 114 sid 241 k718) | run2 30,906, run1 4,543, fro 2,471 | 2,3 (live 5) | verified |
| 5 | 4-5-9-7-0 | 37,374 | 191 | 1,780 | 314,110 | 491 (frontier round 28 sid 275 k7) | run1 26,070, run2 8,369, fro 2,935 | 2,3 (live 5) | verified |
| 5 | 0-4-9-5-3 | 16,122 | 91 | 1,333 | 153,533 | 880 (reach) (rd1 burst 438) | rd2 2,681, sd1 2,616, sd2 2,598 | 2,7 (live 5) | verified |
| 5 | 4-5-9-7-3 | 1,598 | 21 | 800 | 190,081 | 550 (frontier round 35 sid 275 k61) | fro 1,597, run1 1 | 0,2 (live 5) | no |
| 5 | 4-0-5-7-3 | 1,170 | 8 | 480 | 114,112 | 392 (frontier round 30 sid 240 k62) | fro 1,068, run1 69, run2 33 | 9 (live 5) | no |
| 5 | 0-4-5-7-9 | 1,079 | 24 | 488 | 66,139 | 498 (frontier round 15 sid 151 k46) | trail 330, fro 220, sd2 181 | 3 (live 5) | no |
| 5 | 4-5-9-7-2 | 855 | 14 | 372 | 122,471 | 506 (frontier round 35 sid 216 k121) | fro 854, run1 1 | 0,3 (live 5) | no |
| 5 | 4-5-9-3-7 | 790 | 2 | 724 | 171,480 | 667 (frontier round 157 sid 940 k146) | fro 790 | 0 (live 5) | no |
| 5 | 4-5-9-3-0 | 715 | 39 | 556 | 113,335 | 535 (frontier round 145 sid 951 k29) | fro 699, run1 15, run2 1 | 2,7 (live 5) | no |
| 5 | 0-4-9-5-2 | 419 | 5 | 395 | 46,511 | 834 (reach) (rd2 burst 6042) | rd3 132, rd4 82, sd2 77 | 3 (live 5) | no |
| 5 | 4-9-0-7-5 | 385 | 49 | 336 | 57,600 | 583 (frontier round 17 sid 195 k4) | fro 385 | none (live 5) | no |
| 5 | 0-4-5-7-3 | 328 | 6 | 164 | 19,537 | 787 (reach) (rd2 burst 5098) | trail 110, sd2 61, sd1 51 | 9 (live 5) | no |
| 5 | 0-4-5-3-9 | 137 | 9 | 128 | 27,154 | 505 (frontier round 43 sid 313 k61) | fro 137 | none (live 5) | no |
| 5 | 4-5-0-3-9 | 133 | 17 | 116 | 25,680 | 647 (frontier round 176 sid 1116 k2) | fro 133 | none (live 5) | no |
| 5 | 4-5-0-9-3 | 85 | 5 | 80 | 15,238 | 532 (frontier round 134 sid 917 k8) | fro 85 | none (live 5) | no |
| 5 | 4-9-0-3-5 | 68 | 4 | 64 | 14,040 | 434 (frontier round 202 sid 1192 k48) | fro 68 | none (live 5) | no |
| 5 | 0-9-4-5-7 | 56 | 4 | 36 | 6,240 | 491 (trail pair 87 lead k4) | fro 52, trail 2, fro-seed 2 | 3 (live 5) | no |
| 5 | 9-4-5-0-7 | 43 | 6 | 37 | 6,960 | 413 (trail pair 105 lead k0) | fro 32, sd2 5, sd1 2 | none (live 5) | no |
| 5 | 0-4-5-9-2 | 41 | 1 | 24 | 7,869 | 546 (frontier round 38 sid 341 k11) | fro 41 | 7 (live 5) | no |
| 5 | 0-9-4-5-3 | 38 | 6 | 32 | 8,341 | 545 (trail pair 106 lead k6) | fro 32, trail 3, fro-seed 3 | none (live 5) | no |
| 5 | 4-5-0-9-7 | 36 | 4 | 32 | 8,160 | 367 (frontier round 133 sid 898 k14) | fro 36 | none (live 5) | no |
| 5 | 4-0-9-3-5 | 23 | 3 | 20 | 5,280 | 487 (frontier round 211 sid 1250 k16) | fro 23 | none (live 5) | no |
| 5 | 9-4-5-0-3 | 18 | 2 | 16 | 4,264 | 665 (trail pair 104 lead k4) | fro 16, trail 1, fro-seed 1 | none (live 5) | no |
| 5 | 4-0-5-9-3 | 17 | 1 | 16 | 2,183 | 718 (frontier round 14 sid 162 k10) | fro 17 | none (live 5) | no |
| 5 | 4-5-0-3-2 | 17 | 1 | 16 | 4,214 | 831 (frontier round 183 sid 1116 k52) | fro 17 | none (live 5) | no |
| 5 | 4-9-0-3-2 | 17 | 1 | 16 | 5,861 | 510 (frontier round 202 sid 1192 k53) | fro 17 | none (live 5) | no |
| 5 | 0-4-9-3-2 | 9 | 2 | 7 | 805 | 629 (reach) (sd1 burst 15442) | sd2 6, sd1 3 | none (live 5) | no |
| 5 | 0-4-9-5-7 | 4 | 4 | 0 | 0 | 584 (trail pair 59 control k4) | trail 2, fro-seed 2 | none (live 5) | no |
| 5 | 0-4-3-5-9 | 2 | 2 | 0 | 0 | 1,016 (reach) (sd2 burst 19062) | sd2 2 | none (live 5) | no |
| 5 | 4-0-9-3-7 | 2 | 1 | 1 | 120 | 494 (reach) (sd2 burst 20738) | sd2 1, smk 1 | none (live 5) | no |
| 5 | 4-9-5-0-7 | 2 | 2 | 0 | 0 | 630 (frontier round 200 sid 1207 k12) | fro 2 | none (live 5) | no |
| 5 | 0-4-9-3-5 | 1 | 1 | 0 | 0 | 799 (reach) (rd4 burst 13130) | rd4 1 | none (live 5) | no |
| 5 | 0-4-9-7-5 | 1 | 1 | 0 | 0 | 919 (frontier round 16 sid 186 k5) | fro 1 | none (live 5) | no |
| 6 | 4-5-9-7-0-3 | 35,432 | 77 | 836 | 145,671 | 647 (frontier round 39 sid 335 k13) | run1 26,070, run2 8,369, fro 993 | 2 (live 4) | verified |
| 6 | 4-0-5-7-9-3 | 32,698 | 13 | 2,463 | 282,514 | 461 (frontier round 75 sid 574 k7) | run2 29,164, run1 3,229, fro 305 | 2,8 (live 4) | verified |
| 6 | 0-4-9-5-3-7 | 14,096 | 24 | 3,265 | 372,615 | 948 (trail pair 113 lead k2) | sd1 2,368, rd2 2,300, rd3 2,284 | 2 (live 4) | verified |
| 6 | 4-0-5-7-9-2 | 3,192 | 4 | 2,558 | 304,283 | 486 (frontier round 106 sid 240 k565) | run2 1,742, run1 1,314, fro 136 | 3,6 (live 4) | no |
| 6 | 4-5-9-7-3-0 | 839 | 94 | 728 | 149,045 | 678 (frontier round 75 sid 534 k45) | fro 838, run1 1 | 2 (live 4) | no |
| 6 | 4-0-5-7-3-9 | 740 | 58 | 666 | 141,130 | 467 (frontier round 61 sid 437 k53) | fro 638, run1 69, run2 33 | 2 (live 4) | no |
| 6 | 0-4-9-5-3-2 | 628 | 2 | 444 | 52,763 | 1,105 (reach) (sd1 burst 16591) | sd2 269, sd1 179, rd4 95 | 7 (live 4) | no |
| 6 | 0-4-5-7-9-3 | 573 | 6 | 434 | 61,465 | 874 (reach) (sd2 burst 19108) | trail 330, sd2 98, sd1 61 | 2 (live 4) | no |
| 6 | 4-5-9-3-7-0 | 536 | 472 | 64 | 11,400 | 696 (frontier round 157 sid 940 k146) | fro 536 | none (live 4) | no |
| 6 | 4-5-9-7-2-3 | 272 | 16 | 224 | 40,045 | 716 (frontier round 70 sid 536 k6) | fro 272 | 0 (live 4) | no |
| 6 | 4-5-9-7-2-0 | 229 | 16 | 196 | 46,019 | 732 (frontier round 82 sid 582 k32) | fro 228, run1 1 | 3 (live 4) | no |
| 6 | 0-4-5-7-3-9 | 168 | 10 | 142 | 19,472 | 871 (reach) (sd2 burst 19832) | trail 110, fro 16, sd2 14 | 2 (live 4) | no |
| 6 | 4-5-9-3-0-2 | 124 | 4 | 72 | 18,994 | 805 (frontier round 159 sid 1037 k12) | fro 108, run1 15, run2 1 | 7 (live 4) | no |
| 6 | 4-5-9-7-0-2 | 52 | 4 | 32 | 8,691 | 770 (frontier round 48 sid 395 k13) | fro 52 | 3 (live 4) | no |
| 6 | 4-5-9-7-3-2 | 34 | 2 | 32 | 7,179 | 745 (frontier round 43 sid 347 k43) | fro 34 | none (live 4) | no |
| 6 | 0-4-9-5-2-3 | 23 | 4 | 19 | 1,902 | 962 (reach) (rd4 burst 10550) | rd4 9, sd1 8, sd2 6 | none (live 4) | no |
| 6 | 0-4-5-9-2-7 | 17 | 1 | 16 | 2,992 | 751 (frontier round 40 sid 351 k4) | fro 17 | none (live 4) | no |
| 6 | 0-9-4-5-7-3 | 17 | 1 | 16 | 3,240 | 782 (frontier round 1 sid 118 k3) | fro 17 | none (live 4) | no |
| 6 | 4-5-9-3-0-7 | 1 | 1 | 0 | 0 | 1,011 (frontier round 158 sid 1037 k7) | fro 1 | none (live 4) | no |
| 7 | 4-5-9-7-0-3-2 | 34,526 | 7 | 2,811 | 337,449 | 798 (frontier round 48 sid 397 k9) | run1 26,070, run2 8,369, fro 87 | 1,6,8 (live 3) | verified |
| 7 | 4-0-5-7-9-3-2 | 30,112 | 47 | 6,341 | 681,455 | 493 (frontier round 77 sid 579 k5) | run2 27,751, run1 2,274, fro 87 | 1,6,8 (live 3) | verified |
| 7 | 0-4-9-5-3-7-2 | 10,845 | 38 | 5,037 | 583,591 | 1,339 (reach) (rd2 burst 2366) | sd1 2,258, sd2 2,217, rd4 2,053 | 1,6,8 (live 3) | verified |
| 7 | 4-0-5-7-9-2-3 | 460 | 56 | 404 | 29,639 | 638 (frontier round 31 sid 299 k1) | run2 260, run1 149, fro 51 | none (live 3) | no |
| 7 | 4-0-5-7-9-2-6 | 235 | 9 | 226 | 36,631 | 879 (run2 n 27762 cid 27496 k0) | run2 235 | 3 (live 3) | no |
| 7 | 0-4-9-5-3-2-7 | 219 | 37 | 166 | 22,337 | 1,372 (reach) (sd1 burst 14170) | sd2 96, sd1 53, trail 40 | 6 (live 3) | no |
| 7 | 4-0-5-7-9-3-8 | 164 | 7 | 157 | 25,556 | 894 (run2 n 36065 cid 36207 k0) | run2 164 | none (live 3) | no |
| 7 | 0-4-5-7-9-3-2 | 142 | 9 | 117 | 21,950 | 1,097 (trail pair 155 lead k1) | trail 81, fro 32, sd2 22 | 6 (live 3) | no |
| 7 | 4-5-9-3-0-2-7 | 50 | 2 | 48 | 13,320 | 979 (frontier round 155 sid 1019 k7) | fro 34, run1 15, run2 1 | none (live 3) | no |
| 7 | 4-5-9-7-2-3-0 | 34 | 2 | 32 | 6,240 | 1,234 (frontier round 63 sid 495 k1) | fro 34 | none (live 3) | no |
| 7 | 0-4-5-7-3-9-2 | 18 | 2 | 16 | 3,600 | 1,154 (trail pair 147 lead k4) | fro 16, trail 1, fro-seed 1 | none (live 3) | no |
| 7 | 4-5-9-7-2-0-3 | 18 | 1 | 17 | 3,513 | 1,089 (frontier round 85 sid 645 k1) | fro 17, run1 1 | none (live 3) | no |
| 7 | 4-5-9-7-3-0-2 | 18 | 1 | 17 | 3,373 | 1,079 (frontier round 69 sid 534 k0) | fro 17, run1 1 | none (live 3) | no |
| 7 | 4-0-5-7-3-9-2 | 17 | 1 | 16 | 4,069 | 874 (frontier round 69 sid 515 k12) | fro 17 | none (live 3) | no |
| 7 | 4-5-9-7-0-2-3 | 17 | 1 | 16 | 3,128 | 1,101 (frontier round 51 sid 378 k53) | fro 17 | none (live 3) | no |
| 8 | 4-5-9-7-0-3-2-6 | 28,069 | 68 | 8,518 | 950,975 | 1,127 (run1 n 23189 cid 17445 k1) | run1 20,806, run2 7,263 | 1,8 (live 2) | verified |
| 8 | 4-0-5-7-9-3-2-8 | 12,907 | 45 | 4,866 | 406,128 | 974 (run2 n 1185 cid 22220 k0) | run2 12,873, run1 34 | 1 (live 2) | no |
| 8 | 4-0-5-7-9-3-2-6 | 10,181 | 14 | 1,859 | 180,229 | 991 (run2 n 20810 cid 29218 k0) | run2 10,181 | 1,8 (live 2) | verified |
| 8 | 0-4-9-5-3-7-2-6 | 5,516 | 29 | 1,815 | 222,247 | 1,701 (trail pair 184 control k1) | sd2 1,776, sd1 1,712, rd4 1,550 | 1,8 (live 2) | verified |
| 8 | 4-5-9-7-0-3-2-8 | 2,355 | 22 | 1,548 | 145,737 | 1,251 (run1 n 15114 cid 8360 k0) | run1 2,086, run2 269 | 1 (live 2) | no |
| 8 | 4-5-9-7-0-3-2-1 | 1,394 | 20 | 1,374 | 103,246 | 1,341 (run1 n 19850 cid 17187 k0) | run1 1,076, run2 318 | none (live 2) | no |
| 8 | 4-0-5-7-9-3-2-1 | 700 | 5 | 695 | 45,458 | 1,150 (run2 n 27307 cid 18581 k0) | run2 700 | none (live 2) | no |
| 8 | 0-4-9-5-3-7-2-8 | 280 | 10 | 270 | 31,158 | 1,805 (trail pair 191 lead k4) | sd1 150, sd2 122, trail 6 | 1 (live 2) | no |
| 8 | 0-4-5-7-9-3-2-6 | 18 | 2 | 16 | 3,120 | 1,482 (trail pair 170 lead k0) | fro 16, trail 1, fro-seed 1 | none (live 2) | no |
| 8 | 0-4-9-5-3-2-7-6 | 18 | 2 | 16 | 3,720 | 1,489 (trail pair 183 lead k3) | fro 16, trail 1, fro-seed 1 | none (live 2) | no |
| 8 | 0-4-9-5-3-7-2-1 | 16 | 3 | 13 | 1,289 | 1,929 (reach) (sd2 burst 19715) | sd2 11, rd4 4, sd1 1 | none (live 2) | no |
| 8 | 4-0-5-7-9-2-6-3 | 2 | 2 | 0 | 0 | 1,527 (run2 n 32468 cid 34782 k1) | run2 2 | none (live 2) | no |
| 9 | 4-5-9-7-0-3-2-6-8 | 12,205 | 186 | 12,019 | 1,150,413 | 1,276 (run2 n 36595 cid 18823 k0) | run1 8,225, run2 3,980 | 1 (live 1) | verified |
| 9 | 4-0-5-7-9-3-2-8-1 | 8,089 | 93 | 7,996 | 488,172 | 1,051 (run2 n 28549 cid 23635 k0) | run2 8,089 | none (live 1) | no |
| 9 | 4-5-9-7-0-3-2-6-1 | 7,495 | 31 | 7,464 | 612,095 | 1,353 (run1 n 17963 cid 27566 k0) | run1 6,758, run2 737 | 8 (live 1) | verified |
| 9 | 4-0-5-7-9-3-2-6-8 | 4,197 | 42 | 4,155 | 328,026 | 1,078 (run2 n 32684 cid 17718 k0) | run2 4,197 | 1 (live 1) | verified |
| 9 | 4-0-5-7-9-3-2-6-1 | 4,180 | 27 | 4,153 | 340,573 | 1,178 (run2 n 38198 cid 20797 k0) | run2 4,180 | 8 (live 1) | claim only |
| 9 | 0-4-9-5-3-7-2-6-8 | 3,251 | 154 | 3,097 | 265,417 | 1,816 (trail pair 192 lead k5) | sd2 1,226, sd1 892, rd4 869 | 1 (live 1) | verified |
| 9 | 4-5-9-7-0-3-2-8-1 | 818 | 33 | 785 | 59,295 | 1,371 (run2 n 938 cid 12417 k0) | run1 720, run2 98 | none (live 1) | no |
| 9 | 0-4-9-5-3-7-2-6-1 | 594 | 19 | 575 | 36,528 | 1,946 (reach) (sd2 burst 19786) | sd1 364, rd4 143, sd2 87 | none (live 1) | no |
| 9 | 0-4-9-5-3-7-2-8-1 | 2 | 2 | 0 | 0 | 2,003 (reach) (sd2 burst 21111) | sd1 1, sd2 1 | none (live 1) | no |
| 10 | 4-5-9-7-0-3-2-6-1-8 | 209 | 209 | 0 | 0 | 1,588 (run1 n 25467 cid 23988 k1) | run1 209 | none (live 0) | verified |
| 10 | 4-5-9-7-0-3-2-6-8-1 | 157 | 157 | 0 | 0 | 1,352 (run2 n 813 cid 9709 k1) | run1 89, run2 68 | none (live 0) | verified |
| 10 | 4-0-5-7-9-3-2-6-1-8 | 46 | 46 | 0 | 0 | 1,280 (run2 n 38159 cid 23931 k2) | run2 46 | none (live 0) | claim only |
| 10 | 0-4-9-5-3-7-2-6-8-1 | 22 | 22 | 0 | 0 | 1,885 (reach) (sd2 burst 20487) | sd2 14, rd4 5, sd1 1 | none (live 0) | verified |
| 10 | 4-0-5-7-9-3-2-6-8-1 | 22 | 22 | 0 | 0 | 1,245 (run2 n 36236 cid 8692 k0) | run2 22 | none (live 0) | verified |

## 2. Order coverage and concentration

### 2.1 Per level

| level | distinct orders | trajectories at level | top order | top order share | distinct sets | top set | top set share | orders in top set | bursts started at or below | share in top-order family | share of burst ticks in it | orders with one next target | mean next/live |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 1 | 133,004 | (root) | 100.0 % | 1 | {} | 100.0 % | 1 | 133,004 | 100.0 % | 100.0 % | 0 | 0.60 |
| 1 | 6 | 132,310 | 4 | 79.6 % | 6 | {4} | 79.6 % | 1 | 132,069 | 79.7 % | 80.2 % | 1 | 0.30 |
| 2 | 16 | 131,251 | 4-5 | 43.8 % | 9 | {0,4} | 53.3 % | 2 | 130,907 | 43.9 % | 47.4 % | 3 | 0.20 |
| 3 | 26 | 127,691 | 4-5-9 | 38.9 % | 11 | {0,4,5} | 41.4 % | 6 | 126,951 | 39.1 % | 40.2 % | 8 | 0.21 |
| 4 | 38 | 114,976 | 4-0-5-7 | 35.8 % | 10 | {0,4,5,7} | 37.4 % | 4 | 110,047 | 36.1 % | 31.8 % | 7 | 0.14 |
| 5 | 33 | 99,505 | 4-0-5-7-9 | 38.1 % | 9 | {0,4,5,7,9} | 77.3 % | 10 | 98,695 | 38.1 % | 33.0 % | 7 | 0.12 |
| 6 | 19 | 89,671 | 4-5-9-7-0-3 | 39.5 % | 4 | {0,3,4,5,7,9} | 94.9 % | 10 | 88,862 | 39.8 % | 39.7 % | 11 | 0.20 |
| 7 | 15 | 76,875 | 4-5-9-7-0-3-2 | 44.9 % | 3 | {0,2,3,4,5,7,9} | 99.5 % | 13 | 76,655 | 45.0 % | 47.0 % | 3 | 0.27 |
| 8 | 12 | 61,456 | 4-5-9-7-0-3-2-6 | 45.7 % | 3 | {0,2,3,4,5,6,7,9} | 71.3 % | 6 | 61,234 | 45.7 % | 50.5 % | 3 | 0.38 |
| 9 | 9 | 40,831 | 4-5-9-7-0-3-2-6-8 | 29.9 % | 3 | {0,2,3,4,5,6,7,8,9} | 48.1 % | 3 | 40,244 | 29.9 % | 35.1 % | 5 | 0.56 |
| 10 | 5 | 456 | 4-5-9-7-0-3-2-6-1-8 | 45.8 % | 1 | {0,1,2,3,4,5,6,7,8,9} | 100.0 % | 5 | 0 |  |  | 0 |  |

"Top order share" is the top prefix's through-count over all through-counts at that level; "top set share" groups prefixes by
the set of targets broken. "Share in top-order family" is the share of bursts started at that level or deeper whose prefix
begins with the top order, with the matching share of their burst ticks. "Mean next/live" is the mean over the level's prefixes
of (distinct next targets ever broken) / (targets still live).

### 2.2 Families and their budget

At level 5, the right-side set {0,4,5,7,9} holds 77.3 % of the trajectories; 10 of its 120 permutations were played, and two
of them hold 97.9 % of that set (4-0-5-7-9: 37,920; 4-5-9-7-0: 37,374; the next, 0-4-5-7-9, 1,079). The second set at level
5, {0,3,4,5,9} (17.4 %), is the reference clear's family (0-4-9-5-3: 16,122).

Budget by family (bursts started at the family's level or deeper, and their burst ticks):

| family prefix | level | through | bursts started in the subtree | share of bursts started at this level or deeper | burst ticks in the subtree | share |
|---|---|---|---|---|---|---|
| 4-0-5-7-9 | 5 | 37,920 | 37,637 | 38.1 % | 3,544,386 | 33.0 % |
| 4-5-9-7-0 | 5 | 37,374 | 37,183 | 37.7 % | 3,830,810 | 35.7 % |
| 0-4-9-5-3 | 5 | 16,122 | 16,031 | 16.2 % | 1,745,198 | 16.3 % |
| all other level-5 prefixes (30) | 5 | 8,089 | 7,844 | 7.9 % | 1,605,743 | 15.0 % |
| 4-5-9-7-0-3-2 | 7 | 34,526 | 34,519 | 45.0 % | 3,359,210 | 47.0 % |
| 4-0-5-7-9-3-2 | 7 | 30,112 | 30,065 | 39.2 % | 2,470,041 | 34.5 % |
| 0-4-9-5-3-7-2 | 7 | 10,845 | 10,807 | 14.1 % | 1,140,230 | 15.9 % |
| all other level-7 prefixes (12) | 7 | 1,392 | 1,264 | 1.6 % | 180,196 | 2.5 % |

(Level 5 or deeper: 98,695 bursts started, 10,726,137 burst ticks. Level 7 or deeper: 76,655 and 7,149,677.)

### 2.3 Where the tree is thin

- **First break.** 79.6 % of all trajectories broke target 4 first and 19.7 % target 0 first; targets 9, 5, 3 and 2 first hold
  636, 203, 51 and 3 trajectories; 1, 6, 7 and 8 were never first. From the root, 6 of 10 targets were ever broken first.
- **One next target only.** 43 of the 180 prefixes have exactly one observed next target although two or more are live; 77
  prefixes below level 10 (43 % of the 180) have no observed next target at all. The big ones: 4-5-9-7-0-3 (35,432 through, 4 live, only 2 next);
  0-4-9-5-3-7 (14,096, 4 live, only 2 next); 4-0-5-7-9-3-2-8 (12,907, 2 live, only 1 next); 4-0-5-7-9-3-2-8-1 (8,089 through,
  7,996 bursts started, 488,172 burst ticks, 1 live, never broken).
- **Dead ends with budget** (no child, bursts started there): 4-0-5-7-9-3-2-8-1 (7,996 bursts); 4-5-9-0 (1,712); 4-5-9-7-0-3-2-1
  (1,374); 4-5-9-7-0-3-2-8-1 (785); 4-0-5-7-9-3-2-1 (695); 0-4-9-5-3-7-2-6-1 (575); 4-0-5-7-9-2-3 (404); 4-9-0-7-5 (336).
- **Thin levels.** Level 1 has 6 prefixes, level 2 has 16, level 3 has 26, level 4 has 38 (the widest), then 33, 19, 15, 12, 9, 5.
  The tree narrows from level 4 on: the search's effort went into deepening a few prefixes, not into widening.
- **Pairs never played although both were live together**: 23 (section 3.2).

### 2.4 Plain statement for the stage 2 design

By target set the search has explored one order family: at levels 6 and 7, 94.9 % and 99.5 % of all trajectories have broken
the same targets, and the level-8 and level-9 sets differ only in which of the last three targets came first. By order it has
explored three families of the same set, which differ in the permutation of the first five targets and in the order of the last
three; together they hold 98 % of the trajectories and
of the budget from level 7 on. Within the first five targets, 110 of 120 permutations have zero trajectories; the 10 played
ones are listed in the level-5 rows of the tree. Nothing in the records shows an order whose first break is 1, 6, 7 or 8, an
order in which 6 or 1 is broken before 2, or an order in which 6 follows 8 or 1.

## 3. Segment map

### 3.1 Ordered pairs (A then B) with the class at A's break

Count, fastest and median are over the instances played by a burst itself (prefix replays are not re-counted). The class is the
archive's resource class at the tick of A's break, read from the cell key reached at that tick (archive, frontier members, run 1
and 2 kept cells) or from the trace for the reference; "unrecorded" means no cell was kept at that tick. "start -> B" is the
segment from tick 0 to the first break (class G, floor line 4 for all).

| A then B | instances | fastest (ticks) | median | class at A's break: instances / fastest / median | fastest instance |
|---|---|---|---|---|---|
| start -> 0 | 106 | 43 | 123 | G 106 / 43 / 123 | rd1 burst 8, ticks 0 -> 43 |
| start -> 2 | 2 | 258 | 258 | G 2 / 258 / 258 | rd4 burst 12783, ticks 0 -> 258 |
| start -> 3 | 9 | 261 | 412 | G 9 / 261 / 412 | rd3 burst 9395, ticks 0 -> 261 |
| start -> 4 | 56 | 26 | 118 | G 56 / 26 / 118 | rd1 burst 19, ticks 0 -> 26 |
| start -> 5 | 29 | 66 | 147 | G 29 / 66 / 147 | trail pair 1 lead k8, ticks 0 -> 66 |
| start -> 9 | 39 | 36 | 137 | G 39 / 36 / 137 | trail pair 0 control k9, ticks 0 -> 36 |
| 0 -> 2 | 9 | 22 | 139 | A1 5 / 22 / 153; G 3 / 55 / 103; A0 1 / 162 / 162 | frontier round 159 sid 1037 k12, ticks 783 -> 805 |
| 0 -> 3 | 87 | 11 | 51 | A1 70 / 11 / 42; A2 9 / 98 / 138; G 6 / 78 / 185; A0 2 / 172 / 190 | sd2 burst 19957, ticks 524 -> 535 |
| 0 -> 4 | 68 | 16 | 77 | A2 54 / 46 / 77; G 9 / 23 / 30; A0 2 / 16 / 16; unrecorded 2 / 22 / 99; A1 1 / 52 / 52 | rd3 burst 7835, ticks 314 -> 330 |
| 0 -> 5 | 44 | 45 | 141 | G 18 / 45 / 93; A2 16 / 83 / 281; A1 9 / 83 / 113; unrecorded 1 / 114 / 114 | frontier round 170 sid 210 k91, ticks 108 -> 153 |
| 0 -> 7 | 11 | 40 | 79 | A2 7 / 59 / 79; A1 3 / 40 / 53; G 1 / 243 / 243 | frontier round 200 sid 1207 k12, ticks 590 -> 630 |
| 0 -> 9 | 1,126 | 6 | 66 | A1 452 / 47 / 66; A2 309 / 34 / 53; A0 207 / 47 / 47; G 152 / 6 / 157; unrecorded 6 / 11 / 151 | frontier round 207 sid 1243 k0, ticks 114 -> 120 |
| 1 -> 8 | 255 | 100 | 164 | A2 209 / 141 / 164; A1 26 / 150 / 201; A0 20 / 100 / 135 | run2 n 38159 cid 23931 k2, ticks 1180 -> 1280 |
| 2 -> 0 | 16 | 187 | 329 | A0 11 / 223 / 292; A1 3 / 187 / 450; A2 2 / 386 / 432 | frontier round 108 sid 751 k31, ticks 597 -> 784 |
| 2 -> 1 | 28 | 493 | 563 | A2 20 / 493 / 540; unrecorded 5 / 511 / 594; A0 3 / 590 / 628 | run1 n 19850 cid 17187 k0, ticks 848 -> 1341 |
| 2 -> 3 | 77 | 82 | 346 | A0 67 / 128 / 356; A1 7 / 82 / 253; A2 2 / 277 / 280; unrecorded 1 / 285 / 285 | frontier round 31 sid 299 k1, ticks 556 -> 638 |
| 2 -> 6 | 122 | 245 | 440 | A2 70 / 245 / 440; A0 38 / 354 / 467; unrecorded 14 / 352 / 449 | trail pair 170 lead k0, ticks 1237 -> 1482 |
| 2 -> 7 | 40 | 108 | 274 | A1 37 / 259 / 274; A0 3 / 108 / 205 | frontier round 155 sid 1019 k7, ticks 871 -> 979 |
| 2 -> 8 | 77 | 335 | 474 | unrecorded 45 / 335 / 464; A2 22 / 403 / 455; A0 10 / 466 / 534 | run2 n 1185 cid 22220 k0, ticks 639 -> 974 |
| 3 -> 0 | 135 | 77 | 201 | A1 75 / 77 / 168; G 53 / 107 / 262; A2 6 / 180 / 281; A0 1 / 426 / 426 | frontier round 75 sid 534 k45, ticks 601 -> 678 |
| 3 -> 2 | 72 | 12 | 276 | G 59 / 32 / 298; A2 6 / 24 / 51; A1 6 / 12 / 66; A0 1 / 244 / 244 | frontier round 183 sid 1140 k10, ticks 513 -> 525 |
| 3 -> 5 | 11 | 95 | 196 | G 10 / 95 / 217; A2 1 / 196 / 196 | frontier round 202 sid 1192 k48, ticks 339 -> 434 |
| 3 -> 7 | 27 | 36 | 102 | G 26 / 68 / 102; A1 1 / 36 / 36 | sd2 burst 20738, ticks 458 -> 494 |
| 3 -> 8 | 7 | 433 | 468 | G 7 / 433 / 468 | run2 n 36065 cid 36207 k0, ticks 461 -> 894 |
| 3 -> 9 | 101 | 30 | 145 | G 41 / 30 / 207; A1 40 / 41 / 113; A0 17 / 60 / 84; A2 3 / 95 / 228 | frontier round 43 sid 313 k61, ticks 475 -> 505 |
| 4 -> 0 | 112 | 45 | 113 | A2 57 / 46 / 142; A1 51 / 45 / 86; A0 2 / 92 / 112; unrecorded 2 / 65 / 65 | rd4 burst 13848, ticks 169 -> 214 |
| 4 -> 2 | 4 | 220 | 314 | A2 4 / 220 / 314 | rd3 burst 9973, ticks 26 -> 246 |
| 4 -> 3 | 19 | 137 | 329 | A2 10 / 137 / 360; A0 9 / 157 / 263 | sd2 burst 20423, ticks 380 -> 517 |
| 4 -> 5 | 113 | 10 | 56 | A0 78 / 10 / 12; A1 17 / 50 / 58; A2 16 / 53 / 213; unrecorded 2 / 172 / 172 | rd3 burst 6995, ticks 157 -> 167 |
| 4 -> 7 | 9 | 175 | 322 | A0 9 / 175 / 322 | rd3 burst 10366, ticks 343 -> 518 |
| 4 -> 9 | 155 | 49 | 176 | A0 101 / 130 / 192; A2 31 / 49 / 179; A1 22 / 64 / 98; unrecorded 1 / 176 / 176 | rd3 burst 8071, ticks 238 -> 287 |
| 5 -> 0 | 286 | 70 | 148 | A0 271 / 83 / 148; A1 15 / 70 / 153 | rd2 burst 5400, ticks 288 -> 358 |
| 5 -> 2 | 6 | 225 | 246 | A0 6 / 225 / 246 | rd2 burst 6042, ticks 609 -> 834 |
| 5 -> 3 | 104 | 271 | 271 | A0 103 / 271 / 271; A1 1 / 303 / 303 | rd1 burst 438, ticks 609 -> 880 |
| 5 -> 4 | 73 | 22 | 132 | A0 56 / 98 / 170; A1 17 / 22 / 64 | rd2 burst 5140, ticks 79 -> 101 |
| 5 -> 7 | 1,431 | 11 | 17 | A0 1422 / 11 / 17; A1 5 / 51 / 60; unrecorded 4 / 13 / 17 | rd3 burst 9514, ticks 516 -> 527 |
| 5 -> 9 | 210 | 54 | 177 | A0 125 / 95 / 210; A1 78 / 54 / 101; unrecorded 7 / 87 / 193 | frontier round 6 sid 37 k5, ticks 270 -> 324 |
| 6 -> 1 | 77 | 89 | 179 | A2 60 / 114 / 169; A1 15 / 89 / 281; A0 1 / 249 / 249; unrecorded 1 / 166 / 166 | run1 n 23510 cid 11288 k0, ticks 1308 -> 1397 |
| 6 -> 3 | 2 | 406 | 597 | A1 1 / 597 / 597; unrecorded 1 / 406 / 406 | run2 n 32468 cid 34782 k1, ticks 1121 -> 1527 |
| 6 -> 8 | 382 | 39 | 97 | A2 231 / 54 / 90; A1 95 / 42 / 98; unrecorded 35 / 39 / 138; G 19 / 149 / 188; A0 2 / 170 / 202 | trail pair 192 control k5, ticks 1777 -> 1816 |
| 7 -> 0 | 664 | 20 | 29 | A0 486 / 29 / 29; A1 177 / 20 / 174; unrecorded 1 / 331 / 331 | sd2 burst 20862, ticks 504 -> 524 |
| 7 -> 2 | 52 | 24 | 357 | A0 38 / 357 / 357; A1 14 / 24 / 37 | frontier round 35 sid 216 k121, ticks 482 -> 506 |
| 7 -> 3 | 36 | 102 | 255 | A1 20 / 102 / 173; A0 13 / 225 / 369; unrecorded 3 / 208 / 315 | frontier round 92 sid 216 k510, ticks 482 -> 584 |
| 7 -> 4 | 10 | 115 | 207 | A0 10 / 115 / 207 | rd3 burst 7686, ticks 445 -> 560 |
| 7 -> 5 | 50 | 30 | 37 | A1 49 / 30 / 36; A0 1 / 476 / 476 | frontier round 17 sid 195 k4, ticks 553 -> 583 |
| 7 -> 6 | 2 | 102 | 102 | A1 2 / 102 / 102 | trail pair 183 lead k3, ticks 1387 -> 1489 |
| 7 -> 9 | 307 | 96 | 144 | A0 203 / 96 / 147; unrecorded 104 / 97 / 138 | frontier round 114 sid 241 k718, ticks 184 -> 280 |
| 8 -> 1 | 329 | 45 | 114 | A2 180 / 53 / 103; A1 124 / 45 / 150; A0 18 / 144 / 165; unrecorded 7 / 61 / 102 | run2 n 813 cid 9709 k1, ticks 1307 -> 1352 |
| 9 -> 0 | 1,774 | 2 | 55 | A1 726 / 2 / 29; G 569 / 3 / 68; A2 306 / 2 / 73; A0 172 / 27 / 71; unrecorded 1 / 77 / 77 | rd2 burst 3223, ticks 352 -> 354 |
| 9 -> 2 | 8 | 164 | 283 | A1 2 / 283 / 283; A0 2 / 257 / 396; A2 2 / 164 / 293; G 1 / 235 / 235; unrecorded 1 / 227 / 227 | frontier round 106 sid 240 k565, ticks 322 -> 486 |
| 9 -> 3 | 55 | 101 | 240 | G 30 / 101 / 265; A2 12 / 126 / 240; A0 7 / 156 / 217; A1 6 / 140 / 251 | frontier round 142 sid 950 k8, ticks 446 -> 547 |
| 9 -> 4 | 70 | 9 | 132 | G 49 / 32 / 132; A2 20 / 9 / 106; A0 1 / 109 / 109 | rd3 burst 6408, ticks 262 -> 271 |
| 9 -> 5 | 453 | 12 | 12 | A0 357 / 12 / 12; G 83 / 52 / 210; A1 6 / 26 / 104; A2 5 / 138 / 138; unrecorded 2 / 83 / 94 | frontier round 15 sid 180 k10, ticks 254 -> 266 |
| 9 -> 7 | 11 | 35 | 100 | A2 7 / 35 / 100; A0 2 / 120 / 216; unrecorded 2 / 87 / 93 | frontier round 133 sid 898 k14, ticks 332 -> 367 |

### 3.2 Matrix and pairs never observed

Instances / fastest ticks for each ordered pair (row A, column B; "-" never observed):

| A \ B | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | . | - | 9 / 22 | 87 / 11 | 68 / 16 | 44 / 45 | - | 11 / 40 | - | 1,126 / 6 |
| 1 | - | . | - | - | - | - | - | - | 255 / 100 | - |
| 2 | 16 / 187 | 28 / 493 | . | 77 / 82 | - | - | 122 / 245 | 40 / 108 | 77 / 335 | - |
| 3 | 135 / 77 | - | 72 / 12 | . | - | 11 / 95 | - | 27 / 36 | 7 / 433 | 101 / 30 |
| 4 | 112 / 45 | - | 4 / 220 | 19 / 137 | . | 113 / 10 | - | 9 / 175 | - | 155 / 49 |
| 5 | 286 / 70 | - | 6 / 225 | 104 / 271 | 73 / 22 | . | - | 1,431 / 11 | - | 210 / 54 |
| 6 | - | 77 / 89 | - | 2 / 406 | - | - | . | - | 382 / 39 | - |
| 7 | 664 / 20 | - | 52 / 24 | 36 / 102 | 10 / 115 | 50 / 30 | 2 / 102 | . | - | 307 / 96 |
| 8 | - | 329 / 45 | - | - | - | - | - | - | . | - |
| 9 | 1,774 / 2 | - | 8 / 164 | 55 / 101 | 70 / 9 | 453 / 12 | - | 11 / 35 | - | . |

Pairs never observed although both targets were live together, with the number of trajectories at a node ending in A where B
was still live (the opportunity count):

| A then B | trajectories at a node ending in A with B still live |
|---|---|
| 4 -> 1 | 131,119 |
| 4 -> 6 | 131,119 |
| 4 -> 8 | 131,119 |
| 5 -> 1 | 123,986 |
| 5 -> 6 | 123,986 |
| 5 -> 8 | 123,986 |
| 0 -> 1 | 123,569 |
| 0 -> 6 | 123,569 |
| 0 -> 8 | 123,569 |
| 9 -> 1 | 120,361 |
| 9 -> 6 | 120,361 |
| 9 -> 8 | 120,361 |
| 7 -> 1 | 99,653 |
| 7 -> 8 | 99,653 |
| 3 -> 1 | 92,098 |
| 3 -> 6 | 92,096 |
| 8 -> 6 | 15,706 |
| 1 -> 6 | 11,019 |
| 8 -> 2 | 164 |
| 3 -> 4 | 67 |
| 2 -> 5 | 42 |
| 2 -> 9 | 33 |
| 2 -> 4 | 4 |

### 3.3 Fastest instances from an unusual start class

Pairs where the class of the fastest instance holds at most a quarter of the pair's instances and beats the fastest of the most
common class (from the table in 3.1): 0 -> 4 (A0, 2 of 68 instances, 16 ticks against A2's 46); 0 -> 9 (G, 152 of 1,126, 6
against A1's 47); 1 -> 8 (A0, 20 of 255, 100 against A2's 141); 2 -> 0 (A1, 3 of 16, 187 against A0's 223); 2 -> 3 (A1, 7 of 77,
82 against A0's 128); 2 -> 7 (A0, 3 of 40, 108 against A1's 259); 3 -> 2 (A1, 6 of 72, 12 against G's 32); 3 -> 7 (A1, 1 of 27,
36 against G's 68); 4 -> 9 (A2, 31 of 155, 49 against A0's 130); 5 -> 0 (A1, 15 of 286, 70 against A0's 83); 5 -> 4 (A1, 17 of
73, 22 against A0's 98); 6 -> 1 (A1, 15 of 77, 89 against A2's 114); 9 -> 2 (A2, 2 of 8, 164 against A1's 283). Instances by
class over all pairs: A0 3,878; A1 2,178; A2 1,677; G 1,377; unrecorded 248; X 0.

### 3.4 The verified bests, break by break (exact, from their traces)

Tick of each break, the class and status class at that tick, and the floor line when grounded:

| clear | breaks (tick: target, class, status class, floor) |
|---|---|
| 1,245 (run 2 n 36236) | 29: 4 A1 attack_air; 80: 0 A1 attack_air; 167: 5 A0 special_hi; 184: 7 A0 special_hi; 305: 9 A0 special_hi; 461: 3 G crouch_pass floor 1; 639: 2 G special_lw floor 19 (the moving line); 1,042: 6 A2 special_lw; 1,135: 8 A2 attack_air; 1,245: 1 A1 attack_air |
| 1,261 (run 2 n 19643) | same as the 1,245 to 1,042; 1,195: 8 A1 attack_air; 1,261: 1 A1 attack_air |
| 1,352 (run 2 n 813) | 28: 4 A1 attack_air; 95: 5 A0 special_hi; 246: 9 A2 special_n; 482: 7 A1 special_n; 663: 0 A1 attack_air; 761: 3 G dash_run floor 1; 848: 2 A2 special_lw; 1,231: 6 A1 attack_air; 1,307: 8 A1 special_n; 1,352: 1 A1 attack_air |
| 1,429 (run 1 n 28613) | same as the 1,352 to 848; 1,288: 6 A2 attack_air; 1,356: 8 A2 attack_air; 1,429: 1 A2 attack_air |
| 1,588 (run 1 n 25467) | same as the 1,352 to 848; 1,288: 6 A2 attack_air; 1,447: 1 A2 attack_air; 1,588: 8 A1 attack_air |
| 1,884 (splice c073_cid2290) | 43: 0 A2 attack_air; 120: 4 A0 special_hi; 399: 9 G attack_ground floor 4; 609: 5 A0 special_hi; 880: 3 G roll floor 2; 982: 7 A0 special_hi; 1,338: 2 A0 special_hi; 1,775: 6 A2 attack_air; 1,831: 8 A2 attack_air; 1,884: 1 A2 attack_air |
| 1,885 (reference) | as the 1,884 with 1,339 / 1,776 / 1,832 / 1,885 |

## 4. Arrival times at moving geometry

### 4.1 What the records hold

Only the per-tick traces hold the moving groups' translation (every tick of `spatial.groups`); the dispatch rows' break events,
the archive cells and the lab cells hold none. The traces are 823 files; after dropping the 313 r2 replays identical to their
r1 by per-tick hash, 510 traces remain, holding 186,652 unique ticks (shared prefixes collapsed by the anomaly cache's per-tick
state hash): 0.42 % of the 44.1 M burst ticks, from 495 distinct trajectories (321 verified-clear traces, 189 splice-probe
candidates including the only 57 recorded falls, the reference). Everything in this section describes those ticks only.

The recorded geometry (identical in all 823 traces) has 20 lines in two groups: 19 lines in group 1, whose recorded translation
is (0, 0) on every tick, and 1 line (id 19) in group 2. Group 2's translation x is 2,700 on every tick; its translation y lies
between 1,500 and 3,300. The translation y at a given input tick is the same in every record that holds that tick (5,913 distinct
ticks between 1 and 1,971, none with two values). As recorded, it turns at ticks 89 (3300), 239 (1500), 389 (3300), 539 (1500), 689 (3300), 839 (1500), 989 (3300), 1,139 (1500), …: a turning point every 150
ticks, alternating between the two bounds, and 2,168.3 at tick 1. The fighter's left-wall, right-wall and ceiling ids never name
line 19 in any unique tick (they always name a group-1 line; the anomaly inventory noted these fields hold the last contact).

### 4.2 Contacts

A contact tick is a unique tick whose fighter floor line is line 19. A landing is the first tick of a run of consecutive contact
ticks in one trace, deduplicated by the per-tick state hash of that first tick.

| quantity | value |
|---|---|
| unique contact ticks | 5,336 of 186,652 (2.9 %) |
| distinct landings | 36 |
| ticks on the line per landing (min / median / max) | 3 / 87 / 358 |
| landings while the line moves down / up | 27 / 9 |
| status at landing | up-B (special_hi, id 226) 31; aerial attack (211) 1; neutral special (224) 1; airborne (24, 26, 27) 3; the status class names are the classifier's labels for the recorded status ids |
| traces with at least one contact tick (including shared prefix ticks) | 377 of 510; all 321 clear traces; 56 of 189 splice candidates |
| breaks performed while standing on the line | 5 (all of target 2) |

Contact ticks and landings by hundred-unit bin of the translation y (presence = unique ticks in that bin, on the line or not):

| translation y from | to | unique ticks present | unique contact ticks | contact share | landings (episode starts) |
|---|---|---|---|---|---|
| 1500 | 1600 | 26,386 | 1,004 | 3.8 % | 7 |
| 1600 | 1700 | 12,360 | 420 | 3.4 % | 4 |
| 1700 | 1800 | 8,630 | 287 | 3.3 % | 0 |
| 1800 | 1900 | 8,575 | 293 | 3.4 % | 1 |
| 1900 | 2000 | 8,621 | 284 | 3.3 % | 3 |
| 2000 | 2100 | 7,384 | 252 | 3.4 % | 1 |
| 2100 | 2200 | 6,149 | 204 | 3.3 % | 1 |
| 2200 | 2300 | 7,445 | 240 | 3.2 % | 1 |
| 2300 | 2400 | 6,271 | 205 | 3.3 % | 0 |
| 2400 | 2500 | 7,519 | 240 | 3.2 % | 1 |
| 2500 | 2600 | 7,485 | 238 | 3.2 % | 1 |
| 2600 | 2700 | 6,251 | 192 | 3.1 % | 0 |
| 2700 | 2800 | 7,500 | 206 | 2.7 % | 8 |
| 2800 | 2900 | 8,722 | 206 | 2.4 % | 6 |
| 2900 | 3000 | 8,682 | 184 | 2.1 % | 2 |
| 3000 | 3100 | 8,731 | 175 | 2.0 % | 0 |
| 3100 | 3200 | 12,581 | 230 | 1.8 % | 0 |
| 3200 | 3300 | 26,730 | 465 | 1.7 % | 0 |
| 3300 | 3400 | 630 | 11 | 1.7 % | 0 |

Contact ticks occur in every bin because a fighter who lands rides the line through its range (the longest run is 358 ticks,
more than a full cycle). Landings never used the bins 1,700, 2,300, 2,600 and 3,000 to 3,300 (7 of 19 bins); 25 of the 36
landings are in the bins 1,500 to 1,700 and 2,700 to 2,900.

By input tick:

| input ticks | unique contact ticks | landings |
|---|---|---|
| 500 to 599 | 61 | 1 |
| 600 to 699 | 100 | 0 |
| 700 to 799 | 34 | 0 |
| 800 to 899 | 77 | 1 |
| 900 to 999 | 61 | 0 |
| 1,000 to 1,099 | 40 | 2 |
| 1,100 to 1,199 | 430 | 7 |
| 1,200 to 1,299 | 542 | 1 |
| 1,300 to 1,399 | 1,177 | 16 |
| 1,400 to 1,499 | 1,350 | 5 |
| 1,500 to 1,599 | 801 | 3 |
| 1,600 to 1,699 | 303 | 0 |
| 1,700 to 1,799 | 271 | 0 |
| 1,800 to 1,899 | 89 | 0 |

The 36 landings:

| trace | landing tick | leaves at | ticks on the line | translation y at landing | line moving | status at landing |
|---|---|---|---|---|---|---|
| crossing_2026-10-15_run2:clear_n19643_c9709_k0_r1 | 539 | 733 | 195 | 1500.0 | down | 226 |
| splice_probe_2026-10-14:c049_cid2704_r1 | 1,137 | 1,206 | 70 | 1501.0 | down | 226 |
| splice_probe_2026-10-14:c050_cid2703_r1 | 1,142 | 1,307 | 166 | 1502.1 | up | 226 |
| splice_probe_2026-10-14:c019_cid9685_r1 | 1,144 | 1,400 | 257 | 1505.9 | up | 226 |
| splice_probe_2026-10-14:c024_cid10644_r1 | 1,432 | 1,457 | 26 | 1511.4 | down | 26 |
| crossing_2026-10-15:clear_n10074_c9306_k6_r1 | 823 | 960 | 138 | 1557.1 | down | 211 |
| splice_probe_2026-10-14:c044_cid2920_r1 | 1,121 | 1,123 | 3 | 1571.5 | down | 226 |
| splice_probe_2026-10-14:c007_cid16729_r1 | 1,116 | 1,345 | 230 | 1614.0 | down | 224 |
| splice_probe_2026-10-14:c108_cid1153_r1 | 1,115 | 1,158 | 44 | 1623.5 | down | 226 |
| splice_probe_2026-10-14:c119_cid1077_r1 | 1,115 | 1,157 | 43 | 1623.5 | down | 226 |
| splice_probe_2026-10-14:c054_cid2677_r1 | 1,413 | 1,770 | 358 | 1643.5 | down | 226 |
| splice_probe_2026-10-14:c026_cid10405_r1 | 1,394 | 1,407 | 14 | 1888.8 | down | 27 |
| splice_probe_2026-10-14:c031_cid5759_r1 | 1,488 | 1,843 | 356 | 1950.8 | up | 226 |
| splice_probe_2026-10-14:c032_cid5758_r1 | 1,489 | 1,844 | 356 | 1966.7 | up | 226 |
| splice_probe_2026-10-14:c030_cid6456_r1 | 1,490 | 1,560 | 71 | 1982.8 | up | 226 |
| splice_probe_2026-10-14:c132_cid1067_r1 | 1,082 | 1,122 | 41 | 2082.2 | down | 226 |
| splice_probe_2026-10-14:c036_cid4442_r1 | 1,078 | 1,154 | 77 | 2150.9 | down | 226 |
| splice_probe_2026-10-14:c193_cid91_r1 | 1,507 | 1,548 | 42 | 2274.4 | up | 226 |
| splice_probe_2026-10-14:c051_cid2634_r1 | 1,361 | 1,449 | 89 | 2454.0 | down | 226 |
| splice_probe_2026-10-14:c028_cid9681_r1 | 1,524 | 1,602 | 79 | 2578.9 | up | 226 |
| crossing_2026-10-15:reference | 1,347 | 1,529 | 183 | 2700.8 | down | 226 |
| splice_probe_2026-10-14:c029_cid8937_r1 | 1,347 | 1,525 | 179 | 2700.8 | down | 226 |
| splice_probe_2026-10-14:c072_cid2291_r1 | 1,346 | 1,526 | 181 | 2717.8 | down | 226 |
| splice_probe_2026-10-14:c073_cid2290_r1 | 1,346 | 1,527 | 182 | 2717.8 | down | 226 |
| splice_probe_2026-10-14:c084_cid2186_r1 | 1,346 | 1,527 | 182 | 2717.8 | down | 226 |
| splice_probe_2026-10-14:c071_cid2292_r1 | 1,345 | 1,524 | 180 | 2734.7 | down | 226 |
| splice_probe_2026-10-14:c070_cid2295_r1 | 1,342 | 1,425 | 84 | 2784.6 | down | 226 |
| splice_probe_2026-10-14:c160_cid631_r1 | 1,236 | 1,414 | 179 | 2784.6 | up | 226 |
| splice_probe_2026-10-14:c177_cid160_r1 | 1,341 | 1,353 | 13 | 2801.0 | down | 226 |
| splice_probe_2026-10-14:c178_cid161_r1 | 1,341 | 1,353 | 13 | 2801.0 | down | 226 |
| splice_probe_2026-10-14:c179_cid242_r1 | 1,341 | 1,353 | 13 | 2801.0 | down | 226 |
| splice_probe_2026-10-14:c180_cid241_r1 | 1,341 | 1,515 | 175 | 2801.0 | down | 226 |
| splice_probe_2026-10-14:c190_cid139_r1 | 1,339 | 1,345 | 7 | 2833.3 | down | 226 |
| splice_probe_2026-10-14:c192_cid92_r1 | 1,339 | 1,347 | 9 | 2833.3 | down | 226 |
| splice_probe_2026-10-14:c050_cid2703_r1 | 1,332 | 1,418 | 87 | 2941.1 | down | 226 |
| splice_probe_2026-10-14:c193_cid91_r1 | 1,550 | 1,567 | 18 | 2998.2 | up | 24 |

The 5 breaks performed while the fighter's floor was the moving line:

| trace | break tick | target | translation y | line moving |
|---|---|---|---|---|
| crossing_2026-10-15:clear_n10074_c9306_k6_r1 | 848 | 2 | 1518.7 | up |
| splice_probe_2026-10-14:c051_cid2634_r1 | 1,363 | 2 | 2418.0 | down |
| splice_probe_2026-10-14:c019_cid9685_r1 | 1,237 | 2 | 2801.0 | up |
| crossing_2026-10-15_run2:clear_n19643_c9709_k0_r1 | 639 | 2 | 2833.3 | up |
| splice_probe_2026-10-14:c020_cid11141_r1 | 1,274 | 2 | 3249.6 | up |

The verified bests: the 1,245 and 1,261 land on the line at tick 539 (translation y exactly 1,500.0, the bottom turning point of
the recorded series) and leave at 733 (195 ticks), breaking target 2 from the line at tick 639 (y 2,833, moving up); the 1,352
and 1,429 land at 823 (y 1,557, moving down) and leave at 960 (138 ticks); the reference lands at 1,347 (y 2,700.8, moving down)
and leaves at 1,529 (183 ticks). The three verified order families thus arrive at the line at three different translations and
in two directions of travel.

### 4.3 Coverage caveat

The 8,262 break events in dispatch rows and the 49,928 archive cells carry no translation, so the arrival-time data above comes
from 0.42 % of the agent's ticks, almost all of it from verified clears of three lineages and from 198 splice candidates that
descend from the reference. The contact data describes those trajectories; it does not estimate what the other 99.6 % did.

## 5. Timing robustness for human viability (design only, no run)

**Question.** For a verified clear, how far can each hold boundary move before the clear is lost, and where are the zero-slack
boundaries. A hold is a run of identical controller words (one word per tick); a boundary is the tick where the word changes.

**The clears' hold structure (from their verified words, read from the verification rows and the reference's actions file).**

| clear | ticks | holds | boundaries | holds of 1 tick | 2 ticks | 4 | 8 | 10 or more | longest hold |
|---|---|---|---|---|---|---|---|---|---|
| 1,245 | 1,245 | 207 | 206 | 36 | 42 | 42 | 46 | 36 | 16 |
| 1,261 | 1,261 | 210 | 209 | 37 | 44 | 42 | 43 | 38 | 16 |
| 1,352 | 1,352 | 227 | 226 | 47 | 50 | 45 | 40 | 43 | 32 |
| 1,429 | 1,429 | 241 | 240 | 46 | 57 | 40 | 46 | 45 | 24 |
| 1,885 (reference) | 1,885 | 338 | 337 | 69 | 66 | 69 | 63 | 49 | 22 |

(The hold lengths are multiples the search's word-run alphabet produces; 38 % of the 1,245's holds are one or two ticks long.)

**Perturbation.** For each boundary i and each shift d in {-3, -2, -1, +1, +2, +3}: lengthen hold i by d ticks and shorten hold
i+1 by d (so the sequence length and every other boundary are unchanged); skip a variant that would reduce a hold to zero ticks.
That is 6 variants per boundary: 1,236 for the 1,245, 1,254 for the 1,261, 1,356 for the 1,352, 1,440 for the 1,429, 2,022 for
the reference (fewer after the zero-length skips). A second pass may add the two-sided variants (two adjacent boundaries moved
together, 36 per pair), which is out of scope for a first measurement.

**Measurement.** Replay each variant from tick 0 in its own process (or a standby-promoted one, as the dispatch path does), with
the verify flags off (no per-tick trace), recording what the dispatch path already records: outcome (clear, fall, out of words),
`breaks_after_start` [tick, target] from tick 0, the fall tick, the completion clock. A variant survives to break k when its k-th
break is the same target as the original's (the tick may differ); it survives the clear when it completes. Per boundary, the
slack is the largest shift in each direction that still clears; per break, the share of boundaries before it with slack of at
least 1 in both directions; the result lists the zero-slack boundaries by tick (data, not a rule). Variants are compared to the
original by their break lists, never by RNG state.

**Cost under today's pipeline** (measured values from the records): standby-promoted stepping ran at a median 1.09 ms per tick
in run 2 (`step_s` / `ticks` over 39,309 dispatches), with the standby wait at about 0.9 s per job (`docs/frs_prefix_cost_2026-10-14.md`);
a fresh-process replay with the verify flags, as the splice probe ran, costs a median 2.09 s of startup plus 2.77 ms per tick
(208 replays). So one variant of the 1,245 costs about 2.3 s in standby mode (1.4 s stepping, 0.9 s wait) or about 5.6 s with a
trace. With five workers: about 9 to 10 minutes for the 1,245's 1,236 variants in standby mode (23 minutes with traces); about
55 to 60 minutes for all five clears (7,308 variants) in standby mode. It is one lab command run by hand, zero code in any rule,
and it needs the owner's explicit authorisation because it is a new native run. The savestate decision of November week 1 changes
the cost (a variant that moves boundary i only needs the state at boundary i), which is why section 7 recommends sequencing it
after that decision.

## 6. What to look at first in the replay browser

Ten trajectories chosen by generic criteria: the rarest order prefixes that still progressed, the fastest pairs that came from an
unusual start class, contacts at rarely used translations, and the largest dead ends. Nothing is claimed about any of them. The
browser's lab adapter (`replay/replay_lab.py`) opens verified clears by their r1 trace; a dispatch-only trajectory has no trace,
and its words are the start cell's `words_hex` (cells file) followed by the dispatch row's `words_hex` (the ledger's words are
in `bursts.bin` at `bin_off`). Ticks are input ticks.

| # | record and trajectory | ticks to look at | why (criterion) |
|---|---|---|---|
| 1 | `crossing_2026-10-15_run2/run/dispatches.jsonl`, n 38159 (cid 23931, k 2); no trace | 1,271 to 1,280 (break of 8 at 1,280) | the best claim (1,280) of the only full order never verified (4-0-5-7-9-3-2-6-1-8, 46 claims); its last segment 1 -> 8 is the fastest instance of that pair (100 ticks) and comes from its rarest class (A0, 20 of 255) |
| 2 | `crossing_2026-10-15_run2/run/dispatches.jsonl`, n 32468 (cid 34782, k 1); no trace | 1,286 to 1,646 (break of 3 at 1,527) | the rarest level-8 prefix that progressed: 4-0-5-7-9-2-6-3 (2 trajectories), the only one with target 3 after 6 |
| 3 | `trail_probe_2026-10-14/run/dispatches.jsonl`, pair 183, arm lead, k 3 (start cell 14008 of the import); no trace | 1,391 to 1,631 (break of 6 at 1,489) | prefix 0-4-9-5-3-2-7-6 (18 trajectories): one of the two instances of pair 7 -> 6 and the only level-8 prefix of the reference family with 2 before 7 |
| 4 | `frontier_2026-10-14/run/dispatches.jsonl`, round 157, sid 940, k 146; no trace | 500 to 980 (breaks of 7 at 667 and 0 at 696) | prefix 4-5-9-3-7-0: 472 trajectories broke 0 there themselves, 64 bursts were started from it, none broke a seventh target (11,400 burst ticks) |
| 5 | `frontier_2026-10-14/run/dispatches.jsonl`, round 183, sid 1140, k 10; no trace | 513 to 801 (break of 2 at 525, then a fall) | pair 3 -> 2 in 12 ticks from class A1 (6 of 72 instances; the common class G's fastest is 32) |
| 6 | `frontier_2026-10-14/run/dispatches.jsonl`, round 35, sid 216, k 121; no trace | 482 to 842 (breaks of 2 at 506 and 0 at 737) | pair 7 -> 2 in 24 ticks from class A1 (14 of 52; the common class A0's fastest is 357), prefix 4-5-9-7-2-0 |
| 7 | `splice_probe_2026-10-14/run/traces/c026_cid10405_r1.json.gz` (per-tick trace; not a verified clear, so not in the lab adapter's list) | 1,394 to 1,407 | landing on the moving line at translation y 1,888.8 while it moves down, in an airborne status (27): the only landing in the 1,800 to 1,900 bin and one of three landings not in an up-B status |
| 8 | `splice_probe_2026-10-14/run/traces/c193_cid91_r1.json.gz` (per-tick trace, as above) | 1,507 to 1,548 and 1,550 to 1,567 | two landings while the line moves up (2,274.4 and 2,998.2); the second is the highest landing translation observed and the only landing in its bin |
| 9 | `crossing_2026-10-15/run/dispatches.jsonl`, n 19850 (cid 17187, k 0); no trace | 1,318 to 1,554 (break of 1 at 1,341, then a fall) | first entry of the left side by target 1 in the largest family (4-5-9-7-0-3-2-1): 1,374 bursts started there, 103,246 burst ticks, none broke 6 or 8 afterwards |
| 10 | `crossing_2026-10-15_run2/run/dispatches.jsonl`, n 28549 (cid 23635, k 0); no trace | 1,046 to 1,166 (break of 1 at 1,051) | the largest dead end: 4-0-5-7-9-3-2-8-1, 7,996 bursts started (488,172 burst ticks), none broke 6; pair 8 -> 6 was never played in 15,706 opportunities |

The verified bests themselves (run 2 traces `clear_n36236_c8692_k0_r1`, `clear_n19643_c9709_k0_r1`, `clear_n813_c9709_k1_r1`;
run 1 `clear_n28613_c13926_k1_r1`) open directly in the browser; their moving-line landings are at ticks 539 and 823 (section 4.2).

## 7. Open questions for the owner (recommendation first)

1. **Regenerate this catalogue after every lab night?** Recommendation: yes, as a read-only post-run script in the lab tools
   (`r1_catalogue.py` runs in 10 s on today's records, zero native ticks), appending the per-level set and order shares to the
   run's report. Alternatives: by hand weekly; only at the checkpoints.
2. **Which concentration measure should the stage 2 design read?** Recommendation: both, with the set-level share as the headline
   (it separates "a different route" from "a different permutation") and the order-level share and the pair-coverage count
   (observed pairs over pairs that were live together) beside it. Alternatives: order-level only; pair coverage only. This record
   supplies the numbers; it does not choose the arm's rule.
3. **Run the timing-robustness check (section 5), and on what?** Recommendation: after the savestate decision of November week 1,
   on the best verified clear of each verified order family (the four lab bests and the reference), standby mode without traces,
   about an hour of native time, one lab command by hand, its output read by no rule. Alternatives: the 1,245 only now (about ten
   minutes); defer until tier 1 ends.
4. **The 46 clear claims of the never-verified full order.** Recommendation: leave the lab rule as it is (claims are replayed only
   when faster than the best) and let the catalogue carry "claimed, unverified" per order; whether a per-order verification is
   wanted is a stage 2 design question. Alternatives: replay the best claim of each unverified order once (two replays, about 40 s);
   verify all 46.
5. **Raise the coverage of the moving-geometry data?** Recommendation: record, in every dispatch row's break event, the fighter's
   floor group and each moving group's translation at the break tick (generic fields read from the spatial record the worker already
   holds; no new traces, no per-tick cost). Alternatives: trace a sample of non-clear bursts; keep as is (0.42 %).
6. **Open dispatch-only trajectories in the replay browser?** Recommendation: a lab-dispatch adapter that rebuilds the words
   (start cell words plus burst words), labelled LAB unverified, in November after the savestate decision. Alternatives: export the
   ten shortlisted trajectories' words by hand; leave as is (verified clears only).
7. **Which count defines "trajectories that reached a prefix"?** Recommendation: keep both counts (through = budget view, own =
   discovery view) and add a third in the next revision, distinct word prefixes per node, which removes the replayed-prefix
   duplication. Alternatives: own only; through only.

## Appendix A. Working files, commands and checks

Working folder `logs/frs_route/` (Git-ignored, confirmed with `git check-ignore`): `peek_rows.py`, `peek2a.py`, `peek2b.py`,
`peek3.py` (one-row looks at each record shape), `r1_catalogue.py` (lineage and catalogue; outputs `tree.json`, `pairs.json`,
`clears.json`, `summary.json`, console `r1_console.txt`; 10 s), `check_dups.py` (duplicate-target and mask-regain checks),
`r2_moving.py` (moving-geometry contacts from the anomaly cache; `moving.json`, `r2_console.txt`; 10 s), `r3_views.py` (set-level
shares, thin branches, class-unusual bests), `r4_tables.py` (the tables of this record, `tables.json`), `r5_assemble.py` (this
record from `record_prose.md` and the tables). All standard-library Python run with `python -B`, reading files only; total
script time under two minutes. Nothing was written to `C:/BattleShip_lab/`, D:, `rl/`, `tools/`, `port/` or `runs/`; no file
matching `rl/m9_g3_*`, `rl/m8_sd1_*`, `rl/m8_sd2_*`, `tools/m8_sd1/*` or `tools/m8_sd2/*` was edited or created; the registered
D: folders were not read. `rl/m8_rd_cells.py` was imported read-only for the classifier's status-id table. No RNG state or seed
was read.

Commands (from the checkout root, Git Bash):

    python -B logs/frs_route/r1_catalogue.py
    python -B logs/frs_route/r2_moving.py
    python -B logs/frs_route/r3_views.py
    python -B logs/frs_route/r4_tables.py
    python -B logs/frs_route/r5_assemble.py

Line endings: this record and every text working file were checked for CR bytes (all 0; see the assemble console). Git: `main`
at `5047fba`, working tree clean apart from this new record; nothing committed, pushed, branched or stashed. No `lab.lock`
existed and no BattleShip or Python process was running at the start.
