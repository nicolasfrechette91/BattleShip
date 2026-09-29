# Learning-strategy review after M7s: composed temporal distance (2026-09-29, revision 3)

**Design status (user decision, 2026-09-29): M7t is stopped before final acceptance; native eligibility is not
established.**
- The acceptance test `m7t_accept_v1` (§7) was **not authorised and not run**. It has no outcome, and is recorded
  neither as a failure nor as a pass.
- The native gate `m7t1` (§9) will not be proposed.
- The closure is `docs/rl_m7t_closure_2026-09-29.md`.
- The sections below are the design as it stood when M7t stopped, kept unchanged for the record.

Status of the revision itself: **design only.** Nothing was launched, replayed, trained, evaluated or implemented, and
nothing was committed or pushed. The only computation was a read-only comparison of recorded reach ticks with exact
world search (§1.1); no network was loaded.

Registered outcomes, unchanged and kept separate:
- M7o `failure_regression`; M7r outcome 5 (inconclusive); M7s `m7s1` outcome 3 (inconclusive);
- **M7t synthetic prerequisite: FAIL** (S1-S4 fail, S5-S6 pass). Results in
  `docs/rl_m7t_synthetic_prerequisite_2026-09-29.md`, reviewed in `docs/rl_m7t_synthetic_prerequisite_review_2026-09-29.md`;
- **M7t synthetic readout test: CONFIRM** (28 → 46 of 56 rare goals on the saved T networks;
  `docs/rl_m7t_synthetic_readout_2026-09-29.md`).

The CONFIRM does not overturn the FAIL. It re-measured one registered evaluation under a different readout, and none of
S1-S6 (§2).

Observation v3 + reward v2 (Track 1 PPO) stays the selected baseline. The native gate `m7t1` is **not authorised**, and
this report does not request it. No human recording, TAS, crossing fixture or geo4 checkpoint informs any choice. No
native RNG is inspected, logged, controlled, compared or hashed.

**Revision 3** consolidates the M7t findings:
- **Candidate** (§3): the registered T training, unchanged, acting through the set readout confirmed on saved networks.
- **Unmet requirements** (§2), separating measured failures from requirements never re-evaluated.
- **Control** (§4): the twin S is withdrawn. Its saved networks cannot take the set readout fairly, and no
  readout-matched twin with QRL's loss can switch composition off.
- **False arrivals** (§5): tolerated in a return gate as counted failures, under conditions the design now enforces.
- **Repairs** (§6): execution diagnostics, chance reference and F3. Three further definition changes are disclosed and
  justified (§6.4-6.5).
- **One final synthetic acceptance test**, `m7t_accept_v1` (§7), and a fixed endpoint (§8): anything but acceptance
  stops this variant.
- **Native gate** restated for the candidate (§9), still unauthorised.

Revision 2 was overwritten. A verbatim copy is kept, Git-ignored, at
`logs/m7t_design_history/rl_learning_strategy_review_2026-09-29_rev2.md` (sha256 `3e0a372f…`). The registered
prerequisite's tests and thresholds are pinned in its REG (`459994a4…`), so nothing registered depends on that copy.

Labels:
- **[F]** registered result, source fact or tested property;
- **[M]** measurement on existing records;
- **[P]** the QRL paper (arXiv 2304.01203 v7);
- **[I]** inference;
- **[H]** hypothesis.

## 0. Verified state (read-only)

| item | state |
| --- | --- |
| parent | `HEAD 48ea181`. The four modified `rl/*.py` and the untracked M7r / M7s / M7t files are preserved; revision 3 changed only this report |
| submodules | `decomp e4f06348`, `libultraship 805f1950`, `torch 3aa9c97`; unchanged |
| M7t tools (untracked) | harness `rl/tools/m7t_synthetic_prereq.py`, sha256 `cb3ad35a…`, unchanged since registration; readout tool `rl/tools/m7t_synthetic_readout.py`, `1001f14e…` |
| M7t records (Git-ignored) | `logs/m7t_synth_prereq/`: saved `s{0,1,2}_{init,T,S}.pt`, `results.json` `3cd6526c…`, episode files. `logs/m7t_synth_readout/`: `result.json` `8dc5689b…`. `logs/m7t_design_history/`: the revision-2 copy, and the §1.1 script and output |
| `runs/` | A read-only scan found 391,625 regular files, junctions skipped: the count revision 2 verified as covered by the D: base + M7r + M7s increments. The newest file is dated 2026-09-29 00:32 (`runs/m7s/gate/_gate/launch/extract.json`), so nothing was written since. Every M7t output is under `logs/`. No BattleShip process is running |
| compute | torch 2.14.0, CPU only, 6 threads |
| stale items, not fixed | `rl/m7s_gate.py` `BACKUP_INCREMENTS` lists only M7r. The docstring of `rl/tools/m7s_failure_analysis.py` does not match its estimator |

## 1. What M7t has established so far

| step | outcome | established | not established |
| --- | --- | --- | --- |
| prerequisite `m7t_synth_prereq_v1` (registered) | **FAIL** | <ul><li>T's distances rank-order true shortest paths (Spearman 0.98-0.99)</li><li>T returned to 28 of 56 rare goals; S and the untrained network to 0</li><li>the goal-node readout collapses near goals (false arrivals)</li><li>the registered diagnostics fire on healthy behaviour</li><li>K is unreachable when rare goals cluster</li><li>F3 is not comparable across arms</li><li>20,000 steps do not converge the constraint (0.075 / 0.263 / 0.542 against ε² 0.0625, λ rising)</li></ul> | anything about Mario |
| review | primary blocker: the goal-node readout | <ul><li>all 28 rare-goal failures, and 57 of 83 failures overall, reach readout ≤ 1 at states 4-49 true ticks away</li><li>state-to-state distances are compressed at short range but almost never 0</li></ul> | why the goal node collapses (inference only) |
| readout test `m7t_synth_readout_v1` (pinned) | **CONFIRM** | on the saved T networks, the set readout raised rare-goal returns 28 → 46 of 56: 18 gains, 0 losses, no seed worse; every gain airborne | <ul><li>training without goal nodes</li><li>convergence</li><li>removal of false arrivals: all 10 remaining failures are false arrivals, 13-30 true ticks away</li><li>speed</li><li>Mario</li></ul> |

### 1.1 New measurement for this revision [M, post hoc]

This compares the readout test's recorded reach ticks with exact world search from the start. No network was loaded.
The script and output are `logs/m7t_design_history/reach_vs_truth.{py,txt}`.

| | goal-node readout O | set readout R |
| --- | --- | --- |
| true distance of the 56 rare goals | 67-131 ticks (median 119) | same |
| successful returns | 28 | 46 |
| reach tick / true shortest ticks, median (quartiles) | 5.1 (1.8-9.3) | **9.3 (2.1-14.3)** |
| returns within 2 × the shortest path | 8 | 11 |
| median ratio: successes without / with a false-arrival event | 2.1 / 10.7 | **7.0** / 16.4 |
| share of the excess ticks (reach − truth) spent with readout ≤ 1 | 51 % | 15 % |

**[I]** R returns more often, but along long paths, and most of its extra time is not spent stalled. Even without any
false-arrival event, its returns take a median 7 × the shortest path. That bears directly on the composition criterion
(A3, §7.7).

## 2. Requirements still unmet (item 1)

The readout test repeated **one** registered evaluation under R: returns to the rare goals. That is an input of the
gate rule, not one of S1-S6. Every S-test was measured only under the goal-node readout.

| requirement (revision 2 §7) | registered, goal-node readout [F] | under R | status |
| --- | --- | --- | --- |
| S1 correctness: Spearman ≥ 0.9, and ≤ 5 % of goals underestimated by > 20 % | Spearman 0.990 / 0.989 / 0.983 (met); underestimated 18.9 / 30.9 / 27.8 % → **FAIL** | not re-evaluated | **Unmet**: a measured failure under O, unknown under R. The review's state-to-state pairs (median 1.9-7.9 against truth 4-10 at h ≤ 16; zero in 1-3 %) suggest the ranking survives and the underestimation part does not |
| S2 stitching: T ≥ 70 % of stitch-only goals within ⌊1.25 L*⌋ + 20, S ≤ 30 %, gate rule pass | T 5 / 60, S 0 / 60, rule outcome 4 → **FAIL**. Confounded: 29 collapse, 26 too slow | not re-evaluated | **Unmet**; §1.1 makes a pass under R unlikely |
| S3 no invalid stitching: ≥ 90 % of planted pairs with d_b ≥ 0.8 × truth, and D0 | 11 / 90 (d_b = 0 in 19 / 15 / 21 of 30); D0 1.000 → **FAIL** | not re-evaluated | **Unmet** |
| S4 diagnostics: ≥ 80 % correct per plant, ≤ 10 % false alarms | OFF 27 / 28, MODEL 0 / 56, LOOP 0 / 56, false alarms 33 / 33 → **FAIL** | not re-evaluated. The readout test used its own false-arrival definition, not the registered flags | **Unmet**: a measurement defect |
| S5 untrained is never pass | not functional × 3 → PASS | not re-evaluated | met under O only |
| S6 budget: 20,000 steps within 3,600 s | 876-1,382 s → PASS | training unchanged | met |
| gate rule returns pass on the synthetic run (part of S2) | outcome 4 in every seed | not re-run. **[M]** Arithmetic on recorded counts: n_R = 11 / 17 / 18 against return thresholds max(6, K + 1) = 12 / 18 / 20, so Return would still fail in every seed, by 1-2 goals. S's F3 and "execution-healthy" would still block | **Unmet**: K and the diagnostics make a pass unreachable |

## 3. The candidate

**C = the registered T training + the set readout.**

**Training, unchanged:** `train_arm(…, "T", …)` of the harness at REG `459994a4…`.
- one-tick local rows, cost-0 membership rows to goal nodes, and the spread with sink pairs;
- dynamics loss weight 75, λ learning rate 0.3;
- 20,000 Adam steps at 3 × 10⁻⁴, with 512 shared transitions per step.

Goal nodes stay in training. The geometry R reads was shaped by them and their membership rows, and training without
them is untested. The known non-convergence comes with it.

**Action rule:**
- Each tick, submit a* = argmin over the 72 words of min over m ∈ M_G of d(T(z(s), a), z(m)). Ties go to the lowest
  index (`torch.argmin`).
- M_G is up to 32 training-split states whose valid cell is G, taken in ascending sha256 order of (prefix, seed,
  episode, tick). This is the readout test's pinned rule.
- Held-out and evaluation states never enter M_G, and M_G is frozen before training.
- A goal with no training member cannot be commanded; it counts as a failed return. The goal-selection rules are
  unchanged.
- Success is the first valid reach in the world (natively, `goal_reached`). The readout never ends or scores an episode.

**Relation to QRL [P, I].**
- The paper's goal-set method is the augmented symbol; the goal node implements it.
- R instead uses the definition of a set distance, the minimum over members, taken over at most 32 recorded members.
  In the learned metric, that is an upper bound on the distance to the nearest recorded member, exact only if that
  member is sampled.
- It is a project variant, and no guarantee is claimed.

**Not assumed:**
- that training without goal nodes works;
- that false arrivals are gone (§5);
- convergence;
- short or near-optimal paths (§1.1);
- transfer to Mario.

**Unchanged from revision 2:**
- The state is the v4 policy observation (626 values), standardised with frozen training-split statistics. It is only
  approximately Markov, so QRL's deterministic-dynamics assumption holds only approximately.
- The IQE head is a quasimetric: it satisfies the triangle inequality and is asymmetric.
- Mechanics are handled as before:
  - steering by per-tick drift;
  - presses as observed input state;
  - locks scored by post-lock states;
  - projectiles as entity state;
  - hitlag taps as a known 5-8-tick gap.
- There is no reward, discount, PPO or mask.

## 4. The control: why S is withdrawn (item 2)

**The saved S networks do not permit a fair comparison [F].**
- S's constraint rows were (s → goal node, cost h) plus membership rows. No state-to-state distance was ever
  constrained; the spread only pushed such distances apart.
- Recorded held-out one-tick distance: S 19.4 / 13.1 / 16.6, against T 0.73 / 0.72 / 0.70.
- R can be computed on S, which has an encoder, a head and a model. But it would read a quantity S's objective never
  trained, so a gap in T's favour would be built in.

**A readout-matched twin cannot switch composition off [I].**
- R reads state-to-state distances, so a readout-matched S must be retrained with *state* targets.
- The quasimetric composes every constrained state-to-state distance through the triangle inequality. Revision 2's S
  avoided composition only because its targets were goal nodes, which have no outgoing constraints and which R never
  reads.
- If the twin's targets are later states of the same episode, drawn over all ticks, its constraint set contains every
  one-tick pair in the limit. Its feasible set then equals T's, and it differs only in which spans a finite batch
  happens to enforce.
- If its targets are the first-hit states drawn by M7s's `sample_examples`, it composes through cell-entry states. The
  non-entry members that R reads stay unconstrained, which is unfair to S.
- A non-quasimetric twin would avoid forced composition, but only by changing the head and the loss. That is the
  multi-variable control revision 2 rejected.

**Decision.**
- No twin in the acceptance test or the native gate.
- Composition is tested only where it can be verified: against exact ground truth in the synthetic world (A3, §7).
- The native gate no longer claims a composition advantage. It claims goal-directed learned return (§9).
- Revision 2's mechanism indicator (returns faster than every recorded episode that reached the goal) is still reported,
  but decides nothing.
- Revision 2's outcome 3, "return without a composition advantage", disappears.

## 5. False arrivals (item 3)

**Facts [F, M].**
- All 10 of R's failures are false arrivals, stalled 13-30 true ticks from the goal, with the readout at 0.0-1.0.
- No failure exhausted the horizon without one, and there were no deaths.
- 15 of R's 46 successes had a false-arrival event and still arrived later.

**The gate objective** (§9.1): from tick 0, reach commanded rare own cells more often than behaviour chance, and more
often than the same policy reaches them when commanded elsewhere. It asks nothing about reliability, speed or chaining
goals.

**Verdict: tolerable as counted failures. They do not invalidate the distance policy for this gate**, under four
conditions the design enforces:

1. **Scoring by membership only.** Success is the first valid reach, and a false arrival is never scored as one. The
   readout never ends or scores an episode.
2. **They can only remove reaches.** Every counted success, commanded or scrambled, is a real reach, and a false
   arrival never turns a non-reach into one.
   - In commanded episodes, false arrivals lower n_T and b′.
   - In scrambled episodes, they can lower c′, but only by stalling near the commanded partner goal. That is itself
     command-directed behaviour, and b′ still needs real commanded reaches.
   - The behaviour expectation μ_s comes from random data and is untouched.

   False arrivals therefore cannot manufacture a pass.
3. **They are attributed to the distance.** A false arrival is the learned distance being near zero at a non-member, so
   it is distance-limited (§6.1). A null dominated by false arrivals is read as a failure of the distance, never excused
   as execution.
4. **They are priced.** Each one runs to the horizon, and the tick ledger already prices every evaluation episode at
   3,600 ticks.

No stall escape, randomised tie-break or readout threshold is added to hide them. That would be another readout
revision, which §8 excludes.

**What they do rule out:**
- **Reliable arrival.** None of the 10 stalls recovered, so any objective that chains goals in one episode would
  compound them; a clear needs every target broken. A gate pass says nothing about chains.
- **Speed.** §1.1 shows long paths even without stalls.

In the acceptance test, false arrivals are bounded indirectly: they count against A2 and A3, and merged states fail A4.
Their frequency, and the exact remaining distance at the first near-zero tick, are reported.

## 6. Measurement repairs (item 4) and every definition change

**Units.**
- u is the network's median held-out one-tick distance d(z_t, z_t+1). For T, the recorded means are 0.70-0.73.
- ρ_t is the set readout of the current state.

### 6.1 Execution diagnostics

**Per-tick conditions:**
- **OFF′:** the agent's cell (bin × contact) has **no training-split member**. The support key contains no durations,
  status timers, animation frames, tap freshness or velocities.
- **MODEL′:** the realised two-way error of the executed word, max(d(T(z_{t−1}, a), z_t), d(z_t, T(z_{t−1}, a))),
  exceeds the network's own p99 over held-out recorded transitions.
- **FA′:** ρ_t ≤ 1.5 u while the agent is not in G.

**Attribution of a failed episode** uses its final window W: the last 300 ticks, or the whole episode if shorter. The
first matching row wins:

| # | class | condition on W | reading |
| --- | --- | --- | --- |
| 1 | OFF | OFF′ on ≥ 50 % of ticks | execution-limited |
| 2 | MODEL | MODEL′ on ≥ 50 % of ticks | execution-limited |
| 3 | FALSE_ARRIVAL | FA′ on ≥ 50 % of ticks | distance-limited |
| 4 | LOOP | the running minimum of ρ falls by less than u across W | distance-limited |
| 5 | DEATH / SLOW | ended by death / still progressing at the end | distance-limited |

- **False alarm:** a healthy success with OFF′ or MODEL′ on ≥ 50 % of any 300-tick window before the reach (or of the
  whole pre-reach span, if that is shorter).
- **Execution-healthy (unchanged):** at least half of T's failed commanded episodes are distance-limited.

**How this removes the defects found:**
- **Support by place, not by history.** A purposeful run through visited cells stays on support however long its status
  lasts. Status history was why OFF fired early (ticks 11-21) in every registered success. Position is now the whole
  key, so unvisited regions such as the area behind the wall are off support in every seed. The registered metric
  missed this in seed 1.
- **The failure's own end decides, not the earliest flag.** Transient early flags no longer pre-empt the state the
  episode actually failed in. The LOOP plant stands still in a visited cell, so it is no longer read as off support.
- **MODEL keeps a within-network p99 but needs a majority of 300 ticks.** Greedy selection raises the realised error
  sporadically: the registered 3-of-10 rule fired at ticks 14-95 of successes. A corrupted model errs persistently.
- **No absolute distances.** Every threshold is in u or a within-network quantile.

**Costs of these choices:**
- OFF′ ignores novel dynamics inside visited cells; those are left to MODEL′.
- Natively, the cells are `btt_goal_cell_v1` bins (300 units × contact).
- The repaired diagnostics are validated only by A5.

### 6.2 Chance reference

- **μ_s is kept:** the expected number of E goals one behaviour episode reaches, from the 100 non-phase-A episodes. The
  null bound stays ⌈μ_s⌉ + 1.
- **K is withdrawn,** though still reported. Clustered rare goals made K 11 / 17 / 19 and the return thresholds
  12 / 18 / 20. R's counts miss those thresholds by 1-2 goals in every seed (§2).
- **Goal-scrambled reference (new):**
  - Fix a derangement over E's registered order, restricted to goals with members: π(g_k) = g_j with
    j = (k + ⌊n/2⌋) mod n.
  - For each goal g, run one extra episode: the same policy, commanded to π(g) from tick 0, scored on g. Success is the
    first valid reach of g within 3,600 ticks; reaching π(g) does not end the episode.
  - Pair the outcomes per goal: b′ counts goals reached only when commanded, and c′ goals reached only when scrambled.
- **Why [I]:**
  - The network, start and dynamics are identical; only the command differs. Goals the policy passes anyway are credited
    to the reference, not to the command, and a goal-blind policy gives b′ ≈ c′.
  - Clustering cannot make the criterion unreachable. Take a policy that goes to its goal and stays there: about half of
    the goals along one corridor lie before their partner. Then b′ − c′ ≈ n_T / 2, which reaches 4 once about 8-10 goals
    are returned to.
- **Rule elements:**
  - Return(s) = Functional ∧ Sighted ∧ n_T ≥ max(6, ⌈μ_s⌉ + 2) ∧ b′ − c′ ≥ 4 ∧ replays exact. The bound ⌈μ_s⌉ + 2 keeps
    Return and Null disjoint by construction; 4 is revision 2's paired margin, reused.
  - Blind(s) = Functional ∧ b′ − c′ ≤ 0. This is the M7s failure mode, now counted as a fail.

### 6.3 F3

- **F3′ = median held-out two-way model error / u ≤ 1.0.** The model error must be below one typical step. Beyond that
  point, one-tick outcomes cannot be told apart at the median. The ratio does not change when d is rescaled, so any
  network is judged in its own step unit.
- **Disclosure: the value was chosen with the registered numbers in view.**
  - T's ratios are about 0.24 / 0.38 / 0.71: F3 0.173 / 0.276 / 0.499 over the recorded *mean* one-tick d. The medians
    were not recorded.
  - A half-step bound would declare seed 2, with 17-18 of 20 returns, non-functional. So 0.5 has no support as a
    necessary condition.
  - This informed choice is one reason decisions move to fresh seeds (§7.1).
- With S withdrawn, F3′ applies to T and the untrained control. F1 (T's one-tick d ≤ 1.5 on ≥ 90 %) is already in T's
  own cost unit and is unchanged.

### 6.4 Every change against the registered prerequisite and revision 2

| element | registered / revision 2 | revision 3 | kind |
| --- | --- | --- | --- |
| action readout | d(T(z, a), w(G)) | set readout over ≤ 32 members (§3) | the candidate's one change, confirmed on saved networks |
| T training | registered | unchanged | — |
| twin S | same-trajectory, goal-node targets | withdrawn | §4 |
| distance in F2, Sighted, S1, S3 | goal node | set readout | follows the readout |
| F3 | median error ≤ 0.5 | median error / u ≤ 1.0 | repair, §6.3 |
| chance reference and return bound | K_s; n ≥ max(6, K + 1); b − c ≥ 4 against S | scrambled b′ − c′ ≥ 4; n ≥ max(6, ⌈μ⌉ + 2); K reported | repair, §6.2 |
| fail outcome | Null in ≥ 2 seeds | Null or Blind in ≥ 2 seeds | follows the new reference |
| OFF, MODEL, FALSE_ARRIVAL, LOOP, attribution | <ul><li>OFF: Euclidean support over 67 values, p99, 10 ticks</li><li>MODEL: 3 of 10 ticks</li><li>FALSE_ARRIVAL: d ≤ 30 with no reach in 120 ticks</li><li>LOOP: running minimum falls < 1 in 300 ticks</li><li>earliest flag decides</li></ul> | §6.1 | repair |
| S1 | Spearman ≥ 0.9 **and** ≤ 5 % underestimated by > 20 % | Spearman decisive; underestimation reported | **relaxation**, §6.5 |
| S2 | budget ⌊1.25 L*⌋ + 20; T ≥ 70 %; S ≤ 30 %; gate pass | budget own-best − 1; T ≥ 70 %; the gate pass is A2 | repair of a recorded confound; S removed |
| S3 | d_b ≥ 0.8 × truth_b on ≥ 90 % | ρ_b > ρ_a on ≥ 90 % | repair, §6.5 |
| seeds | 0, 1, 2 | decisions on 3, 4, 5; seeds 0-2 anchor the code | out of sample |

**Unchanged:**
- S4's 80 % / 10 % thresholds, S5 and S6;
- D0, F1, F2's 0.30 and Sighted's 10 %;
- the return floor 6, the null bound and the paired margin 4;
- the E, S2 and S3 selection rules;
- world v4 and the data regime.

### 6.5 Why S1, S2 and S3 change

**S1.**
- Revision 2 §2.1 already withdrew any claim that d recovers optimal times. The policy uses only rankings and the
  near-zero region.
- The review measured compression without collapse in state-to-state distances. The magnitude criterion would therefore
  fail for a property the candidate does not claim.
- Collapse, the harmful case, is counted directly as failed returns (A2, A3) and tested by S3.
- The underestimation fraction stays reported. **This is the only relaxation of a registered pass condition.**

**S2.**
- The review found that the registered budget mixed two failures: collapse and slowness.
- Every registered stitch-only goal has own-best > budget, so own-best − 1 is never tighter than the registered budget.
- It still excludes every single-episode path. A reach within it needs transitions from at least 2 episodes, or
  unrecorded ones. That is the capability the staged path needs (H-T3).
- On the registered goal sets, the median budget moves from 118-125 to 153-185 ticks (L* 79-84.5).
- The 70 % threshold is unchanged.

**S3.**
- The hazard is merging two states that continue differently (jump available or not). The pairs are built with
  truth_b ≥ 2 × truth_a, so merging makes ρ_a and ρ_b indistinguishable and their order arbitrary.
- Compression alone fails the registered comparison with truth, but leaves the order intact.
- Ranking therefore tests the hazard itself.

## 7. The final synthetic acceptance test `m7t_accept_v1` (item 5)

It uses zero native ticks and never launches BattleShip.

### 7.1 Data, seeds and arms

**Anchor on the saved networks (integrity):**
- Seeds 0-2, `s{0,1,2}_T.pt`, with the registered data regenerated by seed.
- The test's own set-readout rollout must reproduce all 56 R episodes of the pinned readout test word for word, with the
  same end and reach tick (`result.json` `8dc5689b…`). Any mismatch stops the run.
- This is the only reuse of saved networks. The saved S networks cannot take R (§4), and the saved untrained networks
  belong to seeds 0-2.

**Decision seeds 3, 4, 5 (never generated):**
- World v4 and the registered data regime: 120 uniform-random episodes × 3,600 ticks, 20 phase-A, 12 held out, and
  per-episode behaviour generators.
- E, the S2 goals and the S3 pairs follow the registered rules.
- Initialisation and batch generators are set by seed. T is trained by the unchanged `train_arm` (20,000 steps), and
  M_G is frozen before training.
- **Why fresh seeds:** the readout, the repairs and F3′ were all designed after seeing seeds 0-2. The training recipe is
  unchanged, so fresh seeds cost only three trainings (measured at 15-18 min each).

Per decision seed:

| arm / control | runs | role |
| --- | --- | --- |
| **T + R** (the candidate) | <ul><li>commanded E</li><li>scrambled E</li><li>S2 goals, budget own-best − 1</li><li>plants on E: OFF (start at the first of (16, 8), (15, 30), (35, 45) whose cell has no training member); MODEL (words permuted in scoring); LOOP (neutral word forced from tick 30)</li></ul> | decisive |
| untrained initialisation + R | functional checks; E episodes only if functional | negative control (S5) |
| behaviour | μ_s from the 100 non-phase-A episodes | chance |
| T + goal-node readout O | commanded E | replication of the readout effect; reported only |
| offline, forward passes only | F1, F2 (R), F3′, D0, Sighted (R), S1 (R), S3 (R) | |

### 7.2 Decisive criteria (fixed now)

| id | criterion | minimum count |
| --- | --- | --- |
| **A1 integrity** | <ul><li>pinned inputs match</li><li>regenerated seed-0-2 data equal the registered data</li><li>anchor 56 / 56</li><li>M_G only from the training split</li><li>parameters unchanged after evaluation</li><li>optimizer steps = 3 × 20,000 on seeds 3-5, plus ≤ 60 on seed 99 before the pin</li><li>no BattleShip process</li><li>outputs outside `runs/`</li></ul> | — |
| **A2 return** | rule `m7t1_rule_v3` (§9.2) on seeds 3-5 gives outcome 1: Return in ≥ 2 of 3 seeds | — |
| **A3 composition** | T + R reaches ≥ 70 % of the stitch-only goals within own-best − 1 ticks, pooled | ≥ 15 goals |
| **A4 distance validity** | <ul><li>S1: Spearman(ρ(start, G), truth) ≥ 0.9 in every seed</li><li>S3: ρ_b > ρ_a in ≥ 90 % of pooled pairs</li><li>D0 in every seed</li></ul> | ≥ 15 pairs |
| **A5 diagnostics** | <ul><li>each plant: ≥ 80 % of its failed episodes attributed to it</li><li>false alarms ≤ 10 % of healthy successes (commanded E + S2)</li></ul> | ≥ 10 failed per plant; ≥ 10 healthy successes |
| **A6 negative control** | the untrained initialisation is not Return in any seed | — |
| **A7 budget** | each training completes 20,000 steps within 3,600 s | — |

**Reported only:**
- R against O on the fresh seeds, paired per goal;
- airborne and ground returns;
- false-arrival frequency, with the exact remaining distance at the first near-zero tick;
- attribution of the natural failures;
- reach / truth, with and without false-arrival events;
- S1's underestimation fraction and S3's registered criterion;
- S2 success within the registered budget;
- K and the mechanism indicator;
- constraint and λ trajectories;
- CPU time, per-tick readout cost and memory.

### 7.3 Pinning, caps and integrity

**Code.**
- A new standalone tool imports three files unchanged: the harness (`cb3ad35a…`), the readout tool (`1001f14e…`, for
  representative selection) and `m7s_goal.py`.
- It refuses to write under `runs/`.
- Before the pin, only two things may run: a seed-99 smoke test (≤ 60 optimizer steps, ≤ 2 goals per set) and the
  anchor reproduction on seeds 0-2. Their outcomes are either already known or meaningless, and neither can change a
  threshold.

**Pin.**
- `pin` writes a write-once protocol that holds:
  - the rules and thresholds of this section;
  - the tool hash;
  - the input hashes: saved networks, the readout `result.json`, the harness, the readout tool and `m7s_goal.py`;
  - the seeds and the caps.
- `run` refuses on any mismatch.

**Run phases:**
1. inputs;
2. anchor;
3. per seed: data, goal sets and M_G, training, offline checks, evaluations, attribution;
4. decision.

**Caps:**
- 28,800 s wall time (the registered harness cap);
- 3,600 s per training;
- 2,048 MB peak private memory (corrected probe);
- 0 native ticks.

**Estimate [I]: about 5-5.5 h.**
- The anchor takes about 35 min: R's 56 episodes took about 32 min in the readout test, diagnostics included.
- Each seed takes about 95 min: its training, plus about 10 min per 20 R episodes. The plant, scrambled and untrained
  runs mostly go to the horizon.
- Peak memory is expected near the measured 1.2 GB, since one seed is held at a time.

### 7.4 Outcomes

| outcome | condition |
| --- | --- |
| **ACCEPT** | A1-A7 all hold |
| **REJECT** | valid, complete run in which any of A3-A7 fails with its minimum count met, or A2's rule outcome is 2 (fail) |
| **INCONCLUSIVE** | valid, complete run that is neither ACCEPT nor REJECT: a minimum count is unmet, or A2's rule outcome is 3 |
| **INVALID / INCOMPLETE** | any A1 check fails, or a cap is reached: stop and report, with no interpretation |

### 7.5 Why this one test settles native-gate eligibility

- **It runs the complete candidate the native gate would run.** The training recipe, readout, action rule, evaluation,
  scrambled reference, rule and diagnostics are all the gate's. No component reaches the gate untested.
- **It checks everything the gate relies on but cannot check natively, against ground truth:**

  | the native gate relies on | checked by |
  | --- | --- |
  | its code is the code that produced the confirmed readout effect | A1 |
  | a return count means goal-directed return, not a path that passes goals anyway | A2 (scrambled reference, world truth) |
  | a null cannot come from a learner that is not functional | A6, with A2's functional checks |
  | the distance ranks true times and does not merge states that continue differently | A4 |
  | failures are attributed correctly, so a null is not an execution artefact | A5 |
  | composition beyond single episodes (the M7t premise; H-T3) | A3 |
  | the optimizer budget completes | A7 |
- **It is out of sample.** Decisions rest on seeds that played no part in choosing the readout or the repairs.
- **Nothing is left to tune.** The learner and readout are frozen, every threshold is fixed here, and §8 forbids
  revisions. Its outcome is therefore final for this variant.
- **What it cannot settle is what only the native gate can:**
  - whether Mario's random data contains stitchable overlaps near rare cells;
  - whether a v4 encoder separates Mario states that continue differently;
  - one-step model accuracy with collisions, the moving platform, projectiles, locks and hitlag;
  - how far the dynamics depart from determinism;
  - whether the rescaled φ suits Mario's distances;
  - any crossing, target or clear.

### 7.6 What an ACCEPT would and would not mean

**It means** that, on fresh synthetic seeds, the unchanged T recipe with the set readout:
- returned goal-directedly to rare own cells;
- composed paths shorter than any single recorded episode's, on most stitch-only goals;
- ranked true distances without merging the planted states;
- had its failures attributed correctly;
- completed the budget.

**It does not mean** any expected native result, training without goal nodes, convergence, reliable arrival,
near-optimal speed or transfer to Mario.

### 7.7 Forecast from existing records (for the decision; not part of the test)

- **A3 is the most likely failure.**
  - R's successful returns took a median 9.3 × the shortest path, and 7.0 × even without any stall. Only 11 of 46
    arrived within 2 ×.
  - The own-best − 1 budgets are about 2 × the shortest path (median 153-185 ticks, against L* 79-84.5).
  - Caveat: this was measured on the far, clustered rare goals, not on stitch-only goals.
- **A5 has never been measured.**
- **A2 and A4's Spearman criterion are plausible** if the seed-0-2 behaviour replicates.

## 8. Endpoint (item 6)

- **ACCEPT:** the variant becomes *eligible to be proposed* for the native gate of §9. Proposing it and authorising it
  remain separate user decisions.
- **REJECT, INCONCLUSIVE, INVALID or INCOMPLETE: stop this M7t variant** (the T recipe with the set readout). None of the
  following may follow automatically:
  - a new readout: more or other representatives, a k-nearest or soft minimum, a stall escape, another tie-break;
  - a changed threshold or definition;
  - more optimizer steps, a new budget, network or loss;
  - more or other seeds;
  - a rerun.

  An integrity failure is reported without interpretation, and any rerun is a new decision. Further QRL-family work
  would be a new milestone, by explicit decision.
- The registered FAIL, the readout CONFIRM and the acceptance outcome remain three separate records.

## 9. Native gate `m7t1`, revision 3 (not authorised; proposable only after ACCEPT)

### 9.1 Claim

From one round of its own random tick-0 experience, a greedy agent returns from tick 0 to rare cells its behaviour
reached by chance. Its distances are trained only with one-tick and cost-0 membership constraints, and read through at
most 32 recorded member states. It returns to those cells:
- more often than the behaviour's expected count;
- more often than the same policy reaches them when commanded elsewhere.

Composition in Mario is not claimed. The mechanism indicator is reported only.

### 9.2 Rule `m7t1_rule_v3` (applied once; also used by A2)

**Per seed:**
- Functional(T) = F1 ∧ F2 (R) ∧ F3′ ∧ D0. The thresholds are 1.5 / 90 %, 0.30, 1.0 u and 3,000 / 99 %.
- Sighted (R): swapping the goal's member set changes the greedy word on ≥ 10 % of 4,000 held-out states.
- Return(s) and Blind(s) as in §6.2.
- Null(s) = Functional(T) ∧ execution-healthy ∧ n_T ≤ ⌈μ_s⌉ + 1.

| # | outcome | condition |
| --- | --- | --- |
| 0 | invalid / incomplete | any integrity failure, or a crashed seed |
| 1 | **pass** | Return in ≥ 2 seeds |
| 2 | **fail** | Null or Blind in ≥ 2 seeds |
| 3 | inconclusive | otherwise. The record names each seed's blocker: not functional, not sighted, execution-limited, n_T between the bounds, 1 ≤ b′ − c′ ≤ 3, or seeds disagreeing |

### 9.3 Changes to revision 2's gate

**Changed:**
- The only arm is T.
- The policy is §3's, with M_G taken from the stored v4 observations of the 108 training episodes.
- Each seed evaluates 20 commanded and 20 scrambled E episodes.
- The diagnostics are §6.1's, on native cells.
- Up to 10 T returns are replayed per seed.
- The optimizer runs 3 × 20,000 steps, CPU only.

**Unchanged:**
- seeds 0-2;
- the M7r F-arm v4 environment: executable `30a3913b…`, 5 workers + 1 standby, horizon 3,600, no-render and the
  Raphnet bypass;
- uniform-random behaviour, with 120 normal tick-0 episodes per seed;
- E from phase A: cells reached by 1-2 of 20 episodes, in sha256 order, frozen with witnesses;
- 12 held-out episodes;
- the M7s tick convention and ledger;
- P1 identity plus stored-row identity;
- the launch refusals: approval record, coverage over the D: base and every increment, no game process, no gate
  directory;
- replays through the existing verifiers;
- a new verified D: increment afterwards.

| phase | computation | native ticks (cap) |
| --- | --- | ---: |
| P1 identity | 27,521 + 1,548 | 29,069 |
| collection | 3 × 120 × 3,600 | 1,296,000 |
| evaluation | 3 × (20 commanded + 20 scrambled) × 3,600 | 432,000 |
| exact return replays | 3 × 10 × 3,600 | 108,000 |
| exact clear replays | 3 × 2 × 3,600 | 21,600 |
| **total** | | **1,886,669** |

Revision 2's cap was 1,929,869. Dropping S's evaluation and replays saves more than the scrambled episodes cost.

### 9.4 What a native pass would establish

**It would establish** learned, goal-directed return to rare own cells from tick 0, in ≥ 2 of 3 replicates, with exact
replays. That makes stage 2 (H-T2: iterated collection with return plus local exploration) eligible for a separate
design.

**It would not establish:**
- composition in Mario;
- a return rate, speed, or reliability of arrival;
- frontier expansion, crossings, targets or clears;
- iterated improvement;
- other characters;
- superiority over PPO.

A **fail** falsifies learned return from one round of about 108 random episodes, at this network and budget. An
**inconclusive** result means revise, not rerun.

## 10. The remaining decision

**There is one decision: authorise `m7t_accept_v1` exactly as §7 specifies, or stop M7t now.**

Authorising it covers:
- 3 × 20,000 synthetic CPU optimizer steps (plus ≤ 60 smoke steps), 0 native ticks, and the caps of §7.3;
- the definition changes of §6.4, including the S1 relaxation and the withdrawal of S;
- the endpoint of §8.

Amending any of these is the only other input the design needs.

**Recommendation: authorise it.**
- It costs about 5-5.5 CPU hours and no native ticks.
- It is the only way to test composition under the set readout against ground truth.
- Its endpoint rules out another round.

Stopping now instead would rest on §7.7's forecast, which comes from a different goal set, rather than on a test.

**Decision taken (2026-09-29): stop M7t.**
- `m7t_accept_v1` was not authorised and not run.
- No seed was generated, no network was trained or evaluated, and BattleShip was not launched.
- Status: stopped before final acceptance; native eligibility not established. See
  `docs/rl_m7t_closure_2026-09-29.md`.
