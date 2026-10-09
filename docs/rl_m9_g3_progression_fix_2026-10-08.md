# M9-g3: the unit suite made independent of the line's progression, `--session` required, exact results-record discovery (2026-10-08)

**Status: zero-tick preparation. No native run, no training, no approval, no snapshot, no commit, no push.** This session fixes the defects that
`docs/rl_runbook.md` reports against the committed g3 tooling (section 1.4 blockers 1 and 2, pitfalls P7, P9 and P14), so that the session-3 launch, and
every later session's, can pass its full preflight. Edited: `rl/m9_g3_tests.py`, `rl/m9_g3_session.py`, `rl/m9_g3_snapshot.py`. Nothing else under `rl/`
was touched: no g1, g2, M8 or inherited module, no tool under `logs/`, and no registered contract value. Added: this record and the Git-ignored logs under
`logs/m9_g3_progression_fix/`. Nothing was written under `runs/`, under `docs/` apart from this record, or on D:.

| item | value |
| --- | --- |
| checkout | `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, branch `main` |
| HEAD = `origin/main` = the remote's `main`, at the start and at the end | `985daecefe58f6b422fdb49eeda951e59c3ed2eb` ("Add project runbook for running and reviewing sessions by hand"); `git status` clean at the start |
| read | `CLAUDE.md`; `docs/rl_runbook.md` in full; `docs/rl_m9_g3_resume_k_prep_decisions_2026-10-08.md`; `rl/m9_g3_tests.py`, `rl/m9_g3_session.py`, `rl/m9_g3_snapshot.py`; the chain functions of `rl/m9_g3_report.py`; `predecessor_assertions` of `rl/m9_g3_run.py`; `logs/m9_g3_resume_tools/three_passes.py` and the other three tools' use of `--session` |
| g3 source fingerprint before any edit | `64259b59b3e09d50` over the working tree, as the resume-k record pinned it. Over the committed blobs of `985daec` it is `569aff7c37149839` (section 4) |
| g3 source fingerprint after the last edit | **`15ddbb84932aa658`** over `m9_g3_contract.py 3e720ca8...`, `m9_g3_frontier.py 21ea1137...`, `m9_g3_probe.py 74c66f7d...`, `m9_g3_report.py 32ce1309...`, `m9_g3_rule.py 4a9e5320...`, `m9_g3_run.py 14e02d9a...`, `m9_g3_session.py ec0902a3...`, `m9_g3_snapshot.py 6542edf1...`, `m9_g3_tests.py 210320d9...`, `m9_g3_train.py d74f1891...`. Full digests: `logs/m9_g3_progression_fix/dev/fingerprint_final.txt`. Contract, frontier, probe, report, rule, run and train are unchanged from the resume-k record. Every file's working bytes equal the blob Git stores (`git hash-object` with and without filters), so any checkout of the commit reproduces this value |
| Python / libraries | 3.13.2; SB3 2.9.0; torch 2.14.0+cpu; numpy 2.5.3; gymnasium 1.3.0 (`python -B -X utf8` throughout) |

## 0. Result

- **Blockers 1 and 2 are fixed.** No unit test now asserts the line's later progression on the live repository. The refusals on missing records are checked
  on temporary layouts for k = 2, 3, 4 and 5, at the three stages of session k: before its approval, after its approval, after it completed. Both blockers
  were reproduced first on the unmodified tree (section 1).
- **`--session` is required** by every command of `rl/m9_g3_session.py` and by `rl/m9_g3_snapshot.py snapshot`. There is no default.
- **Predecessor results-record discovery is exact.** Only `docs/rl_m9_g3_s<j>_results_<YYYY-MM-DD>.md` with complete content is a record. A draft, a partial
  name, a partial file or a second record is a refusal.
- **The test count stays 29.** The runbook's holds-when lines ("29/29") stay valid.
- **The e2e digest is unchanged: `078f46c445d8adc5`, three times.**
- **The new g3 fingerprint is `15ddbb84932aa658`.**

## 1. The problems, reproduced before any edit

The simulation harness (section 6) ran the unmodified HEAD suite against a simulated live repository. Logs: `logs/m9_g3_progression_fix/before/`.

| stage simulated | test | result on `985daec` |
| --- | --- | --- |
| s3 approval present (the state of the s3 full preflight, step S13, and of the preflight inside `run`, S14) | `resume_inputs_and_previous_sessions_are_read_from_the_predecessors_records` | **FAIL**: `no document problem for sessions 2 and 3; session 4 lacks s3's two records: got '([], [], 1)', want '([], [], 2)'` (blocker 1, exactly as the runbook predicted) |
| s3 completed (s3 approval, `runs/m9_g3/s3`, one PASS increment `2026-10-09_incr_m9_g3_s3`, the s3 results record: the state of session 4's Part B) | the same test | **FAIL**: `a missing predecessor is named (session 4)` (blocker 2, line 1191) |
| the same | `identity_approval_write_guard_and_the_reused_tape` | **FAIL**: `session 4 adds no tree until s3's increment is recorded` (blocker 2, line 1376) |

Pitfall P7: every subcommand of `m9_g3_session.py`, and `m9_g3_snapshot.py`, defaulted `--session` to 1. Pitfall P9: `results_records(j)` globbed
`docs/rl_m9_g3_s<j>_results_*.md`, so a draft such as `rl_m9_g3_s3_results_draft.md` was taken as the record whenever the final record was absent. With
the final record present too, the preflight refused with a misleading "2 results record(s)".

## 2. Every change

### 2.1 Items 1 and 2: no unit test reads the line's later progression from the live repository (`rl/m9_g3_tests.py`)

Each assertion that depended on how far the line had advanced, what made it depend on that, and its replacement:

| where (HEAD line) | old assertion | false once | replacement on the live repository (holds at every stage) | replacement on temporary layouts |
| --- | --- | --- | --- | --- |
| `resume_inputs_...` 1191 | `predecessor_problems(4)` names "no final-state record" | s3's tree has its `session/final_state.json` (s3 completed) | none (a later session's predecessor check is a launch-day check: `preflight --session k`) | for k = 2..5: session k+1 names session k's missing final state before and after k's approval, not after k completed |
| `resume_inputs_...` 1192 | `unregistered_predecessors(4) == [3]` | s3's increment exists | `unregistered_predecessors(3) == []` (s1 and s2 are registered forever), and `unregistered_predecessors(4) == ([3] if predecessor_tree(3) is None else [])` | `[k]` before k completed, `[]` after, `[k]` again with two increments (ambiguous); a registered session (k = 2) is never unregistered |
| `resume_inputs_...` 1193 | `predecessor_tree(3) is None` | s3's increment exists | s2's increment is unique and its registered entry is used (fixed facts) | `None` before completion; after it, the entry discovered from the increment's record (name, root, increment, files, no record problem); `None` with two increments; a FAIL record, a record naming another tree, or a manifest at another digest is a record problem; a registered session keeps its registered entry at every stage |
| `resume_inputs_...` 1200 | `len(predecessor_doc_problems(4)) == 2` | **the s3 approval is written: 1 (blocker 1)**; the s3 results record: 0 | `predecessor_doc_problems(2) == predecessor_doc_problems(3) == []`, and s1's and s2's results records found by the exact rule with nothing refused (fixed once recorded) | 2 problems before k's approval, 1 after, 0 once k completed, every problem naming session k; session k's own document problems stay `[]` at every stage of k; once complete, session k+1 pins k's approval and results record last |
| `identity_approval_...` 1376 | `trees_for(4)` names == `trees_for(3)` names | s3's increment exists | `trees_for(4)` names == `trees_for(3)` names + (`["m9_g3_s3"]` when `predecessor_tree(3)` exists, else nothing) | `trees_for(k+1)` = the seven + s1 .. s(k-1) before k completed, + `m9_g3_s{k}` after; nothing added when ambiguous |

**How the temporary layouts work.** `progression_layout(d)` is a context manager. For the duration it rebinds the three module roots of
`rl/m9_g3_session` that the progression functions read: `REPO_ROOT` (whose `docs/` holds the approvals and results records), `LINE_ROOT` (`runs/m9_g3`) and
`BACKUP_ROOT` (the D: increments). They point at directories under a temporary directory, and are restored in `finally`.

The builders `layout_record` and `layout_increment` write each session's approval, results record, final-state record and increment there. The
increment uses `rl/tools/runs_backup.py`'s file names and a PASS record naming the tree. The production code under test runs unmodified. The registered
predecessors s1 and s2 keep their registered entries; none of their files is read in a layout.

The checks live in two helper functions, `progression_on_temporary_layouts` and `results_record_rule_on_temporary_layouts`, called at the end of
`resume_inputs_and_previous_sessions_are_read_from_the_predecessors_records`. That keeps the count at 29 (D2).

**Every other test that reads real session state was reviewed and holds at every stage unchanged.** None of them names a session after s2:

- `real_model_resume_round_trip_on_the_predecessors_final_checkpoint`: the registered s1 and s2 only.
- `resume_inputs_...`: the s1 and s2 records, `resume_inputs(2)` / `(3)`, the H6 assertions, `line_consequence` on recorded rows, and a tampered copy of
  the chain in a temporary directory.
- `identity_approval_...`: `trees_for(1..3)`. `write_guard_roots(1..3)`: the session's own tree is excluded by name, and a later tree only adds a
  protected root. `identity(1)` / `(3)`, and approval round trips on temporary files.
- `the_protected_trees_equal_their_increments_and_the_pins_hold`: `trees_state(3)`, the nine fixed trees.
- `snapshot_tool_roundtrip` with `--session 3`: `doc_files(3)` and `log_dirs(3)` never include s3's own records. `logs/m9_g3_s3_prep` is in the set
  whatever it contains, as designed in the resume-k record, D6.

The git-state gate is independent of the stage, but fails by design on any uncommitted edit.

### 2.2 Item 3: `--session` required (`rl/m9_g3_session.py`, `rl/m9_g3_snapshot.py`)

- **`rl/m9_g3_session.py`:** every subcommand (`status`, `preflight`, `approval-template`, `run`, `verify-run`, `report`) declares
  `--session ... required=True`. Without it, argparse exits 2 with `the following arguments are required: --session`. The module docstring shows
  `--session k`.
- **`rl/m9_g3_snapshot.py`:** `--session` has no default (`None`). `snapshot` without it is refused by the parser (`ap.error`, exit 2, message naming
  `--session`) before anything is read or written. `verify` and `powershell` do not use the session and are unchanged.
  - One parser serves all three commands, so argparse cannot make the option required for `snapshot` alone. A parser-wide `required=True` would break
    the runbook's S11 forms `verify --dest` and `powershell --dest --out` (D5).
- **Callers checked:**
  - `logs/m9_g3_resume_tools/launch_detached.ps1` passes `--session $Session`.
  - `write_approval.py`, `wait_session.py` and `three_passes.py` already require their own `--session`.
  - Every command in the runbook passes `--session $K`.
  - The Python functions' `k: int = 1` defaults are not part of the CLI and are unchanged (D5).
- **Tests (in `snapshot_tool_roundtrip`):**
  - A snapshot without `--session` exits 2, names `--session` and writes nothing.
  - The existing overwrite refusal now passes `--session 3` and checks the "exists (never overwritten)" message. It used to rely on the default, and
    would otherwise now pass for the wrong reason.
  - For each of the six commands of `m9_g3_session.py`, the parser refuses without `--session`, and with `--session 7` the command is dispatched with
    k = 7. The six dispatch targets are stubbed for this check, so a parser that stopped refusing could never start a preflight, a run or a verification.

### 2.3 Item 4: exact predecessor results-record discovery (`rl/m9_g3_session.py`)

`results_record_scan(j)` replaces the glob. It looks only at `docs/`, not recursively.

**The rule.**

1. **Name.** A results record of g3 session j is a regular file named exactly `rl_m9_g3_s<j>_results_<YYYY-MM-DD>.md`
   (`RESULTS_RECORD_NAME = rl_m9_g3_s(?P<j>[1-9][0-9]*)_results_(?P<date>YYYY-MM-DD)\.md`, full match, exact case). The date must be a real calendar date
   (month 1-12, day within the month).
2. **Drafts and partial names.** Any other entry of `docs/` whose name begins with `rl_m9_g3_s<j>_results`, in any case, is **refused**. Examples: a
   draft, `..._draft.md`, `.md.tmp`, `.md~`, `2026-10-9`, `2026-13-01`, `2026-02-30`, `_.md`, no date, upper case, `.MD`, or a directory with the
   registered name. Windows file names are case-insensitive, so case-insensitive detection is needed. Session 31's records do not start with session
   3's prefix (`s31_` against `s3_r`), so they are never counted for session 3 (tested).
3. **Partial files.** A file with the registered name is **refused as partial** unless:
   - it is non-empty;
   - it is UTF-8 without a NUL byte;
   - it ends with a newline;
   - its first line starts with the title `# M9-g3-s<j> results (<date>)`, carrying the session and the date of its own name;
   - a `## ` section follows the title.

   A leading UTF-8 byte-order mark and CRLF line ends are tolerated (an editor's BOM, Git's `autocrlf`). s1's and s2's records satisfy the rule
   unchanged (tested on the live repository).
4. **What the preflight requires.** `predecessor_doc_problems(k)` needs, for each predecessor j, its approval and **exactly one** accepted record. Every
   refused entry is a problem (`session j: refused docs/<name>: <why>`), and zero or two accepted records is a problem. `results_records(j)` returns the
   accepted records only, so `identity(k)`, the approval and the snapshot never pin a draft. For s1 and s2 the accepted set equals the old glob's, so
   `identity(3)`'s document set is unchanged.

**Why refuse rather than ignore.** A file beside the record that looks like it is an ambiguity a person must resolve: move the draft out of `docs/`.
Silently ignoring it would let a misnamed final record pass as "missing" and a stray draft go unnoticed. Refusing follows the resume-k record's D2: ambiguity
is never resolved by guessing.

**The title check.** It ties the file to its session and its date. It catches a predecessor's record copied under the next session's name, and a
title-only stub.

**Consequence for every launch session.** Its results record must open with `# M9-g3-s<k> results (<date of its file name>)`, contain a `## ` section and
end with a newline. Copying the structure of `docs/rl_m9_g3_s2_results_2026-10-08.md`, as the runbook's step S20 says, satisfies this.

**Tests** (`results_record_rule_on_temporary_layouts`), every case on a temporary layout:

- the record is discovered;
- each of the eleven bad names beside it is refused, named by the document check and never pinned, while the record stays the only one discovered;
- a directory with the registered name is refused;
- two complete records are refused;
- **a draft alone is never taken for the record**: none is discovered, the draft is refused, and the check names both;
- eight partial contents are refused, each not discovered and refused by the preflight check: empty, no final newline, a NUL byte, not UTF-8, s2's
  record copied under s3's name, a title with another date, the title alone, no title;
- CRLF and a BOM are accepted;
- session 31's record is not session 3's.

## 3. Decisions (none changes a registered measure, threshold, rule, schedule, cap or training setting; each can be overruled)

| # | decision | why |
| ---: | --- | --- |
| D1 | the later progression is never asserted on the live repository; the stages are built on temporary layouts by rebinding `REPO_ROOT`, `LINE_ROOT` and `BACKUP_ROOT` of `rl/m9_g3_session` in a restoring context manager | the request (tests that check refusal on missing records build their own states); the production functions read exactly these three roots, so no production code had to change for testability; a live check is kept only where it holds at every stage |
| D2 | the test count stays **29**: the new checks are inside the two tests that already held the progression assertions (`resume_inputs_...`) and the CLI checks (`snapshot_tool_roundtrip`) | the runbook's holds-when lines (S4, S13: `m9 g3 unit suite: 29/29 passed`) and the resume-k record's B1 stay literally valid |
| D3 | the exact results-record rule of section 2.3: exact name, refusal of near-misses in any case, content completeness with the title, BOM and CRLF tolerated | the request (registered pattern only; refuse drafts, multiple matches and partial files); see "why refuse" and "the title check" above |
| D4 | refused entries are preflight problems and are never pinned; `results_records(j)` returns the accepted records only | a draft must never enter an identity, an approval or a snapshot |
| D5 | `--session` is required by every `m9_g3_session.py` command and by `m9_g3_snapshot.py snapshot`, with no default; `verify` / `powershell` unchanged; the Python functions' defaults unchanged | the request names the two CLIs; the runbook's S11 forms keep working; programmatic callers pass k explicitly |
| D6 | `rl/m9_g3_tests.py` was normalised from CRLF to LF (no content change; `git diff` shows content lines only) | its attribute is `text eol=lf`, so any checkout writes LF; the fingerprint hashes working-tree bytes; with CRLF the B0 value depended on how the file happened to be written (section 4) |
| D7 | logs in a new `logs/m9_g3_progression_fix/` (Git-ignored); the three passes ran with `--out logs/m9_g3_progression_fix/final`, NOT the tool's default `logs/m9_g3_s3_prep/final` | the s3 launch's Part B writes `logs/m9_g3_s3_prep/final/passes.json` there and the tool refuses to overwrite it; that directory is in the s3 snapshot's set. `logs/m9_g3_progression_fix/` is not in any snapshot set (`log_dirs` is unchanged) |
| D8 | this record is NOT added to the pinned documents (`doc_files`) | that would be a further production change outside the request; the fix itself is pinned through the code digests in `identity(k)` and the snapshot |
| D9 | the CLI check stubs the six dispatch targets of `m9_g3_session.main` | a regression of the parser must fail the test, never start a preflight that runs this very suite, a run, or a verification |

## 4. The fingerprint and the line ends of `rl/m9_g3_tests.py`

- **At `985daec`** the working copy of `rl/m9_g3_tests.py` had CRLF line ends (`git ls-files --eol`: `i/lf w/crlf attr/text eol=lf`). The other nine g3
  modules had LF.
- **The fingerprint follows the working-tree bytes.** `three_passes.fingerprint()` hashes working-tree bytes, so it gave `64259b59b3e09d50`, the
  resume-k record's value. The same commit's blobs, which is what a fresh checkout writes, give **`569aff7c37149839`**. B0 at `162e48b` / `985daec` held only
  in this particular working copy.
- **This session normalised the file to LF** (D6). After the last edit:
  - every g3 module's working bytes equal its stored blob;
  - the fingerprint **`15ddbb84932aa658`** is reproducible from the commit by any checkout;
  - `git diff --check` no longer prints the CRLF notice.
- **Intermediate value.** The value with the edits but the old CRLF line ends was `d2bdd7fa8634789a`. It was never used for a pass.

## 5. Verification (all offline, `python -B -X utf8`, zero native ticks; logs under `logs/m9_g3_progression_fix/`)

Every row is on the FINAL working tree (fingerprint `15ddbb84932aa658`) unless marked otherwise.

| check | result | log |
| --- | --- | --- |
| **three passes**: `python -B -X utf8 logs/m9_g3_resume_tools/three_passes.py --session 3 --allow-git-gate --out logs/m9_g3_progression_fix/final`, 20:35:09 to 22:30:14 (local time) | **`THREE_CONSECUTIVE_PASSES_EXCEPT_THE_GIT_GATE`**, exit 0, fingerprint `15ddbb84932aa658` before and after every pass. Unit **28/29, 28/29, 28/29** (1,007.1 / 898.5 / 1,926.2 s), the ONLY failure each time `tracked_files_are_unchanged_except_the_authorised_edit_and_only_new_files_exist`: its input is this uncommitted tree (the three modified g3 modules). **e2e PASS x 3, digest `078f46c445d8adc5` each time** (921.4 / 1,040.0 / 1,112.1 s), with the same figures as the resume-k record. s1: INCONCLUSIVE D = R = 2,128, 19 moves, pointer 1,920, 3 BLOCKED_BY_RECHECK, 1,850 episodes, 94 replays exact. s2: INCONCLUSIVE, 4 BLOCKED_BY_RECHECK, resumed at 180,088, periodic checkpoints 282,488 ... 896,888, deferred 8 and 137, 7 failed attempts at the blocked pointer, line CONTINUE. Pass 3's unit run was slower under memory pressure (section 7) | `final/passes.json`, `final/pass{1,2,3}_{unit,e2e}.txt`, `three_passes_stdout.txt` |
| g3 rule self-test | **PASS** (0 problems), s1 `dea9965a3989bce5`, line `d9d82885703c016d` | `suites/g3_rule_self_test.txt` |
| registered digests | g3 contract `4cd1deaec0f0333b394f0ac85bc0f3c494c117e63eacc0caf5e80e0929b8e040`; line contract `90eac1a6c6682a397fc8e85abdf5b1d8ab3f38b75a80ae08709932286d319a31`; frontier `60e174a61c02e1848a25ba7951a5aaf047060a68b9496a8aea82b0d32704b634`; s1 rule `dea9965a3989bce54a27acc0a33d506664789e4a316f1a0b6aaa512ee66c23a9`; line rule `d9d82885703c016d147878886461156da7050176615bfd923ec66cb446cf1998`; g2 `8dfd44c6a8b7e319` / `1aadc7a6b2ff85bd`; g1 `6958857ed2dfd1c5`: **all unchanged** | `suites/b2_digests.txt` |
| g1 evaluation suite | **29/29** (77 s) | `suites/g1_eval_unit.txt` |
| g2 suite | **28/29** (595 s): only `tracked_files_are_unchanged_and_only_new_files_exist`, got the three modified g3 modules, want `[]` (the documented git gate; 29/29 once committed with nothing staged) | `suites/g2_unit.txt` |
| g1 unit suite | **61/63** (358 s): `identity_names_every_registered_pin`, the documented pre-existing failure: still exactly **30** `rl/m9_*.py` files outside g1's list, since no `rl/` file was added. Plus the same git gate on the same three files. 62/63 once committed | `suites/g1_unit.txt` |
| `verify-run --session 1` (output outside `runs/`) | **`ok: true`, 0 problems**: metadata 2,436 files / 5,327 JSONL lines / 0 failures, 8 checkpoints, the frontier rebuilt equal to the log (pointer 2,220, 4 moves, 13 attempts, 29 deferred), rule NULL and line CONTINUE recomputed equal to recorded, 43 replays exact, `tier0_without_replay` 0. Exactly the s1 record's and the resume-k record's numbers | `final/verify_run_s1.json` |
| `verify-run --session 2` | **`ok: true`, 0 problems**: metadata 2,187 / 5,780 / 0, 13 checkpoints, frontier pointer 2,040, 9 moves, 22 attempts, 30 deferred, rule INCONCLUSIVE / 2,128 / none and line CONTINUE recomputed equal to recorded, 68 replays exact, `resume_checks.chain.ok` true, `equal_to_predecessor_record` true. Exactly the s2 record's numbers | `final/verify_run_s2.json` |
| the edited tests alone, during development (before D6: the CRLF form of the test file, identical content) | `resume_inputs_...` PASS (1.3 s). `snapshot_tool_roundtrip` PASS (515.3 s) on the second attempt: the first attempt died with a `MemoryError` in the snapshot subprocess while hashing, with system commit exhausted (section 7) | `dev/unit_resume_inputs_1.txt`, `dev/unit_snapshot_roundtrip_{1,2}.txt` |
| mutation check of the new checks (in memory; on the CRLF version of the test file, identical content) | **all three mutants killed**: the old glob discovery (the draft beside the record is discovered), an ambiguity-blind `predecessor_tree` (two increments still give a tree), and the content check reduced to "non-empty" (a record without a final newline is accepted). Both helpers pass unmutated | `dev/mutation_check.txt`, `harness/mutation_check.py` |
| `git diff --check` | clean (no CRLF notice since D6) | |
| `preflight --session 3 --skip-unit` | see section 8 | `final/preflight_dry_run_s3.txt` |

## 6. The progression proof by simulation (nothing written into `docs/`, `runs/` or D:)

**The harness.** `logs/m9_g3_progression_fix/harness/sim_progression.py` (sha256 `a27dbda6...`) was run from outside the repository. It simulates the
LIVE repository at a later stage of the line, then runs the g3 tests in-process:

- `REPO_ROOT` of `rl/m9_g3_session` is rebound to an overlay in `%TEMP%`. The overlay's `docs/` is a byte copy of the real `docs/` (393 files, verified
  file by file) plus the simulated records.
- `run_root(3)` and `increment_dirs_for(3)` answer with a simulated `runs/m9_g3/s3` (session records) and one simulated PASS increment
  `2026-10-09_incr_m9_g3_s3` naming it. They do so ONLY while the module's `LINE_ROOT` and `BACKUP_ROOT` are the live ones, so the suite's own temporary
  layouts see the unmodified functions.
- `_rel`, `write_guard_roots` and `git_problems` render the real repository's paths, the real `docs/` and the real tracked files exactly as the live code
  does.
- The temporary directory is removed at the end; each log ends with `temporary directory removed: True`.
- Limitation: `snapshot_tool_roundtrip` runs its snapshot in a subprocess against the real repository, which does not see the simulation. Its dependence
  on the stage is argued in section 2.1: `doc_files(3)` and `log_dirs(3)` never include s3's own records.

| stage simulated | live view the tests saw (printed before and after the run) | result on the final tree | log |
| --- | --- | --- | --- |
| **s3 approval present** (the s3 full preflight and the preflight inside `run`) | `approval_path(3)` present; `predecessor_doc_problems(4)` = 1 problem (s3 has 0 complete results records); `unregistered_predecessors(4)` = `[3]`; `trees_for(4)` = the nine | **the whole unit suite 28/29**, failing only the git gate (1,349 s); every progression test passed | `sim/sim_approval_full_unit.txt` |
| **s3 completed** (session 4's Part B, B1: the three passes) | s3 approval and results record `docs/rl_m9_g3_s3_results_2026-10-09.md` discovered by the exact rule; `predecessor_tree(3)` discovered from the simulated increment with no record problem; `unregistered_predecessors(4)` = `[]`; `trees_for(4)` = the nine + `m9_g3_s3`; `predecessor_doc_problems(4)` = `[]` | **the whole unit suite 28/29**, failing only the git gate (1,021 s) | `sim/sim_completed_full_unit.txt` |
| **s3 completed + s4 approval present** (session 4's full preflight) | as above, `approval_path(4)` present | the three tests that read the line's real state (`real_model_...`, `resume_inputs_...`, `identity_approval_...`): **3/3** (359 s) | `sim/sim_s4approval_progression_tests.txt` |
| live (control, nothing simulated) | the real state | `real_model_...`, `resume_inputs_...`: **2/2** | `sim/sim_live_control.txt` |
| before the fix (HEAD's suite), the two stages above | | **FAIL** as in section 1 | `before/sim_{approval,completed}_head.txt` |

`sim/superseded_sim_approval_interrupted_crlf.txt` is a run stopped by me after 9 tests, when the line-end normalisation (D6) was decided. It is superseded.

## 7. The machine during this session (relevant to B8 of every launch)

**At the start.** IntelliJ (`idea64`, 2.0 GB private), `vmmem` (4.1 GB private) and five `claude` processes were open.

**The development snapshot test.** Its first run died with a `MemoryError` when system commit ran out. Just after it, 8,132 MB of physical memory was
available and 10,833 MB of commit was free; the commit limit is 32,166 MB. The owner then closed IntelliJ, and commit free rose to about 14 GB.

**Sampled every 2 s** by `harness/mem_sampler.py`, logged in `dev/mem_samples.txt`:

- **Two short-lived `node` processes**, PID 40404 at about 19:56 and PID 33696 at about 20:03 (local time), reached **46,346 MB** and **33,567 MB**
  private. They drove system commit free down to **51 MB**, then exited. Neither was started by a command of this session; their origin was not
  determined.
  - This resembles the 17,100 MB `node` in the resume-k record, section 6.
  - The g3 suites running at the time survived, but the native session's memory guard would have ended a real session INCOMPLETE.
- **Later**, IntelliJ (up to 1,918 MB) and Avidemux (6,170 MB private, a recording from `D:\SmashRecordAttempts`) were reopened. Over the whole session,
  867 samples fell below 4,096 MB of commit free. Pass 3's unit run took 1,926 s against about 900-1,000 s. The owner closed both during the g2 suite.
  At the preflight dry run, 8,512 MB was available and 13,173 MB of commit was free.

**Before S11-S15 of a launch:** check for `node` processes, close the IDE and video tools, and keep the machine idle.

## 8. The preflight dry run on the final working tree

`python -B -X utf8 rl/m9_g3_session.py preflight --session 3 --skip-unit` ran at 2026-10-09T02:58:57Z. It exited 1 with `ok: false` and **7 problems**,
with stderr empty. The 7 are: the three modified tracked files, each reported once as a tracked change and once as a git status entry (6), and the missing
approval (1). Nothing else. On the committed tree with nothing staged, only the last line remains (B6).

```
tracked file differs from HEAD and is not an authorised edit: rl/m9_g3_session.py
tracked file differs from HEAD and is not an authorised edit: rl/m9_g3_snapshot.py
tracked file differs from HEAD and is not an authorised edit: rl/m9_g3_tests.py
git status shows an entry other than a new file or the authorised edit:  M rl/m9_g3_session.py
git status shows an entry other than a new file or the authorised edit:  M rl/m9_g3_snapshot.py
git status shows an entry other than a new file or the authorised edit:  M rl/m9_g3_tests.py
no approval record at docs\rl_m9_g3_s3_approval.json (the session is not authorised)
```

Everything else passed:

- **Predecessor:** `predecessor.problems == []` and `unregistered_earlier_sessions == []`. The trees `m9_g3_s1` and `m9_g3_s2` are both "registered". The
  four predecessor documents are named: the s1 and s2 approvals and results records, found by the exact rule.
- **Resume inputs:** expect `e6d2c7d4...` / `cc7480df...` / `81fa52c2...`; members `8afdb8ad...` / `18013ea1...`; counters 1,864,900 / 3,630; the chain
  checked over 2 sessions with rows [1, 2]; no problem.
- **Protected trees:** the **nine trees ok** with the registered facts (rd1 166 `e81226d7`, rd2 62 `6775281e`, rd3 77 `b6e13ecb`, rd4 93 `7ff2b29d`,
  m9_g1 2,740 `92ba5481`, m9_g1_eval 1,393 `ab3e6c61`, m9_g2_s1 9,779 `4ad2c3dc`, m9_g3_s1 4,935 `d12966c1`, m9_g3_s2 4,478 `a6965387`).
- **D: coverage:** 432,800 source files, **0 uncovered**, 14 increments.
- **Readiness:** ok (8,512 MB available, 13,173 MB commit free, C: 100.9 GiB, D: 1,648.4 GiB).
- **Budget:** 7,780 s pessimistic, fits. The close is projected at 436.4 s over nine trees (2,899,055,876 bytes); the total with it is 7,916.4 s.
- **Pins:** executable `30a3913b...`; runtime files and frozen configuration at the pins; the reused tape at `81fa52c21078b2c2 / d915fab920554774`; CVars
  absent; the status table verified.
- **Lineages:** `T_clear` 2,326 words `5eccd4e2d5d77b25`, `T_t` 2,315 words `de1228be4146b720`.
- **Git:** `git_head` `985daec...`; the only new file is this record.

Output: `logs/m9_g3_progression_fix/final/preflight_dry_run_s3.txt`.

## 9. Files

| path | state | commit? |
| --- | --- | --- |
| `rl/m9_g3_tests.py`, `rl/m9_g3_session.py`, `rl/m9_g3_snapshot.py` | modified tracked | **yes** |
| `docs/rl_m9_g3_progression_fix_2026-10-08.md` | new (this record) | **yes** |
| `rl/m9_g3_contract.py`, `rl/m9_g3_frontier.py`, `rl/m9_g3_probe.py`, `rl/m9_g3_report.py`, `rl/m9_g3_rule.py`, `rl/m9_g3_run.py`, `rl/m9_g3_train.py` | unchanged | |
| `logs/m9_g3_progression_fix/**` (`before/`, `dev/`, `sim/`, `final/`, `suites/`, `harness/`, `three_passes_stdout.txt`) | new, Git-ignored | no |
| `logs/m9_g3_s3_prep/` | not created | |
| `logs/m9_g3_prep/`, `logs/m9_g3_s2_prep/`, `logs/m9_g3_resume_tools/`, `logs/m9_g3_resume_k_prep/`, every `runs/` tree, D: | untouched | |

## 10. For the session-3 launch (Part B of the resume-k record, section 8, with these values)

- **B0:** the fingerprint of the committed `rl/m9_g3_*.py` is **`15ddbb84932aa658`**. It replaces `64259b59b3e09d50` in B0 and in the runbook's step S3.
  HEAD = `origin/main` = the commit that carries the three modules and this record. Nothing staged, and `git status --porcelain --untracked-files=all` empty.
- **B1:** `three_passes.py --session 3` WITHOUT `--allow-git-gate`. Expected: unit **29/29** three times, e2e **PASS `078f46c445d8adc5`** three times,
  fingerprint unchanged; g3 rule self-test PASS; g1 evaluation 29/29; g2 29/29; g1 62/63 with only `identity_names_every_registered_pin`.
- **B13** (generic k >= 4, no preparation round) now holds for the unit suite: the progression tests pass at every stage (section 6).
- **The results record of every session** must satisfy the exact rule of section 2.3. Never leave anything named `rl_m9_g3_s<k>_results*` in `docs/` other
  than the final record.

**Statements of `docs/rl_runbook.md` that this record supersedes.** The runbook was not edited, since this session may write only this record under `docs/`:

- section 1.4, blockers 1 and 2: fixed. Blocker 3 was resolved by commit `985daec`;
- section 1.5 and step S3's fingerprint `64259b59b3e09d50`: now `15ddbb84932aa658`;
- the bold line before step S3.0 and pitfall P7 (`--session` defaults to 1): a missing `--session` is now a parser refusal (exit 2);
- pitfall P9: a draft is now refused, and never taken as the record;
- pitfall P14 and the "Blocker 2" bullet of section 3.5: fixed.

## 11. git status at the end

HEAD = `origin/main` = the remote's `main` = `985daecefe58f6b422fdb49eeda951e59c3ed2eb`. There was no commit, push, branch or pull request. Nothing is staged,
and `git diff --check` is clean. No compiled module was written: no `.pyc` is newer than the session's start listing, and the `__pycache__` directories are
the pre-existing ones. The temporary directories of the suites and the harness were removed, and no `BattleShip.exe` ran at any time.

```
 M rl/m9_g3_session.py
 M rl/m9_g3_snapshot.py
 M rl/m9_g3_tests.py
?? docs/rl_m9_g3_progression_fix_2026-10-08.md
```

`logs/m9_g3_progression_fix/` is Git-ignored and therefore not shown.
