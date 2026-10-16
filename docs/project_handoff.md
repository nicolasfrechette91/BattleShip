# BattleShip project handoff (as of 2026-10-16)

One living file, updated by hand. Figures last checked on 2026-10-16; lab results are taken from their records.
Items that are my own plans or preferences are not in any record.

## Goal and how I work
- Build a genuine learning agent for Super Smash Bros. 64's Break the Targets on the PC port, for a YouTube video: clear Mario's stage from tick 0, improve toward the 7.43 s TAS, then other characters.
- Claude Code sessions run locally on Windows; the ROM/assets exist only on my PC. Cloud sessions are read-only review/design only, and must NEVER be started from the PC's terminal (a "cloud" review started locally ran a preflight on 2026-10-11).
- When I ask what to send a session, I want the full copyable prompt. I review alongside decisions: options, recommendation and why. Preparation and launch separate when new or risky.
- Models: Fable 5.1 (or Opus 5.5) for design, hard preparation and reviews; Sonnet 5.5 High for scoped execution and launches.
- Friday 2026-10-16 is my last working day until November; I resume with Claude in November.
- Key records: this document, the runbook (`docs/rl_runbook.md`), `docs/rl_by_hand_session_checklist.md`, the decisions records (`docs/rl_decisions_2026-10-13.md`, superseded in part by `docs/rl_decisions_2026-10-14.md`, whose build order is superseded by `docs/rl_decisions_2026-10-16.md`), the generalization audit (`docs/rl_generalization_audit_2026-10-13.md`), and the fast-route records: the proposal (`docs/rl_m8_fast_route_proposal_2026-10-13.md`), its review (`docs/rl_m8_fast_route_proposal_review_2026-10-14.md`), the splice probe (`docs/frs_splice_probe_2026-10-14.md`), the prefix-cost study (`docs/frs_prefix_cost_2026-10-14.md`), the crossing study (`docs/frs_crossing_2026-10-14.md`), the trail-lead probe (`docs/frs_trail_probe_2026-10-14.md`), the frontier search (`docs/frs_frontier_2026-10-14.md`), crossing search runs 1 and 2 (`docs/frs_crossing_search_2026-10-15.md`, `docs/frs_crossing_search_run2_2026-10-15.md`) and the strategy review (`docs/frs_strategy_2026-10-16.md`). Lab evidence backup: D:/BattleShip_lab_backup/2026-10-16/ (README.txt there).

## Repository and evidence
- Repo: https://github.com/nicolasfrechette91/BattleShip; local checkout C:/Users/kill_/Bureau/gitRepo/Smash_pc_port/BattleShip.
- runs/ and logs/ are git-ignored (`.gitignore`). Evidence is backed up to D:/BattleShip_runs_backup/<date>_incr_<name> (tool backup and verify with the correct --source, plus an independent re-hash). Source snapshots in D:/BattleShip_source_snapshots/<date>_<name>. The 2026-09-28 folder is the base backup of all of runs/ (377,359 files; independently re-hashed 2026-10-13, 0 mismatches; `docs/rl_m8_sd2_review_2026-10-13.md` section 1).
- Three folders under D:/BattleShip_runs_backup are not increments and are skipped by the checks: `2026-09-29_incr_m7t_logs` and `2026-09-30_incr_m7u_logs` (no verification record) and `2026-10-01_m7u3_prep` (not under runs/) (`docs/rl_m8_sd2_results_2026-10-12.md` section 11).
- Coverage after sd2: 446,809 files, 0 uncovered, 20 increments (`docs/rl_m8_sd2_results_2026-10-12.md` section 11).
- Sessions never commit, push or branch. I commit by hand with plain-language messages.
- Some launch tools live only under the Git-ignored `logs/` folder on this PC: the g3 tools in `logs/m9_g3_resume_tools/` and the independent re-hash script `logs/m9_g3_prep/tools/independent_increment_check.ps1`. The M8 speed-discovery tools are tracked (`tools/m8_sd1/`, `tools/m8_sd2/`).

## Absolute constraints
- No native RNG seed inspection, logging, control, comparison or hashing. Python experiment seeds are fine.
- Preserve non-PORT decomp/byte-matching behaviour. Native gameplay is authoritative.
- Process restart resets the episode. Submit action tick T, one native update, consumed_tick=T, input_tick=T+1.
- Canonical controller words are replay truth; no hidden actions. Track 1: btt_s9_b8_v1 = MultiDiscrete([9,8]).
- Human recordings and the TAS (tas_input_2/mario_743.btti) are validation-only: never demonstrations, starts, prefixes, route hints or target times. The agent's own trajectories may be used.
- No hardcoded routes or waypoints. Every selection or curriculum rule is generic and stage-agnostic. No census number in selection, claims, rules or runs.
- New native runs need my explicit authorisation. Never extend, retry or repair a frozen gate. Every registered claim is verified by exact replay from tick 0.

## Results so far (all verified by exact replay from tick 0)
| result | input ticks | about | record |
|---|---|---|---|
| rd4 route discovery: first full clear (the shorter of rd4's two verified routes; the other is 2,326) | 2,315 | 38.6 s | `docs/rl_m8_rd4_results_2026-10-03.md` |
| sd1 speed discovery | 2,086 (cid 901) | 34.8 s | `docs/rl_m8_sd1_results_2026-10-11.md` |
| sd2 speed discovery | 1,885 (cid 1360) | 31.4 s | `docs/rl_m8_sd2_results_2026-10-12.md` |
| crossing search run 1 (lab, unregistered; 298 verified clears) | 1,429 | 23.80 s | `docs/frs_crossing_search_2026-10-15.md` |
| crossing search run 2 (lab, unregistered; also verified 1,261 and 1,352) | 1,245 | 20.73 s | `docs/frs_crossing_search_run2_2026-10-15.md` |

"Input ticks" is `completion_input_tick`; the seconds are `completion_time_passed` (one less) divided by 60. Other verified sd2 clears: 1,929 (cid 1243), 1,964 (cid 1009). TAS: 7.43 s (the scripted baseline in `CLAUDE.md`, replayed by `tas_input_2/mario_743.btti`).

Lab result (exploratory, NOT registered): the splice probe of 2026-10-14 found 9 clears at 1,884 / 1,883 (31.38 s against sd2's 31.40 s), each replayed twice from tick 0 in fresh processes with identical digests. They are two separate one-tick savings while Mario falls after up-B or helpless (`docs/frs_splice_probe_2026-10-14.md`). The 1,884 clear is registered only if it becomes part of a larger improvement (`docs/rl_decisions_2026-10-14.md`).

Lab results (exploratory, NOT registered): the two crossing-search rows above. Each of their verified clears was replayed twice from tick 0 in fresh processes, both replays matching the claim; the registered best stays 1,885. The 1,245 is to be registered at the line's first checkpoint (`docs/rl_decisions_2026-10-16.md`, Q8). First checkpoint = the end of stage 1 (run 3's first night). Lab evidence is backed up and verified at D:/BattleShip_lab_backup/2026-10-16/ (1,360 files, independent re-hash, 0 mismatches; README.txt there).

## History in brief
- M7 (PPO, GCSL, quasimetric, learned-model planner): no clear; bottleneck was exploration (`docs/rl_m8_rd_proposal_2026-10-01.md`).
- M8 route discovery (Go-Explore phase 1): rd4 found the first full clear from tick 0.
- M9 robustification (backward curriculum along the agent's own route): g1 and g2 NULL. g3 sessions s1–s6: depth reached 1,694 at s5 (best registered state: s5 final, D = R = 1,694, model 382dde88…, increment 2026-10-09_incr_m9_g3_s5; `docs/rl_m9_g3_s5_results_2026-10-09.md`). s6 collapsed (clears 17→1 at 2,128); the line ENDED (END_BUDGET_1694; `docs/rl_m9_g3_s6_results_2026-10-10.md`). Stop review (docs/rl_m9_g3_stop_review_2026-10-10.md): drift into horizon-waiting; under reward v2 (gamma 0.999, 3,600-tick horizon) waiting beats attempting below ~0.2 clear probability. Settings drift ruled out; no implementation defect found.
- M8 speed discovery: sd1 PROGRESS (2,086, skipping the target-8 detour); sd2 PROGRESS (1,885, reaching level 8 at 1,776; the ending after target 8 is now a terminal-speed fall within ~1 tick of its floor). sd2 review (docs/rl_m8_sd2_review_2026-10-13.md): recommends pausing the line (it decides nothing itself); the line is paused after sd2 (my decision, 2026-10-13); odds of a same-design sd3 are 10–20 % PROGRESS.

## Code and test state (registered results)
Fingerprints recomputed on 2026-10-13 from the committed blobs at HEAD `6cb3e89`; the suite results are the latest recorded run, sd2's Part B on 2026-10-12 (`docs/rl_m8_sd2_results_2026-10-12.md` section 3).
- g3: fingerprint 15ddbb84932aa658; unit 29/29; e2e 078f46c445d8adc5; rule self-test s1 dea9965a3989bce5, line d9d82885703c016d (`docs/rl_m9_g3_progression_fix_2026-10-08.md`).
- g1 evaluation 29/29; g2 29/29; g1 unit 62/63 (known failure: identity_names_every_registered_pin).
- rd1 48/48, rd2 27/27, rd3 67/67, rd4 79/79, each e2e PASS (no registered digest).
- M8 rule self-tests (PASS, 0 problems each): rd1 e0bbfe212d3c0079…, rd2 f9779faac95feede…, rd3 fae00396494b8e96…, rd4 246813eebb7c7559…, sd1 8267341f2af80dc1…, sd2 d1220a8b2706367f….
- sd1: fingerprint f7fadda5ec11b3dd; unit 87/87; e2e 4cadf507c1c4fbc9 (`docs/rl_m8_sd1_prep_2026-10-11.md`).
- sd2: fingerprint b22c0af8f833b205; unit 101/101; e2e 2adc51de5cf46121 (`docs/rl_m8_sd2_prep_2026-10-12.md`).
- Launch tooling: tools/m8_sd2/ (tracked) is the most complete model: launcher with HEAD check, check_launch.py (exit 0 ok, 3 age-only, other = stop), copy_launch_evidence.py, post_run_checks.py, machine_sampler.py, wait_session.py. Every sd2 tool accepts only `--session sd2` (`-Session sd2` for the launcher), so any other session needs its own tool folder.

## Known defects and open items
- post_run_checks.py (sd2) treats the base backup (source = all of runs/) as an increment and reports the files added to runs/ after it (the twenty per-tree increments' 69,450 files) as missing. No data problem. Fix in a new tool for the next session (classify-and-skip plus optional base-aware check, six tests in the sd2 review).
- The M9 suites' git-state gates fail while any untracked non-M9 file exists under rl/ or docs/: commit new files before running them.
- sd1's verified_clears_of raises on sd1's own tree (inherited replay rows and header rows); sd2 uses its own reader.
- Increment names: sd1 is <date>_incr_m8_sd1, sd2 is <date>_incr_m8_rd_sd2 (the name its tool expects). Pin whichever name is real.
- The recorded session clock (`elapsed_s`) includes the close phase, but the 60-minute hard cap is checked only during open, exploration and verification, and nothing compares `elapsed_s` with the cap afterwards. Report the three capped phases and the close separately (`docs/rl_m8_sd2_review_2026-10-13.md` section 2.1).
- docs/rl_runbook.md sections §1.4, P7, P9, P14 and the S3 fingerprint were outdated (superseded by docs/rl_m9_g3_progression_fix_2026-10-08.md); they were updated in place on 2026-10-13, and the runbook gained a section 9 on the M8 speed-discovery sessions. The runbook is pinned by no session, approval or snapshot.
- Replay browser: M8 route-discovery runs (rd1–rd4) lack task metadata; plan a replay/task_overrides.json (M9+ and sd runs record the task block at the source).
- Launch paths never exercised natively: U8–U11 in `docs/rl_m8_sd2_proposal_2026-10-12.md` section 5.4 (native INVALID or INCOMPLETE, a multi-batch or inexact pool, RECORD_BELOW_MARGIN, a replayed clear whose clock differs); U1–U7 are closed by zero-tick tests. The sd1 review's T1–T6 are not in the repository (the T1–T6 of the sd2 review are a different list: the tests for the post_run_checks fix).
- Native batched-prefix operation: design starts in November week 1 (docs/rl_decisions_2026-10-16.md, Q9). Deferred: the g3 checkpoint evaluation (designed in the stop review, section 5, not run).
- Unguarded decomp edits (`docs/rl_generalization_audit_2026-10-13.md` 9.4): decomp commit `e4bc8e24c` added two includes (`sc1pbonusstage.c:13-14`) and a changed controller callback (`:381`) outside `#ifdef PORT`. Behaviour is preserved, but the N64 build probably no longer matches (not verified; needs the ROM). Decided: fix in November behind `#ifdef PORT` and check that the PORT build's executable hash is unchanged (`docs/rl_decisions_2026-10-13.md`).
- Executable archive: the registered executable `30a3913b…` and its five runtime files (BattleShip.o2r `fe2b307e…`, f3d.o2r, gamecontrollerdb.txt, BattleShip.cfg.json, imgui.ini, all from build-us/Release) are archived in D:/BattleShip_exe_archive/2026-10-13_30a3913b/ (SHA256SUMS.txt; README.txt with the HEAD and submodule pointers; the exact build commit is not recorded). Source snapshots hash the executable but do not copy it: archive before any rebuild. A runnable copy also sits in runs/m8_rd/archive/runtime/exe/ (kept by rd1 on 2026-10-02).
- Line endings: pinned `docs/*.md`, `docs/*approval.json` and `rl/data/*.json` have no eol attribute and this checkout has `core.autocrlf=true`; they are LF here, but a fresh clone or worktree would write them CRLF and break the pins (audit 8.8). Until the `.gitattributes` fix (November, with a check), clone with `core.autocrlf=false` (for example `git clone -c core.autocrlf=false …`).
- E6 disclosure (audit C1): from rd2 to sd2, the search's E6 eligibility rule pruned airborne cells using a hard-coded copy of Mario's floor table and Mario's jump heights (its docstring's claim that the floor is read natively is inaccurate). Not a route or waypoint, and no TAS or human input, but stage-specific knowledge to state in the video. Dropped for new stages. C2–C5 (the rd2/rd3 rule coordinates and census numbers, the sd1/sd2 identity samples, the rd1–rd4 milestone ladder, the M9 tick literals) stand as frozen history, with disclosure.

## Design leads for November
Order (decided 2026-10-16 in `docs/rl_decisions_2026-10-16.md`, which supersedes the build order of `docs/rl_decisions_2026-10-14.md`; that record had superseded the 2026-10-13 order "Donkey Kong first, then g4"): the crossing-search line first; Donkey Kong at a later checkpoint; g4 after it.

1. Crossing-search line (first, the main November line): the two-tier plan in `docs/rl_decisions_2026-10-16.md`, from the strategy review `docs/frs_strategy_2026-10-16.md`, whose findings are accepted (about 37 % of the 1,245 is waiting or slow movement; the agent's own data supports roughly 860 ticks with the current approach and shows nothing below about 850; the limit is how rarely the search returns to promising cells, not the inputs).
   - Tier 1: the review's stages 0 to 2. Stage 0: the run 3 tool (run 2's tool with the end record stored, a budget per (level, mask) group, a draw by arrival rank with a novelty floor, anchors whose share halves after each burst without a new earliest arrival in the group). Stage 1: run 3 from run 2's archive. Stage 2: the order-diverse right-side arm (seeds of every class, anchors per class). Stage 3 (state-aware representatives) only if stage 2 stops. Also in week 1: the offline cell-prior study and the native batched-prefix design (`docs/frs_prefix_cost_2026-10-14.md` section 4.3); no native throughput work for run 3. Claims are replayed only when faster than the best, with deduplication. Plateau: read on verified clears and on the earliest arrival per group; three nights without progress ends a line (the 2026-10-14 record also set a review on 2026-11-27).
   - Tier 2, decided at the first checkpoint: a segment-level speed optimiser (each target-to-target segment optimised from good start states toward the time to the next target, then the segments chained), with the throughput levers it depends on. My goal stays under 8 s; the current approach is not expected to reach it, which is why tier 2 exists.
   - First checkpoint = the end of stage 1 (run 3's first night).
   - The 1,245 is registered at the first checkpoint (replay, provenance and lineage, decision Q10 of `docs/rl_decisions_2026-10-14.md`), with its procedure prepared and reviewed first.
   - Earlier fast-route work, still available: the proposal `docs/rl_m8_fast_route_proposal_2026-10-13.md` and its review `docs/rl_m8_fast_route_proposal_review_2026-10-14.md`; the splice probe `docs/frs_splice_probe_2026-10-14.md` (splicing saves one tick only); PACE and the step-4 plan (`logs/frs_step4/plan.md`, Git-ignored, backed up). Lab night 1 (CONTROL against CONT) never ran and runs only if a comparison needs it. Other 2026-10-14 decisions stand: lab root C:/BattleShip_lab/, E6 dropped everywhere, three replicates per arm.
2. Other characters, revisited at a later checkpoint (decided 2026-10-16; previously the fast-route checkpoint C2): the generalization audit lists every Mario/stage-specific assumption and an "adding a character" checklist. Status: the audit ran on 2026-10-13 (`docs/rl_generalization_audit_2026-10-13.md`): mostly Python work plus one small native change; Donkey Kong is the first other character; decisions in `docs/rl_decisions_2026-10-13.md`. Donkey Kong's first search uses the plain novelty configuration, not R10 (`docs/rl_decisions_2026-10-14.md`).
3. Robust policy (g4), after Donkey Kong: change the minimum so waiting is never better than attempting (horizon as failure, per-tick cost, or shorter horizon), chosen after the offline attractor test (recompute discounted returns from recorded events, no game run). The proposal is `docs/rl_m9_g4_proposal_2026-10-13.md`; contract N1 decided (fall and horizon both −1.0). Decided 2026-10-13 (`docs/rl_decisions_2026-10-13.md`): a new line may change contract values; audit of a selected/restored policy allowed only with a pre-registered rule and fresh audit keys; warm start from s5 final with a generic frontier-setting probe; keep a rebased budget structure; probes triggered, capped at ~30 % of training wall. (The options and open questions behind this are in `docs/rl_m9_g3_stop_review_2026-10-10.md` sections 6 and 8.)

## Lessons (apply to every prompt)
- Launch sessions never modify a tracked file; records go to NEW files; nothing staged. Commit before every launch.
- Never run two local sessions that edit files or run gates at the same time. A read-only cloud review may run in parallel only if started from the web or phone, never from the PC.
- Before a launch: restart the PC, run wsl --shutdown (check with wsl --list --running), close IntelliJ, browsers (and Edge background mode), video editor and replay viewer, open ONE Claude session, disable sleep. Memory refusal = stop; sessions never close apps or lower thresholds.
- Approvals are tied to HEAD; no commit, pinned-document edit, increment verify/backup or new folder on D: between approval and launch.
- Never run the tool's verify on an earlier increment; use the independent re-hash. Always pass the correct --source.
- List every line-ending condition explicitly when accepting a proposal.
- Check that a tool has an argument parser before passing --help.
- An independent review of every new launch path before its first run. It has caught a missing launch path (g3-s2, `docs/rl_m9_g3_s2_prelaunch_review_2026-10-07.md` H1), a refusing test (runbook §1.4 blocker 1) and a wrong increment name (sd2, `docs/rl_m8_sd2_results_2026-10-12.md` section 14, A1).
- Fix launch-procedure findings in the prompt as amendments; don't edit pinned records.
- Write new files with LF line endings; fingerprints are defined on committed files.
- Check that the launcher's PowerShell resolves the same Python interpreter as the suites.
- Lab experiments that answer a question in minutes come before building a module family (the splice probe answered the splice question in six minutes of native time, before any of the 15 to 25 hours of modules).
- Readiness refusals on free commit are fixed by closing Steam, ChatGPT and idle Claude sessions, never by lowering a threshold.
- The Write tool can produce CRLF: check new and edited files for CR bytes before finishing.
- Promoting only target breaks prevented multi-burst crossing chains (the frontier search, `docs/frs_frontier_2026-10-14.md`): stepping stones are required.
- Idle Claude sessions are cleared by quitting the desktop app from the tray, then `Get-Process claude | Stop-Process`; no restart needed.
- Lab runs need no Claude session and can be started by hand from Git Bash.
- Commit tools before a lab run, so its recorded HEAD points to the code that ran.
- Lab evidence lives only on C: until backed up: back it up after every result.

## Right now
- As of 2026-10-16: best verified clear 1,245 input ticks (20.73 s, lab, unregistered; registered best 1,885). Lab evidence backed up to D:/BattleShip_lab_backup/2026-10-16/. No session or lab run active. November starts with tier 1, stage 0 (the run 3 tool) and the native batched-prefix design, per docs/rl_decisions_2026-10-16.md.
