# Crossing bottleneck (2026-10-14)

## 0. Status, scope, sources and method

**Status: offline, read-only investigation; zero native ticks.** No game, lab command, suite or launcher was started. Nothing under
`rl/`, `tools/`, `port/`, `runs/`, `C:/BattleShip_lab/` or on D: was created, modified or deleted. The only new files are this record and the
Git-ignored working files under `logs/frs_crossing/` (scripts in `scripts/`, outputs beside them). Checkout
`C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, branch `main`, HEAD = `origin/main` = `d10c1a8`, clean with nothing staged at the start.
The TAS, every human recording, the owner's run and any external time were not read or used. This record proposes mechanisms for the
owner's decision; it decides nothing and launches nothing.

**Data.** The lab import of the sd2 archive (`C:/BattleShip_lab/import/archive`: 21,323 bursts, 49,928 cells, 42,657 events; import
manifest `98f07e6c3f16`'s sources), the imported reference clear (the 1,885 route, trace and actions), and the splice probe's
candidates and results (`C:/BattleShip_lab/splice_probe_2026-10-14/`). The v4 selection masses were computed with the committed lab
reader exactly as `logs/frs_step4/census.py` does (`LabArchive.read_import`, E6 off, bound L <= 1,860, `lab_probabilities()`); they
reproduce the census (level 7: 11.38 %, 3,750 cells; crossing band 1.281 %, 386 cells). `runs/` was not needed.

**Definitions.** Level = targets broken; every level-7 cell has the same live mask (the three left targets), so the crossing is
required from every level-7 state. A level-7 "success" is a burst dispatched from a level-7 cell whose reaches include a level-8 cell (the
analysis's 14 of 4,734). The reach ticks stored in the ledger are absolute ticks; the offset inside a burst is tick minus the burst's
start L. A dispatch's exact start state is the pinned representative's own win record (recovered for all 4,734 level-7 dispatches).

**Descriptive stage labels (analysis only, never in code).** The crossing in the record goes from the moving platform (floor line 19,
x 2,400 to 3,100) over the top of the stage to the wall top (floor line 0, x about -1,730, y 3,000), then left of the wall (x < -2,100,
the cell contract's boundary) to target 6 at (-3,300, 3,300). Level-7 states are labelled by where they are: `low` (y < 2,700, anywhere
right of the boundary), `launch` (x >= 1,200, y >= 2,700: at or right of the platform, high), `x600` (600 <= x < 1,200, high),
`mid-flight` (x < 600, y >= 2,700, right of x -1,200), `edge` (-2,100 <= x < -1,200, y >= 2,700: airborne just right of the boundary,
above the wall top), `WT` (grounded on the wall top), `LEFT` (x < -2,100). The labels name regions of Mario's stage so the findings can be
read; no mechanism below uses them.

## 1. The 14 successes against the 4,720 failures

### 1.1 None of the 14 crossed anything: all started past the wall

Level-7 dispatches: 4,734 (rd1 308, rd2 1,543, rd3 1,537, rd4 502, sd1 433, sd2 411). Start stages: 4,536 right of the boundary (of
which 3,691 `low`, 630 `launch`, 71 `x600`, 118 `mid-flight`, 26 `edge`), 8 `WT`, 190 `LEFT`. Ends: 3,950 by length, 784 by a fall.
Breaks: 14 (target 6 seven times, target 8 four, target 1 three).

| it | session | stage | L | position (x, y) | velocity (vx, vy) | facing | status | jumps used | class | target at offset (tick) | runs to the break | cell chosen / seen |
| --- | --- | --- | ---: | --- | --- | ---: | --- | ---: | --- | --- | ---: | --- |
| 10819 | rd4 | edge | 1,723 | (-1,801, 3,133) | (-29.8, +65.3) | -1 | 210 attack_air | 1 | A2 | 6 at +115 (1,838) | 20 | 3 / 13 |
| 11512 | rd4 | LEFT | 1,860 | (-2,551, 1,794) | (0.0, -44.0) | -1 | 228 special_lw (air) | 2 | A1 | 1 at +107 (1,967) | 16 | 1 / 4 |
| 12156 | rd4 | LEFT | 1,781 | (-3,047, 4,808) | (-3.4, +25.8) | -1 | 24 airborne | 2 | A1 | 6 at +60 (1,841) | 6 | 1 / 3 |
| 13693 | rd4 | LEFT | 1,824 | (-4,085, 3,896) | (-3.8, -44.0) | -1 | 27 airborne | 2 | A1 | 8 at +88 (1,912) | 21 | 4 / 7 |
| 13788 | rd4 | LEFT | 1,901 | (-3,262, 2,378) | (+4.0, -70.0) | -1 | 27 airborne | 2 | A1 | 6 at +8 (1,909) | 3 | 1 / 2 |
| 14330 | sd1 | LEFT | 1,852 | (-4,101, 2,664) | (+7.2, -44.0) | -1 | 209 attack_air | 2 | A1 | 8 at +55 (1,907) | 7 | 1 / 4 |
| 16305 | sd1 | LEFT | 1,824 | same cell as 13693 | | | | | A1 | 8 at +77 (1,901) | 7 | 4 / 7 |
| 17083 | sd1 | edge | 1,726 | (-1,891, 3,314) | (-29.8, +58.1) | -1 | 210 attack_air | 1 | A2 | 6 at +50 (1,776): the record's break | 6 | 1 / 10 |
| 17195 | sd1 | edge | 1,846 | (-1,509, 5,087) | (-28.4, +23.4) | -1 | 211 attack_air | 2 | A1 | 6 at +104 (1,950) | 14 | 1 / 2 |
| 17544 | sd1 | LEFT | 1,934 | (-4,128, -1,565) | (-7.8, -70.0) | +1 | 27 airborne | 2 | A1 | 1 at +45 (1,979) | 15 | 1 / 11 |
| 18122 | sd2 | LEFT | 1,765 | (-3,021, 3,905) | (-29.8, +6.6) | -1 | 24 airborne | 2 | A1 | 8 at +108 (1,873) | 19 | 1 / 6 |
| 19203 | sd2 | LEFT | 1,803 | (-3,604, 3,538) | (-9.8, -3.8) | -1 | 228 special_lw (air) | 2 | A1 | 6 at +23 (1,826) | 7 | 1 / 2 |
| 19720 | sd2 | LEFT | 1,901 | (-4,154, -3,024) | (0.0, -44.0) | -1 | 228 special_lw (air) | 1 | A2 | 1 at +28 (1,929) | 10 | 1 / 5 |
| 20309 | sd2 | LEFT | 1,765 | (-2,892, 3,556) | (-15.8, -70.0) | -1 | 26 airborne | 1 | A2 | 6 at +56 (1,821) | 8 | 1 / 3 |

Observations. Every success started left of x -1,500, airborne, facing left (one exception, facing right at the bottom left), 9 of 14 at
or above the wall top's height, with the double jump spent in 11 of 14 (class A1), 390 to 4,440 units from the target it broke (the two
lower targets are reached by long falls), at an arrival tick of 1,723 to 1,934 (the record's own break is one of them). The break came 8 to 115 words into the burst (median 58), after
3 to 21 runs of identical words. Each start cell had been dispatched 1 to 4 times and reached 2 to 13 times. Three of the 14 started
on the right side of the boundary, but airborne above the wall top with leftward speed, 100 to 400 units from the boundary: they are
re-landings of the known crossing, not crossings. The analysis's "0.3 % from level 7" is therefore the average of a 0 % stage (4,510
dispatches at `low`, `launch`, `x600`, `mid-flight` and `WT`: no break) and a 5.8 to 11.5 % stage (`LEFT` 11 of 190, `edge` 3 of 26).

### 1.2 The crossing was done once, as a chain of short prefixes

The record's lineage is 38 bursts for 1,885 ticks (49.6 ticks used per burst, 6 to 101). Its level-7 part (the target-2 break at 1,339
inside the burst that ends at 1,350, to the target-6 break at 1,776) is nine links:

| link | it | session | start L | ticks used | start stage, class | start position, velocity, status | cell dispatched (all sessions) | of which reached a later link or the break |
| ---: | ---: | --- | ---: | ---: | --- | --- | ---: | ---: |
| 1 | 2573 | rd2 | 1,350 | 72 | launch, A0 | (2,702, 3,134) (19.3, 19.0) special_hi | 2 | 1 |
| 2 | 2791 | rd2 | 1,422 | 22 | launch, A2 | (2,699, 3,449) (-29.8, 19.6) attack_air | 3 | 3 |
| 3 | 2876 | rd2 | 1,444 | 14 | launch, A2 | (2,364, 3,273) (5.4, -33.2) attack_air | 4 | 2 |
| 4 | 3106 | rd2 | 1,458 | 40 | launch, A2 (low-ish) | (2,281, 2,676) (-8.6, -44.0) airborne | 4 | 2 |
| 5 | 4002 | rd2 | 1,498 | 34 | grounded on the platform | (2,411, 2,416) grounded, landing | 3 | 1 |
| 6 | 5050 | rd2 | 1,532 | 101 | launch, A2 | (2,031, 3,637) (-29.8, 50.8) attack_air: the flight | 2 | 1 |
| 7 | 6085 | rd2 | 1,633 | 61 | mid-flight, A0 | (-631, 4,670) (-108.9, 147.3) special_hi: the up-B | 1 | 1 (wall top) |
| 8 | 10794 | rd4 | 1,694 | 32 | WT | (-1,724, 3,000) landing lag | 2 | 1 |
| 9 | 17083 | sd1 | 1,726 | 50 | edge, A2 | (-1,891, 3,314) (-29.8, 58.1) attack_air | 1 | 1 (break) |

- **Each link is a short prefix of a 120-word random burst** (14 to 101 words used, mean 47); the rest of each burst was discarded.
  The 426 ticks from the level-7 arrival to the break took nine dispatches at those cells, but 14,500 iterations of search: the
  flight and the up-B landing were found inside rd2 (iterations 5,050 and 6,085), the wall-top cell was first dispatched 4,700
  iterations later (rd4, 10,794) and the edge cell it created 6,300 iterations after that (sd1, 17,083). The wall-top cell was dispatched
  twice in six sessions; the edge cell once.
- **From the chain's own cells, random bursts advance often:** 13 of the 22 dispatches ever made from the nine link cells reached a
  later link's key or broke the target (link 2's three dispatches reached links 3, 4 and 6). The rarity is not in the inputs from these
  states; it is in how rarely these states were dispatched.
- **One flight, two landings.** Every one of the 5,314 dispatches ever made from a level-8 or deeper cell descends from the flight burst
  (rd2 it 5050). Of the 342 level-7 dispatches from `mid-flight`, `edge`, `WT` or `LEFT` starts, 263 descend from it; the other 79 are
  other flights (rd2, rd3 mostly) that reached mid-flight or near-edge states (as close as x -965, y 3,296, airborne) and never landed. A
  second, independent flight landed on the wall top at tick **1,683** (sd1 it 15129, from a cell at (657, 4,167), class A2, L 1,604; a
  sibling cell landed at 1,708 in rd4): both dispatches from those two cells landed. The 1,683 landing replaced the representative of the
  record's own wall-top cell (same key) in sd1 and **has never been dispatched since** (section 3.4).
- Falls play no part on the way: `launch`, `x600`, `mid-flight` and `edge` starts fell 1 time in 845; `low` starts fell 755 times in
  3,691 (they are the states that dropped off the platform to the lower right); `LEFT` starts fell 28 times in 190.

### 1.3 Where the failures ended: the stage funnel

For each right-side dispatch, the furthest stage any of its reaches touched (the burst's first visits of distinct keys):

| start stage | dispatches | reached mid-flight | reached edge | reached wall top or left | broke a target | fell |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| low | 3,691 | 20 (0.5 %) | 1 | 1 (0.03 %) | 0 | 755 |
| launch | 630 | 28 (4.4 %) | 1 (0.16 %) | 0 | 0 | 1 |
| x600 | 71 | 37 (52 %) | 1 | 1 (1.4 %) | 0 | 0 |
| mid-flight | 118 | | 11 (9.3 %) | 8 (6.8 %) | 0 | 0 |
| edge | 26 | | | 20 (77 %) | 3 (11.5 %) | 0 |
| WT | 8 | | | 1 reached x < -2,100 | 0 | 0 |
| LEFT | 190 | | | | 11 (5.8 %) | 28 |

Cells and dispatches per stage (all level-7 cells, 6,222): `low` 3,994 cells (1,971 dispatched, 3,691 dispatches, 739 doomed); `launch`
522 (333, 630); `x600` 52 (39, 71); `mid-flight` 148 (87, 118); `edge` 62 (20, 26); `WT` + `LEFT` 1,444 (176, 198; 240 doomed; only 5
grounded left-side cells exist at level 7, the rest are airborne: A0 596, A1 557, A2 268). The left side is barely explored: 7.8 new cells
per burst from `LEFT` starts against 1.3 at level 7 overall. Dispatches per session at the stages that matter: `mid-flight` 13 / 42 / 20 /
18 / 25 (rd2 to sd2), `edge` 1 / 6 / 10 / 6 / 3, `WT` + `LEFT` 0 / 0 / 4 / 34 / 80 / 80 (rd1 to sd2).

Failures by stage, in words: `low` starts wander or fall in the lower right (78 % of level-7 dispatches went there); `launch` starts drift
and end by length far from the wall top (only 4.4 % even reach the middle of the flight); `mid-flight` starts end by length after
drifting, one in eleven reaching the edge; `edge` starts mostly land (re-landings of the known crossing); `WT` starts jump and end by
length without passing near a target (8 dispatches); `LEFT` starts miss the target and run out of words (151 of 190) or fall (28).

### 1.4 The inputs that worked, described generically

Hold lengths are not recorded; runs of identical words are the proxy (mean 5.8 over the record's crossing, 6.2 expected from the uniform
hold draw). Word classes: stick in one of nine directions, button in one of eight.

- **The record's flight (links 5 to 7, 196 ticks, platform to wall top):** left-ish stick (left, up-left, down-left) on 54 % of ticks
  against 33 % expected, right-ish 11 % against 33 %, B held on 29 % of ticks (two up-ish + B inputs of 8 and 4 ticks: the double-jump
  rise and the up-B), C-up on 11 %. In order: a jump from the rising platform (an up-ish stick input in jump squat), a 39-tick aerial
  drifting left, a 17-tick fall, a double jump at 1,575 (a C-button press with the stick neutral), a 39-tick aerial reaching x -41 at y 4,422, a 6-tick fall, the
  up-B at 1,624 (up-left + B for 8 ticks: 39 ticks of special_hi from (-206, 4,194) to (-1,515, 5,026)), 30 ticks helpless drifting
  left 200 units, landing on the wall top at 1,693; then 25 ticks of uninterruptible landing lag, 3 of jump squat, a jump at 1,721,
  a 39-tick aerial and an 11-tick aerial to the break at 1,776 (82 ticks from the landing, 54 of them airborne).
- **The 14 successes pooled (938 ticks before the breaks):** left-ish 39 %, right-ish 31 %, B 8 %, C-up 14 %, seven up-ish + B ticks in
  all: barely biased. From a state already within 1,500 units of a target, a near-uniform random walk hits it in 6 to 12 % of bursts.
- **All 4,536 right-side level-7 bursts realised the uniform draw** (left-ish 33.4 %, right-ish 33.5 %, up-ish + B 5.0 ticks per 120).
- **Holding left helps reach the middle of the flight but not the landing:** `launch`-region bursts (x 600 to 2,400, high) reached
  mid-flight in 13.9 % of cases when fewer than 25 % of their first 100 words were left-ish, 24.5 % at 25 to 45 %, 38.8 % at 45 % or
  more; of the 20 bursts with at least 60 % left-ish words, 0 landed. Direction alone is not the crossing; height and timing are
  (the up-B from x about -200 at y about 4,200, late enough to be past the middle, early enough to be high).
- **The moving platform sets the launch:** the platform (group 2) oscillates vertically over 1,800 units with a 300-tick period
  (maxima at 88 + 300 k, minima at 238 + 300 k). The record landed on it at 1,472, 34 ticks after a minimum, rode it up for 47 ticks at
  17.4 units per tick and jumped at 1,519 at y 2,869. A faster arrival meets the platform at another phase; an arrival 300 ticks
  earlier would meet the same phase.

## 2. Is success a precise multi-step sequence, and how likely is the explorer to produce it?

1. **Within one burst from the launch region, essentially never.** 0 of 630 `launch` dispatches landed; 0 of 185 bursts from the
   flight's own start band (x 1,200 to 2,400, high) landed; the flight burst (link 6) is the single exception and it took two more
   dispatches (the up-B landing, the wall-top jump) to reach the break. A rough bound: the flight needs leftward air drift on about
   two thirds of 175 ticks (about 20 decisions at the mean hold, each left-ish with probability 1/3), a double jump while falling and an
   up-ish + B decision (3 of 72 words, 4.2 % per decision) inside a window of a few decisions at the right height, then a helpless fall
   that meets the wall top: the product is of the order of 10^-5 per burst. The archive's chain mechanism (keep the first reach of
   every new key, re-dispatch it later) is what made the crossing possible: each link needed luck of 1 in 2 to 1 in 11, not 1 in 10^5.
2. **The precision is in the state, not in the word sequence.** From the right cells random bursts advance at high rates (section 1.2:
   13 of 22; `edge` 77 %; `mid-flight` 6.8 %), and the successful sequences are near-uniform draws (section 1.4). Conversely the
   splice probe shows the route's own tape is state-coupled: all 26 level-7 splice candidates failed, including arrivals 12 to 25 units
   away with the same facing, air state, status and jump count (n 5 and 29), and 20 of 20 candidates with gains of 2 to 9 ticks.
   A fixed tape fails under a sub-cell displacement; a fresh random burst from the displaced state does not.
3. **What the explorer is unlikely to produce is the chain, because the selection rarely returns to its links.** The crossing needs 4
   to 9 chained dispatches of 20 to 100 useful words each; the link cells received 1 to 4 dispatches in six sessions (23 in all) among
   4,734 level-7 dispatches, 3,691 of which went to `low` states that never progressed. With v4's weights the 1,683 wall-top landing
   expects 0.21 dispatches per 5,000-dispatch run (section 3.4).
4. **Per-dispatch chances from each stage, as measured** (the honest offline estimate of "how likely from a given start state"):
   `launch` to mid-flight 4.4 %, to a landing about 0.2 % (1 in 630 plus the mid-flight branch); `mid-flight` to a landing 6.8 %;
   `edge` to a landing 77 %, to a break 11.5 %; `LEFT` to a break 5.8 %; `WT` to a break 0 of 8 (the record needed two links from the
   wall top). Multiplying the stage rates along the chain gives about 1 landing per 350 `launch`-stage dispatches if every intermediate
   reach were re-dispatched once, which is roughly what happened (three landings in two lineages from about 700 `launch` and `x600` dispatches).

## 3. Promising start states and generic online signals

### 3.1 Which states produced progress

Progress (a break, or a wall-top / left reach from a right-side start) by the start state's features, level 7:

- **Height and class:** right-side starts at y 3,000 to 4,500: 21 of 529; at y 4,500 to 6,000: 8 of 192; every band below y 1,500:
  0 of about 3,000. Class: A2 10 of 2,000, A1 11 of 1,473, A0 9 of 912 (the up-B and helpless states on the flight), grounded 0 of 151.
  `LEFT` breaks: A1 9 of 83, A2 2 of 58, A0 0 of 47 (helpless left of the wall never broke anything), grounded 0 of 2; with both jumps
  used 9 of 130, one used 2 of 58.
- **Status:** at level 7 the aerial-attack statuses (209 to 212) and the special_hi / helpless pair (226, 58) carry the progress; the
  falling-airborne statuses (26, 27) and ground statuses carry none on the right side.

### 3.2 A cell that succeeded once succeeds again (generic, measurable online)

P(a target break on dispatch k + 1 of a cell | a break among its dispatches 1..k) against the complement, all sessions:

| levels | given a prior break | given none | ratio |
| --- | --- | --- | ---: |
| 0 to 2 | 109 / 260 = 41.9 % | 101 / 521 = 19.4 % | 2.2 |
| 3 to 5 | 19 / 61 = 31.1 % | 28 / 1,214 = 2.3 % | 13.5 |
| 6 to 7 | 9 / 18 = 50.0 % | 3 / 3,395 = 0.09 % | 566 |
| 8 to 9 | 24 / 78 = 30.8 % | 43 / 2,151 = 2.0 % | 15.4 |
| all | 161 / 417 = 38.6 % | 175 / 7,281 = 2.4 % | 16.1 |

Level-7 progress (break or landing) repeats the same way: 5 of 12 after a prior progress against 1 of 2,096 without (cells 18319 "111",
18314 "11", 18766 "11", 35379 "1100"). A cell's record of producing a new key predicts more new keys (2.6 to 2.8 times at every level) but
not breaks (ratio 1.0 to 1.3 except at levels 6 to 7). The useful generic signal is the per-cell **break record**, not novelty.

### 3.3 The arrival count at dispatch time predicts failure (generic)

Replaying the ledger to recover each cell's `seen` as it stood when it was dispatched:

| level 7, seen at dispatch | progress / dispatches | | all levels, break rate by seen at dispatch | 0 to 2 | 3 to 5 | 6 to 15 | 16 + |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| 0 to 2 | 23 / 1,020 = 2.25 % | | levels 0 to 2 | 19.7 % | 21.8 % | 24.7 % | 26.7 % |
| 3 to 5 | 15 / 956 = 1.57 % | | levels 3 to 5 | 4.3 % | 4.7 % | 3.2 % | 0 / 285 |
| 6 to 15 | 3 / 1,564 = 0.19 % | | levels 6 to 7 | 2.25 % | 0.96 % | 0.12 % | 1 / 1,840 |
| 16 + | 0 / 1,194 | | levels 8 to 9 | 2.3 % | 3.7 % | 1.6 % | 1.6 % |

By the number of earlier dispatches of the same cell at level 7: first dispatch 35 of 2,626 (1.33 %), second or third 6 of 1,775
(0.34 %), fourth or later 0 of 333. At levels 3 to 7 the heavily-arrived cells are attractors (states the explorer keeps falling into)
and produce nothing; v4's count term (1 + seen)^-1/2 separates seen 2 from seen 20 by a factor 2.6 only, and the `low` stage holds 7.6 %
of all mass (378 dispatches per run) for a historical yield of 1 landing and 0 breaks in 3,691.

### 3.4 Faster arrivals on the clear's own trail are never searched from (generic)

The 1,885 route passed 310 distinct keys. At 198 of them the archive now holds a representative strictly faster than the route's own
arrival (these are exactly the splice probe's 198 candidates; leads up to 487 ticks at level 4, up to 209 at level 7). 146 of the 198
were never dispatched after the shortening (level 7: 20 of 26). Three of them are on the crossing itself: the link-3 key (route 1,444, now
1,329, lead 115, class A2 at the platform), the link-5 key (route 1,498, now **1,373**, lead 125, grounded on the platform), both shortened
late in sd2 and never dispatched since, and the wall-top key (route 1,694, now **1,683**, lead 11, shortened in sd1 by the second flight,
never dispatched since). Under v4 the four wall-top cells weigh 0.004 to 0.008 % each (0.2 to 0.4 dispatches per 5,000-dispatch run).
The splice probe showed the tape cannot be copied onto these states; whether the search can finish from them was never tried.

### 3.5 What a generic online rule could read

Without any coordinate, target id, cid or census number: (a) a cell's own break record (breaks per dispatch, section 3.2); (b) its
arrival count at dispatch time or its dispatch count (section 3.3); (c) its `fresh` counter and whether its representative was
shortened by a lineage other than its own (section 3.4); (d) its lead over the archive's best verified clear's arrival **at the same
key** (the clear's own trail keys and ticks, in the archive's own units; PACE's lead is per level, section 4.3). Resource class and
status are in the archive already; their effect here (A0 never breaks from the left, grounded never progresses on the right) is
Mario-specific in value but generic in form (a per-(level, class) success rate measured online). What is not determinable offline is in
section 7.

## 4. Expected crossing events per night under CONT and PACE

### 4.1 Masses and rates

v4 (CONT's base pool, E6 off, bound 1,860) on the import, level 7 (11.38 %):

| stage | eligible cells | v4 mass | dispatches per 5,000-dispatch run | historical dispatches | landings (WT / left reach) | breaks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| low | 2,714 | 7.567 % | 378 | 3,691 | 1 | 0 |
| launch | 497 | 1.847 % | 92 | 630 | 0 | 0 |
| x600 | 52 | 0.209 % | 10.5 | 71 | 1 | 0 |
| mid-flight | 145 | 0.468 % | 23 | 118 | 8 | 0 |
| edge | 60 | 0.197 % | 10 | 26 | 20 | 3 |
| WT | 4 | 0.021 % | 1.1 | 8 | 0 | 0 |
| LEFT | 278 | 1.072 % | 54 | 190 | | 11 |

The census's crossing band (1,694 <= L <= 1,775, 386 cells, 1.28 %, 64 per run) is the `edge` + `WT` + `LEFT` cells of that tick range plus
a few mid-flight cells. Under PACE the base pool is v4 times (1 - s); the ahead pool adds nothing to these stages (section 4.3).

### 4.2 Expected events, using the historical per-stage rates

Per 5,000-dispatch run (the step-4 plan's unit; the smoke ran 4,416 dispatches per hour) and per night-2 arm (three runs):

| arm | share | dispatches to launch / mid-flight / edge / WT / LEFT per run | new landings per run (from launch, x600, mid-flight) | re-landings per run (from edge) | level-7 breaks per run | per arm (x 3): new landings / breaks |
| --- | ---: | --- | ---: | ---: | ---: | --- |
| CONT | 0 | 92 / 23 / 10 / 1.1 / 54 | 1.7 | 7.6 | 4.2 | 5.2 / 12.7 |
| PACE | 1/2 | 46 / 12 / 5 / 0.5 / 27 | 0.9 | 3.8 | 2.1 | 2.6 / 6.4 |
| PACE | 1/3 | 62 / 16 / 7 / 0.7 / 36 | 1.2 | 5.1 | 2.8 | 3.5 / 8.5 |

Reading. (a) The breaks are re-breaks of the three left targets from `LEFT` and `edge` states at arrival ticks 1,723 to 1,934: none of
them is faster than the record's 1,776 unless it starts from the 1,683 landing or an edge cell ahead of 1,726. (b) The "new landings"
are landings from `mid-flight` cells that are themselves descendants of the known flight (263 of 342), at the known pace; they are not new
crossings. (c) The events that could shorten the clear through the crossing are dispatches of the trail-lead cells (section 3.4): the
1,683 landing expects 0.63 dispatches per CONT arm and 0.32 per PACE-1/2 arm; the two platform cells with leads of 115 and 125 expect
1.3 and 0.9 dispatches per CONT arm (half of that under PACE 1/2). (d) A `launch`-stage flight that is new (another lineage crossing) expects 0.15 per CONT
run from the `launch` cells' own rate (1 in 630), under 0.5 per arm. These rates are six-session averages over cells that were dispatched
under four different selections; the dispatched representatives are now partly different (shorter) states, and every new dispatch is a
fresh keyed draw, so the rates are the best available estimate, not a measurement of the lab.

### 4.3 Does PACE starve the clears night 2 needs?

- The ahead pool funds level-7 cells with L < R(7) = 1,339, the 27 cells of the dead-end 1,237 lineage (51 dispatches per run at s = 1/2).
  Those are `launch`-stage states (x 1,200 to 5,400, high); their record is 0 landings in 17 dispatches and the level-6 front behind them 0
  in 177. At the `launch` rate they would yield about 7 mid-flight reaches and under 0.5 landings per arm. But a flight from them lands at
  about L 1,550 to 1,600, which is **not** ahead by PACE's per-level definition (lead is against the level-7 arrival, 1,339, while the
  crossing is a 350 to 450-tick traverse inside level 7): once such a lineage leaves the platform its cells fall back to the base pool at
  v4 weights. PACE's lead cannot carry a lineage across the crossing; I2 at level 7 moves only when a lineage reaches level 8. Night 2's
  I2 signal will come from levels 3 to 5, as the plan expects; the crossing is not what night 2 measures.
- The KEEP rule's second clause (a faster verified clear in any PACE run than in every CONT run) needs a clear that is faster than 1,885.
  The ending is at its floor; the one leg with slack (landing to target 6, 25 to 30 ticks) and the 1,683 landing live in the stages PACE
  halves. Both arms expect well under one such clear per arm (section 4.2 (c)); PACE halves a small number. Night 2 will almost surely be
  decided on I2 / I3, where the halving does not enter.
- The trade-off is therefore acceptable **for night 2 as a mechanism test**, and must be pre-declared as such: crossings and clears are
  not a night-2 outcome; the crossing stages' dispatch counts (section 4.1) should be reported as read-only metrics so the halving is
  seen, not inferred. It is not acceptable as a campaign setting: over many nights the ahead pool's 52 % keeps halving the only stages
  that ever produced level-8 progress while funding fronts whose crossing probability per dispatch is about 1 in 600. The plan's share
  decay or exit rule (S4) is the right place for that, with the crossing stages' event counts as its reading.
- s = 1/3 recovers a third of the crossing dispatches (2.8 breaks and 1.2 new landings per run against 2.1 and 0.9) at the price of a
  weaker ahead signal (34 % against 50 %). Since no crossing event in night 2 can decide anything and the ahead signal is the point of the
  night, 1/2 is the cleaner test (open question 1).

## 5. Generic mechanisms that could raise the crossing success rate

Evidence, cost and risk for each; all generic (no coordinate, target id, cid or census number in any rule; the stage names are the
analysis's reading of the archive, never an input).

1. **Longer or continued bursts at low-success transitions (CONT's continuation, already in night 1).** Evidence: the chain's links used
   14 to 101 words of 120 and the next link started from the reach, so a continued job removes the prefix replay (92 % of ticks) and keeps
   the process; the trigger (a new key or a shortening in the last 20 words) fires on the flight (the up-B reaches at ticks 1,631 to 1,633
   are inside the flight burst's last 20 words). What it does not change: the per-link luck (the continuation plays the same random
   stream from the segment's end, not from the reach), and it cannot re-dispatch a link later. Cost: none (built). Risk: none new; read
   night 1's CONTROL against CONT per stage (open question 6) before counting on it. Longer segments (240 words) at a low-success level
   would help only if the selection reached the flight states; at the `low` stage they would waste ticks.
2. **State-aware selection by the cell's own record and arrival count (sections 3.2, 3.3).** Two one-line generic terms: (a) a per-cell
   break-record term (a cell with b breaks in d dispatches gets a bonus, for example (1 + b)^a); (b) a steeper arrival-count penalty or
   a cap on re-dispatching cells with many arrivals at dispatch time (seen >= 16 took 1,840 level-6/7 dispatches for one break; the
   `low` stage's 378 dispatches per run would mostly go elsewhere). Evidence: 16 x on breaks over all levels, 566 x at levels 6 to 7
   (18 cases, the chain cells); seen 16 + is 0 of 1,194 at level 7 and 0 of 285 at levels 3 to 5. Cost: about 40 lines in the selection
   plus the seen-at-dispatch bookkeeping (already derivable from the ledger); a census of the redistributed mass; one arm. Risk: (a) is
   exploitative (it re-dispatches the cells on the record's chain, so it robustifies and polishes rather than discovers; at levels 0 to 2
   the ratio is 2.2 only); (b) changes the base pool, so it is a second change against CONT and needs its own arm; both constants are the
   audit's C6 class (tuned on this archive, to be recorded). Multi-arrival cells (several representatives per key) address the same
   observation from the other side (86 % of shortenings changed the state materially) at a much higher cost; the two cheap terms come
   first.
3. **A trail-lead pool: search from the faster arrivals on the clear's own trail (section 3.4).** Rule: among eligible cells whose key is
   on the archive's best verified clear's trail and whose L is strictly below the clear's arrival at that key, draw with weight
   increasing in the lead and decreasing in dispatches since the shortening (`fresh`), under a fixed small share. Evidence: 198 such
   cells, 146 never dispatched after the shortening, three on the crossing with leads 11, 115 and 125; from the chain's own cells random
   bursts advanced in 13 of 22 dispatches; the splice probe proved the tape cannot be copied onto them but said nothing about a search
   from them (its own "idea 2"). It is PACE's idea measured at the key instead of the level, so it funds exactly the states PACE's
   per-level lead cannot (section 4.3). Cost: the trail is one lineage walk over the reference clear the lab already imports; about
   100 lines plus the `fresh` counter the step-4 plan builds; or, cheaper and first, a one-night lab probe that dispatches each of the 198
   cells k times with the normal explorer and continuation (about 2,000 dispatches at k = 10, under an hour) and reports deeper reaches
   and faster arrivals at later trail keys per cell. Risk: anchoring on one clear's trail (the audit's lock-in concern; bounded by the
   share, and the pool empties as leads are consumed); the platform-phase question (section 7) may make the two platform leads dead
   ends; a probe answers that before any module is built.
4. **A macro explorer built from the agent's own successful segments.** Evidence is weak: the successful sequences are near-uniform
   draws (section 1.4); holding left raises the mid-flight reach 2.8 x but 0 of 20 left-biased bursts landed; the up-B and double-jump
   timing is state-coupled and the tape is brittle to 12-unit displacements. A library of the agent's own short segments (for example
   the words between two reaches that created cells at a deeper level) drawn with some probability would raise the per-decision chance
   of the few decisive inputs, but the evidence that it would help the crossing is thinner than for mechanisms 2 and 3, and it adds a
   new explorer contract (every archive and replay depends on the keyed uniform draws). Cost: a new explorer contract, its own tests,
   an arm. Risk: Mario-specific motion baked into a "generic" library; a changed explorer makes CONT and PACE results incomparable
   with earlier sessions. Defer until mechanisms 2 and 3 are measured.
5. **Effort budgeted to transitions with low online success rates (the proposal's kappa).** Evidence is against it as a per-level
   budget: the level-7 rate (0.3 %) is the average of a dead 0 % stage holding 78 % of the level's dispatches and a 6 to 77 % stage
   holding 4 %; more mass to level 7 under v4's within-level weights goes 66 % to `low` states (378 of the level's 569 dispatches per
   run). The within-level allocation is the problem; a per-level budget cannot see it. The same online rate measured per cell or per
   (level, class) is mechanism 2.
6. **The within-level length reference.** The base pool's length factor measures lag against the level's shortest cell (the 1,237
   lineage, which never crossed), so every post-crossing cell carries a factor of 0.18 to 0.21 while the dead-end lineage carries 1.0.
   The plan caps the lag at one burst in the pace pool only; capping it in the base pool too restores the crossing band to 0.87 % (the
   plan's census). Evidence: all 14 breaks and both landings came from cells with lags of about 300 to 700. Cost: one constant; a second change
   against CONT, so its own arm or night 3. Risk: at other levels the lag reference is meaningful; the cap is generic (one burst) and
   is the explorer's own constant.
7. **The chain economics (observation, not a mechanism).** The archive advances about 50 ticks per useful dispatch (the record's 38
   bursts; dispatched cells use a median 47 words of their burst). A crossing of 350 to 450 ticks is therefore 7 to 9 useful dispatches
   whatever the explorer; the lab's job is to make the selection return to the chain's links within a run, not within four sessions.
   Mechanisms 2 and 3 do that; continuation shortens each link's cost.

## 6. Recommendation

**Night 2.** Keep the plan's PACE at share 1/2 against CONT, as the one-change mechanism test it is, with three additions to the
pre-registration text, none a rule: (a) crossings and clears are not a night-2 outcome and cannot decide the pair (section 4.3); (b)
the summary reports, per run and per arm, the dispatch counts and events of the crossing stages (new keys, breaks and landings from
level-7 cells by `fresh` and by arrival count: all generic quantities; the stage labels stay in the analysis); (c) the share decay / exit
rule for a campaign (S4) is written before night 3, with the level-7 break count as one of its readings. Use 1/3 only if the owner wants
night 2 to double as a short clear hunt, which the numbers say it cannot be.

**Before night 2, if a lab hour is available: the trail-lead probe** (mechanism 3, probe form): dispatch each of the 198 trail-lead
cells k = 10 times with the normal explorer and continuation on, from the committed runner, and report per cell whether any burst
reached a deeper level or a later trail key faster than the clear. It answers "can the search finish from a faster state?" the way the
splice probe answered the tape question, in about an hour of native time, before any module is built. It is generic (the candidate set
is the splice probe's own rule) and registers nothing.

**November build order.** Keep steps 4 (fresh counter, pooled ahead draw, I1 to I4, census) and night 2 as planned. Then, before the
pools and the remaining components: (5a) the trail-lead pool and the per-cell break-record term as two separate arms against CONT
(night 3 and 4, or one night with three arms if throughput allows), each with a pre-declared mass census; (5b) the arrival-count cap and
the base-pool lag cap as a combined "within-level" arm; (5c) the ahead-pool share decay. The macro explorer and multi-arrival cells
stay after these. Donkey Kong at C2 and g4 after are unchanged.

## 7. What cannot be determined offline

1. Whether a crossing is possible from the faster platform states (leads 115 and 125) or from the 1,237 lineage: the platform's phase
   differs there and no trajectory in the archive crossed from any phase but the record's. Only a native search from those states
   answers it (the probe).
2. The actual per-dispatch rates in the lab: every historical rate is a six-session average over cells dispatched under four
   selections; representatives have since changed, E6 is off, continuation is new, and new dispatches are fresh keyed draws.
3. The effect of continuation on the chain (the smoke's 25.6 % continuation rate is not split by stage); night 1's ledger will give it.
4. The hold lengths the explorer drew (not recorded; runs of identical words merge equal consecutive draws).
5. The wall-top landing tolerance (how far the helpless fall may drift and still land): the 24 traces show landings, not the
   boundary of landing.
6. Whether the `LEFT` breaks' 5.8 % holds for the 278 eligible left cells that were never dispatched (172 of the 1,440 left cells were).
7. The states of the 226,205 discarded slower arrivals (the analysis's item 9.1), among them any other flights that reached the middle
   but were dropped at already-known keys.
8. Whether a "generic" per-class success rate transfers to another character: the values here (A0 never breaks from the left, grounded
   never progresses on the right) are Mario's.

## 8. Open questions for the owner

1. **Night-2 share.** Options: (a) 1/2 as planned; (b) 1/3; (c) 1/4. Recommendation: (a), with the pre-registration additions of
   section 6; the crossing cannot decide night 2 under any share, and (a) is the cleanest ahead-pool signal.
2. **Night-2 reporting of the crossing stages.** Options: (a) add read-only per-run counts of level-7 dispatches, new keys, breaks and
   landings, split by `fresh` and by arrival count at dispatch; (b) report nothing new and read the ledger offline afterwards (the scripts
   under `logs/frs_crossing/` do it in minutes). Recommendation: (b) for night 2 (no code change before the night), (a) from step 5 on.
3. **The trail-lead probe.** Options: (a) run it before night 2 under the owner's authorisation (about an hour of native time, a
   150-line driver over the committed worker, zero-tick tests, one light review); (b) run it after night 2; (c) skip it and build the pool
   directly. Recommendation: (a) if a lab hour exists before Friday, else (b) first thing in November; never (c): the probe decides
   whether the pool is worth building.
4. **Night-3 arm.** Options: (a) the trail-lead pool; (b) the per-cell break-record term; (c) the arrival-count cap plus the base-pool
   lag cap. Recommendation: (a) if the probe finds any deeper reach from a lead cell, else (c); (b) after either, because it polishes
   rather than discovers.
5. **The 1,683 landing and the two platform leads.** Options: (a) leave them to the generic pool / probe; (b) dispatch them by hand as a
   lab experiment; (c) register the 1,683 landing as a partial. Recommendation: (a); (b) only inside the probe's generic candidate set
   (they are three of its 198); (c) no, nothing is registered below a clear.
6. **Reading night 1 for continuation.** Options: (a) a zero-tick analysis of night 1's ledgers with the funnel of section 1.3 adapted
   to the lab's segments (CONTROL against CONT per stage, landings per 1,000 level-7 dispatches); (b) rely on the index row's continuation
   rate. Recommendation: (a), before night 2's pre-registration is finalised.
7. **The macro explorer.** Options: (a) defer until mechanisms 2 and 3 are measured; (b) build it as the step-5 explorer. Recommendation:
   (a); the evidence here does not support it.
8. **Campaign reading of crossing progress.** Options: (a) make "a level-7 break from a cell with lead > 0 at its key" the campaign's
   crossing milestone (generic, read-only); (b) keep I2 / I3 only. Recommendation: (a) as a monitored quantity in the S4 exit rule's
   reading, never a selection input.
9. **Per-(level, class) success rates as a selection term.** Options: (a) measure and report them online, no selection use; (b) use
   them in the weights. Recommendation: (a) for Mario; revisit when Donkey Kong's archive shows whether the pattern transfers.
10. **Trail-lead pool share and weight (if built).** Options: (a) a fixed small share (1/10 to 1/6) with weight lead x (1 + fresh)^-1/2;
    (b) membership only (uniform over the lead cells). Recommendation: (a), with the share's origin recorded (audit C6); a census before
    the night as for PACE.

## Appendix. Working files (Git-ignored, `logs/frs_crossing/`)

| file | content |
| --- | --- |
| `scripts/c0_common.py` | read-only loader (import archive, reference trace, words, lineage, start states) |
| `scripts/c1_level7.py`, `c1_level7_rows.json`, `c1_successes.json`, `c1_stdout.txt` | every level-7 dispatch with its exact start state, stage, outcome; the 14 successes with words |
| `scripts/c2_chain.py`, `c2_links.json`, `c2_stdout.txt` | the record's chain, the per-link funnel, successes against the record chain |
| `scripts/c3_corridor.py`, `c3_stdout.txt`, `c3c_stdout.txt` | right-side starts by x band and height, corridor dispatches, lineage against the flight burst, wall-top and left cells |
| `scripts/c3b_funnel.py`, `c3b_stdout.txt` | the stage funnel, cells per stage, dispatches per session |
| `scripts/c4_signals.py`, `c4_stdout.txt`, `c4b_stdout.txt` | per-cell repeat rates, arrival count at dispatch time, class / status tables, left-share test |
| `scripts/c5_masses.py`, `c5_masses.json`, `c5_stdout.txt`, `c5b_stdout.txt` | exact v4 masses per stage, empirical rates, expectations per run and per arm |
| `scripts/c6_record_trace.py`, `c6_stdout.txt` | the record's crossing per tick, its words as runs, the platform's period, link-boundary states |
| `c7_stdout.txt`, `c8_stdout.txt` | word-class composition of the successful segments; trail-lead keys and their dispatch history |
