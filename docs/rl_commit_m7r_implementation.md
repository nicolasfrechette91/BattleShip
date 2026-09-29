# M7r: commitment action contract, semi-Markov learner and control-learning gate — implementation record

Status (2026-09-28): **implemented and unit-tested offline; the gate has NOT run.** No game process was launched, no
training, no native evaluation, no video; nothing committed, pushed, branched or published. Native and decomp code are
unchanged. Design: [`rl_temporal_control_design_2026-09-28.md`](rl_temporal_control_design_2026-09-28.md) (revision 3).
Selected configuration unchanged: v3 + reward v2 + Track 1; every schema default unchanged; the commitment contract is
opt-in through `[contracts].action = "btt_commit_s9_b8_m2_d6_v1"` (observation v4 + reward v2 only).

Identity: parent `48ea181` (HEAD = origin/main) + the uncommitted files below; submodules unchanged (`decomp
e4f06348`, `libultraship 805f1950`, `torch 3aa9c97`); executable `30a3913b…` (M7q, unchanged); action contract digest
`87fd62c7c8e2e7a1…` (`docs/rl_commit_m7r.schema.json`).

## 1. Files

| file | status | role |
| --- | --- | --- |
| `rl/m7r_commit.py` | new | contract (MultiDiscrete [9, 8, 2, 6], tap / hold, lengths 1-32), per-tick expansion, native boundary signatures, `CommitExecutorWrapper` (one decision → τ ticks through the unchanged Track 1 path; rollout quota), sidecar `decisions.json.gz`, `check_expansion`, contract description / digest |
| `rl/m7r_worker.py` | new | worker stacks (v4 stack + optional per-tick `GateTraceWrapper` and eval-metrics recorder + executor), `M7rWorkerWrapper` (idle replies once the quota is used up; per-decision info), factories, `m7r_contracts` |
| `rl/m7r_ppo.py` | new | `smdp_gae`, `SMDPDictRolloutBuffer` (per-environment variable-length sequences, exactly k minibatches per epoch), `CommitPPO` (native-tick rollouts and `num_timesteps`, idle replies never stored, per-rollout accounting) |
| `rl/m7r_analysis.py` | new | exact ST1 / PR1 / RE1 / T from gate traces, 90 % bootstrap, rule `m7r_gate_rule_v1`, self-test |
| `rl/m7r_gate.py` | new | gate driver: `status`, `preflight`, `approval-template`, `run` (blocked without an APPROVED record and a covering PASS backup); phases P1-P5 with measured wall times |
| `rl/m7r_tests.py` | new | 13 offline unit cases (sections 2-4) |
| `rl/tools/runs_backup.py` | new | independent verified backup of `runs/` (copy, source re-hash, backup hash, inventory comparison, PASS / FAIL record, launch coverage check) |
| `rl/configs/m7r/m7r_s{0,1,2}_{commit,tick}.toml` | new | the six gate profiles (arms of a seed differ only in `contracts.action`, name, notes) |
| `docs/rl_commit_m7r.schema.json` | new | machine-readable contract |
| `rl/experiment_config.py` | modified, additive | the commitment contract as a second `contracts.action` choice, its cross-field rules, a summary block only for it |
| `rl/m7_trainer.py` | modified, additive | `M7Config.action` (Track 1 default, omitted from Track 1 `run.json`), opt-in branches for contracts, worker factory, `CommitPPO`, model annotation, network identity, rollout accounting, `run_meta["commit"]` |
| `rl/m7_evaluation.py` | modified, additive | `EvaluationSettings.action` / `gate_trace` (defaults None / False); a commitment checkpoint is loaded as `CommitPPO` and evaluated through its executor |
| `rl/m7g_k_tests.py` | modified, one token | `m7r` added to the Phase K profile-scan exclusion (as M7p / M7q did) |
| `docs/rl_temporal_control_design_2026-09-28.md` | revision 3 | the approved design |

## 2. Contract equivalence (what the tests establish)

| requirement (decision 2) | evidence | result |
| --- | --- | --- |
| duration 1 reproduces every Track 1 native controller word | `unit_duration_one_is_track1`: all 72 (stick, button) pairs × both modes with d = 1 through the executor | the submitted word equals the Track 1 word, one tick, the tick's own reward and observation (144 / 144) |
| d = 1 on real native data | `unit_real_replies`: the eight pinned Track 1 artifacts replayed as d = 1 decisions over their recorded native replies | every word identical over all 27,521 ticks; sidecars pass the expansion check |
| no release or other hidden input at an option boundary | `unit_no_hidden_input`: 60 randomised native-reply scripts (class / ground / apex / hitlag / target changes), random options of every mode and length, 20 with a rollout quota | 11,431 ticks, 3,190 options: the submitted words and option lengths equal an independent reference expansion; every option's first tick is the tick after the previous option's last; quota cuts exact; a step after the quota raises (the worker answers idle, sending nothing) |
| boundaries and tick-1 suppression | `unit_boundaries`: 13 cases (each boundary, non-boundaries: falling without apex, grounded, hitlag start, non-live reply; simultaneous order; a tick-1 status change does not end the option, a tick-4 one does) | as specified |
| options over real boundaries | `unit_real_replies`: the recorded words regrouped greedily into the longest valid options under the contract's own boundary rule, executed over the recorded replies | every word reproduced in all eight traces (e.g. 3,361 ticks as 157 options, mean 21.4 ticks, ending on class changes, apexes, target breaks, hitlag ends and max length); expansion check clean |
| the real observation builder under the executor | `unit_real_stack`: the real `EntityObsV4Wrapper` fed the recorded replies through a fake client, under `GateTraceWrapper` and the executor, against the per-tick v4 stack | four traces, 13,121 ticks: the observation at every decision point is bit-identical to the per-tick stack's at that tick; flat 626; gate-trace rows equal rows computed directly from the replies; expansion check clean |
| replay truth and the sidecar | `unit_sidecar_expansion`: the executor's sidecar vs the canonical words; five mutations (a length, a word, an extra tick, a relabelled boundary, a rollout cut in an evaluation record) | exact record: no problem; every mutation detected |
| R kept, no A+Z action | contract description and `unit_contract_identity`: button table = Track 1 (R = 0x0010); nvec [9, 8, 2, 6] | no combined button exists; the game folds R |

## 3. Semi-Markov learner and native-tick accounting (decisions 3-4)

| check | evidence | result |
| --- | --- | --- |
| τ = 1 is SB3's per-tick PPO | `unit_gae`: `smdp_gae` vs SB3's `RolloutBuffer.compute_returns_and_advantage`, 3 environments × 64 steps with episode ends | max difference 1.9e-6 (float32) |
| τ > 1 | `unit_gae`: λ = 1 gives the discounted return with the γ^τ bootstrap; λ = 0 the one-step semi-Markov TD | exact to 1e-4 |
| equal native ticks, 100 gradient steps, idle replies not stored | `unit_commit_ppo`: `CommitPPO.learn` on a fake commitment vector environment (v4 space, falls, horizon truncations, a quota, idle replies), 2 envs × 128 ticks, 8 minibatches × 2 epochs | `num_timesteps` = 768 native ticks; every rollout exactly 128 ticks per env; 16 gradient steps per rollout at 41 / 29 / 44 decisions (minibatches of 3-6); optimizer samples = decisions × epochs; 3-7 idle replies per rollout, none stored |
| idle replies send nothing | `unit_worker_idle`: `M7rWorkerWrapper` with an exhausted executor | the environment is not stepped; reward 0, not done, the cached observation |
| accounting logged | `rl/m7_trainer.py` writes `commit_accounting` into every C rollout row (native ticks, decisions per env, τ histogram and mean, `d` / mode usage, end reasons, idle replies, minibatch sizes, gradient steps, optimizer samples, cumulative); the gate driver derives the per-tick arm's record (5,120 decisions, 512-sample minibatches, 100 steps) and checks it against SB3's `n_updates` | implemented; exercised offline by `unit_commit_ppo` |

The per-tick γ and λ keep the baseline's credit horizon (1,000 / ≈167 ticks); they do not solve delayed credit across
a long crossing (design section 4).

## 4. Configuration, profiles and defaults

- All 69 pre-existing profiles resolve identically under HEAD's and the modified `experiment_config.py` (summary,
  compatibility view, semantic view, resolved JSON, native flags; scratch comparison script, not in the repository).
- The six gate profiles pass `rl/train_m7.py --dry-run`; within a seed the arms differ exactly in `contracts.action`,
  `run.name`, `run.notes` (`unit_config`); a commitment profile with observation v3, reward v1 or a 1,800-tick horizon
  is refused; a Track 1 `M7Config.to_json` gains no key; `EvaluationSettings` defaults are unchanged
  (`unit_evaluation_defaults`).
- Compatibility fingerprints: commit `353ede8b…`, per-tick `7a3233e5…` (identical across seeds within an arm).

## 5. Tests run (Python only; no game process)

| suite | result | note |
| --- | --- | --- |
| `python rl/m7r_tests.py unit` | **13 / 13 PASS** | sections 2-4 |
| `python rl/m7r_analysis.py self-test` | **14 / 14 PASS** | rule outcomes and boundaries; the exact ST1 / PR1 / RE1 / T arithmetic on a synthetic trace |
| `python rl/m7q_tests.py unit` | 9 / 9 PASS | v4 contract and oracle unchanged |
| `python rl/m7n_tests.py unit` | 10 / 11 | the one failure, `unit_matrix`, is the pre-existing M7n pre-launch check ("campaign directories must not exist"); it has failed since the M7n campaign ran (2026-09-27), as the M7q record states; unrelated to this change |
| `python rl/m7g_obs_tests.py unit` | 8 / 8 PASS | |
| `python rl/m7b_config_tests.py` | 16 / 16 PASS | |
| `python rl/m7g_k_tests.py unit` | 6 / 6 PASS | with `m7r` excluded from its pinned-profile scan |
| profile regression (scratch) | 69 / 69 identical | section 4 |
| `python rl/m7r_gate.py preflight` (full, after the backup) | refuses, as intended | every check passes (profiles, m7r unit suite 13 / 13, analysis self-test, backup coverage 377,359 / 0 uncovered, no game process, executable) except the one deliberate block: no approval record |
| `py_compile`, `git diff --check` | clean | |

Every suite ran with its output root in the session scratch directory; the real-data cases read `runs/` only. Existing
campaign drivers (M7n, M7o, M7p) will report manifest drift because `rl/*.py` changed; their frozen evidence is
byte-unchanged (as after M7q).

## 6. The independent backup of `runs/` (decision 7)

| item | value |
| --- | --- |
| tool | `rl/tools/runs_backup.py` (`btt_runs_backup_v1`, sha256 `c4de9b0a…`, the exact text that ran; standard library only) |
| source | `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip\runs` (disk 0), only read |
| backup | **`D:\BattleShip_runs_backup\2026-09-28\runs\`** on disk 1 (a separate physical SATA disk), with `manifest.tsv.gz` (sha256, size, mtime, relative path of every file; manifest sha256 `a004a26e776e447e…`), `junctions.tsv.gz` (the 46,773 reparse points listed, never followed or copied), `backup_run.json`, **`verification.json`** |
| regular files / bytes | **377,359 / 16,968,155,612** (source, manifest and backup identical) |
| verification | **PASS** at 2026-09-28T20:44:33Z: the source inventory walked again equals the manifest (paths, sizes, mtimes); every source file re-hashed from C:, every backup file hashed from D:, all three hashes equal (**0 mismatches**); the backup inventory equals the manifest (no missing or extra file, equal sizes, no reparse point); no unreadable entry. Verify wall 2,079 s; copy wall 1,486 s (358,472 copied, 18,887 kept identical from an interrupted first attempt, whose 6 leftover temporary files were removed from the backup tree only) |
| launch check | `check-coverage` after all tests: PASS, 377,359 source files, 0 new or changed |
| not claimed | protection against the loss of the whole machine (same machine; an off-machine copy can follow) |

The first attempt wrote each file with a forced flush (about 50 files/s on the HDD) and was stopped after ~17,000 files;
the tool was changed to buffered writes (integrity rests on the independent read-back verification, not on the copy
step) and rerun incrementally. The source was never written.

## 7. The gate driver (implemented, not run)

`python rl/m7r_gate.py run` refuses unless `preflight` passes: the six profiles valid, no gate run directory yet, the
m7r unit suite and the analysis self-test pass, `rl/tools/runs_backup.py check-coverage` PASS for every regular file
under `runs/` at launch, no BattleShip process, the executable present, and **an APPROVED record at
`docs/rl_commit_m7r_gate_approval.json` whose rule id, contract digest, executable hash and code hashes equal the
current ones** (`approval-template` prints the record to review; nothing creates it). Phases: P1 live `d = 1` identity
(27,521 ticks), P2 training (6 × 307,200), P3 evaluation (≤ 1,296,000), P4 verification (expansion of every C
episode, exact replays of 2 final stochastic episodes per run with per-tick trace equality, discovery candidates and
clears), P5 analysis once. Discovery replays (clears first, then candidates, over all seeds) are capped at
`DISCOVERY_REPLAYS_MAX = 20` by a shared counter, added before approval so the documented 72,000-tick bound is enforced
rather than assumed; anything beyond the cap is listed as not replayed and never counted as a discovery (prior M7n/M7p
evaluations had 3 candidates in about 6,000 episodes). Measured wall times of every phase are written to `runs/m7r/gate/_gate/state.json`; no
runtime is claimed in advance.

## 8. Remaining risks (what is not established)

- **No live path has run.** The game-backed pieces — the executor inside a real `M7SubprocVecEnv` worker (quota via
  `env_method`, idle replies, pickled infos), standby promotion under the executor, sidecars and gate traces written
  by the real tracker, `M7Run` end to end with `CommitPPO` (checkpoints, callbacks, the stop request), `CommitPPO.load`
  in evaluation, the driver's P1 / P4 functions — are covered by unit tests with fakes and by code review only. The
  gate's P1 identity check and its per-run verification are the first live exercise; P1 stops the gate on a mismatch.
- Throughput and memory of the commit arm are unmeasured (fewer policy calls, but the v4 builder still runs every tick).
- Training runs cut the option at each environment's 1,024-tick quota (at most one extra decision point per
  environment per rollout); evaluation never does. The first rollout of an episode that spans rollouts therefore sees
  a decision boundary that evaluation would not.
- PR1 limits (design 5.1): a press accepted a tick later counts as ineffective; a same-tick animation-end status change
  counts as effective; Z and tornado B presses are excluded. On the eight pinned v1-policy traces PR1 is 0.05-0.11 for
  stochastic play and 0.17-0.52 for the two deterministic ones (illustrative only).
- Decision 6 is implemented as **both** ST1 and PR1 improving (against the trained per-tick control and the own
  untrained policy) **in the same seed, in at least two seeds**. If the intended reading was "each measure in at least
  two seeds, not necessarily the same", it is a one-line change of `decide()` to confirm before the gate.
- 30 stochastic final episodes per run: the intervals are wide and the gate is exploratory by design.
- The class table behind the boundaries is validated for Mario only; the hold mode exists for multi-jump characters
  but no other character is onboarded.
- Idle vector steps update SB3's never-applied return statistics (`ret_rms`) with zero rewards (normalisation off).
- In gate evaluations the Phase K eval-metrics recorder sits below the executor (it reads one reply per `step`); for the
  per-tick arm it sits below `EpisodeStatsWrapper` instead of above it — transparent per tick, noted for provenance.
- The backup is on another disk of the same machine (section 6). Any file added to `runs/` after it (the gate's own
  outputs included) needs the incremental backup before any later run; the driver refuses otherwise.

