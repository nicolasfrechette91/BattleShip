# M8 continuation: selection `m8_rd_select_v2`, resuming the rd1 archive, and the registered rule for M8-rd2 (proposal, 2026-10-02)

**Status: design only.** No native process was launched and no native tick was consumed. Nothing was trained, committed, pushed or
branched, and no existing file was edited. The rd1 archive under `runs/m8_rd/` was only read: its manifest verified on load, and it
still holds 166 files. The figures below come from scratch scripts outside the repository (appendix A). They read the rd1 archive and
ledger and import the pure modules `rl/m8_rd_archive.py` and `rl/m8_rd_cells.py` with bytecode writing disabled. This document is
the only file added.

Inputs: `docs/rl_m8_rd_proposal_2026-10-01.md` (revision 2), `docs/rl_m8_rd_amendment_2026-10-02.md`,
`docs/rl_m8_rd_implementation.md`, `docs/rl_m8_rd1_results_2026-10-02.md`, `docs/rl_m8_rd1_diagnosis_2026-10-02.md`,
`docs/rl_mechanics_observation_audit_2026-09-28.md`, the external guide `..\guide.md` (sections 2, 10, 12) and `CLAUDE.md`.

## Short answer

1. **A new rd1 fact: returns from below the floor were all fatal.** The diagnosis did not tabulate return outcomes.
   - 456 returns started below the main floor. **409 ended in a fall and none touched the ground.**
   - All 480 falls in arm T came from bursts that never touched the ground.
   - By the time `m8_rd_select_v1` chose them, **371 of its 2,175 returns (17.1 %)** went to cells where every observed
     continuation had already fallen without landing.

   The dilution is therefore a **feasibility** failure (returning to states with no observed or physical recovery) rather than a
   preference failure.
2. **`m8_rd_select_v2` keeps preference position-blind and adds two feasibility exclusions** (section 2). It has four stage-agnostic
   parts, with every parameter fixed in advance:
   - **(a) Descent doom.** An airborne cell is ineligible while every observed continuation of its trajectory ended in a native
     fall and none reached a grounded tick. This replaces the 60-tick window and is revisable.
   - **(b) A recovery bound.** An airborne cell is ineligible when even the character's maximal rise cannot bring it above the
     lowest floor line of the stage's native table. For Mario this is double jump, tornado and up-B: an upper bound plus a
     300-unit margin, falsified live if ever wrong.
   - **(c) A resource weight.** The weight is 1, 1, ½ and ¼ for grounded, A2, A1 and A0.
   - **(d) A harmonic level weight**, 1/(1 + top − level), in place of 2^−(top − level).

   Novelty, the prefix-length factor, the cell key `m8_rd_cell_v1`, the explorer `m8_rd_explore_v1` and the burst length are
   unchanged.
3. **Estimates on the rd1 ledger** (analytic selection mass at each of rd1's 2,175 dispatches over the archive of that moment).
   These are first-order estimates, not predictions of success:

   | dispatch share | rd1 (realized) | v2 (estimate) |
   | --- | ---: | ---: |
   | starts below the floor | 21.0 % | **5.0 %** |
   | grounded starts | 4.4 % | 9.2 % |
   | starts in contact with the raised step | 0.55 % | 1.33 % |
   | A2/A1 starts on stage at y ≥ 0 | 4.4 % | 7.4 % |
   | A2 starts at y ≥ 0 | 1.4 % | 3.7 % |
   | starts with no resource left (A0) | 41.7 % | 15.7 % |
   | on-stage share (y ≥ 0) | 12.2 % | 11.5 % (A0-heavy, see 2.4) |
   | **launch-capable starts** | **0.09 %** | **0.14 %** |

   - With rd1's per-class productivity, about **1.6×** more launch-capable cells would be created per return (16.6 → 26.8 over
     2,175 returns).
   - Returns that fall without landing would drop from about 497 to 111 (497 is the estimate's own v1 value; rd1 had 480).
   - **Selection cannot make rare states common.** Only 14 launch-capable cells existed in rd1. v2 removes the waste; whether that
     is enough is what rd2 measures.
4. **Resume** (section 3). The archive `m8_rd_a1` continues under the unchanged key.
   - rd2 writes only to a new sibling directory, `runs/m8_rd_rd2/`.
   - rd1's tree must stay byte-identical to its D: increment `2026-10-02_incr_m8_rd1` (manifest `e81226d7…`), checked at the open
     and at the close.
   - The ledger is verified by a zero-tick rebuild under v1. rd2's copy of the ledger must begin with rd1's exact bytes.
   - P1 and 16 open identity replays run before exploration. Iterations continue at 2,175.
   - rd1 cells are never edited. Their v2 flags are a derived overlay, stored with a digest at the open.
   - No native re-verification is needed: the executable is unchanged (`30a3913b…`), so decision 11 does not trigger.
5. **Rule `m8_rd2_rule_v1`** (section 4). There is no control arm and the rule is milestone-only.
   - The milestones, each verified by a full replay from tick 0, are: wall-top landing < qualified crossing < left target <
     clear.
   - **Progress** is any verified milestone.
   - A NO_MILESTONE result is labelled DILUTION_REDUCED or DILUTION_PERSISTS. The thresholds are registered: below-floor share
     ≤ 10.5 % and fatal-return share ≤ 11.0 %, half of rd1's values.
   - Nine registered diagnostics are comparable to the rd1 diagnosis.
   - Seven stop conditions are registered, including two new ones: v2 failing its own mechanism, and a falsified recovery bound.
6. **Caps** (section 5). Exploration 50 min or 6,000,000 native ticks, valid from 2,000,000. Open phase 70,000 ticks / 4 min;
   verification 400,000 ticks / 6 min; session hard cap 60 min from P1. Memory caps as rd1. Expected: about 4.7 M ticks and
   about 4,200 returns at rd1's measured 1,560 ticks/s.
7. **Integrity** is as strong as rd1's (section 6):
   - an approval record, a source snapshot and D: increments;
   - identity replays at the open and at the close;
   - the four-way check at every return (tick-0 record, per-tick consumed and input ticks, end record, chain digest);
   - full-replay claims, and any mismatch INVALID.

   Added: rd1 immutability and the ledger prefix property.
8. **Generality** (section 7). Parts (a), (c) and (d) need nothing beyond the character's resource classes. Part (b) needs
   per-character rise constants, or it is switched off. The constant-free variant gives below-floor 9.2 % and launch-capable
   0.12 % on the same estimate.

## 0. Verified state

| item | state |
| --- | --- |
| checkout | `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, branch `main`, `HEAD` = `origin/main` = `e56b41f` (the diagnosis commit); working tree clean before this file |
| executable and runtime files | sha256 (prefixes) `BattleShip.exe 30a3913b32c44353…` (written 2026-09-28), `BattleShip.o2r fe2b307e…`, `f3d.o2r 73ab91ef…`, `gamecontrollerdb.txt 9d3c6b8d…`; frozen `BattleShip.cfg.json 1b29d91b…`, `imgui.ini 0d267321…`. Every one equals the archive pin. Hashed as files, nothing run |
| rd1 archive | `runs/m8_rd/archive`, id `m8_rd_a1`, checkpoint sequence 7, manifest verified on load; 8,264 cells, 2,175 bursts, 4,350 events; dispatch iterations 0..2,174 contiguous, no `fail` events; select digest `e6945dfe…`, cell `a1187d55…`, explore `d7d3c9ae…`, claims `3dbd7da5…`, Track 1 `aab45c26…`, status table `070d6b8f…`; tick-0 pin `2817d8cf…`, line table `c251d89a…` |
| rd1 D: increment | `D:\BattleShip_runs_backup\2026-10-02_incr_m8_rd1\verification.json`: `PASS`, 166 files, 62,448,635 bytes, manifest `e81226d7f36a28a0…` |
| rebuild | the instrumented ledger replay (appendix A) re-derived every one of the 2,175 selections and reproduced all 8,264 cells exactly, as the close audit did |
| not read or used | crossing fixtures, capture recordings, `tas_input_2/`, any `.btti` file, anything derived from them; no RNG state anywhere |

## 1. What rd1 left, including new readings from its ledger

The rd1 results and diagnosis are not repeated here, apart from the figures v2 is designed against. Three readings are new.

**1.1 Return outcomes by start region.** Regions are the diagnosis's, by the start cell's stored position at dispatch time. Here
"touched ground" means the burst has a grounded live reach.

| start region | returns | ended in a fall | touched ground | new cells per return |
| --- | ---: | ---: | ---: | ---: |
| below the main floor (y < −2,850) | 456 | **409** | **0** | 4.2 |
| beside the stage (x > 3,600) | 180 | 47 | 7 | 8.7 |
| on stage, low (−2,850 ≤ y < 0) | 1,274 | 24 | 1,156 | 2.9 |
| on stage, high (y ≥ 0) | 265 | 0 | 222 | 3.9 |
| **all** | **2,175** | **480 (22.1 %)** | 1,385 | 3.8 |

- **All 480 falls came from bursts that never touched the ground.**
- Falls are prolific in new cells: falling through fresh bins creates them, and those cells are then novel and eligible.
- The 60-tick doom window only flagged the last two seconds of each descent. That feedback loop is the dilution.

**1.2 Selection mass on states already known to be lost.**
- **Fatal by the time of selection.** At the moment of dispatch, 371 of v1's returns (17.1 %; analytic mass 400.7) went to cells
  where every observed continuation had fallen and none had landed.
- **Physically unrecoverable.** 284 of v1's returns (13.1 %; analytic 293.3) went to cells that the recovery bound of
  section 2.2 calls unrecoverable.

**1.3 The recovery bound against rd1's own data.**
- rd1 stored 5,161 reaches below the lowest floor line (y < −2,550): A2 241, A1 2,238, A0 2,682.
- **None was followed by a grounded reach in the same burst.**
- The smallest bound margin of any reach that was later followed by a landing is A2 4,639, A1 3,436 and A0 7.8. The A0 case is a
  helpless state just above the floor.

Nothing in rd1 contradicts the bound, and nothing tested it near its edge. The live falsification check in section 2.2 covers that.

## 2. Item 1: selection `m8_rd_select_v2`

### 2.1 Principle

v1 used one position-blind score for everything. v2 separates two questions:

- **Feasibility** (exclusion). Can this state still lead anywhere at all? It is answered only from native facts:
  - the native fall (`btt_native_failure_v1`);
  - grounded live ticks (`ground_air_state`);
  - the stage's native collision-line table;
  - the character's resource classes.
- **Preference** (weighting among feasible states). This stays **position-blind**: progress level, novelty, prefix length and
  remaining movement resources. There is no position term, distance term or surface term.

Under this split, an exclusion is acceptable only if it is a statement about recoverability that holds for every stage. A
preference is acceptable only if it never reads where the character is.

### 2.2 Candidate rules (all evaluated in 2.4)

| id | rule | inputs | status |
| --- | --- | --- | --- |
| R1a | **burst-local fatal**: an airborne reach is doomed if its own burst fell with no grounded tick after it (the v1 window widened to the whole tail) | the native fall, grounded ticks | evaluated, superseded by R1b (most falling cells were created by bursts that ended by length before the fall) |
| **R1b** | **descent doom**: an airborne reach (b, o) is doomed iff (i) no observed continuation of its trajectory reached a grounded live tick, and (ii) at least one ended in a native fall. Continuations are the rest of burst b after o and, recursively, every later burst started from a representative (b, o′) with o′ ≥ o. No completed continuation means pending, not doomed. A later landing clears the doom | the native fall, grounded ticks, the burst tree | **adopted** |
| R1b′ | R1b for A0 only | as R1b | evaluated, rejected (keeps 18.8 % below the floor) |
| R1b″ | R1b with an evidence count by class: 1 fatal continuation for A0, 2 for A1, 3 for A2 | as R1b | evaluated, rejected. It protects 2 more on-stage A2/A1 cells (22 → 20 doomed) but keeps 285 more below-floor cells eligible |
| **R1c** | **recovery bound**: an airborne cell is ineligible iff y + R_class(v_y, status) + 300 < Y_floor_min. Y_floor_min is the lowest vertex of **every** floor-type line in the native line table at tick 0 (a moving group counts at its lowest recorded position). R_class is the character's maximal rise from that resource class, an upper bound (Mario below). The bound never looks at x | the native line table, the cell's own y and v_y, the status class, per-character constants | **adopted**, with a live falsification flag |
| R1c′ | R1c with the tornado term dropped | | **rejected as unsafe.** It looks better on Mario's numbers (6.4 % below the floor), but it is not an upper bound |
| R1d | per-cell outcome discount (1 + landed) / (1 + landed + fell) over the returns from that cell | outcomes of returns | evaluated, rejected: no effect (0.25 returns per cell) |
| **R2** | **resource weight** w_res = 2^−(r_max − r): r counts the character's available movement resources (Mario: G and A2 have both the aerial jump and the up-B, r = 2; A1, r = 1; A0, r = 0), giving 1, 1, ½, ¼ | the key's resource class | **adopted** |
| **R3a** | **harmonic level weight** ∝ 1/(1 + ℓ* − ℓ) over the levels that have eligible cells | targets broken | **adopted** |
| R3b, R3c | ½ v1 + ½ uniform over levels; uniform over levels | targets broken | evaluated; flat gives the top level only 3.6 %, which starves the most advanced lineage |
| R4 | projection novelty: `seen` summed over cells that share (bx, by, class) across masks | visit counts | evaluated, rejected: no effect (visit counts are low everywhere) |
| X1 | **one-target exception**: a cell with exactly one live target is exempt from every doom and bound exclusion, because a clear can complete during a fatal descent | targets count | **adopted** (no rd1 cell is affected; maximum level 7) |

**Mario's rise bound (R1c).** All values are upper bounds. They come from decomp attribute and motion data and from agent flights,
never from the TAS or human recordings:

| term | value | derivation |
| --- | ---: | --- |
| ballistic rise B(v) | max(v,0)²/(2·2.4) + max(v,0) | `gravity 2.4` (`decomp/src/relocData/203_MarioMain.c`), the discrete sum bounded from above |
| aerial jump J | 1,171.8 | v₀ = (80·0.7 + 26)·0.9 = 73.8 (`jump_height_mul`, `jump_height_base`, `jumpaerial_height`; `ftcommonjumpaerial.c:162`) |
| up-B U | 1,361.3 | fixed animation-driven rise, which the stick cannot increase (`docs/rl_m8_rd_proposal_2026-10-01.md` §2, measured on M7p agent flights) |
| tornado T | 2,073.3 | 43-tick rise window (`202_MarioMainMotion.c`, air script: Wait 4 + 13 × 3) at the 40/tick cap (`FTMARIO_TORNADO_VEL_Y_CLAMP`), plus the ballistic rise from 40. **Assumed unspent**, because the observation does not expose `is_expend_tornado` |
| class bounds | A2: B + T + J + U; A1: B + T + U; A0 in up-B (status 225/226): B + U; A0 helpless (58): B | |
| stage | Y_floor_min = −2,550 (line 4 of the pinned table; the moving floor's lowest standable y is 1,800) | `rl/m7g_spatial.EXPECTED_LINES` = the native table |

**Falsification.** If an rd2 burst has a grounded live tick after a reach that the bound marks unrecoverable, the session records
`BOUND_VIOLATION`. This is stop condition S5. The session's trajectories stay exact and its result stands, but v2 may not be reused
unchanged.

### 2.3 How the estimates were made

The scratch scripts replay rd1's ordered ledger over its stored bursts (the close audit's procedure) and reproduce every selection.
**Immediately before each of the 2,175 dispatches**, they compute the analytic per-cell selection probability of each rule over the
archive as it stood at that moment, using only the evidence available then (causal). Then they add up the mass in each category.
The v1 row matches what rd1 actually did (21.9 % against 21.0 % below the floor; 12.2 % against 12.2 % on stage high), which
validates the method.

**Limits.** These are first-order estimates.
- Different selections would have produced different bursts and a different archive. The feedback is not modelled.
- The productivity estimate in 2.4(c) multiplies v2's mass by rd1's realized per-start-class yields. Those yields rest on few events
  (16 launch-capable creations in total).
- Mario-specific categories (step contact, launch-capable, the regions) appear as **reported columns**. No parameter was searched
  to improve them. R1c′ is rejected even though it scores better on them.

### 2.4 Estimates

**(a) Dispatch shares** (% of rd1's 2,175 dispatches; analytic mass at each dispatch).
- *launch* = A2/A1 at y ≥ 1,639.
- *A2/A1 hi* = A2/A1 on stage at y ≥ 0.
- *step* = grounded on floor line 1.

| rule set | below floor | beside | on-stage low | on-stage high | step | grounded | A2+A1 | A2/A1 hi | A2 y ≥ 0 | launch | A0 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rd1 realized | 20.97 | 8.28 | 58.57 | 12.18 | 0.55 | 4.41 | 53.89 | 4.41 | 1.38 | 0.09 | 41.70 |
| v1 analytic | 21.94 | 7.59 | 58.30 | 12.17 | 0.54 | 4.29 | 55.15 | 4.87 | 1.41 | 0.10 | 40.55 |
| R1a burst-local fatal | 19.70 | 7.91 | 59.69 | 12.70 | 0.56 | 4.37 | 55.52 | 5.12 | 1.49 | 0.11 | 40.11 |
| R1b descent doom | 14.15 | 5.65 | 65.48 | 14.72 | 0.70 | 4.82 | 56.99 | 6.20 | 1.93 | 0.15 | 38.19 |
| R1b′ descent doom, A0 only | 18.77 | 6.76 | 61.27 | 13.20 | 0.61 | 4.53 | 61.43 | 5.62 | 1.68 | 0.12 | 34.04 |
| R1c recovery bound | 11.21 | 9.84 | 64.59 | 14.36 | 0.65 | 4.64 | 59.39 | 5.93 | 1.77 | 0.13 | 35.97 |
| R1c′ bound without tornado (unsafe) | 6.44 | 10.95 | 67.27 | 15.34 | 0.69 | 4.79 | 57.10 | 6.41 | 1.93 | 0.14 | 38.11 |
| R1d per-cell outcome | 21.31 | 7.65 | 58.69 | 12.35 | 0.55 | 4.32 | 55.26 | 4.95 | 1.44 | 0.10 | 40.42 |
| R1b + R1c | 6.10 | 6.79 | 70.52 | 16.59 | 0.79 | 5.13 | 59.81 | 7.12 | 2.28 | 0.18 | 35.06 |
| R2 resource weight | 18.17 | 7.36 | 64.56 | 9.92 | 1.13 | 7.60 | 72.03 | 6.19 | 2.89 | 0.11 | 20.36 |
| R3a harmonic | 18.27 | 6.90 | 63.17 | 11.66 | 0.51 | 4.63 | 56.12 | 4.64 | 1.39 | 0.09 | 39.25 |
| R3b mix | 17.00 | 6.67 | 64.69 | 11.65 | 0.50 | 4.69 | 56.48 | 4.64 | 1.40 | 0.09 | 38.83 |
| R3c flat | 12.05 | 5.76 | 71.07 | 11.12 | 0.45 | 5.08 | 57.81 | 4.41 | 1.40 | 0.08 | 37.11 |
| R4 projection novelty | 22.77 | 7.89 | 56.82 | 12.52 | 0.53 | 4.18 | 55.18 | 4.97 | 1.46 | 0.11 | 40.64 |
| R1b + R2 (v1 levels) | 11.09 | 5.68 | 71.50 | 11.73 | 1.37 | 8.44 | 73.26 | 7.53 | 3.68 | 0.15 | 18.30 |
| **M1** = R1b + R2 + R3a (no character constants) | 9.22 | 5.14 | 74.93 | 10.72 | 1.24 | 8.87 | 73.65 | 6.86 | 3.36 | 0.12 | 17.48 |
| **v2** = R1b + R1c + R2 + R3a | **4.98** | 5.66 | 77.86 | 11.50 | **1.33** | **9.17** | 75.11 | **7.41** | **3.66** | **0.14** | **15.72** |

**Reading.**
- R1b and R1c are the levers on the dilution.
- R2 moves mass from resource-less to resource-rich states. It doubles the step-contact, A2-high and grounded shares.
- R3a softens the level priority at small cost.
- R1d and R4 do nothing measurable and are dropped for simplicity.
- **The on-stage-high share does not rise under v2** (12.2 → 11.5 %). Most high cells are A0 states after an up-B, with nothing
  left but drift, so R2 trades them for A2/A1 states. The on-stage share alone is therefore a poor dilution measure, and the
  registered diagnostics in section 4 split it by resource class.

**(b) Level distribution of dispatch mass** (levels 0..7, %): v1 2.1 / 3.8 / 6.6 / 9.0 / 15.0 / 16.6 / 32.4 / 14.4; v2 (harmonic)
6.7 / 8.1 / 10.3 / 11.2 / 14.9 / 13.5 / 24.6 / 10.6. Lower-target lineages keep about twice their v1 mass. The top level keeps the
largest single share while it is the top.

**(c) First-order productivity.** rd1's realized yields per start class (resource class × region) are multiplied by each rule's
mass. The v1 row reproduces rd1: 8,220 new cells predicted against 8,263 actual, and 497 fatal returns predicted against 480 actual.

| per 2,175 returns | new cells | new launch-capable cells | new A2/A1 cells on stage, y ≥ 0 | new A2 cells, y ≥ 0 | new step-contact cells | returns that fell without landing |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| v1 | 8,220 | 16.6 | 413 | 105 | 32.4 | 497 |
| M1 | 8,520 | 25.1 | 646 | 157 | 47.3 | 196 |
| **v2** | 8,572 | **26.8** | **686** | **166** | **49.3** | **111** |

The yields behind this are thin but telling. A2 returns on stage at y ≥ 0 produced 5 launch-capable cells in 27 returns (0.19 per
return). A1 returns there produced 4 in 69. The 636 returns from below or beside the stage produced none. v2 raises the A2-high mass
from 26 to 68 dispatch-equivalents.

**(d) What v2 would exclude from the rd1 archive at the rd2 open** (final rd1 state, 6,960 v1-eligible cells):
- **Descent doom: 1,905** (below the floor 1,307, beside 424, on-stage low 129, on-stage high 45). This includes 22 of the 403
  A2/A1 cells on stage at y ≥ 0 and 8 of the 133 A2 cells at y ≥ 0. It includes no launch-capable and no grounded cell.
- **Recovery bound: 1,309.** All are below the main floor: A1 361, A0 948, A2 0.
- **Union 2,454, leaving 4,506 eligible.** All 14 launch-capable, all 32 step-contact and all 201 grounded cells stay eligible.
- Of the 3,524 below-floor cells, v1 flagged 1,304. Descent doom raises that to 2,611, and the bound to 3,160.

**(e) Plain statement.** The estimate says v2 removes most of the waste: below-floor starts fall from about 22 % to 5 %, and fatal
returns from about 23 % to 5 % of returns. It roughly doubles returns from resource-rich states. **It does not make
launch-capable states common**: 0.14 % of returns is about 6 of rd2's expected 4,200. Only feedback can change that, through more
returns from A2-high and step states creating more launch-capable cells (the 1.6× first-order figure). That is the question rd2's
diagnostics answer.

### 2.5 The rule set `m8_rd_select_v2` (every parameter fixed here)

**Eligibility.** Cell 0 is always eligible. Any other cell c is eligible iff all of the following hold:
- E1: its class is not X;
- E2: its representative did not end the episode at L (not terminal);
- E3: L ≤ 3,480;
- E4: it is not doomed under v1 (the stored 60-tick flag, never rewritten);
- **E5**: it is not descent-doomed (R1b; grounded cells are never descent-doomed);
- **E6**: it is not bound-unrecoverable (R1c; only when the character has a registered bound).

Exception X1: a cell with exactly one live target is exempt from E4–E6.

**Level.** ℓ(c) = targets broken. Draw a level ∝ 1/(1 + ℓ* − ℓ) over the levels with eligible cells, where ℓ* is the top such
level.

**Cell within the level.** w(c) = w_nov(c) · w_len(c) · w_res(c):
- w_nov = 1/√(1 + chosen) + 1/√(1 + seen), as in v1;
- w_len = 900 / (900 + L − L_min(ℓ)), with L_min taken over the **v2-eligible** cells of the level;
- w_res = 1 (G), 1 (A2), ½ (A1), ¼ (A0).

**Replacement.**
- v1's rule, with doom := E4 ∪ E5 ∪ E6 evaluated at the time of the reach: a non-doomed reach beats a doomed one, then the strictly
  shorter L wins, and ties keep the incumbent.
- A new reach's descent doom is known only from its own burst. A reach whose burst ended by length is pending, so it can replace a
  doomed incumbent.
- This lets a key recover from a fatal first representative (open question 2).

**Draws.**
- Two uniforms from sha256(`m8_rd|m8_rd_a1|select|<iteration>`), with the same key form and the same cell order as v1.
- Iterations continue from 2,175 and are never reused.

**Evidence representation.**
- Descent doom is a deterministic function of the stored bursts. It is maintained incrementally at ingest by propagating up the
  burst tree, not recomputed per dispatch. The whole scratch loop (a full recompute plus eight rule sets) averaged under 9 ms
  per dispatch at up to 2,175 bursts, against v1's 1.2 ms selection.
- **The grounded evidence of an rd1 burst is its grounded reaches.** These are first visits of a key within the burst, so a
  re-landing on a key already visited in the same burst is not recorded.
  - For rd1 this is exact where it matters for exclusion: none of rd1's 480 falling bursts touched the ground at all.
  - It can under-report a recovery inside a non-falling burst that has fatal children.
- rd2 bursts store their grounded runs exactly (a new burst field, `ground_runs`; open question 5).

**Contract digest.** The digest covers:
- every rule and constant above;
- the status-class table digest;
- the pinned line-table digest (`c251d89a…`), from which Y_floor_min is derived;
- the derivation of the Mario constants;
- the one-target exception.

### 2.6 Why no rule is a route hint, and why each applies unchanged to any Break the Targets stage

| rule | reads | never reads | why it is not a route hint |
| --- | --- | --- | --- |
| E5 descent doom | native falls; grounded live ticks; the burst tree of the archive's own trajectories | position, surfaces, targets | It says only that, on the evidence, this state did not recover. Any stage has falls and floors |
| E6 recovery bound | the lowest point of **all** floor lines in the native table; the cell's own y and v_y; the character's rise constants | x, any specific line, the wall, the ledge, targets, direction | It is a necessary condition for landing anywhere: no floor is reachable from below its height. It excludes; it never adds weight to any place. On another stage it reads that stage's table |
| R2 resource weight | the key's resource class | position | It prefers states with more remaining movement options, wherever they are. On another stage the same weight favours the same kind of state |
| R3a harmonic level | targets broken (the task objective) | which targets, where | The same formula on any stage |
| X1 one-target exception | targets count | anything else | Generic |
| unchanged parts | novelty counts, prefix length, keyed draws | | as in v1 |

**Explicitly absent:**
- position targets;
- wall-, ledge-, step- or target-specific weights;
- hand-placed waypoints;
- height or distance preferences. A continuous "recovery margin" weight was considered and rejected, because it would prefer height
  everywhere;
- anything derived from human recordings, crossing fixtures or the TAS. The constants come from decomp attribute and motion data
  and from agent-generated M7p flights.

The Mario-specific categories in 2.4 are analysis readings only. No selection code reads them.

### 2.7 What v2 does not change

- The cell key `m8_rd_cell_v1`: 300-unit bins, resource class, full mask, floor, no velocity.
- The explorer `m8_rd_explore_v1`: 72 words, hold lengths {1, 2, 4, 8, 16}, 120-word bursts, the same keys.
- The horizon of 3,600.
- The candidate labels and claim verification (`m8_rd_claims_v1`).
- The Track 1 table.
- The replay-truth contract.

Prefix replay stays near 90 % of ticks. This is accepted to keep one variable changed at a time (open question 8).

## 3. Item 2: resuming the rd1 archive

### 3.1 Layout

| path | owner | access in rd2 |
| --- | --- | --- |
| `runs/m8_rd/` (166 files: `archive/`, `archive.prev/`, `sessions/rd1/`, `routes/`, `launch/`) | rd1 | **read-only**. Never opened for writing; must remain byte-identical to `2026-10-02_incr_m8_rd1`. The frozen runtime (`archive/runtime/`: cfg, imgui, the preserved executable) is read in place and hashed, never re-frozen from the live configuration |
| `runs/m8_rd_rd2/archive/`, `archive.prev/` | rd2 | rd2's materialised checkpoints, schema `m8_rd_archive_v2` |
| `runs/m8_rd_rd2/derived/open_overlay.jsonl` + digest | rd2 | the v2 flags of every rd1 cell at the open |
| `runs/m8_rd_rd2/sessions/rd2/` | rd2 | open, P1, identity, iterations, candidates, memory, verification, rule, close |
| `runs/m8_rd_rd2/routes/` | rd2 | verified claims (M4 form + full trace) |

A later rd3 would read rd2's closed checkpoint as its base and write `runs/m8_rd_rd3/`. Each session directory is immutable after
its close.

### 3.2 The resume protocol (S0-resume and P1, before any exploration)

| step | check (zero native ticks unless stated) | on failure |
| --- | --- | --- |
| R0 | `HEAD` and the tracked tree equal the approved state; the source snapshot `<date>_m8_rd2` verifies (tool and independent re-hash); the approval `docs/rl_m8_rd2_approval.json` matches the fresh identity | refuse |
| R1 | **rd1 immutability**: `runs/m8_rd/` holds exactly rd1's 166 files, each byte-identical to the D: increment (tool `verify` and an independent PowerShell re-hash); combined `runs/` coverage 0 uncovered; `runs/m8_rd_rd2/` absent | refuse |
| R2 | `Archive.read_files(runs/m8_rd/archive)` (manifest verified); `load_latest_verified` returns sequence 7 (prev 6); the manifest equals rd1's close record and `archive_meta.json`; 8,264 / 2,175 / 4,350 | refuse |
| R3 | pins: executable `30a3913b…`, `.o2r` files, `gamecontrollerdb.txt`, frozen cfg and imgui, flags (explore: NO_RENDER, RAPHNET_DISABLE, SPATIAL; verify: all four diagnostics), Track 1, status table, cell, explore and claims digests, tick-0 pin and line table. **If only the executable differs**, this is not an exploration session: decision 11's full re-verification of every carried cell runs as its own authorised session (`m8_rd_session.py reverify` semantics), and any mismatch stops it for review. Any other drift is a refusal | refuse / re-verify |
| R4 | `audit(rd1)`: the ledger under `m8_rd_select_v1` rebuilds every cell byte for byte; every prefix reconstructs; every lineage reaches cell 0 | refuse |
| R5 | **v2 open overlay**: E4–E6 and w_res for every rd1 cell, with reason codes (`x`, `terminal`, `horizon`, `doom60`, `descent`, `bound`), stored with its sha256; computed twice and equal. The expected counts are those of 2.4(d): 6,960 → 4,506 eligible | refuse |
| R6 | **materialise** `runs/m8_rd_rd2/archive/`: rd1's five data files copied byte for byte (hashes equal to the originals), then a `session` event `{name: rd2, select: m8_rd_select_v2, digest, first_iteration: 2175}`; meta records the **base** (rd1 path, checkpoint 7, rd1 manifest sha256, close-record sha256, D: manifest `e81226d7…`) | refuse |
| R7 | **P1** (native, as rd1): the tick-0 record from two processes (cold and standby-promoted) equals the archive's `pin_tick0`; the two pinned Track 1 traces word for word; the return self-test in a scratch archive, including the refused corrupted end record | INVALID |
| R8 | **open identity replays, K = 16** (native): returns of rd1 cells with the four checks (tick-0 record; every word's consumed tick = i, input tick = i + 1, state, no end and no fall; the end record and record digest; the chain digest). Sample: the shortest cell of each of the top three levels (3); the four highest-weight v2-eligible cells at the open (4); four keyed-random cells among the launch-capable and A2-at-y ≥ 0 cells (4); five keyed-random v2-eligible cells (5). Keys `m8_rd|m8_rd_a1|identity_open|rd2|<cell id>` | INVALID |
| R9 | exploration begins at iteration 2,175 (rd1's range 0..2,174 is proved by the ledger) | |

**During rd2.**
- rd1 cells may be selected. Their counters change and their representatives may be replaced, **in rd2's archive only**.
- No rd2 code path writes under `runs/m8_rd/`. A static guard test enforces this, and R1 is repeated at the close.

**At the close.** The close audit adds three checks to rd1's:
- the **prefix property**: the first 4,350 events, the first 2,175 bursts and the first 2,175 index rows of rd2's files are
  byte-identical to rd1's;
- the rebuild of rd1's part under v1 and of rd2's part under v2 reproduces rd2's saved cells;
- R1 again.

**A crashed rd2** is INCOMPLETE. A later session may resume only from rd2's last verified checkpoint, after the full protocol and
under a new approval.

### 3.3 rd1 cells under v2: re-scored or excluded?

- **Nothing is re-scored in place.**
  - v2's flags and weights are a function of stored data, recomputed as the archive evolves.
  - The open overlay records their values at the open, with a digest, for audit.
  - rd1's `doomed` field keeps its v1 meaning (E4).
- **2,454 rd1 cells become ineligible at the open:** descent 1,905 and bound 1,309, overlapping. They stay in the archive (coverage,
  lineage, counts) and are never deleted.
  - A descent-doomed cell becomes eligible again if a landing continuation is observed.
  - Any excluded cell can return through replacement by a non-doomed reach.
- **No rd1 cell needs native re-verification**, because decision 11 is not triggered. The 16 open identity replays sample the
  archive on the live executable.
- rd1's arm-C coverage set is not used by rd2.

## 4. Item 3: the registered rule `m8_rd2_rule_v1` (no control arm)

**Scope label**, carried by every rd2 record: *continuation of archive `m8_rd_a1` under `m8_rd_select_v2`; one session, one set of
keyed draws; no control arm; not a policy result, not a learning result, not a comparison of v2 with v1.*

### 4.1 Milestones (unchanged predicates and analysers)

| m | milestone | predicate, re-derived on a fresh-process replay from tick 0 with all four diagnostics, every raw reply kept |
| ---: | --- | --- |
| 1 | wall-top landing | a grounded live tick on floor line 0 |
| 2 | qualified crossing | `btt_qualified_crossing_v1` (`rl/m7n_crossing.py`, unchanged) |
| 3 | left target | target 1, 6 or 8 broken |
| 4 | clear | the M7d four facts (end reason clear, cleared flag, ten broken, completion clock); `completion_time_passed` and `completion_input_tick` reported separately |

A replay counts only if all of these agree: the native action digest, every consumed tick, the break table, the claimed event tick,
and the predicate from the registered analyser. **An inexact replay is INVALID.**

m(rd2) is the highest milestone held by a verified trajectory whose qualifying event lies in a burst ingested during rd2. rd1 holds
none.

Candidates are labelled online as in rd1. Verification runs the max-t candidate first, then each unsatisfied milestone round-robin
in discovery order until one qualifies. At most three replays run at a time, capped at 400,000 ticks and 6 min.

### 4.2 Outcome table (evaluated in this order; disjoint and exhaustive)

| outcome | condition |
| --- | --- |
| **INVALID** | any rd1 integrity failure (tick-0, prefix, end-record or chain mismatch; consumed-tick violation; inexact claim replay; provenance or static-guard violation; pin drift; any read of fixtures or the TAS), **or** any change under `runs/m8_rd/`, a prefix-property failure, or an open overlay that does not reproduce |
| **INCOMPLETE** | exploration below 2,000,000 native ticks; a hard stop (memory, process count, session cap, worker error, more than 3 lifecycle failures); the open phase not completed; a candidate that could raise m left unverified at the replay cap |
| **PROGRESS_CLEAR** | m = 4 |
| **PROGRESS_LEFT_TARGET** | m = 3 |
| **PROGRESS_CROSSING** | m = 2 |
| **PROGRESS_WALL_TOP** | m = 1 |
| **NO_MILESTONE / DILUTION_REDUCED** | m = 0, and both (a) the share of rd2 dispatches starting below the main floor (y < −2,850) is ≤ 10.5 %, and (b) the share of rd2 returns ending in a native fall with no grounded tick is ≤ 11.0 % |
| **NO_MILESTONE / DILUTION_PERSISTS** | m = 0 otherwise |

The thresholds are half of rd1's realized values (20.97 % and 22.07 %). v2's estimate is about 5 % for both.
`BOUND_VIOLATION` is an orthogonal flag, recorded with any outcome. The dilution verdict is reported with every outcome; it decides
only the stop path.

**Progress** means a verified milestone, and nothing else. The following are reported, never progress:
- a higher maximum target count;
- more launch-capable cells;
- a closer approach.

**What a PROGRESS outcome does not say.** Without a control arm it cannot attribute the milestone to v2 rather than to more returns.

### 4.3 Registered diagnostics (always reported; comparable to the rd1 diagnosis)

| # | measure | method | rd1 reference |
| ---: | --- | --- | --- |
| D1 | start-region shares of rd2's dispatches: below the floor (y < −2,850), beside (x > 3,600), on-stage low, on-stage high (y ≥ 0); also left of the wall (x < −2,100) | start cell's stored position at dispatch | 20.97 / 8.28 / 58.57 / 12.18 %; left 0 |
| D2 | step contact: dispatches from cells grounded on floor line 1; number of such cells | key | 12 (0.55 %); 32 cells |
| D3 | dispatches by resource class G / A2 / A1 / A0; A2/A1 on stage at y ≥ 0; A2 at y ≥ 0 | key + position | 4.41 / 18.76 / 35.13 / 41.70 %; 96 (4.41 %); 30 (1.38 %) |
| D4 | airborne-with-resources supply in the archive: A2/A1 cells; those on stage at y ≥ 0; launch-capable (A2/A1, y ≥ 1,639) and their dispatches; launch-capable at x ≤ 600; highest A2 y; launch-capable cells **created per 1,000 returns** | cells | 4,406; 403 eligible; 14 and 2; 0; 909.6; 6.4 (14 cells; 16 creations) |
| D5 | closest approach: minimum distance from a stored position to the ledge corner (−1,200, 3,000), for all classes and for A2/A1; best y at x ≤ −1,200 and at x ≤ −1,500; highest cell | cells | 1,017 (A0); 2,125; 1,252.3; 1,207.6; 3,247 |
| D6 | fatal returns: share of returns ending in a fall with no grounded tick | bursts | 480 / 2,175 = 22.07 % |
| D7 | efficiency: prefix share, new exploration ticks, returns, new cells per return, throughput | ledger | 90.3 %; 237,209; 2,175; 3.8; 1,560 ticks/s |
| D8 | v2 mechanism: cells excluded by E5 / E6 at the open and the close; descent-doom revivals; replacements of doomed incumbents; level distribution of dispatches; selection time | ledger + overlay | n/a (open: 1,905 / 1,309) |
| D9 | maximum targets broken, verified | claims | 7 |

The new burst fields (`ground_runs`; `res_transitions` = tick, from, to, x, y) are generic per-tick summaries. They also give rd2-only
readings that rd1 cannot provide, notably **the up-B start heights** (A2/A1 → A0 transitions) and their (height, x) Pareto front. In
rd1 the diagnosis could only bound these. They are reported and never compared with rd1.

**Comparability.** rd2 starts from rd1's archive rather than an empty one, so these comparisons are descriptive. The expected values
under v2 are the 2.4 estimates.

### 4.4 Stop conditions (evaluated after the decision; any one stops the line for review)

| # | condition | effect |
| ---: | --- | --- |
| S1 | M8-rd1 NULL (proposal §12.1) | not triggered (rd1 PASS) |
| S2 | no verified over-wall lineage after three sessions (proposal §12.2) | if rd2 is NO_MILESTONE, at most one more session (rd3) may be proposed under this design; a second NO_MILESTONE stops the line |
| S3 | median L of the top level's eligible cells > 3,000 before a left target (proposal §12.3) | horizon review (a longer horizon needs a new decision and label) |
| S4 | **DILUTION_PERSISTS** | v2 failed its own mechanism: revise the selection under a new label; no rd3 under v2 |
| S5 | **BOUND_VIOLATION** | the bound is withdrawn or corrected under a new contract; no rd3 under v2 unchanged |
| S6 | **NO_MILESTONE / DILUTION_REDUCED with launch-capable cells created per 1,000 returns ≤ rd1's 6.4** | selection removed the waste but precursor supply did not rise: the bottleneck is the explorer or the key, so propose a new design rather than rd3 |
| S7 | INVALID / INCOMPLETE | repair and a new approval / read the caps; never an extension or automatic retry |

**After PROGRESS:** an rd3 may be proposed, authorised separately, with S2–S7 re-evaluated. **After NO_MILESTONE / DILUTION_REDUCED
with S6 not triggered:** rd3 under the same design is eligible to propose as the last session before S2.

## 5. Item 4: caps and budget

**Throughput basis** (`sessions/rd1/iterations_T.jsonl`):
- mean job wall 2.68 s per worker, made of 1.48 s waiting for the standby and 1.10 s of stepping;
- fit: wall = 1.94 s + ticks / 1,523;
- 1,120 ticks per job;
- all 2,175 starts were standby-promoted;
- aggregate 1,560 ticks/s at about 75 % worker utilisation.

v2 does not change the prefix lengths much (rd1's median L was 1,055), so the same rate is assumed.

| phase | native ticks: expected (cap) | wall: expected (cap) |
| --- | ---: | ---: |
| S0-resume, outside the clock (R0–R6: immutability, audit, overlay, copy, hashes, D: checks) | 0 | ≈ 5–8 min |
| open: P1 + 16 identity replays | ≈ 6,200 + ≈ 21,000 (**70,000**) | ≈ 1 min (**4 min**) |
| exploration, N = 5, one standby each, flags as rd1 | ≈ 4.7 M, range 3.5–6.0 M (**6,000,000**; valid from **2,000,000**) | 50 min (**50 min**; the wall cap is expected to bind) |
| verification: claims + 16 close identity replays, ≤ 3 processes | ≈ 30,000–130,000 (**400,000**) | ≈ 1–3 min (**6 min**) |
| **within the clock** | **≤ 6,470,000** | **hard cap 60 min from P1** (4 + 50 + 6) |
| S2 close, outside the clock (save, audit, prefix property, R1, D: increment `<date>_incr_m8_rd2` of `runs/m8_rd_rd2/`, verify, re-hash, combined coverage) | 0 | ≈ 5–10 min |

- **Expected returns:** about 4,200 (3,000 s / 1,561 s × 2,175), with about 16,000 new cells, giving an archive of about 24,000
  cells.
- **The tick cap** binds first only if throughput exceeds 2,000 ticks/s.
- **Cutting at the caps:** the amendment-1 allowance at the tick cap. At the wall cap, jobs in flight get a 20 s grace and are then
  aborted and not committed (`aborted_jobs` recorded).
- **Exploration continues regardless of discoveries.**

**Memory and process caps, as in rd1:**
- main process private ≤ 3,072 MB;
- whole tree, sampled every 5 s: private ≤ 9,216 MB and working set ≤ 4,096 MB;
- system available ≥ 1,024 MB and free commit ≥ 2,048 MB;
- archive in memory ≤ 1,024 MB;
- ≤ 10 BattleShip processes (two distinct samples above 10 to stop), and none left after the run;
- readiness ≥ 4,096 MB available, ≥ 10,240 MB free commit, ≥ 5 GiB free on C: and on D:.

rd1 peaked at 493 MB main and 4,278 / 1,632 MB for the tree. About 24,000 cells at 1.84 KB each add about 30 MB.

## 6. Item 5: integrity (rd1 strength, plus the continuation checks)

- **Approval.** `docs/rl_m8_rd2_approval.json`, written from a freshly printed template. It names:
  - the rule digest and the contract digests (cell v1, explore v1, select v2, claims v1, Track 1, status table);
  - the pins and the base (rd1 manifest, close-record and D: manifest digests);
  - the budgets, caps, key strings and code hashes.

  Preflight refuses for exactly one reason without it, and passes with it. Approval tests run on isolated temporary records.
- **Source snapshot.** `D:\BattleShip_source_snapshots\<date>_m8_rd2`: tool `snapshot` and `verify`, then an independent PowerShell
  re-hash before the run, and re-verified after it.
- **D: backups.** Before: 0 uncovered `runs/` files, with rd1's increment re-verified (R1). After: the increment
  `<date>_incr_m8_rd2` of `runs/m8_rd_rd2/`, tool `verify` and an independent re-hash, combined coverage 0 uncovered, and R1 again.
- **Identity replays.** 16 at the open (R8) and 16 at the close (milestone cells first, then the shortest of the top three levels,
  then keyed-random cells).
- **Four-way return verification** at every return and every identity replay:
  - the tick-0 record (except `host_frame`, which is reported);
  - per-tick consumed tick, input tick and state, with no end and no fall;
  - the end record and its record digest;
  - the chain digest.

  **Any mismatch is INVALID**, with no retry and no skip, and the raw replies are preserved. A lifecycle failure is redrawn; more
  than 3 is INCOMPLETE.
- **Claims** by full fresh-process replay from tick 0 (4.1).
- **Static guards**, extended to the new modules:
  - no reads of `rl/fixtures/`, `runs/m7g/capture/`, `tas_input_2/` or `.btti` files;
  - no write path under `runs/m8_rd/`;
  - the provenance guard (every lineage reaches cell 0 of `m8_rd_a1`).
- **The rd1 code stays byte-identical**, so that rd1 remains auditable. Its 48-test suite must still pass.

## 7. Item 6: generality

**What runs unchanged for any character's Break the Targets stage:**
- E5 descent doom (native fall, grounded tick, the burst tree);
- R3a and X1;
- the R2 formula;
- the key mechanics, the explorer (controller-level Track 1 words), the resume protocol, the integrity checks, and the INVALID and
  INCOMPLETE parts of the rule.

**What needs a per-character or per-stage definition before use:**

| item | why | Mario US status |
| --- | --- | --- |
| status-class table (validated) | the resource classes A2 / A1 / A0 / X come from it | `btt_action_class_table_v2`, Mario validated; the 11 others unreviewed |
| resource classes and r, r_max | `jumps_max` and multi-jump rules (Kirby and Jigglypuff 5); which status is the recovery special and whether it ends helpless (it does not for every character, and some recovery specials do not rise); characters whose recovery is a jump or a different special | A2 / A1 / A0 with r = 2 / 1 / 0 |
| recovery-rise bound (E6) | every rising resource with an upper bound and its derivation from attribute or motion data or agent-generated measurements, never from recordings or the TAS; a margin; the live falsification flag. **If not registered, E6 is off**: the constant-free M1 still gives 9.2 % below the floor on the rd1 estimate | J 1,171.8, U 1,361.3, T 2,073.3 (unspent assumed), margin 300 |
| stage floor set | read from the native line table automatically; a moving floor's lowest position needs the per-stage check | Y_floor_min −2,550 |
| milestone ladder | the wall top, the left targets and the crossing are facts of Mario's stage; another stage registers its own (targets and the clear are generic) | as 4.1 |
| reporting regions and precursor readings | the regions, the step, the corner and the 1,639 threshold are Mario-stage analysis definitions; another stage needs its own, or generic ones from the line table (below the lowest floor, outside the floors' x-span, per-floor contact shares) | as 4.3 |
| horizon, completion clocks, anomaly threshold | per task (guide §12) | 3,600; 446 / 447 |
| a JP build | a distinct task family; pins and constants revalidated | n/a |

## 8. Absolute constraints

| constraint | how this design keeps it |
| --- | --- |
| no native RNG seed inspection, logging, control, comparison or hashing | all draws are Python-side sha256 keys; the chain covers observation fields only; nothing reads RNG |
| process restart resets the episode | one fresh process per return and per replay (standby promoted at tick 0 or cold); no in-process reset, no savestate |
| exact submit / consume / input-tick contract | every word is one `step`, with consumed tick = i and input tick = i + 1, in prefixes, bursts, identity replays and claims; reset is the non-consuming `observe` |
| canonical controller words as replay truth, no hidden actions | lineage reconstructs the exact native triples; Track 1 indices are metadata |
| prefixes agent-generated only | the archive starts from rd1's own trajectories, all chained to cell 0 of `m8_rd_a1`; nothing seeded from any other run |
| human crossings and the TAS validation-only | not read; the static guard extends to the new modules; the bound constants come from decomp data and agent flights |
| no hardcoded routes or waypoints | 2.6: no position, surface, target-location or direction term in selection |
| non-PORT decomp and byte-matching preserved | no native, decomp or submodule change; the existing executable and read-only flags |

## 9. Implementation outline (new files only; separately authorised; zero native ticks to prepare)

| file | contents |
| --- | --- |
| `rl/m8_rd_select2.py` | `m8_rd_select_v2`: eligibility overlay, incremental descent-doom propagation (with revival), the recovery bound plus falsification, weights, replacement, contract digest, self-test |
| `rl/m8_rd_resume.py` | R0–R6: immutability check, open of an existing archive, overlay, materialisation with a base pointer, prefix-property audit |
| `rl/m8_rd2_worker.py` | a job kind `iterate2` whose result adds `ground_runs` and `res_transitions`; rd1's `iterate` job stays byte-identical |
| `rl/m8_rd2_session.py` | CLI (status, preflight, approval-template, run, verify-run): P1, open identity, single-arm exploration with caps, verification, close; rd2 constants (`SESSION = "rd2"`, approval, snapshot and backup names) |
| `rl/m8_rd2_rule.py` | `m8_rd2_rule_v1` and its self-test (disjointness, precedence, thresholds, flags) |
| `rl/m8_rd2_report.py` | D1–D9, plus the same computations on rd1, which must reproduce this document's reference values |
| `rl/m8_rd2_tests.py` | v2 selection against the analytic probabilities; descent-doom trees (pending, fatal, revival); the bound and its violation; replacement under v2 doom; the one-target exception; resume (tampering of rd1 files refused, pin drift refused, prefix property, iteration continuation); the immutability guard; the rule; a synthetic continuation end-to-end run at the registered counts; real lifecycle against the fake game |

**Reused unchanged:** `m8_rd_cells`, `m8_rd_explore`, `m8_rd_archive` (read side and audit), `m8_rd_claims`, `m8_rd_finish`'s
verification path, `m7f_trace`, `m7n_crossing`, `m7_standby`, `battleship_process`, `battleship_client`, `tools/runs_backup.py`,
`m8_rd_snapshot.py`, and the M7u3 tree sampler.

**Launch conditions** (as rd1 Part B):
- unit tests and the synthetic end-to-end run pass;
- the pessimistic wall projection fits within 60 min;
- preflight refuses solely for the missing approval;
- `git status` shows only the new files;
- no open design decision remains.

## 10. Open questions for you

1. **v2 as specified (R1b + R1c + R2 + R3a), or the constant-free M1 (without the recovery bound)?** I recommend the full v2 with the
   falsification flag; M1 is the template for characters without registered constants.
2. **Replacement under v2 doom** (a doomed incumbent loses to a pending reach), **or v1's replacement unchanged?** I recommend v2 doom,
   so that a key is not lost to a fatal first representative.
3. **The one-target exception X1:** include it? I recommend yes. It is generic and inactive until level 9.
4. **Directory:** a sibling `runs/m8_rd_rd2/` (recommended, so rd1's tree stays exactly 166 files), or a subdirectory of
   `runs/m8_rd/`?
5. **New burst fields `ground_runs` and `res_transitions` in rd2** (a new worker job kind; the cell key unchanged)? I recommend yes:
   they make descent doom exact for rd2 bursts and give the up-B start heights.
6. **The dilution thresholds and S6:** below-floor ≤ 10.5 %, fatal returns ≤ 11.0 %, and launch-capable creations per 1,000 returns
   > 6.4 to justify rd3. Accept these or set others?
7. **Budget:** exploration 50 min / 6,000,000 ticks, valid from 2,000,000; open 70,000 / 4 min; verification 400,000 / 6 min.
   Acceptable?
8. **Explorer and burst length unchanged**, with prefix replay therefore still near 90 % of ticks, to change one variable at a time?
9. **Draw keys:** keep v1's key strings with iterations continuing from 2,175 (recommended), or a v2-specific key prefix?
10. **The tornado term** assumes the tornado is unspent, because `is_expend_tornado` is not observed. Accept this conservative bound?
    (Exposing the flag would need a native change, which I do not recommend.)
11. **Sequencing:** zero-tick preparation first (code, tests, synthetic run, preflight, template) under its own authorisation, then
    rd2 under another, as for rd1?

## Appendix A. Scratch analyses (outside the repository; not evidence)

**Location:** `%TEMP%\claude\…\scratchpad\rd2\`. Every script ran with `python -B`, read only `runs/m8_rd/` (manifest verified on
load) and the checked-in status table, and imported only the pure modules `m8_rd_archive`, `m8_rd_cells` and `m8_rd_explore`.

| script | what it did |
| --- | --- |
| `s1_ledger_counterfactual.py` | instrumented ledger replay (all 2,175 selections re-derived; 8,264 cells identical); at each dispatch, the analytic distributions of v1, R1a, R1c, R1c′, R1d, R2, R3a–c, R4 and combinations; realized v1 shares; return outcomes by start region; final exclusion counts |
| `s2_descent_doom.py` | the burst-tree propagation of R1b, evaluated causally at each dispatch; R1b′, R1b + R1c, M1, v2 and others; final exclusion counts by region and class |
| `s3_checks.py` | the falsification check of the bound on rd1's stored reaches; the evidence-count variant R1b″; throughput from `iterations_T.jsonl` |
| `s4_joint_productivity.py` | joint (class × region) masses for v1, M1 and v2, and rd1's realized yields per start class (2.4(c)) |

Pins were hashed with PowerShell `Get-FileHash`, and the D: increment's `verification.json` was read. No file under `runs/` or in
the repository was written; `git status` was clean before this document.
