# M7s stage 1 gate `m7s1` (learned return, GCSL): results (2026-09-29)

**Registered outcome (rule `m7s1_return_rule_v2`, applied once): 3 — inconclusive.** No seed is a rare pass, and none
meets the failure conditions. The same blocking condition holds in all three seeds: **the learner was not functional on
the mid goals**. In seed 0, T = 2 was also in the gap. All three trained R policies are also **goal-blind** (post-training
goal-swap action TV 0.0030 / 0.0063 / 0.0051 < 0.01). This did not decide anything, because no seed met the rare
criteria. There was no integrity problem, no budget overrun, no clear, and every claimed return that was replayed
replayed exactly. **A null here is not a rejection** (design section 6): the method did not become functional at this
budget.

Design: `docs/rl_goal_exploration_design_2026-09-28.md` (revision 5). Implementation record:
`docs/rl_gcsl_return_m7s_implementation.md`. Approval: `docs/rl_gcsl_return_m7s_gate_approval.json` (user, 2026-09-28).
Evidence (Git-ignored): `runs/m7s/gate/` — `_gate/state.json`, `_gate/analysis.json`, `_gate/launch/` (logs, memory
samples, preflight, extraction), per-seed `s{0,1,2}/` (init.pt, goal_set / schedule / eval_plan, R_final.pt,
R_train_chunks.json, every episode's artifact and goal sidecar, `_replays/`).

## 1. Run identity and procedure

- Parent `48ea181` (M7r/M7s files uncommitted), submodules unchanged, executable `30a3913b…`, M7n v3 environment
  (`rl/configs/m7n/m7n_s0_v3.toml` `7570cd73…`, unchanged since `88f6e79`): 5 workers + 1 standby each, no-render +
  Raphnet bypass, spatial + entity diagnostics, reward v2 (recorded only), horizon 3,600.
- Approval template reviewed against the implementation record before the record was saved: rule
  `m7s1_return_rule_v2` `bea670ce…`, goal-blind TV 0.01, goal contract `22b0919e…`, policy contract `2b2c5c36…`,
  m7s file hashes `5fcd33f9` / `337e5c82` / `2132b133` / `06cfd0df` / `fbcc402d` / `4bff49b4` / `f00ab169`, P1
  registration (27,521 + 1,548), clear replays 2 per seed, total cap **3,108,269**. `approval_status` = approved.
- Preflight (2026-09-29T03:46:06Z): unit 24 / 24, rule self-test, P1 goal-on expectation, D: base + M7r increment
  PASS covering 382,522 files with 0 uncovered, no game process, executable present, approved → no problem.
- The gate was launched once (detached, 03:48:25Z). It repeated its own preflight, then ran P1, then seeds 0, 1 and 2,
  and finished at 04:31:16Z (**42 min 51 s**). It was not retried, extended or tuned. Stderr was empty. No BattleShip
  process was left.
- Only normal tick-0 starts: all 959 preserved episodes of the gate report `cold_start` (84 = the first reset of each
  worker in each phase, plus P1) or `standby_promoted` (875). There was no `cold_fallback`. Training material was only
  each seed's own phase-A and R phase-B episodes. Native controller words are the replay truth. No RNG was inspected.
  The P1 trace (an M7e policy episode) was validation only.

## 2. P1 live identity (before any training): PASS, 29,069 ticks, 56.6 s

- **Null goal**: the 8 pinned Track 1 artifacts reproduced word for word through the goal worker stack, each with its
  goal sidecar: 3,361 + 2,560 + 6 × 3,600 = **27,521** ticks.
- **Goal-on**: trace `fx_m7e_s2_best6`, goal `17,8,2`, 2 repetitions, **1,548** ticks, 6.7 s.

  | repetition | start | words sent (native `consumed_tick`) | first valid reach | end | v3 / goal-vector mismatches | tracker | parked process |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | 0 | `cold_start` | 774 (0–773) | tick 774 (returned `input_tick` 774) | truncated, `goal_reached` | 0 / 0 | horizon, 774 steps, digest `8821b2ad…`, preserved | alive after truncation; retired `terminated` |
  | 1 | `standby_promoted` | 774 (0–773) | tick 774 | truncated, `goal_reached` | 0 / 0 | same digest | alive; closed `terminated` |

  Termination: 0 worker processes after close, standby thread joined (`no_standby`), no cleanup failure, no BattleShip
  process on the machine.

## 3. Native ticks (ledger vs caps)

| phase | ticks | cap |
| --- | ---: | ---: |
| P1 identity | 29,069 | 29,069 |
| phase A (3 × 20 episodes; falls end early) | 186,905 | 216,000 |
| phase B (R and U, 3 seeds) | 2,150,400 | 2,150,400 |
| evaluation (3 × 2 × 30 episodes; end at the first valid reach) | 545,395 | 648,000 |
| exact return replays (6) | 11,051 | 43,200 |
| exact clear replays | 0 | 21,600 |
| **total** | **2,922,820** | **3,108,269** |

No phase went over its cap (`ledger_over_budget` = {}). R's phase B: 70 chunks, 7,000 gradient steps per seed, as
registered. U's parameters were unchanged through phase B and evaluation (re-checked by digest, no problem).

## 4. Per-seed rule inputs

| seed | rare returns R / U | T | p (sign flip) | R distinct rare goals | mid R / U (of 10) | T_mid | D (rare goals with ≥ 2 own demos) | functional | goal-blind | seed result |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | --- | --- | --- |
| 0 | 3 / 1 | 2 | 0.3125 | 3 | 3 / 2 | 1 | 10 | no | yes | inconclusive: not functional; T = 2 in the gap |
| 1 | 0 / 0 | 0 | 1.0 | 0 | 5 / 5 | 0 | 9 | no | yes | inconclusive: not functional |
| 2 | 1 / 2 | −1 | 1.0 | 1 | 5 / 2 | 3 | 9 | no | yes | inconclusive: not functional (5 < 7 mid returns) |

Across seeds: R had 4 rare returns against U's 3 (60 episodes per arm), and 13 mid returns against U's 9 (30 per arm).
`counts`: rare_pass [], reject [], goal_blind [0, 1, 2], goal_blind_blocked_pass [] (the safeguard blocked nothing,
because no seed met the rare criteria).

## 5. Per-goal outcomes (evaluation, 2 episodes per goal and arm, identical plan and sampling seeds)

"return @t" = `goal_reached` at tick t (the first valid reach); "horizon @3600" = native horizon without a reach;
"fall @t" = fatal fall. "R own phase-B demos" = R's phase-B episodes that validly reached the cell (rare goals only);
"U phase-B visit rate" = the fraction of U's phase-B episodes (117–118 per seed) that validly reached it (reported
only).

#### Seed 0 (goal set `b553eeb6…`, archive 213 cells, candidates rare 40 / mid 72)

| stratum | goal cell | phase-A n (witness first reach) | R episodes | U episodes | r − u | R own phase-B demos | U phase-B visit rate |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| rare | `13,14,-1` | 2 (584, 792) | horizon @3600, **return @1161** | horizon @3600, horizon @3600 | +1 | 13 | 0.119 |
| rare | `17,16,-1` | 2 (2746, 1091) | horizon @3600, horizon @3600 | horizon @3600, horizon @3600 | +0 | 16 | 0.110 |
| rare | `9,13,-1` | 1 (515) | fall @411, horizon @3600 | fall @411, fall @1871 | +0 | 20 | 0.127 |
| rare | `19,18,-1` | 1 (2230) | **return @1649**, fall @1122 | horizon @3600, horizon @3600 | +1 | 8 | 0.034 |
| rare | `16,16,-1` | 1 (1100) | horizon @3600, horizon @3600 | horizon @3600, **return @3199** | -1 | 19 | 0.068 |
| rare | `19,16,-1` | 2 (2223, 489) | fall @3380, horizon @3600 | horizon @3600, horizon @3600 | +0 | 16 | 0.152 |
| rare | `13,15,-1` | 2 (2284, 3528) | horizon @3600, horizon @3600 | fall @2364, horizon @3600 | +0 | 16 | 0.085 |
| rare | `20,17,-1` | 2 (1162, 3547) | fall @3154, horizon @3600 | fall @1395, horizon @3600 | +0 | 11 | 0.127 |
| rare | `14,15,-1` | 2 (2257, 658) | horizon @3600, **return @1714** | horizon @3600, fall @3313 | +1 | 10 | 0.059 |
| rare | `11,16,-1` | 2 (2376, 3539) | fall @2544, horizon @3600 | horizon @3600, horizon @3600 | +0 | 3 | 0.025 |
| mid | `14,14,-1` | 3 (565, 775, 657) | horizon @3600, **return @2552** | horizon @3600, **return @1294** | +0 | – | 0.076 |
| mid | `19,13,-1` | 9 (1558, 2178, 769, 1990, 1182, 1535, 3377, 2727, 2351) | horizon @3600, fall @3029 | horizon @3600, **return @2362** | -1 | – | 0.331 |
| mid | `18,13,-1` | 6 (3142, 3577, 375, 977, 527, 2339) | horizon @3600, horizon @3600 | horizon @3600, horizon @3600 | +0 | – | 0.271 |
| mid | `17,13,-1` | 8 (457, 2768, 354, 1117, 2527, 530, 760, 1926) | horizon @3600, horizon @3600 | horizon @3600, horizon @3600 | +0 | – | 0.288 |
| mid | `14,13,-1` | 4 (2348, 564, 783, 3509) | **return @499**, **return @825** | fall @3290, horizon @3600 | +2 | – | 0.229 |

#### Seed 1 (goal set `61ad9520…`, archive 214 cells, candidates rare 56 / mid 63)

| stratum | goal cell | phase-A n (witness first reach) | R episodes | U episodes | r − u | R own phase-B demos | U phase-B visit rate |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| rare | `23,5,-1` | 1 (3078) | horizon @3600, horizon @3600 | fall @838, horizon @3600 | +0 | 0 | 0.017 |
| rare | `22,17,-1` | 1 (1366) | horizon @3600, horizon @3600 | horizon @3600, horizon @3600 | +0 | 12 | 0.043 |
| rare | `18,17,-1` | 1 (2908) | horizon @3600, horizon @3600 | horizon @3600, horizon @3600 | +0 | 12 | 0.026 |
| rare | `7,12,-1` | 2 (1119, 3476) | horizon @3600, horizon @3600 | horizon @3600, horizon @3600 | +0 | 33 | 0.325 |
| rare | `10,14,-1` | 1 (1091) | horizon @3600, horizon @3600 | fall @2112, horizon @3600 | +0 | 5 | 0.094 |
| rare | `23,1,-1` | 1 (3092) | horizon @3600, horizon @3600 | horizon @3600, fall @2811 | +0 | 2 | 0.017 |
| rare | `14,14,-1` | 1 (3028) | horizon @3600, horizon @3600 | horizon @3600, horizon @3600 | +0 | 12 | 0.103 |
| rare | `18,19,-1` | 1 (2859) | horizon @3600, horizon @3600 | horizon @3600, horizon @3600 | +0 | 3 | 0.017 |
| rare | `21,17,-1` | 1 (2110) | horizon @3600, horizon @3600 | fall @2115, fall @1158 | +0 | 10 | 0.094 |
| rare | `9,15,-1` | 2 (850, 1060) | fall @1743, horizon @3600 | fall @508, horizon @3600 | +0 | 3 | 0.034 |
| mid | `20,13,-1` | 7 (1746, 2051, 3179, 1632, 2271, 1315, 3452) | horizon @3600, **return @2480** | horizon @3600, **return @1922** | +0 | – | 0.453 |
| mid | `20,14,-1` | 7 (2935, 2087, 2067, 2758, 987, 1319, 3445) | horizon @3600, fall @3486 | horizon @3600, **return @2647** | -1 | – | 0.239 |
| mid | `19,7,-1` | 6 (848, 3535, 130, 1308, 2323, 2685) | **return @2467**, **return @665** | **return @1297**, fall @2944 | +1 | – | 0.342 |
| mid | `23,12,1` | 3 (2222, 479, 3532) | fall @985, horizon @3600 | horizon @3600, **return @1149** | -1 | – | 0.265 |
| mid | `7,11,-1` | 9 (1130, 390, 178, 1082, 882, 466, 3493, 569, 1038) | **return @3005**, **return @1882** | horizon @3600, **return @938** | +1 | – | 0.530 |

#### Seed 2 (goal set `be6b2155…`, archive 223 cells, candidates rare 60 / mid 74)

| stratum | goal cell | phase-A n (witness first reach) | R episodes | U episodes | r − u | R own phase-B demos | U phase-B visit rate |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| rare | `10,13,-1` | 2 (1481, 498) | fall @3539, **return @1162** | horizon @3600, **return @1234** | +0 | 23 | 0.119 |
| rare | `21,7,-1` | 1 (2866) | horizon @3600, horizon @3600 | horizon @3600, fall @2430 | +0 | 0 | 0.009 |
| rare | `12,17,-1` | 1 (603) | horizon @3600, horizon @3600 | fall @1393, horizon @3600 | +0 | 5 | 0.017 |
| rare | `12,14,-1` | 2 (617, 99) | fall @1311, horizon @3600 | horizon @3600, **return @2093** | -1 | 12 | 0.093 |
| rare | `23,16,-1` | 2 (1838, 1220) | horizon @3600, fall @3528 | horizon @3600, horizon @3600 | +0 | 16 | 0.152 |
| rare | `23,13,-1` | 2 (707, 2725) | horizon @3600, fall @2749 | horizon @3600, fall @2997 | +0 | 24 | 0.186 |
| rare | `13,16,-1` | 2 (1091, 3459) | horizon @3600, fall @2912 | horizon @3600, horizon @3600 | +0 | 11 | 0.051 |
| rare | `21,19,-1` | 1 (1259) | fall @2021, horizon @3600 | horizon @3600, horizon @3600 | +0 | 2 | 0.017 |
| rare | `19,17,-1` | 1 (533) | horizon @3600, horizon @3600 | fall @2207, horizon @3600 | +0 | 4 | 0.059 |
| rare | `22,18,-1` | 1 (1248) | horizon @3600, horizon @3600 | horizon @3600, horizon @3600 | +0 | 8 | 0.102 |
| mid | `17,14,-1` | 8 (2421, 2810, 2091, 2280, 1261, 563, 2386, 3022) | horizon @3600, fall @3586 | horizon @3600, horizon @3600 | +0 | – | 0.263 |
| mid | `12,11,-1` | 9 (3329, 1472, 1850, 1100, 29, 2901, 126, 264, 3262) | fall @2089, **return @3285** | fall @2669, **return @3285** | +0 | – | 0.466 |
| mid | `8,9,-1` | 8 (117, 2625, 1693, 276, 1054, 751, 2329, 292) | **return @870**, **return @2592** | horizon @3600, **return @152** | +1 | – | 0.585 |
| mid | `15,14,-1` | 3 (1032, 3563, 2782) | **return @1834**, horizon @3600 | horizon @3600, fall @1853 | +1 | – | 0.220 |
| mid | `21,12,1` | 7 (573, 512, 2655, 451, 314, 2500, 1793) | horizon @3600, **return @913** | horizon @3600, horizon @3600 | +1 | – | 0.441 |

Provenance: every E goal of each seed was reached by that seed's own phase-A episodes in the registered band (the
gate's `check_provenance` raised no problem). Every witness is one of that seed's 20 phase-A episodes, and its artifact
is preserved under `runs/m7s/gate/s{seed}/phase_a/`. Frozen digests:

| seed | init parameters | goal set | schedule | phase-A ticks |
| --- | --- | --- | --- | ---: |
| 0 | `30ef2006…` | `b553eeb6…` | `d1c4d18a…` | 65,721 |
| 1 | `5d1ecd2d…` | `61ad9520…` | `ed2cccf2…` | 57,873 |
| 2 | `e858fbae…` | `be6b2155…` | `4ca8f3b6…` | 63,311 |

All E goals are airborne cells except the mid `23,12,1` (seed 1) and `21,12,1` (seed 2) on floor line 1. Two rare goals
never appeared in R's own phase-B data (`23,5,-1` in seed 1 and `21,7,-1` in seed 2).

## 6. Goal-swap sensitivity after training (R_final vs U = initial parameters; same 4,000 states from R's own episodes)

| seed | R action TV (goal swap) | U action TV | R / U | `goal_blind_flag` | R goal / state sensitivity | U goal / state | R trunk sat95 | U trunk sat95 | R goal share of joint pre-activation |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 0 | 0.002985 | 0.000231 | 12.9 | true | 0.164 | 0.242 | 0.439 | 0.184 | 0.269 |
| 1 | 0.006263 | 0.000501 | 12.5 | true | 0.359 | 0.471 | 0.402 | 0.104 | 0.253 |
| 2 | 0.005124 | 0.000366 | 14.0 | true | 0.366 | 0.417 | 0.464 | 0.100 | 0.355 |

R's goal dependence is measurable (12–14 × U) but small, and below the registered 0.01 in every seed. The goal branch
never saturated (0.0). Trunk saturation grew from about 0.10–0.18 to 0.40–0.46.

**Training trajectory** (`R_train_chunks.json`, reported only). The cross-entropy of both heads stayed at the
uniform-policy value throughout. ln 9 + ln 8 = 4.2767; the last chunk gave 4.2744 / 4.2741 / 4.2753 (chunk 1 of seed 0:
4.2766). Stick accuracy ended at 0.121 / 0.118 / 0.120 (uniform 0.111) and button accuracy at 0.135 / 0.134 / 0.128
(uniform 0.125). The per-chunk goal-shuffle TV rose from about 0.002 to about 0.006 within 10 chunks and then stayed
flat. The mean relabelled h was 600–700 ticks.

## 7. Exact replays

Registered design: the first two rare returns per arm and seed are re-tested (mid returns are not replayed). All six
performed replays were **exact**. Each replay had an equal native action digest, per-tick cells equal to the sidecar,
no consumed-tick mismatch, no unsent word, and the goal first validly occupied on the recorded reach tick, which was
the last tick:

| seed | arm | episode | goal | recorded reach | replayed first reach | result |
| --- | --- | --- | --- | ---: | ---: | --- |
| 0 | R | `…7d7aac2f` | `14,15,-1` | 1,714 | 1,714 | exact |
| 0 | R | `…a4487a53` | `19,18,-1` | 1,649 | 1,649 | exact |
| 0 | U | `…48d96011` | `16,16,-1` | 3,199 | 3,199 | exact |
| 2 | R | `…7dc48dd0` | `10,13,-1` | 1,162 | 1,162 | exact |
| 2 | U | `…98f4b626` | `10,13,-1` | 1,234 | 1,234 | exact |
| 2 | U | `…915a7bbb` | `12,14,-1` | 2,093 | 2,093 | exact |

Seed 0 R's third rare return (`13,14,-1` @1161) is beyond the registered two per arm, so it was not replayed. It
counts in the rule as registered. Seed 1 had no rare return.

**Clears: none** in any phase. There were 0 candidates, 0 replays and 0 claimed; no clear on a goal-reach tick.

## 8. Reported diagnostics (never deciding)

- **Collection reaches** (commanded schedule goals reached in phase B, R / U): seed 0 42 of 161 / 44 of 162; seed 1
  33 / 155 vs 32 / 149; seed 2 31 / 146 vs 30 / 148. `survival_120` was True for every uncensored reach (0 False). R and
  U reached commanded goals at the same rate while collecting.
- **R vs U evaluation paths**: none of the 90 paired evaluation episodes has the same word sequence. With common random
  numbers the first differing word falls at a median consumed tick of about 8 (maximum 54), so R's small policy change
  shows up in behaviour immediately. It does not change reach rates. Seed 2's two returns to `12,11,-1` at tick 3,285
  come from different episodes.
- **Chance level of "rare" goals**: over U's ~118 phase-B episodes, the rare goals were visited by 0.9–32.5 % of
  episodes (median 7.6 %), broadly consistent with F10's held-out chance rate (0.055 pooled, p90 0.125); the outlier is seed 1's `7,12,-1` at 32.5 %.

## 9. Wall time and memory

| seed | phase A | R phase B (incl. 7,000 GCSL steps) | U phase B | R eval | U eval |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0 | 53.4 s | 340.3 s | 260.9 s | 72.3 s | 76.5 s |
| 1 | 49.8 s | 342.4 s | 268.4 s | 75.3 s | 68.8 s |
| 2 | 53.0 s | 336.8 s | 258.7 s | 71.7 s | 73.2 s |

Throughput: R's phase B ran at about 1,055 native ticks/s including training, and U's at about 1,364 ticks/s. Total
42 min 51 s.

Memory (read-only WMI sampler every 15 s, 170 samples; peaks between samples can be missed): main process private
peak **1,579 MB** (working set 1,345 MB); the whole gate process tree (6 Python + 10 BattleShip processes) private
peak **6,210 MB** (working set 2,636 MB); system free RAM never below 5,331 MB and free commit never below 10,440 MB
(15.9 GB RAM, 31.4 GB commit limit).

## 10. Evidence preservation

- New increment `D:\BattleShip_runs_backup\2026-09-29_incr_m7s` (source `runs\m7s\`, including `_gate/launch/`):
  9,103 files, 299,893,889 bytes, copied and re-hashed on D: → **PASS**, 0 mismatches (manifest `c58610f2…`,
  `verification.json` `aef58a34…`). 1,049 runtime junctions were excluded as before.
- Base + M7r + M7s increments now cover **391,625** regular files under `runs/`, **0 uncovered**. This was checked
  read-only; the base and M7r records were not touched, and no combined record was written.

## 11. Interpretation (not part of the registered decision)

At 358,400 own ticks and 7,000 GCSL steps per seed, the learner moved only slightly away from its untrained policy.
Its action predictions stayed at uniform entropy, its goal dependence stayed under the registered goal-blind threshold,
and it did not return to mid goals reliably (3–5 of 10, where 7 are required). The rare-goal differences (T = 2, 0, −1)
are within the noise the rule anticipates. The likely mechanism is the one design section 3 used to argue against PPO.
The own data comes from a near-uniform per-tick policy, and relabelled goals lie a mean 600–700 ticks ahead. So the
action at one tick carries almost no information about which cell is reached hundreds of ticks later, and GCSL's
first iteration has almost nothing to fit. The iterated improvement that GCSL relies on never started, because R
collected data at the same rate as U. This is an interpretation of the diagnostics, not a tested claim.

What the gate does not establish: it does not reject goal-conditioned return (outcome 3, not 2). It says nothing about
H2, crossings or targets. It does not change the selected baseline (observation v3 + reward v2 PPO).

## 12. Recommendation (a separately authorised next step; nothing has been started)

1. **Do not extend or rerun `m7s1`**. The rule forbids extension, and the loss curve has no trend that a larger budget
   would plausibly change.
2. **Next, if authorised: a zero-native-tick offline diagnostic on the preserved M7s evidence.** It would measure how much
   goal-conditional action information the own data actually contains. From the 9,103 artifacts and goal sidecars
   (native words + per-tick cells, no replay needed), estimate the achievable reduction in action cross-entropy given
   (current cell, goal cell, h) against the marginal:
   - per tick, as a function of h;
   - for temporally extended segments (k consecutive identical words, or the recorded k-tick action sequence).

   If per-tick information is near zero at the h that rare goals need, and extended segments carry it, any further
   GCSL work needs a segment-level action / decision contract. That would be a new, separately pre-registered design,
   related to the M7r commitment contract and the hold-k probe. If neither carries information, goal-conditioned
   supervised return from random own data is not a promising lever at this scale, and the next direction should be
   chosen from the recorded open questions instead.
3. Any later native run should add the new M7s increment to the gate's coverage list (`BACKUP_INCREMENTS`), which is a
   code change for that milestone.
