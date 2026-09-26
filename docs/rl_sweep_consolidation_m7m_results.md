# M7m results: anchored backward consolidation of the M7l sweep (paired, n = 3)

Date: 2026-09-26 (UTC).

- **Design:** `docs/rl_sweep_consolidation_m7m_design.md`
- **Feasibility:** `docs/rl_sweep_consolidation_m7m_feasibility.md`
- **Frozen before any training:**
  - manifest `docs/rl_sweep_consolidation_m7m_manifest.json`, sha `e800b2da…`, equal to the frozen `runs/m7m/campaign/_matrix/manifest.json`;
  - rule `docs/rl_sweep_consolidation_m7m_decision_rule.json`, sha `307da299…`;
  - code fingerprint `fcb77771…` over 94 files;
  - HEAD `14f5a63`.
- **Recorded decision:** `runs/m7m/campaign/_matrix/analysis_n3.json`, sha `90c7a7b7…`, byte-copied to `docs/rl_sweep_consolidation_m7m_analysis_n3.json`.

## Registered decision: `null` (gate 4)

The rule reads: "no registered effect of the anchored starts at this budget."

- **Primary result.** R, the number of the 100 final stochastic tick-0 episodes per run that break all seven right targets by consumed tick 2699, is **0 in all six runs** (E 0/0/0, K 0/0/0).
- **Gate 1a** fails: 0 of 3 pairs have R_E ≥ 5 and R_E > R_K.
- **Gate 1b** (the static guard) would hold: pooled static targets S_E = 1479 and S_K = 1580, a difference of −101/300 = −0.34 per episode, within the −1/2 limit. It does not change the outcome, because 1a fails.
- **Gate 2** fails: no seed has R_E ≥ 1, and ΣR_E = ΣR_K = 0.
- **Gate 3** fails: every E schedule ended in window W2 [661, 780]. None reached W8 or completed.
- **Integrity (gate 0)** held throughout:
  - six runs verified;
  - 1,980 of 1,980 evaluation episodes, every label verified on its first attempt as tick-0 starts with clean metrics;
  - no native clear anywhere, so there was nothing to replay;
  - no manifest drift.

## Paired tick-0 results (final stochastic evaluation, 100 episodes per run)

| pair | arm | R | static S (mean) | L | target 2 (ticks) | falls | 7 right, any tick | left entries | verified clears | deterministic play |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | warm start (Phase K) | 0 | 471 (4.71) | 0 | 1 | 1 | 0 | 0 | 0 | collapsed (0.507) |
| 0 | E | 0 | 558 (5.58) | 2 | 2 (858, 2586) | 1 | 0 | 0 | 0 | collapsed (0.517), 1 target |
| 0 | K | 0 | 573 (5.73) | 0 | 1 (3188) | 0 | 1 | 0 | 0 | collapsed (0.863), 1 target |
| 1 | warm start | 0 | 475 (4.75) | 0 | 0 | 1 | 0 | 0 | 0 | not collapsed (0.25) |
| 1 | E | 0 | 499 (4.99) | 1 | 1 (840) | 0 | 0 | 0 | 0 | not collapsed (0.439), 4 targets |
| 1 | K | 0 | 502 (5.02) | 0 | 0 | 1 | 0 | 0 | 0 | not collapsed (0.153), 4 targets |
| 2 | warm start | 0 | 425 (4.25) | 1 | 2 | 0 | 0 | 0 | 0 | not collapsed (0.341) |
| 2 | E | 0 | 422 (4.22) | 1 | 3 (1743, 2646, 2933) | 0 | 0 | 0 | 0 | not collapsed (0.115), 4 targets |
| 2 | K | 0 | 505 (5.05) | 0 | 0 | 0 | 0 | 0 | 0 | not collapsed (0.225), 4 targets |

- **Pooled over 300 episodes per arm (the static-target column counts every target except ID 2):**
  - E: L 4, target 2 in 6 episodes, 1 fall.
  - K: L 0, target 2 in 1 episode, 1 fall.
- **Left side:** no episode in either arm entered the left side or broke a left target.
- **Deterministic plays** are each a single action sequence (100 identical episodes), with R = 0 and no target-2 break.
- **Curve points** (60 stochastic episodes each):
  - R was 0 everywhere except one episode at E2's +1,024,000 point, which did not persist to the final.
  - Static means rose over training in both arms, except E2 (4.35 → 4.22).
- **Against the shared warm start,** both arms gained static targets in pairs 0 and 1, and K gained in pair 2. E2 did not gain.

## Training: anchored starts are kept apart from normal-start play

| run | tick-0 episodes (by-2699 sweeps) | anchored episodes (by-2699 successes) | falls | final window (pointer) | blocks (passed) | stale / excluded | prefix ticks (dispatch wall) |
|---|---|---|---|---|---|---|---|
| E0 | 225 (0) | 273 (43) | 16 | W2 (780) | 26 (2) | 5 / 0 | 233,852 (232 s) |
| E1 | 237 (0) | 254 (67) | 2 | W2 (780) | 25 (2) | 3 / 0 | 234,244 (230 s) |
| E2 | 219 (0) | 270 (27) | 0 | W2 (780) | 26 (2) | 2 / 0 | 233,819 (230 s) |
| K0 | 426 (0) | 0 | 3 | — | — | — | 0 |
| K1 | 425 (0) | 0 | 1 | — | — | — | 0 |
| K2 | 425 (0) | 0 | 0 | — | — | — | 0 |

- **Normal-start training play never swept by tick 2699,** in 1,757 tick-0 training episodes. K0 had 4 seven-right episodes that finished after the deadline.
- **Pointer progression** (a curriculum diagnostic only). Transitions are counted after the warm start.

  | run | W0 passed | W1 passed |
  |---|---|---|
  | E0 | block 4 (7/10) at about 192k | block 25 (5/10) at about 1.40M |
  | E1 | block 18 (5/10) at about 1.03M | block 24 (7/10) at about 1.43M |
  | E2 | block 15 (5/10) at about 846k | block 17 (5/10) at about 985k |

  Every W2 block that finished scored 0/10, including nine in a row in E2.
- **What passed W1** (anchored outcomes by cut region, pooled over E0–E2):

  | cut region | right targets standing | successes | target-2 breaks by the policy |
  |---|---|---|---|
  | τ ≥ 838 | 7 only | 123 / 523 | — |
  | τ 801–837 | 2 and 7 | 14 / 96 | 43, of which 40 at exactly tick 837 (the anchor's up-B carried over) |
  | τ ≤ 800 | 3, 2 and 7 | **0 / 178** | 8 at other ticks (E0: 784, 815, 817, 842, 850, 1258; E2: 845, 2620), none followed by a sweep |

  The W1 passes therefore rest on the target-7-only cuts and on the inherited up-B. By the registered interpretation, they are not evidence that the target-2 step was learned.
- **Prefix replay cost** (reported separately, never counted as transitions):
  - about 234,000 ticks and about 230 s of synchronous dispatch per E run (255–276 dispatches);
  - E runs took about 26 min each, K runs about 23 min;
  - end-to-end throughput was about 990 transitions/s for E and about 1,125 for K.

## Pilot and integrity

- **Pilot** (registered cap +40,960 per arm, `runs/m7m/pilot`, report sha `5548af35…`). Both arms passed:
  - n_updates 6,000 → 6,080 and Adam step 60,000 → 60,800 on every parameter; policy digest changed;
  - num_timesteps 3,112,960; observation-statistics count = warm + 5 + 40,960;
  - E: 8 of 10 automatic-reset draws were anchored, all 8 delivered equal to the table, 7,529 prefix ticks;
  - K: 0 anchored draws and 0 prefix ticks;
  - schedule and log re-simulation exact; evaluation smoke tick-0 verified.
  - The pilot was never used for tuning, and every campaign run restarted from its pinned Phase K checkpoint.
- **Campaign runs.** All six are verified:
  - m7d training verification of the warm-start segment;
  - the lineage is exactly the pinned Phase K final, with only the diagnostic flag accepted;
  - n_updates 9,000, Adam step 90,000, num_timesteps 4,608,000, statistics count exact;
  - policy-only accounting, and the schedule re-simulated from its own log equal to the final checkpoint's state (in-flight rule included).
- **Resources.** Every launch gate passed on its first reading. No hard alert, no memory stop, no leftover process. Minimum available physical memory was 7.1 GiB; commit drawn was 5.06–5.25 GiB; at most 10 game processes.
- **M7l evidence** (rule, manifest, analysis and results; docs and frozen copies) is byte-unchanged.
- **Never done:** native RNG inspection of any kind, training videos, reward changes, extra seeds or budget extensions.

## Scope

- **One anchor, one budget, three seeds.** The result says that this schedule, from these warm starts, did not transfer the M7l training sweep into tick-0 play at +1,536,000 transitions. It says nothing about other anchors or budgets.
- **The bottleneck, observed but not proven.** No policy completed the sweep from any cut that required breaking targets 3 and 2 itself.
- **F4 and F5 remain feasibility evidence only.**
- **The source sweep stays a replay-verified M7l training event.**
- **"Right-side sweep before crossing"** remains a working route hypothesis.
