# Trail-lead probe (2026-10-14)

## Status and result

Lab experiment, exploratory and unregistered, run on 2026-10-14 under the owner's authorisation (the trail-lead probe recommended by
`docs/frs_crossing_2026-10-14.md`, open question 3). HEAD = origin/main = `c8b782b`, clean before the run; the run changed no tracked
file. The question: can the search continue from the archive's faster arrivals on the best verified route's trail (the "leads"), and
does it get further from them than from the route's own states at the same cells (the paired "controls")?

**Answer.** Measured by levels gained, no: with the same random words, the leads advanced a level in 136 of 1,980 dispatches and the
controls in 252 of 1,980, and the controls were deeper in 27 pairs against 22 for the leads (149 equal). Two thirds of the controls'
advances (168 of 252) are the route's own next break happening on schedule whatever the input; with those removed the leads advanced
116 times and the controls 84. Measured by pace, yes, clearly: when a lead advanced it arrived at the next level 121 to 304 ticks ahead
of the route on average at levels 2 to 4 and 6, and the probe reached levels 3, 5, 7, 8 and 9 earlier than any state the archive
holds. The decisive events are at the crossing: two level-7 leads on the right side of the stage broke the first left target at
ticks 1,482 and 1,489, about 290 ticks before the route (1,776) and before every archive state, while the route's own states at those
two cells did not cross in 10 tries each. One pair reached level 9 at 1,816, 16 ticks ahead of the route. One clear was found, from a
level-9 lead, at 1,971 / 1,970: verified twice from tick 0 with identical digests, and 86 ticks slower than the reference 1,885.
Nothing here is a registered claim; no archive was changed; no lab code was modified (lab code digest `0b248a9e30304325` before and
after).

## The question and the design

- **Leads.** The splice probe's generic rule (`docs/frs_splice_probe_2026-10-14.md`): the reference clear of the lab import
  (sd2's cid 1360, 1,885 / 1,884) is located in the imported archive as its burst lineage (38 bursts), which gives the route's first
  reach tick j_r at each of its 310 trail cells. A trail cell whose representative arrived strictly earlier (L < j_r) is a lead; the
  lead start is the representative's stored prefix. 198 leads, as expected (per level 0: 4, 1: 4, 2: 31, 3: 33, 4: 39, 5: 4, 6: 53,
  7: 26, 8: 2, 9: 2).
- **Paired control.** The route's own state at its arrival at the same cell: the route's words up to j_r. Its start record (end
  state, record digest, chain digest) is recomputed from the stored reference trace and equals the route's own win record kept in the
  archive's bursts for every cell that has one (197 of 197 trail cells, 123 of the 198 leads).
- **Dispatches.** 10 per lead start and 10 per control start, through the lab's CONT arm unchanged (`rl/frs_worker.run_iterate_frs`:
  the m8_rd_explore_v1 keyed stream, 120-word segments, at most three continuations under the F3 trigger). The trigger was read on the
  imported archive, which the probe never mutates: no ingest, so later dispatches saw the same archive as the first. A lead and its
  control share one key family, `m8_rd_a1|trail|<cell>|<burst>:<offset>`, with iteration k, so dispatch k of both plays the same
  random words from its own start (common random numbers). Rounds alternate direction; every start got its 10.
- **Readings per dispatch** (`run/dispatches.jsonl`, 3,960 rows): start level and tick, words played, end reason, breaks after the
  start with their ticks, the deepest level, the pace at each new level (the route's arrival at that level minus the dispatch's;
  positive = ahead), the delta (pace minus the start's own lead), the archive readings of its reaches (new keys, reaches faster than the
  archive's incumbent at the key, reaches at trail keys ahead of the route), the continuation decisions, the burst words (hex).
- **Clears.** Every clear replayed twice from tick 0 in fresh processes with the verify flags after the workers stopped
  (`rl/frs_verify.verify_twice`); it counts only when both replays agree exactly with each other and with the in-run claim.
- **Tool.** `tools/frs/trail_probe.py` (new, LF, 1,034 lines; `plan` is zero-tick, `run` is native) with `tools/frs/trail_probe_tests.py`
  (478 lines; six zero-tick tests, all passing: the rule reproduces 198, the lead and control prefixes reproduce the archive's chain
  digests, the guard refusals, the clear verdict on stub traces, the readings, and a synthetic end-to-end run with real spawned workers).
  Neither `rl/frs_*.py` nor `tools/frs/splice_probe.py` was touched; the lab code digest covers only the 34 `rl/` modules.

## The run

| item | value |
|---|---|
| command | `python -B tools/frs/trail_probe.py run --lab-root C:/BattleShip_lab --out C:/BattleShip_lab/trail_probe_2026-10-14 --workers 5 --per-start 10 --max-ticks 4000000 --max-wall-min 75` |
| time | 2026-10-15 00:34:47 to 01:18:40 UTC (2026-10-14, 20:34 to 21:18 local); 2,634 s wall (open 10 s, dispatch 2,609 s, close 15 s) |
| readiness at open (registered thresholds) | available 8,828 MB (min 4,096), free commit 11,889 MB (min 10,240), free C: 104.7 GiB, D: 1,623.6 GiB (min 5); no BattleShip process; import pins equal |
| reference clear at open | replayed exactly in one fresh process: 1,885 / 1,884, chain `a48bc948…`, 2.0 s of stepping |
| dispatches | 3,960 (198 starts × 10 × 2 arms); 0 excluded pairs, 0 prefix mismatches, 0 lifecycle failures, 0 tick-0 differences |
| ticks | 3,575,474 in all: dispatch prefixes 3,021,410, bursts 548,237, reference 1,885, verification 3,942 (cap 4,000,000 not reached) |
| throughput | 5,464 jobs per hour, 4.93 M ticks per hour, 3.3 s per job per worker; 138 burst words per job (leads 146, controls 131) |
| continuation | 657 of 4,486 boundaries (14.6 %): leads 456 of 2,352 (19.4 %), controls 201 of 2,134 (9.4 %) |
| processes and memory | at most 10 BattleShip processes; main process 681 MB peak, tree 4,427 MB private peak; no budget breach |
| integrity | no guard or provenance violation, no code change during the run, no process left, every prefix reproduced its level |
| status | COMPLETED (every dispatch done), exit 0 |

## Lead against control, per start level

"Advanced" is a dispatch that broke at least one more target. The pace at the first new level is the route's arrival at that level
minus the dispatch's. A control that advances at pace exactly 0 reached the level at the route's own tick: the break was already
under way in the route's state and happened whatever the words ("momentum"); the lead's equivalent is a delta of exactly 0. "Kept"
counts the advancing dispatches whose delta is at least 0 (the lead's whole head start, or more, was still there at the next level).

| level | pairs | arm | advanced of jobs | momentum | pairs advanced | deepest | pace first: mean / best | delta first: mean / best | kept | falls |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 4 | lead | 17 / 40 | 0 | 4 | 2 | -45 / -2 | -49 / -3 | 0 | 0 |
| 0 | 4 | control | 17 / 40 | 2 | 4 | 2 | -26 / 15 | -29 / 13 | 4 | 0 |
| 1 | 4 | lead | 13 / 40 | 0 | 4 | 2 | -4 / 27 | -19 / 1 | 1 | 0 |
| 1 | 4 | control | 19 / 40 | 10 | 4 | 3 | -22 / 1 | -36 / -11 | 0 | 0 |
| 2 | 31 | lead | 43 / 310 | 0 | 21 | 4 | 121 / 260 | 52 / 138 | 33 | 0 |
| 2 | 31 | control | 33 / 310 | 0 | 20 | 3 | 46 / 137 | -23 / 136 | 15 | 0 |
| 3 | 33 | lead | 26 / 330 | 20 | 7 | 4 | 265 / 355 | -7 / 120 | 23 | 1 |
| 3 | 33 | control | 46 / 330 | 36 | 11 | 5 | 3 / 54 | -285 / -65 | 0 | 0 |
| 4 | 39 | lead | 8 / 390 | 0 | 7 | 5 | 304 / 467 | -47 / 103 | 4 | 5 |
| 4 | 39 | control | 80 / 390 | 80 | 10 | 5 | 0 / 0 | -410 / -368 | 0 | 3 |
| 5 | 4 | lead | 1 / 40 | 0 | 1 | 6 | 34 / 34 | 33 / 33 | 1 | 1 |
| 5 | 4 | control | 1 / 40 | 0 | 1 | 6 | -8 / -8 | -9 / -9 | 0 | 0 |
| 6 | 53 | lead | 2 / 530 | 0 | 2 | 7 | 214 / 242 | -1 / 8 | 1 | 43 |
| 6 | 53 | control | 32 / 530 | 30 | 4 | 7 | 0 / 0 | -43 / -40 | 0 | 19 |
| 7 | 26 | lead | 13 / 260 | 0 | 5 | 9 | 21 / 294 | -11 / 97 | 2 | 10 |
| 7 | 26 | control | 12 / 260 | 0 | 3 | 9 | -29 / 75 | -48 / 3 | 1 | 11 |
| 8 | 2 | lead | 12 / 20 | 0 | 2 | 9 | -6 / -1 | -7 / -2 | 0 | 5 |
| 8 | 2 | control | 12 / 20 | 10 | 2 | 9 | -1 / 0 | -2 / -1 | 0 | 5 |
| 9 | 2 | lead | 1 / 20 | 0 | 1 | 10 | -86 / -86 | -89 / -89 | 0 | 4 |
| 9 | 2 | control | 0 / 20 | 0 | 0 | 9 | - | - | 0 | 6 |
| all | 198 | lead | 136 / 1,980 | 20 | 54 | 10 | | | 65 | 69 |
| all | 198 | control | 252 / 1,980 | 168 | 59 | 9 | | | 20 | 44 |

Reading:

- **Levels gained.** Over the 198 pairs the lead was deeper in 22, the control in 27, both equal in 149 (lead advanced at least once
  in 54 pairs, control in 59). The controls' edge is entirely momentum at levels 3, 4, 6 and 8 (all 80 control advances at level 4 are
  at pace 0: the route's state there is mid-break, so every random continuation "advances"). Without momentum the leads advanced 116
  times and the controls 84; by level the leads are ahead at 0, 1, 2, 4, 7, 8 and 9 and behind at 3 and 6 (the level-6 leads are
  mostly fast-falling arrivals: 43 falls against 19).
- **Pace.** The leads' advances carried their head start: at levels 2 to 4 and 6 the first new level was reached 121, 265, 304 and 214
  ticks before the route on average (best 260, 355, 467, 242), and 65 of the 136 advancing lead dispatches kept the whole lead or
  gained on it (level 2: 33 of 43, mean delta +52). The controls' non-momentum advances were ahead of the route at level 2 (mean +46
  over 33) and level 3 (+12 over 10) and behind elsewhere (level 0: -29, level 1: -47, level 7: -29).
- **Exploration yield** (per-reach counts against the static import; the same key can count in several dispatches): the lead
  dispatches produced reaches faster than the archive's incumbent in 1,114 of 1,980 jobs (9,337 reaches) against 475 of 1,980
  (3,259) for the controls, and reaches at trail keys ahead of the route in 1,819 jobs (6,251) against 590 (1,279). The leads
  also continued more often (19.4 % of boundaries against 9.4 %), since their reaches are shorter than the incumbents more often.
- **Where "level" is a count.** A level is the number of targets broken; a dispatch that breaks a target the route breaks later
  reaches the next level with a different remaining mask. The pace readings compare arrival ticks per level, as the lab's per-level
  readings do.

## The leads that went furthest

One row per pair: the lead's best dispatch (deepest level, then best pace there), with the control's best beside it.

| pair | cell (x, y, class) | level | start L | route tick | lead | k | deepest | new levels (tick) | pace | end, words | control: deepest, best pace, advanced / 10 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 197 | 29171 (-14, -3, A2) | 9 | 1,859 | 1,862 | 3 | 6 | 10 | 10 (1,971) | -86 | clear, 112 | 9, -, 0 |
| 192 | 27335 (-9, 13, A2) | 7 | 1,744 | 1,745 | 1 | 5 | 9 | 8 (1,776), 9 (1,816) | 0, +16 | fall, 293 | 9, +16, 6 |
| 194 | 43190 (-12, 10, A2) | 8 | 1,788 | 1,789 | 1 | 1 | 9 | 9 (1,833) | -1 | out of words, 240 | 9, -2, 2 |
| 195 | 45108 (-12, 2, A2) | 8 | 1,830 | 1,831 | 1 | 0 | 9 | 9 (1,838) | -6 | fall, 179 | 9, 0, 10 |
| 193 | 27336 (-10, 13, A2) | 7 | 1,754 | 1,756 | 2 | 4 | 9 | 8 (1,775), 9 (1,842) | +1, -10 | out of words, 240 | 9, -10, 5 |
| 170 | 9684 (7, 11, A2) | 7 | 1,237 | 1,434 | 197 | 0 | 8 | 8 (1,482) | +294 | out of words, 480 | 7, -, 0 |
| 183 | 14008 (2, 14, A1) | 7 | 1,391 | 1,587 | 196 | 3 | 8 | 8 (1,489) | +287 | out of words, 240 | 7, -, 0 |
| 191 | 18767 (-6, 10, G, floor 0) | 7 | 1,683 | 1,694 | 11 | 4 | 8 | 8 (1,805) | -29 | out of words, 240 | 7, -, 0 |
| 155 | 2921 (9, -1, A2) | 6 | 1,025 | 1,259 | 234 | 1 | 7 | 7 (1,097) | +242 | out of words, 480 | 6, -, 0 |
| 147 | 2703 (6, -3, A2) | 6 | 1,013 | 1,207 | 194 | 4 | 7 | 7 (1,154) | +185 | out of words, 240 | 6, -, 0 |
| 113 | 2186 (2, 0, A1) | 5 | 933 | 934 | 1 | 2 | 6 | 6 (948) | +34 | out of words, 120 | 5, -, 0 |
| 105 | 2080 (5, -2, A1) | 4 | 360 | 816 | 456 | 0 | 5 | 5 (413) | +467 | out of words, 480 | 5, 0, 10 |
| 96 | 1550 (5, -5, A1) | 4 | 411 | 740 | 329 | 9 | 5 | 5 (484) | +396 | out of words, 240 | 4, -, 0 |
| 87 | 1087 (3, -8, A0) | 4 | 313 | 675 | 362 | 4 | 5 | 5 (491) | +389 | out of words, 480 | 4, -, 0 |
| 25 | 246 (0, -7, A2) | 2 | 244 | 251 | 7 | 0 | 4 | 3 (289), 4 (376) | +110, +233 | out of words, 240 | 3, +34, 2 |
| 38 | 422 (3, -9, G, floor 4) | 2 | 111 | 375 | 264 | 8 | 3 | 3 (139) | +260 | out of words, 120 | 3, -33, 1 |

Fastest arrival per level over every dispatch, against the route and against the archive's fastest arrival at that level (the archive's
shortest L over all its cells, read from the import):

| level | route | archive | probe lead (pair, k) | probe control (pair, k) | ahead of the archive |
|---|---|---|---|---|---|
| 1 | 43 | 26 | 45 (0, 3) | 28 (2, 2) | no |
| 2 | 120 | 91 | 93 (4, 2) | 96 (0, 4) | no |
| 3 | 399 | 152 | 139 (38, 8) | 262 (10, 5) | lead, 13 ticks |
| 4 | 609 | 254 | 254 (70, 0) | 555 (54, 1) | equal |
| 5 | 880 | 433 | 413 (105, 0) | 584 (59, 4) | lead, 20 ticks |
| 6 | 982 | 871 | 948 (113, 2) | 990 (112, 1) | no |
| 7 | 1,339 | 1,237 | 1,097 (155, 1) | 1,339 (165, 0) | lead, 140 ticks |
| 8 | 1,776 | 1,776 | 1,482 (170, 0) | 1,701 (184, 1) | lead 294, control 75 |
| 9 | 1,832 | 1,832 | 1,816 (192, 5) | 1,816 (192, 5) | both, 16 ticks |
| 10 | 1,885 | 1,885 | 1,971 (197, 6) | - | no |

None of these states is in the archive (no ingest); each is exact and reproducible: the start cell's stored prefix (or the route's
words up to j_r) followed by the burst words recorded in `dispatches.jsonl` (`words_hex`), which re-derive from the key family and k.

**The crossing (the 26 level-7 pairs).** Three pairs sit at or past the wall (191 at the wall-top key, x cell -6, grounded on floor 0;
192 and 193 at x cells -9 and -10) and 23 to its right. Crossings, with the tick of the first left target's break (the route: target 6
at 1,776):

- From the right side: leads 2 of 230 dispatches (pair 170, k 0: target 6 at 1,482 after 245 of 480 words, three continuations, no
  later break; pair 183, k 3: target 6 at 1,489 after 98 of 240 words); controls 1 of 230 (pair 184, the route's own state at 1,596 at
  cell (2, 15, A1): target 6 at 1,701, 75 ticks ahead of the route). Pair 170 is the level's shortest cell, the "1,237 lineage" of the
  crossing record (representative from sd1, never dispatched since its shortening); pair 183's representative is also sd1's. Their
  controls, the route's own states at 1,434 and 1,587, produced 19 bursts that ended at the first boundary without a continuation
  and one that continued twice and fell; none broke a target.
- The two platform leads the crossing record singled out (pairs 171 and 176, leads 115 and 125, cells (7, 10, A2) and (8, 8, G)):
  0 of 10 each, and 0 of 10 for their controls. The platform-phase concern of the record's section 7 stands for these two states.
- From the wall top (pair 191, lead 11): 1 of 10, target 8 at 1,805, 29 ticks behind the route's 1,776; control 0 of 10.
- Past the wall (pairs 192 and 193, 60 ticks from the targets): leads 10 of 20, controls 11 of 20, with the same words giving nearly
  the same break ticks; the one level-9 arrival ahead of the route came from here (pair 192, k 5: target 6 at 1,776 then target 8 at
  1,816, 16 ticks before the route's 1,832, from both the lead at 1,744 and the control at 1,745; both then fell at 2,037 without the
  last target).

So the record's offline question 7.1 has a native answer: a crossing is possible from a faster right-side state. Not from the two
platform leads in 20 tries, but from the 1,237 lineage (1 of 10) and from a high middle state with no double jump left (1 of 10), each
about 290 ticks before the route, and the random continuation did it; the route's own states at those cells gave 0 of 20.

## Clears

One candidate, verified. The words are the lead cell's stored prefix (1,859 words, the archive's own trajectory) followed by 112 words of
the keyed stream `m8_rd_a1|trail|29171|19397:5`, iteration 6. Replays: `run/traces/clear_p197_lead_k6_r1.json.gz` and `_r2`.

| item | replay 1 | replay 2 |
|---|---|---|
| completion_input_tick / completion_time_passed | 1,971 / 1,970 | 1,971 / 1,970 |
| final chain digest | `a9f54e04f23ba251644f76d3be7a3d2fd0c93562afb333627f95d7d8e344418e` | `a9f54e04f23ba251644f76d3be7a3d2fd0c93562afb333627f95d7d8e344418e` |
| native action digest of the 1,971 words | `2b47d5a2176413147fe76b027fea86598164d8c9a39e93f1da767be85780aa2d` | same |
| break table | equal to replay 2 (target 1 at 1,971) | equal to replay 1 |
| verdict | VERIFIED (both replays identical and equal to the in-run claim) | |

It is 86 ticks slower than the reference's 1,885: the lead's state at level 9 (cell 29171, three ticks ahead of the route's arrival
there) needed 112 random words for the last target where the route's own continuation needed 23. Not faster, not registered; it shows
the probe's native verification path end to end.

## What this means

**For night 2.** Nothing in the pre-registered design changes: PACE at share 1/2 against CONT remains the one-change mechanism test,
and night 2 cannot decide the crossing (the record's section 4.3). Two readings to add to night 2's analysis, both generic and
read-only: the number of level-7 dispatches from cells whose L is below the reference clear's arrival at the same key, and any level-8
reach ahead of the route's (the record's question 8, option a). The probe shows such events are producible at roughly 1 per 100
right-side lead dispatches with the plain explorer and continuation. PACE's per-level lead funds pair 170's cell (the level's shortest)
but not pair 183's (its lag at level 7 is 154 ticks, above the one-burst cap), which is the difference between a per-level and a
per-key lead.

**For a trail-lead pool arm (night 3, the record's question 4).** The probe supports option (a). The pool's membership rule is the
probe's own: eligible cells whose key is on the best verified clear's trail with L strictly below the clear's arrival there. What the
probe measured, which the pool would exploit:

- the leads' advances keep their head start (65 of 136 kept the whole lead; the fastest arrival at levels 3, 5, 7 and 8 came from a
  lead), so ingesting them would move the archive's frontier at several levels at once, not only at the crossing;
- the two right-side crossings came from leads of about 200 ticks whose representatives were sd1's and had never been dispatched since
  (`fresh` = 0), which is the state the proposed weight `lead × (1 + fresh)^-1/2` (question 10, option a) draws first; the two platform
  leads (115, 125) did not cross in 20 tries and would be drawn less as their `fresh` count grows;
- the controls' advantage in level counts is momentum, so the pool should not be judged by "advanced" shares against CONT but by the
  pace of its arrivals and by crossing events, as the record's milestone reading says.

What the probe does not say: whether a search continued from the 1,482 or 1,489 states reaches the remaining two left targets (both
dispatches ended out of words with no later break), and whether a pool share of 1/10 to 1/6 reproduces these events at the lab's
throughput (here 10 dispatches per lead was a census, not a draw). Both are night-3 questions.

**For the speed line.** Two of the probe's states are faster frontiers than anything in the archive at a point where the route is
slow: level 8 at 1,482 (294 ticks ahead) and level 9 at 1,816 (16 ticks ahead; reachable from the route's own words up to 1,745 plus
71 words of one keyed stream, since lead and control met there). A continuation probe from these recorded states, with the same zero-tick
plan and the same verification, is the cheapest next native experiment; it is proposed, not decided.

## Compliance

- No native RNG seed was read, logged, compared or controlled. No TAS, human recording, owner run or external time was read or used.
- No cell id, coordinate, target id, tick value or census number is in the probe's code; the start set is derived from the import by the
  generic rule, and the tests' only literal is the owner's expected count of 198.
- The tick contract was checked on every tick of every prefix and burst (`consumed_tick` = i, `input_tick` = `step_count` = i + 1);
  every prefix reproduced its stored end record and chain digest; the tick-0 record equalled the pin in every job.
- Process restart resets the episode: every dispatch and every verification replay was a fresh process from tick 0 (the lab's
  standby workers, one episode each).
- Writes only under `C:/BattleShip_lab/trail_probe_2026-10-14/`, through the lab's guard (`rl/frs_guard`); `runs/` was never read;
  at most 10 game processes; readiness at the registered thresholds, never lowered; the lab lock held for the plan and the run;
  the night's code untouched: lab code digest `0b248a9e30304325` (34 `rl/` files) before the probe was written, in the run's
  `config.json`, and after the run.
- New files only (the probe, its tests, this record), LF, uncommitted; nothing staged; no commit, push or branch.

## Files

Lab folder `C:/BattleShip_lab/trail_probe_2026-10-14/` (not in the repository):

| file | content |
|---|---|
| `plan.json`, `starts.jsonl` | the zero-tick plan: the 198 starts with their lengths, digests and checks (win check, gain-0 split) |
| `run_console.txt` | the run's console |
| `run/config.json`, `run/reference.json` | configuration with readiness values, the reference replay at open |
| `run/dispatches.jsonl` | one row per dispatch (3,960), with the burst words in hex |
| `run/verifications.jsonl`, `run/traces/` | the clear's two replays and the reference replay |
| `run/summary.json`, `run/report.md`, `run/run_log.jsonl`, `run/memory.jsonl` | the run's summary, report, log and memory samples |
| `analysis/readings.py`, `analysis/readings.json` | the zero-tick readings behind this record (per level, per pair, the crossing, fastest arrivals) |

Repository (new, untracked): `tools/frs/trail_probe.py`, `tools/frs/trail_probe_tests.py`, this record.
