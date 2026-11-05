# Decision: in-process soft reset (C) for search

**Status:** (C) DECIDED, allowed for search only, gated by the pilot. (B) mid-episode snapshots: NOT PURSUED (decided
2026-11-03, recorded in `docs/rl_decisions_2026-11-04.md` §2; see section 9).

**Decided by:** Nicolas, 2026-11-02.

**Sources:**
- `docs/frs_savestate_feasibility_2026-10-16.md` (the feasibility record): options (A), (B), (C) and (D) in section 2, the pilot P0 to P2 in section 7, and the ten recommendations of section 9 (Q1 to Q10), accepted in principle.
- `docs/rl_decisions_2026-10-16.md` and `docs/rl_decisions_2026-10-16_addendum.md` (part 3 asks the question this record answers for (C)).

Naming: "(C)", "(B)", "P0", "P1" and "P2" mean the feasibility record's mechanisms and pilot steps. The numbered options in section 8 below are this record's decision options, not those mechanisms.

## 1. Decision

(C), the in-process soft reset, may be used to start SEARCH episodes, once the pilot below has passed. It does not apply to any claim, verification, registration or validation.

## 2. Claims unchanged

Every claimed clear is still verified by exact replay from tick 0 in fresh processes. Lab claims: twice, with the verify flags. Any original-game result also needs a BizHawk replay of the agent's canonical words. A soft-reset episode is never evidence on its own.

Superseded 2026-11-04: BizHawk is not used in this project (`docs/rl_decisions_2026-11-04.md` §3). The BizHawk sentence above no longer applies. The other sentences stand.

## 3. Implementation constraints

- Native change is PORT-only and behind a default-off flag. Non-PORT decomp source is unchanged.
- The reset path is the game's own existing code, changed only to make the handoff repeatable under that flag. Nothing new reads or writes game state, with one exception: at each reset, the save-data image is re-applied from the copy taken at this process's boot (feasibility §2, option C), so a clear's record update cannot leak into the next episode's end-of-episode branch. This restores bytes the game itself produced at boot in the same process. The copy is handled as one opaque block: never parsed, edited, inspected, selected or compared. Nothing else is restored or written. Port-side bookkeeping outside game memory is not game state. The conditional fix of clearing the animation-stream conversion marks for the arena range (feasibility §2, option C) is one such change. It is added only if P1's evidence calls for it and Nicolas decides so at P1 review, and it is then re-tested under P1.
- Expected fidelity risks: the port bridge's bookkeeping (simulation state), the animation-stream conversion marks that are never cleared, an incomplete save-data re-apply (part of a clear's record update surviving into the next episode), and order effects between episodes in one process. Randomness is not on this list (see section 5).

## 4. Pilot gates

Each step needs Nicolas's explicit go: plan first, then stop for approval, then run. The pilot's definition is feasibility §7; the changes and additions are below.

- **P0, flag-off identity replay.** P0 is feasibility §7's P0, including the M6 equivalence regression, with one change: the registered 1,885-tick clear is replayed from a read-only copy of its words in the lab, never in place, and the 1,245-tick lab clear is replayed as well. If any part of §7's P0 would touch registered files or increments in place, the P0 plan flags it for Nicolas before anything runs. Failure = BUILD_INVALID: stop and fix the build; (C) is not used.
- **P1, fidelity.** P1 is feasibility §7's twelve cases, plus:
  - (a) one process running the full intended episode cap against fresh-process replays, with earlier episodes varying their moves (order effects);
  - (b) at least one case in which a clear occurs in an earlier episode of the same process, testing the save-data re-apply, if this is not already among the twelve.

  Zero mismatches across all of them = FIDELITY_PASS. Any mismatch means (C) is not allowed and process restart stays. §7's 60-minute native hard cap stands. The P1 plan sizes (a) to fit within it, and the cap tested there is the maximum cap search may use. Extending the timebox needs Nicolas's go at plan review.
- **P2, throughput ratio against process restart:**
  - PASS (≥ 1.8): (C) allowed in search.
  - MARGINAL (1.2 to < 1.8): (C) allowed in search, since any gain is free once fidelity has passed. MARGINAL does not justify building (B) on top.
  - NO_GAIN (< 1.2): process restart stays for search.

  (Feasibility §7 names these verdicts THROUGHPUT_PASS, MARGINAL and NO_GAIN, on the ratio of the option to the control.)

## 5. Randomness and the RNG rule

- Nicolas states that no randomness affects Break the Targets outcomes. This statement is recorded here.
- The RNG rule stays exactly as it is: nothing reads, writes, selects, logs, compares or hashes the native RNG seed or state.
- Fidelity is proven only behaviourally: through P1 and the prefix digest alarm (section 6).
- If divergence ever appears, the response is a lower episode cap or NO_GAIN, never RNG inspection.

## 6. Standing safeguards when (C) is in use

- Episode cap per process ≤ the cap P1 tested.
- Every candidate's prefix is digest-checked against its reference. The digest covers only records the agent already produces, never RNG state. Any mismatch retires the process immediately and is logged.
- This is a free drift alarm, so the digest check is never switched off for speed.

## 7. Sequencing

- Building (C) waits for the decomp source-level check and the audit 9.4 fix: the decomp rule restated as a source-level check, and audit item 9.4 fixed in its own build (feasibility §5 and §9, Q7; `docs/rl_generalization_audit_2026-10-13.md`, item 9.4). (C) is new native code.
- The throughput decision (soft reset, in-process chaining or batched prefix), tier 2 and the batched-prefix design depend on this pilot's outcome (`docs/rl_decisions_2026-10-16_addendum.md`, parts 1 (Q13) and 2).

## 8. Options considered

- **Option 1 (chosen):** allow (C) for search only, pilot-gated, as above.
- **Option 2, defer:** keep process restart.
  Correction to the advisor's first framing: today's pipeline gives about 4,800 candidates per hour for the segment shapes (a projection) and 5,057 per hour measured for the archive-job shape (feasibility §4). The segment-optimiser pilot's INVALID verdict ("INVALID: fewer than 3,000 candidates evaluated in the hour", addendum part 1, Q8) belongs to that pilot, not to this pilot's P2, and is unlikely to be hit without (C). The real cost of deferring: tier 2 stays blocked, and search runs at about 36 % to 77 % of (C)'s projected speed (feasibility §4: (C) gives 1.3 to 2.8 times today's throughput).
- **Option 3, allow (C) and (B) together:** rejected. (B) is the largest change and is revisited only with (C)'s evidence.
  Superseded 2026-11-03: (B) is not pursued at all (section 9).
- **Option 4, reject resets permanently:** rejected. It would cap every future search line at boot-bound throughput.

## 9. (B) mid-episode snapshots: NOT PURSUED (decided 2026-11-03)

- Nicolas closed this on 2026-11-03. Mid-episode native savestates are not pursued: neither (B) nor any equivalent, for example
  `fork()`-based snapshots.
- They are not revisited after the (C) pilot.
- Recorded in `docs/rl_decisions_2026-11-04.md` §2.
- (C) is not a snapshot. Sections 1 to 7 are unchanged.
- The draft RNG-compatibility wording that stood here was never decided. It is withdrawn, and it remains in this file's history
  (commit b255bdc).
