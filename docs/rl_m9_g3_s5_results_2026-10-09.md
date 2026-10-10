# M9-g3-s5 results (2026-10-09)

**Registered outcome: PASS** (`m9_g3_s1_rule_v1`, the per-session rule, sha256 `dea9965a3989bce5...`): **D_5 = 1,694**, **R_5 = 1,694**. The frozen final
policy cleared **17 of 20** sticky episodes from the landing state 2,128 (17 clears, 2 falls, 1 horizon, all verified), **12 of 20** from 1,966 (12 clears, 7
falls, 1 horizon, all verified) and **10 of 20** from 1,694 (10 clears, 9 falls, 1 horizon, all verified). Both chains reach 1,694: 2,128: 17 >= 15 (the reach bar
B there) and >= 10; 1,966: 12 >= 10; 1,694: 10 >= 10; 1,473 not audited, by design (decision R8: every landing behind the pointer 1,780 plus the first beyond it).
PASS needs R <= 1,966: met. The rule's reason string, as recorded: "R_1 = 1694 <= 1966" (the rule text names the per-session subscript 1; this is session 5's own
result). **Line outcome: CONTINUE** (`m9_g3_line_rule_v1`, `d9d82885703c016d...`): k = 5, counted sessions [1, 2, 3, 4, 5], depths [none, 2,128, 2,128, 1,966,
1,694], "session 6 is proposable, with its own approval". This is the row the approval's computed `line_consequence` registered for "INCONCLUSIVE or PASS with
D = 1694" before the run (CONTINUE; END_NO_PROGRESS needed D_5 earlier than D_3 = 2,128: met). PASS is the per-session rule's outcome, not the line's
END_SUCCESS (D <= 1,473). Nothing follows automatically: **no s6 was run or authorised**. One session, one run, once; nothing was retried, extended or repaired.
Every number below is read from `runs/m9_g3/s5/` and recomputed by `verify-run` (section 8).

Scope label: *M9-g3-s5: the fifth session of the g3 line, RESUMED bit for bit from g3-s4's recorded final state (model, optimizer, frontier pointer 2,020 and
spacing f 9 / need 320 / have 196, episode and attempt counters), under the unchanged replenishing controlled frontier rule `m9_g3_frontier_v1`, the same recipe
(observation v3, reward v2, sticky p = 0.25, entropy 0.01, 80 minutes, 4 + 6 slots), the reused g2-s1 tape baseline by digest, and the same keyed audit draws as
s1-s4 (a paired measurement, not a replay); progress measured as D and R at landing states under the registered rules; no claim of a tick-0 policy.*

**The date.** The user's rule for this unattended session: one date for everything dated, the local date when Part B started. Part B started on
2026-10-09 at 23:54:48 EDT (B0 at 23:55:25 EDT), so the snapshot, the approval's `authorised_on`, the increment and this record carry **2026-10-09**. Every
UTC timestamp below falls on 2026-10-10 (03:54Z to 09:06Z), because the session crossed local midnight.

## 1. What was run

| item | value |
| --- | --- |
| tree | HEAD = origin/main = remote `main` = `86773666a7d7c6e0563e127cf2688ea32f14b125` ("Add the results of the fourth training session ...", carrying the s4 approval `84751054...` and the s4 results record `03eef472...`); no tracked file modified at any point; nothing staged; g3 source fingerprint **`15ddbb84932aa658`** |
| authorisation | the user's unattended-session message of 2026-10-09, Part C, quoted verbatim in the approval (`authorised_on` 2026-10-09; `logs/m9_g3_s5_prep/launch_2026-10-09/s5_authorisation_part_c_2026-10-09.txt`, sha256 `555a57bf...`, 25 lines), including "Acknowledged line consequence: if D₅ is NULL or 2,128, the g3 line ends (END_NO_PROGRESS). D₅ ≤ 1,966 continues it." |
| source snapshot | `D:\BattleShip_source_snapshots\2026-10-09_m9_g3_s5` (`--session 5`; `log_dirs` [logs/m9_g3_prep, logs/m9_g3_s2_prep, logs/m9_g3_resume_tools, logs/m9_g3_resume_k_prep, logs/m9_g3_s5_prep]); 06:09:02Z-06:12:11Z; PASS, 371 files, 4,084,807 bytes, 185.5 s, `snapshot.json` sha256 **`00d6b4745946e7c8807deb7806768428b2ad1af219b2df517e47aaa4886d50ba`**; tool verify PASS (06:12:09Z: 371 files, 0 mismatches, 0 extra, 0 external mismatches, executable equal); independent PowerShell re-hash checked 372, bad 0, exe equal, PASS |
| approval | NEW `docs/rl_m9_g3_s5_approval.json`, sha256 **`1e594fcb1b11698ae284263f12727f7c0932333ee0bf084b031b6d5c4ea323dd`**, written 06:12:31Z-06:16:45Z by `logs/m9_g3_resume_tools/write_approval.py --session 5` (unchanged, sha256 `e652f04e...`) from `identity(5)` at the final HEAD: session 5; the eleven trees; the D: folders; `resume_inputs` (expect {`7269898a...`, `598ac824...`, `81fa52c2...`}, members `366f9d86...` / `38c940b7...`, counters 5,745,536 / 11,200 / Adam 112,000 x 12, `previous_sessions` = the s1-s4 rows read from s4's `line.json` and cross-checked along the chain s1 -> s2 -> s3 -> s4, s4's tree facts 3,486 / 411,903,655 / `8bc072ba...` discovered from its increment); the snapshot above; the COMPUTED `line_consequence` (B12); the authorisation text verbatim (equal to the file); `approval_status(5)` = approved |
| full preflight (once) | `python -B -X utf8 rl/m9_g3_session.py preflight --session 5`, 06:17:01Z to 06:48:18Z, **exit 0, `ok: true`, `problems: []`**: unit 29 / 29 (1,409 s), rule self-test PASS, approval "approved", snapshot "recorded, PASS and equal to the repository", eleven trees ok, coverage 440,065 / 0 / 16, readiness 7,774.0 MB available / 18,338.1 MB commit free; the only new file the approval |
| launch | `powershell -NoProfile -ExecutionPolicy Bypass -File logs/m9_g3_resume_tools/launch_detached.ps1 -Session 5 -Repo ...` (sha256 `53f675ad...`) from Git Bash: **pid 38104 at 2026-10-10T06:48:41Z**, `python -B -u -X utf8 rl/m9_g3_session.py run --session 5`; its own preflight ran first (unit 29 / 29 in 1,019 s; readiness 7,881.1 MB / 18,236.1 MB); the session clock started 07:16:03Z; the process exited by itself (state `done` at 08:52:55Z); `session_stderr.txt` empty; waited with `wait_session.py --session 5` (done, exit 0, 124.5 min) |
| session clock | **5,811.6 s (96.9 min)** of the 8,700 s cap |
| executable | `build-us/Release/BattleShip.exe` `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee`, unchanged at the close; runtime files and frozen configuration equal their pins |

## 2. Part B (B0-B13), all held before any native tick

Logs: `logs/m9_g3_s5_prep/launch_2026-10-09/` (inside the s5 snapshot's file set; `partb_summary.md` there), `logs/m9_g3_s5_prep/final/` (the three passes).
Conditions: `docs/rl_m9_g3_resume_k_prep_decisions_2026-10-08.md` section 8 for k = 5, with the values of `docs/rl_m9_g3_progression_fix_2026-10-08.md`
section 10 and of the user's message. No preparation round (B13).

| # | result |
| --- | --- |
| B0 | HEAD = origin/main = `git ls-remote origin refs/heads/main` = `8677366` (carrying the s4 approval and results record); `git status --porcelain --untracked-files=all` empty; nothing staged; `git diff --check` clean; fingerprint `15ddbb84932aa658` (per-file digests equal the progression-fix record; all ten g3 modules `i/lf w/lf`) |
| B1 | `three_passes.py --session 5` WITHOUT `--allow-git-gate` (03:57:13Z-05:40:05Z): **THREE_CONSECUTIVE_PASSES**, exit 0; unit **29 / 29** x 3 (1,450.8 / 995.9 / 901.4 s), e2e PASS digest **`078f46c445d8adc5`** x 3 (1,020.8 / 900.5 / 902.0 s), fingerprint unchanged before and after every pass; then, one after another (05:40:31Z-05:54:21Z): rule self-test PASS (s1 `dea9965a3989bce5`, line `d9d82885703c016d`); g1 evaluation 29 / 29 (63 s); g2 29 / 29 (438 s); g1 unit 62 / 63 with ONLY `identity_names_every_registered_pin` failing (325 s; its FAIL line identical to s4's apart from the timing); fingerprint after the suites unchanged; git status empty at the suites' start and end. No `node` or Playwright process at any time (section 7), so the sequence never had to restart |
| B2 | g3 contract `4cd1deae...`, line contract `90eac1a6...`, frontier `60e174a6...`, s1 rule `dea9965a...`, line rule `d9d82885...`, g2 `8dfd44c6a8b7e319` / `1aadc7a6b2ff85bd`, g1 `6958857ed2dfd1c5`: all equal; `G.PPO` = s4's saved `curriculum_state.ppo` |
| B3 | executable `30a3913b...` (= s4's `final_state.executable_sha256`); pins; tape `81fa52c21078b2c2 / d915fab920554774` pinned, measured with the executable now; CVars absent or zero; status table verified; `T_clear` 2,326 / `5eccd4e2d5d77b25`, `T_t` 2,315 / `de1228be4146b720` |
| B4 | s4's saved state byte-identical to its records: `model.zip` `7269898a...` (1,111,726 B), members `366f9d86...` / `38c940b7...` (recorded = now); `curriculum_state.json` `598ac824...` (6,755 B; pointer 2,020; f 9 / need 320 / have 196; sessions [1, 2, 3, 4]; num_timesteps 5,745,536; next_episode 14,341; attempt_counter 46); tape `81fa52c2...`; `final_state.json` `71de3196...` (session 4; counters 5,745,536 / 11,200 / Adam 112,000 x 12; next seed 1005; line CONTINUE); `line.json` `b7251dc3...` rows = s1, s2, s3, s4; `rule.json` `9d6cbbfd...`; `predecessor_problems(5)` = []; `unregistered_predecessors(5)` = []; chain `sessions_checked` 4; `predecessor_doc_problems(5)` = [] (the s1-s4 approvals and results records found by the exact rule); `runs/m9_g3/s4` = its increment `2026-10-09_incr_m9_g3_s4` (manifest `8bc072ba...`, discovered, no record problem) by the tool (eleventh tree ok) AND the independent re-hash (3,486 checked, 0 missing / 0 extra / 0 bad) |
| B5 | the eleven trees of `trees_for(5)` ok with the registered or discovered facts (tool, dry run) and PASS by the independent re-hash (rd1 166, rd2 62, rd3 77, rd4 93, m9_g1 2,740, m9_g1_eval 1,393, m9_g2_s1 9,779, m9_g3_s1 4,935, m9_g3_s2 4,478, m9_g3_s3 3,779, m9_g3_s4 3,486; 0 / 0 / 0 each); coverage 440,065 files, 0 uncovered, 16 increments |
| B6 | `preflight --session 5 --skip-unit` (05:55:00Z-06:03:21Z): exit 1 with exactly `["no approval record at docs\rl_m9_g3_s5_approval.json (the session is not authorised)"]`; stderr empty; readiness passed (8,022.7 MB / 18,257.7 MB; C: 97.4 GiB, D: 1,641.8 GiB) without closing anything |
| B7 | pessimistic 7,780 s of 8,700 s (fits); the close projected 563.1 s over eleven trees (3,740,740,764 B), not clock-enforced; pessimistic total with that close 8,043.1 s, fits |
| B8 | no `BattleShip.exe` anywhere (before the dry run, at 06:08:06Z, before the launch); no tracked, staged or replay-browser change (`replay/_local` untouched since 2026-10-03); readiness above the thresholds at every reading; no `node` or Playwright process and no process >= 1,000 MB at any sample; the other Claude Code sessions idle (section 7) |
| B9 / B10 | section 1 (snapshot first, then the approval; every Part B log written before the snapshot; nothing written under any directory of the snapshot set afterwards; later logs in `logs/m9_g3_s5_run/`) |
| B11 | the four generic tools as found (sha256 unchanged since s4, `b8_b11_machine_and_paths.txt`); `independent_increment_check.ps1` `98abb0b9...`; `logs/m9_g3_s5_run`, `runs/m9_g3/s5`, the s5 approval, any `rl_m9_g3_s5` docs entry, the s5 snapshot and any s5 increment absent before Part C |
| B12 | `line_consequence(5, [s1, s2, s3, s4])` computed into the approval: NULL -> END_NO_PROGRESS; D 2,128 -> END_NO_PROGRESS; D 1,966 / 1,694 -> CONTINUE; D 1,473 / 1,369 / 1,248 -> END_SUCCESS; INCOMPLETE counting -> END_NO_PROGRESS; INCOMPLETE not counting -> CONTINUE; INVALID -> SUSPENDED; reachable line ends: END_NO_PROGRESS, END_SUCCESS, SUSPENDED; END_CAP at k = 8 (k = 5 within the cap). Equal to the consequence the user's message states |
| B13 | k = 5: s4 DISCOVERED from exactly one increment `2026-10-09_incr_m9_g3_s4` (PASS record naming `runs/m9_g3/s4`, manifest at the recorded digest); s3 discovered likewise; s1, s2 registered; `unregistered_predecessors(5)` = [] |

**The s4 failure records (checked read-only before Part C).** `runs/m9_g3/s4` has no `session/failures/` directory, so no step-mismatch or `no_episode`
record exists in s4. Its only lifecycle failure is the one the s4 record reports: `train-0011297`, `episode_timeout`, slot 8, in the first rollout (1 of the
limit of 3); T0, the audit and the probe attempts recorded none (`logs/m9_g3_s5_prep/launch_2026-10-09/s4_failure_record_check.txt`).

## 3. Phases

| phase | wall (cap) | native ticks (cap) | result |
| --- | ---: | ---: | --- |
| open | 0.14 s (60) | 0 | the three inputs copied and checked against the APPROVAL's digests, the H6 predecessor assertions, the resume compatibility check; `resume_source`: expect from the approval, previous_sessions from `runs/m9_g3/s4/session/line.json`, final state from s4's `final_state.json`, chain checked over s1, s2, s3, s4 |
| P1 lineages | 24.7 s (240) | 13,923 (60,000) | PASS, shared prefix 2,298 |
| P2 staging equivalence | 37.3 s (120) | 31,998 (60,000) | PASS |
| T0 drift check | 13.8 s (240) | 14,440 (60,000) | PASS: 5 of 5 tape keys at 2,128 reproduced the table (h, f, c, h, f) and the measuring session's native action digests |
| training | 4,803.8 s (4,800) | 9,352,886 (20,000,000) | valid end: **wall cap**; **1,981,440 policy transitions** (cap 3,072,000), 387 rollouts, 3,870 PPO updates; prefix 5,268,928, policy 1,981,440, probes 2,102,518 ticks |
| close audit | 206.3 s (1,200) | 399,517 (3,000,000) | 144 of 144 planned episodes (landings 2,128, 1,966 and 1,694: 20 sticky + 20 unperturbed + 1 deterministic each; tick 0: 20 sticky + 1 deterministic) |
| verification | 163.7 s (600) | 311,143 (1,500,000) | **122 of 122 replays exact** (tier 0: the 39 audit sticky clears; tier 1: 20 training clears; tier 2: 35 probe clears; tier 3: 28 diagnostics); 0 skipped, 0 errors |
| close | 561.9 s (300, see section 9) | 0 | the eleven protected trees equal their D: increments, no pin drift, no provenance or write-guard violation, metadata audit 2,122 files / 5,369 JSONL lines clean, no leftover process |

**Native ticks in the session: 10,123,907** (13,923 + 31,998 + 14,440 + 9,352,886 + 399,517 + 311,143). Lifecycle failures: 0 in every phase (training,
T0, the 21 attempts, the audit). Stale staging events 26 (`training/stale.jsonl`: episodes started at the pointer before a move and ended after it, 1-3 per
move; s2 recorded 24).

## 4. The resume, bit for bit

| check | s4 final (recorded) | s5 | equal |
| --- | --- | --- | --- |
| copied `input/model.zip` | `7269898ac085...` | `7269898ac085...` (open.json `resume.inputs`; the file in `input/`, byte-equal to s4's final model) | yes |
| copied `curriculum_state.json`, `tape_baseline.json` | `598ac824...`, `81fa52c2...` | same | yes |
| model members at the open | `366f9d86...` / `38c940b7...` | `resume.members` `366f9d86...` / `38c940b7...` | yes |
| **initial checkpoint `ckpt_005745536` (`why` initial)** | | `policy.pth` **`366f9d86247404d76df7e8beae4c9e69782e5453d45cf2b909cc5ab9837ab264`**, `policy.optimizer.pth` **`38c940b723a84de93f925075606034945efe83088d4419a882ca1d26659fef1f`** (H12 byte check at `_on_training_start`: `initial_members_equal_predecessor: true`); its model.zip `ca0c2281...` differs from s4's `7269898a...` only in the `data` member (checked member by member), as designed | yes |
| counters | num_timesteps 5,745,536; `_n_updates` 11,200; Adam step 112,000 on 12 params | start_timesteps 5,745,536 -> final 7,726,976 (+1,981,440); updates 11,200 -> 15,070 (+3,870 = 387 rollouts x 10 epochs); Adam 112,000 -> 150,700 (+38,700 = 387 x 100) on all 12; resumed seed 1005 -> next 1006 | continuous |
| frontier carried | pointer 2,020; f 9 / need 320 / have 196; line_failed {2020: 9, 2040: 6, 2060: 3, 2140: 2, 2160: 1, 2180: 1, 2200: 1, 2220: 4, 2240: 1, 2280: 4}; next_episode 14,341; attempt_counter 46; sessions [1, 2, 3, 4]; 14 moves 2,300 -> 2,020 | initial checkpoint pointer 2,020, spacing f 9 / need 320 / have 196; first s5 attempt n = 47 at 2,020 with a = 10, f 9 / need 320; lowest s5 episode `train-0014341`; final state sessions [1, 2, 3, 4, 5], next_episode 17,100, attempt_counter 67 | continuous |
| previous_sessions | s1-s4 rows | recorded at the open = s4's `line.json` rows (chain s1 -> s2 -> s3 -> s4 checked); s5's `line.json` = [s1 .. s5 rows] | yes (verify-run `equal_to_predecessor_record: true`, `chain.ok: true`, 4 sessions) |

## 5. Training and the frontier

* Episodes 2,623: **1,462 clears (55.7 %)**, 912 falls, 249 horizon. By start region: strip 1,329 (633 clears, 47.6 %), near window 800 (477, 59.6 %),
  rehearsal 494 (352, 71.3 %). Native ticks per policy transition 4.72 (s4: 4.27); prefix share of training ticks 56.3 %, probe share 22.5 %. Staged starts
  2,755; slot wait for a ready start 126.0 s (2.6 % of the training wall); 126 staged starts withdrawn for attempts (6 per attempt); probe wall 1,094.2 s
  (22.8 %; 27.1-76.1 s per attempt).
* **The inherited spacing and the first attempt.** s5 opened at 2,020 with f 9 / need 320 / have 196 (s4's close). Eight triggers were deferred while
  `have` < 320 (at have 213, 227, 238, 255, 272, 286, 296, 311); the first acted-on trigger fired at **342.2 s of training wall** (have 325 at the trigger,
  330 at the attempt), and attempt 47 (a = 10 at 2,020) MOVED the pointer to 2,000 at 389.0 s.
* **The pointer moved 12 times: 2,020 -> 1,780** (14 moves before s5, 26 in the line). Landing 1,966 entered the re-check set at pointer 1,940 (attempt 51).
* **Every attempt** (21; frozen snapshot, keyed strip starts and draws; "live" = clear rate of the counted strip outcomes at that pointer before the trigger,
  at most 60; re-checks at every landing behind the pointer; wait = training wall since the previous trigger, or since the training start, with the deferred
  triggers in between (their `have`); gap = trigger window rate minus frozen strip-test rate):

| # | pointer | a | f / need / have | trigger (training wall) | live (n) | frozen strip test | re-checks (clears / episodes, decision) | result | wall | wait before it / deferred | gap |
| ---: | ---: | ---: | --- | --- | ---: | --- | --- | --- | ---: | --- | ---: |
| 47 | 2,020 | 10 | 9 / 320 / 330 | 8 of 14 (342.2 s) | 0.60 (60) | 10 / 16 | 2,128 10/11 passed | MOVED -> 2,000 | 45.2 s | 342.2 s; 8 deferred at 213, 227, 238, 255, 272, 286, 296, 311 | -0.05 |
| 48 | 2,000 | 1 | 0 / 0 / 22 | 8 of 18 (452.7 s) | 0.50 (22) | 10 / 18 | 2,128 10/11 passed | MOVED -> 1,980 | 50.3 s | 110.4 s | -0.11 |
| 49 | 1,980 | 1 | 0 / 0 / 10 | 8 of 10 (542.0 s) | 0.80 (10) | 10 / 20 | 2,128 10/11 passed | MOVED -> 1,960 | 50.3 s | 89.3 s | +0.30 |
| 50 | 1,960 | 1 | 0 / 0 / 13 | 8 of 11 (644.8 s) | 0.69 (13) | 10 / 16 | 2,128 10/13 passed | MOVED -> 1,940 | 50.3 s | 102.8 s | +0.10 |
| 51 | 1,940 | 1 | 0 / 0 / 15 | 8 of 10 (732.6 s) | 0.67 (15) | 10 / 17 | 2,128 10/13 passed; 1,966 10/17 passed | MOVED -> 1,920 | 68.3 s | 87.8 s | +0.21 |
| 52 | 1,920 | 1 | 0 / 0 / 14 | 8 of 12 (858.1 s) | 0.71 (14) | 10 / 12 | 2,128 10/11 passed; 1,966 10/14 passed | MOVED -> 1,900 | 65.7 s | 125.5 s | -0.17 |
| 53 | 1,900 | 1 | 0 / 0 / 12 | 8 of 12 (958.8 s) | 0.67 (12) | 9 / 20 | - | FAILED_STRIP | 31.1 s | 100.8 s | +0.22 |
| 54 | 1,900 | 2 | 1 / 20 / 36 | 8 of 15 (1,101.2 s) | 0.54 (48) | 9 / 20 | - | FAILED_STRIP | 32.4 s | 142.4 s; 1 deferred at 18 | +0.08 |
| 55 | 1,900 | 3 | 2 / 40 / 52 | 8 of 13 (1,284.5 s) | 0.60 (60) | 10 / 16 | 2,128 10/11 passed; 1,966 10/11 passed | MOVED -> 1,880 | 65.0 s | 183.2 s; 3 deferred at 10, 26, 39 | -0.01 |
| 56 | 1,880 | 1 | 0 / 0 / 15 | 8 of 13 (1,383.2 s) | 0.67 (15) | 10 / 13 | 2,128 10/12 passed; 1,966 10/12 passed | MOVED -> 1,860 | 60.9 s | 98.7 s | -0.15 |
| 57 | 1,860 | 1 | 0 / 0 / 15 | 8 of 11 (1,488.4 s) | 0.80 (15) | 10 / 15 | 2,128 10/12 passed; 1,966 10/11 passed | MOVED -> 1,840 | 62.8 s | 105.2 s | +0.06 |
| 58 | 1,840 | 1 | 0 / 0 / 17 | 8 of 17 (1,619.8 s) | 0.47 (17) | 10 / 15 | 2,128 10/10 passed; 1,966 10/18 passed | MOVED -> 1,820 | 66.7 s | 131.5 s | -0.20 |
| 59 | 1,820 | 1 | 0 / 0 / 18 | 8 of 15 (1,743.6 s) | 0.56 (18) | 9 / 20 | - | FAILED_STRIP | 30.0 s | 123.7 s | +0.08 |
| 60 | 1,820 | 2 | 1 / 20 / 26 | 8 of 11 (1,858.9 s) | 0.59 (44) | 10 / 15 | 2,128 10/14 passed; 1,966 4/15 failed | BLOCKED_BY_RECHECK | 75.6 s | 115.3 s; 1 deferred at 14 | +0.06 |
| 61 | 1,820 | 3 | 2 / 40 / 44 | 8 of 16 (2,056.5 s) | 0.58 (60) | 10 / 15 | 2,128 10/11 passed; 1,966 10/16 passed | MOVED -> 1,800 | 75.0 s | 197.6 s; 2 deferred at 14, 28 | -0.17 |
| 62 | 1,800 | 1 | 0 / 0 / 136 | 8 of 17 (2,457.7 s) | 0.35 (60) | 3 / 14 | - | FAILED_STRIP | 27.1 s | 401.2 s | +0.26 |
| 63 | 1,800 | 2 | 1 / 20 / 32 | 8 of 15 (2,569.0 s) | 0.35 (60) | 6 / 17 | - | FAILED_STRIP | 28.6 s | 111.2 s | +0.18 |
| 64 | 1,800 | 3 | 2 / 40 / 46 | 8 of 16 (2,692.4 s) | 0.48 (60) | 7 / 18 | - | FAILED_STRIP | 30.1 s | 123.5 s; 1 deferred at 10 | +0.11 |
| 65 | 1,800 | 4 | 3 / 80 / 130 | 8 of 12 (3,094.8 s) | 0.43 (60) | 7 / 18 | - | FAILED_STRIP | 29.2 s | 402.4 s; 4 deferred at 17, 31, 62, 78 | +0.28 |
| 66 | 1,800 | 5 | 4 / 160 / 170 | 8 of 19 (3,610.3 s) | 0.38 (60) | 10 / 17 | 1,966 4/15 failed (fail-fast); 2,128 9/14 cancelled | BLOCKED_BY_RECHECK | 76.1 s | 515.5 s; 6 deferred at 16, 35, 52, 85, 118, 149 | -0.17 |
| 67 | 1,800 | 6 | 5 / 320 / 342 | 8 of 10 (4,695.9 s) | 0.50 (60) | 10 / 19 | 2,128 10/14 passed; 1,966 10/18 passed | MOVED -> 1,780 | 73.3 s | 1,085.6 s; 15 deferred at 13, 27, 38, 92, 106, 165, 184, 202, 215, 229, 244, 263, 277, 294, 308 | +0.27 |

  Totals: **12 MOVED, 7 FAILED_STRIP, 2 BLOCKED_BY_RECHECK (both by the 1,966 re-check, 4 of 15), 0 INTERRUPTED**; attempt yield 0.571 moves per decided
  attempt (s4: 0.0); **41 deferred triggers**, 21 acted-on triggers, 20 void windows; no HELD, no STALLED; spacing at the close f 0, need 0, have 4. Line failed
  attempts after s5: {1800: 5, 1820: 2, 1900: 2, 2020: 9, 2040: 6, 2060: 3, 2140: 2, 2160: 1, 2180: 1, 2200: 1, 2220: 4, 2240: 1, 2280: 4}.
* **The frontier position over training time** (training wall, probe pauses included): 2,020 0-389.0 s; 2,000 to 507.8 s; 1,980 to 589.2 s; 1,960 to 692.6 s;
  1,940 to 803.8 s; 1,920 to 920.9 s; 1,900 to 1,346.4 s; 1,880 to 1,443.5 s; 1,860 to 1,555.3 s; 1,840 to 1,683.6 s; 1,820 to 2,125.9 s; **1,800 from
  2,125.9 s to 4,770.6 s (44.1 minutes, six attempts)**; 1,780 from 4,770.6 s to the end of training (about 4,793 s).
* **Strip clear rates while training** (strip-region episodes at the pointer, per 100 in completion order): 2,020 0.56 (135); 2,000 0.48 (25); 1,980 0.83 (12);
  1,960 0.67 (15); 1,940 0.61 (18); 1,920 0.65 (17); 1,900 0.59 (103); 1,880 0.59 (17); 1,860 0.82 (17); 1,840 0.47 (19); 1,820 0.57 (90); **1,800 0.42
  (857: 0.23, 0.38, 0.47, 0.42, 0.39, 0.46, 0.42, 0.51, 0.51 (last 57); last 79 at 0.51)**; **1,780 (the strip at the close) 0.50 (4 episodes; the last 79 are
  not available, only 4 exist)**.
* **Throughput by pointer** (policy transitions/s per rollout, median [min, max], rollouts): 2,020 416.6 [283.4, 750.5] (28); 2,000 514.9 [81.3, 584.5] (6);
  1,980 436.4 [85.1, 545.5] (3); 1,960 480.9 [80.1, 617.4] (5); 1,940 476.7 [80.8, 610.0] (4); 1,920 546.1 [62.6, 641.9] (5); 1,900 566.7 [66.4, 978.8] (33);
  1,880 374.3 [66.1, 510.1] (3); 1,860 513.5 [71.5, 671.8] (5); 1,840 553.9 [68.5, 766.2] (7); 1,820 536.9 [57.7, 869.8] (27); 1,800 561.3 [57.6, 873.0] (259);
  1,780 319.0 [58.6, 579.4] (2). Session median 547.8 transitions/s (s4: 440.2). The low minima are the rollouts that contained an attempt's pause.
* **Periodic checkpoints** (H2 alignment: 5,745,536 + j x 102,400): `ckpt_005847936` (2,020), `005950336` (1,960), `006052736` and `006155136` (1,900),
  `006257536` and `006359936` (1,820), `006462336` ... `007691136` (1,800, thirteen): **19 periodic** (j = 1..19), plus `ckpt_005745536` (initial, 2,020) and
  `final` (7,726,976, 1,780): 21 checkpoints, each pinned (`checkpoint.json`) and re-checked by verify-run.

## 6. The frozen final policy (close audit), paired with the earlier audits and the tape

Audited landings 2,128, 1,966 and 1,694 (every landing behind the pointer 1,780 plus the first beyond it, decision R8); tick 0 descriptive. Final weights
`policy.pth` `f3e0dc3257e03ed2...`. The sticky labels (`m9|g2|reach|<landing>|<k>`) and the audit action keys carry no session component: s5's 20 sticky
episodes at each landing draw the same masks and uniforms as s1-s4's and the tape's first 20 keys (a paired measurement under different weights).

| start | tape (keys 0-19) | s1 | s2 | s3 | s4 | **s5** | s5 endings | B |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| **2,128** | 7 (p_hat 0.490 over 200) | 8 | 13 | 15 | 14 | **17 / 20** | 17 clears, 2 falls, 1 horizon | **15** |
| **1,966** | 2 (p_hat 0.050 over 40) | not audited | 3 | 9 | 13 | **12 / 20** | 12 clears, 7 falls, 1 horizon | 10 |
| **1,694** | 0 (p_hat 0.000 over 40) | not audited | not audited | not audited | not audited | **10 / 20** | 10 clears, 9 falls, 1 horizon | 10 |
| tick 0 | | | | 0 | 0 | 0 / 20 | 20 horizon | |

Non-sticky clears of the final policy (reported only): **unperturbed** 2,128 17 / 20 (s4: 17; s3: 13), 1,966 5 / 20 (s4: 8; s3: 6), 1,694 5 / 20;
**deterministic** 2,128 CLEAR (2,354 ticks, 10 targets, verified; s4: horizon), 1,966 no clear (3,600-tick horizon, 8 targets; s4: fall), 1,694 no clear
(horizon, 7 targets); tick-0 deterministic no clear (horizon).

Per key k = 0..19 (c clear, f fall, h horizon):

```
2,128   tape  hfchfhccchfhchfchhcf   7
        s1    fhfcfcfcffffcffcfccc   8
        s2    cfccfcfccccfcfcfhccc  13
        s3    ffcccccccccffcfccccc  15
        s4    cccccccccccfcfcffcff  14
        s5    ccccccccfchccccfcccc  17
1,966   tape  fffffffhfffffffchffc   2
        s2    fcfffffffffffffcffcf   3
        s3    cfhccchccfcffcfcfffh   9
        s4    fccfccfccfccccchcfcf  13
        s5    fccffchcfccfcccccffc  12
1,694   tape  hhhfffffhffffffffffh   0
        s5    fffchcfcfccfcfcccfcf  10
```

At 2,128: s5 vs s4 on identical keys: both clear 12, s4 only 2, s5 only 5, neither 1; s5 vs s3: both 12, s3 only 3, s5 only 5, neither 0; s5 vs s2: both
11, s2 only 2, s5 only 6, neither 1; s5 vs s1: both 7, s1 only 1, s5 only 10, neither 2; s5 vs the tape: both 5, tape only 2, s5 only 12, neither 1. At 1,966:
s5 vs s4: both 9, s4 only 4, s5 only 3, neither 4; s5 vs s3: both 5, s3 only 4, s5 only 7, neither 4; s5 vs s2: both 2, s2 only 1, s5 only 10, neither 7; s5 vs
the tape: both 2, tape only 0, s5 only 10, neither 8. At 1,694: s5 vs the tape: both 0, tape only 0, s5 only 10, neither 10.

* **Rule outcome PASS:** D_5 = 1,694 (17 >= 10 at 2,128; 12 >= 10 at 1,966; 10 >= 10 at 1,694; 1,473 not audited), R_5 = 1,694 (17 >= B = 15 at 2,128; 12 >= 10;
  10 >= 10). PASS needs R <= 1,966. `D/R_if_every_claimed_clear_were_verified` the same (claimed = verified at every landing). `route_mastered_ticks` 632
  (= 2,326 - R). **Reported, never deciding:** R_unperturbed = 2,128 (17 >= 15 at 2,128, 5 < 10 at 1,966); the deterministic episode cleared from 2,128 only;
  FRONTIER_BACKED true; tick 0 0 of 20. The 1,694 result is one clear above the bar (10 of 20), from a landing 86 ticks beyond the final pointer 1,780; no
  training episode started earlier than tick 1,783.
* Value calibration (reported only; start V against the realised mean return of the 20 sticky episodes): 2,128 V +5.68 against +8.45 (gap -2.78, pessimistic;
  s4: +1.80), start entropy 3.907 nats (91.4 % of 4.2767); 1,966 V +1.74 against +4.88 (gap -3.14; s4: -6.02), entropy 4.001 (93.6 %); 1,694 V +3.62 against
  +4.08 (gap -0.46), entropy 3.426 (80.1 %).
* Entropy per rollout (fraction of maximum): 84.7 % after s5's first update, minimum 80.7 % (rollout 183), maximum 88.0 % (rollout 373), **85.2 % at the end**
  (s4 ended at 85.7 %); explained variance 0.35 -> 0.72 at the end (median 0.57, range -0.11 to 0.94); median approx_kl 0.0109; recent-episode mean return 4.92
  in the first rollout, 4.82 in the last.

## 7. Resources against the caps

| resource | peak / used | cap |
| --- | ---: | ---: |
| session clock | 5,811.6 s | 8,700 s |
| training wall | 4,803.8 s | 4,800 s (the registered valid end) |
| native ticks (session) | 10,123,907 (per phase in section 3) | per phase |
| policy transitions (this session) | 1,981,440 | 3,072,000 |
| main process private memory | 1,648.9 MB (sampler; the clock's own reading 1,652.9 MB) | 3,072 MB |
| process tree private memory | 6,671.1 MB | 9,216 MB |
| process tree working set | 2,454.2 MB | 4,096 MB |
| lowest system available memory | 5,361.3 MB | at least 1,024 MB |
| lowest system commit free | 11,044.2 MB | at least 2,048 MB |
| BattleShip processes (peak) | 10 (the external sampler: 415 of 727 session-window samples at 10) | 10 |
| memory breach | none (1,155 samples at 5 s) | |

**The machine.** A read-only external sampler (10 s, outside the repository; each sample appended and the file closed at once) ran from 03:56:31Z to the end
of the post-run checks, and a file-free 3 s watch (stdout only, re-armed every 29 minutes) ran alongside it. **No `node` and no Playwright process appeared at
any sample or any watch poll, at any time**, Part B and the session included; no process other than the session's own python (pid 38104, up to about 1.0 GB
private) reached 1,000 MB. Lowest free physical memory in the session window 5,659 MB (08:30:31Z), lowest commit free 11,410 MB (same sample). The other Claude
Code sessions in the desktop app were all idle (`isRunning` false at 03:55Z, 06:08Z and after the run; three idle claude-code processes besides this
session's); the latest activity of any of them was at 03:38:59Z, before Part B, and it was unchanged after the run, so none ran BattleShip or any other
project during this session. No application was closed.

## 8. Integrity, evidence and verification

| check | result |
| --- | --- |
| verification | 122 / 122 exact; every clear counted in a registered measure replayed (the 39 audit sticky clears: 17 at 2,128, 12 at 1,966, 10 at 1,694); 20 training clears, 35 probe clears and 28 diagnostics exact |
| `verify-run --session 5` (against `runs/m9_g3/s4` and the chain s1-s4; before any copy; output `logs/m9_g3_s5_run/verify_run.json`, copied to `derived/`) | **`ok: true`, 0 problems**: metadata 2,128 files / 5,369 JSONL lines, 0 failures; 21 checkpoints with pins and g3 identity; training 2,623 / probes 666 / drift 5 / audit 144 records re-derived; resume checks cross-checked (previous_sessions equal to s4's record, 4 rows; inputs = s4's final state; initial checkpoint `ckpt_005745536` members = s4's final members `366f9d86...` / `38c940b7...`); chain ok over 4 sessions; frontier rebuilt from the records = the log (pointer 1,780, 12 moves, 21 attempts, 41 deferred); tape recorded at the open as `resume.inputs`, equal to the registered reuse, pinned; rule recomputed PASS / 1,694 / 1,694 = recorded; line recomputed CONTINUE = recorded; `inexact` [], `tier0_without_replay` 0. Re-run after the copies into `launch/` and `derived/`: `ok: true` again, identical apart from its timestamp (`verify_run_after_copies.json`) |
| drift | 5 of 5 (no tape drift) |
| protected trees | the eleven (rd1 166, rd2 62, rd3 77, rd4 93, m9_g1 2,740, m9_g1_eval 1,393, m9_g2_s1 9,779, m9_g3_s1 4,935, m9_g3_s2 4,478, m9_g3_s3 3,779, **m9_g3_s4 3,486**) equal their D: increments at both preflights, at the close, and after the backup by the tool (`trees_state(5)` after the backup: all eleven ok with the registered or discovered facts, `post_trees_tool_check.txt`) and the independent re-hash (0 missing / 0 extra / 0 bad each, `post_trees_independent_check.txt`) |
| write guard, provenance | no write under any other `runs/` tree, `rl/` or `docs/` during the session; 0 provenance violations; `leftover_processes.json` empty |
| constraints | no RNG seed inspected, logged, controlled, compared or hashed (keyed sha256 draws only); process restart was the reset for every episode; P1 / P2 PASS (the submit / consume / input-tick contract); the submitted canonical words are the replay truth (122 / 122 exact); every start a prefix of the agent's own two verified rd4 routes; no fixture, TAS or recording read; no hardcoded route or waypoint; no native, decomp or submodule change |

**Evidence.** `runs/m9_g3/s5/` (Git-ignored): after the copies (`logs/m9_g3_s5_run` -> `launch/` except the two outputs, the whole of `logs/m9_g3_s5_prep/` ->
`launch/prep/` (byte-equal, `diff -rq` clean), the snapshot record and its verify JSON -> `launch/`, `verify_run.json` and `report.json` -> `derived/`)
**4,302 files, 504,067,346 bytes**. Increment **`D:\BattleShip_runs_backup\2026-10-09_incr_m9_g3_s5`**, manifest sha256
**`2e632bbfcc09f6f1c66b945d0276dbed813e6966275c130d158ac6925bda28ef`**: tool backup PASS (4,302 / 504,067,346, 0 hash mismatches, 08:56:32Z); separate tool
verify `--source runs/m9_g3/s5` PASS (08:56:40Z, `verification.json` PASS, `source` = `runs\m9_g3\s5`); independent `independent_increment_check.ps1`: checked
4,302, missing 0, extra 0, bad 0, PASS. **Total `runs/` coverage: 444,367 source files, 0 uncovered, 17 increments** (`post_coverage.txt`; 440,065 + 4,302).
**Discovery for session 6** (`next_session_discovery.txt`): `unregistered_predecessors(6)` = []; `predecessor_tree(5)` = (`m9_g3_s5`, `2026-10-09_incr_m9_g3_s5`,
4,302 files, 504,067,346 bytes, manifest `2e632bbf...`, discovered from the increment's verification record, no record problem); `trees_for(6)` = the eleven +
`m9_g3_s5`; before this record existed, `predecessor_doc_problems(6)` named only the missing s5 results record. Post-backup logs live in `logs/m9_g3_s5_run/`,
outside the increment.

**The saved state for a later session** (`session/final_state.json` sha256 `5849fbd382240741a9a8acd57a64f4ce4adff3f833c4ced84ade0d552b0f87e8`; a session 6 is
permitted by the line rule, needs its own Part B and its own approval):

| file | sha256 |
| --- | --- |
| `training/checkpoints/final/model.zip` (1,111,718 bytes) | `382dde881fb6618bbcedc9bc68e0fcce4f9f050167fd6910cb32d930fee0028a` |
| its `policy.pth` member | `f3e0dc3257e03ed2ea1dbba0d68ffb53e7b85dd9606538b44f1d896203e76ffc` |
| its `policy.optimizer.pth` member (15,070 updates; Adam step 150,700 on 12 parameters) | `e3a78f5b4f6792639f50c80bd5ec4dd3f187330f3001464c514e4c579dbcd861` |
| `training/checkpoints/final/curriculum_state.json` (14,948 bytes; pointer 1,780; f 0 / need 0 / have 4; sessions [1, 2, 3, 4, 5]; num_timesteps 7,726,976; next_episode 17,100; attempt_counter 67) | `147467caec3847b922026ea943f4b72c1893aec0a2c6e998a45e12624a1e3400` |
| `input/tape_baseline.json` | `81fa52c21078b2c2...` (content `d915fab9...`) |
| `session/line.json` (rows s1-s5) / `session/rule.json` | `7f2387a8a8938b23...` / `5a029aa5f65fd121...` |
| line contract / next session seed | `90eac1a6...` / 1006 |

## 9. Departures and notes

* **Two step-mismatch records** (`session/failures/step_x_w05.json.gz`, 07:30:49Z; `step_x_w01.json.gz`, 08:18:48Z), both `no_episode`, both from the
  probe runner's known race (the one recorded for s3), this time inside RE-CHECK runs: a queued step reached a slot whose re-check episode had just been
  closed because the re-check was decided. w05 = attempt 51's abandoned `probe-1940-1-1966-17` (tau 1,966 + 193 policy ticks = 2,159 = the preserved tail's
  last consumed tick + 1; re-check already `passed`); w01 = attempt 66's abandoned `probe-1800-5-1966-15` (1,966 + 143 = 2,109; re-check already failed
  fast). Each re-check run sent exactly one step more than it ticked; the tails are 48 contiguous replies with input tick = consumed tick + 1; no native call
  was made for the failing command; abandoned episodes count in no test, attempt, spacing, training statistic, audit, rule or line measure; verify-run clean.
  Not a replay or determinism mismatch (`logs/m9_g3_s5_run/s5_step_mismatch_explanation.md`, copied into `launch/`). Reported, not acted on.
* **The close phase took 561.9 s against the 300 s figure in `WALL_CAPS_S`** (projected 563.1 s in the approval's budget block). The close is not
  clock-enforced (the resume-k record, section 5); the session clock total (5,811.6 s) stayed far inside the 8,700 s cap and nothing was marked. Reported as a
  fact, not acted on.
* **Probe share.** 21 attempts (14 with re-checks) took 1,094.2 s of the 4,800 s training wall (22.8 %; s4: 125.9 s for 4 attempts) and 2,102,518 probe
  ticks; training transitions were 1,981,440 against s4's 1,990,876. Reported as a fact.
* **26 stale staging events** (episodes staged at the pointer before a move that finished after it; `training/stale.jsonl`). Recorded by design; s2 had 24.
* **The launch shell.** The launcher was run from the Git Bash shell of this unattended session's tool, which returns once `Start-Process` has started the
  detached, hidden python (the same form as s1-s4). That shell was not an interactive terminal that could be kept open; the detached process ran to
  completion by itself (`state.json` `done`, the process gone, stderr empty).
* **The date** (header): Part B started on 2026-10-09 local, so every dated artifact carries 2026-10-09 although the UTC times are on 2026-10-10.
* No pre-launch fix, no tool copy and no edit: the four generic tools ran as found; no tracked file was modified; nothing was staged; no application was closed.

## 10. What this does and does not say

* It says: resumed from s4's exact final state, a fifth 80-minute session of the same recipe under the same frontier rule moved the pointer twelve strips,
  2,020 -> 1,780 (12 of 21 attempts moved; the pointer held at 1,800 for 44 minutes before its last move), and produced a frozen policy that clears **17 of
  20** sticky episodes from 2,128 (s4: 14; tape 7 on the same keys), **12 of 20** from 1,966 (s4: 13; tape 2) and **10 of 20** from 1,694 (tape 0; not audited
  before). This meets the reach bar at 2,128 again (s3 had R_3 = 2,128; s4 missed it by one) and both bars at 1,966 and 1,694: R_5 = D_5 = 1,694, hence PASS
  under the per-session rule, and the line continues (END_NO_PROGRESS avoided: D_5 = 1,694 is earlier than D_3 = 2,128).
* It also shows, as facts and not decisions: the 1,694 count sits exactly on the bar (10 of 20) and comes from a landing beyond the final pointer; the
  deterministic episodes from 1,966 and 1,694 did not clear; R_unperturbed stayed 2,128 (unperturbed 5 of 20 at 1,966 and at 1,694); tick 0 0 of 20, so no
  tick-0 policy is claimed; the line's END_SUCCESS needs D <= 1,473.
* **For session 6** (`line_consequence(6, rows)` on s5's recorded rows, computed read-only after the run, `logs/m9_g3_s5_run/session6_line_consequence.txt`):
  k = 6 is the END_BUDGET_1694 session. NULL, D = 2,128, D = 1,966, or an INCOMPLETE that counts -> END_BUDGET_1694 (the line ends); D = 1,694 -> CONTINUE;
  D <= 1,473 -> END_SUCCESS; an INCOMPLETE that does not count -> CONTINUE; INVALID -> SUSPENDED. The approval of any session 6 computes the table again.
* It does not say anything about a session 6, other seeds or budgets. No s6 was run; whether to prepare one is the user's decision.

## 11. git status at the end

HEAD = origin/main = `86773666a7d7c6e0563e127cf2688ea32f14b125`; no commit, push, branch or pull request; nothing staged; `git diff --check` clean;
`git status --porcelain --untracked-files=all` shows only new files:

```
?? docs/rl_m9_g3_s5_approval.json
?? docs/rl_m9_g3_s5_results_2026-10-09.md
```

Git-ignored and therefore not shown: `logs/m9_g3_s5_prep/` (Part B), `logs/m9_g3_s5_run/` (snapshot, approval, preflight, launch, wait and post-run logs) and
`runs/m9_g3/s5/`. With this record in place, `predecessor_doc_problems(6)` = [] and the record is the only accepted `rl_m9_g3_s5_results` entry (checked
read-only after writing it).
