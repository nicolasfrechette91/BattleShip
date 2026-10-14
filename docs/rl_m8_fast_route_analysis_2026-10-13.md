# M8 fast-route archive analysis (2026-10-13)

## 0. Scope, sources and method

**Status: offline, read-only analysis; zero native ticks.** No game, suite, preflight or launcher was started. No tracked file was modified; nothing
under `runs/` or on D: was written. The only new files are this record and the Git-ignored working files under `logs/m8_fast_analysis/`
(scripts in `scripts/`, outputs beside them). Checkout `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, branch `main`, HEAD = `origin/main`
= `0134679`, clean with nothing staged at the start. This record proposes no design; it reports observations for the fast-route discovery design
session. The TAS, every human recording, the owner's own run and any external record time were not read or used.

**Data.** The cumulative ledger of archive `m8_rd_a1` as closed by sd2 (`runs/m8_rd_sd2/archive/`): 21,323 bursts (rd1 to sd2), 49,928 cells,
21,326 dispatch and 21,326 ingest events (3 empty ingests). Its per-session burst counts equal each earlier tree's own closing archive (2,175 / 6,212 /
10,406 / 13,886 / 17,554 / 21,323). The three record routes rebuilt from the ledger reproduce their registered native action digests (rd4 cid 239
2,315; sd1 cid 901 2,086; sd2 cid 1360 1,885). Replaying the ledger's own new / replace / keep decisions from the stored reach rows reproduces all
49,927 non-root closing cells (L and representative burst), 0 mismatches (`s0_sanity.json`, `a8_bookkeeping.json`). Per-tick data come from the
24 distinct replay traces of the agent's own trajectories under `runs/m8_rd*/routes/` and `runs/m8_rd*/sessions/*/verification/`.

**Definitions.** Level = targets broken. An arrival at a level is the first live input tick showing the new target mask (equal to the trace's
`break_input_tick`). "Record pace" = the 1,885 route's break ticks 43, 120, 399, 609, 880, 982, 1,339, 1,776, 1,832, 1,885. Targets are the native
ids 0 to 9: 0 (-1,350, -2,250), 4 (0, -900), 9 (1,650, -2,250), 5 (0, 300), 3 (4,950, -1,800), 7 (0, 1,650), 2 (moving; broken at 2,700, 3,433
in the 1,885 route), 6 (-3,300, 3,300), 8 (-3,300, 600), 1 (-3,450, -2,550). Floor lines the routes stood on: 4 bottom floor (y -2,550), 2 right
platform (y -1,500, x 1,200 to 1,950), 1 small right platform (y -450, x about 2,740), 19 moving platform (x 2,388 to 3,123, y 2,036 to 2,790),
0 wall top (x about -1,730, y 3,000), 3 left floor (y -1,950, x -3,887 to -2,879). "Left of the wall" is x < -2,100 (the cell contract's
boundary). Exploration ticks are job ticks (prefix replay plus burst) from the ingest events.

**Archive resolution (limits every item below).** Per burst the ledger stores the tick and cell of the first reach of each distinct cell key
`(floor(x/300), floor(y/300), resource class, live-target mask, floor line)`; the exact 17-field state only for reaches that created or replaced a
cell (126,561 states). It stores no per-tick motion outside the 24 traces and no explorer hold lengths.

## 1. Time budget of the record routes

Ticks per segment between target breaks (full data `logs/m8_fast_analysis/a1_routes.json`, movement classes `a1b_moves.json`).

| seg | target | rd4 2,315 | sd1 2,086 | sd2 1,885 | rd4 to sd2 | where (the 1,885 route) |
| ---: | --- | ---: | ---: | ---: | ---: | --- |
| 1 | 0 | 43 | 43 | 43 | 0 | start on the bottom floor, airborne left |
| 2 | 4 | 77 | 77 | 77 | 0 | bottom floor 58 to 113, roll, up-B |
| 3 | 9 | 279 | 279 | 279 | 0 | three stops on the bottom floor (174 to 208, 269 to 302, 375 to 399) |
| 4 | 5 | 210 | 210 | 210 | 0 | bottom floor, right platform 508 to 535, two up-Bs |
| 5 | 3 | 271 | 271 | 271 | 0 | right platform 753 to 880; target 3 broken by a fireball from 3,447 units (the only break with a projectile alive) |
| 6 | 7 | 102 | 102 | 102 | 0 | right platform 881 to 906, roll, up-B |
| 7 | 2 | 357 | 357 | 357 | 0 | down to the bottom floor 1,061 to 1,133 (73 ticks grounded), right platform, small platform, up-B at 1,330 |
| 8 | 6 | 499 | 499 | **437** | -62 | moving platform 1,369 to 1,396 and 1,473 to 1,519; 175-tick flight (up to y 5,556) to the wall top at 1,694; wall top to 1,721; then 117 ticks (rd4, sd1) or **55** (sd2) to target 6 |
| 9 | 8 | 228 | 60 | **56** | -172 | rd4 landed on the left floor; sd1 and sd2 broke it falling |
| 10 | 1 | 249 | 188 | **53** | -196 | rd4 and sd1 landed on the left floor; sd2 a fast fall past the floor's left edge |
| | **total** | 2,315 | 2,086 | 1,885 | -430 | |

- **Shared prefixes (exact words):** rd4 and sd1 share 1,881 ticks; sd2 shares 1,723 ticks with each. All three have the same break order
  (0, 4, 9, 5, 3, 7, 2, 6, 8, 1), the same wall-top landing (1,694) and the same first left-of-wall tick region (1,739, 1,739, 1,734).
- **What changed:** every one of the 430 ticks gained since rd4 lies after tick 1,721 (leaving the wall top). Ticks 0 to 1,339 (seven targets,
  71 % of the 1,885 route) and the crossing from target 2 to the wall-top landing (1,339 to 1,694, 355 ticks) are unchanged since rd1 and rd2.
- **How the 1,885 route spends its time:** 547 ticks grounded (29 %, all before 1,722), 194 in landing lag, 147 helpless, 52 shielding, 52 idle,
  43 in jump squat; 10 up-B starts, 4 rolls, 1 fireball.

## 2. Fastest arrivals across the whole archive

Fastest arrival per level over every reach in the ledger (kept, replaced and doomed reaches included; every row below is also the fastest
reach outside the 60-tick fall window). Full per-mask list (51 masks): `logs/m8_fast_analysis/a2_fastest_arrivals.json`.

| level | record (1,885) | fastest anywhere | its break order | made in | on the record route | fastest with the record's target set | masks reached |
| ---: | ---: | ---: | --- | --- | --- | --- | ---: |
| 1 | 43 | **26** | 4 | rd1 | no | 43 (rd1, on route) | 6 |
| 2 | 120 | **91** | 4, 0 | rd2 | no | 91 (rd2) | 9 |
| 3 | 399 | **152** | 0, 4, 5 | rd4 | no | 180 (rd4) | 11 |
| 4 | 609 | **254** | 0, 9, 4, 5 | rd2 | no | 254 (rd2) | 9 |
| 5 | 880 | **433** | 9, 4, 5, 0, 7 | sd1 | no | 799 (rd4) | 6 |
| 6 | 982 | **871** | 0, 4, 5, 7, 3, 9 | sd2 | no | 871 (sd2) | 2 |
| 7 | 1,339 | **1,237** | 0, 4, 5, 7, 9, 3, 2 | sd1 | no | 1,237 (sd1) | 1 |
| 8 | 1,776 | 1,776 | record order | sd1 | yes | 1,776 | 3 |
| 9 | 1,832 | 1,832 | record order | sd2 | tie (two bursts at 1,832; the record's is the second) | 1,832 | 3 |
| 10 | 1,885 | 1,885 | record order | sd2 | yes | 1,885 | 1 |

First arrivals: levels 1 to 7 in rd1 (level 7 at 1,355); levels 8, 9, 10 in rd4 (1,838, 2,066, 2,326).

**Observations.** At every level from 1 to 7 the archive holds an arrival ahead of the record, by 17, 29, 247, 355, 447, 111 and 102 ticks, and
none of them lies on the record route; all seven use break orders other than the record's. At levels 8 to 10 the fastest arrival is the record's
own (the archive has nothing faster there). Most of the fastest right-side arrivals were made in rd1 to rd4; levels 5 to 7's in sd1 and sd2.

## 3. Target orders

Distinct break orders seen (as prefixes; full list with fastest tick, sessions and break events: `logs/m8_fast_analysis/a3_target_orders.json`,
details `a3b_details.json`).

| level | distinct orders | target sets | orders ahead of the record pace | fastest order (tick) | the record's own order: fastest (record) |
| ---: | ---: | ---: | ---: | --- | --- |
| 1 | 6 | 6 | 1 | 4 (26) | 43 (43) |
| 2 | 15 | 9 | 3 | 4, 0 (91) | 120 (120) |
| 3 | 26 | 11 | 16 | 0, 4, 5 (152) | **252** (399) |
| 4 | 25 | 9 | 21 | 0, 9, 4, 5 (254) | **501** (609) |
| 5 | 9 | 6 | 7 | 9, 4, 5, 0, 7 (433) | 880 (880) |
| 6 | 5 | 2 | 4 | 0, 4, 5, 7, 3, 9 (871) | 980 (982) |
| 7 | 3 | 1 | 1 | 0, 4, 5, 7, 9, 3, 2 (1,237) | 1,339 (1,339) |
| 8 | 3 | 3 | 0 | record (1,776) | 1,776 |
| 9 | 3 | 3 | 0 | record (1,832) | 1,832 |
| 10 | 1 | 1 | 0 | record (1,885) | 1,885 |

96 distinct order prefixes in all, 47 of them never extended. **Only one complete order exists.** Every trajectory that broke an eighth target
broke the seven right-side targets in exactly the record's order and broke target 2 (the seventh) at exactly tick 1,339, the rd2 trunk (5,328 of
5,328 level-8-or-deeper trajectories). Target 2 is the seventh break in every level-7 order seen; targets 6, 8 and 1 were never broken before all
seven right-side targets. The record order's seventh break (target 2 after 7) happened as a new event 6 times in all (rd1 2, rd2 1, rd3 3), never
after rd3.

**Fronts ahead of the record pace and what happened to them** (all orders at levels 5 to 7 whose fastest arrival leads by 60 ticks or more, and
the record order's own faster partials). "Dispatches" are dispatches from states at that level whose arrival there was ahead of the record (the
state itself may be later).

| order (level) | fastest (lead) | made | dispatches from ahead states (by session) | new cells | extended to | outcome |
| --- | --- | --- | --- | ---: | --- | --- |
| 0, 4, 9 (3, record order) | 252 (147) | rd2 | 69 | 4 | level 4 at 501 (lead 108) | all 69 ended by length; the level-4 front had 8 dispatches (0 new cells) and never reached level 5 (the record order's fastest level 5 is the record's own 880) |
| 9, 4, 5, 0, 7 (5) | 433 (447) | sd1 | 5 (sd2 5) | 0 | no | 5 of 5 ended by length |
| 4, 0, 9, 3, 7 (5) | 494 (386) | sd2 | 0 | 0 | no | never dispatched |
| 0, 4, 5, 7, 9 (5) | 584 (296) | rd2 | 302 (rd2 30, rd3 80, rd4 41, sd1 66, sd2 85), plus 194 from deeper descendants | 1,181 | level 6 at 874 (lead 108), level 7 at 1,237 (lead 102) | none reached level 8; of 496 bursts 479 ended by length, 17 fell |
| 0, 4, 9, 3, 2 (5) | 629 (251) | sd1 | 7 (sd1 2, sd2 5) | 128 | no | |
| 0, 4, 5, 7, 3 (5) | 787 (93) | rd2 | 159 | 682 | level 6 at 871 (lead 111) | stopped at level 6 |
| 0, 4, 5, 7, 3, 9 (6) | 871 (111) | sd2 (first seen rd3) | 23 (rd3 1, rd4 6, sd1 8, sd2 8) | 0 | no | 23 of 23 ended by length |
| 0, 4, 5, 7, 9, 3 (6) | 874 (108) | sd2 (first seen rd3) | 177 (rd3 21, rd4 18, sd1 60, sd2 78) | 313 | level 7 at 1,237 | |
| 0, 4, 5, 7, 9, 3, 2 (7) | 1,237 (102) | sd1 | 17 (all sd2) | 0 (225 shortenings) | no | 16 ended by length, 1 fell; started near x 2,700 to 3,000, y 3,900 to 4,200; never reached x < 600 |

**Observations.** The archive explored many right-side orders (26 at level 3, 25 at level 4) and holds large leads at levels 3 to 7, but every lead
was lost before level 8: the ahead fronts either were never dispatched much (0 to 23 dispatches over up to five sessions) or were dispatched
without breaking the next target. Their bursts end by length (120 ticks without a break), not by falling; the few falls are into the bottom blast
zone below the right half (x about 2,400 to 6,000). No level-7 reach of any other order lies left of x -1,800 above y -4,500 (the 1,237 order's never left of x 600).

## 4. Anchoring on the record lineage

Each dispatch's start state against the final record route (1,885): **on** = the start state is the route's own prefix; **gap 0** = it shares the
route through the route's break at the start state's level, then deviates; **gap k** = it left the route k breaks before its own level; **other
order** = its break order differs from the record's (a subset of gap >= 1). Full data, also against the reference in force at each speed session's
open: `logs/m8_fast_analysis/a4_anchoring.json`, `a3b_details.json`.

| session | dispatches | on + gap 0 | gap 1 | gap >= 2 | other order | new cells: on + gap 0 / other order | shortenings: on + gap 0 | per-mask fastest-arrival improvements: n, on + gap 0 / other order |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |
| rd1 | 2,175 | 77 % | 21 % | 2 % | 6 % | 69 % / 10 % | 73 % | 27: 85 % / 15 % |
| rd2 | 4,037 | 55 % | 37 % | 8 % | 17 % | 55 % / 35 % | 51 % | 30: 47 % / 53 % |
| rd3 | 4,194 | 59 % | 26 % | 15 % | 26 % | 38 % / 59 % | 59 % | 16: 31 % / 69 % |
| rd4 | 3,480 | 26 % | 33 % | 41 % | 29 % | 16 % / 43 % | 22 % | 20: 25 % / 35 % |
| sd1 | 3,668 | 20 % | 32 % | 48 % | 40 % | 20 % / 70 % | 17 % | 17: 24 % / 59 % |
| sd2 | 3,769 | 28 % | 36 % | 36 % | 37 % | 21 % / 73 % | 34 % | 24: 38 % / 50 % |

Against the reference in force at the open: sd1 vs the 2,315 route on + gap 0 32 %, gap 1 53 %; sd2 vs the 2,086 route 20 %, gap 1 46 %.

**Observations.** From rd4 on, only a fifth to a quarter of dispatches start on or just after the record route at their level. In sd2 the levels
1 to 6 dispatches are mostly in other orders (1,100 of 1,315), level 8's mostly branch after the record's break at 1,776 (393 of 650), and level 9's
mostly reached level 9 in the record order by older paths (1,069 of 1,255, the pre-sd2 trunk). Other-order dispatches produced 70 to 73 % of the
speed sessions' new cells; no level-8 progress ever came from them (section 3).

## 5. Search efficiency over time

Per session (exploration ticks from the ingest events; full data with 500,000-tick windows: `logs/m8_fast_analysis/a5_efficiency.json`).

| session | ticks | new cells / M | shortenings / M | per-mask fastest-arrival improvements / M | new masks | per-level fastest improvements | first arrivals at a new level | new order prefixes / M | new cells / M, 1st half -> 2nd half | mask improvements / M, 1st -> 2nd half |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | --- |
| rd1 | 2.44 M | 3,393 | 1,663 | 11.1 | 18 | 15 | levels 1 to 7 | 8.2 | 4,126 -> 2,658 | 18.1 -> 4.1 |
| rd2 | 4.99 M | 2,163 | 2,302 | 6.0 | 10 | 9 | none | 5.0 | 2,510 -> 1,816 | 9.2 -> 2.8 |
| rd3 | 5.17 M | 1,414 | 2,253 | 3.1 | 5 | 1 | none | 3.1 | 1,353 -> 1,474 | 3.5 -> 2.7 |
| rd4 | 5.59 M | 1,957 | 1,871 | 3.6 | 9 | 7 | levels 8 to 10 | 2.9 | 2,504 -> 1,411 | 4.3 -> 2.9 |
| sd1 | 6.00 M | 1,116 | 1,975 | 2.8 | 5 | 5 | none | 1.7 | 1,200 -> 1,032 | 2.7 -> 3.0 |
| sd2 | 5.87 M | 1,008 | 2,699 | 4.1 | 5 | 9 | none | 1.5 | 1,067 -> 949 | 3.4 -> 4.8 |

Per-level fastest improvements at levels 6 to 10, in order (session: level old -> new): rd1 6 (982), 7 (1,355); rd2 7 1,355 -> 1,339; rd3 6 982
-> 931; rd4 8 (1,838), 9 (2,066) -> 1,898, 10 (2,326) -> 2,315; sd1 9 1,898 -> 1,897, 10 2,315 -> 2,086, 8 1,838 -> 1,776, 7 1,339 -> 1,237;
sd2 10 2,086 -> 2,053 -> 1,964 -> 1,929 -> 1,885, 9 1,897 -> 1,864 -> 1,838 -> 1,832, 6 931 -> 874 -> 871 (at 0.7 to 4.6 M of 5.9 M ticks).

**Observations.** New cells per million ticks fell by two thirds from rd1 to sd2 and within almost every session (rd3 the exception); new order
prefixes fell from 8.2 to 1.5 per million ticks. Shortenings did not fall and peaked in sd2 (2,699 per million, rising within the session):
the archive now refines more than it expands. Per-mask fastest-arrival improvements settled at 3 to 5 per million ticks and did not decay within
sd1 or sd2; sd2's level improvements were spread over its whole exploration and arrived up to 4.6 M ticks in, so sd2 had not saturated on its
own terms. Expansion (new cells, new orders) has saturated; refinement of known keys has not.

## 6. Explorer effectiveness

Per burst, by the start state's level (all six sessions; full tables also by session, start class and hold: `logs/m8_fast_analysis/a6_explorer.json`,
`a3b_details.json`).

| start level | bursts | broke a target | reached a new cell | shortened a cell | ended in a fall | new cells per burst |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 839 | 23.8 % | 44.5 % | 58.3 % | 9.8 % | 3.09 |
| 1 | 933 | 23.9 % | 57.8 % | 61.0 % | 5.3 % | 4.38 |
| 2 | 1,105 | 18.1 % | 53.4 % | 55.8 % | 5.3 % | 3.90 |
| 3 | 1,268 | 9.6 % | 56.2 % | 58.1 % | 8.9 % | 4.41 |
| 4 | 1,827 | 2.2 % | 49.5 % | 59.0 % | 15.1 % | 3.55 |
| 5 | 2,113 | 2.0 % | 43.2 % | 53.9 % | 12.7 % | 3.04 |
| 6 | 3,190 | 1.5 % | 29.2 % | 53.5 % | 20.8 % | 1.86 |
| 7 | 4,734 | **0.3 %** | 23.1 % | 56.0 % | 16.6 % | 1.32 |
| 8 | 1,832 | 5.5 % | 37.8 % | 72.2 % | 25.6 % | 2.44 |
| 9 | 3,482 | 0.6 % (20 clears) | 20.2 % | 54.5 % | **63.3 %** | 1.08 |
| all | 21,323 | 4.7 % | 34.9 % | 57.3 % | 23.3 % | 2.34 |

**Burst length and hold.** The explorer draws holds of 1, 2, 4, 8 or 16 ticks but does not record them; the mean run of identical words is used
as a proxy. Among full-length (120-word) bursts the break rate is flat across hold proxies (4.3 to 6.4 %; 1.4 to 2.0 % at levels 6 to 9), and so is
the new-cell rate (34 to 40 %). Bursts shorter than 120 words are almost all falls (4,885 of 4,905) or clears (20), so length is an outcome, not a
setting. **By start class:** a burst from a grounded state never fell; from A2 15 %, A1 30 %, A0 31 % (at level 9: 49 %, 70 %, 79 %).

**Observations.** A burst breaks a target about one time in four at levels 0 and 1, 1.5 to 2.2 % of the time at levels 4 to 6, and one time in 340 at level 7
(14 of 4,734: the crossing to target 6 is the hardest step in the archive). More than half of all bursts shorten some cell, which is the
replacement channel of section 8. At level 9 most bursts end in a fall, because the ending is a fall.

## 7. Movement observed in the agent's own trajectories

All values are observations from the agent's own trajectories, not bounds. Full data: `logs/m8_fast_analysis/a7_movement.json`.

**Speeds by movement class** (status classes of the checked-in table; 24 traces, about 44,800 live ticks; units per tick):

| class | ticks | max horizontal | max rise | max drop |
| --- | ---: | ---: | ---: | ---: |
| roll | 2,294 | **280.6** | 0 | 0 |
| special_hi (up-B) | 5,667 | 126.3 | **226.9** | 47.6 |
| airborne | 7,016 | 55.3 | 79.6 | 70.0 |
| attack_air | 14,257 | 34.7 | 79.6 | 70.0 |
| special_n (fireball) | 1,620 | 29.8 | 52.2 | 70.0 |
| landing_free | 651 | 29.8 | 0 | 50.2 |
| idle_ground | 1,238 | 24.0 | 0 | 8.4 |
| helpless | 3,378 | 17.8 | 0 | 70.0 |

In the 126,561 exact archive states: airborne horizontal velocity at most 30.0 (A2) and 29.8 (A1); fall speed never above 70.0; ground velocity up
to 54 carried into the air. Best displacement over a window, any trace: leftward 1,453 / 2,251 / 3,645 units in 30 / 60 / 120 ticks; rightward
1,266 / 1,675 / 2,104; upward 2,291 / 3,148 / 3,864.

**Consecutive target-to-target segments: the record's against the fastest occurrence of the same pair anywhere** (different trajectories and
states; these cannot be chained into one route):

| segment | record | fastest anywhere | session |
| --- | ---: | ---: | --- |
| start -> 0 | 43 | 43 | rd1 |
| 0 -> 4 | 77 | **16** | rd3 |
| 4 -> 9 | 279 | **49** | rd3 |
| 9 -> 5 | 210 | **132** | sd1 |
| 5 -> 3 | 271 | 271 | rd1 |
| 3 -> 7 | 102 | **36** | sd2 |
| 7 -> 2 | 357 | 357 | rd2 |
| 2 -> 6 | 437 | 437 | sd1 |
| 6 -> 8 | 56 | 56 | sd2 |
| 8 -> 1 | 53 | 53 | sd2 |

Other fast pairs seen: 9 -> 0 in 2 ticks, 0 -> 9 in 7, 9 -> 4 in 9, 4 -> 5 in 10, 5 -> 7 in 11, 0 -> 3 in 11, 3 -> 2 in 24 (all 39 pairs seen are in the file).

**The crossing:**

| milestone | 1,885 route | fastest anywhere |
| --- | ---: | --- |
| target 2 broken -> wall-top landing | 355 | 344 (sd1) |
| earliest wall-top landing (floor line 0) | 1,694 | 1,683 (sd1) |
| target 2 broken -> first x < -2,100 | 395 | 386 (rd4) |
| wall-top landing -> first x < -2,100 | 40 | 31 (rd4) |
| first x < -2,100 -> target 6 broken | 42 | 42 (sd1, the record's ancestor) |
| earliest x < -2,100 above y -4,500 | 1,734 | 1,725 (rd4); the only earlier entries (1,585 to 1,618, rd3) are falls through the blast zone below y -4,500 |
| earliest left-of-wall arrival at the left floor's height (y -3,000 to -1,500) | | 1,844 (sd1), always after the top crossing |

**Observations.** The fastest moves in the archive are rolls (up to 280 units in one tick) and up-B (up to 227 up and 126 sideways in its first
tick); the route uses 10 up-Bs and 4 rolls. In four of the record's seven right-side segments the same consecutive pair has been done faster
elsewhere, by 61, 230, 78 and 66 ticks; the crossing and the left side are already the fastest the archive has seen, within 9 to 11 ticks of the
best sub-legs. The left side has been reached only over the top (via the wall top); the earliest-arrival map by 1,500-unit area is in the file.

## 8. Cell bookkeeping

Outcome of every reach row in the ledger, replayed in ingestion order (409,527 rows; `logs/m8_fast_analysis/a8_bookkeeping.json`).

| outcome | rows | notes |
| --- | ---: | --- |
| new cell | 49,927 | |
| replacement by a strictly shorter reach | 65,351 | gain median 31 ticks (quartiles 10 / 77, max 789); 3,915 gained one tick |
| replacement of a doomed incumbent by a longer reach | 10,564 | the cell became slower (rd1: 60-tick fall window; from rd2: also descent-doom E5 and bound E6) |
| replacement of a doomed incumbent by an equal reach | 719 | |
| kept: slower arrival discarded | **226,205** | only tick and cell stored; the arrival's state is lost |
| kept: equal arrival discarded | 48,838 | |
| kept: faster arrival discarded because doomed | 7,923 | |

- **Does each cell keep its fastest arrival?** 44,860 of 49,927 cells (89.9 %) hold the fastest reach ever made at their key; 5,067 hold a slower
  representative (gap median 53 ticks, 90 % within 186, max 538) because the faster reach was doomed.
- **States merged by the key** (the 65,351 strict shortenings, new against old representative): horizontal velocity differs by >= 10 in 65 %
  (>= 30 in 27 %), vertical by >= 10 in 56 %, the horizontal direction reversed in 23 %, facing differs in 31 %, status differs in 67 %,
  position differs by >= 150 units in 45 %, jumps used differ in 0.8 %; 86 % differ materially (velocity, facing or jumps). The key holds no
  velocity, facing, status, exact position or break order, and A2 merges jumps used 0 and 1.
- **Orders merged by the key** (the mask, not the order, is in the key): 5,862 shortenings replaced a representative with one of a different
  break order (levels 2 to 7; none at 8 to 10). 1,186 of 6,222 level-7 cells and 1,090 of 6,021 level-6 cells now hold a representative whose
  order differs from the one that created the cell. Level-7 cells by current order: the record's 5,033 (the only order whose cells reach
  x < -2,100), (0, 4, 9, 5, 3, 2, 7) 964 (never left of x -1,800), the 1,237 front's 225 (never left of x 1,200).

**Observations.** Faster arrivals replace slower ones often (65,351 times, 1.3 per cell), and nine cells in ten hold their fastest arrival. But the
replaced and discarded arrivals usually carried different velocities, directions or statuses, and 226,205 slower arrivals were dropped without a
record of their state. Because the key ignores the order, the ahead-of-pace level-7 lineage lives in the same cells as the record trunk and
shows up as shortenings rather than new cells (its 17 dispatches: 0 new cells, 225 shortenings).

## 9. What cannot be determined from the archives

1. The state (velocity, facing, jumps, status, exact position) of the 226,205 discarded slower and 48,838 equal arrivals: the kept rows store only
   the tick and the cell. How many distinct, possibly useful states were dropped cannot be counted.
2. Motion between two first reaches of a key, outside the 24 traces: area-to-area transition times are measurable only at target breaks, at the
   first reach of a key, and in the traces. The 1,500-unit earliest-arrival map measures "from tick 0", not from area to area.
3. The explorer's hold lengths (not recorded; approximated by runs of identical words, which merge consecutive equal draws).
4. Why a burst did not break a target, and how the moving platform and target 2 move over time (only their break positions and the traces'
   per-tick groups exist); the hitbox geometry behind breaks at 22 to 751 units from Mario's reported position without a projectile.
5. Whether a segment can be done faster than observed: every number in section 7 is an observation of the agent's own play, not a bound; the
   pair segments of section 7 come from different trajectories and cannot be added into a route.
6. The rd2-onward doom flags (E5 descent-doom, E6 bound) were not re-derived here: the ledger's own actions were used as stored, so the reasons
   behind the 7,923 discarded faster arrivals and the 10,564 slower replacements are not split by doom kind.
7. Native ticks of the open and verification phases (not in the ledger); selection probabilities at dispatch time (not recomputed).

## 10. Most important findings for designing a faster search

1. **The right side and the crossing have never been improved.** Ticks 0 to 1,694 (seven targets and the crossing to the wall top, 90 % of the
   1,885 route) are rd1 and rd2 bursts; all 430 ticks gained since rd4 came after 1,721.
2. **The archive already holds much faster right-side partials, all in other orders,** ahead of the record by 247 to 447 ticks at levels 3 to 5
   and about 100 ticks at levels 6 and 7 (433 at level 5 against 880; 1,237 at level 7 against 1,339). The record's own order reached level 3 at
   252 (399) and level 4 at 501 (609). None of them reached level 8.
3. **Progress beyond level 7 has a single root.** Every trajectory that broke an eighth target broke target 2 at tick 1,339 on the rd2 trunk; only
   one complete break order exists; the left targets were always broken last, and the left side was reached only over the top.
4. **The bottleneck step is from level 7 to target 6**: 0.3 % of bursts from level 7 break a target. The ahead fronts stall there and one level
   earlier, ending by length rather than by falling, after very few dispatches (the 1,237 front: 17, all in sd2; the 871 front: 23 over four
   sessions).
5. **Faster segments exist piecewise:** in four of the seven right-side segments the same consecutive target pair has been done 61 to 230 ticks
   faster on other trajectories; the crossing and the left side are already the archive's fastest.
6. **Anchoring drifted away from the record route but not towards progress.** From rd4 on, 20 to 28 % of dispatches start on or just after the
   record route at their level and 37 to 40 % in other orders; the other orders produced 70 to 73 % of the speed sessions' new cells and none of
   the level-8 progress.
7. **Expansion has saturated, refinement has not.** New cells per million ticks fell from 3,393 to 1,008 and new orders from 8.2 to 1.5, while
   shortenings rose to 2,699 per million and fastest-arrival improvements held at 3 to 5 per million within sd2.
8. **The cell key hides what speed depends on.** Velocity, direction, status and break order are not in the key: 86 % of shortenings changed the
   state materially, 226,205 slower arrivals were dropped without their state, and the ahead level-7 lineage shares its cells with the record trunk.
9. **Observed movement capability is large compared with the route's pace:** rolls up to 280 units per tick, up-B up to 227 up, sustained
   leftward travel of 3,645 units in 120 ticks; the 1,885 route spends 547 ticks grounded and 194 in landing lag.
10. **The explorer's hold length shows no effect** on the break rate among full-length bursts.

## Appendix. Working files (Git-ignored, `logs/m8_fast_analysis/`)

| file | content |
| --- | --- |
| `scripts/common.py` | read-only loader (cells, bursts with words, events, route words, traces) |
| `scripts/s0_sanity.py`, `s0_sanity.json` | ledger completeness, per-session counts, route digests |
| `scripts/a1_routes.py`, `a1_routes.json`; `scripts/a1b_moves.py`, `a1b_moves.json` | item 1 |
| `scripts/a2_ledger.py`, `derived_bursts.pkl`, `a8_bookkeeping.json` | the ledger pass (orders, shared prefixes, arrivals, decisions replayed and audited) |
| `scripts/a3_items.py`, `a2_fastest_arrivals.json`, `a3_target_orders.json`, `a4_anchoring.json`, `a5_efficiency.json`, `a6_explorer.json`, `a3_stdout.txt` | items 2 to 6 |
| `scripts/a3b_details.py`, `a3b_details.json`, `a3b_stdout.txt` | deviation depth, record-order fronts, level-6/7 fronts, hold on full bursts, falls |
| `scripts/a7_movement.py`, `a7_movement.json`, `a7_stdout.txt` | item 7 |
| `scripts/a8_bookkeeping.py` | item 8 additions (gains, order swaps) |
