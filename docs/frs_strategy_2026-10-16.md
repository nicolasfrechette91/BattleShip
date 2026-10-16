# Fast-route strategy review (2026-10-16)

## 0. Status, scope, sources and method

**Status: offline, read-only investigation; zero native ticks.** No game, lab command, suite or launcher was started; no C:/BattleShip_lab/
lab.lock existed and no BattleShip process ran at the start. Nothing under `rl/`, `tools/`, `runs/`, `C:/BattleShip_lab/` or on D: was
created, modified or deleted. The only new files are this record and the Git-ignored working files under `logs/frs_strategy/` (scripts
`scripts/s0_common.py` to `s7_orders_view.py`, their JSON outputs and stdout captures). Checkout
`C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, branch `main`, HEAD = `origin/main` = `df36838`, clean at the start. The TAS, every
human recording, the owner's own run and any external time were not read or used; no time other than the agent's own is a target or a
reference anywhere below. This record proposes options for the owner's decision; it decides nothing and launches nothing.

**Data (all read-only).** Crossing run 1 (`C:/BattleShip_lab/crossing_2026-10-15`: 30,699 dispatches, 105,870 cell rows, 298 verified-clear
traces), crossing run 2 (`crossing_2026-10-15_run2`: 39,309 dispatches, 75,787 cell rows, the 1,245 / 1,261 / 1,352 traces, the reference and
run 1's best), the frontier search (`frontier_2026-10-14`: 37,194 bursts, 136 seeds, 1,252 frontier members), the trail-lead probe
(`trail_probe_2026-10-14`: 3,960 dispatches) and the lab import of the sd2 archive (`import/archive`: 21,323 bursts, 49,928 cells). The
splice probe's folder was listed only. The records read in full: the handoff, the two crossing-search records, the frontier record, the
crossing study and the fast-route archive analysis of 2026-10-13.

**Method.** The exact break history of every trajectory the agent has produced was rebuilt offline (`s2_lineage.py`): in the archive by the
(burst, offset) representatives and the reaches' mask changes; in the probe from the route's or the import cell's prefix; in the frontier by
(round, sid, k); in runs 1 and 2 by the prefix digests the records store (a cell's `origin.parent_digest`, a dispatch's `draw_id`). Checks: the
stored `prefix_breaks` of all 111,162 lab dispatches (30,699 + 39,309 + 37,194 + 3,960) equalled the rebuilt history (0 mismatches); the
archive bests of the 2026-10-13 analysis were reproduced where the lab did not improve them (level 1 at 26, level 3 at 152, level 4 at 254,
level 6 at 871, the record at 1,885) and the lab's improvements appear (78 at level 2; 413 for the order 9, 4, 5, 0, 7; 1,097 for the order
0, 4, 5, 7, 9, 3, 2; 493 at level 7); the 1,245 clear's rebuilt history equals its verification's break table. Per-tick facts come from the traces (`s1_anatomy.py`, `s1b_timeline.py`, `s5_movement.py`); the search facts from the dispatch and
cell rows (`s6_search.py`, `s6b_lead.py`, `s4_explorer.py`). Stage names, target ids, coordinates and cell ids below describe the records;
no mechanism proposed in sections 6 and 7 reads any of them.

**Definitions.** Level = targets broken; a "transition A -> B" = the ticks from the break of target A to the break of target B when B is the
next break; "class" = the archive's resource class (G grounded with its floor line, A2 airborne with double jump and up-B, A1 up-B only,
A0 neither: up-B or helpless) at the moment of the previous break; "composite" = the sum, over an order's consecutive pairs, of the fastest
transition observed anywhere for that pair. **A composite is not a route: its parts come from different trajectories and states, some of
its pairs were broken by a projectile from far away (9 -> 0 in 2 ticks, 0 -> 2 in 22), and nothing says the parts can be chained.** It is
the lower envelope of what the agent has shown piece by piece.

## 1. Anatomy of the 1,245 clear (and the 1,261, 1,429 and 1,885 for comparison)

Order and break ticks: 1,245 and 1,261 break 4, 0, 5, 7, 9, 3, 2 by 639 then 6 at 1,042 and 8, 1 (1,135 / 1,245; 1,195 / 1,261). 1,429 and
1,352 break 4, 5, 9, 7, 0, 3, 2 by 848 then 6 at 1,288 / 1,231, 8 at 1,356 / 1,307, 1 at 1,429 / 1,352. The reference breaks 0, 4, 9, 5, 3, 7, 2
by 1,339 then 6, 8, 1 at 1,776, 1,832, 1,885.

**Ticks per segment and what they contain** (`s1_anatomy.json`; grd = grounded moves other than the ones listed; llag = landing lag;
help = helpless; spec = fireball or down-B; "still" = ticks with no motion; "away" = ticks moving away from the next target's x):

| clear | -> target | ticks | grd | roll | llag | air | up-B | spec | help | still | away-x | notes from the timeline |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1,245 | 4 @29 | 29 | 0 | 0 | 0 | 26 | 0 | 0 | 0 | 2 | 2 | two jumps from the start, aerial |
| | 0 @80 | 51 | 0 | 0 | 0 | 51 | 0 | 0 | 0 | 6 | 0 | aerial drift left and down |
| | 5 @167 | 87 | 15 | 0 | 0 | 56 | 9 | 0 | 0 | 19 | 8 | lands, 15 ticks idle on the floor, two jumps, up-B |
| | 7 @184 | 17 | 0 | 0 | 0 | 0 | 17 | 0 | 0 | 3 | 0 | the same up-B continues through target 7 |
| | 9 @305 | 121 | 15 | 0 | 25 | 5 | 24 | 0 | 49 | 26 | 20 | **49 ticks helpless** falling 3,260 units, 25 landing lag, 15 dash |
| | 3 @461 | 156 | 26 | 0 | 25 | 13 | 42 | 45 | 2 | 64 | 24 | up-B to the right platform, 25 lag, **45 ticks of fireballs + 15 of a ground attack** at x 2,383; target 3 (2,567 units away) breaks at 461 |
| | 2 @639 | 178 | 25 | 31 | 25 | 50 | 30 | 13 | 0 | 3 | 65 | aerial left then up-B right to the moving platform, 25 lag, attack, **31-tick roll away**, down-B |
| | 6 @1,042 | 403 | 29 | 0 | 25 | 203 | 39 | 78 | 7 | 70 | 7 | **77 ticks of down-B on the rising platform**, flight 720 -> 905 (185 ticks), **70 ticks on the wall top** (lag, shield, attack, idle), 63 ticks airborne to the break |
| | 8 @1,135 | 93 | 0 | 0 | 0 | 8 | 0 | 85 | 0 | 3 | 25 | **85 ticks of down-B descending** 2,900 units (34 units per tick; a fall is 70) |
| | 1 @1,245 | 110 | 0 | 0 | 0 | 110 | 0 | 0 | 0 | 7 | 54 | overshoot: down to y -3,531 (1,000 below the target), double jump back up |
| 1,261 | same to 1,042; 8 @1,195 | 153 | 0 | 0 | 0 | 68 | 0 | 85 | 0 | 3 | 74 | the same descent, then 68 airborne ticks wandering |
| | 1 @1,261 | 66 | 0 | 0 | 0 | 66 | 0 | 0 | 0 | 8 | 20 | |
| 1,429 | 9 @246 | 151 | 13 | 0 | 25 | 5 | 26 | 44 | 35 | 42 | 37 | |
| | 7 @482 | 236 | 30 | 0 | 25 | 56 | 39 | 79 | 1 | 84 | 82 | the slowest right-side segment of any clear: 84 still, 82 away |
| | 0 @663 | 181 | 13 | 0 | 0 | 108 | 0 | 57 | 0 | 22 | 88 | 88 away-x ticks |
| | 6 @1,288 | 440 | 20 | 31 | 25 | 194 | 39 | 89 | 21 | 79 | 40 | 88 ticks of down-B on the platform, flight 944 -> 1,133 (189), **88 ticks on the wall top** (lag, roll, attack, shield) |
| | 8, 1 | 68, 73 | | | | 141 | | | | 14 | 35 | the fastest left side of the three (the 1,352: 76 + 45 = 121) |
| 1,885 | all | 1,885 | 133 | 93 | 194 | 901 | 250 | 45 | 147 | 400 | 312 | |

Totals of the 1,245: airborne 522 (42 %), down-B 176, up-B 161, fireball 45, grounded moves 110, landing lag 100 (four landings of 25),
helpless 58, roll 31, jump squat 21, shield 17, landing-free 4; 203 ticks without motion, 205 ticks moving away from the next target in x
and 263 in y; the path is 45,453 units long against 27,779 units of segment chords (ratio 1.64; the 1,429: 1.88).

**Reading.** The 1,245 spends about 455 ticks (37 %) in states that move slowly or not at all: 100 landing lag, 58 helpless, 77 shield /
idle / jump squat / landing-free, and 221 ticks of down-B or fireball (mean horizontal speed 6 and 12 units per tick against 17 to 20
airborne and 26 in up-B). Its three long waits are the platform ride (77 ticks of down-B while the moving platform rises 300 units), the
wall-top stop (70 ticks) and the down-B descent to target 8 (85 ticks); its two detours are the helpless fall after the up-B through target
7 (49 ticks, then 40 more to recover and reach target 9) and the overshoot below target 1. Its right side (639) is 146 ticks slower than the
fastest level-7 arrival the agent has (493, the frontier's helpless state after an up-B, same order); its crossing (403) is 124 to 158 ticks
slower than the fastest observed (sections 2 and 4); its left side (203) is 82 ticks slower than the 1,352's (121).

## 2. Fastest observed transitions and the composites

54 ordered target pairs have been observed as consecutive breaks (10 targets); the best of each pair comes from the archive (22 pairs),
the frontier (20), the probe (5), run 2 (5) and run 1 (2). Full tables: `s2_pairs.json` (top 6 per pair with provenance), `s2_pairs_by_class.json`
(best per pair and start class), `s3_composite.json`.

**The 1,245 order, segment by segment** (clear = the 1,245's own ticks; best = fastest observed anywhere; n / p10 / median over every
observation of the pair; same class = fastest among transitions that started from the class the 1,245 was in at the previous break):

| pair | clear | best | where | n | p10 | median | same class | room (best) |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| start -> 4 | 29 | 26 | archive rd1 | 55 | 26 | 117 | 26 | 3 |
| 4 -> 0 | 51 | 45 | archive rd4 | 111 | 64 | 112 | 45 (A1) | 6 |
| 0 -> 5 | 87 | 45 | frontier (grounded start) | 44 | 53 | 141 | 83 (A1) | 42 |
| 5 -> 7 | 17 | 11 | archive rd3 | 1,431 | 17 | 17 | 11 (A0) | 6 |
| 7 -> 9 | 121 | 96 | frontier, from the 184 up-B state | 307 | 103 | 144 | 96 (A0) | 25 |
| 9 -> 3 | 156 | 101 | frontier (grounded on the right platform) | 55 | 159 | 240 | 156 (A0) | 55 |
| 3 -> 2 | 178 | 12 | frontier (A1 near the platform; a projectile or a hit on arrival) | 71 | 50 | 262 | 32 (G, small platform: the 493 state's own 461 -> 493) | 166 |
| 2 -> 6 | 403 | 245 | probe pair 170 lead (an archive state at 1,237 crossing at 1,482) | 122 | 311 | 440 | n/a: the 1,245 broke 2 grounded on the moving platform and no kept arrival records that class; the A2 best is 245, the best from an unrecorded class 352 | 158 |
| 6 -> 8 | 93 | 39 | probe pair 192 control (the route's neighbourhood, 1,777 -> 1,816) | 359 | 56 | 100 | 54 (A2, run 2) | 54 |
| 8 -> 1 | 110 | 45 | run 2 (the 1,352 clear) | 328 | 72 | 114 | 53 (A2, archive sd2) | 65 |
| **sum** | **1,245** | **665** | | | | | **801 to 908** | **580** |

**Other orders.** The 1,429 / 1,352 order (4, 5, 9, 7, 0, 3, 2, 6, 8, 1): composite 497 (parts 26, 10, 54, 35, 20, 11, 12, 245, 39, 45); its right
side composite is 168 against 848 done, and 798 is the fastest level-7 arrival seen with that order. The reference order: composite 780. The
minimum composite over all 10! orders (a dynamic programme over the 54 pair minima) is 393 for 0, 2, 3, 9, 4, 5, 7, 6, 8, 1, which chains
projectile breaks and is not a route of any kind; it is quoted only to show how little the envelope constrains.

**Where the room is.** Against the best observed transitions the 1,245 has 580 ticks of room, 324 of them in two segments (3 -> 2 and
2 -> 6) and 119 in the left side (6 -> 8, 8 -> 1); against same-class transitions only, 337 to 444 ticks, of which 51 to 158 in the crossing. The
physically coherent reading, chaining whole observed parts rather than pair minima: right side 493 (one frontier trajectory, same order as
the 1,245) + crossing 245 (one probe trajectory, from a state the 1,245 never visits) + left side 121 (the 1,352's) = 859 ticks (14.3 s), and
this too is a composite of three incompatible starts. Below about 850 ticks nothing in the agent's data shows the way: every part the
agent has produced faster than that is a pair broken by a projectile or an aerial on arrival, not a traverse.

## 3. Target orders explored

180 distinct order prefixes exist across the archive and the lab (levels 1 to 10): 38 at level 4, 33 at level 5, 19 at level 6, 15 at level 7,
12 at level 8, 9 at level 9 and **5 complete orders**, all five of them crossing over the top and finishing with 6 then 8 and 1 or 1 and 8:

| complete order | fastest clock | verified clears with it | composite |
| --- | ---: | ---: | ---: |
| 4, 0, 5, 7, 9, 3, 2, 6, 8, 1 | 1,245 (run 2) | 22 claims | 665 |
| 4, 0, 5, 7, 9, 3, 2, 6, 1, 8 | 1,280 (run 2) | 46 | 770 |
| 4, 5, 9, 7, 0, 3, 2, 6, 8, 1 | 1,352 (run 2; 1,429 in run 1) | 157 | 497 |
| 4, 5, 9, 7, 0, 3, 2, 6, 1, 8 | 1,588 (run 1) | 209 | 602 |
| 0, 4, 9, 5, 3, 7, 2, 6, 8, 1 | 1,885 (archive) | 21 | 780 |

**Level 7** (every row below has the three left targets live, except the two run-2 orders that took a left target early):

| order prefix | fastest arrival | composite | trajectories | dispatches from states with exactly this prefix |
| --- | ---: | ---: | ---: | ---: |
| 4, 0, 5, 7, 9, 3, 2 (the 1,245's) | 493 (frontier) | 336 | 47 | 6,341 |
| 4, 0, 5, 7, 9, 2, 3 | 638 | 469 | 56 | 404 |
| 4, 5, 9, 7, 0, 3, 2 (the 1,429's) | 798 | 168 | 7 | 2,811 |
| 4, 0, 5, 7, 3, 9, 2 | 874 | 423 | 1 | 16 |
| 4, 0, 5, 7, 9, 2, 6 (target 6 before 3) | 879 (run 2) | 632 | 9 | 226 (2 breaks, 3 falls, 320 new cells) |
| 4, 0, 5, 7, 9, 3, 8 (target 8 before 2) | 894 (run 2) | 757 | 7 | 157 (0 breaks) |
| 4, 5, 9, 3, 0, 2, 7 | 979 | 398 | 2 | 48 |
| 4, 5, 9, 7, 3, 0, 2 | 1,079 | 326 | 1 | 17 |
| 4, 5, 9, 7, 2, 0, 3 | 1,089 | 347 | 1 | 17 |
| 0, 4, 5, 7, 9, 3, 2 | 1,097 (probe) | 289 | 8 | 113 |
| 4, 5, 9, 7, 0, 2, 3 | 1,101 | 249 | 1 | 16 |
| 0, 4, 5, 7, 3, 9, 2 | 1,154 | 376 | 2 | 16 |
| 4, 5, 9, 7, 2, 3, 0 | 1,234 | 308 | 2 | 32 |
| 0, 4, 9, 5, 3, 7, 2 (the reference's) | 1,339 | 451 | 38 | 5,002 |
| 0, 4, 9, 5, 3, 2, 7 | 1,372 | 511 | 36 | 155 |

Two level-7 orders took 9,152 of the 15,371 level-7 dispatches; nine orders got 16 to 48 each (the frontier's retirement allowance). Levels
8 and 9 hold 12 and 9 prefixes, all of them extensions of the two clearing right sides plus the reference's; the only crossing before the
right side was done is the run-2 pair above (6 at 879, extended once to level 8 at 1,527).

**Barely tried prefixes whose composite beats the 1,245 prefix's composite at the same level** (the 1,245 prefix's composites: level 4: 127,
5: 223, 6: 324, 7: 336): at level 5, 0, 9, 4, 5, 7 (fastest 491, composite 79, 36 dispatches), 4, 5, 0, 9, 7 (367, 147, 32), 9, 4, 5, 0, 7 (413, 165,
37), 4, 9, 0, 3, 2 (510, 100, 16); at level 6, 4, 5, 9, 7, 0, 2 (770, 167, 32), 0, 9, 4, 5, 7, 3 (782, 181, 16), 4, 5, 9, 7, 3, 2 (745, 239, 32); at level
7, 4, 5, 9, 7, 0, 2, 3 (1,101, 249, 16). Reading: the order space is wide open at levels 5 and 6 (33 and 19 prefixes, most with 16 to 40
dispatches), but no order other than the two clearing ones has ever been carried to level 8, and every composite below 300 at level 7 is
built from pair minima that include remote breaks. What the composite does say with some force is that **the order in which the right
side is taken matters less than the state in which the right side ends**: the 1,245's own order reaches level 7 at 493 in one lineage
(helpless at the top right) and at 639 in another (grounded on the moving platform), and only the second ever crossed.

## 4. Movement (observations, not bounds)

From the 302 traces (run 1's 298 clears, run 2's three, the reference; `s5_movement.json`), per-tick extremes by status class:

| class | ticks | max horizontal per tick | max rise | max drop | mean horizontal |
| --- | ---: | ---: | ---: | ---: | ---: |
| roll | 10,044 | 280.6 | 18 | 0 | 22.1 |
| up-B (special_hi) | 55,477 | 126.3 | 226.9 | 47.6 | 25.7 |
| dash / run | 10,423 | 54.0 | 0 | 0 | 25.9 |
| airborne / aerial attack | 209,816 | 55.3 | 79.6 | 70.0 | 17.4 to 19.6 |
| fireball (special_n) | 72,358 | 44.0 | 66.6 | 44.0 | 11.6 |
| helpless | 35,537 | 17.8 | 0 | 70.0 | 9.9 |
| down-B (special_lw) | 30,654 | 34.7 | 22.0 | 44.0 | 6.4 |
| landing lag | 29,137 | 19.8 | 17.5 | 67.5 | 0.8 |

Best displacement over a window, any trace: left 1,453 / 2,251 / 3,645 units in 30 / 60 / 120 ticks (all three in the reference's crossing
flight), right 1,279 / 1,675 / 2,182, up 2,288 / 3,242 / 4,529, down 2,100 / 4,200 / 6,610.

**How the clears move** (302 clears; min / median / max): landing lag 75 / 102 / 194 ticks; helpless 57 / 134 / 174; up-B 121 / 201 / 250
(3 to 6 up-Bs; each up-B costs 39 ticks of the move plus a helpless fall or 25 ticks of landing lag); down-B 0 / 90 / 176; fireball 45 / 225
/ 300; roll 0 / 31 / 93 (0 to 3 rolls); idle 25 / 27 / 56; 13 to 23 jumps. Rolls carry 0 to 10 % of the horizontal distance (median 3 %), up-B
12 to 24 % (median 21 %), down-B 0 to 7 %. The fastest twenty clears against the slowest twenty: landing lag 75 against 100, helpless 57
against 101, up-B 121 against 168, roll 31 against 62, idle 27 against 56, airborne 686 against 770: the faster clears are faster by having
fewer recovery and waiting ticks, not by moving faster per tick. The 1,245's horizontal travel is 17 % up-B and 6 % roll, and 221 of its
ticks are in the two slowest moving classes (down-B, fireball).

**Recovery and lag in the 1,245:** 100 ticks of landing lag (four landings), 58 helpless (one fall after the up-B through target 7), 39 ticks
in the up-B that crossed, 85 ticks of down-B descent: 282 ticks (23 %) in recovery or slow descent. The same landings happen in every clear
of both lineages (right platform, moving platform, wall top), so the landing lag is a structural 75 to 100 ticks of the route family, not a
one-off.

## 5. The search's limits

**Where run 2's effort went** (`s6_search.json`): level 9 took 20,984 of 39,309 dispatches (53 %); of these the group with target 6 left (mask
64) took 8,078 for 0 breaks and 7,327 falls, the group with target 1 left 8,027 for 90 clears, the group with target 8 left 4,879 for 46.
Level 8 took 10,528 (groups: targets 1 and 6 left 5,021 / 109 breaks; 1 and 8 left 4,496 / 185; 6 and 8 left 1,011 / 0). Level 7 took 5,208
(4,825 to the standard level-7 group, 92 breaks; 226 and 157 to the two early-left-target groups). Level 6: 2,589.

**Where the gains came from.** All three bests descend from the 639 right side run 1 had kept at its fifth dispatch (cell 58 at 514, then
602, 734). The 1,245's chain is 12 kept cells (`s4_explorer.json`):

| link | level, tick | created at | first dispatched at | dispatches | produced the next link on |
| ---: | --- | --- | --- | ---: | --- |
| 1 to 4 | 6: 461, 514, 602; 7: 734 | run 1: seed, 5, 11,237, 22,928 | run 1 | 2, 2, 1, 3 | |
| 5 | 7: 978 (mid-flight, A2) | run 1: 23,285 | **run 2: 14,659** (about 22,000 dispatches later) | 1 | its 1st: the crossing, target 6 at 1,042 |
| 6 | 8: 1,042 | run 2: 14,661 | 16,105 | 2 | 1st |
| 7 | 8: 1,071 | 16,110 | 18,309 | 2 | 2nd (29,049) |
| 8 | 8: 1,098 | 29,051 | 29,318 | 3 | 1st |
| 9 | 9: 1,150 | 29,318 | 29,643 | 1 | 1st |
| 10 | 9: 1,188 | 29,646 | 34,242 | 1 | 1st |
| 11 | 9: 1,202 | 34,247 | 35,106 | 2 | 1st |
| 12 | 9: 1,209 | 35,114 | 36,236 | 1 | 1st: the clear |

Every link produced the next link within its first three dispatches; of the eight links dispatched in run 2, seven did so on their first
dispatch and one on its second. The chain's own dispatches are 13 of
39,309; the rest of the 21,575 dispatches between the crossing and the clear were waiting for the selection to come back to a link
(waits of 267 to 4,596 dispatches per link). Run 1's 1,429 chain is the same story: eight level-7 links found in the first 1,500 dispatches,
then the level-8 link waited 17,724 dispatches (four hours) for its first dispatch, and the clear came on the second dispatch of the last
link. **The explorer's inputs are not the scarce resource; dispatches of the right states are.**

**Does a faster arrival propagate?** A faster arrival at a known key replaces the representative (run 1: 73,126 replacements, median gain 24
ticks; run 2: 71,237, median 26). Of these, 18 % (run 1) and 28 % (run 2) were ever dispatched afterwards, after a median wait of about 2,000
dispatches (90th percentile 10,000); 72 to 82 % of the faster states were never tried. By pace (`s6b_stdout.txt`, both runs): at level 7 the
388 cells that arrived at or before the 1,245's own level-7 tick received 481 dispatches in all (96 never dispatched) and produced 0 breaks;
the fastest fifth of level 7 (arrivals 493 to 733: 1,813 cells) received 2,279 dispatches for 1 break; the 493 state itself was dispatched
twice in two runs. At level 8 the 253 cells ahead of the 1,245's crossing tick got 767 dispatches (33 breaks); at level 9 the 174 cells ahead
of its level-9 tick got 1,778 dispatches (3 clears, among them the 1,245). 3,334 of the 9,069 level-7 cells were never dispatched. The pace
term (slack to the power one half) separates the fastest level-7 cell from a median one by a factor 1.6; the level draw gives the deepest
level half the budget and splits a level's eighth over thousands of cells, so a fast state at level 7 expects about one dispatch per run.

**Could the explorer produce the faster segments?** It already did: of the 21 fastest lab transitions (top three per pair), 20 started from a
prefix whose last break was before the burst and 11 broke within 30 words of the burst's start; their words are near-uniform draws with
holds (mean run 3 to 12 ticks). The 8 -> 1 in 45 ticks is 24 words in two runs (up-right with A for 16, with B for 8) from a cell 24 ticks
after the break of 8. In both runs the break inside a burst comes at a median offset of 11 (run 1) and 26 (run 2) words, 90th percentile about
100: the kept cells already sit one short burst from the next break. Random 120-word segments from the right state produce the agent's
fastest known segments; what no random segment produces is a crossing from a state far from the one that crossed (the crossing study's
finding, repeated here: 0 breaks in 481 dispatches from the fast right-side states), and what the selection does not do is return to a
good state before thousands of other dispatches.

**The cell key.** It holds position at 300 units, resource class, mask and floor line; not velocity, facing, the moving platform's phase or
the break order. The 2026-10-13 analysis measured that 86 % of shortenings changed the state materially; here it shows as the 72 to 82 % of
replacements never dispatched and as the level-9 group with target 6 left (8,078 dispatches, 0 breaks): the key cannot tell a state that is
one burst from a break from one that is not.

## 6. Strategy options for November

Each option is generic and stage-agnostic (no coordinate, target id, cell id, direction or census number in any rule; the groups and ranks
below are the archive's own level, mask, arrival tick and dispatch counts). Evidence, cost and risk are from the records above.

1. **Run 3 as the run-2 record proposes, with two selection changes.** Continue from run 2's archive at the registered bound rule, store the
   end record in the cells file, and (a) split the budget at every level by (level, mask) group with a share that rises with the group's
   recent break rate and never falls below a floor, (b) draw within a group by the rank of the cell's arrival tick (the fastest decile with
   at least half the group's draws) instead of the slack term. Evidence: the chain waits above; the 0-break group that took 8,078 dispatches;
   the fastest cells at every level dispatched 0 to 6 times. Cost: about 150 lines over `crossing_search_run2.py`, zero-tick tests, a census
   of the new masses, one night. Risk: exploitation of the current lineage (it polishes the 1,245's left side and crossing; the room there
   is about 80 and 120 to 160 ticks, section 2); no new right side. Expected: a verified clear in the 1,050 to 1,150 range if the left side
   and crossing reach the observed bests; honestly uncertain because the 1,683-style landing states and the probe's 245-tick crossing came
   from other lineages.
2. **Stepping stones toward the fastest observed transitions (segment-by-segment building).** Mechanism: for each (level, mask) group keep
   an "anchor set" = the k earliest arrivals and their descendants' earliest arrivals at the next level; give anchors a reserved share and
   dispatch them in lead order; a segment's milestone is "an arrival at the next level earlier than the group's previous earliest". This is
   the chain mechanism made deliberate: seven of the eight run-2 links produced the next link on their first dispatch, so the search should
   dispatch every new earliest arrival within minutes, not hours. Evidence: the chains; the frontier's "deep states exhausted in 16 bursts" is
   the failure mode to avoid, so anchors are not retired, they decay (share halves after each burst without a new earliest arrival in the
   group and recovers on one). Cost: the same code as option 1 plus the anchor bookkeeping (about a day); two nights. Risk: anchoring on the
   fastest arrival of a group when that arrival's class is a dead end (the 493 state is helpless at the top right; every crossing so far
   started grounded or A2 near the platform); mitigated by keeping anchors per (group, class).
3. **Order-diverse right side.** Reserve a share of the right-side levels' budget per order prefix (the order is derivable from the lineage,
   generic), so that the 33 level-5 and 19 level-6 orders that got 16 to 40 dispatches get hundreds, and seed the archive with the earliest
   arrivals per order from the frontier and the probe (they are exact prefixes, re-derivable and checked, as run 1 did for 48 of them).
   Evidence: the composite and the fastest-arrival table (section 3) say the right side can end 100 to 300 ticks earlier in several orders;
   the counter-evidence is that no order other than two has ever reached level 8, and that the crossing rate from fast right-side states is
   0 in 481. Cost: a seed reader over the frontier files plus the per-order share (half a day); one night as the "right-side arm". Risk:
   dilution; the milestone must be a crossing from a right side faster than the best clear's, not a faster right side alone (the frontier
   already produced those).
4. **State-aware representatives.** Keep up to m representatives per key, distinguished by a generic sub-key (sign and magnitude bucket of
   the velocity, facing, jumps used, grounded/airborne already in the class); replacement happens within a sub-key, so a faster arrival with
   another velocity does not evict the one that crossed, and dispatches draw sub-keys round-robin. Evidence: 86 % of shortenings change the
   state materially; the crossing is timing-coupled (the splice probe's 12-unit brittleness; the platform's 300-tick phase); the run-2 group
   with the hardest remaining work absorbed a fifth of the budget without a break. Cost: a new archive contract (cells file and reader),
   memory times m, tests; archives before and after are not comparable. Risk: cell explosion and dilution; do it after options 1 to 3 have
   shown whether budget allocation alone moves the crossing rate.
5. **A learned cell prior from the agent's own dispatch history (offline first, zero ticks).** Train on run 1's 30,699 dispatches a model
   that predicts "this dispatch breaks a target" from generic cell features (level, class, lead rank in its group, seen, fresh, break record,
   dispatch count) and test it on run 2's 39,309; if its ranking is materially better than the current weights (AUROC, precision at the top
   decile), use it as the within-group draw weight. Evidence for: the crossing study's per-cell signals (break record 16 x, arrival count);
   against: a frozen prior learned on one lineage will favour that lineage. A policy that finishes segments from given states (GCSL-like) is
   not supported: the M7 and M9 lines showed collapse and goal-blindness, and the data holds one route family (five orders, two right
   sides). Cost: one to two days offline, no native ticks; risk: none until it is used in a draw.
6. **Explorer changes built from the agent's own fastest segments.** The evidence is still against: the fastest segments are near-uniform
   random words from well-placed states; holding a direction did not land the crossing (study, section 1.4). Keep continuation (16 to 20 % of
   boundaries) and leave the word distribution alone; revisit only if options 1 to 4 saturate.
7. **Throughput levers and many more nights.** Prefix replay is 86 % of run 2's ticks (46.6 M of 54.1 M); the prefix-cost record's async close
   and second standby give an estimated 1.3 to 1.5 x, a native batched prefix much more but it is port work. Run 2's bests arrived at 22 min,
   4 h 15 and 7 h 21: the run was still finding bests at the cap, so nights do convert into ticks saved while the selection returns to good
   states. Cost: nights; risk: none beyond the plateau rule. Do the Python-side levers when a night is budget-limited; defer native work.

**Recommended staged plan.**

- **Stage 0 (offline, week 1 of November, zero ticks).** Build run 3 = run 2's tool plus the end-record store, the per-group budget, the
  rank draw and the anchor set (options 1 and 2 are one selection change with two switches); zero-tick tests on the real run-2 archive; a
  census of the masses (the fastest decile per group must hold at least half its group's draws, the 0-break group must fall under a tenth
  of its level's budget within an hour of simulated dispatches). In parallel the offline cell-prior study (option 5) as a reading only.
  Checkpoint C0: tests pass, census as stated, one light review of the launch path (the handoff's rule).
- **Stage 1 (night 1): run 3** from run 2's archive at the bound rule with anchors on. Stopping rule: PROGRESS if a verified clear beats the
  best by more than the registered margin or a new earliest arrival at level 8 or 9 appears from a lineage ahead of the best clear's pace at
  level 7; else STOP this arm. Expected PROGRESS probability from the room measured here: moderate (the left side's 80 ticks are the
  likeliest, the crossing's 120 to 160 need a new landing state).
- **Stage 2 (nights 2 and 3): the right-side arm** (option 3) seeded from the frontier's and probe's earliest arrivals per order at levels 5 to
  7, with the per-order share and anchors; milestone = a level-8 arrival from a lineage whose level-7 arrival is earlier than the best
  clear's. Stopping rule: two nights without that milestone means the crossing from fast right-side states needs state-aware
  representatives (stage 3), not more budget.
- **Stage 3 (night 4, only if stage 2 stops): state-aware representatives** (option 4) on the stage-2 configuration, read by the crossing
  rate per 1,000 level-7 dispatches from ahead-of-pace cells. Stopping rule: no change in that rate means the crossing from fast states is not
  a selection problem at all, and the line pauses for a mechanism study.
- **Plateau rule (unchanged from the decisions record):** three campaign nights with no faster verified clear and no new earliest arrival per
  group ends the line; the 2026-11-27 review decides.
- **What the plan can honestly reach, by the agent's own data:** about 1,050 to 1,150 from stage 1 if the measured room is taken, about 860 to
  900 if a fast right side can be made to cross and the observed crossing and left side are chained (stage 2 or 3). Anything lower needs
  segments the agent has never produced, and no offline analysis can say whether they exist.

## 7. What cannot be determined offline

1. Whether a crossing is possible from the fast right-side states (helpless at the top right at 493, grounded on the small platform at
   461 to 493): 0 breaks in 481 dispatches is compatible with a rate of about 0.5 % or with impossibility.
2. Whether the pair minima can be chained: the start state of a transition is a cell key only, the velocity and the platform's phase are
   not recorded for most of them, and the projectile breaks (9 -> 0 in 2, 0 -> 3 in 11, 3 -> 2 in 12) depend on where the projectile was fired.
3. The true per-dispatch break rates under any new selection (every rate here is a two-run average over cells chosen by the old weights).
4. The hold lengths the explorer drew (runs of identical words merge equal consecutive draws).
5. The states of the arrivals the archive dropped as slower or equal (run 1: 451,681 later arrivals; run 2: 509,661), among them any that
   would cross from a fast right side.
6. Whether the wall-top landing tolerance admits a landing from a flight that leaves the platform earlier (the moving platform's phase).
7. Whether the two early-left-target orders of run 2 (a crossing at 879 with target 6 broken before 3) can be completed: 226 dispatches, 2
   breaks, one extension to level 8 at 1,527.

## 8. Open questions for the owner

1. **First night of November.** Options: (a) run 3 with the per-group budget, rank draw and anchors (options 1 + 2); (b) run 3 exactly as the
   run-2 record proposed (per-group share only); (c) the right-side arm first. Recommendation: (a): it reuses the archive and the tool, tests
   the one mechanism every chain here points at, and keeps the right-side arm for nights 2 and 3.
2. **Budget unit.** Options: (a) per (level, mask) group; (b) per order prefix; (c) both. Recommendation: (a) in stage 1 (already in the key),
   (c) in stage 2.
3. **Within-group draw.** Options: (a) rank of arrival tick with a novelty floor; (b) the current product of terms with a steeper pace
   exponent; (c) the learned prior if the offline study supports it. Recommendation: (a); (c) only as a reading in November.
4. **Anchor decay.** Options: (a) share halves per burst without a new earliest arrival in the group, recovers on one; (b) a fixed per-anchor
   dispatch cap (the frontier's retirement, which exhausted the deep states in four rounds); Recommendation: (a).
5. **Seeds for the right-side arm.** Options: (a) the frontier's and probe's earliest arrivals per order at levels 5 to 7, one per key, every
   class; (b) grounded and A2 arrivals only; (c) the fastest arrival per level regardless of order. Recommendation: (a) with anchors per
   (group, class), because the only crossings so far started grounded or A2 and the analysis cannot say the helpless ones are dead.
6. **State-aware representatives.** Options: (a) multi-representative cells with a generic sub-key, after stage 2; (b) a new cell contract now;
   (c) never. Recommendation: (a).
7. **Offline cell-prior study.** Options: (a) do it in week 1, reading only; (b) skip. Recommendation: (a): it costs no native tick and tells
   whether the per-cell signals the crossing study found generalise from run 1 to run 2.
8. **The 1,245 result.** Options: (a) register it now through the registered pipeline in its own session; (b) register at the line's first
   checkpoint; (c) leave it a lab result. Recommendation: (b), unless the owner wants the record before November.
9. **Throughput work.** Options: (a) Python-side levers (async close, second standby) in week 1; (b) a native batched prefix; (c) nothing until
   a night is budget-limited. Recommendation: (c) for native work, (a) only if it fits beside stage 0 without touching the launch path.
10. **Claims policy for run 3.** Options: (a) replay only when faster than the best, dedup by words digest (run 2's rule); (b) replay every claim.
    Recommendation: (a).
11. **Plateau rule.** Options: (a) three nights with no faster verified clear and no new earliest arrival per group; (b) the same on the clear
    only. Recommendation: (a): the earliest arrivals are the line's leading indicator (run 2's 974 and 1,051 preceded the 1,245 by hours).

## Appendix. Working files (Git-ignored, `logs/frs_strategy/`)

| file | content |
| --- | --- |
| `scripts/s0_common.py` | read-only loader (lab paths, trace reader, classifier import from `rl/m8_rd_cells`) |
| `scripts/s1_anatomy.py`, `s1_anatomy.json` | section 1: per-segment classes, away and still ticks of the 1,245, 1,261, 1,352, 1,429, 1,885 |
| `scripts/s1b_timeline.py`, `s1b_1245.txt`, `s1b_1429.txt`, `s1b_1885.txt` | section 1: constant-status timelines with positions and the next target |
| `scripts/s2_lineage.py`, `s2_pairs.json`, `s2_pairs_by_class.json`, `s2_orders.json`, `s2_clear_histories.json`, `s2_stdout.txt` | sections 2, 3, 5: every break history rebuilt and validated; pair bests; order statistics and effort |
| `scripts/s3_composite.py`, `s3_composite.json`, `s3_stdout.txt` | sections 2, 3: composites per order, the clears against the pair bests, the unconstrained minimum |
| `scripts/s4_explorer.py`, `s4_explorer.json`, `s4_stdout.txt` | section 5: words behind the fastest lab transitions; the chains of the four clears |
| `scripts/s5_movement.py`, `s5_movement.json`, `s5_stdout.txt` | section 4: per-class extremes, windows, per-clear time in each class |
| `scripts/s6_search.py`, `s6_search.json`, `s6_stdout.txt`; `scripts/s6b_lead.py`, `s6b_stdout.txt` | section 5: effort by (level, mask), earliest arrivals and their dispatches, replacements, effort by pace |
| `scripts/s7_orders_view.py` | section 3: deep prefixes, early-left-target orders, barely tried prefixes |
