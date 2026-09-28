# M7p geometry-scaling comparison (geo4 vs v3): registered three-seed result

Authorised 2026-09-28 by the user after the passed geo4 diagnostic; run 2026-09-28 03:04 -> 08:25 UTC by
`python rl/m7p_campaign.py all` (5 h 21 min) without a stop; the frozen rule was applied once. Nothing was committed,
pushed or branched. Native RNG state was never inspected. **Decision: `failure_regression` (gate 3). geo4 is recorded as
worse at this budget; `btt_policy_obs_v3_entities` (v3) stays the selected observation.**

Records: manifest [`rl_geometry_scale_m7p_manifest.json`](rl_geometry_scale_m7p_manifest.json) (frozen copy
`runs/m7p/campaign/_matrix/manifest.json`, code `c61d947b…`, control-check fingerprint `5e73a04c…`, rule `b6c58d82…`,
executable `748dbad9…`); rule [`rl_geometry_scale_m7p_decision_rule.json`](rl_geometry_scale_m7p_decision_rule.json);
decision and inputs `runs/m7p/campaign/_matrix/analysis_n3.json`; state `runs/m7p/campaign/_matrix/state.json`;
measurements `runs/m7p/campaign/_matrix/measurements.json`; control records `runs/m7p/campaign/_control/`; log
`runs/m7p/campaign_all.log`; handoff [`rl_geometry_scale_m7p_handoff.md`](rl_geometry_scale_m7p_handoff.md).

## 1. What was compared

| | experimental arm | control arm |
| --- | --- | --- |
| runs | `m7p_geo4_s{0,1,2}` (`runs/m7p/campaign`), fresh models | `m7n_s{0,1,2}_v3` (frozen M7n runs, `runs/m7n/campaign`) |
| observation | `btt_policy_obs_v3_geo4` (digest `2b984528…`): v3 with only the `segment_geometry` block scaled by 1/4 (lengths / 8,000, velocities / 200) | `btt_policy_obs_v3_entities` (digest `4ddc2933…`) |
| everything else | identical: reward v2, Track 1, tanh [64, 64] network, `norm_obs` off, PPO settings, N = 5 standby, 3,072,000 transitions, tick-0 starts, checkpoints every 102,400; profiles differ from the M7n profiles in `contracts.observation`, `run.name`, `run.notes`, `run.output_root` only; compatibility views differ in `contracts.observation` only | |
| initialisation | `ckpt_000000000` equals the fresh construction and the M7n initial set of the seed (same seed, shapes and architecture) in all three seeds; nothing imported from the geo4 diagnostic | |
| evaluation | the M7n protocol post hoc: initial + 9 curve points + final; 100 + 100 at initial and final, 60 + 5 at curve points; seed 12345; frozen parameters; each checkpoint under its own contract; `btt_eval_metrics_v1`; 985 episodes per run | the frozen M7n labels |

### Pre-launch gates (all passed)

- Rule frozen before launch (`m7p_decision_rule_v1`, self-test 40 cases PASS): M7n's corrected clear / crossing semantics
  (`btt_qualified_crossing_v1`, native-verified clears), the paired target thresholds (+1/2 in every seed selects,
  -1/2 in at least two seeds is regression), outcomes invalid / incomplete / success_discovery / failure_regression /
  success_better_targets / failure_no_learning / inconclusive, denominators, ties, precedence (discovery before
  regression; regression before better-targets), and the explicit statement that lower saturation never selects.
- Control compatibility on the final code: **re-executed** = three fresh 102,400-transition runs of the M7n profiles
  (policy and VecNormalize digests at 0 and 102,400 equal to the M7n sets; 28 / 29 / 26 episode rows equal), the
  evaluation verifiers over every M7n final and initial label (counts, frozen parameters, tick-0 starts, metrics,
  artifacts), `verify_training_run` over the three control runs, clear and crossing candidate re-enumeration (0 and 0),
  every rule input recomputed and equal to the recorded M7n analysis (T 138/25, 553/100, 559/100; X 0, 0, 0);
  **validated from records** = the episodes and artifacts themselves (hashed) and the M7n clear / crossing documents
  (no candidates, so nothing to replay). No replacement control was trained.
- The M7n `unit_matrix` 10/11: the failing assertion is the case's pre-launch precondition that the M7n campaign
  directories do not exist. Re-run with the M7n campaign root redirected to a fresh empty directory, every assertion of
  the case passes; on the default root every assertion passes except that precondition (the campaign's own nine
  directories exist). No genuine failure remains. Other suites after the code edits: `m7o_tests unit` 7 / 7,
  `m7g_k_tests unit` 6 / 6.
- Fixed offline sample pinned in the manifest (sha256 `6dd9dbed…`: the two M7n final traces and eight action-hold k = 1
  episodes, 33,997 states) with the measurement procedure of the diagnostic at the eleven registered checkpoints.
- Preflight: 0 blocking problems; launch gate 17.5 GiB commit / 6.4 GiB physical / 117 GiB disk.

## 2. Run

Training 48.2 / 48.8 / 48.8 min at 1,065 / 1,051 / 1,052 transitions per second, 859 / 886 / 863 training episodes,
21 / 76 / 30 falls, 0 native clears, at most 10 game processes, 0 hard or soft alerts, leak-free; every run verified
(fresh start, identity, geo4 contract and digest in `run.json` and every checkpoint set, rows). Evaluation 33 / 33 labels
verified (2,955 / 2,955 episodes, census complete; every artifact starts at consumed tick 0). Clear verification: 0
candidates in every label and in training. Crossing verification on the finals: seed 0 and seed 2 0 candidates; seed 1
**2 candidates, both replayed exactly** (section 4). Control crossing inputs equal the control verification record.
Integrity problems: none. Exit 0.

## 3. Paired result (final stochastic 100 episodes per seed; deterministic 100 reported)

| seed | arm | targets mean T | D = T geo4 - T v3 | native clears K | X (qualified crossing or left break) | left entries | left-target episodes | target-2 breaks | L / R | seven-right | falls | deterministic targets / collapse share |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | v3 | 5.52 | | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 0 | 0 | 4 / 0.02 |
| 0 | geo4 | 4.91 | **-0.61** | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 0 | 0 | 1 / 0.04 |
| 1 | v3 | 5.53 | | 0 | 0 | 0 | 0 | 7 | 4 / 1 | 3 | 13 | 1 / 0.02 |
| 1 | geo4 | 4.93 | **-0.60** | 0 | **1** | 2 | 1 | 0 | 0 / 0 | 0 | 2 | 1 / 0.71 (collapsed) |
| 2 | v3 | 5.59 | | 0 | 0 | 0 | 0 | 1 | 1 / 1 | 1 | 1 | 0 / 0.99 (collapsed) |
| 2 | geo4 | 4.98 | **-0.61** | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 0 | 1 | 3 / 0.08 |

G (geo4 final minus its own initial): +1.73 / +1.73 / +1.85, so geo4 learned from scratch in every seed. Pooled over
300 final episodes: target 2 broken v3 8 vs geo4 0; L 5 vs 0; R 2 vs 0; seven-right episodes 4 vs 0.

Curves (stochastic mean targets, 60-episode labels, 100 at initial and final):

| transitions | 0 | 307,200 | 614,400 | 921,600 | 1,228,800 | 1,536,000 | 1,843,200 | 2,150,400 | 2,457,600 | 2,764,800 | final |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s0 v3 | 3.30 | 3.57 | 3.83 | 4.27 | 4.37 | 4.32 | 4.53 | 4.93 | 4.98 | 5.28 | 5.52 |
| s0 geo4 | 3.18 | 3.88 | 3.95 | 4.57 | 4.77 | 4.85 | 4.75 | 4.75 | 4.95 | 4.87 | 4.91 |
| s1 v3 | 3.33 | 3.57 | 4.10 | 4.28 | 4.12 | 4.78 | 5.05 | 4.95 | 5.28 | 5.23 | 5.53 |
| s1 geo4 | 3.20 | 3.85 | 4.03 | 3.95 | 4.48 | 4.93 | 4.42 | 4.72 | 4.80 | 4.83 | 4.93 |
| s2 v3 | 3.27 | 3.25 | 3.40 | 3.48 | 3.95 | 4.50 | 4.67 | 4.98 | 5.25 | 5.07 | 5.59 |
| s2 geo4 | 3.13 | 3.83 | 3.98 | 3.75 | 4.13 | 4.23 | 4.22 | 4.42 | 4.63 | 4.80 | 4.98 |

geo4 leads in every seed through about 1.2-1.5 M transitions (the diagnostic's 307,200 point included), then flattens
near 4.7-4.9 while v3 keeps rising to 5.5-5.6. The diagnostic's early lead was therefore not a gameplay improvement at
the full budget, as its report had warned.

## 4. The decision, exactly

Gate 0: no integrity problem. Incomplete: none. Gate 1 first_clear false (K = 0 everywhere). Control-clear guard not
engaged. Gate 2 ceiling_broken **false**: X[geo4] = 1 in seed 1 only, the rule requires two seeds (X[v3] = 0 in every
seed). **Gate 3 target_regression true**: D = -61/100, -3/5, -61/100, at or below -1/2 in all three seeds (two required).
Gate 4 better_targets false, gate 5 no_learning false, gate 6 false. No inapplicable gate. **Outcome
`failure_regression`; selected observation v3.** By the registered precedence a discovery gate would have preceded the
regression gate, but the discovery event occurred in one seed and gate 2 needs two.

### The seed-1 discovery event (reported, not deciding)

Final stochastic episode `episode_20260928T072129Z_44619208` of `m7p_geo4_s1` (preserved at
`runs/m7p/campaign/_eval/m7p_geo4_s1/final/stochastic/workers/w04/artifacts/…`, replay record in
`runs/m7p/campaign/_clears/m7p_geo4_s1/final/crossing_verification.json`): replayed exactly from tick 0 on a fresh process
(digest, consumed ticks, break table, first-left-entry tick all equal). Break order 0, 4, 9, 5, 7 (ticks 218-2,400), then
an `over_wall` entry at consumed tick 3001 with crossing height 3,950 (route label `lower_precision`: approach surface L1,
the raised right step), a landing on the decoded left floor L3 at tick 3141, **target 6 broken at tick 3008**, and a
native failure (fall) at tick 3444 with four targets remaining (1, 2, 3, 8). This is the first replay-verified qualified
wall crossing with a left-target break in a final tick-0 evaluation of the project (M7n's only left entry was an
unqualified fall in an intermediate label). The second seed-1 candidate (`…85c10043`) was an over-wall entry at tick
1005 without a landing: unqualified, not a crossing. The event is one episode of one seed's 100; the rule counts it as
X = 1 for that seed and nothing more. It does not make geo4 better, and it is not a clear.

## 5. Whether the saturation reduction persists (supporting diagnostic; decided nothing)

Fixed sample of 33,997 states rebuilt under each arm's own contract (population A = 6,578 policy-play states, B = 27,419
random-play states); sat95 = share of (state, unit) pairs with abs(tanh z) > 0.95; derivative = mean 1 - h^2.

| checkpoint | metric | s0 v3 -> geo4 | s1 v3 -> geo4 | s2 v3 -> geo4 |
| --- | --- | --- | --- | --- |
| 307,200 | actor L1 sat95 (all) | 0.53 -> 0.15 | 0.62 -> 0.16 | 0.57 -> 0.24 |
| 1,536,000 | actor L1 sat95 (all) | 0.77 -> 0.38 | 0.77 -> 0.34 | 0.77 -> 0.34 |
| final | actor L1 sat95 (all / A / B) | 0.77 / 0.81 / 0.77 -> 0.51 / 0.51 / 0.51 | 0.82 / 0.85 / 0.82 -> 0.46 / 0.50 / 0.45 | 0.80 / 0.83 / 0.80 -> 0.45 / 0.51 / 0.43 |
| final | critic L1 sat95 (all) | 0.77 -> 0.57 | 0.91 -> 0.73 | 0.84 -> 0.64 |
| final | actor / critic mean derivative | 0.12 / 0.14 -> 0.28 / 0.26 | 0.10 / 0.05 -> 0.31 / 0.15 | 0.11 / 0.10 -> 0.33 / 0.21 |
| final | critic units stuck at one sign | 0.59 -> 0.33 | 0.70 -> 0.48 | 0.56 -> 0.34 |
| final | break pair abs dV / KL | 0.82 / 0.055 -> 0.85 / 0.19 | 0.70 / 0.026 -> 0.71 / 0.18 | 0.77 / 0.017 -> 0.80 / 0.12 |
| final | up-B progress KL (vs its control pairs) | 2.76 (0.35) -> 4.35 (0.19) | 0.29 (0.12) -> 2.66 (0.88) | 0.99 (0.13) -> 3.05 (0.67) |
| final | ablation KL: targets block / geometry block | 0.35 / 2.62 -> 0.72 / 1.85 | 0.22 / 2.01 -> 1.22 / 1.49 | 0.24 / 2.41 -> 1.23 / 0.53 |
| final | policy entropy (nats) | 1.79 -> 1.50 | 2.24 -> 1.59 | 1.82 -> 1.72 |
| final | actor W1 norm | 18.5 -> 18.1 | 18.5 -> 18.5 | 18.7 -> 17.9 |

The reduction persists to 3,072,000 transitions in every seed and on both populations (actor 0.26-0.36 lower, critic
0.17-0.20 lower), with higher derivatives and fewer stuck critic units; the geo4 networks respond more to target rows
and less to the geometry block. Weight norms and per-interval weight-row changes are the same in both arms, which says
nothing about learning speed. **None of this changed the outcome: the less saturated networks broke fewer targets.**
Lower saturation was, as registered, a supporting diagnostic and not a success criterion, and this result shows why.

## 6. What this establishes and what it does not

Established at this budget, three seeds, tick-0 evaluation: scaling the geometry block by 1/4 lowers first-layer
saturation durably and changes which inputs the policy responds to, but ends 0.60-0.61 targets per episode below v3 in
every seed, with no moving-target breaks and no early sweeps, after leading for the first 1.2-1.5 M transitions. geo4 is
not selected; v3 stays the default; no extension, retune or extra seed follows from this rule. The one qualified crossing
of seed 1 is a genuine, replay-verified event in the project's own policy play and is preserved; it is one episode in one
seed and does not qualify geo4 under the registered rule. Not established: why the early lead reverses (the measurements
show the representation difference, not its consequence), whether other factors or budgets would behave differently, and
anything about crossings from a single episode.
