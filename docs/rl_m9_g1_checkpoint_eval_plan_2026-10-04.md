# M9-g1 checkpoint evaluation plan (2026-10-04)

**Status: plan, written before any native tick of this evaluation.** Nothing here trains, builds an optimizer, edits an existing file or touches
`runs/m9_g1/` or any M8 tree (all read-only; they must stay byte-identical to their D: increments). The diagnosis that motivates it is
`docs/rl_m9_g1_diagnosis_2026-10-04.md` (Part A, zero native ticks). This plan is fixed before the evaluation runs; the readings in section 6 are
pre-registered and are applied unchanged.

Scope label for every record of this evaluation: *M9-g1 checkpoint evaluation: frozen, pinned M9-g1 checkpoints evaluated read-only at three start states
of the trunk (stochastic sticky, stochastic unperturbed, deterministic unperturbed, paired open-loop tape); diagnostic only; no training; not a gate and not
a change to the registered M9-g1 outcome (NULL).*

## 1. Why an evaluation is needed (from Part A)

| hypothesis | Part A verdict from the preserved logs | what is still open |
| --- | --- | --- |
| H2 stochastic dependence | **contradicted as the explanation of the NULL**: training, the frontier rule and the decisive reach evaluation all used the same action mode (stochastic sampling, sticky p = 0.25); deterministic episodes were only reported | nothing for the NULL; the evaluation adds per-checkpoint deterministic and unperturbed readings |
| H3 lucky frontier moves | **supported**: 11 of 16 moves passed only after repeated blocks (2 to 50) while the pooled strip rate at that pointer was 3.5-23.3 % (upper 95 % bound below 30 % for six of them, including the last three moves); 9 of 16 strips never showed a 30 % rate before or after their move | corroboration at the checkpoint nearest a late move |
| H1 forgetting | **partly supported, not decided**: the second left-floor segment (starts 2,128-2,188) fell from 34/113 clears (30 %) to 6/66 (9 %); the clear rate after reaching the post-target-8 phase fell 27 % -> 14 % -> 0 %; critic values at the late trunk states collapsed (final V(2,300) = -3.96 where the true return is about +11). But the airborne drop (2,189-2,249) and 2,250-2,299 did not decay, and the log rates mix a continuously changing policy, shifting start mixtures and small late samples | whether the policy's ability at fixed late start states actually decayed between checkpoints, and whether it ever exceeded the untrained (uniform) policy there |

## 2. Checkpoints (5, chosen from the frontier history; pins from `runs/m9_g1/training/checkpoints.json`)

| checkpoint | transitions | training wall | pointer at that time | why | model.zip sha256 |
| --- | ---: | ---: | ---: | --- | --- |
| `ckpt_000000000` | 0 | 7.5 s | 2,300 | the untrained initial policy (per-state entropy 100.0 % of maximum at every trunk state: the uniform random baseline) | `16dc29c9cac05322d3562dbc3bc865e157b6ede49969c8b0c209aa91e61d5c77` |
| `ckpt_000409600` | 409,600 | 1,509 s | 2,040 | 28 s after move 13; end of the fast phase; the window in which the late segments cleared best in training (2,128-2,188: 30 %) | `bb6ce1ad101abad60078a34893f93ca855752169ea771b7ca93040a86ffacc45` |
| `ckpt_000614400` | 614,400 | 2,112 s | 2,000 | 83 s after move 15 (2,020 -> 2,000, earned on a pooled 6/170); start of the 1,227 s stall | `049807de6e7f9cc719bfba3367a933f2baa0d1d8dd910f4b4087c8dcbfc86568` |
| `ckpt_001228800` | 1,228,800 | 3,356 s | 1,980 | 99 s after move 16 (2,000 -> 1,980, earned on a pooled 21/500) | `21c7ba3635a84d9d6ec4da27ad0ed471d4feaec58892c0a7b8d852cb6ce8c22e` |
| `final` | 1,396,160 | 3,602 s | 1,980 | the frozen final policy the gate measured | `c56cb8dc386f1cd8a3a3a5928e87f073d346ebf2805721caad14a5db3a4fc9e2` |

Each `model.zip` is read once, its sha256 must equal the pin (else nothing runs), and only its `policy.pth` tensors are used (section 4).

## 3. Start points (3, on the trunk T_clear, all inside the shared prefix)

| start tau | trunk state | why |
| ---: | --- | --- |
| **2,128** | the second left-floor landing (registered landing state); target 8 broken, target 1 left | the gate's last landing: g1 final 0/20 sticky, tape 13/20; the training segment that decayed (30 % -> 9 %) |
| **2,250** | airborne in the final drop toward target 1 (76 ticks before the trunk's clear) | late-section control: in training this region did not decay (20-35 %); g1 final fine grid 2/10 |
| **2,010** | the first left-floor segment (grounded 1,966-2,020), targets 8 and 1 left; inside the strip [2,000, 2,020) whose block passed move 16 | the frontier: tests whether the checkpoint near the last moves had the nominal 30 % competence there (H3) and whether frontier competence rose while late competence fell (H1) |

The registered landing 1,966 is not used: it lies on the same grounded segment as 2,010, 44 ticks earlier, and the final, the mid checkpoint and the
tape all scored 0 there; 2,010 is the exact strip of the last move.

## 4. Modes, counts, keys

Per (checkpoint, start point):

| cell | episodes | action | perturbation |
| --- | ---: | --- | --- |
| stochastic sticky (the training mode) | 20 | sampled from the policy's two categorical distributions | sticky p = 0.25 (the M9 rule, `rl/m9_sticky.submit`) |
| stochastic unperturbed | 20 | sampled | none |
| deterministic unperturbed | 1 | argmax of each distribution (SB3's `mode()`) | none |

Plus per start point: **20 open-loop tape episodes** (T_clear's words by tick index, neutral after the end) under the **identical** sticky draws as the
stochastic sticky cells of every checkpoint at that point. Totals: 5 x 3 x 41 = 615 policy episodes + 60 tape episodes = **675 episodes**.

**Deterministic cells run 1 episode, not 20**: a deterministic policy in the deterministic game from the same exact start produces one trajectory; 19 more
episodes would be bit-identical replays of it. This is the only departure from "20 episodes per cell".

**Keys (Python-side sha256 uniforms; never the native RNG):**
- sticky: `m9|g1|sticky|ckeval:<tau>:<k>|<tick>` (`rl/m9_sticky` with the label `ckeval:<tau>:<k>`), shared by all five checkpoints and the tape at that point;
- action sampling: `m9|g1eval|act|<mode>|<tau>|<k>|<tick>|<stick|button>` with mode `sticky` or `unperturbed`, inverse-CDF on the policy's probabilities;
  **independent of the checkpoint** (common random numbers): episode k of two checkpoints sees the same perturbation and the same uniforms, so their
  outcomes are paired.

**Policy loading (no optimizer anywhere).** `torch.optim.Optimizer.__init__` is replaced by a function that raises before any checkpoint is read. The network
is rebuilt from SB3's own building blocks (`MlpExtractor` 606 -> [64, 64] tanh for pi and vf, `Linear(64, 17)`, `Linear(64, 1)`, `MultiCategoricalDistribution([9, 8])`);
no PPO object, no policy class. Validated at zero ticks: the rebuilt final network reproduces the first word of all 7 recorded g1 deterministic episodes from
the trunk's handover observations. The v3 observation is built by the unchanged `rl/m9_obs.V3Pipeline` in the workers, exactly as in g1.

## 5. Run structure, files, caps

New files only: `rl/m9_eval_policy.py` (pinned loading, the weight-only network, keyed sampling, the optimizer guard), `rl/m9_eval_ckpt.py` (jobs, runner,
session engine, readings), `rl/m9_eval_session.py` (CLI: preflight, approval template, run, verify-run, report), `rl/m9_eval_snapshot.py` (the verified D:
source snapshot), `rl/m9_eval_tests.py` (unit tests; a synthetic end-to-end session on the g1 stub world). Every other module is imported read-only and
unchanged (`m9_vec`, `m9_pool`, `m9_worker`, `m9_eval`, `m9_sticky`, `m9_obs`, `m9_lineages`, `m9_verify`, `m9_artifacts`, `m9_run.Clock`, `m9_session.build_real_env`,
`m8_rd*` helpers, `rl/tools/runs_backup.py`). Output tree: `runs/m9_g1_eval/` only.

| phase | content | wall cap | native-tick cap |
| --- | --- | ---: | ---: |
| open | the T_clear tables copied from `runs/m9_g1/lineages/T_clear` (read-only) into `runs/m9_g1_eval/lineages/`, checked against their registered sha256 | (in P1) | 0 |
| P1 | one fresh-process replay of T_clear from tick 0 with the verification flags: exact (digest, every consumed tick, breaks, clear facts, both clocks), its chain equal to the rd4 verifying replay's and to the copied table, its v3 table equal to the copied one, tick-0 record equal to the pin; any difference is INVALID | 120 s | 5,000 |
| eval | the 675 episodes, 10 process slots (staging and playing free-running, as g1's evaluation) | 1,740 s | 2,500,000 (675 x 3,600 = 2,430,000 is the worst case) |
| verify | every clear (policy and tape) replayed exactly from tick 0 (prefix + submitted words, the four read-only diagnostics), as g1's R11 | 420 s | 600,000 |
| close | identity of executable / runtime files / frozen configuration, the M8 and M9-g1 trees against their D: increments, write guard, metadata audit, leftover processes | 120 s | 0 |
| **session** | **hard cap 2,700 s (45 min)**; the session clock starts at the session object (after the preflight) | | **3,105,000 in total** |

Pessimistic projection: 120 + 1,740 + 420 + 120 + two pool spawns (30 s) + 4 x 20 s grace = **2,510 s**, 190 s under the hard cap. Expected: about 2.1 M ticks
at g1's measured evaluation rate (2,037 ticks/s) = about 1,050 s of evaluation, about 25 min in total.

Memory caps as g1 (main process 3,072 MB private; tree 9,216 MB private and 4,096 MB working set; system available >= 1,024 MB; commit free >= 2,048 MB;
a stop needs two distinct samples); **at most 10 BattleShip processes** (eval pool 10, P1 one, verification 8 threads). A memory or process breach stops the
session (INCOMPLETE); no application is ever closed.

**Priority order** (a cap ends the phase validly; cells left incomplete are reported as such and read only where complete): (1) the stochastic sticky cells
and the tape at 2,128, then at 2,250, then at 2,010, interleaved by k across checkpoints so that a partial cell stays paired; (2) the unperturbed cells, same
order; (3) the deterministic episodes. No retry, no extension, no second session.

## 6. Pre-registered readings

Notation: c(ckpt, tau) = verified sticky clears of 20; pairs = episodes with the same k at the same tau (identical keys). The **paired decline test** of
checkpoint A against B: b = pairs where A clears and B does not, d = pairs where B clears and A does not; decline when c(A) - c(B) >= 5 and the one-sided
exact sign test P(Bin(b + d, 1/2) >= b) <= 0.05.

| reading | condition | meaning |
| --- | --- | --- |
| **H1 supported (decay)** | at 2,128 or 2,250, `ckpt_000409600` or `ckpt_000614400` declines against `final` | the policy had acquired the late section and lost it while starts concentrated at the frontier |
| H1 supported, interference | additionally `ckpt_000000000` (uniform) declines against `final` at that point | training made the late section worse than the untrained policy |
| **H1 contradicted** | at both 2,128 and 2,250: no trained checkpoint exceeds `final` by 3 or more, and no trained checkpoint exceeds `ckpt_000000000` by 5 or more | there was nothing above the random level to forget; the log decline is a mixture/sampling effect ("never learned") |
| H1 undecided | anything else | reported with the numbers |
| **H3 supported (move 16)** | at 2,010: c(`ckpt_001228800`) <= 3 and c(`ckpt_000614400`) <= 3 | the checkpoints around the last moves did not have the nominal 30 % (6 of 20) at the strip that moved the pointer |
| H3 contradicted (move 16) | either of them >= 6 at 2,010 | the move was backed by real competence |
| H3 for move 9 | at 2,128 (strip [2,120, 2,140), passed at 1,175 s): c(`ckpt_000409600`) >= 6 says that strip's competence was real at that time (then the final's loss is H1); <= 3 says that move was not backed either | |
| H2 (premise) | deterministic episodes clear in no cell where the same checkpoint's stochastic sticky cell has >= 5 clears | "the most likely actions do not clear" holds across checkpoints; it remains not an explanation of the NULL (decided by the records) |
| stickiness (reported) | unperturbed exceeds sticky by >= 5 in a cell | the p = 0.25 perturbation is a material factor there |
| tape margin (reported) | c - tape per cell | the gate-style margin; never deciding here |

Counting: only clears verified by exact replay count. If the verification cap leaves a clear unverified and counting it could change a reading, that
reading is reported as undecided (incomplete), never as decided.

## 7. Conditions before any native tick (all must hold)

1. The new code's unit tests pass three consecutive times with no change in between (fingerprint of `rl/m9_eval_*.py` recorded before and after).
2. Every checkpoint digest equals its pin (checked by the preflight and again by the session).
3. The preflight passes apart from the approval: `python -B`, run root absent, the executable, runtime files and frozen configuration equal the archive's
   pins, git shows only new files, D: coverage 0 uncovered, no BattleShip process, readiness (memory, disk), the status table.
4. `runs/m8_rd`, `runs/m8_rd_rd2`, `runs/m8_rd_rd3`, `runs/m8_rd_rd4` and `runs/m9_g1` are byte-identical to their D: increments (paths, sizes, mtimes, sha256 against each manifest).

Then, as authorised: approval with fresh identities (written after the snapshot, naming it); source snapshot `D:\BattleShip_source_snapshots\2026-10-04_m9_g1_eval`
verified by the tool and an independent PowerShell re-hash; one session within these caps; afterwards the D: increment
`D:\BattleShip_runs_backup\2026-10-04_incr_m9_g1_eval` verified by the tool and an independent re-hash, the earlier trees re-checked, and `runs/` coverage
reported with 0 uncovered.

## 8. What it does not do

No training, no optimizer, no retry or extension, no change to the g1 outcome, no RNG seed inspection, logging, control, comparison or hashing, no
fixture / TAS / recording read, no route or waypoint in any decision of the policy (start states are prefixes of the agent's own verified route, used only to
place the evaluation), process restart is the reset, the submitted canonical words are the replay truth.
