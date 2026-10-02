# M8-rd1 results (2026-10-02)

**Registered decision (rule `m8_rd1_rule_v1`, digest `e0bbfe212d3c0079bd8f5da1f1d923a180d1d260260a69217ba6c20b770071ef`): PASS.**

Neither arm reached a milestone (no wall-top landing, no qualified crossing, no left target, no clear). The decision rests on the rule's
equal-milestone clause: m(T) = m(C) = none, and the verified maximum targets within the comparison point are **t(T) = 7 against t(C) = 5**, which is exactly the
threshold t(T) >= t(C) + 2.

**Scope.** One session, one set of keyed draws, one executable. Return-based archive exploration (arm T) against a matched no-return control (arm C) from the
normal tick-0 reset. It is not a policy result and not a learning result. It does not show that the archive finds a route to the left side or a clear.

Design: `docs/rl_m8_rd_proposal_2026-10-01.md` (revision 2) as amended by `docs/rl_m8_rd_amendment_2026-10-02.md`. Preparation record:
`docs/rl_m8_rd_implementation.md`. Approval: `docs/rl_m8_rd1_approval.json`. Run directory: `runs/m8_rd/` (Git-ignored, 166 files, 62.4 MB).

## 1. What was run

| item | value |
| --- | --- |
| launch | one detached `python -B -u -X utf8 rl/m8_rd_session.py run`, pid 16748, 2026-10-02T06:06:39Z; exit code 0 at 06:51:45Z; no retry, extension, repair or second session |
| preflight before the launch | `ok: true`, no problems (approval present and matching the fresh identity, snapshot recorded and equal to the repository, 6,727 MB available, 18,341 MB free commit) |
| source snapshot | `D:\BattleShip_source_snapshots\2026-10-02_m8_rd1`, 450 files, `snapshot.json` sha256 `437b529e0043f794c8cf815b7b969016ab75eb435a2531a056fd69b07f70a29f`; tool verify PASS and a separate PowerShell re-hash (451 items, 0 bad) before the launch; tool verify PASS again after the run |
| executable | `BattleShip.exe` `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee`, unchanged; frozen runtime configuration `BattleShip.cfg.json` `1b29d91b...`, `imgui.ini` `0d261732...` |
| git head | `6a30c88`; no tracked file changed (`git diff HEAD --name-only` empty) |

## 2. Native ticks and the comparison point

| phase | native ticks | wall | cap |
| --- | ---: | ---: | ---: |
| P1 (identity, two pinned traces, return self-test) | 6,208 | 14.5 s | 10,000 ticks / 180 s |
| arm T | **2,435,663** (stopped by its 26-minute wall cap at 1,560.8 s) | 1,561.2 s | 3,000,000 ticks / 1,560 s |
| arm C | **3,000,000** (budget; 2 jobs cut so the arm commits exactly the cap) | 931.5 s | 3,000,000 ticks / 1,440 s |
| verification (2 candidate replays, 16 identity returns) | 21,602 | 15.1 s | 400,000 ticks / 420 s |
| **total** | **5,463,473** | **2,526.6 s (42.1 min) on the session clock** | 6,410,000 ticks / 3,600 s |

Arm T is valid (at least 1,500,000 ticks). **Comparison point T = 2,435,663 = the slower arm's cumulative ticks.** Arm C's milestones count only within its
first 2,435,663 ticks (amendment 1). Start-up before P1 (the preflight's unit suite and S0) took about 3 minutes outside the clock; the process ran 45 min 6 s in all.

## 3. Milestones, per arm, each with its full-replay verification

| milestone | arm T | arm C |
| --- | --- | --- |
| wall-top landing (floor line 0) | none | none |
| qualified crossing (`btt_qualified_crossing_v1`) | none | none |
| left target (live x < -2,100, floor line 3, or ids 1/6/8 broken) | none | none |
| clear (four-fact definition) | none | none |
| candidates of these kinds that needed replay | 0 | 0 |
| **maximum targets within T, verified by exact replay** | **7** (candidate 12, 1,355 words, iteration 1543, final targets remaining 3) | **5** (candidate 19, 510 words, final targets remaining 5) |

Both replays are exact (digest, consumed ticks, break table and claimed event tick agree; `problems: []`) and neither replay shows a wall-top landing, a left
region entry, a crossing or a clear (`route: no native left-region entry`). The routes are saved under `runs/m8_rd/routes/T_t` and `C_t` (words, metadata, trace).

**Reading of the margin.** The PASS sits exactly on the threshold and depends on the comparison point. Arm C's own online reading over its full 3,000,000 ticks is 6
targets, first reached at cumulative tick 2,451,268, which is 15,605 ticks after T; that claim lies outside the comparison point and was not replayed. Counted at
its full budget (t(C) = 6) the same data would give t(T) = t(C) + 1, which the rule calls INCONCLUSIVE, but arm T had fewer ticks, which is the reason amendment 1
fixes the comparison point. The registered decision is the one in the header. It is one draw.

First-reach of each target count, cumulative ticks from the start of the arm (trajectory tick in brackets):

| targets broken | arm T | arm C |
| ---: | ---: | ---: |
| 1 | 118 (40) | 27 (27) |
| 2 | 2,558 (120) | 76 (76) |
| 3 | 29,949 (325) | 506 (506) |
| 4 | 61,905 (609) | 3,221 (1,002) |
| 5 | 270,400 (880) | 23,663 (3,294) |
| 6 | 287,677 (982) | 2,451,268 (3,015) |
| 7 | 1,530,667 (1,355) | not reached |

Arm C found each of the first five counts much earlier in cumulative ticks, arm T found the shorter trajectories to 6 and 7. The levels are the archive's "top level" (targets
broken); the archive's top eligible level at the close was 7 (median trajectory length 1,604 ticks).

## 4. Archive and coverage readings (reported, never deciding)

| reading | arm T (full archive) | arm C, within T (coverage only) | arm C, full 3,000,000 ticks |
| --- | ---: | ---: | ---: |
| cells | 8,264 | 19,038 | 21,445 |
| distinct masks | 18 | 53 | 57 |
| 300-unit position bins | 1,042 | 1,073 | 1,083 |
| best y with x <= -1,200 | 1,252.3 | 1,500 (a bin ceiling) | 1,500 (a bin ceiling) |
| cells in contact with L1 | 32 | 129 | 146 |
| launch-capable cells | 14 | 213 | 259 |
| of those with x <= 600 | 0 | 3 | 6 |
| wall-top cells, left-of-wall cells | 0, 0 | 0, 0 | 0, 0 |

Arm T cells by resource class: G 201, A2 1,224, A1 3,182, A0 3,549, X 108. Cells by level 0..7: 209, 547, 645, 1,079, 1,286, 1,261, 1,648, 1,589; 1,304 cells are doomed (a fall within 60 ticks) and there were
4,343 replacements. Archive files: 9.6 MB (cells 3.9 MB, burst index 5.2 MB, words 0.2 MB, events 0.3 MB); the checkpoint manifest and a previous verified checkpoint
(`archive.prev`, sequence 6; the final is sequence 7) are kept. Arm C keeps cell keys only, so its positions are bin ceilings.

Return overhead in arm T: 2,198,454 of 2,435,663 ticks (**90.3 %**) were prefix replay. Throughput: arm T 1,560 ticks/s aggregate, arm C 3,222 ticks/s (five workers each; every
start, 2,175 and 952, was a promoted standby, no cold start). The 1,500,000-tick validity floor needed 962 ticks/s.

**Velocity-swap diagnostic** (airborne replacements whose new representative's horizontal velocity has the opposite sign to the incumbent's, both |vx| >= 6): **973** among
4,343 replacements in arm T (22.4 % of all replacements; the denominator includes ground replacements, so the airborne share is higher). Examples are in `close.json`
(first 20). It is read only; the key was not changed.

## 5. Integrity

- **P1 passed.** Tick-0 record pinned (`2817d8cf3494...`) and reproduced by a second, standby-promoted process (both host frames 64); the two pinned Track 1 traces
  (3,361 and 2,560 words) reproduced word for word with every host frame equal; the return self-test returned three cells from fresh processes and refused a
  corrupted end record (`prefix_end`, field `position_x`; evidence in `failures/iterate_4_w03.json.gz`, which is the expected refusal and not a run failure).
- **Returns.** 2,175 dispatches, 2,175 ingested returns in arm T, **0 failed iterations, 0 mismatches**, 0 lifecycle failures, 0 aborted jobs in either arm
  (tick-0, per-tick consumed/input ticks, end record and chain compared at every return; a mismatch would have made the session INVALID).
- **Identity replays at the close: 16 of 16 returned exactly** (the shortest cells of the top three levels, then keyed random cells; no failures).
- **Close audit**: ok, 8,264 cells, 2,175 bursts, 4,350 events, 8,264 prefixes reconstructed, no problems. Checkpoints `archive` (seq 7) and `archive.prev` (seq 6) verified, no `archive.tmp`.
- **`python rl/m8_rd_session.py verify-run`**: `ok: true`, recomputed outcome PASS. INVALID reasons: none. INCOMPLETE reasons: none.
- Executable and `.o2r` pins unchanged (re-hashed before every launch); controller-rule CVars absent; no leftover BattleShip process after the run.
- No RNG seed was inspected, logged, controlled, compared or hashed; no hand-written route or waypoint exists; the archive's trajectories are agent-generated from tick 0.

## 6. Resources against the caps

| resource | peak / minimum observed | cap |
| --- | ---: | ---: |
| main process private memory | 493.1 MB | 3,072 MB |
| whole tree private memory | 4,277.7 MB | 9,216 MB |
| whole tree working set | 1,631.5 MB | 4,096 MB |
| BattleShip processes | 10 | 10 |
| system available memory (minimum) | 5,708 MB | 1,024 MB minimum |
| system free commit (minimum) | 14,108 MB | 2,048 MB minimum |
| native ticks | 5,463,473 | 6,410,000 |
| session wall clock | 2,526.6 s | 3,600 s |
| arm T wall | 1,561.2 s (the cap bound) | 1,560 s |

501 samples at 5 s, no breach. The sampler's peak of 27 processes counts the whole tree (the main process, the workers and the game processes), not game processes alone; game processes peaked at 10.

## 7. Evidence and backup

| step | command | outcome |
| --- | --- | --- |
| launch logs | copied into `runs/m8_rd/launch/` before the backup | 7 files |
| backup | `python rl/tools/runs_backup.py backup --source runs/m8_rd --dest D:\BattleShip_runs_backup\2026-10-02_incr_m8_rd1` | copy 166/166, verification PASS, 62,448,635 bytes, 0 hash mismatches; manifest sha256 `e81226d7f36a28a09966b577bfd95cbee093fbdf91f2714b9d28d3a7046103f4` |
| separate verify | `python rl/tools/runs_backup.py verify --source runs/m8_rd --dest ...` | PASS, 166/166, 0 mismatches |
| independent re-hash | PowerShell `Get-FileHash` over every source file against its copy (`logs/m8_rd_run/tools/independent_increment_check.ps1`) | checked 166, backup files 166, bad 0, **PASS** (first attempt used a wrong layout prefix and reported the files missing; repeated with the tool's layout `<dest>\runs\`) |
| total coverage | `m7u_gate.combined_coverage()` | **409,243 `runs/` files, 0 uncovered**, over the base and six increments including this one |

Nothing was written into `runs/m8_rd/` after the backup. The session's console logs and the preparation logs also live under `logs/m8_rd_run/` and `logs/m8_rd_prep/` (Git-ignored).

## 8. What this does and does not say

- It says the harness works from the first native contact to the close: a return-based archive with exact returns, a matched control, the amended comparison point, claim
  verification and a D: increment, with every integrity check clean.
- It does not say the archive finds routes the control cannot: both arms stopped at 5-7 targets with no wall-top contact and no left-side entry. Arm T's archive holds
  14 launch-capable cells (none with x <= 600) and no cell on the wall top; arm C's coverage is wider.
- The only separation is the targets tie-break, +2 at the comparison point, with arm C at 6 targets 15,605 ticks later. One draw cannot say whether that is a difference in methods.
- The 90 % prefix share means that only 237,209 of arm T's 2,435,663 ticks (9.7 %) were new exploration; every one of arm C's 3,000,000 ticks was new.

Nothing else was started. No retry, extension, repair or follow-on session.
