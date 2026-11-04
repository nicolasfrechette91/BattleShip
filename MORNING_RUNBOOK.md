# Morning runbook, 2026-11-04 (companion to REVIEW_2026-11-03.md)

Run these in order. Each step says what it touches and what to expect.

- **Parts A and B are zero native ticks:** git, compilers and Python unit tests only.
- **Part C boots the game.** Each step there needs your explicit go and the usual pre-launch list: the handoff's "Before a launch"
  and `docs/frs_lab_guide.md` §1.

The cloud session ran **nothing** native. Every "expected" below is either measured in the cloud (marked) or what the code implies.

Paths assume the handoff's checkout, `C:/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip`. The review branch goes in a sibling
worktree, `BattleShip-cloud-2026-11-03`. It has no submodules of its own; the tools borrow the main checkout's `decomp/` and
`libultraship/`.

Time: A about 2 min, B about 10 min, C about 10 min.

## A. Get the branch (Git Bash)

**A1.** In the main checkout:

```bash
cd /c/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip
```

```bash
git fetch origin cloud/2026-11-03
```

```bash
git diff --name-status origin/main...origin/cloud/2026-11-03
```

Expected: exactly these lines, all `A` (added). Nothing else on the branch touches a tracked file.

```
A	MORNING_RUNBOOK.md
A	REVIEW_2026-11-03.md
A	tools/audit/build_trig_check.sh
A	tools/audit/tick0_frame_probe.py
A	tools/audit/trig_ulp_check.c
A	tools/audit/uninit_scan.sh
```

**A2.** No CR bytes in the new files:

```bash
git grep -I -n $'\r' origin/cloud/2026-11-03 -- REVIEW_2026-11-03.md MORNING_RUNBOOK.md tools/audit
```

Expected: no output (exit code 1).

**A3.** A worktree with LF line endings, per the handoff's line-ending rule:

```bash
git -c core.autocrlf=false worktree add ../BattleShip-cloud-2026-11-03 origin/cloud/2026-11-03
```

Expected: `Preparing worktree (detached HEAD …)` and `HEAD is now at …`.

**A4.** The submodule pins the tools will borrow:

```bash
git -C decomp rev-parse HEAD
```

```bash
git -C libultraship rev-parse HEAD
```

Expected: `e4f06348bfa2c20947f2c64155f4b656977948d6` and `805f195041573230cf0402171337b22ffd558759` (the pins at `9afcaf6`). If
they differ, note it. The trig check depends only on `decomp/src/libultra/gu/sinf.c` and `cosf.c`.

## B. Offline audit (zero native ticks)

**B1. Decides finding D1: ucrt trig against libultra trig.** Open **x64 Native Tools Command Prompt for VS**; x64 matters for B2.
These `cl` lines were not compiled in the cloud (there is no MSVC there).

```bat
cd /d C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip-cloud-2026-11-03
```

```bat
mkdir build-audit\msvc
```

```bat
set D=..\BattleShip\decomp
```

```bat
cl /nologo /O2 /fp:precise /c /D_LANGUAGE_C /DF3DEX_GBI_2=1 /DPORT=1 /DNON_MATCHING=1 /DNON_EQUIVALENT=1 /DAVOID_UB=1 /I%D%\include /I%D%\src /Fobuild-audit\msvc\ %D%\src\libultra\gu\sinf.c %D%\src\libultra\gu\cosf.c
```

```bat
cl /nologo /O2 /fp:precise /Fobuild-audit\msvc\ /Febuild-audit\msvc\trig_ulp_check.exe tools\audit\trig_ulp_check.c build-audit\msvc\sinf.obj build-audit\msvc\cosf.obj
```

```bat
build-audit\msvc\trig_ulp_check.exe > build-audit\msvc\trig_msvc.txt
```

```bat
type build-audit\msvc\trig_msvc.txt
```

Expected:

- The first `cl` may warn `C4068: unknown pragma 'weak'` for the two decomp files. That warning is the whole point: MSVC drops the
  aliases.
- No errors. The run takes about 10 s and prints eight lines (sinf, then cosf, for four ranges).

How to read the **`vs_host`** column (ucrt against libultra; this is what `BattleShip.exe` computes differently from the N64):

- **0 % on all eight lines:** D1 is closed for Windows. Decision O3: close it.
- **About 1 % or more:** D1 is confirmed. Decide O3 before building run 3.
- **The `vs_cr` column** should be close to the review's table. It also depends on ucrt's double `sin`/`cos`, so small differences
  are fine.

If the decomp files fail to compile, copy the first error. That itself is a finding about the MSVC build of those two files.

**B2. Whether ucrt's result depends on the CPU (FMA3).** Same prompt:

```bat
cl /nologo /O2 /fp:precise /DTRIG_FMA3_TOGGLE /Fobuild-audit\msvc\ /Febuild-audit\msvc\trig_fma3.exe tools\audit\trig_ulp_check.c build-audit\msvc\sinf.obj build-audit\msvc\cosf.obj
```

```bat
build-audit\msvc\trig_fma3.exe 0.5 3.14159274
```

Expected: the two usual lines plus `fma3 [0.5, 3.14159274) floats=21565403  host sinf FMA3-on vs off: X  host cosf: Y`.

- **X = Y = 0:** no CPU dependence. On a CPU without FMA3 both paths are the same, so 0 is trivially true there.
- **Non-zero:** the same executable can compute differently on another PC. Option (b) of O3 would then need `_set_FMA3_enable(0)`.
- If `cl` rejects `_set_FMA3_enable`, skip B2 and note it. The default build in B1 doesn't use it.

**B3. Reproduce the cloud's table (WSL or any Linux with gcc and binutils).**

```bash
wsl
```

Inside WSL (run `sudo apt install build-essential clang` first if gcc, objcopy or clang is missing):

```bash
cd /mnt/c/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip-cloud-2026-11-03
```

```bash
DECOMP_DIR=../BattleShip/decomp tools/audit/build_trig_check.sh
```

```bash
build-audit/trig_ulp_check
```

Expected [measured in the cloud with GCC 13 and Clang 18, identical results]:

- `built …/build-audit/trig_ulp_check`, then eight lines.
- The `vs_cr` percentages, in order: `0.5696%`, `4.2508%`, `5.1666%`, `4.6013%`, `4.7077%`, `5.1125%`, `4.9381%`, `4.9122%`.
- `>1ulp 0` everywhere.
- The `vs_host` (glibc) column may move slightly with another glibc version.

If bash complains about `$'\r'`, the worktree was checked out with CRLF; redo A3 with `-c core.autocrlf=false`.

**B4. Uninitialised-use scan (still in WSL).**

```bash
DECOMP_DIR=../BattleShip/decomp LUS_DIR=../BattleShip/libultraship tools/audit/uninit_scan.sh
```

Expected [measured in the cloud with clang 18.1.3]: `files=171 compile_failures=0 candidates=72 -> …/build-audit/uninit_scan.txt`.
Another clang version may report a few more or fewer candidates. The triage of the Mario-path hits is in review D7.

Leave WSL and shut it down before anything native (handoff rule):

```bash
exit
```

```powershell
wsl --shutdown
```

**B5. Existing zero-tick suite (Git Bash, main checkout).**

```bash
cd /c/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip
```

```bash
python -B tools/frs/crossing_search_run2_tests.py
```

Expected: `crossing search run 2 tests: 5/5 passed`, as recorded in `docs/frs_crossing_search_run2_2026-10-15.md`. In the cloud it
was 3/5: `real_resume_on_run1_archive` needs `C:/BattleShip_lab/import`, and `stub_end_to_end` needs `gymnasium`, and both exist only
on the PC. This confirms the branch changed nothing the suites see.

## C. Native checks (each one needs your go)

Before C1, run the pre-launch list and check that no BattleShip process runs:

```bash
tasklist | grep -ci battleship
```

Expected: `0`.

**C1. Lab self-check, the health baseline** (about a minute; boots fresh game processes; writes under `C:/BattleShip_lab/selfcheck/`):

```bash
python -B rl/frs_lab.py selfcheck --lab-root C:/BattleShip_lab
```

Expected: the last line is **PASS** (`docs/frs_lab_guide.md` §2).

**C2. Does every boot fire the update check?** (Throughput item 6 and decision O11.) While C1 runs, in a second window
(PowerShell):

```powershell
$end=(Get-Date).AddMinutes(3); while((Get-Date) -lt $end){ Get-CimInstance Win32_Process -Filter "Name='curl.exe'" | Where-Object { $_.CommandLine -match 'BattleShip-Updater' } | Select-Object ProcessId,ParentProcessId,CommandLine; Start-Sleep -Milliseconds 250 }
```

Expected, one of two:

- Rows with `BattleShip-Updater` in the command line: each game boot spawns curl, so with five workers that is a spawn every few
  seconds. O11's update-check half is worth doing.
- No rows: the check doesn't fire in RL mode. Close that half.

**C3. Frame count before tick 0** (finding D9; ten fresh boots, about 1 min; writes only under `--out`). Run it only while no lab
run is active.

```bash
cd /c/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip-cloud-2026-11-03
```

```bash
python -B tools/audit/tick0_frame_probe.py --exe C:/BattleShip_lab/import/exe/BattleShip.exe --out C:/BattleShip_lab/probes/tick0_frames_2026-11-04 --boots 10
```

Expected:

- Ten JSON lines, then a summary with `"constant": true` and `"all_input_tick_0": true`, and exit code 0. The tool was tested end
  to end in the cloud against the repo's fake game.
- If `"constant": false` (exit 1): the boot path depends on timing. Do not start run 3 until it is understood. Record the values
  from `summary.json`.

## D. Decisions after A to C (review section 4)

| result | decision it feeds |
| --- | --- |
| B1 `vs_host` 0 % / ≥ 1 % | O3: close D1, or choose (a) libultra trig on MSVC or (b) pin the platform, **before** run 3 inherits run 2's archive |
| B2 X, Y | O3 option (b) needs `_set_FMA3_enable(0)` if non-zero |
| C2 rows / none | O11, update-check half |
| C3 constant / not | D9: proceed, or investigate the boot path first |
| none of the above | O1, O2, O4 to O10, O12 can be decided from the review alone |

## E. Clean up

```bash
cd /c/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip
```

```bash
git worktree remove ../BattleShip-cloud-2026-11-03
```

If git refuses because of the untracked `build-audit/` folder, delete that folder in the worktree first, then repeat. The lab
probe output under `C:/BattleShip_lab/probes/` is lab evidence: back it up with the next lab backup (handoff lesson).
