# M7m: anchored backward consolidation of the M7l training sweep (design, revision 1)

Status: implementation and the no-training feasibility gate only. Nothing in M7m has been trained. The paired
training comparison needs its own go-ahead from the user.

Fixed throughout, and unchanged from Phase K and M7l:

- btt_reward_v2, btt_policy_obs_v1 and Track 1 actions (btt_s9_b8_v1);
- the native tick, reset and horizon contracts (3,600 ticks), PPO settings, N = 5 workers with standby;
- the tick-0 evaluation protocol;
- no RNG seed inspection, validation, control, comparison or hashing of any kind.

## 1. Working hypothesis and claims

- **Working route hypothesis.** A first clear can be approached by sweeping the seven right-side targets before
  crossing. This is a working hypothesis. It is not a requirement of every clear.
- **What M7m tests.** Whether one policy-discovered right-side sweep can be repeated from tick 0 after training that
  restarts episodes from progressively earlier states of that sweep.
- **What M7m does not claim.** It does not claim that:
  - every clear needs this order;
  - a crossing made while target 2 is standing cannot lead to a clear;
  - M7l established why the sweep was not repeated.
- **What M7l recorded.** One verified training sweep: all seven right targets broken by tick 1030 in seed 1. There was
  no seven-right-target episode in any final tick-0 evaluation. The sweep remains a replay-verified training event,
  not a learned result.

## 2. The anchor (start states only)

The anchor is registered in `docs/rl_sweep_consolidation_m7m_anchor.json`. It is written once, and its digest is
pinned in `rl/m7m_anchor.py`.

- **Source.** Run `m7l_t2_s1`, training episode `episode_20260925T190612Z_49414363`.
- **How it was produced.** It started at tick 0 and was played by the M7l arm-T policy, which was trained under
  **btt_reward_v3_t2**. The episode ran from SB3 timestep 2,723,840 to 2,744,320.
- **Trajectory.**
  - 3,600 rows, ending at the horizon.
  - Native action digest `8ccf81f2…`.
  - Right-target breaks at consumed ticks 9@41, 0@119, 4@165, 5@580, 3@800, 2@837 and 7@1030.
  - No left entry, no clear, no fall.
- **Permitted use.** The user authorized it on 2026-09-25, solely as start states. Rows 0..τ−1 are replayed as an
  explicit native action prefix after a normal, non-consuming tick-0 reset.
- **Never used as:**
  - supervised targets (no imitation or action loss);
  - a source of policy weights, optimizer state or normalization statistics.
- **Excluded entirely.** The user's crossing fixtures and TAS are never training material.

## 3. Cut semantics

A cut τ is valid for 1 ≤ τ ≤ 1020. τ = 0 is an ordinary tick-0 start.

| Step | What happens |
|---|---|
| Reset | The ordinary non-consuming tick-0 reset: input_tick 0, nothing consumed. |
| Prefix | Anchor rows 0..τ−1 are submitted one per native tick. Row i must consume tick i and leave the game WaitingForAction. |
| Handover | The policy's first observation is o_τ, the observation after consumed tick τ−1. Its first action is for input tick τ. |
| Check | o_τ must equal the registered F1 table in every field except host_frame. The M7f broken mask must equal the anchor breaks at or before tick τ−1. |
| Horizon | Counted from the reset, so the policy phase has at most 3600 − τ steps. |
| Reward | The btt_reward_v2 reference is rebased at o_τ, so targets broken in the prefix earn nothing. |
| PPO rollout | Prefix steps run inside the worker between two vector steps. They never enter a PPO rollout, and `num_timesteps` counts only policy-controlled transitions. |
| Records | Prefix rows are recorded with the M7h `m7h_start` boundary label. |

Right targets standing at τ are those whose anchor break tick is ≥ τ.

- τ in 838..1020: target 7 only.
- τ in 801..837: targets 2 and 7.
- τ in 1..41: all seven.

**Success test.** An episode succeeds when all seven right targets are broken, the last at a consumed tick ≤ 2699.

- For a cut, this means the policy broke every right target still standing at τ by tick 2699.
- A later fall does not undo a success.
- At τ = 0 the test is the M7l fact R.

Target identity comes from the read-only M7f diagnostic (`SSB64_RL_TARGET_DIAG=1`).

## 4. Schedule

- **Pointer values.** The pointer τ* takes the values 1020, 900, 780, 660, 540, 420, 300, 180 and 60.
- **Windows.** Each window is [max(1, τ* − 119), τ*]:
  - W0 = [901, 1020], W1 = [781, 900], W2 = [661, 780], W3 = [541, 660];
  - W4 = [421, 540], W5 = [301, 420], W6 = [181, 300], W7 = [61, 180];
  - W8 = [1, 60] is the final window, clipped at 1.
- **Start draw.** Draws happen only after automatic resets; initial resets are tick-0 starts.
  - If u1 < p0 the episode starts at tick 0.
  - Otherwise the cut is τ = lo + ⌊u2 · (hi − lo + 1)⌋ within the current window.
  - p0 = 1/2 in arm E and 1.0 in arm K.
  - The draws use the run's own seeded `random.Random`, never the global generator and never native RNG.
- **Blocks.**
  - A block is 10 counted anchored outcomes from episodes started in the current window, counted in parent ingestion
    order.
  - A block with ≥ 5 successes moves the pointer back one window.
  - After a passing W8 block the schedule is complete.
  - A failed block starts a new block at the same window.
- **What is not counted.**
  - Stale outcomes, from episodes started under an earlier pointer, are logged.
  - Lifecycle failures and aborted episodes are logged as excluded.
- **Transition to tick 0.** Once the schedule is complete, every later start is a tick-0 start, logged as
  `tick0_schedule_complete` for the anchored half. Nothing else changes.

## 5. Arms, initialization and budget

Arms are paired by seed j ∈ {0, 1, 2}.

| | Arm E | Arm K (matched control) |
|---|---|---|
| Warm start | Phase K reward-v2 final `runs/m7g_k/m7g_s{j}_v1/final` | the same checkpoint |
| Schedule | `[anchor_curriculum]` with tick0_probability 0.5 | `[anchor_curriculum]` with tick0_probability 1.0 |
| Anchored starts | yes | never |

- **Same machinery in both arms.** K uses the same worker, vector wrapper, diagnostic flag, logging and warm-start path
  as E.
- **Warm starts, not fresh models.** Every run is warm-started from an existing checkpoint.
- **Identical handling in E and K:**
  - `model.zip` is loaded with its policy parameters and Adam optimizer state.
  - VecNormalize statistics continue: `training=True`, observation statistics update, rewards unnormalized.
  - `num_timesteps` continues from 3,072,000 (`reset_num_timesteps=False`).
  - Learning rate 3e-4 and clip range 0.2 are constants, so progress-dependent schedules have no effect.
  - `set_random_seed(base_seed)` runs at load, with the same base seed for E_j and K_j.
- **Warm-start acceptance.** The trainer accepts the warm start only when:
  - the source checkpoint was trained without any curriculum; and
  - the one compatibility difference is the added diagnostic flag, which is recorded in the lineage.
- **Budget.** +1,536,000 policy-controlled transitions per run, a hard cap of 300 rollouts of 5,120. The cumulative
  target is 4,608,000.
- **Prefix costs.** Prefix ticks and prefix wall time are reported separately and never counted as transitions.
- **Expected number of anchored episodes (a check, not an assumption).**
  - Phase K finals run tick-0 episodes to about 3,600 steps (1, 1 and 0 falls in 100).
  - With p0 = 1/2, anchored and tick-0 starts are about equal in number. So N_anch ≈ (1,536,000 − 5 · 3,600) /
    (3,600 + 3,600 − τ̄).
  - That gives about 243 anchored episodes while the pointer stays in W0 (τ̄ ≈ 960), and about 212 in W8.
  - Deduct about 2 stale outcomes per pointer move and about 3 episodes in flight at the end. That leaves roughly
    205–240 counted outcomes, i.e. 20–24 blocks.
  - Completing the schedule needs 9 passing blocks, so it tolerates only about 11–15 failing blocks in total.
  - **Completion is not assumed.** A window that needs many blocks, such as the target-2 step in W1, can end the
    budget first. Pointer progress is reported as it falls.

## 6. No-training feasibility gate

Registered in `docs/rl_sweep_consolidation_m7m_feasibility_plan.json` before any check runs. Executed by
`rl/m7m_feasibility.py`.

- **F1: source replay.** Full 3,600-row replays in 3 fresh processes, each checked for:
  - the pinned digest and consumed ticks 0..3599;
  - the break table and the horizon end;
  - the artifact's final observation.

  The table of o_τ for τ = 1..1020 must be identical across the three replays. It is written as
  `docs/rl_sweep_consolidation_m7m_anchor_observations.json`.
- **F2: encoding.**
  - The artifact's native rows map one-to-one onto Track 1 indices.
  - Re-encoding reproduces the digest.
  - The result equals the registered bytes.
- **F3: cut mechanics, through the actual M7m training worker.**
  - Cuts: 7 landmarks (42, 120, 166, 581, 801, 838, 1020) plus 50 registered random cuts.
  - At each cut the worker must deliver:
    - an o_τ equal to the table and the registered mask;
    - the prefix-boundary label, and a reward reference equal to the targets still standing at τ;
    - one neutral policy step that earns only v2 policy terms.
  - At τ = 42, 838 and 1020, the anchor's own remaining rows run through `step()` to the horizon. Each must give:
    - exactly 3600 − τ policy steps;
    - a return that is policy-only;
    - the anchor's full digest;
    - an episode row that passes the m7d validator.
- **Harness validation.** For each warm start, a deterministic tick-0 harness episode must reproduce the Phase K final
  deterministic evaluation digest and return.
- **F4: foothold.** Frozen warm-start policies with stochastic actions.
  - Cuts: 6 per window at offsets 0, 24, 48, 72, 96 and 119, with 5 episodes per cut. That is 30 per window per seed.
  - Each episode ends at success, at a native end, or after consumed tick 2699.
  - Classes:
    - ≤ 2 of 30 is blocked;
    - 3–27 of 30 is a foothold;
    - ≥ 28 of 30 (more than 90 %) is saturated.
  - Per seed: evaluate W0. While the last window was saturated, evaluate the next earlier window, up to W2 at most.
    That is 90 episodes per seed and 270 in total at most.
  - Seed status:
    - the class of its first non-saturated window;
    - or `saturated_through_max_window`, which passes: the pointer would pass those windows in one block each.
  - F4 passes when at least 2 of 3 seeds are not blocked. F4 never changes the schedule.
- **F5: diagnostic only.** It never gates, and it is not proof that reward v2 can or cannot consolidate the route.
  - Cuts 801, 810, 819, 828 and 837, with 10 stochastic episodes per cut per seed. That is 150 in total, never
    extended, each run to its natural end.
  - Compared: the mean policy-phase v2 return of episodes where the policy broke target 2 versus those where it did
    not, with the fall rates of both groups.
  - Classification: inconclusive if either pooled group has fewer than 10 episodes. Otherwise positive or negative
    only beyond ±2 Welch standard errors, and inconclusive in between.
  - Reward v2 is never changed.
- **Verification.** Exact tick-0 replays of up to 150 episodes:
  - every F5 target-2 episode;
  - every F4 success in each seed's last evaluated window;
  - the first episode of every cell.
- **Go / no-go.**
  - **GO** requires F1, F2, F3, the harness validation, F4 and the verification to pass.
  - **Stops:** a failed launch gate (5 readings, 60 s apart), available commit below 3 GiB, an integrity or
    provenance mismatch, or a leftover process. A stop keeps every episode written so far and relaunches nothing.

## 7. Proposed training comparison (after GO and a separate go-ahead)

- **Runs.** Six warm-started runs, E_j and K_j for j = 0, 1, 2.
- **Evaluation.** Tick-0 evaluation under the Phase K protocol:
  - final checkpoint: 100 deterministic + 100 stochastic episodes, seed 12345;
  - curve points at +512,000 and +1,024,000: 60 stochastic + 5 deterministic each.
- **Decision rule.** Proposed here; frozen in the campaign manifest before launch; applied once.
  - **Metric.** R_j is the number of the 100 final stochastic tick-0 episodes that break all seven right targets, the
    last at a consumed tick ≤ 2699.

  | Gate | Condition | Result |
  |---|---|---|
  | 0 | integrity, provenance, tick-0 evaluation, full census | otherwise no decision |
  | 1 | R_E ≥ 5 and R_E > R_K in at least 2 of 3 pairs, and pooled E static targets (all but ID 2) per episode not more than 0.5 below K | sweep consolidated from this anchor |
  | 2 | R_E ≥ 1 in at least 2 seeds and ΣR_E > ΣR_K | sweep reproduced, not consolidated |
  | 3 | pointer reached W8 or completed in at least 2 E runs | learned from anchored starts, not linked to tick 0 |
  | 4 | none of the above | null |

- **Reported, never gating:** L, sweeps at any tick, target-2 rate and timing, falls, deterministic collapse, clears,
  left entries and breaks, pointer and block logs, prefix costs.
- **Stops.** Any gate failure, hard alert, drift, provenance mismatch, process leak or resource stop halts the
  campaign, keeping partial runs. There is no early stop on results, no extension, no extra seeds and no re-decision.
- **Scope of the conclusion.** One anchor, so the result cannot show how often seeds discover a usable sweep.

## 8. Opt-in implementation (defaults unchanged)

- **New files:**
  - `rl/m7m_anchor.py`: pure registration, cut semantics, schedule, success test and plan;
  - `rl/m7m_worker.py`: `AnchorWorkerWrapper`, built on the M7h recorded prefix phase;
  - `rl/m7m_vec.py`: `AnchorVecEnv`, placed where M7h puts its curriculum wrapper;
  - `rl/m7m_feasibility.py`: the feasibility harness;
  - `rl/m7m_tests.py`: tests.
- **Changes to existing files, all active only when a profile has an `[anchor_curriculum]` table:**
  - `rl/experiment_config.py`: the optional, all-or-nothing table; its keys; the derived diagnostic flag; its
    cross-field rules (v1, v2, warm start only, never with `[curriculum]`).
  - `rl/m7_trainer.py`: the config field; the worker factory; the warm-start acceptance, recorded in the lineage; and
    attaching the vector wrapper after the warm-start VecNormalize load.
- **Defaults unchanged.** All 46 existing profiles resolve to byte-identical fingerprints, summaries, resolved configs,
  extra_env and trainer configurations before and after these changes.
