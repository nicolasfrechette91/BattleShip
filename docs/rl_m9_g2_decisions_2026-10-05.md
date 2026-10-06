# M9-g2: the user's decisions for the second robustification gate (session s1), and how they were applied (2026-10-05)

**Status.** Recorded **before any native tick** of M9-g2, at the start of an unattended session whose Part A is zero-tick preparation, whose Part B is the
launch conditions and whose Part C (one M9-g2-s1 training session) runs only if every Part B condition holds. Nothing in the frozen proposals, in any M8 or
M9-g1 file, in `runs/m8_rd*/`, `runs/m9_g1/`, `runs/m9_g1_eval/`, in `replay/`, in the external guide or in any tracked file was edited. The additions are this
file, `docs/rl_m9_g2_implementation.md`, the new `rl/m9_g2_*.py` files, the preparation tools under `logs/m9_g2_prep/` (Git-ignored) and, in Part C, the approval,
the run tree `runs/m9_g2/s1/` and the results record.

**Scope label**, carried by every M9-g2 record (`rl/m9_g2_contract.SCOPE`): *M9-g2-s1: backward-algorithm robustification under the controlled frontier rule
`m9_g2_frontier_v1` (PPO from prefix-replayed start states on the agent's own two verified rd4 clears, sticky actions p = 0.25, observation
btt_policy_obs_v3_entities, reward btt_reward_v2, entropy coefficient 0.01); the first session of a resumable line; one set of keyed draws; progress measured as
the sustained frontier depth D and the reliable reach R at landing states against a pinned tape baseline under the registered rules; no claim of a tick-0 policy.*

This session implements `docs/rl_m9_g2_proposal_2026-10-04.md` as decided below. The M9-g1 records (`docs/rl_m9_g1_*`) and the diagnosis are the evidence the
design rests on; nothing in them is re-decided.

## 1. The decisions (the user's words, abridged) and where each is applied

| # | decision | applied in |
| ---: | --- | --- |
| 1 | **The frontier rule as proposed.** The 8-of-20 trigger; a frozen-policy strip test of 20 sticky episodes, passing at 10 with early stopping; a re-check of EVERY previously passed landing on every attempt; a 20-tick move only if all tests pass; a failed re-check only blocks the move, the pointer never moves forward; at most 3 attempts per pointer per session and 6 per pointer over the line, exhausting 6 ends the line; training pauses while tests run; check points are the landing states computed from the agent's own route | `rl/m9_g2_frontier.py` (`Frontier`: window, trigger, attempts, HELD / STALLED, the move), `rl/m9_g2_probe.py` (the frozen snapshot, the strip test, the re-checks, curtailment, the pause), `rl/m9_g2_contract.py` (`TRIGGER_*`, `TEST_*`, `ATTEMPTS_*`); the landing states are P1's `landing_starts` of the trunk, which must equal the registered six (as g1) |
| 2 | **Entropy coefficient 0.01.** Everything else from g1 unchanged: observation v3, reward v2, a fresh policy (seed 0) for s1, sticky actions 0.25, routes as start states only, the two verified rd4 clears, the final-claim definition, horizon bootstrapping as inherited | `rl/m9_g2_contract.PPO` = `rl/m9_contract.PPO` (ent_coef 0.01, seed 0, fresh); `rl/m9_g2_train.make_fresh_ppo` (`rl/m7n_policy.make_model`); the g1 modules for the observation pipeline, the reward, the staging, the lineages and the claim definition are imported unchanged |
| 3 | **Value calibration check: reported only** | `rl/m9_g2_probe.py` records the snapshot's value and entropy at every probe handover; `rl/m9_g2_report.py` reports the calibration gap per test (mean V against the realised mean return), the close audit's gap per landing, the post-target-8 success share; no rule branch reads them |
| 4 | **Tape baseline.** Measured once in s1: 200 keys at 2,128 and 40 at each other landing, on identical draws; every counted tape clear fully replayed; the result pinned; the bar `max(10, ceil(20 * p_hat) + 5)` | `rl/m9_g2_tape.py` (T0 jobs, the claimed table, the pinned table, `bar`), verification tier 0 (`rl/m9_g2_run.py`), `session/tape_baseline.json` (pinned, with its sha256) |
| 5 | **Resumable line.** Sessions of 80 minutes of training under a 145-minute hard cap; model, optimizer state and frontier state saved at the close with pinned digests, for a later separately authorised s2; evaluation keys identical across sessions | `rl/m9_g2_contract` (`WALL_CAPS_S`, `GLOBAL_CAP_S`), `rl/m9_g2_train.save_checkpoint` (model.zip with `policy.optimizer.pth`, `curriculum_state.json`, `checkpoint.json` pins), `rl/m9_g2_resume.py` (the final-state record, the continuity assertions, the refusals), the audit keys `m9|g2|reach|<landing>|<k>` fixed for the line |
| 6 | **Progress measure and budget.** D_k as proposed; line stop if D has not reached 1,966 after N = 3 sessions; from session 4 one new landing per two sessions; a cap of 8 sessions; g2 complete at D <= 1,473 | `rl/m9_g2_rule.py` (`depth_D`, `m9_g2_line_rule_v1`), `rl/m9_g2_contract` (`LINE_*`) |
| 7 | **g2-s1 rule as proposed.** PASS: R_1 (with the tape margin) <= 1,966; INCONCLUSIVE: D_1 <= 2,128; NULL: D_1 = none; INCOMPLETE and INVALID as in g1 | `rl/m9_g2_rule.py` (`m9_g2_s1_rule_v1`, self-test) |
| 8 | **Replay verification.** Training-time strip and re-check tests may spot-check one clear per passed test by exact replay; every clear counted in a registered measure (D, R, the tape baseline, any final claim) must be fully replayed exactly | `rl/m9_g2_run.py` verification plan: tier 0 = every close-audit sticky clear at an audited landing and every T0 tape clear; tier 1 = the first 20 training clears; tier 2 = one keyed clear per passed test; tier 3 = the diagnostics; the rule counts only verified clears (section 3, R11) |
| 9 | **No throughput measurement; fixed 4 + 6 slots** | no P3; `rl/m9_g2_contract.SPLIT = (4, 6)`, `PROBE_SLOTS = 6` |
| 10 | **Artifact metadata.** Every artifact records the top-level task block `{"id": "ssb64_us_mario_btt_v1", "character": "mario", "stage": "btt_mario"}` and `created_utc` at the source; the writer refuses to write without them | every write goes through `rl/m9_artifacts.py` (imported unchanged; the refusal is tested there and again in `rl/m9_g2_tests.py`); the close audit and `verify-run` audit the whole tree |
| 11 | **Every checkpoint, optimizer state, frontier state and training log is evidence.** Pin their digests; place them under D: backup coverage | `runs/m9_g2/s1/training/checkpoints/*/checkpoint.json` pins model.zip, its `policy.pth` and `policy.optimizer.pth` members and `curriculum_state.json`; `session/final_state.json` pins the saved state for s2; the whole tree is Git-ignored under `runs/` and is backed up as the increment `incr_m9_g2_s1` by the unchanged `rl/tools/runs_backup.py` |

Constraints that stay as they were (unchanged in code, checked by tests): no native RNG seed inspection, logging, control, comparison or hashing (every draw is a
Python-side keyed sha256 uniform, `m9|g2|...`); process restart resets the episode (one fresh process per episode, prefix included; probe, tape and audit
episodes too; a process is never reused; pausing training parks processes at `WaitingForAction`, nothing is reset in-process, there is no save state); the exact
submit / consume / input-tick contract (prefix word i consumes tick i, the policy's first word consumes tick tau, a parked process consumes nothing until its next
word); canonical controller words are the replay truth (the SUBMITTED word is the recorded word; sampled words, sticky masks and action draws are metadata); the
routes used are the agent's own; human crossing recordings, the crossing fixtures and the TAS are validation-only and never read (the static source guard of
`rl/m9_g2_tests.py` refuses any reference); no hardcoded route or waypoint (the landing states are computed from the trunk's own grounded segments; they decide
only when the start window moves, never where the agent goes, and never enter reward, observation or action); non-PORT decomp and byte-matching behaviour is
preserved (no native, decomp or submodule change; the existing executable `30a3913b...` with its existing read-only diagnostics); no commit, push, branch or pull
request; no application is closed; the M8 trees, `runs/m9_g1/` and `runs/m9_g1_eval/` are only read and must stay byte-identical to their D: increments.

## 2. The facts the implementation re-derived from the preserved evidence (read only)

- The two routes and the trunk's landing states are g1's (`docs/rl_m9_g1_decisions_2026-10-04.md`, section 2): T_clear 2,326 words (`5eccd4e2...`), T_t 2,315
  words (`de1228be...`), shared prefix 2,298, the six registered landings 2,128, 1,966, 1,694, 1,473, 1,369, 1,248 computed from the trunk's grounded segments.
  The code refuses any difference at P1 (`rl/m9_lineages.check_landings`, unchanged).
- The executable `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee`, the `.o2r` files, `gamecontrollerdb.txt` and the frozen configuration
  (`BattleShip.cfg.json` `1b29d91b...`, `imgui.ini` `0d267321...`) are rd1's pins, read in place.
- The protected trees and their D: increments: rd1 166 files, rd2 62, rd3 77, rd4 93 (as g1), `runs/m9_g1` 2,740 files / 354,131,925 bytes / manifest
  `92ba5481...` (the increment `2026-10-04_incr_m9_g1`), `runs/m9_g1_eval` 1,393 files / 162,003,001 bytes / manifest `ab3e6c61...` (the increment
  `2026-10-04_incr_m9_g1_eval`).
- Throughput basis for the budget: g1 trained at a median 442 policy transitions/s (283-594 as the frontier moved back), 7,938,755 native ticks in 3,600 s; the
  g1 P4 tape ran 140 episodes in 190 s (0.74 episodes/s on ten slots); the g1 checkpoint evaluation ran 675 episodes in 967 s (0.70 episodes/s on ten slots) and
  replayed 99 clears (244,133 ticks) in 148 s on eight threads; g1's evaluation replayed 52 clears (122,421 ticks) in 68 s.
- g1's untrained checkpoint `ckpt_000000000`: the `policy.pth` member of its model.zip has sha256 `eb592c887fc66aaba038e0b35986463bf03153bd7fe78a3f5d80357fa517ceb0`
  (the zip itself `16dc29c9...` carries file timestamps, so only the member can be compared; reported, never deciding).

## 3. Mechanical readings the implementation needed (none changes a registered measure, threshold, schedule or training setting)

The decisions and the proposal fix every rule, constant, cap and threshold. The items below are the readings the code needed where the proposal's text leaves a
mechanical detail unstated. Each can be overruled; none alters a registered definition. They are written down so that Part B condition 6 can be judged.

**R1. Keys.** Every g2 draw is a Python-side sha256 uniform (`rl/m9_sticky.uniform`, unchanged) on a key of the `m9|g2|...` family. The sticky draw key of an
episode is its label extended by `|<tick>`, exactly as the proposal writes for the probes. Labels: training `m9|g2|train|<episode>`; probe
`m9|g2|probe|<pointer>|<a>|<part>|<k>` (part = `strip` or the landing tick; a = the line-wide attempt index at that pointer, 1-based); T0 tape and the close
audit `m9|g2|reach|<landing>|<k>` (the tape's keys k = 0..199 at 2,128 and 0..39 elsewhere, the audit's k = 0..19 at every landing, identical in every session);
tick 0 `m9|g2|tick0|<k>`; the unperturbed diagnostic has no label. Start draws: training `m9|g2|start|<episode>|region`, `|tau`, `|lineage`; the strip test
`m9|g2|probe|<pointer>|<a>|strip|<k>|tau` and `|lineage`. Action sampling (keyed inverse CDF on the frozen weights, as the g1 checkpoint evaluation):
probes `m9|g2|probeact|<pointer>|<a>|<part>|<k>|<tick>|<stick or button>`; the close audit `m9|g2|auditact|<mode>|<landing>|<k>|<tick>|<stick or button>` with
mode `sticky` or `unperturbed` (tick 0: landing 0). The verification pick of a passed test: `m9|g2|verifypick|<pointer>|<a>|<part>`; the artifact sample
`m9|g2|artifact|<episode>`. P2 is "as g1" and keeps g1's keys (`m9|g1|p2|<k>|tau`, `|word`): an integrity check whose draws decide nothing. The g1 sticky rule
(`rl/m9_sticky.submit`, p = 0.25, nothing repeats at tick 0, the first policy word after a prefix may repeat the prefix's last word) is applied verbatim by the
g2 episode context with the g2 key (`rl/m9_g2_arena.G2EpisodeCtx`); `rl/m9_sticky` itself is not changed.

**R2. The trigger window.** Counted strip outcomes (a completed training episode, native end or horizon, whose start was drawn from the strip under the current
pointer; stale and non-strip outcomes as g1) accumulate in a window that starts at the latest of the session open, the last move and the last attempt at this
pointer. The window is curtailed: the trigger fires at the 8th clear; the window is void at the 13th non-clear and a new window begins at once. Outcomes that
complete between a trigger and its attempt (the rest of that rollout) are logged as `after_trigger` and belong to no window. While the pointer is HELD a window
that reaches 8 clears is logged as `held_trigger` and no attempt runs; the next window begins.

**R3. Attempt timing and the pause.** An attempt runs at the first rollout start after the trigger, inside the training callback's `on_rollout_start` (SB3
calls it after the previous rollout's PPO update). The four playing slots keep their active episodes parked at `WaitingForAction` (SB3 holds their last
observations; no word is sent). The six preparing slots are drained: a start still staging finishes staging (the stage reply is awaited), every parked start is
closed and recorded in `training/withdrawn.jsonl` (its episode number is never drawn again: the training source's counter only advances), and the training
arena's dispatch stays paused until the attempt ends. The attempt then runs on exactly those six slots under a second arena over the same pool; before the
slots are handed back every command sent to them has been answered (in-flight counts, `rl/m9_g2_arena.G2Arena`), so no reply of a probe can reach the training
vector. A probe's native ticks count toward the training phase's native-tick cap and its wall time toward the training wall cap; probe transitions never enter
PPO.

**R4. Probe start draws.** Strip test episode k: tau = pointer + floor(20 u) with u = uniform(`m9|g2|probe|<pointer>|<a>|strip|<k>|tau`); the lineage as g1's R2
(shared up to 2,298, else uniform over the lineages long enough with u = uniform(`...|lineage`)). A re-check episode starts at the trunk's own state at the
landing (T_clear, tau = landing). Snapshot: the current policy's weights copied once at the attempt's start (`torch.save` of the 12-tensor state dict to
`training/attempts/a<n>/snapshot_policy.pth`; its sha256 is the recorded snapshot digest) and evaluated as a weight-only network with one observation per
forward pass and one torch thread (`rl/m9_g2_policy.FrozenPolicy`, built from `rl/m9_eval_policy`'s network, inverse CDF and state keys, without the optimizer
guard, which would break the live optimizer of the same process).

**R5. Curtailment and parallel re-checks.** Each test (the strip, or one landing) passes at its 10th clear and fails at its 11th non-clear. When a test is
decided its remaining episodes (staged, parked, active) are closed and recorded as `abandoned` with the native ticks they consumed; an abandoned episode is
not an outcome. The re-checks run only after the strip test passes; their jobs are interleaved by k across the landings so that the landings progress in
parallel; the attempt fails at the first landing whose test fails, and every other test is then abandoned. A probe episode whose process dies or fails to launch
is a lifecycle failure: it is staged again with the same job id and keys (a fixed list, g1's F1); more than three lifecycle failures in one attempt stop the
session (INCOMPLETE), as in every g1 phase. A probe step that fails an integrity check is INVALID.

**R6. Attempt bounds.** Every decided attempt counts, pass or fail. HELD: after the third failed attempt at one pointer in one session no further attempt runs at
that pointer in that session; training continues; the pointer stays; the per-session count is not carried. STALLED: after the sixth failed attempt at one
pointer over the line, training ends at that rollout boundary as a registered valid end (`stalled`), the close audit runs, and the line rule records
END_STALLED. An attempt that the training wall cap or a stop interrupts is recorded as `interrupted` and counts as neither pass nor fail.

**R7. Checkpoints and the curriculum state.** Every checkpoint directory (`training/checkpoints/ckpt_<t>` at the first rollout start at or after every multiple
of 102,400 global transitions, the initial model, and `final`) holds `model.zip` (SB3's save: the policy and `policy.optimizer.pth`, the Adam moments and step
counts), `curriculum_state.json` and `checkpoint.json`, which pins the sha256 of model.zip, of its `policy.pth` and `policy.optimizer.pth` members and of the
curriculum state. The curriculum state carries the pointer, the move history, every attempt's summary, the failed-attempt counts per pointer over the line, the
HELD and STALLED flags, the session index, the global episode and attempt counters, the line contract digest, the tape table digest (the claimed table during
training; the pinned verified table is in `session/final_state.json`), the task block and `created_utc`.

**R8. Close audit.** The frozen final policy is evaluated at every landing from 2,128 down to one landing beyond the frontier: every registered landing >=
pointer + 20 plus the first landing < pointer + 20 (with the pointer still at or above 2,120 that is 2,128 alone). Per landing: 20 sticky episodes
(keys `m9|g2|reach|<landing>|<k>`, k = 0..19, the same keys as the tape's first 20 at that landing), 20 unperturbed and 1 deterministic (argmax) as diagnostics;
tick 0: 20 sticky and 1 deterministic, descriptive. D and R are computed over the audited landings; a landing that was not audited does not pass. Every audit
action is a keyed inverse-CDF draw from the frozen final weights (the same sampler as the probes), so an audit episode is reproducible from its keys.

**R9. The tape baseline and B.** p_hat(landing) = verified tape clears / tape keys at that landing. B(landing) = max(10, ceil(20 p_hat) + 5). A tape clear is
counted only when its full replay is exact; an inexact tape replay is INVALID; a tape clear left unreplayed by the verification caps leaves that landing's B
unpinned. The pinned table (`session/tape_baseline.json`: per-key outcomes, the verified counts, p_hat, B per landing, the sha256 of the record's canonical
form) is what a later session reads by digest; `t0/tape_table.json` is the claimed table written at the end of T0.

**R10. D and R.** D_1 = the earliest registered landing such that at it and at every later audited landing the final policy's verified sticky clears are >= 10 of
20. R_1 = the same with >= B(landing). R_1 is never earlier than D_1. `FRONTIER_BACKED` is reported when every landing >= pointer + 20 passes the 10-of-20 bar at
the close, else `FRONTIER_AHEAD`.

**R11. Verification and INCOMPLETE.** The verification phase (600 s, 1,500,000 ticks) replays in tiers: 0 = every close-audit sticky clear at an audited landing
and every T0 tape clear (both registered measures); 1 = the first 20 training clears; 2 = one keyed clear per passed test of every attempt (strip and each
re-check); 3 = the unperturbed, deterministic and tick-0 clears. The rule counts only verified policy clears. The session is INCOMPLETE if an unverified
close-audit clear could change D_1 or R_1, or if B is unpinned at an audited landing whose verified policy count is at least 10 (where B could matter). Other
unverified clears are reported. An inexact replay of any replayed clear is INVALID.

**R12. The session envelope.** Phases and caps (wall, native ticks): open 60 s / 0; P1 240 s / 60,000; P2 120 s / 60,000; T0 900 s / 1,500,000; training
4,800 s / 20,000,000 and <= 3,072,000 transitions in the session; close audit 1,200 s / 3,000,000; verification 600 s / 1,500,000; close 300 s / 0; session hard
cap 8,700 s (145 min). The session clock starts at the session object, after the preflight (which runs the unit suite). The registered valid ends of training are
its wall cap, its native-tick cap, its transition cap and STALLED. A wall cap in the close audit ends the audit validly (the rule then decides INCOMPLETE if a
needed cell is incomplete), as g1's evaluation. The open phase records identities and pins and copies the approval; it does not re-hash the six protected trees
(the preflight did so seconds earlier; the close phase does so again). P1 and P2 are g1's, unchanged (both routes replayed three times each, the twelve keyed
staging-equivalence starts).

**R13. Resources.** rd4's and g1's memory caps; at most 10 BattleShip processes (training 4 + 6; an attempt 4 parked + 6 probes; T0 and the audit 10; verification
8 threads; P1 at most 4 + 1; P2 at most 4 + 3); the fixed 4 + 6 split.

**R14. Resume (implemented and tested synthetically; s2 is not run and not authorised).** A session k >= 2 copies the previous session's `final/model.zip`,
`curriculum_state.json` and `session/tape_baseline.json` into `runs/m9_g2/s<k>/input/`, checks each against the digests the approval names, loads with
`PPO.load(model.zip, env=<the training vector>, device="cpu")` (SB3 rebuilds the policy and the optimizer and loads both state dicts), asserts that
`num_timesteps`, `_n_updates` and every parameter's Adam step count equal the saved values, sets the Python-side training seed 1000 + k (recorded), restores the
frontier state (pointer, line attempt counts, moves, STALLED, global counters; the per-session counts, HELD and the window restart), and continues with
`learn(total_timesteps=3,072,000, reset_num_timesteps=False)`. A resume refuses a changed line contract digest, executable, PPO value or input digest.

**R15. Run tree and the write guard.** The session writes only `runs/m9_g2/s1/`; the write guard covers every other directory under `runs/` (the M8 trees,
`runs/m9_g1`, `runs/m9_g1_eval`, every other `runs/m9_g2/s<j>`), `rl/` and `docs/`. The six protected trees are compared with their D: increments by the preflight
and at the close.

**R16. Reported readings (never deciding).** The pointer trace; every attempt (trigger window, snapshot digest, strip result, each re-check, MOVED / FAILED_STRIP /
BLOCKED_BY_RECHECK, HELD, STALLED); FRONTIER_BACKED; R_unperturbed, the deterministic and tick-0 results; per-rollout entropy and explained variance; the
snapshot's entropy, top-word probability and value at every probe handover and the calibration gap per test; the post-target-8 success share per 100 training
episodes; the handover diagnostic; throughput and the native-tick split (prefix, policy, probe); the equality of the untrained `policy.pth` member with g1's.

**R17. What "production-count" means for the end-to-end test.** The synthetic end-to-end run is a two-session line (s1, then s2 resumed from s1's saved state)
at the registered counts and caps (400 T0 episodes, 20 + 20 + 1 per audited landing, 20 + 1 at tick 0, 12 P2 starts, the 4,800 s training wall, the tick and
transition caps, ten slots, 4 + 6, the probe tests of 20 at 10) against the synthetic world of `rl/m9_stub.py` (in-process lock-step pool, virtual clock charged
per native tick), with a synthetic learner whose competence moves back as it collects transitions and which, once its competence boundary is below 1,920, no
longer completes from a cold start at the landing 1,966 (so the e2e exercises BLOCKED_BY_RECHECK, HELD in s1, STALLED and END_STALLED in s2). The transition cap
is exercised by a separate scaled test.

## 4. What is explicitly not part of g2-s1

No s2 (its code path exists and is tested synthetically; it needs its own approval after s1's increment is recorded); no archive session; no tick-0 claim (the
claim definition is g1's, untested); observation v4 stays an evidence-triggered fallback; no imitation; no second seed; no retry, extension or repair. Nothing
follows an outcome automatically.

## 5. Pre-launch review and hazards fixed before launch (recorded before launch; flagged in the report)

This section is filled before the snapshot if the pre-launch review finds a hazard whose fix changes no registered measure, threshold, rule, schedule or
training setting. Each entry names the hazard, the fix and the registered statement it implements; the line contract digest must be unchanged by every entry.

| id | hazard found | fix | registered statement it implements |
| --- | --- | --- | --- |
| H1 | The verification phase launched replays until its own 600 s wall cap, so replays still in flight at the cap would have been stopped by the clock and a complete run recorded INCOMPLETE (the hazard the M9-g1 checkpoint evaluation had found and fixed with a launch margin) | replay launches stop 120 s before the verification wall cap (`rl/m9_g2_contract.VERIFY_LAUNCH_MARGIN_S`, `rl/m9_g2_run.G2Session.verify`); the cap, the tiers and the counting are unchanged | R11 and R12: the verification phase ends inside its cap with every launched replay finished; the g2 contract digest records the margin (`8dfd44c6...`); the line contract digest is unchanged (`1aadc7a6...`) |

Found before the three consecutive passes and before the snapshot (the passes ran on the code with the fix). It changes no registered measure, threshold, rule,
schedule, cap value or training setting. It is flagged in the session report (Part B condition 6). The defects found while testing the new code (a dropped reply
batch at a stop, the rule's hardcoded audit count, the synthetic learner's zip format, the resume refusal class, the resume's tape-digest comparison) are in the
implementation record, section 7: they are corrections of new code to its own specification, made before any pass counted.
