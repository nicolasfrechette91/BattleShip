# M9-g3 session 2: the launch-path preparation and its decisions (2026-10-07)

**Status: zero-tick preparation. Nothing launched, nothing trained, nothing approved, no commit, no push.** This session implements the minimal fixes of
the independent pre-launch review `docs/rl_m9_g3_s2_prelaunch_review_2026-10-07.md` (H1 to H15, S1, M1, N1) so that a later, separately authorised launch
session can run M9-g3 **session 2** as a RESUME of session 1's recorded final state. Edited: the tracked `rl/m9_g3_train.py`, `rl/m9_g3_run.py`,
`rl/m9_g3_report.py`, `rl/m9_g3_session.py`, `rl/m9_g3_snapshot.py`, `rl/m9_g3_tests.py` (nothing else under `rl/`; no g1, g2 or M8 file; no inherited
module). Added: this record, the s2 tools under `logs/m9_g3_s2_prep/tools/` (Git-ignored) and the preparation logs under `logs/m9_g3_s2_prep/`. No file
under `logs/m9_g3_prep/` (s1's preparation) was written by this session's tooling; one 18-byte file there was overwritten by an accident at the start of
the session and is NOT restored (section 4: the user restores it with one copy command). No file under `runs/` was written. The two existing docs the user
had staged before this session (`docs/rl_m8_sd1_proposal_2026-10-07.md`, `docs/rl_m9_g3_s2_prelaunch_review_2026-10-07.md`) were not touched; the
review's author session was still appending to its own file while this session ran (its section 9.1 records this session's first edits).

| item | value |
| --- | --- |
| checkout | `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, branch `main` |
| HEAD = `origin/main` at the start | `f221a3929a689c6fcf8452a593192b5abb35c8e5` |
| `git status --short` at the start | `A  docs/rl_m8_sd1_proposal_2026-10-07.md`, `A  docs/rl_m9_g3_s2_prelaunch_review_2026-10-07.md` (both staged by the user; the second later `AM`, modified by its own author session) |
| read in full | `CLAUDE.md`; `docs/rl_m9_g3_decisions_2026-10-06.md`; `docs/rl_m9_g3_implementation.md`; `docs/rl_m9_g3_recheck_2026-10-06.md`; `docs/rl_m9_g3_launch_record_2026-10-07.md`; `docs/rl_m9_g3_s1_results_2026-10-07.md`; `docs/rl_m9_g3_s2_prelaunch_review_2026-10-07.md`; the ten `rl/m9_g3_*.py`; `rl/m9_g2_resume.py`; the relevant parts of `rl/m9_g2_run.py`, `rl/m9_g2_train.py`, `rl/m9_g2_session.py`, `rl/m9_g2_frontier.py`, `rl/m9_g2_stub.py`, `rl/m9_stub.py`, `rl/m8_rd_session.py`, `rl/m8_rd_resume.py`, `rl/m9_run.py`, `rl/m9_vec.py`, `rl/m7n_policy.py`, `rl/m7n_obs.py`; the five s1 tools under `logs/m9_g3_prep/tools/`; `runs/m9_g3/s1/session/{final_state,line}.json`, `training/checkpoints.json`, `training/checkpoints/final/curriculum_state.json`; `docs/rl_m9_g3_s1_approval.json`; the D: increment's `verification.json` |
| g3 source fingerprint before any edit | `f92ca9067813b9e6` (= the s1 launch value) |
| g3 source fingerprint after the last edit | **`e30b10a9f453c88a`** (over `m9_g3_contract.py 3e720ca8..., m9_g3_frontier.py 21ea1137..., m9_g3_probe.py 74c66f7d..., m9_g3_report.py d63b2487..., m9_g3_rule.py 4a9e5320..., m9_g3_run.py 8d69b11b..., m9_g3_session.py d9a08271..., m9_g3_snapshot.py bfd4cecc..., m9_g3_tests.py f0aa18cf..., m9_g3_train.py d74f1891...`; contract, frontier, probe and rule unchanged from s1) |
| Python / libraries | 3.13.2; SB3 2.9.0; torch 2.14.0+cpu; numpy 2.5.3; gymnasium 1.3.0 (`python -B -X utf8` throughout) |

## 0. What a launch session will find

`python -B -X utf8 rl/m9_g3_session.py preflight --session 2` no longer refuses by construction. It checks the predecessor (`runs/m9_g3/s1`: the final-state
record, the three inputs at their recorded digests, the model's two members, the line outcome CONTINUE with the next session permitted, the records'
consistency, the curriculum state being s1's FINAL one, the line contract and the executable unchanged) and treats `runs/m9_g3/s1` as the eighth protected
tree (4,935 files, 508,166,787 bytes, manifest `d12966c135fdb614...`). `identity(2)` carries a `resume_inputs` block, so the s2 approval pins s1's final
model (`669692023c2d...`, members `ffce3303...` / `c072b0db...`), state (`74adedd8...`), tape (`81fa52c2...`), counters (708,712 / 1,380 / Adam 13,800 x 12),
`previous_sessions` (s1's row from its line record) and s1's tree facts. `run --session 2` builds the resume configuration with `expect` from the APPROVAL,
`previous_sessions` from `runs/m9_g3/s1/session/line.json`, and no tape reuse. The resumed open adds the predecessor assertions; training writes periodic
checkpoints at 708,712 + j x 102,400 and refuses, before the first rollout, an initial checkpoint whose members differ from s1's final members; `verify-run
--session 2` cross-checks the previous-session list, the inputs and the initial members against s1's records. The tools under `logs/m9_g3_s2_prep/tools/`
write the s2 approval (from a verbatim authorisation file with its date), launch `--session 2` into `logs/m9_g3_s2_run/`, wait on
`runs/m9_g3/s2/session/state.json`, and run the three passes into `logs/m9_g3_s2_prep/final/`.

## 1. Every change, by finding id

| id | severity (review) | change | where |
| --- | --- | --- | --- |
| H1 / H5 | BLOCKER / MAJOR | the resume branch of the CLI. `preflight(k >= 2)`: the refusal "only session 1 is prepared" is replaced by `predecessor_problems(k)` (section 1.1) and the eighth tree (H4); the report gains `predecessor` and `resume_inputs`. `identity(k >= 2)` gains `resume_inputs` = `resume_inputs(k)` (section 1.2), measured from the predecessor's tree at identity time, compared by `approval_status` like every other identity key. `cmd_run(k >= 2)`: `expect` = the approval's `resume_inputs.expect` (never the tree); `previous_sessions` = `m9_g3_report.read_previous_sessions(runs/m9_g3/s<k-1>)` (H3), refused unless equal to the approval's; `G3Config(..., resume={final_state, expect, previous_sessions}, tape_source_records=TAPE_RECORDS, tape_reuse=None)`; the open record adds `resume_source` and the preflight's `predecessor` block | `rl/m9_g3_session.py` |
| H2 | MAJOR | `G3Callback._on_rollout_start` overrides g2's: a periodic checkpoint when `n > start_timesteps and (n - start_timesteps) % every == 0`; the attempt hook copied from g2 verbatim; g2's STALLED stop omitted (unreachable: the g3 frontier has no HELD and no STALLED). `CHECKPOINT_EVERY` (102,400), the line contract and its digest are unchanged; the train module's `contract_description` (not part of any registered digest) names the alignment. Recorded as a pre-launch hazard fix in section 3 | `rl/m9_g3_train.py` |
| H3 | MAJOR | `previous_sessions_problems(sessions, line_rec, final_state)` and `read_previous_sessions(predecessor_root)` (new, pure): the list is READ from the predecessor's `session/line.json` and must be consistent with its `session/final_state.json` (non-empty; the last row the predecessor's own session and outcome; the line outcome CONTINUE with the next session permitted in both records; the registered line rule reproducing the recorded outcome from the rows). Used by `resume_inputs`, `cmd_run`, the tests and the e2e. `verify_run(root, predecessor_root=None)` cross-checks the list recorded at the open against the predecessor's record and the session's own line rows (`prev + [this]`); the predecessor root defaults to the sibling `s<k-1>`; its absence is a problem | `rl/m9_g3_report.py`, `rl/m9_g3_session.py` (`cmd_verify_run` passes `run_root(k-1)`) |
| H4 | MAJOR | `PREDECESSOR_TREES = {1: ("m9_g3_s1", runs/m9_g3/s1, D:\BattleShip_runs_backup\2026-10-07_incr_m9_g3_s1, {files 4935, bytes 508_166_787, manifest d12966c1...})}`; `trees_for(k)` = the seven of s1's design plus every registered earlier g3 session tree; `trees_state(k)` (hence `earlier_trees(k)`, `identity(k)["trees"]`, the preflight, the open's and the close's checks) uses it; `unregistered_predecessors(k)` makes a session after an unregistered tree refusable. `TREES` itself stays the seven (s1's design, s1's tests). The two tree tests assert the seven for k = 1 and the eight for k = 2 with the registered facts | `rl/m9_g3_session.py`, `rl/m9_g3_tests.py` |
| H6 | MINOR | `predecessor_assertions(cs, fs, session, table_sha256, members)` (new, pure), run in the resumed branch of `G3Session.open` after the g2 compatibility check: (1) the curriculum state is session k-1's, its `sessions` are 1..k-1 and its `num_timesteps` equals the final-state counters' (the state of a NON-FINAL checkpoint is refused even when the approval's digests name it); (2) the final-state record is session k-1's; (3) its line outcome permits a next session; (4) the state's `tape_table_sha256` equals the copied table's content digest, and the copied model's members equal the record's. Any problem is INVALID at the open with nothing trained. The open record gains `resume.members` and `resume.predecessor`. The same assertions run early in `predecessor_problems` at the preflight | `rl/m9_g3_run.py` |
| H10 | MINOR | `verify_run` reads the copied tape's digest from `open.json`'s `resume.inputs.files.tape_baseline` when there is no `tape_reuse` record, and reports which one it used (`tape.recorded_at_open_as`); neither recorded is a problem | `rl/m9_g3_report.py` |
| H12 | MINOR | the real resume path's bit-exactness is asserted in production: `train(..., expect_initial_members=...)` compares the initial checkpoint's `policy.pth` and `policy.optimizer.pth` digests with the predecessor's final members inside the `save` closure, i.e. at `_on_training_start` BEFORE the first rollout (a wrong load costs no training); a difference raises `IntegrityStop` (INVALID). `G3Session.train` passes `self.resume_members` (recorded at the open). `verify_run` re-checks `ckpt_<saved count>` against the open record and the predecessor's final state. The premise (a `PPO.load` + `save` round trip of the REAL model reproduces the member bytes) is established by the new unit test on s1's actual `model.zip` (section 5), which answers the reviewer's section 9.1 observation 1 | `rl/m9_g3_train.py`, `rl/m9_g3_run.py`, `rl/m9_g3_report.py` |
| S1 / H14 | MINOR | `S2_DOC_FILES` (the s1 results record, the s1 launch record, the s1 approval, the re-check record, the s2 pre-launch review, this record) are in `identity(k >= 2)["docs_sha256"]` and in the session-2 snapshot's file set; `rl/m9_g3_snapshot.py snapshot --session 2` computes `identity(2)`, records `session` and `log_dirs`, and adds `logs/m9_g3_s2_prep/**` to the set (`logs/m9_g3_prep/**` stays in it unchanged). `snapshot_dest_default(k)` for the template. Every s2 preparation log and three-pass output goes under `logs/m9_g3_s2_prep/` | `rl/m9_g3_snapshot.py`, `rl/m9_g3_session.py` |
| H9 / H11 / N1 (B12) | document | `LINE_CONSEQUENCE` (the END_BUDGET_2128 consequence of session 2, the audit pairing by identical keys, the meaning of `s2_permitted`) is written into the s2 approval by the writer and into the approval template for k >= 2 | `rl/m9_g3_session.py`, `logs/m9_g3_s2_prep/tools/write_s2_approval.py` |
| tools (B11) | process | new files in `logs/m9_g3_s2_prep/tools/`: `write_s2_approval.py` (identity(2); `--authorisation-file` quoted verbatim with `--authorised-on`; refuses an existing approval, a non-PASS or non-session-2 snapshot, a snapshot at another HEAD, predecessor problems, an empty authorisation), `launch_detached_s2.ps1` (`--session 2`; logs under `logs/m9_g3_s2_run/`; refuses when a session log, `runs/m9_g3/s2` or no approval exists), `wait_session_s2.py` (`runs/m9_g3/s2/session/state.json`, `--repo`), `three_passes_s2.py` (`--out`, default `logs/m9_g3_s2_prep/final/`; refuses to overwrite `passes.json`; argparse, so `--help` is a help text and not a run). The generic `logs/m9_g3_prep/tools/independent_increment_check.ps1` is reused as it is (`-Source runs/m9_g3/s2`) | `logs/m9_g3_s2_prep/tools/` |
| tests | | 25 -> 28 tests (section 5): the real-model resume round trip on s1's final checkpoint; the s2 checkpoint alignment on the stub; `resume_inputs` and `previous_sessions` read from the records (with the pure tampering cases of H3 and H6); the eighth tree in the two tree tests and `identity(2)` with its approval round trip; the resumed-session test reads `previous_sessions` from the records, checks `verify_run` with the predecessor root (H3 / H10 / H12) and the H6 refusals (a non-permitting line, a non-final checkpoint's state, a wrong session); the snapshot round trip runs `--session 2`; the e2e reads `previous_sessions` from s1's records and checks the H12 and H2 facts (its digest is unchanged by construction: it covers outcomes, moves, attempts, the line verdict, the episode count and the deferred counts only) | `rl/m9_g3_tests.py` |

### 1.1 `predecessor_problems(k)` (the preflight, k >= 2)

`resume_inputs(k).problems` (a missing final-state record or line record; an input missing or not at its recorded digest; a recorded path that is not the
file under the predecessor's tree; members differing from the record; inconsistent records per H3; an unregistered predecessor tree) plus: the final-state
record not session k-1's; the line outcome not CONTINUE or the next session not permitted; the line contract digest not this code's; the executable now
not the one the state was produced with; the saved frontier rule not `m9_g3_frontier_v1`; and the H6 assertions on the predecessor's final
`curriculum_state.json`, `final_state.json` and `input/tape_baseline.json`. The tree's byte equality with its D: increment is `trees_state(k)`'s eighth entry.

### 1.2 `resume_inputs(k)` (the identity, hence the approval)

`predecessor_session`, `root`, `final_state_sha256`, `files` {model_zip, curriculum_state, tape_baseline: path (repository-relative), `sha256_recorded`,
`sha256_now`, bytes}, `members_now`, `members_recorded`, `session`, `outcome`, `line`, `counters`, `next_session_seed`, `executable_sha256`,
`line_contract_sha256`, `spacing_final`, `previous_sessions` (from the line record), `tree` (the registered facts), `expect` (the three `sha256_now`),
`problems`. Measured from `runs/m9_g3/s1` today: `expect` = {`669692023c2dacf8...`, `74adedd8004b6e49...`, `81fa52c21078b2c2...`}; members
`ffce330386c8c133...` / `c072b0dbf4a3d21e...`; counters {708,712; 1,380; seed 0; Adam 13,800.0 on 12}; next seed 1002; line CONTINUE, next session permitted;
`previous_sessions` = `[{"k": 1, "outcome": "NULL", "D": null, "R": null, "train_fraction": 0.9985, "attempts": 13, "failed_attempts": {"2220": 4, "2240": 1, "2280": 4}}]`;
tree {m9_g3_s1, 4,935 files, 508,166,787 bytes, `2026-10-07_incr_m9_g3_s1`, manifest `d12966c135fdb614f08fab2d63ff0af894d171834ed9f87c802103b9024307a5`};
file sizes 1,110,611 / 6,496 / 7,768 bytes; problems `[]`.

## 2. Decisions taken by this session (none changes a registered measure, threshold, rule, schedule or training setting)

| # | decision | why |
| ---: | --- | --- |
| D1 | `expect` comes from the approval; `previous_sessions` from the predecessor's line record; the identity measures the tree at approval-writing time | the review's 1.4 item 2 and H3 / H5: the approval is the source of truth for what the open checks the copies against, and a reviewer sees the measured digests in the record; `cmd_run` refuses when the approval's `previous_sessions` differ from the record read now |
| D2 | `TREES` stays the seven; the eighth tree is added through `trees_for(k)` and a registry `PREDECESSOR_TREES` keyed by session | s1's design and tests keep asserting seven names; a later session 3 would register s2's facts in the same registry, and until it does `unregistered_predecessors(3)` refuses |
| D3 | H2 is an override of `_on_rollout_start` in `G3Callback` with the alignment test; g2's STALLED branch is dropped as unreachable | the review's minimal fix; the inherited g2 file is untouched; CHECKPOINT_EVERY unchanged; in s1 (start 0) both rules coincide; the e2e digest cannot move (its inputs exclude checkpoints) |
| D4 | H6's "four assertions" include the `num_timesteps` consistency as part of the first | the review's own example (a resume from `ckpt_000614400`'s state would be accepted if the approval named it) is caught only by comparing the state's `num_timesteps` with the final-state counters; the session fields alone would not catch a non-final checkpoint of the same session |
| D5 | H12 is a BYTE comparison of the initial checkpoint's members, decided before the first rollout; a difference is INVALID | the real-model round trip on s1's actual `model.zip` reproduces both members bit for bit after `PPO.load` + `save` (twice), so the check is sound for the real model; the stub's save is a pure function of its state; the check runs at `_on_training_start`, i.e. after P1 / P2 / T0 (about 60,000 ticks) but before any training, so a failure costs no training; this is the review's "one assertion after the initial checkpoint in train" |
| D6 | `verify_run` requires the predecessor's records for a resumed session (the sibling `s<k-1>` by default, or an explicit root) and reports their absence as a problem | the launch tree has the sibling; the unit test passes the root explicitly; a verification that cannot cross-check is not a verification |
| D7 | the session-2 snapshot keeps `logs/m9_g3_prep/**` in its set and adds `logs/m9_g3_s2_prep/**` | provenance: s1's preparation logs are part of what s2 rests on; every s2 preparation log is written before the snapshot (B10), under the new directory |
| D8 | the approval writer takes the authorisation text as a FILE and the date as an argument, both required, nothing hard-coded | the s1 writer quoted the wrong date once (H14); the launch session supplies the user's authorising message verbatim |
| D9 | the real-model test is a hard requirement (it fails when `runs/m9_g3/s1` is absent) and the snapshot round-trip test runs `--session 2` | consistent with the suite's existing gates that hard-fail on missing trees; the k = 2 path is the one the launch uses; `file_set(1)` is checked to be inside `file_set(2)` |
| D10 | `S2_DOC_FILES` includes this record and the pre-launch review, both still being written while this session ran | they are the records s2 rests on; consequence for the launch session: the s2 approval and snapshot are written after the LAST edit of any pinned document (an edit afterwards makes `approval_status` and `snapshot_status` refuse, as designed) |
| D11 | the g3 suite's git-state test and the g1 / g2 git gates are expected to fail on THIS uncommitted tree and are reported as such, not repaired | they read `git diff --name-only HEAD` and `git status --porcelain`: the six modified tracked g3 files and the two staged docs are their input; on the committed tree with nothing staged they pass (the review's H15 item 7; the re-check round's finding) |
| D12 | no new `rl/` file; everything lives in the six existing g3 modules | keeps the g1 identity test's documented count (30 files) and the launch session's Part B unchanged in kind |
| D13 | `verify_run`'s metadata audit skips `launch/` as it already skips `derived/` | found by running the modified verifier on s1's real tree as a regression: it reproduced every s1 result (8 checkpoints, the frontier rebuilt equal to the log with 4 moves / 13 attempts / 29 deferred, NULL and CONTINUE recomputed, 43 of 43 replays exact) and reported three metadata failures on `launch/prep/final/passes.json` and `launch/verify_*.json`, files the s1 launch session copied into the tree AFTER its own `verify-run` (launch record 6.8; the tree's `derived/verify_run.json` says ok because it predates the copies). They are post-run copies of tool logs, not engine records (decision 11 governs what the session writes; the close audit skips nothing but workers / vw / input and runs before any copy). With the skip, `verify-run --session 1` on the archived tree is `ok: true` with 2,436 files / 5,327 JSONL lines audited, exactly the s1 record's numbers; the launch session's own `verify-run --session 2` (run before its copies, as s1's was) is unaffected either way |

## 3. Pre-launch hazard fixes (the decisions record's section-6 format; recorded here because that record is tracked and must not be edited)

| id | hazard found | fix | registered statement it implements |
| --- | --- | --- | --- |
| H2 | s2 could never write a periodic checkpoint: s1 ended mid-rollout at 708,712 = 138 x 5,120 + 2,152, and `num_timesteps % 102,400 == 0` is never true at a rollout boundary 708,712 + 5,120 j (enumerated over 3,072,000 transitions by the review) | `G3Callback._on_rollout_start`: a periodic checkpoint when `(n - start_timesteps) % checkpoint_every == 0` and `n > start_timesteps` (new code only; the inherited g2 callback untouched); s2's periodic checkpoints fall at 811,112, 913,512, ... | decision 12 ("every checkpoint ... is evidence") and the line contract's `checkpoint_every` 102,400 (unchanged value and digest `90eac1a6...`); the alignment is a reading, not a change of the interval |

Every registered digest after the fix: g3 contract `4cd1deaec0f0333b...`, line contract `90eac1a6c6682a39...`, frontier `60e174a61c02e184...`, s1 rule
`dea9965a3989bce5...`, line rule `d9d82885703c016d...`, g2 contract `8dfd44c6...`, g2 line contract `1aadc7a6...`, g1 contract `6958857e...`: unchanged (section 5).

## 4. Incident at the start of this session, disclosed (no s1 evidence is lost; one file needs a one-line restore by the user)

While reading the s1 tools, this session ran `python -B -X utf8 logs/m9_g3_prep/tools/three_passes.py --help` expecting a usage text. That s1 tool has no
argument parser: it ignored `--help` and STARTED the s1 three-pass run, which writes into `logs/m9_g3_prep/final/` (s1's preparation evidence). The run was
stopped after about two minutes, inside the first unit-suite pass, before any pass output was written. The only file it touched is
`logs/m9_g3_prep/final/fingerprint_start.txt`, overwritten with the current fingerprint `f92ca9067813b9e6` (its s1 content was `17dea6d712e624ed`). Verified
afterwards by hashing every file under `logs/m9_g3_prep/` against the byte copy s1 took into its own tree (`runs/m9_g3/s1/launch/prep/`, inside the verified
D: increment) and against the D: source snapshot `2026-10-07_m9_g3_s1`: 51 files compared, exactly one differs (`final/fingerprint_start.txt`); `passes.json`
and every `passN_*.txt` are byte-identical. No process remained; nothing under `runs/` or the D: trees was touched (the preflight's tree checks and D:
coverage in section 5 confirm it).

The restore (a copy of the s1 tree's own byte-identical copy back over the overwritten file) was attempted and refused by this session's permission
classifier as an overwrite; it is left to the user. From the repository root:

```bash
cp -p runs/m9_g3/s1/launch/prep/final/fingerprint_start.txt logs/m9_g3_prep/final/fingerprint_start.txt
```

After it, `sha256sum logs/m9_g3_prep/final/fingerprint_start.txt` must print `0190a900f053d5a1...` (the digest of the s1 copy). Consequences until then: the
s1 source snapshot's `snapshot_status` would report this one file changed (irrelevant: the s1 approval is consumed and `preflight --session 1` refuses anyway
because `runs/m9_g3/s1` exists); the s2 snapshot would copy the wrong 18-byte content. The restore is Part B condition B0 (section 7). The new
`three_passes_s2.py` has an argument parser and a new output directory precisely so that this cannot recur.

## 5. Verification (all offline, `python -B -X utf8`, zero native ticks; logs under `logs/m9_g3_s2_prep/`)

Every check below ran on the FINAL working tree (g3 fingerprint `e30b10a9f453c88a` before and after each; sections 1 and 2 describe its content; the
registered digests are those of section 3). Nothing under `runs/` was written (the preflight's eight-tree check and D: coverage below).

| check | result | log |
| --- | --- | --- |
| g3 unit suite, three consecutive passes, nothing else running, nothing changed in between | **27 / 28, 27 / 28, 27 / 28** (743 s, 852 s, 962 s); the ONLY failure each time is `tracked_files_are_unchanged_except_the_authorised_edit_and_only_new_files_exist`, whose input is this uncommitted tree (the six modified tracked g3 modules and the two staged docs, `git diff --name-only HEAD` = 8 entries); every other test, the ten new or extended ones included, passed three times; fingerprint `e30b10a9f453c88a` before and after every pass | `final_uncommitted/pass{1,2,3}_unit.txt`, `final_uncommitted/passes.json` (verdict `THREE_CONSECUTIVE_PASSES_EXCEPT_THE_GIT_GATE`), `dev/three_passes_uncommitted.py` (the driver: the full suite, every PASS / FAIL line recorded) |
| g3 synthetic e2e, three consecutive passes | **PASS x 3, digest `078f46c445d8adc5` each time** (958 s, 988 s, 997 s): s1 INCONCLUSIVE D = R = 2128, 19 moves, pointer 1,920, 3 BLOCKED_BY_RECHECK; s2 INCONCLUSIVE, 4 BLOCKED_BY_RECHECK at f = 3..6 with needs 80 / 160 / 320 / 320 met at 88 / 162 / 325 / 325; deferred 8 and 137; 7 failed attempts at 1,920 with the frontier live; line CONTINUE at k = 2; 94 replays exact. New facts the e2e now also asserts and prints: s2 resumed at **180,088** transitions (= 35 x 5,120 + 888, not a rollout multiple) and wrote **seven periodic checkpoints at 180,088 + j x 102,400** (282,488 ... 896,888) where the previous rule would have written none (H2); its initial checkpoint carries s1's final members (H12); `previous_sessions` read from s1's records; `verify-run` cross-checked them (H3) and read the tape from `resume.inputs` (H10) | `final_uncommitted/pass{1,2,3}_e2e.txt` |
| an aborted first attempt of the three passes | pass 1 unit **26 / 28**: the git gate and `snapshot_tool_roundtrip`, whose `verify` step found a file changed since the copy: `logs/m9_g3_s2_prep/suites/g1_unit.txt`, which the concurrently running g1 suite was still writing (the session-2 snapshot set includes that directory). Stopped during its e2e; re-run from scratch with nothing else running (the rows above). Lesson carried into B10: nothing may write under `logs/m9_g3_s2_prep/` or `logs/m9_g3_prep/` while the s2 snapshot, the preflight's unit suite or the three passes run | `final_uncommitted_r1_aborted/`, `dev/three_passes_uncommitted_r1_aborted_stdout.txt` |
| the new tests in isolation before the passes | the 8 cheap tests 8 / 8 (6 s; the real-model round trip 6.0 s); the 4 heavy ones 4 / 4 (432 s: the resumed-session test with the H6 refusals and the verify-run cross-checks 96.7 s, the checkpoint alignment 86.9 s, identity(2) with its approval round trip 165.4 s, the eight trees 83.5 s) | `dev/cheap_tests_1.txt`, `dev/heavy_tests_1.txt` |
| g3 rule self-test | PASS, s1 `dea9965a3989bce5`, line `d9d82885703c016d` | section 3 (`dev/helpers_check.txt`) |
| registered digests | g3 contract `4cd1deaec0f0333b394f0ac85bc0f3c494c117e63eacc0caf5e80e0929b8e040`; line contract `90eac1a6c6682a397fc8e85abdf5b1d8ab3f38b75a80ae08709932286d319a31`; frontier `60e174a61c02e1848a25ba7951a5aaf047060a68b9496a8aea82b0d32704b634`; s1 rule `dea9965a3989bce54a27acc0a33d506664789e4a316f1a0b6aaa512ee66c23a9`; line rule `d9d82885703c016d147878886461156da7050176615bfd923ec66cb446cf1998`; g2 `8dfd44c6...` / `1aadc7a6...`; g1 `6958857e...`: all unchanged | |
| g1 evaluation suite | **29 / 29** (69 s) | `suites/g1_eval_unit.txt` |
| g2 suite | **28 / 29** (473 s): only `tracked_files_are_unchanged_and_only_new_files_exist`, `got [the 8 entries of this tree], want []`; 29 / 29 once the tree is committed with nothing staged (the s1 launch's reading) | `suites/g2_unit.txt` |
| g1 unit suite | **61 / 63** (353 s): `identity_names_every_registered_pin` (the documented pre-existing failure, 30 tracked `rl/m9_*.py` files not in g1's list: unchanged in count, no new `rl/` file) and the same git gate; 62 / 63 with only the identity test once committed | `suites/g1_unit.txt` |
| the real-model resume round trip, standalone | s1's `model.zip` `669692023c2d...` (1,110,611 bytes); `saved_counters` = the final-state record (708,712; 1,380; seed 0; Adam 13,800.0 on 12); `resume_ppo` on a `DummyVecEnv` of 4 production-space envs: `num_timesteps` 708,712, `_n_updates` 1,380, `resumed_seed` 1002, `n_steps` 1,280; the re-saved `policy.pth` / `policy.optimizer.pth` members **bit-equal** to `ffce3303...` / `c072b0db...`, stable over a second round trip; the policy tensors equal the member; only the `data` member differs (`_last_obs`, `resumed_seed`), as expected | `dev/real_roundtrip_check.txt` |
| `verify-run --session 1` on the archived s1 tree (a regression of the modified verifier; output outside `runs/`) | first run `ok: false` with three metadata failures under `launch/` (section 2, D13); after D13 **`ok: true`**: metadata 2,436 files / 5,327 JSONL lines / 0 failures (= the s1 results record), 8 checkpoints, the frontier rebuilt equal to the log (pointer 2,220, 4 moves, 13 attempts, 29 deferred), the tape at the registered digests recorded as `tape_reuse`, the rule NULL and the line CONTINUE recomputed, 43 replays exact, no `resume_checks` block (k = 1) | `dev/verify_run_s1_regression.json`, `dev/verify_run_s1_regression_2.json` |
| `preflight --session 2 --skip-unit`, first dry run (before D13) and the final one on the final tree | **refuses for the missing s2 approval plus exactly the git entries of this uncommitted tree** (section 5.1, listed one by one). Everything else passed: the predecessor check (`problems: []`, no unregistered earlier session); the eight trees `ok` with the registered facts (`m9_g3_s1`: 4,935 / 508,166,787 / `d12966c1...`); D: coverage 428,322 source files, 0 uncovered, 13 increments; readiness; the executable, runtime files and frozen configuration at the pins; the reused tape at `81fa52c21078b2c2 / d915fab920554774`, pinned, measured with the executable now; CVars absent; the status table; both lineages; the budget 7,780 s fits; `resume_inputs.expect` = {`669692023c2d...`, `74adedd8...`, `81fa52c2...`} | `dev/preflight_dry_run_1.txt`, `final_preflight/preflight_dry_run.txt` |
| `git diff --check` | clean | |
| new tools | the three Python tools compile; `--help` prints a usage text and runs nothing; the launcher parses (`PowerShell Parser::ParseFile`, 0 errors) | |

Compiled-module note: this session's syntax checks used `python -m py_compile`, which writes `rl/__pycache__/<module>.cpython-313.pyc` regardless of `-B`;
the six g3 modules' `.pyc` files were therefore (re)written under `rl/__pycache__/` (Git-ignored; 163 pre-existing cache files from earlier sessions were
already there, as the review noted). Every suite, dry run and tool invocation ran with `python -B`. Section 8 records whether this session could remove
them; the launch session's preflight checks only its own process's `-B` flag, and the cache files are inert either way.

### 5.1 The final preflight dry run's problems, exactly

`python -B -X utf8 rl/m9_g3_session.py preflight --session 2 --skip-unit`, 2026-10-07T21:25:35Z, exit 1, `ok: false`, 17 problems: the 8 modified or
staged tracked files reported once each as a tracked change and once each as a status entry (16), and the missing approval (1). Nothing else. Readiness
7,007 MB available (>= 4,096), 14,902 MB commit free (>= 10,240), C: 106.4 GiB, D: 1,624.0 GiB; `git_head` `f221a39...`; the only new file
`docs/rl_m9_g3_s2_prep_decisions_2026-10-07.md`.

```
tracked file differs from HEAD and is not an authorised edit: docs/rl_m8_sd1_proposal_2026-10-07.md
tracked file differs from HEAD and is not an authorised edit: docs/rl_m9_g3_s2_prelaunch_review_2026-10-07.md
tracked file differs from HEAD and is not an authorised edit: rl/m9_g3_report.py
tracked file differs from HEAD and is not an authorised edit: rl/m9_g3_run.py
tracked file differs from HEAD and is not an authorised edit: rl/m9_g3_session.py
tracked file differs from HEAD and is not an authorised edit: rl/m9_g3_snapshot.py
tracked file differs from HEAD and is not an authorised edit: rl/m9_g3_tests.py
tracked file differs from HEAD and is not an authorised edit: rl/m9_g3_train.py
git status shows an entry other than a new file or the authorised edit: A  docs/rl_m8_sd1_proposal_2026-10-07.md
git status shows an entry other than a new file or the authorised edit: AM docs/rl_m9_g3_s2_prelaunch_review_2026-10-07.md
git status shows an entry other than a new file or the authorised edit:  M rl/m9_g3_report.py
git status shows an entry other than a new file or the authorised edit:  M rl/m9_g3_run.py
git status shows an entry other than a new file or the authorised edit:  M rl/m9_g3_session.py
git status shows an entry other than a new file or the authorised edit:  M rl/m9_g3_snapshot.py
git status shows an entry other than a new file or the authorised edit:  M rl/m9_g3_tests.py
git status shows an entry other than a new file or the authorised edit:  M rl/m9_g3_train.py
no approval record at docs\rl_m9_g3_s2_approval.json (the session is not authorised)
```

The first dry run (before D13, `dev/preflight_dry_run_1.txt`) listed the same 17; the staged `docs/rl_m8_sd1_proposal_2026-10-07.md` appears because a
staged new file is a tracked change against HEAD (the review's H15 item 7). On the committed tree with nothing staged, only the last line remains (B6).

## 6. Files

| path | state | commit? |
| --- | --- | --- |
| `rl/m9_g3_train.py`, `rl/m9_g3_run.py`, `rl/m9_g3_report.py`, `rl/m9_g3_session.py`, `rl/m9_g3_snapshot.py`, `rl/m9_g3_tests.py` | modified tracked | **yes** (the s2 tooling; B0 of section 7) |
| `docs/rl_m9_g3_s2_prep_decisions_2026-10-07.md` | new (this record) | **yes** (pinned by `identity(2)` and the s2 snapshot) |
| `docs/rl_m9_g3_s2_prelaunch_review_2026-10-07.md` | staged by the user, then modified by its author session | **yes**, in its final form (pinned by `identity(2)`; a staged-but-uncommitted or later-modified file trips every git gate) |
| `docs/rl_m8_sd1_proposal_2026-10-07.md` | staged by the user; not read, not touched | the user's call: committed or unstaged, never left staged (H15 item 7) |
| `logs/m9_g3_s2_prep/tools/{write_s2_approval.py, launch_detached_s2.ps1, wait_session_s2.py, three_passes_s2.py}` | new, Git-ignored | no (in the s2 snapshot's set) |
| `logs/m9_g3_s2_prep/dev/*`, `logs/m9_g3_s2_prep/final/*`, `logs/m9_g3_s2_prep/suites/*` | new, Git-ignored | no (in the s2 snapshot's set) |

## 7. Part B conditions for the launch session (the review's B0 to B12, updated)

All must hold, measured on the COMMITTED tree, before Part C; the launch session edits no tracked file, stages nothing, and writes only new files. The
figures that differ from the review's section 4 are the fingerprint (B0), the test count (B1) and the s2-specific tools and records (B9 to B11); B2 to B5
and B7 are the review's values verbatim and were re-measured today.

| # | condition | what "holds" means |
| --- | --- | --- |
| B0 | the s2 tooling is committed and the tree is clean | the six modified `rl/m9_g3_*.py`, this record and the pre-launch review (its final form) are committed; nothing is staged (a staged new file trips every gate, H15 item 7; `docs/rl_m8_sd1_proposal_2026-10-07.md` committed or unstaged); HEAD = `origin/main` = the remote's `main`; `git status --porcelain --untracked-files=all` empty apart from files the launch session creates (new, M9-named); the g3 source fingerprint of the committed `rl/m9_g3_*.py` is **`e30b10a9f453c88a`** (this session's final value; recompute with the tool's `fingerprint()` and stop if it differs, which would mean an edit after this record); `git diff --check` clean; the overwritten s1 log restored (section 4: `cp -p runs/m9_g3/s1/launch/prep/final/fingerprint_start.txt logs/m9_g3_prep/final/fingerprint_start.txt`, then its sha256 `0190a900f053d5a1...`) BEFORE the s2 snapshot |
| B1 | the suites on that tree | g3 unit suite **28 / 28** three consecutive times with the e2e **PASS, digest `078f46c445d8adc5`** three times and the fingerprint unchanged, by `python -B -X utf8 logs/m9_g3_s2_prep/tools/three_passes_s2.py` (output `logs/m9_g3_s2_prep/final/`; the tool refuses to overwrite), with nothing else running on the machine and nothing writing under `logs/m9_g3_s2_prep/` or `logs/m9_g3_prep/` meanwhile; g3 rule self-test PASS with s1 `dea9965a3989bce5` and line `d9d82885703c016d`; g1 evaluation suite 29 / 29; g2 suite 29 / 29; g1 unit suite 62 / 63 with ONLY `identity_names_every_registered_pin` failing |
| B2 | the registered digests are byte-identical to s1's | g3 contract `4cd1deaec0f0333b394f0ac85bc0f3c494c117e63eacc0caf5e80e0929b8e040`; line contract `90eac1a6c6682a397fc8e85abdf5b1d8ab3f38b75a80ae08709932286d319a31`; frontier `60e174a61c02e1848a25ba7951a5aaf047060a68b9496a8aea82b0d32704b634`; s1 rule `dea9965a3989bce54a27acc0a33d506664789e4a316f1a0b6aaa512ee66c23a9`; line rule `d9d82885703c016d147878886461156da7050176615bfd923ec66cb446cf1998`; `G.PPO` equal to the saved `curriculum_state.ppo`; g2 contract `8dfd44c6...`, g2 line contract `1aadc7a6...`, g1 contract `6958857e...` (all re-measured today, section 5) |
| B3 | the pins | executable `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee` (= `final_state.executable_sha256` = the tape's measuring executable); the runtime files, the frozen configuration, the absent controller-rule CVars, the status table, both lineages (`T_clear` 2,326 words `5eccd4e2d5d77b25`, `T_t` 2,315 words `de1228be4146b720`), the reused tape source at `81fa52c2.../d915fab9...` pinned with its drift records: the review's B3 verbatim (all passed in today's dry runs) |
| B4 | the saved state, byte-identical | `model.zip` `669692023c2dacf838d03c94ae608d227b7598377828e7b4d1d36c7d7f3b5db8` (1,110,611 bytes), members `policy.pth` `ffce330386c8c1335441ac22aa34e38c6f0df2aa8635f0f6a9aec4e71dea32ee`, `policy.optimizer.pth` `c072b0dbf4a3d21e1f2ea1bab3988bbf61f9df4ff53d10fc993b09ff059af7aa`; `curriculum_state.json` `74adedd8004b6e4900e0bcf98f3b92f6ac3ccd69d2673294ca146a9a34668163` (pointer 2,220; f 4 / need 160 / have 133; `line_failed` {2280: 4, 2240: 1, 2220: 4}; `next_episode` 3,735; `attempt_counter` 13; `sessions` [1]; `num_timesteps` 708,712); `input/tape_baseline.json` `81fa52c2...`; `final_state.json` with counters {708,712; 1,380; Adam 13,800.0 x 12}, `next_session_seed` 1002, line CONTINUE, `s2_permitted` true; `line.json` `sessions` = the s1 row of section 1.2; the whole `runs/m9_g3/s1` tree equal to `D:\BattleShip_runs_backup\2026-10-07_incr_m9_g3_s1` (4,935 files, 508,166,787 bytes, manifest `d12966c135fdb614f08fab2d63ff0af894d171834ed9f87c802103b9024307a5`) by the tool (the preflight's eighth tree) AND `powershell -File logs\m9_g3_prep\tools\independent_increment_check.ps1 -Source runs\m9_g3\s1 -Dest D:\BattleShip_runs_backup\2026-10-07_incr_m9_g3_s1` (PASS, 0 missing / 0 extra / 0 bad). `preflight --session 2` and `identity(2)` measure all of this; `predecessor_problems(2)` must be `[]` |
| B5 | the seven earlier trees and D: coverage | rd1 166 / `e81226d7...`, rd2 62 / `6775281e...`, rd3 77 / `b6e13ecb...`, rd4 93 / `7ff2b29d...`, m9_g1 2,740 / `92ba5481...`, m9_g1_eval 1,393 / `ab3e6c61...`, m9_g2_s1 9,779 / `4ad2c3dc...` all `ok` (today: yes); `combined_coverage` 0 uncovered (today: 428,322 files, 13 increments) |
| B6 | the preflight refuses SOLELY for the missing s2 approval | `python -B -X utf8 rl/m9_g3_session.py preflight --session 2 --skip-unit` exits 1 with `problems == ["no approval record at docs\rl_m9_g3_s2_approval.json (the session is not authorised)"]` and nothing else (today's dry runs: that problem plus the 16 git entries of the uncommitted tree, section 5.1; on the committed tree with nothing staged the git entries disappear); `predecessor.problems == []`; readiness passes without closing anything; memory or free-commit refusals are stops |
| B7 | the budget | `budget_projection()` pessimistic 7,780 s = 129.7 min of 8,700 s, slack 920 s (unchanged caps). The close now hashes eight trees instead of seven: s1's close took 88.0 s for seven (about 1.9 GB) under the 300 s cap; the eighth adds about 0.5 GB, i.e. about 25 s |
| B8 | the machine | no `BattleShip.exe` process machine-wide (no replay viewer, no `--check` batch); no uncommitted or staged work; available memory and free commit above the thresholds at the preflight's end (4,096 / 10,240 MB); a quiet machine from the standalone preflight until `runs/m9_g3/s2/session/state.json` exists |
| B9 | the approval | a NEW `docs/rl_m9_g3_s2_approval.json` written by `python -B -X utf8 logs/m9_g3_s2_prep/tools/write_s2_approval.py --snapshot D:/BattleShip_source_snapshots/<date>_m9_g3_s2 --independent "<the tool verify and PowerShell re-hash result>" --authorisation-file <the user's authorising message, verbatim> --authorised-on <its date>` at the final HEAD, AFTER the snapshot (B10) and after the last edit of any pinned document; it carries `session` 2, `resume_inputs` (B4's digests, members, counters, `previous_sessions`, s1's tree facts, `expect`), the eight trees, the 17 D: folders with their digest, the s2 snapshot, the verbatim authorisation with its date and `line_consequence` (B12); `approval_status(2)` returns "approved"; the s1 approval is not reused |
| B10 | the snapshot | `python -B -X utf8 rl/m9_g3_snapshot.py snapshot --dest D:/BattleShip_source_snapshots/<date>_m9_g3_s2 --session 2` PASS (its record says `session: 2` and `log_dirs: [logs/m9_g3_prep, logs/m9_g3_s2_prep]`), then `verify --dest ...` PASS, then the independent PowerShell re-hash (`powershell --dest ... --out <file.ps1>`) PASS; taken AFTER B0's restore and AFTER every s2 preparation log is written (the three passes, the suite logs, the dry run), with nothing writing under `logs/m9_g3_s2_prep/` or `logs/m9_g3_prep/` from then until the session ends |
| B11 | the tools | `powershell -NoProfile -ExecutionPolicy Bypass -File logs\m9_g3_s2_prep\tools\launch_detached_s2.ps1 -Repo <repo>` (refuses when `logs/m9_g3_s2_run/session_*.txt`, `runs/m9_g3/s2` or no approval exists; the session's own full preflight runs first inside `run`); `python -B -X utf8 logs/m9_g3_s2_prep/tools/wait_session_s2.py`; after the run `verify-run --session 2` and `report --session 2` with outputs OUTSIDE the tree, then the copies into `runs/m9_g3/s2/launch/` (as s1), then `rl/tools/runs_backup.py backup --source runs/m9_g3/s2` + `verify --source runs/m9_g3/s2` + `independent_increment_check.ps1 -Source runs\m9_g3\s2 -Dest D:\BattleShip_runs_backup\<date>_incr_m9_g3_s2`; the launch session edits no tracked file and stages nothing |
| B12 | the line consequence acknowledged | written automatically into the approval by the writer (`line_consequence`: END_BUDGET_2128 on a NULL s2; the close audit paired with s1's by identical keys; `s2_permitted` = "the next session is permitted"); the results record repeats it |

## 8. git status at the end

HEAD = `origin/main` = `f221a3929a689c6fcf8452a593192b5abb35c8e5` (= `f221a3929a689c6fcf8452a593192b5abb35c8e5`); no commit, push, branch or pull request; `git diff --check` clean; the six compiled-module cache
files this session's `py_compile` checks wrote under `rl/__pycache__/` were removed (no `.pyc` under `rl/` is newer than the session's start; the 163
pre-existing ones are untouched).

```
A  docs/rl_m8_sd1_proposal_2026-10-07.md
AM docs/rl_m9_g3_s2_prelaunch_review_2026-10-07.md
 M rl/m9_g3_report.py
 M rl/m9_g3_run.py
 M rl/m9_g3_session.py
 M rl/m9_g3_snapshot.py
 M rl/m9_g3_tests.py
 M rl/m9_g3_train.py
?? docs/rl_m9_g3_s2_prep_decisions_2026-10-07.md
```

The `A` / `AM` entries are the user's staging and the review author's later edits (not this session's); the ` M` entries are this session's six g3
modules; the `??` entry is this record. Git-ignored and therefore not shown: `logs/m9_g3_s2_prep/` (the tools, the preparation logs, the three passes,
the suite logs, the dry runs) and the one overwritten byte string under `logs/m9_g3_prep/final/` (section 4). Nothing under `runs/` changed (the eight
trees equal their increments; D: coverage 428,322 files, 0 uncovered).
