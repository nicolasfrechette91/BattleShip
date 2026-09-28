# RL handoff, 2026-09-28 (end of the M7p line of work)

One page for whoever picks this up. Everything below is recorded in the linked documents; nothing here is new evidence.

## Selected baseline

- **Observation `btt_policy_obs_v3_entities` (M7n) + reward `btt_reward_v2` + action `btt_s9_b8_v1` (Track 1) + PPO as in
  `rl/configs/m7n/m7n_s{0,1,2}_v3.toml`** is the selected training configuration (M7n gate 3 `better_targets`,
  `docs/rl_observation_v3_proposal_m7n.md`, decision record in `runs/m7n`).
- The config schema defaults in `rl/experiment_config.py` are unchanged (observation v1, reward v1 ids); every later
  contract is chosen per profile. Opt-in only, never default: `btt_policy_obs_v3_geo4` (`rl/m7p_obs_geo4.py`, selected
  solely by `contracts.observation` in `rl/configs/m7p/*.toml`), `btt_reward_v3`, `btt_reward_v3_t2`,
  `btt_explore_cells_v1`, the M7h / M7m curricula.
- Best final tick-0 stochastic result on record: v3 finals at 5.52 / 5.53 / 5.59 targets per episode (seeds 0-2), no
  clear anywhere in the project.

## Rejected experiments (decisions stand, do not relaunch)

| experiment | decision | record |
| --- | --- | --- |
| M7o exploration credit `btt_explore_cells_v1` vs v3 | `failure_regression` | `docs/rl_exploration_credit_m7o_*.md`, `runs/m7o` |
| M7p geometry scale geo4 vs v3, 3 seeds x 3,072,000 | `failure_regression` (D -0.61 / -0.60 / -0.61 targets), saturation reduction persisted but did not help | `docs/rl_geometry_scale_m7p_results.md`, `runs/m7p/campaign/_matrix/analysis_n3.json` |
| M7p geo4 short diagnostic (seed 0, 307,200) | `diagnostic_pass` (eligibility only; superseded by the campaign) | `docs/rl_geometry_scale_diag_2026-09-28.md`, `runs/m7p/diag` |
| action-hold reachability probe (no training, k 1/4/8/16) | `NO FOOTHOLD`; no hold-k campaign | `docs/rl_action_hold_probe_2026-09-27.md` |
| v3 first-layer saturation | real, cause = geometry-block scale; not shown to limit gameplay; no change | `docs/rl_v3_saturation_investigation_2026-09-28.md` |
| earlier M7j / M7k / M7l / M7m / M7h lines | recorded in their own docs; not reopened | `docs/rl_*_m7[h-m]*.md` |

## Verified crossing checkpoint (rare, one seed, not deciding)

`runs/m7p/campaign/m7p_geo4_s1/final` (`model.zip` sha256 `f7d11d76…`, contract geo4 `2b984528…`, executable `748dbad9…`):
in its 100-episode final stochastic tick-0 evaluation, episode `episode_20260928T072129Z_44619208` is the project's
first replay-verified **qualified crossing** (L1 takeoff 2318, landed on the wall top L0 at 2434, left entry 3001,
target 6 at 3008, landing L3 at 3141, fell at 3444) and `…85c10043` an unqualified left entry. The wall-top census of
all 100 episodes found no other L0 landing (2 / 100). Records: `docs/rl_geometry_scale_m7p_crossing_addendum.md`,
`docs/rl_geometry_scale_m7p_walltop_census.md`, artifacts under `runs/m7p/campaign/_eval/m7p_geo4_s1/final/stochastic`,
verification under `runs/m7p/campaign/_clears/m7p_geo4_s1/final`, raw-reply traces under `runs/m7p/addendum/`.

## Corrected analysis claims (all prose / analysis tools; no production defect)

1. "73 of 74 L1 flights used double jump + up-B" and "24 skipped the double jump" were wrong: `jumps_used` is a
   capacity counter that Mario's up-B sets to 2 (`ftmain.c` `nFTMotionEventSetAirJumpMax`). Native status counts: 13
   genuine aerial double jumps, 41 airborne up-Bs straight from the first jump, 19 grounded up-Bs.
2. The "-0.5" at the up-B press is the startup's imposed velocity, not a jump apex.
3. The 3-7 tick "earlier double jump" of the two landings is the lock length of the first-jump aerial move (early
   aerial attack vs aerial fireball / late attack), not a free timing.
4. The counterfactual registration described Kirby's held-stick rule; Mario's jump needs a stick tap within a 3-tick
   buffer or a fresh C-button press. The probe overlooked the C-button edit the contract already exposes.
5. The learning-setup review row "used the double jump 81 % / 69 %" reads "double jump or up-B".
   Production audit with the full table: `docs/rl_geometry_scale_m7p_jump_audit.md` (no fix needed).

## Unresolved learning questions (recorded, not being pursued in this session)

- Why the first left-side events stay at a zero rate under per-tick sampling (credit assignment over ~100-tick
  manoeuvres; `docs/rl_learning_setup_review_2026-09-27.md`), and whether any authorised lever changes it: every
  shaping / curriculum / representation attempt so far (M7h, M7j-M7o, M7p) did not.
- Whether the seed-1 geo4 ledge-standing route is learnable more often than 2 / 100: nothing shows it is.
- Whether v3 saturation matters for gameplay (not established either way).
- The scripted counterfactual probe (`docs/rl_geometry_scale_m7p_counterfactual.md`) answered only "improved height but
  insufficient" for a one-tick shift; it says nothing about learnability.

## Artifact paths

- Documents (untracked, to commit): `docs/rl_learning_setup_review_2026-09-27.md`, `docs/rl_action_hold_probe_*`,
  `docs/rl_v3_saturation_investigation_2026-09-28.md`, `docs/rl_geometry_scale_diag_*`, `docs/rl_geometry_scale_m7p_*`
  (manifest, decision rule, results, handoff log, crossing addendum + replay registry, wall-top census + registration,
  flight comparison, counterfactual + registration, jump audit), this file.
- Code (untracked, to commit): `rl/m7p_obs_geo4.py`, `rl/m7p_{geo4_diag,matrix,campaign,control_check,control_verify,
  measure,analysis}.py`, `rl/configs/m7p/m7p_geo4_s{0,1,2}.toml`, `rl/tools/{action_hold_probe,m7p_crossing_addendum,
  m7p_walltop_census,m7p_flight_compare,m7p_counterfactual_probe}.py`; modified: `rl/experiment_config.py`,
  `rl/m7_trainer.py`, `rl/m7_evaluation.py`, `rl/m7n_obs.py` (default-preserving geo4 hooks), `rl/m7g_k_tests.py`
  (m7p profiles excluded from the Phase K profile scan).
- Evidence (Git-ignored, single copy, needs an independent backup; checksum manifest
  `runs/m7p/backup_manifest_2026-09-28.sha256`, 3,233 files, 176.0 MB, runtime junctions to `build-us/Release/.tcc`
  excluded): `runs/m7p/campaign/m7p_geo4_s1/{final,metrics,run.json,experiment.toml,experiment_resolved.json,
  training_summary.json}`, `runs/m7p/campaign/_eval/m7p_geo4_s1/final`, `runs/m7p/campaign/_clears/m7p_geo4_s1`,
  `runs/m7p/campaign/_matrix`, `runs/m7p/campaign/_control`, `runs/m7p/addendum/{crossings,walltop_census,counterfactual}`,
  `runs/m7p/diag`. The diagnostic's 307,200-transition seed-0 profile survives only as
  `runs/m7p/diag/m7p_geo4_s0/experiment.toml` (sha256 `4459aa0c…`); the tracked `rl/configs/m7p/m7p_geo4_s0.toml` is the
  campaign version (3,072,000; `e0bcb21f…`).
- Earlier milestones' evidence under `runs/m7n`, `runs/m7o`, `runs/m7h`… is likewise ignored and unbacked; it is not
  listed here because this handoff covers the M7p line only.

Nothing is pending. No probe, training or campaign is authorised or proposed.
