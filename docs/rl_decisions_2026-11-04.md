# Decisions (2026-11-04)

**Decided by:** Nicolas. D1 on 2026-11-04; the savestate closure on 2026-11-03; BizHawk, a standing project rule.

**Sources:**

- `GLITCH_CANDIDATES.md` (cloud, 2026-11-04): M13 and §5 step 6.
- `REVIEW_2026-11-03.md` (cloud): finding D1, decisions O2 and O3.
- `SESSION_LOG_2026-11-04.md` §2.4: the measurements on this PC.
- `docs/rl_decision_soft_reset_2026-11-02.md`.

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
