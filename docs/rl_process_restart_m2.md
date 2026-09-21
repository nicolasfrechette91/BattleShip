# RL M2: process-restart episode management

M2 automates the OS-process lifecycle around the frozen M1c stepping, M1d
transport and M1e replay checks. Python owns the process; the game owns its
state. There is no in-process reset, no native reset command, no save state and
no new transport operation. A fresh episode is, by definition:

```text
fresh episode
=
fresh BattleShip process
+ isolated files (save, result JSON, process log)
+ new M1d connection
+ native state WaitingForAction
+ step_count == 0
```

A second episode is always a second OS process. `EpisodeEnded` is terminal for
the process that reached it; nothing ever takes a process from `EpisodeEnded`
back to `WaitingForAction`. M3 will use exactly this restart as its reset.

No C, C++, decomp, libultraship or torch file changed for M2. Standard library
only.

## Files

| File | Role |
| --- | --- |
| `rl/battleship_process.py` | lifecycle: launch configuration, unique episode paths, child environment, port allocation, `subprocess.Popen` ownership, two-stage startup, fresh-state gate, failure classification, clean-exit wait, terminate/kill cleanup, context manager |
| `rl/m2_restart_regression.py` | permanent regression: N consecutive fresh processes (default 3) fed `tas_input_2/mario_743.btti` with the M1e checks, result JSON validated per process |
| `rl/m2_lifecycle_smoke.py` | failure-path checks: startup failure, startup timeout, readiness timeout, abort mid-episode, premature exit, environment isolation |

Reused unchanged: `rl/battleship_client.py` (protocol 1 client),
`rl/btti_replay.py` (replay parser), `rl/m1e_replay_regression.py`
(`check_step`, `check_completion`, the frozen constants).

## Lifecycle of one episode

```text
Preflight
    executable and working directory exist
    unique per-episode directory (tempfile.mkdtemp under the run root)
    loopback port: OS-allocated (bind to port 0, then released) or a caller
        port verified free by an exclusive test bind
    child environment built from os.environ.copy()

launch NEW BattleShip process
    cwd = executable directory (runtime assets, ./mods probe, cwd fallbacks)
    stdin = DEVNULL, stdout + stderr = <episode dir>/battleship_stdout.log

Stage 1: transport
    retry connect to 127.0.0.1:<port> until the startup deadline
    every attempt first checks Popen.poll(): an exited child fails at once
    -> startup_failure (exit code kept) or startup_timeout

Stage 2: native readiness
    poll the non-consuming M1d status until
        state_name == "WaitingForAction" and can_step and step_count == 0
    Inactive is tolerated while the game boots
    any other state is refused immediately -> not_fresh
    deadline -> readiness_timeout; child exit -> startup_failure
    no action is ever sent to test readiness

episode: caller steps with BattleShipClient (M1d / M1c, unchanged)
    a failed request is classified with classify_step_failure():
        process gone            -> premature_exit (exit code kept, 0 included)
        request deadline passed -> episode_timeout
        connection dropped      -> transport_failure
        server rejected it      -> request_rejected

finish(terminal EpisodeEnded result)
    close the client
    wait (bounded) for the native clean exit: SSB64_RL_EXIT_ON_END=1 is the
        existing deferred M1c exit, performed after the final result was
        collected, gate still closed; no shutdown command exists or is sent
    require exit code 0            else exit_failure / exit_timeout
    load and shape-check the result JSON, cross-checked against the terminal
        observation (each clock against its own counterpart)
                                    else result_invalid
    -> completed

close()  (context manager exit; idempotent; runs on every path)
    close the client if connected
    process already gone -> already_exited
    else terminate(), bounded wait -> terminated
    else kill(), bounded wait      -> killed
    else                           -> cleanup_failure (raised)
```

`completed` is never inferred from an exit code alone. It requires the fresh
state proved, the terminal `EpisodeEnded` step result collected, exit code 0
through the expected path and a valid native result JSON. The regression adds
the frozen baseline assertions on top.

## Child environment

Built per episode from `os.environ.copy()`; the parent's environment is never
mutated. Set explicitly for every episode:

```text
SSB64_RL_BTT=1
SSB64_RL_STEP=1
SSB64_RL_PORT=<episode port>
SSB64_SAVE_PATH=<episode dir>/ssb64_save.bin
SSB64_RL_RESULT_PATH=<episode dir>/result.json
SSB64_RL_EXIT_ON_END=1
```

Removed from the child: `SSB64_BTT_INPUT` (a configured replay takes
precedence over interactive stepping and disables the transport, see
`port/rl/rl_boot.cpp`) and `SSB64_MAX_FRAMES` (the clean-exit debug aid in
`port/port.cpp` would end the episode early). `LaunchConfig.extra_env` is
applied before the mandatory settings, so a caller can pass the frame cap on
purpose (the smoke test does) but can never override the six settings above
or re-introduce `SSB64_BTT_INPUT`.

Save, result and process log paths are unique per episode; nothing is reused.
The native `ssb64.log` is written by the game to its app-data directory
(`%APPDATA%\BattleShip\ssb64.log` on Windows) and is overwritten per run; it
is not per-episode and M2 does not relocate it. Consult it for a native bind
failure or boot problem after a `startup_timeout`.

## Ports

The port is asked from the OS (bind to port 0 with an exclusive-use socket,
read the number, close the socket) and passed through `SSB64_RL_PORT`. No
reservation socket stays open, so the native bind can succeed. A caller-fixed
port is checked the same way (an exclusive test bind must succeed) so M2 never
launches beside a stale listener and never connects to one; if a stale process
is reached anyway, its state is not `Inactive` or fresh and the episode fails
as `not_fresh`. A connect probe is deliberately not used: on Windows a closed
loopback port can answer with silence rather than a refusal. The remaining
window between releasing the port and the native bind is accepted; a native
bind failure is logged by the game and surfaces as `startup_timeout`.
Protocol 1 is unchanged; no PID or process identity was added to it.

## Failure categories

| Outcome | Meaning |
| --- | --- |
| `startup_failure` | the process exited (or could not be started) before a fresh episode existed; exit code, executable, working directory, episode directory and log file are reported |
| `startup_timeout` | alive, but the M1d transport never became reachable before the startup deadline |
| `readiness_timeout` | transport connected, still not fresh at the readiness deadline |
| `not_fresh` | transport connected to a state that can never become fresh (`EpisodeEnded`, `Stopping`, `WaitingForAction` with `step_count > 0`, ...) |
| `premature_exit` | fresh episode established, process exited before the terminal `EpisodeEnded` result was collected; a failure even with exit code 0 |
| `episode_timeout` | alive, but a request deadline expired mid-episode |
| `transport_failure` | alive, but the connection failed mid-episode |
| `request_rejected` | alive, the server rejected a request (protocol error or native code) |
| `exit_timeout` | terminal result collected, process still alive at the exit deadline |
| `exit_failure` | terminal result collected, process exited non-zero |
| `result_invalid` | exited 0, but the result JSON is missing, malformed or disagrees with the terminal observation |
| `cleanup_failure` | terminate and kill both left the process alive |
| `completed` | all conditions above met |

## Regression

```text
python rl/m2_restart_regression.py
python rl/m2_restart_regression.py --episodes 5 --run-dir <dir>
```

`--exe` defaults to `build-us/Release/BattleShip.exe` relative to the
repository; `--working-dir` to the executable's directory; `--run-dir` to a
new temporary directory (printed as `run_dir=` at the end). Timeouts:
`--startup-timeout 60`, `--ready-timeout 180`, `--request-timeout 30`,
`--exit-timeout 30`.

For every episode it establishes that the previous process is gone, launches
a new `Popen`, uses a new episode directory, save path, result path, log path
and client connection, and requires `WaitingForAction`, `can_step`,
`step_count == 0` before row 0. It then submits rows one at a time with the
M1e checks (`consumed_tick == i`, `input_tick == i + 1`, `step_count == i + 1`,
frozen observation schema, `btt_active`, `fighter_valid`, `targets_remaining`
within 0..10 and never rising, `time_passed` never falling) and stops at the
first `targets_remaining == 0`, which must be the frozen completion. The last
21 source rows are never sent. Then it waits for the clean exit and validates
the isolated result JSON:

```text
result_schema = 1
outcome = "clear"
targets_broken = 10
completion_time_passed = 446
completion_input_tick = 447
time_passed_final = 446
input_cursor_final = 447
host_frames: present, integer, never compared between runs
```

`446` and `447` are different clocks (in-game timer, input cursor) and are
never derived from each other or combined. No Python checksum exists; all 468
rows and `0x93E9EFB4` remain the native replay regression's job.

Expected output shape:

```text
M2 PASS
episodes=3

episode=1 outcome=completed pid=... fresh_step_count=0 steps=447 last_consumed_tick=446 completion=446/447 targets_remaining=0 final_state=EpisodeEnded exit_code=0 cleanup=already_exited result_json=ok
episode=2 ...
episode=3 ...

source_rows=468
rows_after_completion=21
all_fresh=true
all_processes_exited=true
run_dir=...
```

Exit status: 0 PASS, 1 any episode or invariant failed, 2 unusable replay or
bad usage. A failed episode is fully cleaned up before the next one is
attempted; the run still fails.

## Lifecycle smoke

```text
python rl/m2_lifecycle_smoke.py
python rl/m2_lifecycle_smoke.py child_env startup_failure startup_timeout   # no game needed
```

| Case | Child | Checks |
| --- | --- | --- |
| `child_env` | none | mandatory settings present, `SSB64_BTT_INPUT` removed even when the parent has it, `extra_env` cannot override the episode port or exit flag, parent environment unchanged |
| `startup_failure` | `python -c "sys.exit(3)"` | classified before the startup deadline, exit code 3 kept, log file created, cleanup `already_exited`, `close()` idempotent |
| `startup_timeout` | `python -c "sleep(120)"`, 2 s deadline | classified at the deadline with the child alive, cleanup `terminated` |
| `readiness_timeout` | real game, 0.25 s readiness deadline | transport stage completed, still `Inactive`, game alive at the failure, cleanup `terminated` |
| `abort_mid_episode` | real game | fresh, five neutral steps consume ticks 0..4, context left early, cleanup `terminated`, no result JSON |
| `premature_exit` | real game with `SSB64_MAX_FRAMES=600` via `extra_env` | fresh, neutral steps until the frame cap ends the process, classified `premature_exit` with exit code 0, cleanup `already_exited`, no result JSON |

Nothing native was added for these; the frame cap is the pre-existing
`SSB64_MAX_FRAMES` debug aid.

## Verified (2026-09-21, Windows US Release build, no native change)

`python rl/m2_restart_regression.py` with the default three episodes: PASS.
Each of the three processes (three distinct PIDs, three OS-allocated ports)
was fresh with `step_count = 0` about 3.5 s after launch, consumed 447
actions with last `consumed_tick = 446`, ended in `EpisodeEnded` with
`time_passed = 446`, `input_tick = 447`, `targets_remaining = 0`,
`step_count = 447`, exited on its own with code 0 through the deferred
`SSB64_RL_EXIT_ON_END` path (cleanup found it `already_exited`), and left a
result JSON with `10 / 446 / 447 / 446 / 447` in its own directory. Each
stepping phase took about 14.9 s. 21 source rows stayed unsent per episode.
`host_frames` happened to be 511 in all three and is not asserted. No
BattleShip process remained afterwards.

`python rl/m2_lifecycle_smoke.py`: all six cases PASS. `startup_failure`
kept exit code 3 and found the child already gone; `startup_timeout` fired
after 2.1 s with the child alive and terminated it; `readiness_timeout` had
the transport up after 2.6 s, the game still `Inactive`, and terminated it;
`abort_mid_episode` consumed ticks 0..4, left the context and terminated the
parked game with no result JSON; `premature_exit` was classified after 268
neutral steps with the clean-exit code 0, the process already gone and no
result JSON. Every `close()` was idempotent and every port was free again.

Cross-check: the unchanged `rl/m1e_replay_regression.py` was pointed at a
process launched by `BattleShipEpisode.launch()` + `wait_for_transport()`
(the M2 client closed first, since M1d serves one client at a time). It
reported `M1e PASS` with the same numbers, the process then exited 0 by
itself and wrote its result JSON. The M2 regression itself stops at the
terminal step result and does not repeat M1e's post-completion `status()`
call, because with `SSB64_RL_EXIT_ON_END=1` that call races the deferred
native exit; the terminal step result already carries the same evidence
(`EpisodeEnded`, `step_count = 447`).

## Not in M2

No save states, in-process reset, native reset command, M1c/M1d reset state or
operation, Gymnasium, rewards, PPO or training, Track 1 action mapping,
headless mode, multiprocessing or parallel environments, native lifecycle
change, RNG machinery. M3 is not started.
