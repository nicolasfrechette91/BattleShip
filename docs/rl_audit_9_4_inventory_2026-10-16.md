# Audit item 9.4 inventory: decomp edits outside PORT guards in `e4bc8e24c` (2026-10-16)

Status: COMPLETE. Offline review only: zero native ticks, no build, no compile, no code edited, nothing run. Inventory only; no fix is designed here.

## 0. Scope, state and method

- Parent checkout: `C:/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip`, branch `main`, HEAD `c2308a4` ("Add the first route-insight report"), tree clean, `main...origin/main` in sync. No `C:/BattleShip_lab/lab.lock`; no BattleShip or Python process.
- Decomp submodule: `decomp/`, branch `rl-main` = `origin/rl-main`, HEAD `e4f06348b` ("add mechanics-aware Mario BTT observation v4"), clean; the parent's gitlink points at the same commit. Remotes: `origin` (nicolasfrechette91/ssb-decomp-re), `canonical` (VetriTheRetri/ssb-decomp-re, the matching decomp), `port-upstream` (JRickey/ssb-decomp-re). `rl-main` forked from `port-upstream/port-patches` at `1c44aecbc` (2026-09-04), which is the parent of `e4bc8e24c`.
- The flagged commit: decomp `e4bc8e24c807483f5a3caea371057cde2b821628`, 2026-09-15, "setup mario btt to be automated. It uses the provided TAS and it's able to reproduce it every single time." Three files (numstat): `src/sc/sc1pmode/sc1pbonusstage.c` (+45 / -1), `src/sys/netreplay.c` (+139 / -4), `src/sys/netreplay.h` (+3 / -0). The commit is not in the parent repository's history; the parent only moved its submodule pointer from `1c44aecbc` to `e4bc8e24c` in parent commit `7f3eda8` (2026-09-15, "Add automated Mario BTT episode runner").
- Guard forms treated as PORT-only (the line is compiled only when `PORT` is defined): `#ifdef PORT`; `#if defined(PORT)`; `#if defined(PORT) && ...`; `#elif defined(PORT)`; the `#else` branch of `#ifndef PORT`. Treated as NOT PORT-only: the true branch of `#ifndef PORT` (N64-only, the preferred exclusion pattern); `#if defined(REGION_US) || defined(PORT)`; `#if defined(AVOID_UB) || defined(PORT)`; macros that merely contain the word (`PORT_DIAG_HAVE_ASAN`, `PORT_STAGE_CYCLE_DEMO`). Repo-wide counts (for information only): 1,881 `#ifdef PORT`, 23 `#ifndef PORT`, 12 `#if defined(PORT) && !defined(_WIN32)`, 3 `#if defined(PORT)`, 1 `#elif defined(PORT)`. In the three files inventoried here only `#ifdef PORT` / `#else` / `#endif` and three `#if defined(REGION_US)` blocks occur; the `REGION_US` blocks are untouched by the commit. The PC build defines `PORT=1` together with `NON_MATCHING=1`, `NON_EQUIVALENT=1` and `AVOID_UB=1` (`CMakeLists.txt:607-610`).
- Method: `git show e4bc8e24c`; a per-line preprocessor-stack pass over the HEAD text of each file giving each line a state (PORT-only, N64-only, both, directive); joined with `git blame e4bc8e24c^..HEAD` to attribute every line to the commit that last wrote it; `git log e4bc8e24c..HEAD -- <file>` for the later commits; their deleted lines read from `git show`. "Outside PORT guards" below means: compiled when `PORT` is undefined. All line numbers are at decomp HEAD `e4f06348b`.
- Reading restriction honoured: `docs/project_handoff.md`, audit Area 9 (item 9.4 and the rows it points to: 9.3, 9.7, 9.8), the commit and the logs of its three files. For item 4 only, `decomp/CLAUDE.md` and the upstream Makefile (read from the local git objects of `canonical/main`, nothing fetched) were consulted. No RNG-related code is touched by any hunk below; no random-number routine appears in the diff.

## 1. Hunks of `e4bc8e24c` that change decomp source outside PORT guards

| ID | File | Function / object | Lines at HEAD | What it changes (one line) |
|---|---|---|---|---|
| A | `src/sc/sc1pmode/sc1pbonusstage.c` | file scope, include list | 13-14 | Adds `#include <sys/netinput.h>` and `#include <sys/netreplay.h>` (two port-added headers holding declarations only). |
| B | `src/sc/sc1pmode/sc1pbonusstage.c` | new function `sc1PBonusStageFuncReadReplay` | 62-102; unguarded parts: comment 62-70, signature 71, `{` 72, `syControllerFuncRead();` 101, `}` 102; body 73-100 is inside `#ifdef PORT` | Defines a new controller-read wrapper; with `PORT` undefined it is a function that only calls `syControllerFuncRead()`. |
| C | `src/sc/sc1pmode/sc1pbonusstage.c` | `dSC1PBonusStageTaskmanSetup` (the `SYTaskmanSetup` initialiser) | 381 | Replaces the controller I/O callback pointer `syControllerFuncRead` with `sc1PBonusStageFuncReadReplay`. |
| D | `src/sys/netreplay.c` | file-scope globals | 35, 44 | Adds `const char *sSYNetReplayBTTInputPath` and `sb32 sSYNetReplayIsBTTTextPlayback`. |
| E | `src/sys/netreplay.c` | new function `syNetReplayIsBTTPlaybackConfigured` | 212-215 | Returns the BTT text-playback flag; the whole body is unguarded. |
| F | `src/sys/netreplay.c` | new function `syNetReplayStartBTTSession` | 217-307; unguarded: signature 217, `{` 218, `}` 307; body 219-306 is `#ifdef PORT ... #else (void)battle_state; #endif` | Loads the `.btti` rows and arms replay; with `PORT` undefined it is an empty function. |
| G | `src/sys/netreplay.c` | new function `syNetReplayFinishBTTSession` | 338-363; unguarded: 338-349 and 360-363; only the log at 350-359 is guarded | Resets every slot source to Local and clears the playback flags; with `PORT` undefined the whole logic remains. |
| H | `src/sys/netreplay.h` | declarations | 12-14 | Adds three `extern` prototypes (`syNetReplayStartBTTSession`, `syNetReplayFinishBTTSession`, `syNetReplayIsBTTPlaybackConfigured`). |

Count: 8 hunks outside PORT guards (3 in `sc1pbonusstage.c`, 4 in `netreplay.c`, 1 in `netreplay.h`).

The commit's other 7 hunks are fully inside PORT guards and are listed only so the inventory is complete (the `#ifdef PORT` / `#endif` directive lines themselves are new text outside guards but emit nothing):

| File | Lines at HEAD | Content |
|---|---|---|
| `sc1pbonusstage.c` | 20-21 (block now 20-60) | `extern void port_log(...)`; later commits grew the block into the rl.h constant checks. |
| `sc1pbonusstage.c` | 449-451 | `syNetReplayUpdate()` call in `sc1PBonusStageFuncUpdate`. |
| `sc1pbonusstage.c` | 1327-1333 | "COMPLETE" log in `sc1PBonusStageUpdateTargetCount` when the target count reaches 0. |
| `sc1pbonusstage.c` | 1895-1908 | `syNetReplayStartBTTSession` in `sc1PBonusStageFuncStart`, armed on Mario's bonus map only (audit 9.5). |
| `sc1pbonusstage.c` | 2092-2094 | `syNetReplayFinishBTTSession` in `sc1PBonusStageStartScene`. |
| `netreplay.c` | 180, 192-199 | `syNetReplayInitDebugEnv`: reads `SSB64_BTT_INPUT` and skips the VS replay load; the whole function body (175-209) is one `#ifdef PORT` block. |
| `netreplay.c` | 428-438 | `syNetReplayUpdate`: the verify log split into a BTT branch; inside the existing `#ifdef PORT` 427-439. |

## 2. Per hunk: later commits, non-PORT build output, PORT dependence

| ID | Later commits on the same lines | Would alter non-PORT build output? | PORT behaviour depends on it? |
|---|---|---|---|
| A | None; blame at HEAD is still `e4bc8e24c` for 13-14. | No, with a caveat. Both headers hold only an include guard, type and enum declarations and `extern` prototypes (checked: no object definition, no `inline`, no `static`), so the include emits no code or data. Caveat: both headers are port-added (first commit `f74646d59`, 2026-05-03; absent from `canonical/main`), so the upstream matching tree cannot include them at all; whether an N64 compile of this tree would resolve `<sys/netinput.h>` depends on the restored build's include paths. | Yes. The PORT blocks at 73-100, 449-451, 1327-1333, 1895-1908 and 2092-2094 call `syNetReplay*` / `syNetInput*` functions declared only there. |
| B | `91d7b6b75` (2026-09-20) rewrote the comment 64-70 and the guarded body 74-99 (added the interactive-stepping branch 83-98). The unguarded code lines 71-72 and 101-102 are unchanged. | Yes. A new non-static function (a call and a return) is compiled into the file's text section, adding a symbol and shifting every function placed after it in the object; the ROM would differ even though behaviour is the same. Reasoned from the text, not measured (section 4). | Yes. Every replay row and every RL action enters through this callback (audit 9.3): replay branch 78-82, M1c stepping branch 83-98. |
| C | None. | Yes. An initialised data value changes from the address of `syControllerFuncRead` to the address of the new function. | Yes. It is the only thing that routes the taskman's controller read into the wrapper. |
| D | `91d7b6b75` added a third global at 45 (`sSYNetReplayIsBTTInteractive`); not the same lines. | Not applicable, so unclear. `netreplay.c` is a port-added file absent from the upstream matching tree. If the upstream Makefile were restored on this tree, its source rule (`C_FILES := $(shell find src -type f \| grep \.c$)`, Makefile lines 150 and 158, with filter-outs that cannot name a file upstream never had) would compile the file and the ROM would already differ because the file exists (`f74646d59`), independent of this hunk. | Yes (the configured path and the playback flag). |
| E | None. | Not applicable, as D. | Yes (both branches of the controller callback, `FuncStart`, `UpdateTargetCount`). |
| F | None. | Not applicable, as D. | Yes (arms replay). |
| G | `91d7b6b75` changed 342 (early-return condition now also tests the interactive flag), 351-358 (log split) and 360-362 (flag resets); it deleted the commit's unguarded lines `if (sSYNetReplayIsBTTTextPlayback == FALSE)`, `sSYNetReplayIsBTTTextPlayback = FALSE;` and `sSYNetReplayIsPlaybackActive = FALSE;`. | Not applicable, as D. | Yes (ends the replay or stepping session at scene start). |
| H | `91d7b6b75` added 15-16 (two more prototypes); 12-14 unchanged. | Not applicable, as D (header of a port-added file). | Yes. |

Summary of the "alters non-PORT output" column: yes 2 (B, C); no 1 (A, with the caveat); unclear 5 (D-H, all in the port-added `netreplay.c` / `.h`, where the question has no referent in the matching tree). Nothing in this checkout can produce a non-PORT build (section 4), so every verdict is reasoned from the C text and the upstream build rules, not measured.

## 3. Other decomp edits outside PORT guards in the same files since `e4bc8e24c` (list only)

Source: every non-blank line of the three files that blame attributes to a commit after `e4bc8e24c` and that is not PORT-only, plus the deleted lines of each later commit. Later commits on these files: `91d7b6b75` (2026-09-20), `54c5afc78` (2026-09-23), `3c7fd5d05` (2026-09-23), `3834e227a` (2026-09-27), `e4f06348b` (2026-09-28); all by nicolasfrechette91.

- `91d7b6b75` "feat(port): add interactive BTT input stepping":
  - `sc1pbonusstage.c` 64-70: comment text inside the unguarded comment block of hunk B (one comment line replaced by seven). Comment only, no output effect.
  - `netreplay.c` 45: new unguarded global `sb32 sSYNetReplayIsBTTInteractive`.
  - `netreplay.c` 309-315 and 331: new function `syNetReplayStartBTTInteractiveSession`, unguarded comment, signature and braces (body 316-330 guarded).
  - `netreplay.c` 333-336: new function `syNetReplayIsBTTInteractiveSession`, wholly unguarded.
  - `netreplay.c` 342, 360-362: modified unguarded lines of hunk G (see section 2).
  - `netreplay.h` 15-16: two unguarded prototypes.
- `54c5afc78`, `3c7fd5d05`, `3834e227a`, `e4f06348b`: every added line is inside a `#ifdef PORT` block (chiefly the block 587-1238 opened by `54c5afc78`); the only new unguarded text is the directive pair at 587 and 1238. The three lines deleted by `3c7fd5d05` were inside that block. No unguarded code change.
- Not covered, by instruction: the rest of the decomp, and lines of these files written before `e4bc8e24c` (for example `f74646d59`'s original port edits, such as `sc1pbonusstage.c` 2-4).

## 4. How this repository verifies non-PORT byte-matching

- In this checkout: no check exists, and none can be run. The decomp tree on `rl-main` holds only `CLAUDE.md`, `include/`, `src/`, `tools/` (41 reloc and asset scripts) and `relocData.md`. Commit `0583cc8df` (2026-05-03, JRickey, "Trim port-patches: drop matching infra, keep only what the port consumes", 342 files removed, an ancestor of `e4bc8e24c` by 121 commits) deleted the `Makefile`, `smashbrothers.us.yaml`, `smashbrothers.jp.yaml`, `symbols/`, `diff.py`, `first_diff.py`, `livediff.sh`, `mips_to_c.sh`, `diff_settings.py`, `permuter_settings.toml`, `decomp.yaml`, the progress reports, `src/entry.s`, `src/db`, `src/ovl8`, `src/audio`, `src/particles`, most of `src/libultra`, 130 of 133 `tools/*` files and the nested `splat`, `asm-processor` and `asm-differ` submodules. No ROM can be built from this tree, so byte-matching has not been checkable on this branch since 2026-05-03. The audit's "probably no longer matches" therefore describes a hypothetical build on the upstream infrastructure.
- `decomp/CLAUDE.md` still documents `make`, `make validate`, `diff.py`, `first_diff.py`, `livediff.sh` and `tools/m2ctx.py`; none of those files exist on `rl-main` (stale with respect to the tree).
- Upstream (`canonical/main`, objects present locally; nothing fetched or run): the Makefile's `rom` target (the default, `all: rom`) ends with `cmp $(ROM) $(BASEROM)` and prints OK or FAILURE (Makefile lines 524-528); `nolink` runs `tools/compareObjects.py` (532); `diff` runs `tools/matchbin.py` (535); `verify-reloc` runs `tools/verifyAutoReloc.py`, the reloc-chain byte-compare (1140-1144). `validate` appears only in `.PHONY` (1186); no `validate:` rule is defined, so the `make validate` line in `decomp/CLAUDE.md` names a target that does not exist even upstream. The check needs `baserom.us.z64` (a copy sits in the parent root; not inspected) and the IDO 7.1 toolchain. Upstream CI has one workflow, `.github/workflows/report-progress.yml` (a progress report, not a matching gate; its steps were not studied).
- Parent repository, PORT side only (not N64 matching): `tools/compare_obj_text.sh` and `tools/audit_text_diffs.sh` compare per-translation-unit `.text` bytes between two `ssb64_game` builds and classify differences as LINE_ONLY or STRUCTURAL; they were written against a Mach-O `__TEXT,__text` layout. The November decision in the handoff is a different check: the PORT executable hash must stay `30a3913b...` after the fix (archived in `D:/BattleShip_exe_archive/2026-10-13_30a3913b/`; the exact build commit is not recorded there).

## 5. Open questions for the November fix session

1. What is the reference text for "non-PORT unchanged": the pre-`e4bc8e24c` state of the three files (`1c44aecbc`), or upstream `canonical/main` (where `sc1pbonusstage.c` exists but `netreplay.*` and `netinput.*` do not)?
2. With the matching infrastructure gone since `0583cc8df`, is the rule to be checked as "non-PORT text of upstream files is byte-identical to upstream after stripping PORT blocks" (a git-level check with no ROM), rather than as a ROM comparison?
3. Hunk C: is a `#ifdef PORT` / `#else` / `#endif` pair inside the brace initialiser of `dSC1PBonusStageTaskmanSetup` acceptable, or should the pointer be patched at runtime from the PORT side (a port-side adapter, the preferred pattern in `CLAUDE.md`)?
4. Hunk B: once C is guarded the function is unreferenced outside PORT; wrap the whole definition in `#ifdef PORT` (as `unref_800036B4` is excluded with `#ifndef PORT`) or keep an N64 stub?
5. Hunk A: guard the two includes as well (port-added headers), or leave them since they emit nothing; which does the chosen check in question 2 require?
6. Are the port-added files `netreplay.c`, `netreplay.h`, `netinput.c`, `netinput.h` in scope of the non-PORT rule at all (they only exist in PORT builds; audit 9.7 already treats them as port files), or should they be documented as port files and left alone?
7. How will the PORT executable be proven unchanged: a rebuild compared by SHA-256 against `30a3913b...` (needs the same toolchain and the unrecorded build commit) or per-TU `.text` comparison with `tools/compare_obj_text.sh` (does it run on Windows MSVC objects)?
8. Does the fix also cover the `91d7b6b75` additions listed in section 3 (the interactive-session globals and functions, the extended hunk G), since they are the same wrapper?
9. Does the fix change line numbers in `sc1pbonusstage.c` in a way that touches any `__LINE__`-dependent PORT call sites, which would make a `.text` comparison report LINE_ONLY differences?
10. Should `decomp/CLAUDE.md` on `rl-main` be corrected (it names `make validate` and tools that no longer exist), or left as upstream text?
11. After the fix, which native verification is authorised: the 468-row scripted baseline (7.43 s) and the M1e fresh-process replay regression, or only the executable hash?
12. Should the `0583cc8df` trim be recorded in `docs/architecture.md` or `docs/build_and_tooling.md`, so the next audit does not again infer a ROM check that this branch cannot run?
