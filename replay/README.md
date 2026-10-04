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
| `replay_browser.py` | Episode browser (`replay_index gui`, `replay_gui.pyw`; see "Browser") |
| `replay_task.py` | Character and stage of an episode, from what the run recorded ("?" otherwise) |
| `replay_tags.py` | Per-stage tag extractors (Mario Break the Targets: left entry, crossing) |
| `replay_breaks.py` | Recorded per-target break ticks and the "last target" rule |
| `replay_widgets.py` | Tk pieces shared by the viewer panel and the browser (tooltips, text shortening, colors) |
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
`m7g_fixture.gameplay_config`, `m7n_status_table.parse_enum` /
`CHARACTER_DIRS`. The task registry of `experiment_config` is mirrored, not
imported (see "Character and stage").

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
replay\replay_index list --tag "left entry"   filter + sort (default: most targets, then fastest); numbered rows
replay\replay_index list -m m7p --min-targets 6 --character mario
replay\replay_index list --tag crossing
replay\replay_index list --character ?  runs that recorded no character
replay\replay_index list --end clear --format paths
replay\replay_index show 1               details, tags and where each came from
replay\replay_index play 1 --play        open row 1 of the last list in the viewer
replay\replay_index check 1              headless MATCH/DESYNC for row 1
replay\replay_index gui                  the browser, double-click to play
```

`show`, `play` and `check` also accept an episode id, a unique id suffix
(e.g. `44619208`) or a path.

- **List filters:** `--milestone/-m`, `--run`, `--role`, `--character`
  (`?` = not recorded), `--stage`, `--end clear|fall|timeout|goal|aborted|
  unknown` (or `truncated` for all three non-clear, non-fall ends),
  `--min-targets`, `--max-targets`, `--cleared`, `--tag`,
  `--replay match|desync|none`, `--text` (path, run id, profile or tags).
- **Sort keys:** `targets, time, character, stage, end, verdict, role,
  milestone, run, tags, created, completion, last_tick, steps, path`. Prefix
  `-`/`+` to force the order; `--limit 0` shows all.

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
  - The window is described under "Browser".

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
- **Header.** The episode id, then character, stage, role, run, profile,
  observation, reward, recorded end, targets, rows and prefix.
  - The character is always shown: "?" when the run recorded none
    (`replay_task.py`; never assumed to be Mario).
  - Any other field that is None or not recorded is left out.
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
  - The names are read at start, read-only, from the decomp headers of the
    episode's character:
    - `decomp/src/ft/ftdef.h`: `FTCommonStatus`, ids 0-219, shared by every
      fighter;
    - `decomp/src/ft/ftchar/<dir>/<dir>.h`: that character's own
      `ft<Char>Status`, ids from 220 (specials, entries, ...).
  - `<dir>` comes from `rl/m7n_status_table.CHARACTER_DIRS`. All 12
    characters' tables parse: Mario 9 own states, Fox 26, Donkey Kong 30,
    Samus 11, Luigi 9, Link 17, Yoshi 14, Captain Falcon 19, Kirby 83,
    Pikachu 18, Jigglypuff 16, Ness 25.
  - The same id is a different state per character: 225 is Mario's
    SpecialHi and Fox's SpecialN. So ids from 220 are only named when the
    character is known; with "?" they stay numbers.
  - Only Mario's names are exercised by real runs; the others are exactly the
    decomp's enumerators.
  - The parser is `rl/m7n_status_table.parse_enum`, the one that built the
    M7n/M7q action-class tables.
  - A range marker such as `ControlStart` gives way to the state's own name,
    so 10 is Wait.
  - An id without a name shows as the number only.
  - `python replay\replay_status.py --characters` lists the tables;
    `python replay\replay_status.py fox` prints one.
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

For an M8 route, the same checks come from its verifying replay:

- the digest is `native_action_digest`;
- the end is `replay.terminal.kind`, where `sequence_end` means the rows ran
  out (truncated);
- steps and last tick are `replay.terminal.submitted` and
  `replay.terminal.last_consumed_tick`;
- targets are `replay.t`;
- clear clocks come from `completion_clocks` or `replay.clear_facts`;
- the tick-0 and final observations are the first and last replies in
  `trace.json.gz`.

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

- **Location:** `_local/index.sqlite`, schema 4. An older cache is dropped and
  rebuilt by the next scan: a full re-read, 51 s with a warm disk cache and
  about 7 min cold.
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
- **Reported, never silent.** Every scan counts what it saw but could not
  list, or could not list meaningfully, with one example path each
  (alphabetically first):
  - exploration archive folders, i.e. folders with `cells.jsonl`,
    `archive_meta.json` or `bursts.bin` (M8 route discovery): cells, not
    episodes;
  - folders with `actions.jsonl` but no `metadata.json`;
  - episodes whose `metadata.json` has an unrecognized format: listed, but
    their fields are unknown;
  - folders still being written, and unreadable folders.
  - The line is printed by `replay_index scan` ("not indexed: ..."), stored
    in the index (`meta last_scan_report`), and shown in the browser's
    status bar after a rescan and at start-up.
  - Current tree: 11 archive folders (e.g. `runs/m8_rd/archive`) and 4
    unrecognized episodes (the deliberately broken `bad_*` fixtures of the M4
    regression tests).

Per episode it stores:

- path, milestone, run, phase and worker;
- role, run_id, profile, observation and reward contracts;
- character, stage, and where they were recorded (below);
- end kind and detail, rows, steps, targets (whole episode) and targets
  total, cleared, completion tick/time, last consumed tick;
- recorded per-target break ticks, per source (`breaks` table; see "Last target");
- final position, prefix rows and sidecar files;
- the artifact format (`battleship_btt_episode`, `m8_rd_route_v1`, or
  "unrecognized (...)"), and whether the creation time was recorded or is
  the `metadata.json` file time.

### M8 routes (`runs/m8_rd*/routes/<name>/`)

Route-discovery runs write verified routes in their own schema,
`m8_rd_route_v1`. Each route is a tick-0 native action sequence
(`actions.jsonl`), with `metadata.json` holding its claim, arm and session,
`native_action_digest`, `words`, and the verifying replay's facts under
`replay.*`. `trace.json.gz` holds every reply of that replay. There are no
`labels`, `terminal`, observations, role or creation time.

- **Listed as role `route`.** Targets come from `replay.t`, the end from
  `replay.terminal.kind`, and steps and last tick from `replay.terminal`.
  Clear clocks come from `completion_clocks` or `replay.clear_facts`.
- **End "prefix":** a route that just stops (`terminal.kind
  sequence_end`, a prefix to an archive cell) has the end "prefix". The game
  did not end there.
- **Id:** `route_<session>_<folder>` (e.g. `route_rd4_T_clear`), since folder
  names such as `T_t` repeat across runs.
- **Created:** the `metadata.json` file time, marked as such.
- **Last target:** from the trace (source `route_trace`), or the completion
  for a clear.
- **Tags** are the milestones the route's own replay recorded: "wall top
  @l0_tick", "crossing @first_qualified_entry", "left target @first break",
  "clear". This works through a format extractor
  (`replay_tags.FORMAT_EXTRACTORS`), since no M8 file names the character:
  the M8 code hard-codes Mario. Character and stage therefore show "?", and
  nothing is inferred from stage geometry.
- **Not hidden as tests.** The tests rule hides a missing role only for the
  standard artifact format.
- **The viewer opens routes.** They are read with the same row validation as
  `rl/run_artifacts`, plus `words` == rows. The route runs with its run's
  pinned config: rd1's frozen `runs/m8_rd/archive/runtime/BattleShip.cfg.json`,
  found through `archive_meta.base.rd1_root`. Its gameplay settings equal the
  default. See "MATCH / DESYNC" for the checks.
- **Coverage:** all 9 routes (rd1 C_t and T_t; rd2 T_L0 and T_t; rd3 T_t; rd4
  T_clear, T_crossing, T_left_target, T_t). Their recorded digests equal
  ours. Fed their own recorded replies, all 9 give MATCH: 8-10 checks, none
  skipped.

### Character and stage (`replay_task.py`)

Taken from what the run recorded, first match wins. When nothing is
recorded, both show as "?"; the character is never assumed to be Mario.

| Source | Example | Episodes (current tree) |
| --- | --- | --- |
| `labels.experiment.compatibility_view` `task.character` / `task.stage` | `mario` / `btt_mario` | 33,874 |
| `labels.experiment.task_id`: a registered id (mirrors `rl/experiment_config.SUPPORTED_TASKS`), or the pattern `ssb64_<version>_<character>_<btt or btp>_v<n>` | `ssb64_us_mario_btt_v1` | 4,521 |
| `labels.contracts.action_class_character`; the stage is then `btt_<character>`, since in Break the Targets every character plays their own stage | `mario` | 24 |
| nothing: M7a-era runs, most regression and test folders | "?" | 922 |

The run-level files of those older runs (`run.json`, summaries) do not name
the character either. The copies of `KNOWN_CHARACTERS` and `SUPPORTED_TASKS`
are checked against `rl/experiment_config.py` by `replay_tests.py`. Importing
that module directly costs 0.7 s and pulls in gymnasium and numpy.

Today every recorded episode is Mario on `btt_mario`, so the stage never
varies within a character. The browser therefore shows no stage filter; it
appears once some character has episodes on more than one stage.

### Tags (`replay_tags.py`)

Tags are stage-specific milestones that are not in `metadata.json`, for
example "left entry @3001" or "crossing".

- **One extractor per stage,** registered in `EXTRACTORS`. At scan time it
  reads the episode's own sidecars (`from_episode`) and any run-level file it
  names in `summary_files` (`from_summary`). At load time it reads this
  tool's replay verdicts (`from_replay`) and turns everything into tags plus
  detail lines (`resolve`).
- **Facts are generic.** The index stores them as JSON per
  (episode, stage, source) in the `facts` table.
- **Only the episode's own stage extractor sees them.** An episode with no
  recorded stage gets no tags.
- **Adding a stage** means one `StageTags` subclass and one `EXTRACTORS`
  entry. The index and the browser do not change; `replay_tests.py` shows
  this with a stand-in Fox extractor.

**Mario's Break the Targets (`btt_mario`).** The two tags are:

- left entry: the first live tick with `position_x < -2100`, shown as
  "left entry @tick", or plain "left entry" when the tick is unknown;
- crossing: `btt_qualified_crossing_v1`, shown as "crossing".

The best available source wins:

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

- A missing tag means "no" when an exact source says so, and "unknown"
  otherwise. The details card and `show` say which, with the source.
- "No left entry" implies "no crossing".
- Replaying an episode (windowed or `check`) adds an exact answer.
- Behaviour change: 305 episodes with no recorded character used to count as
  left entries through `final_obs`, mostly regression and test replays (M7f
  and M7g regression suites, `_m7d_regressions`, `_m7c_game*`). They now have
  no tags, because the rule is Mario-stage geometry.
- Coverage on the current tree: 38,419 Mario episodes, of which 28,317 have an exact left-entry answer. 4 are tagged "left entry": M7p geo4 seed-1 episodes A and B, one M7n and one M7m evaluation episode. A is also tagged "crossing".

### Last target (`replay_breaks.py`)

The tick at which the last target broke. For a clear this is the
completion. Per-target break ticks are not in `metadata.json`, and the scan
never replays to find them. It reads what the runs already wrote, in this
order of trust:

| Source | Where |
| --- | --- |
| `replay` | `_local/verdicts.jsonl`, this tool's MATCH replays (exact, whole episode) |
| `evaluation` | `evaluation.json` `episodes[].target_break_ticks` (else `eval_metrics.target_breaks`) |
| `episodes_log` | trainer / evaluator `episodes.jsonl` `target_break_ticks` |
| `gate_trace` | `gate_trace.json.gz`, the per-tick `targets` column (M7r evaluations) |
| `decisions` | `decisions.json.gz`, the per-tick signature field `targets` (M7r) |

The ticks are native consumed ticks. The first rule that applies wins:

- **0 targets:** "–".
- **Clear:** the completion, e.g. "446 · 7.43 s": the consumed tick, and the
  game's `time_passed` in seconds.
- **A source with one tick per recorded target:** its last tick, e.g.
  "3008 · 50.1 s".
- **An M7h/M7m curriculum episode** whose source lists only the policy
  phase (every tick at or after the prefix, fewer ticks than targets): its
  last tick. The missing breaks are the prefix's.
- **Otherwise:** "?". This covers every break inside a curriculum prefix,
  and runs that recorded no break ticks.

Where sources overlap they agree, except in one M7h episode: its training
log omits the prefix breaks, and a MATCH replay has them all. Replaying an
episode (the viewer, `check`, or "Check filtered") makes its last target
exact.

Coverage on the current tree, by milestone:

Known = a recorded tick, a clear, or no target broken. 37,474 of 39,341 episodes (95.3%) are known. The "?" are mostly M7s (941: its goal sidecars do not record breaks), M7h/M7m prefix episodes whose breaks all fell inside the prefix, and M7a-era and regression runs.

| Milestone | Episodes | Known | Unknown (?) |
| --- | ---: | ---: | ---: |
| _m7_g1 | 2 | 2 | 0 |
| _m7_g2 | 2 | 0 | 2 |
| _m7_g3 | 2 | 1 | 1 |
| _m7_g4 | 1 | 1 | 0 |
| _m7_g6 | 19 | 1 | 18 |
| _m7_g7 | 7 | 0 | 7 |
| _m7_regressions | 3 | 0 | 3 |
| _m7_smoke_20260923T032248Z | 2 | 1 | 1 |
| _m7_smoke_final1 | 26 | 7 | 19 |
| _m7b_eval_cli | 3 | 1 | 2 |
| _m7b_m7a_smoke_final | 26 | 5 | 21 |
| _m7b_regressions | 3 | 0 | 3 |
| _m7b_smoke_20260923T032326Z | 22 | 22 | 0 |
| _m7b_smoke_20260925T134448Z | 23 | 23 | 0 |
| _m7b_smoke_20260925T151256Z | 23 | 23 | 0 |
| _m7b_smoke_dev1 | 3 | 3 | 0 |
| _m7b_smoke_dev2 | 20 | 1 | 19 |
| _m7b_smoke_dev3 | 7 | 1 | 6 |
| _m7b_smoke_final | 23 | 4 | 19 |
| _m7c_game2 | 44 | 23 | 21 |
| _m7c_game3 | 32 | 9 | 23 |
| _m7c_reg_m7_smoke | 27 | 4 | 23 |
| _m7c_reg_m7b_smoke | 22 | 5 | 17 |
| _m7c_v2_n5 | 3 | 0 | 3 |
| _m7c_v2_n5b | 4 | 0 | 4 |
| _m7d_preflight_game1 | 90 | 71 | 19 |
| _m7d_regressions | 107 | 74 | 33 |
| _m7dbg | 6 | 2 | 4 |
| _m7e_preflight_game | 28 | 27 | 1 |
| m7a_compare | 14 | 0 | 14 |
| m7a_pilot_n5 | 98 | 2 | 96 |
| m7a_random_baseline | 3 | 0 | 3 |
| m7c_stage1 | 8 | 0 | 8 |
| m7c_stage1b | 8 | 0 | 8 |
| m7c_stage2 | 14 | 0 | 14 |
| m7d | 3,857 | 3,855 | 2 |
| m7e | 3,228 | 3,227 | 1 |
| m7f | 164 | 86 | 78 |
| m7g | 82 | 43 | 39 |
| m7g_k | 6,593 | 6,580 | 13 |
| m7g_obs | 188 | 82 | 106 |
| m7h | 5,085 | 4,894 | 191 |
| m7j | 47 | 44 | 3 |
| m7k | 68 | 65 | 3 |
| m7l | 3,853 | 3,853 | 0 |
| m7m | 2,273 | 2,228 | 45 |
| m7n | 5,124 | 5,100 | 24 |
| m7o | 3,345 | 3,339 | 6 |
| m7p | 3,317 | 3,316 | 1 |
| m7q | 2 | 0 | 2 |
| m7r | 431 | 431 | 0 |
| m7s | 959 | 18 | 941 |
| **all** | **39,341** | **37,474** | **1,867** |

## Browser

`replay_index gui`, or `replay_gui.pyw` without a console. Standard library
only; I recommend no theme package (see the note at the end of this section).

- **Filters** apply as they change; the search applies 150 ms after typing
  stops, and Esc clears it.
  - Filters: milestone, character (`?` = not recorded), role, end, min
    targets, verdict, and a search over path, run id, profile and tags.
  - A stage filter appears only when some character has more than one
    stage.
  - **Reset** clears all filters and switches both toggles off.
- **Show tests** (off by default) shows test, smoke and equivalence
  episodes; otherwise 1,096 of 39,341 are hidden. They are:
  - role `test` (409) or `m6_equivalence` (45);
  - no role recorded (254), all in regression and test folders;
  - everything in `_`-prefixed milestone folders (`_m7_smoke*`,
    `_m7b_regressions`, `_m7c_*`, `_m7d_preflight*`, `_m7d_regressions`,
    `_m7dbg`, `_m7e_preflight_game`, `_m7b_eval_cli`, ...). This is the
    repository's convention for smoke, regression, preflight and debug runs,
    and there is no "smoke" role: those episodes carry ordinary roles
    (training 265, evaluation 122).
  - `random_baseline` (15) stays visible.
  - `replay_index list --no-tests` applies the same rule.
- **Best per run** shows one row per run: milestone plus run path, with
  workers merged. The row is the run's best episode by targets, then
  last-target tick. An **Episodes** column shows how many of the run's
  episodes pass the filters: "12", or "12 of 40" when filters hide some. The
  count reads "N runs (best of M episodes)".
- **The count** reads "N of M episodes (K tests hidden)".
- **Check filtered…** replays every listed episode headless, in the
  background, one BattleShip process at a time:
  - above 50 episodes it asks first, with an estimate (about 4.5 s each);
  - the status bar shows "checking k/N: episode · MATCH / DESYNC / failed
    counts";
  - the button becomes **Cancel check**, which terminates the running replay;
  - each result updates the verdict column at once, and a MATCH fills in an
    unknown last target;
  - when the batch ends, the table reloads from the index.
  - Verdicts are recorded like `replay.py --check`, in
    `_local/verdicts.jsonl`, the verdict log the index reads. `runs/` is
    only read, and sessions live under `_local/sessions/`.
  - Closing the browser cancels a running batch.
- **Columns:**
  - targets: "7/10" (bold when all are broken);
  - character;
  - end: a pill. Clear is green, fall muted red, timeout grey. Goal (M7s
    goal reached) is blue, aborted (aborted or lifecycle failure) amber, and
    prefix (an M8 route that stops at an archive cell) indigo;
  - last target: "3008 · 50.1 s"; for a clear, the completion ("446 · 7.43 s",
    green); "–" when no target broke; "?" when unknown (grey);
  - verdict: ✔ MATCH, ✖ DESYNC or · none, from this tool's replays;
  - role, milestone;
  - run: shortened in the middle, with the full episode path as a tooltip;
  - Episodes, in "Best per run" only;
  - tags: narrow, since only 4 episodes have any; a tooltip shows them when
    cut;
  - created: local time, e.g. "Sep 27 03:22".
- **Sorting:** the default is targets descending, then last-target tick
  ascending, with unknowns last. Click a heading to sort by it (again to
  reverse); ties keep the default order. Drag a heading edge to resize.
- **Look:** zebra rows, 28 px rows, bold headings, a light green tint on
  clears, a blue selection bar.
- **Keys:** Up/Down/PageUp/PageDown/Home/End move the selection; Enter or a
  double-click plays.
- **Details card** (key/value, like the viewer header):
  - The episode id and path are shown; the path is shortened in the middle,
    with the full path in a tooltip.
  - Then every non-empty field: character (and where it was recorded), stage,
    role, run, run id, worker, profile, observation, reward, end with detail,
    targets, last target with its source, end tick, steps, prefix rows,
    created (full local time), verdict, whether it is a test episode, each
    tag's answer and source, and sidecars.
  - Buttons: ▶ Play, Check (headless), Copy path, Open folder.
- **Status bar:** messages (viewer started, check progress and results, scan
  progress, and the scan's "not indexed" line, also shown at start-up), the index size and last scan time, and **Rescan** on the far
  right.
- **How it is drawn.** The table is drawn on a Canvas, visible rows only.
  This lets one cell carry its own colors (`ttk.Treeview` colors whole rows
  only), and all ~39k rows stay listed without the old 5,000-row cap.
- **Theme package.** A package such as sv-ttk would restyle only the ttk
  widgets (comboboxes, buttons, scrollbar). The table, pills and card are
  drawn directly, so it would change little, and I did not propose it.

## Local state (`_local/`)

| Path | Contents |
| --- | --- |
| `index.sqlite` | The cache (~42 MB, schema 2) |
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

### M8 routes and scan report (2026-10-03)

- **Why today's run seemed missing.** `runs/m8_rd_rd4` was already in the
  index, along with yesterday's `m8_rd` to `m8_rd_rd3`: 9 route folders. Its
  `m8_rd_route_v1` metadata was not understood, though:
  - no role, so the tests rule hid the routes by default;
  - no creation time, so the newest dated episode stayed Oct 1;
  - no targets, end or character.

  The viewer also refused to open routes (`artifact_schema` missing). The
  archives themselves are cells, not episodes, and were skipped without a
  word.
- **Offline tests:** 30/30. The new ones:
  - routes load, are checked, give MATCH from their own trace and DESYNC on
    a changed row; a `words` mismatch is refused; route ids are unique;
  - the scan report names archives, actions without metadata and
    unrecognized formats, with stable example paths, and persists it;
  - route rows have role route, tags, last target and the prefix end; an
    unrecognized format is listed and not hidden.
- **Real tree:** 41,207 episodes; the 9 routes are listed and none is
  hidden. Today's three rd4 clear routes top the default view (T_t clears at
  tick 2,314, 38.57 s).
- **Timing:** the rebuild took 418.9 s cold; a warm full rescan takes 51.1 s
  and an incremental scan 7.2 s.
- **Not launched:** no BattleShip process was started, so the routes were
  not replayed live. Their MATCH logic was checked offline against their own
  recorded replies (9/9).

### Last target, tests, best per run, Check filtered (2026-09-30)

- **Offline tests:** 28/28, including the new and rewritten tests.
  - Break-tick sources: `evaluation.json` and its `eval_metrics`
    fallback, `episodes.jsonl`, the gate-trace `targets` column (two
    targets on one tick), the decisions signatures (row t + 1 = tick t), MATCH
    replays, DESYNC ignored.
  - Last-target rules: exact count, replay first, curriculum prefix, every
    break inside the prefix is "?", clear = completion, 0 targets is "–".
  - The browser: the new default order, tests hidden (a `test` role and a
    `_` folder), the "N of M (K tests hidden)" count, the card's last target,
    sorting by last target, best per run with "4" and "2 of 4" counts.
  - Check filtered with a stand-in runner: the confirmation above the limit,
    live verdict and last-target updates, cancel, the final status.
- **Real index rebuilt** (schema 3) in 59 s.
  - The first build of this schema took 627 s: deleting each re-read
    episode's old facts scanned the whole table. The new `source_path`
    indexes fix it (an `m7p` full rescan went from 87.4 s to 5.6 s).
  - `load_rows` takes 2.0 s.
- **Coverage:** 95.3% of episodes have a known last target (table under
  "Last target").
- **Tags:** 4 episodes have any tag. Episode A
  (`runs/m7p/.../w04/.../episode_20260928T072129Z_44619208`) shows
  "left entry @3001 · crossing" and last target "3008 · 50.1 s (replay)".
- **Check filtered, live** on the real index, 8/8:
  - the 4 tagged episodes: 4 MATCH in 20.4 s, progress "checking 2/4 ...",
    the verdict column updated;
  - the 3,317-episode M7p list: asked first, then cancelled after 1;
  - no BattleShip process or session folder left.
  - Worker threads never call Tk: they post to a queue that the Tk thread
    drains. The first live run showed that calling Tk's `after()` from the
    check thread fails when the event loop is not driven by `mainloop`.
- **Viewer UI regression:** 13/13.

### Browser redesign (2026-09-30)

- **Offline tests:** 26/26. The new and rewritten tests cover:
  - the index with character, stage and tags ("?" episodes get no tags);
  - the character, `?`, tag and text filters, and the default sort;
  - verdict evidence (MATCH counts, DESYNC never does);
  - a schema 1 cache being dropped;
  - every character/stage source, with the copies checked against
    `rl/experiment_config`;
  - a stand-in Fox extractor adding tags with no index or browser change;
  - time, end and created texts;
  - per-character action-state names (225: Mario SpecialHi, Fox SpecialN,
    unknown "225"; all 12 tables);
  - the real browser on a temporary index: order, live filters with
    "N of M", tag search, the hidden stage filter, the card without empty
    fields, the run tooltip, keys, sorting.
- **Real index rebuilt** (schema 2, read-only): 39,341 episodes in 100 s.
  - `load_rows` takes 1.5 s; the browser opens in 1.75 s.
  - A filter over all rows takes 50-70 ms.
  - Tag, `list` and `show` results are as described under "Tags".
- **Viewer UI regression:** 13/13. 1x ran at 60.0 ticks/s.
  - The header reads "character Mario · stage btt_mario".
  - The action state showed Mario's own "SpecialN (223)".
- **Browser Play → viewer:** the viewer opened on the selected episode in
  0.9 s. Closing it left no BattleShip process or session folder.

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
