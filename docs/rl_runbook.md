# BattleShip RL: the owner's runbook (M8 route discovery, M9 robustification, the g3 session line)

Written 2026-10-08 for the human owner of this fork. It lets you prepare, launch, wait for, verify, back up and judge an M9-g3 session yourself,
using only the tools already in the repository. It is a guide for a person who reads every output before taking the next step. It is **not** a
script: never paste a whole section into a terminal.

**State when written:** `HEAD` = `origin/main` = the remote's `main` = `162e48bce077373d620e27b311c838f0fe338a57` ("Make training resume generic for
any later session (M9-g3)"); `git status` was clean before this file was added.

> **STOP: read this before session 3.** As committed at `162e48b`, session 3 **cannot pass its full preflight** (step S13), and the step S9 commit
> rule applies to this very file. See [section 1.4](#14-blockers-found-while-writing-this-runbook). Do Part B if you like (it is zero-tick and it
> will pass), but do **not** take the snapshot or write the approval (steps S11 and S12) until blocker 1 is fixed in a separate preparation session.

## How each statement was checked

| tag | meaning |
| --- | --- |
| [code] | read in the source on 2026-10-08 (file and function named) |
| [help] | matches the tool's `--help` output on 2026-10-08 |
| [ran] | executed **read-only** on 2026-10-08 (no game process, nothing written to `runs/`, D: or a tracked file); the result is quoted |
| [record] | taken from a results, launch or preparation record in `docs/` or `logs/` |
| **UNVERIFIED** | not checked against code, help or a run. Treat it as a suggestion |

The full ledger of commands and how each was checked is in [Appendix A](#appendix-a-command-ledger). Every UNVERIFIED item is listed again in
[Appendix C](#appendix-c-every-unverified-item).

## Contents

1. [Where things stand](#1-where-things-stand-2026-10-08)
2. [The absolute rules, and why](#2-the-absolute-rules-and-why-each-exists)
3. [The lifecycle of g3 session k](#3-the-lifecycle-of-g3-session-k)
4. [Machine readiness](#4-machine-readiness)
5. [Reading a results record and judging it (worked example: g3-s2)](#5-reading-a-results-record-and-judging-it-worked-example-g3-s2)
6. [Known pitfalls](#6-known-pitfalls)
7. [Model and cost guidance](#7-model-and-cost-guidance)
8. [After every session: review checklist and decision log](#8-after-every-session-review-checklist-and-decision-log)

---

## 1. Where things stand (2026-10-08)

### 1.1 Milestones

| line | sessions | registered outcome | what it means |
| --- | --- | --- | --- |
| **M8 route discovery** (archive exploration; `docs/rl_m8_rd*`) | rd1, rd2, rd3, rd4 | rd1 PASS (on the +2 targets clause only, 7 against 5, no milestone); rd2 PROGRESS_WALL_TOP; rd3 NO_NEW_MILESTONE (stops S2 and S4); **rd4 PROGRESS: CLEAR** | rd4 found the **first full clear by agent-generated inputs**, verified by exact replay from tick 0: two routes sharing a 2,298-tick trunk, 2,315 words (`completion_time_passed` 2,314, about **38.6 s**) and 2,326 words (2,325, about 38.8 s). For scale, the human TAS is 7.43 s. rd5 is permitted by the rd line and was never started. [record: `docs/rl_m8_rd4_results_2026-10-03.md`] |
| **M8-sd1 speed search** (shorter clears) | none | design only | `docs/rl_m8_sd1_proposal_2026-10-07.md` (committed in `e73e589`): selection `m8_rd_select_v4` (length scale 120, record bound), rule `m8_sd1_rule_v1` against the archive's own record 2,315, a proposed margin of 24 ticks, **12 open questions in its section 13** waiting for your answers. Nothing prepared, nothing run. [record] |
| **M9 robustification** (phase 2 of route discovery: turn the clear into a policy; `docs/rl_m9_*`) | g1, g2-s1, g3-s1, g3-s2 | g1 **NULL**; g2-s1 **NULL** (line END_NULL_S1); g3-s1 **NULL**, line CONTINUE; g3-s2 **INCONCLUSIVE**, line CONTINUE | see 1.2 [record] |

### 1.2 M9 in one table

| gate / session | outcome | sticky clears at landing 2,128 (of 20) | D | R | frontier pointer | line |
| --- | --- | ---: | ---: | ---: | --- | --- |
| g1 (one run) | NULL | 0 (0 at all six landings; open-loop tape 13) | none | none | (g1 design) | gate only |
| g2-s1 | NULL | 0 | none | none | 2,300 -> 2,280, then held for the session | END_NULL_S1 (line ended) |
| g3-s1 | NULL | 8 | none | none | 2,300 -> 2,220 (4 moves, 13 attempts) | CONTINUE, k = 1 |
| **g3-s2** (resumed bit for bit from s1) | **INCONCLUSIVE** | **13** (1,966: 3) | **2,128** | none (bar 15) | **2,220 -> 2,040** (9 moves, 22 attempts) | **CONTINUE, k = 2** |

[record: the four results records; `runs/m9_g3/s2/session/rule.json` and `line.json` re-read today, ran]

No session cleared from tick 0 (g3-s2: 0 of 20 sticky, deterministic no clear). Nothing claims a tick-0 policy yet.

### 1.3 The g3 line budget (`m9_g3_line_rule_v1`, digest `d9d82885703c016d...`) [code: `rl/m9_g3_contract.py` lines 109-112, `rl/m9_g3_rule.apply_line`]

| counted session k | the line ENDS unless | status |
| ---: | --- | --- |
| 2 | D_2 <= 2,128 | **met** (D_2 = 2,128) |
| 3 | (no milestone) | next session; it can only end the line by END_SUCCESS (D <= 1,473) or SUSPENDED (INVALID) |
| 4 | D_4 <= 1,966 (END_BUDGET_1966), and D_4 earlier than D_2 (END_NO_PROGRESS) | the next real hurdle |
| 5 | D_5 exists and, if D_3 exists, is earlier than D_3 (END_NO_PROGRESS) | |
| 6 | D_6 <= 1,694 (END_BUDGET_1694), and earlier than D_4 | |
| 7 | D_7 exists and is earlier than D_5 | |
| 8 | the line ends here in any case (END_CAP, unless an earlier condition fires first) | |
| any | **END_SUCCESS at D <= 1,473** ("crossing learned"); SUSPENDED on an INVALID session or two INCOMPLETE sessions in a row | |

"Earlier" means a smaller tick number (further back from the end of the route). D only takes landing values: 2,128, 1,966, 1,694, 1,473, 1,369,
1,248. The frontier pointer (2,040 now) is a training quantity, **not** D (section 5.1).

### 1.4 Blockers found while writing this runbook

1. **Session 3 cannot pass its full preflight as committed (blocker).** `rl/m9_g3_tests.py` line 1196, inside the unit test
   `resume_inputs_and_previous_sessions_are_read_from_the_predecessors_records`, asserts `len(S3.predecessor_doc_problems(4)) == 2` ("session 4 lacks
   s3's two records"). Today the count is 2 [ran]. The moment `docs/rl_m9_g3_s3_approval.json` exists, the count becomes 1: I simulated that in
   memory, without writing a file, by pointing `approval_path(3)` at an existing approval, and got `len = 1` [ran]. The full preflight (step S13)
   and the preflight inside `run` (step S14) both run the whole g3 unit suite (`_run_unit_suites` in `rl/m9_g3_session.py` [code]). That suite would
   then report 28/29 and the preflight would refuse with `unit_suite_m9_g3 failed`. **The fix needs an edit to a tracked test file.** That means a
   separate preparation session, a commit, a new g3 source fingerprint (no longer `64259b59b3e09d50`) and a new Part B. None of that is in this
   runbook's scope.
2. **The same test file also pins "s3 not recorded yet" in four more places** (lines 1191, 1192, 1193 and 1376: `predecessor_problems(4)` names a
   missing final state; `unregistered_predecessors(4) == [3]`; `predecessor_tree(3) is None`; `trees_for(4) == trees_for(3)`). These hold while s3
   is being launched. They become false once s3's tree and increment exist, so **session 4's Part B will fail too** unless those tests are made
   generic. The resume-k record's claim "B13: generic k >= 4, no preparation round" therefore does not hold for the unit suite as committed. [code]
3. **This runbook trips the git gates until you commit it.** The g1, g2 and g3 git-state tests require every new file under `rl/` or `docs/` to have
   `m9` or `M9` in its name (`rl/m9_g3_tests.py` line 1361; the same line in `rl/m9_tests.py` and `rl/m9_g2_tests.py` [code]). `docs/rl_runbook.md`
   does not. While it is untracked, the three passes and the full preflight fail. Commit it (and stage nothing afterwards) before any Part B, or
   rename it with `m9` in the name. See pitfall P1.

### 1.5 Session 3 readiness today (everything else)

| item | today |
| --- | --- |
| resume-k tooling committed | yes, `162e48b`; g3 source fingerprint **`64259b59b3e09d50`** [ran] |
| registered digests | all unchanged [ran]: g3 contract `4cd1deae...`, line contract `90eac1a6...`, frontier `60e174a6...`, s1 rule `dea9965a...`, line rule `d9d82885...`, g2 `8dfd44c6...` / `1aadc7a6...`, g1 `6958857e...` |
| rule self-test | PASS [ran] |
| session 3 | permitted by the line rule; **not authorised**; `runs/m9_g3/s3` absent; no approval (`status --session 3` [ran]) |
| predecessor s2 | registered (4,478 files, 477,564,684 bytes, increment `2026-10-08_incr_m9_g3_s2`, manifest `a6965387...`); `unregistered_predecessors(3) == []` [ran] |
| D: coverage | 432,800 source files, **0 uncovered**, 14 increments [ran, 1 min 44 s] |
| machine | readiness `ok`, but only **4,112 MB available** against the 4,096 MB threshold, with IntelliJ (`idea64`, about 1.5 GB private) and five `claude` processes (415-808 MB private each) open; no BattleShip process [ran] |

---

## 2. The absolute rules, and why each exists

Sources: `CLAUDE.md`, the external guide `..\guide.md` sections 2 and 10-11, the M8 and M9 decision records.

| # | rule, in plain words | why it exists |
| ---: | --- | --- |
| 1 | `decomp/` is byte-accurate source. PC-only behaviour goes behind `#ifdef PORT`; the original code path is never changed. | The port is trustworthy only because it compiles from a matching decompilation. A "harmless" edit can change game behaviour. |
| 2 | Submodules (`decomp`, `libultraship`, `torch`) stay pinned. Never push to JRickey repositories. Never restore Android/UWP/Xbox. | A stable sandbox you own. Upstream is a reference only. |
| 3 | One submitted action = exactly one native game tick. `completion_time_passed` and `completion_input_tick` are two different clocks and are never merged. | Every replay check and every time claim depends on exact tick accounting. |
| 4 | Restarting the process is the only reset. No in-process reset, no save states. | Every episode starts from the identical state; save states would add untested paths into the game's state. |
| 5 | The submitted native controller words are the replay truth. Every clear that counts must be replayed exactly from tick 0 in a fresh process. | A claim that does not reproduce bit for bit is not evidence. |
| 6 | Routes are the agent's own. The TAS, your crossing recordings and the crossing fixtures are validation-only, never starts, prefixes, demonstrations or hints. No hardcoded route or waypoint. | The claim is that the agent found and learned the route. |
| 7 | No RNG seed inspection, logging, control, comparison or hashing. All randomness is Python-side keyed sha256 draws. | A project decision (`CLAUDE.md`). It keeps the study about learning, not RNG manipulation, while keeping the Python side reproducible. |
| 8 | Rewards and ML libraries stay outside the game executable. Measures use game ticks, never wall-clock time. | The native bridge must stay framework-independent and deterministic. |
| 9 | A rule is registered (and hashed) **before** its data exists. Only the registered rule decides an outcome; diagnostics never decide. Nothing follows an outcome automatically. No retries, extensions or repairs inside a session. Every session needs its own approval. | This stops anyone (you, or an AI) from moving the goalposts after seeing results. |
| 10 | A run tree is never overwritten. Each finished tree is backed up to D:, verified by the tool **and** by an independent re-hash, and then stays byte-identical forever (a "protected tree"). `runs/` must show 0 uncovered files before a launch. | Later sessions resume from these exact bytes and are judged against them. Losing or changing them breaks the evidence chain. |
| 11 | Never commit ROMs, `.o2r` files, generated assets, build directories, `runs/`, `logs/`, datasets or checkpoints. | Copyright and repository size. The D: copies hold the evidence. |
| 12 | Launch only from a clean, committed tree. A launch day edits **no tracked file** and stages nothing; it only creates new files. | The approval and the snapshot pin the exact code and documents. Any edit breaks the link between what was approved and what ran. |
| 13 | Run every Python tool with `python -B`. | A compiled `.pyc` under `rl/` is a write-guard violation; the session tools refuse without `-B` [code]. |
| 14 | A memory or free-commit refusal is a stop. The thresholds are registered and never lowered. | A memory breach during a session ends it INCOMPLETE, which can still count toward the line budget (section 4). |
| 15 | Never claim a check you did not run. | `CLAUDE.md`; the whole method rests on it. |

---

## 3. The lifecycle of g3 session k

This is Part B (B0-B13) of `docs/rl_m9_g3_resume_k_prep_decisions_2026-10-08.md` section 8, made concrete and checked against the code. It is
written for **k = 3**. Section 3.5 says what changes for k >= 4.

**Shells.** Run every command below in **Git Bash** from the repository root. That includes the PowerShell scripts, which are called through
`powershell -NoProfile -ExecutionPolicy Bypass -File <path with forward slashes>` (form checked [ran] with `independent_increment_check.ps1`).
Git Bash `>` writes plain bytes, so the JSON outputs stay readable by Python. Windows PowerShell's `>` may add a byte-order mark or write UTF-16,
which Python's JSON loader rejects (**UNVERIFIED** on this machine). Use a PowerShell window only where section 4 says so.

**Every `rl/m9_g3_session.py` and `rl/m9_g3_snapshot.py` subcommand defaults to `--session 1`** [help]. Always pass `--session $K`.

### 3.0 Set the variables (every new terminal)

```bash
cd /c/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip
K=3                                                    # the session you are running (its predecessor is K-1)
DATE=2026-10-09                                        # today's date, YYYY-MM-DD; used in folder and file names
SNAP=D:/BattleShip_source_snapshots/${DATE}_m9_g3_s${K}
INCR=D:/BattleShip_runs_backup/${DATE}_incr_m9_g3_s${K}
PREP=logs/m9_g3_s${K}_prep/launch_${DATE}              # Part B logs (inside the snapshot's file set)
RUNLOG=logs/m9_g3_s${K}_run                            # launch and post-run logs (outside the snapshot's file set)
export PYTHONDONTWRITEBYTECODE=1
```

The increment name must end in exactly `_incr_m9_g3_s<k>`. Session k+1 finds this session's tree by that suffix (section 3.4, step S18).

### 3.1 Phase 0: before Part B (no gate is running)

**S0. Write down the decision.** Add a decision-log entry (section 8.2): which session, why now, and which line consequences you accept (the
approval will compute them for you, section 5.4).

**S1. Make the machine ready** (section 4). From the start of the three passes until the session process exits, nothing else should start on this
machine.

**S2. Commit any document you have written** (this runbook, a decision log, corrections) and push. After this step, **edit no tracked file and stage
nothing** until the session is over and recorded. Fix blocker 1 (section 1.4) first, in its own preparation session.

### 3.2 Phase 1: Part B (zero native ticks)

**S3. B0: the tree is clean, current and the expected code.**

```bash
mkdir -p "$PREP" "$RUNLOG"
git rev-parse HEAD
git rev-parse origin/main
git ls-remote origin refs/heads/main
git status --porcelain --untracked-files=all
git diff --cached --name-only
git diff --check
python -B -X utf8 -c "import sys; from pathlib import Path; sys.path.insert(0, 'logs/m9_g3_resume_tools'); import three_passes as t; print(t.fingerprint(Path('.').resolve()))"
```

Holds when: the three hashes are equal; the three `git` listings print nothing; the fingerprint is the expected one (k = 3 at `162e48b`:
`64259b59b3e09d50` [ran]; after the blocker-1 fix, the value that fix's record pins). Save what you saw, for example
`git status --porcelain --untracked-files=all > "$PREP/git_status_b0.txt"`.

**S4. B1 part 1: the three passes (about 2 hours; nothing else running).**

```bash
python -B -X utf8 logs/m9_g3_resume_tools/three_passes.py --session $K > "$PREP/three_passes_stdout.txt" 2>&1; echo "exit=$?" >> "$PREP/three_passes_stdout.txt"
tail -n 2 "$PREP/three_passes_stdout.txt"
```

Holds when: the verdict line is `THREE_CONSECUTIVE_PASSES` and `exit=0`. In `logs/m9_g3_s${K}_prep/final/passes.json`, each pass shows unit
29/29 and an e2e digest of `078f46c445d8adc5`, with the fingerprint unchanged. **Never pass `--allow-git-gate` here**: it is for preparation rounds
on an uncommitted tree only [help]. The tool refuses to overwrite an existing `passes.json`; for a second attempt give `--out` a new directory under
`logs/m9_g3_s${K}_prep/` [code].

**S5. B1 part 2: the other suites, one after another (never at the same time as S4).**

```bash
python -B -X utf8 rl/m9_g3_rule.py self-test > "$PREP/g3_rule_self_test.txt" 2>&1; echo "exit=$?" >> "$PREP/g3_rule_self_test.txt"
python -B -X utf8 rl/m9_eval_tests.py unit > "$PREP/g1_eval_unit.txt" 2>&1; echo "exit=$?" >> "$PREP/g1_eval_unit.txt"
python -B -X utf8 rl/m9_g2_tests.py unit > "$PREP/g2_unit.txt" 2>&1; echo "exit=$?" >> "$PREP/g2_unit.txt"
python -B -X utf8 rl/m9_tests.py unit > "$PREP/g1_unit.txt" 2>&1; echo "exit=$?" >> "$PREP/g1_unit.txt"
tail -n 2 "$PREP/g3_rule_self_test.txt" "$PREP/g1_eval_unit.txt" "$PREP/g2_unit.txt" "$PREP/g1_unit.txt"
```

Holds when:

- the rule self-test reads `m9_g3_rule self-test: PASS (0 problem(s)), s1 dea9965a3989bce5 line d9d82885703c016d` [ran];
- the g1 evaluation suite reads `m9 eval unit suite: 29/29 passed`;
- the g2 suite reads `m9 g2 unit suite: 29/29 passed`;
- the g1 suite reads `m9 unit suite: 62/63 passed (failed: identity_names_every_registered_pin)` with `exit=1`. That is the documented, pre-existing
  failure (pitfall P2). Any other failure is a stop. [record: the s2 Part B logs]

Runtimes on this machine: about 1, 8 and 6 minutes [record].

**S6. B2: the registered digests.**

```bash
python -B -X utf8 -c "import sys; sys.path[:0] = ['rl', 'rl/tools']; import m9_g3_contract as G, m9_g3_frontier as F, m9_g3_rule as R, m9_g2_contract as G2, m9_contract as C; print('g3_contract', G.contract_digest()); print('line_contract', G.line_contract_digest()); print('frontier', F.contract_digest()); print('s1_rule', R.s1_rule_digest()); print('line_rule', R.line_rule_digest()); print('g2', G2.contract_digest()[:16], G2.line_contract_digest()[:16]); print('g1', C.contract_digest()[:16])" | tee "$PREP/b2_digests.txt"
```

Holds when [ran]: `4cd1deaec0f0333b394f0ac85bc0f3c494c117e63eacc0caf5e80e0929b8e040`, `90eac1a6c6682a397fc8e85abdf5b1d8ab3f38b75a80ae08709932286d319a31`,
`60e174a61c02e1848a25ba7951a5aaf047060a68b9496a8aea82b0d32704b634`, `dea9965a3989bce54a27acc0a33d506664789e4a316f1a0b6aaa512ee66c23a9`,
`d9d82885703c016d147878886461156da7050176615bfd923ec66cb446cf1998`, g2 `8dfd44c6a8b7e319 1aadc7a6b2ff85bd`, g1 `6958857ed2dfd1c5`. A changed digest
means a registered rule or contract changed: stop.

**S7. B3-B7: the dry-run preflight (no unit suite, no game).**

```bash
python -B -X utf8 rl/m9_g3_session.py preflight --session $K --skip-unit > "$PREP/preflight_dry_run.txt" 2> "$PREP/preflight_dry_run_stderr.txt"; echo "exit=$?"
python -B -X utf8 -c "import json, sys; d = json.load(open(sys.argv[1], encoding='utf-8')); print('ok', d['ok']); print('problems', d['problems']); p = d.get('predecessor') or {}; print('predecessor problems', p.get('problems'), 'unregistered', p.get('unregistered_earlier_sessions')); ri = d.get('resume_inputs') or {}; print('expect', ri.get('expect')); print('chain sessions checked', (ri.get('chain') or {}).get('sessions_checked')); print('trees ok', d['trees']['ok']); print('backup', {k: d['backup'].get(k) for k in ('ok', 'source_files', 'uncovered')}); print('readiness', d['readiness']['ok'], d['readiness']['memory']); b = d['budget']; print('budget', b['pessimistic_total_s'], b['fits_global_cap_pessimistic'], b['close']['projected_s_at_the_s2_rate'])" "$PREP/preflight_dry_run.txt"
```

The reader was checked [ran] on the resume-k dry-run output. Holds when:

- `exit=1`, `ok False`, and `problems` is **exactly** `['no approval record at docs\\rl_m9_g3_s3_approval.json (the session is not authorised)']`
  (B6);
- predecessor problems `[]` and unregistered `[]`;
- `expect` = model `e6d2c7d4...`, curriculum `cc7480df...`, tape `81fa52c2...` (B4; compare with section 4 of the resume-k record);
- chain sessions checked = K-1;
- trees ok `True` (B5; the nine trees of Appendix B);
- backup `ok True` with `uncovered 0`;
- readiness `True` (B8);
- budget `7780.0 True` and a projected close near 436 s (B7).

The dry run takes several minutes because it hashes about 2.9 GB of protected trees.

**S8. B4/B5: independent re-hash of the predecessor tree** (no Python, `Get-FileHash` only; seconds to minutes):

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File logs/m9_g3_prep/tools/independent_increment_check.ps1 -Source runs/m9_g3/s$((K-1)) -Dest D:/BattleShip_runs_backup/2026-10-08_incr_m9_g3_s2 | tee "$PREP/predecessor_independent_check.txt"
```

Holds when it ends with `missing=0 extra_in_backup=0 bad=0 result=PASS` [ran on rd2: 62/62 PASS]. For k >= 4, replace the `-Dest` folder with
session k-1's increment. To re-hash all earlier trees the same way, use the loop in Appendix B.

**S9. B8: the machine, just before the snapshot.**

```bash
tasklist //FI "IMAGENAME eq BattleShip.exe" //NH
python -B -X utf8 -c "import sys, json; sys.path[:0] = ['rl', 'rl/tools']; import m8_rd_session as s; print(json.dumps(s.readiness(), default=str)); print('battleship pids', s.game_processes())"
git status --porcelain --untracked-files=all
```

Holds when: `INFO: No tasks are running...`; readiness `"ok": true` with `available_mb` well above 4,096; the pid list is empty; and `git status`
shows nothing except new M9-named files. In Git Bash, `tasklist` needs `//FI` and `//NH` (double slash) [ran].

**S10. Write your authorisation, the last file under `$PREP`.** The approval quotes it verbatim, line by line [code: `write_approval.py`].
Suggested text (**UNVERIFIED** wording; adapt it):

```text
I, the owner, authorise exactly this, once, on <YYYY-MM-DD>:
1. Snapshot D:\BattleShip_source_snapshots\<date>_m9_g3_s<k> (--session <k>), verified by the tool and by an independent PowerShell re-hash.
2. Approval docs/rl_m9_g3_s<k>_approval.json written by logs/m9_g3_resume_tools/write_approval.py --session <k> at the final HEAD.
3. The full preflight for session <k>, once.
4. One detached session via logs/m9_g3_resume_tools/launch_detached.ps1 -Session <k>, resumed from session <k-1>'s final state, waited to
   completion. No retries, extensions, repairs, and no session <k+1>.
5. Afterwards: the increment D:\BattleShip_runs_backup\<date>_incr_m9_g3_s<k> verified by the tool (--source runs/m9_g3/s<k>) and by an
   independent re-hash; the earlier trees unchanged; runs/ coverage 0 uncovered; verify-run for session <k>; the results record
   docs/rl_m9_g3_s<k>_results_<date>.md.
```

Save it as `"$PREP/authorisation_s${K}_${DATE}.txt"`. **From now on, write nothing under `logs/m9_g3_s${K}_prep/`, `logs/m9_g3_prep/`,
`logs/m9_g3_s2_prep/`, `logs/m9_g3_resume_tools/` or `logs/m9_g3_resume_k_prep/` until the session has ended.** These directories are in the
session-k snapshot's file set [ran: `m9_g3_snapshot.log_dirs(3)`].

### 3.3 Phase 2: snapshot, approval, the single full preflight, launch, wait

> Blocked for k = 3 at `162e48b`: step S13 will refuse once S12 has written the approval (section 1.4, blocker 1). Do not start S11 until the
> test is fixed.

**S11. B10: the source snapshot (a few minutes), verified twice.**

```bash
python -B -X utf8 rl/m9_g3_snapshot.py snapshot --dest "$SNAP" --session $K > "$RUNLOG/snapshot_create.txt"; echo "exit=$?" >> "$RUNLOG/snapshot_create.txt"
python -B -X utf8 rl/m9_g3_snapshot.py verify --dest "$SNAP" > "$RUNLOG/snapshot_verify.txt"; echo "exit=$?" >> "$RUNLOG/snapshot_verify.txt"
python -B -X utf8 rl/m9_g3_snapshot.py powershell --dest "$SNAP" --out "$RUNLOG/independent_snapshot_rehash.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "$RUNLOG/independent_snapshot_rehash.ps1" > "$RUNLOG/independent_snapshot_rehash_output.txt"
cat "$RUNLOG/snapshot_create.txt" "$RUNLOG/snapshot_verify.txt" "$RUNLOG/independent_snapshot_rehash_output.txt"
```

Holds when [code: `rl/m9_g3_snapshot.py`, `rl/m8_rd_snapshot.py`; record: s2]:

- the create line shows `"session": 3, "result": "PASS"` and empty mismatch lists, followed by `snapshot.json sha256 <hash>`;
- the verify line shows `"result": "PASS"` and `"executable_equal": true`;
- the PowerShell line shows `bad=0 ... exe_ok=True result=PASS snapshot_json=<the same hash>`.

The snapshot refuses an existing destination.

**S12. B9: the approval (a new file in `docs/`).**

```bash
python -B -X utf8 logs/m9_g3_resume_tools/write_approval.py --session $K --snapshot "$SNAP" --independent "tool verify (rl/m9_g3_snapshot.py verify) PASS at <utc from snapshot_verify.txt>: <n> files, 0 mismatches, 0 extra, 0 external mismatches, executable equal; independent PowerShell Get-FileHash re-hash (rl/m9_g3_snapshot.py powershell -> $RUNLOG/independent_snapshot_rehash.ps1, no repository module): <paste the output line>" --authorisation-file "$PREP/authorisation_s${K}_${DATE}.txt" --authorised-on $DATE > "$RUNLOG/approval_written.txt"; echo "exit=$?" >> "$RUNLOG/approval_written.txt"
cat "$RUNLOG/approval_written.txt"
```

Holds when: it prints `written` with the approval's sha256, `expect`, the `previous_sessions` rows and `line_consequence_if` (section 5.4), and
`exit=0`. It refuses, among other things: an existing approval, a snapshot from another session or another HEAD, an unregistered earlier session,
predecessor problems, an empty authorisation, or a malformed date [help, code]. **From here until the launch: no commit, no edit of any pinned
document, no `runs_backup.py verify` on any existing increment** (pitfall P8).

**S13. Readiness, then the single full preflight (about 30 minutes).**

```bash
python -B -X utf8 -c "import sys, json; sys.path[:0] = ['rl', 'rl/tools']; import m8_rd_session as s; print(json.dumps(s.readiness(), default=str))" > "$RUNLOG/readiness_before_full_preflight.txt"; cat "$RUNLOG/readiness_before_full_preflight.txt"
python -B -X utf8 rl/m9_g3_session.py preflight --session $K > "$RUNLOG/preflight_full.txt" 2> "$RUNLOG/preflight_full_stderr.txt"; echo "exit=$?" > "$RUNLOG/preflight_full_exit.txt"
cat "$RUNLOG/preflight_full_exit.txt"
python -B -X utf8 -c "import json, sys; d = json.load(open(sys.argv[1], encoding='utf-8')); print('ok', d['ok'], 'problems', d['problems']); print('unit', d.get('unit_suite_m9_g3'), 'rule', d.get('rule_self_test_m9_g3')); print('approval', d['approval']); print('snapshot', d['source_snapshot']); print('readiness', d['readiness']['memory'])" "$RUNLOG/preflight_full.txt"
```

Holds when: `exit=0`, `ok True`, `problems []`, approval `approved`, snapshot `snapshot recorded, PASS and equal to the repository`, and the unit
line `m9 g3 unit suite: 29/29 passed` [code: `preflight()`]. If it refuses, **stop and read the problems**. Whether to try again is your decision
and goes in the decision log. Do not re-run hoping for a different result.

**S14. B11: the launch (detached; the session's own full preflight runs again inside `run` before the session clock starts).**

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File logs/m9_g3_resume_tools/launch_detached.ps1 -Session $K -Repo 'C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip'
cat "$RUNLOG/launch_record.txt"
```

It prints `launched pid=<n> at <utc> session=3` and starts `python -B -u -X utf8 rl/m9_g3_session.py run --session 3`, with stdout and stderr in
`$RUNLOG/session_stdout.txt` and `session_stderr.txt` [code]. It refuses when either session log already exists, when `runs/m9_g3/s<k>` exists,
when no approval exists, or when the predecessor's `final_state.json` is missing. A refusal leaves nothing behind. Calling the script from Git
Bash in this form is checked only through `independent_increment_check.ps1` [ran]; s1 and s2 were launched with the same script form, but their
records do not name the shell [record].

**S15. Wait (about 2 to 3 hours: 25-30 minutes of internal preflight, then up to 145 minutes of session clock; s2's clock ran 91 minutes).**

```bash
python -B -X utf8 logs/m9_g3_resume_tools/wait_session.py --session $K > "$RUNLOG/wait_session_stdout.txt"; echo "exit=$?" >> "$RUNLOG/wait_session_stdout.txt"
```

It blocks, polls every 60 s, appends one line per change to `$RUNLOG/wait_log.txt`, and exits 0 when `state.json` says `done` and the process has
gone (hard timeout `--hours 4.5`) [code]. To look at the session from a second terminal without touching it:
`python -B -X utf8 rl/m9_g3_session.py status --session $K` [ran on k = 3: `run_root_exists: false`]. Do not open applications while it runs
(section 4). Whether closing the terminal that started the launcher affects the detached process is **UNVERIFIED**: keep it open and do not log off.

### 3.4 Phase 3: after the run (in this order; nothing is written into `runs/` except step S17)

**S16. verify-run against the predecessor, and the report, both outside the tree.**

```bash
python -B -X utf8 rl/m9_g3_session.py verify-run --session $K > "$RUNLOG/verify_run.json" 2> "$RUNLOG/verify_run_stderr.txt"; echo "exit=$?" > "$RUNLOG/verify_run_exit.txt"
python -B -X utf8 rl/m9_g3_session.py report --session $K > "$RUNLOG/report.json" 2> "$RUNLOG/report_stderr.txt"; echo "exit=$?" > "$RUNLOG/report_exit.txt"
python -B -X utf8 -c "import json, sys; v = json.load(open(sys.argv[1], encoding='utf-8')); rc = v.get('resume_checks') or {}; print('ok', v['ok'], 'problems', v['problems']); print('rule', v['rule_recomputed']); print('line', v['line_recomputed']); print('replays', v['verification']); print('chain ok', (rc.get('chain') or {}).get('ok'), 'equal_to_predecessor_record', rc.get('equal_to_predecessor_record')); print('initial ckpt', (rc.get('initial_checkpoint') or {}).get('members_sha256'), 'predecessor final', rc.get('predecessor_final_members'))" "$RUNLOG/verify_run.json"
```

`verify-run --session k` automatically checks against `runs/m9_g3/s<k-1>` and the whole chain s1 .. s(k-1) [code: `cmd_verify_run`]. The reader was
checked [ran] on the resume-k `verify_run_s2.json`. Holds when: `ok True`, `problems []`, rule and line recomputed equal to recorded, `inexact []`,
`tier0_without_replay 0`, `chain ok True`, `equal_to_predecessor_record True`, and the initial checkpoint's members equal the predecessor's final
members.

**S17. Copy the launch evidence into the tree, before the backup** (as s1 and s2 did; s2 results record section 8). **UNVERIFIED as exact
commands**: no tool does this. The layout is the one the s2 record describes.

```bash
mkdir -p runs/m9_g3/s$K/launch/prep runs/m9_g3/s$K/derived
cp -p "$RUNLOG/verify_run.json" "$RUNLOG/report.json" runs/m9_g3/s$K/derived/
for f in "$RUNLOG"/*; do case "$(basename "$f")" in verify_run.json|report.json) ;; *) cp -p "$f" runs/m9_g3/s$K/launch/ ;; esac; done
cp -rp logs/m9_g3_s${K}_prep/. runs/m9_g3/s$K/launch/prep/
cp -p "$SNAP/snapshot.json" runs/m9_g3/s$K/launch/source_snapshot_record.json
cp -p "$SNAP"/verify_*.json runs/m9_g3/s$K/launch/
diff -rq logs/m9_g3_s${K}_prep runs/m9_g3/s$K/launch/prep
python -B -X utf8 rl/m9_g3_session.py verify-run --session $K > "$RUNLOG/verify_run_after_copies.json"; echo "exit=$?" > "$RUNLOG/verify_run_after_copies_exit.txt"
```

`verify-run` skips `launch/` and `derived/` in its metadata audit [code: `verify_run`, D13], so the second run must still say `ok: true`. After this
step, never write into `runs/m9_g3/s$K` again.

**S18. B11: the D: increment `<date>_incr_m9_g3_s<k>`, verified three ways.**

```bash
python -B -X utf8 rl/tools/runs_backup.py backup --source runs/m9_g3/s$K --dest "$INCR" > "$RUNLOG/backup_m9_g3_s$K.txt" 2>&1; echo "exit=$?" >> "$RUNLOG/backup_m9_g3_s$K.txt"
python -B -X utf8 rl/tools/runs_backup.py verify --source runs/m9_g3/s$K --dest "$INCR" > "$RUNLOG/backup_m9_g3_s${K}_verify.txt" 2>&1; echo "exit=$?" >> "$RUNLOG/backup_m9_g3_s${K}_verify.txt"
powershell -NoProfile -ExecutionPolicy Bypass -File logs/m9_g3_prep/tools/independent_increment_check.ps1 -Source runs/m9_g3/s$K -Dest "$INCR" > "$RUNLOG/independent_increment_check_m9_g3_s$K.txt"
tail -n 2 "$RUNLOG/backup_m9_g3_s$K.txt" "$RUNLOG/backup_m9_g3_s${K}_verify.txt"; cat "$RUNLOG/independent_increment_check_m9_g3_s$K.txt"
```

Holds when: both tool runs end `verification PASS: files <n> bytes <b> hash mismatches 0 problems 0` with `exit=0`, and the independent line reads
`missing=0 extra_in_backup=0 bad=0 result=PASS` with `checked` = `source_files` = `backup_files` = n [code; record: s2 4,478].

**`--source runs/m9_g3/s$K` is mandatory on both tool commands.** Its default is the whole `runs/`. Without it, `backup` copies everything into the
new folder, and `verify` compares the increment against all of `runs/` and **overwrites `verification.json` with FAIL** (pitfall P4).

**How session k+1 finds this increment** [code: `increment_dirs_for`, `increment_facts`, `predecessor_tree`]: exactly one folder under
`D:\BattleShip_runs_backup` whose name ends in `_incr_m9_g3_s<k>`. Its `verification.json` must say PASS, and its `source` must resolve to
`runs/m9_g3/s<k>`, so run the commands from the repository root. Its `manifest.tsv.gz` must hash to the recorded digest. Zero or two such folders
make session k an "unregistered predecessor", and session k+1 refuses.

**S19. The earlier trees, the coverage, and the discovery check for session k+1.**

```bash
python -B -X utf8 -c "import sys, json; sys.path[:0] = ['rl', 'rl/tools']; import m9_g3_session as S; print(json.dumps(S.trees_state($K), indent=1, default=str))" > "$RUNLOG/post_trees_tool_check.txt"
python -B -X utf8 -c "import sys, json; sys.path[:0] = ['rl', 'rl/tools']; import m8_rd_session as s; c = s.combined_coverage(); print(json.dumps({k: c.get(k) for k in ('ok', 'reason', 'source_files', 'uncovered')}), len(c.get('increments') or []))" > "$RUNLOG/post_coverage.txt"
python -B -X utf8 -c "import sys; sys.path[:0] = ['rl', 'rl/tools']; import m9_g3_session as S; k = $K; print('unregistered before session', k + 1, S.unregistered_predecessors(k + 1)); t = S.predecessor_tree(k); print(t and (t[0], t[2].name, dict(t[3])))" > "$RUNLOG/next_session_discovery.txt"
cat "$RUNLOG/post_coverage.txt" "$RUNLOG/next_session_discovery.txt"; grep '"ok"' "$RUNLOG/post_trees_tool_check.txt"
```

Holds when:

- every tree in `post_trees_tool_check.txt` is `"ok": true` (k = 3: the nine of Appendix B). The function exists [code], but this exact command was
  not run here because it hashes about 2.9 GB;
- the coverage reads `"ok": true ... "uncovered": 0` with one more increment than before (15 after s3) [ran today: 432,800 files, 0, 14];
- the discovery file shows `unregistered ... []`, and a tuple whose files, bytes and manifest equal the backup's (today, before any s3 increment,
  it returns `[3]` and `None` [ran]).

Add the independent re-hash of every earlier tree with the loop in Appendix B, written to `"$RUNLOG/post_trees_independent_check.txt"`.

**S20. The results record, written by hand: `docs/rl_m9_g3_s<k>_results_<date>.md`.** There is **no tool** for this. Session k+1's preflight requires
**exactly one** file matching `docs/rl_m9_g3_s<k>_results_*.md` and pins its sha256 [code: `predecessor_doc_problems`, `doc_files`]. Never leave a
draft with a matching name (pitfall P9), and never edit it after session k+1's snapshot. Copy the structure of
`docs/rl_m9_g3_s2_results_2026-10-08.md`:

1. the outcome and the line outcome with their rule ids and digests;
2. what was run: HEAD, fingerprint, snapshot and approval sha256, preflight, pid, session clock;
3. the Part B table B0-B13;
4. the phases table (wall, ticks, caps);
5. the resume proof (inputs, members, counters);
6. training and the frontier;
7. the close audit against the previous session and the tape;
8. resources against the caps;
9. integrity and verification (verify-run, replays, trees, increment, coverage);
10. the saved state for the next session (final-state, model, members, curriculum digests, counters, next seed);
11. departures;
12. what it does and does not say;
13. `git status` at the end.

**S21. Commit by hand, then push.**

```bash
git status --porcelain --untracked-files=all
git diff --check
git add docs/rl_m9_g3_s${K}_approval.json docs/rl_m9_g3_s${K}_results_<date>.md
git diff --cached --stat
git commit -m "M9-g3-s${K}: <outcome in a few words>"
git push origin main
git rev-parse HEAD; git ls-remote origin refs/heads/main
```

Only the approval and the results record should be new; `runs/` and `logs/` are Git-ignored and are never committed. This matches the pattern of
`f221a39` (s1) and `cb7a8f6` (s2) [ran: `git log --stat`]. Then complete the review checklist (section 8.1).

### 3.5 What changes for k >= 4

- **B0:** the fingerprint must equal the value the previous results record pinned (it changes only if code changed, for example the blocker fix).
- **The predecessor** is discovered from its increment (S18), not registered in code. Check `unregistered_predecessors(K) == []` (the S19 one-liner
  with k = K-1) before Part B.
- **Blocker 2 (section 1.4):** the g3 unit suite pins "s3 not recorded" today and will fail at s4's Part B until it is generalised.
- **The line consequence** is computed for you in the approval (section 5.4). For k = 4 it is the END_BUDGET_1966 session: D_4 must be <= 1,966.
- `three_passes.py` refuses an output directory inside `logs/m9_g3_prep`, `logs/m9_g3_s2_prep` or `logs/m9_g3_resume_tools`, but **not** inside
  `logs/m9_g3_resume_k_prep`. Keep its output under `logs/m9_g3_s<k>_prep/` [code].
- The snapshot's log set for k >= 3 is `logs/m9_g3_prep`, `logs/m9_g3_s2_prep`, `logs/m9_g3_resume_tools`, `logs/m9_g3_resume_k_prep` and
  `logs/m9_g3_s<k>_prep` (it does not include earlier sessions' `s<j>_prep`) [ran: `log_dirs(4)`].

### 3.6 Files a session creates

| path | tracked? | when |
| --- | --- | --- |
| `logs/m9_g3_s<k>_prep/**` (three passes, suite logs, dry run, authorisation) | ignored | Part B, before the snapshot |
| `D:\BattleShip_source_snapshots\<date>_m9_g3_s<k>` | no | S11 |
| `docs/rl_m9_g3_s<k>_approval.json` | new; commit after the session | S12 |
| `logs/m9_g3_s<k>_run/**` | ignored | S11 onward |
| `runs/m9_g3/s<k>/**` | ignored | the session, plus the S17 copies |
| `D:\BattleShip_runs_backup\<date>_incr_m9_g3_s<k>` | no | S18 |
| `docs/rl_m9_g3_s<k>_results_<date>.md` | new; commit with the approval | S20 |

---

## 4. Machine readiness

**Thresholds the preflight checks** [code: `rl/m8_rd_session.READINESS`]: at least **4,096 MB available memory**, at least **10,240 MB free commit**,
and at least **5 GiB free on C: and on D:**. The check runs at the **end** of each preflight, so an application started during the 25-30 minute
unit suite still counts.

**Caps during the session** [code: `rl/m9_contract.MEMORY_CAPS_MB`]: system available at least **1,024 MB**, system commit free at least
**2,048 MB**, main process private at most 3,072 MB, process-tree private at most 9,216 MB, tree working set at most 4,096 MB, at most 10
BattleShip processes. A breach needs two consecutive 5-second samples [record: s2 pre-launch review section 3]. A breach ends the session
**INCOMPLETE**. If training had reached 50 % of its wall time, the session still counts toward k with no depth. For session 4 that means
END_BUDGET_1966: the line ends (section 5.4).

**What has gone wrong before** [record]:

- s1's first full preflight was refused at 3,011 MB after IntelliJ (`idea64`, 2.1 GB) and seven Chrome processes (2.0 GB) were started during it.
- A `node` process (9.8 GB working set, 17.1 GB private) appeared during the resume-k preparation. The memory guard stopped a synthetic session
  with 131 MB free.

**Today's reading:** 4,112 MB available, just 16 MB above the threshold, with IntelliJ and five Claude processes open [ran].

**Before Part B and again before S13:**

1. Close the IDE (IntelliJ `idea64`), every browser, any video editor, and the replay viewer and browser (`replay/`). The viewer starts
   `BattleShip.exe`, and any BattleShip process makes the preflight refuse with "BattleShip already running" [code: `game_processes()`].
2. Look for large processes, `node` in particular. In a **PowerShell window** (checked [ran]):

   ```powershell
   Get-Process | Sort-Object PrivateMemorySize64 -Descending | Select-Object -First 8 Name, Id, @{n='Private_MB';e={[int]($_.PrivateMemorySize64/1MB)}}, @{n='WS_MB';e={[int]($_.WorkingSet64/1MB)}} | Format-Table -AutoSize
   ```

   Task Manager's Details tab, sorted by memory, shows the same (**UNVERIFIED** UI labels).
3. Run at most **one** Claude session, and none at all while a gate or the native session runs. Each `claude` process held 415-808 MB today
   [ran]; a second session can also stage files and trip the git gates (pitfall P6).
4. **No sleep.** Set the PC to never sleep while plugged in, for the whole day (Settings > System > Power; **UNVERIFIED** path). The effect of
   sleep on a running session is **UNVERIFIED**. Do not find out.
5. Re-read readiness with the S9 one-liner. Aim for several GB of margin, not 16 MB.
6. **Applications opened during a session can stop it.** From the start of S4 to the end of S15, start nothing (no browser "quick look", no
   IDE, no viewer).

---

## 5. Reading a results record and judging it (worked example: g3-s2)

### 5.1 The words

| term | meaning | source |
| --- | --- | --- |
| landing states | 2,128, 1,966, 1,694, 1,473, 1,369, 1,248: the first tick of each grounded segment of the shared trunk of the agent's own rd4 clear | [code: `rl/m9_contract.LANDINGS`] |
| close audit | at each audited landing: 20 sticky episodes (keys 0-19, the same draws as the tape and the previous sessions, so the comparison is paired), 20 unperturbed, 1 deterministic; at tick 0: 20 sticky plus 1 deterministic | [record] |
| **D** (depth) | the earliest landing such that it, and every later audited landing, has at least **10 of 20 verified** sticky clears | [code: `s1_rule_description`] |
| **R** (reach) | the same chain, but each landing needs its bar **B = max(10, ceil(20 x p_hat) + 5)**, where p_hat is the reused tape's clear rate there. 2,128: 98/200, so **B = 15**; every other landing: B = 10 | [code: `bar_from_counts`; record] |
| per-session rule `m9_g3_s1_rule_v1` (used by every g3 session; its reason text says "D_1" even for later sessions) | first match wins: **INVALID** (integrity) > **INCOMPLETE** (a phase failed, training ended early, audit incomplete, or an unverified clear could change D or R) > **PASS** if R <= 1,966 > **INCONCLUSIVE** if D <= 2,128 > **NULL** | [code: `apply_s1`] |
| line rule `m9_g3_line_rule_v1` | applied after every session, in order: SUSPENDED, END_SUCCESS, END_BUDGET_2128 / 1966 / 1694, END_NO_PROGRESS, END_CAP, CONTINUE | [code: `apply_line`] |
| counted k | sessions whose training reached at least 50 % of the wall cap. An INCOMPLETE session below that does not count; two INCOMPLETE sessions in a row SUSPEND the line | [code] |
| frontier pointer | where training episodes start (moves back 20 ticks per passed strip test). It is **not** D. s2's pointer 2,040 lies between landings 2,128 and 1,966 | [record] |
| diagnostics | R_unperturbed, deterministic, tick 0, FRONTIER_BACKED, entropy, the trigger-to-test gap, attempt counts: **reported, never deciding** | [code: `s1_rule_description`] |

### 5.2 Where the numbers are

| file | what to read |
| --- | --- |
| `logs/m9_g3_s<k>_run/verify_run.json` | integrity first: `ok`, `problems`, `rule_recomputed`, `line_recomputed`, `verification`, `resume_checks` (S16) |
| `runs/m9_g3/s<k>/session/rule.json` | `outcome`, `D`, `R`, `reasons`, `facts.audit` (per landing: n, clears, verified), `bars`, `facts.training`, `facts.train_fraction` |
| `runs/m9_g3/s<k>/session/line.json` | `outcome`, `k`, `depths`, `sessions` (one row per session) |
| `runs/m9_g3/s<k>/session/state.json`, `memory_summary.json`, `leftover_processes.json` | `done`; memory peaks and breach; leftover processes |
| `logs/m9_g3_s<k>_run/report.json` | readings only (pointer over time, attempts, tape comparison) |
| `docs/rl_m9_g3_s<k>_approval.json` -> `line_consequence.if_this_session_is` | what each outcome was registered to mean, before the run |

### 5.3 Worked example: g3-s2, judged by hand

Read the two records [ran]:

```bash
python -B -X utf8 -c "import json, sys; d = sys.argv[1]; r = json.load(open(d + '/session/rule.json', encoding='utf-8')); l = json.load(open(d + '/session/line.json', encoding='utf-8')); print('session', r['session'], r['outcome'], 'D', r['D'], 'R', r['R'], r['reasons']); print('audit', r['facts']['audit'], 'bars', r['bars']); print('training end', r['facts']['training'], 'train_fraction', r['facts']['train_fraction']); print('line', l['outcome'], 'k', l['k'], 'depths', l['depths'], l['reasons'])" runs/m9_g3/s2
```

Output (abridged):

```text
session 2 INCONCLUSIVE D 2128 R None ['D_1 = 2128 <= 2128; R_1 = None']
audit {'1966': {'n': 20, 'clears': 3, 'verified': 3}, '2128': {'n': 20, 'clears': 13, 'verified': 13}} bars {'2128': 15, '1966': 10, ...}
training end {'valid_end': True, 'stop': 'wall cap of phase train reached (4800 s > 4800 s)'} train_fraction 0.9988
line CONTINUE k 2 depths [None, 2128] ['session 3 is proposable, with its own approval']
```

Now judge it yourself, step by step:

1. **Integrity.** `verify_run.json`: `ok: true`, 0 problems, 68 of 68 replays exact, `tier0_without_replay 0`, rule and line recomputed equal to
   recorded [record]. If this fails, nothing below counts.
2. **INVALID?** No invalid reason was recorded. **INCOMPLETE?** P1, P2 and T0 passed; training ended at its valid end (the 4,800 s wall cap); the
   audit is complete at 2,128 (n = 20); verified clears equal claimed clears (13 = 13, 3 = 3), so no unverified clear could change D or R. Not
   INCOMPLETE.
3. **D:** at 2,128, 13 >= 10, so the chain holds; at 1,966, 3 < 10, so the chain stops. **D = 2,128.**
4. **R:** at 2,128 the bar is 15 and 13 < 15, so the chain fails at its first link. **R = none.**
5. **PASS** needs R <= 1,966: no. **INCONCLUSIVE** needs D <= 2,128: yes. **Outcome INCONCLUSIVE.**
6. **Line.** Rows: s1 NULL (D none, train fraction 0.9985), s2 INCONCLUSIVE (D 2,128, 0.9988). Both count, so k = 2. Not INVALID, not two
   INCOMPLETE. D_2 = 2,128 is not <= 1,473, so not END_SUCCESS. k = 2 is a budget milestone needing D_2 <= 2,128: met. k < 4, so no progress test;
   k < 8. **CONTINUE.**
7. **Diagnostics, reported only:** R_unperturbed 2,128; the deterministic episode from 2,128 cleared; tick 0 0 of 20; the pointer held at 2,040
   for the last 44 minutes. Interesting, but none of them changes the outcome.

You can also let the registered code recompute it [ran]:

```bash
python -B -X utf8 -c "import json, sys; sys.path[:0] = ['rl', 'rl/tools']; import m9_g3_rule as R; d = sys.argv[1]; r = json.load(open(d + '/session/rule.json', encoding='utf-8')); l = json.load(open(d + '/session/line.json', encoding='utf-8')); s = R.apply_s1(r['facts']); print('s-rule recomputed', s['outcome'], s['D'], s['R'], s['D_chain'], s['R_chain']); print('line recomputed', R.apply_line(l['sessions'])['outcome'])" runs/m9_g3/s2
```

Output: `s-rule recomputed INCONCLUSIVE 2128 None {'2128': True, '1966': False} {'2128': False}` and `line recomputed CONTINUE`.

### 5.4 What the next sessions must achieve (computed today from s2's rows by `line_consequence` [ran])

**Session 3**, counted k = 3:

| s3 result | line |
| --- | --- |
| NULL; INCONCLUSIVE or PASS with D = 2,128, 1,966 or 1,694; INCOMPLETE (either way) | CONTINUE |
| D = 1,473, 1,369 or 1,248 | END_SUCCESS |
| INVALID | SUSPENDED |

**Session 4**, counted k = 4. The table is the same whatever s3 produced (none, 2,128 or 1,966):

| s4 result | line |
| --- | --- |
| NULL; D = 2,128; INCOMPLETE that counts | **END_BUDGET_1966** (the line ends) |
| D = 1,966 or 1,694 | CONTINUE |
| D <= 1,473 | END_SUCCESS |
| INCOMPLETE that does not count | CONTINUE |
| INVALID | SUSPENDED |

So the line's real test is session 4: **depth 1,966 by k = 4**, from today's D = 2,128 with 3 of 20 at 1,966. To reproduce the table for any k, use
`S.line_consequence(k, rows)` with `rows` read from the predecessor's `session/line.json`; the approval writer stores the same table in the approval.

---

## 6. Known pitfalls

| # | pitfall | what happened or what the code does | what to do |
| --- | --- | --- | --- |
| P1 | **Git-clean gates.** Any modified tracked file, any staged file, or any new non-M9 file under `rl/` or `docs/` fails the g1, g2 and g3 git tests; a modified tracked file also makes the preflight refuse | `git_problems`, the three `tracked_files_are_unchanged_*` tests [code]; the re-check round of 2026-10-06 and the s2 review H15 [record]. **This runbook itself is such a file until committed.** | Commit everything first, then stage nothing. Records of a launch day go to **new** M9-named files (`docs/rl_m9_...`), never into an edited tracked record. Amendments go to a new file |
| P2 | **The g1 identity test is a known failure** | `rl/m9_tests.py` `identity_names_every_registered_pin` fails since `4a778b4` (2026-10-04): g1's own code list does not name the later `rl/m9_*.py` files. Expected result: **62/63** [record: decisions record section 7] | Accept 62/63 with exactly that test failing. Any other failure is a stop. Never edit a g1 file to "fix" it |
| P3 | **Older tools have no argument parser** | `logs/m9_g3_prep/tools/three_passes.py` and `wait_session.py` have none: `--help` starts the real job (on 2026-10-07 it started s1's three passes and overwrote `logs/m9_g3_prep/final/fingerprint_start.txt`) [code, record]. The test suites take a positional command: **no argument runs the whole unit suite**; `--help` prints the docstring and exits 2. `rl/m9_g3_rule.py` with no argument prints the rule texts | For k >= 3 use only `logs/m9_g3_resume_tools/*` (all have argparse [help]) plus the generic `logs/m9_g3_prep/tools/independent_increment_check.ps1`. Treat the s1 and s2 tool folders as history |
| P4 | **Backup verify needs the correct `--source`** | `rl/tools/runs_backup.py` defaults `--source` to all of `runs/` [code]. In g2-s1, a verify without it compared against `runs/` and overwrote the increment's `verification.json` with FAIL; re-running with `--source` restored PASS [record: `docs/rl_m9_g2_s1_results_2026-10-06.md` line 124] | Always `--source runs/m9_g3/s<k>`, from the repository root. A FAIL record or a wrong `source` also breaks session k+1's discovery (S18) |
| P5 | **Never write logs into a tree being snapshotted or copied** | The snapshot set includes `logs/m9_g3_s<k>_prep/**` and earlier prep and tool folders. A file changed there after the snapshot makes `snapshot_status` refuse [code]. In the s2 preparation, a g1 suite writing into the snapshot set made the g3 suite's snapshot round trip fail [record]. A file written into `runs/` after the backup makes coverage "uncovered", and the next preflight refuses [code] | Part B logs before the snapshot, later logs in `logs/m9_g3_s<k>_run/`; `verify-run` and `report` outputs never into `runs/`; S17 copies before S18, and nothing into `runs/` after |
| P6 | **Never run two sessions that edit files or run gates at the same time** | During the s2 review a second session staged two docs mid-chain and the g2 gate failed [record]. Two suites writing logs at once broke a pass [record] | One AI session at most, none during gates; run the suites one after another |
| P7 | **`--session` defaults to 1** | Every `m9_g3_session.py` subcommand and `m9_g3_snapshot.py` [help]. Without it, `preflight` refuses (s1 exists), `verify-run` checks s1, and the snapshot is a session-1 one, which `write_approval.py` refuses | Always pass `--session $K` |
| P8 | **Approvals are tied to HEAD and to what they pin** | `approval_status` compares the whole identity: `git_head`, code digests, the pinned docs (`doc_files(k)`: the g3 decision and implementation records, the s2 review and preparation records, the resume-k record, every earlier approval and results record), the protected trees, and the D: folders' top-level files (`d_records`) [code]. `write_approval.py` refuses a snapshot taken at another HEAD | Between S11 and S14: **no commit, no edit of a pinned doc, no `runs_backup.py verify` on any existing increment** (it rewrites `verification.json`). Commit the approval only after the session. An approval is used once |
| P9 | **The results-record glob** | Session k+1 needs exactly one `docs/rl_m9_g3_s<k>_results_*.md` [code] | Drafts must not match (for example, keep drafts outside `docs/` until final) |
| P10 | **Memory refusals** | The preflight refuses below 4,096 MB available or 10,240 MB free commit; the session ends INCOMPLETE below 1,024 MB or 2,048 MB [code] | Section 4. A refusal is a stop and a logged decision, never a reason to lower a threshold |
| P11 | **The launcher never relaunches** | It refuses while `logs/m9_g3_s<k>_run/session_stdout.txt` or `session_stderr.txt` exists, even if `run` refused before creating `runs/m9_g3/s<k>` [code] | Read why it stopped. Any retry is your explicit, logged decision (and P8 still applies) |
| P12 | **One increment folder per session** | Discovery needs exactly one folder ending in `_incr_m9_g3_s<k>` [code] | Re-run a failed backup into the **same** `$INCR`. Never create a second dated folder for the same session |
| P13 | **Shell details** | Git Bash: `tasklist //FI ...` (double slash) [ran]. Windows PowerShell `>`: BOM or UTF-16 risk for JSON (**UNVERIFIED** here) | Use the forms in this runbook |
| P14 | **Session k+1's unit suite pins "s3 not recorded"** | Blockers 1 and 2 in section 1.4 [code, ran] | Fix in a preparation session before S11 for s3, and before Part B for s4 |

---

## 7. Model and cost guidance

This is guidance, not something the code checks. Model choice and prices are **UNVERIFIED** here.

- **Design and review: use the most capable model you have** (for example the Opus 5.5 tier). Use it for proposals, rule wording, pre-launch
  reviews, diagnosing a refusal, judging a surprising result, and fixing blockers 1 and 2. These are the tasks where a missed detail costs a
  session; the blockers above were found only by reading the tests against the launch order.
- **Scoped execution: a cheaper model is enough** (for example Sonnet 5.5) when the step is fully specified here, such as "run S16-S19 for k = 3
  and report the holds-when lines". A Haiku-class model suits summarising one log file.
- **Keep sessions short.** One bounded task per AI session, and a fresh session per milestone (`CLAUDE.md`). Start each one with the runbook step
  numbers and the exact files to read. Do not ask it to "read every doc": `docs/rl_m8_rd*` and `docs/rl_m9_*` alone are about 14,000 lines.
- **No AI session during Part B, the full preflight or the native run.** It holds memory (section 4) and can touch git state (P1, P6).
- Prefer pasting the holds-when lines of this runbook into a prompt over asking an AI to infer them again from the records.

---

## 8. After every session: review checklist and decision log

### 8.1 One-page review checklist (session k)

Integrity

- [ ] `verify_run.json`: `ok: true`, `problems: []`.
- [ ] Rule and line recomputed equal to recorded.
- [ ] `inexact: []` and `tier0_without_replay: 0`.
- [ ] `resume_checks.chain.ok: true` and `equal_to_predecessor_record: true`.
- [ ] Initial-checkpoint members equal the predecessor's final members.
- [ ] `verify_run_after_copies.json` also `ok: true`.
- [ ] `state.json` `done: true`; `session_stderr.txt` empty; `leftover_processes.json` empty; `memory_summary.json` shows no breach.
- [ ] Training ended at a valid end (`rule.json` `facts.training`); `train_fraction` recorded (>= 0.5 means the session counts).

Outcome, by hand (section 5.3)

- [ ] D and R re-derived from `facts.audit` and `bars`; per-session outcome re-derived.
- [ ] Line outcome re-derived from `line.json` rows; equal to `line.json`.
- [ ] Equal to the row the approval's `line_consequence.if_this_session_is` predicted for that result.

Evidence

- [ ] S17 copies made **before** the backup; `diff -rq` clean.
- [ ] Increment `<date>_incr_m9_g3_s<k>`: tool backup PASS, tool verify (with `--source`) PASS, independent re-hash PASS; counts equal the tree.
- [ ] All earlier trees `ok` (tool) and PASS (independent).
- [ ] Coverage `uncovered: 0`, increments +1.
- [ ] Discovery check: `unregistered_predecessors(k+1) == []`; the discovered facts equal the backup.

Records and git

- [ ] Exactly one `docs/rl_m9_g3_s<k>_results_*.md`, final.
- [ ] The approval and the results record committed together; pushed; `HEAD` = `origin/main` = remote.
- [ ] No tracked file was modified during the launch day; nothing left staged; `git status` clean.
- [ ] Decision-log entry written. No session k+1 started without a new authorisation.

### 8.2 Decision-log template

Keep the log either **outside the repository** (for example next to `..\guide.md`), or as a tracked doc whose name contains `m9` that you edit
only between sessions and commit before Part B. An untracked non-M9 file in `docs/`, or an edited tracked file, trips the gates (P1).

```markdown
## <YYYY-MM-DD> <short title>  (session m9_g3_s<k>, phase: <before Part B | after S13 refusal | after the run | ...>)

- Context: <what you were about to do, and why now>
- Evidence read: <files and the exact fields, e.g. runs/m9_g3/s<k>/session/rule.json outcome/D/R; logs/m9_g3_s<k>_run/verify_run.json ok>
- Registered rule applied: <rule id + first 16 hex of its digest; the clause that fired>
- Decision: <one sentence>
- Alternatives considered: <...>
- Consequence under m9_g3_line_rule_v1: <from line_consequence / section 5.4>
- Deviations from the runbook: <none | what and why>
- Follow-ups: <...>
- Commit: <hash, once committed>
```

---

## Appendix A. Command ledger

| command | checked how |
| --- | --- |
| `rl/m9_g3_session.py {status, preflight [--skip-unit], approval-template, run, verify-run, report} --session K` | [help] for every subcommand; [code] `main`, `preflight`, `cmd_run`, `cmd_verify_run`; `status --session 3` [ran] |
| `rl/m9_g3_snapshot.py {snapshot, verify, powershell} --dest D --session K [--out F]` | [help]; [code] `cmd_snapshot`, `m8_rd_snapshot.cmd_verify` / `powershell_script` |
| `rl/tools/runs_backup.py {backup, verify, check-coverage} --source S --dest D [--workers N]` | [help]; [code] (default `--source` = `runs/`; `--dest` required; refuses the same volume; `backup` refuses while BattleShip runs) |
| `logs/m9_g3_resume_tools/write_approval.py`, `wait_session.py`, `three_passes.py` | [help]; [code] |
| `logs/m9_g3_resume_tools/launch_detached.ps1 -Session K [-Repo R]` | [code] (not run: it launches) |
| `logs/m9_g3_prep/tools/independent_increment_check.ps1 -Source S -Dest D` from Git Bash | [ran] rd2: `checked=62 ... result=PASS` in 3 s |
| `rl/m9_g3_rule.py self-test` | [ran] PASS |
| `rl/m9_tests.py unit`, `rl/m9_g2_tests.py unit`, `rl/m9_eval_tests.py unit`, `rl/m9_g3_tests.py unit/e2e` | [code] `main` of each; expected counts [record]; not run here |
| fingerprint, B2 digests, readiness, `game_processes`, coverage, `line_consequence`, `unregistered_predecessors`, `predecessor_tree` one-liners | [ran] |
| `trees_state(K)` one-liner | [code] only (not run: it hashes about 2.9 GB) |
| preflight, verify-run, rule and line readers | [ran] on existing outputs |
| S17 copy commands | **UNVERIFIED** (no tool) |
| `git` commands | standard; `ls-remote`, `rev-parse`, `status`, `log --stat` [ran] |

## Appendix B. Protected trees and increments (session 3 protects these nine) [ran: `trees_for(3)`]

| name | tree | increment under `D:\BattleShip_runs_backup\` | files | bytes |
| --- | --- | --- | ---: | ---: |
| rd1 | `runs/m8_rd` | `2026-10-02_incr_m8_rd1` | 166 | 62,448,635 |
| rd2 | `runs/m8_rd_rd2` | `2026-10-02_incr_m8_rd2` | 62 | 66,759,098 |
| rd3 | `runs/m8_rd_rd3` | `2026-10-02_incr_m8_rd3` | 77 | 114,026,700 |
| rd4 | `runs/m8_rd_rd4` | `2026-10-03_incr_m8_rd4` | 93 | 165,147,441 |
| m9_g1 | `runs/m9_g1` | `2026-10-04_incr_m9_g1` | 2,740 | 354,131,925 |
| m9_g1_eval | `runs/m9_g1_eval` | `2026-10-04_incr_m9_g1_eval` | 1,393 | 162,003,001 |
| m9_g2_s1 | `runs/m9_g2/s1` | `2026-10-06_incr_m9_g2_s1` | 9,779 | 988,807,605 |
| m9_g3_s1 | `runs/m9_g3/s1` | `2026-10-07_incr_m9_g3_s1` | 4,935 | 508,166,787 |
| m9_g3_s2 | `runs/m9_g3/s2` | `2026-10-08_incr_m9_g3_s2` | 4,478 | 477,564,684 |

Independent re-hash of all of them, one after another (each call is the [ran] form; the loop itself was not run):

```bash
while read -r src inc; do printf '%s: ' "$src"; powershell -NoProfile -ExecutionPolicy Bypass -File logs/m9_g3_prep/tools/independent_increment_check.ps1 -Source "$src" -Dest "D:/BattleShip_runs_backup/$inc"; done <<'EOF'
runs/m8_rd 2026-10-02_incr_m8_rd1
runs/m8_rd_rd2 2026-10-02_incr_m8_rd2
runs/m8_rd_rd3 2026-10-02_incr_m8_rd3
runs/m8_rd_rd4 2026-10-03_incr_m8_rd4
runs/m9_g1 2026-10-04_incr_m9_g1
runs/m9_g1_eval 2026-10-04_incr_m9_g1_eval
runs/m9_g2/s1 2026-10-06_incr_m9_g2_s1
runs/m9_g3/s1 2026-10-07_incr_m9_g3_s1
runs/m9_g3/s2 2026-10-08_incr_m9_g3_s2
EOF
```

After session k is backed up, add its line (`runs/m9_g3/s<k> <date>_incr_m9_g3_s<k>`).

## Appendix C. Every UNVERIFIED item

1. Windows PowerShell 5.1's `>` encoding (BOM or UTF-16) on this machine; the runbook avoids it by using Git Bash.
2. The S10 authorisation wording (a suggestion; the tool quotes whatever you write).
3. The S17 copy commands into `launch/` and `derived/` (no tool; layout from the s2 results record section 8).
4. Whether closing the terminal that ran the launcher affects the detached session (S15).
5. The Windows sleep settings path, and the effect of sleep on a running session (section 4).
6. Task Manager's UI labels (section 4; the PowerShell command was run).
7. Model tiers and costs (section 7).
8. Durations other than the recorded ones (the S7 dry run "several minutes").
9. Launching `launch_detached.ps1` from Git Bash (S14): the form is checked only through `independent_increment_check.ps1`.
