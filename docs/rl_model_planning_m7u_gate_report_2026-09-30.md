# M7u gate `m7u1`: report (2026-09-30)

**Result: not launched.** The standalone preflight refused, so the gate never started. There is no rule outcome: not
PASS, NULL or INCONCLUSIVE, and not INCOMPLETE or INVALID, because nothing ran.
- **Zero native ticks.** No BattleShip process was started. `runs/m7u` does not exist.
- **No results exist:** no paired P / RC / scrambled-goal outcomes, ambiguity flags, failure attribution, training, or
  time and memory use of a run.
- **Nothing was committed or pushed**, and no video was made.

Scope, unchanged: local control after self-generated supplied prefixes. Nothing here concerns a tick-0 reach, a
landing, a crossing or a clear.

## 1. What was done, in order

| step | result |
| --- | --- |
| review of `approval-template` against the proposal, the implementation record §11 and the benchmark | matches: N 64, S 6,000, E 3, 40 goals, rule `m7u1_control_rule_v2` (PASS 10 / 8 / 6, NULL 2 / 0), controls RC and S as registered, 431,201 native ticks (prefixes 72,000 and replays 6,960 included), per-phase caps, 3,600 s, 3,072 MB |
| gap found in the review | the driver recorded only each decision's chosen index and predicted-reach count. It did not keep candidate sets, scores, member predictions or model-input tensors, which the authorisation requires |
| pre-approval amendment (implementation record §9 item 9) | evidence recording only, in `rl/m7u_gate.py` and `rl/m7u_tests.py`. Checked behaviour-neutral: the offline e2e rerun gave the same goals digest, model parameters, all 120 decision logs, outcomes, ledger and 10 exact replays. Unit suite 17 / 17 before the approval record existed |
| D: source snapshot | `D:\BattleShip_source_snapshots\2026-09-30_m7u1`, **PASS**, `snapshot.json` sha256 `f45de49d…`. 51 files: the 12 untracked M7u files, the 2 ignored identity records, and the gate's whole import closure (37 tracked, unmodified at `ad89c0a`). Each file hashed from the repository, from the D: copy read back, and from the repository again. Independent re-hash with PowerShell `Get-FileHash`: 51 / 51. The tool's own `verify`, run from the D: copy: PASS. `prepared_reference/` holds the reviewed pre-amendment files (12) and `amendment.diff` |
| evidence-backup coverage, read-only | 391,625 `runs/` files, 0 uncovered (base + `_incr_m7r` + `_incr_m7s`). All 26 existing D: records and manifests byte-identical before and after |
| approval record | `docs/rl_model_planning_m7u_gate_approval.json` (sha256 `37c71311…`): `identity()` frozen, with this authorisation, the review block, the snapshot and the coverage. `approval_status()` = approved |
| standalone preflight | **refused**: `unit_suite failed` (16 / 17). Everything else passed: approval matched, benchmark choice N 64 / S 6,000, rule self-test, track check, coverage 0 uncovered, no BattleShip process, executable present |

## 2. Why it stopped

The failing case is `unit_approval_refusal`, a preparation-era test. It asserts that
`docs/rl_model_planning_m7u_gate_approval.json` does not exist. `preflight()` runs the whole unit suite and also
requires an approved record, so it can never pass once the record exists. `cmd_run()` calls the same `preflight()`,
so `run` would refuse the same way before launching anything.

This is a preparation defect that I did not catch in the pre-approval review. During preparation no approval record
could exist, so the defect was invisible to every earlier unit, e2e and preflight run.

The fix is a code change to `rl/m7u_tests.py`, which is in the frozen identity. The authorisation forbids any code
change after approval and requires a stop on identity failures. So nothing was repaired or retried, and the approval
record was left as written.

## 3. Pre-launch machine state (for any later attempt)

The benchmark ran on an idle machine. At the time of this attempt:

| measure | now | benchmark (idle) |
| --- | --- | --- |
| N = 64 planning decision, median | 0.435 s | 0.316 s |
| N = 64 planning decision, p95 | 0.631 s | 0.319 s |
| free physical memory | 1.5 of 15.9 GB | — |
| free commit | 9.4 GB | — |

- **Other processes:** avidemux (5.7 GB private), the Claude app (about 1 core, 3.2 GB), IntelliJ (2.3 GB) and OBS.
- **The offline e2e ran 565 s**, against 289 s at preparation, with every phase slower.
- **Effect on the caps:** at these latencies the evaluation phase would still be projected under its 1,500 s cap, but
  with much less margin. The 1,920 unbatched decisions alone would take about 0.9-1.2 ks. Collection (600 s cap,
  projected 422 s at idle) would also tighten.

## 4. Decisions needed from the user

1. **Test-only fix.** `unit_approval_refusal` should check `approval_status()` against a temporary approval path,
   not the repository one, so the suite does not depend on whether the real record exists. It changes no run
   behaviour, but it changes the code identity. The current approval record then no longer matches and cannot
   authorise a run: a new snapshot and a new approval record would be needed. Only you can approve this.
2. **Machine readiness.** Free the machine (close avidemux and OBS) before any launch, or accept a higher risk of an
   INCOMPLETE stop.

## 5. Evidence

- **Stop evidence:** `logs/m7u_gate/` (Git-ignored, 20 files). It holds:
  - `stop_record.json` and the preflight output with its unit report;
  - the pre-launch checks: coverage, contention timing, D: record hashes before and after;
  - the amended unit and e2e records, and the prepared e2e state for comparison;
  - the snapshot, approval and contention scripts;
  - a copy of this report.
- **D: increment:** `D:\BattleShip_runs_backup\2026-09-30_incr_m7u_logs\` (`m7u_gate\` from `runs_backup.py`).
  - Tool result PASS: 20 files; the manifest hash is in its `verification.json`.
  - `check-coverage`: 0 uncovered.
  - `increment_check.json`: independent PowerShell re-hash of copy vs source vs manifest, 20 / 20, PASS.
  - It has no top-level verification record, so the gate's coverage discovery lists it as skipped, like
    `_incr_m7t_logs`.
- **Source snapshot:** `D:\BattleShip_source_snapshots\2026-09-30_m7u1\`.
- **Working tree:** new untracked files only. Tracked files are unchanged, and the user's replay edits are untouched.
