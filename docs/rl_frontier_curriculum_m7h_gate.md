# RL M7h: implementation through the E1–E7 / R1–R3 review gate

Status (2026-09-24): **implemented and checked up to the review gate. E1–E7 and R1–R3 all pass. Stopped for
review.**
- The three-seed curriculum campaign was not started.
- Nothing was committed or pushed.

The design is [`rl_frontier_curriculum_m7h_proposal.md`](rl_frontier_curriculum_m7h_proposal.md) (revision 2). The
machine-readable record is [`rl_frontier_curriculum_m7h_gate.json`](rl_frontier_curriculum_m7h_gate.json), and the raw
outputs are under `runs/m7h/_gate/` (git-ignored).

## 0. Summary

- **Registered settings, implemented and pinned by the schema:**
  - curriculum selection 50/50, **only after an automatic reset inside `step()`**; every worker's initial episode is an
    ordinary tick-0 start;
  - prefixes of at most 3,000 ticks, and a 60-tick pre-fall exclusion;
  - the M7f cell key;
  - launch gates: available commit ≥ 10 GiB and available physical ≥ 4 GiB;
  - in-run policy on available commit: warn below 4 GiB, cooperative stop below 3 GiB, emergency kill below 1 GiB
    (2-s probe);
  - atomic checkpoint-set writes, for all runs.
- **The reset contract holds.**
  - Every `reset()` returns the tick-0 observation and consumes nothing. This was checked on every episode of the
    curriculum smoke and in 200 replays.
  - The prefix phase is a separate worker command (`run_prefix_phase`). A VecEnv wrapper below VecNormalize sends it
    after the automatic reset and before PPO's next action.
- **The historical v1 control can be reused (R1–R3 all pass):**
  - curriculum off reproduces M7e `ckpt_000102400` bit for bit for seeds 0, 1 and 2;
  - the 600 historical final-evaluation episodes re-evaluate identically;
  - the rule inputs equal the Phase K values.
- **Found and fixed during the gate** (section 6):
  - the inherited training monitor assumed tick-0 starts; its first curriculum episode raised a hard alert, which
    correctly stopped the run;
  - an empty `[curriculum]` table was silently accepted;
  - E3's first fault configuration was too slow;
  - two of my comparisons gave a false result.

  Each first outcome is preserved.

## 1. What was implemented

**New files** (about 2,900 lines):

| File | Content |
| --- | --- |
| `rl/m7h_curriculum.py` | pure logic: cells, `EpisodeTrace` and the episode report, archive (first reach on policy rows, strictly-shorter replacement, per-episode policy-row visits, eligibility, lineage exposure, persistence), `Selector` (own seeded generator), discovery classes, digests |
| `rl/m7h_worker.py` | `CurriculumWorkerWrapper` (outermost worker wrapper, built only when the curriculum is on) and its picklable factory: the trace, the episode report, `run_prefix_phase` (freshness preconditions, replay through `M7BattleShipBTTEnv.step()`, recording in the episode's own recorder and digest, end-observation check, reward rebase, lifecycle-failure path) |
| `rl/m7h_vec.py` | `CurriculumVecEnv` (VecEnvWrapper between `M7SubprocVecEnv` and VecNormalize): ingest, then select, then dispatch in parallel, then deliver, only for done envs; checks that rewards, dones and terminal observations are unchanged on every call; checkpoint persistence of the archive and selector |
| `rl/m7h_guard.py` | launch gate (10 / 4 GiB), 2-s probe, cooperative stop → CTRL_BREAK after 30 s → kill (below 1 GiB, or 240 s after CTRL_BREAK), provenance scan (`stop_record.json`), move to `_partial/` (never deleted), E7-only `DrillOverride` |
| `rl/m7h_run.py` | the gate driver: `gate`, `e1`–`e7`, `r1`–`r3` |
| `rl/m7h_tests.py` | E1, 13 unit tests |
| `rl/configs/m7h/gate/*.toml` | R1 profiles (seeds 0–2, 102,400, no curriculum); the E4, E5 and E7 smoke profiles |

**Inherited files** (284 lines added, 19 removed in total):

| File | Change | Active with the curriculum off? |
| --- | --- | --- |
| `rl/experiment_config.py` | optional all-or-nothing `[curriculum]` table (values pinned; v1 only; never resumed; an empty table is rejected) | no; profiles without it resolve exactly as before (the Phase K `experiment_resolved.json` files re-resolve identically) |
| `rl/m7_trainer.py` | `M7Config.curriculum`; the curriculum factory; the wrapper attached after the pinned `VecNormalize(self.venv, …)` literal; **atomic checkpoint sets** (`.<name>.incomplete`, then renamed); **cooperative stop** (`STOP_REQUEST.json` checked after every vector step); update-boundary snapshots; interrupted-set provenance | only the atomic writes, the stop check and the snapshots (no effect on training; R1 proves it) |
| `rl/btt_parallel.py` | `M7RewardWrapper.rebase_for_policy_phase`, `M7EpisodeTracker.note_prefix_step` | no (called only by the prefix phase) |
| `rl/m7_vec_env.py` | `env_method_each` (per-worker arguments, sent in parallel) | no |
| `rl/m7d_run.py` | `validate_episode_row` accounts for `m7h.prefix_length` / `prefix_targets_broken` (section 6) | rows without the block are checked exactly as before (7,921 historical rows re-checked: 0 violations) |
| `rl/train_m7.py` | status `stopped` exits 130 like `interrupted` | no |
| `rl/m7g_k_tests.py` | `unit_existing_profiles` also excludes the new `rl/configs/m7h/` directory (the pinned-profile checks are unchanged) | test only |

**The contract as built**:
- VecNormalize receives exactly one observation per env per vector step. Its count stays `ε + n_envs + num_timesteps`.
- Prefix steps are never VecEnv steps, so PPO never counts, stores or scores them.
- The reward reference is rebased on the post-prefix observation.
- The 3,600-tick horizon counts prefix plus policy steps.
- The next standby starts booting inside the reset, before the prefix runs. Standbys are never stepped.

**Deviation from revision 2** (recorded here, not decided):
- The prefix/policy boundary is recorded in the artifact label `m7h_start` (`prefix_length`, prefix digest,
  provenance, `o_0`, `o_L`), not as a per-row `phase` field.
- The row format is therefore unchanged, and the existing reader, `verify_artifacts` (consumed ticks 0 … n−1 from a
  tick-0 observation) and the M7f replay tools accept curriculum artifacts as they are.
- A prefix-phase lifecycle failure's summary goes to the worker's `m7h_prefix_failures.jsonl`, not to `episodes.jsonl`.

## 2. R1–R3: reusing the historical v1 control

| Check | Result |
| --- | --- |
| **R1 training** (curriculum off, 102,400 transitions, on the final working tree) | seed 0 `5cec5fc4…/050acde9…`, seed 1 `56241d22…`, seed 2 `5177b527…`: final policy and statistics digests **equal** M7e `ckpt_000102400`; training rows equal in order **and number** (30 / 27 / 29); no curriculum trace anywhere (no `m7h` row keys, no `curriculum` config / summary / compatibility keys, no `curriculum/` directory, no `m7h_start` artifact labels, no extra files or interruption blocks in `final/`, no `.incomplete` directories); executable `1e7c62a0…`. First pass (before the section-6 `m7d_run` edit) also passed; kept as `results/r1_s*__first_pass.json`. |
| **R2 evaluation** (the three historical `m7g_s{0,1,2}_v1/final` sets, Phase K final protocol, `SSB64_RL_TARGET_DIAG=1`) | **600 / 600** episodes equal on `(native_action_digest, targets_broken, end_reason, full btt_eval_metrics_v1 record)`, keyed by `(mode, rank, worker_episode)`; 766 / 694 / 685 s |
| **R3 rule inputs** | k = χ = 0; T = 118/25, 19/4, 427/100 (= 4.72, 4.75, 4.27); falls 1 / 1 / 0; identical to the registered Phase K values |

After R2, no evaluation-path code changed; the only later edits are `m7d_run.validate_episode_row`, the driver and the
tests.

## 3. E1–E7: the engineering checks

| # | Result |
| --- | --- |
| **E1** | 13 / 13 unit tests, listed below this table. |
| **E2** | static guard clean (4 training-path modules, 11 forbidden path fragments; the evaluator has no M7h reference); **1,165 / 1,165** archive entries trace to this run's own episodes, and each full digest equals the source row's; every prefix digest was recomputed from the preserved source artifact; a 10-episode evaluation of the E4 final set: all artifacts start at tick 0 and none carries `m7h_start` |
| **E3** | **200 / 200** archived prefixes (L 1–2,978, mean 1,031.5) replayed exactly through `run_prefix_phase` in the real worker path: 173 standby-promoted, **24 cold-fallback**, 3 cold starts; `host_frame` equal 200 / 200; median 1,094 ticks/s. Negative controls: a corrupted end observation was **refused**; a game process killed 0.3 s into a prefix gave `tick0_after_prefix_lifecycle_failure` with a fresh non-consuming tick-0 episode and one failure-log line. **20 / 20** finished curriculum episodes re-replayed exactly from tick 0 with the M7f tools. |
| **E4** | curriculum on, 102,400 transitions (listed below this table) |
| **E5** | two identical 51,200 runs: identical checkpoint digests (`ce5f9973…/28f4d05e…`), 19 rows, 857 archive cells, identical prefix bytes, 51 selection events; E4's `ckpt_000051200` equals the E5 final. Excluded as identity or timing: episode ids (timestamp + uuid), run names and wall-clock fields. |
| **E6** | end-to-end 824.0 vs 1,069.6 transitions/s (curriculum off, R1 s0): **ratio 0.77** (floor 0.5); prefix rate 1,397 ticks/s in the worker, stall 0.83 s per dispatch step (max 1.92 s); projected training time for 3.072M: **62.1 min** scaled from E4, **74.4 min** worst case (740 starts of 3,000 ticks), limit 75; commit draw 5.08 GiB on vs 5.02 off |
| **E7** | three drills (the probe level was simulated after 12 logged rollouts; the real probe ran throughout; see section 4) |

**E1, the 13 unit tests:**
- codec, cells and digests;
- discovery classes and the trace;
- the archive;
- the selector (60,000 draws: p0 0.4965; weight shares within 4σ);
- **`CurriculumVecEnv` inside a real VecNormalize:**
  - `reset()` never selects;
  - a prefix only follows an automatic reset;
  - rewards, dones and terminal observations are unchanged;
  - the statistics equal an exactly-once replay of the returned observations;
  - selection is deterministic;
- the reward rebase;
- the real worker stack refuses a non-fresh prefix phase;
- atomic checkpoint sets;
- interruption provenance and the cooperative stop;
- prefix-aware row invariants;
- memory-policy levels;
- configuration and the control path (importing the trainer imports no M7h module; the pinned source-guard strings
  are intact);
- the isolation guard.

**E4, curriculum on, 102,400 transitions — zero violations in every check:**
- **Starts:** 41 finished episodes, 24 of them curriculum starts; 46 starts in all (5 initial, 15 tick-0, 26 prefix).
- **Reset contract:** held for 41 / 41 episodes, and every first row consumed tick 0.
- **Rows and digests:** consumed ticks and digests correct; L + policy steps equals the rows, ≤ 3,600; horizon rows
  = 3,600.
- **Returns:** return = the policy-only closed form; prefix breaks unrewarded.
- **PPO steps:** equal the VecEnv steps between automatic resets (41 / 41).
- **VecNormalize:** statistics equal an exact replay of all **102,405** returned observations.
- **Delivered observations:** every checked curriculum start (24) delivered the archived `o_L`, never `o_0`.
- **Artifacts:** 41, contiguous from tick 0, prefix and full digests recomputed.
- **Inherited check:** `verify_training_run` reports no problem.
- **Archive:** 1,165 cells, 986 eligible, 30,273 prefix ticks.

## 4. Low-memory interruption: provenance and E7

**What an interrupted or stopped set records.** Its `checkpoint.json` carries an `interruption` block. The block
never claims a completed-update checkpoint: `completed_update_checkpoint: false`. It records each component separately:
- **policy parameters:** `last_completed_update` only when the digest equals the snapshot taken at the last update
  boundary and the stop came during collection; otherwise `possibly_mid_update` or `unverified`;
- **num_timesteps:** at the stop, and at the last completed update (the difference is the partial rollout);
- **VecNormalize statistics:** `advanced_through_partial_rollout`, with the boundary statistics saved separately as
  `obs_rms_update_boundary.pkl`;
- **workers:** advanced into the partial rollout; in-flight episodes are preserved as `aborted` artifacts.

The guard adds `stop_record.json` (kind, events, probe crossings, exit code, and a scan of every set, every
`.incomplete` directory, rows and artifacts) and moves the run to `_partial/`.

| Drill | Outcome |
| --- | --- |
| **cooperative** (stop below 3 GiB) | stopped at t = 62,580, 1,140 steps into a rollout after the update at 61,440; policy `last_completed_update`, and the `model.zip` digest equals the boundary digest; statistics count 62,585.0001 (advanced) vs the boundary file's 61,445.0001; `ckpt_000000000` and `ckpt_000051200` complete and hash-valid; `interrupted/` complete; 5 in-flight episodes preserved `aborted` (3 of them curriculum starts); 24 rows, no torn tail; exit 130; no process left; moved to `_partial/` |
| **fallback** (request ignored, CTRL_BREAK after 15 s) | KeyboardInterrupt during collection at t = 77,820 (boundary 76,800): policy `last_completed_update` (verified from the file); the same preservation, and `interrupted` recorded as the kind |
| **emergency** (below 1 GiB, kill) | killed; exit 1; no `interrupted/`, no summary; both periodic sets complete and hash-valid; no `.incomplete` directory; 24 complete rows, 0 torn bytes; the kill-on-close job removed all 10 games (the 15-s monitor briefly saw them orphaned); moved to `_partial/` |

The `possibly_mid_update` branch was exercised only by E1; neither live interrupt happened to land during an update.

## 5. Commands and outcomes

- **Commands:** everything was run from the repository root.

  ```
  python rl/m7h_run.py gate       -> ok (commit 16.95 GiB, physical 5.30 GiB at the first launch)
  python rl/m7h_run.py r1         -> r1_s0 / r1_s1 / r1_s2 PASS (final working tree; first pass also PASS)
  python rl/m7h_run.py r2         -> r2_s0 / r2_s1 / r2_s2 PASS (600 / 600)
  python rl/m7h_run.py r3         -> PASS
  python rl/m7h_run.py e1         -> 13 / 13
  python rl/m7h_run.py e4         -> PASS (second attempt; see section 6)
  python rl/m7h_run.py e5         -> PASS (runs trained once; comparison re-run with --compare-only)
  python rl/m7h_run.py e2         -> PASS (the evaluation ran once; the check was re-run)
  python rl/m7h_run.py e3         -> PASS (second attempt)
  python rl/m7h_run.py e6         -> PASS
  python rl/m7h_run.py e7         -> PASS (3 / 3 drills)
  ```

- **Regression suites** (unit cases):
  - `m7b_config_tests` 16 / 16;
  - `m7c_standby_tests` 4 / 4;
  - `m7d_tests` 9 / 9;
  - `m7e_tests` 10 / 10;
  - `m7f_tests` 5 / 5;
  - `m7g_k_tests` 6 / 6, after the one-line scope fix in section 6;
  - `m7g_k_campaign_tests` 6 / 13 against the frozen Phase K manifests, and 12 / 13 against a manifest built for the
    current tree (scratch wrapper, output under `runs/m7h/_gate/regress/`). The frozen manifest was not modified
    (sha256 `9a58f03b…` before and after).

  Every campaign-suite failure comes from the frozen manifests: `docs/rl_obs_v2_phase_k_manifest_m7g.json` and
  `runs/m7g_k/_matrix/manifest.json` record HEAD `afa42fc` and the Phase K code fingerprint. HEAD has been `78e56f4`
  since the Phase K commit, so the drift, provenance and dry-run cases fail even on a clean checkout. The remaining
  case (`unit_dry_runs`) reads the campaign's own frozen manifest.
- `git diff --check` is clean. No BattleShip process remains.
- **Machine time:** R1–R3 about 41 min (R2's evaluations ran about 11–13 min per seed); E1–E7 about 24 min, including
  both abandoned attempts.

## 6. Found during the gate (every first outcome is preserved)

1. **The training monitor assumed tick-0 starts.**
   - `m7d_run.validate_episode_row` (used by the live Monitor and by `verify_training_run`) assumes four things: a
     horizon episode has 3,600 policy steps; terminal targets = 10 − rewarded breaks; a clear has 10 rewarded breaks;
     break ticks lie below the step count.
   - The first curriculum episode (L 1,840, 2 prefix breaks) raised a hard alert. The guard stopped the run correctly
     and moved it to `_partial/m7h_e4_on_s0__20260924T141524Z`.
   - Fixed: the function reads `m7h.prefix_length` and `prefix_targets_broken`, which are 0 for every tick-0 and
     historical row.
   - Verified: 7,921 historical rows give 0 violations, and there is a new E1 test. E4 was re-run.
2. **An empty `[curriculum]` table meant no curriculum.** TOML flattening drops an empty table, so it was silently
   accepted. It is now rejected.
3. **E3's first cold-fallback fault was too slow.**
   - A port-squat fault made each failing standby wait out the 20-s startup timeout, about 75 s per reset.
   - That attempt was stopped: its process was killed, and the job object removed the games.
   - It was moved to `_partial/e3__first_attempt_slow_fault` and replaced by the existing fast `startup_timeout`
     fault.
4. **Two of my comparisons were wrong.**
   - E5 at first compared episode ids and run names, which are unique by construction.
   - E2 at first matched the text `m7h` inside artifact paths.
   - Both comparisons were fixed; the first outcomes are `results/e5__first_compare.json` and
     `results/e2__first_check.json`.
5. **`m7g_k_tests.unit_existing_profiles`** pinned the set of every profile outside `m7g/`. It now also excludes
   `m7h/`, and all its pinned-fingerprint checks pass unchanged.
6. **Observation, no change made.** During the final R1 runs, available *physical* memory dipped to 3.2–3.5 GiB.
   That is below the 4 GiB *launch* gate, but the registered in-run policy watches commit, which stayed at 10.4 GiB or
   more. No stop was due.

## 7. Not done (outside this gate)

- The three-seed campaign.
- The campaign profiles `m7h_f_s{0,1,2}`.
- The campaign drivers (matrix, `decide()` for the registered rule, census), and the wiring of the guard and launch
  gate into them.
- Every item above needs the next approval.

## 8. Working tree (not committed)

- **Modified:**
  - `rl/btt_parallel.py`, `rl/experiment_config.py`, `rl/m7_trainer.py`, `rl/m7_vec_env.py`, `rl/m7d_run.py`,
    `rl/train_m7.py`, `rl/m7g_k_tests.py`;
  - `docs/rl_obs_v2_phase_k_comparison_m7g.{md,json}` (Addendum A, earlier);
  - `docs/rl_frontier_curriculum_m7h_proposal.md` (staged by the user; working copy unchanged since).
- **New:**
  - `rl/m7h_{curriculum,worker,vec,guard,run,tests}.py`;
  - `rl/configs/m7h/gate/` (6 profiles);
  - `docs/rl_frontier_curriculum_m7h_gate.{md,json}`.
- **Unchanged:** submodules (decomp `3c7fd5d05`, libultraship `805f1950`, torch `3aa9c97`) and the executable
  (`1e7c62a0…`).
