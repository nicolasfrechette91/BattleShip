# M8-rd1 preparation: implementation record (2026-10-02)

**Status: zero-native-tick preparation.** The proposal (`docs/rl_m8_rd_proposal_2026-10-01.md`, revision 2) and amendment 1
(`docs/rl_m8_rd_amendment_2026-10-02.md`) are implemented in new files. Before this record was written nothing had launched
BattleShip or consumed a native tick. Nothing was committed or pushed and no branch was created. No tracked file was modified; the
proposal and every earlier M7 file are byte-identical to `HEAD`.

**Scope label**, carried by every M8-rd1 record: *return-based archive exploration (arm T) against a matched no-return control (arm C)
from the normal tick-0 reset; one session, one set of keyed draws; not a policy result, not a learning result.*

## 0. Summary

| item | result |
| --- | --- |
| **Unit suite** | **48 / 48** (`python rl/m8_rd_tests.py unit`, about 2 minutes), including every unit named in section 5 |
| **Production-count synthetic end-to-end** | **PASS** twice, on two synthetic worlds: three million ticks in arm T, 2.7 million in arm C (so the comparison point is 2,700,000 and arm T's later milestones are cut), five workers, the registered caps, the whole-tree sampler, 203 / 74 replays, 16 identity replays, close audit, `verify-run` (section 5) |
| **The real lifecycle code** | exercised without a game: `RealBackend`, the standby lifecycle, the frozen configuration, the executable pin, `finish()` on a clear, cold fallback, process death, the readiness contract, `m7f_trace.run_stepping_trace`, and the whole `cmd_run`, all against a fake game process that speaks the M1d protocol (section 5) |
| **Real recorded data** | the cell key reproduces the proposal's 14,360 cells and 39 masks on the 400 preserved random episodes (scratch run, section 5); the per-tick record digests are identical across processes and flag sets; the registered analyser verifies M7p's recorded qualified crossing |
| **Budgets** (section 6) | at most 6,410,000 native ticks; **expected wall 33-43 min, modelled pessimistic 51.4 min, every cap binding 60.0 min** against the 60-minute session cap; main process about 0.5 GB, whole tree about 4.9 GB private (measured basis below) |
| **Preflight** (section 7) | passes every check except **the missing approval record**: it refuses for exactly that one reason (unit suite 48 / 48, 409,077 `runs/` files covered, 0 uncovered, readiness met) |
| **Guide** | the external guide's M8 section is re-scoped and the old wording kept as superseded (section 8) |
| **Independent review** | a read-only review agent found seven defects and one throughput risk; all seven were fixed or recorded, each with a test (section 4) |

## 1. State

| item | value |
| --- | --- |
| parent | `main` = `origin/main` = `6a30c88` (the proposal commit); only new untracked files |
| submodules | `decomp e4f06348`, `libultraship 805f1950`, `torch 3aa9c97`; no native change; executable `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee` hashed, not run |
| compute | Python 3.13.2, six logical CPUs, 16.3 GB RAM |
| D: | base plus five verified `runs/` increments cover all 409,077 `runs/` files (0 uncovered) |

## 2. Files (all new)

| file | role |
| --- | --- |
| `rl/m8_rd_cells.py`, `m8_rd_explore.py`, `m8_rd_archive.py`, `m8_rd_claims.py`, `m8_rd_rule.py` | the contracts (pure, standard library only): section 3 |
| `rl/m8_rd_worker.py`, `m8_rd_run.py`, `m8_rd_finish.py`, `m8_rd_session.py`, `m8_rd_report.py`, `m8_rd_snapshot.py` | the worker, the engine, verification / decision / close, the CLI, the reports and the source snapshot tool |
| `rl/m8_rd_tests.py`, `m8_rd_stub.py`, `m8_rd_fakegame.py` | the tests, a synthetic world and a fake game process |
| `docs/rl_m8_rd_amendment_2026-10-02.md`, this record | |
| `logs/m8_rd_prep/` (Git-ignored) | the end-to-end outputs, the preflight record, the guide backup |

Nothing was written under `runs/` (the preflight requires `runs/m8_rd` absent and walks every `runs/` file against the D: backup).

## 3. The design as implemented

| proposal | module | what it does |
| --- | --- | --- |
| §4 cell `m8_rd_cell_v1` | `rl/m8_rd_cells.py` | key `(bx, by, res, mask, floor)` from one `SSB64_RL_SPATIAL=1` reply on live steps; resource class from `btt_action_class_table_v2` (X takes precedence, then ground, then A0 / A2 / A1 by `jumps_used`); per-tick record and chain digest; the burst scanner (breaks, first wall-top landing, first left step, left-floor landing, left break, clear) |
| §5.3 `m8_rd_explore_v1` | `rl/m8_rd_explore.py` | keyed sha256 draws: a word uniform over 72 and a hold from {1, 2, 4, 8, 16}, clipped; a "word" is one native tick's Track 1 index |
| §4.3, §5, §8 archive | `rl/m8_rd_archive.py` | cells, bursts, selection `m8_rd_select_v1`, replacement and doom, lineage with a **pinned start representative**, the ordered event ledger, atomic checkpoints, the ledger rebuild and audit, the coverage-only set of arm C |
| §7.3, §7.4, §11.2 claims | `rl/m8_rd_claims.py` | per-arm ledger (cumulative position), candidate registry, the comparison-point truncation, the replay evaluator (exactness, break table, claimed event tick, predicates, the M7d four-fact clear) and the replay planner |
| §11.3 rule | `rl/m8_rd_rule.py` | `m8_rd1_rule_v1`, the comparison point, `could_change`, self-test |
| §13 worker | `rl/m8_rd_worker.py` | lean worker on `battleship_process` / `battleship_client` / `m7_standby`; jobs `tick0`, `iterate` (return then burst), `control`, `trace`, `reverify`; frozen configuration and executable pin checks before every launch; the provenance guard |
| §13 session | `rl/m8_rd_run.py`, `rl/m8_rd_finish.py`, `rl/m8_rd_session.py` | engine (P1, arm loops with tick reservations and wall caps, clock, pool), verification / decision / close, and the CLI (status, preflight, approval-template, run, verify-run, reverify) |
| §8.3, §9 | `rl/m8_rd_report.py` | reported readings, read-only `verify-run`, the rebuilt-executable plan and its cost projection |
| §11.5 snapshot | `rl/m8_rd_snapshot.py` | the verified D: source snapshot (`snapshot`, `verify`, `powershell`) |
| tests | `rl/m8_rd_tests.py`, `rl/m8_rd_stub.py`, `rl/m8_rd_fakegame.py` | unit suite, production-count synthetic end-to-end run, a synthetic world, and a fake game process that speaks the M1d protocol so the REAL lifecycle code can be exercised |

**Process architecture.** The session process spawns five worker processes (Windows `spawn`); each owns one BattleShip standby slot and runs one job at a time
over a pipe. The parent is single-threaded for ingestion (completion order), samples the whole process tree every 5 s (M7u3's sampler, reused) and
checkpoints the archive every 5 minutes. Top-level imports of the launching script are light, because spawned workers re-import it.

**The budget cut (amendment 1).** See the amendment record, section 2: a tick allowance is reserved at dispatch; the job that gets less is cut there.

**Asynchronous ingestion and lineage.** A cell may be replaced while a job that started from its older representative is still running. The dispatch records
`(cell, representative, L)`; the result must match it; the burst pins the representative it replayed (`start_rep`), so every cell's words reconstruct exactly
whatever happened to the start cell afterwards. This was found by the five-worker test (a first version compared against the cell's current representative
and refused a late result).

**Checks per return** (every iteration, every identity replay): the non-consuming `observe` equals the pinned tick-0 record in every field but `host_frame`
(which is reported) including the digest of the observe-only line table; every word is one `step` with `consumed_tick == i`, `input_tick == i + 1`, step count
`i + 1`, state WaitingForAction and no native failure; at L the observation, the record digest and the chain digest equal the archive's. A corrupted end
record is refused (a step of the session's own P1; tested offline against the stub and through the real lifecycle code).

**Verification.** After both arms: the comparison point; per arm, the max-t candidate and, per milestone in discovery order until one qualifies, the other
candidates, replayed in a fresh process with all four read-only diagnostics (at most three at a time, the frozen configuration), every raw reply kept; a
replay counts only if the native action digest, every consumed tick, the break table and the claimed event tick agree (an inexact replay is INVALID) and
the milestone predicate comes from the registered analyser (`m7n_crossing.analyse_trace`, `btt_qualified_crossing_v1`, unchanged). The close identity
replays (K = 16 cells: the shortest wall-top cell, left-of-wall cell, left-target-broken cell and top-three-level cells, then keyed random cells) run on the
workers that stay, concurrently. Routes of verified claims are stored under `runs/m8_rd/routes/<arm>_<claim>/` (actions.jsonl in the M4 form, metadata, the
replay's full trace; both completion clocks for a clear).


## 4. Findings during preparation, and the independent review

**Found by my own tests.** (a) **Asynchronous ingestion:** the first five-worker test refused a late result because it compared its start representative with the
cell's *current* one; a cell can be replaced while a job started from the older representative is still running. The fix pins the dispatched
`(cell, representative, L)` and the burst's start representative. (b) The stub's `time_passed` did not follow the real clock relation (`time_passed` =
`input_tick - 1`), which the result JSON check caught. (c) **Terminal cells:** the last tick of a native-failure or clear cell's prefix is the end itself; an
identity replay of such a cell is expected to end there, and anywhere else is a mismatch (a keyed 16-cell identity sample hits a terminal cell about once in two
samples; this would have been a false INVALID).

**Independent read-only review** (a general-purpose agent, 58 tool uses, no edit rights). Its findings and what changed:

| finding | disposition |
| --- | --- |
| 1. no Windows retry on `os.replace` / `rmtree` (state file every 30 s, checkpoints) | **fixed:** bounded retries (`m8_rd_archive.replace_retry`, `rmtree_retry`); periodic state and checkpoint failures are logged and retried, never fatal; test `windows_retries` |
| 2. claim verification replayed one candidate at a time when `crossing` and `left_target` share a pool | **fixed:** the batch is filled round-robin over the unsatisfied milestones, each pool in discovery order (the order is unchanged; up to three replays run); test `claims_batch_fill` |
| 3. the live configuration is copied by `prepare_worker_runtime` before the frozen copy replaces it; an `OSError` there stopped the arm | **mitigated, convention kept** (section 9, item 9): retried four times and mapped to a startup failure (a lifecycle failure, redrawn); the frozen copy is installed and re-hashed before every launch; test `real_backend_retry_and_evidence` |
| 4. the process-count cap (10) has no headroom over the steady state (5 + 5) | **fixed:** a stop needs two distinct samples above 10, the cap itself is unchanged; test `process_count_debounce` |
| 5. a failed process's native log was deleted; a failed `finish()` after a clear dropped the whole job | **fixed:** the episode directory of a failed process is kept; a failed finish is recorded as `finish_error` and the trajectory (the clear) is kept for verification; tests `finish_error_keeps_the_clear`, `real_backend_retry_and_evidence` |
| 6. verification could starve the second arm's max-t candidate; replay directories could collide | **fixed:** both arms' max-t candidates are replayed first and the arms alternate; a free-slot pool gives each live replay its own port-block rank; the work directory carries the replay's label |
| 7. no hard cap after a stop | **fixed:** the session cap and the job timeout are checked after a stop too; a worker still busy 90 s after a stop is terminated (the job object reaps its games); test `unresponsive_worker_is_terminated` |
| 8. throughput: six CPUs, early iterations boot-bound | recorded (section 6): the 1,500,000 floor needs 962 ticks/s |

The review also found the archive, selection, doom, allowance, truncation, rule precedence, the Track 1 tables, the spawn safety and the provenance guard
correct; its randomized asynchronous simulation (12 seeds) passed the ledger audit.

## 5. Tests

**`python rl/m8_rd_tests.py unit`: 48 / 48.** Approval is tested on isolated temporary records, so the suite stays valid after a real approval exists.

| group | cases |
| --- | --- |
| cells and record | `cells_contract` (resource-class table, key, bins, native-failure rule, tables equal `btt_learning` / `m7h_curriculum`), `cells_on_recorded_replies` (real replies: the mask-derived break table equals the native one, the words digest equals the recorded one), `cell_count_on_probe_prefix` (1,003 cells on five real episodes), `record_digests_across_flag_sets` (identical per-tick records from separate processes with different diagnostic flags: two fixtures, three runs, 18,480 ticks) |
| explore | `explore` (keyed, uniform over 72 words and 5 holds, clipping, mean hold 6.2, key strings) |
| archive | `archive_ingest_rules`, `archive_async_ingestion`, `velocity_reversal_reading`, `selection` (40,000 draws against the analytic probabilities), `ledger_rebuild_and_audit` (five tampering kinds detected), `checkpoint_atomicity` (a crash at every step leaves a verifying checkpoint), `coverage_set` |
| claims | `claims_ledger_rules`, `claims_roundtrip_on_stub` (every kind of candidate replays exactly; six tampering kinds are inexact), `real_analysis_on_recorded_trace` (**the registered analyser on a REAL replay**: M7p's seed-1 qualified crossing, left-target break and wall-top landing, and a truncated copy credits no crossing), `clear_facts`, `claims_batch_fill` |
| worker | `worker_iterate_and_returns` (tamper in the end record, digest, chain, integer type, tick-0 record; allowance cuts; abort; lifecycle; a consumed-tick violation preserves its raw replies), `worker_horizon_fall_clear_control`, `worker_trace_and_reverify`, `terminal_cells_are_returnable`, `finish_error_keeps_the_clear` |
| session (real worker processes, stub backend) | `session_small_run`, `session_budget_exact_cut` (a cap of 7,777 committed exactly), `session_truncation_at_the_slower_arm`, `session_outcomes_and_stops` (below the minimum, redrawn lifecycle failures, more than three, an integrity mismatch, a provenance violation, a memory stop, a process-count stop, a wall-capped arm), `session_verification_cap`, `process_count_debounce`, `unresponsive_worker_is_terminated` |
| **real lifecycle code, fake game** | `real_backend_with_fake_game` (standby promotion, a return, a tampered chain, cold fallback, every launch read the FROZEN configuration and none the live one, clear finished natively with both clocks, process death classified, a game that lies about its flags refused, frozen-file drift and executable / runtime-file drift refused), `real_backend_retry_and_evidence`, `session_real_backend_fake_game` (the whole engine, the real `m7f_trace` replay path, no leftover process), `cmd_run_with_fake_game` (S0, the preserved runnable copy, the open record, the tree sampler, `run_all`) |
| pins and guards | `frozen_runtime_and_preserve`, `controller_cvars` (the live configuration has none), `provenance_guard`, `clock_and_caps` (every registered cap), `approval_isolated` (about 70 altered identity entries refused), `readiness`, `identity_and_pins`, `rule_module`, `source_guard`, `import_isolation`, `tracked_files_unchanged`, `windows_retries` |
| reports and tools | `report_readings`, `verify_run_detects_tampering`, `snapshot_tool` |

**Real-data validation (scratch scripts outside the repository, not evidence files).**
- **The key.** `m8_rd_cell_v1` on the 400 preserved random-play episodes (`runs/probes/action_hold`): 6,578 / 10,009 / 12,192 / **14,360** cells after
  100 / 200 / 300 / 400 episodes and **39 masks**: exactly the figures of the proposal's section 4.2, so the resource-class and floor conventions are the proposal's.
- **Breaks.** The (id, consumed tick) table derived from the live-target mask equals the native target-identity table on 12 episodes (and on the pinned traces).
- **Tick 0.** Real tick-0 is live, `idle_ground`, key `(0, -9, G, 1023, 4)`.
- **Records.** For the two pinned P1 traces and two more fixtures, the per-tick record digests are identical between a run with entity + spatial + target diagnostics, one
  with those plus the input diagnostic, and a repeat in another process (13,121 ticks).

**`python rl/m8_rd_tests.py e2e [--world hard|easy]`.** `run_all` at the registered counts against the stub (synthetic: nothing about Mario).

| item | hard world | easy world |
| --- | --- | --- |
| ticks (arm T / arm C) | 3,000,000 / 2,700,000 | 3,000,000 / 2,700,000 |
| comparison point | 2,700,000 (arm C is the slower arm; arm T's candidates beyond it are not replayed) | same |
| cells T / C | 3,661 / 3,699 | 10,301 / 24,186 |
| candidates T / C | 1,030 / 1,308 | 2,353 / 1,472 |
| replays, replay ticks | 203, 207,906 | 74, 49,635 |
| verified milestones | T left-target t 6, C left-target t 4 (PASS, +2 targets) | both clear, t 10 (NULL) |
| main-process private peak | 420 MB | 525 MB |
| whole tree private / working set | 527 / 397 MB (6 processes) | 561 / 432 MB |
| identity replays | 16 / 16 | 16 / 16 |
| close audit, `verify-run` | pass, pass | pass, pass |

## 6. Budgets

Basis (measured, preserved): action-hold probe (per-worker 789 ticks/s plus 2.22 s per start, fitted over 400 episodes; mean 3,075 ticks per random episode),
M7h campaign dispatch (1,299-1,367 prefix ticks/s per worker), M7f diagnostic replay (2,933 ticks/s aggregate at N = 5), M6 raw (2,112 per worker), and M7u3's 398
whole-tree samples (median 6,460 MB private and 2,781 MB working set with 10 BattleShip processes).

**Native ticks** (cap 6,410,000 = 10,000 + 2 x 3,000,000 + 400,000):

| phase | expected | cap |
| --- | ---: | ---: |
| P1: pinned traces 3,361 + 2,560, a 120-tick keyed burst, three returns of at most 120, one corrupted return | about 6,300 | 10,000 |
| arm T, arm C | 3,000,000 each (an arm capped by its wall cap is valid from 1,500,000) | 3,000,000 each |
| verification: claims (every candidate up to 3,600 ticks) + 16 identity replays (each at most 3,480) | 50,000-130,000 | 400,000 |
| **total** | **about 6.06-6.14 million** | **6,410,000** |

**Wall time** (a worker's iteration is `max(2.22 s boot, ticks / r)` with the standby overlapping the boot, or `2.22 + ticks / r` when boots serialise):

| phase | expected (r = 1,300, overlapped) | pessimistic (r = 789, serial, mean L + 120 = 1,350-1,580) | cap |
| --- | ---: | ---: | ---: |
| P1 (start-up of five workers included) | 0.6 min | 1.5 min | 3 min |
| arm T, 3,000,000 ticks | 14-20 min (2,500-3,560 ticks/s) | 27-29 min needed, so **the 26-min cap binds at 2.7-2.9 M ticks** (valid; 1.5 M needs 962 ticks/s) | 26 min |
| arm C, 3,000,000 ticks (mean episode 3,075 ticks) | 8-13 min | 19.9 min (2,513 ticks/s) | 24 min |
| verification (claims on 3 threads + identity on 3 workers) | 1-2 min | 4 min | 7 min |
| **session from P1** | **about 24-36 min (33-43 with slack)** | **1.5 + 26 + 19.9 + 4 = 51.4 min** | **60 min** |
| every cap binding | | | 3 + 26 + 24 + 7 = **60.0 min** |

Early iterations are boot-bound (prefix 0, mean L + 120 about 120-300: 250-580 ticks/s aggregate with serial boots); the model's means include that ramp. The caps
sum to exactly 3,600 s, so the session cannot exceed its cap by construction; the S0 open and S2 close are outside the clock. **Nothing was trimmed.**

**Memory.** Main process: 420-525 MB private in the production-count synthetic runs (a Python process with the archive of 3,700-10,300 cells and the torch import of
the tree sampler); the archive costs about **1.84 KB per cell** (measured on 41,956 synthetic cells and 3,000 bursts: +75 MB), its checkpoint files **33 MB** at that size
(`cells.jsonl` 18.7 MB, `bursts.idx.jsonl` 14.2 MB), written in 0.9 s; selection 1.2 ms. Projection for 15,000-40,000 cells: main process **0.5-0.6 GB** against the
3,072 MB cap. Workers are lean (about 16 MB each in the run above). BattleShip: from M7u3 (10 processes: 6,460 MB private, 2,781 MB working set, with main and
five gym-stack workers included), about 430 MB private and 250 MB working set each; projected tree **about 4.9 GB private, 2.4 GB working set** (M7u3's observed maximum
7.0 GB / 3.2 GB), against the caps 9,216 / 4,096 MB. System minimums: 1,024 MB available, 2,048 MB free commit.

## 7. Preflight (zero native ticks, before any approval record exists)

`python rl/m8_rd_session.py preflight` (2026-10-02, final code; output in `logs/m8_rd_prep/preflight_noapproval.json`):

| check | result |
| --- | --- |
| unit suite, rule self-test | **48 / 48**; `m8_rd1_rule_v1` digest `e0bbfe21...`, no problems |
| tracked tree and HEAD | no tracked file differs from `6a30c88`; `git status` shows only new files (15 at that moment) |
| executable, runtime files | `30a3913b...` (hashed); `BattleShip.o2r`, `f3d.o2r`, `gamecontrollerdb.txt` hashed as files, never inspected |
| controller-rule CVars | absent in the live configuration |
| pinned P1 traces | both consistent (native digest = recorded digest = trace digest; consumed ticks 0..n-1; flags include spatial) |
| D: coverage | all 409,077 `runs/` files covered over the base and five increments, **0 uncovered** |
| processes, `runs/m8_rd` | no BattleShip process; `runs/m8_rd` absent |
| readiness | 6,897 MB available (minimum 4,096), 18,393 MB free commit (10,240), 112 GiB free on C: and 1,590 GiB on D: (5 each) |
| **approval record** | **refused: none exists** (expected) |

## 8. The guide

`..\guide.md` (outside the repository, not version-controlled; a backup is `guide.md.bak_2026-10-02_pre_m8_rescope` beside it and `logs/m8_rd_prep/guide.md.pre_m8_rescope`).
- Section 10 now opens with the re-scoped **M8: route discovery by archive exploration**. Phase 1 finds a full clear from tick 0, verified by exact replay (first bounded
  session M8-rd1, rule `m8_rd1_rule_v1`); phase 2 robustifies discovered routes into a tick-0 policy, later and not designed. The constraints that carry over are listed.
- The **old M8 wording is kept verbatim** under a "SUPERSEDED (2026-10-02)" heading with a note saying where each part went.
- **Frame-perfect polishing toward the TAS** moved to a new **M11** (section 12a) with the old M8a / M8b / M8e / M8f gates renamed M11a-d; the milestone table has the M8 and M11 rows;
  the goal paragraph (Track 2) and the next-steps list carry the re-scope; the header says what was changed on which date.

## 9. Implementation interpretations (what the proposal, section 14 and the amendment do not spell out)

None changes a registered definition, budget, threshold, the rule or the cell, selection and explorer contracts. Each is listed so it can be overruled.

1. **Process architecture.** Spawned worker processes over pipes, completion-order ingestion in a single-threaded parent (the proposal's asynchronous ingestion).
2. **The cut at the budget** is a tick allowance reserved at dispatch (amendment, section 2). **A job aborted at a wall cap is not committed**; its ticks do not count toward the arm or toward T.
3. **Cells store a compact end record**: the 17 observation values, the sha256 of the full canonical per-tick record (observation without `host_frame`, the spatial fighter block, groups,
   live-target mask and positions, state and step count) and the chain digest; every one of them is compared at a return, so the full record is compared. The full record per cell would have been 100 times larger than the proposal's projected 10-40 MB.
4. **A burst pins the start representative it replayed** (needed for exact lineage under asynchronous ingestion).
5. **Candidates**: the registry follows the proposal's list. The events are taken over the post-prefix part of a trajectory (the prefix's events belong to the job that created it); a
   `left` candidate is a burst with a live step left of x = -2,100, a landing on floor line 3 or a left-target break; `l0` is the first grounded live tick on floor line 0; `t` keeps, per
   number of targets, the strictly shorter trajectories in discovery order; a `t` or `l0` candidate's words stop at its event, the others run to the end of the counted part of the job.
   A replay is evaluated for every milestone and credits each it satisfies. Candidate order is discovery order; the replay cap is 400,000 ticks and, by the proposal's table, the verification wall cap is 7 minutes.
6. **Identity sample at the close**: the shortest wall-top cell, left-of-wall cell and cell with a left target broken, the shortest cell of each of the top three levels, then keyed random cells (sha256 of
   `m8_rd|<archive id>|identity|<cell id>`) up to K = 16; cell 0 is covered by P1. Identity replays are returns on the three workers that stay (the other two are retired to keep within ten processes).
7. **Caps that are not arm caps** (P1, verification, the session): a stop there is INCOMPLETE (the proposal's INCOMPLETE conditions read as "not a performance result"); a replay-cap or wall-cap stop in verification is
   INCOMPLETE only when unverified candidates could change the outcome (the proposal's wording) or an arm's max-t candidate was left unverified. After a hard INCOMPLETE reason (memory, process count, session cap, more than three
   lifecycle failures, a worker error) the remaining phases are not run; after an arm's own wall cap they are.
8. **Operational timeouts** not in the proposal: a job in flight for 900 s stops the arm; 20 s grace for jobs in flight at an arm wall cap, then abort; a worker still busy 90 s after a stop is terminated; start-up 60 s,
   ready 180 s, request 30 s, exit 30 s per process; the process-count cap needs two distinct samples above 10.
9. **`prepare_worker_runtime` is used as prescribed** and therefore copies the live configuration transiently; the frozen copy replaces it and is re-hashed before the launch, the copy is retried on a sharing violation, and nothing else
   reads the live file after S0 (S0 reads it once to freeze it). The executable and the three read-only runtime files are re-hashed before every launch (a pin drift is INVALID).
10. **The reported readings** (section 11.3) are computed offline by `rl/m8_rd_report.py` from the session directory; for arm C, which keeps cell keys only, positions are bin ceilings.
11. **P1** replays the two shortest pinned Track 1 artifacts' words and compares every reply's record digest with the pinned traces (recorded with all four diagnostics; spatial-only records are identical, section 5); the return self-test
    uses a keyed burst from cell 0, returns three of its cells from fresh processes and requires a corrupted end record to be refused.

## 10. Launch conditions (the user's Part B) as evaluated

| # | condition | state |
| ---: | --- | --- |
| 1 | every unit test and the synthetic end-to-end test pass | **yes**: 48 / 48; end-to-end PASS in both worlds |
| 2 | the pessimistic wall projection fits within the 60-minute cap with no trimming | **yes**: modelled 51.4 min; every cap binding 60.0 min; nothing trimmed |
| 3 | preflight refuses solely for the missing approval | **yes** (section 7) |
| 4 | `git status` shows only new files; the proposal and all earlier M7 files byte-identical | **yes** |
| 5 | no design decision had to be made that the proposal, section 14 and the amendment leave open | **no registered definition was left open**; the mechanical interpretations of section 9 were needed and are recorded; none changes a registered quantity |

## 11. Remaining risks

- **First native contact is the run itself** (P1: the pinned traces, the self-test): the real lifecycle code ran only against a fake game. A mismatch in P1 is INVALID with the session unable to proceed.
- **Throughput.** The 1,500,000-tick floor needs 962 ticks/s per arm; measured anchors are 1,200-2,900 aggregate (M7f, the probe) and the model gives 1,700-3,500 for arm T.
- **Verification can hit its caps** if a left-of-wall lineage yields hundreds of candidates and none qualifies early (about 8 s per replay, three at a time, 7 minutes, 400,000 ticks): INCOMPLETE if the unverified ones could change the outcome.
- **A rebuilt executable or a changed `o2r` file during the run** is a pin drift (INVALID), by design.
- **The user's other sessions** (replay viewer) share the machine; the frozen configuration protects the run from configuration edits, and memory readiness is judged at launch and by the sampler.
