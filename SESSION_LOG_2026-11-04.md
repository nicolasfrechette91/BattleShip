# Session log, 2026-11-04 (local, with the owner)

A local session on the PC, working with the owner. Each design decision is proposed and waits for the owner's go. Nothing
native runs without a go. **Zero game ticks so far.**

## 1. Integration branch

**Decision (owner's instruction):** create `run3/integration` from `experiment/msvc-libultra-trig` (24bcb27) and merge the
three cloud branches into it. Nothing is merged to `main`.

- Fetched `origin`. `cloud/2026-11-04-glitch` and `cloud/2026-11-04-infra` were new locally.
- All three branches fork from 9afcaf6. `cloud/2026-11-04-infra` already contains `cloud/2026-11-03` (5a4efce).
- File overlap, checked before merging:
  - none between HEAD and any branch (24bcb27 touches only `CMakeLists.txt`);
  - none between glitch and infra;
  - no branch touches `docs/project_handoff.md` or the untracked files.
- Dry run with `git merge-tree --write-tree` for each branch against HEAD: exit 0, no conflict.
- Merged with `--no-ff`, in this order:

  | merge commit | branch (tip) | result |
  | --- | --- | --- |
  | 6532239 | `origin/cloud/2026-11-03` (5a4efce) | clean, 6 files |
  | 176fdfc | `origin/cloud/2026-11-04-infra` (5f8930a) | clean, 34 files |
  | b51b086 | `origin/cloud/2026-11-04-glitch` (131ce23) | clean, 9 files |

- The owner's local changes are untouched:
  - `docs/project_handoff.md` (modified);
  - `docs/frs_departure_probe_result_2026-11-03.md` and `tools/audit/trig_ab_replay.py` (untracked). The merged
    `tools/audit/` files have other names.

## 2. Step 1: validation without the game

All runs: Git Bash, Python 3.13.2, checkout root. Logs are in the session scratchpad. "Before" means 24bcb27, run in the
same checkout after switching back to `experiment/msvc-libultra-trig`.

### 2.1 Suites

| suite | expected | after the merge (b51b086) | before (24bcb27) |
| --- | --- | --- | --- |
| `python -B rl/infra_port_tests.py` | 7/7 | **7/7** (9 s) | n/a |
| `python -B rl/infra_log_tests.py` | 4/4 | **4/4** (3 s) | n/a |
| `python -B tools/frs/det_schedule_tests.py` | 5/5 | **5/5** (307 s) | n/a |
| `python -B tools/analysis/analysis_tests.py` | 4/4 | **3/4**: `charts_render` fails, no `matplotlib` on this Python | n/a |
| `python -B tools/glitch/test_glitch.py` | 36 tests | **36 run, OK** (1 skipped: the C-reference VPK0 test, no `cc` in Git Bash) | n/a |
| `python -B rl/m8_rd_tests.py unit` | as before | **46/48** | 47/48 |
| `python -B rl/frs_tests.py` | as before | **31/31** (run twice) | 31/31 |
| `python -B tools/frs/crossing_search_tests.py stub` | as before | **5/5** | 5/5 |

The differences:

- **`m8_rd_tests.py unit`: one new failure, caused by the merge.** `source_guard` reports
  `{'m8_rd_fakegame': ['import random']}`.
  - The infra branch's D4 commit (45695db) added `import random` and `random.SystemRandom()` to `rl/m8_rd_fakegame.py`, for the
    opt-in `FAKEGAME_STEP_JITTER_S` wall-clock noise. The noise never changes a reply.
  - The cloud only reran this suite for fix 1, so it never saw the failure.
  - The other failure, `tracked_files_unchanged`, is the owner's `docs/project_handoff.md` edit. It fails before and after.
- **`frs_tests.py`, `unit_run_code_manifest`**: 34 files with digest `0b248a9e30304325` before, 35 files with digest
  `6f3a49899a9461cc` after. The lab code now includes `rl/port_lease.py`. Expected: run 3 has a new code digest anyway.
- **Wall-bounded fake-game counts** (`frs_tests` e2e, `stub_end_to_end`):
  - The job counts vary between runs, before and after. `e2e_control_run` gave 1,256 jobs before, then 1,080 and 1,038 after.
  - `e2e_real_lifecycle_with_fake_game` goes through the real launcher, so through the new lease and handshake. It made
    176 launches before and 163, then 176 after. **No measurable launch cost.**

### 2.2 Run 2 analysis on the real folder

`python -B tools/analysis/run2_lab.py --run C:/BattleShip_lab/crossing_2026-10-15_run2/run --out C:/BattleShip_lab/analysis/run2_lab`

- With charts, the script writes `lab_analysis.json` and then stops on `ModuleNotFoundError: matplotlib`. Rerun with
  `--no-charts`: exit 0, byte-identical JSON. It prints
  `39,309 dispatches, 3 verified clears, 10 targets with a break, 0 short gaps, 0 integrity flags`.
- Row counts: dispatches 39,309, cells 75,787, verifications 3, checks 3,916.

**Measured against `RUN2_ANALYSIS.md`, which was built from the records:**

| quantity | RUN2_ANALYSIS.md | measured from the rows | verdict |
| --- | --- | --- | --- |
| dispatches, new cells, replacements | 39,309, 4,550, 71,237 | 39,309, 4,550, 71,237 | equal |
| breaking bursts, falls, claimed clears | 584, 24,285, 136 | 584, 24,285, 136 | equal |
| level-9 earliest arrivals | 1,293 at 2,274; 1,072 at 2,723; 1,053 at 13,636; 1,051 at 28,551 | same | equal |
| level-8 earliest | 974 at 1,188 | 974 at 1,188 | equal |
| level-9 dispatches, falls | 20,984, 73 % | 20,984, 15,410 (73.4 %) | equal |
| level 9, mask 64 (target 6 left) | 8,078 dispatches, 0 breaks, 7,327 falls | 8,078, 0, 7,327 | equal |
| level 9, mask 2 (target 1 left) | 8,027, 90 clears | 7,990, 90 clears, 4,660 falls | **gap: 37** |
| level 9, mask 256 (target 8 left) | 4,879, 46 clears | 4,874, 46 clears, 3,421 falls | **gap: 5** |
| level 9, no mask in the row | (not listed) | 42 dispatches, 0 breaks, 2 falls | the 42 = 37 + 5 above |
| stepped ticks (prefix + burst) | 46,603,859 + 3,568,728 | 50,172,587; burst words 3,568,728 | equal |
| re-checks, share of worker time | 19,772 s, 13.9 % (derived) | 19,772.1 s of 142,526 s, 13.9 % | equal, now measured |
| time per job outside re-checks | 3.12 s (derived) | 3.12 s | equal |
| stepping per job | 1.45 to 1.75 s (inferred) | **1.44 s** (1.13 ms per stepped tick) | just below the inferred range |
| remainder per job | 1.36 to 1.67 s, 44 to 53 % (inferred) | **1.67 s, 53.6 %**: 0.95 s inside the job clock but not stepping (standby wait, boot, connect) + 0.72 s outside it (close, transfer, ingest, selection, idle) | top of the inferred range |
| continuation questions | (not given) | 100 s in total | negligible |
| earliest break per target, every burst | must be at or before the record's "earliest" column | at or before for 9 targets. Target 0: 80, against 43 | **the 43 comes from the registered 1,884/1,885, not from run 2**: the claim in RUN2_ANALYSIS §6 does not hold for target 0. Not a data gap |
| verified complete orders | 4, 0, 5, 7, 9, 3, 2, 6, 8, 1 "22 claims"; 4, 5, 9, 7, 0, 3, 2, 6, 8, 1 "157" | 2 verified clears (fastest 1,245) and 1 (1,352) | consistent: the record counts claims over several runs, the rows count run 2's verified clears |

New, from the rows only:

- **Run 2 bursts broke four targets earlier than any verified clear did.** Target 6 at 879 (dispatch 27,762), 8 at 894
  (36,065), 1 at 1,051 (28,549) and 2 at 631 (29,102). In the 1,245 these are 1,042, 1,135, 1,245 and 639.
- **Longest level-9 stall:** 14,915 dispatches without a new earliest arrival (13,636 to 28,551), then 10,758 more until
  the stop.
- **Per 1,000 dispatches:** new cells 48 to 207, breaking bursts 7 to 25, claimed clears 0 to 15. Coarser hourly rows smooth
  this out, as the record says, and there is no decay.

### 2.3 Glitch tools on the ROM and the lab traces

| command | expected | result |
| --- | --- | --- |
| `python -I tools/glitch/glitch.py extract --rom <checkout>/baserom.us.z64` | 4 `OK` lines, `20 lines`, exit 0 | **4 OK** (yaml offsets of files 271 and 124, geometry equals the decomp decode, header bounds equal), `20 lines; geometry sha256 2c165c1d…`, exit 0. **No FAIL.** |
| `glitch.py compare` against the 1,245's trace (`clear_n36236_c8692_k0_r1`) | `SAME` | **SAME** |
| `glitch.py compare` against the 1,885's trace (`import/reference/trace.json.gz`) | `SAME` | **SAME** |
| `glitch.py detect --trace-dir C:/BattleShip_lab/splice_probe_2026-10-14/run/traces --out logs/glitch/events_splice.jsonl` | events and a summary | 1,545 events from 208 traces, 92 s |

Detector output (`logs/glitch/`, Git-ignored). These are **candidates**: none counts before a replay from tick 0.

| kind | events | traces | reading |
| --- | ---: | ---: | --- |
| `position_snap` (all of class `edge_snap`, M8) | 1,128 | 105 | floor-end teleport candidates |
| `line_crossing` (M5, M2, M3) | 209 | 169 | all against static lines (group 1 is the static stage; group 2 is the moving floor, line 19). 177 are the right point behind line 18, an `lwall`, about 12 units (median) below its top end, at most 84 units deep. Corner contacts at the wall top (M5), or the detector's tolerance there: to review on a replay |
| `beyond_camera_bounds`, `beyond_map_bounds` | 97, 57 | 94, 57 | the probe's falls |
| `break_without_plausible_hitter` (M11) | 54 | 54 | all target 9, 51 of them at step 398. The anomaly inventory found a fireball near such breaks, while the detector lists no hitter. **The detector's weapon reading must be checked before step 4 relies on it** |
| counted, not emitted: `pass_line_crossing`, other snap classes (`wall_clamp` 11,615, `landing` 2,300, …) | n/a | n/a | the default filter keeps only the edge and unexplained snaps |
| tagged `platform_sensitive: d1_transn_cosf` | 40 | n/a | within 30 ticks of an up-B with \|stick_x\| > 50 |

- **Geometry digests differ, and that is expected.** `detect` hashes the table rebuilt from the trace (`a00869b4…`), `extract`
  the ROM table (`2c165c1d…`).
  - The only differing fields are the last-vertex flags of lines 2 and 19: 16384 from the trace, 0 from the ROM. The trace
    carries first-vertex flags only, and the rebuild copies them to every vertex.
  - `compare` checks first-vertex flags, so it says `SAME`.
  - Lines 2 and 19 are the two pass-through (one-way) lines, which matches GLITCH_CANDIDATES' correction "16384 = one-way".

### 2.4 D1: ucrt `cosf` against libultra `__cosf` (GLITCH_CANDIDATES §5 step 6)

The three `cl` lines, run through `vcvars64.bat` of VS 18 Community (x64), at the checkout root. Output: `build-glitch/`
(Git-ignored).

- `cl` warns `C4068: unknown pragma 'weak'` twice, which is the D1 mechanism itself. `host: MSVC 1951 (ucrt cosf)`.
- Last line:

  ```
  differ: 10 of 61 inputs; on the 8-direction inputs (|stick_x| = 80): 0 of 2
  ```

- Stick 0 and ±80 give identical bits (`0x3f800000`; `0x3f737871` for both ±80).
- The 10 differing inputs are ±54, ±63, ±72, ±76 and ±77, exactly the ones where GLITCH_CANDIDATES found **libultra** 1 ulp
  away from correct rounding. So ucrt is correctly rounded there and libultra is not.

**Checks added in this session** (zero ticks):

- **FMA3** (review D1's second Windows-only effect). A scratch program calls the same ucrt `cosf` on the three restricted
  rotations with `_set_FMA3_enable(1)`, then `(0)`. This CPU has FMA3 (`_get_FMA3_enable` = 1). Bits are identical in both
  modes and equal libultra: 0 differences.
- **Code paths, read in the decomp:**
  - `ftPhysicsGetAirVelTransN` (bare `cosf`, `ftphysics.c:430`; `__sinf` on the next line) is reached for Mario only from
    `ftmariospecialhi.c:75` and `:81`. The other callers are Ness and Yoshi double jumps, other characters, and the ledge climb.
    There are no ledges on BTT.
  - `ftMarioSpecialHiProcInterrupt` writes `TransN.rotate.z = -DTOR((stick_x ∓ 50) × 0.6)` only while motion flag1 is 0 and only
    if that is larger in magnitude than the joint's current rotation.
  - Mario's fireball has `attack_offsets` all zero (`204_MarioSpecial1.c`), so `wpProcessUpdateHitPositions` adds the translation
    and never calls `wpProcessUpdateHitOffsets`, the bare-trig rotation. **The 11-03 review is wrong on both points:** the
    fireball is not on the D1 path, and Mario's Super Jump Punch is.
- **Exposure in the stored traces.** Counted: Mario status 225 airborne, plus 226 with motion flag1 set (captured after the
  update). `stick_x` is the game's own `fp->input.pl.stick_range.x` (`sc1pbonusstage.c`, M7q input diag).

  | route | live ticks | ticks on the `ftphysics.c:430` path | stick_x on them |
  | --- | ---: | ---: | --- |
  | 1,245 (`clear_n36236_c8692_k0_r1`) | 1,245 | 136 (from tick 158 to tick 896) | −80: 16, 0: 39, +80: 81 |
  | 1,885 (registered reference) | 1,885 | 220 | −80: 53, 0: 118, +80: 49 |

- **Not settled by this check** [unverified, as GLITCH_CANDIDATES says]: whether the Super Jump Punch animation keys its own
  TransN `rotate.z`.
  - If it does, rotations other than 0 and ±0.3141593 reach ucrt, and the check above does not cover them.
  - The traces do not record the rotation.

## 3. Open items raised by step 1 (proposed, waiting for the owner)

1. **`source_guard` regression** (`rl/m8_rd_fakegame.py` imports `random`). Recommended: draw the jitter from `os.urandom`
   instead, keep the guard unchanged, and rerun `m8_rd_tests.py unit` (expect 47/48 again). Alternatives: allowlist the fake game
   in the guard (weakens a guard that exists to keep RNG out of M8-rd code), or leave it failing (masks future hits).
2. **`matplotlib` missing.** `analysis_tests` `charts_render` fails and `run2_lab.py` needs `--no-charts`. Recommended: leave it
   (the cloud's ten charts are committed, and every number above comes from the JSON). Installing it is a PyPI download and
   needs the owner's go.
3. **Detector checks before step 4 wires the event format:** the missing hitters on the target-9 breaks, and the line-18 wall-top
   crossings. Step 4 keeps every event either way (events never gate anything).

## 4. Step 2: D1 decision

**Decided by the owner: keep `30a3913b`.** Recorded in `docs/rl_decisions_2026-11-04.md` §1.

| option | for | against | outcome |
| --- | --- | --- | --- |
| **Keep 30a3913b (ucrt trig)** (recommended) | bit-identical to libultra on the agent's three rotations; FMA3 on and off identical; no archive regeneration; no A/B | the animation-keyed TransN rotation is unverified; this matters only for N64 or Linux parity | **chosen** |
| Switch to libultra trig now | N64 parity on every input; removes the residual question | new executable; archive re-checked and claims re-verified, for no difference measured on the current inputs | not chosen; becomes **required** before analog stick values |

Why: the step 2 rule applies. Step 6 shows ucrt == libultra on the agent's inputs. The exposure (136 ticks of the 1,245 and
220 of the 1,885 on the `ftphysics.c:430` path) matters only if the bits differ, and they do not.

## 5. Step 3: decision records

Edited files (no code, no ticks):

- `docs/rl_decisions_2026-11-04.md` (new):
  - §1 D1 = keep, with the correction to the 11-03 review (fireball not on the path; Mario's airborne Super Jump Punch is),
    the residual question and the analog-stick requirement;
  - §2 savestates closed (2026-11-03);
  - §3 BizHawk not used. The `.bk2` file format stays allowed as an export, because the run 3 brief asks for a bk2 per claimed
    clear and the repo keeps the inherited `tools/bk2_to_btt_inputs.py`.
- `docs/rl_decision_soft_reset_2026-11-02.md`:
  - status line: (B) NOT PURSUED;
  - §9 rewritten as closed, with the undecided draft wording withdrawn (it stays in b255bdc);
  - §8 option 3 marked superseded;
  - §2's BizHawk sentence marked superseded, with the rest of §2 standing.
- `docs/frs_anomaly_inventory_2026-10-16.md`:
  - §1.2: types 6/5/5/4, `type` = line kind, `flags` 16384 = `MAP_VERTEX_COLL_PASS` (one-way, lines 2 and 19). Marked as a
    dated correction, stating the old wording.
  - Pointers added in §2 and §4 where the inventory said the meaning was unknown.
  - Both corrections were re-counted on two real traces before editing; types 0 to 3 follow `nMPLineKind` in `mpdef.h`.

Not edited: `docs/project_handoff.md` (owner's local changes). Its line "(B) snapshots open" (under "Decided 2026-11-02") is now
out of date; the owner updates it.

## 6. The `source_guard` regression: fixed

**Decision (owner):** no `os.urandom`. It would get around the guard without respecting its purpose, and it would make the D4
tests irreproducible.

- The jitter is now derived deterministically with hashlib, off by default. Jobs finish out of order, but reproducibly.
- The guard is unchanged. `matplotlib` stays uninstalled for now (owner).
- Alternatives considered:
  - `os.urandom`: refused, as above.
  - Allowlisting the fake game in the guard: weakens the guard.
  - A per-launch key such as the launch nonce or the pid: not reproducible.

**Change** (`rl/m8_rd_fakegame.py` only):

- `import random` and `random.SystemRandom()` removed.
- The delay before each step reply is `j × u`, with
  `u = sha256("fakegame_jitter_v1|<FAKEGAME_STEP_JITTER_SEED>|<step>|<running digest of this process's step requests>")[:8] / 2^64`.
  That is a keyed sha256 uniform, as the guard's docstring requires of every draw in these modules.
- The **job identity is the job's own word stream** (prefix and burst). The process is never told a job id: standby processes
  boot before a job is assigned, and the launch nonce is fresh per launch. Under D4's keyed draws, the word stream is reproducible.
- `FAKEGAME_STEP_JITTER_S` defaults to 0 (off). `FAKEGAME_STEP_JITTER_SEED` defaults to "0".
- Checks:
  - the formula is reproducible for the same seed, differs for another seed, and stays in [0, j);
  - `git diff --check` is clean, and the line endings match the committed file (CRLF).

**Tests after the change** (b51b086 plus the working tree):

| suite | result | expected |
| --- | --- | --- |
| `python -B rl/m8_rd_tests.py unit` | **47/48**; `source_guard` PASS | 47/48. The one failure is `tracked_files_unchanged`, which lists this session's uncommitted edits and the owner's handoff edit |
| `python -B tools/frs/det_schedule_tests.py` | 5/5 (326 s) | 5/5 |
| `python -B rl/infra_port_tests.py` | 7/7 | 7/7 |
| `python -B rl/infra_log_tests.py` | 4/4 | 4/4 |
| `python -B rl/frs_tests.py` | 31/31 (lab code manifest still 35 files, `6f3a49899a9461cc`: the fake game is not lab code) | 31/31 |
| `python -B tools/frs/crossing_search_tests.py stub` | 5/5 | 5/5 |

## 7. Investigations before the step 4 design (read-only, stored traces, zero ticks)

For detection and understanding only. Nothing here steers the agent toward any place, and no position appears in a rule.
Scripts and outputs are in the session scratchpad (`inv1_line18.py`, `inv2_breaks.py`, their `.jsonl` outputs).

### 7.1 The line-18 wall crossings: a detector false positive (no clip)

- **Volume.** 182 events on line 18: 177 with the diamond's right point and 5 with its bottom point.
  - They lie in 169 of the 208 splice traces: 159 r1 candidates, 9 r2 copies and the control (the registered 1,885 itself).
  - Collapsed by the state at the event tick, they are **86 distinct states**.
- **What happens, tick by tick.** On the tick before every right-point event, the right point lies **exactly on the wall plane**
  (`dx` = 0.00): Mario slides up the wall, clamped by it. On the event tick the point is **above the wall's top end** (for example
  +36 units).
  - The point is never inside the solid: 0 of 177 events, at the event tick or in the 11 ticks after.
  - The straight path between the two ticks cuts the corner. It goes 0.78 to 11.36 units (median 4.15) behind the wall plane
    before passing the top end, starting 3.7 to 65.6 units (median 12.4) below it. This is an ordinary between-tick corner pass of
    a rising fighter.
  - The statuses are aerial attacks (F-air 34, B-air 30), jumps, the fireball in the air (224) and the up-B (226).
  - The 5 bottom-point events are a grounded roll (`EscapeB`) on floor 1. That floor starts at the wall's top vertex, and the
    bottom point slides across the shared vertex.
- **Why the detector fires.** `line_crossings` accepts a start on the plane (`d0 >= -margin`), an end behind the line's infinite
  extension (`d1 < -margin`), and a crossing point on the segment (the start point, 12.4 below the top). It never checks that the
  **end** point lies behind the segment itself.
- **All other line crossings have the same shape.** All 209 splice events and the 2 in the 1,245
  (`detect --trace clear_n36236_c8692_k0_r1`) start on the plane:
  - 201 end beyond the wall's end (lines 18, 15, 12 and 10);
  - 10 are bottom points sliding across a floor-to-wall vertex (the end exactly at `u` = 0 or 1).
  - The 1,245's second event (line 12, step 866) is the left point, clamped on that wall during the Super Jump Punch and then
    above the wall's top end. The "133 from the corner" figure is the start point's distance, not the end's.
  - **Zero true crossings.**
- **Outcomes of the 169 trajectories:** 19 clears, 98 out of words, 52 falls. 126 of the 182 events are followed by at least
  one break in the same trajectory.

### 7.2 The 54 target-9 breaks with no hitter: a detector threshold, not an impossible break

- Every target break in the splice traces was scanned: 223 distinct breaks, 1,188 with duplicates.

  | hitter | distinct breaks | evidence |
  | --- | ---: | --- |
  | melee | 166 | hitlag starts on the break tick (the game's own sign that the fighter's attack connected), attack flag on, body centre 46.8 to **697.1** units from the target (median 398) |
  | fireball, recorded | 55 | a weapon 255.5 to 364.4 units from the target on the tick before; the fighter 495.9 to 3,991.1 units away, no hitlag. Targets 0, 3, 4, 6, 7 and 9. These are the inventory's long-range fireball breaks |
  | fireball spawned and hit within one tick | 2 | fireball status (223 on the ground, 224 in the air), target 147 to 185 units away; the weapon is never in a recorded tick |
  | none | **0** | |

- The 54 events are Mario's angled forward smash (`AttackS4Hi`, status 202):
  - 51 at step 398, the registered route's own target-9 break at tick 399, plus 397 and 286;
  - 652 to 697 units from body centre to target, with hitlag 11 starting on the break tick.
  - The detector's box is `body_reach` 500 + `target_half_extent` 150 = 650, so it misses by up to 38 units.
- Its fireball handling is correct: all 55 recorded fireball breaks found the weapon.
- **Fix for step 4:** take melee from hitlag onset, which the game itself reports, not from a distance threshold.

### 7.3 The 42 level-9 rows with no mask

- They are dispatches of **8 cells inherited from run 1** that run 2 never rewrote. `run2_lab.py` reads keys from run 2's
  `cells.jsonl` only, so those cells have no key there.
- Their run 1 keys give mask 2 for 37 dispatches (6 cells) and mask 256 for 5 (2 cells). That is exactly the split the cloud
  record used.
- **The gap is not only at level 9:** 1,906 run 2 dispatches came from such cells (839, 738, 287 and 42 at levels 6 to 9).
- **For step 7:**
  - run 3's group key must come from the merged archive the engine selects from, never from one run's file;
  - a cell without a key must form an explicit `unknown` group: counted and reported, never demoted or promoted, never merged
    into another group;
  - run 3 refuses to start if any eligible cell has no key.

## 8. Step 4 design: decided

**Owner's go on the proposal (S4-1 to S4-6), with four changes:**

1. **Masks of inherited cells.** Before run 3 refuses to start on a missing key, propose how those masks are filled: from the
   archive or the parent chain without ticks, or by a replay with its tick count. Wait for a go (section 10).
2. **Hitlag.** An exactly unchanged position counts as hitlag ONLY if a break or a hit happened within a window justified by
   the code. Otherwise it is logged as `freeze_unexplained`. Measure the volume on the splice traces.
3. **Corner passes.** Keep counting them, but LOG those whose contact passes within a justified float error ε of a convex vertex
   (the 13 corners and 2 bends). Give the volume on the splice set.
4. **detect.py.** A cloud session will also extend it (state machine, branch `cloud/2026-11-05-states` from
   `cloud/2026-11-04-glitch`). Keep these changes in small isolated commits, with no reformatting.

**Rejected:** the entity-diagnostic alternative for run 3 (throughput). Bursts keep the explore flags (spatial only).

**Justifications chosen:**

- **ε = 0.001 game units.** This is the game's own float tolerance: the 0.001 start tolerance of the flat collision tests and the
  ±0.001 clamp of the line getters (`mpcollision.c`; GLITCH_CANDIDATES §1.4). It is about 4 ulps at this stage's coordinates.
- **Hitlag window = 11 ticks after a break**, derived from the code:
  - US `ftParamGetHitLag` (`ftparam.c:1674-1680`) gives `(s32)(damage / 3 + 5) × hitlag_mul`;
  - a hit on a target sets the attacker's `attack_damage` to the hitbox damage (`itprocess.c:311`), which `ftmain.c:4094-4134`
    turns into hitlag;
  - `hitlag_mul` is 1.5 only for electric hits between fighters (`ftmain.c:3020`, `:3140`); BTT has no other fighter;
  - Mario's largest hitbox damage is 19 (the 91 damage values in `src/relocData/202_MarioMainMotion.c`), so the bound is
    (s32)(19/3 + 5) = 11;
  - observed: the largest recorded hitlag onset on a break is 11 (section 7.2);
  - the only hits in BTT are target breaks, so a break is the only event that opens the window.

## 9. Step 4: built and measured

### 9.1 `tools/glitch/detect.py`: four isolated commits (only this file, no reformatting)

| commit | change |
| --- | --- |
| 39dac5a | a crossing needs the end point behind the segment itself (`eps_u < u_end < 1 − eps_u`, with ε as above). Otherwise it is a **corner pass**: counted (`corner_pass`), and emitted as `corner_pass_near_vertex` when the swept path passes within ε of a convex vertex (from `analysis.check_connectivity`, nothing hard-coded) |
| 215439f | a break whose fighter enters hitlag on the break tick is a melee hit at any reach. In live replies (no entity block) a break is counted (`break_live`) and emitted as `break_occluded` only when the fighter-to-target line crosses a solid line |
| e5ebd2c | an exactly unchanged position with a predicted move above the snap threshold counts as hitlag only within `hitlag_window` (11) ticks of a target break; otherwise `freeze_unexplained` is emitted. Downward crossings of one-way lines are emitted as `pass_through` (they were only counted) |
| b757266 | `LiveScanner`: the same detectors fed one reply at a time (replies before `emit_from` only update the break history and the look-back). Near-vertex passes say whether the fighter stood on the floor ending at that vertex (`on_adjacent_floor`) |

- **Checks:**
  - `python -I tools/glitch/test_glitch.py`: 36 run, OK (1 skipped), after every commit;
  - `LiveScanner` equals `Detector.run` (events and counts) on 41 lab traces × 2 modes: 82 of 82;
  - `git diff --check` clean; CRLF kept, as committed.
- **Cost:**
  - about 154 µs per scanned tick, so about 14 ms per 91-word burst (under 0.5 % of a 3.12 s job);
  - prefix ticks only update the break history;
  - building a `LiveScanner` from the cached line table takes 0.28 ms per job.

### 9.2 Volumes on the splice set (208 traces; offline = recorded, live = entity, targets and input blocks removed)

| event or count | offline | live | reading |
| --- | ---: | ---: | --- |
| `line_crossing` | **0** | 0 | was 209: all corner passes (section 7.1) |
| `corner_pass` (counted) | 215 | 215 | |
| `corner_pass_near_vertex` (ε 0.001) | **10** | 10 | all 10 are a grounded bottom point on the floor that ends at the vertex (`on_adjacent_floor`); distance 0.0. Of the 209 corner passes at a convex vertex, 10 are within 0.001, 0.01 and 0.1, 12 within 1, 200 within 10, 209 within 100 |
| `break_without_plausible_hitter` | **0** | n/a | was 54 (section 7.2) |
| `break_through_solid` | 0 | n/a | |
| `break_live` (counted) / `break_occluded` | n/a | 1,188 / **123** | to be decided on a replay with the verify flags |
| `pass_through` | 179 | 179 | |
| `position_snap` (edge or unexplained) | 162 | 162 | was 1,128: 562 + 404 of those are frozen ticks now classified by the freeze rule |
| `freeze:after_break` (counted) | 404 | 4,642 | live: 4,238 of them are recorded hitlag; 404 are within the window without hitlag |
| **`freeze_unexplained`** | **1,685** | **1,685** | no recorded hitlag on any of them; **every recorded hitlag freeze falls in the window** (0 of 4,238 left out) |
| `beyond_map_bounds` / `beyond_camera_bounds` | 57 / 97 | 57 / 97 | the probe's falls |

**The 1,685 `freeze_unexplained` events** (1,206 distinct states, in 160 of the 208 traces):

- by status: 652 `EscapeB`, 464 Mario's grounded down-B (227), 326 `EscapeF`, 64 `LandingLight`, 36 airborne up-B (226), and
  others;
- 1,649 are grounded with a non-zero ground velocity;
- the position explains almost all of them:
  - **562** stand exactly at a floor end or its 40-unit inset (the game's stop-edge and teeter snaps; M8);
  - **1,087** stand exactly 150 units (Mario's half-width) from a floor end, with the side point against the wall at a concave
    corner (a grounded wall stop);
  - **36** are airborne (up-B frames moved by the animation).
- At run 2's size, this rate (0.50 % of ticks) gives about 18,000 events per run. A refinement is proposed in section 10.

### 9.3 Run 3 anomaly keeping: new files (no inherited file edited except the fake game)

- **`tools/frs/run3_anomaly.py`:**
  - `nonfinite_fields`: null, NaN or inf anywhere in the observation and spatial blocks. None in 348,584 stored lab replies.
  - `JobObserver`, worker side:
    - D6 on burst ticks: it raises `NonFiniteReply` on the first bad reply;
    - it runs `LiveScanner` on burst ticks;
    - it rebuilds the burst with `m8_rd_cells`' own functions: reaches, chain, breaks, labels.
  - `AnomalyIngest`, a mixin placed after `DeterministicSchedule`, so it runs at in-order ingest. It writes:
    - `glitch_events.jsonl`, with the source filled from the dispatch and the build identity;
    - `anomaly_bursts.jsonl`, with the words from tick 0, kept whatever the archive does with the burst;
    - `anomalies/nonfinite_<id>.json.gz`, with the words, the step, the fields and the replies from L.
- **`tools/frs/run3_worker.py`:**
  - a transparent process proxy: replies are returned unchanged, and attribute writes such as `failed` reach the real process;
  - `run_job`: `frs_worker.run_job`'s mapping, plus the non-finite case, which returns the burst truncated before the tick as an
    ordinary ok result (`end_reason` "nonfinite"); the engine's own `commit` ingests the earlier reaches;
  - `worker_main` and `Run3Pool`.
- **`rl/m8_rd_fakegame.py`:** opt-in `FAKEGAME_NONFINITE_P` / `_SEED` / `_FIELD` / `_MIN_STEP`. It sets a null keyed on the job's
  word stream, so the same words always meet the same null.
- **`tools/frs/run3_anomaly_tests.py`:** the S4-5 tests (section 9.4).

### 9.4 S4-5 tests and regressions (b757266 plus the working tree)

| suite | result |
| --- | --- |
| `python -B tools/frs/run3_anomaly_tests.py` | **9/9** |
| ↳ in-process | `run_job` == `frs_worker.run_job` on 3 jobs; a null in the key or in a non-key field truncates the burst and keeps the earlier reaches; a null in the prefix stays a prefix mismatch; proxy transparent; detector rules; freeze window 0/11 → hitlag, 12/none → unexplained; `LiveScanner` == `Detector.run` |
| ↳ `e2e_engine_read_only` | same dispatches, cells and verified clears as the plain `DetSearch`; self-check 90/90 |
| ↳ `e2e_nonfinite_keeps_running` | 77 nulls injected, run reached `DISPATCH_CAP`, 77 replay files, both runs identical (D4), saved words replay to the null at step 503 |
| `test_glitch.py` | 36 OK (1 skipped) |
| `m8_rd_tests.py unit` | 47/48 (`tracked_files_unchanged`: uncommitted edits) |
| `det_schedule_tests.py` / `infra_port` / `infra_log` | 5/5, 7/7, 4/4 |
| `frs_tests.py` / `crossing_search_tests.py stub` | 31/31, 5/5 |
| `analysis_tests.py` | 3/4 (`charts_render`: no matplotlib, owner's choice) |

A bug found by the end-to-end test and fixed: the fake game's injection used a chained assignment that wrote the null into a
detached copy.

## 10. Proposals waiting for the owner

1. **Masks of inherited cells: zero ticks.** Run 3's archive = run 1's then run 2's `cells.jsonl`, last row per cell id: 37,294
   cells, 0 without a key, 0 whose mask disagrees with its level. The 1,906 maskless run 2 dispatches (1,490 cells) all get
   their key from run 1's file, and the key level equals the dispatch row's level for all 1,906. No replay is needed (0 native
   ticks). The refusal stays as a guard; it triggers on nothing today.
2. **Freeze refinement.** A grounded freeze whose side point lies on a wall line (within ε) becomes a counted `wall_stop`; one
   at a floor end or its 40-unit inset becomes a counted `edge_stop` (M8). On the splice set this leaves 36 `freeze_unexplained`
   (airborne up-B) of 1,685; 562 edge stops, 1,087 wall stops.

Not started: step 5 (end records) and later steps.

## 11. 2026-11-05: both proposals approved and applied

**Owner's decisions:**

0. Commit the step 4 work locally in coherent commits, no push:
   - cc9d41d: fake game;
   - dbdcc9f: run 3 anomaly keeping;
   - d1bbcb5: decisions;
   - 549172b: inventory;
   - 45c3c38: this log.
   The owner's handoff edit, the probe-result doc and `tools/audit/trig_ab_replay.py` stay uncommitted.
1. **Masks: approved**, after checking that no cell has rows with different masks.
   - **0** such cells: 37,294 cells, 181,657 rows in run 1's and run 2's `cells.jsonl`, 32,160 cells with several rows.
   - 0 key conflicts, 0 masks disagreeing with their level, 0 cells without a key.
   - Applied: `tools/frs/run3_archive.py` (272e165) merges the keys in inheritance order (last row per cell), refuses any
     inconsistency, and makes unknown an explicit group.
   - Run 2's groups with the merged keys: level 9 = 8,078 / 8,027 / 4,879, the record's numbers, and **no unknown group**. With
     run 2's file alone, the unknown group would hold 42 / 287 / 738 / 839 dispatches at levels 9 to 6.
   - `tools/frs/run3_archive_tests.py`: 2/2.
2. **Freeze refinement: approved**, with these details:
   - wall and edge stops are counted, not logged;
   - per-class counts go in the run summary, and the first N per class are logged for audit;
   - the floor-end teleport stays an `edge_snap`;
   - the 36 airborne up-B freezes stay `freeze_unexplained`.
   - **N = 60** (rule of three: 0 misclassified among 60 bounds a class's error rate below 5 % at 95 % confidence).
   - Applied in a0bbd90 (`detect.py` only) and d8db719 (`AnomalyIngest`: counts summed into `summary.anomalies.counts`; samples
     go to `glitch_samples.jsonl`, the first 60 per class of the run in dispatch order; samples are never anomaly events).

**Splice-set volumes after the refinement** (208 traces; offline and live agree except where shown):

| class | count |
| --- | ---: |
| `freeze_unexplained` | **36** (was 1,685); all airborne up-B, none with recorded hitlag |
| `freeze:wall_stop` (counted) | 1,087 |
| `freeze:edge_stop` (counted) | 562 |
| `freeze:after_break` (counted) | 404 offline, 4,642 live (4,238 recorded hitlag, all inside the window) |
| `position_snap` (`edge_snap`, the teleport itself) | 162 |
| `corner_pass` counted / `corner_pass_near_vertex` | 215 / 10 |
| `pass_through` | 179 |
| `break_live` / `break_occluded` (live) | 1,188 / 123 |
| `line_crossing`, `break_without_plausible_hitter` | 0, 0 |

**Tests:** `run3_anomaly_tests.py` 10/10 (new: `unit_freeze_stop_classes`); `test_glitch.py` 36 OK; `run3_archive_tests.py` 2/2.

**Queued, not now (owner):** an offline replay, under the verify flags, of the 123 breaks flagged as possibly through a wall.
It is native and needs the owner's go.

## 12. Step 5: the plan rests on a false premise (stopped for a decision)

- **Finding:** run 2's `checks.jsonl` rows (3,916) hold only booleans and digests: `chain_equal`, `end_digest_equal`,
  `key_equal`, tick counts. **They do not hold the end observation tuple** (`job["end"]`, the 17 fields the worker compares at
  the cell's tick).
- Neither run 1's nor run 2's `cells.jsonl` holds it either: rows carry `end_digest` and `chain`, not `end`. Run 2 kept the end
  records in memory only.
- So REVIEW_2026-11-03 O10 ("import the check rows as end records") cannot be done offline, and **none of the 37,294 cells has
  an end record on disk**.
- What the check rows do give: 3,916 cells whose prefixes were verified to reproduce on 30a3913b.
- Options (measured offline):
  - **A. Fused first dispatch (recommended, 0 extra ticks).**
    - A cell without an end record is dispatched directly. The worker's prefix replay validates it by the stored record digest
      and chain, which cover every observation field the tuple comparison checks (host_frame excluded on both sides, JSON
      types included).
    - The observed tuple at L is returned and stored as the cell's end record from then on, in run 3's `cells.jsonl`.
    - No lazy checks, so D4 is no longer refused.
    - Mechanism: a small explicit change to `rl/frs_worker.py` (`end` absent → no tuple comparison, digest and chain still
      checked, the tuple returned), or a run3_worker shim that fills `job["end"]` from the observed reply at step L − 1.
  - **B. Native harvest:** one replay per prefix-trie leaf: 7,820 replays, 9,171,630 ticks, end records for all 37,294 cells.
    About 1.6 h on 5 workers at run 2's check rate. Needs a go.
  - **C. Run 2's lazy checks:** up to 41.2 M ticks if every cell is drawn; run 2 paid 19,772 worker-seconds (13.9 %) for 3,916
    of them; D4 stays refused.

## 13. Step 5: option A (fused first dispatch), end records, D4 in run 3

**Owner's decision (2026-11-05):** option A as an explicit change to `rl/frs_worker.py` (not a shim), under four conditions. Option B
(the native harvest) is not needed. The 123 `break_occluded` breaks stay queued.

### 13.1 The change (uncommitted)

- **`rl/frs_worker.py`**, the only lab-code file changed:
  - `FUSED_END_MODE = "fused_first_dispatch_v1"` and `fused_prefix(end_t)`.
  - A job with `end_mode == FUSED_END_MODE` carries `end = None`. At L the record digest and the chain are compared as always, the
    tuple comparison is skipped, and the observed 17-field tuple is returned in `prefix["end"]`. A difference raises the same
    `prefix_end` mismatch before any burst word.
  - Refused as an error before any process is acquired: a fused job with an end record, a fused job at L = 0 (the real archive's
    lowest cell tick is 461), an unknown end mode.
  - A job without `end_mode` (every run 1 and run 2 job) runs the old code: `if L > 0:` became `elif L > 0:` after the new branch.
- **`tools/frs/run3_worker.py`**: a D6 truncation of a fused dispatch carries the fused prefix.
- **`tools/frs/run3_search.py`** (new):
  - `Run3Archive`: every eligible cell is dispatchable; `verified` means "end record known"; `unverified_eligible()` is 0, so
    D4's refusal does not apply; `end_pending()` counts the cells whose next dispatch is fused.
  - `adopt_archive`: run 2's freshly loaded archive becomes a `Run3Archive` in place. Step 8's loader of runs 1 + 2 replaces it.
  - `Run3Core(ResumeSearch)`: no eager or lazy check; `Run3Pool` workers; key family `crossing3`.
    - End records are stored at ingest, in dispatch order, as an `end_record` row of `cells.jsonl`. NEW / REPLACED rows carry `end`.
    - A second fused dispatch of one representative must match the stored record in the 16 compared fields (else SEARCH_INVALID);
      the first record stays.
  - `Run3Search(DeterministicSchedule, AnomalyIngest, Run3Core)`.
- **`tools/frs/run3_archive.py`**: `merged_cells` reads end records back by words digest; an `end_record` row is never the
  representative; two records of one representative that differ in a compared field are refused (`end_conflicts`).
- **`tools/frs/run3_search_tests.py`** (new): 9 tests.

### 13.2 Condition 1: 17 fields, one at a time (fake game, L = 37, 68 processes)

The comparison checks **16 of the 17 fields**: `obs_diffs` ignores `host_frame`, and the record (`m8_rd_record_v1`) leaves it out.

| fields | value change (int + 1, next float) | JSON type change (int <-> integral float) |
| --- | --- | --- |
| 16 compared fields | **16/16 detected in both modes**; the record digest changes for all 16 | **14/14** (2 non-integral floats: n/a) |
| `host_frame` | not detected in either mode; digest unchanged | not detected in either mode |

- Detection kind: `prefix_end`, except `input_tick` + 1, which the tick contract catches first (`consumed_tick`) in both modes.
- Every detection: 0 burst words; the fake game stepped exactly L times.
- `host_frame`, as today: the stored path reports `host_frame_equal: False`; the fused path stores the altered value.

### 13.3 Conditions 2 to 4

- **2, mismatch** (`e2e_fused_mismatch`; chain of one inherited cell and record digest of another set wrong):
  - each tampered representative: one dispatch, `prefix_end`, fused, 0 words, 0 ticks, quarantined, never dispatched again;
  - no `end_record` row; the run 2 event in `run_log.jsonl`; the preserved prefix holds exactly L replies; DISPATCH_CAP.
  - The quarantine belongs to the representative, as in runs 1 and 2: a faster arrival at the key later becomes a new
    representative (seen in one earlier run; asserted when it happens).
- **3, run 2's path**:
  - `unit_run2_path_equals_pre_change`: 10 jobs give results identical to the pre-change file (39e20ca, via `git show`).
  - suites: `frs_tests` 31/31, `crossing_search_tests stub` 5/5, `crossing_search_run2_tests stub` 4/4, `det_schedule_tests` 5/5,
    `run3_anomaly_tests` 10/10, `run3_archive_tests` 2/2, `test_glitch` 36 OK, `m8_rd_tests unit` 47/48. The one failure is
    `tracked_files_unchanged` (the uncommitted changes and the owner's handoff edit).
  - `crossing_search_run2_tests real` fails at its pin of run 1's lab code digest. That pin has failed since the merge
    (6f3a4989 != 0b248a9e); every assertion before it passed on the real run 1 folder.
- **4, O10 and D4** (`e2e_fused_runs`, 120 dispatches, 3 workers):
  - D4 accepted the archive (`schedule.json`, no refusal).
  - Two same-seed runs: identical dispatches, cell events (`end_record` rows included), end records (16 fields) and anomaly bursts.
  - Every inherited representative's first dispatch was fused and stored its end record (69 fused, 68 stored, 1 repeat). Later
    dispatches used the stored record with the full comparison (1 such dispatch).
  - Four stored records equal fresh fake-game replays of the cells' words.

### 13.4 Lab code digest

- Runs 1 and 2: `0b248a9e` (34 files). The merge (`rl/port_lease.py`): `6f3a4989` (35). Now: **`81b88be6`** (35); only
  `rl/frs_worker.py` changed (`fb7d3a33` -> `6a968829`).
- Run 1's and run 2's tools pin run 1's digest (`expect_code`), so they already refused this tree before this change.
- `tools/frs/run3_*.py` are not in the manifest (`rl/` only). The run 3 config records `run3_core_file_sha256`.

## 14. Before step 6: stored records under forced redraws; the run 3 digest and the rebuild (proposed)

**Owner (2026-11-05):** step 5 committed (c3bfce3 worker, 212998e run 3 files, 82f3175 log). Before step 6: (1) a targeted test of
stored end records, committed separately; (2) a digest covering every file run 3 depends on, the choice explained before
implementing; then the plan of the single rebuild. Nothing native without a go.

### 14.1 Stored end records under forced redraws (built)

- An end record on disk only helps if a later run reads it, so this needed a loader:
  - `run3_archive.end_records(files)`: every stored record by (cell id, words digest), from `end_record` rows and from the `end`
    of NEW / REPLACED rows; the first per representative; conflicts reported; each file's sha256.
  - `Run3Archive.import_end_records`: attaches a record only to the representative with the same cell id AND words digest (a
    record of a representative replaced since is never attached to the new one).
  - `Run3Core`: `P["end_record_files"]` (optional) imported before the open; files, sha256 and counts in `config.json`
    (`run3.end_import`) and the summary. A conflict between two records of one representative is a refusal.
- Test `e2e_stored_records` (fake game; a test-only engine whose dispatch n draws the n-th of 8 fixed cells in a cycle, under D4):
  - run x, 48 dispatches: the 8 first dispatches fused and stored their records; **40** later dispatches compared against them.
  - a copy of x's `cells.jsonl` with ONE compared field of ONE record changed (`position_x` of cell 2, next float up).
  - run y imports that copy: 8 records imported, 0 fused, **47** dispatches compared against records read from disk, all clean.
  - the corrupted cell: dispatched once (n 3): `prefix_end`, `field_diffs` = {position_x: [true, corrupted]}, chain and record
    digest equal, 0 burst words, 0 ticks, the fake game stepped exactly L = 493 times, quarantined, run 2's event and log.
- `unit_end_record_import`: attach by (cell, digest) only; conflicts reported.
- The bench now rebuilds its synthetic run 1 (run 1's engine, no D4) up to 3 times when it has no verified clear (it had none once).
- `e2e_fused_runs` failed once on a correct engine path: a fused first dispatch stores nothing when the cell was replaced by a faster
  arrival ingested before it (`fused_stale`; e.g. dispatch 8 fused cell 116 at tick 688, dispatch 6 replaced it at 668). The test now
  accepts exactly that case; the rerun had 2 such dispatches and passed.
- Suite: `run3_search_tests.py` 11 tests, all passing (the full run 10/11 before that test fix, then `e2e_fused_runs` alone);
  `run3_archive_tests.py` 2/2. Committed aef1c70.

### 14.2 Proposed, waiting for the owner

- **Run 3 digest:** a separate run 3 manifest (recommended) rather than extending the lab manifest. Details in the reply of
  2026-11-05; closure today: 31 repo files (20 `rl/`, 7 `tools/frs/`, 4 `tools/glitch/`), every `rl/` one already in the lab manifest.
- **Step 6 plan:** one incremental US Release build in `build-us` (trig option OFF), the new executable paired with the
  registered runtime files in a lab probe folder, then M6, Raphnet, the A/B replay against 30a3913b, a stored-chain probe and one
  launcher episode. Preconditions checked (zero ticks): D: archive 6/6 OK, no native file differs from HEAD, submodules clean.
  A build would copy the checkout-root `f3d.o2r` (bf16e8dd) over the registered one (73ab91ef) in `build-us/Release`.

## 15. 2026-11-05: run 3 code manifest; step 6 deferred; step 7 opened

**Owner:** (1) separate run 3 manifest approved, without the run-time check of loaded files; (2) step 6 deferred: run 3 runs on
30a3913b as is, record the plan and the `f3d.o2r` hazard; (3) step 7: sort the run 3 decisions into DECISIVE (one at a time) and MINOR
(one table).

### 15.1 Run 3 code manifest (`tools/frs/run3_manifest.py`)

- Every repository file run 3 imports, computed in a fresh interpreter, recorded by the plan as `P["run3_code_digest"]`; the open
  refuses (nothing launched) when it is missing or differs; recomputed at the close (a change is SEARCH_INVALID); recorded in
  `config.json` (`run3.code`). The lab manifest is recorded as before and unchanged (`81b88be6`).
- **Finding: an import-time closure misses run-time code.** `rl/battleship_process.py` (the launcher) and `rl/port_lease.py` were
  missing from the first version: `m8_rd_worker` imports the launcher inside a function. So did `m7q_status_table`
  (`m8_rd_cells.Classifier`, every worker) and `m7f_targets` (`m7g_fixture.crossing_evidence`, every verification) - neither is in
  the lab manifest either.
- **Rule:** the entries are run 3's modules, the lab runner's explicit list (`frs_run.CODE_MODULES`) and three function-level
  imports on run 3's paths (`m7q_status_table`, `m7g_spatial`, `m7f_targets`). Nine function-level imports are excluded by name, each
  with the function that holds it (`m8_rd_session`'s rd gates and reports; four fixture and study helpers). Following every
  function-level import instead would add 87 training and gate files.
- **Today:** 50 files (38 `rl/`, 8 `tools/frs/`, 4 `tools/glitch/`), digest `7d8d6fd1`. Every lab-manifest file except
  `rl/frs_tests.py` is in it, with the same hash.
- **Tests:** `unit_run3_manifest` (determinism; the files; every function-level import covered or excluded; on a copied tree an
  edit to `tools/glitch/detect.py` changes the digest and names only that file); `e2e_code_digest_refusal` (a wrong recorded digest:
  exit 2, `refused_*.json`, no run folder); every engine run checks the recorded digest and its unchanged value at the close.

### 15.2 Step 6 deferred

Recorded in `docs/rl_decisions_2026-11-04.md` §4: run 3 on `30a3913b` (port leases block the race, identity `unverified`,
`BATTLESHIP_REQUIRE_IDENTITY` not set), the rebuild plan as prepared, and the hazard: a build in `build-us` copies the checkout-root
`f3d.o2r` (`bf16e8dd`) over the registered `73ab91ef` in `build-us/Release`. The stored-chain probe and the launcher script are not
built.

## 16. Step 7: run 3 decisions

### 16.1 MINOR table: approved as a whole (2026-11-05)

Runs 1 + 2 merged as the start (37,294 cells, best 1,245 replayed at open, reference 1,885); eligibility bound 1,220 fixed for the run;
O2, O3 closed; D4 on; O5, O8, O9, O11 deferred; secondary representatives off (Q6); text replay for new verified bests only, a bk2 for
every verified clear; claims replayed only when faster (Q10); run 2's CONT arm (120 words, 6 segments, window 20); 5 workers +
standby, 480 min, 80 M ticks, mismatch limit 3, registered memory budget, plateau rule Q11; lab digest recorded, run 3 digest
enforced, identity unverified, no native log sink; anomaly keeping on; tools committed before the launch, lab backed up after;
Q8 registration and the 123 breaks' replay not before run 3.

### 16.2 DECISIVE 1, selection inside a level: approved as recommended (2026-11-05)

- Level weights unchanged (decay 0.5). Group share: rate rho = (breaks + new earliest arrivals at the next level + 1) / (dispatches
  + 2) over the group's last 200 dispatches, warm-started from run 2; normalised, then floored at 1 / (4 x groups at the level).
- Cell weight: (1 + arrival rank in the group)^-1 x max(0.05, 1 / (1 + dispatches since the representative was set)) x 0.1 per
  claimed clear; run 2's seen, bonus and pace terms dropped; dispatch counts carried from runs 1 + 2 reset (kept as information).
- **Addition (owner):** every hour the run summary records each group's share, the top 10 cells' share per group and the earliest
  arrival per level; every parameter is recorded in config.json.
- Real numbers behind it: the review's formula as written gives every run 2 group the floor (rates 0.0001-0.042 < phi 0.083), equal
  thirds; normalised then floored: level 9 masks 64 / 2 / 256 = 8 / 51 / 42 %, level 8 masks 66 / 258 / 320 = 32 / 60 / 8 %. The 10
  earliest cells of each group got 0.1-1.6 % of its dispatches in run 2; simulated with the approved weight, 28 % of (9, 2), 61 % of
  (9, 256), 10 % of (8, 258).

### 16.3 Eligibility answer, warm-start fix, DECISIVE 2 (demotion): approved (2026-11-05)

- **Eligibility (E7, 1,220):** a strict bound for a gain of at least the 24-tick margin; the remaining time is taken as its minimum,
  1 tick (completion >= L + 1), not estimated. It does cut the 511 level-9 cells at 1,221-1,244 that could beat 1,245 by less than
  24 ticks. **Owner: the margin is kept** (the goal needs gains of about 780 ticks, so new routes, not trimmed endings).
- **Warm-start fix (refines DECISIVE 1):** each group's 200-dispatch window starts as 200 pseudo-dispatches at the group's whole-run-2
  rate; run 3's own dispatches then roll the window. Reason: the literal last-200 warm start put (9, 2) (90 of run 2's 136 clears, 0
  in its last 200) on the floor: level 9 masks 64 / 2 / 256 = 14 / 14 / 71 %; with the fix 14 / 46 / 40 %, level 8 masks 66 / 258 /
  320 = 34 / 58 / 8 %.
- **DECISIVE 2:** a group is demoted when, over its whole history (run 2 + run 3), it has >= 1,000 dispatches, 0 breaks, 0 new
  earliest arrivals at the next level and >= 75 % falls; a demoted group gets a quarter of the floor (phi / 4); it exits on its first
  break or new earliest arrival. On run 2's data it demotes exactly (9, 64) (8,078 dispatches, 91 % falls, 20.1 % of the ticks) and
  (8, 320) (1,011, 81 %); start shares with the fix: level 9 masks 2 / 256 / 64 = 52 / 46 / 2 %, level 8 masks 66 / 258 / 320 =
  36 / 62 / 2 %. P(0 breaks in 1,000) at the lowest productive level-9 rate (46 / 4,879) = 7.7e-5.
- **Addition (owner):** every demotion and exit goes in the hourly summary with the group's counters at that moment; the run summary
  gives each group's fall rate, so the 75 % threshold can be checked on run 3's data.

### 16.4 DECISIVE 3, anchors: approved as recommended (2026-11-05)

- **Anchor set:** in each (level, mask) group, the 3 earliest eligible cells of each resource class (Q5); no descendant rule. A cell
  stops being an anchor when 3 faster arrivals of its class displace it or when it becomes ineligible.
- **Share:** a group draw goes to its anchors with probability 0.5 x w, w = the highest weight among them; otherwise the DECISIVE 1
  rank draw. Each anchor's weight starts at 1 when it becomes an anchor (all anchors at run 3's start), halves after each of its
  bursts without success (Q4), floor 1/8, resets to 1 on success. Success = the burst creates a new anchor in a deeper group (at level
  9: a claimed clear faster than every earlier claim).
- **Draw:** highest weight, then fewest anchor bursts, then earliest arrival, then cell id (rotation, replacing the review's "most
  lead"). Demoted groups: the same rule inside their reduced share.
- **Records:** hourly per group the anchors' share of draws, bursts, successes and each anchor's class, tick, weight and bursts;
  config.json: k, start share 0.5, floor 1/8, success rule, draw order.
- **Real numbers behind it (zero ticks):** break rate per dispatch by class, levels 7 / 9: A0 0.61 / 0.45 %, A1 1.75 / 0.73 %, A2
  2.86 / 0.91 %; every run 2 lineage link after level 6 is A2; the earliest cell is A0 in 4 of 11 groups. The review's "most lead"
  draw piles anchor draws on one cell ((7, 322) A0 at 493: 30 -> 153 a night). The descendant rule adds 5 anchors to 121. Simulated
  night (no successes): anchors take 6-10 % of each group's draws; the 3 earliest A2 / G cells of (7, 322) get 42 / 43 dispatches
  (rank draw alone 12 / 18), of (8, 258) 92 / 86 (26 / 16); top-10 shares move by 0 to 2 points. Limits: anchors cover 3 of the 12
  run 2 lineage links at levels 8-9 (class ranks 0-56); the crossing's parent (L7 @ 978, A2) was at class rank 1,177 (DECISIVE 4).

### 16.5 Analysis scripts

The numbers in 16.1-16.4 come from `tools/analysis/run3_design/` (README there: which script backs which decision). These are
zero-tick, read-only scripts; their results go to `logs/run3_design/` (Git-ignored). Re-run from that folder on 2026-11-05, they
reproduce every number quoted above (the D1-D2 ones were inline commands in the session before; the D3 simulation assumes 80 %
exploitation, as when it was decided).

### 16.6 DECISIVE 4, breadth: approved as recommended (2026-11-06)

**Owner's brief:** start from the cell that made run 2's crossing; do not take 20 % as a given; cover new target orders, demoted
groups, anomaly bursts and the eligibility bound; options with simulated cost and effect, then a recommendation.

- **Share:** 20 % of dispatches are breadth draws; the other 80 % are DECISIVE 1-3 (exploitation).
- **Draw:** count-based, weight 1 / (1 + dispatches of the cell id in runs 1-3), the count growing with run 3's own dispatches
  (exploitation and breadth); eligible cells only (levels 6-9, tick <= 1,220: a cell above the bound can only lead to arrivals
  above it); demoted groups excluded.
- **Anomaly trigger, not a share:** a burst with an event of a class seen fewer than 3 times in the run so far (line_crossing,
  inside_solid, floor_switch_unlinked, D6 non-finite) gives each of its kept cells at or after the event up to 3 breadth draws, the
  trigger draws capped at 10 % of the breadth budget. break_occluded and the ordinary classes are recorded only.
- **No separate order-niche stream** (the order question is answered by 4b's unit).
- **Records:** hourly, breadth draws by level, group and niche; the never-dispatched eligible pool; useful breaks from breadth
  against exploitation; every trigger (class, burst, cells, draws given, cap). config.json: share, weight rule, eligibility,
  exclusion, trigger classes, rarity threshold, draws per cell, cap.
- **Real numbers behind it (zero ticks, `d4_breadth.py`):**
  - The crossing cell (cid 7092, L7 @ 978, A2, mask 322) was made at run 1 ingest 23,281, never dispatched in run 1, and first
    dispatched at run 2 n 14,659 (a fall that reached level 8 at 1,042): 22,075 dispatches of waiting. At that moment 19,029 cells
    were eligible at levels 6-9, 8,635 of them never dispatched. At run 3's start its representative is at 935 (group rank 4,734 of
    7,331).
  - Expected dispatches until a 20 % breadth draw reaches it, at that moment: uniform 95,145, level-uniform 133,380, group-uniform
    296,505, count-based (never-dispatched first) 43,175.
  - Run 2's useful (7, 322) bursts came only from cells at ticks 897-1,178.
  - One simulated night (39,309 dispatches, mask groups), expected useful breaks u6 / u7 / u8 / clears: no breadth 47.7 / 45.3 /
    690.3 / 98.3; count-based 20 % 135.6 / 95.3 / 586.4 / 79.6; uniform 20 % 113.5 / 91.9 / 623.6 / 80.5; order-niche stream 20 %
    53.1 / 61.5 / 609.6 / 85.7. The (7, 322) productive band: 164 draws with no breadth, 668 count-based. Cost of count-based 20 %:
    level-9 draws 16,787 (20,965), the 10 earliest of (9, 2) 2,523 (3,375), A2 / G anchors of (8, 258) 178 (232).
  - Demoted groups in the breadth pool: uniform 20 % gives them 937 draws (524 without) for slightly fewer useful breaks.

### 16.7 DECISIVE 4b, budget unit (level, mask, order niche): approved (2026-11-06)

- **Unit:** DECISIVE 1-3 (the group rate and share, the floor phi, demotion, anchors) are computed per (level, mask, order niche)
  instead of (level, mask). The DECISIVE 1 rate counts useful breaks only: a break whose next-level arrival is <= 1,220; at level 9 a
  claimed clear <= 1,220. e is unchanged (a new earliest arrival in a deeper group, now a niche group; at level 9 a claimed clear
  faster than every earlier claim).
- **Order niche of a representative:** (the mask of the run 1 seed its lineage starts from, the targets broken after the seed, in
  break order). A child = its parent representative's niche + the targets its burst broke at or before the child's tick, ordered by
  break tick, ties by target id; a seed = (mask, ()). Same-mask seeds share a niche (the pre-seed order is not archived). Run 3 writes
  `niche` on NEW / REPLACED rows and derives it at open for inherited rows.
- **A cell's group** = (level, mask, niche of its current representative); level and mask never change, so a cell moves only when a
  replacement's lineage has another order. On a move from A to B:
  - every dispatch stays credited to the group of the representative dispatched (the 200-dispatch window, DECISIVE 2's counters);
    nothing transfers;
  - demotion stays with the group (the exit rule is unchanged);
  - staleness (DECISIVE 1) resets as for any replacement; the breadth count (DECISIVE 4) is kept by cell id;
  - ranks: removed from A, inserted into B by tick;
  - anchors recomputed in both groups: a new anchor starts at w 1 / 0 bursts, a displaced third anchor loses status and weight;
  - a group with no eligible cell drops out of the draw (phi recomputed) and returns with its history.
- **Four rules (owner, approved):** (1) a same-niche replacement of an anchor resets it to w 1 / 0 bursts; (2) a new niche group's
  window starts as 200 pseudo-dispatches at its level's pooled rate; (3) DECISIVE 2 stays on all breaks; (4) level 9 literal: only
  claimed clears <= 1,220 are useful.
- **Corrections from the exact attribution** (`d4b_niche_units.py`: each run 2 dispatch credited to the niche of the representative
  actually dispatched, 39,309 / 39,309 found by start tick):
  - the dead level-7 niche (7, 322, '322:') has 4 useful breaks in 3,084 dispatches (0.13 %), the productive (7, 322, '326:2') 55 in
    1,628 (3.4 %); `d4_breadth.py`'s approximation (the current representative's niche) gave 0 / 2,704 and 59 / 1,987;
  - group moves are common: 15,770 of run 2's 71,237 replacements (22 %; levels 7 / 8 / 9: 4,362 / 6,344 / 5,064); run 1 2,607 of
    73,126;
  - the niche derivation: 5,221 / 5,221 single-target steps agree with the bursts' break lists; 168 multi-target steps are ordered by
    break tick.
- **Start (runs 1 + 2, bound 1,220):** 14 groups (11 mask groups), 153 anchors (121). rho0 = (200 x (bu + e) / n + 1) / 202.

  | group (level, mask, niche) | eligible | anchors | run 2 n / falls / b / bu / e | rho0 | share | demoted |
  | --- | ---: | ---: | --- | ---: | ---: | --- |
  | (9, 2, 326:2-6-8) | 433 | 12 | 4,155 / 72 % / 22 / 0 / 2 | 0.0054 | 51.2 % | no |
  | (9, 256, 326:2-6-1) | 53 | 10 | 4,153 / 72 % / 46 / 0 / 0 | 0.0050 | 46.7 % | no |
  | (9, 64, 326:2-8-1) | 1,054 | 6 | 7,996 / 91 % / 0 / 0 / 0 | 0.0050 | 2.1 % | yes |
  | (8, 258, 326:2-6) | 1,422 | 12 | 1,859 / 66 % / 67 / 52 / 11 | 0.0385 | 52.1 % | no |
  | (8, 66, 326:2-8) | 2,519 | 12 | 4,838 / 68 % / 93 / 92 / 3 | 0.0244 | 33.0 % | no |
  | (8, 258, 322:6) | 320 | 11 | 2,637 / 13 % / 118 / 0 / 3 | 0.0061 | 8.2 % | no |
  | (8, 320, 326:2-1) | 127 | 9 | 695 / 96 % / 0 / 0 / 0 | 0.0050 | 6.7 % | no (n < 1,000) |
  | (7, 322, 326:2) | 3,555 | 12 | 1,628 / 50 % / 58 / 55 / 7 | 0.0427 | 66.9 % | no |
  | (7, 322, 322:) | 3,603 | 12 | 3,084 / 37 % / 34 / 4 / 0 | 0.0062 | 9.8 % | no |
  | (7, 70, 326:8) | 397 | 12 | 157 / 15 % / 0 / 0 / 0 | 0.0050 | 7.8 % | no |
  | (7, 266, 330:6) | 139 | 12 | 226 / 1 % / 2 / 0 / 0 | 0.0050 | 7.8 % | no |
  | (7, 322, 330:3) | 173 | 9 | 113 / 57 % / 0 / 0 / 0 | 0.0050 | 7.8 % | no |
  | (6, 330, 330:) | 4,434 | 12 | 1,277 / 43 % / 30 / 30 / 3 | 0.0305 | 51.2 % | no |
  | (6, 326, 326:) | 4,235 | 12 | 1,312 / 38 % / 30 / 30 / 2 | 0.0291 | 48.8 % | no |

  phi: level 9 1/12, level 8 1/16, level 7 1/20, level 6 1/8; no group is on the floor. Against the mask groups: level 9 52.4 /
  45.6 / 2.1 % (almost the same); level 8 (8, 258) splits into 52.1 % productive and 8.2 % unproductive; level 7 (7, 322) had 56.3 %,
  two thirds of it drawn into the dead niche. Demotion is the same with bu in place of b; with bu, (9, 256) would sit 3 points of fall
  rate from demotion, hence rule (3). Level 9 with any claimed clear counted: 39.3 / 58.6 / 2.1 %.
- **Tests (approved):** niche inheritance (units; the engine's derivation equals the offline one on all 37,294 cells of runs 1 + 2);
  moves (a scripted A -> B move: membership, ranks, anchors in both groups, a displaced third anchor, staleness reset, breadth count
  kept, both groups' windows / counters / demotion unchanged, an emptied group leaving and returning, the pooled warm start of a new
  niche); end to end on the fake game: two same-seed runs with group moves identical under D4 (dispatch rows except clock fields,
  cells.jsonl rows with niche and group, end records, hourly records), with a vacuity guard of >= 5 group moves.

## 17. Step 8: run 3 built (2026-11-06)

**Owner (2026-11-06):** the 4b table and its four rules approved; DECISIVE 4 and 4b recorded and committed (71d5beb). Then step 8: run 3 by
every decision (DECISIVE 1-4b, MINOR table, step 4 anomalies, step 5 fused dispatch, D4, run 3 manifest) with fake-game tests; the hourly
summary must show each group's share, the top 10, the earliest arrival per level, demotions and exits, fall rates, anchors, breadth draws and
the anomaly triggers; then a 20-30 min native smoke run proposed (a go for it, a separate go for the night).

### 17.1 Files

- `tools/frs/run3_select.py` (new, pure): order niches, (level, mask, niche) groups, DECISIVE 1 shares with the warm-started window, DECISIVE 2
  demotion, DECISIVE 3 anchors, DECISIVE 4 breadth and anomaly triggers, the hourly record.
- `tools/frs/run3_load.py` (new): runs 1 + 2 checked and merged, every row's niche from its exact lineage, run 2 replayed with each dispatch
  credited to the niche of the representative actually dispatched (the 4b history).
- `tools/frs/run3_export.py` (new): a .btti and a .bk2 per verified clear (the inverse of `tools/bk2_to_btt_inputs.py`), the native text
  replay of new verified bests.
- `tools/frs/crossing_search_run3.py` (new): `Params3`, the plan of runs 1 + 2, the engine `Run3Night` (D4, anomaly keeping, fused first
  dispatches, the selection), hourly.jsonl / hourly.md, triggers.jsonl, best_times.jsonl, exports.jsonl, text_replays.jsonl, report.md,
  progress.md, the command line (`plan`, `run`).
- `tools/frs/crossing_search_run3_tests.py` (new).
- `rl/m8_rd_fakegame.py`: an opt-in text-replay mode (SSB64_BTT_INPUT), test helper only.
- `tools/frs/run3_manifest.py`: `crossing_search_run3` joins the entry modules: 54 files (the plan records the tree's digest).
- The lab code digest is unchanged (`81b88be6`, 35 files).

### 17.2 Choices made inside the approved decisions (listed so they can be changed)

1. Staleness (DECISIVE 1), the breadth count (DECISIVE 4) and anchor bursts (DECISIVE 3) are counted when a dispatch is SELECTED, not when it
   is ingested: deterministic under D4, and the 10-dispatch reorder window cannot hand one cell ten draws in a row.
2. An anchor's w and bursts change only through anchor draws; a rank or breadth draw of an anchor cell leaves them.
3. Triggers: the kept cells are the burst's new or replaced cells, eligible, at ticks >= the event's step_from + 1. Rarity counts bursts. A
   triggered cell in a demoted group is still drawn (the demotion exclusion is the count-based draw's). **Open:** a non-finite burst is cut
   before the null, so its trigger tick is the burst's last tick and nothing is queued unless a cell was kept at exactly that tick (17.3).
4. A breadth dispatch with no eligible cell outside the demoted groups falls back to exploitation (counted in the records).
5. A new group's pooled rate: its level's windows at that moment; else every level's; else 0.
6. e counts a kept cell at any deeper level (as `d4b_niche_units.py`), not only the next.
7. Text replay (MINOR O7): at the close, when no other game process runs, with SSB64_RL_EXIT_ON_END=1 (the M1a exit; no stepping); only
   result.json is read (the pinned executable keeps one shared log). Clocks that differ from the verified ones are SEARCH_INVALID.
8. A .btti and a .bk2 are written when each clear is verified, not at the close. Frame 0 is the run's tick 0, not power-on.
9. Hourly records by wall time (3,600 s) for the night; by ingested dispatches in the tests (deterministic there).
10. The summary reads Q11's plateau signals for the night: a faster verified clear, and the groups whose earliest eligible arrival improved.

### 17.3 Tests

`python -B tools/frs/crossing_search_run3_tests.py` (zero native ticks):

- unit (9, in process): niche inheritance; the scripted A -> B move (membership, ranks, both groups' anchors, B's displaced third anchor,
  the staleness reset, the breadth count kept, both windows / counters / demotion unchanged, an emptied group leaving level 7 with phi
  0.125 -> 0.25 and returning with its window, the pooled warm start of a new niche, rule 1); demotion at the 1,000th fall, exit on the first
  break, phi / 4; e and anchor success, w halving to 1/8; the draws (anchor rotation, rank weights, the cleared factor, count-based breadth
  in cell-id order; breadth share 0.1994 over 100,000 keyed dispatches); triggers (step_from + 1, 3 draws per cell served in turn, rarity 3,
  the cap, break_occluded never, a replaced queued cell dropped); the bk2 round trip through `tools/bk2_to_btt_inputs.py` and
  `rl/btti_replay.py`; the export writer; parameters and the manifest.
- real (2, read only): niches of all 181,657 rows / 37,294 cells of runs 1 + 2 equal to the offline derivation (0 differences; 5,221 / 5,221
  single steps agree, 168 multi-target steps, 0 orphans; 39,309 / 39,309 run 2 dispatches attributed by start tick; 15,770 moves); the plan's
  start table equal to the approved 4b table (14 groups, 153 anchors, shares to 0.1 %, only (9, 64, 326:2-8-1) demoted, 22,464 eligible,
  best 1,245 from run 2, bound 1,220).
- e2e (fake game): fixture = a synthetic run 1 (run 1's engine, stub world, 200 dispatches, all 32 frontier keys as seeds) and a synthetic
  run 2 on it. With run 1's usual 12 seeds every synthetic cell is at level 9 and no group move can happen.
  - `e2e_same_seed_runs`: two run 3s, same seed, reorder window, step jitter: 160 dispatches each, **147 group moves** (guard >= 5);
    identical dispatch rows (with stream, group, niche, draw), cell rows (with niche, group, moved_from), end records, 5 records each.
  - `e2e_nonfinite_trigger`: nulls past every eligible prefix in a record field (3 triggers, rarity stops further ones), then nulls from tick
    1 in a field neither the record nor the key reads (`spatial.update_tic`, rarity 50): 34 non-finite bursts, 34 triggers, each at its
    burst's cut tick, 0 cells queued, 0 prefix mismatches.
  - `e2e_text_replay`: the fake game's text-replay mode on run 1's best words gives its verified clocks; a cut copy gives no clear.
- Real archive timing (zero ticks): selector built in 0.2 s; per dispatch 0.9 ms (rank), 4.2 ms (breadth over 21,410 cells), 0.07 ms (anchor);
  an ingest with a keep 3.5 ms; the full table 24 ms.
- Defects found and fixed while testing: a heredoc turned an escaped newline into a real one in the fake game (every fake process exited 1);
  the loader required verifications.jsonl (absent when a run replayed no claim); a too strict bound check (run 3's bound may equal run 2's
  when run 2 verified no faster clear); group labels split the markdown tables (now rendered as (level, mask, niche)).
- Result: `crossing_search_run3_tests.py` 14/14 from scratch (unit 9, real 2, e2e 3), then `e2e_nonfinite_trigger` alone with its final
  assertions. Inherited suites after the fake-game change: `run3_search_tests.py` 13/13 (field table 16/16 value, 14/14 type), `run3_archive_tests.py`
  2/2, `det_schedule_tests.py` unit 3/3 and e2e 2/2, `run3_anomaly_tests.py` unit 8/8 and e2e 2/2. `git diff --check` clean.

### 17.4 Before the smoke run

- Readiness on 2026-11-06 with no test running: **refused**, free commit 6,833 MB < 10,240 MB (available 7,508 MB). The open refuses before
  launching anything until about 3.4 GB of commit is freed; the thresholds are not lowered.
- Open for the owner: the non-finite trigger rule (17.2 item 3).
- Not exercised natively yet: the run 3 engine on the real executable, the text-replay path with SSB64_RL_EXIT_ON_END on the pinned
  executable, the bk2 export of a verified clear inside a run (the writer is unit-tested).
- Nothing of step 8 is committed.

### 17.5 2026-11-06, owner: rule (b) for non-finite triggers; the text-replay mismatch; go for the smoke run

- **Rule (b), approved and built:** a non-finite burst that triggers queues the burst's last kept eligible cell before the null, or, when the
  burst kept none, the dispatched cell (eligible). Detector classes keep the at-or-after rule. The trigger row records the rule used
  (`rule`). Tests: `unit_triggers` (both branches) and `e2e_nonfinite_trigger` on the fake game: every triggering non-finite burst queues
  exactly one cell (39 bursts, 39 triggers, 117 draws queued: 20 last kept cells, 19 dispatched cells), 3 trigger draws served within the
  10 % cap; the earlier run past the bound: 3 triggers (rarity), one cell each.
- After the fixes below: `crossing_search_run3_tests.py` unit 9/9, e2e 4/4 on the kept fixture (`e2e_same_seed_runs` 90 moves, identical;
  `e2e_nonfinite_trigger`; `e2e_text_replay`; `e2e_exports_under_guard`); the second non-finite run verified a faster clear (803 < 868):
  exported as .btt.txt + .bk2 under the guard, best_times.jsonl, its text replay at the close equal (803 / 802).
- **Defect found by that test (fixed):** a run of it verified a faster clear, and under the lab guard both the export and the text replay
  failed. G3 (`rl/frs_guard.py`, `m8_rd_worker.FORBIDDEN_FRAGMENTS`) refuses any path holding ".btti" (the human TAS replays' extension), so
  writing `clear_*.btti` was refused (the export recorded an error) and the text replay's `words.btti` raised into the close
  (SEARCH_INCOMPLETE). The run's own words in the .btti format are now written as `.btt.txt` (the native reader ignores the extension);
  every step of a text replay is inside its error handling, and the engine records a text replay that cannot run instead of raising.
  New test `e2e_exports_under_guard` (a guarded child: export and fake text replay, no refusal); `e2e_nonfinite_trigger` also checks that
  every verified clear of its runs was exported and every new best's text replay was equal, with no guard violation.
- **What "invalid" means today** for a text-replay clock mismatch (17.2 item 7): the status becomes SEARCH_INVALID (exit 3) and the close
  goes on (the other text replays, the integrity record, summary.json, report.md). Nothing is deleted: cells.jsonl (every NEW / REPLACED row
  and every end record), dispatches.jsonl, verifications.jsonl (the clear stays VERIFIED there), best_times.jsonl and the .btti / .bk2 files
  stay. The summary still names the faster clear as the run's best. A later run cannot inherit the archive (`run3_load` accepts only the
  clean statuses), but `P["end_record_files"]` would still import its end records (no status check). Nothing registers a clear
  automatically (Q8 is a separate decision).
- **Proposed, not built (owner's preference):** a mismatch sets a new status CLAIMS_FROZEN (its own exit code) and
  `summary["run3"]["claims_frozen"]` (dispatch, both clocks, reason). Every verified clear of the run is reported frozen: the summary's best
  stays the start's, best_times.jsonl and exports.jsonl get a `frozen` row, report.md and progress.md open with a banner. The close stops
  its remaining text replays (recorded as skipped) but still writes the integrity record and the summary. The archive is untouched and
  marked `to_investigate`: a later plan refuses it, and refuses its end records too, unless the owner's decision is recorded (an explicit
  plan flag naming that run folder, written into plan.json).
- **Go:** commit step 8 locally (no push), check readiness, then the smoke run as proposed (plan; run with 3 workers, 25 min, rng seed 1,
  records every 600 s); after it, the checks plus the group shares against the plan table, the native text replay of the 1,245 and the
  memory peak against the registered budget. The full night needs its own go.
- Step 8 committed 1a4a2b7 (local). Readiness then refused (free commit 9,577 MB < 10,240 MB): stopped, nothing planned.
- **2026-11-06, second attempt (owner closed Steam and the NVIDIA overlay; CLAIMS_FROZEN approved, to build after the smoke run and
  before the night, with the end-record import refusing a non-clean run unless a plan flag names it; the full 14/14 suite before the
  night):** readiness passed before launching (free commit 11,171 MB). The plan was written (zero ticks:
  `C:/BattleShip_lab/crossing_2026-11-06_run3_smoke/plan.json`, start table = 4b, run 3 code digest `400a9c9c`). The run then refused
  at its own open, before launching anything: `readiness: free commit 9905 MB < 10240 MB` (`refused_20261106T232856Z.json`, exit 2).
  The run's main process rebuilds the plan (both runs' archives) before the open's check, and held about 1.34 GB of commit by then
  (11,241 MB free again after it exited). Run 2's main process was at 584 MB at its open. So free commit must be about 11.6 GB before
  launching. Stopped as instructed; no game process ran.

### 17.6 The run's footprint at the open (owner, 2026-11-06: reduce it now, before the smoke run; the threshold untouched)

- **Measured** (private bytes of the main process, zero ticks, `run`'s path up to the open's readiness check): imports 22 MB; the
  reference loaded 196 (+174); `r2.read_run1` 489 (+294); `run3_load.load` (both runs' 181,657 cell rows and 70,008 dispatch rows,
  merge, niches, run 2 replay) 1,433 (+943); archive 1,512 (+80); selector 1,525. Dropping the intermediates gives back only 183 MB
  (CPython keeps freed memory): 1,342 MB at the open, the measured refusal. What the engine keeps is small (the reference record is
  words and clocks; `R1` is stored, never used).
- **Change:** `run` builds the plan in a short-lived child process (`plan_via_child`: the same `build_plan`, under the lab guard). The child
  writes a compact payload (the plan, the reference record, the best clear, one record per cell with exactly what
  `ResumeArchive.load_run1` reads, and its root lineage), which the main process reads, removes, and loads with `load_run1` itself.
  The engine still checks its start table against the plan's.
- **Before / after** at the open's readiness check: **1,352 MB -> 196 MB** (run 2: 584 MB). The plan step takes 35 s instead of 24 s.
- **Tests:** `real_plan_via_child_equal`: both routes on the lab's runs 1 + 2 give the same 29 attributes for all 37,294 cells, the same
  archive indexes and counters, plan, best, reference, and start table (14 groups, 153 anchors, only (9, 64, 326:2-8-1) demoted). The
  e2e engine runs now plan through the child as `run` does. The full suite from scratch: 16/16 (unit 9, real 3, e2e 4: 154 group moves,
  same-seed runs identical; 38 non-finite triggers, 114 draws queued, 3 served). `run3_search_tests.py` unit_run3_manifest then flagged the
  plan child's function-level import of `m8_rd_stub` (tests only): excluded by name in `run3_manifest.LAZY_EXCLUDED` with its function;
  after it `run3_search_tests.py` unit 8/8 and this suite's unit 9/9. Committed 1da9c2e.

### 17.7 The native smoke run (2026-11-06, 20:42-21:03 local; owner's go)

- **Command:** plan, then `run --workers 3 --max-wall-min 25 --rng-seed 1 --summary-every-s 600` into
  `C:/BattleShip_lab/crossing_2026-11-06_run3_smoke` (code digest `9a6660e0`, tree 1da9c2e). Readiness before: free commit 11,809 MB; at the
  open: 11,621 MB, main process 203 MB.
- **Open:** reference 1,885 / 1,884 replayed exactly (1.7 s); the best at the start 1,245 / 1,244 (run 2) replayed exactly; bound 1,220.
- **Stop:** WALL_CAP, exit 0; search 1,182 s, close 26 s. 1,398 dispatches (4,258 per hour, 3 workers), 1,586,138 ticks (prefix
  1,401,876, burst 178,740). Integrity clean: 0 prefix mismatches, 0 tick-0 inequalities, 0 lifecycle failures, 0 guard violations,
  no game process left, lab digest `81b88be6` and run 3 digest unchanged at the close.
- **End records:** 665 fused first dispatches, all reproduced (0 mismatches), 661 stored (3 repeats, 1 replaced in flight).
- **New verified best: 1,196 / 1,195** (gain 49 on 1,245; dispatch 928, rank draw in (9, 2, 326:2-6-8), from the level-9 cell 12331 at
  tick 1,114, rank 18 of 681; pace L8 1,013, L9 1,093). Replayed twice from tick 0 with the verify flags (chains equal), exported as
  `clears/clear_n928_t1196.btt.txt` and `.bk2` (round trip ok), `best_times.jsonl` written; its native text replay at the close gave
  1,196 / 1,195. Claims: 6, 1 replayed, 5 not (1,205, 1,244, 1,276, 1,278, 1,305: none faster than the best at the decision).
- **Selection:** streams rank 817, anchor 304, breadth 277 (19.8 %); 614 group moves; no demotion or exit; plateau signals: a faster clear,
  and (7, 322, 330:3) earliest 718 -> 687. Level split of exploitation 54.5 / 25.3 / 13.0 / 7.1 % (levels 9-6; design 53.3 / 26.7 /
  13.3 / 6.7). Group shares within levels against the plan's start shares, no obvious deviation (the shares move with the windows):
  level 9 56.5 / 41.4 / 2.1 % (plan 51.2 / 46.7 / 2.1); level 8 53.9 / 29.2 / 8.5 / 8.5 (52.1 / 33.0 / 8.2 / 6.7); level 7 55.5 / 9.6 /
  13.7 / 11.6 / 9.6 (66.9 / 9.8 / 7.8 / 7.8 / 7.8); level 6 53.7 / 46.3 (51.2 / 48.8).
- **Anomalies:** 1,310 events in 800 bursts, 0 non-finite, 0 scan errors. Two line_crossing triggers (dispatches 151 and 1024, the same
  level-9 cell, event tick 1,065): both bursts kept no cell, so nothing was queued (the detector rule queues kept cells only).
- **Records:** hourly.md / hourly.jsonl with the 10-minute record and the closing one; report.md and progress.md written; the run log has
  no error line.
- **Memory peak against the registered budget:** main process 425 MB (soft 2,560, cap 3,072); process tree private 2,619 MB (soft 8,192,
  cap 9,216); tree working set 957 MB (soft 3,584, cap 4,096); lowest system available 8,372 MB (minimum 1,536 soft, 1,024 cap); lowest
  free commit 9,097 MB (minimum 3,072 soft, 2,048 cap); no soft, hard or process breach. Peak 16 processes, 6 of them BattleShip.
- **Text replay of the 1,245** on the pinned executable after the close (owner's go): 1,245 / 1,244, equal to the verified clocks, exit 0,
  24 s (`text_replay_best_1245.json` in the run folder).

### 17.8 2026-11-06, owner: trigger fallback, the night's start (option c), the freeze deferred, the night prepared

- **Trigger fallback (approved, built):** a detector trigger whose burst kept no eligible cell at or after the event queues the burst's
  last kept eligible cell, otherwise the dispatched cell (the rule (b) fallback). The trigger row records `last_kept_cell` or
  `dispatched_cell`. Tests: `unit_trigger_fallback`; `e2e_detector_trigger_fallback` (fake game, trigger classes the stub world raises
  for that run only, rarity 50).
- **The night's start, option (c) (approved, built):** the archive stays runs 1 + 2; the best and the bound come from every verified clear,
  including the clean run 3 folders given with `--best-from` (their archives are NOT inherited). A source folder must have a clean stop and
  integrity record on the same reference, archive id and margin, and a best taken from it needs its equal native text replay; otherwise
  the plan refuses. With the smoke run: best 1,196 / 1,195 (`run3:crossing_2026-11-06_run3_smoke`), bound 1,171, fastest claim 1,196.
  The 1,196's start cell (12331, level 9, tick 1,114) stays eligible. Test: `real_best_from_smoke` (with both refusals).
- **CLAIMS_FROZEN deferred** to 2026-11-07, before any run inherits from tonight's. **Tonight's run must not be inherited** (archive, end
  records or `--best-from`) until the freeze, and the end-record import's refusal of a non-clean run, are built and tested.
- **The night's start table** (bound 1,171; useful = next-level arrival <= 1,171, at level 9 a claimed clear <= 1,171):

  | group (level, mask, niche) | eligible | anchors | share | rho | demoted |
  | --- | ---: | ---: | ---: | ---: | --- |
  | (9, 2, 326:2-6-8) | 117 | 12 | 96.9 % | 0.0054 | no |
  | (9, 64, 326:2-8-1) | 568 | 6 | 3.1 % | 0.0050 | yes |
  | (8, 66, 326:2-8) | 2,016 | 12 | 42.5 % | 0.0244 | no |
  | (8, 258, 326:2-6) | 775 | 12 | 38.3 % | 0.0220 | no |
  | (8, 258, 322:6) | 57 | 10 | 10.6 % | 0.0061 | no |
  | (8, 320, 326:2-1) | 5 | 3 | 8.6 % | 0.0050 | no |
  | (7, 322, 326:2) | 3,098 | 12 | 65.3 % | 0.0396 | no |
  | (7, 322, 322:) | 3,577 | 12 | 10.3 % | 0.0062 | no |
  | (7, 70, 326:8) | 341 | 12 | 8.2 % | 0.0050 | no |
  | (7, 266, 330:6) | 117 | 12 | 8.2 % | 0.0050 | no |
  | (7, 322, 330:3) | 173 | 9 | 8.2 % | 0.0050 | no |
  | (6, 330, 330:) | 4,432 | 12 | 51.2 % | 0.0305 | no |
  | (6, 326, 326:) | 4,235 | 12 | 48.8 % | 0.0291 | no |

  Eligible per level: 685 / 2,853 / 7,306 / 8,667 (levels 9-6), 19,511 in all; 13 groups, 136 anchors; only (9, 64, 326:2-8-1) demoted;
  phi = 1/8, 1/16, 1/20, 1/8 (levels 9-6). Against the 1,220 start: (9, 256, 326:2-6-1) has no eligible cell left (its earliest is
  1,178), so level 9 is (9, 2) with 117 cells and the demoted (9, 64) at phi / 4; (8, 258, 326:2-6)'s useful breaks fall from 52 to 21.
- **Tests:** `crossing_search_run3_tests.py` 19/19 from scratch (unit 10, real 4, e2e 5; the detector fallback: 57 triggers, 32 at or
  after the event, 11 last kept cells, 14 dispatched cells, 3 served; non-finite: 39 triggers, 117 draws queued); `run3_search_tests.py`
  unit 8/8. `git diff --check` clean.
- **The night (prepared, not launched):** 5 workers + standby, 480 min, 80 M ticks, rng seed 2, records every 3,600 s, `--best-from` the
  smoke run; the owner's go is required to launch.

## 18. The night: run 3 (2026-11-07 20:33 to 2026-11-08 04:31 local; owner's go)

- **Command:** `python -B tools/frs/crossing_search_run3.py run --lab-root C:/BattleShip_lab --run1 C:/BattleShip_lab/crossing_2026-10-15
  --run2 C:/BattleShip_lab/crossing_2026-10-15_run2 --out C:/BattleShip_lab/crossing_2026-11-06_run3 --workers 5 --max-ticks 80000000
  --max-wall-min 480 --rng-seed 2 --summary-every-s 3600 --best-from C:/BattleShip_lab/crossing_2026-11-06_run3_smoke` (tree 6ca6cb8,
  run 3 code digest `6399222b`). Readiness re-checked just before the launch; at the open free commit 11,498 MB, main process 204 MB.
  The main tree was not edited during the run (the CLAIMS_FROZEN work stayed in the `run3/claims-frozen` worktree, tests not run).
- **Open (18 s):** reference 1,885 / 1,884 replayed exactly; the start's best 1,196 / 1,195 (the smoke run) replayed exactly; E7 bound
  1,171; 37,294 inherited cells, eligible 685 / 2,853 / 7,306 / 8,667 (levels 9-6).
- **Stop:** WALL_CAP, exit 0; search 28,482 s, close 175 s. 41,737 dispatches (5,275 per hour), 46,285,631 ticks (prefix 41,280,755,
  burst 4,984,437); outcomes 19,186 falls, 22,461 out of words, 90 claimed clears. Integrity clean: 0 prefix mismatches, 0 tick-0
  inequalities, 0 lifecycle failures, 0 guard violations, no game process left, lab digest `81b88be6` and run 3 digest `6399222b`
  unchanged at the close.
- **End records:** 4,320 fused first dispatches, all reproduced (0 mismatches; 5 repeats, 1 stale), 4,314 stored; nothing imported.
- **Verified clears: 8; the best 978 / 977**, 218 under the start's 1,196 and 907 under the 1,885 reference. All eight are rank draws in
  (9, 2, 326:2-6-8). Each was replayed twice from tick 0 with the verify flags (chains equal), exported as `run/clears/*.btt.txt` and
  `.bk2` (round trips ok), and replayed natively from its text file at the close with equal clocks (`text_replays.jsonl`, 20-23 s each):

  | dispatch | clear | gain | start cell (tick) | rank | pace L8 / L9 | local time |
  | ---: | ---: | ---: | --- | ---: | --- | --- |
  | 1,035 | 1,186 | 10 | 9711 (1,125) | 49 | - | 20:46 |
  | 1,103 | 1,157 | 29 | 9279 (1,125) | 48 | - | 20:47 |
  | 1,849 | 1,141 | 16 | 9709 (1,118) | 40 | - | 20:55 |
  | 18,721 | 1,126 | 15 | 9709 (1,084) | 67 | - | 00:20 |
  | 22,868 | 1,088 | 38 | 8589 (1,030) | 0 | - | 01:05 |
  | 38,068 | 1,004 | 84 | 8739 (978) | 98 | 869 / 939 | 03:49 |
  | 39,217 | 999 | 5 | 9279 (961) | 32 | 869 / 925 | 04:01 |
  | 40,597 | 978 | 21 | 9709 (949) | 22 | 869 / 937 | 04:16 |

  Claims: 90; 8 replayed, 82 not (none faster than the best at the decision; the closest, 979 at dispatch 40,898, came after the 978).
- **Where the last three came from:** all three pass level 8 at 869, the arrival found at dispatch 35,865 (a level-7 rank draw in
  (7, 322, 326:2) from its cell at 809, breaking target 6). From there (8, 258, 326:2-6) broke target 8 at 925-951 (dispatches 36,001
  to 36,537), giving (9, 2) its level-9 cells, and target 1 followed within 26-38 words. (8, 258, 326:2-6)'s rate rose to 0.104 and its
  share of level 8 to 65 % by the close.
- **Earliest arrival per level, record by record** (levels 9 / 8 / 7 / 6; start 1,051 / 974 / 493 / 461):

  | record (local) | dispatches | best | earliest 9 / 8 / 7 / 6 | level-9 share | demotion |
  | --- | ---: | ---: | --- | ---: | --- |
  | 0 (21:33) | 5,094 | 1,141 | 1,051 / 974 / 493 / 461 | 41.7 % | |
  | 1 (22:33) | 9,834 | 1,141 | 1,051 / 974 / 493 / 461 | 43.1 % | |
  | 2 (23:33) | 14,905 | 1,141 | 1,051 / 960 / 493 / 461 | 42.4 % | |
  | 3 (00:33) | 19,953 | 1,126 | 1,030 / 960 / 493 / 461 | 43.0 % | (8, 320, 326:2-1) |
  | 4 (01:33) | 25,457 | 1,088 | 1,030 / 873 / 493 / 461 | 42.4 % | |
  | 5 (02:33) | 30,984 | 1,088 | 1,014 / 873 / 493 / 461 | 43.0 % | (9, 4, 326:8-6-1) |
  | 6 (03:33) | 36,588 | 1,088 | 925 / 869 / 493 / 461 | 41.6 % | |
  | close (04:31) | 41,737 | 978 | 925 / 869 / 493 / 461 | 42.0 % | (9, 64, 322:8-1) |

  The 2-hour flag (levels 9 and 7-8 all unchanged) was raised once, at record 1, and cleared at record 2. Levels 7 and 6 never moved.
- **Selection:** streams rank 29,710, breadth 8,257 (19.8 %), anchor 3,761, trigger 9; useful breaks rank 255, breadth 143, anchor 37;
  new earliest arrivals 29 / 8 / 7; 5,632 group moves. Level split of exploitation 52.6 / 27.0 / 13.5 / 6.9 % (design 53.3 / 26.7 / 13.3 /
  6.7). Demotions 3, no exit: (8, 320, 326:2-1) at 16,551 (911 of 1,000 falls); (9, 4, 326:8-6-1) at 29,179 (1,000 of 1,000);
  (9, 64, 322:8-1) at 37,939 (900 of 1,200). Triggers 3 (dispatches 147, 160, 226: line_crossing on cell 25599 at tick 1,053, rule
  `dispatched_cell`, 9 draws); the class then passed the rarity limit of 3 (21 sightings in all).
- **Group shares within levels against the plan's start shares:** level 9 (9, 2) 63.7 % (plan 96.9), (9, 64, 326:2-8-1) 2.0 (3.1),
  groups outside the plan 34.3 ((9, 256, 326:2-6-1) 21.8, (9, 64, 322:8-1) 6.5, (9, 4, 326:8-6-1) 6.0); level 8 (8, 66, 326:2-8) 20.3
  (42.5), (8, 258, 326:2-6) 38.6 (38.3), (8, 258, 322:6) 7.4 (10.6), (8, 320, 326:2-1) 3.8 (8.6), outside the plan 32.9; level 7
  (7, 322, 326:2) 30.6 (65.3), (7, 322, 322:) 11.0 (10.3), (7, 70, 326:8) 26.6 (8.2), (7, 266, 330:6) 9.4 (8.2), (7, 322, 330:3) 8.1 (8.2),
  outside the plan 14.2; level 6 38.1 / 61.9 (51.2 / 48.8). The deviations come from the design: shares follow the windows, and ten
  groups with no eligible cell at the start (bound 1,171) entered during the night.
- **Finding (to propose, not built): always-falling groups at the floor.** Whenever (9, 2)'s window of 200 held no useful break, every
  active level-9 group sat at the rho floor and the level was shared equally. (9, 256, 326:2-6-1) took 21.8 % of level 9 (3,846
  dispatches; in run 3 0 breaks and 88 % falls) and D2 could not demote it, because its whole history holds run 2's breaks. It also held
  level 9's earliest arrival from record 5 to record 6 (1,014, reached from (8, 258, 326:2-6)), so a rule on recent dispatches alone would
  have set that cell aside.
- **Anomalies:** 55,325 events in 26,505 bursts, 0 non-finite, 0 scan errors.
- **Memory peak against the registered budget:** main process 560 MB (soft 2,560, cap 3,072); process tree private 4,341 MB (soft
  8,192, cap 9,216); tree working set 1,645 MB (soft 3,584, cap 4,096); lowest system available 7,673 MB (minimum 1,536 soft, 1,024 cap);
  lowest free commit 6,979 MB (minimum 3,072 soft, 2,048 cap); no soft, hard or process breach. Peak 27 processes, 10 of them BattleShip.
  The main process grew 204 -> 560 MB over the night.
- **Records:** report.md, progress.md, hourly.md / hourly.jsonl (7 hourly records and the closing one), text_replays.jsonl,
  best_times.jsonl, exports.jsonl; the run log has no error line.
- **Inheritance:** as recorded in 17.8, this run is not to be inherited (archive, end records or `--best-from`) until CLAIMS_FROZEN and the
  end-record refusal of a non-clean run are built and tested.

### 18.1 CLAIMS_FROZEN and the end-record refusal (built 2026-11-07/08 in worktree `BattleShip_freeze`, branch `run3/claims-frozen`)

Built as proposed and approved (17.5, 17.8), on 6ca6cb8, in a separate worktree while the night ran (no test run there before the close).

- **Files:** `tools/frs/crossing_search_run3.py`, `tools/frs/run3_archive.py`, `tools/frs/run3_search.py`, the tests in
  `tools/frs/crossing_search_run3_tests.py` and one fixture in `tools/frs/run3_search_tests.py`. No inherited file edited.
- **The freeze:** a native text replay of a verified best with other clocks than its two stepping replays sets status `CLAIMS_FROZEN`
  (exit code 5, ranked with SEARCH_INVALID; registered in the inherited module's tables at import). Every verified clear of the run is
  frozen (frozen rows appended to `best_times.jsonl` and `exports.jsonl`), the remaining text replays are skipped, the summary's best is the
  start's (the unconfirmed one kept as `best_unconfirmed`), `faster_than_start` 0, the plateau reading does not count the clear,
  `archive_status` = `to_investigate`, and report.md / progress.md open with a CLAIMS FROZEN banner. The archive is left intact.
- **Inheritance refusals:** a later plan refuses a `--best-from` folder whose status is not clean (exit code 0 statuses only: COMPLETED,
  ARCHIVE_EMPTY, TICK_CAP, WALL_CAP, CELLS_CAP, DISPATCH_CAP, MEMORY_BUDGET), and the engine refuses end records (`P["end_record_files"]`)
  from a cells.jsonl whose run folder has no summary or a non-clean status, unless the plan's `--accept-run` names that folder (its output
  folder or its run folder); the plan records `accept_runs` and `accepted_non_clean` per source. There is still no CLI flag that sets
  end-record files: the refusal sits in the engine, so any future path is covered.
- **Choice made inside the decision (listed so it can be changed):** `run` refuses `--best-from` or `--accept-run` folders that differ
  from those its saved plan.json records (added, dropped or reordered), so a non-clean folder is admitted only by the plan, never by a flag
  given at `run` alone. Last night's plan and run had the same flags (checked on its plan.json).
- **Fixture change:** `e2e_stored_records` fed the importer a corrupted cells file loose in the lab root (no summary beside it), which the
  new refusal blocks; the file now sits in a run folder beside a copy of the source run's clean summary.json. The rule is unchanged.
- **Tests (worktree, 2026-11-08, after the night):** `crossing_search_run3_tests.py` 23/23 (unit 13: new `unit_claims_frozen`,
  `unit_non_clean_sources_refused`, `unit_plan_flags_match_saved_plan`; e2e 6: new `e2e_frozen_run_not_inherited`, a CLAIMS_FROZEN copy of
  a real fake-game run refused as a best source and as an end-record source, admitted with `--accept-run` (637 records); real 4/4);
  `run3_search_tests.py` 13/13; `run3_archive_tests.py` 2/2; `run3_anomaly_tests.py` 10/10. The worktree has no decomp checkout, so the
  four real-lab tests ran with a test-only `sitecustomize.py` on PYTHONPATH that points `m7g_fixture` at the main tree's stage source
  (decomp at the same pinned commit e4f06348, clean); every other suite ran without it (the shim breaks `unit_run3_manifest`'s
  copied-tree comparison). `git diff --check` clean. The run 3 code digest becomes `d4b27450` (54 files): the next run needs a new plan.
- **Committed 2026-11-08 (owner's go):** 332b537 on `run3/claims-frozen`, `run3/integration` fast-forwarded to it; this log 26cadf8. The four
  real-lab tests rerun in the main tree (decomp checked out, no shim): 4/4.

### 18.2 DECISIVE 2 revised: demotion on a rolling window (owner 2026-11-08)

- **Decision (approved in principle, built after the replay found 0 false demotions):** a group is demoted while its last 1,000
  dispatches (run 2 then run 3, ingest order) hold 0 bursts with any break, 0 e and >= 75 % falls; it exits when that stops holding (a
  break or an e enters, or the falls drop below 75 %). The thresholds are DECISIVE 2's. Second clause: a burst whose kept cells give a
  demoted group a new earliest eligible cell (earlier than every alive cell of the group before the burst) queues that cell, one per group
  per burst, for 3 draws through the trigger queue (class `demoted_new_earliest`, the same 10 % cap).
- **Replay before building** (`tools/analysis/run3_design/d2_rolling_replay.py`, zero ticks, 20 s). Every run 2 dispatch and every
  dispatch of the night was rebuilt with the selector's counters; the run 2 totals equal the night plan's history and the night's per-group
  totals equal the run's own (23 groups). The whole-history rule replayed beside it reproduces the night's three real demotions at the same
  dispatches (16,551, 29,179, 37,939).

  | data | rolling rule: demotions (dispatch) | exits | false demotions |
  | --- | --- | --- | ---: |
  | run 2 alone | (9, 64, 326:2-8-1) at 5,730; (9, 256, 326:2-6-1) at 21,451 | (9, 256) at 29,753 (a break, not useful) | 0 |
  | night (run 2 history + run 3) | (9, 256) at 16,277; (8, 320, 326:2-1) at 16,551; (9, 4, 326:8-6-1) at 29,179; (9, 64, 322:8-1) at 37,215; (9, 256) again at 41,720 | (9, 256) at 34,970 (falls 749 of 1,000) | 0 |

  On run 2 alone both rules give the same events. On the night the rolling rule adds (9, 256): demoted from dispatch 16,277 to 34,970 and
  from 41,720; its own dispatches in those spans had 0 breaks, 0 useful breaks, 0 e. The groups' own dispatches while demoted: 0 useful
  breaks and 0 e in every group (the one break, in run 2, is the exit). The second clause would have queued 2 cells of (9, 256) in the
  night (6 draws) and 2 of (9, 64, 326:2-8-1) in run 2.
- **Built:** `tools/frs/run3_select.py` (contract `run3_select_v2`; window of `demote_min_dispatches` codes per group, `window_code`,
  `window_counts`, the demotion events carry the window's counters; `_landing_trigger`; `on_ingest` returns `landing_triggers`; the
  history sequences must match the history counters or the selector refuses), `tools/frs/run3_load.py` (`run2_history` returns each group's
  per-dispatch sequence, `tails`), `tools/frs/crossing_search_run3.py` (the plan passes the sequences to the selector and the engine,
  records their sha256 in plan.json's history, the rule text; the engine writes landing triggers to triggers.jsonl). No new parameter.
- **Tests:** `unit_rolling_demotion` (a group whose older history holds 5 breaks and an e is demoted when the window reaches 750 falls,
  exits at 749, and after a break is demoted again exactly 1,000 dispatches later; a sequence that disagrees with its counters is refused),
  `unit_new_earliest_in_demoted_group` (one cell per group per burst, its earliest; not for a later cell nor a non-demoted group; 3 draws
  served within the cap). The fixture's histories now carry sequences.
- **Verified (main tree, no shim, 2026-11-08):** `crossing_search_run3_tests.py` 25/25 (unit 15, real 4: the start table unchanged, 14
  groups, 153 anchors, only (9, 64, 326:2-8-1) demoted; e2e 6); `run3_search_tests.py` 13/13; `run3_archive_tests.py` 2/2;
  `run3_anomaly_tests.py` 10/10. `git diff --check` clean. Run 3 code digest `b043d6bd` (54 files).

## 19. 2026-11-09: the right side is frozen by construction; the inheritance loader; the level weights

### 19.1 The owner's strategic question (answered)

- **A level is the number of targets broken** (`rl/m8_rd_cells.py` `level_of_mask`); level 10 = the clear. Runs 1-3 dispatch only from
  levels 6-9 (all 41,737 of the night's dispatches).
- **Why:** run 1's archive started from 48 seeds, `crossing_seed_v1` = the frontier search's states at level 7 (21) and level 6 (27)
  (`docs/frs_crossing_search_2026-10-15.md`, "The design as run"); runs 2 and 3 continue that archive. Not the bound, not the level weights.
  The right side was deferred, not excluded: the 2026-10-16 strategy review's stage 2, "the right-side arm" (`docs/frs_strategy_2026-10-16.md`
  §6 option 3). By construction (a burst only moves forward, no cell below level 6) level 6 can never beat 461 and level 7 only from the
  461 cell in under 32 ticks.
- **The 978, segment by segment** (traced cell by cell): targets 4, 0, 5, 7, 9, 3 at 29, 80, 167, 184, 305, 461 = the run 1 seed's own
  prefix (frontier search, sid 579); 2 at 530 (night 1,551); **6 at 869 (339 ticks, 35 %; night 1,667 -> 25,119 -> 35,865)**; 8 at 937; 1 at
  978. 480 ticks needs a different route, not only a faster start (the last four targets alone take 517).
- **Earliest arrival per level anywhere:** 1: 26 (the M8 import), 2: 78, 3: 120, 4: 184, 5: 280 (frontier search), 6: 461, 7: 493 (frontier
  search = run 1 seeds), 8: 869, 9: 925, clear 978 (the night). Levels 1-5 are not in the run 1-3 archive.

### 19.2 The inheritance loader (approved 2026-11-09 with rule a; built)

- **Owner's decision:** merge runs 1 + 2 + the night in chronological order with cells, end records and per-dispatch history; niche
  continuity; refuse a non-clean folder unless `--accept-run`; rule (a) for the D1 windows (the last 200 real dispatches, u recomputed at
  this plan's bound, padded with the group's whole-history rate); the smoke run stays out of the chain; a lab backup before the run.
- **Built:** `tools/frs/run3_load.py` (`read_run3`, `merge(run1, run2, *later)`, `inherited_history`, `load(..., inherit, accepted)`;
  run 2's history also returns the D1 window values), `tools/frs/run3_select.py` (`history_windows`: rule a when given, DECISIVE 1's
  warm start otherwise; the values must match the counters), `tools/frs/crossing_search_run3.py` (`--inherit`, repeatable, chronological;
  `inherit_chain_problems`: one linear chain, checked from the plans before any row is read and again with the cell rows; a folder in
  both `--best-from` and `--inherit` is refused; the inherited folders' clears join the best; `P["end_record_files"]` = their cells files;
  the plan records each folder's checks and `windows_rule`; `run` takes exactly the saved plan's `--inherit`).
- **Checks at the plan, on the real night:** every one of its 74,924 rows gets its recorded niche from the exact lineage; its 41,737
  dispatches replay over the archive it started from, each credited to the group of the representative dispatched, to its own per-group
  totals (23 groups); 4,314 end-record rows; best 978 (text replay equal) -> bound 953; 46,240 cells, 15,800 eligible. The start table
  equals the zero-tick prototype's in every field: (9, 2, 326:2-6-8) 39 eligible from 925; (8, 258, 326:2-6) 224 from 869; six level-7
  groups at 1/6 each (all at the rho floor at 953); level 6 55.6 / 44.4 %; 10 groups, 107 anchors, none demoted.
- **Tests (new):** `unit_real_windows`, `unit_inherit_chain` (sibling, wrong order, another run 2, twice; `run` flag), `real_inherit_night_table`
  (the table above, the night's checks), `e2e_inherit_a_to_b` (fake game: B's archive is A's final one, B's new ids continue, A's end
  records imported, B's history = run 2's + A's own totals, rule a; a CLAIMS_FROZEN copy refused unless `--accept-run`, an altered niche
  label refused, a sibling after A refused).
- **Verified (main tree, 2026-11-09):** `crossing_search_run3_tests.py` 29/29 (unit 17, real 5, e2e 7); `run3_search_tests.py` 13/13;
  `run3_archive_tests.py` 2/2; `run3_anomaly_tests.py` 10/10. `git diff --check` clean. Run 3 code digest `44ce752e` (54 files).

### 19.3 The level weights at 953 (proposed, waiting for the owner)

`tools/analysis/run3_design/d5_level_weights.py`, zero ticks. Yield per 1,000 dispatches of the night at the 953 definition (u + e), from
cells at or under 953: level 9 3.8 (261 dispatches, 1 e: the 978), level 8 47.1 (531, 24 level-9 arrivals <= 953), level 7 1.7 (5,154,
2 level-8 arrivals <= 953 + 7 e), level 6 29.1 (5,571, mostly level-7 arrivals <= 953, which are plentiful). Six of the eight bests came
on their start cell's first dispatch, the others on the second or third, 4 to 231 level-9 dispatches after the cell appeared (the 999:
1,372). Earliest level 9 moved only in hours 4, 6 and 7, each time after level 8 moved. DECISIVE 4's model on the real 953 start (33,390
exploitation draws, static archive): current split L9 17,808 draws (39 cells: mean 457, min 104, the earliest 4,009), flat 8,348 (mean
214, min 50), 7-8 first (0.20 / 0.35 / 0.35 / 0.10) 6,678 (mean 171, min 38); expected u + e at level 7: 7.8 / 14.6 / 20.4, at level 8:
419 / 393 / 550.

### 19.4 2026-11-09, owner: "7-8 first" approved; hourly per-level record; backup; GO for the backup and the smoke run

- **Level split approved:** 0.20 / 0.35 / 0.35 / 0.10 for the deepest eligible level and the three below it (9 / 8 / 7 / 6 at 953).
  **Built:** `Params3.level_weights` (`--level-weights 0.20,0.35,0.35,0.10`; default `()` = `level_decay` 0.5, numerically unchanged;
  levels past the list get 0; the deepest level's weight must be positive), recorded in the plan's parameters;
  `Run3Selector.level_weights`. Test: `unit_level_weights` (counting from the deepest level, the draw frequency, the refusals, the
  parameter record, the hourly per-level record).
- **Hourly record per level (owner):** weight, eligible cells, dispatched, ingested, u, e, (u + e) per 1,000 ingested at this run's bound,
  earliest arrival (`levels` in each hourly record and a "Levels" table in hourly.md). The owner's flag: level 8's earliest arrival not
  below its start value (869) after 4 hours (in the session's hourly summary script).
- **Lab backup:** `D:/BattleShip_lab_backup/2026-11-09` (lab/, SHA256SUMS.txt from the sources with Python hashlib, README.txt): 2,489
  files, 1,800,244,362 bytes; Python re-hash of the copies 2,489 / 2,489 equal, sources unchanged after the copy; PowerShell
  Get-FileHash 2,489 equal, 0 differ, 0 missing. The empty folder port_leases holds no file.
- **Verified (main tree, 2026-11-09):** `crossing_search_run3_tests.py` 30/30 (unit 18, real 5, e2e 7); `run3_search_tests.py` 13/13;
  `run3_archive_tests.py` 2/2; `run3_anomaly_tests.py` 10/10. `git diff --check` clean. Run 3 code digest `d0cdde51` (54 files).

### 19.5 The smoke run inheriting the night (2026-11-10, 08:41-09:01 local; owner's go)

- **Command:** plan, then `run --workers 3 --max-wall-min 25 --rng-seed 1 --summary-every-s 600 --level-weights 0.20,0.35,0.35,0.10
  --inherit C:/BattleShip_lab/crossing_2026-11-06_run3` into `C:/BattleShip_lab/crossing_2026-11-09_run3b_smoke` (tree cb98184, run 3
  code digest `d0cdde51`). Readiness first refused (free commit 9,758 < 10,240 MB); after the owner closed Chrome and the NVIDIA overlay:
  free commit 11,535 MB, available 9,375 MB.
- **Open (19 s):** reference 1,885 / 1,884 and the night's 978 / 977 replayed exactly; bound 953; 46,240 cells, eligible 39 / 224 /
  6,169 / 9,368 (levels 9-6), 1,907 cells without an end record (32,529 end records attached from the night's cells file).
- **Stop:** WALL_CAP, exit 0; 1,358 dispatches (4,142 per hour), 1,251,479 ticks. Integrity clean (0 prefix mismatches, 0 tick-0
  inequalities, 0 lifecycle failures, 0 guard violations, no game process left; lab digest `81b88be6` and run 3 digest `d0cdde51`
  unchanged); 43 fused first dispatches, all reproduced. No faster clear: one claim (1,002, not replayed), no verified clear, so no text
  replay. One trigger (line_crossing, 3 draws). Anomalies 782 events, 0 non-finite.
- **Levels (exploitation split observed against 0.20 / 0.35 / 0.35 / 0.10):** level 9 0.209 (228 dispatches over 40 cells, at most 18
  on one; u + e 0; earliest 925); level 8 0.352 (385; 33 level-9 arrivals at or under 953 = 85.7 per 1,000, all at 925-926, so no new
  earliest; earliest 869); level 7 0.330 (457 with breadth; no level-8 arrival; earliest 493); level 6 0.108 (288; 27.8 per 1,000;
  earliest 461). Breadth 19.7 %.
- **Memory peak:** main 467 MB, process tree 2,638 MB private / 1,122 MB working set, lowest free commit 8,728 MB, lowest available
  8,572 MB; no breach (soft budget 2,560 / 8,192 / 3,584, minimums 3,072 / 1,536).
- The smoke folder is a sibling of the night planned next: it is not inherited.

### 19.6 Night 2 of run 3: `crossing_2026-11-10_run3b` (2026-11-10 22:46 to 2026-11-11 06:43 local; owner's go)

- **Before launch:** section 19.5 committed locally (`7de827f`). Readiness at the plan: free commit 11,172 MB, available 9,104 MB; re-checked
  in the launch command just before the run: free commit 11,154 MB, available 9,038 MB, no game process, no lab lock.
- **Command:** `python -B tools/frs/crossing_search_run3.py plan` then `run --lab-root C:/BattleShip_lab --run1 C:/BattleShip_lab/crossing_2026-10-15
  --run2 C:/BattleShip_lab/crossing_2026-10-15_run2 --out C:/BattleShip_lab/crossing_2026-11-10_run3b --workers 5 --max-ticks 80000000
  --max-wall-min 480 --rng-seed 3 --summary-every-s 3600 --level-weights 0.20,0.35,0.35,0.10 --inherit C:/BattleShip_lab/crossing_2026-11-06_run3`
  (tree `7de827f`, run 3 code digest `d0cdde51`). Plan: the smoke's start table exactly (bound 953; eligible 39 / 224 / 6,169 / 9,368; 10 groups,
  107 anchors, none demoted). No manifest-covered file was edited during the night.
- **Open (20 s):** 1,885 / 1,884 and the start's 978 / 977 replayed exactly; 46,240 inherited cells.
- **Stop:** WALL_CAP, exit 0; search 28,479 s, close 43 s. 43,549 dispatches (5,505 per hour), 40,766,318 ticks (prefix 35,195,315, burst
  5,564,278); 14,254 falls, 35 claimed clears. Integrity clean: 0 prefix mismatches, 0 tick-0 inequalities, 0 lifecycle failures, 0 seed
  failures, 0 guard violations, no game process left (checked again after the close), lab lock released, lab digest `81b88be6` and run 3
  digest `d0cdde51` unchanged at the close (and in the tree afterwards). End records: 766 fused first dispatches, all reproduced.
- **Verified clears: 2; best 959 / 958** (19 under the start's 978, 926 under the reference). Both replayed twice from tick 0 with equal
  chains, exported (`run/clears/*.btt.txt` + `.bk2`, round trips ok) and replayed natively from the text file at the close with equal clocks:

  | dispatch | clear | gain | start cell (tick) | stream, rank | local time |
  | ---: | ---: | ---: | --- | --- | --- |
  | 9,506 | 972 / 971 | 6 | 10387 (894) | rank 6 in (9, 2, 326:2-6-8) | 00:30 |
  | 23,283 | 959 / 958 | 13 | 12331 (916) | rank 79 in (9, 2, 326:2-6-8) | 03:02 |

  The 959 breaks 4, 0, 5, 7, 9, 3, 2 exactly as the 978 (to 530), then 6 at 826, 8 at 900, 1 at 959: the crossing is 43 ticks faster
  (296 against 339), the left side 24 slower (133 against 109). Claims: 35; 2 replayed, 33 not (none faster than the best at the time).
- **Earliest arrivals:** level 8 869 -> 826 (dispatch 2,179, a breadth draw, rank 1,756 of 15,910, from cell 7088 at 706 on the 978's own
  lineage: seed 461 -> 2 at 530 -> take-off cell 571 -> 706) -> 813 (40,489, rank draw from cell 20201 at 778) -> **803** (41,720, 06:23, a
  breadth draw from cell 26702 at 796); level 9 925 -> 888 (hour 1) -> **869** (42,513, 06:31). Levels 7 and 6 unchanged (493 / 461). The 813
  and 803 started a cascade of level-9 arrivals at 869 to 887 in the last 40 minutes; none had time to be carried to a clear.
- **Levels, start -> end** (exploitation split observed 0.200 / 0.349 / 0.351 / 0.100; breadth 20.1 %):

  | level | eligible | earliest | dispatches | u | e | (u + e) per 1,000 | falls |
  | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
  | 9 | 39 -> 382 | 925 -> 869 | 6,977 | 0 | 2 | 0.3 | 3,120 |
  | 8 | 224 -> 1,002 | 869 -> 803 | 12,210 | 1,281 | 10 | 105.7 | 4,535 |
  | 7 | 6,169 -> 7,553 | 493 -> 493 | 15,109 | 30 | 9 | 2.6 | 3,250 |
  | 6 | 9,368 -> 10,302 | 461 -> 461 | 9,253 | 180 | 2 | 19.7 | 3,349 |

- **Hourly flag (owner):** level 8 below 869 from hour 1 (826), so the "still at 869 after 4 hours" flag never applied.
- **Demotions and exits: 11 events, all (9, 256, 326:2-6-1), flapping at the threshold.** The group was already demoted at the start; it
  exited at 22,391, 22,914, 25,515, 25,717, 37,110 and 39,329 and was demoted again 23 to 78 dispatches later (five times). Every exit was
  the rolling window reaching 749 falls of 1,000 (b 0, e 0), every re-demotion 750. The rolling rule has no hysteresis. The group had 1
  to 11 eligible cells; it took 178 run-3 dispatches up to its last exit and 535 by the close (54.0 % falls, 0 breaks), ending the night
  not demoted with a full share of level 9's groups. To propose: exit only on b or e, or a lower exit threshold (for example 70 %).
- **Triggers:** 4 (1 demoted_new_earliest: cell 21451 at 943, 3 draws; 3 line_crossing at 35,048-35,065 from cells 31607 at 627 and 27422
  at 714, 9 draws); 12 trigger draws, 0 useful, 0 dropped. Anomalies 34,790 events, 0 non-finite.
- **Memory peak (engine):** main 522 MB, process tree 4,345 MB private / 1,854 MB working set, 10 game processes; lowest free commit
  6,106 MB, lowest available 6,629 MB; no soft, hard or process breach.
- **Zero-tick census with this night added** (right-side arm proposal, `docs/frs_right_side_arm_proposal_2026-11-10.md`, step 1 of its
  recommendation): this night broke target 6 72 times; the four breaks from level-7 mask-322 lineages all come from the 978's 530 end (now
  870 dispatches, 6 crossings), the shortest 273 ticks (530 -> 803). Level-7 ends earlier than 530: 92 ends, 11,480 dispatches over all
  runs, still 0 crossings; the resourceful ones: 21 ends, 2,701 dispatches, the two most tested (521 A1 at the 978's own cell, 1,009; 521
  A1, 907) 0 crossings each, 19 still under 300.
- This night's archive is clean (WALL_CAP, 0 mismatches) and can be inherited after runs 1 + 2 + night 1 (bound 959 - 24 - 1 = 934 at the
  registered rule); not planned, waiting for the owner.
