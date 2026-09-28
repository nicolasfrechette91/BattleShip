# RL observation v4 contract proposal: `btt_policy_obs_v4_input` (specification for review, revision 3)

Status (2026-09-28, revision 3 after the user's final decisions): **design only, nothing implemented, nothing
run.** No game launch, no training, no campaign, no production edit, no commit, branch, push, PR or video. The
selected baseline stays `btt_policy_obs_v3_entities` + `btt_reward_v2` + Track 1 `btt_s9_b8_v1`; the schema
defaults stay v1 / v1 (`rl/experiment_config.py`).

Repository state at writing: parent HEAD `ee96fe2` (clean apart from the untracked audit and this file);
submodules `decomp 3834e227` (rl-main, clean), `libultraship 805f1950`, `torch 3aa9c97`. Evidence:
[`rl_mechanics_observation_audit_2026-09-28.md`](rl_mechanics_observation_audit_2026-09-28.md) (§1 pipeline, §2
capability table, §3 hypotheses, §4 gaps, §7 measured answers) and [`rl_handoff_2026-09-28.md`](rl_handoff_2026-09-28.md).

Constraints preserved by construction: native gameplay is authoritative (every new value is read from FTStruct /
GObj / DObj after the game's own update; none is computed from Python rules); no native RNG seed inspection,
logging, validation, control, comparison or hashes; non-PORT decomp untouched (every native line lives inside the
existing `#ifdef PORT` fill block of `sc1pbonusstage.c`, proven by `rl/m7f_nonport_view.py`); the RLObservation,
spatial, entity, target, reward, replay, reset and tick contracts are unchanged and v4 is additive on top of them;
human recordings and the TAS remain validation-only.

Revision history: rev 2 resolved D1-D8; **rev 3** adds the `air_lock` class for `StopCeil` (23 classes), adds
native `anim_speed` to the policy block (17 appended agent fields, `agent (45,)`), keeps `hold_L`, records the
tick-0 Z counter without a threshold, repairs the field-table cells (no `|` inside cells), defines the tap
encoding for native value 0 with source evidence, and recalculates every shape: flat **626**.

---

## 1. What v4 adds and why (decisions the policy cannot currently make)

The audit found that action selection under Track 1 (one controller word per native tick, no memory in the
policy, no previous action in the observation) is blind to native facts that decide whether the next word does
anything:

| blind spot | native fact | decision it serves |
| --- | --- | --- |
| press vs hold | `input.pl.button_hold` after the R → A+Z fold (`ftmain.c:1376-1440`) | "will choosing A / B / C / Z / R next tick be an edge, or is it already held (no attack, no jump, shield continues)?" |
| stick tap vs stale hold | `tap_stick_x/y` (`ftmain.c:1441-1500`), forced to 254 by dash, jump, fast fall, pass | "is a dash / smash / double jump / fast fall / drop-through still reachable with this stick direction, or must the stick leave the band first?" |
| Z-cancel window | `tics_since_last_z` (`ftmain.c:1510-1517`), reset to 65536 when an aerial starts | "if I land now, is the landing lag-free?" (11-tick inclusive window, audit §3) |
| animation progress, playback speed and the landing-lag flag | `gobj->anim_frame` (frames; frozen in hitlag, unlike `status_total_tics`), `DObj::anim_speed` (0.5 heavy landing, 0.28 Mario up-B landing, 0.5 / 0.2 null landings of nair / dair), `motion_vars.flags.flag1` in aerial statuses | "how far into the move am I, roughly how many ticks remain, and does landing from this aerial lag at all?" |
| helpless, lagged-landing and ceiling-lock states | `nFTCommonStatusFallSpecial`, `LandingAir*`, `LandingAirNull`, `LandingFallSpecial`, `StopCeil` | "can a new jump, attack or special start before this ends, which stick inputs still act, and what follows?" (currently merged into `airborne` / `landing`) |

Plus one contact bit already on the wire (`MAP_FLAG_FLOOREDGE`, the edge-teeter snap) that v3 drops.

Not in scope: anything that changes the game, the action space, the reward, or that duplicates a game rule in
Python. No action mask (a word that cannot start a move still steers, releases a hold or arms a future edge).

---

## 2. Native exposure: diagnostic `btt_input_state_v1` (`SSB64_RL_INPUT=1`)

A new **read-only, opt-in, additive, separate** object in the M7f / M7g / M7n pattern (D1: the `btt_entity_v1`
object, its parser and every pinned `entity_all` reference set stay valid byte-for-byte).

### 2.1 Fields (`RLInputDiag`, `port/rl/rl.h`, filled by `rlGameFillInput()` inside the existing PORT block of `decomp/src/sc/sc1pmode/sc1pbonusstage.c`)

Capture point: the same `GamePostUpdateEvent` callback and the same lock as the observation / spatial / entity
snapshots (`port/rl/rl_observation.cpp`), i.e. **after** the tick's `ftMainProcUpdateInterrupt` (input latch, tap
counters, Z timer, script advance, `proc_update`, `proc_interrupt`) and `ftMainProcPhysicsMap` (physics, landing,
status changes made in `proc_map`). The reply to `step(T)` carries the values **after action T was applied**,
stamped `input_tick = T + 1`, exactly like the entity object. The diagnostic carries **full native values** (no
capping, no scaling); the policy block (§3) applies the bounds.

| field | type | native source | meaning at capture (after action T) | at the tick-0 observe (expected; V3 records) |
| --- | --- | --- | --- | --- |
| `input_schema`, `input_tick`, `scene_active`, `live`, `valid` | u32 | same guards as `rlGameFillEntity` (`sc1pbonusstage.c:1026-1080`) | `valid = 1` only when the fighter and its `FTStruct` exist | `valid 1` |
| `stick_x`, `stick_y` | s8 | `fp->input.pl.stick_range` | action T's stick after the ±80 clamp (the half-range backup flag is off here) | 0, 0 |
| `button_hold` | u16 | `fp->input.pl.button_hold` | action T's button word **after the R fold** (`R` sets `A` and `Z`; the `R` bit itself stays set) | 0 |
| `button_tap`, `button_release` | u16 | `fp->input.pl.button_tap`, `.button_release` | the edges tick T produced (OR-accumulated while `hitlag_tics != 0`) | 0, 0 |
| `tap_stick_x`, `tap_stick_y`, `hold_stick_x`, `hold_stick_y` | u8 | `fp->tap_stick_*`, `fp->hold_stick_*` | tap counters after tick T: 1 on band entry, `++` inside (capped at 254), 254 outside the band; `tap_*` also forced to 254 by dash / jump / fast fall / pass; initialised to 254 at fighter creation (`ftmanager.c:1005`) | 254 ×4 |
| `tics_since_last_z` | s32 | `fp->tics_since_last_z` | ticks since the last Z or R tap, saturating at 65536; 65536 after an aerial start, damage, ledge drop | ticks since spawn (`ftmanager.c:519` sets 0); **recorded, not required** (D-Q4) |
| `anim_frame` | f32 | `fighter_gobj->anim_frame` | elapsed animation frames of the current motion (advances by `anim_speed` per non-hitlag tick; ≤ 0 sentinel once the last joint ended, `ftanim.c:180-205`) | the Wait animation's current frame, **not 0**: control is locked from fighter creation (`ftmanager.c:1080-1085`, `ftParamLockPlayerControl`) until the GO signal (`ifcommon.c:2211`), and while locked `status_total_tics` does not count but the animation keeps playing; recorded value 11 (implementation §2, V3) |
| `anim_speed` | f32 | `DObjGetStruct(fighter_gobj)->anim_speed` | playback rate set by `ftMainSetStatus`'s `anim_speed` argument: literal 1.0 (334 call sites), 0.0 (13, captured / frozen states), 2.0 (1, `WallDamage`), and through variables 0.5 (`FTCOMMON_LANDING_HEAVY_ANIM_SPEED`), 0.28 (`FTMARIO_SUPERJUMP_LANDING_LAG`), `flag1 %` for `LandingAirNull` (nair 0.5, dair 0.2) | 1.0 (`ftCommonWaitSetStatus` passes 1.0) |
| `motion_flag1` | u32 | `fp->motion_vars.flags.flag1` | the motion script's flag 1, **whose meaning depends on the status** (aerials: landing lag armed; Dash: fresh-dash marker; Mario up-B: rise finished; tornado: friction phase; down tilt: repeat allowed) | 0 |

Plumbing copies M7n one-to-one: `rl_boot.cpp` reads `SSB64_RL_INPUT` and requires effective stepping (else a log
line and the flag is ignored); `rl_step.cpp` latches Latest / Result / Last copies under `sMutex` exactly like
`sLatestEntity`; `rl_transport.cpp` adds `"input_diag": true` to `status` and an `"input"` object to `observe` and
`step` replies, rendered by a new `port/rl/rl_input.cpp`. With the flag unset no code path touches the new struct
and every reply is byte-identical to today's (V1).

Intentionally **not** in the native block: `stick_prev` (the tap counters carry what the game does with it),
`kneebend.jump_force / is_shorthop`, `landing.is_allow_interrupt`, `cliffcatch_wait`, `is_expend_tornado`,
`motion_flag0/2/3` (§5).

---

## 3. Python contract `btt_policy_obs_v4_input`

Same Dict layout, key order, SB3 concatenation, masking, stale rule (native `live = 0` or fighter invalid
repeats the last observation with `info["v4_stale"]`) and the one extra non-consuming `observe` per reset as v3
(`rl/m7n_obs.py`). The `projectiles`, `segment_geometry`, `segment_kind` and `targets` blocks are **unchanged**.
New module `rl/m7q_obs.py` (its own `OBS_CONTRACT`, `SHAPES`, `contract_description()` and digest); v3's file,
contract id and digest (`4ddc2933…`) stay untouched.

### 3.1 Shape calculation (recomputed from the complete layout)

| key | v3 shape | v3 size | v4 shape | v4 size | change |
| --- | --- | --- | --- | --- | --- |
| `action_class` | (20,) | 20 | **(23,)** | **23** | +2 (`helpless`, `landing_lag`) rev 2, +1 (`air_lock`) rev 3, `landing` renamed |
| `agent` | (28,) | 28 | **(45,)** | **45** | +16 rev 2, +1 (`anim_speed`) rev 3 |
| `projectiles` | (4, 7) | 28 | (4, 7) | 28 | unchanged |
| `segment_geometry` | (32, 8) | 256 | (32, 8) | 256 | unchanged |
| `segment_kind` | (32, 7) | 224 | (32, 7) | 224 | unchanged |
| `targets` | (10, 5) | 50 | (10, 5) | 50 | unchanged |
| **flat** | | **606** (= `FLAT_SIZE`, `rl/m7n_obs.py:90`) | | **626** | +20 |

Check: 23 + 45 + 28 + 256 + 224 + 50 = 626; rev 2 was 22 + 44 + 28 + 256 + 224 + 50 = 624; one class bit and
one agent field more give 626, as expected.

### 3.2 `action_class`: 20 → 23 (table `btt_action_class_table_v2`, §4)

### 3.3 `agent`: 28 → 45 float32

Indices 0-27 are v3's fields in v3's order and scaling (unchanged, including the raw status scalar
`status_id / 256` at index 17 and `status_tics` at 18), so the v3 slice of a v4 observation is bit-identical to
v3's. The 17 appended fields (`abs(v)` denotes the absolute value; no cell contains a vertical bar):

| # | field | exact native source | encoding | range | tick-0 value (expected; V3 records) | purpose (decision served) |
| --- | --- | --- | --- | --- | --- | --- |
| 28 | `stick_x` | `input.stick_x` = `fp->input.pl.stick_range.x` | `x / 80` | −1..1 (Track 1: −1, 0, +1) | 0 | the horizontal stick the game holds now: whether the next word's direction is a change (fresh tap) or a continuation; which side a tilt / smash / aerial / neutral-B turnaround would take |
| 29 | `stick_y` | `input.stick_y` = `fp->input.pl.stick_range.y` | `y / 80` | −1..1 | 0 | same, vertical: jump / double-jump tap, fast-fall tap, crouch, drop-through, up-B / down-B selection |
| 30 | `hold_A` | `input.button_hold` bit `0x8000` | bit → 0 / 1 | {0, 1} | 0 | A pressed next tick is an edge only if 0 (attack, aerial, jab follow-up, grab with Z) |
| 31 | `hold_B` | `input.button_hold` bit `0x4000` | bit | {0, 1} | 0 | B edge (specials, tornado B taps) |
| 32 | `hold_Z` | `input.button_hold` bit `0x2000` | bit | {0, 1} | 0 | Z edge (Z-cancel timer reset, roll from dash, ledge roll) and Z hold (shield continues, grab needs Z held plus an A edge) |
| 33 | `hold_L` | `input.button_hold` bit `0x0020` | bit | {0, 1} | 0 | L edge (taunt lock; the only L effect); kept for symmetry with the eight-button contract |
| 34 | `hold_R` | `input.button_hold` bit `0x0010` | bit | {0, 1} | 0 | R edge; with 30 and 32 shows the fold: an R action reads `hold_A = hold_Z = hold_R = 1`, an A action reads `hold_A = 1` only |
| 35 | `hold_Cup` | `input.button_hold` bit `0x0008` | bit | {0, 1} | 0 | C-up edge (ground jump / double jump need a C edge; a C-less tick re-arms it) |
| 36 | `hold_Cleft` | `input.button_hold` bit `0x0002` | bit | {0, 1} | 0 | C-left edge (same) |
| 37 | `tap_x` | `input.tap_stick_x` = `fp->tap_stick_x` | 1 → 1.0; 2 → 0.75; 3 → 0.5; 4..253 → 0.25; 254 → 0; **0 → 0 and counted as an anomaly** (§3.4) | {0, 0.25, 0.5, 0.75, 1.0} | 0 | every native cut is a threshold on this value: dash and forward smash need a counter below 3 (value ≥ 0.75), roll below 4 (≥ 0.5); the forced or out-of-band 254 (0) is distinct from a naturally stale hold (0.25); together with `stick_x`: value 0 with `abs(stick_x) >= 20` means the game forced the counter stale |
| 38 | `tap_y` | `input.tap_stick_y` = `fp->tap_stick_y` | same 5-level encoding | {0, 0.25, 0.5, 0.75, 1.0} | 0 | jump and double jump need a counter at most 3 (≥ 0.5); fast fall, drop-through, up and down smash below 4 (≥ 0.5); 0 after the game forced it (jump, fast fall, pass) even though the stick is still held up or down |
| 39 | `z_age` | `input.tics_since_last_z` = `fp->tics_since_last_z` | `min(t, 10) / 10` | 0, 0.1, …, 1.0 (11 distinct ages) | recorded 1.0 (counter 61 = ticks since spawn; no requirement) | the age of the last Z / R press at the end of the observed tick. **Decision reading (source rule, implementation §2 V6):** a landing on the *next* tick first advances the counter (0 on a Z / R edge, else +1) and then lags iff the aerial is armed and the counter exceeds 10; so `z_age < 1.0` (counter ≤ 9) means the next landing is lag-free even without Z, and `z_age = 1.0` (counter ≥ 10) means it lags unless Z / R is pressed on that tick |
| 40 | `z_out` | same counter | 1 iff `t > 10` | {0, 1} | recorded 1 | explicit "outside the window at the end of this tick": separates counter 10 from 11 and more (and from the 65536 reset after an aerial start). It is **not** the next-tick landing boundary (that is `z_age = 1.0`, row 39): it is exact for a landing that happened on the observed tick itself, i.e. it explains the class the agent has just entered |
| 41 | `anim_frame` | `input.anim_frame` = `fighter_gobj->anim_frame` | `clip(f, 0, 240) / 60` | 0..4 | the Wait animation's frame at the GO signal (recorded 11 → 0.183; the animation plays during the control lock while `status_tics` stays 0, §2.1) | progress in animation frames: landing interrupt gate at 4, dash windows 3 / 5 / 20, jump-squat 3, aerial `flag1` windows; unlike `status_tics` (18) it does not advance in hitlag and it follows `anim_speed` |
| 42 | `anim_speed` | `input.anim_speed` = `DObjGetStruct(fighter_gobj)->anim_speed` | `clip(s, 0, 2) / 2` | 0..1 (observed points 0, 0.1, 0.14, 0.25, 0.5, 1.0 for speeds 0, 0.2, 0.28, 0.5, 1.0, 2.0) | 0.5 (speed 1.0 in Wait) | information to **estimate** the remaining time of the current animation: with `anim_frame`, remaining frames ÷ speed is the tick count only while the status persists without hitlag and with a non-zero speed (it is undefined at speed 0, pauses during hitlag and is voided by a status change); it separates nair's null landing (0.5, 14 ticks uninterrupted) from dair's (0.2, 35) inside the same `landing_lag` class, and the heavy landing (0.5, interruptible after 8 ticks) from the light one (1.0, after 4) inside `landing_free` |
| 43 | `aerial_lag_armed` | `input.motion_flag1 != 0` **and** `nFTCommonStatusAttackAirStart <= status_id <= nFTCommonStatusAttackAirEnd` | bit | {0, 1} | 0 | "landing now enters `landing_lag` unless `z_out = 0`"; outside aerial statuses the bit is 0 by definition, so `flag1`'s other meanings never leak in |
| 44 | `contact_edge` | spatial `fighter.mask_curr` bit `0x8000` (`MAP_FLAG_FLOOREDGE`) | bit | {0, 1} | 0 | edge-teeter snap (Ottotto): walking off needs a hard push toward the edge, a jump or a drop |

The folded button word is represented **only as the seven bits 30-36**, never as a numeric scalar; the bits
C-down, C-right, Start and D-pad are asserted zero by the builder (a set bit is an anomaly, counted like an
`unmapped` status).

Authoritative vs derived: 28-43 are native state read after the game applied the action; 44 is a native mask
bit already transported. **No field of v4 is computed from the agent's own action history.**

### 3.4 Tap counters: native value 0

The u8 counters cannot read 0 at any observation boundary: they are initialised to 254 at fighter creation
(`ftmanager.c:1005`, also `ftparam.c:237`), and every writer sets them to 1 (band entry), increments a value that
is already ≥ 1 with an explicit cap at 254 (`ftmain.c:1441-1500`: the `++` is followed by `if (> MAX) = MAX`, so
no wrap to 0), or forces 254 (`ftcommondash.c:120`, `ftcommonjump.c:98`, `ftcommonjumpaerial.c:172, 226`,
`ftcommonpass.c:31`, `ftphysics.c:254`, `ftcommondamage.c:257, 621`, `ftcommondokan.c:81`,
`ftcommonhammerfall.c:84`, `ftcommoncapturekirby.c:137-166`, `ftdonkeythrowffall.c:71`). The per-tick update runs
whenever `is_control_disable` is false (training-menu only), including during hitlag. The encoding still defines
0 → 0.0 (the "no fresh tap" level) and the builder counts it as an anomaly like an `unmapped` status, so a value
that the source says cannot occur is neither silently trusted nor able to break the space.

### 3.5 Previous action: native `button_hold` + stick, not a Python one-hot (unchanged)

| information | previous Track 1 index (Python, 9 + 8 one-hot) | native `stick` + `button_hold` + tap counters |
| --- | --- | --- |
| previous stick state | exact for the agent's own ticks only | exact, and also correct on standby-promoted, replayed or externally driven ticks |
| button edges next tick | recoverable only by re-implementing the fold and edge rule | the word the game will diff against is exposed as-is |
| R's A+Z conversion | invisible (the one-hot says "R") | visible (`A`, `Z`, `R` bits), which is what `ftCommonCatch…`, `…GuardOn…`, `…AttackAir…` read |
| tap-counter resets forced by the game (jump, dash, fast fall, pass) | unknowable without duplicating status logic | included |
| cost | 17 floats, no native change | 9 floats (2 stick + 7 bits) + 2 tap floats, needs the native block anyway |

Native only. The Track 1 index stays in `info["track1_action"]` and the episode records; it is not a feature.

### 3.6 Overlap review of the 17 appended fields

| pair | overlap | kept because |
| --- | --- | --- |
| `stick_x/y` (28-29) vs `tap_x/y` (37-38) | none: direction vs recency; together they separate "outside the band" (tap 0, `abs(stick) < 20`) from "forced stale inside the band" (tap 0, `abs(stick) >= 20`) | both needed |
| `z_age` (39) vs `z_out` (40) | `z_out = 1` implies `z_age = 1.0`; `z_age = 1.0` alone is ambiguous between counter 10 and 11 or more. For a landing on the next tick both mean "lags unless Z / R is pressed now" (the counter advances before the check, row 39); `z_out` distinguishes them only for the landing that already happened on the observed tick | deliberate: an explicit out-of-window bit was requested; kept with its meaning stated precisely (implementation §2 V6) |
| `anim_frame` (41) vs v3 `status_tics` (18) | equal in the common case (speed 1, no hitlag, status entered at frame 0) | they diverge exactly where it matters (hitlag, audit §7.3; slowed landings, §7.1; statuses entered mid-animation, e.g. the fireball air / ground continuation) |
| `anim_speed` (42) vs `anim_frame` (41) and the class | none: frames and class give progress, speed lets the policy estimate remaining ticks from remaining frames (exact only while the status persists without hitlag at a non-zero speed) | the same class and frame count last 14 or 35 ticks for nair vs dair (user decision, rev 3) |
| `aerial_lag_armed` (43) vs class `attack_air` | armed implies `attack_air`, not conversely (start-up and tail frames are unarmed) | carries the window, the class does not |
| `hold_A` + `hold_Z` + `hold_R` | an R action sets all three; an A action only `hold_A`; a Z action only `hold_Z` | the fold is a game fact the policy must see; collapsing it would hide that R also armed the Z timer and the grab |
| `contact_edge` (44) vs v3 `contact_floor` (11) | edge implies grounded, not conversely | the teeter rule differs from a plain floor stand |
| `hold_L` (33) | L has one effect (taunt) | kept by user decision |

No field is redundant without a stated reason; none is removed.

### 3.7 Per-status meaning is never implied

`anim_frame` and `anim_speed` are exposed raw (scaled); their interpretation depends on the status, which the
class one-hot and the raw status scalar (index 17) supply. `motion_flag1` enters only through the aerial-gated
bit 43; its other meanings stay in the diagnostic JSON. `z_age` / `z_out` are status-independent counters that
matter with bit 43; the policy learns the conjunction. Helpless, lagged-landing and ceiling-lock information is
carried by the class table (§4), not by flags.

---

## 4. Status-class table v2: `btt_action_class_table_v2` (new file `rl/data/m7n_action_classes_v2.json`)

Derived by the same generator (`rl/m7n_status_table.py derive` with `TABLE_ID = "btt_action_class_table_v2"`
and `classify_v2`) for all 12 characters from the same enum headers; v1's file, id and digest (`97db1152…`) are
not modified. `ActionClassifier(table, character)` is reused as is.

Exact rule changes relative to `classify()` (`rl/m7n_status_table.py:60-100`); every other line is identical:

| enumerator (short name) | v1 class | v2 class | reason |
| --- | --- | --- | --- |
| `FallSpecial` | `airborne` | **`helpless`** (new; reserved for the post-up-B / post-special helpless fall) | no new jump, attack or special can start until landing (the only interrupt is the double-jump check, which always fails because `jumps_used = jumps_max`); the stick still steers (drift at 0.6 × `air_speed_max_x`), a fresh down tap still fast-falls, and holding down still drops through a platform (`ftcommonfallspecial.c:13-40`); ledge / landing rules differ from Fall (audit §2.4) |
| `StopCeil` | `airborne` | **`air_lock`** (new) | temporary move lock: no jump, attack or special can start and the stick does not change the velocity while it lasts (`proc_interrupt` and `proc_physics` NULL; `vel_air.y = vel_air.z = 0`, `ftcommonstopceil.c`); the controller word still updates the native edge and tap counters for the tick after; ends at the animation end into `Fall` with the double jump kept (`jumps_used` untouched); not helpless |
| `LandingLight`, `LandingHeavy` | `landing` | **`landing_free`** (renamed) | interruptible from animation frame 4 (`ftcommonlanding.c`) |
| `LandingAirN/F/B/Hi/Lw`, `LandingAirNull` | `landing` | **`landing_lag`** (new) | `proc_interrupt = NULL`; Mario 14 / 30 / 15 / 40 / 35 ticks (audit §7.1) |
| `LandingFallSpecial` | `landing` | **`landing_lag`**, annotated `character_dependent: true` | validated for Mario (below) |

`CLASSES_V2` (23, insertion order): `idle_ground, dash_run, jump_squat, airborne, helpless, air_lock,
landing_free, landing_lag, crouch_pass, shield, roll, damage, cliff, attack_ground, attack_air, special_n,
special_hi, special_lw, item, appear_entry, dead, other, unmapped`.

Class mapping of the common statuses that changed or that neighbour the changes (v2):

| status ids (`ftcommonstatus.h` numbering) | v2 class |
| --- | --- |
| 22 JumpF, 23 JumpB, 24 JumpAerialF, 25 JumpAerialB, 26 Fall, 27 FallAerial | `airborne` |
| 58 FallSpecial | `helpless` |
| 66 StopCeil | `air_lock` |
| 31 LandingLight, 32 LandingHeavy | `landing_free` |
| 214-218 LandingAirN/F/B/Hi/Lw, 219 LandingAirNull, 59 LandingFallSpecial | `landing_lag` (59: `character_dependent`) |
| 209-213 AttackAirN/F/B/Hi/Lw | `attack_air` (unchanged) |
| everything else | as in v1 |

**`LandingFallSpecial`, validated for Mario.** Mario's up-B enters the helpless fall with
`is_allow_interrupt = FALSE` (`ftmariospecialhi.c:9-14`, `ftCommonFallSpecialSetStatus(…, FALSE)`), and the
landing status keeps that flag (`ftcommonfallspecial.c:60-66`), so `ftCommonLandingProcInterrupt` never runs its
chain; the captures show 79 of 82 runs lasting exactly 25 ticks with no interrupt (the 3 one-tick runs are edge
fall-offs). The same common status id is shared by every character and the flag is a per-character argument, so
the v2 table records `landing_lag` for the common id with `character_dependent: true`, and the M10 onboarding
gate must read each character's `ftCommonFallSpecialSetStatus` call before that character uses the table. No
claim is made for any other character.

**`StopCeil` (`air_lock`).** Entered when rising into a hard ceiling with `vel_y >= 30` (`mpcommon.c:502-515,
706-726`). While it lasts no jump, attack or special can start and the stick does not change the velocity
(`proc_interrupt` and `proc_physics` NULL), but the controller word is not inert: the native edge and tap
counters keep updating, so the word chosen during the lock decides which presses count as fresh on the first
tick of the following `Fall`; the animation still advances (`anim_frame`, 41) and the class bit makes the lock
linearly readable; `contact_ceil` (v3 index 12) is 1 on the entry tick. It is grouped neither with `helpless`
(which keeps steering and fast fall but loses the double jump and lands with a fixed uninterruptible lag) nor
with `airborne` (where every air interrupt is live).

---

## 5. Intentional omissions

| omitted | why | when it returns |
| --- | --- | --- |
| ledge fields (`LCLIFF` / `RCLIFF` bits, `CLIFF` line flag, `cliffcatch_wait`, `cliffwait.is_allow_interrupt`) | Mario BTT has no ledge-flagged line (audit §7.4); the features would be constant | first versus-stage mode |
| tornado fields (`is_expend_tornado`, the `flag3` rise window, `motion_flag3`) | no recorded evidence the move matters on this stage (audit §7.5); the move stays in the action space via B + down | concrete evidence from records |
| previous Track 1 action one-hot | superseded by native state (§3.5) | never, unless the native block is rejected |
| `button_tap`, `button_release`, `hold_stick_*`, full `tics_since_last_z`, raw `motion_flag1` as policy features | edges of the *past* tick and the hold counters add nothing to the next decision beyond 30-38 and 41-43; full values live in the diagnostic JSON for the oracles (V4-V6) | diagnostic only |
| short-hop / jump-force state, jab follow-up window | derivable from the policy's own recent choices; not on the clear-critical path | on evidence |
| a "can act" flag or any action mask | no single native flag exists; deriving one would re-implement the interrupt chains in Python and would wrongly mark steering / release / arming words as invalid | not planned |
| any change to reward v2 (no Z-cancel reward, no projectile reward) | user decision; the projectile no-hitlag property and the Z timing are route facts the policy can now observe, not objectives | — |

Requires a separate cross-character audit before any non-Mario use: the 11 unvalidated class tables under the
v2 rule; `LandingFallSpecial` interruptibility per character; `jumps_max` and the Kirby / Jigglypuff
hold-to-jump rule (their multi-jumps read `button_hold`, so `hold_C*` matters differently); Yoshi / Ness
double-jump physics; per-character special process tables (what `flag1` means in each special); `is_have_*`
flags; the per-move `flag1` windows and landing speeds (script and animation data per character).

---

## 6. Bounded validation plan (checks, not an execution)

Legend: **R** = answerable from existing records / source now, no game launch; **N** = needs a native run
(captures with the new executable) when implementation is authorised.

| id | check | method | R / N |
| --- | --- | --- | --- |
| V1 | additive, read-only, off-flag equivalence | `rl/m7n_equivalence.py capture` variants with the new executable: flags unset vs the pinned M7g `post_off` set (strict); `SPATIAL+TARGET_DIAG` vs `post_spatial_diag` (strict); `ENTITY` and `entity_all` vs the M7n sets (strict: the `entity` object byte-identical); `INPUT=1` alone vs `post_off` ignoring only the additive `input` object and status key; repeat capture strict (determinism); the 468-row replay `COMPLETE input_tick=447 time_passed=446` checksum `0x93E9EFB4` under every flag set | N (baselines: R) |
| V2 | non-PORT preservation | `python rl/m7f_nonport_view.py --rev HEAD decomp/src/sc/sc1pmode/sc1pbonusstage.c` (and any other touched decomp file) exit 0; `git diff --check`; MSVC `cl /EP` translation-unit comparison as in M7n §2; `rl.h` stays C-compatible (no decomp type) | R (after the edit, before any run) |
| V3 | tick-0 and post-action timing | the reset `observe` carries `input` with `input_tick 0`, `valid 1`, stick 0 / 0, `button_hold 0`, taps 254, `anim_speed 1.0`; `anim_frame` is the Wait animation's current frame (control is locked until the GO signal while the animation plays, so `status_total_tics` is 0 but `anim_frame` is not: recorded 11); `tics_since_last_z` is **recorded** (no threshold); `step(0)` reply has `input_tick 1` and `button_hold` equal to action 0's folded word; cold and standby-promoted episodes give identical v4 chains; the first step still consumes tick 0 | N |
| V4 | edge / tap oracle | replay the 12 pinned action sequences under `INPUT=1`; predict per tick from the **recorded actions alone**: `button_hold` = folded word, `button_tap` = edges (OR-accumulated across recorded hitlag ticks), `tap_stick_*` by the 20-band rule with forced 254 at the recorded status transitions (KneeBend → Jump, Dash entry, `fastfall` rising edge, Pass entry), `tics_since_last_z` with 65536 at every recorded `AttackAir*` entry; require exact equality on every tick; then check the 5-level `tap_*`, the `z_age` / `z_out` and the `anim_speed` encodings against the full diagnostic values; assert no tap counter of 0 | N (oracle written and unit-tested on synthetic sequences: R) |
| V5 | hitlag | on the 30 recorded hitlag events (audit §7.3) replayed under the flag: `anim_frame` constant and `status_total_tics` advancing during hitlag; `button_hold` follows the action; `tap_stick_*` keep counting; any press recorded inside a hitlag interval appears as a tap on the first post-hitlag tick (if none of the 12 sequences presses inside hitlag, this sub-check is recorded as not exercised, never faked) | N |
| V6 | Z-cancel, landing, `air_lock` classification | for every aerial landing in the captures the source rule must reproduce the class: `landing_lag` iff the last airborne tick's `aerial_lag_armed` and the **landing tick's own** `tics_since_last_z` (the value after that tick's input block, which is what `ftcommonattackair.c:63` reads) exceeds 10; otherwise `landing_free` or `idle_ground` (Wait when `vel_y > -20`). Predicting from the previous tick alone needs the next tick's word: counter + 1, or 0 on a Z / R edge (§3.3 row 39). The records must be labelled with their boundary coverage (previous counter 9 / 10 while armed; a Z edge on the landing tick while armed and outside the window), and the boundary itself is checked synthetically against the source rule (`unit_landing_boundary`); durations equal audit §7.1 (14 / 30 / 15 / 40 / 35 / 25) and, for these uninterrupted runs without hitlag, equal the animation length ÷ `anim_speed` (nair 7 / 0.5, dair 7 / 0.2, up-B 7 / 0.28), the one case in which the estimate is exact; `LandingFallSpecial` runs never interrupted (Mario); class-v2 mapping of every status id seen in every existing capture has no `unmapped`; any recorded `StopCeil` run maps to `air_lock`, shows `air_vel_y = 0`, `grounded = 0`, advancing `anim_frame` and `contact_ceil = 1` on its first tick | N for the fields; **R** for the class mapping, the durations and the `LandingFallSpecial` runs (already measured) |
| V7 | observation shape and scaling | unit tests: Dict space, `agent (45,)`, `action_class (23,)`, flat 626, bounds, indices 0-27 bit-identical to the v3 builder on the same replies, bits 30-36 and 40, 43, 44 exactly 0 / 1, `tap_*` in the 5-level set, `z_age` on the 0.1 grid, `anim_speed` in 0..1, forbidden button bits never set, masked rows exactly zero, every value finite and inside the space over all existing captures with a synthetic `input` object, the contract description and digest stable, inference timing within the M7n envelope | R |
| V8 | unchanged v3 / reward / replay behaviour | v3 contract digest `4ddc2933…` and table-v1 digest `97db1152…` unchanged; `python rl/m7n_tests.py unit`, `rl/m7g_obs_tests.py unit`, `rl/m7b_config_tests.py`, `rl/m7g_k_tests.py unit` pass with the new module present; reward-v2 rows recomputed from the pinned artifacts' recorded observations are identical; a v3 profile resolves without `SSB64_RL_INPUT` in its flags; a v4 profile is rejected without all three flags or with observation normalisation on | R (the replay itself: N, in V1) |
| V9 | resource cost | worker native round trip and Python wrapper time under v4 vs v3 (M7n measured +0.17 / +0.21 ms for v3); descriptive, not a gate | N |
| V10 | RNG prohibition | code review: the new fill reads no RNG state, seeds or counters; grep for `syUtilsRand` / `gSYRandom*` in the diff is empty | R |

Existing records that serve as baselines without any run: the M7g / M7n reference capture sets (`runs/m7g/_equiv`,
`runs/m7n/_equiv`), the 12 pinned action sequences and their status / hitlag / landing facts (audit §7), the
v3 contract and table digests, and the tracked replay's completion record.

---

## 7. What v4 can and cannot do about one-tick action spam

Can: the policy sees, on every tick, which buttons the game already holds, whether the stick direction is still
fresh (and whether the game forced it stale), how old the last Z is and whether the window is over, and how far
and how fast the current move is progressing. A press repeated on consecutive ticks is visibly not an edge; a
fresh tap is visibly available or not; shield-holding is visibly a continuation. The information needed to learn
"release for one tick, then press" or "hold Z" is present instead of hidden.

Cannot: v4 changes only the conditional input of a per-tick, memoryless policy. Sampling stays independent tick
by tick, so a stochastic policy can still emit alternating or repeated words at high entropy; the decision period
stays one tick (the hold-k probe found no foothold, `rl_action_hold_probe_2026-09-27.md`); credit assignment over
100-tick manoeuvres and the zero first-event rate (`rl_learning_setup_review_2026-09-27.md`) are untouched.
Memory across ticks (frame stacking or recurrence) and any change of decision period are policy-architecture or
action-contract questions, separate from this observation contract and not proposed here.

---

## 8. Decisions

### 8.1 Resolved (revisions 2 and 3)

| id | decision | resolution |
| --- | --- | --- |
| D1 | separate `input` object vs `entity` v2 | separate opt-in object `btt_input_state_v1` under `SSB64_RL_INPUT=1`; `btt_entity_v1` intact |
| D2 / Q1 | `StopCeil` class | **dedicated `air_lock` class** (rev 3); `helpless` reserved for `FallSpecial` |
| D3 | tap encoding | 5-level: 1 → 1.0, 2 → 0.75, 3 → 0.5, 4..253 → 0.25, 254 → 0; native 0 → 0 with an anomaly count (§3.4) |
| D4 | Z representation | `z_age = min(t, 10) / 10` plus `z_out = (t > 10)` |
| D5 | raw status scalar | kept at index 17, v3 slice bit-identical |
| D6 | diagnostic width | full native values in the diagnostic; bounded, scaled values in the policy block |
| D7 | `LandingFallSpecial` | validated for Mario; `character_dependent` for the common id |
| D8 | names | `btt_policy_obs_v4_input`, `rl/m7q_obs.py`, `btt_input_state_v1`, `btt_action_class_table_v2` |
| Q2 | `anim_speed` in the policy block | **added** as index 42, `clip(s, 0, 2) / 2` (rev 3) |
| Q3 | `hold_L` | **kept** (rev 3) |
| Q4 | tick-0 Z counter | **recorded, never required** to be at least 11 (rev 3) |

Final shapes: `action_class (23,)`, `agent (45,)`, flat **626**.

### 8.2 Genuinely unresolved

None that blocks implementation. Two facts were recorded after implementation without changing any encoding
(implementation §2): the tick-0 `tics_since_last_z` is 61 and the tick-0 `anim_frame` is the Wait animation's frame
11 (control lock before the GO signal); and the next-tick landing boundary is `z_age = 1.0` (previous counter ≥ 10),
not `z_out` (rows 39-40). Whether `z_out` should be re-cut at counter ≥ 10 (so that the bit equals "the next landing
lags without Z") is a possible later contract revision, not made here: the native values are exposed as they are
and the reading is documented.

No training campaign, pilot, probe or native capture is proposed or started by this document.
