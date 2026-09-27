# M7n results addendum: the seven-right-target sweeps of the final tick-0 evaluations

Written 2026-09-27 after the recorded n = 3 decision (gate 3 `better_targets`, success, v3 selected;
`runs/m7n/campaign/_matrix/analysis_n3.json`). This addendum is diagnostic only: it re-decides nothing, changes no
threshold, and leaves the frozen M7n code, manifest, rule v2 and results untouched (the tool lives in
`rl/tools/m7n_sweeps_addendum.py`, outside the fingerprinted set; `manifest_drift` still reports none). No training, no new
policy evaluation. Native RNG state was not inspected; the crossing fixtures and the TAS were not used.

Definitions reused unchanged from the registered rule (`rl/m7l_analysis.episode_facts`, rule v2 parameters): right
targets = {0, 2, 3, 4, 5, 7, 9}; sweep tick = the largest first-break tick over the seven; **L** = target 2 broken by
consumed tick ≤ 2699 with ≥ 5 static right targets broken in the episode; **R** = all seven right targets broken by
consumed tick ≤ 2699; remaining actions = 3600 − (sweep consumed_tick + 1). Final stochastic labels only (100 tick-0
episodes per seed per arm); intermediate checkpoints and training are kept separate (section 4).

## 1. The four sweep episodes (existing records: `runs/m7n/addendum/sweeps/records.json`)

All four are v3; the reproduced v1 control has none. Artifacts are the preserved evaluation artifacts
(`runs/m7n/campaign/_eval/m7n_s{seed}_v3/final/stochastic/workers/w*/artifacts/<episode_id>/`, listed with their
worker in the registry `docs/rl_observation_v3_m7n_sweeps_addendum_replays.json`).

| seed | episode | break order (target@consumed tick) | target 2 | sweep tick | remaining | L | R | end |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `episode_20260927T032209Z_907d762b` | 0@73 4@74 5@85 9@414 7@708 3@1229 2@1678 | 1678 | 1678 | 1921 | yes | yes | fall at 2975 |
| 1 | `episode_20260927T032502Z_8857b614` | 0@34 4@150 9@185 5@338 3@1026 2@1171 7@3392 | 1171 | 3392 | 207 | yes | no | horizon |
| 1 | `episode_20260927T032723Z_b3c4696a` | 9@229 0@446 3@697 5@1569 7@1578 4@1753 2@3011 | 3011 | 3011 | 588 | no | no | horizon |
| 2 | `episode_20260927T042929Z_e404fde0` | 0@205 4@390 5@681 7@698 9@892 3@1358 2@1692 | 1692 | 1692 | 1907 | yes | yes | horizon |

Existing records also establish: no left-region entry and no left target in any of the four (or in any final episode
of either arm); minimum live x −1468 / −948 / −1008 / −1120. They do **not** contain heights or motion, so post-sweep
behaviour needed replays (section 3).

## 2. L / R counts, final 100 stochastic tick-0 episodes per seed

| arm | seed 0 | seed 1 | seed 2 | pooled / 300 |
| --- | --- | --- | --- | --- |
| v1 L | 0 | 0 | 1 | **1** |
| v1 R | 0 | 0 | 0 | **0** |
| v3 L | 0 | 4 | 1 | **5** |
| v3 R | 0 | 1 | 1 | **2** |

Seven-right episodes: v1 0 / 300, v3 4 / 300 (seed 1: 3, seed 2: 1). Target 2 broken: v1 3 / 300, v3 8 / 300. These
equal the quantities in the recorded decision.

## 3. Post-sweep behaviour (registered exact replays, `runs/m7n/addendum/sweeps/replays/*/result.json`)

Registry `docs/rl_observation_v3_m7n_sweeps_addendum_replays.json` (fixed before replaying: the four episodes, their
digests, artifacts, recorded break tables, the arm's evaluation flags, executable `748dbad9…`). Each replay: a fresh
process from tick 0, the source `actions.jsonl` copied beside the replay, read-only diagnostics on, native trajectory
only. **All four exact** (no consumed-tick mismatch, every action consumed, digest equal, break table equal, no left
entry as recorded). Wall geometry from the decoded stage: right face of the tall wall x = −1800, ledge x −2100..−1200,
wall top y = 3000, left region x < −2100.

| episode | position at the sweep | after the sweep | closest to the wall face | highest | ≥ wall-top height | ledge / left region | end |
| --- | --- | --- | --- | --- | --- | --- | --- |
| s1 `907d762b` (1921 left) | (3145, 2119), airborne on the right | 1297 steps: back down to the right step L1 (239 grounded ticks), two excursions across x = 0 (183 steps left of centre, none past x −1200), then back right | x −727 at y −334 (tick 2090), 1073 short of the face | y 2317 at x 3017 (tick 1689, on the right); left of centre never above y 1904 | never | never / never | **off-stage fall on the right side** at tick 2975 (x 1673, y −9659), 3 targets left |
| s1 `8857b614` (207 left) | (59, 1112) | 207 steps drifting left and down to x ≈ −500..−830 near the floor, 29 grounded ticks on L4 | x −830 at y −1098 (tick 3457), 970 short | y 1742 at x −584 (tick 3408) | never | never / never | survives to the horizon at (−570, −384) |
| s1 `b3c4696a` (588 left) | (2943, 2307) | 588 steps: down to L2 / L4, one pass left of centre at floor height (146 steps x < 0, all below y −788) | x −877 at y −1474 (tick 3453), 923 short | y 2570 at x 2802 (tick 3023, on the right) | never | never / never | survives to the horizon at (1374, −1209) |
| s2 `e404fde0` (1907 left) | (2600, 1874) | 1907 steps: lands on the moving platform and **rides it 767 grounded ticks** (riding 765, until tick 2619), jumps from its top (max y 6199 at x 2756, tick 1977), is at or above wall-top height for **474 steps** between ticks 1830 and 2713 with x between −311 and 3234, reaches y 3916 at x −245 (tick 2692), then descends to the main floor and stays right | x −1120 at y −1403 (tick 3388, low); the high pass ends at x −311, 1489 short of the face | y 6199 (right side); y 3916 left of centre | 474 steps, all at x > −311 | never / never | survives to the horizon at (1753, −157) |

None of the four approached within 600 world units of the wall face at any height, touched the ledge, or entered the
left region. The one fall (`907d762b`) happened on the right side of the stage 1,297 steps after the sweep; it was not
a crossing attempt. `e404fde0` is the only episode that reached wall-top height with time left; it did so above the
moving platform and drifted left only to x ≈ −250..−310 before descending.

## 4. Kept separate: intermediate checkpoints and training

Not part of the sweep table above. The only left-region entry of the whole campaign occurred in an intermediate
60-episode curve label (v3 seed 2 at 1,536,000 transitions, episode `…c350b44b`): sweep not complete (5 targets),
grounded takeoff from the right step at tick 1738, path over the ledge, `over_wall` entry at y 3000 on tick 2391,
route label `lower_precision`, no landing, native failure at tick 2742 (implementation report, section 10.2). Under the
registered criterion it is an unqualified entry, not a crossing. Training episodes carry no target or position
diagnostics; their tracker facts (860 / 888 / 860 episodes, 24 / 85 / 23 falls, no clear) say nothing about sweeps or
crossings.

## 5. Assessment

The question was whether completing the right-side sweep early enough is still the immediate bottleneck, or whether
there are now normal-start episodes with useful time remaining that fail to transition into a crossing.

**The evidence is too sparse to choose between the two, and it shows both.** Early sweeps remain rare: R = 2 of 300
v3 final tick-0 episodes (0 of 300 for v1), L = 5 of 300 (1 of 300). At the same time, both R episodes had about 1,900
actions left, roughly ten times what either validated crossing needed from its takeoff to the left entry, and
neither showed any wall-directed behaviour: no approach within 600 units of the face, no ledge contact, no left entry;
one fell on the right side, the other reached wall-top height above the moving platform and drifted only to x ≈ −300.
Two such episodes cannot estimate a transition-failure rate, and four sweeps cannot be read as a consolidated sweep
skill (the other two sweeps finished with 207 and 588 actions left, also without approaching the wall). What can be
said: the policies that now sweep have not shown a crossing to transition into, which is consistent with a tick-0
policy that has never received a left-side signal, and nothing here makes the right-first route mandatory for a clear.
