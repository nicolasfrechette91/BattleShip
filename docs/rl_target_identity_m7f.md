# M7f target identity (`btt_target_identity_v1`)

Status: implemented and validated (sections 1-5 were written before implementation; sections 6-8 record what was
built and measured). Nothing here is committed; see section 8 for the separate submodule / parent commit order.

M7f adds an opt-in, PORT-only native diagnostic that says **which** of the ten Break-the-Targets targets remain and
when each one broke. It exists to diagnose the six-target ceiling observed across 11,767 M7d/M7e episodes. It is a
diagnostic only: it is never part of the policy input, the reward, or the existing observation contract.

## 1. Native facts this design rests on

All ten targets are items created synchronously in `sc1PBonusStageMakeTargets`
(`decomp/src/sc/sc1pmode/sc1pbonusstage.c`), which walks the stage file's target `DObjDesc` array. For Mario that is
relocData file 124 (`GRBonus1MarioFile2`) at offset `0x2150`; the loop skips entry 0 and stops at the `id == 18`
terminator, so loop index `k = 0..9` reads `DObjDesc[k + 1]` and the anim-joint slot `k + 1`. The game keeps no
per-target identity: `gGRCommonStruct.bonus1.target_count` (u8) is an anonymous count, and the HUD sprite removed on a
break is chosen by the count, not by the target.

A target breaks only in `itTargetCommonProcDamage` (`decomp/src/it/itground/ittarget.c`): damage from any number of
hitboxes is summed into `damage_queue` and applied by one priority-0 process per item per frame; returning TRUE
destroys the item inside the same `gcRunAll`. Same-frame breaks run in link order, which is spawn order. The controller
read (which consumes tick `T` and increments the netinput tick) runs before the scene update, so inside the break
`syNetInputGetTick() == T + 1`, the `input_tick` of the post-update observation paired with the step whose
`consumed_tick` is `T`.

Only entry `k = 2` has an anim joint: it is the one moving target (x fixed, y oscillating). The other nine have no
update/map process and zero velocity, so they never move.

## 2. Stable ID rule

**Target ID = the spawn loop index `k` (0..9) of `sc1PBonusStageMakeTargets`, i.e. the position of the target's
descriptor in the stage file's `DObjDesc` array, minus the skipped root entry.** The ID is assigned from the loop
counter at the moment the item is created (`gGRCommonStruct.bonus1.target_count` before its increment), from ROM stage
data. It does not depend on pointer values, allocation order, host frames, render mode, controller backend, process
startup mode or timing, so it is identical across process restarts, visible/no-render, Raphnet on/off, cold/standby,
interactive stepping and native replay. The item `GObj*` is kept only as a transient in-process handle to recognise
which live target `ProcDamage` was called for; it is compared, never exported and never dereferenced after the break
(GObjs come from one LIFO pool shared by every object kind, so a freed pointer can be reused in the same frame).

Validation (section 6) must show this empirically in every mode; the argument above is the reason it can hold.

## 3. Native instrumentation (PORT-only)

Decomp submodule (branch `rl-main`), all inside `#ifdef PORT`:

* `sc1pbonusstage.c`: a PORT-only static table, filled by `rlGameNoteTargetSpawn(k, item_gobj, &translate,
  animated)` from the existing PORT block of the spawn loop, updated by `rlGameNoteTargetBreak(item_gobj)`, read by
  `rlGameFillTargets(RLTargetDiag *)`. A compile-time assert ties `RL_TARGET_COUNT` to `SCBATTLE_BONUSGAME_TASK_MAX`.
* `ittarget.c`: one PORT-only call `rlGameNoteTargetBreak(item_gobj)` in `itTargetCommonProcDamage`, before the
  anonymous `sc1PBonusStageUpdateTargetCount()`.

Both hooks return immediately unless the diagnostic is enabled. They write only the PORT-only table; they read game
state (`target_count`, `time_passed`, the item's root DObj translate) and never write it. `rlGameFillTargets` walks the
item link read-only to count live target items, as an independent cross-check of the hook-derived mask.

Parent repository (`port/rl`): `rl.h` (structs, constants, prototypes), `rl_boot.cpp` (the opt-in flag),
`rl_observation.cpp` (fill at the same post-update capture as the observation), `rl_step.cpp` (pair with the step
result under the M1c mutex, latched with the step count exactly like M4 `timing`), `rl_transport.cpp` (additive wire
key), `rl_result.cpp` (additive result-JSON object on a clear), new `rl_targets.cpp` / `rl_targets.h` (one JSON
serialiser shared by transport and result). No libultraship or torch change.

### 3.1 Native structure (`port/rl/rl.h`, stdint only)

`RL_TARGET_DIAG_SCHEMA = 1`, `RL_TARGET_COUNT = 10`.

| field | type | meaning |
| --- | --- | --- |
| `target_schema` | u32 | `RL_TARGET_DIAG_SCHEMA` |
| `input_tick` | u32 | port stamp: `syNetInputGetTick()` at the capture; equals the paired observation's `input_tick` |
| `scene_active` | u32 | 1 = BTT scene current and battle state present (the `btt_active` guard); link counts valid only then |
| `scene_entries` | u32 | spawn-table resets (BTT scene entries) since process start; 1 in every RL episode |
| `spawn_count` | u32 | targets recorded by the spawn loop in this scene entry (10) |
| `remaining_mask` | u32 | bit `i` set = target `i` spawned and not broken. **The one authoritative mask**; broken = `(1<<spawn_count)-1` minus it |
| `break_count` | u32 | break events recorded in this scene entry |
| `anomaly_flags` | u32 | bit 0 spawn overflow, 1 break of an unknown item, 2 repeated break of one ID, 3 break with the count already 0 (PORT guard path), 4 link walk disagrees with the mask |
| `link_checked` | u32 | 1 = the item-link cross-check ran (scene active and its object links still populated); 0 before the scene or once the scene task has ended (`gcEjectAll` empties every link, the fighter link included, while `scene_curr` is still BTT), with both `link_*` counts 0 |
| `link_live_targets` | u32 | live `nITKindTarget` items on the item link at the capture (`link_checked` only) |
| `link_unmatched` | u32 | of those, items that are not an unbroken table entry (`link_checked` only) |
| `targets[10]` | record | per ID, below |

Per-ID record: `animated` (u32, anim joint attached at spawn), `spawn_x/y/z` (f32, the descriptor translate),
`break_order` (u32, 1..10, 0 while unbroken), `break_input_tick` (u32, `syNetInputGetTick()` inside the breaking
update = consumed_tick + 1), `break_time_passed` (u32, `SCBattleState::time_passed` inside that update; equals the
breaking reply's observation `time_passed`, which is the consumed tick while the battle timer runs),
`break_x/y/z` (f32, root DObj translate at the break; for the moving target this is where it actually was).

### 3.2 Wire and versioning

* Enabled only with `SSB64_RL_TARGET_DIAG=1` together with `SSB64_RL_BTT=1` (stepping **or** native replay). Unset, the
  hooks return at once and every reply, log line and result file is byte-identical to the pre-M7f executable.
* Protocol stays 1 and every change is additive, following the M4 `timing` and M3 `observe` precedents:
  * `status` gains `"target_diag": true` only when enabled;
  * `observe` and `step` replies gain a top-level `"targets"` object only when enabled, captured at the same
    post-update as the reply's `observation` (the step's copy is latched under the M1c mutex with its step count);
  * a clear's result JSON gains a trailing `"target_identity"` object only when enabled (the native 468-row replay
    has no transport; this is its channel).
* `"targets"` carries `"contract": "btt_target_identity_v1"`, `"target_schema": 1` and the fields of 3.1, with the
  records as a list `[{"id": i, "animated", "spawn": [x,y,z], "break_order", "break_input_tick",
  "break_time_passed", "break": [x,y,z]}]`.
* `RLObservation`, `RL_OBSERVATION_SCHEMA = 1`, `RL_STEP_SCHEMA = 1` and the 17-key wire `observation` object are
  unchanged. Nothing is ever added inside `observation` (the Python client rejects unknown observation keys by design).

### 3.3 Python representation and compatibility

* New modules only (`rl/m7f_*`); no inherited Python file changes. Raw replies are captured by shadowing
  `client.request` on the client instance (the `btt_parallel._time_client` precedent), so `resubmit_actions`,
  `StepResult`, the Gym observation, the 15-value `btt_policy_obs_v1` adapter and both reward contracts are untouched
  and never see the diagnostic.
* The M7f reader requires `status.target_diag is True` and `targets.contract == "btt_target_identity_v1"` and
  `target_schema == 1`; anything else (old executable, flag missing, unknown schema) is a clear error, never a guess.
* Break events are derived in Python from consecutive post-update masks: a bit that clears in the reply of the step
  with `consumed_tick T` is a break at consumed tick `T`, resulting `input_tick T + 1`; several IDs may break in one
  step. The native `break_input_tick` must equal `T + 1` (cross-check, not a second source of truth).

### 3.4 Artifacts

Historical artifacts are never rewritten; `actions.jsonl` stays the canonical replay truth. New diagnostic replays write
under `runs/m7f/` a record per replayed sequence: link back to the source (milestone, run, seed, checkpoint/set,
evaluation mode, episode id, native action digest, artifact path, evaluation row), the diagnostic executable sha256
and contract id, the initial mapping, the lossless mask-change events, the per-ID native break records, the final mask
and the reproduction checks against the historical row.

## 4. Why gameplay cannot change

* Default mode: the only new code on any gameplay path is a flag test at the top of two PORT-only hooks.
* Diagnostic mode: the hooks and the fill function only read game state and write PORT-only static memory; no game
  variable, allocator, RNG, list, process or input is touched; the fill runs in the post-update listener, after the
  game update and before the next controller read. The link walk follows `link_next` only.
* Non-PORT (byte-matching) sources: every edit is inside `#ifdef PORT`; `rl/m7f_nonport_view.py` proves the non-PORT
  view of each edited decomp file is text-identical to the pinned rl-main revision.
* Empirically: the pre-change executable (sha256 `57d61fe0...`, preserved runnable under `runs/m7f/_exe/pre_m7f`) and
  the post-change executable, with the diagnostic off and on, must produce identical replies (every key except the
  new `targets`, all 17 observation fields including `host_frame`), identical result JSON and the native checksum
  `0x93E9EFB4`, on the TAS in three host modes and on eight pinned historical artifacts.

## 5. Stage regions (for descriptive labels only)

Derived from the stage's collision geometry (relocData file 124 `MPVertexData`): a tall wall occupies
`-2100 <= x <= -1800` from `y = -2850` up to `y = 3000`; the start floor runs from `x = -1800` to `x = 2100` at
`y = -2550` with Mario's spawn at `(0, -2547)`; a raised block starts at `x = 2100`; the stage's moving platform is at
`x = 2700`, `y` 1500..3300. Labels applied to **natively measured** target positions:

| label | rule |
| --- | --- |
| `left_of_wall` | spawn x < -2100 |
| `central` | -1800 < spawn x < 2100 (the start region) |
| `upper_right_moving` | `animated == 1` |
| `right` | spawn x > 2100 and not animated |

The IDs themselves come only from the native spawn loop, never from these labels or from any image.

## 6. What was built

Decomp submodule (`decomp`, branch `rl-main`, pinned `91d7b6b7`; uncommitted, +214 lines, all inside `#ifdef PORT`):

* `src/sc/sc1pmode/sc1pbonusstage.c`: compile-time assert `RL_TARGET_COUNT == SCBATTLE_BONUSGAME_TASK_MAX`; the
  PORT-only table `SC1PBonusStageRLTargets` with `rlGameNoteTargetSpawn` (static), `rlGameNoteTargetBreak` and
  `rlGameFillTargets`; one call in the existing PORT block of the `sc1PBonusStageMakeTargets` loop.
* `src/it/itground/ittarget.c`: a prototype in the existing PORT extern block and one PORT-only call to
  `rlGameNoteTargetBreak(item_gobj)` in `itTargetCommonProcDamage`, before `sc1PBonusStageUpdateTargetCount()`.

Parent repository: `port/rl/rl.h` (M7f section: `RLTargetRecord`, `RLTargetDiag`, schema/count/anomaly constants,
prototypes; `RLObservation` and `RLStepResult` untouched), `rl_boot.cpp` (`SSB64_RL_TARGET_DIAG`, its own log line;
the existing "enabled" line is unchanged), `rl_observation.cpp` (fill + stamp in the existing capture callback),
`rl_step.cpp` (`sLatestTargets` / `sResultTargets` / `sTargetsLast` paired and latched under `sMutex`, two getters,
`rlStepOnObservation` kept as a wrapper), `rl_transport.cpp` (three additive keys, each only when enabled),
`rl_result.cpp` (additive trailing `target_identity`, only when enabled), new `rl_targets.h` / `rl_targets.cpp` (the
one JSON renderer). No CMake, libultraship or torch change; the new `.cpp` is picked up by the existing
`CONFIGURE_DEPENDS` glob. Line endings of every edited file are preserved (CRLF files stay CRLF, LF files stay LF).

Inherited Python file modified: `rl/m7e_tests.py`, to repair a stale, state-dependent test (section 7.1); no other
inherited Python file changed. New Python: `rl/m7f_targets.py` (contract parser, per-reply invariants, event
derivation, region labels), `rl/m7f_trace.py` (trace capture, native replay, pre/post comparison),
`rl/m7f_validate.py` (Phase D), `rl/m7f_nonport_view.py` (non-PORT source check: text view + MSVC `cl /EP`),
`rl/m7f_manifest.py`, `rl/m7f_replay.py`, `rl/m7f_analysis.py` (Phases F-G), `rl/m7f_tests.py` (permanent
fixtures), `rl/m7f_regressions.py` (M7f regression chain).

Build: `cmake --build build-us --config Release`, exit 0, no warning in any edited file. Executable sha256
`57d61fe0b2a60265...` (pre, the M7a-M7e build) -> `10e8e15d4abe6060...` (post, final). An intermediate build
`af5a8dd945a8841b...` preceded three fixes from an adversarial review of the diff: (1) the item-link cross-check is
skipped once the scene task has ejected its objects (`link_checked`), because after a fall the loop-breaking update's
reply otherwise reported a false `LINK_MISMATCH` (confirmed by `rl/m7f_tests.py game_fall_teardown`: 95 neutral steps
after a historical fall through status 5 / 6 / 7 to the scene unload, one reply with the check skipped, no anomaly);
(2) the M4 `response_ready_ns` stamp is taken after the `targets` object is built; (3) `sHasLatestTargets` is cleared
when a capture carries no targets. Evidence produced with the intermediate build is kept apart
(`runs/m7f/_equiv/interim_af5a8dd9`, `runs/m7f/replay_interim_af5a8dd9`) and every result below comes from the final
build. `BattleShip.o2r` unchanged
(`fe2b307e...`); `f3d.o2r` is re-zipped by every build (`3fc8b733...` -> `f4ff39da...`); the tracked generated
`include/reloc_data.us.h` is unchanged (no new `ll*` token in the decomp edits); the user configuration is untouched.
The pre-change executable is preserved runnable in `runs/m7f/_exe/pre_m7f` (exe, pdb, both archives, controller DB,
config/imgui byte copies, `.tcc`, `assets`; 116 files, manifest `runs/m7f/_exe/pre_m7f_manifest.json`).

## 7. Validation (Phase D)

`python rl/m7f_validate.py --equiv runs/m7f/_equiv` -> 32/32 checks PASS (final executable `10e8e15d...`)
(`docs/rl_target_identity_m7f_validation.json`). The inputs are five capture sets of the same actions, taken with
`rl/m7f_trace.py`: `pre_build` (pre-change executable, before any source edit), `pre_copy` (the preserved copy),
`post_off`, `post_on`, `post_on_r2` (post-change executable; diagnostic off / on / on again). Each set is the TAS
through stepping in three host modes (normal, no-render, no-render + Raphnet bypass), eight pinned historical
artifacts in the historical host mode (the three M7e best six-target episodes, the M7d s0 v1 deterministic fall, a
six-target fall with a same-tick double break, a horizon episode with a same-tick double break, the M7e s2 final
deterministic episode, the random-baseline six-target episode) and the native 468-row replay.

| # | requirement | evidence | result |
| --- | --- | --- | --- |
| 1 | ten active targets initially | every initial `targets`: `remaining_mask 0x3FF`, `spawn_count 10`, `break_count 0`, link walk 10 live | PASS |
| 2 | IDs unique, 0-9 | records in ID order 0-9 (strict parser) | PASS |
| 3 | mapping identical across fresh processes | 24 diagnostic processes (TAS x 3 modes and 8 fixtures, twice, plus 2 parked): one static table | PASS |
| 4 | active count == `targets_remaining` | 61,795 replies checked, every one | PASS |
| 5 | one break clears exactly its bit | per-step cleared bits == drop of `targets_remaining`; native `break_input_tick == consumed_tick + 1 == input_tick` | PASS |
| 6 | no ID reused | `break_order` unique 1..n, `anomaly_flags 0`, `link_checked 1` and `link_unmatched 0` on every reply during play | PASS |
| 7 | broken never active again | no bit ever re-set; broken records never change after the break | PASS |
| 8 | clear: zero active, ten unique IDs | TAS final `remaining_mask 0`, ten distinct IDs | PASS |
| 9 | TAS gives ten events | order `9, 4, 5, 2, 7, 3, 0, 6, 8, 1` at consumed ticks `51, 87, 142, 163, 275, 316, 358, 368, 432, 446` (the frozen ticks) | PASS |
| 10 | tick semantics | every event: `input_tick = consumed_tick + 1 = native break_input_tick`; `break_time_passed =` the breaking reply's `time_passed` (checked on every event) `= consumed_tick` (checked on the TAS) | PASS |
| 11 | cold == standby | a process parked 12 s at tick 0 before its first step (what a standby is) == an immediate start, every reply incl. `targets` and `host_frame` (TAS + one fixture); M7c `cold_vs_standby_replay` in the regression chain | PASS |
| 12 | visible == no-render == Raphnet bypass | TAS `targets` sequences identical in all three host modes; the native replay's `target_identity` == stepping | PASS |
| 13 | 15-value policy observation identical | sha256 of the float32 `btt_policy_obs_v1` vectors of every reply, pre vs post: identical (TAS + 8 fixtures) | PASS |
| 14 | rewards identical | v1 / v2 returns recomputed pre vs post identical; TAS 19.553 under both; fixture returns == historical `raw_return` | PASS |
| 15 | canonical actions byte-identical | action digests of all fixtures == recorded `native_action_digest`; historical files untouched | PASS |
| 16 | non-PORT unchanged | non-PORT text view and MSVC `cl /EP` translation units of both decomp files identical to `91d7b6b7` | PASS |
| 17 | repeatable | `post_on` vs `post_on_r2`, every reply including `targets`: identical | PASS |

Pre/post equivalence (the gate of this milestone): `pre_build` vs `pre_copy` identical; `pre_build` vs `post_off`
identical under a **strict** comparison (every key of every reply including the status key set, all 17 observation
fields including `host_frame`, the result JSON, exit codes, the native replay lines); `pre_build` vs `post_on`
identical except the new `targets` reply key, the `target_diag` status key and the `target_identity` result key.
Native replay, both executables, diagnostic off and on: `COMPLETE input_tick=447 time_passed=446`,
`input exhausted frames=468 actual_checksum=0x93E9EFB4`, result 10 / 446 / 447, `host_frames 511`. TAS through
stepping: 447 actions, last consumed tick 446, input tick 447, time passed 446, step count 447, 21 rows unsent,
`EpisodeEnded`, exit 0.

Native ID -> position table (measured; `docs/rl_target_identity_m7f_mapping.json`):

| ID | spawn (x, y) | moves | region | TAS order / consumed tick |
| --- | --- | --- | --- | --- |
| 0 | (-1350, -2250) | no | central | 7 / 358 |
| 1 | (-3450, -2550) | no | left_of_wall | 10 / 446 |
| 2 | (2700, 2100) | yes (y 2100-3900) | upper_right_moving | 4 / 163 (broken at y 3000) |
| 3 | (4950, -1800) | no | right | 6 / 316 |
| 4 | (0, -900) | no | central | 2 / 87 |
| 5 | (0, 300) | no | central | 3 / 142 |
| 6 | (-3300, 3300) | no | left_of_wall | 8 / 368 |
| 7 | (0, 1650) | no | central | 5 / 275 |
| 8 | (-3300, 600) | no | left_of_wall | 9 / 432 |
| 9 | (1650, -2250) | no | central | 1 / 51 |

(The ID 4 / 5 spawn x values are 5e-06 / 2e-05 in the stage data.) The moving target's measured break height
(y 3000.0 at consumed tick 163) matches the smoothstep 2100 <-> 3900, 150-frames-per-leg animation with 61 frames
elapsed at tick 0 that the decomp predicts.

### 7.1 Regression chain and integrity

`python rl/m7f_regressions.py --keep-going` (`runs/m7f/_regressions/20260923T132814Z/results.json`): **25 / 25
PASS** — 23 suites plus `git diff --check` clean in the parent and the decomp submodule; zero BattleShip processes and
zero listeners left after every suite; user configuration sha256 `1b29d91b...` unchanged throughout (its mtime changes
from `m7_smoke` on because inherited suites deliberately run a process with cwd `build-us/Release`, which rewrites
identical bytes). Passed: M7f unit + game fixtures (incl. the fall-teardown case), MSVC `cl /EP` non-PORT check, M7e
unit (10 / 10), M7d unit, M7b configuration, the authoritative native 468-row replay (checksum `0x93E9EFB4`,
10 / 446 / 447), M1e with the diagnostic off and on, M1d transport (errors, single, delayed, disconnect, baseline), M7e
and M7d existing-suite cases, M7c standby (4 unit + 11 game incl. `cold_vs_standby_replay`), M7b replay-level smoke,
M7a smoke (8 unit + isolation boot/replay, fall regression, timeout/startup/job-object cleanup), M6 equivalence and
Raphnet bypass, M5 (with and without the M6 flags), M4, M3, M2 restart and lifecycle.

Repaired inherited test: the first chain run (`runs/m7f/_regressions/20260923T071004Z`, 24 / 25) failed
`m7e_tests unit_instrumentation`, whose census check asserted that the **live** `runs/m7e` evaluation census was
incomplete — true before M7e evaluated, false ever since (3,055 / 3,055). `rl/m7e_tests.py` now runs `census()` on an
isolated synthetic evaluation tree in a fresh temporary directory (evaluation root and state file redirected, every
file-write primitive disabled during each call, the 38 historical M7e state / summary files fingerprinted before and
after): an empty tree must be rejected with all 33 planned sets and the random baseline reported missing (the original
assertion, kept), a tree with exactly the planned episodes must be accepted (3,055 episodes, 67 sessions, 735 / 2,220
/ 100 by mode), and a tree with three planted gaps must report exactly those three. Mutation checks confirmed the
test fails if `census()` writes or always reports complete. No run data changed; no other test changed. Cases that
train a PPO model against BattleShip were
excluded (listed in `EXCLUDED_TRAINING`); two unit cases train a throwaway PPO on an in-memory dummy environment for
16-128 steps (m5 `policy_observation`, m7_smoke `unit_metadata`), with no game and nothing persisted.

Historical integrity (`runs/m7f/historical_integrity.json`): all 76,471 files present under `runs/` at the start of
M7f (junctions not followed) are byte-identical with unchanged mtimes after it, including all 36,246 under
`runs/m7d` and all 29,751 under `runs/m7e`, re-checked after the final chain; additions are `runs/m7f` and the small
default-root directories the inherited M7e `existing_suites` case creates on each chain run (`runs/_m7b_tests_<utc>`,
`runs/_m7c_tests_<utc>`, 16 files per run).

## 8. Ownership and commit order (not performed; the user commits)

The change spans the parent repository and the `decomp` submodule; `libultraship` and `torch` are untouched. When it
is committed, the order must be:

1. In `decomp` (branch `rl-main`, remote `origin` = the user's fork `nicolasfrechette91/ssb-decomp-re`; never
   `port-upstream` / JRickey, never `canonical`): commit `src/sc/sc1pmode/sc1pbonusstage.c` and
   `src/it/itground/ittarget.c`, then push `rl-main` to `origin`.
2. In the parent: stage and commit the updated `decomp` gitlink **alone**.
3. In the parent, separately: `port/rl/rl.h`, `rl_boot.cpp`, `rl_observation.cpp`, `rl_result.cpp`, `rl_step.cpp`,
   `rl_transport.cpp`, the new `rl_targets.h` / `rl_targets.cpp`, the new `rl/m7f_*.py` files and the M7f docs.

The parent must not be committed with the new `port/rl` code before the decomp commit exists on the fork: the port
calls `rlGameFillTargets`, which only the edited decomp defines (a fresh clone would not link). `.gitmodules` still
names `branch = port-patches` for `decomp`; that stale field is unrelated to M7f and was not changed.
