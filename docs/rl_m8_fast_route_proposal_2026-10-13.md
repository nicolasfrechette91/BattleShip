# M8 fast-route proposal (2026-10-13)

## 1. Summary

**Status: design proposal only; zero native ticks.** No game, suite, preflight or launcher was started and nothing was prepared. No tracked
file was modified; nothing under `runs/` or on D: changed (the agent's own archive and one route trace under `runs/m8_rd_sd2/` were read).
New files: this proposal and the Git-ignored working files under `logs/m8_fast_proposal/` (`scripts/p1_checks.py`, `scripts/p2_splice.py`, their
outputs `p1_checks.json`, `p2_splice.json`; both run with `python -B`). Checkout `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, branch
`main`, HEAD = `origin/main` = `f3d2943`, clean with nothing staged at the start; `docs/rl_m8_fast_route_analysis_2026-10-13.md` is committed (last
changed in `f3d2943`).

**Read.** `docs/project_handoff.md`; `docs/rl_decisions_2026-10-13.md`; in full `docs/rl_m8_fast_route_analysis_2026-10-13.md` and
`docs/rl_m8_sd2_review_2026-10-13.md`; Areas 5, 6 and 10 of `docs/rl_generalization_audit_2026-10-13.md` (the audit's numbered `##` sections stop at
6; its findings are grouped in Areas 1 to 10, so "sections 5, 6 and 10" was read as Areas 5 (action space), 6 (route and speed discovery) and 10
(constraint check)); the module headers and the selection, explorer, cell-key, worker and ingestion code the design builds on (`rl/m8_rd_select2.py`,
`rl/m8_rd4_select.py`, `rl/m8_sd1_select.py`, `rl/m8_rd_explore.py`, `rl/m8_rd_cells.py`, `rl/m8_rd_worker.py`, `rl/m8_rd_archive.py`). Not read or
used anywhere: the TAS, every human recording, the owner's own run, any external record time. Nothing touches native RNG.

**Premise (the owner's).** Track 1 (`btt_s9_b8_v1`) is not the limit; the search is. Every speed statement in this proposal is relative to the
agent's own results only.

**Spot-checks of the analysis** (recomputed independently from `runs/m8_rd_sd2/archive/`; all match):

| figure | analysis | recomputed |
| --- | --- | --- |
| closing cells; shortest L per level 1 to 10 (section 2 and the sd2 review's 4.1) | 49,928; 26, 91, 152, 254, 433, 871, 1,237, 1,776, 1,832, 1,885 | identical |
| bursts started from level 7 and those that broke a target (section 6) | 4,734; 14 (0.3 %) | 4,734; 14 (0.30 %) |
| cumulative bursts at each session's close (section 0); bursts ending in a fall (section 6) | 2,175 / 6,212 / 10,406 / 13,886 / 17,554 / 21,323; 23.3 % | identical; 4,965 of 21,323 (23.3 %) |

**New figures the design needs** (not in the analysis; `p1_checks.json`, `p2_splice.json`):

| id | figure | value |
| --- | --- | --- |
| F1 | share of exploration ticks spent replaying the start cell's prefix (the return) | 90.3 % (rd1) rising to 93.2 to 93.7 % (rd4, sd1, sd2); over six sessions 2,320,750 of 30,064,502 ticks (7.7 %) were new exploration |
| F2 | mean return length by start level | 217, 276, 359, 550, 768, 1,028, 1,294, 1,594 (level 7), 2,003, 2,094 (level 9) ticks, each for a burst of at most 120 |
| F3 | bursts that ended by length yet were still productive in their last 20 words (a non-doomed new or replacing reach) | 5,314 of 16,338 (32.5 %); 27 % at level 7, 49 % at level 8 |
| F4 | position of a burst's first target break inside the burst | median word 20 to 60 by start level; 14 to 50 % after word 60 (level 7: 7 of 14) |
| F5 | splice candidates on the 1,885 route: cells the route passes through whose archive representative arrived earlier than the route did | 198 of the route's 310 cells; 143 earlier by >= 30 ticks, all at levels 2 to 7 (level 4: 39 of 40 cells earlier, median gain 362, maximum 487 ticks; level 6: 53 of 60 earlier, median 112, 40 by >= 30; level 7: 26 of 75 earlier, 16 by >= 30, maximum 209); at levels 8 to 10 at most 3 ticks. 14 of the 143 have a near-identical motion state (each velocity component within 10, same facing, jumps used and status); position inside the 300-unit bin, projectiles and the phase of moving objects were not compared |

**Diagnosis in one paragraph (section 2).** The M8 design is an end optimiser. It improves a route where three things coincide: the selection
puts its mass there (the harmonic level weight sends half of it to the two deepest levels), an improvement fits in one or two bursts (the left-side
legs are 53 to 81 ticks), and no low-rate transition separates the improved segment from the clear. The first 90 % of the route meets none of the
three. Its levels get 3 to 11 % of the mass each. A faster arrival there counts only if every later segment is re-solved from the new state,
including the crossing (0.3 % of bursts from level 7 break a target) and two segments around moving objects. The archive has no operator that tries
the known continuation from a faster state (F5: 143 such states exist at levels 2 to 7). The count term and the mask-agnostic length factor starve the
ahead fronts that do exist. And the search was short: six sessions explored about 30 M ticks (about five hours), 92 % of them prefix replays.

**Recommendation (sections 3 and 4).** Option B, **pace-frontier search (PFS)**, built as one generic, task-parameterised module family and run
first in **lab mode** on a copy of the agent's own archive. PFS values pace at every (level, mask) and funds fronts ahead of the agent's own best
clear, using a bottleneck budget measured online. It counts dispatches since a cell's last shortening, continues productive bursts in the same
process, and verifies every clear in-run by exact replay from tick 0. A one-hour splice probe decides whether a splice-and-repair operator joins
it. A fresh-from-tick-0 arm (option C) tests lock-in and is the configuration a new character needs. Motion-aware multi-arrival cells and a macro
explorer are week-3 ablations. A learned policy is deferred.

**Process (section 6).** Lab mode keeps the non-negotiables (no TAS or human data, exact replay from tick 0 of every clear claimed, exploratory
evidence kept apart) and drops the multi-day registered pipeline. It gives about 36,000 dispatches per night against about 3,700 per registered
session. Registered mode is used only to register a verified lab result.

## 2. Part 2: what in the design limits speed

### 2.1 What one dispatch is

A dispatch draws a level (weight 1 / (1 + top - level) over levels with eligible cells), then a cell. The cell weight is (1 + seen)^-1/2 x
120 / (120 + L - L_min(level)) x w_res, over cells passing E1 to E7 and X1 (`rl/m8_sd1_select.py` header). The worker starts a fresh process,
replays the representative's L words from tick 0, then plays 120 uniform words with holds of 1 to 16 (`rl/m8_rd_explore.py`). The archive ingests
the first reach of each key and replaces a cell's representative only by a strictly shorter (or less doomed) reach (`rl/m8_rd_archive.py`,
`_better`, `decide`). The return is 92 % of the ticks (F1). A dispatch costs about 2.8 s of worker wall, mostly bounded by the 3 s process start-up
when jobs are short (sd2 review 2.2). That is about 4,500 dispatches per hour (sd2: 3,769 in 50 minutes).

### 2.2 The seven findings, explained

| # | finding | what in the design produces it | evidence |
| ---: | --- | --- | --- |
| 1 | The first ~90 % of the route (rd1/rd2 bursts) was never re-optimised; all gains came after the wall top. | (a) **Mass.** The harmonic level weight and E7 put about half the mass on the two deepest levels; levels 0 to 6 hold 3.4 to 8.5 % each. (b) **Propagation.** A faster arrival before level 7 shortens the clear only if every later segment is re-solved from the new state. That includes the crossing and the two segments around moving objects (target 2 and the moving platform), now at a different phase. No operator carries the known continuation onto a faster state. (c) **The end is cheap.** The left-side legs fit in one or two bursts from deep cells that get the most mass, and replacement spreads gains into old cells. | Analysis 1 (all 430 ticks after 1,721; ticks 0 to 1,694 from rd1/rd2); sd2 review 3.3 and 4.1; F5 (143 route cells at levels 2 to 7 with arrivals >= 30 ticks earlier, up to 487, explored only by random bursts) |
| 2 | Every level-8+ trajectory descends from one root; one complete break order. | The crossing was solved once (rd2, burst 6088). Afterwards the deep levels' mass (51 % at the sd2 close) went downstream of it. Any other lineage must solve the 7-to-8 step with about 0.2 % of the mass at a 0.3 % rate per burst: the level-7 front's 17 dispatches give about 0.05 expected breaks. | Analysis 3 (5,328 of 5,328 through 1,339; 96 order prefixes, one complete); sd2 review 5.1 |
| 3 | Faster partial routes in other orders got few dispatches; their bursts mostly ran out of length. | (a) **Count term.** The ahead lineages live in old cells (as shortenings) with `seen` 16 to 52, weight 0.14 to 0.24. (b) They share one level share with about 3,500 eligible cells (level 7: 11.4 %). (c) **Burst length.** 120 words against break-to-break segments of 43 to 437 ticks at the record's pace (five of ten longer than 120). Breaks occur throughout bursts (F4), and a third of length-ended bursts were still producing at their end (F3). Each continuation needs a new dispatch costing 1,028 to 2,094 return ticks at levels 5 to 9 (F2) plus a process start. | Analysis 3 (fronts table: 479 of 496 by length; the 871 front 23 of 23); sd2 review 5.1; F2 to F4 |
| 4 | The crossing is a bottleneck (0.3 % target-break rate from level 7). | (a) The step is long (355 ticks from target 2 to the wall-top landing, three or more bursts) and passes a moving platform. (b) The 0.3 % averages over every level-7 cell, most not placed for the step, and nothing in the selection reads a cell's own transition record. (c) The length factor's reference at level 7 is the dead-end 1,237 lineage, so the crossing cells (1,694 to 1,775) get about a fifth of its per-cell weight: about 46 dispatches per session. | Analysis 6 and 7 (crossing table); sd2 review 4.2 and 4.3 |
| 5 | Faster versions of right-side segments exist in other trajectories but cannot be joined. | A route is a word sequence from tick 0, and a segment's words reproduce their effect only from the same full state. The key equates states that differ in velocity, facing, status, exact position (up to 300 units), projectiles alive and the phase of moving objects (which follows the absolute tick). The archive never attempts a join. | Analysis 7 (four of seven right-side pairs faster elsewhere by 61 to 230) and 8; F5 (143 joins exist at key level, 14 with near-identical motion). Whether any join survives cannot be determined offline. |
| 6 | The search has saturated (new cells and new orders per million ticks falling sharply). | Novelty is measured in a coarse key space (300-unit bins x class x mask x floor) that reachable states have largely covered. Dispatches moved to deep levels with the longest returns (F1, F2), and the eligible top shrinks with each bound. Faster arrivals at known keys keep coming (shortenings rose), but the novelty term does not reward them. Once coverage saturates, key novelty is the wrong signal for a speed objective; pace is the right one. | Analysis 5 (3,393 to 1,008 new cells / M; 8.2 to 1.5 orders / M; 2,699 shortenings / M; mask improvements flat at 3 to 5 / M) |
| 7 | The key discards speed-relevant state and ignores order, so faster arrivals overwrite better-placed slower ones. | By construction (`m8_rd_cell_v1`, one representative per key): velocity, facing, status, exact position and projectiles are not in the key, and A2 merges 0 and 1 jumps used. Merging orders under the mask is correct for the future (what remains depends on the mask only), but it hides ahead lineages inside trunk cells, where the count term cannot see them. | Analysis 8 (65,351 strict shortenings, 86 % materially different state; 226,205 slower arrivals dropped without state; 5,862 order-changing replacements) |

### 2.3 Component by component

| component | what it does | effect on speed (evidence) | in the proposed design |
| --- | --- | --- | --- |
| levels = targets broken | one share per level for every mask; harmonic weight 1 / (1 + top - level) | Deep bias: level 9 34.1 %, level 8 17.1 %, levels 0 to 3 3.4 to 4.9 % (sd2 review 4.1). All masks of a level share one length reference, which can belong to a mask/order with no continuation (level 7: 1,237). | Per-(level, mask) pace quantities; level shares by bottleneck budget among ahead fronts (4.1, R3) |
| count term (1 + seen)^-1/2 | penalises cells whose key was reached often | Measures visits to the old prefix: a cell whose prefix just became faster looks exhausted. 53 % of sd2's dispatches came from cells seen >= 8; yield fell from 5.5 to 0.02 new cells per return by `seen` class (sd2 review 3.3) | Dispatches since the last strict shortening (the sd2 review's V5-b) |
| E6 (recovery bound) | Excludes low airborne cells using a copy of Mario's floor table and rise constants | Stage knowledge (audit C1). The ending's fall past the floor survived only through X1. Its speed effect cannot be measured offline. | Dropped (decision 6 drops it for new stages; proposed here for Mario's new line too, Q5) |
| E7 and the record bound | Only cells with L + 1 <= T_rec - M are eligible | The only pace signal, and only at the end. It raised sd2's deep-band share 1.6 times (it helped). At 1,885 it leaves 20 level-9 and 159 level-8 cells and does nothing at levels 0 to 7. | Kept (generic: the agent's own verified clear) |
| length factor 120 / (120 + L - L_min(level)) | Prefers each level's shortest cell | Values pace, but against a mask-agnostic reference. Two bursts behind gets a third of the weight. At level 7 it favours the dead-end lineage about five-fold over the crossing cells. | Reference per (level, mask): L_min of the cell's own mask |
| replacement (`_better`) | One representative per key, the shortest non-doomed | Nine cells in ten hold their fastest arrival, but the motion state is lost (finding 7) | Kept in stages 1 and 2; multi-arrival cells tested in stage 3 (R8) |
| explorer | Uniform over 72 words, holds {1, 2, 4, 8, 16}, 120-word bursts, no observation | Hold length shows no effect. 23 % of bursts fall; grounded starts never fell. Fast moves (rolls up to 280 units per tick, up-B) are specific words. Bursts are short against segments (finding 3). | Kept as is; continuation in the same process (R4); macro ablation in stage 3 (R9) |
| session budget | 50-minute exploration cap, about 3,700 dispatches; one session per 3 to 4 calendar days of proposal, preparation, launch and review | Six sessions add up to about five hours of search and 2.32 M explored ticks; 92 % of ticks are returns; process start-up bounds short jobs | Lab mode: about 36,000 dispatches per night (section 6) |

## 3. Part 3: design options

Every option is generic and stage-agnostic. No rule reads a position, a surface, a target identity, a cid, a route tick literal or a census number.
Pace references are computed online from the agent's own archive and its own verified clears, as E7 already does.

### 3.1 Option A: a v5 selection on the inherited archive, run as registered sessions (the sd2 review's (b))

- **Mechanism.** Subclass sd2's archive with V5-b (dispatches since the last strict shortening), V5-e (a capped share of dispatches guaranteed to
  freshly shortened cells) and a per-mask length reference; register an sd3 under a new rule.
- **For.** It targets the diagnosed count-term blind spot, needs the smallest code change, and keeps the six-part audit chain.
- **Against.** It does not fund the crossing from ahead fronts, tries no join and keeps the burst length. One 50-minute session per 3 to 4 days,
  with no control arm, is not attributable. The sd2 review gives a same-design sd3 10 to 20 % for PROGRESS; a v5 has no honest estimate.
- **Offline evaluation.** The sd2 review's protocol: exact v5 census at the closing archive (masses to ahead lineages and to shortened cells), with a
  pre-registered choice among V5-b, V5-e and V5-c.
- **Cost.** About one proposal day, 12 to 15 h of preparation and a 9-hour launch day per session.
- **Risks.** Flooding (17,475 replacements against 3,769 dispatches in sd2). A new registered constant fixed without native evidence.
- **Reuses.** Everything M8.

### 3.2 Option B: pace-frontier search (PFS), lab-first, on a copy of the inherited archive

- **Mechanism.** A selection that values pace at every (level, mask) and reserves mass for fronts ahead of the agent's own best clear. Level shares
  among those fronts follow the inverse of each level's transition rate, measured online. Cells are counted by dispatches since their last
  shortening. Productive bursts continue in the same process. Clears are verified in-run. A splice-and-repair operator is added if a one-hour probe
  shows that joins survive. Full definitions are in 4.1.
- **For.** It addresses findings 1 to 7 directly:
  - pace at every mask (1);
  - an ahead pool with a bottleneck budget (2, 3, 4);
  - continuation (3);
  - splices (5);
  - pace instead of novelty (6);
  - the fresh counter, with multi-arrival cells in stage 3 (7).

  F5 shows that the inherited archive already holds the ahead states. Lab mode gives about ten sessions' worth of dispatches per night.
- **Against.**
  - More moving parts.
  - Pace-first can starve the slow exploration that originally solved the crossing. rd2 found it through a seven-burst chain on the level-7
    trunk (sd2 review 3.1), at a time when no pace reference existed.
  - Whether any ahead front can cross is unknown.
  - Splices may never survive (only 14 of 143 candidates match even in motion; position and phase are unknown).
  - The pool shares and caps are new constants.
- **Offline evaluation, registrable before any native run.**
  - (a) A mass census of PFS on the closing archive, with pre-declared mechanism expectations: the ahead pool's share is realised; every level
    with ahead cells is funded; the starved lineages of the sd2 review's section 5 receive at least the guaranteed share. This checks the
    implementation, not the efficacy.
  - (b) The hindsight probability of rd1 to sd2's productive dispatches under PFS against the rule in force. Reported only, because it is biased
    towards the old trunk.
  - (c) The splice census F5 (done).
  - (d) A synthetic-backend end-to-end test of the new job types (the worker's backend is injectable).
- **Cost.**
  - Module family: about 15 to 25 hours of sessions plus one independent review of the lab launch path.
  - Week 1: a one-hour probe and two nights.
- **Risks.** Section 7.
- **Reuses.**
  - The worker's process, standby and backend code (`m8_rd_worker`, `battleship_process`, `m7_standby`).
  - The archive format and its loader (to read the inherited ledger).
  - The keyed explorer draws.
  - The provenance guard (`FORBIDDEN_FRAGMENTS` and the audit hook).
  - The clear-replay check.
  - `rl/tools/runs_backup.py`.

### 3.3 Option C: a fresh, time-aware archive from tick 0 with Pareto cells

- **Mechanism.**
  - A new archive from tick 0, with no inherited data and no E6.
  - The v1 key, but each key keeps a Pareto set: the fastest arrival per motion class (sign of horizontal velocity with a dead zone, sign of
    vertical velocity, facing, jumps used, a projectile alive).
  - PFS selection (the ahead pool stays empty until the archive's own first clear) and continuation.
- **For.**
  - It removes the single-root lock-in (six sessions, one order).
  - It keeps speed-relevant state (finding 7).
  - It is exactly the configuration a new character needs (Donkey Kong has no archive).
  - Every route it finds is new.
  - A lab night (about 56 M ticks at sd2's rate) is about 1.9 times the whole six-session history.
- **Against.**
  - Re-discovery cost: under v1/v2 the first crossing took rd1 and rd2, about 7.4 M ticks. Under pace-first selection it may take longer or
    never happen.
  - Pareto storage multiplies the cells (the main process peaked at 1.4 GB at 50 k cells; the cap is 3 GB).
  - The first clear from scratch may stay slower than 1,885 for a long time.
- **Offline evaluation.**
  - Nothing predicts efficacy.
  - An archive-growth bound: the number of motion classes per key among the 126,561 stored exact states, to size memory.
  - The synthetic end-to-end test.
- **Cost.** Option B's family plus the Pareto archive, about 5 more hours.
- **Risks.** It never clears: nights spent with nothing registrable.
- **Reuses.** As B.

### 3.4 Option D: search plus a learned explorer from the agent's own segments

- **Mechanism.**
  - **D1, macro explorer.** With probability q, a decision copies k consecutive words (k from the hold set, at most 16) from a uniformly chosen
    *productive* burst: one that broke a target or set a new best arrival at some mask. Keyed draws as today.
  - **D2, policy or model.** A policy or model trained on the agent's own trajectories as the burst policy (Go-Explore's second phase).
- **For.** Fast moves are specific words; productive segments concentrate them.
- **Against.**
  - D1: the hold-length proxy showed no effect on breaks (analysis 6), a weak hint that timing structure matters little at this resolution. It
    biases exploration towards the old route's moves.
  - D2: M7 (PPO, GCSL, quasimetric, model planner) found no clear; M9 policies forgot or collapsed (g1 NULL, g3 s6). It is expensive.
- **Offline evaluation.** D1: per-word frequency in breaking against non-breaking bursts (cheap, reported). D2: none cheap.
- **Cost.** D1 about 3 h on top of B; D2 days.
- **Risks.** Long macros would be route pieces in disguise, so k is capped at the explorer's own maximum hold.
- **Reuses.** The explorer.

### 3.5 Comparison and choice

| | A | B | C | D1 | D2 |
| --- | --- | --- | --- | --- | --- |
| findings attacked | 3, 7 (partly) | 1 to 7 | 2, 6, 7 | 3, 4 (perhaps) | 4 |
| first native evidence | about a week | 1 hour (probe), 2 nights (comparison) | 1 to 2 nights | 1 night | weeks |
| preparation | 12 to 15 h plus the registered pipeline | 15 to 25 h | B plus about 5 h | B plus about 3 h | days |
| main risk | low upside | starving the slow exploration a bottleneck needs | never clears | narrowing exploration | collapse, cost |

**Choice: B**, with C as the arm that tests lock-in and prepares the new-character line, and D1 as a week-3 ablation. A's components are inside
B. D2 is deferred until search plateaus.

The sd2 review's v5 options map onto B as follows:

- V5-b is the `fresh` counter.
- V5-d's lead decides membership of the ahead pool.
- V5-c's frontier share becomes the pace pool's per-mask factor.
- V5-e's guaranteed try is subsumed by `fresh` = 0 for a newly shortened cell.
- V5-a (resetting `seen` on every shortening) is rejected: it would make most of 17,475 replacements per session look new.

## 4. Recommended design and November plan

### 4.1 PFS components (all generic, every one switchable)

**Quantities**, all computed online from the archive's own data:

| symbol | definition |
| --- | --- |
| `l(c)`, `m(c)` | a cell's level (targets broken) and live-target mask |
| `B(m)` | the shortest L over eligible cells with mask m |
| `R(l)` | the arrival tick at level l on the archive's best verified clear, from its own break table; undefined until a first clear |
| `lag(c)` | `L(c) - B(m(c))` |
| `lead(c)` | `R(l(c)) - L(c)` |
| `fresh(c)` | dispatches of c since its representative last became strictly shorter |
| `r(l)` | the online transition rate: (bursts from level l in the last window that reached a deeper level + 1) / (bursts from l in the window + 2) |

| id | component | definition | initial constants (lab-tunable; never set from a position, a target, a cid or a route's tick) |
| --- | --- | --- | --- |
| R1 | archive | A lab copy of archive `m8_rd_a1` as closed by sd2 (copied and hashed; the source under `runs/` is never written), continued under a new lab archive id. Cell key `m8_rd_cell_v1`. E1 to E5, X1 and E7 kept; E6 dropped. | none |
| R2 | ahead pool | Cells with `lead(c) > 0`. Level weight proportional to `min(kappa, 1 / r(l))` over levels holding ahead cells (the bottleneck budget). Cell weight `(1 + fresh)^-1/2 x 120 / (120 + lag) x w_res`. | share 1/2; kappa 8; window: the last 1,000 bursts from the level |
| R3 | pace pool | Every eligible cell, uniform level weight, the same cell weight as R2: this re-optimises the start of every mask | share 1/3 |
| R3b | tail pool | The v4 rule unchanged (harmonic levels, `seen`, the per-level length factor, E7): keeps polishing the current route's end and anchors comparability | share 1/6 |
| R4 | continuation | A burst that ends by length continues in the same process for another 120 words if its last 20 words improved some `B(m)` or made a new or strictly shorter non-doomed cell with `lead > 0`. The job carries the `B` and `R` tables at dispatch, so the decision is local and deterministic. | at most 3 continuations per job |
| R5 | splice-and-repair (only if the probe passes) | Donors: every verified clear in the archive. A candidate is a cell whose representative reaches a donor's key earlier than the donor did. Job: that representative's prefix, then the donor's words from its reach of the key to its end, then a normal burst wherever the run stands. Ingested like a burst; one try per (cell, donor). Queue ordered by gain. | 10 % of dispatches, taken from the ahead pool |
| R6 | in-run verification | Any clear candidate shorter than the run's best is replayed at once by a worker in a fresh process from tick 0. Only a verified clear (native outcome clear; `completion_input_tick`, `completion_time_passed` and the native action digest equal to the claim) updates `R` and T_rec. | none |
| R7 | metrics | I1: best verified clear. I2: continuing pace lead, the sum over levels of the positive part of `R(l)` minus the earliest arrival at l of any trajectory that also reached l + 1. I3: ahead depth, the deepest such l with a positive lead. I4: new best arrivals at masks of the deepest three levels reached, per M ticks. Plus throughput (dispatches, ticks, burst ticks per hour). | none |
| R8 (stage 3) | multi-arrival cells | Per key, the fastest arrival per motion class (as option C); selection draws (cell, arrival) | dead zone 10 units per tick |
| R9 (stage 3) | macro explorer | Option D1 | q = 1/4 |
| R10 (arm) | fresh start | R2 to R7 from tick 0 with an empty archive and only its own clears (option C without R8 at first) | none |

If `R` is undefined (R10 before its first clear), the ahead pool's share goes to the pace pool. The family's v4 mode must reproduce the registered v4
masses at the closing archive with E6 on (the equality test). The control arm then runs that mode with E6 off, so it differs from v4 only by E6
(Q5).

**What PFS does not do.**

- No rule reads a position, a surface, a target identity, a cid, a route tick literal or a census number. A source guard over the family enforces
  this.
- No hard pace window that would exclude the current route's own cells.
- No savestate, no native change, no reward, no learning.

### 4.2 Preparation: one generic, task-parameterised module family (decision 10)

| module (proposed names) | content | reuses |
| --- | --- | --- |
| `rl/frs_task.py` | task parameters: task id, character, stage, horizon, cell size, status-class table, resource rules from native `jumps_max` (audit 5.3, 6.2) | the existing task block |
| `rl/frs_archive.py` | ledger, cells, single and multi-arrival representatives, checkpoint/resume, import of an inherited `m8_rd` archive through its existing loader | `m8_rd_archive` format |
| `rl/frs_select.py` | R2 to R3b and the v4 mode; the mass census function (for the offline check and the control's equality test) | v4 formulas |
| `rl/frs_explore.py` | the v1 explorer (keyed draws), continuation (R4), macros (R9) | `m8_rd_explore` |
| `rl/frs_splice.py` | donor index, candidate queue (R5) | the lineage walk |
| `rl/frs_worker.py` | new job types (continue, splice, verify) on the existing process, standby and backend code, imported, not edited | `m8_rd_worker`, `battleship_process`, `m7_standby` |
| `rl/frs_lab.py` | the lab runner: TOML config, budget in wall or ticks, queue, machine guard, checkpoints, in-run verification, a code snapshot with hashes, `summary.json` | `m8_rd_session` patterns |
| `rl/frs_verify.py` | exact replay of a claimed clear from tick 0, and word provenance: every word of a claimed clear re-derived from the keyed explorer draws, the splice donors and the macro rule | the clear-replay check |
| `rl/frs_metrics.py` | I1 to I4 | |
| `rl/frs_tests.py` | unit tests; the synthetic-backend end-to-end test; source guards (no stage literals, no forbidden fragments, no RNG operation) | M8 test patterns |
| `tools/frs_lab/` | a one-command launcher (PowerShell) and the run queue | `tools/m8_sd2` patterns |

**Effort.** About 15 to 25 hours of scoped sessions, plus one independent review of the lab launch path (about 2 h), plus the offline census. No
tracked file is edited; new files only. The splice probe and the control equality test are part of the preparation's acceptance.

### 4.3 November plan (lab weeks first)

Week dates assume the line starts on Monday 2026-11-02 (order relative to Donkey Kong and g4: Q1). Every run below is a lab run. Native runs
need the owner's explicit authorisation.

| when | step | budget | checkpoint question |
| --- | --- | --- | --- |
| week 0 (before November; zero ticks) | Build and test the family. Write the offline census with its pre-declared expectations as the first entry of the lab index. Create the lab root, copy the archived executable and verify its hash, run the review of the lab path. | about 3 sessions | C0: tests pass; the control reproduces the v4 masses; the census meets its expectations |
| week 1, Mon | L0 smoke: the lab path end to end on a tiny budget, including the in-run replay of the inherited 1,885 clear (must be exact) | 15 min | the path works |
| week 1, Mon | L1 splice probe: every splice candidate on every verified clear of the archive, one job each, no exploration | under 1 h | does any splice keep the donor's later breaks? |
| week 1, Mon to Thu nights | Comparison: control against PFS-1 (R1 to R3b, R6, R7), 4 h each, in ABBA order over two nights, each from the same archive copy | about 16 h | C1 (Fri): PFS-1 against control on I1 to I4; the splice verdict |
| week 2 | PFS-2 = the C1 winner + R4 (+ R5 if L1 passed), against the C1 winner (two nights, ABBA). The fresh arm R10, one night. | about 24 h | C2: continuation and splice kept or dropped; the fresh arm's ahead depth and first clear |
| week 2, weekend | Campaign: the best configuration continues its own archive for 48 h | 48 h | |
| week 3 | Ablations R8 and R9 against the current best (one night pair each); campaign nights afterwards | about 4 nights | C3: keep or drop each |
| week 4 | Campaign nights. A registration session for the best verified lab clear if it beats 1,885 (6.6). A written line review (at most two pages), with the plateau check. | | C4: continue, plateau or renew |

**Pre-declared checkpoint rule.** A change is kept if it gives a faster verified clear than every replicate of the arm it is compared with. If
I1 ties, it is kept if it is better on I3 and on I2 in every paired replicate. Otherwise it is dropped. The rule and the arms are written in the
lab index before the runs.

### 4.4 How progress is measured and verified

- The line's progress is I1, the best verified clear (`completion_input_tick`, with `completion_time_passed` reported beside it, never collapsed).
- A clear exists only when its words replay exactly from tick 0 in a fresh process. This is automatic in-run (R6) and repeated at the end of
  every run.
- I2 to I4 are leading indicators, used only for lab decisions, never as claims.
- Word provenance (`frs_verify`) is part of every clear's verification. Each word must come from the keyed explorer, a donor's own words or the
  macro rule, so the claimed route is visibly the agent's own.

### 4.5 Subjective odds (grounds stated; nothing offline measures the crossing from new states)

| event by the end of November | odds | grounds |
| --- | --- | --- |
| a verified clear shorter than 1,885 | 60 to 80 % | A same-design session had 30 to 45 %; lab mode gives about ten sessions of dispatches per night; the tail pool keeps the end-polishing channel |
| at or below 1,800 (needs the crossing or the right side) | 25 to 45 % | It depends on an ahead front crossing, or on surviving splices; the left-side legs have about 40 to 45 ticks of slack in all (sd2 review 4.2) |
| at or below 1,600 | 10 to 25 % | Needs a new crossing from a substantially faster right side; F5 shows such states exist up to level 7 |
| no change at all (plateau at 1,885) | 15 to 30 % | The ahead fronts may be dead ends at a moving-object phase; pace-first may starve what a bottleneck needs |

## 5. Outcomes and line-ending conditions

**Lab-run outcomes** (one per run; written into `summary.json` and the lab index):

| outcome | condition |
| --- | --- |
| `LAB_FASTER_CLEAR` | a clear shorter than the line's best verified clear, verified by exact replay from tick 0 and by word provenance |
| `LAB_CLEAR` | verified clears only at or above the line's best |
| `LAB_FRONT_PROGRESS` | no faster clear; I2 or I3 improved over the run's start archive |
| `LAB_NO_PROGRESS` | none of the above |
| `LAB_INCOMPLETE` | budget not reached (crash, machine guard, owner stop); the archive is checkpointed and resumable |
| `LAB_INVALID` | a forbidden read, an integrity mismatch, an inexact replay of a claimed clear, or a word whose provenance cannot be re-derived; the run's results are void |

**Checkpoint decisions (C1 to C4):** KEEP or DROP each component, by the pre-declared rule (4.3).

**Registration outcomes** (registered mode, 6.6):

| outcome | condition |
| --- | --- |
| `REGISTERED` | Exact replay from tick 0 in the registered path; word provenance re-derived; the lab tree's hashes match its manifest; the lineage walks back to tick 0 through the agent's own bursts. The clear becomes the registered record. |
| `REGISTRATION_INEXACT` | The replay differs. The lab claim is withdrawn and the lab run relabelled `LAB_INVALID`. |
| `REGISTRATION_PROVENANCE_FAIL` | A word not re-derivable, or a forbidden read. The claim is withdrawn and the line stops (`END_DEFECT`). |

**Line-ending conditions (explicit, all of them):**

1. `END_PLATEAU`: three consecutive campaign nights of the best configuration (each at least 8 hours of exploration at N = 5) bring no faster
   verified clear and no new best arrival at any mask of the deepest three levels reached. A written review (at most two pages) follows; renewing
   needs a new design, not more nights.
2. `END_BUDGET`: Friday 2026-11-27 (end of week 4). A written review decides renewal; the line does not continue by default.
3. `END_DEFECT`: any provenance failure (a forbidden read, a word not re-derivable), any native RNG operation found in the path, or a lab clear
   failing registration by provenance.
4. `END_MACHINE`: two machine-guard stops in one week. Stop and review the machine state; never lower a threshold.
5. `END_OWNER`: the owner stops the line.

Not line-ending: a dropped component, `LAB_NO_PROGRESS` on a comparison run, or a `REGISTRATION_INEXACT` explained by a fixed code defect (which
must be documented).

## 6. Part 4: a fast experimental loop (lab mode)

### 6.1 Two speeds

- **Lab mode** tries search ideas quickly: many variants per week, long unattended runs, compact summaries, exploratory evidence only.
- **Registered mode** is the existing pipeline, used only to register a result lab mode found (6.6). Registered trees and lab trees never mix.

### 6.2 What lab mode drops, and what it keeps

| registered pipeline | lab mode |
| --- | --- |
| triple Part B passes; every registered M8/M9 suite (about 5 h) | One pass of the family's own tests and the synthetic end-to-end test per code change (minutes). Lab code never edits registered code, and a source guard checks this. |
| approvals tied to HEAD, fingerprints, source snapshots on D: | The runner copies the code it runs into the run folder, records each file's sha256, and runs from the copy (a mid-run edit cannot leak in) |
| an independent pre-launch review per session | Once for the lab launch path; then a 10-item self-check printed by the runner |
| the six-part close audit (replays every selection, about 10 minutes and growing) | A ledger consistency check, the lineage walk and the word-provenance check of claimed clears |
| post-run increments on D: and an independent re-hash | A weekly copy of the lab root to a separate D: folder with a hash manifest (Q3) |
| long results records, a review per session | `summary.json` (at most about 60 lines) and one line in the lab index; a weekly digest of at most one page |
| a registered line rule per session | The comparison rule and the arms written in the lab index before the run |
| the full pre-launch machine routine | Optional; the memory thresholds and refusal stay |

**Non-negotiable in lab mode** (each enforced in code or by the runner):

1. No TAS, human recording or owner run anywhere: the worker's provenance guard and audit hook, plus `replay/recordings` added to the family's
   forbidden fragments (audit C9).
2. No native RNG seed inspection, logging, control, comparison or hashing.
3. Canonical controller words, one native update per word, process restart as the only reset, no savestate, no hidden action.
4. Generic rules only. The source guard over the family rejects stage coordinates, target identities, cids and route tick literals. Lab
   constants may be tuned on search performance, never set from a position, a target or a route's tick, and each constant's origin is recorded.
5. Any clear claimed, even informally (chat, index, video draft), has been replayed exactly from tick 0 in a fresh process and passed word
   provenance. Unverified means "candidate", never "clear".
6. Lab evidence lives in the lab root, outside `runs/`. Every file carries `"mode": "lab"`. No registered session reads it except a registration
   session, which hashes it first. Registered trees under `runs/` are read-only for lab runs, and inherited archives are copied.
7. The lab runner uses a pinned copy of the executable (the archived `30a3913b`), so rebuilds for other lines cannot change a running
   experiment.
8. Machine safety: memory thresholds and refusal; no application is ever closed by a run or a session; one native workload at a time (no lab run
   during a registered session or any other native work).
9. Sessions never commit, push or branch. New files are written with LF.

### 6.3 Running several variants per week, and longer searches

- **Comparison runs** answer one question. Each arm starts from the same archive copy, under equal wall budgets and the same N. Arms are queued
  back to back overnight in ABBA order (for example four 2-hour runs, or two 4-hour runs per night), and each run is independent.
- **Campaign runs** maximise progress. The current best configuration continues its own archive night after night and over weekends. Only
  campaign runs feed the plateau rule.
- The runner checkpoints every 15 minutes, resumes after a crash, stops itself on a machine-guard trigger, verifies clears in-run, and writes
  `summary.json` at the end. The owner reads one file in the morning.
- Throughput levers, measured once in a dedicated lab run, never mixed into a comparison: a second standby per worker (the sd2 review found
  start-up to be the bound) and N = 6, if memory allows.

### 6.4 Comparing variants fairly with few runs

1. Equal wall budgets, same machine, same N, same start archive; ABBA order cancels drift through the night.
2. Different draw keys per replicate (Python-side keyed draws; no native RNG). Parallel ingestion order makes runs non-reproducible, so two
   control replicates in week 1 measure the run-to-run spread of I1 to I4.
3. One primary metric (I1) and pre-declared leading indicators (I2, I3). A change is kept only if its direction is consistent in every paired
   replicate (4.3). With two to three replicates there are no p-values: a win is "better in every pair" or a verified faster clear.
4. Throughput is reported beside the result, so a variant that wins only by running more dispatches (continuation does, by design) is visible
   as such.

### 6.5 Cost per experiment

| item | registered session (sd2 as measured) | lab experiment |
| --- | --- | --- |
| design | a proposal session of about a day | a paragraph in the lab index |
| preparation | 12 to 15 h of sessions plus about 5 h of unattended passes | 1 to 3 h of a scoped session for a new variant (none for a re-run) plus minutes of tests |
| review before launch | an independent review per launch path | once for the lab path |
| launch day | 10 h 36 min (Part B 4 h 28 min, Part C 2 h 38 min, Part D 3 h 29 min) | one command and 15 minutes of machine preparation |
| search time | 50 minutes | 2 to 10 hours per night, 48 hours per weekend |
| verification | in session | in-run, minutes |
| reading the result | a review session of about a day | `summary.json`, about 10 minutes; a weekly digest, about an hour |
| calendar | 3 to 4 days per experiment | 1 day per experiment, 3 to 5 per week |
| exploration per calendar week | about 1 to 2 hours | about 40 to 90 hours |

Sessions in the registered pipeline read many records in full. A lab experiment needs one short coding session at most, and the run itself costs
no session time.

### 6.6 Registered mode, used only to register a lab result

A registration session takes a frozen lab run folder and performs these steps:

1. Re-hash the folder against its manifest; back it up to D: with an independent re-hash.
2. Walk the claimed clear's lineage back to tick 0. Check inherited bursts against the registered `m8_rd_a1` manifest, and lab bursts against the
   lab ledger.
3. Re-derive every word (explorer keys, donors, macro rule) and check the provenance guard's log.
4. Replay the clear from tick 0 in a fresh process through the registered path.
5. Write a short record.

It does not re-run the search. A registered re-run of the method (a full registered session under the lab-found design) is optional, once, at the
end of the line, if the video needs a claim about the method rather than the result (Q10). Estimated cost: one session of about 2 hours, plus the
backup.

### 6.7 Reading less

- `docs/project_handoff.md` stays the single entry point, with a fast-route block of at most 15 lines: the registered best, the lab best
  (labelled exploratory), the active configuration, the next step, and pointers.
- A tracked lab index, `docs/rl_fast_lab_index.md`, one line per run: id, date, arm, start archive, budget, outcome, I1 to I4, folder. The owner
  commits it weekly.
- Each run's `summary.json` is designed to be read instead of logs.
- Session prompts name exactly what to read: the handoff, the lab index, and the one design section of the variant. "Do not read records in full"
  becomes the default.
- Lab results get no long records. The weekly digest is at most one page, and a registered record cites lab-index lines instead of re-deriving
  them.

## 7. Risks

| risk | effect | mitigation |
| --- | --- | --- |
| pace-first starves the slow exploration a bottleneck needs | No front ever crosses; the line plateaus at the old route | The tail pool (1/6) keeps v4's behaviour; the bottleneck budget raises effort where transitions are rare; the C1 control arm shows it |
| splices never survive (state, position, projectiles, moving-object phase) | One hour lost | The probe gates R5; nothing else depends on it |
| continuation wins only by throughput | Mistaken attribution | Throughput reported beside every result (6.4); attribution is not needed for registration |
| noise taken for signal with 2 to 3 replicates | A useless component kept | Pre-declared rules; the week-1 control spread; any claim rests on I1 (verified clears) only |
| lab constants drift into stage knowledge | Breaks the generic rule (audit C6, C7) | A source guard; each constant's origin recorded; never set from positions, targets or route ticks |
| lab and registered evidence mix | Registered integrity questioned | Separate root outside `runs/`, a `mode` field, a hash-first registration session |
| registered coverage checks see lab files | False alarms like sd2's base row | The lab root is outside `runs/` (Q3) |
| exe rebuilt for the Donkey Kong line during a lab run | Silent change of the environment | The lab uses the pinned archived executable copy and checks its hash at every start |
| memory (multi-arrival cells, long campaigns) | Machine-guard stops | Memory sized from the stored states before R8; checkpoints; END_MACHINE rule |
| inherited archive built with E6 (rd2 to sd2) | Disclosure: the inherited cells were selected under stage-specific pruning | Disclosed as for the frozen lines; the fresh arm (R10) has none |
| a faster registered route changes inputs of other lines (g4's landing registry) | Coupling | g4 derives its landings at P1 by its generic rule (decision 5); decide when g4 starts |
| the line's priority against Donkey Kong and g4 | Calendar conflict | Q1 |

## 8. Open questions

1. **Priority in November.** Options: (a) the fast-route line first, Donkey Kong after; (b) interleave: lab nights on Mario with the pinned
   executable, daytime Donkey Kong work (zero-tick and native smoke tests never overlapping a lab run); (c) Donkey Kong first as decided on
   2026-10-13, this line after. *Recommendation:* (b). It changes the decided order only for nights, and the fresh arm R10 is the Donkey Kong
   search configuration anyway.
2. **Adopt lab mode with the non-negotiables of 6.2.** Options: as written; stricter (an independent review per new variant); looser (no in-run
   verification). *Recommendation:* as written, with one independent review of the lab launch path only.
3. **Lab root location and backup.** Options: (a) a sibling folder outside the checkout (no Git or coverage interaction); (b) a new folder in the
   repository plus a `.gitignore` line (an owner commit); (c) under `runs/` (breaks the registered coverage checks). Backup: a weekly copy to a new
   D: folder, or none. *Recommendation:* (a), with a weekly copy and a hash manifest.
4. **Start archive for the main arm.** Options: a copy of `m8_rd_a1` at sd2's close; fresh from tick 0. *Recommendation:* the copy for weeks 1 and
   2, with the fresh arm (R10) as a one-night arm in week 2.
5. **E6 in this line.** Options: drop in every new arm and in the control; drop in new arms but keep in the control (exact v4); keep everywhere.
   *Recommendation:* drop everywhere, so the control isolates the selection change and the line is generic.
6. **The splice probe.** Options: run it first (under 1 hour, all candidates on all verified clears); skip it and leave R5 out; include R5 without
   a probe. *Recommendation:* run it first.
7. **Initial PFS constants** (pool shares 1/2, 1/3, 1/6; kappa 8; window 1,000 bursts; 3 continuations; splice share 10 %). Options: accept as
   lab starting values; ask for an offline sensitivity census first. *Recommendation:* accept as starting values; the census of C0 checks the
   mechanism, and lab results decide changes.
8. **Fair-comparison protocol.** Options: equal wall against equal ticks; 2 against 3 replicates per arm. *Recommendation:* equal wall, N = 5, 2
   paired replicates in ABBA order, and two control replicates in week 1 to measure the spread.
9. **Plateau rule.** Options: three consecutive campaign nights without a faster clear and without a new best at the deepest three levels; two
   nights; a fixed number of exploration hours. *Recommendation:* three nights, plus the END_BUDGET review on 2026-11-27.
10. **Registration scope.** Options: (a) replay, provenance and lineage only, no search re-run; (b) (a) plus one registered re-run of the method at
    the end of the line. *Recommendation:* (a) for every new best; (b) only if the video needs a method claim.
11. **Macro explorer (R9).** It uses short word runs (at most 16) from the agent's own productive bursts. Options: allowed as the agent's own
    data, with disclosure; not allowed (it reads as a route hint). *Recommendation:* allowed, with the cap, as a week-3 ablation only.
12. **A learned policy or model (D2).** Options: defer until search plateaus; include in November. *Recommendation:* defer.
13. **Throughput levers in lab** (a second standby per worker, N = 6). Options: measure once in a dedicated run; never; adopt without measuring.
    *Recommendation:* measure once, before the campaign nights, never inside a comparison.
14. **Lab index.** Options: a tracked `docs/rl_fast_lab_index.md` committed weekly by the owner; only inside the lab root. *Recommendation:*
    tracked and committed weekly; it is the second file every session reads.
15. **Pace reference for the ahead pool.** Options: `R(l)` from the best verified clear (proposed); the best arrival at each level that continued
    to the next level. *Recommendation:* the best verified clear, because it is the route that actually finishes.
16. **Naming.** Options: `rl/frs_*` and `tools/frs_lab/` (fast-route search); a character-neutral `rl/srch_*` shared with the Donkey Kong line.
    *Recommendation:* `rl/frs_*`, task-parameterised. The name is the owner's choice, and decision 11's character segment goes into run-folder
    names, not module names.
