# M9-g3 preparation: implementation record (2026-10-06)

**Status: zero-native-tick preparation.** The user's decisions for the third robustification gate (`docs/rl_m9_g3_decisions_2026-10-06.md`, which also
records the mechanical readings R1-R12 and the authorised edit with its diff) are implemented in new files only, plus the one authorised edit. Before this
record was written nothing had launched BattleShip or consumed a native tick (every process-level run was against the synthetic world of `rl/m9_stub.py` and
`rl/m9_g2_stub.py`). Nothing was committed or pushed and no branch was created. No tracked file was modified except `rl/m9_eval_tests.py` (decision 9); every
M8, M9-g1, M9-g1-evaluation and M9-g2 file and document, `runs/m8_rd*/`, `runs/m9_g1/`, `runs/m9_g1_eval/` and `runs/m9_g2/s1/` are byte-identical to `HEAD`
and to their D: increments. The external guide was not edited.

**Scope label**, carried by every M9-g3 record (`rl/m9_g3_contract.SCOPE`): *M9-g3-s1: backward-algorithm robustification under the replenishing controlled
frontier rule `m9_g3_frontier_v1` (PPO from prefix-replayed start states on the agent's own two verified rd4 clears, sticky actions p = 0.25, observation
btt_policy_obs_v3_entities, reward btt_reward_v2, entropy coefficient 0.01; the g2 trigger, frozen strip test and re-checks unchanged; attempts spaced by
20 x 2^(f-1) counted strip outcomes, cap 320, no HELD and no STALLED); the first session of a new resumable line (not an amendment of g2); a fresh policy
(seed 0); one set of keyed draws; progress measured as the sustained frontier depth D and the reliable reach R at landing states against g2-s1's pinned tape
baseline reused by digest, under the registered rules; no claim of a tick-0 policy.*

## 0. Summary

M9-g3-s1 is g2-s1's recipe (a FRESH PPO policy, the M7n v3 network and profile with the entropy coefficient 0.01, episodes started late on the agent's own two
verified rd4 clears replayed as exact prefixes in fresh processes, sticky actions p = 0.25 everywhere, the 8-of-20 trigger, the frozen strip test of 20 at 10,
the re-check of every passed landing, the 4 + 6 slots, the 80-minute training wall under the 145-minute cap) with ONE change: the attempt bounds (3 per pointer
per session: HELD; 6 over the line: STALLED) are replaced by a spacing rule under which attempts replenish with training progress. After f consecutive failed
attempts at the pointer, the next attempt needs min(320, 20 x 2^(f-1)) counted strip outcomes at the pointer since the last failed attempt and a fresh trigger;
a trigger inside the spacing is logged `deferred_trigger`, no attempt runs, the window restarts. There is no HELD and no STALLED; no attempt count freezes the
frontier or ends the line. The tape baseline is g2-s1's pinned table, reused by digest (verified at the open with the executable and asset pins; a 5-key drift
check in the T0 phase; nothing measured). The line's budget is progress-only (D <= 2,128 by s2, 1,966 by s4, 1,694 by s6; success at 1,473; cap 8); a NULL s1
does not end it. The s1 rule: PASS iff R_1 <= 1,966; INCONCLUSIVE iff D_1 <= 2,128; NULL iff D_1 = none; INCOMPLETE and INVALID as g2 (plus "an attempt inside
its spacing" as INVALID).

## 1. State

| item | value |
| --- | --- |
| parent | `main` = `origin/main` = `6d73f52`; `git status` shows the one authorised edit (` M rl/m9_eval_tests.py`) and new untracked files, nothing else |
| external guide | `Smash_pc_port/guide.md`, unchanged (M9 = robustification since 2026-10-04) |
| executable | `build-us/Release/BattleShip.exe` `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee` (the archive's pin), hashed, not run; `.o2r` files, `gamecontrollerdb.txt` and the frozen configuration equal rd1's pins |
| reused tape | `runs/m9_g2/s1/session/tape_baseline.json`: file sha256 `81fa52c21078b2c2e5af9239678918099c6fb407608de085c7dd0c46d98196cd`, content digest `d915fab9205547742e77360ba83f247b7ab304af7a37540ceb9910a2b614a23b`, pinned at every landing (B = 15 at 2,128 from 98 of 200; B = 10 elsewhere), measured with the executable above; the drift records `runs/m9_g2/s1/t0/episodes.jsonl` (read-only) |
| compute | Python 3.13.2, SB3 2.9.0, torch 2.14.0 (CPU), gymnasium 1.3.0, numpy 2.5.3; six logical CPUs, 16 GB |
| protected trees | rd1 166 files, rd2 62, rd3 77, rd4 93, `m9_g1` 2,740, `m9_g1_eval` 1,393, `m9_g2/s1` 9,779: each equals its D: increment byte for byte (the g3 preflight and the unit gate `the_protected_trees_equal_their_increments_and_the_pins_hold`) |
| D: | the base plus the increments up to `2026-10-06_incr_m9_g2_s1` cover every `runs/` file (0 uncovered); the g3 increment `2026-10-06_incr_m9_g3_s1` would be created after a run by the unchanged `rl/tools/runs_backup.py` |
| digests | g3 contract `4cd1deaec0f0333b394f0ac85bc0f3c494c117e63eacc0caf5e80e0929b8e040`; g3 line contract `90eac1a6c6682a397fc8e85abdf5b1d8ab3f38b75a80ae08709932286d319a31`; frontier rule `60e174a61c02e184...`; s1 rule `dea9965a3989bce5...`; line rule `d9d82885703c016d...`; g2 contract and line contract (unchanged, read) `8dfd44c6...` and `1aadc7a6...`; g1 contract (unchanged, read) `6958857e...`; fingerprint of `rl/m9_g3_*.py` `17dea6d712e624ed` |

## 2. Files (all new, plus the one authorised edit)

| file | role |
| --- | --- |
| `rl/m9_g3_contract.py` | every registered g3 constant read over the unchanged g2 and g1 constants: the spacing rule (unit 20, cap 320, `spacing_need`), the line budget, the reused tape's pins, the g3 keys (the reach label kept from g2), the envelope caps; `contract_digest`, `line_contract_digest` |
| `rl/m9_g3_frontier.py` | `Frontier(rl/m9_g2_frontier.Frontier)`: g1's start distribution on g3 keys, g2's curtailed trigger window, the spacing rule (`deferred_trigger`, `begin_attempt` refused inside the spacing, f and the outcome counter), no HELD / STALLED, the carried state with the spacing, `replay_history` (the rebuild from records, naming an attempt inside its spacing) |
| `rl/m9_g3_rule.py` | `m9_g3_s1_rule_v1`, `m9_g3_line_rule_v1` (every END a progress or time condition), D / R read from g2, the self-test (`python rl/m9_g3_rule.py self-test`) |
| `rl/m9_g3_probe.py` | the probe, re-check, audit and drift jobs on g3 keys (the audit's sticky labels on the reused tape's family); g2's `run_attempt` copied with the g3 jobs and pick key; the runner classes imported from g2 unchanged |
| `rl/m9_g3_train.py` | the g3 training source and recorder (g2's on g3 keys), checkpoints carrying the g3 line contract, frontier rule and spacing state, the callback (g2's class, the spacing in every rollout row), `train` (g2's with the g3 attempt and checkpoints) |
| `rl/m9_g3_run.py` | `G3Session(rl/m9_g2_run.G2Session)`: the open (the reused table copied into `input/` and verified: file and content digests, every landing pinned, the key counts, the label family, the executable pin; a resumed session as g2 under the g3 identities), T0 = the 5-key drift check, training, the close audit, the close (the g3 rules, the final-state record); `G3Config`, `budget_projection` |
| `rl/m9_g3_report.py` | `verify_run` (g2's checks plus the g3 frontier rebuild with the spacing, the g3 checkpoint identity, the reused table and the drift rows, the line rule recomputed) and `full_report` (g2's readings plus the trigger-to-test gap, the attempt yield, the replenishment schedule, the deferred triggers, the pointer over time, the throughput by pointer, the per-landing clears against the tape) |
| `rl/m9_g3_session.py` | the CLI: identity (the spacing, the line budget, the tape pins, the authorised edit), approval, preflight (the seven protected trees, the reused tape's checks, the git tolerance of exactly the authorised edit at its digest), write-guard roots, `run`, `verify-run`, `report`, `status`, `approval-template`; the real hooks are g2's |
| `rl/m9_g3_snapshot.py` | the verified D: source snapshot (the procedure of rl/m9_g2_snapshot.py; the file set adds the g3 files, the stop review, the g2 results and approval, the authorised edit) |
| `rl/m9_g3_tests.py` | the unit suite and the production-count synthetic two-session e2e (section 5) |
| `rl/m9_eval_tests.py` (edited) | decision 9: two lines of its own source guard assembled from fragments; nothing else (the diff and digests in the decisions record, section 4) |
| `logs/m9_g3_prep/tools/` | `three_passes.py`, `write_approval.py`, `launch_detached.ps1`, `wait_session.py`, `independent_increment_check.ps1` (the g2 tools re-pointed; Git-ignored) |
| `docs/rl_m9_g3_decisions_2026-10-06.md`, this record | |

Reused unchanged (read-only): every `rl/m9_g2_*.py` module (`m9_g2_contract` read for every value g3 keeps; `m9_g2_arena`, `m9_g2_policy`, `m9_g2_probe`'s runner
classes, `m9_g2_tape`, `m9_g2_resume`, `m9_g2_run`'s P1 / P2 / verification / clock / pools, `m9_g2_train`'s callback class and `resume_ppo`, `m9_g2_session.real_hooks`,
`m9_g2_stub` for the tests), every `rl/m9_*.py` module of g1, `rl/m9_eval_policy.py`, the M8 workers and helpers, `rl/m7n_*`, `rl/btt_rewards.py`,
`rl/tools/runs_backup.py`. No inherited file is edited except decision 9.

## 3. The design as implemented

**Process model.** As g2: the session process (the learner, the arena, the engine) and ten spawned worker processes, one BattleShip slot each, never reused;
the fixed 4 + 6 split; during an attempt the four playing slots stay parked at `WaitingForAction` and the six others run the probes under a second arena; at
most 10 BattleShip processes at any time.

**The frontier.** `Frontier.record` keeps g2's curtailed window (trigger at the 8th clear, void at the 13th non-clear; outcomes after a trigger are
`after_trigger`). Every counted strip outcome at the pointer also advances the spacing counter. When a window reaches 8 clears: if f = 0 or the counter has
reached need(f), the trigger is pending and the attempt runs at the next rollout boundary (g2's hook, unchanged); otherwise the event is `deferred_trigger`,
nothing runs, the window restarts. The attempt is g2's (the frozen snapshot, the strip test, the parallel fail-fast re-checks, the move only when every test
passes). A failed attempt raises f by one and resets the counter; a move resets both at the new pointer; an interrupted attempt changes neither. There is no
HELD and no STALLED state; the per-pointer attempt counts are recorded and reported.

**The reused tape.** At the open the table is copied into `input/tape_baseline.json`; its file sha256 (source and copy), its content digest, every landing's
pin and bar, the registered key counts (200 / 40), the label family, the lineage, sticky p and the executable it was measured with are checked against the
registered pins (any difference: INVALID, nothing trained). T0 runs the 5-key drift check (the first five tape keys at 2,128 on the table's own labels must
reproduce the table's outcomes and the measuring session's native action digests). The close audit's sticky episodes use the same labels (k = 0..19), so they
pair with the tape, and the bars come from the table.

**Records.** `training/{episodes,rollouts,stale,windows,withdrawn,attempts,probes,moves}.jsonl` (windows.jsonl carries `trigger`, `deferred_trigger` and `void`
events with the spacing state; every attempt record carries `spacing` and `spacing_after`; every rollout row carries the spacing and the deferred count),
`training/attempts/a<n>/snapshot_policy.pth`, `training/checkpoints/<ckpt>/{model.zip,curriculum_state.json,checkpoint.json}`, `input/tape_baseline.json`,
`t0/drift.jsonl`, `audit/episodes.jsonl`, `verification/replays.jsonl`, `session/{open,p1,p2,t0,training_summary,audit_run,verification,close,rule,line,final_state,
state,...}.json`, `artifacts/`. Every write goes through `rl/m9_artifacts` (the task block and `created_utc`; the writer refuses without them).

**Verification tiers** (decision 10): 0 = every close-audit sticky clear at an audited landing; 1 = the first 20 training clears; 2 = one keyed clear per
passed test of every attempt; 3 = the diagnostics. The reused tape's 100 clears were replayed in g2-s1 and are not re-replayed.

**Resume.** Implemented (g2's machinery under the g3 identities; the carried state adds the spacing counter; a g2 state is refused) and tested
synthetically; s2 is not run and not authorised.

## 4. The checks at the open (preflight)

`python -B rl/m9_g3_session.py preflight`: Python started with `-B`; the run root `runs/m9_g3/s1` absent; the g3 unit suite and the g3 rule self-test; the
executable present; tracked files equal `HEAD` except the authorised edit at its pinned digest, and only new files otherwise untracked; the executable, the
three runtime files and the frozen configuration equal the archive's pins; the reused tape equals its registered digests, is pinned at every landing, was
measured with the executable now, and its drift records exist; the controller-rule CVars absent; the status table; the seven protected trees equal their D:
increments with the registered counts, bytes and manifest digests; both registered lineages re-derived; D: coverage with 0 uncovered; no BattleShip process;
readiness (>= 4,096 MB available, >= 10,240 MB free commit, >= 5 GiB free on C: and D:); the pessimistic budget fits the 145-minute cap; the approval (its task
block and `created_utc`, identity, code hashes, docs hashes, git head, D: records) and the source snapshot. A memory, commit or free-space refusal is a stop,
never a reason to close an application.

## 5. Tests

`python -B rl/m9_g3_tests.py unit` runs the deterministic suite (25 tests, section 5.1); `python -B rl/m9_g3_tests.py e2e` the production-count
synthetic two-session line (5.2). No test starts a game process; a source scan forbids `random`, `secrets`, `uuid`, `os.urandom`, `np.random`,
`torch.manual_seed`, `time.sleep` and any wall-clock read inside a test; the suite assembles every forbidden literal from fragments so that it is itself clean
under g1's scan (which covers the g3 files).

### 5.1 The unit suite (groups)

| group | what is asserted |
| --- | --- |
| contract, keys | every registered g3 value (spacing 20 / 320, need(f) = 0, 20, 40, 80, 160, 320, 320, 320; the line budget; the thresholds, PPO, curriculum, caps and split read unchanged from g2 / g1; the T0 cap 240 s / 60,000; the reused tape's pins); no attempt bound in the frontier description; the g3 digests differ from g2's and are stable; the pessimistic budget (7,780 s of 8,700 s, slack 920 s); every key string is the `m9|g3|...` family except the reach label (g2's, for pairing) and P2 (g1's) |
| frontier | the window as g2 (trigger at the 8th clear, void at the 13th non-clear, `after_trigger` counting toward the spacing, stale and non-strip ignored); the spacing: the schedule as it runs (f, need, have) = (0, 0, 8), (1, 20, 24), (2, 40, 40), (3, 80, 80), (4, 160, 160), (5, 320, 320), (6, 320, 320), with every trigger inside a spacing deferred (window restarted, nothing pending), an attempt inside its spacing refused, no HELD and no STALLED after seven failures, the attempt after the cap (f = 7, 320 of 320), a move resetting f and the counter, INTERRUPTED changing neither; the carried state with the spacing counter restored across a session boundary (33 carried + 48 new = 81 >= 80), the line attempt index continuing, a g2 state and a STALLED flag refused; keyed g3 starts (differing from g2's and g1's) within the strip; the history rebuilt from records (pointer, moves, deferred triggers, the schedule) and five tamperings caught (a move with 9 clears, a wrong line index, an attempt moved inside its spacing, a recorded spacing that differs, a start that does not reproduce) |
| rules | the self-test (every s1 boundary; every line END and the order; a NULL s1 continues; absurd attempt counts and HELD / STALLED flags are never read); the line rule's code reads no attempt count |
| probes, attempt | the strip, re-check, audit and drift jobs on the registered keys (the audit's sticky labels on the reused tape's family, its action keys g3's; counts as g2); `run_attempt` on the synthetic world (MOVED with the pause, the six probe slots, the withdrawn starts, the spacing recorded; FAILED_STRIP at 2,180 making f = 1 / need 20; a trigger inside the spacing deferred and `run_attempt` refused; the replenished attempt at a = 2 after 24 outcomes failing again (f = 2 / need 40) with its probe labels carrying a = 2; BLOCKED_BY_RECHECK at the forgotten cold landing 1,966 with the pointer unmoved and the re-check set every landing behind the frontier; INTERRUPTED by a cap counting nothing with the spacing unchanged) |
| checkpoints, SB3 | the three files per checkpoint with the pins and the g3 identity (gate, frontier rule, line contract, spacing) in `checkpoint.json` and `curriculum_state.json`, the carried spacing counter, the resume compatibility check accepting the g3 state and refusing the g2 line contract; the frozen policy keyed on g3 keys (differing from g2's draws); the real SB3 save / load round trip bit-exact with an update after the reload equal to one without (g2's machinery); `resume_ppo` sets the session seed; the fresh PPO's untrained tensors equal g1's `ckpt_000000000` (reported) |
| sessions (synthetic) | a small session reusing a synthetic pinned table by digest runs every phase (nothing measured; the drift check 5 of 5 with the source digests), writes every record, passes `verify-run`, pins the final state with the reused table, records the pause and the spacing in every attempt, audits on the reused labels, continues the line (CONTINUE, s2 permitted), reports every g3 reading; two runs agree on every record; stops (lifecycle limit, mismatch, write guard, the hard cap, a memory breach, the training wall cap as a valid end); the reused table: a wrong file digest, a wrong content digest and a missing table are INVALID at the open with nothing trained, a table whose recorded outcome the world does not reproduce is INVALID at T0 (tape drift) with nothing trained; a resumed session copies and checks the inputs, restores the pointer, f and the spacing counter, loads the saved model bit-exactly, continues the counters, the attempt and episode numbering, reads the table by digest and runs the drift check again, evaluates the line rule with both sessions (k = 2, CONTINUE) and passes `verify-run`; a wrong input digest is INVALID at the open; `verify-run` catches an unearned move, a tampered probe mask, a tampered reused table and a tampered member pin |
| guards, identity | no fixture / TAS / recording reference and no native RNG vocabulary in any g3 source (the suite included; the authorised edit at its pinned digest is scanned too); no imitation vocabulary; no training call in the probe module; no attempt bound, no `held_trigger` event and no stalled assignment in the g3 frontier; the suite is deterministic by scan; tracked files unchanged except the authorised edit at its digest, only new M9 files otherwise; the write guard covers the seven protected trees (`runs/m9_g2` included), `rl/` and `docs/` and not the run root; the identity (the spacing, the line budget, the tape pins, the authorised edit) and the approval refusals; the seven protected trees equal their increments and the pins hold; the writers refuse a record without the task block or `created_utc`; the snapshot tool round trip (the g3 files, the g2 and g1 files, the authorised edit and the stop review in the set) |

### 5.2 The production-count synthetic end-to-end run

`python -B rl/m9_g3_tests.py e2e` first measures a pinned tape table on the synthetic world at the registered counts (400 T0 episodes: 200 keys at 2,128 and 40
at each other landing; every claimed clear replayed exactly by the g1 verification plan; the g2 pinned table), which stands in for g2-s1's table. Then **s1** at
the registered counts and caps against the synthetic world (an in-process lock-step pool, a virtual clock charged 1,200 ticks/s per native tick, the synthetic
learner of `rl/m9_g2_stub.py` whose competence boundary moves back as it collects transitions and which, once competent below 1,920, no longer completes from a
cold start at 1,966): the table reused by digest and the 5-key drift check against the source records, the 4,800 s training wall under the replenishing
frontier, the audit (20 + 20 + 1 per audited landing, 20 + 1 at tick 0, on the reused labels), the verification tiers, the close; then **s2** resumed from s1's
saved state (the input copies checked against the final-state digests, the carried pointer, f and spacing counter, the continued counters, the session seed
1002, the table read by digest, the drift check again). It asserts the trigger (8 clears of a window), the strip tests with early stopping, every move earned
by a passing strip test and passing re-checks, the pause (four parked and six probe slots, disjoint, withdrawn starts recorded), BLOCKED_BY_RECHECK at the
forgotten cold landing 1,966 with the pointer unmoved, **every attempt at or past its spacing need with the need following 20 x 2^(f-1) capped at 320,
consecutive failures at a pointer raising f by one each, triggers inside a spacing deferred (logged, no attempt), the 320 cap reached with an attempt run after
a 320-outcome wait, more than six failed attempts at one pointer over the line with the frontier still live (g2 would have STALLED at six), no HELD and no
STALLED state anywhere**, the reused table pinned with 200 / 40 keys and the bars by formula, the s1 rule (INCONCLUSIVE: 2,128 held, 1,966 did not, D_1 = 2128,
s2 permitted), the line after s2 (k = 2, D_2 = 2128: CONTINUE, no attempt count ends it), `verify-run` on both sessions, the metadata of every record, the
artifacts (the five drift episodes, the audit episodes), the g3 readings in the report. **The synthetic world is not Mario**; the e2e says nothing about the
real game.

Measured in preparation (the development run before the three passes, `logs/m9_g3_prep/dev/e2e_dev1.txt`): the two-session e2e takes 997.6 s of wall time (16.6 min); the synthetic tape pinned 200 / 40 keys with every clear replayed; s1 ended INCONCLUSIVE (D_1 = R_1 = 2128) after 19 moves (2,300 -> 1,920) and three BLOCKED_BY_RECHECK attempts at the forgotten cold landing 1,966 (f = 0, 1, 2; the next needs 20 and 40 outcomes, met at 28 and 46; 8 deferred triggers), 1,850 training episodes, 94 replays all exact (20 tier-0 audit clears, none unreplayed); s2 resumed bit-exactly with the carried pointer 1,920, f = 3 and the spacing counter, recorded four more blocked attempts at f = 3, 4, 5, 6 (needs 80, 160, 320, 320 met at 88, 162, 325, 325: the cap reached and an attempt run after a 320-outcome wait; 137 deferred triggers), seven failed attempts at one pointer over the line with the frontier still live, no HELD and no STALLED, and the line continued (k = 2, D_2 = 2128: CONTINUE, s2 permitted); result digest `078f46c445d8adc5`.

### 5.3 Three consecutive passes

**Three consecutive passes with no change in between** (`logs/m9_g3_prep/tools/three_passes.py`, outputs under `logs/m9_g3_prep/final/`): the fingerprint of
`rl/m9_g3_*.py` was `17dea6d712e624ed` before and after every pass; the unit suite passed 25 / 25 each time (531.7 s, 563.9 s, 849.2 s) and the end-to-end run
passed each time (909.4 s, 970.7 s, 1,046.3 s) with the identical result digest `078f46c445d8adc5` (s1 INCONCLUSIVE D = R = 2128 after 19 moves and 3 blocked
attempts; s2 INCONCLUSIVE after 4 more blocked attempts at f = 3..6, the needs 80 / 160 / 320 / 320 met at 88 / 162 / 325 / 325; deferred triggers 8 and 137;
7 failed attempts at pointer 1,920 over the line with the frontier live; the line CONTINUE at k = 2; 94 replays exact, 20 tier-0 clears, none unreplayed).
The g3 half of Part B condition 1 holds; the inherited-suite half does not (section 8).

## 6. Budgets (`rl/m9_g3_run.budget_projection`)

| phase | wall cap | native-tick cap |
| --- | ---: | ---: |
| open (the reused table verified by digest, the pins) | 60 s | 0 |
| P1 lineages | 240 s | 60,000 |
| P2 staging equivalence | 120 s | 60,000 |
| T0 (the 5-key drift check; nothing measured) | 240 s | 60,000 |
| training | **4,800 s** | **20,000,000** (and <= 3,072,000 transitions) |
| close audit | 1,200 s | 3,000,000 |
| verification | 600 s | 1,500,000 |
| close (seven protected trees re-hashed) | 300 s | 0 |
| sum of the caps | 7,560 s (126 min) | |
| **session hard cap** | **8,700 s (145 min)** | |

**Pessimistic projection** (every phase wall cap binding, four pool spawns at 15 s, 20 s of grace per phase): **7,780 s = 129.7 min, 920 s below the
145-minute cap, with no trimming.** The expected projection from g2-s1's measured phases is about 5,730 s (96 min): open 20 s, P1 30 s, P2 40 s, T0 about
60 s (five tape episodes of about 2,500 ticks on a fresh pool), training 4,800 s, the close audit about 300 s, verification about 300 s (g2-s1: 149.8 s for 121
replays, 100 of them tape clears that g3 does not replay; up to 60 audit clears plus 20 training clears plus the probe picks), the close about 180 s (the seven
protected trees re-hashed: g2-s1's close took 88.7 s for six trees of about 0.92 GB; the g2-s1 tree adds 0.99 GB). Expected native ticks: T0 about 15,000,
training about 12 M (g2-s1: 12.0 M in 80 min), audit about 0.45 M, verification about 0.4 M: about 13 M of the 25 M summed caps. The training wall is the
binding end of the training phase in every projection (the transition cap of 3,072,000 would need more than 640 transitions/s for 80 minutes; g2-s1 ran at 49
and g1 at 442).

**The change's cost inside the training wall.** The stop review's model (section 2): on g2-s1's observed curve the move comes with probability 1.00 at a
median of 191 counted outcomes (about 7 minutes at the 2,280 rate); attempts at a stuck strip are about 7 per session at the unit of 20, each 25-35 s of pause
(g2-s1: 24-36 s); the probe share stays within the proposal's 15-25 % for a line that reaches 1,966. A session of deferred triggers costs nothing beyond the
log line.

**Memory.** rd4's and g1's caps (main process 3,072 MB private; tree 9,216 MB private and 4,096 MB working set; system available >= 1,024 MB; commit free
>= 2,048 MB; at most 10 BattleShip processes; a stop needs two distinct samples). g2-s1 measured a main-process peak of 1,250 MB, a tree private peak of
6,429 MB and a working set of 2,229 MB with the same process model; g3 adds nothing to it.

## 7. Defects found while testing and fixed before the three passes (new code only)

| defect | fix |
| --- | --- |
| the session recorder stamped every record with `line=<line id>`, which overwrote the rule record's `line` sub-record (the line outcome) | the stamp field is `line_id` |
| the reused table's key-count check read the registered 200 / 40 even in a synthetic session with fewer keys | the check reads the configured key counts (the registered 200 / 40 in production) |
| test-side: two tests assumed that N outcomes since a failure yield a pending trigger (a trigger needs 8 clears in a FRESH window after each deferral); the attempt test used pointer 2,200, where 11 of the 20 keyed g3 starts lie past the synthetic world's last critical tick (2,211), so an incompetent snapshot passed; the small resumed-session test expected blocked attempts the short window never reaches; the suite spelled one forbidden literal and over-matched a state key | the tests feed outcomes until a trigger is pending; the attempt test uses pointer 2,180; the resumed test checks the carry on whatever s1 left (the production-count e2e covers the blocked path); the literal is assembled and the check reads the exact event name |

None changes a registered measure, threshold, rule, schedule or training setting; the contract digests in section 1 were computed after these fixes.

## 8. The inherited suites after the authorised edit (decision 9)

| suite | result |
| --- | --- |
| g1 evaluation suite (`rl/m9_eval_tests.py unit`) | **29 / 29** passed (86 s); its own `source_guards` compares the assembled strings at run time, so its meaning is unchanged |
| g1 unit suite (`rl/m9_tests.py unit`) | **61 / 63** passed (400 s). `source_guard_no_fixtures_tas_or_recordings` and `source_guard_no_rng_and_no_native_randomness` now PASS (the edit's purpose). Failing: `tracked_files_are_unchanged_and_only_new_files_exist` (the git-state gate: the authorised edit is an uncommitted tracked change) and `identity_names_every_registered_pin`, which asserts that every `rl/m9_*.py` file is in g1's own code identity and has failed since the M9-g1 checkpoint evaluation added `rl/m9_eval_*.py` on 2026-10-04 (commit `4a778b4`; g1's list `rl/m9_session.CODE_FILES` names none of the eval or g2 files tracked at HEAD): pre-existing, independent of decision 9 and of g3, and not fixable without editing a g1 file |
| g2 unit suite (`rl/m9_g2_tests.py unit`) | **28 / 29** passed (521 s). Failing: `tracked_files_are_unchanged_and_only_new_files_exist` (the same git-state gate: the authorised edit is an uncommitted tracked change); every other g2 test passes, the g2 files being clean under g1's fragment scan as before |

The two source-guard failures of g1's suite on the tracked `rl/m9_eval_tests.py` (the stop review, section 4) are gone. The remaining failure in the g1 and
g2 suites is their git-state gate (`tracked_files_are_unchanged_and_only_new_files_exist`), which asserts that no tracked file differs from HEAD; it fails by
construction while the authorised edit is uncommitted (the decisions record, section 4). No state of the tree satisfies both suites' gates and decision 9
without a commit or an edit of those gates, neither of which is authorised.

## 9. The preflight, dry run (before any approval)

`python -B rl/m9_g3_session.py preflight --skip-unit` (`logs/m9_g3_prep/prep_preflight_dry_run.txt`; the unit suite runs in the three passes) refuses for exactly
one problem: **no approval record at `docs/rl_m9_g3_s1_approval.json`**. Everything else passed: the run root absent; the executable, the three runtime files
and the frozen configuration equal the archive's pins; the reused tape baseline equals its registered digests (`81fa52c21078b2c2` / `d915fab920554774`), is
pinned, was measured with the executable now, and its drift records exist; git: exactly the one authorised edit, at its pinned digest, and new files otherwise;
the controller-rule CVars absent; the status table verified; the seven protected trees equal their D: increments with the registered counts, bytes and manifest
digests; both lineages re-derived; D: coverage 423,387 source files, 0 uncovered (12 increments); no BattleShip process; readiness (8,947 MB available, 19,841 MB
free commit, 107.5 GiB free on C:, 1,537.6 GiB on D:); the pessimistic budget 7,780 s fits the 8,700 s cap.

## 10. The launch conditions (Part B), as checked

| # | condition | evidence |
| --- | --- | --- |
| 1 | the g3 unit suite and the e2e pass three consecutive times without changes; the g1, g1-evaluation and g2 suites pass after the decision-9 fix; no non-deterministic test gates | three passes: section 5.3 / `logs/m9_g3_prep/final/passes.json`; the inherited suites: section 8 (**the g1 suite 61 / 63 and the g2 suite 28 / 29 do not pass**: their git-state gates fail by construction on the uncommitted authorised edit, and g1's identity test fails for a pre-existing, unrelated reason); the source scan of the g3 suite forbids randomness, sleeps and wall-clock reads |
| 2 | the pessimistic projection fits the 145-minute cap with no trimming | section 6: 7,780 s = 129.7 min, 920 s of slack |
| 3 | the preflight refuses solely for the missing g3-s1 approval | section 9 |
| 4 | every earlier tree equals its D: increment; the executable, `.o2r` files and frozen configuration match the pins | section 9 (the preflight) and the unit gate `the_protected_trees_equal_their_increments_and_the_pins_hold` |
| 5 | `git status` shows only new files plus the single authorised edit | section 9; `git status --porcelain`: ` M rl/m9_eval_tests.py` and `??` entries only |
| 6 | no open design decision had to be made; any pre-launch fix recorded and flagged | every reading is in the decisions record, section 3 (R1-R12); its section 6 (pre-launch fixes) is empty: the two engine defects of section 7 are corrections of new code to its own specification, made before any pass counted |
