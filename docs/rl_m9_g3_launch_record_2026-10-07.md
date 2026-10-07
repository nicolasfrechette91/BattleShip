# M9-g3-s1 launch record (2026-10-07)

**Final status: Part B held in full on the committed tree (section 1). Part C first STOPPED at step 3 (the full preflight refused for memory readiness,
3,011 MB available < 4,096 MB; sections 6.3-6.4, zero ticks). The user then closed the applications concerned and authorised exactly ONE re-run of the full
preflight with the approval and snapshot reused (section 6.5); it passed, and the one M9-g3-s1 session ran to completion (sections 6.7-6.8): registered outcome
NULL, line CONTINUE, pointer 2,220, increment taken and verified three ways; results in `docs/rl_m9_g3_s1_results_2026-10-07.md`.** This file is new; no tracked
file was modified at any point. The only other files this session writes are the ones the user named (the approval, the D: source snapshot, the
run tree `runs/m9_g3/s1/`, the D: increment, the results record) plus Git-ignored logs under `logs/m9_g3_prep/launch_2026-10-07/` and
`logs/m9_g3_run/` (the launch tools' own output directory).

| item | value |
| --- | --- |
| checkout | `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, branch `main` |
| HEAD | `ca3cfb69a754b7c3180f9a7996ad1330c217ff7d` "Fix g3 git-state test for the committed tree" |
| `origin/main` | `ca3cfb69a754b7c3180f9a7996ad1330c217ff7d`; `git ls-remote origin main` also returns `ca3cfb69...` |
| `git status --porcelain --untracked-files=all` | empty at the start (13:13 UTC), after the five suites (14:05 UTC) and after the dry-run preflight |
| external guide | `Smash_pc_port/guide.md`, read, not edited |
| read in full | `CLAUDE.md`; the guide; `docs/rl_m9_g2_stop_review_2026-10-06.md`; `docs/rl_m9_g3_decisions_2026-10-06.md` (section 7 included); `docs/rl_m9_g3_implementation.md`; `docs/rl_m9_g3_recheck_2026-10-06.md` |
| Python | `C:\Users\kill_\AppData\Local\Programs\Python\Python313\python.exe` 3.13.2 (`logs/m9_g3_prep/launch_2026-10-07/python_identity.txt`) |

## 1. Part B, condition by condition

| # | condition | measured | holds |
| ---: | --- | --- | --- |
| 1 | HEAD = origin/main; no tracked change; no untracked file outside ignored paths | `ca3cfb6` = `ca3cfb6` = remote `ca3cfb6`; `git status --porcelain --untracked-files=all` empty | **yes** |
| 2 | the only difference under `rl/` between `5214582` and HEAD is the section-6 replacement in `rl/m9_g3_tests.py` | `git diff --stat 5214582 HEAD`: three files, 147 insertions, 1 deletion: `docs/rl_m9_g3_decisions_2026-10-06.md` (+49, the amendment), `docs/rl_m9_g3_recheck_2026-10-06.md` (+96, new), `rl/m9_g3_tests.py` (+2 -1). Under `rl/` only `rl/m9_g3_tests.py` changed, by exactly the two-line replacement of line 1001 that the re-check record's section 6 proposed (the diff is in section 2 below). New g3 source fingerprint **`f92ca9067813b9e6`** (was `17dea6d712e624ed`), unchanged after the suites | **yes** |
| 3 | the five suites on the committed tree | g3 unit **25 / 25** (954 s); g3 e2e **PASS, digest `078f46c445d8adc5`** (1,026.5 s); g1 evaluation **29 / 29** (78 s); g2 **29 / 29** (586 s); g1 unit **62 / 63** (393 s), failing ONLY `identity_names_every_registered_pin` (the documented pre-existing failure: the tracked `rl/m9_eval_*.py`, `rl/m9_g2_*.py` and `rl/m9_g3_*.py` files are not in g1's `CODE_FILES`) | **yes** |
| 4 | the pessimistic projection fits the 145-minute cap with no trimming | `rl.m9_g3_run.budget_projection()`: sum of caps 7,560 s; pessimistic 7,780 s = 129.7 min of 8,700 s; slack 920 s; expected 5,730 s | **yes** |
| 5 | the preflight refuses SOLELY for the missing g3-s1 approval | `python -B -X utf8 rl/m9_g3_session.py preflight --skip-unit` (the unit suite ran separately under condition 3), exit 1, `problems` = `["no approval record at docs\rl_m9_g3_s1_approval.json (the session is not authorised)"]` and nothing else. Readiness passed: 5,247.7 MB available (>= 4,096), 15,573.6 MB commit free (>= 10,240), C: 103.3 GiB, D: 1,624.5 GiB free. No memory or free-commit refusal; no application was closed; no threshold was changed | **yes** |
| 6 | earlier trees byte-identical to their D: increments; pins and the reused tape table match | the preflight's tree check: rd1 166 files / 62,448,635 B / `e81226d7...`, rd2 62 / 66,759,098 / `6775281e...`, rd3 77 / 114,026,700 / `b6e13ecb...`, rd4 93 / 165,147,441 / `7ff2b29d...`, m9_g1 2,740 / 354,131,925 / `92ba5481...`, m9_g1_eval 1,393 / 162,003,001 / `ab3e6c61...`, m9_g2_s1 9,779 / 988,807,605 / `4ad2c3dc...`, all `ok`; the g3 unit gate `the_protected_trees_equal_their_increments_and_the_pins_hold` passed; an independent PowerShell `Get-FileHash` re-hash of all seven trees against their increments (`logs/m9_g3_prep/launch_2026-10-07/trees_independent_check.txt`): 0 missing, 0 extra, 0 bad, PASS each. Pins: executable `30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee`, "executable, runtime files and frozen configuration equal the archive's pins"; the reused tape `runs/m9_g2/s1/session/tape_baseline.json` file sha256 `81fa52c21078b2c2e5af9239678918099c6fb407608de085c7dd0c46d98196cd`, content digest `d915fab920554774...`, "pinned, measured with the executable now"; controller-rule CVars absent; status table digest verified; both lineages re-derived (`T_clear` 2,326 words `5eccd4e2d5d77b25`, `T_t` 2,315 words `de1228be4146b720`); D: coverage 423,387 source files, **0 uncovered**, 12 increments | **yes** |
| 7 | no design decision; no tracked file edited | no tracked file was edited (`git status` empty throughout Part B). No registered measure, threshold, rule, schedule or training setting was touched. One provenance correction is disclosed in section 4: a corrected COPY of the approval-writing tool, written as a new Git-ignored file, so that the approval record quotes today's authorisation and its date | **yes** |

## 2. The `rl/` diff between `5214582` and HEAD (condition 2)

```diff
diff --git a/rl/m9_g3_tests.py b/rl/m9_g3_tests.py
index b4b5f46..9e59985 100644
--- a/rl/m9_g3_tests.py
+++ b/rl/m9_g3_tests.py
@@ -998,7 +998,8 @@ def tracked_files_are_unchanged_except_the_authorised_edit_and_only_new_files_ex

     probs, info = S3.git_problems()
     eq(f"git state: {probs}", probs, [])
-    eq("exactly the one authorised edit differs from HEAD, at its pinned digest", {k: v["at_pinned_digest"] for k, v in info["tracked_changes"].items()}, {"rl/m9_eval_tests.py": True})
+    committed = "rl/m9_eval_tests.py" not in info["tracked_changes"] and S3.sha256_file(REPO / "rl/m9_eval_tests.py") == S3.AUTHORISED_TRACKED_EDITS["rl/m9_eval_tests.py"]["sha256_after"]
+    eq("the authorised edit is committed (HEAD carries it), or it is the only tracked change, at its pinned digest", {k: v["at_pinned_digest"] for k, v in info["tracked_changes"].items()}, {} if committed else {"rl/m9_eval_tests.py": True})
     new = [ln[3:] for ln in ses1.git("status", "--porcelain").splitlines() if ln.startswith("??")]
     ok("every new file under rl/ or docs/ is an M9 file", all(("m9" in n or "M9" in n) for n in new if n.startswith(("rl/", "docs/"))))
```

`git diff --check` is clean. Working-tree digests: `rl/m9_g3_tests.py` `4e0e681c6cecc98059f99fb10f4b244838b1b3bdc68678c22ae1322d8475b68c`; `rl/m9_eval_tests.py`
`7151c34bee4c6e9cd20697d902dc8e8e10a8e4eeee67cee93f429acbe12edb84` (the pinned post-edit digest of decision 9, now carried by HEAD).

**The g3 source fingerprint** (sha256 over the sorted `rl/m9_g3_*.py` names and contents, first 16 hex, the computation of `logs/m9_g3_prep/tools/three_passes.py`):
**`f92ca9067813b9e6`** over `m9_g3_contract.py, m9_g3_frontier.py, m9_g3_probe.py, m9_g3_report.py, m9_g3_rule.py, m9_g3_run.py, m9_g3_session.py, m9_g3_snapshot.py,
m9_g3_tests.py, m9_g3_train.py`; identical before and after the suites (`fingerprint_after_suites.txt`).

## 3. The suites (condition 3), as run

All five from the repository root, sequentially, in one background chain (13:14:56 to 14:05:43 UTC), `python -B -X utf8 <suite> unit|e2e`, outputs under
`logs/m9_g3_prep/launch_2026-10-07/` (Git-ignored). `git status --porcelain --untracked-files=all` was empty before and after the chain.

| suite | command | result | log |
| --- | --- | --- | --- |
| g3 unit | `rl/m9_g3_tests.py unit` | **25 / 25 passed** in 954 s, exit 0 | `g3_unit.txt` |
| g3 synthetic e2e | `rl/m9_g3_tests.py e2e` | **PASS**, digest **`078f46c445d8adc5`**, 1,026.5 s: s1 INCONCLUSIVE D = R = 2128, 19 moves, pointer 1,920, 3 BLOCKED_BY_RECHECK; s2 INCONCLUSIVE, 4 BLOCKED_BY_RECHECK at f = 3..6 (needs 80 / 160 / 320 / 320 met at 88 / 162 / 325 / 325); deferred 8 and 137; 7 failed attempts at one pointer with the frontier live; line CONTINUE; 94 replays exact, 0 inexact; no problems | `g3_e2e.txt` |
| g1 evaluation | `rl/m9_eval_tests.py unit` | **29 / 29 passed** in 78 s, exit 0 | `g1_eval_unit.txt` |
| g2 | `rl/m9_g2_tests.py unit` | **29 / 29 passed** in 586 s, exit 0 | `g2_unit.txt` |
| g1 unit | `rl/m9_tests.py unit` | **62 / 63 passed** in 393 s, exit 1; the ONLY failure `identity_names_every_registered_pin` ("every m9 source file is in the code identity": the eval, g2 and g3 files), the documented pre-existing failure; both source-guard tests and the git-state gate PASS | `g1_unit.txt` |

## 4. Disclosure: the approval-writing tool (not a design decision; no tracked file)

The provided tool `logs/m9_g3_prep/tools/write_approval.py` (sha256 `b80cffaa1735aca9bb6586849245cd0a87931bba11198eccdc67613904d51963`, unchanged) writes into the
approval record the quoted authorisation text and names its source as "the user's unattended-session message of **2026-10-06** (Part C)". The authorisation under
which this launch runs is the user's message of **2026-10-07**, whose Part C re-authorises the same session in slightly different words ("written to a new file",
"as a new file"). So that the approval quotes the message that actually authorises it, a corrected COPY was written as a new Git-ignored file,
`logs/m9_g3_prep/launch_2026-10-07/write_approval_2026-10-07.py`, differing from the provided tool only in the quoted authorisation (today's items 1-5, verbatim),
the two date strings (2026-10-06 -> 2026-10-07) and one docstring sentence; everything the tool computes, checks and refuses is byte-identical (the diff is in
`write_approval_diff.txt` beside it). The provided tool was not modified. Both files are inside the source snapshot's file set (`logs/m9_g3_prep/**`).

## 5. Other launch tools, as found (unchanged)

| tool | sha256 | note |
| --- | --- | --- |
| `logs/m9_g3_prep/tools/three_passes.py` | `cf8acf2ab834743186ccbc4c1e11c1742a1aa4e54cc24bf5f66c33d883ac6934` | not run (the three passes are the preparation's record; this session ran each suite once as condition 3 asks) |
| `logs/m9_g3_prep/tools/launch_detached.ps1` | `6ff1ea798ff26353d57793ec5c0a29e5a8860f0643093abaa78682edc577959b` | used for the one launch |
| `logs/m9_g3_prep/tools/wait_session.py` | `8eba10bf537f1a64a364b638cd49f660b54780681bc8b2e7909075fece99d9fd` | resolves the repository as `parents[2]`, so it is copied into `logs/m9_g3_run/` and run from there, as g2-s1 did |
| `logs/m9_g3_prep/tools/independent_increment_check.ps1` | `98abb0b9e3ba12c715856b5f1fc0f32298bd17f9ba8bb5d322b3abc7a7b9c310` | used for the seven trees (section 1, condition 6) and for the g3 increment afterwards |

## 6. Part C steps (appended as they complete)

Order as the tools require it: the approval names the snapshot's digest, so the snapshot comes first (the tool's docstring: "AFTER the verified source snapshot"),
then the approval, then the preflight, then the one launch. Logs under `logs/m9_g3_run/` (Git-ignored, the tools' own directory).

### 6.1 Source snapshot (step 2 of the authorisation)

| step | command | result |
| --- | --- | --- |
| create | `python -B -X utf8 rl/m9_g3_snapshot.py snapshot --dest D:/BattleShip_source_snapshots/2026-10-07_m9_g3_s1` | **PASS**: 170 files, 2,975,227 bytes, no problems, no identity code / docs / authorised-edit mismatch, `git_head` `ca3cfb69...`, 213.6 s; `snapshot.json` sha256 **`d6a89a84a5753dc52aa2cc39be952218c3a7f4cf076748f3a108d138723a033f`** (`snapshot_create.txt`) |
| tool verify | `python -B -X utf8 rl/m9_g3_snapshot.py verify --dest ...` | **PASS** at 14:19:35 UTC: 170 files, 0 mismatches, 0 extra, 0 external mismatches, executable equal (`snapshot_verify.txt`, `verify_2026-10-07T141935Z.json` in the snapshot) |
| independent re-hash | `rl/m9_g3_snapshot.py powershell --dest ... --out logs/m9_g3_run/independent_snapshot_rehash.ps1`, then `powershell -NoProfile -ExecutionPolicy Bypass -File ...` (PowerShell `Get-FileHash`, no repository module) | **checked 171, bad 0, exe `30a3913b...` exe_ok True, result PASS, snapshot.json `d6a89a84...`** (`independent_snapshot_rehash_output.txt`) |

The snapshot's file set includes every file under `logs/m9_g3_prep/` (the provided tools, the preparation and re-check logs, this session's suite logs and the
corrected approval-writer copy of section 4).

### 6.2 Approval (step 1 of the authorisation)

`python -B -X utf8 logs/m9_g3_prep/launch_2026-10-07/write_approval_2026-10-07.py --snapshot D:/BattleShip_source_snapshots/2026-10-07_m9_g3_s1 --independent "..."`
(`approval_written.txt`) wrote the NEW file **`docs/rl_m9_g3_s1_approval.json`**, sha256 **`3abd556a411812ef1d6bb27c183e1aff330e47272539a949104d32fc32fb12eb`**,
`created_utc` = `written_utc` = 2026-10-07T14:24:00Z, from the fresh identity: `git_head` `ca3cfb69...`; g3 contract `4cd1deaec0f0333b...`, line contract
`90eac1a6c6682a39...`, frontier rule `60e174a61c02e184...`, s1 rule `dea9965a3989bce5...`, line rule `d9d82885703c016d...`; executable `30a3913b...`; the seven
trees with their counts; the D: records digest over 16 folders `68b793802bbc0fda...`; `source_snapshot` = the snapshot above (`d6a89a84...`, PASS, 170 files, with the
independent-verification sentence); `backup_coverage_before_approval` 423,387 files, 0 uncovered; `authorisation.source` = "the user's unattended-session message of
2026-10-07 (Part C)" with today's items 1-5 verbatim; the task block and `created_utc` at the source. The approval string begins `APPROVED: M9-g3-s1, exactly one
detached training session, once (Part C of the unattended session of 2026-10-07): ...`.

### 6.3 The full preflight (step 3 of the authorisation): REFUSED, so the session STOPPED here

`python -B -X utf8 rl/m9_g3_session.py preflight` (the full preflight, unit suite included), started 14:24:00 UTC, finished 14:44:35 UTC, exit 1
(`preflight_full.txt`, `preflight_full_exit.txt`). Every check passed except one:

| check | result |
| --- | --- |
| g3 unit suite (inside the preflight) | **25 / 25** passed in 864 s |
| g3 rule self-test | PASS (0 problems), s1 `dea9965a3989bce5`, line `d9d82885703c016d` |
| approval | **approved** (matches the current identity) |
| source snapshot | "snapshot recorded, PASS and equal to the repository" |
| git | no tracked change; new files only (`docs/rl_m9_g3_launch_record_2026-10-07.md`, `docs/rl_m9_g3_s1_approval.json`) |
| pins, tape, CVars, status table | equal the archive's pins; the reused tape at `81fa52c21078b2c2 / d915fab920554774`, pinned, measured with the executable now; CVars absent; status table verified |
| seven protected trees | all `ok` with the registered counts |
| lineages | `T_clear` 2,326 words `5eccd4e2d5d77b25`, `T_t` 2,315 words `de1228be4146b720` |
| D: coverage | 423,387 source files, 0 uncovered, 12 increments |
| budget | the pessimistic projection fits |
| **readiness** | **`available memory 3011 MB < 4096 MB`** (commit free 11,924 MB >= 10,240; C: 103.2 GiB, D: 1,624.5 GiB free) |

**Decision applied: STOP.** The user's Part C step 3 says "Preflight passes. If it doesn't, stop; do not re-run it hoping for a different result", and Part B
condition 5 says "Memory or free-commit refusals are stops; do not close applications or change thresholds". The preflight was not re-run, no application was
closed, no threshold was changed, `launch_detached.ps1` was never invoked, and **no native tick was consumed anywhere in this session** (the preflight launches no
game; `runs/m9_g3/` does not exist; `rl/m9_g3_session.py status` reports `run_root_exists: false`; no `BattleShip.exe` process existed at any check; no
`session_stdout.txt` / `session_stderr.txt` under `logs/m9_g3_run/`).

**What the memory reading was (read-only diagnostics, nothing acted on).** Available memory as the tool measures it: about 7,887 MB free at 13:15 UTC (session
start, `Win32_OperatingSystem`), **5,247.7 MB** at the dry-run preflight (about 14:10 UTC, condition 5 held), **3,011.3 MB** at the full preflight's readiness check
(about 14:44 UTC), 3,174 MB when re-read by the readiness function at 14:45 UTC (`PerfOS` "Available MBytes" 3,229, committed 20,400 of a 32,166 MB limit). The
largest working sets at 14:45 UTC were applications started on the machine during this session: `idea64` (2,153 MB, started 14:09 UTC), seven `chrome` processes
(about 2,050 MB together, started 14:13-14:14 UTC), several `claude` processes (640 MB and 230-260 MB each), `Memory Compression` (977 MB), `MsMpEng` (400 MB). No
Python or BattleShip process was alive. None of these was closed.

### 6.4 State left on disk (for the user's decision; nothing here authorises a relaunch)

| item | state |
| --- | --- |
| `docs/rl_m9_g3_s1_approval.json` | written (new file), valid for the identity at HEAD `ca3cfb6` and the snapshot below; the preflight accepts it. The authorised "once" was never consumed because no session was launched. Whether a later launch may use this approval or needs a fresh one is the user's call; this session does not relaunch |
| `D:\BattleShip_source_snapshots\2026-10-07_m9_g3_s1` | PASS, 170 files, `snapshot.json` `d6a89a84...`; equal to the repository at the time of the full preflight |
| `runs/m9_g3/` | does not exist |
| `D:\BattleShip_runs_backup\2026-10-07_incr_m9_g3_s1` | does not exist (nothing to back up) |
| `logs/m9_g3_run/` | the snapshot, approval and preflight logs only; no launch record, no session logs |
| `logs/m9_g3_prep/launch_2026-10-07/` | the suite logs, the dry-run preflight, the fingerprint files, the independent tree check, the approval-writer copy and its diff |
| tracked files | none modified (`git status`: only the two new files above); HEAD = origin/main = `ca3cfb6` |
| the seven protected trees | unchanged (tool check in both preflights; independent re-hash in Part B) |
| `docs/rl_m9_g3_s1_results_2026-10-07.md` | not written: the "Afterwards" items of the authorisation apply only to a session that ran |

### 6.5 The user's second message (2026-10-07, after the stop): ONE re-run of the full preflight authorised

The user closed the applications that had lowered the available memory and authorised exactly one re-run of the full preflight ("the authorised 'once' was
never consumed ... This is not a retry hoping for a different result"), with five pre-conditions and the instruction to reuse the existing approval and snapshot.

**Step 1, nothing changed since the stop (14:51-14:54 UTC, read-only):**

| fact | measured |
| --- | --- |
| HEAD = origin/main = ca3cfb6 | `ca3cfb69...` = `ca3cfb69...`; `git ls-remote origin main` `ca3cfb69...` |
| no tracked change; only the two untracked files | `git status --porcelain --untracked-files=all`: `?? docs/rl_m9_g3_launch_record_2026-10-07.md`, `?? docs/rl_m9_g3_s1_approval.json`, nothing else |
| g3 fingerprint | `f92ca9067813b9e6` |
| the snapshot still verifies | `rl/m9_g3_snapshot.py verify`: PASS at 14:51:28 UTC, 170 files, 0 mismatches, 0 extra, executable equal (`logs/m9_g3_run/snapshot_verify_rerun.txt`) |
| the seven earlier trees still equal their D: increments | tool (`trees_state`): all seven `ok` with the registered counts (`trees_tool_check_rerun.txt`); independent PowerShell re-hash: 0 missing, 0 extra, 0 bad, PASS for all seven (`trees_independent_check_rerun.txt`) |

**Step 2, reuse.** The approval `docs/rl_m9_g3_s1_approval.json` (sha256 `3abd556a...`, unchanged) and the snapshot `D:\BattleShip_source_snapshots\2026-10-07_m9_g3_s1`
(`snapshot.json` `d6a89a84...`) are REUSED, not rewritten, because the user directed it and because both are valid for the identity that still holds: the same HEAD
`ca3cfb6`, the same code and document digests, the same pins, the same D: records, and the approval's "once" was never consumed (no session was launched under it).
The approval-writer refuses to overwrite an existing approval in any case.

**Step 3, memory and commit first (14:51 UTC):** `m8_rd_session.readiness()`: available **7,487.6 MB** (>= 4,096), commit free **16,367.0 MB** (>= 10,240), C: 103.0 GiB,
D: 1,624.5 GiB, `ok: true`. No application was closed by this session; no Python or BattleShip process was alive.

**Step 4, the one full preflight re-run:** `python -B -X utf8 rl/m9_g3_session.py preflight`, 14:55:16 to 15:10:11 UTC, output `logs/m9_g3_run/preflight_full_rerun.txt`
(the refused run's `preflight_full.txt` is kept as evidence). **Exit 0, `ok: true`, `problems: []`.** Unit suite 25 / 25 (662 s); rule self-test PASS; approval
"approved"; snapshot "recorded, PASS and equal to the repository"; pins, tape (`81fa52c21078b2c2 / d915fab920554774`), CVars, status table as before; git: no tracked
change, the two new files; the seven trees `ok`; coverage 423,387 / 0 uncovered / 12 increments; readiness available **7,753.2 MB**, commit free **16,787.2 MB**, C: 106.5
GiB, D: 1,624.5 GiB; the budget fits (7,780 s). The launch follows in 6.7.

### 6.7 The one launch

`powershell -NoProfile -ExecutionPolicy Bypass -File logs\m9_g3_prep\tools\launch_detached.ps1 -Repo <repo>` from the repository root, after checking that no
session log and no `runs/m9_g3` existed: **`launched pid=7140 at 2026-10-07T15:10:48Z`** (`logs/m9_g3_run/launch_record.txt`); the command it detached is
`python -B -u -X utf8 rl/m9_g3_session.py run --session 1` with stdout / stderr captured in `logs/m9_g3_run/session_stdout.txt` / `session_stderr.txt`. The session's
own preflight (the unit suite and the rule self-test included) runs first inside `run`; the session clock starts after it. Waiting: `wait_session.py` copied from
the tools into `logs/m9_g3_run/` (it resolves the repository two levels up) and run from there; it polls `runs/m9_g3/s1/session/state.json` and the pid every
60 s and logs to `wait_log.txt`. Nothing is retried, extended or repaired; no s2.

### 6.8 The session, its records and the increment

* **Registered outcome NULL** (D_1 = none: 8 of 20 sticky clears at 2,128; R_1 none), **line CONTINUE** (k = 1, s2 permitted, its own approval needed). Pointer
  2,300 -> 2,280 -> 2,260 -> 2,240 -> 2,220; 13 attempts (4 MOVED, 9 FAILED_STRIP, 0 BLOCKED_BY_RECHECK, 0 INTERRUPTED), 29 deferred triggers, no HELD, no
  STALLED. Session clock 5,156.5 s of 8,700; 10,205,476 native ticks; 708,712 policy transitions; 43 / 43 replays exact; no memory breach; no leftover process;
  `session_stderr.txt` empty; the process exited by itself at 16:52:44 UTC. Full account: `docs/rl_m9_g3_s1_results_2026-10-07.md`.
* **Post-run, in order:** `verify-run` (`ok: true`, 0 problems; `logs/m9_g3_run/verify_run.json`), `report` (`report.json`), both read-only on the closed tree; then
  `logs/m9_g3_run/*` -> `runs/m9_g3/s1/launch/`, the whole of `logs/m9_g3_prep/` -> `launch/prep/`, the snapshot's `snapshot.json` and both `verify_*.json` ->
  `launch/`, the two outputs -> `derived/` (tree 4,853 -> 4,935 files, 507,814,583 -> 508,166,787 bytes).
* **Increment** `D:\BattleShip_runs_backup\2026-10-07_incr_m9_g3_s1`: `rl/tools/runs_backup.py backup --source runs/m9_g3/s1` PASS (4,935 / 4,935 copied, 0 hash
  mismatches, manifest `d12966c135fdb614f08fab2d63ff0af894d171834ed9f87c802103b9024307a5`, 16:56:28 UTC); separate `verify --source runs/m9_g3/s1` PASS (16:56:53 UTC,
  `verification.json` on D: says PASS with every check true); independent `independent_increment_check.ps1`: checked 4,935, missing 0, extra 0, bad 0, PASS. Logs
  `backup_m9_g3_s1.txt`, `backup_m9_g3_s1_verify.txt`, `independent_increment_check_m9_g3_s1.txt` (written after the backup; outside the increment).
* **Earlier trees after the backup:** the tool (`trees_state`) all seven `ok` with the registered counts (`post_trees_tool_check.txt`); the independent re-hash
  0 missing / 0 extra / 0 bad, PASS for all seven (`post_trees_independent_check.txt`, 17:01 UTC).
* **Coverage:** `combined_coverage()`: **428,322 source files, 0 uncovered, 13 increments** (`post_coverage.txt`); the three skipped D: folders are the known
  non-runs increments.
* **git at the end:** HEAD = origin/main = `ca3cfb6`; `git status --porcelain --untracked-files=all` shows exactly three new files, `docs/rl_m9_g3_launch_record_2026-10-07.md`,
  `docs/rl_m9_g3_s1_approval.json`, `docs/rl_m9_g3_s1_results_2026-10-07.md`; no tracked change; `git diff --check` clean; no commit, push, branch or PR.

### 6.6 What a launch needs, as observed at the first stop (superseded by 6.5)

The only failed input is the machine's available memory at the moment the readiness check runs; every other preflight input holds on this tree. The thresholds
(`rl/m8_rd_session.READINESS`: 4,096 MB available, 10,240 MB commit free, 5 GiB on C: and D:) are registered and were not changed. A later attempt needs the user's
decision on the approval (6.4) and a quiet machine; the g3 unit suite alone takes 14-16 minutes inside the preflight on this machine, during which other
applications may start.
