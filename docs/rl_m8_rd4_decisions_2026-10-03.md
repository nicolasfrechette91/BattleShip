# M8-rd4: the user's decisions for the third continuation, and how they were applied (2026-10-03)

**Status.** Recorded **before any native tick** of M8-rd4, at the start of an unattended session whose Part A is zero-tick preparation, whose Part B is the launch conditions and whose Part C (one
native session) runs only if every Part B condition holds. Nothing in the frozen proposals, in any rd1, rd2 or rd3 file, in `runs/m8_rd/`, `runs/m8_rd_rd2/` or `runs/m8_rd_rd3/`, in the external
guide or in any tracked file was edited. This file, `docs/rl_m8_rd4_implementation.md` and the new `rl/m8_rd4_*.py` files are the additions.

**Scope label**, carried by every rd4 record: *third continuation of archive `m8_rd_a1` (rd1, rd2 and rd3 as closed) under `m8_rd_select_v3` (`m8_rd_select_v2` with one change: the count term
`(1 + seen)^-1/2`); one session, one set of keyed draws; no control arm; not a policy result, not a learning result, not a comparison of v3 with v2.*

This session implements `docs/rl_m8_rd3_stop_review_2026-10-03.md` (the file's name carries the date of its commit; the prompt called it 2026-10-02).

## 1. The decisions (the user's words, abridged) and where each is applied

| # | decision | applied in |
| ---: | --- | --- |
| 1 | **The line continues for at most two sessions: rd4, then rd5 at most.** No verified qualified crossing (or higher) by the end of rd5 ends the line. An INCOMPLETE session counts as one of the two once exploration has started | `rl/m8_rd4_rule.py` (`line_status`, `BUDGET`, the `line` record of every outcome) |
| 2 | **Selection `m8_rd_select_v3` = v2 with exactly one change**: the K1 weight `1/sqrt(1 + times seen)`, the published exponent 1/2. Recovery bound, v2 doom, the one-target-left exception, resource weights, harmonic level weight, the cell key, the explorer and the burst length are unchanged. **Draw-key prefix rd4-specific** | `rl/m8_rd4_select.py` (`Archive4`, `v3_weights`, `select3_description`; draw id `m8_rd_a1_rd4`; the contract digest is built from v2's own description with only the registered keys replaced, and a test enforces that no other key differs) |
| 3 | **Resume from rd3's closing archive (rd1 + rd2 + rd3)** with rd3's procedure and strength: immutability of all three earlier trees at open and close; a zero-tick ledger rebuild reproducing rd3's closing archive and closing overlay exactly as recorded in rd3's results; rd4's ledger copy begins with rd3's exact ledger bytes; P1 and 16 identity replays; iterations continue from rd3's last; rd4 writes only `runs/m8_rd_rd4/`, which must fall under D: backup coverage | `rl/m8_rd4_resume.py` (R1-R6 at three levels, `materialise4`, `prefix_chain`), `rl/m8_rd4_select.py` (`rebuild4`, `audit4`), `rl/m8_rd4_run.py` (`Session4`, `close_checks`), `rl/m8_rd4_session.py` (`RD4_ROOT`, the write guard over all three trees, the D: increment `2026-10-03_incr_m8_rd4`) |
| 4 | **Caps as rd2 and rd3**: exploration 50 min or 6,000,000 native ticks, valid from 2,000,000; open phase 70,000 ticks / 4 min; verification 400,000 ticks / 6 min; 60-minute hard cap; memory caps unchanged | `rl/m8_rd4_session.run_config`, `caps()` (the same numbers; a test asserts equality with rd2's and rd3's) |
| 5 | **Rule `m8_rd4_rule_v1`**: PROGRESS only for a verified qualified crossing (`btt_qualified_crossing_v1`), a left target or a clear; the highest milestone is reported; otherwise NO_NEW_MILESTONE. A crossing counts even when its entry lies in an inherited prefix and its landing in an rd4 burst; the full route is verified by exact replay from tick 0 | `rl/m8_rd4_rule.py` |
| 6 | **Claim-path safety**: the claim and verification code must handle candidates that start from inherited wall-top or left-of-wall cells without a false INVALID; the synthetic end-to-end test must exercise a crossing whose entry is in an inherited prefix and whose landing is in a new burst, and a wall-top continuation | `rl/m8_rd4_claims.py`, `rl/m8_rd4_run.py` (section 3 below); tests `claim_cases_on_stub_traces`, `claim_cases_session`, `verification_capacity_flood` and the production-count end-to-end run |
| 7 | **Mechanism check** at rd4's close: FAIL if more than 45.0 % of returns start from cells seen 8 or more times, or if new cells per return is below 1.74. If it fails AND rd4 has no verified crossing or higher, the line ends after rd4. A verified milestone always outranks the check | `rl/m8_rd4_rule.py` (`mechanism`, `line_status`), `rl/m8_rd4_report.py` (`mechanism_inputs`), `rl/m8_rd4_select.py` (`audit4`'s dispatch rows) |
| 8 | **Dilution: report only, no guard** | `rl/m8_rd4_rule.py` (the `dilution` record, `reported_only`) |
| 9 | **Diagnostics, reported only**: all rd3 diagnostics with rd1-rd3 references; returns to left-of-wall cells and to wall-top cells; the share of returns by start-cell session of creation; the seen-count distribution of start cells; closest approach to the left floor | `rl/m8_rd4_report.py` (`full_report4`) |
| 10 | **No non-deterministic test anywhere in the rd4 suite or preflight** | section 5 below; `rl/m8_rd4_tests.py` (`no_nondeterminism_in_rd4`) |

Constraints that stay as they were (unchanged in code, checked by tests): no native RNG seed inspection, logging, control, comparison or hashing (every draw is a Python-side keyed sha256
uniform); process restart resets the episode; the exact submit / consume / input-tick contract; canonical controller words are the replay truth with no hidden actions; prefixes are
agent-generated only; human crossing recordings, the fixtures and the TAS are validation-only and never read; no hardcoded route or waypoint; the non-PORT decomp and byte-matching behaviour is
preserved (no native, decomp or submodule change; the existing executable is used); no commit, push, branch or pull request; no training; no application is closed.

## 2. Mechanical readings the implementation needed (none changes a registered quantity)

The decisions fix every rule, constant, cap and threshold. The items below are the readings the code needed. Each can be overruled; none alters a registered definition, threshold, cap, the
cell key, the explorer, the replacement rule or the rule's outcome table. They are written down so that Part B condition 7 can be judged against them.

**I1. The base of rd4.** rd4's base is rd3's *closing* archive: `runs/m8_rd_rd3/archive/` (checkpoint sequence 32; `archive.prev` holds 31; 26,371 cells, 10,406 bursts, 20,814 ledger events,
iterations 0..10,405). Its five data files and manifest are copied byte for byte into `runs/m8_rd_rd4/base/`; rd4's own `archive/` starts as that copy plus one new `session` event (name `rd4`)
and is the first checkpoint (sequence 33). The frozen runtime is rd1's, read in place from `runs/m8_rd/archive/runtime/` exactly as in rd2 and rd3.

**I2. The `session` event of rd4.** `{"ev": "session", "name": "rd4", "select": "m8_rd_select_v3", "digest": <v3's digest>, "first_iteration": 10406, "draw_suffix": "_rd4", "changed_from":
{"select": "m8_rd_select_v2", "digest": <v2's digest>, "change": ...}}`. v2's digest is *recomputed from the current code* and must equal the digests of rd2's and rd3's own session events: that
equality is the proof that the earlier sessions ran v2 unchanged and that the base is rd4's history. The ledger rebuild applies the rule and the draw id by session: iterations 0-2,174 under v1
(rd1's key), 2,175-6,211 under v2 (`m8_rd_a1_v2`), 6,212-10,405 under v2 (`m8_rd_a1_rd3`), 10,406 onwards under v3 (`m8_rd_a1_rd4`).

**I3. The rd4 keys.** Selection `m8_rd|m8_rd_a1_rd4|select|<iteration>`; exploration `m8_rd|m8_rd_a1_rd4|explore|<iteration>|<decision index>`; open identity
`m8_rd|m8_rd_a1|identity_open|rd4|<cell id>`; close identity `m8_rd|m8_rd_a1|identity_close|rd4|<cell id>`. Iterations are never reused.

**I4. What `m8_rd_select_v3` reads.** `seen` only (Go-Explore's C_seen: the bursts that visited the cell, incremented once per burst however often the cell is visited in it). `chosen` stays a
counter of the ledger (the archive format is unchanged) and no longer enters the weight. The analytic probabilities exist in both modes on the same archive (`Archive4.probabilities("v2" | "v3")`);
the default is v3 once rd4 has begun and v2 before. Eligibility is v2's, so **the overlay at rd4's open is rd3's closing overlay** (the same flags, the same digest).

**I5. The rule's vocabulary.** The four outcomes are INVALID, INCOMPLETE, PROGRESS and NO_NEW_MILESTONE, evaluated in that order. PROGRESS iff `m >= 2`, with m the highest of the levels 2
(qualified crossing), 3 (left target), 4 (clear) held by an exact fresh-process replay from tick 0 of a trajectory whose qualifying event lies in a burst ingested during rd4. The wall-top
landing (level 1) is rd2's and is not claimed again; rd4's m is 0, 2, 3 or 4. The maximum number of targets verified is **reported, not a basis**: a trajectory with eight or more targets broke a
left target (only seven targets lie right of the wall), so it is already m >= 3. "Qualifying event lies in an rd4 burst" is made true by a registered open-protocol check (I9), not assumed.

**I6. The mechanism check.** *Returns* are rd4's ingested jobs (an aborted job's dispatch is not a return). *Seen at dispatch* is the start cell's `seen` counter at the moment of the dispatch,
read from the zero-tick ledger replay that the close audit already performs (the audit's own rebuild reports it: the ledger is rebuilt once). *New cells* are the cells created from the open
archive's cell count on (the quantity rd3's report called new cells per return). Both comparisons are exact integer arithmetic: a share of exactly 45.0 % and exactly 1.74 new cells per return
hold; one more start from a seen >= 8 cell, or one cell fewer, fails. The check is computed from the ledger, so `verify-run` recomputes it independently. A live counter of the same readings is
kept by the session and written to the close record beside the ledger's (an equality check, informational). With no returns the check is NOT_EVALUABLE (neither holds nor fails).

**I7. The line budget (decisions 1 and 7), read mechanically.**
- A verified milestone (`m >= 2`) outranks everything below (status MILESTONE_VERIFIED): rd5 may be proposed (it needs its own authorisation); the mechanism check does not apply.
- No milestone and exploration started: a FAILED mechanism check ends the line after rd4 (LINE_ENDS_MECHANISM_FAILED); a holding or not-evaluable check leaves rd5 as the last session
  (RD5_LAST_SESSION). An INCOMPLETE session counts as one of the two (`session_counts`), and decision 7 is applied to it as written. The line record also carries `exploration_ticks`,
  `mechanism_returns` and a `provisional` flag, true when the status was read from fewer than 2,000,000 exploration ticks (the validity floor): per-return yield is heavy-tailed, so a session
  stopped early can fail the new-cell test by noise. The flag is descriptive: **the status itself is applied exactly as decisions 1 and 7 state it**, and making a partial session "not evaluable"
  would change a registered measure, which is the user's to decide (recorded for the report, not decided).
- Exploration never started (nothing dispatched): the session does not count (NOT_STARTED).
- INVALID: repair and a new approval. **Whether an INVALID session consumes budget is not stated by the decisions, so it is not guessed**: `rd5_permitted` is `null` and the reason says so.
- "No verified qualified crossing (or higher) by the end of rd5 ends the line" is a statement about rd5's close; rd4's record carries the budget text and the status, and rd5 would carry the same
  rule. The prior sessions' milestones are read from their own recorded files (a missing record raises; a record without its milestone field raises, never read as zero).
- Stops carried from rd3's rule: S3 (horizon pressure), S5 (BOUND_VIOLATION withdraws the bound), S7 (INVALID / INCOMPLETE: repair and a new approval, never an extension or a retry). S1, S2,
  S4 and S6 are replaced by the line budget.

**I8. Identity samples.** The open sample (K = 16) and the close sample are rd2's and rd3's designs with the rd4 keys; "highest-weight" at the open means the four highest analytic
probabilities under v3 (the rule rd4 runs). Their iteration numbers for the identity jobs are rd4's own (6,000,000 and 7,000,000 bases).

**I9. The inherited archive's claim preconditions (registered).** The open protocol refuses the session unless the inherited archive holds **no grounded cell on the left floor, no cell with a
left target broken, and no cell above level 7**, and unless its inherited frontier is exactly the registered one (two wall-top cells 18,318 and 18,767; 54 cells left of x = -2,100). This is what
makes "every milestone above the wall top that an rd4 replay credits arises in an rd4 burst" true: a replay's analyser reads the whole trajectory, and with nothing of the kind in the inherited
archive the qualifying event of a credited crossing, left target or clear can only lie in an rd4 burst (the entry of a crossing may lie in the inherited prefix, which decision 5 allows).
The check is also a test (`precondition_refuses_inherited_milestones`: a synthetic chain whose rd3 tree holds a landing on the left floor is refused). The cell-based facts cannot see a
grounded tick under an X-class status (that cell key carries no floor), so the open protocol adds a read-only **registry-level** check (review finding 6): no candidate in the arm-T
registries of rd1, rd2 and rd3 (`sessions/<rd>/ledger_T.json`, `candidates[*].first`) carries a `left_floor`, `left_break` or `clear` event, and each registry exists. On the real trees it
holds (rd1: 14 candidates, rd2: 23, rd3: 27; the only first-events ever registered are `l0` once in rd2 and `left_live` three times in rd3). The check refuses; it changes no registered measure.

**I10. The diagnostics of decision 9, as implemented.** All reported only; the selection, the explorer, the cell key and the rule read none of them except the mechanism check's two counts.
- D1-D9 of rd2 and the new readings of rd3, for rd4 and for three reference columns (rd3, rd2, rd1), each recomputed by the same functions from the archives.
- *Returns to left-of-wall cells and to wall-top cells*: dispatches whose start cell's stored position is left of x = -2,100 (also -1,800 and -1,650) and cells grounded on floor line 0.
- *Share of returns by start-cell session of creation*: the session whose iterations contain the start cell's `first_iter` (cell 0 counts as rd1).
- *Seen-count distribution of the start cells*: at dispatch, buckets 0-1, 2-3, 4-7, 8-15, 16-31, 32-63, 64+, with the new cells per return of each class.
- *Closest approach to the left floor*: rd3's reading (minimum point-to-segment distance to floor line 3), with the nearest cell.
- *Selection probabilities at the open under v2 and v3*: wall-top cells, eligible left-of-wall cells, cells seen 8 or more times (a reading of the change, never an input).

**I11. The session clock, the identity and the order of the approval.** As rd3's (decisions I12-I14): the clock starts at the session object and counts the worker start-up; the three phase caps sum to
the 60-minute hard cap; the approval record names the source snapshot's digest, so the snapshot is taken first and the approval written from the freshly printed template right after it.

## 3. Claim-path safety (decision 6), and the hazard found in preparation

**The wall-top label (rd3's I15, carried).** The frozen claims engine registers an `l0` candidate from a burst's first grounded tick on floor line 0 and, in a replay, checks it against the first
line-0 tick of the whole trajectory. A burst that continues from a prefix already on line 0 (a wall-top cell, or any descendant) would be judged inexact: a false INVALID. rd4 removes that label
before the commit (`m8_rd3_run.suppress_wall_top_label`, applied by `Session3.commit`, which `Session4` inherits), records the sighting, and never claims the landing again. rd4's replay plan
additionally never replays an `l0` candidate at all. Four sightings occurred in rd3's real session; the wall-top cells carry about 0.07 % of the selection mass, so the case is expected again.

**The left-of-wall continuation.** Nothing in the frozen `evaluate_replay` compares a whole-trajectory first event with a claimed one for `left`, `clear` or `t` candidates (they are checked by the
native action digest, every consumed tick, the break table, and for a clear the four facts). A burst that continues from an inherited left-of-wall prefix carries its inherited `left_live` at its
first tick and is replayed like any other candidate: it cannot be a false INVALID. This is tested at component level on real stub traces and in a real session.

**The crossing whose entry lies in an inherited prefix.** The replay's analyser reads the whole trajectory, so a crossing whose over-wall entry is inherited and whose landing on floor line 3 is in
an rd4 burst is credited by the registered criterion. It is verified by exact replay from tick 0 of the complete canonical words (digest, every consumed tick, break table), exactly as any other claim.

**HAZARD FOUND IN PREPARATION (pre-launch review item; fixed; changes no registered measure, threshold, selection or cell key).** The frozen engine registers a `left` candidate for *every*
trajectory with a live step left of x = -2,100, and rd3's verification plan replays them in discovery order until a cap. rd3 registered 3 such candidates. rd4 returns to the 54 left-of-wall
cells (47 eligible: about 29 returns per session under v2 and 44 under v3, with feedback as new left cells appear), and **every** such return starts left of the wall, so it registers a `left`
candidate at its first tick: hundreds are expected. They cannot all be verified in the 400,000-tick / 6-minute caps, which the 16 close identity replays share. A session that found nothing would end
INCOMPLETE (an unverified candidate "could raise m"), and one that found a crossing late in discovery order would lose it behind hundreds of descriptive replays. The test
`verification_capacity_flood` reproduces it: 300 descriptive candidates need 75,578 replay ticks under the frozen plan before the one decisive candidate is reached, 26 % above a 60,000-tick cap
(the registered cap is 400,000, but the real floods are larger and the identity replays share it).

*The fix (in new files only; `rl/m8_rd4_claims.py`).* The registry is untouched: every candidate is still registered and stored (`candidates_T.jsonl.gz`). The plan changes: the
qualifying events of the ladder above the wall top need events the burst scanner already records (a qualified crossing needs a **landing** on the left floor, `left_floor`; a left target needs
`left_break`; a clear needs `clear`), so a `left` candidate carrying none of them can never raise m. The plan replays first, in discovery order and round-robin over the unsatisfied milestones,
the candidates that *can* raise m (the maximum-targets candidate stays first); the descriptive entries (a live step left of the wall and nothing more, which is every inherited continuation) are
replayed only after every pool is empty or satisfied, at most six of them (rd3 replayed three), and never decide INCOMPLETE; the INCOMPLETE test ("a candidate that could raise m left unverified at
the cap") reads only the can-raise pools. Consequences, each tested: a can-raise candidate placed last among 300 is the first replay; a verified crossing empties the crossing pool, so further
landing candidates (which cannot raise m above a crossing) are not replayed, while left-target and clear candidates still can be; the registered measures (m, t, the mechanism check, the thresholds,
the selection, the cell key) read nothing of the plan.

## 4. Known issue carried (recorded, not edited)

`rl/m8_rd2_tests.py::unit_cmd_run_with_fake_game` is the known flaky test of rd2 (rd3's decisions, section 3). rd4's suite does not run it; it runs the deterministic pure tests of rd1, rd2 and rd3 by
explicit lists (`RD1_PURE`, `RD2_PURE`, `RD3_PURE`).

## 5. What "deterministic" means for rd4's tests (decision 10)

(a) Pure tests use keyed sha256 streams and fixed data. (b) Every session-level test runs the real session engine against the synthetic stub world through rd3's in-process lock-step worker pool and
virtual clock: a run is a pure function of its configuration (tested: two builds of the synthetic chain are byte-identical and two runs of the same rd4 session agree on the archive's data files,
the decision, the mechanism check and the line status). (c) The one test that starts real processes (the fake game behind the real lifecycle code; its pass depends on process
scheduling) is **not in the suite and not in the preflight**: it is the separate non-gating command `rl/m8_rd4_tests.py integration` (review finding 2), asserting only facts that hold under every
schedule. The suite itself contains no test that starts a process other than git and the snapshot tool (deterministic by content). (d) No assertion depends on wall-clock duration (a test scans the sources: no `random`, `secrets`, `uuid`, `os.urandom`, `time.sleep`, and no
assertion that reads the wall clock). (e) The gates (git state, the closed real trees, their D: increments, the executable) assert facts fixed once the trees are closed and the work is staged:
such a test can fail when the state changes but cannot flake. (f) The verification runs its claim replays on a thread pool while the identity replays run on the main thread, both charging one
replay-tick counter (as rd3, decisions I8f): a result could depend on the interleaving only if the cap were nearly binding, which no suite test other than the replay-cap test approaches (that test
removes the identity replays). (g) The synthetic claim cases do not rely on chance: the first dispatches of the session are forced by choosing the *iteration number* whose selection is the wanted
inherited cell (the ledger allows skipped numbers: strictly increasing, never reused), so the ledger still audits and the selection is untouched.

## 6. Pre-launch review

The independent read-only review and its dispositions are recorded in `docs/rl_m8_rd4_implementation.md`, section 9a. Any hazard whose fix changed no registered measure, threshold, selection or
cell key is listed there and flagged in the session report.
