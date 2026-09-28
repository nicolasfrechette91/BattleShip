# RL M7q: `btt_input_state_v1`, `btt_action_class_table_v2` and `btt_policy_obs_v4_input` — implementation and bounded validation

Status (2026-09-28): **implemented; the bounded implementation validation of the proposal (V1–V10) is done and
reported below; nothing trained, no campaign, pilot or evaluation launched; nothing committed, pushed or branched.**
The selected training configuration is unchanged: `btt_policy_obs_v3_entities` + `btt_reward_v2` + Track 1; the
schema defaults stay v1 / v1; v4 is opt-in through `[contracts].observation = "btt_policy_obs_v4_input"` only.
Specification: [`rl_observation_v4_proposal_2026-09-28.md`](rl_observation_v4_proposal_2026-09-28.md) (revision 3);
evidence: [`rl_mechanics_observation_audit_2026-09-28.md`](rl_mechanics_observation_audit_2026-09-28.md).

Identity at the end of this step:

| item | value |
| --- | --- |
| parent HEAD | `ee96fe2` (clean before this step; every change below is uncommitted) |
| submodules | `decomp 3834e227` (rl-main; one PORT-only working-tree edit, §1.1), `libultraship 805f1950`, `torch 3aa9c97` unchanged |
| executable before / after | `748dbad9…` (M7n) / **`30a3913b32c44353…`** (`build-us/Release/BattleShip.exe`, `cmake --build build-us --config Release`, exit 0) |
| v4 contract digest | `c3d461dee0997730575a485c740523b66bc1ebc0578b9e4e127a8a5774882623` (flat 626) |
| v3 contract digest | `4ddc2933…` unchanged (flat 606) |
| action-class table v2 | `btt_action_class_table_v2`, sha256 `070d6b8f00d1ef9e…` (`rl/data/m7n_action_classes_v2.json`); v1 `97db1152…` unchanged |

## 1. What was built

### 1.1 Native: opt-in, read-only diagnostic `btt_input_state_v1` (`SSB64_RL_INPUT=1`)

Same pattern as M7f / M7g / M7n; a **separate object**, so `btt_entity_v1` and its reference captures are untouched:
- `port/rl/rl.h`: `RLInputDiag` (stick, folded `button_hold`, `button_tap`, `button_release`, the four tap / hold
  counters, `tics_since_last_z`, `anim_frame`, `anim_speed`, `motion_flag1`, plus schema / tick / guards),
  `rlInputIsEnabled`, `rlGameFillInput`, `rlStepGetLastInput`, `rlStepGetLatestObservationInput`,
  `rlStepOnObservationDiag3`.
- `decomp/src/sc/sc1pmode/sc1pbonusstage.c` (inside the existing `#ifdef PORT` block, after `rlGameFillEntity`):
  `rlGameFillInput()` reads the typed `FTStruct` / `GObj` / `DObj` fields behind the same guards; 70 added lines, all
  PORT-only. No other decomp file changed.
- `port/rl/rl_input.{h,cpp}` (new): JSON rendering (`"contract": "btt_input_state_v1"`).
- `rl_boot.cpp`: the flag (requires effective stepping, like the entity one; independent of it).
  `rl_observation.cpp`: a new outermost branch fills the input snapshot with whichever other diagnostics are on and
  hands everything over in one locked call; every earlier branch is untouched when the flag is off.
  `rl_step.cpp`: Latest / Result / Last latches; `rlStepOnObservationDiag2` now forwards to `Diag3` with a null input.
  `rl_transport.cpp`: `"input_diag": true` in status, `"input"` in observe / step replies, additive.

### 1.2 Python

| file | role |
| --- | --- |
| `rl/m7q_input.py` | strict parser of `btt_input_state_v1`, typed snapshot, invariants (`check_snapshot`), the fold / edge / tap-counter helper rules |
| `rl/m7q_status_table.py`, `rl/data/m7n_action_classes_v2.json` | `btt_action_class_table_v2`: v1's derivation with `classify_v2` (FallSpecial → `helpless`, StopCeil → `air_lock`, LandingLight / Heavy → `landing_free`, LandingAir* / LandingAirNull / LandingFallSpecial → `landing_lag`); `LandingFallSpecial` recorded `character_dependent`; `diff` command shows exactly the 11 changed common ids and no character-range change |
| `rl/m7q_obs.py` | `btt_policy_obs_v4_input`: builder (the v3 builder plus the 17 appended agent fields and the v2 class one-hot; agent indices 0–27 and the four other blocks are the v3 builder's own output), `EntityObsV4Wrapper`, contract / digest, `m7q_contracts`, `build_worker_env_v4`, `M7qWorkerFactory` |
| `rl/m7q_policy.py` | network identity `btt_policy_net_v4_multiinput_mlp64` (the v3 network with input width 626), checkpoint refusal |
| `rl/experiment_config.py`, `rl/m7_trainer.py`, `rl/m7_evaluation.py`, `rl/m7g_k_tests.py` | opt-in hooks exactly as the geo4 variant added them (v1 / v2 / v3 / geo4 branches untouched); `PRESCALED_OBSERVATIONS` groups the three fixed-scaled contracts for the normalisation / network checks; `m7q` added to the Phase K profile-scan exclusion |
| `rl/configs/m7q/m7q_pilot_s0.toml` | a v4 profile for the configuration tests only (never launched) |
| `rl/m7q_equivalence.py` | capture variants `off / entity_all / input / input_all`, comparison ignoring only the additive objects, and the **action oracle** (§2.3) |
| `rl/m7q_tests.py` | 8 unit + 2 game cases (§2) |
| `docs/rl_observation_v4_m7q.schema.json` | the machine-readable v4 contract (`python rl/m7q_obs.py schema`) |

Encodings are those of the specification's field table (rev 3): stick / 80; seven hold bits of the folded word; 5-level
taps (1 → 1.0, 2 → 0.75, 3 → 0.5, 4..253 → 0.25, 254 → 0, 0 → 0 + anomaly); `z_age = min(t, 10) / 10`, `z_out = t > 10`;
`anim_frame` clip 0..240 / 60; `anim_speed` clip 0..2 / 2; `aerial_lag_armed` = flag1 ≠ 0 only in the five aerial-attack
statuses (looked up by enumerator name, ids 209–213); `contact_edge` = mask bit 0x8000. Full native values stay in the
diagnostic. Not added: ledge fields, tornado fields, any action mask, auto Z-cancel, reward changes, route content.

## 2. Bounded validation (the proposal's V1–V10)

Records: `runs/m7q/_equiv/{off,entity_all,input,input_all,input_all_r2}` (12 traces each: the TAS in three host
modes, the eight pinned artifacts, the native 468-row replay), comparisons under `runs/m7q/_equiv/cmp`, tests under
`runs/m7q/_tests`, the non-PORT views under `runs/m7q/_nonport`.

| id | check | result |
| --- | --- | --- |
| V1 | additive, read-only, off-flag equivalence | flags unset vs M7g `post_off`, strict: **12/12 identical**; `entity_all` vs M7n `entity_all`, strict with the entity object included: **12/12 identical**; `input` alone vs `post_off` ignoring only the `input` object and status key: **12/12**; `input_all` vs M7n `entity_all` ignoring only the input object (entity strict): **12/12**; repeat capture `input_all_r2` vs `input_all`, strict: **12/12** (deterministic); native 468-row replay under every flag set: exit 0, `COMPLETE input_tick=447 time_passed=446`, checksum `0x93E9EFB4`; no leftover process; user configuration byte-identical |
| V2 | non-PORT preservation | `rl/m7f_nonport_view.py --rev HEAD` on `sc1pbonusstage.c`: non-PORT view identical (sha `98bbf64d…`, 1,281 lines, the M7n value); MSVC `cl /EP /TC` with PORT undefined at HEAD vs working tree: 18,124 non-blank lines, byte-identical apart from 70 empty lines the preprocessor emits for the skipped block (`runs/m7q/_nonport/cl`); `git diff --check` clean in both repositories; `rl.h` still C-compatible |
| V3 | tick-0 and post-action timing | every capture's reset observe: `input_tick 0`, `valid 1`, stick 0 / 0, `button_hold 0`, taps 254 / 254, `anim_speed 1.0`, `motion_flag1 0`, status Wait with `status_total_tics 0`, **`anim_frame 11.0`**: the specification's earlier expectation of 0 was wrong and is corrected (rev 3, rows 2.1 / 41 / V3), the native value is untouched. Source: the fighter is created with player control locked (`ftmanager.c:1080-1085` → `ftParamLockPlayerControl`, `ftparam.c:228-240`: word and stick zeroed, tap counters 254, `is_control_disable = TRUE`) and unlocked by the GO signal (`ifcommon.c:2211`); while locked the input block and `status_total_tics` are skipped (`ftmain.c:1370-1373`) but the animation keeps playing (`ftmain.c:1533`), so at tick 0 Wait is 11 frames in while its status counter reads 0; `tics_since_last_z` is outside the lock and reads 61 (recorded, as directed; not required). The builder and tests never assumed 0 (the synthetic builder cases use 0 as an arbitrary input; `game_wrapper_vs_raw` asserts only the observe tick); `step(0)` replies carry `input_tick 1` and the folded word of action 0; the wrapper's first step consumes tick 0 (game cases); cold-start and standby-promoted episodes give the identical v4 chain (`debe6d23…`) which also equals the M5-stack wrapper chain of the same artifact |
| V4 | edge / tap oracle | `rl/m7q_equivalence.py validate` on `input_all` + `input_all_r2`: **57,720 oracle ticks, 0 problems**; from the recorded actions alone the oracle reproduces `button_hold` (5,138 R presses folded), `button_tap` / `button_release` (286 hitlag ticks with OR-accumulation, 60 hit ticks), `stick`, both tap counters (582 forced-y and 30 forced-x resets, 258 same-tick jump transitions) and `tics_since_last_z` (5,930 Z / R edges, 162 aerial-entry resets to 65536) on every tick until a native failure |
| V5 | hitlag and animation progress | on the 286 hitlag ticks: `status_total_tics` advances on every one; `anim_frame` is frozen on the 232 ticks whose previous hitlag was ≥ 2 and advances again on the tick whose previous hitlag was 1 (the countdown precedes the animation step, `ftmain.c`); taps and releases accumulate across hitlag; **on the hit tick itself the game clears that tick's edges** (`ftmain.c:4157`), a mechanic the audit had not listed (§3) |
| V6 | Z-cancel, landing and StopCeil classification | **corrected after the first report.** The game's landing check (`ftcommonattackair.c:63`) reads the counter *after the landing tick's own input block*, so a Z / R press on the landing tick cancels even when the previous tick was outside the window, and the previous tick's counter 10 already lags on the next tick (counter + 1 = 11). The offline check now evaluates the source rule with the last airborne tick's `flag1` and the landing tick's own `tics_since_last_z`: on all 64 recorded aerial → landing transitions (22 traces; 54 free / Wait, 10 lagged) the class equals the rule (0 wrong). **Coverage limit of the records:** no recorded landing sits at the armed boundary (previous counter 9 or 10 while armed: none; the one previous-counter-10 landing, `fx_m7d_s2v2_double56` tick 166, was unarmed), and the four recorded landing-tick Z presses (`fx_m7e_s0_best6` 1718, `fx_m7e_s2_best6` 2920, `fx_random_six` 2384 / 2647, each twice with the repeat) had previous counters 1-5, inside the window, so none was decisive. The boundary is therefore established from source plus the synthetic case `unit_landing_boundary` (previous counter 8-12 and 65536, armed, with and without a Z edge on the landing tick: lag iff armed and no Z edge and previous counter ≥ 10), which also fixes the reading of the encodings: `z_age = 1.0` (previous counter ≥ 10) means the next landing lags unless Z / R is pressed on it; `z_out` separates counter 10 from 11+ and is exact only for a landing that happened on the observed tick. No `flag1` cleared on a landing tick in the records (the auto-cancel boundary is likewise unexercised). Recorded `landing_lag` durations: LandingAirNull at speed 0.5 (nair) 14, LandingAirF 30, LandingFallSpecial 25 (its 1-tick runs are edge fall-offs), no run interrupted; class v2 maps every recorded status id (no `unmapped`); **StopCeil never occurred in any existing record**, so `air_lock` is validated only synthetically (unit_builder) |
| V7 | observation shape and scaling | unit tests: Dict space, `agent (45,)`, `action_class (23,)`, flat 626 = 23 + 45 + 28 + 256 + 224 + 50, mask columns, bits exactly 0 / 1, taps on the 5-level set, `z_age` grid, forbidden button bits never set (0 anomalies over all captures), masked rows zero, finite and contained (largest absolute input 6.67), agent indices 0–27 and the four v3 blocks bit-identical to the v3 builder on the same replies, contract digest = docs schema |
| V8 | unchanged v3 / reward / replay behaviour | v3 digest `4ddc2933…` and table v1 `97db1152…` unchanged (fresh derivation identical); `python rl/m7n_tests.py unit` 10/11 (the one failure, `unit_matrix`, is the pre-existing "campaign directories must not exist yet" pre-launch check, which fails since the M7n campaign ran on 2026-09-27; the v3 contract / config / offline-trace / SB3 cases pass); `rl/m7g_obs_tests.py unit` 8/8; `rl/m7b_config_tests.py` 16/16; `rl/m7g_k_tests.py unit` 6/6 (`unit_checkpoint_identity` failed once because a capture's game process was alive during the run and passed on the isolated rerun); v3 / v2 / v1 profiles keep their flags and identity blocks; the M7n reference sets remain byte-identical under the new executable (V1) |
| V9 | resource cost | not measured (no benchmark was run; the reply grows by one 19-key object) |
| V10 | RNG prohibition | the new fill reads no RNG state, seed or counter (`unit_isolation` greps the function body); no capture, test or oracle inspects, logs, compares or hashes native RNG state |

Test runs: `runs/m7q/_tests/m7q_unit1` (6/6), `m7q_unit2` (offline traces + oracle 2/2), `m7q_unit3` (offline traces
after the duration-key fix 1/1), `m7q_unit4` (the corrected landing rule with coverage labels + `unit_landing_boundary`,
2/2), `m7q_game1` (2/2), `v8_regressions.log`.

### 2.3 What the oracle learned (source-backed corrections to the first pass)

The first validation pass reported mismatches that were all oracle-rule gaps, not native defects, each confirmed in
source before the rule was added (`rl/m7q_equivalence.py` docstring):

1. On the tick the fighter's own attack lands, `ftMainProcParams` sets hitlag and then **clears that tick's tap and
   release edges** (`ftmain.c:4157`): a press on the exact hit tick is lost, not delayed. The audit's §7.3 statement
   ("presses during hitlag are delivered when it ends") holds for the hitlag ticks, not for the hit tick itself.
2. A jump that fires in `proc_update` (KneeBend → JumpF/B, `tap_stick_y` forced 254) can be followed in the same
   tick's `proc_interrupt` by an aerial attack or special, so the observed transition is KneeBend → aerial status.
3. A fast fall set in `proc_physics` and a heavy landing in `proc_map` of the same tick leave no visible fast-fall edge.
4. The hitlag countdown precedes the animation step: the animation advances again on the tick whose previous hitlag
   was 1.
5. The Turn status re-injects an A / B press made on its first frame as a tap on a later frame
   (`ftcommonturn.c`, 2 occurrences in the records).

## 3. Remaining risks and what was not established

- `air_lock` (StopCeil) never occurs in any existing record; its class mapping is validated synthetically only.
- The Z-cancel boundary (previous counter 9 / 10 while armed; a Z press on the landing tick while armed and outside
  the window) and the auto-cancel boundary (`flag1` clearing on the landing tick) are not exercised by any existing
  record; they rest on source and the synthetic `unit_landing_boundary` case (V6). The encodings are unchanged, but
  their reading is: for the next tick's landing, `z_age = 1.0` means "lags unless Z / R is pressed now"; `z_out` is
  not that boundary. A later contract revision could re-cut `z_out` at counter ≥ 10; not done here.
- The recorded landing durations cover nair (14), fair (30) and up-B (25); bair, uair and dair lagged landings did not
  occur in the captures (their lengths rest on the animation decode of the audit).
- `anim_speed` values seen: 0.28, 0.5, 1.0 (the 0.2 dair null landing and the 2.0 wall-damage case did not occur).
- Throughput / memory of the v4 stack (V9) was not measured.
- The pre-existing `unit_matrix` failure in `rl/m7n_tests.py` is environmental (campaign directories exist); it predates
  this step and was not changed.
- `unit_checkpoint_identity` of `rl/m7g_k_tests.py` must not run while a BattleShip process is alive (it checks for
  leftover processes); it passes in isolation.
- The trainer's v4 wiring is exercised by the configuration tests and the worker-stack game case only; no training step
  was run under v4, so the learn-loop path (rollouts, checkpoints, VecNormalize without statistics) is proven by the
  identical v3 code path, not by a v4 run.
- Line endings: Git reports the port/rl files will be normalised to CRLF on the next touch (repository policy); content
  is unaffected.

Nothing here proposes or starts a training campaign.
