# Run 3 design analyses

These scripts back the step 7 run 3 decisions (`SESSION_LOG_2026-11-04.md` §16).

- Zero native ticks. They read `C:/BattleShip_lab` read-only.
- Each script writes its JSON results to `--out`. The default, `logs/run3_design/`, is Git-ignored.
- Standard library only, except numpy for `run3_model.py` and its drivers.

```
python -B tools/analysis/run3_design/<script>.py [--lab C:/BattleShip_lab] [--out logs/run3_design]
```

Run `d3_anchor_replay.py` before the scripts that read `d3_dispatch_log.json`.

| script | backs | what it measures |
| --- | --- | --- |
| `d1_census.py` | DECISIVE 1 (§16.2), MINOR table (§16.1) | Run 2's outcomes and ticks, and the dispatches, breaks, falls and clears per level and per group. Cells per level, both all and eligible at 1,220. The share of each group's dispatches that went to its 10 earliest cells, against the share the rank draw gives them. |
| `d1_group_shares.py` | DECISIVE 1 (§16.2) | The earliest arrival per level over run 2, and b, e and ρ per group. The review's share as written (every group on the floor) against normalised-then-floored shares. |
| `d1_rank_draw_sim.py` | DECISIVE 1 (§16.2) | One simulated night of the cell weight (1 + rank)^-α × max(ν, 1 / (1 + draws)), with α = 1, ν = 0.05 against the alternatives. |
| `d2_demotion.py` | E7 answer, warm-start fix, DECISIVE 2 (§16.3) | Level-9 cells around the bound and the shortest final segments. Per group, the whole-run and last-200 counters. Start shares under the literal warm start, the 200-pseudo-dispatch fix, and the fix plus demotion. |
| `d3_anchor_replay.py` | DECISIVE 3 (§16.4), DECISIVE 4 (§16.6) | Replays run 2 dispatch by dispatch over run 1's archive. Records the class and group rank of each dispatch, its yield by rank, and the waits of new earliest arrivals. Also the anchor bursts, the new class-top-3 arrivals, and the anchor sets at run 3's start. Writes `d3_dispatch_log.json`. |
| `d3_class_lineage.py` | DECISIVE 3 (§16.4) | Break and fall rates by resource class. The lineage of every verified clear. The ranks of each link of run 2's bests at the dispatch that made the next link. |
| `d3_anchor_sim.py` | DECISIVE 3 (§16.4) | One simulated night with the rank draw alone, with lead-order anchors, and with rotating anchors (floors 1/8, 1/4, 1/16). Also counts the descendant rule. |
| `d4_breadth.py` | DECISIVE 4 (§16.6) | The crossing cell's history and the pools at the moment it crossed. Run 2's useful breaks by tick band, class, rank decile and earlier dispatches, and from cells above 1,220. Order niches from the exact lineage (parent digests). One simulated night per breadth option (U, LU, GU, ON, CB, demoted in or out) and per budget unit (mask groups, or niche groups with either rate). |
| `d4b_niche_units.py` | DECISIVE 4b (§16.7) | The run 3 start in the new unit (level, mask, order niche), from an exact replay. Each run 2 dispatch is credited to the niche of the representative actually dispatched. Lists every new group's run 2 counters (n, falls, b, useful b, e), eligible cells, classes and anchors. Gives φ per level, the warm-start rate, DECISIVE 2's demotion, and the start shares. Also counts group moves (replacements into another niche) in runs 1 and 2, and checks the niche derivation against the bursts' break lists. |
| `d2_rolling_replay.py` | DECISIVE 2 revision (§18.2) | Rebuilds every run 2 dispatch and every dispatch of run 3's night (`crossing_2026-11-06_run3`) as the selector counts them (fall, any break, useful break, e), checked against the plan's history and the night's own per-group totals. Replays demotion on the group's last 1,000 dispatches, and the whole-history rule beside it: demotions and exits, the group's own dispatches while demoted, false demotions (a useful break or an e while demoted), and the bursts that give a demoted group a new earliest eligible cell. |
| `d5_level_weights.py` | Level weights before the inheriting run (§19) | The night's yield per dispatch by level at the 953 definition (all dispatches, and those from cells at or under 953), the earliest level-8 / 9 / clear arrivals and the arrivals at or under 953 hour by hour, the creation-to-clear path of each verified best, and one simulated night per level split (current, flat, 7-8 first) with `run3_model.py` on the real 953 start (the plan inheriting the night): draws and expected u + e per level, and the level-9 cells' draws. |
| `run3_model.py` | (module) | The selection model the simulations share. Its docstring states every assumption. |
| `_common.py` | (module) | Paths, row readers, the bound and the margin. |
