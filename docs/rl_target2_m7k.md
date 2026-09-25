# RL M7k: the moving-target bottleneck — analysis, reward comparison, `btt_reward_v3_t2`, teardown

Status (2026-09-25): **analysis, offline comparison, opt-in contract, integration pilots and teardown investigation done;
one experiment proposed; no learning run.** Nothing is committed, pushed or branched.

Preserved and unchanged:
- the registered `btt_reward_v3` contract (canonical JSON sha256 `d9447d47…`, identical);
- the M7j registration and document (`docs/rl_reward_v3_m7j.{md,json}`, byte-identical);
- the Stage 0 result (its run and verification files untouched; re-verified in memory against the current code:
  PASS, digests `5cec5fc4…`, 30 rows);
- every historical run directory (read only).

The v2-versus-v3 campaign and `btt_reward_v3_rt` are not run and not implemented.

Machine-readable record: [`rl_target2_m7k.json`](rl_target2_m7k.json).

## 0. Summary

- **Target 2 is an exploration-and-risk problem, not a near-miss problem.**
  - In the 128 evaluation episodes that broke all six static right targets but not target 2, Mario never came within
    600 units of it and never touched the moving platform.
  - Policies rarely go up there: in ordinary episodes the upper-right approach zone is visited only 5–7 % of the time.
- **When target 2 does break, it is almost always the same maneuver.**
  - An up-B (87 %) from about 680 units below the target, with Mario at x 2,200–3,100 and y ≥ 1,380.
  - The platform is near its lowest point: 58 of 67 breaks fall within ±60 ticks of the platform minimum. The
    platform's motion is an exact function of the tick, with a period of 300 ticks.
  - Target 3 is usually still alive at that moment.
  - 25 % of these episodes then fall, most exactly 174–188 ticks later (the helpless fall after the up-B), against
    1.6 % in reference episodes.
- **Under v2, target 2 is worth nothing to the learner.**
  - The expected discounted value of a target-2 break at the break step is **+0.07**: +1 for the target, minus the
    discounted fall risk.
  - In the unbiased training sample, the target-2 episodes rank at the 2nd percentile of returns.
  - The target-2 rate falls from 2.3 % (untrained) and 4 % (random) to 0.2–0.6 % within the first ~0.9 M transitions,
    together with the falls.
- **Offline comparison at an equal budget (at most 2.0 per episode):**
  - The **even right-target timing credit** puts **0.12 %** of its reward mass on target 2. It leaves target-2
    episodes indistinguishable (within-checkpoint z 0.21, the same as v3's 0.22). It even ranks "five static targets,
    no target 2" above "four static + target 2 at tick 1,500".
  - The **target-2 credit** `2.0·(3600 − n)/3600` raises the break-step value to **+0.88** and z to 1.0. It prefers an
    early target 2 over the 5th and 6th static targets, but not a late one.
  - Registered as **`btt_reward_v3_t2`** (sha256 `fa74d7d7…`), opt-in, with v3 unchanged inside it.
- **Future landing reward, assessed separately (not implemented).** A post-landing fall penalty of
  `−0.001·(3600 − t) − δ` (δ = 0.5):
  - never lets a fall beat idling to the horizon, at any tick;
  - always keeps crossing + landing + a later fall above staying right.
  No constant penalty tested does both. Proposed as `btt_reward_v3_l2`.
- **Teardown: one reproducible defect.**
  - Under CPU load, after `BattleShipEpisode.close()` returns, the killed game (same PID, already reaped) still holds
    its `BattleShip.log` for a median of 4 s and sometimes more than 20 s. This happened in 52 of 60 episodes under
    load, 0 of 40 when idle.
  - It cost 33 of 621 replays their results (now retried) and cannot affect a long run's training, whose deletions are
    deferred. Historical long runs show zero failed deletions.
  - The single "two helper processes" report **did not reproduce**: 0 in 400 no-game iterations, in 3 smokes under
    load and in 2 full suite rounds (plus 4 last session), against 1 in 142 historical training summaries.
- **Integration pilots:**
  - seed 0 at 204,800 transitions: no target-2 break occurred, and the run is bit-identical to the Phase K control;
  - seed 2 at 204,800 transitions: one target-2 break at tick 2,055, credited exactly once; every difference from the
    control follows that update, as registered.
- **Proposal:** `btt_reward_v3_t2` against the historical Phase K v1 control (seeds 0–2, same settings, budget and
  evaluation), with a registered first-clear relevance test (section 10).

## 1. Method and evidence

**Replays.** `rl/m7k_target2.py` replayed 621 stored episodes, each from tick 0 in a fresh process. Flags:
`SSB64_RL_NO_RENDER`, `SSB64_RAPHNET_DISABLE`, `SSB64_RL_TARGET_DIAG` (identity) and `SSB64_RL_SPATIAL` (the live
position of target 2, the platform translate, Mario's floor line). Both diagnostics are read-only and proven
gameplay-neutral.
- All 621 reproduced the recorded native action digest, consumed ticks and recorded target breaks.
- The replay sets were declared by rule before any replay (`runs/m7k/target2/v1/selection.json`):
  - **A (65):** every tick-0 evaluation episode with target 2 broken;
  - **B (128):** every tick-0 evaluation episode with the six static right targets broken and target 2 not;
  - **C (183):** the first 20 episodes of every final stochastic label;
  - **D (259):** every Phase K v1 training episode preserved as `periodic_milestone` (every 10th finished episode,
    content-blind: an unbiased training sample).
- **Not replayable:** 18 Phase K random-baseline episodes were never preserved (4 of them broke target 2). Their
  identities are still in the evaluation census.
- **Data sources.** The TAS and the user crossing fixtures were not read.
- **Offline comparison.** `rl/m7k_rewards.py` used closed forms over all 8,965 tick-0 evaluation episodes (identity
  from `btt_eval_metrics_v1`; none has a left entry) and over the training sample.
- **Evidence directories** (git-ignored):
  - `runs/m7k/target2/v1/` (traces, analysis);
  - `runs/m7k/rewards/final/comparison.json`;
  - `runs/m7k/teardown/`;
  - `runs/m7k/_pilot/`.

## 2. Target-2 breaks and near misses

| Quantity (67 breaks: 65 evaluation + 2 training) | Value |
| --- | --- |
| Consumed tick of the break | median 2,496 (p25 1,191, p75 2,986; min 223) |
| Horizon left at the break | median 1,103; ≥ 900 ticks in 45 of 67 |
| Break order among all targets | median 5th |
| Right targets still alive just before | usually target 3: {3, 7} ×17, {3, 5, 7} ×13, {3} ×8, {5, 7} ×6, all six ×4 |
| Mario's status | up-B: 226 (air) ×40, 225 ×18; other 9 |
| Mario's position | x median 2,486 (2,224–3,136 except one fireball at 1,063); y median 1,679 (≥ 1,382) |
| Distance to target 2 on the previous tick | median 679 (p25 571, p75 745) |
| Platform translate y | median 1,588 (min 1,500); 58 of 67 within ±60 ticks of a platform minimum |
| On the platform at the break | 4; ever on it before the break: 7 |
| Episode ended in a fall | 17 of 67 (25 %); 8 of them exactly 174–188 ticks after the break |

**Platform.** It is a pure function of the consumed tick, with zero spread across 2.19 M samples from 621 episodes.
- The translate y ranges 1,500–3,300; target 2 sits 600 above it.
- The period is 300 ticks, with minima at ticks 238 + 300k.
- The reachable window is therefore about 120 ticks every 300 ticks.

**Near misses and approach.** Distances are from Mario's position (his feet) to target 2 while it is alive.

| Set | Episodes | Closest approach, median | Within 600 | Within 1,000 | Approach zone* visited | Platform contact |
| --- | --- | --- | --- | --- | --- | --- |
| B: six static, no target 2 | 128 | 2,032 | 0 | 6 | 9 (7 %) | 0 |
| C: final stochastic sample | 183 | 2,357 | 0 | 7 | 9 (2 with a break) | 0 |
| D: training sample | 259 | 2,648 | 0 | 2 | 13 (2 with a break) | 1 |

\* **The approach zone** is x 2,100–3,300 and y ≥ 1,350: the box containing the break positions, defined from set A.
In B, C and D it is descriptive only.

**The learning signal under v2.** The discounted value at the break step is +1 for the target plus
−5 · 0.999^(ticks to the fall) for episodes that fell (mean over the 67 breaks):

| Break-step credit b | v2 / v3 (0) | 1 | **2** | 4 |
| --- | --- | --- | --- | --- |
| Mean value | **+0.07** | +0.47 | **+0.88** | +1.69 |
| Breaks with a negative value | 17 | 17 | 16 | 11 |

**Target-2 rate by training stage** (tick-0 stochastic evaluation, Phase K / M7h):

| Stage | Phase K | M7h |
| --- | --- | --- |
| Untrained | 2.3 % (falls 28 %) | 2.3 % (falls 28 %) |
| Up to 0.9 M transitions | 0.6 % | 0.2 % |
| Final | 1.5 % | 0.7 % |

The random baseline breaks target 2 in 4 of 100 episodes.

## 3. Offline reward comparison

Candidates:
- v3 (registered);
- **ER** = v3 + `(2/7)·(3600 − n)/3600` per right target (the proposed `btt_reward_v3_rt`, offline only);
- **T2(b)** = v3 + `b·(3600 − n)/3600` on target 2.

Where n = consumed_tick + 1. ER and T2(2) have the same maximum budget of 2.0.

| Population | Metric | v3 | ER | **T2(2)** | T2(4) |
| --- | --- | --- | --- | --- | --- |
| All 8,965 tick-0 evaluation episodes (69 with target 2) | within-label z of target-2 episodes | 0.22 | 0.21 | **0.97** | 1.67 |
| | target-2 percentile | 0.58 | 0.64 | **0.76** | 0.80 |
| Policy stochastic (6,660; 65) | z | 0.25 | 0.24 | **1.01** | 1.71 |
| Training sample (259; 2) | target-2 percentile | 0.02 | 0.02 | 0.03 | 0.21 |
| All | new term non-zero in | — | 91 % of episodes | 0.8 % | 0.8 % |
| All | share of the new term's mass on target 2 | — | **0.12 %** | 100 % | 100 % |

Outcome classes (all surviving to the horizon):

| Class | v3 | ER | T2(2) |
| --- | --- | --- | --- |
| A: six static (last at 1,699), no target 2 | 2.400 | 3.854 | 2.400 |
| C: four static + target 2 at 1,500 | 1.400 | 2.656 | **2.566** |
| D: four static + target 2 at 3,000 | 1.400 | 2.537 | 1.733 |
| G: five static, no target 2 | 1.400 | **2.704** | 1.400 |
| E: sweep late (target 2 at 3,570) | 6.416 | 7.873 | 6.432 |
| F: sweep early (target 2 at 1,800) | 7.399 | 8.997 | 8.399 |

Resulting orders:
- **v3:** F > E > A > B > C > D > G.
- **ER:** F > E > A > B > **G > C** > D. It prefers another static target over an early target 2.
- **T2(2):** F > E > **C > A** > B > D > G. Early target 2 is preferred over the 5th and 6th static targets; late target 2
  is not; the sweeps stay on top.

**Loopholes of T2.** None found.
- It is paid once (native identity), including when several targets break on one tick and on terminal steps.
- It is added after v3's total, so it is bit-identical to v3 on every other step (a 300-trial random property test).
- A fall still costs −5.

**Decision: T2 with b = 2.0**, registered as a separate contract. The reasons:
- It turns the break from worthless (+0.07) into clearly positive (+0.88).
- It has the same budget as ER, so the comparison is fair.
- Its time sensitivity does the right trade: early target 2 counts over extra statics, late target 2 does not.
- b = 4 overweights the trade; b = 1 does not flip it.

## 4. The contract `btt_reward_v3_t2` (frozen, opt-in)

```
btt_reward_v3_t2 = btt_reward_v3 (unchanged) + moving_target_term
moving_target_term = 2.0 * (3600 - n) / 3600,   n = consumed_tick + 1,
paid once on the step whose diagnostic reply first shows native target ID 2 broken
(n outside 1..3,600 is a violation); total = v3 total + moving_target_term
```

- **Identity:** `btt_rewards.REWARD_V3_T2` (a `MovingTargetRouteRewardContract`). Its route block equals v3's plus
  `"moving_target": {"rule": "btt_moving_target_timing_v1", "target_id": 2, "timing_max": 2.0}`. The canonical sha256
  is `fa74d7d7edf88936fcb63e1c65cc5751dddc0bc6b1c974a70af232160b9def99`.
- **Scope:** the same rules as v3: obs v1 only, a 3,600-tick horizon, no curriculum, `SSB64_RL_TARGET_DIAG=1`. It
  never enters the policy observation.
- **It inherits v3's registered post-landing −1.** That is unreachable here: no sweep has been observed during tick-0
  training. It is not changed, per the instruction to version any revision separately (section 5).

## 5. Separately assessed: a future qualified-landing fall penalty (not implemented)

The requirement: after a qualified landing, falling must never score higher than surviving without another target.

| Post-landing penalty | A fall beats idling? | Crossing + landing + fall loses to staying right? | Break-even success probability for the last left target |
| --- | --- | --- | --- |
| v3 registered −1 | **yes, before tick 2,600** | never | 0 – 8.3 % |
| constant −3.7 | no | **yes, falls after tick 1,900** | 0.9 – 25 % |
| −5 (v2) | no | **yes, falls after tick 600** | 11 – 31 % |
| **−0.001·(3600 − t) − δ** (δ = 0.5) | **no, at any tick** | **never** (for δ < 2) | 4.3 % (constant) |

Proposed as a separate future id, `btt_reward_v3_l2` (v3 with this penalty, δ = 0.5), to be registered when landings
become reachable. The penalty equals the remaining-horizon step cost plus δ. A fall is therefore exactly δ worse than
idling at every tick, and the landing bonus (+2) keeps crossing positive.

## 6. Teardown investigation

**The report.** The first M7j game run had `leak_free: false`: two non-BattleShip job processes (PIDs 16308 and 17856)
were alive at the trainer's end check. That check waits up to 20 s for `BattleShip.exe` to vanish, then samples the
job's live PIDs once. The PIDs appear in no record of that run. Tool: `rl/m7k_teardown_probe.py`.

| Probe | Result |
| --- | --- |
| `micro`: the trainer's exact check pair (a `tasklist` child, then the job sample) ×400, no game | 0 leftovers |
| `smoke` ×3 under 8 busy-loop processes (the fourth cut by my command timeout) | 3 of 3 leak-free |
| `suite` (the original context, full M7j game suite) ×2, idle | 18 of 18 pass, 0 leftovers; plus 4 full runs last session |
| History: every training summary with a cleanup record | 1 of 142 (the reported one) |
| `files`: short episodes, then who holds the game's files after `close()`: 4 workers, idle | 0 of 40 locked |
| `files`: 6 workers + 8 busy-loop processes | **52 of 60 locked**; holder = the episode's own, already reaped `BattleShip.exe` PID (Restart Manager); deletable after a median 4.0 s, p90 11.1 s, max > 20 s; 53 of 60 needed the second `TerminateProcess` |

**Conclusions:**
- **Reproducible defect (under load):** the game's file handles outlive `close()`, which returns once the process
  object is signalled.
  - Anything that deletes a runtime directory immediately after `close()` can fail. That caused all 33 lost replays
    (bursts coinciding with my concurrent probes).
  - Mitigated here: `m7k_target2` retries and records the lock time and holder.
  - Training is not affected by construction: deletions are deferred to the next reset or close. Historical long runs
    show leftover episode/runtime directories exactly equal to the preserved counts (e.g. 90/90), i.e. zero failed
    deletions.
- **Not reproducible:** the two helper processes. Their identity cannot be recovered. They did no harm: no game
  survived, and the job kills its members at exit.
- **Before a long run:**
  - keep the machine otherwise idle (the launch gate checks CPU only at launch);
  - optionally, a separately reviewed change to the trainer's end check: a short grace period, and recording image
    names of any job PIDs, so a recurrence identifies itself.
  - No blocker found.

## 7. Implementation and tests

**New files:**
- `rl/btt_reward_t2.py`: `MovingTargetRouteRewardState`, a subclass of v3's state; `make_route_state`; closed form;
  self-test.
- `rl/m7k_target2.py`: selection, parallel exact replays, analysis.
- `rl/m7k_rewards.py`: the offline comparison, landing assessment and relevance baselines.
- `rl/m7k_teardown_probe.py`.
- `rl/m7k_tests.py`.
- `rl/m7k_run.py`: gate, bounded pilot, verification.
- `rl/configs/m7k/m7k_v3t2_pilot_s0.toml`.

**Additive edits to M7j-era files** (v3's JSON, code path and tests unchanged; `btt_reward_v3.py` is byte-identical):
- `btt_rewards.py`: `MovingTargetRouteRewardContract`, `REWARD_V3_T2`, registry and flags;
- `experiment_config.py`: accepts the id;
- `m7j_reward_env.py`: the state now comes from `make_route_state` (v3 still gets `RouteRewardState`).
- The M7j registration's code hashes for these three files are therefore historical.

**Tests** (all 2026-09-25):
- `m7k_tests all`: **11 / 11** (`runs/m7k/_tests_20260925T145310Z`). They cover:
  - identity and tampering;
  - timing bounds;
  - one-time payment, including on multi-target, failure and clear steps;
  - bit-identical v3 parity (300 random trials);
  - strict configuration (historical fingerprints and the M7j pilot profile unchanged);
  - dispatch;
  - the TAS: v3 24.3536 → v3_t2 26.2624, differing only on tick 163, identical observations;
  - 9a130d1f through a v3_t2 worker: +0.0161 on tick 3,570;
  - a no-target-2 episode equal to v2;
  - a PPO smoke (leak-free);
  - v3 ↔ v3_t2 resume refused.
- M7j regression on the current code: `m7j_tests` unit 9 / 9, game 9 / 9 in each of the two probe rounds;
  `btt_reward_v3` self-test PASS.
- Inherited regressions on the final code:

  | Suite | Result |
  | --- | --- |
  | `m7b_config_tests` | 16 / 16 |
  | `m7b_smoke` (v1/v2 game paths) | 7 / 7 |
  | `m7_smoke unit` | 8 / 8 |
  | `m7c_standby_tests unit` | 4 / 4 |
  | `m7g_obs_tests unit` | 8 / 8 |
  | `m7h_tests` | 13 / 13 |
  | `m7h_campaign_tests unit` | 15 / 15 + archive check |
  | `m7g_k_tests unit` | 6 / 6 (after adding `m7k` to its later-milestone profile exclusion, as M7h and M7j did) |
  | `m7g_k_campaign_tests unit` | 13 / 13 (after scoping its "no training profile sets the diagnostic flag" invariant to non-route rewards; the recorder is still never built in training) |
  | `m7g_tests unit` | 8 / 9: the pre-existing `unit_training_isolation` failure on three M7h files (unchanged from HEAD; no M7k file matches) |

## 8. Bounded integration pilots

Command: `python rl/m7k_run.py pilot --transitions 204800 --seed S`. The pilot uses the Phase K control's settings with
`reward = btt_reward_v3_t2`. Registered checks V1–V5 (see `rl/m7k_run.py`):
- identical to the control until the first rollout containing a target-2 break;
- every later difference explained by the credit;
- every row equal to its closed form.

| Seed | Result |
| --- | --- |
| 0 | **PASS.** 63 episodes, **no target-2 break**, so the run is bit-identical to `m7g_s0_v1` `ckpt_000204800` (policy `690e82cc…`, obs_rms `d29164a4…`). 63 of 63 rows equal. 1,114 transitions/s. |
| 2 | **PASS, divergence path exercised.** One target-2 break (episode `e3f0bab7`, consumed tick 2,055, global transition 123,085, inside the rollout ending at 128,000) earned exactly its credit, 0.8578. All 38 rows that ended before the following update are identical to `m7g_s2_v1`. The first action-divergent row is that same episode (its remaining actions came after the update), and every one of the 60 rows equals its closed form. The final set differs from the control's (`d648140d…` vs `35aa7469…`), as registered. 1,105 transitions/s. |

## 9. First-clear relevance test (registered)

**Episode-level definitions** (tick-0 evaluation):
- **L (leading):** target 2 broken by consumed tick 2,699 in an episode that also breaks at least 5 of the 6 static
  right targets.
- **R (relevance):** all seven right targets broken by consumed tick 2,699, leaving at least 900 ticks for the
  crossing and the left side.

The 900-tick allowance is the M7j convention. It is consistent with the validation references: the TAS needs 88 ticks
from its sweep to the clear, and the user fixtures take about 200–480 ticks from takeoff to their left-target breaks.
Neither is used as an input.

**Baselines** (`runs/m7k/rewards/final/comparison.json`):
- all 8,965 tick-0 evaluation episodes: L = 9, R = 0;
- Phase K v1 control, final stochastic (seeds 0 / 1 / 2): L = 0 / 0 / 1, R = 0 / 0 / 0, target 2 = 1 / 0 / 2.

**Reward-level check:** under v3_t2 the first-clear reference (the TAS, 26.26) ranks above every recorded non-clear
episode, whose best is the late sweep `9a130d1f` at 6.43 (next 4.11). An early sweep ranks above a late one.

## 10. Experiment proposal (one): target-2 timing credit vs the historical control

**Arms and settings:**
- **Arms:**
  - **T** = `btt_reward_v3_t2`, seeds 0, 1 and 2 (three new runs);
  - **C** = the historical Phase K v1 control `m7g_s{0,1,2}_v1` (`btt_reward_v2`, identical to v3 there, because its
    training never broke more than 6 targets).
- **Why the control can be reused:**
  - Stage 0 and this session's pilots show the v3/v3_t2 code path is bit-identical to C until a v3_t2 term fires;
  - C already has the same evaluation with evaluation metrics.
- **Fixed:** obs v1, Track 1, tick-0 starts, M7e/Phase K PPO, N = 5 with standby, 3,072,000 transitions, checkpoints
  every 102,400, no in-process evaluation.
- **Evaluation:**
  - the Phase K protocol: initial 100 + 100, curve 9 × (60 + 5), final 100 + 100, seed 12345, evaluation metrics on;
  - plus post-hoc exact replays (spatial on) of all final stochastic episodes of both arms, for the approach zone.

**Primary endpoint:** the final stochastic target-2 rate per seed, p_T,s against p_C,s (C: 1 / 0 / 2 %).

**Decision rule (registered):**
- **0.** Integrity: every run completes and verifies; T's rows equal their closed forms. Any `leak_free: false` must be
  explained by the recorded names (the recommended instrumentation) or it is reported, not ignored.
- **1. Learned:** p_T ≥ p_C + 5 points in at least 2 of 3 seeds, and pooled p_T ≥ 3 × pooled p_C.
- **2. No trade-off:** the pooled mean of static targets per episode is not lower by more than 0.5.
- **3. First-clear relevant:** 1 and 2 hold, and (R ≥ 1 in at least 1 seed, or pooled L ≥ 5 / 300).
- **Outcomes:**
  - 3 holds → next is the crossing stage, with the landing penalty of section 5 as its own registered contract.
  - Only 1 and 2 hold → target 2 is learned but not early or not together with the statics. Next: add right-side
    timing (ER) as a registered follow-up.
  - 1 fails → the credit cannot overcome the exploration gap (near misses ≈ 0). Next is an exploration mechanism: a
    user decision.

**Secondary endpoints:**
- approach-zone visit rate;
- target-2 break tick and fall-after-break rate;
- static-six completion tick, T, falls;
- sweeps; crossings and landings (reported).

**Honest prediction:** uncertain.
- Encounters are rare: 0.77 % of training episodes, about 5–9 per run at C's rates. They are more frequent early in
  training (≈ 2 %), which is when v2 teaches avoidance.
- The credit changes the sign of the learning signal, but it cannot create visits to a region the policy does not
  reach.

**Cost:** about 3 × 33 min of training + 3 × 36 min of evaluation + about 30 min of replays, roughly 4 h. No long run
was started.

## 11. Open decisions

1. Accept `btt_reward_v3_t2` (b = 2.0) and the decision rule, or choose b = 4 before any run.
2. Approve the three-run experiment, optionally with seed 0 alone first as a signal check.
3. Whether to register `btt_reward_v3_l2` now or when landings become reachable.
4. Whether to add the trainer end-check instrumentation (grace period + names) before the long run.
5. Committing: nothing is committed.
