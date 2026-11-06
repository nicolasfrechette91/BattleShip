# Decisions (2026-11-04)

**Decided by:** Nicolas. D1 on 2026-11-04; the savestate closure on 2026-11-03; BizHawk, a standing project rule; the rebuild deferral on
2026-11-05; run 3's breadth and budget unit (DECISIVE 4 and 4b) on 2026-11-06.

**Sources:**

- `GLITCH_CANDIDATES.md` (cloud, 2026-11-04): M13 and §5 step 6.
- `REVIEW_2026-11-03.md` (cloud): finding D1, decisions O2 and O3.
- `SESSION_LOG_2026-11-04.md` §2.4: the measurements on this PC.
- `docs/rl_decision_soft_reset_2026-11-02.md`.
- `SESSION_LOG_2026-11-04.md` §16 (run 3 decisions) and `tools/analysis/run3_design/` (the zero-tick scripts behind them).

Nothing here changes a tick, a claim rule or the RNG rule.

## 1. D1, host trig on MSVC: keep the pinned executable's physics

**Decision.**

- Run 3 keeps the physics of the pinned executable `BattleShip.exe` `30a3913b…`. On MSVC, the bare `sinf`/`cosf` call sites stay
  on ucrt.
- No archive regeneration and no libultra A/B replay.
- `SSB64_MSVC_LIBULTRA_TRIG` (commit 24bcb27) stays at its default, OFF, in the next native build.
- That build bundles only additive, PORT-only changes. Its M6 equivalence run must show that it changes no tick against `30a3913b`.

**Evidence** (measured 2026-11-04 on this PC, zero game ticks):

- `tools/glitch/transn_cos_check.c`, built with MSVC 1951 (VS 18, x64, `/O2 /fp:precise`) against libultra's `cosf.c`:
  `differ: 10 of 61 inputs; on the 8-direction inputs (|stick_x| = 80): 0 of 2`.
  - Stick 0 and ±80 give identical bits from ucrt and libultra (`0x3f800000`; `0x3f737871` for ±80).
- The CRT's FMA3 path changes nothing on those inputs. `_set_FMA3_enable(1)` and `(0)` give the same bits; this CPU has FMA3.
  This was measured on this CPU only.
- **Exposure** in the stored traces: the ticks on the `ftphysics.c:430` path are Mario status 225 airborne, or 226 with motion
  flag1 set.

  | route | ticks on the `ftphysics.c:430` path |
  | --- | --- |
  | 1,245 | 136 |
  | 1,885 | 220 |

  The agent's `stick_x` on those ticks is −80, 0 or +80 only.

**Correction to `REVIEW_2026-11-03.md` D1.** It names the wrong Mario path. Both points were read in the decomp:

- **The fireball is not on the D1 path.**
  - Mario's fireball has all-zero `attack_offsets` (`src/relocData/204_MarioSpecial1.c`).
  - So `wpProcessUpdateHitPositions` only adds the translation and never calls `wpProcessUpdateHitOffsets`, the bare-trig
    rotation (`src/wp/wpprocess.c`).
  - Its launch uses `__cosf`/`__sinf`. Its only bare-trig call (`syVectorRotateAbout3D`) runs on shields and reflectors, which BTT
    does not have (GLITCH_CANDIDATES M13).
- **Mario's airborne Super Jump Punch is on the D1 path.** The review lists `ftphysics.c:430` as "not Mario".
  - `ftMarioSpecialHiProcPhysics` (`ftmariospecialhi.c:75`, `:81`) calls `ftPhysicsApplyAirVelTransNAll`. That reaches the bare
    `cosf` of the TransN z rotation in `ftPhysicsGetAirVelTransN`.
  - `ftMarioSpecialHiProcInterrupt` derives that rotation from the stick: `-DTOR((stick_x ∓ 50) × 0.6)` for |stick_x| > 50.
  - The function's other callers are other characters and the ledge climb. BTT has no ledges.

**Residual, unverified.** Does the Super Jump Punch animation key its own TransN `rotate.z`?

- If it does, rotations other than 0 and ±0.3141593 reach ucrt, and the check above does not cover them.
- This affects only parity with the N64 or a Linux build. On one executable, Windows results stay deterministic.
- It is not investigated now. Switching to libultra trig (below) removes the question.

**Required before the action set opens to analog stick values.**

- **Switch to libultra trig first**: `-DSSB64_MSVC_LIBULTRA_TRIG=ON` (24bcb27) or an equivalent.
- Reason: 10 of the 58 analog rotations (|stick_x| 54, 63, 72, 76 and 77, both signs) give a different `cosf` on ucrt and on
  libultra, by 1 ulp. On those, libultra is the one that is not correctly rounded, and the N64 uses libultra.
- That switch is a new executable. It needs a new pin and archive. Every inherited archive is re-checked by prefix replay on it,
  and every claim is re-verified from tick 0 on it.

## 2. Mid-episode native savestates: closed (decided 2026-11-03)

- Mid-episode native savestates are **not pursued**. That covers feasibility option (B) and any equivalent, for example
  `fork()`-based snapshots (REVIEW_2026-11-03 §8, "excluded").
- Recorded as REVIEW_2026-11-03 O2 recommends, so that no later session re-opens them.
- The in-process soft reset (C) is not a snapshot and is unaffected. It stays as decided on 2026-11-02: search only, gated by its
  pilot.
- `docs/rl_decision_soft_reset_2026-11-02.md` is updated to match (status line, §8 option 3, §9).

## 3. BizHawk is not used

- BizHawk is not part of this project. It is not run, installed or required by any tool, step, validation or decision, and no
  session proposes it.
- The `.bk2` input-movie format is only a file format and stays allowed:
  - the inherited `tools/bk2_to_btt_inputs.py` stays;
  - a claimed clear's words may be exported as a `.bk2` file, as the owner asked for run 3.

  Writing that file runs no BizHawk.
- Superseded on this point:
  - the soft-reset record's §2 sentence on a BizHawk replay;
  - REVIEW_2026-11-03's D1 scenario and summary, which mention BizHawk validation.
- Claims stay verified as before: exact replay from tick 0 in fresh processes on the pinned executable, twice with the verify
  flags for lab claims.
- This record does not decide what, if anything, validates a result on the original game.

## 4. The single rebuild (step 6): deferred (decided 2026-11-05)

**Decision.** Run 3 runs on the pinned executable `BattleShip.exe` `30a3913b…` as it is.

- The port race (review D3) is blocked by the port leases (`rl/port_lease.py`, INFRA_2026-11-04 fix 1, first layer). The pinned
  executable has no launch-nonce echo, so every launch reports identity `unverified`.
- `BATTLESHIP_REQUIRE_IDENTITY` is not set for run 3 (with this executable it would refuse every launch).
- The per-process log (`SSB64_LOG_PATH`, fix 2) is ignored by this executable: it keeps the shared log, and `native_log_flags` stays empty.
- Not built: the stored-chain probe and the launcher-identity script proposed with the plan.

**The plan, as prepared, for the day of the rebuild.**

1. Zero ticks, before anything: `sha256sum -c` in `D:/BattleShip_exe_archive/2026-10-13_30a3913b` (6/6 OK on 2026-11-05);
   `build-us/Release`, that archive and the lab import must all hold `30a3913b`; no native file may differ from HEAD
   (`git status -- port decomp libultraship torch CMakeLists.txt cmake yamls`), submodules clean. Native changes since the build of
   `30a3913b` (48ea181): `CMakeLists.txt` (the trig option, a no-op when OFF), `port/port.cpp`, `port/port_log.c`, `port/port_log.h`,
   `port/rl/rl.h`, `port/rl/rl_boot.cpp`, `port/rl/rl_transport.cpp`; submodule pointers unchanged.
2. Build, one incremental US Release, trig explicitly OFF:
   `cmake -S . -B build-us -G "Visual Studio 18 2026" -A x64 -DSSB64_VERSION=us -DSSB64_MSVC_LIBULTRA_TRIG=OFF`, then
   `cmake --build build-us --config Release`. Record the source commit and the new executable's sha256.
3. Candidate folder: copy `C:/BattleShip_lab/import/exe` to `C:/BattleShip_lab/probes/rebuild_<date>/exe` and replace only
   `BattleShip.exe`; the two folders must differ in that one file (hash every file). Then restore `build-us/Release`'s runtime
   files from the D: archive (see the hazard below).
4. Native: `rl/m6_equivalence_regression.py --exe <candidate>` (three modes), with `BATTLESHIP_REQUIRE_IDENTITY=1`.
5. Native: `rl/m6_raphnet_bypass_regression.py --exe <candidate>` (opts out of the per-process log by design).
6. Native: tick-by-tick A/B against `30a3913b` with `tools/audit/trig_ab_replay.py` (A = the lab import, B = the candidate; the
   1,245 and 1,885 routes and the 468-row baseline; A once, B twice).
7. Native: one launcher episode with identity required: identity `verified`, `SSB64 RL Transport: launch nonce set` in its
   per-episode `ssb64.log`, no flagged line, the shared `%APPDATA%` log unchanged.
8. Only after the owner's go on the results: archive the new executable on D: (SHA256SUMS, source commit, build flags). Pinning it
   in the lab import and setting `BATTLESHIP_REQUIRE_IDENTITY=1` for lab runs are separate decisions.

**Hazard: the build overwrites a registered runtime file.**

- Every build's POST_BUILD step (`CMakeLists.txt`, after `add_dependencies(${PROJECT_NAME} GenerateF3DO2R)`) runs
  `copy_if_different <checkout root>/f3d.o2r <build-us/Release>/f3d.o2r`, and `GenerateF3DO2R` repackages the root `f3d.o2r`
  from `shaders/` (a zip, rewritten by the build).
- On 2026-11-05 the root `f3d.o2r` is `bf16e8dd…` and the registered one in `build-us/Release` (and in the D: archive and the lab
  import's `frozen_runtime.json`) is `73ab91ef…`. A build in `build-us` replaces the registered file with `bf16e8dd…`.
- The same step stages `BattleShip.o2r` from `build-us/extracted/` with `copy_if_different`; today that file equals the registered
  one (`fe2b307e…`), so it is unchanged unless the extraction reruns. The checkout-root `BattleShip.o2r` (`3b189ff3…`) is not used.
- So never take runtime files from `build-us/Release` after a build: pair the new executable with the registered runtime files
  (the lab import copy), and restore `build-us/Release` from the D: archive afterwards. The lab import itself is not touched by a
  build.

## 5. Run 3: breadth (DECISIVE 4) and the budget unit (DECISIVE 4b) (decided 2026-11-06)

The MINOR table and DECISIVE 1-3 (group shares, demotion, anchors) are recorded in `SESSION_LOG_2026-11-04.md` §16.1-16.4. This
section records the two decisions that complete them; §16.6-16.7 there carry the full numbers.

**DECISIVE 4, breadth.**

- 20 % of dispatches are breadth draws; the other 80 % follow DECISIVE 1-3.
- Count-based draw: weight 1 / (1 + dispatches of the cell id in runs 1-3, run 3's own included as they happen), over eligible cells
  only (levels 6-9, tick <= 1,220); demoted groups excluded.
- Anomaly trigger instead of a share: a burst with an event of a class seen fewer than 3 times in the run (line_crossing,
  inside_solid, floor_switch_unlinked, D6 non-finite) gives each of its kept cells at or after the event up to 3 breadth draws, capped
  at 10 % of the breadth budget. break_occluded and the ordinary classes are recorded only.
- No separate order-niche stream.
- Hourly records: breadth draws by level, group and niche; the never-dispatched pool; useful breaks from breadth against
  exploitation; triggers. Every parameter in `config.json`.
- Basis (`d4_breadth.py`, zero ticks): run 2's crossing came from a cell (L7 @ 978, A2, mask 322) that waited 22,075 dispatches; at
  20 % a count-based draw reaches such a cell in about 43,000 dispatches, a uniform draw in about 95,000. One simulated night:
  expected useful breaks u6 / u7 / u8 / clears 135.6 / 95.3 / 586.4 / 79.6 against 47.7 / 45.3 / 690.3 / 98.3 without breadth.

**DECISIVE 4b, budget unit (level, mask, order niche).**

- DECISIVE 1-3 are computed per (level, mask, order niche). The DECISIVE 1 rate counts useful breaks only: next-level arrival
  <= 1,220; at level 9 a claimed clear <= 1,220 (literal).
- Order niche = (the mask of the lineage's run 1 seed, the targets broken after it in break order). A child inherits its parent
  representative's niche plus the targets its burst broke at or before the child's tick (break tick, then target id). Seeds with the
  same mask share a niche. Run 3 writes `niche` on new and replaced rows; inherited rows are derived at open.
- A replacement into another niche moves the cell: history and demotion stay with the group dispatched; staleness resets; the breadth
  count stays with the cell id; ranks and anchors are recomputed in both groups (new anchors at weight 1, 0 bursts); a group with no
  eligible cell leaves its level's draw and returns with its history.
- Four rules: a same-niche replacement of an anchor resets it to weight 1 / 0 bursts; a new niche group starts its window as 200
  pseudo-dispatches at its level's pooled rate; DECISIVE 2 stays on all breaks; level 9 literal.
- Basis (`d4b_niche_units.py`, exact attribution of every run 2 dispatch): (7, 322) splits into a niche with 55 useful breaks in
  1,628 dispatches and one with 4 in 3,084; 22 % of run 2's replacements are group moves. Start: 14 groups, 153 anchors, only
  (9, 64, 326:2-8-1) demoted; the largest shares (9, 2, 326:2-6-8) 51 %, (8, 258, 326:2-6) 52 %, (7, 322, 326:2) 67 %.
- Tests before any launch: niche inheritance (units and equality with the offline derivation over all runs 1 + 2 cells), moves
  (unit), and two same-seed fake-game runs with at least 5 group moves staying identical under D4.
