# RL M4: measurements, episode artifacts, anomaly recording

M4 establishes objective performance and reliability numbers for the
current visible-window, process-backed environment (M1c stepping, M1d
transport, M2 process lifecycle, M3 Gymnasium wrapper) before anything is
optimised, and adds the infrastructure that preserves interesting episodes
from the first training run onward. The rule of the milestone is

```text
MEASURE + PRESERVE + REPORT, but do not optimise yet
```

Nothing in M4 trains, rewards, renders headless, changes the transport,
touches process pooling, or inspects RNG. The authoritative baseline stays
`completion_time_passed = 446` and `completion_input_tick = 447`, two
different clocks that are never combined or derived from each other.

## Files

| File | Role |
| --- | --- |
| `rl/tools/bench.py` | the benchmark: startup, step throughput/latency, protocol RTT, serialisation, memory/CPU, 1..N concurrent processes, repeated-episode reliability; JSON report + console summary |
| `rl/run_artifacts.py` | episode artifact format (`metadata.json` + `actions.jsonl`), `EpisodeRecorder`, `PositionDeltaDetector`, `read_artifact`, `resubmit_actions`, optional `EpisodeRecordingWrapper` for the M3 environment |
| `rl/m4_smoke.py` | synthetic detector/recorder tests and the game-backed artifact round trip against the 7.43 s baseline |
| `port/rl/rl.h`, `port/rl/rl_boot.cpp`, `port/rl/rl_step.cpp`, `port/rl/rl_transport.cpp`, `port/gameloop.cpp` | the opt-in native timing diagnostic (`SSB64_RL_TIMING=1`), stamps only |
| `docs/rl_transport_m1d.md` | one paragraph describing the additive `timing` object |

`decomp/`, `libultraship/`, `torch/`, CMake and `rl/battleship_env.py` are
unchanged. The M3 Gym action contract `btt_raw_b8_s161_v1` and the native
M1c/M1d contract are unchanged.

## Phase A: what the frozen interfaces can and cannot measure

Measured exactly from Python, without any native change:

- **startup-to-fresh**: wall clock from before `BattleShipEpisode.launch()`
  to the M2 fresh gate (`WaitingForAction`, `can_step`, `step_count 0`),
  with the M2 timeline giving the Popen / transport / fresh sub-stages.
- **step latency and rate**: wall clock around one raw `step` request or one
  `env.step()`; one accepted step is one native tick, so the rate is native
  ticks per second, not a rendering frame rate.
- **protocol round trip**: `ping`, `status`, `observe` are non-consuming;
  their wall clock is the loopback + JSON + worker floor.
- **Python serialisation**: `json.dumps` / `json.loads` of representative
  lines, in isolation (`timeit`).
- **memory and CPU of each child**: `K32GetProcessMemoryInfo` and
  `GetProcessTimes` through `ctypes` (definitions below).
- **1..N concurrent processes** and **repeated-episode reliability**: pure
  orchestration of the M2 lifecycle.

Only approximable from Python: the split of one step into game update,
rendering/present and IPC. Before M4 the game exposed no timestamps at all,
so `step latency - ping RTT` would have been the only handle, and it cannot
tell a paced present from simulation work. The code shows why the split
matters: `GamePostUpdateEvent` (the observation capture) fires *after*
`port_drain_pending_display_list()`, whose `DrawAndRunGraphicsCommands` ends
in `SwapBuffersBegin` / `Present` / `SwapBuffersEnd`; the DXGI backend paces
every present to `1/mTargetFps` (60) with a waitable timer plus spin and
then presents with vsync (`gVsyncEnabled` default 1). A parked host
iteration re-presents the cached framebuffer through the same path. So a
stepped tick is bounded by two paced presents, and how much of it is
simulation was unknowable from outside.

Conclusion: a minimal, opt-in, stamps-only native diagnostic was necessary
for an honest attribution. It is described next; everything else in M4 is
observational Python.

## Native timing diagnostic (`SSB64_RL_TIMING=1`)

Enabled only with effective interactive stepping (`SSB64_RL_STEP=1`, no
`SSB64_BTT_INPUT`). When unset, no stamp is taken and every response is
byte-identical to a build without the diagnostic (verified: the `timing`
key is absent, never `null`). It records `std::chrono::steady_clock`
readings inside the existing M1c locked regions and feeds nothing back into
a transition, an observation or a result. Nothing in `decomp/` changed; the
only inherited-file change is one hook call in `PortPushFrame()`
(`rlStepNoteFrameLogicDone()`, between `port_resume_service_threads()` and
`port_drain_pending_display_list()`).

The successful `step` response gains an additive `timing` object (protocol
stays 1; `Observation.from_wire` is untouched because nothing inside
`observation` changes):

| Stamp | Taken where | Thread |
| --- | --- | --- |
| `request_received_ns` | transport worker extracted the request line from its buffer, before JSON parse | worker |
| `submit_ns` | `rlStepSubmit` accepted the action (WaitingForAction -> ActionReady) | worker |
| `gate_open_ns` | first `PortPushFrame` entry that found the gate open for this step | main |
| `consumed_ns` | `rlStepControllerRead` handed the action to the BTT read for tick T (accepting branch only) | game coroutine |
| `logic_done_ns` | `PortPushFrame` after `port_resume_service_threads()`, before the display-list drain | main |
| `observation_ns` | `rlStepOnObservation` paired the result at `GamePostUpdateEvent` (after render and present) | main |
| `collected_ns` | `rlStepWait` handed the result to the worker | worker |
| `response_ready_ns` | response JSON object built, before `dump()` and `send()` | worker |
| `host_iterations` | unparked `PortPushFrame` entries that served the step (1 is the normal case) | main |
| `parked_iterations` | parked host iterations immediately before the gate-open iteration | main |

What each interval contains (this is the contract the benchmark reports
under `native_timing.segments[*].contains`):

| Interval | Contains |
| --- | --- |
| `request_to_submit` | request parse, field validation, `rlStepSubmit` |
| `submit_to_gate_open` | the remainder of the parked idle-present iteration (paced present of the cached framebuffer: DXGI 1/60 s limiter + vsync) plus main-thread scheduling. Waiting, not stepping work. |
| `gate_open_to_consume` | cheats, SDL `HandleEvents`, vblank rotation, VRETRACE post, scheduler rounds up to the controller read |
| `consume_to_logic_done` | the game update of the tick: fighter, stage, targets, audio thread, display-list build. No rendering, no present. |
| `logic_done_to_observation` | Fast3D render of the display list and the present (frame-limiter wait, `Present` with vsync, frame-latency wait) |
| `observation_to_collect` | condition-variable wake of the worker |
| `collect_to_response` | response object construction |

The stamps are only meaningful as differences among themselves. The
benchmark's `client_residual_ms` is *derived*: client wall latency minus
`response_ready - request_received`, i.e. socket transit both ways, the
worker's `select()` wake, the nlohmann dump and send, and Python's
`json.dumps` / `json.loads`.

`host_iterations > 1` marks a step that needed more than one host frame
(the existing "tick not yet consumed at post-update" branch); the benchmark
reports the count so such steps are not mistaken for one slow frame.

Note for regression runs: M2 copies the parent environment into the child,
so an exported `SSB64_RL_TIMING=1` in the operator's shell would add the
object during M1e/M2/M3 runs (harmless for parsing). The benchmark sets it
explicitly through `LaunchConfig.extra_env`; the regressions were run
without it.

## Benchmark (`rl/tools/bench.py`)

```text
python rl/tools/bench.py --out bench.json
python rl/tools/bench.py --only startup,step,rtt --startup-samples 3
python rl/tools/bench.py --max-processes 3 --mp-seconds 10 --reliability-episodes 5
python rl/tools/bench.py --child-env SSB64_FREEZE_PACING=0      # variant experiments; not the baseline
```

Sections and their exact boundaries:

| Section | Definition |
| --- | --- |
| `startup` | `time.perf_counter()` immediately before `launch()` (preflight, port allocation and `Popen` included) to `wait_for_fresh_episode()` returning the fresh gate. This is fresh interactive readiness, the state before native tick 0; earlier notes called it startup-to-Go. Sub-stages: pre-launch -> Popen return, Popen -> transport reachable, transport -> fresh. Several launches; count/min/median/mean/p95/p99/max. |
| `step` | raw M1d `step` requests through `BattleShipClient.request` in one fresh process (native stamps collected when available), then `BattleShipBTTEnv.step()` in a second fresh process. Warm-up steps excluded. Rate = measured steps / sum of their latencies. Child CPU per step is derived from `GetProcessTimes` before/after. |
| `rtt` | `ping`, `status`, `observe` on the fresh parked process; the benchmark checks afterwards that `input_tick` is still 0. |
| `serialization` | `timeit` of `json.dumps` / `json.loads` on the real captured step and observe responses (re-dumped compactly) and on the request lines; microseconds per call. |
| `memory` | `PROCESS_MEMORY_COUNTERS_EX` via `K32GetProcessMemoryInfo`: `working_set` = `WorkingSetSize` (resident now), `peak_working_set` = `PeakWorkingSetSize`, `private_bytes` = `PrivateUsage` (private commit), `peak_private_bytes` = `PeakPagefileUsage` (peak commit); CPU from `GetProcessTimes`. Sampled at fresh, after stepping, and per concurrent process. Linux falls back to `/proc`. |
| `multiprocess` | for n = 1..N (default `os.cpu_count() - 1`, override `--max-processes`): n `BattleShipEpisode`s launched concurrently, one driver thread each (socket I/O releases the GIL), a shared window opened once all are fresh; aggregate = total steps / window; per-process rate, latency, startup, memory, failures; every process closed and the machine-wide process count checked before the next level. |
| `reliability` | K consecutive fresh-process baseline episodes with the M1e per-step and completion checks, the M2 finish path and the frozen result-JSON values; categories: startup_failure, startup_timeout, readiness_timeout, not_fresh, transport_failure, premature_exit, episode_timeout, request_rejected, incorrect_terminal_result, exit_timeout, exit_failure, result_invalid, cleanup_failure, process_leak. Never retried. |

Action pattern for the non-terminating runs: neutral stick with an `A`
press for one tick every 60 ticks. With a neutral stick `A` is Mario's
standing jab (not a jump); he stays on the enclosed start floor, no target
is in reach, the stage never clears. It is deterministic, legal, and
involves no learning code.

The report (`benchmark_schema` 1) carries platform, Python, logical CPU
count, executable name/size/mtime/sha256/git head, the contracts (protocol
1, observation schema 1, `btt_raw_b8_s161_v1`), every parameter, and the
sections above. Absolute machine paths are not written; every quantity is
either measured or lives under a `derived` key with a note.

## Episode artifacts (`rl/run_artifacts.py`)

The authoritative preserved artifact is the exact controller trajectory
submitted to M1d/M1c: for every accepted step, the native `RLAction` triple
as the `step` request carried it, plus the `consumed_tick` its paired
result reported. A Gym index, a Track 1 bin or a policy checkpoint may all
change later; the native triple cannot, so the run stays reproducible.

```text
<root>/<episode_id>/
    metadata.json
    actions.jsonl        {"sequence_index":0,"buttons":0,"stick_x":0,"stick_y":0,"consumed_tick":0}
```

`metadata.json` (schema `artifact_schema` 1, `action_contract`
`rlaction_native_v1`) carries `source_action_contract` (the Gym contract
the actions came through, `btt_raw_b8_s161_v1` for M3), `episode_id`,
`labels` (free-form training metadata for M5: episode number, checkpoint
label, best metrics; stored verbatim), `preserved` and
`preservation_reasons` (`manual`, `periodic_milestone`,
`new_best_target_count`, `new_fastest_completed_run`,
`major_performance_improvement`, `anomaly`), `action_count`, `status`
(`terminal`, `truncated`, `aborted`, `failed`), `terminal` (state name,
`step_count`, `last_consumed_tick`, `input_tick`, `time_passed`,
`targets_remaining`, `targets_broken`, and for a native `EpisodeEnded`
result `completion_time_passed` and `completion_input_tick`, stored
separately), `anomaly_events`, the detector configuration, the initial and
final observations, and `diagnostics` (creation time, wall time, pid, port:
operational only, never inputs to replay). No RNG metadata, no video, no
screenshots, no state dumps, no Python checksum.

Retention: nothing is written unless `preserve(reason)` was called (an
anomaly event calls it automatically); an unmarked episode is discarded for
the cost of dropping a list. `EpisodeRecordingWrapper` (a `gymnasium.Wrapper`)
records around `BattleShipBTTEnv` without changing the environment class:
it reads `info["native_action"]` and `env.last_step_result` after each
step, starts a recorder at `reset()` with the reset observation, finishes it
on termination, truncation, failure, an early `reset()` or `close()`, hands
it to an optional `on_episode_end(recorder)` hook (where M5 decides on
best-run or periodic preservation), then writes it if preserved or discards
it. The raw-client path uses `EpisodeRecorder.record_action` /
`record_result` directly. `read_artifact` validates schema, contract, row
continuity and count; `resubmit_actions` feeds an artifact through
`BattleShipClient.step` and checks each `consumed_tick` against the record.

## Anomaly recording

Detectors compare consecutive observations of one process and emit events;
they never alter, reject or clamp an action, never terminate an episode,
never change reward or stepping, and never label behaviour invalid. An
event marks the episode for preservation and is stored with its evidence;
the episode continues normally and the artifact holds the complete
trajectory before and after the event.

`PositionDeltaDetector(threshold=300.0)` is the only detector enabled by
default: `dx = current.position_x - previous.position_x` (likewise `dy`),
compared only when both observations have `fighter_valid == 1` and
`btt_active == 1` (validity is the explicit flag; zeros are never read as a
position). An axis delta strictly above the threshold raises
`large_position_delta` with previous/current input ticks, positions, delta,
threshold and the fighter status/ground-air state on both sides. The event
name says what was measured; it is never `glitch`, `glitch_detected` or
`invalid_movement`.

Calibration of the default. M4 first shipped with 200 units per native
tick, and on the tracked 7.43 s baseline that fired exactly once, at
`sequence_index` 148 (`consumed_tick` 148, input ticks 148 -> 149), with a
one-tick vertical move of about 215.525 units (position y 717.0 -> 932.5,
x -4.0), Mario airborne on both sides with fighter status 226 unchanged.
That move is legitimate Mario Up-B behaviour. The default was therefore
raised to 250 the same day and, after M5, to 300 by project decision (see
"Threshold update" below); the baseline is preserved for its manual mark
alone. What 300 is and is not:

- it is a preservation heuristic for the current Mario-only Break the
  Targets environment: exceeding it means "keep this run and look at it";
- it is not a universal definition of a glitch, and the events it raises
  are described, not judged;
- other characters may need different movement thresholds; there are no
  character-specific profiles, and none are to be implemented now;
- the value stays configurable per detector (`PositionDeltaDetector(threshold=...)`),
  and tests keep using 10, 200 and 1000 beside the default.

The detector remains observational only: it reads two observations and
returns event details; it never modifies, clamps or rejects an action,
never terminates an episode, and has no path into rewards, stepping,
physics or replay. Further detectors
(velocity magnitude, velocity delta, sudden performance improvement) plug in
through the same `ObservationDetector.compare(previous, current)` interface
without touching training; none is enabled until there are measurements to
set a threshold from.

## Smoke validation (`rl/m4_smoke.py`)

```text
python rl/m4_smoke.py                                   # every case
python rl/m4_smoke.py detector_synthetic recorder_synthetic   # no game needed
```

| Case | Proves                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| --- |----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `detector_synthetic` | at the default 300: small movement (150; 299.9 on both axes; exactly 300 on both axes) and the legitimate Mario Up-B magnitude (215.525 vertically) -> no event; 300.5 in x -> event on x; 350 in x -> event on x; -400 in y -> event on y; both axes; the event name is `large_position_delta`; invalid fighter on either side and inactive BTT -> no comparison; custom thresholds 10, 200 (fires on 215.525) and 1000 applied; 0 and -1 rejected; an event marks the run, five further actions are recorded, the written artifact has all rows, and the metadata never says "glitch"                                                                                                                                                                                  |
| `recorder_synthetic` | five native triples including the int8 limits and consumed ticks survive write -> read exactly; all six preservation reasons representable; terminal fields incl. separate completion clocks; labels stored verbatim; no RNG fields; an unpreserved episode: write refused, `discard()` drops it, no directory; `read_artifact` rejects a wrong schema, a wrong contract and a row-count mismatch                                                                                                                                                                                                                                                                                                                    |
| `wrapper_discard` | real game: 60 random Gym actions through the wrapper with the default detector; the trajectory is inspected inside the `on_episode_end` hook (the M5 decision point): 60 actions with consumed ticks 0..59, truncated at the bound; with no event the episode is not preserved -> nothing written, discarded; if the default threshold fires on the random movement the events are printed (not judged) and the run is preserved instead                                                                                                                                                                                                                                                                             |
| `baseline_roundtrip` | real game: the 7.43 s baseline through the wrapper with a manual mark -> artifact with 447 rows equal to the submitted replay rows and consumed ticks 0..446, terminal 446 / 447, `targets_broken` 10, exit 0; captured with the default detector, no event and the single reason `manual` (the Up-B move at tick 148 is below 300; any event would be printed in full); read back; resubmitted through a fresh M3 environment and through a fresh raw M1d client (`resubmit_actions`): both reach 447 actions, last `consumed_tick` 446, `completion_time_passed` 446, `completion_input_tick` 447, `step_count` 447, `targets_remaining` 0, result JSON equal to the frozen values, 21 source rows never submitted |
| `anomaly_live` | real game: threshold 1 unit on a scripted walk (stick x = -60, 40 steps): ordinary movement raises `large_position_delta` events, the episode continues to the bound, the artifact is written for reason `anomaly` and holds all 40 rows                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |

## Verified (2026-09-21)

Environment: Windows 11 (10.0.26200), Intel64 Family 6 Model 158 (6 logical
CPUs), Python 3.13.2 (CPython), gymnasium 1.3.0 / numpy 2.5.3, US Release
`build-us/Release/BattleShip.exe` rebuilt with the diagnostic
(`cmake --build build-us --config Release`, exit 0; sha256 `49d7960fa210...`,
git `279baec` + uncommitted M4 changes), DirectX 11 backend, vsync on,
window 640x480, frame interpolation off. `git diff --check` clean.

### Benchmark baseline

`python rl/tools/bench.py --out docs/rl_measurements_m4_baseline.json`
(defaults: 5 launches, 30 warm-up + 600 measured steps per stepping run,
500 RTT samples per op, 20000 x 5 serialisation iterations, N = 1..5 with a
10 s window each, 10 reliability episodes; child env `SSB64_RL_TIMING=1`).
Total wall 342 s. The full report is the JSON file next to this document.

Startup-to-fresh (5 launches, all fresh):

| | s |
| --- | --- |
| samples | 4.093, 3.316, 3.540, 3.224, 3.398 |
| min / median / mean / p95 / max | 3.224 / 3.398 / 3.514 / 4.093 / 4.093 |
| stage medians: pre-launch to Popen return / Popen to transport / transport to fresh | 0.265 / 2.042 / 1.217 |
| close (terminate) | 0.11 median |

Sequential stepping (one process each; 600 measured steps after 30 warm-up):

| Path | min | median | mean | p95 | p99 | max | native ticks/s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw M1d `step` (ms) | 22.95 | 33.30 | 33.29 | 33.64 | 34.06 | 35.06 | 30.04 |
| M3 `env.step()` (ms) | 17.89 | 33.33 | 33.36 | 33.78 | 34.99 | 93.89 | 29.97 |

Derived: M3 wrapper overhead = 0.03 ms (difference of medians); child CPU
time per step = 6.45 ms (user + kernel over the raw run), so about 80 % of
each step's wall time is waiting, not computing.

Native attribution of one raw step (600 steps with stamps, every step
served by exactly one host iteration after exactly one parked iteration):

| Interval | min | median | p95 | p99 | max (ms) |
| --- | --- | --- | --- | --- | --- |
| request_to_submit | 0.02 | 0.02 | 0.04 | 0.08 | 0.13 |
| submit_to_gate_open (parked idle present remainder) | 11.05 | 16.24 | 16.38 | 16.67 | 17.37 |
| gate_open_to_consume (HandleEvents, vblank, scheduler) | 1.07 | 2.99 | 3.52 | 4.00 | 7.31 |
| consume_to_logic_done (game update, no render) | 0.06 | 0.07 | 0.18 | 0.60 | 5.80 |
| logic_done_to_observation (render + paced present) | 0.02 | 13.60 | 14.23 | 14.77 | 15.51 |
| observation_to_collect (worker wake) | 0.01 | 0.02 | 0.14 | 0.36 | 0.91 |
| collect_to_response | 0.03 | 0.03 | 0.06 | 0.18 | 0.41 |
| native total (request received to response ready) | 22.59 | 33.00 | 33.25 | 33.69 | 34.77 |
| client residual, derived (sockets, worker select, dump/send, Python JSON) | 0.24 | 0.30 | 0.52 | 0.77 | 1.12 |

Reading: a step is two paced presents. The parked iteration's idle present
holds the main thread for the remainder of one 1/60 s interval after the
previous frame's present (16.2 ms), the frame's own present is paced to the
next interval (13.6 ms after the 3.0 ms of pre-read work), and the actual
game update of the tick takes 0.07 ms. The 0.02 ms minimum of
`logic_done_to_observation` and the 22.6 ms minimum total are the few
steps where the DXGI backend dropped a present (`IsFrameReady` false: no
render, no wait). IPC and serialisation together are the 0.3 ms residual
plus 0.05 ms of transport work.

Protocol-only round trips (500 each, fresh parked process, `input_tick`
still 0 afterwards):

| op | min | median | p95 | p99 | max (ms) |
| --- | --- | --- | --- | --- | --- |
| ping | 0.084 | 0.101 | 0.135 | 0.215 | 0.360 |
| status | 0.093 | 0.107 | 0.137 | 0.215 | 0.319 |
| observe (455-byte reply) | 0.112 | 0.129 | 0.163 | 0.245 | 0.378 |

Python serialisation (median of 5 x 20000, microseconds per call): dumps
step request (69 B) 2.92, dumps ping (26 B) 2.62, loads step response
(471 B) 6.76, loads step response with timing (845 B) 9.88, loads observe
response (455 B) 6.38, loads ping response 1.47. Derived Python JSON share
of one step: 9.7 us, i.e. 0.03 % of a 33.3 ms step.

Memory and CPU per BattleShip process (Windows definitions above):

| When | working set | peak working set | private commit | peak commit | CPU (user + kernel) |
| --- | --- | --- | --- | --- | --- |
| at fresh (launch 1) | 139.2 MiB | 139.2 MiB | 404.1 MiB | 404.1 MiB | 2.14 s |
| after 630 raw steps | 133.5 MiB | 140.7 MiB | 397.1 MiB | 405.4 MiB | 6.44 s |
| concurrent, N = 5, after 10 s | 132.0 to 141.2 MiB | 140.7 to 150.7 MiB | 395.2 to 398.2 MiB | | 3.2 to 3.9 s each |

Concurrent processes (N independent processes, own port/dir/client/thread,
10 s shared window, all launched concurrently; every level: all processes
fresh, no errors, no leak, machine-wide count back to 0):

| N | aggregate steps/s | per-process steps/s (min / median / max) | latency median / p95 / p99 (ms) | startup median / max (s) | driver Python CPU (s) |
| --- | --- | --- | --- | --- | --- |
| 1 | 30.04 | 30.04 | 33.33 / 33.59 / 34.08 | 3.38 / 3.38 | 0.05 |
| 2 | 60.02 | 30.01 / 30.02 / 30.03 | 33.32 / 33.65 / 33.95 | 4.61 / 5.61 | 0.06 |
| 3 | 86.84 | 28.42 / 29.06 / 29.49 | 33.34 / 65.79 / 71.18 | 4.53 / 6.21 | 0.23 |
| 4 | 110.34 | 26.68 / 27.70 / 28.75 | 33.34 / 68.78 / 71.92 | 5.33 / 6.50 | 0.20 |
| 5 | 136.65 | 26.14 / 27.97 / 28.06 | 33.35 / 69.09 / 71.33 | 4.44 / 6.29 | 0.22 |

Scaling is linear to N = 2 (100 % of ideal), then 96 %, 92 % and 91 % of
ideal at N = 3, 4, 5: the median step stays 33.3 ms but a p95 tail of
about 66 to 69 ms appears from N = 3 on, i.e. some steps lose a whole
present interval. N = 5 (`cpu_count - 1`) was the largest level tested; it
is the initial upper bound, not a recommendation, and the curve is still
rising there. The driver's own CPU is negligible.

Reliability: 10 of 10 consecutive fresh-process baseline episodes
succeeded, failure rate 0.0, no failure category hit. Each: startup 3.33 to
3.52 s, stepping 14.88 to 14.95 s, 447 actions, last `consumed_tick` 446,
completion 446 / 447, `step_count` 447, exit 0, result JSON equal to the
frozen values, cleanup `already_exited`, 21 rows unsent.

`BattleShip.exe` count before and after the whole benchmark: 0 and 0.

### What the measurements imply (no optimisation implemented)

| Candidate | Verdict | Why |
| --- | --- | --- |
| headless / drop-DL path | supported by current measurements | 29.8 of the 33.0 ms native step are present pacing (16.2 ms parked idle present + 13.6 ms frame present); the game update is 0.07 ms and CPU per step 6.45 ms. Removing rendering *and* both paced presents is where the time is; removing the display list alone while keeping a paced present would not be enough, and vsync off alone does not lift the software pacer. |
| binary IPC | not supported by current measurements | Python JSON is 9.7 us per step and the native transport segments 0.05 ms; the whole client residual is 0.3 ms of a 33.3 ms step (1 %). Even at a hypothetical 0.1 ms step it would matter only after the pacing is gone. |
| shared memory | not supported by current measurements | loopback ping RTT is 0.10 ms median, 0.36 ms max; IPC is not on the critical path today. Re-measure after the native step is reduced. |
| parallel process count | supported for N up to 5 on this 6-CPU machine; insufficient evidence beyond | aggregate throughput rose at every tested level (30 -> 137 steps/s) at 91 % efficiency at N = 5, with a p95 tail but no failures and about 135 MiB working set per process. Whether N = 6 or more still scales, and how the curve looks once a process no longer sleeps on presents, was not measured. |

### Artifact round trip and anomaly recording

`python rl/m4_smoke.py`: all five cases PASS, `BattleShip.exe` count 0
before and after. `baseline_roundtrip`: capture through the M3 wrapper gave
447 actions, last `consumed_tick` 446, `completion_time_passed` 446,
`completion_input_tick` 447, `step_count` 447, `targets_remaining` 0, exit
0, 21 rows unsent; the artifact (447 rows, `consumed_tick` 0..446, terminal
446 / 447, `targets_broken` 10) was read back and resubmitted through a
fresh M3 environment and through a fresh raw M1d client, each reproducing
exactly the same terminal values and result JSON. With the original
200-unit default the detector fired once on the baseline, at
`sequence_index` 148 (`dy` +215.49, airborne, status 226: Mario's Up-B), so
that first artifact carried the reasons `manual` + `anomaly`. After the
calibration to 250 (same day) the capture was rerun: no event, the single
reason `manual`; the same holds at the current default of 300 (see the
threshold update below). `anomaly_live` at threshold 1 recorded 37 events on a
40-step walk, the first at `sequence_index` 0 (`dx` -54), the episode
continued to the bound and the artifact holds all 40 rows. `wrapper_discard`:
60 random steps, no default-threshold event, nothing written, an
out-of-domain action (`stick_x` 81) rejected with `ValueError` mid-episode
left the recorder active and unchanged.

### Calibration rerun (default threshold 200 -> 250, same day)

`python rl/m4_smoke.py` after the change: all five cases PASS, no
`BattleShip.exe` before or after. `detector_synthetic` at the then default
250: 150 on one axis and the Up-B magnitude (215.525 vertically) raise
nothing; 350 in x, -400 in y and a both-axes move raise
`large_position_delta`; custom thresholds 10, 200 (which does fire on
215.525) and 1000 keep working. `baseline_roundtrip`: the 7.43 s baseline
captured with the default detector gave 447 rows, terminal 446 / 447,
`targets_broken` 10, exit 0, **zero anomaly events and the single reason
`manual`**; the same artifact then reproduced 447 / 446 / 447 / 446 through
a fresh M3 environment and a fresh raw M1d client. `wrapper_discard`: 60
random steps, no event at 250, nothing written. `anomaly_live` at threshold
1: 37 events, all 40 rows kept. No native file was touched for this change;
the rebuilt executable is the one from the benchmark above.

### Threshold update (default 250 -> 300, after M5)

By project decision after M5 the default became 300 units per native tick
(`DEFAULT_POSITION_DELTA_THRESHOLD = 300.0`); the detector's comparison
(strictly above the threshold, both observations with `fighter_valid` and
`btt_active`) is unchanged, and every caller may still pass another value.
The `detector_synthetic` case now probes the boundary explicitly: 150, 299.9
on both axes, exactly 300 on both axes and the Up-B magnitude raise nothing;
300.5 in x, 350 in x, -400 in y and a both-axes move raise
`large_position_delta`. Rerun of `python rl/m4_smoke.py` at 300 (2026-09-21):
all five cases PASS, no `BattleShip.exe` before or after; `wrapper_discard`
60 random steps with no event, nothing written; `baseline_roundtrip` 447
rows, terminal 446 / 447, `targets_broken` 10, exit 0, zero events, the
single reason `manual`, then 447 / 446 / 447 / 446 through a fresh M3
environment and a fresh raw M1d client; `anomaly_live` at threshold 1: 37
events, all 40 rows kept. Observed while the default was 250 and worth
knowing: a grounded backward roll (`fighter_status_id` 157) produced a
one-tick horizontal displacement of about 280.56 units during M5 random
exploration; at 300 it is no longer preserved by default (details in
`docs/rl_learning_m5.md`).

### Regressions after the rebuild

All run with `SSB64_RL_TIMING` unset:

- `python rl/m3_gym_smoke.py`: 9/9 PASS (`replay_complete` 447 / 446 / 447 / 446, exit 0).
- `python rl/m2_restart_regression.py`: M2 PASS, 3/3 episodes, 446 / 447 each, result JSON ok.
- `python rl/m2_lifecycle_smoke.py`: 6/6 PASS.
- `python rl/m1e_replay_regression.py --port <port>` against a hand-launched process without `SSB64_RL_EXIT_ON_END`: M1e PASS, 447 / 446 / 447 / 446, `EpisodeEnded`.

No `BattleShip.exe` remained after any run.

## Not in M4

No reward design, PPO, neural network, Stable-Baselines3 or training loop;
no Track 1; no headless mode, rendering removal, binary IPC, shared memory,
process-pool optimisation, fixed camera, replay visualisation, video
recording, raw-input optimisation; no RNG inspection, logging, control or
hashing; no change to either action contract; no optimisation of any
measured number.
