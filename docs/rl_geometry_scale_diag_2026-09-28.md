# Geometry-scaling diagnostic (M7p, single bounded run): registration, run, paired measurements, decision

Authorised 2026-09-28 as one bounded diagnostic; no three-seed campaign. Follows
[`rl_v3_saturation_investigation_2026-09-28.md`](rl_v3_saturation_investigation_2026-09-28.md) section 6.
Observation v3 (`btt_policy_obs_v3_entities`) remains the selected default; nothing committed, pushed or branched.

Records: registration (write-once, before launch) [`rl_geometry_scale_diag_registration.json`](rl_geometry_scale_diag_registration.json);
decision (write-once, applied once) [`rl_geometry_scale_diag_decision.json`](rl_geometry_scale_diag_decision.json);
run report `runs/m7p/diag/diag_report.json`; paired analysis `runs/m7p/diag/analysis.json`; control check
`runs/m7p/diag/_control/control_check.json`; run `runs/m7p/diag/m7p_geo4_s0`; evaluation `runs/m7p/diag/_eval/m7p_geo4_s0/final`.
Driver `rl/m7p_geo4_diag.py`; contract `rl/m7p_obs_geo4.py`; profile `rl/configs/m7p/m7p_geo4_s0.toml`.

## 1. The single change (registered)

New, separately versioned observation contract `btt_policy_obs_v3_geo4` (digest `2b984528…`, derived from v3
`4ddc2933…`). Exactly one key changes:

| key | columns | v3 scale | geo4 scale |
| --- | --- | --- | --- |
| `segment_geometry` (32 x 8) | `a_dx, a_dy, b_dx, b_dy, near_dx, near_dy` | native units / 2,000 | native units / 8,000 |
| `segment_geometry` | `vel_x, vel_y` | native units per tick / 50 | native units per tick / 200 |

Unchanged: `segment_kind` (all binary flags incl. present / moving), `agent` (positions, floor_dist, diamond / 2,000;
velocities / 50), `targets`, `projectiles`, `action_class`, masking (masked rows exactly zero under both scales), key
order, shapes (flat 606), stale and displacement rules, the action-class table, both native diagnostics, the network
`btt_policy_net_v3_multiinput_mlp64`, `norm_obs = False`, PPO settings, reward v2, Track 1, N = 5 standby, normal
tick-0 starts, horizon 3,600. Verified offline before registration: the v3 builder is byte-identical to its pre-edit
output on the 2,977-state trace sample; the geo4 builder differs from v3 only in the geometry block, by exactly 1/4
(max abs difference 0 after re-multiplying); the profile's compatibility view differs from `m7n_s0_v3` in
`contracts.observation` only. Code changes: default-preserving hooks (`rl/m7n_obs.py` builder scale parameters and a
wrapper factory method; contract id lists in `experiment_config.py`, `m7_trainer.py`, `m7_evaluation.py`; `m7p` added to
the Phase K pinned-profile exclusion). Unit suites after the edits: `m7n_tests unit` 10 / 11 (the known `unit_matrix`
directory-exists failure), `m7o_tests unit` 7 / 7, `m7g_k_tests unit` 6 / 6.

Per-state L2 norm of the geometry block on the fixed sample: 17.4 (v3) -> 4.35 (geo4); agent 2.66, targets 6.68 (both).

## 2. Control compatibility and the run

Control check on the final code and executable `748dbad9…`: a fresh 102,400-transition run of the M7n seed-0 profile
(`m7o_r1_s0.toml`) reproduced `m7n_s0_v3` bit-exactly (policy and VecNormalize digests at 0 and 102,400, 28 / 28
episode rows equal), 2.0 min. PASS, so `m7n_s0_v3` is the matched control at 307,200 (`ckpt_000307200` and its
registered 60-episode curve label, 3.5667 targets).

Diagnostic run `m7p_geo4_s0` (2026-09-28 02:08 -> 02:18 UTC): guarded training 307,200 transitions in 5.1 min (60
rollouts, 600 PPO updates, 1,045 transitions/s, at most 10 game processes, 0 hard / soft alerts, leak-free), then 60
stochastic + 5 deterministic tick-0 evaluation episodes (4.1 min, every artifact's first action at consumed tick 0,
verified). Engineering checks E1-E8 all passed: exit clean; accounting exact; `ckpt_000000000` equals the fresh
construction **and** the M7n s0 initial set (same seed, architecture and shapes, so both arms start from identical
parameters and diverge from the first rollout); 88 valid training rows (11 falls, 77 horizons), parameters changed and
finite; contracts carry the geo4 id, digest, derivation and both flags; evaluation integrity OK. One attempt, no
relaunch.

## 3. Paired measurements (each arm under its own contract; fixed sample of 33,997 states: A = 6,578 policy-play
states of the two M7n final traces, B = 27,419 random-play states of eight action-hold-probe episodes)

Saturation: sat95 = share of (state, unit) pairs with abs(tanh z) > 0.95; "stuck" = saturated in > 90 % of states at one
sign; "constant" = output std < 0.05 over states.

| checkpoint | arm | actor L1 sat95 all / A / B | actor L1 mean derivative | actor stuck / two-sided / constant | critic L1 sat95 all / A / B | critic L1 mean derivative | critic stuck / two-sided / constant | mean abs z1 actor / critic | actor L2 sat95 | W1 norm actor / critic |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | control v3 | 0.130 / 0.159 / 0.123 | 0.565 | 0.016 / 0 / 0.078 | 0.129 / 0.156 / 0.123 | 0.530 | 0.016 / 0 / 0.047 | 0.91 / 0.97 | 0.039 | 11.3 / 11.3 |
| 0 | geo4 | 0.007 / 0.007 / 0.007 | 0.722 | 0 / 0 / 0 | 0.001 / 0.002 / 0.001 | 0.753 | 0 / 0 / 0 | 0.57 / 0.51 | 0.004 | 11.3 / 11.3 |
| 102,400 | control v3 | 0.381 / 0.444 / 0.365 | 0.366 | 0.094 / 0 / 0.125 | 0.306 / 0.320 / 0.303 | 0.422 | 0.172 / 0.016 / 0.172 | 1.70 / 1.54 | 0.234 | 11.8 / 11.7 |
| 102,400 | geo4 | 0.046 / 0.070 / 0.040 | 0.648 | 0 / 0 / 0 | 0.034 / 0.036 / 0.034 | 0.682 | 0.016 / 0 / 0.047 | 0.72 / 0.65 | 0.089 | 11.8 / 11.5 |
| 204,800 | control v3 | 0.488 / 0.547 / 0.473 | 0.292 | 0.078 / 0 / 0.062 | 0.424 / 0.422 / 0.424 | 0.327 | 0.172 / 0.047 / 0.203 | 2.09 / 1.79 | 0.288 | 12.2 / 11.8 |
| 204,800 | geo4 | 0.118 / 0.197 / 0.099 | 0.563 | 0.047 / 0 / 0.047 | 0.191 / 0.145 / 0.201 | 0.531 | 0.047 / 0 / 0.062 | 0.92 / 1.04 | 0.175 | 12.2 / 12.0 |
| **307,200** | **control v3** | **0.534** / 0.572 / 0.525 | **0.266** | 0.062 / 0.031 / 0.078 | **0.433** / 0.428 / 0.434 | **0.326** | 0.156 / 0.047 / 0.188 | 2.38 / 1.99 | 0.294 | 12.5 / 12.1 |
| **307,200** | **geo4** | **0.146** / 0.205 / 0.132 | **0.518** | 0 / 0 / 0.031 | **0.236** / 0.187 / 0.247 | **0.475** | 0.078 / 0 / 0.062 | 1.03 / 1.20 | 0.246 | 12.6 / 12.2 |

The two arms' first-layer weight norms are the same (12.5 / 12.6 actor, 12.1 / 12.2 critic) and their per-interval
weight-row changes are similar (actor 0.35 / 0.31 / 0.27 control vs 0.39 / 0.32 / 0.30 geo4; critic 0.35 / 0.22 /
0.26 vs 0.29 / 0.31 / 0.27), so the lower saturation comes from the smaller geometry input, not from slower weight
movement; the pre-activations still grow under geo4 (0.57 -> 1.03 actor), about a third as fast in absolute terms.
Saturation is lower on both populations, so it is not a random-play artefact.

Sensitivity on recorded, physically valid pairs (identical state indices in both arms; medians), at 307,200:

| pair type | n | control v3: abs dV / KL / actor L1 dist | geo4: abs dV / KL / actor L1 dist |
| --- | --- | --- | --- |
| target event: consecutive ticks across a break | 43 | 0.732 / 0.0012 / 0.59 | 0.697 / 0.0048 / 0.68 |
| consecutive ticks, no break (control) | 3,000 | 0.002 / 0.0000 / 0.08 | 0.001 / 0.0000 / 0.07 |
| action progress: up-B early vs late, same area | 587 | 0.382 / 0.0342 / 2.88 | 0.417 / 0.0896 / 4.01 |
| up-B early vs early, same area (control) | 800 | 0.391 / 0.0226 / 2.03 | 0.490 / 0.0643 / 2.99 |
| action progress: jump-squat tic 0 vs 2, same place | 140 | 0.037 / 0.0017 / 0.81 | 0.073 / 0.0064 / 1.08 |
| jump-squat tic 0 vs 0 (control) | 174 | 0.036 / 0.0013 / 0.71 | 0.058 / 0.0052 / 1.06 |
| block ablation KL: agent zeroed | all | 0.0061 | 0.0299 |
| block ablation KL: targets zeroed | all | 0.0047 | 0.0254 |
| block ablation KL: segment_geometry zeroed | all | 0.2886 | 0.1337 |

Every registered discrimination margin is retained (all above 0.5 x control; up-B progress KL above its matched
control pairs in both arms). The geo4 policy is more sensitive to the agent and target blocks (about 5x) and less to
the geometry block (0.13 vs 0.29 KL when zeroed) at this point of training; the critic's response to a target
disappearing is the same (0.70 vs 0.73). Squat progress stays barely distinguished in both arms, as at init.

Optimisation over the 60 updates (SB3 `train/*`):

| | control v3 | geo4 |
| --- | --- | --- |
| approx KL, mean | 0.0090 | 0.0083 |
| clip fraction, mean (last 20) | 0.083 (0.088) | 0.072 (0.084) |
| value loss, mean | 0.0202 | 0.0211 |
| explained variance, first 10 -> last 10 (last 20 mean) | 0.60 -> 0.79 (0.85) | 0.49 -> 0.92 (0.86) |
| policy entropy, first -> last update (nats) | 4.27 -> 3.85 | 4.27 -> 3.84 |
| all losses finite | yes | yes |
| gradient norms, per-parameter update sizes | UNAVAILABLE (not logged by SB3; the historical control cannot be re-instrumented) | UNAVAILABLE (same) |
| available gradient proxy: median W1 row change per interval | above | above |

Registered 60-episode tick-0 regression check (stochastic, seed 12345, metrics on):

| | control curve label at 307,200 | geo4 final |
| --- | --- | --- |
| mean targets (60 episodes) | 3.5667 | 3.8833 (histogram 3: 13, 4: 41, 5: 6) |
| difference | | +0.317 (approx. standard error 0.10; band 0.5, stop-only) |
| falls / clears / left entries | 13 / 0 / 0 | 3 / 0 / 0 |
| deterministic play (5 episodes) | 0 targets | 0 targets |

Training behaviour (descriptive, never a check): 88 episodes, mean 3.53 tracker targets, 11 falls (control at the
same point: 3.57 mean targets over its first rollouts; its training rows are in `m7n_s0_v3/metrics/episodes.jsonl`).

## 4. Decision (frozen rule applied once)

Engineering OK; no gameplay regression (+0.317, inside the band on the non-regression side); no optimisation regression
(last-20 clip fraction 0.084, explained variance 0.86, approx KL 0.009, finite); discrimination preserved (6 / 6
registered checks); saturation reduced by the registered margins (actor 0.534 -> 0.146, margin 0.15; critic 0.433 ->
0.236, margin 0.10). **Outcome: `diagnostic_pass`.**

What this means, exactly as registered: in one seed at 307,200 transitions, scaling only the `segment_geometry` block
by 1/4 lowered first-layer saturation of both networks without losing the tested state discrimination and without
destabilising optimisation. It is **not** evidence of improved crossing or clear performance (0 clears, 0 left entries,
the +0.317 targets is within the registered band's uncertainty and the check was stop-only), not evidence about 3 M
transitions, and not evidence about other seeds. Per the registration it makes a larger comparison **eligible as a
separate decision**; it does not authorise one, and nothing here tunes the factor, adds seeds or extends the budget.

## 5. Whether the evidence justifies considering a larger comparison

It justifies *considering* one, and no more: the concrete mechanism identified by the investigation (geometry block
norm dominating the first layer) responds to the one-block rescale as predicted, the tested discrimination margins hold,
and the run is otherwise indistinguishable from the control in optimisation statistics. The evidence remains
insufficient on every question a comparison would have to answer: whether the lower saturation persists to 3,072,000
transitions (the control reached 0.53 by 307,200 and 0.77 by the end; geo4's pre-activations are still growing),
whether it changes target counts, crossings or clears (one seed, 60 episodes, no discovery event), and whether any
effect survives across seeds. If a comparison is considered, the natural form is the M7n protocol (three seeds,
3,072,000 transitions, tick-0 evaluation, the frozen M7n v3 runs as controls since the initial parameters are
identical), with the saturation, discrimination and optimisation measurements of this diagnostic repeated at every
curve checkpoint; it would be a separate registration and a separate decision.
