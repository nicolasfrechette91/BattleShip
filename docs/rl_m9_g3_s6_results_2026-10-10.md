# M9-g3-s6 results (2026-10-10)

**Registered outcome: NULL** (`m9_g3_s1_rule_v1`, the per-session rule, sha256 `dea9965a3989bce5...`): **D_6 = none**, **R_6 = none**. The frozen final
policy cleared **1 of 20** sticky episodes from the landing state 2,128 (1 clear, 10 falls, 9 horizon), **0 of 20** from 1,966 (14 falls, 6 horizon) and
**2 of 20** from 1,694 (2 clears, 7 falls, 11 horizon); every claimed clear verified. The D chain fails at its first link (2,128: 1 < 10), so D = none and
R = none. The rule's reason string, as recorded: "D_1 = none: not even 10 of 20 at 2,128" (the rule text names the per-session subscript 1; this is
session 6's own result). **Line outcome: END_BUDGET_1694** (`m9_g3_line_rule_v1`, `d9d82885703c016d...`): k = 6, counted sessions [1, 2, 3, 4, 5, 6],
depths [none, 2,128, 2,128, 1,966, 1,694, none], reason "k = 6 and D_6 = None is later than 1694", next session NOT permitted. **The g3 line has ended.**
This is the row the approval's computed `line_consequence` registered for "NULL (D none)" before the run (END_BUDGET_1694), and the consequence the user's
authorisation acknowledged. Nothing follows automatically: **no s7 was run or authorised, and the line rule permits none.** One session, one run, once;
nothing was retried, extended or repaired. Every number below is read from `runs/m9_g3/s6/` and recomputed by `verify-run` (section 8).

Scope label: *M9-g3-s6: the sixth session of the g3 line, RESUMED bit for bit from g3-s5's recorded final state (model, optimizer, frontier pointer 1,780 and
spacing f 0 / need 0 / have 4, episode and attempt counters), under the unchanged replenishing controlled frontier rule `m9_g3_frontier_v1`, the same recipe
(observation v3, reward v2, sticky p = 0.25, entropy 0.01, 80 minutes or 3,072,000 transitions, 4 + 6 slots), the reused g2-s1 tape baseline by digest, and
the same keyed audit draws as s1-s5 (a paired measurement, not a replay); progress measured as D and R at landing states under the registered rules; no
claim of a tick-0 policy.*

**The date.** The user's rule for this unattended session: one date for everything dated, the local date when Part B started. Part B started on
2026-10-10 at 16:09:33 EDT (B0 at 16:10:02 EDT), so the snapshot, the approval's `authorised_on`, the increment and this record carry **2026-10-10**. Some
UTC timestamps below fall on 2026-10-11 (the session ran 23:24Z-01:23Z); the local session never crossed midnight.

## 1. What was run

| item | value |
| --- | --- |
| tree | HEAD = origin/main = remote `main` = `1d975efd1a5db8204be331c88851262df6fd3a7e` ("Add the results of the fifth training session", carrying the s5 approval `1e594fcb...` and the s5 results record `69aef4c8...`); no tracked file modified at any point; nothing staged; g3 source fingerprint **`15ddbb84932aa658`** |
| authorisation | the user's unattended-session message of 2026-10-10, Part C, quoted verbatim in the approval (`authorised_on` 2026-10-10; `logs/m9_g3_s6_prep/launch_2026-10-10/s6_authorisation_part_c_2026-10-10.txt`, sha256 `7b0a48b7...`, 25 lines; the approval's text equals the file line for line), including "Acknowledged line consequence: this is the END_BUDGET_1694 session. D₆ = 1,694 continues the line. D₆ ≤ 1,473 ends it with END_SUCCESS. A NULL result, D₆ = 2,128, D₆ = 1,966, or an INCOMPLETE run that counts ends the line." |
| source snapshot | `D:\BattleShip_source_snapshots\2026-10-10_m9_g3_s6` (`--session 6`; `log_dirs` [logs/m9_g3_prep, logs/m9_g3_s2_prep, logs/m9_g3_resume_tools, logs/m9_g3_resume_k_prep, logs/m9_g3_s6_prep]); 18:35:47-18:40:31 EDT; PASS, 381 files, 4,180,687 bytes, 283.5 s, `snapshot.json` sha256 **`da753331336f70c4c59447a6523351c3c687c4de915813974dfa059ae9325434`**; tool verify PASS (22:40:32Z: 381 files, 0 mismatches, 0 extra, 0 external mismatches, executable equal); independent PowerShell re-hash checked 382, bad 0, exe equal, PASS |
| approval | NEW `docs/rl_m9_g3_s6_approval.json`, sha256 **`f639e14146fe64933c36f272fb9edf973c918ad3cf57dd63cc780a16723c78b4`**, written 18:40:47-18:46:52 EDT by `logs/m9_g3_resume_tools/write_approval.py --session 6` (unchanged, sha256 `e652f04e...`) from `identity(6)` at the final HEAD: session 6; the twelve trees; the D: folders; `resume_inputs` (expect {`382dde88...`, `147467ca...`, `81fa52c2...`}, members `f3e0dc32...` / `e3a78f5b...`, counters 7,726,976 / 15,070 / Adam 150,700 x 12, `previous_sessions` = the s1-s5 rows read from s5's `line.json` and cross-checked along the chain s1 -> s2 -> s3 -> s4 -> s5, s5's tree facts 4,302 / 504,067,346 / `2e632bbf...` discovered from its increment); the snapshot above; the COMPUTED `line_consequence` (B12); the authorisation text verbatim; `approval_status(6)` = (True, "approved") |
| full preflight (once) | `python -B -X utf8 rl/m9_g3_session.py preflight --session 6`, 18:57:41-19:23:50 EDT, **exit 0, `ok: true`, `problems: []`**: unit 29 / 29 (1,026 s), rule self-test PASS, approval "approved", snapshot "recorded, PASS and equal to the repository", twelve trees ok, coverage 444,367 / 0 uncovered, predecessor problems [] and unregistered [], readiness 7,174.2 MB available / 18,558.8 MB commit free; the only new file the approval |
| launch | `powershell -NoProfile -ExecutionPolicy Bypass -File logs/m9_g3_resume_tools/launch_detached.ps1 -Session 6 -Repo ...` (sha256 `53f675ad...`) from Git Bash: **pid 18696 at 2026-10-10T23:24:12Z** (19:24:12 EDT), `python -B -u -X utf8 rl/m9_g3_session.py run --session 6`; its own preflight ran first (unit 29 / 29 in 1,012 s; readiness 7,947.8 MB / 18,643.4 MB); the session clock started 23:54:39Z (19:54:39 EDT); the process exited by itself (state `done` at 01:23:33Z, 21:23:33 EDT); `session_stderr.txt` empty; waited with `wait_session.py --session 6` (done, exit 0, 119.5 min) |
| session clock | **5,333.9 s (88.9 min)** of the 8,700 s cap |
| executable | `build-us/Release/BattleShip.exe` `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee`, unchanged at the close; runtime files and frozen configuration equal their pins |

## 2. Part B (B0-B13), all held before any native tick

Logs: `logs/m9_g3_s6_prep/launch_2026-10-10/` (inside the s6 snapshot's file set; `partb_summary.md` there holds every step's local start and end time),
`logs/m9_g3_s6_prep/final/` (the three passes). Conditions: `docs/rl_m9_g3_resume_k_prep_decisions_2026-10-08.md` section 8 for k = 6, with the values of
`docs/rl_m9_g3_progression_fix_2026-10-08.md` section 10 and of the user's message. No preparation round (B13). Part B ran 16:09:33-18:34:31 EDT.

| # | result (local EDT times) |
| --- | --- |
| B0 | 16:10:02-16:10:04 (2 s): HEAD = origin/main = `git ls-remote origin refs/heads/main` = `1d975ef` (carrying the s5 approval and results record); `git status --porcelain --untracked-files=all` empty; nothing staged; `git diff --check` clean; fingerprint `15ddbb84932aa658` (per-file digests equal the progression-fix record; all ten g3 modules `i/lf w/lf`) |
| B1 | `three_passes.py --session 6` WITHOUT `--allow-git-gate`, 16:10:36-17:58:19 (107.7 min): **THREE_CONSECUTIVE_PASSES**, exit 0; unit **29 / 29** x 3 (pass 1 16:10:41-16:34:32, 1,431.0 s; pass 2 16:51:44-17:13:23, 1,299.0 s; pass 3 17:28:25-17:43:23, 898.3 s), e2e PASS digest **`078f46c445d8adc5`** x 3 (16:34:32-16:51:44, 1,031.8 s; 17:13:23-17:28:25, 902.2 s; 17:43:23-17:58:19, 896.1 s), fingerprint unchanged before and after every pass; then, one after another (17:58:49-18:12:38): rule self-test PASS (s1 `dea9965a3989bce5`, line `d9d82885703c016d`; 17:58:49-17:58:50); g1 evaluation 29 / 29 (17:58:50-17:59:55); g2 29 / 29 (17:59:55-18:07:13); g1 unit 62 / 63 with ONLY `identity_names_every_registered_pin` failing (18:07:13-18:12:38; its FAIL line identical to s5's apart from the timing); fingerprint after the suites unchanged; git status empty at the suites' start and end. No `node` or Playwright process at any time (section 7), so the sequence never had to restart |
| B2 | 18:13:03-18:13:04: g3 contract `4cd1deae...`, line contract `90eac1a6...`, frontier `60e174a6...`, s1 rule `dea9965a...`, line rule `d9d82885...`, g2 `8dfd44c6a8b7e319` / `1aadc7a6b2ff85bd`, g1 `6958857ed2dfd1c5`: all equal; `G.PPO` = s5's saved `curriculum_state.ppo` |
| B3 | (dry run 18:13:21-18:24:37) executable `30a3913b...` (= s5's `final_state.executable_sha256`); pins; tape `81fa52c21078b2c2 / d915fab920554774` pinned, measured with the executable now; CVars absent or zero; status table verified; `T_clear` 2,326 / `5eccd4e2d5d77b25`, `T_t` 2,315 / `de1228be4146b720` |
| B4 | 18:13:03-18:13:04 (digests), 18:13:21-18:24:37 (tool), 18:25:03-18:29:19 and 18:33:57-18:34:31 (s5's independent re-hash, twice): s5's saved state byte-identical to its records: `model.zip` `382dde88...` (1,111,718 B), members `f3e0dc32...` / `e3a78f5b...` (recorded = now); `curriculum_state.json` `147467ca...` (14,948 B; pointer 1,780; f 0 / need 0 / have 4; sessions [1, 2, 3, 4, 5]; num_timesteps 7,726,976; next_episode 17,100; attempt_counter 67); tape `81fa52c2...`; `final_state.json` `5849fbd3...` (session 5; counters 7,726,976 / 15,070 / Adam 150,700 x 12; next seed 1006; line CONTINUE); `line.json` `7f2387a8...` rows = s1 .. s5 (rows 1-4 equal s4's `line.json`); `rule.json` `5a029aa5...` PASS 1,694 / 1,694; `predecessor_problems(6)` = []; `unregistered_predecessors(6)` = []; chain `sessions_checked` 5, no problem; `predecessor_doc_problems(6)` = [] (the s1-s5 approvals and results records found by the exact rule); `runs/m9_g3/s5` = its increment `2026-10-09_incr_m9_g3_s5` (manifest `2e632bbf...`, discovered, exactly one folder, no record problem) by the tool (twelfth tree ok) AND the independent re-hash (4,302 checked, 0 missing / 0 extra / 0 bad) |
| B5 | the twelve trees of `trees_for(6)` ok with the registered or discovered facts (tool, dry run) and PASS by the independent re-hash, twice (per-tree times in `partb_summary.md`; rd1 166, rd2 62, rd3 77, rd4 93, m9_g1 2,740, m9_g1_eval 1,393, m9_g2_s1 9,779, m9_g3_s1 4,935, m9_g3_s2 4,478, m9_g3_s3 3,779, m9_g3_s4 3,486, m9_g3_s5 4,302; 0 / 0 / 0 each); coverage 444,367 files, 0 uncovered, 17 increments |
| B6 | `preflight --session 6 --skip-unit` (18:13:21-18:24:37, 11.3 min): exit 1 with exactly `["no approval record at docs\rl_m9_g3_s6_approval.json (the session is not authorised)"]`; stderr empty; readiness passed (7,945.5 MB / 18,566.9 MB; C: 99.7 GiB, D: 1,639.1 GiB) without closing anything |
| B7 | pessimistic 7,780 s of 8,700 s (fits); the close projected 639.0 s over twelve trees (4,244,808,110 B), not clock-enforced; pessimistic total with that close 8,119.0 s, fits |
| B8 | 18:13:21 and 18:29:35 (and 19:24:06 before the launch): no `BattleShip.exe` anywhere; no tracked, staged or replay-browser change (`replay/_local` untouched since 2026-10-03); readiness above the thresholds at every reading; no `node` or Playwright process and no process >= 1,000 MB at any Part B sample; every other Claude session idle, last activity before Part B (section 7) |
| B9 / B10 | section 1 (snapshot first, then the approval; every Part B log written before the snapshot; nothing written under any directory of the snapshot set afterwards; later logs in `logs/m9_g3_s6_run/`) |
| B11 | the four generic tools as found (sha256 unchanged since s5); `independent_increment_check.ps1` `98abb0b9...`; `logs/m9_g3_s6_run`, `runs/m9_g3/s6`, the s6 approval, any `rl_m9_g3_s6` docs entry, the s6 snapshot and any s6 increment absent before Part C |
| B12 | `line_consequence(6, [s1 .. s5])` computed into the approval: NULL -> END_BUDGET_1694; D 2,128 -> END_BUDGET_1694; D 1,966 -> END_BUDGET_1694; **D 1,694 -> CONTINUE**; D 1,473 / 1,369 / 1,248 -> END_SUCCESS; INCOMPLETE counting -> END_BUDGET_1694; INCOMPLETE not counting -> CONTINUE; INVALID -> SUSPENDED; END_CAP at k = 8 (k = 6 within the cap). Equal to the consequence the user's message states; the two extra rows are the rule's own and do not contradict it |
| B13 | k = 6: s5 DISCOVERED from exactly one increment `2026-10-09_incr_m9_g3_s5` (PASS record naming `runs/m9_g3/s5`, manifest at the recorded digest); s3, s4 discovered likewise; s1, s2 registered; `unregistered_predecessors(6)` = [] |

**The s5 failure records (checked read-only before Part C, 16:11-16:14 EDT).** `runs/m9_g3/s5/session/failures/` holds exactly the two `no_episode` records
the s5 record reports; no other lifecycle failure exists in s5. `step_x_w05` (07:30:49Z) belongs to attempt 51's RE-CHECK run at landing 1,966: that test was
decided `passed` by its 10th clear (probe-1940-1-1966-15, slot 6, recorded 07:30:49Z); its `_cancel` closed probe-1940-1-1966-17 (active, 193 policy ticks;
1,966 + 193 = 2,159 = the preserved tail's last input tick); the step queued for that episode in the same polled batch was sent after the `close` and refused
before any native call (the run's `sent.step` = policy ticks + 1, `late_steps` 0). `step_x_w01` (08:18:48Z) belongs to attempt 66's re-check run at 1,966:
decided `failed` by its 11th non-clear (probe-1800-5-1966-13, slot 7, 08:18:48Z), fail fast cancelled 2,128 (9 / 5) and closed probe-1800-5-1966-15 (143
ticks; 1,966 + 143 = 2,109 = the tail's last input tick); its queued step reached worker 1 after the close (`sent.step` = policy ticks + 1; the two late steps
belong to the two closed 2,128 episodes). In both, the decision and the slot close came BEFORE the queued step reached the worker; no native tick ran for it;
no re-check score, move / block decision or registered measure was affected (`logs/m9_g3_s6_prep/launch_2026-10-10/s5_failure_record_check.md`).

## 3. Phases

| phase | wall (cap) | native ticks (cap) | result |
| --- | ---: | ---: | --- |
| open | 0.14 s (60) | 0 | the three inputs copied and checked against the APPROVAL's digests, the H6 predecessor assertions, the resume compatibility check; `resume_source`: expect from the approval, previous_sessions from `runs/m9_g3/s5/session/line.json`, final state from s5's `final_state.json`, chain checked over s1 .. s5 |
| P1 lineages | 23.3 s (240) | 13,923 (60,000) | PASS, shared prefix 2,298 |
| P2 staging equivalence | 35.8 s (120) | 31,998 (60,000) | PASS |
| T0 drift check | 11.1 s (240) | 14,440 (60,000) | PASS: 5 of 5 tape keys at 2,128 reproduced the table (h, f, c, h, f) and the measuring session's native action digests |
| training | 4,648.9 s (4,800) | 9,089,510 (20,000,000) | valid end: **transition cap** (3,072,000 policy transitions reached at 4,638.65 s of training wall, before the 4,800 s wall cap); 600 rollouts, 6,000 PPO updates; prefix 5,668,051, policy 3,072,000, probes 349,459 ticks; train_fraction 0.9664 (>= 0.5: the session counts) |
| close audit | 230.9 s (1,200) | 460,529 (3,000,000) | 144 of 144 planned episodes (landings 2,128, 1,966 and 1,694: 20 sticky + 20 unperturbed + 1 deterministic each; tick 0: 20 sticky + 1 deterministic) |
| verification | 40.1 s (600) | 75,984 (1,500,000) | **31 of 31 replays exact** (tier 0: the 3 audit sticky clears; tier 1: 20 training clears; tier 2: 3 probe clears; tier 3: 5 diagnostics); 0 skipped, 0 errors |
| close | 343.6 s (300, see section 9) | 0 | the twelve protected trees equal their D: increments, no pin drift, no provenance or write-guard violation, metadata audit 1,072 files / 5,136 JSONL lines clean, no leftover process |

**Native ticks in the session: 9,686,384** (13,923 + 31,998 + 14,440 + 9,089,510 + 460,529 + 75,984). Lifecycle failures: 0 in every phase (training, T0,
the 5 attempts, the audit). Two `no_episode` step-mismatch records (section 9). Stale staging events 4.

## 4. The resume, bit for bit

| check | s5 final (recorded) | s6 | equal |
| --- | --- | --- | --- |
| copied `input/model.zip` | `382dde881fb6...` | `382dde881fb6...` (open.json `resume.inputs`; the file in `input/` hashes to it) | yes |
| copied `curriculum_state.json`, `tape_baseline.json` | `147467ca...`, `81fa52c2...` | same | yes |
| model members at the open | `f3e0dc32...` / `e3a78f5b...` | `resume.members` `f3e0dc32...` / `e3a78f5b...` | yes |
| **initial checkpoint `ckpt_007726976` (`why` initial)** | | `policy.pth` **`f3e0dc3257e03ed2ea1dbba0d68ffb53e7b85dd9606538b44f1d896203e76ffc`**, `policy.optimizer.pth` **`e3a78f5b4f6792639f50c80bd5ec4dd3f187330f3001464c514e4c579dbcd861`** (H12 byte check at `_on_training_start`: `initial_members_equal_predecessor: true`); its model.zip `512d2639...` differs from s5's `382dde88...` only in the `data` member (checked member by member: the other five members byte-equal), as designed | yes |
| counters | num_timesteps 7,726,976; `_n_updates` 15,070; Adam step 150,700 on 12 params | start_timesteps 7,726,976 -> final 10,798,976 (+3,072,000); updates 15,070 -> 21,070 (+6,000 = 600 rollouts x 10 epochs); Adam 150,700 -> 210,700 (+60,000 = 600 x 100) on all 12; resumed seed 1006 -> next 1007 | continuous |
| frontier carried | pointer 1,780; f 0 / need 0 / have 4; line_failed {1800: 5, 1820: 2, 1900: 2, 2020: 9, ...}; next_episode 17,100; attempt_counter 67; sessions [1 .. 5]; 26 moves 2,300 -> 1,780 | initial checkpoint pointer 1,780, spacing f 0 / need 0 / have 4; first s6 attempt n = 68 at 1,780 with a = 1; lowest s6 episode `train-0017100`; final state sessions [1 .. 6], next_episode 20,188, attempt_counter 72 | continuous |
| previous_sessions | s1-s5 rows | recorded at the open = s5's `line.json` rows (chain s1 -> s2 -> s3 -> s4 -> s5 checked); s6's `line.json` = [s1 .. s6 rows] | yes (verify-run `equal_to_predecessor_record: true`, `chain.ok: true`, 5 sessions) |

## 5. Training and the frontier

* Episodes 3,048: **744 clears (24.4 %)**, 1,632 falls, 672 horizon (s5: 55.7 %). By start region: strip 1,516 (279 clears, 18.4 %), near window 942 (224,
  23.8 %), rehearsal 590 (241, 40.8 %). Native ticks per policy transition 2.96 (s5: 4.72); prefix share of training ticks 62.4 %, probe share 3.8 %. Staged
  starts 3,084; slot wait for a ready start 54.5 s (66 waits); 30 staged starts withdrawn for attempts (6 per attempt); probe wall 187.7 s (4.0 % of the
  training wall; 28.0-69.1 s per attempt). Recent-episode mean return 5.20 in the first rollout, **-2.66 in the last**.
* **The inherited spacing and the first attempt.** s6 opened at 1,780 with f 0 / need 0 / have 4 (s5's close). No trigger was deferred: the first window
  trigger (8 of 18) fired at **65.1 s of training wall** with have 22, and attempt 68 (a = 1 at 1,780) MOVED the pointer to 1,760 at 128.9 s.
* **The pointer moved once: 1,780 -> 1,760** (27 moves in the line). It then held at 1,760 for the rest of training.
* **Every attempt** (5; frozen snapshot, keyed strip starts and draws; "live" = clear rate of the counted strip outcomes at that pointer before the trigger,
  at most 60; re-checks at every landing behind the pointer; wait = training wall since the previous trigger, or since the training start, with the deferred
  triggers in between (their `have`); gap = trigger window rate minus frozen strip-test rate):

| # | pointer | a | f / need / have | trigger (training wall) | live (n) | frozen strip test | re-checks (clears / non-clears, decision) | result | wall | wait before it / deferred | gap |
| ---: | ---: | ---: | --- | --- | ---: | --- | --- | --- | ---: | --- | ---: |
| 68 | 1,780 | 1 | 0 / 0 / 22 | 8 of 18 (65.1 s) | 0.44 (18) | 10 / 19 | 2,128 10/2 passed; 1,966 10/7 passed | MOVED -> 1,760 | 69.1 s | 65.1 s | -0.08 |
| 69 | 1,760 | 1 | 0 / 0 / 17 | 8 of 15 (182.3 s) | 0.53 (17) | 8 / 19 | - | FAILED_STRIP | 30.4 s | 117.2 s | +0.11 |
| 70 | 1,760 | 2 | 1 / 20 / 263 | 8 of 15 (1,017.5 s) | 0.32 (60) | 4 / 15 | - | FAILED_STRIP | 30.6 s | 835.2 s | +0.27 |
| 71 | 1,760 | 3 | 2 / 40 / 48 | 8 of 13 (1,201.0 s) | 0.37 (60) | 4 / 15 | - | FAILED_STRIP | 29.6 s | 183.5 s | +0.35 |
| 72 | 1,760 | 4 | 3 / 80 / 146 | 8 of 15 (1,649.9 s) | 0.37 (60) | 3 / 14 | - | FAILED_STRIP | 28.0 s | 448.9 s; 2 deferred at 41, 77 | +0.32 |

  Totals: **1 MOVED, 4 FAILED_STRIP, 0 BLOCKED_BY_RECHECK, 0 INTERRUPTED**; attempt yield 0.2 moves per decided attempt (s5: 0.571); **2 deferred
  triggers**, 5 acted-on triggers, 90 void windows; no HELD, no STALLED. After attempt 72 the spacing was f 4 / need 160; `have` grew to 1,020 by the close,
  but **no window reached the trigger again** in the last 2,989 s of training (no attempt after 1,677.9 s). Line failed attempts after s6: {1760: 4, 1800: 5,
  1820: 2, 1900: 2, 2020: 9, 2040: 6, 2060: 3, 2140: 2, 2160: 1, 2180: 1, 2200: 1, 2220: 4, 2240: 1, 2280: 4}.
* **Every re-check at 1,966 and 1,694.** One re-check at 1,966 (attempt 68: 10 clears / 7 non-clears, passed, 17 episodes, mean start value 1.11 against a
  mean return 4.76). None at 1,694: the pointer never passed behind it (1,694 < 1,760). (2,128: attempt 68, 10 / 2, passed.)
* **The frontier position over training time** (training wall, probe pauses included): 1,780 from 0 to 128.9 s; **1,760 from 128.9 s to the end of training
  (4,638.7 s; 75.2 minutes, four failed attempts)**.
* **Strip clear rates while training** (strip-region episodes at the pointer, per 100 in completion order): 1,780 0.41 (22 episodes; the last 79 are not
  available, only 22 exist); **1,760, the strip at the close and the strip where most training happened: 0.18 over 1,494 episodes (per 100: 0.23, 0.08,
  0.30, 0.34, 0.32, 0.17, 0.16, 0.18, 0.16, 0.17, 0.11, 0.24, 0.13, 0.08, 0.03 (last 94)); last 79 at 0.04**. For comparison, s5's last 79 at 1,800 were 0.51.
* **Throughput by pointer** (policy transitions/s per rollout, median [min, max], rollouts): 1,780 583.1 [326.6, 663.0] (6); 1,760 728.0 [62.8, 1,062.5] (594).
  Session median 727.1 transitions/s (s5: 547.8). The low minima are the rollouts that contained an attempt's pause.
* **Periodic checkpoints** (H2 alignment: 7,726,976 + j x 102,400): `ckpt_007829376` ... `ckpt_010696576` (j = 1..29, all at pointer 1,760), plus
  `ckpt_007726976` (initial, 1,780) and `final` (10,798,976, 1,760): **31 checkpoints**, each pinned (`checkpoint.json`) and re-checked by verify-run. None was
  evaluated (not authorised; the rule audits the final policy only).

## 6. The frozen final policy (close audit), paired with the earlier audits and the tape

Audited landings 2,128, 1,966 and 1,694 (every landing behind the pointer 1,760 plus the first beyond it, decision R8); 1,473 and 1,248 not audited; tick 0
descriptive. Final weights `policy.pth` `691fdcbd9b288f78...`. The sticky labels (`m9|g2|reach|<landing>|<k>`) and the audit action keys carry no session
component: s6's 20 sticky episodes at each landing draw the same masks and uniforms as s1-s5's and the tape's first 20 keys (a paired measurement under
different weights).

| start | tape (keys 0-19) | s1 | s2 | s3 | s4 | s5 | **s6** | s6 endings | B |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| **2,128** | 7 (p_hat 0.490 over 200) | 8 | 13 | 15 | 14 | 17 | **1 / 20** | 1 clear, 10 falls, 9 horizon | **15** |
| **1,966** | 2 (p_hat 0.050 over 40) | not audited | 3 | 9 | 13 | 12 | **0 / 20** | 14 falls, 6 horizon | 10 |
| **1,694** | 0 (p_hat 0.000 over 40) | not audited | not audited | not audited | not audited | 10 | **2 / 20** | 2 clears, 7 falls, 11 horizon | 10 |
| tick 0 | | | | 0 | 0 | 0 | 0 / 20 | 20 horizon | |

Non-sticky clears of the final policy (reported only): **unperturbed** 2,128 4 / 20 (s5: 17), 1,966 0 / 20 (s5: 5), 1,694 1 / 20 (s5: 5); **deterministic**
2,128 no clear (3,600-tick horizon, 9 targets; s5: CLEAR), 1,966 no clear (horizon, 8 targets), 1,694 no clear (horizon, 8 targets); tick-0 deterministic no
clear (horizon).

Per key k = 0..19 (c clear, f fall, h horizon):

```
2,128   tape  hfchfhccchfhchfchhcf   7
        s1    fhfcfcfcffffcffcfccc   8
        s2    cfccfcfccccfcfcfhccc  13
        s3    ffcccccccccffcfccccc  15
        s4    cccccccccccfcfcffcff  14
        s5    ccccccccfchccccfcccc  17
        s6    ffhcfhfhhffhffhhffhh   1
1,966   tape  fffffffhfffffffchffc   2
        s2    fcfffffffffffffcffcf   3
        s3    cfhccchccfcffcfcfffh   9
        s4    fccfccfccfccccchcfcf  13
        s5    fccffchcfccfcccccffc  12
        s6    fffhffffffhffhfhfhhf   0
1,694   tape  hhhfffffhffffffffffh   0
        s5    fffchcfcfccfcfcccfcf  10
        s6    hfchfhffhhhfhhfhfhch   2
```

At 2,128: s6 vs s5 on identical keys: both clear 1, s5 only 16, s6 only 0, neither 3; vs s4: both 1, s4 only 13, s6 only 0, neither 6; vs s3: both 1, s3 only
14, s6 only 0, neither 5; vs s2: both 1, s2 only 12, s6 only 0, neither 7; vs s1: both 1, s1 only 7, s6 only 0, neither 12; vs the tape: both 0, tape only 7,
s6 only 1, neither 12. At 1,966: s6 clears none (s5 12, s4 13, s3 9, s2 3, tape 2). At 1,694: s6 vs s5: both 1, s5 only 9, s6 only 1, neither 9; vs the tape:
s6 only 2, neither 18.

* **Rule outcome NULL:** D_6 = none (1 < 10 at 2,128), R_6 = none (1 < B = 15 at 2,128). `D/R_if_every_claimed_clear_were_verified` the same (claimed =
  verified at every landing). `route_mastered_ticks` none. **Reported, never deciding:** R_unperturbed none; no deterministic episode cleared; FRONTIER_BACKED
  false; tick 0 0 of 20.
* Value calibration (reported only; start V against the realised mean return of the 20 sticky episodes): 2,128 V -2.75 against -2.96 (gap +0.21; s5: -2.78),
  start entropy 3.930 nats (91.9 % of 4.2767); 1,966 V -2.45 against -3.86 (gap +1.41; s5: -3.14), entropy 3.967 (92.8 %); 1,694 V -0.21 against -0.72 (gap
  +0.51; s5: -0.46), entropy 3.019 (70.6 %). The start values, positive at all three landings in s5 (+5.68, +1.74, +3.62), are negative in s6.
* Entropy per rollout (fraction of maximum): 87.0 % after s6's first update, minimum 83.9 % (rollout 133), maximum 92.3 % (rollout 535), **87.5 % at the end**
  (s5 ended at 85.2 %); explained variance 0.84 -> 0.78 at the end (median 0.56, range -2.57 to 0.92); median approx_kl 0.0110.

## 7. Resources against the caps

| resource | peak / used | cap |
| --- | ---: | ---: |
| session clock | 5,333.9 s | 8,700 s |
| training wall | 4,648.9 s (the transition cap ended it) | 4,800 s |
| native ticks (session) | 9,686,384 (per phase in section 3) | per phase |
| policy transitions (this session) | 3,072,000 (the registered valid end) | 3,072,000 |
| main process private memory | 1,780.1 MB (sampler; the clock's own reading 1,785.3 MB) | 3,072 MB |
| process tree private memory | 6,752.2 MB | 9,216 MB |
| process tree working set | 2,513.1 MB | 4,096 MB |
| lowest system available memory | 5,988.9 MB | at least 1,024 MB |
| lowest system commit free | 11,915.6 MB | at least 2,048 MB |
| BattleShip processes (peak) | 10 (the external sampler: 400 of 698 session-window samples at 10) | 10 |
| memory breach | none (1,060 samples at 5 s) | |

**The machine.** A read-only external sampler (10 s, in the session scratchpad outside the repository; each sample appended and the file closed at once)
ran from 20:09:42Z (Part B start) to the end of the post-run checks (1,933 samples), and a file-free 3 s watch (stdout only) and 20-30 s `tasklist` monitors
ran alongside it. **No `node` and no Playwright process appeared at any sample, watch poll or monitor poll, at any time**, Part B and the session included
(one pre-pass command-line query for "playwright" matched only this session's own shells, whose command line contained the query text). No process other than
the session's own python (pid 18696, up to 1,785 MB private) reached 1,000 MB. Lowest free physical memory in the session window 5,995 MB (01:10:27Z), lowest
commit free 11,926 MB (same sample). The other Claude / Claude Code sessions in the desktop app were all idle (`isRunning` false at 20:09Z, 22:29Z, 23:24Z and
after the run); the latest activity of any of them was 18:59:51Z ("SewnCovers data layer inventory", another repository), before Part B started (20:09:33Z),
and unchanged after the run, so none ran BattleShip or any other project during this session. No application was closed.

## 8. Integrity, evidence and verification

| check | result |
| --- | --- |
| verification | 31 / 31 exact; every clear counted in a registered measure replayed (the 3 audit sticky clears: 1 at 2,128, 2 at 1,694); 20 training clears, 3 probe clears and 5 diagnostics exact |
| `verify-run --session 6` (against `runs/m9_g3/s5` and the chain s1-s5; before any copy, 21:24:15-21:24:27 EDT; output `logs/m9_g3_s6_run/verify_run.json`, copied to `derived/`) | **`ok: true`, 0 problems**: metadata 1,078 files / 5,136 JSONL lines, 0 failures; 31 checkpoints with pins and g3 identity; training 3,048 / probes 111 / drift 5 / audit 144 records re-derived; resume checks cross-checked (previous_sessions equal to s5's record, 5 rows; inputs = s5's final state; initial checkpoint `ckpt_007726976` members = s5's final members `f3e0dc32...` / `e3a78f5b...`); chain ok over 5 sessions; frontier rebuilt from the records = the log (pointer 1,760, 1 move, 5 attempts, 2 deferred); tape recorded at the open as `resume.inputs`, equal to the registered reuse, pinned; rule recomputed NULL / none / none = recorded; line recomputed END_BUDGET_1694 = recorded; `inexact` [], `tier0_without_replay` 0. Re-run after the copies into `launch/` and `derived/`: `ok: true` again, identical apart from its timestamp (`verify_run_after_copies.json`) |
| drift | 5 of 5 (no tape drift) |
| protected trees | the twelve (rd1 166, rd2 62, rd3 77, rd4 93, m9_g1 2,740, m9_g1_eval 1,393, m9_g2_s1 9,779, m9_g3_s1 4,935, m9_g3_s2 4,478, m9_g3_s3 3,779, m9_g3_s4 3,486, **m9_g3_s5 4,302**) equal their D: increments at both preflights, at the close, and after the backup by the tool (`trees_state(6)` 21:26:45-21:30:56 EDT: all twelve ok with the registered or discovered facts, `post_trees_tool_check.txt`) and the independent re-hash (21:30:56-21:34:56 EDT; 0 missing / 0 extra / 0 bad each, `post_trees_independent_check.txt`) |
| write guard, provenance | 0 provenance violations (`close.json`); every other `runs/` tree unchanged (above); no change under `rl/` or `docs/` apart from the new approval and this record (`git status`, section 11); `leftover_processes.json` empty |
| constraints | no RNG seed inspected, logged, controlled, compared or hashed (keyed sha256 draws only); process restart was the reset for every episode; P1 / P2 PASS (the submit / consume / input-tick contract); the submitted canonical words are the replay truth (31 / 31 exact); every start a prefix of the agent's own two verified rd4 routes; no fixture, TAS or recording read; no hardcoded route or waypoint; no native, decomp or submodule change |

**Evidence.** `runs/m9_g3/s6/` (Git-ignored): after the copies (21:25:44-21:25:47 EDT: `logs/m9_g3_s6_run` -> `launch/` except the two outputs, the whole of
`logs/m9_g3_s6_prep/` -> `launch/prep/` (byte-equal, `diff -rq` clean), the snapshot record and its verify JSON -> `launch/`, `verify_run.json` and
`report.json` -> `derived/`) **2,187 files, 290,350,712 bytes**. Increment **`D:\BattleShip_runs_backup\2026-10-10_incr_m9_g3_s6`**, manifest sha256
**`6d4540095eac5a9415ac098ed1f42a4b757bd71373e35e6f2e609af09c5c667b`**: tool backup PASS (2,187 / 290,350,712, 0 hash mismatches, 01:26:19Z); separate tool
verify `--source runs/m9_g3/s6` PASS (01:26:23Z, `verification.json` PASS, `source` = `runs\m9_g3\s6`); independent `independent_increment_check.ps1`:
checked 2,187, missing 0, extra 0, bad 0, PASS (21:26:09-21:26:33 EDT for the three). **Total `runs/` coverage: 446,554 source files, 0 uncovered, 18
increments** (`post_coverage.txt`; 444,367 + 2,187). **Discovery** (`next_session_discovery.txt`): `unregistered_predecessors(7)` = []; `predecessor_tree(6)`
= (`m9_g3_s6`, `2026-10-10_incr_m9_g3_s6`, 2,187 files, 290,350,712 bytes, manifest `6d454009...`, discovered from the increment's verification record, no
record problem); before this record existed, `predecessor_doc_problems(7)` named only the missing s6 results record. Post-backup logs live in
`logs/m9_g3_s6_run/`, outside the increment.

**The saved state** (`session/final_state.json` sha256 `0031c978920561afe262dc794f616cc203c3b161e14b39f841549d3183b5a5b5`; the line has ended, so no later
g3 session is permitted by the line rule):

| file | sha256 |
| --- | --- |
| `training/checkpoints/final/model.zip` (1,110,776 bytes) | `d90aa54f2b0d556674169e48ae53fc670c51d2dd131a4c2ec4c0dcdbdc3c5484` |
| its `policy.pth` member | `691fdcbd9b288f7842e8a51d0ca237fcbcb265d4b454fd0ed2c49c3c8f5d6ce5` |
| its `policy.optimizer.pth` member (21,070 updates; Adam step 210,700 on 12 parameters) | `a3bcc265640244477656ae26d2baaea0128e1878cd0d3161e92cd3795aa30043` |
| `training/checkpoints/final/curriculum_state.json` (10,407 bytes; pointer 1,760; f 4 / need 160 / have 1,020; sessions [1, 2, 3, 4, 5, 6]; num_timesteps 10,798,976; next_episode 20,188; attempt_counter 72) | `0897143183493657e29cd9c894d77cb03485f798fc10a2cdab0185b1851a36ec` |
| `input/tape_baseline.json` | `81fa52c21078b2c2...` (content `d915fab9...`) |
| `session/line.json` (rows s1-s6) / `session/rule.json` | `0c72ca17992cbeb0...` / `f29ffad6ef85cd3b...` |
| line contract / next session seed | `90eac1a6...` / 1007 |

## 9. Departures and notes

* **Two step-mismatch records** (`session/failures/step_x_w02.json.gz` and `step_x_w04.json.gz`, both 00:23:47Z), both `no_episode`, both from the probe
  runner's known race (the s3 / s5 mechanism), this time inside attempt 72's STRIP test at 1,760: the test was decided `failed` by its 11th non-clear
  (probe-1760-4-strip-13, slot 9, recorded 00:23:47Z), `_cancel` closed the active episodes, and two steps queued earlier in the same batch were sent after the
  close. w02 = abandoned `probe-1760-4-strip-16` (tau 1,767 + 592 policy ticks = 2,359 = the preserved tail's last input tick); w04 = abandoned
  `probe-1760-4-strip-12` (1,767 + 1,690 = 3,457); the strip taus were recomputed from the keyed `strip_start` draws and equal the recorded tau of all 14
  completed strip episodes. The strip run sent exactly two steps that ticked nothing (`sent.step` 16,268 = policy ticks 16,266 + 2); the other two abandoned
  episodes (strip-14, strip-17) had steps in flight that came back as the run's 2 late steps. In both records the decision and the slot close came BEFORE the
  queued step reached the worker; no native call was made for the failing commands; abandoned episodes count in no test, attempt, spacing, training
  statistic, audit, rule or line measure; verify-run clean. Not a replay or determinism mismatch (`logs/m9_g3_s6_run/s6_step_mismatch_explanation.md`, copied
  into `launch/`). Reported, not acted on.
* **Training ended by the transition cap, not the wall cap.** Only 5 attempts paused training for 187.7 s in total (s5: 1,094.2 s for 21), so the session
  reached the registered 3,072,000-transition cap at 4,638.65 s of training wall, a registered valid end (`stop` "transition_cap"); train_fraction 0.9664.
* **The close phase took 343.6 s against the 300 s figure in `WALL_CAPS_S`** (projected 639.0 s in the approval's budget block). The close is not
  clock-enforced (the resume-k record, section 5); the session clock total (5,333.9 s) stayed far inside the 8,700 s cap and nothing was marked. Reported as a
  fact, not acted on.
* **4 stale staging events** (episodes staged at the pointer before the move that finished after it; `training/stale.jsonl`). Recorded by design.
* **The launch shell.** The launcher was run from the Git Bash shell of this unattended session's tool, which returns once `Start-Process` has started the
  detached, hidden python (the same form as s1-s5). That shell was not an interactive terminal that could be kept open; the detached process ran to
  completion by itself (`state.json` `done`, the process gone, stderr empty). Nothing was closed.
* **The independent re-hash of the twelve trees ran twice in Part B** (18:25:03-18:29:19 and, per tree timed, 18:30:05-18:34:31 EDT), both PASS for all
  twelve; the second run exists only to record each tree's start and end time, as the user's message asks. Read-only.
* No pre-launch fix, no tool copy and no edit: the four generic tools ran as found; no tracked file was modified; nothing was staged; no application was closed.

## 10. What this does and does not say

* It says: resumed from s5's exact final state, a sixth session of the same recipe under the same frontier rule moved the pointer once (1,780 -> 1,760 at
  128.9 s, with 2,128 and 1,966 re-checks passed by the frozen snapshot at that moment), then failed four strip tests at 1,760 (8/19, 4/15, 4/15, 3/14) and
  produced a frozen final policy that clears **1 of 20** sticky episodes from 2,128 (s5: 17; tape 7 on the same keys), **0 of 20** from 1,966 (s5: 12) and
  **2 of 20** from 1,694 (s5: 10). D_6 = R_6 = none, hence NULL under the per-session rule, and the line ends by END_BUDGET_1694 (k = 6 needed D_6 at or
  before 1,694).
* It also shows, as facts and not decisions: during s6 the strip clear rate at 1,760 fell from 0.23 (first 100) to 0.04 (last 79), the recent-episode mean
  return turned from +5.20 to -2.66, the frozen snapshots' strip tests fell from 10/19 to 3/14, the start values at all audited landings turned negative, and
  policy entropy rose (maximum 92.3 % of the maximum at rollout 535). The final policy lost the competence the s5 policy had at landings it had trained
  through in earlier sessions. No cause is claimed here: no checkpoint other than the final one was evaluated (not authorised), and the 31 pinned checkpoints
  remain available for a diagnosis if one is ever authorised.
* **For a session 7** (`logs/m9_g3_s6_run/session7_line_consequence.txt`, computed read-only after the run): the recorded line outcome is END_BUDGET_1694 with
  the next session not permitted, so **no g3 session 7 is permitted by `m9_g3_line_rule_v1`**. For completeness, `line_consequence(7, rows)` applied
  mechanically to the six recorded rows gives: NULL, D 2,128, 1,966 or 1,694, or a counting INCOMPLETE -> END_NO_PROGRESS; D <= 1,473 -> END_SUCCESS; an
  INCOMPLETE that does not count -> CONTINUE; INVALID -> SUSPENDED; END_CAP at k = 8. Any further work on this task is a new decision for the user, outside
  the g3 line.
* It does not say anything about other seeds, budgets or recipes, and it does not claim a tick-0 policy.

## 11. git status at the end

HEAD = origin/main = `1d975efd1a5db8204be331c88851262df6fd3a7e`; no commit, push, branch or pull request; nothing staged; `git diff --check` clean;
`git status --porcelain --untracked-files=all` shows only new files:

```
?? docs/rl_m9_g3_s6_approval.json
?? docs/rl_m9_g3_s6_results_2026-10-10.md
```

Git-ignored and therefore not shown: `logs/m9_g3_s6_prep/` (Part B), `logs/m9_g3_s6_run/` (snapshot, approval, preflight, launch, wait and post-run logs) and
`runs/m9_g3/s6/`. With this record in place, `predecessor_doc_problems(7)` = [] and the record is the only accepted `rl_m9_g3_s6_results` entry (checked
read-only after writing it).
