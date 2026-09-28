# v3 first-layer tanh saturation: bounded offline investigation (2026-09-28)

Read-only follow-up to [`rl_learning_setup_review_2026-09-27.md`](rl_learning_setup_review_2026-09-27.md) section 2.4,
on the user's request to establish whether the measured saturation is a practical learning limitation before any network
or observation change. Existing checkpoints and raw-reply records only; no native run, no training, no production-code
edit. Observation v3, reward v2, Track 1 and all frozen evidence untouched. The analysis scripts ran from the session
scratch directory; every figure names its population and checkpoint so it can be recomputed.

## 0. Sample population, thresholds, aggregation

| item | value |
| --- | --- |
| fixed observation sample | 33,997 states, exact 606-value v3 inputs rebuilt with the production `EntityObservationBuilder` from raw replies (extractor order verified equal to `flatten`) |
| population A (policy play) | 6,578 states: the two preserved M7n final episodes with every raw reply (`907d762b` seed 1, 2,977 states; `e404fde0` seed 2, 3,601), both early-sweep episodes |
| population B (ordinary tick-0 play, random) | 27,419 states: 8 action-hold-probe episodes at k = 1 (uniform per-tick random Track 1), raw replies kept by the probe |
| coverage limitation | no raw-reply record of ordinary *trained-policy* play exists except A (the M7o and feasibility traces are compact rows); B is physically valid but random behaviour, mostly floor-level; all states live, none stale; 14 of 20 action classes occur |
| checkpoints | all 30 `ckpt_*` (every 102,400 transitions) + `final` of `m7n_s{0,1,2}_v3`; actor (`policy_net`) and critic (`value_net`) separately, layers 1 and 2 |
| saturation thresholds | sat95: abs(tanh z) > 0.95, i.e. abs(z) > 1.832, derivative 1 - h^2 < 0.0975. sat99: abs(tanh z) > 0.99, abs(z) > 2.647, derivative < 0.0199 |
| aggregations | share over all (state, unit) pairs; per unit, the share of states saturated; "stuck" = saturated in > 90 % of states AND the same sign in > 99 % of states; "two-sided" = saturated in > 90 % of states with both signs occurring; "effectively constant" = std of the unit's output over states < 0.05 |

## 1. The measurement (final checkpoints, whole sample)

| seed / net | mean abs z1 (p90, p99) | sat95 L1 | sat99 L1 | mean derivative L1 | units saturated > 90 % | of which stuck (sign-constant) | two-sided | effectively constant | sat95 L2 | sat95 on A / on B |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s0 actor | 5.6 (11.7, 21.0) | 0.77 | 0.68 | 0.12 | 0.20 | 0.125 | 0.08 | 0.06 | 0.46 | 0.81 / 0.77 |
| s1 actor | 6.9 (14.0, 22.4) | 0.82 | 0.75 | 0.10 | 0.28 | 0.16 | 0.125 | 0.08 | 0.46 | 0.85 / 0.82 |
| s2 actor | 6.9 (14.7, 24.7) | 0.80 | 0.72 | 0.11 | 0.31 | 0.19 | 0.125 | 0.06 | 0.49 | 0.83 / 0.80 |
| s0 critic | 5.0 (9.3, 15.1) | 0.77 | 0.71 | 0.14 | 0.66 | 0.59 | 0.06 | 0.42 | 0.37 | 0.74 / 0.77 |
| s1 critic | 9.1 (16.9, 25.9) | 0.91 | 0.87 | 0.05 | 0.86 | 0.70 | 0.16 | 0.58 | 0.45 | 0.90 / 0.91 |
| s2 critic | 6.0 (11.3, 16.1) | 0.84 | 0.77 | 0.10 | 0.72 | 0.56 | 0.16 | 0.47 | 0.40 | 0.86 / 0.83 |
| untrained (all seeds) | 0.9-1.0 (2.0, 2.9-3.3) | 0.11-0.16 | 0.01-0.04 | 0.51-0.57 | 0.00-0.016 | 0.00-0.016 | 0 | 0.05-0.09 | 0.04-0.08 | - |

Distinction the request asked for: for the **actor**, most saturation is per-state (77-82 % of pairs) while only
12.5-19 % of units are stuck at one sign; a further 8-12.5 % are saturated in both directions (they act as sign
detectors, not constants); only 6-8 % of units are effectively constant. For the **critic** the picture is different:
56-70 % of its first-layer units are stuck at one sign and 42-58 % are effectively constant. The review's earlier
"30-38 % of units frozen" figure (from two trajectories, actor) corresponds to 20-31 % on this larger sample; the
per-state saturation figures are unchanged. Saturation is the same on policy play (A) and random play (B), so it is
not an artefact of unusual states.

## 2. When and where it develops (fixed sample, all seeds)

| checkpoint | actor sat95 L1, s0 / s1 / s2 | actor units > 90 % | critic sat95 L1 | critic units > 90 % | actor mean abs z1 | actor W1 Frobenius norm |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 0.13 / 0.11 / 0.13 | 0.02 / 0.02 / 0.02 | 0.13 / 0.16 / 0.14 | 0.02 / 0.00 / 0.02 | 0.9-1.0 | 11.3 |
| 102,400 | 0.38 / 0.45 / 0.36 | 0.09 / 0.11 / 0.05 | 0.31 / 0.39 / 0.28 | 0.19 / 0.22 / 0.125 | 1.6-1.9 | 11.8 |
| 307,200 | 0.53 / 0.62 / 0.57 | 0.09 / 0.16 / 0.09 | 0.43 / 0.55 / 0.45 | 0.20 / 0.27 / 0.23 | 2.4-2.9 | 12.5-12.7 |
| 614,400 | 0.63 / 0.72 / 0.68 | 0.125 / 0.27 / 0.20 | 0.67 / 0.63 / 0.56 | 0.55 / 0.44 / 0.375 | 3.1-3.9 | 13.4-13.6 |
| 1,536,000 | 0.77 / 0.77 / 0.77 | 0.25 / 0.27 / 0.22 | 0.77 / 0.86 / 0.73 | 0.63 / 0.77 / 0.55 | 4.7-5.5 | 15.5-15.8 |
| final (3,072,000) | 0.77 / 0.82 / 0.80 | 0.20 / 0.28 / 0.31 | 0.77 / 0.91 / 0.84 | 0.66 / 0.86 / 0.72 | 5.6-6.9 | 18.5-18.7 |

Half of the final actor saturation is present at the first checkpoint (3 % of the budget) and two thirds by 10 %; it
then creeps for the rest of training while the mean pre-activation keeps growing roughly linearly (0.9 -> 5.6-6.9).
The critic starts slower and ends more saturated, with most of its units stuck. Layer 2 saturates far less (actor
0.46-0.49, critic 0.37-0.45). Biases stay tiny (norm 0.17-0.37); the growth is in the weights.

Units are not permanently stuck: 11-16 actor units and 25-36 critic units per seed were saturated in > 90 % of states
at some checkpoint and later fell below 50 %. Of the units saturated at 307,200, about half of the actor's (3/6, 5/10,
2/6) and nearly all of the critic's (10/13, 16/17, 14/15) were still saturated at the end.

Plasticity (median change of a unit's first-layer weight row per 102,400 transitions):

| seed / net | early (first 3 intervals) | late (last 5) | late, units saturated > 90 % | late, units < 50 % | corr(saturation share, late change) |
| --- | --- | --- | --- | --- | --- |
| s0 actor | 0.31 | 0.24 | 0.12 (n = 13) | 0.25 (n = 2) | -0.55 |
| s1 actor | 0.33 | 0.24 | 0.12 (n = 18) | - (n = 0) | -0.55 |
| s2 actor | 0.32 | 0.24 | 0.10 (n = 20) | 0.25 (n = 2) | -0.66 |
| s0 critic | 0.28 | 0.09 | 0.009 (n = 42) | 0.27 (n = 14) | -0.74 |
| s1 critic | 0.26 | 0.19 | 0.12 (n = 55) | 0.38 (n = 7) | -0.48 |
| s2 critic | 0.26 | 0.17 | 0.06 (n = 46) | 0.35 (n = 10) | -0.58 |

Saturated actor units keep moving at about half the rate of unsaturated ones; the critic's saturated units in seed 0 are
close to frozen (0.009 per interval). The first layer as a whole still changes late in training.

## 3. Feature and weight audit

Inputs against the contract (33,997 states): every value is within the documented fixed scaling and nothing violates
the contract. Masked segment, target and projectile rows are exactly zero (0 violations); `segment_kind` is constant
across states as designed; the action-class row is a valid one-hot in every state; agent extremes are real recorded
kinematics (displacement / air velocity up to 5.61 = 280 units per tick on 3.3 % of states, target offsets up to 6.7 =
13,400 units when the fighter is far off the stage). No concrete scaling defect was found.

What does stand out is a block-norm imbalance built into the fixed scaling, and what training did with it:

| block | dims | per-state L2 norm, mean (max) | share of values with abs > 1 | constant columns | share of Var(z1), untrained | share of Var(z1), final actor | mean abs contribution to z1, untrained -> final actor | column-norm growth |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| segment_geometry | 256 | 17.4 (45.6) | 0.29 | 111 of 256 (zero velocities of static segments, absent rows) | 0.76-0.84 | 0.78-0.79 | 0.74-0.87 -> 4.4-5.3 | 0.46 -> 0.65-0.67 |
| segment_kind (constant) | 224 | 7.1 (constant) | 0 | 224 | 0 | 0 | 0.33 -> 0.9-1.2 (acts as the effective bias; the bias itself is 0.02) | 0.46 -> 0.47 |
| targets | 50 | 6.7 (16.7) | 0.17 | - | 0.10-0.12 | 0.01 | 0.3 -> 0.8-0.9 | 0.46 -> 0.77-0.79 |
| agent | 28 | 2.7 (10.1) | 0.04 | 3 (carry_x, c_ceil, cliff_hold; diamond fields constant) | 0.05-0.07 | 0.01 | 0.12 -> 0.45-0.51 | 0.45 -> 1.18-1.30 |
| action_class | 20 | 1.0 | 0 | - | 0.01 | 0.00 | 0.05 -> 0.16 | 0.46 -> 1.17 |
| projectiles | 28 | 0.4 (6.1) | 0.004 | - | 0.01 | 0.00 | 0.02 -> 0.09 | 0.46 -> 1.1-1.2 |

The geometry block carries 76-84 % of the first layer's pre-activation variance **already at initialisation**, because
its per-state norm is 6.5 times the agent block's and 2.6 times the target block's under the shared /2,000 scaling and
orthogonal init. Training kept that share (78-79 %) while multiplying the block's mean contribution by 6 with only a
1.4-fold column-norm growth: the learned rows aligned with the geometry input directions. The critic additionally built a
large constant offset out of the constant `segment_kind` block (1.3-2.2). Correlation, not proof: this shows where the
large pre-activations come from, not that they are harmful.

## 4. Functional consequences on recorded, physically valid state pairs (final checkpoints; untrained for reference)

Medians over pairs; hidden distances are L2 over 64 units; KL is between the two states' action distributions.

| pair type | n | actor L1 dist, final (untrained) | critic L1 dist | KL, final (untrained) | abs dV, final (untrained) |
| --- | --- | --- | --- | --- | --- |
| target break: consecutive ticks across a break (target row masked) | 43 | 0.95-1.09 (0.45-0.48) | 1.03-1.22 | 0.017-0.055 (0.000) | 0.70-0.82 (0.04-0.06) |
| consecutive ticks, no break (control) | 3,000 | 0.11-0.13 (0.03-0.04) | 0.01-0.02 | 0.000 | 0.001 |
| up-B early (tics 5-10) vs late (20-30), same area | 587 | 3.6-4.6 (1.7-2.2) | 1.4-2.1 | 0.29-2.76 (0.000) | 0.80-1.21 (0.09-0.40) |
| up-B early vs early, same area (control) | 800 | 2.2-3.1 (1.3-1.5) | 1.3-1.8 | 0.12-0.35 (0.000) | 0.70-0.86 (0.07-0.18) |
| jump-squat tic 0 vs tic 2, same place | 140 | 0.79-1.05 (0.59-0.68) | 0.40-0.77 | 0.024-0.032 (0.000) | 0.05-0.16 |
| jump-squat tic 0 vs tic 0, same place (control) | 174 | 0.74-0.91 (0.57-0.67) | 0.32-0.65 | 0.019-0.024 (0.000) | 0.04-0.15 |
| same floor spot, same targets, platform phase differs by >= 1,500 | 6 | 0.31-0.85 | 0.47-0.57 | 0.004-0.031 | 0.10-0.47 |
| same floor spot, platform phase within 150, 360 ticks apart (control) | 600 | 0.70-1.14 | 0.59-1.65 | 0.015-0.099 | 0.06-0.28 |

Readings. A target disappearing is clearly distinguished: the critic drops its value by 0.70-0.82 of the target's 1.0
and the actor's distribution moves 50-100 times more than between ordinary consecutive ticks. Progress inside an up-B is
distinguished by the actor (KL 0.29-2.76 against 0.12-0.35 for matched early-vs-early pairs). Progress inside a jump
squat is barely distinguished (KL 0.024-0.032 against 0.019-0.024), which matches the review's finding that jump inputs
are not held through the squat; the untrained network did not separate it either, so this is not something saturation
removed. The platform-phase test is **inconclusive**: only 6 valid far pairs exist in the sample (random play rarely
returns to the same floor spot with the platform 1,500 units away), and the near-phase control moves the network as much
as the break pairs because those pairs also differ in time. Hidden-code resolution: the actor's first layer still produces
3,475-5,284 distinct sign patterns over the 34k states (untrained 2,392-4,882) and 8,700-10,500 saturated ternary codes;
the critic's first-layer sign code collapsed to 167-640 patterns (untrained 2,610-3,875) while its explained variance is
0.89-0.96, so the critic's value is carried by a few unsaturated units and by layer 2.

## 5. Conclusion

Strongest supported conclusion: the saturation is real, reproducible across seeds and populations, develops within the
first 3-10 % of training, and comes from the geometry block's dominant input norm combined with learned weight alignment
rather than from any contract violation, masking error or input outlier. Its measured cost is reduced first-layer
plasticity (gradient gate 0.05-0.14 against 0.51-0.57 at init; saturated actor rows move at half the rate of unsaturated
ones; the critic's saturated rows in seed 0 are almost frozen) and a coarse critic first-layer code. Its measured
non-cost is that the trained networks still distinguish the meaningful recorded state changes that could be tested
(target removal, up-B progress) with margins far above tick-to-tick noise, the critic reaches explained variance 0.9, and
the learning curves were still rising at the end of every run. **Whether it is a practical learning limitation is not
established.** It is a representation / optimisation hypothesis, not a bug: the fixed scaling honours the contract, and
the imbalance between blocks is a design consequence of a shared length scale over 256 geometry values.

Not established either way, and not to be assumed: that unsaturated activations would play better, or that saturation
explains the absence of crossings (the review's other measured items stand independently).

## 6. One recommendation: a capped diagnostic on a single block rescale, for later approval

Change exactly one thing: the `segment_geometry` block's fixed scale (lengths /8,000 and velocities /200 instead of
/2,000 and /50 for that block only), so its per-state norm (17.4 -> 4.4) is comparable to the target block (6.7) and the
agent block (2.7). Everything else identical: observation keys, masking, reward v2, Track 1, the tanh [64, 64] network,
`norm_obs = False`, PPO settings, N = 5 standby. This is a separately versioned observation contract (a new id; v3 is
untouched and stays the standing default). No normalisation layer, activation change, encoder change, reward change or
action-frequency change is bundled with it.

Diagnostic: one run, seed 0, capped at 307,200 transitions (60 rollouts, 600 PPO updates, the M7o pilot geometry),
about 6 minutes of training plus a 60-episode stochastic tick-0 evaluation (about 5 minutes). Matched control: the M7n
seed-0 run's first 307,200 transitions (`ckpt_000307200`, its 60-episode curve label 3.5667 targets, and its first 60
update records), which the M7o control check reproduced bit-exactly on the current code. Registered before launch:
profile, code and executable identity, the fixed 33,997-state sample (rebuilt under the new scale for the experimental
arm), and the reading rule.

What it measures beyond saturation, each compared with the control at the same transition count:

1. Saturation and plasticity: sat95 / mean derivative / stuck-unit share for actor and critic on the fixed sample at
   0, 102,400, 204,800 and 307,200 (control: actor 0.53, critic 0.43 at 307,200); first-layer row-change rate per interval.
2. Preserved feature sensitivity: the recorded-pair margins of section 4 (break pairs abs dV and KL, up-B progress KL
   against its control pairs) and the per-block ablation KL for the agent and target blocks; the diagnostic fails this
   check if any margin falls below the control's at 307,200.
3. Stable optimisation: approx KL, clip fraction, value loss and explained variance per update against the control's
   first 60 updates (control: KL about 0.009, clip about 0.08, EV 0.83 -> 0.90); a check fails on a sustained
   departure (for instance clip fraction above 0.2 or explained variance below 0.5 over the last 20 updates).
4. Learning behaviour: training targets per rollout decile and the 60-episode stochastic label at 307,200 against the
   control's 3.5667; with a standard error of about 0.3 targets this is a stop-only regression check (more than 0.5
   below stops), not evidence of benefit.

Reading, fixed before the run: the diagnostic can show that the rescale lowers saturation while keeping sensitivity and
optimisation stable, or that it does not; it cannot show a gameplay benefit, and a pass would only make a three-seed
comparison eligible as a separate decision. The rescale may only delay saturation (Adam's per-step weight change is
roughly independent of input scale, so the same pre-activations are reachable with larger weights); measuring whether
it delays or prevents it is part of what the diagnostic is for. If the user prefers no change on the present evidence,
that is equally defensible: nothing measured here shows that the saturated networks fail to represent what they are
asked to learn.
