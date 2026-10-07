# M8-sd1: a first archive-search session for SHORTER verified clears, resuming rd4's closing archive (proposal, 2026-10-07)

**Status: design only.** Nothing was run, trained, edited or committed; no native tick was consumed. This file is the only addition to the repository. The
scratch analyses behind the numbers (appendix A) read the preserved rd4 records only and imported no repository module. The design is a proposal for a
later, separately authorised preparation session (zero ticks) and, after that, one authorised native session.

**Scope label**, to be carried by every sd1 record: *first time-directed continuation of archive `m8_rd_a1` (rd1, rd2, rd3 and rd4 as closed) under
`m8_rd_select_v4` (`m8_rd_select_v3` with two registered changes: the length-factor scale and a record bound on eligibility); one session, one set of keyed
draws; no control arm; a search for trajectories, not a policy result, not a learning result, not a comparison of v4 with v3.*

## Short answer

1. **Material (section 1).** The rd4 closing archive (37,312 cells) already holds the ingredients of a shorter clear: 57 cells with nine targets broken
   (only target 1 left) at prefix lengths 1,898 to 1,960, against the record route's 2,066 for the same progress; 30 of them were never dispatched and the
   57 received 24 dispatches from a prefix at or below 1,960 (35 over their history). The record's own ending from nine targets took 249 ticks; the ten clear
   events rd4 registered all ended with a 17 to 113-tick burst from level-9 cells at 2,213 to 2,298, so the ending move itself is demonstrated. Lower levels
   hold cells up to 355 ticks ahead of the record at equal target count, but no cell among 5,107 at level 7 arrives before 1,339, the record's own
   arrival, so the right side offers nothing within one session.
2. **Selection `m8_rd_select_v4` (section 3): v3 with two generic, stage-agnostic changes.** (a) The length-factor scale falls from 900 to **120 ticks, one
   explorer burst**: a cell one burst behind the shortest arrival of its level has half the weight (under v3 it kept 88 %). (b) A **record bound** on
   eligibility: a cell whose prefix is already at least as long as the clear the session is looking for cannot produce it, so it is not dispatched
   (`L < T_rec − M`). The level draw, the cell key, the explorer, the replacement rule, the count term and the resource weight stay v3's. The reference
   `T_rec` is the archive's own best verified clear (2,315 input ticks), never the TAS, a human recording or a fixture.
3. **Resume (section 4):** the five-level protocol (rd1 → rd2 → rd3 → rd4 → sd1), rd4's closing archive as the base, the inherited record pinned at the
   open, and the 1,898 arrival (cell 30042) re-verified exactly at every open as the shortest level-9 cell of the identity sample, as it was at rd4's close.
4. **Rule `m8_sd1_rule_v1` (section 6):** PROGRESS iff a clear verified by exact fresh-process replay from tick 0 has `completion_input_tick ≤ 2,315 − M`
   with **M = 24 ticks** (about 1 %); a verified clear shorter than 2,315 but inside the margin is RECORD_BELOW_MARGIN (a new reference, not progress);
   otherwise NO_SHORTER_CLEAR; INVALID and INCOMPLETE as rd4. Both completion clocks are always reported and never collapsed. Tiers reported: 5 % (≤ 2,199),
   10 % (≤ 2,083), ≤ 2,000.
5. **Caps (section 7):** exactly rd4's: exploration 50 minutes or 6,000,000 native ticks (valid from 2,000,000), open 70,000 ticks / 4 minutes,
   verification 400,000 ticks / 6 minutes, a 60-minute hard cap, rd4's memory caps, at most 10 game processes; integrity and backups as rd4 (section 8).
6. **Metadata (section 9):** every sd1 record carries the top-level task block `{"id": "ssb64_us_mario_btt_v1", "character": "mario", "stage": "btt_mario"}`
   and `created_utc` at the source. Correction of the record: the rd4 writers do not stamp this (no rd4 record carries a task block); sd1 would be the first
   M8 session that does.
7. **Odds (section 10, subjective):** a verified clear shorter than 2,315 in one session 60 to 75 %; PROGRESS (≤ 2,291) 50 to 65 %; at least 10 % shorter
   (≤ 2,083) 30 to 45 %; ≤ 2,000 10 to 20 %; a 2× shorter clear about 0. **It finds faster routes; it is not the learning agent**, and a PROGRESS says
   nothing about a policy.

---

## 0. State and what was read

| item | value |
| --- | --- |
| checkout | `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, branch `main`, HEAD `f221a39` = `origin/main`, working tree clean, 0 ahead / 0 behind |
| remotes | `origin` = `nicolasfrechette91/BattleShip` (the user's); `upstream` = JRickey (reference only, never pushed to) |
| read | `CLAUDE.md`; the external guide `..\guide.md` (sections 2, 3, 10, 11, 12a, 13, 14); every `docs/rl_m8_rd*` document (the proposal, amendment, implementation, rd1 results and diagnosis, the continuation proposal, rd2/rd3/rd4 decisions, implementation and results, the rd3 stop review, the four approval records); `docs/rl_m9_g2_proposal_2026-10-04.md` section 10 and `docs/rl_m9_g2_stop_review_2026-10-06.md` section 5 (the speed-search passages); the rd4 code (`rl/m8_rd4_*.py`) and the frozen `rl/m8_rd_cells.py`, `rl/m8_rd_claims.py`, `rl/m8_rd_select2.py`, `rl/m7g_spatial.py` (read only) |
| archive analysed (read only) | `runs/m8_rd_rd4/archive/{cells,events}.jsonl`, `sessions/rd4/{ledger_T.json,iterations_T.jsonl,verification.json,arm_T.json,close.json,rule.json}`, `routes/T_t/{actions.jsonl,metadata.json}`, `derived/analysis_after_run.txt` |
| executable pinned by the archive | `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee` (unchanged since M7q) |

Not read, by rule: the TAS, the crossing fixtures, the human crossing recordings (`tas_input_2/`, `rl/fixtures/`, `runs/m7g/capture/`). The number 446
appears in this document only where the guide's contract is quoted; it enters no rule, bound, reference or weight below.

---

## 1. What the rd4 closing archive holds for a speed search (census, read only)

The archive keeps one trajectory per cell and replaces it only by a strictly shorter arrival ("shorter L wins", proposal section 4.3), so a cell's `L` is the
shortest known arrival at that cell. The record route is the verified clear of rd4 iteration 11286 (2,315 words, `completion_input_tick` 2,315,
`completion_time_passed` 2,314); its ten breaks fall at input ticks 43, 120, 399, 609, 880, 982, 1,339 (the moving target), 1,838 (target 6), 2,066
(target 8) and 2,315 (target 1). "Record pace" below means that route's arrival at each number of broken targets.

### 1.1 Per level

| targets broken | cells | eligible (E1–E4, X1; E5/E6 not applied) | shortest L | record pace | cells ahead of the record pace | masks |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2,767 | 2,472 | 26 | 43 | 4 | 6 |
| 2 | 3,297 | 2,965 | 91 | 120 | 12 | 8 |
| 3 | 4,591 | 3,997 | 152 | 399 | 684 | 7 |
| 4 | 5,418 | 4,335 | 254 | 609 | 622 | 7 |
| 5 | 4,845 | 4,089 | 584 | 880 | 522 | 4 |
| 6 | 4,274 | 3,415 | 931 | 982 | 22 | 2 |
| 7 | 5,107 | 4,372 | **1,339** | 1,339 | **0** | 1 |
| 8 | 2,342 | 1,688 | 1,838 | 1,838 | 0 | 3 |
| 9 | 2,901 | 2,831 | **1,898** | 2,066 | **573** (349 eligible) | 2 |
| 10 (clear, terminal) | 4 | 0 | 2,315 | 2,315 | 0 | 1 |

Readings:
- **Levels 3 to 5 are far ahead of the record at equal count** (up to 355 ticks at level 4, a different target order), yet the advantage is gone by level 7:
  every one of the 5,107 level-7 cells arrives at 1,339 or later, 35 of them by 1,400, and only one mask exists at level 7 (the seven right-side targets).
  Those fast lower-level masks were not neglected: the level-4 mask with the 254 arrival received 812 dispatches, the level-6 mask with the 931 arrival
  2,420. Whatever gates the seventh target (the moving target is broken at 1,339 in every known lineage), the archive's evidence is that three sessions
  of dispatches from faster lower-level cells did not move it. A speed gain on the right side is therefore not expected from one more session, and the
  design does not steer toward it (section 3.5).
- **Level 9 has two families.** 2,163 cells have only target 1 left (shortest 1,898) and 738 have only target 8 left (shortest 2,053; all airborne, 139
  dispatches, none grounded). The design treats them alike (generic rule); the census says only the first is ahead of the record.
- **Level 8 has two alternative orders** (target 8 first, 16 cells from 1,912; target 1 first, 52 cells from 1,967), both later than the record's 1,838 and
  almost undispatched (1 and 3). Reported, not targeted.

### 1.2 The level-9 fast tail

| reading | value |
| --- | --- |
| cells with L ≤ 1,960 / ≤ 2,000 / ≤ 2,066 (the record pace) | 57 / 187 / 580 (all 57 and 187 eligible; 351 of the 580) |
| the 57: dispatches over their history (`chosen`) / dispatches from a prefix at or below 1,960 (ledger) / never dispatched | 35 / 24 / 30 |
| the 57: resource class | 49 A1 (up-B available), 8 A0 (helpless); none grounded; none doomed or terminal |
| the 57: position at the reach | x −4,402 to −2,250; y −2,408 to +1,036; falling (v_y −44 in most) |
| the 57: created in | rd4 only (iterations 10,938 to 13,119), descendants of two level-8 cells created in rd4 (27,443 and 27,463) |
| the 24 dispatches from L ≤ 1,960 | 21 ended by burst length, 3 by a fall; new cells per return 1.5 (13, 6, 6, 6, 5, 5, 1, 1 and sixteen zeros); every one ended at nine targets |
| level-9 cells grounded on the left floor (line 3) | 5, at L 1,966 / 1,971 / 1,975 / 1,979 / 2,018 (4 dispatches) |
| level-9 eligible L quantiles (min / 10 / 25 / 50 / 75 / 90 / max) | 1,898 / 1,998 / 2,099 / 2,170 / 2,215 / 2,282 / 2,482 |
| the 1,898 cell (30042) | key (−10, 3, A1, mask 2), position (−2,813.7, 1,036.2), velocity (24.4, −44.0); **exactly replayed at rd4's close as the identity cell `top_level_9`** (verification record, 16 / 16) |

How these cells arise is visible in the record itself: target 6 is broken at tick 1,838 falling past it near y 3,280, and target 8 lies on the same fall
line about 3,200 units lower; a fall of 44 units per tick covers that in about 70 ticks, which is 1,898 to 1,913, exactly the fast tail. The record route
instead landed on the left floor at 1,966, jumped and broke target 8 at 2,066, landed again at 2,128, and left the floor at 2,189; so the fast tail is
"the record without its 230-tick target-8 detour", not a different crossing. **Nothing above is a selection input**; it is what the archive's own numbers
say, and section 3 reads none of it.

### 1.3 The ending the archive already knows

| clear event (rd4 registry, 10 of them) | completion tick | start cell L and class at dispatch | ending length |
| --- | ---: | --- | ---: |
| iteration 11286 (**verified**, the record) | 2,315 | 2,298, A1, at (−4,095, −3,648) | 17 |
| iteration 12559 (online only) | 2,324 | 2,298, A1, at (−3,626, −2,698) | 26 |
| iteration 11206 (**verified**) | 2,326 | 2,213, A2, at (−3,301, −888) | 113 |
| iteration 12823 (online only) | 2,341 | 2,282, A2, at (−4,000, −3,002) | 59 |
| iteration 12146 (online only) | 2,348 | 2,275, A2, at (−5,104, −2,642) | 73 |

Every ending is a short burst from a level-9 airborne cell left of the stage's left floor and below it, finishing with the final break at Mario positions
such as (−3,512, −3,035) and (−3,736, −2,884). The stage table (`rl/m7g_spatial.EXPECTED_LINES`, read only) places target 1 at (−3,450, −2,550) in a
pocket under the left floor (floor at y −1,950 over x −3,900 to −2,700; ceiling line 7 at y −2,250; the pocket opens to the left of x −3,900 between y
−2,250 and −3,750). So the known ending is: pass the floor's left edge, drop to the pocket's height, and strike inward. Of the 57 fast cells, 11 are already
left of x −3,900, 29 are above the floor's span (a direct fall lands on the floor and costs a detour), 17 are right of x −2,700, and 52 are still above
floor height. Again: analysis, not an input; the explorer finds or fails to find this by keyed draws.

### 1.4 What is NOT in the archive

- No level-7 arrival before 1,339 and no second crossing lineage: every over-wall cell descends from the one trunk through the wall-top landing at 1,694.
- No verified clear other than the two of rd4; the 2,324 and 2,348 endings are online claims that the rd4 plan did not replay (it stopped at the first
  verified clear, as designed).
- No cell-level history: the `parent` field of a cell names the start cell of the burst of its *current* representative, which replacements rewrite, so a
  parent chain is not a route's history. The lineage facts above come from the dispatch ledger (start cell and L at dispatch), which is historical.

### 1.5 The record route's words (for the "how much slack" question)

The 2,315-word route has 406 word changes and 22 neutral ticks (1.0 %); every inter-break segment is almost free of neutral words (0 % in eight of ten,
9 % before the first break, 7 % between targets 6 and 8). The route is not idle anywhere; what it has is a detour (the target-8 climb) and, before 1,339, a
right side no archive cell has beaten. Word-level polishing of the existing route is M11's business and is not what this session does.

---

## 2. Design principle (fixed here, before any preparation)

- **P1. One time direction, from the archive's own verified record.** Every time quantity the session reads is an archive quantity: a cell's `L`, the
  shortest `L` of its level, and the archive's best **verified** `completion_input_tick`. The TAS, the fixtures and the human recordings are read by nothing,
  used as nothing (not a target time, not a bound, not a weight, not a tie-break).
- **P2. Generic and stage-agnostic.** The rule reads prefix length, broken-target count, visit counts, resource class and the verified record's clocks. It
  reads no position, surface, target identity, distance, order or route. On another stage or character the same rule reads that stage's archive.
- **P3. The smallest change that is the time direction.** The cell key `m8_rd_cell_v1`, the explorer `m8_rd_explore_v1`, the replacement rule, the harmonic
  level draw, the count term `(1 + seen)^−½` and the resource weight stay exactly v3's. Every lineage, exactness claim, overlay and audit carries over
  without a rebuild (the rd3 stop review's P4).
- **P4. Constants fixed before the run; the analytic masses are readings.** The two constants (the length scale, the margin) are chosen on stated,
  pre-registered grounds (section 3.3, section 6.1), not by their effect on the fast tail; the masses in section 3.4 describe the choice, they do not make it.
- **P5. A claim is a clear verified by exact fresh-process replay from tick 0**, with the native action digest, every consumed tick, the break table, the
  four clear facts and both completion clocks equal to the claim. Nothing shorter than that is a result.

---

## 3. Item 1: how the archive selects and scores cells when the goal is a shorter clear (`m8_rd_select_v4`)

### 3.1 The two forms the request names, and what the archive already does

| form | where it already lives | what v4 does with it |
| --- | --- | --- |
| **prefix length at equal target mask** | the replacement rule (a strictly shorter arrival replaces the representative of the *same cell*, and a cell is one mask, one 300-unit bin, one resource class, one floor) and the length factor `900 / (900 + L − L_min(level))` | kept; the length factor's scale is the lever that was too weak (3.2) |
| **completion time as the progress level** | nowhere in selection: a clear is terminal (E2) and is never dispatched; completion time lives in the claims (`completion_time_passed`, `completion_input_tick`) | enters selection as the **record bound** (3.3b) and the rule as the registered measure (section 6); it does not become a level, because a level is a count of broken targets and a clear is the end of a trajectory |

Two variants were considered and set aside, with the reason:
- **A per-mask reference** (`L_min(mask)` instead of `L_min(level)`): it would give full weight to the slowest family of a level (at level 9 the only-target-8
  family starts at 2,053, 155 ticks behind the only-target-1 family) because it is the shortest *of its mask*. A shorter clear is about total time at equal
  progress; the level is the right denominator, and the mask stays what it is, the identity of the remaining work in the key.
- **The record's per-level pace as a weight** (`T_rec(level) − L` as a bonus): it would raise levels 3 to 5, which are 250 to 355 ticks ahead of the record
  (1.1) but have shown in 3,000+ dispatches that the advantage does not survive the seventh target. More to the point, it is a second time reference and a
  stage reading; P3 says one reference, the level's own shortest arrival. The per-level pace is **reported** (section 6.4), never weighed.

### 3.2 Why v3's length factor barely prefers the fast tail

Under v3 the factor is `900 / (900 + L − L_min(level))`: at level 9 the median eligible cell is 272 ticks behind the shortest (1.2) and keeps 77 % of the
weight; the whole fast tail (L ≤ 1,960, 62 ticks of slack at most) keeps at least 94 %. With 2,831 eligible level-9 cells and an effective number of about
2,000 under the count term, the 57 fast cells hold **0.6 %** of the archive's selection mass (18 dispatches per 3,000 returns), which is the stop review's
"v3 barely prefers them" made exact. The count term cannot fix this: it spreads mass away from visited cells, in every direction equally.

### 3.3 The rule set `m8_rd_select_v4` (every parameter fixed here)

**Eligibility.** Cell 0 is always eligible. Any other cell c is eligible iff v2's E1 to E6 with the X1 exemption hold (unchanged) **and**:
- **E7, the record bound: `L(c) + 1 ≤ T_rec − M`**, i.e. `L ≤ 2,290` with the section 6 constants. A clear's `completion_input_tick` is at least one tick after
  any cell it passes through, so a cell failing E7 cannot produce a PROGRESS clear through any descendant; it is kept for coverage and never dispatched.
  X1 does not exempt from E7 (X1 is about doom, E7 about arithmetic). `T_rec` and `M` are the registered constants of section 6, pinned at the open; E7 does
  not move during the session.

**Level.** ℓ(c) = targets broken; draw a level with weight `1 / (1 + ℓ* − ℓ)` over the levels with eligible cells, ℓ* the top such level (v2's harmonic draw,
unchanged; ℓ* = 9 at the open, since level-10 cells are terminal).

**Cell within the level.** `w(c) = (1 + seen(c))^−½ × S / (S + L(c) − L_min(ℓ)) × w_res(c)`, with **S = 120** (v3: 900), `L_min(ℓ)` the shortest `L` among
the v4-eligible cells of the level, and `w_res` = 1, 1, ½, ¼ for G, A2, A1, A0 (unchanged).

*Why S = 120.* It is the explorer's own granularity: one burst is 120 words (`m8_rd_explore_v1`), so "one burst behind the level's shortest arrival halves
the weight" is a statement in the archive's own unit, needing no stage quantity. Under S = 120 the median level-9 cell (272 behind) keeps 31 % and the fast
tail at least 66 %. S is a registered constant; sections 3.4 and 13 give the readings for 60, 100 (the stop review's sketch) and 300.

**Replacement, doom, draws, explorer.** v2's replacement rule under v2 doom (a non-doomed reach beats a doomed one, then the strictly shorter `L`, ties keep
the incumbent); the explorer `m8_rd_explore_v1` (72 Track 1 words drawn uniformly, hold lengths {1, 2, 4, 8, 16}, 120-word bursts, native `EpisodeEnded`,
a `btt_native_failure_v1` fall or the 3,600 horizon cut a burst); draws are two uniforms from sha256 of `m8_rd|m8_rd_a1_sd1|select|<iteration>` and
`m8_rd|m8_rd_a1_sd1|explore|<iteration>|<decision index>`, iterations continuing from 13,886 and never reused.

**Contract digest.** v3's description with exactly these keys replaced or added: `length_scale` 120; `eligibility` + "E7 L + 1 ≤ T_rec − M"; a
`record_reference` block (the 2,315 route's native action digest, read at preparation from rd4's `verification.json` claim `t`, cid 239, iteration 11286;
`completion_input_tick` 2,315; `completion_time_passed` 2,314; source `runs/m8_rd_rd4/sessions/rd4/verification.json`); `margin` 24; `draws` (the `_sd1`
suffix). A test builds v3's digest from the same description with these keys restored and asserts equality with the real v3 digest `fd69a033…`, so no other
key differs.

### 3.4 Analytic selection mass at the sd1 open (readings, zero ticks; `census2.py`, `census5.py`)

Computed on the 37,312 cells with E1 to E4 and X1 (E5 and E6 need the engine's burst tree and are not applied here; level 9 is exact because X1 exempts it,
and E5/E6 remove about 26 % of v1-eligible cells elsewhere, which changes the lower-level figures a little and the level-9 figures not at all).

| rule | level-9 mass on L ≤ 1,960 / ≤ 2,000 / ≤ 2,066 | expected dispatches per 3,000 returns to L ≤ 1,960 / ≤ 2,000 (no feedback) | mass within one burst of its level's shortest, all levels | mean dispatch L |
| --- | --- | --- | --- | ---: |
| v3 as it is (S 900, no E7) | 0.0061 / 0.0193 / 0.0541 | 18 / 58 | 0.075 | 1,593 |
| S 900 + E7 | 0.0068 / 0.0217 / 0.0607 | 21 / 65 | 0.079 | 1,585 |
| S 300 + E7 | 0.0091 / 0.0271 / 0.0711 | 27 / 81 | 0.098 | 1,572 |
| **S 120 + E7 (proposed)** | **0.0129 / 0.0351 / 0.0843** | **39 / 105** | **0.124** | **1,558** |
| S 100 + E7 (the stop review's sketch) | 0.0139 / 0.0371 / 0.0871 | 42 / 111 | 0.130 | 1,556 |
| S 60 + E7 | 0.0174 / 0.0430 / 0.0952 | 52 / 129 | 0.147 | 1,549 |

E7 at M = 24 removes 298 eligible cells (282 at level 9, 16 at level 8) and no cell below level 8. The level draw gives level 9 34.1 % of all dispatches
under the harmonic weights; v4 moves the within-level mass, not the level shares. The figures are first order: the first fast-tail bursts create new level-9
cells at L 1,900 to 2,050 that become start cells (rd4's feedback after the first crossing moved its left-of-wall returns from a 1.06 % analytic mass to a
40.8 % realised share).

### 3.5 Why no rule is a route hint, and why each applies unchanged to any Break the Targets stage

| element | reads | never reads | why it is not a hint |
| --- | --- | --- | --- |
| E7 record bound | the cell's `L`; the archive's best verified `completion_input_tick`; the margin | position, surfaces, targets, order | arithmetic: a prefix at least as long as the sought clear cannot shorten it; on another stage it reads that archive's record |
| S = 120 | `L`, `L_min(level)`, the burst length | anything spatial | a time preference in the archive's own unit |
| unchanged parts | counts, level counts, resource class, keyed draws | | as v2 and v3 |

Explicitly absent: any per-level pace weight, any ending, pocket, floor, edge or target-1 quantity, any reading of section 1.3, anything derived from the TAS
or the recordings. The census of section 1 is analysis for the reader; the code reads none of it.

---

## 4. Item 2: resuming rd4's closing archive (five levels)

**Base.** rd4's closing archive `runs/m8_rd_rd4/archive/` (checkpoint sequence 45; 37,312 cells, 13,886 bursts, 27,775 events; dispatch iterations 0..13,885;
session events rd2 and rd3 with v2's digest `a7d1953b…`, rd4 with v3's `fd69a033…`; its five data files' sha256 as rd4's `close.json` records them). The
frozen runtime is rd1's, read in place from `runs/m8_rd/archive/runtime/`.

**Open protocol (zero native ticks except P1 and the identity replays), rd4's R1 to R6 extended by one level:**
- **R1** immutability of all four earlier trees against their D: increments (`2026-10-02_incr_m8_rd1` 166 files, `…_rd2` 62, `…_rd3` 77,
  `2026-10-03_incr_m8_rd4` 93 files, manifest `7ff2b29d…`), each increment's record PASS, at the open and again at the close.
- **R2** rd4's closing facts: manifest verified, the counts above, exactly three session events with the digests recomputed from the current v2 and v3
  contracts (the proof that rd2–rd4 ran unchanged and that this is the same history), rd4's recorded decision (PROGRESS, m 4), and the **inherited record
  facts** that replace rd4's claim preconditions (rd4's I9 required *no* inherited milestone; sd1 inherits a clear, so it pins instead): the best verified
  clear is `completion_input_tick` 2,315 / `completion_time_passed` 2,314 (rd4 verification claim `t`, cid 239, iteration 11286; the other verified clear
  2,326 / 2,325); exactly four level-10 cells (2,315, 2,324, 2,326, 2,348); level-9 shortest `L` 1,898 (cell 30042); 57 level-9 cells at L ≤ 1,960; five
  level-9 cells grounded on floor line 3 (shortest 1,966). Any difference refuses the session.
- **R3** pins (executable, runtime files, frozen configuration, flags, the contract digests; each session's pin set compared to its own contract set, rd4's
  lesson: rd1–rd3 have 7 keys, rd4 8, sd1 9 with `m8_rd_select_v4`).
- **R4** the ledger rebuild of rd4's closing archive in four parts (rd1 under v1, rd2 and rd3 under v2, rd4 under v3; zero ticks) equal to the stored files,
  and the prefix chain rd1 → rd2 → rd3 → rd4 → sd1.
- **R5** rd4's closing overlay reproduced (37,312 cells, 30,506 v1-eligible, 5,053 descent, 3,796 bound, 8,050 union, 22,456 v2-eligible, as rd4's close
  record) **and sd1's own open overlay** (v4: E7 applied), its counts and digest recorded and pinned by the approval; eligibility changes under v4, so the
  open overlay is new and is recomputed at the close.
- **R6** materialise `runs/m8_rd_sd1/`: rd4's five closing data files and manifest copied byte for byte into `base/`, the overlays, a base record, sd1's
  `session` event `{"ev": "session", "name": "sd1", "select": "m8_rd_select_v4", "digest": <v4>, "first_iteration": 13886, "draw_suffix": "_sd1",
  "changed_from": {"select": "m8_rd_select_v3", "digest": "fd69a033…", "changes": ["length_scale 900 -> 120", "eligibility + E7 (L + 1 <= T_rec - M)"]},
  "record_reference": {…}}`, and the first sd1 checkpoint (sequence 46).

**P1 and identity.** P1 as rd4 (the tick-0 record against the archive's pin `2817d8cf…`; the two pinned Track 1 traces, 3,361 and 2,560 words, word for
word; the return self-test with a corrupted end record refused). Open identity replays K = 16 with rd4's sample design and the `sd1` keys: the shortest
cell of each of the top three levels (level 10: the 2,315 record itself, re-verified in full at every open; **level 9: cell 30042, the 1,898 arrival**; level
8: the 1,838 cell), the four highest-weight cells under v4, four keyed-random launch-capable or A2 cells, five keyed-random eligible cells. Any mismatch is
INVALID and nothing runs. The close sample is rd4's (milestone cells, the shortest of the top three levels, keyed-random), so the record and the 1,898 cell
are replayed again at the close.

**The 1,898 arrival, as flagged by the stop review.** It is not a claim and is not treated as one: it is a cell, exactly replayed (rd4 close, `top_level_9`,
16 / 16) and replayed again at sd1's open and close by the existing sample rule. It gets no hand-placed dispatch: under v4 it is the level's `L_min`, so it
carries weight 1 × `(1 + 3)^−½` × ½ (A1) before normalisation, the highest length factor of its level and nothing more.

**Writes.** sd1 writes only `runs/m8_rd_sd1/`, which must fall under D: coverage; the write guard covers all four earlier roots; the four trees are only read.

---

## 5. Claims, candidates and the verification plan (`m8_sd1_claims_v1`)

The frozen engine `m8_rd_claims` (unchanged) labels every burst and registers `t`, `l0`, `left` and `clear` candidates as before; the stored registry keeps
all of them. sd1's plan (a new file, as rd4's `m8_rd4_claims.py` was) decides only the **order and the pool**:

- **The pool that can decide the outcome:** candidates carrying a `clear` event with `first.clear < T_rec`, ordered by `first.clear` ascending (then cid).
  They are replayed three at a time, fastest first, until the fastest exact replay is found (an inexact replay is INVALID for the session, never skipped).
  Replaying fastest first means the first exact replay is the session's best verified clear; nothing slower can change the outcome, so the pool then closes.
- **The INCOMPLETE test** reads only candidates with `first.clear ≤ T_rec − M` (the ones that could be PROGRESS); a candidate inside the margin left unverified
  at the cap is reported, not INCOMPLETE.
- **Never replayed:** `left` candidates (every return from the thousands of left-of-wall cells registers one: 1,459 in rd4, 1,316 descriptive), `left_floor`
  landings, `left_break` candidates, `l0` candidates, and `t` candidates (`t` = 10 is inherited; the frozen plan's "max-t first" is dropped, since the sd1
  ledger's `t` records start empty and its first clear would be max-t whatever its length). None of them can change a speed outcome. Descriptive allowance 0
  (open question 7 offers two for information).
- **Exactness of a clear claim:** native action digest, every consumed tick, the break table, the four clear facts, and `completion_input_tick` equal to the
  claimed `first.clear`; `completion_time_passed` recorded beside it (in rd4 the two differ by exactly one on both verified routes). The rule reads the replay's
  clocks, not the claim's.
- **Hazards carried from rd3/rd4:** the wall-top label suppression (I15: wall-top cells still carry mass and a continuation from one would be a false
  INVALID under the frozen `l0` check; `suppress_wall_top_label` is applied in `commit` as before and sightings are recorded); the verification-capacity
  guard (the sd1 pool ignores the `left` flood entirely).
- **Cost:** a clear replay is about 2,300 ticks; the 16 close identity replays about 30,000 (the record's own 2,315 included). The 400,000-tick cap allows
  well over 100 clear replays; only the fastest few are needed.

---

## 6. Item 3: the registered rule `m8_sd1_rule_v1` (no control arm)

### 6.1 Constants

| constant | value | source |
| --- | ---: | --- |
| `T_rec` | **2,315** input ticks (`completion_time_passed` 2,314 reported beside it) | the archive's best verified clear (rd4 `verification.json`, claim `t`, cid 239, iteration 11286), pinned at the open; never an online claim |
| `M` (margin) | **24** ticks | about 1 % of `T_rec` rounded up to a whole tick (23.15 → 24); it exceeds the longest explorer hold (16) and the 3-tick jump buffer; the two verified routes differ by 11 ticks in their last 17 words, so a gain smaller than this is an ending re-draw, not a route gain |
| PROGRESS bar | `completion_input_tick ≤ T_rec − M = 2,291` | |
| reported tiers | ≤ 2,199 (5 %), ≤ 2,083 (10 %), ≤ 2,000 | reported only |

The clock that defines "shorter" is `completion_input_tick`, the clock the replay truth (one submitted word per consumed tick) measures; `completion_time_passed`
is reported with it and the two are never collapsed and never decremented (guide section 2). Open question 2 asks whether the user wants M = 1, 24 or 46.

### 6.2 Outcomes (evaluated in this order; disjoint and exhaustive)

| outcome | condition |
| --- | --- |
| **INVALID** | any rd4 integrity failure (tick-0, prefix, end-record or chain mismatch; consumed-tick violation; an inexact claim replay; pin drift; provenance or static-guard violation; any read of fixtures, recordings or the TAS; a change under any of the four earlier trees; a prefix-chain failure at any level; an open overlay or ledger rebuild that does not reproduce), **or** an inherited record fact that differs from the pinned one, **or** a replayed clear whose completion clocks differ from the claimed event tick |
| **INCOMPLETE** | exploration below 2,000,000 native ticks; a memory, process-count, session-cap or worker-error stop; more than 3 lifecycle failures; the open phase not completed; a candidate with `first.clear ≤ T_rec − M` left unverified at the replay cap |
| **PROGRESS** | a clear verified by exact fresh-process replay from tick 0 with `completion_input_tick ≤ T_rec − M`; the best such clear (the fastest exact replay) is the session's result and the archive's new record reference |
| **RECORD_BELOW_MARGIN** | no PROGRESS, and a verified clear with `T_rec − M < completion_input_tick < T_rec`; it becomes the new record reference for a later session, and is not progress |
| **NO_SHORTER_CLEAR** | otherwise |

### 6.3 What PROGRESS does and does not say (registered with the rule)

It says: an exactly replayable, agent-generated controller sequence clears the stage in fewer input ticks than any verified before, by at least the margin.
It does not say: anything about a policy or learning (no network, no observation, no reward is involved); that v4 caused it (one session, no control arm,
and the fast tail was the same material under any rule); that the route is robust (exact replay only; a different executable, `.o2r` or configuration needs
re-verification); that a second crossing lineage exists (every over-wall cell descends from one trunk); anything about the right side or the 446 figure.

### 6.4 Registered diagnostics (reported with every outcome; none enters the outcome)

rd4's D1–D9 and readings with rd4 as the reference column, plus: the completion-tick distribution of every clear event registered (verified or not, marked);
the best verified clear's two clocks; dispatches to level-9 cells at L ≤ 1,960 / ≤ 2,000 / ≤ 2,066 and the new cells they produced; dispatches to cells
**ahead of the record pace** per level (`L < T_rec(level)`, the record's own break ticks: a reading, never a weight); the shortest `L` of each level at the
open and the close; the shortest verified left-floor landing; the mechanism readings of rd4 (share of returns from cells seen ≥ 8, new cells per return) as
readings, not a check; the dilution verdict (reported only, rd2's thresholds); E7's count at the open and the close; the analytic v3-vs-v4 selection
probabilities on the same archive at the open (zero ticks).

### 6.5 Stops and the line

- Carried: **S5** (BOUND_VIOLATION withdraws the bound under a new contract), **S7** (INVALID or INCOMPLETE: repair and a new approval; never an extension or an
  automatic retry). S3 (horizon pressure) is reported only (the left target exists). No mechanism check and no dilution guard.
- **Line.** sd1 is one session. After PROGRESS or RECORD_BELOW_MARGIN, an sd2 under the same design with the new record reference may be proposed (its own
  authorisation); after NO_SHORTER_CLEAR, an sd2 may be proposed only with a stated reason read from the diagnostics (for example the fast tail still
  under-dispatched); no third session without a review. Whether an INCOMPLETE session counts is open question 9. The sd line is separate from the rd line
  (rd5 stays "permitted, not started" by rd4's record; running sd1 neither consumes nor grants it).

---

## 7. Item 4: caps and budget (rd4's, unchanged)

| phase | native ticks: expected (cap) | wall (session clock): expected (cap) |
| --- | ---: | ---: |
| S0 open outside the clock (R1–R6, overlays, copies, hashes, D: checks) | 0 | ≈ 6–10 min (rd4's close audit was 1.5–3 min at 35,000 cells; 37,312 now, four parts) |
| open: P1 + 16 identity replays (the 2,315 record included) | ≈ 6,200 + ≈ 30,000 (**70,000**) | ≈ 1 min (**4 min**) |
| exploration, N = 5 workers, one standby each, flags as rd1 | ≈ 5.3–5.6 M (**6,000,000**; valid from **2,000,000**) | **50 min** (expected to bind; 20 s grace, jobs in flight then aborted and not committed) |
| verification: the clear pool fastest first + 16 close identity replays, ≤ 3 threads | ≈ 35,000–60,000 (**400,000**) | ≈ 1–2 min (**6 min**) |
| **within the clock** | **≤ 6,470,000** | **hard cap 60 min from the session object** (4 + 50 + 6) |
| S2 close outside the clock (save, four-part + sd1 audit, R1 again, D: increment, verify, re-hash) | 0 | ≈ 8–12 min |

**Throughput basis** (rd4's `iterations_T.jsonl`, 3,480 jobs, all standby-promoted): per job `wall = 0.95 s + ticks / 715`, mean 1,606 ticks and 3.19 s
(0.67 s waiting, 2.36 s stepping); aggregate 1,861 ticks/s; 93.6 % of ticks were prefix replay. Under v4 the analytic mean dispatch `L` is 1,558 (v3 1,593),
so about 1,680 ticks per return and **about 3,000–3,300 returns** in 50 minutes before feedback; feedback toward level-9 cells at 1,900–2,050 lowers it toward
2,700. Validity needs 2,000,000 ticks, 667 ticks/s.

**Memory and process caps, as rd1–rd4:** main process private ≤ 3,072 MB; process tree (sampled every 5 s) private ≤ 9,216 MB and working set ≤ 4,096 MB;
system available ≥ 1,024 MB and free commit ≥ 2,048 MB; archive in memory ≤ 1,024 MB; ≤ 10 BattleShip processes (two samples above stop), none left after the
run; readiness ≥ 4,096 MB available, ≥ 10,240 MB free commit, ≥ 5 GiB free on C: and D:. rd4 peaked at 1,114 / 4,482 / 1,909 MB with 28 processes in the
tree; about 45,000 cells at the close add about 15 MB.

---

## 8. Integrity and backups (rd4's strength)

- **Source snapshot** `D:\BattleShip_source_snapshots\<date>_m8_sd1` (tool `snapshot` + `verify`, then an independent PowerShell re-hash; re-verified after
  the run). The approval names the snapshot's digest, so the snapshot comes first and the approval is written from the freshly printed template after it.
- **Approval** `docs/rl_m8_sd1_approval.json`: the rule digest; the nine contract digests (`m8_rd_cell_v1`, `m8_rd_select_v1`, `m8_rd_explore_v1`,
  `m8_rd_claims_v1`, `track1_btt_s9_b8_v1`, `btt_action_class_table_v2`, `m8_rd_select_v2`, `m8_rd_select_v3`, `m8_rd_select_v4`) and `m8_sd1_claims_v1`; the
  pins; the base (rd4's archive file hashes, close record, increment manifest, checkpoint 45, the session events); the **record reference**; the sd1 open
  overlay digest and counts; budgets, caps, key strings, code hashes, document hashes, git head, D: records. Preflight refuses for exactly one reason
  without it and passes with it; approval tests run on isolated temporary records.
- **D: coverage** 0 uncovered `runs/` files before the approval, over the base and every increment (the M9 trees of g1, g2 and g3 included, since they are
  under `runs/`); after the run, the increment `D:\BattleShip_runs_backup\<date>_incr_m8_sd1` of `runs/m8_rd_sd1/`, tool `verify`, an independent re-hash,
  combined coverage 0 uncovered, and R1 on the four earlier trees again.
- **Four-way return verification** at every return and identity replay (tick-0 record except `host_frame`; per-tick consumed tick, input tick and state
  with no end and no fall; the end record and its digest; the chain digest); any mismatch INVALID, no retry, no skip, raw replies preserved; a lifecycle
  failure is redrawn, more than 3 is INCOMPLETE.
- **Static guards**, extended to the new modules: no read of `rl/fixtures/`, `runs/m7g/capture/`, `tas_input_2/` or `.btti` files; no write path under
  `runs/m8_rd/`, `runs/m8_rd_rd2/`, `runs/m8_rd_rd3/` or `runs/m8_rd_rd4/`; the provenance guard (every lineage reaches cell 0 of `m8_rd_a1`); the
  earlier sessions' code stays byte-identical and rd4's 79-test suite must still pass.
- **No nondeterministic test** in the sd1 suite or preflight (rd4's decision 10 and its scanner); the real-process fake-game check stays the non-gating
  `integration` command. Three consecutive unit-suite passes with no change between them before the snapshot.
- **A rebuilt executable** (for example from replay-viewer work) suspends the archive's exactness claim; only the separately authorised full re-verification
  of every carried cell may run on it (proposal section 7.2), and any mismatch stops for review.

---

## 9. Item 5: artifact metadata

**Requirement.** Every sd1 record carries, at its source, the top-level task block `{"id": "ssb64_us_mario_btt_v1", "character": "mario", "stage":
"btt_mario"}` and `created_utc` (ISO 8601, seconds, `Z`; the first write; never a file time; never rewritten by a checkpoint rewrite, a copy, a backup or a
re-verification).

**Fact to record first.** The rd4 records carry neither field: `grep` over `runs/m8_rd_rd4/sessions/rd4/*.json`, `archive_meta.json` and the route metadata
finds no `task` and no `created_utc` (the snapshot tool's own record is the only `created_utc`, and it is the tool's). The g2 stop review's sentence that the
rd4 writers "refuse to write without them" describes `rl/m9_artifacts.py` (M9), not the M8 code. sd1 would be the first M8 session that stamps.

**Design.**
- **Writer.** `rl/m9_artifacts.py` already implements exactly this contract (`task_block`, `check`, `stamp`, `write_json` refusing an unstamped object, the
  task registry pinned to `rl/experiment_config.SUPPORTED_TASKS`). sd1 imports it unchanged (read only; no M9 file is edited) through a thin
  `rl/m8_sd1_artifacts.py` that stamps and writes every sd1 JSON object: `open.json`, `p1.json`, `identity_open.json`, `arm_T.json`, `verification.json`,
  `close.json`, `rule.json`, `state.json`, `memory_summary.json`, `leftover_processes.json`, each `routes/<claim>/metadata.json`, each verification trace's
  companion record, the approval, the report and the base record. A record without the stamp is refused at write time.
- **Archive data files keep their frozen row formats** (`cells.jsonl`, `bursts.bin`, `bursts.idx.jsonl`, `events.jsonl`, `manifest.sha256` are the
  `m8_rd_archive_v2` contract; changing a row would change the ledger rebuild and every carried audit). The archive is stamped once, in
  `archive_meta.json`'s top level (`meta_extra` already exists in rd4's `materialise4`), with `created_utc` fixed at sd1's first materialisation and carried
  unchanged through every checkpoint rewrite (a test asserts it).
- **JSONL session files** (`iterations_T.jsonl`, `memory_tree.jsonl`, `wall_top_sightings.jsonl`, `dispatch_rows.jsonl.gz`, `candidates_T.jsonl.gz`) open with
  one header row `{"task": …, "created_utc": …, "schema": …}` (open question 8 offers per-row stamping instead).
- **Audit.** The close audit and `verify-run` walk the whole `runs/m8_rd_sd1/` tree and refuse any JSON object, header row or `archive_meta.json` without a
  valid stamp; the D: backup copies bytes and never restamps. Existing trees (rd1–rd4, M9) are not back-filled.

---

## 10. Honest odds, and what a result would and would not mean

### 10.1 Odds (subjective; one session of about 3,000 returns)

| event | odds | grounds |
| --- | --- | --- |
| a verified clear shorter than 2,315 | **60–75 %** | the fast tail is 168 ticks ahead at level 9 and is the record without its target-8 detour (1.2); the ending move (pass the floor's left edge, drop, strike inward) was executed in ten rd4 bursts from level-9 cells (1.3); v4 sends about 39 dispatches to L ≤ 1,960 and 105 to L ≤ 2,000 before feedback (3.4), against 24 and 55 in all of rd4; feedback multiplies that as new fast cells appear |
| PROGRESS (≤ 2,291) | **50–65 %** | most of the above; the margin excludes only ending re-draws |
| at least 10 % shorter (≤ 2,083) | **30–45 %** | needs the fast tail (1,898–1,960) plus an ending of at most about 120–185 ticks; the record's ending from the floor's edge took 126 ticks (2,189 → 2,315) and the best registered burst ending was 17 ticks from the pocket's depth, so the arithmetic allows it; against it, 29 of the 57 fast cells sit above the floor's span and would land first, and the 24 fast-tail dispatches so far yielded 1.5 new cells per return and no clear |
| ≤ 2,000 | **10–20 %** | needs the direct line (11 of 57 cells are already left of x −3,900) and a near-minimal ending; little evidence either way |
| a 2× shorter clear (≤ 1,160) | **about 0** | the right side is 1,339 in every one of 5,107 level-7 cells and the fast lower-level masks were dispatched thousands of times without moving it; the crossing has one lineage; this is M11's polishing or a different right side, neither of which one archive session reaches |

The g2 stop review's figures (65–80 % and 40–55 %) are inside or next to these ranges; the differences are the 24-versus-35 dispatch correction and the
reading that half the fast tail would land on the floor first.

### 10.2 What a PROGRESS would mean for the project

- **Track 2:** a faster verified route, the archive's new record reference, and the material for an sd2 under the same rule.
- **M9 (robustification):** every start state of the backward curriculum is a replayed prefix, and staging cost grows with the prefix (`wall = 0.95 s +
  ticks / 715` per worker); a clear at 2,000 instead of 2,315 cuts about 14 % of every prefix tick and shortens the route to robustify. It also offers a
  second *ending* lineage for start states below about tick 1,840; above that the lineage is the same trunk.
- **M11:** a second complete route to polish, with the clocks it needs.

### 10.3 What it would not mean

- **Nothing about the learning agent.** No policy, observation, reward or network is involved; the finder is keyed sticky-random exploration over an
  archive. A PROGRESS neither advances nor tests M9's question (can a policy learn the clear from tick 0?).
- **Not attributable to v4.** One session, no control arm; the same cells were available to v3. Attribution would need a matched control, which this design
  does not include (the question is the route, not the rule).
- **Not robust.** Exact replay only; a different executable, `.o2r` or configuration requires re-verification of every carried cell.
- **No new crossing and no faster right side.** Every over-wall cell descends from one trunk; the right side has one lineage at 1,339.
- **Not a step toward the 7.43-second figure**, which this method cannot approach and which enters no sd1 quantity.
- **The margin is a judgment**, stated and registered; it decides the label, not the record (a verified shorter clear inside the margin is still the new
  reference).

---

## 11. Compliance

| constraint | sd1 |
| --- | --- |
| no native RNG seed inspection, logging, control, comparison or hashing | every draw is a Python-side keyed sha256 uniform (`m8_rd\|m8_rd_a1_sd1\|…`); no seed is read, set or compared |
| process restart resets the episode; no save state | one fresh (standby-promoted or cold) process per return and per replay |
| the exact submit / consume / input-tick contract | unchanged: prefix word i consumes tick i; the per-tick checks of every return |
| canonical controller words as the replay truth, no hidden actions | Track 1 words 0–71 submitted as their canonical native triples; the submitted word is the record |
| human recordings, fixtures and the TAS validation-only, never read | never read (static guard); 446 enters no bound, reference, weight or rule; the record reference is the archive's own verified clear |
| no hardcoded routes or waypoints | E7 and S are generic time quantities; cells are agent-generated; the census of section 1 is analysis the code does not read |
| non-PORT decomp and byte-matching behaviour preserved | no native, decomp or submodule change; executable `30a3913b…` with its existing read-only diagnostics |
| a rebuilt executable | suspends the archive's exactness claim until every carried cell is re-verified from tick 0 |
| no commit, push, branch or pull request; no training; no application closed | as rd4 |
| metadata | section 9 |
| decomp preservation, submodules | untouched |

---

## 12. Implementation outline (new files only; a separate, zero-tick preparation session; nothing here is authorised)

| file | contents |
| --- | --- |
| `rl/m8_sd1_select.py` | `m8_rd_select_v4`: `Archive5` over rd4's `Archive4` (draw id by iteration, v4 weights from sd1's first iteration, E7 in eligibility, the record reference), `select4_description`, the contract digest built from v3's description with only the registered keys replaced, `rebuild5` / `audit5` (five parts), `probabilities("v3" \| "v4")` for the zero-tick counterfactual reading |
| `rl/m8_sd1_resume.py` | R1–R6 at five levels, `materialise5`, `prefix_chain` for five archives, the inherited record facts and their refusal |
| `rl/m8_sd1_claims.py` | the fastest-first clear pool, the INCOMPLETE pool, no `left` / `t` / `l0` replays, the exactness check of the clocks |
| `rl/m8_sd1_rule.py` | `m8_sd1_rule_v1`: constants, outcomes, the line record, self-test |
| `rl/m8_sd1_report.py` | rd4's readings with rd4 as reference, the section 6.4 diagnostics |
| `rl/m8_sd1_run.py`, `rl/m8_sd1_session.py` | `Session5` (inherits rd4's commit path and label suppression), the open protocol, `verify_phase5`, caps, preflight / approval-template / run / verify-run / report / open-check commands, the four-root write guard |
| `rl/m8_sd1_artifacts.py`, `rl/m8_sd1_snapshot.py` | the stamping writer over `rl/m9_artifacts.py` (unchanged import); the source snapshot tool |
| `rl/m8_sd1_tests.py` | deterministic suite: v4 formula and digest (v3 restored equals the real v3 digest; 400 draws on the real rd4 archive equal an independent re-implementation; v3 and v4 differ); E7 overlay counts on the real archive; the five-level synthetic resume (two builds byte-identical); the record-fact refusal (a synthetic chain with a different best clear is refused); claims plan (fastest first; a 2,000-candidate `left` flood costs 0 replays; INCOMPLETE reads only the progress pool; a slower clear never replayed before a faster one); rule boundaries by exact integer arithmetic; stamping (an unstamped record refused; `created_utc` unchanged across checkpoint rewrites); session determinism (two runs equal); write guard over four roots; open protocol on the real trees; no nondeterminism; source guard; tracked files unchanged; plus rd1–rd4's pure tests by explicit lists |

Order of a later authorised session, as rd4's: Part A preparation (zero ticks, three consecutive suite passes, independent read-only review) → Part B launch
conditions (git state and tracked files unchanged, the four trees equal to their increments, D: coverage 0 uncovered, executable, readiness, the snapshot,
the approval, a passing full preflight) → Part C exactly one detached `run` with no retry, extension or follow-on → Part D verify-run, report, the D:
increment with an independent re-hash, and a results record `docs/rl_m8_sd1_results_<date>.md`.

---

## 13. Open questions

1. **The length scale S.** 120 (one burst, proposed), 100 (the g2 stop review's sketch), 60, or 300? Section 3.4 gives the readings; the choice is a
   registered constant and none of these is tuned to a result.
2. **The margin M.** 24 ticks (about 1 %, proposed), 1 tick (any verified shorter clear is PROGRESS), or 46 (about 2 %)? With M = 1 the outcome
   RECORD_BELOW_MARGIN disappears and E7 bounds at `L ≤ 2,313`.
3. **E7, the record bound.** Include it (two registered changes, proposed) or keep "exactly one change" and use the scale alone? E7 removes 298 cells that
   cannot produce PROGRESS; its effect on the fast-tail mass is small (3.4), its effect is mostly to stop spending returns on prefixes longer than the goal.
4. **The reference clock.** `completion_input_tick` defines "shorter" with `completion_time_passed` reported beside it (proposed), or the reverse?
5. **The record reference during the session.** Fixed at the open (proposed: 2,315) or tightened online when an unverified faster clear is registered (it
   would make selection depend on an unverified claim; the archive's cells are exact by the per-return checks, but a clear claim is verified only by the full
   replay)?
6. **The level draw.** Keep the harmonic weights (proposed; levels 0–8 keep 66 % of dispatches) or move mass toward the top level for a speed session (for
   example a steeper `1 / (1 + ℓ* − ℓ)^2`, which would be a third change)?
7. **Descriptive replays.** None (proposed), or up to two of the inherited online clears (2,324 and 2,348) for the record, at about 4,700 ticks?
8. **Metadata on JSONL files.** One stamped header row per file (proposed) or the stamp on every row?
9. **The line.** sd1 alone, with sd2 proposable after PROGRESS or RECORD_BELOW_MARGIN and, after NO_SHORTER_CLEAR, only with a stated diagnostic reason
   (proposed); does an INCOMPLETE session count toward a two-session limit, as rd4's decision 1 said for the rd line?
10. **Relation to the rd line.** Confirm that sd1 neither consumes nor grants rd5 (rd4's record leaves rd5 "permitted, not started").
11. **Order against the M9 line.** g3-s1 has run; the sd1 preparation session can be scheduled before or after any g3 continuation. Which, given that both
    use the same machine, the same executable pin and the same D: coverage check?
12. **The two level-9 families and the alternative level-8 orders.** No special treatment (proposed; the rule is generic and the census says they are behind).
    Confirm.

---

## Appendix A. Scratch analyses (read only; session scratchpad `…\scratchpad\sd1\`; not preserved)

| script | input | used in |
| --- | --- | --- |
| `census.py` | `runs/m8_rd_rd4/archive/cells.jsonl` | 1.1, 1.2 (per-level counts, masks, the fast tail, slack quantiles, the level-10 cells) |
| `census2.py` | `cells.jsonl`, `events.jsonl` | 3.2, 3.4 (analytic masses under v3 and candidate rules; rd4's dispatches by level and L) |
| `census4.py` | `sessions/rd4/ledger_T.json`, `events.jsonl`, `routes/T_t/{actions.jsonl,metadata.json}`, `iterations_T.jsonl` | 1.3 (the ten clear events and their start cells), 1.4 (the parent-chain caveat), 1.5 (word statistics), 9 (no task block) |
| `census5.py` | `cells.jsonl`, `events.jsonl`, `iterations_T.jsonl` | 3.3–3.4 (E7 counts, masses with E7), 7 (the throughput fit), 1.3 (fast-cell positions against the floor's span), 1.2 (the 24 fast-tail dispatches) |
| `census3.py` | (superseded by `census4.py` after a schema mismatch; no figure comes from it) | |

No script imported a repository module, loaded weights, read the TAS, a fixture or a recording, or launched a game process. Eligibility in the masses is
E1–E4 with X1; E5/E6 were not applied (the caveat is stated where it matters).

## Appendix B. Sources

- `docs/rl_m8_rd4_results_2026-10-03.md`, `docs/rl_m8_rd4_decisions_2026-10-03.md`, `docs/rl_m8_rd4_implementation.md`, `docs/rl_m8_rd4_approval.json`.
- `docs/rl_m8_rd3_stop_review_2026-10-03.md` (the pre-registration principle and K1), `docs/rl_m8_rd_continuation_proposal_2026-10-02.md` (v2, the
  replacement rule, the rd2 rule and caps), `docs/rl_m8_rd_proposal_2026-10-01.md` (the cell key, the explorer, exactness, persistence),
  `docs/rl_m8_rd_amendment_2026-10-02.md`, `docs/rl_m8_rd_implementation.md`, the rd1/rd2/rd3 results and decisions.
- `docs/rl_m9_g2_proposal_2026-10-04.md` section 10 and `docs/rl_m9_g2_stop_review_2026-10-06.md` section 5 (the speed-search alternative and its first
  census; corrected here on the dispatch count and extended on the lower levels and the two level-9 families).
- The external guide, sections 2 (the two clocks), 3, 10 (M8 constraints), 11 (M9), 12a (M11), 13 (artifact identity).
- A. Ecoffet et al., *First return, then explore*, Nature 590 (2021): the count-based cell weight and the "shorter trajectory replaces" rule this archive uses.
