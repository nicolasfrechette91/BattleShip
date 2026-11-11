# Right-side arm: design proposal (2026-11-10)

**Status: proposal only. Zero native ticks, nothing built, nothing decided.** Written during the night run
`C:/BattleShip_lab/crossing_2026-11-10_run3b` (launched 22:46 local) without touching any file of the run 3 manifest (rl/, tools/frs/,
tools/glitch/: 54 files, digest `d0cdde51` unchanged). The lab was read only; the running night's folder was not read for this record. The
working scripts are in the session scratchpad (Appendix), at below-normal priority. Target ids, ticks, cells and phases below describe the
records; no rule proposed in section 5 names one.

Sources: `docs/frs_strategy_2026-10-16.md` s6 option 3 and s8 q5; `docs/frs_frontier_2026-10-14.md`; `docs/frs_moving_geometry_timing_2026-10-16.md`;
`docs/frs_departure_probe_result_2026-11-03.md`; SESSION_LOG_2026-11-04.md s18-19.5; the lab folders of crossing runs 1 and 2, run 3 night 1
(`crossing_2026-11-06_run3`) and the frontier search (`frontier_2026-10-14`); the 978's verify trace (`clear_n40597_c9709_k1_r1`).

## 0. Summary

- **The 978's crossing (target 2 at 530 to target 6 at 869, 339 ticks) is 28 ticks to get onto the moving line and off it, a 160-tick
  flight, 34 ticks of landing lag and restart on the far static floor, and 117 ticks from there to target 6.** 311 of the 339 ticks come
  after the take-off from the moving line (tick 559).
- **The right side alone can only move the take-off.** Every traced crossing leaves the moving line, and the line repeats every 300
  ticks. The 978 takes off 20 ticks after the line's bottom (phase 20). The earliest level-7 arrival anywhere is 493, so on this
  crossing type a faster right side can save at most 66 ticks (taking off at 493 instead of 559), and in practice less. That earlier
  take-off would fall while the line descends, and **no verified clear on record took off in that part of the cycle** (phases 196 to 19;
  the 978's 20 is the nearest). A larger change needs a new crossing type.
- **Re-finding the crossing is the binding risk.** In runs 1, 2 and night 1, only three level-7 ends with targets 1, 6 and 8 live
  (mask 322) ever crossed through target 6 (level-7 arrivals 530, 639 and 848). Their per-dispatch crossing rates were 1.1 %, 1.4 % and 2.9 %. The 65 ends that
  arrived before 530 received 6,386 dispatches and crossed 0 times. 5,304 of those dispatches went to two helpless (A0) ends (493 and 525),
  and the resourceful fast ends (A1 / A2 / grounded: 14 ends) received about 730.
- **Frontier search, levels 1 to 7:** fast and plentiful up to level 6 (earliest arrivals 28 / 78 / 120 / 184 / 280 / 461). Level 6 advanced
  in 0.7 % of 3,092 bursts, and level 7 in 0 of 368. Its resourceful level-7 arrivals all came later than the 978's (A1 638, grounded 794,
  A2 848; its 493 is A0).
- **Recommendation:** first a zero-tick check of tonight's own data, then option A (a fast-end crossing test inside a normal frontier
  night, 10 % share, about 1 day of build). Build the tick-0 arm (option B, its own night) only if a fast end crosses. Option C (two arms
  in one engine) only after B pays.

## 1. The 978's crossing, tick by tick (verify trace r1)

Breaks: 4@29, 0@80, 5@167, 7@184, 9@305, 3@461, **2@530, 6@869**, 8@937, 1@978. Tick t = the reply after input tick t; phase = (t − 239)
mod 300 (the moving-geometry record's convention: 0 = the line's bottom, rising).

| ticks | n | what the trace shows | part |
| --- | ---: | --- | --- |
| 530 | 1 | target 2 broken in the air (aerial 210, hitlag 7) above the moving line 19, both jumps used (A1), line at its low point, descending (phase 291) | break |
| 531-551 | 21 | aerial continues, falling onto the line | onto the line (28) |
| 552-558 | 7 | lands on line 19 at phase 13 (line rising from 1,538), 4 landing + 3 jump squat; jumps restored | |
| 559-618 | 60 | take-off at phase 20 (line 1,587, rising), aerial drift left over lines 2 and 4 | flight (160) |
| 619-663 | 45 | fall, double jump, aerial 211 x 39 | |
| 664-718 | 55 | up-B (special_hi) x 39, then helpless x 16 | |
| 719-752 | 34 | lands on static line 0 (y 3,000): landing lag x 25, 6 ticks of status 28, jump squat x 3 | wall top (34) |
| 753-808 | 56 | jump, aerial x 39, fall, double jump | far side (117) |
| 809-853 | 45 | fireball (special_n 224) x 45, drifting 15 units per tick | |
| 854-869 | 16 | fall, aerial attack 211, **target 6 at 869** | |

For comparison (moving-geometry record): the 1,245 takes off at phase 195 (line high, descending), the 1,352 family at 122 and the reference
at 91; their flights take 164 to 172 ticks. All of them land on the same static floor and then need 82 to 157 ticks to the next break.
The 978 is the first record to take off from the bottom of the cycle (phase 20).

## 2. Crossings on record (runs 1, 2, night 1): census

Every dispatch whose burst broke target 6: 138 (run 1 40, run 2 51, night 1 47), 78 distinct (previous break, break) pairs. Each
lineage's arrival at the previous level was rebuilt from the cells' `origin.parent_digest` chain and the dispatches' `levels`; all 138
resolved.

| right-side end (level before, live mask, previous break tick) | breaks of 6 | earliest 6 | shortest (prev to 6) | runs |
| --- | ---: | ---: | ---: | --- |
| level 6, 326 (target 2 still live), 461 | 6 | **789** | 328 | n1 |
| level 7, 322, **530** (the 978's) | 2 | 869 | 339 | n1 |
| level 6, 330 (target 3 live), 525 | 10 | 879 | 354 | r2, n1 |
| level 7, 70 (target 8 first), 894 | 17 | 957 | 63 | n1 |
| level 7, 322, 639 (the 1,245's) | 28 | 991 | 352 | r2, n1 |
| level 6, 330, 486 | 7 | 1,121 | 635 | r2, n1 |
| level 7, 322, 848 (run 1's) | 68 | 1,127 | 279 | r1, r2 |

**Level-7 dispatches with target 6 live, by the lineage's level-7 arrival** (all three runs): before 500: 1,168 dispatches, 0 crossings;
500-549: 6,345, 2 (the 530 end); 550-599: 355, 0; 600-649: 2,420, 28; 650-799: 537, 0; 800-899: 4,587, 85; 900 and later: 492, 0.

**Per right-side end** (the lineage's first kept level-7 version): 403 ends were dispatched. Only these crossed through 6 with mask 322:
530 end (A1, cell (8, 6)) 2 crossings in 187 dispatches, 639 end (A2) 28 in 1,965, 848 end (A2) 68 in 2,326. The fast ends that never
crossed include 525 A0 (run 1) with 4,139 dispatches, 493 A0 (the frontier's state, run 1) with 1,165, 521 A1 at the 978's own cell
(8, 6) with 377, 538 A2 (run 1) with 109, and 521 A1 at (8, 5) with 117. The other 60 ends before 530 received 1 to 103 each.

**The 6-before-2 orders.** The earliest target-6 break on record is 789 (night 1), 80 ticks ahead of the 978's. It comes from the
461 level-6 state, which skipped target 2. These lineages did come back to 2 (night 1: 3 breaks of 2 at level 7, 4 at level 8). But the
level-9 group with only target 2 left received 1,055 dispatches and cleared 0 times. That route type exists, but the records show no
clear from it.

## 3. The frontier search at levels 1 to 7 (2026-10-14, 37,194 bursts)

| level | states kept | earliest (class) | earliest per class | bursts from it | advanced | falls |
| ---: | ---: | --- | --- | ---: | ---: | ---: |
| 1 | 3 | 28 (A1) | A1 28, A2 36 | 128 | 56 | 0 |
| 2 | 31 | 78 (A0) | A0 78, A1 78, A2 93, G 93 | 2,140 | 371 | 2 |
| 3 | 231 | 120 (A0) | A0 120, G 139, A2 170, A1 172 | 14,922 | 4,654 | 16 |
| 4 | 382 | 184 (A0) | A0 184, A1 232, G 236, A2 252 | 8,720 | 557 | 150 |
| 5 | 328 | 280 (G) | G 280, A2 281, A0 286, A1 291 | 7,616 | 757 | 922 |
| 6 | 185 | 461 (G) | G 461, A1 467, A0 478, A2 519 | 3,092 | 22 | 1,143 |
| 7 | 23 | 493 (A0) | A0 493, A1 638, G 794, A2 848 | 368 | 0 | 155 |

Level-to-level transitions (start = a state's own arrival; min / p10 / median): 1→2 49 / 58 / 86; 2→3 6 / 92 / 140; 3→4 2 / 12 / 30;
4→5 24 / 43 / 145; 5→6 22 / 29 / 29; 6→7 12 / 32 / 84. Readings: levels 1 to 5 are cheap and diverse (the frontier spent 90 % of its bursts
there). Level 6 is where the right side gets hard (0.7 % advance, 37 % falls). Level 7 has the fast states but not the resourceful ones.
The 14 resourceful level-7 ends earlier than 530 in the archive (section 2) and the 978's own 530 end were all made by run 3 night 1,
not by the frontier search.

## 4. The four risks, with the data

1. **Re-finding the crossing.** A new right-side end has an unknown crossing rate. Ends that did cross did so at 1 to 3 % per dispatch,
   and most ends never did. To see a 1 % end with 95 % confidence takes about 300 dispatches (P(0) = 0.99^300 = 5 %). The archive already
   holds 65 ends ahead of 530, but has spent 300 or more dispatches on only two of them (both A0). This risk can be measured before any
   tick-0 search is built.
2. **Diluting the budget.** Night 1's gains needed the whole night: bests at hours 0.2, 0.2, 0.4, 3.8, 4.5, 7.3, 7.5, 7.7; level 8 reached
   869 at dispatch 35,865 (hour about 6.8). A share s taken by the arm stretches the frontier arm's timeline by 1 / (1 − s): 1.11 x at 10 %,
   1.5 x at 1/3.
3. **The per-level pace rule.** Without one, a tick-0 search drifts to the shallow levels: the frontier search put 90 % of its bursts at
   levels 5 and below. A rule that requires being ahead of the best clear at every level would forbid orders that start slower and finish
   faster (the 1,429 order's right-side composite is 168 against an arrival of 798). Proposed generic rule (backward, from the arm's goal):
   eligible at level L if tick <= T_L, with T_(k+1) = the goal and T_L = T_(L+1) − c_L, where c_L is the fastest observed transition from
   the cell's (level, mask) group to the next level (any lineage, re-read from the records at the plan). Here the frontier search's
   level-wide minima stand in for levels 1 to 6. With the goal "level 8 at or before 868" and the fastest crossing from mask 322 (279):
   T_7 589, T_6 577, T_5 555, T_4 531, T_3 529, T_2 523, T_1 474. Against the earliest arrivals (26 / 78 / 120 / 184 / 280 / 461 / 493),
   this is loose at levels 1 to 5, where order diversity is cheap, and binding at levels 6 and 7 (slack 116 and 96).
4. **Archive growth.** Night 1 added 8,946 cells in 41,737 dispatches (0.21 per dispatch); main process peak 560 MB with 46,240 cells.
   Under run 3's reach-keeping, a tick-0 night of about 48,000 dispatches (the frontier search's 6,312 per hour, with shorter prefixes)
   would add about 10,000 to 20,000 cells, +150 to 300 MB, within the 2,560 MB soft budget. Keeping cells only under T_L (risk 3) caps it.
   With only level arrivals kept (the frontier search's `breaks` mode) it would add about 1,300 states in 6 h.

## 5. Options

The milestone is shared by all three options and is generic: **a level-8 arrival (the first left-side break) at or before the line's
earliest level-8 arrival minus one (868 tonight), from a lineage whose level-7 end differs from the best clear's.** PROGRESS also counts
any verified clear faster than the best by more than the registered margin. Every option keeps claims, verification, text replay and the
E7 bound exactly as run 3 has them.

### Option A: fast-end crossing test inside the frontier arm (precursor; no tick-0 search)

- **Mechanism.** A new exploitation stream `pace` with a 0.10 share. It draws level-7 cells (target 6 live) whose lineage reached level 7
  before the best clear's lineage did (530 tonight). The level-7 arrival comes from the digest chain, as in section 2, computed at the
  plan. Draws go per right-side end in rotation, every class, until each end has 300 dispatches; then that end leaves the stream. The
  hourly record gains a per-end table (dispatches, crossings, earliest level 8).
- **Answers** risk 1 directly with ends the archive already holds: 14 resourceful ends × 300 = 4,200 dispatches, about 10 % of a night.
  The 51 A0 ends at 50 each would add about 2,550 (a 0.16 share in all).
- **Cost.** About 1 day: `run3_select` stream, the level-7 arrival per cell in `run3_load`, the hourly table, unit + e2e tests. A new run 3
  digest (between nights). Native: none of its own; it uses 10 % of one frontier night.
- **Stop rule.** If no end crosses after its 300 dispatches, the fast ends don't cross at 1 % or more. Then a tick-0 arm aimed at the same
  crossing type is not supported, and only a new crossing type would justify one.
- **Expected.** Probably 0 to a few crossings. Any crossing at or before 868 goes straight into the frontier arm's normal flow.

### Option B: tick-0 arm on its own night (separate folder)

- **Mechanism.** The run 3 engine in a new mode with a single tick-0 root (an empty-prefix seed at level 0), keeping cells at levels 0 to
  8 under the crossing3 key. Groups (level, mask, order niche) as in D4b, so orders get their own budget units. Level weights over all
  levels, deepest first (for example 0.30 / 0.25 / 0.20 / 0.10 / 0.15 for levels 7 / 6 / 5 / 4 / 3 and below). The backward pace rule
  (risk 3) decides eligibility and keeping. Anchors per (group, class) (DECISIVE 3), breadth 0.2, triggers as now. Every level-7 end gets
  option A's 300-dispatch crossing budget. At the close its level-6 to level-8 cells are exported. The next frontier night imports them as
  seeds through a new `--seeds-from` loader step (prefixes re-derived and checked, as run 1 did with `crossing_seed_v1`).
- **Cost.** 2 to 3 days: tick-0 root and levels below 6 in the engine, the pace rule, the crossing-budget stream, seed export and import,
  tests including a fake-game e2e, a zero-tick census of the masses. Native: one night per arm night, with the frontier arm paused for
  that night (dilution 100 % of that night, 0 % of the others). Strategy stage 2's rule: two arm nights without the milestone, stop.
- **Risks.** All four. Risk 1 dominates (section 2), risk 2 costs whole nights, and risk 4 is controlled by the pace rule.
- **Expected.** New orders and resourceful level-6 and level-7 ends are likely, since levels 1 to 5 are cheap. A crossing from them is
  uncertain, and on the current crossing type the gain is bounded by the take-off (section 0).

### Option C: two arms in one engine (concurrent, share s)

- **Mechanism.** Option B's archive runs inside the frontier night as a second archive. The scheduler splits dispatches s : 1 − s (for
  example 1/3). Each arm keeps its own groups, records, hourly section and inheritance chain. A milestone arrival is imported live into
  the frontier arm's archive at its next ingest.
- **Cost.** 4 to 5 days: a two-archive `Run3Night`, claims and end records per arm, CLAIMS_FROZEN and inheritance rules for two chains,
  rolling demotion and the D1 windows per arm, the full suite. Native: continuous, with the frontier arm slower by 1 / (1 − s) every night
  (1.5 x at 1/3). Main memory +200 to 400 MB.
- **Benefit.** Live hand-off and no lost night. **Risk.** The most code on the launch path, and every night is diluted.

## 6. Recommendation

1. **Zero ticks, after tonight's close:** rerun the section 2 census on tonight's dispatches. Tonight's rank draw already favours the fast
   ends: they are the top ranks and anchors of (7, 322, 322:) and (7, 322, 326:2), each group with 1/6 of level 7's 0.35. If tonight
   gives a resourceful fast end 300 or more dispatches, part of option A is already answered at no cost.
2. **Option A** in the next frontier night, for whatever step 1 leaves untested (10 % share, about 1 day of build).
3. **Option B** only if a fast end crosses, or if the owner wants a new crossing type searched regardless. Then run it for one or two
   nights with option A's crossing budget built in.
4. **Option C** only if option B produces milestone crossings and both arms are wanted every night.

Reason: the right side's contribution to the 530 to 869 crossing is capped by the take-off on the moving line. The binding unknown is
whether any faster end crosses at all, and that can be measured on the archive's existing ends for about a tenth of one night instead of a
new search.

## 7. Open questions for the owner

1. Order of work: (a) census of tonight, then A, then B if A crosses (recommended); (b) B directly for one night; (c) C.
2. Option A's share and per-end budget: (a) 0.10 and 300 dispatches for the resourceful ends, 50 for A0 (recommended); (b) 0.15 and 300
   for all 65 ends (about 19,500 dispatches: more than one night at that share); (c) another split.
3. Milestone: (a) a level-8 arrival at or before the line's earliest minus one, from a different level-7 end (recommended); (b) a verified
   clear only; (c) also a 6-before-2 route (the 789 break) as its own milestone.
4. Pace rule for B or C: (a) backward from the goal with the fastest observed transitions (recommended); (b) the same with p10
   transitions (tighter: T_6 557, T_5 528, T_4 485); (c) ahead of the best clear at every level.
5. Seeds into the frontier arm (B): (a) levels 6 to 8, under the pace rule, every class (recommended); (b) resourceful classes only;
   (c) level 7 and 8 only.

## Addendum: after the night `crossing_2026-11-10_run3b` (2026-11-11, zero ticks)

Recommendation step 1 done (the census rerun with the night added, `ra_crossing_census_n2.py`):

- The night moved level 8 from 869 to 826, 813 and 803, and the best clear to 959. Every one of these came from the 978's own
  right side (the 530 end; the shortest crossing is now 273 ticks, 530 to 803) and gained after the take-off. That is the part of the
  crossing section 0 attributes to the frontier arm.
- Level-7 ends earlier than 530: 92 ends, 11,480 dispatches over all runs (5,094 of them tonight), still 0 crossings. Resourceful ones:
  21 ends, 2,701 dispatches. The two most tested have 0 crossings each: 521 A1 at the 978's own cell (8, 6) with 1,009 dispatches, and
  521 A1 at (8, 5) with 907. At 1,000 dispatches, 0 crossings bounds each one's rate below about 0.3 % (95 %). The 530 end crossed 6
  times in 870 dispatches (0.7 %).
- Option A now covers the 19 resourceful ends still under 300 dispatches: about 4,900 more dispatches, an 11 % share of one night. The
  evidence against a tick-0 arm on this crossing type is stronger than when section 6 was written. The recommendation order stands, but
  B's case rests more on a new crossing type than on a faster right side.

## Appendix. Working files (session scratchpad, not tracked)

- `ra_timeline.py <trace> <from> <to>`: status-run timeline of a verify trace (section 1).
- `ra_crossing_census.py`: section 2; output `ra_crossing_census.json` (138 crossing dispatches, 403 right-side ends, rates by level-7
  arrival); 14 s, streams runs 1, 2 and night 1.
- Inline reads of `frontier_2026-10-14/run/frontier/round_*.jsonl` (1,189 states) and `run/dispatches.jsonl` (section 3), and of night 1's
  dispatches for the 6-before-2 lineages.
