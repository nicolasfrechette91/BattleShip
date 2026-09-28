# M7p addendum: count correction and one bounded scripted counterfactual probe (diagnostic only)

Written 2026-09-28. The M7p decision (`failure_regression`, v3 selected) is unchanged. Every modified trajectory below is
a **scripted counterfactual probe**: not a learned crossing, evaluation success, demonstration, curriculum prefix or
training start, and never counted as any of those. Registration (write-once):
[`rl_geometry_scale_m7p_counterfactual_registration.json`](rl_geometry_scale_m7p_counterfactual_registration.json); tool
`rl/tools/m7p_counterfactual_probe.py`; records under `runs/m7p/addendum/counterfactual/` (`runs/*/trace.json.gz` with
every raw reply, `runs_summary.json`, `results.json`, `probe_correction.json`, logs). Fixtures and TAS were not read;
native RNG was not inspected; the checkpoint was not loaded.

## 1. Counting discrepancy resolved

The census said "L1 takeoffs with double jump + up-B: 73 of 74"; the flight comparison said "24 of the other 67 skipped
the double jump". **Both were wrong, for the same reason**: the flag `double_jump` was "`jumps_used` reaches 2 anywhere in
the airborne segment", and Mario's up-B sets `jumps_used` to 2 itself when it launches (aerial onset + 5 ticks, grounded
onset + 1). The flag is true in 74 of 74 flights. Counted from the native status (`nFTCommonStatusJumpAerialF/B`):

| the 74 L1 flights | count |
| --- | --- |
| aerial double jump, then up-B | 13 (the 7 high flights + 6 others) |
| aerial double jump, no up-B | 1 |
| airborne up-B directly from the first jump, no double jump | 41 |
| grounded up-B from L1, no double jump | 19 |

The correction is preserved in `runs/m7p/addendum/walltop_census/census_correction.json` and as dated correction
sections in the census and flight-comparison documents; `census.json` itself is left as registered.

Two further corrections surfaced while checking the native transitions: the "-0.5" velocity at the up-B press is the
first value of the up-B startup's own imposed sequence, not the fighter's velocity (the fighters were falling at -25 to
-37); and the "double-jump timing" is not a free choice: in all seven high flights the double jump fired at the first
tick the fighter could jump after its first-jump aerial move (aerial attack ending at dt 39 / 43 for the two landings,
aerial fireball ending at dt 45 / 46 or late attack ending at dt 48 for the failures).

## 2. Registered probe

**Causal question.** In the failed angled flights, does issuing the second jump earlier, with the rest of the recorded
sequence unchanged, raise the up-B start height and produce a valid L0 landing: (a) with the up-B input tick unchanged,
which lengthens the jump-to-up-B interval by the same amount, or (b) with the up-B press moved by the same amount, which
keeps the interval? The two are registered as separate variants; jump timing and up-B delay are not claimed to be
isolated from each other.

**Limitation found before running.** The registered "earlier timings derived from the observed gap" (3 to 7 ticks)
cannot be realised by an isolated edit in any of the four failures: the second jump already came at the first tick the
native fighter could jump. `…78b3dea2` and `…f5806b84` have no actionable tick before their jump (fireball to dt 46,
jump at 47): no valid isolated edit exists and no variant was run for them. `…2394f859` (Fall at dt 46, jump at 47) and
`…d3a8d7b1` (Fall at dt 49, jump at 50) allow exactly one tick. Reaching dt 40 to 44 would require removing 17 to 20 B
presses (no fireball) and would re-time the jump by the residual stick sequence, a different manoeuvre, which was not
substituted.

**Edits** (every other tick unchanged and submitted to the episode's end through the one-native-tick interface; stick x
never changed; the button at the jump tick is a hold of B, so no up-B is triggered there):

| variant | source | edits (dt after takeoff) | ticks changed / unchanged |
| --- | --- | --- | --- |
| V1 | `…2394f859` | dt 46 stick y 0 -> 80 (L -> UL); up-B tick 97 unchanged (interval 50 -> 51) | 1 / 3599 |
| V2 | `…2394f859` | V1 + dt 95 button B -> none, dt 96 button L-trigger -> B (fresh B one tick earlier; interval kept 50) | 3 / 3597 |
| V3 | `…d3a8d7b1` | dt 49 stick y 0 -> 80 (R -> UR); up-B tick 91 unchanged (interval 41 -> 42) | 1 / 3599 |
| V4 | `…d3a8d7b1` | V3 + dt 89 button B -> none, dt 90 button L-trigger -> B (interval kept 41) | 3 / 3597 |

Controls: unmodified replays of both sources. Cap 4 variants, no adaptive search, no additional attempts (the tool
refuses a second run). Registered before running: the expectation that (a) gains about nothing and (b) about +30, and
that a landing also depends on x clearance and contact.

**Native rule correction.** The registration described Mario's aerial jump as "stick y >= 53 held". That is the
Kirby / Jigglypuff multi-jump rule. Mario's second jump (`ftCommonKneeBendGetInputTypeCommon`) requires stick y >= 53
**and** `tap_stick_y` <= 3, i.e. the stick must have entered the up range (>= 20 from below) within the last three
ticks, or a jump-button tap. Recorded in `probe_correction.json` before the results were interpreted; no variant was
added or changed because of it.

## 3. Results (6 runs, 7.0 to 7.2 s each, 0 leftover processes)

Both controls were exact (digest, consumed ticks, length, break table equal to the recorded evaluation; no divergence).

| | source `…2394f859` | V1 | V2 | source `…d3a8d7b1` | V3 | V4 |
| --- | --- | --- | --- | --- | --- | --- |
| native second jump | dt 47, y 799.0, vx -29.8, `JumpAerialF` | **none at dt 46 or 47**; a jump at dt 87 (y -917.8) after a later re-tap | same as V1 | dt 50, y 699.4, vx -29.8, `JumpAerialB` | **dt 49**, y 735.0, **vx +29.8**, `JumpAerialF` | same jump |
| up-B onset dt / y | 97 / 1630.1 | 97 / -383.7 | 96 / -433.5 | 91 / 1586.9 | 91 / 1595.5 (+8.6) | 90 / 1622.5 (+35.6) |
| interval jump -> up-B | 50 | 10 | 9 | 41 | 42 | 41 |
| apex (x, y) | -1193.2, 2991.4 | -1164.7, 977.6 | -1155.1, 927.8 | -1159.1, 2948.2 | -239.1, 2956.8 (+8.6) | -222.6, 2983.8 (+35.6) |
| ledge-face contact (x -1050, wall id 12) | 1 tick falling | none | none | 2 ticks | none | none |
| y >= 3000 over the ledge | never | never | never | never | never | never |
| valid L0 landing | no | no | no | no | no | no |
| landing | L4 at 3301 | L4 at 3273 | L4 at 3271 | L4 at 2094 | L4 at 2089 | L4 at 2088 |
| divergence from source | (control exact) | tick 3140 (dt 47) | tick 3140 | (control exact) | tick 1936 (dt 49) | tick 1936 |

What happened. V1 / V2: the source held the stick up-left through dt 42 to 45 during the fireball and dipped it to left at
dt 46; that dip is what re-armed the tap for the jump at dt 47. Raising stick y at dt 46 kept the stick up without a new
entry into the up range, the three-tick tap buffer had expired, and no jump fired at dt 46 or 47; the A press at dt 48
then started an aerial attack and the fighter fell to y -918 before a later re-tap jumped at dt 87. These two variants
did not produce an earlier second jump and do not test the hypothesis. V3 / V4: the stick had entered the up range at dt
48, so the jump fired one tick earlier as intended and the fighter was 35.6 higher at the jump. The up-B then started 8.6
higher with the press tick fixed (one more falling tick ate most of the gain) and 35.6 higher with the press moved; the
apexes rose by the same amounts, to 2956.8 and 2983.8, both below the ledge top. The jump also took the source's
rightward stick at dt 49, so its horizontal velocity was +29.8 instead of -29.8 and the apex sat about 940 units right
of where the source's apex was; the fighter never came near the ledge or its face.

## 4. Conclusion

**Earlier jump timing improved height but was insufficient** in the two trajectories where a one-tick-earlier second
jump could be isolated (+8.6 with the up-B tick fixed, +35.6 with the up-B moved; both apexes still below 3000), and it
cost the horizontal approach because the only earlier actionable tick carried a rightward stick. In the other two
failures no isolated earlier jump exists, and in the two `…2394f859` variants the one-tick edit produced no jump at all
because of the tap-buffer rule. The 3 to 7 tick "gap" to the landings is the lock length of the first-jump aerial move,
not an independently movable timing, so it could not be tested as registered. Nothing here shows that PPO could learn
a correction; the probe is a diagnostic on four recorded trajectories of one checkpoint. No reward, observation,
training or campaign change follows from it.

## 4b. Jump-input audit (code only, added later on 2026-09-28)

Record: `runs/m7p/addendum/counterfactual/jump_input_audit.json`. No native run, no probe, no contract change.

**Both native jump paths.** Mario's ground jump (`ftCommonKneeBendCheckInterruptCommon`) and aerial second jump
(`ftCommonJumpAerialCheckInterruptCommon`, `jumps_used == 1`) share one input function,
`ftCommonKneeBendGetInputTypeCommon`, which accepts either of two paths: the **stick path** (stick y >= 53 and
`tap_stick_y` <= 3, i.e. the stick entered the up range within the last three ticks) or the **button path**
(`ftCommonKneeBendCheckButtonTap`: `button_tap` masked with all four C buttons). `button_tap` is computed in `ftmain.c`
as `(hold ^ previous hold) & hold`, a press edge on that tick only: a held C button never re-triggers, and there is no
buffer on the button path. The three-tick buffer is a property of the stick path alone and is not generalised to
button jumps. The "held stick or held C button" rule belongs to Kirby and Jigglypuff's multi-jump function only.

**What the contract exposes.** `btt_s9_b8_v1` has one button per tick from {none, A, B, C-up (8), C-left (2), L, R, Z}.
C-up and C-left are both in the native jump mask; C-down and C-right are not exposed. A C button and B cannot be held on
the same tick, so a C-button tick releases B.

**Which path the recorded flights used.** Over the 74 L1 takeoffs, the first jump came from the stick in 50, from a
C-button tap in 2, and 22 were grounded up-B launches with no jump squat. Over the 14 genuine aerial second jumps, 11
used the stick path, 2 used a C-button tap (`…6d9afb13` dt 3 and `…51b5967a` dt 1, stick not up), and 1 had both. **All
seven high flights, the two landings included, used the stick path** (`tap_stick_y` 1 to 3 at the jump tick); none used
a C button there. The policy does use C buttons (C-up in 5.6 %, C-left in 2.1 % of the 357,472 recorded actions).

**Did the probe overlook an available C-button input? Yes.** The contract exposes it and the probe's registration
considered only the stick edit. For `…2394f859`, a C-up or C-left at dt 46 (B held from dt 45, so the C press is a fresh
edge) would have produced the second jump at dt 46 by the button path with the stick kept left (jump velocity -29.8),
without the tap-buffer condition that defeated V1 / V2. It is not side-effect-free either: releasing B at dt 46 turns
the source's B at dt 47 into a fresh tap with the stick up (y 80 >= 40), which is an up-B input, so a second button edit
at dt 47 would be needed (two button ticks, no stick change). For `…d3a8d7b1`, a C-up at dt 49 (B held from dt 48)
would have jumped without touching the stick, but the aerial jump's horizontal velocity follows stick x, which the
source holds right (+80) at dt 49, so the horizontal loss seen in V3 / V4 would remain. For `…78b3dea2` and
`…f5806b84` nothing changes: the lock is the status, not the input path. These edits are described, not run.

## 5. Preservation

Frozen decisions, evidence, code fingerprints and the checkpoint hashes are unchanged (re-verified). New files: the
registration and this document under `docs/`, the probe tool under `rl/tools/`, and 2.5 MB of probe records under
`runs/m7p/addendum/counterfactual/` (Git-ignored like everything under `/runs/`, single copy on this drive; add it to the
backup list of the flight-comparison document). No commit, push, branch, PR or video.
