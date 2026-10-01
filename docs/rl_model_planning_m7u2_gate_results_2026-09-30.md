# M7u2 gate `m7u2`: results (run 2026-10-01 03:18Z; session date 2026-09-30)

**Result: PASS, one seed, scope-limited.** The frozen m7u1 model with the unchanged planner reached **7 of 24** rare
airborne points from the normal tick-0 reset. The no-model control (RC) reached 0 and the scrambled-goal control (S)
reached 0.

**Scope, in the only words this result supports:** rare airborne-point reach initiated from normal reset on one seed
(frozen m7u1 model, 24 goals drawn from this run's own 360-episode behaviour pool). It is **not** a landing, wall-top
reach, crossing, target result or clear. No trial cleared the stage and none broke a target that this gate checked. The
selected baseline remains **M7n v3 with reward v2**; nothing here changes it.

## 1. What was authorised and what was done

- **Amendment 1** (before any native tick): goal selection prevents exact duplicate goal definitions only. It keeps one
  goal per source episode and the deterministic sha ordering, allows overlapping boxes, records the overlaps and describes
  the goals as correlated. Record: `docs/rl_model_planning_m7u2_amendment_2026-09-30.md`. The previous preparation record is
  preserved byte-identically (`..._implementation_preparation_r0.md`, `f062a467…`). The supply-probability table of the
  removed rule was withdrawn and replaced by a labelled binomial estimate.
- **Re-verification on the final code:** unit suite 13 / 13 (with no approval record, and again with the real one present);
  production-count offline e2e (505 s) passed; rule self-test; preflight refused for exactly one reason (no approval), then
  passed after approval.
- **Source snapshot** `D:\BattleShip_source_snapshots\2026-09-30_m7u2` (54 files + 4 pre-amendment reference files):
  tool `snapshot` PASS, tool `verify` PASS, and an independent PowerShell re-hash (58 checked, 0 bad, executable hash
  equal). `snapshot.json` sha256 `a65193ad…`.
- **Approval** `docs/rl_model_planning_m7u2_gate_approval.json` (`4802bf32…`) was written from a freshly generated and
  reviewed template: only the goal-contract digest and the code hashes of `m7u2_{goals,gate,tests}.py` differ from the
  preparation's template; every budget, cap, seed, model and rule entry is identical to the authorisation.
- **Launched once**, detached, 03:18:46Z (`python rl/m7u2_gate.py run`). No retry, extension, extra pool, relaxed
  eligibility or post-approval repair occurred. The code was not modified after the snapshot.
- **Machine readiness** (preflight, zero ticks): 5.9 GB available, 14.9 GB free commit, planning decision median 0.317 s,
  p95 0.327 s (limit 0.5 s); no BattleShip process. I did not close any application.

## 2. Outcome and paired results (registered rule `m7u2_tick0_rule_v1`, unchanged)

| arm | goals reached of 24 |
| --- | ---: |
| **P** (planner commanded g) | **7** |
| RC (candidate 0 at every decision, no model) | 0 |
| S (planner commanded π(g)) | 0 |

| pairing | P only (b) | other only (c) | both | neither | b − c | threshold |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| P vs RC | 7 | 0 | 0 | 17 | **7** | ≥ 6 |
| P vs S | 7 | 0 | 0 | 17 | **7** | ≥ 5 |

n_P = 7 ≥ 6; PASS holds on all three conditions; no blocker; no NULL reading applies. Per-goal, the exact one-sided sign
probability of 7 discordant pairs all favouring P is 2⁻⁷ = 0.0078 (against either control).

**Successes** (all replayed exactly from tick 0 except the 7th, which the registered replay cap does not cover):

| goal k | pool entry, τ | goal (x, y) | rise | reach tick | witness composition | ambiguity flag | replay |
| ---: | --- | --- | ---: | ---: | --- | :-: | --- |
| 3 | c322, 39 | (442, −892) | 1,658 | 60 | up-B | no | exact |
| 5 | c193, 73 | (−1650, −1222) | 1,328 | 73 | ground jump + double jump | no | exact |
| 10 | c060, 70 | (1788, −1190) | 1,360 | 115 | ground jump | yes | exact |
| 12 | c196, 90 | (750, −602) | 1,948 | 77 | ground jump + double jump | yes | exact |
| 13 | c105, 68 | (−1640, −2234) | 316 | 73 | ground jump + double jump | yes | exact |
| 14 | c210, 86 | (−1497, −1367) | 1,183 | 49 | ground jump + double jump + air tornado | no | exact |
| 16 | c138, 39 | (749, −822) | 1,728 | 97 | ground jump + double jump | no | not replayed (cap: first 6 P) |

The 7 reach ticks (49-115) are all inside the 128-word budget. No trial of any arm fell (0 of 72); none cleared.

## 3. Goal overlaps: the 24 goals are correlated, and the evidence is weaker than "7 of 24 independent"

Amendment 1 allows overlapping boxes, so overlap is reported rather than prevented. 0 exact duplicates were found
(0 passed over, 0 skipped).

- **21 of 276 goal pairs overlap.** They form **5 correlated groups** covering 16 goals, with 8 goals standing alone (13
  independent units in total).
- Groups (registered indices): {1, 3, 6, 11, 12, 16}, {2, 19}, {5, 14}, {8, 21}, {13, 18, 22, 23}.
- **P's 7 successes fall in 4 of the 13 units**: group {1, 3, 6, 11, 12, 16} (goals 3, 12, 16: 3 of its 6), group {5, 14}
  (both), group {13, 18, 22, 23} (goal 13 only: 1 of 4), and the stand-alone goal 10. RC and S reached no goal in any unit.
- **Unit-level reading (descriptive only; not the registered rule and not a change to it):** if each unit counts once, P
  reaches 4 of 13 units against 0 for either control, with exact one-sided sign probability 2⁻⁴ = 0.0625. That is
  markedly weaker than the goal-level 0.0078, and the registered threshold n_P ≥ 6 would not be met on unit counts. The
  PASS is the registered one; it should be read with this correlation in view.

## 4. Pool, goals and selection

- **Pool:** exactly c000..c359, 360 episodes of 128 words each from the normal reset (46,080 ticks, 0 falls), all reset rows
  equal to the tick-0 record, all word streams equal to their offline regeneration.
- **Eligibility:** 203 of 360 episodes had at least one candidate point; 823 eligible points (rarity ≤ 1 of 92 references)
  in **63 episodes (17.5 % yield**, above the 13 % estimate and the 7.6 % lower bound); 24 goals registered, goal digest
  `1af171cc…`.
- **Goal properties:** rises 316-2,936 above the spawn; x from −1,650 to 1,788; 20 of 24 goals were reached by at most 1
  of 92 reference episodes and 4 by none.
- **Independent re-derivation:** I re-ran `select_goals` on the stored pool sidecars; the goals digest and the whole
  selection record are identical to the stored ones. Selection has no outcome argument.

## 5. Resource use

| phase | native ticks used (cap) | wall (cap) |
| --- | ---: | ---: |
| P1 identity (m7u1 `g26_P` 171 + `g14_P` 183, exact) | 354 (354) | 8.6 s (120) |
| pool, 360 × 128 | 46,080 (46,080) | 246.0 s (600) |
| goal selection | 0 | 0.4 s (120) |
| evaluation, 24 × 3 | 8,864 (9,216) | 385.9 s (1,200) |
| success replays + analysis (6 P replays: 60+73+115+77+73+49) | 447 (1,280) | 67.9 s (300) |
| **total** | **55,745 (56,930)** | **712.7 s = 11.9 min (2,400)** |

Main-process private memory peaked at **1,054 MB** (cap 3,072). No cap was reached. The gate clock ran 03:20:44Z-03:32:33Z;
launch to exit, including the gate's internal preflight, was about 13.8 min (launched 03:18:46Z). Whole-tree
memory was not sampled in this run (the driver samples the main process only); the m7u1 whole-tree figures (6.1 GB private,
2.5 GB working set) are the closest reference.

## 6. Integrity and replays

- **Integrity problems: none.** The frozen parameter digest `0e70af78…` was checked before and after evaluation and after
  analysis; no optimizer was constructed (zero optimizer steps).
- **P1:** both m7u1 replays exact (words, every stored row field, reach tick, action digest).
- **Tick 0:** all 72 trial files (checked again after the run, independently of the driver) have `t = 0`, an empty prefix, a
  first row equal to the tick-0 record in every field, `input_tick` equal to the number of words, and at most 128 words.
  No prefix or archived start existed in any entry.
- **Success replays:** 6 of 6 registered P replays exact from tick 0 (words, rows, reach tick). No RC or S success existed
  to replay. The 7th P success (goal 16) is outside the registered "first 6 P" cap and was not replayed.
- **Contracts:** reset observation consumed no update; action tick T executed one native update; consumed_tick = T and
  input_tick = T + 1 (enforced by the drive loop per step). No native RNG was inspected, logged, compared or hashed. No human
  recording or TAS entered the run. All 72 Track 1 combinations remain available (no action table changed).

## 7. Failure interpretation (17 P failures)

Reported diagnostics, not part of the rule:

- **Attribution:** 12 MODEL (the model predicted a reaching plan that the native game did not realise), 5 PLAN (no
  decision ever predicted a reaching continuation; goals 0, 9, 15, 21, 23). MODEL share 0.71.
- **Witness test from tick 0:** the ensemble accepts the pool episode's own recorded path to the goal from the reset state
  for only 1 of 24 goals (4 %). So the planner usually reached goals by plans other than the witnessed path, or failed.
- **Model accuracy on the pool (one step):** position error median 2.09, p99 52.7; status accuracy 0.957. Open-loop error
  from tick 0 grows to median 106 / 298 / 559 at 16 / 32 / 64 ticks. In executed plan blocks the median error was 26 and 52
  of 1,446 blocks exceeded the ±150 box (AUROC of the spread against error 0.85).
- **Ambiguity flags** (conditional status, shield, break-without-attack, projectile, second air tornado): set for 3 of the 7
  successes (goals 10, 12, 13) and 7 of the 17 failures; no flag class alone separates the groups.
- **Movement census:** the successful P arm initiated its own rise by tick 1 in 6 of 7 (goal 13 at tick 33). Initiated rises
  per arm: P 23 of 24 trials (16 with a double jump), S 24 of 24 (17), RC 15 of 24 (7). S initiated as many rises as P and
  reached none, so reach is not explained by "jumping at all".
- The overall reading: from rest the model-guided planner is reaching a minority of rare airborne points; most failures are
  rollout error (plans that look reaching in the model but do not natively), a smaller share are plans never found.

## 8. What this does and does not establish

**Establishes (one seed, one frozen model, the registered rule):** planner-controlled reach of 7 behaviour-drawn rare
airborne points from the normal tick-0 reset, within 128 ticks, more often than the same machinery without the model and
than the same planner commanded elsewhere, with 6 of 6 replays exact from tick 0. With the correlation in §3, the number of
independent goals reached is lower (4 of 13 units).

**Does not establish:** a landing, wall-top reach, a crossing, targets, a clear, speed, goals beyond 128 ticks or sequences
of goals, goals not drawn from behaviour, replication across seeds or retrained models, or any advantage over PPO. It does
not change the selected baseline.

## 9. Evidence and backup

- **`runs/m7u2/gate/`** (Git-ignored, 4,131 files, 234 MB): `_gate/state.json` (`f1fc4458…`), `goals.json` (`f16ac74a…`),
  `pool.json` (`b6f3a444…`), `model_inputs_trials.npz` (`54c7ec26…`, 8,864 transitions, 72 episodes), `trials/*.npz` (72:
  native rows, canonical words from tick 0, per-decision candidates, scores, member predictions, histories), worker artifacts
  and sidecars for P1, the pool, evaluation and replays, and `_gate/launch/` (stdout/stderr, both preflight outputs, the
  template, an approval copy, a snapshot copy, the e2e log, the snapshot and verification tools).
- **Backup coverage before the run:** 393,911 `runs/` files, 0 uncovered, over the base and 3 verified increments. Earlier
  PASS records were not overwritten.
- **D: increment** for the new evidence: see §10.

## 10. D: increment

`D:\BattleShip_runs_backup\2026-09-30_incr_m7u2`:
- `rl/tools/runs_backup.py backup --source runs/m7u2`: 4,143 files, 232,824,256 bytes; `verify` PASS (0 hash mismatches,
  inventories equal); manifest `b49f53c9…`.
- An independent PowerShell re-hash of every file (D: copy vs source vs manifest), `increment_check.json`: 4,143 / 4,143,
  0 mismatches, PASS.
- 457 reparse points were skipped by design; all are per-worker `.tcc` links to the build tree, not evidence.
- **Combined coverage afterwards:** 398,054 `runs/` files, 0 uncovered, over the base and 4 increments. The earlier records
  and increments were not touched. The copy of this report under `runs/m7u2/gate/_gate/report/` is the version before this
  section was filled in.
- The approval record still matches the current code identity after the run (the code was not modified after the snapshot).

## 11. Working tree

No tracked file was modified. New untracked files: `rl/m7u2_{goals,rule,gate,tests}.py`, the m7u2 proposal, implementation
record, preparation record, amendment record, approval record and this report. Nothing was committed or pushed; no video was
made; no follow-on run is authorised.
