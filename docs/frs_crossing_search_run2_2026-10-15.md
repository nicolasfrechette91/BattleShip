# Crossing search run 2 (2026-10-15)

## Status and result

Lab experiment, exploratory and unregistered, continued from run 1's archive (`docs/frs_crossing_search_2026-10-15.md`), run on the night of
2026-10-15 to 2026-10-16 under the owner's go ("Go: run the exact command you gave, unchanged"). HEAD = origin/main = `f1a1ea1` ("Add crossing
search run 2"), the tree clean before and after; the run changed no tracked file. The question: from run 1's 32,744 kept cells, with the E7
bound tightened to run 1's best verified clear, can the search finish a clear faster than 1,429 input ticks?

**Answer: yes, three times, each one a new best.** In 466 minutes of dispatching (39,309 dispatches) the search verified a clear at 1,352
twenty-two minutes in, at 1,261 after four hours and a quarter, and at **1,245 input ticks / 1,244 time passed** (20.73 s against run 1's
23.80 s and the registered 31.40 s; a gain of 184 ticks over run 1 and 640 over the reference) after seven hours and twenty-one minutes.
Every verified clear was replayed twice from tick 0 in fresh processes with the verify flags, both replays identical with each other and
with the in-run claim. 136 clears were claimed in all; the 133 slower than the best at the time were counted and recorded but not replayed.
The two fastest clears descend from run 1's second lineage (seed 579, a level-6 state at tick 461), whose right side is finished at tick
639 against 848 for the lineage that cleared in run 1; the whole gain over run 1 is, again, the right side. Every one of the 3,916 inherited
cells checked natively before its first burst reproduced run 1's record (0 quarantines). Nothing here is a registered claim; `runs/` was
never read; no lab code was modified (lab code digest `0b248a9e30304325` at the plan, at the open, at the close and after the run).

## The design as run

Run 1's tool (`tools/frs/crossing_search.py`) is unchanged and reused by import; run 2 is `tools/frs/crossing_search_run2.py` (new, LF,
1,484 lines; `plan` zero-tick, `run` native; sha256 `55a0ef04…` at the run) with `tools/frs/crossing_search_run2_tests.py` (625 lines;
five zero-tick tests, all passing: the resume on the real run 1 archive, the archive rules on synthetic cells, the bound and the policies,
the refusals, a stub end-to-end with a synthetic run 1 made by run 1's own engine). The changes from run 1:

- **Resume.** The final representative of every run 1 cell (the last row per cell id of run 1's `run/cells.jsonl`) is loaded with the same
  cell id, its key, tick, exact prefix, chain and record digests, its later-arrival count as last recorded, and its dispatch statistics
  (dispatches, breaks) rebuilt from run 1's dispatch rows by key family and prefix digest; the prefix words are re-hashed to their digest
  at load. Cells beyond run 2's bound are loaded too, ineligible, so that a faster arrival at their key replaces the representative and
  makes it a fresh start (71,237 replacements happened; 144,999 reaches beyond the bound were dropped).
- **The end-record gap and the checks.** Run 1's cells file stores the chain and record digests but not the end observation tuple that
  the worker compares exactly before every burst, so every inherited cell was checked natively before its first burst by a fresh-process
  verify-flag replay of its prefix from tick 0 (run 1's seed check: every tick under the tick contract, the episode live, the chain digest,
  the record digest, the cell key and the level equal to run 1's record; the replay's last observation becomes the end record). Checking
  all 16,802 eligible cells at the open would have cost two to four hours, so the deepest eligible level (the 477 level-9 cells) and the
  earliest cell of every level were checked eagerly at the open (480 cells, 501 s at five replays), and every other cell lazily on its
  first draw: the draw is kept, the cell is checked on a lent idle worker (at most two lent at once, a lent worker being one standby plus
  one replay, so the ten-process cap holds), then dispatched. A mismatch quarantines the cell; more than three quarantines of any kind
  (eager, lazy or the worker's own prefix check) would have been SEARCH_INVALID.
- **E7 bound.** 1,404 = 1,429 minus the registered margin 24 minus one, through the registered rule (`m8_sd1_select.record_bound_max_L`)
  on the lowest completion_input_tick among run 1's VERIFIED rows (dispatch 28,613, cell 13926), never a literal; fixed for the run. That
  clear was replayed once at the open in a fresh process and reproduced exactly (clocks, chain `ab6341ef…`, action digest, break table).
- **Cleared starts.** A representative whose dispatch produced a claimed clear has its selection weight multiplied by 0.1 per clear (a
  tenth after one, a hundredth after two). Run 1's evidence decided against retirement: of its 180 re-draw clears, 14 were faster than the
  start's first clock, one of them the run's second-best clear (a 71-tick gain on the start's third dispatch). Run 1's own cleared starts
  (42 cells, 123 rows) were loaded with their clear count; 39 cells carried a clear count at the close.
- **Verification only when faster.** A claimed clear was replayed (twice, fresh processes, verify flags, on a lent worker) only when its
  claimed clock was below the best verified clear so far (1,429 at the open, then run 2's own); slower or equal claims were recorded with
  their words in `claims_not_replayed.jsonl`. A verified faster clear became the new best and dropped the queued slower claims.
- **Key family.** `<archive id>|crossing2|<prefix digest>` (iteration 0, 1, ... per representative): no run 1 burst was repeated whatever
  the dispatch count carried over (run 1's per-representative iteration counts reconstruct exactly from its rows, but the new family is
  safer).
- **Selection.** Run 1's terms unchanged: a level with weight 0.5^(deepest eligible level − level), then a cell with weight
  (1 + fresh)^-1 × (1 + seen)^-1 × (1 + breaks) × slack^0.5, times the cleared factor; CONT bursts of at most six 120-word segments under
  the F3 trigger read on this run's archive; Python experiment seed 1. Inherited cells carried their run 1 dispatch counts into the
  novelty term.
- **progress.md.** Rewritten at least every minute and on every event: the best verified clear against 1,429 and 1,885, the deepest
  level with its earliest tick, the cells per level (inherited, found, eligible, verified, pending, cleared, quarantined) and the lineages
  (root seed of run 1) ahead of the best clear's pace at levels 8 and 9.
- **Caps.** 480 minutes of wall (the dispatch deadline minus the close reserve), 80,000,000 ticks, 600,000 cells, five workers with one
  standby each and lent workers for the checks (at most ten game processes), the lab's memory sampler (soft budget = registered caps minus
  headroom), readiness at the registered thresholds.

## The run

| item | value |
|---|---|
| command | `python -B tools/frs/crossing_search_run2.py run --lab-root C:/BattleShip_lab --run1 C:/BattleShip_lab/crossing_2026-10-15 --out C:/BattleShip_lab/crossing_2026-10-15_run2 --workers 5 --level-decay 0.5 --novelty-exp 1 --seen-exp 1 --bonus-exp 1 --pace-exp 0.5 --max-segments 6 --retire-after 0 --cleared-weight 0.1 --check-slots 2 --check-queue-max 8 --eager-levels 1 --eager-max-min 15 --canary-per-level 1 --check-error-limit 10 --max-cells 600000 --rng-seed 1 --max-ticks 80000000 --max-wall-min 480` (launched detached, console at `run_console.txt`) |
| first attempt | 2026-10-15 23:50:40 UTC: **refused by readiness** (free commit 8,021 MB < 10,240 MB); nothing launched, no file changed, the lock released (`refused_20261015T235040Z.json`, `run_console_attempt1_refused.txt`). The owner closed idle sessions (free commit 12,545 MB); the same command was relaunched unchanged |
| time | 2026-10-16 01:22:04 to 09:17:24 UTC (21:22 to 05:17 local); 28,505 s wall (open 518 s of which the eager checks 501 s, search 27,982 s, drain 2 s, close 3 s) |
| readiness at the launch (registered thresholds) | free commit 12,545 MB (min 10,240), available 8,473 MB (min 4,096), free C: and D: above 5 GiB; no BattleShip process; import pins equal; lab code digest equal to run 1's |
| at open | the reference clear replayed exactly (1,885 / 1,884, 1.62 s of stepping); run 1's best clear replayed exactly (1,429 / 1,428, chain `ab6341ef…`); E7 bound 1,404; 32,744 inherited cells, eligible per level 9: 477, 8: 2,710, 7: 6,474, 6: 7,141; eager checks 480 of 480 reproduced |
| dispatches | 39,309, all returned (0 prefix mismatches, 0 lifecycle failures, 0 aborted, 0 tick-0 differences, 0 quarantines); level 9: 20,984 (53 %), 8: 10,528, 7: 5,208, 6: 2,589 |
| ticks | 54,086,814 in all: bursts' prefixes 46,603,859, bursts 3,568,728, inherited-cell checks 3,903,197, verification 7,716, reference 1,885, anchor 1,429 (cap 80,000,000 not reached) |
| throughput | 5,057 jobs per hour, 6.45 M ticks per hour, 1,276 ticks per job, 91 burst words per job; continuation 3,013 of 17,900 boundaries (16.8 %); burst lengths: 36,460 jobs within 120 words, 2,713 to 240, 117 to 360, the rest longer |
| outcomes | 24,285 falls (62 %; 73 % at level 9), 136 clears claimed (3 replayed and verified, 133 not replayed), 584 bursts broke a target |
| cells | 37,294 at the close (32,744 inherited, 4,550 new: level 6: 1,571; 7: 1,548; 8: 709; 9: 722); 71,237 replacements by faster arrivals; 509,661 later arrivals; 33,438 own-key reaches skipped; 144,999 reaches beyond the bound dropped; 24,421 terminal; eligible 32,252 (3,048 of them never checked, never drawn); words 39.3 MB |
| checks of inherited cells | 3,916 (480 eager, 3,436 lazy; 4 stale after a replacement in flight), 3,916 reproduced run 1's record, 0 quarantined, 0 could not run; 3,903,197 ticks, 19,772 s of lent-worker time, 5.05 s each; per level 9: 477, 8: 726, 7: 1,469, 6: 1,244; per UTC hour 1,101, 911, 609, 451, 311, 206, 174, 129, 24 |
| draws | 3,436 draws landed on an unverified cell and queued its check; 121 draws fell back to verified cells (the queue full); 0 worker waits; 0 ready cells dropped |
| processes and memory | 10 BattleShip processes at most; main process 584 MB after the load, 713 MB when the search began, 806 MB peak, 799 MB at the close; tree 4,635 MB private peak; no budget breach (soft budget 2,560 MB main); 10.4 MB per 1,000 new cells |
| status | WALL_CAP, exit 0; no candidate pending at the stop |

## Progress over time

Per hour of the search phase (hour 8 is its last 46 minutes):

| hour | dispatches | broke a target | falls | clears claimed | new cells | replacements | ticks |
|---|---|---|---|---|---|---|---|
| 1 | 4,145 | 65 | 2,094 | 14 | 384 | 8,531 | 5.51 M |
| 2 | 4,776 | 80 | 2,981 | 33 | 457 | 6,800 | 6.06 M |
| 3 | 5,055 | 73 | 3,441 | 10 | 883 | 7,163 | 6.31 M |
| 4 | 5,198 | 64 | 3,363 | 4 | 575 | 11,355 | 6.55 M |
| 5 | 5,274 | 65 | 3,459 | 7 | 432 | 10,997 | 6.72 M |
| 6 | 5,384 | 69 | 3,465 | 9 | 490 | 10,392 | 6.88 M |
| 7 | 5,401 | 92 | 3,198 | 29 | 706 | 9,666 | 6.91 M |
| 8 | 4,076 | 76 | 2,284 | 30 | 623 | 6,333 | 5.23 M |

The first hour was check-bound (1,101 checks, two workers lent most of the time); from the third hour the checks fell below 600 per hour and
the dispatch rate settled above 5,000 per hour.

The best verified clear over the run (dispatch counter, UTC, elapsed since the launch):

| best | previous | gain | dispatch, cell, k | start tick | utc | elapsed |
|---|---|---|---|---|---|---|
| 1,352 / 1,351 | 1,429 | 77 | 813, 9709, 1 | 1,328 | 01:44:39 | 22 min |
| 1,261 / 1,260 | 1,352 | 91 | 19,643, 9709, 0 | 1,232 | 05:37:01 | 4 h 15 min |
| 1,245 / 1,244 | 1,261 | 16 | 36,236, 8692, 0 | 1,209 | 08:43:01 | 7 h 21 min |

The earliest arrival per level (the reference arrives at levels 8 and 9 at 1,776 and 1,832; run 1's earliest were 1,096 and 1,300):

| level | run 1 | run 2 improvements (tick at dispatch, UTC) | earliest at the stop | lead on the reference |
|---|---|---|---|---|
| 9 | 1,300 | 1,293 at 2,274 (02:06); 1,072 at 2,723 (02:12); 1,053 at 13,636 (04:27); 1,051 at 28,551 (07:17) | **1,051** | 781 |
| 8 | 1,096 | 974 at 1,188 (01:50) | **974** | 802 |
| 7 | 493 | none (inherited seed) | 493 | 846 |
| 6 | 461 | none (inherited seed) | 461 | 521 |

The cells ahead of the best clear's pace at the close (level 8 before 1,042: 244 cells; level 9 before 1,135: 160 cells) all descend from
seed 579; the level-9 ones were dispatched 1,466 times for 3 breaks and no clear (see "What limited progress").

## Verified clears faster than 1,429

Three candidates were replayed, three VERIFIED (0 NONDETERMINISTIC, 0 ERROR, 0 unverified), each faster than the best verified clear at the
time. Every row is in `run/verifications.jsonl` with both replays' clocks, chains and break tables and the words; both traces of every
verified clear are in `run/traces/`.

| completion_input_tick / completion_time_passed | found (dispatch, cell, k; start tick, level) | replay 1 clocks | replay 2 clocks | replay 1 chain | replay 2 chain | words digest | utc | gain on run 1 / on the reference |
|---|---|---|---|---|---|---|---|---|
| **1,245 / 1,244** | 36,236, cell 8692, k 0; 1,209, level 9 | 1,245 / 1,244 | 1,245 / 1,244 | `668cd3ac62639aab84a2772a04234e6b13c2dbcd5dc1cd788befe08bb05b18fd` | identical | `1519833e8569ff7f6f27852727597dfac5a184d50c8580f9544e22b254828f14` | 08:43:01 | 184 / 640 |
| 1,261 / 1,260 | 19,643, cell 9709, k 0; 1,232, level 9 | 1,261 / 1,260 | 1,261 / 1,260 | `5ea72ae48ec0733ed4a55cacb912e839f8838e8a8450911e2d6af94810270aed` | identical | `53c94048ebe0db4c7e9e564faa9781c1e00d9bd3e2310e2a5c7e869e4b4cfb69` | 05:37:01 | 168 / 624 |
| 1,352 / 1,351 | 813, cell 9709, k 1; 1,328, level 9 | 1,352 / 1,351 | 1,352 / 1,351 | `f99c8a10ed67d480a291ddb97c2690ace4432a2dbd7c29eee5d0bca542a4e216` | identical | `1d90c6656f53047d1cace65c9f10afc5f8e9c373f35ca2ec5905c43ce4a03505` | 01:44:39 | 77 / 533 |

Each verification took 13 to 14 s on a lent worker. Stage names below describe the records; nothing in the search read them.

- **1,352** descends from seed 417 (run 1's cleared lineage; the right side done at 848 as in run 1's best): eight kept cells from the seed
  (run 1's cells 621 and 662 found at dispatches 36 and 43 of run 1, then run 1's 7089, 8368, 11026, 8698 and 9709), the last link being
  cell 9709's representative replaced at run 2's dispatch 120 with an arrival at 1,328; breaks at 1,231 (target 6), 1,307 (target 8) and
  1,352 (target 1).
- **1,261 and 1,245** descend from seed 579 (run 1's second lineage, a level-6 state at tick 461 that in run 1 reached level 8 at 1,096 in
  the sixth hour and never level 9). Their shared prefix breaks the seven right-side targets by tick 639 (order 4, 0, 5, 7, 9, 3, 2;
  run 1's best took until 848), crosses and breaks target 6 at 1,042 (run 1's best: 1,288), then target 8 at 1,195 or 1,135 and target 1
  at 1,261 or 1,245. The 1,261 chain is nine kept cells (run 1's cell 58 found at run 1's dispatch 5, then cells 22776, 7837, 7092, 13796,
  15395, 8593 replaced by run 2 at dispatches 11,236 to 17,010, and cell 9709 replaced again at 18,999); the 1,245 chain shares its first
  seven links and continues through cells 8577, 29246, 8689, 8691 (replaced at 29,049 to 34,242) to cell 8692 at 1,209, found at 35,106,
  which cleared on its first dispatch 1,130 dispatches later.
- The left side of the best clear (level 7 at 639 to the clear at 1,245) took 606 ticks, against 581 for run 1's best and 546 for the
  reference: the whole 184-tick gain over run 1 is the faster right side of lineage 579; the earliest level-8 and level-9 arrivals (974 and
  1,051) show that 68 to 84 more ticks were reached on the left side in states that did not clear.

## Claims not replayed

133 claimed clears were slower than or equal to the best verified clear at the moment of the decision and were not replayed (all 133 for that
reason; none was dropped by a later best while queued). They come from 121 distinct starts (at most three claims from one start), 121 of
them from lineage 579 and 12 from lineage 417; their claimed clocks run from 1,245 (one claim equal to the best, by the rule not replayed)
to 1,502, with 79 between 1,245 and 1,380. Their words are recorded (`run/claims_not_replayed.jsonl`): any of them can be replayed later. Run 1
replayed 298 clears for 968,250 ticks; run 2 replayed 3 for 7,716 ticks.

## Checks and quarantines

| check | count |
|---|---|
| eager at the open (477 level-9 cells + the earliest cell of levels 8, 7 and 6) | 480, all reproduced, 659,850 ticks, 501 s |
| lazy on first draw | 3,436, all reproduced |
| stale (the representative replaced by a faster arrival while its check ran) | 4 |
| quarantined by a check | 0 |
| checks whose replay could not run | 0 |
| prefix mismatches in the workers (every dispatch replays its prefix and checks the end record, chain and digest) | 0 |
| quarantines in all (limit 3) | 0 |
| tick-0 pin unequal / consumed-tick differences | 0 / 0 |

Every inherited cell that was ever dispatched had passed its check first (the zero-tick suite asserts this invariant on the synthetic run and
the dispatch rows carry the representative digest). 3,048 eligible cells (94 at level 8, 598 at level 7, 2,356 at level 6) were never drawn
and therefore never checked.

## Effects of the signals

| signal | bucket | jobs | broke a target (share) | new cells per job |
|---|---|---|---|---|
| break bonus | cells with a break record | 1,037 | 223 (21.5 %) | 0.10 |
| | without | 38,272 | 361 (0.94 %) | 0.12 |
| seen penalty | seen 0 to 2 | 7,857 | 169 (2.15 %) | 0.46 |
| | 3 to 5 | 4,381 | 70 (1.60 %) | 0.11 |
| | 6 to 15 | 8,672 | 152 (1.75 %) | 0.04 |
| | 16 and more | 18,399 | 193 (1.05 %) | 0.01 |
| novelty | fresh 0 | 25,032 | 375 (1.50 %) | 0.15 |
| | 1 to 3 | 12,400 | 176 (1.42 %) | 0.06 |
| | 4 to 15 | 1,808 | 33 (1.83 %) | 0.03 |

Reading: as in run 1 the break bonus is dominated by starts that cleared and cleared again, now held to 1,037 jobs by the cleared factor (run 1:
561 jobs for 298 clears, run 2: 136 clears from 121 starts); the seen penalty's gradient in new cells per job (0.46 to 0.01) repeats run 1's;
the level draw gave level 9 half the budget throughout.

## What limited progress

1. **The deepest lineage was a dead end the selection could not see.** 5,731 of the 7,382 level-9 cells descend from seed 579, in three
   groups by the target left: 2,611 cells with target 1 left (mask 2), 1,979 with target 8 left (mask 256) and 1,141 with target 6 left
   (mask 64). The mask-64 group holds the earliest level-9 arrivals of the run (1,051 to 1,072) and received 7,996 level-9 dispatches, the
   most of any group, for 0 clears; the mask-2 group received 7,619 for 78 claimed clears and the mask-256 group 4,813 for 46. Target 6 is
   the high left target; a state that broke targets 8 and 1 first is low on the left side with the high target still to reach. The pace
   and level terms read the arrival tick and the level, not which work remains; the break bonus is per cell and never accrued in a group
   that never broke. The earliest start of the clearing groups ahead of the best clear's pace (mask 2 at 1,078) was first dispatched at
   dispatch 34,830, and the mask-256 group's at 1,178 at dispatch 38,651, both in the last hour.
2. **Falls.** 24,285 of 39,309 bursts fell (62 %), 15,410 of the 20,984 at level 9 (73 %): the left-side cells are airborne over the drop,
   as in run 1.
3. **The left side was not improved.** The three clears' left sides took 606, 622 and 504 ticks from their level-7 arrival (the 1,352
   clear: 848 to 1,352); run 1's best took 581 and the reference 546. The gain came from the faster right side that run 1 had already kept
   (seed 579's descendants) and that run 1's level draw starved once level 9 existed.
4. **The checks cost the first hours.** 3,903,197 ticks (7.2 % of the run) and the equivalent of one to two workers for the first two
   hours went to re-deriving end records that run 1 had computed and not stored; run 2's own `cells.jsonl` does not store them either.

## What this means for November

1. **The lab result.** 1,245 input ticks (20.73 s) against run 1's 1,429 (23.80 s) and the registered 1,885 (31.40 s), verified twice from
   tick 0 in fresh processes with the verify flags; two further verified bests at 1,352 and 1,261 on the way. It is a lab result: nothing is
   registered, and registration (if the owner wants it) goes through the registered pipeline in a new session with its own rule, from the
   words recorded in `run/verifications.jsonl` (dispatch 36,236, words digest `1519833e…`).
2. **The resume works and the archive is sound.** 3,916 of 3,916 inherited prefixes reproduced run 1's records; the bound from the best
   verified clear, the cleared factor, the replay-only-when-faster rule and the new key family behaved as designed (3 replays instead of
   298, 0 duplicates verified, 0 repeated bursts). The first fix for a run 3 is to store the end record (the observation tuple) in the cells
   file, so that the next resume needs no check at all.
3. **The next run continues from this archive at the bound 1,245 − 24 − 1 = 1,220**, where 22,464 cells are eligible (level 9: 1,540;
   8: 4,388; 7: 7,867; 6: 8,669), with a budget split at the deepest level by the group of remaining work (the live mask is already part of
   the cell key, so a per-group share or a per-group break-rate term is generic and stage-agnostic) so that a group with thousands of
   dispatches and no break stops taking half the budget, and the 1,078 and 1,178 starts of the groups that do clear are dispatched in the
   first hour rather than the last.
4. **For the speed line and the video.** The right side at 639 and the crossing at 1,042 are both the archive's own work (the frontier
   search's random bursts, run 1's kept intermediate cells, run 2's faster arrivals replacing representatives), with no coordinate, target
   id, route or census number in any rule; the search is now 2.8 times slower than the TAS's 7.43 s, against 4.2 times at the start of the
   week.

## Compliance

- No native RNG seed was read, logged, compared or controlled. No TAS, human recording, owner run or external time was read or used.
- No cell id, coordinate, target id, direction, tick value, route or census number is in the search's rules: the archive is run 1's by cell
  id and key, the bound comes from run 1's verification rows through the registered rule, the selection reads level, dispatch count,
  arrival count, break record, slack and claimed-clear count; the stage names, target ids and masks above describe the records after the
  fact.
- The tick contract was checked on every tick of every check replay, every burst and every verification replay (`consumed_tick` = i,
  `input_tick` = `step_count` = i + 1): 0 differences; every prefix reproduced its stored end record, record digest and chain digest in the
  worker (0 mismatches); every checked prefix reproduced run 1's chain, record digest, key and level (3,916 of 3,916); the tick-0 record
  equalled the pin in every job (0 unequal).
- Process restart resets the episode: every check, every burst and every verification replay was a fresh process from tick 0.
- Writes only under `C:/BattleShip_lab/crossing_2026-10-15_run2/` through the lab's guard (0 violations in the main process and in every
  worker); `runs/` was never read; at most 10 game processes (the sampler's peak 10); readiness at the registered thresholds, never lowered:
  the first launch attempt was refused on free commit and nothing was changed, the owner closed idle sessions and the same command was
  relaunched; the lab lock held for the plan and both run attempts and released; the lab code untouched: digest `0b248a9e30304325` (34
  `rl/` files) at the plan, at the run's open and close and after the run; `rl/frs_*.py` and the existing `tools/frs/` files unchanged.
- New files only (the search, its tests, this record), LF; the search and its tests were committed by the owner before the launch
  (`f1a1ea1`); the session made no commit, push or branch. No application was closed by the session.

## Files

Lab folder `C:/BattleShip_lab/crossing_2026-10-15_run2/` (not in the repository, 277 MB):

| file | content |
|---|---|
| `plan.json` | the zero-tick plan: run 1's identity, the bound and its provenance, the archive per level, the cleared starts, the eager set, the fits |
| `refused_20261015T235040Z.json`, `run_console_attempt1_refused.txt` | the first attempt, refused by readiness |
| `run_console.txt`, `run_console_err.txt` | the run's console (the error stream is empty) |
| `run/config.json`, `run/reference.json`, `run/run1_best.json` | configuration with readiness values and the lab code digest; the reference and the run 1 best-clear replays at open |
| `run/checks.jsonl` | the 3,916 checks of inherited cells (kind, cell, level, tick, verdict, ticks, wall) |
| `run/cells.jsonl` | every cell kept or replaced by run 2 with its exact prefix (hex), key, origin and the dispatch counter (75,787 rows) |
| `run/dispatches.jsonl` | one row per dispatch (39,309) with the draw's shares, the burst words (hex), the levels reached and what was kept |
| `run/verifications.jsonl` | the 3 verifications: both replays' clocks, chain digests and break tables, the words (hex) and digest |
| `run/claims_not_replayed.jsonl` | the 133 claims not replayed, with their words (hex) |
| `run/traces/` | both replay traces of every verified clear, the reference's and run 1's best clear's (8 files) |
| `run/progress.md`, `run/report.md`, `run/summary.json` | the morning file (final), the report and the summary |
| `run/run_log.jsonl`, `run/memory.jsonl`, `run/state.json` | the log, the memory samples, the last state |

Repository: `tools/frs/crossing_search_run2.py`, `tools/frs/crossing_search_run2_tests.py` (committed, `f1a1ea1`), this record (new, untracked).
