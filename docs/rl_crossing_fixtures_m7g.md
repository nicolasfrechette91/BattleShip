# M7g-a: Track 1 wall-crossing fixtures (audit, contract, capture tooling, validation status)

Status (2026-09-23):
- **Lower fixture: VALIDATED.** `rl/fixtures/m7g/lower_precision_2ad7b1da89d8.json`, captured live by the user and
  built with the route confirmed (section 8.1).
- **Upper fixture: VALIDATED.** `rl/fixtures/m7g/upper_moving_platform_8b9ecf2b967f.json`, captured live by the
  user and built with the route confirmed (section 8.2).
- Phase D is complete for both crossings (section 8.3).
- **Review gate:** the user accepted M7g-a (2026-09-23). The fixtures and capture records stay unchanged and are
  validation evidence only.
- **Observation v2 (Phases E-K):** done separately in M7g-b, without using these fixtures:
  [`rl_observation_v2_m7g.md`](rl_observation_v2_m7g.md).

Machine-readable companions: `docs/rl_crossing_fixture_m7g.schema.json` (fixture JSON Schema) and
`docs/rl_crossing_fixtures_m7g_validation.json` (preflight, audit, test and Phase D results).

## 1. What a crossing fixture is, and what it must never be

A crossing fixture is **validation evidence only**. It is a canonical Track 1 (`btt_s9_b8_v1`) action sequence.
Replayed from native tick 0 in a fresh BattleShip process, its native trajectory enters the region left of the tall
wall. It exists to show in the repository that the reported crossings are possible with the frozen Track 1 actions,
which would rule out an action-space impossibility behind the six-target ceiling (M7f).

A fixture is never:
- a PPO demonstration;
- behaviour-cloning data;
- a curriculum start state or prefix;
- reward shaping;
- a route label or preferred target order;
- a training-archive seed.

Nothing in the training, evaluation or reward stack imports the M7g modules. `rl/m7g_tests.py
unit_training_isolation` enforces this. Every fixture file carries the fixed `usage_restrictions` text.

The 7.43 TAS appears in M7g in only two roles:
- a **negative** control for the Track 1 importer, which rejects it and names its 8 non-Track 1 rows;
- a **positive** control for the crossing detector, which replays its raw native rows.

It is never converted, approximated or used as a fixture.

## 2. Phase A: repository preflight (all passed)

| check | result |
| --- | --- |
| `git status --short` | clean |
| `git log -5 --oneline` | `54e5bff` Expose BTT target identity for PORT diagnostics (M7f), `9b2578b`, `9d45235`, `e6fe909`, `0bd6f2d` |
| `git rev-list --left-right --count origin/main...HEAD` | `0 0`: HEAD = origin/main |
| `git submodule status` | decomp `54c5afc7` (rl-main, = origin/rl-main, M7f commit on top of `91d7b6b7`); libultraship `805f1950` (m6/raphnet-bypass, = origin); torch `3aa9c973`. All clean; the parent gitlinks equal them |
| `git diff --check` | exit 0 |
| M7d / M7e / M7f results | present (`runs/m7d`, `runs/m7e`, `runs/m7f`, docs) |
| M7f regression record | `runs/m7f/_regressions/20260923T132814Z/results.json`: **25 / 25**, ok |
| user configuration sha256 | `1b29d91b80051a13...` = the established value |
| executable sha256 | `10e8e15d4abe6060...` = the final M7f build |
| BattleShip / Python processes | none |
| loopback listeners in the port blocks | none |
| historical run files tracked by Git | none (`/runs/` ignored) |
| historical fingerprint (junctions not followed) | 80,058 files, 3,527,645,536 bytes, aggregate `b1d661660f98adca...` (`runs/m7g/_preflight/historical_before.json`) |

## 3. Phase B: capture and import audit

### 3.1 Mechanisms that exist

| mechanism | what it holds | tick 0 | human-usable | exact Track 1 check |
| --- | --- | --- | --- | --- |
| native `.btti` replay (`SSB64_BTT_INPUT`, netreplay.c) | native triples per tick, player 0 | yes (the first Go read) | only by writing or converting a file | yes, row by row (`native_to_track1`) |
| native live-input recording (`SSB64_REPLAY_RECORD`) | **VS battles only**. BTT play reads the controller directly, so nothing is recorded | - | no | - |
| `tools/bk2_to_btt_inputs.py` | BizHawk movie to `.btti`; start row chosen manually | manual | through an emulator | only after conversion |
| M4 artifacts (`actions.jsonl`, `rlaction_native_v1`) | native triples + consumed ticks. **No per-step positions** | yes (0..n-1) | no (written by training / evaluation) | yes |
| Track 1 indices with evaluation episodes | only in the in-memory `info` dict; never written to disk | - | - | - |
| M1c/M1d stepping client | one action per tick, raw replies | yes | would need a client that reads the human's input | by construction |
| manual-control client / sequence editor | **none existed** | - | - | - |
| validators | M1e, M2, M6, `m7d_run.replay_one`, `m7f_replay`, `m7f_trace` (per-tick replies, typed comparison) | - | - | - |

Physical input: while stepping, the injected action overwrites all four controller slots on every gameplay tick
(`sc1PBonusStageFuncReadReplay` -> `syNetInputFuncRead` -> `syNetInputPublishFrame`). A human pressing keys or a
gamepad cannot change the simulation. The visible window still reacts to hotkeys:
- Ctrl+R and the Esc-menu Reset button reset the game;
- the Esc menu can change tap-jump and auto Z-cancel, which alter physics;
- F1, F2 and F11 toggle the menu bar, mouse capture and fullscreen.

The capture tool therefore reads the keyboard globally, and the user keeps focus on the console (section 7).

### 3.2 Do the reported crossings already exist in a file? **No.**

The search covered:
- the repository, including all 80,058 files under `runs/` (by name and content);
- the parent directory `Smash_pc_port` and `guide.md`;
- `Bureau`, `Documents`, `Downloads` and OneDrive (names only).

Findings:
- The only recording that crosses the wall is the 7.43 TAS. It has 8 non-Track 1 rows: 94, 143, 144, 177, 181, 215, 377 and 434.
- The 13 BizHawk `.bk2` files in Downloads are third-party movies for other characters.
- No per-step position below x = -1650 exists anywhere except the TAS and its regression copies.

One historical Track 1 episode was outside the M7f replay census: the M7a pilot's only **seven-target** episode
(`runs/m7a_pilot_n5/workers/w01/artifacts/episode_20260922T021311Z_50bbb545`, 3,005 actions). M7g replayed it with the
target diagnostic:
- the native action digest `9911103d...` and the final observation were reproduced exactly;
- it broke `{0, 2, 3, 4, 5, 7, 9}`, all seven targets right of the wall;
- its minimum x was -1650.0 and it ended in a fall;
- **it is not a crossing.**

It is, however, the only recorded episode that broke the full right-of-wall set, including moving target 2 (M7f's
statement "never achieved" covered M7d / M7e only).

## 4. Stage geometry and the derived crossing boundary

`rl/m7g_fixture.decode_stage_geometry()` parses `MPGeometryData` of Mario's map from the checked-in stage source
`decomp/src/relocData/124_GRBonus1MarioFile2.c`: 26 vertices, 20 lines and 2 yakumono groups. Line kinds follow the
`MPLineInfo` order Floor, Ceil, RWall, LWall, and a line's flags are its first vertex's.

| line | kind | world coordinates | note |
| --- | --- | --- | --- |
| L0 | floor | (-2100, 3000)-(-1200, 3000) | wall-top ledge |
| L1 | floor | (2100, -450)-(3300, -450) | **raised right step; the user marked its top-left corner (2100, -450) as the lower-platform reference point** |
| L2 | floor, pass-through | (2100, -1500)-(1200, -1500) | thin drop-through platform |
| L3 | floor | (-3900, -1950)-(-2700, -1950) | left structure top |
| L4 | floor | (-1800, -2550)-(2100, -2550) | start floor (spawn (0, -2547)) |
| L9 | ceil | (-1200, 2700)-(-1800, 2700) | overhang underside |
| L13 | rwall | x -1800, y -2550..2700 | tall wall, right face |
| L17 | lwall | x -2100, y -2850..3000 | tall wall, left face |
| L19 | floor, pass-through, **moving** | (600, 300)-(-600, 300) relative to the group-2 DObj | moving platform: world x 2100..3300, surface y 1800..3600 (DObj y 1500..3300, 300-tick smoothstep loop) |

The remaining lines are listed in `docs/rl_crossing_fixtures_m7g_validation.json` and frozen in
`rl/m7g_tests.py FROZEN_LINES`. No vertex has the cliff flag, so no ledge can be grabbed anywhere on this stage.

**Derived boundaries** (computed, never hand-entered):
- The closed solid polygon that contains the spawn floor is L0, L1, L4, L6, L8-L13, L17 and L18.
- **Left region: `position_x < -2100`**, the minimum x of that polygon (the wall's left face L17).
- Wall right face x = -1800 (L13); wall top y = 3000 (ledge L0, x -2100..-1200); overhang underside y = 2700.
- Right step = L1, with corner (2100, -450).
- Moving platform = L19.

M7f's region constants agree (`unit_geometry_frozen`).

**Native validation of the decode.** In 11 historical M7f traces, every grounded step lies on a decoded floor line:
0 unmatched out of more than 17,000 grounded steps across the TAS in three host modes and eight policy / random
fixtures. Further checks:
- Mario pressed against the wall stops at x = -1650, which is the face at -1800 plus the collision diamond's
  half-width of 150.
- The TAS stands on the moving platform at y 2416-2486 while its height changes, which is the platform surface, not
  the DObj.

**Correction to earlier docs.** The M7f documents give the platform as "y 1500..3300". That is its DObj translate;
the standing surface is 300 higher (1800..3600). The historical M7f files are left unchanged.

## 5. Fixture contract `btt_crossing_fixture_v1`

A fixture is one JSON file, `rl/fixtures/m7g/<fixture_id>.json`, with
`fixture_id = <crossing>_<first 12 hex of the native action digest>`. The top-level keys are exactly those below;
additional keys are rejected.

| key | content |
| --- | --- |
| `contract` | `btt_crossing_fixture_v1` |
| `fixture_id` | see above |
| `crossing` | `lower_precision` or `upper_moving_platform` |
| `source` | `kind` (`user_recorded` / `imported` / `independently_searched`), the tool, the input device and keymap, `resumed_from` and a note |
| `task` | mario / break_the_targets_mario / us |
| `action_contract` | `btt_s9_b8_v1` |
| `start` | `{"tick": 0, "reset": "fresh_process", "hidden_prefix": false}` (constant) |
| `sequence` | `length`, `track1` ([stick, button] per tick), `native` (the exact table images), `track1_digest` (sha256 of `stick,button\n` lines), `native_action_digest` (the M7 tracker formula over `buttons,stick_x,stick_y,consumed_tick\n` with consumed ticks 0..n-1) |
| `provenance` | executable sha256, parent HEAD, dirty flag and dirty files, each submodule commit, verification UTC and directory |
| `geometry` | decoded lines + derived regions (`btt_stage_geometry_mario_v1`) and the source sha256 |
| `evidence` | `btt_crossing_evidence_v1` from the reference replay (below) |
| `route` | the declared crossing next to the route classifier's proposal: `declared`, `classifier` (rule, identity, reason), `agreement`, `review_required`, `notes`, `takeoff` (surface, tick, position, offset from the marked corner) |
| `verification` | `count` (at least 8), `all_identical`, per-run digests and returns, and every check result |
| `usage_restrictions` | the fixed restriction text |

`evidence` contains:
- `first_left_entry`: step, consumed tick, input tick, time_passed, x, y and ground state of the first native observation with x < -2100;
- `min_x` and `max_y`;
- `wall_top` (**reported separately, never a crossing proof on its own**): first step at or above y 3000, first step over the ledge (x <= -1200, y >= 3000), ledge ground contacts, and minimum x at wall-top height;
- `moving_platform`: grounded steps, contact runs, **riding steps** (consecutive grounded steps on it whose height changed, i.e. carried by a moving floor), first and last contact, and y range;
- `approach_surface`: the takeoff of the crossing itself, i.e. the last grounded surface other than the ledge top
  before the **first left-region step**; `last_grounded_before_entry` (the ledge top included);
- `crossing_path`: `over_ledge` only if Mario is over the ledge (x <= -1200, y >= 3000) between that takeoff and
  the entry; `crossing_over_ledge_step`; `earlier_over_ledge_steps` (reported only, for example a failed attempt that
  fell back to the right);
- **`surface_runs`**: the whole route as native ground contacts, in order. Each run gives the surface (a decoded
  line such as `L1`, `moving_platform` or `ground_unmatched`), its first and last step and tick, and where it began;
- **`trajectory`**: the complete native trajectory, one row per consumed tick: consumed tick, x, y, ground/air
  state, fighter status and the ground surface;
- `targets`: the M7f diagnostic breaks with native IDs, `broken_after_first_left_entry`, left targets 1 / 6 / 8 broken, and the M7f invariants;
- `terminal`: `clear` / `native_failure` / `sequence_end`, submitted actions, last consumed tick, final game status and targets;
- `ground_unmatched_steps`.

**Crossing proof vs route label.** Keeping a crossing and labelling its route are separate decisions.

A crossing is kept (a fixture is written) when these hard gates pass:
- the actions are exact Track 1 actions from tick 0;
- the native trajectory enters the left region;
- the 8 executions are identical;
- every action is consumed;
- the source, capture and integrity gates pass.

The route is recorded **as declared by you** and is never relabelled. The route classifier (`btt_route_rule_v1`)
only proposes a label from the native evidence:
- `upper_moving_platform`: the approach surface is the moving platform L19.
- `lower_precision`: the approach surface is the raised right step L1. The corner
  you marked on 2026-09-23, (2100, -450), identifies the lower-platform **area**. It does not establish that every
  valid lower crossing takes off from exactly L1.
- `unclassified`: anything else, such as another static takeoff (L2, L4), an unmatched ground point, or no
  grounded takeoff at all.

The proposal depends only on the takeoff surface. An unusual path, such as a left entry that is not over the
ledge, is flagged in `notes`.

`route.agreement` is `confirmed` when the classifier proposes the declared crossing. Otherwise it is `mismatch` (it
proposes the other crossing) or `unclassified`. In both of those cases, and whenever the route evidence is
incomplete (grounded steps on no decoded floor line, entry not over the ledge, invariant problems in the M7f
target diagnostic), the crossing is **still written as
declared** with `review_required: true` and explanatory `notes`, and `build` exits with code 3 so you can review it
and decide. `route.takeoff` always records the native takeoff surface, tick and position, and its offset from your
marked corner.

**Hard gates.** `build` writes a fixture only if all of the following hold (route agreement is not among them):
- **Tick 0:** every execution starts in a fresh process at tick 0 (`WaitingForAction`, step_count 0, observe input_tick 0, time_passed 0).
- **Track 1 only:** every action is one of the 72 Track 1 actions and every native row is its exact table image. Native values must be integers; a float such as 80.7 is rejected, never truncated. There are no analog-only values and no hidden prefix.
- **Tick alignment:** action i gives consumed_tick i, input_tick i + 1 and step_count i + 1.
- **Every action consumed:** no action follows a clear or a fall, so `sequence.length` equals the number of consumed ticks in every run.
- **Left entry:** the reference trajectory has a native left entry (x < -2100).
- **Repeatability:** all 8 executions of the verification matrix (section 6) produce identical trajectories, action digests, `btt_policy_obs_v1` bytes and reward v1 / v2 returns. The diagnostic-on runs, including the real standby promotion, also produce identical `targets`. The M7f diagnostic's own invariant checks are recorded and flagged for review, but do not gate.
- **Capture match:** a live capture's own trajectory digest (the visible session) equals the replay's, and the gameplay settings (tap-jump, auto Z-cancel, stage hazards) are unchanged since the capture.
- **Honest source:** `--source` must equal the kind the draft recorded.
  - `user_recorded` needs a live keyboard or XInput capture draft carrying its trajectory digest.
  - A live continuation of an imported or searched prefix is recorded as `imported`.
  - A plain script, list, `.btti` or artifact can only be `imported` or `independently_searched`.
- **Integrity:** the user configuration is unchanged and no process leaked.
- **No overwrite, no twins:** an existing `rl/fixtures/m7g/<fixture_id>.json` is never replaced (it is created atomically and only if absent), and a sequence already preserved as one crossing is never written again as the other, so lower and upper fixtures stay distinct recordings (`build` refuses; `unit_fixture_files` checks that no two fixtures share a sequence).

**The recording is never touched.** A capture directory (`session.jsonl`, `draft.json`, `draft.txt`,
`capture_trace.json.gz`, `summary.json`) is only ever read:
- `build` writes its replays to a new `runs/m7g/fixtures/<id>/<utc>/`;
- every output (`build`, `verify`, `evidence`, `play`, `import`, `export-script`) inside any capture recording directory is refused, whether a new sub-directory or a new file name;
- `verify`, `evidence` and `play` also refuse a non-empty output directory;
- `import --out` and `export-script --out` refuse an existing file.

When a crossing that did enter the left region fails a hard gate (for example a capture-vs-replay mismatch after a
setting changed mid-capture), `build` reports that in `verification.json` and the recording stays as it was.

**Document validation** (`validate_fixture_document`, used by `check-fixture` and `unit_fixture_files`). It trusts
nothing it can re-derive, and it reports problems without raising:
- geometry is decoded afresh from the stage source; the source sha256 and derived regions must match;
- the route assessment is recomputed from the stored native evidence and the declared crossing. The structured fields (declared, proposal, agreement, review flag, takeoff) must equal the stored `route`; the prose notes are not compared. A `mismatch` or `unclassified` route is valid; a forged `confirmed` or a changed `declared` is not. A fixture assessed under an older route rule stays valid;
- the trajectory must hold one row per consumed tick and show the first left entry where the evidence says;
- digests, native rows and `fixture_id` are recomputed from the Track 1 sequence;
- `task`, provenance (executable sha256, revisions, verification time, user-config sha256), `evidence.crossed`, `terminal.submitted == length`, and verification (at least 8 runs, each covering every action, `all_identical` exactly true) are checked.

The stored evidence itself can only be reproduced by replaying the fixture (`verify`).

## 6. Verification matrix (`rl/m7g_crossing.py verify` / `build`)

| run | host mode | purpose |
| --- | --- | --- |
| `cold_nrr` | no-render + Raphnet bypass, target diagnostic on | reference and evidence |
| `cold_nrr_r2` | the same | cold repeatability |
| `cold_nr` | no-render | Raphnet bypass is neutral |
| `visible` | normal window | the visible trajectory is the same |
| `diag_off` | no-render + Raphnet, diagnostic off | the diagnostic is neutral |
| `parked` | no-render + Raphnet, parked 12 s at tick 0 | the standby condition (M7f method) |
| `standby_ep1_cold_start`, `standby_ep2_standby_promoted` | the real M7c lifecycle (`M7BattleShipBTTEnv`, standby on, no-render + Raphnet, diagnostic on), raw replies shadowed on the episode's own client | promotion equivalence, including `targets` and action digests |

The trajectory digest is sha256 over canonical JSON of (state, step_count, consumed_tick, the 16 gameplay observation
fields) for the tick-0 observe and every step. `host_frame` is compared separately and reported for information.

## 7. How to capture the two crossings (user instructions)

The capture is a normal fresh BattleShip process in a visible window, driven one native tick at a time by
`rl/m7g_capture.py`. Every tick it reads your keyboard (or an XInput gamepad) and sends exactly one Track 1 action.
Whatever you do is therefore Track 1 by construction and starts at native tick 0.

1. Close every BattleShip window, open a console in the repository and run:
   ```
   python rl/m7g_capture.py play --label lower
   ```
   Keep **keyboard focus on the console**. The tool reads keys globally and you watch the game window. **Do not press
   Ctrl+R or Esc, or change any setting, in the game window.**
2. Keys (default; `--keymap FILE.json` rebinds them):

   | function | key |
   | --- | --- |
   | stick | arrow keys (8 directions) |
   | A | X |
   | B | C |
   | C-up (jump) | Space |
   | C-left | V |
   | L | A |
   | R | S |
   | Z | Z |

   Only one button per tick exists in Track 1; the most recently pressed held button wins. Controls:
   - **P** pauses and resumes;
   - **.** advances one tick while paused (frame advance, for the precise jump);
   - **[** and **]** make the game slower and faster;
   - **Ctrl+Q** saves and quits.

   Gamepad: `--input xinput`. Left stick or D-pad for the stick, A / B / Y / X / LB / RB / LT for A / B / C-up /
   C-left / L / R / Z, Start to pause, right-stick click to advance, Back to save and quit. If the pad disconnects,
   the capture pauses and records nothing until it is reconnected and Start is pressed.
3. Speed: the default visible stepping runs about 30 ticks/s, half speed (33.3 ms per tick, measured). `--realtime`
   gives 60 ticks/s (16.7 ms, measured) and produces the identical native trajectory. `--tick-ms 100` slows play down
   further.
4. The console prints Mario's native position, the surface he stands on, target breaks and **"NATIVE LEFT-OF-WALL
   ENTRY"** when x < -2100. The session stops by itself on a clear or a fall. Otherwise press Ctrl+Q once you are
   past the wall (or after breaking a left target, which is preferred but optional).
5. To retry only the hard part, resume from a previous draft. For example, keep its first 300 ticks and play on from
   there:
   ```
   python rl/m7g_capture.py play --label lower2 --resume runs/m7g/capture/<dir>/draft.json --at 300
   ```
   The prefix is replayed from tick 0 in the same fresh process and becomes part of the new sequence. It is not
   hidden. Only Ctrl+Q is honoured while the prefix replays. At the hand-over the capture **pauses**: press P to
   play, or . to go one tick at a time. A resumed session keeps `user_recorded` only if its prefix was itself
   user-recorded.
   If a session ends abnormally (the game window closed, the connection lost), the draft, script and summary are
   still written. The per-tick autosave `session.jsonl` is also importable (`--resume`, `import`, `build`).
6. Build the fixture, which runs the full verification matrix headless (about a minute):
   ```
   python rl/m7g_crossing.py build runs/m7g/capture/<dir>/draft.json --crossing lower_precision --source user_recorded
   ```
   Do the same with `--crossing upper_moving_platform` for the moving-platform crossing. The exit code tells you the
   outcome:
   - **0:** fixture written, route confirmed by the classifier.
   - **3:** fixture written **as declared**, but the route needs your review. The printed notes and the fixture's
     `route` section say why (for example the takeoff was not exactly L1), with the native takeoff surface, its
     offset from your marked corner and the full trajectory. Nothing is relabelled or discarded.
   - **1:** no fixture. Either there was no native left entry, or a hard gate failed (reasons in
     `runs/m7g/fixtures/<id>/<utc>/verification.json`). The draft is untouched either way, so you can simply retry
     or resume.
7. Check: `python rl/m7g_crossing.py check-fixture rl/fixtures/m7g/<fixture_id>.json`, then
   `python rl/m7g_tests.py unit_fixture_files`.

**Alternative: import instead of playing.** Write a `btt_track1_script_v1` text file, one row per run:
`<count> <stick> <button>`, where the stick is N R UR U UL L DL D DR (or 0-8) and the button is - A B CU CL L R Z
(or 0-7). Then run `python rl/m7g_capture.py import FILE --out draft.json` and `build` it with `--source imported`.
Files may be UTF-8 (with or without BOM) or BOM-marked UTF-16, as PowerShell redirection writes.
Any row that is not exactly one of the 72 Track 1 actions is rejected with its row number. JSON lists of
[stick, button] or [buttons, stick_x, stick_y], `.btti` files and M4 artifact directories are accepted under the same
rule. `python rl/m7g_capture.py export-script DRAFT` prints any draft as editable text.

Capture outputs: `runs/m7g/capture/<utc>_<label>/`, containing
- `session.jsonl`: an autosave line per consumed tick, so a crash keeps everything;
- `draft.json`: `btt_track1_draft_v1`, with the capture trajectory digest and evidence;
- `draft.txt`;
- `capture_trace.json.gz`: every raw reply;
- `summary.json`.

## 8. Phase D status

### 8.1 Lower crossing fixture `lower_precision_2ad7b1da89d8` (validated 2026-09-23)

The user captured it live with the keyboard (`runs/m7g/capture/20260923T201117Z_lower/`, visible stepping at
33.1 ms per tick, no pauses). The sequence is 1,525 Track 1 actions from tick 0. The warm-up inputs before the
attempt are part of the sequence: they place Mario, and a fixture has no hidden prefix. Route evidence:

| event | consumed tick | native position |
| --- | --- | --- |
| last standing on the raised right step L1 (takeoff) | 912 (in-game 15.2 s) | (2205.2, -450), 105.2 right of the marked corner |
| first over the ledge | 1015 | (-1200.0, 3050.5) |
| standing on the ledge top L0 | 1030-1061 | from (-1515.5, 3000) |
| **first native left-region entry** | **1093** | **(-2100.9, 4356.8)** |
| standing on the left structure L3 | 1292-1332 | from (-3848.5, -1950) |
| minimum x | 1362 | (-4565.4, -2844.4) |
| fall (native failure, the last action) | 1524 | - |

- **Moving platform:** never touched.
- **Ground contacts:** every one lies on a decoded floor line.
- **Targets broken:** 0 (tick 603) and 7 (995) before the crossing; **6 (1189), 8 (1246) and 1 (1394)** after it.
  These are the first Track 1 breaks of any left-of-wall target in the project.
- **Route:** declared `lower_precision`; the classifier proposes `lower_precision`; agreement `confirmed`; no review needed.

**Verification** (`runs/m7g/fixtures/lower_precision_2ad7b1da89d8/20260923T201405Z/verification.json`): all 16
checks pass, and `check-fixture` and `unit_fixture_files` are valid.
- All 8 executions are identical: cold x2, no-render, visible window, diagnostic off, parked 12 s, and the real
  M7c cold start + promoted standby. They match on trajectory `b9fe2b7a...`, targets `a2e2a376...`, native action
  digest `2ad7b1da...`, `btt_policy_obs_v1` bytes and returns (v1 3.475, v2 -1.525).
- The replay equals the user's visible capture.
- The executable was `10e8e15d...`; the user configuration was unchanged; no process was left.
- The capture recording was untouched.

### 8.2 Upper crossing fixture `upper_moving_platform_8b9ecf2b967f` (validated 2026-09-23)

The user captured it live with the keyboard (`runs/m7g/capture/20260923T201858Z_upper/`, visible stepping, no
pauses). The sequence is 681 Track 1 actions from tick 0 and ends when the user saved and quit (`sequence_end`).
Route evidence:

| event | consumed tick | native position |
| --- | --- | --- |
| riding the moving platform | 247-266 | 20 grounded steps, 19 of them carried upwards (y 1818.7 -> 1964.7) |
| takeoff from the moving platform | 266 | (2243.0, 1964.7) |
| first over the ledge | 386 | (-1203.6, 3759.3) |
| standing on the ledge top L0 | 431-463 | from (-1884.7, 3000) |
| **first native left-region entry** (stepping off the ledge's left end) | **464** | **(-2100.7, 3000.0)** |
| minimum x | 532 | (-3397.5, 758.0) |
| standing on the left structure L3 | 666-680 | from (-3397.5, -1950) |

- **Targets broken:** only **8** (tick 592), after the crossing.
- **Ground contacts:** every one lies on a decoded floor line.
- **Route:** declared `upper_moving_platform`; the classifier proposes `upper_moving_platform`; agreement `confirmed`; no review needed.

**Verification** (`runs/m7g/fixtures/upper_moving_platform_8b9ecf2b967f/20260923T202016Z/verification.json`): all 16
checks pass.
- All 8 executions are identical, including the visible window and the real standby promotion (trajectory
  `a743dd9a...`, returns v1 and v2 0.319).
- The replay equals the user's visible capture.
- The executable was `10e8e15d...`; the user configuration was unchanged; no process was left.
- The capture recording was untouched.
- `check-fixture` is valid; `unit_fixture_files` validates both fixtures and confirms they are distinct recordings.

### 8.3 Requirement table (both fixtures validated)

| # | requirement | status | evidence |
| --- | --- | --- | --- |
| 1 | every action in the 72-action space | **PASS** (lower + upper) | `unit_import_formats` (analog 81, C-down, multi-button, Start rejected with row numbers; TAS rejected); capture sends table images only |
| 2 | replay begins at tick 0 | PASS (lower + upper) | `fresh_tick0` in every run of `game_verify_matrix` |
| 3 | first action consumes tick 0 | PASS (lower + upper) | `first_action_consumes_tick0` |
| 4 | contiguous consumed ticks | PASS (lower + upper) | `contiguous_ticks`; capture autosave consumed_tick = i |
| 5 | native left-region entry | **PASS** (lower tick 1093, upper tick 464) | detector positive control: the TAS enters at consumed tick 359 (x -2128.9, y 3440.8) |
| 6 | lower fixture uses the lower crossing | **PASS** (takeoff L1 at 912, route confirmed) | classifier rule implemented (approach surface L1); a disagreement is recorded for review (`route.agreement`), never a rejection; synthetic cases in the self-test |
| 7 | upper fixture contacts / uses the moving platform | **PASS** (takeoff from the platform at tick 266 after 19 riding steps, route confirmed) | classifier rule implemented (approach surface L19; riding steps recorded as evidence), disagreement recorded for review; TAS control: 5 grounded platform steps, 4 riding |
| 8 | target-identity diagnostics consistent | PASS (lower + upper) | `target_diag_invariants`, `identical_targets_diag` |
| 9 | cold execution repeats | PASS (lower + upper) | `cold_nrr` = `cold_nrr_r2` |
| 10 | standby execution repeats | PASS (lower + upper) | parked 12 s and real M7c promotion = cold |
| 11 | no-render and Raphnet bypass repeat | PASS (lower + upper) | `cold_nr` = `cold_nrr` |
| 12 | visible follows the same trajectory | PASS (lower + upper) | `visible` = `cold_nrr`; capture (visible) = replay |
| 13 | identical action and observation digests | PASS (lower + upper) | 8 of 8 identical |
| 14 | existing policy observations unchanged | PASS (lower + upper) | `identical_policy_obs_v1` (the frozen v1 adapter, byte-level) |
| 15 | existing rewards unchanged | PASS (lower + upper) | `identical_rewards` (v1 and v2) |
| 16 | no gameplay or native replay regression | PASS | no native, decomp, submodule or inherited file changed; regression chain (section 9) |

"PASS" means the check passed in the 8-run verification of both fixtures (sections 8.1 and 8.2). Before that, the
same checks were exercised on non-crossing Track 1 sequences: a scripted 96-action capture, a historical M7e
six-target artifact of 3,600 actions, and the M7a seven-target episode.

## 9. Validation of the tooling

`python rl/m7g_tests.py`: **18 / 18 PASS** (`runs/m7g/_tests_final_20260923T154107Z`; summary in
`docs/rl_crossing_fixtures_m7g_validation.json`).
- **unit, 9 / 9:**
  - the contract self-test, including three multi-attempt anchoring scenarios, float rejection and 20 validator mutations;
  - frozen geometry;
  - import formats, including BOM / UTF-16, the autosave and float rejection;
  - input mapping;
  - schema agreement;
  - the `build` positive path with a stubbed `verify` (document assembly, validator and the full JSON schema). The same crossing declared as the other route is **kept as declared** with a `mismatch` route flagged for review. A relabelled source, a rebuild over an existing fixture and one sequence as both crossings are refused. Clearly a plumbing test, written only to the test root;
  - fixture files;
  - training isolation (every `rl/**/*.py`, `rl/configs/**/*.toml`, `tools/*.py`, any path form);
  - historical evidence (8 policy / random traces + 3 TAS traces present and checked).
- **game, 9 / 9:**
  - scripted capture with pause and frame advance;
  - visible vs `--realtime` capture: identical trajectory, 33.33 vs 16.66 ms per tick;
  - resume, pausing at the hand-over;
  - the full 8-run matrix: identical trajectories, action digests, `targets`, policy bytes and returns, including the real standby promotion; capture matched;
  - `build` refuses a non-crossing draft and a contradictory source label and writes no file. **Every file of the capture recording stays byte-identical** (size, mtime, sha256). An output inside the capture directory is refused before anything runs;
  - capture error path: the draft is kept, the autosave is importable, no process is left;
  - TAS detector control;
  - M7a seven-target reproduction;
  - M7e six-target quick matrix.

**Review.** An adversarial review of the new modules (3 lenses, every finding independently re-verified) confirmed
22 defects, all fixed and covered by the tests above. The most important:
- the crossing identity was anchored on the first ledge visit instead of the crossing's own takeoff;
- the validator trusted stored fields;
- actions after a terminal step were accepted;
- a capture error discarded the draft;
- `--source` could relabel a draft.

**Regression chain.** M7g-a makes no native change, so this confirms the inherited stack is untouched:
`python rl/m7f_regressions.py --keep-going --root runs/m7g/_regressions/20260923T150926Z` gave **25 / 25 PASS**:
- the native 468-row TAS: `COMPLETE input_tick=447 time_passed=446`, checksum `0x93E9EFB4`, result 10 / 446 / 447;
- M1e with the diagnostic off and on: 447 actions, last consumed tick 446, 21 rows unsent;
- M7f unit + game, M7e, M7d, M7c standby, M7b config and smoke, M7a smoke, M6, M5, M4, M3, M2, M1d;
- `git diff --check` in the parent and decomp.

The user configuration sha256 was unchanged throughout. Its mtime changes from `m7_smoke` onward, the documented
inherited behaviour of suites that run with cwd `build-us/Release`.

**Historical integrity** (`runs/m7g/_preflight/historical_integrity.json`, junctions not followed, `runs/m7g`
excluded):
- all 80,058 files present under `runs/` at the M7g preflight are byte-identical, with unchanged mtimes, after all
  M7g-a work (0 removed, 0 changed, 0 touched);
- 16 files were added: the default-root directories the inherited M7e `existing_suites` case creates on each chain
  run (`runs/_m7b_tests_<utc>` and `runs/_m7c_tests_<utc>`).

**Process hygiene:** after every suite, and at the end, there were no BattleShip processes and no listeners in the
port blocks.

## 10. Limitations

- Moving-platform contact is inferred from native state plus collision geometry: grounded (`ground_air_state` 0)
  inside the platform's x span, at a height where no static floor exists, within its surface range, and "riding" when
  the grounded height changes between consecutive ticks. The native `coll_data.floor_line_id` is not exposed by any
  existing channel; exposing it is native work deferred to the observation-v2 phase.
- The capture tool drives the visible window through stepping at 30 (or 60) ticks/s. It is not a native recording of
  free-running play. The captured trajectory is re-verified headless before a fixture exists.
- Keyboard input is read globally (`GetAsyncKeyState`), which works whichever window has focus. Game-window hotkeys
  (Ctrl+R, Esc menu) remain a user hazard. They are documented and would be caught by the capture-vs-replay
  comparison, never silently accepted.
- The route classifier's lower rule follows your marked corner (L1). A genuine crossing from anywhere else is kept
  as declared with `route.agreement` `unclassified` or `mismatch` and `review_required`. The rule has not yet met a
  real lower or upper Track 1 crossing (the upper rule was checked only on the non-Track 1 TAS).
- The positive `build` path has run end to end for both fixtures. The route-mismatch path (exit 3) has still only
  been exercised with the stubbed plumbing test, because both real crossings were confirmed.
- Document validation re-derives everything it can without the game. That the stored evidence belongs to the stored
  sequence is proven only by replaying it (`verify`), which the build does 8 times.

## 11. Files (parent repository only; no decomp, libultraship, torch, native or inherited-file change)

New:
- `rl/m7g_fixture.py`, `rl/m7g_crossing.py`, `rl/m7g_capture.py`, `rl/m7g_tests.py`;
- `docs/rl_crossing_fixtures_m7g.md`, `docs/rl_crossing_fixture_m7g.schema.json`, `docs/rl_crossing_fixtures_m7g_validation.json`.

Fixtures go to `rl/fixtures/m7g/` once built (the directory does not exist yet). Run data (captures, verifications,
tests, regressions) goes to the ignored `runs/m7g/`.
