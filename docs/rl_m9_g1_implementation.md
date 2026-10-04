# M9-g1 preparation: implementation record (2026-10-04)

**Status: zero-native-tick preparation.** The user's decisions for the first robustification gate (`docs/rl_m9_g1_decisions_2026-10-04.md`, which also records the mechanical readings R1-R16) are implemented in
new files only. Before this record was written nothing had launched BattleShip or consumed a native tick (the only process-level runs were against the synthetic fake game of `rl/m8_rd_fakegame.py`). Nothing
was committed or pushed and no branch was created. No tracked file was modified: every M8 file and document, `runs/m8_rd/`, `runs/m8_rd_rd2/`, `runs/m8_rd_rd3/` and `runs/m8_rd_rd4/` are byte-identical to `HEAD`
and to their D: increments. The only edit outside the repository is the guide's M9 relabelling (decision 1; a backup beside it).

**Scope label**, carried by every M9 record (`rl/m9_contract.SCOPE`): *M9-g1: backward-algorithm robustification (PPO from prefix-replayed start states on the agent's own two verified rd4 clears, sticky actions
p = 0.25, observation btt_policy_obs_v3_entities, reward btt_reward_v2); one gate, one run, one set of keyed draws; reach measured at landing states under the registered rule; no claim of a tick-0 policy.*

## 0. Summary

M9-g1 trains a FRESH PPO policy (the M7n v3 network and profile, entropy coefficient 0.01) on episodes that start late on the agent's own two verified rd4 clears, replayed as exact prefixes in fresh processes,
and moves the start point back in 20-tick strips only when the policy clears from the newly exposed strip. Sticky actions (p = 0.25 per tick, keyed Python-side draws) apply in training and in every evaluation. The
frozen final policy is then measured at the trunk's landing states against a paired open-loop tape and the registered rule `m9_g1_rule_v1` decides (PASS / INCONCLUSIVE / NULL / INCOMPLETE / INVALID). The backward depth
with no stickiness is reported, never deciding. The final claim (50 of 100 unperturbed, 50 of 100 sticky, margin 25) is defined and not run.

## 1. State

| item | value |
| --- | --- |
| parent | `main` = `origin/main` = `0c0e375`; `git status` shows only new untracked files |
| external guide | `Smash_pc_port/guide.md`: M9 relabelled "robustification", the old M9 marked superseded and relabelled M12 (backup `guide.md.bak_2026-10-04_pre_m9_rename`) |
| executable | `build-us/Release/BattleShip.exe` `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee` (the archive's pin), hashed, not run; `.o2r` files and the frozen configuration (`runs/m8_rd/archive/runtime/`, `BattleShip.cfg.json` `1b29d91b...`) equal rd1's pins |
| compute | Python 3.13.2, SB3 2.9.0, torch 2.14.0 (CPU), gymnasium 1.3.0, numpy 2.5.3; six logical CPUs, 16 GB |
| M8 trees | rd1 166 files, rd2 62, rd3 77, rd4 93: each equals its D: increment byte for byte (`rs.rd1_immutability`, registered file counts, bytes and manifest digests) |
| D: | the base plus the increments of M7r ... M8-rd4 cover every `runs/` file (0 uncovered); the M9 increment `2026-10-04_incr_m9_g1` is created after the run by the unchanged `rl/tools/runs_backup.py` |

## 2. Files (all new)

| file | role |
| --- | --- |
| `rl/m9_contract.py` | every registered constant (task, flags, lineages, curriculum, sticky p, landings, thresholds, PPO, split rule, caps, keys) and the contract digest |
| `rl/m9_artifacts.py` | the task block and `created_utc`: `check`, `stamp`, the only writers (`write_json`, `write_json_gz`, `append_jsonl`, `write_episode_artifact`), `audit_tree` |
| `rl/m9_sticky.py` | keyed sticky draws, the mask rebuilt from keys, the open-loop `Tape` |
| `rl/m9_curriculum.py` | the frontier pointer, strips, the start distribution, blocks, stale accounting |
| `rl/m9_rule.py` | `m9_g1_rule_v1`, the reach depth, the diagnostics, `claim_status`, the self-test |
| `rl/m9_obs.py` | `V3Pipeline`: the M7n builder fed every reply |
| `rl/m9_lineages.py` | the two routes (read from the rd4 tree), landing states, chain and v3 tables, P1's evaluation |
| `rl/m9_verify.py` | exact replay evaluation, the priority-tier replay plan under tick and wall caps |
| `rl/m9_worker.py` | one process slot: `ColdBackend`, `WorkerCore` (stage / step / close), the worker process loop |
| `rl/m9_pool.py` | `SlotPool` (spawned workers over pipes), `LocalPool` and `VirtualClock` (the lock-step pool of the tests) |
| `rl/m9_vec.py` | `Arena` (the staging pipeline), `EpisodeCtx` (words, sticky bookkeeping, rebased reward v2), `TrainVecEnv` (the SB3 VecEnv over staged starts), `TickBudget` |
| `rl/m9_train.py` | start sources, the recorder, the PPO callback (caps, checkpoints, per-rollout metrics), `train` |
| `rl/m9_eval.py` | evaluation jobs (reach, tape, deterministic, tick 0, unperturbed, fine grid), the free-running runner, aggregation |
| `rl/m9_run.py` | the session engine: P1, P2, P3, P4, training, evaluation, verification, close; the clock and caps; the budget projection |
| `rl/m9_claim.py` | the final-claim evaluator (no prefix path), not run by g1 |
| `rl/m9_report.py` | `verify-run` and the reported readings |
| `rl/m9_session.py` | the CLI: identity, approval, preflight, the real environment, run, verify-run, report |
| `rl/m9_snapshot.py` | the verified D: source snapshot |
| `rl/m9_stub.py`, `rl/m9_testenv.py`, `rl/m9_tests.py` | the synthetic world, its environment builder and the suite (tests only) |
| `docs/rl_m9_g1_decisions_2026-10-04.md`, this record | |

Reused unchanged (read-only): `rl/m8_rd_worker.py` (`RealBackend`'s launch code, `RealProc`, `_tick0`, `_finish_proc`, `FrozenRuntime`), `rl/m8_rd2_worker.py` (`WriteGuard`), `rl/m8_rd_cells.py`, `rl/m8_rd_session.py`
and `rl/m8_rd*_resume.py` (the immutability checks, coverage, readiness, approval and snapshot status helpers), `rl/m7f_trace.py`, `rl/m7n_crossing.py`, `rl/m7n_obs.py`, `rl/m7n_policy.py`, `rl/btt_rewards.py`,
`rl/m7_runtime.py`, `rl/battleship_process.py`, `rl/tools/runs_backup.py`. No inherited file is edited.

## 3. The design as implemented

**Process model.** The session process (the learner, the arena, the engine) and N_SLOTS = 10 spawned worker processes. A worker owns AT MOST ONE BattleShip process at a time and never reuses one. A slot is idle ->
staging (cold launch, tick-0 check, the prefix replayed one `step` per tick) -> READY (parked at `WaitingForAction` at input tick tau) -> active (stepped one word per tick) -> idle. The 4 + 6 (or 2 + 8) split is only
how many READY starts become active episodes: 4 playing slots, the others prepare starts. At most 10 BattleShip processes exist at any time: P1 replays and the promoted worker (4 / 2 processes), P2 (at most 4 staged
plus 3 cold replays), every other pool phase (at most 10 slots), verification (8 threads).

**Staging checks, every tick.** Consumed tick, input tick, step count, the per-tick record chain digest against the registered chain, the v3 observation digest against the registered table; the tick-0 record against the
archive's pin; a prefix that ends or falls is an integrity failure. The v3 builder is fed every prefix reply, so the policy sees what it would have seen had it played the prefix. Evidence of a mismatch (the last 48
raw replies) is preserved under `session/failures/`.

**Reward.** `btt_reward_v2` through the unchanged `reward_step`, rebased at the handover: prefix breaks earn nothing, the per-tick cost is the policy phase's, fall = native failure = termination (-5 once), clear +10,
truncation at the 3,600-input-tick horizon counted from the reset (the prefix counts). `num_timesteps` counts policy transitions only.

**Sticky actions.** At every submitted tick t >= 1 a keyed uniform below 0.25 repeats the word submitted at t - 1 (R1). The SUBMITTED word is the recorded one; sampled words and the mask are metadata, and
`rl/m9_report.verify_run` re-derives every mask from its key.

**Curriculum.** Pointer 2,300, strips of 20, 50 / 30 / 20 % strip / near / rehearsal starts drawn when a slot becomes free; only strip starts drawn under the CURRENT pointer count, in blocks of 10; 3 clears move the
pointer back by 20; stale outcomes are logged and still used by PPO (R2). `verify-run` rebuilds the pointer's whole history from the episode records alone.

**Evaluation.** 20 stochastic sticky episodes at each landing state, the paired tape (same labels, same keys), the unperturbed diagnostic, tick 0, the fine grid, a descriptive 30-minute checkpoint (R4, R12).

**Verification.** Every counted clear is replayed from tick 0 (the four read-only diagnostics, the frozen runtime) and must equal the online record (R11); the rule counts only verified policy clears.

## 4. The checks at the open (preflight)

`python rl/m9_session.py preflight`: the run root absent; the unit suite and the rule self-test; the executable present; tracked files equal `HEAD` and only new files untracked; the executable, the three runtime
files and the frozen configuration equal the archive's pins; the four M8 trees equal their D: increments with the registered file counts, bytes and manifest digests; both registered lineages re-derived (words,
digests, clocks, Track 1 range, `actions.jsonl`); the controller-rule CVars absent; the status table; D: coverage with 0 uncovered; no BattleShip process; readiness (>= 4,096 MB available, >= 10,240 MB free commit, >= 5
GiB free on C: and D:); Python started with `-B`; the approval (its task block and `created_utc`, identity, code hashes, docs hashes, git head, D: records) and the source snapshot. A memory, commit or free-space refusal is a stop, never a reason to close an application.

## 5. Tests

`python rl/m9_tests.py unit` runs the deterministic suite (section 5.1); `python rl/m9_tests.py e2e` the production-count synthetic end-to-end run (5.2); `python rl/m9_tests.py integration` is the separate non-gating
command that runs real spawned worker processes and the real cold-launch backend against a fake game (5.3). The suite contains no non-deterministic test (a source scan forbids `random`, `secrets`, `uuid`,
`os.urandom`, `time.sleep` and any wall-clock read inside a test).

### 5.1 The unit suite (groups)

| group | what is asserted |
| --- | --- |
| contract, artifacts | every registered value equals the decisions; the task registry copy equals `rl/experiment_config.SUPPORTED_TASKS`; the writers REFUSE an object without `task` or `created_utc` (nine refusal cases, nothing written); an M4-form artifact passes `rl/run_artifacts.read_artifact`; `audit_tree` finds an unstamped file |
| sticky, tape | the rule, the keys, the 0.25 rate over 20,000 draws, a record's mask rebuilt from keys, tampering caught; the tape under identical draws shares labels and masks with its policy episode |
| curriculum | regions and clipping, the draw distribution (50 / 30 / 20), starts as pure functions of (episode, pointer); a step back only from clears of the newly exposed strip; non-strip and stale clears never count; the history rebuilt from the records equals the live one; a policy that cannot clear from the strip never moves the pointer past what it clears |
| rule | the self-test (every boundary and the precedence) and the claim thresholds |
| real recorded replies (zero ticks) | the two routes' registered facts; the landing states computed from the trunk equal the registered six (and the eleven earlier grounded segments are named); the real v3 tables rebuild identically; P1's evaluation on the real verifying replay (a single altered reply, a wrong promoted digest, a replay that was not promoted all fail); exact verification of the real clear and its tampering cases; the staged-start code (`WorkerCore`) run on the real recorded replies: every tick checked, the registered handover observation delivered, the clear reproduced and finalised, a corrupted table refused as an integrity failure |
| synthetic world | worker core stage / step / close and every failure kind; reward rebasing against the closed form; the horizon counted from the reset; tick budget and arena accounting, stale replies ignored, the lifecycle limit, the process limits of P2 and P3; the SB3 VecEnv contract; one real PPO rollout over the staged VecEnv (hyper-parameters, checkpoints with pinned digests, reload decides identically) |
| evaluation | the job structure and priorities, paired labels, the fine grid, deeper landings, aggregation, the process-split selection rule at its 1.10 boundary (exactly 110 % chooses 2 + 8), the budget projection, requeue after a process death during a step, the tick cap |
| session | a small session runs every phase and every JSON record carries the metadata; two runs agree on every record; INCOMPLETE and INVALID for every stop (lifecycle failures, mismatch, write guard, memory, process count, hard cap, phase caps); P1 refuses an inexact replay; `verify-run` detects tampering (mask, unstamped file, checkpoint, missing replay, unearned step back) |
| guards, identity | no fixture / TAS / recording reference; no native RNG vocabulary; no imitation or auxiliary loss; the claim evaluator cannot import any staging module and refuses a process that is not at tick 0; workers import no torch / SB3 / gymnasium; the write guard covers every other tree; identity pins; approval on isolated records; the snapshot tool round trip; git state; the four M8 trees equal their increments |

### 5.2 The production-count synthetic end-to-end run

`python rl/m9_tests.py e2e` runs the whole session engine (P1 to the close and the rule) at the registered counts against the synthetic `ChainWorld` (an in-process lock-step pool, a virtual clock charged
1,200 ticks/s per native tick, a stub model whose competence boundary moves back as it collects transitions): 20 episodes at each of the six landing states, the 140 tape episodes, the fine grid, 12 P2
starts, the 3,600 s training wall cap, the 15,000,000-tick cap, ten slots, the 4 + 6 and 2 + 8 measurement. It asserts: the start-state pool (every start is a prefix of one of the two lineages and
staged with the registered chain and v3 digests); the backward schedule (the pointer moves 2,300 -> 1,400 in 45 moves, each only after >= 3 clears of 10 counted strip outcomes; the stub learner clears a newly exposed strip only after it has
collected transitions, so every step back is earned by clearing from ticks that were newly exposed; the rule that only such clears count is also a unit test); sticky actions (the keyed mask of every episode rebuilt and equal); the tape baseline under identical draws (paired labels); the
rule's outcome on the recorded rows; the unperturbed diagnostic; the metadata of every record (`verify-run` and the close audit); and that 579 counted clears were verified. Its result is the same on
every pass (outcome PASS, R 1,473 on the synthetic world, 1,889 training episodes, digest `9a4c6e9be82834a6` of the rule, the reach rows, the pointer history, the split and the episode count; wall 476-495 s). It
says nothing about the real game.

**Three consecutive passes with no change in between** (`logs/m9_g1_prep/tools/three_passes.py`, outputs under `logs/m9_g1_prep/final/`): the fingerprint of `rl/m9_*.py` was `aea335a788669447` before and
after every pass; the unit suite passed 63 / 63 each time (329.5 s, 325.4 s, 334.4 s) and the end-to-end run passed each time (479.9 s, 500.9 s, 478.6 s; the identical digest). Part B condition 1.

### 5.3 The integration command

`python -B rl/m9_tests.py integration` (not gating): real spawned worker processes and the real cold-launch backend against the fake game of `rl/m8_rd_fakegame.py`: staging checks, ready / active /
close, a process that dies while staging (the fourth lifecycle failure stops the phase), process counts and the worker lifecycle. PASS in 14.8 s (16 launches).

## 6. Budgets (`rl/m9_run.budget_projection`)

| phase | wall cap | native-tick cap |
| --- | ---: | ---: |
| P1 lineages | 240 s | 60,000 |
| P2 staging equivalence | 120 s | 40,000 |
| P3 split measurement (two 120 s windows, each ending at the earlier of 120 s and 300,000 ticks: decisions 5, F2) | 300 s | 600,000 |
| P4 tape control | 360 s | 600,000 |
| training | **3,600 s** | **15,000,000** (and <= 3,072,000 transitions) |
| evaluation | 1,500 s | 3,000,000 |
| verification | 900 s | 1,500,000 |
| close | 300 s | 0 |
| sum of the caps | 7,320 s (122 min) | |
| **session hard cap** | **7,800 s (130 min)** | |

**Pessimistic projection** (every phase wall cap binding, four pool spawns at 15 s, 20 s of grace per phase): **7,540 s = 125.7 min, 260 s below the 130-minute cap, with no trimming.** The expected projection
(measured throughputs) is about 5,560 s (93 min). The training wall is the binding end of the training phase in every projection. Memory caps are rd4's (main process 3,072 MB private, tree 9,216 MB private,
4,096 MB working set, system available >= 1,024 MB, commit free >= 2,048 MB; at most 10 BattleShip processes, a stop needs two distinct samples above the cap).

**Memory plan (measured parts).** A worker-like Python process holds 74 MB working set (221 MB private) with the v3 builder loaded; ten of them plus ten BattleShip processes (112 MB working set, 367 MB private each
when parked, M7c) plus a PPO main process stay under the working-set cap with about 1 GB to spare and under the private cap with about 2 GB.

**Throughput basis.** M7n foothold: boot 3.2 s and 1,060 prefix ticks/s per process; rd1-rd4: 1,560-1,861 aggregate ticks/s with ten processes. The proposal's estimates (5-11 M native ticks and 0.4-1.6 M transitions in 60
minutes) stand; P3 measures the actual split throughput before training.

## 7. The independent review and its dispositions

Before this record was frozen a separate read-only reviewer read every `rl/m9_*.py` file against the proposal and the decisions. It found **no blocker**. Its findings and what was done (the registered
readings are in the decisions record, section 5, F1-F5):

| finding | disposition |
| --- | --- |
| a staging lifecycle failure in a fixed-job phase (P2, P4, evaluation) loses its job and ends the gate INCOMPLETE | **fixed (F1)**: the same job is staged again; the limit of three per phase is unchanged |
| P3's shared 600,000-tick cap would be reached before the two 120 s windows and escape as a stop | **fixed (F2), flagged**: each window ends at the earlier of 120 s and half the cap; the rate is over the elapsed window; only the tick cap is caught; a window with no transition is ineligible |
| the v3 digest tables are built under the verification flag set and compared under the training flag set | **recorded as a first-contact risk** (section 10): it cannot be changed without changing P1's registered flag set and cannot be shown at zero ticks; if it fails the gate is INVALID in P2 with no training |
| a stale `.pyc` under `rl/` would be a write-guard violation | **fixed (F4)**: `-B` is required by the preflight, the session sets `PYTHONDONTWRITEBYTECODE`, workers do not write bytecode |
| a parked start's death: dead slot left in the ready queue; the budget credited twice | **fixed (F3)** |
| minors: partial records on a stop, a summary after a trainer error, worker tracebacks in the stop reason, a broken pipe in the pool's death scan, a P2 first-step death recorded INVALID, the approval record's metadata unchecked | **fixed (F5)** |
| `job_timeout_s` is registered but there is no separate watchdog | **recorded** (decisions 5, "not changed (b)") |

Tests added for the fixes (the suite now has 63 tests, all deterministic): `a_fixed_list_stages_a_job_again_after_a_staging_lifecycle_failure`,
`a_parked_start_whose_process_dies_is_withdrawn_and_its_job_returns`, `the_slot_pool_treats_a_broken_pipe_as_a_death`,
`p3_ends_a_window_at_its_share_of_the_tick_cap_and_still_measures`, `a_stopped_phase_leaves_its_partial_record`.

## 8. The preflight, dry run (before the approval)

`python -B rl/m9_session.py preflight --skip-unit` (the unit suite had just passed three times; the real preflight of Part C runs it) refuses for exactly one problem: **no approval record at
`docs/rl_m9_g1_approval.json`**. Everything else passed: the run root absent; the executable, the three runtime files and the frozen configuration equal the archive's pins; the four M8 trees equal their D:
increments with the registered counts, bytes and manifest digests; both lineages re-derived; no controller-rule CVar; the status table; D: coverage 409,475 source files, 0 uncovered, nine increments;
no BattleShip process; readiness (8,119 MB available, 18,033 MB free commit, 111 GiB free on C:, 1,566 GiB on D:); `git status` shows 23 new files and nothing else (no tracked file differs from `HEAD`).

## 9. The launch conditions (Part B), as checked

| # | condition | evidence |
| --- | --- | --- |
| 1 | unit suite and end-to-end run pass three consecutive times with no change; no non-deterministic test gates | section 5.2: three passes, fingerprint `aea335a788669447` unchanged, 63 / 63 and PASS each time; the source scan of the suite forbids randomness, sleeps and wall-clock reads |
| 2 | the pessimistic projection fits the 130-minute cap with no trimming | section 6: 7,540 s = 125.7 min, 260 s of slack; `budget_projection_fits_the_session_cap_without_trimming` |
| 3 | the preflight refuses solely for the missing approval | section 8 |
| 4 | the four M8 trees equal their D: increments; the executable, `.o2r` files and frozen configuration equal the pins | section 8 (preflight, every check) |
| 5 | `git status` shows only new files; no existing file changed | section 8 (23 new files; no tracked change) |
| 6 | no open design decision had to be made; hazards fixed are recorded and flagged | decisions record section 5 (F1-F5): each implements a registered statement and changes no registered measure, threshold, schedule, cap value or training setting; `contract_digest` is unchanged (`6958857e...`). F2 (the P3 windows under the tick cap) is the one fix a reader may consider a reading of a registered measure; it is flagged in the report |

## 10. Remaining risks (first contact with the real game)

* **The v3 digest across flag sets** (decisions 5, "not changed (a)"): if the staged handover's v3 digest differs from the table built under the verification flags, P2 fails INVALID before any training.
* **Real throughput.** The measured basis is 1,060-1,861 prefix ticks/s per process; the proposal estimated 5-11 M native ticks and 0.4-1.6 M transitions in 60 minutes. The training phase ends by its wall cap
  in every projection (the transition cap 3,072,000 is not expected to bind). P3 measures the split on the real machine; its two windows are expected to end at their half of the tick cap.
* **Memory.** Ten BattleShip processes, ten workers and the PPO process fit the registered caps with about 1 GB of working-set slack by measurement of the parts, not of the whole; a breach is INCOMPLETE and
  the session never closes another application.
* **The science.** A NULL, an INCONCLUSIVE or a pointer that never moves is a valid outcome; nothing in the gate retries it. The reach rule counts a landing only when at least 10 of 20 verified sticky clears
  and at least 5 more than the paired tape; an unverified clear that could change R makes the gate INCOMPLETE.
* **Peers.** Other sessions share this machine and this checkout. The preflight refuses if a tracked file differs from `HEAD`, if the status shows anything but new files, or if an M8 tree differs from its D:
  increment; the session's write guard records any write under another `runs/` directory, `rl/` or `docs/`.
