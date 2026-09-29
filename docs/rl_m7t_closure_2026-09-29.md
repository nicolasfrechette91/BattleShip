# M7t closure (2026-09-29)

**Status: stopped before final acceptance; native eligibility not established.** This was a user decision.

The final synthetic acceptance test `m7t_accept_v1` (design revision 3, §7) was **not authorised and not run**. It has
no outcome, and it is not recorded as a failure. The native gate `m7t1` was never proposed. No M7t step launched
BattleShip or used a native tick.

Nothing was committed or pushed. No production code changed, and nothing was trained. The unrelated `.gitignore`
modification in the working tree was left untouched.

## 1. Outcomes, kept separate

| record | outcome | source |
| --- | --- | --- |
| synthetic prerequisite `m7t_synth_prereq_v1` (registered) | **FAIL**: S1-S4 fail, S5-S6 pass | `docs/rl_m7t_synthetic_prerequisite_2026-09-29.md`; review in `docs/rl_m7t_synthetic_prerequisite_review_2026-09-29.md` |
| synthetic readout test `m7t_synth_readout_v1` (pinned) | **CONFIRM** | `docs/rl_m7t_synthetic_readout_2026-09-29.md` |
| final acceptance test `m7t_accept_v1` | **not run**; no outcome | `docs/rl_learning_strategy_review_2026-09-29.md` (revision 3, status updated) |

Unchanged:
- the M7o, M7r and M7s registered outcomes;
- v3 + reward v2 as the selected baseline;
- every observation, reward and action contract.

## 2. What we learned

All of this was learned in a small deterministic synthetic platformer, never in BattleShip.

1. **Distances trained only on one-tick transitions can rank true path lengths.** The registered T learner's distance
   from the start ranked exact shortest paths with Spearman 0.98-0.99. A greedy policy on it returned to 28 of 56 rare
   goals; the same-trajectory twin and the untrained network returned to none.
2. **The goal-cell readout was the main recorded blocker.** Reading distance to a learned goal node collapsed to about
   zero near goals. That false-arrival signature appears in all 28 rare-goal failures.
3. **Retained result.** On the three saved T networks, reading distance as the minimum over at most 32 recorded
   training states of the goal cell raised returns from 28 to 46 of 56: 18 gains, 0 losses, no seed worse. The claim
   stops there: a different readout improves these saved synthetic policies.
4. **Limits of that result:**
   - **Arrival is not reliable.** All 10 remaining failures are still false arrivals, 13-30 true ticks from the goal,
     and none recovered.
   - **No speed improvement.** Successful returns took a median 9.3× the shortest path, and 7.0× even without a stall.
     On goals both readouts reached, the new readout was slower in 20 of 28.
   - **Composition is not shown.** No stitching test was run with the new readout.
   - **No transfer.** Nothing about Mario.
   - **No evidence for training without goal nodes.** The networks were trained with them.
5. **Measurement lessons:**
   - Support diagnostics built on time-in-status features flag purposeful behaviour as unsupported.
   - A chance reference based on the best single behaviour episode becomes unreachable when rare goals cluster.
   - Absolute model-error thresholds are not comparable across learned geometries.
   - Under a set readout, a same-trajectory twin that uses the same quasimetric loss cannot isolate composition.
   - The constraint had not converged after 20,000 steps.

## 3. What remains unresolved

- **Whether the candidate composes paths across episodes.** The stitching test was never re-run with the set readout.
- **S1, S3 and S4 under the set readout.** S1 is distance correctness, S3 is no invalid stitching and S4 is the
  diagnostics. The repaired diagnostics, chance reference and F3 check were designed but never run.
- **Training without goal nodes, and optimizer convergence.**
- **Why the goal node collapses.** This is still an inference; no test isolated it.
- **Everything about Mario:**
  - whether its random data contains stitchable overlaps near rare cells;
  - whether a v4 encoder separates states that continue differently;
  - one-step model accuracy with collisions, the moving platform, projectiles, locks and hitlag;
  - how far the dynamics depart from determinism;
  - whether goal-directed return is learnable natively at all.

## 4. Why the further 5-5.5-hour experiment was declined

Revision 3 had recommended running it as the only ground-truth test of composition under the set readout. That
question stays open. The reasons on record for stopping instead:

- **Its central criterion was already the likeliest failure.** The composition check (A3) required reaching goals faster
  than every single recorded episode, about 2× the shortest path. The recorded returns took a median 9.3×, and 7.0× even
  without stalls. The forecast came from a different goal set, but it pointed one way.
- **Even acceptance would have bought little.** An ACCEPT would only have made the native gate eligible to be proposed:
  about 1.9 million native ticks, for a claim narrowed to goal-directed return. It would not have shown composition,
  reliable arrival or speed, and a Mario clear needs all three: goals chained in one episode, and a wall crossing.
- **It would have tested a new design, not the registered one.** It needed a package of definition changes, each
  justified but not tested:
  - the twin withdrawn;
  - S1 relaxed;
  - S2 and S3 redefined;
  - a new chance reference;
  - an F3 threshold chosen with the data in view.

## 5. Evidence preservation: backup report

**Increment:** `D:\BattleShip_runs_backup\2026-09-29_incr_m7t_logs\`, separate from the existing backup records.
- It was made with the existing verified tool `rl/tools/runs_backup.py` (`btt_runs_backup_v1`, sha256 `c4de9b0a…`),
  with one destination per Git-ignored evidence folder.
- Each destination's files sit under a subfolder named `runs/`. That name is the tool's fixed layout; the files are the
  `logs/` evidence.

| source | files | bytes | manifest sha256 | tool verification |
| --- | ---: | ---: | --- | --- |
| `logs/m7t_synth_prereq/`: registration, results, `s{0,1,2}_{init,T,S}.pt`, training logs, episode files, post-hoc and memory outputs, `review_2026-09-29/` script and analysis | 31 | 41,082,001 | `3a98ff3f…` | PASS 21:33:41Z |
| `logs/m7t_synth_readout/`: protocol, results, partial result, run log | 5 | 12,134,304 | `5ac62a50…` | PASS 21:33:41Z |
| `logs/m7t_synth_smoke/` | 7 | 8,320,279 | `cf4c4d9d…` | PASS 21:33:41Z |
| `logs/m7t_synth_world/` | 4 | 2,921 | `189cf0ed…` | PASS 21:33:42Z |
| `logs/m7t_design_history/`: the revision-2 copy, and the reach-versus-truth script and output | 3 | 38,189 | `7207a8b0…` | PASS 21:33:40Z |
| **total** | **50** | **61,577,694** | | |

**Independent recomputation.**
- `increment_check.json` in the increment root (sha256 `2e7b3c3a…`) was written by `increment_check.py`
  (`07210722…`), a script separate from the backup tool.
- **Hashes recomputed from the D: copy:** all 50 equal their manifest entry and a fresh read of the source, with equal
  sizes. Each manifest equals the one its verification record names.
- **Coverage:** 50 of 50 regular files under `logs/m7t_*` are covered, and the source had no reparse points.
- **Pinned identities hold on the backup copy:**
  - the saved networks `s{0,1,2}_T.pt` (as pinned by the readout protocol);
  - `results.json` `3cd6526c…` and the three episode files;
  - the readout `result.json` `8dc5689b…`;
  - the review script `5659e800…` and its analysis `2c92fc81…`;
  - the revision-2 copy `3e0a372f…`.

  The backed-up records carry the registration digest `459994a4…` and the readout protocol digest `800a2544…`.
- **Existing records untouched.** `2026-09-28`, `2026-09-28_incr_m7r` and `2026-09-29_incr_m7s` were only read. Their
  verification and manifest hashes are recorded in `increment_check.json`, with modification times equal to their
  original verification times.

**Omissions:**
- **Untracked source files outside `logs/` are in no backup and no commit; they exist only in this working tree:**
  - `rl/tools/m7t_synthetic_prereq.py` `cb3ad35a…`, `m7t_synthetic_posthoc.py` `5ef55fde…` and
    `m7t_synthetic_readout.py` `1001f14e…`;
  - `rl/m7s_goal.py` `5fcd33f9…`, which the harness imports;
  - `rl/tools/runs_backup.py`;
  - the M7t documents under `docs/`, including this closure.

  The backed-up checkpoints cannot be re-evaluated without the harness source.
- **Excluded as not M7t:** the older port logs directly under `logs/` (`BattleShip.log`, `BattleShip-JP.log`,
  `asset-extract.log`).
- **Session scratch copies** of the review and reach-versus-truth scripts are byte-identical to the backed-up copies.
- **Memory notes** outside the repository are not included.
- **Protection:** like the earlier increments, this copy sits on another disk of the same machine.

**Incident.** A first attempt at 21:33:04Z wrote all five sources into one folder, because of a shell-quoting error in
the destination path. The later runs in that folder failed verification, as they should, since the sources were mixed;
the record left in it reads FAIL. The folder was renamed,
not deleted: `D:\BattleShip_runs_backup\_INVALID_misrouted_attempt_2026-09-29T2133Z_m7t_logs\` (46 copied files, some
overwritten by same-named files from other sources). It is not a valid backup, and deleting it is left to the user.
