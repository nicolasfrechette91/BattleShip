# M7p addendum: the seven high L1 flights of the seed-1 geo4 final policy

Written 2026-09-28 after the wall-top census. Offline only: the existing census traces (raw native replies) and the
canonical action artifacts were read; no native process ran, nothing was trained. The M7p decision
(`failure_regression`, v3 selected) is unchanged. Tool `rl/tools/m7p_flight_compare.py` (outside the frozen fingerprint
set); per-tick rows and derived facts in `runs/m7p/addendum/walltop_census/flight_comparison.json`, console output in
`flight_comparison.log` beside it. Ticks are consumed ticks; "dt" is ticks after the takeoff tick (the last grounded
step on L1, `KneeBend` = jump squat). Positions are the native fighter position; velocities are the native air
velocities; contact ids are the native collision line ids (line 12 = the ledge's right face x -1200, y 2700..3000; line 0 =
the ledge top L0). Status names are the decomp enumerators.

## 1. Seven-flight comparison

| | `…44619208` | `…85c10043` | `…2394f859` | `…78b3dea2` | `…d3a8d7b1` | `…f5806b84` | `…9736791a` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| outcome | **L0 landing** (2434) | **L0 landing** (868) | L4 (3301) | L4 (1417) | L4 (2094) | L4 (3297) | L4 (3522) |
| takeoff tick / x on L1 / facing | 2318 / 2156.6 / right | 745 / 2100.0 / left | 3093 / 2601.2 / left | 1206 / 2131.0 / right | 1887 / 2632.0 / right | 3094 / 2153.2 / right | 3308 / 2446.5 / right |
| takeoff state / action | KneeBend, v 0, jumps 0 / UL+Z | KneeBend / N+B | KneeBend / UL+Z | KneeBend / DL+A | KneeBend / UR+B | KneeBend / L+A | KneeBend / L+B |
| first jump (dt) | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| first-jump path y at dt 30 / 35 / 38 | 894 / 908 / 888 | same | same | same | same | same | same |
| aerial attack during the first jump | AttackAirB from dt 1, 78 attack ticks | AttackAirF from dt 5, 87 | AttackAirF from dt 48, 46 | AttackAirF from dt 50, 48 | AttackAirB from dt 10, 78 | AttackAirF from dt 48, 39 | AttackAirB from dt 10, 78 |
| **double jump (dt) / y at that tick** | **40 / 947.4** | **44 / 877.0** | 47 / 799.0 | 47 / 799.0 | 50 / 699.4 | 47 / 799.0 | 61 / 226.2 |
| stick, first jump to double jump | L 23, UL 10, U 4 | L 37, UL 5 | L 29, UL 15 | L 23, UL 18 | L 31, UL 13 | L 27, UL 11 | L 32, U 18, UL 6 |
| up-B start (dt / after the double jump) | 81 / 41 | 94 / 50 | 97 / 50 | 100 / 53 | 91 / 41 | 93 / 46 | 102 / 41 |
| **state at up-B start: x, y, vy** | **34.4, 1789.5, -0.5** | **-417.8, 1764.5, -0.5** | -50.1, 1630.1, -0.5 | -290.6, 1598.3, -0.5 | -36.2, 1586.9, -0.5 | -236.7, 1527.5, -0.5 | -252.2, 1113.7, -0.5 |
| stick through the up-B startup (first 6 ticks) | U D L L D U | UR L L L L L | UL L L L UL N | U L L L L L | U U L L L L | U L D L L L | U U L D L U |
| up-B launch velocity (vx, vy) | -126.3, 174.7 | -126.3, 174.7 | -126.3, 174.7 | -126.3, 174.7 | -126.3, 174.7 | -126.3, 174.7 | **-0.5, 215.5** (vertical) |
| stick during the up-B flight | L 23, U 8, D 5 | L 27, U 2 | L 20, U 86 (incl. the fall) | L 26, U 81 | L 25, U 89 | L 23, U 80 | L 19, U 87 |
| vx / vy sequence after launch | identical in all six angled flights (-117.4, -108.9, … / 160.8, 147.3, …), whatever the stick | | | | | | own sequence |
| ledge-face contact (x clamped at -1050.0, right-wall id 12), heights | none | 3 ticks rising, y 2605-2789 | 1 tick falling, y 2782 | 4 rising (2537-2763) + 1 falling | 1 rising (2806) + 1 falling | 5 rising (2552-2792) + 3 falling | none (never within 300 of the face) |
| ledge approach (first tick x <= -1100): x, y, vx, vy | -1132.6, 3116.8, -40.1, 27.0 | -1144.1, 2929.2, -59.8, 64.8 | -1116.7, 2894.5, -49.2, 45.1 | -1119.9, 2898.6, -44.5, 35.8 | -1110.9, 2887.2, -44.5, 35.8 | -1100.2, 2873.6, -35.7, 18.8 | never |
| **apex: tick, x, y** (vx -26.8, vy 4.0 in all) | 2426, -1226.1, **3150.8** | 861, -1378.1, **3125.8** | 3212, -1193.2, 2991.4 | 1328, -1168.1, 2959.6 | 2005, -1159.1, 2948.2 | 3209, -1112.2, 2888.8 | 3434, -120.1, 2927.9 |
| apex minus the ledge top / apex x minus the ledge edge | +150.8 / -26.1 (over) | +125.8 / -178.1 (over) | -8.6 / +6.8 | -40.4 / +31.9 | -51.8 / +40.9 | -111.2 / +87.8 | -72.1 / +1079.9 |
| first tick at y >= 3000 over the ledge span | 2426 (-1226.1, 3150.8) | 856 (-1200.0, 3028.9), floor id -> 0 | never | never | never | never | never |
| landing possible / missed: state there | at 2426: SpecialAirHi, jumps 2 of 2 used, descending onto L0, `LandingFallSpecial` at 2434 (-1315, 3000) | at 856: SpecialAirHi, jumps 2 used, landing 868 (-1465.7, 3000) | at the apex: SpecialAirHi, jumps 2 used; `FallSpecial` from 3229 (-1000, 2412); L4 at 3301 | same: FallSpecial 1345, L4 1417 | same: FallSpecial 2022, L4 2094 | same: FallSpecial 3226, L4 3297 | same: FallSpecial 3449 at x +206, L4 3522 |
| airborne ticks | 115 | 122 | 207 | 210 | 206 | 202 | 213 |

Notes on the rows: the first-jump path is identical in all seven at every tick up to the double jump (same y at dt 30, 35,
38, 40, 42, 44 wherever the double jump had not yet happened), so the takeoff position, facing and the aerial attack did
not change the flight. `…44619208` and `…d3a8d7b1` show an 11-tick up-B startup instead of 6 (vy -1.0 held for six extra
ticks); the launch that follows is the same. Four failures hit the ledge's right face while rising (x held at exactly
-1050.0, the face at -1200 plus the fighter's collision half-width, with the right-wall id 12), advanced past x -1050
only once their position was above about 2800, peaked 9 to 111 units below the top and 7 to 88 units right of the edge,
and were clamped again at -1050 on the way down. `…85c10043` also hit the face (3 ticks, y 2605-2789) but was still
rising fast enough to reach (-1200.0, 3028.9) at tick 856, where the native floor id became 0.

## 2. The strongest supported distinction

The **double-jump timing after the L1 takeoff**, and through it the height at which the up-B starts. The seven first
jumps are identical; the two landings double-jumped at dt 40 and 44 (from y 947.4 and 877.0), the five failures at dt
47, 47, 47, 50 and 61 (from y 799.0, 799.0, 699.4, 799.0 and 226.2). The up-B was started in every flight at the apex of
the jump that preceded it (vy -0.5), so its start height follows the double jump: 1789.5 and 1764.5 for the landings,
1527.5 to 1630.1 (and 1113.7) for the failures. The angled up-B then adds a fixed native rise of **+1361.3** from its
start to its apex (identical vx and vy sequences in the six angled flights, and in 27 of the 35 airborne up-Bs of all 74
L1 flights; the stick held during the flight changed nothing after the launch). A start height of at least 1638.7 is
therefore needed to reach y 3000; only the two dt-40/44 flights had it, and `…2394f859` missed it by 8.6. The seventh
flight (`…9736791a`) differs twice: a very late double jump (dt 61 at y 226.2) and a vertical up-B launch (vx -0.5, rise
+1814.2) that kept it more than 1,000 units right of the ledge.

Not distinguishing: takeoff x on L1 (2100-2632 in both groups), facing (both groups mixed), the stick pattern before the
double jump (left / up-left dominant in all seven), the delay from double jump to up-B (41-53 in both groups), and
steering during the up-B (no effect on the native trajectory). Collision geometry differs between the groups only as a
consequence of the height: the face contact at -1050 is what a rising fighter below about 2800 meets at that x.

Compact check on the other 67 L1 flights (existing data only): 24 of them started the up-B directly from the first jump
(no double jump before it; start height 627-876, apex 1989-2620), 4 started it after a double jump from 226-1166 (apex
at most 2380), and 39 had no airborne up-B. No flight anywhere started the up-B at or above 1639 and failed, and none
that started it below 1639 reached 3000 (start height vs apex over the 35 airborne up-Bs: correlation 0.915, the
remainder being the vertical-launch variant). The ordering therefore holds for the lower flights as well.

### Corrections (2026-09-28, later the same day)

Three statements above are corrected here rather than rewritten:

1. "24 of them started the up-B directly from the first jump (no double jump …), 4 started it after a double jump …,
   and 39 had no airborne up-B" used the same `jumps_used`-based flag as the census and is **wrong**. From the native
   status (`JumpAerialF/B`), the 67 other L1 flights split as: 6 aerial double jump then up-B (start heights 226-1166,
   apex at most 2380), 1 aerial double jump without up-B, **41 airborne up-B directly from the first jump**, **19
   grounded up-B from L1**. The statements about the 1639 ordering are unchanged (no flight started an up-B at or above
   1639 and failed; none below reached 3000).
2. "The up-B was started in every flight at the apex of the jump that preceded it (vy -0.5)" is **wrong**: -0.5 is the
   first value of the up-B startup's own imposed velocity sequence (-0.5, -1.0, -1.5, -2.0, -2.5, 0.0, then the launch),
   not the fighter's velocity before the press. The fighters were falling (vy -25 to -37) when the up-B was pressed.
3. The "double-jump timing" is not a free timing choice. In all seven flights the double jump occurred at the **first
   tick at which the native fighter could jump** after its first-jump aerial move: the two landings had an aerial attack
   (A at dt 1, `AttackAirB` dt 1-39 -> jump at 40; A at dt 5, `AttackAirF` dt 5-43 -> jump at 44); three failures threw an
   aerial fireball (B at dt 1-2, `SpecialAirN` dt 1/2-45/46 -> jump at 47) and one attacked late (A at dt 10, `AttackAirB`
   dt 10-48 -> jump at 50). The decomp confirms the mechanism: the aerial jump interrupt is checked from Fall / Jump /
   JumpAerial / FallSpecial / DamageFall and fires at any actionable tick with stick y >= 53 (a hold, not a tap), never
   from `SpecialAirN` or an aerial attack. The 3-7 tick gap is therefore the difference in lock length between the
   fireball (about 45 ticks) or a late attack and an early attack (about 39 ticks): the distinguishing variable is the
   aerial move chosen in the first ticks of the flight, and the "earlier double jump" is its consequence. Section 3's
   conclusion (no learning intervention justified) stands.

## 3. Does this give a concrete, testable learning intervention?

It gives a concrete, measurable variable: in this checkpoint, wall-top arrival from L1 required the double jump to be
issued at dt 40-44 of a first jump whose path is otherwise fixed, roughly three to seven ticks earlier than in the
failures, with the up-B at the double-jump apex and angled left. It does not, by itself, give a learning intervention
this addendum can justify: the difference is a few ticks of timing inside a 100-tick sequence sampled per tick, whose
only consequence in the reward is a possible left-target break about 100 ticks later, which is the credit-assignment
situation the earlier review measured and the M7o / M7m shaping attempts did not resolve; a shaping term on height or
timing would be reward tuning, not authorised and not supported by any evidence here that it would transfer. The
cheapest next check that stays offline is to read the preserved checkpoint's action probabilities at the dt 38-47 states
of these seven traces (whether the jump action is merely rare there or effectively unavailable); it is not run here.
These findings are for this checkpoint, this seed and this evaluation only; two landings are not evidence that the route
is learnable more often, and no campaign is proposed.

## 4. Backup list (independent copies required; nothing here is a backup of anything else)

All paths are under `/runs/`, ignored by Git (`.gitignore` line 120), single copies on this drive. Files elsewhere in
the same `runs/` tree (for example the intermediate `checkpoints/`) are different files, not backups.

| directory or file | contents | size |
| --- | --- | --- |
| `runs/m7p/campaign/m7p_geo4_s1/final/` | the seed-1 final checkpoint: `model.zip`, `vecnormalize.pkl`, `checkpoint.json`, `preservation_state.json` | 1.2 MB |
| `runs/m7p/campaign/m7p_geo4_s1/{run.json, experiment.toml, experiment_resolved.json, training_summary.json}` and `metrics/` | run identity, contracts and training record | 4.2 MB + 2.4 MB |
| `runs/m7p/campaign/_eval/m7p_geo4_s1/final/` | the final evaluations: `stochastic/` (evaluation.json, the 100 canonical action artifacts) 38 MB, `deterministic/` 37 MB | 76 MB |
| `runs/m7p/campaign/_clears/m7p_geo4_s1/` | crossing verification document and the two campaign replay directories | 44 KB |
| `runs/m7p/addendum/crossings/` | addendum registry results, the two raw-reply traces, facts | 0.5 MB |
| `runs/m7p/addendum/walltop_census/` | 98 raw-reply census traces, per-episode results, `census.json`, `flight_comparison.json`, logs | 40 MB |
| `runs/m7p/campaign/_matrix/` and `_control/` | the campaign's frozen analysis, measurements, state and control-check records (the decision's evidence) | 1.7 MB + 11 MB |
| `runs/m7p/addendum/counterfactual/` (added later on 2026-09-28) | the scripted counterfactual probe: 6 raw-reply traces, results, corrections, logs | 2.5 MB |
| total | | about 140 MB |

Optional, not needed for the crossing evidence: `runs/m7p/campaign/m7p_geo4_s1/checkpoints/` (intermediate
checkpoints, 34 MB). The registrations, rule, manifest, results and addenda under `docs/` and the tools under `rl/tools/`
are ordinary untracked source files. No copy was made by this addendum.
