# Fast-route lab guide: running a lab night by hand

This guide is for the owner. It shows how to run a lab night from Git Bash with no Claude session, and how to read the result in the morning.

Lab mode is exploratory. Nothing a lab run finds is a registered claim. A faster clear can be registered later, but only through the registered
path (decision Q10 in `docs/rl_decisions_2026-10-14.md`).

What the lab is made of:

- **Code:** `rl/frs_*.py`, run with `python -B`.
- **Lab root:** `C:/BattleShip_lab`. Every lab write goes there. The runner refuses a lab root inside the checkout, under any `runs` folder, or
  overlapping the three D: evidence folders.
- **Starting archive:** a one-time hashed copy of sd2's closing archive in `C:/BattleShip_lab/import/`, made on 2026-10-14. After that copy, no
  lab run reads `runs/`.
- **Pre-registration and arms:** `docs/frs_lab_index.md`.
- **Design and approval:** `logs/frs_prep/phase1_plan.md` (git-ignored), with its dated amendments.

**Night 1 in order.** Each step is detailed below.

1. Prepare the machine (section 1).
2. Optionally rehearse the self-check (section 2).
3. Plan night `n1` with `--wall-min 75 --open-reserve-min 1 --close-reserve-min 2` (section 3).
4. Run `bash /c/BattleShip_lab/nights/n1/night.sh` and leave the window open (section 4).
5. In the morning, check `night_log.txt` for `NIGHT COMPLETE` (section 5).

All commands below are typed in **Git Bash**. Start every session from the checkout:

```bash
cd /c/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip
```

## 1. Before the night: prepare the machine (about 15 minutes)

1. Commit the lab code first if it has changed since the last commit. Each night pins the code it runs, but a commit makes that code
   recoverable.
2. Shut down WSL, then check that nothing is still running. The second command should print nothing, or "There are no running distributions".

   ```bash
   wsl --shutdown
   ```

   ```bash
   wsl --list --running
   ```

3. Close IntelliJ, the browsers (including Edge's background mode), the video editor, the replay viewer, Steam and any idle Claude sessions.
   Nothing may close them for you, and nothing ever lowers a threshold.
4. Turn off sleep: Windows Settings > System > Power > Screen and sleep > "Never" when plugged in.
5. Check that `python` is the expected interpreter. The planner pins the interpreter path into `night.sh` anyway.

   ```bash
   python --version
   ```

6. Check that no BattleShip process is running. This should print `0`.

   ```bash
   tasklist | grep -ci battleship
   ```

## 2. The self-check (about a minute)

```bash
python -B rl/frs_lab.py selfcheck --lab-root C:/BattleShip_lab
```

The last line says **PASS**, **REFUSED** or **FAIL**. The details are saved in `C:/BattleShip_lab/selfcheck/<time>/selfcheck.json`.

It checks:

- the lab-root guard and the lock;
- that every imported file still matches its hash;
- the write and read guards, from a child process;
- readiness, against the registered thresholds:
  - available memory at least 4,096 MB;
  - free commit at least 10,240 MB;
  - free disk on C: and D: at least 5 GiB;
- that no BattleShip process is running;
- the archive check: E6-on selection must equal sd2's, plus the E6-off census;
- the tick-0 pin: one fresh game process;
- the reference clear replayed exactly from tick 0 with the verify flags, in one fresh game process.

What to do with each answer:

- **PASS:** go on to the next section.
- **REFUSED:** readiness, a running BattleShip, or a held lock. Free memory by closing applications (Steam, ChatGPT, idle Claude sessions)
  and run the self-check again. Never lower a threshold.
- **FAIL:** do not start a night. Keep the folder and ask for a review.

The night script runs the self-check again before its first run, so this manual run is only a rehearsal.

## 3. Plan the night (seconds; no game)

```bash
python -B rl/frs_lab.py plan --lab-root C:/BattleShip_lab --night n1 --runs 6 --wall-min 75 --open-reserve-min 1 --close-reserve-min 2
```

- The order is ABBA: CONTROL, CONT, CONT, CONTROL, CONTROL, CONT.
- Each run gets the same wall time. The two runs of a label pair (n1r1, n1r2, n1r3) share their keyed draws.
- Use a new `--night` label for every night (`n2`, `n3`, ...). A night folder is never overwritten.
- `--hours 8` instead of `--wall-min` computes the per-run wall from the night's length.
- The reserves are set from the smoke run of 2026-10-14 (amendment A2 of the plan): open 1 minute (measured 6 seconds) and close 2
  minutes (measured 5 seconds; the margin covers a slow drain and the close-phase verifications). Each run then explores for
  75 - 1 - 2 = 72 minutes, and ends a few seconds after its exploration, so a six-run night takes about 7 h 15 min.
- Without the two reserve options, the planner uses the original 4 and 6 minutes (65 minutes of exploration). That is safe, only slower.

The planner prints the layout and the start offsets. It writes `C:/BattleShip_lab/nights/n1/plan.json` and
`C:/BattleShip_lab/nights/n1/night.sh`. It also records the code digest, and each run refuses to start if the code has changed since the plan.

## 4. Start the night (by hand, no Claude session)

```bash
bash /c/BattleShip_lab/nights/n1/night.sh
```

- **Leave that Git Bash window open** all night. Closing it stops the night: the runs are children of the window. Locking the screen is fine.
- The script runs the self-check, then the six runs in order.
- It stops at the first non-zero exit. A run that stops at the memory budget (MEMORY_BUDGET) exits 0 and does not stop the night.
- Each run is one fresh process tree. If the parent dies, a job object closes its game processes.

To watch progress from a second Git Bash window (optional; Ctrl+C stops only the watching, never the night):

```bash
tail -f /c/BattleShip_lab/nights/n1/night_log.txt
```

## 5. In the morning: did the night complete?

```bash
tail -n 20 /c/BattleShip_lab/nights/n1/night_log.txt
```

- **The last line is `NIGHT COMPLETE`:** every run finished. Each `exit 0:` line is one finished run.
- **The last line is `NIGHT STOPPED after run k (...)`:** run k exited non-zero and the rest did not start. Read run k's report (below).
- **The log has no final line:** the night was interrupted (the window was closed, the PC slept, or the machine restarted). The last `start:`
  line names the run that was running. That folder has no `summary.json` if the run never reached its close.

Check that nothing is left running. This should print `0`.

```bash
tasklist | grep -ci battleship
```

List the night's runs and show the lab index rows written by the runner:

```bash
ls /c/BattleShip_lab/lab_runs/
```

```bash
cat /c/BattleShip_lab/frs_lab_index.md
```

Read one run's report (replace the folder name with one from the listing):

```bash
python -B rl/frs_lab.py report --run-dir C:/BattleShip_lab/lab_runs/2026-10-15_CONTROL_n1r1
```

## 6. Reading a report

Each run folder holds:

- `summary.json`: one key per line, `"mode": "lab"`;
- `report.md`: the same as a short table;
- `iterations.jsonl`: one row per job, including the continuation decisions;
- `verifications.jsonl`: every replay verdict;
- `quarantine.jsonl`: only when a cell was quarantined;
- `memory.jsonl`;
- `run_log.jsonl`;
- `config.json`: every value and its origin;
- `code/`: the exact code that ran, with its hashes;
- `archive/`: the closing lab archive.

**Status and exit code:**

| status | exit | meaning | stops the night? |
|---|---|---|---|
| COMPLETED | 0 | the explore phase ran to its deadline and the run closed normally | no |
| MEMORY_BUDGET | 0 | memory reached the soft budget; the run stopped cleanly before any registered cap | no |
| REFUSED | 2 | readiness, a running BattleShip, the lock, the import pins or a code change refused the start; nothing was launched | yes |
| LAB_INVALID | 3 | an integrity problem; keep the folder and ask for a review (see below) | yes |
| LAB_INCOMPLETE | 4 | a registered memory cap, a worker death, more than 3 lifecycle failures, a job timeout or a process-count breach | yes |

LAB_INVALID covers:

- a guard violation;
- a replay that differs from its in-run record;
- more than 3 quarantined cells;
- a lab burst whose words do not re-derive from their keys;
- a reference clear that does not replay exactly.

**Measures in the report:**

- **Work:** dispatches, ticks, prefix and burst ticks, new cells.
- **Throughput** per explore hour.
- **Continuation:** boundaries reached, how many continued, and the burst-length counts (120, 240, 360 or 480 words). CONTROL always shows
  0 boundaries.
- **Fastest arrival per level:** the start, the end, and the reference clear's own arrival.
- **Memory:** MB at load, bytes per cell, MB per 1,000 new cells, and the projection at 8, 24 and 48 hours.
- **Quarantines.**

**What a verified clear looks like:**

- A row in `report.md`'s verification table with kind `clear`, verdict **VERIFIED**, and both completion clocks: `completion_input_tick` /
  `completion_time_passed`, two different clocks, never collapsed.
- VERIFIED means both of these held:
  - two separate fresh game processes replayed the clear's words from tick 0 with the verify flags, and both agreed exactly with each other and
    with the in-run record (clocks, action digest, chain digest, break table);
  - every word that came from a lab burst re-derives from its keyed draw.
- Every run also re-verifies the imported reference clear (1,885 / 1,884) first. The report shows `reference clear re-verified in-run | exact`.
- Anything else is a **candidate, never a clear**: verdict ERROR (a replay could not run), a candidate left unverified at the close, or no
  verification at all.
- A verified clear faster than 1,885 is a lab result. It is registered only by a registration session.

## 7. Weekly hashed copy of the lab root to D: (between nights, never during one)

This makes a dated copy in `D:/BattleShip_lab_copies/<date>/`. That folder is outside `D:/BattleShip_runs_backup`,
`D:/BattleShip_source_snapshots` and `D:/BattleShip_exe_archive`. Do this only when no lab run is active, which means
`C:/BattleShip_lab/lab.lock` does not exist.

1. Set the date (change it each week):

   ```bash
   DAY=2026-10-23
   ```

2. Write the hash manifest of everything in the lab root:

   ```bash
   cd /c/BattleShip_lab && find . -type f ! -name 'SHA256SUMS_*' -print0 | sort -z | xargs -0 sha256sum > "SHA256SUMS_$DAY.txt"
   ```

3. Copy the whole lab root:

   ```bash
   mkdir -p "/d/BattleShip_lab_copies/$DAY" && cp -a /c/BattleShip_lab/. "/d/BattleShip_lab_copies/$DAY/"
   ```

4. Re-hash the copy on D: against the manifest. It must print `COPY OK`:

   ```bash
   cd "/d/BattleShip_lab_copies/$DAY" && sha256sum -c --quiet "SHA256SUMS_$DAY.txt" && echo COPY OK
   ```

5. Go back to the checkout:

   ```bash
   cd /c/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip
   ```

## 8. Weekly: copy the lab index rows into the repository and commit

The runner appends one row per run to `C:/BattleShip_lab/frs_lab_index.md`. The tracked `docs/frs_lab_index.md` has the same table header, so
rows copy across unchanged.

1. Append the rows that are not yet in the tracked file. Run ids start with the date, so the rows start with `| 20`:

   ```bash
   grep '^| 20' /c/BattleShip_lab/frs_lab_index.md | grep -v -F -x -f <(grep '^| 20' docs/frs_lab_index.md) >> docs/frs_lab_index.md
   ```

2. Check what changed:

   ```bash
   git diff --stat
   ```

3. Commit by hand with a plain-language message:

   ```bash
   git add docs/frs_lab_index.md
   ```

   ```bash
   git commit -m "Add this week's lab index rows"
   ```

## 9. Never

- Never lower a readiness threshold or a cap, and never close applications from a script.
- Never run a lab night during any other native work: a registered session, a test suite with native ticks, or the replay viewer.
- Never move the lab root into the checkout, under a `runs` folder or into a D: evidence folder. The runner refuses anyway.
- Never delete or edit `C:/BattleShip_lab/import/`. Every run re-hashes it and refuses on any change. The import is one-time: it refuses to run
  again.
- Never treat an unverified candidate as a clear: not in chat, not in the index, not in a video draft.
