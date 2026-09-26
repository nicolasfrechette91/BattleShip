# RL M7l: three-seed target-2 reward experiment — results

Status (2026-09-25): **done at n = 3; decision recorded once: `not_learned` (gate 1).** Nothing is committed, pushed or
branched. No extension, no extra seed, no M7i work and no landing-reward change.

Machine-readable records:
- decision and per-seed evidence: [`rl_target2_m7l_analysis_n3.json`](rl_target2_m7l_analysis_n3.json) (byte-identical
  copy of `runs/m7l/campaign/_matrix/analysis_n3.json`, sha256 `83fb48ad…`);
- registration: [`rl_target2_m7l_manifest.json`](rl_target2_m7l_manifest.json) (sha256 `1beed7f7…`; the campaign's frozen
  copy `runs/m7l/campaign/_matrix/manifest.json` is byte-identical) and
  [`rl_target2_m7l_decision_rule.json`](rl_target2_m7l_decision_rule.json) (sha256 `01762dcb…`);
- control check: `runs/m7l/campaign/_control/control_check.json` (sha256 `4308c655…`).

## 1. Question and arms

Proposal: [`rl_target2_m7k.md`](rl_target2_m7k.md) section 10.

- **T:** `btt_reward_v3_t2` (v3 unchanged + a one-time credit `2.0·(3600 − n)/3600` on native target 2), fresh models,
  seeds 0–2, profiles `rl/configs/m7l/m7l_t2_s{0,1,2}.toml`.
- **C:** the historical Phase K v1 control `runs/m7g_k/m7g_s{0,1,2}_v1` (`btt_reward_v2`).
- **Fixed:** observation v1, `btt_s9_b8_v1`, Phase K PPO, N = 5 with standby, horizon 3,600, tick-0 starts, no curriculum,
  3,072,000 policy transitions, checkpoints every 102,400, the Phase K post-hoc evaluation.
- **The only experimental change:** the reward contract. The compatibility view differs from Phase K only in
  `contracts.reward_resolved` and the derived flag `SSB64_RL_TARGET_DIAG=1`, which is read-only.
- **Identity at registration:**

  | Item | Value |
  | --- | --- |
  | Parent HEAD | `14f5a63` (equal to `origin/main`) |
  | Submodules | `decomp 3c7fd5d0`, `libultraship 805f1950`, `torch 3aa9c97` |
  | Executable | `1e7c62a0…` |
  | Code fingerprint | `ea9691fe3d7b` (82 files; includes the uncommitted M7l files) |
  | Reward contracts | `btt_reward_v3_t2` canonical `fa74d7d7…`; v3 `d9447d47…` unchanged |

The TAS, the user crossing fixtures and the feasibility traces were never read.

## 2. Registration before any launch

- **Code:**
  - new: `rl/m7l_{matrix,analysis,campaign,route_rows,tests}.py`;
  - inherited, route-contract-only edits (see section 7);
  - the three profiles, the decision rule and the manifest.
- **Decision rule** (`m7l_decision_rule_v1`). All comparisons are inclusive, in exact integers or fractions, and seeds
  are paired by number.
  - **Denominator:** the 100 final stochastic episodes per seed and arm (300 pooled), whatever their end.
  - **Gate 1a:** `t2[T][s] − t2[C][s] ≥ 5` in at least 2 seeds.
  - **Gate 1b:** `Σ t2[T] ≥ 3·Σ t2[C]`.
  - **Gate 2:** `Σ static(T) ≥ Σ static(C) − 150`, where `static(e)` is every broken target except ID 2.
  - **Primary rule** = gates 1 and 2.
  - **Gate 3 (secondary):** R ≥ 1 in a seed, or pooled L ≥ 5. It is applied only after gates 1 and 2 hold. It only
    selects `learned_not_early` or `first_clear_relevant` and never changes the primary result.
  - **Recorded separately:** L, R, verified clears, left-side progress, falls and deterministic collapse.
- **Registered control values** (from the Phase K records):

  | Quantity | s0 | s1 | s2 |
  | --- | --- | --- | --- |
  | Target 2 broken | 1 | 0 | 2 |
  | Static targets (sum over 100 episodes) | 471 | 475 | 425 |
  | L | 0 | 0 | 1 |

  So gate 1b needs Σ t2[T] ≥ 9, and gate 2 needs Σ static(T) ≥ 1,221.
- **Tests before freezing:**
  - `rl/m7l_tests.py`: unit 5/5; game 2/2 (a route evaluation of the M7k s2 pilot checkpoint, and a 20,480-transition
    guarded v3_t2 run with the monitor validating route rows).
  - Inherited suites: m7d (8/8 of its unit cases; `unit_directory_guards` skipped because it hashes all of `runs/`),
    m7e 10/10, m7h 13/13, m7h_campaign 15/15, m7g_k 6/6, m7g_k_campaign 13/13, m7j 9/9, m7k 6/6, m7b_config 16/16,
    m7c 4/4, m7g_obs 8/8, m7_smoke 8/8.
  - m7g 8/9: the pre-existing `unit_training_isolation` failure on the same three M7h files; no M7l file is flagged.
  - Reward self-tests: v3 and v3_t2 pass.

## 3. Control check (historical control reused)

**Launch-gate refusals.** Two earlier attempts were refused by the registered launch gate: available physical memory was
3.77–3.94 GiB against the 4 GiB minimum. Nothing was recorded and no game was launched. The user then freed memory.

The check passed on the frozen code at 17:53Z (31.1 min):

| Check | Result |
| --- | --- |
| R1: reward v2, curriculum off, 102,400 transitions | s0 / s1 / s2 final digests equal the pinned Phase K = M7e `ckpt_000102400` (`5cec5fc4…`, `56241d22…`, `5177b527…`); every episode row equal (30 / 27 / 29, equal row hashes) |
| R2: re-evaluation of the three historical finals | 600 / 600 episodes equal (native action digest, targets, end, `btt_eval_metrics_v1`) |
| R3: decision inputs from R2 and from the historical files | equal to each other and to the registered values; deterministic facts equal |

**Preflight** (`train --dry-run`): 0 blocking problems. There was no drift, the control check was accepted, every profile
and fingerprint equalled the manifest, the directory plan was clean, and the gate passed at 7.79 GiB physical and
20.2 GiB commit.

## 4. Training (T arm)

All three runs were verified:
- completed and leak-free;
- a fresh untrained model equal to the control's `ckpt_000000000`;
- every row equal to its `btt_reward_v3_t2` closed form;
- the M7k control-equivalence checks V1–V5 pass: each T run is the control until the rollout containing its first
  credited target-2 break.

| Seed | Rows (falls) | Rows identical to C | First credit rollout / first divergence | Target-2 events in training (consumed tick @ transitions) | Credit paid | Wall, throughput |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 859 (17) | 120 | 414,720 / 414,720 | 2651 @ 0.42 M, 519 @ 0.58 M, 2323 @ 1.53 M, 3524 / 3565 / 3546 / 3525 @ 1.66–1.79 M | 3.08 | 38.2 min, 1,348 tr/s |
| 1 | 872 (31) | 7 | 20,480 / 30,720 | 3529 @ 0.02 M, 250 @ 2.62 M, 837 @ 2.73 M | 3.43 | 38.1 min, 1,350 tr/s |
| 2 | 876 (43) | 38 | 128,000 / 128,000 | 2055 @ 0.12 M, 843 @ 0.64 M, 541 @ 1.95 M, 512 @ 2.17 M | 5.80 | 38.1 min, 1,352 tr/s |

- **Training target-2 rate:** 14 events in 2,607 episodes (0.54 %), against M7k's estimate of 5–9 per run under the
  control.
- **Resources:**
  - minimum available commit 14.9–15.1 GiB; minimum available physical 6.6–7.2 GiB;
  - commit drawn 5.07–5.22 GiB;
  - at most 10 game processes;
  - no hard alert, cold fallback, startup failure or lifecycle failure;
  - no leftover process.
- **Training sweep.** One seven-right-target episode occurred in T s1 training
  (`episode_20260925T190612Z_49414363`, at 2.75 M transitions).
  - Target 2 broke on tick 837; the sweep completed on tick 1,030. That is the earliest policy sweep recorded (earlier
    sweeps: ticks 2,348, 3,237 and 3,570). The v3 sweep term 4.43 and the target-2 credit 1.53 were paid as registered.
  - The exact spatial replay (`runs/m7l/campaign/_replays/training_sweep_s1`) reproduces the digest and all break ticks.
    Target 2 broke by up-B (status 225) from (2245, 1403) at the platform's minimum.
  - Mario then stayed right of x −1,650 and survived to the horizon: no over-wall entry, no crossing.
  - It was a training episode, not an evaluation result.

## 5. Evaluation and decision

- **Census:** 2,955 / 2,955 T episodes (3 × 985), in 33 labels. Every label verified:
  - tick-0 starts;
  - clean metrics;
  - frozen statistics;
  - each route row equal to its closed form, with its credit tick equal to `btt_eval_metrics_v1`;
  - leak-free.
- **Initial checkpoint:** T s0's initial evaluation equals the control's initial evaluation in all 200 episodes.
- **Clears:** no native clear candidate in any T label or in T training. The control's registered labels also have
  none.

**Final stochastic, 100 episodes per seed:**

| Seed / arm | Target 2 (break ticks) | Gain | Static targets / ep | T_incomplete | Falls | L | R | Left entries / left-target breaks | Clears |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s0 C | 1 (2907; fell) | | 4.71 | 4.72 | 1 | 0 | 0 | 0 / 0 | 0 |
| s0 T | 0 | −1 | 4.89 | 4.89 | 0 | 0 | 0 | 0 / 0 | 0 |
| s1 C | 0 | | 4.75 | 4.75 | 1 | 0 | 0 | 0 / 0 | 0 |
| s1 T | 2 (549, 803) | +2 | 3.96 | 3.98 | **24** | 1 | 0 | 0 / 0 | 0 |
| s2 C | 2 (1134, 2033) | | 4.25 | 4.27 | 0 | 1 | 0 | 0 / 0 | 0 |
| s2 T | 1 (1454) | −1 | 3.53 | 3.54 | 1 | 0 | 0 | 0 / 0 | 0 |
| **pooled C** | **3 / 300** | | **4.570** | | 2 | 1 | 0 | 0 | 0 |
| **pooled T** | **3 / 300** | | **4.127** | | 25 | 1 | 0 | 0 | 0 |

| Gate | Condition | Observed | Result |
| --- | --- | --- | --- |
| 1a | gain ≥ +5 in ≥ 2 seeds | gains −1 / +2 / −1; 0 seeds | **fail** |
| 1b | Σ t2[T] ≥ 3·Σ t2[C] = 9 | 3 | **fail** |
| 2 | Σ static(T) ≥ 1,371 − 150 = 1,221 | 1,238 (−133/300 ≈ −0.44 per episode) | pass |
| primary (1 and 2) | | | **false** |
| 3 (secondary) | R ≥ 1 in a seed, or pooled L ≥ 5 | R 0 / 0 / 0; pooled L 1 | fail (reported only) |

**Decision (recorded 22:22Z, never re-decided): `not_learned`.** "Gate 1 failed: within this budget the credit did not
overcome the exploration gap. Next is an exploration mechanism: a user decision."

**Target-2 break timing.**
- T's three final breaks were all early: ticks 549, 803 and 1454, none followed by a fall.
- C's three breaks were at ticks 2907 (followed by a fall), 1134 and 2033.
- Neither arm has an R episode or a seven-right-target evaluation episode.

**Learning curve.** Target-2 count per evaluated checkpoint: 100 stochastic episodes at initial and final, 60 in between.

| Seed | C | T |
| --- | --- | --- |
| 0 | 3, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1 | 3, 0, 0, 1, 1, **4**, 1, 0, 0, 0, 0 |
| 1 | 4, 0, 0, 0, 0, 1, 2, 0, 1, 0, 0 | 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2 |
| 2 | 0, 1, 0, 1, 4, 1, 0, 0, 1, 0, 2 | 0, 1, 0, 0, 0, 1, 0, 1, 0, 0, 1 |

- T s0 shows a transient rise at 1.54 M (4 of 60) that did not persist.
- Mean targets at final: T s0 4.89 against C s0 4.72; T s1 3.98 against 4.75; T s2 3.54 against 4.27.
- T s1's final falls (24) appear only at the last checkpoint: 3 at 2.76 M, then 24.

**Deterministic plays** (100 identical episodes each):
- C: 2 / 2 / 3 targets; collapse 0.507 (collapsed) / 0.25 / 0.34.
- T: 2 / 3 / 2 targets; collapse 0.542 (collapsed) / 0.711 (collapsed) / 0.411.
- No deterministic play broke target 2.

**Approach zone** (secondary, descriptive). These come from exact spatial replays of all 600 final stochastic episodes:
600 / 600 exact, maximum file lock 0.013 s on the idle machine. The zone is x 2,100–3,300, y ≥ 1,350.

| | s0 C / T | s1 C / T | s2 C / T | Pooled C / T |
| --- | --- | --- | --- | --- |
| Episodes visiting the zone | 5 / 7 | 4 / 15 | 5 / 2 | 14 / 24 |
| Zone ticks | 81 / 106 | 15 / 664 | 99 / 104 | 195 / 874 |
| Platform contact (episodes) | 0 / 0 | 0 / 3 | 0 / 1 | 0 / 4 |
| Within 600 units of target 2 | 0 / 0 | 0 / 1 | 1 / 1 | 1 / 2 |
| Median closest approach | 2,233 / 2,091 | 1,864 / 2,313 | 2,275 / 3,304 | |

**Costs:**

| Phase | Wall time |
| --- | --- |
| Control check | 31 min |
| Training | 3 × 38 min |
| Evaluation | 46 / 46 / 46 min |
| Replays | 14 min |

Total from the control check to the decision: about 5 h.

## 6. Interpretation against the M7k prediction

- **Observed:**
  - At 3,072,000 transitions the target-2 break rate did not rise: pooled 3 / 300 in both arms, and no seed gained
    ≥ 5 points.
  - T's breaks came earlier than C's, but that rests on 3 episodes per arm.
  - Target-2 encounters stayed rare in training (0.54 % of episodes).
  - Visits to the approach zone rose modestly in pooled count (24 against 14 of 300), mostly in seed 1, without more
    breaks.
  - Two T seeds finished with fewer static targets (3.96 and 3.53 against 4.75 and 4.25). The pooled loss of 0.44 per
    episode stays inside the registered 0.5, and seed 0 gained static targets.
  - No clear, crossing, left entry or left-target break occurred in any evaluation of either arm.
- **Prediction (M7k section 10):** "uncertain … the credit changes the sign of the learning signal, but it cannot create
  visits to a region the policy does not reach."
- **Consistent, not proven:** the result fits that prediction, but it is not proof of the mechanism.
  - With 0–2 breaks per 100 episodes, the experiment could detect only large effects, which is what the registered
    ≥ 5-point rule asks for.
  - The zone-visit difference is descriptive, from one run per seed, and dominated by seed 1.
- **No target-2 gain to describe:** the primary rule failed, so no target-2 gain is claimed. L and R are secondary
  (pooled L 1 in each arm, R 0 in both). Nothing here is a crossing, a sweep in time in evaluation, or a clear.

## 7. Implementation notes

- **Why the validators were changed.** Before M7l, route contracts could not pass through the shared validators:
  `btt_rewards.expected_return` raises for them. The training monitor would therefore have failed at the end of a v3_t2
  run, and training and evaluation verification would have raised.
- **Additive, route-contract-only edits:**
  - `rl/m7d_run.py`: `validate_episode_row` computes the route closed form from the row's own `reward_v3` record
    (`rl/m7l_route_rows.py`); `eval_row_as_summary` passes that record through.
  - `rl/m7_evaluation.py`: `_row` includes `reward_v3` when present.
  - `rl/m7g_k_tests.py`: `configs/m7l` added to its later-milestone profile exclusion.
- **v1 / v2 unchanged:** those paths are unchanged; all 862 Phase K v2 rows still validate, and R1 / R2 reproduced
  exactly on this code.
- **Driver:** `rl/m7l_campaign.py`. Commands: `manifest`, `control-check`, `train`, `evaluate`, `verify-clears`,
  `replay`, `census`, `analyze`, `status`, `all`.
- **Orchestration:** the campaign was launched by a watcher script outside the repository. It measured the launch gate
  once a minute, required 3 consecutive passes, then ran control-check → preflight → `all`, each only after the previous
  one exited 0. Logs: `runs/m7l/campaign_logs/`.

## 8. Limitations

- **Statistical power.** 100 stochastic episodes per seed and target-2 counts of 0–2 give no power for small effects.
  The rule tested only for a large effect, and none was found.
- **Historical control.** The control is reused from Phase K. It was valid for this code (R1–R3), and each T run equals
  its control until its first credited rollout (V1–V5), so arm differences arise only after that point.
- **One budget.** 3,072,000 transitions, with no extension per instruction. A later effect is not excluded.
- **Unexplained end states.** T s1's final 24 falls, and the lower static-target counts of T s1 and T s2, are
  post-divergence outcomes of single runs. They are not explained here and not registered claims.
- **Uncommitted code.** The manifest pins HEAD `14f5a63` plus code fingerprint `ea9691fe`. Committing changes HEAD, so
  any M7l command would then report drift. The recorded decision is unaffected.
- **Skipped test case.** `m7d_tests unit_directory_guards` was not run: it hashes every file under `runs/`.

## 9. Paths

| Item | Path |
| --- | --- |
| Manifest (frozen) | `docs/rl_target2_m7l_manifest.json` = `runs/m7l/campaign/_matrix/manifest.json` |
| Decision rule | `docs/rl_target2_m7l_decision_rule.json` |
| Decision record | `runs/m7l/campaign/_matrix/analysis_n3.json` (+ `state.json`), copy in `docs/rl_target2_m7l_analysis_n3.json` |
| Control check | `runs/m7l/campaign/_control/control_check.json`, raw `runs/m7l/campaign/_control/code_ea9691fe3d7b__20260925T172236Z/` |
| Training runs | `runs/m7l/campaign/m7l_t2_s{0,1,2}` (verification `runs/m7l/campaign/_matrix/verify/`) |
| Evaluations | `runs/m7l/campaign/_eval/m7l_t2_s{0,1,2}/{initial,curve_t*,final}` |
| Clear verification | `runs/m7l/campaign/_clears/` (no candidates) |
| Spatial replays | `runs/m7l/campaign/_replays/{m7l_t2_s*,m7g_s*_v1,training_sweep_s1}` |
| Guard logs / monitor / probe | `runs/m7l/campaign/_guard/` |
| Campaign logs | `runs/m7l/campaign_logs/` |
| Historical control (read only) | `runs/m7g_k/m7g_s{0,1,2}_v1`, `runs/m7g_k/_eval/m7g_s{0,1,2}_v1` |
