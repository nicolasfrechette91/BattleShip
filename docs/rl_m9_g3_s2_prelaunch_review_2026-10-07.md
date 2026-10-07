# M9-g3 session 2 (RESUME path): independent pre-launch review (2026-10-07)

**Status: read-only review; nothing launched, nothing approved, no existing file edited, no commit, no `git add`.** This file is the only
file this review wrote inside the repository (a second new file from another session appeared and was staged while the review ran; section
9). The only things this review ran were pure-Python digest computations and the offline suites (`python -B -X utf8`, no game process;
outputs in the session scratchpad outside the repository, section 8). The reviewer did not write the g3 code and read it fresh.

**Verdict in one line: the resume ENGINE exists and was exercised with the synthetic stub and with a toy SB3 round trip, but there is NO
tooling that can launch s2 from g3-s1's saved state. The g3 CLI refuses `--session 2` by construction and builds no resume configuration;
the approval record has no place for the resume-input digests; every launch tool is hard-wired to s1. One BLOCKER (the missing launch
path, five missing pieces), four MAJOR hazards (no periodic checkpoint can ever be written in s2; the previous-session list is caller-supplied
and unchecked; g3-s1's tree is write-guarded but not hash-verified; uncommitted replay-browser edits or a running viewer trip the preflight),
and a handful of MINOR items. Nothing here is a reason to doubt s1's record.**

| item | value |
| --- | --- |
| checkout | `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, branch `main` |
| HEAD = `origin/main` | `f221a3929a689c6fcf8452a593192b5abb35c8e5` "With the fixed rule, failed tests now delay the next attempt instead of freezing training." |
| `git status --porcelain --untracked-files=all` at the start | empty |
| HEAD move since the s1 launch | `ca3cfb6` -> `f221a39` adds exactly three files: `docs/rl_m9_g3_launch_record_2026-10-07.md`, `docs/rl_m9_g3_s1_approval.json`, `docs/rl_m9_g3_s1_results_2026-10-07.md` (`git diff --stat ca3cfb6 f221a39`: 977 insertions, 0 deletions, nothing under `rl/`) |
| g3 source fingerprint now (sha256 over the sorted `rl/m9_g3_*.py` names and contents, first 16 hex, the computation of `logs/m9_g3_prep/tools/three_passes.py`) | **`f92ca9067813b9e6`** = the value Part B pinned for s1 (unchanged, as the diff implies) |
| read in full | `CLAUDE.md`; `docs/rl_m9_g2_stop_review_2026-10-06.md`; `docs/rl_m9_g3_decisions_2026-10-06.md`; `docs/rl_m9_g3_implementation.md`; `docs/rl_m9_g3_recheck_2026-10-06.md`; `docs/rl_m9_g3_launch_record_2026-10-07.md`; `docs/rl_m9_g3_s1_results_2026-10-07.md`; `docs/rl_m9_g3_s1_approval.json`; all ten `rl/m9_g3_*.py`; the reused `rl/m9_g2_run.py`, `rl/m9_g2_resume.py`, `rl/m9_g2_train.py`, `rl/m9_g2_session.py`, the relevant parts of `rl/m9_g2_frontier.py`, `rl/m8_rd_session.py`, `rl/m9_session.py`, `rl/m7u3_gate.py`, `rl/m7s_gate.py`, `rl/m7_runtime.py`, `rl/m7n_policy.py`; the five tools under `logs/m9_g3_prep/tools/`; `runs/m9_g3/s1/session/{final_state,line,rule,close,state,open}.json`, `training/checkpoints.json`, `training/checkpoints/final/curriculum_state.json`; the replay viewer's write paths (`replay/replay_game.py`, `replay/replay_index.py`); the installed SB3 2.9.0 `load` / `_setup_learn` / `set_random_seed` sources |

## 0. Short answers to the five questions

1. **Does real tooling exist to launch s2 from s1's saved state?** No. The saved state exists, is pinned and verifies today (section 1.3), and
   the engine can consume it (`rl/m9_g3_run.G3Session.open`, the `cfg.resume` branch), but no caller builds that configuration for the real
   game. `rl/m9_g3_session.preflight` refuses any session other than 1 unconditionally (line 224: "only session 1 is prepared by this
   preflight"), `cmd_run` constructs `G3Config` without `resume=` (line 327), the identity and the approval carry no resume-input digests, and
   the four launch tools name s1. Resume was exercised only with the synthetic stub (the unit test
   `synthetic_resumed_session_carries_the_spacing_and_the_line_never_ends_on_attempts` and the two-session e2e, both through the stub's own
   `resume_model` hook, not `resume_ppo`) and with a toy SB3 round trip on a 1-env / 4-env zero environment. **Never exercised:** `resume_ppo`
   on a real trained `model.zip` with the production `TrainVecEnv`; the full s2 path with the real hooks; the construction of
   `previous_sessions` and `expect` from s1's records. The exact missing list is in section 1.4.
2. **Hazards in the resume path:** section 2 (H1 to H15). The headline ones: H2, **s2 can never write a periodic checkpoint** (s1's final count
   708,712 is not a multiple of the rollout, so `num_timesteps % 102,400 == 0` is never true in s2; only `ckpt_000708712` "initial" and `final`
   would exist); H3, the line verdict at k = 2 depends on a `previous_sessions` list the caller must supply by hand, and `verify-run` cannot
   tell a wrong one from a right one; H4, `runs/m9_g3/s1` is write-guarded but is not one of the protected trees, so it is never compared with
   its D: increment at the preflight, the open or the close. The optimizer / scheduler state, the frontier and spacing carry-over, the reused
   tape, the session numbering and the checkpoint naming are sound (details and evidence in section 2).
3. **Machine readiness:** section 3. The thresholds are unchanged (4,096 MB available, 10,240 MB commit free at the preflight; in-session
   system available >= 1,024 MB, commit free >= 2,048 MB, at most 10 BattleShip processes in the session's OWN process tree). Two windows of
   11 to 16 minutes each (the standalone preflight's unit suite and the session's own preflight) are exposed to applications started on the
   machine, which is exactly how the s1 launch was first refused. Replay-browser work: the viewer never writes below `runs/` or next to the
   executable (private runtime directory, verified in code), so it cannot change what the session reads; but a running viewer `BattleShip.exe`
   trips the machine-wide "BattleShip already running" preflight check, and an uncommitted edit to any tracked `replay/*.py` trips every
   git-clean gate.
4. **Part B launch conditions for s2:** section 4, B0 to B12, with the fingerprints, digests and the byte-identity list.
5. **Severity and minimal fix per finding:** section 5 (table). No fix was applied.

## 1. What exists, what was exercised, what is missing

### 1.1 The resume engine (exists; reachable only through a caller-built configuration)

| piece | where | what it does for s2 |
| --- | --- | --- |
| the resumed open | `rl/m9_g3_run.py` lines 82-100 (`G3Session.open`, the `cfg.resume is not None` branch) | `RS.copy_inputs(final_state, root/input, expect)` copies s1's `model.zip`, `curriculum_state.json`, `tape_baseline.json` and refuses unless copy == source == final-state record == `expect`; `RS.check_resume_compat` refuses a changed line contract digest, a changed executable (against `final_state.executable_sha256`), a STALLED flag or any changed PPO value; the g3 override additionally refuses a frontier rule other than `m9_g3_frontier_v1`; `self.carried = cs["carried"]`; the copied table's content digest and `pinned` flag are checked; `open.json` records `resume.{inputs, carried_state, saved_counters, previous_sessions, tape_baseline_sha256}` |
| the inputs and the continuity assertions | `rl/m9_g2_resume.py` (unchanged g2 module) | `copy_inputs` (`dest.mkdir(exist_ok=False)`), `check_resume_compat`, `saved_counters` (reads `data` and the Adam `step` of every parameter from the zip without building a model), `assert_continuity` (num_timesteps, `_n_updates`, `adam_params`, every Adam step), `final_state_record`, `write_final_state` (`overwrite=False`) |
| the model | `rl/m9_g2_train.resume_ppo` (aliased by `rl/m9_g3_train.resume_ppo`; wired as `hooks.resume_model` by `rl/m9_g2_session.real_hooks`, which `rl/m9_g3_session.real_hooks` returns unchanged) | `assert_v3_checkpoint` (stored observation space == v3 Dict), `saved_counters`, `PPO.load(zip, env=vec, device="cpu")`, `n_steps x n_envs == 5,120`, `assert_continuity`, `set_random_seed(1000 + k)`, `model.resumed_seed` |
| the frontier | `rl/m9_g3_frontier.Frontier._restore` over `rl/m9_g2_frontier.Frontier._restore` | refuses another line's state or a STALLED flag; restores `pointer`, `line_failed` (keys converted to `int`), `next_episode`, `attempt_counter`, `moves_all`, `sessions_seen` (union with the new session), `landings`, and g3's `since_failed`; the window, `pending`, `after_trigger`, `session_failed` and `deferred` start fresh (R1) |
| training | `rl/m9_g3_train.train(..., resumed=True)` | `reset_num_timesteps = not resumed` -> `False`; `start_timesteps = model.num_timesteps`; the per-session transition cap is measured from `start_timesteps`; the initial checkpoint is `ckpt_<num_timesteps>` with `why = "initial"` |
| T0 in a resumed session | `rl/m9_g3_run.G3Session.t0` (not g2's skip) | the 5-key drift check runs again on the carried table's own labels (`m9\|g2\|reach\|2128\|0..4`), with the measuring session's native action digests when `cfg.tape_source_records` is given |
| the close | `rl/m9_g3_run.G3Session.finish` | `apply_line(previous_sessions + [this])`; the final-state record for s3 with `next_session_seed = 1000 + k + 1` |
| the records' verification | `rl/m9_g3_report.verify_run` | rebuilds the frontier from `open.json`'s `resume.carried_state` (`replay_history(..., session=k, state=carried)`); recomputes the line rule from s2's own `line.json` |

### 1.2 The CLI, the identity, the approval and the tools (do NOT support s2)

| item | evidence | consequence |
| --- | --- | --- |
| `rl/m9_g3_session.preflight(k)` | line 224-225: `if int(k) != 1: problems.append("only session 1 is prepared by this preflight; a later session needs its predecessor's recorded increment and resume inputs (g2 decision R14)")` | `preflight --session 2` and therefore `run --session 2` are refused whatever else holds (the same text is in the g2 CLI, line 164-165: g2 never had an s2 path either) |
| `rl/m9_g3_session.cmd_run(k)` | lines 327-330: `G3Config(root=..., session=k, ..., tape_reuse=tape_reuse_spec(), tape_source_records=TAPE_RECORDS, open_record=...)`; no `resume=` | even with the refusal removed, s2 would run the s1 branch of `open` (`_reuse_tape` from the g2 source, a fresh policy, pointer 2,300): a second s1 under the name s2 |
| `identity(k)` and `approval_status` | `identity` carries no resume-input digests, no predecessor-tree facts, no `previous_sessions`; `approval_status` (`rl/m8_rd_session.py`) compares every identity key except `code`, `d_records`, `git_head` generically, then `code` per file, `git_head`, and `d_records` over the folders the approval pinned | the g2 R14 sentence "checks every digest against the ones its approval names" has no implementation: nothing in the approval names `669692023c2d...`, `c072b0db...`, `74adedd8...`; `cfg.resume["expect"]` has no source of truth |
| `TREES` | `rl/m9_g3_session.py` line 52: `tuple(S2.TREES) + (("m9_g2_s1", ...),)`, seven trees; the unit test `identity_approval_write_guard_and_the_reused_tape` asserts exactly those seven names | `runs/m9_g3/s1` (4,935 files, 508,166,787 bytes, increment manifest `d12966c135fdb614...`) is in no `trees_state`, `earlier_trees` or preflight check (H4) |
| `write_guard_roots(k)` | computed today for k = 2: every other `runs/` directory, `runs\m9_g3\s1`, `rl`, `docs` | correct for s2 (the session cannot write into s1's tree); reading s1's three input files is allowed |
| `approval_path(k)`, `run_root(k)` | `docs/rl_m9_g3_s2_approval.json` (absent today), `runs/m9_g3/s2` (absent today) | correct |
| `logs/m9_g3_prep/tools/write_approval.py` | `S.APPROVAL` (= `approval_path(1)`), `S.identity()` (= k 1), the s1 approval string and the 2026-10-06 authorisation text; refuses to overwrite | cannot write an s2 approval; the s1 launch already needed a corrected copy for the date (launch record, section 4) |
| `logs/m9_g3_prep/tools/launch_detached.ps1` | `'--session', '1'` hard-coded; throws when `logs/m9_g3_run/session_stdout.txt` or `session_stderr.txt` exists (both exist from s1) | cannot launch s2 as it is |
| `logs/m9_g3_prep/tools/wait_session.py` | `STATE = REPO/runs/m9_g3/s1/session/state.json`, `REC = logs/m9_g3_run/launch_record.txt`, `parents[2]` | would wait on s1's (already done) state and s1's pid |
| `logs/m9_g3_prep/tools/three_passes.py` | writes `logs/m9_g3_prep/final/` (the s1 preparation's three-pass evidence, which is inside the s1 source snapshot's file set and copied to `runs/m9_g3/s1/launch/prep/final/`) | re-running it overwrites s1's preparation logs; the s1 snapshot's `snapshot_status` check would then report changed files (harmless to s1, whose approval is consumed, but it muddies provenance) |
| `logs/m9_g3_prep/tools/independent_increment_check.ps1` | generic (`-Source`, `-Dest`) | usable |
| `rl/m9_g3_snapshot.py` | `EXTRA` and `MODULES` fixed; the file set adds `identity["code"]` and `identity["docs_sha256"]`; `LOG_DIR = logs/m9_g3_prep` whole | usable with a new `--dest`; it does not include the s1 results, launch record or approval (tracked since `f221a39`), which s2's design rests on (MINOR) |

### 1.3 The saved state (exists, pinned, verified today by recomputation)

| file | sha256 (recomputed 2026-10-07 from `runs/m9_g3/s1/`) | equals the record |
| --- | --- | --- |
| `training/checkpoints/final/model.zip` (1,110,611 bytes) | `669692023c2dacf838d03c94ae608d227b7598377828e7b4d1d36c7d7f3b5db8` | `session/final_state.json`, `training/checkpoints.json` `final`, the results record section 9: yes |
| member `policy.pth` (354,623 bytes) | `ffce330386c8c1335441ac22aa34e38c6f0df2aa8635f0f6a9aec4e71dea32ee` | yes |
| member `policy.optimizer.pth` (707,511 bytes) | `c072b0dbf4a3d21e1f2ea1bab3988bbf61f9df4ff53d10fc993b09ff059af7aa` | yes |
| other members | `data` `f9e908cf...`, `pytorch_variables.pth` `98b4d78e...`, `_stable_baselines3_version` `61846436...` (5 bytes), `system_info.txt` `0cbd8994...` | not pinned anywhere (the resume contract pins the two members above; fine) |
| `training/checkpoints/final/curriculum_state.json` | `74adedd8004b6e4900e0bcf98f3b92f6ac3ccd69d2673294ca146a9a34668163` | yes |
| its content | pointer 2,220; `spacing` f 4 / need 160 / have 133 / ok false; `line_failed` {2280: 4, 2240: 1, 2220: 4}; 4 moves; `attempt_counter` 13; `next_episode` 3,735; `sessions` [1]; `frontier` `m9_g3_frontier_v1`; `line_contract_sha256` `90eac1a6...`; `tape_table_sha256` `d915fab9...`; `ppo` equal to `G.PPO` (seed 0, ent_coef 0.01, ...); `num_timesteps` 708,712; `carried` = {frontier, pointer, line_failed, since_failed 133, moves, next_episode, attempt_counter, sessions, landings} | |
| `input/tape_baseline.json` | file `81fa52c21078b2c2...` (content digest `d915fab9205547742e...`) | yes; equals the registered g2-s1 source table |
| `session/final_state.json` | `resume` `m9_g2_resume_v1`, session 1, `executable_sha256` `30a3913b...`, counters {num_timesteps 708,712, n_updates 1,380, seed 0, adam_steps 13,800.0 on parameters 0..11, adam_params 12}, `next_session_seed` 1002, outcome NULL, line CONTINUE with `s2_permitted` true, `spacing_final` as above | |
| `session/line.json` `sessions` | `[{"k": 1, "outcome": "NULL", "D": null, "R": null, "train_fraction": 0.9985, "attempts": 13, "failed_attempts": {"2220": 4, "2240": 1, "2280": 4}}]` | this is the list s2's `previous_sessions` must carry (H3) |
| the tree | 4,935 files, 508,166,787 bytes; D: increment `2026-10-07_incr_m9_g3_s1`, manifest `d12966c135fdb614f08fab2d63ff0af894d171834ed9f87c802103b9024307a5` (tool backup PASS, tool verify PASS, independent re-hash PASS, per the results record) | not re-verified by this review (read-only; the check is the preflight's job once H4 is fixed) |

### 1.4 Exactly what is missing for a real s2 launch

1. **A resume branch in the CLI** (`rl/m9_g3_session.py`): `preflight(k >= 2)` must stop refusing and instead check the predecessor
   (`runs/m9_g3/s<k-1>/session/final_state.json` present, its three input files at their recorded digests, its `line.outcome == CONTINUE`,
   its tree equal to its D: increment); `cmd_run(k >= 2)` must build `G3Config(..., resume={"final_state": <s1 final_state.json>, "expect":
   <the digests the s2 approval names>, "previous_sessions": <s1 line.json sessions>}, tape_source_records=TAPE_RECORDS)` and no
   `tape_reuse` (the engine ignores it when `resume` is set, but passing both invites a wrong-branch reading).
2. **Resume-input pins in the identity and the approval**: `identity(k >= 2)` gains a `resume_inputs` block (model.zip sha256 and bytes, the
   two member digests, curriculum_state sha256, tape_baseline sha256, the predecessor's counters, the predecessor tree's files / bytes /
   manifest, `previous_sessions`), so that `approval_status` (which compares every identity key) pins them and `cmd_run` derives `expect`
   from the approval rather than from the tree it is about to trust.
3. **An eighth protected tree for k >= 2** (`runs/m9_g3/s1` with its registered facts), in `TREES` / `trees_state` / `earlier_trees`, plus the
   unit test that currently asserts seven names.
4. **The checkpoint-cadence fix** (H2), without which s2 produces no periodic checkpoint.
5. **Re-pointed launch tools**: an s2 approval writer (fresh identity(2), the s2 authorisation text and date), `launch_detached.ps1` with
   `--session 2` and a new log directory (the script refuses when s1's session logs exist), `wait_session.py` on `runs/m9_g3/s2/session/state.json`
   and the new launch record, `three_passes.py` with a new output directory.
6. **A test for the real resume path with the real hooks**, as far as it can go without a game: `resume_ppo` on s1's real `model.zip`
   with a `DummyVecEnv` of the production observation / action spaces (bit-equal members after a re-save, `assert_continuity` at 13,800, seed
   1002), and a CLI-level dry run of `preflight --session 2 --skip-unit` that refuses solely for the missing s2 approval.

Every item above is a code or tool change. By the project's own rules it belongs to a preparation session that the user then commits; the
launch session must find a clean tree and edit nothing (section 2, H15).

## 2. Hazards in the resume path

Severity scale: BLOCKER = s2 cannot be launched or its record would be wrong by construction; MAJOR = a defect or a gap that would make the
s2 record weaker than s1's or could end the session for a non-learning reason; MINOR = a provenance, naming or robustness gap with a cheap fix.
Evidence is cited by file and line of the tree at `f221a39`.

### H1 (BLOCKER). No launch path for s2

As section 1.2 and 1.4. Minimal fix: items 1, 2, 3 and 5 of section 1.4 (the resume branch, the approval pins, the eighth tree, the tools),
committed before any launch session.

### H2 (MAJOR). s2 cannot write a periodic checkpoint

`rl/m9_g2_train.py` lines 199-202 (the callback g3 subclasses and does not override here): `n = model.num_timesteps; if n > start_timesteps
and n % every == 0: checkpoint`. In s1, `num_timesteps` at every rollout boundary was a multiple of 5,120 and `every` = 102,400 = 20 rollouts,
hence the seven periodic checkpoints. s1 ended at the training wall cap **mid-rollout**: 708,712 = 138 x 5,120 + 2,152 (the results record:
138 rollouts, 1,380 updates). In s2 the boundaries are 708,712 + 5,120 j, and (708,712 + 5,120 j) mod 102,400 = (94,312 + 5,120 j) mod 102,400
is never 0 (8,088 is not a multiple of 5,120). Checked by enumeration today over 3,072,000 transitions: zero boundaries. s2 would therefore
hold exactly two checkpoints, `ckpt_000708712` (`why = "initial"`, written by `_on_training_start`) and `final`. Decision 12 ("every checkpoint
... is evidence") and the attempt snapshots are unaffected, but the per-102,400 trail that s1 has would be absent from s2, and nothing in the
suites asserts it (the e2e checks resume facts, not the s2 checkpoint count).

Minimal fix: in `rl/m9_g3_train.make_callback_class`, override `_on_rollout_start` in `G3Callback` with the same body as g2's but the test
`(n - self.start_timesteps) % self.every == 0` (new-code-only; the inherited g2 file stays untouched; `CHECKPOINT_EVERY` and the line contract
digest are unchanged, since the value 102,400 is unchanged and only its alignment moves to the session's own start). Record it in the
decisions record's section 6 as a pre-launch hazard fix.

### H3 (MAJOR). The previous-session list is hand-supplied, and a wrong one is self-consistent

`G3Session.finish` (`rl/m9_g3_run.py` lines 325-331) computes the line as `R.apply_line(prev + [this])` with
`prev = cfg.resume["previous_sessions"]`. In the tests `prev` is built in memory from s1's result object; nothing reads
`runs/m9_g3/s1/session/line.json`. If the launch path omitted it (k = 1 again), the s2 close would say CONTINUE where the registered rule
says END_BUDGET_2128; if it carried a wrong `train_fraction` or outcome, k could be miscounted. `verify_run` (`rl/m9_g3_report.py` lines
189-194) recomputes the line from s2's own `line.json` `sessions`, which is `prev + [this]` as recorded, so a wrong `prev` reproduces itself.

Minimal fix: the s2 launch path reads `previous_sessions` from the predecessor's `session/line.json` (`sessions`), asserts it is consistent
with the predecessor's `final_state.json` (`session`, `line.outcome`), pins it in the approval (section 1.4 item 2), and `verify_run` compares
`open.json`'s `resume.previous_sessions` with the predecessor's recorded list (a read of a protected tree).

### H4 (MAJOR). g3-s1's tree is write-guarded but not hash-verified

`write_guard_roots(2)` includes `runs\m9_g3\s1` (verified today), so the s2 process and its workers cannot write there. But `TREES` has the
seven trees of s1's design only; `trees_state`, `earlier_trees`, the preflight, the open and the close never compare `runs/m9_g3/s1` with
`D:\BattleShip_runs_backup\2026-10-07_incr_m9_g3_s1`. What does cover it: `copy_inputs` pins the three input files; `combined_coverage`
(`rl/m7s_gate.py`) requires every file under `runs/` to match a manifest by **size and mtime** (not content), so a same-size in-place
rewrite would pass. For g2-s1 the preparation added the tree explicitly (`G2_S1_FACTS`); g3-s1 needs the same (`files 4935, bytes
508_166_787, increment_manifest_sha256 d12966c1...`).

Minimal fix: section 1.4 item 3; the unit test `identity_approval_write_guard_and_the_reused_tape` (asserts seven names) and
`the_protected_trees_equal_their_increments_and_the_pins_hold` updated for k >= 2.

### H5 (MAJOR, part of H1). The approval does not name the resume inputs

`identity(k)` has no field for them and `cmd_run` has no `expect`. The s1 approval (checked today) has no key containing "resume" or
"input". Minimal fix: section 1.4 item 2.

### H6 (MINOR). The resumed open does not check that the state is the predecessor's final state

`open` accepts any `curriculum_state.json` that carries the g3 frontier rule, the g3 line contract digest and the registered PPO values. It
does not assert `cs["session"] == k - 1`, `cs["sessions"] == [1 .. k-1]`, `final_state["session"] == k - 1`,
`final_state["line"]["s2_permitted"]`, or `cs["tape_table_sha256"] == table["sha256"]`. A resume from, say, `ckpt_000614400`'s state would be
accepted if the approval's `expect` named it. The approval is the guard today. Minimal fix: four assertions in the resumed branch of
`G3Session.open` (new code), tested on the synthetic s1 / s2 pair (the e2e already produces both files).

### H7 (verified sound). Optimizer and scheduler state

| question | answer | evidence |
| --- | --- | --- |
| are the Adam moments and step counts restored? | yes, bit for bit | `PPO.load` restores `policy.optimizer` through `set_parameters`; the unit test `frozen_policy_keyed_on_g3_keys_and_sb3_round_trip` asserts `tensors_equal(model_state(a), model_state(bb)) == []` after a save / load and again after one further update on each side; `assert_continuity` checks `num_timesteps` 708,712, `_n_updates` 1,380 and the step 13,800 on all 12 parameters |
| is there any schedule that depends on progress? | no | `G.PPO`: `learning_rate` 0.0003 and `clip_range` 0.2 are constants; SB3 wraps them as constant schedules; `ent_coef` constant; `_current_progress_remaining` is recomputed against `708,712 + 3,072,000` in s2 (SB3 `_setup_learn`: `total_timesteps += self.num_timesteps` when `reset_num_timesteps=False`) but nothing reads it |
| does the first s2 rollout start from a stale observation? | no | SB3 2.9.0 `load(..., force_reset=True)` (the default) sets `data["_last_obs"] = None` when an env is passed; `_setup_learn` then calls `env.reset()` and sets `_last_episode_starts` to ones. Verified in the installed source today; the round-trip test mirrors it by setting `a._last_obs = None` on the un-reloaded side and obtaining an equal update |
| the per-session transition cap | measured from `start_timesteps` (`_on_step`: `num_timesteps - start_timesteps > transition_cap`) | `rl/m9_g2_train.py` lines 216-221 |
| the seed | `set_random_seed(1002)` after the load: torch, numpy, Python, the action space and the vec env; s1's `seed` 0 stays in `G.PPO` and in the saved `data` (compared by `check_resume_compat`, correctly) | `rl/m9_g2_train.py` lines 159-160; `rl/m9_g2_contract.SESSION_SEED_BASE` 1000 |
| s1 ended mid-rollout | the 2,152 transitions of the unfinished 139th rollout were never used by an update; the saved weights are those after update 1,380; harmless | results record section 3 (138 rollouts, 1,380 updates, 708,712 transitions) |
| residual (reported readings only) | `ep_info_buffer` is not in `_excluded_save_params` and is kept when `reset_num_timesteps=False`, so the first s2 rollout rows' `ep_return_mean_recent` blend s1's last episodes; `model.resumed_seed` is pickled into later saves | SB3 source today; `rl/m9_g2_train.py` line 160 |

### H8 (verified sound). Frontier pointer and replenishment spacing carry-over (f = 4, need 160, have 133)

`Frontier._restore` converts `line_failed` keys to `int` (`rl/m9_g2_frontier.py` line 93), so after the JSON round trip `f()` =
`line_failed[2220]` = 4, `need()` = 160, `since_failed` = 133: s2 needs 27 more counted strip outcomes at 2,220 AND a fresh 8-clear window
(the window restarts at the open, R1; triggers before outcome 160 are logged `deferred_trigger`). The line attempt index continues at a = 5,
the attempt number at n = 14, the episode number at 3,735; `session_failed`, `deferred` and the window are per-session and start at 0 (by
design, R1). Evidence: the unit test `frontier_state_is_carried_across_sessions_with_the_spacing` (33 carried + 48 new = 81 >= 80, five
deferred triggers, a = 4), the stub e2e (f carried across the cap of 320), and `verify_run`, which rebuilds s2's history from
`open.json.resume.carried_state`. One reading to keep in mind: s1's last 79 outcomes at 2,220 ran at 0.65, so an early s2 trigger at 2,220 is
likely and will be deferred until outcome 160; that is the rule working, not a defect.

### H9 (MINOR, by design; document it in the s2 approval). Evaluation keys identical across sessions

`rl/m9_g3_contract.KEYS`: the close audit's sticky labels (`m9|g2|reach|<landing>|<k>`, kept for pairing with the reused tape, R2), the
audit action keys (`m9|g3|auditact|<mode>|<landing>|<k>|<tick>|...`), the tick-0 labels and the drift keys carry **no session component**. So
s2's close audit draws the same sticky masks and the same inverse-CDF uniforms as s1's; with different weights the actions differ, and the two
audits are a paired measurement. This is the registered "one set of keyed draws". It is not a defect; it should be stated in the s2 record so
that nobody reads the pairing as a replay. Keys that must not repeat do not: probe keys include (pointer, a) and a continues over the line;
training, start and artifact keys include the episode number, which continues at 3,735; the verification pick includes (pointer, a). One
viewer-side consequence: audit episode ids (`audit_sticky-2128-00` ...) repeat between the s1 and s2 trees; the replay browser's verdict log
(`replay/_local/verdicts.jsonl`) is keyed by `episode_id`, so its MATCH / DESYNC column cannot tell the two apart without the path.

### H10 (verified sound; one MINOR gap). The reused tape table

s2 copies s1's `input/tape_baseline.json` (`81fa52c2...`, the registered g2-s1 bytes) and checks copy == source == record == `expect`, then
the content digest and `pinned`. The richer s1 checks of `_reuse_tape` (200 / 40 keys, label family, lineage, sticky p, the measuring
executable) are not re-run at the s2 open, but they hold transitively for identical bytes, the preflight's `tape_reuse_problems()` re-checks
the g2 source against the executable now, and `check_resume_compat` refuses a changed executable. The drift check runs again in s2 (5 keys,
caps 240 s / 60,000 ticks) with the g2-s1 native action digests if `tape_source_records` is passed (it must be: section 1.4 item 1). The gap:
s2's `open.json` has no `tape_reuse` record, so `verify_run` skips its "file digest equals the one recorded at the open" check (`if reuse and
...`) and relies on `equals_registered_reuse`. Minimal fix: none required; optionally record the copied table's digests under `resume.inputs`
(already there) and make `verify_run` read either.

### H11 (registered consequence, not a defect). Session numbering k = 2 and the line budget

`apply_line` with `prev` = s1 (NULL, counted: `train_fraction` 0.9985 >= 0.5) and s2:

| s2 outcome | k | line outcome |
| --- | --- | --- |
| NULL (D_2 = none) | 2 | **END_BUDGET_2128** (the line ends) |
| INCONCLUSIVE (D_2 = 2,128) or PASS | 2 | CONTINUE (or END_SUCCESS at D <= 1,473) |
| INCOMPLETE with `train_fraction` >= 0.5 | 2 | END_BUDGET_2128 (it counts, D none) |
| INCOMPLETE with `train_fraction` < 0.5 | 1 | CONTINUE ("the last session does not count"; another session 2 would be proposable) |
| INVALID | - | SUSPENDED |

So s2 is the budget session of the line, by the user's decision 4. Correct in code (`rl/m9_g3_rule.apply_line`, self-tested). Two things to
carry into the s2 approval text: this consequence, and that the output key `s2_permitted` means "the next session is permitted" at any k
(a naming oddity, not a defect). Correct `previous_sessions` (H3) is what makes this table true.

### H12 (verified sound; one MINOR gap). Checkpoint naming and collisions with s1's tree

s2 writes only under `runs/m9_g3/s2/`. Its checkpoint names are `ckpt_000708712` ("initial") and `final` (plus periodic ones once H2 is
fixed: `ckpt_000811112`, `ckpt_000913512`, ...); attempts continue at `a014`; no path collides with s1's, and the D: increment is per tree.
The gap: nothing asserts that s2's initial checkpoint's `policy.pth` and `policy.optimizer.pth` members equal s1's final members
(`ffce3303...`, `c072b0db...`), which is the direct evidence of a bit-exact resume for the real model (the stub e2e asserts it for the stub).
Minimal fix: one assertion after the initial checkpoint in `train` (or in `verify_run` for k >= 2) comparing `members_sha256` of
`ckpt_<start>` with `open.json.resume.inputs` / the predecessor's final-state members.

### H13 (verified sound). The write guard against s1's read-only tree

`w2.WriteGuard.install(write_guard_roots(k))` and `G1.build_real_env(..., protect=write_guard_roots(k))` take the k-aware list; for k = 2 it
contains `runs\m9_g3\s1`. The guard is the same mechanism that protected `runs/m9_g2/s1` in s1 (0 violations recorded). `copy_inputs` reads
s1 (allowed) and writes under `runs/m9_g3/s2/input` (the session's own tree). See H4 for what the guard does not do.

### H14 (process). Approval and snapshot identities after the HEAD move

* The HEAD move `ca3cfb6` -> `f221a39` changed nothing under `rl/` or in the identity's `DOC_FILES`; the fingerprint and every registered
  digest recomputed today equal the s1 approval's (`contract` `4cd1deaec0f0333b...`, `line_contract` `90eac1a6c6682a39...`, `frontier`
  `60e174a61c02e184...`, `s1 rule` `dea9965a3989bce5...`, `line rule` `d9d82885703c016d...`).
* The s1 approval is bound to `session: 1` and `git_head ca3cfb6`; `approval_status` would refuse it for s2 on both. A **new** approval at the
  **final** HEAD is required (after the user commits the tooling of section 1.4; any later commit invalidates it).
* `d_records` now lists 17 folders (the new `2026-10-07_incr_m9_g3_s1`; digest `b13b28886cb15b98...`); `approval_status` re-hashes only the
  folders the approval pinned, so a folder added later is harmless and the s2 approval will pin the 17.
* The snapshot tool's file set includes all of `logs/m9_g3_prep/**`. Write every s2 preparation log (suites, three passes, dry runs) **before**
  the snapshot, or outside that directory; a file changed under it after the snapshot makes `snapshot_status` refuse at the preflight.
  `three_passes.py` writes into `logs/m9_g3_prep/final/`, which overwrites s1's three-pass evidence (preserved in
  `runs/m9_g3/s1/launch/prep/final/` and in the s1 D: snapshot): use a new output directory.
* `SNAPSHOT_DEST_DEFAULT` still names `2026-10-06_m9_g3_s1` (template output only; harmless).
* The s1 approval writer quoted the wrong date once; the s2 writer must quote the s2 authorisation verbatim with its date.

### H15 (process; the lesson of the re-check round). Git-clean gates a launch session can trip

Readers of `git diff --name-only HEAD` / `git status --porcelain`: `m9_g3_session.git_problems` (the preflight and `cmd_run`), the g3 unit
test `tracked_files_are_unchanged_except_the_authorised_edit_and_only_new_files_exist`, the g1 and g2 gates
`tracked_files_are_unchanged_and_only_new_files_exist`, the snapshot's `git_status_rl_docs`, and `snapshot_status` (every snapshotted file
must still equal the repository). Any **modification of a tracked file** by the launch session trips all of them; only **new** files are
tolerated, and under `rl/` or `docs/` a new file must have "m9" / "M9" in its name. Concrete traps for s2:

1. The tooling of section 1.4 is a set of tracked-file edits: it must be made, tested and **committed by the user in a separate preparation
   round**, the g3 fingerprint re-pinned from the committed files, and the five suites re-run on the committed tree, before a launch session
   starts with a clean tree. The launch session itself edits nothing (as s1's did).
2. Recording an amendment inside a tracked record (the decisions record) fails the gates by itself; amendments go to a new file.
3. `docs/rl_m9_g3_s1_results_2026-10-07.md`, the launch record and the s1 approval are tracked since `f221a39`; a correction to any of them
   during the launch session trips the gates.
4. Uncommitted replay-browser work (`replay/*.py` are tracked) trips the gates (section 3).
5. `python -B` always (a `__pycache__` under `rl/` is a write-guard violation by the preflight's own rule; `__pycache__` is git-ignored, so git
   would not show it).
6. Ignored paths that cannot trip git (verified with `git check-ignore`): `logs/`, `/runs/`, `build-*/`, `/replay/_local/`, `__pycache__`.
7. **A staged but uncommitted new file fails the gates** (observed during this review, section 8.1): `git add` of a new file makes
   `git diff --name-only HEAD` list it and `git status --porcelain` show it as `A ` rather than `??`, so `tracked_changes()` and
   `untracked_not_new()` both report it. The g2 gate failed on exactly that while this review's suites were running, because another session
   staged two new `docs/` files mid-chain. A new file passes the gates only while it is untracked (`??`) or once it is committed; the launch
   session must stage nothing, and nothing may be staged by anyone else between Part B and the launch.
8. This review file is M9-named and under `docs/`: untracked or committed it passes every gate; staged it does not (item 7).

## 3. Machine-readiness risks

| item | value | source |
| --- | --- | --- |
| preflight thresholds | available >= 4,096 MB; commit free >= 10,240 MB; >= 5 GiB free on C: and D: | `rl/m8_rd_session.READINESS` |
| in-session caps (a breach = INCOMPLETE) | main process private <= 3,072 MB; process tree private <= 9,216 MB; tree working set <= 4,096 MB; system available >= 1,024 MB; system commit free >= 2,048 MB; <= 10 BattleShip processes, counted **inside the session's own process tree** (descendants of the session pid, `rl/m7u3_gate.tree_snapshot`), two consecutive 5-s samples over the cap needed | `rl/m9_contract.MEMORY_CAPS_MB`, `rl/m9_g2_run.G2Clock.check` |
| s1 measured | main 1,236.9 MB; tree private 6,558.9 MB; working set 2,437.6 MB; lowest system available 5,786.1 MB; lowest commit free 10,047.8 MB; 10 BattleShip processes at peak | results record section 6 |
| the s1 refusal | the first full preflight read 3,011 MB available at 14:44 UTC after `idea64` (2.1 GB) and seven `chrome` processes (2.0 GB) had been started at 14:09-14:14 UTC, during the 20-minute preflight; the authorised re-run read 7,753 MB | launch record 6.3-6.5 |

Risks for s2, in order of likelihood:

1. **The two exposed windows.** `readiness()` runs at the END of `preflight` (after the g3 unit suite, 11 to 16 minutes on this machine), and
   `cmd_run` runs the whole preflight again before the session clock starts (another 11 to 16 minutes). Applications started in either window
   can push available memory under 4,096 MB. Mitigation (procedure, no code): nothing else started on the machine from the standalone
   preflight until `runs/m9_g3/s2/session/state.json` exists; `wait_session.py` shows it.
2. **A running replay viewer trips the preflight.** `ses1.game_processes()` lists `BattleShip.exe` machine-wide (`rl/m7_runtime.list_processes_named`,
   `tasklist`), so a viewer's or a headless `--check` batch's BattleShip process gives "BattleShip already running" (a refusal). At the end of
   the session `wait_until_no_process` (machine-wide, 60 s) would record a viewer process in `leftover_processes.json` (a warning in the record,
   not INVALID). The in-session 10-process cap is tree-local and is not affected.
3. **Memory held by concurrent work.** A windowed viewer (OpenGL window + the frame history), the Tk browser and an index scan hold memory;
   the in-session floor is 1,024 MB available. s1's lowest reading was 5,786 MB on this 16 GB machine with no viewer. A breach is a
   non-learning INCOMPLETE; if `train_fraction` >= 0.5 it still counts as k = 2 (H11).
4. **What concurrent replay-browser work reads and writes.** Verified in `replay/replay_game.py` and `rl/m7_runtime.prepare_worker_runtime`:
   the viewer launches `BattleShip.exe` with `cwd` = a private runtime directory under `replay/_local/sessions/` holding private copies of
   `BattleShip.cfg.json` and `imgui.ini`, so the frozen pins next to the executable (`frozen_sha256` of those two files, and the three runtime
   files) are never written; verdicts, the index (`index.sqlite`) and the viewer state go to `replay/_local/` (git-ignored); "nothing is written
   below runs/". The index scan reads `runs/` (several minutes for ~40k episodes) and will also read s2's tree while it is being written
   (harmless to the session; a partial JSONL line may be skipped by the indexer). `combined_coverage` keys on size and mtime, so a read-only
   scan cannot make a file "uncovered". Conclusion: no file the session reads is changed by replay-browser work; the hazards are the running
   process (item 2), memory (item 3) and git state (item 5).
5. **Uncommitted or staged concurrent work.** `replay/*.py` are tracked; an uncommitted edit makes `git diff --name-only HEAD` non-empty,
   which refuses the preflight (`git_problems`) and fails the g1, g2 and g3 git gates. A **staged** new file does the same (section 2, H15
   item 7; observed during this review). Concurrent work must be committed, stashed or reverted, and nothing staged, from Part B to the launch.
6. **D: coverage must be 0 uncovered.** Today: 428,322 source files, 13 increments, 0 uncovered (results record). Any new or re-written file
   under `runs/` before the s2 preflight (for example a `report` or `verify-run` output saved INTO a tree instead of `logs/`) refuses the
   preflight with "backup prerequisite not met".
7. Disk: the s2 increment will be about 0.5 GB (s1: 508 MB); D: had 1,624.5 GiB free, C: 103 to 106 GiB.

## 4. Part B launch conditions for s2 (precise)

All must hold, measured on the committed tree, before Part C. Items B0 and B1 presuppose that section 1.4's tooling has been written and
committed; until then the first condition fails and nothing else matters.

| # | condition | what "holds" means |
| --- | --- | --- |
| B0 | the s2 tooling is committed and the tree is clean | HEAD = `origin/main` = the remote's `main`; `git status --porcelain --untracked-files=all` empty apart from files the launch session creates (new, M9-named); the committed tree carries: the resume branch of the CLI, the resume-input pins in the identity and approval, the eighth protected tree, the checkpoint-cadence fix (H2), the re-pointed tools; the **new** g3 source fingerprint computed from the committed `rl/m9_g3_*.py` files is written into this condition (today's `f92ca9067813b9e6` is the pre-change value and WILL change); `git diff --check` clean |
| B1 | the suites on that tree | g3 unit suite N / N (25 today; plus whatever tests the tooling adds); g3 rule self-test PASS with s1 `dea9965a3989bce5` and line `d9d82885703c016d`; g3 synthetic e2e PASS with digest `078f46c445d8adc5` (its digest covers outcomes, moves, attempts, the line verdict, the episode count and the deferred counts, so the H2 fix and the eighth tree do not move it; a change of the engine's s2 behaviour would); g1 evaluation suite 29 / 29; g2 suite 29 / 29; g1 unit suite 62 / 63 with ONLY `identity_names_every_registered_pin` failing (the documented pre-existing failure: 30 tracked `rl/m9_*.py` files are not in g1's `CODE_FILES`; a new `rl/m9_*.py` file added by the tooling changes that test's file count, not the 62 / 63). Three consecutive g3 passes with no change in between if the user restores the original wording of condition 1; the amended condition asked for one pass on the committed tree |
| B2 | the registered digests are byte-identical to s1's | g3 contract `4cd1deaec0f0333b394f0ac85bc0f3c494c117e63eacc0caf5e80e0929b8e040`; line contract `90eac1a6c6682a397fc8e85abdf5b1d8ab3f38b75a80ae08709932286d319a31` (a resume REFUSES any other value: `check_resume_compat`); frontier `60e174a61c02e1848a25ba7951a5aaf047060a68b9496a8aea82b0d32704b634`; s1 rule `dea9965a3989bce54a27acc0a33d506664789e4a316f1a0b6aaa512ee66c23a9`; line rule `d9d82885703c016d147878886461156da7050176615bfd923ec66cb446cf1998`; `G.PPO` equal to the saved `curriculum_state.ppo` (seed 0, ent_coef 0.01, lr 0.0003, batch 512, epochs 10, gamma 0.999, lambda 0.995, clip 0.2, vf 0.5, grad 0.5, 1 thread, cpu, rollout 5,120, no normalisation, fresh); g2 contract `8dfd44c6...`, g2 line contract `1aadc7a6...`, g1 contract `6958857e...` |
| B3 | the pins | executable `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee` (= `final_state.executable_sha256` = the tape's measuring executable); runtime files `BattleShip.o2r` `fe2b307e...`, `f3d.o2r` `73ab91ef...`, `gamecontrollerdb.txt` `9d3c6b8d...`; frozen `BattleShip.cfg.json` `1b29d91b...`, `imgui.ini` `0d267321...`; controller-rule CVars absent; the status table digest verified; both lineages re-derived (`T_clear` 2,326 words `5eccd4e2d5d77b25`, `T_t` 2,315 words `de1228be4146b720`); the reused tape source `runs/m9_g2/s1/session/tape_baseline.json` at `81fa52c21078b2c2e5af9239678918099c6fb407608de085c7dd0c46d98196cd` / content `d915fab9205547742e77360ba83f247b7ab304af7a37540ceb9910a2b614a23b`, pinned, with its drift records present |
| B4 | the saved state, byte-identical | `runs/m9_g3/s1/training/checkpoints/final/model.zip` `669692023c2dacf838d03c94ae608d227b7598377828e7b4d1d36c7d7f3b5db8` (1,110,611 bytes) with members `policy.pth` `ffce330386c8c1335441ac22aa34e38c6f0df2aa8635f0f6a9aec4e71dea32ee` and `policy.optimizer.pth` `c072b0dbf4a3d21e1f2ea1bab3988bbf61f9df4ff53d10fc993b09ff059af7aa`; `curriculum_state.json` `74adedd8004b6e4900e0bcf98f3b92f6ac3ccd69d2673294ca146a9a34668163` (pointer 2,220; f 4 / need 160 / have 133; `line_failed` {2280: 4, 2240: 1, 2220: 4}; `next_episode` 3,735; `attempt_counter` 13; `sessions` [1]; frontier `m9_g3_frontier_v1`; line contract `90eac1a6...`; `tape_table_sha256` `d915fab9...`); `input/tape_baseline.json` `81fa52c2...`; `session/final_state.json` with counters {708,712; 1,380; Adam step 13,800.0 on 12 parameters}, `next_session_seed` 1002, line CONTINUE, `s2_permitted` true; `session/line.json` `sessions` = the s1 row of section 1.3; the whole `runs/m9_g3/s1` tree equal to `D:\BattleShip_runs_backup\2026-10-07_incr_m9_g3_s1` (4,935 files, 508,166,787 bytes, manifest `d12966c135fdb614f08fab2d63ff0af894d171834ed9f87c802103b9024307a5`) by the tool AND an independent `Get-FileHash` re-hash |
| B5 | the seven earlier trees and D: coverage | rd1 166 / `e81226d7...`, rd2 62 / `6775281e...`, rd3 77 / `b6e13ecb...`, rd4 93 / `7ff2b29d...`, m9_g1 2,740 / `92ba5481...`, m9_g1_eval 1,393 / `ab3e6c61...`, m9_g2_s1 9,779 / `4ad2c3dc...` all `ok`; `combined_coverage` 0 uncovered (428,322 files, 13 increments as of the s1 close) |
| B6 | the preflight refuses SOLELY for the missing s2 approval | `python -B -X utf8 rl/m9_g3_session.py preflight --session 2 --skip-unit` exits 1 with `problems == ["no approval record at docs\rl_m9_g3_s2_approval.json (the session is not authorised)"]` and nothing else; readiness passes without closing anything; memory or free-commit refusals are stops |
| B7 | the budget | `budget_projection()` pessimistic 7,780 s = 129.7 min of 8,700 s, slack 920 s (unchanged caps: open 60, P1 240, P2 120, T0 240, train 4,800, audit 1,200, verify 600, close 300) |
| B8 | the machine | no `BattleShip.exe` process machine-wide (the replay viewer and any `--check` batch closed); no uncommitted replay work; available memory and free commit above the thresholds at the preflight's end |
| B9 | the approval | a NEW `docs/rl_m9_g3_s2_approval.json` written from `identity(2)` at the final HEAD, `session` 2, naming the resume inputs of B4, the predecessor tree facts, `previous_sessions`, the 17 D: folders with their digest, the s2 source snapshot, and the s2 authorisation text verbatim with its date; `approval_status(2)` returns "approved"; the s1 approval is not reused (session- and HEAD-bound) |
| B10 | the snapshot | a new `D:\BattleShip_source_snapshots\<date>_m9_g3_s2`, PASS, tool verify PASS, independent PowerShell re-hash PASS, taken AFTER every s2 preparation log under `logs/m9_g3_prep/` is written |
| B11 | the tools | a launch script with `--session 2` and a new log directory (the s1 script refuses when `logs/m9_g3_run/session_stdout.txt` exists), a waiter on `runs/m9_g3/s2/session/state.json`, an increment check with `--source runs/m9_g3/s2`; the launch session edits no tracked file |
| B12 | the line consequence acknowledged | the approval text states that s2 is the END_BUDGET_2128 session (H11) and that the close audit is paired with s1's by identical keys (H9) |

What must be byte-identical between the s1 launch and the s2 launch: everything in B2, B3 and B4. What is expected to differ: HEAD, the g3
fingerprint (after the tooling), the identity's `session`, `code` (the edited files), `d_records` (17 folders), `trees` (eight), the approval,
the snapshot, and nothing else.

## 5. Findings, severity, minimal fix (none applied)

| id | finding | severity | minimal fix (for a preparation session; nothing here is authorised) |
| --- | --- | --- | --- |
| H1 | no s2 launch path: the preflight refuses k != 1, `cmd_run` builds no `resume`, the tools are s1-only | **BLOCKER** | section 1.4 items 1, 2, 3, 5 |
| H2 | s2 can never reach a periodic checkpoint boundary (708,712 mod 5,120 = 2,152) | **MAJOR** | override `_on_rollout_start` in `G3Callback` with `(n - start_timesteps) % every == 0` (new code only); record in the decisions record section 6 |
| H3 | `previous_sessions` hand-supplied; a wrong list yields a wrong, self-consistent line verdict at k = 2 | **MAJOR** | read it from `runs/m9_g3/s1/session/line.json`, pin it in the approval, cross-check in `verify_run` |
| H4 | `runs/m9_g3/s1` write-guarded but never hash-verified against its increment | **MAJOR** | eighth `TREES` entry for k >= 2 with facts (4,935 / 508,166,787 / `d12966c1...`); update the two tree tests |
| H5 | the approval has no resume-input digests; `expect` has no source of truth | **MAJOR** (part of H1) | `resume_inputs` in `identity(k >= 2)`; `expect` derived from the approval |
| H15 | tracked-file edits by a launch session (tooling, amendments, replay work) trip every git gate | **MAJOR** (process) | tooling committed in a separate round; amendments to new files; replay work committed or stashed; the launch session edits nothing |
| M1 | a running viewer / `--check` BattleShip process refuses the preflight and is recorded as a leftover at the close | **MAJOR** (process) | close the viewer before Part B and keep it closed until the increment is taken |
| M2 | two 11-16-minute windows exposed to application starts (the s1 refusal) | **MINOR** (process) | a quiet machine until `state.json` exists |
| H6 | the resumed open does not assert the state is the predecessor's final state (session k-1, `s2_permitted`, tape digest equality) | MINOR | four assertions in the resumed branch of `G3Session.open` |
| H9 | audit / tick-0 / drift keys carry no session component (paired by design) | MINOR (document) | a sentence in the s2 approval and results record |
| H10 | s2's `open.json` has no `tape_reuse` record, so one `verify_run` check is skipped | MINOR | `verify_run` reads `resume.inputs` for k >= 2 |
| H12 | no assertion that s2's initial checkpoint members equal s1's final members | MINOR | compare `ckpt_<start>` members with the final-state members in `train` or `verify_run` |
| H14 | the snapshot file set includes `logs/m9_g3_prep/**`; `three_passes.py` overwrites s1's pass logs; `SNAPSHOT_DEST_DEFAULT` is s1's | MINOR | new output directories; logs before the snapshot |
| S1 | the snapshot's `EXTRA` names neither the s1 results, the launch record nor the s1 approval, which s2 rests on | MINOR | add them to `EXTRA` / `DOC_FILES` for k >= 2 |
| N1 | the line output key `s2_permitted` means "next session permitted" at any k | MINOR (naming) | none required; mention in the record |

Not a finding (verified sound): the optimizer and scheduler state (H7), the frontier and spacing carry-over (H8), the reused tape path
(H10 main), the session numbering and seed (H11), the checkpoint naming (H12 main), the write guard (H13), the registered digests after the
HEAD move (H14 main).

## 6. What this review did not do

* No native process, no preflight, no training, no approval, no snapshot, no backup, no increment verification (the s1 tree's equality with
  its increment is taken from the results record; the preflight re-checks it once H4 is fixed).
* It did not load s1's `model.zip` into SB3 (a torch load is not a unit test); the counters are read from `final_state.json`, which s1 wrote
  from `saved_counters` at the close.
* It did not run the five suites by hand for the Part B evidence of a future tree; it ran them once on today's tree (section 8) only to
  confirm the baseline the launch record reports.

## 7. Suggested order (for the user's decision; nothing started)

1. A zero-tick preparation session implements section 1.4 (and H6, H12 if wanted), extends the tests (the eighth tree; the real-model
   `resume_ppo` round trip; the s2 checkpoint count on the stub), runs the five suites and the e2e three times, records the new fingerprint and
   a decisions amendment **in a new file**, and stops with the tree dirty for the user to commit.
2. The user commits and pushes; HEAD = origin/main.
3. A launch session re-runs Part B (section 4, B0 to B12) on the committed tree with a quiet machine and no viewer, writes the s2 snapshot and
   approval as new files, runs the full preflight once, launches once, waits, takes the increment, writes the results record, and edits
   nothing.

## 8. Measured today (read-only)

| what | result |
| --- | --- |
| HEAD, origin/main, remote | `f221a39` = `f221a39`; remotes `origin` = `nicolasfrechette91/BattleShip`, `upstream` = `JRickey/BattleShip` (reference only) |
| tree at the start | clean |
| g3 fingerprint | `f92ca9067813b9e6` (working-tree bytes; `rl/m9_g3_tests.py` and `rl/m9_eval_tests.py` are `w/crlf`, the rest `w/lf`, `core.autocrlf = true`: the fingerprint is defined over working-tree bytes, as `three_passes.py` computes it) |
| registered digests (pure modules, `python -B`) | contract `4cd1deae...`, line contract `90eac1a6...`, frontier `60e174a6...`, s1 rule `dea9965a...`, line rule `d9d82885...`: all equal to s1's approval and `open.json` |
| saved-state digests | as section 1.3, recomputed from the files |
| `write_guard_roots(2)` | includes `runs\m9_g3\s1`, every other `runs/` directory, `rl`, `docs` |
| `approval_path(2)`, `run_root(2)` | both absent |
| D: records | 17 folders, digest `b13b28886cb15b98...` (s1's approval pinned 16 at `68b793802bbc0fda...`) |
| s2 periodic checkpoint boundaries | none in 3,072,000 transitions from 708,712 (enumeration) |
| ignored paths | `logs/`, `/runs/`, `build-*/`, `/replay/_local/`, `__pycache__` (`git check-ignore -v`) |
| suites on `f221a39` (offline, `python -B -X utf8`, outputs in the session scratchpad, nothing under the repository) | see 8.1 |

### 8.1 The suites on today's tree

Run once, sequentially, from the repository root (`python -B -X utf8 <suite>`), 18:22:02 to 19:15:22 UTC, outputs in the session
scratchpad (`.../scratchpad/suites/`), nothing written under the repository (no `__pycache__` newer than this review; the g3 suite's
temporary directories live under `%TEMP%\m9g3t_*` and two were left behind by its best-effort cleanup, outside the repository). The g3
fingerprint was `f92ca9067813b9e6` before and after. `git status --porcelain --untracked-files=all` was **empty when the chain started**.

| suite | result | wall | note |
| --- | --- | ---: | --- |
| g3 unit (`rl/m9_g3_tests.py unit`) | **25 / 25** | 936 s | its git-state test passed at about 18:28 UTC, before the staging below |
| g3 rule self-test | **PASS**, s1 `dea9965a3989bce5`, line `d9d82885703c016d` | < 1 s | |
| g3 synthetic e2e (`rl/m9_g3_tests.py e2e`) | **PASS, digest `078f46c445d8adc5`** (= the pinned value): s1 INCONCLUSIVE D = R = 2128, 19 moves, pointer 1,920, 3 BLOCKED_BY_RECHECK; s2 INCONCLUSIVE, 4 BLOCKED_BY_RECHECK; deferred 8 and 137; 7 failed attempts at the blocked pointer with the frontier live; line CONTINUE; no problems | 1,108 s | |
| g1 evaluation (`rl/m9_eval_tests.py unit`) | **29 / 29** | 82 s | |
| g2 (`rl/m9_g2_tests.py unit`) | **28 / 29**: only `tracked_files_are_unchanged_and_only_new_files_exist` failed, `got ['docs/rl_m8_sd1_proposal_2026-10-07.md', 'docs/rl_m9_g3_s2_prelaunch_review_2026-10-07.md'], want []` | 663 s | **not a code failure**: while the chain ran, another session created `docs/rl_m8_sd1_proposal_2026-10-07.md` (file mtime 18:38 UTC) and staged both new files (`.git/index` mtime 18:57 UTC); a staged new file makes `git diff --name-only HEAD` non-empty (H15 item 7). On the tree the chain started with, this gate passes (as it did for the s1 launch) |
| g1 unit (`rl/m9_tests.py unit`) | **61 / 63**: `identity_names_every_registered_pin` (the documented pre-existing failure, 30 files) and the same git gate on the same two staged files | 410 s | the registered Part B expectation is 62 / 63 with the identity test alone; the second failure has the cause above and would not occur on a clean or committed tree |

Reading: on the committed tree `f221a39` the suites reproduce the s1 launch record's results exactly (25 / 25, PASS `078f46c445d8adc5`,
29 / 29, 29 / 29, 62 / 63), with the one measured deviation fully explained by concurrent staging, which is itself the clearest possible
demonstration of hazard H15 and of section 3 item 5: a launch session's Part B is only as good as the quietness of the tree while it runs.

## 9. git status at the end (19:17 UTC)

```
A  docs/rl_m8_sd1_proposal_2026-10-07.md
AM docs/rl_m9_g3_s2_prelaunch_review_2026-10-07.md
 M rl/m9_g3_run.py
 M rl/m9_g3_train.py
```

HEAD = `origin/main` = `f221a39`. The two `rl/` modifications are **not this review's** (file mtimes 19:16:37 UTC, after this review's last
read of either file; section 9.1). With them the working-tree g3 fingerprint is `4e5a185cde9dbbab` (the committed tree's is still
`f92ca9067813b9e6`), and the preflight would now refuse with "tracked file differs from HEAD and is not an authorised edit" until they are
committed: expected during a preparation round, and exactly the B0 ordering of section 4. The two `docs/` entries:

* `docs/rl_m9_g3_s2_prelaunch_review_2026-10-07.md`: this review, the only file this session wrote inside the repository. It was
  **staged by another session** at about 18:57 UTC (this review ran no `git add`); the `M` is this session's later edits to its own file,
  so the index holds an earlier draft and the working tree the final text.
* `docs/rl_m8_sd1_proposal_2026-10-07.md`: not this session's; created at about 18:38 UTC and staged at the same time as the review.
  Not read, not touched.

Ignored entries (`--ignored`): `rl/__pycache__/`, `rl/tools/__pycache__/`, both pre-existing (newest file 2026-10-02). Nothing under
`runs/`, `logs/` or `replay/_local/` was written by this review.

### 9.1 Concurrent edits observed at the close (read, not reviewed in depth, not touched)

`git diff` at 19:16 UTC shows another session implementing three items of this review in `rl/m9_g3_run.py` (+45 / -3) and
`rl/m9_g3_train.py` (+43 / -4): H6 as `predecessor_assertions` (session k-1, sessions 1..k-1, the final checkpoint's `num_timesteps`, the
line permitting a next session, the tape digest, the copied members); H2 as a `G3Callback._on_rollout_start` override aligning periodic
checkpoints to `start_timesteps` (the attempt hook copied from g2 unchanged); H12 as an `expect_initial_members` check in `train`'s `save`,
raising `IntegrityStop` when the initial checkpoint's `policy.pth` / `policy.optimizer.pth` sha256 differ from the predecessor's final
members. Three observations for whoever commits them (nothing here was verified by running anything):

1. **The H12 check compares bytes after a load / save round trip, which no existing test does.** The unit test
   `frozen_policy_keyed_on_g3_keys_and_sb3_round_trip` asserts tensor equality (`tensors_equal`), not member-byte equality. A benign
   serialization difference (torch 2.14 `save` of a reloaded optimizer state) would end s2 **INVALID at its first checkpoint, after P1 / P2 / T0
   have consumed about 60,000 ticks, and an INVALID session SUSPENDS the line** (`m9_g3_line_rule_v1`). Before this check is relied on, an
   offline test should `PPO.load` s1's real `model.zip` (`669692023c2d...`), `save` it, and compare the member digests with `ffce3303...` /
   `c072b0db...` (a torch load, no game). If the bytes differ, the check should compare tensors instead, or be reported rather than deciding.
2. The H2 override reproduces g2's attempt hook verbatim and drops only the unreachable STALLED branch: consistent with section 5. The
   `contract_description` of the train module gains a `checkpoint_alignment` entry; that description is not part of the line contract digest
   (`line_contract_description` names `checkpoint_every` only), so B2 is unaffected, but B0's fingerprint changes as expected.
3. The `predecessor_assertions` are satisfied by s1's records as read today (session 1, sessions [1], `num_timesteps` 708,712 in both,
   line CONTINUE with `s2_permitted` true, tape digest `d915fab9...` in both, members equal); the synthetic e2e exercises the same path and
   should be re-run on the committed tree (B1) together with the unit suite, three times if the original condition 1 wording is kept.
