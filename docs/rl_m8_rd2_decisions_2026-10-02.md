# M8-rd2: the user's answers to the continuation proposal's open questions, and how they were applied (2026-10-02)

**Status.** Recorded **before any native tick** of M8-rd2, at the start of the unattended preparation that implements the proposal
as decided. The proposal (`docs/rl_m8_rd_continuation_proposal_2026-10-02.md`) is committed and frozen; nothing in it, in any rd1
file or in `runs/m8_rd/` was edited. This file, the implementation record `docs/rl_m8_rd2_implementation.md` and the new
`rl/m8_rd_select2.py`, `rl/m8_rd_resume.py`, `rl/m8_rd2_*.py` files are the additions.

**Scope label**, carried by every rd2 record: *continuation of archive `m8_rd_a1` under `m8_rd_select_v2`; one session, one set of keyed
draws; no control arm; not a policy result, not a learning result, not a comparison of v2 with v1.*

## 1. The answers (the user's words, abridged) and where each is applied

| # | question of the proposal, section 10 | answer | applied in |
| ---: | --- | --- | --- |
| 1 | v2 as specified, or the constant-free M1 | **Full `m8_rd_select_v2`, including the recovery bound** | `rl/m8_rd_select2.py` (E6, `bound_unrecoverable`, the Mario constants), contract digest |
| 2 | replacement under v2 doom or v1's | **Replacement uses the v2 doom** | `Archive2._decide_v2`, `doom_v2`, `_doom_new` |
| 3 | the one-target exception X1 | **Include it** | `Archive2.eligible`, `doom_v2`, `_doom_new` (a cell with exactly one live target is exempt from E4-E6, in eligibility and in replacement) |
| 4 | directory | **rd2 writes only to the sibling `runs/m8_rd_rd2/`, which must fall under D: backup coverage** | `rl/m8_rd_resume.materialise`, `RD2_ROOT`; the write guard; the D: increment `<date>_incr_m8_rd2` of `runs/m8_rd_rd2/` (Part C) |
| 5 | new burst fields | **Add `ground_runs` and `res_transitions`. Diagnostics only; they change no behaviour** | `rl/m8_rd2_worker.py` (`iterate2`), `Burst2` (see interpretation I1: this answer decides a conflict with the proposal's 2.5) |
| 6 | dilution thresholds and the rd3 requirement | **Accept: below-floor share <= 10.5 %, fatal-return share <= 11.0 %; rd3 requires launch-capable cells per 1,000 returns strictly above rd1's value** | `rl/m8_rd2_rule.py` (`BELOW_FLOOR_MAX_PER_MILLE = 105`, `FATAL_MAX_PER_MILLE = 110`, `launch_above_rd1`) |
| 7 | budget | **Accept: exploration 50 min or 6,000,000 ticks, valid from 2,000,000; open phase 70,000 ticks / 4 min; verification 400,000 ticks / 6 min; 60-minute hard cap; memory caps as in rd1** | `rl/m8_rd2_session.run_config`, `caps()`; the approval record |
| 8 | explorer and burst length | **Unchanged** | `m8_rd_explore` (rd1's module, unchanged), `burst_words = 120` |
| 9 | draw keys | **A v2-specific draw-key prefix, with iterations continuing at 2,175** | `Archive2.draw_id`, `DRAW_SUFFIX` (interpretation I2) |
| 10 | tornado term | **Accept the tornado-unspent assumption** (it makes the bound more permissive) | `RISE_TORNADO` in `rl/m8_rd_select2.py`; the contract digest records it |
| 11 | sequencing | **Preparation and run are combined in this session under the launch conditions of the prompt** | Part B of the prompt; `docs/rl_m8_rd2_implementation.md` section 9 |

Constraints that stay as they were (unchanged in code and checked by tests): no native RNG seed inspection, logging, control, comparison
or hashing (every draw is a Python-side keyed sha256 uniform); process restart resets the episode; the exact submit / consume /
input-tick contract; canonical controller words are the replay truth with no hidden actions; prefixes are agent-generated only; human
crossing recordings, the fixtures and the TAS are validation-only and never read; no hardcoded route or waypoint; the non-PORT decomp
and byte-matching behaviour is preserved (no native, decomp or submodule change; the existing executable is used).

## 2. Interpretations the implementation needed (none changes a registered quantity)

The proposal and the answers fix every rule, constant, threshold, budget and cap. The items below are the mechanical readings the code
needed. Each can be overruled; none alters a registered definition, threshold, budget, cap, the cell key, the explorer, or the rule's
outcome table.

**I1. Answer 5 against the proposal's section 2.5 (the one conflict, resolved in favour of the answer).** Section 2.5 says rd2 bursts store
their exact ground runs "so that descent doom is exact for rd2 bursts" and lists the fields as part of v2. The answer says the new fields
"are diagnostics only and change no behaviour". The two cannot both hold, so the later and more specific text (the answer) governs:
**the grounded evidence of descent doom (E5) is the grounded REACHES of a burst for every burst, rd1's and rd2's alike** (the reading
the proposal's own estimates and the overlay figures use). `ground_runs` and `res_transitions` feed only diagnostics: the up-B start heights,
the exact fatal-return reading, `BOUND_VIOLATION`, and a shadow reading that counts, without applying, how many cells' descent flags would
differ under exact evidence (`exact_ground_evidence_shadow` in the report). The effect is confined to a rare case (a re-landing on a key
already visited in the same burst) and runs in the conservative direction (a recovery may be under-reported, so a cell may be excluded
that exact evidence would keep). The shadow reading lets a later session judge whether to change it, under a new label.

**I2. The v2 draw key.** The archive id stays `m8_rd_a1`. The draw id is `m8_rd_a1_v2`: selection draws use
`m8_rd|m8_rd_a1_v2|select|<iteration>`, exploration draws `m8_rd|m8_rd_a1_v2|explore|<iteration>|<decision index>` (the unchanged rd1
explorer, given the v2 id), iterations 2,175 onwards. Open identity keys: `m8_rd|m8_rd_a1|identity_open|rd2|<cell id>`; close:
`m8_rd|m8_rd_a1|identity_close|rd2|<cell id>`.

**I3. A fourth element in the reach rows of rd2 bursts.** rd2 reach rows are `[tick, cell id, action, bound bit]`; rd1's keep three
elements, so rd1's rows stay byte-identical. The bound bit is the new reach's recovery-bound flag, kept so that the ledger rebuild can
re-derive every KEEP decision (the end record of a kept reach is not stored). It is an audit field; nothing reads it for selection.

**I4. Replacement at the time of a reach.** The incumbent's doom is evaluated against the archive as it stood BEFORE the burst was added
to the tree; the new reach's doom is E4 (the 60-tick window), E5 from its own burst only (a burst that ended by length is pending) and
E6 from its own end record, with the X1 exemption on both sides. The stored `doomed` field keeps its v1 meaning (E4).

**I5. Counters are per session.** `cum_before`, `first_cum` and the ticks recorded in the ledger count from the start of the session
that wrote them; the burst's `session` field and a cell's `first_iter` (>= 2,175 for rd2) disambiguate.

**I6. The launch-capable measure.** "Launch-capable cells created per 1,000 returns" = cells with id >= the first rd2 cell id that are A2
or A1 with y >= 1,639 in the closed archive, divided by rd2's returns (ingested jobs). rd1's value is 14 / 2,175 per 1,000 = 6.4368 (the
proposal's "6.4" is its rounding). Comparisons use integer arithmetic: strictly above means cells x 2,175 > 14 x returns.

**I7. The dilution counts.** Below-floor share = rd2 dispatches whose start cell's stored position at dispatch has y < -2,850, over all rd2
dispatch events (a dispatch whose job was aborted at the wall cap counts). Fatal-return share = rd2 returns whose burst ended in a native
fall with no grounded live tick (the exact ground runs; the reach reading is reported beside it), over all rd2 returns. Thresholds are
compared by integer arithmetic.

**I8. Stop conditions.** S4 and S6 are evaluated on the exact outcome label (NO_MILESTONE/DILUTION_PERSISTS; NO_MILESTONE/DILUTION_REDUCED
with the rd3 requirement not met). S1 and S2 are informational statuses. S3 uses the median length of the v2-eligible cells of the top
level at the close. The dilution verdict is reported with every outcome and decides only the stop path.

**I9. The open identity sample.** K = 16: the shortest cell of each of the top three levels (among all cells, as rd1's close sample did);
the four highest-weight v2-eligible cells at the open (cell 0, covered by P1, excluded); four keyed-random cells among the launch-capable
and the A2-at-y>=0 cells; five keyed-random v2-eligible cells; topped up from the keyed v2-eligible cells if a pool is short.
The close sample is the milestone cells first, the shortest cell of each of the top three levels, then keyed-random cells.

**I10. P1 against the archive.** Both tick-0 processes (the first and the second, standby-promoted) are compared with the archive's
`pin_tick0` in every field but `host_frame` (reported). The two pinned Track 1 traces and the scratch-archive return self-test, including the
refused corrupted end record, are rd1's, unchanged.

**I11. The order of the close.** After the session clock: the final atomic checkpoint, the ledger audit (rd1's part under v1, rd2's part
under v2, derived flags equal to the first-principles recomputation), the prefix property, rd1's immutability (R1 again) and the write-guard
record; any failure is INVALID. Only then is the rule applied.

**I12. Phases.** P1 and the 16 open identity replays share the open phase (70,000 ticks, 4 min, wall cap key `p1`). S0 (R0-R6) and the S2
close checks run outside the session clock, as in rd1. The exploration reuses rd1's arm machinery under the name arm T (tick allowance
reserved at dispatch, exact cut at the cap, 20 s grace at the wall cap, aborted jobs not committed, a checkpoint every 5 min): files are
`arm_T.json`, `iterations_T.jsonl`, `routes/T_*`.

**I13. The frozen runtime is rd1's, read in place.** Workers install `runs/m8_rd/archive/runtime/{BattleShip.cfg.json, imgui.ini}` (hashed
against the archive's pins before every launch) and never read the live configuration; rd2 holds no copy. The write guard (an audit hook in
the session process and in every worker) records any write-type event under `runs/m8_rd/` as a provenance violation, which is INVALID.

**I14. Verification.** One pass over the candidate pools of the session (the maximum-targets candidate first, then each unsatisfied
milestone's pool in discovery order, three replays at a time, 400,000 ticks / 6 min), every candidate counted (there is no comparison
point). `m` counts only qualifying events in bursts ingested during rd2 (rd1 holds none). A cap that leaves a candidate unverified that
could raise `m` is INCOMPLETE. The identity replays at the close share the replay cap.

**I15. Approval and snapshot order.** The approval record names the source snapshot's digest, so the snapshot is taken first (it does not
depend on the approval) and the approval is written from the freshly printed template right after it; the preflight then checks both.

**I16. Preflight.** It runs rd1's 48-test suite (which must still pass), rd2's suite and both rule self-tests, the open protocol R1-R5, the
tracked-tree and git checks, the pins, D: coverage, readiness and the approval; it refuses solely for the missing approval when everything
else holds.

**I17. Lifecycle failures at the open.** A process death or timeout during P1 or the 16 open identity replays is not redrawn: the proposal's
INCOMPLETE condition "the open phase not completed" applies (rd1's P1 behaved the same way). Only the exploration redraws lifecycle failures,
up to three. (rd1 saw none in about 2,200 launches.)

**I18. The session clock.** It starts when the session object is created, as rd1's did, so the worker start-up counts toward the 60-minute
hard cap; the registered caps sum to exactly that cap (4 + 50 + 6 minutes), the open and verification phases are expected to use far less than
their caps, and the expected timeline leaves about five minutes of headroom.

## 3. The launch conditions as they apply (the prompt's Part B)

Condition 7 asks whether a design decision had to be made that the proposal and the answers leave open. **None did.** Every rule,
constant, threshold, budget and cap is registered; the items in section 2 are mechanical readings. I1 is the one place where two texts
disagree; the answer is explicit, so it governs, and the effect is measured rather than assumed (the shadow reading).
