# Decisions addendum (2026-10-16)

Everything in `docs/rl_decisions_2026-10-16.md` stands unless this addendum says otherwise. That record is not edited.

In this addendum, "section N" and "QN" refer to the segment optimiser study, `docs/frs_segment_optimiser_proposal_2026-10-16.md`
("the study"); the parts of this addendum are "part 1" to "part 4".

## Part 1. Owner decisions on the segment optimiser study (its section 10)

The recommended option is accepted for every question, with the exceptions and amendments below. For most questions that is the first
option listed; for Q5 it is (b) (forward sweep with re-optimisation, with the one-evaluation splice test first) and for Q6 it is (c)
(a separate line until a verified chained clear, then an operator over multi-representative cells).

- **Q1, pilot segment.** Rule (a) (the largest gap to the fastest same-class observed transition, among segments at most 200 ticks long),
  plus a generic exclusion: skip any segment during which the fighter's floor line belongs to a moving collision group at any tick. The
  exclusion is read from the records and is generic across stages. The tool computes the selection itself and logs it; no segment, target
  id, tick or coordinate is written into any rule, prompt or code. S0 confirms which segment the rule selects by running it on the current
  best verified clear. If it selects the clear's last segment, no segment follows it: pilot measurements 3 and 4 (end-state class,
  two-segment time) do not apply and move to S2, and the PASS clause on the end class ("ends in a class not worse than the clear's own end
  class at that boundary", section 7) does not apply, so PASS is then a break at least 30 ticks earlier than the clear's.
- **Q3, pilot method.** (a) for the first hour, as recommended. The random-restart control (section 2.1) is required, not optional:
  30 minutes, from the same start state with the same caps, run after the Go-Explore hour. Run 2's history on the lineage is recorded
  beside it but is not the control.
- **Q8, pass thresholds.** (a), with (b) recorded beside it, plus a new verdict, INVALID: fewer than 3,000 candidates evaluated in the
  hour. The method is then not judged, and the hour is re-run after the throughput issue is fixed. FAIL then means only: no candidate
  breaks the target earlier than the clear within the hour at that budget.
- **Pilot measurement 1** (section 7) also records CPU time per boot, from the operating system's process counters, beside the wall
  split. This closes item 3 of section 9.
- **S2, forward sweep** (sections 5 and 8). An upstream segment change is accepted only on the end-to-end clock after the downstream
  segments are re-optimised (at minimum the clock through the next three breaks), never on the segment's own time. Reason, generic:
  moving geometry may depend on elapsed time, so an earlier arrival can make a downstream segment slower.
- **Q13, order against tier 1.** (a), unchanged, plus: November week 1 opens with the savestate decision (part 3), and any native design
  of the batched prefix waits for that decision. S0 and tier 1's stage 0 are separate local sessions, run one after the other.

## Part 2. Consequences recorded

- The study finds that candidate evaluation is boot-bound (section 3): the native batched prefix is not the binding lever for the
  optimiser. The dependency of tier 2 on the batched prefix stated in `docs/rl_decisions_2026-10-16.md` (its Q9) is replaced by: tier 2
  depends on the throughput decision (savestates, in-process chaining, or the batched prefix), decided in November week 1. The design of
  the batched prefix no longer starts by default in week 1; it waits for that decision (part 1, Q13).
- Room estimates (section 4, and the composite in `docs/frs_strategy_2026-10-16.md`) are optimistic for segments in contact with moving
  geometry: their pair bests were observed at other arrival times and may be unreachable from the clear's own states. The other segments
  are unaffected.
- The segment optimiser polishes pace within one route family (risk 5, section 8). It complements, and does not replace, the discovery
  track (part 4).

## Part 3. November week 1, first decision: native savestates for search only

Open: the owner decides, and nothing is built before the decision. The question is whether to allow native savestates for search only.

Unchanged in any case: every claimed clear is verified by exact replay from tick 0, twice, in fresh processes with the verify flags.

Questions to settle:

- (a) Fidelity: restore-and-continue must reproduce replay from tick 0 exactly, on canonical records at every tick, proven before any
  use.
- (b) RNG: the snapshot is opaque and is never read, logged, compared or hashed for RNG content. The owner decides whether restoring it
  is compatible with the RNG rule, and the decision is written down.
- (c) False discoveries: any anomaly or clear found through a restored state counts only after replay from tick 0.
- (d) Cost: memory and disk on 16 GB of RAM, and the restore cost against a replayed prefix.
- (e) Disclosure in the video.

A savestate feasibility study (offline) is in preparation and will be referenced by its own document.

## Part 4. November agenda, not decided: the discovery track

- (a) An anomaly detector over the agent's own trajectories: collision-line pass-through between ticks, position jumps, positions inside
  or outside the geometry, impossible velocities or status changes, breaks from unusual distances. First offline on existing lab data,
  then live in every run.
- (b) A discovery arm that rewards rare physical events and unusual states instead of pace.
- (c) Route-insight reports for the owner: target orders used, segment maps, arrival times at moving geometry, and a timing-robustness
  check for human viability.
- (d) The owner's review of the top clears and flagged anomalies in the replay browser.

Constraints stated with it:

- Detection may read collision geometry generically from game memory.
- Any reward built on it stays stage-agnostic.
- An anomaly counts as a game discovery only if it reproduces by replay from tick 0, and as a discovery for the original game only after
  a validation step on the original game (to be defined), because a PC-port artifact is not a game discovery.
