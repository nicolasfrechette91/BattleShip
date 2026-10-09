# M9-g3-s3 results (2026-10-09)

**Registered outcome: INCONCLUSIVE** (`m9_g3_s1_rule_v1`, the per-session rule, sha256 `dea9965a3989bce5...`): **D_3 = 2,128**, **R_3 = 2,128**. The
frozen final policy cleared **15 of 20** sticky episodes from the last landing state (2,128; 15 clears, 5 falls, all 15 verified): the 10 the depth needs and,
for the first time in the line, the bar B = 15 the reach needs, so R reaches 2,128. The chain stops at 1,966 with **9 of 20** (bar 10; s2: 3 of 20). PASS needs
R <= 1,966, so the outcome is INCONCLUSIVE (D <= 2,128). The rule's reason string, as recorded: "D_1 = 2128 <= 2128; R_1 = 2128" (the rule text names the
per-session subscript 1; this is session 3's own result). **Line outcome: CONTINUE** (`m9_g3_line_rule_v1`, `d9d82885703c016d...`): k = 3, counted sessions
[1, 2, 3], depths [none, 2,128, 2,128], "session 4 is proposable, with its own approval". This is the row the approval's computed `line_consequence` registered
for "INCONCLUSIVE or PASS with D = 2128" before the run. Nothing follows automatically: **no s4 was run or authorised**. One session, one run, once; nothing
was retried, extended or repaired. Every number below is read from `runs/m9_g3/s3/` and recomputed by `verify-run` (section 8).

Scope label: *M9-g3-s3: the third session of the g3 line, RESUMED bit for bit from g3-s2's recorded final state (model, optimizer, frontier pointer 2,040 and
spacing f 5 / need 320 / have 233, episode and attempt counters), under the unchanged replenishing controlled frontier rule `m9_g3_frontier_v1`, the same recipe
(observation v3, reward v2, sticky p = 0.25, entropy 0.01, 80 minutes, 4 + 6 slots), the reused g2-s1 tape baseline by digest, and the same keyed audit draws as
s1 and s2 (a paired measurement, not a replay); progress measured as D and R at landing states under the registered rules; no claim of a tick-0 policy.*

## 1. What was run

| item | value |
| --- | --- |
| tree | HEAD = origin/main = remote `main` = `d86e05fcd76480f187b010c5ae6a9a650f4f2e62` ("Fix g3 tests that assumed the next session had not started"); no tracked file modified at any point; nothing staged; g3 source fingerprint **`15ddbb84932aa658`** |
| authorisation | the user's unattended-session message of 2026-10-08, Part C, quoted verbatim in the approval (`authorised_on` 2026-10-08; `logs/m9_g3_s3_prep/launch_2026-10-08/s3_authorisation_part_c_2026-10-08.txt`, sha256 `74bef933...`) |
| source snapshot | `D:\BattleShip_source_snapshots\2026-10-09_m9_g3_s3` (`--session 3`; `log_dirs` [logs/m9_g3_prep, logs/m9_g3_s2_prep, logs/m9_g3_resume_tools, logs/m9_g3_resume_k_prep, logs/m9_g3_s3_prep]); PASS, 364 files, 3,930,864 bytes, 119.4 s, `snapshot.json` sha256 **`943482b1915c5a987c01c5068951a0bcb881dba9f03491109935ea261616d198`**; tool verify PASS (05:30:03Z: 364 files, 0 mismatches, 0 extra, 0 external mismatches, executable equal); independent PowerShell re-hash checked 365, bad 0, exe equal, PASS |
| approval | NEW `docs/rl_m9_g3_s3_approval.json`, sha256 **`3e3cb9dc20706aed9d037e4a9d85a8f8fa39ed07c1741407ee043a94dadfa25a`**, written 05:30:22Z-05:32:23Z by `logs/m9_g3_resume_tools/write_approval.py --session 3` (unchanged, sha256 `e652f04e...`) from `identity(3)` at the final HEAD: session 3; the nine trees; the D: folders; `resume_inputs` (expect {`e6d2c7d4...`, `cc7480df...`, `81fa52c2...`}, members `8afdb8ad...` / `18013ea1...`, counters 1,864,900 / 3,630 / Adam 36,300 x 12, `previous_sessions` = s1's and s2's rows read from s2's `line.json` and cross-checked along the chain s1 -> s2, s2's tree facts 4,478 / 477,564,684 / `a6965387...`); the snapshot above; the COMPUTED `line_consequence` (B12); coverage before approval 432,800 / 0 uncovered / 14 increments; `approval_status(3)` = approved |
| full preflight (once) | `python -B -X utf8 rl/m9_g3_session.py preflight --session 3`, 05:34:20Z to 05:53:21Z, **exit 0, `ok: true`, `problems: []`**: unit 29 / 29 (924 s), rule self-test PASS, approval "approved", snapshot "recorded, PASS and equal to the repository", nine trees ok, coverage 432,800 / 0 / 14, readiness 7,653.4 MB available / 13,610.9 MB commit free |
| launch | `powershell -NoProfile -ExecutionPolicy Bypass -File logs/m9_g3_resume_tools/launch_detached.ps1 -Session 3 -Repo ...` (sha256 `53f675ad...`) from Git Bash: **pid 21280 at 2026-10-09T05:53:50Z**, `python -B -u -X utf8 rl/m9_g3_session.py run --session 3`; its own preflight ran first (unit 29 / 29 in 940 s; readiness 7,156.5 MB / 13,349.3 MB); the session clock started 06:15:44Z; the process exited by itself (state `done` at 07:48:49Z); `session_stderr.txt` empty; waited with `wait_session.py --session 3` (done, exit 0, 115.6 min) |
| session clock | **5,585.4 s (93.1 min)** of the 8,700 s cap |
| executable | `build-us/Release/BattleShip.exe` `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee`, unchanged at the close; runtime files and frozen configuration equal their pins |

## 2. Part B (B0-B13), all held before any native tick

Logs: `logs/m9_g3_s3_prep/launch_2026-10-08/` (inside the s3 snapshot's file set; `partb_summary.md` there), `logs/m9_g3_s3_prep/final/` (the three passes).
Conditions: `docs/rl_m9_g3_resume_k_prep_decisions_2026-10-08.md` section 8 for k = 3, with the values of `docs/rl_m9_g3_progression_fix_2026-10-08.md`
section 10 (which supersedes the fingerprint and the "28/29" figures).

| # | result |
| --- | --- |
| B0 | HEAD = origin/main = `git ls-remote origin refs/heads/main` = `d86e05f`; `git status --porcelain --untracked-files=all` empty; nothing staged; `git diff --check` clean; fingerprint `15ddbb84932aa658` (per-file digests equal the progression-fix record; all ten g3 modules `i/lf w/lf`) |
| B1 | `three_passes.py --session 3` WITHOUT `--allow-git-gate` (03:18:34Z-05:04:21Z): **THREE_CONSECUTIVE_PASSES**, exit 0; unit **29 / 29** x 3 (1,499.0 / 1,020.2 / 928.9 s), e2e PASS digest **`078f46c445d8adc5`** x 3 (968.4 / 1,006.3 / 923.4 s), fingerprint unchanged before and after every pass; then, one after another: rule self-test PASS (s1 `dea9965a3989bce5`, line `d9d82885703c016d`); g1 evaluation 29 / 29 (64 s); g2 29 / 29 (446 s); g1 unit 62 / 63 with ONLY `identity_names_every_registered_pin` failing (327 s); fingerprint after the suites unchanged |
| B2 | g3 contract `4cd1deae...`, line contract `90eac1a6...`, frontier `60e174a6...`, s1 rule `dea9965a...`, line rule `d9d82885...`, g2 `8dfd44c6a8b7e319` / `1aadc7a6b2ff85bd`, g1 `6958857ed2dfd1c5`: all equal; `G.PPO` = s2's saved `curriculum_state.ppo` |
| B3 | executable `30a3913b...` (= s2's `final_state.executable_sha256`); pins; tape `81fa52c21078b2c2 / d915fab920554774` pinned, measured with the executable now; CVars absent or zero; status table verified; `T_clear` 2,326 / `5eccd4e2d5d77b25`, `T_t` 2,315 / `de1228be4146b720` |
| B4 | s2's saved state byte-identical to the registered values: `model.zip` `e6d2c7d4...` (1,112,120 B), members `8afdb8ad...` / `18013ea1...`; `curriculum_state.json` `cc7480df...` (11,560 B; pointer 2,040; sessions [1, 2]; num_timesteps 1,864,900; next_episode 7,454; attempt_counter 35); tape `81fa52c2...`; `final_state.json` `f9cf6c15...` (session 2; counters 1,864,900 / 3,630 / Adam 36,300 x 12; next seed 1003; line CONTINUE); `line.json` `4fb6b0ef...` rows = s1's then s2's; `predecessor_problems(3)` = []; `unregistered_predecessors(3)` = []; chain `sessions_checked` 2; `predecessor_doc_problems(3)` = [] (the s1 and s2 approvals and results records found by the exact rule); `runs/m9_g3/s2` = its increment by the tool (ninth tree ok) AND the independent re-hash (4,478 checked, 0 missing / 0 extra / 0 bad) |
| B5 | the nine trees of `trees_for(3)` ok with the registered facts (tool, dry run) and PASS by the independent re-hash (rd1 166, rd2 62, rd3 77, rd4 93, m9_g1 2,740, m9_g1_eval 1,393, m9_g2_s1 9,779, m9_g3_s1 4,935, m9_g3_s2 4,478; 0 / 0 / 0 each); coverage 432,800 files, 0 uncovered, 14 increments |
| B6 | `preflight --session 3 --skip-unit` (05:19:46Z-05:24:51Z): exit 1 with exactly `["no approval record at docs\rl_m9_g3_s3_approval.json (the session is not authorised)"]`; stderr empty; readiness passed (8,143.6 MB / 13,659.9 MB; C: 102.0 GiB, D: 1,648.4 GiB) without closing anything |
| B7 | pessimistic 7,780 s of 8,700 s (fits); the close projected 436.4 s over nine trees (2,899,055,876 B), not clock-enforced |
| B8 | no `BattleShip.exe` anywhere (before the dry run, at 05:27Z, before the launch); no tracked, staged or replay-browser change (`replay/_local` untouched since 2026-10-03); readiness above the thresholds at every reading; `node` processes: see section 7 |
| B9 / B10 | section 1 (snapshot first, then the approval; every Part B log written before the snapshot; nothing written under any directory of the snapshot set afterwards; later logs in `logs/m9_g3_s3_run/`) |
| B11 | the four generic tools as found (sha256 in `launch_2026-10-08/b8_b11_machine_and_paths.txt`); `independent_increment_check.ps1` `98abb0b9...`; `logs/m9_g3_s3_run`, `runs/m9_g3/s3`, the s3 approval and any `rl_m9_g3_s3_results*` entry absent before the launch |
| B12 | `line_consequence(3, [s1, s2])` computed into the approval: NULL -> CONTINUE; D 2,128 / 1,966 / 1,694 -> CONTINUE; D <= 1,473 -> END_SUCCESS; INCOMPLETE either way -> CONTINUE; INVALID -> SUSPENDED; reachable line ends: END_SUCCESS, SUSPENDED |
| B13 | k = 3: s1 and s2 registered; `unregistered_predecessors(3)` = [] |

## 3. Phases

| phase | wall (cap) | native ticks (cap) | result |
| --- | ---: | ---: | --- |
| open | 0.13 s (60) | 0 | the three inputs copied and checked against the APPROVAL's digests, the H6 predecessor assertions, the resume compatibility check; `resume_source`: expect from the approval, previous_sessions from `runs/m9_g3/s2/session/line.json`, final state from s2's `final_state.json`, chain checked over s1, s2 |
| P1 lineages | 25.3 s (240) | 13,923 (60,000) | PASS, shared prefix 2,298 |
| P2 staging equivalence | 39.4 s (120) | 31,998 (60,000) | PASS |
| T0 drift check | 12.2 s (240) | 14,440 (60,000) | PASS: 5 of 5 tape keys at 2,128 reproduced the table (h, f, c, h, f) and the measuring session's native action digests |
| training | 4,802.0 s (4,800) | 10,236,471 (20,000,000) | valid end: **wall cap**; **1,889,760 policy transitions** this session (cap 3,072,000), 369 rollouts, 3,690 PPO updates; prefix 7,957,580, policy 1,889,760, probes 389,131 ticks |
| close audit | 155.6 s (1,200) | 299,726 (3,000,000) | 103 of 103 planned episodes (landings 2,128 and 1,966: 20 sticky + 20 unperturbed + 1 deterministic each; tick 0: 20 sticky + 1 deterministic) |
| verification | 87.9 s (600) | 161,416 (1,500,000) | **65 of 65 replays exact** (tier 0: the 24 audit sticky clears; tier 1: 20 training clears; tier 2: 2 probe clears; tier 3: 19 diagnostics); 0 skipped, 0 errors |
| close | 462.9 s (300, see section 9) | 0 | the nine protected trees equal their D: increments, no pin drift, no provenance or write-guard violation, metadata audit 1,869 files / 5,731 JSONL lines clean, no leftover process |

**Native ticks in the session: 10,757,974** (13,923 + 31,998 + 14,440 + 10,236,471 + 299,726 + 161,416). Lifecycle failures 0 (arena); stale staging events
2 in the training summary, 1 record in `training/stale.jsonl` (s2: 24; recorded, never counted); two worker-side `no_episode` step-mismatch records preserved under `session/failures/` (section 9).

## 4. The resume, bit for bit

| check | s2 final (recorded) | s3 | equal |
| --- | --- | --- | --- |
| copied `input/model.zip` | `e6d2c7d48b71...` | `e6d2c7d48b71...` (open.json `resume.inputs`; the file in `input/`) | yes |
| copied `curriculum_state.json`, `tape_baseline.json` | `cc7480df...`, `81fa52c2...` | same | yes |
| model members at the open | `8afdb8ad...` / `18013ea1...` | `resume.members` `8afdb8ad...` / `18013ea1...` | yes |
| **initial checkpoint `ckpt_001864900` (`why` initial)** | | `policy.pth` **`8afdb8ad01fa99cf7ff7958e449740d062d5eae62dd6b436bbaf7cdb0c8b5913`**, `policy.optimizer.pth` **`18013ea1776240a9f9d574f5590bef08cd6179779eb70ec1ba1316f746b9f27f`** (H12 byte check at `_on_training_start`: `initial_members_equal_predecessor: true`); its model.zip `6669e641...` differs from s2's `e6d2c7d4...` only in the `data` member, as designed | yes |
| counters | num_timesteps 1,864,900; `_n_updates` 3,630; Adam step 36,300 on 12 params | start_timesteps 1,864,900 -> final 3,754,660 (+1,889,760); updates 3,630 -> 7,320 (+3,690 = 369 rollouts x 10 epochs); Adam 36,300 -> 73,200 (+36,900 = 369 x 100) on all 12; resumed seed 1003 -> next 1004 | continuous |
| frontier carried | pointer 2,040; f 5 / need 320 / have 233; line_failed {2040: 5, 2060: 3, 2140: 2, 2160: 1, 2180: 1, 2200: 1, 2220: 4, 2240: 1, 2280: 4}; next_episode 7,454; attempt_counter 35; sessions [1, 2] | initial checkpoint spacing f 5 / need 320 / have 233; first s3 attempt n = 36 at 2,040 with a = 6, f 5 / need 320; lowest s3 episode `train-0007454`; final state sessions [1, 2, 3], next_episode 11,289, attempt_counter 42 | continuous |
| previous_sessions | s1 row, s2 row | recorded at the open = s2's `line.json` rows (chain s1 -> s2 checked); s3's `line.json` = [s1 row, s2 row, s3 row] | yes (verify-run `equal_to_predecessor_record: true`, `chain.ok: true`) |

## 5. Training and the frontier

* Episodes 3,783: **1,612 clears (42.6 %)**, 1,953 falls, 218 horizon. By start region: strip 1,888 (553 clears, 29.3 %), near window 1,175 (635, 54.0 %), rehearsal
  720 (424, 58.9 %). Native ticks per policy transition 5.4 (s2: 8.9); prefix share of training ticks 77.7 %. Staged starts 3,831; slot wait for a ready start
  408.3 s (8.5 % of the training wall); 42 staged starts withdrawn for attempts; probe wall 211.8 s (4.4 %; 25.1-49.9 s per attempt).
* **The pointer moved once, 2,040 -> 2,020** (s2: nine moves, 2,220 -> 2,040), at attempt 37 (a = 7, the sixth failed attempt at 2,040 over the line before
  it: five in s2, one in s3), at 1,048.4 s of training wall (2,110,660 transitions cumulative). It then held at 2,020 for the last 62.4 minutes after five failed
  strip tests.
* **Every attempt** (7; frozen snapshot, keyed strip starts and draws; "live" = clear rate of the 60 preceding counted strip outcomes at that pointer; re-check =
  the 2,128 landing, the only landing behind the frontier; wait = training wall between attempts at that pointer and the deferred triggers (their `have`)):

| # | pointer | a | f / need / have | trigger (training wall) | live (n) | frozen strip test | re-check 2,128 | result | wall | wait before it / deferred |
| ---: | ---: | ---: | --- | --- | ---: | --- | --- | --- | ---: | --- |
| 36 | 2,040 | 6 | 5 / 320 / 327 | 8 of 10 (192.0 s) | 0.50 (60) | 6 / 17 | - | FAILED_STRIP | 25.1 s | carried from s2 (9 deferred in s2 at f 5); in s3 4 deferred at 250, 266, 301, 317 |
| 37 | 2,040 | 7 | 6 / 320 / 362 | 8 of 12 (993.0 s) | 0.45 (60) | **10 / 20** | **10 / 17 passed** | **MOVED -> 2,020** | 49.9 s | 801 s; 17 deferred at 38 ... 311 |
| 38 | 2,020 | 1 | 0 / 0 / 646 | 8 of 19 (2,534.1 s) | 0.28 (60) | 3 / 14 | - | FAILED_STRIP | 26.1 s | 1,486 s after the move, trigger-limited (need 0; no deferred) |
| 39 | 2,020 | 2 | 1 / 20 / 266 | 8 of 18 (3,251.0 s) | 0.22 (60) | 6 / 17 | - | FAILED_STRIP | 27.6 s | 717 s, trigger-limited (no deferred) |
| 40 | 2,020 | 3 | 2 / 40 / 58 | 8 of 20 (3,431.7 s) | 0.37 (60) | 4 / 15 | - | FAILED_STRIP | 28.9 s | 181 s; 1 deferred at 35 |
| 41 | 2,020 | 4 | 3 / 80 / 115 | 8 of 20 (3,799.6 s) | 0.33 (60) | 3 / 14 | - | FAILED_STRIP | 26.5 s | 368 s; 1 deferred at 35 |
| 42 | 2,020 | 5 | 4 / 160 / 175 | 8 of 14 (4,298.0 s) | 0.48 (60) | 3 / 14 | - | FAILED_STRIP | 27.6 s | 498 s; 4 deferred at 72, 120, 140, 158 |

  After attempt 42: need 320, 6 deferred triggers (at have 18, 34, 50, 69, 88, 143); training ended at have 171. Totals: **1 MOVED, 6 FAILED_STRIP, 0
  BLOCKED_BY_RECHECK, 0 INTERRUPTED**; attempt yield 0.143 moves per decided attempt (s2: 0.409); **33 deferred triggers** (21 at 2,040, 12 at 2,020), 7 acted-on
  triggers, 77 void windows. No HELD, no STALLED; spacing at the close f = 5, need 320, have 171. Line failed attempts after s3: {2020: 5, 2040: 6, 2060: 3,
  2140: 2, 2160: 1, 2180: 1, 2200: 1, 2220: 4, 2240: 1, 2280: 4}.
* **Trigger-to-test gap** (window rate minus frozen-test rate), attempts 36-42: +0.45, +0.17, +0.21, +0.09, +0.13, +0.19, +0.36. Snapshot `strip_calibration_gap`
  per attempt: +0.71, -0.55, +4.30, -1.02, +0.59, +2.52, +3.44.
* **Strip clear rates while training** (strip-region episodes at the pointer, per 100 in completion order): **2,040 0.49 (457: 0.49, 0.44, 0.51, 0.54, 0.46)**
  (s2 at 2,040: 0.33 over 1,117); **2,020 0.23 (1,431: 0.09, 0.09, 0.10, 0.16, 0.15, 0.15, 0.27, 0.11, 0.18, 0.35, 0.32, 0.37, 0.48, 0.39, 0.26; last 79 at 0.32)**.
* **The frontier position over training time:** 2,040 from 0 to 1,048 s (17.5 min; with s2's last 44.2 minutes, 61.7 minutes at 2,040 across the two
  sessions); **2,020 from 1,048 s to the end at 4,793 s (62.4 min)**. The pointer got past 2,040 once, to 2,020, and not further.
* **Throughput by pointer** (policy transitions/s per rollout, median [min, max], rollouts): 2,040 250.5 [104.1, 408.5] (48); 2,020 479.8 [72.9, 884.9] (321).
  Session median 460.7 transitions/s (s2: 273.2).
* **Periodic checkpoints** (H2 alignment: 1,864,900 + j x 102,400): `ckpt_001967300`, `002069700` (pointer 2,040), `002172100` ... `003708100` (16 more, all at
  2,020): **18 periodic**, plus `ckpt_001864900` (initial) and `final` (3,754,660): 20 checkpoints, each pinned (`checkpoint.json`) and re-checked by verify-run.

## 6. The frozen final policy (close audit), paired with s2's audit and the tape

Audited landings 2,128 and 1,966; tick 0 descriptive. Final weights `policy.pth` `6e4e297ff919d4ee...`. The sticky labels (`m9|g2|reach|<landing>|<k>`) and the
audit action keys carry no session component: s3's 20 sticky episodes at each landing draw the same masks and uniforms as s1's, s2's and the tape's first 20 keys
(a paired measurement under different weights).

| start | sticky verified clears of 20 | endings | unperturbed | deterministic | tape p_hat (keys) / tape on keys 0-19 | B |
| ---: | ---: | --- | ---: | --- | --- | ---: |
| **2,128** | **15 / 20** (s2: 13; s1: 8) | 15 clears, 5 falls | 13 / 20 (s2: 13) | horizon, no clear (3,600 ticks, 9 targets; s2: clear) | 0.490 (200) / 7 of 20 | **15** |
| **1,966** | **9 / 20** (s2: 3) | 9 clears, 8 falls, 3 horizon | 6 / 20 (s2: 4) | horizon, no clear (3,600 ticks, 8 targets; s2: fall) | 0.050 (40) / 2 of 20 | 10 |
| tick 0 | 0 / 20 (s2: 0) | | | no clear | | |

Per key k = 0..19 (c clear, f fall, h horizon):

```
2,128   tape  hfchfhccchfhchfchhcf   7
        s1    fhfcfcfcffffcffcfccc   8
        s2    cfccfcfccccfcfcfhccc  13
        s3    ffcccccccccffcfccccc  15
1,966   tape  fffffffhfffffffchffc   2
        s2    fcfffffffffffffcffcf   3
        s3    cfhccchccfcffcfcfffh   9
```

At 2,128: s3 vs s2 on identical keys: both clear 10, s2 only 3, s3 only 5, neither 2; s3 vs s1: both 7, s1 only 1, s3 only 8; s3 vs the tape: both 6, tape only
1, s3 only 9, neither 4. At 1,966: s3 vs s2: both 1, s2 only 2, s3 only 8, neither 9; s3 vs the tape: both 1, tape only 1, s3 only 8, neither 10.

* **Rule outcome INCONCLUSIVE:** D_3 = 2,128 (15 >= 10 at 2,128; 9 < 10 at 1,966), R_3 = 2,128 (15 >= B = 15 at 2,128; 9 < 10 at 1,966). PASS needs R <= 1,966.
  `D/R_if_every_claimed_clear_were_verified` the same (15 and 9 claimed = verified). **Reported, never deciding:** R_unperturbed = 2,128 (13 >= 10 at 2,128, 6 < 10
  at 1,966); both deterministic episodes ended at the 3,600-tick horizon without a clear; FRONTIER_BACKED true; `route_mastered_ticks` 198.
* Value calibration (reported only): at 2,128 start V +4.72 against a realised mean return +6.68 (gap -1.95; s2: -0.66), start entropy 3.551 nats (83.0 % of
  4.2767); at 1,966 start V -0.21 against +2.96 (gap -3.17, pessimistic; s2: +7.00, optimistic), entropy 3.988 (93.2 %).
* Entropy per rollout (fraction of maximum): 88.6 % after s3's first update, minimum 84.2 % (rollout 296), maximum 92.5 % (rollout 223), **88.3 % at the end**
  (s2 ended at 90.1 %); explained variance 0.55 -> 0.31 at the end (median 0.48, range -0.47 to 0.87); median approx_kl 0.0096; recent-episode mean return 3.74
  in the first rollout, 3.90 in the last.

## 7. Resources against the caps

| resource | peak / used | cap |
| --- | ---: | ---: |
| session clock | 5,585.4 s | 8,700 s |
| training wall | 4,802.0 s | 4,800 s (the registered valid end) |
| native ticks (session) | 10,757,974 (per phase in section 3) | per phase |
| policy transitions (this session) | 1,889,760 | 3,072,000 |
| main process private memory | 1,451.4 MB (sampler; the clock's own reading 1,534.6 MB) | 3,072 MB |
| process tree private memory | 6,606.9 MB | 9,216 MB |
| process tree working set | 2,371.7 MB | 4,096 MB |
| lowest system available memory | 5,661.9 MB | at least 1,024 MB |
| lowest system commit free | 7,042.3 MB | at least 2,048 MB |
| BattleShip processes (peak) | 10 (1,110 samples at 5 s) | 10 |
| memory breach | none | |

**External memory pressure.** A read-only sampler (10 s, outside the repository) ran from 03:18Z to the end of the post-run checks. During the session (launch
05:53:50Z to 07:49Z): **no `node` process at all**; the only processes above 1 GB private were `vmmem` (4,104 MB, present throughout) and the session's own
python (pid 21280, up to about 1.45 GB); lowest free physical 5,834 MB, lowest commit free 7,046 MB (07:38Z, the close audit). Earlier, during Part B pass 1:
one transient `node` (PID 36696) reached 2,094 MB private at 03:28:47Z and was gone within about 20 s; clusters of up to nine short-lived `node` processes of
59-302 MB each around 03:33-03:36Z (lowest commit free 10,894 MB); their origin was not determined and none was closed. None appeared after 03:36Z.

## 8. Integrity, evidence and verification

| check | result |
| --- | --- |
| verification | 65 / 65 exact; every clear counted in a registered measure replayed (the 24 audit sticky clears: 15 at 2,128, 9 at 1,966); 20 training clears, 2 probe clears, 19 diagnostics exact |
| `verify-run --session 3` (against `runs/m9_g3/s2` and the chain s1, s2; before any copy; output `logs/m9_g3_s3_run/verify_run.json`, copied to `derived/`) | **`ok: true`, 0 problems**: metadata 1,875 files / 5,731 JSONL lines, 0 failures; 20 checkpoints with pins and g3 identity; training 3,783 / probes 128 / drift 5 / audit 103 records re-derived; resume checks cross-checked (previous_sessions equal to s2's record, inputs = s2's final state, initial checkpoint members = s2's final members `8afdb8ad...` / `18013ea1...`); chain ok over 2 sessions; frontier rebuilt from the records = the log (pointer 2,020, 1 move, 7 attempts, 33 deferred); tape recorded at the open as `resume.inputs`, equal to the registered reuse, pinned; rule recomputed INCONCLUSIVE / 2,128 / 2,128 = recorded; line recomputed CONTINUE = recorded; `inexact` [], `tier0_without_replay` 0. Re-run after the copies into `launch/` and `derived/`: `ok: true` again, identical apart from its timestamp (`verify_run_after_copies.json`) |
| drift | 5 of 5 (no tape drift) |
| protected trees | the nine (rd1 166, rd2 62, rd3 77, rd4 93, m9_g1 2,740, m9_g1_eval 1,393, m9_g2_s1 9,779, m9_g3_s1 4,935, **m9_g3_s2 4,478**) equal their D: increments at both preflights, at the close, and after the backup by the tool (`trees_state(3)` after the backup: all nine ok with the registered facts, `post_trees_tool_check.txt`) and the independent re-hash (0 missing / 0 extra / 0 bad each, `post_trees_independent_check.txt`) |
| write guard, provenance | no write under any other `runs/` tree, `rl/` or `docs/` during the session; 0 provenance violations; `leftover_processes.json` empty |
| constraints | no RNG seed inspected, logged, controlled, compared or hashed (keyed sha256 draws only); process restart was the reset for every episode; P1 / P2 PASS (the submit / consume / input-tick contract); the submitted canonical words are the replay truth (65 / 65 exact); every start a prefix of the agent's own two verified rd4 routes; no fixture, TAS or recording read; no hardcoded route or waypoint; no native, decomp or submodule change |

**Evidence.** `runs/m9_g3/s3/` (Git-ignored): after the copies (logs/m9_g3_s3_run -> `launch/` except the two outputs, the whole of `logs/m9_g3_s3_prep/` ->
`launch/prep/` (byte-equal, `diff -rq` clean), the snapshot record and its verify JSON -> `launch/`, `verify_run.json` and `report.json` -> `derived/`)
**3,779 files, 429,781,233 bytes**. Increment **`D:\BattleShip_runs_backup\2026-10-09_incr_m9_g3_s3`**, manifest sha256
**`338d49394987780d4163d35dffaffad41f95cce4e207f26e837751613da77fc3`**: tool backup PASS (3,779 / 429,781,233, 0 hash mismatches, 07:51:25Z); separate tool
verify `--source runs/m9_g3/s3` PASS (07:51:32Z, `verification.json` PASS, `source` = `runs\m9_g3\s3`); independent `independent_increment_check.ps1`: checked
3,779, missing 0, extra 0, bad 0, PASS. **Total `runs/` coverage: 436,579 source files, 0 uncovered, 15 increments** (`post_coverage.txt`; 432,800 + 3,779). **Discovery for session 4** (`next_session_discovery.txt`): `unregistered_predecessors(4)` = []; `predecessor_tree(3)` = (`m9_g3_s3`, `runs/m9_g3/s3`, `2026-10-09_incr_m9_g3_s3`, 3,779 files, 429,781,233 bytes, manifest `338d4939...`, discovered from the increment's verification record, no record problem); `trees_for(4)` = the nine + `m9_g3_s3`; before this record existed, `predecessor_doc_problems(4)` named only the missing s3 results record (re-checked after writing it: section 11). Post-backup logs live in `logs/m9_g3_s3_run/`, outside the increment.

**The saved state for a later session** (`session/final_state.json` sha256 `910d503f1c97dbc97ff0ec49ef30f2f533cb21295bb46e5eda2a9b8394d77095`; a session 4 is
permitted by the line rule, needs its own Part B and its own approval):

| file | sha256 |
| --- | --- |
| `training/checkpoints/final/model.zip` (1,110,750 bytes) | `d4ec82ab08a5119435083f72421863df8735691d1c844e6d7c6c1280e8b70015` |
| its `policy.pth` member | `6e4e297ff919d4ee074b54a7e7abe239263a4c9af94fe82d4390fc8379778fb2` |
| its `policy.optimizer.pth` member (7,320 updates; Adam step 73,200 on 12 parameters) | `c09ab68977d7dafd3295cd5e086132ec7c3e4108c7de29539d177bd5ce28f66a` |
| `training/checkpoints/final/curriculum_state.json` (7,533 bytes; pointer 2,020; f 5 / need 320 / have 171; sessions [1, 2, 3]; num_timesteps 3,754,660; next_episode 11,289; attempt_counter 42) | `4a8caf44ecdcc4cc8fc1f538d7cee8fd5a76bb758c01cc0f822e9dc352752506` |
| `input/tape_baseline.json` | `81fa52c21078b2c2...` (content `d915fab9...`) |
| `session/line.json` (rows s1, s2, s3) / `session/rule.json` | `70f4ab4729ce27fe...` / `4e994acb08f0f660...` |
| line contract / next session seed | `90eac1a6...` / 1004 |

## 9. Departures and notes

* **Dates.** The authorising message is dated 2026-10-08 (`authorised_on`, the approval text "Part C of the launch session of 2026-10-08", and the Part B
  log directory `launch_2026-10-08`). The launch session crossed midnight (local and UTC) during B1, so the artifacts created on 2026-10-09 carry that date: the
  D: snapshot `2026-10-09_m9_g3_s3`, the increment `2026-10-09_incr_m9_g3_s3` and this record, as the s2 launch did.
* **The close phase took 462.9 s against the 300 s figure in `WALL_CAPS_S`** (projected 436.4 s in the approval's budget block, from s2's rate). The close is not
  clock-enforced (the resume-k record, section 5); the session clock total (5,585.4 s) stayed far inside the 8,700 s cap and nothing was marked. Reported as a
  fact, not acted on.
* **Two `no_episode` step-mismatch records** (`session/failures/step_x_w01.json.gz` at 07:20:53Z, `step_x_w04.json.gz` at 07:14:51Z) were preserved by workers 1
  and 4 during attempts 41 and 40 (each attempt withdrew 6 staged starts); the arena recorded 0 lifecycle failures, no episode or measure depends on them, and the
  metadata audit and verify-run are clean. s1 and s2 have no such directory. Reported as a fact; not investigated beyond reading the records (zero ticks).
* No pre-launch fix, no tool copy and no edit: the four generic tools ran as found; no tracked file was modified; nothing was staged.
* The detached launch form was checked first with a harmless `Start-Process` sleep from the same shell (it survived the shell's exit); no native tick.
* The rule's reason string says "D_1 ... R_1" because `m9_g3_s1_rule_v1` is the per-session rule; the record's `session` is 3 and the line rows carry k = 3.

## 10. What this does and does not say

* It says: resumed from s2's exact final state, a third 80-minute session of the same recipe under the same frontier rule took the pointer one strip past 2,040
  (to 2,020) and produced a frozen policy that clears **15 of 20** sticky episodes from the last landing state 2,128 (s2's frozen policy: 13; s1's: 8; the
  open-loop tape: 7 on the same keys, p_hat 0.49 over 200) and **9 of 20** from 1,966 (s2: 3; the tape: 2 on the same keys, p_hat 0.05 over 40). This meets the
  reach bar at 2,128 for the first time in the line (R_3 = 2,128) and misses the depth bar at 1,966 by one clear. Hence INCONCLUSIVE with D_3 = R_3 = 2,128, and the
  line continues.
* It also shows, as facts and not decisions: the frontier held at 2,020 for the last 62 minutes (five failed strip tests at 3-6 of 14-17; the training strip rate
  there rose from 0.09-0.10 in the first three hundreds to 0.26-0.48 in the last six, 0.32 over the last 79 outcomes); the deterministic episodes no longer clear from 2,128.
* **For session 4** (the approval's computed table for k = 4, section 5.4 of the runbook): NULL, D = 2,128, or an INCOMPLETE that counts ends the line
  (END_BUDGET_1966); D = 1,966 or 1,694 continues; D <= 1,473 is END_SUCCESS. s3's 9 of 20 at 1,966 is the paired reading closest to that bar so far.
* It does not say anything about a session 4, other seeds or budgets. No s4 was run; whether to prepare one is the user's decision.

## 11. git status at the end

HEAD = origin/main = `d86e05fcd76480f187b010c5ae6a9a650f4f2e62`; no commit, push, branch or pull request; nothing staged; `git diff --check` clean;
`git status --porcelain --untracked-files=all` shows only new files:

```
?? docs/rl_m9_g3_s3_approval.json
?? docs/rl_m9_g3_s3_results_2026-10-09.md
```

Git-ignored and therefore not shown: `logs/m9_g3_s3_prep/` (Part B), `logs/m9_g3_s3_run/` (snapshot, approval, preflight, launch, wait and post-run logs) and
`runs/m9_g3/s3/`. With this record in place, `predecessor_doc_problems(4)` = [] and the record is the only accepted `rl_m9_g3_s3_results` entry (checked
read-only after writing it).
