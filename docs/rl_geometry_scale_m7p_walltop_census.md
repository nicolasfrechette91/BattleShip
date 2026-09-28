# M7p wall-top census: the seed-1 geo4 final policy's 100 recorded tick-0 episodes

Written 2026-09-28 after the crossing addendum. Question: does the seed-1 geo4 final policy reach the wall top (ledge
L0) more often than its two left-entry candidates reveal? The M7p decision (`failure_regression`, v3 selected) is
unchanged; nothing was trained and no new stochastic evaluation was run.

## 1. Existing records were insufficient

The final stochastic evaluation (`runs/m7p/campaign/_eval/m7p_geo4_s1/final/stochastic/evaluation.json`, 100 episodes,
seed 12345) stores one summary per episode under `btt_eval_metrics_v1`: break table, first left entry, left-region step
count, minimum live x, end reason. It has no per-tick position, contact or surface data; the per-episode directories hold
only the save file and an empty stdout log. The summary can rule a wall-top landing out for the 11 episodes whose minimum
x never went below -1000 (the ledge ends at x -1200) but cannot count L1 takeoffs, L0 contacts, time on L0 or departures
for the rest, and minimum x alone must not be read as a landing (x -1650 is simply the wall face stop on the main floor).
Per-tick native evidence existed only for the two addendum traces.

## 2. Registered census

Registration (write-once): [`rl_geometry_scale_m7p_walltop_census_registration.json`](rl_geometry_scale_m7p_walltop_census_registration.json);
tool `rl/tools/m7p_walltop_census.py` (outside the frozen fingerprint set, self-tested against the two addendum traces
before registration). Source artifacts: the 100 preserved canonical action artifacts (`actions.jsonl` + `metadata.json`,
hashes registered), the checkpoint hashes (`model.zip` `f7d11d76…`), the executable (`748dbad9…`) and the campaign flags
plus `SSB64_RL_TARGET_DIAG=1`. The two addendum traces were reused by hash; 98 episodes were replayed exactly on fresh
processes, one at a time, with every raw reply kept (`runs/m7p/addendum/walltop_census/replays/*/trace.json.gz`, 40 MB).

| item | registered estimate | measured |
| --- | --- | --- |
| episodes replayed / reused | 98 / 2 | 98 / 2 |
| ticks replayed | 352,800 | 352,800 |
| runtime | 13.1 min (1.67 ms per step + 2 s per process) | 12.5 min (749 s of replays), 7.0-12.0 s per episode |
| exactness | digest, consumed ticks, 0 unsent, length, break table, first left entry | 100 / 100 exact |
| leftover processes | 0 | 0 |

Counting rules (frozen in the registration): a step is grounded when the native observation says so
(`ground_air_state` 0, live fighter); its surface is the native collision line the fighter stands on
(`spatial.fighter.floor_line_id`), cross-checked against the decoded geometry (`classify_ground` must name the same line;
0 mismatches in 117,588 grounded steps). A wall-top landing is the first grounded step on line 0 (L0, x -2100..-1200,
y 3000) after an airborne segment. An L1 takeoff is an airborne segment leaving line 1 (the raised right step). Left
landings and left-target breaks come from the unchanged `btt_qualified_crossing_v1` code.

## 3. Census

| count (of 100 episodes) | value |
| --- | --- |
| episodes with a wall-top (L0) landing | **2** (`…44619208`, `…85c10043`) |
| L0 visits in total | 2 (one per episode, no hops, no second visit) |
| first-landing ticks | 2434, 868 |
| targets remaining at landing | 5, 7 |
| arrival surface | L1 in both (takeoffs at ticks 2318 and 745; jump, double jump, up-B; 115 / 122 airborne ticks) |
| grounded steps on L0 | 525, 131 |
| departures | 2 x left entry (x < -2100); none back to the right, none fell without entering |
| qualified left landing after L0 | 1 (`…44619208`, L3 at tick 3141) |
| left-target breaks after L0 | 1 (target 6 at tick 3008, same episode) |
| episodes that ever reached y >= 3000 | 2 (the same two) |
| episodes with any L1 takeoff | 52 (74 takeoffs) |
| L1 takeoff landing surfaces | L4 62, L2 5, L0 2, still airborne at the horizon 5 |
| L1 takeoffs with double jump + up-B | 73 of 74 |
| L1 takeoff apex (max y) | quartiles 989 / 1061 / 2188; 30 takeoffs in 27 episodes above 2000; 7 takeoffs in 7 episodes above 2800 |

The seven L1 flights that reached y >= 2800 (the ledge is at y 3000 and ends at x -1200):

| episode | takeoff tick | apex y | minimum x in flight | airborne ticks | contact after the flight |
| --- | --- | --- | --- | --- | --- |
| `…44619208` | 2318 | 3150.8 | -1313.7 | 115 | **L0** (wall top) |
| `…85c10043` | 745 | 3125.8 | -1462.1 | 122 | **L0** (wall top) |
| `…2394f859` | 3093 | 2991.4 | -1193.2 | 207 | L4 (main floor) |
| `…78b3dea2` | 1206 | 2959.6 | -1168.1 | 210 | L4 |
| `…d3a8d7b1` | 1887 | 2948.2 | -1159.1 | 206 | L4 |
| `…9736791a` | 3308 | 2927.9 | -319.3 | 213 | L4 |
| `…f5806b84` | 3094 | 2888.8 | -1112.2 | 202 | L4 |

These five are reported as flights without wall-top contact, from native positions; they are not landings and are not
counted as near misses in any decision sense.

### Correction (2026-09-28, later the same day)

The row "L1 takeoffs with double jump + up-B: 73 of 74" is **wrong**. The census flag `double_jump` was defined as
"`jumps_used` reaches 2 anywhere in the airborne segment", but Mario's up-B itself sets `jumps_used` to 2 when it
launches (5 ticks after the aerial onset, 1 tick after a grounded onset), so the flag is true in 74 of 74 flights and
says nothing about a double jump. Counted from the native status instead (`nFTCommonStatusJumpAerialF/B` appearing in
the segment), the 74 L1 flights split as: **13 aerial double jump then up-B** (the 7 high flights and 6 others), 1
aerial double jump without up-B, **41 airborne up-B directly from the first jump** (no double jump), **19 grounded up-B
from L1** (the segment starts with the launch). The "73 of 74 used double jump + up-B" wording should be read as
"73 of 74 used an up-B". Record: `runs/m7p/addendum/walltop_census/census_correction.json`. The per-flight `double_jump`
field in `census.json` is left as written (it is a registered output) and must be read as "up-B or double jump".

## 4. Interpretation

Wall-top **arrival** is confined to the two known episodes: 2 of 100, both from L1, both departing left, and the census
found no other L0 contact, no hop, no return to the right side and no second visit. The frequency of the first route
segment (L1 -> L0) therefore equals the frequency of a left entry in this evaluation; every wall-top landing led to a
left entry, one of which qualified. Full crossing success remains 1 of 100.

What recurs is the **attempt**, not the arrival: the policy left L1 in 52 episodes, 73 of those 74 flights used the
same double jump + up-B pattern, 30 flights in 27 episodes rose above y 2000, and five in five other episodes came within
about 110 units of the ledge height near its right end and fell back to the main floor. Whether those flights would have
made contact with a different drift is not knowable from the records and is not claimed. The ledge-standing skill is
thus a rare completion of a common manoeuvre in this one seed and one evaluation; nothing here speaks to other seeds,
to repeatability under a new evaluation, or to a clear (targets left 4 and 7 in the two episodes).

## 5. Preservation and backup status

Preserved and untouched: the seed-1 final checkpoint set (hashes re-verified against the registration), the 100 action
artifacts, the campaign verification documents and replays, the two addendum traces, and the new census traces,
per-episode results and `census.json`. Nothing was moved, deleted or overwritten.

Backup status: every one of those files lives under `/runs/`, which `.gitignore` line 120 ignores (`build-*/` ignores the
executable). They exist in one copy on this drive only. The intermediate checkpoints under `m7p_geo4_s1/checkpoints/`
are different files, not copies of `final`. Ignored files in the working tree are not an independent backup; a commit
would carry only the registration and this document. Sizes: `m7p_geo4_s1/final` 1.2 MB, the final stochastic evaluation
38 MB, the campaign clears record 44 KB, the addendum traces 0.5 MB, the census 40 MB (the whole `m7p_geo4_s1` run
directory is 72 MB). No new campaign is proposed in this document.
