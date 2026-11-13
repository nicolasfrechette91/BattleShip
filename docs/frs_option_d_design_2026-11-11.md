# Option D, order discovery from tick 0: detailed design (2026-11-11)

**Status: all 9 open questions settled by the owner on 2026-11-12 (section 12), and the eleven gaps A to F and G1 to G5 that the build
found (section 3.5); the design is decided. Zero native ticks so far.**
Written during night 3 of run 3
(`C:/BattleShip_lab/crossing_2026-11-11_run3c`, launched 22:21 local) in a separate git worktree
(`C:/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip_optionD`, branch `design/option-d` from `cbc64a4`). No file of the main tree
was modified, and the run 3 manifest (54 files, digest `73cbde95`) was not touched. The lab was read only, and the running night's folder
was read only for progress lines.

Owner's frame (2026-11-11): D is approved in principle and option A is abandoned. **The agent must discover the target order itself.**
There is no human route and no order suggested from knowledge of the stage. This document gives the detailed design the owner asked for:

- the budget unit (target sets, then orders);
- the pace rule 48·L + 120 and its justification;
- roots and seeds;
- how D coexists with the frontier archive;
- the pilot night protocol (frontier paused);
- the success criteria (level 6 at or before 408);
- the tests.

Sources:
- `docs/frs_right_side_arm_proposal_2026-11-10.md` (addendum 2: option D in outline, the pace table);
- `docs/frs_route_insight_2026-10-16.md` (the order concentration, descriptive only);
- `docs/frs_frontier_2026-10-14.md`;
- `docs/frs_prefix_cost_2026-10-14.md`;
- `STATE_MACHINE_CANDIDATES.md` s4 (the 8 s threshold);
- `docs/rl_decisions_2026-11-04.md` s5 (DECISIVE 4 / 4b);
- the run 3 code (`tools/frs/run3_select.py`, `run3_search.py`, `crossing_search_run3.py`, `rl/m8_rd_cells.py`, `rl/frs_archive.py`).

## 0. Summary

- **What D is.** A night-long cell search rooted at tick 0 (one empty-prefix root at level 0). Its budget is spread over **target
  sets, then orders**, instead of being concentrated on the pace of one order. A **goal pace rule** keeps a cell only if its tick is at or
  under 48·L + 120, where L is the number of targets broken. D reuses run 3's engine, cells, worker pool, verification, exports and
  integrity checks. It is built in new files, so the frontier arm's digest `73cbde95` stays valid and frontier nights continue during the
  build.
- **Budget unit.** Each dispatch draws:
  1. breadth (0.2) or exploitation (0.8);
  2. for exploitation, a level, deepest first (0.4 / 0.3 / 0.2 / 0.1 over the four deepest levels with an eligible cell);
  3. the **target set** of that level with the fewest dispatches;
  4. the **order** of that set with the fewest dispatches;
  5. a cell of that order, by run 3's rank draw and anchors.

  The accounting unit is one exploitation draw; breadth is a separate, set-blind stream on top. No rule names a target, a position or
  an order.
- **Pace rule.** Eligible and kept at level L if `tick <= (G × L) // 10 + s`, with G = 480 and s = 120.
  - G is the owner's goal: completion at input tick 480 or earlier is a clock under 8.00 s.
  - The linear shape is the only per-level pace that assumes nothing about which targets are cheap.
  - s = 120 sits between two bounds. It must be at least 40 so the records' own fastest level-5 arrival stays inside. It must be at most 156,
    so the current order's level-6 and level-7 arrivals (461, 493) stay outside and that order cannot absorb the budget.
  - 120 is also exactly one burst segment of slack.
- **Roots and seeds.**
  - One root: the tick-0 state, read at the open, and checked equal in two fresh processes.
  - No cell from any earlier archive. No human input of any kind.
  - The search's own keyed random streams take a new `--rng-seed`. Native RNG is never read, and no RNG seed is checked.
- **Coexistence.** D has its own folder, contract, manifest and inheritance chain. D reads one thing from the frontier: its best verified
  clear, read only, as the claim and milestone reference. The frontier reads nothing from D until a hand-off. A hand-off is built only
  after M1 and runs between nights with the owner's go. The lab lock already prevents the two from running at the same time.
- **Pilot night.** The frontier is paused for one night. The prerequisites are:
  - every test passes;
  - the frontier digest is unchanged;
  - a 25-minute smoke with pass criteria;
  - the owner's go.

  The night runs 5 workers for 480 minutes with hourly records. After the close come the usual checks, plus a two-replay verification
  of every milestone arrival.
- **Success.**
  - **M1, the gate:** a verified level-6 arrival at or before 408, in any target set and any order.
  - Reported, not gates: M2 (level 7 at or before 456), M3 (level 8 at or before 504), M4 (level 9 at or before 552), a clear at or
    before 600, and any verified clear faster than the frontier's bound.
  - No M1 in one complete pilot night: stop and review. The slack is never changed automatically.
- **Cost.** About 3 days of build in three verifiable phases (section 10), then one pilot night.

## 1. Purpose, and what D must never do

**Why a new arm.** With 10 targets, the owner's goal (480) means 48 ticks per target. The agent's records follow that pace through level 4.
They fall 40 ticks behind at level 5 and never come back:

| level | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | clear |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fastest arrival on record | 26 | 78 | 120 | 184 | 280 | 461 | 493 | 803 | 869 | 929 |
| 48·L | 48 | 96 | 144 | 192 | 240 | 288 | 336 | 384 | 432 | 480 |

Every record from level 6 on comes from one macro-order. At levels 6 and 7, 94.9 % and 99.5 % of all 133,004 trajectories broke the
same target set. Three orders hold 98.2 % of the level-7 trajectories (route insight s0). Polishing that order (the frontier arm: 1,196
→ 978 → 959 → 929) cannot approach 480. D asks the question the history never asked: whether the agent, given the same action domain
and an equal budget for every set and order it finds, reaches level 6 at the 480 pace plus slack.

**What "the agent discovers the order" means here.** These are enforced rules, not intentions:

- **No target id, position, coordinate, order, tick value from a record, or route** appears in any selection, keeping, pace or
  milestone rule. D's code reads only generic quantities: level, live mask, order label, tick, dispatch counts, resource class and
  break flags. This follows the convention of every FRS module ("No cell id, position, target id ... is in this file").
- **No human input.** D never reads the scripted baseline (468 rows, 7.43 s), any TAS or human recording, any owner time, or any
  route-insight table. The baseline stays what it is: the M1e replay regression fixture.
- **No archive import.** The frontier and run 1 / 2 archives carry the history's order concentration, so D roots at tick 0 only
  (section 5).
- **Relabelling invariance**, as a test: in a fake game whose target ids are permuted, D makes the same dispatch sequence with the labels
  permuted (section 9, U12). Any code path that favoured a particular target would fail it.
- **Detect without steering.** The live anomaly detectors run and record, as in run 3. Their trigger draws are **off** in D's pilot
  (run 3 has them on), so the pilot's budget comes from sets, orders and pace alone. See Q5.
- The hourly report shows, for the owner only, which targets were broken first, which sets exist and so on. **Nothing in a report feeds
  back into a rule** or into the next night's parameters without the owner's decision.

The action domain is unchanged and not up for review: 8 directions at ±80 plus neutral, and one button per frame, through the lab's
CONT explorer (the `m8_rd_explore_v1` keyed stream, 120-word segments).

## 2. Definitions

- **Level L:** the number of targets broken (0 to 10). It equals `10 − popcount(live mask)` (`rl/m8_rd_cells.level_of_mask`).
- **Target set:** the live mask (10 bits) at level L. A set is identified only by its mask, never by what its targets are.
- **Order:** the break sequence from tick 0, the labels of the broken targets in break order (ties within one tick: by target label,
  as run 3 does). This is run 3's **order niche** with the tick-0 root as the only seed: `seed_niche(1023) = (1023, ())`, and a child's
  niche is its parent representative's niche plus the targets its burst broke at or before the child's tick
  (`run3_select.child_niche`, unchanged). With one root, the niche is exactly the full order, and the order determines the set.
  The tie by target label is a label rule, the one place where relabelling the targets can change which order a lineage joins. It is
  kept for the pilot (gap G5, owner 2026-11-12): U12 assumes no two breaks on one tick, and the pilot counts same-tick breaks per level
  (section 7.2, report-only), so the rule can be revisited with data.
- **Group:** run 3's (level, mask, niche label). Under D a group is one order.
- **Cell:** run 3's cell, keyed by `(bx, by, res, mask, floor)` (`rl/m8_rd_cells.cell_key`).
  - The key holds the mask, so cells never mix sets.
  - It does not hold the order. Two orders reaching the same key share one cell, and the faster arrival is the representative
    (run 3's replacement rule). The cell then belongs to the faster representative's order: run 3's group move, DECISIVE 4b.
  - So orders compete cell by cell. An order that is slower at every cell it shares, and holds no other cell, disappears as a group.
    This is intended: with the same mask and the same bucketed state, the faster arrival dominates.

## 3. The budget unit: target sets, then orders

### 3.1 The draw (per dispatch, in this order)

Below, a cell is **active** when it is eligible (inside the line, section 4) and not retired (3.3). Exploitation draws only active
cells; breadth draws any eligible cell, retired or not.

1. **Stream.** Breadth with probability 0.2 (run 3's count-based draw over every eligible cell: weight 1 / (1 + dispatches of the cell)),
   otherwise exploitation. Triggers are off (Q5). An exploitation draw that finds no active cell while retired cells are still
   eligible falls back to a breadth draw, recorded as a fallback (gap G2; the mirror of run 3's breadth-to-exploitation fallback).
2. **Level** (exploitation): weights 0.4 / 0.3 / 0.2 / 0.1 over the four deepest levels that have an active cell, deepest first. With
   fewer than four such levels, the weights are renormalised over those present. The weights go **by rank among the levels present**
   (gap D, owner 2026-11-12): the deepest such level gets 0.4 and the next level present 0.3, whatever the gap between them. Run 3's
   `level_weights` indexes by the distance from the deepest level instead, which would give a weight to a missing level, so D computes
   its own.
3. **Target set:** among the level's sets that have an active cell, the set with the **lowest budget count**. Ties go to the set whose
   earliest active cell has the lowest tick, then to the lowest cell id of that earliest cell (gap A).
4. **Order:** among the set's orders that have an active cell, the order with the lowest budget count. Ties as for sets: the earliest
   active cell's tick, then its cell id (gap A).
5. **Cell:** within the order (= run 3's group), run 3's machinery unchanged, over the order's active cells. Anchors (the 3 earliest
   active cells per resource class) are drawn with probability `anchor_share × w_max`. Otherwise the rank draw
   `(1 + rank)^-1 × max(0.05, 1 / (1 + draws since set))`.

**Tie-breaks (gap A, owner 2026-11-12).** Cell ids follow creation order, which a relabelling of the targets does not change, and a cell
belongs to one set and one order, so the tie-break is total and the relabelling test (U12) holds. The first wording (lowest mask value,
then niche label) favoured low-numbered targets whenever two units tied on count and earliest tick, which happens at every alternation.

**Budget count.** The number of **exploitation** dispatches selected for the set, or for the order, counted when the dispatch is
**selected** (run 3's convention under D4, so the reorder window cannot give one unit ten draws in a row). Breadth dispatches do not
count: breadth is a separate, set-blind stream on top (D-Q3). Counting them would break "within 1", because breadth can give one set more
than exploitation can rebalance, and levels outside the level draw get breadth only. "Within 1" and the hourly bug flag therefore apply
to the levels currently in the level draw.

**New units join at their siblings' minimum.** A set or order that appears mid-night starts at the lowest budget count among its
siblings, not at 0. It gets an equal share from then on, without a catch-up burst that would starve the others. A unit that loses its
last eligible cell leaves the rotation and keeps its count. If it comes back, it resumes at `max(its count, the siblings' minimum)`.
Precisely (gap F, owner 2026-11-12):
- a unit is **in the rotation** while it has an active cell;
- its **siblings** are the other units in the rotation: for a set, the sets of the same level; for an order, the orders of the same set;
- the siblings' minimum is the lowest count among them;
- when there is none (gap G1), the joiner starts at `max(its count, the highest count any sibling ever had)`, 0 when there never was a
  sibling; the first wording ("0 when there is none") let a returner come back far above a newcomer that had refilled an emptied
  level, which gave the newcomer a catch-up burst (31 draws in a row on the fake game);
- the siblings are read before the ingest that brings the unit in: units entering together do not count each other, and units leaving
  in it still count;
- a unit that left because all its cells retired returns like one that lost its eligible cells, at `max(its count, the siblings'
  minimum)`.

With these rules the counts of the units in the rotation stay within 1 at all times: a draw adds 1 to a unit at the minimum, a joiner
starts at or above the minimum, and a unit that left was at most 1 above a minimum that has not fallen since.

### 3.2 Why this unit

- **It inverts the history's allocation.** Every earlier search spent its budget by pace or by productivity inside the order it already
  had: 98 % or more on three orders. Equal counts per set, then per order, give a newly found set at level L the same budget as the
  incumbent's set, from its first cell.
- **Equal is the only split that names nothing.** A productivity-weighted share (run 3's rate window) would favour whatever order
  produces first, which brings the concentration back in. The pace rule (section 4) does the pruning instead: a set or order behind pace
  has no eligible cell and leaves the rotation.
- **Sets before orders.** Orders within one set share most of their future: the same live targets remain. Sets are the coarser
  diversity, and at level L there can be up to C(10, L) of them. Splitting by set first keeps one set with many orders from taking the
  level.
- **Deterministic least-count, not a random uniform draw.** It gives exact equality (within 1 per unit) at any point of the night. It is
  a pure function of the selection history, and the U4 test checks it directly. A keyed uniform draw would also be equal in expectation;
  see Q3.

**Cost of the unit: thin budgets per order.** Illustration with 50,000 dispatches in a night (the smoke measures the real rate; the
frontier search ran 6,312 per hour). Exploitation gets 40,000.
- A deepest level holding 20 sets of 3 orders gets 0.4 × 40,000 / 60, about 270 dispatches per order.
- A level weighted 0.1 holding 100 sets of 2 orders gets 20 per order.

The deepest-first weights are what keep the frontier of discovery fed. Shallow levels get breadth (0.2 of everything) and the 0.1 share.

### 3.3 Dead ends: per-cell retirement

With deepest-first weights, a deep level whose only cells are dead ends would absorb 40 % of exploitation. Run 3 handles dead groups
with the zero-break demotion (a window of 1,000 dispatches). In D, orders are many and small, and few would ever fill a 1,000 window.

Decided instead (D-Q4): **a cell is retired from exploitation after R = 300 of its dispatches, none of which kept a cell (new, or a
faster representative) at a deeper level.** A break behind the line keeps nothing, so it does not hold off retirement. (The first
wording, "no break and no kept cell at a deeper level", would have let one late break protect a dead cell forever.)
- **Why 300:** the detection argument of the right-side proposal (risk 1). An event at 1 % per dispatch shows up in 300 dispatches
  with 95 % probability (0.99^300 = 5 %).
- A retired cell stays in the archive and stays eligible for breadth, so it is not lost.
- A unit (set or order) with only retired cells leaves the exploitation rotation, and a level with only retired cells leaves the level
  draw.
- **A faster representative starts over** (gap B, owner 2026-11-12). When a faster arrival replaces a cell's representative, the cell's
  dispatch count and its kept-a-deeper-cell status restart from zero, and a retired cell becomes active again. It is a new trajectory.
  Run 3 does the same: it resets the staleness and the anchor status on replacement, and its own (unused) retire rule counts `fresh`,
  the dispatches since the representative was set.
- **A retired cell can come back** (gap C, owner 2026-11-12). It still gets breadth dispatches. If one of them keeps a deeper cell, the
  cell is active again and, like any cell one of whose dispatches kept a deeper cell, never retires.
- **A dispatch from a replaced representative counts for neither** (gap G3, owner 2026-11-12). With several dispatches in flight, a
  dispatch can be selected from a cell whose representative a faster arrival replaces before the dispatch is ingested. It counts toward
  neither representative's 300, and what it kept protects neither: the old trajectory is gone, and the new one starts at its
  replacement. Run 3 skips the anchor update in the same case.
- **A clear inside the line counts as a deeper cell** (gap G4, owner 2026-11-12). The archive keeps no level-10 cell (a clear is the
  DEEP verdict), so a dispatch whose clear has a completion input tick ≤ line(10) = 600 counts as keeping a deeper cell. Without it, a
  level-9 cell whose dispatches clear inside the line would still retire.
- The zero-break demotion is not used in D: `demote_min_dispatches` is unreachable at these sizes (section 12, D-Q4).

### 3.4 Reused from run 3, and what is new

| part | source | in D |
| --- | --- | --- |
| cells, key, replacement, group moves, end records, fused first dispatch, D4 scheduling, worker pool, mismatch limit, caps, readiness | `run3_search`, `run3_worker`, `rl/m8_rd_cells`, `rl/frs_archive` | unchanged, imported |
| niche derivation | `run3_select.seed_niche` / `child_niche` | unchanged; one root with mask 1023 |
| cell draw inside a group (rank draw, anchors, staleness) | `run3_select.Run3Selector` | unchanged, called per order |
| breadth (count-based) | `run3_select` | unchanged |
| level draw | `level_weights` | **replaced**: 0.4 / 0.3 / 0.2 / 0.1 by rank among the levels present (gap D) |
| group shares (rate window, floor, demotion) | `run3_select` | **replaced** by least-count set, then order |
| E7 bound (best − 25) as the keep / eligible rule | `crossing_search` | **replaced** by the pace rule (section 4) |
| claims, verification twice from tick 0, text replay, exports | `crossing_search_run3`, `run3_export`, `rl/frs_verify` | unchanged; claim threshold = the frontier's best at the plan |
| anomaly detectors (live, recorded) | `run3_anomaly`, `run3_worker` | on; trigger draws off |
| start | runs 1 + 2 merged, inheritance chain | **replaced** by the tick-0 root (section 5) |
| new | | pace rule; set/order budget; retirement; milestones and verified arrivals; D's hourly tables; D's contract, manifest and folder name |

### 3.5 Gaps settled during the build (owner, 2026-11-12)

Phase 1 found eleven places where the decided text was ambiguous or contradicted itself (A to F, then G1 to G5). The owner accepted the
recommended answer to each. Every one is written into the rule it belongs to, and the tests (section 9) check it.

| gap | question | answer | where |
| --- | --- | --- | --- |
| A | Tie-breaks by mask value and niche label favour low-numbered targets, against U12 | the earliest active cell's tick, then its cell id | 3.1 |
| B | Does a faster representative restart the retirement count and status? | yes, both; a retired cell becomes active again | 3.3 |
| C | Does a retired cell whose breadth dispatch keeps a deeper cell return to exploitation? | yes, and it never retires | 3.3 |
| D | Level weights when a level in between has no active cell | by rank among the levels present | 3.1 |
| E | A same-tick double break skips a level (5 to 7): how is a milestone met? | M_L is met by the first kept arrival with at least L targets broken at a tick ≤ line(L) | 7.3, 8 |
| F | Newcomer start | the minimum over the siblings in the rotation; a unit whose cells all retired returns like one that lost its eligible cells | 3.1 |
| G1 | With no sibling in the rotation, F's "0" let a returner come back far above a newcomer (within 1 broken, a catch-up burst) | the joiner starts at max(its count, the highest count any sibling ever had); counts in the rotation then stay within 1 at all times | 3.1 |
| G2 | An exploitation draw finds no active cell while retired cells remain eligible | fall back to a breadth draw, recorded as a fallback | 3.1 |
| G3 | A dispatch ingested after its cell got a faster representative | it counts for neither representative | 3.3 |
| G4 | A clear is not a kept cell, so it did not protect a level-9 cell from retirement | a clear at or before line(10) = 600 counts as keeping a deeper cell | 3.3 |
| G5 | Two breaks on one tick are ordered by target label (run 3's rule), against U12 | kept for the pilot; U12 assumes no same-tick breaks; the pilot counts same-tick breaks per level, report-only, to decide with data | 2, 7.2 |

## 4. The pace rule: 48·L + 120

### 4.1 The rule

A reach at level L with input tick t is **kept** (as a new cell or a faster representative) and its cell is **eligible** only if

    t <= line(L) = (G × L) // 10 + s,    G = 480, s = 120, L = 0 ... 10   (integer arithmetic)

| L | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 (clear) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| line(L) | 120 | 168 | 216 | 264 | 312 | 360 | **408** | 456 | 504 | 552 | 600 |
| fastest on record | 0 | 26 | 78 | 120 | 184 | 280 | 461 | 493 | 803 | 869 | 929 |
| record − line | | −142 | −138 | −144 | −128 | −80 | +53 | +37 | +299 | +317 | +329 |

**Claims are separate from the pace rule.** A clear is claimed whenever it is faster than the frontier's best at the plan (929 tonight),
at any tick. Keeping stops at 600 and claims do not. A clear between 601 and 904 is still worth handing to the frontier (section 6.4).

### 4.2 Why G = 480 and a straight line

- **G** is the owner's goal. `STATE_MACHINE_CANDIDATES.md` s4: a time shown under 8 s needs `time_passed <= 479`, that is
  `completion_input_tick <= 480`. G is a parameter. It comes from no record and no route.
- **Linear in L** means every target is given the same time, 48 ticks. Any other profile (front-loaded, back-loaded, or a backward rule
  from observed transitions) states which part of the route is fast or slow, and that is a route belief. The backward rule considered in
  the right-side proposal (Q4 there) reads its transitions from the current order's records (the 279-tick crossing), so it would bring
  that order's shape into D. A straight line is the only per-level pace with no such content.
- **Per level, not per tick.** The rule says how many targets a state must have broken by its tick. That is the same as "at tick t,
  at least `ceil((t − s) × 10 / G)` targets", so the archive holds no state that is behind the goal by more than s.

### 4.3 Why s = 120

A slack too small prunes orders that start slower and finish faster. A slack too large lets the current order back in, and its states
then take the deepest-first budget. Both bounds can be read from the records (descriptive, used only to choose a constant):

- **Lower bound, s ≥ 40.** The fastest level-5 arrival on record is 280 (line 240). A slack under 40 would prune the only level-5 states
  known to exist, and D would have to beat the history at level 5 before keeping anything there.
- **Upper bound, s ≤ 156.**
  - The current order's fastest level-7 arrival is 493, and 336 + 157 = 493. Its fastest level-6 arrival is 461, and 288 + 173 = 461.
  - At s ≥ 157, the current order's level-7 states become eligible. Under deepest-first weights they would take the deepest level's 0.4,
    which is the absorption the right-side proposal warned about.
  - It would also make M1 / M2 meaningless: they would be met by states that already exist.
- **Inside the window, 120:**
  - One segment of slack. The CONT explorer plays 120-word segments, so a lineage can fall one full unproductive segment behind the
    line and still be kept.
  - 2.5 targets' worth of pace.
  - 37 ticks under the level-7 bound and 53 under the level-6 one.
  - At levels 1 to 4 it leaves 128 to 144 ticks of room under the records. An order whose first targets are slower than the history's
    is not pruned early.
- **What the records keep at each slack** (addendum 2's census, frontier search states / order prefixes within the line):

  | level | +60 | +120 |
  | --- | --- | --- |
  | 3 | 70 / 9 | 139 / 12 |
  | 4 | 13 / 4 | 132 / 11 |
  | 5 | 31 (one mask) / 1 | 65 / 1 |
  | 6 | 0 | 0 |

  At +60, level 5 is one mask and one order. At +120, it is twice the states.

The slack fixes the gate (M1 = line(6) = 408). Changing s therefore changes the success criterion and is the owner's decision, never
automatic (section 8).

### 4.4 Consequences

- **Archive cap.** No cell past tick 600. Level-0 cells exist only up to tick 120. Growth is bounded by the pace, not only by `max_cells`.
- **Shorter bursts.** F3's continuation trigger (`rl/frs_archive`: continue a burst when its last segment reached a new key or a faster
  arrival) is read with the pace filter. A reach that would not be kept does not trigger a continuation, so bursts that have fallen behind
  stop at the next segment boundary.
- **Cheaper prefixes.** Every prefix is at most 600 ticks, against 700 to 930 in tonight's frontier archive. Prefix replay was 92 % of
  the ticks in the frontier search (`docs/frs_prefix_cost_2026-10-14.md`). The smoke measures D's dispatch rate.

### 4.5 What the pace rule does not do

- It does not rank cells. Ranking stays run 3's rank draw inside an order.
- It reads no record value. G and s are constants in Params.
- It is not the E7 bound. D has no bound tied to the frontier's best except the claim threshold.

## 5. Roots and seeds

### 5.1 One root: the tick-0 state

- **Root:** level 0, mask 1023, niche `(1023, ())`, empty prefix, resource class as read.
- **Open:**
  1. Two fresh processes each reach tick 0 with no input word played.
  2. Their end records (the 16 compared fields), cell keys and chain digests must be equal. This is run 3's tick-0 inequality check
     applied to the root.
  3. The root's end record is stored as any cell's is.
  4. Every later dispatch is, as always, a fresh process from tick 0 (process restart resets the episode), so nothing else is needed.
- **Why one root.** The order is discovered from the first input. With a single root the order niche is the complete order, which is
  what the budget unit counts.

### 5.2 No seeds from earlier archives (recommended)

The frontier archive, runs 1 / 2, the frontier search and the M8 import are the agent's own records, not human ones. But they carry the
history's concentration: 10 of the 120 first-five permutations were ever played, and 2 of them carry 97.9 % (route insight s0).
Seeding D with their level 1 to 5 states would start D with deep cells in exactly those orders. The least-count budget would treat them
equally, but they would hold the deepest levels from minute one and take the 0.4.

The pilot starts from tick 0 alone. D reads no earlier record of any kind except the frontier's best verified clear, as the claim
threshold (section 12: D-Q6 decided; the census report was dropped under D-Q1).

### 5.3 The search's random seeds

- **Selection.** Run 3's `det_schedule.KeyedRandom`, seeded by `--rng-seed`. The pilot uses a value no frontier night used: 11
  (D-Q7), recorded in config.json.
- **Bursts.** The CONT explorer's keyed stream, keyed by D's archive id, the key family and the cell's prefix digest, as run 3 does
  (`<archive id>|order1|<prefix digest>`, iteration 0, 1, ...). D's archive id differs from every run 3 archive, so no frontier burst is
  repeated.
- **Native RNG** is never read, logged or compared. No RNG seed is implemented, validated or compared (CLAUDE.md).

## 6. Coexistence with the frontier archive

### 6.1 Separation

| | frontier arm (run 3) | D |
| --- | --- | --- |
| folder | `crossing_<date>_run3*` | `order_<date>` (new prefix) |
| contract | `frs_crossing_search_run3_v1` | `frs_order_search_v1` (new) |
| code digest | run 3 manifest `73cbde95` | D's own manifest (import closure of D's entry modules), enforced at its open |
| inheritance | its own linear chain (`--inherit`) | none in the pilot; a later D night inherits D folders only |
| refusals | `run3_load` reads only its own contract, so a D folder is refused | D refuses run 3 folders as inheritance |
| lab lock | one night at a time | the same lock, so D and the frontier never run together |

### 6.2 What each reads from the other

- **D reads from the frontier:** the latest verified best of the frontier chain (completion tick, chain digest and source), read only at
  D's plan. It is the claim threshold (verify a claim faster than it) and the reference for the "faster than the frontier's bound"
  readout. Nothing else: no cell, no niche, no rate.
- **The frontier reads from D:** nothing, until a hand-off (6.4).

### 6.3 Building D while frontier nights continue

The run 3 manifest is the import closure of run 3's entry modules (`run3_manifest.RUN3_MODULES`), computed in a fresh interpreter. New
files that run 3 does not import do not change its digest. D is therefore built as new files that import run 3 modules unchanged:
- `tools/frs/order_search.py` (plan / run);
- `tools/frs/order_select.py` (pace rule, set/order budget, retirement, milestones);
- `tools/frs/order_search_tests.py`.

A test checks that the run 3 digest still equals `73cbde95` after D's files land (T-M1).

**Line endings (owner, 2026-11-12).** The run 3 manifest hashes the files' bytes as they are on disk. In the main tree, 7 of its `rl/` files
are CRLF on disk while the index holds LF. That gives `73cbde95`. A fresh checkout or a worktree has the same files with LF, which gives
`11ec3040` for the same content. T-M1 accepts exactly these two digests. The main tree is never switched to another branch, and its files
are never checked out again, since a rewrite would change the frontier's digest to `11ec3040`. D is built in a worktree. D's own manifest
(T-M2) normalises line endings to LF before hashing, from the start, so the checkout cannot change D's digest.

If D ever needs a change inside a run 3 manifest file, for example a hook in `run3_search` for a root with an empty prefix:
- it happens between nights;
- it is its own commit with the full run 3 suites and a frontier smoke run;
- the owner is told first, because the frontier digest changes.

Adapters and subclasses come first.

### 6.4 Hand-off from D to the frontier (built only after M1)

Two loader steps on the frontier side. Both change run 3 manifest files, so each is built between nights with its own tests:
- **Best:** a D verified clear faster than the frontier's best becomes the frontier's E7 best through a `--best-from` path accepting D
  folders (it needs a clean run, a text replay of the clear, and the export round trip, as run 3 requires of its own folders).
- **Cells:** D's lineages at level 6 or deeper whose ticks are inside the frontier's bound become frontier roots through a
  `--seeds-from` step. Their prefixes are re-derived from D's rows and replayed at the open, as run 1 did with its seeds. They start new
  groups, with the order niche taken from D's order.

Each hand-off is a plan the owner approves before a night. Nothing passes live.

### 6.5 Shared, unchanged

- The pinned executable and frozen runtime.
- The lab guard: writes only under D's folder; refuses the checkout, `runs/` and the D: evidence roots.
- Readiness thresholds (free commit 10,240 MB, available 4,096 MB, 5 GiB disk), never lowered.
- Verification: twice from tick 0 with the verify flags.
- Text replay of new bests, and exports (`.btt.txt`, `.bk2`).
- The replay lab viewer (add D's folder to `sources.json`).
- The backups: D's folders join the lab backup.

## 7. Pilot night protocol (frontier paused)

### 7.1 Before the night

1. **Build complete, tests green:**
   - D's unit, fake-game e2e and zero-tick real-lab tests (section 9);
   - the four run 3 suites unchanged (33 / 13 / 2 / 10);
   - the run 3 digest still `73cbde95`;
   - `git diff --check` clean.
2. **The plan (zero ticks), printed and saved in plan.json:**
   - the root;
   - the pace table (line per level);
   - the parameters;
   - the frontier reference read (the claim threshold).

   The census of earlier records (what they would keep at each slack) was dropped: see section 12, D-Q1.
3. **Smoke** (owner's go): 3 workers, 25 minutes, `--rng-seed 1`, into `order_<date>_smoke`.
   - Pass criteria:
     - 0 prefix mismatches and 0 tick-0 inequalities (the root included);
     - digests unchanged at the close;
     - no game process left;
     - every end record fused;
     - the set/order counts equal within 1 per unit at every level in the level draw (exploitation draws, checked from the dispatch
       rows).
   - Measured:
     - dispatches per hour;
     - new cells per dispatch;
     - main and tree memory per 1,000 cells;
     - the deepest level reached and its earliest tick.
   - **Projection:** cells and memory at 8 hours. If it exceeds the 2,560 MB soft budget, `max_cells` is set so the night stops cleanly
     at 80 % of it. If even that would end the night before 6 hours, the night is not launched, and the owner decides.
4. **Readiness** just before the launch. A refusal is reported with what is missing.
5. **The owner's go**, and the session log section committed before the launch.

### 7.2 The night

- **Command shape:** `order_search.py plan` then `run --workers 5 --max-wall-min 480 --rng-seed 11 --summary-every-s 3600`, into
  `C:/BattleShip_lab/order_<date>`. The tick cap is as the frontier's (80 M).
- **The frontier is paused:** no frontier night that night. Its chain is untouched, and the next frontier night inherits exactly as
  before. D's folder is never in its chain.
- **Hourly record** (`hourly.jsonl` / `hourly.md`). Per level:
  - cells, eligible cells and retired cells;
  - the number of sets and orders with an eligible cell;
  - dispatches;
  - the earliest arrival against the line (lead or lag);
  - the largest and smallest set and order budget counts, as the equality check;
  - **reaches rejected by the line** (owner, 2026-11-12): their count, and the earliest rejected tick with its distance over line(L).
    The same two numbers for the whole night go in `summary.json`, per level. Report-only: no rule reads them. Rejected reaches do not
    extend their bursts (section 4.4), so these numbers show how close D came to the line, not how far a looser line would have gone.
    After a null night they tell whether the line pruned too hard (for example, level 6 earliest rejected at 415, +7) or was not what
    stopped D (+182).

  - **same-tick breaks** (gap G5, owner 2026-11-12): the number of burst ticks on which two or more targets broke, counted at the level
    the lineage reached on that tick, with the number of targets broken; also for the night in `summary.json`. Report-only: they show how
    often the label tie of section 2 decided an order.

  Also:
  - milestones with their time, dispatch, cell and lineage digest;
  - memory and the dispatch rate;
  - claims and verifications;
  - for the owner only, the first-break and set tables (descriptive; nothing reads them).
- **Flags** (reported, never acted on automatically):
  - the deepest eligible level has not grown in 2 hours;
  - a set's or order's budget count (exploitation draws) is off the minimum by more than 1 at a level in the level draw, which would be
    a bug;
  - breadth outside 0.18 to 0.22 of the hour;
  - memory above 80 % of the soft budget.
- **Stop rules, as run 3:**
  - mismatch limit 3, giving SEARCH_INVALID;
  - a soft memory breach, giving a clean stop;
  - `max_cells`, the tick cap and the wall cap;
  - **no early stop at M1** (D-Q7): the night runs to its caps, so the remaining hours give the M2 to M4 data. M1 is verified at the
    close (D-Q8).

### 7.3 After the close

- **Integrity, as run 3:**
  - status and exit code;
  - prefix mismatches and tick-0 inequalities;
  - digests unchanged;
  - no game process left;
  - end records;
  - claims and verification results.
- **Verified arrivals.** For every milestone, M1 to M4, the prefix up to the arrival is replayed twice from tick 0 in fresh processes
  with the verify flags. It counts only if both replays show at least L targets broken by the recorded tick (gap E: a same-tick double
  break can skip level L), with chain digests equal to D's record. This is the "verified arrival" standard of rd2's wall-top landing. Only the first qualifying arrival per milestone is
  verified. A disagreeing replay is an integrity finding, and the night is then not a test of M1 (section 7.4); there is no fallback
  to a later arrival (section 12, D-Q8).
- **Standalone verification: deferred** (owner, 2026-11-12). `run/cells.jsonl` keeps every kept cell at ingest (level, tick, inputs,
  chain), so a night that dies before its close loses no data. A standalone `verify-milestones` command (reading only the folder's
  plan and cell rows, calling the close's verification step; native, the owner's go) is built only if that ever happens.
- **Exports.** A text replay (`.btt.txt`) of each verified milestone prefix, so the owner can watch it in the replay lab.
- **Records.** The per-level table at start against end, the memory peak, and a backup of the folder (Python sums against
  `Get-FileHash`, as the 2026-10-16 backup).
- **Report.** A section of the session log, with the decision table below filled in, and nothing launched after it.

### 7.4 Decision after the pilot

| outcome | reading | next (owner's go each time) |
| --- | --- | --- |
| M1 verified | the 48-per-target pace plus slack is reachable at level 6 by D's own budget | a second D night (new rng seed, same parameters; the budget then presses levels 7 and 8), and the hand-off loader built between nights |
| M1 not met, night complete (≥ 6 h of dispatching, no integrity stop) | the random-burst budget under this pace does not reach level 6 at 408 | **stop D and review**; no automatic change of s, G or the weights |
| night incomplete (integrity or memory stop before 6 h, or a milestone replay that disagrees) | not a test of M1 | fix the cause; the pilot is rerun |
| a verified clear faster than the frontier's bound (with or without M1) | a new best for the frontier | hand-off of the best (6.4) before the next frontier night |

## 8. Success criteria

- **Gate, M1:** a verified level-6 arrival at or before **408** (line(6) = 48 × 6 + 120), in any target set and any order, made by D's
  own search from the tick-0 root in the pilot night. Verified means both replays agree (7.3). A claim or an in-run reading alone does
  not count.
- **Reported, not gates:**
  - M2: a level-7 arrival at or before 456;
  - M3: a level-8 arrival at or before 504;
  - M4: a level-9 arrival at or before 552;
  - a clear at or before 600 (a 10.0 s clock);
  - any verified clear faster than the frontier's bound (904 tonight; best − 24 − 1).

  Each is verified as M1 when met.
- **A skipped level (gap E, owner 2026-11-12).** Two targets broken on the same tick take a lineage from level 5 straight to level 7, with
  no level-6 cell. M_L is therefore met by the first kept arrival with **at least** L targets broken at a tick ≤ line(L): a level-7
  arrival at 400 meets M1 (400 ≤ 408) as well as M2.
- **Diversity readouts, for the owner, never gates or inputs:**
  - the number of sets and orders with a cell inside the line at each level;
  - how many different targets were broken first.

  They describe what D found and steer nothing.
- **Failure:** a complete pilot night without M1. D stops and is reviewed. Any change of slack, goal, weights or roots is a new proposal,
  because s fixes the gate itself.

## 9. Tests

All zero native ticks unless marked native. D's tests live in `tools/frs/order_search_tests.py`, in the run 3 suite's style (`unit_`,
`real_`, `e2e_`).

**Unit (pure, no process):**

- **U1 pace line:**
  - `line(L) = (G × L) // 10 + s` for L = 0 to 10 at G = 480, s = 120: 120 / 168 / ... / 600;
  - a reach at exactly line(L) is kept, and at line(L) + 1 it is not;
  - G and s are parameters;
  - G ≤ 0, s < 0 and a non-integer are refused.
- **U2 keep rule:**
  - a behind-pace reach is neither kept nor counted as new for F3;
  - a reach at line(L) + 1 is counted as rejected at level L with distance +1, the earliest rejected tick per level is the minimum
    over the rejected reaches, and the counts enter no rule;
  - a faster arrival at a known key replaces the representative, and the group moves when its order differs;
  - a clear past 600 is still claimed when it is faster than the reference.
- **U3 root and niches:**
  - the root's niche is `(1023, ())`;
  - a child's niche is the full order;
  - a two-target burst is ordered by (break tick, target label);
  - group key = (L, mask, order);
  - with one root, the order determines the mask;
  - same-tick breaks are counted per level reached, with the number of targets, and the count enters no rule (gap G5).
- **U4 set then order:**
  - least budget count at each stage;
  - ties by the earliest active cell's tick, then that cell's id, never by mask or label (gap A);
  - counts are exploitation draws only: a breadth draw changes no set or order count;
  - over 10,000 simulated draws (breadth included) on a fixed archive, at every level in the level draw, every set's count and every
    order's count within its set differ by at most 1; a level outside the level draw is not checked;
  - a set with one order and a set with ten orders get equal set counts.
- **U5 newcomers:**
  - a set or order created mid-run joins at its siblings' minimum, the siblings being the units in the rotation (gap F);
  - with no sibling in the rotation, it starts at the highest count any sibling ever had, and at 0 when there never was one (gap G1);
  - a unit that loses its last eligible cell leaves and keeps its count, and returning resumes at max(count, minimum);
  - a unit whose cells all retired returns the same way (gap F);
  - a level that empties and refills: a newcomer starts at the returner's level of count, counts stay within 1, and there is no
    catch-up burst (gap G1).
- **U6 level weights:**
  - 0.4 / 0.3 / 0.2 / 0.1 over the four deepest levels with an active cell;
  - renormalised when there are fewer;
  - a level with only retired cells is skipped;
  - by rank among the levels present: with active cells at levels 7, 5, 4 and 2 only, 7 / 5 / 4 / 2 get 0.4 / 0.3 / 0.2 / 0.1 (gap D).
- **U7 retirement:**
  - a cell retires after exactly R = 300 dispatches none of which kept a cell (new, or a faster representative) at a deeper level, not
    at 299;
  - a cell any of whose dispatches kept a deeper cell never retires;
  - a cell whose only break is behind the line (nothing kept) retires at exactly 300;
  - a retired cell stays in the archive and in breadth;
  - a unit with only retired cells leaves the rotation;
  - a faster representative restarts the count and the status, and a retired cell becomes active again (gap B);
  - a retired cell whose breadth dispatch keeps a deeper cell is active again and never retires (gap C);
  - a dispatch ingested after its cell got a faster representative counts for neither, even when it kept a deeper cell (gap G3);
  - a level-9 cell whose dispatches clear at or before 600 never retires; a clear at 601 does not protect it (gap G4);
  - with every eligible cell retired, an exploitation draw falls back to a breadth draw, recorded as a fallback (gap G2).
- **U8 milestones:**
  - M1 at a level-6 arrival of 408, not at 409;
  - M2 to M4 and the clear line likewise;
  - in any mask;
  - a skipped level: a level-7 arrival at 400, with no level-6 cell, meets M1 and M2 (gap E);
  - recorded once, at the first occurrence, with dispatch, cell and lineage digest.
- **U9 claims:** the threshold is the frontier's best read at the plan, and a claim faster than it is queued for verification as run 3.
- **U10 parameters:**
  - defaults;
  - refusals (weights not summing to 1, R < 1, a breadth share outside [0, 1]);
  - the config fingerprint;
  - `run` refuses flags that differ from the saved plan, as run 3 does.
- **U11 isolation:**
  - `run3_load` refuses a D folder (contract);
  - D refuses a run 3 folder as inheritance, refuses to plan into a folder holding a run 3 plan, and writes only under its own folder
    through the guard.
- **U12 relabelling invariance:**
  - on a fake archive and a fake burst oracle whose target labels are permuted by a fixed permutation, the selection sequence is the same
    with the labels permuted;
  - the fake game breaks at most one target per tick: U12 assumes no same-tick breaks, the one case where run 3's label tie decides an
    order (gap G5);
  - counts, ranks and milestones are equal;
  - this is the test that no rule prefers a target.
- **U13 no human input:** the plan's source list holds only D's own folder and the frontier's best record. No file under the scripted
  baseline's or the M1e fixtures' paths is opened (checked by an open-hook in the test).

**Manifest:**

- **T-M1:** the run 3 manifest digest is still `73cbde95` (the main tree's working copy) or `11ec3040` (the same 54 files with LF, as in a
  fresh checkout or a worktree), with D's files present. Any other value fails (section 6.3).
- **T-M2:**
  - D's manifest covers D's import closure;
  - it hashes each file with its line endings normalised to LF, so the same content gives the same digest in any checkout;
  - D's open refuses a missing or different digest;
  - a change during the run is SEARCH_INVALID at the close.

**Fake-game end-to-end** (run 3's fake game, zero native ticks):

- **E1 same seed:** two runs with the same seed give identical dispatch rows, cells, hourly records and milestones (D4 under the reorder
  window).
- **E2 tick-0 open:** the root is read twice and equal; an injected inequality refuses the open.
- **E3 pace and budget:**
  - a fake game with fast and slow orders;
  - behind-pace reaches are never kept;
  - every set with an eligible cell is drawn, and counts stay equal within 1 at every level in the level draw;
  - the slow orders leave the rotation when their cells fall behind;
  - every dispatch row's stream is an exploitation stream (rank or anchor) or breadth: no trigger stream (D-Q5).
- **E4 milestone:**
  - a fake level-6 arrival at 408 triggers M1;
  - its verified-arrival replay runs twice;
  - a replay that disagrees leaves M1 unverified and is reported.
- **E5 caps and stops:**
  - `max_cells` and a soft memory breach give a clean stop;
  - 3 mismatches give SEARCH_INVALID;
  - no game process is left.
- **E6 exports:** a fake verified clear gives a `.btt.txt` and a `.bk2` with the round trip, and a milestone prefix export.

**Real lab, zero ticks:**

- **R1 census: dropped** (section 12, D-Q1).
- **R2 run 3 untouched:** the four run 3 suites pass unchanged.

**Native (each with the owner's go):** the smoke run (7.1 step 3), then the pilot (7.2).

## 10. Build plan and cost (about 3 days)

Each phase is verified before the next (CLAUDE.md: one independently verifiable milestone at a time).

| phase | content | verified by |
| --- | --- | --- |
| 1 (about 1 day) | `order_select.py`: pace rule, set/order least-count budget, newcomers, level weights, retirement, milestones; built on `run3_select` without editing it | U1 to U10, U12, T-M1 |
| 2 (1 to 1.5 days) | `order_search.py`: plan (tick-0 root, reference read) and run (open with the root check, F3 with the pace filter, records, hourly tables, verified arrivals, exports); D's manifest | U11, U13, T-M2, E1 to E6, R2 |
| 3 (half a day) | the session log section, `docs/` record of the design as built, smoke run (owner's go) and its report | 7.1 criteria |

The hand-off loader steps (6.4) are not in this build. They are designed and built only after a verified M1.

## 11. Risks

- **The crossing for a new set.** Any set that is faster to level 6 still has to reach the remaining targets. D's deepest-first weights
  and M2 / M3 measure that in the same night. The pilot's gate is level 6 only.
- **Thin budgets.** If the number of sets and orders explodes at middle levels, per-order budgets fall to a few dispatches. The hourly
  equality and per-level tables show it. Retirement and the pace keep the rotation to live units.
- **Slack.** Too tight prunes slow-start orders, and too loose lets the current order back in. Section 4.3 fixes the window. Any change
  is the owner's.
- **Archive growth from tick 0.** The early game is new territory for the archive, and the new-cell rate is unknown until the smoke.
  The pace caps it (nothing past 600), and the projection sets `max_cells`.
- **A null pilot is informative but not final.** It shows that this budget under this pace does not reach 408 in one night. It does not
  show that no order can. The review decides.
- **Nothing in the records shows that any order fits 480.** D is the measurement.

## 12. Open questions for the owner

1. **Slack:** (a) s = 120 (recommended, section 4.3); (b) 90; (c) 150.
   **Decided 2026-11-12 (owner): (a), s = 120**: pace line 48·L + 120, gate M1 = 408. Rationale: one 120-input explorer segment of
   slack, with a gate 53 ticks faster than any level-6 arrival on record. **Also decided: the census is dropped from D** (section 7.1
   step 2, the section 5.2 mention, test R1), because it reads earlier archives, which D-Q6 excludes, and addendum 2's offline numbers
   already justify s.
2. **Level weights:** (a) 0.4 / 0.3 / 0.2 / 0.1 over the four deepest eligible levels (recommended); (b) flat over all eligible levels;
   (c) another list.
   **Decided 2026-11-12 (owner): (a)**, 0.4 / 0.3 / 0.2 / 0.1 deepest first over the four deepest levels with an eligible, non-retired
   cell, renormalised when fewer exist. It does not touch the gate (M1 depends on s only), so it can be revisited after the pilot from
   the hourly per-level readout. Run 3's 0.20 / 0.35 / 0.35 / 0.10 was excluded: it was chosen from where the incumbent route's
   archive yielded most (session log §19.3).
3. **Equality mechanism:** (a) deterministic least-count for sets and orders (recommended); (b) keyed uniform draws.
   **Decided 2026-11-12 (owner): (a)**, deterministic least-count, set then order, with budgets counting exploitation draws only;
   breadth is a separate, set-blind stream on top. "Within 1" and the hourly bug flag apply only to the levels currently in the level
   draw; U4 is updated. How it stops an early-deep order from extending its lead: while it is alone at a level it takes that level's
   whole share (nothing else is there); the moment a second set reaches the level it joins at the leader's count, and least-count then
   alternates between them, so the head start is not paid back but is not extended by a single draw. Set before order means a set with
   ten orders gets no more than a set with one.
4. **Dead ends:** (a) per-cell retirement at R = 300 (recommended); (b) run 3's zero-break demotion per order; (c) neither.
   **Decided 2026-11-12 (owner): (a), with one condition:** a cell retires after 300 dispatches none of which kept a cell (new, or a
   faster representative) at a deeper level. Retired cells stay in the archive and in breadth; a set, order or level with only retired
   cells leaves the exploitation rotation. U7 is updated to the single condition, with the case "only break is behind the line ->
   retires at exactly 300". R does not touch the gate, so it can be revisited after the pilot from the hourly per-level readout.
5. **Breadth and triggers:** (a) breadth 0.2 as run 3, anomaly detectors on and recorded, trigger draws off (recommended, "detect without
   steering"); (b) triggers on as run 3; (c) breadth off.
   **Decided 2026-11-12 (owner): (a).** Breadth 0.2, count-based as run 3, over in-pace cells including retired ones; the anomaly
   detectors on and recorded; no trigger draws in D's selector (E3 asserts it). 0.2 is a generic default (run 3 validated it on the
   incumbent route's archive, DECISIVE 4), so it can be revisited after the pilot; it does not touch the gate. Checked on night 3: every
   burst with a detector event is logged in `anomaly_bursts.jsonl` with its full inputs from tick 0, its parent cell and draw id,
   whatever the archive keeps (21,314 rows = the summary's 21,314 bursts with events; every row's length = start tick + burst). D reuses
   `run3_anomaly` unchanged, so an anomaly in a lineage the line rejects stays replayable; no addition needed.
6. **Roots:** (a) the tick-0 root only (recommended); (b) also the records' level 1 to 5 states inside the line (agent-made, but they
   carry the history's order concentration).
   **Decided 2026-11-12 (owner): (a), the tick-0 root only.** D reads nothing from earlier archives except the frontier's best verified
   clear, as the claim threshold. Rationale: earlier archives carry the history's order concentration, so seeding from them would
   hand D the incumbent orders instead of letting it discover its own.
7. **Pilot:** 5 workers, 480 minutes, a new rng seed, M1 as the only gate. Confirm, or set another length.
   **Decided 2026-11-12 (owner): (a), as designed.** A smoke first (3 workers, 25 minutes, `--rng-seed 1`), then one pilot night
   (5 workers, 480 minutes, the 80 M tick cap, `--rng-seed 11`, the frontier paused), M1 the only gate, **no early stop at M1**.
   `max_cells` is set from the smoke's memory projection; if that would end the night before 6 hours, the night is not launched and the
   owner decides. Whether to run a second night is decided at the review, from the pilot's data.
8. **Verified arrival:** both replays show the break at the recorded tick with equal chain digests (recommended). Or stricter: also the
   full end record at the arrival.
   **Decided 2026-11-12 (owner): (a).** Two fresh-process replays from tick 0 with the verify flags; both show the level-L break at the
   recorded tick and give a chain digest equal to D's record. Only the first qualifying arrival per milestone, at the close. A mismatch
   is an integrity finding and the night is "not a test of M1"; no fallback to the next arrival for now. Rationale: the per-tick chain
   already covers the 16 compared end-record fields, so (b) adds nothing; an in-run reading alone is not enough for a gate.
   **Refinement, confirmed by the owner 2026-11-12 (phase 2 build):** a mismatch gives the night the status SEARCH_INVALID. That
   means "not a test of M1", as above, and one thing more: SEARCH_INVALID is not a clean status, so any later use of the folder (a
   later D night reading it, or the hand-off of D-Q9) needs the owner's explicit acceptance naming it, as run 3's `--accept-run` does.
   Clears verified during the night stay claimed: a milestone mismatch does not freeze claims.
9. **Hand-off:** designed and built only after a verified M1 (recommended), or designed now.
   **Decided 2026-11-12 (owner): deferred.** The hand-off (section 6.4) is built only after a verified M1 or a verified D clear faster
   than the frontier's best; each hand-off night remains a plan the owner approves. Deferring keeps about a day and a run 3 manifest
   change out of the build, and loses no data: D's `cells.jsonl` keeps every kept cell with its inputs, chain, end record and order.
