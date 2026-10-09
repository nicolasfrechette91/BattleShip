# M9-g3-s4 results (2026-10-09)

**Registered outcome: INCONCLUSIVE** (`m9_g3_s1_rule_v1`, the per-session rule, sha256 `dea9965a3989bce5...`): **D_4 = 1,966**, **R_4 = none**. The
frozen final policy cleared **13 of 20** sticky episodes from the landing state 1,966 (13 clears, 6 falls, 1 horizon, all 13 verified), meeting the depth bar
of 10 there for the first time in the line, and **14 of 20** from 2,128 (14 clears, 6 falls, all verified). The depth chain therefore reaches 1,966
(2,128: 14 >= 10; 1,966: 13 >= 10; 1,694 not audited, by design, decision R8). The reach chain fails at its first link (2,128: 14 < B = 15), so R is none.
PASS needs R <= 1,966, so the outcome is INCONCLUSIVE (D <= 2,128). The rule's reason string, as recorded: "D_1 = 1966 <= 2128; R_1 = None" (the rule text
names the per-session subscript 1; this is session 4's own result). **Line outcome: CONTINUE** (`m9_g3_line_rule_v1`, `d9d82885703c016d...`): k = 4,
counted sessions [1, 2, 3, 4], depths [none, 2,128, 2,128, 1,966], "session 5 is proposable, with its own approval". This is the row the approval's computed
`line_consequence` registered for "INCONCLUSIVE or PASS with D = 1966" before the run: the END_BUDGET_1966 milestone (D_4 at or before 1,966) is met and the
line does not end. Nothing follows automatically: **no s5 was run or authorised**. One session, one run, once; nothing was retried, extended or repaired.
Every number below is read from `runs/m9_g3/s4/` and recomputed by `verify-run` (section 8).

Scope label: *M9-g3-s4: the fourth session of the g3 line, RESUMED bit for bit from g3-s3's recorded final state (model, optimizer, frontier pointer 2,020 and
spacing f 5 / need 320 / have 171, episode and attempt counters), under the unchanged replenishing controlled frontier rule `m9_g3_frontier_v1`, the same recipe
(observation v3, reward v2, sticky p = 0.25, entropy 0.01, 80 minutes, 4 + 6 slots), the reused g2-s1 tape baseline by digest, and the same keyed audit draws as
s1, s2 and s3 (a paired measurement, not a replay); progress measured as D and R at landing states under the registered rules; no claim of a tick-0 policy.*

## 1. What was run

| item | value |
| --- | --- |
| tree | HEAD = origin/main = remote `main` = `b1a9a9387d11141482e3a28dca16b9e783f791db` ("reach bar met, one clear short at the left floor", carrying the s3 approval `3e3cb9dc...` and the s3 results record `f9fd80f7...`); no tracked file modified at any point; nothing staged; g3 source fingerprint **`15ddbb84932aa658`** |
| authorisation | the user's unattended-session message of 2026-10-09, Part C, quoted verbatim in the approval (`authorised_on` 2026-10-09; `logs/m9_g3_s4_prep/launch_2026-10-09/s4_authorisation_part_c_2026-10-09.txt`, sha256 `dae05b51...`), including "Acknowledged line consequence: this is the END_BUDGET_1966 session" |
| source snapshot | `D:\BattleShip_source_snapshots\2026-10-09_m9_g3_s4` (`--session 4`; `log_dirs` [logs/m9_g3_prep, logs/m9_g3_s2_prep, logs/m9_g3_resume_tools, logs/m9_g3_resume_k_prep, logs/m9_g3_s4_prep]); PASS, 369 files, 4,011,254 bytes, 154.2 s, `snapshot.json` sha256 **`bc898b9ce7862742ee5d386bdd5fe898cc17182e2cfcb820620d08f834899f7d`**; tool verify PASS (16:08:34Z: 369 files, 0 mismatches, 0 extra, 0 external mismatches, executable equal); independent PowerShell re-hash checked 370, bad 0, exe equal, PASS |
| approval | NEW `docs/rl_m9_g3_s4_approval.json`, sha256 **`847510542076c6463cdda8a180ffd245efa49beb6fb119fe8186bef18c21d8c1`**, written 16:08:55Z-16:12:19Z by `logs/m9_g3_resume_tools/write_approval.py --session 4` (unchanged, sha256 `e652f04e...`) from `identity(4)` at the final HEAD: session 4; the ten trees; the D: folders; `resume_inputs` (expect {`d4ec82ab...`, `4a8caf44...`, `81fa52c2...`}, members `6e4e297f...` / `c09ab689...`, counters 3,754,660 / 7,320 / Adam 73,200 x 12, `previous_sessions` = the s1, s2 and s3 rows read from s3's `line.json` and cross-checked along the chain s1 -> s2 -> s3, s3's tree facts 3,779 / 429,781,233 / `338d4939...` discovered from its increment); the snapshot above; the COMPUTED `line_consequence` (B12); the authorisation text verbatim (25 lines, equal to the file); `approval_status(4)` = approved |
| full preflight (once) | `python -B -X utf8 rl/m9_g3_session.py preflight --session 4`, 16:12:35Z to 16:34:45Z, **exit 0, `ok: true`, `problems: []`**: unit 29 / 29 (1,042 s), rule self-test PASS, approval "approved", snapshot "recorded, PASS and equal to the repository", ten trees ok, coverage 436,579 / 0 / 15, readiness 7,568.6 MB available / 18,955.6 MB commit free; the only new file the approval |
| launch | `powershell -NoProfile -ExecutionPolicy Bypass -File logs/m9_g3_resume_tools/launch_detached.ps1 -Session 4 -Repo ...` (sha256 `53f675ad...`) from Git Bash: **pid 24972 at 2026-10-09T16:35:08Z**, `python -B -u -X utf8 rl/m9_g3_session.py run --session 4`; its own preflight ran first (unit 29 / 29 in 1,031 s; readiness 7,334.5 MB / 18,826.8 MB); the session clock started 16:59:17Z; the process exited by itself (state `done` at 18:32:39Z); `session_stderr.txt` empty; waited with `wait_session.py --session 4` (done, exit 0, 117.7 min) |
| session clock | **5,602.1 s (93.4 min)** of the 8,700 s cap |
| executable | `build-us/Release/BattleShip.exe` `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee`, unchanged at the close; runtime files and frozen configuration equal their pins |

## 2. Part B (B0-B13), all held before any native tick

Logs: `logs/m9_g3_s4_prep/launch_2026-10-09/` (inside the s4 snapshot's file set; `partb_summary.md` there), `logs/m9_g3_s4_prep/final/` (the three passes).
Conditions: `docs/rl_m9_g3_resume_k_prep_decisions_2026-10-08.md` section 8 for k = 4, with the values of `docs/rl_m9_g3_progression_fix_2026-10-08.md`
section 10 and of the user's message. No preparation round (B13).

| # | result |
| --- | --- |
| B0 | HEAD = origin/main = `git ls-remote origin refs/heads/main` = `b1a9a93` (carrying the s3 approval and results record); `git status --porcelain --untracked-files=all` empty; nothing staged; `git diff --check` clean; fingerprint `15ddbb84932aa658` (per-file digests equal the progression-fix record; all ten g3 modules `i/lf w/lf`) |
| B1 | `three_passes.py --session 4` WITHOUT `--allow-git-gate` (13:41:02Z-15:37:46Z): **THREE_CONSECUTIVE_PASSES**, exit 0; unit **29 / 29** x 3 (2,034.6 / 1,004.8 / 1,026.3 s), e2e PASS digest **`078f46c445d8adc5`** x 3 (993.8 / 960.2 / 983.3 s), fingerprint unchanged before and after every pass; then, one after another (15:38:02Z-15:53:48Z): rule self-test PASS (s1 `dea9965a3989bce5`, line `d9d82885703c016d`); g1 evaluation 29 / 29 (73 s); g2 29 / 29 (502 s); g1 unit 62 / 63 with ONLY `identity_names_every_registered_pin` failing (367 s; its FAIL line identical to s3's); fingerprint after the suites unchanged; git status empty at the suites' start and end |
| B2 | g3 contract `4cd1deae...`, line contract `90eac1a6...`, frontier `60e174a6...`, s1 rule `dea9965a...`, line rule `d9d82885...`, g2 `8dfd44c6a8b7e319` / `1aadc7a6b2ff85bd`, g1 `6958857ed2dfd1c5`: all equal; `G.PPO` = s3's saved `curriculum_state.ppo` |
| B3 | executable `30a3913b...` (= s3's `final_state.executable_sha256`); pins; tape `81fa52c21078b2c2 / d915fab920554774` pinned, measured with the executable now; CVars absent or zero; status table verified; `T_clear` 2,326 / `5eccd4e2d5d77b25`, `T_t` 2,315 / `de1228be4146b720` |
| B4 | s3's saved state byte-identical to its records: `model.zip` `d4ec82ab...` (1,110,750 B), members `6e4e297f...` / `c09ab689...` (recorded = now); `curriculum_state.json` `4a8caf44...` (7,533 B; pointer 2,020; f 5 / need 320 / have 171; sessions [1, 2, 3]; num_timesteps 3,754,660; next_episode 11,289; attempt_counter 42); tape `81fa52c2...`; `final_state.json` `910d503f...` (session 3; counters 3,754,660 / 7,320 / Adam 73,200 x 12; next seed 1004; line CONTINUE); `line.json` `70f4ab47...` rows = s1, s2, s3; `rule.json` `4e994acb...`; `predecessor_problems(4)` = []; `unregistered_predecessors(4)` = []; chain `sessions_checked` 3; `predecessor_doc_problems(4)` = [] (the s1, s2, s3 approvals and results records found by the exact rule); `runs/m9_g3/s3` = its increment `2026-10-09_incr_m9_g3_s3` (manifest `338d4939...`, discovered, no record problem) by the tool (tenth tree ok) AND the independent re-hash (3,779 checked, 0 missing / 0 extra / 0 bad) |
| B5 | the ten trees of `trees_for(4)` ok with the registered or discovered facts (tool, dry run) and PASS by the independent re-hash (rd1 166, rd2 62, rd3 77, rd4 93, m9_g1 2,740, m9_g1_eval 1,393, m9_g2_s1 9,779, m9_g3_s1 4,935, m9_g3_s2 4,478, m9_g3_s3 3,779; 0 / 0 / 0 each); coverage 436,579 files, 0 uncovered, 15 increments |
| B6 | `preflight --session 4 --skip-unit` (15:54:30Z-16:02:03Z): exit 1 with exactly `["no approval record at docs\rl_m9_g3_s4_approval.json (the session is not authorised)"]`; stderr empty; readiness passed (7,930.7 MB / 18,855.8 MB; C: 99.7 GiB, D: 1,648.0 GiB) without closing anything |
| B7 | pessimistic 7,780 s of 8,700 s (fits); the close projected 501.1 s over ten trees (3,328,837,109 B), not clock-enforced; pessimistic total with that close 7,981.1 s, fits |
| B8 | no `BattleShip.exe` anywhere (before the dry run, at 16:04:56Z, before the launch); no tracked, staged or replay-browser change (`replay/_local` untouched since 2026-10-03); readiness above the thresholds at every reading; `node` processes: see section 7 |
| B9 / B10 | section 1 (snapshot first, then the approval; every Part B log written before the snapshot; nothing written under any directory of the snapshot set afterwards; later logs in `logs/m9_g3_s4_run/`) |
| B11 | the four generic tools as found (sha256 unchanged since s3, `b8_b11_machine_and_paths.txt`); `independent_increment_check.ps1` `98abb0b9...`; `logs/m9_g3_s4_run`, `runs/m9_g3/s4`, the s4 approval, any `rl_m9_g3_s4` docs entry, the s4 snapshot and any s4 increment absent before Part C |
| B12 | `line_consequence(4, [s1, s2, s3])` computed into the approval: NULL -> END_BUDGET_1966; D 2,128 -> END_BUDGET_1966; D 1,966 / 1,694 -> CONTINUE; D <= 1,473 -> END_SUCCESS; INCOMPLETE counting -> END_BUDGET_1966; INCOMPLETE not counting -> CONTINUE; INVALID -> SUSPENDED; reachable line ends: END_BUDGET_1966, END_SUCCESS, SUSPENDED |
| B13 | k = 4: s3 DISCOVERED from exactly one increment `2026-10-09_incr_m9_g3_s3` (PASS record naming `runs/m9_g3/s3`, manifest at the recorded digest); s1, s2 registered; `unregistered_predecessors(4)` = [] |

**The s3 step-mismatch records (checked read-only before Part C).** `runs/m9_g3/s3/session/failures/step_x_w04.json.gz` and `step_x_w01.json.gz` were written by
`rl/m9_worker.WorkerCore.step` (`MismatchError("no_episode")`), which refuses a `step` command reaching a worker with no episode, before any native call,
and preserves the worker's ring of the last 48 replies. In `rl/m9_g2_probe.ProbeRunner.run` (used unchanged by g3), a non-final step of a strip episode
is queued in `need`; a later event of the same polled batch decides the strip test `failed` and `_cancel` closes every active strip slot; the queued step
is then sent to a slot already closed. The runner ignores the reply (no active episode on the slot; per-slot replies arrive in command order, before any
new episode there). The records match exactly: attempt 40 (worker 4) sent 13,049 steps for 13,048 ticks, its preserved tail ends at consumed tick 2,194 =
`probe-2020-3-strip-17` (tau 2,024 + 171 policy ticks at abandonment); attempt 41 (worker 1) sent 8,676 for 8,675, tail ends at 2,183 =
`probe-2020-4-strip-14` (2,033 + 151). Both are episodes abandoned after the strip test was decided; no native tick ran for the failing command, nothing is
a replay or determinism mismatch, and no counted episode or registered measure depends on them. Recorded and continued
(`logs/m9_g3_s4_prep/launch_2026-10-09/s3_step_mismatch_explanation.md`). s4 preserved no such record (it has no `session/failures/` directory).

## 3. Phases

| phase | wall (cap) | native ticks (cap) | result |
| --- | ---: | ---: | --- |
| open | 0.13 s (60) | 0 | the three inputs copied and checked against the APPROVAL's digests, the H6 predecessor assertions, the resume compatibility check; `resume_source`: expect from the approval, previous_sessions from `runs/m9_g3/s3/session/line.json`, final state from s3's `final_state.json`, chain checked over s1, s2, s3 |
| P1 lineages | 23.3 s (240) | 13,923 (60,000) | PASS, shared prefix 2,298 |
| P2 staging equivalence | 38.6 s (120) | 31,998 (60,000) | PASS |
| T0 drift check | 12.4 s (240) | 14,440 (60,000) | PASS: 5 of 5 tape keys at 2,128 reproduced the table (h, f, c, h, f) and the measuring session's native action digests |
| training | 4,802.9 s (4,800) | 8,506,475 (20,000,000) | valid end: **wall cap**; **1,990,876 policy transitions** this session by the counter (1,990,875 counted by the vector env: one step ended by a lifecycle failure, section 9; cap 3,072,000), 388 rollouts, 3,880 PPO updates; prefix 6,316,027, policy 1,990,875, probes 199,573 ticks |
| close audit | 179.2 s (1,200) | 289,138 (3,000,000) | 103 of 103 planned episodes (landings 2,128 and 1,966: 20 sticky + 20 unperturbed + 1 deterministic each; tick 0: 20 sticky + 1 deterministic) |
| verification | 111.6 s (600) | 179,077 (1,500,000) | **72 of 72 replays exact** (tier 0: the 27 audit sticky clears; tier 1: 20 training clears; tier 3: 25 diagnostics); 0 skipped, 0 errors |
| close | 433.9 s (300, see section 9) | 0 | the ten protected trees equal their D: increments, no pin drift, no provenance or write-guard violation, metadata audit 1,720 files / 4,879 JSONL lines clean, no leftover process |

**Native ticks in the session: 9,035,051** (13,923 + 31,998 + 14,440 + 8,506,475 + 289,138 + 179,077). Lifecycle failures: 1 in training (arena, section 9);
stale staging events 0 (`training/stale.jsonl` empty).

## 4. The resume, bit for bit

| check | s3 final (recorded) | s4 | equal |
| --- | --- | --- | --- |
| copied `input/model.zip` | `d4ec82ab0851...` | `d4ec82ab0851...` (open.json `resume.inputs`; the file in `input/`, byte-equal to s3's final model) | yes |
| copied `curriculum_state.json`, `tape_baseline.json` | `4a8caf44...`, `81fa52c2...` | same | yes |
| model members at the open | `6e4e297f...` / `c09ab689...` | `resume.members` `6e4e297f...` / `c09ab689...` | yes |
| **initial checkpoint `ckpt_003754660` (`why` initial)** | | `policy.pth` **`6e4e297ff919d4ee074b54a7e7abe239263a4c9af94fe82d4390fc8379778fb2`**, `policy.optimizer.pth` **`c09ab68977d7dafd3295cd5e086132ec7c3e4108c7de29539d177bd5ce28f66a`** (H12 byte check at `_on_training_start`: `initial_members_equal_predecessor: true`); its model.zip `33b1caa7...` differs from s3's `d4ec82ab...` only in the `data` member (checked member by member), as designed | yes |
| counters | num_timesteps 3,754,660; `_n_updates` 7,320; Adam step 73,200 on 12 params | start_timesteps 3,754,660 -> final 5,745,536 (+1,990,876); updates 7,320 -> 11,200 (+3,880 = 388 rollouts x 10 epochs); Adam 73,200 -> 112,000 (+38,800 = 388 x 100) on all 12; resumed seed 1004 -> next 1005 | continuous |
| frontier carried | pointer 2,020; f 5 / need 320 / have 171; line_failed {2020: 5, 2040: 6, 2060: 3, 2140: 2, 2160: 1, 2180: 1, 2200: 1, 2220: 4, 2240: 1, 2280: 4}; next_episode 11,289; attempt_counter 42; sessions [1, 2, 3]; 14 moves 2,300 -> 2,020 | initial checkpoint pointer 2,020, spacing f 5 / need 320 / have 171; first s4 attempt n = 43 at 2,020 with a = 6, f 5 / need 320; lowest s4 episode `train-0011289`; final state sessions [1, 2, 3, 4], next_episode 14,341, attempt_counter 46 | continuous |
| previous_sessions | s1, s2, s3 rows | recorded at the open = s3's `line.json` rows (chain s1 -> s2 -> s3 checked); s4's `line.json` = [s1, s2, s3, s4 rows] | yes (verify-run `equal_to_predecessor_record: true`, `chain.ok: true`, 3 sessions) |

## 5. Training and the frontier

* Episodes 3,017: **1,508 clears (50.0 %)**, 1,177 falls, 332 horizon. By start region: strip 1,552 (570 clears, 36.7 %), near window 885 (558, 63.1 %),
  rehearsal 580 (380, 65.5 %). Native ticks per policy transition 4.27 (s3: 5.4); prefix share of training ticks 74.2 %. Staged starts 3,049; slot wait for a
  ready start 194.9 s (4.1 % of the training wall); 24 staged starts withdrawn for attempts; probe wall 125.9 s (2.6 %; 29.6-33.2 s per attempt).
* **The pointer did not move: 2,020 for the whole session** (0 to 4,793 s of training wall, 79.9 minutes; with s3's last 62.4 minutes, about 142 minutes at
  2,020 across the two sessions). The attempts at 2,020 since the s3 move: 9 (5 in s3, 4 in s4), all FAILED_STRIP.
* **Every attempt** (4; frozen snapshot, keyed strip starts and draws; "live" = clear rate of the 60 preceding counted strip outcomes at that pointer; no
  re-check ran, every attempt failed its strip test; wait = training wall since the previous trigger, or since the session start, with the deferred triggers
  in between (their `have`)):

| # | pointer | a | f / need / have | trigger (training wall) | live (n) | frozen strip test | re-check | result | wall | wait before it / deferred |
| ---: | ---: | ---: | --- | --- | ---: | --- | --- | --- | ---: | --- |
| 43 | 2,020 | 6 | 5 / 320 / 339 | 8 of 18 (533.6 s) | 0.37 (60) | 7 / 18 | - | FAILED_STRIP | 33.2 s | 533.6 s from the start (have 171 carried from s3); no deferred trigger before it |
| 44 | 2,020 | 7 | 6 / 320 / 361 | 8 of 19 (1,666.9 s) | 0.33 (60) | 2 / 13 | - | FAILED_STRIP | 29.6 s | 1,133 s; 9 deferred at 13, 32, 48, 118, 131, 184, 201, 221, 290 |
| 45 | 2,020 | 8 | 7 / 320 / 402 | 8 of 13 (2,837.9 s) | 0.33 (60) | 7 / 18 | - | FAILED_STRIP | 31.5 s | 1,171 s; 7 deferred at 38, 52, 82, 101, 117, 224, 297 |
| 46 | 2,020 | 9 | 8 / 320 / 425 | 8 of 11 (4,129.5 s) | 0.33 (60) | 1 / 12 | - | FAILED_STRIP | 31.4 s | 1,292 s; 7 deferred at 63, 211, 229, 249, 262, 298, 309 |

  After attempt 46: need 320, 12 deferred triggers (at have 16, 33, 43, 56, 73, 84, 100, 115, 127, 138, 152, 191); training ended at have 196. Totals: **0 MOVED,
  4 FAILED_STRIP, 0 BLOCKED_BY_RECHECK, 0 INTERRUPTED**; attempt yield 0.0 moves per decided attempt (s3: 0.143); **35 deferred triggers** (all at 2,020),
  4 acted-on triggers, 53 void windows. No HELD, no STALLED; spacing at the close f = 9, need 320, have 196. Line failed attempts after s4: {2020: 9, 2040: 6,
  2060: 3, 2140: 2, 2160: 1, 2180: 1, 2200: 1, 2220: 4, 2240: 1, 2280: 4}. Abandoned probe episodes after each decided test (not counted anywhere): 43: 2
  active; 44: 3 active + 2 staged; 45: 2 staged; 46: 1 active + 4 staged.
* **Trigger-to-test gap** (window rate minus frozen-test rate), attempts 43-46: +0.06, +0.27, +0.23, +0.64. Snapshot `strip_calibration_gap` per attempt:
  -0.68, +3.99, -1.28, +3.92.
* **Strip clear rates while training** (strip-region episodes at the pointer, per 100 in completion order): **2,020 0.37 (1,552: 0.29, 0.41, 0.40, 0.36,
  0.26, 0.40, 0.40, 0.34, 0.30, 0.36, 0.18, 0.40, 0.36, 0.42, 0.60, 0.42 (last 52); last 79 at 0.53)** (s3 at 2,020: 0.23 over 1,431).
* **The frontier position over training time:** 2,020 from 0 s to the end at 4,793 s; no move.
* **Throughput by pointer** (policy transitions/s per rollout, median [min, max], rollouts): 2,020 440.2 [93.5, 791.7] (388). Session median 440.2
  transitions/s (s3: 460.7).
* **Periodic checkpoints** (H2 alignment: 3,754,660 + j x 102,400): `ckpt_003857060`, `003959460`, ... `005700260`: **19 periodic** (j = 1..19, all at 2,020),
  plus `ckpt_003754660` (initial) and `final` (5,745,536): 21 checkpoints, each pinned (`checkpoint.json`) and re-checked by verify-run.

## 6. The frozen final policy (close audit), paired with the earlier audits and the tape

Audited landings 2,128 and 1,966 (every landing behind the pointer 2,020 plus the first beyond it, decision R8); tick 0 descriptive. Final weights
`policy.pth` `366f9d86247404d7...`. The sticky labels (`m9|g2|reach|<landing>|<k>`) and the audit action keys carry no session component: s4's 20 sticky
episodes at each landing draw the same masks and uniforms as s1's, s2's, s3's and the tape's first 20 keys (a paired measurement under different weights).

| start | sticky verified clears of 20 | endings | unperturbed | deterministic | tape p_hat (keys) / tape on keys 0-19 | B |
| ---: | ---: | --- | ---: | --- | --- | ---: |
| **2,128** | **14 / 20** (s3: 15; s2: 13; s1: 8) | 14 clears, 6 falls | 17 / 20 (s3: 13) | horizon, no clear (3,600 ticks, 9 targets; s3: horizon) | 0.490 (200) / 7 of 20 | **15** |
| **1,966** | **13 / 20** (s3: 9; s2: 3) | 13 clears, 6 falls, 1 horizon | 8 / 20 (s3: 6) | fall, no clear (2,250 ticks, 8 targets; s3: horizon) | 0.050 (40) / 2 of 20 | 10 |
| tick 0 | 0 / 20 (s3: 0) | 20 horizon | | no clear (horizon) | | |

Per key k = 0..19 (c clear, f fall, h horizon):

```
2,128   tape  hfchfhccchfhchfchhcf   7
        s1    fhfcfcfcffffcffcfccc   8
        s2    cfccfcfccccfcfcfhccc  13
        s3    ffcccccccccffcfccccc  15
        s4    cccccccccccfcfcffcff  14
1,966   tape  fffffffhfffffffchffc   2
        s2    fcfffffffffffffcffcf   3
        s3    cfhccchccfcffcfcfffh   9
        s4    fccfccfccfccccchcfcf  13
```

At 2,128: s4 vs s3 on identical keys: both clear 10, s3 only 5, s4 only 4, neither 1; s4 vs s2: both 11, s2 only 2, s4 only 3, neither 4; s4 vs s1: both 5,
s1 only 3, s4 only 9, neither 3; s4 vs the tape: both 5, tape only 2, s4 only 9, neither 4. At 1,966: s4 vs s3: both 6, s3 only 3, s4 only 7, neither 4;
s4 vs s2: both 2, s2 only 1, s4 only 11, neither 6; s4 vs the tape: both 0, tape only 2, s4 only 13, neither 5.

* **Rule outcome INCONCLUSIVE:** D_4 = 1,966 (14 >= 10 at 2,128; 13 >= 10 at 1,966; 1,694 not audited), R_4 = none (14 < B = 15 at 2,128). PASS needs
  R <= 1,966. `D/R_if_every_claimed_clear_were_verified` the same (14 and 13 claimed = verified). **Reported, never deciding:** R_unperturbed = 2,128 (17 >= 15 at
  2,128, 8 < 10 at 1,966); neither deterministic episode cleared (2,128: 3,600-tick horizon; 1,966: fall at 2,250); FRONTIER_BACKED true;
  `route_mastered_ticks` none.
* Value calibration (reported only): at 2,128 start V +7.72 against a realised mean return +5.91 (gap +1.80, optimistic; s3: -1.95), start entropy 3.647 nats
  (85.3 % of 4.2767); at 1,966 start V -0.12 against +5.89 (gap -6.02, pessimistic; s3: -3.17), entropy 3.915 (91.5 %).
* Entropy per rollout (fraction of maximum): 87.3 % after s4's first update, minimum 82.0 % (rollout 343), maximum 91.8 % (rollout 75), **85.7 % at the end**
  (s3 ended at 88.3 %); explained variance 0.39 -> 0.33 at the end (median 0.46, range -0.25 to 0.86); median approx_kl 0.0102; recent-episode mean return 3.88
  in the first rollout, 5.08 in the last.

## 7. Resources against the caps

| resource | peak / used | cap |
| --- | ---: | ---: |
| session clock | 5,602.1 s | 8,700 s |
| training wall | 4,802.9 s | 4,800 s (the registered valid end) |
| native ticks (session) | 9,035,051 (per phase in section 3) | per phase |
| policy transitions (this session) | 1,990,876 | 3,072,000 |
| main process private memory | 1,550.6 MB (sampler; the clock's own reading 1,543.1 MB) | 3,072 MB |
| process tree private memory | 6,702.3 MB | 9,216 MB |
| process tree working set | 2,642.5 MB | 4,096 MB |
| lowest system available memory | 6,025.5 MB | at least 1,024 MB |
| lowest system commit free | 12,155.7 MB | at least 2,048 MB |
| BattleShip processes (peak) | 10 (1,113 samples at 5 s) | 10 |
| memory breach | none | |

**External memory pressure.** A read-only sampler (10 s, outside the repository) ran from 13:40Z to 18:41Z, with a gap 13:46:02Z-14:16:40Z (its file was held
open by a monitor; samples in that window were not written), and a read-only 15 s hazard watch ran from about 14:17Z to the session's end and printed
nothing. During the session (launch 16:35:08Z to 18:33Z, 692 samples): **no `node` process at all**; the only process above 1 GB private was the session's
own python (pid 24972, up to about 1.55 GB); lowest free physical 6,024 MB (18:10Z), lowest commit free 12,160 MB (18:11Z). Earlier, during Part B pass 1
only (13:40:30Z-13:46:02Z): up to five `node` processes of another project's `npm run test:e2e` / Playwright run (largest 730 MB private, summed at most
974 MB), started 09:41:57 local, not by this session; none reached 1 GB; none was closed; none appeared in any later sample.

## 8. Integrity, evidence and verification

| check | result |
| --- | --- |
| verification | 72 / 72 exact; every clear counted in a registered measure replayed (the 27 audit sticky clears: 14 at 2,128, 13 at 1,966); 20 training clears and 25 diagnostics exact |
| `verify-run --session 4` (against `runs/m9_g3/s3` and the chain s1, s2, s3; before any copy; output `logs/m9_g3_s4_run/verify_run.json`, copied to `derived/`) | **`ok: true`, 0 problems**: metadata 1,726 files / 4,879 JSONL lines, 0 failures; 21 checkpoints with pins and g3 identity; training 3,017 / probes 61 / drift 5 / audit 103 records re-derived; resume checks cross-checked (previous_sessions equal to s3's record, 3 rows; inputs = s3's final state; initial checkpoint `ckpt_003754660` members = s3's final members `6e4e297f...` / `c09ab689...`); chain ok over 3 sessions; frontier rebuilt from the records = the log (pointer 2,020, 0 moves, 4 attempts, 35 deferred); tape recorded at the open as `resume.inputs`, equal to the registered reuse, pinned; rule recomputed INCONCLUSIVE / 1,966 / none = recorded; line recomputed CONTINUE = recorded; `inexact` [], `tier0_without_replay` 0. Re-run after the copies into `launch/` and `derived/`: `ok: true` again, identical apart from its timestamp (`verify_run_after_copies.json`) |
| drift | 5 of 5 (no tape drift) |
| protected trees | the ten (rd1 166, rd2 62, rd3 77, rd4 93, m9_g1 2,740, m9_g1_eval 1,393, m9_g2_s1 9,779, m9_g3_s1 4,935, m9_g3_s2 4,478, **m9_g3_s3 3,779**) equal their D: increments at both preflights, at the close, and after the backup by the tool (`trees_state(4)` after the backup: all ten ok with the registered or discovered facts, `post_trees_tool_check.txt`) and the independent re-hash (0 missing / 0 extra / 0 bad each, `post_trees_independent_check.txt`) |
| write guard, provenance | no write under any other `runs/` tree, `rl/` or `docs/` during the session; 0 provenance violations; `leftover_processes.json` empty |
| constraints | no RNG seed inspected, logged, controlled, compared or hashed (keyed sha256 draws only); process restart was the reset for every episode; P1 / P2 PASS (the submit / consume / input-tick contract); the submitted canonical words are the replay truth (72 / 72 exact); every start a prefix of the agent's own two verified rd4 routes; no fixture, TAS or recording read; no hardcoded route or waypoint; no native, decomp or submodule change |

**Evidence.** `runs/m9_g3/s4/` (Git-ignored): after the copies (`logs/m9_g3_s4_run` -> `launch/` except the two outputs, the whole of `logs/m9_g3_s4_prep/` ->
`launch/prep/` (byte-equal, `diff -rq` clean), the snapshot record and its verify JSON -> `launch/`, `verify_run.json` and `report.json` -> `derived/`)
**3,486 files, 411,903,655 bytes**. Increment **`D:\BattleShip_runs_backup\2026-10-09_incr_m9_g3_s4`**, manifest sha256
**`8bc072bad358a82580fd8fedc23c61087a8c69a66c4166ebed2e9f319cb7350c`**: tool backup PASS (3,486 / 411,903,655, 0 hash mismatches, 18:34:47Z); separate tool
verify `--source runs/m9_g3/s4` PASS (18:34:55Z, `verification.json` PASS, `source` = `runs\m9_g3\s4`); independent `independent_increment_check.ps1`: checked
3,486, missing 0, extra 0, bad 0, PASS. **Total `runs/` coverage: 440,065 source files, 0 uncovered, 16 increments** (`post_coverage.txt`; 436,579 + 3,486).
**Discovery for session 5** (`next_session_discovery.txt`): `unregistered_predecessors(5)` = []; `predecessor_tree(4)` = (`m9_g3_s4`, `2026-10-09_incr_m9_g3_s4`,
3,486 files, 411,903,655 bytes, manifest `8bc072ba...`, discovered from the increment's verification record, no record problem); `trees_for(5)` = the ten +
`m9_g3_s4`; before this record existed, `predecessor_doc_problems(5)` named only the missing s4 results record. Post-backup logs live in
`logs/m9_g3_s4_run/`, outside the increment.

**The saved state for a later session** (`session/final_state.json` sha256 `71de3196a0f6e5f2c036e9682f4efebb55ab774867eb32208f9b690dabe21574`; a session 5 is
permitted by the line rule, needs its own Part B and its own approval):

| file | sha256 |
| --- | --- |
| `training/checkpoints/final/model.zip` (1,111,726 bytes) | `7269898ac085f17cd840c57997c4539b2a5035cb0c0c363eacf88f70e84d21b1` |
| its `policy.pth` member | `366f9d86247404d76df7e8beae4c9e69782e5453d45cf2b909cc5ab9837ab264` |
| its `policy.optimizer.pth` member (11,200 updates; Adam step 112,000 on 12 parameters) | `38c940b723a84de93f925075606034945efe83088d4419a882ca1d26659fef1f` |
| `training/checkpoints/final/curriculum_state.json` (6,755 bytes; pointer 2,020; f 9 / need 320 / have 196; sessions [1, 2, 3, 4]; num_timesteps 5,745,536; next_episode 14,341; attempt_counter 46) | `598ac824e3ea7589bdb4d73f4886bde108a919e7b681548a3fc67965d8c5ff65` |
| `input/tape_baseline.json` | `81fa52c21078b2c2...` (content `d915fab9...`) |
| `session/line.json` (rows s1, s2, s3, s4) / `session/rule.json` | `b7251dc3ae548cb0...` / `9d6cbbfd018be16b...` |
| line contract / next session seed | `90eac1a6...` / 1005 |

## 9. Departures and notes

* **One training lifecycle failure.** Episode `train-0011297` (slot 8, the ninth episode of s4, inside the first rollout, at most 54.8 s into training) ended
  with `episode_timeout`: "no reply within the 30 s request deadline; process still alive (ConnectionClosed: recv failed: timed out)". The arena recorded it
  (1 of the registered limit of 3 per phase; more than 3 would make the session INCOMPLETE), the vector env ended the episode as a truncation, and the start
  was redrawn; the episode is not in `training/episodes.jsonl` and no registered measure depends on it. Free physical memory was about 6.4 GB at the time.
  verify-run is clean. Reported as a fact; not investigated further (zero ticks).
* **The close phase took 433.9 s against the 300 s figure in `WALL_CAPS_S`** (projected 501.1 s in the approval's budget block). The close is not
  clock-enforced (the resume-k record, section 5); the session clock total (5,602.1 s) stayed far inside the 8,700 s cap and nothing was marked. Reported as a
  fact, not acted on.
* **Probe in-flight accounting.** Attempt 43 sent 14,241 steps against 14,239 counted policy ticks, with 4 commands outstanding at the runner's end, consistent
  with the in-flight step and close of its 2 abandoned active episodes being settled after the runner loop (before the slots were handed back). No step
  failure was preserved in s4.
* **The launch shell.** The launcher was run from the Git Bash shell of this unattended session's tool, which returns once `Start-Process` has started the
  detached, hidden python (the same form as s1-s3). That shell was not an interactive terminal that could be kept open; the detached process ran to
  completion by itself (`state.json` `done`, the process gone, stderr empty).
* **Sampler gap.** The external sampler wrote no sample from 13:46:02Z to 14:16:40Z (during Part B pass 1's unit suite), because a monitor of this session held
  its file open; the monitor was replaced by a file-free watch. Readiness passed at every preflight; the session's own memory guard sampled throughout.
* Dates: the authorising message and every artifact of this session carry 2026-10-09.
* No pre-launch fix, no tool copy and no edit: the four generic tools ran as found; no tracked file was modified; nothing was staged.

## 10. What this does and does not say

* It says: resumed from s3's exact final state, a fourth 80-minute session of the same recipe under the same frontier rule left the pointer at 2,020 (four
  failed strip tests: 7/18, 2/13, 7/18, 1/12) and produced a frozen policy that clears **13 of 20** sticky episodes from the landing state 1,966 (s3's frozen
  policy: 9; s2's: 3; the open-loop tape: 2 on the same keys, p_hat 0.05 over 40) and **14 of 20** from 2,128 (s3: 15; s2: 13; s1: 8; the tape: 7 on the same
  keys, p_hat 0.49 over 200). This meets the depth bar at 1,966 for the first time in the line (D_4 = 1,966) and misses the reach bar at 2,128 by one clear
  (R_4 = none; s3 had R_3 = 2,128). Hence INCONCLUSIVE with D_4 = 1,966, and the line continues: the END_BUDGET_1966 milestone is met.
* It also shows, as facts and not decisions: the frontier held at 2,020 for the whole session (about 142 minutes across s3 and s4, 9 failed strip tests there);
  the training strip rate at 2,020 rose to 0.37 over the session (0.53 over the last 79 outcomes) while the frozen strip tests stayed at 1-7 of 12-18; no
  deterministic episode cleared from 2,128 or 1,966; R_unperturbed stayed 2,128; tick 0 0 of 20.
* **For session 5** (`line_consequence(5, rows)` on s4's recorded rows, computed read-only after this record was written): NULL, D = 2,128, or an
  INCOMPLETE that counts -> END_NO_PROGRESS (D_5 must be earlier than D_3 = 2,128); D = 1,966 or 1,694 -> CONTINUE; D <= 1,473 -> END_SUCCESS; an INCOMPLETE
  that does not count -> CONTINUE; INVALID -> SUSPENDED. The next budget milestone is k = 6 (D_6 <= 1,694). The approval of any session 5 computes the table
  again.
* It does not say anything about a session 5, other seeds or budgets. No s5 was run; whether to prepare one is the user's decision.

## 11. git status at the end

HEAD = origin/main = `b1a9a9387d11141482e3a28dca16b9e783f791db`; no commit, push, branch or pull request; nothing staged; `git diff --check` clean;
`git status --porcelain --untracked-files=all` shows only new files:

```
?? docs/rl_m9_g3_s4_approval.json
?? docs/rl_m9_g3_s4_results_2026-10-09.md
```

Git-ignored and therefore not shown: `logs/m9_g3_s4_prep/` (Part B), `logs/m9_g3_s4_run/` (snapshot, approval, preflight, launch, wait and post-run logs) and
`runs/m9_g3/s4/`. With this record in place, `predecessor_doc_problems(5)` = [] and the record is the only accepted `rl_m9_g3_s4_results` entry (checked
read-only after writing it).
