# Generalization audit (2026-10-13)

## 0. Scope, method and limits

- **Checkout.** `main` at HEAD `98dd10b`. The working tree was clean at the start and at the end (`git status --porcelain --untracked-files=all` empty). Submodules:
  - `decomp` `e4f06348b` (branch `rl-main`)
  - `libultraship` `805f1950`
  - `torch` `3aa9c97`
- **Where this ran.** This was not a cloud session. It ran as a local Claude Code session (desktop app) against the PC checkout, and stayed strictly read-only:
  - no file was created, modified, staged or committed;
  - no game process, native binary, suite, preflight or launcher was started;
  - no ROM, `.o2r` or save file was read.
- **Evidence not read.** `runs/` and `logs/` exist on this PC but were deliberately not read, so the audit reflects the repository only. Anything that lives only there is marked (D).
- **What was executed.**
  - grep and static reading;
  - an AST import-closure scan;
  - sha256 of tracked files, which reproduced all three registered fingerprints;
  - the pure-stdlib `rule_digest()` functions, which reproduced the eight rule self-test digests. Those functions are the only repository code that was executed.
- **Not recomputed.** The e2e digests (that needs the suites).
- **Size scale.** S = one small new module or a few lines. M = about one preparation session. L = several preparation sessions and/or native runs.
- **Classes.**
  - (A) already parameterised, or no change needed;
  - (B) Python change;
  - (C) native PORT-only change;
  - (D) cannot be determined from code.
- **Abbreviations in the last column of the findings tables.** That column says which registered values would break **if the file were edited in place**. The recommended pattern (section 3) puts all new work in new files, which breaks none of them.

| Abbreviation | Registered value | What it covers |
|---|---|---|
| Fg3 | g3 fingerprint `15ddbb84932aa658` | sorted `rl/m9_g3_*.py` |
| Fsd1 | sd1 fingerprint `f7fadda5ec11b3dd` | `rl/m8_sd1_*.py` + `tools/m8_sd1/*` |
| Fsd2 | sd2 fingerprint `b22c0af8f833b205` | `rl/m8_sd2_*.py` + `tools/m8_sd2/*` |
| Eg3 / Esd1 / Esd2 | e2e digests `078f46c445d8adc5` / `4cadf507c1c4fbc9` / `2adc51de5cf46121` | behaviour of the code each suite imports |
| AP | approval `code` pins | sd1 76 files, sd2 90 files, g3 s1–s6 80 files each |
| RD | rule self-test digests | g3 s1 `dea9965a…`, g3 line `d9d82885…`, rd1–rd4, sd1 `8267341f…`, sd2 `d1220a8b…` |
| CD | contract digests in approvals | cell, select, claims, artifacts, g3 contract, line contract |
| EXE | executable `30a3913b…` | pinned by every approval |

## 1. Verdict

Going from Mario to another character is **mostly Python work plus one small native PORT-only change**. No save-data or unlock work is needed.

**Native side.**
- The only Mario constant on the native side is the `nFTKindMario` argument at `decomp/src/sc/scmanager.c:1072`.
- Everything downstream already works for all twelve stages: the stage is chosen as `gkind = bonus_fkind + nGRKindBonus1Start`, and targets, clear, clocks and the tick contract are all generic.
- The fix is an env var read in `port/rl/rl_boot.cpp`. That is size S, and the decomp does not need to change.
- Unlockable fighters need no unlocking: the boot writes the scene handoff directly and never enters the character-select lock check.
- Seven of the twelve stages exceed the read-only spatial diagnostic's capacities, which were sized for Mario's stage (32 lines, 4 vertices per line, 4 groups). Those stages would need a native schema bump (S–M) before obs v3 and the M8 chain digest could represent them fully.

**Python side.** The cost is in Python:
- Route discovery's claims and rules are written around Mario-stage milestones: wall top, crossing, left target.
- Its eligibility rule E6 uses Mario's rise constants and a hard-coded copy of Mario's floor table.
- Its cell resource classes assume Mario's jump count and up-B.
- The policy line's landings, budgets and rule depths are tick numbers of Mario's own route.

**Rough total, code and process only (native session time is separate):**

| Method | Size | What it needs |
|---|---|---|
| Route discovery | M–L | 2–3 preparation sessions plus a pre-launch review, then an open-ended number of native sessions until a verified clear |
| Speed discovery | S–M on top | a new sd module set reading T_rec from the new stage's own verified clear |
| Policy line (g3/g4) | L | the new route, re-derived landings, rebased rules, a re-measured tape and a fresh start; g4's warm start from Mario's s5 model is impossible |

**Constraint flags (details in area 10).**
- No use of the TAS or human recordings, and no native RNG handling, anywhere in the active M8/M9 paths.
- Stage-coordinate and census-derived constants do sit in registered rules and selection:
  - rd2/rd3 rules: `y < −2,850` and `y ≥ 1,639`;
  - E6 eligibility in every session from rd2 to sd2;
  - the sd1/sd2 identity samples;
  - M9 rule depths written as Mario-route tick literals.

  None of these is a route or waypoint sequence. None can be reused for another stage, and several fail a strict reading of "no census number in selection, claims, rules or runs".

## 2. Findings

### Area 1 — Task definition and identity

| ID | Where | What it assumes | Class | Size | If edited in place |
|---|---|---|---|---|---|
| 1.1 | `rl/experiment_config.py:132-149`, `:876-887` | `SUPPORTED_TASKS` holds only `ssb64_us_mario_btt_v1` (us, mario, btt_mario, player 0, costume 0, `targets_total` 10, native_boot text). Other combinations are rejected. `KNOWN_CHARACTERS` / `KNOWN_STAGES` already list all 12 in fkind order. | A (append a row) | S | Nothing registered: the file is in no approval or fingerprint, and `semantic_view` takes only the selected row (`:659-667`). The Mario row must stay byte-identical. `replay/replay_tests.py:328` requires `replay/replay_task.TASKS` to match exactly. |
| 1.2 | `rl/m9_contract.py:25-26`; `rl/m9_artifacts.py:32,44-45,48-55` | `TASK` and `REGISTERED_TASKS` are Mario-only. `task_block()` returns the global `C.TASK`. `validate_task` refuses unregistered ids. | B (new writer module) | S | AP (sd1, sd2, g3). `m8_sd1_tests.py:1533-1543` and `m8_sd2_tests.py:1587-1594` pin the registry to exactly `{mario}`. |
| 1.3 | `rl/m8_sd1_artifacts.py:41-50,70-72`; `rl/m8_sd2_artifacts.py:35,55` | The task block is stamped into every sd record and folded into `artifacts_digest` (approvals `:2-6`). The mechanism is generic; the value is Mario. | A (mechanism) / B (new session set) | S | Fsd1, Fsd2, CD |
| 1.4 | `rl/m9_g2_contract.py:33-34,191,205`; `rl/m9_g3_contract.py:44-45,219,233` | The task is part of `contract_sha256` / `line_contract_sha256` (g3 approvals `:13-14`). | B (new line) | S | Fg3, CD, AP-g3 |
| 1.5 | `rl/m8_rd_cells.py:36` | `FIGHTER_CHARACTER = "mario"`. rd1–rd4 records carry no task block (handoff; `replay/README.md:537-540`). | B | S | AP (sd1, sd2, g3), cell CD, Esd1, Esd2 |
| 1.6 | `rl/m7n_obs.py:98,313-320`; `rl/m7g_fixture.py:49` | `DEFAULT_CHARACTER = "mario"` is the fallback. The fixture task spells the stage `break_the_targets_mario`, not `btt_mario`. | B | S | AP-g3 (`m7n_obs`), AP-sd (`m7g_fixture`) |
| 1.7 | `replay/replay_task.py:27-31,53-74`; `replay/replay_tags.py:73-88,221-230`; `replay/replay_episode.py:51` | `TASKS` is Mario-only. The regex already accepts `us\|jp` and multi-word names. The browser never reads the top-level `task` block, so rd1–rd4 and sd1/sd2 route records resolve to "?" (`rl/m8_sd1_run.py:341-345` writes no `labels`). The `MarioBTT` tags (x < −2,100) and `RouteClaims` (wall top / crossing / left target) are stage-specific. `replay/task_overrides.json` is untracked and nothing refers to it, so its design is (D). | B | S–M | Nothing registered (replay/ is in no pin) |
| 1.8 | `rl/configs/m7_mario_us_reward_v{1,2}{,_standby}.toml`; run trees `runs/m8_rd*`, `runs/m8_rd_sd{1,2}`, `runs/m9_g3`; increments `<date>_incr_m8_rd{1..4}`, `_incr_m8_sd1`, `_incr_m8_rd_sd2`, `_incr_m9_g3_s<k>` | M8/M9 tree and increment names carry no character, so a second character would collide with Mario's names. The M7 TOML sha256 values are pinned in `m7g_k_tests.py:85-96`. | B (new names with a task segment) | S | Nothing if new names are used. `tools/m8_sd2/post_run_checks.py` expects exactly `_incr_m8_rd_sd2`. |
| 1.9 | `port/rl/rl_boot.cpp:166` | Log tag `episode=btt_mario` | C | S | EXE |
| 1.10 | `rl/m8_rd_session.py:46` (`EXE_DIR`, reused by sd1/sd2/g3); `rl/battleship_env.py:95`; `rl/battleship_process.py:21`; `rl/m7f_trace.py:40`; snapshot tools (`m8_sd1_snapshot.py:105,136`, `m8_sd2_snapshot.py:111,142`, `m9_g3_snapshot.py:133`, …); `replay/replay_game.py:61` | `build-us/Release` is hard-coded. | B (pass the executable explicitly in new code) | S | AP when the file is pinned |
| 1.11 | `rl/m7_runtime.py:71`; `rl/experiment_config.py:880-887` | `ROM_BASENAME = "baserom.us"`: the "ROM reachable" refusal would not detect a JP ROM. `game_version` must be `"us"`. Irrelevant to a US character; needed only for JP. | B | S (US) / M (JP) | AP |

### Area 2 — Getting into the stage

**How the harness gets there, in order:**
1. `port/port.cpp:1396` calls `rlConfigInit`.
2. `scManagerRunLoop` reaches the `#ifdef PORT` block at `decomp/src/sc/scmanager.c:1004-1076`.
3. `rlBootApply` runs there, after the `SSB64_START_SCENE` / `SSB64_SPGAME_*` / boot-to-CSS overrides, so it wins over all of them.
4. It writes `scene_prev = nSCKind1PBonus1Players`, `scene_curr = nSCKind1PBonusStage`, player 0, `bonus_fkind = fkind_mario`, costume 0, and latches once per process (`port/rl/rl_boot.cpp:41-43,276-306`).
5. `sc1PBonusStageInitVars` takes the practice path: `gkind = bonus_fkind + nGRKindBonus1Start` with an infinite time limit (`decomp/src/sc/sc1pmode/sc1pbonusstage.c:511-522`).

The `nGRKindBonus1*` enum order (`decomp/src/gr/grdef.h:39-52`) is the fkind order, which is also `KNOWN_CHARACTERS`. No menus are driven.

| ID | Where | What it assumes | Class | Size | If edited in place |
|---|---|---|---|---|---|
| 2.1 | `decomp/src/sc/scmanager.c:1069-1073` (inside `#ifdef PORT`) | Passes the compile-time constant `nFTKindMario`. No environment variable selects the character. `SSB64_SPGAME_FKIND` sets `fkind`, which the practice path does not read, and it is overwritten anyway. | C | S | EXE; decomp pointer |
| 2.2 | `port/rl/rl_boot.cpp:276-306` | **Recommended fix, no decomp edit:**<ul><li>read `SSB64_RL_FKIND` in `rlConfigInit`;</li><li>substitute it for `fkind_mario` in `rlBootApply` when set;</li><li>range-check 0..11, because `dSC1PBonusStageTargetDescs[gkind - nGRKindBonus1Start]` (`sc1pbonusstage.c:1242`) is indexed without a bounds check.</li></ul>When unset, the behaviour stays exactly as today. | C | S | EXE |
| 2.3 | `decomp/src/mn/mnplayers/mnplayers1pbonus.c:396-415`; `sc1pbonusstage.c:513`; `rl/battleship_process.py:238,602`; `port/port_save.cpp:38` | **Unlocks:** the only lock check (Ness, Jigglypuff, Captain Falcon, Luigi) is in the Bonus character-select screen, which the RL boot never enters, and `bonus_fkind` is used with no mask check. Every episode also gets a fresh save file (`SSB64_SAVE_PATH` in the episode directory), so it starts from default backup data. **No save-data unlocking is needed and none touches native code.** Runtime confirmation that an unlockable fighter loads cleanly from a fresh save cannot be determined here. | A / D (runtime) | — | — |
| 2.4 | `sc1pbonusstage.c:2100-2169` | After a full clear the game writes the record backup and may route to the Luigi challenger or an unlock message. This happens after the episode end; the harness exits or parks first, and saves are per episode. Whether the post-clear teardown sequence differs per character cannot be determined. | A / D | — | — |
| 2.5 | `sc1pbonusstage.c:1895-1907` | The **native `.btti` replay is armed only when `gkind == nGRKindBonus1Start`** (Mario's map; the comment cites `mario_743.btti`). The interactive stepping session is armed for any `gkind`. Learning and verification never use native file replay (`rl/battleship_process.py:83,241` strips `SSB64_BTT_INPUT`), so this matters only if `.btti` replays of other stages are ever wanted. | C (optional) | S | EXE |
| 2.6 | `port/rl/rl_transport.cpp:341-357` and the status reply | `fkind` / `gkind` are not reported, so Python cannot directly verify which fighter and stage are running. Indirect evidence today: the tick-0 line-table digest, `map_bounds` and the entity `jumps_max`. Recommended: report them only when `SSB64_RL_FKIND` is set, so Mario's replies stay byte-identical. | C | S | EXE |
| 2.7 | `docs/audit_per_character_bonus_stages_2026-04-29.md:30-40` | Port audit verdicts. CLEAN: Mario, Fox, DK, Luigi, Link, Yoshi, Captain Falcon, Pikachu, Jigglypuff. LATENT: Samus (A1, weapon `owner_gobj` NULL dereference), Kirby (C1 `specialhi` panic; C2), Ness (C3 PK Thunder double reflect, an original-game bug). | D (runtime) | — | — |
| 2.8 | `decomp/src/relocData/129_GRBonus1LinkFile2.c` (reported by the native investigation; not re-checked) | Link's Break the Targets data differs between US and JP: collision and targets 8/9. No other Break the Targets data file has a region conditional. Matters only for JP. | D | — | — |

### Area 3 — Episode semantics (all checked for character independence)

| ID | Where | What it assumes | Character-agnostic? | Class | Size | If edited in place |
|---|---|---|---|---|---|---|
| 3.1 | Native: `sc1pbonusstage.c:1291-1296` (the game halts unless exactly 10 targets spawn); `port/rl/rl.h:609` (`RL_TARGET_COUNT 10u`, compile-time cross-checked). Python: `rl/btt_learning.py:105` (comment "Mario's … ten targets"), `rl/m8_rd_cells.py:32`, `rl/m7f_targets.py:27-28`, `rl/m7n_obs.py:231`, `rl/m7_standby.py:175` | 10 targets | Yes: the game enforces 10 on all 12 stages. Only the comment is Mario-worded. | A | — | — |
| 3.2 | `rl/btt_learning.py:286-301`; `decomp/src/it/itground/ittarget.c:42-46`; `rl/m7f_targets.py:248-290` | A hit is a decrease of `targets_remaining`. Target ID = spawn order in the stage's own table (`sc1pbonusstage.c:1278-1280`). `check_trace` compares against its own tick-0 table. | Yes | A | — | — |
| 3.3 | `port/rl/rl_step.cpp:669`; `port/rl/rl_result.cpp:161-189`; `rl/battleship_env.py:417`; `rl/m8_rd_claims.py:168-180` | Clear = `btt_active && targets_remaining == 0`. The native result latches the first non-zero count as the total (`rl_result.cpp:172-179`). | Yes | A | — | — |
| 3.4 | `rl/btt_parallel.py:116-121,171-178`; copies at `rl/m8_rd_cells.py:33,157-160` (used by M9, `rl/m9_worker.py:247,301`) and `rl/btt_reward_v3.py:156-164` | There is no native failure signal (`rl_result.cpp:7-8`). Failure is `game_status == 5 ∧ btt_active ∧ targets > 0`. | The rule: yes. The teardown facts behind it (the stale `live == 0` terminal reply, `m7n_obs.py:202-207`; the 1/90/5 update sequence) were measured on Mario only (`docs/rl_parallel_training_m7.md:70-77`). | A / D | Checked by the smoke test (section 5) | — |
| 3.5 | `rl/btt_parallel.py:114`; `rl/m8_rd_cells.py:31`; `rl/m9_contract.py:29` | Horizon 3,600 ticks, Python-owned (practice has an infinite time limit). | The value is generic. Whether 3,600 is enough for a first clear elsewhere cannot be determined (Mario's first clear was 2,315). | A / D | — | AP, CD |
| 3.6 | `port/rl/rl.h:113-139,322-327`; `rl_step.cpp:651-668,698-712`; `rl_result.cpp:112-121,188`; `rl/battleship_process.py:251-284` | `completion_input_tick` / `completion_time_passed`; submit tick T, `consumed_tick == T`, `input_tick == T + 1`; activation on the first `btt_active` outside Wait/Pause. | Yes | A | — | — |
| 3.7 | `rl/btt_learning.py:112` | `DEFAULT_MAX_EPISODE_STEPS = 1800`, about four times the TAS clear (M5 only, retired). | n/a | — | — | — |
| 3.8 | `rl/battleship_env.py:354` | Comment: "Mario BTT has no RNG state". | Not established for other stages. Determinism must be shown empirically by bit-exact replay, never by RNG inspection. | D | — | — |

### Area 4 — Observations and rewards

**Selected contracts.** M9 trains on `btt_policy_obs_v3_entities` and `btt_reward_v2` (`rl/m9_contract.py:31-32`). Obs v3 is pre-scaled with fixed constants; there is no running normalisation.

| ID | Where | Constant / assumption | Origin | Class | Size | If edited in place |
|---|---|---|---|---|---|---|
| 4.1 | `rl/m7n_obs.py:50` | `LENGTH_SCALE 2000` | Mario's stage span (`docs/rl_observation_v3_proposal_m7n.md:115`) | B (new contract) | S | AP-g3, Eg3, obs CD |
| 4.2 | `rl/m7n_obs.py:51` | `VELOCITY_SCALE 50` | Mario's fireball and fall speeds | B | S | same |
| 4.3 | `rl/m7n_obs.py:54` | `STATUS_ID_SCALE 256` | Mario's ids 220–228. Kirby's ids reach 302, giving values above 1 with no clip. | B | S | same |
| 4.4 | `rl/m7n_obs.py:57` | `FLOOR_DIST_CAP 8000` (= 4 × L) | Follows from 4.1 | B | S | same |
| 4.5 | `rl/m7n_obs.py:58,80` | `PROJECTILE_LIFE_SCALE 140` ("Mario's fireball lifetime"); `PROJECTILE_SLOTS 4`. The entity diagnostic walks weapons only, so item projectiles (Link's bomb, Ness's PK Fire pillar) are invisible. | Mario | B | S–M | same |
| 4.6 | `rl/m7n_obs.py:78`; `port/rl/rl.h:717-719` | `SEGMENT_SLOTS 32` = native `RL_SPATIAL_MAX_LINES`. Seven stages exceed it (table in 9.6) and are truncated natively with an anomaly flag. | Mario's stage (20 lines) | C + B | S–M | EXE, obs CD |
| 4.7 | `rl/m7n_obs.py:180` | The CLIFF (ledge) vertex flag is dropped because Mario's stage has none (proposal `:368`). Whether other stages have ledge-flagged lines cannot be determined. | Mario's stage | B / D | S | obs CD |
| 4.8 | `rl/m9_obs.py:39`; `rl/m7n_obs.py:98`; `rl/m7n_status_table.py:55` | M9 builds its action-state classifier for `DEFAULT_CHARACTER` (Mario), not for the task's character. `VALIDATED = ("mario",)`. Unknown ids become `unmapped`, which is resource class X in M8 (never eligible). | Mario | B (validate each character's table in a new data file) | M | AP-g3 (`m9_obs`), Eg3 |
| 4.9 | `rl/m7n_obs.py:217-218` | `jumps_left = (jumps_max − jumps_used) / jumps_max`, with `jumps_max` read natively | Generic | A | — | — |
| 4.10 | `rl/m7g_obs.py:113-116`; `rl/m7g_spatial.py:44-79` | Obs v2 refuses any collision table but Mario's (`EXPECTED_LINES`, platform group 2 / line 19, moving target 2, `MAP_BOUNDS ±9600`). Retired as a policy observation, **but `EXPECTED_LINES` is live in M8's E6** (6.4). | Mario's stage | — | — | AP-sd, AP-g3 |
| 4.11 | `rl/m7p_obs_geo4.py:28-30`; `rl/m7q_obs.py`; `rl/m7q_status_table.py:53-55` | geo4 factor 4 is calibrated on Mario. Obs v4's `LandingFallSpecial` class is validated for Mario only. Neither is selected. | Mario | — | — | — |
| 4.12 | `rl/btt_rewards.py:150-151`; `rl/btt_learning.py:240-242,306-311` | **Reward v2:** +1 per target, −0.001 per tick, +10 on clear, −5 on a native failure; the horizon is a bootstrapped truncation. | Generic | A | — | — |
| 4.13 | `rl/btt_rewards.py:105-136,152,159-176`; `rl/btt_reward_v3.py`; `rl/btt_reward_t2.py` | **Reward v3 / v3_t2:** right-side target ids (0,2,3,4,5,7,9), `left_boundary_x` −2100, `wall_top_y` 3000, `under_stage_y` −2850, landing floor −1950 with x −3900..−2700, moving target 2. Not an M8/M9 reward, but `REWARD_V3` and `classify_entry` are imported by the M8/M9 claims analyser (6.6). | Mario's stage | — (do not reuse) | — | AP-sd |
| 4.14 | `rl/btt_explore_cells.py:58-63` | Generic formula using runtime map bounds; constants tuned on Mario runs. Retired. | Mario-tuned | — | — | — |
| 4.15 | `rl/run_artifacts.py:88`; `rl/experiment_config.py:263` | Position-delta anomaly threshold 300 (Mario's up-B 215.5, roll 280.6). Artifact heuristic only; not used by M8/M9 decisions. | Mario | B (if reused) | S | AP (`run_artifacts.py` is pinned) |
| 4.16 | `docs/rl_m9_g4_proposal_2026-10-13.md:231,249-254` | **g4's N1** (proposal only): −P on a fall and −P at the horizon, which becomes a terminal failure, with P = c·γ/(1−γ) = 0.999 → −1. Everything else stays v2. | The rule is generic. Its justification (p\* 0.202 / 0.213 / 0.246, the attractor) is Mario-data analysis and relies on obs v3's clock feature. Whether the attractor exists on another stage cannot be determined. | A / D | — | — |

### Area 5 — Action space

| ID | Where | What it assumes | Class | Size | If edited in place |
|---|---|---|---|---|---|
| 5.1 | `rl/btt_learning.py:117-162`; `rl/m8_rd_cells.py:61-70`; `port/rl/rl.h:227-246` | `btt_s9_b8_v1` = MultiDiscrete([9,8]), word = stick × 8 + button. Sticks: neutral plus 8 directions at ±80. Buttons: none, A, B, C-up, C-left, L, R, Z. Canonical controller words, with no move-specific mapping. **Character-agnostic as an encoding.** Whether 8 fixed directions suffice for analog-steered recoveries (Fox's Firefox, Pikachu's Quick Attack, Ness's PK Thunder) cannot be determined. | A / D | — | — |
| 5.2 | `rl/m8_rd_explore.py:22-24,60-63` | Uniform over the 72 words, holds of {1,2,4,8,16}, bursts of 120 words. The values are generic; the rationale cites Mario's flights (`docs/rl_m8_rd_proposal_2026-10-01.md:340-352`). | A | — | AP, cell CD |
| 5.3 | `rl/m8_rd_cells.py:41,172` | **Move-set assumptions in the M8 cell key:**<ul><li>A0 = `special_hi` or `helpless` (assumes up-B is the recovery that spends all jumps);</li><li>`A2 if jumps_used < 2 else A1` (assumes `jumps_max == 2`).</li></ul>The decomp attribute files give `jumps_max` 2 for every fighter except Kirby and Jigglypuff, which have 6 (`decomp/src/relocData/229_KirbyMain.c`, `233_PurinMain.c`). | B (new cell contract and new archive) | M | AP (sd1, sd2, g3), cell CD, Esd1, Esd2 |
| 5.4 | `rl/m8_rd_select2.py:52,57-62` | Mario's gravity, aerial-jump, up-B and tornado rises; `UPB_STATUS_CLASS = "special_hi"` ("ids 225/226 for Mario"); `W_RES` derived from "Mario: G and A2 have both the aerial jump and the up-B". See 6.4. | B | M | AP-sd, select CD, Esd1, Esd2 |
| 5.5 | `rl/m7u_state.py:55`; `rl/tools/m7o_offline.py:182,350`; `rl/m7n_equivalence.py:117` | `JUMPS_MAX = 2` (Mario), in retired M7u/M7o analysis code | — | — | — |
| 5.6 | `docs/rl_observation_v3_proposal_m7n.md:38` vs `docs/rl_mechanics_observation_audit_2026-09-28.md:92` | The docs disagree on Kirby/Jigglypuff `jumps_max` (6 vs 5). The decomp data says 6, and the code reads it natively, so code is unaffected. | — | — | — |

### Area 6 — Route and speed discovery (M8)

| ID | Where | What it assumes | Class | Size | If edited in place |
|---|---|---|---|---|---|
| 6.1 | `rl/m8_rd_cells.py:9-14,175-189` | Cell key `(bx, by, res, mask, floor)`: x and y bins with no clipping and no stage extents; the native 10-bit live mask; native `floor_line_id` when grounded. Level = 10 − popcount. **The structure is generic.** | A | — | — |
| 6.2 | `rl/m8_rd_cells.py:30`; `docs/rl_m8_rd_proposal_2026-10-01.md:262-274` | **`CELL_SIZE = 300`, justified from Mario's geometry:** surfaces ≥ 300 apart (L0 3,000 … L4 −2,550), "launch-capable from ≥ 1,639", and 600-unit bins would merge the 1,500–2,100 band. Cell counts were measured on 400 random Mario episodes. ⚠ tuned to Mario (C6). | B (re-justify or derive per stage; new contract and new archive) | S code / L process | AP, cell CD, Esd1, Esd2 |
| 6.3 | `rl/m8_rd_cells.py:41,172` | Resource classes (5.3) | B | M | as 5.3 |
| 6.4 | `rl/m8_rd_select2.py:28-33,57-62,72-83,120-134`; inherited unchanged by v3 (`rl/m8_rd4_select.py:13,57-76`) and v4 (`rl/m8_sd1_select.py:13`) | **E6 eligibility:** an airborne cell is ineligible iff `y + R + 300 < Y_floor_min`.<ul><li>R is built from Mario's gravity 2.4 (`203_MarioMain.c`), aerial-jump rise 1,171.8, up-B rise 1,361.3 (M7p agent flights) and tornado rise.</li><li>`Y_floor_min` comes from `rl/m7g_spatial.EXPECTED_LINES`, a hard-coded copy of Mario's table (`:48-73`).</li><li>The docstring (`:28-29`) says "read from the native line table", but no registered launch path passes `floor_min` (the default is None: `m8_rd2_session.py:165`, `m8_sd1_session.py:248`, `m8_sd2_session.py:250`).</li></ul>Active in rd2, rd3, rd4, sd1 and sd2. ⚠ C1. | B (remove E6 in a new selection, or per-character constants plus the live tick-0 floor) | M | AP-sd, select CD (in approval `contracts`), Esd1, Esd2 |
| 6.5 | `rl/m8_rd_claims.py:28,101-111,159-165,209-211`; `rl/m8_rd_rule.py:25`; `rl/m8_rd4_claims.py:36`; `rl/m8_rd_cells.py:55-58,244-293` | **Milestone ladder `("none","L0","crossing","left_target","clear")`**, with `LEFT_BOUNDARY_X` −2100, `L0_FLOOR_LINE` 0 (wall top), `LEFT_FLOOR_LINES` (3,), `LEFT_TARGET_IDS` (1,6,8). The rd1–rd4 outcomes are this ladder's level. ⚠ C4: Mario-stage milestones in claims and rules. | B (generic ladder: target levels + clear) | M | rd1–rd4 RD, AP, cell CD, claims CD |
| 6.6 | `rl/m7n_crossing.py:40-75,150-223` via `m8_rd_session.py:497-500` and `m8_rd2_session.py:335-338` (rd3, rd4, sd1, sd2) and `m9_session.py:309,365-366` | The claims analyser decodes Mario's stage geometry from `decomp/src/relocData/124_GRBonus1MarioFile2.c` (`rl/m7g_fixture.py:49-50`) and `REWARD_V3`. The break table it returns comes from the generic `m7f_targets.check_trace`; sd1, sd2 and M9 consume only that table and the clear facts. Whether `analyse_trace` completes without raising on another stage cannot be determined. | B (generic break extractor in a new module) / D | S | AP-sd, AP-g3 |
| 6.7 | `rl/m8_rd2_rule.py:37-41,54-58,76,95-97`; `rl/m8_rd2_report.py:25-30,47-48`; `rl/m8_rd3_rule.py:36,141` | **rd2/rd3 rules:**<ul><li>below-floor `y < −2,850` dilution limits of 105 and 110 per mille, against rd1's counts (`RD1 = {2175, 456, 480, 14, …}`);</li><li>launch-capable `y ≥ 1,639` drives stop S6;</li><li>`PROGRESS_MIN_TARGETS = 8` (= 7 right-side targets + 1).</li></ul>rd4, sd1 and sd2 keep these as "reported only". ⚠ C2. | — (frozen; not reusable) | — | rd2/rd3 RD |
| 6.8 | Open: `rl/m8_sd1_run.py:88`, `rl/m8_sd2_run.py:88`. Close: `rl/m8_rd2_run.py:134-136`, `rl/m8_rd3_run.py:102-104`, `rl/m8_rd4_run.py:110-112`, `rl/m8_sd1_run.py:116-118`, `rl/m8_sd2_run.py:116-118`, `rl/m8_rd_finish.py:48-50` | **Identity-replay sampling** uses `is_launch_capable` (y ≥ 1,639), grounded on line 0, `key[0] <= -8` (≡ x < −2,100) and `LEFT_TARGET_IDS`. It chooses which cells get integrity replays; an inexact replay makes the session INVALID. ⚠ C3. | B (generic predicates) | S | Fsd1, Fsd2, AP |
| 6.9 | `rl/m8_rd3_run.py:120-133`; inherited at `m8_rd4_run.py:56`, `m8_sd1_run.py:60`, `m8_sd2_run.py:59` | The I15 suppression of the `l0` label (Mario wall-top hazard). Unneeded with a generic ladder. | — | — | AP |
| 6.10 | v1 `rl/m8_rd_archive.py:47-55,188-216`; v2 `m8_rd_select2.py:52,322-323`; v3 `rl/m8_rd4_select.py:45,125-128`; v4 `rl/m8_sd1_select.py:51,92-94,152-155,189-194` | **Preferences read no position.** Harmonic level weight, count term (1+seen)^−½, length factor (900 / 120), E7 record bound. Generic, except `W_RES`'s Mario-based derivation. | A (B S for `W_RES`) | S | select CD |
| 6.11 | `rl/m8_sd1_rule.py:48-51`; `rl/m8_sd2_rule.py:53-56`; `rl/m8_sd1_resume.py:47-85`; `rl/m8_sd2_resume.py:56-107`; `rl/m8_rd4_resume.py:44-54` | T_REC 2,315 → 2,086 are the agent's own verified clears; MARGIN 24 is "about 1 % of T_REC". The integrity literals are this archive's facts. **Per-archive by design.** A new stage gets T_rec from its own first clear. | A (data) | — | Fsd1, Fsd2, RD |
| 6.12 | `rl/m8_rd2_session.py:86-96` (reused by rd3, rd4, sd1, sd2); `N_WORKERS = 5` | Caps: 6,000,000 / 2,000,000 arm ticks, walls p1 240 s / T 3,000 s / verify 360 s, global 3,600 s. Generic. | A | — | — |
| 6.13 | `rl/m8_rd_session.py:66-74` | The P1 determinism traces are Mario M7d episodes under `runs/`. A new stage needs its own (the smoke test can produce them). | B | S | AP |
| 6.14 | `rl/m9_lineages.py:129-131`; the select contract's `lines_sha256` | The tick-0 pin (line-table digest, archive meta) pins Mario's stage. The mechanism is generic. | A | — | — |

### Area 7 — Policy line (M9 g3, and g4 as proposed)

| ID | Where | What it assumes | Class | Size | If edited in place |
|---|---|---|---|---|---|
| 7.1 | `rl/m9_lineages.py:137-148` | **Landing detection is generic:** the first input tick of each grounded run (`is_live ∧ ground_air_state == 0`). | A | — | — |
| 7.2 | `rl/m9_contract.py:61`; `rl/m9_lineages.py:151-157`; used at `rl/m9_g3_frontier.py:59`, `rl/m9_g3_session.py:724,737`, `rl/m9_g3_run.py:247,298` | **The landing registry is a constant:** `LANDINGS = (2128, 1966, 1694, 1473, 1369, 1248)`. It is cut at 1,248 ("segments from the moving target on", `docs/rl_m9_policy_proposal_2026-10-03.md:87-104`). `check_landings` only verifies the constant against the derived list. ⚠ C5. | B (derive at P1 by the registered rule) | M | AP-g3, g3 s1 RD, Eg3 |
| 7.3 | `rl/m9_contract.py:38-46,49`; `rl/m9_curriculum.py:55`; `rl/m9_g2_frontier.py:48`; `rl/m9_g3_frontier.py:43`; `rl/m9_lineages.py:108` | Lineages `T_clear` (2,326) and `T_t` (2,315), `SHARED_PREFIX` 2,298, `TAU0` 2,300, and lineage names hard-coded in code. | B S (code) + L (needs a verified M8 clear on the new stage) | S / L | AP-g3, CD, Eg3 |
| 7.4 | `rl/m9_contract.py:65-67`; `rl/m9_rule.py:31`; `rl/m9_g2_contract.py:70-78`; `rl/m9_g3_contract.py:109-110`; `rl/m9_g3_rule.py:44,103-104`; `rl/m9_g2_rule.py:31,135-136,206` | **Rule depths in Mario-route ticks:**<ul><li>PASS 1,694; CROSSING 1,473 ("crossing learned"); INCONCLUSIVE 1,966 / 2,128;</li><li>`LINE_BUDGET {2: 2128, 4: 1966, 6: 1694}`; success 1,473; `ROUTE_END` 2,326;</li><li>the literal `2128` in the close-audit test;</li><li>outcome-name literals `END_BUDGET_2128/1966/1694`, which feed the line-rule digest.</li></ul>⚠ C5. | B (express as landing indices; replace literal 2128 with `max(LANDINGS)`) | S–M | Fg3, g3 RD (both), Eg3, AP-g3 |
| 7.5 | `rl/m9_g2_contract.py:60`; `rl/m9_g3_contract.py:65,115-126`; `rl/m9_g2_tape.py:39`; `rl/m9_g3_run.py:138-139` | `TAPE_KEYS {2128: 200, …}`, the reused tape table pinned by sha256, `DRIFT_LANDING` 2,128. g3 refuses to run without the reused table. | B (re-measure with g2's T0 machinery on the new route) | M | Fg3, Eg3, AP-g3 |
| 7.6 | `rl/m9_contract.py:49-58`; `rl/m9_g2_contract.py:48-53,157-169`; `rl/m9_g3_contract.py:95-105`; `rl/m9_g3_frontier.py:141-207`; `rl/m9_g2_rule.py:68-90` | **Generic machinery:** strip 20, near window 40, region weights 50/30/20, trigger 8 / void 13, test 20 with pass at 10 and fail at 11, spacing `min(320, 20·2^(f−1))`, sticky p 0.25, pointer moves, the D/R chain. | A | — | — |
| 7.7 | `rl/m9_worker.py:219-268`; `rl/m9_lineages.py:160-172,214-266` | Prefix replay of the registered lineage words, with per-tick chain and v3 digests checked against tables built at P1 from the rd4 verifying replay. The mechanism is generic; the data is Mario's. | A (mechanism) / L (data) | — | — |
| 7.8 | `rl/m9_obs.py:39`; `rl/m7n_obs.py:58` | Observation for Mario's classifier and Mario's projectile scale (4.5, 4.8) | B (new module) | S | AP-g3, Eg3 |
| 7.9 | `rl/m9_worker.py:258`; `rl/m9_vec.py:161` | `BurstScanner` Mario labels in every episode record; no M9 rule reads them. | B | S | AP-g3 |
| 7.10 | `rl/m9_g2_report.py:110-133`; `rl/m9_g3_report.py:38,458` | `post_target8_share` uses `tau >= 2066` and target id 8 (report only). | B | S | Fg3 (`m9_g3_report`), AP-g3 |
| 7.11 | `rl/m9_eval_ckpt.py:64` | `START_POINTS (2128, 2250, 2010)` | B | S | AP-g3 |
| 7.12 | g4 proposal `:260,366-382,426-429,239,285-287,292-306,328,336-337` | **g4's Mario- and data-specific items:**<ul><li>warm start from s5's final model `382dde88…`: impossible for another character, which must start fresh;</li><li>`D_start` 1,694, a pace of 100 ticks per session, budgets `END_BUDGET_1473/1248/1061/841`;</li><li>the 16-landing scale taken from Mario's trunk;</li><li>re-check "the route's last landing" (generic as worded; the value is 2,128);</li><li>trigger NR < 0.40, calibrated so it fires 0× in g3 s1–s5 and once in s6 (⚠ C7);</li><li>probe budget 30 % (from s5's 22.8 %); tape bar B = 15 at 2,128.</li></ul>The rest (N1 as a rule, keep-best, forward-only init probe, fresh keys) is generic. | B / D | M (design) | — (not implemented) |

### Area 8 — Tests, fixtures and pinned digests

**How the registered values are computed:**
- **sd fingerprints.** `rl/m8_sdN_session.py:108-118` and `tools/m8_sdN/three_passes.py`. They hash the repo-relative path plus sha256 for the glob `rl/m8_sdN_*.py` and every file in `tools/m8_sdN/`. The glob is a **filesystem glob**, so any new file matching it changes the fingerprint.
- **g3 fingerprint.** Computed by the untracked `logs/m9_g3_resume_tools/three_passes.py`. It was reproduced here as basename plus sha256 over sorted `rl/m9_g3_*.py`, giving `15ddbb84932aa658`.
- **e2e digests.** Behaviour digests, compared to the docs by people only:
  - Eg3: `rl/m9_g3_tests.py:1828-1837`;
  - Esd1: `rl/m8_sd1_tests.py:1814-1817` (`signature5`, `:251-267`);
  - Esd2: `rl/m8_sd2_tests.py:2297-2300` (`signature6`, `:248-268`).
- **No registered value appears as a literal in code.**

| ID | Where | Mario-specific content | Per-character equivalent needed | Class | Size |
|---|---|---|---|---|---|
| 8.1 | `rl/fixtures/m7g/lower_precision_2ad7b1da89d8.json`, `upper_moving_platform_8b9ecf2b967f.json` | Human-recorded Mario crossings; validation-only. Never read on the active path (guard at `rl/m8_rd_worker.py:45`). | **None.** Must not be created as starts or demonstrations. | — | — |
| 8.2 | `rl/m1e_replay_regression.py:4-7,61-69`; `rl/m6_equivalence_regression.py`; `rl/m1d_smoke.py:46-50`; `rl/m6_raphnet_bypass_regression.py:28,103` | TAS baseline: 468 rows, 447 / 446, 7.43 s, checksum `0x93E9EFB4`; native-replay gate (2.5). | None for other stages. The regression for a new stage is its own smoke chain digests (section 5) and later its own verified clear. Mario's M1e must still pass on any new executable. | B | S |
| 8.3 | `rl/m7f_tests.py:39-64`; `rl/m7f_validate.py:41-45`; `rl/m7f_targets.py:44-50` | Frozen target-ID mapping, spawns, TAS break order and ticks, Mario regions | A target-identity check generated from the new stage's native tick-0 table (not from any recording) | B | S |
| 8.4 | `rl/m8_rd_stub.py:35-57,268-288`; `rl/m8_rd_tests.py:172-176,763,942`; `rl/m8_sd1_tests.py:337-340,414,806-807,…`; `rl/m8_sd2_tests.py:348-354,…,1599-1602` | Stub worlds use Mario line ids (0, 1, 3, 4) and real spawns. The analyser uses x < −2,100. Pinned references are 2,315 and 2,086. `CENSUS_TOKENS` is defined here. These feed Esd1 and Esd2. | New suites with a synthetic stub that is not Mario-shaped and the new stage's own references | B | M |
| 8.5 | `rl/m9_stub.py:37-42`; `rl/m9_g3_tests.py:76,79-87,250-258,1727-1786` | The stub world copies Mario's trunk (landings, break ticks and ids, 2,326 / 2,315 / 2,298); `forget_landing` 1,966; assertions on 2,128 / 1,966. These feed Eg3. | A new stub derived from no real route, or from the new route | B | M |
| 8.6 | `rl/m9_g3_tests.py:1494-1496`; `rl/m9_g3_session.py:103` | `rl/m9_eval_tests.py` is pinned by sha256 (`AUTHORISED_TRACKED_EDITS`). **Editing it breaks the g3 suite even after a commit.** | Never edit | — | — |
| 8.7 | `rl/m8_sd1_tests.py:1648-1664`; `rl/m8_sd2_tests.py:1747-1767`; the M9 suites' git gates | Earlier modules, `m9_artifacts.py`, `m9_contract.py` and `DOC_FILES` must equal HEAD. The M9 suites fail while any untracked non-M9 file exists under `rl/` or `docs/`. | Commit new files before running any registered suite | — | — |
| 8.8 | `.gitattributes`; `git ls-files --eol` | `*.py` and `*.ps1` are `eol=lf`. Pinned `rl/data/*.json`, `docs/*.md` and `docs/*approval.json` have **no eol attribute**, and `core.autocrlf=true` here. They are LF in this working tree today, but a fresh clone or worktree would write CRLF and break the approval docs and data pins. `tas_input_2/mario_743.btti` is already CRLF in the working tree. | Open question 11 | — | — |
| 8.9 | `replay/replay_tests.py:206,220-251,306-328,376-377,598-613,891-952` | Mario labels, task identity, 7.43 s | Extend when the browser gains task metadata | B | S |

### Area 9 — Native port code (every hook the agent relies on)

| ID | Where | What it does | Mario-specific? | Non-PORT path preserved? | Class | Size | If changed |
|---|---|---|---|---|---|---|---|
| 9.1 | `decomp/src/sc/scmanager.c:1069-1073` | `rlBootApply` call | **Yes (`nFTKindMario`)** | Yes (`#ifdef PORT`) | C (change in `rl_boot.cpp` instead) | S | EXE |
| 9.2 | `scmanager.c:830-924` | `rlGameFillObservation` (player fighter, generic) | No | Yes | — | — | — |
| 9.3 | `decomp/src/sc/sc1pmode/sc1pbonusstage.c:71-102` | Controller read: replay first, then interactive stepping (player 0), otherwise the stock read | No | Branches inside `#ifdef PORT` | — | — | — |
| 9.4 | `sc1pbonusstage.c:13-14` (includes) and `:381` (taskman controller callback `syControllerFuncRead` → `sc1PBonusStageFuncReadReplay`) | Added by decomp commit `e4bc8e24c` (2026-09-15) **outside `#ifdef PORT`** | No | **Probably not byte-identical.** Behaviour is preserved, because outside PORT the wrapper only calls `syControllerFuncRead()`. But a new function and a changed pointer in the N64 build mean the build would no longer match. This is an inference: it was not verified, because a decomp `make` / validate needs the ROM. ⚠ This is a pre-existing project-rule issue, not Mario-specific. | C (wrap: `#ifdef PORT` wrapper / `#else syControllerFuncRead`) | S | decomp pointer; whether EXE stays bit-identical cannot be determined |
| 9.5 | `sc1pbonusstage.c:1895-1907` | Native `.btti` replay armed only on Mario's map; interactive session for any stage | **Yes (replay only)** | Yes | C (optional) | S | EXE |
| 9.6 | `sc1pbonusstage.c:587-1238,1278-1280`; `decomp/src/it/itground/ittarget.c:3-7,42-46`; `port/rl/rl.h:717-719,880` | Target table and spawn/break hooks; spatial, entity and input fills. Read-only, PORT-only memory. Capacities `RL_SPATIAL_MAX_GROUPS 4` / `LINES 32` / `LINE_VERTICES 4` (comments: "Mario's stage has 3 / 20 / 4"); `RL_ENTITY_MAX_WEAPONS 8` ("Mario never exceeds 4 live fireballs"). Overflow sets an anomaly flag and truncates; it does not crash. | Sized for Mario | Yes | C | S–M (struct sizes; schema bump) | EXE, obs CD |
| 9.7 | `decomp/src/sys/netreplay.c:45,309-363`; `netinput.c:177-186` | Interactive session arming and saved-input staging | No | Port-added files (added in commit `f74646d59`), not part of the matching build | — | — | — |
| 9.8 | `decomp/src/sys/dma.c` (`unref_800036B4`, `#ifndef PORT`) | The preferred exclusion pattern | No | Yes | — | — | — |
| 9.9 | `port/gameloop.cpp:763,770,798-802,845,902-906,920`; `port/port.cpp:1396,1399,1403,1449,1453` | Stepping host gate, no-render, timing, init and shutdown | No | Host side | — | — | — |
| 9.10 | `libultraship/src/ship/controller/controldeck/ControlDeck.cpp:34-48` (commit `805f1950`) | `SSB64_RAPHNET_DISABLE` bypass | No | Host side | — | — | — |
| 9.11 | `port/rl/rl_transport.cpp:341-357,651-657` | Protocol 1: ping, status, observe, step. No fkind/gkind; no seed operation. | n/a (2.6) | — | C (optional) | S | EXE |
| 9.12 | `port/rl/*` | No US/JP conditionals. The `REGION_US` blocks in `sc1pbonusstage.c` touch only the 1P-game time-up path. No RNG anywhere in `port/rl`. | No | — | — | — | — |

**Collision capacity per stage.** Counted statically from `decomp/src/relocData/124–135_GRBonus1*File2.c`. The Mario, DK, Samus, Captain Falcon and Fox line counts were re-checked here from the `MPVertexLinks` array sizes; group counts are `Layer1DObj` entries minus the terminator.

| Stage | Lines (cap 32) | Max vertices/line (cap 4) | Groups (cap 4) | Fits? |
|---|---|---|---|---|
| Mario | 20 | 4 | 3 | yes |
| Donkey Kong | 23 | 3 | 4 | yes (groups at the cap) |
| Samus | 26 | 2 | 3 | yes |
| Captain Falcon | 27 | 2 | 3 | yes |
| Jigglypuff | 26 | **6** | 4 | no |
| Fox | **36** | 4 | **5** | no |
| Luigi | **39** | 2 | **5** | no |
| Link | **36** | **6** | 4 | no |
| Kirby | **41** | 4 | 3 | no |
| Pikachu | **41** | **6** | 3 | no |
| Yoshi | **60** | 2 | 4 | no |
| Ness | **68** | 2 | 3 | no |

**Executable consequence.** Any native change produces a new executable. Every registered approval pins `executable_sha256 30a3913b…`. The snapshot tool hashes the executable but **does not copy it** (`rl/m8_sd2_snapshot.py:111-114`, "hashed, not copied (build output)"). The registered binary therefore exists only at `build-us/Release/BattleShip.exe` unless you have archived it elsewhere (open question 2).

### Area 10 — Constraint check (reported prominently)

**Clean:**
- **TAS and human recordings.** No read in any active M8/M9 path.
  - The runtime provenance guard is `rl/m8_rd_worker.py:45` (`tas_input`, `mario_743`, `.btti`, fixtures), plus the audit hook at `:77-101`.
  - `rl/battleship_process.py:83,241` keeps native TAS replay away from RL children.
  - The rule files list any such read as INVALID: rd2 `:65`, rd3 `:60`, rd4 `:80`, sd1 `:96`, sd2 `:110`.
- **RNG.** No native RNG seed inspection, logging, control, comparison or hashing anywhere. The protocol has no seed operation.
  - Python seeds only: PPO `seed 0` (`rl/m9_contract.py:80`) and `1000 + k` (`rl/m9_g2_train.py:159`). `TrainVecEnv.reset` ignores seeds.
  - Every M8/M9 draw is a sha256-keyed uniform.
- **Routes.** No hand-written waypoint list or scripted action sequence. Prefixes, lineages and tapes are the agent's own verified rd4 clears, digest-pinned.

**Flags, most significant first:**

| Flag | Status | Where | Finding |
|---|---|---|---|
| ⚠ C1 | POTENTIAL; active in rd2, rd3, rd4, sd1, sd2 | `rl/m8_rd_select2.py:57-62,72-83,120-134` | **E6 eligibility reads the cell's own height `y`** against a floor taken from a hard-coded copy of Mario's stage table, with Mario's rise constants. `RISE_UPB` 1,361.3 comes from the same M7p agent flights as the 1,639 threshold (1,639 ≈ 3,000 − 1,361.3; `docs/rl_m8_rd1_diagnosis_2026-10-02.md:97`). It is not a preference and not a route, but it is a position-dependent eligibility rule tuned to Mario and his stage. The docstring's claim that the floor is read from the native table is inaccurate. |
| ⚠ C2 | VIOLATION by the letter of "no census number in selection, claims, rules or runs"; registered and frozen | `rl/m8_rd2_rule.py:37-41,54-58,76,95-97`; `rl/m8_rd3_rule.py:36,141` | The rd2 and rd3 rules use stage coordinates and census numbers:<ul><li>below-floor `y < −2,850`;</li><li>dilution limits 105 / 110 per mille derived from rd1's measured counts;</li><li>launch-capable `y ≥ 1,639` driving stop S6;</li><li>`PROGRESS_MIN_TARGETS = 8` from the stage's 7 right-side targets.</li></ul>From rd4 on these are "reported only". Whether the census rule was in force when rd2/rd3 were registered cannot be determined (open question 4). |
| ⚠ C3 | VIOLATION, low impact; inside the registered sd1/sd2 run engines | `rl/m8_sd1_run.py:88`; `rl/m8_sd2_run.py:88` (open); close predicates in 6.8 | 1,639 picks 4 of the 16 open identity-replay cells. The close sample uses the wall top (floor line 0), `key[0] <= -8` (≡ x < −2,100) and `LEFT_TARGET_IDS`. These choose integrity replays only, never selection, claims or outcome (except INVALID on an inexact replay). **Guard gap:** the sd census source guards (`rl/m8_sd1_tests.py:1592-1598`, `rl/m8_sd2_tests.py:1599-1667`) scan only the four sd wrapper modules. Their token list lacks 1639, −2850, 3000 and −8, and the constants live in imported modules (`m8_rd2_report`, `m8_rd_select2`, `m8_rd_cells`). |
| ⚠ C4 | POTENTIAL; rd1–rd4 claims and rules | 6.5 | Milestones (wall top, crossing, left target) are defined by Mario's stage geometry and target ids. Not a sequence, but stage-specific by construction. |
| ⚠ C5 | POTENTIAL under a strict reading; M9 | 7.2, 7.4, 7.5, 7.11 | M9 rules, curriculum and the "crossing learned" claim label are written as tick numbers from the agent's own trunk. The landings are re-derived and checked at P1 by the generic rule, and own trajectories are allowed. But they are literals in rule code, and sd2's own guard lists 2128, 1694, 1966, 2298 and 2066 as census tokens (`rl/m8_sd2_tests.py:1600-1602`). |
| ⚠ C6 | POTENTIAL; design-time tuning | 6.2, 5.2, 6.10 | `CELL_SIZE` 300 is justified from Mario's surface spacing and the 1,639 launch height. The explorer holds are justified from Mario's flights. `W_RES` is derived from Mario's resources. |
| ⚠ C7 | POTENTIAL; g4 proposal | 7.12 | Trigger NR < 0.40 calibrated on the g3 s1–s6 record (a census-calibrated rule threshold). Budget pace taken from g3. |
| C8 | Low | `rl/m7g_fixture.py:55-57,797-823` → `rl/m8_rd_claims.py:224` | The claims analyser's route-label vocabulary is named after the human-recorded crossings (`MARKED_LOWER_CORNER = (2100, −450)`, "user-marked"). The label is written into every claim-replay record but decides nothing. |
| C9 | Documentation / guard inconsistency | `rl/m7g_fixture.py:10`; `rl/m9_tests.py:1332`; `rl/m9_session.py:309` | The fixture docstring says "nothing in the training stack imports this module", but M8 and M9 import it transitively through `m7n_crossing` (`:49`). The M9 guard forbids the token `m7g_fixture` in M9 sources, yet the transitive import exists. No fixture file is read. Also, the M8 runtime guard lacks `replay/recordings`, which the M9 test guards forbid (`rl/m9_g2_tests.py:1093`). |

## 3. Files a future preparation must NOT modify, and the safe pattern

**A. Fingerprinted.** Any byte change, or any new file matching the glob, breaks these:
- `rl/m9_g3_*.py` (10 files) → `15ddbb84932aa658`
- `rl/m8_sd1_*.py` (10 files) + `tools/m8_sd1/*` (5 files) → `f7fadda5ec11b3dd`
- `rl/m8_sd2_*.py` (10 files) + `tools/m8_sd2/*` (9 files) → `b22c0af8f833b205`

Never create a file named `rl/m8_sd1_*`, `rl/m8_sd2_*` or `rl/m9_g3_*`, or anything under `tools/m8_sd1/` or `tools/m8_sd2/`.

**B. Approval-pinned code.** These 130 files under `rl/` plus 14 tool files form the union of the `code` lists in the sd1, sd2 and g3 s1–s6 approvals. Edits change approval matches and, through behaviour, Esd1, Esd2, Eg3, the contract digests and the rule digests.
- `rl/m8_rd_*.py`, `rl/m8_rd2_*.py`, `rl/m8_rd3_*.py`, `rl/m8_rd4_*.py`
- every `rl/m9_*.py`, including `m9_contract.py`, `m9_artifacts.py`, `m9_stub.py`, `m9_testenv.py` and `m9_eval_tests.py` (also pinned by `AUTHORISED_TRACKED_EDITS`)
- `rl/battleship_client.py`, `rl/battleship_process.py`, `rl/btt_learning.py`, `rl/btt_rewards.py`, `rl/btt_reward_v3.py`, `rl/run_artifacts.py`
- `rl/m7_runtime.py`, `rl/m7_standby.py`, `rl/m7f_trace.py`, `rl/m7g_fixture.py`, `rl/m7g_spatial.py`, `rl/m7h_curriculum.py`
- `rl/m7n_crossing.py`, `rl/m7n_entity.py`, `rl/m7n_obs.py`, `rl/m7n_policy.py`, `rl/m7n_status_table.py`, `rl/m7q_status_table.py`
- `rl/m7s_gate.py`, `rl/m7u_gate.py`, `rl/m7u2_gate.py`, `rl/m7u3_gate.py`
- `rl/data/m7n_action_classes_v1.json`, `rl/data/m7n_action_classes_v2.json`, `rl/tools/runs_backup.py`

**C. Unpinned but on the active path; treat as frozen.**
- `rl/m7f_targets.py` supplies the break table every claim depends on.
- `rl/battleship_env.py`.
- `rl/experiment_config.py`: append-only. New `SUPPORTED_TASKS` rows are fine; the Mario row stays byte-identical, and `replay/replay_task.TASKS` is updated in the same commit.

**D. Pinned documents** (`docs_sha256`, 49 files), and by project rule every approval and results record:
- the M8 route-discovery records:
  - `rl_m8_rd_proposal_2026-10-01`, `_amendment_2026-10-02`, `_continuation_proposal_2026-10-02`, `_implementation`;
  - rd1 results and diagnosis; rd2, rd3 and rd4 decisions, implementation and results; the rd3 stop review;
- `rl_m8_sd1_{approval.json, prep, proposal, results}` and `rl_m8_sd2_{prep, proposal}`;
- `rl_m9_g1_{decisions, diagnosis, implementation, results}`;
- `rl_m9_g2_{decisions, implementation, proposal, s1_results, stop_review}`;
- `rl_m9_g3_{decisions, implementation, launch_record, recheck, resume_k_prep_decisions, s2_prelaunch_review, s2_prep_decisions}`, `rl_m9_g3_s1…s5_{approval.json, results}`;
- `rl_m9_policy_proposal_2026-10-03`.

**E. Native and runtime.**
- `build-us/Release/BattleShip.exe` (`30a3913b…`). It is not copied by any snapshot, so **archive it, with a note of the commit that built it, before any rebuild**.
- Runtime files: `BattleShip.o2r` (`fe2b307e…`), `f3d.o2r`, `gamecontrollerdb.txt`, `BattleShip.cfg.json`, `imgui.ini`.
- Submodule pointers: `decomp` `e4f06348b`, `libultraship` `805f1950`, `torch` `3aa9c97`.
- Each approval's `git_head`: sd1 `7009c9e`, sd2 `5985a83`, g3 s1–s6 `ca3cfb6 … 1d975ef`.
- Note: g3 s1 and s2 already mismatch HEAD in 6 and 5 code pins (the progression fix), so re-verifying them needs their own `git_head`.

**F. Evidence.** `runs/` trees and the D: increments.

**Safe pattern for per-character code:**
1. **One new, task-parameterised module family** with a prefix that collides with no glob above (for example `rl/c1_*.py`, tools in `tools/c1_<session>/`). Every task-specific value (fkind, stage, references, landings) is passed in from a task row or a data file, never written as a module constant.
2. **Reuse by import, extend by subclass or composition**, as sd2 does over sd1. Never edit, and never monkey-patch at import time, a constant that frozen code reads (`m8_rd_cells.FIGHTER_CHARACTER`, the E6 constants, `m9_obs`). Where frozen code reads a module-level constant, write a replacement class in the new module.
3. **A new task registry module** with exactly `{id, character, stage}` blocks and its own writer validation. Leave `m9_artifacts.REGISTERED_TASKS` alone, because frozen tests pin it to Mario.
4. **New names carry the task:** `runs/<line>_<character>/…`, `<date>_incr_<line>_<character>_<session>`. Each tool names the increment it expects.
5. **Native changes are default-off and additive.** With the variable unset, Mario's replies must be byte-identical. Build into a separate build directory, or archive the registered executable first. Prove equivalence by replaying the agent's registered clears from tick 0 and by Mario's M1e regression (validation-only).
6. **LF for every new file.** Commit before any registered suite runs (git-state gates). No pinned document is edited; records go to new files.

## 4. Adding a character — checklist (in dependency order)

**Recommended first character: Donkey Kong. Runner-up: Captain Falcon.** Based only on what the code shows:
- **Capacity.** DK's stage fits every native diagnostic capacity: 23 lines, 3 vertices per line, 4 groups (at the cap). Only DK, Samus and Captain Falcon have that property besides Mario, so obs v3 and the M8 chain digest represent it completely without a native schema change.
- **Jumps.** `jumps_max` is 2, as for Mario (`decomp/src/relocData/213_DonkeyMain.c`), so M8's A2/A1 split keeps its meaning.
- **Projectiles.** DK has no weapon-type projectile, so the obs v3 projectile block and Mario's fireball scale do not matter.
- **Port audit.** DK is rated CLEAN in the per-character bonus audit.
- **Unlocks.** DK is a starter, which removes the one runtime unknown about loading an unlockable fighter from a fresh save (2.3).

Captain Falcon has the same profile (27 / 2 / 3, `jumps_max` 2, no projectile, CLEAN), with more headroom on groups; it is unlockable, but the boot bypasses unlocks by code. Samus fits the capacities but has projectiles and the LATENT A1 finding.

Avoid as a first character:
- Kirby and Jigglypuff (`jumps_max` 6; Kirby's C1 panic);
- Ness (68 lines; C3);
- Yoshi (60 lines);
- Link (36 lines, 6 vertices, US/JP data difference);
- Fox, Luigi, Pikachu (all exceed the capacities).

| # | Step | Class | Size |
|---|---|---|---|
| 0 | **Decide** the character, task id and names (open questions 1, 10). | — | S |
| 1 | **Archive** the registered executable `30a3913b…` and its runtime files; record the commit that built them. | process | S |
| 2 | **Select the character natively.** In `port/rl/rl_boot.cpp`, read `SSB64_RL_FKIND` (0..11, range-checked) and substitute it in `rlBootApply`. Name the log tag after the stage. Optionally report `fkind` / `gkind` / `bonus_fkind` in status only when the variable is set. No decomp edit. Build to a separate directory; libultraship and torch untouched. | C | S |
| 2b | Only if the chosen stage exceeds a capacity: raise `RL_SPATIAL_MAX_*` / `RL_ENTITY_MAX_WEAPONS` with a schema bump. Not needed for DK, Captain Falcon or Samus. | C | S–M |
| 3 | **Mario equivalence on the new executable** (needs your authorisation for native ticks): M1e TAS regression (validation only); replay the agent's sd2 clear (cid 1360) and rd4 `T_clear` from tick 0 with the variable unset and with it set to 0; chain digests must equal the registered ones. | B (tooling) | S |
| 4 | **Task registry:** new registry module; append rows to `experiment_config.SUPPORTED_TASKS` and `replay_task.TASKS`. | B | S |
| 5 | **Stage smoke test** for the chosen character (section 5). Its traces become the stage's P1 determinism traces. | B + native | S–M |
| 6 | **Character status table:** classify the fighter's own status ids (special_hi / helpless / landing / damage …) from decomp headers into a new data file; validate against the smoke traces. | B | M |
| 7 | **Generic M8 core in new modules:**<ul><li>resource class from native `jumps_max` and the validated table;</li><li>no Mario `BurstScanner` labels;</li><li>milestone ladder = target levels + clear;</li><li>break table from `m7f_targets.check_trace` only;</li><li>E6 removed, or per-character rise plus the live tick-0 `floor_min` (question 5);</li><li>generic identity-sample predicates;</li><li>`CELL_SIZE` decision (question 6);</li><li>new rule, claims, session, snapshot, tools and suites with a synthetic stub that is not Mario-shaped;</li><li>an independent pre-launch review.</li></ul> | B | M–L |
| 8 | **Route discovery sessions** on the new stage until a clear is verified by exact replay from tick 0. | native | L |
| 9 | **Speed discovery:** a new sd module set; T_rec = the stage's own verified clear; margin by a generic rule (for example ⌈1 % of T_rec⌉); E7 unchanged. | B + native | S–M |
| 10 | **Policy line:**<ul><li>lineages from step 8;</li><li>landings derived at P1 by `landing_starts` (no constants);</li><li>TAU0 derived from the route length by a registered rule;</li><li>rule depths and budgets as landing indices;</li><li>tape re-measured with g2's T0;</li><li>observation with the task's classifier;</li><li>N1 if g4 is adopted;</li><li>fresh start.</li></ul> | B + native | L |
| 11 | **Replay browser:** read the top-level `task` block (or `replay/task_overrides.json`); generic stage tags. | B | S |

## 5. Smoke test design (not run): `c0_stage_smoke_v1`

**Goal.** For one task, with zero training and no RNG seed handling, prove that:
1. the character's stage loads;
2. random canonical inputs run under the tick contract;
3. every run replays bit-exactly from tick 0 in a fresh process.

**Prerequisites:** checklist steps 1–2 and step 4 (the new task row); your written authorisation for native ticks.

**New files only:**
- `rl/c0_stage_smoke.py`
- `rl/c0_tests.py` (zero-tick tests against a fake process)
- record `docs/rl_c0_smoke_<task>_<date>.md`
- evidence under `runs/c0_smoke/<task_id>/<date>/`

It imports frozen helpers read-only:
- `m7f_trace.run_stepping_trace` (`rl/m7f_trace.py:131-197`)
- `m8_rd_cells.record_of`, `tick0_record`, `chain_start`, `chain_next` (`rl/m8_rd_cells.py:210-241`)
- `m7f_trace.action_digest`
- `m7f_targets.check_trace`

It imports nothing that decides by Mario geometry (`m7n_crossing`, `BurstScanner`, `m8_rd_select2`). It installs a forbidden-path guard like `rl/m8_rd_worker.py:45`.

**Process and flags.** One fresh process per run, launched with the new executable path passed explicitly.
- `extra_env` = `FLAGS_VERIFY` (`rl/m9_contract.py:35`: no-render, Raphnet bypass, spatial, entity, target diagnostic, input) plus `SSB64_RL_FKIND=<k>`.
- Fresh save directory per process (as `battleship_process.py` does).

**Phase L — load** (tick-0 `observe`, no tick consumed). These are the LOAD_FAIL checks:
- Status reports `fkind == k` and `gkind == Bonus1Start + k`. If the optional native fields are not built, this check is replaced by the indirect ones below.
- The tick-0 line-table digest differs from Mario's registered lines digest. `map_bounds` and the line count are recorded.
- Entity `jumps_max` equals the fighter's decomp attribute value (2 for DK).
- Targets (`check_trace`): `spawn_count` 10, remaining mask `0x3FF`, `scene_entries` 1, no target anomaly flags.
- Spatial and entity overflow flags are recorded and reported. They fail only if the chosen stage was expected to fit.

**Phase R — random canonical inputs.** Three runs.
- **Word stream:** the M8 explorer's decision rule (72 Track-1 words uniformly, hold ∈ {1,2,4,8,16}), drawn from a new key family `c0|<task_id>|smoke|run<r>|<decision>` (sha256 uniforms, as `m8_rd_explore.uniforms`).
- **Length:** up to 3,600 words.
- **Stops:** the native clear; or the failure rule (`game_status == 5 ∧ btt_active ∧ targets > 0`, then disposal); or the horizon.
- **Per tick, assert** `consumed_tick == i` and `input_tick == i + 1`. Record the per-tick chain digest, the reply count, the end reason and tick, the break table and the action digest.
- Also record the terminal and teardown replies, to test fact 3.4 on this stage.

**Phase V — replay.** For each run, a second fresh process replays the recorded words from tick 0.
- **PASS** iff all of these are identical:
  - the chain digest at every tick;
  - the number of replies;
  - the end reason and end tick;
  - the break table and action digest;
  - the final and teardown replies.
- **On a desync,** report the first differing tick and field.
- A third replay of run 1 checks three-way agreement.

**Phase M — Mario control** on the same executable. Replay the agent's own sd2 clear (cid 1360, 1,885 words), once with `SSB64_RL_FKIND` unset and once with it set to 0. Its chain digests and `completion_input_tick` 1,885 / `completion_time_passed` 1,884 must equal the registered verification. This reads `runs/m8_rd_sd2` read-only; no TAS or human input.

**Outcome order** (first match wins):
1. INVALID (forbidden read, protocol violation);
2. INCOMPLETE (lifecycle failure);
3. LOAD_FAIL;
4. DESYNC;
5. PASS.

**Budget.** At most 3 × 3,600 × 2 + 3,600 + 2 × 1,885 ≈ 36,000 native ticks across about 9 process starts; random play mostly falls much earlier. Wall time is minutes, dominated by start-up.

**What it does not do:** no training, no selection, no claims, no rules from Mario's data, no RNG seed operation of any kind.

## 6. Open questions only you can answer

1. **First character:** Donkey Kong (recommended), Captain Falcon, or another?
2. **Native change:** approve `SSB64_RL_FKIND` in `port/rl/rl_boot.cpp` (no decomp edit), and the optional status fields gated on it?
   - Is the registered executable `30a3913b…` archived anywhere? The snapshots do not copy it, and whether a rebuild from the same commit is bit-identical cannot be determined.
3. **The two unguarded decomp edits** from commit `e4bc8e24c` (`sc1pbonusstage.c:13-14`, `:381`): fix them now behind `#ifdef PORT`, or leave them?
4. **Scope of "no census number in selection, claims, rules or runs":**
   - Does it apply retroactively to the frozen rd2/rd3 rules (C2) and the sd1/sd2 identity samples (C3)?
   - For new lines, are landing ticks derived at P1 from the agent's own route by a registered generic rule acceptable as rule inputs, provided no tick literal appears in code (C5)?
5. **E6 for new stages:** drop it (the simplest stage-agnostic choice) or re-derive it per character?
6. **`CELL_SIZE`:** keep 300 as a fixed registered value for all stages, or derive it from each stage's map bounds?
7. **Milestones:** may new-stage route discovery use only target levels and the clear (no wall-top / crossing / left-target style milestones)?
8. **Spatial capacity:** raise the native limits once, with one schema bump covering all twelve stages, or only when a chosen character needs it?
9. **Module layout:** one generic, task-parameterised module family registered once (recommended for re-verifiability), or a module set per character?
10. **Names:** task id `ssb64_us_donkey_kong_btt_v1` and stage `btt_donkey_kong`, as `KNOWN_CHARACTERS` / `KNOWN_STAGES` spell them; run trees and increments with a character segment. Confirm?
11. **Line endings:** add `eol=lf` attributes for `*.json` and `*.md`, so a fresh clone or worktree cannot turn pinned documents and data CRLF?
12. **Order for November:** the character line first, or g4 on Mario first? A policy line on a new character needs that character's own verified route first.
13. **Horizon:** keep 3,600 ticks for every stage, or decide per stage after its first clear?
14. **Replay browser:** implement `replay/task_overrides.json` (its intended design is not in the repository), or switch the browser to the top-level `task` block that M9/sd records already carry?
