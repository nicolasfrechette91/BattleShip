# RL M7n proposal: observation audit and `btt_policy_obs_v3_entities`

Status (2026-09-26): **proposal only.** Read-only code inspection and one bounded offline analysis (the Phase K
VecNormalize statistics). Nothing was trained, replayed, rebuilt, committed or pushed. No M7l / M7m artifact or
fingerprinted file was touched. HEAD `1373710` (M7l / M7m committed), working tree clean, submodules unchanged
(`decomp 3c7fd5d0`, `libultraship 805f1950`, `torch 3aa9c97`).

Scope set by the user: prioritise reusable stage, target and character awareness over another Mario-specific v1
curriculum. Standing constraints apply unchanged (no RNG work, non-PORT decomp untouched, native gameplay
authoritative, one action / one tick, tick-0 non-consuming reset, canonical actions as truth, Track 1
`btt_s9_b8_v1`, fixtures and TAS validation-only, rewards and observations versioned separately).

Sources read: `rl/btt_learning.py`, `rl/battleship_env.py`, `rl/m7g_obs.py`, `rl/m7g_spatial.py`, `rl/m7g_policy.py`,
`rl/m7_trainer.py`, `rl/experiment_config.py`, `port/rl/rl.h`, `port/rl/rl_observation.cpp`, `port/rl/rl_spatial.*`,
`port/rl/rl_targets.*`, `decomp/src/sc/scmanager.c` (`rlGameFillObservation`),
`decomp/src/sc/sc1pmode/sc1pbonusstage.c` (`rlGameFillSpatial`), `decomp/src/ft/fttypes.h`, `decomp/src/ft/ftdef.h`,
`decomp/src/ft/ftmain.c`, `decomp/src/mp/mptypes.h`, `decomp/src/wp/wptypes.h`, `decomp/src/wp/wpdef.h`,
`decomp/src/wp/wpmario/wpmariofireball.c`, and the M7f / M7g / Phase K / M7l / M7m documents.

## 1. Observation audit

Coordinates are native world units (x right, y up), one tick = one native update. "v1" = `btt_policy_obs_v1`
(15 float32, raw casts). "v2" = `btt_policy_obs_v2_spatial` (Dict, 525 values, `state` = v1). "diag" = read-only
opt-in native diagnostics `btt_target_identity_v1` (`SSB64_RL_TARGET_DIAG`) and `btt_spatial_v1`
(`SSB64_RL_SPATIAL`). "native" = present in game memory but in no diagnostic.

| Need | v1 | v2 | diag / native | Missing | Decision it serves |
| --- | --- | --- | --- | --- | --- |
| Remaining target identity | count only (`targets_remaining`) | `target_live` (10, binary, stable M7f ID) | `remaining_mask` (both diags) | nothing | which target an attack is for (the W2 aliasing: same ground state, three different target sets) |
| Target relative position | none | `target_geometry` (10×2, TopN-relative, 0 when broken) | live root translate (spatial) | neutral encoding of "broken" (section 2) | aim, approach, when to fire |
| Target motion | none | none (row 2 moves, no velocity) | none; target 2 = platform translate + 600 every tick (verified invariant) | per-target velocity | timing the up-B on the moving target from live state, not from time |
| Floors, ceilings, walls, one-way, ledge corners | none | `segment_geometry` (32×8: both endpoints, closest point, velocity) + `segment_kind` (32×7) | line table (observe reply), vertex flags incl. `CLIFF` | ledge-grabbable flag not exported (flag 0x8000 is parsed, not emitted) | crossing geometry, wall top, step corner; generic per stage |
| Moving-platform position / velocity | none | row 23 endpoints + `vel` = last-update speed | group translate + `gMPCollisionSpeeds` | nothing | platform phase from live state (y, vy) |
| Character position | `position_x/y` (TopN) | same | same | nothing | all |
| Character velocity | `air_velocity_x/y`, `ground_velocity_x` (self-induced only) | same | `MPCollData::vel_speed` (moving-floor carry), `pos_diff` | effective displacement (self + carry) | riding the platform, landing prediction |
| Facing | `facing_direction` | same | | nothing | direction of specials and projectiles |
| Grounded / contact | `ground_air_state` | same | `mask_curr` (floor / ceil / lwall / rwall), `floor_line_id`, `floor_dist`, carry, collision diamond | contacts and floor distance not in any policy input | wall contact, "standing on the platform", height above floor |
| Remaining jumps | `jumps_used` | same | `attr->jumps_max` native (2 for Mario, 6 for Kirby / Jigglypuff) | `jumps_max` | recovery / aerial planning; character-independent form needs the maximum |
| Action state | `fighter_status_id` as one raw integer (about 220 common ids, then per-character ids; Mario 220–228) | same, byte-identical | | categorical semantics (ordinal scalar: SpecialAirN 224, SpecialHi 225, SpecialAirHi 226 differ by 1 / std 70); character-independent class | choosing an action that is legal / useful in the current state |
| Action progress | none (only via `input_tick` / `time_passed`) | none | `status_total_tics` native (`fttypes.h`: tics in this action state; `ftmain.c` increments each update, reset to 0 on every status change), `hitlag_tics`, `is_attack_active`, `is_cliff_hold`, `is_shield`, `is_fastfall` | all | the up-B startup frames 818–822 differed only in time fields; steering during startup needs the frame |
| Active projectiles | none | none | none. Native: weapon GObjs on `gGCCommonLinks[nGCCommonLinkIDWeapon]`; `WPStruct` has `kind`, `owner_gobj`, `physics.vel_air`, `coll_data.p_translate`, `lifetime`, `attack_coll.attack_state`, `lr` | everything | the fireball that broke target 3 at tick 800 was input at 739: 61 ticks in which nothing observable distinguishes "shot in flight" from "nothing"; same for Link, Samus, Fox, Pikachu, Ness, Yoshi, Kirby projectiles |
| Time | `input_tick` and `time_passed` (both, raw) | same | | nothing | horizon awareness; one clock is enough |
| Validity / bookkeeping | `game_status`, `btt_active`, `fighter_valid` (constant 1 in play) | same | | constant inputs | none for the policy |

What v1 already contains that the diagnosis needed: position, self-velocity, facing, grounded, jumps used, a raw
status id and the clocks. What only v2 adds: geometry, the platform's live height and speed (so the phase *is* live
in v2), target identities and positions. What nothing exposes: action progress, contacts, effective displacement,
target velocity, projectiles.

Smallest coherent addition that supports the listed decisions and extends to other characters:
action-state class + progress, contacts + floor distance + carry, remaining-jump fraction, per-target velocity,
own projectiles, and a neutral encoding of absent entities. Everything else is retained from v1 / v2.

## 2. Why the existing v2 may not have helped

### 2.1 Verified (from code and the saved Phase K statistics; nothing here needed a game process)

Offline analysis: the three v2 finals' `vecnormalize.pkl` (`runs/m7g_k/m7g_s{0,1,2}_v2/final`, count 3,072,005
each) and the v1 s0 final, read with pickle only.

1. **A broken target is not "absent" after normalisation.** v2 writes `(0, 0)` for a broken target and lets
   VecNormalize standardise the row. The standardised value of raw 0 is `−mean / std`, clipped at ±10:

   | target (ID) | s0 | s1 | s2 |
   | --- | --- | --- | --- |
   | 3 (right, breaks late) | (−6.00, −0.30) | (−4.16, −0.37) | (−3.57, −0.01) |
   | 2 (moving) | (−3.75, −4.91) | (−3.00, −5.16) | (−2.53, −4.14) |
   | 7 (top centre) | (−0.82, −3.63) | (−0.33, −4.10) | (−0.12, −2.14) |
   | 6 / 8 (left, never broken) | (2.75, −6.67) / (2.75, −3.30) | (2.93, −7.37) / (2.93, −3.67) | (3.05, −5.73) / (3.05, −2.70) |

   So each break moves 2 inputs by 3–7 standard deviations to an ID-specific "phantom" value, and the same raw 0
   means different things in different runs and checkpoints. `target_live` (raw binary) does carry the mask, but
   the geometry channel contradicts it. This is a masking defect of the contract, not a bug in the code.
2. **224 of the 525 inputs are constant.** `segment_kind` depends on the static table and on the `moving` column,
   which is set whenever the platform group is present and translated; that is every live reply
   (`check_snapshot` asserts it). 43 % of the input carries no information and acts as a random bias at
   initialisation.
3. **Most geometry is Mario's position again.** The 23 static rows' endpoints (92 values) and the static targets'
   rows are `constant − TopN`; their per-element std equals the `state` position std to three decimals in all three
   runs (for example 919.939 in s0). The non-redundant content of v2 beyond v1 is the 46 closest-point coordinates,
   the platform row (height, speed), the 10 live bits and the moving target's row. That is by design (section 5 of
   `rl_observation_v2_m7g.md`), but it means v2 was mostly v1 re-expressed 35 times wider.
4. **The action state is an ordinal scalar in both contracts** (`state` is byte-identical to v1), and no contract
   has action progress. This is the representational side of the M7m finding that the startup frames were
   distinguishable only through time.
5. **Both arms trained with `ent_coef = 0`** and the same 64-unit heads; the v2 first layer had 33,600 input
   weights against 960. Not a defect, but the comparison gave the wider input no extra regularisation or capacity.

### 2.2 Plausible, not established

- The per-break input jumps (item 1) and the drifting running statistics over 3.07 M steps are consistent with
  v2 s0 leading until 921,600 and regressing afterwards, and with s1 never learning. Explained variance was
  0.89–0.96 in both arms, so the critic was not obviously broken.
- The redundancy (item 3) plus orthogonal initialisation gives every hidden unit a strong random projection of
  Mario's position at step 0; whether that slowed learning is not measurable from the saved aggregates.

### 2.3 Unknown

- Whether any of this caused gate 7. Phase K saved rollout aggregates only; per-state advantages, activations and
  the observation stream were not stored, and the causal contribution cannot be recovered offline.
- Whether the information that v2 did add (live platform phase, target identity) was ever used: the M7m offline
  probes were of v1 policies. The Phase K result therefore still says "this v2 setup gave no benefit", not
  "stage information is unnecessary".

## 3. Recommended revision: `btt_policy_obs_v3_entities`

Design rule: **every entity is an explicit, fixed-scaled, masked row; absent means all zeros; nothing in the
contract names a location, tick, period, order or route.** The v2 builder and native spatial diagnostic are reused
as they are; one new read-only native diagnostic supplies the agent extras and projectiles.

### 3.1 Fixed physical scaling (replaces VecNormalize for v3 keys)

| constant | value | applies to |
| --- | --- | --- |
| `L` | 2,000 units | every length (about one camera half-height; the stage spans −3,900..3,300 × −4,050..3,600, blast zones ±9,600) |
| `V` | 50 units / tick | every velocity (fireball launch speed 50, terminal 55; Mario's fall speeds are of that order) |
| `T` | 3,600 ticks | the episode clock (the training horizon) |
| `P` | 60 ticks | action progress and hitlag |

Rationale: raw 0 stays 0 after masking (fixes 2.1 item 1); statistics no longer live in the checkpoint, so a v3
checkpoint has the same input meaning on any character or stage; evaluation needs no frozen statistics. No clipping.
Values stay within about ±5 on this stage.

### 3.2 Keys (Gymnasium `Dict`; SB3 concatenates in sorted key order)

**`agent`** float32 (28,), all from the paired v1 fields, `btt_spatial_v1.fighter` and the new diagnostic:

| # | field | source | scaling |
| --- | --- | --- | --- |
| 0–1 | `pos_x, pos_y` | TopN (v1) | / L |
| 2–3 | `disp_x, disp_y` | TopN of this reply − TopN of the previous reply; 0 at reset | / V |
| 4–6 | `air_vel_x, air_vel_y, ground_vel_x` | v1 | / V |
| 7–8 | `carry_x, carry_y` | spatial `fighter.carry` (moving-floor carry) | / V |
| 9 | `facing` | v1 `lr` | −1, 0, 1 |
| 10 | `grounded` | v1 `ga == 0` | 0 / 1 |
| 11–14 | `contact_floor, contact_ceil, contact_lwall, contact_rwall` | spatial `fighter.mask_curr` bits | 0 / 1 |
| 15 | `floor_dist` | spatial `fighter.floor_dist`, clipped at 4 L | / L |
| 16 | `jumps_left` | `(jumps_max − jumps_used) / jumps_max` | fraction |
| 17 | `status_id` | v1, raw id | / 256 (kept lossless beside the class) |
| 18 | `status_tics` | `min(status_total_tics, 240)` | / P |
| 19 | `hitlag` | `min(hitlag_tics, 60)` | / P |
| 20 | `attack_active` | `is_attack_active` | 0 / 1 |
| 21 | `cliff_hold` | `is_cliff_hold` | 0 / 1 |
| 22 | `shield_active` | `is_shield` | 0 / 1 |
| 23 | `fastfall` | `is_fastfall` | 0 / 1 |
| 24 | `time` | `time_passed` | / T |
| 25 | `targets_left` | `targets_remaining` | / 10 |
| 26–27 | `diamond_top, diamond_width` | spatial `fighter.coll` (character size) | / L |

**`action_class`** float32 (20,), one-hot over a character-independent class table built from the decomp enums
(`ftdef.h` common range, then each character's header), checked in as a generated JSON with a digest:
`idle_ground` (Wait, Walk*, Turn*), `dash_run` (Dash, Run, RunBrake), `jump_squat` (KneeBend, GuardKneeBend),
`airborne` (JumpF/B, JumpAerialF/B, Fall, FallAerial, FallSpecial), `landing` (Landing*), `crouch_pass` (Squat*,
Pass, GuardPass, Ottotto*), `shield` (Guard*), `roll` (EscapeF/B), `damage` (Damage* through DamageFall, Passive*,
Down*), `cliff` (Cliff*), `attack_ground` (Attack11..AttackLw4, per-character Attack13 / Attack100 ids),
`attack_air` (AttackAirN..Lw), `special_n`, `special_s`, `special_hi`, `special_lw` (per-character ids, ground and
air merged; the raw id and `grounded` keep the split), `item` (Get / Throw / Swing / shoot ids), `appear_entry`
(Entry, Appear*, Rebirth*), `dead` (Dead*, Sleep), `other`. Ids not in the table map to `other` and are counted
(a test fails on an unmapped id in any replayed trace).

**`segment_geometry`** float32 (32, 8) and **`segment_kind`** float32 (32, 8): the v2 rows unchanged in meaning
(endpoints, closest point, velocity; present / floor / ceiling / wall +x / wall −x / one-way / moving), lengths / L,
velocities / V, plus one new kind column `ledge` = vertex flag `CLIFF` (0x8000, already parsed by
`m7g_spatial`). Row order = native line id then vertex pair; padding rows all zero; the builder accepts any table
with ≤ 32 segments (the pinned-Mario-table check moves to the task profile's validation, not the contract).

**`targets`** float32 (10, 5), row = stable ID (every Break the Targets stage has 10 targets):
`dx / L, dy / L, vx / V, vy / V, live`. `vx, vy` = live position of this reply − live position of the previous reply
(0 at reset, on the first live tick of a row, and on a stale reply). Broken or absent: the whole row is 0. On this
stage `v` of row 2 must equal the platform speed within float32 rounding every tick (a test, not a contract term).

**`projectiles`** float32 (4, 8), rows in weapon-link order, `present, owned, dx / L, dy / L, vx / V, vy / V,
hitbox_active, life` (remaining lifetime / 140 clipped at 1). Absent slot: all zero. More than 4 weapons sets an
anomaly flag in the native object and truncates (never observed for Mario; a test counts the maximum on the TAS and
on the M7l sweep replay).

Flat size 28 + 20 + 256 + 256 + 50 + 32 = **642**. Explicit masks: `segment_kind[:, 0]`, `targets[:, 4]`,
`projectiles[:, 0]`.

### 3.3 Moving objects and destroyed targets

- Moving platform: as v2 (live translate in the endpoints, last-update speed in `vel`); no phase, period or future
  position is exposed.
- Moving target: its row carries live position and Python-side velocity; nothing ties it to the platform.
- Destroyed target: row zeroed on the reply that reports the break (the native mask is authoritative); velocity
  history for that row is discarded, so it cannot leak back.
- Projectile that despawns: slot zeroed; slots are not compacted, so a slot index has no meaning.
- Teardown reply (`live = 0`, terminal reply of a fall): the v2 stale rule (hold the last live dynamic state,
  `info["spatial_stale"]`) is kept; the new diagnostic follows the same rule.

### 3.4 Character-independent semantics

Everything is relative to the agent's TopN or scaled by physical constants; the character enters only through
`jumps_max`, the collision diamond, the action-class table and which projectile kinds appear. Character-specific
status ids are mapped to shared classes by name pattern from each `ftXXX.h`, and the raw id is kept so nothing is
lost. What still needs separate work per character: the class table entry (a few lines from the header), the
anomaly threshold and completion clocks (M10 gate), and of course training; a Mario policy is not expected to
transfer, but a v3 checkpoint's inputs mean the same thing for Link, so transfer can be *studied* later without a
new contract.

### 3.5 Native change: one new read-only diagnostic `btt_entity_v1` (`SSB64_RL_ENTITY=1`)

Same pattern as M7f / M7g: PORT-only fill in typed decomp code (`sc1pbonusstage.c`, `#ifdef PORT`), port-side JSON
rendering (`port/rl/rl_entity.cpp`), captured in the same `GamePostUpdateEvent` callback and handed over under the
same lock as the observation, stamped with the same `input_tick`; off = byte-identical replies, logs and results.
Contents: `fighter_extra {status_total_tics, hitlag_tics, jumps_max, is_attack_active, is_cliff_hold, is_shield,
is_fastfall}` and `weapons [{kind, owned, translate xy, vel_air xy, ga, lifetime, attack_state, lr}]` walked from
`gGCCommonLinks[nGCCommonLinkIDWeapon]` (`id == nGCCommonKindWeapon`), max 4 with an overflow flag. It writes only
`*out`, calls no game function that can block, and touches no non-PORT line. `RLObservation` schema 1, both
existing diagnostics, both rewards and protocol 1 stay unchanged.

### 3.6 Minimum encoder

`MultiInputPolicy` with the default `CombinedExtractor` (flatten, 0 parameters) into the unchanged `[64, 64]` tanh
heads, exactly the Phase K network family with input width 642 instead of 525 or 15 (about 87,300 parameters against
11,538). No set encoder, attention or CNN: the slots have stable meanings (line id, target ID), so a flat MLP reads
them directly, and keeping the network family fixed keeps the comparison about the representation. A pooled
per-entity encoder is the documented next step only for a multi-stage track where slot identities vary.

### 3.7 Versioning and compatibility

- Contract id `btt_policy_obs_v3_entities`, schema 1, digest of the machine-readable description; any change of
  meaning, shape or scaling constant is a new id.
- v1 and v2 stay byte-identical and selectable; v3 is opt-in through `contracts.observation`, with the same
  cross-field rules as v2 (policy `MultiInputPolicy`, `net_arch [64, 64]`, tanh) plus `normalize_observations =
  false` required (v3 keys are pre-scaled); `SSB64_RL_SPATIAL=1` and `SSB64_RL_ENTITY=1` are derived flags.
- Fresh models only; a v1 or v2 checkpoint is refused by shape and by an explicit identity check, as v2 does today.
- Artifact labels record the v3 contract digest, the class-table digest and the executable hash; replays remain
  canonical native actions and are unaffected.

## 4. Bounded comparison: v3 versus v1, everything else matched

Main change: the observation representation. Matched: `btt_reward_v2`, `btt_s9_b8_v1`, PPO (`rl/configs/m7g`
settings verbatim: 3e-4, 5,120 / 1,024, batch 512, 10 epochs, γ 0.999, λ 0.995, `ent_coef 0`), N = 5 standby,
horizon 3,600, tick-0 starts only, no curriculum, checkpoints every 102,400, 3,072,000 policy transitions, seeds
0–2, the M7e / Phase K post-hoc evaluation (initial + 9 curve points + final; 100 stochastic + 100 deterministic;
frozen policy; `btt_eval_metrics_v1`; random baseline).

### 4.1 Initialisation

**Recommendation: fresh models in both arms; reuse the verified Phase K v1 control only after a control-identity
check on the new code fingerprint, otherwise retrain it.** The check is the M7l R1–R3 procedure: a 102,400-transition
v1 run per seed must reproduce the pinned Phase K = M7e `ckpt_000102400` digests and every episode row, and a
re-evaluation of the three historical finals must reproduce all 600 episodes. If it passes, the six historical v1 runs
(bit-exact to M7e, re-verified in M7l) are the control and the campaign trains only the three v3 runs. If it fails,
three fresh v1 runs are trained in the same campaign, interleaved with the v3 runs.

Trade-off: a fresh v3 has no warm start, so the test is "does the representation let PPO learn more from scratch in
3.07 M transitions", not "does it repair a trained policy". The rejected alternative, transplanting the Phase K v1
final's weights into v3's first layer (v1 columns copied with the VecNormalize affine folded in, new columns zero),
would make both arms start from the same trained behaviour and test the added information directly, but it inherits
v1's collapsed / low-entropy finals (s0 collapsed), re-uses 3.07 M transitions of Mario-specific training in the arm
meant to be reusable, and needs a bespoke, hard-to-validate weight surgery. From-scratch is also the M10 default.

### 4.2 No-training correctness and native invariance (all before any pilot)

1. **Native equivalence** (M7f method, `rl/m7f_validate.py` style, 32-case matrix): new executable with both new flags
   unset versus the pinned `1e7c62a0…` on the TAS in three host modes and the eight historical artifacts: every
   reply key, all 17 observation fields including `host_frame`, result JSON and native replay identical; 468-row
   checksum `0x93E9EFB4`, 10 / 446 / 447 unchanged; `SSB64_RL_TARGET_DIAG` and `SSB64_RL_SPATIAL` replies identical
   to the M7g records; with `SSB64_RL_ENTITY=1` identical except the new object. Non-PORT token view and MSVC
   `cl /EP` translation units of the edited decomp file unchanged.
2. **Builder unit tests** (extend `rl/m7g_obs_tests.py` pattern): shapes, dtypes, bounds, key order, digest
   determinism; every masked row all-zero; padding all-zero; scaling constants; `disp` = position delta and 0 at
   reset; targets' `v` = position delta and 0 on first live tick; target 2's `v` equals the platform speed within
   float32 on every live tick of the stored spatial traces; every status id in the 3,074 M7f replays, the Phase K
   traces and the M7l / M7m replays maps to a class other than `other` (counted, reported).
3. **Projectile sanity on stored replays** (new opt-in traces of existing canonical artifacts, read-only): on the
   TAS and on the M7l training sweep (`training_sweep_s1`), a projectile row appears on the tick after each fireball
   input, |v| ≤ 55 / V, life decreases by 1 / 140 per tick, at most 4 rows ever present, and a projectile row is
   present at tick 800 when target 3 breaks.
4. **SB3 wiring**: fresh model construction, forward, save / reload, evaluation with no statistics, v1 / v2
   checkpoint refusal, 11 TOML rejections extended with the v3 rules, standby promotion with both flags (a process
   booted without them must fail loudly, as v2 does).
5. **Throughput**: `game_n5_standby_bench` arms v1, v3, v3, v1; require ≥ 80 % of v1 environment throughput
   (v2 measured 85–90 %).

### 4.3 Integration pilot (capped)

One v3 run, seed 0, cap +40,960 transitions (the M7m pilot cap), N = 5 standby, with the monitor: checkpoint set
written and re-loadable, `checkpoint.json` identity (contract digest, class-table digest, executable), 0 invariant
violations, 0 stale steps outside fall teardown, leak-free, then a 5 + 5 episode evaluation smoke from tick 0 with
metrics verified. Memory gate per Phase K Addendum A: ≥ 10 GiB available commit and ≥ 4 GiB physical before launch,
stop below 1.5 GiB commit in two consecutive samples. The pilot is never used for tuning and its run is not a
campaign run.

### 4.4 Budget and runtime

| item | transitions | wall (estimate from Phase K / M7l measurements) |
| --- | --- | --- |
| native build + equivalence matrix | 0 | about 1.5 h |
| unit + wiring tests, bench | 0 | about 1 h |
| control-identity check | 3 × 102,400 | about 0.5 h |
| pilot | 40,960 | about 0.5 h |
| v3 training, 3 seeds | 3 × 3,072,000 | 3 × 45 min (v2 was 42) |
| v3 evaluation, 3 seeds | about 2,955 episodes | 3 × 43 min |
| (control retrain + eval, only if the identity check fails) | 3 × 3,072,000 | 3 × 34 + 3 × 36 min |

About 8 h if the control is reused, about 11.5 h if not; disk about 1.7 GiB per v3 run.

### 4.5 Pre-registered outcomes (rule `m7n_decision_rule_v1`, frozen before training)

Denominators as in Phase K: verified clears over the 200 final episodes per run; targets and target 2 over the 100
final stochastic tick-0 episodes per run; D = v3 − v1 mean targets per seed, paired by seed number.

| gate | condition | recorded outcome |
| --- | --- | --- |
| 0 | any integrity failure (unverified run, drift, invariant violation, unreproduced clear) | `invalid`, stop |
| 1 | a verified clear in v3 and none in v1 (or more clears in every seed) | **success** (`first_clear`) |
| 2 | no clear, but a left-region entry or a left-target break in the final stochastic episodes of ≥ 2 v3 seeds and 0 in v1 | **success** (`ceiling_broken`) |
| 3 | no clear or crossing; D ≥ +0.5 in all 3 seeds | **success** (`better_targets`) |
| 4 | D ≤ −0.5 in all 3 seeds | **failure** (`worse`) |
| 5 | v3 final mean targets not above its own initial checkpoint in ≥ 2 seeds | **failure** (`no_learning`) |
| 6 | anything else | **inconclusive** (`no_benefit`), no extension |

Supporting diagnostic, reported and never gating: T2 = final stochastic tick-0 episodes with target 2 broken,
pooled over 300 per arm (Phase K v1 control: 3). All tick-0 breaks are policy-initiated by construction; no anchored
or prefix evaluation is part of this campaign, so inherited-maneuver completion cannot enter the count. Also
reported: deterministic collapse share, falls, first-left-entry ticks, per-checkpoint curves, wall and memory.

Success is defined only by normal tick-0 evaluation. A verified clear is re-validated natively from tick 0 on a
fresh process, as in Phase K.

## 5. What this does and does not claim

- It fixes verified representational defects (absent-entity encoding, constant inputs, ordinal action state) and
  adds the state the diagnosis found missing (action progress, contacts, target motion, projectiles) in a
  character-independent form. It does not claim these caused the Phase K or M7m results; that is what the
  comparison tests.
- It hardcodes no location, tick, period, target order or route. The moving target's timing must be read from live
  height and speed.
- It bundles no new reward, action macro or curriculum. Reward v2 and Track 1 are unchanged.

## 6. Blockers and open items

- **Native work is required** (the only part not confined to `rl/`): one PORT-gated fill function in
  `sc1pbonusstage.c`, one port C++ rendering file, `rl.h` declarations, a rebuild and the equivalence matrix. It
  follows the M7f / M7g pattern exactly and is bounded, but it needs a fresh session and the full verification
  list of CLAUDE.md. No blocker was found in the decomp: every field named above exists with the stated semantics.
- The action-class table currently covers Mario only; other characters need their header mapped (a few lines each)
  before the contract is used for them. This does not affect the Mario comparison.
- `rl/experiment_config.py` currently rejects a Dict observation without normalisation; v3 needs the inverse rule.
  This is an inherited-file hook of the same kind as Phase K route A.
- Nothing else blocks. The tree is clean, M7l / M7m are committed, and no frozen artifact is involved.

## 7. Resolutions before implementation (2026-09-26, user review points 1–5)

These supersede the corresponding statements in sections 3–4 above. The implementation and validation record is
[`rl_observation_v3_m7n_implementation.md`](rl_observation_v3_m7n_implementation.md).

1. **Cross-character scope.** Fixed scaling makes feature *meanings* consistent across characters; it does not make
   a checkpoint transferable, and no transfer is claimed. The action classes are shared semantics derived from the
   decomp status enums by name (`rl/m7n_status_table.py`, table `btt_action_class_table_v1`, generated and digest-
   checked): 20 columns, the last being the explicit fallback `unmapped`. Lookup is per task character: the common
   range (ids below `nFTCommonStatusSpecialStart` = 220) is shared by every fighter; a character-specific id is looked
   up **only** in that character's own table, never through another character's names, and an id absent from the
   table maps to `unmapped` and is counted in the step info. Implemented and validated for Mario (every id seen in the
   TAS, 8 historical artifacts and 3 capture sets maps, none unmapped). The other 11 playable characters have
   derived-but-unvalidated tables (`validated: false`); onboarding one requires replaying its own traces, reviewing
   its `other` entries (for example Donkey Kong's cargo states, which the name rule leaves in `other`), its
   `jumps_max`, its collision diamond and its projectile kinds. The pinned Mario collision table is a task validation,
   not a contract term: the builder accepts any table with at most 32 segments.
2. **Representation and encoder.** Final size **606** inputs: action classes 20, agent 28, projectiles 4×7, segment
   geometry 32×8, segment kind 32×7, targets 10×5. The v2 segment rows are retained despite the redundancy noted in
   section 2 because they are the only exact representation of the crossing geometry (step corner, wall top,
   platform), they are already validated, and their closest-point columns are the non-redundant part; the constant
   `segment_kind` columns are kept for stage generality (they cost 224 zero-information inputs on this stage and
   nothing else). A `ledge` column was dropped: no line of Mario's table carries the flag on its stored first vertex,
   so it would have been another constant with misleading semantics. The encoder stays the Phase K network family
   (`CombinedExtractor` flatten, `[64, 64]` tanh heads, about 86 k parameters): with stable slot meanings a flat MLP
   reads every row directly, and keeping the family fixed keeps the comparison about the representation. The
   observations of section 2 (constant / redundant inputs, non-neutral masking) are design facts about v2, not a
   demonstrated cause of Phase K's outcome.
3. **Masking and preprocessing.** Validity columns: `segment_kind[:, 0]`, `targets[:, 4]`, `projectiles[:, 0]`; a
   row whose validity column is 0 is all zeros, and because no running normalisation is applied to v3 keys, it is
   exactly zero *at the network input* (verified: `VecNormalize(norm_obs=False)` passes observations through
   unchanged in the dummy and real-game tests; `masked_rows_are_zero` holds on every observation of every trace).
   Projectiles: only weapons owned by the player fighter; each keeps a **sticky slot** for its life, assigned in
   ascending native spawn serial (a PORT-only per-process counter that survives the shared GObj pool); a new spawn
   takes the lowest free slot; with no free slot it is dropped and counted (`v3_projectile_overflow`); the native
   object reports up to 8 weapons with an overflow anomaly bit beyond that (random play reached 4 simultaneous
   fireballs). Projectile velocity is the native `vel_air`, not an estimate, so creation and destruction cannot
   corrupt it. The agent's displacement and the targets' velocities are reply-to-reply differences (0 at reset, on a
   row's first live reply and on a stale reply). Historical v1 / v2 preprocessing is untouched (byte-identical
   contracts and digests, re-tested).
4. **Claims.** The experiment compares the complete observation package against v1. It cannot isolate geometry,
   action progress, projectiles or normalisation, and it does not test why the Phase K v2 comparison gave no benefit.
   Section 2's findings are recorded as verified properties of v2 and as motivation, not as an explanation of its
   result.
5. **Decision rule.** The exact proposed rule, with metrics, denominators, thresholds, tie handling, incomplete-run
   handling and the failure / inconclusive distinction, is `docs/rl_observation_v3_m7n_decision_rule.json`
   (`m7n_decision_rule_v1`, proposed, not frozen). Learning success is decided only by normal tick-0 evaluation of
   frozen final checkpoints (gates 1–3); target-2 metrics and every other diagnostic are listed under
   `supporting_diagnostics_never_gating`.
