# RL M7e Phase A: v2 idle diagnosis and the extended-training proposal

Companion to the generated data report
[`rl_v2_idle_diagnosis_m7e.md`](rl_v2_idle_diagnosis_m7e.md) and its JSON.
That document holds the measurements; this one interprets them, ranks the
root-cause hypotheses, and pre-registers the next controlled experiment.

Nothing here was trained, tuned or launched. No reward was created or
changed. No native or submodule file was touched. No M7d result was
modified: 508,330 files under `runs/m7d`, `runs/m7a_*` and `runs/m7c_*` were
fingerprinted before and after this work and **0 changed, 0 were removed and
0 were added**; the 13 pre-existing M7 documents are byte-identical; the
user's `BattleShip.cfg.json` sha256 is unchanged at
`1b29d91b80051a13...`.

## Scope

- Track 1 only.
- Frozen contracts unchanged: `btt_s9_b8_v1` (MultiDiscrete([9, 8]), 72
  actions), the M5 flat 15-value float32 observation, observation-only
  VecNormalize with reward normalisation off, N=5 with standby, at most 10
  game processes, process restart as episode reset, cached non-consuming
  tick-0 reset observation, first action after reset consumes tick 0.
- `btt_reward_v1` and `btt_reward_v2` are both preserved unchanged. No `v3`.
- No native RNG state was introduced, inspected, logged, validated,
  controlled, compared or hashed, here or in anything proposed below.
- The authoritative replay baseline is untouched and restated exactly:
  `tas_input_2/mario_743.btti`, 468 source rows, checksum `0x93E9EFB4`,
  `completion_time_passed = 446`, `completion_input_tick = 447`, 447
  interactive actions submitted, last `consumed_tick` 446, final
  `step_count` 447, 21 source rows not submitted. The two clocks are
  reported separately and neither is collapsed or decremented. The TAS is
  not representable through Track 1 and is never approximated through it.

## 1. The M7d idle metric measures episode length as much as it measures idling

M7d's `idle` flag is, verbatim:

> `idle(e) = [end(e) = horizon] and [tail(e) >= 1800]`, where
> `tail(e) = L - (b_T + 1)` if at least one target broke, else `L`.

It has an **absolute** 1,800-tick threshold. An episode that ends at tick 917
cannot trip it no matter how inert it is. M7d said so in its own limitations,
and the M7e measurements quantify how much of `I = +0.433` that accounts for.

The **proportional** version of the same quantity,
`tail_frac(e) = tail(e) / L(e)`, is the share of the episode spent after the
last target. Final stochastic, v1 → v2:

| seed | tail fraction v1 | tail fraction v2 | M7d idle rate v1 | M7d idle rate v2 |
| --- | --- | --- | --- | --- |
| 0 | 0.475 | 0.485 | 0.22 | 0.54 |
| 1 | 0.418 | 0.460 | 0.00 | 0.45 |
| 2 | 0.372 | 0.634 | 0.00 | 0.53 |

At seeds 0 and 1 the two contracts spend **the same proportion** of the
episode in their no-progress tail (0.475 vs 0.485; 0.418 vs 0.460), while the
M7d idle rate reads 0.22 vs 0.54 and 0.00 vs 0.45. Only seed 2 shows a real
proportional gap (0.372 vs 0.634), and seed 2's v1 dies at a mean length of
917 ticks. The `+0.433` idle difference that disqualified v2's fall path is,
at two of three seeds, a restatement of "v2's episodes are longer".

**This does not overturn the M7d decision.** v2 was selected through
`v2_more_targets`, not through the fall path, and the idle condition only
blocked a path that did not carry the classification. What it does change is
the standing of limitation 4 in the M7d recommendation: "v2 substantially
increases idle and horizon behaviour" is accurate as written about the
registered metric, and misleading if read as "v2 spends proportionally more
of its episode doing nothing". It does not, at two of three seeds.

## 2. The diagnosis

### 2.1 Directly measured facts

**The tail is not inactive, in any action-level sense.** Over the 100 final
stochastic episodes of each v2 seed, measured on the stored canonical native
actions (all 3,588 model evaluation episodes have their full action stream
preserved):

| seed | tail joint entropy (bits, max 6.170) | tail switch rate | tail long-run share | tail full-neutral share |
| --- | --- | --- | --- | --- |
| 0 | 5.109 | 0.810 | 0.000 | 0.007 |
| 1 | 4.985 | 0.881 | 0.000 | 0.066 |
| 2 | 5.285 | 0.888 | 0.000 | 0.004 |

`long_run_share` is the fraction of ticks inside a maximal run of ≥ 60
identical actions. It is **0.000** in every v2 seed: not one tick of any tail
sits in a 60-tick repeat. The action changes on 81–89 % of ticks, and the
policy emits literally-no-input (neutral stick, no button) on 0.4–6.6 % of
tail ticks. The mean longest single repeat in a whole episode is 7.1–15.6
ticks.

**No zero-target inactivity.** `zero_target_horizon_rate` is **0.000** at all
three v2 seeds in the final stochastic sets. The single 0-target episode
anywhere in those 300 (seed 2) ended in a *fall*, not at the horizon.

**Progress does not stop; its rate collapses, and it collapses identically
under both contracts.** Targets broken per 600-tick band, over the episodes
that reached that band (seed 0, the only seed where v1 survives far enough
to compare):

| band | s0_v1 (n reaching) | s0_v2 (n reaching) |
| --- | --- | --- |
| 0–600 | 2.400 (100) | 2.520 (100) |
| 600–1200 | 1.076 (92) | 0.620 (100) |
| 1200–1800 | 0.560 (84) | 0.270 (100) |
| 1800–2400 | 0.348 (69) | 0.130 (100) |
| 2400–3000 | 0.173 (52) | 0.200 (100) |
| 3000–3600 | 0.119 (42) | 0.210 (100) |

Both fall by roughly 12–20× from the first band to the last. v1 is not
immune to the collapse; it simply dies before the flat part is long enough
to register as a tail. And v2's last band is **not zero** — 0.21 targets per
100 episodes-band at seed 0, with 20 % of episodes still scoring there.

**The argmax policy is a different animal from the sampled one.** Same
models, deterministic evaluation, `collapse_share = max_run / L`:

| run | max run (ticks) | collapse share | joint entropy (bits) | targets |
| --- | --- | --- | --- | --- |
| m7d_s0_v1 | 1886 | 0.561 | 1.815 | 2 |
| m7d_s0_v2 | 3402 | 0.945 | 0.477 | 2 |
| m7d_s1_v1 | 3245 | 0.901 | 0.676 | 2 |
| m7d_s1_v2 | 354 | 0.098 | 2.989 | 3 |
| m7d_s2_v1 | 1624 | 0.451 | 1.700 | 0 |
| m7d_s2_v2 | 3305 | 0.918 | 0.464 | 1 |

Five of six argmax policies hold one action for 45–95 % of the episode.
`m7d_s1_v2` is the only exception, and it is also the best deterministic
result in the whole matrix (3 targets).

**The optimizer had not converged at 1,024,000 transitions.** `ent_coef` is
`0.0` in every run, so nothing holds the policy entropy open; `H` is where
the optimizer left it. `H_max = ln 9 + ln 8 = 4.2767` nats.

| run | H start | H end | fraction of max | slope /1e6 | last-third slope /1e6 | deceleration | explained variance |
| --- | --- | --- | --- | --- | --- | --- | --- |
| m7d_s0_v1 | 4.273 | 1.823 | 0.426 | −2.353 | −1.532 | 0.65 | 0.927 |
| m7d_s0_v2 | 4.273 | 2.448 | 0.572 | −1.852 | −1.967 | **1.06** | 0.923 |
| m7d_s1_v1 | 4.273 | 2.409 | 0.563 | −1.959 | −1.858 | 0.95 | 0.847 |
| m7d_s1_v2 | 4.273 | 2.816 | 0.658 | −1.365 | −0.817 | 0.60 | 0.897 |
| m7d_s2_v1 | 4.272 | 1.819 | 0.425 | −2.448 | −2.628 | **1.07** | 0.863 |
| m7d_s2_v2 | 4.272 | 2.786 | 0.651 | −1.402 | −1.851 | **1.32** | 0.879 |

Every v2 run ends at 57–66 % of maximum entropy, still concentrating, with
two of three *accelerating* over the final third. Explained variance over the
final third is 0.88–0.92 for v2: the critic is fitting the return, so the learning signal is being
used, not lost.

**Where the character actually is (Phase A4 replay).** The stored records
hold only the first and last observation, so 15 selected episodes were
re-submitted to fresh processes from tick 0 with their own canonical native
actions. All 15 reproduced their record exactly — same targets, same
break ticks, `consumed_tick` aligned throughout, enforced by
`run_artifacts.resubmit_actions`. Tail segments:

| role | run | tail ticks | tail path length | tail x range | distinct 100-cells | stationary share |
| --- | --- | --- | --- | --- | --- | --- |
| worst_idle_v2 | m7d_s0_v2 | 3414 | 99,929 | 4,219 | 624 | 0.43 |
| worst_idle_v2 | m7d_s1_v2 | 3290 | 95,153 | 3,638 | 467 | 0.32 |
| worst_idle_v2 | m7d_s2_v2 | 3434 | 86,082 | 3,771 | 520 | 0.48 |
| deterministic_v2 | m7d_s0_v2 | 3508 | 6,572 | 2,146 | 53 | 0.97 |
| deterministic_v2 | m7d_s1_v2 | 1647 | **0** | **0** | **1** | **1.00** |
| deterministic_v2 | m7d_s2_v2 | 3549 | 3,148 | 1,482 | 29 | 0.98 |

The worst *sampled* "idle" episode of each seed travels 86,000–100,000 units
and visits 467–624 distinct 100-unit cells during the tail the metric calls
idle. The *argmax* policy of seed 1 travels **zero units across 1,647
ticks** — one cell, perfectly motionless.

**Stage extent.** Whole-episode horizontal range in the replays, and the
final position of all 600 final-stochastic episodes:

| | replayed x max (v1) | replayed x max (v2) | final x median (v1, n=100) | final x median (v2, n=100) |
| --- | --- | --- | --- | --- |
| seed 0 | 5,797 | 1,950 | 4,824 | 667 |
| seed 1 | 5,894 | 1,950 | 5,791 | 354 |
| seed 2 | 8,435 | 2,089 | 5,164 | 463 |

Every v1 run's modal final-position bin sits at `y = −9,800` — below the
stage, which is the fall. Every v2 run's sits at `y = −1,600` or `−2,600`,
on it. v2 confines itself to roughly `x ∈ [−1650, +2200]`; v1 ranges out to
`x ≈ 5,800–8,400` and dies there.

**Survival-matched progress.** Restricting both arms to the episodes that
actually reached tick `W` removes the confound M7d flagged:

| seed | W | v1 survivors | v2 survivors | v1 targets < W | v2 targets < W | v2 − v1 |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 1800 | 84 | 100 | 3.952 | 3.410 | **−0.542** |
| 0 | 3600 | 42 | 100 | 4.262 | 3.950 | **−0.312** |
| 1 | 1800 | 31 | 100 | 3.290 | 3.450 | +0.160 |
| 1 | 3600 | 1 | 100 | 4.000 | 4.160 | +0.160 |
| 2 | 1800 | 1 | 86 | 2.000 | 3.593 | (1 survivor) |
| 2 | 3600 | 0 | 73 | — | 3.918 | (no survivors) |

At seed 0 — the only seed where enough v1 episodes survive to compare — v1
breaks **more** targets than v2 at every window from 900 ticks onward, and
the survival-matched gap (−0.31 to −0.66) is larger than the raw per-episode
gap (−0.36). At seeds 1 and 2, v1 has 0–1 survivors past 3,000 ticks, so
v2's `+0.65` and `+0.40` are substantially *survival* effects: conditional on
surviving to the horizon at seed 1, the two are 4.00 vs 4.16.

**The 6-target ceiling.** No episode anywhere in M7d — 6,108 of them — broke
more than 6 of 10 targets. The replay shows 6 targets are obtainable without
leaving `x ≤ 1,950` (seed 0 v2) and also with a route reaching `x = 5,797`
(seed 0 v1). v1 *has* the horizontal range v2 lacks and still caps at 6.

### 2.2 Evidence-supported inference

- The v2 tail is **stochastic exploration without progress**: continued,
  near-uniform, vigorous movement over a bounded region that has already
  yielded its targets. It is not stuck, not looping on a held input, and not
  standing still. Support: entropy 4.99–5.29 of 6.17 bits, switch rate
  0.81–0.89, long-run share 0.000, tail path 86k–100k units over 467–624
  cells, last-band target rate non-zero.
- The **progress-rate collapse is a property of the task and the policy
  class, not of `btt_reward_v2`**. Both contracts collapse by the same
  order of magnitude across bands; v2 only makes the flat part observable by
  surviving into it. Support: the seed-0 band table, where the first-to-last
  band ratio is 20.2× for v1 and 12.0× for v2.
- **Deterministic collapse is a symptom of an unconverged policy, not an
  independent failure.** A distribution at 57–66 % of maximum entropy has a
  weak argmax; taking it greedily in every state yields the same action
  everywhere. The one model whose argmax still plays (`m7d_s1_v2`, share
  0.098) is also the one with the highest end-of-run entropy (0.658 of max),
  which is the opposite of what an "over-committed" explanation predicts.
- **The remaining four targets are not blocked by horizontal range alone.**
  v1 travels to `x ≈ 5,800–8,400` and still never exceeds 6. Whatever the
  last four require, reaching that part of the stage is not sufficient.
- **The final checkpoint being "not the best" is not established.** The
  intermediate curve points use n = 20 stochastic episodes against n = 100
  at initial and final. With a per-episode target standard deviation near
  0.65, a 20-episode mean carries a standard error of ≈ 0.145. The
  best-minus-final gaps are +0.10 (seed 0), +0.29 (seed 1) and +0.18
  (seed 2) — inside, or barely outside, one standard error of the noisier
  estimate. Treating those peaks as real would be reading sampling noise.

### 2.3 Unknowns — not answerable from what M7d stored

- **Which** target each break corresponds to. `target_break_ticks` records
  when, never which. So "the policy always farms the same easy four" is not
  measurable, and neither is "v1 and v2 collect different sets of six".
  Closing this needs a native observation field and therefore its own
  milestone gate; it is proposed below as optional and separately gated.
- Position occupancy for any episode **not** replayed. The 15 replayed
  trajectories are a documented sample, not the population; the population
  statement is limited to final position.
- Per-state value or advantage estimates. Only rollout-level training
  metrics are stored.

## 3. Learning-curve classification, per v2 seed

Rule, stated before application: Theil-Sen slope `s` over the checkpoint
curve in targets per 1e6 transitions, against a noise scale `eps` set to half
the mean checkpoint-to-checkpoint absolute change, rescaled to the same
units; `improving` if `s > eps` and (last third − first third) > 0;
`regressing` if the mirror image; `plateaued` if `|s| <= eps`; `too_noisy`
if slope and endpoint difference disagree.

| seed | stochastic | slope /1e6 | noise | last − first third | deterministic | classification |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | improving | +0.732 | 0.158 | +0.453 | improving | **still improving** |
| 1 | improving | +1.150 | 0.173 | +0.803 | improving | **still improving** |
| 2 | improving | +0.456 | 0.122 | +0.447 | plateaued | **still improving** |

All three v2 seeds are **still improving** at 1,024,000 transitions, with
slopes 2.9–6.6× the noise scale. For contrast, v1 gives improving (seed 0),
too_noisy (seed 1) and regressing (seed 2) — the degeneration M7d described.

This classification rests on gameplay (targets, falls, horizon, tails), never
on numerical reward. The entropy telemetry in §2.1 is independent
corroboration from the optimizer's side, and it agrees: no seed had
converged.

**Was the final checkpoint the best checkpoint?** On the raw numbers, no for
all three v2 seeds (best at 716,800 / 921,600 / 819,200). After accounting
for the n = 20 sampling noise of those intermediate points (§2.2), **no seed
shows a real decline from its peak**, and no seed shows deterioration in
falls, horizon rate or tail fraction over the same stretch. The correct
statement is that the final checkpoint is statistically indistinguishable
from the best one, not that training overshot.

**Does idling rise as falling drops?** Within v2's own curve the fall rate is
already at or near zero by 204,800 transitions at every seed, while the
target count keeps climbing afterwards. The tail fraction does not grow
monotonically once falls are gone. The two are not trading off against each
other inside v2; the tail is what remains after the fall mode is removed, not
something the removal creates.

**Does one seed behave differently?** Yes, seed 1 — but on the v2 side it is
the *best-behaved*: highest slope (+1.150), highest end-of-run entropy
(0.658 of max), the only non-collapsed argmax policy, and the best
deterministic score. Seed 0 is the one that disagrees on the v1/v2 contrast
(§2.1, survival-matched), and seed 2 has v2's only residual fall rate (0.27).

## 4. Root-cause hypotheses, ranked by evidence

1. **The policy is under-trained; 1,024,000 transitions is early, not late.**
   Strongest support: entropy at 57–66 % of maximum with `ent_coef = 0.0` and
   no deceleration (1.06, 0.60, 1.32), improving target curves on 3/3 seeds,
   healthy explained variance, and argmax degeneracy that follows directly
   from a flat distribution. Nothing in the data shows a plateau, because no
   plateau occurred.
2. **The task's remaining targets need a capability the policy class has not
   found, and sparse +1.0 rewards over a 3,600-step horizon are a weak
   teacher for it.** Support: the shared 12–20× band collapse under both
   contracts, the hard 6-target ceiling across all 6,108 episodes, and the
   fact that v1's much larger horizontal range buys it no extra targets.
3. **The `−5.0` fall penalty narrows where v2 goes.** Support: v2's final
   positions cluster at `x ≈ 350–670` with p90 ≤ 2,209, against v1's
   4,824–5,791 medians at `y = −9,800`. This is a real behavioural
   difference. It is ranked third, not first, because hypothesis 2 shows the
   extra range does not by itself yield targets — so confinement is a
   plausible contributor to the ceiling, not a demonstrated cause of it.
4. **Exploration is too diffuse to chain a long approach.** Support: 81–89 %
   action-change rate and near-uniform action marginals mean the policy
   rarely holds a direction long enough to execute a multi-second traverse.
   Ranked fourth because it is a restatement of hypothesis 1's mechanism at
   this stage of training and is expected to change as entropy falls.
5. **Rejected by the evidence:** literal idling, being stuck in place,
   repeated ineffective action loops, and zero-target inactivity — for the
   *sampled* policy. All four are confirmed for the *argmax* policy, which is
   an evaluation-mode artefact of hypothesis 1 rather than what training
   optimises.

## 5. Recommendation: **option B — a smaller bounded v2 extension first**

The evidence points two ways, which is exactly what option B is for.

**For continuing unchanged (would support A):** all three v2 seeds are still
improving at 2.9–6.6× the noise scale; policy entropy is still falling at
full speed with no entropy bonus propping it up; the critic is healthy; and
no plateau, regression or deterioration exists anywhere in the curves. A
plateau cannot be declared on a curve that never flattened, and an anti-idle
intervention cannot be justified against a tail the measurements show is
neither idle nor caused by v2.

**Against committing the full budget (rules out A):** the objective is a
verified clear, and there is no clear-directed signal to extrapolate — 0 in
6,108 episodes, a hard 6-target ceiling, and a progress collapse that both
contracts share. The improving trend is improvement *inside* a region whose
observed maximum is 6 targets; at +0.75 targets per 1e6 transitions,
extrapolating to 10 would demand ~8M transitions on a linear assumption that
the ceiling evidence contradicts. Seed 0's survival-matched comparison also
favours v1, which is a live complication in the selection that stands behind
this experiment.

**Why not C.** An anti-idle intervention would target a behaviour that the
measurements show is not idling, is not caused by v2, and occurs identically
under v1. Designing a contract change against a misread metric is how the
selection error compounds. C becomes the right call *after* the extension, if
a plateau appears while the ceiling holds — and §6.6 pre-registers exactly
that hand-off.

**Why not D.** The measurements are not missing. The diagnosis is decisive on
what the tail is, what it is not, and whether the optimizer converged. One
genuine unknown remains (target identity) and it is scoped below as an
optional, separately gated addition rather than a blocker.

## 6. Proposed experiment: `m7e_ext`

### 6.1 Models and seeds

**Fresh models**, not resumes of the M7d runs. The M7d runs and their
checkpoints, statistics and artifacts are preserved untouched; a resume would
entangle the new lineage with them and complicate the compatibility
fingerprint. Training the first 1,024,000 again also gives a within-experiment
replication of M7d's own curve.

Seeds **0, 1, 2** — the same three, so every M7e point is paired with an M7d
point at the same seed. Reward **`btt_reward_v2`, unchanged**, on all three.
No v1 arm: this is not a contract comparison, it is a budget question about
the provisionally selected contract, and M7d already supplies the v1 curves
at the same seeds.

### 6.2 Transition budget, derived

| quantity | value | source |
| --- | --- | --- |
| v2 end-to-end throughput | 1,168.6 transitions/s | mean of the three M7d v2 runs |
| episodes per 1e6 transitions (v2) | 287 | 293.7 episodes per 1.024M, measured |
| entropy still to burn, slowest seed | 2.816 → 1.82 nats | seed 1 v2 end vs v1's end state |
| its last-third rate | −0.817 nats per 1e6 | measured |
| transitions to commitment, slowest seed | **≈ 1.22M** | 0.996 / 0.817 |

The extension is sized as *commitment plus enough post-commitment room to
observe a plateau*: ≈ 1.22M to bring the slowest seed to the entropy level
v1 already reached, plus ≥ 0.8M (8 checkpoint intervals) afterwards during
which a flattening curve can actually be measured rather than assumed.

**Total per seed: 3,072,000 transitions** (2,048,000 beyond M7d's budget) —
30 checkpoint intervals of 102,400, ~881 training episodes per run against
M7d's ~294, i.e. **three times the learning opportunities**. It is 3 × 1.024M
because 1.024M is the M7d unit and the derivation lands between 2× and 3×,
not because 3 is round.

**Maximum budget: 3,072,000 per seed, hard.** No continuation beyond it
inside M7e, whatever the curves do; a further extension is a new milestone
with its own pre-registration.

### 6.3 Checkpoints and evaluation

- Checkpoint cadence **102,400 transitions** (as M7d), giving 30 checkpoints
  plus `final`, ~5.6 MB of model files per run (186 KB per checkpoint set,
  measured).
- **Post-hoc evaluation only**, after all training completes — so evaluation
  can never reseed training and the process count cannot exceed 10.
- Evaluated points per seed: `initial` (0), then every **307,200**
  transitions (9 intermediate), then `final` (3,072,000) = 11 points.
- **Stochastic: 100 episodes** at `initial` and `final`, **60** at each
  intermediate point. 60 gives a standard error of ≈ 0.084 targets against
  M7d's observed σ ≈ 0.65, which is what makes a plateau declarable; M7d's
  n = 20 (SE ≈ 0.145) is the reason its intermediate peaks could not be
  ranked.
- **Deterministic: 100 episodes** at `initial` and `final` (M7d
  comparability, and it re-verifies identical play), **5** at each
  intermediate point — enough to confirm the 100-identical-plays property
  without spending 100 runs on one trajectory.
- Per seed: 740 stochastic + 245 deterministic = 985. Three seeds = 2,955.
  Plus a fresh 100-episode random baseline = **3,055 evaluation episodes**.
- Frozen normalisation during evaluation; VecNormalize statistics loaded from
  the evaluated checkpoint and never updated.

### 6.4 Lifecycle, artifacts and preservation

- N = 5, standby enabled, at most one active and one standby BattleShip per
  worker, **maximum 10 game processes**, verified by the existing monitor.
- `SSB64_RL_NO_RENDER=1` and `SSB64_RAPHNET_DISABLE=1`, as M7d.
- Isolated worker directories, job object, M7 port blocks, unchanged.
- Artifact policy: training preserves on `new_best_target_count`, periodic
  milestones and any anomaly, as M7d. Evaluation preserves **every** episode
  (`preserve_all`), so the M7e action-stream analysis can be rerun exactly as
  this one was.
- Canonical native actions remain artifact and replay truth. No hidden reset
  action. No video recording. No reward normalisation.

### 6.5 First clear: preservation and verification

A clear is the objective, so it gets a fixed, pre-registered path:

1. The episode is preserved immediately and unconditionally with its full
   canonical native action stream, metadata, both observations and the
   checkpoint that produced it — regardless of any other preservation rule.
2. `completion_time_passed` and `completion_input_tick` are recorded as
   **two separate values** and neither is collapsed into the other nor
   decremented.
3. It is **natively re-validated** by replaying its canonical actions on a
   fresh process from tick 0 through the existing `replay_one` path, which
   checks the fresh state, the initial observation, every `consumed_tick`,
   the final observation including `host_frame`, the target count, both
   completion clocks and `cleared_natively`. A clear that does not reproduce
   is reported as a clear **candidate**, never as a verified clear.
4. Its time is compared to the 7.43-second baseline only after native
   re-validation, and reported against `completion_time_passed = 446` /
   `completion_input_tick = 447` as separate clocks.
5. Training is **not** stopped by a clear; the run continues to its budget so
   the curve stays interpretable. (Gate 1 in §7 governs what happens next.)

### 6.6 Idle monitoring and the plateau rule

Monitored at every evaluated checkpoint, all defined in
`rl/m7e_idle_analysis.py` and reused unchanged:

- `tail_fraction` (the proportional metric — the headline, since §1 shows the
  absolute one tracks episode length),
- M7d's `idle` rate (kept for continuity with the M7d tables),
- `zero_target_horizon_rate`, `early_then_stagnant_rate`,
- phase-progress bands and the survival-matched windows,
- tail entropy, tail switch rate, tail long-run share, full-neutral share,
- `collapse_share` for the deterministic play,
- policy entropy and its deceleration from the rollout metrics.

**A plateau is declared** when, over the **final 6 evaluated checkpoints**
(t = 1,536,000 through 3,072,000, spanning 1,536,000 transitions), the bootstrap 95 % CI of the Theil-Sen
slope of mean stochastic targets **excludes +0.25 targets per 1e6
transitions**, in at least 2 of 3 seeds, *and* no seed's tail fraction has
fallen by more than 0.05 over the same span. Both halves are required: a flat
target curve with a still-shrinking tail is progress in a form the target
count has not yet registered.

**Optional, separately gated:** target-identity instrumentation — recording
*which* target broke, not only when. It would close the one real unknown in
§2.3 and is the measurement any future anti-confinement design would need.
It requires a new native observation field in `port/rl`, so it is **not** part
of this proposal's approved scope; it is flagged for its own decision, with
its own build, replay and regression verification, before any of it is
written.

### 6.7 What is deliberately held constant

Exactly one thing changes from the M7d v2 baseline: **the transition budget**
(1,024,000 → 3,072,000), with the evaluation episode counts raised as a
measurement consequence of it. Not changed: reward values, reward identity,
PPO hyperparameters, action contract, observation contract, horizon, N,
lifecycle, normalisation, seeds, artifact policy.

Explicitly excluded from this experiment, in any form: route hints, target
order hints, TAS demonstrations, target-distance shaping, hardcoded movement,
hidden termination changes, reward v3, RNG seed checking.

## 7. Pre-registered decision gates

Objective ranking throughout, unchanged: **(1) verified clear, (2) more
targets for incomplete runs, (3) faster time among verified clears,
(4) reward is diagnostic only.**

| # | Outcome at the maximum budget | Pre-registered response |
| --- | --- | --- |
| 1 | **A verified clear** (natively re-validated per §6.5) | The primary objective is reached for the first time. M7f becomes clear-rate and completion-time work under `btt_reward_v2`, which is then *confirmed* rather than provisional. Preserve the clear, its checkpoint and its full action stream permanently; report both completion clocks separately; open the Track 2 comparison against the 7.43 s baseline. Do not retune anything until the clear is reproduced at a second seed. |
| 2 | **Better targets, no clear** (mean targets up, 3/3 or 2/3 seeds, ceiling still ≤ 6) | v2 is confirmed for continued use on objective rank 2. The budget question is answered: more transitions help. M7f addresses the **ceiling**, not the budget — and the target-identity instrumentation (§6.6) is promoted from optional to prerequisite, because "which four are never broken" is then the blocking unknown. |
| 3 | **Still improving at 3,072,000** (no plateau by §6.6) | Do **not** silently extend. Record that the budget is still not the binding constraint, and open M7f as an explicit budget-versus-intervention decision with the new curves in hand. A further extension needs its own pre-registration and its own maximum. |
| 4 | **A plateau** (by the §6.6 rule) | The budget question is settled negatively: unchanged v2 has converged short of the objective. This is the trigger for **option C** — a controlled anti-confinement or exploration intervention, one behaviour-changing variable against the v2 baseline, given a new contract identity (never an edit to v1 or v2), with v2 preserved and rerun as the control arm. |
| 5 | **Worse idling** (tail fraction up ≥ 0.10 in ≥ 2 seeds, or `zero_target_horizon_rate` > 0.05 anywhere, or targets flat/down) | Treat as a genuine regression of the selected contract, not a metric artefact — the proportional metric is immune to the §1 confound. Stop; do not extend further. Re-open the M7d selection with the M7e evidence attached, and design the intervention against a documented failure rather than a suspicion. |
| 6 | **Strong seed disagreement** (≥ 1 seed improving while ≥ 1 regresses, by §3's rule) | No aggregate claim is made. Report per seed, add seeds 3 and 4 at the *same* 3,072,000 budget before any contract or hyperparameter change, and treat the three-seed conclusion as unresolved until five exist. Seed-cluster intervals, not episode-level ones, carry the cross-seed claim. |
| 7 | **Deterministic collapse persists** (`collapse_share ≥ 0.5` in ≥ 2 of 3 seeds at `final`) | Record it as an evaluation-mode property of the contract, not as a training failure, and keep the stochastic policy as the reported one. If it persists *while* policy entropy has stopped falling, that combination contradicts hypothesis 1 in §4 and forces a re-ranking of the root causes before M7f is designed. |
| 8 | **A lifecycle, artifact or replay regression** (any process-count breach, port leak, non-reproducing preserved artifact, `git diff --check` failure, or a changed user-configuration sha256) | Stop the experiment at once. Do not analyse or report gameplay results from a run whose lifecycle is in question. Diagnose, document under `docs/bugs/`, fix, re-verify the full regression chain, and only then decide whether the affected runs are salvageable or must be rerun. |

Gates 1, 2 and 4 are mutually exclusive and are evaluated in that order.
Gate 8 pre-empts all others.

## 8. Estimated duration, memory and disk

All figures are measured from the M7d v2 runs on this machine (6 logical
CPUs) and scaled; they are estimates, not commitments.

| item | estimate | basis |
| --- | --- | --- |
| training, per seed | 3,072,000 / 1,168.6 ≈ **44 min** | measured v2 end-to-end throughput |
| training, 3 seeds | **≈ 2.2 h** | sequential, as M7d |
| evaluation, 3,055 episodes | **≈ 2.3 h** | 2.71 s/episode measured over M7d's 1,794 v2 evaluation episodes |
| **total wall** | **≈ 4.5 h**, call it 5–6 h with orchestration and verification | 2.2 h train + 2.3 h evaluate |
| peak memory | **≈ 1.7 GB** | parent 306 MB + 5 workers × 48.5 MB + 10 game processes × 110.6 MiB |
| disk, training | 3 × ≈ 54 MB ≈ **160 MB** | 18 MB measured per 1.024M-transition run, ×3 budget |
| disk, evaluation | ≈ **1.2 GB** | 225 MB per M7d model for 598 preserved episodes, scaled to 3,055 |
| **total disk** | **≈ 1.4 GB** | against 148 GB free |

M7d itself is 1.1 GB and stays. Memory does not scale with the budget — it is
per-step, not cumulative.

## 9. Limitations of this diagnosis

- Three seeds, one task, one horizon, one process count, one PPO
  configuration, one machine, one executable build. Nothing here generalises
  beyond that.
- The trajectory evidence is 15 replayed episodes chosen by stated rules. It
  is a documented sample; population-level spatial claims are limited to
  final position.
- Target identity is unknown (§2.3), so every statement about *which*
  targets are or are not reached is an inference from counts and positions,
  never a measurement.
- The 6-target ceiling is an observation over 6,108 episodes of two
  contracts, not a proof that 7 is unreachable.
- The entropy-based "still learning" argument reads the optimizer, not the
  game. It establishes that training had not converged; it does not
  establish that convergence would produce a clear, and §5 does not claim it
  would.
- The survival-matched comparison conditions on surviving, which is itself
  an outcome. It answers "given both are alive at tick W, who has scored
  more", which is the right question for diagnosing the tail, and it is not
  a substitute for the per-episode comparison M7d registered.
- `m7d_s1_v2`'s non-collapsed argmax is a single model. It is treated as a
  counter-example to one explanation, not as evidence for a mechanism.
- No M7d conclusion is retracted here. The v2 selection stands as
  provisional, through the target path, exactly as registered.

## 10. Commands

```text
python rl/m7e_idle_analysis.py --test            # 85 metric-definition cases
python rl/m7e_idle_analysis.py                   # the diagnosis -> docs/rl_v2_idle_diagnosis_m7e.{md,json}
python rl/m7e_idle_analysis.py --no-actions      # same, skipping the action-stream pass
python rl/m7e_idle_analysis.py --replay-plan     # the Phase A4 selection, by rule
python rl/m7e_idle_analysis.py --replay          # the bounded observational replay probe
```

Nothing in this document has been committed, pushed, branched or merged.
