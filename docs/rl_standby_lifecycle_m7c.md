# RL M7c: standby-process lifecycle (pre-booted BattleShip per worker)

M7c removes most of the synchronous episode-restart waiting of the M7a/M7b
parallel PPO stack by keeping exactly one pre-booted STANDBY BattleShip
process ready for each worker's ACTIVE process. When the active episode
ends, the old process is closed and reaped, the ready standby is promoted
without a reset op, a step or any hidden action, its cached tick-0
observation becomes the reset observation, and the next standby boots in
the background while the new episode runs.

It is a performance optimisation only. Nothing native, in the decomp or in a
submodule changed; no M0-M6 file changed; Track 1, `btt_reward_v1`,
`btt_reward_v2`, the M3 environment, the M4 artifact format, the PPO
settings, VecNormalize, the horizon, the failure classification, the native
replay behaviour and the authoritative replay values are unchanged. The
semantic-equivalence regression below proves that cold-start and
standby-promoted episodes are identical on every submitted action, consumed
tick, observation field, reward, terminal value and canonical artifact.

```text
worker (spawn process, rl/btt_parallel.py)
    active  BattleShip  <- stepped by Track 1 -> M4 recorder -> reward -> M3/M2 (unchanged stack)
    standby BattleShip  <- booted by one background thread (rl/m7_standby.py), parked at tick 0
episode ends -> old active closed + reaped -> ready standby promoted (tick-0 observe re-verified)
             -> next standby launched (unique generation, port, process, runtime + episode directory)
```

## Files

| File | Role |
| --- | --- |
| `rl/m7_standby.py` (new) | `StandbyManager` state machine, `StandbyRecord`, `verify_readiness()`, `AcquireResult`; standard library + M2, launcher injected (unit-testable without a game) |
| `rl/btt_parallel.py` | `StandbySettings`, `M7BattleShipBTTEnv` promotion / cold fallback / background launch / generation runtime directories / cleanup, lifecycle labels and summaries, `WorkerSpec.standby_*`, standby pid reporting |
| `rl/m7_vec_env.py` | reset-mode, exposed-wait, retirement and promotion accounting; standby pids for orphan cleanup |
| `rl/experiment_config.py` | `environment.standby_preboot` / `standby_count` (class `lifecycle`), `standby_wait_timeout_s`, `resume.allow_lifecycle_change`, compatibility defaults for older checkpoints, dry-run lifecycle line, `CONFIG_MODULE_VERSION = 2` |
| `rl/m7_trainer.py` | `M7Config.standby_*`, `lifecycle` in `run.json` / `checkpoint.json` / `training_summary.json`, resume across lifecycle modes, `lifecycle_summary()`, comparison columns |
| `rl/m7_evaluation.py` | evaluation workers use the profile's lifecycle; results record it |
| `rl/m7_report.py` | pilot report carries the lifecycle block |
| `rl/configs/m7_mario_us_reward_v1_standby.toml`, `..._v2_standby.toml` (new) | the v1 / v2 profiles with the standby lifecycle |
| `rl/m7c_standby_tests.py` (new) | 4 unit + 17 game cases (equivalence, repeated promotion, every failure and cleanup path, contention, bounded v2 smoke, resume across modes) |
| `rl/m7c_compare.py` (new) | Stage 1 (standby off vs on) and Stage 2 (N=4 vs N=5 with standby) drivers and report |
| `docs/rl_standby_lifecycle_m7c*.json` | machine-readable results (see "Results") |

## Phase A findings (before any edit)

- **Where the restart cost lives.** `M7BattleShipBTTEnv.reset()` (worker
  side) disposes of the previous process and launches a new one through
  M3/M2 synchronously; SB3's `SubprocVecEnv` protocol auto-resets inside the
  worker's `step` command, so every other worker waits for it inside
  `step_wait` (M7a: about 2.3 s per restart, 56 % of collection wall time in
  the pilot).
- **When the old process dies, per terminal path.** Native clear: M3 waits
  for the deferred clean exit inside `step()` (`finish()`, exit code 0,
  result JSON), then disposes. Native failure (fall): M7 disposes at once
  inside `step()`. Horizon: M3 disposes inside `step()`. Request timeout /
  transport failure: M3 disposes in `step()` (phase `failed`) and Track 1
  turns it into a truncation; the auto-reset then launches. Worker
  exception: `m7_worker` closes the environment in its `except` and
  `finally`. Startup failure: M3 disposes the failed process; M7 retries on
  a new port up to three times. Interrupt: the parent drains replies, asks
  every worker to close. In every path the reset that follows starts with
  `_dispose_episode()` on an already-gone or still-parked process.
- **Job object.** A process launched from a worker background thread is
  inside the trainer's kill-on-close job (probe: `IsProcessInJob` true for
  a thread-launched BattleShip); membership is per process and inherited.
- **Thread safety.** `BattleShipEpisode` and `BattleShipClient` are
  documented not thread-safe; M7c never shares them between threads: the
  launcher thread owns the episode until readiness, the main thread takes
  it only after joining the thread. `PortCandidates.claim()` is guarded by a
  lock; `subprocess.Popen` in a thread is safe (CPython passes an explicit
  handle list, so a concurrent launch cannot inherit another child's
  handles), and M7c never has two launches in flight in one worker anyway.
- **Runtime directories.** M7a gives every worker one private cwd (config
  copy, imgui copy, `.tcc` junction). Two processes of one worker sharing it
  would race on `BattleShip.cfg.json`: a clear's clean exit rewrites the
  file (libultraship `Config::Save` truncates in place) while the next
  standby may be booting and reading it, and `Reload()` falls back to an
  empty configuration on a parse error. In standby mode every launch
  therefore gets its own generation runtime directory
  (`workers/wNN/runtime_gens/g<gen>_a<attempt>`, prepared by the unchanged
  `prepare_worker_runtime`), deleted together with its episode directory.
  Standby off keeps the M7a layout exactly.
- **Ports.** Each rank's block and the fresh-candidate-per-attempt rule are
  reused; standby attempts draw from the same block under the lock.
- **Parked standby cost (measured, one process, both M6 flags, 20 s parked
  at tick 0):** CPU 0.0625 s over 20 s (0.31 % of one core), working set
  112 MiB, private 367 MiB, boot CPU 2.06 s. All 17 observation fields
  (including `host_frame`) identical before and after the park; status
  `WaitingForAction`, `can_step`, `step_count 0`, `input_tick 0`,
  `time_passed 0` unchanged; the first step after the park returned
  `consumed_tick 0`, `input_tick 1`, `step_count 1`. Wall-clock waiting does
  not advance simulated BTT time (the M6 parked iteration sleeps on the
  M1c condition variable; the game coroutine cannot run while the gate is
  closed).
- **Safe preboot needs no native or submodule change**: readiness is
  proven with the existing non-consuming `status` and `observe` ops.

## State machine and ownership

```text
no_standby --launch(gen)--> starting --thread: fresh + readiness proven--> ready
starting   --thread: attempts exhausted / unexpected error----------------> failed
starting   --cancel() (terminate in-flight process, join)------> closing --> no_standby
ready      --acquire(): alive + status + observe re-verified---> promoting --promoted()--> no_standby
ready      --acquire(): dead / request failed / observation drifted--> (lost) no_standby
ready      --cancel() / close()----------------------------------> closing --> no_standby
failed     --acquire(): failure consumed and reported (cold fallback)-----> no_standby
```

- One `StandbyManager` per worker; `launch()` refuses while a standby
  exists or is in flight, so a worker owns at most one active and one
  standby process (`live_processes()`, `max_concurrent_processes` recorded).
- Every launch attempt has a unique generation number (shared counter with
  cold launches: the M3 episode index IS the generation), port, OS process,
  runtime directory, episode directory, save path, result path and log; a
  promoted process's files are never touched by the retirement of the
  previous one (directories are unique and the retired process is reaped
  before any deletion).
- The launcher thread owns the `BattleShipEpisode` it creates until the
  state is `ready` and the thread has finished; the main thread never uses
  it before joining the thread. Cancellation from the main thread only
  terminates the OS process, which makes M2's bounded wait loops return in
  the launcher thread; the thread then closes and reaps its own episode. A
  cancel that arrives before the process exists is applied in
  `note_inflight()`.
- The replacement standby is launched only after the promoted (or
  cold-launched) active process exists with its own generation.
- `close()` cancels, joins (bounded by request + exit timeout + 5 s) and
  closes; `M7BattleShipBTTEnv.close()` runs it before the M3 close so no new
  process can appear during shutdown. The worker's final report is taken
  after close. The parent kills, by pid with an image-name check, the active
  AND the last reported standby of any worker that did not close cleanly;
  the Windows job object is the backstop behind both.

## Readiness and promotion contract

A standby is promotable only after the launcher thread proved, with
non-consuming requests only: process alive, transport connected, status
`WaitingForAction` with `can_step` and `step_count 0` (M2's fresh-episode
contract), `observe()` succeeded with `input_tick 0`, `time_passed 0`,
`btt_active 1`, `targets_remaining 10`, and the status flags `no_render` /
`raphnet_disabled` equal to what the worker's environment variables demand
(`verify_readiness()`, recorded as `readiness_proof`). The record also
carries the worker's profile (reward contract and values, semantic
fingerprint, task id, horizon, flags, executable); promotion refuses a
record booted for another profile. No controller action is consumed
(`step_count 0`) and no artifact episode starts: the M4 recorder is
created only by `EpisodeRecordingWrapper.reset()`, which runs at promotion.

At promotion the main thread re-issues `status` and `observe` and requires
the observation to equal the cached one field for field; any difference,
a dead process or a failed request is `standby_lost` (the process is
closed, a cold fallback follows, no stale observation is ever returned).
The promoted process is installed exactly where M3's reset would have
installed a new one (`_episode`, `last_observe`, phase `active`, step
counters zero), so every outer wrapper (M4 recorder, Track 1, reward,
statistics) sees an ordinary reset. The first action after promotion
produces `consumed_tick 0`, `input_tick 1`, `step_count 1`.

Recorded per reset (`info["m7_startup"]`, artifact labels `startup` /
`startup_mode` / `lifecycle`, episode summaries `startup_mode`): mode
(`cold_start`, `standby_promoted`, `cold_fallback`), generation, attempts
and ports, standby startup duration, time ready before promotion, exposed
wait at reset, promotion latency, active retirement duration, live
processes after reset, the readiness proof and, for a fallback, its reason
with the failed standby's attempt history.

## Failure recovery

| Situation | Behaviour |
| --- | --- |
| standby still booting at reset | wait for the already-owned launch, bounded by `standby_wait_timeout_s` (exposed wait recorded); on expiry cancel it and fall back cold (`wait_timeout`) |
| standby attempt fails (bind race, transport, timeout, not fresh) | recorded, process killed and reaped, next candidate port, up to `startup_attempts`; the active episode is never touched |
| all standby attempts fail | state `failed`; the next reset performs the unchanged synchronous launch (`cold_fallback`, reason `failed`, attempts attached) and starts a new standby afterwards |
| standby dies or changes after readiness | detected at promotion (`standby_lost`), closed, cold fallback |
| launcher bug (non-lifecycle exception) | structured `starting_error` surfaced as a worker failure at the next reset, never silent, the active episode finishes first |
| active request timeout / transport failure | unchanged M3/M7 path (`episode_failure` truncation); the auto-reset promotes the standby |
| worker exception | environment closed in the worker (standby cancelled first); parent kills leftovers by pid |
| Ctrl+C | parent drains replies and closes every worker: a ready standby is closed, a booting one cancelled |
| hard kill of the trainer | kill-on-close job object removes workers, active and standby processes |

No reward term is attached to any of these: `btt_reward_v2` penalises only
`native_failure`, and administrative events never become gameplay
terminations.

## Configuration

```toml
[environment]
standby_preboot = true          # class lifecycle: in both fingerprints, compared on resume
standby_count = 1               # 0 or 1 in M7c; must agree with standby_preboot
standby_wait_timeout_s = 120.0  # operational
[resume]
allow_lifecycle_change = false  # accept a resume across lifecycle modes (recorded in the lineage)
```

The historical profiles (`m7_mario_us_reward_v1.toml`, `..._v2.toml`) are
untouched and resolve to no standby (defaults `false` / `0`); the new
`..._v1_standby.toml` / `..._v2_standby.toml` differ from them exactly in
`run.name`, `run.notes`, `standby_preboot` and `standby_count`. The legacy
M7a subcommands never enable a standby. `standby_count = 2`,
`standby_preboot = true` with `standby_count = 0` (and vice versa),
`standby_wait_timeout_s <= 0` and `allow_lifecycle_change` outside
`mode = "resume"` are rejected with the field path.

Recorded: source and resolved configuration (`resolved.lifecycle` with the
expected maximum game-process counts), experiment summary (`lifecycle`),
`run.json` and every `checkpoint.json` (`lifecycle`), `model.zip`
(`m7_experiment.lifecycle`), `training_summary.json` (`lifecycle` with the
aggregated standby metrics and per-worker reports), evaluation results
(`lifecycle`, `checkpoint_lifecycle`), artifact labels (`lifecycle`,
`startup_mode`, `startup`), comparison reports. The dry run prints the
lifecycle line with the expected maximum game-process count (N x 2 with a
standby).

Resume: the two lifecycle keys are compared like immutable fields. A
checkpoint written before M7c (no `lifecycle` block, or an M7b
`compatibility_view` without the keys) is read as standby off. Resuming it
under a standby profile is refused with a message naming
`resume.allow_lifecycle_change`; with that key the resume runs and the
lineage records `lifecycle_change` and `lifecycle_at_checkpoint`.
`CONFIG_MODULE_VERSION` is 2: fingerprints of the historical profiles
computed by module version 2 include the lifecycle keys and therefore
differ from the module-version-1 values quoted in the M7b document (v1
semantic `c93faaf9...` now, `d49c320d...` under module version 1); the
legacy `pilot --n-envs 5` arguments and the v1 profile still share one
semantic fingerprint.

## Semantic equivalence (`cold_vs_standby_replay`, `terminal_paths_promotion`)

The authoritative 447-action raw replay (`tas_input_2/mario_743.btti`)
through the worker stack below Track 1 (M7 base environment, reward wrapper,
M4 recorder with every episode preserved), M3 action domain, both M6 flags:

- Reference: standby off, two cold episodes, identical to each other.
- Candidate: standby on, 11 consecutive episodes in one worker (modes
  `cold_start` then `standby_promoted` x 10). Every promoted episode equals
  the cold reference on the initial tick-0 observation (state, `step_count`
  and all 17 observation fields), on every submitted action, every
  `consumed_tick`, every observation field of every step, every reward,
  the terminal result JSON (clear, 10 targets, `completion_time_passed`
  446, `completion_input_tick` 447), the byte-identical canonical
  `actions.jsonl` (sha256 equal) and the authoritative artifact metadata
  (action count 447, status `terminal`, terminal values, 0 anomaly events
  at threshold 300, initial and final observations, detectors). Each
  episode: 447 steps, final `step_count` 447, 21 rows unsubmitted, native
  clear, return exactly 19.553; the first step of every promoted episode
  returned `consumed_tick 0`, `input_tick 1`, `step_count 1` (no hidden
  step, no stale observation).
- Identity: 11 distinct pids, ports and episode directories; 11 artifact
  directories for 11 episodes (a standby boot creates no artifact); 11
  generation runtime directories left (the generation cancelled at close
  was removed); manager counts launches 11, ready 10, promoted 10, failed 0,
  lost 0, failed attempts 0, cancelled 1 (the in-flight one at close);
  16 threads started and joined (11 launcher threads; thread alive after
  close: no); maximum concurrent processes 2.
- Timing (this deliberately fast episode takes ~0.8 s of stepping, shorter
  than a boot): standby startup mean 2.31 s (median 2.17, max 3.14),
  exposed wait mean 1.36 s (the boot still in flight), promotion 0.1 ms.
- v2: three episodes (`cold_start`, `standby_promoted` x 2) return 19.553
  each with the same actions sha256 and step trace as the cold v1
  reference.
- Terminal paths (vector environment, one worker, horizon 600, v1 then
  v2): fall (432 steps, consumed tick 431) -> promoted -> horizon truncation
  (600 steps) -> promoted -> fall -> promoted. Returns v1 -0.432 / -0.6 /
  -0.432, v2 -5.432 / -0.6 / -5.432 (penalty applied exactly once per fall,
  never on a promoted horizon episode); every artifact canonical with rows
  equal to steps and labels `startup_mode` / `lifecycle`; promotion 0.1 ms;
  standby startup 2.32-2.37 s.

## Failure and cleanup (`rl/m7c_standby_tests.py`, 4 unit + 17 game cases, all PASS)

After every case: zero `BattleShip.exe`, every launcher thread joined
(started == joined, none alive, state `no_standby`), no listening socket
left on any port a worker used, user configuration sha256 and mtime
unchanged.

| Case | Evidence |
| --- | --- |
| `unit_state_machine` | every transition with a fake launcher: happy path, refused second launch, cancel while starting (in-flight process terminated, thread joined, not counted as a failed attempt), attempts exhausted, retry, lost by death / request failure / state change / observation drift, wait timeout (0.2 s bound honoured), unexpected launcher error surfaced as `starting_error`, close idempotent and terminal, abandoned promotion closed |
| `unit_readiness_contract` | rejects `input_tick 1`, `step_count 1`, `time_passed 1`, wrong or missing flags, 9 targets |
| `unit_config_lifecycle` | profiles resolve, diff sets exact, both fingerprints change with the mode, legacy arguments never enable a standby, rejections, dry-run line, CLI dry run |
| `unit_resume_lifecycle` | M7a/M7b-shaped checkpoints read as standby off; the real pilot set is refused under the standby profile with the `allow_lifecycle_change` hint and accepted with it (override recorded), no directory created |
| `shutdown_active_and_ready` | active + ready standby (2 live processes) closed in 0.16 s, both pids dead, history `closed`, no runtime generation left |
| `shutdown_while_starting` | close while booting: cancelled in 2.25 s, counts cancelled 1 / failed attempts 0, cancelled generation directory removed |
| `wait_timeout_fallback` | 40-tick episodes with a 0.05 s bound: `wait_timeout` -> cancel -> `cold_fallback` three times, all recorded |
| `interrupt_active_play` / `interrupt_during_standby_launch` | Ctrl+C (test hook) at vector step 2500 / 3 of a training run: status `interrupted`, `interrupted/` set with the lifecycle, ready standby `closed` / booting standby `cancelled`, leak-free, no forced termination |
| `worker_exception_both_slots` | injected fault in rank 1 with an active and an in-flight standby: `M7WorkerFailure` with the standby snapshot in its context, run `failed`, leak-free |
| `active_timeout_then_promotion` | detection off, 3 s request timeout: fall hangs -> `episode_timeout` -> auto-reset promotes the standby -> the promoted process serves the next episode |
| `standby_startup_timeout_retry` | first standby attempt times out (0.3 s bound), second is fresh on another port, first pid dead, promotion records 2 attempts / 1 failure |
| `standby_bind_failure_retry` | port squatted after launch: `transport_failure` after 8.4 s, retry fresh on the next port, promoted |
| `standby_exhausted_cold_fallback` | all 3 standby attempts fail while the active episode runs its full 300 steps unaffected; next reset `cold_fallback` (reason `failed`, 3 attempts attached), 3 failure directories kept under the cap, the following standby promoted |
| `standby_lost_after_ready` | ready standby killed from outside: `standby_lost` ("process exited (code 1) after readiness"), cold fallback, next standby promoted |
| `job_object_kill_standby` | trainer with 2 workers, 2 active and 2 ready standby processes hard-killed: all 6 gone |
| `startup_contention` | see "Resource cost" |
| `v2_standby_smoke` (N=2 and N=5) / `resume_lifecycle_game` | see "Bounded v2 compatibility" |

## Resource cost of a standby

Parked standby (Phase A probe, one process, 20 s at tick 0): CPU 0.31 % of
one core, working set 112 MiB, private 367 MiB; observation unchanged.
In the 51,200-transition runs (every promoted generation sampled at
readiness and at promotion): CPU while parked 0.04-0.07 s mean per
generation over 9.6-14.1 s parked (max 0.16 s), working set at readiness
110 MiB (max 117), private 369 MiB, boot CPU about 1.9-2.1 s per launch.

Initial boot burst (`startup_contention`, one rollout of 5120 transitions,
horizon 3600, `docs/rl_standby_lifecycle_m7c_contention.json`): with the
standby on, every worker's first standby boots while every active process
steps, i.e. 2N processes booting or stepping on 6 logical CPUs.

| | N=4 off | N=4 on | N=5 off | N=5 on |
| --- | --- | --- | --- | --- |
| initial reset (s) | 5.01 | 5.77 | 5.09 | 6.45 |
| first standby startup per worker (s) | - | 2.3-4.1 | - | 2.7-6.2 |
| system CPU during collection | 88 % | 99.8 % | 96 % | 99.8 % |
| native step p50 / p99 (ms) | 0.89 / 3.5 | 1.41 / 7.9 | 1.12 / 4.5 | 1.78 / 11.2 |
| end-to-end in this single first rollout (tr/s) | 469 | 366 | 454 | 351 |
| maximum concurrent processes per worker | 1 | 2 | 1 | 2 |

The burst slows the first rollout (no promotion can happen yet) and
doubles native step latency while it lasts; no startup failure, retry or
timeout occurred in any run. In the full runs the boots are staggered and
the effect appears as a modest steady-state cost: native step p50 0.79 ->
0.89 ms and p99 2.8 -> 4-5 ms at N=5, system CPU during collection 59-60 %
-> 77-82 %, worker working set 45 -> 47 MiB, parent unchanged (287-290 MiB
working set, 461 MiB private), game processes 110 MiB working set / 369
MiB private each. Total game-process memory bound at N=5 with standby: 10
x 110 MiB working set (1.1 GiB), 10 x 369 MiB private (3.7 GiB) on the
16 GB machine. No bounded-startup mechanism was added: the burst is
one-off, bounded by N, and every run stayed free of startup problems; see
"Limitations".

## Stage 1: N=5, standby off versus on

`python rl/m7c_compare.py stage1` twice (`m7c_stage1`, `m7c_stage1b`;
`docs/rl_standby_lifecycle_m7c_stage1.json`, `..._stage1_repeat.json`).
Equal workload: `btt_reward_v1`, 51,200 transitions = 10 rollouts of 5120,
`n_steps` 1024, batch 512, 10 epochs, gamma 0.999, GAE lambda 0.995, horizon
3600, observation-only VecNormalize, 64x64 tanh, lr 3e-4, base seed 0.

| | off (stage1) | on (stage1) | off (repeat) | on (repeat) |
| --- | --- | --- | --- | --- |
| end-to-end PPO transitions/s | 755.8 | 908.4 | 746.5 | 972.8 |
| collection transitions/s | 882.3 | 1153.5 | - | - |
| learn / collect / optimizer wall (s) | 67.8 / 58.0 / 5.3 | 56.4 / 44.4 / 6.0 | 68.6 / - / - | 52.7 / - / - |
| restart vector steps wall (exposed) (s) | 25.7 | 2.9 | 24.5 | 0.6 |
| synchronous stall, summed over workers (s) | 140.5 | 70.8 | 136.9 | 53.4 |
| worker reset p50 / max (ms) | 2512 / 4133 | 4.5 / 126 | 2512 / 3745 | 4.5 / 14.7 |
| promotions / ready at reset / waited / cold fallbacks | - | 11 / 11 / 0 / 0 | - | 11 / 11 / 0 / 0 |
| standby startup mean / max (s); hidden total (s) | - | 3.12 / 3.50; 32.7 | - | 2.96 / 3.54; 30.9 |
| time ready before promotion mean (s) | - | 14.1 | - | 13.2 |
| standby failures / retries / lost / wait timeouts | - | 0 / 0 / 0 / 0 | - | 0 / 0 / 0 / 0 |
| episodes started / finished; falls / horizon / clears; targets mean | 16 / 11; 5 / 6 / 0; 3.27 | identical | identical | identical |
| native step p50 / p99 (ms) | 0.79 / 2.8 | 0.89 / 5.0 | - | - |
| system CPU collect / optimize | 59 % / 44 % | 82 % / 58 % | 60 % / 56 % | - / 63 % |
| leaks / forced terminations / user config | 0 / none / identical | 0 / none / identical | same | same |

Gain: +20.2 % and +30.3 % (mean of the four N=5 standby-on runs including
Stage 2: 966.5 tr/s versus 751.2 off, +28.7 %). The exposed restart time
fell from 24.5-25.7 s to 0.6-2.9 s per run, the summed stall halved, and
every promoted generation had been ready for 13-14 s. Episode outcomes
and target counts are identical between off and on (same seed, same
trajectories). The first Stage 1 standby row's `startup_retries` (11) was
an accounting bug (promoted generations counted as retries), fixed before
Stage 2 and the repeat; the repeat row reads 0.

## Stage 2: N=4 versus N=5 with standby on

`python rl/m7c_compare.py stage2` (`m7c_stage2`, order 4, 5, 5, 4;
`docs/rl_standby_lifecycle_m7c_stage2.json`).

| | run1 N=4 | run2 N=5 | run3 N=5 | run4 N=4 |
| --- | --- | --- | --- | --- |
| end-to-end PPO transitions/s | 878.1 | 974.7 | 1010.2 | 880.8 |
| learn / collect / optimizer wall (s) | 58.4 / 47.3 / 5.9 | 52.6 / 40.8 / 6.1 | 50.8 / 40.7 / 6.0 | 58.2 / 46.6 / 6.3 |
| optimizer share | 11.0 % | 13.1 % | 12.8 % | 11.8 % |
| exposed restart wall (s) / summed stall (s) | 0.8 / 48.5 | 0.8 / 59.7 | 1.2 / 61.2 | 1.0 / 47.7 |
| promotions / ready at reset / fallbacks | 15 / 15 / 0 | 11 / 11 / 0 | 11 / 11 / 0 | 15 / 15 / 0 |
| standby startup mean (s); ready before promotion mean (s) | 2.63; 9.9 | 3.24; 12.6 | 3.01; 12.6 | 2.89; 9.6 |
| episodes finished; falls / horizon; targets mean | 15; 6 / 9; 2.87 | 11; 5 / 6; 3.27 | 11; 5 / 6; 3.27 | 15; 6 / 9; 2.87 |
| native step p50 / p99 (ms); vector step p99 (ms) | 0.89 / 4.0; 6.3 | 0.89 / 4.0; 7.9 | 0.89 / 5.0; 8.9 | 0.89 / 3.5; 6.3 |
| system CPU collect / optimize | 84 % / 68 % | 77 % / 58 % | 79 % / 58 % | 81 % / 70 % |
| parked standby CPU mean per generation (s) | 0.047 | 0.048 | 0.041 | 0.037 |
| game WS max / worker WS / parent private (MiB) | 110 / 47 / 461 | 110 / 47 / 461 | 117 / 47 / 461 | 110 / 47 / 461 |
| standby failures / retries / lost; leaks; clean close; user config | 0; 0; yes; identical | same | same | same |

**Selected: N=5 with standby on.** Mean 992.5 vs 879.5 transitions/s
(+12.8 %, above the 5 % tolerance), spreads 3.6 % (N=5) and 0.3 % (N=4),
equal reliability (no startup failure, retry, timeout, leak or forced
termination in any run), 10 game processes at most. N=4 keeps more CPU
headroom (84 % vs 77-79 % during collection is not headroom, both are
high) and slightly tighter latency tails (vector step p99 6.3 vs 7.9-8.9
ms), but the throughput difference is well outside the tolerance and the
episode statistics of each N reproduce M7a's cold runs exactly (N=4: 15
episodes, 2.87 targets; N=5: 11 episodes, 3.27 targets), so the lifecycle
changed nothing but time. Native tick capacity is still several times the
PPO throughput: the remaining gap is the synchronous vector (the slowest
worker per step plus about 1 ms of parent inference), not restarts.

## Bounded v2 compatibility (`v2_standby_smoke`, `resume_lifecycle_game`)

Derived from `m7_mario_us_reward_v2_standby.toml`: 15,360 transitions (3
rollouts, 30 optimizer updates), horizon 3600, checkpoint every 5120,
final evaluation 1 deterministic + 2 stochastic episodes, seed 0.

| | N=2 | N=5 (selected) |
| --- | --- | --- |
| status | completed, leak-free, user config identical | completed, leak-free, user config identical |
| episodes started / finished | 7 / 5 (2 falls, 3 horizon) | 6 / 1 (1 fall) |
| falls with the penalty | rank 1 ep 1 (832 steps, -4.832, cold start); rank 1 ep 2 (2061 steps, -5.061, standby promoted) | rank 3 ep 1 (2090 steps, -5.09, cold start) |
| every finished return = v2 closed form; penalty flag exactly on falls | yes | yes |
| promotions / ready at reset / fallbacks / lost | 5 / 5 / 0 / 0 | 1 / 1 / 0 / 0 |
| hidden startup (s) / exposed wait (s) | 11.4 / 0.0 | 2.5 / 0.0 |
| end-to-end transitions/s | 514 | 807 |
| checkpoint sets (each with `vecnormalize.pkl` and `lifecycle`) | 4 | 4 |
| final evaluation (frozen statistics, parameters and `obs_rms` unchanged) | det 1 episode; stoch 2 (mean 3.0, 1 fall), raw returns = v2 closed form | det 1 (2 targets, horizon); stoch 2 (mean 3.0, 1 fall), raw returns = v2 closed form |
| provenance | `run.json`, every `checkpoint.json`, `model.zip`, `training_summary.json`, evaluation summary and every artifact label carry `btt_reward_v2` and `lifecycle.standby_preboot = true`; evaluation workers promoted their standbys too | same |

Resume across modes (v2 standby smoke checkpoint `ckpt_000010240` under
the standby-off v2 profile): refused before any directory exists with the
`allow_lifecycle_change` hint; with `resume.allow_lifecycle_change = true`
one more rollout runs (10240 -> 15360), the lineage records
`lifecycle_change` and `lifecycle_at_checkpoint`, and the standby-off
resume promotes nothing. Verified at N=2 and again at N=5 (`runs/_m7c_v2_n5b`).

No learning quality is compared and no million-transition v2 pilot was run.

## Regression chain (2026-09-22)

Sequential, one suite at a time, zero `BattleShip.exe` after every suite
(`runs/_m7c_regressions.log`, `runs/_m7c_regressions/results.json`). The
user's `build-us/Release/BattleShip.cfg.json` sha256 `1b29d91b...` was
identical before and after every suite. Its mtime is unchanged after every
M7c group (standby tests, Stage 1, Stage 2, v2 smoke) and after the M7b
suites; it changes once inside the M7a smoke (its `isolation_boot_replay`
default-cwd reference leg runs the game in `build-us/Release` by design,
rewriting the file with identical bytes) and inside the M1-M6 suites, the
M1e hand-launched process and the native replay, which all run there by
design. No M7c worker ever opens that file.

| Suite | Result |
| --- | --- |
| `python rl/m7c_standby_tests.py` (4 unit + 17 game cases) | PASS (unit 4/4; game 10/17 in the first run, the 7 test-side corrections rerun 7/7; N=5 v2 smoke + resume rerun 2/2) |
| `python rl/m7b_config_tests.py` | 16/16 PASS (12.9 s) |
| `python rl/m7b_smoke.py` | 7/7 PASS (207.9 s) |
| `python rl/m7_smoke.py` | 20/20 PASS (241.0 s) |
| `python rl/m6_equivalence_regression.py` | exit 0 (35.1 s) |
| `python rl/m6_raphnet_bypass_regression.py` | exit 0 (127.5 s) |
| `python rl/m5_smoke.py --child-env SSB64_RL_NO_RENDER=1 --child-env SSB64_RAPHNET_DISABLE=1` | exit 0 (38.3 s) |
| `python rl/m5_smoke.py` | exit 0 (93.2 s) |
| `python rl/m4_smoke.py` | exit 0 (68.6 s) |
| `python rl/m3_gym_smoke.py` | exit 0 (104.1 s) |
| `python rl/m2_restart_regression.py` | exit 0 (56.4 s) |
| `python rl/m2_lifecycle_smoke.py` | exit 0 (23.1 s) |
| `python rl/m1e_replay_regression.py --port 52101` (hand-launched process, cwd `build-us/Release`) | exit 0, game exit 0, result clear 10 / 446 / 447, host_frames 511 |
| native replay (`SSB64_BTT_INPUT`, `SSB64_MAX_FRAMES=1500`, cwd `build-us/Release`) | `COMPLETE input_tick=447 time_passed=446`, `frames=468 actual_checksum=0x93E9EFB4`, result clear 10 / 446 / 447 |
| dry runs of the four profiles | exit 0; lifecycle line off / 5 processes for v1 and v2, on / 10 processes for the standby profiles |
| dry-run resume of `runs/m7a_pilot_n5/final` | v1 profile: no diffs; v1 standby profile: exactly the two lifecycle diffs |
| `git diff --check` (tracked changes; new files have no trailing whitespace) | clean |

## Known limitations

- The gain depends on episode length versus boot time: a standby needs
  about 2.4-3.5 s (more under the initial burst); episodes shorter than
  that expose the remaining boot as a wait (`late_hits_waited`). With the
  random / early policies of these runs every promotion was ready 10-14 s
  before it was needed; a policy that falls within a second of the start
  would see partial waits, still never longer than a cold start.
- The initial burst (2N boots on 6 CPUs) doubles native step latency for a
  few seconds and slows the first rollout; no bounded-startup gate was
  added because no failure, retry or timeout occurred at N=4 or N=5 and
  the effect is one-off. Ten processes are the ceiling at N=5; more
  workers would need that gate (and more memory: 369 MiB private each).
- Steady-state cost: system CPU during collection rises from about 60 %
  to 77-82 % at N=5 and native step p99 from 2.8 to 4-5 ms, because boots
  overlap stepping. The throughput numbers above include that cost.
- Native clears still wait for the deferred clean exit inside `step()`
  (M3 `finish()`, unchanged); a standby cannot hide that part. Clears are
  rare in training; the raw-stack replay regression measures the full
  clear path.
- `retire_s` statistics are empty in the training runs because every
  terminal path (clear, fall, horizon) already disposed of the process
  inside `step()`; only a reset after an unusual state pays a retirement.
- The per-generation runtime directories add two small file copies and a
  junction per launch (about 1 ms) and one directory per live generation.
- `standby_count` is limited to 0 or 1; the machine has no CPU budget for
  more.
- Windows only, as before; the Linux paths are untested.
- The evaluation protocol was not shortened; evaluations also use the
  standby lifecycle when the profile enables it.

## Recommended next step

Run the v1 and v2 standby profiles as two full 1,024,000-transition pilots
(`python rl/train_m7.py --config rl/configs/m7_mario_us_reward_v1_standby.toml
--run-id <id>` and the v2 twin, N=5, same seed and evaluation cadence),
compare them by the M7a learning-evidence rule (never by training reward),
and report the lifecycle metrics of both. Before that, if evaluation cost
matters, reduce the evaluation cadence in a derived profile rather than in
the checked-in ones. The remaining throughput ceiling is the synchronous
vector; an asynchronous vector environment would be the next lifecycle
change and is out of M7c's scope.

## Commands

```text
python rl/m7c_standby_tests.py                       # 4 unit + 17 game cases
python rl/m7c_standby_tests.py unit
python rl/m7c_standby_tests.py v2_standby_smoke resume_lifecycle_game --selected-n 5
python rl/m7c_compare.py stage1 --compare-id m7c_stage1
python rl/m7c_compare.py stage2 --compare-id m7c_stage2
python rl/train_m7.py --config rl/configs/m7_mario_us_reward_v1_standby.toml --dry-run
python rl/train_m7.py --config rl/configs/m7_mario_us_reward_v2_standby.toml --run-id <run name>
```
