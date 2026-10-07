# M9-g3: the user's decisions for the third robustification gate (session s1), and how they were applied (2026-10-06)

**Status.** Recorded **before any native tick** of M9-g3, at the start of an unattended session whose Part A is zero-tick preparation, whose Part B is the
launch conditions and whose Part C (one M9-g3-s1 training session) runs only if every Part B condition holds. Nothing in the frozen proposals, in any M8,
M9-g1, M9-g1-evaluation or M9-g2 file, in `runs/m8_rd*/`, `runs/m9_g1/`, `runs/m9_g1_eval/`, `runs/m9_g2/`, in `replay/`, in the external guide or in any
tracked file was edited, with ONE exception, decision 9 (two lines of the tracked `rl/m9_eval_tests.py`, recorded in section 4 with its diff and digests).
The additions are this file, `docs/rl_m9_g3_implementation.md`, the new `rl/m9_g3_*.py` files, the preparation tools under `logs/m9_g3_prep/` (Git-ignored)
and, in Part C, the approval, the run tree `runs/m9_g3/s1/` and the results record.

**Scope label**, carried by every M9-g3 record (`rl/m9_g3_contract.SCOPE`): *M9-g3-s1: backward-algorithm robustification under the replenishing controlled
frontier rule `m9_g3_frontier_v1` (PPO from prefix-replayed start states on the agent's own two verified rd4 clears, sticky actions p = 0.25, observation
btt_policy_obs_v3_entities, reward btt_reward_v2, entropy coefficient 0.01; the g2 trigger, frozen strip test and re-checks unchanged; attempts spaced by
20 x 2^(f-1) counted strip outcomes, cap 320, no HELD and no STALLED); the first session of a new resumable line (not an amendment of g2); a fresh policy
(seed 0); one set of keyed draws; progress measured as the sustained frontier depth D and the reliable reach R at landing states against g2-s1's pinned tape
baseline reused by digest, under the registered rules; no claim of a tick-0 policy.*

This session implements section 3 of `docs/rl_m9_g2_stop_review_2026-10-06.md` as decided below. The g2 records (`docs/rl_m9_g2_*`) and the stop review are
the evidence the design rests on; nothing in them is re-decided. g2-s1's registered outcome (NULL, END_NULL_S1) stands.

## 1. The decisions (the user's words, abridged) and where each is applied

| # | decision | applied in |
| ---: | --- | --- |
| 1 | **g3 is a new line, not an amendment of g2** | `rl/m9_g3_contract.py` (`GATE = m9_g3`, `LINE_ID = m9_g3_line`, its own contract, line contract, frontier, s1 and line rule identities and digests); the run tree `runs/m9_g3/s<k>/`; `runs/m9_g2/s1` is a seventh protected read-only tree (`rl/m9_g3_session.TREES`); a g2 carried state is refused by the g3 frontier and by the resume check (`rl/m9_g3_frontier.Frontier._restore`, `rl/m9_g3_run.G3Session.open`) |
| 2 | **The one change: attempts replenish with training progress.** After f consecutive failures the next attempt waits 20 x 2^(f-1) counted strip outcomes, capped at 320; no HELD and no STALLED; the frontier never freezes on attempt counts. Everything else as g2: the 8-of-20 trigger; the frozen strip test of 20 sticky episodes passing at 10 with early stopping; a re-check of every previously passed landing on every attempt; a move only if all pass; a failed re-check only blocks; training pauses during tests | `rl/m9_g3_contract.py` (`SPACING_UNIT = 20`, `SPACING_CAP = 320`, `spacing_need(f)`; the trigger and test constants READ from g2); `rl/m9_g3_frontier.py` (`Frontier.record`: a trigger inside the spacing is `deferred_trigger`, the window restarts, no attempt; `begin_attempt` refuses inside the spacing; `finish_attempt`: a failed attempt raises f and resets the outcome counter, a move resets both, INTERRUPTED changes neither; `held()` is always False; no STALLED; `replay_history` names an attempt inside its spacing); `rl/m9_g3_probe.run_attempt` (g2's attempt under the g3 frontier); `rl/m9_g3_train.py` (g2's callback: the attempt hook at the rollout boundary) |
| 3 | **A fresh policy (seed 0) for g3-s1.** Everything else unchanged from g2: observation v3, reward v2, entropy 0.01, sticky actions 0.25, routes as start states only, the two verified rd4 clears, the final-claim definition, horizon bootstrapping as inherited, fixed 4 + 6 slots | `rl/m9_g3_contract.PPO = rl/m9_g2_contract.PPO` (= g1's, ent_coef 0.01, seed 0, fresh); `rl/m9_g3_train.make_fresh_ppo = rl/m9_g2_train.make_fresh_ppo` (= `rl/m9_train.make_ppo`); the g1 and g2 modules for the observation pipeline, the reward, the staging, the lineages, the sticky rule, the arena, the policy snapshots and the claim definition are imported unchanged; `SPLIT = (4, 6)` read from g2 |
| 4 | **Line budget, progress-only.** D <= 2,128 by s2, D <= 1,966 by s4, D <= 1,694 by s6; success at D <= 1,473; cap of 8 sessions; the line does NOT end on a NULL s1 and does NOT end on attempt counts; only the milestone deadlines and the cap end it; every line-ending condition stated explicitly | `rl/m9_g3_contract.py` (`LINE_BUDGET = {2: 2128, 4: 1966, 6: 1694}`, `LINE_SUCCESS_DEPTH = 1473`, `LINE_CAP_SESSIONS = 8`, `LINE_PROGRESS_FROM_SESSION = 4`); `rl/m9_g3_rule.apply_line` (`m9_g3_line_rule_v1`); section 2 below states every line-ending condition |
| 5 | **g3-s1 rule:** its own registered PASS / NULL / INCONCLUSIVE / INCOMPLETE / INVALID as the stop review specifies; its outcome informs but never ends the line by itself | `rl/m9_g3_rule.apply_s1` (`m9_g3_s1_rule_v1`: g2's logic under the g3 identity; INVALID includes "an attempt inside its spacing" and "a pointer move without a recorded passing attempt"; INCOMPLETE's valid ends are the wall, tick and transition caps only); the self-test asserts that a NULL s1 continues the line |
| 6 | **Session envelope:** 80 minutes of training under a 145-minute hard cap; model, optimizer and frontier state saved at the close with pinned digests, for a later separately authorised s2 | `rl/m9_g3_contract` (`WALL_CAPS_S`, `TICK_CAPS`, `GLOBAL_CAP_S = 8700`); `rl/m9_g3_train.save_checkpoint` (model.zip with `policy.optimizer.pth`, `curriculum_state.json` carrying the spacing state, `checkpoint.json` pins); `rl/m9_g2_resume.py` (reused unchanged: the final-state record, the continuity assertions, the refusals); `session/final_state.json` |
| 7 | **Tape baseline:** reuse g2-s1's pinned table by digest (`81fa52c2...`), verified at the open together with the executable and asset pins; if any pin differs, stop. Bars as in g2: max(10, ceil(20 p_hat) + 5) | `rl/m9_g3_contract.TAPE_REUSE` (source path, file sha256 `81fa52c21078b2c2...`, content digest `d915fab920554774...`, the executable it was measured with `30a3913b...`, the key counts 200 / 40); `rl/m9_g3_run.G3Session._reuse_tape` (copied into `input/`, both digests, every landing pinned, the key counts, the label family, the lineage, sticky p, the executable pin: any difference is INVALID at the open with nothing trained); the preflight's `tape_reuse_problems`; the bars `B` are read from the table (`rl/m9_g2_tape.bars`, unchanged); T0 is not re-measured (reading R3 below) |
| 8 | **Additional readings, reported only:** the trigger-to-test gap for every attempt, the attempt yield, the replenishment schedule as it ran | `rl/m9_g3_report.full_report` (`trigger_to_test_gap`: the window's displayed rate, the live rate over the preceding 60 counted strip outcomes at that pointer, the frozen test's rate, the strip calibration gap; `attempt_yield`: moves per decided attempt, per pointer; `replenishment_schedule`: per attempt f, need, have, result; `deferred_triggers`; `pointer_over_time`; `throughput_by_pointer`; `per_landing_against_tape`); no rule branch reads them |
| 9 | **AUTHORISED EDIT:** the stop review's option a (fragment assembly) on the two guard lines of the tracked `rl/m9_eval_tests.py`, exactly as the g2 tests already do, changing nothing else; then the g1 unit suite, the g1 evaluation suite and the g2 suite must all pass; the diff recorded here | section 4 (the diff, the digests before `05c6765f...` and after `7151c34b...`); `rl/m9_g3_session.AUTHORISED_TRACKED_EDITS` pins the post-edit digest, and the g3 preflight tolerates exactly that modified tracked file at exactly that digest; the suite results are in the implementation record and the session report |
| 10 | **Replay verification as in g2:** training-time tests may spot-check one clear per passed test; every clear counted in a registered measure is fully replayed exactly | `rl/m9_g3_run.G3Session.verify` (= g2's tiers: 0 = every close-audit sticky clear at an audited landing; 1 = the first 20 training clears; 2 = one keyed clear per passed test, on the g3 pick key; 3 = the diagnostics); the reused tape's clears were replayed in g2-s1 (100 of 100) and are not re-replayed; the rule counts only verified clears |
| 11 | **Artifact metadata:** every artifact records the top-level task block and `created_utc` at the source; the writer refuses to write without them | every write goes through `rl/m9_artifacts.py` (imported unchanged; the refusal is tested again in `rl/m9_g3_tests.py`); the close audit and `verify-run` audit the whole tree |
| 12 | **Every checkpoint, optimizer state, frontier state and training log is evidence.** Pin their digests; place them under D: backup coverage | `runs/m9_g3/s1/training/checkpoints/*/checkpoint.json` pins model.zip, its `policy.pth` and `policy.optimizer.pth` members and `curriculum_state.json`; `session/final_state.json` pins the saved state for s2; the whole tree is Git-ignored under `runs/` and is backed up as the increment `incr_m9_g3_s1` by the unchanged `rl/tools/runs_backup.py` |

Constraints that stay as they were (unchanged in code, checked by tests): no native RNG seed inspection, logging, control, comparison or hashing (every draw is a
Python-side keyed sha256 uniform of the `m9|g3|...` family, except the audit's sticky labels, which keep the reused tape's `m9|g2|reach|...` family for
pairing, reading R2); process restart resets the episode (one fresh process per episode, prefix included; probe, drift and audit episodes too; a process is
never reused; pausing training parks processes at `WaitingForAction`, nothing is reset in-process, there is no save state); the exact submit / consume /
input-tick contract (prefix word i consumes tick i, the policy's first word consumes tick tau, a parked process consumes nothing until its next word);
canonical controller words are the replay truth (the SUBMITTED word is the recorded word; sampled words, sticky masks and action draws are metadata); the
routes used are the agent's own; human crossing recordings, the crossing fixtures and the TAS are validation-only and never read (the static source guard of
`rl/m9_g3_tests.py` refuses any reference, and g1's guard scans the g3 files too); no hardcoded route or waypoint (the landing states are computed from the
trunk's own grounded segments; they decide only when the start window moves, never where the agent goes, and never enter reward, observation or action);
non-PORT decomp and byte-matching behaviour is preserved (no native, decomp or submodule change; the existing executable `30a3913b...` with its existing
read-only diagnostics); no commit, push, branch or pull request; no application is closed; the M8 trees, `runs/m9_g1/`, `runs/m9_g1_eval/` and
`runs/m9_g2/s1` are only read and must stay byte-identical to their D: increments.

## 2. Every line-ending condition, explicitly (decision 4)

`m9_g3_line_rule_v1` is checked at every session close, in this order; the first condition that holds is the line outcome. k counts the sessions whose
training reached at least 50 % of the wall cap (an INCOMPLETE session below that does not count toward k); D_k is the sustained frontier depth of the k-th
counted session.

| outcome | condition | ends the line? |
| --- | --- | --- |
| SUSPENDED | the session is INVALID; or two consecutive sessions are INCOMPLETE | a review; no next session until repaired and re-approved |
| END_SUCCESS | D_k <= 1,473 ("crossing learned") | yes; the right side and the claim need a separate proposal |
| END_BUDGET_2128 | k = 2 and D_2 = none | yes |
| END_BUDGET_1966 | k = 4 and D_4 later than 1,966 (none, or 2,128) | yes |
| END_BUDGET_1694 | k = 6 and D_6 later than 1,694 | yes |
| END_NO_PROGRESS | k >= 4 and D_k not earlier than D_{k-2} | yes |
| END_CAP | k = 8 without END_SUCCESS | yes |
| CONTINUE | otherwise | no; session k + 1 is proposable with its own approval |

What can never end the line: a NULL s1 (k = 1 is CONTINUE whatever s1's outcome); any attempt count at any pointer; a HELD or STALLED state (neither
exists in g3); a last session that does not count toward k (the line stays where the previous counted session left it, CONTINUE, unless SUSPENDED).
`rl/m9_g3_rule.apply_line` reads no attempt count and no flag; its self-test feeds absurd attempt counts and HELD / STALLED flags and asserts CONTINUE.

## 3. Mechanical readings the implementation needed (none changes a registered measure, threshold, rule, schedule or training setting)

The stop review and the decisions fix every rule, constant, cap and threshold. The items below are the readings the code needed where the text leaves a
mechanical detail unstated. Each can be overruled; none alters a registered definition. They are written down so that Part B condition 6 can be judged.

**R1. The spacing counter.** "Counted strip outcomes since the last failed attempt" counts every completed training episode whose start was drawn from the
strip under the current pointer (a native end or the horizon; stale and non-strip outcomes never count, as g2's R2), from the moment the failed attempt is
recorded. Outcomes that complete between a trigger and its attempt (`after_trigger`, g2's R2) count: they are practice at the strip. The counter resets to
0 on a failed attempt and on a move; an INTERRUPTED attempt leaves it unchanged. f is the number of failed attempts at the current pointer over the line,
which equals the consecutive failures since the last move because the pointer never returns to a pointer it left; the line attempt index a stays f + 1
(g2's R1), so the probe keys never repeat across sessions. The trigger window restarts at the session open, after every move, after every attempt and after
every deferred trigger (g2's R2 plus the deferral: a window that fired inside the spacing has served its purpose).

**R2. Keys.** Every g3 draw is a Python-side sha256 uniform on a key of the `m9|g3|...` family: training `m9|g3|train|<episode>`; starts
`m9|g3|start|<episode>|region`, `|tau`, `|lineage`; probes `m9|g3|probe|<pointer>|<a>|<part>|<k>` and their starts `|tau`, `|lineage`; probe actions
`m9|g3|probeact|...`; the audit's action draws `m9|g3|auditact|<mode>|<landing>|<k>|<tick>|<stick or button>`; tick 0 `m9|g3|tick0|<k>`; the verification pick
`m9|g3|verifypick|<pointer>|<a>|<part>`; the artifact sample `m9|g3|artifact|<episode>`. ONE registered exception: the close audit's sticky labels keep the
reused tape's family `m9|g2|reach|<landing>|<k>` (k = 0..19), because the reused tape's episode k at a landing was perturbed under exactly that label and the
audit episodes must stay paired with it (identical sticky draws), as g2's R1 and R8 intended within a line. P2 keeps g1's keys (an integrity check). The g1
sticky rule is applied verbatim by the g2 episode context on the g3 label.

**R3. T0 is the drift check, not a measurement.** Decision 7 reuses g2-s1's table by digest, so no tape episode is measured. The g2 design (proposal 5.3,
item 3) requires a session that reads the table by digest to re-run the first 5 keyed tape episodes at 2,128 and to require identical outcomes; g2's code
carried `drift_jobs` for it. g3 runs this drift check in the T0 phase of every session (s1 included): the 5 episodes on the reused labels must reproduce the
table's recorded outcomes (clear / fall / horizon) and, where the measuring session's T0 records are present (`runs/m9_g2/s1/t0/episodes.jsonl`, read-only),
the same native action digests. A difference is INVALID (tape drift) with nothing trained. The T0 phase caps are 240 s and 60,000 native ticks (g2's 900 s /
1,500,000 belonged to the measurement). The drift episodes' clears are integrity readings, not counted measures, and are not re-replayed.

**R4. The pins at the open.** Decision 7's "verified at the open together with the executable and asset pins": the open records the executable, the three
runtime files and the frozen configuration (as g2) and additionally refuses, as INVALID, any difference from the registered pins and any difference between
the executable now and the one the reused table was measured with. The preflight checks the same.

**R5. Reuse of the g2 modules (the stop review's preparation reading).** `rl/m9_g2_probe.run_attempt` and `rl/m9_g2_train.train` cannot take the g3 frontier
unchanged: the former builds its jobs through module-level functions on g2 keys and picks verification clears with the g2 key, the latter calls that attempt
and writes the g2 line contract into every checkpoint. Both are copied into `rl/m9_g3_probe.py` and `rl/m9_g3_train.py` with those references changed and
nothing else. Reused unchanged (imported, never edited): the probe runner (`ProbeSource`, `TestState`, `ProbeRecorder`, `ProbeRunner`), the arena and the
episode context, the frozen policy, the tape helpers (the drift jobs, the bars, the digest), the resume machinery, the session engine's P1, P2, verification,
clock and pools, the callback class (subclassed only to add the spacing state to the per-rollout row), the real hooks, the synthetic stand-ins, and every g1
module. `rl/m9_g2_contract` is imported unchanged and read for every value g3 keeps.

**R6. Resume (implemented and tested synthetically; s2 is not run and not authorised).** As g2's R14 under the g3 identities: the carried state adds
`since_failed` (R1); the open refuses a curriculum state whose frontier rule is not `m9_g3_frontier_v1` or whose line contract digest is not g3's; the drift
check (R3) runs again in every session; the session seed is 1000 + k.

**R7. Checkpoints and the curriculum state.** As g2's R7 with the g3 identities: every `curriculum_state.json` carries the g3 line contract digest, the
frontier rule id, the spacing state (f, need, have), the deferred-trigger count, the per-pointer attempt counts and the carried state; `checkpoint.json` pins
the three digests and records the spacing state. `verify-run` refuses a checkpoint that does not carry the g3 identity.

**R8. The close audit, D, R, verification, INCOMPLETE, resources, the write guard.** As g2's R8-R13 and R15, with the g3 keys (R2), the seven protected
trees (the six of g2 plus `runs/m9_g2/s1` with its increment `2026-10-06_incr_m9_g2_s1`: 9,779 files, 988,807,605 bytes, manifest `4ad2c3dc...`) and the
write guard covering every other `runs/` directory (`runs/m9_g2` included), every other g3 session tree, `rl/` and `docs/`.

**R9. The session envelope.** Phases and caps (wall, native ticks): open 60 s / 0; P1 240 s / 60,000; P2 120 s / 60,000; T0 (the drift check) 240 s / 60,000;
training 4,800 s / 20,000,000 and <= 3,072,000 transitions; close audit 1,200 s / 3,000,000; verification 600 s / 1,500,000; close 300 s / 0; session hard cap
8,700 s (145 min). The pessimistic projection (every cap binding, four pool spawns at 15 s, 20 s of grace per phase) is 7,780 s = 129.7 min, 920 s below the
cap, with no trimming. The registered valid ends of training are its wall cap, its native-tick cap and its transition cap (STALLED does not exist).

**R10. The reported readings (never deciding).** g2's R16 set (the pointer trace, every attempt with its trigger window, snapshot digest, strip result and
re-checks, FRONTIER_BACKED, R_unperturbed, the deterministic and tick-0 results, entropy and explained variance per rollout, the snapshot's value and entropy
at every probe handover and the calibration gap, the post-target-8 share, the handover diagnostic, throughput with the native-tick split, the untrained
`policy.pth` equality with g1's `eb592c88...`) plus decision 8's: the trigger-to-test gap per attempt, the attempt yield, the replenishment schedule as it ran,
every deferred trigger, the pointer over training time, the throughput by pointer, the per-landing clears against the reused tape.

**R11. What "production-count" means for the end-to-end test.** The synthetic end-to-end run first measures a pinned tape table on the synthetic world at the
registered counts (200 keys at 2,128, 40 elsewhere; every claimed clear replayed exactly; the g2 machinery), which stands in for g2-s1's table; then s1 at the
registered counts and caps (the table reused by digest, the 5-key drift check, 20 + 20 + 1 per audited landing, 20 + 1 at tick 0, 12 P2 starts, the 4,800 s
training wall, the tick and transition caps, ten slots, 4 + 6, the probe tests of 20 at 10); then s2 resumed from s1's saved state. The synthetic learner
(`rl/m9_g2_stub.py`, unchanged) forgets the cold start at 1,966 once its competence is below 1,920, so every attempt at the last pointer is
BLOCKED_BY_RECHECK and the line exercises the replenishment schedule up to and past the 320 cap, with no HELD, no STALLED and no END.

**R12. The git state the preflight accepts.** Exactly one tracked file may differ from HEAD, `rl/m9_eval_tests.py`, and only at its pinned post-edit digest
(decision 9); every other entry of `git status` must be a new file. The g3 identity and the source snapshot pin that digest.

## 4. The authorised edit (decision 9)

The two guard lines of the tracked `rl/m9_eval_tests.py` (its own `source_guards` test, lines 557 and 559) spell six literals that g1's source guard
(`rl/m9_tests.py`, which scans every `rl/m9_*.py` file except itself) forbids; the stop review's option a assembles them from fragments, as `rl/m9_g2_tests.py`
line 1092 already does. The edit changes the test's own meaning in no way (the assembled strings are compared at run time) and touches nothing else. The
file keeps its CRLF line endings.

```diff
--- a/rl/m9_eval_tests.py
+++ b/rl/m9_eval_tests.py
@@ -554,9 +554,9 @@ def source_guards() -> None:
     files = {f: (RL / f).read_text(encoding="utf-8") for f in ("m9_eval_policy.py", "m9_eval_ckpt.py", "m9_eval_session.py", "m9_eval_snapshot.py")}
     tests_src = (RL / "m9_eval_tests.py").read_text(encoding="utf-8")
     for f, src in files.items():
-        for bad in ("tas_input", ".btti", "fixtures/m7g", "m7g_capture", "replay/recordings"):
+        for bad in ("tas_" + "input", ".bt" + "ti", "fixtures/" + "m7g", "m7g_" + "capture", "replay/recordings"):
             ok(f"{f}: no reference to {bad}", bad not in src)
-        for bad in ("import random", "np.random", "torch.manual_seed", "import secrets", "import uuid", "os.urandom", "rng_seed", "native_rng"):
+        for bad in ("import random", "np.random", "torch.manual_seed", "import secrets", "import uuid", "os.urandom", "rng_" + "seed", "native_" + "rng"):
             ok(f"{f}: no {bad}", bad not in src)
         for bad in (".learn(", "PPO(", "PPO.load", ".backward(", "optimizer.step", "zero_grad", "torch.optim.Adam(", "torch.optim.SGD("):
             ok(f"{f}: no training vocabulary {bad}", bad not in src)
```

| | sha256 |
| --- | --- |
| `rl/m9_eval_tests.py` before (HEAD `6d73f52`) | `05c6765f5694eb08b18b081cab4e585ad34d0bbe3813b50c59b4a49f0f03c9d8` |
| `rl/m9_eval_tests.py` after | `7151c34bee4c6e9cd20697d902dc8e8e10a8e4eeee67cee93f429acbe12edb84` |

`git diff --check` is clean. The edit is uncommitted (no commit is authorised); the g3 preflight, identity and source snapshot pin the post-edit digest (R12).

**A consequence recorded here for Part B.** The g1 unit suite (`rl/m9_tests.py`, `tracked_files_are_unchanged_and_only_new_files_exist`) and the g2 suite
(`rl/m9_g2_tests.py`, the test of the same name) each assert that NO tracked file differs from HEAD (`git diff --name-only HEAD` empty) and that `git status`
shows nothing but new files. With the authorised edit uncommitted, those two gates fail by construction; the six source-guard failures the edit was meant to
remove do pass. No state of the working tree satisfies both "the edit is applied" and "no tracked file differs from HEAD" without a commit, which is not
authorised, or an edit of those two gates, which is not authorised either. The suite results are reported as measured in the implementation record and the
session report; the judgement belongs to Part B condition 1.

## 5. What is explicitly not part of g3-s1

No s2 (its code path exists and is tested synthetically; it needs its own approval after s1's increment is recorded); no archive session (M8-sd1 is a
separate proposal); no tick-0 claim (the claim definition is g1's, untested); observation v4 stays an evidence-triggered fallback; no imitation; no second
seed; no warm start from g2-s1's weights; no change to the trigger bar (the stop review's sustained-trigger alternative is not chosen); no retry, extension or
repair. Nothing follows an outcome automatically.

## 6. Pre-launch review and hazards fixed before launch (recorded before launch; flagged in the report)

This section is filled before the snapshot if the pre-launch review finds a hazard whose fix changes no registered measure, threshold, rule, schedule or
training setting. Each entry names the hazard, the fix and the registered statement it implements; the line contract digest must be unchanged by every entry.

| id | hazard found | fix | registered statement it implements |
| --- | --- | --- | --- |
| (none yet) | | | |

Defects found while testing the new code are corrections of new code to its own specification, made before any pass counted; they are listed in the
implementation record, section 7.
