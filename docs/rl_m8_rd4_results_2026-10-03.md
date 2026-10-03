# M8-rd4 results (2026-10-03)

**Registered outcome (rule `m8_rd4_rule_v1`, digest `246813eebb7c75590e7548e5c1606687012042bb023bb01a932acdcdfd00bbe3`): PROGRESS. Highest milestone: CLEAR (level 4). All ten targets were broken in the real game by
agent-generated controller words, verified by exact replay from tick 0.**

Two distinct complete routes were verified (iteration 11206, 2,326 words; iteration 11286, 2,315 words); both pass through a **qualified crossing** (`btt_qualified_crossing_v1`, upper moving-platform route) and break the three
left-side targets (6, 8, 1). The line budget status is **MILESTONE_VERIFIED**: the line's requirement (a verified qualified crossing or higher) is met; rd5 may be proposed, authorised separately; **no rd5 was started.**
The mechanism check is reported (it **holds**) and, by decision 7, does not apply once a milestone is verified. The dilution verdict is DILUTION_PERSISTS (reported only). No stop condition, no BOUND_VIOLATION, no INVALID, no INCOMPLETE.

**Scope.** One session, one set of keyed draws, no control arm: the third continuation of archive `m8_rd_a1` (rd1, rd2 and rd3 as closed) under `m8_rd_select_v3` (`m8_rd_select_v2` with one change: the count term
`(1 + seen)^-1/2`). **Not a policy result, not a learning result, not a comparison of v3 with v2**: with a single session and no control arm this result cannot be attributed to v3 (section 9).

Design: `docs/rl_m8_rd4_decisions_2026-10-03.md`. Preparation record: `docs/rl_m8_rd4_implementation.md`. Approval: `docs/rl_m8_rd4_approval.json`. Run directory: `runs/m8_rd_rd4/` (Git-ignored, 93 files, 165.1 MB). rd1's, rd2's and
rd3's trees (`runs/m8_rd/`, `runs/m8_rd_rd2/`, `runs/m8_rd_rd3/`) are unchanged.

## 1. What was run

| item | value |
| --- | --- |
| preparation | 79 / 79 unit tests and the production-count synthetic end-to-end run passed three consecutive times with no change in between (fingerprint `1fd257a13b1d7ab2`); the dry-run preflight (unit suite skipped) refused for exactly one reason, the missing approval; the independent review's nine MINOR items and notes were dispositioned before the snapshot (implementation record, section 9a) |
| **pre-launch hazard, fixed in new files (flagged)** | **verification capacity**: every return from the inherited left-of-wall cells registers a `left` candidate, so the frozen plan could have spent its replay cap on descriptive candidates. In the session 1,459 `left` candidates were registered, 1,316 of them descriptive (no landing, no left-target break, no clear); the plan replayed the can-raise ones first and six descriptive ones at most. The fix changes no registered measure, threshold, selection or cell key (decisions record, section 3) |
| source snapshot | `D:\BattleShip_source_snapshots\2026-10-03_m8_rd4`, 112 files, `snapshot.json` sha256 `47e90c48a7d6e5d12706842325c265ced4e9c429f8548bbb739aeba500a30e07`; tool verify PASS and a separate PowerShell re-hash (113 items, 0 bad, same `snapshot.json` sha256) |
| approval | written from the freshly computed identity right after the snapshot (it names the snapshot's digest): `docs/rl_m8_rd4_approval.json`; the full preflight with it (including the 79-test unit suite) passed (`ok: true`, no problem) |
| launch | one detached `python -B -u -X utf8 rl/m8_rd4_session.py run` (pid 17492, 2026-10-03T18:32:46Z); the run's own preflight passed; no retry, extension, repair or follow-on session; no rd5. The launcher did not capture the exit code; the session's final records are `state.json` phase `done` and `rule.json`; stderr is empty |
| session | the session clock ran 3,296.0 s (54.9 min) of the 3,600 s hard cap (the process, with its own preflight before the clock, ended at about 19:42 UTC); no BattleShip process was left |
| executable | `BattleShip.exe` `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee`, unchanged; rd1's frozen runtime configuration read in place; flags as rd1, rd2 and rd3 |
| git head | `bdc7344`; no tracked file changed; `git status` shows only new untracked files (nine `rl/m8_rd4_*.py`, the decisions, implementation, approval and results records) |

## 2. Native ticks, returns and the replay fraction

| phase | native ticks | wall (session clock) | cap |
| --- | ---: | ---: | ---: |
| P1 (tick-0 record, two pinned traces, return self-test) | 6,208 | 26.7 s (with the open identity) | 240 s |
| open identity replays (16 / 16 returned exactly) | 15,000 | (in the open phase) | 70,000 ticks |
| exploration (arm T) | **5,590,384** (valid from 2,000,000) | 3,005.6 s | 3,000 s (+ 20 s grace); stop `wall_cap` |
| verification (9 claim replays + 16 close identity replays) | 40,787 | 35.6 s | 400,000 ticks / 360 s |
| **total native ticks** | **5,652,379** | | |

Exploration: **3,480 returns** (3,480 dispatches, 0 aborted, 0 lifecycle failures), 1,861 ticks/s; **93.6 % of the exploration ticks are prefix replay** (5,231,544) and 358,840 are new burst ticks. 13,886 bursts in the
archive at the close (10,406 inherited + 3,480 new), 37,312 cells (26,371 inherited + **10,941 new**), 27,775 ledger events. 1,486 candidates registered (arm T), 5 of them clear-kind.

## 3. Milestones, each with its full-replay verification

Every claim below is an exact replay from tick 0 in a fresh process: native action digest, every consumed tick, the break table and (for a clear) the four clear facts, checked by the frozen claims engine and read back by
`verify-run`. The canonical Track 1 words (0-71) are the replay truth; no hidden action. Saved routes (words, metadata, native trace) are in `runs/m8_rd_rd4/routes/{T_crossing,T_left_target,T_clear,T_t}`.

| milestone | candidate (iteration) | words | verification | short factual route description |
| --- | --- | ---: | --- | --- |
| **qualified crossing** (level 2) | cid 194 (11206) | 2,326 | exact; `first_qualified_entry` 1,738 (consumed tick); route identity `upper_moving_platform` ("approach surface is the moving platform") | the first 1,694 ticks are an inherited lineage: the seven targets right of the wall (breaks at input ticks 43, 120, 399, 609, 880, 982, 1,339), the moving platform (line 19) at ticks 1,369-1,397 and 1,473-1,520, an up-B from (-206.0, 4,194.4) at tick 1,625 (apex (-1,468.0, 5,555.6) at tick 1,647), then a grounded landing on the wall top (floor line 0) at tick 1,694, (-1,724.1, 3,000.0). The character is airborne again at tick 1,722 and is left of x = -2,100 at tick 1,739 ((-2,106.9, 3,851.4), airborne); it lands on the left floor (line 3) at tick 1,966, (-3,146.3, -1,950.0) |
| **left target** (level 3) | cid 16 (10819) | 1,843 | exact; target 6 at consumed tick 1,837 (8 targets, 2 remaining) | the same first 1,694 ticks; iteration 10794 starts from the inherited wall-top cell 18767 and iteration 10819 continues from the inherited cell 18319 (A2, L 1,723); target 6 is broken at input tick 1,838, airborne, at (-3,289.9, 3,280.2). Also present in both clear routes |
| **clear** (level 4) | cid 194 (11206) | 2,326 | exact; end record `outcome: clear`, `targets_broken: 10`, `completion_time_passed` 2,325, `completion_input_tick` 2,326; the four clear facts all true | after the crossing: left floor contact (line 3) 1,966-2,021 and 2,128-2,189; target 8 at tick 2,066 at (-3,643.3, 89.4); target 1 at tick 2,326 at (-3,736.2, -2,883.5) |
| clear (second route) | cid 239 (11286), kind `t`, 10 targets | 2,315 | exact; `completion_time_passed` 2,314, `completion_input_tick` 2,315 | shares its first 2,298 ticks with the route above and differs in the last 17 words (target 1 at tick 2,315 at (-3,511.6, -3,035.3)) |
| maximum targets | | | 10 (verified) | rd1, rd2 and rd3 each reached 7 |

**Lineage of the clearing route** (archive bursts, `start_rep` chain, read only): 42 bursts: 24 from rd1, 8 from rd2 (the last at iteration 6085 ends at L 1,694 with the wall-top landing), then **10 from rd4**: iteration 10794 (from the
inherited wall-top cell 18767, 29 words), 10819 (from cell 18319, 115 words), 10826, 10874, 10890, 10938, 11023, 11045, 11087 and 11206 (which ends in the clear, from a cell at L 2,213 created in rd4 at iteration 11087). Every burst is
an agent-generated explorer burst (keyed draws, Track 1 words); no human recording, TAS or hardcoded waypoint was used. The first left-target break was found by iteration 10819 (exploration tick 495,448, about 6 min into
the exploration) and the first clear by iteration 11206 (exploration tick 1,108,660, about 11 min); a first landing on the left floor was registered at iteration 10833 (exploration tick 513,027).

Registered but not replayed (the replay plan stops at the first verified claim of each level): the arm-T registry holds 124 candidates with a left-floor landing, 31 with a left-target break and 10 with a clear event; the
descriptive pool is 1,316 candidates of which six were replayed (all exact; they add no new milestone, two of them also break left target 6 at tick 1,837 as cid 16 does). Replays: 9 in all, all exact, no INVALID.

## 4. The registered diagnostics against the references

(`runs/m8_rd_rd4/derived/report_after_run.json`; every column recomputed by the same functions from the archives.)

| reading | rd1 | rd2 | rd3 | **rd4** |
| --- | ---: | ---: | ---: | ---: |
| returns | 2,175 | 4,037 | 4,194 | **3,480** |
| new cells per return (threshold 1.74) | 3.80 | 2.67 | 1.74 | **3.14** |
| returns from cells seen 8 or more times (threshold 45.0 %) | 12.8 % | 27.1 % | 43.0 % | **22.8 %** (793 / 3,480) |
| mechanism check | | | | **MECHANISM_HOLDS** (both comparisons hold) |
| returns starting left of x = -2,100 | 0 | 0 | 1 | **1,419 (40.8 %)** (x < -1,650: 1,496) |
| dispatches from wall-top cells | 0 | 0 | 3 | 3 (the archive's wall-top cells: 18,318, 18,767 and the new 26,944) |
| returns starting below the floor | 21.0 % | 20.5 % | 22.6 % | **44.0 %** |
| fatal returns (native failure) | 22.1 % | 12.8 % | 14.3 % | **32.7 %** |
| dilution verdict (reported only) | | | | DILUTION_PERSISTS |
| launch-capable cells created per 1,000 returns | 6.4 | 122.6 | 26.0 | **70.4** (245) |
| top level reached | 7 | 7 | 7 | **10** |
| median L of the top eligible level (S3 limit 3,000) | | | | 2,184 |
| leftmost start cell | | -1,876 | -5,124 | **-9,614** (cell 37,244) |

| start-cell session of creation (share of rd4's returns) | rd1 | rd2 | rd3 | rd4 |
| --- | ---: | ---: | ---: | ---: |
| rd4's returns | 11.7 % | 22.9 % | 12.9 % | **52.5 %** |
| rd3's returns (reference) | 32.5 % | 53.3 % | 14.3 % | 0 |

Seen-count distribution of rd4's start cells (new cells per return): 0-1 seen 24.7 % (6.85), 2-3 28.0 % (3.57), 4-7 24.5 % (1.60), 8-15 14.3 % (0.38), 16-31 6.5 % (0.12), 32-63 1.9 % (0.0), 64+ 0.1 % (0.0). Closest approach to the left floor:
cells are grounded on it (nearest cell 27,487, class G, at (-2,909.1, -1,950.0), distance 0; rd3's closest was 1,050.8 units away). Ground contact: 1,069 of 3,480 bursts touched the ground in rd4 (rd3: 2,027 of 4,194). rd4's
up-B starts at or above height 1,639: 20 (rd3: 50). The returns to left-of-wall cells grew by feedback: the first successful crossing created new cells left of the wall, which became start cells (the selection
probability of the eligible inherited left-of-wall cells was 0.0070 under v2 and 0.0106 under v3 at the open).

## 5. Stop conditions and flags

| item | reading |
| --- | --- |
| S3 (horizon pressure: median L of the top level above 3,000 with no left target) | not triggered (median L 2,184; a left target exists) |
| S5 (BOUND_VIOLATION) | not triggered; 0 bound violations |
| S7 (INVALID / INCOMPLETE) | not triggered |
| line budget | MILESTONE_VERIFIED, `rd5_permitted` true, `line_ends` false (rd5 would need its own authorisation) |
| mechanism check | holds; applies only without a milestone |
| flags | none (`BOUND_VIOLATION` not raised) |

## 6. Integrity

P1 passed (tick-0 record equals the archive pin; both pinned traces word for word); open identity 16 / 16 and close identity 16 / 16 returned exactly; every return's tick-0 record, per-tick consumed and input ticks, end
record and chain digest matched; the four-part ledger rebuild of the whole archive (rd1 under v1, rd2 and rd3 under v2, rd4 under v3) passed at the close and again in `verify-run` (37,312 cells, 13,886 bursts, 27,775 events); the prefix chain
rd1 -> rd2 -> rd3 -> rd4 holds; the live seen-at-dispatch counters equal the ledger's (3,480 dispatches, 793 from cells seen 8 or more times); the write guard recorded no write under any earlier tree; rd1's, rd2's and rd3's trees
equal their D: increments again at the close (166, 62 and 77 files, manifests unchanged) and by an independent PowerShell re-hash after the run. Independent offline checks of the saved clear route: 2,326 words, all Track 1 indices
(0-71), the digest of the words and of the canonical rows both equal the recorded `native_action_digest` (`5eccd4e2d5d77b25d69a2ae87211c05f8c7349fdeeeed6e094b53a88003907ba`), consumed ticks 0..2,325 contiguous, a fresh episode
at tick 0, no unsent action.

## 7. Resources against the caps

| resource | peak / used | cap |
| --- | ---: | ---: |
| session clock | 3,296.0 s | 3,600 s |
| exploration | 3,005.6 s | 3,000 s (+ 20 s grace) |
| main process private memory | 1,114.4 MB | 3,072 MB |
| process tree private memory | 4,481.9 MB | 9,216 MB |
| process tree working set | 1,909.0 MB | 4,096 MB |
| lowest system available memory | 5,486.2 MB | at least 1,024 MB |
| lowest system commit free | 11,386.8 MB | at least 2,048 MB |
| processes in the tree (peak) | 28 | (BattleShip processes at most 10) |
| memory breach | none (636 samples at 5 s) | |

## 8. Evidence and backup

| item | value |
| --- | --- |
| launch logs, preflights, snapshot records | copied into `runs/m8_rd_rd4/launch/` before the backup; the post-run `verify-run`, `report` and the factual analysis (route facts, lineage) into `runs/m8_rd_rd4/derived/` |
| backup | `python rl/tools/runs_backup.py backup --source runs/m8_rd_rd4 --dest D:\BattleShip_runs_backup\2026-10-03_incr_m8_rd4`: copy 93 / 93, verification PASS, 165,147,441 bytes, 0 hash mismatches; manifest sha256 `7ff2b29dfad2bcaa26e2567786acc3c84c55a6414501545b0f1c1815480068a8` |
| separate verify | `python rl/tools/runs_backup.py verify ...`: PASS, 93 / 93, 0 mismatches |
| independent re-hash | `logs/m8_rd4_prep/tools/independent_increment_check.ps1` (Get-FileHash, no Python): rd4 93 / 93 PASS; rd1 166 / 166, rd2 62 / 62, rd3 77 / 77 PASS (0 missing, 0 extra, 0 bad) |
| coverage | `runs/` holds 409,475 files, **0 uncovered** (the base and the increments of M7r, M7s, M7u, M7u2, M7u3, M8-rd1, M8-rd2, M8-rd3 and M8-rd4) |

## 9. What this does and does not say

- It is a verified, exactly replayed clear of Mario's Break the Targets by agent-generated controller words in the native executable. The first 1,694 ticks of the route are inherited from rd1 and rd2 (the wall-top landing of
  rd2's lineage); the crossing, the three left-side targets and the clear were found in rd4.
- It is **one session with no control arm**. It does not show that `m8_rd_select_v3` caused it: the 54 inherited airborne cells left of the wall, the wall-top cells and the archive's accumulated cells were the same
  material for any selection rule. rd4's return distribution did change sharply (40.8 % of returns started left of the wall against one in rd3), but that is mostly the feedback of the first crossing creating new cells there.
  The mechanism check holds (22.8 % of returns from cells seen 8 or more times against 43.0 % in rd3, 3.14 new cells per return against 1.74); it is not the cause of the clear and says nothing about rd5.
- The route is exactly replayable, not robust: nothing here is a policy or a generalisation, and a different executable, `.o2r` or configuration would require re-verification.
- DILUTION_PERSISTS is reported and guards nothing. The higher below-floor and fatal shares are the many returns from left-of-wall airborne cells that fall into the pit.
- Whether to propose an rd5 is the user's decision: the line's requirement is met, the line does not end, and rd5 (the second and last permitted session) needs its own authorisation.

## 10. Gotchas

- The session's own preflight (79 tests, about 9 minutes) runs before the session clock starts, so the process lived about 70 minutes for a 55-minute session clock.
- The launcher (PowerShell `Start-Process`) did not capture the exit code; the session's own records are the evidence.
- A candidate's `first.left_live` is relative to its burst (it is the burst's first tick for a burst that starts left of the wall, e.g. 2,214 for iteration 11206); the route facts above use the whole trajectory (first live x < -2,100 at tick 1,739).
- `state.json` records the main process peak at 796.5 MB at its last clock update; the sampler's final peak (`memory_summary.json`) is 1,114.4 MB; both are far below the cap.
- The report's `rd4.iterations` ends in `null` (the archive's last iteration is the last dispatch, 13,885); the ledger ranges are in `iteration_ranges`.
