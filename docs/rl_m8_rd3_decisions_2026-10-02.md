# M8-rd3: the user's decisions for the second continuation, and how they were applied (2026-10-02)

**Status.** Recorded **before any native tick** of M8-rd3, at the start of an unattended session whose Part A is zero-tick preparation, whose Part B is the
launch conditions and whose Part C (one native session) runs only if every Part B condition holds. Nothing in the frozen proposal, in any rd1 or rd2
file, in `runs/m8_rd/` or in `runs/m8_rd_rd2/` was edited. This file, `docs/rl_m8_rd3_implementation.md` and the new `rl/m8_rd3_*.py` files are the additions.

**Scope label**, carried by every rd3 record: *second continuation of archive `m8_rd_a1` (rd1 and rd2 as closed) under `m8_rd_select_v2`; one session, one set
of keyed draws; no control arm; not a policy result, not a learning result, not a comparison of v2 with v1.*

## 1. The decisions (the user's words, abridged) and where each is applied

| # | decision | applied in |
| ---: | --- | --- |
| 1 | rd3 is a continuation resuming the archive as it stood at rd2's close (rd1 + rd2), with rd2's resume procedure and strength: immutability checks on **both** earlier trees at open and close; a zero-tick ledger rebuild that reproduces rd2's closing archive (19,062 cells) and its closing v2 overlay; rd3's ledger copy begins with rd2's exact ledger bytes; P1 and 16 identity replays; iterations continue from rd2's last; rd3 writes only to `runs/m8_rd_rd3/`, which must fall under D: backup coverage | `rl/m8_rd3_resume.py` (R1-R6 for two levels, `materialise3`, the prefix chain), `rl/m8_rd3_select.py` (`rebuild3`, `audit3`), `rl/m8_rd3_run.py` (`Session3`, close checks), `rl/m8_rd3_session.py` (`RD3_ROOT`, the write guard over both trees, the D: increment `2026-10-02_incr_m8_rd3`) |
| 2 | selection `m8_rd_select_v2` unchanged with every rd2 decision carried over (full recovery bound, v2 doom in replacement, the one-target-left exception, the tornado-unspent assumption); explorer and burst length unchanged; **draw-key prefix rd3-specific** | `Archive3` subclasses rd1's v2 archive and overrides nothing but the draw id by iteration; the contract digest of `m8_rd_select_v2` must equal the one in rd2's `session` event |
| 3 | caps as rd2: exploration 50 min or 6,000,000 ticks, valid from 2,000,000; open phase 70,000 ticks / 4 min; verification 400,000 ticks / 6 min; 60-minute hard cap; memory caps as rd1 and rd2 | `rl/m8_rd3_session.run_config`, `caps()` (the same numbers, tested equal to rd2's) |
| 4 | rule `m8_rd3_rule_v1`: PROGRESS if a verified milestone above the wall-top landing is found (qualified crossing < left target < clear) or if the verified maximum number of targets from tick 0 reaches 8 or more; otherwise NO_NEW_MILESTONE; every claim needs an exact full replay from tick 0; report the highest milestone and the maximum targets | `rl/m8_rd3_rule.py` |
| 5 | diagnostics, reported only: rd2's nine diagnostics with rd1 and rd2 reference values; the number of wall-top cells and the dispatches from them; cells left of the wall face; the closest approach to the left floor; the selection probability of the wall-top cells at the open | `rl/m8_rd3_report.py` |
| 6 | stop conditions carried over (the proposal's and rd2's); the original "no verified crossing after three sessions" is evaluated explicitly at rd3's close (rd3 is the third session) | `rl/m8_rd3_rule.py` (S1-S7, S2 with the three sessions' recorded milestones) |
| 7 | rd3's tests and preflight contain **no non-deterministic test**; deterministic rd3 versions in new files; rd2's flakiness recorded as a known issue | section 3 below; `rl/m8_rd3_tests.py` |

Constraints that stay as they were (unchanged in code, checked by tests): no native RNG seed inspection, logging, control, comparison or hashing (every
draw is a Python-side keyed sha256 uniform); process restart resets the episode; the exact submit / consume / input-tick contract; canonical controller words
are the replay truth with no hidden actions; prefixes are agent-generated only; human crossing recordings, the fixtures and the TAS are validation-only and
never read; no hardcoded route or waypoint; the non-PORT decomp and byte-matching behaviour is preserved (no native, decomp or submodule change; the existing
executable is used); no commit, push, branch or pull request; no training; no application is closed.

## 2. Mechanical readings the implementation needed (none changes a registered quantity)

The decisions fix every rule, constant, cap and threshold. The items below are the readings the code needed. Each can be overruled; none alters a registered
definition, cap, the cell key, the explorer, the selection or the rule's outcome table. They are written down so that Part B condition 7 (no open design
decision) can be judged against them.

**I1. The base of rd3.** rd3's base is rd2's *closing* archive: `runs/m8_rd_rd2/archive/` (checkpoint sequence 20; `archive.prev` holds 19). Its five data files
and manifest are copied byte for byte into `runs/m8_rd_rd3/base/`; rd3's own `archive/` starts as that copy plus one new `session` event (name `rd3`) and is the
first checkpoint (sequence 21). The frozen runtime (`BattleShip.cfg.json`, `imgui.ini`) is rd1's, read in place from `runs/m8_rd/archive/runtime/` exactly as in
rd2 (rd3 holds no copy; the live configuration is never read).

**I2. The `session` event of rd3.** `{"ev": "session", "name": "rd3", "select": "m8_rd_select_v2", "digest": <the digest of rd2's session event>, "first_iteration": 6212,
"draw_suffix": "_rd3"}`. The digest is *recomputed from the current code* and must equal rd2's recorded one: that equality is the proof that the selection,
the bound and the status table are unchanged. The ledger rebuild applies the draw id by session: iterations 0-2,174 select under v1 (rd1's key), iterations 2,175-6,211
under `m8_rd_a1_v2`, iterations 6,212 onwards under `m8_rd_a1_rd3`.

**I3. The rd3 keys.** Selection `m8_rd|m8_rd_a1_rd3|select|<iteration>`; exploration `m8_rd|m8_rd_a1_rd3|explore|<iteration>|<decision index>`; open identity
`m8_rd|m8_rd_a1|identity_open|rd3|<cell id>`; close identity `m8_rd|m8_rd_a1|identity_close|rd3|<cell id>`. The archive id stays `m8_rd_a1`. Iterations are never reused.

**I4. Cumulative counters.** `diag2` (revivals, newly descent-doomed, replaced doomed incumbents, bound violations) is cumulative over rd2 and rd3. rd3's own figures
are the difference to rd2's closing record (`runs/m8_rd_rd2/sessions/rd2/close.json`).

**I5. The rule's vocabulary.** The four outcomes are INVALID, INCOMPLETE, PROGRESS and NO_NEW_MILESTONE, evaluated in that order (INVALID and INCOMPLETE carry over from
rd2's rule, with rd2's conditions plus rd2's tree in the immutability and prefix checks). PROGRESS has two independent bases, both read only from verified quantities:
`m >= 2`, where m is the highest of the levels 2 qualified crossing, 3 left target, 4 clear held by an exact fresh-process replay from tick 0 of a trajectory whose qualifying
event lies in a burst ingested during rd3 (rd1 and rd2 hold none of them; the replay's analyser reads the whole trajectory, which is safe for these three); and `t >= 8`, where t is
the largest number of targets broken by any exactly replayed trajectory of rd3 (the maximum-targets candidate is replayed first, so it is among them; an inexact replay counts for
nothing and is INVALID). The wall-top landing (level 1) is rd2's: it is not re-claimed in rd3 (I15), so rd3's m is 0, 2, 3 or 4 and `highest_milestone` is "none" when rd3 finds no
new milestone; rd2's landing stays in the record as `highest_milestone_over_sessions` and in `prior_sessions`. The record carries `highest_milestone`, `max_targets_verified`, the list
of bases and `claims_verified`.

**I6. The stop conditions.** S1-S7 carry over from rd2's rule. S4 and S6 were written on rd2's outcome labels; they are evaluated on NO_NEW_MILESTONE with the same registered dilution
thresholds (below-floor dispatch share <= 10.5 %, fatal-return share <= 11.0 %) and the same launch-capable comparison against rd1's 14 / 2,175 per 1,000 returns,
computed on rd3's counts. S2 is evaluated explicitly: *no verified qualified crossing exists after three sessions* is triggered iff rd1, rd2 and rd3 all hold
m < 2, rd3 is not INVALID and rd3's claims were verified (an INCOMPLETE session that stopped before the verification has no verified claims to read: S2 is then reported as not
evaluable, next to S7). rd1's and rd2's milestones are read from their recorded files (rd2: `rule.json`, m = 1; rd1: `rule.json`, the higher of its two arms), not assumed; a record
that lacks its milestone field is refused, never read as zero. When S2 is triggered together with PROGRESS (a count of 8 or more without a crossing), both are reported and the line
stops for review, as the stop table says.

**I7. The new diagnostics.** *Wall-top cell*: resource class G on floor line 0 (the ledge, x -2,100..-1,200 at y 3,000). *Dispatches from them*: dispatch events whose
start cell is such a cell. *Left of the wall face*: stored x < -1,650 (the wall-face reference of the M7f diagnostic), additionally counted at x < -1,800 and x < -2,100
(the registered left boundary). *Closest approach to the left floor*: the minimum point-to-segment distance from a cell's stored (x, y) to floor line 3 (x -3,900..-2,700 at
y -1,950), over all cells and over the A2/A1 cells, with the cell. *Selection probability of the wall-top cells at the open*: the analytic probability under the
archive as materialised (before any rd3 dispatch), per cell and summed. None of them is read by the selection, the explorer, the cell key or the rule.

**I8. What "deterministic" means for rd3's tests.** (a) Pure tests use keyed sha256 streams and fixed data. (b) Every session-level test runs the real session engine
(`Session`, `Session3`, the archive, the claims, the verification, the close checks, the rule) against the synthetic stub world through an **in-process lock-step worker
pool and a virtual clock**: jobs complete in dispatch order, time advances only with the engine's polls, so a run is a pure function of its configuration (tested: two runs
agree on every ledger event, cell key, word and decision; only the stub's per-process `host_frame` offset differs, and nothing depends on it). (c) The tests that need real
processes (the fake game behind the real lifecycle code) assert only facts that hold under every schedule (the outcome is any registered one but INVALID; the integrity
checks hold; every launched process read the frozen configuration; none survives) and never assert that a particular milestone, candidate or replay occurred; an INCOMPLETE is
accepted there only for a cap or lifecycle limit of the registered kinds. (d) No assertion depends on wall-clock duration except as a very generous upper bound. (e) A few tests are
**gates**, not hermetic tests: they assert facts of the repository (`git` state, the closed real trees `runs/m8_rd/` and `runs/m8_rd_rd2/`, their D: increments, the executable); these
facts are fixed once the trees are closed, so such a test can fail when the state changes but cannot flake; they are required (never silently skipped). (f) The verification runs its
claim replays on a thread pool while the identity replays run on the main thread, both charging one replay-tick counter: a result could depend on the interleaving only if the
cap were nearly binding, which no suite test other than the replay-cap test approaches (that test removes the identity replays). No suite test reads the live
`BattleShip.cfg.json` (the preflight does).

**I9. The preflight.** It runs rd3's unit suite (which includes the explicit lists of the deterministic pure tests of rd1 and rd2, section 3) and the three rule
self-tests, then the same checks as rd2's preflight (tracked tree, executable and runtime pins, controller CVars, status table, the pinned P1 traces, the open protocol R1-R5 at both
levels, D: coverage, process check, readiness, the source snapshot and the approval). It does **not** run rd1's or rd2's whole suites: they contain asynchronous tests
(rd2's `cmd_run_with_fake_game` is the known flaky one).

**I10. Identity samples.** The open sample (K = 16) and the close sample are rd2's designs with the rd3 keys: open = the shortest cell of each of the top three levels, the four
highest-weight v2-eligible cells at the open, four keyed-random cells among the launch-capable and the A2-at-y>=0 cells, five keyed-random v2-eligible cells, topped up from the
keyed v2-eligible cells; close = the milestone cells first (wall-top, left-of-wall, left-target-broken), the shortest cell of each of the top three levels, then keyed-random
cells.

**I11. Verification.** One pass over the candidate pools of the session (the maximum-targets candidate first, then each unsatisfied milestone's pool in discovery order, three
replays at a time, 400,000 ticks / 6 min), every candidate counted; `m` counts only qualifying events in bursts ingested during rd3 (rd1 and rd2 hold none above the wall-top
landing; the wall-top landing itself is not claimed, I15). A cap that leaves a candidate unverified that could raise `m` or reach `t >= 8` is INCOMPLETE.

**I12. Order of the approval and the snapshot.** The approval record names the source snapshot's digest, so (as in rd2) the snapshot is taken first and the approval is written
from the freshly printed template right after it; the preflight then checks both. Both are fresh: the identities in the approval are computed at that moment.

**I13. The write guard** (an audit hook in the session process and in every worker) records any write-type event under `runs/m8_rd/` **or** `runs/m8_rd_rd2/` as a provenance
violation, which is INVALID.

**I14. The session clock** starts when the session object is created and counts the worker start-up; the caps sum to exactly the 60-minute hard cap (4 + 50 + 6 minutes), as in rd2.

**I15. The wall-top label is not claimed (found in review, before any native tick).** The frozen claims engine (`rl/m8_rd_claims.py`, rd1's) registers an `l0` candidate from a burst's first
grounded tick on floor line 0 and, in the verification, requires the replay's FIRST line-0 tick over the WHOLE trajectory (prefix included) to equal that claim. rd2's archive now holds two
wall-top cells (ids 18318 and 18767, both grounded on line 0 at the end of their prefix). A burst that starts from either (or from any descendant that stood on the ledge) is on
line 0 at its first tick: the engine would create an `l0` candidate whose replay finds the earlier prefix tick, call it inexact and stop the session as INVALID, a false integrity failure
(the analytic probability of such a dispatch is 0.068 % per dispatch, about 2.7 expected in 4,000, so it is likely). rd3 therefore (a) removes the `l0` label from a job's result before it is
committed (`m8_rd3_run.suppress_wall_top_label`, applied in `Session3.commit`; the archive ingestion is untouched), (b) records every sighting in `wall_top_sightings.jsonl` and in `arm_T.json`
(burst, whether the start cell was a wall-top cell, whether it was the burst's first tick), (c) never saves a wall-top route and counts no wall-top level in `m`. This changes no registered
quantity: the rule already excludes the wall-top landing from PROGRESS; it only prevents the engine from turning a repeat of rd2's landing into an INVALID. Tested with a real session in which
the first rd3 burst is made to look like a continuation (the same session without the fix is INVALID) and with the frozen engine's own check on a hand-made trace.

## 3. Known issue: rd2's flaky test (recorded, not edited)

`rl/m8_rd2_tests.py::unit_cmd_run_with_fake_game` asserts that at least one verification replay occurred ("the verification replays ran with the four diagnostics") in a
3,000-tick asynchronous synthetic session. Whether a candidate appears in so short a run depends on the scheduling of the worker processes, so the assertion fails
occasionally; it failed once during rd2's first launch attempt (the preflight refused, nothing was created) and passed in every later run. It is a test flaw, not a code
defect. rd2's files are frozen (the rd2 approval covers them), so it is not changed; rd3 does not run rd2's suite as a whole.

rd3's replacements and the lists:

- **rd3 versions.** The fake-game `cmd_run` test of rd3 asserts no milestone and no replay; the four-diagnostics flag set is checked by a *direct* replay of a constructed
  candidate through the real replay path (`build_real_env3(...).replay`), which does not depend on exploration.
- **Deterministic pure tests of rd2 run inside rd3's suite** (each is a pure function of keyed data or reads the closed real trees): `select2_contract`, `bound_rule`,
  `descent_tree_vs_reference`, `descent_doom_semantics`, `archive2_mode1_equals_v1`, `select2_probabilities`, `replacement_v2`, `ledger_rebuild_v2`, `begin_v2_and_persistence`,
  `overlay`, `iterate2_equals_iterate`, `write_guard`, `rule2_module`, `report_on_rd1_reference`, `open_overlay_on_rd1_reference`, `budget_projection`, `identity_samples`.
- **Deterministic pure tests of rd1** are listed in `rl/m8_rd3_tests.py` (`RD1_PURE`) after being classified one by one (no thread, process, sleep or wall-clock dependence).

## 4. Launch conditions

The prompt's Part B conditions are evaluated at the end of the preparation in `docs/rl_m8_rd3_implementation.md`, section 11, and again in the report.
