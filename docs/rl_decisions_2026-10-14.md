# Decisions (2026-10-14)

## Supersedes
- The November order in `docs/rl_decisions_2026-10-13.md` ("Donkey Kong first, then g4") is superseded: the Mario fast-route line comes first. Donkey Kong is revisited at the fast-route checkpoint C2; g4 comes after that.
- Reason: the agent should first get much faster on Mario; a second character now would mostly reproduce the same limits.
- This replaces the second bullet of that record's General section and its audit answer 13 ("the character line first"). That record is not edited; its other decisions are not changed by this one.

## Fast-route proposal (`docs/rl_m8_fast_route_proposal_2026-10-13.md`), as changed by its review (`docs/rl_m8_fast_route_proposal_review_2026-10-14.md`)
- All six MUST-CHANGE findings of the review (M1–M6) are accepted. The eleven SHOULD-CHANGE items (S1–S11) are to be addressed in the November preparation.
- Answers to the proposal's sixteen open questions (its section 8):
  - Q1, priority: the fast-route line first (see Supersedes). When Donkey Kong's first search comes, it uses the plain novelty configuration, not R10.
  - Q2, lab mode: adopted with the non-negotiables (proposal section 6.2), plus the review's additions: in-run verification with the verify-flag process (S8); the registered roots in the lab write guard (S10, which also asks that no lab run read `runs/` except the one hashed archive copy); a memory budget (M5); a quarantine rule for stale prefixes (S11); and three replicates for a KEEP (M4). One light review of the lab launch path before the first lab night, focused on proving that the lab cannot write into registered trees.
  - Q3, lab root: outside the checkout at `C:/BattleShip_lab/`, with a weekly hashed copy to D:.
  - Q4, start archive: the main arm starts from a copy of the sd2 closing archive; one fresh-from-tick-0 night in week 2.
  - Q5, E6: dropped everywhere, including the control. This changes which inherited cells are eligible, not only how cells are selected (review S7).
  - Q6, splice probe: done; it ran on 2026-10-14 (`docs/frs_splice_probe_2026-10-14.md`; result below).
  - Q7, starting constants: kappa 8 and the length factor are NOT accepted as starting values (review M2, M3). Use a pooled cell draw and no length factor in the pace pool, or a lag capped at one burst; the preparation decides which, with an offline check.
  - Q8, comparisons: three replicates per arm in ABBA order, with burst ticks reported beside dispatches. A KEEP requires "not worse on I3 and better on I2" (review M4).
  - Q9, plateau: no faster verified clear and no I3 increase over three campaign nights (review S1); plus the review on 2026-11-27.
  - Q10, registration scope: replay, provenance and lineage only.
  - Q11, macro explorer: allowed (the agent's own short word runs, at most 16 ticks), disclosed, as an ablation.
  - Q12, learned policy or model: deferred.
  - Q13, throughput levers: measured once, outside any comparison.
  - Q14, lab index: a tracked lab index, committed weekly.
  - Q15, pace reference: the lead reference comes from the best verified clear's arrival at each level; no length reference at level 7.
  - Q16, naming: module prefix `rl/frs_*`.
- Build order for November (from the review, section 9):
  1. Done: the splice probe.
  2. A minimal lab runner on sd2's archive class, with the E6 switch, burst continuation, in-run verification and memory measurement.
  3. Lab night 1: v4 against v4 plus continuation (both with E6 off), to measure the run-to-run spread, throughput and memory.
  4. Then the fresh counter and the pooled ahead draw. The pools and the remaining components come after.

## Splice probe result (lab, unregistered)
- 9 verified clears at 1,884 / 1,883 (`completion_input_tick` / `completion_time_passed`), one tick faster than sd2's 1,885. Each was replayed twice from tick 0, in fresh processes, with identical digests.
- They are two separate one-tick savings, both while Mario falls after up-B or helpless (seven clears from one saving at level 6, two from another at level 2).
- All 180 splices with gains of 2 or more failed: a fixed input tape cannot absorb a different motion state.
- Consequence: large earlier arrivals can only be used by a search that finishes from those states (the pace-frontier design), not by splicing.
- The 198 candidates are kept as an offline test set for state matching (lab folder `C:/BattleShip_lab/splice_probe_2026-10-14/`).
- The 1,884 clear stays a lab result. It is registered only if it becomes part of a larger improvement.
