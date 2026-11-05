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
