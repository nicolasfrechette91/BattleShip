# M7p geometry-scaling comparison: durable handoff / status document

Purpose: a new session or a compacted context must be able to see, without re-deriving anything, what was authorised,
what is registered, what has run, what is pending, and how to continue WITHOUT launching anything twice. Read this and
`runs/m7p/campaign/_matrix/state.json` before touching the campaign. The driver appends one dated line per phase boundary
to the log section at the end of this file.

## Authorization (the user's message of 2026-09-28, quoted in substance)

"The geo4 diagnostic passed. I authorize one bounded three-seed comparison against the matched M7n v3 controls, after
final registration and verification. No further approval is needed between preparation, passing preflight and launch."
Constraints: experimental observation `btt_policy_obs_v3_geo4` exactly as tested; control = original v3; reward v2, Track 1,
tick-0 starts, network and PPO unchanged; three fresh runs, seeds 0-2, 3,072,000 transitions each; the diagnostic checkpoint
and optimizer state are never continued or imported; the M7n evaluation protocol. Before launch: freeze manifest, profiles
and rule (M7n corrected clear / crossing semantics and paired thresholds, adapted to v3 vs geo4; regression, inconclusive,
incomplete, invalid outcomes; denominators, ties, precedence; lower saturation never sufficient); verify control
compatibility on the final code (all three seeds, digests and rows, final evaluation integrity, every control input
recomputed; state re-executed vs validated from records; stop on mismatch, never train replacements); resolve the M7n
10/11 unit result under a fresh root; pin the offline sample and measurement procedure (saturation on policy and random
samples + sensitivity at registered checkpoints; never alters training or selects checkpoints). Then run, evaluate, verify
every clear / crossing candidate, apply the frozen rule once. Report paired per-seed targets, qualified crossings,
left-target breaks, native-verified clears, target-2 breaks, L / R, falls, deterministic collapse, and whether the
saturation reduction persists. Keep v3 selected until the registered comparison decides otherwise. Stop on a failed gate,
drift, hard alert, provenance mismatch, resource failure or process leak; preserve partial results; no automatic
repair-and-relaunch; no extra seeds, budget extensions, scale tuning, reward changes, curricula, videos, commits, pushes,
branches or PRs. Stop after the registered three-seed decision.

## Identity of the campaign

| item | value |
| --- | --- |
| driver | `rl/m7p_campaign.py` (adapted from `rl/m7o_campaign.py`); matrix `rl/m7p_matrix.py`; rule code `rl/m7p_analysis.py`; measurements `rl/m7p_measure.py` |
| profiles | `rl/configs/m7p/m7p_geo4_s{0,1,2}.toml` (= `rl/configs/m7n/m7n_s{s}_v3.toml` except run.name, run.notes, run.output_root, contracts.observation) |
| experimental contract | `btt_policy_obs_v3_geo4` (`rl/m7p_obs_geo4.py`): segment_geometry lengths / 8,000, velocities / 200; everything else v3 |
| control | `runs/m7n/campaign/m7n_s{0,1,2}_v3` (frozen M7n v3 runs, evaluations and crossing documents) |
| rule | `docs/rl_geometry_scale_m7p_decision_rule.json` (schema `m7p_decision_rule_v1`) |
| manifest | `docs/rl_geometry_scale_m7p_manifest.json`; frozen copy `runs/m7p/campaign/_matrix/manifest.json` once `train` runs |
| control records | `runs/m7p/campaign/_control/control_check.json` (R1) and `control_verify.json` (records) |
| state | `runs/m7p/campaign/_matrix/state.json` (runs, evaluations, clears, crossings, measurements, decisions, events) |
| campaign log | `runs/m7p/campaign_all.log` (stdout of `python rl/m7p_campaign.py all`) |
| guard logs | `runs/m7p/campaign/_guard/logs/<run>__<utc>.log`; a stopped run is moved to `runs/m7p/campaign/_partial/` |
| decision record | `runs/m7p/campaign/_matrix/analysis_n3.json` (written once by `analyze`) |
| executable | `build-us/Release/BattleShip.exe` sha256 `748dbad9…` (pinned in the manifest) |
| selected default | `btt_policy_obs_v3_entities` (v3) until the recorded decision says otherwise |

## Commands, in order (each refuses to redo a completed phase)

```bash
python rl/m7p_analysis.py self-test
python rl/m7p_campaign.py manifest
python rl/m7p_campaign.py control-check
python rl/m7p_campaign.py train --dry-run
python rl/m7p_campaign.py all
python rl/m7p_campaign.py status
```

`all` = train (s0, s1, s2, each behind the launch gate) -> evaluate -> verify-clears -> verify-crossings -> measure -> analyze.
Re-invoking `all` after a stop does NOT relaunch a stopped or partial run (the plan says STOP and exits); a completed but
unverified directory is verified, never retrained. A recorded n3 decision is never re-decided.

## Duplicate-launch protection

- Before any command: `tasklist | findstr BattleShip` must be empty and `runs/m7p/campaign/_matrix/state.json` must be read.
- If `state.json` lists a run as `pending`/`partial` with a live trainer pid in the guard log, the campaign is RUNNING: do
  not start another `all`; watch `runs/m7p/campaign_all.log`.
- If a run directory exists without `training_summary.json` and no trainer is alive, it is a preserved partial: stop and report.

## Phase log (appended by the driver; manual notes marked "manual")
- 2026-09-28T02:55:52+00:00 manual: preparation done: rule self-test PASS (m7p_analysis), profiles created, matrix/driver/measure validated offline on a temporary root, M7n unit_matrix assertions re-run under a fresh campaign root (ALL PASS; the default-root 10/11 is the pre-launch 'directories do not exist' precondition only), manifest built (docs/rl_geometry_scale_m7p_manifest.json)
- 2026-09-28T02:56:10+00:00 pid 18340: control-check started (R1 3 x 102,400 + record verification)
- 2026-09-28T03:02:45+00:00 pid 18340: control-check finished: R1 PASS, records PASS, bound=yes
- 2026-09-28T03:04:35+00:00 manual: control-check PASS (R1 3/3 seeds bit-exact: 28/29/26 rows; record verification PASS; bound to manifest c61d947bb7b6 / control-check fp 5e73a04c0722); preflight 0 blocking problems; LAUNCHING 'python rl/m7p_campaign.py all' -> log runs/m7p/campaign_all.log (single launch; do not start another)
- 2026-09-28T03:04:37+00:00 pid 24500: campaign `all` started
- 2026-09-28T03:04:37+00:00 pid 24500: manifest frozen at runs/m7p/campaign/_matrix/manifest.json (sha256 6c5cd775912e)
- 2026-09-28T03:04:50+00:00 pid 24500: m7p_geo4_s0: training launched (guard log under runs/m7p/campaign/_guard)
- 2026-09-28T03:53:11+00:00 pid 24500: m7p_geo4_s0: training finished and verified (48.3 min)
- 2026-09-28T03:53:16+00:00 pid 24500: m7p_geo4_s1: training launched (guard log under runs/m7p/campaign/_guard)
- 2026-09-28T04:42:14+00:00 pid 24500: m7p_geo4_s1: training finished and verified (48.9 min)
- 2026-09-28T04:42:20+00:00 pid 24500: m7p_geo4_s2: training launched (guard log under runs/m7p/campaign/_guard)
- 2026-09-28T05:31:14+00:00 pid 24500: m7p_geo4_s2: training finished and verified (48.9 min)
- 2026-09-28T05:31:14+00:00 pid 24500: phase train completed
- 2026-09-28T05:31:16+00:00 pid 24500: evaluation phase started (M7n protocol, 985 episodes per run)
- 2026-09-28T06:28:54+00:00 pid 24500: m7p_geo4_s0: all evaluation labels verified
- 2026-09-28T07:26:04+00:00 pid 24500: m7p_geo4_s1: all evaluation labels verified
- 2026-09-28T08:23:31+00:00 pid 24500: m7p_geo4_s2: all evaluation labels verified
- 2026-09-28T08:23:31+00:00 pid 24500: phase evaluate completed
- 2026-09-28T08:23:33+00:00 pid 24500: verify-clears finished (OK)
- 2026-09-28T08:23:33+00:00 pid 24500: phase verify-clears completed
- 2026-09-28T08:23:45+00:00 pid 24500: verify-crossings finished (OK)
- 2026-09-28T08:23:45+00:00 pid 24500: phase verify-crossings completed
- 2026-09-28T08:25:26+00:00 pid 24500: offline measurements recorded
- 2026-09-28T08:25:26+00:00 pid 24500: phase measure completed
- 2026-09-28T08:25:33+00:00 pid 24500: DECISION recorded: failure_regression (gate 3 target_regression); selected = v3; record runs/m7p/campaign/_matrix/analysis_n3.json
- 2026-09-28T08:25:33+00:00 pid 24500: phase analyze completed
- 2026-09-28T08:25:33+00:00 pid 24500: campaign `all` completed
- 2026-09-28T08:28:30+00:00 manual: CAMPAIGN COMPLETE. Decision failure_regression (gate 3; D -0.61/-0.60/-0.61); v3 stays selected; seed-1 geo4 final produced one replay-verified qualified crossing + left-target break (X=1 in one seed; not deciding). Results doc docs/rl_geometry_scale_m7p_results.md. Nothing pending; do NOT relaunch.
- 2026-09-28 manual (post-campaign addenda, decision unchanged): crossing addendum (docs/rl_geometry_scale_m7p_crossing_addendum.md), wall-top census 2/100 L0 landings (docs/rl_geometry_scale_m7p_walltop_census.md; double-jump count CORRECTED: 13/74 real aerial jumps, up-B sets jumps_used=2), seven-flight comparison (docs/rl_geometry_scale_m7p_flight_comparison.md), scripted counterfactual probe = improved height but insufficient (docs/rl_geometry_scale_m7p_counterfactual.md). Jump-input audit: btt_s9_b8_v1 exposes C-up (8) and C-left (2), both native jump buttons with press-edge (no buffer) semantics; the stick path needs stick y>=53 within a 3-tick tap buffer; all 7 high flights used the stick path; the probe overlooked the C-button edit (described in the audit, not run). No new probes, no contract change, no training. Backup list (~140 MB, all Git-ignored) in the flight-comparison doc. Nothing pending; do NOT relaunch.

## Handoff status (2026-09-28, after the post-campaign audits)

- Selected configuration: original v3 observation (btt_policy_obs_v3_entities) + reward v2 remains selected; geo4 is not adopted.
- M7o (exploration credit) and M7p (geo4 geometry scale) retain their recorded failure_regression outcomes; nothing was re-decided.
- The geo4 seed-1 final checkpoint (runs/m7p/campaign/m7p_geo4_s1/final, model.zip f7d11d76...) retains its rare replay-verified tick-0 qualified crossing + target-6 break (episode ...44619208), plus the unqualified entry ...85c10043; the wall-top census found no other L0 landing in its 100 episodes.
- Corrected jump counts: only 13 of the 74 L1 flights had a genuine aerial double jump (native JumpAerialF/B); the earlier '73 of 74 double jump + up-B' and '24 skipped the double jump' were wrong because the up-B sets jumps_used = jumps_max (ftmain.c nFTMotionEventSetAirJumpMax). Production audit docs/rl_geometry_scale_m7p_jump_audit.md: no production code, observation feature (jumps_left = capacity), reward, curriculum, verifier or decision used that inference; NO production defect, no fix proposed.
- Stick-only counterfactual probe limitations: the 3-7 tick 'earlier double jump' is the lock length of the first-jump aerial move, not a movable input; only a one-tick shift was isolable (2 of 4 failures), giving +8.6 / +35.6 height (apex still < 3000) and a lost horizontal approach; the two 2394f859 variants produced no jump (3-tick stick tap buffer); a C-up / C-left press-edge edit was available in the contract and overlooked (described, not run). Conclusion: improved height but insufficient.
- Outstanding uncommitted work (untracked): docs/rl_action_hold_probe_*, docs/rl_learning_setup_review_2026-09-27.md, docs/rl_v3_saturation_investigation_2026-09-28.md, docs/rl_geometry_scale_* (diag, manifest, rule, results, handoff, crossing addendum + replays registry, wall-top census + registration, flight comparison, counterfactual + registration, jump audit), rl/configs/m7p/, rl/m7p_*.py, rl/tools/{action_hold_probe,m7p_crossing_addendum,m7p_walltop_census,m7p_flight_compare,m7p_counterfactual_probe}.py; modified: rl/experiment_config.py, rl/m7_evaluation.py, rl/m7_trainer.py, rl/m7g_k_tests.py, rl/m7n_obs.py. Not committed by instruction.
- Ignored evidence needing an independent backup (all under /runs/, .gitignore line 120, single copies, ~140 MB): runs/m7p/campaign/m7p_geo4_s1/final (1.2 MB) + run.json/experiment*.json/toml/training_summary.json/metrics (6.6 MB); runs/m7p/campaign/_eval/m7p_geo4_s1/final (76 MB); runs/m7p/campaign/_clears/m7p_geo4_s1 (44 KB); runs/m7p/campaign/_matrix + _control (13 MB); runs/m7p/addendum/crossings (0.5 MB); runs/m7p/addendum/walltop_census (40 MB); runs/m7p/addendum/counterfactual (2.5 MB). Nothing else in the runs tree is a backup of these.
- Nothing pending; no probe, training or campaign is authorised or proposed; do NOT relaunch.
