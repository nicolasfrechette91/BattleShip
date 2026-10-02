# Route discovery, phase 1: return-based archive exploration toward a verified tick-0 clear (proposal, 2026-10-01)

**Status: read-only analysis plus this proposal.** I launched no native process and collected, trained, committed and
pushed nothing. The only computations were scratch scripts outside the repository (appendix A). They read preserved
`runs/` artifacts and one checked-in data table, and imported no repository module. This document is the only file
added.

**Revision 2 (2026-10-01): your answers to the 13 open questions are applied throughout and listed in §14.**
- The new direction is milestone **M8**. Sessions are M8-rd1, rd2, …; later files use the prefix `rl_m8_rd`. This
  document keeps the name you asked for.
- Contract, code and run names were renamed to match (`m8_rd_*`).
- The cell key drops the velocity sign (§4).
- The budget is a fixed 3,000,000 native ticks per arm (§11).
- Workers use a frozen copy of the runtime config, and a rebuilt executable triggers full re-verification of every
  carried cell (§7.2, §8.3).
- Nothing is implemented or authorised.

**Decisions recorded, unchanged here:**
- The hybrid gate `h1` (`docs/rl_hybrid_ppo_planner_proposal_2026-10-01.md`) will not be launched.
- The M7u4 offline study (`docs/rl_model_planning_m7u4_offline_proposal_2026-10-01.md`) stays parked.
- Neither document is edited. Section 2 records one finding from the first as a known model-recipe limit.
- Selected learning baseline: **M7n v3 + reward v2** (Track 1 `btt_s9_b8_v1`, PPO). Every registered outcome M7d–M7u3
  stands as recorded.

**New direction (user decision).**
- **Phase 1, designed here.** Archive-based exploration whose goal is to **discover a route**: a full clear of Mario's
  Break the Targets from tick 0, verified by exact replay.
- **Phase 2, later and not designed here.** Go-Explore-style robustification of discovered routes into a genuine tick-0
  policy, then optimisation toward faster times.

**Short answer.**
1. **The hypothesis holds for discovery, with qualifications. It does not explain the learning failures** (§1):
   - Every explorer started at tick 0 stays right of the wall: random play at four hold lengths, PPO (v1 / v3 / geo4) and
     the planner. Random play reaches the early stepping stones (the raised step L1 in 51–63 % of episodes) but never
     chains them.
   - The one recorded intervention that returned an explorer to its own archived states, M7h's archive-prefix starts,
     produced every left-region event of those runs. That is 19 left-region episodes, 232 left-of-wall archive cells and
     two over-wall crossings (one landing on the left floor). The 1,876 tick-0 starts of the same runs produced none.
   - The effect appeared in **1 of 3 seeds**, with a PPO explorer. Good start states alone did not suffice for a frozen
     policy (M7n, 0 / 225).
   - Every learning line also failed at *consolidation* (M7h gate 4, M7m, M7p 2 / 100). Coverage is the phase-1
     bottleneck; it is not the whole story for phase 2.
2. **Cell `m8_rd_cell_v1`** (§4). The key is:
   - 300-unit position bins from the world origin;
   - a 5-way **resource class** (grounded with its native floor line / airborne with double jump and up-B / up-B only /
     no up-B / other);
   - the **full 10-bit live-target mask**.

   No RNG, no clock, no velocity. On 400 preserved random episodes this key gives 14,360 cells, against 3,680 under the
   M7h key.
3. **Selection** (§5). Choose the progress level (targets broken) geometrically from the top. Within a level, weight by
   count-based novelty times a prefix-length factor, so shorter prefixes are preferred. A cell keeps its shortest
   non-doomed prefix.
   - **Exploration** is a keyed sticky-random Track 1 burst: uniform over the 72 words, hold k ∈ {1, 2, 4, 8, 16},
     120 words.
4. **Return cost** (§6). Measured per-worker stepping is 789–1,397 ticks/s depending on the reply load. The aggregate
   with N = 5 and standby is **≈ 2,900 ticks/s**, measured by M7f on 10.07 M replays.
   - A return costs max(≈ 2.2 s boot, (L + 120) / r) per worker.
   - Prefix replay is 81–97 % of the native ticks once L ≥ 500.
   - Expect ≈ 8,100 returns per hour at short prefixes, falling to ≈ 2,700–4,000 per hour as prefixes approach the horizon.
5. **Exactness** (§7) rests on more than 5,000 recorded exact prefix and full replays, with no mismatch on record (M7f,
   M7h, M7n, M7p, M7r–M7u3). Each return is checked against the pinned tick-0 record, the consumed tick of every word, a
   per-tick observation chain digest and the full end record. Any mismatch stops the run as INVALID.
6. **Persistence** (§8). The archive is saved atomically, is resumable and is pinned to the executable and to a frozen
   copy of the runtime config. Every session opens and closes with identity replays and a verified D: increment. A
   rebuilt executable forces re-verification of every carried cell, and any mismatch stops for review.
7. **Session M8-rd1** (§11). About 60 minutes:
   - arm T (return-based archive) against arm C (the same explorer, fresh from reset, no return), matched on native ticks
     (**exactly 3,000,000 each**);
   - registered measures: max targets broken from tick 0, wall-top (L0) landing, qualified crossing, left-target break,
     clear;
   - rule `m8_rd1_rule_v1` (PASS / NULL / INCONCLUSIVE / INCOMPLETE / INVALID); every claim is replay-verified.
8. **Sessions to a clear** (§12). **Plausible, not likely in session 1.** My central estimate is **4–6 sessions** of
   about 60 minutes, with low confidence. The range runs from 1–2 sessions to never.
   - It becomes implausible under this design if session 1 is NULL, if no verified over-wall lineage exists after three
     sessions, or if the top-level prefixes crowd the 3,600-tick horizon.

## 0. Verified state and what was read

| item | state |
| --- | --- |
| checkout | `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, branch `main`. `HEAD` = `origin/main` = remote `refs/heads/main` (`git ls-remote`) = `68064d9`. Working tree clean before this document. Remotes: `origin` is the user's fork; `upstream` (JRickey) is reference only |
| submodules | `decomp e4f06348` (`rl-main`), `libultraship 805f1950`, `torch 3aa9c97`; not touched |
| executable | `build-us/Release/BattleShip.exe` sha256 `30a3913b…` (the M7q/M7u build); hashed, not run |
| guide and instructions | external `..\guide.md` (revised 2026-09-22; narrative stops at M7g), `CLAUDE.md` |
| documents read | `docs/rl_handoff_2026-09-28.md`; `docs/rl_mechanics_observation_audit_2026-09-28.md`; M7n implementation §9–10, prefix feasibility, sweeps addendum; M7o assessment; M7p results, crossing addendum, wall-top census; M7r results; M7s results; `docs/rl_m7t_closure_2026-09-29.md`; M7u / M7u2 / M7u3 gate results; the M7u4 offline proposal; the hybrid proposal; also, for the return mechanism, the M7h proposal §2–3, gate report and results, and the action-hold probe |
| preserved artifacts read | M7h final archives and curriculum logs of `m7h_f_s{0,1,2}` and `runs/m7h/_report/entry_describe_v2.log`; the 400 random-probe episodes `runs/probes/action_hold/episodes/k*/ep*.json.gz` (every raw reply) and `results.jsonl`; `rl/data/m7n_action_classes_v2.json` (the decomp-derived status class table) |
| not read or used | crossing fixtures, capture recordings, the TAS input and anything derived from them |

## 1. The working hypothesis against the preserved evidence

The hypothesis under test: every learning line so far learned from the agent's own experience, which rarely reaches the
parts of the stage that matter, so **exploration and coverage are the bottleneck**.

### 1.1 What explorers started at tick 0 reach

| explorer (tick 0 only) | episodes | left of the wall (x < −2,100) | wall-top / ledge | source |
| --- | ---: | --- | --- | --- |
| uniform random, hold k = 1 / 4 / 8 / 16 | 400 | 0; min live x −1,650 (the wall foot) in every condition | over-ledge (y ≥ 3,000, x ≤ −1,200) 0; best height near the wall 1,807 | action-hold probe |
| PPO v1 / v2, random and bias samples (exact diagnostic replay) | 3,074 sequences | 0; never past x −1,650 | 14 sequences at wall-top height; none closer than x −357 at that height | M7f |
| PPO v3 finals (selected baseline), 3 seeds | 300 | 0; 1 unqualified over-wall entry in all 2,955 v3 evaluation episodes | — | M7n |
| M7h F policies, tick-0 evaluation | 2,955 | 0 | highest final-checkpoint y 2,811 | M7h |
| PPO geo4 seed 1 final (rejected recipe) | 100 | 2 (1 qualified crossing) | L0 landings 2 / 100; L1 in 52, 74 flights | M7p census |
| learned-model planner | 24 + 24 goals | — | no model training row above y 2,659 | M7u2 / M7u3, hybrid §2.3 |

**Stepping stones in random play** (scratch `s3`, the 400 probe episodes with native `floor_line_id`):

| k | episodes grounded on L1 (raised right step) | on the moving platform | airborne with up-B unused at y ≥ 1,639 | … and x ≤ 600 | over-ledge |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 59 | 1 | 7 | 1 | 0 |
| 4 | 63 | 1 | 7 | 0 | 0 |
| 8 | 55 | 0 | 6 | 1 | 0 |
| 16 | 51 | 0 | 5 | 1 | 0 |

The height threshold 1,639 is M7p's measured minimum up-B start that can reach y 3,000. Random play routinely produces
the first conditions of a wall-top approach: L1 contact, and occasionally a high airborne state with the up-B still
available. It never chains them, because each episode starts over from tick 0.

### 1.2 What returning to the explorer's own archived states changed (M7h F arm)

M7h trained PPO with half of its episodes started by exact replay of an archived own prefix
(`btt_curriculum_frontier_v1`, cell `(x/300, y/300, targets_remaining)`, weight 1/√(1 + visits)). Its own logs give a
within-run comparison: same policies, same runs, two start kinds (scratch `s1`, `s5`).

| start kind (3 seeds pooled) | episodes | left-region episodes | over-wall entries, genuine | left-target breaks under policy |
| --- | ---: | ---: | ---: | --- |
| tick 0 (incl. 15 initial resets) | 1,891 | **0** | **0** | 0 |
| archive prefix | 1,886 | **19** (18 in seed 1, 1 in seed 2) | **2** (seed 1; plus 1 under-stage entry in seed 2) | targets 8 and 6 (seed 1, from prefix-reproduced left starts) |

| final archive | seed 0 | seed 1 | seed 2 |
| --- | ---: | ---: | ---: |
| cells | 4,249 | 4,564 | 4,806 |
| cells left of the wall | 0 | **232** (24 with 7 targets broken, 153 with 6) | 5 (the under-stage fall) |
| cells at y ≥ 3,000 | 37 | 187 | 55 |
| grounded on L0 | 0 | 0 | 0 |
| fewest targets remaining in any cell | 4 | 3 | 3 |

**Seed 1's lineage.**
- The first genuine over-wall entry came after **284** archive starts, at lineage depth 4 (four archived generations).
- A second entry came from a cell at prefix length **254**. It crossed x = −2,100 at row 314 at y 4,086, with one target
  broken. Agent-generated trajectories can therefore reach the left side very early.
- Once a left lineage existed, the archive returned to it 15 more times. Targets 8 and 6 were broken from those starts.
- All 19 left-region episodes ended in a fall.

### 1.3 What the evidence does not support

- **The effect was rare.**
  - It occurred in one seed of three. Seed 0 had no left cell in 648 archive starts, and seed 2's only entry passed
    under the stage.
  - 2 genuine crossings against 0 in about 1,890 starts per kind is suggestive but not significant on its own (one-sided
    Fisher p ≈ 0.25 for 2 vs 0).
  - Across the project, about 3 over-wall entries are on record in tens of thousands of tick-0 episodes. The two
    archive-start crossings came in 1,886 starts.
- **Start states are not enough by themselves.** From nine favourable post-sweep states, the frozen v3 policies made 0
  over-ledge passages in 225 continuations (M7n prefix feasibility). Returning only helps if the explorer can extend
  from the state it returns to. For the wall top, that means the archive must ratchet through *airborne* intermediate
  states, not just restart on the ground.
- **The M7o novelty credit does not test return.** It is an intrinsic reward inside PPO, with no return; its credit
  decayed to about 0.013 per episode. Its `failure_regression` is consistent with the known weakness of count bonuses
  without return (the frontier is forgotten or not re-reached). It neither supports nor refutes the hypothesis.
- **Learning.** M7h's discoveries were not consolidated into tick-0 behaviour (gate 4); anchored starts did not transfer
  (M7m null); M7p's route stayed at 2 / 100. The learning lines (M7s functionality, M7t readout, M7u model accuracy)
  hit their own blockers as well. Coverage is a precondition for all of them, but more coverage would not by itself have
  fixed those blockers.

### 1.4 Verdict (accepted by you, 2026-10-01)

**For discovery, the hypothesis holds.** Tick-0 exploration of any kind tried so far does not reach the left side. The
only intervention that did was return to own archived states, and only once in three seeds, with an explorer and
archive not built for discovery.

**As an explanation of why no policy has learned a clear, it does not hold on its own.** Consolidation is a separate,
demonstrated bottleneck, which is the reason to keep phase 2 separate. Phase 1 is justified as a discovery tool. Its
success would not show that a policy can learn the route.

## 2. Known model-recipe limit: the up-B rise is mispredicted (recorded, no change to either proposal)

Recorded from `docs/rl_hybrid_ppo_planner_proposal_2026-10-01.md` §2.3 (c), unchanged.

**The physics.** After an L1 takeoff, a wall-top (L0) arrival is decided by the up-B: its launch adds a fixed native rise
of **+1,361.3**, the stick cannot brake it, and it reaches y 3,000 only from a start of at least **1,638.7**. The
recorded failures missed by **8.6** units at the start, and the landings cleared it by 126–151 (M7p).

**The frozen M7u1 model,** open loop over 48 ticks from every up-B onset in its data:

| | held-out (55 onsets) | in-sample (300 sampled) |
| --- | --- | --- |
| member \|rise error\|, median (p25) | **586** (274) | **553** (233) |
| onsets with all 3 members within 100 units | **0 / 55** | 0.3 % |
| onsets where a member majority predicts any rise ≥ 1,000 | 52.7 % | 54.7 % |

**The other recipes, on the same held-out onsets:**
- P_refit: member error 689, majority launch 43.6 %;
- P_retrain: member error 590, majority launch 61.8 %;
- every model: 0 / 55 onsets with all members within 100 units.

**Status.** This is a **known limit of the M7u model recipe**, not of one checkpoint. Any planner-side approach to the
wall top depends on it.
- `h1` is not launched and M7u4 stays parked, as decided. Neither proposal is edited.
- Phase 1 below uses no learned model, so the limit does not affect it.
- A model-based component proposed for phase 2 would have to show up-B launch accuracy first.

## 3. Design overview

```
archive (cells; each cell = one exact own prefix from tick 0, the shortest non-doomed one found)
  │ select a cell (level from targets broken, novelty, prefix length)          ← §5
  ▼
fresh process (standby promoted at tick 0) → non-consuming observe = pinned tick-0 record
  ▼
replay the cell's L canonical words, one `step` each (consumed_tick == i), chain digest per tick  ← §7
  ▼ end record + chain at L must equal the archive's, else INVALID
explore: keyed sticky-random Track 1 burst, 120 words or native end / fall / horizon             ← §5.3
  ▼
insert every new cell reached (prefix = cell prefix + burst words up to that tick); replace a cell's representative when
a strictly shorter (or non-doomed) prefix reaches it; close the process; log the iteration          ← §4.3
```

**What it never uses:**
- savestates, in-process resets or hidden actions. Each iteration is one fresh process, whose episode the restart resets;
- learned components or reward shaping;
- the crossing fixtures, capture recordings or the TAS;
- native RNG.

## 4. Item 1: cell representation `m8_rd_cell_v1`

### 4.1 Key fields (live steps only: `btt_active = 1` and `fighter_valid = 1`)

| field | value | native source | why it is in the key |
| --- | --- | --- | --- |
| `mask` | the 10-bit **live-target mask** | `spatial.target_live_mask` | **Central.** A clear needs all ten targets, and the *identity* of the remaining targets decides what is left to do. A count would let a shorter prefix that broke an easy target replace one that broke target 2 or a left target. The guide's M8 lists target subsets as route families. 39 distinct masks occur in 400 random episodes |
| `bx, by` | ⌊x / 300⌋, ⌊y / 300⌋, grid origin = world origin, no clipping | `position_x/y` | spatial progress; §4.2 |
| `res` | **G** grounded; **A2** airborne, double jump and up-B available (`jumps_used < 2`, not helpless, not in up-B); **A1** airborne, up-B available, no double jump (`jumps_used = 2` outside the up-B states); **A0** airborne without up-B (class `special_hi` or `helpless`); **X** damage / dead / appear / other / unmapped | `ground_air_state`, `jumps_used`, `fighter_status_id` → `btt_action_class_table_v2` (decomp-derived names, Mario validated) | The two aerial resources are the levers of every wall-top approach on record: double jump height, then the up-B. `jumps_used` alone cannot separate "double jump used, up-B left" from "up-B used" (the audit's capacity-counter correction), so the status class is needed. Aerial attack, fireball and tornado locks fold into A2 / A1, because both resources survive them |
| `floor` (G only) | the native floor line id | `spatial.fighter.floor_line_id` | separates standing on L0 / L1 / L2 / L3 / L4 / the moving platform from being airborne in the same bin; makes a wall-top landing a distinct cell |

**Absent by design:**
- **horizontal velocity sign** (your decision 2):
  - fewer cells means more revisits per cell, and `res` already captures what matters in the air;
  - accepted risk: a reversal costs about 30 ticks (air acceleration 2 / tick, cap 30), about a quarter of a recorded
    L1 → L0 flight (116 ticks), so a representative drifting the wrong way can replace a better one in the same cell;
  - the descriptive readings of §11.3 show whether this happens;
- vertical velocity sign (follows from position along the arc and from `res`);
- the clock and time passed: the prefix length *is* the time, and it is what "prefer shorter" minimises;
- grounded speed (a ground reversal is short);
- the moving platform's phase (Mario's position captures it when he stands on it);
- RNG in any form (§10).

The key is computed from one reply produced with `SSB64_RL_SPATIAL=1`. That diagnostic is read-only and
trajectory-neutral (M7g-b equivalence). No other diagnostic is needed during exploration.

### 4.2 Granularity, measured on the 400 preserved random episodes (scratch `s4`, 1.23 M ticks)

| key variant | cells | after 100 / 200 / 300 / 400 episodes | new cells per episode at the end |
| --- | ---: | --- | ---: |
| M7h key `(x/300, y/300, targets_remaining)` | 3,680 | 2,050 / 2,888 / 3,360 / 3,680 | 3.2 |
| 600-unit bins + mask + res (+ floor) | 5,700 | 2,740 / 4,080 / 4,902 / 5,700 | 8.0 |
| **300 + mask + res (+ floor) — `m8_rd_cell_v1`** | **14,360** | 6,578 / 10,009 / 12,192 / 14,360 | 21.7 |
| 300 + mask + res (+ floor) + horizontal velocity sign (rev 1 proposal, not selected) | 25,461 | 11,145 / 17,472 / 21,561 / 25,461 | 39.0 |
| 300 + mask + res + horizontal and vertical velocity signs | 35,295 | 15,247 / 24,143 / 29,908 / 35,295 | 53.9 |
| 150-unit bins + mask + res | 36,353 | 15,946 / 24,811 / 30,656 / 36,353 | 57.0 |

**Why 300-unit bins:**
1. **Bin size against motion.** A bin is crossed in about 4–10 ticks of air drift, run or rise (air speed ≤ 30, dash 54,
   up-B rise about 45 / tick). Cells therefore change every few ticks, and a 120-word burst crosses many of them.
2. **Surfaces separate.** The surfaces that matter are ≥ 300 apart vertically: L0 3,000, L1 −450, L2 −1,500, L3 −1,950,
   L4 −2,550. Each falls in its own bin row, and `floor` resolves the rest.
3. **The decisive margin is representable without placing anything by hand.** The up-B can clear y 3,000 only from a
   start ≥ 1,639. Every A2 / A1 cell in bin rows y ≥ 1,800 is therefore launch-capable by construction. The 8.6–151-unit
   margins are left to exploration from those cells.
4. **Same grid as M7f and M7h.** It was proven workable at 4–5 k cells per run.

**Why not finer or coarser:**
- 150-unit bins multiply cells by about 2.5 with no stage feature that needs them.
- 600-unit bins merge the y 1,500–2,100 band, where launch-capable and non-capable starts meet.
- The extra dimensions (`mask`, `res`, `floor`) cost about ×3.9 in cells over the M7h key, but they are exactly the
  quantities that distinguish route-relevant states. The archive keeps growing (21.7 new cells per random episode), and
  §5 handles the dilution.
- Adding the velocity sign would have cost a further ×1.8. It was dropped (decision 2).

### 4.3 Representative, replacement and doom

- **Representative.** Each cell stores one trajectory: the canonical words 0 … L − 1 whose last reply (`input_tick = L`)
  is the first live reach of that cell along that trajectory. It also stores the end record and the chain digest at L
  (§7).
- **"Better" (replacement):**
  1. a non-doomed reach beats a doomed one;
  2. then the strictly shorter L wins;
  3. ties keep the incumbent.

  Counters stay with the cell.
- **Doomed.** The representative's own burst hit a native fall (`btt_native_failure_v1`) within **60** ticks after the
  reach (M7h's window).
  - Doomed cells are kept for coverage but never selected.
  - A burst that ends within 60 ticks of the reach without a fall counts as not doomed.

## 5. Item 2: selection, scoring and the exploration policy

### 5.1 Eligibility

A cell is eligible if all of the following hold:
- it is not doomed;
- its class is not X;
- its representative did not end the episode at L;
- **L ≤ 3,600 − 120**, so one full burst fits inside the horizon.

Cell 0 (the tick-0 reset, L = 0) is always eligible.

### 5.2 Selection `m8_rd_select_v1` (all parameters fixed here, none tuned; decision 4)

1. **Progress level.** ℓ(c) = number of broken targets = 10 − popcount(mask). Let ℓ* be the highest level with an
   eligible cell. Draw level ℓ* − j with probability ∝ 2^−j over the levels that have eligible cells. Half the returns go
   to the top level, and every lower level stays alive, because a clear may need a different mask from a lower level
   (for example, the moving target before the wall).
2. **Cell within the level:** w(c) = w_nov(c) · w_len(c), where
   - w_nov(c) = 1/√(1 + chosen(c)) + 1/√(1 + seen(c)), the count-based novelty of Go-Explore. *chosen* = times selected;
     *seen* = bursts in which the cell was visited;
   - w_len(c) = 900 / (900 + L(c) − L_min(ℓ)), where L_min(ℓ) = the shortest eligible prefix at that level.

   **This is the "prefer the shorter prefix among equal progress" rule.** A cell 900 ticks (15 s of game time) longer
   than the level's shortest gets half weight. Together with the replacement rule of §4.3, routes stay reasonably short
   without optimising time.
3. **Draws.** Two uniforms from sha256(`m8_rd|<archive_id>|select|<global iteration>`). The draws are Python-side, keyed and
   stateless, so a resumed archive needs no generator state.

**Nothing else enters the score:**
- no position, height, surface, distance or target-location bonus;
- no goal;
- no route or order;
- no reward.

### 5.3 Exploration from a cell: `m8_rd_explore_v1` (Track 1 `btt_s9_b8_v1` only)

- **Decisions.** At each decision, draw one of the **72 Track 1 words uniformly** and a hold length **k uniformly from
  {1, 2, 4, 8, 16}** (mean 6.2). Submit the word's canonical native triple for k consecutive ticks.
- **Burst length.** 120 words (2.0 s of game time), or less at native `EpisodeEnded`, a `btt_native_failure_v1` fall or
  the 3,600-tick horizon. A hold is clipped at any of these.
- **Keying.** Draws come from sha256(`m8_rd|<archive_id>|explore|<global iteration>|<decision index>`).

**Why sticky multi-scale random:**
- **Short holds keep fresh edges.** k = 1–2 keeps the taps the controller needs: the 3-tick jump buffer, fresh B / C
  presses and stick taps for the double jump.
- **Long holds provide drift.** k = 8–16 provides the sustained drift that a 3,300-unit L1 → ledge traverse needs.
  Per-tick uniform sticks average to zero drift.
- **Measured evidence for multi-scale.** The action-hold probe found no single k better from tick 0. k = 1 had the best
  height near the wall (1,807) and k ≥ 4 drifted no further, so a mixture loses nothing measured.
- **The explorer reads no observation**, which keeps arms T and C identical and needs no policy observation stack.

**Why 120 words:**
- It covers the 116-tick L1 → L0 flight on record (M7p) and the 64–128-tick reach horizons of M7u.
- It is of the order of Go-Explore's 100-action bursts.
- It is short against the prefix, so returns stay frequent. Longer bursts spend native ticks (the budget unit) far from
  the selected cell.

**Alternatives, not used (decision 3):**
- pure per-tick random (k = 1);
- a PPO explorer as in M7h. It would bring a learned component back into what must be a clean exploration test. It
  would also need the v3 observation stack, it is slower, it is the confined behaviour of §1.1, and it would make the
  arm-C control a policy rather than a probe.

### 5.4 Insertion during a burst

For every live reply of the burst with `input_tick = j`:
1. compute the key;
2. a new key is inserted with L = j, its end record and its chain digest;
3. an existing key is replaced only when the new reach is better (§4.3);
4. `seen` is incremented once per burst per visited cell.

Prefix rows are never inserted, because they reproduce known trajectories. Doom status of the burst's reaches is
settled at burst end.

## 6. Item 3: return cost

### 6.1 Measured throughput (preserved records; scratch `s2`, `s1`)

| record | setting | per worker | aggregate |
| --- | --- | ---: | ---: |
| M6 raw | plain client, no-render + Raphnet bypass, no diagnostics | 2,112 (single) | 8,525 at N = 5 |
| M7h E6 | prefix replay inside the M7 worker, v1 observation | 1,397 | — |
| M7h campaign dispatch | 2,430,160 prefix ticks over 1,809 s of dispatch wall, almost always one prefix at a time | 1,299 / 1,356 / 1,367 | — |
| M7h E3 | 200 prefixes, standby or cold | median 1,094 | — |
| **M7f diagnostic replay** | **10,066,918 replies, 3,074 sequences, N = 5 with one pre-booted process each, target diagnostic on** | ≈ 587 incl. restarts | **≈ 2,933** (57.2 min) |
| action-hold probe | 3 workers, cold start per episode, spatial + entity + target diagnostics, every raw reply kept | **789** stepping + **2.22 s** per start (least-squares fit over 400 episodes) | 1,206 (17.0 min) |
| M7p wall-top census | 1 process, all diagnostics, raw kept | ≈ 471 | — |
| M7u planning stack | v4 input, planner in the loop | ≈ 110 | ≈ 545 |

**Planning figures for a lean worker with `SSB64_RL_SPATIAL` only:**
- per worker r = 789–1,300 ticks/s;
- boot b ≈ 2.2 s, overlapped by the M7c standby when an iteration lasts at least that long;
- aggregate at N = 5 **≈ 2,500–2,900 ticks/s**, the M7f anchor (heavier spatial replies discount it slightly).

M8-rd1 measures it in its first minutes and reports it. The budget is in native ticks, so throughput changes only the
wall time.

### 6.2 Return overhead as routes lengthen (scratch `s6`; E = 120, N = 5)

| prefix L | prefix share of native ticks | wall per iteration, standby overlapped / serial: r = 789 | r = 1,300 | returns per hour at N = 5: r = 789 (overlapped / serial) |
| ---: | ---: | --- | --- | --- |
| 0 | 0 % | 2.22 / 2.37 s | 2.22 / 2.31 s | 8,108 / 7,588 |
| 500 | 80.6 % | 2.22 / 3.01 | 2.22 / 2.70 | 8,108 / 5,988 |
| 1,000 | 89.3 % | 2.22 / 3.64 | 2.22 / 3.08 | 8,108 / 4,946 |
| 1,500 | 92.6 % | 2.22 / 4.27 | 2.22 / 3.47 | 8,108 / 4,212 |
| 2,000 | 94.3 % | 2.69 / 4.91 | 2.22 / 3.85 | 6,699 / 3,668 |
| 2,500 | 95.4 % | 3.32 / 5.54 | 2.22 / 4.24 | 5,421 / 3,249 |
| 3,000 | 96.2 % | 3.95 / 6.17 | 2.40 / 4.62 | 4,552 / 2,915 |
| 3,480 | 96.7 % | 4.56 / 6.78 | 2.77 / 4.99 | 3,945 / 2,654 |

**Reading:**
- **Below L ≈ 1,600 a return is boot-bound.** The process restart, not the replay, sets the rate, and longer prefixes
  are almost free in wall time.
- **Toward a full clear the selected prefixes approach the horizon.** The archive then spends **95–97 % of its native
  ticks re-playing known prefixes**, and the return rate falls to about **2,700–4,000 per hour** at N = 5. Per return
  that is 1.3–2.3 s of wall per worker beyond the boot floor.
- **This is affordable** because the useful quantity is returns, not exploration ticks. It is also the reason the
  length factor of §5.2 and the shortest-prefix replacement matter: shorter prefixes are both better routes and cheaper
  returns.
- **The overhead is pure replay:** no learning, no observation building, no model.

## 7. Item 4: exactness of prefix replay

### 7.1 Evidence on record

| record | exact replays | what was compared |
| --- | --- | --- |
| M1e / M6 / M7c | 447-step authoritative replay; normal = no-render = bypass; cold = standby-promoted | every step and observation |
| M7f | **3,074 / 3,074** sequences, 10,066,918 replies | native digest, break tables, every diagnostic reply |
| M7h campaign | **1,886** archive-prefix starts, `delivered_equals_archived_end` 1,886, 0 digest mismatches, 0 consumed-tick mismatches; E3 200 / 200 (24 forced cold fallbacks) plus 20 / 20 full re-replays; every left entry | full end observation (`host_frame` reported, equal 200 / 200) |
| M7n | 225 prefix continuations (prefix digest, consumed ticks, post-prefix observation and target mask); 4 / 4 sweep replays | as stated |
| M7p | 100 / 100 census episodes, 2 addendum traces | digest, break table, first left entry |
| M7r / M7s / M7u1 / M7u2 / M7u3 | 12 / 12, all claimed returns, all successes, 6 / 6, 13 / 13 | digests and per-row fields |

**No mismatch is recorded anywhere in the project.**

**Why exactness is expected:**
- The game is deterministic given the executable, the runtime files, the controller words from tick 0 and the boot path.
- The opt-in diagnostics are read-only and trajectory-neutral (M7f / M7g / M7n / M7q equivalence).
- Standby promotion equals a cold start (M7c, M7h E3).

### 7.2 What must be pinned (beyond the words)

Each pinned identity is recorded in the archive. Any drift refuses resume, except the rebuilt-executable path below.
- **The executable sha256** (`30a3913b…` today).
- **A frozen runtime config** (decision 11):
  - **Taking the copy.** At M8-rd1's S0, `build-us/Release/BattleShip.cfg.json` and `imgui.ini` are copied once into
    `runs/m8_rd/archive/runtime/` and hashed. The CVars that change controller rules (`TapJumpDisabled.P1..P4`,
    `CasualRules.AutoZCancel`, `CasualRules.FailedZCancelFlash`) must be absent or zero, as the mechanics audit found.
  - **Using it.** Each worker runtime is prepared by the existing `m7_runtime.prepare_worker_runtime`. The private
    config copy is then **replaced by the frozen copy** and re-hashed before every launch.
  - **Isolation.** After S0, no M8 tool reads the user's live config again. Concurrent work, such as the replay viewer,
    cannot change an archive run through it.
- **The read-only runtime files the worker resolves** (`BattleShip.o2r`, `f3d.o2r`). Their sha256 come from the
  existing `runtime_manifest.json`; the files are hashed as files and never inspected.
- **The flag set** (`NO_RENDER`, `RAPHNET_DISABLE`, `SPATIAL`).
- **The Track 1 mapping table digest.**

**A rebuilt executable** (decision 11), for example from the replay-viewer work:
- **Effect.** The archive's exactness claim is suspended. No exploration session may run on the new executable until
  **every carried cell** has been re-verified from tick 0 on it.
- **Re-verification is its own separately authorised session.** It uses the §7.3 checks:
  - It replays the trajectory of every burst that holds at least one representative, checking each such cell at its L
    along that one replay. Every cell is covered at about the cost of one replay per such burst.
  - Projected cost: Σ (start L + burst length) over those bursts. With 3–8 representatives per burst and 15,000–40,000
    cells, that is about 4–15 M ticks, or 0.5–1.5 h at the §6 rate. The tool computes the exact figure before asking
    for the authorisation.
- **Any mismatch stops the session for review.** No cell is dropped, repaired or re-pinned silently. The archive stays
  pinned to the old executable until you decide.
- **If every cell passes,** the pin moves to the new executable, recorded with both digests.
- **The pinned executable is preserved.** A runnable copy is kept beside the archive, as `runs/m7f/_exe/pre_m7f` was, so
  a mismatch can be reviewed against it.

### 7.3 Per-return verification (every iteration, both arms where applicable)

1. **Tick 0.** The promoted (or cold) process's non-consuming `observe` equals the archive's pinned tick-0 record in
   every field except `host_frame`, which is reported. That includes the observe-only collision line table, compared by
   digest.
2. **Prefix.** Word i is submitted as `step`. The reply must have `consumed_tick == i`, `input_tick == i + 1`, state
   `WaitingForAction`, and no `EpisodeEnded` and no fall. A chain digest h_i = sha256(h_{i−1} ‖ canonical(record_i)) is
   updated per tick. record_i holds:
   - the 17-key observation minus `host_frame`;
   - the spatial `fighter` block, `groups`, `target_live_mask` and `target_positions`;
   - reply `state` and `step_count`.
3. **At L.** The full end record and h_L must both equal the archive's. Any difference stops the run (**INVALID**). There
   is no retry and no skip; the failed iteration's raw replies are preserved. A lifecycle failure (process death,
   timeout) is not a mismatch: the iteration is recorded as failed and redrawn. More than 3 per arm is INCOMPLETE.
4. **Burst.** The same per-tick contract checks apply, and the chain continues, so every newly inserted cell carries its
   own h_L.

### 7.4 Full-trajectory verification of claims

Every registered claim is verified by a fresh-process replay from tick 0 of its complete canonical words:
- a target count, an L0 landing, a crossing, a left-target break or a clear;
- the replay uses spatial + entity + target + input diagnostics, keeping every raw reply;
- the existing tools are reused: `rl/m7f_trace.run_stepping_trace`, the break table, and `rl/m7n_crossing.py`
  (`btt_qualified_crossing_v1`, unchanged).

A replay counts only if all of these are equal:
- the native action digest and every consumed tick;
- the break table (id, tick);
- the claimed event tick;
- the milestone predicate as re-derived by the registered analyser.

An inexact replay is **INVALID** for the session, never just uncounted (as M7n gate 0).

## 8. Item 5: persistence and bounded sessions

### 8.1 Layout (Git-ignored `runs/m8_rd/`)

| path | contents |
| --- | --- |
| `archive/archive_meta.json` | schema `m8_rd_archive_v1`, archive id, contracts and digests (`m8_rd_cell_v1`, `m8_rd_select_v1`, `m8_rd_explore_v1`, Track 1 table, status table `btt_action_class_table_v2`), pins (§7.2), horizon, burst length, session ledger, totals |
| `archive/cells.jsonl` | per cell: id, key, level, L, `burst_id` + offset, parent cell, end record, chain digest h_L, doomed flag, `chosen`, `seen`, new cells produced, first and last session and iteration, replacement count |
| `archive/bursts.bin` + `bursts.idx.jsonl` | per burst: id, start cell, start L, Track 1 indices (1 byte each), length, end reason, session, iteration, worker, the cell id reached at each tick (for offline audit) |
| `archive/runtime/` | the frozen `BattleShip.cfg.json` and `imgui.ini` (§7.2) and the pinned executable's runnable copy |
| `archive/manifest.sha256` | sha256 of every archive file |
| `sessions/rdK/` | iteration ledger (`iterations.jsonl`: selected cell, L, tick-0 / end / chain checks, standby or cold, burst id, inserts, replacements, ticks, wall), control episodes (arm C), memory samples, verification replays, the rule record, the open and close records |
| `routes/<claim>/` | Phase-2 material (§9) |

Each cell's prefix is reconstructed by walking `burst_id` → start cell → … → cell 0. Storage is lossless and about one
byte per word.

### 8.2 Saving and resuming

- **Atomic checkpoints.** Every 5 minutes, at each arm end and at close: write `archive.tmp/`, fsync, verify the
  manifest by re-reading it, rename, and keep `archive.prev/`.
- **A crashed session is INCOMPLETE.** The next session may resume only from the last verified checkpoint, after the
  open protocol. Ledger rows after that checkpoint are kept but marked not ingested.
- **Asynchronous ingestion.** Ingestion is asynchronous (completion order, single-threaded parent), which avoids
  lockstep stalls on mixed prefix lengths. The archive is therefore **auditable**, not bit-reproducible from a seed:
  replaying the ledger's ingest order over the stored bursts must rebuild every cell exactly (zero native ticks). Every
  claim is replay-verified independently, so the archive itself need not be bit-reproducible (decision 9).

### 8.3 Session open and close (every session)

**Open (S0). Zero native ticks except the identity replays:**
1. HEAD, the tracked tree and the approved source snapshot all match.
2. The archive manifest equals the previous close record.
3. The previous D: increment's `verification.json` is PASS, and its manifest covers every local archive file (0
   uncovered).
4. The pins match: executable, the frozen config (and each worker's copy of it), the read-only runtime files and the
   flags. If **only the executable** differs, the session is not an exploration session. Only the separately authorised
   full re-verification of §7.2 may run, and any mismatch stops it for review.
5. The approval for this session matches.
6. Readiness: memory, disk, and no BattleShip process.
7. **Identity replays (K = 16):** every milestone cell, the shortest cell of each of the top three levels, and keyed
   random cells. Each is replayed from tick 0 with the §7.3 checks. Any mismatch is INVALID, and the session does not
   run.

**Close (S2):**
1. Final atomic save.
2. Offline audit:
   - the ledger rebuilds the archive;
   - every prefix reconstructs to its stored L;
   - every cell's lineage reaches cell 0 of this archive.
3. Close identity replays (K = 16; a different keyed sample, the milestone cells included).
4. `rl/tools/runs_backup.py backup --source runs/m8_rd --dest D:\BattleShip_runs_backup\<date>_incr_m8_rdK`, then `verify`.
5. An independent PowerShell re-hash, and combined coverage with 0 uncovered.
6. The close record with every digest.

**Carrying the archive forward.** A session whose close fails still has a valid scientific record, but its archive is
not carried forward until the close is repaired.

## 9. Item 6: phase-2 readiness (stored, nothing designed)

- **Every cell:** its full canonical-word trajectory (via lineage, lossless), mask, level, L, end record and chain
  digest.
- **Every verified claim:**
  - `routes/<claim>/actions.jsonl` in the M4 canonical artifact form (`buttons`, `stick_x`, `stick_y`, `consumed_tick`,
    plus `native_action_digest`);
  - `metadata.json`;
  - `trace.json.gz` holding **every raw reply of the verification replay with all four diagnostics on**, so that any
    later observation contract (v1, v3, v4) can be rebuilt per tick without native ticks;
  - for a clear, both completion clocks (`completion_time_passed`, `completion_input_tick`), kept distinct.
- **Lineage:** parent cell, burst, iteration, session and worker for every cell; per-cell `chosen` / `seen` / new-cell
  counts; the full iteration ledger.

## 10. Item 7: explicit compliance

| constraint | how the design keeps it |
| --- | --- |
| prefixes agent-generated only | **The archive starts empty** (cell 0 = the tick-0 reset). Every other cell is inserted only from this archive's own bursts; its lineage must chain to cell 0 (audited at close and open). No other run's artifact seeds it, including earlier agent runs such as M7h and M7p, so no earlier PPO behaviour mixes into the result (decision 10) |
| runtime isolation | Workers use the frozen config copy taken at M8-rd1 S0, never the user's live file (§7.2) |
| human crossings and TAS are validation-only | No `m8_rd` module reads `rl/fixtures/`, `runs/m7g/capture/`, `tas_input_2/` or any `.btti` file. A static source guard test enforces this, M7h E2 style. They are never cells, starts, prefixes, demonstrations, scoring references or route hints |
| no hardcoded routes or waypoints | The key is a uniform grid on the world origin plus native fields. The score uses only targets broken (the task objective), counts and prefix length. There is no position, surface, height or target-location term, no goal, no order and no shaping |
| tick contract and canonical words | Every native word is one `step`, checked for consumed tick T and returned `input_tick` T + 1, in the prefix, the burst, arm C and every verification. Reset is the non-consuming `observe`; nothing is hidden. Canonical native triples are the replay truth; Track 1 indices are metadata |
| process restart resets the episode | One fresh process per iteration and per control episode (standby promoted at tick 0 or cold), closed after use. No in-process reset, no savestate |
| no native RNG inspection, logging, control, comparison or hashing | Nothing reads, logs, sets or hashes RNG state. All draws are Python-side sha256-keyed uniforms. The chain digest covers observation fields only, and no reply carries RNG state |
| non-PORT decomp behaviour preserved | No native, decomp or submodule change. The existing executable (`30a3913b…`) and existing opt-in, read-only flags are used |
| Track 1 only | The explorer draws from the 72 `btt_s9_b8_v1` words. Prefixes are recorded words of this archive |

## 11. Item 8: the first bounded session M8-rd1

### 11.1 Arms

| arm | what runs | budget |
| --- | --- | --- |
| **T** (treatment) | the full loop of §3: select, return, burst, insert. N = 5 workers, one standby each, flags `NO_RENDER`, `RAPHNET_DISABLE`, `SPATIAL` | **exactly B = 3,000,000 native ticks** (prefix + burst). The iteration in progress at the budget is cut there; only ticks within it count. Wall cap 26 min. It continues regardless of discoveries |
| **C** (control, no return) | `m8_rd_explore_v1` (same draws scheme, keyed `m8_rd1|control|<episode>|<decision>`) from a fresh tick-0 process, each episode run to native end, fall or the 3,600 horizon. Same workers, flags and per-tick checks; cells are recorded for coverage, never selected | **exactly B = 3,000,000 native ticks.** The last episode is cut at the budget; only ticks within it count. Wall cap 24 min |

**Why match on native ticks (decision 5):**
- It is the honest test of whether return is worth its replay cost: every prefix tick counts against T, so T gets no
  free compute.
- The guide's unit is game frames, not wall time.
- T runs first, then C; the machine state and order are recorded.

### 11.2 Registered measures (per arm; each verified per §7.4)

1. **t**: the maximum number of targets broken in one trajectory from tick 0, within the arm's budget and the 3,600
   horizon.
2. **L0 landing**: a grounded live tick with `floor_line_id = 0`, the wall top.
3. **Crossing**: `btt_qualified_crossing_v1`, unchanged.
4. **Left-target break**: target 1, 6 or 8.
5. **Clear**: the M7d four-fact definition — end reason clear, cleared flag, ten broken targets, completion clock. Both
   clocks are reported.

**Milestone ladder:** m = 0 none < 1 L0 < 2 crossing < 3 left target < 4 clear. m is the highest level whose predicate
holds for some verified trajectory of the arm.

**Candidates.** The worker labels candidates online over the full trajectory (prefix + burst, or the control episode):
- the max-t trajectory: the shortest at that t;
- the first L0 cell;
- every trajectory with a live left step, a left-floor landing or a left break;
- every clear.

**Verification order and cap.** Candidates are verified in discovery order, per milestone, until one qualifies. The cap
is 400,000 replay ticks per session (§11.4).

### 11.3 Decision rule `m8_rd1_rule_v1` (applied once, after verification; fixed before any tick; decision 7)

| outcome | condition (evaluated in this order) |
| --- | --- |
| **INVALID** | any integrity failure: a tick-0 / prefix / end / chain mismatch; a consumed-tick violation; an inexact verification replay; a provenance or static-guard violation; a pin drift; any read of fixtures or TAS |
| **INCOMPLETE** | any of the following, which make the result not a performance result: either arm did not reach **B = 3,000,000** native ticks within its wall cap; a candidate that could change the outcome was left unverified at the replay cap; a memory or process-count stop; more than 3 lifecycle failures in an arm |
| **PASS** | m(T) > m(C), or m(T) = m(C) and **t(T) ≥ t(C) + 2** |
| **NULL** | m(T) < m(C), or m(T) = m(C) and t(T) ≤ t(C) |
| **INCONCLUSIVE** | otherwise (m equal and t(T) = t(C) + 1) |

**Properties.**
- The five outcomes are disjoint and exhaustive.
- The rule reads only verified m and t; no diagnostic enters it.
- The PASS record carries a reading, `pass_milestone` or `pass_targets`.

**Why +2.**
- Random tick-0 play broke at most 5 targets in 400 episodes (5 in 1–6 % of episodes per hold length, never 6). The control's maximum
  over about 1,000 episodes is therefore expected at 6, perhaps 7.
- The M7h PPO archive reached 7.
- One target above the control's maximum is within what a lucky control episode could add. Two is not.

**What each outcome means.**
- **PASS.** On this seed, return-based archive exploration progressed beyond the matched no-return control. Continuation
  sessions become eligible to propose; none is authorised by the outcome.
- **NULL.** No sign that return helps with this cell key and explorer. Stop the design; revise, do not rerun.
- **INCONCLUSIVE.** Revise, not rerun. The persistent archive remains valid evidence, and continuing it is a separate
  decision.
- **INCOMPLETE.** Read the caps; no extension.
- **INVALID.** Repair, then a new approval.

**Reported, never deciding** (both arms):
- coverage: cells, distinct masks, position bins;
- first-reach tick from tick 0 of each level;
- best y with x ≤ −1,200, L1 contacts, launch-capable states (the §1.1 table);
- archive size per level; returns;
- return overhead (prefix share), standby vs cold starts, throughput, memory;
- **velocity reversals at replacement:** airborne cell replacements where the new representative's horizontal velocity
  has the opposite sign to the incumbent's (|vx| ≥ 6 for both). This watches the risk accepted with decision 2. It is
  read only and never changes the key within the M8 line without a new contract.

### 11.4 Budget, caps and timeline

| phase | native ticks: expected (cap) | wall: expected (cap) |
| --- | ---: | --- |
| S0 open, outside the clock: repo, snapshot, D: coverage, approval, readiness, empty archive, the frozen runtime config copy (§7.2) | 0 | ≈ 5 min |
| P1 identity: tick-0 record pinned from one process and reproduced by a second (standby-promoted); the two shortest pinned Track 1 artifacts (3,361 + 2,560 words) word for word through the `m8_rd` worker; a return self-test in a scratch archive (3 cells from one keyed burst, returned from fresh processes; a corrupted end record must be refused) | ≈ 8,000 (10,000) | ≈ 1 min (3 min) |
| arm T | exactly 3,000,000 | ≈ 17–20 min (26 min) |
| arm C | exactly 3,000,000 | ≈ 17–20 min (24 min) |
| verification: claims (≤ 20 trajectories) + close identity replays (16 cells), ≤ 3 processes | ≈ 60,000–130,000 (400,000) | ≈ 3 min (7 min) |
| **within the clock** | **≤ 6,410,000** | **≈ 40–45 min; hard cap 60 min from P1** |
| S2 close, outside the clock: save, audit, D: increment, verify, re-hash | 0 | ≈ 5–10 min |

**Expected returns in T:** 3,000,000 / mean(L + 120) ≈ **1,900–2,700**.

**The risk of the fixed budget.** T reaches 3,000,000 ticks in about 17–20 min at the §6 aggregate, but only if the
standby boot overlaps the returns. If boots serialise (r = 789, about 1,700 ticks/s aggregate at L ≈ 1,200), T needs
about 29 min. It would then hit its 26-min cap, and the session would be INCOMPLETE. The first minutes of T report the
rate, so this shows early. No cap is extended.

**Memory and process caps** (the M7u3 values, which bounded comparable process trees):
- main process private ≤ 3,072 MB;
- whole tree, sampled every 5 s over all descendants: private ≤ 9,216 MB, working set ≤ 4,096 MB. M7u3 peaked at 7,020 /
  3,218 MB with 26 processes;
- system available ≥ 1,024 MB and free commit ≥ 2,048 MB, else stop;
- archive in memory ≤ 1,024 MB (projected 10–40 MB);
- ≤ 10 BattleShip processes; none left after the run;
- readiness: ≥ 4,096 MB available, ≥ 10,240 MB free commit, ≥ 5 GiB free on C: and on D:.

### 11.5 Integrity

**Before the run:**
- **Source snapshot.** `D:\BattleShip_source_snapshots\<date>_m8_rd1`, made with the snapshot tool of the M7u3 kind: tool
  `snapshot` and `verify`, then an independent PowerShell re-hash. It is re-verified after the run.
- **Approval record.** `docs/rl_m8_rd1_approval.json`, written from a freshly printed template. It names
  the rule digest, the three contract digests, the pins, budgets, caps, the key strings and the code hashes. Preflight
  refuses for exactly one reason without it, then passes with it.
- **D: coverage.** 0 uncovered `runs/` files over the base plus every increment.

**During the run:** every check of §7.3, the memory sampler, the process bound, and the ledger.

**After the run:**
- the claim verification of §7.4;
- archive close (§8.3);
- the D: increment of `runs/m8_rd`.
- Preparation output goes under `logs/`, never `runs/`.

**Gotchas carried over:** short temp paths (MAX_PATH); approval tests on isolated temp records; repository-state tests
that break preflight once the approval exists; memory readiness judged on working set.

## 12. Item 9: how many sessions might a full clear need?

**Supply of returns** (§6):
- Session 1, arm T: ≈ 1,900–2,700 returns.
- A continuation session (no control arm, about 50 min of exploration, cap ≈ 8 M ticks): ≈ 3,500–6,500 returns. That
  falls toward ≈ 2,500–3,500 once most selected prefixes sit at L 2,500–3,400.

**Demand: a stage model.** The stages are sequential, because each needs the previous level in the archive. Progress
weighting sends about half of the returns to the current top level. All stage figures are assumptions anchored on the
listed evidence, not measurements of this design.

| stage | evidence anchor | returns needed: optimistic / central / pessimistic |
| --- | --- | --- |
| A. the seven right targets, incl. the moving target 2, in one trajectory | random tick-0: target 2 in 1–3 %, 7 in 4 %, 3 in 6–14 % of episodes; M7h PPO archive: 7-broken cells in 2 of 3 seeds within about 600 archive starts | 500 / 2,000 / 6,000 |
| B. an over-wall lineage that survives: an L0 landing or a crossing | M7h PPO archive: 2 genuine over-wall entries in 1 seed, first after 284 archive starts; about 1 per 1,900 archive starts pooled. Random tick-0: launch-capable states in 5–7 % of episodes, over-ledge 0 / 400. A random explorer is assumed 1–10× less effective per return than PPO at flights | 1,000 / 6,000 / 25,000 |
| C. the three left targets, incl. target 1 (under the left floor; never broken by any agent) without falling | M7h: targets 8 and 6 broken within about 15 returns to left cells; all 19 left episodes fell | 500 / 4,000 / 15,000 |
| D. all ten in one trajectory within 3,600 ticks | none. PPO sweeps of the right seven took 1,678–3,392 ticks; agent flights about 120 ticks; left-side sequences 150–450 ticks; random-burst routes will be longer until shortened | 0 / 3,000 / blocked by the horizon |
| **total** | | **≈ 2,000 / ≈ 15,000 / ≥ 46,000 or blocked** |
| **sessions of about 60 min, incl. M8-rd1** | | **1–2 / 4–6 / ≥ 10 or never** |

**Plain statement.**
- **A clear in session 1 is unlikely.** I would put it below 10 %.
- **Session 1 should reach 7 or more verified targets from tick 0.** It has a fair chance of an L0 landing or an
  over-wall lineage; I would guess 15–35 %.
- **A clear is plausible with this design within about 4–6 sessions,** with low confidence in that figure.

**It becomes implausible under this design, and should be reviewed rather than continued, if any of the following
holds:**
1. M8-rd1 is NULL;
2. no verified over-wall lineage exists after three sessions;
3. the median L of the top level's eligible cells exceeds about 3,000 before the left targets are reached (horizon
   pressure).

In case 3, the obvious lever is a longer discovery horizon. By decision 6 it needs a separate decision and a new label.
Changing the cell key or the explorer would be a new design, not a continuation.

**Continuation policy (decision 12).** After a PASS, continuation sessions run one at a time. Each is authorised
separately, carries its own registered measures, and is subject to the stop conditions above.

**What the estimate does not cover:**
- phase 2: robustifying a discovered route into a policy is a different and, on the project's record, harder problem;
- speed: routes found here are reasonably short, not optimised.

## 13. Implementation outline (new files only; a separate authorisation)

| file | contents | approx. lines |
| --- | --- | ---: |
| `rl/m8_rd_cells.py` | `m8_rd_cell_v1`: key, resource class from `btt_action_class_table_v2`, end record, chain digest, contract digest | 200 |
| `rl/m8_rd_archive.py` | cells, insertion and replacement, doom, eligibility, `m8_rd_select_v1`, lineage, atomic save, manifest, ledger audit | 600 |
| `rl/m8_rd_explore.py` | `m8_rd_explore_v1` keyed sticky-random Track 1 bursts | 100 |
| `rl/m8_rd_worker.py` | lean worker on `battleship_process` / `battleship_client` / `m7_standby`: frozen-config substitution after `prepare_worker_runtime` (hash-checked per launch), tick-0 check, prefix replay with chain and end check, burst, fall detection, control episodes | 480 |
| `rl/m8_rd_session.py` | S0 / P1 / T / C / verification / S2, caps, tree sampler, approval, identity replays, D: backup calls; a separate `reverify` command for the rebuilt-executable path of §7.2 (cost projection first, stop at the first mismatch) | 800 |
| `rl/m8_rd_rule.py` | `m8_rd1_rule_v1` and its self-test (every boundary, disjointness, INCOMPLETE paths) | 150 |
| `rl/m8_rd_tests.py` | synthetic-world tests: insertion and replacement, lineage reconstruction, ledger audit, keyed draws, static source guard, rule | 500 |

**Reused unchanged:** `rl/m7f_trace.py`, `rl/m7n_crossing.py`, `rl/m7_standby.py`, `rl/m7_runtime.py`,
`rl/battleship_client.py`, `rl/battleship_process.py`, `rl/tools/runs_backup.py`, the M7u3 tree sampler and snapshot
tool. No inherited file needs an edit.

**Preparation** (zero native ticks except an optional P1 dry run): code, unit tests, synthetic end-to-end run, rule
self-test, preflight, and the approval template.

## 14. Decisions (your answers, 2026-10-01) and what they changed

| # | decision | applied in |
| ---: | --- | --- |
| 1 | Verdict accepted: holds for discovery, not as the explanation of the learning failures | §1.4 |
| 2 | **Drop the velocity sign, keep the full target mask.** Fewer cells mean more revisits per cell; the resource class already captures what matters in the air; which targets are left shapes the route | §4.1, §4.2 (14,360 cells on the random data); the risk is watched by a reported reading (§11.3) |
| 3 | Explorer: sticky multi-scale random as proposed. PPO would bring a learned component back into a clean exploration test | §5.3 |
| 4 | All selection settings fixed in advance as proposed | §5.2 |
| 5 | **Budget: native ticks, 3,000,000 per arm**, the honest test of whether return is worth its replay cost | §11.1, §11.3, §11.4. I read it as **exactly** 3,000,000 per arm, which replaces the earlier "up to 3,000,000, minimum 1,500,000". T's wall cap is raised to 26 min, and an arm that misses the budget is INCOMPLETE (item a below) |
| 6 | Horizon 3,600 for M8-rd1; a longer horizon later only by separate decision, under a new label | §11, §12 |
| 7 | Rule as proposed | §11.3 |
| 8 | Diagnostics as proposed: spatial only while exploring, all four in verification replays | §4.1, §7.4 |
| 9 | Ingestion asynchronous and auditable from the log; the archive need not be bit-reproducible, since every claim is replay-verified | §8.2 |
| 10 | Start empty. Seeding from M7h or M7p would mix earlier PPO behaviour into the result | §10 |
| 11 | **Rebuilt executable → re-verify every carried cell; any mismatch stops the session for review; nothing is dropped silently. Workers use a frozen copy of the runtime config**, protecting runs from the concurrent replay-viewer work | §7.2, §8.1, §8.3, §10, §13 |
| 12 | After a PASS, continuation sessions one at a time, each authorised separately, with the stop conditions applied | §12 |
| 13 | **Milestone M8** for the new direction; sessions M8-rd1, rd2, …; file prefix `rl_m8_rd` | Throughout: contracts `m8_rd_*`, rule `m8_rd1_rule_v1`, code `rl/m8_rd_*.py`, runs `runs/m8_rd/`, approval `docs/rl_m8_rd1_approval.json`, snapshot `<date>_m8_rd1`, backup `<date>_incr_m8_rdK` |

**Remaining items to confirm (none blocks this document):**
- **a. The fixed-budget reading of decision 5** (exactly 3,000,000 per arm, T cap 26 min). §11.4 states the risk: if
  standby boots serialise, T may hit its cap and the session would be INCOMPLETE. The alternative would be the earlier
  "up to 3,000,000" with a 1,500,000 floor.
- **b. The external guide still describes M8 as raw-input route discovery and frame-perfect polishing (Track 2).**
  M8 now begins with this Track 1 discovery phase. I did not edit the guide; whether and how to re-scope its M8 section
  is your call.
- **c. This document's name.** It keeps the name you requested. Later M8 documents would use `rl_m8_rd`. Should this
  one be copied or renamed to that prefix when it is committed?
- **d. Next step.** The zero-native-tick preparation (§13: code, unit tests, synthetic end-to-end, rule self-test,
  preflight, approval template) needs its own authorisation. M8-rd1 needs another after that.

## Appendix A. Scratch analyses (outside the repository; not evidence)

**Location.** `%TEMP%\claude\…\scratchpad\rd\`. Every script ran with `python -B`, read preserved files only and
imported no repository module.

| script | what it did |
| --- | --- |
| `s1_m7h_archive.py` | the three M7h final archives: cells by targets remaining, prefix lengths, left-of-wall / high / L0 cells, prefix and dispatch statistics |
| `s2_hold_rate.py` | the action-hold probe's ticks and wall times, with a least-squares fit wall = 2.220 s + ticks / 788.6 per episode |
| `s3_random_stones.py` | the 400 random episodes: L1 / platform / L0 contacts, launch-capable states, cells under the proposed key, masks |
| `s4_key_variants.py` | archive size and growth under seven candidate keys on the same episodes |
| `s5_m7h_lineage.py` | M7h selection logs: archive starts before the first genuine entry, lineage depth of each left episode |
| `s6_return_cost.py` | the return-cost table of §6.2 from the measured anchors |

One inadvertent working-directory change during the session (a `cd` into `runs/m7h/campaign/m7h_f_s1` to list files)
wrote nothing. The working tree was verified clean after this document was written, apart from this document.

**Revision 2.** The edits were made with the editor and one scratch script, `r1_rename.py`, which applied the M8 names
(contract, code, run, approval, snapshot and backup identifiers) to this document only. No figure from the scratch
analyses changed. The selected key's cell count (14,360) is the `s4` value already reported in rev 1.
