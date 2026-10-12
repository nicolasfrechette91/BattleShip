# M8-sd2 proposal (2026-10-12)

**Status: design only.** Nothing was run, prepared, edited or committed; no native tick was consumed. This file is the only addition to the repository
(the scratch analyses behind the numbers live under the Git-ignored `logs/m8_sd2_proposal/`, read the preserved sd1 records only and import no repository
module). The design is a proposal for a later, separately authorised preparation session (zero ticks) and, after that, one authorised native session.

**Scope label**, to be carried by every sd2 record: *second time-directed continuation of archive `m8_rd_a1` (rd1, rd2, rd3, rd4 and sd1 as closed)
under `m8_rd_select_v4` unchanged, with the record reference moved to sd1's verified clear; one session, one set of keyed draws; no control arm; a
search for trajectories, not a policy result, not a learning result, not a comparison of v4 with anything.*

## Short answer

1. **The same design (section 1).** Everything registered for sd1 carries over unchanged: `m8_rd_select_v4` (S = 120, E7), the margin M = 24, the
   harmonic level draw, the explorer, the caps (6,000,000 ticks or 50 minutes, valid from 2,000,000; open 70,000 / 4 min; verification 400,000 / 6 min;
   60-minute hard cap; the memory and process caps), N = 5, K = 16, batches of 3, the outcomes and their precedence, the stops, the stamped artifacts.
   What changes because the reference changes: T_rec = **2,086** (`completion_time_passed` 2,085; sd1 cid 901, iteration 15795, native action digest
   `a2a85903...`), the bar **2,062** (E7 at `L <= 2,061`), the tiers 1,981 and 1,877 plus a round threshold (section 1.3), the chain rd1 → rd2 → rd3
   → rd4 → sd1 → sd2 (six levels), the base = sd1's closing archive (44,007 cells, checkpoint 57), and the pinned facts of sd1's tree (section 1.4).
   v4's contract digest is parametrised by the reference, so sd2's session event carries a **new v4 digest** (v4 at 2,086) beside sd1's (v4 at 2,315):
   the same contract, a different pinned constant; the six-part ledger rebuild recomputes each.
2. **Changes beyond the reference (section 2): none recommended.** The 6,000,000-tick cap bound at 46 of 50 minutes in sd1 and would again; raising it
   is a departure worth about 8 % more returns, not recommended. One structural finding is recorded for the review after sd2, not acted on: the
   count term `(1 + seen)^-1/2` is per cell, so a cell whose representative was just shortened by 100 ticks is still "well seen", and the new
   level-7 arrival at 1,237 (102 ticks ahead of the record's right side) would receive about 2 dispatches in a whole session (section 3.4).
3. **Census (section 3).** The level-9 slack sd1 was built on is spent: the level's shortest arrival is 1,897 and the new record reaches level 9 at
   1,898. What is left: (a) the ending, 188 ticks from target 8 to target 1, 24 of which must go; (b) 18 level-8 cells at 1,776 to 1,837 (62 ticks
   ahead of the record's target-6 break), created in sd1's last 500 iterations, 17 never dispatched; (c) the level-7 lineage at 1,237, starved by
   the count term. Under the same design E7 now excludes about 4,700 cells (72 % of level 9, 56 % of level 8) and v4 sends about 970 of 3,600
   dispatches to level-9 cells at L <= 2,040 (sd1: about 290), where sd1's 261 such dispatches produced 46 new cells and no clear.
4. **Odds (section 3.6, subjective):** a verified clear shorter than 2,086 in one session 45 to 60 %; **PROGRESS (<= 2,062) 30 to 45 %**;
   RECORD_BELOW_MARGIN 15 to 20 %; NO_SHORTER_CLEAR 40 to 55 %; <= 2,000 about 10 to 15 %; <= 1,981 about 10 %; <= 1,877 about 2 %. The line is in
   diminishing returns: the right side (1,339 ticks, 64 % of the route) has one lineage the design cannot move, and the ending's floor on this trunk is
   about 1,990 to 2,010.
5. **Line (section 4):** the precedence INVALID > INCOMPLETE (NOT_STARTED before exploration, COUNTED_INCOMPLETE after) > PROGRESS >
   RECORD_BELOW_MARGIN > NO_SHORTER_CLEAR is sd1's. sd2 is the line's second session, so **every counted outcome ends in a written review before any
   sd3**; sd2 neither consumes nor grants rd5.
6. **Preparation (section 5):** new files only, `rl/m8_sd2_*.py` and `tools/m8_sd2/`, subclassing sd1's modules exactly as sd1 subclassed rd4's; about
   3,500 to 4,500 lines, one zero-tick session plus the three passes and the existing suites; three new tools close the launch-path gaps sd1's review
   found (a launch check, an evidence copier, a post-run checker). The run: about 6.06 M native ticks, a 50 to 55-minute session clock, 85 to 90
   minutes of process, 6 to 7 hours of launch day.
7. **Launch path (section 6):** Git Bash with forward slashes throughout; every launch-day output under `logs/m8_sd2_run/` (outside the snapshot set);
   the no-commit / no-edit / no-verify rule from the approval to the launch, enforced by the launcher's HEAD check; earlier increments re-hashed
   independently only; stamped JSON only into `launch/` and `derived/`; a launch check within two minutes; a waiter limit of 3.5 hours; the
   NOT_STARTED consequence written in the approval.

---

## 0. State and what was read

| item | value |
| --- | --- |
| checkout | `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, branch `main`, HEAD `6435a5d5592a36dfabe1889ff8e4b628da851ffe` = `origin/main` ("Add the results of the first speed-discovery search"); `git status --porcelain --untracked-files=all` empty at the start; nothing staged |
| committed at HEAD | `docs/rl_m8_sd1_approval.json` (blob `ec3ba49e`), `docs/rl_m8_sd1_results_2026-10-11.md` (blob `2b63b305`) |
| read | `CLAUDE.md`; `docs/rl_runbook.md` (sections 2, 3.3, 3.4, 3.5, 6; sections 1.4, P7, P9, P14 and the S3 fingerprint are superseded by `docs/rl_m9_g3_progression_fix_2026-10-08.md`, read in full); `docs/rl_m8_sd1_proposal_2026-10-07.md`, `docs/rl_m8_sd1_prep_2026-10-11.md` and `docs/rl_m8_sd1_results_2026-10-11.md` in full; `docs/rl_m8_sd1_approval.json`; all ten `rl/m8_sd1_*.py` and the five `tools/m8_sd1/*`; the rd4 modules sd1 builds on where needed (`m8_rd4_resume`, `m8_rd4_select`, `m8_rd2_session.run_config`, `m8_rd2_rule`, `m8_rd_select2`'s eligibility, `m8_rd_cells`, `m8_rd_session`, `rl/tools/runs_backup.py`) |
| sd1's closing archive (read only) | `runs/m8_rd_sd1/archive/{cells,events}.jsonl`, `archive_meta.json`, `manifest.sha256`; `sessions/sd1/{rule,close,verification,state,arm_T}.json`, `ledger_T.json`, `iterations_T.jsonl`, `verification/{T_c0901_clear,record_open}.json.gz`; `routes/T_clear_best/metadata.json`; `derived/report.json`; `launch/*`; `logs/m8_sd1_run/*`; `D:\BattleShip_runs_backup\2026-10-11_incr_m8_sd1\verification.json` (read) |
| executable pinned by the archive | `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee` (hashed by nothing here; unchanged since M7q) |

Not read, by rule: the TAS, the crossing fixtures, the human recordings. No native process was started; no test suite was run; nothing under `runs/`
or on D: changed. **sd1's independent review is not in the repository** (no document under `docs/` or `logs/` names its T1 to T6); its lessons are taken
from the user's instruction and from the amendments sd1's authorisation and results record carry (S2, S3, S4, S7, N1, N2, N4, N7), and section 5.4 gives
my own enumeration of the untested launch paths for the user to map onto T1 to T6 (open question 5).

---

## 1. "The same design": what carries over unchanged, what changes because the reference changes

### 1.1 Carried over unchanged (registered for sd1 on 2026-10-11; no value is re-derived)

| element | value | source |
| --- | --- | --- |
| selection | `m8_rd_select_v4` = v3 with the length scale **S = 120** and **E7** (`L + 1 <= T_rec - M`; X1 does not exempt; cell 0 always eligible); E1 to E6, the harmonic level draw `1 / (1 + top - level)`, the count term `(1 + seen)^-1/2`, the resource weights 1 / 1 / ½ / ¼, replacement under v2 doom, the cell key `m8_rd_cell_v1`, the explorer `m8_rd_explore_v1` (120-word bursts, holds {1, 2, 4, 8, 16}) | `rl/m8_sd1_select.py` |
| margin | **M = 24** ticks (sd1's registered constant; it is not re-derived: 1 % of 2,086 would be 21, and the margin's other grounds, the longest hold 16 and the jump buffer, stand) | `rl/m8_sd1_rule.py` |
| the reference clock | `completion_input_tick` defines "shorter"; `completion_time_passed` reported beside it, never collapsed or decremented | sd1 decision Q4 |
| the reference during the session | fixed at the open from the predecessor's verified record; never an online claim; never moved | sd1 decision Q5 |
| record bound E7 | the eligible set is recomputed with the new bound; `L_min(level)` over the v4-eligible cells | |
| claims plan | the clear pool (`first.clear < T_rec`, fastest first, batches of 3, closed at the first exact replay; an inexact replay INVALID); the INCOMPLETE test reads only candidates at or below the bar; `left`, `l0`, `t` never replayed; exactness = the engine's plus `completion_input_tick == first.clear` | `rl/m8_sd1_claims.py` |
| the inherited descriptive rule | every clear-event trajectory of the predecessor's registry that no predecessor replay verified, replayed after the pool, reported only, an inexact one flagged | amendment 1 of sd1 |
| caps | exploration 6,000,000 ticks or 50 min, valid from 2,000,000; open 70,000 ticks / 4 min; verification 400,000 / 6 min; hard cap 60 min from P1; checkpoints every 300 s; memory 3,072 / 9,216 / 4,096 / 1,024 / 2,048 MB; at most 10 game processes; 3 lifecycle failures; job timeout 900 s; grace 20 s; readiness 4,096 MB available, 10,240 MB commit, 5 GiB on C: and D: | `m8_rd2_session.run_config`, sd1's approval |
| workers, identity, threads | N = 5 (one standby each), K = 16 at the open and the close with sd1's sample design (the shortest cell of the top three levels, the four highest-weight, four keyed launch-or-A2, five keyed eligible), 3 verification threads | |
| outcomes and precedence | INVALID > INCOMPLETE > PROGRESS > RECORD_BELOW_MARGIN > NO_SHORTER_CLEAR, the same conditions (section 4) | `rl/m8_sd1_rule.py` |
| stops and flags | S5 (BOUND_VIOLATION), S7 (INVALID or INCOMPLETE: repair and a new approval, never an extension); S3 reported only; flags BOUND_VIOLATION, INHERITED_REPLAY_INEXACT; dilution reported only; no mechanism check | |
| artifacts | the task block and `created_utc` on every record, one stamped header row per JSONL file, `archive_meta.json` stamped once at the materialisation | `rl/m8_sd1_artifacts.py` |
| open protocol | R1 to R6 (one level deeper), P1 against the archive's tick-0 pin `2817d8cf...`, the record re-verified in full at the open, the identity replays; INVALID stops before any dispatch | |
| integrity | the four-way return verification, the write guard over every other `runs/` tree, the static guards, the prefix chain, the stamp audit, the D: increment with the tool's verify (new increment only) and an independent re-hash, 0 uncovered `runs/` files before the launch | |

### 1.2 What changes only because the reference changes

| element | sd1 | sd2 |
| --- | --- | --- |
| T_rec / `completion_time_passed` | 2,315 / 2,314 (rd4 cid 239, iteration 11286, kind `t`, digest `de1228be...`) | **2,086 / 2,085** (sd1 cid 901, iteration 15795, kind `clear`, 2,086 words, digest `a2a85903e704aab4819a4c6bb8e73d3b69fffdcdfce08a85f7e5d24f4a4a4e23`, source `sessions/sd1/verification/replays.jsonl`) |
| PROGRESS bar `T_rec - M` | 2,291 | **2,062** (about 34.4 s at 60 ticks per second) |
| E7 | `L <= 2,290` | **`L <= 2,061`** |
| RECORD_BELOW_MARGIN | 2,291 < c < 2,315 | 2,062 < c < 2,086 |
| tiers (reported only) | 2,199 / 2,083 / 2,000 | **1,981** = floor(0.95 × 2,086), **1,877** = floor(0.90 × 2,086), a round threshold (section 1.3) |
| the chain | rd1 → rd2 → rd3 → rd4 → sd1 (five levels) | rd1 → rd2 → rd3 → rd4 → sd1 → **sd2** (six levels); R1 over **five** earlier trees against their increments; the prefix chain of six; the ledger audit in six parts (rd1 under v1, rd2 and rd3 under v2, rd4 under v3, sd1 under v4 at 2,315, sd2 under v4 at 2,086) |
| the base | rd4's closing archive, checkpoint 45 | **sd1's closing archive**, checkpoint 57 (previous 56): 44,007 cells, 17,554 bursts, 35,118 events; copied byte for byte into `runs/m8_rd_sd2/base/`; the first sd2 checkpoint is 58 |
| first iteration, draw id | 13,886, `m8_rd_a1_sd1` | **17,557**, `m8_rd_a1_sd2` (`m8_rd\|m8_rd_a1_sd2\|select\|<iteration>`, `...\|explore\|<iteration>\|<decision index>`; identity keys `...\|identity_open\|sd2\|<cell id>`, `...\|identity_close\|sd2\|<cell id>`) |
| the session event | `{"ev": "session", "name": "sd1", "select": "m8_rd_select_v4", "digest": <v4 at 2,315> ...}` | `{"ev": "session", "name": "sd2", "select": "m8_rd_select_v4", "digest": <v4 at 2,086>, "first_iteration": 17557, "draw_suffix": "_sd2", "changed_from": {"select": "m8_rd_select_v4", "digest": <v4 at 2,315>, "changes": ["record_reference 2315/2314 (rd4 cid 239) -> 2086/2085 (sd1 cid 901)"]}, "record_reference": {...}, "margin": 24, "length_scale": 120.0}` |
| the v4 contract digest | `eb08059242eef123...` (the description's `record_reference` block names 2,315) | **a new value** computed at the preparation from the same description with the 2,086 block; the description differs from sd1's in `record_reference` only (a test asserts it); both digests are registered in the approval, sd1's under its session event and sd2's under `contracts["m8_rd_select_v4"]` |
| the archive's bound by iteration | one bound (2,290) from 13,886 on | **two bounds in one ledger**: 2,290 for iterations 13,886 to 17,556 (sd1's part rebuilds under it), 2,061 from 17,557; the eligible-levels cache is keyed on the active bound (section 5.2) |
| the record candidate at the open | rd4's `t` candidate truncated at 2,315 | sd1's `clear`-kind candidate 901 (no truncation; its words must hash to `a2a85903...`) |
| the inherited descriptive replays | three (rd4's unverified clear trajectories, 7,013 ticks) | **zero** by the same rule: sd1's registry holds one clear trajectory (iteration 15795, cids 900 `left` and 901 `clear`) and sd1 verified it; rd4's three are now sd1's exact facts (2,324 / 2,341 / 2,348) and are not replayed again |
| the identity samples | `top_level_10` = the 2,315 cell 30164; `top_level_9` = cell 30042 (1,898); `top_level_8` = cell 27398 (1,838) | `top_level_10` = **cell 41080 (2,086)**; `top_level_9` = **cell 30961 (1,897)**; `top_level_8` = **cell 43189 (1,776)**; the 2,315 route leaves the sample (same rule) |
| the record pace readings | the 2,315 route's break ticks 43, 120, 399, 609, 880, 982, 1,339, 1,838, 2,066, 2,315 | read at runtime from candidate 901's break table: **43, 120, 399, 609, 880, 982, 1,339, 1,838, 1,898, 2,086** (the same prefix through 1,838) |
| the reference column of the report | rd4 (and rd3, rd2, rd1) | **sd1** (and rd4, rd3, rd2, rd1) |
| names | `m8_sd1_rule_v1`, `m8_sd1_claims_v1`, `m8_sd1_artifacts_v1`, `runs/m8_rd_sd1`, `logs/m8_sd1_run`, `docs/rl_m8_sd1_approval.json`, `docs/rl_m8_sd1_results_<date>.md` | `m8_sd2_rule_v1`, `m8_sd2_claims_v1`, `m8_sd2_artifacts_v1`, `runs/m8_rd_sd2`, `logs/m8_sd2_run`, `docs/rl_m8_sd2_approval.json`, `docs/rl_m8_sd2_results_<date>.md` |

### 1.3 The round tier

sd1's third tier, 2,000, was a round threshold just below its 10 % tier (2,083): the stretch tier. For 2,086 the literal constant 2,000 lies above the 5 %
tier (1,981) and would be reached whenever that tier is. Three readings of "a round threshold below the reference": **1,800** (the stretch tier below the
10 % tier, sd1's role), 1,900 (between the tiers), or 2,000 kept as a literal constant. Tiers are reported only and enter no selection, claim or outcome
(the static test asserts it); the choice changes a reported line and nothing else. Open question 2; I recommend 1,800.

### 1.4 The pinned facts of sd1's tree (the sd2 counterpart of `RD4_FACTS` / `INHERITED_RECORD`; integrity facts, never selection inputs)

| fact | value (read from the tree on 2026-10-12) |
| --- | --- |
| increment | `D:\BattleShip_runs_backup\2026-10-11_incr_m8_sd1`: 130 files, 211,061,918 bytes, manifest sha256 `4a204dcb77cadcc8129ef9da9c879099dae665a77cc42e4ed9403c7719d30dbc`, `verification.json` PASS, source `runs\m8_rd_sd1` |
| archive | checkpoint 57 (previous 56); 44,007 cells, 17,554 bursts, 35,118 events; `manifest.sha256`: `archive_meta.json 4a5b76e4...`, `cells.jsonl bd0daa62...`, `bursts.bin 2e9bc8b1...`, `bursts.idx.jsonl da2ecbef...`, `events.jsonl 7f3cc951...`; `created_utc` 2026-10-12T03:38:54Z; `first_new_cell` 37312; mode 2, schema `m8_rd_archive_v2`, `archive5_contract` `m8_sd1_archive_v1` |
| dispatch iterations | 13,886 .. 17,556 contiguous (3,671 returns, all standby-promoted; 0 `fail` events); **the first sd2 iteration is 17,557** |
| session events | rd2 at 2,175 and rd3 at 6,212 (v2 `a7d1953b...`), rd4 at 10,406 (v3 `fd69a033...`), **sd1 at 13,886 (v4 `eb08059242eef123...`, record reference 2,315 / 2,314, margin 24, length scale 120)**; each recomputed from the current contracts at the open |
| sd1's records | `close.json` sha256 `2d919ed9e695ddcb740ff8b49350b2b82b4b2b8bd2e6cc0a955b41652a2a1efa`; `rule.json` `79883480...`; `verification.json` `e5c0f2ee...`; the diag2 counters (bound violations 0, doomed incumbent replacements 13,189, newly descent-doomed 27,219, revivals 15,709); state `done`; decision **PROGRESS**, line **`SD2_PROPOSABLE_NEW_REFERENCE`**, `session_counts` true, exploration 6,000,000 ticks, returns 3,671, cells created 6,695; rd5 permitted (copied through, not consumed, not granted) |
| the inherited record | best verified **2,086 / 2,085** (cid 901, iteration 15795, kind `clear`, 2,086 words, digest `a2a85903...`); verified clears: exactly one; clear-event candidates 2 (cids 900 and 901, one trajectory); clear trajectories registered 1; **unverified 0**; the three rd4 trajectories replayed exactly (2,324 / 2,341 / 2,348, flag absent) |
| the levels | cells / shortest L: 0: 1,944 / 0; 1: 3,312 / 26; 2: 3,928 / 91; 3: 5,235 / 152; 4: 5,956 / 254; 5: 5,486 / **433**; 6: 5,188 / 931; 7: 5,742 / **1,237**; 8: 3,553 / **1,776**; 9: 3,658 / **1,897**; 10: 5 / **2,086**; level-10 arrivals [2,086, 2,315, 2,324, 2,326, 2,348]; top eligible level 9, shortest 1,897 at cell 30961; left-floor landings 20 (shortest 1,850); wall-top cells [18318, 18767, 26944, 39911]; max level 10 |
| sd1's closing overlay under v4 at 2,315 (`close.json`, `overlay_close_v4`) | 44,007 cells; v1-eligible 35,895; v2-eligible 26,381; v3-eligible 27,841; **v4-eligible 27,603**; record-bound cells 317 (level 8: 106, level 9: 207, level 10: 4), 238 of them v3-eligible; v4-eligible by level 996 / 2,457 / 2,687 / 3,493 / 3,040 / 3,238 / 2,948 / 3,820 / 1,546 / 3,378 / 0; launch-capable 1,248, grounded 701, step-contact 121. Its row bytes and digest are to be computed at the preparation and pinned (sd1 stored the counts) |
| sd2's open overlay under v4 at 2,086 | to be computed at the preparation (both computations equal) and pinned. By this census the record bound would exclude about 4,697 cells (level 7: 63, level 8: 1,992, level 9: 2,637, level 10: 5); the exact figure with E5 and E6 applied is the tool's |
| pins | executable `30a3913b...`; the runtime files, frozen configuration and flags of rd1's archive; sd1's contract set has nine keys with `m8_rd_select_v4` = v4 at 2,315 |
| documents | `docs/rl_m8_sd1_proposal_2026-10-07.md` `a28658d1...`, `docs/rl_m8_sd1_prep_2026-10-11.md` `e2e0b02c...`, `docs/rl_m8_sd1_approval.json` `6aa13ccc...`, `docs/rl_m8_sd1_results_2026-10-11.md` `7b37d70b95fa67c21eb95c7bcecd7d0f8a1f32f986385e5506d19c49c3df6fc2` (all pinned by sd2's identity and snapshot) |

Every one of these is read back from sd1's tree at the open and compared (any difference refuses the session), exactly as sd1 did with rd4's.

---

## 2. Candidate changes beyond the reference (default: none; each decision is the user's)

| # | candidate | departs from "the same design"? | recommendation and why |
| ---: | --- | --- | --- |
| C1 | **The exploration tick cap.** sd1 reached 6,000,000 ticks at 2,758 s, 242 s before the 50-minute wall; with E7 at 2,061 the mean dispatch L falls (analytic 1,553 → 1,497), so the cap binds again at about 45 minutes. Options: keep 6,000,000 (the wall is slack); raise to 6,500,000 so the wall binds; wall only | yes (the caps are "exactly rd4's", registered in the approval) | **keep 6,000,000.** The gain is about 8 % more returns; the cost is a registered constant that no longer equals rd4's and sd1's, and the comparison of sd2's 3,700 returns with sd1's 3,671 would carry a footnote. Open question 3 |
| C2 | **The margin.** 24 stays; re-deriving "about 1 %" would give 21 | re-deriving would | keep 24 (the user's list) |
| C3 | **The count term on replaced representatives.** Section 3.4: the level-7 cells at 1,237 to 1,318 are old cells (seen 16 to 47) whose representatives were shortened in sd1's iteration 17,124; under v4 they hold 0.06 % of the selection mass (about 2 dispatches per session). A rule that reset `seen` on a strictly shorter replacement, or weighed a representative's age, would be a third registered change (a v5) | yes, a new selection contract | **no change for sd2.** The line rule allows sd2 "under the same design"; a v5 is its own proposal, and the review after sd2 (section 4) is where this finding belongs. Open question 10 |
| C4 | **The number of workers.** N = 5 with one standby each puts exactly 10 game processes on the machine, the cap; sd1 saw no 11th in 608 samples. N = 4 would leave headroom | yes | keep N = 5; the N2 sampler stays |
| C5 | **The dilution.** sd1's below-floor share was 42 % (reported only). E7 at 2,061 removes most of the deep level-9 cells that produced it, so sd2's figure will fall without any change | no | nothing |
| C6 | **Replaying the old record (2,315) at the open as a descriptive fact**, since it leaves the identity sample | yes (an extra replay, 2,315 ticks) | not recommended; the 2,315 route is an exact fact of rd4 and sd1 already |
| C7 | **The Part B scope.** sd1's Part B re-ran every registered suite; sd2's adds sd1's own (unit 87 / 87, e2e `4cadf507c1c4fbc9`), about 30 minutes | no (procedure) | yes, add them: they are the evidence that sd1's code is unchanged |

---

## 3. Census of sd1's closing archive against the new reference (read only; `logs/m8_sd2_proposal/census_sd2.py`, `census_tail_sd2.py`, `endings_sd2.py`)

"Record pace" below is candidate 901's own break table (43, 120, 399, 609, 880, 982, 1,339, 1,838, 1,898, 2,086); "ahead" means a cell's L below the
record's arrival at its level. Eligibility in the masses is approximate (class not X, not terminal, L <= 3,480, not doomed unless level 9 under X1, E7;
E5 and E6 not applied); the tool's figures at the preparation will differ a little below level 9. Nothing here is a selection input.

### 3.1 Per level

| level | cells (new in sd1) | shortest L (open → close) | record pace | cells ahead of the pace | of them never dispatched / created in sd1 | sd1 dispatches to them | within one burst of the shortest | E7 at 2,061 excludes |
| ---: | --- | --- | ---: | ---: | --- | ---: | ---: | ---: |
| 3 | 5,235 (644) | 152 → 152 | 399 | 762 | 447 / 13 | 52 | 139 | 0 |
| 4 | 5,956 (538) | 254 → 254 | 609 | 765 | 347 / 21 | 68 | 54 | 0 |
| 5 | 5,486 (641) | 584 → **433** | 880 | 643 | 445 / 88 | 71 | 22 | 0 |
| 6 | 5,188 (914) | 931 → 931 | 982 | 31 | 3 / 0 | 8 | 300 | 0 |
| 7 | 5,742 (635) | 1,339 → **1,237** | 1,339 | **8** | 0 / 0 (created in rd2; representatives shortened in sd1) | 1 | 12 | 63 |
| 8 | 3,553 (1,211) | 1,838 → **1,776** | 1,838 | **18** | 17 / 15 | 1 | 82 | 1,992 (56 %) |
| 9 | 3,658 (757) | 1,898 → **1,897** | 1,898 | **2** | 0 / 1 | 5 | 482 | 2,637 (72 %) |
| 10 | 5 (1) | 2,315 → **2,086** | 2,086 | 0 | | | | 5 |

Levels 0 to 2 are omitted (level 1 has 6 cells ahead, level 2 has 14, level 0 has no pace). sd1's dispatches by level: 133 / 130 / 154 / 170 / 217 / 241 / 333 / 433 / 627 / 1,233 (rd4: 996 at
level 9); its 3,671 returns produced 6,695 cells (1.82 per return), ended by length 2,450 times, by a fall 1,217 times, by a clear once.

### 3.2 Level 9: the slack is spent

| reading | value |
| --- | --- |
| L quantiles (min / 10 / 25 / 50 / 75 / 90 / max) | 1,897 / 2,003 / 2,053 / 2,139 / 2,214 / 2,261 / 2,527 (sd1's open: 1,898 / 1,998 / 2,099 / 2,170 / 2,215 / 2,282 / 2,482) |
| cells at L <= 1,877 (the 10 % tier) | **0** |
| L <= 1,981 (the 5 % tier) | 205 (70 never dispatched; 12 new in sd1; A1 125, A0 56, A2 19, G 5); sd1 dispatches 116, 99 of them from a prefix in the band |
| L <= 2,000 | 334 (136 never dispatched); sd1 dispatches 167 (141 from the band) |
| L <= 2,040 | 736 (344 never dispatched); sd1 dispatches 313 (261 from the band) |
| **L <= 2,061 (the sd2 eligible band)** | **1,021** (490 never dispatched; 52 new in sd1; A1 616, A0 310, A2 73, G 5, X 17; 326 doomed, exempt under X1); sd1 dispatches 391 (328 from the band) to 320 distinct cells |
| 2,062 <= L <= 2,290 (eligible for sd1, excluded for sd2) | 2,430 (619 new in sd1; 1,471 never dispatched); **842 sd1 dispatches** to these cells; 905 sd1 dispatches started from a prefix in this band and produced 658 new cells |
| families (mask: cells, shortest L, sd1 / rd4 dispatches) | target 1 left: 2,425, 1,897, 877 / 857; target 8 left: 1,221, 1,964, 356 / 139; target 6 left (new in sd1): 12, 2,301, 0 / 0 |
| grounded level-9 cells | 5, all at L 1,942 to 1,943 on the left floor (the record's own landing at 1,968 is on this floor), seen 13 to 50, 4 sd1 dispatches between them |

**What sd1's dispatches in the fast band yielded** (`iterations_T.jsonl`, by the start cell's L): [1,897, 1,981]: 99 dispatches, 9 new cells, 0 clears
(79 ended by length, 20 by a fall); [1,982, 2,000]: 42, 8 new; [2,001, 2,040]: 120, 29 new; [2,041, 2,061]: 67, 5 new and **the clear**; [2,062, 2,290]:
905, 658 new. The clear came from cell 30102 (level 9, A2, created in rd4 at L 2,268, its representative shortened to 2,059 by sd1's burst 15,112,
dispatched at iteration 15,795): a 27-tick burst. The fast band is the archive's least productive region per return (0.07 to 0.24 new cells by band,
0.16 over the whole band, against 0.73 for the excluded band), because its cells are airborne A1 / A0 cells falling past the floor with few live options.

### 3.3 The two endings (the agent's own traces; readings only)

Both routes share the prefix through target 6 at 1,838 (falling past it near y 3,280 at x −3,290). The new record keeps falling, breaks target 8 at
1,897 at (−2,814, 1,036), lands on the left floor at about 1,968 (x −3,152, y −1,950), stands about 16 ticks, jumps at about 1,982, arcs left and down past
the floor's edge to its deepest point (−4,074, −3,594) at 2,064, double-jumps back up and right, and breaks target 1 at 2,085 at (−3,452, −2,883). The
ending is **188 ticks from target 8**: 71 of free fall, 16 on the floor, 101 of arc. The old record landed at the same place and time (1,968), waited about
60 ticks, climbed for target 8 (2,065), landed again (2,136), waited about 55 ticks and ran the same arc from 2,189 to 2,315 (126 ticks, deepest −3,771).

For PROGRESS (<= 2,062) the ending must lose at least 24 ticks: <= 164 from target 8, or <= 94 from the floor landing (the record's 118 incl. the wait),
or a line that never lands. Two such lines are mechanically plausible on the record's own geometry: a shallower arc from the floor (the record dips
1,000 units below the target before rising to it), and a direct fall that drifts left past the floor's edge (x < −3,900) before reaching floor height
(about 1,090 units of drift in about 68 ticks of fall from target 8). Neither is a selection input; the explorer finds them or not by keyed draws from
the floor cells (grounded, weight 1.0, L 1,942 to 1,968) and the falling cells of the band.

### 3.4 The other material

- **Level 8, 1,776 to 1,837 (18 cells, 62 ticks ahead).** All from the record's trunk (parent chain 43189 ← 27331 (level 7, 1,726) ← 18767, the
  wall-top landing cell): a faster path from the wall top to target 6. 15 were created at iterations 17,083 and 17,420 (the last 500 of sd1's 3,671),
  17 were never dispatched, the one dispatch (iteration 17,420) produced 10 new cells. Classes A2 12, A1 6, none doomed. With the record's own
  continuation (+60 to target 8, +188 ending) they clear at 2,024 to 2,085: the nine at L <= 1,814 would be PROGRESS, the rest RECORD_BELOW_MARGIN.
  Under v4 at the new bound they hold 1.6 % of the selection mass (about **56 dispatches** per 3,600 returns; 82 level-8 cells lie within one burst of
  1,776, 35 never dispatched).
- **Level 7, 1,237 (8 cells, 102 ticks ahead).** Old rd2 cells (seen 16 to 47, 18 dispatches over their history) whose representatives were replaced
  in sd1's iteration 17,124 by a burst from a level-6 grounded cell at 1,198 (itself from a lower-level lineage that reached level 5 at 752 to 843 and
  level 6 at 964): the seventh, moving target was broken 39 ticks after level 6, against 357 for the record's lineage. This is the first level-7
  arrival before 1,339 in the archive's history. Its continuation is a new crossing problem (the record's crossing from level 7 took 499 ticks through
  the wall top). Under v4 the count term gives these cells 0.06 % of the mass (**about 2 dispatches** per session). The same design will not pursue
  it; section 2 C3 records the finding for the review.
- **Levels 3 to 5** stay far ahead at equal count (level 5 now 433 against 880) and, after four sessions, finally produced one level-7 arrival ahead of
  the record (above). They receive about 17 % of dispatches under the harmonic draw; no change is proposed.
- **Level-10 cells:** 5 (2,086, 2,315, 2,324, 2,326, 2,348), all terminal.

### 3.5 Analytic selection at the sd2 open (approximate eligibility; readings)

| rule | eligible cells | level-9 mass on L <= 1,981 / 2,000 / 2,040 / 2,061 | level-8 mass ahead of the pace | level-7 mass ahead of the pace | mean dispatch L | expected dispatches per 3,600 returns: level 9 at L <= 2,040 / <= 2,000; level 8 ahead; level 7 ahead |
| --- | ---: | --- | ---: | ---: | ---: | --- |
| v4 at the sd1 bound (2,290), for comparison | 37,070 | 0.029 / 0.044 / 0.080 / 0.101 | 0.008 | 0.0006 | 1,553 | 288 / 157; 29; 2.3 |
| **v4 at the sd2 bound (2,061)** | 33,372 | **0.097 / 0.147 / 0.270 / 0.341** | **0.016** | 0.0006 | 1,497 | **972 / 527; 56; 2.3** |

The level shares are the harmonic draw's and do not change (level 9 34.1 %, level 8 17.1 %, level 7 11.4 %). E7 at the new bound moves level 9's whole
share onto its 1,021 cells at or below 2,061 (sd1 realised 261 dispatches from L <= 2,040 against the analytic 288: the first-order figures were
accurate). Feedback changes the picture once the first shortened cells appear, as it did in sd1 (the clear's start cell was such a cell).

### 3.6 Odds (subjective; one session of about 3,700 returns)

| event | odds | grounds |
| --- | --- | --- |
| a verified clear shorter than 2,086 | **45 to 60 %** | the ending band [2,041, 2,061] gave one clear in 67 dispatches in sd1 and will receive about 250 (analytic); the 18 level-8 cells are a second, undispatched source; the record's own landing cells are grounded and heavily weighted |
| **PROGRESS (<= 2,062)** | **30 to 45 %** | needs 24 ticks out of a 188-tick ending whose two plausible shortcuts (3.3) are untested by the archive, or one of the nine level-8 cells at L <= 1,814 followed by the record's own continuation (about 56 expected dispatches to the 18) |
| RECORD_BELOW_MARGIN | 15 to 20 % | an ending re-draw inside 23 ticks is the most likely shorter clear; it moves the reference and is not progress |
| NO_SHORTER_CLEAR | 40 to 55 % | the fast band's yield in sd1 (0.09 to 0.24 new cells per return, no clear from L <= 2,040 in 261 dispatches); the clear-event rate under v4 is low (1 in 3,671 returns, against rd4's 10 in 3,480) |
| <= 2,000 | 10 to 15 % | the direct line or a short arc from the floor; little evidence either way |
| <= 1,981 (5 % tier) | about 10 % | the same lines at their best, or a level-8 cell at 1,776 with a 145-tick ending |
| <= 1,877 (10 % tier), <= 1,800 | about 2 %, about 1 % | needs the level-7 lineage, which the design starves, or a new crossing |
| INVALID or INCOMPLETE | about 5 % | a native inexact replay (never seen in five sessions), a memory or process-count stop |

**The case for diminishing returns.** sd1 bought 229 ticks (9.9 %) because the archive held a complete fast tail at level 9 that only needed its ending;
that tail is now the record. The remaining gains on this trunk are bounded: the right side (1,339 ticks, 64 % of the route) has one lineage that the
design cannot move except through the starved 1,237 cells; the crossing (1,339 → 1,838) is the record's in every over-wall cell; the ending's floor on
the record's geometry is about 1,990 to 2,010. At M = 24 that is one, at most two, further PROGRESS steps even if everything goes right, each needing more
dispatches per tick gained than the last. An sd2 is justified by the undispatched material (490 level-9 cells in the band, 17 level-8 cells) rather than by
sd1's rate; an sd3 under the same design would need the review of section 4 to say what is left.

---

## 4. Outcomes and line-ending conditions for sd2 (precedence order; disjoint and exhaustive)

| order | outcome | condition (sd1's, with the sd2 constants) | line status | what it implies for an sd3 | counts? |
| ---: | --- | --- | --- | --- | --- |
| 1 | **INVALID** | any integrity failure: a tick-0, prefix, end-record or chain mismatch; a consumed-tick violation; an inexact replay of a pool candidate, of the record at the open or of an identity cell; a replayed clear whose `completion_input_tick` differs from its registered clear tick; a pin drift; a provenance or static-guard violation, a write under any other `runs/` tree; any read of fixtures, recordings or the TAS; a change of any of the **five** earlier trees at the open or the close; a prefix-chain failure at any level; an overlay or ledger rebuild that does not reproduce; an inherited record fact that differs from the pinned one; an unstamped record | `REPAIR_NEEDED` | repair and a new approval; no sd3 before the repair is reviewed | the user's decision (`None`) |
| 2a | **INCOMPLETE before exploration started** (the open phase, P1, the identity replays or the record's replay not completed; a readiness or cap stop before the first dispatch) | | **`NOT_STARTED`** | does not count; sd2 may be repaired and run again **as sd2** with a new approval, a new snapshot and the procedure of 6.5 | no |
| 2b | **INCOMPLETE after exploration started** (exploration below 2,000,000 ticks; a memory, process-count, session-cap or worker-error stop; more than 3 lifecycle failures; a pool candidate at or below 2,062 left unverified at a cap before any exact clear replay; the close identity replays not completed) | | `COUNTED_INCOMPLETE` | counts as sd2: the line has had its two sessions; an sd3 only after a review that states the cause; a verified clear found before the stop is reported, and the review decides whether it becomes the reference | yes |
| 3 | **PROGRESS** | an exact replay with `completion_input_tick <= 2,062`; the fastest is the result and the archive's new record reference | `SD3_AFTER_REVIEW_NEW_REFERENCE` | the new reference stands; an sd3 under the same design may be proposed **only after a written review** (the line rule: no third session without a review) | yes |
| 4 | **RECORD_BELOW_MARGIN** | no PROGRESS, and an exact replay with `2,062 < completion_input_tick < 2,086` | `SD3_AFTER_REVIEW_NEW_REFERENCE` (not progress) | as PROGRESS: the new reference, the review first | yes |
| 5 | **NO_SHORTER_CLEAR** | otherwise | `SD3_AFTER_REVIEW_WITH_REASON` | the reference stays 2,086; an sd3 only after a review and with a stated reason read from the diagnostics | yes |

Both completion clocks are always reported and never collapsed. **rd5:** sd2 neither consumes nor grants it; rd4's recorded status (`rd5_permitted`
true, "permitted, not started") is copied through unchanged as `rd5_permitted_before_sd2` / `after_sd2`, `consumed_by_sd2` false, `granted_by_sd2`
false. **The review** is a written document (the model is `docs/rl_m8_rd3_stop_review_2026-10-03.md`): it reads sd2's diagnostics, the C3 finding of
section 2 and the remaining material, and decides whether the line continues under the same design, changes (a v5 with its own proposal), or ends.
The approval's `line_consequence` lists all six rows above, **`NOT_STARTED` as its own key**, and the rd line.

---

## 5. Preparation plan (a separate, zero-tick session; nothing here is authorised)

### 5.1 Strategy: new files only, subclassing sd1 as sd1 subclassed rd4

The M8 pattern (rd1 → rd2 → rd3 → rd4 → sd1) keeps every earlier session's code byte-identical and its suite passing, and pins the new session's code by
its own fingerprint. sd2 follows it: `rl/m8_sd2_*.py` and `tools/m8_sd2/*`, with sd1's modules imported unchanged. The alternative, generalising sd1's
modules to `--session sdK` as the g3 line did, edits tracked sd1 files (their hashes are in sd1's approval and snapshot) and is not recommended; a
generic "sdK" set written now is more work than sd2 needs. Open question 4.

### 5.2 Reused unchanged, and the sd2 counterparts

| sd1 module | reused unchanged by sd2 | sd2 counterpart (new file) and what it adds |
| --- | --- | --- |
| `m8_sd1_select` | `Archive5`, `select4_description` / `select4_contract_digest` (already parametrised by the reference and the margin), `v4_weights`, `overlay_rows5` / `overlay_counts5`, `record_reference_block`, `validate_record_reference`, `record_bound_max_L`, `restore_v3` | `m8_sd2_select.py`: `Archive6(Archive5)` with `begin_sd2` (requires rd2, rd3, rd4 and sd1's events; v4 recomputed with **sd1's event's reference** must equal sd1's digest; sd2's event as in 1.2), `draw_for` (`_sd2` from 17,557), **`bound_for(iteration)`** (2,290 for sd1's iterations, 2,061 for sd2's) with the eligible-levels cache keyed on the active bound, `session_of_iteration` over six, `rebuild6` / `audit6` (six parts), `probabilities("v4")` at the sd2 bound, `draws_description` with the sd2 keys; `Archive6.adopt` accepts sd1 archives (four events) and sd2 archives (five); **`Archive5.adopt` refuses an sd2 archive** (its names check), which a test asserts so that sd1's tools can never misread sd2's tree |
| `m8_sd1_claims` | `pool5`, `progress_pool5`, `plan_replays5`, `exactness5`, `verified_clear_record`, `registry_words` / `rd4_replays` / `clear_trajectories` / `inherited_unverified_clears` / `record_candidate` (all take a tree and a session name; sd1's JSONL registry files open with a stamped header row, which these readers skip: a test asserts it on the real sd1 tree) | `m8_sd2_claims.py`: the contract `m8_sd2_claims_v1` (the same plan, the inherited rule now read from sd1's registry: zero candidates on the real tree, asserted; the rd4 three are not re-replayed), the record candidate from sd1's `clear`-kind candidate 901 |
| `m8_sd1_rule` | `outcome_of`, `tiers_for`, `tier_report`, `best_of` (parametrised by `t_rec`) | `m8_sd2_rule.py`: `m8_sd2_rule_v1` with T_REC 2,086 / 2,085, M 24, bar 2,062, the tiers (1,981, 1,877, the round tier of 1.3), `LINE` and `line_status` for the second session (the five statuses of section 4, the review requirement, `NOT_STARTED`), `apply` with `sd1_line` copied through, the self-test |
| `m8_sd1_artifacts` | `stamp`, `check`, `write_json5`, `write_json_gz5`, `jsonl_header`, `append_jsonl5`, `write_jsonl_gz5`, `read_jsonl5`, `rows_of` | `m8_sd2_artifacts.py`: `m8_sd2_artifacts_v1` = the same writer with the exemption list naming `derived/sd1_closing_overlay.jsonl` and `derived/open_overlay.jsonl`; `audit_tree6` |
| `m8_sd1_resume` | `rd4_archive_facts` (for the rd4 level), `record_fact_problems`, `rd4_line_status`, `verified_clears_of` / `record_reference_from` / `inherited_record_facts` (take a tree and a session name) | `m8_sd2_resume.py`: `SD1_FACTS` and `INHERITED_RECORD` (section 1.4), `SD1_INCREMENT_NAME` / manifest, `sd1_archive_facts` (R2 / R4: checkpoint 57 / 56, counts, the four session events recomputed including v4 at sd1's reference, iterations contiguous, diag2, decision and line, the base copy equal to rd4's closing files, the prefix chain of five, the inherited record), `build_overlay6` / `closing_overlay6` (sd1's closing overlay under v4 at 2,315 reproduced and sd2's open overlay under v4 at 2,086, each twice), `materialise6` (base = sd1's five files and manifest; `derived/sd1_closing_overlay.jsonl`, `open_overlay.jsonl`, their stamped companion, `base.json`; sd2's session event; checkpoint 58 with `created_utc` fixed), `prefix_chain` of six, `prior_milestones6`, `sd1_line_status` |
| `m8_sd1_run` | `identity_sample_open` / `close` (parametrised by the archive; the key tags become `sd2`), `save_route5`, `verify_phase5` (via the subclass), `close_checks5`, `decide5` | `m8_sd2_run.py`: `Session6(Session5)` with `SESSION_ID` "sd2", the schemas `m8_sd2_*_v1`, the five earlier roots, the record candidate 901, `inherited = []`, close checks over five trees and the prefix chain of six, `decide6` under `m8_sd2_rule_v1`, `run_all6` |
| `m8_sd1_report` | `record_pace`, `pace_readings`, `shortest_by_level`, `left_floor_landings`, `clear_event_distribution`, `analytic_masses`, the D1 to D9 readers | `m8_sd2_report.py`: `full_report6` with **sd1 as the reference column** (then rd4, rd3, rd2, rd1), E7's counts at both bounds, the readings of section 6.4 of the sd1 proposal at the new pace; `verify_run6` (six-part audit, prefix chain of six, both overlay digests, the base record, the stamp audit, the rule recomputed) |
| `m8_sd1_session` | `source_fingerprint` (pattern), `run_config` / `caps` (exactly sd1's values), `contract_digests5` (eight + v4 at the given reference), `open_protocol5` (the rd4 level), `build_real_env5`, `results_record_problems` (pattern), the CLI | `m8_sd2_session.py`: the roots (`SD1_ROOT`, `SD2_ROOT`, the five increments including `2026-10-11_incr_m8_sd1`), `APPROVAL` = `docs/rl_m8_sd2_approval.json`, `identity()` with the nine contract names (`m8_rd_select_v4` = v4 at 2,086) **and sd1's session digest (v4 at 2,315) recomputed under `base.sd1_session_event`**, `open_protocol6` (R1 over five trees; each session's pins against its own contract set: rd1 six keys, rd2 and rd3 seven, rd4 eight, sd1 nine with v4 at its own reference; R5 both overlays; the record candidate; zero inherited), `preflight` (refuses if `runs/m8_rd_sd2` exists; runs the sd2 unit suite and the six rule self-tests), `protected_runs_roots` (every tree but sd2's own), `earlier_trees_immutability` over five, the results-record rule with prefix `rl_m8_sd2_results` and title `# M8-sd2 results ({date})`, the fingerprint over `rl/m8_sd2_*.py` and `tools/m8_sd2/*` |
| `m8_sd1_snapshot` | the helpers | `m8_sd2_snapshot.py`: the file set = sd1's + the sd2 modules, `tools/m8_sd2/`, `logs/m8_sd2_prep/`, `docs/rl_m8_sd1_results_2026-10-11.md`, this proposal, `docs/rl_m8_sd2_prep_*.md`; **never `logs/m8_sd2_run/`** |
| `m8_sd1_tests` | `host_masked_sha256` (the host-frame fix), `build_chain5`, `copy_chain5`, `run5_small`, the pure tests of rd1 to rd4 and sd1 by explicit lists | `m8_sd2_tests.py` (section 5.3) |
| `tools/m8_sd1/*` | `independent_increment_check.ps1` (byte copy) | `tools/m8_sd2/launch_detached.ps1` (`-Session sd2`; refuses an existing session log under `logs/m8_sd2_run`, an existing `runs/m8_rd_sd2`, a missing `docs/rl_m8_sd2_approval.json`, a missing `runs/m8_rd_sd1/sessions/sd1/rule.json`, **and a HEAD that differs from the approval's `git_head`** (the S2 rule enforced); a refusal leaves nothing behind), `wait_session.py` (`--session sd2`, **default `--hours 3.5`**; the limit ends the waiter only), `write_approval.py` (sd2; prints the S2 rule on success; the `line_consequence` with `NOT_STARTED`), `three_passes.py` (sd2; `NEVER_WRITTEN_AGAIN` adds `logs/m8_sd1_prep`, `logs/m8_sd2_prep`, `tools/m8_sd1`, `tools/m8_sd2`; the git-gate name `tracked_files_unchanged6`), and three **new** tools: `check_launch.py --session sd2` (the S7 check as code: the pid of `launch_record.txt` alive, `session_stdout.txt` and `session_stderr.txt` free of "refused" and "Traceback", written to `logs/m8_sd2_run/s7_check.txt`, non-zero exit otherwise), `copy_launch_evidence.py --session sd2` (N4 as code: `verify_run.json` and `report.json` into `derived/`; every other file of `logs/m8_sd2_run/` into `launch/`, any JSON-like file without a valid stamp renamed `.txt`, then `verify-run` again; prints what it did), `post_run_checks.py --session sd2` (S3 as code: the independent PowerShell re-hash of **every** registered increment including sd1's 130 files, R1 through the session code, the combined coverage; it refuses to invoke `runs_backup.py verify` on anything but `--source runs/m8_rd_sd2`). Optional: `machine_sampler.py` (sd1's hand script as a tracked tool) and `run_part_b.py` (the Part B sequence with its timeline into `logs/m8_sd2_run/partB/`). Open question 6 |

### 5.3 Tests to add (`rl/m8_sd2_tests.py`; every one deterministic; no real process)

sd2's own, about 35: `sd2_contract` (names, the `_sd2` suffix, S and M and every cap equal sd1's, the reference 2,086 / 2,085 pinned, the tiers'
derivation including the round tier, the nine contract names with v4 at 2,086 distinct from v4 at 2,315, the tools exist, the fingerprint equals the
tool's); `select_v4_reference_parametrisation` (the two descriptions differ in `record_reference` only; both restore to the real v3 digest);
`record_bound_by_session` (2,061 eligible and 2,062 not for an sd2 iteration; 2,290 / 2,291 for an sd1 iteration of the same archive; the cache keyed on
the bound; 300 sd2 draws never select a bound cell); `archive6_draw_and_mode_switch` (six draw ids; sd2's draws against an independent re-implementation
and distinct from sd1's); `begin_sd2_and_persistence` (every refusal; the event; reload knows both bounds; `Archive5.adopt` refuses an sd2 archive);
`ledger_rebuild6` (six parts, sd1's under 2,290 and sd2's under 2,061; tampering detected); `resume_five_level_synthetic` (R1 over five trees blaming
the right one; R2 refusing wrong sd1 facts; R3 with sd1's pins at v4 at 2,315; R5 both overlays twice; R6 twice byte-identical, checkpoint 58);
`inherited_record_facts_refusal`; `open_protocol_real_trees6` (gate: 166 / 62 / 77 / 93 / **130** files with the pinned manifests, sd1's audit of 44,007
cells, the four session digests recomputed, the pin key counts 6 / 7 / 7 / 8 / 9, both overlay digests, the record candidate's 2,086 words hashing to
`a2a85903...`, zero inherited); `write_guard_all_runs_roots` (sd1's tree protected); `claims6_pool_and_plan` (header rows tolerated in sd1's registry
files; the pool at 2,086; zero inherited on the real tree; the rd4 three not re-replayed); `clear_exactness6`; `rule6_module` (boundaries at 2,062 and
2,086 by integer arithmetic; the tiers; the five line statuses; rd5 copied; `outcome_of` reads no tier); `decide6_outcomes_and_stops`;
`session6_small_run`; `session6_determinism` (host frame masked); `session6_record_replay_at_open` (the 2,086 record); `budget_projection6` (the open
with the new identity lengths inside 70,000); `approval_isolated6` (`NOT_STARTED` present; the S2 rule text); `results_record_rule6` (the eleven bad
names, drafts, partial contents, CRLF and BOM); `artifacts6_stamping`; `task_block_pinned`; `source_guard6` (sd1's forbidden list plus the census
tokens of this proposal: 1897, 1776, 1237, 1942, 1968, 2040, 2059 and the stage coordinates of 3.3; the registered constants 2086, 2085, 2062, 2061, 24,
120, 1981, 1877 and the round tier allowed); `no_nondeterminism_in_sd2`; `tracked_files_unchanged6`; `snapshot_tool6` (the run log directory never in
the set); `import_isolation6`; `tools6_parsers` (every tool's parser, a forward-slash `--repo`, the waiter's default limit). Plus the pure tests of rd1,
rd2, rd3, rd4 and sd1 by explicit lists (about 95 tests in all; about 15 minutes).

**The e2e:** `build_chain6` = `build_chain5` plus a synthetic sd1 run (sd1's own engine on the chain through the lock-step pool) that verifies a clear in
the stub world (sd1's e2e verified one at 460 / 459 against a synthetic record of 878; the small-run budget that does so is found by experiment and fixed
in the suite, as sd1's `CHAIN_RD4` was); then the sd2 session at the registered counts on it: the six-level resume, both overlays, the selection under
sd2's draws and both bounds, the open, the fastest-first pool, zero inherited, the close audit of the six parts, the prefix chain, the stamp audit,
`verify-run`, with rd4's claim cases (a) and (b) as the first dispatches; the last line prints `{"e2e": "PASS", "digest": ...}` with the host frame masked.
Three consecutive passes with the fingerprint unchanged pin the digest.

### 5.4 The untested launch paths (my enumeration; the review's T1 to T6 are not in the repository: open question 5)

| # | path sd1's run never exercised | how sd2's preparation closes it (zero native ticks) |
| --- | --- | --- |
| U1 | `launch_detached.ps1`'s four refusals (an existing session log; an existing run root; no approval; no predecessor rule record) and the new HEAD check | PowerShell invoked on a temporary `-Repo` layout for each refusal: non-zero exit, nothing created; the positive path with a stub `rl/m8_sd2_session.py` in the layout that only writes `state.json` `done` |
| U2 | `wait_session.py`'s error exits (no launch record; another session's record; the process gone before any state record; gone without a `done` state; the hard limit) | a fake launch record with an already-exited pid and `--hours 0.01`; each message asserted |
| U3 | the S7 check finding "refused" or a traceback in the session's stdout / stderr | `check_launch.py` on temporary files: exit 0 on a clean start, non-zero with the offending line quoted |
| U4 | `write_approval.py`'s live refusals (another HEAD, another fingerprint, an existing approval, a snapshot that is not PASS) | sd1's `approval_isolated5` pattern, extended to the S2 rule text and `NOT_STARTED` |
| U5 | N4: an unstamped JSON-like file copied into `launch/`; `verify-run` after the copies | `copy_launch_evidence.py` on a temporary tree: stamped files kept, unstamped renamed `.txt`, `derived/` holding exactly two files |
| U6 | S3: a `runs_backup.py verify` against an earlier increment (it rewrites that increment's `verification.json`) | `post_run_checks.py` refuses any `--dest` but the new increment's; the independent re-hash loop over every registered increment on a temporary layout |
| U7 | the results-record checker on a bad live file | sd1's `results_record_rule5` pattern (already closed by tests; kept) |
| U8 | a native INVALID at the open (an inexact record or identity replay) and a native INCOMPLETE (a cap, a memory or process-count stop) | synthetic only (`decide6`, the small runs with injected stops); cannot be closed without native ticks and is not proposed |
| U9 | a pool of more than one batch, an inexact pool replay, `remaining_faster_than_best` | synthetic only (the e2e's pool had 424 candidates and 3 replays); as U8 |
| U10 | RECORD_BELOW_MARGIN as a realised outcome | synthetic only |
| U11 | a replayed clear whose clock differs from its registered tick | synthetic only |

### 5.5 Effort and the run's estimates

| item | estimate | basis |
| --- | --- | --- |
| code | 3,500 to 4,500 lines (sd1: 6,017 incl. a 1,970-line suite; sd2 subclasses rather than rewrites) | sd1's module sizes |
| preparation | one zero-tick session of about 8 to 10 hours of work for the modules, tools and suite, then the three passes (about 2 hours: each pass's e2e grows by the synthetic sd1 run) and the existing suites (about 2.5 hours incl. sd1's) which run unattended; a preparation record `docs/rl_m8_sd2_prep_<date>.md`; then the user commits (the three M9 unit suites' git gates clear only on the committed tree, as in sd1's Part B) | sd1's preparation of 2026-10-11 |
| the run's native ticks | about **6.06 M**: open 33,000 to 36,000 (P1 6,208; 16 identity replays about 25,000 to 28,000, the top-level cells are 1,776 to 2,086 words; the record 2,086), exploration 6,000,000 (the cap binds at about 45 min), verification 25,000 to 35,000 (the pool's first batches at about 2,050 words each; no inherited; 16 close identity about 22,000) | sd1's 34,706 / 6,000,000 / 31,687 |
| the session clock | 50 to 55 minutes (cap 60) | sd1's 3,218 s |
| the process | 85 to 90 minutes: the internal preflight about 30 minutes (the unit suite about 15, the open protocol over five trees about 12), the clock, the close about 7 minutes at about 51,000 cells | sd1: 23:10:56 to 00:32:46 |
| the launch day | 6 to 7 hours: Part B about 3.5 hours (three passes 90 min, the suites 2 h incl. sd1's), C1 to C3 about 35 minutes, the run 90 minutes, Part D about 70 minutes (`verify-run` twice at about 7 min, `report` 7, the increment and its three checks 2, the independent re-hash of 19 earlier increments about 17, coverage 2, the record) | sd1: 19:33 to 01:16 |
| archive at the close | about 50,500 to 51,500 cells (+6,500 to 7,500); main process private about 1.3 to 1.5 GB (cap 3,072); process tree about 4.7 GB private (cap 9,216) | sd1: +6,695 cells, 1,253 MB, 4,614 MB |
| throughput validity | 667 ticks/s needed; sd1 measured 2,175 | |

---

## 6. The launch path, with sd1's lessons built in

**Conventions for the whole launch day.** Git Bash, forward slashes in every path, `python -B -X utf8` always; one date for everything dated = the local
date when Part B starts, kept across midnight; **every output under `logs/m8_sd2_run/`** (Part B under `logs/m8_sd2_run/partB/`), nothing under
`logs/m8_sd2_prep/` or any directory of the snapshot set; no tracked file edited, nothing staged, only new files; no application closed; no other AI
session on the machine; the machine sampler (N2) running from the Part B baseline to the end, one sample every 30 s, with the baseline processes named.

**Part A: state.** HEAD = `origin/main` = the remote's `main`, carrying the sd2 modules, `tools/m8_sd2/`, this proposal, the preparation record, sd1's
approval and results record; nothing staged; `git status --porcelain --untracked-files=all` empty; `python -B rl/m8_sd2_session.py fingerprint` equals the
preparation record's value. Any failure is a stop.

**Part B: conditions (zero native ticks; all must hold).**

| step | command (from the repository root) | holds when |
| --- | --- | --- |
| B0 | `git rev-parse HEAD origin/main; git ls-remote origin refs/heads/main; git status --porcelain --untracked-files=all; git diff --check; python -B rl/m8_sd2_session.py fingerprint` → `logs/m8_sd2_run/partB/b0_git_state.txt` | equal, empty, clean, the pinned fingerprint |
| B1 | `python -B -X utf8 tools/m8_sd2/three_passes.py --session sd2 --out logs/m8_sd2_run/partB/three_passes` (no `--allow-git-gate`); then one after another: `rl/m8_rd_tests.py` unit 48/48 and e2e PASS, `rl/m8_rd2_tests.py` 27/27 and e2e PASS, `rl/m8_rd3_tests.py` 67/67 and e2e PASS, `rl/m8_rd4_tests.py` 79/79 and e2e PASS, **`rl/m8_sd1_tests.py` unit 87/87 and e2e `4cadf507c1c4fbc9`**, the g3 rule self-test (s1 `dea9965a3989bce5`, line `d9d82885703c016d`), `rl/m9_eval_tests.py` 29/29, `rl/m9_g2_tests.py` 29/29, `rl/m9_tests.py` 62/63 with only `identity_names_every_registered_pin`, `rl/m9_g3_tests.py` 29/29 and e2e `078f46c445d8adc5`, the six rule self-tests (rd1 `e0bbfe21...`, rd2 `f9779faa...`, rd3 `fae00396...`, rd4 `246813ee...`, sd1 `8267341f...`, sd2 at its pinned digest); outputs under `logs/m8_sd2_run/partB/suites/` | THREE_CONSECUTIVE_PASSES with the pinned e2e digest and the fingerprint unchanged; every registered result reproduced |
| B2 | the registered digests (the sd2 rule, claims, artifacts and draws digests; v4 at 2,086 and v4 at 2,315; v3; v2; both overlay digests) and the line consequence computed by `m8_sd2_rule.line_status` on the constructed cases including **NOT_STARTED**, equal to section 4 | all equal |
| B3 | the pins: executable `30a3913b...`, the runtime files, the frozen configuration, no controller-rule CVars, the status table | as pinned |
| B4 | the five earlier trees: `tools/m8_sd2/independent_increment_check.ps1 -Source runs/<tree> -Dest D:/BattleShip_runs_backup/<increment>` for rd1 (166), rd2 (62), rd3 (77), rd4 (93), **sd1 (130)**, invoked from Git Bash; the session's R1 in B6. **The tool's verify is never run on an existing increment** | `missing=0 extra_in_backup=0 bad=0 result=PASS` each |
| B5 | combined coverage: 0 uncovered `runs/` files | |
| B6 | `python -B -X utf8 rl/m8_sd2_session.py preflight --skip-unit` → `logs/m8_sd2_run/partB/preflight_skip_unit.json` | exit 1 with exactly one problem, `no approval record at docs\rl_m8_sd2_approval.json`; R1 to R5 ok at five levels; zero inherited candidates; readiness ok |
| B7 | the budget projection | the pessimistic total inside the 60-minute cap without trimming |
| B8 | the machine: no BattleShip, node or Playwright process; the IDE and video tools closed; the sampler's baseline recorded | `logs/m8_sd2_run/partB/b8_machine.txt` |
| B9 | the authorisation file `logs/m8_sd2_run/authorisation_sd2_<date>.txt` (Part C verbatim with the session date) as the last Part B file | |

**Part C: exactly once.**

| step | command | lesson built in |
| --- | --- | --- |
| C1 | `python -B -X utf8 rl/m8_sd2_snapshot.py snapshot --dest D:/BattleShip_source_snapshots/<date>_m8_sd2`; `... verify --dest ...`; `... powershell --dest ... --out logs/m8_sd2_run/independent_snapshot_rehash.ps1`; `powershell -NoProfile -ExecutionPolicy Bypass -File logs/m8_sd2_run/independent_snapshot_rehash.ps1 > logs/m8_sd2_run/independent_snapshot_rehash_output.txt` | the snapshot's file set excludes the run log directory, so nothing written on launch day can make it refuse |
| C2 | `python -B -X utf8 tools/m8_sd2/write_approval.py --session sd2 --snapshot D:/BattleShip_source_snapshots/<date>_m8_sd2 --independent "<the two verifications>" --authorisation-file logs/m8_sd2_run/authorisation_sd2_<date>.txt --authorised-on <date>` → `docs/rl_m8_sd2_approval.json` | the tool prints the **S2 rule** on success: from here to the launch no commit, no edit of any pinned document, no `runs_backup.py verify` or `backup` of any existing increment, no new folder on D: (the approval's D: digest) |
| C3 | `python -B -X utf8 rl/m8_sd2_session.py preflight > logs/m8_sd2_run/preflight_full.json` (the full preflight, once; if it fails, stop) | |
| C4 | `powershell -NoProfile -ExecutionPolicy Bypass -File tools/m8_sd2/launch_detached.ps1 -Session sd2 -Repo 'C:/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip'`; then, **within two minutes**, `python -B -X utf8 tools/m8_sd2/check_launch.py --session sd2` | the launcher re-checks HEAD against the approval before starting anything; the check tool confirms the pid alive and no "refused" or traceback; a non-zero exit is a stop and a report, never a relaunch; the launching terminal stays open |
| C5 | `python -B -X utf8 tools/m8_sd2/wait_session.py --session sd2` (default limit 3.5 h) | the limit fits the run (about 90 minutes) and ends the waiter only |

**Part D: afterwards.**

| step | command | lesson built in |
| --- | --- | --- |
| D1 | `python -B -X utf8 rl/m8_sd2_session.py verify-run > logs/m8_sd2_run/verify_run.json`; `... report > logs/m8_sd2_run/report.json`; `python -B -X utf8 tools/m8_sd2/copy_launch_evidence.py --session sd2` (then `verify-run` again, which it runs) | only stamped sd2-tool JSON reaches `launch/` and `derived/`; hand captures become `.txt` |
| D2 | `python -B -X utf8 rl/tools/runs_backup.py backup --source runs/m8_rd_sd2 --dest D:/BattleShip_runs_backup/<date>_incr_m8_sd2`; `... verify --source runs/m8_rd_sd2 --dest ...`; `powershell ... tools/m8_sd2/independent_increment_check.ps1 -Source runs/m8_rd_sd2 -Dest ...` | `--source` mandatory on both; this is the only increment the tool's verify touches |
| D3 | `python -B -X utf8 tools/m8_sd2/post_run_checks.py --session sd2` | the independent re-hash of every registered earlier increment (19, sd1's included), R1 over five trees, coverage 0 uncovered; it refuses the tool's verify on any earlier increment |
| D4 | the results record `docs/rl_m8_sd2_results_<YYYY-MM-DD>.md` (the session date): first line `# M8-sd2 results (<same date>)`, a `## ` section, a final newline, no other entry of `docs/` starting with `rl_m8_sd2_results`; `python -B rl/m8_sd2_session.py check-results-record --path docs/rl_m8_sd2_results_<date>.md` | the exact rule, as sd1's |
| D5 | the report (section 6.6) and `git status --porcelain --untracked-files=all` (expected: the approval and the record, nothing else) | no commit by the session |

**6.5 The NOT_STARTED consequence, written in the approval and the authorisation.** If `run` ends INCOMPLETE before the first dispatch (the open phase
or a readiness stop), the session does not count. Before any second attempt: the attempt's `logs/m8_sd2_run/` is renamed `logs/m8_sd2_run_not_started_<utc>/`
(outside every snapshot set); if `runs/m8_rd_sd2` was created, it is renamed `runs/_m8_rd_sd2_not_started_<utc>` and backed up as its own increment so that
coverage stays at 0 uncovered (a run tree is never deleted or overwritten); the approval is void (it is used once) and a new approval and a new snapshot,
dated the new session date, precede the retry, which is sd2 again. Open question 7.

**6.6 Naming.** Snapshot `D:\BattleShip_source_snapshots\<date>_m8_sd2`; increment `D:\BattleShip_runs_backup\<date>_incr_m8_sd2`; approval
`docs/rl_m8_sd2_approval.json`; results record `docs/rl_m8_sd2_results_<YYYY-MM-DD>.md` (first line `# M8-sd2 results (<same date>)`, a `##` section, a
final newline); logs `logs/m8_sd2_run/` (launch day) and `logs/m8_sd2_prep/` (preparation only); tree `runs/m8_rd_sd2/`. **The report** after the run:
the outcome and the line status with the rule digest; the best verified clear's two clocks and digest and the tiers reached; every verified clear; the
native ticks per phase against the caps; the open (P1, 16 / 16 identity, the 2,086 record re-verified); the pool's size, order and closure; the close
checks (the six-part audit, the prefix chain, the five trees, the stamp audit); `verify-run`; resources against the caps and the maximum number of game
processes with any transient 11th; the increment and the coverage; the results record's path; `git status`.

---

## 7. Risks, and what should not carry over from sd1

1. **The slack is spent (3.2).** sd1's odds rested on a 168-tick fast tail; sd2's rest on an ending nobody has shortened and on 18 undispatched level-8
   cells. Expect a NO_SHORTER_CLEAR as the single most likely outcome and plan the review accordingly.
2. **E7 at 2,061 removes the archive's productive region.** The band [2,062, 2,290] gave sd1 658 of the 709 new cells its level-9 dispatches produced;
   the eligible level-9 band gave 0.16 new cells per return. This is the design working as registered, not a defect; it does mean sd2's "new cells per return" reading will fall,
   and the dilution verdict will improve, for reasons that say nothing about progress.
3. **The count term starves fresh representatives of old cells (3.4).** The one right-side lineage ahead of the record will not be pursued under the same
   design. Carry it into the review, not into sd2.
4. **Ten game processes against a cap of ten.** sd1's maximum equalled the cap in every sample; two samples above it end the session INCOMPLETE and, once
   exploration has started, counted. The N2 sampler and the quiet-machine rules carry over; nothing closes this risk short of N = 4 (section 2 C4).
5. **The single-candidate pool.** sd1 never exercised a multi-batch pool or an inexact native replay on the real executable (U9, U11); an inexact replay
   is INVALID for the whole session by design. The risk is inherent and accepted.
6. **Git-state gates.** The g1, g2 and g3 unit suites refuse untracked non-M9 files under `rl/` and `docs/`; sd2's files, this proposal and the
   preparation record must be committed before Part B (sd1's Part B reproduced 29/29, 29/29, 62/63 on the committed tree).
7. **Between the approval and the launch.** The approval pins HEAD, every code and document hash and the D: folders' top-level files; a commit, an edit
   of a pinned document, a `runs_backup.py verify` on an earlier increment, or a new folder on D: makes the full preflight or the run's own preflight
   refuse (sd1's S2). The launcher's HEAD check (5.2) catches the first of these early.
8. **Background processes.** sd1 found four idle Claude Code processes of closed sessions and a windowless Edge that relaunched itself; the g3 line met
   stray `node` processes of 46 GB. The sampler and the baseline procedure carry over; the memory guard (1,024 MB available, 2,048 MB commit) ends a
   session INCOMPLETE and counted.
9. **Drafts.** Nothing named `rl_m8_sd2_results*` may exist under `docs/` but the final record; nothing under `logs/m8_sd2_prep/` may be written on launch day.
10. **The executable.** A rebuilt executable or a changed `.o2r` is a pin drift (INVALID); the archive's exactness claim rests on `30a3913b...`.
11. **Not to carry over:** sd1's hand-written Part B shell script and machine sampler (`launch/session_scripts/*.txt`) become tracked tools or stay
    documented commands (open question 6); sd1's waiter default of 2.5 hours (3.5 built in); the preparation record's draft location
    `logs/m8_sd1_prep/launch_<date>/` (superseded by S4; `logs/m8_sd2_run/` from the start); the three inherited descriptive replays (none by the rule);
    the expectation, from sd1's proposal, that a shorter clear is "the record without a detour" (there is no detour left in the record).
12. **What a PROGRESS would and would not say** is sd1's statement: an exactly replayable, agent-generated controller sequence clearing the stage in fewer
    input ticks than any verified before, by at least the margin; nothing about a policy or learning; not attributable to v4; not robust to another
    executable; no new crossing; nothing about the 7.43-second figure, which enters no sd2 quantity.

---

## 8. Open questions (numbered; each with options, my recommendation and why)

1. **"The same design" (section 1.1).** Confirm the carried-over set as listed, with only the items of 1.2 changing. *Options:* confirm; name any item
   to change (which then falls under section 2). *Recommendation:* confirm; the line rule's "under the same design" is what makes sd2 proposable
   without a review.
2. **The round tier (1.3).** *Options:* 1,800 (the stretch tier below the 10 % tier, sd1's role); 1,900; 2,000 kept as the literal constant.
   *Recommendation:* 1,800; reported only, and the only reading of "a round threshold below the reference" that keeps the tiers ordered.
3. **The exploration tick cap (2 C1).** *Options:* keep 6,000,000 (the wall slack of about 4 minutes unused); raise to 6,500,000; wall only.
   *Recommendation:* keep; an 8 % gain is not worth a registered constant that differs from rd4's and sd1's.
4. **Module strategy (5.1).** *Options:* new `rl/m8_sd2_*.py` and `tools/m8_sd2/` subclassing sd1 (the M8 pattern); generalise sd1's modules to
   `--session sdK` (edits tracked, pinned files); a generic "sdK" set written now. *Recommendation:* the first; it is what every M8 session did and it
   leaves sd1's code and suite byte-identical.
5. **The untested paths (5.4).** The review's T1 to T6 are not in the repository. *Options:* map T1 to T6 onto U1 to U11 and confirm that U1 to U6 are
   closed by zero-tick tests and U7 to U11 stay synthetic; or give me the review's list to fold in. *Recommendation:* close U1 to U6 as proposed; they are
   the paths a refusal or a mistake on launch day would hit first.
6. **The new tools (5.2).** *Options:* the three (`check_launch.py`, `copy_launch_evidence.py`, `post_run_checks.py`); the three plus `machine_sampler.py`;
   all four plus `run_part_b.py`. *Recommendation:* the three plus the sampler; Part B as a documented command table is enough, and a Part B tool that
   runs every suite is a large script to test.
7. **The NOT_STARTED procedure (6.5).** *Options:* rename the attempt's logs and any created tree, back the tree up as its own increment, new approval and
   snapshot, run sd2 again; or delete the partial tree. *Recommendation:* the first; a run tree is never overwritten, and coverage must stay at 0.
8. **The line statuses (section 4).** *Options:* confirm the five (`REPAIR_NEEDED`, `NOT_STARTED`, `COUNTED_INCOMPLETE`, `SD3_AFTER_REVIEW_NEW_REFERENCE`,
   `SD3_AFTER_REVIEW_WITH_REASON`) with a written review required before any sd3 whatever the counted outcome; or allow an sd3 after PROGRESS without a
   review. *Recommendation:* confirm; sd1's registered line says "no third session without a review", and section 3.6 says the review is needed on the merits.
9. **The rd line.** Confirm that sd2 neither consumes nor grants rd5 (copied through unchanged). *Recommendation:* confirm.
10. **The count-term finding (2 C3).** *Options:* no change for sd2, the finding goes to the review; or make sd2 a v5 session with a representative-age
    term (then sd2 is not "under the same design" and needs its own proposal and justification). *Recommendation:* no change; one session, one question.
11. **Part B scope (2 C7).** *Options:* add sd1's unit and e2e to the registered suites of Part B (about 30 minutes); or not. *Recommendation:* add them.
12. **Scheduling.** *Options:* the preparation session, the commit, the three M9 suites on the committed tree, then the launch session on a quiet day;
    or preparation and launch on the same day. *Recommendation:* separate days; the launch day is already 6 to 7 hours and sd1's review found the
    launch-day mistakes, not the preparation's.
13. **The authorisation text.** *Options:* sd1's Part C with the session-date rule, S2, S3, S7 within two minutes, the 3.5-hour waiter, N1, N2, N4 and
    the NOT_STARTED consequence, with sd2's names; or a shorter text. *Recommendation:* the full text; the approval quotes it verbatim and the record
    checks against it.

---

## Appendix A. Scratch analyses (read only; `logs/m8_sd2_proposal/`, Git-ignored)

| script | input | used in |
| --- | --- | --- |
| `census_sd2.py` (+ `census_sd2_output.txt`) | `runs/m8_rd_sd1/archive/{cells,events}.jsonl`, `sessions/sd1/{ledger_T.json,iterations_T.jsonl}` | 3.1, 3.2, 3.4, 3.5 (per-level counts, the bands, the families, the parent chains, sd1's dispatch yields, the analytic masses at both bounds) |
| `census_tail_sd2.py` (+ output) | the same, `archive_meta.json`, `sessions/sd1/*.json`, the sd1 increment's `verification.json`, the sd1 documents | 1.4 (the pinned facts and digests), 3.2 (the grounded cells), 3.4 |
| `endings_sd2.py` (+ output) | `sessions/sd1/verification/{T_c0901_clear,record_open}.json.gz` | 3.3 (the two endings) |

No script imported a repository module, launched a process, read the TAS, a fixture or a recording, or wrote anywhere but `logs/m8_sd2_proposal/`.

## Appendix B. Sources

- `docs/rl_m8_sd1_proposal_2026-10-07.md`, `docs/rl_m8_sd1_prep_2026-10-11.md`, `docs/rl_m8_sd1_results_2026-10-11.md`, `docs/rl_m8_sd1_approval.json`
  (the design, its decisions and amendments S2, S3, S4, S7, N1, N2, N4, N7, and the run).
- `rl/m8_sd1_{select,resume,claims,rule,run,session,report,artifacts,snapshot,tests}.py`, `tools/m8_sd1/*` (what carries over and what needs a counterpart).
- `docs/rl_m9_g3_progression_fix_2026-10-08.md` (the exact results-record rule, `--session` required, the launch-day pitfalls), `docs/rl_runbook.md`
  sections 2, 3.3 to 3.5 and 6 (the absolute rules, the launch sequence, pitfalls P1, P4, P5, P8, P9, P11, P12).
- `docs/rl_m8_rd3_stop_review_2026-10-03.md` (the model for the review after sd2), `docs/rl_m8_rd4_results_2026-10-03.md` (the record route).
- A. Ecoffet et al., *First return, then explore*, Nature 590 (2021): the per-cell count term whose blind spot section 3.4 records.
