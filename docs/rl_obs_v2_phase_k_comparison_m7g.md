# RL M7g Phase K: the six-run v1-versus-v2 comparison and its decision

Status (2026-09-24): **complete. Decision recorded: gate 7, `no_benefit`. Stopped for review.** The seed 3/4
extension is not unlocked and was not launched, and no longer training was started. Code and profiles were not edited
during the campaign. Nothing was committed or pushed.

The design and rule are in [`rl_obs_v2_experiment_proposal_m7g.md`](rl_obs_v2_experiment_proposal_m7g.md) (revision 2)
and the pilot in [`rl_obs_v2_phase_k_pilot_m7g.md`](rl_obs_v2_phase_k_pilot_m7g.md). The machine-readable record is
[`rl_obs_v2_phase_k_comparison_m7g.json`](rl_obs_v2_phase_k_comparison_m7g.json). The driver's own analysis is
`runs/m7g_k/_matrix/analysis_n3.json` (git-ignored).

## 0. Summary

- **Decision (pre-registered response, verbatim):** "v1 stays the default; v2 stays available, unchanged and
  documented; record 'no measurable benefit of structured perception at 3.072M transitions'; the next milestone proceeds
  with category D on v1."
- **Why gate 7:**
  - no verified clear in either arm (K = 0 / 0);
  - no crossing or left-target break in any final stochastic episode (X = 0 / 0);
  - the seeds disagree in sign on targets: D = −0.66, −0.89, +0.39, so D̄ = −29/75 ≈ −0.387, and gate 5 does not fire;
  - no seed reached +0.5, so gate 6 (the extension) does not fire.
- **Integrity passed:**
  - all six runs verified;
  - the existing `runs/` tree was byte-identical after every run;
  - census 6,010 / 6,010;
  - 0 metric problems, 0 alerts, 0 leaks, peak 10 processes.
- **v1 = M7e, bit for bit.** Every v1 run reproduces the M7e run of the same seed exactly: every training row, the final
  digests, and all 22 evaluation label/mode pairs.
- **Nothing reached the ceiling at the final checkpoint.** Across all 6,010 episodes there was no clear, no left entry
  and no seven-target episode. There was one left-target break, a mid-run v2 episode that broke target 6 without
  crossing (section 5).

## 1. What ran

| step | command | UTC | result |
| --- | --- | --- | --- |
| training, registered order s0v1, s0v2, s1v2, s1v1, s2v1, s2v2 | `rl/m7g_k_run.py train` under a per-launch gate (below) | 02:20 → 06:21 (4.0 h) | 6 / 6 verified, 0 problems, 0 deviations |
| evaluation (M7e protocol + `btt_eval_metrics_v1`) | `python rl/m7g_k_run.py evaluate` | 06:22 → 10:17 (3.9 h) | 67 / 67 labels verified (66 + random baseline) |
| clear verification | `python rl/m7g_k_run.py verify-clears` | | 0 candidates (no native clear anywhere) |
| census | `python rl/m7g_k_run.py census` | | planned 6,010 = 6 × 985 + 100; executed 6,010; missing 0 |
| rule | `python rl/m7g_k_run.py analyze` | 10:17:18 | gate 7 `no_benefit`, `extension_required` false, recorded once |

**Checks before each launch.** The driver checks drift, resources and isolation only once at the start of `train`, and
never checks the pilot control. So the unchanged `train` command ran from a scratch wrapper (not in the repository,
sha256 `b2a90c8e…`), which used the driver's existing `LAUNCHER` hook. Before each of the six launches it re-checked,
and recorded under `runs/m7g_k/_matrix/prelaunch/<run>.json`:
- manifest drift;
- the passed pilot control on the same code fingerprint (`78ee37f6…`);
- the resource gate (commit and physical, separately);
- output isolation (the directory plan and a fresh run directory; no resume);
- the run's identity preflight;
- the provenance of every already-verified run's final checkpoint set.

It then called the default launcher `m7d_run.train_once` with the driver's own arguments.

All six gates passed:
- available commit was 16.9–19.9 GiB (gate 6.0) and available physical 5.2–7.8 GiB (gate 2.5);
- the driver's own start-of-campaign checks also passed (manifest frozen to `runs/m7g_k/_matrix/manifest.json`).

## 2. The rule (revision 2, n = 3, m = 2), at `final` = 3,072,000 transitions

| arm | seed | verified clears (200 episodes) | ceiling episodes (100 stoch.) | T (mean targets, 100 stoch., no verified clear) |
| --- | --- | --- | --- | --- |
| v1 | 0 | 0 | 0 | 472/100 = 4.72 |
| v1 | 1 | 0 | 0 | 475/100 = 4.75 |
| v1 | 2 | 0 | 0 | 427/100 = 4.27 |
| v2 | 0 | 0 | 0 | 406/100 = 4.06 |
| v2 | 1 | 0 | 0 | 386/100 = 3.86 |
| v2 | 2 | 0 | 0 | 466/100 = 4.66 |

- D (v2 − v1): seed 0 −33/50, seed 1 −89/100, seed 2 +39/100. D̄ = −29/75 (−0.3867).
- **Gate by gate:**
  - **Gate 0:** no integrity problem.
  - **Gates 1–3:** K = 0 in both arms.
  - **Gate 4:** X = 0 in both arms; neither a single-arm crossing nor a single-seed crossing.
  - **Gate 5:** does not fire. D is not positive in every seed, and not negative in every seed; D̄ is also above −0.5,
    so v2 is not recorded as worse.
  - **Gate 6:** requires one seed with D ≥ +0.5 and one with D ≤ −0.5. The largest D is +0.39, so it does not fire.
  - **Gate 7:** decides.
- I checked this walk by hand against `decide()`. The exact fractions above are the recorded values.

## 3. Per seed and arm: final evaluation (100 stochastic + 100 deterministic)

| | v1 s0 | v1 s1 | v1 s2 | v2 s0 | v2 s1 | v2 s2 |
| --- | --- | --- | --- | --- | --- | --- |
| verified clears / native clears | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| stochastic targets mean (= T) | 4.72 | 4.75 | 4.27 | 4.06 | 3.86 | 4.66 |
| stochastic targets max | 6 | 5 | 6 | 5 | 5 | 6 |
| stochastic distribution | 4:40 5:48 6:12 | 3:1 4:23 5:76 | 3:3 4:69 5:26 6:2 | 3:1 4:92 5:7 | 2:3 3:20 4:65 5:12 | 3:7 4:25 5:63 6:5 |
| stochastic ends (horizon / fall) | 99 / 1 | 99 / 1 | 100 / 0 | 100 / 0 | 97 / 3 | 100 / 0 |
| first left entries (stoch. / det.) | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| left-target (1 / 6 / 8) breaks | 0 | 0 | 0 | 0 | 0 | 0 |
| seven-target episodes | 0 | 0 | 0 | 0 | 0 | 0 |
| target 2 breaks (stochastic) | 1 | 0 | 2 | 0 | 1 | 5 |
| deterministic targets (all 100 identical) | 2 | 2 | 3 | 2 | 4 | 1 |
| deterministic collapse share (max run / 3,600) | **0.507 (collapsed)** | 0.250 | 0.341 | 0.286 | 0.039 | 0.295 |
| diagnostic return, stochastic mean | 1.075 | 1.123 | 0.670 | 0.460 | 0.200 | 1.060 |

Every episode carries a clean `btt_eval_metrics_v1` record: 6,010 of 6,010 are ok, with 0 metric problems. The
deterministic play of every final set is one repeated trajectory (1 unique action digest per 100 episodes). Returns are
diagnostic only.

## 4. Per seed and arm: every evaluated checkpoint (initial, 9 curve points, final; 985 episodes per run)

| | v1 s0 | v1 s1 | v1 s2 | v2 s0 | v2 s1 | v2 s2 |
| --- | --- | --- | --- | --- | --- | --- |
| native clears | 0 | 0 | 0 | 0 | 0 | 0 |
| first left entries | 0 | 0 | 0 | 0 | 0 | 0 |
| left-target break episodes | 0 | 0 | 0 | 0 | 0 | **1** (target 6, at 1,228,800) |
| seven-target episodes | 0 | 0 | 0 | 0 | 0 | 0 |
| target 2 break episodes | 5 | 8 | 10 | 8 | 4 | 17 |

Stochastic targets mean per checkpoint (60 episodes at the curve points, 100 at initial and final):

| transitions | v1 s0 | v2 s0 | v1 s1 | v2 s1 | v1 s2 | v2 s2 |
| --- | --- | --- | --- | --- | --- | --- |
| 0 (initial) | 3.19 | 3.17 | 3.30 | 3.11 | 3.23 | 3.22 |
| 307,200 | 3.47 | **3.73** | 3.38 | 3.15 | 3.32 | **3.35** |
| 614,400 | 3.53 | **4.00** | 3.85 | 3.30 | 3.32 | **3.50** |
| 921,600 | 3.73 | **3.92** | 4.30 | 3.23 | 3.58 | **3.68** |
| 1,228,800 | 3.98 | 3.30 | 4.27 | 3.62 | 2.97 | **4.12** |
| 1,536,000 | 3.95 | 3.83 | 4.62 | 3.85 | 4.07 | **4.32** |
| 1,843,200 | 4.03 | 3.68 | 4.93 | 3.72 | 4.20 | **4.42** |
| 2,150,400 | 4.17 | 3.95 | 4.77 | 4.03 | 4.12 | **4.48** |
| 2,457,600 | 4.22 | 3.88 | 4.72 | 3.90 | 4.47 | 4.45 |
| 2,764,800 | 4.58 | 3.98 | 4.77 | 3.88 | 4.23 | **4.82** |
| 3,072,000 (final) | 4.72 | 4.06 | 4.75 | 3.86 | 4.27 | **4.66** |

Bold marks v2 above v1 at that point. Sign agreement across the seeds holds only at initial and at 2,457,600 (v2 below
v1 in all three seeds at both).
- **Seed 1:** v2 is below v1 at every point.
- **Seed 0:** v2 is above v1 up to 921,600, then below.
- **Seed 2:** v2 is above v1 at 9 of 10 trained points.

**Random baseline** (100 episodes, metrics on): targets mean 3.23 (max 6), 30 falls, 4 target 2 breaks, 0 left entries,
0 left-target breaks, 0 seven-target episodes, 0 clears.

## 5. The one left-target break (reported, never gating)

- **Where:** `m7g_s2_v2`, checkpoint 1,228,800, a stochastic episode (`episode_20260924T095405Z_5d068ee4`). It broke 6
  targets (9, 4, **6**, 5, 0, 3) and ended at the horizon. Target 6 (spawn (−3300, 3300), left of the wall and above
  its top at y 3000) broke at consumed tick 1871.
- **No crossing:** there was no left entry, and Mario's minimum live x was −1650.0, the wall face.
- **Plausible mechanism:** B (special) was pressed at ticks 1839–1845 and at 1868 / 1871, so a projectile over the wall
  top is plausible. This is a **hypothesis, not verified**: the artifact stores actions only, and no replay was run.
- **Rule impact:** as far as the prior M7f replay set and this campaign show, this is the first break of target 1, 6 or
  8 by a trained policy. It is not in any final evaluation, so it does not enter X.

## 6. Throughput and resource use (training, per run)

| | v1 s0 | v1 s1 | v1 s2 | v2 s0 | v2 s1 | v2 s2 |
| --- | --- | --- | --- | --- | --- | --- |
| learn wall | 2,018 s | 1,981 s | 1,994 s | 2,547 s | 2,513 s | 2,493 s |
| end-to-end transitions/s | 1,523.4 | 1,552.0 | 1,541.5 | 1,206.9 | 1,223.2 | 1,232.9 |
| collection transitions/s | 1,770.5 | 1,803.5 | 1,784.2 | 1,447.9 | 1,470.2 | 1,484.6 |
| training episodes (fall) | 862 (22) | 853 (6) | 889 (71) | 901 (77) | 869 (33) | 857 (22) |
| peak BattleShip processes (monitor / per worker) | 10 / 2 | 10 / 2 | 10 / 2 | 10 / 2 | 10 / 2 | 10 / 2 |
| system commit drawn (monitor max − pre-launch) | 5.04 GiB | 5.15 GiB | 5.16 GiB | 5.30 GiB | 5.21 GiB | **5.58 GiB** |
| available physical drawn | 1.00 GiB | 1.10 GiB | 1.13 GiB | 1.27 GiB | 1.30 GiB | 1.36 GiB |
| parent peak working set / private | 298 / 460 MiB | 297 / 460 MiB | 299 / 460 MiB | 314 / 463 MiB | 315 / 462 MiB | 313 / 463 MiB |
| game process peak working set / private (max) | 212 / 442 MiB | 106 / 370 MiB | 113 / 370 MiB | 114 / 370 MiB | 113 / 370 MiB | 109 / 370 MiB |
| hard / soft alerts, lifecycle failures | 0 / 0, 0 | 0 / 0, 0 | 0 / 0, 0 | 0 / 0, 0 | 0 / 0, 0 | 0 / 0, 0 |
| post-hoc evaluation wall | 36.2 min | 35.7 min | 35.6 min | 41.1 min | 41.3 min | 41.3 min |

- **Throughput.** v2 averaged 0.79× v1 end to end (1,221 versus 1,539 transitions/s), consistent with the pilot's
  0.81–0.88.
- **Commit versus the gate.**
  - The commit draw peaked at 5.58 GiB (v2 s2), above the 5.0 GiB estimate and 0.42 GiB under the 6.0 GiB gate. On this
    machine at least 14 GiB of commit stayed available throughout.
  - Before any longer or larger run, consider raising the commit gate to about 7 GiB (not changed here).
  - These draws are system-wide deltas sampled every 15 s.
- **Game process outlier.** v1 s0 had one game process peaking at 212 MiB working set and 442 MiB private, versus about
  110 / 370 elsewhere. Nothing failed and nothing leaked.

## 7. Integrity evidence

- **Training runs:** all six verified. Each run's checks:
  - the untrained checkpoint equals the manifest's fresh construction;
  - checkpoint cadence, per-key statistics (v2) and observation / network / executable / revision identity are correct;
  - no episode invariant violation, no lifecycle failure, standby threads all joined;
  - leak-free, and your user config byte-identical and untouched;
  - the existing `runs/` tree byte-identical after every run.
- **v1 = M7e.** `m7g_s{0,1,2}_v1` equal `runs/m7e/m7e_s{0,1,2}_v2`:
  - training: every row (862 / 853 / 889) and every final digest;
  - evaluation: `(native_action_digest, targets, end_reason)` identical in all 22 label/mode pairs per seed, so the
    evaluation-only diagnostic flag changed nothing in play.
- **Evaluation:** 67 / 67 labels verified (row invariants, metrics, flags `SSB64_RL_TARGET_DIAG=1` plus
  `SSB64_RL_SPATIAL=1` for v2 only), leak-free, peak 10 processes.
- **End state:** manifest drift after the campaign `[]`; `git diff --check` clean. The executable (`1e7c62a0…`), both
  fixtures and your user config are unchanged.

## 8. What this does and does not show

- At 3.072M transitions with this PPO setup, v2's structured spatial observation gave no measurable benefit on the
  pre-registered outcomes: no clears, no crossings, no seven-target episodes.
- On final targets, v2 is lower in two seeds and higher in one; the mean difference is −0.39 targets.
- v2 learned early in seeds 0 and 2 but not in seed 1. The rule does not treat any of this as evidence.
- Neither arm reached the ceiling. Both final policies stay right of the wall, and the left targets remain out of reach
  apart from one mid-run v2 episode.
- The deterministic (argmax) plays stay weak in both arms (1–4 targets). v1 seed 0 is collapsed, as in M7e.
- No evidence here supports a longer v2 run. The extension is not unlocked; the next step under the rule is category D
  (the frontier / exploration intervention) on v1, a separate decision.

## 9. Working tree

No file under `rl/` or `rl/configs/` was edited during the campaign, and the code fingerprint is `78ee37f6…`
throughout. New in this step: this document and its JSON.

The Phase K files had been staged in the index (`A`) before the campaign started. That was not done by me, and I left
the index as found. Nothing was committed or pushed. decomp is clean on `rl-main` (`3c7fd5d05`); libultraship and torch
are unchanged.
