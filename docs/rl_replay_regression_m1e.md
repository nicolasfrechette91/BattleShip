# RL M1e: scripted replay integration regression

`rl/m1e_replay_regression.py` is the permanent check that the tracked
baseline replay `tas_input_2/mario_743.btti`, fed one raw controller row at a
time through the frozen M1d client and the M1c stepping path, reproduces the
authoritative Mario Break the Targets completion. It is a regression, not a
training environment: it does not launch, restart, kill or reset BattleShip,
and it has no rewards, no Gymnasium and no learning code. Standard library
only.

## Run it

BattleShip is started by hand, fresh, with interactive stepping and the M1d
transport enabled. From `build-us/Release`, with an isolated save file:

```text
SSB64_RL_BTT=1 SSB64_RL_STEP=1 SSB64_RL_PORT=5555 SSB64_SAVE_PATH=<save> ./BattleShip.exe
```

Then, from any directory:

```text
python rl/m1e_replay_regression.py --port 5555
```

`--port` is required, as it is for the M1d client. `--host` defaults to
`127.0.0.1` and `--replay` to `tas_input_2/mario_743.btti` (resolved from the
script, not the working directory). `--connect-timeout` bounds how long a
refused connection is retried and `--ready-timeout` how long a booting game
may stay `Inactive`.

## Expected result

```text
M1e PASS
source_rows=468
steps=447
last_consumed_tick=446
completion_input_tick=447
completion_time_passed=446
targets_remaining=0
final_state=EpisodeEnded
rows_after_completion=21
```

followed by `wall_s` and a `host_frame_diagnostic` line. `host_frame` is
diagnostic only and is never asserted. Exit status is 0 for PASS, 1 for a
regression or precondition failure (the report names the failing source row,
the expected and actual consumed tick, the observation `input_tick` and
`time_passed`, and the native state or error), and 2 for an unusable or
malformed replay or bad usage.

## What it proves

- The replay is validated in full (see below) before anything is sent.
- The game starts as a fresh episode: native state `WaitingForAction` with
  `step_count == 0`, after waiting out `Inactive` while it boots.
- For source row `i`: `consumed_tick == i`, `observation.input_tick == i + 1`
  and `step_count == i + 1`. `input_tick` is the stepping authority; no clock
  is derived from another.
- Narrow observation sanity per step: the frozen `observation_schema`,
  `btt_active` and `fighter_valid` set, `targets_remaining` within 0..10 and
  never rising, `time_passed` never falling, and the result state
  `WaitingForAction` until the last target breaks. Positions, velocities and
  animation ids are not asserted.
- The first result with `targets_remaining == 0` has `consumed_tick == 446`,
  `input_tick == 447`, `time_passed == 446`, `step_count == 447` and state
  `EpisodeEnded`, and a following `status` reports `EpisodeEnded`,
  `can_step == false`, `step_count == 447`.

## Source rows versus consumed rows

The baseline has 468 rows. The episode ends once row 446 is consumed, so 447
rows go through M1c and the last 21 lie after the completion cursor. This is
expected: those rows are not sent, and M1c's terminal semantics are not
changed to consume them. The native replay regression (M0/M1a) is what
validates all 468 rows and the native checksum; nothing here recomputes it.

## Fresh process required

One BattleShip process runs one episode and this regression completes it, so
each run needs a newly launched process. If the process is partway through an
episode, ended, stopping or otherwise not `WaitingForAction` at step 0, the run
fails with `Regression requires a fresh BattleShip M1c episode; relaunch
BattleShip and retry.` and exits 1. It never resets or recovers.

## Delay mode

`--delay-ms N --delay-every K` sleeps `N` ms before every source row `i` where
`i % K == 0` (row 0 included; `K` defaults to 1). The pattern is fixed, never
random. The parked game is frozen between steps, so the result must remain
446 / 447 whatever the delays:

```text
python rl/m1e_replay_regression.py --port 5555 --delay-ms 25 --delay-every 20
```

## Replay format

`rl/btti_replay.py` reads the format of `syNetReplayStartBTTSession`
(`decomp/src/sys/netreplay.c`): `#` comment lines and empty lines are skipped;
every other line is `buttons_hex,stick_x,stick_y`, with `buttons` hex in
0..0xFFFF and the two sticks decimal in -128..127. It is stricter than the
native `sscanf` (no stray whitespace, `+` sign, `0x` prefix or trailing text)
so a malformed file fails before any step. It does not apply the M1c button
rule (zero or exactly one permitted button); that stays with the server, and a
rejected row is reported with the native error.
