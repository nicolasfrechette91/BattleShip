# M9-g3-s2 results (2026-10-08)

**Registered outcome: INCONCLUSIVE** (`m9_g3_s1_rule_v1`, the per-session rule, sha256 `dea9965a3989bce5...`): **D_2 = 2,128**, **R_2 = none**. The
frozen final policy cleared **13 of 20** sticky episodes from the last landing state (2,128; 13 clears, 6 falls, 1 horizon, all 13 verified): at least the 10 the
depth needs, below the bar B = 15 the reach needs. The chain stops at 1,966 (3 of 20). The rule's reason string, as recorded: "D_1 = 2128 <= 2128; R_1 = None"
(the rule text names the per-session subscript 1; this is session 2's own result). **Line outcome: CONTINUE** (`m9_g3_line_rule_v1`, `d9d82885703c016d...`):
k = 2, counted sessions [1, 2], depths [none, 2,128], "session 3 is proposable, with its own approval". **The END_BUDGET_2128 consequence acknowledged in the
authorisation did not fire**, because it applies to a NULL s2 and s2 reached D_2 = 2,128. Nothing follows automatically: **no s3 was run or authorised**. One
session, one run, once; nothing was retried, extended or repaired. Every number below is read from `runs/m9_g3/s2/` and recomputed by `verify-run` (section 8).

Scope label: *M9-g3-s2: the second session of the g3 line, RESUMED bit for bit from g3-s1's recorded final state (model, optimizer, frontier pointer 2,220 and
spacing f 4 / need 160 / have 133, episode and attempt counters), under the unchanged replenishing controlled frontier rule `m9_g3_frontier_v1`, the same recipe
(observation v3, reward v2, sticky p = 0.25, entropy 0.01, 80 minutes, 4 + 6 slots), the reused g2-s1 tape baseline by digest, and the same keyed audit draws as
s1 (a paired measurement, not a replay); progress measured as D and R at landing states under the registered rules; no claim of a tick-0 policy.*

## 1. What was run

| item | value |
| --- | --- |
| tree | HEAD = origin/main = remote `main` = `e73e58970f9f74ebbef6fb5c9aad93b907f08e84`; no tracked file modified at any point; g3 source fingerprint **`e30b10a9f453c88a`** |
| authorisation | the user's unattended-session message of 2026-10-07, Part C, quoted verbatim in the approval (`authorised_on` 2026-10-07) |
| source snapshot | `D:\BattleShip_source_snapshots\2026-10-08_m9_g3_s2` (`--session 2`; `log_dirs` [logs/m9_g3_prep, logs/m9_g3_s2_prep]); PASS, 267 files, 3,500,404 bytes, `snapshot.json` sha256 **`85b2b9baeddea84a701f36214cd3b96e633ba56cc0e8601c06dbacaf5999ab6d`**; tool verify PASS (04:44:21Z: 0 mismatches, 0 extra, executable equal); independent PowerShell re-hash checked 268, bad 0, exe equal, PASS |
| approval | NEW `docs/rl_m9_g3_s2_approval.json`, sha256 **`671ddae798ccd9eeb478b9d41b5ab185f63f4cb7effd50c2cd7e7aa818e96ba9`**, written by `logs/m9_g3_s2_prep/tools/write_s2_approval.py` (unchanged, sha256 `e7b1e778...`) from `identity(2)` at the final HEAD: session 2; the eight trees; 17 D: folders (digest `b13b28886cb15b98...`); `resume_inputs` (expect {`669692023c2d...`, `74adedd8...`, `81fa52c2...`}, members `ffce3303...` / `c072b0db...`, counters 708,712 / 1,380 / Adam 13,800 x 12, `previous_sessions` read from s1's `line.json`, s1's tree facts 4,935 / 508,166,787 / `d12966c1...`); the snapshot above; `line_consequence` (B12); coverage before approval 428,322 / 0 uncovered |
| full preflight (once) | `python -B -X utf8 rl/m9_g3_session.py preflight --session 2`, 04:46:58Z to 05:02:09Z, **exit 0, `ok: true`, `problems: []`**: unit 28 / 28 (728 s), rule self-test PASS, approval "approved", snapshot "recorded, PASS and equal to the repository", eight trees ok, coverage 428,322 / 0 / 13, readiness 7,914.7 MB available / 19,392.2 MB commit free |
| launch | `launch_detached_s2.ps1` (sha256 `d8806378...`): **pid 23092 at 2026-10-08T05:02:25Z**, `python -B -u -X utf8 rl/m9_g3_session.py run --session 2`; its own preflight ran first; the session clock started 05:19:00Z; the process exited by itself at 06:50:21Z; `session_stderr.txt` empty; waited with `wait_session_s2.py` (done, exit 0) |
| session clock | **5,480.8 s (91.3 min)** of the 8,700 s cap |
| executable | `build-us/Release/BattleShip.exe` `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee`, unchanged at the close; runtime files and frozen configuration equal their pins |

## 2. Part B (B0-B12), all held before any native tick

Logs: `logs/m9_g3_s2_prep/launch_2026-10-07/` (inside the s2 snapshot's file set; `partb_summary.md` there), `logs/m9_g3_s2_prep/final/` (the three passes).

| # | result |
| --- | --- |
| B0 | HEAD = origin/main = remote main `e73e589`; `git status --porcelain --untracked-files=all` empty; nothing staged; `git diff --check` clean; fingerprint `e30b10a9f453c88a` (per-file digests = the prep record); `logs/m9_g3_prep/final/fingerprint_start.txt` = its copy in `runs/m9_g3/s1/launch/prep/final/` (`0190a900...`, content `17dea6d712e624ed`) |
| B1 | `three_passes_s2.py`: **THREE_CONSECUTIVE_PASSES**, unit 28 / 28 (1,050 / 887 / 764 s), e2e PASS digest **`078f46c445d8adc5`** x 3 (s2 resumed at 180,088 with 7 aligned periodic checkpoints), fingerprint unchanged, nothing else running; rule self-test PASS (s1 `dea9965a3989bce5`, line `d9d82885703c016d`); g1 evaluation 29 / 29; g2 29 / 29; g1 unit 62 / 63 with ONLY `identity_names_every_registered_pin` failing |
| B2 | g3 contract `4cd1deae...`, line contract `90eac1a6...`, frontier `60e174a6...`, s1 rule `dea9965a...`, line rule `d9d82885...`, g2 `8dfd44c6...` / `1aadc7a6...`, g1 `6958857e...`: all equal; `G.PPO` = the saved `curriculum_state.ppo` |
| B3 | executable `30a3913b...` (= s1's `final_state.executable_sha256`); pins; tape `81fa52c21078b2c2 / d915fab920554774` pinned, measured with the executable now; CVars absent; status table verified; `T_clear` 2,326 / `5eccd4e2d5d77b25`, `T_t` 2,315 / `de1228be4146b720` |
| B4 | s1's saved state byte-identical to the registered values (model.zip, both members, curriculum state content, tape, final-state counters, next seed 1002, line CONTINUE / s2_permitted, `line.json` row); `predecessor_problems(2)` = []; `runs/m9_g3/s1` = its increment by the tool AND the independent re-hash (4,935 checked, 0 / 0 / 0) |
| B5 | the seven earlier trees ok (tool) and PASS (independent re-hash); coverage 428,322, 0 uncovered, 13 increments |
| B6 | `preflight --session 2 --skip-unit`: exit 1 with exactly `["no approval record at docs\rl_m9_g3_s2_approval.json (the session is not authorised)"]`; readiness passed (7,937.6 MB / 19,367.6 MB) without closing anything |
| B7 | pessimistic 7,780 s of 8,700 s (slack 920 s) |
| B8 | no `BattleShip.exe` anywhere (three readings before the launch); no tracked, staged or replay-browser change |
| B9 / B10 | section 1 (snapshot first, then the approval; nothing written under `logs/m9_g3_s2_prep/` or `logs/m9_g3_prep/` after the snapshot; later logs in `logs/m9_g3_s2_run/`) |
| B11 | the four s2 tools as found (sha256 in `launch_2026-10-07/tools_sha256.txt`); the generic `independent_increment_check.ps1` (`98abb0b9...`) |
| B12 | `line_consequence` in the approval (END_BUDGET_2128 on a NULL s2; audit pairing by identical keys; `s2_permitted` naming) |

## 3. Phases

| phase | wall (cap) | native ticks (cap) | result |
| --- | ---: | ---: | --- |
| open | 0.13 s (60) | 0 | the three inputs copied and checked against the APPROVAL's digests, the H6 predecessor assertions, the resume compatibility check; `resume_source`: expect from the approval, previous_sessions from `runs/m9_g3/s1/session/line.json` |
| P1 lineages | 22.6 s (240) | 13,923 (60,000) | PASS, shared prefix 2,298 |
| P2 staging equivalence | 36.4 s (120) | 31,998 (60,000) | PASS |
| T0 drift check | 14.3 s (240) | 14,440 (60,000) | PASS: 5 of 5 tape keys at 2,128 reproduced the table (h, f, c, h, f) and the measuring session's native action digests |
| training | 4,804.2 s (4,800) | 10,327,000 (20,000,000) | valid end: **wall cap**; **1,156,188 policy transitions** this session (cap 3,072,000), 225 rollouts, 2,250 PPO updates; prefix 7,899,080, policy 1,156,188, probes 1,271,732 ticks |
| close audit | 147.2 s (1,200) | 284,224 (3,000,000) | 103 of 103 planned episodes (landings 2,128 and 1,966: 20 sticky + 20 unperturbed + 1 deterministic each; tick 0: 20 sticky + 1 deterministic) |
| verification | 91.4 s (600) | 169,967 (1,500,000) | **68 of 68 replays exact** (tier 0: the 16 audit sticky clears; tier 1: 20 training clears; tier 2: 14 probe clears; tier 3: 18 diagnostics); 0 skipped, 0 errors |
| close | 364.5 s (300, see section 9) | 0 | the eight protected trees equal their D: increments, no pin drift, no provenance or write-guard violation, metadata audit 2,181 files / 5,780 JSONL lines clean, no leftover process |

**Native ticks in the session: 10,841,552** (13,923 + 31,998 + 14,440 + 10,327,000 + 284,224 + 169,967). Lifecycle failures 0; stale staging events 24 (recorded,
never counted).

## 4. The resume, bit for bit

| check | s1 final (recorded) | s2 | equal |
| --- | --- | --- | --- |
| copied `input/model.zip` | `669692023c2d...` | `669692023c2d...` (open.json `resume.inputs`) | yes |
| copied `curriculum_state.json`, `tape_baseline.json` | `74adedd8...`, `81fa52c2...` | same | yes |
| model members at the open | `ffce3303...` / `c072b0db...` | `resume.members` `ffce3303...` / `c072b0db...` | yes |
| **initial checkpoint `ckpt_000708712` (`why` initial)** | | `policy.pth` **`ffce330386c8c1335441ac22aa34e38c6f0df2aa8635f0f6a9aec4e71dea32ee`**, `policy.optimizer.pth` **`c072b0dbf4a3d21e1f2ea1bab3988bbf61f9df4ff53d10fc993b09ff059af7aa`** (H12 byte check at `_on_training_start`: `initial_members_equal_predecessor: true`); its model.zip `84081f03...` differs only in the `data` member, as designed | yes |
| counters | num_timesteps 708,712; `_n_updates` 1,380; Adam step 13,800 on 12 params | start_timesteps 708,712 -> final 1,864,900 (+1,156,188); updates 1,380 -> 3,630 (+2,250 = 225 rollouts x 10 epochs); Adam 13,800 -> 36,300 (+22,500 = 225 x 100) on all 12; resumed seed 1002 -> next 1003 | continuous |
| frontier carried | pointer 2,220; f 4 / need 160 / have 133; line_failed {2280: 4, 2240: 1, 2220: 4}; next_episode 3,735; attempt_counter 13; sessions [1] | first s2 attempt n = 14 at 2,220 with a = 5, f 4 / need 160; first s2 episode `train-0003735`; final state sessions [1, 2], next_episode 7,454, attempt_counter 35 | continuous |
| previous_sessions | s1 row | recorded at the open = s1's `line.json` row; s2's `line.json` = [s1 row, s2 row] | yes (verify-run `equal_to_predecessor_record: true`) |

## 5. Training and the frontier

* Episodes 3,577: **1,775 clears (49.6 %)**, 1,767 falls, 35 horizon. By start region: strip 1,836 (735 clears, 40.0 %), near window 994 (553, 55.6 %), rehearsal
  747 (487, 65.2 %). Native ticks per policy transition 8.9 (s1: 13.9); prefix share of training ticks 76.5 %. Staged starts 3,696; slot wait for a ready start
  541.5 s (11.3 % of the training wall); 132 staged starts withdrawn for attempts; probe wall 651.5 s (13.6 %; 21.5-47.5 s per attempt).
* **The pointer moved nine times, 2,220 -> 2,040** (s1: four moves, 2,300 -> 2,220), then held at 2,040 for the last 44.2 minutes after five failed strip tests.

| move | from -> to | attempt (a) | training wall | transitions (cumulative) | failed attempts before, at that pointer (line) |
| ---: | --- | --- | ---: | ---: | ---: |
| 1 | 2,220 -> 2,200 | 14 (a = 5) | 199.4 s | 744,552 | 4 (all in s1) |
| 2 | 2,200 -> 2,180 | 16 (2) | 471.8 s | 800,872 | 1 |
| 3 | 2,180 -> 2,160 | 18 (2) | 723.4 s | 872,552 | 1 |
| 4 | 2,160 -> 2,140 | 20 (2) | 924.2 s | 913,512 | 1 |
| 5 | 2,140 -> 2,120 | 23 (3) | 1,336.9 s | 1,021,032 | 2 |
| 6 | 2,120 -> 2,100 | 24 (1) | 1,396.1 s | 1,031,272 | 0 |
| 7 | 2,100 -> 2,080 | 25 (1) | 1,463.5 s | 1,036,392 | 0 |
| 8 | 2,080 -> 2,060 | 26 (1) | 1,565.0 s | 1,051,752 | 0 |
| 9 | 2,060 -> 2,040 | 30 (4) | 2,150.8 s | 1,174,632 | 3 |

* **Every attempt** (22; frozen snapshot, keyed strip starts and draws; "live" = clear rate of the preceding counted strip outcomes at that pointer, up to 60;
  re-check = the 2,128 landing, the only landing behind the frontier from pointer 2,100 on; wait = deferred triggers (their `have`) before the next attempt at that
  pointer):

| # | pointer | a | f / need / have | trigger | live (n) | frozen strip test | re-check 2,128 | result | wall | wait before the next attempt there |
| ---: | ---: | ---: | --- | --- | ---: | --- | --- | --- | ---: | --- |
| 14 | 2,220 | 5 | 4 / 160 / 208 | 8 of 18 (0.44) | 0.48 (60) | **10 / 19** | - | **MOVED -> 2,200** | 26.1 s | (2 deferred before it, at have 143, 155) |
| 15 | 2,200 | 1 | 0 / 0 / 63 | 8 of 17 (0.47) | 0.43 (60) | 9 / 20 | - | FAILED_STRIP | 26.1 s | need 20: none deferred; next at have 39 |
| 16 | 2,200 | 2 | 1 / 20 / 39 | 8 of 13 (0.62) | 0.48 (60) | **10 / 18** | - | **MOVED -> 2,180** | 26.3 s | |
| 17 | 2,180 | 1 | 0 / 0 / 41 | 8 of 18 (0.44) | 0.37 (41) | 5 / 16 | - | FAILED_STRIP | 27.0 s | need 20: 1 deferred at 15; next at 50 |
| 18 | 2,180 | 2 | 1 / 20 / 50 | 8 of 17 (0.47) | 0.38 (60) | **10 / 16** | - | **MOVED -> 2,160** | 25.1 s | |
| 19 | 2,160 | 1 | 0 / 0 / 21 | 8 of 18 (0.44) | 0.48 (21) | 6 / 17 | - | FAILED_STRIP | 26.0 s | need 20: 1 deferred at 18; next at 32 |
| 20 | 2,160 | 2 | 1 / 20 / 32 | 8 of 11 (0.73) | 0.55 (53) | **10 / 18** | - | **MOVED -> 2,140** | 25.7 s | |
| 21 | 2,140 | 1 | 0 / 0 / 23 | 8 of 19 (0.42) | 0.39 (23) | 3 / 14 | - | FAILED_STRIP | 25.4 s | need 20: 1 deferred at 19; next at 61 |
| 22 | 2,140 | 2 | 1 / 20 / 61 | 8 of 16 (0.50) | 0.42 (60) | 8 / 19 | - | FAILED_STRIP | 26.1 s | need 40: 2 deferred at 18, 35; next at 53 |
| 23 | 2,140 | 3 | 2 / 40 / 53 | 8 of 14 (0.57) | 0.48 (60) | **10 / 17** | - | **MOVED -> 2,120** | 25.1 s | |
| 24 | 2,120 | 1 | 0 / 0 / 14 | 8 of 9 (0.89) | 0.64 (14) | **10 / 17** | (none behind) | **MOVED -> 2,100** | 25.9 s | |
| 25 | 2,100 | 1 | 0 / 0 / 10 | 8 of 10 (0.80) | 0.80 (10) | **10 / 13** | **10 / 11 passed** | **MOVED -> 2,080** | 38.9 s | |
| 26 | 2,080 | 1 | 0 / 0 / 18 | 8 of 12 (0.67) | 0.56 (18) | **10 / 14** | **10 / 14 passed** | **MOVED -> 2,060** | 46.1 s | |
| 27 | 2,060 | 1 | 0 / 0 / 31 | 8 of 9 (0.89) | 0.42 (31) | 10 / 18 (passed) | 5 / 16 failed | **BLOCKED_BY_RECHECK** | 47.5 s | need 20: 1 deferred at 11; next at 30 |
| 28 | 2,060 | 2 | 1 / 20 / 30 | 8 of 12 (0.67) | 0.55 (60) | 10 / 16 (passed) | 6 / 17 failed | **BLOCKED_BY_RECHECK** | 47.3 s | need 40: 2 deferred at 14, 29; next at 48 |
| 29 | 2,060 | 3 | 2 / 40 / 48 | 8 of 11 (0.73) | 0.67 (60) | 4 / 15 | - | FAILED_STRIP | 26.3 s | need 80: 5 deferred at 20, 33, 44, 57, 72; next at 86 |
| 30 | 2,060 | 4 | 3 / 80 / 86 | 8 of 10 (0.80) | 0.65 (60) | **10 / 11** | **10 / 16 passed** | **MOVED -> 2,040** | 43.3 s | |
| 31 | 2,040 | 1 | 0 / 0 / 98 | 8 of 17 (0.47) | 0.32 (60) | 6 / 17 | - | FAILED_STRIP | 23.6 s | need 20: 1 deferred at 12; next at 219 (trigger-limited) |
| 32 | 2,040 | 2 | 1 / 20 / 219 | 8 of 17 (0.47) | 0.25 (60) | 2 / 13 | - | FAILED_STRIP | 21.5 s | need 40: 1 deferred at 35; next at 129 |
| 33 | 2,040 | 3 | 2 / 40 / 129 | 8 of 19 (0.42) | 0.30 (60) | 5 / 16 | - | FAILED_STRIP | 27.2 s | need 80: 1 deferred at 54; next at 230 |
| 34 | 2,040 | 4 | 3 / 80 / 230 | 8 of 19 (0.42) | 0.37 (60) | 1 / 12 | - | FAILED_STRIP | 22.6 s | need 160: 3 deferred at 37, 91, 105; next at 208 |
| 35 | 2,040 | 5 | 4 / 160 / 208 | 8 of 20 (0.40) | 0.30 (60) | 2 / 13 | - | FAILED_STRIP | 22.3 s | need 320: 9 deferred at 33 ... 222; training ended at have 233 |

  Totals: **9 MOVED, 11 FAILED_STRIP, 2 BLOCKED_BY_RECHECK, 0 INTERRUPTED**; attempt yield 0.409 moves per decided attempt (s1: 0.308); **30 deferred
  triggers** (2 at 2,220, 1 at 2,180, 1 at 2,160, 3 at 2,140, 8 at 2,060, 15 at 2,040), 22 acted-on triggers, 50 void windows. No HELD, no STALLED; spacing at the
  close f = 5, need 320, have 233.
* **Trigger-to-test gap** (window rate minus frozen-test rate), attempts 14-35: -0.08, +0.02, +0.06, +0.13, -0.15, +0.09, +0.17, +0.21, +0.08, -0.02, +0.30, +0.03,
  -0.05, +0.33, +0.04, +0.46, -0.11, +0.12, +0.32, +0.11, +0.34, +0.25. Snapshot `strip_calibration_gap` per attempt: +0.23, +0.06, -2.38, +0.98, -2.24, +2.78,
  -0.24, +3.19, -0.36, -2.08, -0.07, +0.36, -4.01, -1.94, -1.89, +5.42, -5.41, -1.27, +3.34, +2.23, +2.74, +3.06.
* **Strip clear rates while training** (counted strip outcomes at the pointer; per 100 in completion order where n > 100): 2,220 0.55 (78); 2,200 0.42 (105);
  2,180 0.40 (93); 2,160 0.55 (55); 2,140 0.44 (141); 2,120 0.67 (18); 2,100 0.83 (12); 2,080 0.55 (20); 2,060 0.60 (197; 0.56, 0.65); **2,040 0.33 (1,117: 0.32,
  0.30, 0.23, 0.34, 0.31, 0.23, 0.34, 0.38, 0.28, 0.43, 0.43, 0.47; last 79 at 0.43)**.
* **The frontier position over training time:** 2,220 from 0 to 199 s (3.3 min); 2,200 to 472 s (4.5); 2,180 to 723 s (4.2); 2,160 to 924 s (3.3); 2,140 to 1,337 s
  (6.9); 2,120 to 1,396 s (1.0); 2,100 to 1,464 s (1.1); 2,080 to 1,565 s (1.7); 2,060 to 2,151 s (9.8); **2,040 from 2,151 s to the end at 4,804 s (44.2 min)**.
* **Throughput by pointer** (policy transitions/s per rollout, median [min, max], rollouts): 2,220 210.5 [154.0, 353.9] (7); 2,200 243.2 [105.7, 340.9] (11);
  2,180 373.1 [119.1, 553.8] (14); 2,160 273.4 [106.8, 369.2] (8); 2,140 316.2 [106.5, 476.6] (21); 2,120 270.0 [110.6, 429.4] (2); 2,100 93.7 (1); 2,080 243.0
  [85.9, 374.7] (3); 2,060 306.3 [66.1, 458.1] (24); 2,040 266.4 [81.7, 572.3] (134). Session median 273.2 transitions/s (s1: 222.4).
* **Periodic checkpoints** (H2 alignment: 708,712 + j x 102,400): `ckpt_000811112` (pointer 2,180), `913512` (2,160), `1015912` (2,140), `1118312` (2,060),
  `1220712`, `1323112`, `1425512`, `1527912`, `1630312`, `1732712`, `1835112` (all 2,040): **11 periodic**, plus `ckpt_000708712` (initial) and `final`
  (1,864,900): 13 checkpoints, each pinned (`checkpoint.json`) and re-checked by verify-run.

## 6. The frozen final policy (close audit), paired with s1's audit and the tape

Audited landings 2,128 and 1,966; tick 0 descriptive. Final weights `policy.pth` `8afdb8ad01fa99cf...`. The sticky labels (`m9|g2|reach|<landing>|<k>`) and the
audit action keys carry no session component: s2's 20 sticky episodes at 2,128 draw the same masks and uniforms as s1's and the tape's first 20 keys (a paired
measurement under different weights).

| start | sticky verified clears of 20 | endings | unperturbed | deterministic | tape p_hat (keys) / tape on keys 0-19 | B |
| ---: | ---: | --- | ---: | --- | --- | ---: |
| **2,128** | **13 / 20** (s1: 8 / 20) | 13 clears, 6 falls, 1 horizon | **13 / 20** (s1: 10) | **clear** (verified; 2,220 ticks, 10 targets) | 0.490 (200) / 7 of 20 | **15** |
| **1,966** | **3 / 20** (s1: not audited) | 3 clears, 17 falls | 4 / 20 | fall (2,209 ticks, 8 targets) | 0.050 (40) / 2 of 20 | 10 |
| tick 0 | 0 / 20 (s1: 0) | | | no clear | | |

Per key k = 0..19 at 2,128 (c clear, f fall, h horizon):

```
tape  hfchfhccchfhchfchhcf   7
s1    fhfcfcfcffffcffcfccc   8
s2    cfccfcfccccfcfcfhccc  13
```

s2 vs s1 on identical keys: both clear 7, s1 only 1, s2 only 6, neither 6. s2 vs the tape: both 5, tape only 2, s2 only 8, neither 5. At 1,966: tape
`fffffffhfffffffchffc`, s2 `fcfffffffffffffcffcf` (both 1, tape only 1, s2 only 2, neither 16).

* **Rule outcome INCONCLUSIVE:** D_2 = 2,128 (13 >= 10 at 2,128; 3 < 10 at 1,966), R_2 = none (13 < B = 15). `D/R_if_every_claimed_clear_were_verified` the
  same (13 claimed = 13 verified). **Reported, never deciding:** R_unperturbed = 2,128; the deterministic episode from 2,128 clears; FRONTIER_BACKED true.
* Value calibration (reported only): at 2,128 start V +4.57 against a realised mean return +5.23 (gap -0.66; s1: +1.84), start entropy 3.985 nats (93.2 % of
  4.2767); at 1,966 start V +4.57 against -2.43 (gap +7.00, optimistic), entropy 3.348 (78.3 %).
* Entropy per rollout (fraction of maximum): 87.9 % after s2's first update, minimum 83.9 % (rollout 93), maximum 92.8 % (rollout 20), **90.1 % at the end**
  (s1 ended at 90.7 %); explained variance 0.42 -> 0.56 at the end (median 0.46, range 0.05-0.77); median approx_kl 0.0090; recent-episode mean return 4.54 in
  the first rollout, 2.93 in the last.

## 7. Resources against the caps

| resource | peak / used | cap |
| --- | ---: | ---: |
| session clock | 5,480.8 s | 8,700 s |
| training wall | 4,804.2 s | 4,800 s (the registered valid end) |
| native ticks (session) | 10,841,552 (per phase in section 3) | per phase |
| policy transitions (this session) | 1,156,188 | 3,072,000 |
| main process private memory | 1,350.3 MB (sampler; the clock's own reading 1,468.5 MB) | 3,072 MB |
| process tree private memory | 6,511.1 MB | 9,216 MB |
| process tree working set | 2,378.7 MB | 4,096 MB |
| lowest system available memory | 6,225.2 MB | at least 1,024 MB |
| lowest system commit free | 12,679.7 MB | at least 2,048 MB |
| BattleShip processes (peak) | 10 (1,090 samples at 5 s) | 10 |
| memory breach | none | |

## 8. Integrity, evidence and verification

| check | result |
| --- | --- |
| verification | 68 / 68 exact; every clear counted in a registered measure replayed (the 16 audit sticky clears); 20 training clears, 14 probe clears, 18 diagnostics exact |
| `verify-run --session 2` (against `runs/m9_g3/s1`, before any copy, output `logs/m9_g3_s2_run/verify_run.json`, copied to `derived/`) | **`ok: true`, 0 problems**: metadata 2,187 files / 5,780 JSONL lines, 0 failures; 13 checkpoints with pins and g3 identity; training 3,577 / probes 423 / drift 5 / audit 103 records re-derived; resume checks cross-checked (previous_sessions equal to s1's record, inputs = s1's final state, initial checkpoint members = s1's final members); frontier rebuilt from the records = the log (pointer 2,040, 9 moves, 22 attempts, 30 deferred); tape recorded at the open as `resume.inputs`, equal to the registered reuse; rule recomputed INCONCLUSIVE / 2,128 / none = recorded; line recomputed CONTINUE = recorded. Re-run after the copies into `launch/` and `derived/`: `ok: true` again (`verify_run_after_copies.json`) |
| drift | 5 of 5 (no tape drift) |
| protected trees | the eight (rd1 166, rd2 62, rd3 77, rd4 93, m9_g1 2,740, m9_g1_eval 1,393, m9_g2_s1 9,779, **m9_g3_s1 4,935**) equal their D: increments at both preflights, at the close, and after the backup by the tool (`post_trees_tool_check.txt`) and the independent re-hash (0 missing / 0 extra / 0 bad each, `post_trees_independent_check.txt`) |
| write guard, provenance | no write under any other `runs/` tree, `rl/` or `docs/` during the session; 0 provenance violations; `leftover_processes.json` empty |
| constraints | no RNG seed inspected, logged, controlled, compared or hashed (keyed sha256 draws only); process restart was the reset for every episode; P1 / P2 PASS (the submit / consume / input-tick contract); the submitted canonical words are the replay truth (68 / 68 exact); every start a prefix of the agent's own two verified rd4 routes; no fixture, TAS or recording read; no hardcoded route or waypoint; no native, decomp or submodule change |

**Evidence.** `runs/m9_g3/s2/` (Git-ignored): 4,361 files / 476,913,781 bytes at the close; after the copies (logs/m9_g3_s2_run -> `launch/` except the two
outputs, the whole of `logs/m9_g3_s2_prep/` -> `launch/prep/` (byte-equal, `diff -rq`), the snapshot record and its verify JSON -> `launch/`, `verify_run.json` and
`report.json` -> `derived/`) **4,478 files, 477,564,684 bytes**. Increment **`D:\BattleShip_runs_backup\2026-10-08_incr_m9_g3_s2`**, manifest sha256
**`a696538766c381ebcfbbb0f8a9b6d98b516d4d585b0c1f41510007e749d1dd0e`**: tool backup PASS (4,478 / 4,478 copied, 0 hash mismatches, 06:53:30Z); separate tool
verify `--source runs/m9_g3/s2` PASS (06:53:44Z, `verification.json` PASS); independent `independent_increment_check.ps1`: checked 4,478, missing 0, extra 0, bad 0,
PASS. **Total `runs/` coverage: 432,800 source files, 0 uncovered, 14 increments** (`post_coverage.txt`). Post-backup logs live in `logs/m9_g3_s2_run/`, outside the
increment.

**The saved state for a later session** (`session/final_state.json` sha256 `f9cf6c15e4759c8c22b3133f765f7617ebbeba67a2b47242a9508fcdfdcbbd8e`; a session 3 is
permitted by the line rule, needs its own preparation (the predecessor registry has no s2 entry yet: `predecessor_problems(3)` today returns "session 2's tree
has no registered increment facts (an unregistered predecessor)") and its own approval):

| file | sha256 |
| --- | --- |
| `training/checkpoints/final/model.zip` (1,112,120 bytes) | `e6d2c7d48b71470bdd9574ee721ba2182c5bc09068febd1154df0bdc6b8f0ad9` |
| its `policy.pth` member | `8afdb8ad01fa99cf7ff7958e449740d062d5eae62dd6b436bbaf7cdb0c8b5913` |
| its `policy.optimizer.pth` member (3,630 updates; Adam step 36,300 on 12 parameters) | `18013ea1776240a9f9d574f5590bef08cd6179779eb70ec1ba1316f746b9f27f` |
| `training/checkpoints/final/curriculum_state.json` (pointer 2,040; f 5 / need 320 / have 233; sessions [1, 2]; num_timesteps 1,864,900; next_episode 7,454; attempt_counter 35) | `cc7480df06b739ca5745b8d23730394f051fd5f58f69c9d0dea92e794f2cbef5` |
| `input/tape_baseline.json` | `81fa52c21078b2c2...` (content `d915fab9...`) |
| line contract / next session seed | `90eac1a6...` / 1003 |

## 9. Departures and notes

* **Dates.** The authorising message is dated 2026-10-07 (`authorised_on`, the approval text and the Part B log directory `launch_2026-10-07`). The launch session
  crossed midnight before the snapshot (local and UTC), so the artifacts created on 2026-10-08 carry that date: the D: snapshot `2026-10-08_m9_g3_s2`, the
  increment `2026-10-08_incr_m9_g3_s2` and this record. The approval's own string reads "Part C of the launch session of 2026-10-07" (the tool composes it from
  `--authorised-on`).
* **The close phase took 364.5 s against the 300 s figure in `WALL_CAPS_S`.** The close is not clock-enforced in the code (`finish` runs with no phase set; the
  value is used by the budget projection only); the session clock total (5,480.8 s) stayed far inside the 8,700 s cap and nothing was marked. It hashed eight trees
  (about 2.4 GB; s1's close took 88 s for seven). Reported as a fact, not acted on.
* No pre-launch fix, no tool copy and no edit: the four s2 tools ran as found; no tracked file was modified; nothing was staged.
* The rule's reason string says "D_1 ... R_1" because `m9_g3_s1_rule_v1` is the per-session rule; the record's `session` is 2 and the line rows carry k = 2.
* The two audited landings are 2,128 and 1,966 (the pointer passed 2,128 and the next landing is the depth chain's next link); s1 audited 2,128 only, so the 1,966
  readings have no s1 pair.

## 10. What this does and does not say

* It says: resumed from s1's exact final state, a second 80-minute session of the same recipe under the same frontier rule took the pointer through nine strips
  (2,220 -> 2,040) and produced a frozen policy that clears **13 of 20** sticky episodes from the last landing state 2,128 (s1's frozen policy: 8 on the same keys;
  the open-loop tape: 7 on those keys, p_hat 0.49 over 200), which meets the depth bar (10) and not the reach bar (15). Hence INCONCLUSIVE with D_2 = 2,128, and the
  line continues rather than ending on budget.
* It also shows, as facts and not decisions: the frontier stalled at 2,040 for the last 44 minutes (five failed strip tests at 1-6 of 12-17, live strip rate
  0.25-0.37 at the attempts; the training strip rate there was 0.43 in each of its last two full hundreds and over its last 79 outcomes); two attempts at 2,060 passed the strip and were blocked by the 2,128
  re-check (5 / 16, 6 / 17), i.e. the late strips were trained while the 2,128 landing fluctuated around the bar; the next landing, 1,966, is at 3 of 20.
* It does not say anything about a session 3, other seeds or budgets. No s3 was run; whether to prepare one is the user's decision.

## 11. git status at the end

HEAD = origin/main = `e73e58970f9f74ebbef6fb5c9aad93b907f08e84`; no commit, push, branch or pull request; `git diff --check` clean;
`git status --porcelain --untracked-files=all` shows only new files: `?? docs/rl_m9_g3_s2_approval.json`, `?? docs/rl_m9_g3_s2_results_2026-10-08.md`.
