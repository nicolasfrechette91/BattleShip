# Frontier continuation search (2026-10-14)

## Status and result

Lab experiment, exploratory and unregistered, run on the night of 2026-10-14 to 2026-10-15 under the owner's authorisation (the
continuation probe proposed by `docs/frs_trail_probe_2026-10-14.md`, "For the speed line"). HEAD = origin/main = `a69f38a`, clean
before the run apart from the two new tool files; the run changed no tracked file. The question: starting from the ahead-of-pace
states the trail-lead probe recorded, can the agent finish a clear faster than its best verified 1,885 input ticks?

**Answer: no clear at all.** In 355 minutes, 211 rounds and 37,194 bursts from 1,189 distinct states, no burst cleared the stage,
so nothing was verified. The probe's deep states were exhausted early: the level-9 state at 1,816 broke nothing in 16 dispatches,
the level-8 states at 1,482 and 1,489 (294 and 287 ticks ahead of the route) broke nothing in 16 dispatches each, and the one
level-8 state that kept breaking (1,772, 4 ticks ahead) reached level 9 seventeen times in 124 dispatches, never earlier than the
route's own 1,832. The crossing stayed closed: 23 level-7 states, 368 dispatches, 0 breaks, 155 falls. What the search did find is
a far faster right side: new fastest arrivals at every level from 3 to 7, the deepest a level-7 state at tick 493 (846 ticks before
the route's 1,339 and 744 before the fastest level-7 arrival the archive holds), each reproduced in a fresh process at least 16
times with its end record and chain digest checked. Nothing here is a registered claim; no archive was changed; no lab code was
modified (lab code digest `0b248a9e30304325` before, in the run's `config.json`, and after).

## The design as run

- **Starts.** Every level arrival the probe recorded (`levels` in its `dispatches.jsonl`) whose tick is strictly earlier than the
  reference clear's arrival at that level, with its exact prefix: the probe start's base words (lead = the cell's stored prefix,
  control = the route's words up to its arrival, both rebuilt from the import by the probe's own rule and checked against the
  probe's recorded digests) followed by the recorded burst words up to the arrival, re-derived from the probe's key family and
  iteration. 137 such arrivals, 136 distinct prefixes: per level 9: 2, 8: 5, 7: 2, 6: 1, 5: 10, 4: 35, 3: 68, 2: 9, 1: 4. The probe's
  1,482, 1,489 and 1,816 states are among them (1,816 twice: the lead and the control arm of pair 192 arrived at the same cell on
  the same tick with different words).
- **Seed.** The probe's rows carry ticks and words but not the arrival's cell key or end record, which the worker's prefix check
  needs. The run therefore opened with a seed phase: each base prefix replayed and the recorded burst played to the arrival tick
  (every tick under the tick contract), the words played required to equal the recorded ones and the arrival to be a break at the
  recorded level; the reach at that tick gives the key, end record, record digest and chain digest. 136 of 136 seeds reproduced,
  56,385 ticks in 81 s. Deduplicated by cell key keeping the earliest arrival: 73 distinct keys (62 later arrivals dropped, 1
  superseded). The two 1,816 states share a key; one was kept.
- **Rounds.** B = 4 bursts (the lab's CONT arm unchanged: `m8_rd_explore_v1` keyed stream, 120-word segments, at most three
  continuations under the F3 trigger read on the imported archive, never mutated) from each of F = 32 frontier starts; a start with
  a break record gets B + 4. Candidates: the owner's change from the proposal, `--candidates breaks`: a level arrival of a burst that
  is strictly ahead of the reference's arrival at that level (not every reach). Key dedup over the whole run (the earliest arrival
  holds a key; a later arrival is dropped before any state is kept, an earlier one supersedes the holder). Next frontier: 8 slots
  (share 1/4) for the previous frontier's best members, then the round's candidates by (level descending, lead descending), then
  the rest of the previous frontier, then a reserve of remembered states (at most 2,000 prefixes). A start with 16 dispatches
  without a break is retired. Both switches on.
- **Clears.** Every claimed clear would have been replayed twice from tick 0 in fresh processes with the verify flags as soon as a
  worker could be lent (`rl/frs_verify.verify_twice`, the lab runner's path), counting only when both replays agree exactly with each
  other and with the in-run claim. None was claimed.
- **Tool.** `tools/frs/frontier_search.py` (new, LF, 1,649 lines; `plan` is zero-tick, `run` is native) with
  `tools/frs/frontier_search_tests.py` (618 lines; six zero-tick tests, all passing: the start rule on the real probe outputs, the
  prefixes against the recorded reaches, the round logic on stub results, the guard refusals, the verification verdicts, a stub
  end-to-end with verified clears and clean tick-cap and wall-cap stops). Neither `rl/frs_*.py` nor any existing `tools/frs/` file
  was touched.

## The run

| item | value |
|---|---|
| command | `python -B tools/frs/frontier_search.py run --lab-root C:/BattleShip_lab --probe C:/BattleShip_lab/trail_probe_2026-10-14 --out C:/BattleShip_lab/frontier_2026-10-14 --workers 5 --bursts 4 --frontier 32 --share 0.25 --bonus 4 --retire-after 16 --candidates breaks --reserve 2000 --max-ticks 60000000 --max-wall-min 360` |
| time | 2026-10-15 03:27:15 to 09:22:21 UTC (2026-10-14 23:27 to 2026-10-15 05:22 local); 21,305 s wall (open 9 s, search 21,293 s, drain 2 s, close 4 s) |
| readiness at open (registered thresholds) | available 8,604 MB (min 4,096), free commit 11,180 MB (min 10,240), free C: 104.5 GiB, D: 1,621.1 GiB (min 5); no BattleShip process; import pins equal; lab code digest equal to the probe's |
| reference clear at open | replayed exactly in one fresh process: 1,885 / 1,884, chain `a48bc948…`, 2.0 s of stepping |
| dispatches | 37,330 = 136 seeds + 37,194 bursts (10,216 bonus); 0 prefix mismatches, 0 seed failures, 0 lifecycle failures, 0 tick-0 differences, 0 skipped |
| ticks | 21,299,223 in all: prefixes 14,303,234, bursts 6,994,104, reference 1,885, verification 0 (cap 60,000,000 not reached) |
| throughput | 6,312 jobs per hour, 3.60 M ticks per hour, 35.7 rounds per hour; rounds of 87 to 120 s; ticks per job fell from 675 (rounds 1 to 11) to 463 (rounds 201 to 211) as the frontier moved to shallow levels |
| continuation | 22,207 of 55,530 boundaries (40.0 %; the probe's 14.6 %: the frontier's shallow states produce new and shorter reaches more often) |
| states | 1,258 kept (1,189 ever in a frontier), 5,405 later arrivals dropped at held keys, 418 superseded, 1,099 retired, 0 evicted (the reserve never exceeded 43) |
| processes and memory | at most 10 BattleShip processes; main process 605 MB at open, 680 MB peak; tree 4,453 MB private peak; no budget breach; projection 5.9 MB per hour, 323 h to the soft budget |
| status | WALL_CAP (the 360-minute wall minus the close reserve), exit 0; 22 bursts of round 211 left queued |

## The frontier's progress per round

Frontier composition at the start of selected rounds (starts per level), and the best lead ever reached at each level as of
that round (ticks ahead of the reference's arrival at the level; the arrival tick in parentheses). The reference arrives at levels
3 to 9 at 399, 609, 880, 982, 1,339, 1,776 and 1,832.

| round | frontier per level | jobs / advanced / candidates | retired | level 9 | 8 | 7 | 6 | 5 | 4 | 3 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 9: 1, 8: 5, 7: 2, 6: 1, 5: 7, 4: 11, 3: 5 | 128 / 4 / 1 | 0 | 16 (1,816) | 294 (1,482) | 242 (1,097) | 200 (782) | 467 (413) | 355 (254) | 260 (139) |
| 4 | 9: 1, 8: 4, 7: 2, 6: 2, 5: 6, 4: 14, 3: 3 | 140 / 2 / 0 | 25 | 16 | 294 | 242 | 200 | 467 | 355 | 260 |
| 5 | 8: 1, 6: 1, 4: 3, 3: 27 | 140 / 6 / 4 | 2 | 16 | 294 | 242 | 200 | 467 | 355 | 260 |
| 10 | 8: 1, 4: 13, 3: 15, 2: 3 | 152 / 5 / 4 | 6 | 16 | 294 | 242 | 200 | 467 | 355 | 260 |
| 20 | 5: 7, 4: 9, 3: 16 | 160 / 8 / 4 | 6 | 16 | 294 | 242 | 200 | 467 | 372 (237) | 260 |
| 30 | 6: 2, 5: 15, 4: 13, 3: 2 | 156 / 16 / 5 | 10 | 16 | 294 | 242 | 502 (480) | 591 (289) | 425 (184) | 260 |
| 40 | 7: 1, 6: 3, 5: 18, 4: 8, 3: 2 | 172 / 19 / 9 | 2 | 16 | 294 | 701 (638) | 502 | 598 (282) | 425 | 260 |
| 50 | 7: 3, 6: 6, 5: 10, 4: 9, 3: 4 | 172 / 13 / 2 | 3 | 16 | 294 | 701 | 502 | 598 | 425 | 260 |
| 75 | 6: 16, 5: 6, 4: 4, 3: 6 | 160 / 26 / 2 | 10 | 16 | 294 | 701 | 521 (461) | 599 (281) | 425 | 260 |
| 78 | 7: 2, 6: 7, 5: 7, 4: 7, 3: 9 | 164 / 22 / 9 | 3 | 16 | 294 | 846 (493) | 521 | 599 | 425 | 260 |
| 100 | 6: 2, 5: 11, 4: 10, 3: 9 | 184 / 41 / 7 | 7 | 16 | 294 | 846 | 521 | 599 | 425 | 260 |
| 150 | 6: 3, 5: 8, 4: 8, 3: 13 | 164 / 29 / 5 | 4 | 16 | 294 | 846 | 521 | 600 (280) | 425 | 260 |
| 200 | 5: 5, 4: 6, 3: 20, 2: 1 | 196 / 66 / 2 | 3 | 16 | 294 | 846 | 521 | 600 | 425 | 260 |
| 211 | 5: 4, 4: 4, 3: 22, 2: 2 | 194 / 61 / 1 | 5 | 16 | 294 | 846 | 521 | 600 | 425 | 279 (120) |

Reading: the probe's deep states (levels 7 to 9) were all retired by round 4 except the 1,772 state (round 16), and from round 5 the
frontier lived at levels 3 to 6, where breaks are frequent (level 3: 4,654 advances in 14,922 bursts, level 5: 757 in 7,616) and
falls rare. Level-7 states reappeared from round 40 on (23 in all), each retired after its 16 dispatches without a break. From
round 17 the frontier never again held a state above level 7. The budget by start level: level 9: 16 bursts, 8: 192, 7: 368 (1.5 % of
all bursts together); level 6: 3,092; level 5: 7,616; level 4: 8,720; level 3: 14,922; levels 2 and 1: 2,268.

## The deep states (levels 7 to 9)

| state | tick | lead | key (x, y, class) | dispatches | breaks | outcomes | retired |
|---|---|---|---|---|---|---|---|
| level 9 (pair 192, the 1,816 arrival) | 1,816 | 16 | (-12, 2, A2) | 16 | 0 | 12 out of words, 4 falls | round 4 |
| level 8 (pair 170 lead k 0) | 1,482 | 294 | (3, -9, G, floor 4) | 16 | 0 | 16 out of words | round 4 |
| level 8 (pair 183 lead k 3) | 1,489 | 287 | (2, 8, A0) | 16 | 0 | 16 out of words | round 4 |
| level 8 (pair 184 control k 1) | 1,701 | 75 | (3, 2, A1) | 16 | 0 | 16 out of words | round 4 |
| level 8 (pair 193 lead k 4) | 1,775 | 1 | (-11, 10, A2) | 20 | 2 | 18 out of words, 2 falls | round 3 |
| level 8 (pair 192 control k 1) | 1,772 | 4 | (-10, 11, A2) | 124 | 17 | 93 out of words, 31 falls | round 16 |
| level 7 (pair 155 lead k 1) | 1,097 | 242 | (9, 6, A0) | 16 | 0 | 13 out of words, 3 falls | round 4 |
| level 7 (pair 147 lead k 4) | 1,154 | 185 | (9, 4, A0) | 16 | 0 | 16 out of words | round 4 |

The 19 level-9 arrivals all came from the two states 60 ticks from the left targets (1,772 and 1,775): at ticks 1,832 (once, the
route's own tick, pace 0), 1,835, 1,841, 1,846, 1,850, 1,853, 1,857, 1,858, 1,866, 1,867, 1,870, 1,874, 1,876, 1,892, 1,895, 1,903,
1,906, 1,916 and 1,929. None was ahead of the route, so none became a start, and none of those bursts went on to the last target
(all ended out of words). From 1,482 and 1,489 (the two crossings the probe found about 290 ticks ahead) the random continuation
broke nothing in 16 bursts each, as the probe's own continuations after those crossings had broken nothing in their remaining
words.

## The fastest new arrivals

The best lead ever at each level, with the lineage of the deepest. Every state below was dispatched 16 times or more, each time
from a fresh process that replayed its words and checked its end record, record digest and chain digest (0 mismatches in the
run), so each is an exactly reproducible state; its prefix (hex) sits in the frontier file of the round that first selected it.
The archive's fastest arrival per level is the probe record's reading of the import.

| level | reference | archive fastest | this run: tick (lead) | earlier than the archive by | state and first frontier file |
|---|---|---|---|---|---|
| 7 | 1,339 | 1,237 | 493 (846) | 744 | sid 596, `frontier/round_0078.jsonl`, words digest `76d4b1fb…` |
| 6 | 982 | 871 | 461 (521) | 410 | sid 579, `round_0076` |
| 5 | 880 | 433 | 280 (600) | 153 | sid 820, `round_0115` |
| 4 | 609 | 254 | 184 (425) | 70 | sid 241, `round_0022` |
| 3 | 399 | 152 | 120 (279) | 32 | sid 1246, `round_0208` |
| 2 | 120 | 91 | 78 (42) | 13 | sid 589, `round_0077` |
| 1 | 43 | 26 | 28 (15) | no | the probe's own (pair 2 control) |

The level-7 state at 493 descends from the route's own first words: probe start pair 0 control k 7 (level 1 at 29, target 4) →
target 0 at 80 (round 17) → targets 5 at 167 and 7 at 184 in one burst (round 21) → target 9 at 305 (round 73, the parent's
386th dispatch) → target 3 at 461 (round 75) → target 2 at 493 (round 77). The seven targets are the route's seven right-side
targets in a different order, 846 ticks earlier; its live mask (322) is the one every level-7 cell of the archive has, so the
three left targets remain. The state is helpless airborne (class A0) at cell (8, 6).

## Verified clears

None. No burst of the 37,194 ended in a clear, so no replay was run and `verifications.jsonl` does not exist. The only verify-flag
replay of the run is the reference clear at open (exact).

## What limited progress

1. **The crossing, again.** 23 level-7 states (the probe's two and 21 new ones at ticks 493 to 1,297, all with the archive's level-7
   mask) received 368 bursts: 0 breaks, 155 falls (42 %), 213 out of words. The states at the far right and low (x cells 15 to 17,
   y -6 to -8) fell in 48 of 48 bursts; the high right-side states (x 7 to 10, y 4 to 7, mostly helpless after an up-B) ended out of
   words or fell without ever reaching a left target. The probe's crossings came at about 1 per 100 dispatches from right-side lead
   cells; at that rate 368 dispatches would have given about 3 to 4, and gave none (a 2 to 3 % chance under that rate, or a lower rate
   from these states).
2. **The retirement budget was too small for rare events.** With 4 bursts per round and retirement after 16 dispatches without a
   break, every deep state got exactly four rounds. The 1,482 and 1,489 states, whose next break the probe had already shown to be
   rare, were gone by round 4; so were both level-7 probe states. Only a state that kept breaking (1,772) stayed, and its breaks were
   never ahead of the route.
3. **The order then drained the budget into the shallow levels.** Once no deep state was alive, the (level descending, lead
   descending) order and the plentiful candidates at levels 3 to 5 kept the frontier there for 200 rounds: 90 % of the bursts went to
   levels 5 and below, where a break is easy and the pace lead grew to 600 ticks, but every chain that reached level 7 stalled at the
   same wall with the same 16-burst allowance.
4. **The last two targets from the route's own neighbourhood are not faster with random words.** From 1,772 and 1,775 (the route
   reaches level 9 at 1,832 and clears at 1,885), 19 level-9 arrivals in 144 bursts were at best equal to the route's tick and never
   continued to the last target in the same burst.

## Effects of the two switches

- **Break-record bonus (on).** 10,216 of 37,194 bursts (27 %) were bonus bursts, given to 236 starts that had broken a target. They
  advanced a level in 30.0 % of cases against 12.5 % for the base bursts, and at every level with both kinds the bonus share is
  higher (level 8: 11.8 % against 8.9 %; 6: 4.0 against 0.6; 5: 24.7 against 6.5; 4: 17.0 against 4.2; 3: 36.4 against 27.5; 2: 20.0
  against 15.3). The comparison is partly selection (the bonus goes to the starts that have already shown they can break), as the
  crossing study's section 3.2 said; within the run it held.
- **Retirement (on).** 1,099 starts retired after 16 dispatches without a break, having consumed 27,528 bursts (74 % of all); 199 of
  them had a break record earlier. By level: 9: 1, 8: 5, 7: 23, 6: 181, 5: 309, 4: 356, 3: 201, 2: 23. The rule kept the frontier
  moving (the reserve never ran dry; the frontier never emptied) and it is what removed every deep state after 16 bursts; a
  per-level budget would have spent those bursts differently.
- **Candidate mode `breaks` (the owner's change).** Candidates were level arrivals only: 6,465 ahead-of-pace arrivals over the run,
  1,258 kept after key dedup, 5,405 dropped as later arrivals at held keys. The frontier never crowded a deep state out with a
  deeper state's children, as intended; it emptied the deep levels by retirement instead.

## What this means for night 2 and November

**For night 2.** Nothing in the pre-registered design changes (PACE at share 1/2 against CONT; night 2 cannot decide the
crossing). Two readings this run adds to the record's generic list: the crossing rate from fast right-side level-7 states under the
plain explorer is at most about 1 % (0 of 368 here, 2 of 230 lead dispatches in the probe), and a frontier search that promotes
ahead-of-pace breaks drifts to the shallow levels within a few rounds unless the deep levels have their own budget.

**For November (the fast-route line).** Two facts to carry:

1. The right side is far faster than the archive knows. Seven targets by tick 493 (8.2 s; the reference needs 1,339 and the archive's
   fastest arrival at level 7 is 1,237), found by random bursts from a breaks-promoting frontier in a few hours, with new fastest
   arrivals at every level from 3 to 7. These states are not in the archive (no ingest); their prefixes are in the run's frontier
   files and re-derive from the probe start, the key family and the iterations recorded in the dispatch rows. A speed line that
   starts the crossing from such states would have about 850 ticks of slack against 1,885.
2. The crossing is the whole problem, and 16 random bursts per state do not open it. Three directions, proposed and not decided:
   a crossing-focused continuation from the 23 level-7 states (and the 185 level-6 states) with hundreds of dispatches each and no
   retirement, to measure the rate from fast states; the archive's own mechanism, a chain of short prefixes through intermediate
   cells (the `reaches` candidate mode restricted to level 7, so the left-of-wall cells become starts); or PACE's per-level lead on
   an import extended with these arrivals. Whichever is chosen, the search tool needs a per-level budget (or level-aware retirement)
   so that the deepest states are not exhausted in four rounds while shallow breaks absorb the night.

**For the search itself.** The seed re-derivation, the key dedup, the in-run verification lending and the clean wall-cap stop all
worked natively at scale (37,330 jobs, 0 mismatches, 0 guard events, 10 processes at most, 680 MB main process). The dispatches
per hour (6,312) exceeded the plan's projection (5,468) because the frontier's prefixes were short.

## Compliance

- No native RNG seed was read, logged, compared or controlled. No TAS, human recording, owner run or external time was read or used.
- No cell id, coordinate, target id, tick value, route or census number is in the search's code; the start set is derived from the
  probe's rows and the import by the generic rule, and the tests' only literals are the owner's expected counts and the probe
  record's frontier ticks.
- The tick contract was checked on every tick of every prefix and burst (`consumed_tick` = i, `input_tick` = `step_count` = i + 1);
  every prefix reproduced its stored end record, record digest and chain digest (0 mismatches); the tick-0 record equalled the pin
  in every job.
- Process restart resets the episode: every seed, every burst and the reference replay was a fresh process from tick 0 (the lab's
  standby workers, one episode each).
- Writes only under `C:/BattleShip_lab/frontier_2026-10-14/`, through the lab's guard (`rl/frs_guard`); `runs/` was never read; at
  most 10 game processes; readiness at the registered thresholds, never lowered; the lab lock held for the plan and the run and
  released; the lab code untouched: digest `0b248a9e30304325` (34 `rl/` files) at the probe, at the plan, at the run's open and at
  its close.
- New files only (the search, its tests, this record), LF, uncommitted; nothing staged; no commit, push or branch. No application
  was closed.

## Files

Lab folder `C:/BattleShip_lab/frontier_2026-10-14/` (not in the repository):

| file | content |
|---|---|
| `plan.json`, `starts.jsonl` | the zero-tick plan: the 136 starts with their seeds (lengths and digests), the parameters, the throughput fit and projection |
| `run_console.txt` | the run's console |
| `run/config.json`, `run/reference.json` | configuration with readiness values and the lab code digest, the reference replay at open |
| `run/dispatches.jsonl` | one row per job (37,330: 136 seeds with their verdicts, 37,194 bursts), with the burst words in hex |
| `run/rounds.jsonl` | one row per round (212): frontier per level in and out, candidates, retirements, best lead per level |
| `run/frontier/round_NNNN.jsonl` | the frontier each round dispatched from (212 files), every member with its exact prefix (hex), key and record digests |
| `run/progress.md`, `run/report.md`, `run/summary.json` | the morning file (final), the report and the summary |
| `run/run_log.jsonl`, `run/memory.jsonl`, `run/state.json` | the log, the memory samples (707), the last state |
| `run/traces/reference.json.gz` | the reference replay's trace |

Repository (new, untracked): `tools/frs/frontier_search.py`, `tools/frs/frontier_search_tests.py`, this record.
