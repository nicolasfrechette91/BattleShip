# M8 stop review after rd3: diagnosis, selection candidates, the call, and an rd4 sketch (2026-10-03)

**Status: read-only review and design.** No native process was launched and no native tick was consumed. Nothing was trained,
committed, pushed or branched, and no existing file was edited. The rd1, rd2 and rd3 trees (`runs/m8_rd/`, `runs/m8_rd_rd2/`,
`runs/m8_rd_rd3/`) were only read: the closing rd3 archive was loaded through its own verified loader (manifest checked). The figures
come from scratch scripts outside the repository (appendix A); they import the pure archive modules with bytecode writing disabled.
This document is the only file added.

**Why this review exists.** rd3 ended NO_NEW_MILESTONE under `m8_rd3_rule_v1`, and stops S2 (no verified qualified crossing after three
sessions) and S4 (DILUTION_PERSISTS) fired. The line is stopped. This review decides whether continuing is justified.

## Short answer

1. **Diagnosis: frontier starvation is real, and it is the main cause of the falling yield. It is not the only constraint on the next
   milestone.**
   - **Where the weight went.** Selection is close to uniform over a large archive: about 8,300 effective cells in rd3, against
     4,194 returns. Cells created in rd3 itself received 13.8 % of rd3's selection mass and produced **5.24 new cells per return**.
     Cells created in rd1 received 33.6 % and produced **0.36**.
   - **The seen count predicts yield; the weight ignores it.** Yield falls about 200-fold with times seen (6.11 new cells per return
     at seen ≤ 1, 0.03 at 16–31). v2's novelty weight varies only 2.6-fold over the whole archive, because its times-chosen term
     equals 1 for 64 % of eligible cells. In rd3, **43 % of the mass went to cells seen 8 or more times**.
   - **The mix explains most of the decline.** A shift-share split of the yield drop from 3.80 to 1.74 new cells per return gives
     about 71 % to where the returns went and 29 % to lower yields within each seen class. Returns to fresh cells did not lose yield
     (5.24 in rd3 against 3.78 in rd1).
   - **The other suspects** are secondary or absent:
     - the explorer: it overshoots, and 2 of 3 wall-top returns never left their starting cell;
     - burst length: not binding;
     - cell granularity: the counters do accumulate;
     - claim semantics: claims never feed selection;
     - the recovery bound: 0 violations, and it excluded only fallen states.
2. **Candidates** (Go-Explore family, position-blind, stage-agnostic). The recommendation was **fixed and hashed before any candidate
   was evaluated** (section 2):
   - **K1**, the published single-counter count score W = 1/√(1 + times seen), replacing v2's novelty term. **Recommended, by
     principle.**
   - **K2**, the three-counter score (times chosen, times seen, times chosen since new).
   - **K3**, a coarser key with 600-unit bins.
3. **Offline estimates** (first order, labelled as estimates; section 3), per dispatch at the rd4 open:

   | | v2 | K1 | K2 | K3 |
   | --- | ---: | ---: | ---: | ---: |
   | left-of-wall cells | 0.70 % | 1.06 % | 0.63 % | 1.45 % |
   | wall-top cells | 0.044 % | 0.065 % | 0.040 % | 0.19 % |
   | cells created in rd3 | 23.4 % | 27.9 % | 22.2 % | 23.3 % |
   | starts below the floor | 23.6 % | 23.5 % | 23.4 % | 28.0 % |

   - **K1 is a modest change**, about ×1.5 on the frontier labels. K3 scores higher on those labels but adds dilution and needs a
     rebuild. The labels did not and do not change the recommendation.
4. **The call: continue, narrowly, for at most two sessions; otherwise end the line.**
   - The case rests mostly on **the archive's state, not on the strength of K1**. rd3 left 47 eligible, exactly replayed states left
     of the wall: all at the top level, with only the three left targets live and 1,653–1,835 ticks of horizon remaining. Ten of
     them are airborne with up-B, directly above the left floor.
   - At the rd4 open these states carry about **29 returns per session under v2 and 44 under K1** (first order, no feedback). In rd3
     they received 1 return, because they existed only for its last ~500 dispatches.
   - **Design.** rd4 = the single change K1 (`m8_rd_select_v3`), resuming the rd3 archive with the key unchanged. A verified
     qualified crossing is required by the end of rd5, else the line ends. The line ends after rd4 already if K1's mechanism check
     fails. Rule sketch: section 4.3.
   - **If you prefer to end now:** the archive hands the PPO line exact, agent-generated starts at the wall top and beyond it
     (section 4.4).
5. **I15 changed no registered measure.** Confirmed by code reading and by the independent replay of this review (section 5).

## 0. State and what was read

| item | state |
| --- | --- |
| checkout | `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, branch `main`; `HEAD` = `origin/main` = `386c752`; working tree clean before this file |
| guide and instructions | external `..\guide.md` (revised 2026-09-22; M8 re-scoped 2026-10-02, section 10); `CLAUDE.md` |
| M8 documents read, in order | `rl_m8_rd_proposal_2026-10-01.md` (rev 2), `rl_m8_rd_amendment_2026-10-02.md`, `rl_m8_rd_implementation.md`, `rl_m8_rd1_results_2026-10-02.md`, `rl_m8_rd1_diagnosis_2026-10-02.md`, `rl_m8_rd_continuation_proposal_2026-10-02.md`, `rl_m8_rd2_decisions_2026-10-02.md`, `rl_m8_rd2_implementation.md`, `rl_m8_rd2_results_2026-10-02.md`, `rl_m8_rd3_decisions_2026-10-02.md`, `rl_m8_rd3_implementation.md`, `rl_m8_rd3_results_2026-10-02.md`; the three approval records were consulted for identities only |
| data read | `runs/m8_rd_rd3/archive/` (checkpoint 32: 26,371 cells, 10,406 bursts, 20,814 events; manifest verified on load); `runs/m8_rd_rd3/sessions/rd3/` (rule, candidates, verification, sightings); `runs/m8_rd_rd3/derived/analysis_after_run.txt` |
| code read | `rl/m8_rd_archive.py`, `m8_rd_cells.py`, `m8_rd_explore.py`, `m8_rd_select2.py`, `m8_rd3_select.py`, `m8_rd3_run.py` (I15), `m8_rd_claims.py` (registry and replay evaluation), `m7n_crossing.py` (criterion text) |
| external reference | Ecoffet et al., *First return, then explore*, Nature 590 (2021), arXiv 2004.12919, Methods and Extended Data Table 1; Ecoffet et al., *Go-Explore*, arXiv 1901.10995, appendix A.5–A.6 |
| not read or used | crossing fixtures, capture recordings, `tas_input_2/`, any `.btti` file; no RNG state anywhere |

**Replay validation.** The review's own ledger replay mirrors `rebuild3`. It re-derived all 10,406 selections and reproduced all 26,371
cells exactly. Its numpy probabilities matched `Archive2.probabilities()` to 1e-12 at every 997th dispatch. Two figures reproduce
earlier documents exactly:
- v2's analytic below-floor share over rd1's dispatches is 4.98 %, the continuation proposal's estimate;
- the wall-top probability at the rd3 open is 0.0684 %, the rd3 report's figure.

## 1. Diagnosis

### 1.1 What three sessions bought

| | rd1 (arm T) | rd2 | rd3 |
| --- | ---: | ---: | ---: |
| exploration ticks | 2,435,663 | 4,992,640 | 5,170,886 |
| returns | 2,175 | 4,037 | 4,194 |
| archive cells at close | 8,264 | 19,062 | 26,371 |
| eligible cells at the next open (v2) | 4,506 | 11,794 | 16,610 |
| returns per eligible cell (next session, ~4,000 returns) | 0.89 | 0.34 | 0.24 |
| effective number of cells selected from (1/Σp², session median) | 1,751 | 5,623 | 8,292 |
| new cells per return | 3.80 | 2.67 | 1.74 |
| bursts that created no cell | 47.9 % | 58.9 % | 72.3 % |
| milestone | none | wall-top landing | none new |
| closest approach to the ledge corner | 1,017 | 162 | 64 |
| cells left of the wall (x < −2,100) | 0 | 0 | 54 (47 eligible) |

### 1.2 How selection weight was spread

The weight is the causal analytic selection mass at every dispatch: the expected number of dispatches, as a share of the session.
**Real** is the realized dispatches. **Yield** is the new cells per return of the returns that started there. All values come from the
ledger.

**By session of creation** (whether the start cell was created in the dispatching session or earlier):

| session | created in rd1: mass / real / yield | created in rd2 | created in rd3 |
| --- | --- | --- | --- |
| rd1 | 99.8 % / 2,170 / 3.78 | — | — |
| rd2 | 52.1 % / 2,077 / 1.54 | 47.9 % / 1,960 / 3.88 | — |
| rd3 | 33.6 % / 1,361 / **0.36** | 52.6 % / 2,234 / 1.65 | **13.8 % / 599 / 5.24** |

- At the rd4 open, the mean per-cell probability of rd3-created cells is 5.28e-5. Older cells average 5.44e-5 (rd1) and 7.00e-5
  (rd2), against a uniform 6.02e-5.
- **The newest cells are selected slightly less than uniformly.** The length factor and the resource weight offset the small
  novelty bonus.

**By age at dispatch (rd3):**

| iterations since creation | 0–249 | 250–999 | 1,000–1,999 | 2,000–3,999 | ≥ 4,000 |
| --- | ---: | ---: | ---: | ---: | ---: |
| mass | 2.0 % | 5.8 % | 7.7 % | 20.9 % | **63.6 %** |
| real | 69 | 256 | 343 | 880 | 2,646 |
| yield | 6.62 | 5.59 | 4.39 | 2.53 | 0.64 |

**By times seen** (bursts that visited the cell before the dispatch):

| seen | 0–1 | 2–3 | 4–7 | 8–15 | 16–31 | 32–63 | 64+ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rd1: mass / yield | 32.6 % / 6.68 | 31.1 % / 3.77 | 23.6 % / 1.53 | 10.6 % / 0.39 | 1.9 % / 0.10 | 0.2 % / 0.00 | — |
| rd2: mass / yield | 22.4 % / 6.09 | 25.9 % / 3.30 | 24.5 % / 1.51 | 18.0 % / 0.44 | 8.0 % / 0.07 | 1.2 % / 0.00 | 0.1 % / 0.30 |
| rd3: mass / yield | 13.7 % / 6.11 | 19.5 % / 2.87 | 23.3 % / 1.02 | 22.1 % / 0.30 | 16.3 % / 0.03 | 4.5 % / 0.01 | 0.5 % / 0.00 |
| rd3: real | 600 | 821 | 971 | 936 | 667 | 177 | 22 |

**By times chosen**, and by **times chosen since the cell last led to a new cell** (csn):

| rd3 | chosen 0 | 1 | 2–3 | 4–7 | | csn 0 | 1 | 2–3 | 4+ |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| mass | 59.7 % | 25.7 % | 13.2 % | 1.4 % | | 72.3 % | 19.3 % | 7.9 % | 0.6 % |
| real | 2,513 | 1,078 | 548 | 55 | | 3,040 | 806 | 330 | 18 |
| yield | 2.49 | 0.85 | 0.23 | 0.18 | | 2.33 | 0.25 | 0.09 | 0.00 |

The same ordering holds in rd1 and rd2. rd1: chosen 0 → 4.23, chosen 1 → 2.17; csn 0 → 4.08, csn 1 → 0.81. rd2: chosen 0 → 3.30,
chosen 1 → 1.25; csn 0 → 3.08, csn 1 → 0.52.

**By level (rd3).**
- Levels 6 and 7 took 55 % of the mass and yielded 0.30 and 0.39 new cells per return. Levels 0–5 yielded 2.6–4.1.
- The top level, where the frontier is, is mostly exhausted cells. The harmonic level weight boosts all of them alike.

**Fatal returns by seen** are flat (rd3: 0.12–0.15 in every class). Times seen is not a proxy for falling.

### 1.3 Why the weight is flat

**The novelty term.** v2's cell weight multiplies w_nov = (1 + chosen)^−½ + (1 + seen)^−½ by the length factor and the resource weight.
- At the rd4 open, **times chosen is 0 for 64 % of eligible cells and at most 1 for 88 %** (0.24 returns per eligible cell per
  session). The first term is therefore close to 1 almost everywhere.
- It floors the weight: w_nov spans 0.66–1.71 between the 1 % and 99 % quantiles. A brand-new cell gets 1.71; a cell seen 23
  times and never chosen still gets 1.20.
- Over the same range, yield falls from about 6 to about 0.03.

**Times seen carries the information.**
- A burst revisits its own start cell in 85 % of returns, and seen ≥ chosen for all but 8 of 26,371 cells. Times seen therefore
  subsumes times chosen.
- Bursts visit 19.7 distinct keys on average (rd3). Among eligible cells, seen has median 5, 90th percentile 23 and maximum 146.
- The counter that discriminates is there; the weight's additive form discards most of it.

**The shift-share split (rd1 → rd3, by seen class).**
- rd3's per-class yields at rd1's dispatch mix give 3.21 new cells per return.
- The mix therefore accounts for 3.21 − 1.74 = 1.47 of the 2.06 drop (71 %). Lower yields inside each class account for 0.59 (29 %).
- By age class the mix accounts for all of it: rd3's yields at rd1's age mix give 5.97.

### 1.4 The other suspects

| suspect | evidence | verdict |
| --- | --- | --- |
| explorer (`m8_rd_explore_v1`) | yield from fresh cells did not fall (rd3-created cells 5.24 per return); but it is blind and sticky: of the 3 returns to wall-top cells, 2 never left their starting key in 120 ticks and 1 went up and right; the two flights that crossed the wall overshot, and 33 of the 47 eligible left cells lie beyond the left floor's far end (x < −3,900) | **secondary**: real inefficiency, but it is the share of returns that changed between sessions, not the explorer |
| burst length (120 ticks) | both over-wall flights were still airborne at burst end, and continuing them needs another return; the one return from a left cell (iteration 10,369) extended the flight with 27 new cells | **not binding**: the binding quantity is how rarely those cells are returned to |
| cell granularity (`m8_rd_cell_v1`) | the counters accumulate (seen median 5); but a fine key multiplies cells, so returns per cell is 0.24 and any near-uniform weight dilutes a frontier of a few dozen cells among 16,610 | **contributing** through the cell count, not because counting fails |
| claim semantics | claims never enter selection, the key or the explorer; the qualified-crossing criterion (`btt_qualified_crossing_v1`) correctly reports no crossing: no grounded tick left of the wall exists | **not a cause** (one wording note below) |
| recovery bound (E6) | 0 `BOUND_VIOLATION` in 8,231 rd2 and rd3 bursts; of the 54 left cells it excludes only the 7 at y ≈ −5,900 to −6,050 from the under-stage fall of iteration 6,474 (also descent-doomed) | **not a cause** |
| dilution (S4) | below-floor starts 21.7 % of rd3's mass; v2's exclusions remain in force; no candidate below changes this materially | **orthogonal**: it wastes about a fifth of the returns but is not what starves the frontier |

**Wording note on S2.**
- The proposal's original stop (§12, item 2) read "no verified over-wall lineage exists after three sessions". rd3 registered it as
  "no verified qualified crossing".
- rd3's candidates 24 and 26 are exact replays of over-wall entries. They took off from the wall top and crossed x = −2,100 at
  y 4,098, above the wall top. They never land.
- So a verified over-wall *lineage* exists, and a verified qualified *crossing* does not. S2 fired as registered. This review does not
  reinterpret it; the fact is relevant to the call in section 4.

### 1.5 Verdict

- **The failure is frontier starvation in the Go-Explore sense.** The selection spends its returns roughly in proportion to how
  many cells exist, not to how unexplored they are. The archive's own counts show that most returns go where nothing new is found.
- **For the specific next milestone, the binding fact is that the frontier is small.** It holds 2 wall-top cells, 62 wall-top-lineage
  cells and 47 eligible left cells among 16,610.
- **Position-blind count weights cannot single the frontier out**, because thousands of other cells are equally new. They can only
  stop wasting returns on exhausted cells.

**Frontier facts from the actual history** (diagnosis, never used to choose a candidate):
- After their creation, the wall-top cells had an expected 2.55 dispatches under v2 and received 3.
- The wall-top lineage expected 14.2 and received 11. Two of those 11 returns produced the 47 eligible over-wall cells (iterations
  9,907 and 10,369).

## 2. Candidates, and the principle the recommendation follows

The principle and the choice below were written into a scratch file and hashed **before the evaluation script existed**:
sha256 `4b346ae5c4e044f9ef44affb7855678300335e58d1b902749a205e4f9f70973b`, 2026-10-03T15:09:30Z. The file is
`preregistration.md` in this review's scratchpad, appendix A. It quotes only the diagnosis facts of section 1, which are generic.

### 2.1 Principle (fixed before evaluation)

- **P1. Go-Explore's count-based selection.** A cell's weight should fall as the archive's own evidence that the cell is exhausted grows.
- **P2. Act on the diagnosed mechanism.** v2's weight does not fall, because a near-constant counter term floors it (section 1.3).
- **P3. Exactly one change.** E1–E6, X1, the harmonic level weight, the length factor, the resource weight and the keyed draws stay
  as they are.
- **P4. Keep the cell key unless the key itself is the diagnosed cause.** Section 1.4 says it is not. Every lineage, exactness claim,
  overlay and audit then carries over without a rebuild.
- **P5. A published form, with no constant chosen by looking at results.** Position-blind; no per-stage or per-character quantity.
- **P6. The choice is fixed here.** The wall-top and left-of-wall figures are evaluation labels only.

### 2.2 The three candidates

| id | definition | published source |
| --- | --- | --- |
| **K1** | w_cnt = (1 + seen)^−½ replaces w_nov; everything else is v2 | Go-Explore 2021 (Nature), Methods and Extended Data Table 1: cell selection weight W = 1/√(C_seen + 1), with C_seen "increased by one when it is visited in the exploration step, even if the cell was visited multiple times in that step", which is exactly this archive's `seen` |
| **K2** | w_cnt = (1 + chosen)^−½ + (1 + seen)^−½ + (1 + csn)^−½ replaces w_nov (equal weights, ε₁ → 1 as in v1/v2, ε₂ = 0) | Go-Explore 2019, appendix A.5: a sum over the attributes times chosen, times chosen since new and times seen of w_a·(1/(v + ε₁))^p_a + ε₂; p_a = 0.5 was found by grid search; v1/v2's novelty term is this form with two attributes and equal weights |
| **K3** | coarser key (⌊bx/2⌋, ⌊by/2⌋, res, mask, floor), i.e. 600-unit bins: the smallest nested coarsening, each coarse bin exactly four fine bins; v2's rules unchanged on coarse cells, counts aggregated per coarse cell, representative = the shortest v2-eligible constituent | Go-Explore 2021, Methods: the downscaled representation is re-chosen dynamically against "a target number of cells T" |

**K3's rebuild, for completeness (not recommended).**
- The coarse archive is a merge of stored data with zero native ticks. Every stored reach row names its fine cell, so its coarse key
  follows from that cell's key.
- Each coarse representative is an existing exact trajectory: the shortest non-doomed constituent, with its stored end record and
  chain digest. No verified lineage is lost.
- The cost is a new cell contract, a new overlay and a rebuilt audit.

### 2.3 The choice: K1

- **K2** keeps the additive form whose near-constant terms are the diagnosed floor, so P2 fails. Its added counter is 0 or 1 for most
  cells. Its published weights were grid-searched per game; untuned equal weights are the only principled choice, and they are
  flatter still.
- **K3** changes the cell contract and needs a rebuild, while the key is not the diagnosed cause, so P4 fails. It also permanently
  merges states the explorer distinguishes.
- **K1** is the single-counter published form. It uses the counter that carries the information at this budget, changes one term and
  keeps the key.

## 3. Offline estimates (first order; every figure in this section is an estimate)

**Method.**
- The real rd1–rd3 ledger is replayed over the stored bursts.
- Immediately before each of the 10,406 dispatches, each rule's analytic selection distribution is computed over the archive as it
  stood then, using only evidence available then.
- The history is the real one, so feedback is not modelled: different selections would have produced different bursts.
- K3 is approximated. A coarse cell is eligible if any constituent is eligible, its counts aggregate the real dispatches and visits,
  and "new" means a new coarse key.
- The yield and fatal estimates weight each rule's mass by the realized per-class rates of section 1.2 (yield by seen class, fatal
  share by region), which were measured under v2.

### 3.1 During the sessions (share of each session's dispatches)

| figure | session | v2 (= actual) | K1 | K2 | K3 |
| --- | --- | ---: | ---: | ---: | ---: |
| cells created in the dispatching session | rd2 | 47.9 % | 53.0 % | 46.4 % | 48.9 %ᶜ |
| | rd3 | 13.8 % | **16.6 %** | 13.1 % | 12.6 %ᶜ |
| start cell seen ≥ 8 | rd2 | 27.3 % | 21.3 % | 29.0 % | 24.6 % |
| | rd3 | 43.4 % | **36.6 %** | 45.1 % | 39.6 % |
| new cells per return (estimate) | rd2 | 2.67 | 3.01 | 2.57 | 2.87 |
| | rd3 | 1.71 | **2.00** | 1.63 | 1.89 |
| starts below the floor | rd3 | 21.7 % | 21.6 % | 21.5 % | 26.4 % |
| fatal returns (estimate) | rd3 | 13.8 % | 13.8 % | 13.7 % | 16.2 % |
| effective cells (median) | rd3 | 8,292 | 7,390 | 8,340 | 2,726 |

ᶜ K3 counts a coarse key as new, so its "created" shares use a different definition.

Over rd1's dispatches, where the actual rule was v1, the same comparison gives below-floor shares of 21.9 % (v1), 5.0 % (v2) and 5.35 %
(K1). The v2 figure reproduces the continuation proposal.

### 3.2 Evaluation labels during the sessions

Expected dispatches from the first appearance of the label to the end of rd3; the actual count is in brackets.

| label | from iteration | v2 | K1 | K2 | K3 |
| --- | ---: | ---: | ---: | ---: | ---: |
| wall-top cells (G on floor line 0) | 5,862 | 2.55 [3] | 3.59 | 2.39 | 10.61 |
| wall-top lineage cells (representative descends from a wall-top landing) | 5,862 | 14.2 [11] | 20.3 | 13.0 | 35.4 |
| left-of-wall cells (x < −2,100) | 6,479ᵃ | 1.69 [1] | 2.56 | 1.51 | 3.64 |

ᵃ The first left cells were the 7 ineligible under-stage cells. The over-wall cells exist from iteration 9,907, about 500 dispatches
before rd3's close.

### 3.3 At the rd4 open (the closing rd3 archive, per dispatch; in brackets × 4,194 returns, no feedback)

| figure | v2 | K1 | K2 | K3 |
| --- | ---: | ---: | ---: | ---: |
| cells created in rd3 (the latest session) | 23.4 % | **27.9 %** | 22.2 % | 23.3 %ᶜ |
| wall-top cells (2) | 0.044 % [1.8] | 0.065 % [2.7] | 0.040 % [1.7] | 0.186 % [7.8] |
| wall-top lineage (62 cells) | 0.95 % [39.9] | 1.43 % [59.8] | 0.86 % [36.0] | 2.09 % [87.6] |
| left-of-wall (54 cells, 47 eligible) | 0.70 % [29.4] | **1.06 % [44.4]** | 0.63 % [26.3] | 1.45 % [60.6] |
| launch-capable cells | 9.1 % | 10.2 % | 9.0 % | 9.1 % |
| start cell seen ≥ 8 | 48.5 % | 41.5 % | 50.1 % | 43.7 % |
| starts below the floor | 23.6 % | 23.5 % | 23.4 % | 28.0 % |
| new cells per return (estimate, rd3 yields) | 1.58 | 1.88 | 1.51 | 1.85 |
| fatal returns (estimate) | 14.8 % | 14.8 % | 14.7 % | 17.1 % |
| effective cells | 9,115 | 7,886 | 9,207 | 2,904 (of 6,100 eligible coarse cells) |

### 3.4 Reading

- **K1 does what the principle says, modestly.** It moves 6–7 points of mass off cells seen 8 or more times. It raises the
  latest session's share by 2.8–5.1 points and the yield estimate by 13–19 %. The frontier labels rise by about 1.5×.
- The exponent ½ is gentle: from seen 1 to seen 23 the weight falls only 3.5-fold, while yield falls more than 20-fold. A steeper
  exponent would be a tuned constant, which P5 excludes. It is listed as an open question.
- **K3 moves the labels 2–4× but raises below-floor starts from 23.5 % to 28.0 %** and the fatal estimate from 14.8 % to 17.1 %.
  Merging 300-unit bins concentrates the sparse frontier and also the sparse falls.
- **K2 is slightly worse than v2 everywhere**, as P2 predicted.
- **None of the candidates fixes dilution.** About 23 % of starts stay below the floor under K1.
- These label figures were not available when K1 was chosen. They do not change the choice.

## 4. The honest call

### 4.1 What the evidence says for and against continuing

**For:**
- **The archive's state changed qualitatively in rd3.** It now holds 47 eligible, exactly replayed states left of the wall. All are at
  level 7 with mask 322 (only targets 1, 6 and 8 live), at L 1,765–1,947, so 1,653–1,835 ticks of horizon remain.
- Ten of them are A1 cells (up-B still available) directly above the left floor's span, at x −3,703 to −2,719 and y 1,795 to 3,335.
- The next milestone, a landing on floor line 3 at y −1,950 inside the same left visit, is the shortest step the line has faced.
- **The frontier is already selectable.** At the rd4 open these cells carry about 29 returns per session under v2 and 44 under K1.
  They received 1 return in rd3. That return produced 27 new left-of-wall cells.
- New left cells are level-7 cells seen once, so feedback (not in the estimate) pushes their share up.
- **The frontier moved monotonically.** The closest approach to the ledge corner went 1,017 → 162 → 64. The sessions produced first a
  wall-top landing (rd2) and then the first over-wall entries (rd3).
- **The cost is bounded.** A session is about 53 minutes of machine time plus preparation, and the harness ran three sessions with
  zero mismatches.

**Against:**
- **Slow progress.** 12.6 M exploration ticks bought one milestone of four.
- **Falling yield.** New cells per return fell 3.80 → 2.67 → 1.74, and 72 % of rd3's bursts created nothing.
- **The fix is modest.** The selection change is about ×1.5 on the frontier, first order.
- **The explorer overshoots.** 33 of the 47 eligible left cells lie beyond the floor's far end.
- **One return is not a rate.** The landing probability per return from a left cell cannot be estimated from the archive: there was
  1 such return, and it did not land.
- **Dilution persists.** About 23 % of starts are below the floor, and no candidate changes that.
- **A crossing would still be milestone 2 of 4.** Target 1 (under the left floor, never broken by any agent) and a clear inside the
  horizon would remain.

### 4.2 The call

**Continue, narrowly: at most two further sessions under one revised selection (K1), with a verified qualified crossing required by
the end of the second, else the line ends.**
- The justification is mainly the archive's state, not the strength of K1. K1 is the principled revision that S4 requires ("revise
  the selection under a new label"). The frontier figures attribute to it a modest gain, not a cure.
- My judgement, which is not an estimate from this analysis, is roughly even odds of a verified qualified crossing within the two
  sessions, with low confidence.
- **Ending now is also defensible** if the machine time and attention are worth more on the PPO line. Section 4.4 says what the archive
  hands over in that case.

### 4.3 If continuing: the rd4 design (a sketch; nothing is registered)

**The single change.** Selection `m8_rd_select_v3` is `m8_rd_select_v2` with the cell weight's count term replaced by (1 + seen)^−½.
Everything else is unchanged:
- eligibility E1–E6 and X1, the harmonic level weight, the length factor, the resource weight and replacement under v2 doom;
- the explorer `m8_rd_explore_v1` and its 120-tick bursts;
- the key `m8_rd_cell_v1`, the horizon of 3,600 and the Track 1 table;
- the claims engine `m8_rd_claims_v1`, with I15's suppression carried (section 5).

Because eligibility is unchanged, the open overlay is rd3's closing overlay.

**Resume** (rd3's two-level protocol extended to three levels):
- **Base.** rd3's closing archive: checkpoint 32, 26,371 cells, 10,406 bursts, 20,814 events.
- **Immutability.** `runs/m8_rd/` (166 files), `runs/m8_rd_rd2/` (62) and `runs/m8_rd_rd3/` (77) must equal their D: increments at
  the open and at the close.
- **Rebuild.** A zero-tick ledger rebuild reproduces the closing archive.
- **Prefix chain.** rd1 → rd2 → rd3 → rd4.
- **Session event.** An rd4 `session` event carrying v3's own digest, a recorded change from v2, with draw id `m8_rd_a1_rd4`.
  Iterations continue from 10,406.
- **Writes.** rd4 writes only `runs/m8_rd_rd4/`, which must fall under D: backup coverage. P1 and 16 open and 16 close identity
  replays as before.
- **New code.** New files `rl/m8_rd4_*.py` only. Earlier sessions' code stays byte-identical.

**Caps** as rd2 and rd3:
- exploration 50 min or 6,000,000 native ticks, valid from 2,000,000;
- open phase 70,000 ticks / 4 min, verification 400,000 ticks / 6 min, 60-minute hard cap;
- memory and process caps unchanged.

**Rule sketch `m8_rd4_rule_v1`** (evaluated in this order; disjoint and exhaustive):

| outcome | condition |
| --- | --- |
| INVALID | rd3's conditions, plus any change under `runs/m8_rd_rd3/` or a broken four-part prefix chain |
| INCOMPLETE | rd3's conditions (exploration below 2,000,000 ticks, a hard stop, the open phase not completed, an unverified candidate at the replay cap that could raise m) |
| PROGRESS_CLEAR / PROGRESS_LEFT_TARGET / PROGRESS_CROSSING | m = 4 / 3 / 2. m comes from exact fresh-process replays from tick 0 analysed by the unchanged `btt_qualified_crossing_v1`, the left-target and the clear predicates. The **qualifying event** (the left-side landing for a crossing, the break, the clear) must lie in a burst ingested during rd4; the entry and takeoff may lie in the prefix, since the analyser reads the whole trajectory. t ≥ 8 implies m ≥ 3, because only seven targets lie right of the wall, so it is reported, not a separate basis |
| NO_CROSSING | m < 2 |

**Mechanism verdict** (reported with every outcome; it decides only the stop path; thresholds taken from section 3.3, fixed at
registration):
- **MECHANISM_HOLDS** iff both:
  - (a) at most 45.0 % of rd4's dispatches start from cells seen ≥ 8 at dispatch, the midpoint between v2's 48.5 % and K1's 41.5 %;
  - (b) new cells per return is at least 1.74, rd3's realized value; v2's first-order projection is 1.58 and K1's is 1.88.
- **MECHANISM_FAILS** otherwise.

**Stop budget (replaces S2 and S4 for this line):**
- **B1.** PROGRESS in rd4: the budget's second session (rd5) may be proposed under the same design toward the left targets and the
  clear. Anything after rd5 needs a new review.
- **B2.** NO_CROSSING with MECHANISM_HOLDS: rd5 under the identical design, with new draws only. It is the last session.
- **B3.** NO_CROSSING with MECHANISM_FAILS: **the line ends after rd4.**
- **B4.** No verified qualified crossing in rd4 or rd5: **the line ends.**
- **B5.** INVALID: repair and a new approval. INCOMPLETE: read the caps; whether it consumes budget is open question 4.
- **Carried.** S3 (horizon pressure) and S5 (`BOUND_VIOLATION` withdraws the bound).
- **Not carried as a stop.** The dilution verdict stays reported with rd2's thresholds. It is v2's mechanism, and no candidate
  changes it.

**Registered diagnostics.** rd3's D1–D9 and new readings, plus:
- realized dispatches to wall-top cells, wall-top-lineage cells and left-of-wall cells, beside their analytic mass;
- every grounded tick on floor line 3, qualified or not;
- dispatch mass by seen class and by creation session, with v2's counterfactual on the same ledger (zero ticks);
- new cells per return.

### 4.4 If ending: what the M8 archive contributes to a combined approach with the PPO line

**Verified, agent-generated lineages from tick 0** (every one replayed exactly with all four diagnostics, traces kept):

| lineage | words | where it is kept |
| --- | ---: | --- |
| the wall-top landing (digest `9c4ad73b…`) | 1,694 | `runs/m8_rd_rd2/routes/T_L0` |
| the two over-wall flights from the wall top (rd3 candidates 24 and 26), airborne left of the wall with only the three left targets live | 1,864 and 1,948 | `runs/m8_rd_rd3/sessions/rd3/verification/T_c0024_left.json.gz`, `T_c0026_left.json.gz` |
| 7-target routes | 1,339–1,355 | `routes/T_t` of each session |
| every cell of the archive: 26,371 cells, 62 in the wall-top lineage, 54 left of the wall | — | an exact prefix, end record and chain digest each |

**Uses, not designed here.**
- **Starts.** These are the agent's own start states for frontier restarts in PPO: M7h-style, or a backward curriculum that starts
  late on the over-wall lineage and moves the start toward tick 0. Tick-0 evaluation stays authoritative.
- **Observations.** The stored raw replies let any observation contract (v1, v3, v4) be rebuilt per tick without native ticks.
- **Compliance.** They satisfy the guide's constraints: agent-generated prefixes, exact canonical words, process restart as the reset,
  no TAS or fixtures.
- **Caveat.** M7h gate 4, M7m and M7p showed that good start states alone did not consolidate into tick-0 behaviour. A combined
  approach needs its own design and gate.

## 5. Note on I15 (rd3's wall-top claim-label correction)

**Confirmed: I15 changed no registered measure.**

**What I15 does** (`rl/m8_rd3_run.py`, `suppress_wall_top_label`, applied in `Session3.commit`). It clears `labels.first.l0` in a job's
result before rd1's commit registers candidates, and records a sighting.

**Why no registered measure moved:**
- **Archive ingestion never reads `labels`.** `Archive2.ingest` reads the iteration, cell, L, representative, words, end reason,
  ticks, reaches, ground runs, resource transitions, session, worker and cumulative position. The review's own replay confirms it:
  from the ledger and the stored bursts alone it reproduces all 10,406 selections and all 26,371 cells, and the claims are not an
  input.
- **Selection, cells, dilution shares and the launch-capable rate are therefore untouched.**
- **The candidate registry changed in one way only: no `l0` candidate.**
  - rd3 registered 27 candidates (24 `t`, 3 `left`) and 0 `l0`.
  - The frozen registry keeps only the first `l0` (`self.l0_cid is None`), so without I15 exactly one would have been registered,
    from the first sighting (iteration 6,854).
  - Its replay would have been judged against the first line-0 tick of the whole trajectory (1,694, in the prefix) against the
    claimed 1,695. `evaluate_replay` checks event ticks only for `l0`, so that is the false INVALID I15 prevents.
- **The left candidates were unaffected.** None of the four sightings (iterations 6,854, 8,169, 9,892 and 10,076) is the burst of a
  left candidate (6,474, 9,907, 10,369). Their `first` records carry no `l0` either way.
- **The `t` candidates were unaffected.** None arose from a sighting burst, since those bursts started at L ≥ 1,694, longer than the
  1,339-word level-7 record.
- **m, t, the dilution verdict, the launch-capable rate and S1–S7 read nothing I15 touches.** rd3's m excludes the wall-top level by
  its registered rule (decision 4). Verification used 23,336 of its 400,000 replay ticks, so removing one candidate could not have
  changed a cap outcome.

**Two qualifications, not disputes:**
- **It is a behavioural change in the candidate registry** relative to rd2's engine, correctly recorded as such in the rd3 decisions
  (I15). Removing one candidate kind is not a "mechanical reading". It changed no measure because rd3's rule does not count that kind.
- **The prevented INVALID is inferred from the code and a test**, not observed, as rd3's results already say. One sighting (9,892, from
  cell 18,766) did not start on the wall top: its prefix contains the landing and the burst re-landed at tick 1,794. I15 handles that
  case too.
- **For rd4,** any label the frozen engine checks against a whole-trajectory first event must be suppressed the same way; today that
  is only `l0`.

## 6. Compliance of this review

| constraint | how it was kept |
| --- | --- |
| no native RNG seed inspection, logging, control, comparison or hashing | nothing touched RNG; the only sha256 draws recomputed are the archive's Python-side keyed selection uniforms, to re-derive the ledger's selections |
| prefixes agent-generated only; human crossings and TAS validation-only | no fixture, recording, `tas_input_2/` or `.btti` file was read; every state discussed is a cell of archive `m8_rd_a1`, chained to its tick-0 cell |
| no hardcoded routes or waypoints | every candidate is position-blind; positions appear only as evaluation labels, after the choice was hashed |
| no native run, training, code change, commit or edit | zero native ticks; scratch scripts outside the repository; the rd1–rd3 trees were only read; this document is the only file added |

## 7. Open questions for you

1. **Continue or end?** Section 4.2 recommends a bounded continuation (rd4, at most rd5) and says ending now is defensible. Which do
   you choose?
2. **K1 as the single change.** Do you accept the pre-registered choice? The section 3 estimates call it modest. K3 scores higher on the
   frontier labels but adds dilution and needs a rebuild; the principle excludes it, and it can only enter by your explicit override.
3. **The exponent.** K1 uses the published ½. A steeper exponent would be a tuned constant. Keep ½?
4. **Budget accounting.** Does an INCOMPLETE session consume one of the two sessions? I suggest yes once exploration has started, no if
   it stopped at the open.
5. **Mechanism thresholds.** (a) at most 45.0 % of dispatches from cells seen ≥ 8; (b) at least 1.74 new cells per return. Accept, or
   set others? Should a MECHANISM_FAILS on rd4 end the line (B3), or only bar a further revision?
6. **Dilution.** Keep reporting rd2's dilution verdict without a stop, given that no candidate addresses it, or add a guard, for example
   that below-floor starts must not exceed rd3's 22.6 % by more than a margin?
7. **The rule's progress basis.** Rely on m ≥ 2 only, since t ≥ 8 implies a left target here? And count a crossing whose entry lies in
   the prefix and whose landing lies in an rd4 burst?
8. **Sequencing.** Zero-tick preparation (new `rl/m8_rd4_*` files, tests, synthetic end-to-end, preflight, approval template) under its
   own authorisation, then rd4 under another, as for rd1–rd3?
9. **If ending:** should the handover in section 4.4 become its own proposal for the PPO line, or wait?

## Appendix A. Scratch analyses (outside the repository; not evidence)

**Location.** `%TEMP%\claude\…\scratchpad\rd4review\`. Every script ran with `python -B`. They read only `runs/m8_rd_rd3/` through
`Archive3.read_dir` (manifest verified) and imported the pure modules `m8_rd_archive`, `m8_rd_cells`, `m8_rd_select2` and
`m8_rd3_select`. No file under `runs/` or in the repository was written, and `git status` was clean before this document.

| file | what it did |
| --- | --- |
| `engine.py` | instrumented replay of the four-event ledger (mirrors `rebuild3`); asserts every selection and the final cells; numpy per-cell arrays (chosen, seen, csn, L, level, class, flags, position, creation iteration) kept in step for causal analytic distributions |
| `s1_diag.py` | section 1: mass, real dispatches and yields by creation session, age, chosen, seen, csn, level, class and region; snapshots at each open |
| `s1b_lineage.py` | wall-top lineage, the left cells' creating bursts and eligibility, burst visit counts, seen distribution, self-visit rate |
| `preregistration.md` (+ `.sha256`) | the principle, the three candidate definitions and the choice, hashed at 15:09:30Z before `s2_candidates.py` was written |
| `s2_candidates.py` | section 3: v2, K1, K2 and K3 at every dispatch and at the rd4 open; labels; the yield and fatal first-order estimates |
| `goexplore.txt`, `ge2019.txt` | text of the two Go-Explore papers (arXiv 2004.12919, 1901.10995), used for the formulas in section 2.2 |
