# M8-rd1 archive diagnosis and the M8-rd2 stop (2026-10-02)

**Status: read-only analysis. Zero native ticks.** No BattleShip process was launched. Nothing was committed, pushed, trained
or edited; the frozen rd1 archive (`runs/m8_rd/`, 166 files) and every existing document are unchanged. This file is the only
addition.

**Scope.** Part A explains, from the preserved rd1 archive and logs alone, why neither arm reached the wall top. Part B records
why the requested M8-rd2 continuation session was **not run**. This is a report, not a design change: selection, the cell
key and every setting are as rd1 left them.

Related: `docs/rl_m8_rd_proposal_2026-10-01.md` (revision 2), `docs/rl_m8_rd_amendment_2026-10-02.md`,
`docs/rl_m8_rd_implementation.md`, `docs/rl_m8_rd1_results_2026-10-02.md`.

## 0. State and method

| item | value |
| --- | --- |
| checkout | `main`, `HEAD` = `origin/main` = `9f2b674`, working tree clean before this file |
| archive | id `m8_rd_a1`, checkpoint sequence 7 (manifest verified on load), 8,264 cells, 2,175 bursts, 4,350 ledger events |
| executable | `build-us/Release/BattleShip.exe` sha256 `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee`, last written 2026-09-28, equal to the archive pin |
| what was read | `runs/m8_rd/archive/*`, `runs/m8_rd/sessions/rd1/*` (ledgers, candidates, close record), the two saved routes; the pure modules `rl/m8_rd_archive.py` and `rl/m8_rd_cells.py` were imported with bytecode writing disabled |
| what was not done | no native replay, no cell re-verification, no change to any file under `runs/` |

**Method.** The ledger was replayed over the stored bursts (the same procedure as the close audit's `rebuild`), and before each of
the 2,175 dispatches the eligible-level distribution was recorded. The rebuilt selection equalled the ledger's cell for all
2,175 dispatches and every rebuilt cell equalled the stored one. All positions below are the stored **representative** of a
cell: the first live reach (or the shortest later reach) of its 300-unit bin, so a position is exact for that tick but the
true extreme of a bin may lie up to one bin (300 units) further. Positions are in game units; the wall-top floor (line 0)
runs x -2100..-1200 at y 3000, the right-hand ledge corner is (-1200, 3000), the wall's right face is x -1800 (Mario's
centre stops at x -1650), the main floor is y -2550.

## Part A. Why neither arm reached the wall top

### A1. How selection probability was split across target levels

`m8_rd_select_v1` draws a level with weight 2^-(top - level) over the levels that have eligible cells, then a cell inside the
level. Over the 2,175 dispatches of arm T:

| level (targets broken) | analytic expected dispatches | realized | final cells | final eligible |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 45.8 (2.1 %) | 52 | 209 | 209 |
| 1 | 81.6 (3.8 %) | 84 | 547 | 547 |
| 2 | 144.5 (6.6 %) | 132 | 645 | 645 |
| 3 | 195.3 (9.0 %) | 195 | 1,079 | 934 |
| 4 | 326.6 (15.0 %) | 370 | 1,286 | 1,011 |
| 5 | 362.1 (16.6 %) | 370 | 1,261 | 1,035 |
| 6 | 704.9 (32.4 %) | 664 | 1,648 | 1,328 |
| **7** | **314.2 (14.4 %)** | **308 (14.2 %)** | 1,589 | 1,251 |

- **The top level took half of the returns, as designed.** The then-current top level received 51.1 % of the analytic mass
  (49.4 % realized), and 50.2 % while level 7 was the top.
- **Level 7 became the top level late.** First dispatch index at which each level was the top eligible level: 0 at #0, 1 at
  #5, 2 at #19, 3 at #101, 4 at #161, 5 at #443, 6 at #462, **7 at #1549** (cumulative tick about 1.53 M). Level 6 was the top level for 1,087 dispatches
  (50 % of the run), which is why it received the largest share of returns (32.4 %); level 7 was the top level for 626 (28.8 % of the run).
- **Inside level 7 the mass is thin.** The 308 dispatches fell on 1,251 eligible cells (0.25 per cell). At the close an eligible
  level-7 cell has a per-dispatch probability of about 4.0e-4; over all 6,960 eligible cells the final per-dispatch probability
  ranges 8.8e-6 to 5.9e-4 (uniform would be 1.44e-4). Level-7 eligible prefixes have L 1,355..1,797 (median 1,604); the length factor
  inside the level ranges 0.671..1.000 (mean 0.793), so it is not what spreads the mass.
- **The level axis is the number of targets broken, not position.** Level 7 is exactly the mask `0101000010` (live targets 1, 6, 8, the three
  left-of-wall targets). Level 6 is `0101000110` (the same plus the moving target 2).

### A2. The archive's closest approaches to the wall top

Mask is the 10-bit live-target mask (bit i = target i still live). `A0` is airborne without the up-B (the up-B in progress, or helpless).
Distances are to the ledge corner; the distance to the nearest point of the line-0 floor is the same for all cells listed.

**Highest cells.** Only two cells reach y 3,000.

| cell | x | y | vx / vy | class | mask | level | prefix L | distance to ledge |
| ---: | ---: | ---: | --- | --- | --- | ---: | ---: | ---: |
| 6461 | 1,774.7 | **3,247.0** | -31.1 / +11.2 | A0 | `0101000110` | 6 | 1,347 | 2,985 |
| 6460 | 2,029.6 | 3,054.4 | -59.8 / +64.8 | A0 | `0101000110` | 6 | 1,341 | 3,230 |
| 6459 | 2,089.4 | 2,989.6 | -65.7 / +75.3 | A0 | `0101000110` | 6 | 1,340 | 3,290 |
| 5764 | 3,013.0 | 2,889.2 | +29.8 / +38.1 | A0 | `0101000010` | 7 | 1,364 | 4,215 |
| 6332 | 892.2 | 2,657.6 | -26.1 / +20.2 | A0 | `0111001110` | 4 | 1,038 | 2,120 |

**Cells nearest the wall-top floor.**

| cell | x | y | vx / vy | class | mask | level | prefix L | distance |
| ---: | ---: | ---: | --- | --- | --- | ---: | ---: | ---: |
| 7989 | -769.1 | 2,078.8 | -9.0 / -24.8 | A0 | `0101000110` | 6 | 1,072 | **1,017** |
| 7988 | -633.4 | 2,134.8 | -35.7 / +18.8 | A0 | `0101000110` | 6 | 1,065 | 1,034 |
| 7987 | -597.7 | 2,116.0 | -40.1 / +27.0 | A0 | `0101000110` | 6 | 1,064 | 1,070 |
| 7990 | -760.9 | 1,762.0 | +6.4 / -46.7 | A0 | `0101000110` | 6 | 1,080 | 1,314 |
| 7986 | -349.8 | 1,888.6 | -65.7 / +75.3 | A0 | `0101000110` | 6 | 1,059 | 1,399 |

**With the up-B still available (A2/A1)** the nearest cell is 5835 at (-3.3, 1,244.2), class A1, level 5, L 1,049, 2,125 from the ledge, and the highest
is 5817 at (3,604.8, 2,004.8), class A1, level 6, L 1,370.

**The two necessary conditions occurred in different bursts.** Each is documented from the burst's own stored reaches.

- **Height without position (burst 1634, start cell 4708, A2 at (2418, -146), L 1,234).** A jump and a double jump rose over x about 2,775 to
  (2,773, 1,802) (cell 6454, A1). The up-B began near (2,883, 1,890), flew left at vx -117 decaying to -31, and peaked at (1,775, 3,247) at L 1,347.
  The apex is above 3,000 but 2,985 units right of the ledge corner.
- **Position without height (burst 2063, start cell 2890, A2 at (1082, -21), L 1,023).** The first stored up-B cell is (146, 1,264) at vy +147; the flight peaked at (-633, 2,135), then fell
  through (-769, 2,079). It reached x -769, 1,017 units from the floor line, but its apex was about 865 units below 3,000. The up-B start height is not stored, only the cells reached; it is lower than 1,639 because the apex is.
- This is the physics of the known limit: the up-B adds a fixed +1,361.3 and reaches y 3,000 only from a start of at least about 1,639
  (`docs/rl_m8_rd_proposal_2026-10-01.md` section 2, from the M7p flights).

**Other extremes.**

- No cell stands on floor line 0 (grounded cells: floor 1 x 32, floor 2 x 31, floor 4 x 138, floor 0 x 0). No cell has x < -1,650; minimum x is -1,650 exactly, held by 97 cells (A1 38, A0 35, A2 20, grounded 4) at y -2,550..648.8, that is, Mario pressed against the wall face at many heights. Only 5 cells with x <= -1,600 are at y >= 0, the highest at y 648.8; the highest cell left of x -1,500 is 4252 (see below).
- The best height at x <= -1,200 is 1,252.3; at x <= -1,500 it is 1,207.6 (cell 4252 at (-1,569, 1,207.6)).
- **At level 7 nothing at y >= 1,000 lies left of x 730.** The best level-7 cell (5764) is at (3,013, 2,889) and the best level-7 A2/A1 cell is at y 1,754.6. The only cells that
  approached the wall area belong to levels 4-6.

### A3. Airborne cells with the up-B available near or below wall-top height

Cells with the up-B still available (A2: double jump and up-B; A1: up-B only), by the height of their stored position. "Dispatches" counts returns that started
from a cell in the band; "analytic mass" sums the per-dispatch probabilities at the time of each dispatch.

| band | cells | eligible | dispatches | analytic mass | bursts that visited them | new cells produced |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| y < 0 | 3,892 | 3,374 | 1,053 (48.4 %) | 1,076.4 (49.5 %) | 16,334 | 4,350 |
| 0 <= y < 1,000 | 421 | 421 | 108 (5.0 %) | 109.6 | 1,168 | 669 |
| 1,000 <= y < 1,639 | 79 | 79 | 9 (0.41 %) | 11.6 | 132 | 57 |
| **1,639 <= y < 2,400 (can reach 3,000)** | **14** | 14 | **2 (0.09 %)** | **2.0** | 19 | 25 |
| y >= 2,400 | 0 | 0 | 0 | 0 | 0 | 0 |
| all A2 + A1 | 4,406 | 3,888 | 1,172 (53.9 %) | 1,199.6 (55.2 %) | 17,653 | 5,101 |

- **Total A2/A1 cells: 4,406** (A2 1,224, A1 3,182). **Launch-capable (y >= 1,639): 14, all A1.** No A2 cell (double jump still available) is above y 909.6.
- **They were selected 2 times, as often as their expectation (2.0).** They were scarce, not suppressed: 14 of 8,264 cells. Four were created at iteration 1,081
  (cumulative tick about 981 k, level 4); ten at iteration 1,550 or later. After creation each had an expected 0.14 dispatches.
- **What the two dispatches did.** Dispatch #1824 (cell 5818, at (3,907, 1,839), L 1,382) and #1980 (cell 6454, the cell that carried the 3,247 up-B in its original burst)
  each ran a 120-tick burst of 16-17 new cells, the highest at y 1,275 and 1,296. Neither repeated an up-B; together they were 240 exploration ticks.
- **The 9 dispatches from the 1,000..1,639 band** produced one burst that went high: #1618 (cell 4415, (1,623, 1,502)) reached (892, 2,658) (cell 6332 above) with the up-B.
- **By x.** None of the 14 is at x <= 1,495 (nearest: cell 7247, A1, (1,495.5, 1,643.0), L 1,503); A2/A1 cells at y >= 1,000 and x <= 600 number 6, with 2 dispatches and 1 new cell
  produced; none is at x <= -600.
- **Where the returns went instead** (all 2,175 dispatches, by the start cell's stored position):

| region (definition) | cells | eligible | dispatches |
| --- | ---: | ---: | ---: |
| below the main floor (y < -2,850) | 3,524 | 2,220 | 456 (21.0 %) |
| beside the stage (x > 3,600, above the floor) | 804 | 804 | 180 (8.3 %) |
| on-stage low (-2,850 <= y < 0) | 3,094 | 3,094 | 1,274 (58.6 %) |
| on-stage high (y >= 0) | 842 | 842 | 265 (12.2 %) |

  86.1 % of dispatches started at y < 0 (53.7 % below y -1,500); start-cell y quantiles 0/10/25/50/75/90/99/100 %: -9,575, -5,693, -2,550, -1,564, -601, 314, 1,511, 2,889.
  Only 71 dispatches (3.3 %) started at y >= 1,000, and 12 (0.55 %) from the 32 cells in contact with the raised right step (floor line 1).
  The extremes are min y -9,669 and max x 9,363, both near the blast zones (map bounds 9,600). Of the 3,524 below-floor cells 1,304 are doomed, which leaves 2,220
  eligible, 1,122 of them with the up-B available; the median dispatch from below the floor started at y -5,466.
- **New exploration was a small part of the ticks.** 237,209 of arm T's 2,435,663 ticks (9.7 %) were new; 90.3 % replayed prefixes (the results document reports the same).
  For context, the results document's arm C (not recomputed here) found 213 launch-capable cells within T against 14, because each of its ticks is new exploration.

### A4. Does anything in the code make wall-top or left-of-wall states unreachable or unselectable?

**No defect was found.** Checks, each on the preserved archive unless stated:

| possible cause | finding |
| --- | --- |
| **bug in the stored state** | 0 violations among 8,264 cells: bin equals floor(position / 300); mask popcount equals targets remaining and level; ground / air agrees with G / A; A2 only with `jumps_used` < 2 and A1 only with 2; floor only for G; every cell live |
| **cell-key collision** | 0 duplicate keys. A wall-top landing would be a grounded cell with floor 0, never equal to an airborne cell. The key merges states by design (no velocity; one representative per cell), see below |
| **bin boundary** | the ledge (y 3,000) is exactly on a bin edge (row 10), but a landing carries floor 0 and the burst scanner labels it independently of the key (`first["l0"]`). Checked by reading `rl/m8_rd_cells.py`, not in a live run |
| **fall-window effect** | all 1,304 doomed cells are at y < 0. No cell at y >= 0 is doomed, terminal, class X or beyond the L limit (3,480): 0 cells with L > 3,480 |
| **eligibility / selection** | every eligible cell has a nonzero probability (min 8.8e-6). Selection is position-blind by contract, so a cell is favoured only by level, novelty and prefix length |
| **off-stage boundary** | none in code: the key has no clipping, the horizon is 3,600 ticks, and cells exist out to y -9,669 and x 9,363. The minimum x of -1,650 is Mario's centre against the wall face at x -1,800 (collision line 13), a physical limit |
| **ledger consistency** | the rebuild reproduced all 2,175 selections and every cell byte for byte (the close audit's result, repeated) |

**Design weaknesses (not bugs), recorded and left unchanged.**

1. **Selection ignores position.** Level is targets broken, so the mass was spread over 6,960 eligible cells, 86 % of dispatches starting below y 0, while the 14 cells that could reach the wall top received 0.09 %.
2. **The 60-tick doom window leaves most of a fall eligible.** A falling Mario is flagged only in its last 60 ticks (76 % of reaches in the 480 falling bursts are within 60 ticks of the fall; median gap 35). Cells farther up the descent (the 60-tick window covers roughly the last 4,000 units of a fall at terminal speed 70) stay eligible.
3. **The key has no velocity.** 973 of 4,343 replacements (22.4 %) flipped the sign of a horizontal velocity of at least 6; among cells at y >= 1,000 there were 36 replacements and 2 flips, so this did not shape the high airborne region in rd1.
4. **Prefix replay dominated** (90.3 % of arm T's ticks), so a long run of returns buys little exploration per return.

Neither Part A nor these notes change `m8_rd_cell_v1`, `m8_rd_select_v1`, `m8_rd_explore_v1` or the doom window, and the proposal records that changing the key or explorer would be a new design,
not a continuation (proposal section 12).

## Part B. Launch conditions for M8-rd2 and the stop

Part C (one continuation session, M8-rd2) was authorised only if every condition held. **Condition 2 did not hold, so no native tick was run.**

| # | condition | result |
| ---: | --- | --- |
| 1 | Part A found no code defect (a design weakness is not a stop) | **Met** (section A4) |
| 2 | the proposal and implementation already define the continuation session, with budget, caps, rule and stop conditions | **Not met** (below) |
| 3 | the rd1 archive verifies against its pins; executable unchanged or every cell re-verified | **Met.** Executable `30a3913b...` equals the pin, as do `BattleShip.o2r` `fe2b307e...`, `f3d.o2r` `73ab91ef...`, `gamecontrollerdb.txt` `9d3c6b8d...`, the frozen `BattleShip.cfg.json` `1b29d91b...` and `imgui.ini` `0d267321...`; manifest verified on load; `python rl/m8_rd_session.py verify-run`: `ok: true`, no problems. No re-verification is needed |
| 4 | all unit tests pass and preflight refuses solely for the missing approval | **Partly met.** Unit suite 48 / 48 (157 s) and the rule self-test pass; memory is not a blocker (7,797 MB available, 18,586 MB free commit; 113 GiB free on C:, 1,590 GiB on D:); D: coverage 409,243 `runs/` files, 0 uncovered over six increments. Preflight **refuses for two reasons** (see below) |
| 5 | `git status` shows only the expected files | **Met** (clean, `HEAD` = `origin/main` = `9f2b674`) |

### B1. Condition 2: what the continuation lacks

**Unimplemented in code** (`python rl/m8_rd_session.py --help` lists status, verify-run, approval-template, run, preflight, reverify; `run` is described as the arm T against arm C session):

- `rl/m8_rd_session.py:45,51-52`: the approval path `docs/rl_m8_rd1_approval.json`, `SESSION = "rd1"` and `GATE = "m8_rd1"` are constants.
- `rl/m8_rd_session.py:350`: preflight adds `runs\m8_rd exists (never overwritten)` as a problem; `:421` `preserve_runtime` raises if the runtime directory exists; `:549` `cmd_run` creates `M8_ROOT` with `mkdir(parents=True)`.
- `rl/m8_rd_run.py:510-514`: `init_archive` always builds a new archive containing only cell 0; no code path loads the closed rd1 archive into a running session. `load_latest_verified` is used only by the report and the tests.
- `cmd_run` always runs both arms and the rd1 rule (`fin.run_all`, `m8_rd1_rule_v1`, which compares arm T with arm C). A session without a control arm has no rule.
- No S0 open for an existing archive (proposal section 8.3: manifest equal to the previous close record, previous increment PASS, identity replays before the run), no continuation of the global iteration number that keys the selection and exploration draws, and no `rd2` snapshot, approval or backup identity (`<date>_m8_rd1` style names are rd1 constants). `reverify` is for a rebuilt executable and is documented as not used by M8-rd1.

**Left open by the proposal.**

- Section 12 gives only an estimate for a continuation ("no control arm, about 50 min of exploration, cap about 8 M ticks"), and decision 12 says each continuation is authorised separately and "carries its own registered measures". There is no registered rd2 rule, outcome table, measures, tick or wall caps, replay cap, memory caps for a longer run, or INCOMPLETE conditions.
- These are design decisions, not mechanical choices. Making them in an unattended run would exceed the instruction to stop in that case.

### B2. Preflight, run with zero ticks

`python -B rl/m8_rd_session.py preflight` returned `ok: false` with exactly two problems:

1. `runs\m8_rd exists (never overwritten)`: structural, because the rd1 archive is the thing a continuation needs. It is not "the missing approval".
2. `approval record does not match the current identity: ['git_head']`: the existing record is rd1's, written at `6a30c88`; an rd2 approval would be a new record with new identities, as the authorisation said.

Everything else passed: unit suite 48 / 48, rule self-test (digest `e0bbfe21...`), executable and runtime pins, controller-rule CVars absent, status table digest, pinned P1 traces, source snapshot status, readiness, and no BattleShip process.

### B3. The proposal's stop conditions at the rd1 close (section 12)

| stop condition | state |
| --- | --- |
| M8-rd1 is NULL | not triggered; the registered outcome is PASS (on the +2 target tie-break, t 7 against 5 at the comparison point) |
| no verified over-wall lineage after three sessions | not applicable yet; one session has run and no wall-top landing, crossing or left-side entry exists in either arm |
| median L of the top level's eligible cells above about 3,000 before the left targets are reached | not triggered; the median is 1,604 (level 7), maximum 1,797 |

None is triggered, so the design is not stopped by them. Part A shows that rd1 gives no sign of wall-top progress, and that its exposure of the relevant region was small: 14 launch-capable cells, 2 dispatches, no cell
where the up-B height and the horizontal position coincide.

### B4. What would unblock an rd2 (open items, not a design)

A separately authorised implementation of a continuation session, and a registered rd2 rule with its caps and measures decided by the user. The items to decide include the budget and wall caps, the measures
and outcome table without a control arm, whether the rd1 key, selection and explorer are kept (the proposal says changing them is a new design), the identity-replay and verification budget, and how the existing rd1 approval and
snapshot conventions are renamed. Nothing here is authorised by this document.

## Appendix. Compliance of this analysis

No native RNG was inspected, logged, controlled, compared or hashed. No fixture, recording, TAS input or `.btti` file was read. Positions and masks come only from the rd1 archive's own agent-generated cells.
The analysis scripts ran from the session scratchpad outside the repository; they are not evidence files and were not preserved here. Every figure above can be rederived from `runs/m8_rd/archive/` and `runs/m8_rd/sessions/rd1/`
by replaying `events.jsonl` over `bursts.idx.jsonl` and `cells.jsonl`.
