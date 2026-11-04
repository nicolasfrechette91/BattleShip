# Glitch candidates for Mario's Break the Targets (2026-11-04)

Cloud session, branch `cloud/2026-11-04-glitch` (from `main` at `9afcaf6`). Offline only: the game was never run, no ROM was
available, the game code was only read. Decomp pinned at `e4f0634`; paths below are relative to `decomp/` unless they start
with `port/`, `rl/`, `tools/` or `docs/`.

**Purpose.** This record lists the mechanisms in the decompiled code that could produce something glitch-like in Mario's Break
the Targets. It is meant for **detecting and explaining** what the agent does. It proposes no route and no input sequence.
On purpose, it states no stage coordinate where a mechanism applies. The local script (section 4) names places, for review
only. None of it should become a reward, goal, curriculum or action prior.

**Evidence labels.**

- [code]: read in the decomp at the cited line.
- [data]: read in the decomp's relocData C source. The decomp builds byte-identically, so these are the ROM's bytes. For the
  stage geometry they also equal the native line table recorded by the port (`docs/rl_observation_v2_m7g.md` §3.3; a test
  here checks them against the m7g fixture).
- [measured here]: computed in this session (scripts in `tools/glitch/`).
- [inferred]: my reasoning from the code. It was not observed in the game.
- [unverified]: needs a local run.

## Short answer

- **Collision is a swept point test, so speed alone cannot tunnel through a line** [code]. Each tick, the floor test sweeps
  the diamond's bottom point from its previous position, the ceiling test sweeps the top point, and the wall tests sweep the
  side point, the bottom and the top. Each sweep is checked against every line segment. A crossing is found at any speed.
  Sub-stepping starts only above 250 units per tick on one axis. The largest per-tick velocity change recorded for Mario is
  226.9 (a Super Jump Punch launch from rest, `docs/frs_anomaly_inventory_2026-10-16.md` §3.2), so Mario always runs one
  step.
- **A clip can only come from the gaps of that scheme** [code, inferred]:
  - the diamond's edges are not swept, only its vertices; at the end of a step, each edge is tested only against the walls
    that face it, and never against floors or ceilings (M5);
  - snaps applied after the wall tests are never re-tested in the same step (M6, M8);
  - two opposing contacts are resolved in a fixed order (M2);
  - the grounded path has no ceiling test (M4);
  - **once the diamond's centre is inside a solid, no test pushes it out until it leaves through a face** (M3). Every test
    only catches a point that enters a line from its face side.
- **On this stage, most easy clip preconditions are absent** [data, measured here]:
  - the line order matches what the early exits assume (M1);
  - no passage is narrower than the diamond (M2), no floor-to-ceiling gap is lower than the diamond (M4), and no solid is
    thinner than the spacing of the diamond's swept points (M3);
  - no line can be grabbed as a ledge;
  - no static line lies in the moving platform's path (M7);
  - the PORT byte-swap layout is word-aligned (M12);
  - no floor is shorter than 40 units (M8b).

  What remains: 13 convex corners where lines end, 2 convex bends inside lines (M5), two pass-through lines (M9), the
  floor-end teleports (M8), and the snaps (M6).
- **Most plausible "glitch-looking" observations, ranked** [inferred]:
  1. the floor-end teleport (teeter snap, M8);
  2. target hits that look impossible (swept hitboxes, square-cornered boxes, no line-of-sight check, M11);
  3. falls through a pass-through line, or relative motion on the moving platform (M9, M7);
  4. snap discontinuities (M6).

  These are original-game mechanics. A genuine wall, ceiling or floor clip needs a contact within float error of a corner
  (M5), or a snap that lands the diamond inside a line (M6). I rate both low on this stage.
- **D1 needs two corrections** [code, data, measured here]:
  - **Mario's fireball hitbox never reaches the host trig.** Its offsets are zero, so `wpProcessUpdateHitOffsets` is skipped.
  - **Mario's Super Jump Punch does reach it.** `ftphysics.c:430` calls a bare `cosf` on the TransN rotation, which comes
    from the stick. The 11-03 review lists that site as "not Mario".

  For the agent's stick values (±80 and 0), libultra `__cosf` gives the correctly rounded result. So D1 can affect the
  restricted agent through this path only if ucrt rounds those two inputs differently. `tools/glitch/transn_cos_check.c`
  decides it in one run (section 5).
- **Detection**: section 3 gives the per-tick signal of each mechanism, the read-only native fields that would make each
  test exact, and the event format (`btt_glitch_event_v1`). `tools/glitch/detect.py` implements the trace-based part.

## 1. Collision map

### 1.1 Representation

- **Line table** [code: `src/mp/mptypes.h`, `src/mp/mpdef.h`]:
  - **Vertices**: integer `s16` positions, plus `u16` flags per vertex. In the flags, `0x4000` = pass-through (one-way),
    `0x8000` = ledge-grabbable, and the low byte is the material.
  - **Lines**: runs of vertex ids.
  - **Groups**: `MPLineInfo`, one per yakumono group, gives `(first line id, count)` for each kind: floor, ceiling, right
    wall, left wall.
- **Face sides** [code: tests below]:
  - floor: up;
  - ceiling: down;
  - `lwall`: faces −x. It is hit by a fighter moving right, through the diamond's right vertex.
  - `rwall`: faces +x.
- **A segment's flags are the flags of its first vertex** (`mpcollision.c:400-403` and the sweep loops).
- **Tables the game derives at load** [code: `mpcollision.c:3547-3696`]:
  - per line, a near bound and a far bound (`coll_pos_*`): the min/max of y for floors and ceilings, of x for walls;
  - edge links to the line at each end, found by **shared vertex index** (not by coordinates);
  - the line kind, from the group ranges.
- **Moving groups**: their lines are stored in group-local coordinates. Every test subtracts the group's DObj translation,
  and the "Diff" variants also add the group's last per-tick speed to the previous position (`mpcollision.c:1042-1202`).
- **This stage** [data: `src/relocData/124_GRBonus1MarioFile2.c:330-399`, `271_GRBonus1MarioMap.c`]:
  - 20 lines: 6 floors, 5 ceilings, 5 right walls, 4 left walls;
  - 2 of the floors are pass-through: one static, and one that is the only line of moving group 2;
  - two wall lines have 4 vertices, with 45° segments;
  - static lines close into **two solid polygons** [measured here];
  - no line carries the ledge flag;
  - death bounds ±9600, camera bounds ±5000.

  Two corrections to `docs/frs_anomaly_inventory_2026-10-16.md` §1.2. The recorded types are 6/5/5/4, not "10/5/4/1" (they
  match the m7g native table). `flags` 16384 is `0x4000`, the pass-through bit. The native record keeps only each line's
  first-vertex flags (`src/sc/sc1pmode/sc1pbonusstage.c:924`). That is exact on this stage, where only first vertices carry
  flags.

### 1.2 Mario's collision body and speeds

- **Diamond** [data: `src/relocData/203_MarioMain.c:274-275`]: `map_coll` = top 320, centre 190, bottom 0, half-width 150,
  relative to the TopN position. The ledge-catch box is (400, 360). Every trace records the same four values (inventory
  §1.2).
- **Attributes** [data, same file]: dash 54, run 44, air maximum x 30, fall terminal velocity 44 (fast fall 70), gravity
  2.4 per tick.
- **Super Jump Punch**: its velocity comes from the animation's TransN motion. It reaches about 216 to 227 units per tick
  (inventory §3.1 to §3.2). It goes through `cosf` and `__sinf` of the TransN z rotation (section 2, M13).

### 1.3 Order inside one tick

`ftMainProcPhysicsMap` (`src/ft/ftmain.c:1875-2060`) [code]:

1. `pos_prev` = TopN (`:1890`).
2. Unless the fighter is in hitlag, physics adds `vel_air` (plus damage velocity).
3. `pos_diff` = new − previous (`:1943`).
4. If grounded on a line of a moving group, the group's speed (carry) is added (`:1945-1950`).
5. **The death check runs before collision**: TopN against the map bounds (`:1952`, `src/ft/ftcommon/ftcommondead.c:579-680`).
6. The status's map proc runs `mpProcessUpdateMain` (`src/mp/mpprocess.c:399-465`). It resets to `pos_prev` and splits the
   motion into `int(max(|dx|, |dy|) / 250) + 1` steps when any axis exceeds 250 (`:423-427`). Carry and push are applied in
   step 0 only (`:448`). The collision proc then runs once per step.
7. The slope contour (foot IK, `:1982`; `src/mp/mpcommon.c:365-409`).
8. Hitbox world positions (`:2000-2050`). On the first frame, a hitbox is a point. After that it is the segment from the
   previous frame's position to this frame's (`pos_prev` → `pos_curr`).

The item process tests targets against those hitboxes (`src/it/itprocess.c:750`, `:984`).

**Grounded proc** `mpCommonRunFighterAllCollisions` (`src/mp/mpcommon.c:166-223`) [code]:

1. Left-wall test and clamp, then right-wall test and clamp. Each sets `is_coll_end`, so a wall hit ends the remaining
   steps.
2. Floor follow (`mpprocess.c:915-985`): snap to the current floor at the new x. Past a floor end, an inner-corner wall
   stops the fighter at the end (x snap, `:972`); otherwise the fighter leaves the floor.
3. Floor-edge adjust.
4. Teeter (`CLIFFEDGE`) or stop-edge (`STOPEDGE`), per the status.
5. A swept floor test against the other floors (`:987-1029`).

**There is no ceiling test on the ground.**

**Airborne proc** `mpCommonRunFighterSpecialCollisions` (`src/mp/mpcommon.c:475-582`) [code]:

1. Left wall, then right wall (both with corner rules).
2. Ceiling, plus the ceiling-edge adjust.
3. Swept floor, with the pass rule and the status callback.
4. Landing snap.
5. Ledge catch.

**No test is repeated after any snap in the same step.**

### 1.4 The tests and their tolerances

- **Swept points** [code: `mpprocess.c:467-575` ground, `:1132-1383` air].
  - Floors: bottom point only.
  - Ceilings: top point only.
  - Walls: side point, bottom and top, each swept from the previous diamond to the current one. Then two **static** edge
    tests at the end position: bottom→side and top→side, on the side that faces the wall kind (right edges for left walls,
    left edges for right walls).
  - So each diamond edge is tested only against the walls that face it. A floor or ceiling that crosses an edge is never
    tested.
- **Direction** [code].
  - A flat floor is hit only by downward motion (`mpcollision.c:974`); a flat ceiling only by upward motion (`:1478`); a flat
    wall only by motion toward its face (`:1798`, `:2339`).
  - Sloped segments use the "Tilt" tests (`:758`, `:1263`, `:1901`, `:2407`). These need the start on, or within 0.001 of,
    the face side.
- **Tolerances** [code].
  - The flat tests (`:1204-1261`, `:2189-2247`) accept a start up to 0.001 behind the line and need the end strictly behind
    it. The crossing must lie inside the segment's span, with **no** tolerance.
  - The Tilt tests use 0.001 on the y span of a floor but **none on its x span** (`:817`). The same asymmetry holds on the
    other axis for walls.
  - The getters accept a position within ±0.001 of a line's ends and clamp it (`:362`, `:491`).
  - Vertices are integers. A float ulp at |x| between 2048 and 4096 is 2.4e-4, so 0.001 is about 4 ulps at this stage's
    coordinates.
- **Early exit** [code: `:949-955`, `:1453-1459`, `:1773-1779`, `:2314-2320`]. A loop over one group's lines of one kind stops
  at the first line wholly past the sweep (`goto l_break`). That is safe only if the lines are sorted: floors and right walls
  by descending far bound, ceilings and left walls by ascending near bound. Also, the bounds are stored at a running index
  (`:3594-3597`) that equals the line id only if ids are laid out group by group and kind by kind.
- **Resolution** [code].
  - Walls: up to 5 hit lines are collected. The nearest clamp is chosen with a vertex rule: a wall vertex inside the
    diamond's height pushes the diamond until its edge passes through that vertex (`mpprocess.c:577-688`, `:649-675`). Only
    x is clamped.
  - Floors and ceilings: y snaps to the line. When the fighter is past a line's end:
    - a landing snaps x to the floor end (`mpProcessSetLandingFloor`, `:2089-2119`, `:2112`);
    - a ceiling hit sets y to the end vertex's height unconditionally, and x only at an inner corner
      (`mpProcessRunCeilCollisionAdjNew`, `:1939-1993`, `:1982-1986`).

### 1.5 Corners, ledges, platforms

- **Corners** [code].
  - In the air, a wall test also counts a side-point crossing of a ceiling or floor whose end joins a wall of the same
    facing as a hit on that wall (`mpprocess.c:1252-1380`). Pass-through floors are excluded (`:1333`).
  - The ceiling-edge and floor-edge adjusts slide the diamond off a wall next to a line end (`:93-214`, `:216-381`).
  - The grounded wall tests ignore the wall joined under the current floor's end (`:482`, `:706`).
  - **All of these rules follow edge links, which join lines by vertex index.** Two lines that touch at equal coordinates
    through different indices get no corner handling. The script checks for this.
- **Ledges** [code, data].
  - A ledge catch needs the `0x8000` flag (`mpprocess.c:1031-1130`). No line here has it, so **Mario can never grab a ledge
    on this stage** (as `docs/rl_observation_v2_m7g.md` §2.2 also states).
  - Floor ends have two teleports instead (M8): the teeter snap (`mpcommon.c:24-97`), and the stop-edge snap of the grounded
    fireball (`src/ft/ftchar/ftmario/ftmariospecialn.c:60`).
- **Pass-through lines** [code].
  - They are landed on only from above with downward motion.
  - Dropping through sets `ignore_line_id` (`src/ft/ftcommon/ftcommonpass.c:29`), which every status change resets
    (`ftmain.c:4759`).
  - The Super Jump Punch descent lands on them only while `stick_y >= -44` (`src/ft/ftchar/ftmario/ftmariospecialhi.c:99-108`).
- **Moving platform** [measured: m7g]: group 2, x always 2700, y 1500 to 3300, at most 17.999 per tick.

### 1.6 Targets

- **Break** [code]: a target is an item (`nITKindTarget`). It breaks in `itTargetCommonProcDamage`
  (`src/it/itground/ittarget.c:37-50`).
- **Hurtbox** [data, code]: a box of half-extent 150 on each axis (300 × 0.5: `src/relocData/253_ITBonus1ObjectHeader.c:21`,
  `src/it/itmanager.c:382-384`). It is centred on the item's translation.
- **Test** [code: `src/gm/gmcollision.c:700-817`].
  - Normally, the hitbox's centre **path** (previous → current) is clipped against the box. The box is grown **per axis** by
    the hitbox radius (`:715`), so the corners are square: at a corner, the reach is radius × √2.
  - On a hitbox's first frame, the test is a point test (`:719`).
  - There is **no line-of-sight test**.
- **Hitbox positions** [code, data].
  - Fighter hitboxes ride the joint matrices, which use the `lbCommonSin`/`lbCommonCos` lookup table (`gmcollision.c:34-60`,
    `src/lb/lbcommon.c:335-371`). They are the same on every platform.
  - The fireball's hitbox is the weapon's position: its offsets are zero (`src/relocData/204_MarioSpecial1.c:32`;
    `src/wp/wpprocess.c:45-53`, `:66-75`). Its radius is 100 (size 200 × 0.5, `src/wp/wpmanager.c:215`).
  - The fireball's launch uses libultra `__cosf`/`__sinf` (`src/wp/wpmario/wpmariofireball.c:201-202`).

## 2. Candidate mechanisms, by plausibility for Mario with 8 directions + neutral and one button per tick

"Platform" means: whether the outcome can differ between N64, Windows (MSVC) and Linux builds for the same inputs.

| rank | id | mechanism | plausible here | platform |
| --- | --- | --- | --- | --- |
| 1 | M8 | floor-end teleports (teeter snap ±40, stop-edge snap) | high (ordinary mechanic; looks like a teleport) | same |
| 2 | M11 | target hit geometry (swept path, square-cornered box, no line of sight, path spans snaps) | high (looks like an impossible hit) | same, except via M13 |
| 3 | M9 | pass-through lines and relative motion on the moving one | high (looks like falling through a floor) | same |
| 4 | M6 | snaps after resolution, never re-tested in the same step | moderate as a discontinuity, low as a clip | same |
| 5 | M7 | moving-group frame, carry and tick bookkeeping | moderate as an oddity, low as a clip | same |
| 6 | M5 | a convex corner or bend between the swept points; float-edge contacts | low (the most plausible entry for a real clip here) | same |
| 7 | M3 | free motion once the centre is inside a solid | follows M5 or M6 only; large effect if reached | same |
| 8 | M13 | D1 host trig in the Super Jump Punch velocity | trajectory difference only; likely none for 8 directions | Windows only |
| 9 | M14 | PORT-only float thresholds (foot IK) | very low | PC vs N64 |
| 10 | M10 | out of bounds | only as a consequence | same |
| — | M1 | early exit or running index skips a line | absent on this stage | same |
| — | M2 | narrow passage: opposing contacts, the last push wins | absent on this stage | same |
| — | M4 | grounded path without a ceiling test | absent on this stage | same |
| — | M12 | PORT byte-swap of the geometry arrays | absent on this stage | PC only |
| — | M8b | uninitialised floor distance on floors shorter than 40 | absent on this stage | stack contents: PC vs N64 |

### M8: floor-end teleports [code; plausibility inferred]

- **Where**:
  - `mpCommonCheckSetFighterCliffEdge`, `src/mp/mpcommon.c:24-97`. The decomp comments the assignment at `:86`: "This is
    what causes the infamous Dream Land teleport".
  - `mpCommonCheckSetFighterEdge`, `:99-164`.
  - They are used by 15 grounded statuses' map procs (Wait, walking, landings and others, `src/ft/ftcommon/ftcommonstatus.h`)
    and by the grounded fireball (`ftmariospecialn.c:60`).
- **How**: a grounded update leaves the current floor past one of its ends. If the fighter faces that end and the stick does
  not push away hard, the position is **set** to the end ± 40 units on the floor (`:47`, `:67`, `:86`). The condition is
  `stick_x > -60` at a left end, or `< 60` at a right end. With the restricted inputs, that means stick 0 or toward the
  inside. The jump equals the overshoot past the end plus 40, in one tick. The stop-edge variant snaps to the end vertex
  itself.
- **Conditions**: a grounded status with these map procs; reaching a floor end while facing it. Any mismatch between the
  floor id held at the start of the update and the actual position turns into a longer teleport.
- **M8b** [code]: the getter result at `:49` and `:69` is not checked. On a floor narrower than 40, `floor_dist`, `flags` and
  `angle` stay uninitialised, so the teleport reads stack garbage. That differs between builds (review D7). No floor here is
  narrower than 40 [measured here], so M8b is absent.
- **Platform**: same on all builds (M8b aside).

### M11: target hits that look impossible [code; plausibility inferred]

- **Where**: `src/gm/gmcollision.c:700-817` (test), `:1443-1453` (fighter against item), `:1923-1943` (weapon against item),
  `src/it/itprocess.c:750`, `:984`.
- **How**: four properties make a legitimate hit look wrong:
  1. The hitbox centre's whole path since the last frame is tested, so a fast limb or projectile hits a target that neither
     endpoint overlaps.
  2. The box is grown per axis, so corner hits reach radius × √2.
  3. Nothing checks for walls in between: a box crossing a wall line can be hit from behind that wall.
  4. The path uses last frame's position even across a teleport (M6, M8): the segment spans a distance the body never
     travelled.
- **Conditions**: an active hitbox or a fireball near a target box (half-extent 150, plus the hitbox radius).
- **Plausibility**: high as an *observation*. The inventory's long-range breaks were fireballs (§3.4). None of this is a
  glitch in the game's terms.
- **Platform**: same, except through M13. Positions use the lookup-table trig; the fireball's offsets are zero.

### M9: pass-through lines [code]

- **Where**: `mpcollision.c:974` (downward only), `mpprocess.c:2029` (pass and ignore rule), `:1333`,
  `ftmariospecialhi.c:99-108`.
- **How**:
  - Rising through a pass line is free.
  - Landing needs downward motion relative to the line, so on the moving platform it is computed in the platform's frame.
    If the platform rises faster than Mario falls, Mario does not land, and the platform passes through him.
  - The Super Jump Punch descent ignores pass lines while `stick_y < -44`: with the restricted inputs, while the stick
    points down or diagonally down.
- **Plausibility**: high, and by design. The detector counts pass-line crossings and does not raise them as events.
- **Platform**: same.

### M6: snaps after resolution [code; clip plausibility inferred]

- **Where**:
  - landing x-snap to the floor end: `mpprocess.c:2089-2119`, at `:2112`;
  - ceiling y set to the end vertex, and x at inner corners: `:1939-1993`, at `:1982`, `:1986`;
  - floor-follow end snap: `:972`;
  - inner-corner snap of a "projected" floor contact: `:2121-2177`;
  - ceiling-edge and floor-edge adjusts: `:93-214`, `:216-381`;
  - air order: walls, then ceiling, then floor (`mpcommon.c:475-582`).
- **How**: each snap moves the diamond after the wall tests of the same step, and nothing tests the new position again. A
  snap whose target puts a vertex, or the centre, behind another line completes a clip if the centre ends up behind it (M3).
- **Conditions**: a landing, or a ceiling hit, whose end position lies past the line's end. That happens when the swept
  contact is near a line end and the step's motion carries on. A clip also needs another solid line within one step's
  motion of that end.
- **Plausibility**: the snaps themselves are frequent; the inventory's "ledge clamp" and "wall-blocked" events are
  ordinary snaps. As a clip: low here.
- **Platform**: same.

### M7: moving group [code]

- **Where**: `mpcollision.c:1042-1202` (Diff variants), `mpprocess.c:448` (carry in step 0 only), `:461`,
  `mpcollision.c:3889-3892` (`gMPCollisionUpdateTic`, advanced once per frame by the ground process,
  `src/gr/grdisplay.c:226`), `ftmain.c:1945-1950`.
- **How**:
  - When the platform has moved since the fighter's last collision update, the tests shift the fighter's previous position
    by the platform's last per-tick speed.
  - The carry is the platform speed, added only while grounded on its line.
  - The order of the ground process and the fighter process within a tick decides which variant runs.
  - Inventory §3.5 row 5 recorded a zero carry on a status-change tick while the fighter still moved with the line.
- **Conditions**: standing on, landing on, or leaving the platform's line.
- **Plausibility**: moderate for oddities. Low for clips: no static line lies in the platform's travel band grown by the
  diamond [measured here, with the m7g range].
- **Platform**: same.

### M5: convex corners and bends between the swept points [code; plausibility inferred]

- **Where**: the tests in §1.4. The corner rules: `mpprocess.c:1252-1380` (air), `:93-381` (edge adjusts), `:649-675` (wall
  vertex rule).
- **How**: only vertices are swept. At a convex corner, a diagonal approach can bring the corner inside the diamond between
  the bottom point and the side point (or between the side point and the top point):
  - walls entering that way are caught by the two static edge tests at the end of the step;
  - floors and ceilings are caught only by the corner rule of the air wall test.

  So with walls taller than the diamond's edge, a clean 90° corner is handled [inferred from the code]. What remains is
  float-level:
  - the flat tests have no tolerance on the crossing's span, while the start side gets 0.001;
  - the Tilt tests have no tolerance on one axis;
  - the getters clamp at ±0.001.

  A sweep that passes within a few ulps of the corner vertex can miss both lines of the corner, and the static edge test
  then decides. The 135° bends inside the two 45° wall lines go through the Tilt tests and the vertex rule.
- **Conditions**: a diagonal motion whose swept point passes within about 1e-3 of a convex corner or bend, and a static edge
  test that also misses.
- **On this stage** [measured here]:
  - 13 convex corners at line ends, plus 2 convex bends;
  - every corner links by vertex index; none touches through a different index;
  - no corner has inconsistent normals.
- **Plausibility**: low. It is the most plausible genuine clip entry here, and searches that seek razor-thin contacts are
  exactly what finds it.
- **Platform**: same for the same floats. Through M13, an analog Super Jump Punch could shift those floats by an ulp.

### M3: free motion inside a solid [code-derived; inferred]

- **How**: every test catches a point only as it enters a line from the face side. Inside a solid:
  - a fighter moving right meets the far `rwall`'s back, and right walls are only hit by leftward motion;
  - falling meets the solid's ceiling line from above, and ceilings are only hit by upward motion;
  - the static edge tests look only for walls that face the diamond, and a solid's own faces point away from a centre that
    is inside it.

  So once the centre is inside, the fighter moves freely. When it leaves through any face, the edge tests push it out on that
  side.
- **This is the "completion" of a clip, not an entry.** Entry by thinness would need a solid thinner than the swept-point
  spacing: 190 between bottom and side, 130 between side and top, 150 sideways. There is none on this stage (both solids are
  at least 300 thick) [measured here].
- **Plausibility**: only after M5 or M6. Large effect if reached.

### M13: D1 host trig [code, data, measured here]

- **Super Jump Punch**:
  - `ftmariospecialhi.c:66-97` calls `ftPhysicsApplyAirVelTransNAll` on airborne frames (`:75`, `:81`);
    `ftPhysicsGetAirVelTransN` then multiplies the animation velocity by `cosf(TransN.rotate.z)` (bare; `ftphysics.c:430`)
    and by `__sinf` (libultra; `:431`). The grounded frames use `ftPhysicsApplyGroundVelTransN` (`:168`), which uses no
    trig.
  - `ftMarioSpecialHiProcInterrupt` (`ftmariospecialhi.c:19-63`) sets `TransN.rotate.z = -DTOR((stick_x ∓ 50) × 0.6)` when
    `|stick_x| > 50` (`ftmario.h:8-10`).
  - On MSVC, the bare `cosf` is ucrt: the decomp's `#pragma weak` is ignored (`CMakeLists.txt:674-688`).
- **Measured here** (`tools/glitch/transn_cos_check.c`, GCC 13 and Clang 18, glibc host), on every rotation the stick can
  produce (`|stick_x|` 51 to 80, plus 0):

  | input set | libultra = correctly rounded | libultra = glibc |
  | --- | --- | --- |
  | `stick_x` = ±80 (the agent's only non-zero x) | 2 of 2 | 2 of 2 |
  | `stick_x` = 0 (rotation 0, cos = 1) | 1 of 1 | 1 of 1 |
  | analog 51 to 79, both signs | 48 of 58 (1 ulp off at ±54, ±63, ±72, ±76, ±77) | 48 of 58 |

  [Unverified]: the ucrt column. If ucrt is correctly rounded at the two ±80 inputs, this path gives the restricted agent
  identical velocities on Windows and N64. Also [unverified]: whether the Super Jump Punch animation keys its own TransN
  rotation. The interrupt only raises the magnitude (`:40-45`), so animation-keyed rotations would add other inputs. Logging
  `TransN.rotate.z` (§3.2) settles it.
- **The fireball is not on the D1 path**, a correction to review D1:
  - `wpProcessUpdateHitOffsets` (`src/wp/wpprocess.c:13-22`) runs only for non-zero offsets (`:45-53`, `:66-75`), and Mario's
    fireball offsets are zero (`204_MarioSpecial1.c:32`). The rotation it applies is the pitch (`rotate.z`), not the spin
    (`rotate.x`).
  - The launch uses `__cosf`/`__sinf`. Rebounds use `lbCommonReflect2D` (no trig).
  - The fireball's bare-trig call (`syVectorRotateAbout3D`, `wpmariofireball.c:154`) runs only on shields and reflectors,
    which do not exist in BTT.
- **No other bare `sinf`/`cosf` on Mario's BTT path** [code: grep of `src`]: the remaining callers are other characters'
  moves, items, the menus, audio, the camera and display matrices.
- **Platform**: Windows only; plus FP contraction on AArch64 (review D11).

### M14: PORT-only float thresholds [code]

- **Where**: `src/ft/ftparam.c:2846-2860`. A PORT `#ifdef` replaces an exact `== ±1.0` gimbal check with `|v| >= 0.9999` in
  the two-bone IK (`func_ovl2_800EBD08`). The slope contour runs that IK on Mario's feet (`mpcommon.c:386`, `:398`), after
  collision and before the hitbox positions are taken.
- **Reach**: when grounded with foot contouring on and the IK within about 0.8° of the singular pose, foot-attached hitboxes
  can sit differently on PC than on N64.
- The other PORT thresholds (`gmcollision.c:305-330`, `:592`) are on grab and clank paths that BTT never runs.
- **Plausibility**: very low. **Platform**: PC (both OSes) vs N64.

### M10: out of bounds [code]

- **Where**: the death check uses TopN against ±9600 **before** collision (`ftmain.c:1952`, `ftcommondead.c:579-680`). The
  camera bounds are ±5000.
- **Effect**: a falling Mario is a failed episode. Nothing out of bounds helps a clear. Out of bounds appears here only as
  the consequence of M3 (free motion in a solid, then a fall).

### Absent on this stage (preconditions checked, not met) [measured here]

- **M1**: the early-exit order and the running-index layout both hold for every group and kind (`mpcollision.c:949-955`
  etc., `:3594-3597`).
- **M2**: no horizontal gap between facing walls is under 300, and no vertical gap under 320. Opposing contacts in one update
  (left wall, then right wall: the last clamp wins and can leave the centre in a solid) cannot occur from static geometry.
- **M4**: no floor-to-ceiling clearance is under 320, and no static line is in the moving platform's band. With no ceiling
  test on the ground (`mpcommon.c:166-223`), such a gap would put the top point past a ceiling, and a later jump would not be
  stopped.
- **M12**: every array the PORT build fixes up is word-aligned, and no word is rotated twice
  (`mpcollision.c:4127-4258`; `port/bridge/lbreloc_byteswap.cpp:1009-1022`). The m7g native table also equals the decomp
  decode.
- **M8b**: every floor spans at least 40 units.

## 3. Detection

### 3.1 Signals per mechanism

All signals compare consecutive live ticks t−1 and t in the trace, plus the line table recorded at tick 0.

| id | observable signal in a burst | fields needed | in today's traces | in `detect.py` |
| --- | --- | --- | --- | --- |
| M5, M2, M3 | a swept diamond point (bottom, side, top, centre) ends more than 0.01 behind a solid line it was in front of, with the crossing inside the segment, measured in the line's group frame. The detector reports how close the crossing is to the corner. | position, ECB, lines, group translation | yes | `line_crossing` |
| M3 | the centre (TopN + centre height) is inside a closed solid polygon; one event per run of ticks | same | yes | `inside_solid` |
| M6, M8 | position change minus the velocity prediction (inventory §3.1 predictor) above 1 unit, classed as wall clamp, ceiling clamp, landing, take-off, status change, moving line, **edge snap** (x equals a floor end or the end ± 40) or **unexplained** | velocities, carry, mask, floor id, status, hitlag | yes | `position_snap` (edge and unexplained by default; `--all-snaps` for all) |
| M6, M7, M9 | grounded on both ticks, with the floor id changing to a line that shares no endpoint | floor id, ground/air | yes | `floor_switch_unlinked` |
| M10 | TopN enters the death or the camera bounds | position, bounds | yes | `beyond_map_bounds`, `beyond_camera_bounds` |
| M11 | a target bit clears without plausible geometry: no fighter path within body reach of the box while an attack flag or fireball status is on, and no weapon path within weapon radius; or every plausible hitter's straight path to the target crosses a solid line | target mask and positions, attack flag, weapons | yes (reach is approximate: hitbox positions are not logged) | `break_without_plausible_hitter`, `break_through_solid` |
| M13 | events within 30 ticks of a Super Jump Punch status (ids 225/226, `rl/data/m7n_action_classes_v2.json`) with `|stick_x| > 50` get tagged | status, stick | yes | `platform_sensitive: ["d1_transn_cosf"]` on any event |
| native | a non-zero `anomaly_flags` in spatial, entity or targets | as recorded | yes | `native_anomaly_flag` |
| M1, M12 | static checks on the table (no per-tick signal) | the ROM table | — | `glitch.py analyze`, `compare` |

What the traces cannot show:

- the pre-resolution position (to tell "the game moved me here" from "a test missed");
- the hitbox geometry;
- `mask_stat`, which separates the teeter snap (`FLOOREDGE`) from the other snaps;
- the TransN rotation (the D1 input).

The wall and ceiling line ids are last-contact ids, not current contacts (inventory §2).

### 3.2 Where to log, without changing behaviour

A read-only addition to the existing post-update capture `rlGameFillSpatial` (`src/sc/sc1pmode/sc1pbonusstage.c:797-1000`,
PORT-only, env-gated like `SSB64_RL_SPATIAL`), under a new contract (for example `btt_contact_v1`). Everything below is read
after `ftMainProcPhysicsMap` and written nowhere in the game:

- from `fp->coll_data`:
  - `pos_prev`, `pos_diff` and `vel_speed`, so the candidate position = `pos_prev + pos_diff + vel_speed` can be compared
    with the resolved TopN;
  - `mask_prev`, `mask_curr`, `mask_stat` (`FLOOREDGE` = teeter snap) and `mask_unk` (the air wall-contact bits);
  - `line_coll_dist` (the last swept-hit point);
  - `floor_flags`, `ceil_flags`, `lwall_flags`, `rwall_flags` and the four angles;
  - `ewall_line_id`, `cliff_id`, `ignore_line_id`, `is_coll_end`;
  - `update_tic` against `gMPCollisionUpdateTic` (which tells a Diff update from a Same one);
- `fp->joints[nFTPartsJointTransN]->rotate.vec.f.z`, the D1 input;
- `fp->attack_colls[i]`: `attack_state`, `pos_prev`, `pos_curr` and `size`, for active slots;
- each weapon's `attack_coll.attack_pos[i]` (prev and current) and `size`;
- once per run: the target `damage_coll` offset and size.

About 40 floats and 16 integers per tick. With them, every test in §3.1 becomes exact:

- a clip is a resolved displacement that crosses a solid line while no contact bit names that line;
- a target hit can be re-run with `gmCollisionTestRectangle`'s own arithmetic.

Send the block in the transport reply, not in `ssb64.log` (review D8).

### 3.3 Anomaly event format (`btt_glitch_event_v1`, one JSON object per line)

```json
{
  "schema": "btt_glitch_event_v1",
  "event_id": "16 hex: sha256 of geometry, trace, kind, step, evidence key",
  "kind": "line_crossing | inside_solid | position_snap | floor_switch_unlinked | beyond_map_bounds | beyond_camera_bounds | break_without_plausible_hitter | break_through_solid | native_anomaly_flag",
  "mechanisms": ["M5", "M2", "M3"],
  "step": 412, "step_from": 411, "step_to": 412,
  "input_tick": 413, "consumed_tick": 412,
  "score": 3.7, "threshold": 0.01,
  "source": {"trace": "...", "run_folder": "...", "n": 0, "cid": 0, "k": 0, "words_digest": "..."},
  "geometry_sha256": "...", "ecb": [320, 190, 0, 150],
  "fighter": {"prev": {"step": 411, "pos": [0, 0], "vel_air": [0, 0], "ga": 1, "status": 0, "floor": -1, "lwall": -1,
                       "rwall": -1, "ceil": -1, "mask_curr": 0, "carry": [0, 0], "hitlag": 0},
              "curr": {"...": "same fields at step"}},
  "evidence": {"kind-specific": "line id, segment, swept point, depth, distance to the corner; or class and residual; or hitters"},
  "platform_sensitive": ["d1_transn_cosf"],
  "detector": {"name": "tools/glitch/detect.py", "version": 1},
  "needs_replay": true
}
```

What the explorer should keep:

- every event, append-only, in its run folder (for example `glitch_events.jsonl`, next to `dispatches.jsonl`), with:
  - `source` filled from the dispatch: `run_folder`, `n`, `cid`, `k`, the words digest and the parent chain, so the replay
    browser can replay from tick 0;
  - the build identity (executable sha256 and platform);
- events never gate, rank, reward or select anything (they are passive);
- a `needs_replay` event becomes a finding only after a tick-0 replay reproduces it, on the same build and, for
  `platform_sensitive` events, on the other build.

I did not touch the explorer. `glitch.py detect` takes the `source` fields from the trace and its path today.

## 4. The tools (`tools/glitch/`)

- **`extract`**: reads the ROM's reloc table (US at `0x1AC870`, 2132 files; JP at `0x1ACAF0`, 2107 files, the constants of
  `tools/generate_yamls.py`).
  1. It decodes the map header file (US 271; JP looked up as `GRBonus1MarioMap` in `yamls/jp`).
  2. It follows the header's `map_geometry` extern pointer to its file and offset (US: file 124 at `0x20E8`), using the
     extern file-id trailer of `src/lb/lbreloc.c:169-205`.
  3. It decodes VPK0 and checks that every geometry pointer is on the file's intern relocation chain.
  4. It parses `MPGeometryData`, derives the game's tables exactly as `mpcollision.c:3547-3696` does, and reads the header
     bounds.
  5. It cross-checks the file offsets against `yamls/<version>/*.yml`, the geometry against the decomp-source decode, and
     the bounds against `271_GRBonus1MarioMap.c`.
  6. It writes `logs/glitch/geometry_<version>.json`.

  Byte orders z64, v64 and n64 are handled.
- **`compare`**: diffs that table against a trace's native `initial.spatial.lines`: kinds, groups, vertices and first-vertex
  flags. A difference would be a PC-only geometry bug (M12).
- **`analyze`**: runs the M1 to M12 checks: order, running index, PORT swap layout, degenerate segments, short floors,
  corners and bends, unlinked touches, solids, passages, thickness, pass lines, ledge flags, the moving band, target boxes
  against lines, and bounds. It writes JSON and Markdown that **name places**.
- **`detect`**: §3.1 over one or more traces.

**Tested here** (`python -I tools/glitch/test_glitch.py`: 36 tests, all pass, in under a second):

- VPK0: round trip of the test encoder for both sample methods. The same streams through torch's own C decoder
  (`torch/lib/libvpk0/vpk0.c`, compiled at test time) agree byte for byte.
- A synthetic ROM in all three byte orders, built from the decomp-source geometry: the reloc table at the US address, file
  124 compressed with an intern chain, and the map header with an extern chain and its file-id trailer. Extraction
  reproduces the decomp decode exactly. A geometry pointer missing from the chain is refused.
- The decomp decode equals the m7g native fixture's line table, line by line.
- Each analysis check on crafted geometry with a known answer.
- Each detector event on synthetic traces, plus no event on a clean trace, and no crossing while riding a moving floor.
- The CLI end to end, on the synthetic ROM.
- `transn_cos_check.c` built and run with GCC 13 and Clang 18.

**Not tested** (needs your machine):

- the real ROM bytes: the table address, file ids 124 and 271, the extern trailer, and Nintendo-encoded VPK0 streams (the
  decoder matches the C decoder torch already uses on that ROM, but only on streams from my encoder);
- JP extraction;
- real lab traces: the format is taken from `port/rl/*.cpp` and the readers in `rl/`;
- the MSVC build of `transn_cos_check.c`;
- the thresholds of `detect.py` (1 unit snap, 0.01 crossing, 500 body reach) against real data.

## 5. What to run locally

From the checkout root in Git Bash, with the decomp submodule checked out. Outputs land in the Git-ignored `logs/glitch/`.
Nothing here starts the game.

```bash
git fetch origin cloud/2026-11-04-glitch
```

```bash
git worktree add ../BattleShip-glitch origin/cloud/2026-11-04-glitch
```

```bash
cd ../BattleShip-glitch && git submodule update --init decomp
```

1. Tests. Expect `Ran 36 tests ... OK`; the C-reference VPK0 test is skipped if no `cc` is on the PATH.

   ```bash
   python -I tools/glitch/test_glitch.py
   ```

2. Extraction. Expect four `OK` lines (two yaml offsets, geometry equal to the decomp, bounds equal), then `20 lines` and
   exit code 0. A `FAIL` line means my ROM-layout assumptions are wrong somewhere: send me the output.

   ```bash
   python -I tools/glitch/glitch.py extract --rom /c/path/to/baserom.us.z64
   ```

3. ROM table against the table the port loaded. Expect `SAME`. Pick any `*.json.gz` under a lab `run/traces/` folder.

   ```bash
   python -I tools/glitch/glitch.py compare --geometry logs/glitch/geometry_us.json --trace /c/BattleShip_lab/crossing_2026-10-15/run/traces/<one trace>.json.gz
   ```

4. Candidate map, for review only (it names places). The trace adds the platform range and the target boxes.

   ```bash
   python -I tools/glitch/glitch.py analyze --geometry logs/glitch/geometry_us.json --trace /c/BattleShip_lab/crossing_2026-10-15/run/traces/<one trace>.json.gz
   ```

5. Detector over the existing traces. The splice probe has the most varied ticks and the only recorded falls. Then read
   `logs/glitch/events_splice.summary.json`: counts per kind and per snap class.

   ```bash
   python -I tools/glitch/glitch.py detect --trace-dir /c/BattleShip_lab/splice_probe_2026-10-14/run/traces --out logs/glitch/events_splice.jsonl
   ```

6. D1 on the Super Jump Punch, in an **x64 Native Tools Command Prompt for VS** at the checkout root. Expect `host: MSVC ...`
   and a last line `... on the 8-direction inputs (|stick_x| = 80): 0 of 2` if ucrt agrees with libultra there. Send me the
   output either way: any `ulp=1` row with `stick ±80` is a Windows-only trajectory difference for the current agent.

   ```bat
   mkdir build-glitch
   cl /nologo /O2 /fp:precise /c /D_LANGUAGE_C /DF3DEX_GBI_2=1 /DPORT=1 /DNON_MATCHING=1 /DNON_EQUIVALENT=1 /DAVOID_UB=1 /Idecomp\include /Idecomp\src /Fobuild-glitch\ decomp\src\libultra\gu\cosf.c
   cl /nologo /O2 /fp:precise /Fobuild-glitch\ /Febuild-glitch\transn_cos_check.exe tools\glitch\transn_cos_check.c build-glitch\cosf.obj
   build-glitch\transn_cos_check.exe
   ```

   The first `cl` may warn `C4068: unknown pragma 'weak'`. That warning is the D1 mechanism itself.

## Appendix: session record

- **Read**:
  - `decomp/src/mp/*`, the Mario, item, weapon, hit-test and death files cited above;
  - `port/rl/rl_spatial.cpp`, `rl_entity.cpp`, `rl_targets.cpp`, `port/bridge/lbreloc_byteswap.cpp`, `CMakeLists.txt`;
  - `docs/frs_anomaly_inventory_2026-10-16.md`, `docs/rl_observation_v2_m7g.md`;
  - `REVIEW_2026-11-03.md` and `MORNING_RUNBOOK.md` from `origin/cloud/2026-11-03` (read with `git show`, not checked out).
- **Initialised in the cloud checkout only**: the `decomp` and `torch` submodules, at their pinned commits. Their pointers
  are unchanged; nothing in them was modified.
- **Not touched**: `rl/`, `port/`, `decomp/` sources, `tools/frs/`, the explorer, `main`.
- **Added**: this file and `tools/glitch/` (8 files).
- **Checks**:
  - `python -I tools/glitch/test_glitch.py` → 36 tests OK;
  - `git diff --check` clean;
  - `transn_cos_check` with GCC 13 and Clang 18 → `differ: 10 of 61 inputs; on the 8-direction inputs (|stick_x| = 80): 0 of 2`.
