# M8-rd1 amendment 1: budget matching by comparison point (2026-10-02)

**Status.** A user-authorised amendment to revision 2 of `docs/rl_m8_rd_proposal_2026-10-01.md`, recorded **before any native tick**
of M8-rd1 and implemented in the new `rl/m8_rd_*.py` files. The proposal is committed and frozen at revision 2; this document and
the implementation record `docs/rl_m8_rd_implementation.md` are new files. Nothing in the proposal was edited.

The amendment replaces one sentence of decision 5 (budget matching). Everything else in revision 2 and in its section 14 stands.

## 1. Decision 5, as amended

| item | revision 2 | amendment 1 |
| --- | --- | --- |
| budget of each arm | **exactly** 3,000,000 native ticks | **capped** at 3,000,000 native ticks, with a **minimum of 1,500,000** for a valid comparison |
| what the arms are compared at | each at its own 3,000,000 | **T = the cumulative native tick count reached by the slower arm** |
| milestones of the faster arm | all of them | count **only if they occurred within its first T cumulative ticks** |
| an arm below the minimum | INCOMPLETE (it missed the exact budget) | **either arm below 1,500,000 native ticks makes the session INCOMPLETE** |
| treatment arm's wall cap | 26 min | **kept: 26 min** |
| session hard cap | 60 min from P1 | **kept: 60 min from P1** |

The control arm's own wall cap (24 min), the P1 and verification caps, the memory and process caps, the cell key, the explorer,
the selection, the rule's outcome table and the +2 target margin are unchanged. "T" in this document is the **comparison point**;
the two arms keep their names, arm T (treatment) and arm C (control).

## 2. How it is implemented

**The cap, in a parallel run.** The cumulative tick count of an arm is the sum of the ticks of its committed jobs. A job is an
archive iteration (arm T) or a control episode (arm C). Jobs finish in completion order and are committed in that order; the
cumulative position of an event at absolute tick `j` of a job is `cum_before + j`. To make the cap exact with five concurrent jobs,
each job is given a tick **allowance** when it is dispatched, `remaining = cap - committed - (allowances of the jobs in flight)`,
and a job that gets less than it wants is **cut there**, inside its prefix or inside its burst; only the ticks inside the allowance
exist. Nothing can overshoot, and an arm that is not stopped by its wall cap commits exactly 3,000,000 ticks.

**The comparison point.** After both arms, `T = min(ticks of arm T, ticks of arm C)` (`rl/m8_rd_rule.comparison_point`). If either
arm is below 1,500,000 ticks the session's rule record carries an INCOMPLETE reason for it (the check is `<`, so exactly
1,500,000 is valid). Both arms' reported readings are given in full and within T.

**The truncation.** Every candidate trajectory of an arm is stored with its job's `cum_before` and the absolute tick `event_j` of its
earliest qualifying event. Inside the comparison point means `cum_before + event_j <= T`. A job that straddles T is **cut at
`T - cum_before` words**: the replay that verifies it covers only those words, so a milestone that would complete after T does not
count (`rl/m8_rd_claims.ArmLedger.counted_len`). The maximum number of targets broken, t, is taken the same way: for each number of
targets, only the strictly shorter trajectories that first reached it are kept in discovery order, and the t of an arm within T is
the highest level with a record whose event lies within T, replayed on its shortest such trajectory. A candidate beyond T is never
replayed.

**A job aborted at a wall cap is not committed.** At an arm's wall cap no new job is dispatched; jobs in flight get a 20 s grace to
finish and are then aborted. An aborted job's ticks were consumed natively but its results never enter the archive or the candidate
set, so they do not count toward the arm's tick count or toward T. This is the one convention the amendment leaves implicit; it
only matters when a wall cap binds, and the discarded count is recorded (`aborted_jobs` in the arm record).

## 3. Tests of the amended rule

`rl/m8_rd_rule.py self-test` covers the comparison point (the slower arm; 1,499,999 incomplete; 1,500,000 valid; both arms
named when both are below), disjointness and exhaustiveness of the outcome table over every `(m, t)` combination, and the
precedence INVALID, INCOMPLETE, then PASS / NULL / INCONCLUSIVE. `rl/m8_rd_tests.py` tests the truncation explicitly:
`claims_ledger_rules` (strictly shorter t records, `within`, `counted_len` at and around a job boundary, a job straddling T),
`session_truncation_at_the_slower_arm` (arms capped at 9,000 and 4,000 ticks: the comparison point is 4,000, no replayed candidate
lies beyond it, the verified t equals the online t within T), `session_budget_exact_cut` (a cap of 7,777 is committed exactly, with
cut jobs) and the production-count synthetic end-to-end run (3,000,000 and 2,700,000 ticks: comparison point 2,700,000).

## 4. What this amendment does not change

The scope label, the milestone ladder, the five outcomes, the integrity checks of section 7.3, the claim verification of section 7.4
(a replay is exact only if the native action digest, every consumed tick, the break table, the claimed event tick and the
re-derived predicate agree; an inexact replay is INVALID), the frozen runtime configuration, the D: evidence rules and every absolute
constraint of the project guide (no native RNG inspection, logging, control, comparison or hashing; process restart resets the
episode; the exact submit / consume / input-tick contract; canonical controller words as replay truth with no hidden actions;
agent-generated prefixes only; the crossing fixtures and the TAS validation-only; no hardcoded routes; the non-PORT decomp
behaviour preserved).
