# M7m feasibility gate: results (no training)

Date: 2026-09-25/26 (UTC). Design: `docs/rl_sweep_consolidation_m7m_design.md`. Plan, registered before any check:
`docs/rl_sweep_consolidation_m7m_feasibility_plan.json`. Harness: `rl/m7m_feasibility.py`. Raw outputs:
`runs/m7m/feasibility/` (git-ignored; `summary.json` sha `11076040…`).

**Registered GO decision.** F1, F2, F3, the harness validation, F4 and the verification all pass. F5 is diagnostic only.

- Nothing was trained.
- No PPO update ran.
- No M7l run was extended.
- No RNG state was inspected.

## Registered identities

- **Anchor** (`…_anchor.json`, sha `7a1bbf3a…`):
  - Source: `m7l_t2_s1`, `episode_20260925T190612Z_49414363`, SB3 timesteps 2,723,840 → 2,744,320.
  - Discovered by a policy trained under **btt_reward_v3_t2** (canonical sha `fa74d7d7…`).
  - Trajectory: 3,600 rows, native digest `8ccf81f2…`. Breaks 9@41, 0@119, 4@165, 5@580, 3@800, 2@837, 7@1030; ends at
    the horizon.
  - Permitted use: start states only. Excluded: supervised targets, weights, and the user's fixtures and TAS.
- **Observation table** (`…_anchor_observations.json`, sha `88806074…`, 475 KB): o_τ for τ = 1..1020, produced by F1.
- **Plan** (`…_feasibility_plan.json`, sha `433b784f…`).
- **Warm starts.** Phase K reward-v2 finals, all at num_timesteps 3,072,000 with obs_rms count 3,072,005.0001; the M7l
  control check was OK for each.

  | seed | checkpoint.json | model.zip | vecnormalize.pkl | policy digest | Phase K deterministic digest / return |
  |---|---|---|---|---|---|
  | 0 | `b04ca3c1…` | `36fea1fd…` | `85ca39eb…` | `6edb91f4…` | `868152fa…` / −1.6 |
  | 1 | `9d9cb38a…` | `57d9060f…` | `9c7295e9…` | `086f73ad…` | `dc0072c7…` / −1.6 |
  | 2 | `0543d7d5…` | `1c26908c…` | `38bcc4e3…` | `ce9a8e0a…` | `cf18b7cb…` / −0.6 |

- **Registration correction** (`registration_log.jsonl`). The anchor and plan were rewritten once, before any check read
  them. The field `reward_canonical_sha256` had recorded the label boolean `True` instead of the hash. The superseded
  shas are logged.

## Results

| Check | Denominator | Result |
|---|---|---|
| F1 source replay | 3 fresh processes | 3/3 exact: digest, consumed ticks 0..3599, break table, horizon end, final observation (host_frame included); the three o_τ tables are identical, host_frame included |
| F2 encoding | 7 checks | 7/7 |
| F3 cut mechanics (M7m training worker) | 57 cuts (7 landmarks + 50 random) | 57/57 exact (o_τ = table, mask, label, reward reference, one policy step with v2 policy terms only); host_frame equal 57/57 |
| F3 full cuts (anchor tail through `step()`) | τ = 42 / 838 / 1020 | 3558 / 2762 / 2580 policy steps (= 3600 − τ); returns 2.442 / −1.762 / −1.58, policy-only as expected; full digest = anchor; m7d validator clean |
| Harness validation | 3 warm starts | 3/3 deterministic tick-0 digests and returns = Phase K final evaluation, with the diagnostic flag on |
| F4 foothold (W0 = [901, 1020]) | 30 per seed | s0 **9/30**, s1 **9/30**, s2 **4/30**; all three are footholds, so F4 passes 3/3. No window saturated, so W1/W2 were not needed: 90 episodes out of a cap of 270 |
| F5 diagnostic | 150 (50 per seed) | complete, see below |
| Verification replays | 110 (F5 target-2 episodes, F4 last-window successes, the first of each cell) | 110/110 exact (digest, consumed ticks, first-break table) |
| No-learning vector test | 2 workers with standby, neutral actions | anchored τ 1005 and 949 delivered equal to the table; vector steps seen = policy steps; returns policy-only; 2,885 prefix ticks never reached PPO |

**F4 detail.** Successes by cut, pooled over the three seeds (5 episodes per cut per seed):

| τ | 901 | 925 | 949 | 973 | 997 | 1020 |
|---|---|---|---|---|---|---|
| successes / 15 | 1 | 1 | 1 | 5 | 3 | 11 |

- Of 22 successes, 17 break target 7 within about 30 ticks of the anchor's own break at tick 1030. The other 5 come
  from later policy navigation (ticks 1880–2630).
- Episode ends: 67 at the deadline, 22 at success, 1 fall. No left entry.
- At these untrained rates, a W0 block of 10 would pass (≥ 5 successes) with probability about 15 % for seeds 0 and 1,
  and 0.6 % for seed 2.
- For comparison, from tick 0 the same policies break target 7 by tick 2699 in 36, 83 and 8 of 100 final stochastic
  episodes.

**F5 diagnostic** (never gating; not proof either way). Pooled registered classification: **positive**. Target-2 group
n = 66, mean policy-phase v2 return −1.869; other group n = 84, mean −2.466; Δ = +0.60, SE 0.14. It is strongly
confounded by cut:

| cut | 801 | 810 | 819 | 828 | 837 |
|---|---|---|---|---|---|
| target 2 broken / 30 | 2 | 2 | 2 | 30 | 30 |

- 62 of 66 target-2 breaks happened at tick 837, the anchor's own up-B carried into the policy phase. From 18 or more
  ticks before the break, the policy broke target 2 in 6 of 90 episodes.
- Falls: 4 of 66 after a target-2 break, 1 of 84 without.
- Per seed: s0 positive, s1 inconclusive (within 2 SE), s2 positive.
- 2 of 150 swept all seven right targets by tick 2699. No clears, no left entries.

## Events and deviations

- **Launch gate.** F1 needed 4 readings: physical memory was 3.70 to 3.78 GiB, then 4.71 GiB. Every other phase passed
  on its first reading. There was no in-run memory stop and no leftover process after any phase.
- **F3 run 1 was a harness defect**, not a worker failure. At the three full cuts the harness took a neutral probe step
  at τ and then replayed anchor rows τ + 1 onward. The plan requires the anchor's own rows, so the digests could not
  match, and τ = 42 lost breaks. Run 1 had 57/57 cuts exact.
  - Run 1 is kept as `f3_run1_harness_defect.json` and `f3_cuts_run1_harness_defect.jsonl`.
  - The harness was corrected to the registered plan; the plan itself did not change. The full rerun passed.
- **Regression suites after the inherited edits:**
  - M7b config 16/16, M7h 13/13, Phase K 6/6, M7l unit 5/5, M7m 5/5.
  - The Phase K suite needed its profile-set filter to exclude `rl/configs/m7m`, the same one-line edit M7l made.
  - Its `unit_checkpoint_identity` case failed once, only while F4's game processes were running. It passed once they
    had finished.
  - The M7g isolation scan still reports only the three pre-existing M7h files.
- **Defaults unchanged.** All 46 pre-existing profiles resolve to byte-identical identities (fingerprints, summaries,
  resolved configs, extra_env, trainer configs) before and after.

## Corrected schedule and proposed paired budget

- **Schedule.** As in design section 4:
  - Windows [max(1, τ* − 119), τ*] for τ* = 1020, 900, …, 60; W8 = [1, 60].
  - Blocks of 10 counted anchored outcomes; ≥ 5 successes move the pointer back.
  - Stale and excluded outcomes are logged, not counted.
  - After W8 passes, every later start is a tick-0 start.
  - Cut τ replays consumed ticks 0..τ−1, and the policy acts from input tick τ with at most 3600 − τ steps.
- **Budget.** Six warm-started runs (E_j, K_j for j = 0–2) of +1,536,000 policy-controlled transitions each: 9,216,000
  in total, cumulative 4,608,000 per run.
- **Prefix cost** (E only, counted separately). Measured at about 0.93 s per ~960-tick dispatch while the vector env
  waits. About 205–240 anchored starts per E run is roughly 3–4 minutes of wall time and up to about 230,000 prefix
  ticks if the pointer stays in W0.
- **Anchored outcomes.** About 205–240 counted outcomes (20–24 blocks) per E run. Completing the schedule needs 9 passing
  blocks, and the untrained W0 block-pass odds are about 15 / 15 / 0.6 %. **Completion is not assumed.** A stall at W0,
  or at the target-2 step in W1, is a plausible outcome, which the proposed rule records as null or anchored-only.
