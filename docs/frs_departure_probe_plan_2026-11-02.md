# Departure probe: plan (Phase 1, 2026-11-02; updated with Nicolas's answers and, on 2026-11-03, with the review fixes)

Status: Phase 1 done, with zero native ticks. No build was made, and no game, lab run, search, suite with native ticks or self-check was started. `lab.lock` was not taken. Lab
records and traces were read only; nothing was written in `C:/BattleShip_lab`. Nicolas answered the open questions of the first version (section 9); the tool, the
tests and this plan follow those answers. On 2026-11-03 an independent review of commit `46a99cd` returned READY AFTER FIXES; the tool, the tests and this plan now
follow Nicolas's decisions on that review (section 9, 2026-11-03), still with zero native ticks. **Phase 2 is one native lab run and needs Nicolas's explicit go.**
This record decides nothing. Its numbers describe the 1,245's records; the tool reads every one of them from those records.

Sources: `docs/project_handoff.md`, `docs/frs_lab_guide.md`, `docs/frs_lab_index.md`, `docs/frs_moving_geometry_timing_2026-10-16.md` (sections 0 to 6),
`docs/rl_decision_soft_reset_2026-11-02.md` (for context), the existing lab tools (`tools/frs/trail_probe.py`, `tools/frs/splice_probe.py`,
`tools/frs/crossing_search_run2.py`, `rl/frs_verify.py`, `rl/frs_guard.py`, `rl/frs_lab.py`, `rl/frs_machine.py`). Lab data read: the verification row and the two
verified traces of the 1,245 (`C:/BattleShip_lab/crossing_2026-10-15_run2/run/`), every lab `verifications.jsonl` (rows only), and the splice probe's and run 2's
replay-timing records (for the cost). The band was computed with `--band`, which reads the other verified clears' `_r1` traces.

## 0. Summary

- **Question:** every traced clear leaves the moving collision group in one band of its cycle. Is that band forced by the geometry, or is it inherited habit?
- **Probe:** take the best verified lab clear, the 1,245 (dispatch 36,236, cell 8692). Replay its words up to a departure tick d, then try exits from d, for every d in a
  window. Each try is one fresh process from tick 0 with the verify flags. Each try's own departure is measured with the same rule as D, and a try counts only when it
  departs at d. A counted try is valued by its **progress tick**: the first tick after d at which it has broken every target the baseline had broken by B, in any
  order (its live-target mask is a subset of the baseline's at B). It beats B when its progress tick is before B. The first break after d is still reported.
- **Derived from the 1,245's own trace** (nothing hardcoded):
  - moving group 2, line 19, moving along y with period P = 300;
  - one contact interval, ticks 539..733; first grounded tick F = 545;
  - departure D = 716 (the exit's onset); airborne from A = 720; floor line off the group from L = 734;
  - baseline B = 1,042, target 6, with B − D = 326; live mask at B 258 (targets 1 and 8 still live);
  - one on-group break (F ≤ tick ≤ D), tick 639 (target 2).
- **Window:** 545..716 (172 earlier departures) and 717..1,016 (300 later departures): 472 departure ticks. The 94 departures 545..638 are **pre-break departures**:
  they leave before the on-group break. They are labelled, form their own part of the curve and of every table with their own counts, and count like any other
  departure (decision D2 of 2026-11-03): a pre-break try beats B only when its progress tick is before B, so it must also break the on-group target before B.
- **Band:** the verified clears leave at group phases 77..177 of the 300-tick cycle (295 verified clears plus the probed clear; 3 departure phases; every one of the
  296 departures is the tick before a 3-tick status-20 take-off). Of the 472 planned departure ticks, 202 are inside the band and 270 outside: **71 on the earlier
  side (545..615, all pre-break) and 199 on the later side (717..915)**. Every earlier departure after the on-group break (639..716) is inside the band, so the earlier
  side is tested only by pre-break departures. The verdict states which sides were actually tested, counted from the rows that departed at d (S1).
- **Plan:** 472 departure ticks times 2 exits (the clear's own exit shifted to d, and K = 1 generic exit from the lab burst generator, the same at every d) gives
  **944 candidates** and 1,352,280 ticks. Candidate-set digest `bfca96f3401e6b5629398f3a414432cd85154cc54abf382834cfc99e0d7ad68f` (unchanged by the
  2026-11-03 fixes). Band digest `0cb3b2912c00b6e8ea0ce36457efc853ef1aa60541aded6aa09ddf5fe3e20146`.
- **Cost:** measured from the splice probe's 207 fresh-process trace replays (5 at once) as 4.08 s + 2.74 ms per tick per slot. Expected native time **25.3 minutes**,
  56 % of the 45-minute cap.
- **(a) and (b)** are answered in section 2 from the record: 720..733 is the fighter airborne above the line, and B − D = 326 contains the timing study's 171-tick
  flight.
- **Tool:** `tools/frs/departure_probe.py` (1,941 lines), with tests in `tools/frs/departure_probe_tests.py` (1,201 lines; 18/18 pass, zero ticks).

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
| progress rule | A candidate's progress tick is the first tick after d whose live-target mask is a subset of the baseline's live mask at B, read from the record (258 here: targets 1 and 8 live). It beats B when its progress tick is before B (decision D1; `plan.progress_rule`). |
| on-group breaks | The clear's breaks with F ≤ tick ≤ D (decision N1; `on_group_breaks`). A departure d is **pre-break** when one of them has a tick after d (`pending_of`). |
| each candidate's departure | The same rule as D (`departure_core`, shared with D and the band), applied to the candidate's own trace on the contact run that contains d: `departure_tick`, `departure_phase`, and the reason (`at_d`, `later`, `earlier`, or why there is none: `no_exit`, `left_grounded`, ...) (`measured_departure`). The floor-line field is reported apart as `floor_line_leave_tick` and is never used for the band. |
| exit run, spans | What the record shows from A to L, and B − D split at the record's own events (`exit_run_of`, `spans_of`; section 2). |

**Window** (answers 2 and 7).

- Earlier departures: every d in [F, D] = 545..716, which is 172 ticks. Each prefix is the clear's words 0..d−1. The contact ticks 539..544 come before the first
  grounded tick (the up-B above the line) and are excluded.
- Later departures: every d in (D, D + P] = 717..1,016, which is 300 ticks. Each prefix is the clear's words 0..D−1, then the canonical neutral word (Track 1 word 0,
  triple (0, 0, 0)) for ticks D..d−1.
- The later window is checked natively once, at open, by a filler reference replay (the words 0..D−1 plus P neutral words). Later d are kept only while the fighter
  stays grounded on the group through d. Later candidates past the filler's first tick off the group (the first tick that is not both grounded and on a group line:
  the ground-contact rule, like D) are not dispatched and are listed in `not_dispatched.jsonl`. This cut **counts as complete**. The measured cut point is reported in
  `controls.json`, `summary.json` (`later_cut`: the filler's first tick off the group, the last later d, the later departure ticks dispatched of planned) and
  `report.md`.
- Dispatch order: the control (d = D, the clear's exit) goes first. The other departure ticks follow in van der Corput order, so every prefix of the run spreads over
  the whole window. A run stopped by the cap therefore keeps a uniform subsample, although it is still INCONCLUSIVE.

**Pre-break departures** (answer 3, amended by decision D2 of 2026-11-03). The record shows one on-group break, at 639 (target 2), so d = 545..638 (94 ticks) are
pre-break departures; the tool derives this, it is not written anywhere. Every pre-break candidate is labelled `part = pre_break` in `curve.csv` and has its own counts:

- in `summary.json`, `verdict.pre_break`: the d range, the valid count, how many departed at d, how many of those are outside the band, how many break first before B,
  how many beat B (`beats_B`, `counted_as_gain`), and the first-break target histogram, as the native records report it. For each target it records the earliest tick
  and its d, and how often the target hit is the pending on-group target or the baseline's next;
- in the verdict counters (`beats_B_pre_break`, `beats_B_outside_band_pre_break`, `outside_band_pre_break`, `counted_pre_break`) and next to the verdict (S1);
- in `curve_by_type` and `progress_by_type` under `pre_break_clear_exit` and `pre_break_generic`;
- in a separate table in `report.md`.

A pre-break candidate counts like any other departure: it beats B only when its progress tick is before B, which requires it to break the on-group target (here
target 2) before B as well. When its measured departure is outside the band, it counts on the band's **earlier side**.

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
- the tick contract on every step: consumed_tick = T, input_tick = T + 1, step_count = T + 1, and no consumed-tick mismatch; and the native action digest of the
  submitted words. These are read first: any failure is outcome `contract` and ends the run as PROBE_INVALID (decision S6);
- the pin check: `rl/frs_verify` re-hashes the pinned game files beside the executable before every replay, the controls included. A change (pin drift) launches
  nothing; the row is outcome `pin_drift` with the detail, and the run ends as PROBE_INVALID on the first detection, with the S6 treatment (2026-11-03);
- the prefix digest: the m8_rd chain at d against the verified clear's chain (earlier d), or against the filler reference (later d);
- the outcome: budget end, fall, ended, error, mismatch, contract, pin_drift, or `clear_not_claimed` (a clear that is recorded but never verified or claimed);
- the measured departure: `departure_tick`, `departure_phase`, `departure_reason`, `departed_at_d` (only those rows count, S3), and the detail (S, G, A, the status
  of G). `in_band` is read on `departure_phase` (S2). The floor-line facts are `floor_line_leave_tick` and `floor_line_leave_phase`, for reference only;
- the first break after d: its chained tick, the target id and every target broken at that tick (as the native target records report them), whether that is the target
  the baseline broke next, whether it is a pending on-group target, the live mask, and the exit ticks;
- `comparable`: the live mask at that first break is already a subset of the baseline's at B; `earlier_than_B`: the first break is before B;
- `progress_tick`, the targets broken at it, `beats_B` (the progress tick is before B) and the gain B − progress tick (D1);
- the end states at the first break and at the progress tick: grounded or airborne, status id and class, helpless or not, resource class, the three velocities,
  position, jumps used, floor line, whether it is on the group, and the group's translation;
- the wall, startup and stepping seconds, the slot, and any errors.

Each candidate's trace is saved before it is read (N7), so a crash while reading keeps it.

**Prefix mismatch.** A candidate whose prefix digest differs is a failed row, and the first differing tick is logged. Its process has already exited, because every
candidate is its own fresh process, so the process is retired and never reused, and the run continues with fresh processes. The third mismatch aborts the run.

**Controls, at open, three fresh processes at once:**

- the 1,245's words, twice. Both replays must be VERIFIED by the lab's own verdict (`rl/frs_verify.verdict`), equal the verified m8_rd chain at every tick,
  reproduce the row's break table, and keep the full tick contract (step_count included, which `fv.evaluate` does not check);
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

| part | d | count | in band / outside | band side when outside |
|---|---|---|---|---|
| pre-break (earlier, before the on-group break; labelled, own counts) | 545..638 | 94 | 23 (616..638) / 71 (545..615) | earlier |
| earlier, after the on-group break | 639..716 | 78 | 78 / 0 | earlier |
| later | 717..1,016 | 300 | 101 (916..1,016) / 199 (717..915) | later |
| all (every part counts, decision D2) | | 472 | 202 / 270 | earlier 71 (all pre-break), later 199 |

These are planned departure ticks. A row counts only if the candidate actually departs at d (its measured departure, by the D rule, is d; S3). Rows that leave later,
earlier or never are reported as "did not depart at d", with their reasons, and never count toward NOT_FORCED, FORCED_IN_PROBE or IN_BAND_GAIN. How many rows depart at
d, for the clear's exit shifted to d and for the generic exit, is known only after the run; the side statement (S1) reports it.

- Variants: `a` (the clear's exit) plus `g1` (K = 1, seed 1). That is 944 candidates (472 × 2) and 1,352,280 ticks.
- Candidate-set digest: `bfca96f3401e6b5629398f3a414432cd85154cc54abf382834cfc99e0d7ad68f`. It covers the clear's digest, D, B, E, P, F, the on-group breaks, and every
  (d, variant, words digest, pre-break flag) in dispatch order. The 2026-11-03 fixes leave it unchanged: no input of the candidate set changed (N1 moves the
  on-group-break range from [C0, D] to [F, D], which still holds the one break [639, 2], so the pre-break flags are the same; the window, variants, exits and budget are
  unchanged; the contract string `frs_departure_probe_v1` is unchanged).
- `--dry-run --list` prints all 944 candidates. The first in the order are d00716_a, d00716_g1, d00545_a, d00545_g1, d00802_a, d00802_g1, and so on.

**Band (the tool's rule).** The band is the shortest arc of phase, modulo the measured period, that contains the departure phase of every verified lab clear that
has a stored trace. Each departure is found with the same D rule (`departure_core`), the same group id, and each clear's own period measurement.

- Sources: every `*_r1` trace whose action digest matches a VERIFIED row of its run, plus the lab import's reference. Every source must be a verified clear's trace, or
  the tool stops (N2): made with the verify flags, the full tick contract, the native target records agreeing with the live mask, the four clear facts, and the clocks of
  its VERIFIED row (the reference is checked by `rl/frs_verify.load_reference`). The tool reads them at Phase 2 plan time, with zero ticks, in about 49 s.
- Each row records the source, D, the phase, P, G, S, the status of G and G − D (N2). The band also records the probed clear's own row and the distinct
  (status of G, G − D) onsets.
- Result: 295 verified clears plus the probed clear, none skipped, with three departure phases:
  - 101, rising (292 trajectories: run 1's lineage);
  - 77, rising (2: the reference lineage);
  - 177, falling (2: the 1,245 and the 1,261).
- Onsets: all 296 departures are the tick before a 3-tick run of status 20 (G − D = 3), the take-off.
- Arc: 77..177 (length 100 of 300), with y at departure from 2,436 to 3,146.
- Band digest (N3): `0cb3b2912c00b6e8ea0ce36457efc853ef1aa60541aded6aa09ddf5fe3e20146`, a sha256 over the probed clear's row, every source row, every skipped source,
  P and the arc. `--dry-run --band` prints it; the run recomputes the band and refuses a digest other than `--expect-band`.
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
minute before the first process) and the close (seconds).

Traces (N8): 947 files. The 944 candidates average 1,432 steps (1,352,280 planned ticks; a candidate that falls stops early) and the three controls have 3,506 steps
(2 × 1,245 + 1,016). Stored lab traces take 110 to 125 bytes per step (34 traces measured: the 1,245's pair, run 1, run 2 and the splice probe; median 122). That is
about 158 to 179 KB per candidate and **about 150 to 170 MB in all** (about 165 MB at the median), far below the 5 GiB disk threshold.

The full window fits with K = 1, as chosen. For reference only, K = 0 would be 12.7 minutes and K = 2 would be 37.9 minutes (84 % of the cap). Any change to K, the
seed, the budget factor or a reduction changes the candidate-set digest; re-run the dry run and use the digest it prints.

## 5. Outputs

Everything goes under `C:/BattleShip_lab/departure_probe_2026-11-02/`, through the lab guard. The writer is LF-only and refuses any path outside the lab root. The
run refuses an `--out` under the lab's `import/` folder, and an existing `--out` that holds anything but this plan's `plan.json` (same candidate-set and band
digests), `candidates.jsonl` and `refused_*.json` from a refused attempt (S5).

- `plan.json`: the derivation (groups, intervals, choice, departure with F and L, period, baseline, progress rule, budget, window with its start rule and the excluded
  airborne contact ticks, on-group breaks, pre-break range, exit run, spans, variants, digest), the band with its 295 source rows and its digest, and the HEAD.
- `candidates.jsonl`: one row per planned candidate: label, d, side, variant, prefix reference, pre-break flag with the pending on-group breaks, words digest and ticks
  (no raw words; they re-derive from the plan). Written atomically (N11).
- `refused_<utc>.json`: only on a refusal.
- `run/`:
  - `config.json`: every value and its origin, the git state, the HEAD checked at start, the code manifest digest, the probe's sha256, readiness, the band digest and the
    cost estimate;
  - `controls.json`: both clear replays (with their tick contract) and the filler reference, with the filler's first tick off the group and the last later d,
    and any pin drift detected in them;
  - `results.jsonl`: one row per candidate (section 1);
  - `curve.csv`: per d and variant, the `part` (control, earlier, later or pre_break), the outcome, the measured departure (tick, phase, `departed_at_d`, reason), the
    band, the first-break tick, the target, whether it is the on-group target or the baseline's next, comparability, the progress tick, `beats_B`, the gain, the end
    state at the first break and the floor-line leave facts;
  - `summary.json`: status and stop reason, the verdict (with `sides`, `did_not_depart_at_d` and `pre_break`) and `verdict_line`, the HEAD, counters (with
    `contract` and `pin_drift`), native seconds, `later_cut`, the curves by variant type (`curve_by_type`: the earliest first break per counted d;
    `progress_by_type`: the earliest progress tick; each for the clear exit and the generic exit, and the same two for the pre-break part), memory and integrity
    (with every pin drift detected, `integrity.pin_drift`);
  - `report.md`: the status with its stop reason and the HEAD, the verdict line (sides and pre-break counts next to it), a short table (with the later cut, the sides,
    the pre-break and did-not-depart counts, and the contract and pin-drift counters), the curve for every non-pre-break d (first break / progress, or `nd` when no
    row departed at d), the pre-break table, the controls and integrity;
  - `run_log.jsonl`, `state.json`, `memory.jsonl`, and `not_dispatched.jsonl` (only if the filler leaves the group);
  - `traces/`: the 3 controls and one trace per candidate, all kept (answer 9);
  - `vw/`: per-replay work folders, removed after each replay.

## 6. Verdict rules (the tool computes them: `verdict_of`)

A row **counts** when it is valid and **departed at d**: its own departure, measured with the D rule, is d (S2, S3). Its band membership and its band side are read on
that departure: the earlier side for d before D, the later side for d after D (the control, d = D, is in the band by construction). Rows that did not depart at d
(they left later or earlier, or never) are reported as "did not depart at d", with their reasons, and never count.

A counted candidate **beats B** when its **progress tick** is before B: at some tick after d, before B, its live mask is a subset of the baseline's at B, so it has
broken every target the baseline had broken by B, in any order (D1). Its first break after d and that break's target are reported but do not decide. A first break
before B without that progress before B is reported as "earlier, without the baseline's progress" and never counted as faster. Pre-break departures count like any
other (D2): labelled, with their own counts, and on the earlier side when outside the band.

**Integrity failures draw no verdict.** A tick-contract or action-digest failure (S6) and a pin drift (the pinned game files changed during the run, seen by the pin
check before every replay; 2026-11-03) end the run as PROBE_INVALID on the first occurrence or detection, in a control (at open, before any candidate) or in a
candidate. Dispatching stops, in-flight candidates finish and are recorded, and `summary.json` and `report.md` record the status, the stop reason, the counters
(`contract`, `pin_drift`) and, for a pin drift, every detection (`integrity.pin_drift`; `controls.json` for a control). The verdict is then INCONCLUSIVE with the
status as its reason (the first rule below): no verdict is drawn.

- **INCONCLUSIVE** if any of these holds:
  - the run did not complete its planned window (status other than COMPLETED, or fewer rows than the planned set after the filler cut, which itself counts as
    complete);
  - more than 10 % of the planned candidates failed to run (a row with outcome error, mismatch, contract or pin_drift; the last two have already ended the run as
    PROBE_INVALID, above);
  - no band;
  - no counted departure (valid, departed at d) outside the band.
- **NOT_FORCED:** at least one counted departure outside the band beats B. The tool reports:
  - the best gain in ticks (B − progress tick), with its d, side, pre-break flag, measured departure and phase, variant, progress tick and targets, first break and the
    end state at the progress tick;
  - how many candidates and distinct departure ticks beat B, overall and outside the band, and how many of them are pre-break.
- **FORCED_IN_PROBE:** no counted departure beats B. Outside the band, every counted candidate either does not break within the budget, first breaks at or after B, or
  breaks earlier without the baseline's progress before B. Each count is reported.
- **IN_BAND_GAIN** (accepted, answer 4): no counted departure outside the band beats B, but one inside it does.
- **Sides (S1), with every verdict:** the counts of counted outside-band rows on the earlier side (and how many of those are pre-break) and on the later side, and
  which sides were tested: "both sides", "later side only", "earlier side only" or "neither side". This statement is appended to the verdict's reasons automatically,
  and the verdict line (`verdict_line`, at the top of `report.md`) shows the pre-break counts next to it: valid, departed at d, outside the band, beat B.
- **Always reported:** the curve. For every d, the first-break and progress ticks (or none) per variant, with the pre-break departures as their own part, and the
  did-not-depart counts by reason.

How to read a verdict: (a) plays open-loop words recorded for another state, and g1 is one random stream. Neither searches for the best exit from d. A NOT_FORCED is
direct evidence. A FORCED_IN_PROBE means only that these exits found nothing outside the band, which is why the name says "in probe". The earlier side of the band can
be tested only by pre-break departures (545..615), which beat B only if they also break the on-group target before B; the side statement says whether either side was
tested at all. A row counts only when its exit takes off at d, so an exit that does not start the take-off at once is reported apart and narrows what was tested; how
many rows of each exit take off at d is known only after the run.

## 7. Phase 2

**Command** (Git Bash, from the checkout; one line):

```bash
python -B tools/frs/departure_probe.py run --lab-root C:/BattleShip_lab --out C:/BattleShip_lab/departure_probe_2026-11-02 --clear crossing_2026-10-15_run2:36236:8692 --variants 1 --seed 1 --budget-factor 2 --slots 5 --max-wall-min 45 --expect-digest bfca96f3401e6b5629398f3a414432cd85154cc54abf382834cfc99e0d7ad68f --expect-band 0cb3b2912c00b6e8ea0ce36457efc853ef1aa60541aded6aa09ddf5fe3e20146 --expect-head <HEAD after Nicolas commits>
```

`<HEAD after Nicolas commits>` is the full hash printed by `git rev-parse HEAD` after the commit of the three files (the dry run prints it in the command once the
tree is clean). The run checks the required arguments, takes `lab.lock`, refuses a tracked change under `tools/`, `rl/` or `docs/` and a HEAD other than
`--expect-head`, re-derives the plan and refuses when its digest differs from `--expect-digest`, reads the band (zero ticks) and refuses when its digest differs from
`--expect-band`, checks the output folder, writes `plan.json` and `candidates.jsonl`, and opens. It needs no Claude session (lab guide, lessons). The output folder
keeps the plan's date whatever day the run starts.

**Readiness checklist:**

1. Nicolas has given an explicit go for Phase 2.
2. The changed files are committed by hand: `tools/frs/departure_probe.py`, `tools/frs/departure_probe_tests.py` and this plan. The run refuses tracked changes under
   `tools/`, `rl/` and `docs/`, and a HEAD other than `--expect-head`; it records the HEAD in `plan.json`, `config.json`, `summary.json` and `report.md`.
3. `python -B tools/frs/departure_probe_tests.py` gives 18/18 (zero ticks).
4. `python -B tools/frs/departure_probe.py --dry-run --band --out C:/BattleShip_lab/departure_probe_2026-11-02` prints the candidate-set digest and the band digest in
   the command, `git: HEAD <hash>; tracked changes under tools/, rl/, docs/: 0`, and `output folder ...: accepted by the run`.
5. The machine is prepared as in lab guide section 1:
   - `wsl --shutdown`, and `wsl --list --running` shows nothing;
   - IntelliJ, the browsers (with Edge background mode), the video editor, the replay viewer, Steam, ChatGPT and idle Claude sessions are closed;
   - sleep is off;
   - `tasklist | grep -ci battleship` prints 0.
6. No other lab workload or native work runs: `C:/BattleShip_lab/lab.lock` is absent, and no suite with native ticks or registered session is running.
7. Readiness at the registered thresholds, which are never lowered: available memory at least 4,096 MB, free commit at least 10,240 MB, and at least 5 GiB free on
   C: and D:. The run needs about 0.17 GB for traces.
8. Optional rehearsal, which costs native ticks: `python -B rl/frs_lab.py selfcheck --lab-root C:/BattleShip_lab`.
9. After the run, back up the lab evidence (lessons: lab evidence lives only on C: until backed up).

**Stop conditions.** Exit 0 = COMPLETED, PARTIAL or MEMORY_BUDGET; 2 = REFUSED; 3 = ABORTED or PROBE_INVALID; 4 = PROBE_INCOMPLETE.

| condition | status, exit | when |
|---|---|---|
| an argument refusal (`--max-wall-min` above 45, slots outside 1..5, `--variants` below 0, `--budget-factor` below 1, both or neither of `run` and `--dry-run`, an `--out` outside the lab root, under `runs/` or under `import/`, a missing `--expect-digest`, `--expect-band` or `--expect-head`, no lab import) | REFUSED, 2 (N6) | before the lock: nothing written |
| a held lock (a live process), a tracked change under `tools/`, `rl/` or `docs/`, a HEAD other than `--expect-head`, a different candidate-set digest, a different band digest, an existing `--out` with anything but this plan's `plan.json`, `candidates.jsonl` and `refused_*.json` | REFUSED, 2 | before anything is written: nothing launched |
| readiness, a running BattleShip, import pins, an existing run folder | REFUSED, 2 | at open, before any process: nothing launched (`refused_<utc>.json`) |
| a band source that is not a verified clear's trace | stopped, 3 | plan time (also in the dry run): nothing written |
| the 1,245 does not replay exactly twice (verdict, chain per tick, break table, tick contract) | PROBE_INVALID, 3 | open, before any candidate |
| a control cannot run (other than a pin drift) | PROBE_INCOMPLETE, 4 | open |
| the filler reference does not reproduce the clear's prefix at D | PROBE_INVALID, 3 | open |
| the filler leaves the group before D + P | not a stop: the later window is cut there, reported, counted as complete | open |
| the in-run control (d = D, the clear's exit) does not reproduce B, its target and the chain at B | PROBE_INVALID, 3 | first candidate |
| a tick-contract or action-digest failure on any candidate (consumed_tick, input_tick, step_count, a recorded consumed-tick mismatch, the native action digest) | PROBE_INVALID, 3 (S6) | the first occurrence: stops dispatching; in-flight candidates finish |
| a pin drift: the pinned game files beside the executable change during the run (`rl/frs_verify` re-hashes them before every replay; nothing is launched) | PROBE_INVALID, 3 (2026-11-03, as S6) | the first detection, in a control (at open, before any candidate) or a candidate: stops dispatching; in-flight candidates finish; recorded in `summary.json` and `report.md`; no verdict drawn |
| the third prefix-digest mismatch | ABORTED, 3 | stops dispatching; in-flight candidates finish |
| more than 10 % of the planned candidates failed to run (error or prefix mismatch) | PROBE_INCOMPLETE, 4 | stops dispatching |
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
- Submit tick T, one update, consumed_tick = T, input_tick = T + 1. This is checked on every step of every replay, together with step_count = T + 1; any failure
  ends the run as PROBE_INVALID.
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

**Decisions of 2026-11-03 (Nicolas, on the independent review of `46a99cd`, verdict READY AFTER FIXES), all applied:**

- D1 (review S4): "at least the baseline's progress" means that by some tick after d, the candidate's set of broken targets includes every target the baseline had
  broken by B, in any order. `progress_tick` = the first tick after d whose live-target mask is a subset of the baseline's at B; a candidate beats B when
  `progress_tick` < B. The first break and its target stay reported. This amends answer 3's "faster".
- D2: pre-break departures can count as gains, only if `progress_tick` < B (so the on-group break must happen later too). They stay labelled, their own part of the
  curve and of every table, with their own counts, and count toward the band's earlier side when their measured departure is outside the band. This amends answer 3's
  "never counted as gains".
- S1: the verdict states which sides of the band were testable, from the counted outside-band rows (earlier side, of them pre-break, later side), automatically, with
  the pre-break counts next to it.
- S2: each candidate's own departure is measured with the D rule (`departure_tick`, `departure_phase`), used for every band decision; the floor-line field is renamed
  `floor_line_leave_tick` (`floor_line_leave_phase`).
- S3: a row counts as an outside-band test only when its measured departure is outside the band; rows that did not depart at d are reported apart and never count.
- S5: an existing `--out` may hold only this plan's `plan.json`, `candidates.jsonl` and `refused_*.json`; an `--out` under `import/` is refused.
- S6: a tick-contract or action-digest failure ends the run as PROBE_INVALID on the first occurrence.
- N1: on-group breaks over [F, D]. N2: band rows record G, S, the status of G and G − D; band sources must be verified clears. N3: `--expect-band`. N4: the literal test
  is kept; a synthetic `band_of` test is added. N5: a dirty tree (tracked changes under `tools/`, `rl/`, `docs/`) or a HEAD other than the required `--expect-head` is
  refused; the HEAD is recorded. N6: argument refusals exit 2. N7: each trace is saved before it is read. N8: the trace-size estimate (section 4). N9: the unreachable
  branch is removed; `--stride` and `--half` are not options (the reductions stay plan text). N11: `candidates.jsonl` is written atomically.
- Pin drift (follow-up, 2026-11-03): if the pinned game files change during the run (the existing pin check before every replay detects it), the run ends as
  PROBE_INVALID on the first detection, with the S6 treatment: recorded in `summary.json` and `report.md`, no verdict drawn.

Note for Nicolas, not a question: with answer 2 and D2, the earlier side outside the band (545..615) is tested only by pre-break departures, which beat B only if they
also break the on-group target (target 2) before B. The later side (717..915) is tested by departing later than the clear. The band's later edge is the 1,245's own
departure phase (177).

## 10. Phase 1 verification

- Files (2026-11-03): `tools/frs/departure_probe.py` (1,941 lines), `tools/frs/departure_probe_tests.py` (1,201 lines) and this plan, changed in place from
  `46a99cd`. No other file was modified; no shared lab module was changed.
- Unit tests: `python -B tools/frs/departure_probe_tests.py` passes 18/18, all zero ticks.
  - 13 synthetic tests:
    - the derivation on arbitrary ids, period and ticks, including F, L, the window start, the on-group breaks over [F, D] (a break before F is not one), the
      pre-break flags, the progress rule's mask, the exit run with line extents, and the spans;
    - the refusals on records that cannot support the method;
    - the full window (no reductions) and the order;
    - the candidate words;
    - reading a candidate: the measured departure (the control departs at D; a candidate held on the group departs later and one that never leaves has none, both
      reported as not departing at d), the progress tick (another target first, then the baseline's, before B, beats B), a pre-break departure that reaches the
      baseline's progress before B (counted, labelled pre-break) and ones that do not, and the contract failures (consumed tick, step_count, action digest, a recorded
      mismatch read before the prefix digest);
    - the verdict rules: D1, D2, S3 (rows that did not depart at d never count), the side statement (both, later only, earlier only, neither) with the pre-break counts
      next to the verdict, the incomplete-run rules, and the curves;
    - band arcs with wrap-around;
    - `band_of` on a synthetic lab with distinct departures: rows with D, phase, G, S, the status of G and G − D, a wrapping arc, a duplicate counted once, a clear
      without the group and one with another period skipped, the band digest, and the refusal of a source that is not a verified clear's trace;
    - the engine end to end with a fake replay: completion, mismatch retirement, the abort at 3, PARTIAL at the cap, FORCED, the invalid clear control, refusals, the
      filler cut reported and counted as complete, rows not departing at d reported apart, the sides and HEAD in the report;
    - the engine stops: the in-run control not reproducing B (PROBE_INVALID), one tick-contract failure (PROBE_INVALID on the first occurrence), more than 10 %
      failures (PROBE_INCOMPLETE, verdict INCONCLUSIVE), and a pre-break gain counted and labelled in the curve and the report;
    - a pin drift with a fake replay that raises the pin check's error from a given call on: after six candidates, PROBE_INVALID on the first detection (dispatching
      stops, only the in-flight candidates finish, each detection a `pin_drift` row), verdict INCONCLUSIVE, recorded in `summary.json` (status, stop reason,
      counter, `integrity.pin_drift`) and `report.md`; before the controls, PROBE_INVALID at open (not PROBE_INCOMPLETE), no candidate dispatched, the detections in
      `controls.json`;
    - the run guards as functions: the output-folder rule (import/, a refused attempt's files accepted, another plan, another band, run/, any other file) and the git
      rule (wrong HEAD, short hash, dirty tree, unreadable state);
    - the command-line refusals, in child processes, all exit 2: the cap, slots, run with --dry-run, `--stride` and `--half` not options, an `--out` outside the lab
      root, under runs/ or under import/, missing expected digests and HEAD, no import, a lock held by a live process, a wrong HEAD (the real checkout), a dirty tree, a
      different candidate set, a different band, an existing `--out` with another file; and the dry run printing the band digest only with `--band`.
  - 5 read-only tests on the real records of the 1,245:
    - consistency of r1, r2, the row and the target diagnostic;
    - the geometry read from the record (F, the window, the on-group breaks over [F, D] and pre-break flags, the candidate departure rule measuring D on the clear
      itself, the exit run against the line's extent, and the spans);
    - determinism and the method;
    - a child-process dry run that writes nothing, takes no lock and prints the exit run, the spans, the pre-break range, the progress rule, the git state, the
      output-folder check and the command with `--expect-band` and `--expect-head`;
    - no record value appears as a literal in the source (unchanged).
- Dry run: `python -B tools/frs/departure_probe.py --dry-run --band --out C:/BattleShip_lab/departure_probe_2026-11-02`. Exit 0 in 49 s, zero native ticks, nothing
  written, no lock. Candidate-set digest `bfca96f3…d7ad68f` (unchanged), band digest `0cb3b291…e3e20146`, expected native time 25.3 minutes. `tasklist` shows no
  BattleShip process.
- CR bytes, checked with `tr -cd '\r' < file | wc -c`: 0 for each of the three files.
