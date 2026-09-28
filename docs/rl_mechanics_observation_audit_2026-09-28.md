# RL mechanics and observation audit (Mario first), 2026-09-28

Status: **read-only source audit**. No native run, no training, no production edit, no campaign proposal. Observation
`btt_policy_obs_v3_entities` + `btt_reward_v2` + action `btt_s9_b8_v1` remain selected. Every claim below is tied to a
file and line in the pinned submodule `decomp 3834e227` (working tree clean) or to a tracked file of this repository.
Repository state at the audit: HEAD `ee96fe2`, clean; `libultraship 805f1950`, `torch 3aa9c97` unchanged.

Sources read in full or in the cited ranges: `decomp/src/ft/ftmain.c` (`ftMainProcUpdateInterrupt` 1351-1710,
`ftMainProcPhysicsMap` 1876-2050, motion events 160-780, `ftMainSetStatus` 4579-4960), `ftphysics.c`, `ftanimend.c`,
`ftmanager.c` 500-640, `ftcommon.h`, `ftdef.h`, `fttypes.h` (FTStruct / FTAttributes / FTPlayerInput),
`ftcommon/ftcommon{wait,walk,dash,run,runbrake,turn,turnrun,kneebend,jump,jumpaerial,fall,landing,landingair,
attackair,specialair,specialn,specialhi,speciallw,fallspecial,squat,pass,stopceil,ottotto,guard1,guard2,escape,
cliffcatchwait,cliffclimb,cliffescape,cliffattack,attack1,attackdash,attacks3,attackhi3,attacklw3,attacks4,attackhi4,
attacklw4,catch1,appeal,damagefall}.c`, `ftcommon/ftcommonstatus.h` (per-status process table), `ftchar/ftmario/*`,
`mp/mpcommon.c`, `mp/mpprocess.c` (`mpProcessCheckTestLCliffCollision`), `mp/mpdef.h`, `sys/objanim.c`
(anim_frame semantics), `relocData/202_MarioMainMotion.c` lines 1209-1310 only (the five aerial scripts, a bounded
check of the landing-lag flag), `sc/scmanager.c` (`rlGameFillObservation`), `sc1pmode/sc1pbonusstage.c` (spatial /
entity fill), `port/rl/rl.h`, `port/rl/rl_observation.cpp`, `port/enhancements/{TapJump,AutoZCancel,
FailedZCancelFlash}.cpp`, `rl/btt_learning.py`, `rl/m7n_obs.py`, `rl/m7n_status_table.py`, `rl/m7_runtime.py`,
`rl/battleship_env.py`, `docs/rl_gymnasium_m3.md`.

Conventions: a **tick** is one game update (one `ftMainProcUpdateInterrupt` + one `ftMainProcPhysicsMap`); one
Track 1 action is exactly one tick's controller word (`docs/rl_gymnasium_m3.md`, `rl/battleship_client.py`).
"Stick" values are the native signed bytes after the ±80 clamp. `lr` is the facing sign (+1 right, -1 left);
"toward" means `stick_x * lr > 0`.

---

## 1. The per-tick pipeline every fighter shares

| step | what happens | where |
| --- | --- | --- |
| 1 | `status_total_tics++`; the controller word is latched into `input.pl`: `button_tap = pressed now and not last tick`, `button_release` likewise, `button_hold = now`. **R adds A and Z to the word before edge detection** (`button_hold |= A|Z`), so an R press is an A tap + a Z tap + a Z hold. Taps and releases accumulate (OR) while `hitlag_tics != 0`. | `ftmain.c:1376-1440` |
| 2 | stick clamped to ±80; tap / hold counters: if `|x| >= 20` then `tap_stick_x = hold_stick_x = 1` on the tick of entry into the band (previous `|x| < 20`, **including a sign reversal**), `++` while staying inside; `= 254` (`FTINPUT_STICKBUFFER_TICS_MAX`) whenever `|x| < 20`. Same for y. | `ftmain.c:1441-1500`, `ftdef.h:16` |
| 3 | `tics_since_last_z++` (saturates at 65536); `= 0` if Z (or R) tapped this tick. Runs even in hitlag. | `ftmain.c:1510-1517` |
| 4 | hitlag countdown; `proc_lagend` at 0. | `ftmain.c:1518-1530` |
| 5 | if not in hitlag: animation + motion script advance (`ftMainPlayAnimEventsAll`), then `proc_update` (the move's own logic, usually "at animation end go to X"), then **`proc_interrupt` (the input-driven interrupt chain of the current status)**. | `ftmain.c:1533-1536, 1616-1628` |
| 6 | `ftMainProcPhysicsMap`: if not in hitlag `proc_physics` (velocity from stick / gravity / friction), position `+= vel_air (+ knockback)`; **if grounded on a moving line, position `+= mpCollisionGetSpeedLineID` (the carry)**; then `proc_map` (landing, ledge, walking off an edge, ceiling). | `ftmain.c:1876-1960` |
| 7 | `GamePostUpdateEvent`: the RL observation, spatial and entity snapshots are captured after all of the above. | `port/rl/rl_observation.cpp` header |

Consequences for a per-tick controller interface:

- A "press" is decided by the difference between this tick's word and the previous tick's word. The agent creates
  a press by choosing a button after at least one tick without it. A "hold" is the same button chosen again.
- A stick "tap" is decided by the 20-band: with Track 1 magnitudes (0 or ±80) every change from neutral or from the
  opposite direction is a fresh tap (`tap_stick = 1` that same tick, before `proc_interrupt` runs).
- `anim_frame` counts **up** by `anim_speed` per tick and is forced to a non-positive sentinel when the animation
  reaches its end (`sys/objanim.c:461, 699`); "move ends" is `anim_frame <= 0` (`ftanimend.c`). It is not the same
  as `status_total_tics` when `anim_speed != 1` (heavy landing 0.5, Mario's up-B landing 0.28) or when a status is
  entered mid-animation (`frame_begin`).
- `ftMainSetStatus` (every status change) resets `is_fastfall` unless `FTSTATUS_PRESERVE_FASTFALL`, clears active
  hitboxes, `is_cliff_hold`, `is_shield`, `is_special_interrupt`, `status_total_tics = 0`. It does **not** touch
  `jumps_used`, `tap_stick_*`, `tics_since_last_z`. (`ftmain.c:4579-4800`)

Port enhancement flags that change these rules (`port/enhancements/*.cpp`): `TapJumpDisabled.P1..P4`,
`CasualRules.AutoZCancel`, `CasualRules.FailedZCancelFlash` are libultraship CVars, default 0. The workers copy the
user's `build-us/Release/BattleShip.cfg.json` (`rl/m7_runtime.py:55-58, 177`), which contains none of these keys,
so training runs with **tap jump enabled, auto Z-cancel off**. Nothing in `port/rl` or `rl/` sets them.

---

## 2. Capability table (common fighter logic; Mario-specific rows marked **M**)

Columns: required state; initiating input (**P** = fresh press edge, **H** = hold, **T** = stick tap within a
buffer, **S** = stick position, held is fine); what still changes while it runs; how it ends and what is next;
code; policy exposure (**E** exposed accurately, **N** available natively but omitted, **D** derivable from
existing observation / own action history, **U** uncertain).

### 2.1 Grounded movement

| capability | state | input | adjustable during | ends / next | code | exposed |
| --- | --- | --- | --- | --- | --- | --- |
| Walk (3 tiers) | Wait, Landing (after gate), Ottotto, SquatRv | **S** `stick_x*lr >= 8`; tiers at `|x| >= 26` (middle) and `>= 62` (fast); `>= 80` in Track 1 is always fast | speed follows `|x|` every tick (`ftPhysicsSetGroundVelAbsStickRange`); tier switch keeps animation phase | `stick_x*lr < 8` → Wait; every ground interrupt (§2.5-2.7) checked first | `ftcommonwalk.c`, `ftcommon.h:22-23` | status **E**; tier only via `status_id` scalar |
| Turn (standing) | Wait / Walk / Landing | **S** `stick_x*lr <= -20` | lr flips on the first update; specials / attacks allowed from the 2nd frame; A/B pressed on frame 1 are re-injected as taps on frame 2 (`turn.button_mask`) | anim end → Wait; a fresh `|x| >= 56` tap toward the new side → Dash | `ftcommonturn.c`, `ftcommon.h:25` | status **E** (class `idle_ground`) |
| Dash | any state with the ground chain | **T** `|x| >= 56` **and** `tap_stick_x < 3` (stick entered the band at most 2 ticks ago); `tap_stick_x` is then forced to 254 | frames `<= 5` (only from a fresh dash, `flag1`): neutral-B, grab, forward smash, roll (Z tap, frames `<= 3`), shield; frames `<= 20`: neutral-B, grab, dash attack, reverse dash-dance (fresh tap the other way → Turn with dash pending), shield; jump (KneeBend, `y > 44` fresh tap or C) and taunt any time | at `attr->dash_to_run` frames with `stick_x*lr >= 50` → Run; else at anim end `vel_ground *= 0.75` → Wait; walking off the edge → Fall | `ftcommondash.c`, `ftcommon.h:27-31` | class `dash_run` **E**; frame window **N** (`anim_frame`) |
| Run | Dash at `dash_to_run` | **S** `stick_x*lr >= 50` | neutral-B, grab, dash attack, shield (4-tick slide), taunt, jump, turn-run (`<= -30`) | `stick_x*lr < 50` → RunBrake (friction ×1.25, anim end → Wait; jump / turn-run allowed in its first 4 frames) | `ftcommonrun.c`, `ftcommonrunbrake.c`, `ftcommon.h:33-35` | class **E** |
| Crouch | ground chain | **S** `stick_y <= -55` | all ground interrupts; SquatWait when the anim ends; stand up at `y >= -49` | Pass (below) | `ftcommonsquat.c`, `ftcommon.h:129` | class `crouch_pass` **E** |
| Drop through a platform | Wait / Landing / Squat / Ottotto / shield (GuardPass) | **T** `stick_y <= -53`, `tap_stick_y < 4`, floor line has `MAP_VERTEX_COLL_PASS`; from Squat: 3-tick delay (`FTCOMMON_SQUAT_PASS_WAIT`) | becomes airborne (Pass status): aerial attacks, specials, double jump, drift, fast fall | anim end → Fall | `ftcommonpass.c`, `ftcommon.h:126-131` | `one_way` line flag **E** (v3 `segment_kind[5]`); the fresh-tap condition **N** |
| Edge teeter (Ottotto) | walking / standing at a floor edge | automatic: standing within the edge snap facing the edge with `stick toward < 60` snaps to the edge (`MAP_FLAG_FLOOREDGE`) | all ground interrupts; walking off needs `stick_x*lr >= 60` | anim end → OttottoWait; moving `> 60` units from the edge → Wait; ground lost → Fall | `ftcommonottotto.c`, `mpcommon.c:24-96`, `ftcommon.h:143-144` | class `idle_ground` **E**; `FLOOREDGE` bit **N** (in `mask_curr`, dropped by v3's 4-bit mask) |
| Moving-floor carry | grounded, `floor_line_id` valid | none | position `+= line speed` each tick; **not** added to `vel_air`, so nothing is inherited at take-off | ends when airborne | `ftmain.c:1936-1943` | `carry_x/y` **E** |

### 2.2 Jumps and air control

| capability | state | input | adjustable during | ends / next | code | exposed |
| --- | --- | --- | --- | --- | --- | --- |
| Jump squat (KneeBend) | ground chain; Run/RunBrake/TurnRun with the run variant | stick: **T** `stick_y >= 53` and `tap_stick_y <= 3` (run: `y > 44`); or **P** any C button tap (`R_CBUTTONS|L_CBUTTONS|D_CBUTTONS|U_CBUTTONS`); from shield only with Z held (GuardKneeBend) | stick jump: `jump_force = max(stick_y)` over the squat; up-B and up-smash (A tap + `y >= 53`) cancel the squat; **short hop = C-button jump with the C button released within the first 3 squat frames** (stick jumps have no short hop) | after `attr->kneebend_anim_length` frames → JumpF (`stick_x*lr > -10`) or JumpB | `ftcommonkneebend.c`, `ftcommon.h:37-55` | class `jump_squat` **E**; input source / short-hop flag **N** (`status_vars.common.kneebend`) |
| Jump velocity | at the JumpF/B transition | stick jump: `vy = max(jump_force,53) * jump_height_mul + jump_height_base`, `vx = stick_x * jump_vel_x`; C jump: `vy = (17·√(1-(|x|/80)²) + 63) clamped ≤ 77` (short: `9·√… + 36`), `vx = ±|x|·jump_vel_x`; `tap_stick_y` forced to 254 | — | — | `ftcommonjump.c` | velocities **E** |
| First jump (JumpF/B) | airborne, `jumps_used = 1` | — | drift (below); fast fall; aerial attack (A), aerial special (B), double jump | anim end → Fall | `ftcommonjump.c`, status table | class `airborne` **E** |
| Aerial steering (drift) | every airborne status whose physics is `ftPhysicsApplyAirVelDrift[FastFall]`: Jump, JumpAerial, Fall, Pass, StopCeil-exit, **all five aerial attacks**, **M** SpecialAirN, tornado (own rule) | **S** `|stick_x| >= 8`: `vel_x += stick_x * air_accel`, clamped to `±air_speed_max_x`, then `air_friction` toward 0 every tick; if `|vel_x| > max` the game decelerates 1 unit/tick and ignores the stick until inside | continuous | — | `ftphysics.c:284-350` | `air_vel_x` **E**; whether the current status drifts **D** (static per-status table) |
| Fast fall | any airborne status whose physics calls `ftPhysicsCheckSetFastFall`: Jump, JumpAerial, Fall, Pass, FallSpecial, DamageFall. **Not** during aerial attacks or **M** specials (they use `ftPhysicsApplyAirVelDrift`, no fast-fall check) | **T** `stick_y <= -53`, `tap_stick_y < 4`, and `vel_y < 0` (falling) | once set, `vel_y = -tvel_fast` every tick; preserved across attacks / double-jump-less statuses that pass `PRESERVE_FASTFALL`; cleared by any other status change | landing (heavy landing if `vel_y <= -tvel_fast`) | `ftphysics.c:224-238`, `ftcommon.h:70-71` | `fastfall` **E**; the fresh-tap requirement **N** |
| Double jump (Mario and all non-Kirby/Puff) | Jump, Fall, Pass, DamageFall, FallSpecial (always refused there): `jumps_used < attr->jumps_max` (Mario 2) | same detector as the ground jump: **T** `y >= 53` with `tap_stick_y <= 3` **or P** C tap; the first jump forced `tap_stick_y = 254`, so holding up through the first jump never double-jumps: the stick must leave the 20-band and re-enter | fixed height (`80 * jump_height_mul + base) * jumpaerial_height`; `vx = stick_x * jumpaerial_vel_x` (Yoshi/Ness variants); `jumps_used++`; same interrupts as Jump | anim end → FallAerial (no jumps left) | `ftcommonjumpaerial.c:230-300, 318-330` | `jumps_left` **E** (capacity, incl. up-B setting it to 0, `ftmain.c:431-441`) |
| Multi-jump (Kirby, Jigglypuff) | `jumps_used < jumps_max` (5) | 2nd jump as above; 3rd-5th: `y >= 53` held is enough, or a C button **held**, gated by the per-jump motion flag `flag1` | decaying per-jump velocities | — | `ftcommonjumpaerial.c:270-316` | not needed for Mario; **cross-character rule** |
| Fall vs FallAerial | after any airborne move ends | — | Fall keeps the double jump; FallAerial has none (same interrupts otherwise) | landing / ledge | `ftcommonfall.c` | both class `airborne` **E**, distinguished only by `jumps_left` |
| Ceiling bonk (StopCeil) | rising into a hard ceiling with `vel_y >= 30` | — | nothing (interrupt NULL), no drift | anim end → Fall | `mpcommon.c:502-515, 706-726`, `ftcommonstopceil.c` | class `airborne` **E**; `contact_ceil` **E** |
| Jump restoration | `mpCommonSetFighterGround` (every landing, ledge catch): `jumps_used = 0`; `mpCommonSetFighterAir` (walk-off, jump, pass): `jumps_used = 1`; up-B / FallSpecial: `= jumps_max` | — | — | — | `mpcommon.c:885-905`, `ftcommonfallspecial.c:87`, `ftmain.c:431-441` | **E** via `jumps_left` and `grounded` |

### 2.3 Aerial attacks and landing (hypothesis 1 and 2)

| capability | state | input | adjustable during | ends / next | code | exposed |
| --- | --- | --- | --- | --- | --- | --- |
| Aerial attack (N/F/B/Hi/Lw) | Jump, JumpAerial, Fall, FallAerial, Pass, DamageFall; **not** FallSpecial, not during another attack or special | **P** A tap (R counts); direction from the stick: neutral if `|x| < 20 and |y| < 20`; up if angle `> 50°`; down if `< -50°`; forward if toward, else back | **drift yes** (`ftPhysicsApplyAirVelDrift`), **no new fast fall**, existing fast fall kept (`PRESERVE_FASTFALL`); **no interrupt at all** (`proc_interrupt = NULL`): no jump, special, attack or shield until the animation ends; **no ledge catch** (`ftCommonAttackAirProcMap` calls `mpCommonCheckFighterLanding` without the CLIFF flag) | anim end → Fall (`ftAnimEndSetFall`); or landing (next rows) | `ftcommonattackair.c:115-224`, `ftcommonstatus.h` rows 209-213 | class `attack_air` **E**; `attack_active` **E**; progress `status_tics` **E**; the landing-lag flag `motion_vars.flag1` **N** |
| Landing from an aerial: full lag | landing (`mpCommonCheckFighterLanding` true) while `flag1 != 0` **and** `tics_since_last_z > 10` (auto Z-cancel CVar off) | — | LandingAir<X> plays the character's landing animation; **`proc_interrupt = NULL`: nothing can interrupt it**; if the character has no landing animation for that move, LandingAirNull at speed `flag1 %` | anim end → Wait | `ftcommonattackair.c:57-87`, `ftcommonlandingair.c`, rows 214-219 | class `landing` **E**; lagged vs light landing **D** (status id scalar only) |
| **Z-cancel** (hypothesis 2, verified) | as above with `tics_since_last_z <= 10` | Z (or R) **tapped on the landing tick or on any of the 10 preceding ticks: an 11-tick inclusive window** (`FTCOMMON_ATTACKAIR_SMOOTHLANDING_TICS_MAX = 10`, counter 0 on the tap tick, `++` at the start of each later tick, the landing check runs in the same tick's `proc_map`). The counter is set to 65536 when the aerial starts (`ftcommonattackair.c:220`), after damage and after a ledge drop, so **the Z must come after the aerial began**. Z during hitlag still counts (the counter runs outside the hitlag gate). | — | if `vel_y > -20` → Wait immediately (no landing animation); else LandingLight (interruptible from animation frame 4) or LandingHeavy if fast-falling at `-tvel_fast` (played at 0.5 speed → interruptible after 8 ticks) | `ftcommonattackair.c:63`, `ftcommon.h:361`, `ftmain.c:1510-1517`, `ftcommonlanding.c` | `tics_since_last_z` **N**; **D** only with action history and the reset rules |
| Auto-cancel (no Z needed) | landing while `flag1 == 0`: **before the script's first `SetFlag1` (start-up) or after its `SetFlag1(0)`** | — | — | same as the Z-cancelled landing | `ftcommonattackair.c:63, 216` | **N** (`flag1`) |
| **M** Mario's five aerials: `flag1` window in animation frames (`WaitAsync` = absolute frame, `Wait` = relative) | nair 3-37 (value 50), fair 11-27 (1), bair 10-20 (1), uair 2-12 (20), dair 10-33 (20, loop 7 × 3) | — | — | — | `relocData/202_MarioMainMotion.c:1209-1310` (bounded check) | **N** |
| Landing lag lengths | the LandingAir animations (Mario has LandingAirF/B/U scripts; N and D not confirmed here) | — | — | — | animation data, not source text | **U** |
| Normal landing (no attack) | landing from Jump / Fall / Pass / StopCeil | — | LandingLight / Heavy: ground interrupts allowed from animation frame 4 (`FTCOMMON_LANDING_INTERRUPT_BEGIN`), crouch on exactly that frame; `vel_y > -20` → Wait directly | anim end → Wait | `mpcommon.c:676-686`, `ftcommonlanding.c:34-58, 146-150` | class `landing` **E** |

### 2.4 Specials (common dispatch) and Mario's three specials

| capability | state | input | adjustable during | ends / next | code | exposed |
| --- | --- | --- | --- | --- | --- | --- |
| Special dispatch | ground chain / air interrupt (Jump, JumpAerial, Fall, Pass, DamageFall); **not** during attacks, specials, FallSpecial, shield, ledge | **P** B tap; `stick_y >= 40` → up-B; `<= -40` → down-B; else neutral-B, which **turns around first if `stick_x*lr < -20`** (air too) | per character | per character | `ftcommonspecial{n,hi,lw}.c`, `ftcommonspecialair.c:403-458`, `ftcommon.h:372-374` | classes `special_n/hi/lw` **E** |
| **M** Fireball (SpecialN / SpecialAirN) | as above; the ground version continues as the air version when walking off an edge and vice versa | B tap | ground: friction only; air: **drift yes**, no new fast fall; **no interrupt** (`NULL`); **no ledge catch** (`mpCommonProcFighterLanding`) | anim end → Wait / Fall; the fireball spawns at `flag0` | `ftmariospecialn.c`, `ftmariostatus.h` | class **E**; projectiles **E** |
| **M** Super Jump Punch (SpecialHi / SpecialAirHi) | as above; air start: `vel_y = 0`, `vel_x /= 1.5` | B tap with `y >= 40` | **steering, not drift**: while `flag1 == 0` (rise) `|x| > 50` tilts the TransN arc by `(|x|-50)*0.6°`, and at the `flag2` event `|x| > 20` sets facing; the rise is animation velocity (TransN), so the stick cannot brake it; after `flag1` (air start only) velocity decays ×0.95/tick, then gravity 0.5 with friction and no drift; no attack / jump / special; **ledge catch only when `flag1 != 0` and `vel_y < 0`**; landing before the apex is projected (`mpCommonCheckFighterProject`), i.e. the move keeps going through a floor while rising | anim end → **FallSpecial** (helpless): `jumps_used = max`, drift at `0.6 * air_speed_max_x`, fast fall allowed, **no new jump, attack or special can start** (the only interrupt is the double-jump check, which always fails; steering, fast fall and the platform drop remain available, `ftcommonfallspecial.c:13-40`), ledge catch allowed, drop-through with `y < -44`; landing → LandingFallSpecial at anim speed 0.28 (`7/0.28 ≈ 25` ticks per the header comment), **not interruptible** (`is_allow_interrupt = FALSE`) | `ftmariospecialhi.c`, `ftmario.h:8-12`, `ftcommonfallspecial.c` | class `special_hi` **E**; **helpless FallSpecial is classified `airborne`, indistinguishable from Fall except by `jumps_left = 0` and the `status_id/256` scalar** (gap) |
| **M** Tornado (SpecialLw / SpecialAirLw) | as above; the ground version starts airborne with `vel_y = -7`, the air version with `vel_y = 15 - 22·expended` | B tap with `y <= -40`; **extra B taps** (fresh presses) during the `flag3` window add `+22` to `vel_y` (cap 40) if `is_expend_tornado` is false; the `flag2` event marks it expended until the next landing | steering `vel_x += stick_x * 0.03` (air) / `0.025` (ground), cap 17, friction after `flag1`; no interrupt; no ledge catch; no fast fall | anim end → Wait / Fall | `ftmariospeciallw.c`, `ftmario.h:14-19`, `mpcommon.c:445-460` | class **E**; `is_expend_tornado` **N**; the B-mash window (`flag3`) **N** |

### 2.5 Ground attacks and grab

| capability | state | input | adjustable during | ends / next | code | exposed |
| --- | --- | --- | --- | --- | --- | --- |
| Jab 1 / 2 (/ 3 **M** Attack13) | ground chain | **P** A tap with the stick inside the tilt / smash thresholds not met; jab 2 needs A within `attack1_followup_frames` (motion data) of jab 1 | grab in jab 1's first 2 ticks; jab follow-ups; nothing else | anim end → Wait; edge → Fall | `ftcommonattack1.c` | class `attack_ground` **E** |
| Tilts (S3 / Hi3 / Lw3) | ground chain | **P** A tap + **S** `stick toward >= 20` and `|angle| <= 50°` (S3); `y >= 20` and angle `> 50°` (Hi3); `y <= -20` and angle `< -50°` (Lw3, repeatable during its `flag1`) | no interrupt (Lw3: A tap queues a repeat) | anim end → Wait | `ftcommonattacks3.c`, `attackhi3.c`, `attacklw3.c` | **E** |
| Smashes (S4 / Hi4 / Lw4) | ground chain; S4 also from Dash frames `<= 5` and Turn | **P** A tap + **T**: S4 `|x| >= 56` with `tap_stick_x < 3`; Hi4 `y >= 53` with `tap_stick_y < 4` (also cancels KneeBend); Lw4 `y <= -53` with `tap_stick_y < 4` | no interrupt | anim end → Wait | `ftcommonattacks4.c:220`, `attackhi4.c:60`, `attacklw4.c:60`, `ftcommon.h:346-359` | **E**; the fresh-tap condition **N** |
| Dash attack | Dash frames `<= 20`, Run | **P** A tap | no interrupt | anim end → Wait | `ftcommonattackdash.c` | **E** |
| Grab (Catch) | ground chain, before every attack in the chain | **H** Z held + **P** A tap (`is_have_catch`); **an R press satisfies both**, so R on the ground = grab, not shield | — | miss → Wait | `ftcommoncatch1.c` | class `attack_ground` **E** |
| Taunt (Appeal) | ground chain | **P** L tap | no interrupt | anim end → Wait | `ftcommonappeal.c` | class `idle_ground` (name rule) **E** |

### 2.6 Shield and roll (SSB64 has no spot dodge and no air dodge: the status enum has only EscapeF/EscapeB)

| capability | state | input | adjustable during | ends / next | code | exposed |
| --- | --- | --- | --- | --- | --- | --- |
| Shield (GuardOn → Guard) | ground chain, Dash (`<= 20`, slide), Run (4-tick slide); `shield_health > 0` | **H** Z held (`button_hold`), **not** a tap; Z alone; R = grab instead (§2.5) | stick tilts the bubble; from GuardOn / Guard: roll, grab, jump (GuardKneeBend, jump input with Z held), drop-through (GuardPass); shield decays 1 health / 16 ticks | Z released → GuardOff after the current animation (release lag 8 ticks keeps the bubble); GuardOff is not interruptible, then Wait | `ftcommonguard1.c`, `ftcommonguard2.c`, `ftcommon.h:233-246` | class `shield` **E**; `shield_active` **E** |
| Roll (EscapeF/B) | GuardOn / Guard; Dash frames `<= 3` with a Z tap (forward roll) | **T** `|x| >= 56` with `tap_stick_x < 4` | no interrupt; `is_jostle_ignore`; facing flips at `flag1` | anim end → Wait (Yoshi: back to shield if Z held) | `ftcommonescape.c`, `ftcommon.h:248-249` | class `roll` **E** |

### 2.7 Ledge

| capability | state | input | adjustable during | ends / next | code | exposed |
| --- | --- | --- | --- | --- | --- | --- |
| Ledge catch | only statuses whose `proc_map` passes `MAP_PROC_TYPE_CLIFF`: Jump, JumpAerial, Fall, FallAerial, Pass, StopCeil (`mpCommonProcFighterCliffFloorCeil`), FallSpecial, DamageFall, **M** up-B descent; **never** during aerial attacks or **M** fireball / tornado; `cliffcatch_wait == 0` (30 ticks after a drop); facing the ledge (`lr` toward the edge); the `cliffcatch_coll` box sweep (previous → current position) crosses a floor line flagged `MAP_VERTEX_COLL_CLIFF` within 800 units of its edge; no other fighter holding that ledge. **No vertical-velocity condition in the shared path** (Mario's up-B adds `vel_y < 0`). | none | — | CliffCatch anim → CliffWait | `mpcommon.c:552-580`, `mpprocess.c:1031-1080`, `ftcommoncliffcatchwait.c` | `cliff_hold` **E**; ledge-capable lines **N** (vertex flag 0x8000 is in the spatial line flags, v3 keeps only `PASS`); `cliffcatch_wait` **N**; `LCLIFF/RCLIFF` contact bits **N** |
| Ledge options | CliffWait | attack: **P** A or B tap; roll on: **P** Z tap; climb: **S** stick up (`angle > 50°`) or toward the stage, **but only after the stick has been neutral (`|x|,|y| < FTCOMMON_CLIFF_MOTION_STICK_RANGE_MIN`) for at least one tick since the catch** (`is_allow_interrupt`); drop: stick away or down, after the same neutral gate, sets `cliffcatch_wait = 30` and goes to Fall with the double jump available (`jumps_used = 1` from `mpCommonSetFighterAir` at the catch) | none during the climb / attack / roll animations (interrupt NULL) | quick variants below 100 % damage; timeout after 1080 ticks → DamageFall | `ftcommoncliffclimb.c:80-120`, `ftcommoncliffescape.c`, `ftcommoncliffattack.c`, `ftcommon.h:178-186` | class `cliff` **E**; the neutral gate **N** (`status_vars.common.cliffwait.is_allow_interrupt`) |

### 2.8 Hitlag and damage (for completeness; Mario's Break the Targets has no attacker)

| capability | state | input | adjustable during | ends / next | code | exposed |
| --- | --- | --- | --- | --- | --- | --- |
| Hitlag | `hitlag_tics != 0` after a hit lands | none (taps and releases accumulate and are delivered as edges when hitlag ends) | animation, `proc_update`, `proc_interrupt`, `proc_physics` all skipped; position frozen; `tics_since_last_z` keeps counting | countdown to 0 | `ftmain.c:1518-1536, 1893` | `hitlag` **E** |
| Hitstun / tumble (DamageFall) | knockback | — | DamageFall allows aerial attacks, specials and the double jump (`ftcommondamagefall.c`) | — | `ftcommondamage.c`, `ftcommondamagefall.c` | class `damage` **E** |

---

## 3. Hypotheses, as verified

1. **"Aerial attacks block another action while still allowing steering"**: true. All five `AttackAir*` statuses have
   `proc_interrupt = NULL` and `proc_physics = ftPhysicsApplyAirVelDrift`. Exceptions: no *new* fast fall (the
   drift routine has no fast-fall check; a fast fall started before the attack persists), no ledge catch during the
   attack, and the landing itself can happen at any frame.
2. **"A Z input shortly before landing reduces aerial-attack landing lag"**: true, and the window is exactly the
   landing tick plus the 10 preceding ticks (11 inclusive), from `tics_since_last_z > 10` in
   `ftcommonattackair.c:63` with the counter semantics of `ftmain.c:1510-1517`. The "11 frames" recollection is
   consistent with the source. Refinements: R counts as Z; the Z must be pressed after the aerial started (the counter
   is set to 65536 at the start of every aerial); a Z pressed during hitlag counts; the cancel only matters while the
   move's `flag1` is set (Mario: nair frames 3-37, fair 11-27, bair 10-20, uair 2-12, dair 10-33); landing outside that
   window is lag-free without Z; the cancel never applies to Mario's up-B landing (`LandingFallSpecial`, fixed
   uninterruptible lag) nor to the fireball / tornado landings (they continue as ground statuses).
3. Preserved corrections: `jumps_used` is a capacity counter (`mpCommonSetFighterGround` → 0,
   `mpCommonSetFighterAir` → 1, `ftCommonJumpAerialSetStatus` → `++`, up-B / `FallSpecial` → `jumps_max`); C-up
   and C-left are in the Track 1 table; a C tap edge is a valid jump input on the ground and in the air.

---

## 4. What the agent receives today

**Action** (`rl/btt_learning.py:115-152`): `MultiDiscrete([9, 8])`, one controller word per tick: stick ∈ {neutral,
8 directions at magnitude 80}, button ∈ {none, A, B, C-up, C-left, L, R, Z}; no combination. Consequences from §1:
a press needs a preceding tick without the button; a held Z (shield) needs Z chosen every tick; a stick tap is any
change into a new direction; a double jump by stick needs an up-less tick in between; a C-button double jump needs
a C-less tick in between; R is grab (ground) or aerial attack + Z-timer reset (air); L is taunt.

**Policy**: MLP (`btt_policy_net_v3_multiinput_mlp64`), no frame stack, no recurrence, no previous action in the
observation (`rl/m7n_policy.py`, `rl/m7_trainer.py`). The only history-like feature is the one-tick displacement
`disp_x/y`.

**Observation v3 agent block** (`rl/m7n_obs.py:69-72, 214-232`): position, displacement, air / ground velocities,
carry, facing, grounded, four contact bits (floor, ceiling, left wall, right wall), floor distance, `jumps_left`,
`status_id/256`, `status_total_tics`, hitlag, `attack_active`, `cliff_hold`, `shield_active`, `fastfall`, clock,
targets left, diamond; plus the 20-class one-hot (`rl/m7n_status_table.py:60-100`), projectiles, segments, targets.

### Gap table

| information | status | evidence and the concrete gap |
| --- | --- | --- |
| remaining jump capacity | **exposed accurately** | `jumps_left = (jumps_max - jumps_used)/jumps_max`; reflects up-B / helpless (0), ground (1), air (0.5). |
| "can a jump start this tick" | **not exposed; only partly derivable** | needs: an interrupt chain that contains the jump check (status), `jumps_used < max`, no hitlag, **and** a fresh input (`tap_stick_y <= 3` or a C tap edge). The status part is derivable from the class one-hot; the input-edge part depends on the previous action (not observed) and on `tap_stick_y`, which moves like the action history except where the game forces it to 254 (jump, dash, fast fall, pass). |
| "can an attack / special start this tick" | **derivable (coarse), status-dependent** | the chain per status is a static fact of `ftcommonstatus.h` + the per-status files; A/B need a fresh press (previous action). No native single "actionable" flag exists (`is_special_interrupt` is unrelated). |
| helpless state (FallSpecial) | **exposed only weakly** | classified `airborne` together with Fall / Jump (`m7n_status_table.py:76`); the only signals are `jumps_left = 0` (shared with FallAerial) and the raw `status_id/256` scalar. Distinct natively (`nFTCommonStatusFallSpecial`). |
| lagged vs interruptible landing | **exposed only weakly** | LandingAir* (uninterruptible), LandingFallSpecial (uninterruptible for Mario), LandingLight / Heavy (interruptible from frame 4 / 8 ticks) are one class `landing`. |
| current move progress | **partly exposed** | `status_total_tics` (cap 240) is exposed; `anim_frame` (the value every "end" and every frame window is written against), `anim_speed`, and the `flag1` landing-lag / hitbox window are not. `attack_active` covers the hitbox part. |
| previous held inputs, buffered taps | **available natively, omitted** | `input.pl.button_hold` (= this tick's word at capture time, i.e. the "previous word" for the next decision), `button_tap`, `tap_stick_x/y`, `hold_stick_x/y` are all plain FTStruct fields (`fttypes.h:1201-1207, 1577-1580`). Also derivable in Python from the agent's own action history, except for the forced-254 resets, which are only known natively. |
| Z-cancel timer | **available natively, omitted** | `tics_since_last_z` (`fttypes.h:1473`). Derivable from action history only together with the reset rules (aerial start, damage, ledge drop). |
| steering that remains effective during a lock | **derivable (static)** | per-status physics function from `ftcommonstatus.h` and `ftmariostatus.h` (drift / no drift / tornado rule / up-B tilt); not a dynamic native field. |
| landing state and contact | **partly exposed** | floor distance, fast fall, four contact bits exposed; `FLOOREDGE`, `LCLIFF`, `RCLIFF` bits are in the native `mask_curr` (`sc1pbonusstage.c` fill line "f->mask_curr = coll->mask_curr") but dropped by v3's 4-bit mask (`m7n_obs.py` `_CONTACT_BITS`); `cliffcatch_wait` not exposed; ledge-capable segments: vertex flag `0x8000` is in `RLSpatialLine.flags`, v3 keeps only `PASS` (`m7n_obs.py:180`). |
| moving-platform carry, jump restoration | **exposed accurately** | `carry_x/y`, `grounded`, `jumps_left`. |
| tornado spent flag (Mario) | **available natively, omitted** | `passive_vars.mario.is_expend_tornado`; reset by every landing (`mpcommon.c:445-460`). |
| short-hop / jump input source | **not exposed; derivable** | `status_vars.common.kneebend.{input_source,is_shorthop}`; derivable from the agent's own last actions. |
| tap-jump / auto-Z-cancel configuration | **fixed, not observed** | CVars absent from the copied config → tap jump on, auto Z-cancel off. |

---

## 5. Recommendation (one, prioritised)

**Priority 1 — an opt-in, read-only native "input state" block plus two Python table fixes, then a v4 observation
that adds the previous action.** Same pattern as M7f / M7g / M7n (flag-gated fill in the `#ifdef PORT` block,
additive JSON, native equivalence check with the flag off); no game rule is re-implemented in Python.

| item | where it belongs | why | source |
| --- | --- | --- | --- |
| `button_hold` masked to the 8 contract buttons, `tap_stick_x`, `tap_stick_y` (each as `min(v, 8)`), `tics_since_last_z` (as `min(v, 16)`) | **observation** (new entity fields) | these four numbers are exactly what the next tick's edge / tap / Z-cancel checks read; they include the forced resets the agent cannot infer; they are authoritative and cheap | `ftmain.c:1376-1517` |
| `anim_frame` and `motion_vars.flags.flag1` (0/1) | **observation** | progress against which every window in §2 is written; `flag1 != 0` is the "landing will lag unless Z" state for aerials and the phase marker for Mario's specials | `sys/objanim.c`, `ftcommonattackair.c:63` |
| split the class table: `airborne` → {`airborne`, `helpless`}; `landing` → {`landing_free`, `landing_lag`} (Python data edit of `rl/m7n_status_table.py`, new table id) | **observation** | makes "no action possible until landing" and "cannot interrupt this landing" linearly readable instead of hidden in `status_id/256` | `ftcommonfallspecial.c`, rows 214-219 |
| previous Track 1 action (one-hot 9 + 8) | **observation** (Python, no native change) | closes the press-vs-hold ambiguity for A / B / C / Z; also yields "one tick without C" bookkeeping | §1 |
| `FLOOREDGE` bit | **observation** | already on the wire; the edge-teeter snap (§2.1) is the one contact state v3 cannot see | `mpdef.h`, `mpcommon.c:24-96` |
| `LCLIFF` / `RCLIFF` bits, the `CLIFF` vertex flag, `cliffcatch_wait` | **deferred** (not in the Mario BTT v4) | the stage has no ledge-flagged line (§7.4): these fields would be constant zero; they return with the first versus-stage mode | `mpdef.h`, `mpprocess.c:1031` |
| per-status "interrupt chain" names and the physics routine | **diagnostic overlay / analysis only** | useful to read replays; a static table derived from `ftcommonstatus.h`, not something the policy should learn from a second implementation | `ftcommonstatus.h` |
| `is_expend_tornado`, the tornado `flag3` rise window | **deferred** (user decision 2026-09-28): the move stays available through the existing B input; its mechanics are documented in §2.4; no tornado-specific v4 field unless existing evidence shows it matters (§7.5) | | |
| kneebend input source / short hop | **optional** (history-derivable); expose only if a short-hop question comes up | | |
| an action-availability interface (mask) | **do not build now** | "the move cannot start" never makes the controller word invalid: the same word still steers, releases a hold, or arms the next edge (e.g. a C-less tick). If ever wanted, it must be a native query of the actual interrupt chain, not a Python rule table, and it should only ever mask *button* starts, never stick states | §1, §2 |

Ordering inside the priority: (a) native block + equivalence proof, (b) table split, (c) v4 builder with the
previous action and the ledge / edge bits, (d) the usual bounded no-training validation before any campaign is
proposed. Nothing here changes v3, reward v2, the timing / reset contracts, non-PORT code, or the native RNG.

Cross-character mappings required before any of this is claimed for another character (Mario alone establishes
nothing about them): the 11 unreviewed status class tables; `jumps_max` and the multi-jump hold rule (Kirby,
Jigglypuff); the double-jump physics variants (Yoshi, Ness, `ftcommonjumpaerial.c:66-100`); each character's
special-status process table (Mario's is `ftmariostatus.h`; others have their own ledge / landing / drift rules,
e.g. `ftcommonspecialair.c` tables, DK has no aerial down-B); the `is_have_*` attribute flags; `cliffcatch_coll`
per character; per-character passive flags like `is_expend_tornado` (Samus charge, Captain, Jigglypuff in
`mpcommon.c:445-470`); the landing-lag `flag1` windows, which are per-move script data.

---

## 6. Open questions, as directed by the user on 2026-09-28

All six were answered or decided the same day from existing records only (no game run, no training); the
evidence is in §7. Standing decisions recorded here:

1. Landing lag: determined from animation data and cross-checked against traces (§7.1). Z-cancel *timing* (§2.3,
   §3) and the resulting *lag duration* (§7.1) are kept as two separate facts.
2. Jump squat and dash-to-run: read from Mario's attribute data, cross-checked against traces (§7.2).
3. Target-hit hitlag: measured from the entity captures, direct attacks and projectile hits separated (§7.3).
4. Ledges: Break the Targets and Board the Platforms have no catchable ledge; the stage data confirms it (§7.4).
   Ledge fields are **removed from the proposed Mario BTT v4** and return with the first mode that has ledges.
5. Tornado: stays available (it is an ordinary B input); mechanics documented in §2.4; tornado-specific v4
   fields are **deferred** because no existing evidence shows the move matters on this stage (§7.5).
6. Auto Z-cancel: **stays off**; native rules preserved; Z-cancel timing remains learnable and is not a
   prerequisite for the first clear, so no reward or training intervention targets it. A casual-rules experiment,
   if ever run, needs its own explicitly named contract and must never be compared as if it used the native
   setting.

---

## 7. Evidence for the answers (existing source, data files and captures; nothing was run)

Record sets used: `runs/m7n/_equiv/entity_all` (12 traces with the entity object: the TAS in three host modes,
the eight pinned Track 1 artifacts, the native replay; 28,873 replies), the M7f / M7g / M7g_obs equivalence sets
(observation only, 26 distinct traces after de-duplication by action digest), and the M7p addendum raw-reply traces.
Data files: `decomp/src/relocData/203_MarioMain.c` (attributes), `202_MarioMainMotion.c` (motion scripts),
`518/627/628/629_FTMarioAnimLandingAir{X,F,B,U}.c` and `622/623/626_FTMarioAnimAttackAir{N,F,D}.c` (figatree
keyframe scripts). Scratch scripts (not part of the repository): a status-run / hitlag scanner over the captures
and a figatree length decoder; the decoder sums the wait opcodes per joint exactly as `ftAnimParseDObjFigatree`
does (Block / SetValBlock / SetValRateBlock / SetVal0RateBlock / SetValAfterBlock / SetTranslateInterp /
SetFlags add their payload; the non-Block twins do not; the animation ends when the last running joint ends,
`ftanim.c:180-205`).

### 7.1 Mario's aerial landing durations (separate from the Z-cancel window)

Mario's animation set has landing animations for fair, bair and uair only (`627/628/629`); there is no
`FTMarioAnimLandingAirN` or `…AirD` file, so **nair and dair land in `LandingAirNull`**, which plays the generic
7-frame landing (`518_FTMarioAnimLandingAirX`, decoded 7) at the speed given by the move's `flag1` percentage
(nair 50 %, dair 20 %; `ftcommonattackair.c:79`, scripts at `202_MarioMainMotion.c:1211, 1291`). The traces
confirm the rule twice (nair 14 = 7 / 0.5; Mario's up-B landing 25 = 7 / 0.28) and the decoder reproduces the
two lengths the traces fix (fair 30, generic 7).

| move | landing status when `flag1 != 0` and no Z | length (ticks) | source |
| --- | --- | --- | --- |
| nair | `LandingAirNull` at 0.5 | **14** | 8 trace runs, all 14; decoder 7 / 0.5 |
| fair | `LandingAirF` | **30** | 4 trace runs, all 30; decoder 30 |
| bair | `LandingAirB` | **15** | decoder 15 (no lagged bair landing in any trace) |
| uair | `LandingAirU` | **40** | decoder 40 (no lagged uair landing in any trace) |
| dair | `LandingAirNull` at 0.2 | **35** (derived, 7 / 0.2) | not observed; the same rule as nair |
| any aerial, Z within the window or `flag1 == 0` | `LandingLight` / `LandingHeavy` (or `Wait` if `vel_y > -20`) | interruptible from tick **4** / **8** (light / heavy); observed 4 (34 of 36) and 8 (10 of 13), the rest are later interrupts | `ftcommonlanding.c`, 49 trace runs |
| up-B | `LandingFallSpecial` at 0.28 | **25**, not interruptible | 79 of 82 trace runs (the 3 one-tick runs are edge fall-offs) |

Every `LandingAir*` and `LandingFallSpecial` run in the traces ended only at its animation end (no interrupt
observed, `proc_interrupt = NULL`). The traces also show the full aerial animations: nair 49, fair / bair / uair
39, dair 38 ticks in status (animation lengths 50 / 40 / 39 by the decoder; one tick less in status because the
aerial's first animation step happens on the tick it starts).

### 7.2 Jump squat and dash-to-run

`203_MarioMain.c:248-263`: `kneebend_anim_length = 3.0`, `dash_to_run = 14.0`, `jumps_max = 2` (also
`jump_height_mul 0.7`, `jump_height_base 26`, `air_accel 0.025`, `air_speed_max_x 30`, `air_friction 0.2`,
`gravity 2.4`, `tvel_base 44`, `tvel_fast 70`, `dash_speed 54`, `run_speed 44`, `walk_speed_mul 0.3`). Trace
cross-check: KneeBend lasted 3 ticks in 124 of 146 runs; the 22 shorter runs are up-B / up-smash cancels or an
aerial special started from the squat (all documented interrupts, §2.2), not a different squat length. Dash
never reached Run in any capture (15 dash runs of 1-3 ticks, all ended by a jump, grab, taunt or special), so
`dash_to_run = 14` has no trace cross-check; it is the attribute value only.

### 7.3 Hitlag on target hits

Entity captures, every decrease of `targets_remaining` classified by the fighter's hitlag on that tick and by
whether an owned weapon disappeared:

| hit source | events | fighter `hitlag_tics` at the hit | notes |
| --- | --- | --- | --- |
| fireball (owned weapon lost on the hit tick, fighter in fireball / up-B / helpless / fall / jump / taunt statuses) | 39 | **0** in all 39 | the weapon path (`ftMainUpdateAttackStatWeapon`) never writes the fighter's `hitlag_tics`; the fighter keeps moving and taking input |
| up-B punch (ground or air) | 24 | **5** (18) or **6** (6) | `ftParamGetHitLag`: `floor(damage / 3 + 5) × hitlag_mul` (US, `ftparam.c`), applied in `ftMainProcParams` (`ftmain.c:4134`) from the fighter's own attack damage |
| tornado | 4 | **5** | same formula |
| dair (the tracked replay's final hit) | 3 | **6** | same |
| fair (M7p crossing replay) | 1 | **8** | same, higher damage |
| unclassified | 1 | 0 | one target drop with no weapon lost on the same tick and no active attack (`fx_m7e_s2_final_det`, tick 105); most likely a fireball whose lifetime ended on the hit tick; not a hitlag case |

Effect on the next input, from source (§1): during those 5-8 ticks the animation, `proc_update`, `proc_interrupt`
and `proc_physics` are skipped and the position is frozen; button presses and releases made during hitlag are
OR-ed into `button_tap` / `button_release` and delivered as edges on the first tick after hitlag, so a press is
delayed, not lost; stick tap counters and `tics_since_last_z` keep running; `status_total_tics` keeps counting
(observed: 7 → 12 across a 5-tick hitlag) while `anim_frame` does not, so `status_tics` overstates animation
progress by the hitlag length after a hit. Target destruction by a projectile causes no fighter hitlag.

### 7.4 Ledges on this stage

The 20 collision lines of Mario's Break the Targets carry no `MAP_VERTEX_COLL_CLIFF` flag (`0x8000`) in the
spatial reply of every capture; lines 2 and 19 carry `PASS` (the two drop-through platforms already in v3's
`one_way`). Ledge catch is therefore impossible here regardless of status (`mpprocess.c:1031-1080` needs the
flag), which matches the user's statement that ledges are a versus-stage mechanic. Ledge fields are removed from
the Mario BTT v4 proposal (§5); the mechanics stay documented in §2.7 for later modes.

### 7.5 Tornado on this stage

Existing evidence: the tornado appears in the captures (45 runs across the ground / air statuses) and scored 4
target hits, all at hitlag 5; no clear, crossing or otherwise distinguished event in any recorded run involved
it. Its mechanics (B-tap rise up to +22 per tap, cap 40, once per airtime, steering 0.03 / tick, no interrupt,
no ledge, no fast fall) are in §2.4. Nothing in the records shows it matters for a route, so the tornado-specific
fields (`is_expend_tornado`, the `flag3` window) stay out of v4; the move itself remains available through the
existing B input with the down stick.

### 7.6 Auto Z-cancel

Configuration state unchanged: `CasualRules.AutoZCancel` is absent from `build-us/Release/BattleShip.cfg.json`,
which every worker copies, so the native 11-tick rule applies in training. No proposal changes it.
