# Production audit: jump counters, jump-input semantics and the double-jump inference (code only)

Written 2026-09-28 after the wall-top census correction. Existing code and records only; no native run, no edit, no
training. Question: does the incorrect inference "`jumps_used == 2` means a genuine aerial jump happened" reach any
production code, policy observation, reward, curriculum, verifier or registered decision, or is it confined to the
analysis tools and prose of the addenda?

## 0. Native facts used

| fact | source |
| --- | --- |
| `jumps_used` is incremented by the ground jump's motion event and by the aerial jump (`ftCommonJumpAerialSetStatus`) | `decomp/src/ft/ftmain.c:426` (`nFTMotionEventSetAirJumpAdd`), `ftcommonjumpaerial.c:170,242` |
| every recovery special, Mario's up-B included, sets `jumps_used = attr->jumps_max` through the motion event `nFTMotionEventSetAirJumpMax`, which the animation script fires a few ticks after the onset (5 for the aerial up-B) | `ftmain.c:438`; per-character writes in `ft<char>specialhi.c` |
| `jumps_max` is the character constant (2 for Mario) | `FTStruct::attr->jumps_max` |
| Mario's ground and aerial jump share one input function: stick y >= 53 with `tap_stick_y` <= 3 (entered the up range within 3 ticks), or a fresh C-button press (`button_tap` = press edge, no buffer) | `ftcommonkneebend.c:81-110`, `ftcommonjumpaerial.c:288-360` |
| the "held stick or held C button" rule is Kirby's and Jigglypuff's multi-jump function only | `ftCommonJumpAerialMultiGetJumpInputType`, `ftcommonjumpaerial.c:276` |
| the aerial jump is checked from Fall / Jump / JumpAerial / FallSpecial / DamageFall, not from `SpecialAirN` or aerial attacks | callers of `ftCommonJumpAerialCheckInterruptCommon` |

Consequence: `jumps_used` is a **jump-capacity counter** (jumps consumed, where a recovery special consumes all of them),
not a record of which jumps were performed. `jumps_used == 2` after an up-B is correct native behaviour.

## 1. Audit table

| code location | current behaviour | correct semantics | impact | fix needed |
| --- | --- | --- | --- | --- |
| `port/rl/rl.h:179`, `rl_transport.cpp:352` | copies `FTStruct::jumps_used` (widened u32) into the observation; comment "FTStruct::jumps_used, widened" | raw native counter, no interpretation | none | no |
| `port/rl/rl_entity.cpp:27`, `rl.h:893` | exposes `attr->jumps_max` as the entity diagnostic's character constant | correct | none | no |
| `rl/battleship_env.py:241`, `battleship_client.py:135` | `jumps_used` as a u32 observation field | raw counter | none | no |
| `rl/m7n_obs.py:217-226`, `AGENT_FIELDS[16] = jumps_left` | v3 agent feature `(jumps_max - jumps_used) / jumps_max`, clipped to [0, 1]; contract text `"jumps_left": "(jumps_max - jumps_used) / jumps_max"` | remaining **jump capacity** (1.0 = both jumps available, 0.5 = one, 0.0 = none, including after an up-B); it is not "can jump this tick", which also needs an actionable status and a valid input; the formula and label match the native counter | none (the label says what it computes; the proposal's "Remaining jumps" is the same thing) | no |
| `rl/m7n_obs.py` action class one-hot, `rl/m7n_status_table.py:15-19` | `KneeBend` -> `jump_squat`; `JumpF/B`, `JumpAerialF/B`, `Fall*`, `StopCeil` -> `airborne`; `SpecialHi` / `SpecialAirHi` -> `special_hi`; `Landing*` -> `landing`; `status_tics` = `min(status_total_tics, cap)` (action progress) | the class one-hot does not separate a double jump from a fall; that is a design choice of the registered table, not an error; progress is the native tick counter of the current status | none | no |
| `rl/m7n_entity.py:187-190` | validation: `jumps_max == 2` and `jumps_max >= jumps_used` | capacity invariant; holds under up-B (equal) | none | no |
| `rl/m7h_curriculum.py:68`, `m7h_run.py:714`, `m7m_anchor.py:189`, `m7m_feasibility.py:309` | `jumps_used` is one of the fields compared for state equality of prefix / anchor tables | raw equality, no inference | none | no |
| `rl/btt_rewards.py`, `btt_reward_v3.py`, `btt_reward_t2.py`, `btt_explore_cells.py` | no use of any jump field | | none | no |
| `rl/m7g_fixture.py` (crossing evidence, route classifier), `rl/m7n_crossing.py` (qualified-crossing criterion), `rl/m7g_eval_metrics.py` | no use of any jump field (the synthetic self-test observation at `m7g_fixture.py:1001` only carries `jumps_used: 0`) | | none: `btt_qualified_crossing_v1` and every verified clear / crossing record are independent of the counter | no |
| `rl/tools/m7o_offline.py:182,350` (M7o assessment, `runs/m7o/offline/variants.json`) | "airborne, jump left" = `jumps_used < 2`, "helpless" otherwise | this **is** capacity, so the classification is right; the prose "after the double jump and the up-B" in `docs/rl_exploration_credit_m7o_assessment.md:23` describes the typical case, not a test | none on the M7o decision (its inputs are `btt_explore_cells_v1` totals and target counts) | no; one wording note recorded here |
| `docs/rl_learning_setup_review_2026-09-27.md:113` "airborne segments after a squat that used the double jump: 81 % / 69 %" | computed from a session script not kept in the repo, on `jumps_used` reaching 2 (the same inference as the census) | should read "used the double jump or an up-B" | prose measurement in a review; not a decision input; the review's recommendation (hold-k probe) did not depend on it | no code fix; correction note added below |
| `rl/tools/m7p_crossing_addendum.py:174` `double_jump_used_at` = first tick with `jumps_used >= 2` | for candidates A and B the ticks it reports (2358, 789) coincide with genuine `JumpAerialF` onsets, so the addendum's facts are right; the field name is the wrong semantics in general | analysis tool only | no; noted |
| `rl/tools/m7p_walltop_census.py:281` `double_jump` flag; `rl/tools/m7p_flight_compare.py` | true whenever `jumps_used` reaches 2, i.e. after any up-B | corrected by native status counts (13 / 74 genuine aerial jumps) in `census_correction.json` and the dated sections of both documents | analysis tools and prose of the census / comparison addenda; no decision used them | no code fix (registered outputs left as written, corrections preserved) |
| `rl/tools/m7p_counterfactual_probe.py` registration text "stick y >= 53 held" | described the Kirby / Jigglypuff rule for Mario | stick tap buffer of 3 ticks for the stick path; fresh press for the C-button path | probe design only; corrected in `probe_correction.json` and the jump-input audit | no |

**Input semantics in production.** No production code models jump inputs at all: the environment submits one native
controller state per tick and the game applies its own edge and buffer rules; the Track 1 table exposes A, B, C-up,
C-left, L, R, Z with one button per tick. Nothing in `rl/` applies a held-input rule to Mario, and nothing conflates a
fresh C-button press with the stick's tap buffer, because nothing interprets inputs. The C buttons are already in the
contract; no action-space change is proposed.

**Observation semantics (v3), for the record.** The agent block exposes `jumps_left` (capacity fraction as above),
`status_id` (raw id / scale), `status_tics` (progress of the current status, capped), `hitlag`, the flags
`attack_active`, `cliff_hold`, `shield_active`, `fastfall`, `grounded` and the four contact bits, plus the 20-class
action one-hot. It does not expose "can jump on this tick", the tap-buffer state, the button-edge state, or whether the
last jump was a double jump or an up-B consumption. Those are absent, not wrong.

## 2. Impact

- **Training, evaluation, registered decisions: no defect.** No observation feature, reward, curriculum, verifier or
  decision rule infers a double jump from the counter. `jumps_left` is a correct capacity feature. M7n, M7o, M7p and the
  qualified-crossing verifications stand as recorded.
- **Analysis tools and prose: three items corrected or annotated.** The census / flight-comparison double-jump counts
  (corrected 2026-09-28), the counterfactual registration's jump rule (corrected), and the learning-setup review's
  "used the double jump" row (annotated here: read as "double jump or up-B"; the script is not in the repo so the row
  cannot be recomputed without a new replay, which is not done). The M7o assessment sentence is a wording note only.
- **Historical conclusions needing correction:** only the three prose items above. No milestone is reopened.

**No production defect exists; no fix is proposed.**
