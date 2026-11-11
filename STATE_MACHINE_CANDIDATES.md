# State-machine candidates for Mario's Break the Targets (2026-11-05)

Cloud session, branch `cloud/2026-11-05-states` (from `cloud/2026-11-04-glitch` at `131ce23`). Offline only: the game was
never run, no ROM was available, the game code was only read. Decomp pinned at `e4f0634`; paths are relative to `decomp/`
unless they start with `port/`, `rl/`, `tools/` or `docs/`.

**Purpose.** `GLITCH_CANDIDATES.md` audited collision. This record audits Mario's action state machine: the statuses, their
windows, what a status change resets, the order of work inside one tick, and the places where an input, a transition or
a collision event lands one tick earlier or later than a player would expect. It is for **detecting and explaining**
what the agent does. It proposes no route, no input sequence and no place on the stage, and none of it should become a
reward, goal, curriculum or action prior.

**Evidence labels.** [code]: read at the cited line. [data]: read in the decomp's relocData C source (byte-identical to
the ROM). [measured here]: computed in this session by `tools/glitch/states/` from the decomp source. [inferred]: my
reasoning from the code, not observed in the game. [unverified]: needs a local run.

**Ticks.** "Tick 0" of a status is the update that set it: the post-update capture shows `status_total_tics == 0`
(reset at `src/ft/ftmain.c:4807`). An animation frame N of a status whose setter plays the first frame twice (the
`+1 entry` below) happens on status tick N − 1.

## Short answer

- **Mario reaches 82 of the 229 statuses here** [measured here], plus the four death statuses. The rest need items,
  ledge-grab lines, other fighters, damage or pipes, none of which exist on this stage (section 1.1).
- **A status change resets very little** [code: `ftMainSetStatus`, `src/ft/ftmain.c:4579-5225`]. It clears hitboxes, the
  fast-fall flag (unless preserved), the pass-through ignore line, `status_total_tics` and a few display flags. It keeps
  velocities, `jumps_used`, the four motion-script flags and the `status_vars` union. Each setter re-initialises what its
  status reads. Section 1.3 lists the exceptions.
- **The order inside one tick decides most "frame-perfect" effects** (section 2) [code]:
  - a status set by `proc_update` (animation end) runs the new status's `proc_interrupt` in the same update;
  - a status set by `proc_map` (landing, ceiling, leaving a floor) waits until the next tick for its interrupt and
    physics, and the old status's hitboxes are gone before that tick's hit test.
- **41 of the 82 reachable statuses start on animation frame 1** [measured here]. Their setters call
  `ftMainPlayAnimEventsAll` after `ftMainSetStatus`, so frame 0 and frame 1 both run on the entry tick. Every
  frame-numbered event (hitboxes, flags, the fireball spawn) and the animation end come one tick earlier than the frame
  data says. This covers all aerials, tilts, smashes, the jab, dash, turn, squat, shield, roll and grab, and all three
  specials.
- **Most plausible "glitch-looking" observations, ranked** [inferred]. All of them are original behaviour of the matching
  code:
  1. **status chaining inside one tick** (S1): states that never show up in a trace (squat → jump → double jump in one
     update);
  2. **Mario Tornado** (S3): sustained rise from repeated B taps while the rise window is open. The rise charge comes back
     on any landing, including the ground touch in the middle of the tornado. Each ground-to-air switch sets
     `jumps_used = 1`, and the hitboxes vanish for up to 2 ticks after each switch;
  3. **aerial landing branches** (S4): no landing lag at all when the aerial ends its fall slower than 20 units per tick.
     Collision decides "landed" from the motion relative to the floor, while the lag rule reads Mario's absolute vertical
     speed. On a rising platform the two disagree;
  4. **the dash-start roll** (S7): a stale motion flag 1 from `Dash` turns Mario around on the roll's first tick. The roll
     then ends facing where it travelled instead of turned around. This is the one place where the code reads a flag it
     never reset (`ftcommonescape.c:14` vs `ftcommondash.c:121`);
  5. **ceiling contact** (S8): below 30 units per tick upward, a jump or fall keeps its upward velocity while the
     position is clamped (Mario hugs the ceiling). At 30 or more, `StopCeil` freezes vertical motion for 7 ticks with no
     gravity, no air friction and no interrupt.
- **Hitting a target with Mario's body freezes Mario** (S6) [code]:
  - `hitlag = (int)(damage / 3 + 5)` is set at the end of the hit tick, and Mario is frozen for `hitlag − 1` updates
    while the clock runs (`src/ft/ftmain.c:4134`, `src/ft/ftparam.c:1674-1687`);
  - fireball breaks freeze Mario not at all;
  - button presses made during the freeze are buffered; stick-tap windows keep counting down.
- **The clock** (section 4) [code, record]:
  - `time_passed` counts scheduler tics. The port posts one per stepped update.
  - It adds nothing on the first Go tick and counts the tick that breaks the last target, so
    `time_passed = completion_input_tick − 1`.
  - The displayed hundredths come from `ticks mod 6` divided by 0.554, so they can only be 0, 1, 3, 5, 7 or 9.
  - **Below 8 s means `time_passed ≤ 479`, that is `completion_input_tick ≤ 480`**; 7.43 is `time_passed = 446`.
- **No PORT-only behaviour on the restricted agent's state path** [code, measured here], given the frozen configuration
  that refuses the TapJump and AutoZCancel CVars (`rl/m8_rd_session.py:62`). The PORT animation-parser changes do not
  touch Mario's gameplay animations: none has a payload with bit 15, and none uses the event32 parser. The special-move
  registry is seeded from the vanilla tables (section 3, S15).
- **Detection** (section 5): `tools/glitch/states/state_detect.py` reads today's traces (all five blocks are recorded on
  verification ticks). It counts the ordinary mechanics and emits `btt_glitch_event_v1` events for departures from what
  the code allows. The static table comes from `tools/glitch/states/mario_states.py extract`.

## 1. Mario's states in Break the Targets

### 1.1 What is reachable

`tools/glitch/states/mario_states.py extract` builds the transition graph from the status descriptors and the C bodies of
every proc and helper (section 6). It then walks it from `Wait` with these statuses removed, each for a reason checked in
the code or data:

| ids | statuses | why unreachable here |
| --- | --- | --- |
| 4-9 | Sleep, Entry, Rebirth | before Go, or after a lost stock (a fall ends the episode) |
| 37-57, 67-83 | damage, down, passive, rebound | nothing on the stage has a hitbox that hurts Mario |
| 60-65 | Twister, barrel, pipes | not on this stage |
| 84-99 | ledge | no line carries the ledge flag (`GLITCH_CANDIDATES.md` §1.5) |
| 100-151 | item and hammer statuses | Mario holds no item; targets are items but cannot be picked up |
| 167-188 | grab follow-ups, capture, thrown | need another fighter |
| 221-222 | Appear | before Go |

**Reached** [measured here]: 0-3 (death, terminal), 10, 13, 15-36, 58, 59, 66, 152-154, 156-166, 189-220, 223-228. The
two-step grab (`Catch`, 166) is reachable through R alone (S11). Its follow-ups need a victim.

### 1.2 The statuses that matter, with their windows

The full table (82 rows: animation length, nominal end tick, every setter, exits, window comparisons, motion-script
events, inputs read) is generated as `logs/glitch/states/mario_states.md`. The rows below keep what explains behaviour
with the restricted inputs. "Ticks" uses the convention above. Inputs: stick ±80 or 0 per axis, at most one of A, B,
C-up, C-left, L, R or Z per tick (`rl/btt_learning.py:119-140`).

Except where a row says otherwise:

- [code] comes from the status's procs, its setter and `ftcommon.h`;
- [data] comes from the motion scripts in `src/relocData/202_MarioMainMotion.c` and the animations in
  `src/relocData/<id>_FTMarioAnim*.c`;
- [measured here] marks the frame counts the extractor computed.

**Ground movement**

| status | duration | windows (when → into what) | inputs read | entry: set / inherited |
| --- | --- | --- | --- | --- |
| Wait 10 | loop | every tick, in this order (`src/ft/fighter.h:47-69`): neutral/up/down special (B; stick y ≥ 40 = up, ≤ −40 = down), grab (Z held + A tap), smashes S4/Hi4/Lw4 (A with a fresh stick tap), tilts S3/Hi3/Lw3 (A with the stick held), jab (A), shield (Z held), taunt (L tap), jump squat (C tap, or stick y ≥ 53 within 3 ticks of crossing 20), dash (\|x\| ≥ 56, fresh tap), pass-through drop, squat, turn, walk | A, B, Z, L, C taps; Z hold; stick and tap counters | ground; `jumps_used = 0` when it lands Mario |
| Dash 15 | 23 frames, +1 entry → Wait on tick 22 (ground speed × 0.75) | standing dash only (`flag1 = 1`): anim ≤ 5 → fireball, grab, forward smash; anim ≤ 3 → **Z = forward roll**; shield. Otherwise anim ≤ 20 → fireball, run grab, dash attack, dash back, shield. After that grab, dash, shield; then taunt, jump squat, run (`ftcommondash.c:23-89`) | A, B, Z, L, C, stick x tap | `vel_ground.x = dash_speed` (54), `flag1 = 1` from Wait, 0 from Turn (`ftcommondash.c:112-120`, `ftcommonturn.c:89`) |
| Run 16 / RunBrake 17 / Turn 18 / TurnRun 19 | loop / 23 / 12 (+1: 11 ticks) / 22 | Turn's direction flag at anim 6; TurnRun's at 16 | stick x | Turn resets flag1 before it sets the status (`ftcommonturn.c:114`) |
| Squat 28 / SquatWait 29 / SquatRv 30 | 8 (+1: 7) / loop / 12 (+1: 11) | squat on a pass-through line: stick ≤ −53 within 4 ticks → Pass after a 3-tick wait (`FTCOMMON_SQUAT_PASS_WAIT`) | stick y, tap y | — |
| Pass 33 | 25 frames → 24 ticks (air) | air special, aerial, double jump from tick 0 | as Fall | `ga` air, `jumps_used = 1`, `vel_air.y = 0`, x clamped to 30, `ignore_line_id` = the floor (`ftcommonpass.c:19-28`) |
| Ottotto 36 / OttottoWait 35 | 13 / loop | every ground action except walk; walk needs stick x·lr ≥ 60 | ground set | **all velocities zeroed** at entry (`ftcommonottotto.c`, setter) |

**Jumps and falls**

| status | duration | windows | inputs read | entry |
| --- | --- | --- | --- | --- |
| KneeBend 20 | **3 ticks**: Jump is set on tick 3 (`attr->kneebend_anim_length` 3.0 [data], compared in `ftcommonkneebend.c:14-34`). The 7-frame animation does not end it | ticks 1-2: up-B (stick y ≥ 40 + B tap) or up-smash. Ticks 1-3: releasing any C button → short hop (button jumps only, `FTCOMMON_KNEEBEND_SHORTHOP_FRAMES` 3). Ticks 0-2: jump force = the highest stick y | C release, B/A taps, stick y | `jump_force`, frame counter, input source and short-hop flag set (`:54-64`) |
| JumpF 22 / JumpB 23 | 40 / 100 frames → Fall | **from tick 0, inside the squat's last update** (S1): air special, aerial, double jump | B, A, C taps, stick | `ga` air, `jumps_used = 1` (`mpCommonSetFighterAir`, `src/mp/mpcommon.c:897-904`); `vel_air` from the jump rule (S9); `tap_stick_y = 254` so the same stick tap cannot double jump |
| JumpAerialF 24 / JumpAerialB 25 | 60 / 90 frames → Fall | same as Jump, from tick 0 | same | `jumps_used++`; `vel_air.y = (80·0.7 + 26)·0.9 = 73.8` always; `vel_air.x = stick_x·0.35` (`ftcommonjumpaerial.c:129-183`) |
| Fall 26 / FallAerial 27 | loop | air special, aerial, double jump while `jumps_used < 2` | same | FallAerial when `jumps_used ≥ 2`; fast fall kept (`ftcommonfall.c:19-38`) |
| FallSpecial 58 | until landing | only the double-jump check, which always fails (`jumps_used = jumps_max` at entry) | stick for drift ×0.6 | `jumps_used = 2`; landing → LandingFallSpecial (`is_goto_landing`), passes through one-way floors while stick y ≤ −44 (`ftcommonfallspecial.c:25-99`) |
| StopCeil 66 | 8 (+1: 7 ticks) → Fall | **none**: no interrupt, no physics proc | — | `vel_air.y = 0`; x velocity kept unchanged for 7 ticks (`ftcommonstopceil.c`, status 66 has NULL interrupt and physics) |

**Landings**

| status | duration | interruptible | entered when |
| --- | --- | --- | --- |
| LandingLight 31 | 7 ticks | from anim frame 4 (tick 4), every ground action (`ftcommonlanding.c:36-57`) | falling at or below −20, no fast fall |
| LandingHeavy 32 | 7 frames at speed 0.5 → 14 ticks | from tick 8 | fast-falling at ≤ −70 |
| LandingAirF 215 / B 216 / Hi 217 | 30 / 15 / 40 ticks | no | aerial with flag1 set, no Z in the last 10 ticks |
| LandingAirNull 219 (neutral and down air) | 7 frames at speed flag1 / 100 → 14 ticks (neutral, 50 %) or 35 ticks (down, 20 %) | no | same rule, for the aerials without a landing animation (`ftcommonattackair.c:80-85`) |
| LandingFallSpecial 59 | 7 frames at 0.28 → **25 ticks** [measured here] | no (`is_allow_interrupt` FALSE for the Super Jump Punch) | FallSpecial or Super Jump Punch landing |
| (none: straight to Wait) | 0 | — | aerial or Jump/Fall landing with `vel_air.y > −20` (S4) |

**Attacks** (animation frames; with the +1 entry, hitbox frame N is status tick N − 1) [data, measured here]

| status | anim frames → end tick | hitbox frames | landing-lag flag1 (aerials) |
| --- | --- | --- | --- |
| Attack11 190 / 12 191 / 13 220 (jab 1-3) | 18 → 17 / 20 → 19 / 26 → 25 | 2-3 / 3-5 / 3-7 | follow-up window flag1 at 10 / 8 |
| AttackDash 192 | 40 → 40 (no +1) | 7-27 | — |
| AttackS3 195, Hi3 199, Lw3 201 | 43 → 42, 42 → 41, 40 → 39 | 8-17, 5-16, 5-11 | — |
| AttackS4 204, Hi4 207, Lw4 208 | 54 → 53, 60 → 59, 45 → 44 | 16-20, 7-15, 8-29 | — |
| AttackAirN 209 | 50 → 49 | 3-36 | 50 % from 3 to 36 |
| AttackAirF 210 / B 211 / Hi 212 / Lw 213 | 40 → 39 / 40 → 39 / 40 → 39 / 39 → 38 | 11-26 / 10-19 / 2-11 / 10-11 | 11-26 / 10-19 / 2-11 / 10-32 (20 %) |

Aerials are entered by an A tap with the stick deciding the direction (≥ 20 on an axis; up and down beyond 50°,
`ftcommonattackair.c:96-227`). The setter clears flag1 first, keeps fast fall, plays frame 0 twice and sets
`tics_since_last_z = 65536`. The aerial's own proc_interrupt is NULL: nothing cancels an aerial but its landing or its end.

**Specials**

| status | phases (animation frames; tick = frame − 1) | windows | exits |
| --- | --- | --- | --- |
| SpecialN 223 / SpecialAirN 224 (fireball) | +1 entry; `flag0` at frame 16 spawns the fireball (tick 15) through `proc_accessory` after collision (`ftmariospecialn.c:17-48`); 46 frames → tick 45 | none (no interrupt proc) | Wait or Fall at the end. Air → ground on landing and ground → air on leaving the floor, both keeping the frame (continuation entry). The ground version's map proc is stop-edge, so it does not walk off a floor end (M8 snap) |
| SpecialHi 225 / SpecialAirHi 226 (Super Jump Punch) | +1 entry. Frames 1-5: ground version on the ground with TransN ground velocity; air version at `vel_y := 0`, `vel_x /= 1.5`, gravity 0.5. Frame 6 (tick 5): motion event `SetAirJumpMax` sets `ga` air and `jumps_used = 2` directly; flag1 and flag2 set. From frame 6: TransN velocity (air version ×0.95). Hitboxes 2-7, then every 2 frames to 23. 40 frames → FallSpecial on tick 39 (`ftmariospecialhi.c`, `202_MarioMainMotion.c:1349-1375`) | while flag1 == 0 (ticks 0-4): \|stick x\| > 50 sets the TransN rotation, and only a larger angle replaces it. On the flag2 tick (5): \|stick x\| > 20 turns Mario toward the stick | no landing test while flag1 == 0 or `vel_y ≥ 0` (projection only). Afterwards: a pass-through floor is ignored if stick y < −44; landing → LandingFallSpecial (25 ticks) |
| SpecialLw 227 / SpecialAirLw 228 (Mario Tornado) | ground start enters **SpecialAirLw directly**: `ga` air, `jumps_used = 1`, `vel_y = −7`, then frame 0 played twice (`ftmariospeciallw.c:150-161`). Air start: `vel_y = 15 − (charge spent ? 0 : 22)`. Frames 0-42: `flag3` (rise window). Frame 43: rise window closes, ground friction starts, and the air script sets `flag2` (charge spent). Hitboxes every 3 frames. 83 / 87 frames | rise: B tap while flag3 and the charge is unspent → `vel_y += 22`, capped at 40 (air) or, on the ground, switch to air (`:64-95`) | landing ↔ air switches keep the frame (continuation). End → Fall or Wait |

**Shield, roll, grab, taunt**

| status | duration | notes |
| --- | --- | --- |
| GuardOn 152 / Guard 153 / GuardOff 154 | 4 (+1: 3) / held / 12 (+1: 11) | Z or R held. The shield decays while held. At 0, ShieldBreakFly 158 (vertical launch, intangible) → Fall 159 → down → stand → dizzy 164 (reachable with Z alone, but slow) |
| EscapeF 156 / EscapeB 157 | 32 (+1: 31) | from Dash (Z tap, anim ≤ 3) or from Guard (stick x ≥ 56 tap). Intangible 4-19. **Flag1 is read but not reset at entry** (S7); it is cleared on exit by `proc_status` |
| Catch 166 | 16 (+1: 15) | grab = Z held + A tap: only R gives both with one button (S11). Its proc logs a line every tick under PORT (`ftcommoncatch1.c:13-28`, diagnostics only) |
| Appeal 189 | 180 ticks | L tap; its interrupt (grab) opens at frame 128 |

### 1.3 What a status change resets, and what it keeps

`ftMainSetStatus` (`src/ft/ftmain.c:4579-5225`) [code]:

- **Resets**:
  - hitboxes: `ftParamClearAttackCollAll` unless `FTSTATUS_PRESERVE_HIT` (`:4673-4676`);
  - `is_fastfall` unless `PRESERVE_FASTFALL` (`:4716-4719`);
  - `is_reflect`, `is_shield`, `is_hitstun`, `is_jostle_ignore`;
  - `coll_data.ignore_line_id = -1` (`:4759`);
  - `status_total_tics = 0` (`:4807`);
  - `damage_mul`, `knockback_resist_status`, `is_special_interrupt`;
  - the TopN yaw = lr · 90° (`:4736`);
  - `vel_air.z`, `vel_ground.z`;
  - all procs except the four of the new status;
  - motion script 0 restarted at `frame_begin`; scripts 1-3 cleared.
- **Runs**:
  - the old status's pending effects (`ftMainUpdateMotionEventsForwardEffect` and `proc_accessory`, `:4656-4664`), so a
    fireball whose flag was set this tick is still spawned when a landing switches status in the same tick;
  - then the old status's `proc_status` exit hook (`:4888-4892`): `EscapeF/B` clears flag1 there, and Attack11 and AttackLw3
    have their own.
- **Keeps**:
  - `vel_air.x/y` and `vel_ground.x`;
  - `jumps_used`;
  - `motion_vars.flags.flag0-3`;
  - the `status_vars` union;
  - `tap_stick_*`, `hold_stick_*`, `tics_since_last_z`;
  - `hitlag_tics`, `lr`, `shield_health`;
  - `passive_vars` (the tornado charge).

**Kinetics helpers** [code]:

- `mpCommonSetFighterAir` sets `ga` air and `jumps_used = 1` (`src/mp/mpcommon.c:897-904`).
- `mpCommonSetFighterGround` sets `ga` ground, `jumps_used = 0` and `vel_ground.x = vel_air.x · lr` (`:885-894`). Air
  speed becomes ground slide.
- `mpCommonSetFighterLandingParams` runs on every air-collision landing and resets the tornado charge (`:425-449`).
- Motion events `SetAirJumpAdd` and `SetAirJumpMax` change `ga` and `jumps_used` without either helper
  (`src/ft/ftmain.c:421-440`).

**Fast-forwarded entries** [code]. `ftMainSetStatus(..., fighter_gobj->anim_frame, ...)` (fireball and tornado
ground ↔ air switches, walk speed changes) replays the new motion script up to the current frame with
`ftMainUpdateMotionEventsForward` (`:855-947`). That replay skips SetFlag0/1/2, hitbox creation, hitbox edits and the
air-jump events, and runs SetFlag3, waits, loops, gotos and subroutines.

**Motion flags read without a reset at entry** [measured here, then read]:

- `EscapeF/B` flag1 (S7) is the only case.
- `SpecialAirLw` flag2 is inherited on the ground → air switch. That one is consistent, because the ground script never
  sets flag2.

### 1.4 Counters and limits

- **`jumps_used`** [code]:
  - 1 on any ground → air change through `mpCommonSetFighterAir`: jump, fall, drop, fireball or tornado switch, tornado
    ground start, shield break;
  - 0 on landing;
  - +1 per double jump;
  - 2 from the Super Jump Punch motion event at frame 6 and at FallSpecial entry.

  **Nothing on Mario's reachable path lowers it in the air** [measured here: every `mpCommonSetFighterAir` call on the
  reachable path is behind a ground check or comes from a grounded status].
- **Super Jump Punch "limit"**: there is no usage counter. It makes `jumps_used = 2` and ends in FallSpecial, which has no
  usable interrupt until landing.
- **Tornado charge** (`passive_vars.mario.is_expend_tornado`) [code]:
  - set when the air tornado consumes flag2 at frame 43 (`ftmariospeciallw.c:34-43`);
  - cleared by every air-collision landing (`src/mp/mpcommon.c:445-450`) and at spawn (`src/ft/ftmanager.c:644`);
  - while set, the next air tornado starts at +15 and B taps do not lift.
- **`tics_since_last_z`**: counts from the last Z (or R) press and is set to 65536 by every aerial entry. Landing within
  10 ticks of a Z press during the aerial gives the normal landing instead of the aerial landing lag (S4).
- **Stick tap counters**: `tap_stick_x/y` go to 1 on the first tick the axis passes ±20, then count up to 254; they are
  updated even during hitlag (`src/ft/ftmain.c:1446-1500`). Smash, tap jump, dash, fast fall and drop windows read them.

## 2. Order of operations in one tick

### 2.1 The update, process by process [code]

`gcRunAll` (`src/sys/objman.c:2335-2371`) first runs each GObj's `func_run` over the links, then the process queue from
priority 5 down to 0. Within a priority, processes run in registration order.

1. **Input**: the controller read publishes port 0's frame before the scene update (`port/rl/rl_step.cpp` header,
   `src/sys/netinput.c`).
2. **Clock**: `ifCommonTimerFuncRun` is a `func_run`, so it runs before any process. It adds the scheduler tics since its
   stamp (`src/if/ifcommon.c:2686-2700`).
3. **Priority 5, fighter `ftMainProcUpdateInterrupt`** (`src/ft/ftmain.c:1351-1709`):
   1. `status_total_tics++` (`:1372`);
   2. the controller is latched; R is expanded to R + A + Z (`:1387-1390`); taps and releases are computed against the last
      latched hold, and OR-ed during hitlag (`:1394-1402`);
   3. the stick is clamped to ±80; tap counters (`:1446-1500`); the Z timer (`:1509-1517`);
   4. hitlag is decremented, and `proc_lagend` runs on 0 (`:1518-1531`);
   5. if not in hitlag: animation and motion-script events of this frame (`:1534-1537`);
   6. colour animation, timers, `proc_passive`;
   7. **if not in hitlag: `proc_update`, then `proc_interrupt` (`:1630-1643`)**. The interrupt pointer is read after
      `proc_update` returns, so a status set there gets its own interrupt checked at once.

   The BTT clock sprite updates at the same priority (`src/sc/sc1pmode/sc1pbonusstage.c:1845`).
4. **Priority 4, fighter `ftMainProcPhysicsMap`** (`:1876-2053`):
   1. if not in hitlag: `proc_physics` and `pos += vel_air` (`:1890-1934`);
   2. moving-floor carry;
   3. **death check** (`:1952`);
   4. `proc_map` (collision, landing, leaving a floor, ceiling) (`:1965-1979`);
   5. slope contour;
   6. pending effects and `proc_accessory` (the fireball spawn);
   7. **hitbox world positions for every active hitbox, also during hitlag** (`:2002-2052`).

   The ground's moving platforms and `mpCollisionAdvanceUpdateTic` are also at priority 4 (`src/gr/grdisplay.c:221-226`).
5. **Priority 3**: items (target animation) and weapons (the fireball moves and collides) (`src/it/itmanager.c:446`,
   `src/wp/wpmanager.c:323`).
6. **Priority 1**: hit searches. The item search tests fighter hitboxes and weapons against the target's hurtbox
   (`src/it/itprocess.c:672-1013`). A fighter hit sets `fp->attack_damage` (`:311-314`).
7. **Priority 0**:
   - `ftMainProcParams`: attacker hitlag from `attack_damage` (`src/ft/ftmain.c:4092-4160`);
   - `itProcessProcHitCollisions`: the target's `proc_damage` breaks it and decrements the count. On the last target it
     sets `game_status = End` (`src/it/itground/ittarget.c:35-50`, `src/sc/sc1pmode/sc1pbonusstage.c:1313-1348`,
     `src/if/ifcommon.c:3513`).

### 2.2 Where something lands one tick early or late

| # | what | why [code] | what a player would expect |
| --- | --- | --- | --- |
| W1 | the next status's interrupt runs in the same update when `proc_update` ends a status (animation end, the squat's third tick) | `:1636-1643` | one tick of the new status before acting |
| W2 | a status set in `proc_interrupt` gets its physics, its frame-0 and frame-1 hitboxes and its hit test in the same tick | priority 5 → 4 → 1 | — (this is the "same frame" a human expects) |
| W3 | a status set in `proc_map` (landing, leaving a floor, StopCeil, tornado and fireball switches) gets no physics or interrupt until the next tick | priority 4 is past both | acting on the landing frame |
| W4 | the old status's hitboxes are cleared before the hit test of the tick it lands in | `ftMainSetStatus` at priority 4 (`:4673`), hit test at priority 1 | the aerial hits on the landing frame |
| W5 | the setter plays frame 0 then frame 1 (41 statuses) | `ftMainSetStatus` + `ftMainPlayAnimEventsAll` | frame data counted from the press |
| W6 | a fresh hitbox is a point at the end-of-tick position on its first tick, then the swept segment from the previous position | `:2008-2016`, `src/gm/gmcollision.c:719` | the limb's sweep on its first frame |
| W7 | button presses during hitlag are kept and acted on in the first free update; taps and releases of the hit tick are cleared; stick-tap windows keep counting | `:1396-1402`, `:4157`, `:1446-1500` | presses during the freeze are lost, or the stick tap survives it |
| W8 | the death check runs before collision | `:1952` | collision first |
| W9 | the tornado switches to air in `proc_physics` (B tap), so the same tick's collision is the air status's | `ftmariospeciallw.c:66-74` | — |
| W10 | the clock adds the tick that breaks the last target; it stops from the next update | section 4 | — |

## 3. Candidates, by plausibility with the restricted inputs

"Status": OB = original behaviour of the matching (non-PORT) code; Q = original but reads like an oversight; P = PORT
difference.

| rank | id | mechanism | plausible with one button per tick | status |
| --- | --- | --- | --- | --- |
| 1 | S1 | status chaining inside one update: intermediate statuses never captured | certain | OB |
| 2 | S2 | the +1 entry (41 statuses); continuation entries and the fast-forward | certain | OB |
| 3 | S3 | Mario Tornado: rise window, charge, re-arm on landing, `jumps_used = 1` on each switch, hitbox gap after a switch | high | OB |
| 4 | S4 | aerial landing branches; no lag at `vel_y > −20`; landing tick clears the hitboxes; relative-vs-absolute on the moving platform | high | OB |
| 5 | S9 | jump rules with the square-gate diagonal and the two C buttons | certain | OB |
| 6 | S6 | body-hit hitlag on breaks; buffered taps; fireball breaks free | certain (explains time) | OB |
| 7 | S7 | dash-start roll keeps Dash's flag1 → the roll ends facing its travel direction | moderate to high | Q |
| 8 | S8 | ceiling: velocity kept below 30, StopCeil lock at or above 30 | high where a ceiling is reachable | OB |
| 9 | S5 | Super Jump Punch phases, no landing while rising, FallSpecial lock | high | OB |
| 10 | S11 | R is A + Z on the same tick | certain | OB |
| 11 | S12 | fireball: frame-16 spawn, ground/air continuation, stop-edge map | high | OB |
| 12 | S13 | pass-through drop: the ignore line resets on the next status change | low as an anomaly | OB |
| 13 | S14 | shield break launch from a held shield | low (hundreds of ticks of shield) | OB |
| 14 | S10 | `jumps_used` lowered in the air | none found in code; would be a real anomaly | — |
| 15 | S15 | PORT-only deltas on the state path | absent for Mario with the frozen configuration | P (absent) |

### S1: status chaining inside one update [code; plausibility inferred]

- **Where**: `src/ft/ftmain.c:1630-1643`; the KneeBend → Jump set in `proc_update` (`ftcommonkneebend.c:14-34`); every
  `ftAnimEnd*` exit (`src/ft/ftanimend.c`).
- **How**: `proc_interrupt` is read after `proc_update` returns. When `proc_update` changes the status (animation end,
  squat end), the new status's interrupt checks run on the same input in the same update.
- **Examples**:
  - squat → JumpF → JumpAerialF in one update (a C tap on the squat's third tick, possible by alternating C-up and C-left);
  - JumpF's animation end → Fall → an aerial on the same tick;
  - SJP's animation end → FallSpecial.

  A status set by `proc_interrupt` or `proc_map` does not chain.
- **Observable**:
  - a trace shows `KneeBend` followed directly by `JumpAerialF` with `jumps_used` 2, and JumpF never appears;
  - the first jump's velocity is overwritten in the same update.
- **Detection**: transitions explained by one intermediate edge are counted (`chain:A>X>B`); transitions explained by none
  are emitted (`status_transition_unlisted`).

### S2: entry double advance, continuations, fast-forward [code, measured here]

- **Where**: the setters list (`logs/glitch/states/mario_states.json`, `entry[].double_advance`); examples:
  - `ftcommonattackair.c:205-212`;
  - `ftmariospecialhi.c:142-168`;
  - `ftmariospecialn.c:103-116`;
  - `ftmariospeciallw.c:149-182`;
  - `ftcommondash.c:112-120`;
  - `ftcommonescape.c:46-56`.
- **How**: the setter calls `ftMainSetStatus` (which plays frame 0 and runs its events) and then
  `ftMainPlayAnimEventsAll` (frame 1). Async waits (`WaitAsync(N)`) key on the animation frame, so an event at frame N
  runs on status tick N − 1, and an animation of L frames ends on tick L − 1.

  Wiped flags: some setters clear a flag after the double pass (Attack11's flag1, the fireball's flag0). In every one of
  them the script sets that flag later than frame 1 [measured here: no `script_flags_wiped_at_entry` on Mario's
  reachable statuses].
- **Continuations**: on a landing, a floor exit or a B tap, the fireball and the tornado switch status keeping the
  animation frame, with the fast-forward rules of §1.3.
- **Observable**:
  - `anim_frame` at the entry tick is 1 instead of 0 (+1), or the old frame plus the speed (continuation);
  - inside a status, `anim_frame` advances by `anim_speed` per tick except in hitlag;
  - the animation ends on the predicted tick.
- **Detection**: `entry_frame_unexpected`, `anim_clock_skew` and `status_shorter_than_nominal` fire when a trace departs
  from these rules. The ordinary entries are counted (`entry:+1`, `entry:cont`, `entry:0`).

### S3: Mario Tornado [code; plausibility inferred]

- **Where**: `src/ft/ftchar/ftmario/ftmariospeciallw.c` (whole file); scripts at `202_MarioMainMotion.c:1385-1440`;
  `src/mp/mpcommon.c:425-450`.
- **How**:
  1. **Ground start**: B with stick y ≤ −40 → `ftMarioSpecialLwSetStatus`. It calls `mpCommonSetFighterAir`
     (`jumps_used = 1`), sets **SpecialAirLw** with `vel_y = −7`, plays the first frame twice and keeps
     `stat_flags.ga` ground (`:149-160`). Unless Mario is already in the air, the next collision lands him into the
     ground tornado (`SpecialLw`, continuation).
  2. **Rise**: in the air, a B tap while flag3 (frames 0-42) and the charge is unspent adds 22 to `vel_y`, capped at 40
     (`:80-95`).
     - On the ground, a B tap during flag3 adds 22 and switches to air (`:64-78`); that switch sets `jumps_used = 1` again.
     - A tap needs B released on the previous tick, so at most one tap every 2 ticks; another button in between also
       counts as a release of B.
     - The B tap that starts the tornado is also a rise tap in that tick's physics [inferred from W2: entry in
       `proc_interrupt`, physics in the same tick with flag3 set at frame 0]. A fresh tornado therefore leaves its entry
       tick at −7 + 22 − 2.4 = 12.6, the same as a spent one (15 − 2.4).
  3. **Charge**:
     - the air script sets flag2 at frame 43, which spends the charge;
     - the ground script never does;
     - any landing clears it, including the air → ground switch inside the same tornado.
  4. **Hitboxes**: the script recreates them every 3 frames. A ground ↔ air switch clears them (no `PRESERVE_HIT`), and
     the fast-forward does not recreate them, so the tornado has no hitbox until the script's next `MakeAttackColl`, up to
     2 ticks later [code, inferred].
- **Plausibility**: high. The agent has B and the down stick, and B-tap rise gains height fast:
  - net +17.2 per 2 ticks before the cap [inferred from the constants];
  - the window is 43 frames per tornado, and it re-arms on ground contact.

  This is the most likely source of "flying" Mario.
- **Observable**:
  - `vel_air_y` jumps by about +19.6 on B-tap ticks in status 228;
  - `jumps_used` returns to 1 after a ground touch;
  - targets in reach are not broken just after a switch.
- **Detection**: rise taps and charge resets are counted. A rise while the tracked charge is spent is emitted
  (`special_limit_rearm_unexpected`).

### S4: aerial landing branches [code; plausibility inferred]

- **Where**: `ftCommonAttackAirProcMap` (`ftcommonattackair.c:56-91`); `mpCommonSetFighterWaitOrLanding`
  (`src/mp/mpcommon.c:676-685`) for Jump/Fall.
- **How**: on landing during an aerial, `ftCommonAttackAirProcMap` picks the first branch that applies:
  1. flag1 set (the script's landing-lag window, table in §1.2) **and** no Z press in the last 10 ticks → the aerial's
     landing lag;
  2. else `vel_air.y > −20` → **Wait, no landing at all**;
  3. else the normal landing (7 ticks, actions from tick 4).

  So the window ends of each aerial, a Z press within 10 ticks, or a slow vertical speed each skip the lag. Jumps and
  falls use the same −20 rule.
- **Two systems on one tick**:
  - The floor test decides "landed" from the motion relative to the floor, in the moving group's frame
    (`GLITCH_CANDIDATES.md` M7, M9). The lag rule reads `vel_air.y`, which is absolute.
  - Landing on a rising platform while falling slowly in absolute terms therefore skips the lag [inferred].
  - The landing tick also clears the aerial's hitboxes before the hit test (W4).
- **Observable**: the landing status against `motion_flag1`, `tics_since_last_z` and `air_velocity_y` at the landing tick.
  All three are recorded, so the branch can be checked exactly.
- **Detection**: branches are counted (`landing:lag`, `landing:skip`, `landing:zcancel`, `landing:normal`,
  `landing:skip_on_moving_line`). A branch the rule does not give is emitted (`landing_branch_mismatch`).

### S9: jump rules [code, data]

- **Squat**: 3 ticks (above).
- **Stick jump** (stick y ≥ 53 within 3 ticks of crossing 20): `vel_x = stick_x · 0.35`,
  `vel_y = max(stick y during the squat, 53) · 0.7 + 26`, with **no circular limit** (`ftcommonjump.c:65-101`).
- **Button jump** (C tap): height from `17·√(1 − (x/80)²) + 63`, limited to the circle and to 77; short hop 9 / 36
  (`ftcommonjump.c:19-62`).
- **Consequences**:
  - The restricted diagonal (80, 80) is outside a physical stick gate (`rl/btt_learning.py:119-130`). With it a stick
    jump gets the full height (82) and the full drift (28) at once.
  - A button jump with |x| = 80 gets the minimum height (63 → 70.1) [inferred from the formulas].
  - The double jump is always full height (73.8); its x velocity is `stick_x · 0.35`.
- **Two C buttons**: a tap is a press relative to the previous tick's hold (`src/ft/ftmain.c:1394-1402`), so switching
  between C-up and C-left gives a fresh tap every tick. Each switch also releases the other C button: a short hop when it
  lands on squat ticks 1-3. A double jump is possible on the first jump's tick 0 (S1).
- **Up-B and up-smash** are available from squat ticks 1-2 (squat cancels).
- **Plausibility**: certain; these explain trajectories, they are not glitches.

### S6: hitlag around target breaks [code; time effect inferred]

- **Where**:
  - `itProcessUpdateDamageStatFighter` (`src/it/itprocess.c:301-314`) records the attack damage on Mario;
  - `ftMainProcParams` (`src/ft/ftmain.c:4092-4160`) turns it into `hitlag_tics = (s32)(damage/3 + 5)`
    (`src/ft/ftparam.c:1674-1687`, US) at the end of the hit tick, and clears that tick's taps and releases;
  - the next updates skip animation, update, interrupt and physics while the decremented value is non-zero
    (`src/ft/ftmain.c:1518-1643`, `:1890`).
- **Freeze lengths**: `hitlag − 1` frozen updates. From the damage values [data]:
  - tornado 1 → 5;
  - Super Jump Punch 1/3/5 → 5/6/6;
  - jab 2 → 5;
  - aerials 9-16 → 8-10;
  - smashes 17-19 → 10-11.

  The traces show `hitlag_tics = N` on the break tick, then N − 1 … 1.
- **Fireball**: a fireball break puts the weapon, not Mario, in hitlag (Mario has no `attack_damage`).
- **Last target**: the clock stops on the break tick, so its freeze costs nothing.
- **During hitlag**:
  - hitbox positions still update (`:2002-2052`), but Mario does not move, so the swept segment collapses to a point;
  - a second target can still be hit during the freeze only if it moves into the frozen hitbox [inferred];
  - buttons pressed during the freeze are acted on in the first free update (W7); a stick tap made during it expires.
- **Detection**:
  - `break:hitlag=N` is counted;
  - `break_hitlag_mismatch` is emitted when a body-only break shows no hitlag, or a weapon-only break shows hitlag;
  - `break_during_hitlag` is emitted when a target breaks while Mario is frozen.

### S7: the dash-start roll keeps Dash's flag 1 [code; effect inferred]

- **Where**:
  - `ftCommonDashSetStatus` sets `flag1 = 1` for a standing dash (`ftcommondash.c:112-120`, called with 1 from
    `:138`);
  - `ftCommonDashProcInterrupt` takes Z at animation frame ≤ 3 into `ftCommonEscapeCheckInterruptDash`
    (`:20-37`, `ftcommonescape.c:86-95`);
  - `ftCommonEscapeSetStatus` does not clear flag1 (`ftcommonescape.c:46-56`); it only installs the exit hook that
    clears it later (`:38-43`);
  - `ftCommonEscapeProcUpdate` flips `lr` whenever flag1 is set, then clears it (`:10-18`);
  - the roll script sets flag1 at frame 20 for the intended turn-around (`202_MarioMainMotion.c:306-316`).
- **How**: a roll started from the standing-dash window enters with flag1 = 1, so its first update flips `lr`, and frame
  20 flips it back.
  - The movement does not change: `ftPhysicsApplyGroundVelTransN` negates the velocity when `lr` and the model yaw
    disagree (`src/ft/ftphysics.c:190-194`), so the world-space motion is the same.
  - Only the facing changes: an ordinary roll ends facing back, this one ends facing its travel direction.
  - The same holds for any Escape entered with a non-zero flag1, for example Dash → shield → roll within the window
    [inferred: shield statuses do not touch flag1].
- **Conditions**: stick ±80 to dash from standing, then Z (with the stick) on Dash ticks 1-2. That is one button per
  tick. Facing matters for the next forward-dependent action: fireball, forward smash, aerial direction, turn costs.
- **Status**: original code (non-PORT, matching). It reads like an oversight, since every other flag-reading status
  clears its flags at entry. I found no note of it in the repository.
- **Observable**: `motion_flag1` = 1 at the EscapeF entry tick; `facing_direction` flips on the next tick and again at
  frame 20.
- **Detection**: `stale_flag_at_entry` is emitted for any status listed in the table's `stale_flag_candidates` that is
  entered with `motion_flag1 ≠ 0`.

### S8: ceilings [code; plausibility inferred]

- **Below 30 upward**:
  - The air collision clamps the position under a ceiling and never touches `vel_air.y`
    (`src/mp/mpcommon.c:475-582`; no ceiling handler zeroes velocity in Mario's statuses [code: grep of `MAP_FLAG_CEIL`
    in `src/ft`]).
  - A jump, fall or aerial therefore stays pinned under the ceiling while gravity eats its upward speed: about
    `vy / 2.4` ticks.
- **At 30 or more**:
  - Jump, JumpAerial, Fall and FallAerial use `mpCommonProcFighterCliffFloorCeil`, which sets `CEILHEAVY` (`:500-507`)
    and enters `StopCeil`.
  - `StopCeil` zeroes `vel_y` and has no physics or interrupt for 7 ticks, so x keeps its velocity with no air friction;
    then it goes to Fall.
  - Aerials and the Super Jump Punch never enter StopCeil.
- **Observable**: `mask_curr` has the ceiling bit, `vel_y > 0` and y is constant; or status 66.
- **Detection**: `ceiling_velocity_kept` is emitted for runs of 3 or more ticks; StopCeil entries are counted.

### S5: Super Jump Punch [code, data]

The phases are in §1.2. Points that matter for detection:

- The ground version flips to the air by a motion event, not by a status change. `ga` changes on tick 5 inside status 225.
- Before frame 6 it uses the stop-edge map proc. It falls into Fall (with `jumps_used = 1`, so both the double jump and
  the Super Jump Punch come back) only where the edge snap fails: a wall right at the floor end
  (`src/mp/mpcommon.c:99-164`, `:294-300`). That case is low here [inferred].
- No landing test while rising. Pass-through floors are ignored while stick y < −44 on the way down.
- FallSpecial forces LandingFallSpecial (25 ticks), so a Wait right after FallSpecial would be an anomaly
  (`fallspecial_landing_lag_skipped`).
- The TransN rotation grows only. It is the D1 input of `GLITCH_CANDIDATES.md` M13.

### S11: R is A + Z on the same tick [code]

- `src/ft/ftmain.c:1387-1390`: a held R adds A and Z to the held mask before taps are computed.
- So the restricted "one button" R is a grab on the ground: Catch needs Z held and an A tap
  (`ftcommoncatch1.c:150-155`), and grab precedes jab and shield in the check order.
- In the air, R starts an aerial and resets the Z timer, but the aerial entry overwrites it (`tics_since_last_z = 65536`).
  A later R during the aerial is a Z-cancel input.
- Holding R shields.

### S12: fireball [code, data]

- Spawn on animation frame 16 (tick 15). `proc_accessory` runs after collision, at the hand position of that tick
  (`ftmariospecialn.c:17-48`).
- Landing or leaving the floor switches status keeping the frame. The spawn happens once even when the switch is on the
  spawn tick, through the pending-effects call at the start of `ftMainSetStatus` (`src/ft/ftmain.c:4656-4664`).
- Fireball breaks cost Mario no hitlag (S6). The launch trig is libultra's (`GLITCH_CANDIDATES.md` M13).

### S13: pass-through drop [code; inferred]

- Pass sets `ignore_line_id` to the floor and `vel_y = 0` (`ftcommonpass.c:19-28`). Any later status change resets it
  (`src/ft/ftmain.c:4759`), including the aerial, special or double jump that Pass allows from tick 0.
- The first Pass tick already moves the bottom point below the line, and floors are only hit from above. So re-landing on
  the same line needs Mario to come back above it. Only an upward move does that, such as a double jump or a spent
  tornado (+15).
- An anomaly would be a landing on the dropped line with no upward motion in between.
- Not emitted today: it needs the floor id at the Pass tick, which is recorded, so it is a candidate for the next
  detector version.

### S14: shield break [code]

Holding Z keeps Guard. At zero shield health, `ftCommonShieldBreakFlyCommonSetStatus` launches Mario upward
(`shield_break_vel_y` 70 [data]), intangible, into a long down-and-dizzy sequence. Reaching zero takes hundreds of ticks
of holding [inferred from `FTCOMMON_GUARD_DECAY_INT` 16 and a 55 health start], so it is a low-plausibility curiosity.
Entries into 158 are counted.

### S10: `jumps_used` going down in the air [code]

No reachable path does it (§1.4). An observed decrease while airborne on two consecutive ticks
(`jumps_restored_in_air`), or a value above 2 (`jumps_over_max`), would be a genuine anomaly.

### S15: PORT-only deltas on Mario's state path [code, measured here]

| delta | where | effect for Mario in BTT |
| --- | --- | --- |
| AObjEvent16 block payloads read as signed (`.s`) instead of unsigned | `src/ft/ftanim.c:470-521` | none: no Mario gameplay animation has a payload ≥ 0x8000 [measured here]; only the pre-Go Appear animations do |
| gobj anim-end latch in the event32 parser | `src/sys/objanim.c:461-471` | off-path: Mario's gameplay motions use the event16 parser (`is_anim_joint` clear) [measured here]; the latch also never triggers, because nothing writes `AOBJ_ANIM_END` to `gobj->anim_frame` |
| special-move dispatch through the fighter registry | `ftcommonspecial*.c` PORT branches; seeded from `dFTCommonSpecial*StatusList` (`src/ft/ftport.c:167-172`) | same handlers |
| tap-jump, auto Z-cancel and failed-Z flash CVars | `ftcommonkneebend.c:91-96`, `ftcommonattackair.c:63-76` | off: the session refuses configurations that set them (`rl/m8_rd_session.py:62`) |
| ECB override hook in `ftMainSetStatus` | `src/ft/ftmain.c:4628-4639`, `port/fighter_registry.cpp:168-181` | none unless a mod registers one for Mario |
| NULL guards (TransN joint) and per-tick `port_log` calls | `src/ft/ftphysics.c:172-184`, `ftcommoncatch1.c:13-28`, `ftcommonspecial*.c` | no game state; Catch logs every tick to `ssb64.log` (throughput only) |

## 4. The Break the Targets clock

**Read in the code:**

- **Counter**: `gSCManagerBattleState->time_passed += time_delta`, where `time_delta` = scheduler tics since the last stamp
  (`src/if/ifcommon.c:2686-2700`). Scheduler tics come from `sySchedulerVRetrace` (`src/sys/scheduler.c:1088`). In the
  port, `PortPushFrame` posts one VRETRACE before each game update, and none while the stepping host is parked
  (`port/gameloop.cpp:752-821`).
- **Start**: on the first update whose `game_status` is Go, `ifCommonBattleUpdateInterfaceAll` marks the clock started,
  stamp 0, and sets the tic count to 0 before `gcRunAll` (`src/if/ifcommon.c:3395-3407`). The same update's
  `ifCommonTimerFuncRun` reads 0 tics and adds nothing. Go is set by the countdown during the previous update, which also
  unlocks Mario (`src/if/ifcommon.c:2203-2217`). The stepping contract makes that next update tick 0
  (`port/rl/rl_step.cpp` header).
- **Each later update** adds one tic. The timer is a `func_run`, so it is added before Mario's processes.
- **Stop**: the last target's `proc_damage` (priority 0) sets `game_status = End` through
  `ifCommonAnnounceCompleteInitInterface` → `ifCommonBattleSetInterface` (`src/sc/sc1pmode/sc1pbonusstage.c:1313-1348`,
  `src/if/ifcommon.c:3511-3525`). The next update sees a status other than Go and stops the clock before `gcRunAll`
  (`:3397-3400`). **The tick that breaks the last target is counted; no tick after it is.**
- **Display** (`sc1PBonusStageTimerProcUpdate`, `src/sc/sc1pmode/sc1pbonusstage.c:1727-1765`): the value is capped at
  59:59:59 ticks, then float divisions by 36000, 3600, 600, 60, 6 and 0.554 (`277/500`) give the six digits.

**Inferred from the above, checked against the records:**

- **`time_passed` = the consumed tick of the last break.** The records give `completion_input_tick = time_passed + 1`:
  446 / 447 for the 468-row baseline (`docs/rl_crossing_fixtures_m7g.md:471`), 1,884 / 1,883, and 1,244 for the 1,245
  clear.
- **The hundredths digit** is `floor((ticks mod 6) / 0.554)`: 0, 1, 3, 5, 7 or 9. The tenths digit is
  `floor((ticks mod 60) / 6)`.
  - The display is neither truncation nor rounding of `ticks / 60`: 4 ticks show .07 (truncation .06), 5 ticks show .09
    (truncation .08).
  - 446 → 7.43; 1,244 → 20.73; 479 → 7.99; 480 → 8.00 (`tools/glitch/states/test_states.py`, `ClockTests`).
- **8 s threshold**: a time shown below 8 s needs `time_passed ≤ 479`, that is `completion_input_tick ≤ 480`. 7.43 is
  `time_passed = 446`.
- **Hitlag**: body-hit hitlag (S6) is counted by the clock for every target but the last. Fireball breaks freeze nothing.
- **What could make the count differ from the number of updates** [inferred]:
  - On the console, a game update that takes longer than one video frame lets two or more VRETRACEs pass, and the clock
    advances by the number of tics, not updates.
  - The port never does that while stepping (one VRETRACE per update), and the 0-mismatch record over about 70,000
    dispatches (`REVIEW_2026-11-03.md` §1.1) is consistent with it.
  - **A time measured in the port equals a console time only if the console run has no lag frames** [unverified]. A
    detector check (`timer_tick_mismatch`) catches any departure in the port.
- **The record comparison** uses `time_passed` too (`bonus1_time`, `src/sc/sc1pmode/sc1pbonusstage.c:2038-2040`).

## 5. Detection

### 5.1 Signals per candidate

All signals compare consecutive ticks of one trace, plus the static table. "Today": the field is in today's verification
traces (`observation`, `btt_entity_v1`, `btt_input_state_v1`, `btt_spatial_v1`, `btt_target_identity_v1`;
`docs/frs_anomaly_inventory_2026-10-16.md` §1.2).

| id | signal | fields | today | in `state_detect.py` |
| --- | --- | --- | --- | --- |
| S1 | a status change not in the table, directly or through one intermediate edge | status, table | yes | `status_transition_unlisted`; chains counted |
| S2 | entry `anim_frame` not in {0, 1 for +1 setters, frame_begin, continuation frame}; `anim_frame` step ≠ `anim_speed` outside hitlag; an animation-end exit earlier than the nominal tick | `anim_frame`, `anim_speed`, `status_total_tics`, `hitlag_tics` | yes | `entry_frame_unexpected`, `anim_clock_skew`, `status_shorter_than_nominal` |
| S3 | a B-tap rise in 228 while the charge (tracked from flag2's frame and landings) is spent | status, `button_tap`, `air_velocity_y`, `anim_frame`, ga | yes (charge itself not recorded) | `special_limit_rearm_unexpected`; rises and re-arms counted |
| S4 | aerial landing status vs the rule from `motion_flag1`, `tics_since_last_z`, `air_velocity_y` | those, status, ga | yes | `landing_branch_mismatch`; branches counted (incl. on a moving line) |
| S5 | FallSpecial → Wait on landing | status, ga | yes | `fallspecial_landing_lag_skipped` |
| S6 | break with no hitlag while only a body hitbox could hit; hitlag after a weapon-only break; a break while frozen | target mask, `attack_active`, weapons, `hitlag_tics` | yes (hitter attribution approximate) | `break_hitlag_mismatch`, `break_during_hitlag`; `break:hitlag=N` counted |
| S7 | entry into a stale-flag status with `motion_flag1 ≠ 0` before its script sets it | `motion_flag1`, status, `anim_frame` | yes | `stale_flag_at_entry` |
| S8 | 3+ ticks with the ceiling bit, `vel_y > 0`, y constant; StopCeil entries | `mask_curr`, `air_velocity_y`, y, status | yes | `ceiling_velocity_kept`; `ceiling:stopceil` counted |
| S9, S11, S12, S14 | ordinary mechanics | status, input | yes | counted through transitions and chains |
| S10 | `jumps_used` lower while airborne on both ticks; above `jumps_max` | `jumps_used`, ga | yes | `jumps_restored_in_air`, `jumps_over_max` |
| S13 | landing on the line just dropped through without upward motion | floor ids, status, `vel_y` | yes | not yet (next version) |
| CLK | `time_passed ≠ consumed_tick` before completion, or ≠ the completion tick after | `time_passed`, `consumed_tick`, `targets_remaining` | yes | `timer_tick_mismatch` (evidence has the displayed time) |

Every event carries `evidence.input` (stick, tap, hold, and `square_gate_corner` when the stick is a (±80, ±80) diagonal)
and the two status names.

### 5.2 What the traces cannot show, and where to read it without changing a tick

Missing today: motion flags 0, 2 and 3; `is_expend_tornado`; the per-status entry details (`frame_begin`, the setter); the
TransN rotation; the hitbox records; which process changed the status.

A read-only addition next to `rlGameFillInput` (`src/sc/sc1pmode/sc1pbonusstage.c:1174-1235`, PORT-only, env-gated like
`SSB64_RL_INPUT`). It would be a new block, for example `btt_state_v1`, so `btt_input_state_v1` stays byte-identical.
Every field below is read after the update and written nowhere in the game:

- `fp->motion_vars.flags.flag0`, `flag2`, `flag3` (flag1 is already recorded);
- `fp->passive_vars.mario.is_expend_tornado`;
- `fp->status_vars` as raw words: 8 u32 cover KneeBend's force/frame/short hop, FallSpecial's landing flags, landing
  `is_allow_interrupt`, escape and guard vars;
- `fp->proc_status != NULL`, i.e. an exit hook pending (S7);
- `fp->joints[nFTPartsJointTransN]->rotate.vec.f.z` (D1, S5);
- `fp->physics.vel_ground.x` and `fp->lr` (already `facing_direction`);
- `fp->coll_data.ignore_line_id` (S13);
- `fp->attack_damage` before `ftMainProcParams` would need a capture inside the tick. Instead, the hitlag value plus the
  `attack_colls[i].damage` of active slots (read after the update) give the damage that set it;
- a per-update **status-change log**: a ring of `(old, new, setter call site)` filled by `ftMainSetStatus` itself. This one
  is the only addition that writes. It writes a port-side ring buffer and no game state. It is the only way to see S1
  chains directly. It needs a PORT-only line in decomp code, so it is optional, and the chain counts above recover most
  of it.

About 20 words per tick, sent in the transport reply, not in `ssb64.log`.

### 5.3 Event format

Unchanged: `btt_glitch_event_v1` (`GLITCH_CANDIDATES.md` §3.3). New `kind` values are `status_transition_unlisted`,
`entry_frame_unexpected`, `anim_clock_skew`, `status_shorter_than_nominal`, `special_limit_rearm_unexpected`,
`landing_branch_mismatch`, `fallspecial_landing_lag_skipped`, `break_hitlag_mismatch`, `break_during_hitlag`,
`stale_flag_at_entry`, `ceiling_velocity_kept`, `jumps_restored_in_air`, `jumps_over_max` and `timer_tick_mismatch`.

- `mechanisms` lists the S ids of this file (`CLK` for the clock).
- `detector` is `{"name": "tools/glitch/states/state_detect.py", "version": 1}`.
- `evidence` additionally has `status_names` and `input`.

As before, events never gate, rank, reward or select anything. One becomes a finding only after a tick-0 replay
reproduces it.

## 6. The tools (`tools/glitch/states/`)

- **`mario_states.py extract`** (`decomp_states.py`): reads the descriptors, enums, Mario's motion table (PORT branch of
  `src/ft/ftdata.c`), the motion scripts, the animations, the attributes and the C bodies (section 1). It writes:
  - `logs/glitch/states/mario_states.json` (`btt_state_table_v1`):
    - per status: motion, animation lengths, script events and hitbox windows;
    - every setter, with `frame_begin`, anim speed, `+1`, continuation, fighter guard, exit hooks, fields written,
      implied kinetics and wiped script flags;
    - exits per proc with the call chain; window comparisons with file:line; inputs read; stale-flag candidates;
      PORT-only lines in the procs; nominal end tick; BTT reachability with an example path;
  - `logs/glitch/states/mario_states.md`, the readable table.

  It exits 1 if any parsing problem is found. Here: 229 statuses, 82 reachable, 0 problems. It runs in about 21 s.
- **`mario_states.py detect`**, or **`tools/glitch/glitch.py detect --states TABLE|decomp`** to run both detectors in one
  pass: section 5.1 over traces, writing JSONL plus a summary of counts. `detect.py` gained the extra per-tick fields, a
  `detector` override in `emit` and the `state_table` hook. Its 36 tests still pass.
- **Heuristics**, named in the JSON:
  - the call graph uses identifier references (no types), depth 7;
  - a status set through a variable takes every status constant of the setter (and of helpers that return one);
  - relative sets (`fp->status_id + k`) are resolved for the aerial → landing case;
  - the animation end is the last non-NULL joint stream. For every reachable Mario animation that equals the longest
    stream [measured here], so the choice does not matter here.
- **Tested here** (`python -I tools/glitch/states/test_states.py`: 35 tests, all pass, about 22 s, most of it the
  real-decomp class):
  - the preprocessor; the macro word counts;
  - motion offsets across a data array, and the mismatch report;
  - script timelines with async waits, loops and goto, and the hitbox windows;
  - AObjEvent16 lengths, loops and bit-15 payloads;
  - descriptors; the call graph with param setters and fighter guards;
  - one synthetic trace per signal, a clean trace with no event, a trace without the input block;
  - the `detect.py` hook; both CLIs end to end;
  - the displayed clock;
  - 10 checks against the real decomp: the tornado and SJP script frames, the fireball frame 16, the aerial windows, the
    squat edges, the dash-roll stale flag and its exit hook, no bit-15 or event32 animation on the reachable path,
    reachability, 0 problems.
- **Not tested** (needs your machine):
  - real lab traces: field names come from `rlGameFillEntity`/`rlGameFillInput` and the inventory, but no real file was
    read here;
  - the thresholds against real data;
  - whether `button_tap` in the input block is the post-latch value the interrupts saw. It is read after the update, so a
    status set later in the tick shows the same taps [inferred];
  - the extractor on Windows paths;
  - anything in the game itself: S3's rise numbers, S7's facing flip and S8's hover are read in code, not observed.

## 7. What to run locally

From the checkout root (Git Bash), with the decomp submodule checked out. Nothing starts the game. Outputs land in the
Git-ignored `logs/glitch/`.

```bash
git fetch origin cloud/2026-11-05-states
```

```bash
git worktree add ../BattleShip-states origin/cloud/2026-11-05-states
```

```bash
cd ../BattleShip-states && git submodule update --init decomp
```

1. Tests. Expect `Ran 35 tests ... OK`, then `Ran 36 tests ... OK (skipped=1)` (the torch C-decoder test is skipped
   without the torch submodule; the yaml `FAIL` lines it prints are the expected refusals of the synthetic ROM).

   ```bash
   python -I tools/glitch/states/test_states.py
   ```

   ```bash
   python -I tools/glitch/test_glitch.py
   ```

2. The static table. Expect `229 statuses, 82 reachable in BTT, 3281 edges, 0 problems` and exit code 0. Open
   `logs/glitch/states/mario_states.md`. A non-zero problem count means a decomp layout this parser does not know: send me
   the output.

   ```bash
   python -I tools/glitch/states/mario_states.py extract
   ```

3. The state signals over the most varied traces (the splice probe). Then read
   `logs/glitch/states/state_events_splice.summary.json`.

   ```bash
   python -I tools/glitch/states/mario_states.py detect --table logs/glitch/states/mario_states.json --trace-dir /c/BattleShip_lab/splice_probe_2026-10-14/run/traces --out logs/glitch/states/state_events_splice.jsonl
   ```

   Expected:
   - `counts` full of `transition:*`, `chain:KneeBend>JumpF>…` or `chain:…>Fall>…`, `entry:+1`, `landing:*`,
     `break:hitlag=N` and `jumps:*` keys;
   - `completion_tick` / `completion_time_passed` equal to the recorded pair minus one for every clear (for example 1,244
     and `00:20.73` on the 1,245 clear if it is in the folder);
   - **zero** `timer_tick_mismatch`, `jumps_restored_in_air`, `jumps_over_max` and `landing_branch_mismatch`. Any of those
     is either a real finding or a field I read wrong: send me 2-3 events.

   Expected noise: `status_transition_unlisted` (the call graph is heuristic) and `break_hitlag_mismatch` (hitter
   attribution is approximate). Send their counts and a few examples so I can tighten the table or the rule.
4. The same over run 2's clears, through the combined detector:

   ```bash
   python -I tools/glitch/glitch.py detect --states logs/glitch/states/mario_states.json --trace-dir /c/BattleShip_lab/crossing_2026-10-15_run2/run/traces --out logs/glitch/events_run2_states.jsonl
   ```

   Expect the collision events as before, plus state events with `"detector": {"name": "tools/glitch/states/state_detect.py"…`.
   On the 1,245 clear: the count of `break:hitlag=*` keys tells how many targets were broken by Mario's body and how
   much freeze each cost.
5. To confirm S7 by hand (optional): search the summaries for `stale_flag_at_entry`. Each one is an EscapeF/B entered with
   flag1 set. In its trace, `observation.facing_direction` should flip on the next tick and again about 19 ticks later.

## Appendix: session record

- **Read**:
  - `GLITCH_CANDIDATES.md`, `tools/glitch/*`;
  - `REVIEW_2026-11-03.md` (from `origin/cloud/2026-11-03`, with `git show`);
  - in the decomp: `src/ft/ftmain.c` (input, process order, `ftMainSetStatus`, motion events, physics/map, params), the
    statuses cited above in `src/ft/ftcommon/`, all of `src/ft/ftchar/ftmario/`, `src/ft/ftanim.c`, `src/ft/ftphysics.c`,
    `src/mp/mpcommon.c`, `src/it/itprocess.c`, `src/it/itground/ittarget.c`, the BTT timer and scene code in
    `src/sc/sc1pmode/sc1pbonusstage.c` and `src/if/ifcommon.c`, `src/sys/objman.c`, `src/sys/scheduler.c`, `src/sys/objanim.c`,
    and the relocData files 202, 203 and Mario's animations;
  - in the port: `port/gameloop.cpp`, `port/rl/rl_step.cpp`, `port/fighter_registry.cpp`, `port/enhancements/TapJump.cpp`.
- **Initialised in the cloud checkout only**: the `decomp` submodule at its pinned commit; its pointer is unchanged.
- **Not touched**: `rl/`, `port/`, `decomp/` sources, `tools/frs/`, the explorer, `main`.
- **Added**: this file, `tools/glitch/states/` (`decomp_states.py`, `state_detect.py`, `mario_states.py`,
  `test_states.py`, `README.md`).
- **Changed**:
  - `tools/glitch/detect.py`: extra per-tick fields, `emit(detector=…)`, the `state_table` / `only_states` parameters and
    the hook;
  - `tools/glitch/glitch.py`: `detect --states`;
  - `tools/glitch/README.md`: the new directory.
- **Checks**:
  - `python -I tools/glitch/states/test_states.py` → 35 tests OK;
  - `python -I tools/glitch/test_glitch.py` → 36 tests OK (1 skipped: no torch submodule here);
  - `python -I tools/glitch/states/mario_states.py extract` → 229 statuses, 82 reachable, 3281 edges, 0 problems;
  - `git diff --check` clean.
