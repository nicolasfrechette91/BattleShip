# Splice probe (2026-10-14)

## Status and result

Lab experiment, exploratory and unregistered, run on 2026-10-14 under the owner's authorisation as finding M6 of
`docs/rl_m8_fast_route_proposal_review_2026-10-14.md` (HEAD = origin/main = `0126363`). The question: does the agent's own
archive already contain a faster clear, made by joining an earlier arrival at a cell of the best verified route (sd2, cid 1360,
1,885 input ticks) with that route's own continuation from the same cell?

**Answer: yes, by one tick, and only by one tick.** Of 198 candidates, 9 clear. Each completes at
`completion_input_tick` 1,884 / `completion_time_passed` 1,883 (31.38 s against 31.40 s). Each was replayed twice from tick 0,
in two fresh processes with the verify flags, and both replays gave identical chain digests and clocks. All 9 are gain-1
splices. Every one of the 180 candidates with a gain of 2 to 487 ticks failed. That includes the review's nine "cleanest"
candidates (gains 11 to 209): none reached the clear, and eight of them missed the next target after the splice. These are lab
results: nothing here is a registered claim, and no record, approval or pinned file was changed.

## The rule

The rule is generic. The script contains no cell id, position, target id or tick literal.

1. The route is the verified clear in `runs/m8_rd_sd2/routes/T_clear_best` (its `actions.jsonl` words reproduce the registered
   native action digest `05a17835…`). Its burst chain in the archive (`runs/m8_rd_sd2/archive`, files checked against the
   archive manifest) is found by matching the route's words: 38 bursts, 310 distinct cells, each with the route's first reach
   tick `j_r`.
2. For each such cell, the archive representative (the arrival the archive keeps, with stored words, at tick `L`) is a
   candidate if `L < j_r`. The gain is `j_r − L`.
3. Candidate words = the representative's stored words `[0, L)` followed by the route's words `[j_r, 1,885)`. The length is
   1,885 − gain.

This gives 198 candidates, 143 with a gain of at least 30. Both numbers equal the review's F5 figures. 22 candidates pass the
review's motion test ("similar": each velocity within 10, same facing, jumps used and status), and 14 of those have a gain of
at least 30 (review: 14). No candidate's state equals the route's state at the splice point. The position inside the 300-unit
cell differs by 12 to 295 units.

## How each candidate was run and judged

- **Tool:** `tools/frs/splice_probe.py` (new, LF).
  - `plan` uses zero ticks and writes the candidates.
  - `run` performs the replays.
- **Replay setup:** each replay is a fresh BattleShip process from tick 0, through `rl/m7f_trace.run_stepping_trace`
  (unchanged).
  - Flags: `rl/m9_contract.FLAGS_VERIFY` (no render, Raphnet off, spatial, entity, target diagnostic, input). These are the
    same flags as sd2's verification replays and the stored route trace.
  - Executable `30a3913b…`, with the runtime files and frozen configuration pinned in `runs/m8_rd/archive/runtime`, installed
    into each private runtime as the M8 sessions do.
- **Stop after a fall:** the probe stops submitting words after a native-failure reply (a fall), because the game hangs on
  the steps after a fall.
- **Control first:** the unspliced route was replayed first, alone, with a stop rule: the run would end unless the control
  reproduced 1,885 / 1,884, the registered action digest, the break table and the chain digest recomputed from the stored
  route trace.
- **Prefix check:** at the splice point, the replay's 17-field end state and m8_rd chain digest are compared with the
  archive's stored record for the representative.
- **Divergence:**
  - Splice tick `k` is compared with route tick `k + gain`.
  - The exact divergence is the first tick whose observation differs, ignoring the three clock fields.
  - The cell divergence is the first tick after the splice point whose (x cell, y cell, ground/air, live-target mask) differs.
- **Breaks:** the route's breaks after `j_r` are compared with the splice's breaks after `L`: how many were kept, how many
  were kept exactly `gain` ticks earlier, and the first one missed.
- **Clear test:** the four-fact clear test of `rl/m8_rd_claims.clear_facts` (end reason, outcome, ten targets, both completion
  clocks).
- **Faster clear:** a clear counts as faster only if `completion_input_tick` < 1,885 and a second fresh-process replay gives
  the identical final chain digest, clocks, break table and action digest.
- **Chain digest:** the m8_rd chain (`chain_start` over the tick-0 observe record, `chain_next` over every step record) after
  the last tick.

## Run

- **First attempt (14:14:23 UTC):** refused at preflight. Free commit was 9,820 MB, below the 10,240 MB threshold of
  `rl/m8_rd_session.readiness`. Nothing was launched. The record is kept as `preflight_refused_20261014T141423Z.json`. The
  script's refusal path was then changed to write its record beside `run/` rather than inside it, so that the same command
  could run again. The candidate rule and the replay code were not changed.
- **Second attempt (14:28:06 UTC), after the owner closed two applications:**
  - Preflight: no BattleShip process running; available memory 9,583 MB; free commit 12,985 MB; free disk C: 101.7 GiB,
    D: 1,623.6 GiB; all pins equal.
  - Control: clear, exact, 1,885 / 1,884, final chain `a48bc9484d4f36858ffce47f5ec2b145b5f4dae4b2b1d41c1d9a1a400ef1f14b`.
  - 198 candidates replayed, latest splice point first, at most 5 processes at once. None was skipped by a cap.
  - 208 processes in all (control, 198 candidates, 9 second replays). 337,338 native ticks (cap 1,000,000). Wall time
    357.1 s (cap 59 min).
  - 0 errors, 0 retries, no BattleShip process left afterwards.
- **Prefixes:** all 198 prefixes replayed exactly. At the splice point, the end state and the chain digest equal the archive's
  stored record in 198 of 198 cases.
- **Outcomes:** 9 clear, 57 fall (at route-equivalent ticks 966 to 1,712), and 132 ran out of words without clearing.

## Verified clears faster than 1,885

All nine clears are faster than 1,885. Both replays agree exactly on the chain digest, the clocks
(`completion_input_tick` / `completion_time_passed`), the break table (…, target 6 at 1,775, target 8 at 1,831, target 1 at
1,884) and the action digest. The words digest is the native action digest of the candidate's words (first 16 hex digits;
full value in `candidates.jsonl`).

| # | cell | level | route tick | earlier arrival | replay 1 clocks | replay 2 clocks | replay 1 chain digest | replay 2 chain digest | words digest |
|---|---|---|---|---|---|---|---|---|---|
| 73 | 2290 | 6 | 1,046 | 1,045 | 1,884 / 1,883 | 1,884 / 1,883 | `c4a1a54d9abef747f7500ee7c6da0615414d08cecc7104ee68d3c4ae0c672924` | `c4a1a54d9abef747f7500ee7c6da0615414d08cecc7104ee68d3c4ae0c672924` | `158f030f2c4ae8f0` |
| 74 | 2289 | 6 | 1,041 | 1,040 | 1,884 / 1,883 | 1,884 / 1,883 | `01d9d0d015503c6fe12e74a58463c219fefe1f0c91baeec25a6c6eac6251a586` | `01d9d0d015503c6fe12e74a58463c219fefe1f0c91baeec25a6c6eac6251a586` | `7375e5d2f59fc789` |
| 75 | 2288 | 6 | 1,037 | 1,036 | 1,884 / 1,883 | 1,884 / 1,883 | `5ab61a403b0e1b162c2f3e4bbf40465f74ec4fa2fcae02bb6cf38d46e4714c97` | `5ab61a403b0e1b162c2f3e4bbf40465f74ec4fa2fcae02bb6cf38d46e4714c97` | `eb72a73069c3d935` |
| 76 | 2287 | 6 | 1,033 | 1,032 | 1,884 / 1,883 | 1,884 / 1,883 | `9517d0fbb38e2fedc222f8d29f8ff4e6f773084a70e99fc0c2dac2ac3e80470b` | `9517d0fbb38e2fedc222f8d29f8ff4e6f773084a70e99fc0c2dac2ac3e80470b` | `57b7fd8321b684c4` |
| 77 | 2285 | 6 | 1,024 | 1,023 | 1,884 / 1,883 | 1,884 / 1,883 | `ddc11c06d8e0067831a465b425555ee3766cfc56450387b6e9faa87852c92752` | `ddc11c06d8e0067831a465b425555ee3766cfc56450387b6e9faa87852c92752` | `b0426053c909ed4f` |
| 78 | 2284 | 6 | 1,020 | 1,019 | 1,884 / 1,883 | 1,884 / 1,883 | `cce9ba016fc75fb494c447be78fe7e2189cebbf599f8fa2c4550787b7f5b6bde` | `cce9ba016fc75fb494c447be78fe7e2189cebbf599f8fa2c4550787b7f5b6bde` | `f2f22086244918dd` |
| 79 | 2283 | 6 | 1,016 | 1,015 | 1,884 / 1,883 | 1,884 / 1,883 | `534af0530505317944eebf518b11c572752df4b2846f39112cf5478b15217f07` | `534af0530505317944eebf518b11c572752df4b2846f39112cf5478b15217f07` | `4c2529760628ee64` |
| 186 | 149 | 2 | 159 | 158 | 1,884 / 1,883 | 1,884 / 1,883 | `b042838e1af5799bf48cf0f634d0ba3169d8e8175cceb3ffacaa7dc528f6cfc3` | `b042838e1af5799bf48cf0f634d0ba3169d8e8175cceb3ffacaa7dc528f6cfc3` | `272c44106e14de56` |
| 187 | 148 | 2 | 154 | 153 | 1,884 / 1,883 | 1,884 / 1,883 | `b67ba0f491298c8f74da1124fd4eefbddd744ac6c235c4f5b2639a1c44601774` | `b67ba0f491298c8f74da1124fd4eefbddd744ac6c235c4f5b2639a1c44601774` | `284cec8a21d83dc0` |

These nine are two independent one-tick savings, not nine:

- **Level 6 (seven clears):** seven consecutive cells on the route's descent at route ticks 1,016 to 1,046. All are in the
  up-B/helpless resource class (A0). The cells were created in rd1, and their representatives come from rd1 and rd2 bursts.
  The splice at the next cell on the same descent (cell 2291, route tick 1,050, also gain 1) did not clear: it missed the last
  target.
- **Level 2 (two clears):** two consecutive cells at route ticks 154 and 159, also class A0, created in rd1.

Every clear keeps every later route break, each exactly one tick early. The exact state differs from the first tick of the
splice, and the cell sequence differs from the route's within 3 to 9 ticks, yet every target is reached on the shifted
schedule.

Provenance to disclose if any of these is ever registered: the words are the agent's own throughout. They are an older archive
trajectory up to the splice point, then the sd2 route's words. No TAS, human recording or owner run was read.

## Results by gain and level

| gain | candidates | clear | fall | out of words | kept ≥ 1 later break | kept every later break |
|---|---|---|---|---|---|---|
| 1 | 18 | 9 | 1 | 8 | 14 | 9 |
| 2 to 9 | 20 | 0 | 4 | 16 | 12 | 0 |
| 10 to 29 | 17 | 0 | 5 | 12 | 13 | 0 |
| 30 to 99 | 26 | 0 | 5 | 21 | 12 | 0 |
| 100 to 487 | 117 | 0 | 42 | 75 | 43 | 0 |

| level | candidates | clear | fall | out of words |
|---|---|---|---|---|
| 0 | 4 | 0 | 0 | 4 |
| 1 | 4 | 0 | 2 | 2 |
| 2 | 31 | 2 | 10 | 19 |
| 3 | 33 | 0 | 8 | 25 |
| 4 | 39 | 0 | 25 | 14 |
| 5 | 4 | 0 | 2 | 2 |
| 6 | 53 | 7 | 9 | 37 |
| 7 | 26 | 0 | 1 | 25 |
| 8 | 2 | 0 | 0 | 2 |
| 9 | 2 | 0 | 0 | 2 |

The review's motion test does not predict survival. The 22 "similar" candidates gave 3 clears (all gain 1), 10 falls and 9
out of words. The 12 "similar" level-4 candidates in up-B/helpless status (review N5) all failed.

**S9's criterion** is a strictly faster verified clear, or survival past the first moving-object interaction after the splice
point.

- 168 splices start before the moving target's break (target 2, the only animated target, broken at route tick 1,339). 55 of
  them broke it after the splice. 31 kept every route break up to and including it (gains 1 to 265).
- None of those 31 with a gain above 1 also kept the next break after the moving platform (target 6 at 1,776). Only the gain-1
  splices did.
- So the probe passes S9 on the first clause (nine one-tick-faster verified clears). On the second clause, nothing larger than
  one tick survives the moving platform.

## The review's nine cleanest candidates

These nine have no moving object between them and the clear: eight airborne level-7 cells in the flight to the wall top, and
the wall-top landing.

| # | cell | route tick | gain | result | targets | later breaks kept | cell divergence (route tick) | first missed |
|---|---|---|---|---|---|---|---|---|
| 13 | 14007 | 1,596 | 209 | out of words at 1,676 | 8 | 1 of 3 (target 6) | 1,597 | target 8 (route 1,832) |
| 14 | 14008 | 1,587 | 196 | out of words at 1,689 | 7 | 0 of 3 | 1,593 | target 6 (route 1,776) |
| 15 | 15110 | 1,581 | 183 | out of words at 1,702 | 7 | 0 of 3 | 1,584 | target 6 |
| 7 | 16729 | 1,625 | 168 | out of words at 1,717 | 7 | 0 of 3 | 1,629 | target 6 |
| 19 | 9685 | 1,530 | 129 | out of words at 1,756 | 7 | 0 of 3 | 1,532 | target 6 |
| 16 | 11132 | 1,577 | 94 | out of words at 1,791 | 7 | 0 of 3 | 1,581 | target 6 |
| 17 | 11133 | 1,576 | 90 | out of words at 1,795 | 7 | 0 of 3 | 1,577 | target 6 |
| 18 | 16711 | 1,574 | 48 | out of words at 1,837 | 7 | 0 of 3 | 1,576 | target 6 |
| 6 | 18767 | 1,694 | 11 | out of words at 1,874 | 9 | 2 of 3 (targets 6, 8) | 1,723 | target 1 (route 1,885) |

None fell and none cleared. The wall-top landing came closest: it broke targets 6 and 8 and ended with nine targets, 11 words
before the route's clear tick.

## What failed and where, in plain language

The route's words are a fixed tape: they do not look at where Mario is. A splice hands that tape a Mario who is in the same
300-unit cell, but 12 to 295 units away from where the tape expects, often with a different speed, status or animation frame.
Within a few ticks he is in a different cell from the route (median 1.5 to 4.5 ticks after the splice point, by level; at
most 43). The tape then makes him jump, attack or up-B at the wrong place.

The first target after the splice point is where most splices fail:

| first missed target (route tick) | splices |
|---|---|
| 9 (399) | 14 |
| 5 (609) | 42 |
| 3 (880) | 39 |
| 7 (982) | 4 |
| 2, the moving target (1,339) | 38 |
| 6 (1,776) | 40 |
| 8 (1,832) | 5 |
| 1, the last target (1,885) | 7 |

57 of the 189 failures fell off the stage. The other 132 kept moving but missed a target and ran out of words.

The only offsets the tape tolerated were one-tick-early arrivals during two up-B/helpless descents. There, the player's inputs
barely change the motion, so the state stays close enough for every later target to break one tick early. Every splice with a gain of 2 to 9
failed (20 of 20), and so did every larger one.

## What this means for the November design

- **Splice-only R5 is a one-tick operator.** The proposal's R5 (splice-and-repair) cannot be justified by the hope of large
  free gains: 0 of 180 splices with a gain of at least 2 cleared, including all nine post-platform candidates. Its measured
  yield on this archive is one tick (two independent one-tick savings, nine clears). The review asked for the yield to be
  stated from the number of survivors, not the best one: 9 of 198 survive, all at gain 1.
- **What R5 would be worth.** It does propagate a faster arrival, which nothing else in the archive does (review S5). But only
  a one-tick-faster arrival propagates, and only in up-B/helpless stretches. If R5 is kept, its value is cheap
  tick-by-tick polishing at low priority. A "splice then normal burst" job is essentially a search from the splice point; the
  probe says nothing about that repair part.
- **Larger gains need state-aware matching.** The cell key (300-unit bins, resource class, mask, floor) is far too coarse for
  two arrivals to be interchangeable under a fixed tape. Cell divergence within a median of 2 to 4 ticks supports M6's
  alternative: R8 (motion-aware cells), or any operator that re-plans after the splice instead of copying words, has to carry
  the gains above one tick.
- **The ahead fronts are the only source of large gains.** The 487-tick level-4 and 209-tick level-7 gains in the archive are
  not reachable by copying the route's tape. Only a search that finishes from those states can use them, which is what the
  pace-frontier pools (R1 to R4) are for.
- **Registration:** if wanted, the 1,884 clears can be registered by the usual exact-replay path. Their words, digests and
  provenance are in the lab folder. The probe registers nothing.

## Ideas for November (not tried in this session)

1. **Iterated splice:** re-apply the same rule with a 1,884 clear as the route. The new route's cells come from its saved trace
   at zero ticks; the classifier is needed for the resource class. Whether the level-2 and level-6 one-tick savings compound is
   unknown. Both come from different archive lineages, and the level-6 representatives arrive one tick before the 1,885 route,
   so they may only tie a route that is already one tick ahead.
2. **Splice then repair, only where the tape survived longest:** for example the wall-top landing (cell 18767, gain 11), which
   kept targets 6 and 8 and missed only the last one. A short search from its state after target 8 could test whether a
   repair burst recovers a faster clear. The candidate must come from a generic rule (such as the most later breaks kept),
   not from this list.
3. **Time-shifted donor words:** splice with the route's words taken from `j_r + s` for small `s` (both signs). This is a generic
   family that tests whether the tape's timing, not its position, is what breaks.
4. **Motion-aware splice selection:** score candidates by the full end-state distance (sub-cell position, velocities, status
   and timers) rather than the five-field "similar" test. The 198 rows here, with their outcomes, are a ready offline test set
   for any such score.

## Compliance

| constraint | how it was kept |
| --- | --- |
| only the agent's own trajectories | the archive's own bursts and the sd2 route; no TAS, human recording, owner run or external time was read |
| no RNG inspection, logging, control, comparison or hashing | nothing touched RNG |
| generic candidate rule | the script has no cell id, position, target id or tick literal; the cell ids in this record are outputs |
| process restart resets the episode; submit/consume/input tick contract; canonical words | every replay is a fresh process from tick 0 through `run_stepping_trace`; consumed tick `i` and input tick `i + 1` were checked on every step; words are Track 1 canonical triples |
| clears verified twice | each of the 9 clears was replayed in a second fresh process with identical chain digest and clocks |
| caps | 337,338 ticks of 1,000,000; 357 s of 59 min; at most 5 game processes at once |
| writes | the script wrote only under `C:/BattleShip_lab/splice_probe_2026-10-14/`; the game itself rewrites its own log `%APPDATA%\BattleShip\ssb64.log` on every launch; nothing under `runs/` or on D: was written |
| repository | new files only: `tools/frs/splice_probe.py` and this record (both LF); no tracked file modified; nothing staged, committed or pushed |

## Files (lab folder `C:/BattleShip_lab/splice_probe_2026-10-14/`, not in the repository)

| file | content |
| --- | --- |
| `plan.json`, `candidates.jsonl` | the rule's output: 198 candidates with words (hex), digests, gains, motion comparison; candidate-set digest `41c966a4…` |
| `preflight_refused_20261014T141423Z.json`, `run_stdout_refused_20261014T141423Z.txt` | the refused first attempt |
| `run_stdout.txt`, `run/preflight.json`, `run/summary.json`, `run/results.jsonl` | the run: one row per replay (control, 198 first replays, 9 second replays) |
| `run/traces/*.json.gz` | all 208 raw stepping traces |
| `candidate_table.md` | the table below |

## Candidate table

Columns:

- **#**: run order (latest splice point first).
- **state**: the cell's resource class.
- **earlier**: the representative's arrival tick.
- **similar**: the review's motion test.
- **dpos**: the position offset in units.
- **result**: clear, fall (with its tick in splice time), or words_exhausted.
- **kept / after**: the route's later breaks kept.
- **on time**: kept exactly `gain` ticks earlier.
- **bin div**: the route tick at which the splice first left the route's cell sequence.
- **first missed**: target @ route tick.
- **clock**: completion_input_tick / completion_time_passed.

| # | cid | level | state | route tick | earlier | gain | similar | dpos | result | ticks | targets | kept / after | on time | bin div (route tick) | first missed (target @ route tick) | clock |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 29171 | 9 | A2 | 1862 | 1859 | 3 | y | 210 | words_exhausted | 1882 | 9 | 0/1 | 0 | 1863 | 1 @ 1885 |  |
| 1 | 46804 | 9 | A2 | 1851 | 1850 | 1 | y | 70 | words_exhausted | 1884 | 9 | 0/1 | 0 | 1854 | 1 @ 1885 |  |
| 2 | 45108 | 8 | A2 | 1831 | 1830 | 1 | n | 59 | words_exhausted | 1884 | 9 | 1/2 | 0 | 1832 | 1 @ 1885 |  |
| 3 | 43190 | 8 | A2 | 1789 | 1788 | 1 | y | 44 | words_exhausted | 1884 | 8 | 0/2 | 0 | 1791 | 8 @ 1832 |  |
| 4 | 27336 | 7 | A2 | 1756 | 1754 | 2 | y | 25 | words_exhausted | 1883 | 9 | 2/3 | 1 | 1759 | 1 @ 1885 |  |
| 5 | 27335 | 7 | A2 | 1745 | 1744 | 1 | y | 12 | words_exhausted | 1884 | 9 | 2/3 | 1 | 1755 | 1 @ 1885 |  |
| 6 | 18767 | 7 | G | 1694 | 1683 | 11 | n | 222 | words_exhausted | 1874 | 9 | 2/3 | 2 | 1723 | 1 @ 1885 |  |
| 7 | 16729 | 7 | A0 | 1625 | 1457 | 168 | n | 177 | words_exhausted | 1717 | 7 | 0/3 | 0 | 1629 | 6 @ 1776 |  |
| 8 | 16728 | 7 | A1 | 1624 | 1621 | 3 | n | 106 | words_exhausted | 1882 | 7 | 0/3 | 0 | 1628 | 6 @ 1776 |  |
| 9 | 15391 | 7 | A1 | 1617 | 1612 | 5 | n | 275 | words_exhausted | 1880 | 8 | 1/3 | 1 | 1618 | 8 @ 1832 |  |
| 10 | 16727 | 7 | A1 | 1616 | 1608 | 8 | n | 285 | words_exhausted | 1877 | 7 | 0/3 | 0 | 1617 | 6 @ 1776 |  |
| 11 | 16726 | 7 | A1 | 1607 | 1592 | 15 | n | 163 | words_exhausted | 1870 | 8 | 1/3 | 0 | 1609 | 8 @ 1832 |  |
| 12 | 14006 | 7 | A1 | 1597 | 1583 | 14 | n | 46 | words_exhausted | 1871 | 8 | 1/3 | 0 | 1605 | 8 @ 1832 |  |
| 13 | 14007 | 7 | A1 | 1596 | 1387 | 209 | n | 273 | words_exhausted | 1676 | 8 | 1/3 | 0 | 1597 | 8 @ 1832 |  |
| 14 | 14008 | 7 | A1 | 1587 | 1391 | 196 | n | 262 | words_exhausted | 1689 | 7 | 0/3 | 0 | 1593 | 6 @ 1776 |  |
| 15 | 15110 | 7 | A1 | 1581 | 1398 | 183 | n | 260 | words_exhausted | 1702 | 7 | 0/3 | 0 | 1584 | 6 @ 1776 |  |
| 16 | 11132 | 7 | A1 | 1577 | 1483 | 94 | n | 95 | words_exhausted | 1791 | 7 | 0/3 | 0 | 1581 | 6 @ 1776 |  |
| 17 | 11133 | 7 | A1 | 1576 | 1486 | 90 | n | 109 | words_exhausted | 1795 | 7 | 0/3 | 0 | 1577 | 6 @ 1776 |  |
| 18 | 16711 | 7 | A2 | 1574 | 1526 | 48 | n | 238 | words_exhausted | 1837 | 7 | 0/3 | 0 | 1576 | 6 @ 1776 |  |
| 19 | 9685 | 7 | A2 | 1530 | 1401 | 129 | n | 143 | words_exhausted | 1756 | 7 | 0/3 | 0 | 1532 | 6 @ 1776 |  |
| 20 | 11141 | 7 | G | 1514 | 1348 | 166 | y | 284 | words_exhausted | 1719 | 7 | 0/3 | 0 | 1520 | 6 @ 1776 |  |
| 21 | 11315 | 7 | G | 1498 | 1373 | 125 | n | 247 | words_exhausted | 1760 | 7 | 0/3 | 0 | 1506 | 6 @ 1776 |  |
| 22 | 11314 | 7 | G | 1474 | 1411 | 63 | n | 295 | words_exhausted | 1822 | 7 | 0/3 | 0 | 1478 | 6 @ 1776 |  |
| 23 | 10645 | 7 | G | 1473 | 1401 | 72 | n | 227 | words_exhausted | 1813 | 7 | 0/3 | 0 | 1474 | 6 @ 1776 |  |
| 24 | 10644 | 7 | A2 | 1472 | 1432 | 40 | n | 264 | words_exhausted | 1845 | 7 | 0/3 | 0 | 1473 | 6 @ 1776 |  |
| 25 | 10406 | 7 | A2 | 1451 | 1338 | 113 | y | 78 | fall 1583 | 1583 | 7 | 0/3 | 0 | 1473 | 6 @ 1776 |  |
| 26 | 10405 | 7 | A2 | 1444 | 1329 | 115 | n | 21 | words_exhausted | 1770 | 7 | 0/3 | 0 | 1445 | 6 @ 1776 |  |
| 27 | 9684 | 7 | A2 | 1434 | 1237 | 197 | n | 18 | words_exhausted | 1688 | 7 | 0/3 | 0 | 1442 | 6 @ 1776 |  |
| 28 | 9681 | 7 | A2 | 1412 | 1410 | 2 | n | 90 | words_exhausted | 1883 | 7 | 0/3 | 0 | 1417 | 6 @ 1776 |  |
| 29 | 8937 | 7 | G | 1369 | 1368 | 1 | n | 24 | words_exhausted | 1884 | 7 | 0/3 | 0 | 1381 | 6 @ 1776 |  |
| 30 | 6456 | 6 | A0 | 1336 | 1296 | 40 | n | 107 | words_exhausted | 1845 | 7 | 1/4 | 0 | 1338 | 6 @ 1776 |  |
| 31 | 5759 | 6 | A0 | 1334 | 1292 | 42 | n | 137 | words_exhausted | 1843 | 7 | 1/4 | 0 | 1336 | 6 @ 1776 |  |
| 32 | 5758 | 6 | A0 | 1332 | 1291 | 41 | n | 154 | words_exhausted | 1844 | 7 | 1/4 | 0 | 1333 | 6 @ 1776 |  |
| 33 | 3227 | 6 | A0 | 1324 | 1261 | 63 | n | 74 | words_exhausted | 1822 | 6 | 0/4 | 0 | 1325 | 2 @ 1339 |  |
| 34 | 6695 | 6 | A1 | 1292 | 1026 | 266 | n | 182 | fall 1227 | 1227 | 6 | 0/4 | 0 | 1293 | 2 @ 1339 |  |
| 35 | 5328 | 6 | A1 | 1285 | 1019 | 266 | n | 95 | fall 1345 | 1345 | 6 | 0/4 | 0 | 1293 | 2 @ 1339 |  |
| 36 | 4442 | 6 | A1 | 1281 | 1016 | 265 | n | 278 | words_exhausted | 1620 | 7 | 1/4 | 0 | 1284 | 6 @ 1776 |  |
| 37 | 4443 | 6 | A1 | 1280 | 1057 | 223 | n | 288 | words_exhausted | 1662 | 6 | 0/4 | 0 | 1281 | 2 @ 1339 |  |
| 38 | 4444 | 6 | A1 | 1276 | 1003 | 273 | n | 117 | fall 1344 | 1344 | 6 | 0/4 | 0 | 1278 | 2 @ 1339 |  |
| 39 | 5256 | 6 | A2 | 1275 | 993 | 282 | n | 215 | fall 1212 | 1212 | 6 | 0/4 | 0 | 1280 | 2 @ 1339 |  |
| 40 | 5532 | 6 | A2 | 1269 | 1015 | 254 | n | 105 | words_exhausted | 1631 | 6 | 0/4 | 0 | 1272 | 2 @ 1339 |  |
| 41 | 5326 | 6 | A2 | 1264 | 1018 | 246 | n | 210 | words_exhausted | 1639 | 6 | 0/4 | 0 | 1269 | 2 @ 1339 |  |
| 42 | 2921 | 6 | A2 | 1259 | 1025 | 234 | n | 252 | words_exhausted | 1651 | 6 | 0/4 | 0 | 1264 | 2 @ 1339 |  |
| 43 | 2863 | 6 | G | 1248 | 1031 | 217 | n | 19 | words_exhausted | 1668 | 6 | 0/4 | 0 | 1258 | 2 @ 1339 |  |
| 44 | 2920 | 6 | A2 | 1247 | 1031 | 216 | n | 205 | words_exhausted | 1669 | 7 | 1/4 | 0 | 1248 | 6 @ 1776 |  |
| 45 | 4709 | 6 | A2 | 1244 | 964 | 280 | n | 107 | words_exhausted | 1605 | 6 | 0/4 | 0 | 1245 | 2 @ 1339 |  |
| 46 | 4708 | 6 | A2 | 1234 | 965 | 269 | n | 151 | words_exhausted | 1616 | 6 | 0/4 | 0 | 1239 | 2 @ 1339 |  |
| 47 | 2706 | 6 | A2 | 1221 | 902 | 319 | n | 63 | fall 1393 | 1393 | 6 | 0/4 | 0 | 1225 | 2 @ 1339 |  |
| 48 | 2705 | 6 | A2 | 1218 | 901 | 317 | n | 17 | fall 1350 | 1350 | 6 | 0/4 | 0 | 1219 | 2 @ 1339 |  |
| 49 | 2704 | 6 | A2 | 1213 | 1014 | 199 | n | 149 | words_exhausted | 1686 | 7 | 1/4 | 0 | 1218 | 6 @ 1776 |  |
| 50 | 2703 | 6 | A2 | 1207 | 1013 | 194 | n | 266 | words_exhausted | 1691 | 7 | 1/4 | 0 | 1208 | 6 @ 1776 |  |
| 51 | 2634 | 6 | A2 | 1202 | 1032 | 170 | n | 145 | words_exhausted | 1715 | 7 | 1/4 | 0 | 1207 | 6 @ 1776 |  |
| 52 | 2633 | 6 | A2 | 1199 | 1039 | 160 | n | 191 | words_exhausted | 1725 | 6 | 0/4 | 0 | 1202 | 2 @ 1339 |  |
| 53 | 2635 | 6 | G | 1192 | 1043 | 149 | n | 116 | words_exhausted | 1736 | 6 | 0/4 | 0 | 1199 | 2 @ 1339 |  |
| 54 | 2677 | 6 | A1 | 1185 | 1070 | 115 | n | 11 | words_exhausted | 1770 | 7 | 1/4 | 0 | 1199 | 6 @ 1776 |  |
| 55 | 2676 | 6 | A1 | 1174 | 1063 | 111 | n | 111 | words_exhausted | 1774 | 6 | 0/4 | 0 | 1181 | 2 @ 1339 |  |
| 56 | 2675 | 6 | A1 | 1164 | 931 | 233 | n | 29 | words_exhausted | 1652 | 6 | 0/4 | 0 | 1170 | 2 @ 1339 |  |
| 57 | 2674 | 6 | A1 | 1157 | 930 | 227 | n | 235 | words_exhausted | 1658 | 6 | 0/4 | 0 | 1158 | 2 @ 1339 |  |
| 58 | 2673 | 6 | A1 | 1152 | 1023 | 129 | n | 270 | words_exhausted | 1756 | 6 | 0/4 | 0 | 1156 | 2 @ 1339 |  |
| 59 | 2672 | 6 | A1 | 1150 | 1080 | 70 | n | 130 | words_exhausted | 1815 | 6 | 0/4 | 0 | 1152 | 2 @ 1339 |  |
| 60 | 2671 | 6 | A1 | 1144 | 1074 | 70 | n | 40 | words_exhausted | 1815 | 6 | 0/4 | 0 | 1152 | 2 @ 1339 |  |
| 61 | 2670 | 6 | A1 | 1141 | 1070 | 71 | n | 122 | words_exhausted | 1814 | 6 | 0/4 | 0 | 1144 | 2 @ 1339 |  |
| 62 | 2381 | 6 | A2 | 1140 | 1028 | 112 | n | 113 | words_exhausted | 1773 | 6 | 0/4 | 0 | 1143 | 2 @ 1339 |  |
| 63 | 2382 | 6 | A2 | 1138 | 1032 | 106 | n | 101 | fall 1439 | 1439 | 7 | 1/4 | 0 | 1140 | 6 @ 1776 |  |
| 64 | 2383 | 6 | A2 | 1135 | 1069 | 66 | n | 290 | words_exhausted | 1819 | 6 | 0/4 | 0 | 1138 | 2 @ 1339 |  |
| 65 | 2384 | 6 | A2 | 1134 | 1074 | 60 | n | 133 | words_exhausted | 1825 | 6 | 0/4 | 0 | 1138 | 2 @ 1339 |  |
| 66 | 2364 | 6 | G | 1108 | 1076 | 32 | n | 147 | fall 1513 | 1513 | 7 | 1/4 | 0 | 1123 | 6 @ 1776 |  |
| 67 | 2355 | 6 | G | 1102 | 1069 | 33 | n | 149 | fall 1512 | 1512 | 7 | 1/4 | 0 | 1108 | 6 @ 1776 |  |
| 68 | 2354 | 6 | G | 1097 | 967 | 130 | n | 32 | words_exhausted | 1755 | 6 | 0/4 | 0 | 1099 | 2 @ 1339 |  |
| 69 | 2343 | 6 | G | 1095 | 954 | 141 | n | 5 | words_exhausted | 1744 | 6 | 0/4 | 0 | 1097 | 2 @ 1339 |  |
| 70 | 2295 | 6 | G | 1061 | 1054 | 7 | n | 44 | words_exhausted | 1878 | 7 | 1/4 | 0 | 1065 | 6 @ 1776 |  |
| 71 | 2292 | 6 | A0 | 1051 | 1049 | 2 | n | 119 | words_exhausted | 1883 | 7 | 1/4 | 0 | 1054 | 6 @ 1776 |  |
| 72 | 2291 | 6 | A0 | 1050 | 1049 | 1 | n | 203 | words_exhausted | 1884 | 9 | 3/4 | 2 | 1051 | 1 @ 1885 |  |
| 73 | 2290 | 6 | A0 | 1046 | 1045 | 1 | n | 96 | clear | 1884 | 10 | 4/4 | 4 | 1051 | none | 1884/1883 |
| 74 | 2289 | 6 | A0 | 1041 | 1040 | 1 | y | 16 | clear | 1884 | 10 | 4/4 | 4 | 1049 | none | 1884/1883 |
| 75 | 2288 | 6 | A0 | 1037 | 1036 | 1 | n | 64 | clear | 1884 | 10 | 4/4 | 4 | 1041 | none | 1884/1883 |
| 76 | 2287 | 6 | A0 | 1033 | 1032 | 1 | n | 36 | clear | 1884 | 10 | 4/4 | 4 | 1041 | none | 1884/1883 |
| 77 | 2285 | 6 | A0 | 1024 | 1023 | 1 | y | 16 | clear | 1884 | 10 | 4/4 | 4 | 1028 | none | 1884/1883 |
| 78 | 2284 | 6 | A0 | 1020 | 1019 | 1 | n | 92 | clear | 1884 | 10 | 4/4 | 4 | 1023 | none | 1884/1883 |
| 79 | 2283 | 6 | A0 | 1016 | 1015 | 1 | n | 36 | clear | 1884 | 10 | 4/4 | 4 | 1024 | none | 1884/1883 |
| 80 | 2281 | 6 | A0 | 1003 | 994 | 9 | n | 157 | words_exhausted | 1876 | 6 | 0/4 | 0 | 1010 | 2 @ 1339 |  |
| 81 | 2279 | 6 | A0 | 989 | 986 | 3 | n | 68 | words_exhausted | 1882 | 6 | 0/4 | 0 | 992 | 2 @ 1339 |  |
| 82 | 2278 | 6 | A0 | 982 | 980 | 2 | n | 137 | words_exhausted | 1883 | 6 | 0/4 | 0 | 988 | 2 @ 1339 |  |
| 83 | 2188 | 5 | A1 | 968 | 957 | 11 | n | 81 | words_exhausted | 1874 | 5 | 0/5 | 0 | 971 | 7 @ 982 |  |
| 84 | 2186 | 5 | A1 | 934 | 933 | 1 | n | 38 | words_exhausted | 1884 | 9 | 4/5 | 4 | 940 | 7 @ 982 |  |
| 85 | 2169 | 5 | A1 | 921 | 920 | 1 | n | 179 | fall 1489 | 1489 | 5 | 0/5 | 0 | 922 | 7 @ 982 |  |
| 86 | 2168 | 5 | A1 | 920 | 915 | 5 | n | 287 | fall 1485 | 1485 | 5 | 0/5 | 0 | 921 | 7 @ 982 |  |
| 87 | 1400 | 4 | G | 841 | 354 | 487 | n | 102 | fall 1028 | 1028 | 4 | 0/6 | 0 | 878 | 3 @ 880 |  |
| 88 | 1531 | 4 | A1 | 834 | 423 | 411 | n | 171 | fall 1104 | 1104 | 4 | 0/6 | 0 | 840 | 3 @ 880 |  |
| 89 | 1532 | 4 | A1 | 827 | 459 | 368 | n | 114 | fall 1178 | 1178 | 6 | 2/6 | 0 | 832 | 3 @ 880 |  |
| 90 | 2078 | 4 | A1 | 826 | 455 | 371 | n | 238 | fall 1175 | 1175 | 6 | 2/6 | 0 | 827 | 3 @ 880 |  |
| 91 | 1552 | 4 | A1 | 820 | 428 | 392 | n | 248 | fall 825 | 825 | 4 | 0/6 | 0 | 826 | 3 @ 880 |  |
| 92 | 2080 | 4 | A1 | 816 | 360 | 456 | n | 190 | words_exhausted | 1429 | 5 | 1/6 | 0 | 820 | 3 @ 880 |  |
| 93 | 2151 | 4 | A1 | 804 | 396 | 408 | n | 272 | fall 973 | 973 | 4 | 0/6 | 0 | 816 | 3 @ 880 |  |
| 94 | 1336 | 4 | A1 | 790 | 404 | 386 | n | 238 | words_exhausted | 1499 | 4 | 0/6 | 0 | 802 | 3 @ 880 |  |
| 95 | 1338 | 4 | A1 | 788 | 411 | 377 | n | 133 | fall 1138 | 1138 | 4 | 0/6 | 0 | 790 | 3 @ 880 |  |
| 96 | 2039 | 4 | A1 | 783 | 395 | 388 | n | 201 | words_exhausted | 1497 | 4 | 0/6 | 0 | 784 | 3 @ 880 |  |
| 97 | 1602 | 4 | A1 | 778 | 415 | 363 | n | 246 | fall 1152 | 1152 | 4 | 0/6 | 0 | 780 | 3 @ 880 |  |
| 98 | 1603 | 4 | A1 | 777 | 407 | 370 | n | 286 | fall 1145 | 1145 | 4 | 0/6 | 0 | 778 | 3 @ 880 |  |
| 99 | 1639 | 4 | A2 | 774 | 365 | 409 | n | 232 | fall 1106 | 1106 | 4 | 0/6 | 0 | 777 | 3 @ 880 |  |
| 100 | 1399 | 4 | G | 753 | 373 | 380 | n | 69 | fall 1135 | 1135 | 4 | 0/6 | 0 | 774 | 3 @ 880 |  |
| 101 | 1550 | 4 | A1 | 740 | 411 | 329 | n | 201 | words_exhausted | 1556 | 4 | 0/6 | 0 | 753 | 3 @ 880 |  |
| 102 | 1549 | 4 | A1 | 730 | 417 | 313 | n | 98 | words_exhausted | 1572 | 4 | 0/6 | 0 | 732 | 3 @ 880 |  |
| 103 | 1529 | 4 | A1 | 725 | 472 | 253 | n | 256 | words_exhausted | 1632 | 4 | 0/6 | 0 | 727 | 3 @ 880 |  |
| 104 | 1148 | 4 | A1 | 724 | 403 | 321 | n | 293 | words_exhausted | 1564 | 4 | 0/6 | 0 | 725 | 3 @ 880 |  |
| 105 | 1280 | 4 | A1 | 719 | 414 | 305 | n | 236 | words_exhausted | 1580 | 4 | 0/6 | 0 | 724 | 3 @ 880 |  |
| 106 | 1279 | 4 | A1 | 717 | 422 | 295 | n | 154 | words_exhausted | 1590 | 4 | 0/6 | 0 | 719 | 3 @ 880 |  |
| 107 | 1154 | 4 | G | 682 | 320 | 362 | y | 25 | fall 1179 | 1179 | 6 | 2/6 | 2 | 725 | 2 @ 1339 |  |
| 108 | 1153 | 4 | A0 | 680 | 459 | 221 | y | 201 | fall 1324 | 1324 | 7 | 3/6 | 2 | 718 | 6 @ 1776 |  |
| 109 | 1088 | 4 | A0 | 679 | 317 | 362 | y | 22 | fall 1179 | 1179 | 6 | 2/6 | 2 | 680 | 2 @ 1339 |  |
| 110 | 1087 | 4 | A0 | 675 | 313 | 362 | y | 47 | fall 1179 | 1179 | 6 | 2/6 | 2 | 679 | 2 @ 1339 |  |
| 111 | 1086 | 4 | A0 | 671 | 308 | 363 | y | 85 | fall 1178 | 1178 | 5 | 1/6 | 1 | 675 | 3 @ 880 |  |
| 112 | 1085 | 4 | A0 | 667 | 305 | 362 | y | 49 | fall 1179 | 1179 | 6 | 2/6 | 2 | 679 | 2 @ 1339 |  |
| 113 | 1103 | 4 | A0 | 663 | 303 | 360 | y | 147 | words_exhausted | 1525 | 4 | 0/6 | 0 | 665 | 3 @ 880 |  |
| 114 | 1084 | 4 | A0 | 662 | 300 | 362 | y | 28 | fall 1179 | 1179 | 6 | 2/6 | 2 | 663 | 2 @ 1339 |  |
| 115 | 1081 | 4 | A0 | 658 | 296 | 362 | y | 43 | fall 1179 | 1179 | 6 | 2/6 | 2 | 662 | 2 @ 1339 |  |
| 116 | 1080 | 4 | A0 | 654 | 291 | 363 | y | 120 | fall 1178 | 1178 | 5 | 1/6 | 1 | 658 | 3 @ 880 |  |
| 117 | 1079 | 4 | A0 | 649 | 287 | 362 | n | 153 | fall 1179 | 1179 | 6 | 2/6 | 2 | 662 | 2 @ 1339 |  |
| 118 | 1078 | 4 | A0 | 645 | 285 | 360 | n | 188 | words_exhausted | 1525 | 4 | 0/6 | 0 | 646 | 3 @ 880 |  |
| 119 | 1077 | 4 | A0 | 639 | 417 | 222 | n | 33 | fall 1323 | 1323 | 7 | 3/6 | 2 | 645 | 6 @ 1776 |  |
| 120 | 1076 | 4 | A0 | 631 | 412 | 219 | y | 100 | words_exhausted | 1666 | 4 | 0/6 | 0 | 636 | 3 @ 880 |  |
| 121 | 1074 | 4 | A0 | 623 | 403 | 220 | y | 95 | words_exhausted | 1665 | 4 | 0/6 | 0 | 627 | 3 @ 880 |  |
| 122 | 1073 | 4 | A0 | 618 | 397 | 221 | n | 39 | fall 1324 | 1324 | 7 | 3/6 | 2 | 623 | 6 @ 1776 |  |
| 123 | 1072 | 4 | A0 | 617 | 271 | 346 | n | 35 | fall 1169 | 1169 | 4 | 0/6 | 0 | 618 | 3 @ 880 |  |
| 124 | 1071 | 4 | A0 | 615 | 261 | 354 | n | 120 | fall 1027 | 1027 | 4 | 0/6 | 0 | 617 | 3 @ 880 |  |
| 125 | 1070 | 4 | A0 | 609 | 254 | 355 | n | 106 | words_exhausted | 1530 | 4 | 0/6 | 0 | 615 | 3 @ 880 |  |
| 126 | 892 | 3 | A0 | 608 | 387 | 221 | n | 172 | fall 1324 | 1324 | 7 | 4/7 | 3 | 623 | 6 @ 1776 |  |
| 127 | 893 | 3 | A0 | 607 | 252 | 355 | n | 40 | words_exhausted | 1530 | 4 | 1/7 | 1 | 608 | 3 @ 880 |  |
| 128 | 1069 | 3 | A0 | 605 | 282 | 323 | n | 200 | words_exhausted | 1562 | 3 | 0/7 | 0 | 607 | 5 @ 609 |  |
| 129 | 1068 | 3 | A0 | 599 | 276 | 323 | n | 108 | fall 1222 | 1222 | 6 | 3/7 | 2 | 600 | 5 @ 609 |  |
| 130 | 1019 | 3 | A1 | 597 | 301 | 296 | n | 226 | words_exhausted | 1589 | 4 | 1/7 | 1 | 603 | 3 @ 880 |  |
| 131 | 934 | 3 | A1 | 592 | 259 | 333 | n | 254 | words_exhausted | 1552 | 4 | 1/7 | 0 | 595 | 3 @ 880 |  |
| 132 | 1067 | 3 | A1 | 587 | 330 | 257 | n | 278 | fall 1288 | 1288 | 6 | 3/7 | 2 | 592 | 5 @ 609 |  |
| 133 | 936 | 3 | A1 | 584 | 268 | 316 | n | 284 | fall 1229 | 1229 | 6 | 3/7 | 2 | 587 | 5 @ 609 |  |
| 134 | 1066 | 3 | A1 | 575 | 399 | 176 | n | 143 | words_exhausted | 1709 | 5 | 2/7 | 0 | 576 | 3 @ 880 |  |
| 135 | 1065 | 3 | A1 | 563 | 395 | 168 | n | 190 | words_exhausted | 1717 | 4 | 1/7 | 0 | 567 | 5 @ 609 |  |
| 136 | 837 | 3 | A1 | 557 | 376 | 181 | n | 264 | fall 1135 | 1135 | 3 | 0/7 | 0 | 561 | 5 @ 609 |  |
| 137 | 838 | 3 | A1 | 552 | 380 | 172 | n | 173 | words_exhausted | 1713 | 4 | 1/7 | 0 | 557 | 5 @ 609 |  |
| 138 | 835 | 3 | A1 | 550 | 418 | 132 | n | 264 | words_exhausted | 1753 | 3 | 0/7 | 0 | 552 | 5 @ 609 |  |
| 139 | 774 | 3 | A1 | 545 | 388 | 157 | n | 197 | fall 809 | 809 | 3 | 0/7 | 0 | 546 | 5 @ 609 |  |
| 140 | 871 | 3 | A1 | 542 | 302 | 240 | n | 125 | fall 726 | 726 | 3 | 0/7 | 0 | 545 | 5 @ 609 |  |
| 141 | 834 | 3 | A1 | 541 | 306 | 235 | n | 62 | words_exhausted | 1650 | 3 | 0/7 | 0 | 542 | 5 @ 609 |  |
| 142 | 771 | 3 | A2 | 540 | 265 | 275 | n | 236 | words_exhausted | 1610 | 3 | 0/7 | 0 | 542 | 5 @ 609 |  |
| 143 | 770 | 3 | A2 | 536 | 252 | 284 | n | 52 | words_exhausted | 1601 | 3 | 0/7 | 0 | 540 | 5 @ 609 |  |
| 144 | 752 | 3 | G | 508 | 261 | 247 | n | 74 | fall 719 | 719 | 3 | 0/7 | 0 | 509 | 5 @ 609 |  |
| 145 | 738 | 3 | A0 | 502 | 348 | 154 | n | 213 | words_exhausted | 1731 | 5 | 2/7 | 0 | 504 | 3 @ 880 |  |
| 146 | 737 | 3 | A0 | 496 | 350 | 146 | n | 249 | words_exhausted | 1739 | 5 | 2/7 | 0 | 500 | 3 @ 880 |  |
| 147 | 736 | 3 | A0 | 482 | 354 | 128 | n | 33 | words_exhausted | 1757 | 3 | 0/7 | 0 | 486 | 5 @ 609 |  |
| 148 | 735 | 3 | A0 | 481 | 358 | 123 | n | 176 | words_exhausted | 1762 | 3 | 0/7 | 0 | 482 | 5 @ 609 |  |
| 149 | 734 | 3 | A0 | 477 | 371 | 106 | n | 244 | words_exhausted | 1779 | 3 | 0/7 | 0 | 478 | 5 @ 609 |  |
| 150 | 733 | 3 | A0 | 474 | 366 | 108 | n | 70 | words_exhausted | 1777 | 4 | 1/7 | 0 | 477 | 3 @ 880 |  |
| 151 | 732 | 3 | A0 | 472 | 318 | 154 | n | 247 | words_exhausted | 1731 | 3 | 0/7 | 0 | 474 | 5 @ 609 |  |
| 152 | 731 | 3 | A0 | 471 | 308 | 163 | n | 94 | words_exhausted | 1722 | 4 | 1/7 | 0 | 472 | 5 @ 609 |  |
| 153 | 730 | 3 | A0 | 465 | 323 | 142 | n | 226 | words_exhausted | 1743 | 3 | 0/7 | 0 | 469 | 5 @ 609 |  |
| 154 | 729 | 3 | A2 | 464 | 310 | 154 | n | 260 | words_exhausted | 1731 | 3 | 0/7 | 0 | 465 | 5 @ 609 |  |
| 155 | 728 | 3 | A2 | 455 | 327 | 128 | n | 263 | words_exhausted | 1757 | 3 | 0/7 | 0 | 461 | 5 @ 609 |  |
| 156 | 727 | 3 | A2 | 454 | 301 | 153 | n | 230 | words_exhausted | 1732 | 3 | 0/7 | 0 | 455 | 5 @ 609 |  |
| 157 | 726 | 3 | A2 | 451 | 299 | 152 | n | 198 | words_exhausted | 1733 | 3 | 0/7 | 0 | 453 | 5 @ 609 |  |
| 158 | 698 | 3 | G | 399 | 308 | 91 | n | 236 | words_exhausted | 1794 | 3 | 0/7 | 0 | 423 | 5 @ 609 |  |
| 159 | 422 | 2 | G | 375 | 111 | 264 | n | 30 | words_exhausted | 1621 | 3 | 1/8 | 0 | 382 | 5 @ 609 |  |
| 160 | 631 | 2 | A1 | 373 | 261 | 112 | n | 39 | words_exhausted | 1773 | 7 | 5/8 | 4 | 374 | 6 @ 1776 |  |
| 161 | 557 | 2 | A1 | 335 | 152 | 183 | n | 76 | fall 940 | 940 | 2 | 0/8 | 0 | 346 | 9 @ 399 |  |
| 162 | 293 | 2 | A1 | 328 | 183 | 145 | n | 188 | words_exhausted | 1740 | 4 | 2/8 | 0 | 335 | 3 @ 880 |  |
| 163 | 292 | 2 | A1 | 319 | 243 | 76 | n | 243 | words_exhausted | 1809 | 3 | 1/8 | 0 | 323 | 5 @ 609 |  |
| 164 | 291 | 2 | A1 | 315 | 247 | 68 | n | 162 | words_exhausted | 1817 | 3 | 1/8 | 0 | 319 | 5 @ 609 |  |
| 165 | 290 | 2 | A1 | 313 | 256 | 57 | n | 250 | words_exhausted | 1828 | 4 | 2/8 | 0 | 315 | 3 @ 880 |  |
| 166 | 289 | 2 | A1 | 309 | 251 | 58 | n | 241 | words_exhausted | 1827 | 3 | 1/8 | 0 | 313 | 5 @ 609 |  |
| 167 | 288 | 2 | A1 | 308 | 232 | 76 | n | 226 | fall 1047 | 1047 | 2 | 0/8 | 0 | 309 | 9 @ 399 |  |
| 168 | 287 | 2 | A2 | 304 | 121 | 183 | n | 95 | words_exhausted | 1702 | 6 | 4/8 | 2 | 313 | 9 @ 399 |  |
| 169 | 251 | 2 | G | 269 | 110 | 159 | n | 38 | words_exhausted | 1726 | 3 | 1/8 | 0 | 273 | 9 @ 399 |  |
| 170 | 250 | 2 | A2 | 266 | 119 | 147 | n | 51 | words_exhausted | 1738 | 3 | 1/8 | 0 | 268 | 9 @ 399 |  |
| 171 | 247 | 2 | A2 | 255 | 248 | 7 | n | 42 | words_exhausted | 1878 | 3 | 1/8 | 0 | 256 | 5 @ 609 |  |
| 172 | 246 | 2 | A2 | 251 | 244 | 7 | n | 179 | words_exhausted | 1878 | 3 | 1/8 | 0 | 252 | 5 @ 609 |  |
| 173 | 245 | 2 | A2 | 244 | 197 | 47 | n | 115 | fall 1494 | 1494 | 5 | 3/8 | 2 | 254 | 9 @ 399 |  |
| 174 | 244 | 2 | A2 | 232 | 213 | 19 | n | 166 | words_exhausted | 1866 | 4 | 2/8 | 0 | 238 | 3 @ 880 |  |
| 175 | 243 | 2 | A2 | 223 | 213 | 10 | n | 52 | fall 1306 | 1306 | 2 | 0/8 | 0 | 229 | 9 @ 399 |  |
| 176 | 159 | 2 | A2 | 222 | 139 | 83 | n | 275 | fall 1462 | 1462 | 6 | 4/8 | 3 | 223 | 9 @ 399 |  |
| 177 | 160 | 2 | A2 | 216 | 207 | 9 | n | 111 | fall 1536 | 1536 | 6 | 4/8 | 3 | 220 | 9 @ 399 |  |
| 178 | 161 | 2 | A2 | 212 | 203 | 9 | n | 114 | fall 1536 | 1536 | 5 | 3/8 | 2 | 216 | 9 @ 399 |  |
| 179 | 242 | 2 | A2 | 211 | 202 | 9 | n | 43 | fall 1536 | 1536 | 7 | 5/8 | 4 | 221 | 6 @ 1776 |  |
| 180 | 241 | 2 | A2 | 209 | 201 | 8 | n | 60 | words_exhausted | 1877 | 7 | 5/8 | 4 | 210 | 6 @ 1776 |  |
| 181 | 154 | 2 | G | 174 | 139 | 35 | n | 63 | words_exhausted | 1850 | 3 | 1/8 | 0 | 183 | 5 @ 609 |  |
| 182 | 153 | 2 | A0 | 172 | 148 | 24 | n | 125 | words_exhausted | 1861 | 3 | 1/8 | 0 | 173 | 5 @ 609 |  |
| 183 | 152 | 2 | A0 | 170 | 149 | 21 | n | 81 | fall 1102 | 1102 | 2 | 0/8 | 0 | 171 | 9 @ 399 |  |
| 184 | 151 | 2 | A0 | 168 | 150 | 18 | n | 92 | fall 1105 | 1105 | 2 | 0/8 | 0 | 169 | 9 @ 399 |  |
| 185 | 150 | 2 | A0 | 164 | 151 | 13 | n | 177 | words_exhausted | 1872 | 3 | 1/8 | 0 | 165 | 5 @ 609 |  |
| 186 | 149 | 2 | A0 | 159 | 158 | 1 | y | 42 | clear | 1884 | 10 | 8/8 | 8 | 163 | none | 1884/1883 |
| 187 | 148 | 2 | A0 | 154 | 153 | 1 | n | 18 | clear | 1884 | 10 | 8/8 | 8 | 163 | none | 1884/1883 |
| 188 | 146 | 2 | A0 | 148 | 122 | 26 | n | 251 | words_exhausted | 1859 | 3 | 1/8 | 0 | 152 | 5 @ 609 |  |
| 189 | 145 | 2 | A0 | 140 | 126 | 14 | n | 234 | words_exhausted | 1871 | 3 | 1/8 | 0 | 143 | 5 @ 609 |  |
| 190 | 139 | 1 | A0 | 115 | 102 | 13 | n | 71 | fall 1532 | 1532 | 6 | 5/9 | 3 | 116 | 9 @ 399 |  |
| 191 | 93 | 1 | G | 96 | 81 | 15 | n | 30 | words_exhausted | 1870 | 3 | 2/9 | 0 | 114 | 5 @ 609 |  |
| 192 | 92 | 1 | G | 88 | 76 | 12 | n | 26 | fall 1533 | 1533 | 6 | 5/9 | 3 | 93 | 9 @ 399 |  |
| 193 | 91 | 1 | G | 84 | 58 | 26 | n | 121 | words_exhausted | 1859 | 4 | 3/9 | 0 | 88 | 5 @ 609 |  |
| 194 | 40 | 0 | A2 | 24 | 14 | 10 | n | 90 | words_exhausted | 1875 | 3 | 3/10 | 0 | 25 | 5 @ 609 |  |
| 195 | 6 | 0 | A2 | 14 | 10 | 4 | n | 140 | words_exhausted | 1881 | 4 | 4/10 | 0 | 18 | 5 @ 609 |  |
| 196 | 5 | 0 | A2 | 7 | 5 | 2 | n | 58 | words_exhausted | 1883 | 4 | 4/10 | 0 | 12 | 5 @ 609 |  |
| 197 | 0 | 0 | G | 1 | 0 | 1 | n | 0 | words_exhausted | 1884 | 3 | 3/10 | 0 | 4 | 5 @ 609 |  |
