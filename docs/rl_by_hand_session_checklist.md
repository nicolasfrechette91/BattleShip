# Running a registered session by hand (without Claude)

Written 2026-10-13 at HEAD `6cb3e89`. This is the launch-day procedure for one registered native session, run by a person who reads every output
before the next step. It is a checklist, **not a script**: never paste a whole section into a terminal.

**The model.** It follows the most complete launch so far, M8-sd2: section 11 of `docs/rl_m8_sd2_prep_2026-10-12.md` (the launch prompt) with
the amendments A1 to A10 that its launch applied (`docs/rl_m8_sd2_results_2026-10-12.md` section 14, from the pre-launch review
`logs/m8_sd2_review/review_2026-10-12.md`). Every "expected output" below is what sd2 actually printed (`logs/m8_sd2_run/`), unless it says otherwise.

**sd2 itself cannot be run again.** Its tools accept only `--session sd2`, the launcher refuses because `runs/m8_rd_sd2` exists, and the approval
writer refuses because `docs/rl_m8_sd2_approval.json` exists. A new session needs a preparation first (its own modules, tool folder, preparation
record and registered values, committed and pushed). The commands below are the pattern that preparation should keep.

**Markers.**

- **[NEW]**: this step needs a new tool, module, name or registered value for any session other than sd2. The preparation of that session must
  supply it, and its preparation record must give the exact command.
- **[g3]**: how a g3-type session (a resumed training session, `--session k`) differs. The g3 procedure in full is `docs/rl_runbook.md` section 3.
  The g3 line itself has ended (END_BUDGET_1694); a future training line will need its own tools, so read every [g3] note as a pattern too.

**Conventions.** Git Bash only, from the repository root, forward slashes, `python -B -X utf8` for every Python command (the tools refuse without
`-B`). PowerShell scripts are called from Git Bash as `powershell.exe -NoProfile -ExecutionPolicy Bypass -File <script> <arguments>` (amendment A5).
**One date for everything dated:** the local date when Part B starts, even if the session crosses midnight.

## 0. The decision, before the day

1. The session has a proposal, a preparation record with its own launch section, and my written decision to launch it (options, recommendation,
   why). Preparation and launch on **different days** when the session is new or risky (sd2 preparation record, decision 13).
2. Everything is committed and pushed: the session's code, its preparation record and any document written since. `git status` is clean.
   New files under `rl/` or `docs/` that are not committed make the three M9 unit suites fail their git-state test (B1 below).
3. The pre-launch review of the new launch path is done and its findings are written into the launch steps as amendments (never by editing a
   pinned record). sd2's review caught a wrong increment name (A1).
4. Read the preparation record's launch section, the proposal and the predecessor's results record.

## 1. Machine preparation

Do this in order on the launch day, before Part B.

1. **Restart the PC.**
2. **Stop WSL** (in Git Bash):

   ```bash
   wsl --shutdown
   wsl --list --running
   ```

   Correct: the second command lists no running distribution. (sd2's samplers saw no `vmmem`, `vmmemWSL` or WSL host process at any time.)
3. **Close** IntelliJ (`idea64`), every browser including Edge's background mode (Edge's five background processes were still running at sd2's
   baseline), any video editor (Avidemux once held 6,170 MB), the replay viewer and browser (`replay/`: the viewer starts `BattleShip.exe`, and any
   BattleShip process makes the preflight refuse), and any `node` process (two once reached 46,346 MB and 33,567 MB private).
4. **Claude:** none while running by hand. If you open one, at most ONE Claude session, and none may edit files or run gates at the same time
   (runbook pitfall P6). Nine idle Claude Code processes held about 1.8 GB at sd2 (sd2 review, section 6).
5. **Sleep off** for the whole day: Settings > System > Power, never sleep when plugged in (the menu path is not checked against this machine).
6. **The launch never closes anything.** If memory is short later, that is a stop; no threshold or cap is ever lowered (A3, A4).
7. **Check** (Git Bash):

   ```bash
   cd /c/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip
   tasklist //FI "IMAGENAME eq BattleShip.exe" //NH
   tasklist //FI "IMAGENAME eq node.exe" //NH
   tasklist //FI "IMAGENAME eq idea64.exe" //NH
   tasklist //FI "IMAGENAME eq msedge.exe" //NH
   tasklist //FI "IMAGENAME eq claude.exe" //NH
   python -B -X utf8 -c "import sys, json; sys.path[:0] = ['rl', 'rl/tools']; import m8_rd_session as s; print(json.dumps(s.readiness(), default=str)); print('battleship pids', s.game_processes())"
   ```

   Correct: each `tasklist` prints `INFO: No tasks are running which match the specified criteria.` (for `claude.exe`, only if no Claude app is
   open); readiness `"ok": true` with available memory well above **4,096 MB** and free commit above **10,240 MB** (thresholds of
   `rl/m8_rd_session.READINESS`; sd2 had about 6,000 MB and 14,000 MB); `battleship pids []`. In Git Bash, `tasklist` needs `//FI` and `//NH`.
   A readiness failure is a **stop**.

## 2. Variables (every new Git Bash terminal)

```bash
cd /c/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip
export PYTHONDONTWRITEBYTECODE=1
DATE=2026-10-12                                   # the local date when Part B starts
REPO=C:/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip
RUNLOG=logs/m8_sd2_run                            # launch-day logs (Git-ignored)
PARTB=$RUNLOG/partB                               # Part B logs; nothing else is written here
SNAP=D:/BattleShip_source_snapshots/${DATE}_m8_sd2
INCR=D:/BattleShip_runs_backup/${DATE}_incr_m8_rd_sd2
```

- **[NEW]** Every `sd2` above (and in every command below) becomes the new session's name, and the paths become the ones its preparation record
  names. Check the **increment name** against the code of the new post-run tool, not only against the preparation record: sd2's record said
  `_incr_m8_sd2` while its tool looks for `_incr_m8_rd_sd2` (A1). sd1's increment is `<date>_incr_m8_sd1`.
- **[g3]** `K=<k>`, `SNAP=D:/BattleShip_source_snapshots/${DATE}_m9_g3_s${K}`, `INCR=D:/BattleShip_runs_backup/${DATE}_incr_m9_g3_s${K}`, Part B logs
  in `logs/m9_g3_s${K}_prep/launch_${DATE}` (inside the snapshot's file set), later logs in `logs/m9_g3_s${K}_run` (runbook section 3.0).

## 3. Part A: the state (stop if anything differs)

```bash
git rev-parse HEAD origin/main
git ls-remote origin refs/heads/main
git status --porcelain --untracked-files=all
git diff --cached --name-only
ls runs/m8_rd_sd2 logs/m8_sd2_run docs/rl_m8_sd2_approval.json
```

Correct: the three hashes are equal (HEAD carries the session's code and preparation record); `git status` and the staged list print nothing;
`ls` reports `No such file or directory` for all three. Anything else is a stop.

## 4. Part B: the conditions (zero native ticks outside the registered test suites)

All must hold before Part C. Any other result than the expected one is a **stop**: write down what you saw, do not continue, do not "try again".
sd2's Part B took 4 h 28 min. Run the steps one after another; never two suites at the same time; start nothing else on the machine.

### B-start. The log folder and the machine sampler

```bash
mkdir -p $PARTB
tasklist //FI "IMAGENAME eq claude.exe" //FO CSV //NH
```

Open a **second Git Bash window** (same `cd` and variables) and start the sampler there; it runs to the end of Part D and never kills anything:

```bash
python -B -X utf8 tools/m8_sd2/machine_sampler.py --out $RUNLOG/machine_samples.jsonl --alerts $RUNLOG/machine_alerts.txt --baseline-claude ""
```

`--baseline-claude` takes the comma-separated `claude.exe` pids present now (an empty string for none; sd2 passed 21). Stop it with Ctrl+C after
the results record (Part D). Correct: one line is appended to `machine_samples.jsonl` every 30 s and `machine_alerts.txt` stays empty.
**[NEW]** The sampler takes no session name; a new tool folder needs its own copy (or the same script under the new folder).

### B0. The tree is clean, current and the expected code

```bash
{ git rev-parse HEAD origin/main; git ls-remote origin refs/heads/main; echo "## status"; git status --porcelain --untracked-files=all; echo "## staged"; git diff --cached --name-only; git diff --check; echo "diff-check rc=$?"; echo "## fingerprint"; python -B -X utf8 rl/m8_sd2_session.py fingerprint; echo "## eol"; git ls-files --eol rl/m8_sd2_*.py tools/m8_sd2/ docs/rl_m8_sd2_prep_2026-10-12.md docs/rl_m8_sd2_proposal_2026-10-12.md; } > $PARTB/b0_git_state.txt 2>&1
cat $PARTB/b0_git_state.txt
```

Correct: three equal hashes; nothing under `## status` and `## staged`; `diff-check rc=0`; fingerprint **`b22c0af8f833b205`** (A6: from the session
command); every `--eol` line starts `i/lf    w/lf`.
**[NEW]** The new session's `fingerprint` command and the value its preparation record pins.
**[g3]** `python -B -X utf8 -c "import sys; from pathlib import Path; sys.path.insert(0, 'logs/m9_g3_resume_tools'); import three_passes as t; print(t.fingerprint(Path('.').resolve()))"`,
expected `15ddbb84932aa658`.

### B1. The three passes, then every existing suite (about 4 h 10 min at sd2)

```bash
python -B -X utf8 tools/m8_sd2/three_passes.py --session sd2 --out $PARTB/three_passes > $PARTB/three_passes_stdout.txt 2>&1; echo "exit=$?" >> $PARTB/three_passes_stdout.txt
tail -n 2 $PARTB/three_passes_stdout.txt
```

Correct (2 h 7 min): the last lines are `THREE_CONSECUTIVE_PASSES` and `exit=0`; in each pass line, `"unit_passed": "101 / 101"`, `"digest":
"2adc51de5cf46121"` and `"unchanged": true` (the fingerprint before and after). **Never pass `--allow-git-gate`** (it is for preparation rounds on an
uncommitted tree only). The tool refuses an existing output folder.
**[NEW]** The new suite's three-passes tool, test count and e2e digest.
**[g3]** `logs/m9_g3_resume_tools/three_passes.py --session $K`: unit 29/29 and e2e `078f46c445d8adc5` three times.

Then every other suite, one after another (a little over 2 hours at sd2):

```bash
mkdir -p $PARTB/suites
while read -r name script cmd; do
  python -B -X utf8 "$script" "$cmd" > "$PARTB/suites/$name.txt" 2>&1 < /dev/null; echo "exit=$?" >> "$PARTB/suites/$name.txt"
  echo "$name: $(grep -v '^\s*$' "$PARTB/suites/$name.txt" | tail -n 2 | head -n 1 | cut -c 1-160)"
done <<'EOF'
g3_rule_self_test rl/m9_g3_rule.py self-test
rd1_rule_self_test rl/m8_rd_rule.py self-test
rd2_rule_self_test rl/m8_rd2_rule.py self-test
rd3_rule_self_test rl/m8_rd3_rule.py self-test
rd4_rule_self_test rl/m8_rd4_rule.py self-test
sd1_rule_self_test rl/m8_sd1_rule.py self-test
sd2_rule_self_test rl/m8_sd2_rule.py self-test
g1_eval_unit rl/m9_eval_tests.py unit
g2_unit rl/m9_g2_tests.py unit
g1_unit rl/m9_tests.py unit
g3_unit rl/m9_g3_tests.py unit
g3_e2e rl/m9_g3_tests.py e2e
rd1_unit rl/m8_rd_tests.py unit
rd2_unit rl/m8_rd2_tests.py unit
rd3_unit rl/m8_rd3_tests.py unit
rd4_unit rl/m8_rd4_tests.py unit
sd1_unit rl/m8_sd1_tests.py unit
sd1_e2e rl/m8_sd1_tests.py e2e
rd4_e2e rl/m8_rd4_tests.py e2e
rd3_e2e rl/m8_rd3_tests.py e2e
rd2_e2e rl/m8_rd2_tests.py e2e
rd1_e2e rl/m8_rd_tests.py e2e
EOF
```

Correct (each file also ends with its `exit=`):

| suite | the line printed | exit |
| --- | --- | --- |
| g3 rule self-test | `m9_g3_rule self-test: PASS (0 problem(s)), s1 dea9965a3989bce5 line d9d82885703c016d` | 0 |
| rd1 to sd2 rule self-tests | `{"rule": "m8_rd1_rule_v1", "digest": "e0bbfe212d3c0079...", "problems": []}`; rd2 `f9779faac95feede...`; rd3 `fae00396494b8e96...`; rd4 `246813eebb7c7559...`; sd1 `8267341f2af80dc1...`; sd2 `d1220a8b2706367f...` | 0 each |
| g1 evaluation | `m9 eval unit suite: 29/29 passed in ...` | 0 |
| g2 | `m9 g2 unit suite: 29/29 passed in ...` | 0 |
| g1 | `m9 unit suite: 62/63 passed (failed: identity_names_every_registered_pin) in ...` (the registered failure; any other failing test is a stop) | **1** |
| g3 unit | `m9 g3 unit suite: 29/29 passed in ...` | 0 |
| g3 e2e | a JSON line starting `{"e2e": "PASS"` and containing `"digest": "078f46c445d8adc5"` | 0 |
| rd1, rd2, rd3, rd4 unit | `48 / 48 passed (unit)`, `27 / 27`, `67 / 67`, `79 / 79` | 0 |
| sd1 unit / e2e | `87 / 87 passed (unit)`; `{"e2e": "PASS", "digest": "4cadf507c1c4fbc9", "outcome": "PROGRESS", "problems": []}` | 0 |
| rd4, rd3, rd2, rd1 e2e | `E2E PASS` (no registered digest) | 0 |

If a g1, g2 or g3 unit suite fails only its git-state test (`tracked_files_are_unchanged...`, "every new file under rl/ or docs/ is an M9 file"),
something is uncommitted: stop, go back to section 0.
**[NEW]** Add the new session's predecessor suites and rule self-test (for an sd3: sd2's unit 101/101, e2e `2adc51de5cf46121`, rule `d1220a8b...`).

### B2. The registered digests (A2: `approval-template`, not `status`)

```bash
python -B -X utf8 rl/m8_sd2_session.py approval-template > $PARTB/b2_approval_template.json 2> $PARTB/b2_approval_template_stderr.txt; echo "exit=$?"
python -B -X utf8 -c "import json, sys; t = json.load(open(sys.argv[1], encoding='utf-8-sig')); c = t['contracts']; o = t['open_overlay']; print('rule', t['rule_sha256']); print('v4', c['m8_rd_select_v4']); print('sd1 event', t['sd1_session_event_digest']); print('v3', c['m8_rd_select_v3']); print('v2', c['m8_rd_select_v2']); print('claims', t['claims_digest']); print('artifacts', t['artifacts_digest']); print('draws', t['draws_sha256']); print('overlays', o['sd1_closing_v4_sha256'], o['v4_sha256']); print('fingerprint', t['source_fingerprint']); print('reference', t['record_reference']['completion_input_tick'], 'bar', t['progress_bar'], 'bound', t['record_bound_max_L'], 'tiers', t['tiers'])" $PARTB/b2_approval_template.json
```

Correct: `exit=0`, and the values of `docs/rl_m8_sd2_prep_2026-10-12.md` section 4: rule `d1220a8b2706367f...`, v4 at 2,086 `8e09d332f16bb6cb...`,
sd1 event `eb08059242eef123...`, v3 `fd69a0332de9db28...`, v2 `a7d1953b7de76040...`, claims `4c87a3e69954b4ea...`, artifacts `3d06da399dd8cb9c...`,
draws `ba0cdfe8c8359d60...`, overlays `f6af59157fb2b420...` and `2481c0d33abc5c02...`, fingerprint `b22c0af8f833b205`, reference 2086, bar 2062,
bound 2061, tiers 1981 / 1877 / 1800. A changed digest is a stop. (`status` prints only four fields and cannot show these.)
**[NEW]** The new session's digests and key names. **[g3]** The B2 one-liner of runbook step S6.

### B7. The budget and the line consequence

sd2 checked these with a hand-written helper, saved as `logs/m8_sd2_run/session_scripts/partb_b2_b7.py.txt`. To use it, copy it **outside the
repository** and run it on the template:

```bash
mkdir -p "$HOME/bt_scratch" && cp logs/m8_sd2_run/session_scripts/partb_b2_b7.py.txt "$HOME/bt_scratch/partb_b2_b7.py"
python -B -X utf8 "$HOME/bt_scratch/partb_b2_b7.py" $PARTB/b2_approval_template.json > $PARTB/b2_b7_line_check.txt; echo "exit=$?"
python -B -X utf8 -c "import json, sys; d = json.load(open(sys.argv[1], encoding='utf-8-sig')); p = d['B7']['projection']; print('B2', d['B2']['ok'], 'B7', d['B7']['ok'], 'line', d['line_consequence']['ok']); print('fits without trimming', p['fits_hard_cap_without_trimming'])" $PARTB/b2_b7_line_check.txt
```

Correct: `B2 True B7 True line True` and `fits without trimming True` (sd2: pessimistic 3,415 s inside the 3,600 s cap). The B7 projection counts
the open, exploration and verification phases only; the close checks run outside the hard cap (about 540 s at sd2, more next time).
**[NEW]** The helper holds sd2's registered values and its rule's cases (2,086 / 2,062): a new session needs its own helper or, better, a tool
written by its preparation. **[g3]** The budget is in the dry-run preflight's JSON (runbook step S7); the line consequence is computed into the
approval.

### B4. The earlier trees, by the INDEPENDENT re-hash only

```bash
while read -r src inc; do
  echo "## $src vs $inc"
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/m8_sd2/independent_increment_check.ps1 -Source "$src" -Dest "D:/BattleShip_runs_backup/$inc" < /dev/null
  echo "exit=$?"
done > $PARTB/b4_independent_rehash.txt <<'EOF'
runs/m8_rd 2026-10-02_incr_m8_rd1
runs/m8_rd_rd2 2026-10-02_incr_m8_rd2
runs/m8_rd_rd3 2026-10-02_incr_m8_rd3
runs/m8_rd_rd4 2026-10-03_incr_m8_rd4
runs/m8_rd_sd1 2026-10-11_incr_m8_sd1
EOF
cat $PARTB/b4_independent_rehash.txt
```

Correct: five lines `checked=N source_files=N backup_files=N missing=0 extra_in_backup=0 bad=0 result=PASS` with N = 166, 62, 77, 93 and 130, each
followed by `exit=0`. **Never run `rl/tools/runs_backup.py verify` on any of these** (it rewrites the increment's `verification.json`).
**[NEW]** For an sd3, add `runs/m8_rd_sd2 2026-10-12_incr_m8_rd_sd2` (125 files). **[g3]** Use `logs/m9_g3_prep/tools/independent_increment_check.ps1`
over the session's protected trees (runbook Appendix B).

### B3, B5, B6. The dry-run preflight (no unit suite; about 15 minutes)

```bash
python -B -X utf8 rl/m8_sd2_session.py preflight --skip-unit > $PARTB/preflight_skip_unit.json 2> $PARTB/preflight_skip_unit_stderr.txt; echo "exit=$?"
python -B -X utf8 -c "import json, sys; d = json.load(open(sys.argv[1], encoding='utf-8-sig')); b = d['backup']; print('ok', d['ok']); print('problems', d['problems']); print('coverage ok', b.get('ok'), 'files', b.get('source_files'), 'uncovered', b.get('uncovered')); print('readiness', d['readiness'].get('ok'))" $PARTB/preflight_skip_unit.json
```

Correct: `exit=1`, `ok False`, and `problems` is **exactly** `['no approval record at docs\\rl_m8_sd2_approval.json (the session is not authorised)']`;
coverage `ok True` with `uncovered 0`; readiness `True` without closing anything. Any second problem is a stop.
**[g3]** `rl/m9_g3_session.py preflight --session $K --skip-unit` (runbook step S7).

### B8. The machine, just before Part C

Repeat the checks of section 1, step 7, and `git status --porcelain --untracked-files=all` (empty). Save them as `$PARTB/b8_machine.txt`.

### B9. One Python interpreter (A9)

```bash
{ python -B -c "import sys; print(sys.executable, sys.version.split()[0])"; powershell.exe -NoProfile -Command "(Get-Command python).Source"; } > $PARTB/b9_interpreter.txt 2>&1
cat $PARTB/b9_interpreter.txt
```

Correct: the same path twice, `C:\Users\kill_\AppData\Local\Programs\Python\Python313\python.exe` (3.13.2 at sd2). The launcher starts `python`
from PowerShell, so a different interpreter there would run a different environment: stop.

### B-end. The authorisation file (the last Part B file)

Write the Part C text you authorise, verbatim, with a first line naming the session date, as `$PARTB/authorisation_sd2_${DATE}.txt` (sd2's is
`logs/m8_sd2_run/partB/authorisation_sd2_2026-10-12.txt`; copy its structure). From now on write nothing under `$PARTB`.

## 5. Part C: snapshot, approval, preflight once, launch, wait

### C1. The source snapshot, verified twice (about 1 minute)

```bash
python -B -X utf8 rl/m8_sd2_snapshot.py snapshot --dest $SNAP > $RUNLOG/c1_snapshot.txt 2>&1; echo "exit=$?" >> $RUNLOG/c1_snapshot.txt
python -B -X utf8 rl/m8_sd2_snapshot.py verify --dest $SNAP > $RUNLOG/c1_snapshot_verify.txt 2>&1; echo "exit=$?" >> $RUNLOG/c1_snapshot_verify.txt
python -B -X utf8 rl/m8_sd2_snapshot.py powershell --dest $SNAP --out $RUNLOG/independent_snapshot_rehash.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $RUNLOG/independent_snapshot_rehash.ps1 > $RUNLOG/independent_snapshot_rehash_output.txt
cat $RUNLOG/c1_snapshot.txt $RUNLOG/c1_snapshot_verify.txt $RUNLOG/independent_snapshot_rehash_output.txt
```

Correct (sd2): `{"result": "PASS", "n_files": 231, ... "problems": [], "identity_code_mismatch": [], "identity_docs_mismatch": [], ... "source_fingerprint": "b22c0af8f833b205" ...}`
then `snapshot.json sha256 <H>`; the verify record ends `"executable_equal": true, "result": "PASS"}`; the PowerShell line reads
`checked=232 bad=0 exe=30a3913b... exe_ok=True result=PASS snapshot_json=<the same H>`. The snapshot refuses an existing destination.
**[NEW]** The new snapshot tool. **[g3]** `rl/m9_g3_snapshot.py snapshot --dest $SNAP --session $K` (runbook step S11).

### C2. The approval (about 13 minutes; it runs the open check)

```bash
python -B -X utf8 tools/m8_sd2/write_approval.py --session sd2 --snapshot $SNAP --independent "tool verify (rl/m8_sd2_snapshot.py verify) PASS at <verified_utc from c1_snapshot_verify.txt>: <n> files, 0 mismatches, 0 extra files, 0 external mismatches, executable equal; independent PowerShell Get-FileHash re-hash invoked from Git Bash (rl/m8_sd2_snapshot.py powershell -> $RUNLOG/independent_snapshot_rehash.ps1, no repository module): <paste the output line>" --authorisation-file $PARTB/authorisation_sd2_${DATE}.txt --authorised-on $DATE > $RUNLOG/c2_write_approval.txt 2>&1; echo "exit=$?" >> $RUNLOG/c2_write_approval.txt
cat $RUNLOG/c2_write_approval.txt
```

Correct: a JSON block with `"written": "...\\docs\\rl_m8_sd2_approval.json"`, its `sha256`, `"git_head"` = HEAD, `"source_fingerprint":
"b22c0af8f833b205"`, the references, then the printed **S2 RULE**, and `exit=0`. It refuses an existing approval, a snapshot that is not PASS or
not this session's, another HEAD or fingerprint, an empty authorisation and a bad date.

**From here until the launch (the S2 rule): no commit, no edit of any pinned document, no `runs_backup.py verify` or `backup` of any existing
increment, no new folder on D:.** Any of them makes the preflight refuse; the launcher refuses when HEAD differs from the approval's `git_head`.
**[NEW]** The new approval writer. **[g3]** `logs/m9_g3_resume_tools/write_approval.py --session $K` (runbook step S12).

### C3. The full preflight, ONCE (about 35 minutes)

```bash
python -B -X utf8 rl/m8_sd2_session.py preflight > $RUNLOG/preflight_full.json 2> $RUNLOG/preflight_full_stderr.txt; echo "exit=$?"
python -B -X utf8 -c "import json, sys; d = json.load(open(sys.argv[1], encoding='utf-8-sig')); print('ok', d['ok'], 'problems', d['problems']); print('approval', d['approval']); print('snapshot', d['source_snapshot']); print('readiness', d['readiness'].get('ok'))" $RUNLOG/preflight_full.json
```

Correct: `exit=0`, `ok True problems []`, `approval approved`, `snapshot snapshot recorded, PASS and equal to the repository`, readiness `True`.
**If it fails for any reason, stop. Do not re-run it.** Whether to try another day is a decision for the decision log, with a new approval.

### C4. The launch, and the two-minute check

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/m8_sd2/launch_detached.ps1 -Session sd2 -Repo "$REPO" > $RUNLOG/c4_launch_output.txt 2>&1; cat $RUNLOG/c4_launch_output.txt
python -B -X utf8 tools/m8_sd2/check_launch.py --session sd2 > $RUNLOG/c4_check_launch_output.txt 2>&1; echo "exit=$?"; cat $RUNLOG/c4_check_launch_output.txt
```

Correct: `launched pid=<n> at <utc> session=sd2 head=<HEAD>`; then, **within two minutes** of the launch, six `ok` lines (`record`, `alive`, `age`,
`refused`, `traceback`, `game`) and `verdict    PASS (exit 0)`.

| `check_launch.py` exit | meaning | what to do |
| --- | --- | --- |
| 0 | every condition holds | continue |
| 3 | only the two-minute limit was missed; the process is alive with no refusal | write down the delay and continue |
| 1 | a dead pid, a `refused` or `Traceback` line, or another failure | **stop** and write down what it printed; never relaunch |
| 2 | no sd2 launch record | **stop**; never relaunch |

The check at 0 s confirms that the process started, not that its own preflight passed: the run spends about 48 minutes in its own preflight (the
101-test suite) before the session clock starts, and a refusal there shows only in the waiter and in `state.json` never appearing (sd2 review,
section 6).
**[NEW]** A new launcher and launch check. **[g3]** `logs/m9_g3_resume_tools/launch_detached.ps1 -Session $K`; there is no launch-check tool for
g3: read `$RUNLOG/launch_record.txt` and the session's stdout and stderr yourself.

### C5. Wait (about 1 h 50 min at sd2)

```bash
python -B -X utf8 tools/m8_sd2/wait_session.py --session sd2 > $RUNLOG/c5_wait_output.txt 2>&1; echo "exit=$?" >> $RUNLOG/c5_wait_output.txt
cat $RUNLOG/c5_wait_output.txt
```

Correct: `exit=0` and a last line such as `{"t_min": 108.8, "alive": false, "session": "sd2", "phase": "done", ... "done": true, "decision": "PROGRESS", "invalid": [], "incomplete": []}`.
Any non-zero exit (no launch record, the process gone before any state or without `done`, or the waiter's own 3.5-hour limit) is a **stop**: write
it down; never relaunch (A7). The waiter's limit ends the waiter only, never the session.

While it runs: keep the launching terminal open, do not log off, open no application. To look without touching anything, from another terminal:
`python -B -X utf8 rl/m8_sd2_session.py status` or `tail -n 3 $RUNLOG/wait_log.txt`.
**[g3]** `logs/m9_g3_resume_tools/wait_session.py --session $K` (limit 4.5 hours); a g3 session runs 2 to 3 hours.

## 6. Part D: verify, copy, back up, check, record

### D1. What happened

```bash
python -B -X utf8 -c "import json; r = json.load(open('runs/m8_rd_sd2/sessions/sd2/rule.json', encoding='utf-8-sig')); ln = r['line']; print('outcome', r['outcome'], '| line status', ln['status'], '| counts', ln['session_counts']); print('best', r['best_verified']); print('invalid', r['invalid'], 'incomplete', r['incomplete'])"
```

sd2 printed `outcome PROGRESS | line status SD3_AFTER_REVIEW_NEW_REFERENCE | counts True`. If the outcome is INCOMPLETE with status
`NOT_STARTED`, go to section 9 now; do **not** do D2 to D6. Every other outcome (INVALID included) continues with D2.

### D2. verify-run and the report (about 9 minutes each)

```bash
python -B -X utf8 rl/m8_sd2_session.py verify-run > $RUNLOG/verify_run.json 2> $RUNLOG/verify_run_stderr.txt; echo "exit=$?"
python -B -X utf8 rl/m8_sd2_session.py report > $RUNLOG/report.json 2> $RUNLOG/report_stderr.txt; echo "exit=$?"
python -B -X utf8 -c "import json, sys; d = json.load(open(sys.argv[1], encoding='utf-8-sig')); print('ok', d['ok'], 'problems', d['problems'])" $RUNLOG/verify_run.json
```

Correct: `exit=0` twice, `ok True problems []`, both stderr files empty. A failing verify-run is a stop: report it, change nothing.
**[g3]** `verify-run --session $K` also checks the chain of predecessors (runbook step S16).

### D3. Copy the launch evidence into the tree (about 9 minutes)

```bash
python -B -X utf8 tools/m8_sd2/copy_launch_evidence.py --session sd2 > $RUNLOG/d_copy_launch_evidence_output.txt 2>&1; echo "exit=$?"
tail -n 8 $RUNLOG/d_copy_launch_evidence_output.txt
```

Correct: `exit=0`; the JSON lists `"derived": ["verify_run.json", "report.json"]`, the `launch` files, `"renamed_unstamped": ["machine_samples.jsonl"]`,
and `"verify_run_after_copies": {"exit": 0, "ok": true, ...}`. After this, **nothing is ever written into `runs/m8_rd_sd2` again**.
**[NEW]** A new copy tool. **[g3]** No tool: the hand commands of runbook step S17.

### D4. The D: increment (seconds)

```bash
python -B -X utf8 rl/tools/runs_backup.py backup --source runs/m8_rd_sd2 --dest $INCR > $RUNLOG/d_backup_output.txt 2>&1; echo "exit=$?" >> $RUNLOG/d_backup_output.txt
tail -n 2 $RUNLOG/d_backup_output.txt
```

Correct (sd2): `verification PASS: files 125 bytes 252637797 hash mismatches 0 problems 0` and `exit=0`. **`--source` is mandatory**: without it the
tool backs up, or verifies against, all of `runs/` (runbook pitfall P4). The increment name is exactly `$INCR` (`2026-10-12_incr_m8_rd_sd2` for
sd2); one folder per session; a failed backup is re-run into the same folder.
**[NEW]** The new name, matched to the new post-run tool. **[g3]** `$INCR` = `<date>_incr_m9_g3_s<k>`, then `runs_backup.py verify --source runs/m9_g3/s$K --dest $INCR`
and the independent re-hash of that one tree (runbook step S18).

### D5. The post-run checks (about 3 hours, because of the known defect)

```bash
python -B -X utf8 tools/m8_sd2/post_run_checks.py --session sd2 --tool-verify > $RUNLOG/d_post_run_checks_output.txt 2>&1; echo "exit=$?" >> $RUNLOG/d_post_run_checks_output.txt
grep -E "^(PASS|FAIL) " $RUNLOG/d_post_run_checks_output.txt
python -B -X utf8 -c "import json; d = json.load(open('$RUNLOG/post_run_checks.json', encoding='utf-8-sig')); c = d['coverage']; print('ok', d['ok']); print('r1', d['r1_five_trees'].get('ok')); print('tool verify', d['tool_verify_new_increment']['pass'], d['tool_verify_new_increment']['last_line']); print('coverage', c['ok'], c['source_files'], 'uncovered', c['uncovered'], 'increments', c['increments']); print('FAIL rows', [(r['folder'], r['fields']) for r in d['independent_rehash'] if not r['pass']])"
```

What it does: the tool's own verify on the new increment only (with `--source runs/m8_rd_sd2`), the independent PowerShell re-hash of every
registered increment, R1 over the earlier M8 trees, and the `runs/` coverage.

**The known defect (sd2 review, section 1).** The base backup `D:/BattleShip_runs_backup/2026-09-28` names all of `runs/` as its source, so the tool
re-hashes today's whole `runs/` against it and reports every file added since 2026-09-28 as missing. Correct output **with this defect**: exit 1,
`ok False`, exactly **one** FAIL row, `2026-09-28`, with `extra_in_backup=0 bad=0` (at sd2: `checked=446809 ... missing=69450 extra_in_backup=0 bad=0 result=FAIL`,
2 h 37 min); every other row PASS (21 rows at sd2); `r1 True`; `tool verify True` with `verification PASS`; coverage `True ... uncovered 0` with one
more increment than before (20 after sd2). `bad=0` and `extra_in_backup=0` on the base row mean the evidence is intact. **Any other FAIL row, `bad`
above 0, `extra_in_backup` above 0, `uncovered` above 0 or `r1 False` is a real problem: stop.** Do not edit the sd2 tool; the fix belongs in the
next session's tool (classify the base and skip it, with an optional base-aware re-hash).
**[NEW]** A new post-run tool, ideally with that fix (sd2 review, section 1.4: six tests T1 to T6). **[g3]** No tool: the loops of runbook step S19.

### D6. The results record

Write it by hand as the new file `docs/rl_m8_sd2_results_<DATE>.md` (the session date), with LF line endings:

- its **first line** is exactly `# M8-sd2 results (<DATE>)`; a `## ` section follows; the file ends with a newline; UTF-8 without NUL;
- **no other file** in `docs/` may have a name starting with `rl_m8_sd2_results` (no draft, no `.bak`, no copy): keep drafts outside `docs/`;
- copy the 16-section structure of `docs/rl_m8_sd2_results_2026-10-12.md`: 1 outcome; 2 what was run; 3 Part B; 4 Part C; 5 the open phase;
  6 exploration; 7 the verification pool and the best clear; 8 inherited descriptive replays; 9 the close; 10 resources against the caps; 11 integrity,
  evidence and backups; 12 the integrity literals; 13 the line; 14 the machine, the amendments and departures; 15 what it does and does not say;
  16 files and git status;
- state that the integrity literals were read back and never used for selection (N1), the maximum number of BattleShip processes and any transient
  11th (N2), the increment name used (A1), and resources against the caps (A10);
- report the session clock as the three capped phases (open, exploration, verification) and the close separately (sd2 review, section 2);
- explain the base-backup FAIL row of D5 as a known defect, not as missing evidence.

Check it:

```bash
python -B -X utf8 rl/m8_sd2_session.py check-results-record --path docs/rl_m8_sd2_results_${DATE}.md
```

Correct: a JSON block ending `"ok": true, "problems": []`. Then stop the sampler (Ctrl+C in its window) and check:

```bash
git status --porcelain --untracked-files=all
```

Correct: exactly two lines, `?? docs/rl_m8_sd2_approval.json` and `?? docs/rl_m8_sd2_results_<DATE>.md`. `runs/` and `logs/` are Git-ignored.
**[NEW]** The new record name, title and checker. **[g3]** `docs/rl_m9_g3_s<k>_results_<YYYY-MM-DD>.md`, first line `# M9-g3-s<k> results (<date>)`,
checked by the next session's preflight (runbook step S20 and pitfall P9).

## 7. Commit afterwards

```bash
git add docs/rl_m8_sd2_approval.json docs/rl_m8_sd2_results_2026-10-12.md
git diff --cached --check
git diff --cached --stat
git commit -m "Add the results of the second speed-discovery search"
git push origin main
git rev-parse HEAD origin/main
git ls-remote origin refs/heads/main
git status --porcelain --untracked-files=all
```

Correct: the staged list holds only those two files; `git diff --cached --check` prints nothing; after the push the three hashes are equal and
`git status` is empty. That is exactly sd2's commit `2efaaea`. Use a plain-language message that says what happened, for example "Add the results
of the third speed-discovery search: no shorter clear". Never commit `runs/`, `logs/`, ROMs, `.o2r` files, builds or checkpoints. Then write the
decision-log entry (runbook section 8.2) and, if the line rule asks for one, plan the written review before any next session.

## 8. If the outcome is INVALID

`INVALID` (a tick-0, prefix or chain mismatch, an inexact replay, a pin drift, a changed earlier tree, a write under another tree...) gives the line
status `REPAIR_NEEDED`: a repair and a new approval; whether the session counts is **my decision**, never guessed (`rl/m8_sd2_rule.py`).

1. Do Part D (D2 to D6): the evidence is kept, verified, backed up and recorded like any other outcome. The results record says INVALID, names the
   reasons from `rule.json` (`invalid`), and changes nothing. If `verify-run` itself is not ok, `copy_launch_evidence.py` refuses: stop there, write
   down the problems, and decide the next step in the decision log. No record describes a procedure for that case, and nothing may be written into
   the run tree after its backup, so do not back up a tree whose evidence copy has not been made.
2. Commit the approval and the results record (section 7).
3. The repair is a new preparation (code or test fix), its own review and a new approval, never an extension or an automatic retry. No next
   session before the repair is reviewed.

**[g3]** INVALID gives the line outcome SUSPENDED; two INCOMPLETE sessions in a row also suspend the line (runbook section 5.1).

## 9. If the outcome is INCOMPLETE before exploration started (NOT_STARTED)

It does not count, and the session is repeated under the same name only by this procedure (`docs/rl_m8_sd2_prep_2026-10-12.md` section 5,
`NOT_STARTED_PROCEDURE` in `rl/m8_sd2_rule.py`). Evidence is renamed and backed up, **never deleted**. No file named `rl_m8_sd2_results*` is created.

```bash
UTC=$(date -u +%Y%m%dT%H%M%SZ)
mv logs/m8_sd2_run logs/m8_sd2_run_not_started_$UTC
```

If `runs/m8_rd_sd2` was created:

```bash
mv runs/m8_rd_sd2 runs/_m8_rd_sd2_not_started_$UTC
python -B -X utf8 rl/tools/runs_backup.py backup --source runs/_m8_rd_sd2_not_started_$UTC --dest D:/BattleShip_runs_backup/${DATE}_incr_m8_rd_sd2_not_started_$UTC
python -B -X utf8 rl/tools/runs_backup.py verify --source runs/_m8_rd_sd2_not_started_$UTC --dest D:/BattleShip_runs_backup/${DATE}_incr_m8_rd_sd2_not_started_$UTC
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/m8_sd2/independent_increment_check.ps1 -Source runs/_m8_rd_sd2_not_started_$UTC -Dest D:/BattleShip_runs_backup/${DATE}_incr_m8_rd_sd2_not_started_$UTC
```

Correct: both tool runs end `verification PASS ... hash mismatches 0 problems 0`; the re-hash ends `missing=0 extra_in_backup=0 bad=0 result=PASS`.
Then void the approval by moving it (never deleting it):

```bash
mv docs/rl_m8_sd2_approval.json logs/m8_sd2_run_not_started_$UTC/rl_m8_sd2_approval_void.json
git status --porcelain --untracked-files=all
```

Correct: `git status` is empty again. Find and fix the cause first (a preparation if code must change). Then, on the new session date, a new
Part B, a new snapshot and a new approval dated that day, and the session again under the same name. The launcher's and the approval writer's
refusals enforce this order; no tool performs the procedure. If the session stopped **after** exploration started, it is `COUNTED_INCOMPLETE`: it
counts, Part D applies in full, and the next session needs a written review stating the cause first.
**[NEW]** The same procedure with the new session's names. **[g3]** An INCOMPLETE session below half of its training wall does not count; the
launcher refuses while the session's logs exist (runbook pitfall P11), so any repeat is a written, logged decision.

## 10. Never

- **Never retry, extend or repair a frozen gate or a registered session.** No second launch, no re-run of the full preflight, no "one more try".
- **Never delete or overwrite evidence**: no file under `runs/`, no D: increment or snapshot, no log of a launch day. Rename and back up instead
  (section 9).
- **Never run the tool's verify (`rl/tools/runs_backup.py verify`) on an earlier increment.** It rewrites that increment's `verification.json`. Earlier
  increments are checked by the independent re-hash only. On the new increment, always with the correct `--source`.
- Never commit, edit a pinned document, back up or verify an increment, or create a folder on D: between the approval and the launch.
- Never edit a tracked file on a launch day; records go into new files. Never stage anything during Part B to Part D.
- Never lower a memory or readiness threshold or a cap; a refusal is a stop. The session never closes applications.
- Never pass `--help` to a tool before checking that it has an argument parser (an old tool once started its real job).
- Never pass `--allow-git-gate` on a launch day.
- Never read or use the TAS, a human recording or a crossing fixture in a session; never inspect, log, control, compare or hash a native RNG seed.
- Never start a second session that edits files or runs gates while one is running, and never start a cloud session from this PC.
