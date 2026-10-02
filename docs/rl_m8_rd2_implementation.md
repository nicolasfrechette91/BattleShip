# M8-rd2 preparation: implementation record (2026-10-02)

**Status: zero-native-tick preparation.** The continuation proposal (`docs/rl_m8_rd_continuation_proposal_2026-10-02.md`, committed and
frozen) is implemented as decided in `docs/rl_m8_rd2_decisions_2026-10-02.md`, in new files only. Before this record was written
nothing had launched BattleShip or consumed a native tick. Nothing was committed or pushed and no branch was created. No tracked file was
modified: rd1's code, rd1's documents and `runs/m8_rd/` are byte-identical to `HEAD` and to their D: increment.

**Scope label**, carried by every rd2 record: *continuation of archive `m8_rd_a1` under `m8_rd_select_v2`; one session, one set of keyed
draws; no control arm; not a policy result, not a learning result, not a comparison of v2 with v1.*

## 0. Summary

| item | result |
| --- | --- |
| **Unit suite** | **27 / 27** (`python rl/m8_rd2_tests.py unit`, about 90 s). rd1's suite (`python rl/m8_rd_tests.py unit`) still passes **48 / 48** (about 155 s) with the new files present |
| **Production-count synthetic end-to-end** | **PASS** in two synthetic worlds (section 7): 6,000,000 exploration ticks, five workers, the registered caps, the whole-tree sampler, the resume path R1-R6 on a synthetic rd1 tree, P1 against the archive's pin, 16 open and 16 close identity replays, close audit, prefix property, `verify-run` |
| **Real data (read only)** | the open overlay of the real rd1 archive reproduces the proposal's figures **exactly** (6,960 eligible cells, 1,905 descent, 1,309 bound, 2,454 union, 4,506 left); every rd1 reference value of the diagnostics is reproduced (section 6) |
| **Budgets** (section 8) | expected exploration about 4.7 M native ticks; **pessimistic wall projection 56.9 min, every cap binding 60.0 min**, against the 60-minute hard cap; nothing trimmed |
| **rd1 tree** | equal to its D: increment: the repository check (size, mtime, sha256 of every file, and of the backup's bytes) and an independent PowerShell re-hash, 166 / 166 |
| **Preflight** (section 9) | refuses for exactly one reason: the missing rd2 approval |
| **Independent review** | a read-only review agent found no blocker and no major defect and seven minor ones; six were fixed (each with a test), one is a registered behaviour kept as is (section 9a) |
| **Design decisions needed** | none beyond the mechanical interpretations I1-I18 of the decisions record (one conflict, I1, is decided by the user's answer) |

## 1. State

| item | value |
| --- | --- |
| parent | `main` = `origin/main` = `1e0f847`; `git status` shows only new untracked files |
| submodules | no change; no native, decomp or submodule edit; executable `build-us/Release/BattleShip.exe` `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee` (the archive's pin), hashed, not run |
| compute | Python 3.13.2, six logical CPUs |
| rd1 archive | id `m8_rd_a1`, checkpoint sequence 7 (previous 6), 8,264 cells, 2,175 bursts, 4,350 ledger events, dispatch iterations 0..2,174, increment `2026-10-02_incr_m8_rd1` (manifest `e81226d7...`) |
| D: | the base plus six verified `runs/` increments cover every `runs/` file (0 uncovered) |

## 2. Files (all new)

| file | role |
| --- | --- |
| `rl/m8_rd_select2.py` | `Archive2`: two modes (rd1's rules for rd1's ledger part, then one `session` event and selection v2); eligibility E1-E6 and X1, the burst tree of descent doom (incremental and first-principles), the recovery bound with Mario's constants, replacement under v2 doom, the ledger rebuild and audit of both modes, the open overlay, persistence |
| `rl/m8_rd_resume.py` | the open protocol R1-R6 (rd1 immutability, archive facts, pins, overlay, materialise) and the prefix property |
| `rl/m8_rd2_worker.py` | the `iterate2` job (rd1's `iterate` unchanged behind a recording proxy that adds `ground_runs` and `res_transitions`), the rd2 worker entry point, the write guard |
| `rl/m8_rd2_run.py` | `Session2` (a subclass of rd1's `Session`), identity samples, verification, the close checks, the decision |
| `rl/m8_rd2_session.py` | the CLI (`status`, `open-check`, `preflight`, `approval-template`, `run`, `verify-run`, `report`), the registered run configuration, the identity and approval |
| `rl/m8_rd2_rule.py` | the registered rule `m8_rd2_rule_v1` and its self-test |
| `rl/m8_rd2_report.py` | the registered diagnostics D1-D9, the rule inputs, `verify-run`, the budget projection |
| `rl/m8_rd2_snapshot.py` | the verified D: source snapshot (`snapshot`, `verify`, `powershell`) |
| `rl/m8_rd2_tests.py` | the unit suite and the production-count synthetic end-to-end run |
| `docs/rl_m8_rd2_decisions_2026-10-02.md`, this record | |
| `logs/m8_rd2_prep/` (Git-ignored) | the preparation outputs: unit and end-to-end summaries, the preflight record, the independent re-hash script and its output |

Reused unchanged (rd1's files, byte-identical to `HEAD`): `m8_rd_cells`, `m8_rd_explore`, `m8_rd_archive`, `m8_rd_claims`, `m8_rd_worker`,
`m8_rd_run` (the engine: pool, clock, caps, arm loop, commit), `m8_rd_finish` (route saving, the verification path's helpers),
`m8_rd_session` (identity and approval helpers, readiness, coverage, the tree sampler, the P1 pins), `m8_rd_stub`, `m8_rd_fakegame`,
`m7f_trace`, `m7n_crossing`, `m7_standby`, `battleship_process`, `battleship_client`, `tools/runs_backup.py`, `m8_rd_snapshot`. Nothing under
`runs/` was written: the preflight and the tests only read `runs/`.

## 3. The design as implemented

| proposal | module | what it does |
| --- | --- | --- |
| 2.2-2.5 selection `m8_rd_select_v2` | `rl/m8_rd_select2.py` | `Archive2.select`: eligibility E1 (not X), E2 (not terminal), E3 (L <= 3,480), E4 (not doomed under v1, the stored flag), E5 (not descent-doomed), E6 (not bound-unrecoverable), X1 (a one-target cell is exempt from E4-E6), cell 0 always eligible; level weight 1 / (1 + top - level); cell weight (1/sqrt(1+chosen) + 1/sqrt(1+seen)) x 900 / (900 + L - L_min over the eligible cells of the level) x w_res (1, 1, 1/2, 1/4); two keyed uniforms from `m8_rd|m8_rd_a1_v2|select|<iteration>` |
| descent doom (R1b) | `DescentTree` | per burst R and F (a reach at offset o recovers iff o < R, has a fatal continuation iff o <= F); incremental at ingest by propagation up the tree with early stop; `DescentTree.reference` evaluates the definition bottom-up; the two are compared in tests and at every audit |
| recovery bound (R1c) | `bound_unrecoverable` | y + R + 300 < Y_floor_min, R = ballistic(v_y) + tornado 2,073.33 + aerial jump 1,171.8 + up-B 1,361.3 for A2, without the jump for A1, with only the up-B for an A0 cell in an up-B status, with nothing for a helpless one; Y_floor_min = -2,550 read from the native line table (the moving platform at its lowest recorded position); never reads x |
| replacement | `Archive2._decide_v2` | doom := (E4 or E5 or E6) and not X1; the incumbent's against the archive before the burst joined the tree, the new reach's from its own burst (E5) and its own end record (E6); a non-doomed reach beats a doomed one, then the strictly shorter L, ties keep the incumbent |
| 3.2 resume R1-R9 | `rl/m8_rd_resume.py`, `rl/m8_rd2_session.py`, `rl/m8_rd2_run.py` | section 4 |
| 5 caps | `rl/m8_rd2_session.run_config` | exploration 50 min / 6,000,000 ticks (valid from 2,000,000), open 4 min / 70,000 ticks, verification 6 min / 400,000 ticks, 60-minute hard cap, memory caps as rd1's |
| burst fields (decision 5) | `rl/m8_rd2_worker.py` | `iterate2`; the tick-by-tick summaries are taken by a proxy that only watches the replies, so rd1's `run_iterate` is run unchanged |
| 4 rule | `rl/m8_rd2_rule.py` | outcome table, thresholds as integer comparisons, `BOUND_VIOLATION`, stops S1-S7 |
| 4.3 diagnostics | `rl/m8_rd2_report.py` | D1-D9 from the archive and the session files, the up-B start heights and their Pareto front, the exact-evidence shadow reading |
| 6 integrity | `rl/m8_rd2_run.py`, `rl/m8_rd2_worker.py` | the four-way return check (rd1's, unchanged) at every return and identity replay; claims by full replay from tick 0; the write guard; the provenance guard |

**The archive in memory and on disk.** `Archive2` is rd1's archive plus derived state. The five data files are rd1's format (cells, burst
index, words, ledger, meta). rd1's bursts and cells re-serialise **byte for byte** (tested on the real archive: cells, index, words and ledger
are identical; the meta differs by schema and counters). The first rd2 checkpoint (sequence 8) is rd1's files plus one `session` event.
Derived state (the tree, the two flags per cell) is a function of the stored data and is recomputed at load and compared at every audit.

**The rebuild.** `rebuild2` replays the ordered ledger over the stored bursts: rd1's part under v1 (every selection re-derived), the `session`
event (its digest covers every rule, the status-class table, the pinned line table and the floor), then rd2's part under v2. Every insert,
replace and keep is re-decided by the same code path a live ingest uses (`_ingest_core`) and compared with the stored action. rd2's reach rows
carry the new reach's bound bit (interpretation I3) because the end record of a kept reach is not stored.

## 4. The resume protocol as implemented

| step | where | check | on failure |
| --- | --- | --- | --- |
| R0 | `preflight`, `cmd_run` | `HEAD` and the tracked tree equal the approved state; the source snapshot verifies; the approval matches the fresh identity | refuse |
| R1 | `rd1_immutability` | `runs/m8_rd/` holds exactly the 166 files of its D: increment: same paths, sizes and mtimes; every file's sha256 equals the manifest's and the backup copy's; the increment's record is PASS. Repeated at the close | refuse / INVALID |
| R2 | `rd1_archive_facts` | rd1's manifest verifies; checkpoint 7 (previous 6); the archive's five file hashes equal rd1's close record; 8,264 / 2,175 / 4,350; the ledger holds contiguous dispatch iterations 0..2,174 and no `fail` event | refuse |
| R3 | `pin_problems` | executable, runtime files, frozen configuration (read in rd1's `archive/runtime`), flags and every contract digest equal the archive's pins. If only the executable differs the session is not an exploration session (decision 11) | refuse |
| R4 | `m8_rd_archive.audit` (rd1's own code) | the ledger rebuilds every cell under v1; every prefix reconstructs; every lineage reaches cell 0 | refuse |
| R5 | `build_overlay` | the v2 flags of every rd1 cell with reason codes, computed twice (the incremental structures of one load, the first-principles recomputation of another) and equal, stored with a digest; the figures equal the proposal's | refuse |
| R6 | `materialise` | `runs/m8_rd_rd2/base/` (rd1's data files byte for byte, hashes equal), `derived/` (overlay and its digest, the base record), the `session` event and checkpoint 8 in `archive/` | refuse |
| R7 | `Session2.p1` | the tick-0 record of two processes equals the archive's `pin_tick0`; the two pinned Track 1 traces word for word; the return self-test in a scratch archive including the refused corrupted end record | INVALID |
| R8 | `Session2.open_identity` | 16 returns of rd1 cells (the shortest of the top three levels; the four highest-weight v2-eligible cells; four keyed-random launch-capable or A2-high cells; five keyed-random v2-eligible cells) with the four checks | INVALID |
| R9 | `make_job` | exploration begins at iteration 2,175; rd1's range is proved by the ledger | |
| close | `close_checks` | final checkpoint; `audit2`; the prefix property (rd2's event, burst-index and word files begin with rd1's exact bytes); R1 again; the write guard's record | INVALID |

## 5. Tests

**`python rl/m8_rd2_tests.py unit`: 27 / 27.** Approval is tested on isolated temporary records, so the suite stays valid after a real approval
exists. Run beside rd1's unit suite by the preflight.

| group | cases |
| --- | --- |
| contract and bound | `select2_contract` (the Mario constants, Y_floor_min, w_res, Mario's up-B statuses 225 / 226, the digest, the v2 key strings), `bound_rule` (the strict inequality at the threshold of each class, ballistic rise, G and X exempt, the floor as an input, X1) |
| descent doom | `descent_tree_vs_reference` (360 random trees: incremental equals the definition, the changed-set, order errors), `descent_doom_semantics` (a fatal burst dooms its airborne reaches, a landing from the reach clears only it and counts a revival, a fatal child keeps the doom, a pending burst is not doomed, a landing later in the same burst, X1) |
| archive | `archive2_mode1_equals_v1` (80 random iterations: mode 1 builds exactly rd1's cells, bursts, ledger, diagnostics and eligibility), `select2_probabilities` (analytic probabilities against an independent formula and 40,000 draws, every eligibility case, harmonic and resource weights, the v2 key), `replacement_v2` (doomed incumbents by E5, E6 and X1; doomed new reaches; ties) |
| rebuild and persistence | `ledger_rebuild_v2` (a two-mode archive audits; ten kinds of tampering detected: a counter, a bound bit, an action, a missing or altered session event, a different line table, a derived flag, a v2 counter, a win record, a forward lineage), `begin_v2_and_persistence` (the switch rules, rd1-schema files load as mode 1, the prefix property and its failure, self-describing v2 files, a crash at every checkpoint step), `overlay` (computed twice and equal, reason codes, the floor as an input, a changed file refused) |
| worker | `iterate2_equals_iterate` (80 iterations in two worlds: the two jobs' results are identical except for the two new fields; the new fields equal a brute-force computation over the replay; cuts inside the prefix and the burst; failures keep rd1's structured shapes), `write_guard` (twelve write kinds caught, reads and other paths never) |
| rule, reports, budget | `rule2_module`, `report_on_rd1_reference` and `open_overlay_on_rd1_reference` (the real archive, read only), `budget_projection`, `identity_samples` |
| resume and session | `resume_protocol_synthetic` (R1: byte, mtime, extra, missing and increment changes each caught; R2, R3, R5, R6; no write under rd1), `session2_small_run` (the whole session through real worker processes against the stub: every record, `verify-run`, the report), `session2_outcomes_and_stops` (below the minimum, redrawn and excess lifecycle failures, an integrity mismatch, a provenance violation, a changed rd1 tree, a write under rd1, memory and process-count breaches, a wall-capped exploration), `session2_replay_cap`, `cmd_run_with_fake_game` (the `run` command's own sequence through the REAL lifecycle code and a fake game: rd1's frozen runtime read in place, no process reading the live configuration, the real replay path) |
| pins and guards | `approval_isolated2` (about 80 altered identity entries refused), `import_isolation2`, `source_guard2` (no fixture, recording or TAS vocabulary, no learning framework, no write call that can take a path built from rd1's root), `tracked_files_unchanged2` (rd1's files and documents equal `HEAD`), `snapshot_tool2` |

## 6. Real-data validation (read only; scratch scripts outside the repository, now unit tests)

- **The overlay.** On the real rd1 archive: 8,264 cells, 6,960 eligible under v1; descent-doomed among them **1,905** (below the floor 1,307, beside 424,
  on-stage low 129, on-stage high 45; 22 of the 403 A2/A1 cells on stage at y >= 0, 8 of the 133 A2 cells at y >= 0; no launch-capable and no grounded
  cell); bound-unrecoverable **1,309** (A1 361, A0 948, A2 0; all below the main floor); union **2,454**; **4,506** left; all 14 launch-capable, 32 step-contact and
  201 grounded cells still eligible. Overlay digest `3c1b684c88e881dfed92a374ed736b8f514bf620193a2f3183bb50fad30df454`.
- **The diagnostics.** The same functions on rd1's 2,175 dispatches reproduce the proposal's references exactly: regions 456 / 180 / 1,274 / 265 (20.97 / 8.28 / 58.57 /
  12.18 %), left of the wall 0; step contact 12 dispatches and 32 cells; classes 96 / 408 / 764 / 907 (4.41 / 18.76 / 35.13 / 41.70 %); A2/A1 on stage y >= 0: 96;
  A2 y >= 0: 30; 4,406 A2/A1 cells, 403 eligible on stage y >= 0, 14 launch-capable with 2 dispatches and none at x <= 600, highest A2 y 909.6, 6.4368 per 1,000
  returns; closest approach 1,017 (an A0 cell), 2,125 (A2/A1), best y 1,252.3 at x <= -1,200 and 1,207.6 at x <= -1,500, highest cell y 3,247; fatal returns 480 / 2,175
  (22.07 %); dispatches by level 52 / 84 / 132 / 195 / 370 / 370 / 664 / 308.
- **The round trip.** Loading rd1's archive into `Archive2` and writing it back reproduces the cell, burst-index, word and ledger files byte for byte; with the `session`
  event added the prefix property holds; the audit of the mode-1 archive passes (4.2 s) and so does rd1's own.
- **`open-check`** (`python rl/m8_rd2_session.py open-check`, writes nothing): R1-R5 pass on the real tree.

## 7. The production-count synthetic end-to-end run

`python rl/m8_rd2_tests.py e2e [--world hard|easy]` builds a synthetic rd1 tree with rd1's own engine against the stub (an archive with its checkpoints, a close record,
a frozen runtime directory, the pins and a verified increment of it), then runs the rd2 session at the registered counts: `open_protocol`, `materialise`, `Session2`,
`run_all2`, five real worker processes, the whole-tree sampler, then `verify-run` and the report. The world is synthetic: nothing here says anything about Mario.

| item | hard world | easy world |
| --- | --- | --- |
| outcome (the rule's, on synthetic milestones) | PROGRESS_LEFT_TARGET (m = 3) | PROGRESS_CLEAR (m = 4); routes saved for every milestone |
| exploration ticks | 6,000,000 (the cap; committed exactly) | 6,000,000 |
| exploration wall | 63 s (95,720 ticks/s) | 122 s (49,136 ticks/s; the parent's selection and ingestion cost grows with the archive) |
| cells (rd1 part / total), bursts | 2,017 / 6,127, 6,795 | 3,437 / 25,408, 10,059 |
| candidates, replay ticks | 1,889, 15,303 | 4,390, 9,740 |
| descent-doom revivals, newly doomed, doomed incumbents replaced | 1,773, 3,475, 1,737 | 1,794, 7,036, 1,246 |
| bound violations | 0 | 0 |
| open / close identity replays | 16 / 16, 16 / 16 | 16 / 16, 16 / 16 |
| close audit, prefix property, `verify-run` | pass, pass, pass | pass, pass, pass |
| main process private peak | 557 MB | 782 MB |
| whole tree private / working set | 557 / 423 MB (6 processes) | 782 / 604 MB (6 processes) |

The two outcomes are in different synthetic worlds and the runs are asynchronous, so rd1-part sizes differ between runs; both are valid.

## 8. Budgets

Basis (rd1, measured): wall per job 1.94 s + ticks / 1,523, 1,120 ticks per job, 1,560 aggregate ticks/s at about 75 % worker utilisation, all 2,175 starts
standby-promoted; the action-hold probe's serial-boot fit 2.22 s + ticks / 789 per episode (pessimistic). Computed by `rpt2.budget_projection(caps)` and tested.

| phase | native ticks: expected (cap) | wall: expected / pessimistic (cap) |
| --- | ---: | --- |
| S0 open (R0-R6), outside the clock | 0 | 5-8 min |
| open: P1, 16 identity replays | about 6,200 + 21,000 (**70,000**) | 90 s / 150 s (**4 min**) |
| exploration | about 4.68 M expected (**6,000,000**, valid from **2,000,000**) | 50 min / 50 min + 20 s grace + 5 s (**50 min**; the wall cap is expected to bind) |
| verification | about 30,000-130,000 (**400,000**) | 150 s / 240 s (**6 min**) |
| **within the clock** | **<= 6,470,000** | **expected 54 min; pessimistic 56.9 min (3,415 s); every cap binding 60.0 min = the hard cap** |
| S2 close, outside the clock | 0 | 5-10 min |

- **Expected returns:** about 4,180 (4.68 M / 1,120 ticks per job).
- **The pessimistic aggregate rate** (every job pays a serial boot at the slow rate) is about 1,766 ticks/s, above the 667 ticks/s the exploration needs to reach 2,000,000 in 50 minutes.
- The three phase caps sum to the session cap, so the clock stops anything past it by construction (a stop inside verification is INCOMPLETE). The tick cap binds first only if the
  rate exceeds 2,000 ticks/s. **Nothing was trimmed.**
- **Memory.** About 1.84 KB per cell: 25,000-30,000 cells add about 50 MB to rd1's 493 MB main-process peak; the synthetic runs peaked at 557 and 782 MB (25,000 cells) against the 3,072 MB cap.
  BattleShip processes: rd1's tree peaked at 4,278 MB private and 1,632 MB working set with ten game processes, against the caps 9,216 / 4,096 MB.

## 9. Preflight (zero native ticks, before any approval record exists)

`python rl/m8_rd2_session.py preflight` runs rd1's suite and rd2's suite in parallel, both rule self-tests, the open protocol R1-R5, the tracked-tree and git checks, the pinned P1 traces,
the controller CVars, the status table, D: coverage, readiness and the approval; the record is in `logs/m8_rd2_prep/preflight_noapproval.json`.

Result (2026-10-02T18:56:57Z, final code): **`ok: false` with exactly one problem: `no approval record at docs\rl_m8_rd2_approval.json (the session is not authorised)`.**

| check | result |
| --- | --- |
| rd1's unit suite, rd2's unit suite, both rule self-tests | **48 / 48** (146 s), **27 / 27** (78 s); `m8_rd1_rule_v1` digest `e0bbfe21...`, `m8_rd2_rule_v1` digest `f9779faa...`, no problems |
| tracked tree and HEAD | no tracked file differs from `1e0f847`; `git status` shows only new files (11 at that moment) |
| executable, runtime files | `30a3913b...` (hashed); equal to the archive's pins (R3) |
| controller-rule CVars, status table | absent or zero; digest verified |
| pinned P1 traces | both consistent (native digest = recorded digest = trace digest; consumed ticks 0..n-1; spatial flag present) |
| R1 | `runs/m8_rd/`: 166 files equal to the increment `2026-10-02_incr_m8_rd1` (manifest `e81226d7...`); an independent PowerShell re-hash gives 166 / 166, 0 bad (`logs/m8_rd2_prep/rd1_independent_check_before.txt`) |
| R2 / R4 | checkpoints 7 / 6, 8,264 cells, 2,175 bursts, 4,350 events, iterations 0..2,174, rd1's own audit ok |
| R5 | overlay sha256 `3c1b684c...`, equal to the proposal's figures (`differs_from_the_proposal: []`) |
| D: coverage | all 409,243 `runs/` files covered over the base and six increments, **0 uncovered** |
| processes, `runs/m8_rd_rd2` | no BattleShip process; `runs/m8_rd_rd2` absent |
| readiness | 7,640 MB available (minimum 4,096), 17,723 MB free commit (10,240), 115 GiB free on C: and 1,584 GiB on D: (5 each) |
| **approval record** | **refused: none exists** (expected) |

## 9a. Independent review (read only, before the code was frozen)

A general-purpose agent with no edit rights read the new modules against the proposal, the decisions record and rd1's code, and probed them with read-only
snippets (including a real-scale simulation: 600 random ingests into the real rd1 archive after the switch, the incremental flags equal to the first-principles
recomputation every 100 iterations, `audit2` passing). **No blocker and no major finding.** It confirmed the archive core, the resume protocol, the caps and the
rule arithmetic. Its seven minor findings and what changed:

| finding | disposition |
| --- | --- |
| M1 `verify-run` could say ok with no decision recorded, and copied `m` from the record | **fixed**: it now needs `rule.json`, `close.json` and a finished state, and recomputes `m` from the exact replays; tests |
| M2 the 16 close identity replays could be skipped silently at a cap | **fixed**: not completed is INCOMPLETE; test |
| M3 a software error in the close path could hide the other checks or leave no decision record | **fixed**: every close check runs in its own guard (an error is recorded and INCOMPLETE, the others still run), `close.json` is written before the decision, and a decision record is always written; test |
| M4 the scope label was not carried by every record | **fixed**: it is in `p1`, `identity_open`, `arm_T`, `verification`, `rule`, `close` and `state`; test |
| M5 a malformed step reply was downgraded from INVALID to INCOMPLETE by the recorder | **fixed**: the recorder ignores a malformed reply and rd1's own check raises its `bad_reply` mismatch; test |
| M6 one lifecycle failure at the open stops the single run | **kept**: the registered INCOMPLETE condition is "the open phase not completed" (decisions record I17) |
| M7 write-guard edge cases (`\\?\` paths, a hook that could raise) | **fixed**: the extended-length prefix is stripped and the hook never raises into the audited call; test |

Also noted by the review (not a defect): the session clock starts at session creation, not at P1 (I18); and the expectation below.

## 10. Interpretations

The mechanical readings the code needed are I1-I18 of `docs/rl_m8_rd2_decisions_2026-10-02.md`. None changes a registered definition, threshold, budget, cap, the cell key, the explorer or
the rule's outcome table. The one conflict between texts (the proposal's 2.5 against the user's answer 5) is decided by the answer: descent doom reads grounded reaches for every burst and the
exact ground runs are diagnostics; a shadow reading counts, without applying, how many cells' flags would differ.

## 11. Launch conditions (the prompt's Part B) as evaluated at the end of the preparation

| # | condition | state |
| ---: | --- | --- |
| 1 | all unit tests and the synthetic end-to-end test pass | **yes**: 27 / 27 and rd1's 48 / 48; the end-to-end run passes in both synthetic worlds (section 7) |
| 2 | the pessimistic wall projection fits within the 60-minute hard cap, with no trimming | **yes**: pessimistic 56.9 min, every cap binding 60.0 min = the hard cap; nothing trimmed (section 8) |
| 3 | preflight refuses solely for the missing rd2 approval | **yes** (section 9); memory and free commit are met |
| 4 | rd1's tree is byte-identical to its D: increment, and its pins match | **yes**: R1 (repository check and independent PowerShell re-hash, 166 / 166) and R3 |
| 5 | the zero-tick ledger rebuild reproduces 8,264 cells, and the overlay matches the proposal's figures | **yes**: rd1's audit rebuilds all 8,264 cells; the overlay equals 6,960 -> 2,454 excluded -> 4,506 eligible, with all 14 launch-capable, 32 step-contact and 201 grounded cells still eligible |
| 6 | `git status` shows only new files, no existing file changed | **yes**: eleven new untracked files before the snapshot; no tracked file differs from `HEAD` |
| 7 | no design decision left open had to be made | **yes**: none (decisions record, section 3; I1 is decided by the user's answer) |

## 12. Remaining risks

- **The dilution threshold may fail at the start.** At the rd2 open the analytic v2 selection mass on cells below the main floor (y < -2,850) is **14.7 %** (v1: 45.3 %), above
  the registered 10.5 % limit for DILUTION_REDUCED (the proposal's "about 5 %" is an average over rd1's evolving archive). It sits on 364 eligible below-floor cells (340 never
  dispatched), mostly level-7 A2 and A1 cells; each should be descent-doomed after about one fatal return, so the share should decay, but the rule applies to the whole-session
  average. **NO_MILESTONE/DILUTION_PERSISTS (stop S4) is a live possibility, not a remote one.** The thresholds are the user's registered values and are not changed here.
- **First native contact is the run itself** for the rd2-specific paths (the `iterate2` proxy and the write guard against the real backend: both ran against a fake game that speaks the
  M1d protocol through the real lifecycle code, not against BattleShip). A mismatch in P1 or an open identity replay is INVALID and the session stops there.
- **Throughput.** The exploration needs 667 ticks/s to be valid; rd1 measured 1,560. A much slower machine state (a concurrent heavy job) could make it INCOMPLETE; readiness is judged
  at launch and the tree sampler stops the run on a memory breach.
- **Verification can hit its caps** if a left-of-wall lineage yields many candidates and none qualifies early (about 8 s per replay, three at a time): INCOMPLETE only when an unverified candidate could raise `m`.
- **A rebuilt executable or a changed `.o2r` file during the run** is a pin drift (INVALID), by design. The user's other sessions share the machine; the frozen configuration protects the run from configuration edits.
- **`BOUND_VIOLATION`.** The bound is an upper bound derived from decomp data and agent flights, assumed correct and falsified live if ever wrong; a violation is recorded with any outcome and stops the line (S5).
