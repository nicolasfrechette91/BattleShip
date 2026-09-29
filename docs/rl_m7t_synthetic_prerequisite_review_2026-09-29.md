# Review of the M7t synthetic prerequisite (2026-09-29)

This reviews `docs/rl_m7t_synthetic_prerequisite_2026-09-29.md`. **The registered result stays FAIL (S1-S4).**

No training, rerun, BattleShip launch, code change or threshold change was made. The review used only:
- the run's records in `logs/m7t_synth_prereq/`;
- the harness's deterministic world: re-simulation of recorded words and exact BFS;
- forward passes of the saved networks.

The review script and its output are kept Git-ignored in `logs/m7t_synth_prereq/review_2026-09-29/`
(`m7t_review.py` sha256 `5659e800…`, `review_analysis.json` `2c92fc81…`). No native gate is authorised.

## 1. Counts and denominators

All rows except the last two are **registered evaluations**. The last two are post-hoc splits of those registered
episodes, never deciding.

| evaluation | goals / episodes | budget | T | S | untrained |
| --- | --- | --- | --- | --- | --- |
| rare goals E (gate-rule input) | 16 + 20 + 20 = **56** | 3,600 ticks | 2 + 9 + 17 = **28** | 0 | 0 |
| S2 stitch-only goals | 20 × 3 = **60** | ⌊1.25 L*⌋ + 20 (median about 120) | 1 + 3 + 1 = **5** | 0 | — |
| goals shared by E and S2 | 1 / 3 / 4 | | | | |
| S1 goal cells (start → cell) | 190 + 191 + 187 = 568 | offline | 147 underestimated (36 / 59 / 52) | | |
| S3 planted pairs | 90 | offline | 11 pass | | |
| S4 OFF plant (seeds 0 and 2; seed 1 had no off-support start) | 16 + 20 episodes | 3,600 | 0 + 8 reached; 28 failed, 27 attributed OFF | | |
| S4 MODEL / LOOP plants | 56 + 56 episodes | 3,600 | 0 reached; 0 attributed MODEL or LOOP | | |
| S4 healthy successes | 28 (E) + 5 (S2) = 33 | | 33 carry an OFF or MODEL flag before the reach | | |
| post-hoc split by goal contact: E | ground 8 / 8, air 20 / 48 | | | | |
| post-hoc split by goal contact: S2 | ground 5 / 6, air 0 / 54 | | | | |

**"T 5 / 60" and "28 of 56" are different registered evaluations.** 5 / 60 is the stitch-only set under a tight
per-goal budget. 28 / 56 is the rare-goal set E under the full horizon. Both appear in the results report; the "28 of
56" framing in its §5 is post hoc.

## 2. The false-arrival claim: what the records show, and what stays inference

For each of T's 83 failed episodes (28 on E, 55 on S2), states were reconstructed by re-simulating the recorded words.
The recorded per-tick distance d(z_t, w(G)) and the recorded predicted next distance were then read at those states.

**Supported by records:**
- **57 of 83 failures** (33 / 17 / 7) reach a recorded d ≤ 1 while not in the goal cell. That includes **all 28 E
  failures**.
- At the first such tick, the agent is grounded in 53 of 57 cases, within 3 cells of the goal's column and mostly 0-11
  cells below it.
- Exact BFS from the reconstructed state gives a **true distance of 4-49 ticks**.
- After that tick:
  - the chosen word is the neutral word 0 in a median 75-95 % of ticks;
  - the position is unchanged in a median 84-97 % of ticks;
  - the recorded predicted next distance has a median of 0.

  With every one of the 72 predicted next states at d ≈ 0, the lowest-index tie-break selects "stand still".
- **The other 26 failures are S2 goals in seeds 1-2.** They never reach d ≤ 1 (minimum d 1.4-82) and run out of the
  tight budget. This is a second failure mode: the path is too slow, and the distance does not collapse.

**Measured post hoc on held-out pairs** (40 per h ∈ {4, 8, 16, 32, 64} per seed; exact BFS truth):
- The goal-node distance d(z(s), w(G)) is ≤ 0.5 for 81-88 % of pairs (median 0 at every h ≤ 32; true cell distance
  median 3-8 ticks).
- The state-to-state distance d(z(s), z(s′)) from the same states is compressed at short range (median 1.9-7.9 against
  truth 4-10 at h ≤ 16) but almost never 0 (1-3 %). Its Spearman with truth is 0.57 / 0.71 / 0.69, against 0.48 / 0.41 /
  0.33 for the goal node.
- S1's underestimates all lie at goals within 40 true ticks of the start: 36 / 63, 58 / 63 and 52 / 63 there, against
  0 / 63, 1 / 64 and 0 / 62 at 40-80 ticks.

**Still inference:** that the zero-cost membership rows plus weak repulsion of nearby non-members *cause* the goal-node
collapse. The records show the collapse is specific to the goal-node readout (state-to-state distances from the same
states are not collapsed). No intervention has tested why.

### Corrections to the results report (applied there in §5)

1. "Underestimated goals are overwhelmingly airborne cells" was a **base-rate artefact**: 88 % of goals are airborne,
   and the air and ground underestimate rates are similar (19.6 / 31.4 / 27.9 % against 13.6 / 27.3 / 27.3 %). The
   underestimates are short-range, not airborne-specific.
2. "Reached d ≤ 30 without arriving in 33 / 33, 24 / 28 and 12 / 22 cases (FALSE_ARRIVAL)" mixed two measures.
   - Those counts are the recorded minimum d ≤ 30.
   - The registered FALSE_ARRIVAL flag fired in 33 / 23 / 9.
   - The stronger recorded signature (d ≤ 1 at a state 4-49 true ticks away) holds in 33 / 17 / 7.
3. "Most S2 failures end under an airborne goal with d near 0" holds only for 29 of 55. The other 26 are budget
   exhaustion without collapse.

## 3. One primary blocker: the cell-goal node (zero-cost membership readout)

**Why it takes priority:**
- **It accounts for most failures.** It is the recorded signature of 57 / 83 failures and of 28 / 28 failures under the
  full horizon, where speed is not the issue.
- **It links the offline failures.** S1's underestimates (short-range only), S3 (d_b = 0) and the evaluation stalls are
  one phenomenon.
- **It is specific to the goal readout.** Goal-node distances collapse; state-to-state distances do not.

**Why not optimizer convergence:**
- Returns do not track constraint satisfaction. Seed 0 had the best-satisfied constraint (0.075) and the fewest returns
  (2 / 16); seed 2 had the worst (0.542) and the most (17 / 20).
- Underestimation is confined to short range in every seed, while long-range distances are over-estimated (median
  ratio 1.6-2.1) and the spread was still rising. More steps of the same objective push long distances up; nothing in
  it except random pairs pushes nearby non-members away from a goal node.

**Secondary, not primary:** the S2 slowness (26 failures) reflects path quality under a tight budget. It depends on the
state geometry and possibly on convergence, and it matters only after the collapse is removed.

**Gate-design problems, to repair before any native gate and not changed here:**
- The OFF and MODEL diagnostics fire on purposeful behaviour, so attribution and "execution-healthy" are unusable.
- The K reference (11 / 17 / 19) is unreachable when rare goals cluster.
- F3's absolute threshold is not comparable across arms.

These concern the measurement, not the learner.

## 4. Proposed test (one, separately registered; not authorised, not built)

**`m7t_synth_readout_v1`: goal-node readout versus a set readout on the same trained networks.**

**One controlled change.** The goal distance used by the greedy action rule (and by the stall check) changes from the
goal node, d(T(z, a), w(G)), to the QRL goal-set distance over recorded member states:
min over m ∈ M_G of d(T(z, a), z(m)). M_G is at most 32 training-split states of cell G, in sha256 order of their row
ids (all of them if fewer). Everything else stays fixed:
- the saved networks `s{0,1,2}_T.pt` (0 optimizer steps);
- the world, the data regenerated by seed, the observation builder;
- the greedy loop and the lowest-index tie-break;
- the start, the goal sets E (16 / 20 / 20) and the 3,600-tick budget.

**Control and reuse.** The control arm is the registered, recorded goal-node T evaluation. Its reuse is conditional on
integrity checks:
- the regenerated datasets and the E sets must equal the registered ones;
- 2 recorded goal-node episodes per seed must re-evaluate to identical word sequences (otherwise the goal-node arm is
  re-evaluated within the cap);
- parameter digests must be unchanged;
- no BattleShip process, and outputs outside `runs/`.

**Decisive metric:** returns to the **airborne** E goals within 3,600 ticks, pooled over 3 seeds. The control has
20 / 48 (1 / 15, 6 / 17, 13 / 16).

**Supporting metric:** the stall signature. This is a readout-arm failure whose readout distance is ≤ 1 at a
reconstructed non-member state with exact truth ≥ 4 ticks. The control shows it in 28 / 28 E failures.

**Outcomes:**

| result | condition |
| --- | --- |
| **confirm**: the goal node is the primary blocker | ≥ 36 / 48 airborne E returns, no seed below its control count, and the stall signature in ≤ 10 % of the readout arm's E failures |
| **reject**: not the goal node | ≤ 24 / 48 airborne E returns |
| inconclusive | anything else |

Ground-goal returns, S2 within budget (confounded by slowness), reach ticks and path diversity are reported and never
decide.

**Caps:**
- 0 optimizer steps;
- at most 3 × 20 greedy episodes of ≤ 3,600 ticks, plus ≤ 6 integrity re-evaluations;
- 120 min wall time;
- 2 GB private memory (corrected probe).

The per-tick cost of 72 × 32 set distances is measured on smoke seed 99 before registration. Hitting a cap means
incomplete: no conclusion, and no extension.

**What each result would mean:**
- **Confirm.** The state geometry learned here already supports greedy return to airborne cells, and the goal-node
  readout is the demonstrated blocker. A later design may change **only** the goal representation. It would then need
  the full S1-S6 prerequisite again, after the diagnostics and K are repaired, before any native gate is discussed.
  Caveat: this geometry was trained *with* goal nodes, so a confirm does not show that training without them works.
- **Reject.** Even without the goal node, this state geometry does not carry greedy return. The blocker then lies in
  the learned geometry itself: convergence, the objective's short-range resolution, or one-step greedy extraction.
  These cannot be separated by one further change, so **stop M7t** rather than package several revisions into a new
  run.
- **Inconclusive.** Stop as well; no follow-on variants.

## 5. Unchanged

- The registered FAIL and every registered number.
- The M7o, M7r and M7s registered outcomes.
- The v3 + reward v2 baseline.
- Observations, rewards and action contracts.
- No native gate or campaign is authorised.
