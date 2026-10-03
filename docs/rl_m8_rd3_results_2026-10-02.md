# M8-rd3 results (2026-10-02)

**Registered outcome (rule `m8_rd3_rule_v1`, digest `fae00396494b8e966dc84e9a1e54af140143a52a6e624e14110dadaed76e0279`): NO_NEW_MILESTONE.**

No verified milestone above the wall-top landing (no qualified crossing, no left-target break, no clear) and no verified trajectory with 8 or more targets: the highest milestone of rd3 is *none* (rd2's wall-top landing
stays the highest over the sessions), the maximum number of targets verified from tick 0 is **7** (an exact replay of 1,339 canonical words). The stop conditions **S2** (no verified qualified crossing after three sessions) and **S4**
(the dilution verdict is DILUTION_PERSISTS on a NO_NEW_MILESTONE) are triggered, as the rule records; the line stops for review and nothing further was started.

**Scope.** One session, one set of keyed draws, no control arm: a second continuation of archive `m8_rd_a1` (rd1 and rd2 as closed) under the unchanged `m8_rd_select_v2`. It is not a policy result, not a learning result and not a
comparison of v2 with v1.

Design: `docs/rl_m8_rd3_decisions_2026-10-02.md`. Preparation record: `docs/rl_m8_rd3_implementation.md`. Approval: `docs/rl_m8_rd3_approval.json`. Run directory: `runs/m8_rd_rd3/` (Git-ignored, 77 files, 114.0 MB). rd1's tree `runs/m8_rd/`
and rd2's tree `runs/m8_rd_rd2/` are unchanged.

## 1. What was run

| item | value |
| --- | --- |
| preparation | 67 / 67 unit tests and the production-count synthetic end-to-end passed three consecutive times with no change in between (hard world; the easy world once); the preflight without an approval refused for exactly one reason, the missing approval (`runs/m8_rd_rd3/launch/preflight_noapproval_before_approval.json`) |
| source snapshot | `D:\BattleShip_source_snapshots\2026-10-02_m8_rd3`, 120 files, `snapshot.json` sha256 `9d0005f232f493699eb9a88dcfd826b47f0be3c3303ce6a7a351c5246851a077`; tool verify PASS and a separate PowerShell re-hash (121 items, 0 bad, same `snapshot.json` hash) before the launch |
| approval | written from the freshly computed identity right after the snapshot (it names the snapshot's digest): `docs/rl_m8_rd3_approval.json`; the preflight (without the unit suite, for the record) passed with it; the `run` command then ran the full preflight, unit suite included, and passed it |
| launch | one detached `python -B -u -X utf8 rl/m8_rd3_session.py run` (pid 18076, 2026-10-02T23:47:31Z), exit without error; no retry, extension, repair or follow-on session. The first and only command passed its preflight |
| session | the session clock ran 3,157.5 s (52.6 min); the process ended at about 2026-10-03T00:46:37Z; no BattleShip process was left |
| executable | `BattleShip.exe` `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee`, unchanged; rd1's frozen runtime configuration read in place; flags as rd1 and rd2 (exploration: no render, no Raphnet, spatial; verification replays: all four diagnostics) |
| git head | `bde29cf`; no tracked file changed; `git status` shows only new untracked files (8 `rl/m8_rd3_*.py`, the decisions, implementation and approval records, and this record) |

## 2. Native ticks, returns and the replay fraction

| phase | native ticks | wall (session clock) | cap |
| --- | ---: | ---: | ---: |
| open: P1 (tick-0 record vs the archive's pin, two pinned traces, return self-test) | 6,208 | 25.4 s for the open phase | 70,000 ticks / 240 s |
| open: 16 identity returns | 17,742 | (included above) | (included above) |
| exploration | **5,170,886** (stopped by its 50-minute wall cap at 3,001 s; valid from 2,000,000) | 3,002.3 s | 6,000,000 ticks / 3,000 s |
| verification (4 claim replays, 16 close identity returns) | 23,336 | 14.9 s | 400,000 ticks / 360 s |
| **total** | **5,218,172** | **3,157.5 s (52.6 min)** | 3,600 s |

- **Returns: 4,194** (dispatches 4,194, ingested 4,194; iterations 6,212..10,405, none reused). Every start was a standby promotion; **0 lifecycle failures, 0 aborted jobs, 0 cut jobs, 0 mismatches.** Throughput 1,723 ticks/s aggregate (rd2: 1,663; rd1: 1,560).
- **Replay fraction: 4,687,034 of 5,170,886 exploration ticks (90.6 %) were prefix replay**; new exploration 483,852 ticks (rd2 90.6 % and 466,895). New cells per return 1.74 (rd2 2.67, rd1 3.80); the archive grew from 19,062 to
  **26,371 cells** (10,406 bursts, 20,814 ledger events).

## 3. Milestones, each with its full-replay verification

| milestone | result |
| --- | --- |
| wall-top landing | not re-claimed in rd3 (rd2's stands; decisions I15). Four bursts stood on floor line 0 after their prefix (`wall_top_sightings.jsonl`: three continuations from the two wall-top cells, one from cell 18766, whose lineage passes through the wall-top landing); they are recorded and never claimed |
| qualified crossing (`btt_qualified_crossing_v1`) | none |
| left target (ids 1, 6, 8) | none |
| clear | none |
| maximum targets, verified | **7** (candidate 21, iteration 7,524, 1,339 words, native action digest `e0e948f8c54666def3d30ecda3ba3530388bb59662b1cdf3c250fe92595e1eca`, exact replay with all four diagnostics) = rd1's and rd2's 7; no eighth target |

The four exact claim replays (all `exact`, `problems: []`; 27 candidates were registered, the rule's pools needed these four): the 7-target route above, and three **left-region candidates** (cids 12, 24, 26) that each had a live tick at x < -2,100 and were
replayed because that is the engine's pool for crossings and left targets. None qualifies:

| candidate | words | what the exact replay shows (facts of the trace, not a claim about method) |
| --- | ---: | --- |
| 12 (lower-precision approach by the engine's route rule) | 1,648 | targets 6; the first live tick at x < -2,100 is at tick 1,585 at (-2,108.3, -5,883.0), far below the stage, in an up-B status; no landing; native failure (game status 5) at tick 1,648 at (-1,786.4, -9,606.1) with 4 targets left |
| 24 (upper-moving-platform approach by the engine's route rule) | 1,864 | targets 7; stands on floor line 0 (the wall top) for 34 ticks, 1,694..1,727 (rd2's landing is in its prefix); the first live tick at x < -2,100 is at tick 1,765 at (-2,122.0, 4,098.5), airborne (status 209); at the end of the burst (tick 1,864) it is airborne at (-4,533.6, 599.3), 3 targets left; no landing |
| 26 (same approach) | 1,948 | same prefix and same first tick at x < -2,100; leftmost point (-5,125.0, -2,498.7) at tick 1,905; at the end (tick 1,948) airborne and falling at (-4,865.4, -5,508.7), 3 targets left; no landing |

By the criterion (an entry over the wall followed by a landing) all three are unqualified left entries: no grounded tick left of the wall. The claims record (`sessions/rd3/verification.json`) holds `m = 0`, `max_targets = 7`, `satisfied: {L0: true, crossing: false, left_target: false, clear: false}` (the L0 flag
reads the whole trajectory, wall-top prefix included, and carries no claim).

## 4. The registered diagnostics against the references

rd2's and rd1's values are recomputed by the same functions from the archives (they reproduce rd2's stored report field for field: a unit test). rd3 = its 4,194 dispatches.

| # | measure | rd3 | rd2 | rd1 |
| ---: | --- | --- | --- | --- |
| D1 | start regions: below the floor / beside / on-stage low / on-stage high; left of the wall (x < -2,100) | 946 (22.56 %) / 740 (17.64 %) / 1,611 (38.41 %) / 897 (21.39 %); **1** | 829 (20.54 %) / 622 (15.41 %) / 1,772 (43.89 %) / 814 (20.16 %); 0 | 456 (20.97 %) / 180 (8.28 %) / 1,274 (58.57 %) / 265 (12.18 %); 0 |
| D2 | step contact: dispatches; cells | 29 (0.69 %); 84 | 31 (0.77 %); 56 | 12 (0.55 %); 32 |
| D3 | dispatches by class G / A2 / A1 / A0; A2/A1 on stage y >= 0; A2 y >= 0 | 185 (4.41 %) / 1,804 (43.01 %) / 1,468 (35.00 %) / 737 (17.57 %); 625 (14.90 %); 430 (10.25 %) | 190 (4.71 %) / 1,691 (41.89 %) / 1,472 (36.46 %) / 684 (16.94 %); 578 (14.32 %); 338 (8.37 %) | 96 / 408 / 764 / 907; 96; 30 |
| D4 | A2/A1 cells; on stage y >= 0 (v1-eligible); **launch-capable cells** and their dispatches; at x <= 600; highest A2 y | 16,296; 1,642; **614** and **345**; **115**; 4,856.9 | 11,874; 1,212; 509 and 263; 79; 4,820.5 | 4,406; 403; 14 and 2; 0; 909.6 |
| D4 | launch-capable cells created per 1,000 returns | **26.0 (109 cells in 4,194 returns)** | 122.6 (495 in 4,037) | 6.44 (14 in 2,175) |
| D5 | closest approach to the ledge corner (-1,200, 3,000): all classes / A2 and A1; best y at x <= -1,200 / <= -1,500; highest cell | **64.4** (A0 cell 24,689) / 296.1; 5,544.0 / 5,544.0; y 7,154.2 | 162.1 (A1) / 162.1; 5,544.0 / 5,544.0; y 6,356.9 | 1,017.0 (A0) / 2,124.8; 1,252.3 / 1,207.6; y 3,247.0 |
| D6 | fatal returns (a fall with no grounded live tick) by the exact runs | 599 / 4,194 = **14.28 %** | 516 / 4,037 = 12.78 % | 480 / 2,175 = 22.07 % |
| D7 | efficiency: prefix share; new exploration ticks; returns; new cells per return; throughput; selection time | 90.64 %; 483,852; 4,194; 1.74; 1,723 ticks/s; 81.9 s | 90.65 %; 466,895; 4,037; 2.67; 1,663 ticks/s; 52.3 s | 90.26 %; 237,209; 2,175; 3.80; 1,560 ticks/s; n/a |
| D8 | v2 mechanism: eligible v1 -> excluded (descent / bound / union) -> eligible v2, at the open and the close | open 16,221 -> 2,992 / 2,087 / 4,427 -> 11,794; close 22,336 -> 3,734 / 2,666 / 5,726 -> 16,610 | open 6,960 -> 1,905 / 1,309 / 2,454 -> 4,506; close = rd3's open | n/a |
| D8 | counters of the session: descent-doom revivals; doomed incumbents replaced; newly doomed; bound violations | 4,160; 4,002; 6,024; **0** | 4,312; 4,002; 6,859; 0 | |
| D8 | dispatches by level 0..7 (share of level 7) | 202 / 192 / 243 / 301 / 411 / 541 / 767 / 1,537 (36.6 %) | 181 / 224 / 236 / 258 / 379 / 465 / 751 / 1,543 (38.2 %) | 52 / 84 / 132 / 195 / 370 / 370 / 664 / 308 (14.2 %) |
| D9 | maximum targets broken, verified | 7 | 7 | 7 |

**The new readings (reported only, never read by the selection):**

| reading | rd3 (at its close) | rd2's close |
| --- | --- | --- |
| wall-top cells (G on floor line 0); dispatches from them | 2 (ids 18,318 and 18,767, both L = 1,694); **3** of 4,194 dispatches (0.072 %) | 2; 0 of 4,037 |
| selection probability of the wall-top cells at the open (analytic, per dispatch) | 0.0684 % (18,318: 0.0356 %; 18,767: 0.0329 %), about 2.9 dispatches expected in 4,194; 3 occurred | |
| cells left of the wall face: stored x < -1,650 / < -1,800 / < -2,100 | **80 / 71 / 54** | 14 / 8 / 0 |
| leftmost stored position | cell 26,243 (A1) at (-5,123.8, -2,428.7) | cell 18,319 at x -1,876.2 |
| closest approach to floor line 3 (x -3,900..-2,700 at y -1,950), all classes / A2 and A1 | 1,050.8 (A1 cell 15,284 at (-1,650.0, -1,909.0)) / 1,050.8 | 1,051.1 / 1,054.1 |

The 54 cells at x < -2,100 were all created in rd3 (47 A1, 7 A0), all with 7 targets broken and exactly the three left targets (ids 1, 6, 8; 3 targets left, plus the moving target 2 in 7 of them): the first agent-generated archive states left of the wall. The highest, cell 25,304 at
(-2,122.0, 4,098.5, L = 1,765), and its successors (-2,358.4, 3,892.1), (-2,415.8, 3,816.5), ... lie on the flight of candidates 24 and 26 above. Three bursts produced them (candidates 12, 24, 26). None of the 54 is grounded, so none is a landing.

**The up-B start heights (measured in rd2 and rd3 only):** 600 resource transitions A2/A1 -> A0 in rd3 (rd2: 541); highest start y **5,796.9** (x 2,634.3; rd2 4,542.7); **50** starts at or above y 1,639 (rd2: 29); the leftmost of them at x -1,767.1 (y 3,231.1; rd2 -740.2).
Exact ground runs in rd3's bursts: 2,334 runs in 2,027 of 4,194 bursts, 107,235 grounded ticks.

## 5. Stop conditions and flags

| condition | status |
| --- | --- |
| `BOUND_VIOLATION` | none (0) |
| S1 M8-rd1 NULL | not triggered (rd1 PASS) |
| **S2 no verified qualified crossing after three sessions** (explicit evaluation at rd3's close; rd3 is the third session) | **TRIGGERED**: rd1 m = 0 (`sessions/rd1/rule.json`, both arms), rd2 m = 1 (`sessions/rd2/rule.json`, PROGRESS_WALL_TOP), rd3 m = 0; rd3's claims were verified and rd3 is not INVALID |
| S3 median L of the top level's eligible cells > 3,000 before a left target | not triggered (median 1,574) |
| **S4 NO_NEW_MILESTONE with DILUTION_PERSISTS** | **TRIGGERED**: below-floor dispatches 946 / 4,194 = 22.6 % against the 10.5 % limit; fatal returns 599 / 4,194 = 14.3 % against 11.0 % |
| S5 `BOUND_VIOLATION` | not triggered |
| S6 NO_NEW_MILESTONE with DILUTION_REDUCED and launch-capable cells created per 1,000 returns not above rd1's | not applicable (the verdict is PERSISTS; the rate 26.0 is above rd1's 6.44 and below rd2's 122.6) |
| S7 INVALID / INCOMPLETE | not triggered |

The rule's `next` is "stop conditions ['S2', 'S4'] stop the line for review". These are the registered consequences; they are reported here and nothing was acted on.

## 6. Integrity

- **P1 passed**: the tick-0 record of two promoted processes equals the archive's `pin_tick0` (`2817d8cf3494...`, host frames 64 and 64); the two pinned Track 1 traces reproduced word for word; the return self-test returned three cells and refused a corrupted end record (6,208 ticks).
- **Open identity replays: 16 of 16 returned exactly** (the shortest cells of the top three levels, the four highest-weight v2-eligible cells, four keyed-random launch-capable or A2-high cells, five keyed-random v2-eligible cells; 17,742 ticks).
  **Close identity replays: 16 of 16** (the wall-top cell, a left-of-wall cell, the shortest cells of levels 7, 6 and 5, then keyed-random cells).
- **Every return** (4,194) passed the four checks (tick-0 record, per-tick consumed and input ticks, end record, chain digest); 0 mismatches; no consumed-tick violation.
- **Close checks** (`close.json`): the three-part ledger rebuild reproduces all 26,371 cells exactly (rd1's part under v1, rd2's and rd3's under v2 with their own draws), every prefix reconstructs, the derived flags equal the first-principles recomputation; **the prefix chain holds** (rd2's files begin with rd1's exact bytes, rd3's with rd2's closing
  bytes); **both earlier trees are unchanged** (R1 at the close); the write guard recorded no violation. `verify-run`: `ok: true`, recomputed outcome NO_NEW_MILESTONE, no problems.
- Executable and `.o2r` pins unchanged (re-hashed before every launch); controller-rule CVars absent; no leftover BattleShip process; no RNG seed was inspected, logged, controlled, compared or hashed; no hand-written route or waypoint exists; the archive's trajectories are agent-generated from tick 0; no fixture, recording or TAS file was read.

## 7. Resources against the caps

| resource | peak / minimum observed | cap |
| --- | ---: | ---: |
| main process private memory (sampler / session clock) | 848.5 MB / 618.1 MB | 3,072 MB |
| whole tree private memory | 4,289.8 MB | 9,216 MB |
| whole tree working set | 1,596.0 MB | 4,096 MB |
| BattleShip processes | 10 | 10 |
| system available memory (minimum) | 6,032.3 MB | 1,024 MB minimum |
| system free commit (minimum) | 12,564.1 MB | 2,048 MB minimum |
| exploration native ticks | 5,170,886 | 6,000,000 |
| open ticks / verification ticks | 23,950 / 23,336 | 70,000 / 400,000 |
| session clock | 3,157.5 s | 3,600 s |
| exploration wall | 3,002.3 s (the cap bound) | 3,000 s |

617 samples at 5 s, no breach. The preparation's pessimistic projection (3,415 s) and expected 54 min bracket the measured 52.6 min.

## 8. Evidence and backup

| step | command | outcome |
| --- | --- | --- |
| launch logs | copied into `runs/m8_rd_rd3/launch/` before the backup (the run's stdout and stderr, the launch record, the preflights, the snapshot records); the post-run `verify-run`, `report` and the factual analysis into `runs/m8_rd_rd3/derived/` | 10 + 3 files |
| backup | `python rl/tools/runs_backup.py backup --source runs/m8_rd_rd3 --dest D:\BattleShip_runs_backup\2026-10-02_incr_m8_rd3` | copy 77 / 77, verification PASS, 114,026,700 bytes, 0 hash mismatches; manifest sha256 `b6e13ecbc1ef9a76fee105de90fbf09072ae2b450f9f626542f6df355e35f324` |
| separate verify | `python rl/tools/runs_backup.py verify --source runs/m8_rd_rd3 --dest ...` | PASS, 77 / 77, 0 mismatches |
| independent re-hash | PowerShell `Get-FileHash` over every source file against its copy (`logs/m8_rd3_prep/tools/independent_increment_check.ps1`) | rd3: checked 77, bad 0, **PASS** |
| the earlier trees | the same script on `runs/m8_rd` (against `2026-10-02_incr_m8_rd1`) and `runs/m8_rd_rd2` (against `2026-10-02_incr_m8_rd2`), before the run and after it; the tool's R1 after the run | 166 / 166 and 62 / 62, bad 0, **PASS** (before and after) |
| total coverage | `m7u_gate.combined_coverage()` | **409,382 `runs/` files, 0 uncovered**, over the base and the eight increments including this one |

Nothing was written into `runs/m8_rd_rd3/` after the backup. The run's console logs and the preparation logs also live under `logs/m8_rd3_run/` and `logs/m8_rd3_prep/` (Git-ignored).

## 9. What this does and does not say

- It says the two-level continuation works end to end on the real game (two-level resume, closing overlay, three-part ledger, rd3's keyed draws, exact returns, verification, close audits, backup) with every integrity check clean, and that **under the registered rule rd3 found nothing new**: no milestone above the wall-top landing and no
  eighth target in 4,194 further returns.
- **A finding of the preparation mattered in the run.** Three of the 4,194 dispatches started from a wall-top cell and each burst was on floor line 0 at its first tick. The frozen claims engine would have registered an `l0` candidate from such a burst and judged its replay inexact (the first line-0 tick of the whole
  trajectory lies in the prefix), which stops a session as INVALID. rd3 removed that label before committing the job (decisions I15) and recorded the four sightings; the same mechanism is reproduced by a test with the label injected (INVALID without the fix, complete with it). That statement about the real session is an inference from the mechanism the test demonstrates,
  not an observed failure: the unfixed code never ran on the real game.
- **Not progress by the rule, but in the diagnostics:** 54 archive cells exist left of the wall (none before), all airborne, from three bursts whose replays are exact; two of those trajectories jump off the wall top at about (-2,122, 4,098) and are still in the air, 3 targets left, when their bursts end. No grounded tick left of the wall exists, so by `btt_qualified_crossing_v1` nothing qualifies. The closest approach to the left floor did not move (1,050.8 against 1,051.1): the new cells are
  above and beyond it, not on it.
- It does **not** say v2 caused any of this (no control arm), and it is not a policy result: a verified route does not show that a policy can learn it.
- The dilution measures did not fall (22.6 % below-floor starts; rd2 20.5 %; limit 10.5 %), which with the NO_NEW_MILESTONE outcome triggers S4 as registered. The wall-top cells carried 0.07 % of the selection mass and received 3 dispatches.

## 10. Gotchas

- The preparation's independent review found no blocker; the wall-top hazard was found in the follow-up to its first finding and is the one behavioural difference from rd2 (decisions I15).
- The `rule.json` reports `highest_milestone: none` for rd3 and `highest_milestone_over_sessions: L0`, by design: the wall-top landing is rd2's.
- `satisfied.L0: true` in `verification.json` reads the whole trajectory and is not a claim.
