# RL M3: Gymnasium environment

M3 wraps the validated M1c stepping, M1d transport and M2 process lifecycle
in the smallest clean Gymnasium environment:

```python
from battleship_env import BattleShipBTTEnv

env = BattleShipBTTEnv()                 # launches nothing
observation, info = env.reset()          # NEW BattleShip process, initial observation, tick 0 untouched
observation, reward, terminated, truncated, info = env.step(action)   # exactly one native tick
env.close()                              # idempotent, never leaks the process
```

It is an environment/API milestone. There is no reward design (`reward` is
a documented `0.0` placeholder), no training, no model, no Track 1
discretisation, no headless mode, no binary IPC, no shared memory, no
parallel environments and no performance work. M4 measures before anything
is optimised.

## Files

| File | Role |
| --- | --- |
| `rl/battleship_env.py` | `BattleShipBTTEnv`, the action and observation spaces, the Gym <-> native action conversion |
| `rl/m3_gym_smoke.py` | wrapper validation (nine cases, see below) |
| `rl/requirements.txt` | the RL tooling's Python dependency declaration (`gymnasium>=1.0,<2`) |
| `port/rl/rl.h`, `port/rl/rl_step.cpp` | `rlStepGetLatestObservation()`: pure query, added for the reset observation |
| `port/rl/rl_transport.cpp` | the additive `observe` op (protocol 1 unchanged otherwise) |
| `rl/battleship_client.py` | `BattleShipClient.observe()` and the `Observe` dataclass; nothing existing changed |
| `docs/rl_transport_m1d.md` | one protocol-table row and a paragraph for `observe` |

No decomp, libultraship, torch or CMake file changed. M1a to M1e and M2
behaviour is unchanged: `ping`, `status` and `step` are byte-for-byte the
same, the button rule, pairing, gating, replay precedence and the deferred
exit are untouched, and every existing regression still passes (below).

## Install

The repository had no Python dependency declaration: M1 and M2 are standard
library only. M3 introduces `rl/requirements.txt`, which lists Gymnasium
alone (NumPy comes with it; no ML framework is declared or linked into the
game):

```text
python -m pip install -r rl/requirements.txt
```

Verified with gymnasium 1.3.0 and numpy 2.5.3 on Python 3.13.

## The reset observation: why a native change was necessary

Gymnasium's `reset()` must return the initial observation. The frozen M1d
contract had exactly two observation paths: `status` (non-consuming, carries
no observation, on purpose) and `step` (returns an observation, but consumes
one native tick). Obtaining the initial observation by submitting a neutral
action would consume tick 0 before the agent chose its first action, so it
was ruled out.

Repository evidence showed the snapshot already exists natively:

- `port/rl/rl_observation.cpp` captures an `RLObservation` on every
  `GamePostUpdateEvent` and hands that struct to `rlStepOnObservation()`.
- `rlStepOnObservation()` (`port/rl/rl_step.cpp`) stores it as `sLatest`
  under the M1c mutex *before* evaluating the Inactive -> WaitingForAction
  predicate on that same snapshot. So when `step_count == 0` first becomes
  visible, `sLatest` is the post-update of the update that set Go: the state
  the tick-0 action will act upon, with `input_tick == 0` and
  `time_passed == 0`. `rl.h` already documents this copy as "the state the
  next action will act upon" (the `RL_STEP_READY` case of `rlStepPoll`).
- Nothing exposed it to Python: the transport deliberately never calls
  `rlStepPoll()` (it collects an ObservationReady result, i.e. it is
  consuming in one state), the result JSON is written only on a clear, and
  the activation log line carries a subset of fields.

The smallest non-consuming exposure, and what was implemented:

```text
rlStepGetLatestObservation(RLObservation *out)     port/rl/rl_step.cpp
    copies sLatest under the M1c mutex; returns 1 if a snapshot exists
    touches no state, no result, no gate, no game (mirrors rlStepGetState)

{"protocol":1,"op":"observe"}                       port/rl/rl_transport.cpp
    -> {"protocol":1,"op":"observe","ok":true,"state":S,"state_name":"...",
        "can_step":bool,"step_count":N,"observation":{...}}
    -> protocol error "no_observation" before the first capture
```

`observe` is additive: the protocol version stays 1 (bumping it would make
every existing M1d, M1e and M2 client reject the server), `status` is not
turned into an observation response, the observation schema is unchanged,
and the transport still never calls `rlStepPoll()` or `rlStepSubmit()`
outside `step`. Against a BattleShip built before this change the client
gets `unknown_op`, which the environment reports as a `request_rejected`
lifecycle failure naming the rebuild.

## Gymnasium contract

### observation_space

`gymnasium.spaces.Dict` over the frozen M1b `RLObservation`
(`observation_schema` 1), field for field, in declaration order, with the
native widths and no narrower ranges than the type guarantees:

| Field | Native | Space |
| --- | --- | --- |
| `observation_schema`, `host_frame`, `input_tick`, `time_passed`, `game_status`, `targets_remaining`, `jumps_used` | `uint32_t` | `Box(0, 2^32-1, shape=(), dtype=uint32)` |
| `btt_active`, `fighter_valid` | `uint32_t`, exactly 0 or 1 by contract | `Discrete(2)` |
| `position_x`, `position_y`, `air_velocity_x`, `air_velocity_y`, `ground_velocity_x` | `float` | `Box(-inf, inf, shape=(), dtype=float32)` |
| `facing_direction`, `ground_air_state`, `fighter_status_id` | `int32_t` | `Box(int32 min, int32 max, shape=(), dtype=int32)` |

Every observation returned by `reset()` and `step()` satisfies
`env.observation_space.contains(observation)`. Box fields are 0-d arrays in
the native dtype (exact: the floats come off the wire as the exact float32
value widened to double and are cast back losslessly); the two flags are
plain ints, Gymnasium's convention for a Discrete observation. Validity is
read from `btt_active` and `fighter_valid` only, never inferred from zeros.
Diagnostic fields (`observation_schema`, `host_frame`) are kept; feature
selection and normalisation are later, Python-owned steps. The full raw
`Observation` dataclass is also in `info["native_observation"]`.

### action_space

Two domains exist and must not be confused:

| Layer | Buttons | Stick | Where |
| --- | --- | --- | --- |
| M1c / M1d native controller domain (frozen) | none, or exactly one of A, B, Z, L, R, C-up, C-down, C-left, C-right | int8, -128..127 on each axis | `RLAction`, `rlStepValidateAction`, the `step` op, `BattleShipClient.step()` |
| M3 Gym-facing action domain | none, A, B, Z, L, R, C-up, C-left | -80..80 on each axis | `BattleShipBTTEnv.action_space`, `action_to_native()` |

The Gym domain is a deliberate subset of the native one, contract id
`btt_raw_b8_s161_v1` (8 button states, 161 stick values per axis). The
identifier names the Gym-facing domain only, not the transport's
capability. It is not Track 1 (`btt_s9_b8_v1 = MultiDiscrete([9, 8])`),
which reduces both domains further and remains reserved.

```text
Dict({
    "button":  Discrete(8),              # index into BUTTON_TABLE
    "stick_x": Discrete(161, start=-80), # exact native value, -80..80
    "stick_y": Discrete(161, start=-80), # exact native value, -80..80
})
BUTTON_TABLE:  0 none   1 A   2 B   3 Z   4 L   5 R   6 C-up   7 C-left
```

Why this subset:

- analog magnitudes beyond 80 do not add useful effective controller
  states (they are capped to +-80 in effect), so the Gym domain stops at 80;
- two C directions are sufficient for M3 environment validation;
- leaving out the redundant actions avoids needless duplicate effective
  actions in the Gym domain;
- the lower-level raw/native interface (`BattleShipClient.step()`, the
  `step` op, `RLAction`) is unchanged and remains available for later exact
  or raw optimisation work.

Consequences, stated plainly: the M3 Gym action space is not lossless over
every M1c action. C-down, C-right and stick magnitudes above 80 are
unrepresentable through a valid Gym action. They are rejected, never
clamped: `action_to_native()` raises `ValueError` for -81 or 81 exactly as
it does for a wrong key, and `native_to_action()` raises for a native
triple outside the Gym domain (a replay row with C-down, for instance).
Values inside the domain pass through exactly (-80 stays -80, 80 stays 80).
Nothing native changed for this: the button rule, the int8 stick range and
the replay path are the frozen M1c / M1d ones.

`action_to_native()` maps a Gym action to the `RLAction` triple
(`buttons`, `stick_x`, `stick_y`) by table lookup and validation; a valid
Gym action can never produce an illegal native word (Start, D-pad, unknown
bits, several buttons are unrepresentable, as are C-down and C-right).
`native_to_action()` is the inverse for native triples inside the Gym
domain, such as the baseline replay rows. A `Box` with integer dtype was
rejected for the stick because Gymnasium's `Box.sample()` clips integer
samples two values inside the limits, so the end points could never be
sampled; `Discrete` with a start offset samples every value uniformly and
its `contains` is exact.

### reset(*, seed=None, options=None)

```text
close()/dispose any previously owned episode (M2 close(): terminate, else kill)
launch a completely NEW BattleShip process (M2 BattleShipEpisode.start())
    isolated save, result JSON and log paths under the environment's run root
    new loopback port, new transport connection
wait for fresh WaitingForAction, can_step, step_count == 0 (M2 gate)
observe (non-consuming) -> initial observation
require: WaitingForAction, can_step, step_count == 0, input_tick == 0, btt_active == 1
return observation, info
```

`super().reset(seed=seed)` seeds the Python-side `np_random` only. Mario
BTT here has no RNG state this project inspects or controls, and the seed
never reaches the game. `options` is accepted and unused. There is no
in-process reset, no save state and no reuse of an ended process. A failure
anywhere raises `EpisodeFailure` (M2 classification) or `BattleShipError`
after the owned process has been disposed of.

### step(action)

```text
validate and convert the Gym action (ValueError before anything is sent)
submit exactly one M1d step  ->  M1c consumes exactly one native tick
return the paired authoritative M1b observation
```

Invariants preserved: `info["consumed_tick"] == T`,
`observation["input_tick"] == T + 1`, `info["step_count"] == T + 1`. No
extra `status` or `step` request is issued per step. A transport, request
or process failure is classified by `BattleShipEpisode.classify_step_failure`
and raised as `EpisodeFailure` after the process is disposed of; it is
never reported as a finished episode. Stepping outside an active episode
raises `BattleShipEnvError`.

### reward

`0.0` on every transition. This is a placeholder required by the Gymnasium
signature and nothing else: no target, completion, time, distance or
movement term exists. Reward design is Python-owned and belongs to a later
learning milestone.

### terminated

`True` exactly when the step result's native state is `EpisodeEnded`, i.e.
the authoritative M1c terminal state (the result whose observation shows
`btt_active` with `targets_remaining == 0`). It is not inferred from the
target count. On termination the environment runs the existing M2 finish
path: wait for the deferred `SSB64_RL_EXIT_ON_END` clean exit, require exit
code 0, load and shape-check the result JSON. The terminal observation is
returned to the caller regardless; `info` additionally carries
`exit_code`, `result` (the native result JSON), `result_path` and
`cleanup_action`. Lifecycle or process failures raise instead of
terminating.

### truncated

`True` only from the optional, Python-owned `max_episode_steps` bound
(default `None`: normal BTT semantics, no time limit). On the bound the
parked process is disposed of immediately (`info["cleanup_action"]`,
`info["truncation_reason"] == "max_episode_steps"`), `terminated` is
`False`, and the last observation is returned. Native completion is never
reported as truncation.

### close()

Idempotent. Delegates to M2 `close()`: closes the client, terminates the
process if alive, kills it if terminate fails, raises `cleanup_failure` only
if both fail. Safe before `reset()`, during an active episode, after a
terminal or truncated episode, after a failed `reset()` or `step()`, and any
number of times. After `close()`, `reset()` raises `BattleShipEnvError`.

### render

No render mode is supported (`metadata["render_modes"] == []`,
`render_mode=None` only). BattleShip draws its normal window; nothing about
the rendering path changed.

### info

`protocol` (1), `env_contract`, `observation_schema`, `state`, `state_name`,
`step_count`, `consumed_tick` (`None` at reset), `input_tick`,
`time_passed`, `targets_remaining`, `native_observation`, `native_action`
(step only), plus the process identity `pid`, `port`, `episode_dir`,
`episode_index` (`PROCESS_IDENTITY_INFO_KEYS`). Terminal and truncated steps
add the keys described above.

## Smoke validation

```text
python rl/m3_gym_smoke.py                      # all nine cases
python rl/m3_gym_smoke.py construct action_mapping   # no game needed
```

| Case | Proves |
| --- | --- |
| `construct` | spaces defined (`Discrete(8)`, `Discrete(161, start=-80)` x2, contract `btt_raw_b8_s161_v1`); 20000 samples all inside the Gym domain (button in the 8 declared states, never C-down / C-right, both sticks in -80..80) and covering every button and every stick value on both axes; no process launched; `step()` before `reset()` refused; `close()` twice before reset |
| `action_mapping` | explicit button table 0 none, 1 A, 2 B, 3 Z, 4 L, 5 R, 6 C-up, 7 C-left; C-down and C-right absent; 2576 native triples round-trip exactly (8 buttons x 161 values x 2); boundaries -80, -79, 0, 79, 80 pass through unchanged; representative actions for all 8 buttons with (-80,-80), (-79,0), (79,0), (80,80), (-1,1), (37,-61), (80,-80) convert exactly, also from numpy-typed inputs; 12 native words unrepresentable (C-down and C-right included); stick -81, 81, -128, 127 rejected on both axes; 14 malformed or out-of-domain Gym actions rejected, never clamped |
| `reset_tick_zero` | `reset()` returns `step_count 0`, `input_tick 0`, `time_passed 0`, `targets 10`, `btt_active`/`fighter_valid` 1; three `observe` calls 0.5 s apart return identical snapshots with nothing consumed; the first `step()` gives `consumed_tick 0`, `input_tick 1`, `step_count 1`, reward `0.0`, `terminated False`, `truncated False`; the second gives 1 / 2 / 2 |
| `raw_actions` | all eight Gym buttons with the analog boundaries (-80,-80), (-79,0), (0,0), (79,0), (80,80) plus (-1,1), (37,-61), (80,-80), (0,79), (0,-79) reach the wire as the exact integers (the request lines are recorded and compared), consumed ticks 0..9; then, bypassing the wrapper, the raw client steps C-down, C-right, (-128,127) and (127,-128) to show the native layer below still accepts them |
| `random_agent` | 150 `action_space.sample()` steps on a fresh process: every sample inside the Gym domain (checked explicitly, no reliance on native clipping), all observations in space, consumed ticks 0..149, `truncated True` / `terminated False` at the bound, process terminated at the bound, `step()` afterwards refused |
| `reset_partial` | reset, 5 steps (`input_tick 5`, `time_passed 4`), reset: new pid, new directory, previous process terminated, `step_count 0`, `input_tick 0`, `time_passed 0`, `targets 10`, first step consumes tick 0 |
| `replay_complete` | first checks that the tracked replay lies inside the Gym domain (it does: 0 C-down rows, 0 C-right rows, no stick beyond +-80 in all 468 rows, so it is fed exactly, nothing substituted or clamped), then the 7.43 s baseline through the wrapper with the unchanged M1e per-step and completion checks (below); then `reset()` gives a new pid with `step_count 0`. Had the replay used an action outside the Gym domain, this case would be dropped rather than approximated: M1e and M2 remain the authoritative exact 7.43 regression |
| `env_checker` | `gymnasium.utils.env_checker.check_env` (below) |
| `close_paths` | `close()` before reset (x2), mid-episode (x2, process terminated), after a failed reset (missing executable -> `startup_failure`), after a failed step (`SSB64_MAX_FRAMES` -> `premature_exit` with exit code 0 raised, never a finished episode), and `step()` refused afterwards |

Every case checks that the environment owns no live process afterwards and
that the machine-wide `BattleShip.exe` count did not rise.

### The 7.43 s baseline through the wrapper

```text
actions consumed        447
last consumed_tick      446
completion_time_passed  446
completion_input_tick   447
final step_count        447
targets_remaining       0
terminated              true
truncated               false
process exit code       0
rows unsent             21 (of 468)
result JSON             result_schema 1, outcome clear, targets_broken 10,
                        completion 446 / 447, final 446 / 447
```

`446` (in-game timer) and `447` (input cursor) are different clocks; nothing
derives one from the other.

### Gymnasium checker

`check_env(env)` on a plain instance (no `spec`, so its own
seeded-determinism asserts are skipped and only containment, return types,
seeding and the step-determinism check run). It stops at exactly one
assertion:

```text
AssertionError: Deterministic step info are not equivalent for the same seed and action
```

This is not a Gym API violation. The check resets twice with the same seed,
steps once with the same sampled action and requires `info` to be equal. Two
resets are two OS processes, so `info["pid"]`, `info["port"]`,
`info["episode_dir"]` and `info["episode_index"]` differ by construction. The
observations, reward, terminated and truncated of the two fresh processes
were equivalent (the checker asserts those first, and they passed). The
smoke case repeats the check by hand with `PROCESS_IDENTITY_INFO_KEYS`
stripped: the observations are exactly equal (including `host_frame`), and
`info` differs in nothing else. The process identity stays in `info`
because it is the diagnostic that names the episode's process and files.

Warnings, all advisory:

- `A Box observation space minimum value is -infinity / maximum value is
  infinity` for the five float fields: the native contract bounds no float,
  and inventing bounds is out of scope.
- `The obs returned by reset()/step() should be an int or np.int64` was
  reported for the two `Discrete(2)` flags while they were 0-d arrays; this
  was a genuine convention mismatch and was fixed (the flags are now plain
  ints).
- `check_env(warn=...) parameter is now ignored` in gymnasium 1.3.0; the
  argument is no longer passed.
- `Not able to test alternative render modes due to the environment not
  having a spec` and the skipped close check: the environment is not
  registered with `gymnasium.make`; there are no render modes to test.

Gymnasium's own `Box.sample()` for a 0-d Box returns a numpy scalar, and its
`Box.contains` then warns `Casting input x to numpy array`; this concerns
synthetic samples of the observation space only, never an observation the
environment returns.

## Verified (2026-09-21, Windows US Release build with the `observe` op)

`python rl/m3_gym_smoke.py`: all nine cases PASS, `BattleShip.exe` count 0
before, 0 after, no owned process alive after any case. Boot to fresh took
about 3.5 to 4.5 s per process; stepping about 34 ms per step; the baseline
episode about 15 s. The numbers above are the ones observed.

Rerun the same day after the action-space correction (8 buttons, -80..80),
with no native rebuild because nothing native changed: all nine cases PASS
again. Observed: 20000 samples never left the Gym domain and covered all 8
buttons and every value in -80..80 on both axes; 2576 round trips exact;
-80 / -79 / 0 / 79 / 80 passed through unchanged; -81, 81, -128 and 127
rejected on both axes; C-down and C-right unrepresentable through the Gym
mapping while the raw client, below the wrapper, still stepped C-down,
C-right, (-128, 127) and (127, -128) natively (consumed ticks 10..13 of
that process); the 150-step random agent sampled all 8 buttons with stick
values within [-80, 80]; the tracked replay was confirmed inside the Gym
domain (0 C-down rows, 0 C-right rows, 0 rows beyond +-80) and reproduced
447 / 446 / 447 / 446 / exit 0 through the wrapper. M2 regression (3/3,
446/447 each), M2 lifecycle smoke (6/6) and M1e on a hand-launched process
(447 / 446 / 447 / 446) passed unchanged. No `BattleShip.exe` remained.

Existing regressions, rerun unchanged against the rebuilt executable:

- `python rl/m2_restart_regression.py`: M2 PASS, three fresh processes, each
  447 actions, last `consumed_tick 446`, completion `446 / 447`,
  `step_count 447`, `EpisodeEnded`, exit code 0, result JSON
  `10 / 446 / 447 / 446 / 447`.
- `python rl/m2_lifecycle_smoke.py`: all six cases PASS.
- `python rl/m1e_replay_regression.py --port <port>` against a fresh process
  launched by hand as `docs/rl_replay_regression_m1e.md` prescribes (no
  `SSB64_RL_EXIT_ON_END`, so the post-completion `status()` cannot race an
  exit): M1e PASS with 447 / 446 / 447 / 446 / `EpisodeEnded`.

Native build: `cmake --build build-us --config Release`, exit code 0; only
`rl_step.cpp` and `rl_transport.cpp` recompiled. `git diff --check` clean.

## Not in M3

No reward design, PPO, training, model or neural-network code, reward
shaping, curriculum, headless mode, binary IPC, shared memory, parallel
environments or multiprocessing, Track 1 (`btt_s9_b8_v1`) and its nine-state
stick, performance optimisation, replay visualisation, fixed camera,
raw-input optimiser, RNG inspection or control. M4 measures startup-to-Go,
native frames per second, protocol round trip, the simulation / IPC /
serialisation split, memory and multi-process throughput before any
optimisation is chosen. Observed but not acted on: about 34 ms per step and
about 3.5 to 4.5 s per reset in this configuration.
