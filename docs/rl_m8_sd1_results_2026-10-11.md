# M8-sd1 results (2026-10-11)

**Status: one authorised native session, run once, unattended.** Part B (zero native ticks outside the registered test suites) held in full; Part C ran exactly once: the
source snapshot, the approval, one full preflight, one detached session, the post-run verification, the copies, the D: increment and this record. No retry, extension, repair,
sd2 or rd5. No commit, push, branch or pull request. No tracked file was modified. The session date is **2026-10-11**, the local date when Part B started (19:33 EDT); the
session crossed midnight and every dated name still uses 2026-10-11, as instructed.

**Scope label** (carried by every sd1 record): *first time-directed continuation of archive `m8_rd_a1` (rd1, rd2, rd3 and rd4 as closed) under `m8_rd_select_v4`
(`m8_rd_select_v3` with two registered changes: the length-factor scale and a record bound on eligibility); one session, one set of keyed draws; no control arm; a search for
trajectories, not a policy result, not a learning result, not a comparison of v4 with v3.*

## 1. Outcome

**PROGRESS** under `m8_sd1_rule_v1` (digest `8267341f2af80dc1d1f086edf1114ea8a2b8bb68e31a08de8bf9fb7fe5b567a2`); line status **`SD2_PROPOSABLE_NEW_REFERENCE`**; rd5 unchanged
(permitted before and after sd1; neither consumed nor granted). No flag, no stop (S3 not triggered, S5 0 bound violations, S7 not triggered), no invalid or incomplete reason.

| item | value |
| --- | --- |
| best verified clear (the archive's new record reference) | sd1 candidate cid **901**, kind `clear`, iteration **15795**: **`completion_input_tick` 2,086**, `completion_time_passed` 2,085, 2,086 words, native action digest `a2a85903e704aab4819a4c6bb8e73d3b69fffdcdfce08a85f7e5d24f4a4a4e23`; route `runs/m8_rd_sd1/routes/T_clear_best` |
| against the old reference | 2,315 / 2,314 (rd4 cid 239, iteration 11286): **229 input ticks shorter (9.9 %)**; 205 ticks inside the PROGRESS bar 2,291 |
| reported tiers (reported only) | 2,199 (floor 0.95 T_rec) **reached**; 2,083 (floor 0.90 T_rec) **not reached, by 3 ticks**; 2,000 not reached (by 86) |
| in seconds (the runbook's conversion, 60 per second) | about 34.8 s (`completion_time_passed` 2,085), against about 38.6 s for the old record |
| verified clears | exactly one (the pool held one candidate) |
| the three inherited descriptive replays | all exact (section 8); no `INHERITED_REPLAY_INEXACT` |
| dilution (reported only) | DILUTION_PERSISTS (below-floor 42.0 %, fatal 33.2 %) |

## 2. What was run

| item | value |
| --- | --- |
| checkout | `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, branch `main`; HEAD = `origin/main` = the remote's `main` = `7009c9e36d52e2ec4ed0ff83095794a2c2c4f0fd` ("Add the speed-discovery search (sd1)") at the start and at the end |
| sd1 source fingerprint (`rl/m8_sd1_*.py`, `tools/m8_sd1/*`) | `f7fadda5ec11b3dd` (B0, before and after each of the three passes, in the snapshot, the approval and both preflights) |
| executable | `build-us/Release/BattleShip.exe` `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee` (the archive's pin) |
| source snapshot | `D:\BattleShip_source_snapshots\2026-10-11_m8_sd1`: 159 files, 3,580,109 bytes, PASS; `snapshot.json` sha256 `110bbdd469d46d9db13addf717b80629ef3e616f9b8c779673223ddaab076b0b` |
| approval | `docs/rl_m8_sd1_approval.json` (new, untracked), sha256 `6aa13ccc80c05b6c73d9763befb2bc5a4b9931b3371ac86b1f874a4b1ebe701b`, written 2026-10-12T02:49:00Z; authorisation quoted verbatim (25 lines) from `logs/m8_sd1_run/authorisation_sd1_2026-10-11.txt`, authorised on 2026-10-11 |
| full preflight (once) | `python -B -X utf8 rl/m8_sd1_session.py preflight`, 22:49:15 to 23:10:39 EDT, exit 0, `ok: true`, problems `[]` |
| launch | `powershell -NoProfile -ExecutionPolicy Bypass -File tools/m8_sd1/launch_detached.ps1 -Session sd1 -Repo 'C:/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip'` from Git Bash: **pid 38812 at 2026-10-12T03:10:56Z** (23:10:56 EDT); S7 check at 23:11:01 (pid alive, `session_stdout.txt` empty, no "refused") |
| the session's own preflight | inside `run`, 23:10:56 to about 23:39:08 EDT (unit 87 / 87 again) |
| session clock | 2026-10-12T03:39:08Z to 04:32:46Z, `elapsed_s` 3,218.1 (hard cap 3,600) |
| process end | `state.json` phase `done`, decision PROGRESS; `session_stderr.txt` empty; `leftover_processes.json` empty |
| wait | `python -B -X utf8 tools/m8_sd1/wait_session.py --session sd1 --hours 3.5` (the parser offers `--hours`), 23:11:07 to 00:32:54 EDT, exit 0 (`done`, process gone) |

## 3. Part B (all held; zero native ticks outside the test suites)

Every command ran in Git Bash with forward slashes; every output is under `logs/m8_sd1_run/` (nothing under `logs/m8_sd1_prep/`). Local times (EDT, 2026-10-11).

| step | start - end (duration) | result |
| --- | --- | --- |
| B0 git state | 19:33:06 - 19:33:08 (2 s) | HEAD = origin/main = `git ls-remote origin refs/heads/main` = `7009c9e`; `git status --porcelain --untracked-files=all` empty; nothing staged; `git diff --check` clean; fingerprint `f7fadda5ec11b3dd` (session CLI and tool agree); all 16 sd1 files and the proposal in HEAD, LF |
| B1 three passes (`tools/m8_sd1/three_passes.py --session sd1 --out logs/m8_sd1_run/partB/three_passes`, no `--allow-git-gate`) | 19:33:53 - 21:00:36 (86 min 43 s) | **THREE_CONSECUTIVE_PASSES**: unit 87 / 87 (840 / 838 / 709 s), e2e PASS digest **`4cadf507c1c4fbc9`** three times (1,000 / 935 / 881 s); fingerprint unchanged before and after each pass |
| B1 g3 rule self-test | 21:00:47 (< 1 s) | PASS (0 problems), s1 `dea9965a3989bce5`, line `d9d82885703c016d` |
| B1 g1 evaluation (`rl/m9_eval_tests.py unit`) | 21:00:47 - 21:01:53 (66 s) | 29 / 29 |
| B1 g2 (`rl/m9_g2_tests.py unit`) | 21:01:53 - 21:10:14 (8 min 21 s) | 29 / 29 |
| B1 g1 (`rl/m9_tests.py unit`) | 21:10:14 - 21:15:39 (5 min 25 s) | 62 / 63, only `identity_names_every_registered_pin` (the registered failure) |
| B1 g3 unit | 21:15:39 - 21:34:26 (18 min 47 s) | 29 / 29 |
| B1 g3 e2e | 21:34:27 - 21:49:38 (15 min 11 s) | PASS **`078f46c445d8adc5`** |
| B1 rd1 / rd2 / rd3 / rd4 unit | 21:49:38 - 22:06:10 | 48 / 48 (2 min 35 s), 27 / 27 (1 min 39 s), 67 / 67 (4 min 24 s), 79 / 79 (7 min 53 s) |
| B1 rd4 / rd3 / rd2 / rd1 e2e | 22:06:10 - 22:29:32 | E2E PASS each (10 min 51 s, 8 min 10 s, 3 min 19 s, 1 min 1 s) |
| B1 the five M8 rule self-tests | 22:29:32 - 22:29:34 | PASS: rd1 `e0bbfe21...`, rd2 `f9779faa...`, rd3 `fae00396...`, rd4 `246813ee...`, sd1 `8267341f...` (0 problems each) |
| B2 registered digests + B7 budget + the line consequence | 22:29:52 - 22:30:01 (9 s) | all nine equal: rule `8267341f2af80dc1`, select_v4 `eb08059242eef123`, select_v3 `fd69a0332de9db28`, select_v2 `a7d1953b7de76040`, claims `758d465b4235252f`, artifacts `bb5f0133eb842753`, draws `b248d9f076607bf6`, overlays `c6b8d52db89c217e` (rd4's closing) and `a5d0af34a00b115e` (sd1's open). B7: pessimistic 3,415 s (open 150, exploration 3,025, verification 240) inside the 3,600 s cap, valid (1,766 ticks/s projected against 667 needed), no trimming |
| B4 independent re-hash (`tools/m8_sd1/independent_increment_check.ps1`) | 22:30:10 - 22:30:16 (6 s) | rd1 166, rd2 62, rd3 77, rd4 93: `missing=0 extra_in_backup=0 bad=0 result=PASS` each. The tool's verify was NOT run on any earlier increment (S3) |
| B3 / B4 (R1) / B5 / B6 `preflight --skip-unit` | 22:30:23 - 22:40:02 (9 min 39 s) | exit 1 with exactly one problem: `no approval record at docs\rl_m8_sd1_approval.json (the session is not authorised)`. R1 ok for the four trees (166 / 62 / 77 / 93, manifests `e81226d7` / `6775281e` / `b6e13ecb` / `7ff2b29d`); R2/R4 ok at four levels (audits of 8,264 / 19,062 / 26,371 / 37,312 cells); R3 no problem (contract keys 6 / 7 / 7 / 8), executable at the pin, controller CVars absent, status table verified; R5 both overlays at their digests (23,539 v3-eligible, 23,253 v4-eligible, 323 bound cells, 286 of them v3-eligible); the three inherited trajectories (7,013 ticks); coverage 446,554 files, 0 uncovered; readiness ok (7,397 MB available, 16,853 MB commit free) |
| B8 the machine | 22:40:19 | no BattleShip process; readiness ok (7,597 MB / 17,034 MB); no new alert; git clean |
| the line consequence | (with B2) | computed by `m8_sd1_rule.apply` / `line_status` on eight constructed cases; equal in every case to the authorised list: precedence INVALID > INCOMPLETE > PROGRESS > RECORD_BELOW_MARGIN > NO_SHORTER_CLEAR; INVALID -> REPAIR_NEEDED, counts `None`; INCOMPLETE after exploration started -> COUNTED_INCOMPLETE (counts; a repeat is sd2); INCOMPLETE before exploration started -> NOT_STARTED (does not count; sd1 may be repaired and run again); best <= 2,291 -> PROGRESS, new reference; 2,291 < best < 2,315 -> RECORD_BELOW_MARGIN, new reference, not progress; otherwise NO_SHORTER_CLEAR (sd2 only with a stated reason); rd5 copied unchanged (rd4's `rule.json`: `rd5_permitted` true) |
| Part B end | 22:40:36 | |

## 4. Part C, the launch path

| step | local time | result |
| --- | --- | --- |
| C1 snapshot (`rl/m8_sd1_snapshot.py snapshot --dest D:/BattleShip_source_snapshots/2026-10-11_m8_sd1`) | 22:40:51 - 22:41:15 | PASS, 159 files, no mismatch, git head `7009c9e`, fingerprint `f7fadda5ec11b3dd` |
| C1 tool verify | 22:41:21 | PASS (`verify_2026-10-12T024121Z.json`): 159 files, 0 mismatches, 0 extra, 0 external mismatches, executable equal |
| C1 independent re-hash (`snapshot.py powershell` -> `logs/m8_sd1_run/independent_snapshot_rehash.ps1`, run from Git Bash) | 22:41:23 | `checked=160 bad=0 exe=30a3913b... exe_ok=True result=PASS snapshot_json=110bbdd4...` (159 files and the external `guide.md`) |
| C2 approval (`tools/m8_sd1/write_approval.py --session sd1 ...`) | 22:41:37 - 22:49:00 | written, exit 0; the open check inside it passed. From here to the launch: no commit, no edit, no `runs_backup.py verify` |
| C3 full preflight, once | 22:49:15 - 23:10:39 | `ok: true`, problems `[]`: unit 87 / 87 (832 s), the five rule self-tests PASS, approval `approved`, snapshot "recorded, PASS and equal to the repository", readiness 6,813 MB / 16,495 MB, coverage 0 uncovered |
| C4 launch + S7 | 23:10:56 / 23:11:01 | pid 38812 alive; no refusal |
| C5 wait | 23:11:07 - 00:32:54 (81.8 min) | done, exit 0 |

## 5. The open phase

| item | result |
| --- | --- |
| R1 (the four earlier trees against their increments) | ok at the open (166 / 62 / 77 / 93 files) and again at the close |
| R2 / R4 | rd1, rd2, rd3, rd4 archive facts and ledger audits ok; the three recorded session digests recomputed; the inherited record facts equal the pinned ones (section 12) |
| R3 | no pin problem; contract keys 6 / 7 / 7 / 8 |
| R5 | rd4's closing overlay `c6b8d52d...` and sd1's open overlay `a5d0af34...` reproduced |
| R6 | `runs/m8_rd_sd1/` materialised: `base/` (rd4's five data files and manifest), both overlay row files with the stamped companion `derived/open_overlay.json`, the stamped base record `derived/base.json`, the first sd1 checkpoint 46 (`archive_meta.json` `created_utc` 2026-10-12T03:38:54Z, carried to checkpoint 57) |
| P1 | PASS: the tick-0 record equals the archive pin `2817d8cf...` (two standby-promoted processes, host frames equal); the two pinned Track 1 traces replayed word for word (3,361 words `f6ac1593...`, 2,560 words `0766f0f3...`); the return self-test refused the corrupted end record (`prefix_end`, `position_x`); 6,208 ticks |
| identity at the open | **16 / 16 exact** (26,183 ticks): `top_level_10` cell 30164 (the record's terminal cell), `top_level_9` cell **30042** (the 1,898 arrival), `top_level_8` cell 27398, four highest-weight, four keyed launch-or-A2, five keyed eligible |
| the record re-verified (`record_open.json`) | **exact**: 2,315 words, native action digest `de1228be4146b720adc3f1272a9e65a8c0dcd7882b83134949f3893adfef8045` (= rd4 claim `t`, cid 239, iteration 11286), all four clear facts, **`completion_input_tick` 2,315, `completion_time_passed` 2,314**, ten targets |
| open ticks and wall | 34,706 ticks (= 6,208 + 26,183 + 2,315; cap 70,000), 32.5 s (cap 240 s) |

## 6. Exploration

| item | value |
| --- | --- |
| native ticks | **6,000,000** (the registered tick cap; valid from 2,000,000); stop `budget, 6,000,000 ticks`, before the 50-minute wall cap |
| duration | 2,758.4 s arm wall (phase 2,760.8 s; cap 3,000 s); 2,175 ticks/s (rd4 1,861) |
| returns / dispatches | 3,671 (iterations 13,886 to 17,556, contiguous), all standby-promoted; 3 cut jobs, 0 aborted, 0 lifecycle failures; prefix replay 93.7 % of ticks |
| the clear | found at iteration 15795 (the 1,910th sd1 dispatch), after about 3.11 M exploration ticks: start cell 30102 (level 9, L 2,059), a 27-tick ending burst |
| archive | 37,312 -> **44,007 cells** (+6,695), bursts 13,886 -> 17,554, events 27,775 -> 35,118; checkpoint 46 -> 57; 59,159 replacements; top eligible level 9, its median L 2,128 (S3 limit 3,000: not triggered) |
| mechanism readings (reported only) | returns from cells seen >= 8: 38.3 % (rd4 22.8 %); new cells per return 1.82 (rd4 3.14); returns by the start cell's session: rd1 10.6 %, rd2 15.8 %, rd3 9.0 %, rd4 49.3 %, sd1 15.3 %; left-of-wall returns 45.8 % (rd4 40.8 %); 0 dispatches from wall-top cells |
| analytic selection at the open (v3 against v4 on the same cells) | level shares identical; top-level mass ahead of the record pace 0.054 -> 0.084, within one burst of the level's shortest 0.027 -> 0.047, at or below 2,000 0.019 -> 0.035; mean dispatch L 1,570 -> 1,535 |

**Archive growth and the selection's dispatches by level.** "Ahead of pace" = dispatches to cells with L below the record route's own arrival at that level (read at runtime
from the record candidate's break table: 43, 120, 399, 609, 880, 982, 1,339, 1,838, 2,066, 2,315); a reading, never a weight. rd4's columns are the same readings over rd4's
3,480 dispatches.

| level | cells open -> close (+new) | sd1 dispatches (rd4) | ahead of the record pace sd1 (rd4) | within one burst of the level's shortest at the open, sd1 (rd4) | shortest L open -> close |
| ---: | --- | --- | --- | --- | --- |
| 0 | 1,766 -> 1,944 (+178) | 133 (133) | - | 53 (27) | 0 -> 0 |
| 1 | 2,767 -> 3,312 (+545) | 130 (145) | 2 (0) | 28 (22) | 26 -> 26 |
| 2 | 3,297 -> 3,928 (+631) | 154 (172) | 1 (0) | 18 (15) | 91 -> 91 |
| 3 | 4,591 -> 5,235 (+644) | 170 (184) | 51 (36) | 12 (3) | 152 -> 152 |
| 4 | 5,418 -> 5,956 (+538) | 217 (229) | 65 (45) | 8 (2) | 254 -> 254 |
| 5 | 4,845 -> 5,486 (+641) | 241 (223) | 70 (41) | 9 (1) | 584 -> **433** |
| 6 | 4,274 -> 5,188 (+914) | 333 (341) | 8 (4) | 35 (25) | 931 -> 931 |
| 7 | 5,107 -> 5,742 (+635) | 433 (502) | 0 (0) | 63 (38) | 1,339 -> **1,237** |
| 8 | 2,342 -> 3,553 (+1,211) | 627 (555) | 1 (0) | 168 (112) | 1,838 -> **1,776** |
| 9 | 2,901 -> 3,658 (+757) | 1,233 (996) | **337** (127) | 190 (66) | 1,898 -> 1,897 |
| 10 | 4 -> 5 (+1) | terminal | - | - | 2,315 -> **2,086** |

Level-9 dispatches at or below L 2,000: 141. Left-floor landings: 15 (shortest 1,911) at the open, 20 (shortest 1,850) at the close. The level-7 arrival moved for the
first time in the archive's history (1,339 -> 1,237), but only after the clear was found; the clear's route keeps the old right side (section 7).

## 7. The verification pool and the best clear

The frozen engine registered 1,768 candidates (1,732 `left`, 35 `t`, 0 `l0`, **1 clear-kind**). The pool (clear-kind with `first.clear < 2,315`, fastest first) held exactly one
candidate, which was also the whole progress pool (`first.clear <= 2,291`).

| order | candidate | first.clear | replayed `completion_input_tick` | replayed `completion_time_passed` | exact |
| ---: | --- | ---: | ---: | ---: | --- |
| 1 | cid 901, iteration 15795, kind `clear`, 2,086 words | 2,086 | **2,086** | **2,085** | **yes** (native action digest equal to the words, every consumed tick, the break table, the four clear facts, the clock equal to the registered clear tick) |

The pool closed at the first exact replay (remaining 0, none faster). The replay's facts (`routes/T_clear_best/metadata.json`): route identity `upper_moving_platform`
(`btt_route_rule_v1`, the same crossing as rd4: wall-top landing `l0` at 1,694, first qualified entry 1,738); left targets broken at 1,837 (target 6), **1,897 (target 8)** and
2,085 (target 1); final game status 5, 0 targets remaining. Against the old record (target 8 at 2,066, target 1 at 2,315), the new route breaks target 8 on the fall from
target 6 instead of landing and climbing back for it; the right side and the crossing are the record's.

**The best verified clear against the bar and the record:** 2,086 <= 2,291 (PROGRESS) and < 2,315; tiers: 2,199 reached; 2,083 and 2,000 not reached.

## 8. The three inherited descriptive replays (rd4's unverified clear trajectories; reported only)

| rd4 cid / iteration | registered clear tick | replayed `completion_input_tick` / `completion_time_passed` | native action digest | exact |
| --- | ---: | --- | --- | --- |
| 849 / 12559 | 2,324 | 2,324 / 2,323 | `1ce7388e13c8c817...` | yes |
| 979 / 12823 | 2,341 | 2,341 / 2,340 | `37791c7926694f56...` | yes |
| 656 / 12146 | 2,348 | 2,348 / 2,347 | `1d8a57821904366f...` | yes |

7,013 ticks; no `INHERITED_REPLAY_INEXACT` flag. rd4's registry therefore holds five clear trajectories that all replay exactly (2,315, 2,324, 2,326, 2,341, 2,348).

## 9. The close

| check | result |
| --- | --- |
| close identity replays | **16 / 16 exact**: `wall_top` 18767, `left_of_wall` 19529, `left_target_broken` 43189, `top_level_10` 41080, `top_level_9` 30961, `top_level_8` 43190, ten keyed-random |
| verification ticks and wall | 31,687 ticks (2,086 pool + 7,013 inherited + 22,588 close identity; cap 400,000), 20.8 s (cap 360 s) |
| five-part audit | ok: 44,007 cells, 17,554 bursts, 35,118 events, 44,007 prefixes reconstructed |
| prefix chain rd1 -> rd2 -> rd3 -> rd4 -> sd1 | ok (`events.jsonl`, `bursts.idx.jsonl`, `bursts.bin` byte-identical prefixes at every level) |
| the four earlier trees (R1 at the close) | ok (166 / 62 / 77 / 93, manifests unchanged) |
| write guard | 0 violations (126 protected roots: every tree under `runs/` but sd1's) |
| stamp audit | ok: 32 stamped files, 6 JSONL headers, 17 exemptions, 0 failures |
| closing overlay under v4 | 27,841 v3-eligible, 27,603 v4-eligible, 317 bound cells (238 v3-eligible) |

## 10. Resources against the caps (N2 included)

| measure | peak / minimum | cap |
| --- | ---: | ---: |
| main process private | 1,252.9 MB (`memory_summary.json`; the clock's `peak_main_private_mb` 817.5) | 3,072 MB |
| process-tree private | 4,613.5 MB | 9,216 MB |
| process-tree working set | 2,034.7 MB | 4,096 MB |
| system available (minimum) | 5,926 MB | >= 1,024 MB |
| system free commit (minimum) | 12,335 MB | >= 2,048 MB |
| processes in the tree | 30 | |
| **game (BattleShip) processes** | **maximum 10**: in all 608 of the session's 5-second samples (03:39:08Z to 04:32:45Z; 228 samples at 10) and in all 596 of this session's own 30-second machine samples (19:32:59 to 00:46:43 EDT). **No transient 11th was recorded**, during the record's open replay or at any other time; a transient shorter than the 5-second sampling interval cannot be excluded by either sampler | 10 |
| breach | none | |
| leftover game processes after the run | none | none |

## 11. Integrity, evidence and backups

| item | result |
| --- | --- |
| `verify-run` (output `logs/m8_sd1_run/verify_run.json`, 00:33:13 - 00:39:42 EDT) | **`ok: true`, problems `[]`**: checkpoints `archive` 57 and `archive.prev` 56 verified, `archive.tmp` absent; audit ok (44,007 / 17,554 / 35,118); prefix chain ok; stamp audit ok (36 files, 6 headers, 17 exempt); outcome PROGRESS and line `SD2_PROPOSABLE_NEW_REFERENCE` recomputed equal; 4 replays |
| `report` (`logs/m8_sd1_run/report.json`, 00:39:42 - 00:46:23) | exit 0, stderr empty |
| copies (N4) into `runs/m8_rd_sd1/` (00:47:10 - 00:47:11) | `derived/verify_run.json`, `derived/report.json`; `launch/` 67 files, of which the only JSON-like files are stamped sd1-tool records (`preflight_full.json`, `partB/preflight_skip_unit.json`, `partB/three_passes/passes.json`, `source_snapshot_record.json`, `snapshot_verify_2026-10-12T024121Z.json`); every hand capture is `.txt` (`b2_b7_line.json.txt` and `machine_samples.jsonl.txt` renamed because they carry no stamp; my two helper scripts as `session_scripts/*.txt`) |
| `verify-run` again after the copies (00:47:18 - 00:53:49) | `ok: true`, problems `[]`; stamp audit 43 files, 0 failures |
| the D: increment `D:\BattleShip_runs_backup\2026-10-11_incr_m8_sd1` | `runs_backup.py backup --source runs/m8_rd_sd1` and `verify --source runs/m8_rd_sd1`: `verification PASS: files 130 bytes 211061918 hash mismatches 0 problems 0`, exit 0 each; manifest `4a204dcb77cadcc8129ef9da9c879099dae665a77cc42e4ed9403c7719d30dbc`; independent re-hash `checked=130 source_files=130 backup_files=130 missing=0 extra_in_backup=0 bad=0 result=PASS` |
| the earlier trees, independent re-hash only (00:54:33 - 01:10:44) | **18 / 18 PASS**, 0 missing, 0 extra, 0 bad: rd1 166, rd2 62, rd3 77, rd4 93, m9_g1 2,740, m9_g1_eval 1,393, m9_g2/s1 9,779, m9_g3/s1 4,935, s2 4,478, s3 3,779, s4 3,486, s5 4,302, s6 2,187, m7r 5,163, m7s 9,103, m7u 2,286, m7u2 4,143, m7u3 11,023. The tool's verify was not run on any earlier increment. The older trees held only by the base backup `2026-09-28` (377,359 files, 17 GB, no per-tree increment) were not independently re-hashed; they are covered by the coverage check below |
| total `runs/` coverage (01:10:54 - 01:12:41) | `ok: true`, **446,684 source files, 0 uncovered**, 19 increments (+1: `2026-10-11_incr_m8_sd1`); skipped as before: `2026-09-29_incr_m7t_logs`, `2026-09-30_incr_m7u_logs` (no top-level record), `2026-10-01_m7u3_prep` (not under `runs/`) |
| constraints | no RNG seed was inspected, logged, controlled, compared or hashed; every episode a fresh (standby-promoted) process; the submit / consume / input-tick contract checked per tick on every return and replay; canonical Track 1 controller words are the replay truth; every route is the agent's own (cells from rd1-rd4 and sd1 exploration only); no human recording, fixture or TAS was read; no hardcoded route or waypoint; no native, decomp or submodule change |

## 12. The inherited record facts pinned in `rl/m8_sd1_resume.py` (N1)

`INHERITED_RECORD`, `RD4_FACTS`, `EXPECTED_RD4_CLOSE_OVERLAY` and `EXPECTED_OPEN_OVERLAY5` are literals in `rl/m8_sd1_resume.py` that pin **the structure of rd4's closed archive**:
every level's cell count and shortest arrival (0: 1,766 / 0; 1: 2,767 / 26; 2: 3,297 / 91; 3: 4,591 / 152; 4: 5,418 / 254; 5: 4,845 / 584; 6: 4,274 / 931; 7: 5,107 / 1,339;
8: 2,342 / 1,838; 9: 2,901 / 1,898; 10: 4 / 2,315), the four level-10 arrivals (2,315, 2,324, 2,326, 2,348), the top eligible level (9, shortest 1,898 at cell 30042), the
left-floor landings (15, shortest 1,911), the wall-top cells (18318, 18767, 26944), the two verified clears (2,315 / 2,314 cid 239; 2,326 / 2,325 cid 194), the three unverified
clear trajectories, rd4's totals (37,312 cells, 13,886 bursts, 27,775 events, checkpoint 45, 3,480 returns, 5,590,384 exploration ticks, PROGRESS m 4, rd5 permitted), and both
overlays' per-level figures. At the open they are **read back from rd4's closed tree** (`inherited_record_facts`, the overlays recomputed twice) **and compared**
(`record_fact_problems`; any difference refuses the session). They are integrity facts only: `rl/m8_sd1_select.py`, `rl/m8_sd1_claims.py` and `rl/m8_sd1_rule.py` do not
reference them (checked by search in this session), the selection reads the live archive, and `source_guard5` asserts that no census number enters the selection, claims, rule or
run modules. **They were never used for selection.** At this open every pinned fact equalled the tree (R2 ok).

## 13. The line

`rule.json.line`: status **`SD2_PROPOSABLE_NEW_REFERENCE`**, `session_counts` true, `exploration_ticks` 6,000,000 (not provisional). The new record reference is cid 901,
`completion_input_tick` 2,086, `completion_time_passed` 2,085, digest `a2a85903...`. **An sd2 under the same design with this reference may be proposed. It needs its own
preparation and its own authorisation; it was not started.** No third session without a review. The rd line is copied through: `rd5_permitted` true before and after sd1,
not consumed, not granted (source `runs/m8_rd_rd4/sessions/rd4/rule.json`).

## 14. The machine, and departures from section 11 of the preparation record

**Processes observed** (this session's sampler, one sample every 30 s, each appended and the file closed at once: `logs/m8_sd1_run/machine_samples.jsonl`, copied as
`launch/machine_samples.jsonl.txt`):

- **No node, Playwright, vmmem / vmmemWSL, IntelliJ (`idea64`) or new Claude Code process** appeared at any sample from 19:32:59 to 00:46:43 EDT. `wslservice.exe` (the WSL
  service; no VM running) and `jetbrainsd.exe` (JetBrains' protocol daemon, 81 MB; not the IDE) were present throughout.
- **Claude processes present at the baseline (19:32 EDT), not closed:** the Claude desktop app (34400 and its helpers), this session's Claude Code process (30472), and
  **four Claude Code CLI processes of other sessions** (26020, 37532, 16984, 40404; 390 to 483 MB private each), whose sessions all reported `isRunning: false`. I treated them
  as the state the owner left (sessions closed, processes resident in the app) and watched for any NEW Claude Code process; none appeared. One desktop helper (31088) exited
  between 19:33 and 20:03.
- **Microsoft Edge in background mode** (`--no-startup-window`, no renderer, no window or page; main pid 22816 started 18:10:04, before this session) was present at the
  baseline; it **relaunched itself at 22:10:05** (new main pid 42596, parent 22816, same flags, no renderer) while the rd4 e2e suite ran. Recorded, not closed.
- Memory before the launch: minimum 6,692 MB available / 16,402 MB commit free (431 samples); during the session: minimum 5,970 / 12,388 (137 samples).

**Departures and notes:**

1. Part B outputs, the authorisation file and every launch-path output are under `logs/m8_sd1_run/` (amendment S4), not `logs/m8_sd1_prep/launch_<date>/` as section 11
   drafted; nothing was written under `logs/m8_sd1_prep/`.
2. B4 used the independent re-hash and the session's R1 only (amendment S3); the tool's verify ran only on the new sd1 increment, with `--source runs/m8_rd_sd1`.
3. The independent re-hash after the run covers the 18 trees with their own increments; the base-backup trees were covered by the coverage check only (section 11).
4. A machine sampler of mine (`python.exe`, about 17 MB) ran from 19:32 to 00:46 EDT; it was restarted twice (19:33:43 and 22:10:44) to mark the background Edge processes
   as baseline. It closed nothing.
5. `launch/launch_timeline.txt` in the tree is a copy taken at 00:47; the live file `logs/m8_sd1_run/launch_timeline.txt` continues with the backup and re-hash times.
6. The session crossed midnight; every dated name uses 2026-10-11 (the snapshot, the increment, the approval date, this record).

## 15. What it does and does not say

It says: the agent's own archive search, under `m8_rd_select_v4` with a fixed reference and keyed draws, produced a controller sequence that clears Mario's Break the Targets
in **2,086 input ticks**, verified by exact fresh-process replay from tick 0, 229 ticks (9.9 %) shorter than the previous verified record. It does not say anything about a
policy or learning (no network, observation or reward is involved); that v4 caused it (one session, no control arm); that the route is robust (exact replay only; a
different executable, `.o2r` or configuration needs re-verification); or anything about the 7.43-second figure. The gain is the target-8 detour removed; the crossing and
the right side are the record's.

## 16. Files and git status

New files only: `docs/rl_m8_sd1_approval.json` and this record (untracked, for the owner to commit); `logs/m8_sd1_run/**` (Git-ignored); `runs/m8_rd_sd1/**` (Git-ignored,
backed up); `D:\BattleShip_source_snapshots\2026-10-11_m8_sd1`; `D:\BattleShip_runs_backup\2026-10-11_incr_m8_sd1`. No tracked file was modified; nothing staged; no commit.

`git status --porcelain --untracked-files=all` at the end:

```text
?? docs/rl_m8_sd1_approval.json
?? docs/rl_m8_sd1_results_2026-10-11.md
```
