# Decisions (2026-10-16)

## Results this week (lab, unregistered; each clear verified twice from tick 0)
- Crossing search run 1 (`docs/frs_crossing_search_2026-10-15.md`): best 1,429 input ticks (23.80 s), 298 verified clears.
- Crossing search run 2 (`docs/frs_crossing_search_run2_2026-10-15.md`), continued from run 1's archive: best 1,245 input ticks (20.73 s); the other verified bests on the way were 1,261 and 1,352.
- Every clear above was replayed twice from tick 0 in fresh processes, and both replays matched the claim. None is registered: the registered best is unchanged at 1,885 (31.40 s, `docs/rl_m8_sd2_results_2026-10-12.md`).
- The lab evidence is backed up and verified at `D:/BattleShip_lab_backup/2026-10-16/`: a copy of `C:/BattleShip_lab/` and of the lab-related Git-ignored `logs/` folders, 1,360 files, re-hashed independently with 0 mismatches (`README.txt` and `SHA256SUMS.txt` there).

## Supersedes
- The November build order in `docs/rl_decisions_2026-10-14.md` (minimal lab runner, then lab night 1, then the fresh counter and the pooled ahead draw) is superseded: the crossing-search line is the main November line.
- The earlier components remain available: PACE and the step-4 plan (`logs/frs_step4/plan.md`, Git-ignored, backed up with the lab evidence).
- Lab night 1 (CONTROL against CONT) never ran. It runs only if a comparison needs it.
- Donkey Kong is revisited at a later checkpoint; g4 comes after it.
- That record is not edited. Apart from the build order, and the plateau reading that answer Q11 below sets for the crossing-search line, its decisions are not changed by this one.

## Strategy (`docs/frs_strategy_2026-10-16.md`)
- Its findings are accepted:
  - About 37 % of the 1,245 clear (about 455 ticks) is waiting or slow movement: landing lag, helpless falls, shield and idle ticks, down-B and fireballs (its section 1).
  - The agent's own data supports roughly 860 ticks with the current approach: its fastest observed right side, crossing and left side chained give 859, and each comes from a different start. The data shows nothing below about 850 (its section 2).
  - The limit is how rarely the search returns to promising cells, not the inputs. The 1,245's chain used 13 of run 2's 39,309 dispatches; most of the rest of the time went to waiting for the selection to come back to a link (its section 5).
- Two tiers for November:
  - Tier 1: the review's stages 0 to 2. Stage 0 is the run 3 tool (run 2's tool with the end record stored, the per-group budget, the rank draw and the anchors). Stage 1 is run 3 from run 2's archive. Stage 2 is the order-diverse right-side arm. Stage 3 (state-aware representatives) comes only if stage 2 stops.
  - Tier 2, decided at the first checkpoint: a segment-level speed optimiser. It optimises each target-to-target segment from good start states toward the time to the next target, then chains the segments. The throughput levers it depends on come with it.
  - First checkpoint = the end of stage 1 (run 3's first night).
- Answers to the review's open questions (its section 8):
  - Q1, first night: run 3 with the per-group budget, the rank draw and the anchors.
  - Q2, budget unit: per (level, mask) group first.
  - Q3, draw within a group: the rank of the arrival tick, with a novelty floor.
  - Q4, anchor decay: an anchor's share halves after each burst without a new earliest arrival in its group, and recovers on one.
  - Q5, seeds for the right-side arm: every class, with anchors per class.
  - Q6, state-aware representatives: only if stage 2 stops.
  - Q7, offline cell-prior study: in week 1.
  - Q8, the 1,245 result: registered at the first checkpoint, through replay, provenance and lineage (the registration scope of decision Q10 in `docs/rl_decisions_2026-10-14.md`). Its procedure is prepared and reviewed first.
  - Q9, throughput: no native throughput work for run 3. The design of the native batched prefix (`docs/frs_prefix_cost_2026-10-14.md` section 4.3) starts in week 1, because tier 2 depends on it.
  - Q10, claims: a claimed clear is replayed only when it is faster than the best verified clear, with deduplication.
  - Q11, plateau: read on verified clears and on the earliest arrival per group. Three nights without progress ends a line. The 2026-11-27 calendar review set on 2026-10-14 (`docs/rl_decisions_2026-10-14.md`, Q9) still applies.
- My goal stays under 8 s. The current approach is not expected to reach it (the data supports about 860 ticks, 14.3 s), which is why tier 2 exists.

## Lessons
- Promoting only target breaks prevented multi-burst crossing chains (the frontier search, `docs/frs_frontier_2026-10-14.md`): stepping stones are required. The crossing searches crossed through chains of kept intermediate cells.
- Idle Claude sessions are cleared by quitting the desktop app from the tray, then `Get-Process claude | Stop-Process`. No restart is needed.
- Lab runs need no Claude session and can be started by hand from Git Bash.
- Commit tools before a lab run, so that its recorded HEAD points to the code that ran.
- Lab evidence lives only on C: until it is backed up: back it up after every result.
