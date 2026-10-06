# M9-g2 preparation: implementation record (2026-10-05)

**Status: zero-native-tick preparation.** The user's decisions for the second robustification gate (`docs/rl_m9_g2_decisions_2026-10-05.md`, which also records the
mechanical readings R1-R17) are implemented in new files only. Before this record was written nothing had launched BattleShip or consumed a native tick (every
process-level run was against the synthetic world of `rl/m9_stub.py`). Nothing was committed or pushed and no branch was created. No tracked file was modified:
every M8, M9-g1 and M9-g1-evaluation file and document, `runs/m8_rd*/`, `runs/m9_g1/` and `runs/m9_g1_eval/` are byte-identical to `HEAD` and to their D:
increments. The external guide was not edited.

**Scope label**, carried by every M9-g2 record (`rl/m9_g2_contract.SCOPE`): *M9-g2-s1: backward-algorithm robustification under the controlled frontier rule
`m9_g2_frontier_v1` (PPO from prefix-replayed start states on the agent's own two verified rd4 clears, sticky actions p = 0.25, observation
btt_policy_obs_v3_entities, reward btt_reward_v2, entropy coefficient 0.01); the first session of a resumable line; one set of keyed draws; progress measured as
the sustained frontier depth D and the reliable reach R at landing states against a pinned tape baseline under the registered rules; no claim of a tick-0 policy.*

## 0. Summary

M9-g2-s1 is g1's recipe (a FRESH PPO policy, the M7n v3 network and profile with the entropy coefficient 0.01, episodes started late on the agent's own two
verified rd4 clears replayed as exact prefixes in fresh processes, sticky actions p = 0.25 everywhere) with ONE change to the training: the frontier pointer
moves back a strip of 20 ticks only when a frozen snapshot of the policy passes a curtailed test from the newly exposed strip (10 clears before 11 non-clears,
on keyed starts, keyed inverse-CDF action draws) AND passes the same test from the trunk's own state at every landing the frontier has already passed. Training
outcomes only trigger a test (8 clears among 20 counted strip outcomes); attempts are bounded (3 per pointer per session: HELD; 6 over the line: STALLED, the line
ends); training pauses while a test runs. The tape baseline is measured once (200 keys at 2,128, 40 elsewhere), every counted tape clear is replayed, the result
is pinned, and the bar is `max(10, ceil(20 p_hat) + 5)`. The session is the first of a resumable line (80 minutes of training under a 145-minute hard cap); at
its close the model, the optimizer state and the frontier state are saved with pinned digests for a separately authorised s2. The s1 rule: PASS iff R_1 <= 1,966;
INCONCLUSIVE iff D_1 <= 2,128; NULL iff D_1 = none; INCOMPLETE and INVALID as g1.

## 1. State

| item | value |
| --- | --- |
| parent | `main` = `origin/main` = `acf522f`; `git status` shows only new untracked files |
| external guide | `Smash_pc_port/guide.md`, unchanged (M9 = robustification since 2026-10-04) |
| executable | `build-us/Release/BattleShip.exe` `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee` (the archive's pin), hashed, not run; `.o2r` files, `gamecontrollerdb.txt` and the frozen configuration equal rd1's pins |
| compute | Python 3.13.2, SB3 2.9.0, torch 2.14.0 (CPU), gymnasium 1.3.0, numpy 2.5.3; six logical CPUs, 16 GB |
| protected trees | rd1 166 files, rd2 62, rd3 77, rd4 93, `m9_g1` 2,740, `m9_g1_eval` 1,393: each equals its D: increment byte for byte (the g2 preflight and the unit gate `the_protected_trees_equal_their_increments_and_the_pins_hold`) |
| D: | the base plus the increments up to `2026-10-04_incr_m9_g1_eval` cover every `runs/` file (0 uncovered); the g2 increment `2026-10-05_incr_m9_g2_s1` is created after the run by the unchanged `rl/tools/runs_backup.py` |
| digests | g2 contract `8dfd44c6a8b7e31942de0d0ee6bd2784e4fa9b0475182c624cbe2ca07132aab8`; line contract `1aadc7a6b2ff85bd83b8bff80c2b97c3081652e845996546429ba2a483379e12`; frontier rule `aac6a990883315b0...`; s1 rule `73351aa313c46a85...`; line rule `d10d2ad84f399891...`; g1 contract (unchanged, read) `6958857e...` |

## 2. Files (all new; 5,199 lines of Python)

| file | role |
| --- | --- |
| `rl/m9_g2_contract.py` | every registered g2 constant (the frontier rule, the tape keys, the bars, the s1 and line rules, the envelope caps, the split, the keys) read over the unchanged g1 constants; `contract_digest`, `line_contract_digest` |
| `rl/m9_g2_arena.py` | the g1 sticky rule on g2 keys (`submit`, `mask_from_keys`, `check_record`), `G2EpisodeCtx`, `G2TickBudget` (the probe split), `G2Arena` (a slot subset, the pause, in-flight accounting, `withdraw_parked`, a batch-safe `pump`) |
| `rl/m9_g2_frontier.py` | `Frontier`: g1's start distribution on g2 keys, the curtailed trigger window, attempts with the per-session and per-line bounds (HELD / STALLED), the move, the carried state, `replay_history` (the rebuild from records) |
| `rl/m9_g2_policy.py` | `FrozenPolicy`: a weight-only copy of the live network (rl/m9_eval_policy's building blocks, no optimizer guard), keyed inverse-CDF sampling, argmax, value / entropy / top-word stats; the snapshot file and its digest |
| `rl/m9_g2_tape.py` | T0 jobs (keyed, interleaved), the claimed table, the pinned table (verified clears only, p_hat, B, digest), the drift jobs of a later session |
| `rl/m9_g2_rule.py` | D, R, `FRONTIER_BACKED`, `m9_g2_s1_rule_v1`, `m9_g2_line_rule_v1`, the self-test (`python rl/m9_g2_rule.py self-test`) |
| `rl/m9_g2_probe.py` | the probe runner (curtailment, cancellation, abandoned episodes, lifecycle requeue), the strip / re-check / audit jobs, `run_attempt` (the pause, the snapshot, the strip test, the parallel fail-fast re-checks, the move, the hand-back) |
| `rl/m9_g2_train.py` | the g2 recorder (windows, withdrawn starts), checkpoints with `curriculum_state.json` and member pins, the callback with the attempt hook at the rollout boundary, `train`, `make_fresh_ppo`, `resume_ppo` |
| `rl/m9_g2_resume.py` | the final-state record, the input copy with digests, the continuity assertions (num_timesteps, _n_updates, every Adam step), the refusals, bit-exact tensor comparison |
| `rl/m9_g2_run.py` | `G2Session` (open, g1's P1 and P2, T0, training, the close audit, verification by tiers, the pinned tape, the close with the s1 rule, the line rule and the final-state record), `G2Clock`, `budget_projection` |
| `rl/m9_g2_report.py` | `verify_run` (masks from keys, words digests, starts from keys, the frontier history from records, the bounds, the checkpoint pins, the tape table, D / R and the rule recomputed, the metadata audit) and `full_report` |
| `rl/m9_g2_session.py` | the CLI: identity, approval, preflight (the six protected trees), write-guard roots, the real hooks, `run`, `verify-run`, `report`, `status`, `approval-template` |
| `rl/m9_g2_snapshot.py` | the verified D: source snapshot (the procedure of rl/m9_eval_snapshot.py) |
| `rl/m9_g2_stub.py`, `rl/m9_g2_tests.py` | the synthetic learner (competence boundary, exact state round trip, resume, injectable cold-start forgetting), the frozen stand-in, the builder; the unit suite and the two-session e2e |
| `logs/m9_g2_prep/tools/` | `three_passes.py`, `write_approval.py`, `independent_increment_check.ps1` (a copy of g1's; Git-ignored) |
| `docs/rl_m9_g2_decisions_2026-10-05.md`, this record | |

Reused unchanged (read-only): every `rl/m9_*.py` module of g1 (`m9_contract`, `m9_artifacts`, `m9_sticky`, `m9_curriculum`, `m9_lineages`, `m9_verify`, `m9_worker`, `m9_pool`,
`m9_vec`, `m9_train`, `m9_eval`, `m9_run`, `m9_session`, `m9_snapshot`, `m9_stub`, `m9_testenv`), `rl/m9_eval_policy.py`, the M8 workers and helpers, `rl/m7n_*`, `rl/btt_rewards.py`,
`rl/tools/runs_backup.py`. No inherited file is edited: the g1 sticky key, start key and block rule are not changed; g2 derives from them in new classes.

## 3. The design as implemented

**Process model.** As g1: the session process (the learner, the arena, the engine) and ten spawned worker processes, one BattleShip slot each, never reused. The
fixed 4 + 6 split: four playing slots hold the training episodes, six prepare starts. During an attempt the four playing slots stay parked at
`WaitingForAction` and the six others run the probes under a second arena over the same pool, restricted to those slots; the slots are handed over and handed
back only when every command sent to them has been answered (decision R3). At most 10 BattleShip processes exist at any time.

**The frontier.** `Frontier.record` keeps the curtailed window (trigger at the 8th clear, void at the 13th non-clear; outcomes after a trigger are logged as
`after_trigger`; a trigger while HELD is logged as `held_trigger`). The attempt runs in the training callback's `on_rollout_start` (after the previous
update): the weights are copied once to `training/attempts/a<n>/snapshot_policy.pth` (its sha256 is the recorded snapshot digest) and loaded back as a
weight-only network; the strip test runs 20 keyed starts (`m9|g2|probe|<pointer>|<a>|strip|<k>|tau`), passes at the 10th clear and fails at the 11th non-clear;
only then every landing >= pointer + 20 is re-checked from the trunk's own state, in parallel, failing fast. `Frontier.finish_attempt` moves the pointer only when
every test passed, counts a failed attempt per pointer per session and over the line, and sets HELD / STALLED. STALLED raises a registered valid end of training.

**Records.** `training/{episodes,rollouts,stale,windows,withdrawn,attempts,probes,moves}.jsonl`, `training/attempts/a<n>/snapshot_policy.pth`,
`training/checkpoints/<ckpt>/{model.zip,curriculum_state.json,checkpoint.json}`, `t0/{episodes.jsonl,tape_table.json}`, `audit/episodes.jsonl`,
`verification/replays.jsonl`, `session/{open,p1,p2,t0,training_summary,audit_run,verification,tape_baseline,close,rule,line,final_state,state,...}.json`,
`artifacts/` (M4-form artifacts for every T0, audit and clearing probe episode, every training clear and a keyed 2 % sample). Every write goes through
`rl/m9_artifacts` (the task block and `created_utc`; the writer refuses without them).

**Verification tiers** (decision 8, R11): 0 = every close-audit sticky clear at an audited landing and every T0 tape clear; 1 = the first 20 training clears;
2 = one keyed clear per passed test of every attempt; 3 = the diagnostics. The pinned tape table is written after the verification from the verified clears only.

**Resume (decision R14).** Implemented (`G2Session.open` with `cfg.resume`, `rl/m9_g2_resume`, `rl/m9_g2_train.resume_ppo`) and tested synthetically and on
the real SB3 model at zero ticks; s2 is not run and not authorised.

## 4. The checks at the open (preflight)

`python -B rl/m9_g2_session.py preflight`: Python started with `-B`; the run root `runs/m9_g2/s1` absent; the g2 unit suite and the g2 rule self-test; the
executable present; tracked files equal `HEAD` and only new files untracked; the executable, the three runtime files and the frozen configuration equal the
archive's pins; the controller-rule CVars absent; the status table; the six protected trees equal their D: increments with the registered counts, bytes and
manifest digests; both registered lineages re-derived; D: coverage with 0 uncovered; no BattleShip process; readiness (>= 4,096 MB available, >= 10,240 MB free
commit, >= 5 GiB free on C: and D:); the pessimistic budget fits the 145-minute cap; the approval (its task block and `created_utc`, identity, code hashes, docs
hashes, git head, D: records) and the source snapshot. A memory, commit or free-space refusal is a stop, never a reason to close an application.

## 5. Tests

`python -B rl/m9_g2_tests.py unit` runs the deterministic suite (29 tests, section 5.1); `python -B rl/m9_g2_tests.py e2e` the production-count synthetic
two-session line (5.2). No test starts a game process; a source scan forbids `random`, `secrets`, `uuid`, `os.urandom`, `np.random`, `torch.manual_seed`,
`time.sleep` and any wall-clock read inside a test.

### 5.1 The unit suite (groups)

| group | what is asserted |
| --- | --- |
| contract, keys, bars | every registered g2 value; the g1 values it reads are unchanged; the pessimistic budget (8,440 s of 8,700 s, slack 260 s); every key string is the `m9|g2|...` family and differs from g1's; `bar_from_counts` at the boundaries (95/200 -> 15, 101/200 -> 16, 10/40 -> 10, 11/40 -> 11); the rule self-test |
| sticky, arena | g1's rule on g2 keys (nothing at tick 0, the prefix's last word may repeat, the 0.25 rate over 20,000 keyed draws, masks rebuilt from keys, tampering caught); a subset arena dispatches only on its slots, pauses, withdraws and records parked starts, counts in-flight commands and settles; a second arena shares the pool without touching the first's slots; a stray event is returned loudly; a death outside the subset stops the attempt |
| frontier | the window (trigger at the 8th clear, void at the 13th non-clear, `after_trigger`, stale and non-strip ignored); attempts (a move of 20 and a window restart, failed attempts counted, HELD at 3 in a session with `held_trigger`, STALLED at 6 over the line through the carried state, a stalled state refused, a move without passing tests refused, INTERRUPTED counts nothing); the audit landings per pointer; keyed starts (the 50 / 30 / 20 mix, starts within the strip, strip-test starts keyed by attempt); the history rebuilt from records and four tamperings caught |
| frozen policy | sampling is a pure function of (weights, observation, key); argmax and probabilities equal the same weights inside a real SB3 policy (`get_distribution`, `predict(deterministic=True)`); a wrong pin refused; `state_dict_of` a live PPO has the 12 registered keys |
| tape | 400 T0 jobs (200 / 40), interleaved, unique keys; the claimed and pinned tables (verified clears only, B, unpinned when a clear is unreplayed, an inexact replay listed, the digest) |
| probes, attempt | source cancellation and requeue; `TestState` curtailment at the 10th clear / 11th non-clear; the runner on the synthetic world (pass with early stopping and abandoned episodes, fail at 11 non-clears, parallel re-checks failing fast at the forgotten cold landing, the tape driver completing every job, lifecycle requeue with the same id, a mismatch is INVALID); `run_attempt` with four parked training episodes and six probe slots (MOVED, FAILED_STRIP at a strip with critical ticks, BLOCKED_BY_RECHECK at 1,966 with the pointer unmoved and the re-check set equal to every landing behind the frontier, INTERRUPTED by a cap with the slots handed back settled; withdrawn starts recorded, probe ticks charged, the snapshot digest and file, one keyed clear per passed test) |
| checkpoints, resume | the three files per checkpoint with the pins (model.zip, both members, the curriculum state); the synthetic learner's state round trip; **the real SB3 model at zero ticks**: save / load bit-equal in every tensor, Adam moment and step; `assert_continuity`; one update after the reload equals the same update without it (every tensor, Adam moment and step bit-exact); the refusals (a counter mismatch, a changed contract / executable / PPO value, a stalled state, a wrong input digest); `resume_ppo` on a rollout-sized model sets the session seed and refuses a wrong rollout; the fresh PPO's untrained tensors equal g1's `ckpt_000000000` (reported) |
| sessions (synthetic) | a small session runs every phase, writes every record, passes `verify-run`, pins the tape, saves the final state, records the pause in every attempt; two runs agree on every record; stops (lifecycle limit, mismatch, write guard, a T0 wall cap, the hard cap, a memory breach, the training wall cap as a valid end); a resumed session copies and checks the inputs, restores the carried state, loads the saved model bit-exactly, continues the counters and the episode numbering, skips T0 by digest, evaluates the line rule with both sessions and passes `verify-run`; a wrong input digest is INVALID at the open with nothing trained; `verify-run` catches an unearned move, a tampered probe mask and a tampered member pin |
| guards, identity | no fixture / TAS / recording reference and no native RNG vocabulary in any g2 source (the tests included; the fragments are assembled so that the suite is itself clean under g1's scan); no imitation vocabulary; the probe runner builds no optimizer; the suite is deterministic by scan; tracked files unchanged and only new M9 files; the write guard covers the six protected trees, `rl/` and `docs/` and not the run root; identity pins and the approval refusals; the six protected trees equal their increments and the pins hold; the snapshot tool round trip |

### 5.2 The production-count synthetic end-to-end run

`python -B rl/m9_g2_tests.py e2e` runs **s1** at the registered counts and caps against the synthetic world (an in-process lock-step pool, a virtual clock charged
1,200 ticks/s per native tick, a synthetic learner whose competence boundary moves back as it collects transitions and which, once competent below 1,920, no
longer completes from a cold start at 1,966): 400 T0 episodes, the 4,800 s training wall under the controlled frontier, the audit (20 + 20 + 1 per audited landing,
20 + 1 at tick 0), the verification tiers, the close; then **s2** resumed from s1's saved state (the input copies checked against the final-state digests, the carried
frontier state, the continued counters, the session seed 1002, T0 skipped by digest). It asserts the trigger (8 clears of a window), the strip tests with early
stopping, every move earned by a passing strip test and passing re-checks, the pause (four parked and six probe slots, disjoint, withdrawn starts recorded),
BLOCKED_BY_RECHECK at the forgotten cold landing 1,966 with the pointer unmoved, HELD after three failed attempts at one pointer, the pinned tape baseline (200 / 40
keys, every counted clear replayed, the bars by formula), the s1 rule (INCONCLUSIVE: 2,128 held, 1,966 did not, D_1 = 2,128, s2 permitted), `verify-run`, the
metadata of every record, the artifacts; in s2 the bit-exact resume, the line attempt index continuing (a = 4, 5, 6), STALLED after six failed attempts over the line
as a valid end of training, and the line outcome END_STALLED. **The synthetic world is not Mario**; the e2e says nothing about the real game.

Measured in preparation (the development run before the three passes): the two-session e2e takes about 9.7 minutes of wall time; s1 ended INCONCLUSIVE (D_1 = R_1 =
2,128) after 19 moves (2,300 -> 1,920) and three BLOCKED_BY_RECHECK attempts at the forgotten cold landing 1,966 (HELD), 1,847 training episodes, 222 replays all
exact (148 tier-0 clears, none unreplayed); s2 resumed bit-exactly, recorded three more blocked attempts (a = 4, 5, 6), STALLED, and the line ended END_STALLED.

### 5.3 Three consecutive passes

Filled from `logs/m9_g2_prep/final/passes.json` (Part B condition 1) in the session report and in section 9 below.

## 6. Budgets (`rl/m9_g2_run.budget_projection`)

| phase | wall cap | native-tick cap |
| --- | ---: | ---: |
| open | 60 s | 0 |
| P1 lineages | 240 s | 60,000 |
| P2 staging equivalence | 120 s | 60,000 |
| T0 tape baseline (s1) | 900 s | 1,500,000 |
| training | **4,800 s** | **20,000,000** (and <= 3,072,000 transitions) |
| close audit | 1,200 s | 3,000,000 |
| verification | 600 s | 1,500,000 |
| close | 300 s | 0 |
| sum of the caps | 8,220 s (137 min) | |
| **session hard cap** | **8,700 s (145 min)** | |

**Pessimistic projection** (every phase wall cap binding, four pool spawns at 15 s, 20 s of grace per phase): **8,440 s = 140.7 min, 260 s below the
145-minute cap, with no trimming.** The expected projection from g1's measured throughputs is about 6,260 s (104 min): open 20 s, P1 30 s, P2 40 s, T0 about
560 s (400 tape episodes at g1's P4 rate of 0.74 episodes/s on ten slots), training 4,800 s, the close audit about 300 s (two or three audited landings: 103-144
episodes at g1's evaluation rate of 0.62 episodes/s), verification about 420 s (about 100 tape clears of 2,326 ticks, up to 60 audit clears, 20 training clears, the
probe picks and the diagnostics: about 550,000 ticks at g1's replay rate of about 1,650-1,800 ticks/s on eight threads), close about 90 s (the six protected trees
re-hashed). Expected native ticks: T0 about 1.0 M, training about 11 M (g1: 7.9 M in 60 min plus the probes), audit about 0.45 M, verification about 0.55 M: about
13 M of the 26 M summed caps. The training wall is the binding end of the training phase in every projection (the transition cap of 3,072,000 would need more
than 640 transitions/s for 80 minutes; g1 ran at a median 442/s).

**Probe cost inside the training wall** (proposal 2.4): about 14-17 probe episodes per strip test plus about 14 per re-checked landing; at about 0.5 episodes/s
on six slots that is 30-90 s per attempt; the proposal's estimate of 15-25 % of the training wall for probes holds for a line that reaches 1,966; the pause time is
recorded per rollout (`pause_s`) and per attempt.

**Memory.** rd4's and g1's caps (main process 3,072 MB private; tree 9,216 MB private and 4,096 MB working set; system available >= 1,024 MB; commit free >=
2,048 MB; at most 10 BattleShip processes; a stop needs two distinct samples). g1 measured a main-process peak of 1,534 MB and a tree working set of 2,372 MB with
the same process model; the frozen policy adds a 77 k-parameter network per attempt (freed after it) and the probe records.

## 7. Defects found while testing and fixed before the three passes (new code only)

| defect | fix |
| --- | --- |
| a stop raised while handling one event of a polled batch dropped the batch's remaining replies, so the slots could never settle and a phase waited until its wall cap (seen as a T0 wall cap under injected launch failures) | `G2Arena.pump` handles every event of a batch before the first stop propagates |
| the rule hardcoded 20 audited episodes; `verify-run` rebuilt the tape table with the contract's key counts instead of the recorded ones | the rule reads the audited count from the facts (the registered 20 in production); `verify-run` reads the recorded claimed table's key counts |
| the final-state record could not read the synthetic learner's zip (no SB3 `data` member) | `saved_counters` reads the stand-in format when there is no `data` member (the real path unchanged) |
| a wrong resume input digest surfaced as a software error | it is an integrity stop (INVALID at the open, nothing trained) |
| the resumed session's open compared the pinned tape table's content digest with the input file's hash (two different digests), so every resume would have been refused | the file hash is checked against the final-state record and the approval by the input copy; the open checks the table's content digest against itself and that the table is pinned |
| the probe runner's guard tests and the source-guard test read their own literals | test-side corrections (the guard fragments are assembled; the SB3 equivalence test seeds each learner immediately before its rollout; the zero-tick env's observations depend on the step only) |

**Pre-launch hazard fixed and flagged (decisions record, section 5, H1):** replay launches in the verification phase stop 120 s before the phase's wall cap
(`VERIFY_LAUNCH_MARGIN_S`), so the replays in flight finish inside the cap; the cap, the tiers and the counting are unchanged.

None changes a registered measure, threshold, rule, schedule or training setting; the contract digests above were computed after these fixes.

## 8. Known conditions of the inherited suites (not changed)

g1's unit suite (`rl/m9_tests.py`) scans every `rl/m9_*.py` file except itself for forbidden literals; since the M9-g1 checkpoint evaluation added
`rl/m9_eval_tests.py` (tracked, unchanged, containing those literals in its own guard), two g1 guard tests fail on that file. This predates g2. The g2 files
pass g1's fragment scan (checked separately); the g2 suite assembles its own fragments so that it is clean under that scan.

## 9. The launch conditions (Part B), as checked

Filled in the session report from the records: the three passes (`logs/m9_g2_prep/final/`), the pessimistic projection (section 6), the dry-run preflight, the
protected trees and pins, `git status`, and the absence of open design decisions (every reading is in the decisions record, section 3).
