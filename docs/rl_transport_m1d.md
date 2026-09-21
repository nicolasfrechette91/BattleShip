# RL M1d: external stepping transport

M1d lets a process outside BattleShip drive the frozen M1c one-action /
one-native-tick stepping primitive. It is integration plumbing only: no
reward, no reset, no launcher, no learning framework.

## Transport decision

Requirements: external process, Windows and Linux, no third-party Python
dependency, no shared-memory complexity, Python does not launch the game yet,
one client, one outstanding step at a time.

What the repository already had:

- `decomp/src/sys/netpeer.c`: a debug UDP peer, compiled only on POSIX
  (`!defined(_WIN32)`), inside the decomp. Not usable on Windows and not a
  place for port-side RL code.
- libultraship: no socket or IPC wrapper.
- `nlohmann/json.hpp`: already compiled into the port target
  (`port/enhancements/Updater.cpp`), so JSON parsing costs no new dependency.
- Python tooling (`tools/`, `debug_tools/`): standard library only.

Decision: one loopback TCP socket (`127.0.0.1:SSB64_RL_PORT`) with plain OS
sockets on the native side and `socket` from the Python standard library on
the client side, carrying newline-delimited JSON. Shared memory, HTTP,
WebSocket and RPC frameworks were rejected for M1d as unnecessary weight;
the transport is small enough to replace later if profiling demands it.

## Enablement

```text
SSB64_RL_BTT=1 SSB64_RL_STEP=1 SSB64_RL_PORT=<1..65535>
```

`SSB64_RL_PORT` is ignored, with a log line, unless interactive stepping is
effective (`SSB64_RL_STEP=1` and no `SSB64_BTT_INPUT`). When unset there is
no socket and no thread, and the replay-only M1a/M1b behaviour is unchanged.
The socket binds loopback only. Windows links `ws2_32` for this.

## Wire protocol, version 1

One JSON object per line, `\n` terminated, UTF-8. Every request and response
carries `"protocol": 1`.

| Request | Success response |
| --- | --- |
| `{"protocol":1,"op":"ping"}` | `{"protocol":1,"op":"ping","ok":true}` |
| `{"protocol":1,"op":"status"}` | `{"protocol":1,"op":"status","ok":true,"state":S,"state_name":"...","can_step":bool,"step_count":N}` |
| `{"protocol":1,"op":"step","buttons":B,"stick_x":X,"stick_y":Y}` | `{"protocol":1,"op":"step","ok":true,"step_schema":1,"state":S,"state_name":"...","step_count":N,"consumed_tick":T,"observation":{...}}` |

`buttons` is a JSON integer 0..65535 holding the native N64 button word
(`RL_BUTTON_*`); `stick_x` / `stick_y` are JSON integers -128..127, passed
through verbatim. Floats, booleans, strings and null are rejected before any
native call. The button rule (zero or exactly one permitted button) is
enforced by M1c itself.

`observation` is `RLObservation` field for field (integers as integers,
floats as JSON numbers): the M1b snapshot of the update that consumed the
action, so `observation.input_tick == consumed_tick + 1`. It appears only in
a successful step response. `status` is non-consuming (it reads
`rlStepGetState()` only, never `rlStepPoll()`) and carries no observation,
so the transport worker consumes M1c step results only and never reads the
main-thread M1b cache. Its `step_count` is that of the last result the
worker collected, which is M1c's counter because the worker is the sole
submitter and collector.

Error response:

```json
{"protocol":1,"op":"step","ok":false,"error":"invalid_action","message":"...","native_code":-3}
```

Protocol errors (`native_code` null): `malformed_request`,
`unsupported_protocol`, `unknown_op`, `missing_field`, `out_of_range`.
Native errors carry the `RL_STEP_ERR_*` code verbatim: `null` (-1),
`disabled` (-2), `invalid_action` (-3), `not_ready` (-4), `busy` (-5),
`episode_ended` (-6), `stopping` (-7), `main_thread` (-8). No error response
advances the game.

## Threading and gating

```text
Python
  -> transport worker thread (port/rl/rl_transport.cpp)
  -> rlStepSubmit() / rlStepWait()          existing M1c API
  -> main-thread host gate (PortPushFrame)   one full native frame
  -> native input tick T consumed
  -> M1b observation at GamePostUpdateEvent
  -> rlStepWait() returns the paired RLStepResult
  -> transport worker -> Python
```

The worker never holds a lock while calling into M1c and never polls for
step completion: `rlStepWait()` blocks on the M1c condition variable. While
Python is idle the host gate stays closed, so `input_tick`, `time_passed`,
fighter state and target state cannot change however long the client waits.

## Connections, disconnects, shutdown

- One listening socket, one client served at a time, requests handled
  sequentially. A second connection waits in the listen backlog until the
  active client disconnects.
- Disconnect while `WaitingForAction`: nothing changes; the game stays
  parked until the next client steps.
- Disconnect after submitting an action but before reading the result: the
  worker still collects the paired result through `rlStepWait()` and sends
  the reply; the closed peer discards it, or the send fails and the
  undelivered result is logged in `ssb64.log`. The state machine has moved
  on, so the next client sees `step_count` advanced by one and its next step
  consumes the following tick (verified: one orphaned step advanced the
  consumed tick by exactly one). No action is duplicated and no native state
  is discarded silently.
- Window close: `main()` calls `rlRuntimeShutdown()` (releases a worker
  blocked in `rlStepWait()` with `stopping`) and then `rlTransportShutdown()`
  (stop flag, join). A connected client receives a `stopping` error and/or
  EOF; the Python client raises `ConnectionClosed`.

## Python

`rl/battleship_client.py` (standard library only):

```python
from battleship_client import BattleShipClient, Button

with BattleShipClient(port=5555) as client:
    client.wait_until_can_step(timeout=60.0)
    status = client.status()
    result = client.step(buttons=Button.NONE, stick_x=0, stick_y=0)
    print(result.consumed_tick, result.observation.input_tick)
```

`rl/m1d_smoke.py` holds the verification tests (`single`, `delayed`,
`errors`, `disconnect`, `baseline`, `shutdown`); see its docstring. The
permanent scripted-replay regression built on this client is
`rl/m1e_replay_regression.py`; see `docs/rl_replay_regression_m1e.md`.
