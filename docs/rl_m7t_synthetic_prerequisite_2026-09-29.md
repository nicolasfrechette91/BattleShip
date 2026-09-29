# M7t synthetic prerequisite: results (2026-09-29)

**Registered outcome: FAIL.** S1, S2, S3 and S4 fail; S5 and S6 pass. The prerequisite in §7 of
`docs/rl_learning_strategy_review_2026-09-29.md` (revision 2) is therefore not met.

- Per revision 2, the native `m7t1` gate is **not** to be proposed as designed. This is a reason to revise the proposal,
  not to run the gate anyway.
- **Scope of the authorisation:** optimizer steps on synthetic environments only. No BattleShip process was launched,
  no native tick was used, and nothing was committed or pushed.
- **Unchanged:** existing observations, rewards and action contracts; the M7o, M7r and M7s registered outcomes; the
  selected v3 + reward v2 baseline.

Labels: **[R]** registered result (pinned before training and applied once); **[P]** post-hoc diagnostic (descriptive,
never deciding); **[F]** fact about the paper, the code or this harness.

## 1. QRL checked against the paper and the reference code [F]

Sources:
- The paper: arXiv 2304.01203 v7, read through its ar5iv rendering.
- The official code: `quasimetric-learning/quasimetric-rl` (`modules/quasimetric_critic/losses/{local_constraint,
  global_push,latent_dynamics,__init__}.py`, `models/{quasimetric_model,latent_dynamics}.py`, `modules/__init__.py`)
  and `quasimetric-learning/torch-quasimetric` (`torchqmet/iqe.py`, `reductions.py`), read on 2026-09-29.
- The reference code for goal-set injection was **not located**; Appendix A's text is the only source for it.

| element | paper (MountainCar, the discrete precedent) | reference code (defaults) | harness T / S (as registered) |
| --- | --- | --- | --- |
| local constraint | E[relu(d(s,s′) + r)²] ≤ ε², ε 0.25 | `relu(d − step_cost)².mean() − ε²`, ε 0.25, cost 1 | same, cost 1 per tick, ε 0.25. **Differs:** 256 cost-0 membership rows share the same mean (T and S); S's 512 main rows are (s_t → G, cost h) instead of local rows |
| Lagrange multiplier | softplus-parameterised, init 0.01, lr 0.3 | softplus of a raw parameter, init 0.01, gradient reversal, AdamW 1e-2 | softplus, init 0.01, gradient reversal, **Adam lr 0.3** (paper value) |
| global push | φ(x) = −softplus(500 − x, β 0.01) | `softplus(offset − d, β).mean()` over (zx, roll(zy)), offset 15, β 0.1 | **offset 4,000, β 0.00125** (rescaled to the horizon); 1,024 pairs: 384 (zx, roll zy) as in the code, **plus** 384 state→goal node and 256 goal node→state (sink), which are project additions |
| dynamics | residual T, weight 75, ½(d(ẑ′,z′)² + d(z′,ẑ′)²) | residual MLP (512, 512), zero-initialised last layer, `weight × mean(d_bidirectional²)`, weight 0.1 | residual MLP (256, 256), zero-initialised last layer, weight **75** (paper) |
| encoder / head | 3-1024-1024-1024-256; IQE-maxmean 16 × 32 | projector (512,) → IQE dim 2048 / 64 components | 626-256-256-256; **IQE-maxmean 16 × 16**; goal encoder 10-256-256 (project) |
| IQE maths | IQE-maxmean | `iqe()` union-of-intervals + `MaxMean` with raw α initialised at −1 | reimplemented; equal to a brute-force union + maxmean (selftest, 20 random cases) and the triangle inequality holds (200³ triples) |
| latents | — | one encoder for obs and next obs; no detach, no target network | same |
| optimiser, budget | model lr 5e-4, batch 4,096, 5 × 10⁵ steps | AdamW 1e-4 | **Adam 3e-4 (revision 2), 20,000 steps, 512 shared transitions per step** |
| goals | states; Appendix A: augment S with G, add (s′, G) when a transition ends in G (cost not stated) | goal-set code not located | cell goal nodes via a separate encoder; cost-0 membership rows; sink pairs (project variant) |
| policy | discrete MountainCar: greedy on the estimated value | continuous: actor, two critics, entropy (online), + behaviour cloning (offline maze2d) | greedy argmin over the 72 words; ties go to the lowest index |

The two budgets differ by roughly two orders of magnitude (the paper: 5 × 10⁵ steps at batch 4,096; the harness:
20,000 at 512). That gap was flagged as a risk in revision 2 and is measured here (§4.4).

## 2. Harness and reproduction [F]

- `rl/tools/m7t_synthetic_prereq.py`: standalone.
  - It imports only the unchanged `rl/m7s_goal.py` `EpisodeData` / `sample_examples`, which it uses literally for
    S's rows.
  - It does not use the M7 trainer, contracts, observations, rewards or actions.
  - It refuses to write under `runs/`.
- `rl/tools/m7t_synthetic_posthoc.py`: post-hoc diagnostics and the supplemental memory measurement (§6), written
  after the run.
- Outputs are in `logs/m7t_synth_prereq/`, which is Git-ignored (`.gitignore:111`). This covers
  `registration.json`, `world_check_*.json`, `run.log`, `results.json`, `s{0,1,2}_{init,T,S}.pt`,
  `s{seed}_{T,S}_trainlog.json`, `s{seed}_episodes.json.gz` (every episode's words and per-tick diagnostics),
  `posthoc.json` and `memory_supplement.json`.

```bash
python rl/tools/m7t_synthetic_prereq.py selftest
```
```bash
python rl/tools/m7t_synthetic_prereq.py world-check --out logs/m7t_synth_world
```
```bash
python rl/tools/m7t_synthetic_prereq.py register --out <new dir>
```
```bash
python rl/tools/m7t_synthetic_prereq.py run --out <same dir>
```
```bash
python rl/tools/m7t_synthetic_posthoc.py --run <same dir>
```

Identities of the registered run:
- REG digest `459994a4aee31b37…`, registered 2026-09-29T15:12:32Z.
- Harness sha256 `cb3ad35abfdb1644…` at registration and at run; **the code did not change between them**.
- Run 15:16:23Z → 17:40:37Z (8,654 s), exit 0.
- Torch 2.14.0 CPU, 6 threads.
- Every result is seeded (`sha256("m7t_synth|…")`) and CPU-deterministic apart from floating-point thread
  scheduling.

## 3. What was pinned, and what happened before registration [F]

### 3.1 Before registration: world design, on seed 99 only

The harness was written first. The world was then checked by BFS over its exact dynamics, plus behaviour-only data on
a non-registered seed (99). Three world revisions happened **before** registration and before any learner ran; each
earlier check is kept in `world_check_v*.json`:

| world | problem found on seed-99 behaviour data | change |
| --- | --- | --- |
| v1, wall top 40 | random play crossed the wall (3 / 40 episodes on the wall top), unlike Mario | wall top raised to 45 |
| v2, wall top 45 | still crossed: only about 5 units of leftward drift were needed | raised step F2 moved to x 48-58 |
| v3 | no crossing, but the small right region was covered uniformly: 1 rare cell | world widened to 192 units, start x 170, extra one-way platform, cells 8 × 4 |
| **v4 (registered)** | 0 crossings in 120 episodes; wall top and left region need the double jump (BFS without it: unreachable); 42 rare cells; 106 stitch-only goals | — |

### 3.2 Registration

REG pins everything below. Revision 2 left four items open, and they were pinned before registration:

- **Wall-time limit.** Revision 2 set none. Caps: 3,600 s per training, 28,800 s for the harness.
- **λ learning rate and dynamics weight.** The paper's discrete MountainCar values, 0.3 and 75.
- **Support subset.** The clock is excluded, so that late-but-familiar states are not "off-support".
- **Operational S2 definition.** §7's "reachable within the horizon only by combining segments of ≥ 2 episodes" cannot
  hold literally when every episode starts at the same state: the witness path always exists. It was pinned as a
  per-goal budget ⌊1.25 L*⌋ + 20 that no single training episode's loop-free own path meets.

Pinned contents:
- the world;
- the data regime: 3 seeds × 120 uniform-random episodes × 3,600 ticks, 20 phase-A episodes, 12 held out;
- the model sizes;
- the training: 20,000 Adam steps at 3e-4, ε 0.25, the rescaled φ, the row composition, S rows from `sample_examples`;
- greedy evaluation;
- the diagnostics (OFF / MODEL / LOOP / FALSE_ARRIVAL windows);
- the revision-2 gate rule;
- tests S1-S6 with their thresholds.

### 3.3 Smoke run (after registration, before the registered run)

A crash test on seed 99 (16 short episodes, 60 steps) exposed a design weakness: the support diagnostic's
time-in-status features make any long purposeful status run look off-support. **The registration was not changed.**
The registered run went ahead as pinned, and the weakness is reported in §5.

## 4. Registered results [R]

### 4.1 Tests

| test | requirement | result | verdict |
| --- | --- | --- | --- |
| S1 correctness | every seed: Spearman ≥ 0.9 with true shortest ticks, and ≤ 5 % of goals underestimated by > 20 % | Spearman 0.990 / 0.989 / 0.983; underestimated 18.9 % / 30.9 % / 27.8 % (of 190 / 191 / 187 goals) | **FAIL** |
| S2 stitching + control | pooled stitch-only: T ≥ 70 %, S ≤ 30 %, ≥ 15 goals; gate rule outcome 1 | T 5 / 60 (8.3 %), S 0 / 60; gate rule outcome 4 (inconclusive in every seed) | **FAIL** |
| S3 no invalid cell stitching | ≥ 90 % of planted pairs keep d_b ≥ 0.8 × truth; D0 in every seed | 11 / 90 (12.2 %); D0 1.000 in all seeds | **FAIL** |
| S4 diagnostics | per plant ≥ 80 % correct attribution (≥ 10 failed); false alarms ≤ 10 % of healthy successes | OFF 27 / 28 (seed 1 had no off-support start); MODEL 0 / 56; LOOP 0 / 56 (all attributed OFF); false alarms 33 / 33 | **FAIL** |
| S5 negative control | untrained: null or not functional in every seed | not functional × 3 (0 / 56 returns) | PASS |
| S6 budget | every training completes 20,000 steps within 3,600 s | 894 / 1,159 / 1,051 / 1,382 / 876 / 1,073 s (T / S per seed) | PASS |

### 4.2 Per seed

| | seed 0 | seed 1 | seed 2 |
| --- | --- | --- | --- |
| rare candidates → E used | 16 → 16 | 20 → 20 | 57 → 20 |
| μ (behaviour chance) / K (most E goals one behaviour episode reached) | 1.12 / 11 | 2.33 / 17 | 3.37 / 19 |
| return threshold max(6, K + 1) / null bound | 12 / 3 | 18 / 4 | 20 / 5 |
| rare returns T / S / untrained | **2** / 0 / 0 | **9** / 0 / 0 | **17** / 0 / 0 |
| b − c (T only − S only) | 2 | 9 | 17 |
| T functional: F1 / F2 / F3 / D0 / sighted | 0.924 / 0.494 / 0.173 / 1.0 / 0.421 ✓ | 0.926 / 0.448 / 0.276 / 1.0 / 0.482 ✓ | 0.912 / 0.406 / 0.499 / 1.0 / 0.443 ✓ |
| S functional (F2 / F3 / D0) | 0.408 / **0.819** / 1.0 ✗ (F3) | 0.477 / **0.789** / 1.0 ✗ | 0.457 / **0.781** / 1.0 ✗ |
| execution-healthy (≥ half of T's failures distance-limited) | no (0 / 14) | no (0 / 11) | no (0 / 3) |
| rule class | inconclusive | inconclusive | inconclusive |
| S2 stitch-only candidates / T / S (of 20) | 115 / 1 / 0 | 118 / 3 / 0 | 116 / 1 / 0 |
| S3 pairs ok | 5 / 30 | 5 / 30 | 1 / 30 |
| replays (T returns, re-simulated) | 2 / 2 exact | 9 / 9 exact | 10 / 10 exact (cap) |

### 4.3 Distance quality (S1, from the start state to every training goal cell)

| | T seeds 0 / 1 / 2 | S seeds 0 / 1 / 2 | untrained |
| --- | --- | --- | --- |
| Spearman with true ticks | 0.990 / 0.989 / 0.983 | 0.986 / 0.986 / 0.991 | −0.76 / 0.22 / −0.74 |
| median d / truth | 1.56 / 1.71 / 2.14 | 2.57 / 3.30 / 3.54 | 0.005 |
| mean absolute error (ticks) | 57 / 65 / 88 | 203 / 220 / 275 | 64 |
| underestimated > 20 % | 18.9 / 30.9 / 27.8 % | 16.3 / 16.2 / 18.7 % | 100 % |

The union data graph's shortest paths equal the world's true shortest paths (median ratio 1.00). The data therefore
contained near-optimal composed routes; single episodes' own loop-free paths were 1.9-2.2× longer.

### 4.4 Training and cost

| | T seeds 0 / 1 / 2 | S seeds 0 / 1 / 2 |
| --- | --- | --- |
| wall (s) for 20,000 steps | 894 / 1,051 / 876 | 1,159 / 1,382 / 1,073 |
| ms per step (wall) | 44.7 / 52.6 / 43.8 | 57.9 / 69.1 / 53.6 |
| process CPU (s) | 4,888 / 5,251 / 4,863 | 6,508 / 6,931 / 6,316 |
| final λ | 188 / 203 / 302 | 66 / 67 / 61 |
| final constraint mean relu(d − c)² (ε² = 0.0625) | 0.075 / **0.263** / **0.542** | 0.000 / 0.051 / 0.000 |
| mean spread distance at the end (still rising) | 2,307 / 2,551 / 2,467 | 2,897 / 2,669 / 2,708 |
| held-out one-tick d (mean) | 0.73 / 0.72 / 0.70 | 19.4 / 13.1 / 16.6 |

- **Convergence.** T's constraint was still violated at the end in seeds 1-2 with λ rising, and spread distances were
  still growing. 20,000 steps did not converge.
- **Time.** Six trainings took 6,435 s (1 h 47 min) sequentially at 6 threads. The whole run took 2 h 24 min,
  including evaluation and ground-truth searches (per seed 44-54 min). One evaluation batch of 20 greedy episodes takes
  about 110 s.
- **Memory** (supplemental, §6): peak working set 1,036 MB and peak private bytes 1,227 MB for one seed's data, BFS,
  both arms' training and one evaluation batch.

## 5. Post-hoc diagnosis [P] (`posthoc.json`; descriptive, never deciding)

*Three statements below were corrected on 2026-09-29 by the review
(`docs/rl_m7t_synthetic_prerequisite_review_2026-09-29.md`). No registered number changed.*

1. **T learns something S does not.** On the registered rare-goal evaluation (goal set E, 56 goals, full horizon),
   T returned to 28 of 56 against S's 0 and the untrained network's 0, above the behaviour's expected 6.8. This is a
   different set from S2's 60 stitch-only goals under a tight budget, where T reached 5. T's distances rank-order the
   truth (ρ ≈ 0.99). Composition from one-tick constraints is not idle in this world.
2. **The distances collapse near goals at short range.** This is revision 2 §3.2's encoder-generalisation route.
   - *Corrected:* the underestimates are short-range, not airborne-specific. All of them lie at goals within 40 true
     ticks of the start (36 / 63, 58 / 63, 52 / 63). The air and ground rates are similar; airborne cells simply make
     up 88 % of the goals (air 33 / 168, 53 / 169, 46 / 165; ground 3 / 22, 6 / 22, 6 / 22).
   - In S3, T's d from the no-jump state is **0** for 19 / 15 / 21 of 30 pairs, and d from the jump state is often 0
     as well.
   - Consequences in evaluation:
     - *Corrected:* 57 of T's 83 failures reach a recorded d ≤ 1 at a state that exact BFS puts 4-49 ticks from the
       goal, and the agent then mostly selects the neutral word and stands still. That includes all 28 rare-goal
       failures and 29 of the 55 S2 failures. The other 26 S2 failures (seeds 1-2) exhaust the tight budget without
       any collapse.
     - *Corrected:* the registered FALSE_ARRIVAL flag fired in 33 / 23 / 9 failures. (33 / 24 / 12 is the count with a
       recorded minimum d ≤ 30.)
   - The goal-node wormhole route was prevented: D0 = 1.000 in every seed.
3. **The S2 failure is confounded.** Stitching could not be tested cleanly: the collapse stops T short of its goal in
   29 of the 55 S2 failures, and slowness under the budget explains the other 26.
4. **The execution diagnostics fired on healthy behaviour, making them unusable as registered.**
   - OFF fired at tick 11 / 11 / 21 in every successful episode. It was driven by `anim_frame` and `status_tics`
     (identical by construction here) and by tap freshness: purposeful runs are longer than anything in random data.
   - MODEL fired at tick 14 / 43 / 95 in successes, because the realised error on greedy words exceeds a p99
     calibrated on random words.
   - The LOOP and MODEL plants were therefore attributed to OFF. "Execution-healthy" could not hold in any seed, which
     blocks the rule's null path.
   - The support metric also under-weights position: in seed 1 the left-floor, left-platform and wall-top starts all
     fell within p99, so no OFF plant ran there. Behaviour never crossed the wall in any seed, so this is a metric
     property, not a data fact.
5. **The K reference is unreachable when rare goals cluster.** Goals reached by 1-2 of 20 phase-A episodes are cells of
   the same few long excursions. The top-5 single-episode counts were 11-7, 17-16 and 19-18, so the return threshold
   became 12, 18 and 20. Seed 2's 17 / 20 returns could not register. T's successful returns also shared one 60-tick
   opening (1 / 3 / 1 distinct prefixes), because every rare goal lies in the same far region.
6. **F3 is not comparable across arms.** S's model error, measured in its own quasimetric (0.78-0.82), fails the
   absolute 0.5 threshold. That blocks Pass independently of return performance; the latent geometries differ (S keeps
   state-state distances large).

## 6. Disclosures and deviations [F]

- **World revisions.** v1-v3 were rejected before registration on seed-99 behaviour data and BFS only (§3.1).
- **Smoke finding.** The diagnostic weakness seen in the smoke run did not change the registration (§3.3).
- **Memory probe bug.** The harness's in-process probe (`ctypes` psapi call) returned zeros in the registered run.
  Memory was re-measured afterwards by `m7t_synthetic_posthoc.py --memory` with `K32GetProcessMemoryInfo`, using 1,000
  optimizer steps per arm on synthetic seed-0 data and one evaluation batch. This was a supplemental measurement inside
  the authorisation; it decides nothing.
- **Post-hoc tool.** `m7t_synthetic_posthoc.py` was written after the run and only reads its outputs, apart from
  `--memory`.
- **Differences from the gate's proposed setup** (these limit what S1-S6 can say about it):
  - the 626-value observation mimics v4's layout but is synthetic;
  - the dynamics are a small discrete 2-D platformer: no projectiles, moving platform, hitlag, RNG or analog stick;
  - discrete states make exact revisits common, which makes composition easier than in Mario's continuous state;
  - cells are 8 × 4 units on a 24 × 16 grid;
  - the determinism is exact by construction, so the replays test pipeline integrity, not BattleShip determinism.

  The architectures, losses (as pinned), update budget, data regime and action rule are the ones proposed for the
  gate.

## 7. What this establishes

**Established:**
- In a deterministic synthetic platformer with random own data, the revision-2 T learner produces distances that
  rank-order true shortest paths.
- T returns to rare cells far more often than the same-trajectory twin S.
- Cell-goal membership lets distances collapse at airborne goals, producing false arrivals.
- The registered execution diagnostics fire on purposeful behaviour and cannot attribute failures.
- The gate rule's K reference cannot be met when rare goals cluster.
- The 20,000-step budget completes in 15-23 min per training on this CPU but does not converge the constraint.

**Not established:** anything about Mario or BattleShip, the native gate's outcome, crossings, targets, clears, or
iterated collection.

## 8. Consequences for the proposal (for review; nothing changed)

1. Do not propose `m7t1` as specified in revision 2: its prerequisite failed on S1-S4.
2. The areas that would need a new, separately registered design:
   - the goal definition: airborne cells or zero-cost membership let states that continue differently collapse
     together;
   - the execution diagnostics: history features, spatial weighting, and a model-error calibration valid for greedy
     actions;
   - the gate statistics: a chance and dependence reference that does not collapse when rare goals come from one
     excursion, and an F3 comparable across arms;
   - the optimisation budget: the constraint had not converged at 20,000 steps.

   None was tried here. No steps were added, and no task or threshold was changed after outcomes.
3. The M7o, M7r and M7s registered outcomes and the v3 + reward v2 baseline stand.
