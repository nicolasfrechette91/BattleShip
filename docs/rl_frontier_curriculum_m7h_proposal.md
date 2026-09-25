# RL M7h: frontier-restart curriculum on v1: design and contract

Status (2026-09-24): **proposal, revision 2, for review.** Nothing is implemented, registered, trained, committed or
pushed.

This revision supersedes revision 1. Revision 1 replayed the prefix inside the worker's `reset()`, so a policy-facing
reset consumed actions. That broke the established reset contract ("reset returns the tick-0 observation without
consuming an action"), whatever the base environment did underneath.

This is the registered gate-7 response of Phase K ("the next milestone proceeds with category D on v1"). See
[`rl_obs_v2_phase_k_comparison_m7g.md`](rl_obs_v2_phase_k_comparison_m7g.md), including Addendum A. It revises the
deferred M7f recommendation, [`rl_next_experiment_m7f_proposal.md`](rl_next_experiment_m7f_proposal.md).

## 0. Summary

- **One variable changes: the start state of training episodes.**
  - With probability 1/2, a training episode starts at tick 0 exactly as today.
  - Otherwise, **after** the environment's ordinary non-consuming reset has returned the tick-0 observation, a
    separately recorded **prefix phase** runs. It replays canonical Track 1 steps from this run's own earlier episodes,
    up to a rarely visited "frontier" cell.
  - Only then does PPO take its first action in that episode.
- **Every `reset()` call keeps the contract.**
  - `reset()` returns the tick-0 observation, consumes nothing and never steps.
  - The prefix phase is a different operation: a worker control command sent by a VecEnv wrapper between the
    subprocess VecEnv and VecNormalize.
- **This is feasible with the current stack.**
  - It needs no change to SB3 2.9.0 and no change to `M7PPO`.
  - It uses SB3's VecEnvWrapper extension point and the project-owned worker protocol (`env_method`).
- **What PPO sees changes, and this is declared.** For a curriculum episode, the first observation the policy receives
  is the post-prefix observation `o_L`, not `o_0`. `o_0` is recorded but is not a policy input. No curriculum can let
  the policy start acting at tick L while giving it the tick-0 observation, so the contract question is only whether
  reset consumes actions. Here it does not.
- **Unchanged:**
  - the observation, reward and action contracts;
  - the native game and protocol;
  - PPO, the lifecycle and evaluation;
  - the M7f cell key.
- **Evaluation stays tick-0 full-task only.**
- **The crossing fixtures stay out.** Neither user crossing fixture, nor the TAS, nor another run can enter training,
  the archive or selection.
- **Crossings are counted by who produced them.** A new left entry made by policy-controlled actions is kept apart
  from a left position that a prefix merely reproduced. Only the former satisfies the training-discovery gate.
- **Checks before the campaign:**
  - a bounded engineering check (E1–E7), which includes a low-memory stop drill and no crossing search;
  - the accepted curriculum-off reproduction check (R1–R3), which is the condition for reusing the historical v1
    control.
- **The in-run memory stop is reassessed** (section 6.3). A cooperative stop at 3 GiB of available commit, sampled
  every 2 s, replaces "1.5 GiB in two consecutive 15-s samples".

## 1. What stays fixed

| Item | Value |
| --- | --- |
| Reset contract | **Every** `reset()`, in every start kind, launches a fresh process (standby promotion or a cold start), returns the proven tick-0 observation (step_count 0, input_tick 0, from the non-consuming `observe`) and consumes no action. |
| Observation | `btt_policy_obs_v1` (15 float32 values), VecNormalize on observations only |
| Reward | `btt_reward_v2`: +1 per target, −0.001 per step, +10 on a native clear, −5 on a native failure |
| Actions | Track 1 `btt_s9_b8_v1`, `MultiDiscrete([9, 8])`, mapped to canonical native inputs (`rlaction_native_v1`) |
| Native | executable `1e7c62a0…`; decomp `3c7fd5d05`, libultraship `805f1950`, torch `3aa9c97`; protocol 1; no native change |
| Episode | 3,600-tick horizon counted from tick 0; fall = `native_failure` |
| Lifecycle | N = 5 workers with M7c standby (at most 2 processes per worker and 10 in total), no-render, Raphnet bypass |
| PPO | the M7e settings (`n_steps` 1,024 × 5, batch 512, 10 epochs, lr 3e-4, γ 0.999, λ 0.995, clip 0.2, `ent_coef` 0, [64, 64] tanh, CPU); SB3 2.9.0 |
| Checkpoints | every 102,400 policy transitions, plus `final` |
| Evaluation | the Phase K protocol, tick-0 starts only (section 6.1) |
| Diagnostics | `SSB64_RL_TARGET_DIAG` and `SSB64_RL_SPATIAL` are **off** in training |
| RNG | native RNG state is never inspected, logged, controlled, compared, validated or hashed. The curriculum uses its own seeded Python generator in the parent process only. |

## 2. The contract (`btt_curriculum_frontier_v1`)

### 2.1 The components and what each one does

| Component | Curriculum on | Curriculum off |
| --- | --- | --- |
| worker env `reset()` (the full worker stack, including the M7c standby) | **unchanged**; returns `o_0`, consumes nothing | unchanged |
| worker control method `run_prefix_phase(spec)` (new, called through the worker's `env_method` protocol) | runs the explicit prefix phase on the freshly reset episode | not constructed |
| `CurriculumVecEnv` (new VecEnvWrapper **between** `M7SubprocVecEnv` and `VecNormalize`) | archive, start selection, prefix dispatch, and delivery of the first policy observation | not constructed |
| `VecNormalize`, `M7PPO`, the SB3 rollout loop | unchanged code | unchanged |

With the curriculum off, the training stack is object-for-object the Phase K stack. R1 proves that the stack also
behaves the same.

### 2.2 The sequence at an episode boundary

Environment i's episode ends during vector step t. SB3 2.9.0 `collect_rollouts` calls `env.step(actions)` on
VecNormalize, which calls `CurriculumVecEnv`, which calls `M7SubprocVecEnv`.

1. **The worker auto-resets, unchanged.** For env i, `m7_worker` runs `env.step(a)`. The episode ends (terminated or
   truncated), and the worker records `terminal_observation` and `TimeLimit.truncated`. It then calls `env.reset()`,
   which does the following:
   - retires the process;
   - promotes the standby, or cold-starts a process;
   - returns the proven tick-0 observation `o_0`, consuming nothing;
   - starts booting the next standby.

   The worker's recording wrapper opens the new episode's recorder with `o_0` as its initial observation. The reward
   wrapper initializes from `o_0`. The worker replies `(o_0, r, done=True, info, reset_info)`.
2. **`CurriculumVecEnv.step_wait` receives all replies.** The step's rewards, dones and the previous episode's
   `terminal_observation` are left exactly as returned.
3. **Ingestion.** For each done env, in index order, the wrapper ingests the finished episode's archive report
   (carried in that step's `info`) into the parent-side archive (section 3).
4. **Selection.** For each done env, in index order, the wrapper draws a start (section 3.2).
5. **Prefix dispatch.** For every env that drew `archive_prefix`, the wrapper sends
   `run_prefix_phase(prefix, expected_end_observation, meta)` to that worker. All selected workers receive their
   command before any reply is awaited, so the phases run **in parallel**. The wrapper then collects each reply, the
   post-prefix policy observation `o_L`.
6. **Delivery.** The wrapper places `o_L` in the observation it returns for env i. Envs that start at tick 0 keep
   `o_0`. The start record goes into `reset_infos[i]` and into the worker's episode row.
7. **VecNormalize** updates `obs_rms` with that observation and normalizes it. It also normalizes the previous
   episode's `terminal_observation`, as today.
8. **PPO** stores the previous episode's final transition with its unchanged reward and terminal handling. It sets
   `_last_obs[i] = o_L` and `_last_episode_starts[i] = True`. Its **next** action for env i is the first
   policy-controlled step, which consumes tick L.

**The initial `reset()` at the start of training** (VecNormalize.reset → CurriculumVecEnv.reset → M7SubprocVecEnv.reset)
goes through steps 4–7 as well. The archive is empty then, so every start is tick-0.

### 2.3 The prefix phase inside the worker (`run_prefix_phase`)

1. **Preconditions.** The episode must be fresh:
   - phase `active`;
   - base `_steps` = 0;
   - worker `step_in_episode` = 0;
   - the recorder holds 0 rows;
   - the last observation is `o_0` with input_tick 0.

   If any precondition fails, the worker raises, which stops the run with a hard failure. A prefix can therefore never
   follow a policy action, and it never runs inside `reset()`.
2. **Replay.** For i = 0 … L−1, the worker sends the archived action `a_i` through `M7BattleShipBTTEnv.step()`. That is
   the same request path, fall detection, timing and `_steps` horizon counter a policy step uses. Each `a_i` is a Track
   1 pair stored with its canonical native triple and checked to be Track 1-representable.
   - Each step is written to the **same episode recorder** with `phase: "prefix"`.
   - Each step requires `consumed_tick == i` and state `WaitingForAction` (no `EpisodeEnded`, no truncation, no native
     failure).
3. **The end check.** `o_L` (input_tick = L) must equal the archived end observation in every field except
   `host_frame`, which is compared and reported.
4. **Reward rebase.** `M7RewardWrapper.rebase(o_L)` sets its previous target count from `o_L`. Its return, step count,
   targets-broken count and failure terms stay 0.
5. **Records.** The tracker notes the start record; the recorder notes the phase boundary (the first policy row is L).
6. **The reply** is `o_L` passed through the same Track 1 observation mapping that `reset()` and `step()` apply, so the
   policy receives the ordinary 15-value v1 vector.

**Why this phase is never hidden:**
- every prefix step is a real native step, and its consumed tick is recorded in the episode's own artifact;
- it is issued by a named command, separate from `reset()`;
- it is summarized in the episode row and in `reset_infos`;
- it is never a VecEnv step, so it is never a policy action, never scored and never a transition.

### 2.4 The reset contract, stated precisely

| Guarantee | Holds for | How it is checked |
| --- | --- | --- |
| `reset()` consumes no action and returns input_tick 0 with step_count 0 | **every** episode, both start kinds | E4: 100 % of episodes; the recorded initial observation is `o_0` |
| the first recorded action row has consumed tick 0 | every episode | E4 |
| the prefix runs only between a completed reset and the first policy action | every curriculum episode | the E1 preconditions; E4 |
| the first observation the policy receives equals `o_0` | **tick-0 starts only** | declared: for `archive_prefix` starts it is `o_L`, the output of the recorded prefix phase |

### 2.5 Worked example with L = 1,200

| Phase | Requests | Consumed ticks | Returned to | Enters `obs_rms` | Reward | PPO transitions |
| --- | --- | --- | --- | --- | --- | --- |
| worker `reset()` (auto-reset inside the `step` command) | one non-consuming `observe` | none | `CurriculumVecEnv` (`o_0`) | **no** (it is not delivered to the policy) | the reward state is initialized from `o_0` | none |
| `run_prefix_phase` (a separate command) | 1,200 `step` requests with `a_0 … a_1199` | 0 … 1,199 | `CurriculumVecEnv` (`o_1200`) → VecNormalize → PPO | **yes**, as env i's observation for that vector step | none; the reward state is rebased on `o_1200` | none |
| policy | up to 2,400 `step` requests | 1,200 … 3,599 | VecNormalize → PPO | yes, one per step | −0.001, plus target / clear / fall terms | at most 2,400 |

### 2.6 VecNormalize counts

- SB3 2.9.0 `VecNormalize.step_wait` calls `obs_rms.update` on exactly the batch the wrapped VecEnv returns: one
  observation per env per vector step. `VecNormalize.reset` does the same once.
- Because `CurriculumVecEnv` sits **below** VecNormalize, the start observation that enters `obs_rms` is `o_L` for a
  curriculum start and `o_0` for a tick-0 start. The `o_0` of a curriculum episode never enters it, because the policy
  never acts on it.
- **The count invariant is unchanged:** `obs_rms.count = ε + n_envs + num_timesteps`, with ε = 1e-4. For example,
  `m7e_s0_v2` `ckpt_000102400` records 102,405.0001, and `m7g_s0_v1` `final` records 3,072,005.0001. E4 checks the
  invariant exactly.
- Normalization of `terminal_observation` is unchanged. Reward normalization stays off.

### 2.7 Rewards and horizon

- **Rewards.**
  - The prefix bypasses the reward wrapper, and the rebase makes the first policy step's target delta relative to
    `o_L`. **Targets broken during the prefix earn nothing** and are recorded as `prefix_targets_broken`.
  - The reward of the vector step in which the previous episode ended belongs to that episode and is unchanged.
  - The episode return is the sum over policy steps only.
- **Horizon.**
  - Prefix steps pass through `M7BattleShipBTTEnv.step()` and increment `_steps`. So every episode not ended by a clear
    or a fall still truncates on the step that consumes tick 3,599 (`truncation_reason = max_episode_steps`).
  - Policy steps are therefore at most 3,600 − L.
  - `input_tick` and `time_passed` in the observation tell the policy how much time is left.
  - The worker's `TimeLimit.truncated` flag and SB3's value bootstrap at the time limit are unchanged.

### 2.8 Standby promotion and processes

- The auto-reset promotes the standby (M7c) and starts the next standby boot **inside `reset()`**, before the prefix
  phase begins. The boot therefore overlaps the replay.
- The prefix phase runs only on the **active** process, and only after `step_wait` has collected every reply. A
  standby is never stepped; it stays parked at tick 0.
- The process bound is unchanged: one active and at most one standby per worker, 10 in total.

### 2.9 Prefix cost

- **Cost per tick.** Each prefix tick is one native step round trip without a policy. Two measurements bracket it:
  - M6 measured the raw step at 0.45 ms median, 2,112.5 ticks/s (`docs/rl_throughput_m6.md`);
  - the Phase K target-6 replays ran at 972–1,210 ticks/s through the Python client with the diagnostic on.

  The design assumes 1,000–2,000 ticks/s.
- **Stall.** The phase runs inside `CurriculumVecEnv.step_wait`, so the vector step waits for the longest prefix
  dispatched in that step. Phases in different workers overlap.
- **What is recorded.** Each episode records `prefix_wall_s` and L. Each run records the total prefix ticks, the total
  stall and the stall per vector step.
- **Projection (an assumption, measured in E6):**
  - 550–740 curriculum starts per run;
  - a mean L between 1,500 and 3,000;
  - 7–37 min of added stall;
  - **43–73 min per training run**, against the 36 min of v1.

  The extra round trip for the command itself is negligible.

### 2.10 PPO transition counts

- `num_timesteps` grows by `n_envs` per vector step only. The prefix phase is not a vector step.
- **The budget of 3,072,000 is exactly 3,072,000 policy transitions** (600 rollouts × 5,120).
- The first stored transition of a curriculum episode has observation `o_L` and `episode_start = True`, the same flag
  as for any new episode.
- GAE episode boundaries, the time-limit bootstrap and the rollout buffer are unchanged.

### 2.11 What is recorded

- **Episode artifact: one contiguous trajectory from tick 0.**
  - The initial observation is `o_0`, the reset observation.
  - Rows 0 … L−1 have `phase: "prefix"`; rows L … have `phase: "policy"`.
  - `native_action_digest` covers all rows, so every curriculum episode replays from tick 0 with the existing M7f tools
    as they are.
  - A `start` block holds:
    - the kind and L;
    - `prefix_digest` (the native action digest of rows 0 … L−1);
    - the cell, and the source run, episode, rank and worker episode;
    - `lineage_left_exposed`;
    - `prefix_end_observation` (`o_L`);
    - `prefix_wall_s` and `prefix_targets_broken`.
- **Training row:**
  - `start_kind` and `prefix_length`;
  - `policy_steps` and `total_consumed_ticks` (= L + policy steps);
  - `targets_broken_total` and `targets_broken_policy`;
  - the left-region class (section 4).
- **`reset_infos[i]["m7h_start"]`:** the same start record, for the parent's logs.
- **With the curriculum off, no `phase` field and no `start` block are written.** Artifacts and rows keep their
  current form.

### 2.12 Failure handling

| Event | Handling |
| --- | --- |
| A precondition fails (the episode is not fresh) | **Hard failure; the run stops.** This is a defect. |
| `consumed_tick ≠ i`, an unexpected state, an end or truncation during the prefix, or an end-observation mismatch | **Hard failure; the run stops.** Exact replay is a validated invariant. The recorder is finished `failed` and preserved with the raw trace. |
| Lifecycle failure during the prefix (process death, transport error, timeout) | The recorder is finished `failed` and preserved. The worker performs a fresh, non-consuming `reset()` and returns its `o_0`. The parent delivers it as a tick-0 start of kind `tick0_after_prefix_lifecycle_failure`, with a soft alert. More than 3 in one run → hard stop. |
| An archived action that is not Track 1-representable | **Hard failure; the run stops.** |

## 3. Archive and cell selection (parent side)

### 3.1 Cells, ingestion and eligibility

- **Cell key (decided: the M7f key):** `(⌊position_x / 300⌋, ⌊position_y / 300⌋, targets_remaining)`. It is computed on
  live steps only (`fighter_valid = 1` and `btt_active = 1`).
- **Sources:** only the finished **training** episodes of the same run, both kinds. Never evaluation, the TAS, crossing
  fixtures, capture recordings, other runs or hand-written routes.
- **The report.** At an episode's end, the worker attaches a compact report to that step's `info`:
  - the full trajectory as Track 1 indices (one byte per action, 0–71);
  - each cell's first live step on a **policy** row;
  - the observation after that step;
  - the set of cells visited on policy rows;
  - the end reason, end tick and lineage flags.
- **Ingestion** (in env-index order, before selection in the same vector step):
  - A cell first reached at step j has **L = j + 1** and end observation `o_{j+1}`.
  - A new cell is added.
  - A **strictly** shorter L replaces the existing prefix and keeps its visit count. Equal lengths keep the existing
    entry.
- **Visits:** `visits(c)` counts the episodes in which c occurred on at least one policy row.
- **Eligibility**, all of the following:
  - 1 ≤ L ≤ 3,000, so at least 600 policy ticks remain;
  - the source did not end at or before step L − 1;
  - the source's native failure, if any, happened more than 60 ticks after step L − 1.
- **Storage:**
  - in memory in the training parent, at most about 15 MB (for example 5,000 cells × 3,000 one-byte actions);
  - persisted with every checkpoint set as `curriculum_archive.json` plus `curriculum_prefixes.bin`, including the
    selection generator's state;
  - a curriculum run is never resumed; a partial run is restarted.

### 3.2 Selection

The parent owns `random.Random(sha256("btt_curriculum_frontier_v1", run seed))`. It is separate from the global `random`
and `np.random`, and it is not constructed when the curriculum is off. For each done env, in index order:

1. Draw u₁ ∈ [0, 1). If u₁ < 1/2, the start kind is `tick0`.
2. Otherwise, if no cell is eligible, the start kind is `tick0_archive_empty`.
3. Otherwise draw u₂ and pick eligible cell c with probability w(c) / Σw, where w(c) = 1 / √(1 + visits(c)). Cells are
   in archive insertion order, and the choice is made by an inverse-CDF walk.

### 3.3 Determinism

- Workers step in lockstep. Episode ends and their order therefore follow from the deterministic game and the seeded
  policy sampling.
- Ingestion and selection happen in the parent, in env-index order within each vector step.
- **A curriculum run is therefore reproducible from (seed, code, executable).** This is a requirement, checked by E5.
- There is no snapshot staleness: a cell ingested at vector step t can be selected from step t on.

### 3.4 Isolation

1. **Static source guard.** No curriculum, archive, selection or trainer module refers to `rl/fixtures/`,
   `runs/m7g/capture/`, `tas_input_2/`, `runs/m7f/` or any other run's directory. A test enforces this.
2. **Runtime provenance.** Every archive entry names an episode of **this** run, and its `prefix_digest` equals the
   digest recomputed from that episode's reported trajectory.
3. **Evaluation.** Evaluation never constructs `CurriculumVecEnv` or the worker's prefix method. The evaluation verifier
   requires `start_kind = tick0` and L = 0 for every episode. The historical control evaluations predate the field and
   are tick-0 by construction.
4. **The fixtures are read by nothing in M7h,** including the checks.

## 4. Left-region metrics: policy-controlled versus reproduced

**Definitions:**
- A **live left step** is a step whose post-update observation has `fighter_valid = 1`, `btt_active = 1` and
  `position_x < −2100` (strict). This is the `btt_eval_metrics_v1` / M7g-a rule.
- **Policy-controlled** means a row with `phase: "policy"`. All rows of a tick-0 start are policy rows.
- **Prefix-reproduced left position:** a live left step on a prefix row.
- **Policy-controlled left entry:** the first live left step on a policy row, in an episode with no prefix-reproduced
  left position.
- **Lineage left-exposed:** the prefix's source trajectory has any live left step **anywhere**, including after the cut,
  or its source's lineage is left-exposed. Tick-0 starts are never exposed.

**Classification:**

| Class | Condition | Counts toward the discovery gate |
| --- | --- | --- |
| `genuine_new_policy_entry` | a policy-controlled left entry, and the lineage is not left-exposed | **yes** |
| `policy_reentry_exposed_lineage` | a policy-controlled left entry, but the lineage is left-exposed (this includes momentum carried from a prefix cut just before its source crossed) | no |
| `prefix_reproduced` | a live left step on a prefix row | no |

**Property.** Prefix replay is exact, so any left position inside a prefix reproduces an earlier trajectory's left
position. Therefore a run's earliest live left step is always on a policy row of a never-exposed lineage.

**Verification.** For each F seed, the first `genuine_new_policy_entry` episode, and up to 5 more, is replayed from tick
0 in a fresh process with the M7f replay path and the evaluation-only target diagnostic. The replay must confirm:
- every consumed tick;
- that the first live left step is on a row ≥ L;
- that no prefix row is a live left step.

g_s = 1 if and only if seed s has at least one verified genuine new entry.

**Limitations:**
- Left-*target* identity is measured only in evaluation.
- The historical control recorded no per-step positions in training, so G applies to F only.

## 5. Checks before the campaign

### 5.1 Engineering check E1–E7

The check is bounded to **2 hours of machine time** in total. Every item is pass/fail, and a failure is a defect to fix.
**It contains no crossing search, and no crossing outcome can block the experiment.**

| # | What | Pass condition |
| --- | --- | --- |
| E1 | **Unit tests, no game.** Archive ingestion (first reach, strictly-shorter replacement, ties, visits on policy rows, eligibility at the L bounds, the 60-tick window, clears); selection (p0, exact weights as fractions, empty archive, fixed draw sequence); curriculum off draws nothing and constructs nothing; `CurriculumVecEnv` against a fake VecEnv (only selected done envs are substituted; one observation per env per step reaches the normalizer; `terminal_observation`, rewards and dones untouched; the initial reset; simultaneous dones handled in index order); the prefix preconditions refuse a non-fresh episode; the discovery classes on synthetic traces (including x = −2100.0, an entry on the first policy row, an exposed lineage, and a left step on a prefix row); the reward rebase; the artifact `phase` rows and digest | all pass |
| E2 | **Isolation.** The static source guard; runtime provenance of every archive entry after E4; every evaluation episode `tick0` | 100 % |
| E3 | **Exact prefix replay** through `run_prefix_phase` in the real worker path: every eligible entry up to 200 from the E4 archive (stratified by L), plus L = 1, 2 and the largest eligible; standby-promoted starts plus at least 10 forced cold-fallback starts (the existing standby fault hook). Also 20 finished curriculum episodes re-replayed from tick 0 with the M7f tools. | consumed ticks exact; end observation equal (`host_frame` reported); no end in the prefix; all actions Track 1; full-trajectory replays exact |
| E4 | **Accounting and contract smoke:** curriculum on, seed 0, 102,400 transitions | **reset contract:** 100 % of episodes have a recorded `o_0` with input_tick 0 and step_count 0, and a first row at consumed tick 0. **Accounting:** `total_consumed = L + policy_steps ≤ 3,600`; horizon ends at tick 3,599; `num_timesteps = 102,400 = Σ policy steps`; `obs_rms.count = ε + 5 + 102,400`; return = Σ policy-step rewards; prefix targets unrewarded; the first delivered observation of every curriculum episode equals the archived `o_L` |
| E5 | **Determinism:** the E4 configuration twice at 51,200 transitions, same seed | identical checkpoint digests, rows, archive and selection logs |
| E6 | **Timing and resources:** prefix ticks/s, stall per vector step, end-to-end transitions/s against R1's curriculum-off run, commit and physical draw | throughput ≥ 1/2 of curriculum off; projected training ≤ 75 min per run; the draws are recorded for the gate |
| E7 | **Low-memory stop drill:** during a short curriculum-on smoke, lower the stop threshold through a test-only override to just above the current available commit, then run the full stop sequence of section 6.3 | stop reason recorded; the model equals the last completed update; the `interrupted/` set is complete and hash-valid; in-flight episodes preserved as `aborted` with their prefix and policy rows; no BattleShip process left; the run directory moved to `_partial/`; the E4 periodic sets are byte-identical before and after |

E4, E5 and E7 are short smoke trainings (at most about 230k transitions in total), not campaign runs.

### 5.2 Curriculum-off reproduction check R1–R3 (accepted; condition for reusing the control)

**Preconditions:**
- the executable is `1e7c62a0…`, with the submodule pins of section 1;
- the M7h manifest is frozen;
- profiles `m7h_c_s{0,1,2}` exist with the curriculum absent. Their training compatibility view equals that of Phase K
  `m7g_s{s}_v1` except for `curriculum = "none"` and the name / output paths.

| # | What | Pass condition |
| --- | --- | --- |
| R1 | **Training.** For each seed s ∈ {0, 1, 2}, run `m7h_c_s{s}` with the curriculum off for exactly 102,400 transitions in a fresh directory. | (a) Its final `(policy_parameter_digest, obs_rms_digest)` equals `runs/m7e/m7e_s{s}_v2/checkpoints/ckpt_000102400`; for seed 0 that is `5cec5fc4…` / `050acde9…`. (b) Its training rows equal, in order and in number (30 / 27 / 29), the M7e rows with `sb3_num_timesteps_seen ≤ 102,400`, on `(rank, worker_episode, end_reason, steps, targets_broken, native_action_digest)`. (c) Every row is tick-0 and no `phase` field is written. (d) Neither `CurriculumVecEnv` nor the prefix method nor a curriculum generator is constructed, and no archive file exists. |
| R2 | **Evaluation.** Re-evaluate `runs/m7g_k/m7g_s{0,1,2}_v1/final` with the new code, using the Phase K final protocol (100 stochastic + 100 deterministic, `SSB64_RL_TARGET_DIAG=1`). | 600 of 600 episodes, keyed by `(mode, rank, worker_episode)`, equal `runs/m7g_k/_eval/m7g_s{s}_v1/final` on `(native_action_digest, targets_broken, end_reason, full btt_eval_metrics_v1 record)`. |
| R3 | **Rule inputs.** Recompute k, χ, T and φ (section 7) from R2. | They equal the Phase K values: k = χ = 0, T = 472/100, 475/100, 427/100, falls 1 / 1 / 0. |

- **If R1, R2 and R3 all pass**, the historical control is reused as arm C.
- **If any fails**, `m7h_c_s{0,1,2}` are trained in full and evaluated (about +3.7 h).
- **Any code change after R** means manifest drift, and R is repeated.
- The stop and atomic-write changes of section 6.3 also touch curriculum-off code, so R runs after them.

## 6. The campaign

### 6.1 Arms, budget and evaluation

- **Arms:**
  - **C:** plain v1. It is the historical `m7g_s{0,1,2}_v1` if R passes, otherwise `m7h_c_s{0,1,2}`.
  - **F:** `m7h_f_s{0,1,2}`, the same configuration plus `btt_curriculum_frontier_v1` (a semantic TOML field that is
    part of the checkpoint identity) with p0 = 1/2, the M7f cell key, w = 1/√(1 + visits), 1 ≤ L ≤ 3,000 and a
    60-tick failure window.
- **Seeds:** 0, 1 and 2. Seeds 3 and 4 run only through the extension (section 7.4).
- **Budget:** 3,072,000 **policy** transitions per run, a hard maximum. Prefix ticks are reported, not budgeted.
- **Order:** F s0, F s1, F s2. If C is retrained: C0, F0, F1, C1, C2, F2.
- **Evaluation:** post hoc, frozen statistics, tick-0 only; identical to Phase K.
  - labels `initial`, 9 curve points (every 307,200) and `final`;
  - stochastic 100 / 60 / 100 and deterministic 100 / 5 / 100, so 985 episodes per run;
  - `btt_eval_metrics_v1` with `SSB64_RL_TARGET_DIAG=1`;
  - clear verification, census, and `start_kind = tick0` asserted.
- **Primary metrics:** verified clears; crossing (final stochastic live x < −2100); final stochastic mean targets T,
  and its per-seed difference from C.
- **Secondary, never merged with crossing:**
  - left-target breaks (IDs 1, 6 and 8, each separately);
  - seven-target episodes;
  - target 2;
  - crossings and left-target breaks at every checkpoint.
- **Training diagnostics:**
  - the section-4 classes;
  - archive size and eligible cells;
  - the lowest x reached at y ≥ 3,000;
  - the distribution of L and prefix cost.
- **Guards:** falls, deterministic collapse and policy entropy.

### 6.2 Resources and launch gate

- **Estimate:** commit draw ≤ 5.4 GiB (v1 measured 5.04–5.16 GiB; the archive is at most about 15 MB); physical draw ≤
  1.3 GiB; at most 10 game processes; about 0.5 GB of disk per run including evaluation.
- **Launch gate** (Phase K Addendum A.2; pending approval): available commit ≥ 10 GiB and available physical ≥ 4 GiB
  before each launch.

### 6.3 The in-run memory stop: reassessment and a safe stop sequence

This section supersedes the Addendum A.2 recommendation "stop when available commit is below 1.5 GiB in two
consecutive samples".

**Why 1.5 GiB in two consecutive 15-s samples is not adequate:**
- **Detection dominates the reaction time.** The Monitor samples every 15 s, and two samples are required, so detection
  takes 15–30 s. The stop itself is fast: in Phase K, closing all workers took 0.45 s, and 31 checkpoint sets took
  1.23 s in total (a v1 set is about 0.2 MB).
- **The machine can sit near exhaustion for a long time.** M7e trained with a *mean* available commit of 1.74–2.08 GiB
  and a minimum of 1.49 GiB. A 1.5 GiB threshold is inside the range where a transient spike from any process can fail
  an allocation. That could crash a game (a lifecycle failure) or the trainer (a `MemoryError` outside the tidy stop
  path).
- **Background activity is real.** About 3 GiB of background swing was observed between same-day launches. A burst from
  another program can consume 1.5 GiB well within 30 s.

**The recommended policy** (implemented in the orchestrator, `m7d_run`, and the trainer; M7h scope):
- **Probe.** A lightweight thread calls `GlobalMemoryStatusEx` every 2 s, separate from the 15-s Monitor. It records
  the minimum per 15 s and every threshold crossing.
- **Warn** when available commit is below 4 GiB.
- **Stop cooperatively** on the first sample below 3 GiB. With the 10 GiB launch gate and a draw of about 5.6 GiB, the
  steady state keeps at least 4.4 GiB, so this stop fires only after at least 1.4 GiB of outside growth.
- **Escalate** to the existing CTRL_BREAK path if the trainer has not exited 30 s after the stop request.
- **Kill** (the existing path; the kill-on-close job object removes workers and games) when available commit falls
  below 1 GiB, or 240 s after CTRL_BREAK.

**The cooperative stop sequence and what it preserves:**
1. The orchestrator writes `coordination/STOP_REQUEST.json` atomically (reason and memory sample).
2. `M7Callback._on_step` checks for the file after every vector step and returns `False`. SB3 2.9.0 then abandons the
   rollout in progress, which is never trained on, and `learn()` returns.
   - The model is exactly the model after the last completed update.
   - A request that arrives during `train()` takes effect at the next vector step, within about 1 s.
   - A request that arrives during a prefix phase takes effect after the phase completes, because the phase runs inside
     `step_wait`.
3. The trainer sets status `stopped_low_commit`. It then requests manual preservation of the in-flight episodes and
   closes VecNormalize, `CurriculumVecEnv` and the workers (all existing paths). During this, each worker:
   - finishes its in-flight recorder as `aborted` and writes it, with prefix and policy rows from tick 0, so the
     trajectory can be replayed;
   - joins its standby;
   - disposes of its processes.

   This **releases** the games' commit (about 3.7 GiB) and the workers' commit (about 0.95 GiB) **before** the parent
   writes anything.
4. The parent writes the `interrupted/` set: the model, VecNormalize statistics, the preservation snapshot, and the
   curriculum archive with its generator state. It writes into `interrupted.tmp/` and renames the directory only after
   `checkpoint.json` with its file hashes is complete. This is a proposed change: today `save_checkpoint_set`
   writes directly into the final directory. The same atomic write applies to every periodic set.
5. `training_summary.json` is written atomically, as today. The JSONL metrics are append-only, and the existing reader
   ignores a torn final line.
6. The orchestrator verifies what exists and moves the run directory to `_partial/<name>__<utc>`. It never deletes it.
   It records the event, and restarts the run from scratch only after the launch gate passes again. A partial run feeds
   no rule and no other run's archive.

| Artifact | Cooperative stop | CTRL_BREAK escalation | Kill |
| --- | --- | --- | --- |
| periodic checkpoint sets | intact | intact | intact; a set that was being written stays `*.tmp` and is never used |
| `interrupted/` set | complete; model at the last completed update | complete; the model may be mid-update, which is flagged | absent |
| in-flight episode artifacts | written as `aborted`, replayable from tick 0 | same, after the pending replies are drained | lost; never used by any rule |
| finished episode artifacts and rows | intact | intact | intact, apart from a torn last line, which is ignored |
| curriculum archive | in `interrupted/` | in `interrupted/` | the last periodic set's copy |
| game and worker processes | closed, standby joined | closed | removed by the job object |

### 6.4 Stop conditions

- **Stop conditions:**
  - any hard failure or alert: a prefix mismatch or precondition failure; more than 3 prefix lifecycle failures; a
    leak; a process count above 10; a changed user config; low disk;
  - the memory policy of section 6.3;
  - a manifest drift;
  - the budget cap.
- A stopped run is restarted, never resumed.
- There is no early stop based on results.

## 7. Decision rule (to be registered before any campaign run)

The rule is applied once at n = 3, and once more at n = 5 only through the extension. It is never re-decided. All
quantities are exact rationals, and the first gate that fires decides. Every gate condition is reported.

### 7.1 Definitions

These are per arm a ∈ {C, F} and seed s, at the final checkpoint (3,072,000). Its evaluation has 100 stochastic and 100
deterministic episodes, all tick-0.

| Symbol | Definition |
| --- | --- |
| k_{a,s} ∈ {0, 1} | 1 if and only if at least one of the 200 final episodes is a **verified** clear (Phase K clear verification) |
| c_{a,s} | verified clears among the 100 final stochastic episodes, divided by 100 |
| χ_{a,s} ∈ {0, 1} | 1 if and only if at least one of the 100 final stochastic episodes has a live step with `position_x < −2100` |
| x_{a,s} | the number of such crossing episodes, divided by 100 |
| T_{a,s} | total `targets_broken` over the final stochastic episodes that are not verified clears, divided by their count; undefined if the count is 0 |
| φ_{a,s} | the number of final stochastic episodes ending in `native_failure` |
| K_a, X_a | Σ_s k_{a,s} and Σ_s χ_{a,s} |
| S_T, D_s, D̄ | S_T = the seeds where T is defined in both arms; D_s = T_{F,s} − T_{C,s}; D̄ = (Σ_{s∈S_T} D_s) / \|S_T\| |
| Φ_a | Σ_s φ_{a,s} / (100 n) |
| g_s, G | g_s = 1 if and only if F's training run of seed s has at least one verified `genuine_new_policy_entry`; G = Σ_s g_s (F only) |
| m(n) | m(3) = 2, m(5) = 3 |

**Known control values at n = 3** (confirmed by R3):
- K_C = X_C = 0;
- T_C = 472/100, 475/100, 427/100;
- Φ_C = 2/300.

**Reported, never gating:**
- left-target breaks;
- seven-target episodes, target 2;
- non-final crossings;
- deterministic results and entropy;
- the training classes other than `genuine_new_policy_entry`.

### 7.2 Gates at n = 3

| Gate | Condition, evaluated in order | Response |
| --- | --- | --- |
| 0 integrity | any of: R not passed (or the control not retrained); a run not verified; census incomplete; any evaluation episode not `tick0`; an archive entry without own-run provenance; a prefix mismatch; a reset-contract violation (E4 invariants re-checked on every campaign run) | no decision; report |
| 1 clears | K_F ≥ 2 | **adopt F**; the next milestone targets reliable clears |
| 2 crossings | K_F ≤ 1 and X_F ≥ 2 | **adopt F as the exploration base**; next milestone: from crossings to left targets and clears |
| 3 extension | gates 1 and 2 did not fire, and (K_F = 1 or X_F = 1) | seeds 3 and 4 in **both** arms (section 7.4), then section 7.3 |
| 4 discovered, not consolidated | gates 1–3 did not fire, and G ≥ 2 | record it. Next: a separately registered consolidation proposal built on F and the agent's own verified discoveries (never the fixtures). No budget extension. |
| 5 targets | gates 1–4 did not fire, and S_T ≠ ∅ | (a) D_s > 0 for every s ∈ S_T, D̄ ≥ 1/2 and Φ_F − Φ_C ≤ 1/10 → F preferred on targets and becomes the base; the ceiling stays open. (b) The same with Φ_F − Φ_C > 1/10 → record "more targets with more falls", not adopted; go to gate 6. (c) D_s < 0 for every s ∈ S_T and D̄ ≤ −1/2 → F worse on targets; the curriculum line stops. Otherwise → gate 6. |
| 6 null | none of the above | record "no measurable benefit of frontier restarts at 3.072M policy transitions". No extension; the next step is the user's decision. |

- **Inequalities:** "> 0" and "< 0" are strict, so D_s = 0 in any seed blocks 5(a) and 5(c). "≥ 1/2", "≤ −1/2" and
  "≤ 1/10" include equality.
- **Precedence example:** K_F = 1 with X_F = 2 is adopted at gate 2, and the single clear is recorded.

### 7.3 Gates at n = 5 (only through gate 3)

These use seeds 0–4. C seeds 0–2 are historical (or retrained), and C seeds 3–4 are new.

| Gate | Condition, evaluated in order | Response |
| --- | --- | --- |
| 0 integrity | as at n = 3, over all 10 runs | no decision |
| 1 clears | (a) K_F ≥ 3 and K_C = 0 → adopt F. (b) K_C ≥ 3 and K_F = 0 → F worse at clears; stop. (c) K_F ≥ 1 and K_C ≥ 1: let Δ = mean_s (c_{F,s} − c_{C,s}). If Δ ≥ 1/20 and c_{F,s} ≥ c_{C,s} for every s, adopt F. If Δ ≤ −1/20 and c_{F,s} ≤ c_{C,s} for every s, F is worse; stop. Otherwise record "clears in both arms" and continue. (d) Otherwise, if exactly one arm has 1 or 2 clear seeds → record "clear not reproduced (k of 5)" and continue. | as stated |
| 2 crossings | the same structure with X, x and the same thresholds (3, and 1/20) | (a) adopt F as the exploration base; (b) F worse at the ceiling; stop; (c) and (d) as for clears |
| 3 discovered, not consolidated | G ≥ 3 | as gate 4 at n = 3 |
| 4 targets | the same inequalities as gate 5 at n = 3, over S_T ⊆ {0 … 4} | as gate 5 at n = 3 |
| 5 null | none of the above | record "no measurable benefit after 5 seeds" |

At n = 5 there is no further extension.

### 7.4 The seed 3/4 extension

- **Triggered only by gate 3 at n = 3.** Targets, discovery, left-target breaks and non-final checkpoints never
  trigger it.
- **Runs:** four new runs at the same budget and protocol: `m7h_c_s3` and `m7h_c_s4` (curriculum off, the path proven by
  R) and `m7h_f_s3` and `m7h_f_s4`.
- **Order:** C3, F3, F4, C4. Each run passes the launch gate, and none starts before the n = 3 decision "extension
  required" is recorded.
- **Estimate:** about 5.4–7.3 h.

## 8. What is repository-validated, and what is assumed

| Repository-validated fact | Evidence |
| --- | --- |
| Replay of canonical actions from tick 0 is exact in fresh processes | M7f 3,074 / 3,074; M7g-a fixtures 8 / 8; the Phase K target-6 replay, 3 / 3 (Addendum A) |
| Track 1 crossings exist, and both pass high near the wall | the two validated user fixtures (lower entry 1,093 after an L1 takeoff at 912; upper entry 464 after a platform takeoff at 266) |
| No crossing and no seven-target episode in any evaluation so far | M7d, M7e, M7f, Phase K |
| The v1 control reproduces bit for bit | Phase K `m7g_s*_v1` = M7e `m7e_s*_v2` |
| The worker auto-resets inside its `step` command and returns the reset observation with the terminal step's reward and done | `rl/btt_parallel.py` `m7_worker` |
| `M7SubprocVecEnv` sends a command to every target before receiving, so the calls run in parallel | `rl/m7_vec_env.py` `_call` |
| `VecNormalize.step_wait` / `reset` update `obs_rms` with exactly the batch the wrapped VecEnv returns | SB3 2.9.0 `vec_normalize.py` |
| `collect_rollouts` counts `num_timesteps` per vector step, and `on_step() → False` abandons the rollout in progress | SB3 2.9.0 `on_policy_algorithm.py` |
| The horizon counts every base `step()` call, and reward initializes from the reset observation | `rl/battleship_env.py`; `rl/btt_learning.py` `RewardV1Wrapper.reset` |
| The existing stop path closes workers before saving `interrupted/`, and in-flight episodes are preserved as `aborted` | `rl/m7_trainer.py` (KeyboardInterrupt path); `rl/run_artifacts.py` `EpisodeRecordingWrapper.close` |
| `save_checkpoint_set` is not atomic today; `write_json` is (a temporary file, then a replace) | `rl/m7_trainer.py` |
| Stop costs and memory history | close 0.45 s, 31 sets in 1.23 s (Phase K v1 s0); M7e mean available commit 1.74–2.08 GiB |

**Design assumptions (unvalidated):**
- lack of coverage is a major contributor to the ceiling;
- the M7f cell with visit weighting reaches wall-top height near the wall;
- p0 = 1/2 does not starve tick-0 learning;
- the prefix cost projection;
- a curriculum run is bit-reproducible (E5 tests it);
- the 3 GiB / 2-s stop policy is adequate for this machine's background load;
- training discovery would precede evaluation crossings.

**The ceiling's cause is not assumed to be single.** Other contributors remain possible: the precision and
consolidation of 180–200-tick crossings, entropy collapse, perception, fall risk near edges, and the rarely broken
target 2.

## 9. Risks

- **A declared semantic difference.** For curriculum episodes, the first observation delivered to PPO is not the reset
  observation. Tooling that assumes "first observation = tick 0" must read the start record. Evaluation is unaffected.
- **More inherited touch points than revision 1** (section 10). Every one is inactive with the curriculum off, except
  the stop and atomic-write changes, which R covers.
- **The frontier may never reach wall-top height near the wall.** The result is then gate 6, which is informative.
- **Distribution shift** from mid-episode starts. Gate 5(c) and the fall guard expose it.
- **Stall cost:** up to about 73 min per run. E6 bounds it at 75 min.
- **Attribution:** training discovery has no control counterpart. Gate 4 routes to a proposal; it adopts nothing.
- **Nuisance stops:** a false low-memory stop only costs a restart.

## 10. Implementation cost

**New files:**

| File | Content | Estimated lines |
| --- | --- | --- |
| `rl/m7h_curriculum.py` | pure logic: archive, eligibility, visits, lineage flags, selection, discovery classes, serialization | 550–700 |
| `rl/m7h_vec.py` | `CurriculumVecEnv` (step_wait / reset interception, parallel prefix dispatch, start records, archive persistence hook) | 250–350 |
| `rl/m7h_prefix.py` | the worker-side prefix phase (preconditions, replay through the base env, recording, reward rebase, tracker note, reply) | 200–300 |
| `rl/m7h_matrix.py`, `rl/m7h_run.py`, `rl/m7h_analysis.py` | campaign drivers, reusing the Phase K drivers (manifest, gate, R1–R3, E-checks, census, `decide()` in exact fractions) | 1,200–1,600 |
| `rl/m7h_tests.py` | unit and game tests for E1–E7 and R | 1,000–1,400 |
| `rl/configs/m7h/*.toml` | C and F profiles for seeds 0–4, plus smoke profiles | about 14 files |

**Inherited touch points** (each inactive with the curriculum off, unless noted):

| File | Change | Estimated lines |
| --- | --- | --- |
| `rl/btt_parallel.py` | `M7WorkerWrapper.run_prefix_phase`; the archive-report info key; `M7RewardWrapper.rebase`; tracker start fields | 100–150 |
| `rl/run_artifacts.py` | an optional `phase` on recorded rows; the `start` block; the reader accepts both | 40–70 |
| `rl/m7_vec_env.py` | a per-index command call (different payload for each worker, sent in parallel) | 20–40 |
| `rl/m7_trainer.py` | build `CurriculumVecEnv` when enabled; archive in checkpoint sets; **cooperative stop check and `stopped_low_commit` status; atomic checkpoint-set writes (all runs)** | 120–180 |
| `rl/experiment_config.py` | the `[curriculum]` block (semantic field, fingerprint, resume refused) | 60–100 |
| `rl/m7d_run.py` | **the 2-s memory probe and the stop / escalation sequence (all runs)**; curriculum invariants in `verify_training_run` | 150–220 |
| `rl/m7_evaluation.py` | assert tick-0 starts | 10–20 |

**Totals and phases:**
- About 3,700–5,000 lines, of which about 500–780 are in inherited files.
- Honoring the reset contract costs about 600–900 lines more than revision 1: the VecEnv wrapper, the control method,
  the reward rebase, parallel dispatch and their tests.
- **I1:** pure modules and unit tests, no game.
- **I2:** integration, the stop changes and the game tests.
- **I3:** the E1–E7 and R1–R3 runs, about 2.5–3 h of machine time.
- Implementation effort is not estimated in hours.

**Machine time:**

| Step | Estimate |
| --- | --- |
| E1–E7 | ≤ 2 h |
| R1–R3 | ≈ 0.6 h |
| Campaign: three F runs | training 2.2–3.7 h, evaluation ≈ 1.8 h |
| If the control is retrained | + ≈ 3.7 h |
| Extension (only through gate 3) | + ≈ 5.4–7.3 h |

**Fallback if I2 or E1–E7 show that the VecEnv-level delivery cannot be made exact and deterministic:**
- M7h stops and reports.
- The contract-preserving alternative is a single-variable **entropy-coefficient arm** (`ent_coef` > 0, v1, reward v2,
  tick-0 starts only). It needs no start-state or reset change and only a small configuration change.
- It tests the entropy-collapse contributor, not coverage. M7f measured near-maximum-entropy play from tick 0 as equally
  confined, so its prior for crossings is lower.

## 11. Next gate and open decisions

**Next gate.** The user reviews and approves revision 2. After that:
1. **I1:** pure modules and unit tests.
2. **I2:** integration, the stop changes and the game tests.
3. **I3:** run E1–E7 and R1–R3, report, and **stop for review.**

The campaign is a separate approval.

**Decided:**
- the M7f cell key;
- the conditional reuse of the control through R1–R3;
- the Phase K addendum.

**Open:**
1. **Curriculum parameters:** p0 = 1/2, L ≤ 3,000, and the 60-tick failure window.
2. **Launch gate:** 10 GiB commit / 4 GiB physical.
3. **In-run memory policy:** a 2-s probe; warn at 4 GiB; cooperative stop at 3 GiB; escalate after 30 s; kill below 1
   GiB.
4. **Atomic checkpoint-set writes** for all runs: yes or no. It changes inherited code that R then re-verifies.

## 12. Non-goals

- no action inside `reset()`, no hidden reset action, save state or teleport;
- no observation change;
- no reward change, intrinsic bonus or shaping;
- no action-contract, native or gameplay change;
- no TAS or fixture data anywhere in training;
- no route or target-order hints;
- no evaluation from non-tick-0 starts;
- no native RNG handling;
- no silent budget extension.

## Revision history

- **Revision 1 (2026-09-24):** the prefix was replayed inside the worker's `reset()`. Superseded because it violated
  the tick-0 reset contract.
- **Revision 2 (2026-09-24):**
  - the prefix phase became a separate worker command dispatched by a VecEnv wrapper after the non-consuming reset;
  - the archive and selection moved to the parent, synchronous and without staleness;
  - the artifacts became contiguous from tick 0 with `phase` rows;
  - the VecNormalize count invariant is stated;
  - the M7f cell key is decided;
  - the low-memory stop was reassessed (section 6.3), with an E7 stop drill;
  - the implementation cost and a fallback were added.
