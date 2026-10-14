# M8 fast-route proposal review (2026-10-14)

## 0. Status, scope and verdict

**Status: independent, read-only review; zero native ticks.** No game, suite, preflight or launcher was started. No tracked file was
modified; nothing under `runs/` or on D: changed (the sd2 closing archive and the 1,885 route trace under `runs/m8_rd_sd2/` were read). New files:
this record and the Git-ignored working files under `logs/frs_review/` (`scripts/r1_checks.py`, `scripts/r2_census.py`, their outputs
`r1_checks.json`, `r2_census.json`; both run with `python -B`, standard library only). Checkout `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`,
branch `main`, HEAD = `origin/main` = `fee475a` ("Add the fast-route discovery proposal"), clean with nothing staged at the start; the proposal,
the analysis, the sd2 review, the audit and the handoff are all committed. The TAS, every human recording, the owner's own run and any external
time were not read or used. Nothing touches native RNG. The owner's premise is taken as given: Track 1 is not the limit; the search is.

**Read.** `docs/project_handoff.md`; in full `docs/rl_m8_fast_route_proposal_2026-10-13.md`, `docs/rl_m8_fast_route_analysis_2026-10-13.md` and
`docs/rl_m8_sd2_review_2026-10-13.md`; Areas 3, 5, 6 and 10 and section 3 of `docs/rl_generalization_audit_2026-10-13.md`;
`docs/rl_decisions_2026-10-13.md`; the proposal's own scripts (`logs/m8_fast_proposal/scripts/`) and the analysis loader; and only the code the
claims rest on: `rl/m8_rd_explore.py` (whole), `rl/m8_rd_worker.py` (the step contract, `run_iterate`, `run_trace`, `run_reverify`,
`FrozenRuntime`), `rl/m8_rd_archive.py` (`_better`, `decide`, `ingest`, `eligible`), `rl/m8_sd1_select.py` and `rl/m8_rd_cells.py` headers,
`rl/m8_rd_session.py` (the verification replay), `rl/m8_rd_run.py` (the process cap), the headers of `rl/battleship_process.py` and
`rl/m7_standby.py`. No record was read in full beyond the three named.

**Verdict: sound after the listed changes.** The diagnosis (an end optimiser with no propagation, a single root, a starved crossing, a
saturated novelty signal) is correct and every figure it rests on reproduces exactly (section 1). Lab mode is the right process change. But
three of the design's components do not do what the proposal says they do: the continuation trigger as written fires on 0.7 % of length-ended
bursts, not a third (M1); the per-mask length reference cannot relieve the crossing cells because level 7 has one mask (M2); and the kappa-8
bottleneck budget is flat across levels 3 to 9 and sends 9.5 % of all dispatches to 23 cells at levels 1 and 2 (M3). The comparison protocol can
only detect effects larger than about twice the run-to-run spread and its keep rule is biased towards dropping (M4). Campaign nights run into the
3 GB main-process cap by the second or third night (M5). And the plan builds 15 to 25 hours of modules before the one experiment that can answer
its central question in minutes: replaying the splice candidates that have no moving object between them and the clear, with tooling that
already exists (M6). With those changes, and the build order of section 9, the line is worth November's nights.

## 0.1 Findings

**MUST-CHANGE**

| id | finding | why it matters | suggested fix |
| --- | --- | --- | --- |
| M1 | **F3 and R4 do not describe the same rule.** F3 counts a length-ended burst as productive if any non-doomed new cell or strict shortening fell in its last 20 words: 5,314 of 16,338 (32.5 %), reproduced. R4 as written continues only if the last 20 words "improved some B(m) or made a new or strictly shorter non-doomed cell with lead > 0". Replaying the ledger with the tables in force at each dispatch, that condition held for **119 of 16,338 (0.7 %)**; with the final tables in hindsight, 180. At level 7: 4 of 3,950. "Non-doomed" also cannot be known at the boundary: doom needs the next 60 ticks. | Either continuation is almost inert (0.7 %), or the trigger is F3's condition and a third of jobs grow by 120 words, which changes throughput and every comparison. The proposal argues from the second and specifies the first. | Define the trigger as F3's condition (any new cell or strict shortening in the last k words; doom assigned at ingest), pre-register the expected continuation rate (about a third, 27 % at level 7, 49 % at level 8), ingest a continued job as one burst so a later fall dooms earlier reaches, and record the decision inputs in the burst row. |
| M2 | **The per-mask length reference does not relieve the crossing cells.** Level 7 holds exactly one mask (322) across all 6,222 cells; its B is the dead-end lineage's 1,237. The 490 eligible crossing cells at L 1,694 to 1,775 keep a length factor of 0.18 to 0.21 under PFS, as under v4. Approximate masses at the sd2 close: the crossing band 1.4 % under v4 (52 dispatches per session) and **0.65 % under PFS** (232 per 36,000-dispatch night); the 31 cells of the 1,237 lineage 0.19 % under v4 and **8.2 % under PFS** (2,949 per night). | The sd2 review names the landing-to-target-6 leg as the one leg with real slack (25 to 30 ticks). PFS halves its share and the component table (2.3) claims the opposite. | In the pace pool use the `fresh` counter only (no length factor), or cap the lag at one burst (120 / (120 + min(lag, 120))). Add a census expectation for the crossing band's mass. Masks per level are 1, 6, 9, 11, 9, 6, 2, 1, 3, 3, 1: a per-mask reference changes nothing at levels 0, 7 and 10 and little at 6. |
| M3 | **The kappa-8 bottleneck budget is flat where it matters, and tiny levels absorb it.** r(l) over each level's last 1,000 bursts gives 1/r of 4.2, 4.2, 5.2 at levels 0 to 2 and 9.2, 36, 44, 23, 84, 14, 77 at levels 3 to 9: every level from 3 up sits at the cap. Among levels with ahead cells the shares are 8.5, 10.5 and 16.2 × 5 %. Levels 1 and 2 hold 6 and 17 ahead cells with leads of 17 and 29 ticks and would receive **9.5 % of all dispatches** (3,400 per night; 254 and 111 per cell), while levels 3 to 5's 800 ahead cells each get 3 to 4. | The budget neither expresses the bottleneck nor scales with the number of cells; the first 120 ticks of the game get a tenth of the search. | Draw ahead cells from one pooled list with weight = cell weight × level factor (so level mass follows cell count, as Go-Explore's flat draw does), or weight levels by the sum of their cell weights. Raise kappa (or drop it) if the bottleneck is meant to be expressed. Require lead ≥ one explorer burst (120 ticks, the explorer's own constant) for membership, or accept the levels 1 to 2 share knowingly. |
| M4 | **The comparison protocol cannot detect realistic effects, and its keep rule is biased to DROP.** With two paired replicates a sign test's smallest p is 0.25; on a continuous metric under the null, "faster than every replicate of the other arm" happens 1 time in 6 and "better in both pairs" 1 time in 4. I1 is a rare event (sd2's clear came at dispatch 2,935 of 3,769, an upper-tail outcome), so both arms will usually tie at 1,885; then the rule needs better I3 **and** I2 in every pair, but I3 is 6 for both arms unless a level-7 ahead front crosses, so a tie on I3 drops the component. Two control replicates estimate the spread with one degree of freedom. | A useful component is dropped, or a useless one kept, by noise; the week-1 decision is pre-committed to the control. | Three replicates per arm minimum for a KEEP (p 0.125) or a continuous pre-declared metric with a margin above the measured spread; "not worse on I3 and better on I2"; treat C1 as a mechanism check (the census realised, throughput, the spread), not an efficacy verdict; let the campaign (I1) decide efficacy. Smallest reliably detectable effect: about 2.3 run-to-run standard deviations (P(PFS run beats control run) ≈ 0.95); the spread itself is unknown. |
| M5 | **Campaign memory and selection cost are unplanned.** New cells per dispatch were 3.8, 2.7, 1.7, 3.1, 1.8, 1.6 (rd1 to sd2): 57,000 to 137,000 new cells per 36,000-dispatch night. The main process holds 790 MB at 49,928 cells and 21,323 bursts (burst wins kept in memory), 1,420 MB peak at the close; a linear projection adds about 1 GB per night, so the 3,072 MB cap is reached on the second or third campaign night and the 48-hour weekend campaign cannot run as designed. Selection rebuilds the eligible lists on every ingest (53 ms per dispatch at 50 k cells, about 150 ms at 150 k). | END_MACHINE would end the line by design on the first campaign weekend. | Before any campaign night: a write-through ledger (wins not kept in memory), incremental eligibility, a measured bytes-per-cell figure at C0, and an archive-size stop that is not a machine stop. |
| M6 | **The splice probe needs no module family and should run first.** `m8_rd_session` already replays any action list from tick 0 through `m7f_trace.run_stepping_trace` with the verify flags, and `m7n_crossing.analyse_trace` returns the break table. A splice candidate's words are the representative's stored prefix plus the donor's stored words from its reach tick: 198 candidates × 3 donors is at most about 600 episodes of under 1,885 ticks, about 30 to 45 minutes at N = 5; the nine candidates with no moving object ahead of them take one minute. | If one of the nine survives, a clear up to 209 ticks faster is in hand and is registrable now. If none of the 198 survives one break, R5 is dead and R8 (motion-aware cells) moves up. Either answer changes what is built. | A 150-line script over the existing tracer (section 9, step 1), run under the owner's authorisation before week 0's modules. |

**SHOULD-CHANGE**

| id | finding | why it matters | suggested fix |
| --- | --- | --- | --- |
| S1 | The plateau rule's second condition ("no new best arrival at any mask of the deepest three levels") can be reset by dead-end masks: levels 8 and 9 hold three masks each; the non-record masks' bests are 1,873 and 1,929 (level 8) and 1,946 and 2,003 (level 9), improvable by noise from level-7 and level-8 cells below the bound. | The plateau is never declared; END_BUDGET becomes the only stop. | Plateau = three campaign nights with no faster verified clear and no increase of I3. |
| S2 | The `fresh` counter's value at import is undefined. Starting every inherited cell at 0 re-dispatches the whole archive as new (the flooding the proposal rejects for V5-a). | The first night's dispatch mix is decided by an unstated default. | Compute `fresh` from the ledger at import (dispatch events per cell since the iteration of its last strict shortening) and report its distribution in the C0 census. |
| S3 | r(l) is under-defined: which bursts count (all pools or the ahead pool; a continued job once or per segment); whether the window is seeded from the inherited ledger or starts empty (then r = 1/2 at every level); and the ahead cells' own record differs from the level's (reached deeper from ahead cells: level 3 27 of 259, level 4 6 of 307, level 5 6 of 296, level 6 0 of 25, level 7 0 of 6). | Two implementations of the same text give different weights. | Define it per pool, seed it from the inherited ledger, count a job once, and log the value used at each dispatch. |
| S4 | The lock-in moves to the 1,237 lineage. The ahead pool's level-7 members are its 31 cells (same mask as the record, right side at x 2,700 to 3,000, y 3,900 to 4,200; 17 dispatches ever, 0 new cells, never left of x 600). PFS gives them about 2,949 dispatches per night. | That is the experiment, and it is a fair one, but the design should say so and bound it. | Pre-declare it, and pre-declare the exit: the `fresh` counter alone takes 100 dispatches to cut a cell's weight to 0.1; add a per-night cap per cell or a share decay for levels whose ahead cells produce no new cell. |
| S5 | The pace pool funds what the archive already does: shortenings ran at 2,699 per million ticks in sd2 with no route gain, because nothing propagates a faster arrival. Only continuation (at most 480 words) and splices propagate. | A third of the mass buys refinement the ledger shows to be free. | Make the pace pool the smallest share (or merge it into the tail pool) until a propagation operator is shown to work. |
| S6 | 36,000 dispatches per night is realistic for the first night only. sd2's rate (4,500 per hour) holds at its dispatch mix; PFS's shallower mix shortens returns and pushes the pipeline to the 3 s process start-up bound (about 5,000 to 6,000 per hour), then M5's growth slows it. N = 5 with one standby each equals the ten-process cap (`max_battleship_processes = 10`, a registered guard constant); a second standby or N = 6 needs a lab guard configuration the owner sets. On 16 GB: sd2's tree peaked at 4.7 GB private with 10 processes plus 3.1 to 3.6 GB of Claude processes; a night without sessions has room for N = 5, and N = 6 with two standbys (about 18 processes, 6 GB plus the main process) only if nothing else runs. | The budget per night is quoted as a constant; it is a first-night figure. | Measure dispatches per hour in the first lab night and quote the measured figure; keep the readiness and stop thresholds; state the lab process cap explicitly. |
| S7 | E6 off changes eligibility of the inherited archive, not only the selection: low airborne cells pruned since rd2 become eligible. The "control = v4 minus E6" therefore differs from registered v4 in the eligible set. | The equality test and the first comparison must separate the two effects. | C0: equality test with E6 on (must reproduce the registered masses), then an E6-off census (cells made eligible per level and their mass) reported before the first run. |
| S8 | In-run verification must use the verify flag set in a fresh process (the registered path's `SSB64_RL_ENTITY`, `_INPUT`, `_TARGET_DIAG` on top of the explore flags). A clear "verified" by a worker in explore mode is not registration-equivalent. | A lab claim that later fails registration voids the run. | R6 replays through `run_stepping_trace` with the verify flags, as `m8_rd_session.replay` does. |
| S9 | The splice pass criterion "does any splice keep the donor's later breaks" can pass on a static target and fail where it matters. | R5 could be added on a result that predicts no clear. | Pass = a strictly faster verified clear, or survival past the first moving-object interaction after the splice point; report per candidate the ticks and breaks survived and the divergence tick. |
| S10 | Lab non-negotiable 6 says no registered session reads the lab root; it should also say no lab run reads `runs/` except the one hashed archive copy. | The provenance guard's forbidden fragments cover TAS and recordings, not registered trees. | Add the registered roots to the lab guard's forbidden list, with the single copy as the only allowed read. |
| S11 | The lab needs a rule for a prefix that no longer replays (a `prefix_end` mismatch). The registered path stops INVALID; a campaign that stops on one stale cell loses the night. | Not a correctness issue, an availability one. | Quarantine the cell (mark ineligible, log it), continue, and count quarantines in `summary.json`; more than a handful in a run is LAB_INVALID. |

**NOTE**

| id | note |
| --- | --- |
| N1 | All verified figures reproduce exactly (section 1); the approximate v4 census reproduces the sd2 review's level masses to the decimal (3.4, 3.8, 4.3, 4.9, 5.7, 6.8, 8.5, 11.4, 17.1, 34.1 %), which validates the method behind M2 and M3. |
| N2 | F3 has an upward bias from truncation: a reach in a length-ended burst's last 20 words is non-doomed only because the burst stopped; with continuation some will fall within 60 ticks and become doomed. Of the last-20 wins, 7,681 are new cells and 8,409 replacements; replacement gains have quartiles 3 / 24 / 71 ticks, and 2.4 % are one-tick gains. |
| N3 | Continuation's value is cost, not productivity: 120 more words cost about 0.14 s of stepping against about 2.8 s for a fresh dispatch (20 times cheaper per explored tick), but it does not fix the 92 %: if a third of jobs continue once, the burst share rises from 7.7 to about 10 % of ticks. The only thing that removes the return is a native batched prefix (deferred) or a savestate (forbidden). |
| N4 | The 92 % is not pure waste: the prefix replay is also the determinism check at L (end state, record digest, chain), which the archive's integrity rests on. |
| N5 | The twelve "similar" level-4 splice candidates are all in status class A0 (up-B or helpless) at route ticks 623 to 682 with gains of 219 to 363; the two at level 7 are cell 10406 at tick 1,451 (gain 113, between the route's two rides on the moving platform at 1,369 to 1,396 and 1,473 to 1,519) and cell 11141 at tick 1,514, grounded on the moving platform itself (floor line 19; its phase differs by the gain by construction). |
| N6 | The horizon is not a constraint on continuation: E7 bounds every eligible L at 1,860, so L + 480 ≤ 3,600 always holds. |
| N7 | The decisions record (2026-10-13) says a continued speed line starts with a v5 proposal evaluated offline; this proposal is that, and the offline part is largely done in the analysis, the proposal's F-figures and this review. |

## 1. The proposal's key figures, verified independently

Every figure was recomputed from `runs/m8_rd_sd2/archive/` (cells, burst index, events) and the 1,885 route trace by the reviewer's own scripts;
replaying the ledger's new / replace / keep rows reproduces all 49,927 non-root representatives (0 mismatches), so the per-cell L values the
figures depend on are the archive's own.

| figure | proposal | recomputed | holds? | what it depends on |
| --- | --- | --- | --- | --- |
| F1: prefix (return) share of exploration ticks | 92 %; 2.32 M new of 30.1 M | 27,742,728 prefix + 2,320,750 burst = 30,063,478 of 30,064,502 ingest ticks (prefix 92.28 %, burst 7.72 %); per session 90.3, 90.6, 90.6, 93.6, 93.7, 93.2 % | **yes, exactly** (1,024 ticks of sd1 are three empty ingests) | the ingest events' `ticks` and each burst's `start_L` and `n`; mean prefix 1,301 words per burst, mean burst 108.8 |
| F3: length-ended bursts productive in their last 20 words | 5,314 of 16,338 (32.5 %); 27 % at level 7, 49 % at level 8 | 5,314 of 16,338; level 7 1,063 of 3,950 (26.9 %); level 8 670 of 1,364 (49.1 %) | **yes under F3's definition**; **no as R4's trigger** (119 of 16,338 at the time, 180 in hindsight; level 7 4, level 8 10, level 9 19) | the definition of "productive": any non-doomed win (new or replace) in the last 20 words, with hindsight doom; see M1 and N2 |
| F3 split | not given | new cell in the last 20 words: 2,610 (16.0 %); a replacement gaining ≥ 10 ticks: 2,312 (14.2 %) | | |
| F5: splice candidates on the 1,885 route | 198 of 310 route cells earlier; 143 by ≥ 30 ticks, all at levels 2 to 7; level 4 39 of 40, median gain 362, max 487; level 6 53 of 60 earlier, 40 by ≥ 30; level 7 26 of 75, 16 by ≥ 30, max 209; 14 similar | 310 route keys; 198 earlier; 143 by ≥ 30 (levels 2: 15, 3: 33, 4: 39, 6: 40, 7: 16; level 5 none, max 11); level 4 max 487; level 7 max 209; 14 similar (12 at level 4, 2 at level 7) | **yes, exactly** | the route chain (38 bursts), the per-burst first reaches, the current representatives, and the 17-field end state; "similar" = velocities within 10, same facing, jumps used and status |
| F5 addition: candidates with no moving object ahead (route tick > 1,519) | not given | 8 level-7 cells with gains 209, 196, 183, 168, 129, 94, 90, 48 (airborne A1/A0/A2, position offset 95 to 273 units, none similar); the wall-top landing cell 18767 (route 1,694, representative 1,683, gain 11, offset 222); small level-8/9 gains of 1 to 3 ticks | | these nine are the probe's real question (section 4) |
| spot-checks (cells, shortest L, level-7 bursts and breaks, cumulative bursts, falls) | as the analysis | 49,928 cells; 26, 91, 152, 254, 433, 871, 1,237, 1,776, 1,832, 1,885; 4,734 and 14; 2,175 / 6,212 / 10,406 / 13,886 / 17,554 / 21,323; 4,965 falls, 20 clears | **yes** | |
| transition rates by level (analysis section 6, used by R2) | 23.8, 23.9, 18.1, 9.6, 2.2, 2.0, 1.5, 0.3, 5.5, 0.6 % | over all bursts 23.9, 24.0, 18.2, 9.7, 2.3, 2.1, 1.5, 0.3, 5.5, 0.6 %; over the last 1,000 per level 23.9, 24.0, 19.4, 10.9, 2.8, 2.3, 4.3, 1.2, 7.2, 1.3 % | **yes** (the window estimate at level 7 is 1.2 % because sd2's bursts are the window) | the 1,000-burst window; see M3 |
| about 4,500 dispatches per hour; 36,000 per night | | sd2: 3,769 in 3,004 s = 4,517 per hour | **yes for sd2's mix**; see S6 and M5 | the job mix and the archive size |

**What could not be determined offline:** whether any splice survives; whether any ahead front can cross; the run-to-run spread of I1 to I4
in a 4-hour run; dispatches per hour under PFS's dispatch mix; bytes per cell in the main process.

## 2. In-process continuation: feasibility

**The harness allows it.** `run_iterate` replays the prefix with the tick-0 pin, the end-state, record-digest and chain checks at L, then
steps keyed words in the same process until length, a fall, the native end or the horizon, and closes the process in `finally`. After a
"length" end the process is alive in `WaitingForAction`. Continuing is stepping more words of the same keyed stream in the same episode: every
step still checks `consumed_tick == i`, `input_tick == i + 1`, `step_count == i + 1`. Nothing is reset, saved or restored, so "process restart
resets the episode" is untouched: a continued job is one longer episode, and the next job is still a new process. The archive format already
stores `n` per burst and the ingest accepts any `n` (it checks only `start_L < j <= start_L + len(words)`), and `rep_words` rebuilds prefixes
from any burst length. The explorer contract digest names 120 words, so continuation is a new explorer contract version, which a new line
needs anyway.

**What must be true for exact replay from tick 0 to verify every clear (all already true, or made true by one definition):**

1. A clear's words are the concatenation of its lineage's stored words plus its own burst, all canonical Track 1 words. Continuation keeps
   this as long as the whole continued job is ingested as **one** burst row (also needed so that a fall after word 120 dooms reaches made
   before it; M1).
2. The words are re-derivable from keys. Define the burst as the first n words of the stream `words(explore_key(archive_id, iteration, ·), 480)`
   with n in {120, 240, 360, 480}: `words()` clips holds only at its end, so the first 120 words of the 480-stream equal today's 120-word
   burst, and a continuation never changes words already played. Then word provenance needs only n.
3. The same executable, runtime files and flags (the pinned `30a3913b` copy, `FrozenRuntime`'s cfg and imgui pins, the tick-0 pin's line
   digest).
4. Verification in a fresh process under the verify flags (S8).

**Hidden assumptions, found:**

- "The job carries the B and R tables at dispatch, so the decision is local and deterministic." Deterministic given the tables, but the tables
  at dispatch depend on the parallel ingestion order (non-reproducible, as the proposal itself notes in 6.4), so the length of a burst cannot be
  re-derived from the ledger. Harmless for the lab (the six-part audit is dropped) and for registration (n is recorded), but say so.
- "New or strictly shorter non-doomed cell" is not decidable from B and R alone: it needs the archive's key → (L, doomed) map (49,928 entries
  now, 100,000 or more after a night). Either ship a snapshot per job (megabytes, refreshed every few dispatches) or ask the main process at
  the boundary (one round trip of a few milliseconds). The round trip is simpler and uses current tables; log the decision inputs.
- Doom is unknowable at the boundary (M1).
- The tick allowance per job must cover up to 480 extra words or cut the job; the existing "cut" path ingests the words played so far.
- Continuation changes the standby cover: longer jobs leave the standby waiting less, so the throughput lever and the exploration lever are
  confounded in any comparison (the proposal says so; the fix is to report burst ticks beside dispatches and compare per burst tick as well).

## 3. The pace-frontier selection

**Generic and stage-agnostic as specified: yes.** R2 to R3b read levels (popcount of the mask), masks, L, the archive's own verified clear's
break table, dispatch counts and transition counts; no position, surface, target identity, cid, route tick or census number. The constants
(shares 1/2, 1/3, 1/6; kappa 8; window 1,000; three continuations; 10 %) are design-time choices tuned on Mario's archive, which is the audit's
C6 class: record their origin, as the proposal says. Two things the specification leaves open are listed in S3.

**Does it starve the end?** It cuts the end's mass from 51 % (levels 8 and 9 under v4) to about 15 %. The end is at its physical floor (the
ending about 1 tick, the 6-to-8 leg about 14), so that is defensible, but the one leg with slack, the landing-to-target-6 leg, lives in the
level-7 crossing cells, and PFS halves their share (M2). Approximate level masses at the sd2 close, v4 against PFS: 3.4 / 3.8 / 4.3 / 4.9 /
5.7 / 6.8 / 8.5 / 11.4 / 17.1 / 34.1 % against 3.9 / 8.2 / 9.3 / 12.3 / 12.4 / 12.6 / 12.9 / 13.3 / 6.2 / 9.0 % (levels 0 to 9; `fresh`
approximated by `seen`, so the PFS figures for heavily seen cells are lower bounds).

**Does it overfit noise in per-level pace?** Not under kappa 8, because every level from 3 up is at the cap whatever the window says: at level
7 the window holds 3 ± 2 breaks per 1,000 bursts, so 1/r swings between 170 and 1,000, all capped. If kappa is raised to express the
bottleneck, the level-7 share would swing two- to three-fold between windows; a longer window or a prior proportional to the level's all-time
count would be needed.

**Does it move the lock-in?** Yes, to the 1,237 lineage (S4) and, unintentionally, to the 23 ahead cells of levels 1 and 2 (M3). The
ahead pool compares L against R(l) by level, not by order, so every ahead cell at levels 3 to 5 (806, 874, 752 cells) is an "other order"
partial whose continuation must re-solve six or seven levels including the crossing and the two moving objects. Their leads (up to 447) are
the old right-side slack the record never used; whether any of them leads anywhere is the question the archive cannot answer. The ahead
pool is the right experiment; its shares should follow cell counts (M3) so that the right-side partials and the level-7 front are funded in
proportion, and the stopping condition for a front that produces nothing should be written before the first night (S4).

**Is the online bottleneck rule well defined?** Not yet (S3). It also measures the wrong population: the rate over all level-l bursts, while
the pool funds only ahead cells, whose own record is 0 of 25 at level 6 and 0 of 6 at level 7.

## 4. The splice probe

**Allowed under the rules: yes.** The donors are the agent's own verified clears, the candidates' prefixes are the agent's own bursts, every
word is a canonical Track 1 word, and the words replay from tick 0 in a fresh process. "The agent's own trajectories may be used" covers it,
as M9's backward curriculum along the agent's own route did. Disclosure: a splice-made clear's words come partly from an older clear, which the
lineage walk and word provenance must show (the proposal's `frs_verify` does). A splice is not a hidden action and not a hand-written route.

**What it would show.** Per candidate: how many ticks and breaks of the donor's continuation survive from the representative's end state, and
where the run diverges. The nine candidates with no moving object between them and the clear (eight airborne level-7 cells in the flight to
the wall top with gains 48 to 209, and the wall-top landing itself with gain 11) are the only ones where survival would be a faster clear at
once; all others must pass target 2 (moving, broken at 1,339) or the moving platform (1,369 to 1,519) at a phase shifted by the gain, or, at
levels 2 to 4, the fireball break of target 3 at 880 from a position that depends on the exact state. The state comparison in F5 covers five
of the fields that matter; position inside the 300-unit bin (offsets of 95 to 273 units for the nine), animation frame, status timers, hit
freeze and the moving objects' phase are not compared and cannot be, offline.

**How a positive could mislead.** (i) A verified faster clear cannot mislead: the replay is deterministic, and a route that works by a
coincidence of state is still a route. (ii) Partial survival can: the donor's words may break the next static target from a slightly different
state and then diverge, so "some later break survives" would pass on the easy part (S9). (iii) The twelve "similar" level-4 candidates are all
in up-B or helpless status, where inputs barely change the motion; a splice there can look right for a stretch for a reason that says nothing
about splices in general. (iv) A gain equal to a multiple of a moving object's period would survive by coincidence and overstate the operator's
yield. The pass criterion should therefore be a faster verified clear or survival past the next moving-object interaction, reported per
candidate, and the operator's expected yield should be stated from the number of candidates that survived, not from the best one.

**Cost and the first result.** Nine episodes answer the direct question in one minute; the full 198 × 3 donors in under 45 minutes. No new
module is needed (M6).

## 5. Lab mode

**Non-negotiables: sufficient for honesty, with four additions.** The nine listed items cover the forbidden data, RNG, the tick contract,
generic rules, the meaning of "clear", separation of evidence, the pinned executable, machine safety and Git. Add: the verify-flag process for
in-run verification (S8); the registered roots in the lab guard's forbidden list (S10); the measured memory budget and an archive-size stop
(M5); and the quarantine rule for stale prefixes (S11). The code-copy-and-hash per run, the `mode` field and the hash-first registration keep
registered evidence safe; the lab root outside the checkout (Q3 (a)) keeps the coverage checks clean.

**The comparison protocol.** Equal wall, N = 5, two paired replicates in ABBA order, two control replicates for the spread: see M4. In short,
the protocol can detect only effects larger than about twice the run-to-run spread of the metric, and the spread is unknown because two
control points do not estimate it. Three replicates per arm is the smallest design in which "better in every pair" is not a coin flip
(p 0.125); with equal wall and the first-night spread measured, the keep rule should be "not worse on I3, better on I2 in every pair, or a
faster verified clear in any pair", and C1 should be read as a mechanism check. The honest statement for the lab index: comparisons are
screening, campaigns are evidence.

## 6. The November plan

- **Checkpoints.** C0 should add the E6-on equality test followed by the E6-off census (S7), the `fresh` distribution at import (S2), and the
  memory and throughput measurements (M5, S6). C1 as a mechanism check (M4). C2's fresh arm (R10) for one night is reasonable: one lab night is
  about twice the six-session history in ticks, and rd1 plus rd2 (7.4 M ticks) solved the crossing once, so a first crossing in one night is
  plausible but a clear is not; pre-declare that R10's success metric is I3, not I1. The week-2 weekend campaign cannot run before M5 is fixed.
- **Stopping rules.** The pre-declared checkpoint rule needs M4's repair of its tie case. The 48-hour campaign and the three-night
  plateau both need the archive-size policy.
- **The five line-ending conditions.** END_PLATEAU: repair per S1. END_BUDGET (2026-11-27): sound. END_DEFECT: sound. END_MACHINE ("two
  machine-guard stops in one week"): sound only once archive growth has its own stop, otherwise the design ends the line on the first weekend.
  END_OWNER: sound. Nothing is missing except an archive-size stop and, optionally, an END_NO_PATH (C0 or L0 failing twice).
- **36,000 dispatches per night on 16 GB.** Realistic for the first night at N = 5 (S6): sd2 ran 4,517 per hour with 10 BattleShip processes,
  a 1.4 GB main process and 3 to 4 GB of idle Claude processes resident, and overnight without sessions is more comfortable, not less. It is not a
  constant: the shallower PFS mix raises it towards the process-start bound, archive growth lowers it, and N = 6 or a second standby needs a lab
  process cap above the registered 10.

## 7. The sixteen open questions

| # | proposal's recommendation | this review | where it differs and why |
| --- | --- | --- | --- |
| 1 | (b) interleave: lab nights on Mario, Donkey Kong by day | Run the splice replay first (one minute of native time for the nine, under authorisation), then (b) once the lab runner exists; the decided order (Donkey Kong first by day) stands. | Agrees in substance; disagrees that R10 "is the Donkey Kong configuration anyway": before a first clear R10 is novelty search with a pace pool, and Donkey Kong's first search should be the plain novelty configuration (v1/v2 without E6), which is what found Mario's first clear. |
| 2 | lab mode as written, one review of the lab path | As written plus S8, S10, M5 and S11, and three replicates for a KEEP (M4). | Stricter on four points, all enforceable in code. |
| 3 | (a) sibling folder outside the checkout, weekly D: copy with a hash manifest | (a). | Agrees. |
| 4 | the sd2 archive copy for weeks 1 and 2; R10 one night in week 2 | Agrees, with the E6-off census (S7) and the `fresh` import rule (S2) stated before the copy is used. | Adds two preconditions. |
| 5 | drop E6 everywhere | Drop everywhere, after the E6-on equality test at C0. | Agrees; adds the ordering. |
| 6 | run the probe first | Run it first, before any module, over all 198 candidates and all three verified clears, with S9's criterion and per-candidate reporting. | Agrees and widens it (gains ≥ 1 included: the wall-top landing's 11-tick gain is the cleanest candidate of all). |
| 7 | accept the constants as lab starting values | Disagrees: the offline census already shows kappa 8 is flat and the levels 1 to 2 pathology (M3) and the level-7 reference problem (M2); fix those two before the first run, accept the rest. | The census is cheap and was the proposal's own acceptance criterion for C0. |
| 8 | equal wall, N = 5, 2 paired replicates, 2 controls | Equal wall, N = 5, **3** replicates per arm for any KEEP, burst ticks and dispatches reported beside every metric. | M4. |
| 9 | three nights without a faster clear and without a new best at the deepest three levels | Three nights without a faster verified clear and without an I3 increase. | S1. |
| 10 | (a) replay, provenance, lineage; (b) only for a method claim | (a). | Agrees. |
| 11 | macros allowed, capped at the hold maximum, week-3 ablation | Agrees; the cap at 16 words is the explorer's own constant and the words come from the agent's bursts, with disclosure. | Agrees. |
| 12 | defer D2 | Defer. | Agrees. |
| 13 | measure throughput levers once, never inside a comparison | Agrees; add that the lab process cap is the owner's setting, written in the lab config, never lowered thresholds. | Adds the cap. |
| 14 | tracked lab index, committed weekly | Agrees. | |
| 15 | R(l) from the best verified clear | Agrees for the ahead pool's lead. For the length factor, no reference works at level 7 (one mask): drop the factor in the pace pool (M2). | Partly disagrees: the question conflates the lead reference with the length reference. |
| 16 | `rl/frs_*`, `tools/frs_lab/`, task-parameterised | Agrees, with one addition: the first deliverable is a script over existing tools, not the family (section 9). | |

## 8. What is missing, simpler alternatives, the cheapest first experiment

- **The cheapest first experiment** (M6): replay the splice candidates with the existing tracer. Nine episodes decide whether a faster clear is
  already in the archive; 600 decide whether R5 exists. Zero modules, one authorised native run of under an hour.
- **The second cheapest**: a continuation-only night. v4 with E6 off, plus continuation as the F3 condition, against v4 with E6 off: two arms,
  the cheapest code change, and it measures the throughput lever and the run-to-run spread that every later decision needs.
- **The third**: Option A's selection in lab mode (the `fresh` counter alone) before any pool. The sd2 review's diagnosed mechanism is the count
  term; one night tests it in isolation.
- **A simpler ahead pool**: the sd2 review's V5-d (level share proportional to lead) with a flat cell draw does most of R2 with one constant
  fewer, and it is what M3 reduces R2 to.
- **Missing risks**: archive growth (M5); the `fresh` import default (S2); the E6-off eligibility jump (S7); stale prefixes in long campaigns
  (S11); the ten-process cap (S6); the pace pool's lack of a propagation mechanism (S5); and a front that produces shortenings forever without
  a new cell (the 1,237 lineage's pattern: 225 shortenings, 0 new cells) which neither `fresh` nor the ahead pool detects quickly (S4).
- **Missing from the odds**: the 60 to 80 % for "a clear shorter than 1,885 by the end of November" rests on the tail pool and ten sessions'
  worth of dispatches per night; the sd2 review's floors leave about 15 ticks at the end plus the landing-to-6 leg, which PFS funds less than
  v4 did (M2). The odds are not unreasonable, but their grounds point at the leg the design under-funds.
- **Something the proposal gets right that this review would keep unchanged**: in-run verification, the lab root outside `runs/`, the
  code-copy-and-hash per run, word provenance, the fresh arm as the lock-in test, and the "reading less" rules.

## 9. Recommended build order for November

| step | what | size | why first |
| --- | --- | --- | --- |
| 1 (zero modules; before week 0) | `logs/frs_probe/splice_replay.py`: build the 198 × 3 word lists from the archive (representative prefix + donor words from the reach tick), replay each through `m7f_trace.run_stepping_trace` with the verify flags and the pinned executable copy, run `analyse_trace`, write one row per candidate (ticks survived, breaks survived, divergence tick, outcome). Run the nine post-platform candidates first. | about 150 lines, one session of 2 to 3 hours; native time under one hour under the owner's authorisation | Decides R5 and may hand over a faster clear before anything is built. |
| 2 (week 0) | The minimal lab runner: import sd2's `Archive6` and the worker unchanged; an E6 switch; continuation as the first n words of the 480-stream with F3's trigger, ingested as one burst; in-run verification through the tracer with the verify flags; TOML config; 15-minute checkpoints; code copy and hashes; pinned executable; machine guard with a lab process cap; `summary.json`; the equality test (v4 masses with E6 on); the synthetic-backend end-to-end test; the memory and bytes-per-cell measurement. No pools. | about 800 to 1,200 lines plus tests; 8 to 10 hours of sessions; one independent review of the path | The smallest runnable lab; every later variant is a selection subclass on it. |
| 3 (night 1) | v4 (E6 off) against v4 + continuation, 4 hours each, ABBA, from the same archive copy. | one night | Measures the spread, the throughput lever, dispatches per hour under lab conditions and memory growth: the four numbers every later decision needs. This is the first night that gives the most information. |
| 4 (week 1) | The `fresh` counter computed from the ledger at import; the ahead pool as a pooled draw (M3); I1 to I4; the census with pre-declared expectations (including the crossing band and the levels 1 to 2 share). | about 400 lines; 4 to 6 hours | The diagnosed mechanism and the one new idea, isolated from each other by nights 2 and 3 (fresh alone, then fresh + ahead). |
| 5 (week 2) | R10 one night (metric I3); the pace and tail pools only if night 2 and 3's census shows a gap they fill; R5 only if step 1 passed; the archive-size policy before any campaign. | | |
| 6 (week 3) | R8 and R9 as ablations, each a three-replicate pair; campaign nights afterwards. | | |

## Appendix. Working files (Git-ignored, `logs/frs_review/`)

| file | content |
| --- | --- |
| `scripts/r1_checks.py`, `r1_checks.json` | F1, F3 (the proposal's definition and the R4-trigger variants, at the time and in hindsight), per-level transition rates with the 1,000-burst window and the kappa-8 weights, the ahead pool census, F5 with the post-platform candidates and the wall-top landing, the deepest-level masks for the plateau rule, archive growth and sizes |
| `scripts/r2_census.py`, `r2_census.json` | masks per level, the level-7 crossing band under a per-mask reference, approximate v4 and PFS level masses, the 1,237 lineage's and the crossing band's masses |

## Appendix B. Compliance of this review

| constraint | how it was kept |
| --- | --- |
| zero native ticks | no `BattleShip.exe`, suite, preflight, launcher or run-creating tool was started; the archive was read as files |
| no tracked file modified; nothing under `runs/` or on D: changed | only this record and `logs/frs_review/` were written; D: was not touched |
| no RNG inspection, logging, control, comparison or hashing | nothing touched RNG |
| no TAS, human recording or owner run read or used | the one trace read is the agent's own verified 1,885 clear |
| no commit, push, branch or pull request | `git status` at the end shows only this record as untracked |
