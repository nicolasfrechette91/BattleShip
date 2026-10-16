# Fast-route anomaly inventory and first offline scan (2026-10-16)

Design-study record. Offline only: zero native ticks; no game, lab command, suite, launcher or build was started. The record
proposes; it decides nothing and launches nothing. Lab evidence was read from `C:/BattleShip_lab/` read-only (the executable
folder `import/exe/` was skipped); the registered D: folders were not read. Working files (scripts, caches, outputs) are under the
Git-ignored `logs/frs_anomaly/` (appendix A). Checkout at HEAD `dba2381` (main, clean) before and after this session; no
`lab.lock`, no BattleShip or Python process at the start.

Question answered: do the agent's own trajectories already contain anything physically unusual, and can an anomaly detector
(addendum part 4 (a)) start offline on existing lab data in November, or does it need replays?

Short answer:

- About 0.4 % of the agent's experience has per-tick data today (186,652 unique ticks of about 44.1 M burst ticks). It lives in
  495 distinct full trajectories: the verified lab clears, the splice-probe replays (including 57 falls) and the reference clear.
  Every other burst (99.6 %) left only a one-tick end snapshot (the imported rd1 to sd2 archive), a 300-unit cell key (the
  crossing runs) or a per-burst summary. The 133 unreplayed clear claims of crossing run 2 have no per-tick data at all.
- The per-tick records are richer than the earlier summaries suggested: position, both velocities, facing, status id, status
  timer, hitlag, floor and wall line ids, jumps, the collision box, the moving-line group translation, projectile positions,
  the live target mask and the native break positions, and the collision lines themselves (once per trace, read natively).
  Four of the five anomaly classes can therefore run offline on the traces; the fifth (inside/outside geometry) can too but
  needs a region model built from the recorded line types.
- The first generic scan (four tests, thresholds from the data) flagged 117 + 96 + 133 + 9 events. Every flagged event has an
  ordinary reading from the data itself (wall and ledge clamps of rolls, hitlag freezes, launches from rest, landings,
  moving-line carry, fireball breaks, close hits, rare move sequences). Nothing here is a finding: confirming any event needs a
  replay from tick 0, which is November work. No native anomaly flag was ever set.
- A November detector can start offline on the traces (and should, to calibrate its thresholds), but to cover the search's
  experience it must log per tick inside every run, or replay the bursts it wants to inspect. Section 4 lists what to log.

## 1. Inventory

### 1.1 Totals

| quantity | value | source |
|---|---|---|
| lab folders read | 8 (`import`, `smoke_2026-10-14`, `smoke_2026-10-14_attempt1`, `splice_probe_2026-10-14`, `trail_probe_2026-10-14`, `frontier_2026-10-14`, `crossing_2026-10-15`, `crossing_2026-10-15_run2`) | listing |
| bursts (trajectory segments the agent played) | 133,004 = 21,323 (imported rd1 to sd2) + 383 (smoke) + 3,960 (trail) + 37,330 (frontier) + 30,699 (run 1) + 39,309 (run 2) | `bursts.idx.jsonl`, `iterations.jsonl`, `dispatches.jsonl` |
| burst ticks (new experience) | 44,058,343 = 30,063,478 + 53,389 + 548,237 + 6,994,104 + 2,830,407 + 3,568,728 | same, `ticks` / `words_played` / `n` sums |
| ticks simulated including prefix replays, where recorded | run 1 48.39 M, run 2 50.17 M (+3.90 M checks), frontier 21.30 M, trail 3.58 M, smoke 0.60 M | `summary.json` `work` |
| per-tick trace files | 823 (`*.json.gz`), 1,337,615 step rows | `build_cache.py` |
| after dropping r2 replays identical to r1 | 510 traces (313 r2 files, all 313 identical to their r1 by per-tick hash) | `cache_index.json` |
| distinct trajectories with per-tick data | 495 (the reference clear appears 8 times; run 2 stored run 1's best again; 7 pairs in run 1 are the same trajectory verified under two cids) | per-trace hash |
| unique ticks with per-tick data | 186,652 (shared prefixes collapsed by a per-tick state hash) | `scan.py` |
| fraction of burst ticks with per-tick data | 0.42 % | 186,652 / 44,058,343 |
| trajectories with no per-tick data | 132,700 bursts (99.6 %): all 50,495 falls (18,707 + 24,285 + 2,425 + 113 + 4,965), all out-of-words bursts, the 133 unreplayed clear claims | counts above |
| native anomaly flags set (spatial, entity, targets) | 0 of 1,337,615 rows; `link_unmatched` 0; `fighter_valid == 0` 0; tick gaps 0 | `build_cache.py` |
| script run time | about 3.3 minutes in total (inventory 10 s, cache build 162 s, scan 5 s per run, classifier 1 s) | consoles |

### 1.2 Per-tick records (full state, one row per consumed tick)

Only verification and probe traces hold per-tick data. Each trace is one gzip JSON file with `initial` (the state at tick 0,
including the collision lines), `steps` (one record per tick) and `result`. Every step holds five blocks:

| block (contract) | fields per tick |
|---|---|
| `observation` (schema 1) | `position_x`, `position_y`, `air_velocity_x`, `air_velocity_y`, `ground_velocity_x`, `facing_direction`, `ground_air_state`, `fighter_status_id`, `jumps_used`, `targets_remaining`, `time_passed`, `host_frame`, `input_tick`, `game_status`, `btt_active`, `fighter_valid` |
| `spatial` (`btt_spatial_v1`) | `fighter`: `floor_line_id`, `lwall_line_id`, `rwall_line_id`, `ceil_line_id`, `floor_dist`, `carry` [x, y], `coll` [4 values], `mask_curr`, `valid`; `groups` [id, present, status, translate (x, y), speed (x, y), translated]; `target_live_mask`; `target_positions` [10 pairs; a broken target reads (0, 0)]; `camera_bounds`, `map_bounds`, `update_tic`; **`lines` only in `initial`** (20 lines: id, type 0 to 3, group 1 or 2, flags, vertex list) |
| `entity` (`btt_entity_v1`) | `fighter`: `attack_active`, `hitlag_tics`, `hitstun`, `status_total_tics`, `cliff_hold`, `fastfall`, `shield_active`, `jumps_max`; `weapons` [kind, translate (x, y), velocity (x, y), lifetime, attack_state, owned, serial, lr, ga], `weapon_total` |
| `input` (`btt_input_state_v1`) | `stick_x`, `stick_y`, `button_hold`, `button_tap`, `button_release`, `anim_frame`, `anim_speed`, `motion_flag1`, `tics_since_last_z`, `hold_stick_*`, `tap_stick_*` |
| `targets` (`btt_target_identity_v1`) | per target: `id`, `spawn` (x, y, z), `animated`, `break` (x, y, z, native break position), `break_input_tick`, `break_time_passed`, `break_order`; `break_count`, `remaining_mask`, `link_*` checks, `anomaly_flags` |

Trace files and what they cover (rows = step records; unique = ticks not already present in a trace loaded before it):

| folder | files | rows | unique ticks | content |
|---|---|---|---|---|
| `crossing_2026-10-15/run/traces/` | 597 | 970,135 | 11,508 | 298 verified clears (1,429 to about 1,880 ticks) as r1 and r2, plus the reference clear. The clears descend from one seed lineage and share most of their prefix, which is why 298 clears add only 11.5 k unique ticks |
| `crossing_2026-10-15_run2/run/traces/` | 8 | 11,030 | 1,627 | 3 verified clears (1,245, 1,261, 1,352) as r1 and r2, the reference, and run 1's best again |
| `splice_probe_2026-10-14/run/traces/` | 208 | 337,338 | 173,325 | 198 candidate replays from archive cells across rd1 to sd2 (132 words-exhausted, 57 falls, 9 clears), 9 r2 replays, 1 control. The most diverse per-tick data in the lab: the only recorded falls, and prefixes from the whole archive |
| `trail_probe_2026-10-14/run/traces/` | 3 | 5,827 | 112 | 1 verified clear (r1, r2) and the reference |
| `smoke_2026-10-14/` | 5 | 9,515 | 80 | 1 verified clear (r1, r2), the reference twice, the self-check reference |
| `frontier_2026-10-14/run/traces/`, `import/reference/` | 1 + 1 | 3,770 | 0 | the reference clear only |

The splice falls end where the probe stopped submitting words (`final_state` `WaitingForAction`, no `result` block); the fall
tick is in `splice_probe_2026-10-14/run/results.jsonl` (`fall_tick`). The 57 falls are the only per-tick records of a failing
trajectory in the lab.

Collision geometry: every trace's `initial.spatial.lines` holds the same 20 lines (one geometry hash across all 823 traces):
10 of type 0, 5 of type 1, 4 of type 2, 1 of type 3 by the recorded `type` field; 19 in group 1 (static) and 1 in group 2, whose
`translate` and `speed` are recorded every tick (the moving line). Two lines carry `flags` 16384; the meaning of `type` and
`flags` is not recorded anywhere in the lab. The fighter's `coll` is the same four values on every tick of every trace.

### 1.3 Sparse snapshots (one tick per row, no neighbours)

| record | rows | state held | ticks covered |
|---|---|---|---|
| `import/archive/cells.jsonl` | 49,928 cells | `end`: the 17 observation fields at the cell's tick (position, velocities, facing, status id, ground/air, jumps, time, host frame, targets remaining), cell key [bx, by, resource class, mask, floor id], tick `L`, parent, burst, chain and end digests | one tick per cell; 51 distinct status ids; 746 grounded, 49,182 airborne (cells record airborne states by design of the search key) |
| `import/archive/bursts.idx.jsonl` | 21,323 bursts | per burst: `ticks`, `end_reason` (length 16,338 / fall 4,965 / clear 20), `fall_tick`, `reaches` (409,527 entries: tick, cell, kind), `wins` (126,561 entries each with a 17-field `end` snapshot), `res_transitions`, `ground_runs`, session, start cell | one snapshot per win; no neighbours |
| `smoke_2026-10-14/run/archive/` | 50,656 cells / 21,706 bursts | the imported archive plus the smoke run's 728 cells and 383 bursts (a superset copy of `import/archive`) | as above |
| `crossing_2026-10-15/run/cells.jsonl` | 105,870 rows (32,744 new, 73,126 replaced) | key, level, tick, lead, slack, digests, origin, words; **no state values** | none beyond the 300-unit key |
| `crossing_2026-10-15_run2/run/cells.jsonl` | 75,787 rows (4,550 new) | same | none |
| `frontier_2026-10-14/run/frontier/round_*.jsonl`, `starts.jsonl` | 6,779 + 136 | key, level, tick, lead, digests, origin, words | none |
| `splice_probe_2026-10-14/candidates.jsonl` | 198 | `rep_end` (17-field snapshot of the archive cell), `dpos`, `dv`, `same` flags | one tick per candidate |
| `trail_probe_2026-10-14/starts.jsonl` | 198 pairs | key, digests, words of the lead and control starts | none |

### 1.4 Per-burst and per-event summaries (no per-tick state)

| record | rows | what it holds about physics |
|---|---|---|
| `crossing_2026-10-15/run/dispatches.jsonl` | 30,699 | `outcome` (clear 298, fall 18,707, out_of_words 11,694), `ticks`, `words_played`, `start_tick`, `breaks_after_start` [tick, target] (544 events), `levels`, `pace`, `reaches` (count), `kept` cells, continuation decisions, words |
| `crossing_2026-10-15_run2/run/dispatches.jsonl` | 39,309 | same (clear claims 136, fall 24,285, out_of_words 14,888; 587 break events) |
| `frontier_2026-10-14/run/dispatches.jsonl` | 37,330 | same shape plus `candidates` and `seed` (136 seeds; falls 2,425; 6,727 break events) |
| `trail_probe_2026-10-14/run/dispatches.jsonl` | 3,960 | same shape plus lead/control pairing (falls 113; 404 break events) |
| `smoke_2026-10-14/run/iterations.jsonl` | 383 | end reason, ticks, new and replaced cells |
| `verifications.jsonl` (run 1 298, run 2 3, trail 1, smoke 2) | 304 | verdict, `breaks_r1` / `breaks_r2` [tick, target], `clocks_r1` / `clocks_r2`, chains, words |
| `crossing_2026-10-15_run2/run/checks.jsonl` | 3,916 | replay checks of cells (ticks, chain and end-digest equality) |
| `crossing_2026-10-15_run2/run/claims_not_replayed.jsonl` | 133 | clear claims never replayed (words and claimed clock only) |
| `seeds.jsonl` (run 1) | 48 | seed verification verdicts |
| `splice_probe_2026-10-14/run/results.jsonl` | 208 | outcome, `breaks` [tick, target], `fall_tick`, divergence ticks |
| `events.jsonl`, `run_log.jsonl`, `memory.jsonl`, `progress.md`, `report.md`, `summary.json`, `config.json`, `plan.json` | logs and summaries | dispatch and ingest events, memory, configuration; no physics |

Break events with a tick but without per-tick state: 8,262 in the dispatch rows (544 + 587 + 6,727 + 404), plus the mask
changes implied by the imported archive's keys. Break events with per-tick state: 4,208 recorded in traces, 396 unique.

### 1.5 What fraction of the agent's experience can be scanned offline

- Per tick, with neighbours (needed for pass-through, position jumps, velocity jumps, status transitions): 186,652 unique ticks,
  0.42 % of the 44.1 M burst ticks. Of these, 173,325 (93 %) come from the splice probe's 198 replays and only 13,135 from the
  301 verified clears of the crossing runs, because those clears share one lineage.
- One tick without neighbours (positions, velocities, status ids at a cell's end): 49,928 import cells plus 126,561 win snapshots
  (smoke copy: 50,656 and 128,651). These support distribution checks (status ids, positions against the recorded bounds,
  velocity magnitudes) but no between-tick test.
- Breaks: 396 unique with the fighter's and the target's positions; 8,262 more with tick and target id only.
- Nothing per tick for falls except the 57 splice falls, and nothing at all for the 133 unreplayed clear claims.

## 2. Detector needs against what exists

Collision geometry: the native collision lines exist in every trace (`initial.spatial.lines`, 20 lines with group ids), and
the moving line's translation exists per tick (`spatial.groups[].translate`). No cell, dispatch or snapshot record holds any
geometry. This record used no hand-written or stage-specific floor data and did not reuse the E6 floor data; the one generic
geometry use in the scan (the distance from the fighter to the nearest recorded line, section 3) reads the lines from the
traces themselves.

A data check on the recorded line ids (stride-7 sample of unique ticks; distance from the fighter to the line the id names):

| id field | grounded: n, median, q90, max | airborne: n, median, q90, max | reading |
|---|---|---|---|
| `floor_line_id` | 10,760; 0.0; 0.0; 0.0 | 13,667; 1,101.5; 3,202.1; 8,795.5 | a current-contact id when grounded (exactly on the line in every sample), a last-floor id when airborne |
| `lwall_line_id` | 6,829; 1,580.7; 3,484.7; 5,980.8 | 11,292; 1,700.1; 5,216.4; 8,138.2 | a last-contact id, not a current-contact id |
| `rwall_line_id` | 2,377; 1,158.0; 3,247.9; 4,588.4 | 2,811; 2,170.7; 4,344.0; 9,425.4 | same |
| `ceil_line_id` | none | 107; 2,437.8; 7,502.8; 8,929.9 | same |

So wall and ceiling contact cannot be read from the ids alone; it has to be derived from the position, the collision box and
the recorded lines (as the scan did), or logged natively (section 4).

| anomaly class (addendum part 4 (a)) | fields needed | exists offline | missing |
|---|---|---|---|
| collision-line pass-through between ticks | position at t-1 and t, collision box, lines with per-tick group translation, line type and one-way flags | yes, in the 495 traces (lines once per trace; box and translation per tick) | the meaning of `type` and `flags` (not recorded; must be read from the decomp or logged), the point of the body the game tests, whether lines are ever added or removed at run time (the list is recorded once); not run in this session by instruction |
| position jumps | position, velocities, status, hitlag, carry | yes | nothing for the test itself; a wall-contact signal would remove most ordinary flags (section 3, test A) |
| positions inside or outside the geometry | position, lines, `map_bounds`, `camera_bounds` | yes | a region model (which side of each wall is inside) built from the recorded line types; not run |
| impossible velocities or status changes | velocities, status id, `status_total_tics`, hitlag, ground/air state | yes | a per-status reference (which transitions the game allows) if the test is to be more than a rarity count; the checked-in class table gives names and classes only |
| breaks from unusual distances | fighter position, native break position, `attack_active`, weapon positions | yes | attack hitbox positions and sizes (only the `attack_active` flag is recorded), the projectile's hitbox size, the target's collision radius |

For the 99.6 % of bursts without traces, none of the five classes can run offline. Two routes exist: log per tick inside every
run (section 4), or replay selected bursts from tick 0 (the lab already stores every burst's words and its parent chain, so any
burst is replayable; a replay costs the prefix plus the burst, about 1.1 to 1.4 ms per tick in the current prefix path per
`docs/frs_prefix_cost_2026-10-14.md`).

## 3. First offline scan

Scope: the 510 traces (r1 only; the 313 r2 replays were dropped after their per-tick hashes matched r1 exactly), 826,890 rows,
186,652 unique ticks after collapsing shared prefixes. Generic tests only; every threshold is a quantile or a robust z-score
computed from the data. No route, coordinate, target id or tick enters any test; those appear below only as descriptions of
flagged data. Scripts: `logs/frs_anomaly/build_cache.py`, `scan.py`, `classify_events.py` (appendix A); full tables in
`logs/frs_anomaly/scan_report.md`; all flagged events with annotations in `scan_results.json` and `event_classes.json`.

Nothing flagged counts as a finding. Confirming any event needs a replay from tick 0, which is November work.

### 3.1 Test A: position change per tick against the recorded velocity

Method: for each consecutive tick pair in a trace, the residual is the position change minus a velocity predictor. The
predictor is chosen by the data per ground/air class (median absolute residual over a stride-5 sample) among 12 candidates for
x (air velocity or ground velocity times facing, at t or t-1, with or without the carry) and 4 for y. Chosen: x = `air_velocity_x[t]`
in all four classes; y = `air_velocity_y[t]` plus `carry[y]` when grounded on both ticks, `air_velocity_y[t]` otherwise, and
`air_velocity_y[t-1]` on the landing tick. Flag: |residual| above the class's 99.9 % quantile (any non-zero residual where that
quantile is zero). Score: the larger absolute residual in game units (the ratio to the quantile is kept as a column; it explodes
where a class is almost all zeros).

| class (ground/air before -> after) | n | x: q99, q99.9, max, exact-zero share | y: q99, q99.9, max, exact-zero share |
|---|---|---|---|
| grounded -> grounded | 74,122 | 31.5, 67.2, 280.6, 0.875 | 0.0, 0.0, 12.6, 0.997 |
| grounded -> airborne | 1,103 | 11.9, 29.8, 29.8, 0.648 | 0.0, 0.0, 11.1, 0.121 |
| airborne -> grounded | 1,196 | 26.6, 29.8, 29.8, 0.145 | 69.0, 69.8, 83.0, 0.000 |
| airborne -> airborne | 110,226 | 29.8, 93.0, 126.3, 0.134 | 12.6, 144.3, 215.5, 0.379 |

Result: 261 flagged ticks, 117 events (consecutive flagged ticks merged). Classified by the event's own annotations
(`classify_events.py`, first match wins): pinned 21 (position unchanged, a wall id set, on a recorded line), hitlag 18, ledge
clamp 7 (grounded, x only, exactly one recorded collision-box value from a line endpoint), wall-blocked 19 (x unchanged,
a wall id set, one collision-box value from the nearest line), class change 5 (landing or take-off), landing status 19, moving
line 24 (carry recorded and |residual| within the carry), other 4.

The tail below the flag threshold reads the same way. Airborne ticks with |x residual| >= 1: 7,635 of 110,226; 4,361 have the
x position unchanged with a wall id set, 950 are in hitlag, and of the remaining 2,987 all but 3 have a wall id set and 2,310 sit
exactly one collision-box value from the nearest recorded line (partial movement on the tick a wall is met, or sliding along a
sloped wall line). Grounded ticks with |x residual| >= 1: 2,434; 1,499 are x-unchanged with a wall id, 444 are rolls (`EscapeB`,
`EscapeF`), 156 the grounded tornado, 173 landings, 36 status changes.

### 3.2 Test B: velocity jumps not accompanied by a status change

Method: on ticks where the status id and the ground/air state did not change, the per-tick change of the air velocity vector
and of the ground velocity; flag above the class's 99.9 % quantile.

| class | n | air velocity change: median, q90, q99, q99.9, max | ground velocity change: q99, q99.9, max |
|---|---|---|---|
| grounded | 69,922 | 0.0, 2.0, 70.3, 280.6, 280.6 | 24.9, 280.6, 280.6 |
| airborne | 106,432 | 2.4, 5.7, 16.8, 215.5, 226.9 | 0.0, 0.0, 0.0 |

Result: 96 flagged ticks, 96 events, all `M:SpecialHi` with the previous air velocity exactly zero (a rising special launched
from rest a few ticks into its status). None in hitlag.

### 3.3 Test C: status transitions that are rare in the data

Method: count distinct (status before, status after) pairs over unique ticks; rare = count in the lowest decile of transition
counts, or at most 3. Names come from the checked-in class table (labels only).

Result: 57 status ids, 353 distinct transitions over 10,198 unique transition ticks (counts: min 1, median 7, max 634). 133
transitions are rare (81 seen once). They read as rare move sequences (for example `Turn -> AttackS3`, `Run -> Appeal`,
`LandingHeavy -> Dash`), one ceiling stop under the left structure (`JumpAerialF -> StopCeil`, then `StopCeil -> AttackAirStart`
or `AttackAirB`), one fall death (`AttackAirF -> DeadDown`), and one ground-to-air special start (`Turn -> M:SpecialAirLw`, the
fighter leaving the floor by 12.6 units on the first tick). Least-occupied statuses: `AttackS3` 11 ticks, `AttackDash` 15,
`Attack12` 19, `Run` 21. Status ids seen in the import snapshots but never in a trace: 1 id; seen in traces but never in a
snapshot: 7 ids (the snapshots record airborne cell ends almost exclusively).

### 3.4 Test D: fighter-to-target distance at the tick of a break

Method: for each break (a target's `break_input_tick` turning non-zero), the distance from the fighter to the target one tick
before (`d_prev`, both positions from the previous step) and at the break tick (`d_now`, the fighter against the native break
position); flag beyond the 99 % quantile or below the 1 % quantile over unique breaks.

Result: 4,208 recorded breaks, 396 unique. `d_prev`: median 605, q90 1,871, q99 3,417, max 5,044; `d_now`: median 537, q99
3,447, max 5,067. At the break, a projectile was present in 86 of 396 breaks and the attack flag in 324; 4 breaks had neither
flag (all in the fireball statuses `M:SpecialN` / `M:SpecialAirN`, at 162 to 336 units: a projectile spawned and consumed
within the same tick is the ordinary reading). 9 flagged: 4 far (3,435 to 5,044 units, all with a projectile 261 to 335 units
from the target one tick earlier) and 5 near (20 to 88 units, attack flag on).

### 3.5 Ranked flagged events

One line each, most extreme first within each test. "Shared" is the number of traces containing the identical tick. Every
reading below is taken from the recorded annotations; none is a claim.

| rank | test | record (trace), tick | how extreme | what the data shows | what a reviewer should look at |
|---|---|---|---|---|---|
| 1 | A | `splice_probe_2026-10-14/run/traces/c088_cid1531_r1`, 446 (+2) and 8 more rolls | x residual -280.6, 4.2 x q99.9 | `EscapeB`, position fixed at exactly one collision half-width from a wall line, wall id set, roll velocity recorded | a backward roll pressed into a wall; replay the 3 ticks to see the clamp |
| 2 | A | `splice_probe_2026-10-14/run/traces/c101_cid1550_r1`, 459 (+2) and 6 more | x residual -265 to -149 | roll ending exactly one collision half-width (or exactly at the vertex, 3 cases) from a floor line's endpoint | a roll stopped at a ledge |
| 3 | A | `splice_probe_2026-10-14/run/traces/c091_cid1552_r1`, 243 (+3); 17 similar | y residual -215.5, 1.5 x q99.9 | `M:SpecialAirHi` with hitlag 4, a break within one tick, position frozen while the velocity is kept | a rising special hitting a target: hitlag freeze |
| 4 | A | `splice_probe_2026-10-14/run/traces/c161_cid557_r1`, 640; 18 similar | x residual +-126.3 or +-117.4 | `M:SpecialAirHi` rising with x fixed one collision half-width from a wall line, wall id set | a rising special sliding up a wall |
| 5 | A | `crossing_2026-10-15_run2/run/traces/clear_n19643_c9709_k0_r1`, 626 (shared 2) | y residual +4.9 (the grounded-y class is 99.7 % exact zeros) | `EscapeB -> M:SpecialLw` on the moving line: the fighter moved with the line (+17.5) while `carry` reads 0 and the velocity reads +12.6 on this status-change tick; `carry` is non-zero again on the next tick | the only grounded event not covered by a category: check in the replay browser whether the carry field is simply unset on the first tick of a new status |
| 6 | A | `crossing_2026-10-15/run/traces/clear_n10074_c9306_k6_r1`, 850 (+1) (shared 300) | y residual -12.6 | `M:SpecialLw` on the moving line with hitlag 2, velocity y 12.6 held during hitlag, position moving with the line only | the grounded tornado in hitlag on the moving line; ordinary if the hop velocity is held during hitlag |
| 7 | A | `splice_probe_2026-10-14/run/traces/c030_cid6456_r1`, 1560 | y residual +11.1 | `WalkFast -> Fall`, floor id changes from the moving line to a static line, carry recorded | walking off the moving line |
| 8 | B | `crossing_2026-10-15/run/traces/reference`, 114 (shared 122); 95 similar | air velocity change 226.9, 1.05 x q99.9 | `M:SpecialHi`, previous velocity exactly zero | the launch tick of the rising special |
| 9 | C | `crossing_2026-10-15/run/traces/clear_n10303_c16554_k11_r1`, 1512 (shared 17) | transition seen once | `Turn -> M:SpecialAirLw`, grounded to airborne, y +12.6 above the floor line on the first tick, jumps used 0 -> 1 | the aerial tornado started from the ground: the 12.6 hop (the same value as in rows 5 and 6) |
| 10 | C | `crossing_2026-10-15/run/traces/clear_n25371_c9231_k0_r1`, 1442 and 1449 (shared 4) | transitions seen once | `JumpAerialF -> StopCeil`, then `StopCeil -> AttackAirB`, under the left structure | a ceiling stop; check the ceiling line against the recorded box |
| 11 | C | `splice_probe_2026-10-14/run/traces/c091_cid1552_r1`, 824 | transition seen once | `AttackAirF -> DeadDown` at y below the recorded map bound | a fall death during an aerial |
| 12 | D | `crossing_2026-10-15/run/traces/clear_n10074_c9306_k6_r1`, 662 (shared 300) | d_prev 5,044, z 17.9 | target 0 broke while the fighter was 5,044 units away in `AttackAirF`; a projectile was 335 units from the target one tick earlier | a fireball break (the agent's long-range breaks) |
| 13 | D | `splice_probe_2026-10-14/run/traces/c049_cid2704_r1`, 786; and 2 more | d_prev 3,435 to 3,954 | same pattern, projectile 261 to 317 units from the target | fireball breaks |
| 14 | D | `splice_probe_2026-10-14/run/traces/c072_cid2291_r1`, 1774; 4 similar | d_prev 20 to 88, below q1 | `AttackAirB` or `AttackAirF`, attack flag on at the break tick | point-blank hits |
| 15 | D | `splice_probe_2026-10-14/run/traces/c007_cid16729_r1`, 1112; 3 similar | no attack flag and no projectile observed | `M:SpecialAirN` / `M:SpecialN` at 162 to 336 units | a fireball spawned and consumed within one tick; the per-tick record cannot see it |

Expected and observed: the flags are landings, ledge and wall clamps, hitlag freezes, launches, moving-line carry, projectile
breaks and rare move sequences. The two items a reviewer might open first are rows 5 and 9 (the 12.6-unit hop and the zero
`carry` on a status-change tick), both as checks on the diagnostic fields rather than on the game.

## 4. Design notes for November

What the live detector must log per tick that today's records lack:

- A contact record from the native collision step: for each of the four directions, the line id tested this tick and whether
  it blocked, with the pre-resolution candidate position (position plus velocity before clamping). This replaces the
  last-contact ids and makes pass-through a direct test (candidate crossed a line, resolved position did not stop at it).
- The meaning of line `type` and `flags` (once per run, from the decomp), and any run-time change of the line list.
- Attack hitbox positions and sizes while `attack_active`, the projectile hitbox size, and the target collision radius (once).
- A per-tick signed distance to the nearest line of each type (cheap to compute natively, removes the need for a region model).
- The burst's identity on every row: run folder, dispatch `n`, `cid`, `k`, consumed tick, so a row maps to a replayable burst.

Cost: today's JSON trace record is about 3 KB per tick uncompressed (110 to 120 bytes per tick gzipped), written only for
verification replays. The fields above add about 20 floats and 12 ints; a fixed binary layout of 128 to 192 bytes per tick for
every burst would be 5.6 to 8.5 GB over the 44 M burst ticks played so far, or 0.5 to 0.7 GB if kept only for bursts that the
ingest keeps (new or replaced cells, about 7 % of run 1's bursts by its `kept` counts). Offline, the four tests ran at about
6 microseconds per row once cached; JSON parsing dominated (about 0.1 ms per row). A per-burst check at ingest (120 to 480
ticks) costs 1 to 3 ms in Python, below the 2.7 to 5.9 s wall time of a dispatch recorded in `dispatches.jsonl`.

Handing a flagged event to the replay browser: one JSONL row per event with `run_folder`, `n`, `cid`, `k`, the trace path when
one exists, `tick_from` and `tick_to` (about 30 ticks around the event), the test, the score and the data-derived threshold.
The browser already reads `C:/BattleShip_lab` read-only (index schema 5); it needs the burst's words (present in
`dispatches.jsonl` / `cells.jsonl`) plus the parent chain to replay from tick 0, and a "jump to tick" on the row.

## 5. Open questions for the owner (recommendation first)

1. Where should the November detector first run? Recommended: offline on the 495 traces, to calibrate thresholds and the
   category rules of section 3 before any live run. Alternative: straight into run 3 live, with thresholds from this record.
2. How should per-tick data be captured for the 99.6 % of bursts? Recommended: a compact native per-tick log for every burst,
   discarded at ingest unless the burst is kept or flagged. Alternatives: full JSON traces for kept bursts only; replay on demand
   from the stored words (no new logging, but prefix cost per inspected burst).
3. Pass-through test source: Recommended: a native contact record (section 4) so the test is exact. Alternative: an offline
   geometric test on the recorded lines and collision box, which needs the `type` and `flags` semantics first.
4. How are flags handled during a night? Recommended: queued to a JSONL file and reviewed in the replay browser after the
   night; never gating the search. Alternative: a per-night cap that stops the run after N flags of one class.
5. Thresholds: Recommended: recomputed from each run's own data (quantiles and robust z as here), with the previous run's
   values reported beside them. Alternative: frozen values from this record (they would encode this stage).
6. Should rows 5 and 9 of section 3.5 be replayed in the browser? Recommended: optional, low priority (both read as the
   tornado's 12.6-unit hop and an unset carry field on a status-change tick). Alternative: skip until the live detector exists.
7. The 50 MB cache under `logs/frs_anomaly/cache/`: Recommended: keep until the November detector reads it (Git-ignored,
   rebuildable in 162 s). Alternative: delete now.
8. Should the discovery arm (addendum part 4 (b)) reuse these four statistics as its rarity signal? Recommended: not decided
   here; revisit after the live detector has one night of data.

## Appendix A. Working files, commands and checks

Working folder `logs/frs_anomaly/` (Git-ignored, confirmed with `git check-ignore`): `inventory.py` (JSONL inventory, 9.8 s),
`build_cache.py` (per-tick caches from all 823 traces, 162 s), `scan.py` (tests A to D, 5 s), `classify_events.py` (event
categories, 1 s), outputs `inventory.json`, `cache_index.json` (includes the recorded geometry), `scan_results.json`,
`scan_report.md`, `event_classes.json`, consoles, and `cache/` (823 gzip pickles, about 50 MB; binary, rebuildable). All
scripts are standard-library Python run with `python -B`, reading files only; nothing was written to `C:/BattleShip_lab/`, D:,
`rl/`, `tools/`, `port/` or `runs/`. No RNG state or seed was read. The status-name table `rl/data/m7n_action_classes_v2.json`
was read for labels only.

Commands (from the checkout root, Git Bash):

    python -B logs/frs_anomaly/inventory.py
    python -B logs/frs_anomaly/build_cache.py
    python -B logs/frs_anomaly/scan.py
    python -B logs/frs_anomaly/classify_events.py

Line endings: this record and every text working file were checked for CR bytes (all 0; the per-trace cache files are binary
gzip and excluded from the check). Git: `main` at `dba2381`, working tree clean apart from this new record; nothing committed,
pushed, branched or stashed.
