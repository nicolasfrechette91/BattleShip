# M8-rd4 preparation: implementation record (2026-10-03)

**Status: zero-native-tick preparation.** The user's decisions for the third continuation (`docs/rl_m8_rd4_decisions_2026-10-03.md`, which also records the mechanical readings and the
verification-capacity hazard found in preparation) are implemented in new files only. Before this record was written nothing had launched BattleShip or consumed a native tick. Nothing was
committed or pushed and no branch was created. No tracked file was modified: rd1's, rd2's and rd3's code and documents, `runs/m8_rd/`, `runs/m8_rd_rd2/` and `runs/m8_rd_rd3/` are byte-identical
to `HEAD` and to their D: increments, and the external guide is untouched.

**Scope label**, carried by every rd4 record: *third continuation of archive `m8_rd_a1` (rd1, rd2 and rd3 as closed) under `m8_rd_select_v3` (`m8_rd_select_v2` with one change: the count term
`(1 + seen)^-1/2`); one session, one set of keyed draws; no control arm; not a policy result, not a learning result, not a comparison of v3 with v2.*

## 0. Summary

The three decisions of the third continuation that change anything are implemented in new files only: **`m8_rd_select_v3`** (v2 with exactly one change, the count term `(1 + seen)^-1/2`), the
**three-level resume** from rd3's closing archive (immutability of all three earlier trees at open and close; a zero-tick ledger rebuild that reproduces rd3's closing archive and the closing overlay
exactly as rd3's results record them), and the **rule `m8_rd4_rule_v1`** with the **mechanism check** and the **line budget** (rd4, then rd5 at most; a verified qualified crossing or higher meets the
line's requirement). Claim-path safety (decision 6) is tested at component and session level, including a crossing whose entry lies in an inherited prefix and whose landing lies in an rd4 burst, and the
continuation of an inherited wall-top cell. Everything else (explorer, burst length, cell key, recovery bound, descent doom, resource weights, harmonic level weight, caps, memory caps) is rd3's.

**State at the end of the preparation.** 79 unit tests and the production-count synthetic end-to-end run each passed three consecutive times with no change to any rd4 file in between (section 5 and 7);
the dry-run preflight (unit suite skipped, because it had just passed three times) refuses **solely** for the missing rd4 approval (section 10); zero native ticks have been consumed.

**Pre-launch hazard, fixed in new files only (flagged for the report).** *Verification capacity*: every return from the inherited left-of-wall cells registers a `left` candidate, so the frozen plan could
spend its 400,000-tick cap on descriptive candidates before reaching a decisive one. The plan now replays first the candidates that can raise the milestone (section 3 of the decisions record, tested by
`verification_capacity_flood`). It changes no registered measure, threshold, selection or cell key. Eleven items from the independent review are dispositioned in section 9a.

## 1. State

| item | value |
| --- | --- |
| parent | `main` = `origin/main` = `bdc7344`; `git status` shows only new untracked files |
| submodules | no change; no native, decomp or submodule edit; executable `build-us/Release/BattleShip.exe` `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee` (the archive's pin), hashed, not run |
| compute | Python 3.13.2, six logical CPUs |
| rd3's closing archive | id `m8_rd_a1`, `runs/m8_rd_rd3/archive/` checkpoint 32 (previous 31), 26,371 cells, 10,406 bursts, 20,814 ledger events, dispatch iterations 0..10,405 contiguous, two `session` events (rd2 at 2,175, rd3 at 6,212, both carrying the v2 digest `a7d1953b...`), 4,194 returns, 5,170,886 exploration ticks, decision NO_NEW_MILESTONE (m = 0) |
| rd4's start | iteration 10,406; draw id `m8_rd_a1_rd4`; checkpoint sequence 33 for the materialised open; closing v2 overlay sha256 `4ab51e43cf68aeceff126bce320735bced182bddd3a952f713daefb2ec664547` (16,610 of 22,336 v1-eligible cells remain eligible; 3,734 descent-doomed, 2,666 bound-unrecoverable, 5,726 in the union) |
| inherited frontier (registered) | 2 wall-top cells (18,318 and 18,767), 54 cells left of x = -2,100 (47 eligible, all airborne, none grounded), no cell on the left floor, no cell with a left target broken, maximum level 7 |
| D: | the base plus the increments of M7r, M7s, M7u, M7u2, M7u3, M8-rd1, M8-rd2 and M8-rd3 cover every `runs/` file (409,382, 0 uncovered); the rd4 increment `2026-10-03_incr_m8_rd4` is created after the run by the unchanged `rl/tools/runs_backup.py` |

## 2. Files (all new)

| file | role |
| --- | --- |
| `rl/m8_rd4_select.py` | `Archive4` (rd3's `Archive3` plus rd4's session: the draw id and the v3 weights by iteration, `begin_rd4`, `iteration_ranges`, `session_of_iteration`), the v3 contract (`select3_description` built from a replica of v2's description, `changed_keys`), `rebuild4` / `audit4` (the four-part ledger rebuild, which also reports every dispatch's start-cell counters at dispatch) |
| `rl/m8_rd4_resume.py` | the three-level open protocol pieces: `rd3_archive_facts`, `inherited_claim_facts`, `closing_overlay`, `materialise4`, `prefix_chain`, `prior_milestones`, the registered facts of rd3 |
| `rl/m8_rd4_claims.py` | the claim-path guard: the can-raise pools, the replay plan (`plan_replays4`), the descriptive allowance (rationale: the decisions record, section 3) |
| `rl/m8_rd4_rule.py` | the registered rule `m8_rd4_rule_v1`, the mechanism check, the line budget status and the self-test |
| `rl/m8_rd4_report.py` | D1-D9, rd3's new readings and decision 9's readings in four columns, the mechanism inputs, `verify_run4`, `full_report4` |
| `rl/m8_rd4_run.py` | `Session4` (a subclass of rd3's `Session3`), the identity samples, `verify_phase4`, `close_checks`, `decide4`, `run_all4` |
| `rl/m8_rd4_session.py` | the CLI: identity and approval, `open_protocol4`, `preflight`, `cmd_run`, `verify-run`, `report`, `open-check`, `status`, `approval-template` |
| `rl/m8_rd4_snapshot.py` | the verified D: source snapshot (`snapshot`, `verify`, `powershell`) |
| `rl/m8_rd4_tests.py` | the deterministic unit suite, the production-count end-to-end run and the separate non-gating `integration` command |
| `docs/rl_m8_rd4_decisions_2026-10-03.md`, this record | |
| `logs/m8_rd4_prep/` (Git-ignored) | the preparation outputs |

Reused unchanged (rd1's, rd2's and rd3's files, byte-identical to `HEAD`): every `m8_rd_*`, `m8_rd2_*` and `m8_rd3_*` module (including rd3's `suppress_wall_top_label`, the lock-step pool and
virtual clock of its tests), `m7f_trace`, `m7n_crossing`, `m7_standby`, `battleship_process`, `battleship_client`, `tools/runs_backup.py`. Nothing under `runs/` was written: the preparation only read
`runs/`.

## 3. The design as implemented

| decision | module | what it does |
| --- | --- | --- |
| 1 line budget | `m8_rd4_rule.line_status` | section 4 of the rule record: `status`, `session_counts`, `rd5_permitted`, `line_ends`, `reason` for every outcome |
| 2 selection v3 | `m8_rd4_select.Archive4` | rd3's draw-id wrapper around rd2's selection, with v3's weights from rd4's first iteration (`_v3` is set per selection by the iteration, so the whole history rebuilds); the explorer is rd1's unchanged (the job carries the draw id) |
| 3 resume, three levels | `m8_rd4_resume`, `m8_rd4_session.open_protocol4`, `m8_rd4_run.close_checks` | section 4 |
| 4 caps as rd2 and rd3 | `m8_rd4_session.run_config`, `caps()` | rd2's numbers, tested equal to rd2's and rd3's |
| 5 rule | `m8_rd4_rule` | PROGRESS iff m >= 2 (crossing, left target, clear) from exact replays, else NO_NEW_MILESTONE after INVALID and INCOMPLETE; the highest milestone and the maximum targets are reported |
| 6 claim-path safety | `m8_rd4_claims`, `m8_rd4_run` | the wall-top label is suppressed as in rd3; the plan replays can-raise candidates first; section 3 of the decisions record |
| 7 mechanism check | `m8_rd4_rule.mechanism`, `m8_rd4_report.mechanism_inputs`, `m8_rd4_select.audit4` | exact integer comparison; the inputs come from the ledger replay |
| 8 dilution | `m8_rd4_rule.apply` | reported with `reported_only` |
| 9 diagnostics | `m8_rd4_report.full_report4` | D1-D9 and the new readings in four columns; seen distribution, creation shares, frontier returns |
| 10 determinism | `m8_rd4_tests` | section 5 of the decisions record |

## 4. The resume protocol as implemented

| step | where | check | on failure |
| --- | --- | --- | --- |
| R1 | `open_protocol4` (`rs.rd1_immutability`, three times) | `runs/m8_rd/` holds exactly the 166 files of its D: increment, `runs/m8_rd_rd2/` the 62 files and `runs/m8_rd_rd3/` the 77 files of theirs: same paths, sizes, mtimes, sha256 and the backup's own bytes; each increment's record is PASS; the increments' file counts, byte totals and manifest digests equal the registered ones | refuse |
| R2/R4 (rd1, rd2) | `rs.rd1_archive_facts`, `r3.rd2_archive_facts` | rd3's open protocol's checks, unchanged | refuse |
| R2/R4 (rd3) | `r4.rd3_archive_facts` | rd3's manifest verifies; checkpoint 32 / previous 31 and `archive/` is the newest; the five files equal rd3's close record; 26,371 cells / 10,406 bursts / 20,814 events; iterations 0..10,405 contiguous; no `fail` event; exactly two `session` events (rd2, rd3) whose digests equal the digest recomputed from the current v2 contract; the diag2 counters equal the close record's; rd3's recorded decision, returns and ticks equal the registered ones; rd3's base copy equals rd2's closing files; the prefix chain rd1 -> rd2 -> rd3; **the inherited claim facts equal the registered ones and meet the claim preconditions, and no candidate in rd1's, rd2's or rd3's arm-T registry carries a left-floor landing, a left-target break or a clear (the registry-level check, review finding 6)**; rd3's own `audit3` (the ledger rebuild, zero ticks) passes | refuse |
| R3 | `rs.pin_problems` three times | the pins equal rd3's, rd2's and rd1's (executable, runtime files, frozen configuration, flags, contracts; rd1's predate `m8_rd_select_v2`); an executable-only difference refuses the session as a re-verification case | refuse |
| R5 | `r4.closing_overlay` | the v2 flags of every cell of rd3's closing archive, computed twice and equal, equal to the counts rd3's close record stores, to the registered headline figures and to the registered sha256 | refuse |
| R6 | `r4.materialise4` | `runs/m8_rd_rd4/base/` = rd3's closing data files and manifest byte for byte; `derived/` (the overlay, its digest, a base record); rd4's `session` event; the first checkpoint (sequence 33); the prefix property rd3 -> rd4 checked on it | refuse |
| P1, open identity | `Session4.p1`, `open_identity` | the tick-0 record of two promoted processes equals the archive's pin; two pinned Track 1 traces word for word; the return self-test with a refused corrupted record; 16 identity returns of archive cells with the four checks of every return | INVALID |
| every return | rd1's worker, unchanged | tick-0 record, per-tick consumed and input ticks, end record, chain digest | INVALID |
| close | `close_checks` | final checkpoint; `audit4` (four-part rebuild, with the dispatch rows); the prefix chain rd1 -> rd2 -> rd3 -> rd4; all three earlier trees equal their increments again; the write guard (any write under any earlier tree) | INVALID |

Every section of the open protocol runs inside a guard: a tampered file whose manifest no longer verifies refuses the session with a recorded problem and never aborts the protocol.

## 5. Tests

`python rl/m8_rd4_tests.py unit` runs 79 deterministic tests (32 rd4's own, plus the pure tests of rd3 (8), rd1 (22) and rd2 (17) that the continuation still exercises, by explicit lists). Decision 10:
no test in the suite or the preflight is non-deterministic: keyed sha256 streams and fixed data; every session-level test runs the real session engine against the synthetic stub world through rd3's
in-process lock-step pool and virtual clock; a source scan forbids `random`, `secrets`, `uuid`, `os.urandom`, `time.sleep` and any wall-clock read inside an assertion; the one test that starts real
processes (the fake game behind the real lifecycle code) is **not** in the suite or the preflight, but in the separate non-gating `integration` command (review finding 2; it passed in the first trial run, when
it was still in the suite, and is not part of the three consecutive passes).

| group | tests (rd4's own) |
| --- | --- |
| selection | `rd4_contract`, `select_v3_formula`, `archive4_draw_and_weights_switch`, `begin_rd4_and_persistence`, `ledger_rebuild4`, `dispatch_rows_and_mechanism_inputs` |
| rule, readings | `rule4_module`, `identity_samples4`, `report_readings`, `report4_on_real_rd3` |
| claim path | `claims_pools_and_plan`, `claim_cases_on_stub_traces`, `claim_cases_session`, `verification_capacity_flood`, `scanner_vs_analyser_on_real_traces`, `registry_has_no_inherited_milestone_events` |
| resume, session | `resume_three_level_synthetic`, `precondition_refuses_inherited_milestones`, `session4_small_run`, `session4_refuses_unbegun_archive`, `session4_outcomes_and_stops`, `session4_mechanism_and_line`, `session4_determinism`, `write_guard_three_roots` |
| budgets, identity | `budget_projection4`, `approval_isolated4`, `import_isolation4`, `source_guard4` |
| gates | `no_nondeterminism_in_rd4`, `tracked_files_unchanged4`, `snapshot_tool4`, `open_protocol_real_trees4` |

**Three consecutive passes, no change in between** (the fingerprint of `rl/m8_rd4_*.py`, `1fd257a13b1d7ab2`, was identical at the start and after every pass; outputs are in `logs/m8_rd4_prep/final/`):

| pass | unit suite | wall | end-to-end | wall |
| --- | --- | --- | --- | --- |
| 1 | 79 / 79 | 522 s | E2E PASS | 506 s |
| 2 | 79 / 79 | 526 s | E2E PASS | 516 s |
| 3 | 79 / 79 | 521 s | E2E PASS | 514 s |

(A first trial of the suite before the review fixes passed 71 of 78; its seven failures were all one defect of the test infrastructure, rd3's temp-directory cleanup deleting cached synthetic chains, fixed
in `build_chain4`. The passes above came after every fix and are the ones that count.)

## 6. Validation against the real data (read only)

| check | result |
| --- | --- |
| rd3's closing archive loads and its four-part ledger rebuild (rd1 under v1; rd2 and rd3 under v2) equals the stored checkpoints | `audit` PASS: 26,371 cells, 10,406 bursts, 20,814 ledger events, 26,371 prefixes reconstructed |
| the v2 digest recomputed from the current contract equals the digests of rd2's and rd3's `session` events | `a7d1953b7de76040ccb052703ec565100791c944f2d8a176ea189cb134c1c9d1`, both |
| the closing v2 overlay of rd3's archive equals rd3's recorded counts | sha256 `4ab51e43cf68aeceff126bce320735bced182bddd3a952f713daefb2ec664547`; 16,610 of 22,336 v1-eligible cells eligible; 3,734 descent-doomed, 2,666 bound-unrecoverable, 5,726 in the union |
| the registered inherited frontier | 2 wall-top cells (18,318 and 18,767), 54 cells left of x = -2,100, 0 grounded on the left floor, 0 with a left target broken, maximum level 7; the three registries hold 14, 23 and 27 candidates and none carries `left_floor`, `left_break` or `clear` |
| the mechanism inputs and rd3's report columns reproduced by rd4's reader on rd3's real archive | 1,802 of 4,194 dispatches from cells seen 8 or more times; 1,361 / 2,234 / 599 dispatches by start-cell creation session; selection probability of the eligible left-of-wall cells at the open 0.00702 under v2 and 0.01058 under v3 (x 1.51; the stop review's first-order estimate was about x 1.5) |
| analyser vs scanner landing label on real traces | 8 stored verification traces of rd1, rd2 and rd3, 3,675 grounded live steps, 0 disagreements (L0 69, L1 121, L2 869, L4 2,391, moving platform = line 19: 225); no L3 sample exists because nothing has landed there |
| the three earlier trees equal their D: increments | 166, 62 and 77 files, byte for byte, with the pinned manifests `e81226d7...`, `6775281e...`, `b6e13ecb...` |
| pins (executable `30a3913b...`, `.o2r` files, frozen configuration, flags, contracts) equal rd3's, rd2's and rd1's | no problem at any level |

## 7. The production-count synthetic end-to-end run

`python rl/m8_rd4_tests.py e2e` runs the real session at the registered counts and caps (6,000,000 exploration ticks valid from 2,000,000, five workers, the memory checks) against a synthetic chain of three
trees built by their own real engines, each with its verified increment, and the stub world, through the lock-step pool and the virtual clock. **The world is synthetic: the outcome says nothing about Mario.**
It exercises the three-level resume (R1-R6), the overlay at open, the v3 selection under rd4's draws, P1, the open and close identity replays (16 and 16), the descent-doom tree, the rule with the mechanism
check and the line budget, the four-part ledger audit, the prefix chain, `verify-run`, and the claim cases of decision 6. All three passes agreed on every recorded value except wall-clock and memory readings.

| item | value (all three passes) |
| --- | --- |
| outcome | PROGRESS, m = 4 (a verified clear), 10 targets, `progress_basis` `milestone:clear`; line status MILESTONE_VERIFIED |
| ticks, stop | 6,000,000 exploration ticks, stop `budget` (tick cap); 8,988 bursts; 8,936 returns |
| mechanism check | 1,408 of 8,936 returns from cells seen 8 or more times (15.8 %); 25,990 new cells (2.91 per return); MECHANISM_HOLDS |
| verification | 9 exact replays (9,651 replay ticks), `verify-run` PASS; identity 16 / 16 at open (6,161 ticks) and 16 / 16 at close; ledger audit PASS (26,518 cells, 17,985 events); prefix chain rd1 -> rd2 -> rd3 -> rd4 PASS |
| **claim case (a)** inherited left-of-wall continuation, no landing | forced dispatch at iteration 272 from inherited cell 268: registered, replayed exact (candidate 0), no false INVALID |
| **claim case (b)** inherited wall-top continuation | forced dispatch at iteration 594 from inherited wall-top cell 388: wall-top label suppressed, sighting recorded (1,214 sightings in all, first tick of the burst from a wall-top start), 0 `l0` candidates, no false INVALID |
| **claim case (c)** crossing: entry in the inherited prefix, landing in the new burst | forced dispatch at iteration 1,745 from inherited cell 466: entry at consumed tick 120, landing on the left floor at consumed tick 172, inherited prefix 130 words (entry < prefix length < landing), credited and exactly replayed from tick 0 |
| pools | 4,213 candidates; can-raise pools: crossing 2,015, left target 1,125, clear 492; descriptive 1,721; plan replays 9 (the decisive candidates first) |
| memory | main process peak 326 MB (private); 0 bound violations |
| other | `BOUND_VIOLATION` 0; dilution reported (DILUTION_PERSISTS, reported only) |

## 8. Budgets

`rpt4.budget_projection` (caps as rd2's and rd3's): open 240 s, exploration 3,000 s, verification 360 s, sum 3,600 s = the hard cap. **Expected** (rd3's measured 1,723 ticks/s with overheads): 4.68 M exploration
ticks, 90 s open, 150 s verification, 3,240 s total, tick cap not binding. **Pessimistic** (aggregate 1,766 ticks/s, the slowest of rd2's and rd3's measured phases, 150 s open and 240 s verification):
5.30 M ticks (validity needs 2.0 M, i.e. 667 ticks/s), 3,415 s total: **fits the 60-minute hard cap with no trimming**. With every cap binding the phases sum to exactly 3,600 s (the exploration phase may overrun
by its 20 s grace, inside the 3,600 s as the clock counts from the session object). The close audit (about 1.5-3 minutes at about 35,000 cells) runs outside the session clock. Memory caps are unchanged
(main process 3,072 MB, tree private 9,216 MB, tree working set 4,096 MB, system available at least 1,024 MB, commit free at least 2,048 MB).

## 9. Independent review and dispositions

An independent read-only review (a separate agent, which wrote nothing and ran only bounded read-only snippets against the real trees) examined the selection, the resume anchors, the claim plan, the
rule and line status, the mechanism inputs, the session and pins, and the tests. **No BLOCKER and no MAJOR.** It reproduced independently: v3 = v2's formula with only the count term changed (a
v2 replica digest equal to the real v2 digest on the real lines and floor; 400 of 400 v3 draws on the real rd3 archive equal to an independent re-implementation; v2 and v3 selections differ on all
400); every registered rd3 anchor (77 files / 114,026,700 bytes, 26,371 cells, 10,406 bursts, 20,814 events, the overlay sha `4ab51e43...`, the inherited frontier); the three trees equal to their D:
increments; and, on 2,973 grounded live steps of six stored real traces, agreement of the analyser's ground classification with the scanner's floor line on every step (the claim that a `left`
candidate without `left_floor`, `left_break` or `clear` cannot raise m). The rule's boundaries were fuzzed against exact fractions (about 2,700 triples, 0 mismatches) and `plan_replays4` against 150
seeded ledgers. Nine MINOR items and several notes were returned; each is recorded here with its disposition. **None changed a registered measure, threshold, selection or cell key.**

### 9a. Dispositions

| # | finding | disposition |
| --- | --- | --- |
| 1 | the nondeterminism scan's fake-game slice was vacuous (the string it split on occurred first inside the check itself) | the slice is gone: the scan now asserts that the fake-game test is absent from the suite and from the preflight (finding 2) |
| 2 | the fake-game test starts real processes (30 s waits): its pass depends on scheduling, yet it sat in the suite and so in the preflight | **moved out** of `TESTS` into a separate non-gating `integration` command (`rl/m8_rd4_tests.py integration`); the suite, the preflight and Part B's condition 1 no longer contain it; decisions section 5(c) updated |
| 3 | an operator-precedence slip made one assertion weaker than written (`A and B or C`) | parenthesised `A and (B or C)` |
| 4 | an rd4 checkpoint's `select2_digest` (written by rd2's writer) is the LAST session's digest, i.e. v3's | rd4's checkpoints now also carry `select3_contract` and `select3_digest`; `select2_digest` is documented as "the last session's digest" (nothing reads the field in rd1-rd4); a test pins both |
| 5 | `RD3_REFERENCE` labelled the analytic selection mass (0.434) as rd3's realised share | now rd3's realised values: 1,802 / 4,194 = 0.4297 dispatches from cells seen 8 or more times, and 7,309 / 4,194 = 1.7427 new cells per return; the 0.434 is named as the analytic mass; the reference is reported only (not in the rule description, so the rule digest is unchanged by it) |
| 6 | the claim preconditions were cell-based only (a grounded tick under an X-class status has no floor in its key) | new read-only **registry-level** open check: no candidate in rd1's, rd2's or rd3's arm-T registry carries `left_floor`, `left_break` or `clear`, and each registry exists (real trees: 14 + 23 + 27 candidates, none); a test refuses constructed violations |
| 7 | the stub's analyser applies the scanner's own landing rule, so scanner-vs-analyser agreement was tautological in the suite | new deterministic read-only test on the REAL stored verification traces of rd1, rd2 and rd3: every grounded live step's analyser class equals the scanner's floor line (L0-L2, L4, moving platform = line 19) |
| 8 | an INCOMPLETE exploration skips verification, so the registered candidate pools were not visible | `arm_T.json` now records the can-raise pool sizes at the end of exploration whether or not the verification runs |
| 9 | the mechanism check applied literally to a partial session (INCOMPLETE with a failed mechanism ends the line) | **applied as the decisions state it** (decisions 1 and 7; the user's rule). A descriptive flag is added to the line record: `exploration_ticks`, `mechanism_returns` and `provisional` (true below 2,000,000 ticks). Making a partial session "not evaluable" would change a registered measure and is left to the user |
| 10 | NOTE: the 1.74 new-cell threshold equals rd3's realised 1.7427; saturation, not v3, may decide it | recorded under the remaining risks (section 12) |
| 11 | NOTE: rd4's pin set has 8 contract keys (rd1-rd3: 7); `COUNT_EXPONENT` is a described constant (`v3_weights` computes `1/sqrt(1+seen)` directly); the frozen `WriteGuard` text says "rd1's tree" for any protected root | the open protocol compares each session's pins to its own contract set; the comment on `COUNT_EXPONENT` says so; the guard's message cannot change (frozen file) and includes the path |

**The hazard (flagged for the report).** The review's checks confirmed the one pre-launch hazard found in preparation and fixed in new files only: the **verification capacity** hazard (decisions section 3).
Its fix changes the verification plan only; the registered measures, thresholds, the selection and the cell key do not read the plan.


## 10. Preflight

`python rl/m8_rd4_session.py preflight` (the unit suite, pins, the open protocol at three levels, the D: coverage, readiness and the approval). Dry run at 2026-10-03 18:12 UTC with `--skip-unit` (the suite had
just passed three times): **the only problem is the missing approval** (`no approval record at docs\rl_m8_rd4_approval.json`). Everything else passes: tracked files equal `HEAD`, 11 new untracked files;
executable `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee`; both P1 traces consistent; controller CVars absent; the status table's digest verified; R1-R5 at three levels (section 4); D: coverage
409,382 `runs/` files, 0 uncovered; readiness (available memory 6,840 MB against 4,096 MB; commit free 15,596 MB against 10,240 MB; free space C: 109.6 GiB, D: 1,581.6 GiB; no BattleShip process running). The preflight
that gates the run runs the unit suite itself; a memory, commit or free-space refusal is a stop, never a reason to close an application or change a threshold.

## 11. Launch conditions (Part B) and the order of events (Part C)

| # | condition | evidence at the end of the preparation |
| --- | --- | --- |
| 1 | the full unit suite and the synthetic end-to-end run pass three consecutive times without changes | section 5: three passes, identical fingerprint |
| 2 | the pessimistic wall projection fits the 60-minute hard cap with no trimming | section 8: 3,415 s |
| 3 | the preflight refuses solely for the missing approval | section 10 |
| 4 | rd1's, rd2's and rd3's trees equal their D: increments byte for byte; the pins match | sections 4 and 6 |
| 5 | the zero-tick rebuild reproduces rd3's closing archive and overlay exactly | section 6 |
| 6 | `git status` shows only new files | 11 new files, none tracked, none modified |
| 7 | no open design decision had to be made | none; one hazard (verification capacity) was fixed in new files without touching a registered measure, threshold, selection or cell key, and is recorded in the decisions record before launch |

Part C, if Part B holds: an approval record with fresh identities (written only after the source snapshot to `D:\BattleShip_source_snapshots\2026-10-03_m8_rd4`, verified by the tool and by an independent
PowerShell re-hash); the preflight (once; a failure is a stop, not a retry); **one** detached rd4 session, waited to completion, no retry, no extension, no repair, **no rd5**; the backup of `runs/m8_rd_rd4/` to
`D:\BattleShip_runs_backup\2026-10-03_incr_m8_rd4`, verified by the tool and by an independent re-hash; the three earlier trees confirmed byte-identical again; `runs/` coverage reported; and the results record
`docs/rl_m8_rd4_results_2026-10-03.md`. The record of what actually happened is that results record and the session report, not this file.

## 12. Remaining risks

- **A crossing, a left target or a clear is not expected to be likely.** rd3 left 47 eligible, exactly replayed states left of the wall (all airborne, 1,653-1,835 ticks of horizon remaining); at the open they carry about 44 returns per
  session under v3 (29 under v2), first order, with no feedback. v3 is a modest change (about x1.5 on the frontier labels). The mechanism check and the line budget are the user's way of ending the line if it does not help.
- **First native contact for the rd4-specific paths**: `Session4`, `verify_phase4`'s plan, `close_checks`' four-part audit and the three-root write guard run against the real executable for the first time in the session
  itself (they ran against a fake game that speaks the M1d protocol through the real lifecycle code, and `audit4` ran on the real rd3 archive). A mismatch in P1 or an open identity replay is INVALID and stops there.
- **A wall-top sighting is recorded and never claimed**; a genuine crossing from the wall top is still found by the unchanged `left` candidates and the analyser.
- **Throughput.** The exploration needs 667 ticks/s to be valid; rd3 measured 1,723. A concurrent heavy job could make it INCOMPLETE; readiness is judged at launch.
- **A rebuilt executable or a changed `.o2r` file** during the run is a pin drift (INVALID), by design.
- **Close time.** The close audit rebuilds the whole ledger once with the dispatch rows (about 1.5-3 minutes at about 35,000 cells), outside the session clock.
- **The mechanism check's new-cell threshold (1.74 per return) equals rd3's realised 1.7427** (7,309 / 4,194). Within-class yields fell about 29 % between rd1 and rd3 and the stop review's 1.88 for v3 is a
  first-order estimate with no decay, so a pass or a fail may be decided by archive saturation rather than by v3. The check is applied as the user wrote it; the report states the values beside rd3's.
- **A partial session.** An INCOMPLETE session with at least one dispatch and a failed mechanism check ends the line (decisions 1 and 7, as written), even from a small sample; the line record carries a
  `provisional` flag below 2,000,000 ticks so the report can say so. Treating a partial session as "not evaluable" would change a registered measure and is the user's decision.
- **The integration command is not a gate.** `python rl/m8_rd4_tests.py integration` (real worker processes behind the fake game) is scheduling-dependent by nature; it is neither run by the preflight nor part of any
  launch condition.
- **Pin sets differ by session** (rd4's has 8 contract keys, rd1-rd3's 7): an rd5 open protocol must compare each session's pins to its own contract set, as rd4's R3 does.
