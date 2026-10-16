# Segment optimiser proposal (2026-10-16)

## 0. Status, scope, sources and method

**Status: offline design study; zero native ticks.** No game, lab command, suite or launcher was started; no `lab.lock` existed under
`C:/BattleShip_lab/` and no BattleShip or Python process ran at the start. Checkout `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`,
branch `main`, HEAD = `origin/main` = `d1691d0`, clean. Nothing under `rl/`, `tools/`, `port/`, `runs/`, `C:/BattleShip_lab/` or D: was
created, modified or deleted. New files: this record and the Git-ignored working files under `logs/frs_segment/` (three `python -B`
scripts, standard library only, and their JSON outputs; appendix). The TAS, every human recording, the owner's own run and any external
time were not read or used, and no time other than the agent's own appears below as a target or a reference. This record proposes; it
decides nothing and launches nothing.

**Read.** `docs/project_handoff.md`, `docs/rl_decisions_2026-10-16.md`, `docs/frs_strategy_2026-10-16.md` and
`docs/frs_prefix_cost_2026-10-14.md` in full, `docs/frs_splice_probe_2026-10-14.md` in full, `docs/frs_crossing_2026-10-14.md` sections 1
to 3 and 5 to 8; the strategy review's working files (`logs/frs_strategy/s1_anatomy.json`, `s2_pairs.json`, `s2_pairs_by_class.json`,
`s4_explorer.json`, `scripts/s0_common.py`); read-only, the lab's record shapes (one row each of run 2's `cells.jsonl`, `dispatches.jsonl`
and `verifications.jsonl`, run 2's `summary.json` and `report.md`, one step of the 1,245 trace, the splice probe's `candidates.jsonl` and
`run/results.jsonl`); the cell key and classifier of `rl/m8_rd_cells.py`.

**Vocabulary.** Level = targets broken; "transition A -> B" = ticks from the break of A to the break of B when B is the next break; class =
the archive's resource class at a tick (G grounded, A2 airborne with double jump and up-B, A1 up-B only, A0 up-B in progress or helpless);
"pair best" = the fastest transition observed anywhere in the agent's data for an ordered pair (the strategy review's section 2). Target ids,
ticks and coordinates below describe the records; no rule, objective or selection proposed here reads any of them.

## 1. Formulation

### 1.1 What a segment is

- **Start state S.** The complete native state reached after a verified prefix of L canonical words from tick 0: the 17-field observation
  record plus the spatial, entity and input records at input tick L (position, velocities, facing, status id, status timer, jumps used,
  floor line, the moving groups' translation and speed, the live-target mask). Its level k is the mask's popcount deficit. Without
  savestates S is only ever re-entered by replaying the same L words from tick 0, so "a start state" and "a prefix" are the same object; a
  prefix is accepted as S only if its replay reproduces the stored end digest and chain, the check the worker already makes.
- **End condition.** The first tick after L at which the live-target mask loses a bit (one break). Secondary ends: a native failure
  (fall), the word budget exhausted without a break, or the episode's end. Two breaks inside one burst are two segments, the second
  starting mid-move (the 1,245 breaks targets 5 and 7 within one up-B, 17 ticks apart). The segment's time is the break tick minus L.
- **The chain.** A clear is the concatenation W_1 ... W_10 of ten segment words from tick 0; its clock is the last break tick. The
  prefix of segment k + 1 is P_k || W_k, exactly, so chaining is exact by construction as long as every segment is optimised from the
  actual end state of its predecessor (section 5).

### 1.2 Which start states precede the fastest transitions (data)

From `s2_pairs_by_class.json` (54 ordered pairs, class at the previous break; `logs/frs_segment/a1_classes.json`):

| quantity | value |
| --- | --- |
| class at the previous break of the 54 pair bests | A1 20, A0 11, A2 10, G 10, unrecorded 3 |
| class at the end of the 54 pair bests (the class the next segment starts from) | A0 22, A1 9, A2 6, G 5, unrecorded 12 |
| same over the top six transitions of every pair (310 rows) | A0 93, A1 69, A2 39, G 23, unrecorded 86 |
| pairs with a G or A2 start observed | 38 of 54 |
| cost of requiring a G or A2 start (G/A2 best minus pair best) | 0 ticks in 20 pairs, 1 to 30 in 7, 31 to 100 in 9, over 100 in 2 |

The 1,245's own ten segments start G, A1, A1, A0, A0, A0, G, A2, A2, A2 (the fine classes: jump squat, aerial attack x 2, up-B x 3, jump
squat, down-B x 2, aerial attack). Its three slowest segments relative to their pair bests start A0 (toward targets 9 and 3) and G on the
moving platform (toward target 6); its two cleanest start G at tick 0 and A2.

**Reading.** The fastest transitions are launched from airborne states that still hold resources (A1 and A2 together 30 of 51 recorded
starts) and they very often end in the resource-poor class A0 (22 of 42 recorded ends): an up-B or an aerial that breaks the target and
leaves the fighter helpless or in a 25-tick landing lag. That is exactly where the 1,245 then loses time (49 helpless + 25 lag after the up-B
through target 7, 25 lag after the up-B to the right platform, 70 ticks on the wall top after the crossing up-B). A segment objective that
counts only the time to the next break will select these ends; the chain then pays for them in the next segment. The data also says the
price of insisting on a G or A2 end is often small (zero in 20 of 38 pairs, at most 30 ticks in 27 of 38), which makes an end-state term
affordable. These are observations over one route family; they are not bounds.

### 1.3 How sensitive a transition is to small state differences (the splice probe's 198 results)

Recomputed from `candidates.jsonl` and `run/results.jsonl` by class, position offset and gain (`logs/frs_segment/a2_sensitivity.json`).
Every candidate replaced the route's state at a cell by an archive arrival in the same 300-unit cell, 12 to 295 units away, and played the
route's own tape from there.

| split | n | cleared | kept the next route break | kept it on the shifted schedule | median ticks to leave the route's cell |
| --- | ---: | ---: | ---: | ---: | ---: |
| class A0 | 57 | 9 | 37 (65 %) | 25 | 3 |
| class G | 25 | 0 | 12 (48 %) | 3 | 7 |
| class A2 | 52 | 0 | 22 (42 %) | 9 | 3 |
| class A1 | 64 | 0 | 23 (36 %) | 6 | 3 |
| offset <= 50 units | 41 | 6 | 29 (71 %) | 21 | 5 |
| offset 51 to 150 | 71 | 3 | 32 (45 %) | 12 | 3 |
| offset > 150 | 86 | 0 | 33 (38 %) | 10 | 3 |
| gain 1 | 18 | 9 | 14 | 12 | 4 |
| gain 2 to 9 | 20 | 0 | 12 | 6 | 3.5 |
| gain 10 to 99 | 43 | 0 | 25 | 5 | 3 |
| gain 100 + | 117 | 0 | 43 | 20 | 4 |
| gain > 1 and offset <= 50, class A0 | 10 | 0 | 8 | 8 | 4 |
| gain > 1 and offset <= 50, classes A1, A2, G | 20 | 0 | 12 | 5 | 5.5 |

The exact state differed at the first tick in every case (median exact divergence 0 ticks); the cell diverged within a median of 3 ticks
(7 for grounded starts); the tape kept the very next break in about half the cases and the one after it essentially never (0 of 180 with
gain >= 2 kept every later break; the nine clears are all gain-1 splices in helpless descents, where inputs barely move the fighter).

**Consequences for the optimiser, all generic.**

1. A word sequence is valid only from the exact state it was optimised from. Every segment is therefore optimised from the actual end
   state of its predecessor, never copied onto a "similar" state (section 5).
2. Two search states may be merged as duplicates only when their end records are identical (same end digest). Coarser keys serve
   diversity and budget allocation, never merging; the archive's one-representative-per-key rule is the wrong structure for an optimiser
   (section 2.2).
3. A local change to a known segment invalidates its tail within a few ticks. Mutation operators must re-plan everything after the
   mutation point ("mutate and repair"), not keep the old tail; the cheapest repair is a fresh random tail, which is what an archive
   dispatch from a kept cell already is.
4. The first break after a change is the natural checkpoint: survival to the next break is common (about half), survival beyond it is
   not, so segment boundaries are exactly where re-planning must happen.

### 1.4 Objective, stated generically

- **Primary:** the time from the start state to the next break (ticks). A candidate that does not break within its word budget scores by
  a generic progress fallback used only to order non-breaking candidates among themselves: the smallest distance reached to any live target
  (target positions and the live mask are observed each tick; no coordinate is written anywhere), and the ticks spent without motion.
- **Secondary (end-state quality for the next segment):** generic resource and availability features of the state at the break: the
  resource class order G = A2 > A1 > A0; whether the fighter is in an uninterruptible status at the break (the classifier's landing-lag and
  helpless classes, the status timer); jumps remaining (jumps_max minus jumps_used from the entity record). None of these names a stage.
- **Measured rather than modelled (recommended for the pilot):** the two-segment time, that is the break after next, obtained by continuing
  the same process from the break with the explorer's random words for one burst (the worker's continuation path already does this). It
  prices the end state by what actually follows instead of by a hand-made order, at the cost of up to one burst per elite candidate.
- **Combination.** Lexicographic: the primary decides; among candidates within a tolerance of the best primary, the secondary decides.
  The tolerance is a search constant (one hold length), not a census number. The pilot measures the primary alone and the two-segment time
  on the elite, so the owner can see whether the secondary is needed before it enters any rule (open question 2).

## 2. Search methods for a deterministic simulator without savestates and with an expensive prefix

The one fact that shapes every method: **a candidate evaluation is one process**, booted fresh, replaying the prefix of L words and then
the candidate's words; nothing can be rewound. Candidates per hour equal processes per hour (section 3), whatever the method. A method's
merit is therefore its evaluations per improvement and how well it uses the prefix already paid.

### 2.1 Random restarts from the start state (the baseline and the control)

The archive's dispatch confined to one state and one objective: random hold-runs from S, stop at the break or the budget. Evaluations per
improvement: the strategy review found the agent's fastest transitions were produced this way, breaking at a median of 11 to 26 words into
the burst, and the crossing study measured 6 to 77 % per-burst success from states already within reach of a target and 0 % from states
that are not. No use of the prefix beyond the one replay; no use of the agent's segments. It is the control every other method is
compared with, and it is already built.

### 2.2 Within-segment Go-Explore with exact deduplication (recommended first)

The archive's mechanism (keep the first reach of each key, re-dispatch kept states) restricted to one segment, with three changes: (a) the
objective is the earliest break, so a kept state's weight rises with its lead over the best known break and falls with its dispatch count,
and non-breaking states are weighted by the generic progress fallback; (b) merging only on identical end records, with a fine diversity key
(position at a finer bin, velocity sign and magnitude bucket, class, status class, jumps used, the moving groups' translation bucketed:
all read from the records, none stage-specific) that caps how many kept states share a bucket; (c) the selection returns to a kept state
within minutes because the pool is a few thousand states, not 37,000 cells over four levels. Evaluations per improvement: the chain
economics of the crossing study (about 50 useful ticks per useful dispatch, each link found within 1 to 3 dispatches of its cell) suggest
a 150-tick segment needs 3 to 5 chained dispatches of the right states; with a pool that is re-dispatched promptly, hundreds rather than
tens of thousands of evaluations. Prefix sensitivity: each evaluation replays L plus the kept state's offset; moderate. Use of the agent's
segments: the words of the pair's fastest observed transitions seed the first dispatches (played from S they are expected to fail by
section 1.3, but they cost one evaluation each and their first holds often survive the first few ticks).

### 2.3 Cross-entropy or evolutionary optimisation over hold-run sequences

Candidates are sequences of (word, duration) hold-runs; a population of N per generation, the elite fraction refits per-position categorical
word distributions and duration distributions; the objective is the break tick with the progress fallback. Evaluations per improvement:
N x generations (for example 128 x 20 = 2,560) with no guarantee on this landscape, because section 1.3 says a one-tick timing change can
flip the outcome: the fitness surface is rugged in exactly the dimensions CEM smooths over. Prefix sensitivity: one replay of L per
candidate, the lowest of all methods. Use of the agent's segments: the hold statistics (direction and button frequencies by phase of the
segment, run lengths) of the pair's fastest observed transitions form the initial distribution, which is the only place a prior enters.
Best suited to short segments whose motion is mostly ballistic (aerial drifts, descents), worst to landings and moving-object timing.

### 2.4 Monte Carlo tree search over hold-runs

A tree whose edges are hold-runs and whose rollouts are random bursts; a simulation is one process (prefix, the path to the node, the
rollout); node value is the best break tick in its subtree, the tree policy balances it against visit counts, and progressive widening
limits the 72 words x durations branching. It makes the "return to good states" explicit along depth, which is what the archive lacked,
and the deterministic simulator removes rollout noise. Evaluations per improvement: comparable to 2.2 in principle, with the known
difficulty of tuning exploration constants on a rugged objective; the tree itself is the dedup structure, so exact-record merging becomes a
transposition table. Prefix sensitivity: like 2.2. Use of the agent's segments: as rollout biases or initial children. Worth building
only if 2.2 shows that the pool's selection, not the per-state luck, is the bottleneck within a segment.

### 2.5 Beam search over hold-runs with state-key deduplication

At depth d every kept state (beam width B) is expanded by K hold-runs: B x K processes per depth, each replaying the prefix and the path so
far; depth about the segment's length over the mean hold (150 / 6 = 25); total about B x K x 25 evaluations (16 x 6 x 25 = 2,400) and a
ranking heuristic at every depth (the progress fallback). Prefix sensitivity: the highest of all methods, since every depth replays the
prefix and the whole path; the native block prefix matters most here. Risk: a greedy progress heuristic prefers approach over the detours
the fast transitions actually take (the 1,245's flight away from the next target before an up-B). Not recommended first.

### 2.6 Local refinement of a known segment (mutate and repair)

Start from the clear's own segment (or a pair best from the same exact state, if any) and apply small changes: shift a hold boundary by
one to three ticks, replace a hold's word, delete or insert a hold, biased toward the segment's slow stretches (still ticks, ticks moving
away from every live target, landing lag: generic motion measures of the trace). Section 1.3 forbids keeping the old tail, so each mutation
is followed by a repair: the remaining words are re-drawn (random tail) or re-optimised by 2.2 from the mutated state. Evaluations per
improvement: unknown and probably hundreds per mutation point; it is a polishing pass for a segment that is already fast, cheap when the
mutation sits in a helpless or ballistic stretch (the probe's nine one-tick clears are this case) and expensive around landings.

### 2.7 Recommended combination

Within-segment Go-Explore (2.2) as the body of the search, with the agent's fast segments as first dispatches; the two-segment continuation
(section 1.4) on the elite to price the end state; mutate-and-repair (2.6) as a second pass on the best segment found. CEM (2.3) is kept as
the second pilot arm if 2.2 passes or is inconclusive, on a short ballistic segment, because its evaluation cost is the lowest and its
failure mode (ruggedness) is the one thing the pilot can measure cheaply.

## 3. Cost model

### 3.1 Per candidate, today

From `docs/frs_prefix_cost_2026-10-14.md` and run 2's summary: a job is a standby wait (0.72 to 0.89 s), tick 0 (18 ms), the prefix at 1.1 to
1.4 ms per tick, the segment's ticks at the same rate, and 1.1 to 1.2 s outside the job clock (close, transfer, select). One standby per
worker boots in 2.2 to 4.8 s loaded (median 3.76 s), launched at the previous acquire, so a worker's cycle is about max(boot, job + close):
**today's pipeline is boot-bound as soon as a job is shorter than a boot**, and a segment candidate with a short prefix is not evaluated
faster than one with a long prefix. Run 2 measured 5,057 jobs per hour at N = 5 with 1,276 ticks per job on average; the cycle floor from
the boot alone is about 4,800 per hour at the median boot (3,800 to 6,100 between the quartile boots of 4.72 and 2.94 s). Candidates per
hour today: about 5,000 for any segment; per 7.2-hour night about 36,000.

### 3.2 Per candidate, with the Python levers and with the native batched prefix (projections)

| scenario | segment with prefix 0 | prefix 461, segment 178 | prefix 1,042, segment 93 | binding cost |
| --- | --- | --- | --- | --- |
| today, single step, one standby | job 2.0 s, cycle 3.8 s | 2.8 s, cycle 3.8 s | 3.4 s, cycle 3.8 s | the boot wall (one standby per worker) |
| revision 2 (close off the critical path, two standbys) | 0.3 s, cycle about 1.9 s | 1.1 s, cycle 1.9 s | 1.7 s, cycle 1.9 s | the boot: two per 3.76 s per worker, and its CPU (unmeasured) |
| revision 2 + native block prefix, single-step segment | 0.3 s | 0.7 s | 0.85 s | the boot, then its CPU |
| revision 2 + native block prefix and segment | 0.3 s | 0.6 s | 0.8 s | the boot's CPU |

Rows are per-job wall from the record's measured constants (1.25 ms per tick single step, 0.42 ms per tick in a block, 2.0 s and 0.3 s of
per-job overhead); `logs/frs_segment/a3_cost.json` has all ten segments. Candidates per hour at N = 5: today about 5,000; revision 2 about
9,500 if the boot's CPU allows it (if a boot costs about 2 CPU-seconds, 9,500 boots per hour occupy about 5.3 of 6 logical CPUs; the record's
d1 cap is about 10,800 per hour with nothing else running); with the native block the per-job wall falls below the two-standby cycle for
every segment, so the block alone raises candidates per hour only if more standbys (three per worker or a shared boot pool) are allowed,
and then the boot's CPU is the cap. Realistic ranges per night: today 36,000; revision 2 50,000 to 68,000; native block 55,000 to 78,000,
all capped by a boot CPU cost nobody has measured.

### 3.3 Candidates per segment, segments per night

- One segment per night: 36,000 candidates today, 50,000 to 78,000 later. Two segments: half each. A within-segment Go-Explore run that
  improves a segment in 1,000 to 3,000 evaluations (section 2.2's hope, unverified) would allow a full forward sweep of ten segments in one
  night today (10 x 3,000 = 30,000); a CEM run of 2,560 likewise. If a segment needs 10,000 evaluations, a night improves three or four.
- **Where the native batched prefix changes feasibility:** (a) beam search and any method that replays the prefix at every depth; (b) the
  deep-prefix segments (prefix >= 639) under revision 2, whose single-step wall (1.1 to 1.9 s) is at the two-standby cycle; (c) CPU headroom,
  since the round trip's 0.8 to 1.0 ms per tick of CPU across threads is freed for boots; (d) the verification replays (3.7 to 8.3 s each
  today, 2.7 to 5.4 s in blocks; minor). It does not change the boot-per-candidate equation.
- **The lever specific to segments: several segment evaluations per process.** A candidate that breaks its target can continue into the
  next segment with the next candidate from the state it actually reached (the continuation path), so one boot evaluates a chain of
  segments: the two-segment objective of section 1.4 is free for breaking candidates, and a forward sweep that evaluates segment k + 1
  candidates right after a successful segment k amortises the boot over two or three segments. This matters more for the optimiser than the
  prefix speed-up.

## 4. Evidence of room (observations, not bounds)

The 1,245 segment by segment against the agent's own fastest observed transition for the same pair (the strategy review's table), with the
class at the end of that pair best and the segment's slow ticks (`s1_anatomy.json`): "same class" = fastest observed from the class the 1,245
was in at the previous break; "G/A2" = fastest observed from a grounded or A2 start.

| pair | clear | pair best | from class | best ends in | same class | G/A2 | still | away in x | path over chord | what the segment contains |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| start -> 4 | 29 | 26 | G | A2 | 26 | 26 | 2 | 2 | 1.06 | two jumps, aerial |
| 4 -> 0 | 51 | 45 | A1 | A0 | 45 | 46 | 6 | 0 | 1.27 | aerial drift |
| 0 -> 5 | 87 | 45 | G | A0 | 83 | 45 | 19 | 8 | 1.49 | 15 idle ticks on the floor, two jumps, up-B |
| 5 -> 7 | 17 | 11 | A0 | A0 | 11 | n/a | 3 | 0 | 1.01 | the same up-B |
| 7 -> 9 | 121 | 96 | A0 | G | 96 | n/a | 26 | 20 | 1.43 | 49 helpless, 25 lag, dash |
| 9 -> 3 | 156 | 101 (A2 126) | A2 | unrecorded | 156 | 126 | 64 | 24 | 2.22 | up-B, 25 lag, 45 ticks of fireballs, ground attack |
| 3 -> 2 | 178 | 12 (projectile) | A1 | A0 | 32 | 24 | 3 | 65 | 1.81 | aerial, up-B to the moving platform, lag, 31-tick roll |
| 2 -> 6 | 403 | 245 | A2 | unrecorded | n/a | 245 | 70 | 7 | 2.07 | 77 ticks riding the platform, flight, 70 on the wall top |
| 6 -> 8 | 93 | 39 | unrecorded | unrecorded | 54 | 54 | 3 | 25 | 1.06 | 85 ticks of down-B descent |
| 8 -> 1 | 110 | 45 | A1 | unrecorded | 53 | 53 | 7 | 54 | 1.77 | overshoot below the target, double jump back |
| sum | 1,245 | 665 | | | 801 to 908 | | 203 | 205 | 1.64 | |

**What this suggests, and no more.** Against same-class observations the 1,245 has 337 to 444 ticks of room; against G/A2 observations
about 490 over the eight pairs where one exists. Six segments carry almost all of it: the two A0 starts (toward 9 and 3: 25, and 0 to 55
depending on the reference class), the moving-platform approach (3 -> 2: about 150, but the observed bests are an aerial or a projectile
on arrival from a nearby state), the crossing (2 -> 6: 158 from a different start class and platform phase) and the left side (6 -> 8 and
8 -> 1: 39 and 57 against same-class bests). The slow ticks are concentrated in the same places: the three segments with the most room
(toward 3, 2 and 6) hold 137 of the clear's 203 still ticks and 96 of its 205 ticks moving away in x. A local optimiser that only removed
the still and away ticks of those three segments would be worth of the order of 150 to 230 ticks (the two counts overlap in part); one
that reached the same-class bests, 340 to 440. Both numbers are observations about one lineage's data: the pair bests come from other
states and other platform phases, and nothing offline says they are reachable from the 1,245's own states (section 9).

## 5. Chaining

1. **Exact by construction.** Segment k + 1 is optimised from the state P_k || W_k actually reaches. A chained clear is one word sequence
   from tick 0; its claim goes through the lab's existing path (words digest, two fresh-process replays from tick 0 with the verify flags,
   identical chain digests, clocks and break tables), exactly as every lab clear so far.
2. **Forward sweep.** Segments are optimised in order from tick 0. A change to segment k invalidates W_{k+1} ... W_10 as tapes; they are
   re-optimised from the new states, which is the chaining cost: one sweep per upstream change. The order makes the cost bounded (an
   upstream change never touches the segments before it) and makes every intermediate state a verified prefix.
3. **The free splice test.** Before re-optimising W_{k+1}, play the old W_{k+1} from the new state once. Section 1.3 says it survives to the
   next break in about half the cases and rarely further, so it is a one-evaluation test, never a step the plan relies on; when it survives
   it saves a segment's budget.
4. **Which classes to join through.** Not prescribed. The secondary objective (or the measured two-segment time) steers each segment's end
   toward states that its successor can use; the data of section 1.2 says that costs little in most pairs. If the owner prefers a rule, the
   generic one is "a segment's end state may not be in an uninterruptible status unless no breaking candidate avoids it".
5. **Verifiability.** Every intermediate prefix is replayed and digest-checked by the worker at each evaluation (the prefix check); the
   whole clear is verified twice from tick 0 before any claim; the words are the agent's own throughout (the clear's prefix plus words drawn
   by the optimiser from the agent's own distributions).

## 6. Integration: a separate line, or an operator inside the archive search?

| | separate line (own driver, own lab folder, own records) | polishing operator inside the crossing search's archive |
| --- | --- | --- |
| reuse | the worker, the prefix check, the claims and verification path, the lab readiness and caps | all of that plus the archive, its selection, continuation and the end-record store of stage 0 |
| objective | clean: one segment, earliest break, exact dedup, fine diversity key | the archive's objective is the earliest arrival per coarse key; a faster-but-different arrival evicts the state the optimiser was building on (72 to 82 % of replacements were never dispatched; 86 % changed the state materially) |
| comparability | measurable against the archive on equal nights; no change to run 3's contract or explorer | changes the archive's selection and word distribution: run 3's results become incomparable with runs 1 and 2 |
| launch risk | a second launch path to review (the handoff's rule) | one path, but a riskier change to a tool that is about to run its campaign |
| lock-in | works on one lineage's boundaries by construction (the audit's concern); bounded by stating it | the archive's lineages, same concern, less visible |
| cost | one driver (about the size of the trail-lead probe's) plus the generators and tests | the multi-representative cell contract (stage 3 of tier 1) is a prerequisite, or the optimiser's elite is evicted |

**Recommendation.** A separate line for the pilot and the first forward sweep: the question it answers (gain per hour against the archive)
needs the archive untouched as the control. If a sweep produces a verified chained clear, integrate as an operator applied to promising
lineages, on top of the state-aware representatives of tier 1's stage 3, which both lines then need for the same reason.

## 7. Minimal native pilot (November week 1, about one hour of native time)

**Question.** Does optimising one segment from a verified start state gain clearly more per hour than the archive search gains per hour
on the same lineage?

**Setup, all generic.**

- The lineage is the best verified clear at the time (its words, trace and break table are in the lab).
- The segment is chosen by a rule over the agent's own data, not by name: among the clear's segments at most 200 ticks long, the one with
  the largest gap between its time and the fastest observed transition for its pair from the same class; the record states which segment
  the rule selected. (On today's data the rule selects the approach to the moving platform, 178 against 32; the second is the last
  segment, 110 against 53.)
- Start state: the clear's state at the segment's start tick, replayed from tick 0 and checked against the stored record on every
  evaluation. Word budget per candidate: one burst (120 words) plus one continuation burst after a break (the two-segment measurement).
- Method: within-segment Go-Explore (section 2.2) with exact-record merging and the fine diversity key; the first dispatches are the words of
  the pair's three fastest observed transitions played from the start state (expected to fail; one evaluation each). Control: the archive's
  own history on the same lineage, read from run 2's record (three verified improvements in 7.8 hours: 77, 91 and 16 ticks at 22 min, 4 h 15
  and 7 h 21), and, if a second half-hour is available, random restarts (section 2.1) from the same state with the same budget.
- Caps: 60 minutes of wall, 5 processes, a tick cap, memory refusal as in every lab run; writes only under a new lab folder; nothing
  registered; the executable, runtime pins and verify flags of the lab import.

**Measurements, fixed in advance.**

1. Candidates evaluated per hour, and the per-job wall split (wait, prefix, segment, close): the first measurement of the boot-bound claim
   of section 3.1 at a short prefix.
2. The improvement curve: evaluations to the first candidate that breaks the segment's target earlier than the clear does, to a gain of 10 %
   of the segment's time, and the best gain at the end.
3. The class and status of the end state of the best candidate and of the ten best (section 1.2's concern, measured).
4. For every candidate that broke the target: the two-segment time (the continuation burst's break tick, or none), against the clear's own
   two-segment time at that boundary.
5. Exact dedup rate (evaluations whose end record already existed) and the diversity buckets' occupancy, to size the pool for the sweep.
6. If a candidate's two-segment continuation reaches the next break: the whole clear's words with the old tail are replayed once as the free
   splice test, and if that clears, twice from tick 0 as a lab claim.

**Pass criteria (decided now).**

- PASS: within the hour a candidate breaks the segment's target at least 30 ticks earlier than the clear and ends in a class not worse than
  the clear's own end class at that boundary, or at least 60 ticks earlier in any class. 30 ticks is above the archive's mean gain per hour
  on this lineage in run 2 (184 over 7.8 hours) and above every one-tick splice gain; 60 is twice that and about a third of the room the
  table of section 4 shows for the selected segment.
- INCONCLUSIVE: an improvement of 1 to 29 ticks, or 30 or more that ends in a worse class with a two-segment time no better than the
  clear's. A second hour on a second segment (the rule's second choice) is then permitted before the decision.
- FAIL: no candidate breaks the target earlier than the clear within the hour, or the pipeline evaluates fewer than 3,000 candidates in it
  (then the pilot measured throughput, not the method, and the throughput levers come first).

## 8. Staged plan, dependence on the native batched prefix, effort, risks

| stage | content | depends on | effort | checkpoint and stopping rule |
| --- | --- | --- | --- | --- |
| S0 (offline, week 1, zero ticks) | the segment contract and record format; the fine diversity key and exact-merge rule; the generators (random restarts, within-segment Go-Explore, mutate-and-repair; CEM as a second arm); the segment-selection rule; a reader for the pair bests' words; zero-tick tests on a fake backend over the real 1,245 trace; a light review of the launch path | nothing native; the stored end record of stage 0 is not needed (the start state comes from the clear's own trace) | 2 to 3 sessions | tests pass; the review finds no missing path; the pilot's rule and criteria are frozen in the prompt |
| S1 (native pilot, week 1 or 2) | section 7 | the lab import as it is; the committed worker | 1 session + about 1 h native | PASS, INCONCLUSIVE (one more hour), FAIL (line ends with its reasons recorded) |
| S2 (forward sweep) | the sweep tool: ten segments in order, equal budget, the free splice test, two-segment pricing on the elite, the claims path; one night | S1 PASS | 2 sessions + 1 night | a verified chained clear faster than the best verified; else a second night with the budget reallocated by the pilot's improvement curves; no verified chained clear in two nights ends the line |
| S3 (throughput) | revision 2's Python levers measured in a throughput night; the native block prefix as designed in the prefix-cost record, with its four-part equivalence proof | the native block design of November week 1 (decision Q9), independent of S1 | as the prefix-cost record: 1 session + 1 night for revision 2; 3 sessions + build + 1 h native + 1 night for the block | taken only if S1 or S2 show candidates per hour as the binding constraint (improvement still rising at the cap) |
| S4 (integration) | the operator on promising lineages over multi-representative cells, shared with tier 1's stage 3 | S2's result and tier 1's stage-3 decision | 2 sessions | the 2026-11-27 review |

**Dependence on the native batched prefix.** The pilot and the first sweep run on today's pipeline: both arms of the comparison share it,
and the optimiser's candidates are boot-bound, not prefix-bound (section 3). The block prefix becomes necessary for beam-style methods, for
deep-prefix segments once two standbys exist, and for CPU headroom; it is a throughput lever for the line, not a prerequisite of the pilot.

**Risks.** (1) The boot per candidate caps everything at 5,000 to 10,000 evaluations per hour; if a segment needs tens of thousands the
line is too slow, which the pilot's improvement curve shows. (2) Ruggedness: one-tick timing flips outcomes, so CEM-style smoothing may not
converge and the pool-based method may stall on landings. (3) The end-state trade-off may cost more than section 1.2's small gaps suggest
once the chain is real. (4) Segments coupled to a moving object cannot be optimised in isolation from their start phase; the 403-tick
crossing is both the biggest room and the hardest case, and the segment-length cap keeps it out of the pilot deliberately. (5) Lock-in to
one lineage's boundaries (the audit's concern): the line polishes a route family rather than discovering one; stated in every record.
(6) The within-segment pool can grow to tens of thousands of records per segment; traces are kept only for elites and claims. (7) The
per-hour comparison with the archive is noisy (run 2's three improvements were hours apart); the criteria use fixed thresholds, not the
control's realised rate.

## 9. What cannot be determined offline

1. Whether any candidate from the clear's own state at a boundary can reach the pair best observed from another state: the pair bests are
   observations about other states and, for the moving-platform segments, other phases.
2. The evaluations-to-improvement curve of any method on this landscape; section 1.3 says it is rugged at the one-tick scale, not how often
   a fresh tail from a kept state succeeds under the segment objective (the archive's rates were measured under its own weights).
3. The boot's CPU cost, hence candidates per hour under revision 2 and the block (the prefix-cost record's d1).
4. Whether the end-state secondary term is needed: only the measured two-segment time (pilot measurement 4) says.
5. The hold lengths the explorer drew for the fast segments (records merge equal consecutive words), so the CEM initial distributions
   would be approximations.
6. Whether a chained clear of optimised segments stays verifiable under the lab's claim rule when the sweep's last segment ends the
   episode mid-burst (the worker's finish path handles a clear inside a burst today; the sweep adds no new case, but this is asserted, not
   tested).

## 10. Open questions for the owner

1. **Pilot segment rule.** Options: (a) largest gap to the fastest same-class observed transition, segments at most 200 ticks; (b) largest
   share of still and away ticks; (c) the first segment (shortest prefix, cleanest start). Recommendation: (a); it is the room the data
   shows, it excludes the moving-object-coupled crossing, and the record states what it selected.
2. **Objective.** Options: (a) time to the next break only; (b) lexicographic with the generic end-state order; (c) the measured two-segment
   time. Recommendation: (a) as the pilot's primary, with (c) measured on the elite; (b) only enters the sweep's acceptance rule if the pilot
   shows (a)'s best candidates end badly and (c) disagrees with them.
3. **Pilot method.** Options: (a) within-segment Go-Explore with exact dedup; (b) CEM over hold-runs; (c) both in two half-hours.
   Recommendation: (a) for the first hour: it isolates the two changes that distinguish the optimiser from the archive (the objective and the
   fine key) and reuses the mechanism that produced every fast transition so far; (b) as the second hour if (a) is INCONCLUSIVE.
4. **Deduplication key.** Options: (a) exact end record for merging plus a fine bucket for diversity and budget; (b) the archive's key;
   (c) exact only. Recommendation: (a).
5. **Chaining rule.** Options: (a) forward sweep with re-optimisation; (b) the same with the one-evaluation splice test first; (c) end-state
   constraints that keep downstream tapes valid. Recommendation: (b); (c) is the splice probe's failure mode.
6. **Integration.** Options: (a) separate line; (b) operator inside run 3's archive now; (c) separate until a verified chained clear, then an
   operator over multi-representative cells. Recommendation: (c).
7. **Pipeline for the pilot.** Options: (a) today's; (b) after revision 2; (c) after the native block. Recommendation: (a); the pilot's
   question is about the method and both arms share the pipeline; it also delivers the first short-prefix throughput measurement.
8. **Pass thresholds.** Options: (a) 30 ticks with a class not worse, or 60 in any class; (b) the archive's realised gain per hour on the
   night; (c) any verified improvement. Recommendation: (a), with (b) recorded beside it.
9. **Budget split in the sweep.** Options: (a) equal per segment; (b) proportional to the segment's room in the agent's data; (c)
   proportional to the segment's ticks. Recommendation: (a) for the first sweep; (b) afterwards if the improvement curves justify it.
10. **Candidate atom.** Options: (a) hold-runs (word, duration 1 to 16); (b) one word per tick. Recommendation: (a): the agent's fast
    segments have mean runs of 3 to 12.
11. **Use of the agent's own fast segments.** Options: (a) first dispatches and CEM priors; (b) none; (c) as literal tails. Recommendation:
    (a); (c) only as the one-evaluation splice test.
12. **Registration.** Options: (a) lab only until the line's checkpoint; (b) register a chained clear as soon as it beats the registered
    best, through the registered pipeline. Recommendation: (a).
13. **Order against tier 1.** Options: (a) S0 beside stage 0 in week 1, S1 right after run 3's first night (the first checkpoint); (b) S0 and
    S1 only after stage 1's decision; (c) S1 before run 3. Recommendation: (a): S0 is zero-tick and S1 is an hour, and the checkpoint was
    where tier 2 was to be decided.

## Compliance

| constraint | how the design holds it |
| --- | --- |
| zero native ticks in this session | nothing started; three offline scripts over existing records |
| no RNG seed handling | nothing proposed reads, logs, controls or compares RNG; Python experiment seeds only |
| process restart resets the episode; no savestates | every candidate is a fresh process replaying its prefix from tick 0; sections 1.1, 2, 3 |
| tick contract on every tick | the worker's per-tick checks and prefix digest check on every evaluation; unchanged |
| canonical controller words as replay truth | candidates are canonical word sequences; chained clears are one word sequence from tick 0 |
| every claimed clear verified twice from tick 0 | the lab's existing claims path; section 5 |
| no hardcoded routes, coordinates, target ids, directions or census numbers in selection, objectives or rules | the segment rule, objective, keys and criteria use generic quantities (time to the next break, distance to any live target, resource class, status class, jumps left, exact record identity); ids and ticks in this record describe data |
| only the agent's own trajectories | the clear's words and the pair bests' words are the agent's; TAS, recordings and the owner's run never read |
| no code under rl/, tools/, port/, the lab or D: | none written; the pilot's driver is November work |

## Appendix. Working files (Git-ignored, `logs/frs_segment/`)

| file | content |
| --- | --- |
| `scripts/a1_classes.py`, `a1_classes.json` | section 1.2 and 4: start and end classes of the pair bests, the G/A2 gap, the 1,245's segment start classes |
| `scripts/a2_sensitivity.py`, `a2_sensitivity.json` | section 1.3: the splice probe's 198 results by class, offset and gain, divergence delays |
| `scripts/a3_cost.py`, `a3_cost.json` | section 3: per-segment job wall and candidates per hour under four pipeline scenarios |
