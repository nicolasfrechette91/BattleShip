# M8-sd2 results (2026-10-12)

**Status: one authorised native session, run once, unattended.** Part B (zero native ticks outside the registered test suites) held in full; Part C ran exactly once: the
source snapshot, the approval, one full preflight, one detached session, the post-run verification, the copies, the D: increment, the post-run checks and this record. No retry,
extension, repair, sd3 or rd5. No commit, push, branch or pull request. No tracked file was modified. The session date is **2026-10-12**, the local date when Part B started
(20:23:56 EDT); the session crossed midnight and every dated name still uses 2026-10-12, as instructed. The launch prompt's amendments A1 to A10 of the independent review of
2026-10-12 were applied wherever they differ from section 11 of `docs/rl_m8_sd2_prep_2026-10-12.md`.

**Scope label** (carried by every sd2 record): *second time-directed continuation of archive `m8_rd_a1` (rd1, rd2, rd3, rd4 and sd1 as closed) under `m8_rd_select_v4`
unchanged, with the record reference moved to sd1's verified clear 2,086 / 2,085; one session, one set of keyed draws; no control arm; a search for trajectories, not a policy
result, not a learning result, not a comparison of v4 with v3.*

## 1. Outcome

**PROGRESS** under `m8_sd2_rule_v1` (digest `d1220a8b2706367f372dd63db24c2a2bea591420196fefe5b33322fa009ca988`); line status **`SD3_AFTER_REVIEW_NEW_REFERENCE`** (counts;
the best verified clear is the archive's new record reference; an sd3 under the same design may be proposed only after a written review); rd5 unchanged (permitted before
and after sd2; neither consumed nor granted). No flag, no stop (S3 not triggered, top-level median L 1,975; S5 0 bound violations; S7 not triggered), no invalid or incomplete
reason.

| item | value |
| --- | --- |
| best verified clear (the archive's new record reference) | sd2 candidate cid **1360**, kind `clear`, iteration **20491**: **`completion_input_tick` 1,885**, `completion_time_passed` 1,884, 1,885 words, native action digest `05a178352380e403aef9f8224b1afc2ec3911c200383c5963b671d9d7d112646`; route `runs/m8_rd_sd2/routes/T_clear_best` |
| against the reference | 2,086 / 2,085 (sd1 cid 901, iteration 15795): **201 input ticks shorter (9.6 %)**; 177 ticks inside the PROGRESS bar 2,062 |
| reported tiers (reported only) | 1,981 (floor 0.95 T_rec) **reached**; 1,877 (floor 0.90 T_rec) **not reached, by 8 ticks**; 1,800 (round) not reached (by 85) |
| in seconds (the runbook's conversion, 60 per second) | about 31.4 s (`completion_time_passed` 1,884), against about 34.8 s for the old record |
| verified clears | three, all exact: 1,885 / 1,884 (cid 1360), 1,929 / 1,928 (cid 1243), 1,964 / 1,963 (cid 1009) |
| inherited descriptive replays | zero (as registered: sd1's registry holds no unverified clear trajectory); no `INHERITED_REPLAY_INEXACT` |
| dilution (reported only) | DILUTION_PERSISTS (below-floor 36.2 %, fatal 27.0 %; sd1 42.0 % / 33.2 %) |

**The line in one line:** PROGRESS (1,885 / 1,884 <= 2,062) -> `SD3_AFTER_REVIEW_NEW_REFERENCE`: the session counts, 1,885 / 1,884 (cid 1360) is the new record reference,
any sd3 needs a written review first; rd5 copied through (permitted before and after, not consumed, not granted).

## 2. What was run

| item | value |
| --- | --- |
| checkout | `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, branch `main`; HEAD = `origin/main` = the remote's `main` (`git ls-remote`) = `5985a8378a52cf0ba6951a97cf7b53a38afb63cd` ("Add the second speed-discovery search (sd2): code") at the start and at the end |
| sd2 source fingerprint (`rl/m8_sd2_*.py`, `tools/m8_sd2/*`) | `b22c0af8f833b205` (B0 from the session CLI and from `three_passes.fingerprint`, before and after each of the three passes, in the snapshot, the approval and both preflights) |
| executable | `build-us/Release/BattleShip.exe` `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee` (the archive's pin) |
| interpreter (A9) | `C:\Users\kill_\AppData\Local\Programs\Python\Python313\python.exe` (3.13.2) both as `sys.executable` of `python -B` and as PowerShell's `(Get-Command python).Source`: the same executable |
| source snapshot | `D:\BattleShip_source_snapshots\2026-10-12_m8_sd2`: 231 files, 4,575,805 bytes, PASS; `snapshot.json` sha256 `3ea6205f139bbc83d0d17d2ceb6df81a8a35364ed872aef0e6a18eb14cb87fa2` |
| approval | `docs/rl_m8_sd2_approval.json` (new, untracked), sha256 `555f9840e911fbbcb702d6d86e1209ac79f49620b1132ff822810504ab77ddc0`, written 2026-10-13T05:06:23Z; authorisation quoted verbatim (23 lines) from `logs/m8_sd2_run/partB/authorisation_sd2_2026-10-12.txt`, authorised on 2026-10-12 |
| full preflight (once) | `python -B -X utf8 rl/m8_sd2_session.py preflight`, 01:06:34 to 01:41:40 EDT, exit 0, `ok: true`, problems `[]` |
| launch | `powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/m8_sd2/launch_detached.ps1 -Session sd2 -Repo 'C:/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip'` from Git Bash (A5): **pid 32896 at 2026-10-13T05:42:02Z** (01:42:02 EDT), head `5985a83` |
| launch check (A8) | `python -B -X utf8 tools/m8_sd2/check_launch.py --session sd2` at 01:42:02 EDT (0 s after the launch): **PASS, exit 0** (record ok, pid alive, age 0 s, no "refused", no "Traceback", 0 BattleShip processes) |
| the session's own preflight | inside `run`, 01:42:02 to about 02:30:06 EDT (unit 101 / 101 again, 1,338 s) |
| session clock | 2026-10-13T06:30:06Z to 07:30:03Z, `elapsed_s` **3,596.9** (hard cap 3,600): open 31.5 s, exploration 3,007.0 s, verification 17.2 s, the close checks the rest (07:21:03 to 07:30:02Z, about 539 s) |
| process end | `state.json` phase `done`, decision PROGRESS; `session_stderr.txt` empty; `leftover_processes.json` empty |
| wait (A7) | `python -B -X utf8 tools/m8_sd2/wait_session.py --session sd2` (default 3.5 h), 01:42:10 to 03:30:59 EDT, **exit 0** (`done`, process gone) |

## 3. Part B (all held; zero native ticks outside the test suites)

Every command ran in Git Bash with forward slashes; every output is under `logs/m8_sd2_run/partB/` (nothing under `logs/m8_sd2_prep/`). Local times (EDT; Part B started on
2026-10-12 and ended on 2026-10-13). Timeline: `logs/m8_sd2_run/partB/timeline.txt`.

| step | start - end (duration) | result |
| --- | --- | --- |
| baseline + machine sampler | 20:24:04 / 20:24:10 | `tools/m8_sd2/machine_sampler.py` every 30 s to `logs/m8_sd2_run/machine_samples.jsonl` (alerts to `machine_alerts.txt`), running to the end of the session; baseline in `partB/b8_baseline_processes.txt` |
| B0 git state | 20:24:16 - 20:24:18 (2 s) | HEAD = origin/main = `git ls-remote origin refs/heads/main` = `5985a83`; `git status --porcelain --untracked-files=all` empty; nothing staged; `git diff --check` clean; fingerprint `b22c0af8f833b205` (session CLI and tool agree); every sd2 file and the two sd2 documents in HEAD, `i/lf w/lf` |
| B1 three passes (`tools/m8_sd2/three_passes.py --session sd2 --out logs/m8_sd2_run/partB/three_passes`, no `--allow-git-gate`) | 20:24:39 - 22:31:56 (2 h 7 min 17 s) | **THREE_CONSECUTIVE_PASSES**: unit 101 / 101 (1,469 / 1,486 / 1,433 s), e2e PASS digest **`2adc51de5cf46121`** three times (1,093 / 1,073 / 1,083 s); fingerprint unchanged before and after each pass |
| B1 the seven rule self-tests | 22:31:56 - 22:31:58 (2 s) | PASS, 0 problems each: g3 s1 `dea9965a3989bce5` and line `d9d82885703c016d`; rd1 `e0bbfe212d3c0079...`, rd2 `f9779faac95feede...`, rd3 `fae00396494b8e96...`, rd4 `246813eebb7c7559...`, sd1 `8267341f2af80dc1...`, sd2 `d1220a8b2706367f...` |
| B1 g1 evaluation (`rl/m9_eval_tests.py unit`) | 22:31:58 - 22:33:08 (70 s) | 29 / 29 |
| B1 g2 (`rl/m9_g2_tests.py unit`) | 22:33:08 - 22:42:15 (9 min 7 s) | 29 / 29 (the git-state gate passes on the committed tree) |
| B1 g1 (`rl/m9_tests.py unit`) | 22:42:15 - 22:48:06 (5 min 51 s) | 62 / 63, only `identity_names_every_registered_pin` (the registered failure) |
| B1 g3 unit | 22:48:06 - 23:09:12 (21 min 6 s) | 29 / 29 |
| B1 g3 e2e | 23:09:12 - 23:25:30 (16 min 18 s) | PASS **`078f46c445d8adc5`** |
| B1 rd1 / rd2 / rd3 / rd4 unit | 23:25:30 - 23:42:15 | 48 / 48 (2 min 24 s), 27 / 27 (1 min 22 s), 67 / 67 (4 min 36 s), 79 / 79 (8 min 22 s) |
| B1 sd1 unit and e2e | 23:42:15 - 00:11:38 | 87 / 87 (12 min 58 s); e2e PASS **`4cadf507c1c4fbc9`** (16 min 25 s) |
| B1 rd4 / rd3 / rd2 / rd1 e2e | 00:11:38 - 00:35:16 | E2E PASS each (11 min 44 s, 8 min 5 s, 3 min 1 s, 48 s) |
| B2 registered digests (A2: `rl/m8_sd2_session.py approval-template`, not `status`) | 00:35:44 - 00:35:58 (14 s) | all equal to the preparation record: rule `d1220a8b2706367f...`, `m8_rd_select_v4` at 2,086 `8e09d332f16bb6cb...`, v4 at 2,315 (sd1's session event) `eb08059242eef123...`, v3 `fd69a0332de9db28...`, v2 `a7d1953b7de76040...`, claims `4c87a3e69954b4ea...`, artifacts `3d06da399dd8cb9c...`, draws `ba0cdfe8c8359d60...`, overlays `f6af59157fb2b420...` (sd1's closing under v4 at 2,315) and `2481c0d33abc5c02...` (sd2's open under v4 at 2,086); the reference 2,086 / 2,085, previous 2,315 / 2,314, margin 24, bar 2,062, bound 2,061, tiers 1,981 / 1,877 / 1,800, nine contracts (`partB/b2_approval_template.json`, `partB/b2_b7_line_check.txt`) |
| B7 budget + the line consequence | 00:35:58 (< 1 s) | B7: pessimistic 3,415 s (open 150, exploration 3,025, verification 240) inside the 3,600 s cap, valid (1,766 ticks/s projected against 667 needed), no trimming. The line consequence computed by `m8_sd2_rule.apply` on ten constructed cases and `write_approval.line_consequence()` equal in every case to the authorised list: precedence INVALID > INCOMPLETE > PROGRESS > RECORD_BELOW_MARGIN > NO_SHORTER_CLEAR; INVALID -> `REPAIR_NEEDED`, counts `None`; INCOMPLETE before exploration -> `NOT_STARTED` (does not count; the repeat procedure); INCOMPLETE after exploration -> `COUNTED_INCOMPLETE` (counts; sd3 only after a review stating the cause); <= 2,062 -> PROGRESS, new reference, review first; 2,063 to 2,085 -> RECORD_BELOW_MARGIN, new reference, not progress, review first; 2,086 or none -> NO_SHORTER_CLEAR, the reference stays, review with a stated reason; rd5 copied (sd1's `rule.json`: `rd5_permitted` true; not consumed, not granted) |
| B4 independent re-hash (`tools/m8_sd2/independent_increment_check.ps1`, A5 form) | 00:36:26 - 00:36:35 (9 s) | rd1 166, rd2 62, rd3 77, rd4 93, sd1 130: `missing=0 extra_in_backup=0 bad=0 result=PASS` each. The tool's verify was NOT run on any earlier increment |
| B3 / B4 (R1) / B5 / B6 `preflight --skip-unit` | 00:36:42 - 00:51:05 (14 min 23 s) | exit 1 with exactly one problem: `no approval record at docs\rl_m8_sd2_approval.json (the session is not authorised)`. R1 ok for the five trees (166 / 62 / 77 / 93 / 130, manifests `e81226d7` / `6775281e` / `b6e13ecb` / `7ff2b29d` / `4a204dcb`); R2/R4 ok at five levels (audits of 8,264 / 19,062 / 26,371 / 37,312 / 44,007 cells; sd1's four session digests recomputed equal); R3 no problem (contract keys 6 / 7 / 7 / 8 / 9), executable at the pin, controller CVars absent, status table verified, P1 traces consistent; R5 both overlays at their digests (24,599 v4-eligible, 4,697 bound cells, 3,242 of them v3-eligible); zero inherited candidates; the record candidate (2,086 words, `a2a85903...`); coverage 446,684 files, 0 uncovered, 19 increments; readiness ok (5,997 MB available, 14,385 MB commit free, C: 92.9 GiB, D: 1,629.0 GiB) |
| B8 the machine | 00:51:33 | no BattleShip, node, Playwright, vmmem / vmmemWSL / WSL host or IntelliJ process; no new Claude process (section 14); git clean; 6,286 MB available, 14,813 MB commit free (`partB/b8_machine.txt`) |
| B9 interpreter (A9) | 00:51:43 | the same executable (section 2; `partB/b9_interpreter.txt`) |
| Part B end; authorisation file | 00:52:05 | `partB/authorisation_sd2_2026-10-12.txt` (Part C verbatim with the session date) written as the last Part B file |

## 4. Part C, the launch path

| step | local time | result |
| --- | --- | --- |
| C1 snapshot (`rl/m8_sd2_snapshot.py snapshot --dest D:/BattleShip_source_snapshots/2026-10-12_m8_sd2`) | 00:52:28 - 00:52:58 | PASS, 231 files, no mismatch, no identity code or document mismatch, git head `5985a83`, fingerprint `b22c0af8f833b205` |
| C1 tool verify | 00:52:59 - 00:53:00 | PASS (`verify_2026-10-13T045259Z.json`): 231 files, 0 mismatches, 0 extra, 0 external mismatches, executable equal |
| C1 independent re-hash (`snapshot.py powershell` -> `logs/m8_sd2_run/independent_snapshot_rehash.ps1`, run from Git Bash with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File`) | 00:53:13 - 00:53:14 | `checked=232 bad=0 exe=30a3913b... exe_ok=True result=PASS snapshot_json=3ea6205f...` (231 files and the external `guide.md`) |
| C2 approval (`tools/m8_sd2/write_approval.py --session sd2 ...`) | 00:53:24 - 01:06:23 | written, exit 0; the open check inside it passed; zero inherited candidates; the S2 rule printed. From here to the launch: no commit, no edit, no `runs_backup.py` verify or backup, no new folder on D: |
| C3 full preflight, once | 01:06:34 - 01:41:40 | `ok: true`, problems `[]`: unit 101 / 101 (1,343 s), the six M8 rule self-tests PASS, approval `approved`, snapshot "recorded, PASS and equal to the repository", readiness 5,981 MB / 14,302 MB, coverage 0 uncovered |
| C4 launch + launch check (A8) | 01:42:01 - 01:42:02 / 01:42:02 | pid 32896 alive; `check_launch.py` exit **0** (PASS) |
| C5 wait (A7) | 01:42:10 - 03:30:59 (108.8 min) | done, exit 0 |

## 5. The open phase

29,567 native ticks (cap 70,000) in 31.5 s (cap 240 s); every check passed before the first dispatch.

| item | result |
| --- | --- |
| R1 to R5 (`sessions/sd2/open.json`) | R1: the five earlier trees equal their increments (166 / 62 / 77 / 93 / 130 files; manifests `e81226d7` / `6775281e` / `b6e13ecb` / `7ff2b29d` / `4a204dcb`); R2/R4: sd1's closing archive (44,007 cells, 17,554 bursts, 35,118 events, checkpoint 57 / 56, iterations 0..17,556 contiguous, the four session digests recomputed equal: v2 `a7d1953b...`, v3 `fd69a033...`, v4 at sd1's reference `eb080592...`), sd1's line read (`SD2_PROPOSABLE_NEW_REFERENCE`, counts, `rd5_permitted` true); R3: no pin problem, contract keys 6 / 7 / 7 / 8 / 9; R5: sd1's closing overlay under v4 at 2,315 `f6af59157fb2b420...` (27,603 v4-eligible) and sd2's open overlay under v4 at 2,086 `2481c0d33abc5c02...` (24,599 v4-eligible; 4,697 bound cells, 3,242 of them v3-eligible) |
| R6 materialisation | `base/` = sd1's five closing files and manifest (checkpoint 57), `derived/base.json`, `derived/open_overlay.json` / `.jsonl`, `derived/sd1_closing_overlay.jsonl`; sd2's session event at iteration 17,557 with v4 at 2,086; the first sd2 checkpoint 58 |
| P1 | the tick-0 record equals the archive pin `2817d8cf3494...`; both pinned traces replayed: 6,208 native ticks |
| open identity replays | **16 / 16 exact** (21,273 ticks): `top_level_10` 41080 (the 2,086 cell), `top_level_9` 30961, `top_level_8` 43189, three highest-weight (43343, 43190, 43695), four keyed launch-or-A2 (29545, 30392, 14991, 26217), five keyed eligible (20838, 22441, 6383, 38366, 37860) and the keyed top-up 6670 |
| the record re-verified at the open | **exact**: sd1 cid 901's 2,086 registered words (digest `a2a85903e704aab4...`) replayed from tick 0 in a fresh process: `completion_input_tick` 2,086, `completion_time_passed` 2,085, all four clear facts, 10 targets (2,086 ticks; `sessions/sd2/record_open.json`) |
| inherited descriptive candidates | zero (read from sd1's registry by the rule) |

## 6. Exploration

| item | sd2 | sd1 (for comparison) |
| --- | --- | --- |
| native ticks | **5,874,929** in 3,004.2 s: the **50-minute wall cap bound** (stop `wall_cap`); the 6,000,000 tick cap was not reached; valid (>= 2,000,000) | 6,000,000 in 2,758.4 s (the tick cap bound) |
| rate | 1,955.6 ticks/s (prefix share 93.2 %, new exploration ticks 399,969) | 2,175.2 ticks/s (93.7 %, 375,009) |
| returns / dispatch iterations | 3,769 (17,557..21,325), all standby-promoted; 0 cut, 0 aborted, 0 lifecycle failures | 3,671 |
| archive | 44,007 -> **49,928 cells** (+5,921; 1.57 per return); bursts 17,554 -> 21,323; events 35,118 -> 42,657; checkpoints 58 to 70 | +6,695 (1.82 per return) |
| clear-event candidates | 14 `clear`-kind (the first at iteration 18,013 with 2,053), 33 `t`, 1,709 `left`, 0 `l0`; 1,756 candidates; max targets online 10 | 2 clear-kind (one trajectory) |
| bound violations / doomed incumbent replacements / newly descent-doomed / revivals | sd2's part 0 / 2,661 / 6,003 / 4,586 (cumulative at sd2's close 0 / 15,850 / 33,222 / 20,295) | cumulative at sd1's close 0 / 13,189 / 27,219 / 15,709 |
| dilution (reported only) | below-floor 1,363 / 3,769 (36.2 %), fatal 1,016 (27.0 %): DILUTION_PERSISTS | 42.0 % / 33.2 % |
| launch-capable cells created | 324 (86.0 per 1,000 returns) | 384 (104.6) |

**By level** (the record pace is candidate 901's break table read at runtime; "ahead" = dispatches from cells with L below the record's arrival at that level, for both
sessions against the same 2,086 pace; readings only, nothing here is a selection input):

| level | cells at the open -> close (new) | shortest L open -> close | record pace | sd2 dispatches (ahead of pace) | sd1 dispatches (ahead of pace) | sd1 new cells |
| ---: | --- | --- | ---: | --- | --- | ---: |
| 0 | 1,944 -> 2,185 (+241) | 0 -> 0 | | 138 (0) | 133 (0) | 178 |
| 1 | 3,312 -> 3,885 (+573) | 26 -> 26 | 43 | 158 (0) | 130 (2) | 545 |
| 2 | 3,928 -> 4,478 (+550) | 91 -> 91 | 120 | 168 (2) | 154 (1) | 631 |
| 3 | 5,235 -> 5,754 (+519) | 152 -> 152 | 399 | 160 (45) | 170 (51) | 644 |
| 4 | 5,956 -> 6,536 (+580) | 254 -> 254 | 609 | 221 (56) | 217 (65) | 538 |
| 5 | 5,486 -> 6,535 (+1,049) | 433 -> 433 | 880 | 273 (63) | 241 (70) | 641 |
| 6 | 5,188 -> 6,021 (+833) | 931 -> **871** | 982 | 335 (8) | 333 (8) | 914 |
| 7 | 5,742 -> 6,222 (+480) | 1,237 -> 1,237 | 1,339 | 411 (6) | 433 (0) | 635 |
| 8 | 3,553 -> 4,359 (+806) | 1,776 -> 1,776 | 1,838 | 650 (**74**) | 627 (1) | 1,211 |
| 9 | 3,658 -> 3,944 (+286) | 1,897 -> **1,832** | 1,898 | 1,255 (**135**) | 1,233 (4) | 757 |
| 10 | 5 -> 9 (+4) | 2,086 -> **1,885** | 2,086 | 0 | 0 | 1 |
| all | 44,007 -> 49,928 (+5,921) | | | 3,769 (389) | 3,671 (202) | 6,695 |

**E7 at both bounds** (`report.json` `D8_overlays.E7`): at the open, the sd2 bound `L <= 2,061` excluded 4,697 cells (3,242 v3-eligible; level 7: 63, 8: 1,992, 9: 2,637,
10: 5) and left 24,599 v4-eligible; sd1's bound 2,290 would have excluded 317 (238; 27,603 v4-eligible). At the close, the sd2 bound excludes 3,400 cells (2,254
v3-eligible; 7: 95, 8: 1,741, 9: 1,560, 10: 4) with 29,136 v4-eligible; sd1's bound 222 (177; 31,213 v4-eligible). The analytic selection at the open under v4 at 2,061: top
level 9 with 34.1 % of the mass, mean dispatch L 1,476.5 (v4 at 2,290: 1,528.9; v3: 1,561.9).

## 7. The verification pool and the best clear

The pool (`first.clear` < 2,086, `clear` kind only, fastest first, batches of 3, closed at the first exact replay): **12 candidates**, all at or below 2,062 (registered
clear ticks 1,885, 1,929, 1,964, 1,978, 2,053 x 4, 2,055 x 4; two further clear-kind candidates at 2,089 and 2,100 are not shorter than the reference and not in the pool).
One batch was replayed; every replay exact; the pool closed with 9 candidates unreplayed, none faster than the best (`remaining_faster_than_best` 0). Verification 31,450 ticks
(cap 400,000) in 17.2 s (cap 360 s): the three pool replays (5,778 ticks) and the 16 close identity replays (25,672 ticks).

| order | cid | iteration | kind | `first.clear` (registered) | replayed `completion_input_tick` / `completion_time_passed` | exact | left-target breaks (target, tick) |
| ---: | ---: | ---: | --- | ---: | --- | --- | --- |
| 1 | 1360 | 20491 | clear | 1,885 | **1,885 / 1,884** | **yes** (all four clear facts, 10 targets, no problem) | (6, 1,775), (8, 1,831), (1, 1,884) |
| 2 | 1243 | 20219 | clear | 1,929 | 1,929 / 1,928 | yes | (6, 1,775), (8, 1,831), (1, 1,928) |
| 3 | 1009 | 19688 | clear | 1,964 | 1,964 / 1,963 | yes | (6, 1,775), (8, 1,831), (1, 1,963) |

Not replayed (the pool closed): cid 1225 (1,978), 219, 410, 447, 685 (2,053 each), 227, 792, 848, 921 (2,055 each).

**The best clear** (cid 1360; `routes/T_clear_best`): dispatched at iteration 20,491 from cell 46827 (level 9, created in sd2, L 1,850) with a 35-tick burst. Its replay
records the first grounded tick on floor line 0 at 1,694, target 6 at 1,775, target 8 at 1,831 and target 1 (the last) at 1,884; route identity `upper_moving_platform` (the
record's). Against the record's pace (levels 8, 9, 10 at 1,838, 1,898, 2,086) it arrives at 1,776, 1,832 and 1,885: 62 ticks ahead at level 8 (the archive's shortest level-8
L at the open was 1,776), and an ending of 53 ticks from target 8 to target 1 against the record's 188. All three verified clears share the prefix through target 8 at 1,831
and differ in the ending only.

| threshold | reached by 1,885? |
| --- | --- |
| PROGRESS bar 2,062 | yes (by 177) |
| the reference 2,086 | yes (by 201) |
| tier 1,981 (5 %) | **yes** |
| tier 1,877 (10 %) | no (by 8) |
| tier 1,800 (round) | no (by 85) |

## 8. Inherited descriptive replays

None, as registered: sd1's registry holds exactly one clear trajectory (cids 900 and 901), verified by sd1; rd4's three are sd1's exact facts and were not replayed again. No
`INHERITED_REPLAY_INEXACT` flag; no other flag.

## 9. The close

| check | result (`sessions/sd2/close.json`, 07:21:03 to 07:30:02Z) |
| --- | --- |
| the six-part audit | ok: 49,928 cells, 21,323 bursts, 42,657 events, 49,928 prefixes reconstructed |
| close identity replays | **16 / 16 exact**: `wall_top` 18767, `left_of_wall` 19529, `left_target_broken` 43189, `top_level_10` 48579, `top_level_9` 46800, `top_level_8` 43190, ten keyed (47297, 23398, 8889, 12810, 36153, 33476, 19879, 29299, 42522, 38726) |
| the prefix chain of six | ok (rd1 -> rd2 -> rd3 -> rd4 -> sd1 -> sd2, every file identical as a prefix) |
| the five earlier trees | unchanged (166 / 62 / 77 / 93 / 130 files, the pinned manifests) |
| write guard | 0 violations |
| the stamp audit | ok: 29 files, 6 headers, 16 exempt, 0 failures |
| live and ledger `seen` at dispatch | equal (3,769 dispatches, 1,997 with `seen` >= 8) |

## 10. Resources against the caps (A10)

| item | value | cap |
| --- | --- | --- |
| open ticks / wall | 29,567 / 31.5 s | 70,000 / 240 s |
| exploration ticks / wall | 5,874,929 / 3,004.2 s (the wall cap bound) | 6,000,000 / 3,000 s (+20 s grace) |
| verification ticks / wall | 31,450 / 17.2 s | 400,000 / 360 s |
| total native ticks | 5,935,946 | |
| session clock | **3,596.9 s** | 3,600 s (hard, from P1) |
| main process private (peak) | 1,419.9 MB | 3,072 MB |
| process tree private (peak) | 4,674.4 MB | 9,216 MB |
| process tree working set (peak) | 1,981.6 MB | 4,096 MB |
| system available (minimum, session sampler) | 5,074.6 MB | >= 1,024 MB |
| system commit free (minimum, session sampler) | 9,891.6 MB | >= 2,048 MB |
| BattleShip processes (maximum) | **10**, in both samplers: the session's own (665 samples at 5 s) and `machine_sampler.py` (30 s); **no transient 11th observed** in either | 10 |
| lifecycle failures | 0 | 3 |
| memory breach | none | |

**The session clock came within 3.1 s of the hard cap.** Exploration ran to its 3,000 s wall cap (sd1's rate would have hit the 6,000,000-tick cap at about 2,760 s), and
the close checks over 49,928 cells took about 539 s; the B7 projection (3,415 s pessimistic) counts the open, exploration and verification phases but not the close checks.
Nothing was cut and no cap was reached; this is reported for the review, not acted on.

## 11. Integrity, evidence and backups

| item | result |
| --- | --- |
| `verify-run` (output `logs/m8_sd2_run/verify_run.json`, 03:31:23 - 03:40:09 EDT) | **`ok: true`, problems `[]`**: checkpoints `archive` 70 and `archive.prev` 69 verified, `archive.tmp` absent; audit ok (49,928 / 21,323 / 42,657); prefix chain ok; stamp audit ok (33 files, 6 headers, 16 exempt); outcome PROGRESS and line `SD3_AFTER_REVIEW_NEW_REFERENCE` recomputed equal; 3 replays |
| `report` (`logs/m8_sd2_run/report.json`, 03:40:09 - 03:48:54) | exit 0, stderr empty |
| copies (`tools/m8_sd2/copy_launch_evidence.py --session sd2`, 03:49:07 - 03:57:56) | `derived/verify_run.json` and `derived/report.json`; `launch/` 64 files plus the snapshot record and its tool verification; the only unstamped JSON-like file, `machine_samples.jsonl`, copied as `machine_samples.jsonl.txt`; exit 0 |
| `verify-run` again after the copies (run by the copier; `logs/m8_sd2_run/verify_run_after_copies.json`) | `ok: true`, problems `[]`; stamp audit 41 files, 0 failures |
| the D: increment **`D:\BattleShip_runs_backup\2026-10-12_incr_m8_rd_sd2`** (A1) | `rl/tools/runs_backup.py backup --source runs/m8_rd_sd2 --dest D:/BattleShip_runs_backup/2026-10-12_incr_m8_rd_sd2` (03:58:27 - 03:58:28): `verification PASS: files 125 bytes 252637797 hash mismatches 0 problems 0`, manifest `2518d560f3ecf5da45b0baac5157ddd119f3e55a7540522de95a97e21dd61f16`; the tool's verify run again by `post_run_checks.py --tool-verify` on this folder only, with `--source runs/m8_rd_sd2`: PASS (10:57:25Z); independent re-hash `checked=125 source_files=125 backup_files=125 missing=0 extra_in_backup=0 bad=0 result=PASS` |
| `tools/m8_sd2/post_run_checks.py --session sd2 --tool-verify` (03:58:36 - 06:57:25) | **exit 1, `ok: false`**, for one reason only, explained in the next row. 21 folders re-hashed independently; **20 PASS** with 0 missing, 0 extra and 0 bad each: m7r 5,163, m7s 9,103, m7u 2,286, m7u2 4,143, m7u3 11,023, rd1 166, rd2 62, rd3 77, rd4 93, m9_g1 2,740, m9_g1_eval 1,393, m9_g2/s1 9,779, m9_g3/s1 to s6 4,935 / 4,478 / 3,779 / 3,486 / 4,302 / 2,187, sd1 130, sd2 125. R1 over the five M8 trees ok (166 / 62 / 77 / 93 / 130, the pinned manifests). Combined coverage ok: **446,809 `runs/` files, 0 uncovered**, 20 increments (+1). Skipped as before: `2026-09-29_incr_m7t_logs`, `2026-09-30_incr_m7u_logs` (no verification record), `2026-10-01_m7u3_prep` (not under `runs/`). Outputs: `logs/m8_sd2_run/post_run_checks.json`, `logs/m8_sd2_run/post_increments/*.txt` |
| **the one FAIL: the base backup `D:\BattleShip_runs_backup\2026-09-28`** (a finding about the tool, not about the evidence) | its `verification.json` names the whole `runs/` folder as its source (377,359 files, 15.8 GB), so `registered_increments` takes it as an increment and the independent script compares every file of today's `runs/` with it: `checked=446809 source_files=446809 backup_files=377359 missing=69450 extra_in_backup=0 bad=0 result=FAIL` (2 h 37 min). **`bad=0`**: every one of the 377,359 base files still equals its `runs/` file; **`extra_in_backup=0`**: no base file is missing from `runs/`. The 69,450 "missing" files are exactly the twenty per-tree increments' trees, file for file (m7r 5,163; m7s 9,103; m7u 2,286; m7u2 4,143; m7u3 11,023; m8_rd 166; m8_rd_rd2 62; m8_rd_rd3 77; m8_rd_rd4 93; m8_rd_sd1 130; m8_rd_sd2 125; m9_g1 2,740; m9_g1_eval 1,393; m9_g2/s1 9,779; m9_g3/s1 to s6 4,935 / 4,478 / 3,779 / 3,486 / 4,302 / 2,187; sum 69,450), each re-hashed PASS against its own increment above. The FAIL is therefore by construction of the tool's scope; sd1's run excluded the base from its re-hash on purpose and relied on the coverage check. Not repaired, not re-run (no fix allowed); reported for the review |
| the earlier trees | unchanged: R1 at the open, at the close (close checks) and after the run (post-run checks), and the independent re-hash of every per-tree increment. The tool's verify was not run on any earlier increment at any time (B4 and the post-run checks used only the independent script) |
| constraints | no RNG seed was inspected, logged, controlled, compared or hashed; every episode a fresh (standby-promoted) process; the submit / consume / input-tick contract checked per tick on every return and replay; canonical Track 1 controller words are the replay truth; every route is the agent's own (cells from rd1 to rd4, sd1 and sd2 exploration only); no human recording, fixture or TAS was read; no hardcoded route or waypoint; no native, decomp or submodule change |

## 12. The integrity literals pinned in `rl/m8_sd2_resume.py` (N1, A10)

The integrity literals of `rl/m8_sd2_resume.py` (`SD1_INCREMENT_NAME` and its manifest, `RECORD_REFERENCE6`, `SD1_RECORD_REFERENCE`, `SD1_MARGIN`, `SD1_SESSION_DIGEST`,
`SD1_FACTS`, `INHERITED_RECORD6`, `EXPECTED_SD1_CLOSE_OVERLAY_V4` with `SD1_CLOSING_OVERLAY_V4_SHA256`, `EXPECTED_OPEN_OVERLAY6` with `SD2_OPEN_OVERLAY_SHA256`) **were read
back from the real closed trees and compared** at B6 (`preflight --skip-unit`), inside `write_approval.py`, in the full preflight (C3), in the run's own preflight and at the open
of the session (R1 to R5: every comparison equal, zero problems), and **they were never used for selection**: they are integrity facts compared against what the trees hold;
the selection, claims, rule and run modules reference none of them (asserted by `source_guard6`, which passed in all three Part B passes and in both preflights), and the
selection drew from the archive's own cells under `m8_rd_select_v4` with the sd2 keyed draws only.

## 13. The line

| item | value |
| --- | --- |
| outcome | **PROGRESS** (`m8_sd2_rule_v1`, digest `d1220a8b...`) |
| line status | **`SD3_AFTER_REVIEW_NEW_REFERENCE`**: the session counts as sd2 (the line's second session); the best verified clear 1,885 / 1,884 (cid 1360, iteration 20491, digest `05a17835...`) is the archive's new record reference; an sd3 under the same design may be proposed **only after a written review** |
| sd line (copied through) | sd1: `SD2_PROPOSABLE_NEW_REFERENCE`, counts, source `sessions/sd1/rule.json` |
| rd line | `rd5_permitted_before_sd2` true, `rd5_permitted_after_sd2` true, `consumed_by_sd2` false, `granted_by_sd2` false |
| what this session did not do | no sd3, no rd5, no retry, no extension, no repair |

## 14. The machine, the amendments, and departures from section 11 of the preparation record

**A1 (the increment name).** Section 9 and section 11 step 5 of `docs/rl_m8_sd2_prep_2026-10-12.md` (and section 6.6 of the proposal) name the sd2 increment
`D:/BattleShip_runs_backup/<date>_incr_m8_sd2`; `tools/m8_sd2/post_run_checks.py` looks for the unique folder ending in `_incr_m8_rd_sd2` and refuses `--tool-verify`
otherwise. Following amendment A1 of the launch prompt, the increment is **`D:/BattleShip_runs_backup/2026-10-12_incr_m8_rd_sd2`**; this name was used for the backup, the
tool verify and every report. The preparation record was not edited.

**The other amendments.** A2: B2 compared the digests printed by `approval-template`. A3: no readiness or memory refusal occurred; no threshold or cap was lowered. A5: both
PowerShell scripts were invoked from Git Bash as `powershell.exe -NoProfile -ExecutionPolicy Bypass -File <script> <arguments>`, after reading their `param()` blocks
(`launch_detached.ps1`: `-Session` (ValidateSet sd2), `-Repo`; `independent_increment_check.ps1`: `-Source`, `-Dest`). A6: the fingerprint came from
`rl/m8_sd2_session.py fingerprint` (and agreed with `three_passes.fingerprint`). A7: the waiter exited 0. A8: `check_launch.py` exited 0 at 0 s. A9: one interpreter
(section 2). A10: sections 10 and 12.

**The machine (A4; nothing was closed).**

| process group | observation |
| --- | --- |
| Claude | at the baseline (20:24:04 EDT) 21 `claude.exe` processes: the desktop app (pid 34400 and its 10 helpers, since 2026-10-10 12:41) and 10 Claude Code CLI processes (26020, 37532, 16984, 40404, 30472, 30100, 39564, 32084, 40900 from earlier sessions, 154 to 270 MB working set each, and 32240, this session). **No new Claude process appeared** (the sampler classified every `claude.exe` pid; none outside the baseline). The nine earlier CLI processes stayed idle: 48 to 59 s of CPU each over the 4.5 hours of Part B (this session's own: 137 s); the desktop app's GPU and renderer processes accumulated more (2,194 s, 828 s), consistent with rendering this session |
| Microsoft Edge | five `msedge.exe` processes in background mode (`--no-startup-window`, started 18:10 EDT, before this session) at the baseline, passed to the sampler as baseline-quiet; they exited by themselves at about 21:09 and did not return. The WebView2 runtime (6 processes, since 2026-09-23) stayed |
| node, Playwright, vmmem / vmmemWSL / WSL hosts, IntelliJ, video tools | **none at any sample** (Part B, Part C and the post-run steps); `machine_alerts.txt` stayed empty |
| BattleShip | 0 outside the session; at most 10 during it (section 10); 0 after it (`leftover_processes.json` empty) |
| Python | the sampler, the suites, the tools and the session's own processes only (at most 8 at once, during the suites and during the run) |
| memory (machine sampler, 1,212 samples, none with an error) | Part B: at least 5,720 MB available and 13,570 MB commit free; Part C and the run: at least 5,200 MB / 10,103 MB (the session's own 5-second sampler: 5,074.6 MB / 9,891.6 MB); the post-run steps: at least 3,723 MB / 12,021 MB (the base-backup re-hash held about 2.3 GB) |

**Departures and observations.**

1. **The preparation and the launch ran on the same calendar day.** The preparation record ends at about 18:27 EDT on 2026-10-12 and recommends a later day (its decision on
   scheduling); this launch session started at 20:23 EDT the same day, on the user's launch prompt of 2026-10-12. Every Part B condition held on the committed tree. Noted only.
2. **`post_run_checks.py` re-hashed the base backup** against the whole of `runs/` and reported FAIL by construction (section 11). Not repaired.
3. **The session clock ended 3.1 s inside the 60-minute hard cap** (section 10); the B7 projection does not count the close checks. Reported for the review.
4. **The launch check ran at 0 s**, well inside the two-minute window; at that moment the run was still in its own preflight (about 48 minutes), so a later refusal would have
   shown only in `state.json` and the waiter, which both reported `done` with no refusal.
5. **The authorisation file** is `logs/m8_sd2_run/partB/authorisation_sd2_2026-10-12.txt`, the last Part B file, as section 11 of the preparation record says (the proposal named
   `logs/m8_sd2_run/`); it holds a one-line header with the session date and Part C verbatim.
6. **Helper scripts.** Part B's B1 driver and the B2 / B7 / line-consequence check were two hand-written scripts run from the session's scratch folder; copies are in
   `logs/m8_sd2_run/session_scripts/*.txt` (made after the evidence copy, so they are not in `launch/`). Neither imports anything that writes; both write only under
   `logs/m8_sd2_run/partB/`.
7. To follow the logs, `touch -a` was run on `logs/m8_sd2_run/machine_alerts.txt`, `wait_log.txt` and `timeline_partC.txt`; it creates a file only when absent: `machine_alerts.txt` was created that way and stayed empty (no alert at any sample), `wait_log.txt` possibly so, just before the waiter's first line.

## 15. What it does and does not say

It says that the archive now holds an exactly replayable, agent-generated controller sequence that clears Mario's Break the Targets in 1,885 input ticks
(`completion_time_passed` 1,884), 201 fewer than any clear verified before, with two further exact clears at 1,929 and 1,964, all found by keyed exploration from the archive's
own cells under the registered selection and verified from tick 0 in fresh processes. It says nothing about a policy or about learning; the result is not attributable to v4
as against any other selection (no control arm); it is not robust to another executable; it contains no new crossing (the route identity is the record's
`upper_moving_platform`); and it says nothing about the 7.43-second scripted baseline, which enters no sd2 quantity. The written review the line requires before any sd3 is
not part of this session.

## 16. Files and git status

| path | state |
| --- | --- |
| `docs/rl_m8_sd2_approval.json` | new, untracked (sha256 `555f9840e911fbbcb702d6d86e1209ac79f49620b1132ff822810504ab77ddc0`) |
| `docs/rl_m8_sd2_results_2026-10-12.md` | new, untracked (this record) |
| `runs/m8_rd_sd2/` | new (Git-ignored); 125 files, backed up to `D:\BattleShip_runs_backup\2026-10-12_incr_m8_rd_sd2` |
| `logs/m8_sd2_run/` | new (Git-ignored): Part B under `partB/`, the launch and post-run logs, `post_increments/`, `session_scripts/` |
| `D:\BattleShip_source_snapshots\2026-10-12_m8_sd2` | new (snapshot, its tool verification) |
| every tracked file | unchanged; nothing staged; no commit, push, branch or pull request |

`git status --porcelain --untracked-files=all` after this record (HEAD = `origin/main` = `5985a83`):

```text
?? docs/rl_m8_sd2_approval.json
?? docs/rl_m8_sd2_results_2026-10-12.md
```
