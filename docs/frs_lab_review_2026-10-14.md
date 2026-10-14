# Fast-route lab review (2026-10-14)

## Verdict

**Ready for night 1.** There is no blocker. On every code path that night 1 runs, the lab cannot write into the checkout (apart from the
self-test's git-ignored `logs/` probe), `runs/`, `D:/BattleShip_runs_backup/`, `D:/BattleShip_source_snapshots/` or
`D:/BattleShip_exe_archive/`. After the one-time import it cannot read `runs/`, the D: evidence roots, the TAS or the human recordings. This
rests on reading the code, the test suite (31/31), the smoke run's integrity block, and two facts observed after the self-check and the smoke:
the unchanged import folder and the game's only AppData file. The guard's general claim is still stronger than what it implements. On Python
3.13.2, `shutil.copy2` (through `_winapi.CopyFile2`) and writes through a junction pointing outside the lab get past the guard (S1, S2, shown
by a zero-tick probe). No lab code performs either operation. Any code fix moves the code digest away from the smoke-tested
`0b248a9e30304325`, so I recommend running night 1 on the current code, starting `night.sh` with its console redirected into the lab (S4: a
documentation-only workaround), and fixing S1 to S6 before the first campaign night.

## Scope, state and method

- Checkout `C:/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip`: HEAD = origin/main = remote main = `39e20ca` ("Add the fast-route lab
  runner"). The tree was clean with nothing staged. All nine `rl/frs_*.py` files and both `docs/frs_lab_*.md` files are committed. `39e20ca`
  adds 11 files and modifies none.
- Read: `docs/project_handoff.md`, `docs/rl_decisions_2026-10-14.md`, review items M1, M5, S7, S8, S10, S11 and section 5 of
  `docs/rl_m8_fast_route_proposal_review_2026-10-14.md`, `docs/frs_lab_guide.md`, `docs/frs_lab_index.md`, every `rl/frs_*.py` file (the tests
  in the parts that matter here), `logs/frs_prep/phase1_plan.md` with A1 and A2, and the registered helpers the lab calls (`m8_rd_worker._step`
  / `_tick0` / `RealBackend`, `m7_runtime.prepare_worker_runtime`, `m7f_trace.run_stepping_trace`, `battleship_process.build_child_env`,
  `m8_sd2_select.Archive6.adopt`, the sd1/sd2 fingerprint globs).
- Read only: `C:/BattleShip_lab/smoke_2026-10-14/` (selfcheck.json, summary.json, report.md, config.json, run_log.jsonl, the code manifest),
  `C:/BattleShip_lab/import/` (file list against `import_manifest.json`), `C:/BattleShip_lab/frs_lab_index.md` and `%APPDATA%/BattleShip/`
  (listing only).
- Zero native ticks. No BattleShip.exe, self-check, smoke, planner, night.sh or lab run. One pure-Python probe (`guard_probe.py`) armed the
  guard in a child process on a fake repo and lab, and wrote only under `logs/frs_review/lab_review_2026-10-14/`.

## Test suite

`python -B rl/frs_tests.py`: **31/31 passed in 166 s**, exit 0, with Python 3.13.2 (the interpreter the smoke used). `unit_run_code_manifest`
reports 34 files and digest `0b248a9e30304325`, the same digest as the smoke run (A2). The full output is in
`logs/frs_review/lab_review_2026-10-14/tests_output.txt`.

## The eight review items

1. **Write safety: PASS for the code paths the lab runs, with S1, S2 and S3.**
   - G1 (`rl/frs_guard.py:101-122`) refuses a relative root, a drive root, any `runs` component, a root inside or containing the checkout, and
     a root overlapping a D: evidence root (18-case matrix test).
   - G2 is armed in each process:
     - in the run's main process before the lock and the pool (`rl/frs_lab.py:237`);
     - in every worker as its first statement (`rl/frs_worker.py:218-219`, from the spec built after the main guard, `rl/frs_lab.py:205`);
     - in the verify threads, because they are threads of the guarded main process;
     - in the self-check (`rl/frs_lab.py:278`), the planner (`:408`) and the import (`:123`).
   - The only checkout write is the self-test parent's removal of its own probe under the git-ignored `logs/`, made only if the guard failed
     (`rl/frs_guard.py:451-453`).
   - Across all 34 modules in the code manifest, the only link the lab creates is `m7_runtime.py:135`, whose target `import/exe/.tcc` is
     inside the lab. Nothing calls `shutil.copy2`, and `m8_rd_session.py:447`'s `copytree` is checked at its destination.
   - Null-device exception (A1): see N1. It is as narrow as claimed.
   - Writes outside Python's reach: see N2. They are the game's `ssb64.log` and, probably, git's index refresh.
2. **Read safety: PASS, with N3.**
   - G3 (`rl/frs_guard.py:198-211`) refuses `open`/`listdir`/`scandir` under `<checkout>/runs`, under the three D: roots, and on paths
     containing any fragment of `m8_rd_worker.FORBIDDEN_FRAGMENTS` plus `replay/recordings`. This covers `tas_input_2/mario_743.btti`.
   - Only `import` gets an allowlist of exact files (`rl/frs_lab.py:117,123`).
   - The game's environment drops `SSB64_BTT_INPUT` (`battleship_process.py:239`).
   - The import cannot run twice:
     - `import/` existing refuses it before any read, lock or guard (`rl/frs_lab.py:113-115`);
     - the copy is made in `import.tmp` and moved in place with one atomic `os.replace` (`:168`);
     - every run re-hashes all 125 copies (`:176-185`) and the pinned executable directory (`frs_verify.py:78-89`).
   - After the self-check and the smoke, `import/` holds exactly the 125 manifest copies plus the manifest: nothing new, nothing changed.
3. **Registered evidence: PASS, with N5.**
   - No tracked file is modified.
   - The registered fingerprints glob `rl/m8_sd1_*.py` / `rl/m8_sd2_*.py` plus their `tools/` folders (`rl/m8_sd1_session.py:112`,
     `rl/m8_sd2_session.py:114`), and `rl/frs_*` matches neither.
   - At run time the guard refuses every checkout write.
   - The registered `Archive6.adopt` refuses a lab archive because of the extra `frs_lab` session event (`rl/m8_sd2_select.py:255-259`,
     tested at `rl/frs_tests.py:452`).
4. **Constraints: PASS.**
   - The source guard test rejects `random`, `seed(`, TAS and recording fragments, and integer literals of 1,000 or more outside a named
     allowlist (`rl/frs_tests.py:1251-1281`).
   - E7's reference (1,885) and bound (1,860) are read from the imported route (`rl/frs_run.py:362-366`).
   - The tick contract (consumed_tick == i, input_tick == i + 1, step_count == i + 1, `m8_rd_worker.py:456`) is checked on every prefix word
     and every burst word, including continued segments. `i` is absolute in both loops (`rl/frs_worker.py:93,141-143`).
5. **The arms: PASS.**
   - Arms table: `rl/frs_run.py:49-50`. CONTROL has one segment and asks no boundary question (`rl/frs_worker.py:163`). It is tested equal to
     `run_iterate` on 69 stub jobs.
   - E6 is off in both arms (`rl/frs_run.py:355`). The E6-on equality check (200/200 draws) and the census run at every self-check.
   - CONT differs only in `max_segments` 4. Its trigger is M1's F3 condition: a reach in the last 20 words whose key is new or that is
     strictly shorter (`rl/frs_archive.py:230-244`). The whole continued job is ingested as one burst (tested).
   - Draw keys: `<archive_id>_frs_<label>` (`rl/frs_archive.py:47-51`). Both arms start at the same first iteration. The first 120 words of
     the 480-word stream equal the 120-word stream (tested).
6. **Verification: PASS, with S3, N6 and N7.**
   - Each candidate is replayed twice by `run_stepping_trace` in fresh processes with `m8_rd_session.FLAGS_VERIFY`, in-run on a borrowed slot
     and at the close on up to 5 threads.
   - Any disagreement with the claim or between the two replays gives NONDETERMINISTIC, which makes the run LAB_INVALID
     (`rl/frs_verify.py:175-197`, `rl/frs_run.py:650-651`). A provenance failure is also LAB_INVALID (`:627-630`).
   - Clears are reported only when VERIFIED (`rl/frs_report.py:27-34`). ERROR and unverified leftovers are shown as candidates.
   - The smoke's reference replay and in-run clear were both VERIFIED, with at most 10 BattleShip processes.
7. **The night: PASS, with S4, S5, N6 and N11.**
   - Order and stop rule:
     - `night.sh` runs the self-check, then six runs in ABBA order (`rl/frs_lab.py:415-426`, test `unit_lab_planner`);
     - every step has `|| { ...; exit 1; }`, so any non-zero exit stops the night;
     - MEMORY_BUDGET exits 0 (`rl/frs_run.py:58`).
   - The readiness thresholds are the registered `m8_rd_session.READINESS` (4,096 MB available, 10,240 MB free commit, 5 GiB on C: and D:)
     and are never lowered (`rl/frs_machine.py:27,172-198`).
   - The lock is `O_EXCL`, and a stale lock is taken over only when its pid is dead (`rl/frs_guard.py:375-393`).
   - Code digest: computed by the planner and re-checked by every run before launch (`rl/frs_run.py:340-343`).
   - Run lengths: 75 min wall, 1 and 2 min reserves, 72 min of exploration. The smoke measured the open at 5.5 s and the close at 4.3 s. The
     night's upper bound is 461 min.
   - Memory, from the smoke:
     - main private: 380 MB at load, 632 MB at the start of exploration, 695 MB peak, projected growth 87 MB per explore hour (conservative),
       so about 740 MB after 72 min against a soft budget of 2,560 MB (cap 3,072);
     - process tree: 4,373 / 8,192 MB private and 1,678 / 3,584 MB working set;
     - system minima: 8,338 / 1,536 MB available and 9,169 / 3,072 MB free commit;
     - every run restarts from the import, so nothing accumulates over the six runs.
   - Morning check, failure by failure:
     - a run that refuses inside the Runner leaves `refused.json`;
     - LAB_INVALID and LAB_INCOMPLETE leave `summary.json`, `report.md`, an index row and a `NIGHT STOPPED after run k` line;
     - a crash of the shell itself leaves no final line in the log, a partial run folder without `summary.json` and a stale `lab.lock`;
     - a refusal before the Runner (lock held, run folder exists, no import), or any traceback, is not recorded in any file (S4).
8. **The guide: followable by hand, with S6, N8 and N12.**
   - Every command was checked against the code: the planner's arguments, `night.sh`'s Windows-style paths under Git Bash, `report --run-dir`,
     the hash-copy-verify sequence and the index grep.
   - Missing: the self-check stop line, what a REFUSED run leaves, and how to recognise a stale lock.

## Findings

### BLOCKER

None.

### SHOULD-FIX

| id | file:line | finding | why it matters | suggested fix (not applied) |
|---|---|---|---|---|
| S1 | `rl/frs_guard.py:39-40` | `_winapi.CopyFile2` is not a guarded write event. On Python 3.13.2, `shutil.copy2(src, outside)` raises only that event, and the probe's file was created outside the lab. | The docstring and the plan promise that every write kind outside the lab is refused. A future `copy2` (or `shutil.copy2`-based tooling) would bypass G2 silently. | Add `"_winapi.CopyFile2"` to `WRITE_EVENTS_DST` (destination `args[1]`). Add copy2 to `unit_guard_hook_writes_and_reads`. |
| S2 | `rl/frs_guard.py:188-196, 257-263` | For `CreateJunction` / `symlink` / `link` only the link path is checked, not the target. `inside_lab` accepts a path when either its normalised form or its real path is inside the lab. The probe made a junction from inside the lab to outside and wrote through it. | A link inside the lab turns every later write through it into an outside write. Today the lab's only link targets `import/exe/.tcc` (inside). | Check `args[0]` of the link events too. For writes, require both the normalised and the real path inside the lab. Also check the real path in `read_banned`. Add tests. |
| S3 | `rl/frs_run.py:432-433, 303-305, 730-732` | Main-process guard violations become LAB_INVALID only inside the explore loop. A violation in the open phase gives LAB_INCOMPLETE. One in the drain or the close (close verifications, archive write) is only recorded in `integrity.guard_violations_main`: the status can stay COMPLETED with exit 0. | The write is still blocked, but the guide promises "a guard violation" = LAB_INVALID (`docs/frs_lab_guide.md:187`), and the night would go on. | In `close()` before `write_summary`, and in the open exception handler, mark LAB_INVALID when `g.LabGuard.violations` is not empty. Test a violation in the close. |
| S4 | `rl/frs_lab.py:420` (`step`), `:231-243` | `night.sh` writes start and exit lines to `night_log.txt`, but command output goes only to the window. A refusal before the Runner (lock held, run folder exists, no import), a self-check's printed reason, or a Python traceback is in no file. | In the morning the log may say only `exit 2` or `exit 1`. | Code: `"$@" >> "$NIGHT_DIR/step_$n.out" 2>&1`. Night 1 workaround, with no digest change: start the night with `bash /c/BattleShip_lab/nights/n1/night.sh > /c/BattleShip_lab/nights/n1/night_console.txt 2>&1` and add this line to the guide. |
| S5 | `rl/frs_run.py:709` vs `:719, 733`; `:334-336`; `rl/frs_lab.py:46` | The "no BattleShip left" check runs before the close-phase verifications start their replays, and nothing re-checks afterwards. The next run's open refuses at once if a BattleShip process is still exiting, and `night.sh` has no pause (the plan's 1-minute gap exists only in the start offsets). | A lingering replay process makes the next run REFUSED, which stops the night (availability, not safety). Unlikely: close replays are rare and wait for their own process. | Move the wait after `close_verifications()`. In `open()`, wait up to 60 s (`wait_no_battleship`) before refusing, or add `sleep 60` between steps. |
| S6 | `docs/frs_lab_guide.md:133-136, 154-158, 219-220` | Section 5 does not cover the self-check stop line (`NIGHT STOPPED: self-check did not pass`) or a REFUSED run, which has `refused.json` and `run_log.jsonl` but no `report.md` (`report` prints "no report"). After an interrupted night `lab.lock` stays behind with a dead pid, but section 7 says to copy only when the lock does not exist. | The owner cannot finish the morning check, or the weekly copy, by hand in these cases. | Add these three cases. For the stale lock: if `lab.lock` exists and `tasklist` shows no python with its pid, the lock is stale and the next lab command takes it over. Document the console capture of S4. |

### NOTE

| id | file:line | note |
|---|---|---|
| N1 | `rl/frs_guard.py:178-191` | The null-device exception is as narrow as claimed: exactly `nul` and `\\.\nul` in any case and with either slash (and `\\?\nul` after prefix stripping), `/dev/null` on POSIX. `C:/x/nul_file` and `<dir>/nul` stay refused (tested). It applies to every write event type, not only `open`, which is harmless for a device. |
| N2 | `rl/frs_lab.py:61-67`; `rl/frs_run.py:69-72` | Writes outside Python's reach. (a) BattleShip.exe writes `%APPDATA%/BattleShip/ssb64.log`, which is disclosed; it is the only file there, last modified at the smoke's end. Its other writes go to the run's runtime and episode folders in the lab. (b) `git status` (the self-check's step 1 and the import) probably refreshes `<checkout>/.git/index` (an opportunistic lock): not a tracked file and not evidence; `git --no-optional-locks status` avoids it. (c) The code-manifest child and the self-test parent run without the guard; they only import, and remove the probe. |
| N3 | `rl/frs_guard.py:198-211` | G3 compares path spellings. A junction, an 8.3 short name, or a UNC or subst spelling of `runs/` would pass. `os.stat` and `exists` are not audited, so existence checks are possible. No lab path is built that way: all derive from `REPO`, the lab root and the import. |
| N4 | `rl/frs_worker.py:218-219` | A worker whose spec has no `guard` runs unguarded (fail-open). The real spec always has one (`rl/frs_lab.py:205`). Refuse a real-backend worker without it. |
| N5 | `rl/frs_archive.py:278-282` | `Archive6.adopt` refuses a lab archive, but the rd2-level `Archive2.read_dir` accepts one (by design: `read_lab_dir` uses it). The lab archive keeps archive id `m8_rd_a1`. Its markers are the `frs_lab` session event, the `frs_mode: lab` meta key and its location. A distinct lab archive id would make confusion impossible. |
| N6 | `rl/frs_run.py:111, 420, 743` | With the amended 2-min close reserve, the close-phase verification window is about 40-50 s (`close_write_reserve_s` = 120 s, the whole reserve), and zero after a worst-case 90 s drain. Leftovers are correctly listed as unverified. In-run verification takes about 20 s per candidate, so the queue should be short. Report "unverified at the close" from night 1. |
| N7 | `rl/frs_run.py:710-714` | A verify thread still alive after the close join is dropped: its candidate appears neither in `rows` nor in `unverified`. Append it to `unverified`. |
| N8 | `docs/frs_lab_guide.md:260` | The smoke's row in the lab index starts with `| 20`, so section 8's grep would copy it into the tracked index with the night-1 rows. |
| N9 | `rl/frs_run.py:59, 66-83` | The night digest covers the 34 `rl/` modules. The executable and the import are pinned by hash, the interpreter only by path. |
| N10 | `docs/frs_lab_index.md:59-60` | The pre-registration expects a CONT rate above a third, but the smoke measured 25.6 % (101 of 394 boundaries in 5 min). It is a reference figure only, and no code or decision reads it. |
| N11 | `rl/frs_run.py:523-526, 438-439` | One worker death or one job timeout makes the run LAB_INCOMPLETE and so ends the night (approved rule 5). Accepted availability risk. |
| N12 | `docs/frs_lab_guide.md:32-59` | The preparation omits the handoff's "restart the PC" step and does not mention pausing Windows Update, whose restart would end the night (case "no final line"). |

## What cannot be determined here

- Native writes other than `ssb64.log`, such as Windows Error Reporting dumps after a native crash, without running the game.
- Whether `git status` actually rewrote `.git/index` during the smoke.
- The native behaviour of LAB_INVALID, LAB_INCOMPLETE, MEMORY_BUDGET, quarantine and close-phase verification: these are stub-tested only.
- The memory, throughput and continuation rate of a 72-minute run: they are projected from the smoke's 5 minutes.

## Open questions

1. Fix S1 to S5 before night 1? That changes the smoke-tested digest, so it needs the suite and a new 10-minute smoke. Or after night 1
   (recommended, with the S4 console workaround)?
2. Should the smoke row go into the tracked index (N8)?
3. Should one worker death end the whole night (N11), or only its run?
4. Is disclosure enough for native side-writes beyond `ssb64.log`, or should night 1's morning check list `%LOCALAPPDATA%/CrashDumps`?

## Working files (git-ignored)

`logs/frs_review/lab_review_2026-10-14/`: `tests_output.txt` (suite output), `guard_probe.py` (the zero-tick guard probe), `probe_16704/` (its
fake repo, lab and outside folder; the probe's junction was removed after the run).
