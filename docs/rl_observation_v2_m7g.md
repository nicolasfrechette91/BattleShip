# RL M7g-b: structured-spatial policy observation `btt_policy_obs_v2_spatial`

Status (2026-09-23): **designed, implemented to the Phase I boundary, validated; not trained.** Phases E–J of the M7g
milestone. The controlled learning comparison (Phase K) is designed and pre-registered in
[`rl_obs_v2_experiment_proposal_m7g.md`](rl_obs_v2_experiment_proposal_m7g.md) and has not been run.

Machine-readable companions:
- [`rl_observation_v2_m7g.schema.json`](rl_observation_v2_m7g.schema.json): the v2 contract (generated from
  `rl/m7g_obs.py`, digest-checked by the unit tests), the network, and the JSON Schema of the native object;
- [`rl_observation_v2_m7g_comparison.json`](rl_observation_v2_m7g_comparison.json): every measurement of section 4;
- [`rl_observation_v2_m7g_validation.json`](rl_observation_v2_m7g_validation.json): the Phase J results, tests and
  regressions.

**Separation from M7g-a.** The two validated crossing fixtures (`rl/fixtures/m7g/`) and their capture records were not
read, replayed or used anywhere in this work. The observation modules are checked in the tests not to reference them
(`unit_isolation`). The crossing *opportunities* in section 4 are defined from collision geometry only: the raised
right step L1 around its marked corner (2100, -450) and the moving platform over its whole range. The one shared
piece is the decomp stage-source decoder, which a unit test uses to cross-check the pinned line table.

## 0. Summary

- **Native:** a new opt-in, PORT-only, read-only diagnostic `btt_spatial_v1` (`SSB64_RL_SPATIAL=1`). It reports:
  - the collision line table;
  - the moving platform's live translate and speed;
  - Mario's collision contacts;
  - the live position of every unbroken target under the M7f stable ID.

  With it off, every reply is byte-identical to the M7f record, and the native 468-row replay still ends at 446/447
  with checksum `0x93E9EFB4`.
- **Comparison:** three families were measured on native stage data.
  - A global semantic grid preserves every feature only at 150-unit cells (4×56×62). Its CNN makes a 512-sample
    minibatch forward pass about 35 times as expensive as the v1 network's (24 times the segment network's).
  - Egocentric rays never see the wall-top ledge surface from the raised right step, whatever their count or range.
  - Structured segments are exact, small and cheap.
- **Selected:** structured segments + targets, Mario-relative, fixed size.

  | key | shape | content |
  | --- | --- | --- |
  | `state` | 15 | the v1 vector, byte for byte |
  | `segment_geometry` | 32×8 | per collision segment: both vertices, closest point, velocity |
  | `segment_kind` | 32×7 | binary kind flags |
  | `target_geometry` | 10×2 | live target positions |
  | `target_live` | 10 | binary live flags |

  525 values in all.
- **Network:** the M7 control MLP (`[64, 64]`, tanh) under SB3 `MultiInputPolicy`. Only the input width changes (15 →
  525): 76,818 parameters against 11,538.
- **Cost:**
  - Environment-side throughput at N=5 with standby is 85–90 % of v1 (two measurements, section 6.4).
  - PPO update compute is about 1.4× v1's (estimate).
- **Validation:** the 15 Phase J items were checked with numerical native invariants, all PASS (section 8).

## 1. Scope and constraints honoured

- No training or fine-tuning against the game, no learning campaign, no `learn()` call anywhere in the M7g-b code.
  SB3 is used only for dummy / in-memory initialisation, forward passes, save/load and frozen evaluation.
- No gameplay, physics, collision, target, platform or controller-timing change. The native addition only reads and
  is proven equivalent (section 8).
- Unchanged:
  - reward v1 and v2 (no reward v3);
  - the Track 1 action contract `btt_s9_b8_v1`;
  - policy observation v1, which stays available and byte-identical: `v2["state"]` *is* the v1 vector.
- No route instruction, target order, TAS demonstration, gateway label or shaping, in any form.
- The non-PORT decomp is unchanged: its preprocessed view is byte-identical, by both the token-level view and MSVC
  `cl /EP`.
- No commit, push, branch or pull request. No native RNG state is inspected or compared.

## 2. Phase E — requirements analysis

### 2.1 What a human perceives

Source: the read-only camera audit (`gmcamera.c`, `sc1pbonusstage.c`), values computed from code constants [E].

- **Camera:** `PlayerFollow` on Mario (look-at = Mario + 250 up, eased at 0.3 per tick), fixed distance 9,000, pitch
  −9°, FOV 31.5.
- **Visible window on the play plane:** about 6,950 × 5,150 world units at 4:3, or about 9,250 × 5,150 with the
  port's default widescreen. It extends about 2,710 above Mario's feet and 2,440 below.
- **Stage extent:** 8,850 × 7,950 including targets. Static collision alone is 7,200 × 7,050.
- **One frame shows** about 65 % of the stage height and never both ends of the stage.
- **From the spawn:**
  - visible: targets 0, 4 and 9 (1 at the 4:3 edge, 5 partly);
  - not visible: targets 2, 3, 6, 7, 8 and the moving platform.
- **HUD:** shows only the *count* of remaining targets.
- **Pause:** a human can press START for a whole-stage map view. Track 1 has no START.

**Structured global state.** v2 therefore gives *structured global state*: every collision segment and every live
target, wherever the camera points. That is more information than one camera frame. It is comparable to a human who
has studied the pause-view map, **not** a visual equivalent of the screen. v2 contains no pixels, no camera state and
no visual-only decoration (the layer-0 set pieces at z −600 and the wallpaper have no collision).

### 2.2 What native state exposes safely

| source | what | safe to read | used by v2 |
| --- | --- | --- | --- |
| `RLObservation` (M1b) | Mario TopN position, velocities, status, ground/air, jumps, tick, targets remaining | yes (existing) | yes, as `state` |
| `btt_target_identity_v1` (M7f) | spawn / break records per stable ID | yes | no (its table is reused natively, section 3) |
| `btt_spatial_v1` (new) | collision lines, yakumono groups (platform translate / speed), Mario's collision contacts, live target positions | yes (read-only fill, guarded) | lines, platform translate / speed, live targets |
| game RNG, future animation state, camera | — | not read | no |

**Hidden collision facts** v2 must convey, all measured natively:
- one-way (pass-through) lines L2 and L19 (the platform);
- **no ledge grab anywhere** (no line has the cliff flag);
- the overhang underside L9 at y 2,700 blocks a straight climb along the wall's right face.

### 2.3 Allowed world state and where v2 carries it

| allowed item | v2 encoding |
| --- | --- |
| static collision geometry: floors, walls, ceilings | `segment_geometry` rows 0–22 + `segment_kind` type flags (floor / ceiling / wall facing +x / wall facing −x) |
| one-way property | `segment_kind[:, one_way]` (L2, L19) |
| moving-platform geometry | segment row 23 (line 19), world position = stored local vertices + live translate |
| moving-platform current position | row 23 vertices relative to Mario; absolute = relative + `state` position |
| moving-platform velocity | row 23 `vel_x, vel_y` = the translate change made by the last update (a present quantity) |
| active targets | `target_live[i]` per M7f stable ID |
| target current positions | `target_geometry[i]` (live root DObj translate relative to Mario; target 2 moves) |
| Mario's position in the representation | the origin of every relative vector; absolute TopN in `state` |

### 2.4 Excluded content, and how it is kept out

**Not in v2:**
- optimal path, preferred crossing, target order, TAS action;
- "go left" indicator, gateway / region labels (the M7g-a left-region boundary x < −2100 is not in v2);
- distance along a handcrafted route;
- future platform positions or any future game state;
- reward shaping.

**Target rows** are indexed by the stable ID, which is the stage file's descriptor order: an identity, never an order.

**Mechanical checks** (`unit_isolation`):
- the builder reads exactly three observation fields (`position_x`, `position_y`, `input_tick`) plus the native
  snapshot;
- no key or field name carries route vocabulary;
- no observation module references the crossing fixtures or calls `.learn(`.

### 2.5 Honest statement

Full global geometry **does** provide more information than the current camera view. v2 is labelled *structured global
state*.

For a single fixed stage, the *static* geometry is constant across episodes, so on its own it carries no information
the v1 position does not. Its value is representational: Mario-relative, nonlinear features such as the closest point
on each surface.

The genuinely new information is dynamic:
- *which* targets remain (v1 has only a count) and where the moving target is;
- where the platform is and how it moves (v1 carries it only implicitly through `input_tick`).

## 3. The native diagnostic `btt_spatial_v1`

### 3.1 Enabling and wire format

- **Enabling:** `SSB64_RL_SPATIAL=1`. It needs `SSB64_RL_BTT=1` and effective interactive stepping; otherwise it is
  ignored with a log line.
- **Replies:** `status` gains `"spatial_diag": true`. `observe` and `step` replies gain a top-level `"spatial"` object,
  paired with the reply's observation (same `input_tick`). The step copy is sent only when its step count matches the
  reply's `step_count`: the M7f pairing rule.
- **Line table:** only in `observe` replies, because it never changes after collision init.
- **Where it lives:**
  - fill `rlGameFillSpatial` in `decomp/src/sc/sc1pmode/sc1pbonusstage.c` (inside the existing M7f `#ifdef PORT`
    block);
  - struct and constants in `port/rl/rl.h`;
  - JSON rendering in `port/rl/rl_spatial.{h,cpp}`;
  - latch in `port/rl/rl_step.cpp`;
  - keys in `port/rl/rl_transport.cpp`;
  - capture in `port/rl/rl_observation.cpp`;
  - flag in `port/rl/rl_boot.cpp`.

| field | meaning |
| --- | --- |
| `input_tick`, `scene_active`, `live` | port stamp; the BTT-scene guard; `live` = scene active, object links populated, collision arrays present |
| `update_tic` | `gMPCollisionUpdateTic` (+1 per stage-animation update) |
| `anomaly_flags` | group / line / vertex overflow, bad group, target mismatch; 0 in every captured reply |
| `map_bounds`, `camera_bounds` | blast zone ±9,600; camera clamp ±5,000 |
| `groups[i]` | `present`, `status`, `translated` (the `mpCollisionGetVertexPositionID` rule), `translate`, `speed` (`gMPCollisionSpeeds`) |
| `fighter` | `floor/ceil/lwall/rwall_line_id`, `mask_curr` contacts, `floor_dist`, `carry` (moving-floor `vel_speed`), `coll` diamond |
| `target_live_mask`, `target_positions` | live item link ∩ M7f ID table; root DObj translate |
| `lines` (observe only) | per line: type, group, flags of the first vertex, stored vertices |

### 3.2 Safety of the fill

- **Scene guards:** the same as M7f. The BTT scene must be current, the battle state present, and the fighter link
  non-NULL (`gcEjectAll` teardown), with NULL checks on every collision array.
- **Direct array reads:** it reads the arrays directly and calls **no** collision getter, because several spin forever
  on line id −1 / −2 or a switched-off group.
- **Target handles:** they are dereferenced only for items found on the live item link.
- **Constants:** restated constants (line types, pass / cliff flags, contact bits, group statuses) are cross-checked
  against the decomp enums at compile time.
- **Shared M7f table:** the spawn/break table now records while *either* diagnostic is on (`rlTargetTableIsEnabled`,
  two gate calls in `sc1pbonusstage.c`). M7f's own outputs stay gated on `SSB64_RL_TARGET_DIAG` alone. With the
  target diagnostic on, the new build is strictly identical to the M7f `post_on` record (section 8).

### 3.3 What the native data measured

These are facts from 33 captured traces: 3 sets, 11 traces each, 28,873 replies per set (86,619 in all).

- **Line table:** identical to the pinned table and to the decomp stage-source decode. 20 lines; group 2 (line 19) is
  local to the platform DObj.
- **Platform translate:** x is always 2,700; y spans exactly 1,500 … 3,300 over a full cycle, so the standable surface
  is at 1,800 … 3,600. The largest per-update speed is 17.999.
- **Platform speed:** exactly `float32(translate_y − previous translate_y)` in every consecutive live pair, and
  `update_tic` advances by 1.
- **Phase at tick 0:** `update_tic` = 61. The platform translate is 2,150.927, rising.
- **Target 2:** always at (2,700, platform translate + 600), within one float32 ulp (maximum deviation 0.000244). The
  two animations are evaluated separately.
- **Riding the platform** (TAS ticks 176–180):
  - `position_y` equals `float32(translate + 300)` exactly;
  - Mario's carry equals the platform speed from the second grounded update on;
  - on the landing update the carry is still 0, because physics runs before the collision pass grounds him.
- **Pressing the tall wall:** a right-wall contact with line 13 (1,737 replies in one historical fall episode).
- **Live mask:** equals M7f's `remaining_mask` in all 28,873 replies with both diagnostics on.
- **Teardown reply:** no `live = 0` reply occurred. The terminal reply of a fall is still live, so the builder's
  hold-last path is covered only by unit tests.

### 3.4 Cost

**Reply sizes:**

| reply | diagnostic off | `btt_spatial_v1` on |
| --- | --- | --- |
| step (mean) | 561 B | 1,564 B |
| reset `observe` | 503 B | 4,004 B (2,441 B of it is the line table) |

The reply grows by about 1,000 B per step.

**Per worker step at N=5 with standby** (final run, section 6.4):
- the native round trip grows by 0.11 ms (JSON rendering, transfer, client parse);
- the Python wrappers grow by 0.13 ms (lean parse ~20 µs and v2 build ~35 µs in isolation, more under 10-process
  CPU contention).

## 4. Phase F — comparison of the three representation families

All numbers come from `rl/m7g_representations.py`, run on a native 3,601-snapshot trace. Target positions, platform
range and line table are native measurements. Full output: [`rl_observation_v2_m7g_comparison.json`](rl_observation_v2_m7g_comparison.json).

### 4.1 Candidates as prototyped

1. **Global semantic grid.**
   - World-aligned, extent x −4,050 … 5,250 and y −4,200 … 4,200: every segment, target box and the platform, aligned
     to multiples of 150.
   - Four uint8 channels: solid (supersampled coverage ≥ 0.5), one-way surface (static L2 + the platform at its live
     height), live target boxes (±150), and Mario (the cell of his diamond centre).
   - Encoder: SB3 NatureCNN (256 features) + the target / state vectors.
2. **Structured segments + targets** (the v2 candidate): the production builder of `rl/m7g_obs.py`.
3. **Egocentric rays.**
   - N rays from Mario's diamond centre (TopN + 190), range R.
   - Per ray: normalised distance and a hit-kind one-hot (floor, ceiling, wall, one-way, moving platform, target
     box).
   - Plus the same target / state vectors.

### 4.2 Measured fidelity

**Grid resolution** (the thin features come from the line table). Solid features show full cells across their
thickness; "on lines" means every static vertex and target box lies on cell boundaries.

| cell | C×H×W | tall wall | wall-top ledge | right-step ledge | 45° band | 150 gap: target 0 to floor | free rows above wall top | platform rows | on lines | erased |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 50 | 4×168×186 | 6 | 6 | 6 | 5 | 3 | 12 | 37 | yes | — |
| 75 | 4×112×124 | 4 | 4 | 4 | 3 | 2 | 8 | 25 | yes | — |
| 100 | 4×84×93 | 2 (+2 half) | 3 | 2 | 2 | 1 | 6 | 19 | **no** | smeared to 400 wide |
| **150** | **4×56×62** | **2** | **2** | **2** | **1** | **1** | **4** | **13** | **yes** | **—** |
| 200 | 4×42×46 | 1 | 1 | **0** | **0** | 1 | 3 | 10 | no | 45° band, right-step ledge |
| 300 | 4×28×31 | **0** | 1 | **0** | **0** | **0** | 2 | 7 | no | most solids, target gaps |

- **Minimum useful grid: 150 units.** It is the coarsest resolution that erases no thin platform, no wall and no
  ledge, keeps the 150-unit target gaps, and aligns every vertex.
- **What even that grid still costs:**
  - the platform surface and Mario's position are quantised to ±75;
  - zero-thickness one-way lines exist only as a separate channel;
  - 13,888 bytes per observation.

**Segments.**
- Exact: static vertices are integers; world vertices are formed in float32 exactly as the game forms them.
- The maximum float32 error of a relative coordinate anywhere in the ±9,600 blast zone is **0.00061 world units**.
- Nothing is quantised or erased; the one-way lines and the platform are exact segments.

**Rays** (lower = standing anywhere on L1 across the platform phases; upper = standing on the platform at 13 heights
across its range; coverage = mean fraction of the 20 lines hit, from 192 free positions).

| rays | range | ledge top L0 seen from L1 | L0 seen from the platform | wall / overhang seen from L1 | left targets seen from either | line coverage |
| --- | --- | --- | --- | --- | --- | --- |
| 16 | 2,500 | 0.00 | 0.00 | 0.00 | 0.00 | 0.086 |
| 32 | 3,500 | 0.00 | 0.00 | 0.00 | 0.00 | 0.129 |
| 32 | 5,000 | 0.00 | 0.022 | 1.00 | 0.00 | 0.166 |
| 64 | 5,000 | 0.00 | 0.033 | 1.00 | 0.00 | 0.185 |

From the step's corner, the ledge's right corner (−1,200, 3,000) lies 3,300 to the left and 3,260 above: 4,639 units
at diamond height, and above the camera's ~2,710 upward reach. From the platform's left end it is 3,300 to the left,
3,393–3,451 away over the platform's range, near the 4:3 half-width of 3,476.

Rays see the ledge top *from below* only edge-on, and never with realistic ranges. They never see the three left
targets through the wall, and they cover at most 18.5 % of the stage's lines.

### 4.3 Can each family represent both crossing opportunities?

| | lower (raised right step L1 near its corner) | upper (moving platform, all phases) |
| --- | --- | --- |
| grid 150 | yes: L1, ledge, overhang and gap all present at 2-cell thickness; the platform row moves in 13 distinct rows (±75) | yes, quantised |
| segments | yes, exact: L1 with corner (2,100, −450) as a vertex, L0, L9, L12, L13, L17 | yes, exact: row 23 at the live translate, with velocity |
| rays | **no**: L0 is never hit from L1 at any tested count or range | **mostly no**: L0 hit from ≤ 3.3 % of platform positions |

### 4.4 Measured cost

- **Build time:** per observation, in Python on this 6-thread i7 (Intel64 family 6 model 158); `rl/m7g_representations.py`.
- **Networks:** in-memory SB3 policies at `torch_threads = 1` (the M7 profile setting), random weights and inputs,
  forward passes only.
- **PPO update:** an estimate (3 × forward × 100 minibatches of 512, i.e. one PPO iteration of 10 epochs × 5,120),
  not a measurement.

| | v1 (control) | segments (v2) | rays 32 + targets | grid 150 NatureCNN + targets |
| --- | --- | --- | --- | --- |
| observation values / bytes | 15 / 60 | 525 / 2,100 | 269 / 1,076 | 4×56×62 uint8 + 45 / 14,068 |
| build per observation | — | **43 µs** (incl. ~7 µs of synthetic-snapshot setup; 70 µs in the first prototype) | 140 µs | 25 µs (static channels precomputed) |
| parameters | 11,538 | 76,818 | 44,050 | 322,994 |
| forward, batch 5 (rollout step) | 0.71 ms | 0.75 ms | 0.71 ms | 1.82 ms |
| forward, batch 512 (minibatch) | 1.65 ms | 2.38 ms | 1.85 ms | **57.5 ms** |
| PPO update compute (estimate) | 0.50 s | 0.72 s | 0.56 s | **17.2 s** |
| rollout-buffer observations (5,120) | 0.29 MiB | 10.3 MiB | 5.3 MiB | 68.7 MiB |

Timings are from the final idle-machine run. Repeated runs vary by about ±20 % for the small networks: an earlier run
measured v1 at 1.39 ms and v2 at 2.32 ms per minibatch.

For scale: one PPO iteration (5,120 transitions plus its update) takes about 4.4 s end-to-end at the measured M7
rate of 1,168.6 transitions/s. The grid would add about 17 s of update compute per iteration, roughly five times the
wall time. Segments add about 0.2–0.3 s (about +5 %).

### 4.5 Criteria

| criterion | 1. global semantic grid | 2. structured segments (selected) | 3. egocentric rays |
| --- | --- | --- | --- |
| information included | full static map, one-way surfaces, platform row, live targets, Mario cell | every collision segment (exact), kind flags, platform velocity, live targets, Mario-relative | first hits within range and angle; targets as a vector |
| information omitted | sub-cell detail (±75), platform velocity unless added as a vector | pixels / appearance; nothing geometric | everything occluded, beyond range or between rays (the ledge top from below, left targets) |
| dimensionality | 13,888 values (+45) | 525 | 269 (32 rays) |
| fixed / variable size | fixed per stage extent; another stage needs another extent | fixed 32 slots + presence flag; ≤ 32 segments per stage (Mario uses 24) | fixed, stage-independent |
| network | CNN (NatureCNN 256) + MLP heads | the v1 MLP heads, input 525 | the v1 MLP heads, input 269 |
| CPU cost | build 25 µs; training ≈ 35× v1 update compute | build ~36 µs; ≈ 1.4× update compute | build 140 µs; ≈ 1.1× |
| memory cost | 68.7 MiB rollout buffer | 10.3 MiB | 5.3 MiB |
| N=5 standby compatibility | yes (same native data); training cost dominates | yes, measured (section 6.4) | yes |
| reusability (characters / stages / versions) | characters: yes; stages: re-derive extent and resolution; versions: via the native table | characters: yes (Mario-relative; diamond in the diagnostic); stages: yes while ≤ 32 segments, else a new version; versions: native table | characters: yes; stages: yes; versions: yes |
| represents both crossing opportunities | yes, quantised | **yes, exactly** | **no** (section 4.3) |
| leaks route information | no | no | no |
| expected learning difficulty [I] | highest: CNN from sparse reward, static channels constant on one stage, Mario localised from a one-hot cell | low: exact relative features into the unchanged MLP family | low to moderate, but blind to the crossing geometry |
| implementation complexity | medium (rasteriser, CNN, image-key normalisation pitfalls) | low (implemented) | medium (ray caster, occlusion, kinds) |
| validation strategy | rasterisation vs geometry, per-feature cell counts | exact segment equality with the native table, closest-point unit cases, determinism | hit tests against analytic geometry |

## 5. Phase G — selection and the exact v2 contract

### 5.1 Selection: family 2, structured segments + targets

1. **Fidelity.** It is the only family that represents both crossing opportunities exactly (4.2, 4.3). The grid
   quantises the platform and Mario by ±75; rays cannot see the ledge top from the lower crossing area at all.
2. **A clean controlled comparison.** The network stays the v1 MLP (`[64, 64]`, tanh); only its input width changes.
   The grid would change the network family (a CNN, 28× the parameters, ~35× the update compute) and confound "better
   perception" with "different architecture".
3. **Cost.** The rollout buffer grows by 10 MiB, update compute by ~1.4× (estimate) and environment throughput falls by
   10–15 % (measured, section 6.4). The grid's cost is more than an order of magnitude higher.
4. **Honest information content.** For one fixed stage the grid's static channels are constant, so its spatial
   inductive bias has nothing to generalise over in Track 1. Segments put the stage into Mario-relative, nonlinear
   features (closest points) that an MLP can use directly.

The grid remains the documented option for a future multi-stage track where layouts vary.

### 5.2 Exact schema

`gymnasium.spaces.Dict`, key order = sorted = the SB3 `CombinedExtractor` concatenation order:

| key | shape | dtype | bounds | content | normalised |
| --- | --- | --- | --- | --- | --- |
| `segment_geometry` | (32, 8) | float32 | (−inf, inf) | per segment: `a_dx, a_dy, b_dx, b_dy, near_dx, near_dy, vel_x, vel_y` | yes |
| `segment_kind` | (32, 7) | float32 | [0, 1] | binary: `present, floor, ceiling, wall_facing_pos_x, wall_facing_neg_x, one_way, moving` | **no** |
| `state` | (15,) | float32 | (−inf, inf) | `btt_policy_obs_v1`, byte-identical | yes |
| `target_geometry` | (10, 2) | float32 | (−inf, inf) | per stable target ID: `dx, dy` of the live target centre | yes |
| `target_live` | (10,) | float32 | [0, 1] | binary: target unbroken | **no** |

**Definitions:**
- p = (`position_x`, `position_y`) of the paired observation: Mario's TopN, i.e. his feet.
- A segment is a consecutive vertex pair of a native line, in line-id order. Lines 14 and 16 have four vertices, so
  three segments each: 24 segments for the stage's 20 lines. Row 23 is the platform (line 19).
- World vertex = the stored vertex, plus the float32 group translate for a translated group (`float32` addition,
  exactly as the game).
- `a − p`, `b − p`, and `near − p = (a − p) + clamp(−((a − p)·(b − a)) / |b − a|², 0, 1) · (b − a)` are computed in
  float64 and cast once to float32.
- `vel` = the group's last-update speed (0 for static segments).

**Encoding rules:**
- **Stable ordering:** segment rows follow native line ids; target rows follow M7f stable IDs 0–9.
- **Missing / inactive:**
  - padding rows 24–31 are all zeros (`present = 0`);
  - a broken target has `target_live = 0` and `target_geometry = (0, 0)`;
  - on a teardown reply (native `live = 0`; never observed, section 3.3) the last live platform and target state is
    held and `info["spatial_stale"]` is set.
- **World coordinates:** native world units, x right, y up.
  - Stage bounds: blast zone ±9,600; camera clamp ±5,000; static extent x −3,900 … 3,300, y −4,050 … 3,000; platform
    surface y 1,800 … 3,600.
  - No fixed scaling: normalisation is VecNormalize's running statistics.
- **Normalisation:** `VecNormalize(norm_obs=True, norm_obs_keys=["segment_geometry", "state", "target_geometry"],
  norm_reward=False, clip_obs=10)`. The binary keys are never normalised: VecNormalize leaves unlisted keys untouched,
  as tested. Reward normalisation stays off.
- **Versioning:** contract id `btt_policy_obs_v2_spatial`, schema 1, contract digest
  `dcfd14b276c3d9f38f180888c132febb67ace39797bdef2aefb185e024c8c0cb`. Any change of meaning or shape is a new id.
  The builder refuses a native line table that differs from the pinned Mario table.
- **Compatibility:**
  - fresh models only; a v1 checkpoint is refused for v2 (`m7g_policy.assert_v2_checkpoint`), and SB3 refuses to load
    one onto a v2 environment (both tested);
  - v1 remains the default everywhere; nothing in the existing trainer, config or evaluator changed.

### 5.3 Static and dynamic spatial state

| part | changes during an episode | source | treatment |
| --- | --- | --- | --- |
| static segments (rows 0–22), kind flags | no | reset `observe` line table (pinned, verified) | recomputed relative to Mario every step |
| platform segment (row 23) | yes: translate every update | step `spatial.groups[2]` | world vertex from the live translate; velocity = last-update speed |
| target identity / positions | yes: breaks; target 2 moves | step `spatial.target_*` | live flag + relative position; broken → zeros |
| Mario | yes | the paired observation | the origin; absolute position in `state` |

## 6. Phase H — policy / network

### 6.1 Identity and architecture

`btt_policy_net_v2_multiinput_mlp64` (`rl/m7g_policy.py`):

- **SB3:** `MultiInputPolicy` (`MultiInputActorCriticPolicy`), `share_features_extractor=True`.
- **Extractor:** `CombinedExtractor` with no image key. Each key is flattened and the keys concatenated in key order,
  giving **525 features**; the extractor has 0 parameters.
- **Policy branch:** Linear(525, 64) → Tanh → Linear(64, 64) → Tanh → action net Linear(64, 17), the logits of
  MultiDiscrete [9, 8].
- **Value branch:** Linear(525, 64) → Tanh → Linear(64, 64) → Tanh → value net Linear(64, 1).
- **Relation to the control:** it is the M7 control network (`MlpPolicy`, `net_arch [64, 64]`, tanh) with only the
  input width changed. That is the one architecture adjustment the Dict observation strictly requires, since SB3
  rejects a Dict space under `MlpPolicy`.

### 6.2 Parameters (measured on the real game environment, `game_sb3_real`)

| module | parameters |
| --- | --- |
| features extractor | 0 |
| policy and value MLP bodies | 75,648 (2 × (525·64 + 64 + 64·64 + 64)) |
| action net | 1,105 |
| value net | 65 |
| **total** | **76,818** (v1: 11,538) |

### 6.3 Inference, memory, checkpoints

- **Inference:** 0.75 ms per 5-observation rollout step, against 0.71 ms for v1 (+0.04 ms); 2.38 ms per 512-sample
  minibatch forward, against 1.65 ms. Single-threaded torch, in-memory.
- **Training memory [E]:**
  - rollout buffer: 10.3 MiB of observations at 5,120 transitions (v1 0.29 MiB);
  - parameters and Adam state: about 0.9 MiB;
  - minibatch activations: about 1 MiB.
  All negligible against the ~1.7 GB M7 process footprint.
- **Checkpoint compatibility:**
  - v2 checkpoints are fresh;
  - `assert_v2_checkpoint` refuses any other observation space, and a v1 checkpoint cannot load onto a v2 environment
    (tested);
  - VecNormalize statistics are per key (`obs_rms` is a dict over the three continuous keys);
  - evaluation must load the v2 statistics with `training=False`.

### 6.4 Measured N=5 standby throughput impact

Source: `game_n5_standby_bench`.
- **Set-up:** 5 workers with one standby each (≤ 10 game processes, never exceeded), random Track 1 actions, no policy
  inference, no learning.
- **Arms:** 4 arms of 8,000 vector steps (40,000 transitions), in the order v1, v2, v2, v1.
- **Runs:** the final run (after the lean parse and the pure-Python builder), and an earlier run with the strict
  parse and a 34 µs builder.

| | v1 | v2 | v2 / v1 |
| --- | --- | --- | --- |
| **final run:** environment transitions/s (mean of 2 arms) | 2,046 | 1,832 | **89.5 %** |
| final run: worker native round trip per step | 0.935 ms | 1.045 ms | +0.11 ms |
| final run: worker Python wrappers per step | 0.134 ms | 0.265 ms | +0.13 ms |
| earlier run: environment transitions/s | 1,736 | 1,483 | 85.4 % |

The absolute rates differ between the runs with machine load. The relative cost is 10–15 %.

End-to-end training throughput also includes policy inference, parent-side vector overhead and the PPO update
(≈ +0.3 s per 5,120-transition iteration for v2, estimated). The **expected** end-to-end impact is about −10 to
−20 %: for example, 4.4 s per M7 iteration becomes ≈ 5.3 s if the whole rollout slowed to 85 %. It will be measured,
not assumed, in the Phase K pilot.

A possible later optimisation (not done) is a compact numeric step encoding in a future `btt_spatial_v2`. It would
cut the ~1 KB of per-step JSON rendering and parsing.

## 7. Phase I — implementation boundary

**Implemented and validated:**
- native capture (section 3);
- Python observation construction (`SpatialObservationBuilder`);
- Gymnasium compliance: `space.contains` on every observation of 33 traces and all game tests;
- stable shapes and ordering;
- deterministic repeatability;
- the wrapper above `Track1PolicyWrapper`;
- the M7 v2 worker stack (`build_worker_env_v2`, `M7gWorkerFactory`), including standby promotion;
- SB3 initialisation, forward passes, save/reload, VecNormalize key handling and frozen evaluation, both in memory
  and on the real game.

**Not implemented:**
- The trainer / config / evaluator integration (`rl/experiment_config.py` observation choices, `rl/m7_trainer.py`
  policy / VecNormalize / contracts, `rl/m7_evaluation.py` statistics digest).

  No experiment can run without it, and it is **the unresolved choice for Phase K**:
  - route A: small behaviour-preserving hooks in the inherited files, with v1 defaults and new fingerprints only for v2
    profiles;
  - route B: a separate `m7g_trainer.py` duplicating about 400 lines.

  The read-only audit recommends route A. It changes inherited files, so it is left for the user's decision.
- No learning campaign; no `learn()` anywhere.

## 8. Phase J — equivalence and safety validation

**References.** The M7f records captured with executable `10e8e15d…`:
- `runs/m7f/_equiv/post_off`: diagnostics off;
- `runs/m7f/_equiv/post_on`: `SSB64_RL_TARGET_DIAG=1`.

**Candidate.** The M7g-b executable `1e7c62a0…`.

**What each set contains.** The TAS in three host modes, eight historical Track 1 artifacts (3,361–3,600 actions;
falls, horizons, double breaks, a deterministic collapse, random play) and the native 468-row replay.

| # | requirement | result | evidence |
| --- | --- | --- | --- |
| 1 | diagnostic / observation mode off matches M7f exactly | **PASS** | `post_off` vs M7f `post_off`: 12/12 identical, strictly (every key, JSON type, status, result, `host_frame`) |
| 2 | policy observation v1 byte-identical | **PASS** | replies identical (1); v1 constants pinned (`unit_contract`, M5 `policy_observation`); `v2["state"]` bytes == v1 in all 86,619 offline v2 observations and every wrapper step |
| 3 | authoritative TAS trajectory identical | **PASS** | native 468-row replay in all five sets (off, target diag, spatial, spatial + target diag, repeat): exit 0, COMPLETE 447/446, checksum `0x93E9EFB4`; stepping TAS 447 actions, 21 unsent |
| 4 | reward v1 and v2 identical | **PASS** | every observation field identical, so both rewards are identical (TAS returns 19.553 / 19.553 under both); M5 / M7b reward regressions (section 9) |
| 5 | target identity identical | **PASS** | spatial + target diag vs M7f `post_on`: 12/12 identical with `targets` compared (not ignored); live mask == `remaining_mask` in 28,873 replies |
| 6 | tick timing identical | **PASS** | consumed ticks, step counts and action digests identical in every comparison; first action consumes tick 0 |
| 7 | visible / no-render / Raphnet-bypass equivalent | **PASS** | TAS in `normal`, `no_render` and `no_render_raphnet` identical to M7f per mode, and v2 identical across the three modes (9 TAS runs, one chain) |
| 8 | cold / standby equivalent | **PASS** | `game_standby_v2`: cold-start and standby-promoted episodes of 3,600 actions give identical v2 observations (reset included); M7c standby suite (section 9) |
| 9 | no reset action consumed | **PASS** | the v2 re-observe is non-consuming: equal observation, step count 0; first step `consumed_tick` 0 in cold and promoted episodes |
| 10 | no process / thread / port leaks | **PASS** | every capture and test ends with zero BattleShip processes; ≤ 10 processes in the N=5 bench; M7c / M7 smoke cleanup cases (section 9) |
| 11 | user configuration unchanged | **PASS** | `BattleShip.cfg.json` sha256 `1b29d91b…` before and after every capture set and suite |
| 12 | non-PORT preprocessing unchanged | **PASS** | `m7f_nonport_view` token view identical to HEAD (`54c5afc7`) and to pre-M7f (`91d7b6b7`), sha `98bbf64d…`; MSVC `cl /EP` translation units identical, 18,123 lines, sha `fa4c7346…` |
| 13 | historical artifacts untouched | **PASS** | section 9: whole-`runs/` fingerprint before vs after; the M7g-a fixtures' sha256 unchanged |
| 14 | observation-v2 data deterministic | **PASS** | 3 capture sets: 9 TAS runs identical; each artifact identical across 3 repeats; wrapper v2 == offline v2 on a separate process; cold == promoted |
| 15 | spatial data depicts the required world | **PASS** | numerical invariants below |

**Item 15, what the numerical invariants check:**
- **Tall wall:** rows 13 and 17 are exactly x −1,800 (y −2,550 … 2,700) and x −2,100 (y −2,850 … 3,000), with wall
  kinds. Unit case: Mario at (−1,650, 0) gives the closest point (−150, 0). Natively, the wall contact names line 13.
- **Lower crossing region:** row 1 is L1 (2,100 … 3,300, −450), with the marked corner (2,100, −450) as its first
  vertex. The ledge L0, the overhang L9 and its tip L12 are exact.
- **Moving platform:**
  - row 23 = local ±600 + translate, one-way, moving, with the velocity equal to the native speed;
  - the speed equals the translate difference exactly;
  - on-platform `position_y` equals the surface;
  - the carry equals the speed.
- **Upper crossing region:** L0 at y 3,000 with the platform surface reaching 3,600 (above the ledge top for about 116
  of every 300 updates).
- **All ten targets:**
  - static targets are at their native positions exactly;
  - target 2 is at the platform + 600 (≤ 0.000244);
  - the live mask equals M7f's;
  - broken rows are zero.
- **Mario:** the origin of every relative vector; `state` position bytes are identical to v1.

## 9. Tests and regressions

All results are in [`rl_observation_v2_m7g_validation.json`](rl_observation_v2_m7g_validation.json).

| suite | command | result |
| --- | --- | --- |
| observation v2 | `python rl/m7g_obs_tests.py` | **12/12 PASS** (8 unit, 4 game) |
| equivalence | `python rl/m7g_equivalence.py compare\|validate` | 5 × 12/12 identical; 0 problems in 86,619 replies |
| M7g-a crossing fixtures | `python rl/m7g_tests.py` | **18/18 PASS** |
| M1–M7f permanent chain | `python rl/m7f_regressions.py` | **25/25 PASS** (23 suites + `git diff --check` in parent and decomp) |
| historical integrity | whole-`runs/` fingerprint (82,984 files) before vs after | identical: 0 removed, 0 changed, 0 mtime changes; 283 files added by test runs |
| M7g-a fixtures | sha256 before vs after | both unchanged |

**Notes on the runs:**
- The first run of the regression chain was cut off by a power outage after 17 suites (all PASS); it wrote no results
  file. It was re-run in full.
- The user configuration's sha256 stayed `1b29d91b…` throughout. Its mtime changes from `m7_smoke` onwards, as in every
  earlier record: an inherited suite runs a process with cwd `build-us/Release`, which rewrites identical bytes.

The M7g-a suite's game cases replay recorded non-fixture sequences. The validated fixtures' files are only read and
checked.

The M1–M7f chain covers:
  - M7f unit + game;
  - non-PORT `cl`;
  - M7e / M7d unit + existing suites, M7c standby, M7b config + smoke, M7 smoke;
  - M6 equivalence + Raphnet;
  - M5 (including the pinned v1 policy vector), M4, M3, M2;
  - native 468-row TAS, M1e 447-action replay (default and diagnostic), M1d transport.

  Every training case stays excluded.

## 10. Limitations

- **Mario only.** The contract is specific to Mario's Break the Targets (pinned line table, 24 segments). Another stage
  needs a new contract version, but the native diagnostic is generic (caps 4 groups / 32 lines / 4 vertices, with
  overflow flags).
- **Global state.** v2 is structured global state, not visual equivalence. It does not model what the camera shows.
- **Untested teardown path.** The hold-last path for a teardown reply is exercised only synthetically; no captured
  reply had `live = 0`.
- **Learning is unmeasured.** "Expected learning difficulty" is an inference. Nothing was trained, so v2's effect on
  learning is unknown until Phase K.
- **Estimates vs measurements.** Throughput is measured environment-side with random actions. The end-to-end cost with
  PPO updates is an estimate. PPO update times are estimates from forward passes; no backward pass was run.
- **No trainer integration.** Section 7: needed before Phase K.
- **Sources of some numbers.** The camera window numbers come from code constants, not a rendered measurement.

## 11. Files

**Parent repository (all uncommitted).**

New:
- `rl/m7g_spatial.py`, `rl/m7g_obs.py`, `rl/m7g_policy.py`, `rl/m7g_representations.py`, `rl/m7g_equivalence.py`,
  `rl/m7g_obs_tests.py`;
- `port/rl/rl_spatial.h`, `port/rl/rl_spatial.cpp`;
- `docs/rl_observation_v2_m7g.md`, `.schema.json`, `_comparison.json`, `_validation.json`;
- `docs/rl_obs_v2_experiment_proposal_m7g.md`.

Modified: `port/rl/rl.h`, `rl_boot.cpp`, `rl_observation.cpp`, `rl_step.cpp`, `rl_transport.cpp`.

**Decomp submodule (uncommitted, branch `rl-main`).** Modified: `src/sc/sc1pmode/sc1pbonusstage.c` (PORT-only).

**Commit order.** The parent calls `rlGameFillSpatial`, which only the edited decomp defines:
1. commit the decomp change on `rl-main` and push it to the user's fork (`origin`);
2. commit the parent's `decomp` gitlink **alone**;
3. commit the parent's `port/rl` + `rl/` + docs, with the M7g-a files as their own commit.
