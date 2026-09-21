# RL M6: training throughput, the no-render host mode

M6 removes the host work that M4 measured as the cost of a stepped tick
(rendering, presentation and presentation pacing) behind one explicit,
opt-in, training-only mode, proves that the simulation is unchanged by it,
and remeasures single-process and multi-process throughput. It is an
execution-performance and semantic-equivalence milestone, not training. The
rule of the milestone is

```text
REMOVE ONLY HOST OUTPUT WORK. The game-facing frame stays byte-for-byte the same.
```

Nothing in M6 changes the M1c action contract, the M1d protocol version, the
M3 Gym domain, Track 1, `btt_reward_v1`, the 300-unit position-delta
default, or the two completion clocks (`completion_time_passed = 446`,
`completion_input_tick = 447`, never combined, never derived from each
other). No RNG work of any kind. No binary IPC, shared memory, in-process
reset, save states, camera, capture or video work.

## Files

| File | Role |
| --- | --- |
| `port/rl/rl.h` | declarations and contract of the mode: `rlNoRenderIsEnabled()`, `rlStepHostWaitParked()` |
| `port/rl/rl_boot.cpp` | parses `SSB64_RL_NO_RENDER`; effective only with effective interactive stepping; log lines |
| `port/rl/rl_step.cpp` | `rlStepHostWaitParked()`: the bounded condition-variable wait of a parked host iteration |
| `port/rl/rl_transport.cpp` | additive `no_render` boolean in the `status` response (configuration, not an observation) |
| `port/gameloop.cpp` | the two opt-in branches in `PortPushFrame()`: discard the staged display list instead of rendering and presenting it; wait instead of the parked idle present; no 0-submit idle present |
| `rl/m6_equivalence_regression.py` | permanent semantic-equivalence regression, normal host vs no-render host, every step and every authoritative field |
| `rl/m5_smoke.py`, `rl/train_m5.py` | `--child-env KEY=VALUE` so every launched process (including the PPO smoke) can run in the mode |
| `docs/rl_throughput_m6_baseline.json` | `rl/tools/bench.py` report of the no-render mode (1..8 processes) on the M6 executable |
| `docs/rl_throughput_m6_normal_reference.json` | the same benchmark, normal visual mode, same executable, same session |
| `docs/rl_throughput_m6_experiments.json` | attribution experiments (not implemented as features) and the equivalence summary |
| `docs/rl_transport_m1d.md` | the `status` row gains the `no_render` field |

`decomp/`, `libultraship/`, `torch/`, CMake, `rl/battleship_client.py`,
`rl/battleship_process.py`, `rl/battleship_env.py`, `rl/run_artifacts.py`,
`rl/btt_learning.py`, `rl/tools/bench.py` and every M1e/M2/M3/M4 smoke or
regression script are unchanged. The submodule pointers are unchanged.
Nothing was committed or pushed.

## Phase A: the measured step and where its time went

The call path of one interactive step (traced, not inferred from names):

1. transport worker: `rlStepSubmit` (WaitingForAction -> ActionReady) and
   `rlStepWait` on the M1c condition variable.
2. main thread, `PortPushFrame()`: `rlStepHostUpdate()` reports the gate
   open; cheats; `HandleEvents()` (Win32 message pump of the DXGI backend);
   `port_vi_simulate_vblank()`; VRETRACE posted; `GamePreUpdateEvent`.
3. `port_resume_service_threads()`: scheduler round, controller thread
   (`syControllerThreadMain`, the BTT read consumes tick T through
   `rlStepControllerRead`), audio thread, game thread (fighter, stage,
   targets, timer), display list built and submitted through
   `osSpTaskStartGo` -> `port_submit_display_list()` (the pointer is only
   staged; the SP/DP completion is queued for the next vblank rotation).
4. `port_drain_pending_display_list()`: `Fast3dWindow::DrawAndRunGraphicsCommands`
   -> Fast3D interpreter walk of the display list -> `Interpreter::EndFrame`
   -> `GfxWindowBackendDXGI::SwapBuffersBegin` (waitable timer to the next
   1/60 s slot, then a spin, then `Present(vsync)`) -> `SwapBuffersEnd`
   (wait on the frame-latency waitable object).
5. `GamePostUpdateEvent` -> M1b capture -> `rlStepOnObservation` pairs the
   result (ObservationReady) -> worker wakes -> response.
6. Every following parked iteration: `HandleEvents()` then
   `port_present_idle_frame()` -> `PresentCurrentFramebuffer()` -> the same
   `EndFrame` / `SwapBuffersBegin` / `SwapBuffersEnd` path.

**Root cause of the pacing.** Two presentation points per step, both paced
by the DXGI backend's software frame limiter in `SwapBuffersBegin`
(`mTargetFps` = 60, waitable timer plus spin, independent of the vsync
console variable) followed by a vsynced `Present` and the frame-latency
wait: the frame's own present after the display-list walk (13.6 ms median)
and the parked idle present of the cached framebuffer (16.2 ms median of
the interval lands in `submit_to_gate_open`). The game update of the tick is
0.07 ms. Disabling vsync alone would leave the software limiter in place, as
M4 anticipated.

**Why the render path can be skipped without touching the simulation.**

- Fast3D only reads the display list and the game memory it references; it
  writes nothing back. The staged pointer is game-owned memory that the next
  tick reuses anyway.
- The SP/DP task completion is queued by `osSpTaskStartGo` before any
  rendering happens; the display-list cost model that can lengthen the
  deferral (`port_get_last_dl_defer_n`) is gated by
  `port_scene_wants_freeze_simulation`, which excludes bonus stages, so in
  BTT the deferral is always 1 with or without a walk.
- Audio output (`portAudioSubmitFrame` -> WASAPI `DoPlay`) never blocks: it
  clips to the available buffer and returns; `osAiSetNextBuffer` is a stub.
- Wall-clock reads (`osGetCount`) in the scheduler, taskman and audio code
  only feed diagnostic deltas; the BTT timer counts VRETRACEs.
- The window's message pump is what keeps the close button and the
  deferred clean exit (`Window::Close()` -> `WindowIsRunning()` false)
  working; it does not need a painted frame.

**Baseline reproduced before optimising** (normal mode, this build, same
session, `docs/rl_throughput_m6_normal_reference.json`): raw step median
33.31 ms = 30.03 ticks/s, `submit_to_gate_open` 16.23 ms,
`gate_open_to_consume` 2.94 ms, `consume_to_logic_done` 0.07 ms,
`logic_done_to_observation` 13.63 ms. This equals the M4 baseline
(33.30 / 16.24 / 2.99 / 0.07 / 13.60), so the M6 build did not change the
normal path.

## The mode: `SSB64_RL_NO_RENDER=1`

```text
SSB64_RL_BTT=1 SSB64_RL_STEP=1 SSB64_RL_PORT=<port> SSB64_RL_NO_RENDER=1
```

Effective only when interactive stepping is effective (`SSB64_RL_STEP=1`
and no `SSB64_BTT_INPUT`). Otherwise it is ignored with the log line
`SSB64 RL NoRender: SSB64_RL_NO_RENDER=1 ignored: interactive stepping is
not effective; normal rendering and presentation kept`, so replay mode keeps
its precedence and ordinary play is untouched (verified below). Unset, the
visual path is the default and is the pre-M6 frame verbatim.

What it changes, all in `PortPushFrame()` and all host-side:

1. **Unparked frame**: `port_discard_pending_display_list()` instead of
   `port_drain_pending_display_list()`. The game built and submitted the
   display list exactly as before; only the Fast3D walk and the present that
   would follow are omitted. `GamePostUpdateEvent` still fires at the same
   point of the frame, so the observation timing is unchanged.
2. **No 0-submit idle present**: every frame is a 0-submit frame by
   construction, and none is presented.
3. **Parked iteration**: instead of `port_present_idle_frame()` (a paced
   present of the cached framebuffer) the main thread calls
   `rlStepHostWaitParked(5)`: a bounded wait on the existing M1c condition
   variable that returns immediately when `rlStepSubmit` opens the gate,
   when the deferred exit is recorded, or when shutdown begins. The 5 ms
   bound only sets how often the window's message pump runs while nobody is
   stepping; a submitted action never waits it out. This replaces a present
   with a sleep rather than a spin, which is what keeps idle processes off
   the CPU in the multi-process case.

What stays alive: the window and the DirectX 11 / DXGI backend, the message
pump every iteration, the audio device, the transport, the watchdog. The
window is simply never repainted (it shows whatever the desktop composes
for an unpainted client area). This is therefore a **no-render, no-present,
no-pacing mode with a live but unpainted window**, not a headless process:
it still needs a display session and the graphics backend to initialise.

What it does not touch: the M1c state machine and its transitions, the BTT
controller callback, the controller read that consumes the action on tick
T, the game update, the M1b capture, `step_count`, the BTT timer, the
targets, fighter physics and status, the terminal result, the result JSON,
the artifact recorder, the deferred clean exit, process restart, the
protocol (version stays 1; `status` gains one additive boolean).

Log evidence in `ssb64.log`: `SSB64 RL: enabled ... no_render=1` and
`SSB64 RL NoRender: training no-render mode enabled: display lists
discarded, no presents, no presentation pacing, parked host waits on the
step condition variable`. Protocol evidence: `status` -> `"no_render": true`.

### Python configuration

No new configuration path: the mode is one entry in the existing M2
`LaunchConfig.extra_env`, which `build_child_env` copies into the child.
`rl/tools/bench.py` already had `--child-env`; `rl/m5_smoke.py` and
`rl/train_m5.py` gained the same `--child-env KEY=VALUE` option (repeatable;
`train_m5.py` records it in `config.json` through `TrainingConfig.extra_env`;
a case-specific `SSB64_MAX_FRAMES` is layered on top of it, never instead).

```text
python rl/tools/bench.py --child-env SSB64_RL_NO_RENDER=1 --out <json>
python rl/m5_smoke.py --child-env SSB64_RL_NO_RENDER=1
python rl/train_m5.py --child-env SSB64_RL_NO_RENDER=1
python rl/m6_equivalence_regression.py [--repeats N] [--out <json>]
```

## Phase C: semantic equivalence (`rl/m6_equivalence_regression.py`)

Permanent regression. It launches, with the M2 lifecycle, one normal
process and N no-render processes (`--repeats`, default 1), reads
`status.no_render` to prove which kind each one is, takes the M3 `observe`
snapshot at fresh WaitingForAction, feeds the 468-row authoritative replay
through the raw M1d client with the M1e per-row checks, records every step
result, and compares:

- the initial observations (input tick 0), and
- for every one of the 447 submitted steps: `state`, `step_count`,
  `consumed_tick`, and all 16 remaining observation fields
  (`observation_schema`, `input_tick`, `time_passed`, `game_status`,
  `btt_active`, `targets_remaining`, `fighter_valid`, `position_x`,
  `position_y`, `air_velocity_x`, `air_velocity_y`, `ground_velocity_x`,
  `facing_direction`, `ground_air_state`, `fighter_status_id`,
  `jumps_used`), exact equality and same type, no tolerance.

Excluded field: `host_frame` only, because it is the host's
`GamePostUpdateEvent` counter and diagnostic by the M1b contract. It is
still recorded and reported as `host_frames_identical`; it was identical
(511 at the terminal step) in every run. No other field is excluded.

The no-render trace must additionally satisfy the frozen contract on its
own (447 actions, last `consumed_tick` 446, `completion_time_passed` 446,
`completion_input_tick` 447, `step_count` 447, `targets_remaining` 0,
EpisodeEnded, exit code 0, 21 rows unsent, zero `large_position_delta`
events from the default 300-unit detector), and the canonical M4 artifact
(`rlaction_native_v1`, 447 rows) recorded from the normal trace is read back
and resubmitted through a third, fresh no-render process with
`run_artifacts.resubmit_actions`; its results must equal the no-render trace
field for field. The first divergent step index and field would be printed;
none occurred.

Results (three separate invocations on the final executable, `--repeats 2`
in the regression suite, `--repeats 2` and `--repeats 1` earlier):

| Trace | actions | last consumed_tick | completion_time_passed / completion_input_tick | step_count | targets | state | exit | rows unsent | anomaly events | host_frame |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| normal | 447 | 446 | 446 / 447 | 447 | 0 | EpisodeEnded | 0 | 21 | 0 | 511 |
| no_render (each repeat) | 447 | 446 | 446 / 447 | 447 | 0 | EpisodeEnded | 0 | 21 | 0 | 511 |
| artifact replay through no_render | 447 | 446 | 446 / 447 | 447 | 0 | EpisodeEnded | 0 | 21 | n/a | 511 |

Every comparison: equivalent on all 447 steps plus the initial observation,
`host_frames_identical = true`, result JSON equal to the frozen values,
`BattleShip.exe` count 0 before and after. Informational only: the stepping
phase took 14.9 s in normal mode and 1.46 to 1.49 s in no-render mode.

## Phase D: single-process performance

Environment: Windows 11 (10.0.26200), Intel64 Family 6 Model 158, 6 logical
CPUs, Python 3.13.2, gymnasium 1.3.0, numpy 2.5.3, US Release
`build-us/Release/BattleShip.exe` built from this tree with MSVC (`cmake
--build build-us --config Release`, exit 0; sha256 `c284e70de225...`, git
`12e969f` + the uncommitted M6 changes), DirectX 11 backend, WASAPI audio,
window 640x480 visible, frame interpolation off, vsync console variable at
its default. A Raphnet N64 USB adapter is attached to this machine (this
matters below). Both benchmark runs used the defaults (5 launches, 30
warm-up + 600 measured steps, 500 RTT samples, 10 s windows, 10 reliability
episodes) with `SSB64_RL_TIMING=1` in the child. Normal:
`python rl/tools/bench.py --max-processes 5 --out docs/rl_throughput_m6_normal_reference.json`
(338 s). No-render: `python rl/tools/bench.py --child-env SSB64_RL_NO_RENDER=1
--max-processes 8 --out docs/rl_throughput_m6_baseline.json` (207 s).

Startup to fresh (5 launches each, all fresh):

| Mode | min | median | mean | p95 | max (s) | stage medians: Popen / transport / fresh |
| --- | --- | --- | --- | --- | --- | --- |
| normal | 3.160 | 3.379 | 3.373 | 3.547 | 3.547 | 0.267 / 2.041 / 1.215 |
| no-render | 2.300 | 2.499 | 2.532 | 2.732 | 2.732 | 0.011 / 2.048 / 0.355 |

The boot to Go (the `transport -> fresh` stage) drops from 1.2 s to 0.36 s
because boot frames are no longer paced either; the 2.0 s before the
transport is process start and asset loading, unchanged.

Sequential stepping, one process each (600 measured steps):

| Metric | normal | no-render | ratio |
| --- | --- | --- | --- |
| raw M1d step median (ms) | 33.31 | 3.12 | 10.7x |
| raw step min / p95 / p99 / max (ms) | 32.69 / 33.59 / 33.83 / 33.92 | 2.40 / 3.73 / 4.03 / 4.42 | |
| native ticks/s (raw) | 30.03 | 316.9 | 10.6x |
| M3 `env.step()` median (ms) | 33.33 | 3.19 | 10.4x |
| M3 native ticks/s | 30.00 | 308.4 | 10.3x |
| Gym wrapper overhead, derived (ms) | 0.025 | 0.074 | |
| child CPU per step, `GetProcessTimes` (ms) | 7.54 | 0.69 | |
| working set after stepping (MiB) | 132.1 | 110.4 | |

Native attribution (medians, 600 steps with stamps, every step served by
one host iteration):

| Segment | normal (ms) | no-render (ms) | contains |
| --- | --- | --- | --- |
| request_to_submit | 0.02 | 0.02 | parse, validate, `rlStepSubmit` |
| submit_to_gate_open | 16.23 | 0.01 | normal: remainder of the parked idle present; no-render: condition-variable wake |
| gate_open_to_consume | 2.94 | 2.68 | cheats, message pump, vblank, VRETRACE, scheduler and controller thread up to the read |
| consume_to_logic_done | 0.07 | 0.07 | the game update |
| logic_done_to_observation | 13.63 | 0.00 | normal: Fast3D walk + paced present; no-render: display list discarded |
| observation_to_collect | 0.03 | 0.02 | worker wake |
| collect_to_response | 0.03 | 0.03 | response object |
| native total | 33.00 | 2.86 | |

Protocol round trips are unchanged (medians, ms): ping 0.102 / 0.100,
status 0.110 / 0.105, observe 0.131 / 0.116 (normal / no-render). Python
JSON per step 10.2 us in both. Full 447-action replay wall time: 14.89 s
median in normal mode (10 reliability episodes, 14.89 to 14.91) and 1.49 s
in no-render mode (1.47 to 1.50); reliability 10/10 in both modes, no
failure category hit, every episode 447 / 446 / 446 / 447 / exit 0.

Measured fact: the render, present and pacing work is gone
(`logic_done_to_observation` 0.00 ms, `submit_to_gate_open` 0.01 ms). What
remains is the 2.7 ms of `gate_open_to_consume`, which is attributed in the
next section but not removed by M6.

## Phase E: process count

Independent processes stepped concurrently from one Python driver (one
thread per process, 10 s window, the M4 action pattern), every level with
all processes fresh, no error, no leak, machine-wide count back to 0.
Efficiency is aggregate / (N x the same mode's N = 1 aggregate).

| N | normal aggregate (steps/s) | normal per-process median | normal efficiency | no-render aggregate | no-render per-process median | no-render efficiency | no-render latency median / p95 / p99 (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 30.0 | 30.0 | 100 % | 312.8 | 312.8 | 100 % | 3.15 / 3.80 / 4.14 |
| 2 | 60.0 | 30.0 | 100 % | 372.7 | 186.8 | 60 % | 5.11 / 8.97 / 11.92 |
| 3 | 90.0 | 30.0 | 100 % | 431.1 | 142.8 | 46 % | 6.92 / 13.12 / 18.80 |
| 4 | 109.7 | 27.6 | 91 % | 457.1 | 114.8 | 37 % | 7.69 / 18.29 / 26.16 |
| 5 | 134.7 | 27.1 | 90 % | 485.1 | 96.2 | 31 % | 8.28 / 25.97 / 41.22 |
| 6 | | | | 491.1 | 81.1 | 26 % | 9.52 / 32.23 / 48.72 |
| 7 | | | | 491.9 | 68.9 | 22 % | 10.51 / 40.98 / 52.35 |
| 8 | | | | 495.7 | 60.3 | 20 % | 11.84 / 48.28 / 52.95 |

Working set 109 to 110 MiB per no-render process at every level; the
driver's own CPU under 1 s per level. CPU utilisation of a single no-render
process while stepping flat out is about 22 % of one core by
`GetProcessTimes` (0.44 s over a 2.0 s window), i.e. most of the remaining
3.1 ms step is waiting, not computing.

Interpretation (not a measured fact): the no-render aggregate saturates at
about 490 steps/s from N = 5 on, which is one step every 2.0 ms machine-wide.
That is the signature of a resource serialised across processes with about
2 ms of occupancy per step, not of CPU exhaustion (six processes at 22 % of a
core each would fit on this machine). The attribution below identifies it.

## Residual attribution: the native controller adapter (experiment, not implemented)

A temporary per-thread timer (steady-clock accumulation around every
coroutine resume in `port_resume_service_threads` and around the
`PortPushFrame` segments; added, measured, reverted, never committed, the
final executable does not contain it) gave, per unparked frame, averaged
over 500 frames of the baseline replay:

| Slot | normal (us) | no-render (us) |
| --- | --- | --- |
| thread 3, scheduler | 4.9 | 4.2 |
| thread 4, audio | 328.1 | 304.7 |
| thread 6, controller (`syControllerThreadMain`) | 2605.1 | 2558.4 |
| thread 5, game | 403.3 | 375.4 |
| message pump | 6.5 | 5.4 |
| vblank + VRETRACE + pre-update | 1.8 | 0.9 |
| display-list drain (render + present) | 13663.1 | 6.9 (discard) |
| whole `PortPushFrame` | 17025.3 | 3265.7 |

The controller thread costs 2.6 ms per frame in both modes. Two experiments
against an isolated copy of `build-us/Release` in a scratch directory (only
the copied `BattleShip.cfg.json` was edited; the repository's executable and
config were never modified; details and full numbers in
`docs/rl_throughput_m6_experiments.json`):

| Experiment | raw step median (ms) | ticks/s | gate_open_to_consume median (ms) | N = 1..6 aggregate (steps/s) |
| --- | --- | --- | --- | --- |
| no-render, WASAPI audio (the mode as shipped) | 3.12 | 317 | 2.68 | 313 / 373 / 431 / 457 / 485 / 491 |
| no-render, `Window.AudioBackend = null` | 3.11 | 317 | 2.72 | 315 / 385 / 478 / 474 / 483 / 494 |
| no-render, `gControllers.Raphnet.Enabled = 0` | 0.48 | 1955 | 0.24 | 1780 / 3491 / 4966 / 6126 / 7197 / 7428 |

Measured facts: the audio output path is not the residual; disabling
libultraship's native Raphnet adapter support removes 2.4 ms of the 2.7 ms
pre-read segment, the single-process step falls to 0.48 ms median (about
1950 ticks/s, 65x the visible-window baseline, 6.5x the shipped no-render
mode), and the process-count curve becomes 98 %, 93 %, 86 %, 81 %, 70 % of
ideal at N = 2..6 (7428 steps/s at N = 6) with working sets unchanged.
Interpretation: `RaphnetTransport` performs a USB HID feature-report round
trip on every controller read (the libultraship log shows the adapter
opened with `SUSPEND_POLLING(1)`, native SI access, and a poll per read);
one such round trip is on the order of a USB frame, and the Windows HID
host stack serialises them across processes, which matches both the 2.6 ms
per frame and the 490 steps/s machine-wide ceiling. It also explains the one
anomalous process seen in an earlier no-render sweep at N = 7 (1687 steps/s
at 0.54 ms while its six siblings stepped at about 70 steps/s: the sweep's
startups were slow at that level and that process evidently did not obtain
the adapter).

Why M6 does not ship a per-process switch for it:

- the only existing knob is the console variable
  `gControllers.Raphnet.Enabled` in `BattleShip.cfg.json`, which is shared by
  every process in the executable directory and would also change normal
  play on the machine;
- an in-memory override from `port/` could be persisted back into the user's
  config by libultraship's console-variable save paths;
- an environment override next to the existing `SSB64_RAPHNET_MOCK` would be
  a `libultraship` submodule change, which M6 was told to avoid.

It is machine-specific: a training host without a native adapter attached
(or with `gControllers.Raphnet.Enabled = 0` set deliberately for a training
session, or with the adapter unplugged) already gets the 0.5 ms step with
the shipped no-render mode. This is the first recommendation for M7.

## Phase F: M5 PPO smoke under the no-render mode

`python rl/m5_smoke.py --child-env SSB64_RL_NO_RENDER=1`: 8/8 PASS,
`BattleShip.exe` 0 before and after (run twice on the final executable; the
second run after `launch_config()` also learned `--child-env`, so every game
case, not only the M5 learning stack, ran in the mode). `ppo_smoke`:
PPO/MlpPolicy, 512 timesteps, max_episode_steps 128, n_steps 128, batch 32,
2 epochs: 5 episodes started / 4 finished, 4 rollouts, 8 SB3 updates
(32 gradient steps), parameters changed, checkpoints at 256 and 512 steps,
final model saved, reloaded, 20 inference steps from the reloaded model with
every action a legal Track 1 pair and consumed ticks 0..19, 3 artifacts
preserved (`new_best_target_count`, 2 periodic) with canonical native
triples that all map back to Track 1 (`native_to_track1`), evaluation
artifact preserved manually; train wall 14.97 s against 34.69 s for the
same case in normal mode the same session (case walls 17.8 s and 38.7 s;
the M5 document reported 34.3 s). `baseline_reward` (the exact 7.43 s trajectory with `btt_reward_v1`,
return 19.553): 5.0 s in the mode against 19.0 s in normal mode.
`failure_truncation` (`SSB64_MAX_FRAMES=600` layered on top of the mode):
PASS. No claim about learning quality is made or supported by this.

## Regression results (final executable, sequential, `SSB64_RL_TIMING` unset)

| Suite | Command | Result |
| --- | --- | --- |
| M6 equivalence | `python rl/m6_equivalence_regression.py --repeats 2` | PASS (see Phase C) |
| M5 smoke, no-render | `python rl/m5_smoke.py --child-env SSB64_RL_NO_RENDER=1` | 8/8 PASS |
| M5 smoke, normal | `python rl/m5_smoke.py` | 8/8 PASS |
| M4 smoke | `python rl/m4_smoke.py` | 5/5 PASS (`baseline_roundtrip` 447 / 446 / 447, zero events at 300) |
| M3 smoke | `python rl/m3_gym_smoke.py` | 9/9 PASS (`replay_complete`, `env_checker`) |
| M2 restart | `python rl/m2_restart_regression.py` | 3/3 episodes, 446 / 447, exit 0, result JSON 10 / 446 / 447, PASS |
| M2 lifecycle | `python rl/m2_lifecycle_smoke.py` | 6/6 PASS |
| M1e, hand-launched normal process | `python rl/m1e_replay_regression.py --port 52101` | PASS 447 / 446 / 447 / 446, 21 rows after completion, result JSON 10 / 446 / 447 |
| M1e, hand-launched no-render process | `python rl/m1e_replay_regression.py --port 52102` | PASS, same values |
| native replay, checksum run | `SSB64_RL_BTT=1 SSB64_BTT_INPUT=<mario_743.btti> SSB64_MAX_FRAMES=1500` | `COMPLETE input_tick=447 time_passed=446`, `input exhausted frames=468 actual_checksum=0x93E9EFB4`, result JSON clear 10 / 446 / 447, host_frames 511 |
| native replay precedence | as above plus `SSB64_RL_EXIT_ON_END=1 SSB64_RL_STEP=1 SSB64_RL_NO_RENDER=1 SSB64_RL_PORT=52103` | log `step=0 transport_port=0 no_render=0` and `SSB64_RL_NO_RENDER=1 ignored`; replay completes 447 / 446, clean exit at frame 511, result JSON identical |

`BattleShip.exe` count was 0 after every suite, after both benchmarks and
after the hand-launched runs. `git diff --check` clean. Linux was not built
or run; Linux CI was not modified.

## Recommendation for M7 (not implemented here)

1. Run training processes with `SSB64_RL_NO_RENDER=1` (the M2 `extra_env`
   entry; `train_m5.py --child-env SSB64_RL_NO_RENDER=1`).
2. On this machine, decide how the Raphnet adapter is kept away from training
   processes before choosing a process count. With the adapter polled, the
   aggregate is flat at about 490 steps/s from N = 5 on and N = 3 already
   reaches 431 steps/s; more processes only add latency. With the adapter
   disabled (isolated-copy experiment) the curve is near-linear to N = 5
   (7197 steps/s, 81 %) and still rising at N = 6 (7428 steps/s, 70 %), on a
   six-logical-CPU machine that also has to run the learner. Recommended
   starting point for M7 experiments: **N = 4 processes** with the adapter
   disabled (6126 steps/s at 86 % efficiency, leaving two logical CPUs for
   the Python learner), remeasured with the learner in the loop; **N = 3**
   if the adapter must stay active. The M4 figure of 91 % at N = 5 no longer
   describes the optimised path.
3. If a per-process adapter switch is wanted, the smallest option is an
   environment override in `ControlDeck::PreInitRaphnet` next to the
   existing `SSB64_RAPHNET_MOCK` (a `libultraship` change on the user's fork),
   validated with the M6 equivalence regression exactly as the no-render
   mode was.

## Limitations

- Not headless: a window and the DirectX 11 backend are still created and
  the process needs a display session; the window is unpainted.
- The residual 2.7 ms per step and the 490 steps/s ceiling are properties of
  this machine's attached adapter, not of the mode; numbers on another
  machine will differ in that segment.
- `host_frame` values are identical between the modes today, but only the
  authoritative fields are asserted; a future change that alters boot frame
  counts would show up as a reported, not asserted, difference.
- The console-variable save that `port.cpp` schedules at frame 60 through
  the GUI never runs in the mode (no GUI frame is drawn); nothing depends on
  it during training, and the visual path is unaffected.
- `SSB64_MAX_FRAMES` counts parked iterations as before; in the mode a
  parked iteration lasts up to 5 ms instead of one present interval, so a
  frame cap expires sooner in wall time (its meaning in frames is unchanged).
- The `no_render` field is in `status` only; `BattleShipClient.Status` does
  not expose it (the regression reads the raw response), so the frozen
  client API is untouched.
- Benchmarks are single-machine, single-session; the multi-process
  experiment with the adapter disabled used an isolated executable copy and
  an 8 s window, and one of the isolated-copy audio-null sweeps had a
  transport failure at N = 4 (the level was reported with 3 ready processes
  and the experiment was not repeated).

## Rollback / disable

Leave `SSB64_RL_NO_RENDER` unset (or anything but `1`): the frame loop is
the pre-M6 path verbatim. To remove the feature, revert the M6 hunks in
`port/gameloop.cpp`, `port/rl/rl.h`, `port/rl/rl_boot.cpp`,
`port/rl/rl_step.cpp` and `port/rl/rl_transport.cpp` (the `status`
field is additive and clients ignore it) and drop the `--child-env`
plumbing in `rl/m5_smoke.py` / `rl/train_m5.py`; `rl/m6_equivalence_regression.py`
then fails at its `no_render` check by design.

## Commands run

```text
cmake --build build-us --config Release                       (twice: after the M6 edits; after reverting the temporary profile)
git diff --check
python rl/m6_equivalence_regression.py --repeats 2 --out <json>
python rl/tools/bench.py --child-env SSB64_RL_NO_RENDER=1 --max-processes 8 --out docs/rl_throughput_m6_baseline.json
python rl/tools/bench.py --max-processes 5 --out docs/rl_throughput_m6_normal_reference.json
python rl/tools/bench.py --only step,multiprocess --max-processes 6 --mp-seconds 6 --exe <isolated copy, audio null> --child-env SSB64_RL_NO_RENDER=1
python rl/tools/bench.py --only step --exe <isolated copy, Raphnet.Enabled=0> --child-env SSB64_RL_NO_RENDER=1
python rl/tools/bench.py --only multiprocess --max-processes 6 --mp-seconds 8 --exe <isolated copy, Raphnet.Enabled=0> --child-env SSB64_RL_NO_RENDER=1
python rl/m5_smoke.py --child-env SSB64_RL_NO_RENDER=1
python rl/m5_smoke.py
python rl/m4_smoke.py
python rl/m3_gym_smoke.py
python rl/m2_restart_regression.py
python rl/m2_lifecycle_smoke.py
python rl/m1e_replay_regression.py --port 52101      (hand-launched normal process, no SSB64_RL_EXIT_ON_END)
python rl/m1e_replay_regression.py --port 52102      (hand-launched SSB64_RL_NO_RENDER=1 process)
build-us/Release/BattleShip.exe with SSB64_RL_BTT=1 SSB64_BTT_INPUT=<replay> SSB64_MAX_FRAMES=1500            (checksum run)
build-us/Release/BattleShip.exe with SSB64_RL_BTT=1 SSB64_BTT_INPUT=<replay> SSB64_RL_EXIT_ON_END=1 SSB64_RL_STEP=1 SSB64_RL_NO_RENDER=1 SSB64_RL_PORT=52103   (precedence run)
```

## Not in M6

No binary or shared-memory IPC, no protocol change (version 1, one additive
`status` field), no in-process reset, no save states, no serious PPO
training, no reward or curriculum change, no new action space, no camera,
capture or video work, no libultraship or torch change, no submodule pointer
change, no adapter switch, no RNG inspection, logging, control, comparison
or hashing, no change to the 300-unit threshold or to the 446 / 447
contract.
