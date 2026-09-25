# RL M7h: campaign readiness

Status (2026-09-24): **the campaign is prepared and every launch and analysis path is dry-run tested. It is not
started.** One registered precondition is still open: the R1–R3 control check must be re-run on the frozen campaign
code (section 8). Nothing was committed or pushed.

- Design and rule: [`rl_frontier_curriculum_m7h_proposal.md`](rl_frontier_curriculum_m7h_proposal.md) (revision 2).
- Gate result: [`rl_frontier_curriculum_m7h_gate.md`](rl_frontier_curriculum_m7h_gate.md) (accepted; unchanged).
- Registered for the campaign:
  - manifest: [`rl_frontier_curriculum_m7h_manifest.json`](rl_frontier_curriculum_m7h_manifest.json);
  - decision rule: [`rl_frontier_curriculum_m7h_decision_rule.json`](rl_frontier_curriculum_m7h_decision_rule.json).
- Machine record: [`rl_frontier_curriculum_m7h_readiness.json`](rl_frontier_curriculum_m7h_readiness.json).
- Raw outputs: `runs/m7h/_readiness/` (git-ignored).

## 0. Summary

| Item | Result |
| --- | --- |
| 1. Phase K campaign tests | Cause found: the frozen manifests record the Phase K launch commit (`afa42fc`). Test isolation fixed. 13 / 13 pass on the current tree and in a clean checkout of HEAD. The frozen manifests and the Phase K state are byte-identical. |
| 2. Prefix-row identification | One gap found and fixed; the row format is unchanged. The proof passes across capture, replay, training diagnostics and analysis: 7 runs, 157 rows, 173 artifacts, 12 fresh tick-0 replays, 1 game test, 6 tamper cases. |
| 3. Campaign | Built: 10 profiles, the manifest, the driver `rl/m7h_campaign.py`, the evaluation plan (2,955 episodes), the machine-readable rule, and control reuse re-verified at launch. |
| 4. Resource gates | Tested at every boundary. The 3.2–3.5 GiB physical dip is reproduced and reported. The thresholds are unchanged. |
| 5. Dry runs | Every launch and analysis path, synthetic records, 14 / 14 cases. The real campaign root: the only blocker is the control check. |

**Correction to my previous report.** In the gate hand-off message I wrote "6 of 13 fail" for the Phase K campaign
suite. The gate record is right: 6 of 13 **passed**, so **seven** cases failed.

## 1. The Phase K campaign-test failures

**The seven failing cases:**
- `unit_manifest`
- `unit_drift_detection`
- `unit_dry_runs`
- `unit_partial_and_resume`
- `unit_pilot_gating`
- `unit_checkpoint_provenance`
- `unit_analysis`

### 1.1 Cause

- The frozen manifest (`docs/rl_obs_v2_phase_k_manifest_m7g.json` = `runs/m7g_k/_matrix/manifest.json`, sha256
  `9a58f03b…`) records HEAD `afa42fc`, the commit the campaign launched on, and code fingerprint `78ee37f6…`.
- Every launch path first compares the checkout with that manifest.
- On any checkout after the Phase K commit (`78e56f4`), the manifest drift is non-empty. Each of the seven cases
  then fails for that reason alone:
  - the manifest and drift cases assert "no drift";
  - the dry-run, partial / resume, pilot and analysis cases are blocked by it;
  - the provenance case builds sets that record the current HEAD.

### 1.2 Evidence

**Clean checkout of HEAD** (a detached worktree of `78e56f4` in the scratch directory, since removed):
- The same seven cases failed. Two more failed for environment reasons: the uninitialized decomp submodule and the
  runtime files missing next to the copied executable. Copying those files cleared both.
- Drift was HEAD and code.
- The code drift is line endings only:
  - In the campaign tree, one module (`rl/m6_raphnet_bypass_regression.py`) was CRLF; its committed blob is LF.
  - With that file's campaign bytes restored, the code fingerprint equals `78ee37f6…` exactly and the drift is **HEAD
    only**. The same seven cases still fail.

**Current tree:** drift is HEAD and code (the M7h modules). A manifest built for the current tree gave 12 / 13.
`unit_dry_runs` still failed, because it reads the real root's frozen copy.

**Latent note, not changed:** the fingerprints are byte-level. With this repository's `core.autocrlf=true`, a fresh
clone checks files out as CRLF, which changes every profile sha256 and the code fingerprint.

### 1.3 Fix: test isolation only

No production code changed, and the frozen manifests and historical results are untouched.

**`rl/m7g_k_campaign_tests.py`:**
- **Temporary roots** are seeded with a manifest built for the tree under test, by `km.build_manifest()`, the
  `manifest` command's own function. Every drift and provenance check runs in full against it.
- **Archived-campaign checks** (strengthened; none removed):
  - the frozen manifest is byte-identical to the recorded sha256 and equal to the `runs/` copy;
  - it is internally consistent (pinned profiles, proofs, census, digests);
  - its drift on this checkout is only HEAD (a descendant of `afa42fc`) and, if `rl/` changed, the code. The
    executable, the submodules and every profile must still match, so a relaunch is refused;
  - mutation checks prove that this filter still catches executable, submodule and profile drift.
- **The current-tree manifest** must equal the frozen one in every contract field: runs, fingerprints, untrained
  digests, proofs, census, rule, limits and directory plan. Only `created_utc`, `revisions`, `code` and
  `directory_plan.existing` may differ. Result: equal.
- **`unit_dry_runs` is split into two parts:**
  - *Archived real root:* every launch path is refused by exactly the archived drift. The verified runs are skipped,
    the existing pilot is never overwritten, the extension stays locked by the recorded gate 7, and the bookkeeping
    bytes are unchanged.
  - *Temporary root:* the original plan and refusal assertions.
- **Default `--root`** moved out of `runs/m7g_k` to `runs/_tests/…`, in this suite and in `rl/m7g_k_tests.py`. The
  archived tree gains nothing.

**Result:** 13 / 13 on the current tree, and 13 / 13 in the clean worktree with only the updated test file.

## 2. Prefix-row identification

### 2.1 The rule

`m7h_curriculum.prefix_rows(labels, rows)` is the one reader of the boundary. It returns `(L, kind)`. Rows `[0, L)` are
prefix rows and rows `[L, rows)` are policy rows.

| Artifact label `m7h_start` | L |
| --- | --- |
| absent | 0: a tick-0 start, including every evaluation episode |
| `archive_prefix` | `prefix_length`, where 1 ≤ L ≤ rows |
| `archive_prefix_in_progress` / `archive_prefix_failed` | rows: the phase never completed, and rows ≤ the planned length |

Consumed ticks are `0 … n−1`, so a row index is its native tick.

### 2.2 Gap found and fixed

- **The gap.** The label used to be written only after a successful prefix phase.
  - After a hard prefix failure (an end-observation or consumed-tick mismatch), the worker's exception path closes
    the environment.
  - If a preservation mark exists (the anomaly detector can set one), an aborted artifact is then written with prefix
    rows and **no label**. It would read as a tick-0 episode.
  - Only a run that is already hard-stopped could produce it, but the ambiguity was real.
- **The fix.** The worker now writes `archive_prefix_in_progress` (planned L, digest, cell, source) **before the first
  prefix row**. Completion replaces it with `archive_prefix`; a lifecycle failure replaces it with
  `archive_prefix_failed`. No other path changes.
- **Other paths were already unambiguous:**
  - Cooperative and CTRL_BREAK stops drain a pending prefix reply before preservation, so an aborted in-flight episode
    always carries its complete label.
  - A kill writes nothing.
- **The row format is unchanged.**

### 2.3 The proof

`python rl/m7h_campaign.py prove-rows` → PASS.

**Every view of every recorded curriculum episode agrees with the rule, with zero violations.** The data:
- E4, E5a and E5b;
- the E4 first attempt, stopped by the monitor;
- the three E7 drills.

In total: 157 rows and 173 artifacts. Of the artifacts, 89 are prefix starts and 84 are tick-0 starts; 16 are
in-flight episodes that a stop preserved as aborted. The views compared:

| View | What is compared |
| --- | --- |
| **capture** | the label's L and kind; rows `[0, L)` digest = the label's prefix digest; full digest; ticks `0 … n−1` from a tick-0 observation |
| **training diagnostics** | the row's `m7h` block (start kind, `prefix_length`, rows = L + policy steps); the Monitor's `validate_episode_row`; the parent's selection log (the start dispatched to that env before the episode, with its L); PPO steps = vector steps between automatic resets |
| **replay** | the archive entries' prefix digests recomputed from the source artifacts (1,165 / 857 / 857 … entries, 100 %) |
| **analysis** | the same `prefix_rows` feeds the training diagnostics, the left-region classes and the genuine-entry replays |

**E3's lifecycle-failure artifact:** `archive_prefix_failed` with L = rows = 426, consistent.

**12 fresh tick-0 replays**, all exact:
- 8 prefix starts stratified over L = 6 … 2,947, 2 tick-0 starts, and 2 aborted in-flight prefix episodes;
- the replayed observation after row L−1 equals the delivered `o_L`, including `host_frame`;
- the final observations are equal;
- the left-region facts on each side of L equal the worker's.

**Game test of the fix** (`game_provisional_label`), with a real worker:
- A corrupted end observation is refused. The written artifact carries `archive_prefix_in_progress` with L = rows =
  61.
- An exact prefix followed by 25 policy steps gives `archive_prefix`, L = 61, rows = 86.

**Tamper cases, all detected** (copies of the E4 run):
- the label L;
- a removed label;
- the row L;
- the row start kind;
- the selection-log L;
- a foreign archive source.

**Regression of the changed curriculum code.** The E5 configuration (51,200 transitions, a check, not a campaign run)
was re-run on the final code. It is **bit-identical** to the recorded E5:
- final digests `ce5f9973…`;
- 19 rows;
- the archive, the selection log and the prefix bytes.

All verifiers are clean.

**Limitation.** No left-region episode exists in any run; the only real crossings are the two fixtures, which M7h
never reads (registered). The positive path of the section-4 replay verification (`g_s`) is therefore unit-tested with
stubbed replay facts: the selection of the first entry plus up to 5 more, the pass and fail conditions, and `g`.

## 3. The campaign

### 3.1 Profiles (`rl/configs/m7h/`)

**`m7h_f_s{0…4}`:**
- `rl/configs/m7g/m7g_s{s}_v1.toml` verbatim, plus the registered `[curriculum]` table;
- name, notes and `output_root = "runs/m7h/campaign"` are the only other changes;
- the compatibility view differs from Phase K v1 in exactly the five `curriculum.*` keys.

**`m7h_c_s{0…4}`:** curriculum off, identical to Phase K v1 in both the semantic and compatibility fingerprints.
- C s3 and s4 are used only in the extension.
- C s0–s2 are used only on the retrain branch.

**Fresh untrained models:** F and C of the same seed build identical untrained models, equal to the M7d / Phase K
digests (`68155f41…`, `1dd753ae…`, `9fa632c6…`).

### 3.2 Manifest (`docs/rl_frontier_curriculum_m7h_manifest.json`, sha256 `9d5e0c15…`)

It holds:
- the executable `1e7c62a0…`, HEAD `78e56f4` (dirty), and the submodules;
- the code fingerprint `8f9a9112…`: 76 files, every non-test `rl/*.py`, every M7h profile including the gate
  profiles R1 uses, and the rule;
- the rule sha256 `98d1d55d…`;
- every profile's identity, checks and the Phase K comparison proof;
- the untrained digests;
- the historical control identity: the final checkpoint and evaluation file sha256s and rule inputs, T = 118/25, 19/4,
  427/100, falls 1 / 1 / 0, k = χ = 0;
- the registered settings: the curriculum, the 10 / 4 GiB launch gate, the 4 / 3 / 1 GiB commit-only in-run policy,
  atomic sets, the budget, stop and restart policy, and the training-input restriction;
- the evaluation plan and census;
- the directory plan;
- the limits: 3 runs planned; at most 10 runs, 30,720,000 transitions.

**Frozen at first launch.** It is copied to `runs/m7h/campaign/_matrix/manifest.json` at the first real launch and
never rebuilt afterwards; the `manifest` command refuses.

### 3.3 Decision rule (`docs/rl_frontier_curriculum_m7h_decision_rule.json`)

- It is section 7 in machine-readable form: definitions, gates 0–6 at n = 3, gates 0–5 at n = 5, every threshold as
  an exact fraction, inequality strictness, the extension trigger and order, and what is never gating.
- `rl/m7h_analysis.py` reads the thresholds **from this file**. A self-test covers every gate, branch and boundary at
  n = 3 and n = 5, and proves that a changed threshold changes the decision.
- **One registration detail for review.** Gate 0 lists "a native clear whose clear verification did not run or did not
  reproduce both clocks". This follows the Phase K precedent; section 7.1 defines k on verified clears.

### 3.4 Driver (`rl/m7h_campaign.py`)

Commands: `manifest`, `control-check`, `train` (and `preflight`), `evaluate`, `verify-clears`, `verify-entries`,
`census`, `analyze`, `status`, `prove-rows`.

- **Order.** Strictly sequential: F0, F1, F2. The launch gate runs before **every** launch, and the guarded trainer
  applies the in-run memory policy.
- **Stops.** A stopped run is moved to `_partial/`, never deleted, and restarted from scratch by a later invocation.
  `--resume` is always refused. A crash leaves a partial directory that needs `--restart-partial`, which moves it aside
  intact.
- **Extension.** Only after a recorded n = 3 gate 3.
- **Retrain branch.** Only after a **failed** control check and an explicit `--retrain-control`. Its order is C0, F0,
  F1, C1, C2, F2.
- **Verification after training:**
  - the inherited training verification, with the expected untrained digests;
  - identity (executable, revisions, curriculum config, no lineage);
  - for F, `m7h_verify.verify_curriculum_run`: the E4 invariants re-checked on every campaign run (reset contract,
    accounting, returns, PPO steps, VecNormalize count = ε + 5 + t for every set, delivered observations), prefix
    rows, and archive provenance;
  - for C, a clean control path.
- **Evaluation.** Checkpoint provenance is checked first: run, point, seed, executable, revisions, archive present,
  never an interrupted set. Then the Phase K protocol runs (initial, 9 curve points, final; 985 episodes per run;
  `btt_eval_metrics_v1`), and every label is checked tick-0.
- **Analysis:**
  - Unfinished work is **pending**: `analyze` refuses and records nothing.
  - Violations in finished work are **gate 0**.
  - A decision is recorded once.
- **Isolation.** The driver writes only below `runs/m7h/campaign`. It reads the historical control and never touches
  the Phase K state; its Phase K helpers are the pure ones.

### 3.5 Two diagnostics added (curriculum-only; training unchanged, as E5 proves)

1. **Left-region trajectories.** The parent keeps every left-region training trajectory in
   `curriculum/left_episodes.jsonl` (Track 1 bytes from tick 0, digests, L). The registered section-4 replay
   verification needs these trajectories, but training preserves only every 10th artifact.
2. **Lowest x at y ≥ 3,000.** The worker records the lowest x reached at y ≥ 3,000 on policy and prefix rows. This is a
   registered training diagnostic that was not recorded before.

### 3.6 Control reuse at launch

**`train` refuses** unless:
- a **passed** R1–R3 record exists for exactly the manifest's code fingerprint, executable and submodules;
- the historical control files still match the manifest (final set, evaluation files, rule inputs, Phase K status);
- the historical final labels are tick-0 (verified: 600 / 600 artifacts).

**Failure handling.**
- A launch-gate refusal during `control-check` records nothing, so it cannot open the retrain branch.
- A failed reproduction opens the branch only through an explicit user flag.

## 4. Resource gates and the physical-memory dip

**Launch gate.** Available commit ≥ 10 GiB **and** available physical ≥ 4 GiB:
- evaluated separately;
- inclusive;
- a missing reading fails;
- disk, CPU, processes, ports and environment are checked as well.

`m7h_guard.evaluate_launch` makes this testable on synthetic readings. All boundaries are tested. **The observed dip
values of 3.2 and 3.5 GiB are refused at launch.**

**In run.** The level reads available commit only (warn < 4, stop < 3, kill < 1 GiB). A physical dip never changes it.
The probe now **counts and reports** samples below the 4 GiB launch threshold (`samples_physical_below_launch_gate`),
report only.

**Observed:**

| Run | Launch commit / physical (GiB) | Minimum in run: commit / physical (GiB) |
| --- | --- | --- |
| R1 first pass, seeds 0–2 | 16.6–16.9 / 5.19–5.31 | 11.6–11.9 / 4.07–4.22 |
| R1 final pass, seeds 0–2 | 15.4–15.9 / 4.24–4.40 | 10.4–10.8 / **3.18–3.49** |
| E5 re-check (today) | 15.93 / 4.45 | 10.85 / **3.50** (31 of 36 samples below 4 GiB) |
| real-root dry run (now) | 15.57 / 4.30 | — |

- A run draws about 1 GiB of physical memory and about 5.0–5.2 GiB of commit.
- Commit never came near the in-run thresholds.
- The physical margin at launch was 0.24–0.45 GiB in the last four readings, falling over the day.

The thresholds are unchanged (section 8, item 3).

## 5. Dry runs with synthetic records (`rl/m7h_campaign_tests.py`, 14 / 14)

No training or `learn()` happens in any case.

| Case | What it establishes |
| --- | --- |
| `unit_prefix_rows_rule` | the rule on every label kind and every inconsistency; the provisional label is written before the first prefix row |
| `unit_manifest_profiles` | the manifest is ok and current; F = Phase K v1 + exactly the curriculum keys; C = Phase K v1; fresh F = C = M7d digests; census 2,955 / 6,895 / 5,910; order; limits; registered values; directory plan; fingerprint coverage |
| `unit_rule_registered` | the rule JSON holds the proposal's thresholds; the self-test; the manifest pins it |
| `unit_historical_control` | identity and R3 values; every reuse refusal (missing, failed, stale or other-executable record, changed control files); the `control-check` command (a gate refusal records nothing, a pass binds to the code); a failure plus `--retrain-control` gives the registered retrained order |
| `unit_resource_gates` | as in section 4, plus one real reading (nothing launched) |
| `unit_dry_runs` | every path dry: the control check required, stale or failed refused, gate refusal, order, extension, resume, retrain without a failed check, `control-check`, `evaluate`, `census`, `analyze` (not ready), `status`; the frozen manifest never rebuilt; nothing created |
| `unit_launch_stop_restart` | stand-in launcher: F0 → F1 → F2 in the root; profiles and output isolation; the gate before every launch (3 calls); the manifest frozen at the first launch; a stop kept intact in `_partial` and restarted from scratch; a crash needs `--restart-partial` (moved aside intact); a gate refusal between runs stops before the next launch |
| `unit_checkpoint_identity` | untrained F sets are clean at t = 0 and t > 0; wrong point, seed, other run, executable, missing archive, interrupted set, a C set with curriculum files and an F set as C are all refused; `ckpt_000000000` = the fresh-model digests |
| `unit_curriculum_verification` | the six tamper cases of section 2 |
| `unit_eval_tick0` | real evaluation artifacts pass; a start label, a non-tick-0 initial observation and an `m7h` row key are refused |
| `unit_analysis_end_to_end` | synthetic F trees + the real historical control: premature `analyze` records nothing; gate 5a (D = 1/2 in each seed); gate 3 unlocks exactly C3, F3, F4, C4; n = 5 refused until those runs exist; gate 0 on a tick-0 violation; recorded once |
| `unit_left_entries` | left-trajectory persistence round trip; the genuine-entry selection and `g` |
| `unit_isolation` | no fixture, TAS or capture path in any M7h module or profile; no `learn()`; the evaluator has no curriculum reference; the suite leaves the Phase K bookkeeping, `runs/m7h/_gate`, the docs manifest and a non-existent `runs/m7h/campaign` unchanged |
| `game_provisional_label` | section 2.2, on a real worker |

**Real campaign root.** `train --dry-run` with the real gate:
- plan: F0 "train from scratch", F1 and F2 "wait";
- manifest drift: none;
- gate: ok;
- preflight and directory plan: ok;
- **one blocker:** "the R1–R3 control check has not run on this code".

`census`, `status` and `analyze` (not ready), `evaluate` / `control-check --dry-run`, the refused extension and
resume, and `verify-entries` created nothing. `runs/m7h/campaign` does not exist.

## 6. Other findings (fixed unless noted)

1. **`rl/m7h_run.py r3` always exited 0** (it returned a truthy path). The gate's recorded R3 result (`ok: true`) is
   correct, so the gate outcome stands. R1–R3 now also take an output base, so the campaign re-runs them in its own
   tree.
2. **The new driver's stop record** passed `kind=` into `event()`. The launch test found it.
3. **Premature `analyze`** would have recorded a permanent gate-0 decision. I fixed this before any use (the pending
   versus integrity split).
4. **The test copies followed the evaluation workers' junctions** into `build-us/Release/.tcc` and copied the tcc
   toolchain. The copies were removed after I confirmed they held no links. The executable and `.tcc` are intact
   (`1e7c62a0…`). The copies now skip runtime folders.
5. **Line-ending sensitivity of byte fingerprints** (section 1.2). Not changed.

## 7. Commands and results

All commands were run from the repository root on the final code.

```
python rl/m7h_tests.py                              -> 13 / 13
python rl/m7h_analysis.py self-test                 -> PASS
python rl/m7h_campaign_tests.py                     -> 14 / 14, archived trees unchanged
python rl/m7g_k_campaign_tests.py unit              -> 13 / 13 (was 6 / 13); also 13 / 13 in a clean HEAD worktree
python rl/m7g_k_tests.py unit                       -> 6 / 6
python rl/m7h_campaign.py prove-rows --replays 12   -> PASS (7 / 7 runs, 12 / 12 replays)
python rl/m7h_campaign.py manifest                  -> ok (code 8f9a9112..., 76 files)
python rl/m7h_campaign.py train --dry-run           -> exit 1, one blocker: the control check
E5 configuration re-run (51,200, readiness scratch) -> bit-identical to the recorded E5
git diff --check                                    -> clean
```

No BattleShip process remains.

## 8. Remaining blockers

1. **The R1–R3 control check on the frozen code.**
   - The code fingerprint changed after the gate's R run: the prefix label, the diagnostics, the guard refactor, the R
     parameters, and the new campaign modules, profiles and rule. The registered rule is that any code change after R
     means R is repeated.
   - This task did not edit the trainer, the worker stack, the configuration schema, the vector env or the monitor.
     The E5 re-check shows the curriculum behaviour is unchanged.
   - Command: `python rl/m7h_campaign.py control-check`. It takes about 45 min and trains 3 × 102,400 curriculum-off
     transitions, then re-evaluates 600 episodes.
   - It needs your go-ahead.
2. **Your approval to launch the campaign** (`python rl/m7h_campaign.py train`, then `evaluate`, `verify-clears`,
   `verify-entries` and `analyze`).
3. **Physical-memory margin (operational; thresholds unchanged).**
   - Available physical at idle was 4.24–4.45 GiB in the last four readings, against the 4 GiB launch gate.
   - Growth of about 0.3–0.45 GiB in background use would refuse a launch. This includes the launch of F1 or F2 after
     the previous run: the gate runs before every launch, and the invocation then stops, preserving everything.
   - During runs, physical sits at about 3.2–3.5 GiB, as registered. It is reported, not a stop trigger.
4. **If you commit the M7h work before launch.**
   - HEAD changes, so the manifest drifts; `python rl/m7h_campaign.py manifest` must be re-run before the first launch.
   - The control-check record binds to the code fingerprint, executable and submodules, not HEAD, so it stays valid
     unless the file bytes change (for example through line-ending conversion on checkout).

## 9. Projected time and disk

### 9.1 Time

| Step | Estimate | Basis |
| --- | --- | --- |
| control check (R1–R3) | about 45 min | the gate's R1–R3: about 41 min |
| F training, per run | 44 min expected; 62 min by the E6 projection; at most 74 min | Phase K v1 full runs, 33.6 min at about 1,540 tr/s, ÷ the E6 ratio 0.77; the E6 short-run projection; the E6 worst-case bound |
| evaluation, per run | about 36 min | Phase K v1: 35.7–36.3 min for 985 episodes |
| entry and clear verification | under 1 min per run | ≤ 6 replays of about 3 s; clear replays only if there are clears |
| **three-seed campaign** | **about 4.7–5.7 h (worst case 6.3 h)** | control check + 3 × training + 3 × evaluation |
| extension (only through gate 3) | about 5.0–6.0 h | C3 and C4 at about 34 min, F3 and F4 as above, 4 evaluations |
| control-retrain branch (only if the check fails) | about 3.5 h more | 3 × (34 + 36) min |

### 9.2 Disk

| Item | Estimate | Basis |
| --- | --- | --- |
| per F run | about 0.6–0.8 GB | training directory like the control's (Phase K v1: 44–82 MB); the curriculum archive in each of 31 sets (2.9 MB per set at 102,400 with 1,165 cells; 5–10 MB per set if it grows to 2,000–4,000 cells, so 150–310 MB); evaluation about 373 MB |
| control check | about 0.24 GB | R2 225 MB |
| three-seed campaign | about 2.0–2.6 GB | |
| extension | about 2.3–2.9 GB more | |

Free disk: 133.7 GB.

## 10. Working tree (not committed)

**New in this task:**
- `rl/m7h_matrix.py`, `rl/m7h_campaign.py`, `rl/m7h_analysis.py`, `rl/m7h_verify.py`, `rl/m7h_campaign_tests.py`;
- `rl/configs/m7h/m7h_{f,c}_s{0…4}.toml`;
- `docs/rl_frontier_curriculum_m7h_{manifest,decision_rule}.json`;
- `docs/rl_frontier_curriculum_m7h_readiness.{md,json}`.

**Changed in this task:**
- M7h modules (untracked):
  - `rl/m7h_curriculum.py`: `prefix_rows`, the label constants, the lowest-x diagnostic;
  - `rl/m7h_worker.py`: the provisional label, the row fields;
  - `rl/m7h_vec.py`: left trajectories;
  - `rl/m7h_guard.py`: `evaluate_launch`, the report-only physical counter;
  - `rl/m7h_run.py`: the R output base and the R3 exit code.
- Inherited tests only:
  - `rl/m7g_k_campaign_tests.py`: isolation;
  - `rl/m7g_k_tests.py`: the default root.

**Unchanged since the gate:**
- the inherited runtime files (`rl/m7_trainer.py`, `rl/btt_parallel.py`, `rl/experiment_config.py`,
  `rl/m7_vec_env.py`, `rl/m7d_run.py`, `rl/train_m7.py`);
- the Phase K addendum edits;
- the gate report;
- your staged proposal (working copy equal to the index).

**Frozen evidence and other trees:**
- The frozen Phase K manifests (`9a58f03b…`) and `runs/m7g_k` bookkeeping: byte-identical.
- The submodules (decomp `3c7fd5d05`, libultraship `805f1950`, torch `3aa9c97`) and the executable (`1e7c62a0…`):
  unchanged.
- HEAD `78e56f4` = `origin/main`. Nothing committed or pushed. No BattleShip process remains.
