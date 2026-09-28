# M7p evidence addendum: the two left-side candidates of the seed-1 geo4 final evaluation

Written 2026-09-28 after the recorded M7p decision (`failure_regression`; v3 stays selected). This addendum changes
nothing about that decision; it documents the two episodes that crossed x = -2100 in a final tick-0 evaluation, one of
which is the project's first replay-verified qualified crossing. No new policy evaluation was run. Sources: the campaign
records (`runs/m7p/campaign/_clears/m7p_geo4_s1/final/crossing_verification.json`, the final stochastic evaluation and
its preserved artifacts) plus the one minimal exact replay this addendum registered
([`rl_geometry_scale_m7p_crossing_replays.json`](rl_geometry_scale_m7p_crossing_replays.json), write-once) and ran with every
raw reply kept (`runs/m7p/addendum/crossings/replays/*/trace.json.gz`, facts in `runs/m7p/addendum/crossings/facts.json`,
tool `rl/tools/m7p_crossing_addendum.py`). Both replays are exact (digest, consumed ticks, every action, break table,
first left entry). Fixtures and TAS were not read; native RNG was not inspected.

## 1. Identity

| item | value |
| --- | --- |
| checkpoint | `runs/m7p/campaign/m7p_geo4_s1/final` (run `m7p_geo4_s1`, 3,072,000 transitions, 6,000 updates); `model.zip` sha256 `f7d11d76…`, `vecnormalize.pkl` `822386f6…`, `checkpoint.json` `676feb0e…` |
| observation contract | `btt_policy_obs_v3_geo4`, digest `2b984528…`, derived from `btt_policy_obs_v3_entities` `4ddc2933…`; network `btt_policy_net_v3_multiinput_mlp64`; `norm_obs` False (no statistics) |
| runtime / configuration metadata | `checkpoint.json` (contracts, PPO, seeds, executable `748dbad9…`, HEAD `88f6e79`, submodules `decomp 3834e22` / `libultraship 805f195` / `torch 3aa9c97`, native flags `SSB64_RL_NO_RENDER / RAPHNET_DISABLE / RL_SPATIAL / RL_ENTITY` = 1), `run.json`, `experiment.toml` (byte copy of `rl/configs/m7p/m7p_geo4_s1.toml`), `experiment_resolved.json` beside the run |
| evaluation | `runs/m7p/campaign/_eval/m7p_geo4_s1/final/stochastic/evaluation.json`, seed 12345, frozen parameters, tick-0 starts, metrics on (`SSB64_RL_TARGET_DIAG` = 1 added) |
| verification | `runs/m7p/campaign/_clears/m7p_geo4_s1/final/crossing_verification.json` (criterion `btt_qualified_crossing_v1`, 2 candidates, 2 exact, 1 qualified, X = 1); replay work dirs `crossing_000_af661e29`, `crossing_001_eabee627` |

## 2. The two episodes

Stage facts used below (decoded geometry): the tall wall's face is at x = -1800, the **ledge L0** is the static floor
x -2100..-1200 at y = 3000 (the wall top), L1 is the raised right step x 2100..3300 at y = -450, the left floor L3 is
x -3900..-2700 at y = -1950, the main floor L4 ends at x = -1800; the pit between L4 and L3 spans x -2700..-1800. The
left region is x < -2100. Targets 1, 6, 8 are the left targets; 2 is the moving target.

| | candidate A | candidate B |
| --- | --- | --- |
| episode id | `episode_20260928T072129Z_44619208` (rank 4, worker episode 5) | `episode_20260928T072253Z_85c10043` (rank 2, worker episode 10) |
| artifact | `runs/m7p/campaign/_eval/m7p_geo4_s1/final/stochastic/workers/w04/artifacts/episode_20260928T072129Z_44619208/` (`actions.jsonl`, `metadata.json`) | `…/workers/w02/artifacts/episode_20260928T072253Z_85c10043/` |
| native action digest | `af661e29…` | `eabee627…` |
| exact replays | campaign `crossing_000_af661e29` (verification) and addendum `runs/m7p/addendum/crossings/replays/00_44619208/trace.json.gz`; both exact | campaign `crossing_001_eabee627` and addendum `…/01_85c10043/trace.json.gz`; both exact |
| length / end | 3,445 ticks; native failure (fall) at consumed tick 3444 | 1,227 ticks; native failure (fall) at consumed tick 1226 |
| break order (target @ consumed tick) | 0@218, 4@327, 9@706, 5@1579, 7@2400, **6@3008** | 0@32, 4@155, 7@800 |
| targets remaining at takeoff / entry / landing / termination | 6 / 5 / 4 / 4 | 8 / 7 / (no landing) / 7 |
| classifier's approach surface (last static right floor) | L1 at tick 2318, (2157, -450), grounded, jumps used 0 of 2, moving platform at y 1588 descending | L1 at tick 745, (2100, -450), grounded, jumps used 0 of 2, platform at y 2718 descending |
| flight L1 -> ledge | 116 ticks (2318-2434): jump squat at 2318, first jump 2319, aerial attack, double jump 2358, aerial attack, up-B onset 2399, apex y 3151 at x -1226 (tick 2426), **landing on the ledge L0 at (-1315, 3000)** at tick 2434; inputs mostly L / UL stick with A (86 of 116) and B (16) | 123 ticks (745-868): jump squat 745, first jump 746, aerial attack, double jump 789, aerial attack, up-B onset 839, apex y 3126 at x -1378 (tick 861), **landing on the ledge L0 at (-1466, 3000)** at tick 868; inputs L stick (106 of 123) with A (88) and B (29) |
| on the ledge | grounded on L0 for 525 ticks (2434-2958), status mostly idle / turn, ending at x -1232 (the ledge's right end) with jumps used 0 | grounded on L0 for 131 ticks (868-998); fireball (status 223) at 988-990, then a **grounded up-B** (status 225) from 994 at x -1466 |
| actual takeoff toward the left region | tick 2958-2959 from L0: `UL+A` then `DR+A` starts a jump (jumps used 1 at 2959), `U+A` at 2960 gives the double jump (2), then `L+A` / `L+B` while drifting left; no up-B on this flight | tick 998-999 from L0: the grounded up-B (`U+B` at 994, then `L+B`, `U+A`, `L+A`, `L+B`) launches at 999 with jumps used 2 of 2 (special fall follows), air velocity (-90, +115) |
| platform state at takeoff / entry | y 1588 rising (+8.1) / y 2186 rising (+17.5); platform at x 2700, far right, not involved | y 3277 descending (-4.3) / y 3236 descending (-7.1); not involved |
| entry (crossing x = -2100) | consumed tick 3001 at (-2118, 3932), airborne, status 224 (aerial fireball), jumps used 2, crossing height 3,950 (class `over_wall`, path `over_ledge`); apex before entry y 4098 at x -1778 (tick 2989) | consumed tick 1005 at (-2131, 3892), airborne, status 225 (up-B), jumps used 2, crossing height 3,853 (`over_wall`, `over_ledge`); the entry step is the apex |
| left target | **target 6 broken at tick 3008**, fighter at (-2303, 3676) airborne in the fireball state, 7 ticks after entry, 133 ticks before landing (broken by the aerial fireball / body during the descent; the replay's break table confirms it) | none |
| landing | **L3 at tick 3141, (-3061, -1950)**, status 59 (landing), jumps reset to 0; grounded on L3 3141-3272, walking right from x -3061 to -2740 | none: special fall from the apex, min x -2812, x -2632 when passing y = 0, into the pit between L3 (ends x -2700) and L4 (starts x -1800) |
| termination | after leaving L3's right end (x -2740) the fighter drifted right and fell into the pit; failure at 3444, (-2186, -9649), 4 targets remaining (1, 2, 3, 8) | failure at 1226, (-2269, -9651), 7 targets remaining |
| criteria (`btt_qualified_crossing_v1`) | over_wall entry PASS; over-ledge path PASS; grounded takeoff PASS; landing on a decoded left floor in the same visit PASS -> **qualified crossing**; left-target break PASS (target 6) | over_wall entry PASS; over-ledge path PASS; grounded takeoff PASS; landing FAIL (native failure before any left floor) -> **unqualified left entry**; no left-target break |
| route label | `lower_precision` (classifier: approach surface L1 is the raised right step) | `lower_precision` |

**The qualified crossing and the target-6 break are the same episode (candidate A).** Candidate B is the other seed-1
episode: an over-wall entry from the ledge by a grounded up-B that ended in the pit without a landing.

### Same movement sequence or different approaches?

The two episodes share the first half of the manoeuvre and differ in the second:

- Shared: a takeoff from L1 (jump, aerial attack, double jump, aerial attack, up-B at the end of the flight) that
  **lands on the ledge L0 itself** after about 120 airborne ticks, with left-stick inputs held on 60-86 % of the flight
  ticks. This is a different use of the ledge from the validated human crossings, which flew over it; the policy treats
  the wall top as a platform to stand on. Neither episode used the moving platform.
- Different: candidate A then walked to the ledge's right end, waited 525 ticks, and left the ledge with a full jump +
  double jump and leftward drift (no up-B), threw a fireball, broke target 6 during the descent and landed on L3;
  candidate B waited 131 ticks, threw a fireball, and left the ledge with a grounded up-B that spent both jumps and
  ended in a special fall into the pit. The first 60 recorded actions after each L1 takeoff are identical in 30 of 60
  ticks (a partially repeated pattern, not a copied sequence).

## 3. Preservation

Preserved and unchanged (nothing was deleted, moved or overwritten by this addendum): the seed-1 final checkpoint set
(`model.zip`, `vecnormalize.pkl`, `checkpoint.json`, `preservation_state.json`) with its observation contract and runtime
metadata; the run's `run.json`, `experiment.toml`, `experiment_resolved.json`, `metrics/`; the two canonical action
artifacts and their metadata; the campaign's crossing verification document and replay directories; the two addendum
traces with every raw reply; the registered replay list.

**Git does not back these up.** `.gitignore` line 120 ignores `/runs/` entirely, so every file under
`runs/m7p/…` (checkpoints, artifacts, verification documents, traces, `analysis_n3.json`, `measurements.json`) is
untracked and would not be included in any commit. `build-*/` (the executable) is ignored too. What a commit of the
source would carry: the profiles under `rl/configs/m7p/`, the M7p modules and tools under `rl/`, and the documents and
JSON records under `docs/` (manifest, rule, registration, decision, results, this addendum and its replay registry).
Committing the source therefore preserves the identity of the evidence (hashes, ids, paths), not the evidence itself; a
backup of `runs/m7p/campaign/m7p_geo4_s1/final`, the two artifact directories, `runs/m7p/campaign/_clears/m7p_geo4_s1/final`
and `runs/m7p/addendum/crossings` is a separate step the user must take.

## 4. What these episodes establish, and what they do not

They establish policy-controlled left-side progress from a normal tick-0 start under the project's own contracts: a
learned Track 1 policy took off from the raised right step, landed on the wall top, crossed into the left region at
height, broke a left target and landed on the left floor, all replay-verified on a fresh process with the standing native
timing, reset and non-PORT restrictions. Both episodes reached the ledge from L1 without the moving platform, and
candidate A shows that a left target can be broken before any landing.

They do not establish repeatability (two episodes of 100 in one seed; the other two seeds and every control seed had
none), a clear (four and seven targets remained; both ended in falls), or any superiority of geo4 (the registered
comparison found geo4 worse on targets in every seed, and these episodes were counted exactly as the rule counts them:
X = 1 in one seed). They do not show that a right-side sweep must precede a valid clear: candidate A crossed with two
right targets (2 and 3) still standing and candidate B with five, and nothing here says in which order a clear must be
assembled. No new experiment is proposed in this document.
