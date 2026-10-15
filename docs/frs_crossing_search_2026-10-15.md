# Crossing search (2026-10-15)

## Status and result

Lab experiment, exploratory and unregistered, run on 2026-10-15 from 09:52 to 16:47 local (13:52:41 to 20:47:45 UTC) under the owner's
authorisation ("I would like to run the 7 h tests", given before leaving). HEAD = origin/main = `a73ac95`, the tree clean apart from the two
new tool files; the run changed no tracked file. The question: from the fast right-side states the frontier search found
(`docs/frs_frontier_2026-10-14.md`), can a cell-based search get across to the left side and finish a clear faster than the agent's best
verified 1,885 input ticks?

**Answer: yes, repeatedly.** In 420 minutes and 30,699 dispatches the search crossed for the first time at dispatch 659 (nine minutes in),
reached level 8 as early as tick 1,096 (the reference arrives there at 1,776) and level 9 at 1,300 (reference 1,832), and claimed 298 clears,
every one of them replayed twice from tick 0 in fresh processes with the verify flags and VERIFIED (both replays identical with each other
and with the in-run claim), every one faster than 1,885. The best is **1,429 input ticks / 1,428 time passed** (23.80 s against the
reference's 31.40 s, a gain of 456 ticks), reached four times, by different words from two cells of the same lineage. Every clear and every
level-9 cell of the run descends from one of the 48 seeds (the frontier state 417, a level-7 state at tick 848); a second crossing lineage,
from a level-6 seed, reached level 8 at 1,096 in the sixth hour and had no time to finish. Nothing here is a registered claim; `runs/` was
never read; no lab code was modified (lab code digest `0b248a9e30304325` at the plan, at the run's open and at its close).

## The design as run

- **Seeds (crossing_seed_v1, generic).** The frontier search's states (every member of its 212 frontier files, each with its exact prefix,
  cell key and record digests) at the deepest level the frontier's own bursts reached ahead of the reference's pace, read from its dispatch
  rows (a level arrival with a positive pace): level 7 (25 such arrivals; no burst ever arrived at level 8), and the level below it; one
  state per cell key (the earliest arrival); ordered by (level, lead); the top 48. That gave all 21 level-7 keys (ticks 493 to 1,297, leads
  846 to 42) and the 27 fastest level-6 keys (461 to 610, leads 521 to 372). Every seed's prefix was re-derived at zero ticks from the
  frontier's rows (the parent's prefix plus the keyed burst to the arrival, 213 links in all, down to the probe starts 2, 4 and 127, whose
  words equal the frontier planner's own starts on the import), then replayed at the run's open from tick 0 in a fresh process with the
  verify flags: the chain digest, the record digest and the cell key at its last tick had to equal the frontier's record, every tick under
  the tick contract. 48 of 48 reproduced (32,188 ticks, 38 s, five replays at a time before any worker was started); the replay's last
  observation is the seed's end record (the frontier files store none).
- **Archive.** Every reach of a burst (the first visit of a key inside the job) was kept with its exact prefix when its key was new (a new
  cell) or its tick strictly below the cell's representative (a faster arrival replaces the representative, which becomes a fresh start:
  its dispatch counter and iteration restart, the replaced representative is recorded); a later arrival at a known key counted as a visit
  (`seen`); a reach past the E7 bound (1,860 = 1,885 minus the registered margin 24 minus one, `m8_sd1_select.record_bound_max_L`) was
  never kept; the burst's own start key and terminal reaches were skipped. `cells.jsonl` holds every kept cell and every replacement with
  its words.
- **Selection.** Every idle worker drew one start: first a level with weight 0.5^(deepest eligible level − level), then a cell within the
  level with weight (1 + fresh)^-1 × (1 + seen)^-1 × (1 + breaks)^1 × slack^0.5 (fresh = dispatches since the representative was set,
  seen = later arrivals at the key, breaks = dispatches of the cell that broke a target, slack = bound − tick + 1). The seen penalty and
  the break bonus were on (switches); retirement off (the novelty term is a soft retirement). The draws came from a Python experiment
  seed (1); no native RNG was touched.
- **Bursts.** The lab's CONT explorer (the `m8_rd_explore_v1` keyed stream, key family `<archive id>|crossing|<prefix digest>`, iteration =
  the representative's dispatch count, 120-word segments, F3 window 20) with at most six segments (720 words; the lab arm's four) and the
  F3 trigger read on this run's own archive.
- **Clears.** Every claimed clear was replayed from tick 0 twice in fresh processes with the verify flags on a lent worker as soon as one was
  idle (`rl/frs_verify.verify_twice`); it counted only when both replays agreed exactly with each other and with the in-run claim. None was
  pending at the stop.
- **Caps.** 420 minutes of wall (the dispatch deadline minus the close reserve), 80,000,000 ticks, 600,000 cells, five workers with one
  standby each (at most ten game processes), the lab's memory sampler (soft budget = registered caps minus headroom), readiness at the
  registered thresholds.
- **Tool.** `tools/frs/crossing_search.py` (new, LF, 1,807 lines; `plan` zero-tick, `run` native; sha256 `6e4a6472…` at the run and now)
  with `tools/frs/crossing_search_tests.py` (734 lines; seven zero-tick tests, all passing: the seed rule on the real frontier outputs, the
  seed prefixes re-derived from the frontier's rows and the import, the archive's keep / replace / E7 / quarantine logic, selection on stub
  archives, the guard refusals, the verification verdicts, a stub end-to-end with chains of kept cells, verified clears and clean tick, wall
  and cells cap stops). Neither `rl/frs_*.py` nor any existing `tools/frs/` file was touched.

## The run

| item | value |
|---|---|
| command | `python -B tools/frs/crossing_search.py run --lab-root C:/BattleShip_lab --frontier C:/BattleShip_lab/frontier_2026-10-14 --out C:/BattleShip_lab/crossing_2026-10-15 --workers 5 --seeds 48 --seed-order level --level-decay 0.5 --novelty-exp 1 --seen-exp 1 --bonus-exp 1 --pace-exp 0.5 --max-segments 6 --retire-after 0 --max-cells 600000 --rng-seed 1 --max-ticks 80000000 --max-wall-min 420` (launched detached with its console at `run_console.txt`) |
| time | 2026-10-15 13:52:41 to 20:47:45 UTC (09:52 to 16:47 local); 24,904 s wall (open 48 s of which the seeds 38 s, search 24,852 s, drain 2 s, close 2 s) |
| readiness at open (registered thresholds) | available 9,101 MB (min 4,096), free commit 10,996 MB (min 10,240), free C: 103.6 GiB, D: 1,621.1 GiB (min 5); no BattleShip process; import pins equal; lab code digest equal to the frontier's |
| reference clear at open | replayed exactly in one fresh process: 1,885 / 1,884, chain `a48bc948…`, 1.66 s of stepping |
| dispatches | 30,699, all returned (0 prefix mismatches, 0 lifecycle failures, 0 aborted, 0 tick-0 differences, 0 quarantines) |
| ticks | 48,390,344 in all: bursts' prefixes 44,557,614, bursts 2,830,407, seeds 32,188, reference 1,885, verification 968,250 (cap 80,000,000 not reached) |
| throughput | 4,447 jobs per hour, 6.86 M ticks per hour, 1,544 ticks per job, 92 burst words per job; continuation 2,925 of 14,617 boundaries (20.0 %); burst lengths: 28,153 jobs within 120 words, 2,256 to 240, 229 to 360, 38 to 480, 18 to 600, 5 to 720 |
| outcomes | 18,707 falls (61 %), 11,694 out of words, 298 clears; 539 bursts broke a target |
| cells | 32,744 (level 6: 7,142; 7: 7,521; 8: 11,421; 9: 6,660); 73,126 replacements by faster arrivals; 451,681 later arrivals; 26,048 own-key reaches skipped; 17,036 reaches beyond the E7 bound dropped; 19,005 terminal; words 39.1 MB |
| processes and memory | 10 BattleShip processes at most; main process 454 MB after the seeds, 555 MB peak; tree 4,402 MB private peak; no budget breach; 5.1 MB per 1,000 new cells, 24 MB per hour, 89 h to the soft budget |
| status | WALL_CAP, exit 0 |

## The deepest progress over time

The earliest arrival per level over the run ("found at" = the dispatch counter when the cell was kept; the burst that found it was dispatched
a few jobs earlier). The reference arrives at levels 6 to 9 at 982, 1,339, 1,776 and 1,832.

| level | first arrival | improvements (tick at counter) | earliest at the stop | lead |
|---|---|---|---|---|
| 8 | 1,159 at 670 (14:01 UTC, nine minutes in) | 1,127 at 23,194; 1,096 at 26,317 (19:48 UTC) | **1,096** | 680 |
| 9 | 1,417 at 1,547 (14:11 UTC) | 1,373 at 1,684; 1,362 at 2,576; 1,355 at 7,666; 1,350 at 10,732; 1,300 at 16,126 (17:26 UTC) | **1,300** | 532 |
| 7 | 493 (seed) | none | 493 | 846 |
| 6 | 461 (seed) | none | 461 | 521 |

The best verified clear over the run (dispatch counter, UTC): 1,762 at 1,552 (14:12, twenty minutes in), 1,650 at 2,368, 1,522 at 3,367
(14:35), 1,492 at 11,520 (16:24), 1,487 at 14,982, 1,438 at 23,066 (19:03), **1,429 at 28,613 (20:19)**. Per hour of dispatches (4,400
each): bursts that broke a target 58, 52, 60, 72, 105, 108, 84; clears 7, 18, 32, 37, 76, 78, 50; new cells 15,506 in the first hour, then
4,624, 4,785, 3,319, 1,981, 1,228, 1,253; falls 2,400 to 2,900 every hour.

## How the left side was reached

Stage names below describe the records; nothing in the search read them.

- **The first crossing (dispatch 659).** From the level-7 cell 618 (tick 984, a child of seed 417 found by its very first dispatch; key
  x cell 4, y cell 14, class A2: high up, right of the centre, with the double jump and up-B available), a 480-word burst broke target 6
  at tick 1,159 (617 ticks ahead of the reference's level-8 arrival) and kept 53 new cells. The 82 bursts from level-7 starts that broke a
  target over the run broke target 6 forty times, target 8 twenty-eight times and target 1 nineteen times (the three left targets; every
  level-7 cell of the run carries the same live mask 322). The first level-8 cell's key places Mario low near the stage centre at the break
  tick; bursts leave no trace, so the mechanism of that first break was not examined. The level-8 cells arrive with masks 258 (target 6
  broken first, 7,545 cells), 66 (target 8 first, 2,506) and 320 (target 1 first, 1,370).
- **The lineage that cleared.** Every level-9 representative (29,150 rows) and all 298 clears descend from seed 417 (frontier state 417:
  level 7 at tick 848, lead 491, key (9, 6, A2), the route's seven right-side targets done by 848). The best clear's chain of kept cells,
  from the seed to the clear (level, tick, key x and y cells and class): 7, 848, (9, 6, A2) → 7, 1,001, (3, 12, A2) → 7, 1,054, (−1, 13, A1)
  → 7, 1,072, (−1, 11, A1) → 7, 1,073, (−1, 11, A0) → 7, 1,080, (−2, 13, A0) → 7, 1,129, (−5, 10, A0) → 7, 1,250, (−10, 14, A2) →
  8, 1,334, (−12, 5, A2) → 9, 1,382, (−13, −1, A2) → 9, 1,390, (−13, −3, A2) → clear at 1,429 with 39 words. Ten kept intermediate
  states; the level-7 links were kept by dispatches 40, 47, 87, 255, 410, 855 and 1,483 (the first forty minutes), the level-8 and level-9
  links at 1,547, 19,273 and 20,636. The clear itself needed only one more burst from the last cell (its second dispatch).
- **The best clear's trace** (`run/traces/clear_n28613_c13926_k1_r1.json.gz`, replay 1; replay 2 identical): the right side is finished at
  848 (target 2, on the moving platform, like the record but 491 ticks earlier); a double jump and an up-B carry Mario over the top from
  x 974, y 3,933 at tick 1,000 to x −1,359, y 4,887 at 1,100; he lands on the wall top (floor line 0) at tick 1,133 at x −1,427, walks
  left on it to x −2,100 by 1,180, leaves it airborne at about 1,224 (the first tick left of x −2,100), breaks target 6 at 1,288 with an
  aerial attack at (−3,153, 3,385), falls along the left side and breaks target 8 at 1,356 at (−3,435, 789) and target 1 at 1,429 at
  (−3,838, −3,337). The crossing and the three left targets took 581 ticks from the level-7 arrival (the record's took 546 from 1,339),
  so the whole gain over 1,885 is the right side; the earliest level-8 (1,096) and level-9 (1,300) arrivals show that 170 to 240 more
  ticks were available on the left side in lineages that did not clear before the wall cap.
- **The second lineage.** The earliest level-8 arrival of the run (1,096, 680 ahead) descends from the level-6 seed 579 (tick 461) through
  eight kept cells (level 6 at 514 and 602, level 7 at 734, 852, 862, 974 and 1,032, then level 8 at 1,096, key (−11, 2, A2), found at
  counter 26,317 in the sixth hour); it holds 463 level-8 representatives and never reached level 9. The other 46 seeds produced the
  7,142 level-6 and most of the 7,521 level-7 cells and never crossed.

## Verified clears

298 candidates, 298 VERIFIED (0 NONDETERMINISTIC, 0 ERROR, 0 unverified): 291 distinct word sequences, 136 distinct final chain digests,
89 distinct clocks from 1,429 to 1,883, all faster than the reference. Every row is in `run/verifications.jsonl` with both replays' clocks,
chains and break tables and the words; both traces of every clear are in `run/traces/`.

| rank | completion_input_tick / completion_time_passed | found (dispatch, cell, k; start tick) | replay 1 chain | replay 2 chain | words digest | gain |
|---|---|---|---|---|---|---|
| 1 | 1,429 / 1,428 | 28,613, cell 13926, k 1; 1,390 (20:19:45 UTC) | `ab6341ef4cc4c3ad3e8864720f8f8286e413c6e59952a0a3df1d63b6248b2c76` | identical | `e452242981a94ffe…` | 456 |
| 1 | 1,429 / 1,428 | 28,640, cell 8694, k 0; 1,426 | `1e461f093bcc6c8837f77440dded9bfc2baabb7b1d5646a4fc666b61ffa6e72a` | identical | `be6c37c20469e196…` | 456 |
| 1 | 1,429 / 1,428 | 28,879, cell 8694, k 1; 1,426 | `1e461f093bcc6c88…` | identical | `26823871ab0e6098…` | 456 |
| 1 | 1,429 / 1,428 | 30,300, cell 8694, k 2; 1,426 | `ab6341ef4cc4c3ad…` | identical | `c11562b3f1babae0…` | 456 |
| 5 | 1,438 / 1,437 | 23,066, cell 30409, k 2; 1,392 | `72e4e5ba01ff4c6c…` | identical | | 447 |
| 6 | 1,441 / 1,440 | 27,832, cell 8696, k 0; 1,439 | `8f21907af70afa55…` | identical | | 444 |
| 7 | 1,459 / 1,458 | 25,371, 28,491, 28,583, 28,938 (cells 9231, 10862) | three chains | identical | | 426 |

Clock histogram (count): 1,429 ×4, 1,438, 1,441, 1,459 ×4, 1,465, 1,487, 1,492 ×21, then 1,509 to 1,883. Cell 8694 (tick 1,426) clears
three ticks after its arrival with three different words, so the three distinct words share two final chains. Starts that cleared were
drawn again (the break bonus and the novelty term): cell 29404 at 1,610 cleared twenty times with the same clock, cell 25017 seventeen
times, cell 26923 thirty-three times from two representatives; 298 verifications cost 968,250 ticks and about 15 s each.

## Effects of the signals

| signal | bucket | jobs | broke a target (share) | new cells per job |
|---|---|---|---|---|
| break bonus (on) | cells with a break record | 561 | 255 (45.5 %) | 0.71 |
| | without | 30,138 | 284 (0.94 %) | 1.07 |
| seen penalty (on) | seen 0 to 2 | 14,350 | 346 (2.41 %) | 2.07 |
| | 3 to 5 | 4,727 | 70 (1.48 %) | 0.41 |
| | 6 to 15 | 6,535 | 99 (1.51 %) | 0.14 |
| | 16 and more | 5,087 | 24 (0.47 %) | 0.02 |
| novelty | fresh 0 | 23,779 | 276 (1.16 %) | 1.23 |
| | 1 to 3 | 6,567 | 159 (2.42 %) | 0.53 |
| | 4 to 15 | 344 | 96 (27.9 %) | 0.05 |
| | 16 and more | 9 | 8 | 0.0 |

Reading: at level 9 a break is a clear, so the bonus table is dominated by the cells that cleared once and cleared again (selection, as the
crossing study's section 3.2 warned); the seen penalty's buckets confirm the study's reading on this archive (progress and new cells fall
by a factor five to a hundred from seen 0 to 2 to seen 16 and more), and the penalty moved 47 % of the draws to the freshest bucket; the
level draw gave level 9 half the budget from the moment it existed (15,588 of 30,699 jobs), level 8 a quarter, levels 7 and 6 the rest.
Continuation fired at 20 % of boundaries (the trigger reads the growing archive; the frontier's 40 % read the import), and 61 % of all
bursts fell, 66 % at level 9: the left-side cells are airborne over the drop, and random words from them fall within a segment.

## What limited progress

1. **Falls.** 18,707 of 30,699 bursts ended in a fall; the mean burst lasted 92 words. From the left-side cells most random continuations
   drop off the stage, so each kept cell yields few words of exploration per dispatch.
2. **One lineage.** All level-9 cells and all clears descend from one seed; the crossing happened once from the right side and was then
   exploited. 46 of 48 seeds never crossed in 6,779 dispatches from levels 6 and 7, and the second crossing lineage appeared only in the
   sixth hour. The crossing rate from a fast right-side state is low per seed and needs the chain of kept intermediate cells to be built
   for that seed; the level draw gave the right-side levels only a quarter of the budget once level 9 existed.
3. **The left side was not optimised.** The best clear's crossing and left targets took 581 ticks against the record's 546; the earliest
   level-8 and level-9 arrivals (1,096 and 1,300) belong to lineages that did not clear. A run that continues from this archive's deep cells
   with the E7 bound set at the run's best verified clear (1,429 minus the margin) would discard the 17,036 reaches kept only because they
   beat 1,860 and concentrate on the faster lineages.
4. **Cleared starts were re-drawn.** The break bonus counts a clear as a break, so a start that cleared is drawn more, and identical or
   near-identical clears were claimed and verified again and again (20 verifications of one 1,611 clear). A start that cleared adds nothing
   when its clock is within a few ticks of its own tick; stopping such starts and deduplicating claims by words digest would have freed
   about 3 % of the ticks and the lent worker.

## What this means for November

1. **The lab result.** 1,429 input ticks (23.80 s) against the registered 1,885 (31.40 s), a 456-tick gain, verified twice from tick 0 in
   fresh processes with the verify flags, reached four times from two cells of one lineage; 298 verified clears faster than the reference in
   seven hours. It is a lab result: nothing is registered, and registration (if the owner wants it) goes through the registered pipeline in
   a new session with its own rule, from the words recorded in `run/verifications.jsonl` (dispatch 28,613, words digest `e4522429…`).
2. **The crossing is a selection problem, and the cell archive solves it.** With kept intermediate cells and novelty-driven draws the
   search crossed in nine minutes from a seed whose descendants the frontier search would have retired after sixteen bursts; the chain
   behind the best clear is ten kept cells, seven of them found in the first forty minutes. The frontier record's "16 random bursts per
   state do not open the crossing" stands; "the archive's own mechanism, a chain of short prefixes through intermediate cells" is the
   answer it proposed, and it worked at the first try.
3. **The next run continues from the archive, not from seeds.** `cells.jsonl` holds every kept cell with its exact prefix (32,744 cells,
   375 MB); the faster level-8 and level-9 arrivals (1,096, 1,300) and the second lineage's cells are the states to search from, with the
   bound tightened to the run's best, cleared starts stopped, claims deduplicated, and a share of the budget reserved for the right-side
   levels so that other seeds can cross. The same tool can take a crossing run's `cells.jsonl` as its seed source with a small reader.
4. **For the speed line and the video.** The right side at 848 came from the frontier search's random bursts and the crossing from this
   search's archive; both are generic (no coordinate, target id, route or census number in any rule) and both are far from the TAS's 7.43 s.
   The 1,429 route's trace shows the crossing over the top of the stage with a walk along the wall top: the same mechanism as the record's,
   491 ticks earlier.

## Compliance

- No native RNG seed was read, logged, compared or controlled. No TAS, human recording, owner run or external time was read or used.
- No cell id, coordinate, target id, direction, tick value, route or census number is in the search's rules: the seeds come from the
  frontier's own rows by the generic rule, the archive keeps by cell key and tick, the selection reads level, dispatch count, arrival count,
  break record and slack to the registered E7 bound; the stage names and target ids above describe the records after the fact.
- The tick contract was checked on every tick of every seed replay, every burst and every verification replay (`consumed_tick` = i,
  `input_tick` = `step_count` = i + 1): 0 differences; every prefix reproduced its stored end record, record digest and chain digest
  (0 mismatches); the tick-0 record equalled the pin in every job (0 unequal).
- Process restart resets the episode: every seed replay, every burst and every verification replay was a fresh process from tick 0 (the
  lab's standby workers, one episode each; the verify replays in their own processes).
- Writes only under `C:/BattleShip_lab/crossing_2026-10-15/` through the lab's guard (`rl/frs_guard`, 0 violations in the main process and
  in every worker); `runs/` was never read; at most 10 game processes (the sampler's peak 10); readiness at the registered thresholds, never
  lowered; the lab lock held for the plan and the run and released; the lab code untouched: digest `0b248a9e30304325` (34 `rl/` files) at
  the plan, at the run's open and at its close; `rl/frs_*.py` and the existing `tools/frs/` files unchanged.
- New files only (the search, its tests, this record), LF, uncommitted; nothing staged; no commit, push or branch. No application was closed.
  One runaway process of the zero-tick test suite (a test process that had armed the lab guard in itself and spun) was terminated before
  the launch; no game process was involved.

## Files

Lab folder `C:/BattleShip_lab/crossing_2026-10-15/` (not in the repository, 507 MB):

| file | content |
|---|---|
| `plan.json`, `seeds.jsonl` | the zero-tick plan: the seed rule's readings, the 48 seeds with their keys, digests and lineages, the parameters, the throughput fit |
| `run_console.txt`, `run_console_err.txt` | the run's console (the error stream is empty) |
| `run/config.json`, `run/reference.json` | configuration with readiness values and the lab code digest; the reference replay at open |
| `run/seeds.jsonl` | the 48 native seed checks (chain, record digest, key, level; all ok) |
| `run/cells.jsonl` | every kept cell and every replacement with its exact prefix (hex), key, origin (parent cell, iteration, offset) and the dispatch counter (105,870 rows) |
| `run/dispatches.jsonl` | one row per dispatch (30,699) with the draw's shares, the burst words (hex), the levels reached and what was kept |
| `run/verifications.jsonl` | the 298 verifications: both replays' clocks, chain digests and break tables, the words (hex) and digest |
| `run/traces/` | both replay traces of every verified clear (596 files) and the reference's |
| `run/progress.md`, `run/report.md`, `run/summary.json` | the morning file (final), the report and the summary |
| `run/run_log.jsonl`, `run/memory.jsonl`, `run/state.json` | the log, the memory samples (819 rows), the last state |

Repository (new, untracked): `tools/frs/crossing_search.py`, `tools/frs/crossing_search_tests.py`, this record.
