# RL learning-setup review (2026-09-27): does the PPO setup give the policy a practical way to learn the crossing?

Bounded, read-only review requested after M7o. Nothing was trained, no game process was launched, no production file
changed, no reward or setting was tuned.

Corrections on user review (2026-09-27, second pass): the first version of this document stated that action
persistence *is* the binding constraint, that the probability of a k-tick sequence follows 0.5^k, and that the v3
input dimensionality and missing normalisation are the proven cause of the saturation. Those were over-claims.
Action persistence is a **hypothesis** about why the first-event rate is zero; the zero rate itself is the measurement.
The probability of a specific sequence is the product of the state-conditioned per-tick probabilities of its actions
and has no general closed form; the figure quoted is an illustration for sequences whose actions are not the mode. The
saturation is measured; its cause is not isolated (input width, absence of running normalisation and the fixed scale
changed together between v1 and v3). The measured findings in section 2 are unchanged. The no-training action-hold
probe that follows from section 6 is registered and reported separately in
[`rl_action_hold_probe_2026-09-27.md`](rl_action_hold_probe_2026-09-27.md); its outcome was **no foothold under hold
lengths 1, 4, 8 and 16** (S2 = 0, S3 = 0 in 400 episodes), so no hold-k learning comparison is proposed. HEAD `88f6e79` (clean), submodules `decomp 3834e22`, `libultraship 805f195`,
`torch 3aa9c97`; no BattleShip or Python process was running. Standing defaults stay as they are: observation
`btt_policy_obs_v3_entities`, reward `btt_reward_v2`, Track 1 `btt_s9_b8_v1`, PPO of `rl/configs/m7n/*.toml`.

Sources verified against the artifacts (all figures quoted in the request matched): `rl_observation_v3_m7n_implementation.md`
section 10, `rl_observation_v3_m7n_sweeps_addendum.md`, `rl_observation_v3_m7n_prefix_feasibility.md`,
`rl_exploration_credit_m7o_assessment.md` sections 8 and 11, `rl_exploration_credit_m7o_{contract,manifest,decision_rule}.json`,
`runs/m7o/campaign/_matrix/analysis_n3.json`, `runs/m7n/campaign/_matrix/analysis_n3.json`.

Evidence used for the new measurements (existing records only):

| evidence | what it gave |
| --- | --- |
| `runs/m7n/campaign/m7n_s{0,1,2}_v3/metrics/rollouts.jsonl`, same for `runs/m7g_k/m7g_s*_v1` and `runs/m7o/campaign/m7o_s*_x1` | SB3 `train/*` statistics of every one of the 600 updates per run (entropy, approx KL, clip fraction, value loss, explained variance) |
| `metrics/episodes.jsonl` of the same runs | 2,608 v3 and 2,604 v1 training episodes with target-break ticks |
| final stochastic evaluation artifacts (`_eval/*/final/stochastic/workers/w*/artifacts/*/actions.jsonl`), 300 v3 + 300 v1 + 300 untrained v3 episodes | per-tick Track 1 actions |
| `runs/m7n/feasibility/prefix/traces/{907d762b,e404fde0}.json.gz` | every raw reply of one seed-1 and one seed-2 final episode: the exact 606-value network inputs were rebuilt with the production `EntityObservationBuilder` (extractor order verified equal to `m7n_obs.flatten`) |
| `runs/m7o/offline/replays/traces/*.json.gz` (200 exact replays of seed-0 final and untrained episodes) joined with their action files | per-tick fighter status + the action chosen at that tick |
| checkpoint sets `ckpt_*` and `final` of the v3 runs, `final` of the v1 runs | network parameters, VecNormalize statistics |

The probe scripts were run from the session scratch directory and are not part of the repository; every quantity below
names the record it was computed from so it can be recomputed.

## 1. Implementation checks (no defect found)

| check | result |
| --- | --- |
| horizon truncation | `btt_parallel.m7_worker` sets `TimeLimit.truncated` and `terminal_observation`; SB3 2.9.0 `collect_rollouts` adds `gamma * V(terminal_obs)` (bootstrap) on truncation and not on a native fall (terminated) - correct |
| fall reward | the -5.0 lands on the terminal step and the fall is a termination (no bootstrap) - correct |
| v3 input order | `CombinedExtractor` concatenation equals `m7n_obs.flatten` (asserted numerically on rebuilt inputs) |
| action distribution | `MultiCategoricalDistribution`: two independent categoricals (9 stick, 8 button) conditioned on the same 64-unit latent; every Track 1 combination reachable |
| hyperparameters | as registered: lr 3e-4 constant, rollout 5 x 1,024, batch 512, 10 epochs (100 gradient steps per rollout, 6,000 per run), gamma 0.999, lambda 0.995, clip 0.2, ent_coef 0, vf_coef 0.5, max_grad_norm 0.5, tanh [64, 64], `norm_obs` False for v3 |
| fresh construction | verified by the campaigns' own digests (not re-verified here) |

## 2. Findings

### 2.1 Temporal credit assignment (measured)

| quantity | value |
| --- | --- |
| discount horizon 1/(1-gamma) | 1,000 ticks |
| GAE horizon 1/(1-gamma*lambda) | 167 ticks; (gamma*lambda)^200 = 0.30, ^400 = 0.09 |
| rollout segment per env | 1,024 ticks; a 3,600-tick episode spans about 3.5 segments (bootstrapped at each cut) |
| inter-break gaps, v3 training (8,990 gaps in 2,608 episodes) | median 263, p75 592, p90 1,171 ticks; 63 % exceed the GAE horizon, 30 % exceed 500, 13 % exceed 1,000 |
| first break | median tick 70 (p90 327) |
| zero-reward tail of horizon episodes | median 2,005 ticks after the last break |
| crossing chain (documented, validation-only timing references) | 181 / 198 ticks from takeoff to left entry in the two validated crossings, then a landing and a break; reward v2 pays nothing before the first left-target break (prefix feasibility report, section 4) |

The critic on the two rebuilt trajectories (final policies of the same seeds):

| | seed 1 final | seed 2 final | untrained |
| --- | --- | --- | --- |
| corr(V, discounted return-to-go) | 0.865 | 0.966 | 0.43 / 0.16 |
| explained variance on the trajectory | 0.73 | 0.93 | 0.13 / 0.02 |
| TD error at the break step (of the +1.0) | +0.62 | +0.67 | +1.21 / +1.19 |
| change of V over the 15 / 60 / 240 ticks before a break | -0.50 / -0.53 / -0.18 | +0.04 / -0.12 / -0.31 | ~0 |

Reading: the global explained variance (0.83 -> 0.95 across training in every run) comes from the slow component of the
return (targets still collectable, time left). The timing of an individual break is still mostly a surprise to the
critic at the end of training: V does not rise in the 15-240 ticks before a break, and 62-67 % of a break's value is
paid as TD error at the break step. Credit for the actions preceding a break therefore travels almost entirely through
GAE with weights (gamma*lambda)^k, i.e. about 0.30 at 200 ticks and 0.09 at 400 ticks. For a several-hundred-tick
reward-free chain such as the crossing this only starts to operate after the chain has paid at least once.

### 2.2 Action execution (measured)

Final stochastic evaluations, 100 episodes per seed (`actions.jsonl`):

| | v3 s0 | v3 s1 | v3 s2 | v1 s0 | v1 s1 | v1 s2 | untrained v3 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| same-action run length, mean / median | 1.69 / 1 | 1.44 / 1 | 1.46 / 1 | 1.95 / 1 | 2.00 / 1 | 2.05 / 1 | 1.01 / 1 |
| share of runs that are a single tick | 0.75 | 0.81 | 0.78 | 0.70 | 0.68 | 0.70 | 0.99 |
| stick-up (U/UL/UR) run length mean / p90 | 3.7 / 9 | 2.8 / 5 | 2.4 / 3 | 6.3 / 13 | 4.8 / 10 | 4.0 / 9 | 1.5 / 3 |
| B held, share of ticks | 0.55 | 0.46 | 0.14 | 0.16 | 0.07 | 0.05 | 0.12 |
| up+B ticks per episode | 812 | 739 | 291 | 417 | 87 | 63 | 130 |
| dominant joint action | R+B 0.18 | U+B 0.16 | neutral+C-left 0.12 | U+A 0.13 | neutral+none 0.12 | neutral+A 0.15 | uniform |
| action-sequence entropy, bits (max 6.17) | 4.35 | 4.59 | 4.41 | 4.61 | 4.67 | 4.60 | 6.15 |

Policy state-dependence on the rebuilt trajectories (nats; maximum 4.277):

| | v3 s1 final | v3 s2 final | v1 s1 final | v1 s2 final |
| --- | --- | --- | --- | --- |
| per-state policy entropy | 2.08 | 1.37 | 1.11 | 1.31 |
| entropy of the episode-marginal action distribution | 3.48 | 3.52 | 3.19 | 3.62 |
| mutual information state -> action | 1.40 | 2.15 | 2.08 | 2.32 |
| mean probability of the modal joint action | 0.41 | 0.54 | - | - |

Jump behaviour, seed-0 final (100 episodes, status trace joined with actions; alignment check: the jump input sits on
the same index as the first jump-squat row in 81 % of 2,444 onsets):

| | seed-0 final | seed-0 untrained |
| --- | --- | --- |
| jump squats per episode | 24.8 | 14.9 |
| P(jump input while idle on the ground) | 0.074 | 0.416 |
| P(jump input while airborne) | 0.70 | 0.43 |
| up-B onsets per episode | 12.4 | 5.4 |
| jump apex above takeoff, median / p90 / max (units) | 1,267 / 2,239 / 3,445 | 1,135 / 2,166 / 3,401 |
| airborne segments after a squat that used the double jump | 81 % | 69 % |

Distinction the request asked for. The action representation is valid: every Track 1 combination is tested, and the
two validated crossings are Track 1 sequences (documented in M7g). Ease of learning a sequence is another matter: the
policy draws a fresh action every native tick from a distribution whose modal joint action has probability 0.41-0.54,
so it switches action on 75-81 % of ticks. The probability of a specific k-tick commitment is the product of the
state-conditioned per-tick probabilities of its actions; for a commitment whose actions are not the mode in the states
it passes through, that product is at most about 0.5^k on these trajectories (an illustration, not a law: a mode-
following sequence can have probability near 1). Sustained inputs are measured to exist where the learned mode already
sustains them (stick-up p90 of 3-9 ticks, mostly through the airborne jump-input habit). Whether this per-tick
randomness is what keeps the crossing from ever being executed is a hypothesis (section 3). What the policies
actually learned is a right-side routine: high-frequency B (fireball) and up-B use, jumps initiated from landings and
dashes rather than from idle, and 5 of 8 breaks in the seed-1 trace within 40 ticks of an up-B onset. None of this is
a crossing; the feasibility report's 50 approaches all attempted the wall from its foot.

### 2.3 Optimisation (measured from `rollouts.jsonl`; deciles of 600 updates)

| | v3 s0 | v3 s1 | v3 s2 | v1 s0 | v1 s1 | v1 s2 |
| --- | --- | --- | --- | --- | --- | --- |
| policy entropy, first -> last decile (nats) | 4.05 -> 1.56 | 3.96 -> 1.95 | 4.05 -> 1.78 | 3.99 -> 1.07 | 4.02 -> 1.11 | 4.06 -> 1.08 |
| final entropy as share of maximum | 0.36 | 0.46 | 0.42 | 0.25 | 0.26 | 0.25 |
| rollouts 401-500 -> 501-600 | 1.76 -> 1.69 | 2.00 -> 1.99 | 2.15 -> 1.85 | | | |
| approx KL per update | 0.009 -> 0.011 | 0.009 -> 0.011 | 0.009 -> 0.010 | 0.008 -> 0.007 | 0.008 -> 0.006 | 0.008 -> 0.006 |
| clip fraction | 0.08 -> 0.11 | 0.08 -> 0.12 | 0.08 -> 0.11 | 0.055 -> 0.057 | 0.056 -> 0.055 | 0.055 -> 0.050 |
| value loss | 0.020 -> 0.006 | 0.021 -> 0.018 | 0.014 -> 0.011 | 0.038 -> 0.007 | 0.026 -> 0.007 | 0.036 -> 0.007 |
| explained variance | 0.83 -> 0.95 | 0.81 -> 0.89 | 0.82 -> 0.96 | 0.77 -> 0.95 | 0.81 -> 0.94 | 0.77 -> 0.95 |
| training targets per episode, first -> last decile | 3.46 -> 5.45 | 3.71 -> 5.43 | 3.19 -> 5.41 | 3.09 -> 4.54 | 3.26 -> 4.65 | 3.22 -> 4.34 |

The optimizer is behaving: update sizes are moderate and stable (KL about 0.01, clip fraction 0.08-0.12), the value
loss falls, the curves rise in every seed, and the policy entropy declines smoothly without collapse (v3 keeps 36-46 %
of the maximum with `ent_coef = 0`, more than v1's 25 %, and is still falling in the last 100 rollouts). Deterministic
collapse (v3 s2 final 0.986, v1 s0 0.507) is a closed-loop fixed point of argmax play: along the stochastic seed-2
trajectory the argmax action changes with the state (25 distinct argmax actions, top share 0.21). Nothing in these
logs says PPO is unsuitable; they say it has converged towards what is rewarded.

### 2.4 Observation use (measured on the rebuilt 606-value inputs)

Input scale at the network (fixed scaling, no normalisation): `segment_geometry` has 34 % of its values above 1 in
magnitude and 14-17 % above 2 (maximum 5.1-6.3); agent displacement / velocity reach 5.6, `pos_y` 4.8 (a fall), target
offsets 6.5. First-layer saturation, share of (state, unit) pairs with |tanh| > 0.95:

| network | pi layer 1 | pi layer 2 | units saturated in > 90 % of states | mean tanh gradient gate (1 - h^2) | vf layer 1 | mean abs pre-activation |
| --- | --- | --- | --- | --- | --- | --- |
| v3 s1 final | 0.84 | 0.46 | 0.375 | 0.093 | 0.89 | 7.5 (p99 24.7) |
| v3 s2 final | 0.82 | 0.46 | 0.297 | 0.101 | 0.86 | 8.4 (p99 29.2) |
| v3 untrained | 0.14-0.17 | 0.06-0.08 | 0.016 | 0.47-0.54 | 0.16-0.19 | 1.0-1.1 |
| v3 s1 at 307,200 transitions | 0.67 | 0.33 | 0.19 | 0.18 | 0.52 | 3.3 |
| v1 s1 final (same trajectory, VecNormalize inputs) | 0.08 | 0.54 | 0.000 | 0.58 | 0.09 | 0.9 |
| v1 s2 final | 0.16 | 0.51 | 0.000 | 0.53 | 0.18 | 1.0 |

The v3 first layer is driven into saturation within the first tenth of training and keeps going (first-layer weight
norm 11.3 -> 18.5); 30-38 % of its 64 units are saturated in more than 90 % of states, and the average gradient gate
through the layer is a tenth of its initial value. The v1 control networks, whose inputs are normalised, do not
saturate at all at the end of training. The saturation is a measured limitation of the trained v3 networks, not a bug,
and its cause is **not isolated**: input width (15 -> 606), the absence of running normalisation and the fixed physical
scale all changed together between v1 and v3, and the growth of the first-layer weight norm under a constant learning
rate contributes as well. The consequence is measured: the layer that reads the geometry behaves largely as a fixed set
of hyperplane indicators, so fine spatial distinctions are represented coarsely and the first layer barely learns after
the first 300,000 transitions. v3 still beat v1 on targets despite this, so it does not by itself explain the missing
crossing. The issue stays documented as unresolved; no network or observation change is proposed here.

Which inputs the trained networks use (variance-weighted squared gradient of the logits / value, share per group; and
KL of the policy when a group is zeroed):

| group | policy share s1 / s2 | value share s1 / s2 | KL(pi, pi with group zeroed) s1 / s2 |
| --- | --- | --- | --- |
| segment_geometry (agent-relative) | 0.51 / 0.68 | 0.37 / 0.26 | 3.23 / 5.29 |
| agent (of which displacement + velocity) | 0.34 (0.27) / 0.23 (0.11) | 0.04 / 0.16 (time 0.14) | 0.21 / 0.18 |
| projectiles | 0.07 / 0.02 | 0.01 / 0.01 | 0.09 / 0.02 |
| targets (right rows / left rows / moving) | 0.045 (0.030 / 0.014 / 0.006) / 0.050 (0.031 / 0.018 / 0.005) | 0.58 (0.57 / 0.01 / 0.06) / 0.57 (0.56 / 0.01 / 0.03) | 0.07 / 0.11 |
| action_class | 0.03 / 0.02 | 0.00 / 0.00 | 0.01 / 0.01 |
| segment_kind (constant per stage) | 0.00 / 0.00 | 0.00 / 0.00 | 0.35 / 0.34 (acts as a bias) |

First-layer weight change since initialisation tells the same story: left-target rows moved 0.4-1.0 against 1.5-2.4
for right-target rows (policy) and 0.4-0.7 against 2.0-3.5 (value). The trained v3 policy is a geometry- and
velocity-conditioned controller whose action barely depends on the target rows; the critic is the opposite, valuing
the right-target rows and the clock. The v3 information is used, but as position, not as target-seeking, and never as
anything about the left side.

## 3. Classification

Verified defects: none. Truncation bootstrap, terminal handling, input order, reward placement and the registered
hyperparameters are correct.

Measured limitations:

1. No positive reward exists before the first left-target break, and no left-side event has ever occurred in tick-0
   play (M7d-M7o) or in 225 continuations from post-sweep states; the approaches attack the wall from its foot, under
   the overhang.
2. Per-tick independent sampling with a modal probability of 0.41-0.54: action changes on 75-81 % of ticks, median
   run length 1; committed multi-tick manoeuvres exist only as learned modes.
3. The critic does not anticipate breaks (62-67 % of a break is TD surprise; no V rise beforehand); 63 % of
   inter-break gaps exceed the 167-tick GAE horizon.
4. v3 first-layer saturation (82-89 %, 30-38 % of units frozen); absent in v1 on the same trajectories; cause not
   isolated (input width, normalisation and scale changed together).
5. The policy's action depends on target rows for about 5 % of its sensitivity; the left-target rows contribute
   1-2 %.

Plausible hypotheses (not measured): that per-tick randomness (finding 2) is what keeps the takeoff-and-traverse from
L1 or the platform from ever being executed; that the up-B habit spends the height tool on right-side targets; that
saturation limits the discrimination of wall-adjacent geometry; that any of these, rather than something unmeasured,
accounts for the zero first-event rate.

## 4. Strongest supported explanation

What is measured: the first-event rate is zero (finding 1), the optimizer and critic are functioning normally on what
is rewarded (section 2.3), and the reward and critic cannot shape a reward-free chain before it has paid at least once
(findings 1 and 3). So the unresolved bottleneck is the discovery of the first left-side event, not credit assignment
or optimisation after it. Why the event never occurs is **not** established. The hypothesis this review advances, and
the one it proposes to test first, is that per-tick independent sampling (finding 2) prevents the multi-tick
commitments the crossing needs from being executed unless they are already the policy's mode. It is preferred over
the alternatives because it is the one measured property that no previous milestone varied: M7m, M7o and the prefix
feasibility check changed where the policy starts or what it is paid for, never how long an action persists. Its status
remains a hypothesis until the probe in section 6 has run.

## 5. One next intervention: a versioned decision period for Track 1 (hold-k)

Change exactly one variable: the policy's decision period. A new Track 1 variant (proposed id `btt_s9_b8_hold<k>_v1`)
in which one policy decision is submitted as the same Track 1 action for k consecutive native ticks. The native
contract is untouched: each of the k submissions is one action consuming one tick, canonical artifacts still record
one native action per tick, replays and verifiers are unchanged. The hold wrapper sits above `EntityObsV3Wrapper` so
the observation builder still processes every reply (displacement, sticky projectile slots, action-class history) and
returns the observation after the k-th tick; the k per-tick v2 rewards are summed; an episode end inside a hold ends
the decision early. Observation v3, reward v2, PPO hyperparameters (in decisions) and the network are unchanged.

Why this variable, from the evidence: it is the one measured property of the setup that no previous milestone varied
and that changes the execution of multi-tick inputs without changing what is rewarded (a hypothesis about its effect
on the first-event rate, section 4). It also changes the learning time scale: the GAE horizon in ticks becomes 167 k
(at k = 4 the share of inter-break gaps beyond it falls from 63 % to 22 %, at k = 8 to 8 %), the episode shortens to
3,600 / k decisions, and the discount horizon in ticks becomes 1,000 k at an unchanged gamma. Keeping every PPO
setting therefore does **not** isolate action persistence; a comparison must state which time-scale it matches
(section 5 of the probe report discusses this). It costs timing resolution, which is exactly what the diagnostic below
measures before anything is trained.

Matched control: the frozen M7n v3 runs (`runs/m7n/campaign/m7n_s{0,1,2}_v3`), reproduced bit-exactly in the M7o
control check. Budget matched in native ticks (3,072,000 per run = 768,000 decisions at k = 4, same game time and
about the same wall clock), same seeds, no in-process evaluation, the M7n tick-0 evaluation protocol (the evaluation
applies the same hold-k to the policy under test; the control's records are reused). Gamma per decision left at 0.999
and recorded as part of the contract (the tick horizon becomes 1,000 k); if the user prefers a matched tick horizon,
gamma_k = 0.999^k is the alternative and must be chosen before registration. Rollout geometry stays 5 x 1,024
decisions. Decision by a pre-registered rule of the M7n family: native-verified clear, replay-verified qualified
crossing or left-target break as discovery gates, then the half-target regression gate, paired by seed.

Not recommended now, recorded for a later network version: fixing the v3 saturation (input normalisation or a
saturation-resistant first layer). It has no no-training diagnostic, its link to discovery is indirect, and it must
not be bundled with the decision-period change if the comparison is to attribute anything.

## 6. Diagnostic before any campaign: hold-k random reachability probe (no training)

Question: does holding actions for k ticks let Track 1 exploration from a normal tick-0 start reach the states the
crossing needs, which per-tick random play (k = 1) never reaches?

Design: uniform random Track 1 actions held for k ticks, k in {1, 4, 8, 16}, 100 fresh-process tick-0 episodes each
(3,600-tick horizon), raw replies kept, staged with the S1-S5 functions of the prefix feasibility harness (S1 approach
x <= -1200; S2 over-ledge y >= 3000 at x <= -1200; S3 `over_wall` entry; S4 `btt_qualified_crossing_v1`; S5 left
break) plus an elevated-state count (y >= 2400), targets and falls. The k = 1 arm is the matched control, and its
expected figures already exist: the M7g/M7n random baseline (100 episodes, `runs/m7g_k/_eval/random_baseline`) broke
3.23 targets, fell 30 times, reached the wall foot (min live x -1650) in 75 % of episodes and produced 0 left entries;
no height is recorded there, so k = 1 is rerun under the probe's own recording. Cost: 400 episodes, about 1.4 M
ticks, roughly 15-25 minutes on three processes; registration of k values, seeds and the rule before launch, as in
M7n/M7o. The evaluator's random mode (`rl/m7_evaluation.py`, per-tick uniform sampling) is the template; the probe
needs a hold-k action source and the position recording, both outside the fingerprinted training code.

Pre-registered reading (the exact registered rule is in the probe registration): a hold length k meets the feasibility
threshold if S2 occurs in at least 3 of its 100 episodes or any raw over-wall entry (S3) occurs. If a longer hold meets
it, the finding is that temporally correlated random actions can reach the relevant region under this probe, not that
PPO will learn a crossing. If none does, the finding is no foothold under the tested hold lengths; Track 1 crossing
controllability is already established by the validated fixtures and is not what the probe tests. Elevated and S1
rates are reported for every k but decide nothing. The validated crossing fixtures are not consulted to design the
probe or choose k; whether they are representable under a selected k may be recorded afterwards as a validation fact
only.

## 7. Evidence not available

Not logged anywhere, so not assessed: gradient norms and per-parameter update sizes; advantage and value-target
statistics per update (only the SB3 batch means exist); per-state action probabilities during training (only 600
batch-mean entropies per run); hidden activations during training (the saturation figures come from two evaluation
trajectories and the saved checkpoints); positions or target diagnostics of training episodes (by design); any
observation of the v1 networks on their own training data. The saturation, sensitivity and critic measurements rest
on two rebuilt trajectories (seeds 1 and 2) and should be read as bounded, not as population estimates.

> Correction (2026-09-28): the row "airborne segments after a squat that used the double jump (81 % / 69 %)" was computed from `jumps_used` reaching 2, which Mario's up-B also sets (`jumps_used = jumps_max`); read it as "used the double jump or an up-B". The genuine-double-jump rate was not recomputed (the script is not in the repo). See docs/rl_geometry_scale_m7p_jump_audit.md.
