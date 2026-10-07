# M9-g3: the re-check of the Part B conditions on the committed tree, under the amended condition 1 (2026-10-06)

**Status.** Part C did **not** run. Zero native ticks. No approval record, no source snapshot, no `runs/m9_g3/` tree, no D: increment, no BattleShip process
at any point. The amended condition 1 is recorded in `docs/rl_m9_g3_decisions_2026-10-06.md`, section 7 (written before this re-check, as the user asked);
this file records the re-check as measured and names the input of every gate, so that the committed tree's own state can be read off. Nothing was edited
except that amendment; this file is new. Logs: `logs/m9_g3_prep/committed/` (Git-ignored).

## 1. The committed tree

| fact | value |
| --- | --- |
| HEAD | `5214582a08046498274cfbad07a618f3f7cd7c9c` "failed tests delay the next attempt" (13 files: the decision-9 edit, the ten `rl/m9_g3_*.py`, the two g3 records) |
| `origin/main`, and the remote's `main` by `git ls-remote` | both `5214582a08046498274cfbad07a618f3f7cd7c9c` |
| `git status --porcelain` before the amendment was written | empty (observed at the start of this round, before any write) |
| `rl/m9_eval_tests.py` in the working tree | sha256 `7151c34bee4c6e9cd20697d902dc8e8e10a8e4eeee67cee93f429acbe12edb84` = the pinned post-edit digest (`m9_g3_session.AUTHORISED_TRACKED_EDITS`) |
| the HEAD blob of that file | `07194869bf5326cb...` with LF endings; with CRLF restored it is `7151c34bee4c6e9c...` (`core.autocrlf = true`, the file is `w/crlf`); the committed content is the authorised edit |
| the g3 source fingerprint (sha256 over the sorted `rl/m9_g3_*.py` names and contents, first 16 hex) | `17dea6d712e624ed` before and after the re-check (`fingerprint_before.txt`, `fingerprint_after.txt`) |

## 2. The amendment and the one consequence of recording it

The user's amendment was appended to the decisions record (section 7) before anything else, as instructed. That record has been a tracked file since
`5214582`, so from that moment `git diff --name-only HEAD` lists `docs/rl_m9_g3_decisions_2026-10-06.md` and `git status --porcelain` shows
` M docs/rl_m9_g3_decisions_2026-10-06.md` (`git_state_after_amendment.txt`, 2026-10-07T02:20:46Z). Four readers see that entry: the g1 and g2 git-state
gates (`tracked_files_are_unchanged_and_only_new_files_exist`), the g3 suite's git-state test, and `m9_g3_session.git_problems` (hence the preflight, which
reports "tracked file differs from HEAD and is not an authorised edit" and "git status shows an entry other than a new file or the authorised edit"). Every
such failure below is marked **[amendment]** and its measured input is the amendment alone.

## 3. Amended condition 1, bullet by bullet

| bullet | required | measured | holds |
| --- | --- | --- | --- |
| 1 | HEAD = origin/main, containing the new commit | `5214582` = `5214582` = remote `5214582` | yes |
| 2 | g3 source fingerprint unchanged | `17dea6d712e624ed` before and after | yes |
| 3a | the g3 unit suite passes once more on the committed tree | **24 / 25** (581 s; `g3_unit.txt`). Failing: `tracked_files_are_unchanged_except_the_authorised_edit_and_only_new_files_exist`, at its first assertion, on the two `git_problems` entries of the amendment **[amendment]**. Its second assertion (line 1001) cannot pass on any committed tree: see section 5 | **no** |
| 3b | the synthetic e2e passes with digest `078f46c445d8adc5` | **PASS**, digest `078f46c445d8adc5` (951.7 s; `g3_e2e.txt`): s1 19 moves, pointer 1,920, 3 BLOCKED_BY_RECHECK; s2 4 BLOCKED_BY_RECHECK at f = 3..6 with needs 80 / 160 / 320 / 320 met at 88 / 162 / 325 / 325; deferred 8 and 137; 7 failed attempts at one pointer with the frontier live; line CONTINUE at k = 2; 94 replays exact, 0 inexact; no problems | yes |
| 4 | the g1 evaluation suite 29 / 29 | **29 / 29** (74 s; `g1_eval_unit.txt`) | yes |
| 5 | the g2 suite 29 / 29 | **28 / 29** (490 s; `g2_unit.txt`). Failing: the git gate, `got "['docs/rl_m9_g3_decisions_2026-10-06.md']", want '[]'` **[amendment]**; every other g2 test passes | **no as measured**; the gate's input on the committed tree before the amendment was empty |
| 6 | the g1 unit suite 62 / 63, only the identity test failing | **61 / 63** (348 s; `g1_unit.txt`). Failing: `identity_names_every_registered_pin` (the documented, pre-existing failure: 30 tracked `rl/m9_*.py` files are not in `rl/m9_session.CODE_FILES`: 5 `m9_eval_*`, 15 `m9_g2_*`, 10 `m9_g3_*`) and the git gate on the amendment **[amendment]**. The two source-guard tests of decision 9 pass | **no as measured**; without the amendment entry the result would be the required 62 / 63 |

The e2e digest covers the outcomes, moves, attempts, line verdict, episode count and deferred counts only (`rl/m9_g3_tests.py`, the `digest` of `e2e`), not
the identity or any record, so the amendment cannot affect it.

## 4. The other Part B conditions on the committed tree

| # | condition | measured | holds |
| --- | --- | --- | --- |
| 2 | the pessimistic projection fits the 145-minute cap with no trimming | `budget_projection()`: 7,780 s = 129.7 min of 8,700 s, slack 920 s | yes |
| 3 | the preflight refuses solely for the missing approval | `preflight --skip-unit` (`preflight_dry_run_committed.txt`): three problems: the two git entries of the amendment **[amendment]** and the missing approval. Everything else passed: the executable, runtime files and frozen configuration at the pins; the reused tape at `81fa52c21078b2c2` / `d915fab920554774`, pinned, measured with the executable now; controller CVars absent; the status table verified; the seven trees equal their D: increments; coverage 423,387 source files, 0 uncovered, 12 increments; readiness 8,635 MB available, 19,306 MB commit free, C: 107.2 GiB, D: 1,537.6 GiB; the budget fits | **no as measured**; solely the approval once the amendment is committed |
| 4 | earlier trees byte-identical to their D: increments; pins match | rd1, rd2, rd3, rd4, m9_g1, m9_g1_eval, m9_g2_s1 all `ok`; pins equal the archive's | yes |
| 5 | clean git status apart from files this session creates | ` M docs/rl_m9_g3_decisions_2026-10-06.md` (the amendment, a modification of a tracked file, not a created file) and this new record | **no as literally stated** |
| 6 | no open design decision was made; any pre-launch fix recorded and flagged | none made; no file other than the decisions record (the amendment) was edited; no hazard fix | yes |

## 5. Why Part C did not run

Two findings, of which the first stands on its own.

1. **The g3 suite's git-state test pins the pre-commit state and cannot pass on the committed tree; its fix changes the pinned fingerprint.**
   `rl/m9_g3_tests.py` line 1001 asserts `{k: v["at_pinned_digest"] for k, v in info["tracked_changes"].items()} == {"rl/m9_eval_tests.py": True}`, which is
   true only while `rl/m9_eval_tests.py` differs from HEAD at its post-edit digest, the state when the test was written. On the committed tree that file
   does not differ from HEAD: `git_problems()` reports it in no entry (`git_problems_after_amendment.txt`: `tracked_changes` holds only the amendment; on
   the tree before the amendment it would hold nothing), so the left side is `{}` (or the amendment's entry) and never the required `{"rl/m9_eval_tests.py":
   True}`. In this round the test failed one assertion earlier, on the amendment; removing the amendment moves the failure to line 1001, it does not remove
   it. The only repair is an edit of `rl/m9_g3_tests.py`, which changes the g3 source fingerprint that bullet 2 pins and modifies a tracked file. Not
   authorised in this round: nothing was edited.
2. **Recording the amendment in a tracked record fails the gates by itself.** Bullets 3a, 5 and 6 of condition 1, condition 3 and condition 5 all read the
   amendment's `git status` entry. Everything those gates measure apart from that entry holds, and their input was empty on the committed tree before the
   amendment was written. Any future instruction to record an amendment in a tracked record before the re-check recreates this.

## 6. What a launch needs (for the user's decision; nothing here was applied)

- **The g3 test.** A two-line replacement of line 1001 of `rl/m9_g3_tests.py` that accepts the committed state and still pins the edit (the identity and the
  snapshot keep pinning `7151c34b...`; `git_problems` already tolerates both states):

  ```python
      committed = "rl/m9_eval_tests.py" not in info["tracked_changes"] and S3.sha256_file(REPO / "rl/m9_eval_tests.py") == S3.AUTHORISED_TRACKED_EDITS["rl/m9_eval_tests.py"]["sha256_after"]
      eq("the authorised edit is committed (HEAD carries it), or it is the only tracked change, at its pinned digest", {k: v["at_pinned_digest"] for k, v in info["tracked_changes"].items()}, {} if committed else {"rl/m9_eval_tests.py": True})
  ```

  After it is committed the fingerprint of `rl/m9_g3_*.py` changes; the next condition must name the new value (computed from the committed files), and the
  g3 unit suite and the e2e must pass once more on that tree. The e2e digest `078f46c445d8adc5` is unaffected by a test-only edit.
- **The tree.** Commit the amendment (the decisions record, section 7) and this record, or direct future amendments to a new file, so that
  `git diff --name-only HEAD` is empty when the gates run. Then the g2 gate passes, the g1 suite is 62 / 63 with only the identity test, the g3 session's git
  check and the preflight see nothing but new files, and condition 5 holds.
- **The g1 identity test** stays as documented (30 files; no g1 file is edited).
- The launch tools are unchanged: `logs/m9_g3_prep/tools/` (`write_approval.py`, `launch_detached.ps1`, `wait_session.py`, `independent_increment_check.ps1`).

## 7. Files of this round

| path | what |
| --- | --- |
| `docs/rl_m9_g3_decisions_2026-10-06.md` section 7 | the amendment, recorded first (49 lines appended; `git diff --check` clean; LF endings kept) |
| `docs/rl_m9_g3_recheck_2026-10-06.md` | this record (new) |
| `logs/m9_g3_prep/committed/g3_unit.txt`, `g3_e2e.txt`, `fingerprint_before.txt`, `fingerprint_after.txt` | the g3 suite and e2e once more, with the fingerprint |
| `logs/m9_g3_prep/committed/g1_eval_unit.txt`, `g2_unit.txt`, `g1_unit.txt` | the inherited suites |
| `logs/m9_g3_prep/committed/preflight_dry_run_committed.txt` | the dry-run preflight (`--skip-unit`) |
| `logs/m9_g3_prep/committed/git_state_after_amendment.txt`, `git_problems_after_amendment.txt`, `git_*_before_*.txt` | the gate inputs as measured |
