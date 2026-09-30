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
| `replay_ui.py` | Tk control panel (see "Window layout"), click-through HUD overlay and saved-frame view on the game window |
| `replay_history.py` | Saved-frame store, memory math, pixel conversion, step-back planner (see "Stepping back") |
| `replay_status.py` | Action-state names for `fighter_status_id`, read from the decomp headers (see "Window layout") |
| `replay_win32.py` | ctypes helpers (find the game window, overlay placement, hotkeys, process priority) |
| `replay_tests.py` | Offline tests (no game; temp fixtures; reads the decomp status headers) |
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
replay\replay <episode dir> --no-markers               no background pre-pass (no target markers)
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
- **Controls** (panel, or the game window while it has focus):
  - Space: play/pause.
  - Left or `,`: back one tick (see "Stepping back").
  - Right or `.`: step one tick. Left and Right repeat when held.
  - `+`/`-`: speed.
  - R: restart.
  - G: jump to the typed tick.
  - Q/Esc: quit.
  - The timeline jumps on release. The media buttons do the same as the keys
    (hover for the key).
- **Speed.** 0.25x, 0.5x, 1x measured at 15.0-15.3, 29.9-30.3 and 58.3-60.0
  ticks/s. 2x and 4x can be selected but run at 1x for the live game (see
  "Limits"); playback through saved frames honours them.
- **Jump.** `jump N` stops with tick N consumed (the frame on screen is the
  post-update of tick N).
  - A saved tick is shown instantly.
  - A forward jump fast-forwards at the 60 ticks/s render cap.
  - An older unsaved tick is rebuilt: a fresh process fast-forwarded from
    tick 0.
- **HUD** (top-left of the game window; click-through; hidden while another
  application's window overlaps the game): tick, stick arrow + values + stick
  diagram, button name, targets broken so far (`targets_total -
  targets_remaining`), x/y, playback state and the final verdict.

### Window layout

Top to bottom:

- **Verdict badge** (top left). This is the only place the panel shows the
  verdict word.
  - Grey PENDING while there is no verdict, green MATCH, red DESYNC.
  - A per-row clock mismatch turns it red before the end: it already decides
    DESYNC.
  - Grey STOPPED after BattleShip stops.
  - The HUD over the game window still names the verdict at the end
    ("■ MATCH: fall at tick 3444"), since the panel may be elsewhere.
- **Header.** The episode id, then role, run, profile, observation, reward,
  recorded end, targets, rows and prefix.
  - A field that is None or not recorded is left out.
  - The path is shown relative to `runs\` (the full path for an episode
    elsewhere), with an **Open folder** button that opens it in Explorer.
  - A path that doesn't fit is shortened in the middle, so the episode
    folder name stays visible:
    `runs\m7p\campaign\_ev…\episode_20260928T072129Z_44619208`.
    The tooltip shows the full path, and right-click copies it.
- **Live state**, in fixed-width columns: TICK, STICK, BUTTON, TARGETS, X, Y,
  ACTION STATE.
  - Every text that changes has a fixed width, so nothing shifts and the
    window never resizes while playing.
  - On a saved frame, the TICK column turns cyan.
- **Action state.** `fighter_status_id` is shown as a name next to the number,
  e.g. `Wait (10)`, `JumpAerialF (24)`, `SpecialAirHi (226)`.
  - The names are read at start, read-only, from two decomp headers:
    - `decomp/src/ft/ftdef.h`: `FTCommonStatus`, ids 0-219;
    - `decomp/src/ft/ftchar/ftmario/ftmario.h`: `ftMarioStatus`, 220-228.
  - The parser is `rl/m7n_status_table.parse_enum`, the one that built the
    M7n/M7q action-class tables.
  - A range marker such as `ControlStart` gives way to the state's own name,
    so 10 is Wait.
  - An id without a name shows as the number only.
  - `python replay\replay_status.py` prints the table.
- **Status line.** The playback state, with engine messages in grey below.
  Examples: "▶ 1x 59.9 ticks/s", "❚❚ paused", "» fast-forward",
  "⟲ rebuilding", "◀ SAVED FRAME tick N — live game at tick L",
  "■ ended: fall at tick N".
- **Timeline with target-break markers.** An amber triangle and the target
  number sit under the tick where each target broke. Hover for a tooltip
  ("Target 2 broken at tick 360"); click to jump to that tick.
  - The markers come from a headless pre-pass started in the background at
    load. It is the same no-render replay as `--check`: a separate fresh
    process at IDLE priority, with its own session folder.
  - The window therefore opens at once. The markers appear after about 5 s
    (4.7-4.8 s measured for 3,445 rows).
  - The markers describe this replay, which is what the viewer shows. The
    pre-pass compares and records nothing.
  - `--no-markers` skips it. Closing the viewer while it runs stops its
    process.
- **Controls**, in three groups:
  - media buttons: ⏮ restart, ◀❚ back one tick, ▶/❚❚ play/pause, ❚▶ step;
  - speed;
  - the tick field and Jump.
- **Result.** One line, e.g. "✔ MATCH — 8 ok, 0 skipped".
  - Click it to expand every check: ✔ / ✖ with expected and got, then the
    skipped ones.
  - It opens by itself on DESYNC and on an error.
  - **Likely root cause.** When the actions digest check fails,
    `actions.jsonl` differs from what the recorded run submitted, so the
    replay fed other inputs.
    - The summary leads with that: "✖ DESYNC — likely root cause:
      actions.jsonl differs from the recording (actions digest); 3 downstream
      failures, 4 ok, 0 skipped".
    - In the list, that check is marked "likely root cause", and every other
      failure is marked "downstream".
    - When the digest matches (or was not recorded), failures are listed
      without labels.
  - **Observation mismatches** (final, and initial if it ever differs) are a
    field / expected / got table.
    - Floats are shown to 3 decimals.
    - Copying gives full precision, tab-separated: select lines and press
      Ctrl+C (whole lines are copied), or right-click for "Copy all checks".
    - The console and `verdicts.jsonl` text is unchanged.
  - The window height follows the content; only the panel position is
    remembered.
- **Footer** (small, grey): the keys; below them, the saved-frame diagnostics
  (count, MB, resolution, tick range, median copy time) and the marker
  pre-pass state.

### Stepping back (saved frames)

The game itself only moves forward: there are no save states, and one process
is one episode. But a replay is deterministic: tick T renders the same frame
in every process that replays the episode. So the viewer keeps recent frames
and shows them for instant steps back.

- **Saving.** Right after each tick returns, the frame on screen is copied
  from the game window into memory, together with that tick's input,
  observation and targets.
  - This covers 1x playback, single steps, slow motion, and the last
    history-length ticks of every fast-forward (so after a rebuild, further
    steps back are instant again).
  - The tick-0 state is saved too.
  - Nothing is read from or written to the game.
- **Left / `,`:**
  - One tick back. A saved tick is shown at once over the game window: a
    click-through image with a cyan frame.
  - The HUD shows a solid cyan banner, **◀ SAVED FRAME tick N** with
    **live L**, and describes the saved tick (input, targets, position). The
    panel status reads "◀ SAVED FRAME tick N — live game at tick L", and its
    TICK column turns cyan.
  - The game stays paused at the live tick.
  - If the live game was playing, it is paused first.
- **Right / `.`:** forward through saved frames. Past the newest one, the
  live game is back.
- **Space on a saved frame:** plays forward through the saved frames at the
  selected speed (2x/4x work here), then hands over to the live game
  seamlessly.
- **Older than the saved frames:** fallback. The engine launches a fresh
  process and fast-forwards to the tick. The HUD and panel show
  "⟲ rebuilding to tick N" (booting, then progress k/N).
  - This takes about 2.5 s + N/60 s (measured: tick 390 in 9.6 s, tick 900
    in 17.7 s).
  - The last history-length ticks are saved on the way, so the next Left is
    instant (measured: 37 ms).
- **Options:**
  - `--history-seconds S`: history length (default 10 s = 600 ticks; 0 turns
    it off, and every step back becomes a rebuild).
  - `--history-scale N`: resolution = game window / N; default 2 (half).
  - `--history-filter smooth|nearest`: downscale filter (area-averaged, or
    nearest-pixel with less CPU).
  - `--history-capture always|slow`: slow saves only single steps, ≤ 0.5x
    and fast-forward tails (for a heavily loaded machine; 1x playback then
    saves nothing).

Memory (pixel data; the viewer process adds ~80 MB):

| Game window | Scale | Per frame | 10 s (600 frames) |
| --- | --- | --- | --- |
| 960x720 (default) | 1/2 (default) | 518 KB | **311 MB** (measured working set 394 MB) |
| 960x720 | 1/1 | 2.07 MB | 1.24 GB |
| 960x720 | 1/3 | 230 KB | 138 MB |
| 960x720 | 1/4 | 130 KB | 78 MB |

Memory scales linearly with `--history-seconds`. `replay.py` prints the
upper bound at start. The panel footer shows the current count, MB and saved
tick range.

**How a frame is copied, and why it is the right tick.** All of this lives in
`replay_game.CaptureWorker` and `replay_win32.WindowCapturer`.

- **The read.** One GDI BitBlt from the game window's own DC (~5 ms at
  960x720).
  - It is byte-identical to `PrintWindow(PW_RENDERFULLCONTENT)`, and
    windows on top (the HUD, other applications) are not included.
  - `PrintWindow` itself takes ~16 ms because it waits for DWM, so it is
    only a fallback.
  - The downscale (StretchBlt, memory to memory) and the BGRX to RGB
    conversion happen after the read.
- **The capture thread.** Copies run on a background thread, so the
  stepping thread submits the next tick immediately.
- **Why the read is safe after the next submit.** The port paces presents at
  least 1/60 s apart, so tick k's frame stays on screen for at least ~16 ms
  after its step reply. The pacer (libultraship `gfx_sdl2.cpp`
  `SyncFramerateWithTime`) re-bases on the actual present time, so a late
  frame is never followed early by the next one.
- **Settle delay.** The step reply can arrive before the new frame is
  visible: an immediate read returned the previous tick's image on 2-3 % of
  1x ticks. The thread therefore waits 2 ms (0 stale in 1,200 ticks). A read
  that still equals the previous tick's image is taken again.
- **After a gap.** When the previous tick's copy is missing (a dropped copy),
  a stale image cannot be recognised by that comparison. The thread then
  waits 6 ms instead: three times the longest stale window seen, and the read
  still ends near 11 ms.
- **When a read is stored.** Only if it finished within 16 ms of the reply,
  or before the next tick was submitted. Anything later is dropped and
  counted, never stored under the wrong tick.
- **Ground truth** (1x copies vs slow single-stepped references, 600 ticks):
  - every read within 20 ms of the reply was the correct frame;
  - reads at 24-28 ms (a start-up backlog) showed the next tick.
- **Determinism, end to end.** A saved frame was byte-identical to the same
  tick re-rendered by a fresh process after a rebuild. A later audit compared
  1x copies with the same ticks re-copied during a rebuild fast-forward:
  2,161 ticks over 4 rounds, all byte-identical, with 0 dropped copies and
  0 stale reads.

**1x playback, before / after (full UI running, 8 s windows):**

| Saved frames | Rate |
| --- | --- |
| off | 59.8-60.1 ticks/s |
| on (default: 10 s, half, smooth) | 59.3-60.1 ticks/s |

- One run under load read 57.1 ticks/s, and one outlier read 30.0 ticks/s;
  that outlier did not repeat in 4 reruns and was probably other desktop
  activity.
- Copy latency: median ~7 ms, p95 ~9 ms.
- Dropped copies: 0-8 of ~530 frames in most runs (up to 24 in one run with
  a ~70 ms hiccup).

How the 60 ticks/s was reached:

- A first synchronous version dropped 1x to 56.3 ticks/s. The copy then
  moved to the background thread.
- The viewer sets a 1 ms Python GIL switch interval.
- The capture thread runs at above-normal priority (viewer process only; the
  game's priority is untouched).
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
- **Saved-frame gaps.** A copy that could not be proven to show its own tick
  is dropped (see "Stepping back"). This was 0-8 of ~530 frames in most 1x
  runs on this machine. Stepping back onto such a tick is a rebuild, like a
  tick older than the history.
- **Saved-frame display.** Saved frames are shown at the capture resolution,
  scaled up by an integer factor (half resolution by default). They are
  hidden, like the HUD, while another application's window covers the game
  window. Resizing the game window after a frame was saved shows that frame
  at its old size.

## Verification (2026-09-29, exe sha256 30a3913b...)

### Result panel and timeline polish

- **Offline tests:** 21/21, including the new root-cause / downstream and
  table test.
  - The rounded table is shown and the full-precision text is copied.
  - Middle ellipsis keeps the episode folder.
  - The panel test now also covers the marker tooltip and click, copying the
    whole list and a selection, and the path label and its tooltip.
- **Real DESYNC verdict** (headless replay of the tampered scratch copy)
  rendered in the panel.
  - The digest failure leads the summary; end, targets and final observation
    are downstream; the table has 7 fields.
  - A real mouse selection over two table rows plus Ctrl+C gave the
    full-precision tab-separated lines. The clipboard was not written; the
    text was recorded.
- **UI regression:** 13/13.
- **Live sessions:** saved frame 7/7, DESYNC 7/7.
  - The markers check first failed once: the script counted before the
    viewer's next refresh.
  - The markers are drawn 54-62 ms after the pre-pass finishes; the check now
    waits for them.

### Window layout

Offline tests: `python replay/replay_tests.py` passes 20/20. The 6 layout
tests cover:

- action-state names from the decomp headers (aliases, Mario's range, the
  number fallback);
- panel texts: the header without unrecorded fields, the `runs\` relative
  path, the badge, the result line and check list, the columns (no `t=`) and
  marker grouping;
- the pre-pass break ticks and its cancellation;
- stale-session cleanup sparing a session that is still being created;
- the real panel, withdrawn: the width and every column stay the same between
  short and long values, the result stays one line on MATCH, opens by itself
  on DESYNC and toggles on click;
- the post-gap capture wait.

On a real game window, with scratch copies of episode A (never `runs/`):

- **UI regression:** 13/13. 1x ran at 59.9 ticks/s; 4x ran at 59.9 ticks/s
  (capped).
- **Saved frames:** 18/18.
- **Layout, saved frame:** 7/7.
  - The window opened while the pre-pass was running.
  - The pre-pass finished in 4.8 s, with break ticks 218, 327, 706, 1579,
    2400 and 3008: the same as `--check`.
  - 1x ran at 60.1 ticks/s.
- **Layout, DESYNC** (rows 200-230 tampered): 7/7.
  - Red badge, and the checks opened by themselves.
  - No verdict word in the status line.
  - The pre-pass markers (218, 360, 661, 1450) equal the windowed replay's
    target breaks.
- **Closing `replay.py` early:** exit in 2.6 s while the pre-pass was still
  launching (two BattleShip processes), and 0.3 s after it finished. No
  process or session folder was left behind.
- **Test-script race:** the first reruns of the saved-frame scenario failed
  its check that a saved frame equals the same tick re-rendered.
  - The frames were identical. The script compared too early: the new copy
    lands ~10-30 ms after the engine reports "paused".
  - The script now waits for the copy.

### Saved frames

Offline tests at the time: 14/14. The 6 saved-frame tests cover:

- memory math;
- eviction around the current position;
- BGRX to RGB conversion and a Tk PPM round trip;
- the step-back planner (saved / live / forward / rebuild / none);
- the engine's capture policy;
- the capture thread's timing rule, with a fake capturer: on time is stored,
  late after the next submit is dropped, late before the next submit is
  stored, a stale copy is re-read, and a backlog is skipped.

Saved frames, end to end on episode A (scripted, real game window; 18/18):

- 1x 60.1 ticks/s with saved frames vs 60.0 without.
- Left x5 gives saved frames with the game untouched (same process, same
  live tick), and the SAVED FRAME banner and panel text.
- Right back to live; Space through saved frames into live play.
- Saved frame == the same tick re-rendered by a fresh process, byte for byte.
- No false "paused" state during rebuilds.
- A fast-forward to 1500 keeps exactly ticks 901..1500.
- Left at 901 rebuilds to 900 (17.7 s), then Left is instant again (37 ms).
- MATCH at the end; Left works after the fall.

The earlier 13-step UI regression (keys, speeds, jumps, restart, MATCH) still
passes 13/13 with saved frames on.

### Launchers, episodes and the first viewer

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
