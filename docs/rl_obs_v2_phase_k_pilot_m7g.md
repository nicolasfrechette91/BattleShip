# RL M7g Phase K: the pilot (v1 control + v2 pilot)

Status (2026-09-24): **both pilot runs passed. Stopped for review.** Only the two isolated pilot runs were trained. The
six-run comparison, the seed 3/4 extension and every other training run were not started. Nothing was committed or
pushed.

The plan is in section 5 of [`rl_obs_v2_phase_k_campaign_m7g.md`](rl_obs_v2_phase_k_campaign_m7g.md) and the
pre-registered rule is in [`rl_obs_v2_experiment_proposal_m7g.md`](rl_obs_v2_experiment_proposal_m7g.md) (revision 2).
The machine-readable record is [`rl_obs_v2_phase_k_pilot_m7g.json`](rl_obs_v2_phase_k_pilot_m7g.json). The artifacts are
under `runs/m7g_k/_pilot` (git-ignored).

## 0. Summary

- **P1 v1 control (102,400 transitions): exact reproduction of M7e.**
  - Its final set's policy and statistics digests equal those of `runs/m7e/m7e_s0_v2/checkpoints/ckpt_000102400`
    (`5cec5fc4…` / `050acde9…`).
  - All 30 training episode rows are equal. M7e also has exactly 30 rows at or before 102,400, so the comparison is
    complete, not truncated. Every row field is equal except process identity (episode id, pid, port and startup timing).
- **P2 v2 pilot (204,800 transitions) through the real launcher: passed.**
  - The run verifies, and so do all three checkpoint sets (untrained, mid-run `ckpt_000102400` and `final`).
  - The per-key statistics are correct and the evaluation records clean metrics on every episode.
  - Measured throughput and memory are within the gates, with no failures, alerts or leaks.
- **Existing results are untouched.** `runs/` outside `runs/m7g_k` (86,893 files, 3.83 GB) was byte-identical before
  and after each invocation (aggregate `236eade0…`).
- **The full comparison is ready for a separate decision.** No blocking problem remains (section 6).

## 1. Commands and preflight

| step | command | result |
| --- | --- | --- |
| manifest (code changed, section 7) | `python rl/m7g_k_run.py manifest` | ok, 12 runs; code `78ee37f6…` |
| resources | `python rl/m7g_k_run.py resources` | commit 16.807 GiB ≥ 6.0 ok; physical 5.516 GiB ≥ 2.5 ok |
| dry run | `python rl/m7g_k_run.py pilot --dry-run` | exit 0, 0 blocking problems |
| P1 | `python rl/m7g_k_run.py pilot --arm v1` | exit 0 |
| P2 dry run | `python rl/m7g_k_run.py pilot --arm v2 --dry-run` | exit 0 (the recorded v1 pass satisfies the v2 gate) |
| P2 | `python rl/m7g_k_run.py pilot --arm v2` | exit 0 |

The dry run confirmed:
- **Manifest:** no drift.
- **Executable:** sha256 `1e7c62a0…`, equal to the file on disk.
- **Revisions:** parent HEAD `afa42fc` (with the uncommitted working tree); decomp `3c7fd5d05`, libultraship `805f1950`,
  torch `3aa9c973`, none differing from the gitlinks.
- **Profiles:** the 22 arm and identity checks of both pilot profiles all pass.
- **Output:** runs, evaluations, clear verification, logs and monitors all go under `runs/m7g_k/_pilot`.
- **Machine state:** CPU 0.2 %, disk 143 GiB free, no BattleShip process, no listener, no `SSB64_*` variable.

The resource gate was measured again at each launch: commit 16.858 / 16.561 GiB and physical 5.54 / 5.11 GiB (v1 / v2).

## 2. P1: the v1 control (`m7g_pilot_s0_v1`)

| check | result |
| --- | --- |
| trainer | exit 0, no stop; 96.4 s |
| post-run verification (M7d + Phase K identity) | ok, 0 problems |
| untrained `ckpt_000000000` | `68155f41…` / `06b1b370…` = the fresh construction (= M7d's seed-0 digest) |
| final (102,400, 200 updates) | `5cec5fc4…` / `050acde9…` = M7e `ckpt_000102400` **exactly** |
| training episodes | 30 (8 fall, 22 horizon); 0 invariant violations; 0 anomalies |
| lifecycle | 30 standby promotions, 0 cold fallbacks, 0 standby failures, threads 35 / 35 joined |
| evaluation (5 det + 20 stoch, metrics) | verified; 25 / 25 metric records ok; the 5 deterministic episodes are one identical trajectory |
| clears | 0 candidates |

## 3. P2: the v2 pilot (`m7g_pilot_s0_v2`)

| check | result |
| --- | --- |
| trainer (`train_once` → `train_m7.py`, live monitor) | exit 0, no stop; 206.5 s |
| post-run verification (M7d + Phase K identity) | ok, 0 problems: v2 network id, 76,818 parameters, contract digest, `MultiInputPolicy`, final statistics keys |
| untrained `ckpt_000000000` | `a968777d…` / `64d01c2a…` = the manifest's expected fresh construction |
| mid-run `ckpt_000102400` (200 updates) | provenance ok; loads as `MultiInputActorCriticPolicy` on the Dict space; statistics keys ok |
| `final` (204,800, 400 updates) | provenance ok; identity ok |
| per-key statistics | `norm_obs_keys` = segment_geometry, state, target_geometry; counts 102,405.0001 / 204,805.0001 per key; finite; `norm_reward` false; clip 10 |
| training episodes | 59 (7 fall, 52 horizon); 0 invariant violations; 0 anomalies; targets mean 3.31, max 5 |
| lifecycle | 59 standby promotions, 0 cold fallbacks, 0 standby failures, threads 64 / 64 joined |
| evaluation (5 det + 20 stoch, metrics) | verified; flags `SSB64_RL_SPATIAL=1` + `SSB64_RL_TARGET_DIAG=1`; 25 / 25 metric records ok; the 5 deterministic episodes are one identical trajectory |
| clears | 0 candidates |

The small evaluations are a plumbing check, not evidence: 25 episodes of a barely trained policy, from which no claim is
drawn. For the record, neither arm had a left entry, a seven-target episode or a target-2 break. v1 broke 2 targets
deterministically and 3.15 on average stochastically (max 6); v2 broke 3 and 3.30 (max 4).

## 4. Measured cost

| | v1 control | v2 pilot | v2 / v1 |
| --- | --- | --- | --- |
| end-to-end transitions/s | 1,183.6 | 1,046.8 | 0.884 |
| first 20 rollouts, transitions/s (matched) | 1,298.0 | 1,052.6 | 0.811 |
| collection per rollout | 3.46 s | 4.08 s | 1.18× |
| optimisation per rollout | 0.484 s | 0.780 s | 1.61× |
| parent peak working set / private | 286 / 460 MiB | 303 / 462 MiB | |
| worker peak working set (max) | 45.9 MiB | 46.3 MiB | |
| game process peak working set / private (max) | 106.1 / 369.6 MiB | 106.0 / 369.0 MiB | |
| system commit drawn (monitor max − pre-launch) | 4.76 GiB | 5.17 GiB | |
| available physical drawn (pre-launch − monitor min) | 0.67 GiB | 1.06 GiB | |
| peak BattleShip processes (monitor, 15 s samples) | 10 | 10 | limit 10 |
| max concurrent processes per worker (trainer, exact) | 2 | 2 | 5 × 2 = 10 |
| hard / soft alerts; lifecycle failures; startup failures | 0 / 0; 0; 0 | 0 / 0; 0; 0 | |

- **Throughput floor.** The pre-registered floor is 50 % of v1. v2 reached 81–88 %, so it is not a blocker.
- **Commit versus the gate.** The v2 commit draw (5.17 GiB) is slightly above the 5.0 GiB estimate. The 6.0 GiB gate
  keeps about 0.8 GiB of margin, and the lowest available commit during the run was 11.3 GiB.
- **How the memory was measured.** Both draws are system-wide deltas sampled every 15 s, so they include unrelated
  activity on the machine.
- **Projection [E] for the full comparison.**
  - Basis: the M7e seed-0 full run averaged 1,446 transitions/s over its rollouts. Scaling by the matched ratio 0.811
    gives about 35 minutes of training per v1 run and about 44 per v2 run.
  - That is about 4.0 h for the six runs, plus boots, verification, the historical snapshots (1–3 minutes each) and the
    post-hoc evaluations.
  - The small pilot evaluations took 80–86 s for 25 episodes including boots.

## 5. What the pilot proved, and what remains untested

**Now exercised on real runs** (items 1–5 and 7 of the campaign report's "not yet exercised" list):
- **PPO on real v2 observations:** real v2 rollouts and 400 updates, with the Dict rollout buffer on game data and finite
  per-key statistics.
- **v2 cost:** throughput and memory under training (section 4).
- **Checkpoints and verification:** the real v2 checkpoint cadence and post-run verification of a real v2 run.
- **Launch path:** `train_once` driving `train_m7.py` on a v2 profile under the live monitor.
- **Metrics on trained policies:** the recorder on both arms' trained episodes, including the identical deterministic
  episodes.
- **The control:** v1 reproduces M7e exactly on the current executable and code, which is the input to gate 0.

**Still untested:**
- A genuine v2 → v2 resume. Only the guard is tested; the protocol default is `--restart-partial`.
- Native verification of a real Track 1 clear. None exists yet; the TAS stands in.
- The recorder's positive paths (a left entry, seven targets, target 2) on trained-policy episodes. They are validated
  only on the fixtures and the TAS, and none occurred in these 50 episodes.
- Throughput and memory at the full 3,072,000-transition budget (projected, not measured).

## 6. Readiness for the full comparison (a separate decision)

After the pilot, `python rl/m7g_k_run.py train --dry-run` reports:
- 0 blocking problems;
- plan: `m7g_s0_v1` would train from scratch, and the other five runs wait in the registered order;
- no manifest drift and no directory-plan problems;
- resource gate ok (commit 16.50 GiB, physical 5.09 GiB);
- `status`: all ten comparison and extension runs absent, no decisions recorded.

The campaign unit suite passes 13/13 after the pilot. The analysis now sees `state["pilot"]["control_reproduction"].ok ==
true`, which its integrity check requires.

**Constraint for the decision.** The pilot evidence is tied to the code fingerprint `78ee37f6…`. Any later change to
`rl/*.py` or a profile changes the manifest. The campaign would then launch on a code fingerprint the control
reproduction did not see. Rerunning P1 alone (about 3 minutes plus the snapshots) restores that link.

## 7. Change made in this step (before any training)

`cmd_pilot` in `rl/m7g_k_run.py`, as prepared, did not stop between a failed v1 control reproduction and v2. It also
wrote pilot logs, monitors and evaluation bookkeeping into the campaign's `_matrix`. Fixed:

- a control reproduction that is not exact stops the pilot before any evaluation and before v2;
- `pilot --arm v1|v2`: v2 alone is refused unless a passed v1 (verified, exact reproduction, evaluation passed) is
  recorded;
- every checkpoint set (untrained, mid-run, final) goes through provenance plus the loaded model and statistics identity
  of the arm;
- throughput (end to end and rollout-matched), the 50 % floor, memory and process peaks are recorded;
- `runs/` outside `runs/m7g_k` is fingerprinted before and after every invocation;
- pilot logs, monitors, verification records, evaluation bookkeeping and `pilot_record.json` are kept under
  `runs/m7g_k/_pilot`. The campaign state keeps only `state["pilot"]`, which the analysis requires.
- `run_label` / `evaluate_run_label` take optional `monitor_path` / `book` arguments; the campaign defaults are unchanged.

Tests:
- new unit case `unit_pilot_gating`: v2 refused without a passed v1, and a synthetic control mismatch stops before
  evaluation and v2;
- `unit_dry_runs` accepts the pilot dry run's refusal once a pilot directory exists;
- campaign unit suite 13/13 (before and after the pilot); readiness unit suite 6/6; `git diff --check` clean.

No change was made to gameplay, native code, rewards, observations, actions, stepping, the six comparison profiles or the
fixtures.
