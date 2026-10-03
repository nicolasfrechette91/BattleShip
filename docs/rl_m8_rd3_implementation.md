# M8-rd3 preparation: implementation record (2026-10-02)

**Status: zero-native-tick preparation.** The user's decisions for the second continuation (`docs/rl_m8_rd3_decisions_2026-10-02.md`) are implemented in new files only. Before this record was
written nothing had launched BattleShip or consumed a native tick. Nothing was committed or pushed and no branch was created. No tracked file was modified: rd1's and rd2's code and documents,
`runs/m8_rd/` and `runs/m8_rd_rd2/` are byte-identical to `HEAD` and to their D: increments.

**Scope label**, carried by every rd3 record: *second continuation of archive `m8_rd_a1` (rd1 and rd2 as closed) under `m8_rd_select_v2`; one session, one set of keyed draws; no control arm; not a
policy result, not a learning result, not a comparison of v2 with v1.*

## 0. Summary

| item | result |
| --- | --- |
| **Unit suite** | **67 / 67**, three consecutive passes in separate processes with no change in between (255 s, 253 s, 254 s): 28 rd3 tests, 22 pure tests of rd1, 17 pure tests of rd2 (section 5) |
| **Production-count synthetic end-to-end** | **PASS three consecutive times** (hard world) and once in the easy world: 6,000,000 exploration ticks, five workers, the registered caps, two-level resume R1-R6, the closing overlay, P1 against the archive's pin, 16 + 16 identity replays, close audit of the three-part ledger, prefix chain, `verify-run` (section 7). The three hard runs agree on every figure (cells, bursts, candidates, replay ticks) |
| **Real data (read only)** | the open protocol on the real closed trees passes: both trees equal their D: increments (166 and 62 files; independent PowerShell re-hash 166 / 166 and 62 / 62, 0 bad), rd2's closing archive (19,062 cells, 6,212 bursts, 12,425 events) rebuilds, its session digest equals the digest recomputed from the current selection contract, the closing v2 overlay reproduces rd2's own record exactly (section 6) |
| **Budgets** (section 8) | expected exploration about 4.7 M native ticks (rd2 measured 4.99 M); **pessimistic wall projection 56.9 min, every cap binding 60.0 min** against the 60-minute hard cap; nothing trimmed |
| **Preflight** (section 9) | refuses for exactly one reason: the missing rd3 approval |
| **Independent review** | a read-only review agent found no blocker and eight minor findings; all were addressed, and the review together with a follow-up analysis exposed one real hazard (section 9a, decisions I15), fixed and tested |
| **Design decisions needed** | none beyond the mechanical readings I1-I15 of the decisions record |

## 1. State

| item | value |
| --- | --- |
| parent | `main` = `origin/main` = `bde29cf`; `git status` shows only new untracked files |
| submodules | no change; no native, decomp or submodule edit; executable `build-us/Release/BattleShip.exe` `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee` (the archive's pin), hashed, not run |
| compute | Python 3.13.2, six logical CPUs, about 7.9 GB of memory available at the time of the checks |
| rd2's closing archive | id `m8_rd_a1`, `runs/m8_rd_rd2/archive/` checkpoint 20 (previous 19), 19,062 cells, 6,212 bursts, 12,425 ledger events, dispatch iterations 0..6,211 contiguous, one `session` event (rd2, first iteration 2,175, digest `a7d1953b...`), 4,037 returns, 4,992,640 exploration ticks, decision PROGRESS_WALL_TOP (m = 1) |
| rd3's start | iteration 6,212; draw id `m8_rd_a1_rd3`; checkpoint sequence 21 for the materialised open; closing v2 overlay sha256 `551a723bdd94d1f5fd3a8293e5f68b22b8fe0397cdb28e7c1091378b9461ba1b` (11,794 of 16,221 v1-eligible cells remain eligible; 2,992 descent-doomed, 2,087 bound-unrecoverable, 4,427 in the union) |
| D: | the base plus the increments of M7r, M7s, M7u, M7u2, M7u3, M8-rd1 and M8-rd2 cover every `runs/` file (0 uncovered); the rd3 increment `2026-10-02_incr_m8_rd3` is created after the run by the unchanged `rl/tools/runs_backup.py`, which is generic over any source under `runs/` |

## 2. Files (all new)

| file | role |
| --- | --- |
| `rl/m8_rd3_select.py` | `Archive3` (rd2's `Archive2` with the draw id by iteration, `begin_rd3`, `iteration_ranges`), `rebuild3` / `audit3` (the three-part ledger rebuild: rd1 under v1, rd2 under v2 with `_v2` draws, rd3 under v2 with `_rd3` draws) |
| `rl/m8_rd3_resume.py` | the two-level open protocol pieces: `rd2_archive_facts`, `closing_overlay`, `materialise3`, `prefix_chain`, `prior_milestones`, the registered facts of rd2 |
| `rl/m8_rd3_rule.py` | the registered rule `m8_rd3_rule_v1`, its stops S1-S7 and its self-test |
| `rl/m8_rd3_report.py` | the diagnostics D1-D9 with rd2's and rd1's reference columns, the new readings, the rule inputs, `verify_run3`, the budget projection |
| `rl/m8_rd3_run.py` | `Session3` (a subclass of rd2's `Session2`), the identity samples, `verify_phase3`, `close_checks`, `decide3`, `run_all3`, the wall-top label suppression |
| `rl/m8_rd3_session.py` | the CLI: identity and approval, `open_protocol3`, `preflight`, `cmd_run`, `verify-run`, `report`, `open-check`, `status`, `approval-template` |
| `rl/m8_rd3_snapshot.py` | the verified D: source snapshot (`snapshot`, `verify`, `powershell`) |
| `rl/m8_rd3_tests.py` | the deterministic unit suite and the production-count end-to-end run |
| `docs/rl_m8_rd3_decisions_2026-10-02.md`, this record | |
| `logs/m8_rd3_prep/` (Git-ignored) | the preparation outputs: the three consecutive passes (`final/`), the independent re-hash script and outputs, scratch tools |

Reused unchanged (rd1's and rd2's files, byte-identical to `HEAD`): `m8_rd_cells`, `m8_rd_explore`, `m8_rd_archive`, `m8_rd_claims`, `m8_rd_worker`, `m8_rd_run`, `m8_rd_finish`, `m8_rd_session`,
`m8_rd_select2`, `m8_rd_resume`, `m8_rd2_worker`, `m8_rd2_run`, `m8_rd2_session`, `m8_rd2_rule`, `m8_rd2_report`, `m8_rd2_snapshot`, `m8_rd_snapshot`, `m8_rd_stub`, `m8_rd_fakegame`, the
lifecycle modules and `tools/runs_backup.py`. Nothing under `runs/` was written: the preparation only read `runs/`.

## 3. The design as implemented

| decision | module | what it does |
| --- | --- | --- |
| 1 resume, two levels | `m8_rd3_resume`, `m8_rd3_session.open_protocol3`, `m8_rd3_run.close_checks` | section 4 |
| 2 selection unchanged, rd3-specific draws | `m8_rd3_select.Archive3` | rd2's `Archive2.select` is called as it is, with the draw id `m8_rd_a1_rd3` from rd3's first iteration (`m8_rd_a1_v2` before, rd1's own key in rd1's part). rd3's `session` event carries a digest recomputed from the current contract; it must equal rd2's recorded digest, which proves the selection, the recovery bound and the status table are unchanged. The explorer is rd1's unchanged (the job carries the draw id) |
| 3 caps as rd2 | `m8_rd3_session.run_config`, `caps()` | rd2's numbers, tested equal to rd2's |
| 4 rule | `m8_rd3_rule` | PROGRESS iff `m >= 2` or `t >= 8` (both from exact replays), else NO_NEW_MILESTONE, after INVALID and INCOMPLETE; reports the highest milestone, the maximum targets and the basis |
| 5 diagnostics | `m8_rd3_report` | D1-D9 for rd3, rd2 (recomputed on rd2's closing archive, equal to what rd2 stored: a unit test) and rd1; the wall-top cells and their dispatches, cells left of the wall face (x < -1,650, -1,800, -2,100), the closest approach to floor line 3, the selection probability of the wall-top cells at the open |
| 6 stops | `m8_rd3_rule` | S1-S7 carried over; S2 is the explicit three-session crossing condition, read from the sessions' recorded files |
| 7 deterministic tests | `m8_rd3_tests` | section 5 |

**Findings of the preparation that the decisions did not cover (recorded as readings, none changes a registered quantity).**
- *Wall-top label (decisions I15).* rd2's archive holds two wall-top cells (ids 18318, 18767; neither was ever dispatched). A burst that starts from one is on floor line 0 at its first tick;
  the frozen claims engine would turn that into an `l0` candidate and fail its replay against the first line-0 tick of the whole trajectory (the prefix's): a false INVALID. Their combined
  analytic selection probability at the open is 0.068 % per dispatch (about 2.7 expected dispatches in 4,000), so the hazard was likely. rd3 removes the label before the commit and records the
  sighting. A real session in which the first burst is made to look like such a continuation is INVALID without the fix and complete with it (`wall_top_label_suppressed`).
- *`t` is the maximum over exactly replayed trajectories* (I5), not only the replay of the maximum-targets candidate.
- *S2 is not evaluable* on an INCOMPLETE session that stopped before the verification (I6).

## 4. The resume protocol as implemented

| step | where | check | on failure |
| --- | --- | --- | --- |
| R1 | `open_protocol3` (`rs.rd1_immutability`, twice) | `runs/m8_rd/` holds exactly the 166 files of its D: increment and `runs/m8_rd_rd2/` exactly the 62 files of its increment: same paths, sizes, mtimes, sha256, and the backup's own bytes; each increment's record is PASS; the increments' file counts, byte totals and manifest digests equal the registered ones | refuse |
| R2/R4 (rd1) | `rs.rd1_archive_facts` | rd1's manifest, checkpoints, close record, counts, contiguous iterations and its own ledger audit | refuse |
| R2/R4 (rd2) | `r3.rd2_archive_facts` | rd2's manifest verifies; checkpoint 20 / previous 19 and `archive/` is the newest; the five files equal rd2's close record; 19,062 cells / 6,212 bursts / 12,425 events; iterations 0..6,211 contiguous; no `fail` event; exactly one `session` event (rd2, 2,175) whose digest equals the digest recomputed from the current contract; counters equal the close record's; rd2's recorded decision, returns and ticks equal the registered ones; rd2's base copy equals rd1's files; the prefix property rd1 -> rd2; rd2's own `audit2` (the ledger rebuild, zero ticks) passes | refuse |
| R3 | `rs.pin_problems` twice | the pins equal rd2's and rd1's (executable, runtime files, frozen configuration, flags, contracts; rd1's predate `m8_rd_select_v2`); an executable-only difference refuses the session as a re-verification case | refuse |
| R5 | `r3.closing_overlay` | the v2 flags of every cell of rd2's closing archive, computed twice (incremental structures and first-principles recomputation) and equal, equal to the counts rd2's close record stores and to the registered headline figures | refuse |
| R6 | `r3.materialise3` | `runs/m8_rd_rd3/base/` = rd2's closing data files and manifest byte for byte; `derived/` (the overlay, its digest, a base record); rd3's `session` event; the first checkpoint (sequence 21); the prefix property rd2 -> rd3 is checked on that first checkpoint | refuse |
| P1, open identity | `Session3.p1`, `open_identity` | the tick-0 record of two promoted processes equals the archive's pin; two pinned Track 1 traces word for word; the return self-test with a refused corrupted record; 16 identity returns of archive cells with the four checks of every return | INVALID |
| every return | rd1's worker, unchanged | tick-0 record, per-tick consumed and input ticks, end record, chain digest | INVALID |
| close | `close_checks` | final checkpoint; `audit3` (three-part rebuild); the prefix chain rd1 -> rd2 -> rd3; both earlier trees equal their increments again; the write guard (any write under either earlier tree) | INVALID |

Every section of the open protocol runs inside a guard: a tampered file whose manifest no longer verifies refuses the session with a recorded problem and never aborts the protocol.

## 5. Tests

**`python rl/m8_rd3_tests.py unit`: 67 / 67.** Deterministic by construction (decisions I8): the real session engine runs against the synthetic stub world through an in-process lock-step pool and a virtual
clock, so a run is a pure function of its configuration; the tests that start real processes assert only schedule-independent facts. Two builds of the synthetic chain are byte-identical (cells, words,
index, ledger) and two runs of the same rd3 session agree on the archive's data files and the decision.

| group | cases |
| --- | --- |
| contract and archive | `rd3_contract` (key strings, draw ids, caps equal rd2's, the digest of rd2's recorded session event equals the digest recomputed from the current code), `archive3_draw_switch`, `selection_draws_independent` (an independent re-implementation of the v2 draw under each part's draw id), `begin_rd3_and_persistence` (refusals, files readable by rd2's loader, the prefix property, a crash at every checkpoint step), `ledger_rebuild3` and `audit3_edge_cases` (thirteen kinds of tampering detected, a missing burst is a failure not an exception) |
| rule and records | `rule3_module`, `strict_records` (a missing milestone field is refused; the registered anchors of both increments and of rd2's record are enforced), `identity_samples3` |
| diagnostics | `new_diagnostics` (exact values on a hand-built archive), `report3_on_real_rd2` (rd2's and rd1's reference columns recomputed from the real archives equal what rd2 stored; the real wall-top, left-of-face and left-floor readings; the analytic probability at the open) |
| resume | `resume_two_level_synthetic` (R1 for each tree: byte, mtime, extra, missing, increment; R2, R3, R5, R6; both trees untouched), `open_protocol_real_trees` (the real closed trees: R1-R5, the overlay digest) |
| session (deterministic engine) | `session3_small_run` (every record, the scope label, the keyed explorer streams of each part, the report, `verify-run` and its refusals), `session3_refuses_unbegun_archive`, `session3_outcomes_and_stops` (below the minimum, redrawn and excess lifecycle failures, a mismatch, a provenance violation, a changed earlier tree, a write under either tree, an erroring close check, memory and process-count breaches, a wall cap, the replay cap), `session3_milestones_and_stops` (three worlds; the recorded decision equals the rule applied to values recomputed from the replay records), `session3_unverified_claims` (a claim of eight targets left at a cap is INCOMPLETE, not reproduced is INVALID), `wall_top_label_suppressed`, `session3_determinism` |
| guards and pins | `write_guard_two_roots`, `budget_projection3`, `approval_isolated3` (every altered identity entry refused), `import_isolation3`, `source_guard3`, `tracked_files_unchanged3`, `snapshot_tool3` |
| real lifecycle code | `cmd_run3_with_fake_game` (the whole `run` sequence through the real lifecycle code, real worker processes and a fake game: both trees equal their increments, rd1's frozen configuration read by every process, none left running, the four-diagnostics flag set checked by a direct replay of a constructed candidate, the refusal path) |
| rd1's pure tests (22) and rd2's pure tests (17) | the lists `RD1_PURE`, `RD2_PURE`, classified one by one (no process, thread, sleep, wall-clock assertion or live configuration) |

## 6. Real-data validation (read only)

- **The open protocol on the real trees** (`open-check`, about 50 s): R1-R5 pass at both levels. The rebuild of rd2's closing archive reproduces all 19,062 cells; the digest of rd2's session event
  (`a7d1953b7de76040ccb052703ec565100791c944f2d8a176ea189cb134c1c9d1`) equals the digest recomputed from the current selection contract; the closing overlay reproduces rd2's stored overlay counts.
- **A zero-tick dry run of the open into a scratch directory outside the repository** (`materialise3`, the audit of the materialised archive, `Session3` construction): `audit3` passes on 12,426 events (42 s);
  the prefix chain holds; the first five selections under the rd3 key are cells 9685, 3845, 17450, 4707, 8289; the worker spec protects both earlier trees. A second, independent simulation by the
  review agent agrees on the first selection (cell 9685 under the rd3 key, 11921 under the rd2 key).
- **rd2's registered diagnostics reproduce**: the reference column recomputed from rd2's closing archive equals `derived/report_after_run.json` field for field (829 / 622 / 1,772 / 814 start regions; 509
  launch-capable cells, 495 created in 4,037 returns).
- **The new readings at rd2's close**: 2 wall-top cells (18318, 18767; both L = 1,694, neither ever dispatched); their selection probability at the open 0.0684 % per dispatch in total; 14 cells at x < -1,650, 8 at
  x < -1,800, none at x < -2,100 (leftmost x -1,876.2); the closest approach to floor line 3 is 1,051.1 units (an A0 cell at (-1,649.5, -1,984.8)), 1,054.1 for the A2/A1 cells.
- Selection cost at 19,062 cells: 13.2 ms with the eligible levels recomputed at every selection (0.95 ms cached); about 21 ms at 30,000 cells, so under 2 % of the exploration wall time.

## 7. The production-count synthetic end-to-end run

`python rl/m8_rd3_tests.py e2e [--world hard|easy] [--small] [--async]` builds a synthetic rd1 tree with rd1's own engine, a synthetic rd2 tree on it with rd2's own engine (both with verified increments), then
runs the rd3 session at the registered counts (`ses3.run_config`, only the checkpoint cadence overridden), through the lock-step pool and the virtual clock (`--async` runs real worker processes, a measurement
run). The world is synthetic: nothing here says anything about Mario.

| item | hard world (three runs, identical) | easy world |
| --- | --- | --- |
| rd2 outcome (synthetic) | PROGRESS_LEFT_TARGET | PROGRESS_CLEAR |
| rd3 outcome | PROGRESS (left target, m = 3, 7 targets) | PROGRESS (clear, m = 4, 10 targets; both bases) |
| exploration ticks | 6,000,000 (the cap; committed exactly) | 6,000,000 |
| cells open -> close; bursts | 3,327 -> 6,596; 7,770 | 9,360 -> 29,937; 12,476 |
| candidates; replay ticks | 1,598; 15,561 | 4,743; 9,016 |
| open / close identity replays | 16 / 16, 16 / 16 | 16 / 16, 16 / 16 |
| close audit, prefix chain, earlier trees, `verify-run` | pass | pass |
| wall (rd3 part, one process) | 309-314 s | 570 s |
| main process private peak | 269 MB | 378 MB |

## 8. Budgets

Basis (rd1, measured; rd2 confirmed): wall per job 1.94 s + ticks / 1,523, 1,120 ticks per job in rd1 (1,237 in rd2), 1,560 aggregate ticks/s at about 75 % worker utilisation (rd2: 1,663), all starts
standby-promoted; the action-hold probe's serial-boot fit 2.22 s + ticks / 789 per episode (pessimistic). Computed by `rpt3.budget_projection(caps)` (rd2's function, unchanged) and tested.

| phase | native ticks: expected (cap) | wall: expected / pessimistic (cap) |
| --- | ---: | --- |
| S0 open (R1-R6), outside the clock | 0 | 3-5 min (measured about 1 min of protocol plus the dry run) |
| open: P1, 16 identity replays | about 6,200 + 19,000-21,000 (**70,000**) | 90 s / 150 s (**4 min**) |
| exploration | about 4.7 M expected, 5.3 M pessimistic rate (**6,000,000**, valid from **2,000,000**) | 50 min / 50 min + 20 s grace + 5 s (**50 min**; the wall cap is expected to bind) |
| verification | about 20,000-130,000 (**400,000**) | 150 s / 240 s (**6 min**) |
| **within the clock** | **<= 6,470,000** | **expected 54 min; pessimistic 56.9 min (3,415 s); every cap binding 60.0 min = the hard cap** |
| S2 close, outside the clock | 0 | 5-10 min |

- The pessimistic aggregate rate (every job pays a serial boot at the slow rate) is about 1,766 ticks/s, above the 667 ticks/s the exploration needs to reach 2,000,000 in 50 minutes.
- The three phase caps sum to the session cap, so the clock stops anything past it by construction (a stop inside verification is INCOMPLETE). Nothing was trimmed.
- Memory: rd2's real run peaked at 703 MB (main process) with 19,062 cells at the end; rd3 starts there and adds about 11,000 cells (about 1.8 KB each), so about 750 MB against the 3,072 MB cap; the whole
  tree peaked at 4,344 MB private and 1,926 MB working set against 9,216 / 4,096 MB.
- Expected returns: about 4,000-4,200. The probability that a dispatch starts from a wall-top cell is 0.068 % at the open (rising as the archive grows around it only if new wall-top cells appear).

## 9. Preflight

Zero native ticks, before any approval record exists (`python rl/m8_rd3_session.py preflight`): rd3's unit suite and the three rule self-tests, the tracked-tree and git checks, the executable and runtime pins, the
controller CVars, the status table, the pinned P1 traces, the open protocol R1-R5 at both levels, D: coverage, the process check, readiness, the source snapshot and the approval. Its result is recorded in the
report of the session; it must refuse for exactly one reason, the missing rd3 approval. It does not run rd1's or rd2's whole suites (decisions I9).

## 9a. Independent review (read only, before the code was frozen)

A general-purpose agent with no edit rights read the new modules against the decisions, rd2's modules and rd1's engine, and probed them with read-only snippets (including a simulation of rd3's open on
a copy of the real rd2 closing archive). **No blocker and no major finding**; eight minor findings, four test-quality findings and three documentation points. Dispositions:

| finding | disposition |
| --- | --- |
| A1 a wall-top landing would be inherited into `m` (the replay's `l0` flag reads the prefix) | **fixed, and found to hide a larger hazard** (a false INVALID from the frozen engine's `l0` check): the label is suppressed, `m` excludes the wall-top level, sightings are recorded (decisions I15); tests |
| A2 S2 fires on an INCOMPLETE session that never verified | fixed (`claims_verified`; S2 not evaluable); rule self-test |
| A3 R3 failed open when the pins were missing | fixed (a problem is recorded) |
| A4 `audit3` let `Select2Error` / `KeyError` escape | fixed (an audit failure, not an exception); test |
| A5 `audit3` did not check dispatches against a session's first iteration | fixed; test |
| A6 `materialise3` never checked the ledger prefix | fixed (checked on the first checkpoint, and again at the close); test |
| A7 registered anchors were dead constants | fixed (`open_protocol3` and `rd2_archive_facts` enforce them); test |
| A8 `prior_milestones` defaulted a missing field to zero | fixed (a missing field raises); test |
| B `cmd_run3_with_fake_game` accepts only some caps; `controller_cvars` reads the live configuration; some tests depend on git / D: / real-tree state; the replay-cap interleaving | fixed (allow-list widened to the registered cap kinds and tightened for complete sessions; `controller_cvars` removed from `RD1_PURE`; the gates are required and named as gates; the interleaving is documented and removed from the one test that approaches the cap) |
| C weak tests (self-referential draw check; tautological milestone test; orphan comment; trivial caps equality) | strengthened (`selection_draws_independent`; m and t recomputed from the replay records; `session3_unverified_claims`; absolute cap values) |
| D reference columns of D7 / D8 / D9; `arm.t` key; I5 and I11 wording | fixed; the decisions record is corrected |

## 10. Interpretations

The mechanical readings the code needed are I1-I15 of `docs/rl_m8_rd3_decisions_2026-10-02.md`. None changes a registered definition, threshold, budget, cap, the cell key, the explorer, the selection or the
rule's outcome table. I15 (the wall-top label) was found during the review and is the one reading that changes behaviour relative to rd2: it only prevents a false INVALID.

## 11. Launch conditions (the prompt's Part B) as evaluated at the end of the preparation

| # | condition | state |
| ---: | --- | --- |
| 1 | the full unit suite and the synthetic end-to-end pass three consecutive times without changes | **yes**: 67 / 67 three times and the hard-world end-to-end three times (the easy world once), no file changed in between (hashes checked) |
| 2 | the pessimistic wall projection fits within the 60-minute hard cap, with no trimming | **yes**: 56.9 min; every cap binding 60.0 min (section 8) |
| 3 | preflight refuses solely for the missing rd3 approval | see the report: evaluated after this record is final |
| 4 | rd1 and rd2 trees byte-identical to their D: increments, and the pins match | **yes**: R1 (repository check) and an independent PowerShell re-hash, 166 / 166 and 62 / 62, 0 bad |
| 5 | the zero-tick rebuild reproduces rd2's closing archive (19,062 cells) and closing overlay | **yes** (section 6) |
| 6 | `git status` shows only new files | see the report (checked at the end) |
| 7 | no design decision left open had to be made | **yes**: none; the readings I1-I15 change no registered quantity (I15 prevents a false INVALID) |

## 12. Remaining risks

- **Reaching beyond the wall top is improbable under an unchanged selection.** The wall-top cells carry 0.068 % of the selection mass at the open and nothing is left of the wall face; the closest approach to the
  left floor is 1,051 units. A NO_NEW_MILESTONE with S2 triggered is the likeliest outcome; the rule and the stop conditions are the user's.
- **First native contact** for the rd3-specific paths: `Session3.commit`, `build_real_env3`'s wrapper and the two-root write guard run against the real executable for the first time in the session itself (they
  ran against a fake game that speaks the M1d protocol through the real lifecycle code). A mismatch in P1 or an open identity replay is INVALID and stops there.
- **A wall-top sighting** is recorded but never claimed; a genuine crossing from the wall top is still found by the unchanged `left` candidates and the analyser.
- **Throughput.** The exploration needs 667 ticks/s to be valid; rd2 measured 1,663. A concurrent heavy job could make it INCOMPLETE; readiness is judged at launch.
- **A rebuilt executable or a changed `.o2r` file** during the run is a pin drift (INVALID), by design.
- **Dilution.** rd2's session ended with DILUTION_PERSISTS (20.5 % below-floor starts against the 10.5 % limit); rd3 reports the verdict and applies S4 / S6 only to NO_NEW_MILESTONE, as the decisions carry them over.
