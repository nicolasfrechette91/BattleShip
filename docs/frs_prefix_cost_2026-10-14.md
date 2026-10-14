# Prefix replay cost (2026-10-14)

## 0. Status, scope and verdict

**Status: read-only investigation; zero native ticks.** No BattleShip.exe, self-check, smoke, planner, suite or lab run was started. Nothing
under `rl/`, `tools/`, `port/`, `decomp/`, `C:/BattleShip_lab/`, `runs/` or D: was created, modified or deleted. New files: this record and the
git-ignored working files under `logs/frs_prefix_cost/` (four `python -B` scripts, standard library plus a read-only import of `rl/m8_rd_cells.py`,
and their printed outputs). Checkout `C:/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip`, branch `main`, HEAD = `origin/main` = `17ce7e4`
("Add the light review of the fast-route lab"), clean with nothing staged before and after. Night 1 runs the committed code (digest
`0b248a9e30304325`) unchanged.

**Verdict in one paragraph.** The prefix is 91 to 93 % of the ticks but only 41 to 48 % of a worker's time. A job of about 4.0 s is: prefix
stepping 1.65 to 1.95 s, burst stepping 0.12 to 0.19 s, waiting for the standby process 0.7 to 0.9 s, and 1.1 to 1.2 s outside the job's clock
(process close, result transfer, selection). One prefix tick costs 1.1 to 1.4 ms under load, of which the native frame is about 0.28 ms and the
Python checks 0.07 ms; the rest is the per-tick round trip (socket, four thread hand-offs, JSON) under contention. The right first build is not the
native operation but two Python-only levers (close off the critical path; standby timing and a second standby) measured in one throughput night,
then the native batched prefix as a streamed-records operation under a default-off flag, whose equivalence is proved by byte-identical per-tick
replies. Together they project 2.3 to 3.1 times the dispatches per night, bounded by two things this record cannot measure: the CPU cost of a
process boot and the main process's selection time at higher dispatch rates.

## 1. Sources and method

- Read: `docs/project_handoff.md`; proposal `docs/rl_m8_fast_route_proposal_2026-10-13.md` sections 2.1 to 2.3, 6.3 to 6.5 and Q13; review
  `docs/rl_m8_fast_route_proposal_review_2026-10-14.md` (M1, M5, S6, N3, N4 and section 2); `docs/frs_lab_review_2026-10-14.md`; the
  deferred batched-prefix row of `docs/rl_m9_g2_stop_review_2026-10-06.md` (section 2 table and Q9); `docs/rl_m8_sd2_review_2026-10-13.md`
  section 2.2; `docs/rl_throughput_m6.md` and its JSON (`docs/rl_throughput_m6_experiments.json`); `docs/rl_transport_m1d.md` (additive-op rules).
- Code, whole or the parts named: `rl/frs_worker.py` (whole), `rl/frs_run.py` (pool, explore loop, boundary, commit, verification),
  `rl/m8_rd_worker.py` (`RealProc`, `RealBackend`, `_step`, `_tick0`, `_finish_proc`, `_stamp`, `remove_tree_retry`), `rl/m8_rd_cells.py`
  (record, digest, chain, key, scanner), `rl/battleship_client.py` (whole), `rl/battleship_process.py` (launch, readiness, finish, close),
  `rl/m7_standby.py` (`_run`, `acquire`), `rl/m7_runtime.py` (`prepare_worker_runtime`), `rl/frs_verify.py` and `rl/m7f_trace.py`
  (`run_stepping_trace`), `rl/m8_rd_run.py` (`WorkerPool`); native `port/rl/rl_transport.cpp`, `port/rl/rl_step.cpp`, `port/rl/rl_boot.cpp`,
  `port/rl/rl_observation.cpp`, `port/rl/rl_spatial.cpp`, `port/rl/rl_result.cpp` (whole), `port/gameloop.cpp` (`PortPushFrame`),
  `decomp/src/sc/sc1pmode/sc1pbonusstage.c` (the PORT controller hook).
- Data, read-only: `C:/BattleShip_lab/smoke_2026-10-14/run/` (`iterations.jsonl`, `summary.json`, `run_log.jsonl`, `verifications.jsonl`, the four
  trace files, `config.json`) and `selfcheck/`; `runs/m8_rd_sd2/sessions/sd2/iterations_T.jsonl`, `arm_T.json`; `runs/m8_rd_sd2/launch/`
  (`session_stdout.txt`, `machine_samples.jsonl.txt`). No ROM, TAS, recording or RNG material was read.
- Method: per-job records carry `wall` (job clock from the first line of `run_iterate_frs` to `_stamp`, before `proc.close()`), `step` (the sum
  of the `proc.step` round trips), `ask` (boundary questions) and, in sd2, `wait_s` (the standby wait inside `acquire`). The worker-seconds of a run
  (workers times explore wall) minus the sum of `wall` is the time outside the job clock. Linear fits of `step` and of `wall - step - ask`
  against ticks separate per-tick from per-job costs. The Python per-tick work was timed offline on the smoke's recorded replies.

## 2. Where a job's wall time goes

### 2.1 The pipeline, step by step

1. **Standby boot** (`m7_standby._run` on a thread per worker, launched at the previous `acquire`): re-hash the pinned executable and runtime
   files, create a private runtime directory (file copies plus junctions), spawn BattleShip.exe, connect, poll `status` every 50 ms until
   WaitingForAction at step 0, then `observe` + `status` (readiness proof). Boot wall: 2.04 s unloaded (the self-check's reference replay),
   2.18 to 4.82 s under the smoke's load (its four verify replays), implied median 3.76 s in sd2 (p25 2.94, p75 4.72).
2. **Acquire / hand-off** (`RealBackend.acquire`): wait while the standby is STARTING, re-verify it (`status` + `observe`, a few ms), promote it,
   launch the next standby. The wait is the standby's remaining boot: sd2 mean 0.89 s per job (71.7 % of jobs waited; p50 0.59 s, p90 2.28 s);
   the smoke does not log it separately, but its per-job constant of 0.72 s (section 2.2) is the same quantity.
3. **Tick 0** (`_tick0`): one `observe`, record with the line-table digest, compare with the pin: about 18 ms per job (sd2 fit intercept).
4. **Prefix stepping**: L single `step` requests with the per-tick checks; 1,414 ticks per job in the smoke, 1,453 in sd2.
5. **Burst stepping**: n `step` requests plus key / reach / scanner work; 139 words per job in the smoke (continuation), 106 in sd2.
6. **Boundary question** (CONT only): 10 ms per job in total (`ask`), 0.22 s over the whole smoke.
7. **Finish** (clears only): wait for the native exit, read the result JSON.
8. **Close** (`proc.close()`, after the job clock stops): `terminate()`, wait, remove the runtime and episode directories (`remove_tree_retry`,
   0.25 s steps on a sharing violation). Then the result is pickled to the main process, ingested (0.34 ms), and the next job is selected
   (82 ms per dispatch in the smoke at 50 k cells, 53 ms in sd2) and sent.
9. **Verification** (clears): two fresh-process replays with the verify flags on a borrowed explore slot: 19.8 s (reference, 1,885 words) and
   24.3 s (1,930 words) in the smoke, that is two boots of 2.2 to 4.8 s plus stepping at 1.2 to 2.8 ms per tick.

### 2.2 Per-job budget

| item | smoke (CONT, N = 5, 312 s, 383 jobs) | sd2 arm T (N = 5, 3,004 s, 3,769 jobs) |
|---|---|---|
| worker-seconds / jobs = budget per job | 1,561 s / 383 = **4.08 s** | 15,021 s / 3,769 = **3.99 s** |
| prefix stepping (step x L / ticks) | 1.95 s (47.8 %) | 1.65 s (41.3 %) |
| burst stepping | 0.19 s (4.7 %) | 0.12 s (3.0 %) |
| standby wait inside the job | inside "other" (fit constant 0.72 s, 17.7 %) | 0.89 s (22.4 %) |
| other inside the job clock (tick 0, Python per tick, finish) | 0.83 s incl. the wait; fit 723 ms + 0.072 ms per tick | 0.13 s; fit 18 ms + 0.072 ms per tick |
| boundary questions | 0.01 s | none |
| outside the job clock (close, transfer, ingest, select, verification borrow) | **1.09 s (26.8 %)** | **1.20 s (30.0 %)** |
| ticks: total / prefix share | 595,005 / 91.0 % | 5,874,929 / 93.2 % |
| jobs per worker-hour; machine ticks per second | 885; 1,906 | 903; 1,956 |

The 92 % of ticks is therefore 41 to 48 % of the time. The standby wait and the time outside the job clock, both per-process costs of the
restart, add up to 44 to 52 %. The selection accounts for 53 to 82 ms of the outside time; the verification borrow for 44 s of the smoke's 1,561
worker-seconds (2.8 %); the rest (about 1.0 s per job) is the close, the result transfer and the main loop's latency, which no record splits.

### 2.3 Per tick: round trip against native update

| quantity | value | source |
|---|---|---|
| `step` round trip under load | 1.378 ms mean (median 1.376, p10 0.82, p90 1.90); fit 1.331 ms per tick + 73 ms per job | smoke `iterations.jsonl` |
| same, sd2 | 1.140 ms mean; fit 1.118 ms per tick + 25 ms | sd2 `iterations_T.jsonl` |
| same, flat across levels | 1.31 to 1.62 ms (smoke), 1.12 to 1.21 ms (sd2) | per-level fits |
| unloaded round trip, N = 1, no spatial, verify-off | 0.482 ms median; child CPU 0.347 ms per step | M6 experiments JSON |
| native segments at N = 1 | request to submit 0.015; submit to gate open 0.010; gate open to consume 0.243; consume to logic done 0.030; logic done to observation 0.000 ms | same |
| N = 5 aggregate without boots, no spatial | 7,197 steps/s = 0.69 ms per step per process | `docs/rl_throughput_m6.md` |
| verify-flag stepping, unloaded (self-check) / loaded (smoke) | 0.93 ms / 1.21 to 2.83 ms per tick | the five trace files |
| Python per prefix tick (parse 29.5 + record digest 29.9 + checks and chain < 5 us) | **57 us** (burst tick: 63 us; verify reply parse 78 us) | `d_pytick.py` on 1,885 recorded replies |
| explore reply size / verify reply size | 1,408 B (spatial 914 of it) / 3,732 B | same |
| pure loopback echo of a 1.45 KB reply (one Python process, two threads) | 56 us | same |

Reading: the native frame (event pump, scheduler, controller read, game update, capture) is about 0.28 ms of a loaded 1.1 to 1.4 ms tick
(20 to 25 %); the Python checks 0.07 ms (5 %); the remaining 0.8 to 1.0 ms (65 to 75 %) is the per-tick round trip itself: Python send, the
transport thread's select wake, JSON parse, `rlStepSubmit`, the main thread's condition-variable wake, the frame, the result hand-back to the
transport thread, the 1.4 KB JSON build and send, Python's recv. At N = 1 that round trip costs 0.2 ms; under the lab's load (five games, five
workers, up to five booting standbys, the main process and a verification on six logical CPUs) it is four to five times that. The split between
scheduling latency, contention and the JSON work cannot be measured without a loaded run with `SSB64_RL_TIMING=1`.

### 2.4 Ticks per second per process

| | prefix (stepping only) | burst (stepping only) | whole job (ticks / worker-seconds) |
|---|---|---|---|
| smoke | 726 per s | 726 per s (same per-tick cost) | 381 per s |
| sd2 | 894 per s | 894 per s | 391 per s |

Burst ticks per night at the smoke's rate: 615,611 per explore hour, so 4.4 M for night 1 (six runs of 72 min, N = 5).

### 2.5 Chain-digest computation and ingest

Per tick the worker builds the record (observation without `host_frame`, spatial fighter, groups, mask, target positions, state, step count),
serialises it canonically, hashes it and extends the chain: 31 us. Ingest is 0.34 ms per job; selection 82 ms per dispatch and growing with the
cell count (review M5). Digest computation is not a cost worth attacking; selection is (section 4.4).

## 3. What the prefix replay must check, and what it does beyond that

Needed per prefix tick to keep every guarantee: (1) the tick contract on the reply (`ok`, `op == "step"`, `spatial` present, `consumed_tick == i`,
`input_tick == i + 1`, `step_count == i + 1`); (2) the episode is still live (`state == WaitingForAction`, not `btt_native_failure_v1`) unless the
cell is terminal at L - 1; (3) the record digest and the chain step, because the chain at L is compared with the archive's `chain`. Needed at tick 0:
the pinned tick-0 record (with the line table). Needed at L: the 17-field end observation (without `host_frame`), `end_digest` and `chain`. Needed
per process: the executable and runtime pins before launch, the readiness proof, the flags.

Beyond that the worker keeps every raw reply in memory for the job (for `_preserve` on a mismatch), tracks mask changes for `breaks_all`, and polls
the abort flag every 16 ticks. All of it is inside the 0.072 ms per tick. There is nothing to remove on the Python side that would matter; the
cost is the one-request-one-reply structure, not the checks. Note the consequence for section 4.3: because the chain covers the full record of every
tick, any faster path must still produce every per-tick record (or a chain computed from an identical encoding).

## 4. Options

### 4.1 (a) Python-side

| option | guarantees | estimated gain (evidence) | cost, risks |
|---|---|---|---|
| a1 lighter prefix replies | breaks chain_v1 (section 3); the diagnostics are process-level flags | none on its own: parse + build is about 0.1 ms of 1.3 | not available |
| a2 pipelined submission (send word i + 1 before reading reply i; the transport already serves buffered lines back to back, `serveClient`) | words, order and consumed ticks unchanged; every reply still checked, but one reply late: on a prefix mismatch, a fall or a clear, k extra words have been consumed natively before Python sees it (the process is discarded anyway; the extra ticks are never recorded) | removes Python's 0.07 ms and one scheduler wake from the critical path: 0.2 to 0.4 ms per tick, x1.1 to x1.15 jobs (projection; unmeasured) | about 60 lines in the worker and client; changes the "checked before the next submit" timing; `request_timeout` and `finish()` after a clear need care; superseded by (c) |
| a3 cheaper digest / drop `raw` retention | kept | nil (31 us per tick) | not worth a digest change |
| a4 close off the critical path: terminate and remove directories on a background thread after the result is sent; the process cap counts closing processes | kept (the next process is a new one; nothing about the episode changes) | up to the outside-clock gap minus select: at most 1.0 s per job, x1.24 if the gap is mostly the close (unmeasured split) | about 40 lines; the lab process cap must allow one closing process per worker (owner's setting); a slow removal must not block the next acquire |
| a5 standby timing and a second standby per worker | kept | wait 0.72 to 0.89 s per job to about 0: x1.14 (smoke mix) to x1.29 (sd2); memory +5 processes, about +2.2 GB private (sd2: 4.4 to 4.7 GB for 10) against the 8,192 MB soft budget; the boots' CPU is unchanged but earlier | config switch + per-job fields `wait_s`, `standby_startup_s`, `close_s`, boot CPU seconds (GetProcessTimes at readiness): about 50 lines; measured in a dedicated night (decision Q13) |

### 4.2 (b) Scheduling

Without a savestate a process's position can only be extended, never rewound, so reusing a position means playing more words of the same
trajectory: that is continuation (R4, already an arm). Reordering jobs by shared prefix buys nothing: every job is one process playing one
trajectory from tick 0, and the draw is keyed and random by design. The remaining scheduling levers are per-process, not per-trajectory:

- b1 keep the boot covered: the wait is max(0, boot - previous job wall) per worker; sd2's data: previous job under 1 s -> 1.58 s mean wait
  (91 % wait), 2 to 3 s -> 0.82 s (70 %), 4 to 5 s -> 0.53 s (57 %). Faster jobs make this worse: after (c) every job is shorter than a boot.
  A second standby (a5) or a shared boot pool (M standbys in flight for N workers, decoupled from the workers) removes it regardless of job length.
- b2 verification on its own slot (a sixth process) instead of a borrowed explore worker: 2.8 % of the smoke's worker-seconds; memory for one more
  process; low priority.
- b3 level mix: a level-0 job replays 251 ticks, a level-9 job 1,845; the mix is the selection's business, never a throughput lever.

### 4.3 (c) Native batched prefix: protocol-level design

**Principle.** The harness sends a block of canonical words; the native side consumes them one input tick per word on the main thread, with the
gate held open between ticks (no parked iteration, no condition-variable hand-off per tick), checks the tick contract on every tick, and streams
back one reply line per tick that is byte-identical to today's single-step reply. Nothing is derived natively: Python computes every record
digest and chain exactly as now, so the archive's chain definition does not change and equivalence is a byte comparison.

**Messages** (one request, k + 1 reply lines; additive op under protocol 1, like `observe`):

- request: `{"protocol":1,"op":"step_block","actions":[[buttons,stick_x,stick_y], ...]}`; at most 256 actions per block (3.6 KB, inside the
  8 KB line limit); a prefix of 1,414 words is six blocks.
- per consumed tick, in order: exactly the `step` reply line of that tick (`{"protocol":1,"op":"step","ok":true,"step_schema":..,"state":..,
  "state_name":..,"step_count":..,"consumed_tick":..,"observation":{..},"spatial":{..}[,"targets","entity","input"]}`), built by the same
  functions as today, so a block's lines equal the lines a single-step replay would produce.
- trailer: `{"protocol":1,"op":"step_block","ok":true,"requested":K,"count":k,"stop":"count"|"episode_ended"|"native_failure"|
  "contract_error"|"stopping","first_step_count":..,"last_step_count":..,"error":null|{...}}`.
- refusals before any tick, as one `ok:false` line: `unknown_op` (flag off), `malformed_request`, `out_of_range`, `too_many_actions`, and the
  native codes `not_ready`, `busy`, `episode_ended`, `stopping` (nothing advanced).

**Stop rules, all generic (fields of `RLObservation`, no stage knowledge):** after each tick the main thread stops the block when k == K, when the
result is final (`btt_active` and `targets_remaining == 0`: EpisodeEnded, the deferred exit as today), when `btt_native_failure_v1` holds on the
captured observation (`game_status == 5` with targets left: the scene is unloading; a further submit would wedge), or on a contract error.

**Mismatch reporting.** A contract error is: the post-update `input_tick` is not `consumed_tick + 1`; the controller read for the tick did not
happen within two host frames; or the read reached the hook in a wrong state (the existing fallback-park cases). The block stops, the lines of
the completed ticks stay valid, the trailer carries `stop:"contract_error"` and `error:{kind, tick, expected, got}`, and the state machine enters
Stopping so no further `step` or `step_block` is accepted on that process (today's `rlStepWait` already reports Stopping as a native error). Python
raises `MismatchError("block_contract")`, preserves the replies, and the cell is quarantined or the run LAB_INVALID exactly as for `prefix_end`.
The Python checks (`consumed_tick`, `input_tick`, `step_count`, state, digest, chain, end record at L) run on every streamed line unchanged.

**Native shape** (PORT-only, default-off, additive): `rl_step.cpp` gains a pending-action block (`vector<RLAction>` + index) and an outbound queue
of results with their diagnostic copies; in `rlStepOnObservationDiag3`, ActionConsumed with a block active pushes the result to the queue, notifies,
and either sets the next action (ActionReady, gate stays open) or ends the block (WaitingForAction / EpisodeEnded / Stopping). `rl_transport.cpp`
gains `handleStepBlock`: validate, `rlStepSubmitBlock`, then loop `rlStepWaitBlockRecord` and send each line (JSON built on the transport thread,
in parallel with the next frame), then the trailer. `rl_boot.cpp` parses `SSB64_RL_STEP_BLOCK=1`, effective only with effective stepping; `status`
gains `"step_block":true` only when on (the same rule as the four diagnostic flags). With the flag off the op answers `unknown_op`, the new fields
are never entered, and every reply is byte-identical to today's. About 250 lines native, 60 in the client, 100 in the worker, plus tests.

**Why streamed records rather than a native digest.** A native chain would have to reproduce Python's canonical JSON (sorted keys, shortest
round-trip float repr, `-0.0`, `1.0`) byte for byte, or define a chain_v2 over a native encoding that the archive does not hold for its 49,928 cells
(the archive stores chains, not records, so chain_v2 could only be filled by replaying every cell). Records keep one chain definition, keep every
Python check, and make the equivalence proof a byte comparison. A digest trailer can be added later if the record stream itself is measured to be
the bound (section 7, Q2).

**Expected gain.** Per tick: the frame (0.28 ms at N = 1) plus queue work, with the JSON build off the main thread: 0.35 to 0.5 ms under load
(projection from the N = 1 segments; the contention share is unmeasured). Prefix stepping 1.95 s -> 0.5 to 0.7 s per job; alone x1.44 to x1.56 jobs
(`c_shares.py`); verification replays 20 to 24 s -> about 8 s (boot-bound). Bursts can use blocks of one segment later (the stream is known in
advance; the native-failure stop is generic): at most x1.1 more.

**Equivalence proof (all under authorisation, on the lab's imported executable copy, after archiving the new build):**

1. Flag off: the existing regressions (`rl/m6_equivalence_regression.py`, the M1e replay regression, the M2 lifecycle suite) on the new executable,
   and the registered identity replays (P1 tick-0 pin `2817d8cf3494`, the 16 open identity replays) in a zero-claim dry run: every pin must match.
2. Flag on against off: the six registered clears (2,315, 2,326, 2,086, 1,885, 1,929, 1,964) and the lab reference, each twice per mode in fresh
   processes with the verify flags; compare every per-tick reply line byte for byte, the chain at every tick, `completion_input_tick`,
   `completion_time_passed`, the result JSON and `host_frames`.
3. A stratified sample of 200 archive cells (20 per level): replay each prefix with blocks and compare the end record, `end_digest` and `chain` at L
   with the archive's stored values (the same check the worker makes).
4. A 10-minute lab smoke with the flag on: `tick0_unequal` 0, quarantines 0, reference VERIFIED exact, every in-run clear VERIFIED; the same smoke
   with the flag off for the throughput comparison. The two verification replays keep the single-step path at first, so every clear is also
   checked by the old path for free.

### 4.4 (d) What else the evidence says

- d1 **The restart is the floor, and its CPU is unknown.** Boot wall 2.0 s unloaded, 2.2 to 4.8 s loaded; no run recorded CPU utilisation
  (the sd2 machine samples hold memory and process counts only). If a boot costs about 2 CPU-seconds, six logical CPUs sustain at most about three
  boots per second, that is about 10,800 jobs per hour against 4,416 today: a hard cap near x2.4 before any stepping gain, and a reason to measure
  boot CPU first (a5). A lighter boot (no audio or graphics device while no-render) would be a libultraship-level change and is not proposed.
- d2 **Selection becomes the bound at higher dispatch rates.** 82 ms per dispatch at 50 k cells is 10 % of the single-threaded main process's
  time today; at three times the dispatch rate and 150 k cells (about 150 ms, review M5) it is more than half, and workers would idle for jobs.
  Incremental eligibility (M5) is a prerequisite for realising any throughput gain, not a campaign nicety.
- d3 **Memory growth scales with jobs.** 11.2 MB per 1,000 new cells and 1.9 new cells per job: three times the jobs reaches the 2,560 MB soft
  budget in about 7 h instead of 22 h. The write-through ledger (M5) moves up with d2.
- d4 **Continuation is the cheapest tick**: 120 more words cost 0.17 s against a 4 s dispatch (review N3), and nothing above changes that ratio.

### 4.5 Comparison

| option | native change | keeps every guarantee | jobs per night (smoke mix, projection) | effort | measurable before building |
|---|---|---|---|---|---|
| a4 close off the critical path | no | yes | x1.1 to x1.24 | 1 session (with a5 and the lab review's S1 to S6) | no (split of the 1.0 s gap unknown) |
| a5 second standby + timing fields | no | yes | x1.14 to x1.29 | same session + 1 night | no |
| a2 pipelined submission | no | content yes, timing of the check one reply late | x1.1 to x1.15 | 1 session | no |
| c batched prefix (streamed records) | yes, PORT-only, default-off, additive op | yes; byte-identical lines on, byte-identical replies off | x1.44 to x1.56 alone; x2.3 to x3.1 with a4 + a5 | 3 sessions + build + about 1 h native equivalence + 1 night | no |
| d2 incremental eligibility | no | yes | needed to realise the above | 2 sessions | partly (offline timing of selection at 150 k cells) |

## 5. Recommendation

1. **Night 1 as planned**, on the committed code: it gives the run-to-run spread, the continuation rate and the memory growth that every later
   decision needs, and its per-job rows are the baseline for the levers below.
2. **Lab revision 2, Python only (one session, suite plus a 10-minute smoke):** a4 (close on a background thread, cap raised by the owner to
   N closing processes), a5 (standbys per worker 1 or 2 as a config value; per-job `wait_s`, `standby_startup_s`, `close_s`, boot CPU seconds),
   and the lab review's S1 to S6. Then **one throughput night** of four 2-hour runs: one standby against two, twice, never inside a comparison.
   Expected: x1.2 to x1.5 jobs per hour, and the first measurements of the close, the boot CPU and the machine's headroom.
3. **The native batched prefix (section 4.3):** two native sessions, one Python session, the build, the archive of the new executable, the
   equivalence proof, and one throughput night (flag on against off). Prefix only; bursts later. Expected with revision 2: job 4.1 s -> 1.3 to
   1.8 s, x2.3 to x3.1 dispatches, 10 to 14 M burst ticks per 7.2-hour night against 4.4 M, capped by d1 and d2.
4. **Incremental eligibility and the write-through ledger (review M5)** before the first campaign night.
5. **Then the pace-frontier selection** (the fresh counter and the pooled ahead draw, then the pools) on the faster pipeline.

Why throughput before the selection components: the comparison protocol needs three replicates per arm (review M4) and each replicate's power is
its dispatch count, so x2 to x3 throughput makes every selection night worth two to three; the native change is cleanest to prove while the
archive, the reference and the registered executable are frozen; and both levers are "measured once, never inside a comparison" (decision Q13),
so they must precede the comparisons anyway. The alternative, selection first on today's pipeline, costs nothing in correctness and about a week
of calendar if the selection work is the scarce resource; it is Q1 below.

Verification plan for the whole line: revision 2 is a code-digest change, so the suite and a fresh smoke; the native build is archived before any
run (D:/BattleShip_exe_archive/<date>_<hash>/), the lab import is re-pinned, and the four-part equivalence proof of section 4.3 runs before the
first run with the flag on; every clear stays verified twice by exact replay from tick 0, and the two verification replays keep the single-step path
until the equivalence corpus has grown.

## 6. What cannot be measured without running the game

- The split of the loaded 1.1 to 1.4 ms round trip between the native frame, the JSON build and parse, the thread hand-offs and CPU contention
  (needs `SSB64_RL_TIMING=1` under N = 5 load; only unloaded N = 1 segments exist).
- The close and the result transfer: the 1.0 s per job outside the job clock is one number; no record times `proc.close()`.
- The boot's CPU seconds and the machine's CPU utilisation at N = 5: no run sampled CPU.
- The batched operation's per-tick cost under load (0.35 to 0.5 ms is a projection) and whether the main thread or the transport thread bounds it.
- Whether a second standby per worker removes the wait without slowing the stepping, and its memory in the lab configuration.
- The gain of pipelined submission (a2), and whether `remove_tree_retry` ever retries in the lab.

## 7. Open questions

1. **Order.** Options: (a) throughput levers (revision 2, then the native prefix) before the pace-frontier selection components; (b) selection
   first on today's pipeline, throughput after the first comparison nights; (c) revision 2 only, native prefix deferred to a plateau.
   *Recommendation:* (a).
2. **Native variant.** Options: streamed per-tick records (chain stays in Python); a native chain digest (chain_v2, archive migration by replay);
   both. *Recommendation:* records now; a digest trailer only if the stream is measured to bound.
3. **Gating.** Options: an additive op under protocol 1 behind `SSB64_RL_STEP_BLOCK=1` (the `observe` and diagnostic-flag precedent); protocol
   version 2. *Recommendation:* the additive op; the version stays 1 because nothing existing changes.
4. **Equivalence corpus.** Options: the six registered clears + the lab reference + 200 stratified cells + one smoke; every archive cell (about
   70 M ticks); clears only. *Recommendation:* the first.
5. **New executable in the lab.** Options: a new lab root per executable version (keeps the one-shot import rule; the old root stays for
   night-1 comparisons); an import version field in the current root. *Recommendation:* a new lab root.
6. **Pipelined submission (a2).** Options: build it as a stop-gap; never. *Recommendation:* never if (c) is approved; it changes when a tick is
   checked and (c) dominates it.
7. **Standby cover.** Options: a 1-or-2 switch measured in revision 2's night; a shared boot pool decoupled from the workers. *Recommendation:*
   the switch first; the pool only if the native prefix makes two insufficient.
8. **Bursts in blocks.** Options: after the prefix path is proven; together; never. *Recommendation:* after; it is at most x1.1.
9. **Verification path.** Options: keep single-step replays for the two verifications (an independent check of the block path on every clear);
   switch them to blocks for speed. *Recommendation:* keep single-step until the corpus is large.
10. **Selection cost (d2).** Options: incremental eligibility before revision 2's night; before the native night; before the first campaign night.
    *Recommendation:* before the first campaign night, with `select_ms_per_dispatch` watched in both throughput nights.
11. **Night 1's rows** lack `wait_s` and the close time; the digest is frozen. Options: accept; re-plan night 1 on revision 2. *Recommendation:*
    accept.

## 8. Working files (git-ignored)

`logs/frs_prefix_cost/scripts/`: `a_smoke.py` (smoke per-job timings, fits, per level), `b_sd2.py` (sd2 arm T, wait against previous job,
implied boot), `c_shares.py` (per-job budgets, projections), `d_pytick.py` (offline Python per-tick benchmark and loopback echo on the smoke's
recorded replies). Their outputs are in `logs/frs_prefix_cost/outputs/`.
