# M9-g1 diagnosis (2026-10-04)

**Status: diagnosis and one checkpoint evaluation; no training.** No optimizer was built anywhere, nothing was committed or pushed, no existing file was edited, and
`runs/m9_g1/` and the four M8 trees are byte-identical to their D: increments before, during and after. The registered M9-g1 outcome (**NULL**,
`docs/rl_m9_g1_results_2026-10-04.md`) is unchanged; nothing here re-decides it. Plan of the evaluation, fixed before its first native tick:
`docs/rl_m9_g1_checkpoint_eval_plan_2026-10-04.md`.

| item | state |
| --- | --- |
| checkout | `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, `main`, HEAD = origin/main = `45f0486` (clean at the start) |
| read | the external guide (`Smash_pc_port/guide.md`), `CLAUDE.md`, M7h and M7m results, M8-rd4 results, `rl_m9_policy_proposal_2026-10-03.md`, every `rl_m9_g1_*` document |
| new files | `docs/rl_m9_g1_checkpoint_eval_plan_2026-10-04.md`, `docs/rl_m9_g1_eval_approval.json`, this record; `rl/m9_eval_{policy,ckpt,session,snapshot,tests}.py`; run tree `runs/m9_g1_eval/` (Git-ignored); prep logs `logs/m9_g1_eval_prep/`, `logs/m9_g1_eval_run/` (Git-ignored) |

## 1. Verdict

| hypothesis | verdict | the evidence in one line |
| --- | --- | --- |
| **H1 forgetting** | **supported** | the checkpoint at 409,600 transitions cleared the gate's last landing (2,128) in **9 of 20** sticky episodes; the final policy cleared **0 of 20** on the same keys (paired 9 to 0, p = 0.002); at 2,250 it was 5 of 20 (and still 5 of 20 at 1,228,800) against 0 of 20 at the end (p = 0.031). The final policy is back at the level of the untrained, uniform policy there (1 and 0 of 20), not below it |
| **H2 stochastic dependence** | **contradicted** as the explanation of the NULL | training, the frontier rule and the decisive reach evaluation all used the same mode (sampled actions, sticky p = 0.25). Its premise holds as a description (argmax episodes never cleared where the sticky cell had 5 or more clears) but explains nothing about the gate |
| **H3 lucky frontier moves** | **supported** | 9 of the 16 moves were never backed by a 30 % strip rate before or after the move; the last three (2,040 -> 1,980, 49 % of training) had pooled rates of 3.5-11.7 %. The checkpoints at the stall and after the last move cleared that strip's start 2,010 in **2 and 1 of 20** |

The three are linked. Real competence on the last section existed by about 409,600 transitions (45 % at 2,128 under sticky actions; still short of the gate's
bar, which there required 18 of 20 against the tape's 13). The pointer then moved through 2,040 -> 1,980 on repeated tries at about 4 % (H3). From then on 85 %
of the starts lay on the first left-floor segment, where 85-90 % of episodes fell, and the policy's last-section skill, the drop to target 1, decayed to the random
level while its frontier skill, the climb to target 8, grew (H1). The gate measured the final checkpoint.

## 2. Part A: read-only diagnosis (zero native ticks)

**Sources (read only):** `runs/m9_g1/training/{episodes,blocks,pointer,rollouts,stale}.jsonl`, `training/checkpoints.json` and the 15 pinned `model.zip`,
`eval/episodes.jsonl`, `p4/episodes.jsonl`, `session/*.json`; the trunk's recorded replies in `runs/m8_rd_rd4/routes/T_clear/trace.json.gz`. The scratch
analyses ran in the session scratchpad; they and their outputs are preserved in `runs/m9_g1_eval/derived/part_a/`. They imported nothing from the repository
except, for 2.6, the unchanged v3 builder (`rl/m9_obs`, `rl/m7n_obs`) and SB3's network building blocks; no PPO object, policy class or optimizer was built (an
optimizer guard raised on any construction). The five protected trees were compared with their D: increments before the analysis (equal).

### 2.1 Action modes (H2)

| where | action | perturbation | evidence |
| --- | --- | --- | --- |
| training (3,064 episodes) | sampled (SB3 PPO rollout collection) | sticky p = 0.25, keys `train:<episode>` | every record `deterministic: false`; measured sticky rate 0.251 of 1,396,160 policy ticks |
| frontier rule | the outcomes of those same training episodes (1,460 counted strip outcomes, 82 stale) | same | `training/blocks.jsonl`; the policy changed every 5,120 transitions while a block filled |
| **reach evaluation (the decision)** | **sampled** (`model.predict(deterministic=False)`) | **sticky p = 0.25**, keys `reach:<tau>:<k>` | 120 records, all `deterministic: false` |
| unperturbed diagnostic | sampled | none | 120 records |
| deterministic | argmax | none | 7 records (one per landing and tick 0), all horizon |
| fine grid; 30-minute checkpoint | sampled | sticky | 150 + 60 records |
| tape control | open-loop T_clear words | sticky, the reach keys | 140 records |

### 2.2 The 16 frontier moves (H3)

Rule: 3 clears in a block of 10 counted strip outcomes moves the pointer back 20 ticks; a failed block is simply retried. "Pooled" = every counted outcome at
that pointer. "Chance" = probability that at least one of that many blocks reaches 3 of 10 at the pooled rate of the non-passing blocks. "After" = every training
start on that strip completed after the move, any region.

| # | from -> to | wall (s) | blocks | clears per block | pooled strip rate (95 % CI) | chance | after the move | last 500 episodes |
| ---: | --- | ---: | ---: | --- | --- | ---: | ---: | ---: |
| 1 | 2,300 -> 2,280 | 31 | 1 | 10 | 10/10 = 100 % (69-100) | first block | 142/157 | 3/3 |
| 2 | 2,280 -> 2,260 | 63 | 1 | 3 | 3/10 = 30 % (7-65) | first block | 61/120 | 3/6 |
| 3 | 2,260 -> 2,240 | 187 | 6 | 0 2 1 0 1 3 | 7/60 = 11.7 % (4.8-22.6) | 0.22 | 37/143 | 1/10 |
| 4 | 2,240 -> 2,220 | 420 | 10 | 1 1 1 0 1 1 0 1 0 4 | 10/100 = 10.0 % (4.9-17.6) | 0.22 | 23/104 | 2/6 |
| 5 | 2,220 -> 2,200 | 893 | 21 | nine zeros, eleven 1s, then 3 | 14/210 = 6.7 % (3.7-10.9) | 0.27 | 13/62 | 2/12 |
| 6 | 2,200 -> 2,180 | 927 | 1 | 3 | 3/10 = 30 % (7-65) | first block | 18/54 | 3/8 |
| 7 | 2,180 -> 2,160 | 1,009 | 3 | 2 2 3 | 7/30 = 23.3 % (9.9-42.3) | 0.69 | 14/62 | 2/11 |
| 8 | 2,160 -> 2,140 | 1,064 | 2 | 1 3 | 4/20 = 20.0 % (5.7-43.7) | 0.14 | 15/67 | 0/9 |
| 9 | 2,140 -> 2,120 | 1,175 | 4 | 2 1 1 3 | 7/40 = 17.5 % (7.3-32.8) | 0.45 | 11/48 | 1/11 |
| 10 | 2,120 -> 2,100 | 1,215 | 1 | 3 | 3/10 = 30 % (7-65) | first block | 17/55 | 0/7 |
| 11 | 2,100 -> 2,080 | 1,244 | 1 | 6 | 6/10 = 60 % (26-88) | first block | 19/62 | 3/9 |
| 12 | 2,080 -> 2,060 | 1,364 | 5 | 2 1 1 2 3 | 9/50 = 18.0 % (8.6-31.4) | 0.63 | 25/73 | 1/4 |
| 13 | 2,060 -> 2,040 | 1,481 | 5 | 2 1 1 2 5 | 11/50 = 22.0 % (11.5-36.0) | 0.63 | 29/93 | 2/4 |
| 14 | 2,040 -> 2,020 | 1,626 | 6 | 1 1 1 0 1 3 | 7/60 = 11.7 % (4.8-22.6) | 0.22 | 20/205 | 6/41 |
| 15 | 2,020 -> 2,000 | 2,029 | 17 | fourteen zeros, 2, 1, then 3 | 6/170 = 3.5 % (1.3-7.5) | 0.01 | 6/200 | 2/84 |
| 16 | 2,000 -> 1,980 | 3,256 | 50 | 33 zeros, sixteen 1s/2s, then 3 | 21/500 = 4.2 % (2.6-6.3) | 0.22 | 0/40 | 7/155 |

After the last move: 12 blocks at 1,980 with 1 clear in 120.

A move is **backed** when its strip showed at least 30 % either in the pooled outcomes up to the move or in the starts after it. **Backed: 7 of 16** (moves 1, 2,
6, 10, 11, 12, 13). **Not backed: 9 of 16.** Moves 3, 4, 5, 14, 15 and 16 have a pooled upper 95 % bound below 30 % and an after-rate below 30 %; moves 7, 8 and 9
have pooled rates of 17.5-23 % and after-rates of 22-23 %. **The last three moves were all not backed** (pooled 11.7 %, 3.5 %, 4.2 %; after 10 %, 3 %, 0 %) and
took 1,775 s, 49 % of training. The block rule has no protection against repeated testing: at a true rate of 5 % a block passes with probability 1.2 % (44 %
within 50 blocks); at 10 %, 7.0 % per block. The pointer measured persistence, not competence.

### 2.3 Per-start-point outcomes over training (H1)

Episodes in completion order, windows of 500 (window 6 = the last 64):

| window | training wall (s) | transitions | pointer | clears | falls | horizon | median start |
| ---: | --- | --- | --- | ---: | ---: | ---: | ---: |
| 0 | 14-554 | 0.9 k-102 k | 2,300 -> 2,220 | 201 | 298 | 1 | 2,273 |
| 1 | 555-1,118 | 102 k-265 k | 2,220 -> 2,140 | 142 | 357 | 1 | 2,232 |
| 2 | 1,119-1,685 | 266 k-457 k | 2,140 -> 2,020 | 143 | 351 | 6 | 2,095 |
| 3 | 1,686-2,267 | 457 k-696 k | 2,020 -> 2,000 | 56 | 422 | 22 | 2,037 |
| 4 | 2,269-2,875 | 697 k-985 k | 2,000 | 52 | 420 | 28 | 2,019 |
| 5 | 2,876-3,505 | 986 k-1,329 k | 2,000 -> 1,980 | 43 | 402 | 55 | 2,017 |
| 6 | 3,505-3,599 | 1,330 k-1,393 k | 1,980 | 1 | 33 | 30 | 2,012 |

Clears / starts by start group (h = horizon endings where they appear):

| start group (trunk state) | w0 | w1 | w2 | w3 | w4 | w5 | w6 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1,980-2,065 (first left-floor segment, the climb to target 8; 8 and 1 standing) | - | - | 13/111 | 21/371, h17 | 18/393, h17 | 17/402, h45 | 0/51, h25 |
| 2,066-2,127 (8 broken, airborne) | - | - | 68/218 | 12/61 | 12/29 | 7/21 | 0/1 |
| **2,128-2,188 (second left-floor segment: the gate's last landing)** | - | 18/75 | **34/113 (30 %)** | **1/20** | **2/21** | **3/25** | 0/4 |
| 2,189-2,249 (the drop toward target 1) | 5/113 | 42/267 | 7/28 | 8/25 | 4/20 | 8/29 | 1/5 |
| 2,250-2,299 | 54/234 | 39/114 | 13/22 | 6/15 | 9/28 | 5/19 | 0/3 |
| 2,300-2,325 (the last 26 ticks) | 142/153 | 43/44 | 8/8 | 8/8 | 7/9 | 3/4 | - |

* The second left-floor segment fell from **34/113 (30 %) in window 2 to 6/66 (9 %) in windows 3-5**, exactly when the pointer entered the unbacked moves 14-16.
  The airborne drop and 2,250-2,299 held in training (16-40 %); the checkpoint evaluation shows that 2,250 nevertheless decayed late (section 4).
* The fall of the clears per 500 episodes (201 -> 43) is mostly the start distribution moving back (median start 2,273 -> 2,017), not a uniform decay.
* **Horizon endings grew** from 1 per 500 to 55 per 500 and 30 of the last 64, nearly all from starts at 1,980-2,010: the policy increasingly stayed on the left
  floor until the 3,600-tick horizon (-1.6) rather than risk the fall (-5). The median policy ticks to a fall rose from 251 to 497.

### 2.4 How often later landings were reached

Training starts are all at or after 1,980, so the only later landing a training episode could reach is the 2,128 phase (target 8 broken, the drop to target 1
left). From starts below 2,066:

| window | starts < 2,066 | broke 8 (reached the 2,128 phase) | cleared after reaching it | endings after reaching it | final-section practice per 500 episodes (starts >= 2,066 + arrivals) |
| ---: | ---: | ---: | ---: | --- | ---: |
| 2 | 111 | 48 (43 %) | 13 (27 %) | 35 falls | 437 |
| 3 | 371 | 86 (23 %) | 21 (24 %) | 57 falls, 8 horizon | 215 |
| 4 | 393 | 95 (24 %) | 18 (19 %) | 68 falls, 9 horizon | 202 |
| 5 | 402 | 118 (29 %) | 17 (14 %) | 83 falls, 18 horizon | 216 |
| 6 | 51 | 22 (43 %) | **0** | 5 falls, **17 horizon** | 35 (of 64) |

The 2,128 phase kept being reached while success after reaching it fell from 27 % to 14 % and then to 0 of 22. Final-section practice roughly halved after window
2 but did not become rare. The g1 evaluation shows the same thing from fixed landings (final policy, 20 sticky episodes each): from 1,694 the policy reached the left
floor 17 times and broke target 8 in 15, but target 1 in 1; from 1,966 target 8 in 10 and target 1 in 0; from 2,128 target 1 in 0, against the tape's 13. **The
policy reaches the later landings; the final drop to target 1 is what it does not do.**

### 2.5 Policy entropy

Maximum for MultiDiscrete [9, 8]: ln 9 + ln 8 = 4.277 nats.
* Per rollout (`training/rollouts.jsonl`): 4.268 (99.8 %) after the first update, minimum 3.861 (90.3 %) at rollout 95, final 3.919 (91.6 %). **The policy never
  left the near-uniform regime.**
* Per state at the trunk's own states (2.6's method), final checkpoint: 88 % of maximum at 2,128, 97 % at 1,966, 85 % at 1,694, 73 % at tick 0; the untrained
  checkpoint is 100.0 % everywhere. The trunk's own words keep a near-uniform probability at every checkpoint (mean log-probability over 2,128-2,325: -4.37 to -4.80
  against -4.28 for uniform; a diagnostic only, the trunk is never a target).

### 2.6 Value estimates at the landings

The v3 observation of every trunk tick was rebuilt from the recorded replies (2,327 observations; **0 digest mismatches** against the registered
`runs/m9_g1/lineages/T_clear/v3.bin`). Each checkpoint was read from its pinned `policy.pth` (all 15 digests equal). The rebuilt final network reproduces the first
word of all **7 recorded deterministic episodes**, and the evaluation's online handover values equal these offline ones (409,600 at 2,128: 1.7327 online, 1.73
offline; final: -2.2768 and -2.28). Under reward v2 a clear is worth about +10.8 from 2,128 and +10.97 from 2,300; a fall -5 plus the step cost; staying to the
horizon from 2,128, -1.47.

| checkpoint | V(2,300) | V(2,250) | V(2,128) | V(2,000) | V(1,966) | V(1,694) | V(1,473) | V(1,248) | V(0) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ckpt_000000000 | -0.46 | -0.82 | -0.68 | -0.65 | -0.76 | -1.02 | -0.97 | -1.17 | -0.90 |
| ckpt_000204800 | 9.83 | -0.46 | -1.28 | 0.08 | -0.34 | -0.59 | -5.42 | -5.64 | -4.91 |
| ckpt_000409600 | 8.46 | 2.01 | **1.73** | -1.52 | -1.77 | -0.54 | 1.11 | -1.71 | -3.80 |
| ckpt_000512000 | -2.74 | -3.06 | -2.77 | -2.31 | -2.79 | 1.49 | 1.87 | -2.59 | -5.44 |
| ckpt_000614400 | -3.72 | -2.75 | -2.69 | -2.94 | -2.65 | -0.32 | -1.45 | -4.69 | -4.06 |
| ckpt_000819200 | -3.79 | -3.03 | -1.63 | -3.14 | -2.84 | -5.19 | -4.98 | -5.53 | -3.96 |
| ckpt_001024000 | -1.47 | 4.70 | 6.60 | -3.38 | -3.38 | 1.08 | -5.44 | -2.42 | -4.41 |
| ckpt_001228800 | -4.26 | -0.89 | -0.68 | -2.46 | -2.75 | -2.02 | -7.69 | -8.84 | -4.86 |
| ckpt_001331200 | 9.52 | -2.66 | -1.99 | -2.13 | -2.01 | -2.05 | -8.32 | -8.47 | -5.37 |
| final | **-3.96** | -2.44 | **-2.28** | -2.17 | -1.95 | -2.11 | -9.46 | -9.07 | -4.24 |

* From 512,000 transitions on, the critic no longer tells the end of the route from the frontier. V(2,300) is -3.96 at the final checkpoint, although the true return
  is about +11 and the policy clears 10 of 10 there; V(2,128) to V(1,966) sit at -2 to -3, between the fall and horizon values. The final explained variance (0.61) was
  earned on frontier-dominated rollouts.
* Late-state estimates swing by up to 14 between neighbouring checkpoints (V(2,300): 9.83, 5.46, 8.46, -2.74, ..., 9.52, -3.96): those states were rare in the rollouts
  (window 5 had 4 of 500 starts at 2,300 or later).
* The highest late values belong to `ckpt_000409600`, the checkpoint that also cleared best (section 4).

### 2.7 Handover diagnostic (the registered v4 trigger)

Failure rate of strip starts drawn mid-hold divided by that of starts at a word change, per pointer: 0.56-1.45 everywhere, **1.01 at 2,000 and 0.99 at 1,980** (the
stalled strips). The registered fallback condition, a ratio of 2 or more at the stalled strip, is **not met**: nothing here calls for observation v4.

### 2.8 What Part A decided

H2 contradicted (2.1) and H3 supported (2.2) from the records. H1 was only partly supported. The logs mixed a continuously changing policy, shifting start mixtures and
small late samples, and two late regions had not decayed in training. So Part B planned a checkpoint evaluation (`docs/rl_m9_g1_checkpoint_eval_plan_2026-10-04.md`):
five checkpoints from the frontier history, three start points (2,128, 2,250, 2,010), stochastic sticky / stochastic unperturbed (20 each) and deterministic (1)
cells, the tape on identical keys, keyed action draws shared across checkpoints (paired episodes), and pre-registered readings.

## 3. Part C: preconditions, authorised steps and integrity

| step | record |
| --- | --- |
| new code | `rl/m9_eval_policy.py` (pinned weight-only network: SB3 `MlpExtractor` + `Linear` heads + `MultiCategoricalDistribution`; keyed inverse-CDF sampling; `torch.optim.Optimizer.__init__` replaced by a function that raises), `rl/m9_eval_ckpt.py`, `rl/m9_eval_session.py`, `rl/m9_eval_snapshot.py`, `rl/m9_eval_tests.py`; every other module imported unchanged |
| independent review | read-only reviewer: **no blocker**; three hazards fixed before freezing (an unverified clear could have been read as decided in H2 / stickiness / interference; COMPLETE was possible with unverified clears; a 60 s verification launch margin raised to 120 s) and five minors (interference tied to the decayed point, tape cells in the completeness lists, records kept on an error stop, `-B` enforced by the snapshot tool, H3 labels) |
| condition 1 | unit suite **29 / 29 three consecutive times**, fingerprint of `rl/m9_eval_*.py` `125c848591c41d14` before and after every pass (`runs/m9_g1_eval/derived/prep/three_passes.json`) |
| condition 2 | all five checkpoint digests equal their pins (preflight, session open, after the run) |
| condition 3 | preflight with the unit suite refused for exactly one reason, the missing approval |
| condition 4 | `runs/m8_rd` (166 files), `m8_rd_rd2` (62), `m8_rd_rd3` (77), `m8_rd_rd4` (93), `m9_g1` (2,740) equal their D: increments (paths, sizes, mtimes, sha256; two independent checkers) |
| source snapshot | `D:\BattleShip_source_snapshots\2026-10-04_m9_g1_eval`, 93 files, `snapshot.json` sha256 `3e683bd407cd0f60cffb4408c5180d397e4b9758d1af88c947c0cdb4ff82ada8`; tool verify PASS; independent PowerShell re-hash checked 94, bad 0, executable equal |
| approval | `docs/rl_m9_g1_eval_approval.json` (sha256 `fb2d91fa...`), written from fresh identities after the snapshot; the preflight with it passed (`ok: true`, no problem) |
| the session | one run, `python -B -u -X utf8 rl/m9_eval_session.py run`, launched 23:33:51 UTC, its own preflight first; session clock **1,145.5 s (19.1 min) of the 2,700 s cap**; P1 9 s, evaluation 967 s, verification 148 s, close 21 s; exit 0; no retry, no extension |
| P1 | T_clear replayed exactly from tick 0 (2,326 ticks, clocks 2,325 / 2,326, chain equal to the rd4 verifying replay's and to the copied table, v3 table equal, tick-0 record equal to the pin) |
| evaluation | **675 of 675** planned episodes; 1,841,708 native ticks (prefix 1,437,300, policy 404,408; cap 2,500,000); 0 lifecycle failures; no stop |
| verification | **99 of 99 clears replayed exactly** (0 inexact, 0 skipped, 0 errors), 244,133 ticks; every counted clear is verified |
| caps | total **2,088,167 native ticks** of 3,105,000; at most **10** BattleShip processes (225 samples); main process private peak 891 MB (cap 3,072), tree private 6,088 MB (9,216), working set 1,907 MB (4,096), system available min 6,106 MB, commit free min 11,072 MB; no breach |
| close | write guard and provenance: no violation; executable and runtime pins unchanged; the five protected trees equal their increments; metadata audit 685 files / 999 lines clean; no BattleShip process left |
| `verify-run` | re-derived every cell and reading from the records (equal to the recorded outcome), every sticky mask from its key, every word sequence from the registered prefix and the submitted words; `ok: true` |
| status | **COMPLETE** (`runs/m9_g1_eval/session/outcome.json` sha256 `66f7bd83...`) |
| backup | `D:\BattleShip_runs_backup\2026-10-04_incr_m9_g1_eval`: 1,393 files, 162,003,001 bytes, manifest sha256 `ab3e6c61ffe3cbbb39f39308881283646b92dc857fa27254abe676c0b29f48a0`; tool backup + verify PASS and a separate verify PASS; independent PowerShell re-hash 1,393 / 1,393, 0 missing, 0 extra, 0 bad |
| after the backup | the five earlier trees again equal their increments (both checkers; the g1 increment's own PowerShell re-hash 2,740 / 2,740 PASS); `runs/` coverage **413,608 source files, 0 uncovered** (11 increments) |

## 4. Part C results

Verified clears of 20 (stochastic cells) or of 1 (deterministic). In brackets: the policy's value estimate and entropy at the handover observation.

**Stochastic, sticky p = 0.25 (the training mode):**

| start | untrained | 409,600 | 614,400 | 1,228,800 | final | tape (same keys) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **2,128** | 1 [-0.68, 4.28] | **9** [+1.73, 4.15] | 3 [-2.69, 4.10] | 1 [-0.68, 4.04] | **0** [-2.28, 3.77] | 6 |
| **2,250** | 0 [-0.82, 4.28] | **5** [+2.01, 4.11] | 4 [-2.75, 4.11] | **5** [-0.89, 3.92] | **0** [-2.44, 3.32] | 20 |
| **2,010** | 0 | 0 | 2 | 1 | 0 | 3 |

**Stochastic, unperturbed:**

| start | untrained | 409,600 | 614,400 | 1,228,800 | final |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2,128 | 0 | 6 | 3 | 5 | 0 |
| 2,250 | 0 | 7 | 7 | 3 | 7 |
| 2,010 | 0 | 0 | 0 | 0 | 0 |

**Deterministic (argmax), unperturbed:** no clear in 14 of 15 cells. The exception is the final policy at 2,250, which clears (its sticky cell there: 0 of 20).

**What the episodes did (stochastic sticky):** at 2,010 the final policy broke target 8 in **10 of 20** (untrained 3, 409,600 2) and target 1 in none. The
409,600 checkpoint broke target 1 in 6 of 20 there, always before target 8, so those episodes fell with 8 still standing. At 2,128 the final policy ended 9 falls
and **11 horizon**: it mostly stayed on the floor. The frontier skill grew while the last-section skill was lost.

**The pre-registered readings (plan section 6), as recorded:**
* **H1: `supported_decay`** at 2,128 (409,600 against final: 9 to 0, pairs 9-0, p = 0.0020) and at 2,250 (5 to 0, pairs 5-0, p = 0.031). Interference: **not
  supported**. The untrained policy scores 1 and 0 there, so the final is back at the random level, not below it.
* **H3: move 16 `supported`** (2,010: 2 of 20 for the stall checkpoint, 1 of 20 after the move, against a nominal 6). **Move 9 `competence_real`**: at 1,509 s the 409,600
  checkpoint cleared 9 of 20 at 2,128, inside the strip [2,120, 2,140) that move 9 passed. That early move was earned, and its competence was later lost (H1).
* **H2 premise: `holds`.** Argmax failed in every cell with at least 5 sticky clears (409,600 at 2,128 and 2,250, 1,228,800 at 2,250). The one argmax clear (final,
  2,250) is in a cell where the sticky policy fails.
* **Stickiness (reported):** final at 2,250, 7 unperturbed against 0 sticky. At 2,128, the gate's landing, the final is 0 either way, so stickiness does not explain the
  gate's failure there.
* **Tape margin (reported):** no checkpoint beats the tape by 5 anywhere; the best is 409,600 at 2,128 (+3).
* Under these keys the tape cleared **6 of 20 at 2,128**, against 13 of 20 under g1's P4 keys for the same words. At 20 episodes the tape control's own count moves by
  that much between key sets.

**The decay over checkpoints is not uniform.** At 2,128 it is gradual (9, 3, 1, 0), following the frontier into 2,040-1,980. At 2,250 the sticky rate held at 4-5 of 20
until 1,228,800 and dropped to 0 in the last 167,360 transitions, while the final's unperturbed rate there (7 of 20) shows that what remains is fragile under
perturbation.

## 5. Verdict on H1-H3, with the evidence

* **H1, forgetting: supported.** Direct, paired evidence at two fixed start states (section 4). Supporting records: the 2,128-2,188 training segment fell 30 % -> 9 %
  (2.3); success after reaching the 2,128 phase fell 27 % -> 0 % (2.4); the late-state values collapsed from +1.7/+2.0 to -2.3/-2.4, and from about +8.5 to -4.0 at
  2,300 (2.6). One qualification: "later sections were rarely reached" is too strong. The final section kept about 200 practice episodes per 500 and kept being
  reached. The decay coincides with the frontier region's dominance, its 85-90 % falls on the same left floor, the growth of the climb to target 8 and of horizon
  endings. In short, the frontier's gradient overwrote the final drop.
* **H2, stochastic dependence: contradicted** as the explanation of the NULL. There was no train / evaluation mode mismatch (2.1). Its descriptive premise (argmax does
  not clear where sampling does) holds in every cell where it could be tested, and is not why the gate failed.
* **H3, lucky frontier moves: supported.** 9 of 16 moves were not backed and the last three not at all (2.2). The checkpoints around the last two moves cleared that
  strip's start 1 and 2 times in 20 (section 4). The reported backward rate of 320 route ticks per hour was not competence: the policy's reliable reach never
  extended past the last 26 ticks (R_fine 2,300), and at its best (409,600) it reached 45 % at 2,128.

## 6. Recommendation for M9-g2 (not a design; nothing authorised)

**One primary change: make the frontier move only on demonstrated, sustained competence**, with a statistically controlled pass. For example, a lower confidence bound
on the strip's pooled rate over many outcomes instead of "any block of 10 with 3 clears, retried without limit". That bound would be re-checked at the later landings
so the pointer cannot move while they decay.

Why this one:
* H3 is the first link of the chain. The decay of the last section (H1) began when the pointer passed through moves 14-16, which were not backed. Then 85 % of
  starts went to a region where the policy succeeded about 4 % of the time, and its 85-90 % falls on the same floor drove the critic and the policy away from the final
  drop. A frontier that waits for competence would have held starts where the policy was still learning (2,040-2,120). There the evaluated 409,600 checkpoint cleared
  2,128 at 45 %.
* It changes what the gate's own progress measure means, so later results become interpretable: the pointer would mean reach.

Why not the others, on this evidence:
* **Start sampling across all exposed points** addresses H1 directly, but leaves H3 in place: the pointer would still run ahead on repeated tries. It is the natural
  second lever if the competence-gated frontier still shows decay.
* **A larger budget** with the same rule would spend it at a frontier with about 4 % success. Decay continued to the last checkpoint (2,250 fell from 5 to 0 in the
  final 167,360 transitions).
* **Deterministic evaluation alignment**: H2 is contradicted. Training and the decision already used the same mode.
* **Self-imitation** of the agent's own routes: the policy stayed at 90 %+ entropy, so sharpening might help. But this diagnosis does not isolate a lack of
  exploitation as the cause, since plain PPO did reach 45 % at 2,128 before losing it. SIL stays a separate decision, as before.

**Honest budget estimate.** The only measured real progress is the last section: about 200 route ticks (2,128-2,326) reached 45 % sticky / 30 % unperturbed by
409,600 transitions (about 25 minutes of g1 training), and even then not the last 76 ticks reliably (25 % at 2,250, where the tape clears 20 of 20).

The gate is demanding at 2,128: with the P4 tape at 13 of 20, it requires at least 18 of 20 clears there. No checkpoint was within 9 of that.

If a competence-gated frontier preserved even the early rate of real progress (about 200 route ticks per 0.4 M transitions, ignoring the harder target-6 and
left-floor segments), the left side to 1,694 (about 630 route ticks) would need at least about 1.5-3 M transitions. Late starts are short episodes, so staging dominates
(P3 measured 158 transitions/s at starts 2,250-2,310, against the training median of 442/s). That is roughly **2-5 hours** of wall time, not one.

The crossing and the right side to tick 0 (2,326 route ticks, the moving platform twice) would be an order of magnitude more (**15-30 M transitions or more, days**),
consistent with the published backward-algorithm costs being far above g1's budget. These are extrapolations from one run and one seed. The evidence does not show
that any budget suffices with this recipe; it shows that one hour at this frontier rule produced reach of only the last 26 ticks.

## 7. What this does and does not say

* It says, for this one run: the final policy's failure at the last landing is forgetting of a skill an earlier checkpoint had (H1). The frontier's progress after
  2,040 was not competence (H3). The action mode was not the problem (H2).
* It does not say that even the best checkpoint would have passed the gate: at 9 of 20 against a tape of 13, it would not. It says nothing about other seeds,
  observations or rewards. It does not change the registered NULL. It authorises nothing: no g2, no second seed, no extension.
* No RNG seed was inspected, logged, controlled, compared or hashed. Every start state is a prefix of the agent's own verified route. Process restart was the reset.
  The submitted canonical words are the replay truth. No fixture, TAS or human recording was read.

## 8. Evidence

* Run tree `runs/m9_g1_eval/` (Git-ignored, 1,393 files): `session/` (open, p1, tables, eval_run, verification, close, outcome, memory), `eval/episodes.jsonl` (675
  records, sha256 `95472160...`), `artifacts/` (675 M4-form episodes), `verification/replays.jsonl` (99, sha256 `2d434327...`), `lineages/T_clear/` (copied tables),
  `launch/` (preflights, snapshot records, run stdout / stderr), `derived/` (verify-run, report, the three-pass record, the Part A analyses and their outputs, tree
  checks).
* D: increment `D:\BattleShip_runs_backup\2026-10-04_incr_m9_g1_eval` (manifest `ab3e6c61...`); source snapshot `D:\BattleShip_source_snapshots\2026-10-04_m9_g1_eval`.
* git: HEAD `45f0486`; no tracked file changed; new untracked files only (section header table).
