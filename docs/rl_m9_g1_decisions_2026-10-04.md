# M9-g1: the user's decisions for the first robustification gate, and how they were applied (2026-10-04)

**Status.** Recorded **before any native tick** of M9-g1, at the start of an unattended session whose Part A is zero-tick preparation, whose Part B is the launch conditions and whose
Part C (one native gate) runs only if every Part B condition holds. Nothing in the frozen proposals, in any M8 file, in `runs/m8_rd/`, `runs/m8_rd_rd2/`, `runs/m8_rd_rd3/` or
`runs/m8_rd_rd4/`, in `replay/`, or in any tracked file was edited. This file, `docs/rl_m9_g1_implementation.md` and the new `rl/m9_*.py` files are the additions; the one edit outside the
repository is the relabelling of the old M9 milestone in the external guide (decision 1), with the guide's previous text kept beside it.

**Scope label**, carried by every M9 record (`rl/m9_contract.SCOPE`): *M9-g1: backward-algorithm robustification (PPO from prefix-replayed start states on the agent's own two
verified rd4 clears, sticky actions p = 0.25, observation btt_policy_obs_v3_entities, reward btt_reward_v2); one gate, one run, one set of keyed draws; reach measured at landing
states under the registered rule; no claim of a tick-0 policy.*

This session implements `docs/rl_m9_policy_proposal_2026-10-03.md` as decided below.

## 1. The decisions (the user's words, abridged) and where each is applied

| # | decision | applied in |
| ---: | --- | --- |
| 1 | **Naming.** M9 is robustification; the old M9 "replay visualization" milestone is relabelled in the external guide, the old wording marked superseded, not deleted | `Smash_pc_port/guide.md` (a dated backup `guide.md.bak_2026-10-04_pre_m9_rename` was made first); every M9 record names the milestone `M9` |
| 2 | **Sticky actions at 0.25 per tick**, as proposed. ADDITIONALLY the backward depth reached with no stickiness, as a diagnostic only; it never affects the decision | `rl/m9_sticky.py`, `rl/m9_contract.STICKY_P`; the unperturbed diagnostic = the `unperturbed` job family of `rl/m9_eval.py` (20 stochastic episodes without stickiness at every landing state and 20 at tick 0), reported as `R_unperturbed` by `rl/m9_rule._diagnostics`, which no rule branch reads |
| 3 | **Thresholds.** Gate: at least 10 of 20 perturbed clears at each landing point and a margin of at least 5 over the tape. Final claim, defined but not tested in g1: 50 of 100 unperturbed, 50 of 100 sticky, margin at least 25 | `rl/m9_contract` (`GATE_MIN_CLEARS`, `TAPE_MARGIN`, `CLAIM`), `rl/m9_rule` (`depth`, `claim_status`), `rl/m9_claim.py` (the claim evaluator, never run by g1) |
| 4 | **PASS depth** the wall-top landing (tick 1,694) or earlier; INCONCLUSIVE at 1,966 or 2,128; NULL if none | `rl/m9_rule.apply` (`PASS_DEPTH`, `INCONCLUSIVE_DEPTHS`; R <= 1,473 adds "crossing learned", reported) |
| 5 | **Routes.** Only the two verified rd4 clears (iterations 11206 and 11286). Each must replay exactly from tick 0 at the gate's open; any mismatch is INVALID | `rl/m9_lineages.py` (registration, tables), `rl/m9_run.Session.p1` (three replays per route; any inexact replay is INVALID) |
| 6 | **A freshly initialised policy**, observation v3, reward v2, the existing PPO settings EXCEPT an entropy coefficient of 0.01 from the start (one standard value, never tuned) | `rl/m9_contract.PPO` (`ent_coef` 0.01, `initialisation` fresh), `rl/m9_train.make_ppo` (`rl/m7n_policy.make_model`, seed 0, fresh) |
| 7 | **Observation v3 only.** No v4 in g1 | `rl/m9_obs.V3Pipeline` (the M7n builder fed every reply); `btt_policy_obs_v4_input` and `SSB64_RL_INPUT` are used nowhere in training or evaluation (`SSB64_RL_INPUT` appears only in the verification replays' flag set, as in rd1-rd4's) |
| 8 | **Routes are start states only.** No imitation or self-imitation loss | `rl/m9_train.py` (PPO only; the docstring states it and a source test forbids any auxiliary loss, behaviour-cloning or SIL vocabulary); lineage words are read only to replay prefixes |
| 9 | **Process split.** Default 4 playing + 6 preparing starts; the short pre-launch throughput measurement may choose 2 + 8 by a selection rule written here before launch | `rl/m9_run.select_split`, `Session.p3`; the rule is in section 3 (R6) below |
| 10 | **Artifact metadata.** Every M9 artifact records the top-level task block and `created_utc`, placed as the proposal specifies; the writer refuses to write without them; `replay/` untouched | `rl/m9_artifacts.py` (`check`, `write_json`, `write_json_gz`, `append_jsonl`, `write_episode_artifact`, `audit_tree`), enforced again by the close audit and `verify-run` |
| 11 | **M8-rd5 stays in reserve.** Not started | nothing in M9 imports or launches an M8 session; no rd5 file exists |
| 12 | **Budget.** 60 minutes of training, 15,000,000 native ticks, 3,072,000 transitions, at most 10 game processes, rd4's memory limits, a 130-minute session hard cap | `rl/m9_contract` (`WALL_CAPS_S`, `TICK_CAPS`, `TRANSITION_CAP`, `GLOBAL_CAP_S`, `MEMORY_CAPS_MB`, `MAX_BATTLESHIP_PROCESSES`), `rl/m9_run.Clock`, `rl/m9_run.budget_projection` |
| 13 | **Every policy checkpoint and training log of the gate is evidence.** Pin their digests; place them where the D: backup procedure covers them | `runs/m9_g1/training/checkpoints/ckpt_<t>/{model.zip, checkpoint.json}` (each `checkpoint.json` pins the model's sha256) and `runs/m9_g1/training/checkpoints.json` (the index); all logs are under `runs/m9_g1/`, which the unchanged `rl/tools/runs_backup.py` copies as the increment `incr_m9_g1`; `verify-run` re-hashes every model |

Constraints that stay as they were (unchanged in code, checked by tests): no native RNG seed inspection, logging, control, comparison or hashing (every draw is a Python-side keyed
sha256 uniform, `m9|g1|...`); process restart resets the episode (one fresh process per episode, prefix included; a process is never reused; no in-process reset, no save state); the exact
submit / consume / input-tick contract (prefix word i consumes tick i, the policy's first word consumes tick tau, a parked process waits frozen at `WaitingForAction`); canonical controller
words are the replay truth (the SUBMITTED word is the recorded word; sticky draws and sampled words are metadata); the routes used are the agent's own; human crossing recordings, the
crossing fixtures and the TAS are validation-only and never read (the static source guard of `rl/m9_tests.py` refuses any reference); no hardcoded route or waypoint (the landing states are
computed from the trunk's own grounded segments and used only by the evaluation and the rule, never by training, reward or observation); non-PORT decomp and byte-matching behaviour is
preserved (no native, decomp or submodule change; the existing executable `30a3913b...` is used with its existing read-only diagnostics); no commit, push, branch or pull request;
no application is closed.

## 2. The facts the implementation re-derived from the preserved evidence (read only)

- The two routes (`runs/m8_rd_rd4/routes/T_clear` 2,326 words, native action digest `5eccd4e2...`, completion clocks 2,325 / 2,326; `T_t` 2,315 words, digest `de1228be...`, clocks 2,314 /
  2,315) are Track 1 words 0..71 equal to their `actions.jsonl`; they share exactly their first 2,298 words.
- The trunk's grounded segments begin at input ticks 0, 58, 174, 269, 375, 508, 682, 753, 841, 1,061, 1,192, 1,248, 1,369, 1,473, 1,694, 1,966, 2,128 (computed from the verifying replay's
  replies). The six registered landing states 2,128, 1,966, 1,694, 1,473, 1,369, 1,248 equal the segment starts from 1,248 up, and the code refuses any difference (P1). **The proposal's estimate of "22 earlier landings" does not
  match the trace: the trunk has eleven grounded-segment starts below 1,248, tick 0 included.**
- The frozen runtime configuration, the executable and the read-only runtime files are rd1's pins, read in place; the four M8 trees equal their D: increments (166, 62, 77, 93 files).

## 3. Mechanical readings the implementation needed (none changes a registered measure, threshold, schedule or training setting)

The decisions and the proposal fix every rule, constant, cap and threshold. The items below are the readings the code needed. Each can be overruled; none alters a registered definition.
They are written down so that Part B condition 6 can be judged against them.

**R1. The sticky rule's first tick.** "At every policy-phase tick t > first" is read as every tick after the episode's FIRST tick: a draw is made for every submitted tick t >= 1, so the first
policy word after a prefix may repeat the prefix's last word (the proposal says exactly that, "which is still the agent's own lineage word"); at tick 0 (a tick-0 start) there is no previous
word and nothing repeats. Same rule in training, the reach evaluation, the tape control and the claim (`rl/m9_sticky.submit`).

**R2. Lineages and the start distribution.** Start tau is valid when some lineage holds at least tau + 2 words (0..2,324). At or below the shared prefix (2,298) the two routes give the same
words, so the start is labelled `shared` and uses T_clear's; above it the lineage is drawn uniformly among those long enough. The frontier pointer starts at 2,300. A region that is empty after
clipping to the valid starts (the rehearsal region at the first pointer: [2,360, 2,324] is empty) is drawn as the preceding non-empty region (rehearsal -> near window -> strip). Starts are
drawn when a slot becomes free (as late as possible), keyed by their episode number, and carry the pointer in force (`rl/m9_curriculum.py`).

**R3. P1.** Per lineage: two fresh-process replays (the proven `rl/m7f_trace.run_stepping_trace`, the four read-only diagnostics, the frozen runtime) and one replay through a promoted
standby (the unchanged M8 worker's `trace` job, which requires every reply's record digest to equal the rd4 verifying replay's). Every replay must be exact (native action digest, every
consumed tick, break table, the four clear facts, both completion clocks) and equal, tick by tick, to the rd4 verifying replay's chain; the two fresh replays must agree on every v3 observation
digest. The chain and v3 tables are written once and every staged start checks every prefix tick against them. The proposal's wording "three replays, once through a standby promotion" is kept
(6 replays, 14,000 ticks, cap 60,000). Any inexact replay is INVALID. A promoted-standby replay that fell back to a cold launch (the standby was not ready) is a lifecycle condition, not an integrity
failure: the promotion equivalence was not exercised, so P1 is not passed (INCOMPLETE), never INVALID.

**R4. Landing states and the evaluation.** As section 2. The reach evaluation uses the trunk lineage (T_clear) for every landing. A landing below 1,248 is evaluated (20 sticky, 20 tape, 1
deterministic, 20 unperturbed) only if the final pointer is at or below it; tick 0 is always evaluated separately (20 sticky, 1 deterministic, 20 unperturbed; its tape is P4's). The
descriptive fine grid is 2,300, 2,275, ... down to 50 below the final pointer, at most 40 points. The checkpoint nearest 30 minutes (by recorded wall time) is evaluated descriptively with 10
sticky episodes at each landing state; "the best checkpoint by reach" is reported among the two evaluated models (final and the 30-minute one) only.

**R5. P2.** Twelve keyed starts (`m9|g1|p2|<k>|tau`, uniform over the valid starts 0..2,324, trunk lineage; and a keyed first word): each is staged through the production staging (so every prefix
tick, the tick-0 record, the handover chain and the handover v3 digest are checked against the tables), one word is submitted, and the reply's record digest must equal the same tick of a cold
replay (fresh process, the four diagnostics, the frozen runtime) of the same prefix and word. Pass = all 12 equal; any difference is INVALID.

**R6. P3 and the process-split selection rule (written before launch).** P3 measures, for 120 s of wall time each, 4 + 6 and then 2 + 8 slots under a keyed random policy with starts drawn
uniformly (keyed) in 2,250..2,310, sticky actions on, no learning, counting the policy transitions of the whole window (the pipeline fill included; both configurations share it). A configuration
with any lifecycle failure during its window is ineligible. **Rule: 2 + 8 is chosen only if it is eligible and its measured policy transitions per second are at least 1.10 times those of an eligible
4 + 6; otherwise 4 + 6; if only one is eligible that one; if neither, P3 is not passed (INCOMPLETE).** The 10 % margin keeps measurement noise from moving the split. The split changes no
semantics. With 2 playing slots the rollout stays 5,120 (n_steps 2,560 x 2).

**R7. P4.** The open-loop tape (T_clear's words by tick index from the landing state, the neutral word 0 after its last word) at the six landing states and at tick 0, 20 episodes each, under
the evaluation's sticky labels (`reach:<tau>:<k>`, `tick0:0:<k>`: the policy episode and its tape share them). P4 passes when all 140 episodes complete without an integrity failure; the tape's
clears are the control of the reach rule, never a pass condition (the proposal expects essentially none).

**R8. Training.** Playing slots = the P3 split; `n_steps` = 5,120 / playing slots; no VecNormalize or other normalisation wrapper exists (observation and reward normalisation are off, the
proposal's "no observation or reward normalisation"), so a checkpoint is `model.zip` alone; checkpoints are written at the first rollout start at or after every multiple of 102,400
transitions (after the update), plus the initial untrained model and the final one. A training episode's reward is `btt_reward_v2` through the unchanged `rl/btt_rewards.reward_step`, rebased at the
handover (prefix breaks earn nothing; the per-tick cost is the policy phase's); the horizon counts input ticks from the reset (the prefix counts).

**R9. Caps.** The native-tick cap is enforced on ticks consumed plus the prefix lengths reserved at dispatch (a stage is dispatched only if its prefix fits), plus each policy step as taken; the
phase ends validly when the sum reaches the cap. The 60-minute training wall cap, the tick cap and the transition cap are the registered valid ends; any earlier stop (memory, process count, more than
three lifecycle failures, a dead worker, a software error) is INCOMPLETE. The session clock starts at the session object (pool spawns count) and the preflight, which runs the unit suite, is before it.

**R10. Lifecycle failures.** A process that dies or times out while staging is recorded and redrawn (a new episode number, a new draw); more than three in a phase is INCOMPLETE (rd1-rd4's rule). One that
dies during a policy step truncates that episode with reward 0 and is not an outcome of the curriculum. An integrity failure (tick-0, prefix, chain, v3, consumed-tick, provenance or write-guard) is INVALID with no
retry; the last 48 raw replies of the failing worker are preserved.

**R11. Verification.** Every counted clear of the reach evaluation and P4 (tier 0), the first 20 training clears (tier 1), then the deterministic, tick-0, unperturbed (tier 2) and fine-grid or
30-minute-checkpoint clears (tier 3) are replayed in that order under 1,500,000 ticks and 15 minutes. A replay must equal the online record (native action digest, every consumed tick, break table after the
handover, the per-tick chain at the last tick, the end observation but `host_frame`, the clear facts and both clocks). The rule counts only verified policy clears and the tape's claimed clears (the strict side); if
counting every claimed policy clear (and only the verified tape clears) would give a different R, an unverified clear could change R and the gate is INCOMPLETE. A replay that could not run (a process that failed to
launch or died) is a lifecycle failure, not an integrity failure: its clear stays unverified (never counted); an inexact replay of a counted clear is INVALID.

**R12. The diagnostics.** R_fine: the earliest grid point with at least 5 of 10 sticky clears at it and every later point. R_unperturbed: the earliest landing with at least 10 of 20 unperturbed clears at it and every
later landing (no tape margin: without stickiness the tape would trivially clear). The handover diagnostic: a strip start is mid-hold when the prefix's last word continues a hold (`words[tau-1] == words[tau-2]`),
else at a word change; the failure rate of each class is reported per pointer and at the final pointer. None reads into a rule branch.

**R13. Metadata.** The metadata of an M4-form episode artifact is `metadata.json` (carrying the two fields); its `actions.jsonl` rows are the M4 per-action rows (the layout `rl/run_artifacts.read_artifact`
validates) and are not objects of their own. Every other JSON, JSONL and gzipped JSON under `runs/m9_g1/` (the tree sampler's rows, the registrations, the checkpoint records, the rule) is written through the
M9 writer and carries both fields; the close audit and `verify-run` check all of them except the private runtime copies under `session/workers/` and `session/vw/` (the game's own configuration files).

**R14. Order of the Part C records.** The user's list names "approval with fresh identities", then "final source snapshot". The approval names the snapshot's digest (rd2-rd4's procedure and the proposal's 5.7), so the
snapshot is taken first and the approval is written from the freshly printed template right after it, then the preflight checks both. No identity is reused from an earlier session.

**R15. Write guard.** For the session and every worker: any write under any other directory of `runs/`, under `rl/` or under `docs/` is recorded as a provenance violation and the session is INVALID
(`rl/m8_rd2_worker.WriteGuard`, reused unchanged). The four M8 trees are additionally compared with their D: increments at the open and at the close.

**R16. What "production-count" means for the end-to-end test.** The synthetic end-to-end run uses the registered counts and caps (20 episodes per landing state, 140 tape episodes, the fine grid, 12 P2
starts, a 3,600 s training wall cap, 15,000,000 / 3,072,000 caps, 10 slots, the 4 + 6 and 2 + 8 measurement) against a synthetic world, an in-process lock-step pool and a virtual clock charged per native
tick (1,200 ticks/s). The transition cap (3,072,000) is exercised by a separate scaled test, because it would need more than ten minutes of synthetic stepping.

## 4. What is explicitly not part of g1

The final claim (50 of 100 unperturbed, 50 of 100 sticky, margin 25) is defined (`rl/m9_rule.claim_status`, `rl/m9_claim.py`) and not run. The replay browser (`replay/`) is not changed: it does not yet read the
top-level `task` and `created_utc` (a separate small change). Observation v4, imitation, M8-rd5, a second seed, a longer budget and any retry are not part of this gate. Nothing follows an outcome automatically.

## 5. Pre-launch review and the hazards fixed before launch (recorded before launch; flagged in the report)

An independent read-only review of the implementation ran before this record was frozen. It found **no blocker**. It found hazards that would have ended a correct real run INCOMPLETE (or
mis-recorded it) in cases the synthetic tests had not exercised. Each fix below makes an already registered statement (R6, R9, R10, R15) hold in the case the review found it not holding; **none changes a
registered measure, threshold, schedule, cap value, training setting, the start distribution, the reward, the observation or the rule** (`rl/m9_contract.contract_digest()` is unchanged by these fixes). They
are listed in the session report under "pre-launch fixes" because condition 6 asks for exactly that.

| id | hazard found | fix | registered statement it implements |
| --- | --- | --- | --- |
| F1 | A staging lifecycle failure in a FIXED-job phase (P2, P4, the evaluation) dropped its job, so the phase held fewer than its registered episodes and the gate ended INCOMPLETE on a failure R10 says is redrawn | `ListSource.requeue_on_lifecycle`: the same job (same id, same sticky label, hence the same keyed draws) is staged again; the per-phase limit of three lifecycle failures is unchanged (the fourth stops the phase INCOMPLETE). Training and the measurement windows still draw a fresh start | R10 ("recorded and redrawn"): for a fixed list the redraw is the same job |
| F2 | P3's 600,000-tick cap is shared by two 120 s windows; staging dominates (about 2,300 prefix ticks per start) so a window is expected to reach its half of the cap in about a minute. The cap's `CapStop` (valid) then escaped P3 and ended the whole gate INCOMPLETE although R9 calls the tick cap a valid end of a phase | each configuration's window ends at the EARLIER of its 120 s and half of the P3 cap (300,000 ticks, identical for 4 + 6 and 2 + 8); its rate is policy transitions over its elapsed window; `window_end` ("wall" or "tick_cap") and `tick_share` are recorded beside the rows. Only the tick cap is caught: a wall cap, a lifecycle limit, a dead worker or an integrity failure is still a stop. A window with no policy transition measured nothing and is ineligible (the old `0 >= 1.10 x 0` would have chosen 2 + 8); an undecided split is recorded instead of raising | R6 (a measurement of transitions per second, the pipeline fill included, both configurations alike) read together with R9 (the tick cap is a registered valid end). The window length (120 s), the total cap (600,000) and the 1.10 rule are untouched |
| F3 | A parked start whose process died was left in the ready queue (a consumer would have received a dead slot) and its prefix was credited back to the tick budget a second time | the slot leaves the ready queue; only a start still staging returns its reservation; a fixed-list job returns to the list (F1) | R9 (the budget counts what is consumed and reserved) and R10 |
| F4 | A compiled module written under `rl/` (a stale `.pyc`) is a write-guard violation (R15), and the session could be started without `-B` | preflight refuses unless Python runs with `-B`; `run` sets `PYTHONDONTWRITEBYTECODE=1`; a worker sets `sys.dont_write_bytecode`; spawned workers inherit `-B` | R15 |
| F5 | A stop left no record of what the phase had measured; a software error in the trainer left no `training_summary.json`; a worker's error carried no traceback; a broken pipe on a dead worker could escape the pool's death scan; a P2 first-step process death was recorded INVALID instead of a lifecycle failure; the approval record was not checked for the task block | partial records (`partial: true`, the reason, what was measured) for P1-P3 and a summary after a trainer error; tracebacks in the stop reason; the death scan treats a broken pipe as a death; a P2 first-step lifecycle failure is INCOMPLETE (an inexact reply stays INVALID); preflight checks the approval record's metadata | R10, R13 |

**Defects found while testing F1-F5 and fixed (same rule).** `Session.finish` and `_p3` raised on an undecided split (`list(None)`), which would have recorded a software error instead of "P3 did not
pass". The small synthetic sessions had a P3 window shorter than the staging fill, so they had measured zero transitions and chosen 2 + 8 on `0 >= 0`; their window is now 20 s (test configuration only).

**Not changed, recorded as first-contact risks.** (a) The v3 observation digest tables are built from P1's replays, which run with the verification flag set (the four diagnostics), while staging runs with the
training flags. The chain digest uses a whitelist of the reply's fields and the v3 builder reads only the named `observation` fields and the spatial and entity snapshots, so the flag sets should agree; this
cannot be shown at zero ticks. If they disagree, P2 reports a staged handover that differs from the registered tables, the gate is INVALID with no training, and the record says which digest. (b) The registered
`job_timeout_s` (900 s) is not a separate watchdog: a hung job is bounded by its phase's wall cap and the worker's own launch and step timeouts. (c) A lifecycle failure inside P1's promoted replay makes P1
INCOMPLETE, never INVALID.
