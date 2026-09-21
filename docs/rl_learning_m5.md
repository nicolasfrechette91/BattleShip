# RL M5: Track 1 learning environment, reward v1, first PPO training smoke

M5 is the first milestone with machine-learning infrastructure. It is a
learning-pipeline proof, not serious training: it shows that Stable-Baselines3
PPO can drive BattleShip through the frozen M2/M3 stack with a reduced
action space, a minimal Python-owned reward, bounded episodes, model
save/load/inference and M4 artifact capture from the first run onward.

```text
PPO (SB3)  ->  Track 1 btt_s9_b8_v1  ->  M3 btt_raw_b8_s161_v1  ->  M1d/M1c  ->  BattleShip
```

Nothing in M5 is expected to clear the stage, beat random play or approach
the 7.43 s scripted baseline. No number below is evidence of skill. M6
(training throughput, headless execution) and M7 (serious training) come
after; neither was started here.

## Files

| File | Role |
| --- | --- |
| `rl/btt_learning.py` | Track 1 action space and mapping, `btt_reward_v1`, policy observation adapter, `RewardV1Wrapper`, `Track1PolicyWrapper`, `TrainingTracker` (best-run semantics and preservation policy), `make_learning_env()` |
| `rl/train_m5.py` | bounded PPO training run: config, checkpoints, final model, reload + inference, `training_summary.json`; `--evaluate` mode |
| `rl/m5_smoke.py` | the eight M5 smoke cases (three without a game) |
| `rl/requirements.txt` | adds `stable-baselines3>=2.9,<3` (PyTorch, NumPy, cloudpickle come with it) |
| `.gitignore` | ignores `/runs/` (training outputs are never committed) |
| `docs/rl_learning_m5.md` | this document |
| `rl/run_artifacts.py`, `rl/m4_smoke.py`, `docs/rl_measurements_m4.md` | the position-delta default set to 300 by project decision after M5 (`DEFAULT_POSITION_DELTA_THRESHOLD`), the M4 smoke boundaries and messages updated to it, and one stale literal in the no-game `detector_synthetic` case corrected (expected delta -250 for a -300 move); the detector's logic is unchanged (Phase A findings below) |

No native C/C++ file, no decomp file, no `libultraship`/`torch` submodule,
no CMake file, and none of `rl/battleship_client.py`,
`rl/battleship_process.py`, `rl/battleship_env.py`, `rl/run_artifacts.py`,
`rl/tools/bench.py` or the M1e/M2/M3 smoke and regression scripts changed.
No native rebuild was needed; the executable is the M4 one.

## Phase A findings

- **SB3 cannot consume the M3 observation space as is.** M3 exposes the M1b
  snapshot as a `Dict` of zero-dimensional Boxes (uint32 / int32 / float32)
  plus two `Discrete(2)` flags. SB3's `MultiInputPolicy` feeds every Dict
  entry through `nn.Flatten()`, which needs a feature axis; on a 0-d entry
  it raises `IndexError: Dimension out of range` inside torch. Verified with
  a scripted stand-in environment (no game) before and inside the smoke
  (`policy_observation`). A Box of shape `(1,)` would pass, but two M3
  fields (`observation_schema`, `host_frame`) are diagnostics that must not
  become features, so an M5-only adapter was implemented instead of touching
  M3.
- **M4 reuse.** `EpisodeRecordingWrapper` already takes a `labels` callable
  (evaluated at every reset) and an `on_episode_end(recorder)` hook. M5
  supplies both from `TrainingTracker`; the artifact format, reader,
  detectors and retention rule are used unchanged. The frozen
  `PreservationReason` enum has no "first successful clear" member; M5
  encodes that event as `new_fastest_completed_run` (the first clear is the
  fastest so far) with an explanatory note and tags every M5 decision in
  `labels["preservation_events"]` (see below) rather than changing M4.
- **Dependency compatibility.** `stable-baselines3 2.9.0` declares
  `gymnasium>=0.29.1,<2.0`, `numpy>=1.20,<3.0`, `torch>=2.8,<3.0`, Python
  3.10 to 3.13. It kept the installed gymnasium 1.3.0 / numpy 2.5.3 and
  added torch 2.14.0 (CPU wheel) with its pure-Python dependencies.
- **Observed facts that shaped the design.** The committed M4 position-delta
  default was 250 units per tick, while the M5 brief and the M4 working
  notes said 300. Rerunning the M4 smoke after M5 showed the committed
  `detector_synthetic` case failing on its own (verified from
  `git show HEAD:rl/m4_smoke.py`): it asserted 250.0 as the default but
  its "below the default" probe used 299.9, i.e. it had been written for
  300; further down it moved a synthetic fighter from x -30 to -330 (delta
  -300) and expected the stored delta -250. The project decision after M5
  is 300: `DEFAULT_POSITION_DELTA_THRESHOLD` is now 300.0, the 299.9 probe
  is valid again, exact-300 and 300.5 boundary probes were added, and the
  -300 delta expectation was corrected. The detector's comparison (strictly
  above the threshold, both observations valid and BTT active) is
  unchanged. The M4 notes record
  that a fighter leaving the stage does not end the episode natively: the
  next step wedges until the 30 s request timeout raises `EpisodeFailure`.
  M5 therefore treats a mid-episode lifecycle failure as a truncated
  learning step (below) so PPO can continue with the next fresh process.
- **Smallest file scope.** Three new Python files, one document, the
  requirements line and one `.gitignore` line.

## Track 1 action contract: `btt_s9_b8_v1`

```text
action_space = MultiDiscrete([9, 8])     dimension 0 = stick state, dimension 1 = button state
```

| Stick index | Native `(stick_x, stick_y)` | Name |
| --- | --- | --- |
| 0 | (0, 0) | neutral |
| 1 | (80, 0) | right |
| 2 | (80, 80) | up-right |
| 3 | (0, 80) | up |
| 4 | (-80, 80) | up-left |
| 5 | (-80, 0) | left |
| 6 | (-80, -80) | down-left |
| 7 | (0, -80) | down |
| 8 | (80, -80) | down-right |

| Button index | Native word | Name | M3 button index |
| --- | --- | --- | --- |
| 0 | 0x0000 | none | 0 |
| 1 | 0x8000 | A | 1 |
| 2 | 0x4000 | B | 2 |
| 3 | 0x0008 | C-up | 6 |
| 4 | 0x0002 | C-left | 7 |
| 5 | 0x0020 | L | 4 |
| 6 | 0x0010 | R | 5 |
| 7 | 0x2000 | Z | 3 |

72 actions. C-up and C-left are the two C-button choices; this supersedes
the older draft Track 1 definition that used C-down. Start, the D-pad,
C-down, C-right and every button combination are absent, and no
intermediate analog value exists. The mapping is a table lookup
(`track1_to_m3()` returns the M3 action `{"button", "stick_x", "stick_y"}`;
`track1_to_native()` runs it through the unchanged M3 `action_to_native()`);
nothing is clamped, scaled or approximated, and an invalid action (index out
of range, wrong length, float, boolean, string) raises `ValueError` before
anything is sent. `native_to_track1()` is the inverse for artifacts and
tests; it raises for anything Track 1 cannot express.

The M3 raw domain (`btt_raw_b8_s161_v1`: `Discrete(8)` buttons, sticks
`Discrete(161, start=-80)`) and the native M1c/M1d contract are unchanged.

**The 7.43 s replay is not representable in Track 1.** All 468 rows lie in
the M3 domain (0 C-down, 0 C-right, sticks within +-80), but 8 rows carry
intermediate analog values outside the nine stick states. The replay is
never sent through Track 1 and never approximated; M1e, M2 and M3 remain
the exact baseline regressions, and the M5 reward sanity check feeds it
through the raw M3 path.

## Learning observation: `btt_policy_obs_v1`

PPO receives `Box(-inf, inf, shape=(15,), dtype=float32)`: the M1b fields
in declaration order, cast to float32, minus the two diagnostics.

| Included (15) | Excluded (2) | Why excluded |
| --- | --- | --- |
| `input_tick`, `time_passed`, `game_status`, `btt_active`, `targets_remaining`, `fighter_valid`, `position_x`, `position_y`, `air_velocity_x`, `air_velocity_y`, `ground_velocity_x`, `facing_direction`, `ground_air_state`, `fighter_status_id`, `jumps_used` | `observation_schema` | schema id, describes the capture format |
| | `host_frame` | host-side callback count; advances on parked host iterations, not a game quantity |

Notes on the fields the prompt asked to treat carefully:

- `fighter_status_id` is a categorical action-state id (for example 157 =
  `nFTCommonStatusEscapeB`, 226 = `nFTMarioStatusSpecialAirHi`). It is kept
  because it is gameplay state, fed raw as a scalar; the contract defines
  no ordering or count for it, so no one-hot or scaling was invented.
- `game_status` is `Go` (1) throughout an interactive episode (Start is not
  an action, so Pause never occurs); it is kept for completeness at no cost.
- `input_tick` and `time_passed` are both kept as the two native clocks;
  neither is derived from the other.
- uint32 counters are cast to float32 unchanged. They stay far below 2^24
  in any episode, so the cast is exact in practice.
- No normalisation: the native contract establishes no ranges. This is a
  first learnable representation, not a final observation design.

The full M3 Dict observation is still available in `info["m3_observation"]`
and the raw `Observation` in `info["native_observation"]`.

## Reward v1: `btt_reward_v1`

Python-owned, computed by `RewardV1Wrapper` directly on top of
`BattleShipBTTEnv` from the M3 transition only (no wall clock, no
positions, no target coordinates, no shaping):

```text
reward = newly_broken_targets * 1.0      (decrease of the live targets_remaining)
       - 0.001                           (per consumed native tick)
       + 10.0 if the step is the native EpisodeEnded result (successful clear)
```

Constants live in `RewardV1Config` (`target_broken`, `per_step`,
`clear_bonus`) and are stored in every artifact's labels and the run
config. Rules:

- targets are counted from the decrease in `targets_remaining` between
  consecutive observations, so two targets in one tick reward both;
- `targets_remaining` is read only while `btt_active == 1` (otherwise it is
  a deterministic zero by the M1b contract, never "all broken");
- an increase raises `RewardContractViolation`; it never becomes a negative
  reward. A native `EpisodeEnded` with targets left raises too;
- the bonus applies only to `terminated` (the authoritative native
  EpisodeEnded); truncation, failure and reset produce no bonus, and reset
  produces no reward at all;
- the reward is computed after the step from its result and touches
  nothing in the game.

Exact baseline check: 10 targets, 447 steps, clear =
`10 * 1.0 + 10.0 - 447 * 0.001 = 19.553`. Verified with the real replay
on the raw M3 path (below), tolerance 1e-9 on `math.fsum` of the per-step
rewards.

This is a first baseline reward, not a claim of optimality, and it was not
tuned on the smoke result.

## Bounded episodes and failure handling

M3's Python-owned `max_episode_steps` (native ticks) is reused unchanged;
no native timeout or reset exists. On the bound the step returns
`terminated=False, truncated=True` and M3 disposes of the process at once.

`DEFAULT_MAX_EPISODE_STEPS = 1800` for training (configurable with
`--max-episode-steps`): about four times the 447-tick scripted clear,
chosen for exploration rather than around the TAS. Game-time equivalent:
the tracked baseline pairs `time_passed` 446 with the 7.43 s display time,
i.e. 60 tics per second, so 1800 ticks are about 30 s of game time. This is
game time, never wall clock (at the current ~30 ticks/s a full-length
episode takes about a minute of wall time; M6 addresses that).

A lifecycle failure raised by M3 during a step (process exit, transport
loss, or the request timeout after the fighter has left the stage) arrives
after M3 has disposed of the process and after the M4 recorder has finished
the episode as `failed`. `Track1PolicyWrapper` reports it as a truncated
step: the last observation, reward 0.0 (no tick was consumed),
`terminated=False`, `truncated=True`, `info["truncation_reason"] ==
"episode_failure"`, `info["failure_outcome"]` (the M2 category). The next
`reset()` launches a fresh process. A failure at `reset()` still raises.
This is never reported as a native completion.

## PPO integration

| | |
| --- | --- |
| framework | Stable-Baselines3 2.9.0 on torch 2.14.0 (CPU); the only ML framework added |
| algorithm / policy | `PPO`, `MlpPolicy` (flat Box observation; `MultiInputPolicy` would be for a Dict) |
| vectorisation | `DummyVecEnv` over one `Monitor(Track1PolicyWrapper(...))`; no `SubprocVecEnv`, one BattleShip process at a time |
| seed | `--seed`: Python / NumPy / PyTorch only; it never reaches the game |
| defaults | 1024 timesteps, `n_steps` 256, `batch_size` 64, `n_epochs` 4, lr 3e-4, gamma 0.99, checkpoint every 512 timesteps, periodic artifact every 10 finished episodes, eval 30 steps |
| interrupt | Ctrl+C saves `interrupted_model.zip`, preserves the running episode for `manual`, closes the environment (process disposed) |

`rl/train_m5.py` builds the stack (`make_learning_env`), trains with
`M5TrainingCallback` (keeps the tracker's SB3 timestep and checkpoint label
current, saves checkpoints), saves `final_model.zip`, then reloads it with
`PPO.load` and runs `--eval-steps` deterministic actions on a fresh
environment (bounded to exactly that many ticks, preserved for `manual`).
Optimizer activity is proven, not assumed: the policy parameters are
snapshotted before `learn()` and compared afterwards, and SB3's own
`_n_updates` counter (n_epochs per rollout) is reported.

```text
python rl/train_m5.py                                             # bounded default run
python rl/train_m5.py --total-timesteps 512 --max-episode-steps 128 --periodic-episodes 2 --run-id demo
python rl/train_m5.py --evaluate runs/demo/final_model.zip --eval-steps 60
```

Output layout:

```text
runs/<run_id>/
    config.json               effective configuration, versions, contracts (portable: repo-relative paths only)
    checkpoints/              ppo_<sb3 timesteps>_steps.zip
    artifacts/<episode_id>/   preserved M4 artifacts: metadata.json + actions.jsonl
    episodes/                 M2 per-episode game files (save, result JSON, process log)
    final_model.zip
    interrupted_model.zip     only after Ctrl+C
    training_summary.json     counts, updates, wall time, artifacts, inference result
```

`runs/` is git-ignored. Model binaries are never stored inside artifacts;
artifacts reference the checkpoint label instead.

## M4 artifact integration and preservation policy

Wrapper order (inner to outer): `BattleShipBTTEnv` -> `RewardV1Wrapper` ->
`EpisodeRecordingWrapper` -> `Track1PolicyWrapper`. The recorder sees M3
actions and records the native triple the environment submitted
(`buttons`, `stick_x`, `stick_y`, `consumed_tick`), never a Track 1 index;
the reward wrapper sits below it so the episode's return and target count
are final when the recorder's `on_episode_end` hook runs. Track 1 indices
are not stored; they are recoverable exactly with `native_to_track1()`.

`TrainingTracker.on_episode_end(recorder)` decides preservation for every
finished episode (terminal, truncated or failed):

| M5 event (`labels["preservation_events"]`) | M4 reason written | When |
| --- | --- | --- |
| `periodic_milestone` | `periodic_milestone` | every N finished episodes (`--periodic-episodes`) and/or every N native steps (`--periodic-timesteps`) |
| `new_best_target_count` | `new_best_target_count` | `targets_broken` strictly above the best so far (initial best 0) |
| `first_successful_clear` | `new_fastest_completed_run` (note "first successful clear") | the first native clear of the run |
| `new_fastest_completed_run` | `new_fastest_completed_run` | a clear with a smaller `completion_time_passed` than the best clear |
| `anomaly` | `anomaly` (written by M4 itself) | a detector event; M5 only tags it |
| `manual` | `manual` | `TrainingTracker.request_manual_preservation(note)`; used for evaluation episodes and Ctrl+C |

Ordinary episodes are discarded (the M4 default). Anomaly detection stays
M4's, non-invasive and unchanged (default `PositionDeltaDetector(300)`,
configurable with `--position-delta-threshold`).

Best-run semantics use objective game metrics only: maximum
`targets_broken`, and for clears the minimum `completion_time_passed`.
`completion_input_tick` is stored beside it and never compared or derived;
`host_frame` and wall-clock time are never used as performance.

Labels written into every recorded episode (at reset, completed at the
end): `milestone`, `role` (training / evaluation), `run_id`,
`episode_number`, `native_steps_at_start/_end`,
`sb3_num_timesteps_at_start/_end`, `checkpoint_label` (stem of the most
recent saved checkpoint, `initial` before the first), `track1_contract`,
`reward_contract`, `reward_config`, `policy_observation_contract`,
`episode_status`, `episode_steps`, `episode_return`, `targets_broken`,
`terminated`, `truncated`, `completion_time_passed`,
`completion_input_tick`, `preservation_events`, and the best metrics before
and after the episode. No video, no screenshots, no RNG metadata.

## Tested versions (2026-09-21)

Windows 11 (10.0.26200), Python 3.13.2 (CPython, the user's global
interpreter, as for M3), gymnasium 1.3.0, numpy 2.5.3, torch 2.14.0+cpu,
stable-baselines3 2.9.0, cloudpickle 3.1.2. US Release
`build-us/Release/BattleShip.exe` from M4 (no rebuild). Installed with
`python -m pip install -r rl/requirements.txt`.

## Smoke validation (`rl/m5_smoke.py`)

```text
python rl/m5_smoke.py                                          # all eight cases
python rl/m5_smoke.py track1_mapping reward_synthetic policy_observation   # no game needed
```

Full run of 2026-09-21: 8/8 PASS, `BattleShip.exe` count 0 before, 0 after,
no owned process alive after any case.

| Case | Observed |
| --- | --- |
| `track1_mapping` | `MultiDiscrete([9, 8])`; all 72 actions map to the expected M3 action and native triple in four input forms (tuple, list, int64 and int32 arrays) and back through `native_to_track1`; C-down, C-right, Start, D-pad, multi-button words and 7 intermediate stick values unrepresentable; 20000 `sample()` draws all legal, all mapping to legal M3 actions, covering all 72 actions; 18 malformed actions rejected with `ValueError`; M3 contract and spaces unchanged |
| `reward_synthetic` | no target -0.001, one 0.999, two 1.999, three 2.999, clear on the last target 10.999, clear with two at once 11.999, truncation -0.001, non-live counts 0 targets; 9 -> 10, 0 -> 1 and a clear with a target left raise `RewardContractViolation`; custom constants applied; closed form 19.553; `RewardV1Wrapper` over a scripted stand-in: per-step rewards exact, 19.994 for 10 targets in 6 steps with a clear, -0.002 for a 2-step truncation, reset gives no reward |
| `policy_observation` | 15 float32 features in M1b order, `observation_schema` / `host_frame` absent, values cast exactly; SB3 `MultiInputPolicy` on the raw M3 Dict space fails with the `IndexError` above; `MlpPolicy` on the adapter space trains 32 steps and predicts a legal Track 1 action (no game) |
| `baseline_reward` | the 7.43 s replay on the raw M3 path with reward v1: 447 steps, last `consumed_tick` 446, `completion_time_passed` 446, `completion_input_tick` 447, targets 0, result JSON equal to the frozen values, return **19.553** (`fsum`; wrapper 19.553000); target-breaking steps at consumed ticks 51, 87, 142, 163, 275, 316, 358, 368, 432, 446; 8 of 468 rows outside Track 1 |
| `learning_reset_step` | `reset()` -> `step_count` 0, `input_tick` 0, `consumed_tick` None, policy vector starts `[0, 0, 1, 1, 10, 1, ...]`; Track 1 (1,0) -> `consumed_tick` 0, `input_tick` 1, `step_count` 1, reward -0.001, native (0, 80, 0) recorded; (3,3) -> tick 1 with C-up; ten (5,0) ticks walking left (x deltas 0, 0, then -29.8 per tick); bound 12 -> `truncated`, process terminated; the 1-unit detector preserved the episode for `anomaly` (8 events) with the M5 labels (episode 1, 12 steps, return -0.012, 0 targets, status truncated, `completion_time_passed` None); rows invert to the Track 1 actions sent; second reset is a new pid at `step_count` 0 consuming tick 0 again |
| `failure_truncation` | `SSB64_MAX_FRAMES=600`: 267 neutral steps, then the step after the clean exit returned `truncated=True`, `terminated=False`, `truncation_reason` `episode_failure` (`premature_exit`) after 9.4 s; recorder status `failed`, not preserved; the tracker counted one failure; the next reset gave a fresh process consuming tick 0 |
| `ppo_smoke` | see below |
| `save_load_inference` | `final_model.zip` loaded (action space `MultiDiscrete([9, 8])`, observation shape (15,)) -> fresh environment -> reset -> 10 x predict + step: consumed ticks 0..9, every predicted action inside the space and mapping to a legal M3 action |

### The PPO training smoke

Configuration of the smoke (deliberately small; the game runs at about 30
native ticks/s in the visible window, which M6 addresses): 512 timesteps,
`max_episode_steps` 128, `n_steps` 128, `batch_size` 32, `n_epochs` 2,
checkpoint every 256, periodic artifact every 2 finished episodes, eval 20
steps, seed 0, CPU.

| | |
| --- | --- |
| SB3 timesteps / native steps | 512 / 512 |
| episodes | 5 started, 4 finished (all truncated at 128), 1 aborted at close (the auto-reset after the fourth) |
| rollouts / SB3 `n_updates` / gradient steps | 4 / 8 / 32 |
| policy parameters changed | true |
| training wall time | 33.6 s (case wall 37.8 s including reload + inference) |
| checkpoints | `ppo_00000256_steps.zip`, `ppo_00000512_steps.zip`; `final_model.zip` |
| reload + inference | 20 deterministic steps on a fresh process, consumed ticks 0..19, all rewards finite, return -0.020, truncated at the bound; evaluation episode preserved for `manual` |
| artifacts | 3 training episodes preserved, 2 discarded: episode 1 `new_best_target_count` (1 target broken by the initial random policy, return 0.872), episode 2 `periodic_milestone`, episode 4 `periodic_milestone`; plus the evaluation artifact (`manual`) |
| example labels (episode 1) | `sb3_num_timesteps_at_end` 127, `checkpoint_label` `initial`, `episode_return` 0.872, `targets_broken` 1, `episode_status` truncated, `preservation_events` `["new_best_target_count"]` |
| canonical actions | every artifact row holds `buttons`, `stick_x`, `stick_y`, `consumed_tick` (0..127); every row inverts to a Track 1 action; `source_action_contract` `btt_raw_b8_s161_v1`; all artifacts parsed by `read_artifact` |
| leaks | `BattleShip.exe` 0 before and after |

The one target broken in episode 1 is the initial policy stumbling into a
target; it says nothing about learning. Running the smoke three times with
seed 0 reproduced the same trajectories, counts and returns.

Anomaly note: while the default threshold was still 250 (during M5
development), the same seed-0 run additionally preserved episodes 2 and 3
for `anomaly`: a one-tick horizontal displacement of 280.56 units at floor
level (position y -2550, x about -915 -> -635 in episode 2 and -900 -> -1181
in episode 3), grounded on both sides, `fighter_status_id` 157
(`nFTCommonStatusEscapeB`, a backward roll) unchanged. At the 300 default
this move is below the threshold and those episodes are discarded as
ordinary; the observation is kept here as measured, not judged, and
`--position-delta-threshold 250` records it again.

## Regressions after M5

Run with `SSB64_RL_TIMING` unset, no native rebuild (nothing native
changed):

| Regression | Result |
| --- | --- |
| `python rl/m5_smoke.py` | 8/8 PASS at the 300 default (above), `BattleShip.exe` 0 before / 0 after |
| `python rl/m4_smoke.py` | 5/5 PASS at the 300 default (at HEAD `detector_synthetic` fails before any M5 code is involved, see Phase A); `detector_synthetic` 150 / 299.9 / exactly 300 / Up-B 215.525 no event, 300.5 / 350 / -400 / both axes event; `wrapper_discard` 60 random steps, no event at 300, nothing written; `baseline_roundtrip` captured, env-replayed and raw-replayed 447 actions, last `consumed_tick` 446, completion 446 / 447, `step_count` 447, targets 0, exit 0, 21 rows unsent, no event at 300; `anomaly_live` 37 events at threshold 1, 40 rows preserved; 0 processes before / after |
| `python rl/m3_gym_smoke.py` | 9/9 PASS; `replay_complete` 447 actions, `consumed_tick` 446, completion 446 / 447, `step_count` 447, exit 0, result JSON 10 / 446 / 447; 0 processes after |
| `python rl/m2_restart_regression.py` | M2 PASS, 3/3 fresh processes (step_count 0 after about 3.1 s each), each 447 actions, `consumed_tick` 446, `input_tick` 447, `time_passed` 446, targets 0, exit 0, result JSON 10 / 446 / 447, cleanup `already_exited` |
| `python rl/m2_lifecycle_smoke.py` | 6/6 PASS |
| `python rl/m1e_replay_regression.py --port 5599` against a hand-launched process (no `SSB64_RL_EXIT_ON_END`), terminated afterwards | M1e PASS: 468 source rows, 447 steps, last `consumed_tick` 446, `completion_input_tick` 447, `completion_time_passed` 446, targets 0, `EpisodeEnded`, 21 rows after completion, 14.9 s wall |

`completion_time_passed = 446` and `completion_input_tick = 447` are
unchanged everywhere; they remain two clocks and nothing derives one from
the other. `git diff --check` clean. No `BattleShip.exe` remained after any
run.

## Not in M5

No headless mode, drop-DL or present-pacing work, binary IPC, shared
memory, `SubprocVecEnv`, multiprocessing or parallel environments, serious
or long training, hyperparameter tuning, curriculum, distance-to-target or
any other shaping beyond `btt_reward_v1`, map or path planning, fixed
camera, replay visualisation, video recording, raw-input optimiser, TAS
polishing, native save states, in-process reset, and no RNG inspection,
logging, control, hashing or comparison of any kind. M6 and M7 were not
started.
