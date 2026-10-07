# M9-g3-s1 results (2026-10-07)

**Registered outcome: NULL** (`m9_g3_s1_rule_v1`, sha256 `dea9965a3989bce5...`): *D_1 = none: not even 10 of 20 at 2,128.* The frozen final policy cleared
**8 of 20** sticky episodes from the last landing state (2,128; 11 falls, 8 verified clears, 1 horizon), below the 10 the depth needs and the bar B = 15 the reach
needs; R_1 is undefined. **Line outcome: CONTINUE** (`m9_g3_line_rule_v1`, `d9d82885703c016d...`): k = 1, D_1 = none, "session 2 is proposable, with its own
approval"; **s2 is permitted** by the line rule and is NOT authorised by anything in this session. One session, one run, once; nothing was retried, extended or
repaired; nothing follows this outcome automatically. Every number below is read from `runs/m9_g3/s1/` (digests in section 9) and recomputed by `verify-run`
(section 7). The pointer reached **2,220** (four moves, 2,300 -> 2,280 -> 2,260 -> 2,240 -> 2,220) under the replenishing frontier rule, against g2-s1's one move.

Scope label (carried by every record): *M9-g3-s1: backward-algorithm robustification under the replenishing controlled frontier rule `m9_g3_frontier_v1` (PPO from
prefix-replayed start states on the agent's own two verified rd4 clears, sticky actions p = 0.25, observation btt_policy_obs_v3_entities, reward btt_reward_v2,
entropy coefficient 0.01; the g2 trigger, frozen strip test and re-checks unchanged; attempts spaced by 20 x 2^(f-1) counted strip outcomes, cap 320, no HELD and
no STALLED); the first session of a new resumable line (not an amendment of g2); a fresh policy (seed 0); one set of keyed draws; progress measured as the
sustained frontier depth D and the reliable reach R at landing states against g2-s1's pinned tape baseline reused by digest, under the registered rules; no claim
of a tick-0 policy.*

## 1. What was run

Design: `docs/rl_m9_g2_stop_review_2026-10-06.md` (section 3) as decided in `docs/rl_m9_g3_decisions_2026-10-06.md` (readings R1-R12, the authorised edit of
decision 9, the amended condition 1 of section 7); preparation `docs/rl_m9_g3_implementation.md`; re-check `docs/rl_m9_g3_recheck_2026-10-06.md`; this session's
launch conditions, the first stop and the authorised re-run in `docs/rl_m9_g3_launch_record_2026-10-07.md`. In short: g2-s1's recipe (a FRESH PPO policy, the M7n v3
network and profile, entropy coefficient 0.01, 80 minutes of training on episodes that start late on the agent's own two verified rd4 clears replayed as exact
prefixes in fresh processes, sticky actions p = 0.25 everywhere, the 8-of-20 trigger, the frozen strip test of 20 at 10 with early stopping, the re-check of every
passed landing, the fixed 4 + 6 slots) with ONE change: the attempt bounds are replaced by the spacing rule (after f consecutive failures at a pointer the next
attempt needs min(320, 20 x 2^(f-1)) counted strip outcomes there and a fresh trigger; triggers inside the spacing are logged `deferred_trigger`; no HELD, no
STALLED). The tape baseline is g2-s1's pinned table reused by digest with a 5-key drift check; nothing was measured.

| item | value |
| --- | --- |
| tree | HEAD = origin/main = `ca3cfb69a754b7c3180f9a7996ad1330c217ff7d`; no tracked file modified at any point; g3 source fingerprint `f92ca9067813b9e6` |
| launch | 2026-10-07 15:10:48 UTC, one detached session (pid 7140), `python -B -u -X utf8 rl/m9_g3_session.py run --session 1`; its own preflight (unit suite 25 / 25, rule self-test) ran first; the session clock started 15:26:47 UTC; the process exited by itself at 16:52:44 UTC; `session_stderr.txt` empty; no BattleShip process left |
| session clock | **5,156.5 s (85.9 min)** of the 8,700 s cap |
| executable | `build-us/Release/BattleShip.exe` `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee` (the archive's pin), unchanged at the close; the `.o2r` files, `gamecontrollerdb.txt` and the frozen configuration equal rd1's pins |
| approval | `docs/rl_m9_g3_s1_approval.json` sha256 `3abd556a411812ef1d6bb27c183e1aff330e47272539a949104d32fc32fb12eb` (written 14:24:00 UTC from the fresh identity after the snapshot; reused for the authorised re-run, see section 8); source snapshot `D:\BattleShip_source_snapshots\2026-10-07_m9_g3_s1` (170 files, `snapshot.json` sha256 `d6a89a84a5753dc52aa2cc39be952218c3a7f4cf076748f3a108d138723a033f`; tool verify PASS twice; independent PowerShell re-hash checked 171, bad 0, executable equal) |
| reused tape | `runs/m9_g2/s1/session/tape_baseline.json` file sha256 `81fa52c21078b2c2...`, content digest `d915fab920554774...`, copied to `input/tape_baseline.json`, verified at the open (file and content digests, every landing pinned, key counts 200 / 40, label family, lineage, sticky p, the measuring executable); bars B(2,128) = 15, B = 10 elsewhere |
| untrained policy | the fresh policy's `policy.pth` member `eb592c887fc66aaba038e0b35986463bf03153bd7fe78a3f5d80357fa517ceb0` equals g1's and g2-s1's `ckpt_000000000` member (reported, never deciding): g3-s1 against g2-s1 is one changed mechanism from identical initial weights |

## 2. Pre-launch fixes

None. The decisions record's section 6 (pre-launch hazards) is empty; no registered measure, threshold, rule, schedule or training setting was touched. The only
non-tool items of the launch are provenance: the approval-writer copy (launch record, section 4) and the reuse of the approval and snapshot for the authorised
re-run (section 8 below).

## 3. Phases

| phase | wall (cap) | native ticks (cap) | result |
| --- | ---: | ---: | --- |
| open | 0.17 s (60) | 0 | identities, pins, the reused table verified by digest, the approval copy recorded |
| P1 lineages | 23.4 s (240) | 13,923 (60,000) | PASS: both routes replayed three times each (two fresh, one through a promoted standby), exact; `T_clear` 2,326 words (completion_time_passed 2,325, completion_input_tick 2,326), `T_t` 2,315 words; shared prefix 2,298 |
| P2 staging equivalence | 42.3 s (120) | 31,998 (60,000) | PASS: 12 of 12 keyed starts equal the registered tables and a cold replay |
| T0 drift check | 15.2 s (240) | 14,440 (60,000) | PASS: the first 5 tape keys at 2,128 (`m9\|g2\|reach\|2128\|0..4`) reproduced the table's outcomes (horizon, fall, clear, horizon, fall) and the measuring session's native action digests, 5 of 5; nothing measured |
| training | 4,805.0 s (4,800) | 9,855,945 (20,000,000) | valid end: **wall cap**; **708,712 policy transitions** (cap 3,072,000), 138 rollouts, 1,380 PPO updates; prefix 8,508,024 ticks, probes 639,209 ticks |
| close audit | 115.3 s (1,200) | 183,929 (3,000,000) | all 62 planned episodes (the one audited landing, 2,128: 20 sticky + 20 unperturbed + 1 deterministic; tick 0: 20 sticky + 1 deterministic) |
| verification | 67.3 s (600) | 105,241 (1,500,000) | **43 of 43 replays exact** (tier 0: the 8 audit sticky clears; tier 1: the first 20 training clears; tier 2: one keyed probe clear per passed test, 4; tier 3: 11 diagnostics); 0 skipped, 0 errors |
| close | 88.0 s (300) | 0 | the seven protected trees equal their D: increments, no pin drift, no provenance or write-guard violation, metadata audit 2,430 files / 5,327 JSONL lines clean, no leftover process |

**Native ticks in the session: 10,205,476** (13,923 + 31,998 + 14,440 + 9,855,945 + 183,929 + 105,241). Lifecycle failures: 0 in every phase. Stale staging
events: 6 (recorded, never counted).

## 4. Training and the frontier

* Episodes 3,647: **2,202 clears (60.4 %)**, 1,388 falls, 57 horizon. By start region: strip 1,830 (738 clears, 40.3 %), near window 1,424 (1,108, 77.8 %),
  rehearsal 393 (356, 90.6 %; non-empty from pointer 2,260 on). Mean policy phase 193.8 ticks (clears 68.0, falls 345.5, horizon 1,358.6); mean sticky hits 48.5
  per episode. Native ticks per policy transition 13.9 (g2-s1: 63.1). Staged starts 3,729; the playing slots waited 1,188 s for a ready start (24.7 % of the
  training wall); 78 staged starts withdrawn for attempts.
* **The pointer moved four times** (every move on a passing frozen strip test; no landing was behind the frontier, so no re-check ever ran and every `rechecks`
  record is empty):

| move | from -> to | attempt (a at the pointer) | training wall | transitions | after failed attempts at the pointer |
| ---: | --- | --- | ---: | ---: | ---: |
| 1 | 2,300 -> 2,280 | 1 (a = 1) | 309.7 s | 5,120 | 0 |
| 2 | 2,280 -> 2,260 | 6 (a = 5) | 1,888.6 s | 92,160 | 4 |
| 3 | 2,260 -> 2,240 | 7 (a = 1) | 2,636.5 s | 199,680 | 0 |
| 4 | 2,240 -> 2,220 | 9 (a = 2) | 3,172.9 s | 296,960 | 1 |

* **Every attempt** (13; every one on a frozen snapshot, keyed starts over the strip, keyed action draws; the live rate is the clear rate of the preceding 60
  counted strip outcomes at that pointer; `f / need / have` is the spacing state at the attempt):

| # | pointer | a | f / need / have | trigger window | live rate before | frozen strip test | result | wall | wait before the next attempt at this pointer |
| ---: | ---: | ---: | --- | --- | ---: | --- | --- | ---: | --- |
| 1 | 2,300 | 1 | 0 / 0 / 129 | 8 of 8 (1.00) | 0.85 | **10 / 12** (0.83) | **MOVED -> 2,280** | 22.8 s | |
| 2 | 2,280 | 1 | 0 / 0 / 63 | 8 of 16 (0.50) | 0.37 | 9 / 20 (0.45) | FAILED_STRIP | 27.4 s | need 20: met; the next trigger came at have 154 (no deferral) |
| 3 | 2,280 | 2 | 1 / 20 / 154 | 8 of 19 (0.42) | 0.35 | 5 / 16 (0.31) | FAILED_STRIP | 27.3 s | need 40: 1 trigger deferred at have 35; attempt at 80 |
| 4 | 2,280 | 3 | 2 / 40 / 80 | 8 of 9 (0.89) | 0.50 | 9 / 20 (0.45) | FAILED_STRIP | 27.6 s | need 80: 4 deferred at have 20, 38, 51, 70; attempt at 120 |
| 5 | 2,280 | 4 | 3 / 80 / 120 | 8 of 14 (0.57) | 0.47 | 4 / 15 (0.27) | FAILED_STRIP | 25.7 s | need 160: 10 deferred at have 18 ... 158; attempt at 213 |
| 6 | 2,280 | 5 | 4 / 160 / 213 | 8 of 10 (0.80) | 0.63 | **10 / 13** (0.77) | **MOVED -> 2,260** | 24.8 s | |
| 7 | 2,260 | 1 | 0 / 0 / 308 | 8 of 19 (0.42) | 0.33 | **10 / 19** (0.53) | **MOVED -> 2,240** | 28.8 s | |
| 8 | 2,240 | 1 | 0 / 0 / 127 | 8 of 16 (0.50) | 0.37 | 7 / 18 (0.39) | FAILED_STRIP | 31.0 s | need 20: 1 deferred at have 15; attempt at 45 |
| 9 | 2,240 | 2 | 1 / 20 / 45 | 8 of 12 (0.67) | 0.43 | **10 / 17** (0.59) | **MOVED -> 2,220** | 29.8 s | |
| 10 | 2,220 | 1 | 0 / 0 / 260 | 8 of 13 (0.62) | 0.35 | 3 / 14 (0.21) | FAILED_STRIP | 30.8 s | need 20: 1 deferred at have 14; attempt at 35 |
| 11 | 2,220 | 2 | 1 / 20 / 35 | 8 of 19 (0.42) | 0.45 | 8 / 19 (0.42) | FAILED_STRIP | 32.9 s | need 40: 1 deferred at have 37; attempt at 61 |
| 12 | 2,220 | 3 | 2 / 40 / 61 | 8 of 18 (0.44) | 0.40 | 4 / 15 (0.27) | FAILED_STRIP | 30.1 s | need 80: 3 deferred at have 16, 33, 49; attempt at 88 |
| 13 | 2,220 | 4 | 3 / 80 / 88 | 8 of 20 (0.40) | 0.37 | 2 / 13 (0.15) | FAILED_STRIP | 28.4 s | need 160: 8 deferred at have 13 ... 125; training ended at have 133 |

  Totals: 4 MOVED, 9 FAILED_STRIP, 0 BLOCKED_BY_RECHECK, 0 INTERRUPTED; attempt yield 0.308 moves per decided attempt; **29 deferred triggers** (15 at 2,280, 1 at
  2,240, 13 at 2,220), 13 acted-on triggers, 50 void windows. Probe wall 367.7 s in total (7.7 % of the training wall; 22.8-32.9 s per attempt); the four playing
  slots stayed parked in every attempt (`parked_slots` 4, `probe_slots` 6, disjoint). The frontier never froze: no HELD, no STALLED, and the spacing state at the
  close was f = 4, need 160, have 133.
* **The trigger-to-test gap** (window rate minus frozen-test rate): +0.17, +0.05, +0.11, +0.44, +0.31, +0.03, -0.11, +0.11, +0.08, +0.40, 0.00, +0.18, +0.25; the
  window displays at least 0.40 by construction, the frozen tests read 0.15-0.83, and the live rate over the preceding 60 outcomes was 0.33-0.63 at every attempt
  but the first. The three moves after a failure (attempts 6 and 9) and the first-attempt move at 2,260 (live rate 0.33, test 0.53) show the test's sampling
  band in both directions.
* **Strip clear rates while training** (counted strip outcomes at the pointer, per 100 in completion order): 2,300: 0.91, 0.72 (129 outcomes); 2,280: 0.32,
  0.28, 0.43, 0.51, 0.46, 0.55, 0.65 (634); 2,260: 0.20, 0.22, 0.26, 0.17 (312); 2,240: 0.21, 0.43 (176); 2,220: 0.23, 0.29, 0.39, 0.43, 0.40, 0.65 (579). The
  strip at 2,220 (the drop toward target 1 begins here) was at 0.65 over its last 79 outcomes when the wall cap ended training, with the next attempt 27 outcomes
  away.
* **The frontier position over training time** (pointer at the rollout boundaries): 2,300 until 310 s; 2,280 from 310 s to 1,889 s (26.3 min); 2,260 from 1,889 s
  to 2,636 s (12.5 min); 2,240 from 2,636 s to 3,173 s (8.9 min); 2,220 from 3,173 s to the end at 4,805 s (27.2 min). Transitions at the moves: 5,120; 92,160;
  199,680; 296,960.
* **Throughput by pointer** (policy transitions/s per rollout, median [min, max]): 2,300: 17.9 (1 rollout); 2,280: 56.9 [40.3, 92.7] (17); 2,260: 143.6 [85.1,
  317.3] (21); 2,240: 195.1 [87.8, 366.5] (19); 2,220: 291.4 [84.5, 616.7] (80). Session median 222.4 transitions/s (g2-s1: 49.4 at 2,280 throughout).
* Handover diagnostic (descriptive, mid-hold starts vs starts at a word change, clears / n): 2,300: 99 / 116 vs 13 / 13; 2,280: 220 / 538 vs 57 / 92; 2,260:
  68 / 281 vs 2 / 27; 2,240: 50 / 157 vs 4 / 15; 2,220: 200 / 514 vs 24 / 63.
* The frontier history rebuilt by `verify-run` from the records alone equals the log (4 moves, 13 attempts, 29 deferred triggers, pointer 2,220, every attempt at or
  past its spacing need).

## 5. The frozen final policy (close audit) and the tape

Audited landings: 2,128 only (the pointer's strip never reached 2,120). Tick 0 descriptive. Every audit action is a keyed inverse-CDF draw from the final weights
(`policy.pth` member `ffce330386c8c133...`); the sticky labels are the reused tape's (`m9|g2|reach|2128|k`), so the 20 sticky episodes pair with the tape's.

| start | sticky (verified clears of 20) | endings | unperturbed (of 20) | deterministic | tape p_hat (keys) | B |
| ---: | ---: | --- | ---: | --- | ---: | ---: |
| **2,128** | **8 / 20** | 11 falls, 8 clears, 1 horizon | **10 / 20** | **clear** (verified; 2,178 ticks, 10 targets) | 0.490 (200) | **15** |
| 1,966 | not audited | | | | 0.050 (40) | 10 |
| 1,694 ... 1,248 | not audited | | | | 0.000 (40 each) | 10 |
| tick 0 | 0 / 20 | | | horizon, no clear | | |

* **Rule outcome NULL:** D_1 = none (the chain fails at 2,128: 8 < 10); R_1 = none (8 < B = 15). `D_if_every_claimed_clear_were_verified` and the R counterpart
  are also none (every claimed audit clear was verified; 8 = 8). **Reported, never deciding:** R_unperturbed = **2,128** (10 of 20 unperturbed clears from the last
  landing); the deterministic episode from 2,128 clears; FRONTIER_BACKED is vacuously true (no landing behind the frontier). Against the tape: 8 sticky clears
  where the open-loop tape's rate predicts 9.8 of 20; the policy's sticky rate from the cold start at 2,128 (never a training start) is therefore about the tape's,
  not above it.
* Value calibration at the 2,128 handover (reported only): the final critic's V was +2.91 against a realised mean return of +1.07 (gap +1.84); start entropy
  4.047 nats (94.6 % of the 4.2767 maximum). At the probe handovers the snapshot's `strip_calibration_gap` ran -3.07, -4.74, -3.01, -3.75, +1.65, -4.87 (2,300 and
  2,280), -4.99 (2,260), +2.70, -0.89 (2,240), +2.42, +0.86, +2.74, +3.22 (2,220): pessimistic early at the late strips, optimistic at 2,220.
* Entropy per rollout: 99.8 % of maximum after the first update, 96.0 % at 2,260 (rollout 36), 93.9 % at rollout 70, 90.9 % at rollout 104, **90.7 % at the end**
  (minimum 87.7 %); explained variance -0.03 -> 0.60 (rollout 36) -> 0.55 at the end; median approx_kl 0.0079; value loss 24.7 -> 4.8. Recent-episode mean return
  9.54 in the first rollout (every start at 2,300), 4.37 in the last.
* Post-target-8 share of clearing episodes' ticks per 100 training episodes: 0.41 and 0.54 in the first 200 (starts at 2,300 / 2,280 are post-target-8), then
  0.09-0.18 as the starts moved to the drop toward target 1 (where target 8 is still standing at the start).

## 6. Resources against the caps

| resource | peak / used | cap |
| --- | ---: | ---: |
| session clock | 5,156.5 s | 8,700 s |
| training wall | 4,805.0 s | 4,800 s (the registered valid end) |
| native ticks (session) | 10,205,476 (P1 13,923; P2 31,998; T0 14,440; training 9,855,945; audit 183,929; verification 105,241) | per phase, section 3 |
| policy transitions | 708,712 | 3,072,000 |
| main process private memory | 1,236.9 MB | 3,072 MB |
| process tree private memory | 6,558.9 MB | 9,216 MB |
| process tree working set | 2,437.6 MB | 4,096 MB |
| lowest system available memory | 5,786.1 MB | at least 1,024 MB |
| lowest system commit free | 10,047.8 MB | at least 2,048 MB |
| BattleShip processes (peak) | 10 (1,020 samples at 5 s) | 10 |
| memory breach | none | |

## 7. Integrity

| check | result |
| --- | --- |
| verification | 43 / 43 exact; every clear counted in a registered measure replayed (the 8 audit sticky clears; the reused tape's 100 clears were replayed in g2-s1 and are not re-replayed by design); the first 20 training clears, the 4 keyed probe clears of the passed tests and 11 diagnostics exact |
| `verify-run` (after the run, output outside the tree, then copied to `derived/verify_run.json`) | `ok: true`, no problems: metadata audit 2,436 files / 5,327 JSONL lines, 0 failures; 8 checkpoints with their pins and the g3 identity; the frontier history rebuilt from the records equals the log (4 moves, 13 attempts, 29 deferred, the schedule 20 x 2^(f-1)); the reused table equals the registered digests, pinned, 5 drift rows; the rule recomputed from the records = the recorded NULL; the line recomputed = the recorded CONTINUE |
| drift check | 5 of 5 tape keys reproduced the table's outcomes and the g2-s1 native action digests (tape drift: none) |
| pins | executable, runtime files and frozen configuration equal the archive's pins at the preflights, at the open and at the close |
| protected trees | `runs/m8_rd` (166 files), `m8_rd_rd2` (62), `m8_rd_rd3` (77), `m8_rd_rd4` (93), `m9_g1` (2,740), `m9_g1_eval` (1,393), `m9_g2/s1` (9,779) equal their D: increments at both full preflights, at the close and again after the backup (the tool and an independent PowerShell re-hash, 0 missing, 0 extra, 0 bad each) |
| write guard, provenance | no write under any other `runs/` tree, `rl/` or `docs/` during the session; no provenance violation; `leftover_processes.json` empty |
| untrained policy | `policy.pth` member `eb592c887fc66aaba038e0b35986463bf03153bd7fe78a3f5d80357fa517ceb0` equals g1's `ckpt_000000000` member (reported, never deciding) |
| constraints | no RNG seed inspected, logged, controlled, compared or hashed (every draw a Python-side keyed sha256 uniform of the `m9\|g3\|...` family, the audit's sticky labels on the reused `m9\|g2\|reach` family for pairing); process restart was the reset for every episode (training, probes, drift, audit, verification); the exact submit / consume / input-tick contract (P1 and P2 PASS); the submitted canonical words are the replay truth (43 / 43 exact); every start state a prefix of the agent's own two verified rd4 routes; no fixture, TAS or recording read (the static source guards pass in the g3, g2 and g1 suites); no hardcoded route or waypoint; no native, decomp or submodule change (executable `30a3913b...`) |

## 8. Departures and notes

* **First launch attempt stopped on memory readiness; the user authorised ONE re-run.** The Part B conditions held in full on the committed tree (launch record,
  section 1). The snapshot and the approval were written; the full preflight then refused for `available memory 3011 MB < 4096 MB` (applications started on the
  machine during the session) and the launch was stopped with zero native ticks, as the rules require. The user closed those applications and authorised exactly one
  re-run of the full preflight with the approval and snapshot reused (both valid for the unchanged identity at `ca3cfb6`; the authorised "once" had not been
  consumed). The re-run passed (`ok: true`, readiness 7,753 MB available, 16,787 MB commit free) and the single session followed. Launch record, sections 6.3-6.7.
* **Approval provenance.** The provided approval-writing tool quoted the user's message of 2026-10-06; a corrected COPY (new Git-ignored file) quoting today's
  message was run instead, the provided tool left byte-identical (launch record, section 4). No tracked file was modified at any point.
* **Order of the post-run steps** (as g2-s1): `verify-run` and `report` ran on the closed tree first (outputs under `logs/m9_g3_run/`), then the launch, preflight,
  snapshot and preparation logs were copied into `runs/m9_g3/s1/launch/` (`launch/prep/` = the whole of `logs/m9_g3_prep/`) and the two outputs into
  `derived/`, then the increment was taken. The backup, verify, independent-check, tree and coverage logs written after the backup live in `logs/m9_g3_run/`
  (`backup_m9_g3_s1*.txt`, `independent_increment_check_m9_g3_s1.txt`, `post_*.txt`), outside the increment.
* The pointer never reached 2,120, so the only audited landing is 2,128 and no re-check ran (every `rechecks` is `{}`); the other five landings carry no audit
  reading. The e2e's synthetic world is not Mario; nothing in the synthetic results transfers.
* g1's unit suite fails exactly one test on this tree (`identity_names_every_registered_pin`, the documented pre-existing failure); the g2 and g1-evaluation
  suites pass in full and the g3 suite 25 / 25 (launch record, section 3).
* This record, the approval and the launch record are new untracked files; no commit, push, branch or pull request was made and no existing file was
  modified. The external guide was not edited.

## 9. Evidence and digests

Everything lives under `runs/m9_g3/s1/` (Git-ignored; **4,935 files, 508,166,787 bytes**, the copied launch and preparation logs under `launch/` and the
`verify-run` and `report` outputs under `derived/` included) and in the D: increment **`D:\BattleShip_runs_backup\2026-10-07_incr_m9_g3_s1`** (manifest sha256
**`d12966c135fdb614f08fab2d63ff0af894d171834ed9f87c802103b9024307a5`**): tool backup PASS (copy 4,935 / 4,935, 0 hash mismatches, 16:56:28 UTC), separate tool verify
with `--source runs/m9_g3/s1` PASS (16:56:53 UTC), independent PowerShell `Get-FileHash` re-hash 4,935 source / 4,935 backup files, 0 missing, 0 extra, 0 bad.
Total `runs/` coverage afterwards: **428,322 source files, 0 uncovered** (the base and 13 increments).

**The saved state for a later session** (`session/final_state.json`; s2 is permitted by the line rule and needs its own approval; the state is evidence):

| file | sha256 |
| --- | --- |
| `training/checkpoints/final/model.zip` (1,110,611 bytes) | `669692023c2dacf838d03c94ae608d227b7598377828e7b4d1d36c7d7f3b5db8` |
| its `policy.pth` member | `ffce330386c8c1335441ac22aa34e38c6f0df2aa8635f0f6a9aec4e71dea32ee` |
| its `policy.optimizer.pth` member (Adam: 1,380 updates, step 13,800 on every one of the 12 parameters) | `c072b0dbf4a3d21e1f2ea1bab3988bbf61f9df4ff53d10fc993b09ff059af7aa` |
| `training/checkpoints/final/curriculum_state.json` (pointer 2,220; f = 4, need 160, have 133; failed attempts {2,280: 4, 2,240: 1, 2,220: 4}; 4 moves; 13 attempts; 29 deferred) | `74adedd8004b6e4900e0bcf98f3b92f6ac3ccd69d2673294ca146a9a34668163` |
| `input/tape_baseline.json` (file) | `81fa52c21078b2c2...`; content digest `d915fab9...` |
| line contract | `90eac1a6c6682a397fc8e85abdf5b1d8ab3f38b75a80ae08709932286d319a31`; next session seed 1002 |

Checkpoints (`training/checkpoints/<name>/model.zip`, 8 in all, each with `curriculum_state.json` and `checkpoint.json` pinning the g3 identity, the members and
the spacing state): `ckpt_000000000` `ee6d0543bf3b8d8a...` (pointer 2,300; `policy.pth` `eb592c88...`), `ckpt_000102400` `a44f76470e51aa24...` (2,260),
`ckpt_000204800` `37a7c0a273835a26...`, then every 102,400 transitions to `ckpt_000614400`, and `final` as above (708,712 transitions); the full list is in
`session/training_summary.json` and `derived/report.json` (`checkpoint_digests`). Snapshots of the thirteen attempts: `training/attempts/a001..a013/snapshot_policy.pth`
(`60bfe14b...`, `fda14ef5...`, `0778ad90...`, `8de14420...`, `35e0121a...`, `73b013a1...`, `19b4360e...`, `d39ece0a...`, `296d2a6a...`, `567dd3e9...`, `88a1c36a...`,
`08d380bd...`, `e4c0b832...`). Records: `training/{episodes,rollouts,stale,windows,withdrawn,attempts,probes,moves}.jsonl`, `t0/drift.jsonl`, `audit/episodes.jsonl`,
`verification/replays.jsonl`, `session/*.json`, `artifacts/`; the launch logs, both full preflights (the refused one and the passing one), the snapshot and approval
records, the suite logs and the preparation tools under `launch/`.

## 10. What this does and does not say

* It says: under the replenishing controlled frontier rule, this single session of this recipe (a fresh v3 policy, reward v2, sticky p = 0.25, entropy 0.01, 80
  minutes, 4 + 6 slots) **did not** produce a policy that clears 10 of 20 sticky episodes from the last landing state: the frontier advanced four strips to 2,220 and
  the frozen final policy, from the cold start at 2,128 (92 ticks before its earliest trained start), cleared 8 of 20 sticky, 10 of 20 unperturbed and the
  deterministic episode. Measured against g2-s1 from identical initial weights, the one changed mechanism did what it was designed to do: the frontier never froze
  (13 attempts against 4, 29 triggers deferred and acted on later rather than discarded), four moves against one, 708,712 transitions against 190,696, and 8 / 20 at
  2,128 against 0 / 20. The outcome class is the same (NULL), because the depth measure needs the last landing and the pointer stopped 92 ticks short of it.
* It also shows, as facts for the review and not as decisions: the strips at 2,280 and 2,220 cost 26 and 27 minutes each, the strips at 2,260 and 2,240 about 9-13;
  two of the four moves (2,260, 2,240) were granted on frozen tests of 0.53 and 0.59 when the live strip rate was 0.33-0.43, i.e. inside the frozen test's upper
  sampling band, and training at 2,260 then ran at a strip rate of about 0.2; the 2,220 strip reached 0.65 over its last 79 outcomes when the wall cap ended the
  session with the next attempt 27 outcomes away. The pessimistic early critic values at the late strips and optimistic values at 2,220 are reported, not
  interpreted.
* It does not say that the recipe cannot reach 2,128 with a second session (the line rule permits s2, and END_BUDGET_2128 fires only if D_2 is still none), that
  the trigger bar or the spacing unit is right, or anything about other seeds or budgets; one seed and one session were the registered scope. Whether and how to
  continue is the user's decision. No RNG seed was inspected, logged or compared; every start state is a prefix of the agent's own verified routes; process restart
  was the reset; the submitted canonical words are the replay truth; no fixture, TAS or recording was read.
