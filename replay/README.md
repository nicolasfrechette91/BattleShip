# Episode replay viewer and index

Tooling only. It re-plays existing episode artifacts from `runs/` in a visible
BattleShip window, compares the result with the recorded `metadata.json`
(MATCH / DESYNC), and indexes `runs/` so interesting episodes can be found and
opened. It does not train, start campaigns, or change training/evaluation
behaviour. It writes nothing below `runs/` and needs no native, decomp,
libultraship or build change.

## Files

| File | Purpose |
| --- | --- |
| `replay.py` / `replay.cmd` | Viewer entry point (windowed, or `--check` headless) |
| `replay_index.py` / `replay_index.cmd` | Index: `scan`, `list`, `show`, `play`, `check`, `gui` |
| `replay_browser.py` | Tk table browser (`replay_index gui`) |
| `replay_episode.py` | Artifact loading, expected outcome, per-step tracking, MATCH/DESYNC comparison |
| `replay_game.py` | BattleShip process launch in a private runtime, replay engine (pause/step/speed/restart/jump) |
| `replay_ui.py` | Tk control panel + click-through HUD overlay on the game window |
| `replay_win32.py` | ctypes helpers (find the game window, overlay placement, hotkeys, process priority) |
| `replay_tests.py` | Offline tests (no game, temp fixtures only) |
| `replay_gui.pyw` | Windowless launcher: browser + background index refresh (see "Launchers") |
| `replay_open.pyw` | Windowless launcher: one episode in the viewer (Explorer entry, browser Play) |
| `replay_windowless.py` | Shared support for the `.pyw` launchers (log file, message boxes) |
| `replay_context_menu_install.reg` | Adds the Explorer "Replay episode" entry (you import it) |
| `replay_context_menu_uninstall.reg` | Removes that entry |
| `make_context_menu_reg.py` | Regenerates both `.reg` files (absolute paths) after moving the repo or Python |
| `_local/` | Local state, created on first use, Git-ignored (see "Local state") |

Project modules are imported read-only from `rl/`: `battleship_client`,
`battleship_process.allocate_loopback_port`, `run_artifacts.read_artifact`,
`m7_runtime.prepare_worker_runtime` / `remove_worker_runtime` / `pid_alive`,
`m7g_fixture.gameplay_config`.

## Running (Windows, from the repository root)

```
replay\replay runs\m7p\campaign\_eval\m7p_geo4_s1\final\stochastic\workers\w04\artifacts\episode_20260928T072129Z_44619208
replay\replay <episode dir or its actions.jsonl> --play --speed 0.5
replay\replay <episode dir> --start-tick 2900          fast-forward first, then paused on tick 2900
replay\replay <episode dir> --check                    headless, prints MATCH/DESYNC, exit 0/1
```

In PowerShell use `.\replay\replay.cmd ...`; `python replay\replay.py ...`
works everywhere. Exit codes: 0 MATCH, 1 DESYNC, 2 bad arguments or
artifact, 3 BattleShip failure or no verdict (window closed early).

```
replay\replay_index scan                 incremental, read-only (first run ~6 min for ~39k episodes, then ~7 s)
replay\replay_index list --left yes      filter + sort; prints numbered rows
replay\replay_index list -m m7p --min-targets 6 --sort -targets,left_tick
replay\replay_index list --crossing yes
replay\replay_index list --end clear --format paths
replay\replay_index show 1               details + where left entry / crossing came from
replay\replay_index play 1 --play        open row 1 of the last list in the viewer
replay\replay_index check 1              headless MATCH/DESYNC for row 1
replay\replay_index gui                  sortable / filterable table, double-click to play
```

`show`, `play` and `check` also accept an episode id, a unique id suffix
(e.g. `44619208`) or a path. List filters: `--milestone/-m`, `--run`, `--role`,
`--end clear|fall|truncated`, `--min-targets`, `--max-targets`, `--cleared`,
`--left yes|no|?`, `--crossing yes|no|?`, `--replay match|desync|none`,
`--text`. Sort keys: `targets, left, left_tick, crossing, completion, end,
last_tick, steps, min_x, created, path, milestone` (prefix `-`/`+` to force
the order; `--limit 0` shows all).

## Launchers (optional, no console window)

Both `.pyw` files work from any current directory. They switch to the
repository root, write their output to `_local/launcher.log` (rotated at
2 MB), and show failures in a message box.

### Browser: `replay_gui.pyw`

- **Starting it:**
  - Double-click `replay\replay_gui.pyw`. The `.pyw` association runs the
    `pyw` launcher; the `#! python3` line selects the installed Python 3.
  - Or make a shortcut to
    `pythonw.exe "<repo>\replay\replay_gui.pyw"`.
- **Behaviour:**
  - The table opens at once on the existing index.
  - The index refreshes in the background: read-only and incremental, about
    7 s. A first build takes several minutes, with progress shown in the
    status line.
  - The table reloads when the refresh finishes.
  - Play opens the episode through `replay_open.pyw`.

### Explorer "Replay episode" entry

- **Install:**
  1. Import `replay\replay_context_menu_install.reg` yourself: double-click
     it, or run `reg import replay\replay_context_menu_install.reg`.
  2. Right-click an episode folder, or an `actions.jsonl`, then choose
     "Replay episode". On Windows 11 it is under "Show more options"
     (Shift+F10).
- **Uninstall:** import `replay\replay_context_menu_uninstall.reg`.
- **What the entries do:**
  - Both entries are per-user (`HKEY_CURRENT_USER\Software\Classes`, no
    admin rights).
  - Both run
    `"<Python313>\pythonw.exe" "<repo>\replay\replay_open.pyw" "%1"`, with
    the icon of `build-us\Release\BattleShip.exe`.
  - Both appear only when exactly one item is selected
    (`MultiSelectModel=Single`), so a multi-selection cannot start several
    games.
- **Folder entry** (`Directory\shell\BattleShipReplay`):
  - It is offered on every folder; Explorer has no name filter I could
    verify for folders.
  - For a folder that is not an episode, `replay_open.pyw` shows "Not a
    replayable episode" and starts nothing.
- **File entry** (`SystemFileAssociations\.jsonl\shell\BattleShipReplay`):
  - It is limited to files named exactly `actions.jsonl`
    (`AppliesTo = System.FileName:=actions.jsonl`, the documented exact-name
    form).
- **Uninstall leftovers:** the uninstall removes the two `BattleShipReplay`
  keys. The empty parent key `SystemFileAssociations\.jsonl\shell` that the
  install created is left in place.
- **Paths are absolute.** The `.reg` files were generated for this checkout
  and `C:\Users\kill_\AppData\Local\Programs\Python\Python313\pythonw.exe`.
  After moving the repository or changing Python, rerun
  `python replay\make_context_menu_reg.py` (`--pythonw PATH` selects another
  interpreter), then re-import.

### When the game window is closed

- Closing the BattleShip window during a replay no longer ends the viewer.
- The panel shows "BattleShip stopped - press Restart", and Play/Step are
  refused.
- Restart, or Jump, launches a fresh tick-0 process.

## Viewer

- **Reset.** Every replay starts in a fresh BattleShip process at native tick
  0, the reset training uses (`WaitingForAction`, `step_count 0`; tick-0
  `observe` compared with `initial_observation`). Row T of `actions.jsonl` is
  submitted as the input of native tick T through the protocol-1 loopback
  transport, one native update per row. M7h/M7m curriculum prefixes are
  ordinary leading rows, so they replay too.
- **Controls** (panel, or the game window while it has focus): Space
  play/pause, Right or `.` single step (hold to repeat), `+`/`-` speed, R
  restart, G jump to the typed tick, Q/Esc quit. The seek bar jumps on
  release.
- **Speed.** 0.25x, 0.5x, 1x measured at 15.0-15.3, 29.9-30.3 and 58.3-60.0
  ticks/s. 2x and 4x can be selected but run at 1x (see "Limits").
- **Jump.** `jump N` stops with tick N consumed (the frame on screen is the
  post-update of tick N). Forward jumps fast-forward at the 60 ticks/s render
  cap; a target behind the cursor launches a fresh process and fast-forwards
  from tick 0.
- **HUD** (top-left of the game window; click-through; hidden while another
  application's window overlaps the game): tick, stick arrow + values + stick
  diagram, button name, targets broken so far (`targets_total -
  targets_remaining`), x/y, playback state and the final verdict.
- **End.** A replay ends on a native clear (`EpisodeEnded`), on the
  `btt_native_failure_v1` fall rule (the same rule training applies; the
  next submit would wedge the game), or when the rows run out. The window
  stays open on the last frame. The verdict is printed, shown in the panel
  and HUD, and appended to `_local/verdicts.jsonl`.

### MATCH / DESYNC

MATCH requires every check that `metadata.json` supports to agree exactly:

1. `native_action_digest` of `actions.jsonl` (same bytes as
   `M7EpisodeTracker`).
2. Tick-0 observation equals `initial_observation`.
3. Every row: `consumed_tick == row`, `step_count == i+1`,
   `input_tick == consumed_tick+1`.
4. End kind (clear / fall / truncated) equals the recorded one.
5. `terminal.step_count` and `terminal.last_consumed_tick` (the fall or clear
   tick).
6. Targets broken (`terminal.targets_broken`, prefix included).
7. For clears, `completion_time_passed` and `completion_input_tick`.
8. The final observation equals `final_observation`.

`host_frame` is excluded, as in every project comparison. There is no RNG
inspection, logging, control or hashing.

### Launch settings (existing opt-in knobs only)

- `SSB64_RL_BTT=1`, `SSB64_RL_STEP=1`, and `SSB64_RL_PORT` on an
  OS-assigned ephemeral port (not the trainers' 30000+ blocks).
- `SSB64_SAVE_PATH` and `SSB64_RL_RESULT_PATH` are private per launch.
- `SSB64_RAPHNET_DISABLE=1`, as in training.
- **Windowed:** `SSB64_FREEZE_PACING=0`, plus the OpenGL backend in the
  private config copy. `--check` uses `SSB64_RL_NO_RENDER=1` (training's
  headless mode).
- `SSB64_RL_EXIT_ON_END` is not set, so the window stays open after a clear.
- All other inherited `SSB64_*` variables are stripped from the child's
  environment.
- **Working directory:** a private runtime (`rl/m7_runtime.prepare_worker_runtime`)
  under `_local/sessions/`. The user's `build-us/Release/BattleShip.cfg.json`,
  `imgui.ini` and `logs/` are never written.
- **Config:** the base is the episode's recorded runtime config
  (`labels.startup.runtime_dir`) when it still exists, otherwise the
  executable directory's. Only `Window.*` is changed. The gameplay settings
  (tap-jump, auto Z-cancel, hazards) are printed at launch.
- The executable is used read-only (default `build-us/Release/BattleShip.exe`;
  `--exe` selects another, e.g. a future `build-replay` build).

Why OpenGL + `SSB64_FREEZE_PACING=0`? A probe with neutral inputs measured:

- With the default pacing, a rendered step costs two paced presents, a cap
  of 30 ticks/s.
- With `SSB64_FREEZE_PACING=0`, the cap is 60 ticks/s. But DX11 then drops
  displayed frames at slower speeds (26-33 of 45-60 frames at 15/30/45 Hz):
  its late-frame logic in `gfx_dxgi.cpp IsFrameReady` fires.
- OpenGL always renders (0 dropped).

Rendering cannot change game logic here. The port's RCP freeze model is
limited to intro/ending scenes (`port/stubs/port_diag_stubs.c`
`port_scene_wants_freeze_simulation`), and `rl/m7g_crossing.py verify()`
already showed visible and no-render trajectories are identical.

## Index

- **Location:** `_local/index.sqlite`.
- **Walk:** the scan walks `runs/` read-only. It prunes junctions and
  directories that never hold artifacts (`logs`, `runtime`, `runtime_gens`,
  `gNNNN_aN`, `episodes`, `coordination`, `checkpoints`; `--no-prune`
  disables this).
- **Re-reading:** an episode directory is re-read only when its mtime changes
  (artifacts are write-once). Summary files are re-read when their mtime or
  size changes.
- **Skipped:** episode directories modified within `--recent-minutes`
  (default 5), or without `metadata.json`, are skipped and picked up by a
  later scan.
- **Removed:** vanished episodes are dropped.

Per episode it stores:

- path, milestone, run, phase and worker;
- role, run_id, profile, observation and reward contracts;
- end kind and detail, rows, steps, targets (whole episode), cleared,
  completion tick/time, last consumed tick;
- final position, prefix rows and sidecar files.

**Left entry** (first live tick with `position_x < -2100`) and **qualified
crossing** (`btt_qualified_crossing_v1`) are not in `metadata.json`. The best
available source wins:

| Source | Where | Answers |
| --- | --- | --- |
| `replay` | `_local/verdicts.jsonl`, MATCH replays only | exact yes/no |
| `gate_trace` | `gate_trace.json.gz` (M7r evals) | exact yes/no |
| `eval_metrics` | sibling `evaluation.json` (M7g-K..M7r evals) | exact yes/no |
| `census` | `runs/m7p/addendum/walltop_census/census.json` | exact yes/no, crossing |
| `reward_v3` | `labels.reward_v3` (M7j/M7k/M7l) | exact yes/no |
| `m7s_goals` | `m7s_goals.json.gz` (cell x-bins align with -2100) | exact yes/no |
| `crossing_verification` | `_clears/.../crossing_verification.json` | yes only, crossing yes/no |
| `final_obs` | final observation live and x < -2100 | yes only |

- Anything else shows `?`.
- "No left entry" implies "no crossing".
- Replaying an episode (windowed or `check`) turns its `?` into an exact
  answer.

Coverage on the current tree (39,341 episodes):

- M7g-K, M7h, M7j, M7k, M7l, M7m, M7n, M7o, M7p, M7r and M7s are mostly
  resolved.
- M7a-M7e training and evaluation episodes stay `?`: there is no per-tick
  source.

## Local state (`_local/`)

| Path | Contents |
| --- | --- |
| `index.sqlite` | The cache (~36 MB) |
| `verdicts.jsonl` | One line per finished replay |
| `last_list.json` | Row numbers of the last `list` |
| `viewer_state.json` | Window positions |
| `launcher.log` (+ `.log.1`) | Output of the `.pyw` launchers |
| `sessions/<id>/` | Per-viewer runtime dir: config copy, `.tcc` junction, save/result per launch |

A session directory is removed when the viewer exits. Stale ones (dead viewer
pid) are removed on the next start.

`_local/` is Git-ignored (`/replay/_local/` in the repository `.gitignore`).
It is machine-local cache and scratch state, including a directory junction,
and must never be committed.

## Limits and the native change they would need

- **2x/4x and faster-than-real-time jumps are not possible without a native
  change.** Every rendered tick is paced to at least 1/60 s by libultraship's
  present pacer (`gfx_sdl2.cpp SyncFramerateWithTime`, `gfx_dxgi.cpp
  SwapBuffersBegin`, target `mTargetFps` = 60; frame interpolation keeps the
  60 Hz game clock). No-render is fixed per process at launch
  (`port/rl/rl_boot.cpp` `rlConfigInit`, `sConfig.noRender`).
  - The minimal change, not made: a PORT-only, additive protocol-1 step field
    `"render": false`.
  - `port/rl/rl_boot.cpp` + `port/rl/rl.h`: make the no-render flag an atomic
    with a setter (stepping sessions only).
  - `port/rl/rl_transport.cpp`: accept the optional boolean on `step` and
    set the flag before `rlStepSubmit`.
  - `port/gameloop.cpp`: no change. `PortPushFrame` already reads
    `rlNoRenderIsEnabled()` once per host iteration, after the gate opens.
  - Absent field = today's behaviour, so the training path stays
    byte-identical.
  - The viewer would then render 1 of k ticks (2x/4x) and skip rendering
    during jumps. The change must be built into a separate directory (e.g.
    `build-replay`) and passed with `--exe`.
  - It cannot live in `replay/`: the render decision is made inside the game
    process's frame loop, and the only runtime channel into that process is
    the compiled transport.
- **Don't press keys in the game window** other than the viewer hotkeys
  (Space, Right, `.`, `+`, `-`). Ctrl+R resets the game, and the Esc menu can
  change gameplay settings. Either desyncs the replay; the per-row clock
  check reports it.
- **CPU while paused.** With `SSB64_FREEZE_PACING=0` the parked game loop
  spins one core. The viewer drops the game to IDLE priority while paused, so
  a concurrent training run keeps priority.
- **Shared port log.** Every BattleShip launch truncates
  `%APPDATA%\BattleShip\ssb64.log`. The viewer never reads it, but a replay
  started while another tool waits to read that log after a clean exit would
  clobber it.
- The HUD is a separate click-through window over the game, not drawn by the
  game. Screen recording tools capture it as part of the desktop.

## Verification (2026-09-29, exe sha256 30a3913b...)

Offline tests: `python replay/replay_tests.py` passes 8/8.

Launchers, run exactly as Explorer or a double-click would, from
`C:\Windows\Temp` (the `.reg` files were not imported):

- The `.reg` command form on episode B opened the viewer; with
  `--play --exit-at-end` it gave MATCH and exit 0.
- A non-episode folder gave the "Not a replayable episode" box, no game,
  exit 2.
- `pyw.exe replay_gui.pyw` opened the browser; the background refresh
  finished in 6.8 s.
- No console window appeared.
- Closing the game window mid-replay gave the error state, and Restart gave
  a fresh tick-0 process that steps again (6/6 checks).

Named episodes:

| Episode | Headless | Windowed |
| --- | --- | --- |
| `runs/m7s/gate/s2/U_phase_b/workers/w03/artifacts/episode_20260929T042423Z_e699a8eb` (3600 rows, truncated at the horizon, 3 targets) | MATCH (2.6 s) | MATCH (1x, `--play --exit-at-end`) |
| M7p geo4 seed-1 episode A, `runs/m7p/campaign/_eval/m7p_geo4_s1/final/stochastic/workers/w04/artifacts/episode_20260928T072129Z_44619208` (fall at tick 3444, 6 targets) | MATCH | MATCH (64 s wall, 1x) |

For episode A the replayed trajectory reproduces the documented left entry
at tick 3001 (-2117.8, 3932.4) and the target break at 3008.

Scripted UI run (13/13 pass):

- boot paused at tick 0;
- single steps;
- 0.25x / 0.5x / 1x / 4x;
- pause;
- jump forward to 900;
- jump back to 120 (fresh process);
- restart;
- play to the end → MATCH;
- controls inert after the end.

Headless MATCH on a cross-layout sample:

- a TAS clear (447 steps);
- an M7h curriculum episode with 2026 prefix rows;
- M7d training, M7e evaluation, M7r evaluation, M7o control, M7j.
- Also M7p episode B, via `replay_index check`.

Negative tests on a tampered scratch copy of episode A:

- One stick value changed during a shield (R held) → DESYNC on the digest
  only.
- Rows 200-230 changed → DESYNC on digest, end kind, targets and final
  observation.
