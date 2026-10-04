# M9-g1 results (2026-10-04)

**Registered outcome: NULL** (`m9_g1_rule_v1`): *no reliable clear even from the last landing state.* R is undefined: the frozen final policy cleared **0 of 20** sticky episodes at every one of the six
landing states (2,128, 1,966, 1,694, 1,473, 1,369, 1,248); the open-loop tape cleared 13 of 20 at 2,128 and none elsewhere. One gate, one run, once; nothing was retried, extended or repaired, and
nothing follows this outcome automatically. Every number below is read from `runs/m9_g1/` (digests in section 8) and recomputed by `verify-run` (section 6).

Scope label (carried by every M9 record): *M9-g1: backward-algorithm robustification (PPO from prefix-replayed start states on the agent's own two verified rd4 clears, sticky actions p = 0.25,
observation btt_policy_obs_v3_entities, reward btt_reward_v2); one gate, one run, one set of keyed draws; reach measured at landing states under the registered rule; no claim of a tick-0 policy.*

## 1. What was run

The preparation is in `docs/rl_m9_g1_decisions_2026-10-04.md` (decisions, readings R1-R16, **section 5: the pre-launch fixes**) and `docs/rl_m9_g1_implementation.md`. In short: a FRESH PPO policy (the M7n v3
network and profile, entropy coefficient 0.01 from the start) trained for 60 minutes on episodes that start late on the agent's own two verified rd4 clears (iterations 11,206 and 11,286), replayed as exact prefixes
in fresh processes; start point moved back in 20-tick strips only when 3 of 10 counted strip outcomes were clears; sticky actions p = 0.25 per tick throughout training and evaluation; 4 playing + 6 preparing slots.

| item | value |
| --- | --- |
| launch | 2026-10-04 06:55:10 UTC, one detached session (pid 29048), `python -B -u -X utf8 rl/m9_session.py run`; its own preflight (including the unit suite, 63 / 63) ran first; the run root appeared 07:01:14 UTC |
| session clock | **4,981.6 s (83.0 min)** of the 7,800 s cap; close 11.5 s; the process exited by itself; no BattleShip process left |
| executable | `build-us/Release/BattleShip.exe` `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee` (the archive's pin), unchanged at the close |
| approval | `docs/rl_m9_g1_approval.json` `ee20df5b073b607436b3306eda54d4fd8e378cf86a1753a7ed1f70fbaf3f2ce9`; source snapshot `D:\BattleShip_source_snapshots\2026-10-04_m9_g1_r2` (`snapshot.json` `bf9ca457acd9fa07c68fe211222ac4a3a2dfdd505990acd9a603f5edc6437256`; 100 files) |

## 2. Pre-launch fixes (flagged: condition 6)

The independent review found no blocker but five hazards that would have ended a correct run INCOMPLETE or mis-recorded it. They were fixed before launch and recorded in the decisions record (section 5, F1-F5)
before the snapshot; none changes a registered measure, threshold, schedule, cap value or training setting (`contract_digest` `6958857e...` unchanged): **F1** a fixed-job phase stages a job again after a staging
lifecycle failure; **F2** P3's windows end at the earlier of 120 s and half the P3 tick cap; **F3** parked-start death bookkeeping; **F4** `-B` / no stale bytecode under the write guard; **F5** partial records, tracebacks,
broken-pipe death scan, P2 first-step lifecycle classification, approval metadata check. **In the real run F1, F2, F3 and the F5 paths did not trigger**: no lifecycle failure occurred anywhere, and P3's windows ended by
their 120 s wall (276,657 and 272,004 ticks against a 300,000 share), so F2's tick-cap branch was never taken. F4's preflight check was met.

## 3. Phases

| phase | wall (cap) | native ticks (cap) | result |
| --- | ---: | ---: | --- |
| P1 lineages | 25.1 s (240) | 13,923 (60,000) | PASS: both routes replayed 3 times each (two fresh, one through a promoted standby), exact; tables built |
| P2 staging equivalence | 34.6 s (120) | 31,998 (40,000) | PASS: 12 of 12 keyed starts: handover chain, handover v3 digest and the first reply's record digest equal the registered tables / a cold replay (this also settles the first-contact risk about the v3 digest across flag sets) |
| P3 split measurement | 246.6 s (300) | 548,661 (600,000) | PASS: 4 + 6: 158.35 transitions/s (109 episodes in 120.9 s); 2 + 8: 160.22 transitions/s (108 episodes in 120.0 s): 1.012 x, below the 1.10 rule, so **4 + 6**; no lifecycle failure |
| P4 tape control | 189.7 s (360) | 404,958 (600,000) | PASS: 140 of 140 tape episodes; tape clears: 13 at 2,128, none at the other five landings or tick 0 |
| training | 3,602.0 s (3,600) | 7,938,755 (15,000,000) | valid end: **wall cap**; 1,396,160 policy transitions (cap 3,072,000), 272 PPO updates (1,392,640 transitions), 6,542,595 prefix ticks |
| evaluation | 803.8 s (1,500) | 1,637,857 (3,000,000) | all 497 planned episodes completed; no deeper landing (the frontier did not reach 1,248) |
| verification | 68.5 s (900) | 122,421 (1,500,000) | 52 of 52 replays exact (20 training clears, 32 evaluation / P4 clears) |
| close | 11.5 s (300) | 0 | M8 trees equal their D: increments, no pin drift, no provenance or write-guard violation, metadata audit clean |

Total native ticks of the session: 10,698,573 (the registered 15,000,000 is the training cap; training used 7,938,755). Lifecycle failures: 0 in every phase. Stale staging replies: 5 (P3, 2 + 8, ignored by design).

## 4. Training

* Episodes 3,064: 638 clears (20.8 %), 2,283 falls (74.5 %), 143 horizon (4.7 %). By start region: strip 151 / 1,542, near 202 / 914, rehearsal 285 / 608 clears.
* **Backward depth reached: the frontier moved from 2,300 to 1,980 in 16 moves** (146 blocks, 16 passed; `training/pointer.jsonl`): the first four moves (to 2,220) came at 31 s, 63 s, 187 s and 420 s of training wall
  time and the move to 2,200 at 893 s; from there the pointer moved back by 20 every 30-150 s down to 2,020 (1,626 s), then needed until 2,029 s for 2,000 and **3,256 s for the last move, 2,000 -> 1,980** (block 133, after 2,813
  episodes); the 12 blocks that followed (the final 340 s) at 1,980 earned 0 clears. The wall-top landing (1,694), the PASS depth, was **not reached**: the frontier stopped 286 ticks short of it. Backward rate 320 route ticks in
  the hour (320.8 / h; an extrapolation to tick 0 is never a result).
* Clears in 500-episode blocks: 201, 142, 143, 56, 52, 43 (and 1 in the last 64). The mean recent episode return went from +6.51 (first rollout window) to -3.50 (last); entropy loss -4.27 -> -3.92; explained variance
  -0.05 -> 0.61. Median 442 policy transitions/s over the rollouts (P3's random-policy windows, starts only at 2,250-2,310, measured 158/s); the arena waited 483.7 s for a staged start in 3,590 s.
* Handover diagnostic (strip starts, pooled over pointers): mid-hold 113 clears / 1,293 starts (8.7 %), at a word change 16 / 167 (9.6 %). Descriptive only.
* 15 checkpoints (the untrained model, every 102,400 transitions, and the final), digests in section 8.

## 5. Evaluation of the frozen final policy (`final`, 1,396,160 transitions)

| landing | sticky policy clears (verified) | paired tape clears | unperturbed (diagnostic) | deterministic |
| ---: | ---: | ---: | ---: | --- |
| 2,128 | 0 / 20 | 13 / 20 | 0 / 20 | horizon, no clear |
| 1,966 | 0 / 20 | 0 / 20 | 0 / 20 | horizon |
| 1,694 | 0 / 20 | 0 / 20 | 1 / 20 | horizon |
| 1,473 | 0 / 20 | 0 / 20 | 0 / 20 | horizon |
| 1,369 | 0 / 20 | 0 / 20 | 0 / 20 | horizon |
| 1,248 | 0 / 20 | 0 / 20 | 0 / 20 | horizon |
| tick 0 | 0 / 20 sticky, 0 / 20 unperturbed | 0 / 20 | | horizon |

* **Rule outcome NULL**; `R_if_every_claimed_clear_were_verified` is also null (no claimed policy clear existed to change it), so the verified-vs-claimed check does not trigger INCOMPLETE.
* Diagnostics (never deciding): `R_unperturbed` null (the single unperturbed clear at 1,694 is 1 of 20, short of 10); `R_fine` = 2,300 (descriptive fine grid, 10 sticky episodes per point: 10 / 10 at 2,300, then 2 / 10 at 2,275,
  2 / 10 at 2,250, 1 / 10 at 2,225, 1 / 10 at 2,200, 0 at 2,175-2,125, 1 / 10 at 2,100, none from 2,075 to 1,950).
* Episode endings of the 120 sticky reach episodes: 30 falls and 90 horizon (every one of the 60 episodes at 1,473, 1,369 and 1,248 reached the 3,600-tick horizon without a clear). No episode ended in a clear.
* The 30-minute checkpoint (`ckpt_000512000`, 10 sticky episodes per landing, descriptive): 1 clear at 2,128 (replayed exactly), none elsewhere. The two models evaluated were `final` and this one.
  (The `verified` field of those descriptive rows reads 0 because their aggregation did not receive the verification map; the clear itself is among the 52 exact replays: `reach_mid-2128-06`.)
* The tape's 13 / 20 at 2,128 is the open-loop control under the same sticky draws as its paired policy episodes; it would have required at least 18 / 20 policy clears at 2,128 (13 + 5) for that landing to count.

## 6. Integrity, resources and caps

| check | result |
| --- | --- |
| verification | 52 / 52 exact; 0 skipped, 0 errors, 0 inexact; every counted or reported clear of P4 and the evaluation has a replay (`clears_without_a_replay` 0) |
| `verify-run` (after the run) | `ok: true`, no problems: metadata audit 1,361 files / 5,256 JSONL lines, 0 failures; 3,064 training, 497 evaluation, 140 P4 records re-derived; the pointer history rebuilt from the records equals the live log (1,980, 16 moves); the rule recomputed from the records equals the recorded NULL. (A first invocation wrote its own output file inside the audited tree while it was being written and reported that one file as unreadable; it was deleted and re-run with its output outside the tree. No gate record was affected.) |
| memory (caps) | main process private peak 1,534 MB by the session clock, 1,461 MB by the tree sampler (cap 3,072), tree private 6,628 MB (9,216), tree working set 2,372 MB (4,096), system available min 6,364 MB (>= 1,024), commit free min 11,450 MB (>= 2,048); no breach in 987 samples |
| processes | at most 10 BattleShip processes (cap 10); 28 processes in the tree at the peak |
| lifecycle failures / dead workers / provenance violations | 0 / 0 / 0 |
| wall caps | training reached its 3,600 s cap (the registered valid end); every other phase well inside its cap; the 130-minute session cap was not approached (83 min) |
| earlier trees | `runs/m8_rd/`, `runs/m8_rd_rd2/`, `runs/m8_rd_rd3/`, `runs/m8_rd_rd4/` equal their D: increments byte for byte at the open, at the close and again after the backup (166, 62, 77 and 93 files) |
| pins | executable, `.o2r` files, `gamecontrollerdb.txt` and the frozen configuration equal the archive's pins at the open and at the close |
| write guard | no write under any other `runs/` tree, `rl/` or `docs/` during the session |

## 7. Departures and notes

* **Snapshot path.** The first snapshot attempt (`D:\BattleShip_source_snapshots\2026-10-04_m9_g1`) failed the tool's own verification on one file: my redirect of the snapshot tool's output into the covered log
  directory (`logs/m9_g1_prep/final/snapshot_create.txt`) was written after it had been copied. It was not used and was not deleted. The snapshot of record is `..._m9_g1_r2` (new destination, outputs outside the
  covered directory), verified by the tool and by an independent PowerShell re-hash (checked 101, bad 0, executable equal). Both attempts' records are under `runs/m9_g1/launch/`.
* **Preflight.** One full preflight before the launch (it passed: no problem, unit suite 63 / 63); the launch re-ran it inside `run`, as designed, and it passed again. The dry-run preflight before the approval refused
  for exactly one reason, the missing approval.
* Between the snapshot and the close of the session nothing in `rl/`, in `docs/` (apart from the new approval record) or in the covered logs changed; the approval's identity check passed at both preflights.
* This record, the approval and the decisions / implementation records are new untracked files; no commit, push, branch or pull request was made and no existing file was modified.

## 8. Evidence and digests

Everything lives under `runs/m9_g1/` (Git-ignored; 2,740 files, 354,131,925 bytes) and in the D: increment `D:\BattleShip_runs_backup\2026-10-04_incr_m9_g1` (manifest sha256
`92ba5481acbb0ab9c0a17e19dffeb48965e68197feb6a44064524ccdf2419eac`): `tool backup` PASS and `verify` PASS twice (2,740 / 2,740 files, 0 hash mismatches, 0 problems), and an independent PowerShell `Get-FileHash`
re-hash PASS (2,740 source files, 2,740 backup files, 0 missing, 0 extra, 0 bad). Total `runs/` coverage afterwards: **412,215 source files, 0 uncovered** (ten increments). The launch logs, the preflight outputs, the
snapshot records and the pre-launch three-pass record are under `runs/m9_g1/launch/`; `verify-run` and `report` outputs under `runs/m9_g1/derived/`.

Checkpoints (`training/checkpoints/<name>/model.zip`, sha256):

| checkpoint | transitions | sha256 |
| --- | ---: | --- |
| `ckpt_000000000` (untrained) | 0 | `16dc29c9cac05322d3562dbc3bc865e157b6ede49969c8b0c209aa91e61d5c77` |
| `ckpt_000102400` | 102,400 | `56648638bc990778734883fe881b715d4d1d5561c2b375dbd37a627241b3d6cf` |
| `ckpt_000204800` | 204,800 | `c960e594a113dd2035eb68f3e51d768bf591081abd84224991e0ac2d17e0c709` |
| `ckpt_000307200` | 307,200 | `20c3cc04f387483d7abbead9202e91061c4e7f271c9ef9c3f32797ddb8b402b5` |
| `ckpt_000409600` | 409,600 | `bb6ce1ad101abad60078a34893f93ca855752169ea771b7ca93040a86ffacc45` |
| `ckpt_000512000` (the 30-minute model) | 512,000 | `cce25477187c8de7b89848680394b6acdad5b6de4bc33180992d7be304b56e2c` |
| `ckpt_000614400` | 614,400 | `049807de6e7f9cc719bfba3367a933f2baa0d1d8dd910f4b4087c8dcbfc86568` |
| `ckpt_000716800` | 716,800 | `c1bd03e885ddaf36a42e87653c4c2f83e151d2869110b727cca4d39de2298681` |
| `ckpt_000819200` | 819,200 | `f3831204a6f3ff04cac6241b51d7f9eca27a897ec0513539f9be6c4cc0756d63` |
| `ckpt_000921600` | 921,600 | `8df3e90fb65645beed066f92d190c6200feb81249700c51e2c1d61bd05792d09` |
| `ckpt_001024000` | 1,024,000 | `37a879c54ba79ad5062ed396f4bcf543547bb389fb844f0b9beae4b07864053d` |
| `ckpt_001126400` | 1,126,400 | `b497ec44b5ab5758b39f56d86cf1f7e1153d8198bcf19f918108431c0d510019` |
| `ckpt_001228800` | 1,228,800 | `21c7ba3635a84d9d6ec4da27ad0ed471d4feaec58892c0a7b8d852cb6ce8c22e` |
| `ckpt_001331200` | 1,331,200 | `65ec9109c9e415683f376c99d1ef841eb2566606e36fe40e634e2f377720cbfe` |
| `final` | 1,396,160 | `c56cb8dc386f1cd8a3a3a5928e87f073d346ebf2805721caad14a5db3a4fc9e2` |

Training and session records (sha256, first 16 hex): `training/episodes.jsonl` `bf693684c49c4100`, `training/blocks.jsonl` `fd3e1351065d414c`, `training/pointer.jsonl` `25a4c7a417a6ce22`, `training/rollouts.jsonl`
`d1eac8160ae6cd4a`, `training/stale.jsonl` `9927aefdd07ba064`, `training/checkpoints.json` `91aeee7c3e2c8947`, `session/rule.json` `35fda58c2c7de577`, `session/training_summary.json` `64caa678b6b3a009`, `eval/episodes.jsonl`
`9de126e34978abae`, `p4/episodes.jsonl` `b7f1cdbf3da6e935`, `verification/replays.jsonl` `caf55e1c34cd2905`, `session/memory_tree.jsonl` `6c79bef60f391463`, `launch/gate_stdout.txt` `1fcd2310f40ff0e7`. (Full digests of every file:
the backup manifest above.)

## 9. What this does and does not say

* It says: under the registered rule, this single run of this recipe (a fresh v3 policy, reward v2, sticky p = 0.25, entropy 0.01, 60 minutes, 4 + 6 slots) did not produce a policy that reliably clears from any
  of the six landing states, including the shortest tail (2,128 ticks, where the open-loop tape clears 13 of 20). The frontier advanced 320 ticks backward in the hour and slowed sharply after 2,000.
* It does not say that the recipe cannot work with more time, another seed, another observation or another reward; one seed and one hour were the registered scope. It does not say anything about tick 0 (no claim was
  tested), the final claim (50 / 100, 50 / 100, margin 25) was defined and not run, and no RNG seed was inspected, logged or compared anywhere.
* Nothing is authorised by this record: no relaunch, no second seed, no extension, no rd5. Whether and how to continue is the user's decision.
