# Moving-geometry timing in the verified clears (offline study, 2026-10-16)

Status: COMPLETE. Design study, zero native ticks: no game, emulator, lab command, suite, launcher or build was started.
This record describes the agent's records and proposes; it decides nothing and launches nothing. Target ids, ticks,
translations and phases below describe the data only; the generic consequences in section 6 name none of them.

Sources read: `docs/project_handoff.md`; `docs/frs_route_insight_2026-10-16.md` section 4; `docs/frs_segment_optimiser_proposal_2026-10-16.md`
section 4; `docs/frs_anomaly_inventory_2026-10-16.md` section 1. Data: the per-tick caches `logs/frs_anomaly/cache/` (built from the
lab traces by `logs/frs_anomaly/build_cache.py`) and `logs/frs_anomaly/cache_index.json`, read-only. Working files under `logs/frs_phase/`
(Git-ignored by `.gitignore` line 111, `logs/`; confirmed with `git check-ignore`). No lab file, D: folder or `rl/`, `tools/`, `port/`, `runs/`
file was read or written. No RNG state or seed, no human recording, TAS or external time.

## 0. Summary

- Every distinct verified clear with a per-tick trace (306 of 306) contacts the moving collision group exactly once. The 306 clears
  land on it at only four distinct landings from three lineages: 292 clears share one landing (run 1's lineage, two target orders),
  3 share the reference's landing, 9 one-tick splice variants of the reference share a landing one tick earlier, and the 1,245 and
  1,261 share one landing. In effect the records hold three arrival phases.
- The moving group's recorded translation is a function of the input tick alone (one value per tick, ticks 1 to 1,971, none
  missing) with turning points every 150 ticks and a period of 300 ticks, both measured from the records.
- Riding is where the time goes. Ticks on the moving line: 195 (the 1,245 and 1,261), 138 (run 1's family), 183 (the reference).
  All four clear landings leave the line in the upper part of its range (translation 2,632 to 3,135, phases 89 to 195 of 300),
  and the flight from the line to the next static floor takes 164 to 172 ticks in all three lineages. The non-clear traces left
  at every height, so the records do not show that the upper range is required; they show that every clear used it.
- Dependence on arrival time: the time from first contact to the next break is 503 (arrival phase 0), 429 (phases 207 and 208)
  and 407 to 465 (phase 284). The three arrival phases come from three lineages that also do different things on the line (two
  break a target from it, one does not), so the records cannot separate an arrival-phase effect from the on-line actions. The
  structure that the records do show (periodic motion plus a common leave band) is the stepped kind: the ride lasts until the
  line reaches the leave band, so an arrival just after the band costs up to a cycle. Confidence: low (three arrival phases,
  three lineages, 292 of 306 clears on one landing).
- The 1,245: in the two segments around the moving geometry (581 ticks from the break before contact to the break after
  leaving) it spends 195 ticks riding (99 of them with no horizontal motion), 4 still ticks in the approach and 66 still
  ticks on the static floor after the flight: 261 ticks riding or still (45 %), 169 still (29 %). Its 56-tick still run right
  after landing was not forced by the target's reachability: the target it breaks from the line is recorded as animated and sits
  580 to 620 units above the line at every recorded break, so it moves with the line.

## 1. Method

- Trace set: the 823 cached traces minus the 313 r2 replays identical to their r1 (510 traces), deduplicated by the hash of the
  whole per-tick hash sequence: 495 distinct trajectories, 306 distinct clears (every `result.outcome == "clear"` trace: crossing
  runs 1 and 2, the reference and its copies, the trail-probe and smoke clears, the 9 splice clears) and 189 non-clears (splice
  candidates that ran out of words or fell).
- Moving group: the group whose recorded translation range is non-degenerate (group index 2, id 2, one line, id 19). Nothing
  about its behaviour is assumed; the translation series, turning points and period are measured from the recorded (tick,
  translation) pairs across all traces.
- Contact tick: the fighter's `floor_line_id` is a line of the moving group. Episode: a run of consecutive contact ticks. Landing:
  the first tick of an episode, deduplicated across traces by that tick's per-tick state hash (a landing shared through a common
  prefix counts once).
- Phase of a tick: (tick − 239) mod 300, where 239 is the first recorded bottom turning point and 300 the measured period: phase 0
  is the bottom bound rising, 150 the top bound falling. Defined only for ticks with a recorded translation (no extrapolation).
- Without-progress ticks, generic: still = position unchanged from the previous tick; away = the distance to every live target
  increased (target positions taken from the recorded break positions; the one animated target is therefore approximate);
  riding-still = on the moving line with x unchanged.
- Lineage: the clears' target orders and the divergence tick of each clear from its landing's representative (first tick whose
  per-tick hash differs).

## 2. The moving group as recorded

| quantity | value |
|---|---|
| groups with a non-degenerate translation range | 1 (index 2, id 2, line 19); the other two groups read (0, 0) on every tick |
| translation x / y range | 2,700 fixed / 1,500 to 3,300 |
| recorded ticks | 1 to 1,971, one value per tick, 0 missing, 0 ticks with two values |
| translation at tick 1 | 2,168.3 |
| turning points (tick, translation) | 89 top, 239 bottom, 389, 539, 689, 839, 989, 1,139, 1,289, 1,439, 1,589, 1,739, 1,889 top: alternating every 150 ticks |
| gaps between successive bottoms / tops | 300 (5 of 5) / 300 (6 of 6): measured period 300 ticks |
| phase convention | (tick − 239) mod 300; 0 bottom rising, 150 top falling |

## 3. Per verified clear: contact, ride, leave (deliverable 1)

Distinct clears: 306 (orders [4,5,9,7,0,3,2,6,1,8] x203 and [4,5,9,7,0,3,2,6,8,1] x89 share run 1's landing; [0,4,9,5,3,7,2,6,8,1]
x12 is the reference's lineage; [4,0,5,7,9,3,2,6,8,1] x2 is the 1,245's). Every clear has exactly one contact episode. The four
landings (one row per landing; the clears sharing it diverge from each other only after leaving, except the splice clears, 8 of
which diverge before contact by one tick):

| landing (representative) | clears | clocks min / med / max | previous break | first contact | translation, direction, phase at contact | ticks from previous break (still / away) | ticks on the line (riding-still) | break on the line | leave tick, translation, phase | next break after leaving | first contact to next break | leave to next break | still / away after leaving |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A: `crossing_2026-10-15_run2:clear_n36236_c8692_k0_r1` (the 1,245) | 2 | 1,245 / 1,261 / 1,261 | 461 (target 3) | 539 | 1,500.0, down, 0 (the bottom turning point) | 78 (4 / 0) | 195 (99) | 639 (target 2), phase 100 | 734, 2,926, 195 | 1,042 (target 6) | 503 | 308 | 66 / 16 |
| B: `crossing_2026-10-15:clear_n10074_c9306_k6_r1` (run 1) | 292 | 1,352 / 1,611 / 1,883 | 761 (target 3) | 823 | 1,557.1, down, 284 | 62 (0 / 11) | 138 (53) | 848 (target 2), phase 9 | 961, 3,124, 122 | 1,231 to 1,288 (target 6) | 407 to 465 (median 465) | 269 to 327 | 32 to 78 / 14 to 24 |
| C: `crossing_2026-10-15:reference` (1,885; also smoke 1,930, trail 1,971) | 3 | 1,885 / 1,930 / 1,971 | 1,339 (target 2, broken in the air 8 ticks before contact) | 1,347 | 2,700.8, down, 208 | 8 (4 / 3) | 183 (74) | none | 1,530, 2,666, 91 | 1,776 (target 6) | 429 | 246 | 26 / 15 |
| D: `splice_probe_2026-10-14:c073_cid2290_r1` (the 9 splice clears, 1,884) | 9 | 1,884 | 1,338 (target 2) | 1,346 | 2,717.8, down, 207 | 8 (4 / 3) | 182 (75) | none | 1,528, 2,632, 89 | 1,775 (target 6) | 429 | 247 | 26 / 15 |

What happens on the line (status run-lengths are the recorded `fighter_status_id`; the labels are the classifier's):

- A: up-B (226) x6 on contact, then 59 x25, 18 x6, 166 x15: a 56-tick run with no horizontal motion (ticks 546 to 601) while the
  line rises from 1,511 to 2,168; then 28 x4, 152 x1, 157 x31 (the 31-tick roll of the optimiser proposal), attack 227 from 627; the
  break at 639 (line 2,833, fighter 3,133, target 3,417); status 227 continues to 716 (77 ticks after the break, 39 of them with no
  horizontal motion while the line passes its top at 689 and descends to 3,113); then 20 x3, 22 x13, 210 x1; the fighter jumps off at
  734 (status 210, jumps 1, vertical speed +34) with the line at 2,911 descending.
- B: aerial attack (211) x13 on contact, 32 x11, attack 228/227 from 836; the break at 848 (line 1,519, fighter 1,827, target 2,115),
  25 ticks after contact; status 227/228 continues to 940 (88 ticks after the break, 42 with no horizontal motion while the line
  rises from 2,186 to 2,896); 28 x3, 20 x3, 23 x17; the jump off at 961 (status 209, vertical speed +39) with the line at 3,135 rising.
- C: up-B (226) x20 on contact, 58 x2, 59 x25 (29 still ticks while the line descends from 2,257 to 1,802), 20 x3, 22 x20, 211 x39,
  26 x3, 210 x14, 215 x30, 152 x3, 154 x11 (43 still ticks while the line rises from 1,788 to 2,490), 20 x3, 211 x10; the fighter
  leaves at 1,530 in an aerial attack (211, vertical speed +56) with the line at 2,684 rising. D is C shifted one tick.
- After leaving, all three lineages fly 164 to 172 ticks before the next ground/air change (A 171, B 170, C 164), landing on the
  same static floor (line 0, y 3,000) on the far side; the still ticks after leaving sit on that floor (A 65 at x −1,848; B 31 to
  77; C 25), and the next break follows 82 to 157 ticks after that landing (A 137, B 100 to 155, C 82).
- The target broken from the line (id 2) is recorded as animated with x 2,700 (the group's x) and y 3,417 (A), 2,115 (B), 3,449
  (C), i.e. 584, 596 and 616 above the line's translation at the three breaks: it rides the group.

The 32 non-clear landings (splice candidates; `logs/frs_phase/tables.md`) arrive at 28 distinct phases spanning the whole cycle
and leave at translations from 1,523 to 3,262 (16 of 32 below 2,000); ticks on the line 3 to 358. Only one has a later break
(a different target, 271 ticks after contact). They show that leaving is recorded at every height; they say nothing about clearing.

## 4. Dependence on arrival time (deliverable 2)

Every landing with a break after leaving, by phase at contact:

| phase at contact | translation, direction | ticks on the line | leave phase, translation | first contact to next break | leave to next break | outcome, clears sharing |
|---|---|---|---|---|---|---|
| 0 | 1,500 down (bottom) | 195 | 195, 2,926 | 503 | 308 | clear, 2 (A) |
| 207 | 2,718 down | 181 to 182 | 88 to 89, 2,614 to 2,632 | 429 | 247 to 248 | clear, 9 (D) and 2 non-clears |
| 208 | 2,701 down | 183 | 91, 2,666 | 429 | 246 | clear, 3 (C) |
| 277 | 1,614 down | 230 | 207, 2,735 | 271 (a different target) | 41 | non-clear |
| 284 | 1,557 down | 138 | 122, 3,124 | 407 to 465 | 269 to 327 | clear, 292 (B) |

Same-phase control: the 292 clears of landing B share every tick through the leave (all diverge at tick 1,055 or later, after
leaving at 961), so their 58-tick spread in "first contact to next break" (407 to 465) and 531-tick spread in clock (1,352 to
1,883) arise entirely after the moving geometry. The 3 clears of C and the 2 of A likewise diverge only after leaving.

Reading of the relation:

- Flat, smooth or stepped cannot be decided from three arrival phases that are also three lineages with different on-line actions
  (A and B break a target from the line and then hold an attack status for 77 and 88 ticks; C broke it in the air before contact).
  The differences in "first contact to next break" (407 to 503) come in part from the ride (138 to 195) and in part from the static
  side after the flight (82 to 157), not from the moving line alone.
- What the records show consistently: the motion is periodic with a 300-tick period; all four clear landings leave the line in one
  band of the cycle (phases 89 to 195, translation 2,632 to 3,135, in or just past the rising half); the flight after leaving takes
  164 to 172 ticks in all lineages; and the ride ends 16 to 105 ticks after the line passes the bottom and rises past 2,600. Given a
  common leave band, the ride length is the wait for the line to reach that band: (leave phase − arrival phase) mod 300, which is a
  sawtooth in the arrival phase. The three clear points fit it (284 → 138; 0 → 195; 208 → 183: 92 ticks down to the bottom plus 91
  up). This is the stepped kind: an arrival just after the band would wait most of a cycle; arrivals anywhere inside the waiting
  stretch reach the next break at about the same tick, so a saving before the geometry is absorbed unless it moves the arrival
  across a band boundary.
- The records do not show that the band is required: 16 of 32 non-clear landings left below translation 2,000, at phases spread over
  the cycle, but none of those traces cleared or holds a later break on the crossing side, so whether leaving earlier in the cycle
  can lead to a clear is not in the data. The band is what every clear did, not what the geometry forces.
- Confidence: low. 306 clears, but 292 on one landing; three arrival phases, three lineages; no clear arrives in the rising half of
  the cycle (phases 1 to 149) except by riding into it.

## 5. The 1,245 (deliverable 3)

Segments around the moving geometry: target 3 broken at 461, contact at 539, target 2 broken from the line at 639, leave at 734,
target 6 broken at 1,042: 581 ticks (the optimiser proposal's 3 → 2 and 2 → 6 segments, 178 + 403).

| part | ticks | riding | still (no motion) | moving away from every live target | what the records show |
|---|---|---|---|---|---|
| break of 3 to contact | 78 | 0 | 4 | 0 | 20 x3, 23 x1, aerial attack 211 x39, 26 x10, up-B 226 x24; contact exactly at the bottom turning point, line descending to meet the rising fighter |
| contact to break of 2 | 100 | 100 | 56 with no horizontal motion (ticks 546 to 601, line 1,511 to 2,168) | 7 | 6 ticks of up-B, 25 + 6 + 15 ticks of ground statuses standing still, 4 + 1, the 31-tick roll, attack |
| break of 2 to leave | 95 | 95 | 43 with no horizontal motion (39 in status 227, ticks 681 to 719, line 3,285 to 3,113) | 8 | status 227 held to 716 (77 ticks after the break), then 3 + 13 ground ticks, jump at 734 with the line at 2,911 descending, 45 ticks past the top |
| leave to break of 6 | 308 | 0 | 66 (65 at x −1,848, y 3,000 on static line 0, ticks 907 to 971) | 16 | flight 171 ticks over lines 2 and 4 to line 0, 137 ticks on the static side |
| total | 581 | 195 (34 %) | 169 (29 %) | 31 | riding or still: 261 (45 %) |

The 56-tick still run after landing is not a wait for the target: the target broken from the line moves with the line (584 above
it at this break, 596 and 616 at the other two recorded breaks), and lineage B broke it 25 ticks after contact at translation 1,519
with the line near the bottom. The wait in A is in the agent's recorded inputs, not in the geometry. Likewise the 77 ticks of status
227 after the break (39 of them motionless as the line crosses its top) are the fighter's state, not the line's.

What arrivals at other phases were followed by (observations, not bounds):

- 16 ticks earlier in the cycle (phase 284, lineage B): a ride of 138 ticks, break of the same target 25 ticks after contact near
  the bottom, a jump off at translation 3,124 while rising (phase 122), 73 ticks earlier in the cycle than A's leave. From contact to
  the next break: 407 to 465 against A's 503. Its approach was 62 ticks from the previous break (A: 78).
- 92 ticks before the bottom (phase 208, lineage C): a ride of 183 ticks (92 down, 91 up), leaving at 2,666 while rising (phase 91);
  from contact to the next break 429. Its previous break was the on-line target, broken in the air 8 ticks before contact.
- If the 1,245 had arrived later by up to about 90 ticks at the same landing height and kept the same leave tick, the ride would
  have been shorter by the same amount and the next break unchanged: the arrival time would have been absorbed. If it had left
  while rising, as B and C did (phase 91 to 122, 73 to 104 ticks before its actual leave), the next break could have come earlier by
  up to that amount, provided the flight from a lower, rising line still reaches the far floor; B's and C's flights (170 and 164
  ticks from 3,124 and 2,666) say that flights from both heights reached it, but from a different x and state. Arriving earlier at
  the same landing would have added the extra wait before the bottom, as in B (16 ticks), with no change at the next break unless
  the on-line actions also finished earlier.

## 6. Consequences, generic (deliverable 4)

No rule here names a target, order, tick, period or coordinate; the numbers above describe the data.

- Segment optimiser, S2 end-to-end acceptance. A segment that ends on, or whose successor starts from, a moving collision group has an
  end state that includes the group's recorded translation and direction at that tick. Its value is not its own duration: the records
  show the ride lasting until the group reaches a band of its cycle, so two end states that differ only in arrival time can lead to
  the same tick at the next break. S2 should accept a candidate segment only on the chained time through the first break (or first
  static-floor landing) after the moving geometry, with the successor segment re-run from the new end state; a segment-local
  saving that does not change that later tick should count as zero. Where the end-state price is used instead, it must carry the
  group's phase as measured from the records (translation and direction at the end tick), never a value computed from a formula.
- Value of time saved before the moving geometry. A saving upstream of the group is realised at the next break only if it moves the
  arrival across the boundary of the band the ride waits for; smaller savings are absorbed into the ride. So upstream gains should be
  valued by the change in the tick of the first break after the moving geometry (measured by replaying through it), not by the local
  saving, and gains smaller than the current ride's slack should be expected to show nothing until they accumulate past a boundary.
  Conversely a saving that shortens the ride itself (leaving the group earlier in its cycle, or acting on it sooner) is realised in
  full, which makes the on-group actions the better place to look for time than the approach.
- Tier 1 stage 2 (the order-diverse arm). Order diversity changes the arrival phase at the moving group for free: the three recorded
  lineages arrive at three phases because they break different targets first. The arm should therefore record the moving group's
  translation and direction with every cell it keeps (the cell records hold none today), rank cells that sit on a moving group by
  their earliest arrival at the next static cell rather than by their arrival at contact, and treat the arrival phase as a diversity
  key within a (level, mask) group so that anchors do not all share one phase. The earliest contact is not the earliest exit.

## 7. Open questions for the owner (recommendation first)

1. Should run 3's cell records store each non-static group's translation and direction at the cell tick?
   (a) Yes, add them to the cell end record from the native `spatial.groups` already in the observation (recommended; cheap, needed by
   the stage-2 ranking above and by any later phase analysis without traces). (b) Derive them offline from the tick through the recorded
   series (valid only inside the recorded tick range; no new field). (c) No.
2. How should S2 accept a segment that ends on or just before the moving group?
   (a) On the chained time to the first break after the moving geometry, re-running the successor segment from the new end state
   (recommended; the only measure the records support). (b) On the segment's own time plus a phase price learned from the records
   (needs more than three arrival phases). (c) On the segment's own time alone (the records show this can be zero-valued end to end).
3. Should the arrival-rank draw and the anchors treat cells on a moving group by arrival at the next static cell?
   (a) Yes, rank and anchor by the earliest arrival at the next static cell, keeping arrival phase as a diversity key (recommended).
   (b) Keep arrival at contact (as today). (c) Keep both as separate groups.
4. Is a short lab probe of leaving the group earlier in its cycle worth a few minutes of native time after stage 1?
   (a) Yes: a splice-style probe from the best clear's on-line states that jumps off at each tick of the rising half, replayed and
   compared at the first break after the geometry (recommended; answers in minutes what the records cannot, as the splice probe did).
   (b) Fold it into the segment-optimiser pilot. (c) No probe; rely on the search.
5. Which phase convention should later records use?
   (a) Phase measured from the records each time (origin at the first recorded bottom turning point, modulo the measured period), with
   translation and direction also stated (recommended; stage-agnostic and verifiable). (b) Raw translation and direction only.
   (c) A fixed convention written into a tool.

## Compliance

- Zero native ticks; nothing started. Read-only on the caches and index; `logs/frs_route/` not modified. Nothing written in
  `C:/BattleShip_lab/`, on D:, or under `rl/`, `tools/`, `port/`, `runs/`; no file matching the excluded patterns touched; no registered D:
  folder read.
- Working files only under `logs/frs_phase/` (Git-ignored). Standard-library Python with `python -B`, reading files only; total script
  time about 25 seconds.
- No RNG state or seed read, logged, compared or discussed; no TAS, human recording, owner time or external time used.
- Timebox: about 25 minutes of work; complete.
- LF line endings: CR count 0 for this record and every working file (checked with `tr -cd '\r' | wc -c`).

## Appendix A. Working files, commands and checks

| file | content |
|---|---|
| `logs/frs_phase/p1_contacts.py` | loads the 510 caches, measures the moving group's series, turning points and period, finds contact episodes, classifies approach / ride / after ticks, deduplicates trajectories and landings, computes per-landing divergence and spreads; writes `contacts.json` (about 7 s) |
| `logs/frs_phase/p2_tables.py` | the tables of sections 3 and 4 and the 36-landing and leave-phase tables; writes `tables.md` |
| `logs/frs_phase/p3_detail.py` | ride detail for five traces (status run-lengths, still runs against the line's translation, the on-line break, leaving, floors and still runs after leaving) and the fighter's height at contact and leave for all 36 landings; writes `detail.md` |

Commands (from the checkout root): `python -B logs/frs_phase/p1_contacts.py`, `python -B logs/frs_phase/p2_tables.py`,
`python -B logs/frs_phase/p3_detail.py`.

Checks: the 36 distinct landings, the 5,336 contact ticks' share, the 1,245's landing at 539 / leave at 733 and lineage B's 823 / 960
agree with the route-insight record's section 4 (its "leaves at" is the last contact tick; this record's leave tick is the first
tick off the line, one later). The 1,245's 77 riding ticks and 70 wall-top ticks in the segment-optimiser proposal's 2 → 6 row are
the ride after the on-line break (95 here, counted from the break tick) and the still ticks on the far floor (66 here); the
difference is the counting rule, not the data.
