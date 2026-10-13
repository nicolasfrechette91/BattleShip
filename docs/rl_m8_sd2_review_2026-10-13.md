# M8-sd2 review (2026-10-13)

**Status: read-only review; zero native ticks.** Nothing was launched, prepared, trained, committed, pushed or branched. No tracked file was
modified; nothing under `runs/` or on D: changed (D: was read, including one independent re-hash of the 2026-09-28 base backup). The only new
files are this record and the working files under the Git-ignored `logs/m8_sd2_review2/` (scratch scripts under `scripts/`, their outputs beside
them). The checkout is `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, branch `main`, HEAD = `origin/main` =
`2efaaea5df9a2c3ee0b759a4d61cff499fa5ad0c` ("Add the results of the second speed-discovery search"), clean with nothing staged at the start;
`docs/rl_m8_sd2_approval.json` (blob `b2ae42db`) and `docs/rl_m8_sd2_results_2026-10-12.md` (blob `e5a3ce26`) are committed at HEAD.

**Why this review exists.** sd2 ended PROGRESS under `m8_sd2_rule_v1` with a verified clear at 1,885 / 1,884 (cid 1360) against the reference
2,086 / 2,085, line status `SD3_AFTER_REVIEW_NEW_REFERENCE`: the new reference is 1,885, and the line rule requires a written review before any
sd3. This is that review. It decides nothing by itself; section 8 lists the decisions for the owner.

**What was read.** `CLAUDE.md`; `docs/rl_m8_sd2_results_2026-10-12.md`, `docs/rl_m8_sd2_prep_2026-10-12.md`, `docs/rl_m8_sd2_proposal_2026-10-12.md`
and `docs/rl_m8_sd1_results_2026-10-11.md` in full; `docs/rl_runbook.md` sections 2, 6 and 7 (sections 1.4, P7, P9, P14 and the S3 fingerprint are
superseded by `docs/rl_m9_g3_progression_fix_2026-10-08.md`); `docs/rl_m8_rd3_stop_review_2026-10-03.md` (the model for this review); every file
under `logs/m8_sd2_run/` (Part B, the launch path, the post-run checks, the machine samples) and the pre-launch review note
`logs/m8_sd2_review/review_2026-10-12.md`; the sd2 run tree `runs/m8_rd_sd2/` (read only: `archive/`, `base/`, `sessions/sd2/*`, the three route
traces); sd1's and rd4's session records for comparison; `rl/m8_sd2_*.py`, `tools/m8_sd2/*`, and the sd1, rd4 and rd archive and run modules they
build on (`m8_sd1_select`, `m8_rd4_select`, `m8_rd_archive`, `m8_rd_run`, `m8_rd2_report`, `m8_rd_worker`, `rl/tools/runs_backup.py`); the D:
verification records of the base backup and of every increment. Not read, by rule: the TAS, the crossing fixtures, the human recordings; no ROM
content; no RNG state anywhere.

**How the figures were produced.** Six scratch scripts under `logs/m8_sd2_review2/scripts/`, every one run with `python -B`, reading only:
`missing_set_check.py` (the base re-hash's missing set against the increments' manifests), `base_rehash.py` (the independent re-hash of the base
backup, standard library only), `lineage.py` (cid 1360's exact burst chain and the per-level census from the archive files), `census_v4.py` and
the leg census (exact v4 eligibility and analytic selection through the archive's own loader `Archive6.read_dir`, at the old and the new bound),
`audit_timing.py` (the six-part audit timed once). The loader reproduced the session's own close figure (29,136 v4-eligible cells at the bound
2,061), which validates the census. Every number below that is not in a cited record comes from these outputs.

## 0. Short answer

1. **The `post_run_checks.py` FAIL is a defect of the tool's scope, confirmed in every part** (section 1). The base backup's record names the whole
   `runs/` folder as its source; `registered_increments` resolves that source relative to `runs/` and gets `.`, which is not an error, so the base
   is enumerated as an increment and compared file for file with today's `runs/`. The 69,450 "missing" paths are exactly the union of the twenty
   per-tree increments' manifests (69,450 paths, equal as sets, per tree 5,163 + 9,103 + 2,286 + 4,143 + 11,023 + 166 + 62 + 77 + 93 + 2,740 +
   1,393 + 9,779 + 4,935 + 4,478 + 3,779 + 3,486 + 4,302 + 2,187 + 130 + 125), none of them is in the base manifest, and 377,359 + 69,450 = 446,809
   is today's regular-file count. An independent Python re-hash of all 377,359 base rows against both the backup and `runs/` found 0
   mismatches. sd1 never met the problem because its post-run re-hash was a hand loop over eighteen named increments. The fix belongs in a new
   sd3 tool, not in sd2's pinned one; section 1.4 gives it and the tests.
2. **The 3.1 s "margin" was a margin to a reported number, not to a stop** (section 2). The 60-minute hard cap is checked inside the open,
   exploration and verification phases only; the clock is ended before the close checks run, and nothing reads the recorded `elapsed_s` against
   the cap afterwards. The three capped phases took 3,055.7 s (544 s inside the cap); the close took 540 s outside it. B7 projects the same three
   phases. An sd3 under the same caps would not breach the hard cap; its recorded clock would read about 3,750 to 3,950 s because the close
   grows with the ledger (rd4 225 s, sd1 403 s, sd2 539 s, sd3 about 700 to 800 s).
3. **The throughput drop (2,175 to 1,956 ticks/s) is mostly the standby pipeline, not the machine's stepping speed.** Native stepping was 16 %
   faster per tick in sd2; jobs were shorter (1,559 against 1,634 ticks) and the standby process (about 3 s to start) was not ready when the next
   job came, so the in-job wait doubled (0.48 to 0.89 s per job, about 310 s of wall over the session). A modest start-up slowdown (implied median
   2.97 against 2.83 s) and lower worker utilisation outside jobs (3.50 against 3.69 busy workers of 5) are also visible; their causes cannot be
   separated from the records.
4. **sd2 improved through a four-dispatch chain on cells created or shortened in the same session** (section 3): the band-8 cell 43190 (1,789, its
   only dispatch ever, at iteration 18,199) made 45103 (1,811); its second dispatch (19,167) made the first level-9 arrivals ahead of the record
   (1,832 to 1,850) and shortened 45459 to 1,826; 45459's first dispatch (19,206) made 46827 (1,850); 46827's first dispatch (20,491) cleared at
   1,885. The 201 ticks are 62 at level 8 (the proposal's census), 4 on the 8-to-9 leg and 135 in the ending, which is a terminal-speed fall
   (70 units per tick) drifting past the floor's edge: within about one tick of the physical minimum for that leg. The proposal gave the realised
   band (1,877 to 1,981) roughly 8 %. The old trunk's own ending re-draws (2,053, from iteration 18,013) would have been PROGRESS by 9 ticks on
   their own.
5. **Against 1,885 with E7 at 1,860, the top of the archive is almost empty** (section 4): 20 level-9 cells and 159 level-8 cells stay eligible
   (2,340 and 1,555 at 2,061); the harmonic draw would send about 1,263 dispatches to the 20 and 632 to the 159. The ending leg has at most about
   one tick of physical slack, the 6-to-8 leg at most about 14, the landing-to-6 leg perhaps 25 to 30 (uncertain), the right side and the
   crossing are untouched after six sessions. Subjective odds for an sd3 under the same design: a shorter verified clear 30 to 45 %, PROGRESS at or
   below 1,861 10 to 20 %, at or below 1,800 at most 3 %.
6. **The count-term finding stands and has grown** (section 5): the level-7 lineage ahead of the record went from 8 cells (1,237 to 1,318) at the
   open to 31 (1,237 to 1,338) at the close, received 6 dispatches in sd2 (0.16 %; forecast about 2), produced no new cell, and still holds 0.2 %
   of the mass (7 to 8 dispatches per session). A level-6 front appeared one level deeper (72 cells ahead of 982, shortest 871) with the same 0.2 %.
   Five generic v5 options are listed with evidence; none is chosen here.
7. **Recommendation (section 7): pause the speed-discovery line** at 1,885 / 1,884; if it is resumed, resume it with a v5 proposal evaluated
   offline on the ledger first, not with an sd3 under the same design. Costs: (a) sd3 same design about one preparation day plus a 9-hour launch
   day for a 10 to 20 % chance of PROGRESS; (b) v5 about one proposal day plus 1.5 preparation days plus the same launch day; (c) pause: nothing.
8. Section 8 lists eleven numbered questions with options and a recommendation each.

## 1. The `post_run_checks.py` defect

### 1.1 The launch session's diagnosis, confirmed point by point

| claim of the results record (section 11) | evidence | verdict |
| --- | --- | --- |
| the base backup's `verification.json` names the whole `runs/` folder as its source | `D:\BattleShip_runs_backup\2026-09-28\verification.json`: `source` = `...\BattleShip\runs`, `files` 377,359, `bytes` 16,968,155,612, `result` PASS, verified 2026-09-28T20:44:33Z; `backup_run.json`: 358,472 copied, 18,887 kept | confirmed |
| `registered_increments` takes it as an increment | `tools/m8_sd2/post_run_checks.py` lines 48 to 57: `rel = src.resolve().relative_to(runs)`; for `src == runs` this returns `.` without raising, `src.is_dir()` holds, and the folder is appended to `increments` with `source_rel` `.` (the stamped record shows exactly that row) | confirmed: by construction of the enumeration, not by a corrupted record |
| the independent script then compares every file of today's `runs/` with the base | `independent_increment_check.ps1` walks `-Source` (today's `runs/`, 446,809 files) and counts a source path absent from the backup as `missing`; `extra` counts backup paths absent from the source; `bad` counts hash mismatches of the paths present on both sides | confirmed; the script's semantics are per-tree |
| `bad = 0`: every base file still equals its `runs/` file | the tool's line: `checked=446809 ... bad=0`; independently: `logs/m8_sd2_review2/base_rehash_result.json` re-hashed all 377,359 manifest rows, backup copy and `runs/` file each against the manifest's sha256: 377,359 rows checked, 0 backup copies differing, 0 `runs/` files differing or absent, PASS, 1,478 s | confirmed independently |
| `extra_in_backup = 0`: no base file is missing from `runs/` | the tool's line; independently, the same re-hash opened every base row's `runs/` file (0 open or read errors) and the identity 377,359 + 69,450 = 446,809 with a disjoint missing set (below) | confirmed independently |
| the 69,450 "missing" files are exactly the twenty per-tree increments' trees, file for file | `logs/m8_sd2_review2/missing_set_check.json`: the 69,450 `MISSING in backup` paths of `post_increments/2026-09-28.txt` equal, as a set, the union of the 20 PASS increments' `manifest.tsv.gz` paths prefixed by each increment's source tree (69,450; `missing - union` and `union - missing` both empty); the per-tree counts are the record's; the intersection with the base manifest is empty; today's regular-file count by the backup tool's own `walk` is 446,809 (50,361 reparse points skipped) | confirmed |
| the FAIL is by construction of the tool's scope; the evidence is intact | coverage `ok`, 446,809 files, 0 uncovered, 20 increments; R1 over the five M8 trees ok; every per-tree increment PASS | confirmed |

**What the record says is accurate.** The one thing it could not say, and this review adds, is the independent confirmation of `bad = 0` and
`extra = 0` by a second implementation (Python `hashlib`, six threads, 24 min 38 s against the PowerShell run's 2 h 37 min).

### 1.2 How sd1's checks excluded the base

sd1 had no post-run tool. Its launch session ran the independent re-hash as a hand loop over eighteen named increments (sd1 results, section 11,
00:54:33 to 01:10:44 EDT) and wrote: "the older trees held only by the base backup `2026-09-28` ... were not independently re-hashed; they are
covered by the coverage check". The exclusion was a choice of folders, not a rule in code. sd2's proposal (section 5.2) turned the step into a tool
whose rule is "every registered increment", defined as every folder with a PASS record whose source is a tree under `runs/` that exists. The base
satisfies that definition. The U6 test (`unit_post_run_checks_tool`) builds two tiny increments and four skipped folders (no record, a FAIL record,
a vanished source, a source outside `runs/`); none has a source equal to the `runs/` root, so the enumeration's one surprising case was never
exercised. The pre-launch review of 2026-10-12 read the tool for the increment-name blocker (which it found) and did not notice this case either.

### 1.3 What it cost, and what it did not

| item | value |
| --- | --- |
| launch-day time | the base row alone 2 h 37 min of the post-run checks' 2 h 59 min (03:58:36 to 06:57:25 EDT); the whole Part D 3 h 29 min; the launch day 10 h 36 min against the proposal's 6 to 7 hours |
| the tool's verdict | exit 1, `ok: false`, with 20 of 21 rows PASS, R1 ok, coverage ok, the tool's verify PASS: a false alarm an unattended reader would have had to interpret |
| the evidence | unaffected: coverage 0 uncovered before the launch and after it; every per-tree increment and the five M8 trees re-hashed PASS; the base's files unchanged |
| the written record | the results record explains the row correctly and did not repair anything (no fix was allowed) |

### 1.4 The fix (not applied) and the tests it needs

**Where.** Not in `tools/m8_sd2/post_run_checks.py`: that file is pinned by sd2's approval, snapshot and fingerprint `b22c0af8f833b205`, and the
M8 pattern never edits a closed session's code. The fix goes into the next session's tool (`tools/m8_sd3/post_run_checks.py` or whatever the next
line's tool folder is), with sd2's record left as it stands.

**What.**

1. *Classification.* In `registered_increments`, a record whose resolved source equals the `runs/` root (`rel == Path(".")`) is a **base**, listed under
   a new key `bases` with the reason "source = runs/: the whole tree; verified by the coverage check", never under `increments`. A source that is a
   parent of `runs/` stays skipped as today.
2. *An optional base-aware check* (`--rehash-base`, default off because of the time): for every row of the base's `manifest.tsv.gz`, hash the backup
   copy and the `runs/` file and compare both with the manifest's sha256 (`bad` = a backup copy that differs, `changed` = a `runs/` file that differs
   or is absent); a `runs/` file absent from the base is not a defect; the files of today's `runs/` that are in neither the base nor an increment
   are reported as `uncovered` (the coverage check's own quantity, recomputed here for the record). Standard library only, threads, about 25
   minutes on this machine; the PowerShell script stays for the per-tree increments.
3. *The verdict.* `ok` depends on the base only when `--rehash-base` was asked; the stamped record carries the base entry either way.

**Tests (zero native ticks, in the next suite's U6 successor).**

| # | test | asserts |
| ---: | --- | --- |
| T1 | classification | on a temporary layout with a real `runs_backup.cmd_backup` of the whole `runs/` (one tree) and a per-tree increment of a second tree: the whole-tree folder is a base, the per-tree one an increment, a parent-of-runs source skipped; `rel == Path(".")` is the discriminator |
| T2 | default mode | exit 0 with untampered trees; the base listed with its reason and not re-hashed; the stamped record's `bases` entry; `post_increments/` holds no base output |
| T3 | `--rehash-base` positive | PASS: every base row equal on both sides; the second tree's files (absent from the base) all in its increment's manifest; `uncovered` 0 |
| T4 | `--rehash-base` negative | a tampered `runs/` file of the base's tree makes `changed` 1 and exit 1; a tampered backup copy makes `bad` 1; a third tree in no manifest makes `uncovered` > 0 and exit 1 |
| T5 | isolation | the base check imports no repository module and writes nothing under the backup root (mtimes of the root's files unchanged after the run); the tool's verify is still reachable through one function only, with `--source` naming the new tree |
| T6 | the real root, read only | a gate test (like `open_protocol_real_trees6`) that runs `registered_increments` against the real `D:\BattleShip_runs_backup` and asserts exactly one base (`2026-09-28`), the expected number of increments and the three known skipped folders; this is the test that would have caught the defect before the launch |

## 2. The hard-cap margin

### 2.1 The session clock by phase

| phase | start to end (UTC) | wall | cap | inside the hard cap? | inside B7? |
| --- | --- | ---: | ---: | --- | --- |
| open (P1, 16 identity replays, the record re-verified) | 06:30:06 to 06:30:37 | 31.5 s | 240 s | yes | yes (150 s pessimistic) |
| exploration (arm T) | 06:30:38 to 07:20:45 | 3,007.0 s (arm wall 3,004.2 s; the wall cap bound, plus the arm-end checkpoint) | 3,000 s + 20 s grace | yes | yes (3,025 s) |
| verification (3 pool replays, 16 close identity replays) | 07:20:45 to 07:21:02 | 17.2 s | 360 s | yes | yes (240 s) |
| the three capped phases | | **3,055.7 s** | 3,600 s | margin **544 s** | pessimistic total 3,415 s |
| close checks (final checkpoint, six-part audit, dispatch rows, overlays, prefix chain, five trees, write guard, stamp audit) | 07:21:03 to 07:30:02 | 539 s (the audit line at 07:29:50, the prefix chain at 07:29:52, the rest 10 s) | none | **no** | **no** |
| decision and `state.json` | 07:30:03 | 1 s | | | |
| recorded `elapsed_s` | | **3,596.9 s** | 3,600 s | a reading, not a check | |

**Which phases the hard cap covers (code facts).** `Clock.global_check` raises `CapStop` when `elapsed > global_cap_s` (`rl/m8_rd_run.py` lines
156 to 159). It is called from `Clock.begin` (so at the start of P1, of the arm and of verification), from the pool's result loop during the open
replays and the verification batches (`clock.check`, `m8_rd_run.py` line 377, `m8_sd2_run.py` lines 246 and 344), and on every turn of the
exploration loop even after a stop (`m8_rd_run.py` line 550). `run_all6` ends the clock in its `finally` (`m8_sd2_run.py` line 606) **before**
`close_checks6` runs; the close checks contain no clock call, and a `CapStop` cannot arise in them. After the session, nothing compares
`elapsed_s` with `global_cap_s`: `verify-run`, `report`, the rule and the results-record check read neither. The hard cap therefore covers the
session from its start (06:30:06Z, six seconds before P1's first log line) to the end of verification. The B7 projection (`m8_rd2_report.budget_projection`)
covers the same three phases and nothing else. The results record's sentence "the session clock came within 3.1 s of the hard cap" is true of the
reported number and does not describe a near-stop; nothing in sd2 came within 544 s of a stop.

### 2.2 The exploration throughput drop

| reading | rd4 | sd1 | sd2 |
| --- | ---: | ---: | ---: |
| exploration ticks / wall | 5,590,384 / 3,003.5 s (wall cap) | 6,000,000 / 2,758.4 s (tick cap) | 5,874,929 / 3,004.2 s (wall cap) |
| aggregate rate | 1,861 ticks/s | 2,175 ticks/s | 1,956 ticks/s |
| returns; returns per second | 3,480; 1.159 | 3,671; 1.331 | 3,769; 1.255 |
| ticks per return; mean start L; median start L | 1,606; 1,503; 1,624 | 1,634; 1,534; 1,907 | 1,559; 1,453; 1,839 |
| native stepping rate per worker (ticks per second of `step_s`) | 681 | 758 | **882** |
| in-job wait for the standby process (`wait_s`, mean / median / share above 2 s) | 0.67 s | 0.48 s / 0.00 / 7.6 % | **0.89 s / 0.59 / 15.1 %** |
| other in-job overhead per return (`wall_s` minus `step_s` minus `wait_s`) | | 0.13 s | 0.13 s |
| wall per return | 3.19 s | 2.77 s | 2.79 s |
| busy workers (sum of job wall over the arm wall; 5 workers) | 3.70 | 3.69 | **3.50** |
| selection time per dispatch | 31 ms | 54.0 ms | 53.4 ms |
| rate in the first and last five-minute windows | | 2,117 (peak 2,251) to 2,050 | 2,007 to 1,884 |

**Reading.** (i) The machine was not slower at the thing that costs ticks: native stepping per tick was 16 % faster than in sd1 (882 against 758
ticks per worker-second), consistent with shorter and lighter jobs. (ii) The wall per return did not fall with it, because each worker's next
BattleShip process is launched at the previous acquisition and takes about 3 s to be ready: when the job in between is short, the worker waits.
In both sessions the wait rises steeply as the previous job shortens (sd1: 1.10 s mean wait after a job under 1.5 s of busy time, 0.12 s after one
over 3 s; sd2: 1.62 s and 0.13 s), and sd2's jobs were shorter (mean previous busy time 1.90 against 2.29 s) because E7 at 2,061 and the harmonic
draw moved the dispatch mix down (mean start L 1,453 against 1,534) and the stepping was faster. The extra wait alone, 0.41 s over 3,769 returns,
is about 1,550 worker-seconds, about 310 s of wall at five workers: the whole gap between sd1's rate and sd2's (5,874,929 ticks at 2,175 ticks/s
would have taken 2,701 s; sd2 took 3,004 s). (iii) At equal previous-job length sd2 waited longer than sd1, and the implied standby start-up
(previous busy time plus wait, when a wait occurred) has median 2.97 s against 2.83 s and lower quartile 2.53 against 2.20 s: a modest start-up
slowdown of 5 to 15 %. Its cause cannot be determined from the records: no CPU sampling exists, the resident process set was the same on both
days (21 `claude.exe`, Edge's background processes), and available memory was 5.2 GB against 5.9 GB. (iv) Worker utilisation outside jobs fell
(3.50 against 3.69 busy workers): time the main process spends per return on ingestion, checkpoints (13 in sd2 at about 85 MB each) and selection
(unchanged at 53 ms) over an archive that grew from 44,007 to 49,928 cells; the records do not time ingestion, so the archive's share of the drop
cannot be separated from the job mix. (v) The chain length (six levels) affects the open protocol and the close, not the exploration loop.
**Verdict:** mostly the job mix and the standby cover (determinable from the per-job records), plus a modest start-up slowdown and main-process
overhead whose split is not determinable. The useful fact for any future design is that this pipeline is bounded by process start-up (about 3 s)
when jobs are short, not by stepping.

### 2.3 An sd3 under the same caps

| phase | sd3 estimate | basis |
| --- | ---: | --- |
| open | about 32 s | P1 6,208 ticks, 16 identity replays of up to 1,885 words, the 1,885-word record |
| exploration | 3,000 to 3,025 s, the wall cap | the aggregate rate is below 2,000 ticks/s, so the 6,000,000-tick cap is out of reach; about 5.7 to 5.9 M ticks |
| verification | 20 to 90 s | a larger pool (sd2's registry holds 11 unverified clear trajectories, about 22,700 ticks, replayed descriptively after the pool) and 16 close identity replays; the cap is 360 s |
| the three capped phases | about 3,060 to 3,150 s | no hard-cap breach; B7's pessimistic 3,415 s still holds |
| close checks | about 700 to 800 s | the six-part audit replays every selection over the archive as it stood: rd4 225 s (13,886 dispatches), sd1 403 s (17,556), sd2 539 s (21,325, measured again here: 1,016 s, but measured while a six-thread re-hash ran on the same machine, so not comparable with the session's 527 s, which stands); sd3 about 25,000 dispatches over up to 56,000 cells |
| recorded `elapsed_s` | about 3,750 to 3,950 s | above 3,600 s, with no consequence in code |
| the process | about 2 h | the run's own preflight grows by one audit (about 58 min), inside the 3.5-hour waiter |

**Would it breach?** The hard cap: no. The recorded clock: yes, by 150 to 350 s, which the record would have to explain exactly as sd2's record
explained 3.1 s. The main-process memory follows the archive (790 MB at the open, 1,420 MB peak in the close; cap 3,072 MB) and would stay inside.

### 2.4 Options to restore a safe margin

| option | departs from "the same design"? | cost | risk | note |
| --- | --- | --- | --- | --- |
| O1 count the close in B7 as a reported estimate (dispatches times archive size) | no (B7 is a projection, not a registered constant) | trivial | none | makes the launch-day projection honest; changes no behaviour |
| O2 state the cap's scope in the record and report the three-phase clock and the close separately | no | trivial | none | removes the "3.1 s" reading; recommended with O1 |
| O3 reduce the exploration wall cap (for example 3,000 to 2,400 s) | yes: a registered cap, "exactly rd4's and sd1's" | about 20 % fewer returns | fewer returns is the one cost the line cannot afford | not recommended |
| O4 raise the hard cap (for example 3,600 to 4,500 s) so the recorded clock fits | yes: a registered cap; `every_cap_binding.equals_hard_cap` in B7 would fail unless the projection is changed too | none in returns | the cap would no longer equal the sum of the phase caps; a new constant with no mechanism behind it | not recommended |
| O5 move the audit out of the session (into `verify-run`) | yes: the audit decides INVALID at the close | none in returns | a failed audit would be found after the decision; weakens the close | not recommended |
| O6 make the audit cheaper (the eligible-levels cache is rebuilt per ingest; a lazier invalidation would cut the quadratic term) | no in the contract (a performance change in a new subclass); but it touches the rebuild path | a day of work and a digest-neutral test | a rebuild that differs from the live selection is INVALID by construction, so a mistake is caught, not hidden | worth doing only if the line continues for several sessions |

## 3. Why sd2 improved: the lineage of cid 1360

### 3.1 The exact chain

cid 1360 is burst 20487 (iteration 20,491), a 35-word burst from cell 46827 (level 9, L 1,850). Its words are the pinned start representatives
walked back to the tick-0 root: 39 bursts. Grouped (the full table is `logs/m8_sd2_review2/lineage_census.json`):

| links | session of the bursts | iterations | L | levels | what they are |
| --- | --- | --- | --- | --- | --- |
| 1 to 25 | rd1 | 4 to 1,799 | 0 to 1,281 | 0 to 6 | the right side: six targets by 1,281 |
| 26 | rd2 | 2,367 | 1,281 to 1,350 | 6 to 7 | the seventh target (the record's 1,339 is on this trunk) |
| 27 to 33 | rd2 | 2,573 to 6,085 | 1,350 to 1,694 | 7 | the crossing: burst 6088 (iteration 6,085, from cell 16732 at 1,633) reaches the wall-top landing at 1,694, the representative of cell 18767 |
| 34 | rd4 | 10,794 | 1,694 to 1,726 | 7 | the take-off from the wall top: cell 27331 (created rd4; 1 dispatch in its life, in sd1) |
| 35 | sd1 | 17,083 | 1,726 to 1,789 | 7 to 8 | target 6 at 1,775: the burst that created the band-8 cells 43189 to 43198 (the proposal's "18 level-8 cells 62 ticks ahead"); here cell 43190 (1,789) |
| 36 | **sd2** | 18,199 | 1,789 to 1,811 | 8 | cell 43190's only dispatch ever (seen 4 at dispatch): 11 new cells, among them 45103 (level 8, 1,811) |
| 37 | **sd2** | 19,167 | 1,811 to 1,826 | 8 | cell 45103's second dispatch: the first level-9 arrivals ahead of the record (46800 to 46804 at 1,832 to 1,850, target 8 at 1,831) and the representative of cell 45459 (an older sd2 cell, created 18,362) shortened to 1,826 |
| 38 | **sd2** | 19,206 | 1,826 to 1,850 | 8 to 9 | cell 45459's first dispatch after the shortening, 39 iterations later: cell 46827 (level 9, 1,850) |
| 39 | **sd2** | 20,491 | 1,850 to 1,885 | 9 to 10 | cell 46827's first dispatch, 1,285 iterations after its creation: target 1 at 1,884, the clear |

**Dispatches received by the chain's sd2 cells:** 43190 one (18,199); 45103 two (18,232, which made 5 cells, and 19,167); 45459 two (19,206,
19,953); 46827 two (20,491, 20,493). Every productive link was the cell's first dispatch (or, for 45103, its second) at `seen` 4 to 8 and
`chosen` 0 to 1. Earlier in the chain: 27331 one dispatch in its life, 18767 two (rd3, rd4), the four wall-top cells none in sd1 and two in sd2.

### 3.2 Against the proposal's census, E7 and the odds

- **The 18 level-8 cells (section 3.4 of the proposal).** They received 27 dispatches in sd2 (the proposal's analytic forecast was about 56; the
  difference is feedback: each dispatch creates cells at the same level that share the level's mass, and `seen` rises). Three were never dispatched.
  The band's shortest (43189 at 1,776) got two dispatches and one new cell; the chain went through the band's second cell, 43190 (1,789), and no
  level-8 cell shorter than 1,776 appeared in sd2. The proposal's expectation for the band ("with the record's own continuation they clear at
  2,024 to 2,085") assumed the record's 60-tick leg to target 8 and its 188-tick ending; the lineage kept the first (56 ticks) and replaced the
  second with a 53-tick fall.
- **Where the 201 ticks came from:** 62 at level 8 (1,838 to 1,776), 4 on the 8-to-9 leg (60 to 56), 135 in the ending (188 to 53). The record broke
  target 8 at (-2,814, 1,036) falling at -44 units per tick, landed on the left floor and ran a 101-tick arc; cid 1360 broke it at (-3,321, 726)
  already fast-falling at -70, then fell at -70 for 48 ticks (plus about 6 ticks of hit-freeze) drifting left to x -4,036, past the floor's edge, and
  broke target 1 at (-4,036, -2,494). That is the proposal's second "mechanically plausible line" (a direct fall that drifts left past the floor's
  edge), reached from a different target-8 break than the proposal imagined.
- **E7 at 2,061.** It excluded 4,697 cells at the open (level 8: 1,992, level 9: 2,637) and left 940 eligible level-8 cells and 1,004 level-9 cells
  against 1,546 and 3,378 under sd1's bound. The band's share of level 8's 17 % therefore rose by about 1.6 times; that is the bound's whole
  contribution to this lineage, whose own cells lay far below either bound. The analytic allocation at the open, 972 dispatches to level-9 cells at
  or below 2,040, was realised as 1,255 level-9 dispatches of which 41 went to cells at or below 1,860 and 990 to cells between 1,861 and 2,000.
- **Two independent sources of PROGRESS.** The pool held 12 candidates at or below 2,062. Eight of them (2,053 x 4 and 2,055 x 4, the first at
  iteration 18,013) are ending re-draws from old rd4 cells at L 1,989 to 2,057 on the record's trunk, and 2,053 would have been PROGRESS by 9 ticks
  on its own. The lineage's clears came later: 1,964 (iteration 19,688), 1,929 (20,219), 1,885 (20,491). The verified 1,929 and 1,964 started from
  rd4 cells (29779 at 1,918, 36537 at 1,898) whose representatives the lineage's bursts had shortened at iterations 19,400 and 19,207: the
  improvement propagated into old cells by replacement before it was dispatched from them.
- **The odds.** The proposal gave PROGRESS 30 to 45 %, a clear at or below 1,981 about 10 % and at or below 1,877 about 2 %. The realised 1,885 lies
  in the roughly 8 % band between those two tiers: an upper-tail outcome, and the first time the speed line beat its own forecast's centre.

### 3.3 What this says about how the design finds improvements

1. **It finds endings, through short chains on fresh cells.** Both speed sessions' gains are on the left side after the wall top (sd1: the target-8
   detour removed; sd2: the ending and the 6-to-8 leg). The productive dispatches were first or second dispatches of cells created or shortened in
   the same session, 39 to 1,285 iterations earlier. The count term at `seen` 4 to 8 and the length factor near the level's shortest are what put
   them in reach; E7 raised their share.
2. **Replacement is the main channel, and the count term does not see it.** sd2 made 5,921 new cells and 17,475 representative replacements;
   10,893 cells created before sd2 were shortened, 1,489 of them dispatched afterwards, with a median `seen` of 10. Two of the three verified clears
   started from such cells. A cell whose prefix just got shorter is treated as the well-seen cell it was.
3. **The right side and the crossing have not moved in six sessions.** Every level up to 7 on the record's trunk (43, 120, 399, 609, 880, 982,
   1,339) and the wall-top landing at 1,694 are rd1 and rd2 bursts. The lineages ahead of that pace (level 7 at 1,237, now level 6 at 871) receive
   7 to 8 dispatches per session (section 5).
4. **Progress came late and at the wall cap.** The clear is dispatch 2,935 of 3,769, at 82 % of the exploration wall; the level-9 arrivals ahead
   of the record appeared at dispatch 1,611. A session at sd1's rate would have reached about the same iteration before its tick cap.
5. **The dispatch mix is the rd3 review's starvation pattern again.** 53 % of sd2's dispatches started from cells seen 8 or more times (sd1 38 %,
   rd4 23 %); yields by `seen` class were 5.5, 3.3, 1.4, 0.32, 0.06 and 0.02 new cells per return (0 to 1, 2 to 3, 4 to 7, 8 to 15, 16 to 31, 32 and
   more); 41 % of dispatches started from rd4-created cells at 0.75 new cells per return, against 3.6 for sd1- and sd2-created cells. E7 shrinks
   the eligible top levels to heavily seen cells and the harmonic draw keeps sending half the mass there.

## 4. The closing archive against the new reference 1,885 (bar 1,861, E7 at L <= 1,860)

### 4.1 Per level

"New pace" is cid 1360's own break table read from its trace (43, 120, 399, 609, 880, 982, 1,339, 1,776, 1,832, 1,885); "slack" is pace minus the
level's shortest arrival. Eligibility and masses are the exact v4 figures from the archive's loader at the close (the loader reproduces the
session's 29,136 at the bound 2,061). Expected dispatches are mass times 3,700, first order, no feedback.

| level | cells at the close | shortest L | new pace | slack | cells ahead of the new pace | E7 excludes at 1,860 (raw) | v4-eligible at 1,860 (at 2,061) | v4 mass | expected dispatches per 3,700 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| 0 | 2,185 | 0 | | | | 0 | 1,099 (1,099) | 3.4 % | 126 |
| 1 | 3,885 | 26 | 43 | 17 | 6 | 0 | 2,807 (2,807) | 3.8 % | 140 |
| 2 | 4,478 | 91 | 120 | 29 | 17 | 0 | 2,996 (2,996) | 4.3 % | 158 |
| 3 | 5,754 | 152 | 399 | 247 | 806 | 0 | 3,735 (3,735) | 4.9 % | 180 |
| 4 | 6,536 | 254 | 609 | 355 | 878 | 0 | 3,399 (3,399) | 5.7 % | 211 |
| 5 | 6,535 | 433 | 880 | 447 | 782 | 0 | 3,616 (3,616) | 6.8 % | 253 |
| 6 | 6,021 | **871** (931 at the open) | 982 | 111 | 72 | 0 | 3,529 (3,529) | 8.5 % | 316 |
| 7 | 6,222 | 1,237 | 1,339 | 102 | 31 | 1,254 | 3,518 (4,060) | 11.4 % | 421 |
| 8 | 4,359 | 1,776 | 1,776 | 0 | 0 | 4,189 | **159** (1,555) | 17.1 % | 632 |
| 9 | 3,944 | 1,832 | 1,832 | 0 | 0 | 3,924 | **20** (2,340) | 34.1 % | 1,263 |
| 10 | 9 | 1,885 | 1,885 | | | 9 | 0 (0) | 0 | 0 |
| all | 49,928 | | | | | **9,376** (3,400 at 2,061) | **24,878** (29,136) | | 3,700 |

The 20 eligible level-9 cells (L 1,832 to 1,859, all class A2, 12 created in sd2, 7 in rd4, 1 in sd1) received 41 dispatches in sd2 and produced
the 1,885 (from 46827, on its first dispatch) and nothing shorter. The 159 eligible level-8 cells (5 at or below 1,800) received 158 dispatches.
Under the same design in an sd3 the harmonic draw puts 34.1 % of the mass on the 20 and 17.1 % on the 159 from the first dispatch on, until
feedback (new cells at those levels, rising `seen`) spreads it.

### 4.2 Physical bounds on the left side, from the agent's own traces

| leg | cid 1360 | lower bound (terminal fall 70 units per tick, the minimum `air_velocity_y` seen in both traces; about 6 ticks of hit-freeze after a break, as observed at 1,831 to 1,837) | slack |
| --- | ---: | ---: | ---: |
| target 8 (1,831, y 726) to target 1 (1,884, y -2,494) | 53 ticks | 3,220 units of fall: 46 ticks, plus the freeze: about 52 | **about 1 tick** |
| target 6 (1,775, y 3,236) to target 8 (1,831, y 726) | 56 ticks | 2,510 units: 36 ticks, plus the freeze: about 42 (the route fell at -44 for about 40 ticks before fast-falling) | **about 14 ticks** |
| wall-top landing (1,694) to target 6 (1,775) | 81 ticks | the flight (take-off between 1,714 and 1,726, 1,513 horizontal units at up to 30 units per tick): at least about 50 to 55 ticks; the 20 to 30 ticks standing on the wall top before the jump may or may not be removable (the moving platform's timing is not readable from the archive) | **perhaps 25 to 30 ticks; uncertain** |
| the crossing (1,339 to 1,694) and the right side (1,339) | 355 and 1,339 ticks | unknown; the only lineages ahead are the starved ones of section 5 | unknown |

These bounds assume the same break order and that no other mechanic (up-B, tornado, a platform) shortens a leg; they are readings of two traces,
not a model of the game. **The bar 1,861 cannot be reached by an ending re-draw**: 24 ticks must come from the 6-to-8 leg, the landing-to-6 leg,
the crossing or the right side. Under the same design the first two legs are explored from the 159 level-8 cells (632 dispatches, at most about
14 ticks available) and from the 348 eligible level-7 cells at L 1,694 to 1,775 (mass 1.25 %, about 46 dispatches, the leg with the most slack);
the four wall-top cells hold 0.02 % (under one dispatch); the right-side lineages 0.2 % each.

### 4.3 Odds for an sd3 under the same design (subjective; one session of about 3,700 returns)

| event | odds | grounds |
| --- | --- | --- |
| a verified clear shorter than 1,885 (RECORD_BELOW_MARGIN or better) | 30 to 45 % | 1,900 dispatches on the two short legs; a few ticks from a faster 6-to-8 fast-fall or a one-tick ending; sd2's rate of clear-kind candidates from the band (1 in 41) |
| **PROGRESS (at or below 1,861)** | **10 to 20 %** | needs about 24 ticks from the landing-to-6 leg (46 dispatches on 348 cells, few of which are at the useful take-off states) combined with the 6-to-8 leg, or an earlier wall-top landing, or the right side; the ending cannot give it |
| at or below 1,800 | at most 3 % | needs the crossing or the right side |
| NO_SHORTER_CLEAR | 50 to 65 % | the top levels' eligible sets are small and heavily seen; the physical floors |
| INVALID or INCOMPLETE | about 5 % | as before |

**The case for diminishing returns, stated honestly.** sd1 bought 229 ticks and sd2 201, so the realised gains are not yet falling. What has
fallen is the slack the design can reach: the ending it just found is at its physical floor, the 6-to-8 leg has about 14 ticks, and the one leg
with real slack (landing to target 6) receives about 46 dispatches per session under the harmonic draw and the length factor, which favour the
level's shortest cells (the 1,237 lineage) over the crossing cells at 1,694 to 1,775 by a factor of about five in weight per cell. Everything
beyond that (about 1,700 ticks of right side and crossing, 90 % of the route) is explored at 7 to 8 dispatches per session per lineage. A third
same-design session is a 10 to 20 % shot at the margin; each later one is worse, because the eligible top levels shrink with every new reference
(2,340 to 20 level-9 cells from one move of the bound).

## 5. The count-term finding

### 5.1 With sd2's data

| item | at the sd2 open | at the sd2 close |
| --- | --- | --- |
| level-7 cells ahead of the record's 1,339 | 8 (L 1,237 to 1,318; rd2 cells whose representatives sd1's burst 17124 shortened) | **31** (1,237 to 1,338): 23 more rd2 and rd3 cells shortened by nine sd2 bursts, six from the lineage's own cells (iterations 17,611, 18,098, 19,772, 19,803, 20,857, 21,125) and three from level-6 cells at 1,223 to 1,262 (18,911, 18,920, 21,204) |
| dispatches from the lineage in sd2 | forecast about 2 (0.06 % of the mass) | **6** realised (0.16 %), from cells 11148, 10960, 11711, 13104, 11754, 11143 |
| new cells from those dispatches | | **0** (23 shortenings, no new key) |
| the lineage's lead at level 7 | 102 ticks | 102 ticks (1,237 unchanged); no level-8 cell descends from it ahead of 1,776 (the level-8 shortest is the record's trunk) |
| `seen` / `chosen` of the lineage's cells | 16 to 47 | 16 to 52 / 0 to 4 |
| v4 mass at the close (bound 2,061 / 1,860) | | 0.19 % / 0.21 %: about 7 to 8 dispatches per 3,700 |
| the same pattern one level deeper | level 6 shortest 931 | **871** (cell 2351, an rd1 cell shortened at iteration 19,837 by a burst from a level-5 cell at 826): 72 level-6 cells ahead of 982, mass 0.20 %, about 7.5 dispatches per session |

**Is it still ahead?** Yes at level 7 (102 ticks) and now at level 6 (111 ticks); nothing from either reached level 8 ahead of 1,776. The lineage
is the level's shortest, so the length factor gives it 1.0; the count term gives it 0.14 to 0.17 (`seen` 35 to 52), and it competes with 3,518
eligible level-7 cells for 11.4 % of the mass. The 23 new members are old cells (`seen` 17 to 46) whose representatives became shorter: the term
that is meant to measure exhaustion measures the old prefix's visits.

### 5.2 Generic options for a v5 selection (options only; every one position-blind and stage-agnostic)

| id | change (one change each; everything else v4) | evidence for | evidence against |
| --- | --- | --- | --- |
| V5-a | reset `seen` (and `chosen`) to 0 when a cell's representative is replaced by a strictly shorter one | the counters describe visits to the old prefix; sd2's three verified clears all started from cells created or shortened in sd2; the starved lineage would get the weight of a new cell | 17,475 replacements against 5,921 new cells in sd2: a reset makes every shortened cell "new", and most shortenings are small (the 23 level-7 ones moved cells from 1,400 to 1,330, still behind nothing); the flooding would dilute the real frontier |
| V5-b | add a counter "chosen since the last strict shortening" and use the published count form on it beside or instead of `seen` | targets exactly the diagnosed blind spot without resetting the visit evidence; Go-Explore's own "times chosen since new" is the same idea for new cells (rd3 review, K2) | the rd3 review found additive count forms flat (K2); a replacement-aware counter is 0 for 10,893 cells after sd2 and would need a weight that is not tuned on results |
| V5-c | a frontier share per level: a fixed fraction of each level's mass (for example the harmonic weight's own 1 / (1 + top - level)) goes to the cells within one burst of the level's shortest arrival | directly funds the ahead-of-pace lineages (31 at level 7, 72 at level 6, 20 at level 9) without reading positions or targets; the rd3 review's "the frontier is small" diagnosis | it funds the level's shortest cells, which at levels 8 and 9 are the exhausted ending cells too; the fraction is a new constant; the crossing cells at 1,694 to 1,775 are not within one burst of 1,237 and would still get little |
| V5-d | replace the harmonic level weight by a lead weight: each level's share proportional to how far its shortest arrival lies ahead of the archive's best verified clear's arrival at that level | uses only archive-internal time quantities (like E7); would send mass to levels 6 and 7 (102 to 447 ticks ahead) and almost none to levels 8 and 9 (0 ahead) | assumes the record's target order (a level is "ahead" only along the same route order); the deep levels' leads (447 at level 5) are the old right-side slack the record never used, so the mass may go where no crossing follows |
| V5-e | one guaranteed dispatch per strict shortening: shortened cells join a queue drawn with a fixed small share of dispatches (first in, first out), then return to the ordinary weights | a cell whose prefix just improved is the cheapest test of whether the improvement continues; the lineage's 23 shortenings would each have been tried once | sd2 would have queued 17,475 entries for 3,769 dispatches: the share decides everything, and most shortenings are not frontier events; needs a de-duplication rule (per cell, per session) that is itself a design choice |

None of these changes the physical floors of section 4.2; what they change is whether the crossing and the right side are explored at all. Any of
them is a new selection contract (a v5) with its own proposal, offline evaluation on the six-session ledger (as the rd3 review did for K1, with a
pre-registered choice), new modules and its own line rule; none is "under the same design".

## 6. Other observations from the run

1. **The launch day was 10 h 36 min** (Part B 4 h 28 min, Part C 2 h 38 min of which the run's own preflight 48 min and the session 60 min, Part D
   3 h 29 min of which the base re-hash 2 h 37 min) against the proposal's 6 to 7 hours. Without the base row Part D is about 50 minutes.
2. **The machine.** 21 `claude.exe` processes all day (the desktop app with 10 helpers, 10 Claude Code CLI processes): nine CLI processes of
   earlier sessions held 1.68 to 1.89 GB of working set in sum (all Claude processes 3.1 to 3.6 GB) and used 48 to 59 s of CPU each over 4.5 hours
   (the record's figure), so they were idle and cost memory only. Nothing was closed. Available memory: minimum 5,720 MB in Part B, 5,200 MB in the
   session (the session's own sampler 5,075 MB), 3,723 MB during the PowerShell re-hash; free commit minimum 9,892 MB in the session; readiness
   thresholds 4,096 / 10,240 MB, stop thresholds 1,024 / 2,048 MB. The margin above the readiness threshold was 1.1 GB with those processes
   resident. Edge's five background processes exited by themselves at 21:09; no node, Playwright, WSL or IDE process at any sample; no alert.
3. **Ten BattleShip processes against a cap of ten** in every busy sample of both samplers, as in sd1: N = 5 with one standby each equals the cap
   by construction. Section 2.2 shows the standby is also the throughput bound; a second standby per worker would raise both.
4. **The main process:** 790 MB private at the open, 850 to 870 MB during exploration, 1,112 MB after the close (the loaded archive), peak 1,420 MB
   (cap 3,072 MB); the process tree peaked at 4,674 MB private (cap 9,216 MB).
5. **The waiter saw `session: null` for the first 44 minutes** (the run's own preflight writes no state); the launch check at 0 s therefore
   confirms the process started, not that the preflight passed. A preflight refusal would be noticed only when `state.json` never appears.
6. **The pool closed with nine unreplayed clear candidates** (1,978, 2,053 x 4, 2,055 x 4), all shorter than the old reference and all now
   inherited descriptive replays for any sd3 (about 22,700 ticks; the inherited rule replays every unverified clear trajectory of the predecessor).
7. **The verification cap was far away** (31,450 of 400,000 ticks; 17 s of 360 s) and the open used 29,567 of 70,000 ticks.
8. **Replacements outnumber new cells three to one** (17,475 to 5,921). The archive is shortening more than it is growing; the overlays and the
   count term describe cells, not prefixes.
9. **The preparation and the launch ran on the same day**, against the preparation record's recommendation; no incident followed. The three M9
   unit suites' git-state gates failed before the commit as expected and passed on the committed tree in Part B.
10. **The results record is accurate** on every point checked here, including the one it flagged for this review.

## 7. Recommendation

| option | what it is | preparation | launch day | what it can buy | risk |
| --- | --- | --- | --- | --- | --- |
| (a) sd3 under the same design, with the tool fix and O1 + O2 | `rl/m8_sd3_*.py` and `tools/m8_sd3/` subclassing sd2 as sd2 subclassed sd1: a third bound (1,860) by iteration, a seven-level resume (R1 over six trees), the claims over sd2's registry (11 inherited descriptive replays), `m8_sd3_rule_v1` at 1,885 / 1,861, the base-aware post-run checks, B7 with the close estimate | one zero-tick session of about 8 to 10 hours plus about 5 hours of unattended passes and suites (the gate test over six real trees adds about 9 minutes per unit pass; each e2e pass grows by a synthetic sd2), then the owner's commit and the three M9 unit suites | about 9 hours (Part B about 5 h, Part C about 2.9 h, Part D about 1.3 h) | PROGRESS 10 to 20 %, a shorter clear 30 to 45 %; both from the two short legs | low operational risk; a fourth same-design session afterwards would be worse again |
| (b) sd3 with a v5 selection | a proposal first (the offline evaluation of section 5.2's options on the six-session ledger, a pre-registered choice as in the rd3 review), then a preparation as (a) plus the new contract (weights, a three-bound and v5 switch in the rebuild, the overlay, the digest tests) and its own rule | about one proposal day plus 12 to 15 hours of preparation plus the unattended passes | the same 9 hours | the crossing and the right side explored for the first time; no estimate of a clear is honest before the offline evaluation | a new contract with one uncontrolled session; its result is not attributable (no control arm); the physical floors of the left side are unchanged |
| (c) pause the line | the archive stands at 1,885 / 1,884 (cid 1360) with its exact replays, routes and six protected trees; the line's record is complete | none | none | the machine and the owner's time go to the policy line, with the archive's exact left-side lineages (the 1,885 route, the level-9 arrivals at 1,832, the wall-top cells) available as the agent's own starts | the sd line's momentum (two PROGRESS in two sessions) is left unused |

**Recommendation: (c), pause.** Reasons: the leg the design would spend half of an sd3 on is at its physical floor (section 4.2); the legs with
slack are reached by about 50 dispatches per session; the right side has not been explored in six sessions and will not be under the same design;
a same-design sd3 is a 10 to 20 % shot at 24 ticks for about two days of work and machine time. If the owner wants the line continued, (b) is the
only option that attacks the diagnosed mechanism, and its first step costs one offline day and no native tick; (a) is not recommended, but it is
permitted by the line rule and its costs are in the table.

## 8. Open questions (numbered; each with options and a recommendation)

1. **The line.** Options: pause (c); sd3 under the same design (a); a v5 proposal (b). *Recommendation:* (c); if continued, (b) first as an
   offline proposal.
2. **The `post_run_checks.py` fix.** Options: classify-and-skip only; classify plus the optional base-aware Python re-hash (`--rehash-base`);
   keep the tool as it is and document the FAIL. Where: a new tool in the next session's folder, or an edit of the pinned sd2 tool.
   *Recommendation:* classify plus the optional check, in a new file; sd2's tool and record stay as they are.
3. **The sd2 results record.** Options: leave it (this review records the clock's scope and the base re-hash); append a dated note (an edit of a
   tracked, pinned document). *Recommendation:* leave it.
4. **The clock's scope.** Options: O1 + O2 (report the close in B7 and in the record, state the cap's scope); O4 (raise the hard cap); O3 (shorten
   exploration). *Recommendation:* O1 + O2 if any session follows; no registered constant changes.
5. **Part B's scope for any next session.** Options: every registered suite again (about 5 hours); the three passes plus the M8 suites of the chain
   and the three M9 unit suites once (about 3.5 hours). *Recommendation:* the owner's call; the full set is the evidence that nothing inherited
   changed, and it has never found a regression.
6. **If (b): which v5 options go to the offline evaluation.** Options: V5-b and V5-e (replacement-aware, the diagnosed mechanism); V5-c or V5-d
   (frontier or lead weights, a different principle); all five. *Recommendation:* V5-b and V5-e, with V5-c as the comparison, evaluated on the
   real ledger with a pre-registered choice as the rd3 review did.
7. **The idle Claude Code processes.** Options: the owner closes the nine idle sessions (about 1.8 GB) before any launch; leave them. *Recommendation:*
   close them before Part B; the launch session itself must close nothing (A4).
8. **If (a): the exploration caps.** Options: keep 6,000,000 ticks or 50 minutes (the wall binds at the current rate); wall only. *Recommendation:* keep.
9. **If (a): the reported tiers at 1,885.** Options: floor(0.95 x 1,885) = 1,790 and floor(0.90 x 1,885) = 1,696 with a round tier 1,700 (the stretch
   tier below the 10 % tier, sd2's rule) or 1,600. *Recommendation:* 1,790 / 1,696 / 1,700, reported only, as before.
10. **If (a): an explicit end condition.** Options: sd3 is the line's last same-design session unless it ends PROGRESS; no end condition.
    *Recommendation:* the end condition, written into the rule.
11. **The nine unreplayed pool candidates.** Options: replay them descriptively in a future session (the inherited rule does this at the next open);
    nothing now. *Recommendation:* nothing now.

## Appendix A. Working files (Git-ignored, `logs/m8_sd2_review2/`)

| file | content |
| --- | --- |
| `scripts/missing_set_check.py`, `missing_set_check.json` | the 69,450 missing paths against the 20 increments' manifests and the base manifest |
| `scripts/base_rehash.py`, `base_rehash_result.json`, `base_rehash_progress.txt`, `base_rehash_stdout.txt` | the independent re-hash of the base backup (both sides against the manifest) |
| `scripts/lineage.py`, `lineage_census.json` | cid 1360's chain, the band-8 and level-7 cells, the per-level counts, the clears' start cells |
| `scripts/census_v4.py`, `census_v4.json`, `census_legs.json` | exact v4 eligibility and analytic masses at the bounds 2,061 and 1,860 |
| `scripts/audit_timing.py`, `audit_timing.json` | the six-part audit of the closing archive timed once |

## Appendix B. Compliance of this review

| constraint | how it was kept |
| --- | --- |
| zero native ticks | no `BattleShip.exe`, no suite, no preflight, no launcher, no tool that creates a run was started; the archive was read through its pure loader |
| no tracked file modified; nothing under `runs/` or on D: changed | only this record and `logs/m8_sd2_review2/` were written; D: was read (manifests, records, the base files for hashing) |
| no RNG seed inspection, logging, control, comparison or hashing | nothing touched RNG |
| no human recording, fixture or TAS read | the two traces read are the agent's own verified clears (`routes/T_clear_best/trace.json.gz`, sd1's `T_c0901_clear.json.gz`) |
| no commit, push, branch or pull request | `git status` at the end shows only this record as untracked (the Git-ignored logs do not appear) |
| no hardcoded route, waypoint, cid or census number proposed for selection | section 5.2's options are generic; the positions and cids in this record are readings |
