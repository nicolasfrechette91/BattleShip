# Fast-route lab index

One row per lab run (exploratory, unregistered). Written by the runner into the lab root's copy of this file; the owner copies the rows here and commits them weekly. A clear appears only when verified by two exact fresh-process replays from tick 0.

Lab runs are made by `rl/frs_lab.py` (decision Q14 in `docs/rl_decisions_2026-10-14.md`; the runner's design and its approval are in the git-ignored
`logs/frs_prep/phase1_plan.md`; how to run a night by hand: `docs/frs_lab_guide.md`). Lab mode is exploratory: no lab result is a registered claim.
A lab clear can only be registered through the registered path (decision Q10).

## Night 1: pre-registration (written 2026-10-14, before any lab run)

**Purpose: a mechanism and spread check, not an efficacy test.** Night 1 is build order step 3 of `docs/rl_decisions_2026-10-14.md`. It measures
three things: the run-to-run spread of every reported measure, the throughput and memory under lab conditions, and whether continuation behaves
as specified. **No KEEP or DROP decision is taken from night 1.** Decision Q8 sets the KEEP rule: three replicates per arm, and either "not worse
on I3 and better on I2 in every pair" or a faster verified clear in any pair. I2 and I3 arrive with build step 4. The arm difference observed on
night 1 is screening only (review M4: C1 is a mechanism check).

**Arms.** The two arms differ only in continuation.

- **CONTROL** runs sd2's selection `m8_rd_select_v4` unchanged: the harmonic level draw, the v4 cell weights and eligibility E1 to E5, X1 and E7.
  E7 is read at the imported best verified clear (1,885 / 1,884) with M = 24, so L ≤ 1,860, fixed for each run. **E6 is off** (decision Q5).
  Bursts are 120 words, with no continuation.
- **CONT** is CONTROL plus in-process burst continuation:
  - at most three continuations of 120 words each, so at most 480 words;
  - the trigger is the analysis's F3 condition: a reach in the last 20 words whose key is new to the archive or strictly shorter than the
    incumbent (review M1);
  - doom is assigned at ingest, where the whole continued job is one burst.

**Common setup.**

- **Start archive:** a one-time hashed copy of sd2's closing archive in `C:/BattleShip_lab/import/`. Each row records the import manifest's
  digest. No lab run reads `runs/`.
- **Executable:** the pinned executable copy `30a3913b…` with the frozen configuration.
- **Workers:** N = 5, one standby each, at most 10 BattleShip processes.

**Layout.** Six runs of 75 minutes in ABBA order: CONTROL n1r1, CONT n1r1, CONT n1r2, CONTROL n1r2, CONTROL n1r3, CONT n1r3. That is three
replicates per arm. The two runs of a label pair share their keyed draws (common random numbers); different labels draw differently. The
open/close reserves, and therefore the explore minutes, are amended after the smoke run.

**Measures reported for each run** (`summary.json`, `report.md`, one row below):

- **Best verified clear,** as `completion_input_tick` / `completion_time_passed`. A clear counts as verified only when two fresh-process replays
  from tick 0 with the verify flags both reproduce the claim exactly, and its lab words re-derive from their keys.
- **Fastest arrival per level:** the archive's shortest L at each level at the start and the end of the run, with the reference clear's arrival
  beside it.
- **Work:** dispatches, committed jobs, ticks, prefix ticks, burst ticks, new cells, replacements.
- **Throughput** per explore hour: dispatches, ticks, burst ticks, new cells.
- **Continuation:** the rate overall, by start level and by boundary, and the distribution of burst lengths.
- **Memory:** MB at load, bytes per cell, MB per 1,000 new cells, the projected main-process MB at 8, 24 and 48 h of exploration, and the
  peaks.
- **Quarantines and verifications:** every quarantine, and every verification including the in-run re-verification of the reference clear.

**Reading.**

- **Spread:** for each arm, the range of each measure across its three replicates.
- **Arm difference:** the per-pair differences, reported beside dispatches and burst ticks.

Reference figures, written here only and read by no code:

- The review's F3 rate, computed in hindsight, is about a third of length-ended bursts (27 % at level 7, 49 % at level 8). Online, doom is
  unknown at the boundary, so the CONT rate is expected to be higher.
- sd2 ran about 4,500 dispatches per hour at its mix. CONT jobs are longer, so CONT should run fewer dispatches per hour.

**Stops.** The night stops at the first non-zero exit: refused, LAB_INVALID or LAB_INCOMPLETE. MEMORY_BUDGET exits 0 and does not stop it.

## Runs

| run | utc start | arm | label | import | wall min | explore min | status | best verified clear (input / passed) | verified | dispatches | burst ticks | new cells | dispatches / h | peak main MB | MB / 1k new cells | continuation rate | quarantines | folder |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
