# M9-g2-s1 results (2026-10-06)

**Registered outcome: NULL** (`m9_g2_s1_rule_v1`): *D_1 = none: not even 10 of 20 at 2,128.* The frozen final policy cleared **0 of 20** sticky episodes from the
last landing state (2,128; every episode fell); R_1 is undefined. **Line outcome: END_NULL_S1** (`m9_g2_line_rule_v1`): the line ends with its first session;
**s2 is not permitted**; the next step is a review. One session, one run, once; nothing was retried, extended or repaired, and nothing follows this outcome
automatically. Every number below is read from `runs/m9_g2/s1/` (digests in section 9) and recomputed by `verify-run` (section 7).

Scope label (carried by every record): *M9-g2-s1: backward-algorithm robustification under the controlled frontier rule `m9_g2_frontier_v1` (PPO from
prefix-replayed start states on the agent's own two verified rd4 clears, sticky actions p = 0.25, observation btt_policy_obs_v3_entities, reward
btt_reward_v2, entropy coefficient 0.01); the first session of a resumable line; one set of keyed draws; progress measured as the sustained frontier depth D and the
reliable reach R at landing states against a pinned tape baseline under the registered rules; no claim of a tick-0 policy.*

## 1. What was run

Design: `docs/rl_m9_g2_proposal_2026-10-04.md` as decided in `docs/rl_m9_g2_decisions_2026-10-05.md` (readings R1-R17, **section 5: the flagged pre-launch
fix**); preparation record `docs/rl_m9_g2_implementation.md`. In short: a FRESH PPO policy (the M7n v3 network and profile, entropy coefficient 0.01) trained for
80 minutes on episodes that start late on the agent's own two verified rd4 clears, replayed as exact prefixes in fresh processes; the frontier pointer moved back
only when a frozen snapshot passed a curtailed strip test (10 clears before 11 non-clears) and every landing behind it (none was ever behind it); at most 3 attempts
per pointer per session; sticky actions p = 0.25 everywhere; the fixed 4 + 6 slots.

| item | value |
| --- | --- |
| launch | 2026-10-06 04:52:35 UTC, one detached session (pid 20556), `python -B -u -X utf8 rl/m9_g2_session.py run --session 1`; its own preflight (the unit suite 29 / 29 and the rule self-test) ran first; the session clock started 05:01:36 UTC |
| session clock | **5,641.3 s (94.0 min)** of the 8,700 s cap; the process exited by itself; no BattleShip process left; `session_stderr.txt` empty |
| executable | `build-us/Release/BattleShip.exe` `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee` (the archive's pin), unchanged at the close; the `.o2r` files, `gamecontrollerdb.txt` and the frozen configuration equal rd1's pins |
| approval | `docs/rl_m9_g2_s1_approval.json` sha256 `c49c2045c1a3df98f97a29df6429d03d6e4677ffe2249d08ca1a6bbb9a15239b`, written from the fresh identity after the snapshot; source snapshot `D:\BattleShip_source_snapshots\2026-10-06_m9_g2_s1` (116 files, `snapshot.json` sha256 `6206a4fa1b7ca4a8267e9d333bbdd759c4a3859cb6006c7b61cca5f007162631`; tool verify PASS; independent PowerShell re-hash checked 117, bad 0, executable equal) |
| dates | the user's instruction is dated 2026-10-05 (the preparation records carry that date); the snapshot, the launch, the increment and this record carry the day of their creation, 2026-10-06 |

## 2. Pre-launch fix (flagged: Part B condition 6)

**H1 (decisions record, section 5):** replay launches in the verification phase stop 120 s before the phase's 600 s wall cap, so that the replays in flight finish
inside it (the hazard the M9-g1 checkpoint evaluation had found and fixed the same way). The cap, the tiers and the counting are unchanged; the line contract digest
is unchanged (`1aadc7a6...`); the g2 contract digest records the margin (`8dfd44c6...`). Found before the three consecutive passes and before the snapshot. In the real
run the verification took 149.8 s, so the margin did not bind.

## 3. Phases

| phase | wall (cap) | native ticks (cap) | result |
| --- | ---: | ---: | --- |
| open | 0.1 s (60) | 0 | identities, pins and the approval copy recorded |
| P1 lineages | 21.4 s (240) | 13,923 (60,000) | PASS: both routes replayed three times each (two fresh, one through a promoted standby), exact; tables registered |
| P2 staging equivalence | 37.7 s (120) | 31,998 (60,000) | PASS: 12 of 12 keyed starts equal the registered tables and a cold replay |
| T0 tape baseline | 451.0 s (900) | 1,127,526 (1,500,000) | PASS: 400 of 400 tape episodes; claimed clears **98 of 200 at 2,128** (53 falls, 49 horizon), **2 of 40 at 1,966**, 0 of 40 at 1,694, 1,473, 1,369 and 1,248 |
| training | 4,804.0 s (4,800) | 12,036,120 (20,000,000) | valid end: **wall cap**; 190,696 policy transitions (cap 3,072,000), 37 PPO updates, prefix 11,661,851 ticks, probes 183,573 ticks (the workers' own count: 12,049,936) |
| close audit | 88.8 s (1,200) | 173,019 (3,000,000) | all 62 planned episodes (the one audited landing, 2,128, and tick 0) |
| verification | 149.8 s (600) | 281,434 (1,500,000) | **121 of 121 replays exact** (tier 0: 100 tape clears; tier 1: the first 20 training clears; tier 2: the one keyed probe clear of the passed strip test); 0 skipped, 0 errors |
| close | 88.7 s (300) | 0 | the six protected trees equal their D: increments, no pin drift, no provenance or write-guard violation, metadata audit 4,879 files / 7,088 JSONL lines clean, no leftover process |

Lifecycle failures: 0 in every phase. Stale staging replies: 0.

## 4. Training and the frontier

* Episodes 5,038: **4,347 clears (86.3 %)**, 691 falls, 0 horizon. Starts: 2,511 from the strip (1,910 clears), 2,527 from the near window (2,437 clears), none
  from rehearsal (empty at these pointers). Mean policy phase 37.8 ticks per episode against a 2,280-2,324-tick prefix: median **49.4 policy transitions/s**
  (17.8 in the first rollout, 22-30 at the end), far below g1's 442/s, because the pointer never left the last 46 ticks of the route.
* **The pointer moved once, 2,300 -> 2,280, and stayed at 2,280 for the remaining 79 minutes.** Attempts (every one on a frozen snapshot, keyed starts over the
  strip, keyed action draws; no landing was behind the frontier, so no re-check ran):

| # | pointer | a | trigger (clears of counted outcomes) | at transitions | strip test (clears / episodes; outcomes in order) | result | wall | withdrawn starts |
| ---: | ---: | ---: | --- | ---: | --- | --- | ---: | ---: |
| 1 | 2,300 | 1 | 8 of 8 | 5,120 | **10 / 12** `ccccccxcxccc` (early stop; 5 abandoned) | **MOVED -> 2,280** | 35.7 s | 6 |
| 2 | 2,280 | 1 | 8 of 18 | 10,240 | 4 / 15 `xxccxcxxcxxxxxx` | FAILED_STRIP | 24.2 s | 6 |
| 3 | 2,280 | 2 | 8 of 20 | 20,480 | 6 / 17 `xxccccxxxcxxxxxcx` | FAILED_STRIP | 23.6 s | 6 |
| 4 | 2,280 | 3 | 8 of 17 | 30,720 | 4 / 15 `xccxxcxcxxxxxxx` | FAILED_STRIP -> **HELD** | 24.4 s | 6 |

* The three failures at 2,280 came within the first 7 minutes of training (transitions 10,240-30,720). The per-session bound (3) then held the pointer: **213
  later windows reached 8 clears and were logged as `held_trigger`** (6 windows were void). Counted strip outcomes at 2,280: 2,361; their clear rate was 39 % in the
  first 200 and **92.5 % in the last 200** (75.3 % overall); the frozen snapshots tested at 27-35 %, below the 50 % bar.
* Probe wall time 108 s in total (2.2 % of the training wall); 24 staged training starts withdrawn and recorded (`training/withdrawn.jsonl`); the four
  playing slots stayed parked in every attempt (`parked_slots` 4, `probe_slots` 6, disjoint); at most 10 BattleShip processes throughout.
* Handover diagnostic at 2,280 (descriptive): mid-hold starts 1,505 clears / 2,036, at a word change 273 / 325.
* The frontier history rebuilt by `verify-run` from the records alone equals the log (1 move, 4 attempts, pointer 2,280).

## 5. The frozen final policy (close audit) and the tape

Audited landings: 2,128 only (the pointer's strip never reached 2,120). Tick 0 descriptive. Every audit action is a keyed inverse-CDF draw from the final weights
(`policy.pth` member `4b16529d...`).

| start | sticky (verified clears of 20) | endings | unperturbed (of 20) | deterministic | tape p_hat (keys) | B |
| ---: | ---: | --- | ---: | --- | ---: | ---: |
| **2,128** | **0 / 20** | 20 falls; no episode broke target 1 (mean 514 policy ticks) | 0 / 20 (20 falls) | fall | 0.490 (200) | **15** |
| 1,966 | not audited | | | | 0.050 (40) | 10 |
| 1,694 ... 1,248 | not audited | | | | 0.000 (40 each) | 10 |
| tick 0 | 0 / 20 | 5 falls, 15 horizon; 2-6 targets broken | | horizon, 1 target | | |

* **Rule outcome NULL:** D_1 = none (the chain fails at 2,128); R_1 = none. `D_if_every_claimed_clear_were_verified` and the R counterpart are also none (no
  claimed audit clear existed). `FRONTIER_BACKED` is vacuously true (no landing behind the frontier). R_unperturbed none.
* **The tape baseline (pinned, `session/tape_baseline.json` sha256 `d915fab9205547742e77360ba83f247b7ab304af7a37540ceb9910a2b614a23b`):** every one of the 100
  counted tape clears was replayed exactly (0 unverified, 0 inexact). B(2,128) = ceil(20 x 0.49) + 5 = **15**; B = 10 at the five other landings.
* Value calibration (reported only): at the 2,128 handover the final critic's V was -2.51 against a realised mean return of -5.51 (gap +3.0); entropy 3.51 nats
  (82 % of maximum), top-word probability 9.9 %. At the probe handovers: attempt 1 (2,300) V +5.66 against +8.29; attempts 2-4 (2,280) V -0.42 / -2.38 / -1.41
  against -0.88 / +0.53 / -0.88; entropy 99.8 -> 97.5 % of maximum, top word 1.7 -> 3.6 %.
* Entropy per rollout: 99.8 % of maximum after the first update, 86.6 % at the end (the minimum); explained variance 0.84 at the end; median approx_kl 0.0075.
  Post-target-8 success share per 100 training episodes: 53 % in the first 100, 74 % in the last full 100 (nearly every start here is post-target-8).

## 6. Resources against the caps

| resource | peak / used | cap |
| --- | ---: | ---: |
| session clock | 5,641.3 s | 8,700 s |
| training wall | 4,804.0 s | 4,800 s (the registered valid end) |
| native ticks (session) | 13,664,020 (P1 13,923; P2 31,998; T0 1,127,526; training 12,036,120; audit 173,019; verification 281,434) | per phase, section 3 |
| main process private memory | 1,249.9 MB | 3,072 MB |
| process tree private memory | 6,428.9 MB | 9,216 MB |
| process tree working set | 2,229.1 MB | 4,096 MB |
| lowest system available memory | 5,774.7 MB | at least 1,024 MB |
| lowest system commit free | 10,886.0 MB | at least 2,048 MB |
| BattleShip processes (peak) | 10 (1,116 samples at 5 s) | 10 |
| memory breach | none | |

## 7. Integrity

| check | result |
| --- | --- |
| verification | 121 / 121 exact; every clear counted in a registered measure replayed (the 100 tape clears; no audit clear existed); the first 20 training clears and the one keyed probe clear exact |
| `verify-run` (after the run, output outside the tree) | `ok: true`, no problems: metadata audit 4,885 files / 7,088 JSONL lines, 0 failures; 5,038 training, 59 probe, 400 T0 and 62 audit records re-derived (every sticky mask from its keys, every start from its keys, every words digest from the registered prefix and the submitted words, every tape word the trunk's); the frontier history rebuilt from the records equals the log; the three checkpoints' model.zip, member and curriculum-state digests equal their pins; the pinned tape table re-derives from the T0 records and the replays with the same digest; the rule recomputed from the records equals the recorded NULL |
| pins | executable, runtime files and frozen configuration equal the archive's pins at the open and at the close |
| protected trees | `runs/m8_rd` (166 files), `m8_rd_rd2` (62), `m8_rd_rd3` (77), `m8_rd_rd4` (93), `m9_g1` (2,740), `m9_g1_eval` (1,393) equal their D: increments at the preflight, at the close and again after the backup (the tool and an independent PowerShell re-hash, 0 missing, 0 extra, 0 bad each) |
| write guard, provenance | no write under any other `runs/` tree, `rl/` or `docs/` during the session; no provenance violation |
| untrained policy | the fresh policy's `policy.pth` member sha256 `eb592c887fc66aaba038e0b35986463bf03153bd7fe78a3f5d80357fa517ceb0` equals g1's `ckpt_000000000` member (reported, never deciding) |

## 8. Departures and notes

* **Backup verify mis-invoked once.** After the tool backup had verified PASS, I ran the separate `runs_backup.py verify` without `--source`; the tool compared the
  increment against the whole `runs/` tree and overwrote the increment's `verification.json` with FAIL (9,779 "mismatches"). The copy was never touched (the
  independent PowerShell re-hash passed before and after). The separate verify was re-run with `--source runs/m9_g2/s1` and wrote PASS (`verified_utc`
  06:44:38 UTC); that is the record on disk. The two verify logs were written after the backup, so they are not inside the increment; they live in
  `logs/m9_g2_run/backup_m9_g2_s1_verify.txt` and `logs/m9_g2_run/backup_m9_g2_s1_verify_rerun.txt`, beside the backup, coverage and tree-check logs.
* The dry-run preflight was run twice (once during preparation, once on the final code after the flagged fix); both refused for the single reason, the missing
  approval. The full preflight before the launch passed (`ok: true`, unit suite 29 / 29); the session re-ran it inside `run` and it passed again.
* g1's unit suite (`rl/m9_tests.py`) fails two source-guard tests on the tracked, unchanged `rl/m9_eval_tests.py` (pre-existing, from the checkpoint-evaluation
  session); the g2 files pass g1's fragment scan.
* This record, the approval and the decisions / implementation records are new untracked files; no commit, push, branch or pull request was made and no
  existing file was modified. The external guide was not edited.

## 9. Evidence and digests

Everything lives under `runs/m9_g2/s1/` (Git-ignored; 9,779 files, 988,807,605 bytes, the copied launch and preparation logs under `launch/` and the `verify-run`
and `report` outputs under `derived/` included) and in the D: increment `D:\BattleShip_runs_backup\2026-10-06_incr_m9_g2_s1` (manifest sha256
`4ad2c3dc240ef1bbbce9dfe1c924efa9936d0a1ce5db51df099ce4736fd8b45f`): tool backup PASS (copy 9,779 / 9,779, 0 hash mismatches), separate tool verify PASS, independent
PowerShell `Get-FileHash` re-hash 9,779 source / 9,779 backup files, 0 missing, 0 extra, 0 bad. Total `runs/` coverage afterwards: **423,387 source files, 0
uncovered** (the base and 12 increments).

**The saved state for a later session** (`session/final_state.json`; s2 is not permitted by the line rule, the state is evidence):

| file | sha256 |
| --- | --- |
| `training/checkpoints/final/model.zip` | `b79a71d3018747b280480e11d3019bfc16abdd182ffae7d781179eceff5e8963` |
| its `policy.pth` member | `4b16529df10c61911c8a390a6a1c6cb5ada19c2a221cdf44e4d8f41ed8f631ae` |
| its `policy.optimizer.pth` member (Adam: 370 updates, step 3,700 on every one of the 12 parameters) | `338dada3881fbbf4b352ef6d3d5ead97cfd67df0623a9c8be8fa529a11054c83` |
| `training/checkpoints/final/curriculum_state.json` (pointer 2,280; line failed attempts {2,280: 3}; 1 move; next episode 5,062; 4 attempts) | `d011ecb8203e7a2a...` |
| `session/tape_baseline.json` (file) | `81fa52c21078b2c2...`; content digest `d915fab9...` |

Checkpoints (`training/checkpoints/<name>/model.zip`): `ckpt_000000000` `4bf26eec620dd014...` (pointer 2,300), `ckpt_000102400` `40f0b0ae7416de5f...` (pointer 2,280),
`final` as above (190,696 transitions). Snapshots of the four attempts: `training/attempts/a001..a004/snapshot_policy.pth` (`8a30b4a0...`, `541b45d2...`,
`38c0a41e...`, `5e0e95e7...`). The launch logs, the preflights, the snapshot and approval records, the three-pass record (`launch/prep_final/passes.json`,
fingerprint `e075ca5db30f1881`, 29 / 29 and e2e PASS with digest `e87c71a79980286d` three times) are under `launch/`.

## 10. What this does and does not say

* It says: under the registered controlled frontier rule, this single session of this recipe (a fresh v3 policy, reward v2, sticky p = 0.25, entropy 0.01, 80
  minutes, 4 + 6 slots) did not produce a policy that clears from the last landing state: the frontier passed one strip and was then held at 2,280 for the whole
  session, so the policy never trained from any state before tick 2,280, and from the cold start at 2,128 it fell 20 times in 20. The rule did what it was designed to
  do: the frozen tests measured the strip at 27-35 % when the live outcomes had triggered at 40-47 %, and no move was granted on a test below the bar.
* It also shows, as a fact for the review and not as a decision: the per-session bound of three attempts was exhausted after seven minutes, while the live strip
  rate rose to 92 % by the end of the session with 213 triggers that could not be acted on. The bound as decided holds a pointer for the rest of the session once
  three frozen tests fail, whatever the policy does afterwards.
* It does not say that the recipe cannot work with more sessions, another bound, another trigger, another seed or another budget; one seed and one session were the
  registered scope. The line rule ends the line (END_NULL_S1); whether and how to continue is the user's decision. No RNG seed was inspected, logged or compared;
  every start state is a prefix of the agent's own verified routes; process restart was the reset; the submitted canonical words are the replay truth; no fixture,
  TAS or recording was read.
