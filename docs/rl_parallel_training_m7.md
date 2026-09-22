# RL M7a: parallel PPO training, process-count selection, first learning pilot

M7a turns the single-environment M5 learning pipeline into parallel
Stable-Baselines3 PPO training on the M6 no-render stack, selects the process
count from measured learner-in-the-loop throughput, and runs one bounded
from-scratch pilot with a fixed evaluation protocol.

```text
PPO (MlpPolicy, CPU, 1 torch thread)
  -> VecNormalize (observations only; rewards untouched)
  -> M7SubprocVecEnv (spawn workers, one BattleShip process per worker at a time)
       worker: Track 1 -> M4 recorder -> btt_reward_v1 -> M3/M2 (+ M7 lifecycle policy) -> BattleShip
```

Frozen and unchanged: one action per native tick (M1c), process restart as
reset, no in-process reset, no save states, Track 1 `btt_s9_b8_v1`,
`btt_reward_v1` (constants and function), `btt_policy_obs_v1`, the M3
environment, the M4 artifact format (canonical native triples + consumed
tick), the 300-unit anomaly threshold, the authoritative replay values. No
native, decomp, libultraship or torch change; no M1-M6 file changed. No native
RNG inspection, logging, validation, control, comparison or hashing exists;
seeds are Python / NumPy / PyTorch / SB3 only.

The pilot is a bounded baseline. It is not expected to clear the stage, and
no learning claim is made beyond what the fixed evaluation protocol supports
(see "Pilot").

## Files

| File | Role |
| --- | --- |
| `rl/m7_runtime.py` | host utilities (stdlib): isolated worker runtime directories, rank port blocks, kill-on-close job object, process liveness/listing, system CPU, fingerprints, git revisions, Windows path budget, retrying atomic replace |
| `rl/btt_parallel.py` | worker side (no torch/SB3): `M7BattleShipBTTEnv` (startup retry, native-failure termination, timing), `M7RewardWrapper`, `RunCoordinator` (file-locked global preservation), `M7EpisodeTracker`, `EpisodeStatsWrapper`, `M7WorkerWrapper`, `WorkerSpec` / `WorkerFactory`, the `m7_worker` loop |
| `rl/m7_vec_env.py` | `M7SubprocVecEnv`: SB3 `SubprocVecEnv` semantics with bounded receives, worker-failure propagation, bounded close, stall accounting |
| `rl/m7_trainer.py` | `M7PPO` (timed `train()`), `M7Config`, run layout, checkpoint sets, callback, resume, comparison runner and selection rule |
| `rl/m7_evaluation.py` | checkpoint-set verification, frozen-statistics evaluation (deterministic / stochastic / random), objective ranking, bootstrap statistics, learning-evidence rule |
| `rl/m7_report.py` | pilot report builder (reads run directories only) |
| `rl/train_m7.py` | CLI: `train`, `compare`, `pilot`, `resume` (stdlib at module level: spawn workers re-import it) |
| `rl/eval_m7.py` | CLI: `checkpoint`, `random`, `report` |
| `rl/m7_smoke.py` | 20 unit and game-backed regression cases |
| `docs/rl_parallel_training_m7.md` | this document |
| `docs/rl_parallel_training_m7_comparison.json` | machine-readable N=4/N=5 comparison |
| `docs/rl_parallel_training_m7_pilot.json` | machine-readable pilot report |

`requirements.txt` is unchanged (no new dependency). Training outputs stay
under the git-ignored `runs/`.

## Phase A discoveries

- **No native failure result, and falls hang the step.** Break the Targets in
  bonus practice has no time limit (`time_limit = SCBATTLE_TIMELIMIT_INFINITE`,
  timer display capped at 59:59.59) and `rl_result.cpp` only ever writes
  `outcome: "clear"`. A fall runs `ftcommondead.c` -> `ifCommonAnnounceEndMessage`
  -> `ifCommonBattleSetInterface` (game_status `End` = 5); measured sequence:
  1 update at status 5, 90 at 6, 5 at 7, then the scene unloads and the next
  M1c step never completes (M2 `episode_timeout` after the request timeout).
  Under a synchronous `SubprocVecEnv` that hang stalls every worker.
- **Random play is not weak.** Uniform-random Track 1, 8 episodes of 3600
  ticks: 6 hit the bound with 3-5 targets, 2 fell (ticks 3419 and 1238).
- **SB3 2.9.0 `SubprocVecEnv` on Windows** uses `spawn`; a worker exception
  kills the worker without `env.close()` (orphaning its BattleShip), and
  `step_wait` is synchronous (one restart, about 2.4 s, stalls all workers).
- **Shared configuration race.** libultraship `Config::Save()` truncates and
  rewrites `BattleShip.cfg.json` in place and `Reload()` falls back to an
  empty config on a parse error; the portable app directory is `"."`. Workers
  sharing `build-us/Release` as cwd could clobber the user's settings.
- **Port race.** M2 asks the OS for an ephemeral port and releases it before
  the game binds; client sockets draw from the same range, which is the
  likely cause of M6's single N=6 startup `transport_failure`.
- A nested Windows kill-on-close job object works from this shell.

## Vector architecture

- `M7SubprocVecEnv` (parent) starts one `spawn` process per rank running
  `btt_parallel.m7_worker` with a top-level picklable `WorkerFactory(WorkerSpec)`
  (plain pickle; `unit_factory_pickle` proves a spawn child rebuilds the spec
  without importing torch or SB3). The protocol is SB3's: `step` with
  auto-reset, `terminal_observation`, `TimeLimit.truncated`, `reset` with the
  per-env seed, `env_method`, `get/set/has_attr`, `is_wrapped`, `close`.
- Each worker owns at most one BattleShip process; a reset disposes of the old
  process before launching the next one (M3).
- CLIs import torch/SB3 only inside `main()`, so spawn children (which
  re-import `__mp_main__`) stay light: worker working set about 45 MiB.
- Worker stack (inner to outer): `M7BattleShipBTTEnv`, `M7RewardWrapper`,
  `EpisodeRecordingWrapper` (M4, unchanged), `Track1PolicyWrapper` (M5,
  unchanged), `EpisodeStatsWrapper` (SB3-Monitor-compatible `info["episode"]`
  without importing SB3), `M7WorkerWrapper` (slim picklable info, error
  context, control methods).
- Seeds: SB3/PPO seed = base seed; vector reset seeds `base + rank`; worker
  Python/NumPy seeds `base + rank`. `torch.set_num_threads(1)` in the parent;
  workers never import torch.

## Fall semantics: `btt_native_failure_v1`

The first post-update M1c step result with `game_status == 5`,
`btt_active == 1`, `targets_remaining > 0` and no native `EpisodeEnded`
ends the episode:

- Gymnasium `terminated = True`, `truncated = False`,
  `info["termination_reason"] = "native_failure"`;
- the process is disposed of at once; no further step is sent, the
  failure-screen ticks are never advanced, the stage unload is never waited for;
- reward: the unchanged `btt_reward_v1` of that tick (`-0.001`, plus 1.0 per
  target newly broken on the same tick); no clear bonus, no failure penalty.
  `M7RewardWrapper` calls the unchanged `reward_v1()` with the native clear
  as its terminal flag, so a fall can never receive the bonus;
- a clear stays `termination_reason = "native_clear"`: it carries
  `EpisodeEnded` with `targets_remaining == 0`. Measured: the replay's clear
  observation also has `game_status == 5`, and it is classified `native_clear`
  (return exactly 19.553);
- the horizon (3600 native ticks) and lifecycle failures stay truncations
  (`max_episode_steps`, `episode_failure`).

M4 artifacts record a fall as status `terminal` with
`terminal.end_reason = "fall"`, `terminal.termination_reason = "native_failure"`,
`terminal.cleared = false` (M7 artifacts widen `terminal` from "native clear"
to "the game ended the attempt"; `end_reason` / `termination_reason` always
disambiguate, and M5-era artifacts are unaffected).

Proof (`fall_regression`, both without and through VecNormalize): the scripted
fall (hold right, C-up every 40 ticks) terminates at consumed tick 431 with
`native_failure`, `TimeLimit.truncated = False`, status `terminal`; the fall
step took 0.07-0.10 s (no request timeout); the old process was dead when the
step returned; `terminal_observation` equals `policy_observation(post-update
failure observation)` exactly (and `normalize_obs` of it with VecNormalize);
return exactly `-0.432`; the artifact holds 432 canonical rows with
`termination_reason native_failure`. `request_timeout_cleanup` shows the old
path with detection disabled: 527 steps through the failure screen, then a
3.08 s request timeout, `episode_failure` / `episode_timeout` truncation,
process killed, worker recovers.

## Isolated worker directories

Resolution, proven from source and by the `isolation_boot_replay` regression:

| File | Resolved by | Worker directory |
| --- | --- | --- |
| `BattleShip.cfg.json` | libultraship `GetPathRelativeToAppDirectory` -> `"./"` (portable Windows) | private byte copy; read and written only there |
| `imgui.ini`, `logs/`, `default.sav`, `cvars.cfg`, `shaders/`, `hires_*` | app directory = cwd | private (copy of `imgui.ini`; the rest created privately or absent) |
| `f3d.o2r`, `BattleShip.o2r` | `LocateExistingFile`: cwd, then executable directory | not linked: resolved from `build-us/Release` |
| `gamecontrollerdb.txt` | libultraship `LocateFileAcrossAppDirs`: cwd, then bundle | not linked: resolved from `build-us/Release` |
| `assets/` | `LocateExistingFile` | not linked |
| `.tcc/` | cwd only (scripting include paths) | directory junction to `build-us/Release/.tcc` |
| save file | `SSB64_SAVE_PATH` (M2, per episode) | `episodes/episode_*/ssb64_save.bin` |
| result file | `SSB64_RL_RESULT_PATH` (M2, per episode) | `episodes/episode_*/result.json` |
| `ssb64.log` | `SDL_GetPrefPath` (`%APPDATA%\BattleShip`) | shared diagnostic log (see limitations) |

`BattleShip.o2r` is deliberately not hard-linked: asset extraction writes the
cwd path, and a hard link would carry a write into the user's archive.
Extraction needs a ROM in the `FindBaseRom` set (cwd, executable directory,
its parent); `prepare_worker_runtime` refuses to run if one is reachable (the
ROM at the repository root is not in that set).

Evidence: a marker added to the worker's config copy survived the game's own
save (file rewritten, marker kept); `ssb64.log` shows
`bootstrap archive (shaders) -> ...\build-us\Release\f3d.o2r` and
`adding game archive -> ...\build-us\Release\BattleShip.o2r`; the replay in
the isolated directory is identical to a default-cwd run on all 447 steps and
the initial observation (host_frame 511 in both); the native replay in the
isolated directory reports `actual_checksum=0x93E9EFB4`, `frames=468`,
`COMPLETE input_tick=447 time_passed=446`, result JSON clear 10 / 446 / 447;
the user's `BattleShip.cfg.json` kept its sha256 and its mtime through the
isolated run. Every M7 training run records the user config's fingerprint
before and after (`user_config` in `training_summary.json`).

## Ports and startup retry

Each rank owns the block `30000 + 250 * rank .. +249` (validated below the
dynamic range 49152-65535 read from `netsh`, and disjoint). Every startup
attempt takes a NEW candidate from the block (random start offset per worker,
sequential after that), checks it with M2's exclusive-bind probe (busy ports
are skipped and reported: another application, a process still shutting down,
TIME_WAIT, OS exclusions), and launches through M2 with that fixed port. A
failed attempt is classified by M2, the process is killed and reaped by M3's
disposal, and the next attempt uses the next candidate; at most 3 attempts,
every attempt recorded (port, outcome, pid, liveness after, elapsed).
`startup_failure_retry` proves both failure shapes: a port taken after launch
(the game's bind fails; `transport_failure` after 6.4 s with a 3 s request
timeout and a 3 s exit wait; pid dead; retry on the next port) and a port
taken before launch (M2 refuses, no process); exhausted attempts surface as
`M7StartupError` with rank context. Startup timeouts for training: startup 20
s, readiness 60 s, request 10 s (fall detection removes the only known long
native wait).

## Cleanup and the job object

- The trainer (and the smoke/eval CLIs) put themselves into a kill-on-close
  job object; workers and games inherit it, so everything dies with the
  trainer even after `TerminateProcess` (`job_object_kill`: 2 workers + 2
  games gone after the hard kill of their parent).
- Each worker ignores Ctrl+C (the parent coordinates), reports any command
  exception as a `WorkerFailure` (rank, command, traceback, worker episode,
  step, game pid) after closing its environment, and closes the environment
  in `finally` on every exit path.
- The parent's receives are bounded; a failure raises `M7WorkerFailure`
  instead of freezing (`worker_exception_cleanup`: injected fault in rank 1 at
  worker episode 1 step 50, surfaced with that context, all processes gone).
- Interrupts (`KeyboardInterrupt`, also inside `step_wait` with replies
  pending): replies are drained, the running episodes are preserved for
  `manual`, `interrupted/` is saved (model + statistics), workers are closed
  (`interrupt_cleanup`).
- `close()` drains pending replies, asks each live worker to close (it
  disposes its game and returns a final report), joins with a timeout,
  terminates stragglers and kills any game a dead worker left behind (pid +
  image-name check). After every run the trainer waits for zero
  `BattleShip.exe` and lists the job's remaining processes.

## VecNormalize

`VecNormalize(norm_obs=True, norm_reward=False, clip_obs=10.0)`; no reward
clipping or transformation (`clip_reward` only applies with `norm_reward`).
The environment keeps emitting the unchanged `btt_policy_obs_v1` vector; the
native observation schema is unchanged. Path: raw native M1b observation ->
15 float32 features -> running mean/variance normalisation -> policy input.
Every checkpoint set stores `vecnormalize.pkl` beside `model.zip` with both
hashes in `checkpoint.json`; loading refuses a missing, altered or
mismatched statistics file. Evaluation loads it with `training = False`,
`norm_reward = False` and checks the policy parameters and `obs_rms` hashes
before/after (`checkpoint_reload`: 30 deterministic legal Track 1 actions
after reload, statistics and parameters unchanged, missing/tampered files
refused).

## PPO configuration

| | |
| --- | --- |
| algorithm / policy | SB3 2.9.0 PPO, `MlpPolicy` (net_arch pi/vf 64x64, tanh, orthogonal init), CPU |
| rollout | 5120 transitions: N=4 `n_steps` 1280, N=5 `n_steps` 1024 |
| batch / epochs | 512 / 10 (10 minibatches per epoch) |
| gamma / GAE lambda | 0.999 / 0.995 |
| other | SB3 defaults, recorded as resolved: lr 3e-4, clip 0.2, clip_range_vf None, normalize_advantage True, ent_coef 0.0, vf_coef 0.5, max_grad_norm 0.5, no SDE, no target_kl, Adam eps 1e-5 |
| horizon | 3600 native ticks (60 s of game time), Python-owned truncation |

Rationale: at one decision per 60 Hz tick, targets are hundreds of ticks
apart. gamma 0.99 discounts a reward 300 ticks away to about 5 %, gamma 0.999
to about 74 %. With lambda 0.95 the GAE credit still decays by 0.95 per tick
(about 2e-7 after 300 ticks), so lambda is 0.995 (about 0.22 after 300
ticks, combined with gamma about 0.16). Nothing was tuned during the
comparison or the pilot.

## Checkpoints, resume and run layout

```text
runs/<run_id>/
    run.json                 config, resolved PPO values, contracts, seeds, flags, executable hash, git + submodule revisions, lineage, port blocks, job object, worker runtime manifests
    checkpoints/ckpt_<t>/    model.zip, vecnormalize.pkl, checkpoint.json, preservation_state.json
    final/  interrupted/     same set
    coordination/            state.json, state.lock, preservation_ledger.jsonl
    workers/wNN/             runtime/ (private cwd), episodes/ (M2 dirs), artifacts/, dispositions.jsonl
    evaluations/<label>/     deterministic/ and stochastic/ sets with their own workers and evaluation.json
    metrics/                 rollouts.jsonl, episodes.jsonl
    training_summary.json
```

Checkpoints are taken at rollout boundaries: `ckpt_<t>` holds the policy
after `t / 5120` updates, `ckpt_000000000` the untrained policy; `final/` is
saved after `learn()`. `checkpoint.json` records timesteps, `n_updates`,
contracts (Track 1 tables, reward constants, observation fields, failure rule,
horizon), process count, every resolved PPO value, base/worker/reset seeds,
executable sha256, parent HEAD + dirty files + submodule commits, M6 flags,
VecNormalize settings, versions, run id, lineage and file hashes. Nothing is
ever overwritten (run directories, checkpoint sets).

Resume (`train_m7.py resume --from <set>`) verifies the set, rejects
incompatible contracts (including the horizon), missing statistics or
different PPO settings / process count before creating anything, creates a new
run directory with lineage, continues the timestep count
(`reset_num_timesteps=False`) and the preservation state. `resume_short`:
5120 -> 10240 in a new run, lineage recorded, all source-run files
byte-identical afterwards, a horizon change rejected without creating a run.

## Artifacts and preservation

Every worker records canonical native actions (`buttons`, `stick_x`,
`stick_y`, `consumed_tick`) with the unchanged M4 recorder into its own
`workers/wNN/artifacts/<episode_id>/`. Global decisions (periodic milestone
every 10 finished episodes, new best target count, first successful clear,
new fastest clear) are made by `RunCoordinator` under a file lock and appended
to `preservation_ledger.jsonl`; ties are never a new best, so two workers
finishing together cannot both claim it (`unit_coordinator`: 6 processes x
60 decisions, counts exact, best values strictly increasing, one first clear).
Anomaly (M4 detector at 300) and manual reasons are worker-local. Unpreserved
ordinary episodes are never written; their M2 directories are deleted once the
process is gone; lifecycle-failure directories are kept up to 20 per worker;
preserved artifacts are never deleted; every decision is logged in
`dispositions.jsonl`. Evaluation deterministic episodes are preserved for
`manual`; stochastic/random sets preserve their own new-best / clears /
anomalies.

## Evaluation protocol

`m7_evaluation.evaluate_checkpoint`: fresh processes through the same worker
stack, 3600-tick horizon, both M6 flags, frozen statistics, no model update.
Modes: `deterministic` (2 episodes: the game and the argmax policy are
deterministic, so both must be identical, which is checked with the digest of
the submitted native actions), `stochastic` (20 episodes, fixed Torch seed
12345), `random` (uniform Track 1 from `numpy.random.default_rng(12345)`, 100
episodes). The first K completed episodes (by vector step, then rank) count;
episodes still running at the quota are aborted and never counted. Every
episode reports targets broken, raw return (diagnostic), length,
terminated/truncated, termination reason, clear, `completion_time_passed`,
`completion_input_tick`, artifact path when preserved.

Objective ranking: a verified clear ranks above any incomplete episode;
incomplete episodes rank by targets broken; clears by lower
`completion_time_passed`. Reward never overrides it (`unit_ranking`).
Learning is claimed only if the stochastic mean targets of the policy exceed
both the initial policy and the random baseline with the 95 % bootstrap CI of
each difference above zero.

## Validation (before the pilot)

`python rl/m7_smoke.py`: **20/20 PASS** (`runs/_m7_smoke_final1`), zero
`BattleShip.exe` after every case, user config sha256 unchanged.

| Case | Evidence |
| --- | --- |
| `unit_factory_pickle` | spec survives pickle and a spawn child; child imports neither torch nor SB3 |
| `unit_ports` | 8 disjoint blocks below 49152; fresh candidate per claim; squatted candidates skipped; exhausted block raises |
| `unit_metadata` | checkpoint.json holds every required field and resolved PPO value; overwrite refused; missing/tampered statistics or model, horizon mismatch refused; invalid configs rejected |
| `unit_ranking` | objective order, stable ties, reward ignored, evidence rule |
| `unit_fall_rule` | rule true only for status 5 + targets left + no EpisodeEnded |
| `unit_reward_fall` | fall -0.001 (0.999 with a same-tick target), clear 10.999, truncation -0.001, clear with targets left raises |
| `unit_coordinator` | 360 concurrent decisions from 6 processes exact |
| `unit_vec_protocol` | auto-reset/terminal_observation/TimeLimit semantics, failure with rank + context, interrupt close |
| `isolation_boot_replay` | see "Isolated worker directories" |
| `fall_regression` / `request_timeout_cleanup` | see "Fall semantics" |
| `startup_failure_retry` | see "Ports and startup retry" |
| `vector_smoke_n2/n4/n5` | 10240 transitions, 20 updates, auto-resets, canonical artifacts, clean close, user config untouched |
| `checkpoint_reload` / `resume_short` | see VecNormalize / resume |
| `worker_exception_cleanup` / `interrupt_cleanup` / `job_object_kill` | see "Cleanup" |

Existing regressions, sequential, zero processes after each, user config
sha256 `1b29d91b...` unchanged after each:

| Suite | Result |
| --- | --- |
| `python rl/m6_equivalence_regression.py` | PASS: normal vs no-render vs no-render + bypass identical on all 447 steps; artifact replays identical |
| `python rl/m6_raphnet_bypass_regression.py` | PASS 8/8 (config bytes identical, native replay complete) |
| `python rl/m5_smoke.py --child-env SSB64_RL_NO_RENDER=1 --child-env SSB64_RAPHNET_DISABLE=1` | 8/8 PASS |
| `python rl/m5_smoke.py` | 8/8 PASS |
| `python rl/m4_smoke.py` | 5/5 PASS |
| `python rl/m3_gym_smoke.py` | 9/9 PASS |
| `python rl/m2_restart_regression.py` | PASS, 3/3 episodes 447 actions, 446/447, exit 0 |
| `python rl/m2_lifecycle_smoke.py` | 6/6 PASS |
| `python rl/m1e_replay_regression.py --port 52101` (hand-launched) | M1e PASS, 446/447 |
| native replay (`SSB64_BTT_INPUT`, `SSB64_MAX_FRAMES=1500`, cwd build-us/Release) | `COMPLETE input_tick=447 time_passed=446`, `frames=468 actual_checksum=0x93E9EFB4`, result clear 10/446/447, host_frames 511 |

## N=4 versus N=5

`python rl/train_m7.py compare --order 4,5,5,4 --total-timesteps 51200
--compare-id m7a_compare`: four sequential runs, each a new model with base
seed 0, 51,200 transitions, 10 rollouts of 5120, horizon 3600, identical PPO,
normalisation and artifact policy. Full numbers:
`docs/rl_parallel_training_m7_comparison.json`.

| | run1 N=4 | run2 N=5 | run3 N=5 | run4 N=4 |
| --- | --- | --- | --- | --- |
| end-to-end PPO transitions/s | 654.3 | 731.4 | 760.4 | 617.2 |
| collection transitions/s | 738.2 | 861.7 | 904.6 | 718.0 |
| native tick capacity (sum, not training throughput) | 4874 | 5206 | 5523 | 4759 |
| learn wall / collect / optimizer (s) | 78.3 / 69.4 / 5.5 | 70.1 / 59.4 / 5.6 | 67.4 / 56.6 / 5.7 | 83.0 / 71.3 / 5.6 |
| collect % / optimize % | 92.7 / 7.3 | 91.5 / 8.5 | 90.8 / 9.2 | 92.8 / 7.2 |
| policy inference (s) | 12.0 | 10.0 | 10.0 | 12.3 |
| native stepping, summed over workers (s) | 42.2 | 49.3 | 46.5 | 43.0 |
| restart s mean / median / p90 | 2.47 / 2.30 / 3.39 | 2.84 / 2.39 / 4.86 | 2.71 / 2.36 / 5.01 | 2.76 / 2.36 / 4.41 |
| restart-step wall (s) | 31.3 | 23.8 | 23.2 | 32.3 |
| synchronous stall, summed over workers (s) | 123.0 | 142.6 | 132.3 | 126.7 |
| episodes started / finished | 19 / 15 | 16 / 11 | 16 / 11 | 19 / 15 |
| falls / horizon / clears | 6 / 9 / 0 | 5 / 6 / 0 | 5 / 6 / 0 | 6 / 9 / 0 |
| mean length / targets mean / max | 2986 / 2.87 / 4 | 3359 / 3.27 / 4 | 3359 / 3.27 / 4 | 2986 / 2.87 / 4 |
| startup retries, failures, request timeouts, transport failures, illegal actions, anomalies | 0 | 0 | 0 | 0 |
| system CPU collect / optimize | 59 % / 50 % | 63 % / 51 % | 62 % / 47 % | 62 % / 48 % |
| parent peak WS / private (MiB) | 285 / 458 | 286 / 458 | 287 / 458 | 288 / 458 |
| worker peak WS / game peak WS / game private (MiB) | 45 / 110 / 370 | 45 / 111 / 369 | 45 / 111 / 370 | 45 / 111 / 370 |
| native step p50 / p99 (ms) | 0.79 / 2.0 | 0.79 / 2.5 | 0.79 / 2.5 | 0.79 / 2.2 |
| vector step p50 / p99 (ms) | 1.58 / 3.5 | 1.78 / 4.0 | 1.78 / 4.0 | 1.58 / 3.5 |
| artifacts preserved / discarded; checkpoints | 3 / 12; 3 | 4 / 7; 3 | 4 / 7; 3 | 3 / 12; 3 |
| leak-free, clean close, no forced kill, user config identical | yes | yes | yes | yes |

**Selected: N=5.** Mean end-to-end throughput 745.9 vs 635.8 transitions/s
(+17.3 %, above the 5 % tolerance), equal reliability (no startup failure,
timeout, leak or forced termination in any run), optimizer share 8.9 % vs
7.3 % with the same absolute optimizer time, CPU 62 % during collection.
Repeats agree within 5.8 % (N=4) and 3.9 % (N=5). Runs with the same seed and
N produced identical episode statistics (1/4 and 2/3): training is
reproducible from Python/SB3 seeds.

Native tick capacity is about 7x the useful PPO throughput. The difference is
the synchronous learner loop: about 1 ms of SB3 policy inference per vector
step in the parent, the slowest worker per step, and above all process
restarts (about 2.5 s each, 30-45 % of collection wall time) during which
every worker waits.

## Pilot

`python rl/train_m7.py pilot --n-envs 5 --run-id m7a_pilot_n5`: a new
policy, base seed 0, 1,024,000 transitions = 200 rollouts of 5120 (N=5,
`n_steps` 1024), horizon 3600, both M6 flags, Track 1, unchanged
`btt_reward_v1`, checkpoint every 51,200, evaluation of the saved set every
102,400 (2 deterministic + 20 stochastic episodes, evaluation seed 12345),
plus the untrained policy and the final set. Random baseline:
`python rl/eval_m7.py random --episodes 100 --workers 5 --out
runs/m7a_random_baseline`. Machine-readable report:
`docs/rl_parallel_training_m7_pilot.json`.

Training-side facts (statistics, not evidence of learning):

| | |
| --- | --- |
| transitions / rollouts / optimizer updates | 1,024,000 / 200 / 2000 (10 epochs x 10 minibatches per rollout) |
| wall | run 2749 s (45.8 min); `learn()` 2540 s of which 886 s were checkpoints + evaluations inside it; 11 evaluations 1088 s in total (39.6 % of the run, reported separately, protocol unchanged) |
| end-to-end PPO throughput | 619.3 transitions/s (collection 666.6/s; native capacity 5378 ticks/s) |
| time split | collect 93.3 % (1536 s) / optimize 6.7 % (111 s); policy inference 198 s (0.97 ms per vector step) |
| restarts | 376 process starts, mean 2.29 s, p90 2.45 s, max 6.19 s; restart vector steps took 857 s = 56 % of collection wall; synchronous stall 4294 s summed over 5 workers |
| episodes | 376 started, 371 finished: 211 falls, 160 horizon truncations, 0 clears, 0 lifecycle failures; mean length 2740; targets mean 3.88, max 7 |
| reliability | 0 startup retries, 0 startup failures, 0 request timeouts, 0 transport failures, 0 illegal actions, 0 anomalies at 300, 0 leaks, clean close of all 5 workers, no forced termination |
| artifacts | 42 preserved (5 `new_best_target_count` up to 7 targets, 37 `periodic_milestone`), 329 discarded, 334 M2 episode directories deleted, 0 failure directories kept, 42 ledger entries; run directory 34 MB |
| checkpoints | 21 sets (`ckpt_000000000` .. `ckpt_000972800` every 51,200, `final`), each model + statistics + metadata + preservation state |
| resources | system CPU 61 % during collection, 47 % during optimisation; parent peak working set 290 MiB (private 460), worker 45 MiB, game 111 MiB working set / 370 MiB private |
| latency | native step p50 0.79 ms, p99 2.8 ms; vector step p50 1.78 ms, p99 4.5 ms, p99.9 2.5 s (restarts) |
| user config | sha256 and mtime unchanged |
| SB3 training metrics | entropy loss -4.27 -> -2.02 (rollout 1 -> 200), explained variance about 0.8-0.9 after rollout 50, clip fraction about 0.06; `approx_kl` was not captured in this run (see limitations) |

Training windows of 51,200 transitions: targets mean 3.14 (first window)
-> 4.3-4.7 (last four windows); the fall rate rose from 36 % to 83-96 %.

Evaluation (frozen statistics, fresh processes; every deterministic pair
identical by action digest; policy parameters and `obs_rms` unchanged after
every evaluation):

| timesteps | deterministic targets | stochastic targets mean [CI95] | max | falls / horizon | mean length | evidence vs initial / random (CI low) | learning supported |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 (initial) | 0 | 3.15 [2.65, 3.65] | 5 | 7 / 13 | 3025 | - | - |
| 102,400 | 1 | 2.55 [2.05, 3.00] | 4 | 11 / 9 | 2494 | -1.30 / -1.22 | no |
| 204,800 | 1 | 3.35 [2.80, 3.90] | 5 | 15 / 5 | 2050 | -0.55 / -0.49 | no |
| 307,200 | 2 | 3.25 [2.80, 3.70] | 5 | 12 / 8 | 2407 | -0.55 / -0.46 | no |
| 409,600 | 1 | 3.95 [3.55, 4.35] | 5 | 3 / 17 | 3431 | +0.15 / +0.27 | yes |
| 512,000 | 1 | 3.40 [2.80, 3.95] | 5 | 9 / 11 | 2752 | -0.50 / -0.45 | no |
| 614,400 | 1 | 3.95 [3.35, 4.50] | 6 | 14 / 6 | 2321 | +0.05 / +0.12 | yes |
| 716,800 | 1 | 3.95 [3.50, 4.40] | 6 | 15 / 5 | 2580 | +0.10 / +0.20 | yes |
| 819,200 | 1 | 4.25 [3.85, 4.65] | 6 | 11 / 9 | 2926 | +0.45 / +0.58 | yes |
| 921,600 | 1 | 4.15 [3.75, 4.55] | 5 | 20 / 0 | 2214 | +0.35 / +0.46 | yes |
| 1,024,000 (final) | 1 | 4.30 [3.85, 4.70] | 6 | 19 / 1 | 2140 | +0.50 / +0.59 | yes |
| random Track 1 (100 episodes) | - | 3.23 [3.02, 3.43] | 6 | 30 / 70 | 3051 | - | - |

Result under the fixed protocol: the final policy's stochastic mean of 4.30
targets exceeds the initial policy (3.15; difference +1.15, 95 % CI
[0.50, 1.80]) and the random baseline (3.23; +1.07, CI [0.59, 1.53]), and the
criterion has held at every evaluation from 614,400 on. This is a modest,
statistically supported improvement in targets broken. It is not a clear:
no evaluated or training episode cleared the stage, the best evaluated
episode broke 6 of 10 targets (stochastic, 614,400, horizon truncation;
artifact under `runs/m7a_pilot_n5/evaluations/t000614400/stochastic/`), and
the random baseline also reached 6 once. Objective ranking puts every
evaluated episode in the incomplete class.

Two observations, reported as measured:

- The deterministic (argmax) policy breaks 1 target in every evaluation
  after 102,400 (2 at 307,200) and then idles until the horizon; the
  sampled policy is far better. The learned behaviour depends on action
  sampling.
- The sampled policy falls in 19 of 20 final episodes (random: 30 of 100),
  with shorter episodes (2140 vs 3051 ticks): it breaks targets faster and
  then leaves the stage. Under `btt_reward_v1` a fall ends the -0.001 per
  tick cost with no penalty, so nothing in the current reward discourages it.
  No reward change was made or tested in M7a.

## Known limitations

- Process restarts and the synchronous vector dominate: restart steps are
  56 % of collection wall time in the pilot, and the learner uses about 12 %
  of native tick capacity. The one-active-process-per-worker rule and the
  synchronous `SubprocVecEnv` are the cause; both were kept by design here.
- The evaluation protocol costs about 100 s per point (11 points = 40 % of
  the pilot run). It was not reduced; a longer run should evaluate less often
  or in larger checkpoint intervals.
- `train/approx_kl` is missing from the pilot's `rollouts.jsonl`: SB3 logs it
  as `numpy.float32`, which the metric filter did not accept. Fixed in
  `M7PPO.train()` after the pilot (the pilot itself was not rerun; nothing
  else was affected).
- `%APPDATA%\BattleShip\ssb64.log` is shared by every process (port-side log,
  `SDL_GetPrefPath`); concurrent workers overwrite it. It is diagnostic only
  and no M7 code reads it during training; libultraship's `logs/BattleShip.log`
  is private per worker.
- The evaluation of the M2 per-episode directory of a preserved episode is
  kept (save, result JSON); every other one is deleted. Failure directories
  are capped at 20 per worker (none occurred).
- N=5 was selected from two 51,200-transition runs per configuration
  (spread 3.9-5.8 %); the pilot's end-to-end rate (619/s) was lower than the
  comparison's N=5 rate (746/s) because the learned policy falls more often,
  i.e. restarts more often. Process count depends on the policy's episode
  length.
- 20 stochastic episodes per evaluation give a CI of about +-0.45 targets;
  differences below that are not resolvable with this cadence.
- The deterministic evaluation uses 2 episodes (identical by construction);
  its only purpose is the identity check and the argmax behaviour.
- Windows only; Linux paths exist in `m7_runtime.py` but were not run.
- Limits from the comparison's short horizon still apply: no clear was
  observed anywhere, so the fastest-clear preservation path was exercised only
  by unit tests (`unit_coordinator`).

## Recommended next step

Build the M7b experiment-configuration layer from the fields this pilot
actually recorded (`run.json` / `checkpoint.json`: contracts, PPO values,
seeds, horizon, flags, evaluation cadence), then attack the dominant cost
before any longer training: overlap the next BattleShip boot with the running
episode (one standby process per worker, launched during the episode and
promoted at reset), which would remove most of the 56 % restart share while
keeping one *active* process per worker; re-measure with
`train_m7.py compare`. Any reward change (for example a fall penalty) should
be proposed as `btt_reward_v2` against this pilot's evaluation numbers, never
by editing v1.

## Commands

```text
python rl/m7_smoke.py                                   # 20 cases (unit + game), sequential
python rl/train_m7.py compare --order 4,5,5,4 --total-timesteps 51200 --compare-id m7a_compare
python rl/train_m7.py pilot --n-envs 5 --run-id m7a_pilot_n5
python rl/eval_m7.py random --episodes 100 --workers 5 --out runs/m7a_random_baseline
python rl/eval_m7.py report --pilot runs/m7a_pilot_n5 --random runs/m7a_random_baseline --out docs/rl_parallel_training_m7_pilot.json
python rl/eval_m7.py checkpoint runs/m7a_pilot_n5/final --out runs/m7a_pilot_n5/evaluations/manual_final
python rl/train_m7.py resume --from runs/<id>/checkpoints/ckpt_<t> --n-envs 5 --total-timesteps 5120 --run-id <new id>
```
