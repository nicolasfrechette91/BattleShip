# M7u gate `m7u1`: results (2026-09-30)

**Outcome: PASS.** The registered rule `m7u1_control_rule_v2` was applied once, unchanged. There were no integrity
problems, and no cap was reached.

**Scope:** local control after self-generated supplied prefixes, on one seed. A reach is a rising airborne point
64 ticks from a start state of this run's own held-out behaviour episodes. Nothing here is a reach from tick 0, a
landing, a crossing, a target result or a clear.

Earlier record: the first attempt stopped at preflight with zero native ticks
(`docs/rl_model_planning_m7u_gate_report_2026-09-30.md`, kept unchanged).

## 1. Paired outcomes (40 goals)

| arm | reached |
| --- | ---: |
| P: trained ensemble, commanded g | **22** |
| RC: no model (candidate 0) | **1** |
| S: trained ensemble, commanded π(g), scored on g | **8** |

| pair | both | only P (b) | only other (c) | neither | b − c | rule threshold |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| P vs RC | 1 | 21 | 0 | 18 | **21** | ≥ 8 for PASS |
| P vs S | 6 | 16 | 2 | 16 | **14** | ≥ 6 for PASS |

- **The rule:** n_P = 22 ≥ 10; no blockers.
- **Per goal** (digits give P, RC, S; 1 = reached):
  `0:000 1:000 2:000 3:100 4:100 5:000 6:101 7:100 8:000 9:101 10:100 11:100 12:000 13:000 14:100 15:000 16:100
  17:000 18:000 19:100 20:000 21:000 22:101 23:000 24:001 25:000 26:101 27:100 28:100 29:100 30:101 31:001 32:100
  33:000 34:100 35:100 36:100 37:101 38:000 39:110`
- **P reach time:** median 55 controlled ticks after the prefix (range 11-94, budget 96).
- **Trial ends:** every trial ended at its goal or at the budget. None ended by a fall.
- **Clears:** none (not a claim either way).

**What this PASS establishes** (implementation record §11, unchanged): on one seed, learned one-step predictions
searched by a fixed planner reached rare rising airborne points, 64 ticks away from own-prefix native states. They did
so more often than the same machinery choosing without predictions (RC), and more often than the same planner
commanded elsewhere (S). Every replayed success was exact.

**What it does not establish** (the rule's own list): reach from a normal tick-0 start, replication across seeds, a
wall-top landing, a wall crossing, targets, a clear, or speed.

## 2. Integrity

| check | result |
| --- | --- |
| P1: 2 pinned Track 1 artifacts through the M7u stack | 3,361 / 3,361 and 2,560 / 2,560 words, identical |
| collection | 92 / 92 episodes (cold start and standby promotion). RC regeneration equal on all 92. Every sidecar equals the streamed rows. The clock track is consistent on the 80 training episodes and equal on the 12 held-out ones |
| storage replay (training episode c046, from tick 0) | exact, 3,600 ticks, no differing field |
| reset worlds | every episode equals the pinned stage table |
| start identity at tick t (every stored field) | 120 / 120 |
| platform against the clock track during evaluation | no difference |
| model parameters through evaluation | unchanged |
| success replays | 9 / 9 exact (action digest, every row field, reach tick): 6 P, 1 RC (its only success), 2 S |
| ledger | within budget in every phase |
| stderr of the gate process | empty |

## 3. Diagnostics (reported; not part of the rule)

**Attribution of P trials.**
- All 22 successes were predicted by the model (0 unpredicted).
- The 18 failures split 9 MODEL (the model predicted a reach on the executed words, but it did not occur) and 9 PLAN
  (the executed plan was never predicted to reach).
- MODEL share: 0.50 over all failures, 0.40 over the 5 failures without an ambiguity flag.

**Witness test.** For each goal, the recorded 64-word continuation that reached it natively was rolled out from the
same start state. A majority of the 3 members predicted the reach for only **1 of 40** goals. Open-loop 64-tick
predictions of the recorded continuations mostly miss the 150-unit box. Yet closed-loop replanning every 4 ticks
reached 22 goals. This fits the compounding error named as the main scientific risk. It is reported as measured, not
explained further.

**Calibration** of the ensemble mean after 4 executed words:

| blocks | count | error > 150 | median error | AUROC of spread for error > 150 |
| --- | ---: | ---: | ---: | ---: |
| executed (P and S) | 1,582 | 56 (3.5 %) | 19.0 | 0.64 |
| held-out behaviour | 494 | 19 | 15.8 | 0.72 |

**Held-out accuracy** (31,181 transitions):
- One step: position error median 2.30, p99 52.3; status accuracy 0.951.
- Weakest status classes, all small samples: dead 0.48 (n 7), crouch / pass 0.51 (n 131), dash / run 0.59 (n 96).
- Open loop on recorded held-out words, position error:

  | horizon | median | p90 |
  | --- | ---: | ---: |
  | 16 ticks | 121 | 444 |
  | 32 ticks | 290 | 1,040 |
  | 64 ticks | 645 | 1,577 |

  This is consistent with the witness result above.

**Ambiguity flags** (trials with any flag; the rule counts all trials):

| arm | any flag | conditional status | shield | projectile | break without attack | reached: flagged / unflagged |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| P | 24 | 15 | 9 | 6 | 1 | 11 / 24, 11 / 16 |
| RC | 28 | 20 | 10 | 6 | 2 | 0 / 28, 1 / 12 |
| S | 23 | 13 | 11 | 5 | 3 | 4 / 23, 4 / 17 |

**Training.**
- 6,000 steps in 348 s.
- Total loss at step 6,000: 0.770 on training data, 1.002 held out.
- Vocabulary: 61 statuses, 16 floor / contact combinations, 28 hitlag / flag combinations (caps 160 / 128 / 64).
- 240,964 training and 31,181 held-out transitions.

**Goals.**
- 40 goals from the 12 held-out episodes, out of 1,901 candidates.
- Start ticks 95-591; pooled chance q ≤ 0.0171, so none was filled by the fallback rule.
- Digest `ce3fbc1a…`; frozen before training.

## 4. Resource use

| phase | native ticks | tick cap | wall (s) | wall cap (s) |
| --- | ---: | ---: | ---: | ---: |
| P1 | 5,921 | 5,921 | 10.6 | 180 |
| collection | 272,145 | 331,200 | 541.3 | 600 |
| storage | 3,600 | 3,600 | 6.9 | 120 |
| goals + training | 0 | — | 360.0 | 900 |
| evaluation: prefixes | 40,821 | 72,000 | 851.5 | 1,500 |
| evaluation: controlled | 10,171 | 11,520 | (included above) | |
| replays + analysis | 4,384 | 6,960 | 61.0 | 300 |
| **total** | **337,042** | **431,201** | **1,831 (30.5 min)** | **3,600** |

- **Wall time:**
  - The 60-minute clock starts at P1 (17:41:20Z). The run ended at 18:11:51Z.
  - Including the gate's internal preflight, launch to exit took 32.3 min (17:39:35Z to 18:11:51Z).
  - The projection was 1,702 s. Collection had the smallest margin: 541 s against its 600 s cap, projected 422 s.
- **Memory** (driver sampling and a read-only sampler every 15 s):
  - Main process: peak 1,471 MB private (cap 3,072), 1,190 MB working set.
  - Whole gate tree (6 Python + 10 BattleShip processes): 6,100 MB private, 2,483 MB working set.
  - System minimums: 3,861 MB available, 9,125 MB free commit.

## 5. Before launch

1. **Test-only repair, user-authorised.** `unit_approval_refusal` now runs the production `approval_status()` against
   an isolated temporary record.
   - Missing, PENDING and altered-identity records are refused; an unreadable record raises; a valid one is accepted.
   - The suite passed 17 / 17 with the real record present.
   - Four mutated checks all fail the test.
   - No other code changed.
2. **Source snapshot r2:** `D:\BattleShip_source_snapshots\2026-09-30_m7u1_r2`, PASS, 53 files, `snapshot.json`
   `91752bb5…`.
   - Hashes were recomputed from the copy; an independent PowerShell re-hash matched 53 / 53.
   - Its `repair.diff` shows the code identity changed only in `rl/m7u_tests.py`.
   - Snapshot r1 is intact.
3. **Approval r2** (`docs/rl_model_planning_m7u_gate_approval.json`, `71a3aafc…`) supersedes r1. r1 is preserved
   byte-identically as `docs/rl_model_planning_m7u_gate_approval_r1_superseded.json` (`37c71311…`) and linked by path
   and hash.
4. **Coverage:** 391,625 files, 0 uncovered. **Standalone preflight:** PASS, with no problems.
5. **Machine readiness.**
   - Avidemux and OBS were no longer running; no application was closed by me.
   - Memory: 6.28 GB available, 16.8 GB free commit.
   - My first threshold (8 GB free physical) treated M7s's 6.2 GB private tree as physical need. M7s's own record
     shows a 2.6 GB working set, launched from nearly identical conditions (6.8 / 16.7 GB). The launch used that
     measured basis.
   - Planning latency: 0.389 s median, 0.401 s p95 (benchmark 0.316 / 0.319).
6. **Launched once,** detached: `python rl/m7u_gate.py run`, 17:39:35Z. No retry, extension or repair followed.

## 6. Evidence

- **`runs/m7u/gate/`** (Git-ignored):
  - `_gate/state.json`, `goals.json`, `collection.json`;
  - `model.pt`;
  - `model_inputs_train.npz` and `model_inputs_heldout.npz`, separate files;
  - `model_inputs_trials.npz`;
  - `trials/*.npz` (120): native rows, canonical words from tick 0 with the supplied prefix, candidates, scores and
    member predictions;
  - the worker artifacts and sidecars of every phase;
  - `_gate/launch/`: launch, readiness, preflight, memory samples, approval copies r1 and r2, tools;
  - `_gate/report/`: a copy of this report.
- **D: increment** `D:\BattleShip_runs_backup\2026-09-30_incr_m7u`:
  - tool verification PASS;
  - an independent PowerShell re-hash of every file (copy vs source vs manifest) in `increment_check.json`, PASS;
  - with it, combined coverage of every `runs/` file, 0 uncovered;
  - the 30 earlier D: records and manifests byte-identical.
- **Stop evidence of the first attempt:** `D:\BattleShip_runs_backup\2026-09-30_incr_m7u_logs`, unchanged.
- **Working tree:** no tracked file modified by this work. The M7u files you staged are left as staged, with later
  edits unstaged. Nothing was committed or pushed, no video was made, and no follow-on run is authorised.
