# M7s stage 1 (learned return, GCSL): implementation record (2026-09-28, revision 5)

Design: `docs/rl_goal_exploration_design_2026-09-28.md` revision 5. **Opt-in Python only. No inherited file was
changed; nothing committed.** Sections 1–8 describe the code as it was pinned for approval. That code is unchanged
since, and the implementation claims below were written before the run.

**Update 2026-09-29: the gate was approved by the user (`docs/rl_gcsl_return_m7s_gate_approval.json`, identity
unchanged) and run once.** P1 passed (29,069 ticks). The registered outcome is **3, inconclusive**: the learner was not
functional in all three seeds, and all three R are goal-blind. 2,922,820 native ticks were used of the 3,108,269 cap.
There were no clears, and 6 of 6 exact return replays matched. Full report: `docs/rl_gcsl_return_m7s_results.md`.
Evidence is in `runs/m7s/` and D: increment `2026-09-29_incr_m7s` (PASS).

**Revision 5 (pre-gate corrections, design section 13)** adds, before any approval:

- the user's four confirmed contract choices, now explicit in the goal contract (first reach needs no survival period;
  `goal_reached` over `max_episode_steps` on the horizon tick; a clear on the reach tick is a clear, claimed only after
  an exact native replay; the next collection goal applies to the next action tick, nothing inserted);
- the **goal-blind safeguard**: rule `m7s1_return_rule_v2` refuses a pass for a trained R with `goal_blind_flag = true`
  (the existing, fixed 0.01 goal-swap TV threshold); such a seed is inconclusive and its success counts are reported;
- the **P1 goal-on identity check**, implemented and tested offline, not executed;
- bounded exact native replay of claimed clears, with a clear-fact consistency check in the evaluation analysis.

**Contract correction of revision 4 (retained).** The decisive success is the **first valid reach**, and an
evaluation episode ends on that tick with `truncation_reason = goal_reached`.

- **Valid tick** (one definition for success, the goal archive and the supervised labels): `btt_active` 1,
  `fighter_valid` 1, inside the box, and not the tick on which a native-failure (fatal) fall ends the episode.
- The 120-tick behaviour is gone from every decisive path; only the non-decisive collection diagnostic
  `survival_120` remains.

## 1. Files (all new and untracked, under `rl/`)

| file | role | revision 5 change |
| --- | --- | --- |
| `m7s_goal.py` | Pure contract module:<br>• `btt_goal_cell_v1`: box, bins, contact, `valid_cells` (only the fatal-fall tick is invalid);<br>• end reasons `goal_reached` / `tick_quota` / `max_episode_steps`;<br>• `btt_goal_obs_v3_v1`: 14-value goal vector;<br>• frozen E + archive A with witnesses and a provenance check;<br>• the matched schedule and the evaluation plan;<br>• `btt_gcsl_return_v1` relabelling: examples inside the recorded prefix only, asserted | the contract description states the four confirmed choices (`no_survival_requirement`, `horizon_precedence`, `clear`, `next_goal`); behaviour unchanged |
| `m7s_policy.py` | `btt_gcsl_policy_v1`: v3 trunk 606 → 64, bounded goal branch 14 → 32 (tanh, gain √2 · κ, **κ fixed at 1.0**), joint 96 → 64, heads 9 / 8; seeded matched initialisation; digest, save / load; common-random-number sampling; `GCSLTrainer`; `goal_sensitivity`; `GOAL_BLIND_TV = 0.01` | comment only (the flag is now decisive for a pass); contract digest unchanged |
| `m7s_worker.py` | The goal worker stack: `GoalProbeWrapper`, `GoalObsWrapper`, `M7sWorkerWrapper`, factory | unchanged |
| `m7s_collect.py` | The M7n v3 environment settings; worker preparation; `run_phase` | episode rows also carry `termination_reason`, `cleared` and both completion clocks |
| `m7s_analysis.py` | Rule (goal-level paired sign-flip); self-test | **rule v2**: goal-blind safeguard, `rule_description` / `rule_digest`, required goal-sensitivity input, self-test cases |
| `m7s_gate.py` | Driver | **P1** = null-goal identity + goal-on identity (`GOAL_ON`, `recorded_v3`, `goal_on_expected`, `goal_on_check`, `_close_and_check`, `p1_identity`); `clear_fact_problems`, `clear_candidates`, `verify_clears`; `rule_goal_sensitivity`; revised `TICK_BUDGET`; identity / approval pin the rule digest, P1 registration, clear cap and tick caps; preflight recomputes the P1 expectations; `cmd_run` stops before training on any P1 failure |
| `m7s_tests.py` | Offline cases (section 5) | 6 new cases, 2 updated; fakes for the goal-on worker |

Worker stack (M7n v3 stack plus two layers; every other layer, argument and order unchanged):

    M7BattleShipBTTEnv -> GoalProbeWrapper -> M7RewardWrapper (v2) -> EpisodeRecordingWrapper -> Track1PolicyWrapper
    -> EntityObsV3Wrapper -> GoalObsWrapper -> EpisodeStatsWrapper -> M7sWorkerWrapper

- The probe sits below the reward wrapper and the recorder, so `goal_reached` and `tick_quota` are ordinary
  truncations: native words recorded and preserved; `truncation_reason` stored in the tracker labels and summary; the
  tracker's `end_reason` reads `horizon` for every truncation.
- **Every consumer decides by `truncation_reason`**: the evaluation rows, the replay precondition, the reported
  collection statistics and the rule inputs.

## 2. Contracts and identities

| contract | digest (sha256, first 16) | change |
| --- | --- | --- |
| goal cell + goal observation + GCSL relabelling (`m7s_goal.contract_description`) | `22b0919eea3ab5e0` | was `12a71b1a43cdbf2a`; description only (the four confirmed choices) |
| `btt_gcsl_policy_v1` (`m7s_policy.contract_description`) | `2b2c5c36aaf6dc79` | unchanged (already pinned `goal_blind_tv` 0.01) |
| rule `m7s1_return_rule_v2` (`m7s_analysis.rule_description`) | `bea670ce1e9105c3` | new (v1 had no digest and was never applied) |
| P1 goal-on registration (`m7s_gate.GOAL_ON`) | trace `856c0e8d…`, word prefix `8821b2ad…`, v3 block `c9000896…` | new |
| executable | `30a3913b…` | unchanged |

`python rl/m7s_gate.py approval-template` prints (never writes) the record to review. It pins:

- the rule id and digest and `goal_blind_tv` 0.01;
- the goal and policy contract digests and the executable;
- `p1` (the P1 caps and the full `GOAL_ON` registration), `clear_replays_per_seed` 2 and the whole tick budget;
- the sha256 of the seven m7s files (`m7s_goal` `5fcd33f9…`, `m7s_policy` `337e5c82…`, `m7s_worker` `2132b133…`,
  `m7s_collect` `06cfd0df…`, `m7s_analysis` `fbcc402d…`, `m7s_gate` `4bff49b4…`, `m7s_tests` `f00ab169…`), the
  unchanged inherited modules the stage depends on, and the M7n environment profile.

`approval_status` refuses a record that differs in any of these.

## 3. Budget arithmetic (upper bounds; enforced per phase)

| item | computation | native ticks |
| --- | --- | ---: |
| P1 (a) null-goal identity | 3,361 + 2,560 + 6 × 3,600 | 27,521 |
| P1 (b) goal-on identity | 2 × 774 updates (native `consumed_tick` 0–773 each; no word after the reach update) | 1,548 |
| **P1 cap** (`p1_identity`) | | **29,069** |
| phase A | 3 × 20 × 3,600 | 216,000 |
| phase B | 3 seeds × 2 arms × 5 workers × 71,680 | 2,150,400 |
| evaluation | 3 × 2 × 30 × 3,600 (episodes end at the first valid reach, so fewer in practice) | 648,000 |
| exact return replays | 3 × 2 × 2 × 3,600 | 43,200 |
| exact clear replays | 3 × 2 × 3,600 (none expected: no clear anywhere in the project) | 21,600 |
| **total** | | **3,108,269** (revision 4: 3,085,121; M7r: 3,139,200) |

`p1_identity` refuses a sub-check whose ticks exceed its cap and requires P1 to total exactly 29,069; the goal-on check
cannot exceed 1,548 by construction; the ledger has one key per row and `analyse` treats any row over its cap as an
integrity failure.

### 3.1 Tick convention and the P1 goal-on accounting (reconciled 2026-09-28, read-only, no code change)

**Convention** (design section 3): an M7s tick k is the ordinal of a native update. After update k the native
`step_count` is k and the returned `input_tick` is k; that update's native `consumed_tick` is k − 1; the reset
observation is tick 0 and consumes nothing. Every "tick" and "native ticks" figure in this record, the probe's
`reach_tick`, the sidecar's `set_tick` / `reach_tick` / `ticks` and the tracker's `steps` use k. Artifact action rows and
the tracker's `native_action_digest` carry the 0-based native `consumed_tick`.

**"Reach tick 774" is the returned `input_tick` (= `step_count`), not the native `consumed_tick` (773).** Verified on
the pinned trace's recorded replies: the reset `observe` reply has `step_count` 0, `input_tick` 0; `steps[0]` has
`consumed_tick` 0, `input_tick` 1, `step_count` 1; `steps[770]` (tick 771, `consumed_tick` 770) is the first reply in
the bin `17,8` (in the air, cell `17,8,-1`); `steps[773]` (tick 774) has `consumed_tick` 773, `input_tick` 774,
`step_count` 774 and is the first reply in `17,8,2`; the 774 artifact rows used carry `consumed_tick` 0–773 (the first
unsent row is 774).

Per repetition (identical for both; each starts from a fresh process frozen at tick 0):

| quantity | value |
| --- | --- |
| reset (cold launch or standby promotion, plus the v3 wrapper's non-consuming `observe`) | `input_tick` 0, `step_count` 0, **no update** |
| first submitted word: at `input_tick` / native `consumed_tick` | 0 / 0 |
| last submitted word: at `input_tick` / native `consumed_tick` | 773 / 773 |
| final native `consumed_tick` | 773 |
| returned next `input_tick` (= `step_count` = `reach_tick`) | 774 |
| native updates | **774** |

Two repetitions: **1,548** updates = the P1 (b) cap; **no off-by-one**. The null-goal part counts the same way (3,361 +
2,560 + 6 × 3,600 recorded words = updates).

What P1 (b) asserts about ticks: exactly 774 `env.step` calls per repetition (the loop sends no word after the 774th);
the probe's first `reached` event and the end at step 774; tracker `steps` 774 and sidecar `ticks` / `reach_tick` 774;
artifact rows equal to the pinned words, including their native `consumed_tick` 0–773, and the tracker digest (which
hashes `consumed_tick`) equal to `8821b2ad…`. The native `input_tick` of the last reply is not compared as a separate
field.

Two pinned code strings use the ordinal wording and were left unchanged so no approval identity moves: the `GOAL_ON`
comment in `rl/m7s_gate.py` ("consumed tick 774") and the goal contract's `next_goal` text ("action a_k (consumed tick
k + 1)"). Both read correctly under the convention; aligning them to native field names would change the
`m7s_gate.py` hash and the goal contract digest.

## 4. Corrections as implemented

1. **Supervised examples** are (o_t, a_t, g = c_{t+h}, h) over valid cells, with b ∈ [h, H − t] (b = h with
   probability ½). Collection and evaluation use b = H − t. `sample_examples` asserts 0 ≤ t < t + h ≤ T, so a phase-B
   episode cut by the tick quota supplies only pairs inside its recorded prefix.
2. **Comparison.** The goal-level paired sign-flip comparison of R with U on the same goals; r_g and u_g count
   `goal_reached` evaluation episodes only.
3. **Matched arms.** One `init.pt`, one schedule, identical sampling seeds; U's digest is re-checked. Exact replay is
   a tested property, re-tested for each claimed return.
4. **Scope of a pass:** design section 9.
5. **First valid reach (revision 4).** Probe, collection, archive, labels, `survival_120` (reported only), evaluation
   rows and return replays as recorded in revision 4; unchanged.
6. **Post-training goal sensitivity.** `post_training_sensitivity` measures R_final and U on the same 4,000 states
   from R's own episodes and the same goal pairs from the frozen E cells; `rule_goal_sensitivity` hands R's and U's
   goal-swap TVs and `goal_blind_flag` to the rule.
7. **Goal-blind safeguard (revision 5).** `seed_comparison` computes `goal_blind = R_goal_swap_tv < 0.01` (strict),
   requires the reported flag to agree, and sets `rare_pass = rare criteria met and not goal_blind`. A would-pass
   goal-blind seed gets the blocking reason "goal-blind R (post-training goal-swap action TV x < 0.01): not credited
   as learned return (R a vs U b rare returns on n distinct goals, T, p; mid R / U)" and the per-seed record keeps
   every count, both TVs and `rare_criteria_met`. `decide` needs two goal-sighted rare passes for outcome 1; a
   missing, non-finite or inconsistent sensitivity record is `invalid`. The fail path (outcome 2) is unchanged.
8. **Clears (revision 5).** A clear ends `terminated` with `native_clear` and no truncation (`battleship_env`: a native
   end is never also a horizon truncation), records no reach and commands no next goal (the probe excludes the clear
   tick). `_eval_rows` accepts `end_class = clear` (never a success) only when the four facts agree
   (`clear_fact_problems`); a cleared flag on any other end is flagged. `clear_candidates` collects clears from
   evaluation R, evaluation U, phase B R, phase B U and phase A (dedup by digest); `verify_clears` replays the first two
   per seed with `m7d_run.replay_one` (verified = all checks, native clear, both clocks equal to the recorded pair);
   verified clears are the only ones claimed; the rest are reported `unverified_not_claimed`; a replay that does not
   verify is an integrity problem. `analyse` reports clears; they never decide m7s1.
9. **Next goal timing (confirmed).** After the update of reach tick k the goal wrapper commands the next goal; the
   observation of tick k (`input_tick` k) already carries it, so it first governs a_k, which is native `consumed_tick` k
   and produces tick k + 1. No request is sent on the reach tick beyond the policy's own action, and the probe
   evaluates the new goal only from tick k + 1.
10. **P1 goal-on identity (revision 5, design section 5.1).**
    - `goal_on_expected` (no game) checks the trace sha256, rebuilds the 774-word prefix (native `consumed_tick`
      0–773) from the trace's artifact and its tracker digest, the first valid reach at tick 774 (native
      `consumed_tick` 773) and the same-bin air occupation from tick 771, and the 775 × 606 v3 block (ticks 0–774)
      built by the unchanged `EntityObsV3Wrapper` over the recorded replies (`recorded_v3`), each against `GOAL_ON`.
      Preflight runs it.
    - `goal_on_check` builds one real goal worker (`_goal_on_env`: rank 0, M7n settings, standby) in plan mode with
      `end_on_success`, two plan entries with the registered goal, and feeds the recorded Track 1 words, never past the
      774th (native `consumed_tick` 773). Per repetition it compares the v3 block (bytes) and the goal vector at every
      tick 0–774, records the first `reached` event and the end, reads the artifact's words and the sidecar, and applies
      `_repetition_problems`.
    - Clean termination: the parked process must be alive after the truncation; when the next reset retires it and
      at close, its `cleanup_action` must be `terminated` and the process gone; `_close_and_check` then requires 0
      worker processes, a joined standby thread in state `no_standby` without cleanup failures, and no BattleShip
      process on the machine.
    - The first failing repetition (or a failed retire, or an exception) stops the check. `p1_identity` runs the
      null-goal part first and skips the goal-on part if it fails. `cmd_run` records `stopped_at` and returns 3
      before the first seed.

## 5. Offline tests: `python rl/m7s_tests.py unit` → **24 / 24 PASS**

Revision-4 cases, all still passing: `unit_cell_contract`, `unit_goal_features`, `unit_reply_cells` (27,521 replies),
`unit_relabel`, `unit_goal_set_provenance`, `unit_schedule_plan`, `unit_probe`, `unit_real_stack` (13,121 ticks),
`unit_collector`, `unit_gcsl_synthetic`, `unit_policy_matched`, `unit_init_scaling`, `unit_coverage_logic`,
`unit_no_forbidden_sources`, `unit_analysis`, `unit_survival_diagnostic`.

Updated:

| case | change |
| --- | --- |
| `unit_contract_and_budget` | total 3,108,269 < 3,139,200; P1 caps 27,521 + 1,548 = 29,069; clear replays 21,600; the other phase caps unchanged; the rule digest reported |
| `unit_end_reason_interpretation` | the clear row carries its four facts and is accepted; four inconsistent clear records (no facts, 9 targets, a missing clock, a cleared flag on a horizon end) are each flagged |

New:

| case | result |
| --- | --- |
| `unit_goal_blind_rule` | one threshold (rule = policy contract = 0.01) pinned by the approval identity; the rule self-test (a goal-blind would-pass seed: `rare_criteria_met`, no pass, counts "R 7 vs U 0" reported; TV exactly 0.01 is not blind; missing or inconsistent sensitivity → invalid); through `gate.analyse`: three goal-blind would-pass seeds → **inconclusive**; one sighted + two blind → **inconclusive**; two sighted + one blind → pass |
| `unit_clear_precedence` | real probe + goal wrapper: a clear on the reach tick (and on the reach + horizon tick) ends terminated at tick 12 with no truncation reason, no reach, sidecar `native_clear`; `_eval_rows` accepts it (`end_class` clear, not a success, no problem); the rule counts 0; the return replay refuses it; it is one clear candidate; a verified replay claims it, cap 0 leaves it unclaimed; in collection it records no reach and no next goal; without a clear a reach on the horizon tick is `goal_reached` through the full stack and a success row |
| `unit_next_goal_timing` | reaches at ticks 5 and 6 for a next cell and for a repeated cell (never 5 and 5); 20 native actions for 20 steps; the reach step's observation carries the next goal; sidecar (set, reach) = (0, 5), (5, 6) |
| `unit_p1_goal_on_expected` | no problem; 774 words, goal `17,8,2`, 775 × 606 v3 block equal to the direct builder path; air in the same bin from 771; a tampered trace, reach tick 775, contact `-1` (first reach 771) and a wrong v3 digest are each refused |
| `unit_p1_goal_on_check` | real goal / probe / v3 wrappers on the pinned replies with fake processes: **pass** with 1,548 ticks, first process retired `terminated`, clean close. Each fault fails it and stops after the failing repetition, never above the cap: a corrupted recorded word (first difference at word 100); `position_x` + 1 at tick 300 (v3 differs at 300, 301; goal vector at 300); airborne on tick 774 (no reach, no end); the goal state on tick 500 (first reach 500, 500 ticks sent); a tracker `max_episode_steps` label; a parked process that died; a killed process; a leftover BattleShip process; a standby cleanup failure. A refused expectation launches nothing |
| `unit_p1_stops_gate` | `cmd_run` (gate root redirected to the test directory): goal-on failure, null-goal failure, a raised goal-on check and goal-on ticks over the cap each return 3 with no seed started, `stopped_at` named and the ticks on the P1 ledger; a complete P1 (29,069) starts seed 0; nothing written under `runs/` |

`python rl/m7s_analysis.py self-test` → PASS.

**Preflight** `python rl/m7s_gate.py preflight` (2026-09-29T03:19:24Z), read-only:

- unit suite 24 / 24 and analysis self-test PASS;
- P1 goal-on expectation: no problem (reach 774, v3 `c9000896…`);
- D: base `D:\BattleShip_runs_backup\2026-09-28` (377,359 files, PASS, verified 2026-09-28T20:44:33Z, manifest intact)
  + increment `2026-09-28_incr_m7r` (5,163 files, prefix `m7r/`, PASS, verified 2026-09-28T23:17:13Z, manifest
  intact) cover **382,522** files under `runs/`, **0 uncovered**; neither record was written;
- no game process; the executable is present;
- `problems` = only "no approval record … (the gate is not authorised)".

No game process was started, no approval record was created, and nothing was written under `runs/` (`runs/m7s` does
not exist).

## 6. Goal sensitivity

**Initialisation** (4,000 of 27,529 real v3 observations from the pinned traces; goals from 215 of their own cells;
κ = 1.0):

| seed | trunk sat95 | goal-branch sat95 | joint sat95 | goal share of joint pre-activation | goal / state sensitivity | action TV for a goal swap |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 0.172 | 0.000 | 0.035 | 0.135 | 0.456 | 0.00042 |
| 1 | 0.103 | 0.000 | 0.026 | 0.134 | 0.399 | 0.00043 |
| 2 | 0.095 | 0.000 | 0.028 | 0.147 | 0.445 | 0.00043 |

**After training** (gate): R_final and U on the same 4,000 states from R's own episodes and goals from the frozen E
cells. A goal-blind R shows a TV near U's (about 0.0004) and `goal_blind_flag = true`, which **now blocks a pass** for
that seed (rule v2). The synthetic GCSL case shows the flag's intended separation: trained R 0.130 vs U 0.00030.

## 7. Remaining risks

- **No live path has run.** P1 (b) is the first live exercise of a `goal_reached` end, standby promotion under the goal
  wrappers, the parked-process retire and the real recorder / tracker labels; phase B / evaluation paths
  (`M7SubprocVecEnv` with the `goal` key, `env_method_each`, idle resets leaving a parked process until close) are
  still exercised only by the gate itself.
- **P1 (b) assumes native determinism on the pinned words.** The trace was recorded with two extra diagnostic flags
  (`SSB64_RL_INPUT`, `SSB64_RL_TARGET_DIAG`) that the M7n environment does not set; both were validated as
  gameplay-neutral (M7f / M7q) and the v3 builder reads neither key, but a mismatch there would stop the gate (a false
  stop costs 29,069 ticks at most, never training).
- **Promotion is not guaranteed** in the second repetition: a late standby gives `cold_fallback`, which P1 accepts as a
  normal start and records.
- **Goal-blind seeds can count toward outcome 2 (fail) — by decision.** The user confirmed (2026-09-28) that rule v2
  stays as implemented: goal blindness blocks a pass only; a goal-blind seed that independently meets the registered
  failure conditions (functional, data present, T ≤ 1) contributes to "return not learned".
- **The 0.01 threshold** separates the synthetic learner (0.130) from untrained networks (~0.0004) by wide margins; a
  real R between them is possible and would be classified by the fixed value, not re-examined.
- **Clear replay cap 2 per seed.** A third clear in one seed would be reported and not claimed until a separately
  authorised replay (extremely unlikely: no clear anywhere in the project).
- **Unmeasured:** throughput and memory (R's dataset about 1 GB per seed).
- **Noisy rarity:** rare goals from 20 episodes include some chance-reachable at up to 9 % (F10); the paired comparison
  with U absorbs this.
- **Learning risks:** GCSL multimodality at shared early states; per-tick stochastic drift; 7,000 gradient steps may be
  too few; trunk saturation may grow with training (M7p: 0.77–0.82 on trained networks).
- **Low power:** two episodes per goal and arm.
- **Inherited:** `m7g_tests.unit_training_isolation` already fails at HEAD because of 11 older files, none of them m7s;
  old campaign drivers' code manifests will see the new files.
- **Backup afterwards:** a later run's `runs/m7s/` needs its own D: increment.

## 8. Before gate authorisation

1. **Review revision 5**: the P1 goal-on registration (trace, goal, reach tick 774 = returned `input_tick`, two
   repetitions of 774 updates, termination criteria), the clear handling and cap, and the revised caps. The rule-v2
   goal-blind clause (pass path only) and the 1,548-tick P1 (b) accounting (section 3.1) are settled.
2. **Authorise, if approved,** by saving the reviewed `python rl/m7s_gate.py approval-template` output as
   `docs/rl_gcsl_return_m7s_gate_approval.json` with an `APPROVED:` line. Not created here. Any further edit to an m7s
   file changes the pinned code hashes and needs a fresh template.
