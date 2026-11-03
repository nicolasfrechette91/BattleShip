# Departure probe: plan (Phase 1, 2026-11-02; updated with Nicolas's answers)

Status: Phase 1 done, with zero native ticks. No build was made, and no game, lab run, search, suite with native ticks or self-check was started. `lab.lock` was not taken. Lab
records and traces were read only; nothing was written in `C:/BattleShip_lab`. Nicolas answered the open questions of the first version (section 9); the tool, the
tests and this plan follow those answers. **Phase 2 is one native lab run and needs Nicolas's explicit go.** This record decides nothing. Its numbers describe the
1,245's records; the tool reads every one of them from those records.

Sources: `docs/project_handoff.md`, `docs/frs_lab_guide.md`, `docs/frs_lab_index.md`, `docs/frs_moving_geometry_timing_2026-10-16.md` (sections 0 to 6),
`docs/rl_decision_soft_reset_2026-11-02.md` (for context), the existing lab tools (`tools/frs/trail_probe.py`, `tools/frs/splice_probe.py`,
`tools/frs/crossing_search_run2.py`, `rl/frs_verify.py`, `rl/frs_guard.py`, `rl/frs_lab.py`, `rl/frs_machine.py`). Lab data read: the verification row and the two
verified traces of the 1,245 (`C:/BattleShip_lab/crossing_2026-10-15_run2/run/`), every lab `verifications.jsonl` (rows only), and the splice probe's and run 2's
replay-timing records (for the cost). The band was computed with `--band`, which reads the other verified clears' `_r1` traces.

## 0. Summary

- **Question:** every traced clear leaves the moving collision group in one band of its cycle. Is that band forced by the geometry, or is it inherited habit?
- **Probe:** take the best verified lab clear, the 1,245 (dispatch 36,236, cell 8692). Replay its words up to a departure tick d, then try exits from d, for every d in a
  window. Each try is one fresh process from tick 0 with the verify flags. Each try is valued by the chained tick, counted from tick 0, of the first break after the
  departure.
- **Derived from the 1,245's own trace** (nothing hardcoded):
  - moving group 2, line 19, moving along y with period P = 300;
  - one contact interval, ticks 539..733; first grounded tick F = 545;
  - departure D = 716 (the exit's onset); airborne from A = 720; floor line off the group from L = 734;
  - baseline B = 1,042, target 6, with B − D = 326;
  - one on-group break, tick 639 (target 2).
- **Window:** 545..716 (172 earlier departures) and 717..1,016 (300 later departures): 472 departure ticks. The 94 departures 545..638 are **pre-break departures**:
  they leave before the on-group break, so they are their own part of the curve and never count as gains. That leaves 378 departures that can count.
- **Band:** the verified clears leave at group phases 77..177 of the 300-tick cycle (296 verified trajectories, 3 departure phases). Of the 378 counted departures, 179
  are inside the band and 199 outside. **All 199 outside the band are later departures (717..915).** Every earlier departure outside the band is a pre-break departure
  (545..615), and every earlier departure after the on-group break (639..716) is inside the band. So with these answers a NOT_FORCED verdict can only come from
  departing later than the clear, never earlier.
- **Plan:** 472 departure ticks times 2 exits (the clear's own exit shifted to d, and K = 1 generic exit from the lab burst generator, the same at every d) gives
  **944 candidates** and 1,352,280 ticks. Candidate-set digest `bfca96f3401e6b5629398f3a414432cd85154cc54abf382834cfc99e0d7ad68f`.
- **Cost:** measured from the splice probe's 207 fresh-process trace replays (5 at once) as 4.08 s + 2.74 ms per tick per slot. Expected native time **25.3 minutes**,
  56 % of the 45-minute cap.
- **(a) and (b)** are answered in section 2 from the record: 720..733 is the fighter airborne above the line, and B − D = 326 contains the timing study's 171-tick
  flight.
- **Tool:** `tools/frs/departure_probe.py` (1,607 lines), with tests in `tools/frs/departure_probe_tests.py` (822 lines; 14/14 pass, zero ticks).

## 1. Method, as implemented

Everything is read from the probed clear's own verified trace (`_r1`), checked against `_r2` and against the verification row. No line id, group id, coordinate,
height, period, target id or tick appears in the tool. A test (`real_source_has_no_record_literal`) checks that no numeric literal in the source equals any of the
29 record values of 10 or more.

The tool reads these from the record:

| quantity | rule (tool function) |
|---|---|
| probed clear | `--clear best` is the fastest VERIFIED clear over every lab `verifications.jsonl`. The Phase 2 command pins it explicitly (`select_clear`). |
| input checks | Both traces were made with the verify flags. Each evaluates to the row's clocks, words digest, final chain and break table. Their m8_rd chains agree at every tick. The break table read from the native target records equals the row's. Any disagreement, or a missing field the method reads, stops the tool (`load_clear`, `required_field_problems`). |
| moving groups | Every group whose recorded `translate` takes more than one value over the trace. The moving axis is the component with the largest range. The group's lines come from the observe-only line table, `initial.spatial.lines[].group` (`moving_groups`). |
| contact intervals | Every maximal run of ticks whose `floor_line_id` is a line of a moving group. All of them are listed. The tool probes the one with the largest ride-or-still count: ticks grounded on the group, or with the position unchanged from the previous tick (`contact_intervals`, `pick_interval`). |
| F, G, A, L | F is the interval's first grounded tick and G its last. A = G + 1 is the first airborne tick. L = C1 + 1 is the first tick whose floor line is off the group. If the fighter is still grounded at G + 1 (no airborne exit) or the interval reaches the end of the trace, the tool stops (`departure_of`). |
| departure D | D = (the first tick of the `fighter_status_id` run that contains G) − 1, never before C0; the tool stops when D < F. The clear's word at index D starts the exit, and the observation at input tick D is the clear's last state on the group before the exit (answer 1). |
| period P | The median gap between successive turning points of the same kind in the group's translation. A record whose gaps differ from the median by more than 1 tick, or that has fewer than two turning points of one kind, stops the tool. The phase origin is the first bottom: phase(t) = (t − origin) mod P (`period_of`). |
| baseline B | The first break after D in the verified clear, by input tick, with the target id that the native target records report. Also recorded: the live mask at B and the end state at B (`baseline_of`). |
| on-group breaks | The clear's breaks with C0 ≤ tick ≤ D (`on_group_breaks`). A departure d is **pre-break** when one of them has a tick after d (`pending_of`). |
| exit run, spans | What the record shows from A to L, and B − D split at the record's own events (`exit_run_of`, `spans_of`; section 2). |

**Window** (answers 2 and 7).

- Earlier departures: every d in [F, D] = 545..716, which is 172 ticks. Each prefix is the clear's words 0..d−1. The contact ticks 539..544 come before the first
  grounded tick (the up-B above the line) and are excluded.
- Later departures: every d in (D, D + P] = 717..1,016, which is 300 ticks. Each prefix is the clear's words 0..D−1, then the canonical neutral word (Track 1 word 0,
  triple (0, 0, 0)) for ticks D..d−1.
- The later window is checked natively once, at open, by a filler reference replay (the words 0..D−1 plus P neutral words). Later d are kept only while the fighter
  stays grounded on the group through d. Later candidates past the first tick off the group are not dispatched and are listed in `not_dispatched.jsonl`. This cut
  **counts as complete**. The measured cut point is reported in `controls.json`, `summary.json` (`later_cut`: the filler's first tick off the group, the last later d,
  the later departure ticks dispatched of planned) and `report.md`.
- Dispatch order: the control (d = D, the clear's exit) goes first. The other departure ticks follow in van der Corput order, so every prefix of the run spreads over
  the whole window. A run stopped by the cap therefore keeps a uniform subsample, although it is still INCONCLUSIVE.

**Pre-break departures** (answer 3). The record shows one on-group break, at 639 (target 2), so d = 545..638 (94 ticks) are pre-break departures; the tool derives
this, it is not written anywhere. Every pre-break candidate is labelled `part = pre_break` in `curve.csv` and reported apart:

- in `summary.json`, `verdict.pre_break`: the d range, the valid count, how many break before B (and how many of those with the baseline's progress), and the
  first-break target histogram, as the native records report it. For each target it records the earliest tick and its d, and how often the target hit is the pending
  on-group target or the baseline's next;
- in `curve_by_type` under `pre_break_clear_exit` and `pre_break_generic`;
- in a separate table in `report.md`.

A pre-break candidate is never counted as a gain, even if its first break is earlier than B and leaves the baseline's progress (`counted_as_gain` is always 0). Pre-break
departures do not count for the band either: "no valid departure outside the band" is read on the counted departures only.

**Exits at each d** (answers 5, 6 and 8).

- (a) The clear's own exit words, D..B−1 (326 words), shifted to start at d. They are followed by the neutral word up to the budget, so the candidate never plays the
  clear's words past B and is never extended toward a clear.
- (g1) One generic exit from the lab burst generator: `rl/frs_archive.stream_words`, the m8_rd_explore_v1 keyed stream, with draw id `1519833e8569ff7f|departure|s1`
  (the clear's words digest, then the key family, then the recorded Python seed 1), iteration 1. The same stream is used at every d (common random numbers). Native
  RNG is untouched.
- Budget: E = ceil(2 × (B − D)) = 652 exit words after d, so the margin equals B − D (326). The earliest departure (d = 545) is followed to tick 1,197 (B + 155). The
  latest (d = 1,016) is followed to tick 1,668.

**Per candidate** (`read_candidate`), one row in `results.jsonl`:

- d, the variant, the side (control, earlier or later), `pre_break` with the pending on-group breaks, and the group's phase, translation and direction at d;
- whether d is in the band;
- the tick contract on every step: consumed_tick = T, input_tick = T + 1, step_count = T + 1, and no consumed-tick mismatch;
- the native action digest of the submitted words;
- the prefix digest: the m8_rd chain at d against the verified clear's chain (earlier d), or against the filler reference (later d);
- the outcome: budget end, fall, ended, error, mismatch, contract, or `clear_not_claimed` (a clear that is recorded but never verified or claimed);
- the first break after d: its chained tick, the target id and every target broken at that tick (as the native target records report them), whether that is the target
  the baseline broke next, whether it is a pending on-group target, the live mask, and the exit ticks;
- `comparable`: the candidate's live mask at that break is a subset of the baseline's at B, so the candidate has broken everything the baseline had;
- `earlier_than_B`, `beats_B` (earlier, comparable, and not pre-break) and the gain;
- the end state at that break: grounded or airborne, status id and class, helpless or not, resource class, the three velocities, position, jumps used, floor line,
  whether it is on the group, and the group's translation;
- the first tick off the group, the last grounded tick on it, and the leave phase;
- the wall, startup and stepping seconds, the slot, and any errors.

**Prefix mismatch.** A candidate whose prefix digest differs is a failed row, and the first differing tick is logged. Its process has already exited, because every
candidate is its own fresh process, so the process is retired and never reused, and the run continues with fresh processes. The third mismatch aborts the run.

**Controls, at open, three fresh processes at once:**

- the 1,245's words, twice. Both replays must be VERIFIED by the lab's own verdict (`rl/frs_verify.verdict`), equal the verified m8_rd chain at every tick, and
  reproduce the row's break table;
- the filler reference. Its chain at D must equal the clear's; its first tick off the group sets the later window's cut.

In the run, the first candidate (d = D, the clear's exit) must reproduce B, its target and the clear's chain at B.

**No claims.** The probe never extends a candidate to a full clear, never verifies or claims a clear, and writes no lab index row. Its output is evidence for run 3
and the segment optimiser. It is not a result.

## 2. Derived from the 1,245 (the dry run's output), with (a) and (b)

| quantity | value |
|---|---|
| probed clear | `crossing_2026-10-15_run2`, n 36,236, cid 8,692, 1,245 words, 1,245 / 1,244; the best of 302 VERIFIED lab clear rows |
| input checks | r1 and r2 both evaluate to the row, are equal per tick, and have 10 breaks with 0 anomalies |
| moving groups | one: group 2, line 19, translation x fixed at 2,700 and y from 1,500 to 3,300; axis y |
| contact intervals | one: 539..733 (195 ticks, 175 riding, 0 still, ride-or-still 175). "Still" is 0 because the platform always moves the fighter. |
| ticks on the interval | C0 539 (airborne up-B above the line), F 545 (first grounded), D 716 (status 227, grounded, floor line 19), S 717 (status 20, the take-off run), G 719 (last grounded), A 720 (status 22, airborne), C1 733, L 734 |
| period | P 300 (bottom and top gaps 300, 300, 300); origin 239 |
| group at C0 / D / A | phase 0, y 1,500.0, rising / phase 177, y 3,146.0, falling / phase 181, y 3,101.1, falling |
| baseline | B 1,042, target 6 (the target the baseline broke next); live mask 258 at B (322 before); end state airborne, status 228 (class special_lw, not helpless), resource A2, velocities (−14.6, 12.6, 6.0), jumps 1 |
| on-group breaks | one, tick 639, target 2; pre-break departures 545..638 (94) |
| flight sign at A, along the axis | +1 (the clear's next flight rises) |

**(a) What happens from 720 (airborne) to 733 (last contact).** The record shows no contact in those ticks. Contact, meaning grounded on the group, ends at G = 719.

- **720..733 (14 ticks):** the fighter is airborne on every tick (`observation.ground_air_state` 1). It is in status 22 (class airborne) for 13 ticks, then status 210
  (class attack_air, an aerial attack) at 733.
- **Motion:** it rises from y 3,480.5 to 4,142.2 (vertical speed falling from +67.7 to +36.5) and moves left from x 2,513.6 to 2,126.2 at −29.8 per tick.
- **The field that shows "contact" at 733** is `spatial.fighter.floor_line_id`, which still reads 19. That field names the floor line under the fighter, airborne or not;
  it is not a contact flag. `spatial.fighter.floor_dist` gives the height above that line: −79.4 at 720 and −916.0 at 733, so at 733 the fighter is 916 units above line
  19. Line 19's extent across the axis is its vertices (±600) plus the group's translation (2,700), that is x 2,100..3,300, and the fighter's x (2,126.2) is still
  inside it.
- **At 734 (L):** x is 2,096.4, outside line 19's extent, so the floor line under the fighter becomes static line 2 (x 1,200..2,100, y −1,500) with floor_dist
  −5,676.3. The fighter is still airborne in status 210.

So C1 = 733 marks where the fighter's horizontal position leaves the line's extent, not where it leaves contact. The 14 ticks from A to C1 belong to the airborne exit.
This is why D is read from the status run that leads to take-off and not from the last floor-line tick (answer 1). The dry run prints this from the record
(`exit run` and `reading` lines).

**(b) B − D = 326 against the timing study's flight of about 170 ticks.** The two numbers measure different spans with different tick definitions, and they agree on the
record (`spans_of`):

| span | ticks | definition | timing study |
|---|---|---|---|
| D → A | 4 | D 716, the tick before the take-off status run (this probe's departure), to A 720, the first airborne tick | not measured |
| A → L | 14 | airborne while `floor_line_id` is still the group's line (part (a)) | counted as ticks on the line (its 195 = C0..C1, 539..733) |
| L → landing | 171 | L 734, the first tick whose floor line is off the group (the study's "leave tick"), to 905, the first grounded tick after it (static line 0; the floor lines under the flight are 2, 4 and 0) | "fly 164 to 172 ticks before the next ground/air change (A 171)" |
| landing → B | 137 | 905 to the break of target 6 at 1,042, with the still run on the far floor inside it | "137 ticks on the static side" |
| sum | 326 | = B − D | |

- The study's "about 170" is L → landing, which is the flight alone, from its leave tick (the floor-line change at 734) to the next ground/air change.
- Its "leave to next break" of 308 is B − L. Its "first contact to next break" of 503 is B − C0.
- This probe's B − D adds the 18 ticks from the onset to L (4 + 14) and the 137 static-side ticks: 4 + 14 + 171 + 137 = 326.
- The study's phrase "the fighter jumps off at 734" names the leave tick. The take-off itself starts at 717 (the take-off status run) and the fighter is airborne from 720.
- The method is unchanged by this.

## 3. Window, variants and counts

| part | d | count | in band / outside |
|---|---|---|---|
| pre-break (earlier, before the on-group break; reported apart) | 545..638 | 94 | 23 (616..638) / 71 (545..615) |
| earlier, after the on-group break | 639..716 | 78 | 78 / 0 |
| later | 717..1,016 | 300 | 101 (916..1,016) / 199 (717..915) |
| counted departures (not pre-break) | | 378 | 179 / 199 |
| all | | 472 | 202 / 270 |

- Variants: `a` (the clear's exit) plus `g1` (K = 1, seed 1). That is 944 candidates (472 × 2) and 1,352,280 ticks.
- Candidate-set digest: `bfca96f3401e6b5629398f3a414432cd85154cc54abf382834cfc99e0d7ad68f`. It covers the clear's digest, D, B, E, P, F, the on-group breaks, and every
  (d, variant, words digest, pre-break flag) in dispatch order.
- `--dry-run --list` prints all 944 candidates. The first in the order are d00716_a, d00716_g1, d00545_a, d00545_g1, d00802_a, d00802_g1, and so on.
- The band's 199 counted departures outside it are all later departures (section 0).

**Band (the tool's rule).** The band is the shortest arc of phase, modulo the measured period, that contains the departure phase of every verified lab clear that
has a stored trace. Each departure is found with the same D rule, the same group id, and each clear's own period measurement.

- Sources: every `*_r1` trace whose action digest matches a VERIFIED row of its run, plus the lab import's reference. The tool reads them at Phase 2 plan time, with
  zero ticks, in about 46 s.
- Result: 296 distinct trajectories, none skipped, with three departure phases:
  - 101, rising (292 trajectories: run 1's lineage);
  - 77, rising (2: the reference lineage);
  - 177, falling (2: the 1,245 and the 1,261).
- Arc: 77..177 (length 100 of 300), with y at departure from 2,436 to 3,146.
- The splice probe's 9 clears have no VERIFIED rows (their double replays are in that probe's own summary), so they are not read. They are 1-tick variants of the
  reference lineage.

## 4. Cost and native time

The per-candidate cost is measured from lab records, not assumed:

| source | shape | measured |
|---|---|---|
| splice probe, 2026-10-14 (`C:/BattleShip_lab/splice_probe_2026-10-14/run/`, the model) | 207 fresh-process replays with the verify flags, 5 at once, traces saved, nothing else running, mean 1,621 ticks | per slot: startup 2.243 s + overhead 1.839 s + 2.741 ms per tick, so 4.081 s + 2.741 ms × ticks; 1.705 s per replay overall (357.1 s wall) |
| crossing run 2 checks (`.../crossing_2026-10-15_run2/run/checks.jsonl`, cross-check) | 3,916 fresh-process check replays, 2 at once beside 5 search workers, no trace save | wall 3.858 s + 1.195 ms × ticks (least squares) |
| run 2 verifications | 3 verify_twice pairs of 1,245 to 1,352 words | 6.9 s per replay, sequential |

The splice probe's shape matches the probe: one fresh process per candidate, 5 threads in one Python process, verify-flag traces captured and saved. Its overhead
also includes a 0.8 s target analysis per replay that the probe does not run (the probe reads the native records directly), so the model is conservative.

Expected native time at 5 slots (`expected_wall`; the dry run prints it):

- open: about 7.5 s (the three control replays at once);
- candidates: 944 × 8.01 slot-s / 5 = 1,512 s;
- total **25.3 minutes, 56 % of the 45-minute cap**.

The cross-check model gives about 17.5 minutes. Non-native time comes on top and does not count toward the cap: building the plan and reading the band (about 1
minute before the first process) and the close (seconds). Traces: 947 files of about 145 to 170 KB each, about 150 MB in the lab root.

The full window fits with K = 1, as chosen. For reference only, K = 0 would be 12.7 minutes and K = 2 would be 37.9 minutes (84 % of the cap). Any change to K, the
seed, the budget factor or a reduction changes the candidate-set digest; re-run the dry run and use the digest it prints.

## 5. Outputs

Everything goes under `C:/BattleShip_lab/departure_probe_2026-11-02/`, through the lab guard. The writer is LF-only and refuses any path outside the lab root.

- `plan.json`: the derivation (groups, intervals, choice, departure with F and L, period, baseline, budget, window with its start rule and the excluded airborne contact
  ticks, on-group breaks, pre-break range, exit run, spans, variants, digest) and the band with its 295 source rows.
- `candidates.jsonl`: one row per planned candidate: label, d, side, variant, prefix reference, pre-break flag with the pending on-group breaks, words digest and ticks
  (no raw words; they re-derive from the plan).
- `refused_<utc>.json`: only on a refusal.
- `run/`:
  - `config.json`: every value and its origin, the git state, the code manifest digest, the probe's sha256, readiness and the cost estimate;
  - `controls.json`: both clear replays and the filler reference, with the filler's first tick off the group and the last later d;
  - `results.jsonl`: one row per candidate (section 1);
  - `curve.csv`: per d and variant, the `part` (control, earlier, later or pre_break), the first-break tick or the outcome, the target, whether it is the on-group
    target or the baseline's next, comparability, the gain, the phase, the band, the end state and the leave facts;
  - `summary.json`: status, verdict (with `pre_break`), counters, native seconds, `later_cut`, the curve by variant type (the earliest first break per d for the clear
    exit and for the generic exit, and the same two for the pre-break part), memory and integrity;
  - `report.md`: a short table (with the later cut and the pre-break counts), the curve for every counted d, the pre-break table, the controls and integrity;
  - `run_log.jsonl`, `state.json`, `memory.jsonl`, and `not_dispatched.jsonl` (only if the filler leaves the group);
  - `traces/`: the 3 controls and one trace per candidate, all kept (answer 9);
  - `vw/`: per-replay work folders, removed after each replay.

## 6. Verdict rules (the tool computes them: `verdict_of`)

A candidate **beats B** when it is not a pre-break departure, its first break after the departure is earlier than B, **and** it leaves at least the baseline's progress:
its live mask at that break is a subset of the baseline's at B. An earlier break that leaves a target live that the baseline had broken is reported as "earlier, with
less progress" and never counted as faster. Pre-break departures are reported apart (section 1) and never counted.

- **INCONCLUSIVE** if any of these holds:
  - the run did not complete its planned window (status other than COMPLETED, or fewer rows than the planned set after the filler cut, which itself counts as
    complete);
  - more than 10 % of the planned candidates failed to run (error, prefix mismatch or tick-contract failure);
  - no band;
  - no valid counted departure outside the band.
- **NOT_FORCED:** at least one counted departure outside the band beats B. The tool reports:
  - the best gain in ticks, with its d, phase, variant, first break and end state;
  - how many candidates and distinct departure ticks beat B, overall and outside the band.
- **FORCED_IN_PROBE:** no counted departure beats B. Outside the band, every valid counted candidate either does not break within the budget, breaks at or after B, or
  breaks earlier with less progress. Each count is reported.
- **IN_BAND_GAIN** (accepted, answer 4): no counted departure outside the band beats B, but one inside it does.
- **Always reported:** the curve. For every d, the first-break tick (or no break) per variant, with the pre-break departures as their own part.

How to read a verdict: (a) plays open-loop words recorded for another state, and g1 is one random stream. Neither searches for the best exit from d. A NOT_FORCED is
direct evidence. A FORCED_IN_PROBE means only that these exits found nothing outside the band, which is why the name says "in probe". With these answers, the outside
of the band is tested only by departing later than the clear (section 0).

## 7. Phase 2

**Command** (Git Bash, from the checkout; one line):

```bash
python -B tools/frs/departure_probe.py run --lab-root C:/BattleShip_lab --out C:/BattleShip_lab/departure_probe_2026-11-02 --clear crossing_2026-10-15_run2:36236:8692 --variants 1 --seed 1 --budget-factor 2 --slots 5 --max-wall-min 45 --expect-digest bfca96f3401e6b5629398f3a414432cd85154cc54abf382834cfc99e0d7ad68f
```

The run takes `lab.lock`, re-derives the plan and refuses when its digest differs from `--expect-digest`. It then reads the band (zero ticks), writes `plan.json`
and `candidates.jsonl`, and opens. It needs no Claude session (lab guide, lessons). The output folder keeps the plan's date whatever day the run starts.

**Readiness checklist:**

1. Nicolas has given an explicit go for Phase 2.
2. The new files are committed by hand: `tools/frs/departure_probe.py`, `tools/frs/departure_probe_tests.py` and this plan. The run records the HEAD, so the HEAD must
   point to the code that ran.
3. `python -B tools/frs/departure_probe_tests.py` gives 14/14 (zero ticks).
4. `python -B tools/frs/departure_probe.py --dry-run --out C:/BattleShip_lab/departure_probe_2026-11-02` prints the digest in the command.
5. The machine is prepared as in lab guide section 1:
   - `wsl --shutdown`, and `wsl --list --running` shows nothing;
   - IntelliJ, the browsers (with Edge background mode), the video editor, the replay viewer, Steam, ChatGPT and idle Claude sessions are closed;
   - sleep is off;
   - `tasklist | grep -ci battleship` prints 0.
6. No other lab workload or native work runs: `C:/BattleShip_lab/lab.lock` is absent, and no suite with native ticks or registered session is running.
7. Readiness at the registered thresholds, which are never lowered: available memory at least 4,096 MB, free commit at least 10,240 MB, and at least 5 GiB free on
   C: and D:. The run needs about 0.15 GB for traces.
8. Optional rehearsal, which costs native ticks: `python -B rl/frs_lab.py selfcheck --lab-root C:/BattleShip_lab`.
9. After the run, back up the lab evidence (lessons: lab evidence lives only on C: until backed up).

**Stop conditions.** Exit 0 = COMPLETED, PARTIAL or MEMORY_BUDGET; 2 = REFUSED; 3 = ABORTED or PROBE_INVALID; 4 = PROBE_INCOMPLETE.

| condition | status, exit | when |
|---|---|---|
| readiness, a running BattleShip, import pins, a held lock, an existing run folder, a different digest, `--max-wall-min` above 45 | REFUSED, 2 | before any process: nothing launched |
| the 1,245 does not replay exactly twice (verdict, chain per tick, break table) | PROBE_INVALID, 3 | open, before any candidate |
| a control cannot run | PROBE_INCOMPLETE, 4 | open |
| the filler reference does not reproduce the clear's prefix at D | PROBE_INVALID, 3 | open |
| the filler leaves the group before D + P | not a stop: the later window is cut there, reported, counted as complete | open |
| the in-run control (d = D, the clear's exit) does not reproduce B, its target and the chain at B | PROBE_INVALID, 3 | first candidate |
| the third prefix-digest mismatch | ABORTED, 3 | stops dispatching; in-flight candidates finish |
| more than 10 % of the planned candidates failed to run | PROBE_INCOMPLETE, 4 | stops dispatching |
| registered memory cap, or more than 10 BattleShip processes in two samples | PROBE_INCOMPLETE, 4 | stops dispatching |
| memory soft budget | MEMORY_BUDGET, 0 | stops dispatching; verdict INCONCLUSIVE |
| guard violation | PROBE_INVALID, 3 | stops dispatching |
| native time reaches 45 min minus the 60 s stop reserve | PARTIAL, 0 | stops dispatching; in-flight candidates (about 8 s each) finish; verdict INCONCLUSIVE |
| a BattleShip process left after the close | PROBE_INCOMPLETE, 4 | close |

## 8. Constraints (restated, not relaxed)

- No native RNG seed or state is inspected, logged, controlled, compared or hashed. The only seed is the Python seed in the burst generator's key family.
- Native changes would be PORT-only and default-off, and non-PORT decomp source stays unchanged. **This task needs no native change, and no lab-tool hook was needed.**
  The probe reuses `rl/frs_lab.real_env` (the replay with the verify flags, readiness, the pins), `rl/frs_verify` (replay, retry, verdict, trace save), `rl/frs_guard`
  (lab root, run folder, guard, lock, LF writer), `rl/frs_machine` (the memory and process sampler) and `rl/frs_archive.stream_words`, all unchanged.
- Process restart resets the episode: every candidate and control is a fresh process from tick 0. The soft reset is decided but not built. It is not used and not
  designed for here.
- Submit tick T, one update, consumed_tick = T, input_tick = T + 1. This is checked on every step of every replay, together with step_count = T + 1.
- Canonical controller words are replay truth (Track 1 btt_s9_b8_v1 = MultiDiscrete([9,8])). Every candidate is a sequence of canonical words, and its native action
  digest is checked.
- The TAS and human recordings are validation-only and never read. The lab guard refuses their path fragments.
- No hardcoded routes, waypoints, cids, coordinates, target ids, directions, orders, periods or census numbers in selection or rules. Everything, including the window
  start, the on-group breaks and the pre-break range, is read from the probed clear's records (tested). The pinned `--clear` in the command identifies the input
  record; it is not a rule.
- Every claimed clear is verified by exact replay from tick 0 (in the lab: twice, in fresh processes, with the verify flags). This probe makes no claims.
- New native runs need Nicolas's explicit go.

## 9. Decisions (Nicolas, 2026-11-02)

1. D = 716, the take-off onset.
2. The earlier window starts at the first grounded tick (545). The airborne up-B contact ticks 539..544 are excluded.
3. Faster = earlier than B and at least the baseline's progress. The departures before the on-group break are their own part of the curve ("pre-break departures"),
   derived from the record. They are reported separately with the break they reach first and never counted as gains.
4. IN_BAND_GAIN is a verdict.
5. K = 1 on the full window.
6. The same generic exit at every departure tick.
7. If the neutral filler cannot keep the fighter on the group, the shortened later window counts as complete; the measured cut point is reported.
8. Exit length 652 words (2 × (B − D)).
9. Every candidate's trace is kept.

Requested additions, done: (a) and (b) are in section 2 and in the dry-run output.

Note for Nicolas, not a question: with answers 2 and 3, every earlier departure outside the band (545..615) is pre-break, so the band can be refuted only by later
departures (717..915).

## 10. Phase 1 verification

- Files: `tools/frs/departure_probe.py` (1,607 lines), `tools/frs/departure_probe_tests.py` (822 lines) and this plan. All three are new; no existing file was modified.
- Unit tests: `python -B tools/frs/departure_probe_tests.py` passes 14/14, all zero ticks.
  - 9 synthetic tests:
    - the derivation on arbitrary ids, period and ticks, including F, L, the window start, the on-group breaks, the pre-break flags, the exit run with line extents, and
      the spans;
    - the refusals on records that cannot support the method;
    - the window, reductions and order;
    - the candidate words;
    - reading a candidate, including pre-break departures that break earlier, with or without the baseline's progress, and the on-group target, never counted;
    - the verdict rules, including the pre-break part;
    - band arcs with wrap-around;
    - the engine end to end with a fake replay: completion, mismatch retirement, the abort at 3, PARTIAL at the cap, FORCED, the invalid control, refusals, the filler
      cut reported and counted as complete, and the pre-break part in the summary, report and curve;
    - the command-line refusals, in child processes.
  - 5 read-only tests on the real records of the 1,245:
    - consistency of r1, r2, the row and the target diagnostic;
    - the geometry read from the record (F, the window, the on-group breaks and pre-break flags, the exit run against the line's extent, and the spans);
    - determinism and the method;
    - a child-process dry run that writes nothing, takes no lock and prints the exit run, the spans and the pre-break range;
    - no record value appears as a literal in the source.
- Dry run: `python -B tools/frs/departure_probe.py --dry-run --band --out C:/BattleShip_lab/departure_probe_2026-11-02`, and `--list` for the 944 rows. Exit 0, zero
  native ticks, nothing written, no lock. `tasklist` shows no BattleShip process.
- CR bytes, checked with `tr -cd '\r' < file | wc -c`: 0 for each of the three files.
