# Departure probe: result and offline analysis (2026-11-03)

**Lab result, exploratory, unregistered. No claims.** This record decides nothing. The analysis used zero native ticks: no build, no game, no probe or lab run, and
`lab.lock` was not taken. `C:/BattleShip_lab` was read only. Every number below is read from the run's own files and traces; nothing is taken from game mechanics.
Status of this record: complete (not PARTIAL).

Sources: `docs/project_handoff.md`, `docs/frs_departure_probe_plan_2026-11-02.md`, and the run folder `C:/BattleShip_lab/departure_probe_2026-11-02/` (`plan.json`,
`candidates.jsonl`, `run/summary.json`, `run/results.jsonl`, `run/curve.csv`, `run/report.md`, `run/controls.json`, `run/config.json`, `run/state.json`, and the traces
`run/traces/control_clear_r1`, `control_clear_r2`, `control_filler` and the 944 candidate traces), plus the console log `~/departure_probe_2026-11-03_console.log`.
Status classes are the names of the checked-in status table that the probe itself uses (`rl/m8_rd_cells.Classifier`, Mario).

Tick convention (the probe's): tick t is the reply after input tick t (`steps[t − 1]`; t = 0 is the tick-0 reply). The word at index t is consumed at tick t and its
effect is first seen at tick t + 1. A candidate at departure tick d plays the clear's words 0..d − 1 (later d: words 0..D − 1, then the neutral word), then its exit
from word index d. Phase(t) = (t − 239) mod 300.

## 1. Run identity

| item | value |
|---|---|
| tool / contract | `tools/frs/departure_probe.py` (sha256 `95fc3e5b…`, same at start and end) / `frs_departure_probe_v1` |
| HEAD (checked at start; 0 tracked changes) | `9afcaf6c88e6c8e5e92766746ab8723b91952872` |
| lab code digest | `0b248a9e30304325b24a2eba548d988501fc0bd5f4dd116e5fe997ef0a6b1475` |
| candidate-set digest | `bfca96f3401e6b5629398f3a414432cd85154cc54abf382834cfc99e0d7ad68f` (as planned) |
| band digest | `0cb3b2912c00b6e8ea0ce36457efc853ef1aa60541aded6aa09ddf5fe3e20146` (as planned; arc 77..177, 295 sources) |
| probed clear | `crossing_2026-10-15_run2:36236:8692` (the 1,245), D 716, B 1,042 (target 6), P 300, origin 239 |
| run (UTC) | 2026-11-03 22:15:56 to 22:37:17; native 1,278.7 s of the 2,700 s cap |
| status / stop | **COMPLETED** / none |
| verdict | **FORCED_IN_PROBE**: no departure beats B; both sides of the band tested (outside the band, departed at d: earlier 12, all pre-break; later 199) |
| counters | 944 planned, dispatched, returned and valid; 0 failed, 0 mismatches, 0 contract, 0 pin drift; 1,335,376 candidate ticks + 3,506 control ticks |
| counted (valid, departed at d) | 314: the control (716), 300 later rows of the clear's exit (717..1,016) and 13 pre-break rows; did not depart at d: 630 (later 603, no_exit 27) |
| controls | the 1,245 VERIFIED twice (chain per tick, break table, tick contract); the filler stays on the group to 1,016 (no later cut) |
| key output digests (sha256, first 16) | `plan.json` 24470e310a91259a, `candidates.jsonl` 67f5816ba7706cd1, `run/results.jsonl` 3a12a080f9149b25, `run/summary.json` 7a7b9fa084c9ae83, `run/report.md` 2337c8ccef67ce4b, `run/curve.csv` 224e30ed76afbf18 |

**Backup:** `D:/BattleShip_lab_backup/2026-11-03_departure_probe/` holds `lab/departure_probe_2026-11-02/...` (958 files, the whole folder with `run/` and all 947
traces; the empty `run/vw/` folder is copied too) and `console/departure_probe_2026-11-03_console.log`: 959 files, 148,927,360 bytes. Copied with `cp -rp`, nothing
moved, deleted or modified. Every source and destination file was hashed independently with `sha256sum` and with PowerShell `Get-FileHash`: same 959 paths, same
hashes, 0 mismatches. `SHA256SUMS.txt` (sorted, LF, 959 lines) has sha256 `df6173814befdc87f7a58037db0b1eb5678c0f56ba9e6b07946fc4eb4d663a5f`.

## 2. Summary

- **A.** None of the 154 rows with d in 639..715 departs at d. Every measured departure is at 716 or later. The rows neither all converge on 716 nor all depart a
  fixed few ticks after d: 26 of 154 depart at 716..718, and most of the rest depart at a fixed offset into their own exit (the clear's exit: d + 175 in 55 rows;
  the generic exit: d + 83, d + 124, d + 41 or d + 9). No row breaks a target within its budget.
- **B.** In the clear, the fighter is in one grounded status-227 run (class special_lw) from 627 to 716 (status timer 0..89). Target 2 breaks inside it at 639. The
  take-off (status 20) starts at 717, the tick after that run's last tick. In all 154 candidates the special_lw run that contains d also ends at exactly 716, whatever
  the exit plays, and no status 20 starts before 717. The clear's own take-off input, played at d, is followed by status 227 at d + 1 in all 77 rows of the clear's exit.
- **C.** The later rows marked '-' (742..930 and 973..999, 216 rows) all depart at d. None breaks a target. 742..930 (phases 203..91) land 246 ticks after d on
  static line 4 at y −2,550 and stay there; 973..999 (phases 134..160) land 192 ticks after d on line 0 (the clear's landing line) and end on line 3 at y −1,950.
- **D.** All 85 successes (716..741, 931..972, 1,000..1,016) reach the baseline's progress at exactly d + 326 (target 6). The group is moving at every one of their
  departure ticks (it is never still in the record). The take-off height differs between successes, from y 3,000.8 to 3,572.4, always 300.0 above the group's
  translation.
- **E.** At matching phases 100..133 the group is identical, but the fighter is not: special_lw (timer 12..45), at x 3,065.0 to 2,607.4 moving left, in the first
  cycle; idle_ground (timer 222..255), standing at x 2,543.4, in the next.
- **F.** (1) SUPPORTED for the clear's exit. (2) SUPPORTED. (3) SUPPORTED that no take-off happened before 716 in the 154 recorded input streams; UNKNOWN for every
  possible input. (4) UNKNOWN: an earlier take-off after the break needs a different prefix. With the clear's 326-tick exit the gain could be at most 77 ticks. The
  next cycle's results do not transfer to the first cycle's different state.

## 3. Part A: departures for d in 639..715 (after the on-group break, before D)

Every row is valid. Reasons: the clear's exit (a) is `later` in 77 of 77 rows. The generic exit (g1) is `later` in 67 rows and `no_exit` in 10 (still on the group's
line when the trace ends). No row has a first break or a progress tick. Outcomes: a 58 fall and 19 budget end; g1 69 budget end and 8 fall. "Status of G" is the status
of the run that holds the last grounded tick, so 20 (jump_squat) is a take-off.

| d | phase | a: departure_tick | a: Δ | a: dep. phase | a: status of G | g1: departure_tick | g1: Δ | g1: dep. phase | g1: reason | g1: status of G | first break (a / g1) | progress_tick (a / g1) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 639 | 100 | 814 | 175 | 275 | 20 jump_squat | 722 | 83 | 183 | later | 225 special_hi | – / – | – / – |
| 640 | 101 | 815 | 175 | 276 | 20 jump_squat | 723 | 83 | 184 | later | 225 special_hi | – / – | – / – |
| 641 | 102 | 816 | 175 | 277 | 20 jump_squat | 724 | 83 | 185 | later | 225 special_hi | – / – | – / – |
| 642 | 103 | 817 | 175 | 278 | 20 jump_squat | 725 | 83 | 186 | later | 225 special_hi | – / – | – / – |
| 643 | 104 | 818 | 175 | 279 | 20 jump_squat | – | – | – | no_exit | – | – / – | – / – |
| 644 | 105 | 716 | 72 | 177 | 20 jump_squat | 900 | 256 | 61 | later | 20 jump_squat | – / – | – / – |
| 645 | 106 | 717 | 72 | 178 | 20 jump_squat | – | – | – | no_exit | – | – / – | – / – |
| 646 | 107 | 716 | 70 | 177 | 20 jump_squat | – | – | – | no_exit | – | – / – | – / – |
| 647 | 108 | 716 | 69 | 177 | 20 jump_squat | 730 | 83 | 191 | later | 225 special_hi | – / – | – / – |
| 648 | 109 | 892 | 244 | 53 | 18 idle_ground | 731 | 83 | 192 | later | 225 special_hi | – / – | – / – |
| 649 | 110 | 824 | 175 | 285 | 20 jump_squat | 732 | 83 | 193 | later | 225 special_hi | – / – | – / – |
| 650 | 111 | 825 | 175 | 286 | 20 jump_squat | 733 | 83 | 194 | later | 225 special_hi | – / – | – / – |
| 651 | 112 | 826 | 175 | 287 | 20 jump_squat | 734 | 83 | 195 | later | 225 special_hi | – / – | – / – |
| 652 | 113 | 827 | 175 | 288 | 20 jump_squat | 735 | 83 | 196 | later | 225 special_hi | – / – | – / – |
| 653 | 114 | 828 | 175 | 289 | 20 jump_squat | 736 | 83 | 197 | later | 225 special_hi | – / – | – / – |
| 654 | 115 | 829 | 175 | 290 | 20 jump_squat | 737 | 83 | 198 | later | 225 special_hi | – / – | – / – |
| 655 | 116 | 830 | 175 | 291 | 20 jump_squat | 738 | 83 | 199 | later | 225 special_hi | – / – | – / – |
| 656 | 117 | 716 | 60 | 177 | 28 crouch_pass | 739 | 83 | 200 | later | 225 special_hi | – / – | – / – |
| 657 | 118 | 832 | 175 | 293 | 20 jump_squat | 740 | 83 | 201 | later | 225 special_hi | – / – | – / – |
| 658 | 119 | 833 | 175 | 294 | 20 jump_squat | 741 | 83 | 202 | later | 225 special_hi | – / – | – / – |
| 659 | 120 | 834 | 175 | 295 | 20 jump_squat | 783 | 124 | 244 | later | 20 jump_squat | – / – | – / – |
| 660 | 121 | 835 | 175 | 296 | 20 jump_squat | – | – | – | no_exit | – | – / – | – / – |
| 661 | 122 | 836 | 175 | 297 | 20 jump_squat | 785 | 124 | 246 | later | 20 jump_squat | – / – | – / – |
| 662 | 123 | 837 | 175 | 298 | 20 jump_squat | 786 | 124 | 247 | later | 20 jump_squat | – / – | – / – |
| 663 | 124 | 838 | 175 | 299 | 20 jump_squat | 787 | 124 | 248 | later | 20 jump_squat | – / – | – / – |
| 664 | 125 | 839 | 175 | 0 | 20 jump_squat | 788 | 124 | 249 | later | 20 jump_squat | – / – | – / – |
| 665 | 126 | 840 | 175 | 1 | 20 jump_squat | 789 | 124 | 250 | later | 20 jump_squat | – / – | – / – |
| 666 | 127 | 841 | 175 | 2 | 20 jump_squat | 790 | 124 | 251 | later | 20 jump_squat | – / – | – / – |
| 667 | 128 | 842 | 175 | 3 | 20 jump_squat | 791 | 124 | 252 | later | 20 jump_squat | – / – | – / – |
| 668 | 129 | 843 | 175 | 4 | 20 jump_squat | 792 | 124 | 253 | later | 20 jump_squat | – / – | – / – |
| 669 | 130 | 844 | 175 | 5 | 20 jump_squat | 793 | 124 | 254 | later | 20 jump_squat | – / – | – / – |
| 670 | 131 | 845 | 175 | 6 | 20 jump_squat | 794 | 124 | 255 | later | 20 jump_squat | – / – | – / – |
| 671 | 132 | 846 | 175 | 7 | 20 jump_squat | 795 | 124 | 256 | later | 20 jump_squat | – / – | – / – |
| 672 | 133 | 716 | 44 | 177 | 20 jump_squat | 796 | 124 | 257 | later | 20 jump_squat | – / – | – / – |
| 673 | 134 | 716 | 43 | 177 | 20 jump_squat | 797 | 124 | 258 | later | 20 jump_squat | – / – | – / – |
| 674 | 135 | 716 | 42 | 177 | 20 jump_squat | 798 | 124 | 259 | later | 20 jump_squat | – / – | – / – |
| 675 | 136 | 717 | 42 | 178 | 20 jump_squat | 717 | 42 | 178 | later | 21 jump_squat | – / – | – / – |
| 676 | 137 | 718 | 42 | 179 | 20 jump_squat | 717 | 41 | 178 | later | 21 jump_squat | – / – | – / – |
| 677 | 138 | 852 | 175 | 13 | 20 jump_squat | 718 | 41 | 179 | later | 21 jump_squat | – / – | – / – |
| 678 | 139 | 853 | 175 | 14 | 20 jump_squat | 719 | 41 | 180 | later | 21 jump_squat | – / – | – / – |
| 679 | 140 | 748 | 69 | 209 | 20 jump_squat | 720 | 41 | 181 | later | 21 jump_squat | – / – | – / – |
| 680 | 141 | 855 | 175 | 16 | 20 jump_squat | 721 | 41 | 182 | later | 21 jump_squat | – / – | – / – |
| 681 | 142 | 856 | 175 | 17 | 20 jump_squat | 722 | 41 | 183 | later | 21 jump_squat | – / – | – / – |
| 682 | 143 | 857 | 175 | 18 | 20 jump_squat | 723 | 41 | 184 | later | 21 jump_squat | – / – | – / – |
| 683 | 144 | 858 | 175 | 19 | 20 jump_squat | 724 | 41 | 185 | later | 21 jump_squat | – / – | – / – |
| 684 | 145 | 859 | 175 | 20 | 20 jump_squat | 725 | 41 | 186 | later | 21 jump_squat | – / – | – / – |
| 685 | 146 | 860 | 175 | 21 | 20 jump_squat | 726 | 41 | 187 | later | 21 jump_squat | – / – | – / – |
| 686 | 147 | 861 | 175 | 22 | 20 jump_squat | 727 | 41 | 188 | later | 21 jump_squat | – / – | – / – |
| 687 | 148 | 890 | 203 | 51 | 152 shield | 728 | 41 | 189 | later | 21 jump_squat | – / – | – / – |
| 688 | 149 | 748 | 60 | 209 | 28 crouch_pass | 729 | 41 | 190 | later | 21 jump_squat | – / – | – / – |
| 689 | 150 | 749 | 60 | 210 | 28 crouch_pass | 730 | 41 | 191 | later | 21 jump_squat | – / – | – / – |
| 690 | 151 | 865 | 175 | 26 | 20 jump_squat | 731 | 41 | 192 | later | 21 jump_squat | – / – | – / – |
| 691 | 152 | 866 | 175 | 27 | 20 jump_squat | 732 | 41 | 193 | later | 21 jump_squat | – / – | – / – |
| 692 | 153 | 867 | 175 | 28 | 20 jump_squat | 733 | 41 | 194 | later | 21 jump_squat | – / – | – / – |
| 693 | 154 | 868 | 175 | 29 | 20 jump_squat | – | – | – | no_exit | – | – / – | – / – |
| 694 | 155 | 897 | 203 | 58 | 152 shield | – | – | – | no_exit | – | – / – | – / – |
| 695 | 156 | 898 | 203 | 59 | 152 shield | – | – | – | no_exit | – | – / – | – / – |
| 696 | 157 | 716 | 20 | 177 | 20 jump_squat | – | – | – | no_exit | – | – / – | – / – |
| 697 | 158 | 716 | 19 | 177 | 20 jump_squat | – | – | – | no_exit | – | – / – | – / – |
| 698 | 159 | 716 | 18 | 177 | 20 jump_squat | – | – | – | no_exit | – | – / – | – / – |
| 699 | 160 | 874 | 175 | 35 | 20 jump_squat | 716 | 17 | 177 | later | 28 crouch_pass | – / – | – / – |
| 700 | 161 | 875 | 175 | 36 | 20 jump_squat | 716 | 16 | 177 | later | 28 crouch_pass | – / – | – / – |
| 701 | 162 | 876 | 175 | 37 | 20 jump_squat | 716 | 15 | 177 | later | 15 dash_run | – / – | – / – |
| 702 | 163 | 877 | 175 | 38 | 20 jump_squat | 785 | 83 | 246 | later | 225 special_hi | – / – | – / – |
| 703 | 164 | 878 | 175 | 39 | 20 jump_squat | 827 | 124 | 288 | later | 20 jump_squat | – / – | – / – |
| 704 | 165 | 879 | 175 | 40 | 20 jump_squat | 828 | 124 | 289 | later | 20 jump_squat | – / – | – / – |
| 705 | 166 | 880 | 175 | 41 | 20 jump_squat | 788 | 83 | 249 | later | 225 special_hi | – / – | – / – |
| 706 | 167 | 881 | 175 | 42 | 20 jump_squat | 830 | 124 | 291 | later | 20 jump_squat | – / – | – / – |
| 707 | 168 | 882 | 175 | 43 | 20 jump_squat | 716 | 9 | 177 | later | 225 special_hi | – / – | – / – |
| 708 | 169 | 883 | 175 | 44 | 20 jump_squat | 717 | 9 | 178 | later | 225 special_hi | – / – | – / – |
| 709 | 170 | 884 | 175 | 45 | 20 jump_squat | 718 | 9 | 179 | later | 225 special_hi | – / – | – / – |
| 710 | 171 | 885 | 175 | 46 | 20 jump_squat | 719 | 9 | 180 | later | 225 special_hi | – / – | – / – |
| 711 | 172 | 886 | 175 | 47 | 20 jump_squat | 720 | 9 | 181 | later | 225 special_hi | – / – | – / – |
| 712 | 173 | 887 | 175 | 48 | 20 jump_squat | 721 | 9 | 182 | later | 225 special_hi | – / – | – / – |
| 713 | 174 | 888 | 175 | 49 | 20 jump_squat | 722 | 9 | 183 | later | 225 special_hi | – / – | – / – |
| 714 | 175 | 716 | 2 | 177 | 28 crouch_pass | 716 | 2 | 177 | later | 20 jump_squat | – / – | – / – |
| 715 | 176 | 716 | 1 | 177 | 15 dash_run | 716 | 1 | 177 | later | 20 jump_squat | – / – | – / – |

**Distribution of departure_tick − d:**

| variant | departure_tick − d | rows | d | departure ticks |
|---|---|---|---|---|
| a | 1 | 1 | 715 | 716 |
| a | 2 | 1 | 714 | 716 |
| a | 18 | 1 | 698 | 716 |
| a | 19 | 1 | 697 | 716 |
| a | 20 | 1 | 696 | 716 |
| a | 42 | 3 | 674..676 | 716..718 |
| a | 43 | 1 | 673 | 716 |
| a | 44 | 1 | 672 | 716 |
| a | 60 | 3 | 656, 688..689 | 716, 748..749 |
| a | 69 | 2 | 647, 679 | 716, 748 |
| a | 70 | 1 | 646 | 716 |
| a | 72 | 2 | 644..645 | 716..717 |
| a | 175 | 55 | 639..643, 649..655, 657..671, 677..678, 680..686, 690..693, 699..713 | 814..818, 824..830, 832..846, 852..853, 855..861, 865..868, 874..888 |
| a | 203 | 3 | 687, 694..695 | 890, 897..898 |
| a | 244 | 1 | 648 | 892 |
| g1 | 1 | 1 | 715 | 716 |
| g1 | 2 | 1 | 714 | 716 |
| g1 | 9 | 7 | 707..713 | 716..722 |
| g1 | 15 | 1 | 701 | 716 |
| g1 | 16 | 1 | 700 | 716 |
| g1 | 17 | 1 | 699 | 716 |
| g1 | 41 | 17 | 676..692 | 717..733 |
| g1 | 42 | 1 | 675 | 717 |
| g1 | 83 | 18 | 639..642, 647..658, 702, 705 | 722..725, 730..741, 785, 788 |
| g1 | 124 | 18 | 659, 661..674, 703..704, 706 | 783, 785..798, 827..828, 830 |
| g1 | 256 | 1 | 644 | 900 |
| g1 | none (no_exit) | 10 | 643, 645..646, 660, 693..698 | – |

Reading:

- **No row departs before 716.** The earliest departure is 716 (a 12 rows, g1 6 rows). 716..718 hold 15 rows of a and 11 of g1 (17 %), so some rows meet the clear's
  own departure tick, but most do not.
- **Most rows depart a fixed offset after d, and that offset belongs to the exit, not to the state.** For a, 55 of 77 rows depart at d + 175 (departures 814..888,
  phases 275..49). For g1, 18 rows depart at d + 83, 18 at d + 124, 17 at d + 41 and 7 at d + 9. One exit is the same word sequence at every d, so a fixed offset
  means the take-off came from the same word of that exit, at whatever tick the exit reached it.
- So there are two patterns, both at or after 716: a take-off on the first ticks after 716, or a take-off at a fixed offset into the exit.

## 4. Part B: why no take-off begins at d + 1

### 4.1 The clear's own trace, ticks 630..720

Status runs (the run of status 227 began at 627, with timer 0, so the timer is 3 at 630):

| status | class | ground/air | first tick | length | status timer (status_total_tics) |
|---|---|---|---|---|---|
| 227 | special_lw | grounded | 630 | 87 | 3..89 |
| 20 | jump_squat | grounded | 717 | 3 | 0..2 |
| 22 | airborne | airborne | 720 | 1 | 0..0 |

Per tick (g = grounded, a = airborne; timer = `entity.fighter.status_total_tics`; group 2 velocity = `spatial.groups[2].speed[1]`, equal on every tick to the change of
the translation from the previous tick):

| tick | phase | status | ground/air | timer | hitlag | fighter x | fighter y | group 2 translation y | group 2 velocity y |
|---|---|---|---|---|---|---|---|---|---|
| 630 | 91 | 227 | g | 3 | 0 | 3167.4 | 2983.6 | 2683.63 | +17.231 |
| 631 | 92 | 227 | g | 4 | 0 | 3161.8 | 3000.8 | 2700.76 | +17.129 |
| 632 | 93 | 227 | g | 5 | 0 | 3154.2 | 3017.8 | 2717.78 | +17.020 |
| 633 | 94 | 227 | g | 6 | 0 | 3144.6 | 3034.7 | 2734.68 | +16.905 |
| 634 | 95 | 227 | g | 7 | 0 | 3133.0 | 3051.5 | 2751.47 | +16.783 |
| 635 | 96 | 227 | g | 8 | 0 | 3119.4 | 3068.1 | 2768.12 | +16.655 |
| 636 | 97 | 227 | g | 9 | 0 | 3105.8 | 3084.6 | 2784.64 | +16.521 |
| 637 | 98 | 227 | g | 10 | 0 | 3092.2 | 3101.0 | 2801.02 | +16.380 |
| 638 | 99 | 227 | g | 11 | 0 | 3078.6 | 3117.3 | 2817.25 | +16.233 |
| 639 | 100 | 227 | g | 12 | 5 | 3065.0 | 3133.3 | 2833.33 | +16.079 |
| 640 | 101 | 227 | g | 13 | 4 | 3065.0 | 3149.3 | 2849.25 | +15.919 |
| 641 | 102 | 227 | g | 14 | 3 | 3065.0 | 3165.0 | 2865.00 | +15.753 |
| 642 | 103 | 227 | g | 15 | 2 | 3065.0 | 3180.6 | 2880.58 | +15.580 |
| 643 | 104 | 227 | g | 16 | 1 | 3065.0 | 3196.0 | 2895.98 | +15.400 |
| 644 | 105 | 227 | g | 17 | 0 | 3051.4 | 3211.2 | 2911.20 | +15.215 |
| 645 | 106 | 227 | g | 18 | 0 | 3037.8 | 3226.2 | 2926.22 | +15.023 |
| 646 | 107 | 227 | g | 19 | 0 | 3024.2 | 3241.0 | 2941.05 | +14.825 |
| 647 | 108 | 227 | g | 20 | 0 | 3010.6 | 3255.7 | 2955.67 | +14.620 |
| 648 | 109 | 227 | g | 21 | 0 | 2997.0 | 3270.1 | 2970.08 | +14.408 |
| 649 | 110 | 227 | g | 22 | 0 | 2983.4 | 3284.3 | 2984.27 | +14.191 |
| 650 | 111 | 227 | g | 23 | 0 | 2969.8 | 3298.2 | 2998.23 | +13.967 |
| 651 | 112 | 227 | g | 24 | 0 | 2956.2 | 3312.0 | 3011.97 | +13.737 |
| 652 | 113 | 227 | g | 25 | 0 | 2942.6 | 3325.5 | 3025.47 | +13.500 |
| 653 | 114 | 227 | g | 26 | 0 | 2929.0 | 3338.7 | 3038.73 | +13.257 |
| 654 | 115 | 227 | g | 27 | 0 | 2913.4 | 3351.7 | 3051.73 | +13.007 |
| 655 | 116 | 227 | g | 28 | 0 | 2896.4 | 3364.5 | 3064.48 | +12.751 |
| 656 | 117 | 227 | g | 29 | 0 | 2879.4 | 3377.0 | 3076.97 | +12.488 |
| 657 | 118 | 227 | g | 30 | 0 | 2862.4 | 3389.2 | 3089.19 | +12.220 |
| 658 | 119 | 227 | g | 31 | 0 | 2845.4 | 3401.1 | 3101.14 | +11.945 |
| 659 | 120 | 227 | g | 32 | 0 | 2828.4 | 3412.8 | 3112.80 | +11.663 |
| 660 | 121 | 227 | g | 33 | 0 | 2811.4 | 3424.2 | 3124.17 | +11.375 |
| 661 | 122 | 227 | g | 34 | 0 | 2794.4 | 3435.3 | 3135.26 | +11.081 |
| 662 | 123 | 227 | g | 35 | 0 | 2777.4 | 3446.0 | 3146.04 | +10.780 |
| 663 | 124 | 227 | g | 36 | 0 | 2760.4 | 3456.5 | 3156.51 | +10.473 |
| 664 | 125 | 227 | g | 37 | 0 | 2743.4 | 3466.7 | 3166.67 | +10.159 |
| 665 | 126 | 227 | g | 38 | 0 | 2726.4 | 3476.5 | 3176.51 | +9.839 |
| 666 | 127 | 227 | g | 39 | 0 | 2709.4 | 3486.0 | 3186.02 | +9.513 |
| 667 | 128 | 227 | g | 40 | 0 | 2692.4 | 3495.2 | 3195.20 | +9.179 |
| 668 | 129 | 227 | g | 41 | 0 | 2675.4 | 3504.0 | 3204.04 | +8.841 |
| 669 | 130 | 227 | g | 42 | 0 | 2658.4 | 3512.5 | 3212.53 | +8.494 |
| 670 | 131 | 227 | g | 43 | 0 | 2641.4 | 3520.7 | 3220.68 | +8.143 |
| 671 | 132 | 227 | g | 44 | 0 | 2624.4 | 3528.5 | 3228.46 | +7.784 |
| 672 | 133 | 227 | g | 45 | 0 | 2607.4 | 3535.9 | 3235.88 | +7.420 |
| 673 | 134 | 227 | g | 46 | 0 | 2592.4 | 3542.9 | 3242.93 | +7.048 |
| 674 | 135 | 227 | g | 47 | 0 | 2579.4 | 3549.6 | 3249.60 | +6.671 |
| 675 | 136 | 227 | g | 48 | 0 | 2568.4 | 3555.9 | 3255.89 | +6.287 |
| 676 | 137 | 227 | g | 49 | 0 | 2559.4 | 3561.8 | 3261.78 | +5.897 |
| 677 | 138 | 227 | g | 50 | 0 | 2552.4 | 3567.3 | 3267.28 | +5.500 |
| 678 | 139 | 227 | g | 51 | 0 | 2547.4 | 3572.4 | 3272.38 | +5.096 |
| 679 | 140 | 227 | g | 52 | 0 | 2544.4 | 3577.1 | 3277.07 | +4.687 |
| 680 | 141 | 227 | g | 53 | 0 | 2543.4 | 3581.3 | 3281.34 | +4.271 |
| 681 | 142 | 227 | g | 54 | 0 | 2543.4 | 3585.2 | 3285.19 | +3.849 |
| 682 | 143 | 227 | g | 55 | 0 | 2543.4 | 3588.6 | 3288.61 | +3.420 |
| 683 | 144 | 227 | g | 56 | 0 | 2543.4 | 3591.6 | 3291.59 | +2.984 |
| 684 | 145 | 227 | g | 57 | 0 | 2543.4 | 3594.1 | 3294.13 | +2.543 |
| 685 | 146 | 227 | g | 58 | 0 | 2543.4 | 3596.2 | 3296.23 | +2.095 |
| 686 | 147 | 227 | g | 59 | 0 | 2543.4 | 3597.9 | 3297.87 | +1.640 |
| 687 | 148 | 227 | g | 60 | 0 | 2543.4 | 3599.0 | 3299.05 | +1.180 |
| 688 | 149 | 227 | g | 61 | 0 | 2543.4 | 3599.8 | 3299.76 | +0.713 |
| 689 | 150 | 227 | g | 62 | 0 | 2543.4 | 3600.0 | 3300.00 | +0.239 |
| 690 | 151 | 227 | g | 63 | 0 | 2543.4 | 3599.8 | 3299.76 | -0.239 |
| 691 | 152 | 227 | g | 64 | 0 | 2543.4 | 3599.0 | 3299.05 | -0.713 |
| 692 | 153 | 227 | g | 65 | 0 | 2543.4 | 3597.9 | 3297.87 | -1.180 |
| 693 | 154 | 227 | g | 66 | 0 | 2543.4 | 3596.2 | 3296.23 | -1.640 |
| 694 | 155 | 227 | g | 67 | 0 | 2543.4 | 3594.1 | 3294.13 | -2.095 |
| 695 | 156 | 227 | g | 68 | 0 | 2543.4 | 3591.6 | 3291.59 | -2.543 |
| 696 | 157 | 227 | g | 69 | 0 | 2543.4 | 3588.6 | 3288.61 | -2.985 |
| 697 | 158 | 227 | g | 70 | 0 | 2543.4 | 3585.2 | 3285.19 | -3.420 |
| 698 | 159 | 227 | g | 71 | 0 | 2543.4 | 3581.3 | 3281.34 | -3.849 |
| 699 | 160 | 227 | g | 72 | 0 | 2543.4 | 3577.1 | 3277.07 | -4.271 |
| 700 | 161 | 227 | g | 73 | 0 | 2543.4 | 3572.4 | 3272.38 | -4.687 |
| 701 | 162 | 227 | g | 74 | 0 | 2543.4 | 3567.3 | 3267.28 | -5.097 |
| 702 | 163 | 227 | g | 75 | 0 | 2543.4 | 3561.8 | 3261.78 | -5.500 |
| 703 | 164 | 227 | g | 76 | 0 | 2543.4 | 3555.9 | 3255.89 | -5.896 |
| 704 | 165 | 227 | g | 77 | 0 | 2543.4 | 3549.6 | 3249.60 | -6.287 |
| 705 | 166 | 227 | g | 78 | 0 | 2543.4 | 3542.9 | 3242.93 | -6.671 |
| 706 | 167 | 227 | g | 79 | 0 | 2543.4 | 3535.9 | 3235.88 | -7.049 |
| 707 | 168 | 227 | g | 80 | 0 | 2543.4 | 3528.5 | 3228.46 | -7.420 |
| 708 | 169 | 227 | g | 81 | 0 | 2543.4 | 3520.7 | 3220.68 | -7.785 |
| 709 | 170 | 227 | g | 82 | 0 | 2543.4 | 3512.5 | 3212.53 | -8.143 |
| 710 | 171 | 227 | g | 83 | 0 | 2543.4 | 3504.0 | 3204.04 | -8.495 |
| 711 | 172 | 227 | g | 84 | 0 | 2543.4 | 3495.2 | 3195.20 | -8.840 |
| 712 | 173 | 227 | g | 85 | 0 | 2543.4 | 3486.0 | 3186.02 | -9.180 |
| 713 | 174 | 227 | g | 86 | 0 | 2543.4 | 3476.5 | 3176.51 | -9.512 |
| 714 | 175 | 227 | g | 87 | 0 | 2543.4 | 3466.7 | 3166.67 | -9.839 |
| 715 | 176 | 227 | g | 88 | 0 | 2543.4 | 3456.5 | 3156.51 | -10.159 |
| 716 | 177 | 227 | g | 89 | 0 | 2543.4 | 3446.0 | 3146.04 | -10.473 |
| 717 | 178 | 20 | g | 0 | 0 | 2543.4 | 3435.3 | 3135.26 | -10.780 |
| 718 | 179 | 20 | g | 1 | 0 | 2543.4 | 3424.2 | 3124.18 | -11.081 |
| 719 | 180 | 20 | g | 2 | 0 | 2543.4 | 3412.8 | 3112.80 | -11.375 |
| 720 | 181 | 22 | a | 0 | 0 | 2513.6 | 3480.5 | 3101.14 | -11.663 |

What the trace shows:

- From 627 to 716 the fighter is in **one grounded run of status 227 (special_lw)**, 90 ticks, timer 0..89, on line 19. Target 2 breaks at 639 inside the run (live
  mask 326 → 322). Hitlag is 5..1 on 639..643, and the position holds at x 3,065.0 while the timer keeps counting.
- The group rises to its top at 689 (y 3,300.0) and falls after it. At 716 it is at y 3,146.04, falling at −10.47 per tick.
- The take-off run (status 20, jump_squat, 3 ticks) starts at 717. That is the tick after the special_lw run's last tick, and the input record at 717 shows a newly
  pressed button. The fighter is airborne from 720.
- The clear's own input record also shows that button newly pressed at 652, inside the run, and status 227 continued (stick (0, 80) there, (−80, −80) at 717).

### 4.2 The candidates d = 639, 650, 672 and 700 (the clear's exit), from d to the measured departure

**d = 639** (phase 100; measured departure 814, Δ 175; S 815, G 817, A 818; outcome fall):

| status | class | ground/air | first tick | length |
|---|---|---|---|---|
| 227 | special_lw | grounded | 639 | 32 |
| 228 | special_lw | airborne | 671 | 15 |
| 227 | special_lw | grounded | 686 | 31 |
| 13 | idle_ground | grounded | 717 | 3 |
| 166 | attack_ground | grounded | 720 | 15 |
| 152 | shield | grounded | 735 | 3 |
| 153 | shield | grounded | 738 | 2 |
| 156 | roll | grounded | 740 | 31 |
| 152 | shield | grounded | 771 | 2 |
| 156 | roll | grounded | 773 | 31 |
| 28 | crouch_pass | grounded | 804 | 7 |
| 29 | crouch_pass | grounded | 811 | 4 |
| 20 | jump_squat | grounded | 815 | 3 |
| 23 | airborne | airborne | 818 | 1 |

**d = 650** (phase 111; measured departure 825, Δ 175; S 826, G 828, A 829; outcome fall):

| status | class | ground/air | first tick | length |
|---|---|---|---|---|
| 227 | special_lw | grounded | 650 | 67 |
| 152 | shield | grounded | 717 | 2 |
| 156 | roll | grounded | 719 | 31 |
| 152 | shield | grounded | 750 | 1 |
| 157 | roll | grounded | 751 | 31 |
| 152 | shield | grounded | 782 | 2 |
| 156 | roll | grounded | 784 | 31 |
| 28 | crouch_pass | grounded | 815 | 7 |
| 29 | crouch_pass | grounded | 822 | 4 |
| 20 | jump_squat | grounded | 826 | 3 |
| 23 | airborne | airborne | 829 | 1 |

**d = 672** (phase 133; measured departure 716, Δ 44; S 717, G 719, A 720; outcome budget_end):

| status | class | ground/air | first tick | length |
|---|---|---|---|---|
| 227 | special_lw | grounded | 672 | 45 |
| 20 | jump_squat | grounded | 717 | 3 |
| 22 | airborne | airborne | 720 | 1 |

**d = 700** (phase 161; measured departure 875, Δ 175; S 876, G 878, A 879; outcome fall):

| status | class | ground/air | first tick | length |
|---|---|---|---|---|
| 227 | special_lw | grounded | 700 | 17 |
| 166 | attack_ground | grounded | 717 | 15 |
| 223 | special_n | grounded | 732 | 45 |
| 13 | idle_ground | grounded | 777 | 4 |
| 166 | attack_ground | grounded | 781 | 15 |
| 152 | shield | grounded | 796 | 3 |
| 153 | shield | grounded | 799 | 2 |
| 156 | roll | grounded | 801 | 31 |
| 152 | shield | grounded | 832 | 2 |
| 156 | roll | grounded | 834 | 31 |
| 28 | crouch_pass | grounded | 865 | 7 |
| 29 | crouch_pass | grounded | 872 | 4 |
| 20 | jump_squat | grounded | 876 | 3 |
| 23 | airborne | airborne | 879 | 1 |

### 4.3 Across all 154 rows with d in 639..715

- **Status at d + 1:** 227 (special_lw, grounded) in 154 of 154 rows. For a, the input record at d + 1 shows the same stick (−80, −80) and the same newly pressed
  button as the clear's at 717 in 75 rows. In the other 2 (d = 652, 653), the button is already held from the prefix's last word. So in all 77 rows the clear's
  take-off word reached the fighter at d, and no take-off followed.
- **The special_lw run ends at 716 in every row.** The run of class special_lw that contains d lasts to exactly 716 in 154 of 154 rows. In 128 rows (a 75, g1 53)
  it is status 227 throughout. In 26 rows (a: d 639, 640; g1: d 639..662) the fighter passes through status 228 (also special_lw), airborne for 13 to 32 ticks and still
  above line 19, then returns to grounded status 227, and the special_lw run still ends at 716. Those hops never leave the group's line, so the D rule does not count
  them as departures.
- **No status 20 starts before 717** in any of the 154 rows. The first status-20 tick is 717 in 14 rows (a 10, g1 4) and later in 120. Twenty rows have none.
- **The inputs do change other things inside the run.** For d 639..652 (14 rows of each exit), the fighter's x first differs from the clear's before 717, at 644 at
  the earliest (the first tick after the hitlag); x is the only field that differs at that tick. In the other 10 g1 rows (d 653..662) the first difference is the
  status-228 hop. None of this ends the run before 716.
- **After 716** the fighter takes the status the exit's words give at that point (idle, shield, roll, crouch, ground attack, another special, ...), and it departs
  at the exit's next take-off. For the clear's exit, that is usually the word at offset 175 (part A). The exit's offset-0 word was used up inside the run.

**In plain terms:** at every d from 639 to 715, the clear's fighter is in the middle of one grounded special move that started at 627 and, in this record, always runs
to 716. Of the 154 input streams tried, including the clear's own take-off input, none ended it early or started a take-off inside it. A take-off can therefore begin
no earlier than 717, and the earliest measured departure (by the D rule) is 716 in every row. This describes what the records show. It does not say why the game
behaves this way.

**Context from the pre-break part (same exit, same rule, d 545..638), for comparison only:**

| clear status run (class) | d | variant a departed at d | measured departures (variant a) |
|---|---|---|---|
| 59 (landing_lag) | 545..568 | no (24) | 569, 628..643, 721, 726, 750..751 |
| 59 (landing_lag) | 569 | yes (1) | 569 |
| 18 (idle_ground) | 570..575 | yes (6) | 570..575 |
| 166 (attack_ground) | 576..589 | no (14) | 590, 652..664 |
| 166 (attack_ground) | 590 | yes (1) | 590 |
| 28 (crouch_pass) | 591..594 | yes (4) | 591..594 |
| 152 (shield) | 595 | no (1) | 626 |
| 157 (roll) | 596..625 | no (30) | 626, 658..659, 771, 778, 784..798, 800, 807..808 |
| 157 (roll) | 626 | yes (1) | 626 |
| 227 (special_lw) | 627..638 | no (12) | 716, 802..804, 808..813 |

The clear's exit departs at d only when d is inside an idle_ground or crouch_pass run, or on the last tick of a landing_lag, attack_ground or roll run (569, 590,
626). Inside those runs it departs later, often on the run's last tick (569, 590, 626) or at 716. The rows at 639..715 follow the same pattern: their run is the
special_lw run, and its last tick is 716 = D.

## 5. Part C: the later rows without a break (d 742..930 and 973..999)

All 216 rows are the clear's exit, and all depart at d (departure_tick − d = 0). The generic exit never departs at d anywhere in the later window (300 of 300 rows are
`later`), so the later side was tested by the clear's exit only.

| d | phases | rows | departed at d | landing tick − d | landing line, x, y | any break | outcome | end state (status, line, x, y, live mask) |
|---|---|---|---|---|---|---|---|---|
| 742..915 | 203..76 | 174 | 174 | 246 (174) | line 4, x -987.2, y -2550.0 | 0 | budget_end 174 | 10 idle_ground, line 4, x -981.6, y -2550.0, mask 322 (174 of 174) |
| 916..930 | 77..91 | 15 | 15 | 246 (15) | line 4, x -987.2, y -2550.0 | 0 | budget_end 15 | 10 idle_ground, line 4, x -981.6, y -2550.0, mask 322 (15 of 15) |
| 973..999 | 134..160 | 27 | 27 | 192 (27) | line 0, x -1936.6..-1906.4, y 3000.0 | 0 | budget_end 27 | 10 idle_ground, line 3, x -3806.1..-3776.0, y -1950.0, mask 322 (27 of 27) |

- **742..930 (phases 203..91, 189 rows):** they depart at d, land 246 ticks later on static line 4 at (−987.2, −2,550.0), and stay there idle to the end of the
  budget. The clear lands at D + 189 on line 0. No break; the live mask stays 322 (targets 1, 6 and 8 live). This range covers the band's later outside part
  (742..915) and the start of the band (916..930).
- **973..999 (phases 134..160, 27 rows):** they depart at d and land 192 ticks later on line 0 at y 3,000.0, the clear's landing line, x −1,936.6..−1,906.4. They end
  idle on line 3 at y −1,950.0, x −3,806.1..−3,776.0. No break; mask 322.
- Together with part D, the clear's exit applied to the group's next cycle succeeds at phases 177..202 (716..741), 92..133 (931..972) and 161..177 (1,000..1,016). It
  breaks nothing at phases 203..91 (742..930) and 134..160 (973..999).

## 6. Part D: the counted successes

85 rows: 716..741 (26, including the control at 716), 931..972 (42) and 1,000..1,016 (17). All are the clear's exit, all depart at d, and in every one the first break
after d is target 6 and is also the progress tick.

| d | phase | progress_tick | progress − d | first break (target) | group y translation at d | group y velocity at d | group | fighter status at d | fighter y at d (take-off height) | fighter y − group y | landing tick − d |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 716 | 177 | 1042 | 326 | 1042 (6) | 3146.04 | -10.473 | falling | 227 special_lw | 3446.0 | 300.0 | 189 |
| 717 | 178 | 1043 | 326 | 1043 (6) | 3135.26 | -10.780 | falling | 10 idle_ground | 3435.3 | 300.0 | 189 |
| 718 | 179 | 1044 | 326 | 1044 (6) | 3124.18 | -11.081 | falling | 10 idle_ground | 3424.2 | 300.0 | 189 |
| 719 | 180 | 1045 | 326 | 1045 (6) | 3112.80 | -11.375 | falling | 10 idle_ground | 3412.8 | 300.0 | 189 |
| 720 | 181 | 1046 | 326 | 1046 (6) | 3101.14 | -11.663 | falling | 10 idle_ground | 3401.1 | 300.0 | 189 |
| 721 | 182 | 1047 | 326 | 1047 (6) | 3089.19 | -11.945 | falling | 10 idle_ground | 3389.2 | 300.0 | 189 |
| 722 | 183 | 1048 | 326 | 1048 (6) | 3076.97 | -12.219 | falling | 10 idle_ground | 3377.0 | 300.0 | 188 |
| 723 | 184 | 1049 | 326 | 1049 (6) | 3064.48 | -12.489 | falling | 10 idle_ground | 3364.5 | 300.0 | 188 |
| 724 | 185 | 1050 | 326 | 1050 (6) | 3051.73 | -12.751 | falling | 10 idle_ground | 3351.7 | 300.0 | 188 |
| 725 | 186 | 1051 | 326 | 1051 (6) | 3038.73 | -13.007 | falling | 10 idle_ground | 3338.7 | 300.0 | 188 |
| 726 | 187 | 1052 | 326 | 1052 (6) | 3025.47 | -13.257 | falling | 10 idle_ground | 3325.5 | 300.0 | 187 |
| 727 | 188 | 1053 | 326 | 1053 (6) | 3011.97 | -13.500 | falling | 10 idle_ground | 3312.0 | 300.0 | 187 |
| 728 | 189 | 1054 | 326 | 1054 (6) | 2998.23 | -13.737 | falling | 10 idle_ground | 3298.2 | 300.0 | 187 |
| 729 | 190 | 1055 | 326 | 1055 (6) | 2984.27 | -13.967 | falling | 10 idle_ground | 3284.3 | 300.0 | 187 |
| 730 | 191 | 1056 | 326 | 1056 (6) | 2970.08 | -14.191 | falling | 10 idle_ground | 3270.1 | 300.0 | 187 |
| 731 | 192 | 1057 | 326 | 1057 (6) | 2955.67 | -14.409 | falling | 10 idle_ground | 3255.7 | 300.0 | 186 |
| 732 | 193 | 1058 | 326 | 1058 (6) | 2941.05 | -14.620 | falling | 10 idle_ground | 3241.0 | 300.0 | 186 |
| 733 | 194 | 1059 | 326 | 1059 (6) | 2926.22 | -14.824 | falling | 10 idle_ground | 3226.2 | 300.0 | 186 |
| 734 | 195 | 1060 | 326 | 1060 (6) | 2911.20 | -15.023 | falling | 10 idle_ground | 3211.2 | 300.0 | 186 |
| 735 | 196 | 1061 | 326 | 1061 (6) | 2895.99 | -15.215 | falling | 10 idle_ground | 3196.0 | 300.0 | 185 |
| 736 | 197 | 1062 | 326 | 1062 (6) | 2880.58 | -15.401 | falling | 10 idle_ground | 3180.6 | 300.0 | 185 |
| 737 | 198 | 1063 | 326 | 1063 (6) | 2865.00 | -15.580 | falling | 10 idle_ground | 3165.0 | 300.0 | 185 |
| 738 | 199 | 1064 | 326 | 1064 (6) | 2849.25 | -15.753 | falling | 10 idle_ground | 3149.3 | 300.0 | 184 |
| 739 | 200 | 1065 | 326 | 1065 (6) | 2833.33 | -15.919 | falling | 10 idle_ground | 3133.3 | 300.0 | 184 |
| 740 | 201 | 1066 | 326 | 1066 (6) | 2817.25 | -16.079 | falling | 10 idle_ground | 3117.3 | 300.0 | 184 |
| 741 | 202 | 1067 | 326 | 1067 (6) | 2801.02 | -16.232 | falling | 10 idle_ground | 3101.0 | 300.0 | 183 |
| 931 | 92 | 1257 | 326 | 1257 (6) | 2700.76 | +17.129 | rising | 10 idle_ground | 3000.8 | 300.0 | 183 |
| 932 | 93 | 1258 | 326 | 1258 (6) | 2717.78 | +17.020 | rising | 10 idle_ground | 3017.8 | 300.0 | 184 |
| 933 | 94 | 1259 | 326 | 1259 (6) | 2734.68 | +16.905 | rising | 10 idle_ground | 3034.7 | 300.0 | 184 |
| 934 | 95 | 1260 | 326 | 1260 (6) | 2751.47 | +16.783 | rising | 10 idle_ground | 3051.5 | 300.0 | 184 |
| 935 | 96 | 1261 | 326 | 1261 (6) | 2768.12 | +16.655 | rising | 10 idle_ground | 3068.1 | 300.0 | 185 |
| 936 | 97 | 1262 | 326 | 1262 (6) | 2784.64 | +16.521 | rising | 10 idle_ground | 3084.6 | 300.0 | 185 |
| 937 | 98 | 1263 | 326 | 1263 (6) | 2801.02 | +16.380 | rising | 10 idle_ground | 3101.0 | 300.0 | 185 |
| 938 | 99 | 1264 | 326 | 1264 (6) | 2817.25 | +16.233 | rising | 10 idle_ground | 3117.3 | 300.0 | 186 |
| 939 | 100 | 1265 | 326 | 1265 (6) | 2833.33 | +16.079 | rising | 10 idle_ground | 3133.3 | 300.0 | 186 |
| 940 | 101 | 1266 | 326 | 1266 (6) | 2849.25 | +15.919 | rising | 10 idle_ground | 3149.3 | 300.0 | 186 |
| 941 | 102 | 1267 | 326 | 1267 (6) | 2865.00 | +15.753 | rising | 10 idle_ground | 3165.0 | 300.0 | 186 |
| 942 | 103 | 1268 | 326 | 1268 (6) | 2880.58 | +15.580 | rising | 10 idle_ground | 3180.6 | 300.0 | 187 |
| 943 | 104 | 1269 | 326 | 1269 (6) | 2895.98 | +15.400 | rising | 10 idle_ground | 3196.0 | 300.0 | 187 |
| 944 | 105 | 1270 | 326 | 1270 (6) | 2911.20 | +15.215 | rising | 10 idle_ground | 3211.2 | 300.0 | 187 |
| 945 | 106 | 1271 | 326 | 1271 (6) | 2926.22 | +15.023 | rising | 10 idle_ground | 3226.2 | 300.0 | 187 |
| 946 | 107 | 1272 | 326 | 1272 (6) | 2941.05 | +14.825 | rising | 10 idle_ground | 3241.0 | 300.0 | 187 |
| 947 | 108 | 1273 | 326 | 1273 (6) | 2955.67 | +14.620 | rising | 10 idle_ground | 3255.7 | 300.0 | 188 |
| 948 | 109 | 1274 | 326 | 1274 (6) | 2970.08 | +14.408 | rising | 10 idle_ground | 3270.1 | 300.0 | 188 |
| 949 | 110 | 1275 | 326 | 1275 (6) | 2984.27 | +14.191 | rising | 10 idle_ground | 3284.3 | 300.0 | 188 |
| 950 | 111 | 1276 | 326 | 1276 (6) | 2998.23 | +13.967 | rising | 10 idle_ground | 3298.2 | 300.0 | 188 |
| 951 | 112 | 1277 | 326 | 1277 (6) | 3011.97 | +13.737 | rising | 10 idle_ground | 3312.0 | 300.0 | 189 |
| 952 | 113 | 1278 | 326 | 1278 (6) | 3025.47 | +13.500 | rising | 10 idle_ground | 3325.5 | 300.0 | 189 |
| 953 | 114 | 1279 | 326 | 1279 (6) | 3038.73 | +13.257 | rising | 10 idle_ground | 3338.7 | 300.0 | 189 |
| 954 | 115 | 1280 | 326 | 1280 (6) | 3051.73 | +13.007 | rising | 10 idle_ground | 3351.7 | 300.0 | 189 |
| 955 | 116 | 1281 | 326 | 1281 (6) | 3064.48 | +12.751 | rising | 10 idle_ground | 3364.5 | 300.0 | 189 |
| 956 | 117 | 1282 | 326 | 1282 (6) | 3076.97 | +12.488 | rising | 10 idle_ground | 3377.0 | 300.0 | 189 |
| 957 | 118 | 1283 | 326 | 1283 (6) | 3089.19 | +12.220 | rising | 10 idle_ground | 3389.2 | 300.0 | 190 |
| 958 | 119 | 1284 | 326 | 1284 (6) | 3101.14 | +11.945 | rising | 10 idle_ground | 3401.1 | 300.0 | 190 |
| 959 | 120 | 1285 | 326 | 1285 (6) | 3112.80 | +11.663 | rising | 10 idle_ground | 3412.8 | 300.0 | 190 |
| 960 | 121 | 1286 | 326 | 1286 (6) | 3124.17 | +11.375 | rising | 10 idle_ground | 3424.2 | 300.0 | 190 |
| 961 | 122 | 1287 | 326 | 1287 (6) | 3135.26 | +11.081 | rising | 10 idle_ground | 3435.3 | 300.0 | 190 |
| 962 | 123 | 1288 | 326 | 1288 (6) | 3146.04 | +10.780 | rising | 10 idle_ground | 3446.0 | 300.0 | 190 |
| 963 | 124 | 1289 | 326 | 1289 (6) | 3156.51 | +10.473 | rising | 10 idle_ground | 3456.5 | 300.0 | 190 |
| 964 | 125 | 1290 | 326 | 1290 (6) | 3166.67 | +10.159 | rising | 10 idle_ground | 3466.7 | 300.0 | 191 |
| 965 | 126 | 1291 | 326 | 1291 (6) | 3176.51 | +9.839 | rising | 10 idle_ground | 3476.5 | 300.0 | 191 |
| 966 | 127 | 1292 | 326 | 1292 (6) | 3186.02 | +9.513 | rising | 10 idle_ground | 3486.0 | 300.0 | 191 |
| 967 | 128 | 1293 | 326 | 1293 (6) | 3195.20 | +9.179 | rising | 10 idle_ground | 3495.2 | 300.0 | 191 |
| 968 | 129 | 1294 | 326 | 1294 (6) | 3204.04 | +8.841 | rising | 10 idle_ground | 3504.0 | 300.0 | 191 |
| 969 | 130 | 1295 | 326 | 1295 (6) | 3212.53 | +8.494 | rising | 10 idle_ground | 3512.5 | 300.0 | 191 |
| 970 | 131 | 1296 | 326 | 1296 (6) | 3220.68 | +8.143 | rising | 10 idle_ground | 3520.7 | 300.0 | 191 |
| 971 | 132 | 1297 | 326 | 1297 (6) | 3228.46 | +7.784 | rising | 10 idle_ground | 3528.5 | 300.0 | 191 |
| 972 | 133 | 1298 | 326 | 1298 (6) | 3235.88 | +7.420 | rising | 10 idle_ground | 3535.9 | 300.0 | 191 |
| 1000 | 161 | 1326 | 326 | 1326 (6) | 3272.38 | -4.687 | falling | 10 idle_ground | 3572.4 | 300.0 | 191 |
| 1001 | 162 | 1327 | 326 | 1327 (6) | 3267.28 | -5.097 | falling | 10 idle_ground | 3567.3 | 300.0 | 191 |
| 1002 | 163 | 1328 | 326 | 1328 (6) | 3261.78 | -5.500 | falling | 10 idle_ground | 3561.8 | 300.0 | 191 |
| 1003 | 164 | 1329 | 326 | 1329 (6) | 3255.89 | -5.896 | falling | 10 idle_ground | 3555.9 | 300.0 | 191 |
| 1004 | 165 | 1330 | 326 | 1330 (6) | 3249.60 | -6.287 | falling | 10 idle_ground | 3549.6 | 300.0 | 191 |
| 1005 | 166 | 1331 | 326 | 1331 (6) | 3242.93 | -6.671 | falling | 10 idle_ground | 3542.9 | 300.0 | 191 |
| 1006 | 167 | 1332 | 326 | 1332 (6) | 3235.88 | -7.049 | falling | 10 idle_ground | 3535.9 | 300.0 | 191 |
| 1007 | 168 | 1333 | 326 | 1333 (6) | 3228.46 | -7.420 | falling | 10 idle_ground | 3528.5 | 300.0 | 191 |
| 1008 | 169 | 1334 | 326 | 1334 (6) | 3220.68 | -7.785 | falling | 10 idle_ground | 3520.7 | 300.0 | 191 |
| 1009 | 170 | 1335 | 326 | 1335 (6) | 3212.53 | -8.143 | falling | 10 idle_ground | 3512.5 | 300.0 | 190 |
| 1010 | 171 | 1336 | 326 | 1336 (6) | 3204.04 | -8.495 | falling | 10 idle_ground | 3504.0 | 300.0 | 190 |
| 1011 | 172 | 1337 | 326 | 1337 (6) | 3195.20 | -8.840 | falling | 10 idle_ground | 3495.2 | 300.0 | 190 |
| 1012 | 173 | 1338 | 326 | 1338 (6) | 3186.02 | -9.180 | falling | 10 idle_ground | 3486.0 | 300.0 | 190 |
| 1013 | 174 | 1339 | 326 | 1339 (6) | 3176.51 | -9.512 | falling | 10 idle_ground | 3476.5 | 300.0 | 190 |
| 1014 | 175 | 1340 | 326 | 1340 (6) | 3166.67 | -9.839 | falling | 10 idle_ground | 3466.7 | 300.0 | 190 |
| 1015 | 176 | 1341 | 326 | 1341 (6) | 3156.51 | -10.159 | falling | 10 idle_ground | 3456.5 | 300.0 | 190 |
| 1016 | 177 | 1342 | 326 | 1342 (6) | 3146.04 | -10.473 | falling | 10 idle_ground | 3446.0 | 300.0 | 189 |

- **progress_tick − d = 326 for all 85.** Only the control (716) is not after B. Every other success reaches the baseline's progress at d + 326 > 1,042, which is d − 716
  ticks after B.
- **The group is moving at every success's departure tick.** It is rising at 931..972 (velocity +17.13 to +7.42) and falling at 716..741 (−10.47 to −16.23) and
  1,000..1,016 (−4.69 to −10.47). The translation series (the filler, ticks 0..1,016) has no still tick: |velocity| is at least 0.239 on every tick, and below 1 only
  on the four ticks around each turning point (88..91, 238..241, ..., 688..691, 988..991).
- **The take-off height differs.** The fighter's y at d runs from 3,000.8 (d 931) to 3,572.4 (d 1,000), always exactly 300.0 above the group's translation, at x
  2,543.4 (where the clear's fighter stood from 680 on). The landing tick − d varies from 183 to 191, but the target-6 break stays at d + 326.
- At d the fighter is in status 10 (idle_ground) in 84 rows and in status 227 (special_lw, timer 89) at the control.

## 7. Part E: matching phases, first cycle (d 639..672) and next cycle (d 939..972)

At d the first cycle's state is the clear's own state (each candidate's prefix equals the clear's there). The next cycle's state is the filler prefix (the clear's words
0..715, then neutral words). The next cycle's successful phases are 92..133 (931..972). Phases 92..99 fall before 639 in the first cycle (pre-break, also special_lw), so
the comparison uses phases 100..133.

| phase | first cycle d | status (class) | timer | ground | x | y − group y | ground vx | hitlag | next cycle d | status (class) | timer | ground | x | y − group y | ground vx | next-cycle result |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 100 | 639 | 227 (special_lw) | 12 | g | 3065.0 | 300.0 | 13.6 | 5 | 939 | 10 (idle_ground) | 222 | g | 2543.4 | 300.0 | 0.0 | progress 1265 (d + 326) |
| 101 | 640 | 227 (special_lw) | 13 | g | 3065.0 | 300.0 | 13.6 | 4 | 940 | 10 (idle_ground) | 223 | g | 2543.4 | 300.0 | 0.0 | progress 1266 (d + 326) |
| 102 | 641 | 227 (special_lw) | 14 | g | 3065.0 | 300.0 | 13.6 | 3 | 941 | 10 (idle_ground) | 224 | g | 2543.4 | 300.0 | 0.0 | progress 1267 (d + 326) |
| 103 | 642 | 227 (special_lw) | 15 | g | 3065.0 | 300.0 | 13.6 | 2 | 942 | 10 (idle_ground) | 225 | g | 2543.4 | 300.0 | 0.0 | progress 1268 (d + 326) |
| 104 | 643 | 227 (special_lw) | 16 | g | 3065.0 | 300.0 | 13.6 | 1 | 943 | 10 (idle_ground) | 226 | g | 2543.4 | 300.0 | 0.0 | progress 1269 (d + 326) |
| 105 | 644 | 227 (special_lw) | 17 | g | 3051.4 | 300.0 | 13.6 | 0 | 944 | 10 (idle_ground) | 227 | g | 2543.4 | 300.0 | 0.0 | progress 1270 (d + 326) |
| 106 | 645 | 227 (special_lw) | 18 | g | 3037.8 | 300.0 | 13.6 | 0 | 945 | 10 (idle_ground) | 228 | g | 2543.4 | 300.0 | 0.0 | progress 1271 (d + 326) |
| 107 | 646 | 227 (special_lw) | 19 | g | 3024.2 | 300.0 | 13.6 | 0 | 946 | 10 (idle_ground) | 229 | g | 2543.4 | 300.0 | 0.0 | progress 1272 (d + 326) |
| 108 | 647 | 227 (special_lw) | 20 | g | 3010.6 | 300.0 | 13.6 | 0 | 947 | 10 (idle_ground) | 230 | g | 2543.4 | 300.0 | 0.0 | progress 1273 (d + 326) |
| 109 | 648 | 227 (special_lw) | 21 | g | 2997.0 | 300.0 | 13.6 | 0 | 948 | 10 (idle_ground) | 231 | g | 2543.4 | 300.0 | 0.0 | progress 1274 (d + 326) |
| 110 | 649 | 227 (special_lw) | 22 | g | 2983.4 | 300.0 | 13.6 | 0 | 949 | 10 (idle_ground) | 232 | g | 2543.4 | 300.0 | 0.0 | progress 1275 (d + 326) |
| 111 | 650 | 227 (special_lw) | 23 | g | 2969.8 | 300.0 | 13.6 | 0 | 950 | 10 (idle_ground) | 233 | g | 2543.4 | 300.0 | 0.0 | progress 1276 (d + 326) |
| 112 | 651 | 227 (special_lw) | 24 | g | 2956.2 | 300.0 | 13.6 | 0 | 951 | 10 (idle_ground) | 234 | g | 2543.4 | 300.0 | 0.0 | progress 1277 (d + 326) |
| 113 | 652 | 227 (special_lw) | 25 | g | 2942.6 | 300.0 | 13.6 | 0 | 952 | 10 (idle_ground) | 235 | g | 2543.4 | 300.0 | 0.0 | progress 1278 (d + 326) |
| 114 | 653 | 227 (special_lw) | 26 | g | 2929.0 | 300.0 | 13.6 | 0 | 953 | 10 (idle_ground) | 236 | g | 2543.4 | 300.0 | 0.0 | progress 1279 (d + 326) |
| 115 | 654 | 227 (special_lw) | 27 | g | 2913.4 | 300.0 | 15.6 | 0 | 954 | 10 (idle_ground) | 237 | g | 2543.4 | 300.0 | 0.0 | progress 1280 (d + 326) |
| 116 | 655 | 227 (special_lw) | 28 | g | 2896.4 | 300.0 | 17.0 | 0 | 955 | 10 (idle_ground) | 238 | g | 2543.4 | 300.0 | 0.0 | progress 1281 (d + 326) |
| 117 | 656 | 227 (special_lw) | 29 | g | 2879.4 | 300.0 | 17.0 | 0 | 956 | 10 (idle_ground) | 239 | g | 2543.4 | 300.0 | 0.0 | progress 1282 (d + 326) |
| 118 | 657 | 227 (special_lw) | 30 | g | 2862.4 | 300.0 | 17.0 | 0 | 957 | 10 (idle_ground) | 240 | g | 2543.4 | 300.0 | 0.0 | progress 1283 (d + 326) |
| 119 | 658 | 227 (special_lw) | 31 | g | 2845.4 | 300.0 | 17.0 | 0 | 958 | 10 (idle_ground) | 241 | g | 2543.4 | 300.0 | 0.0 | progress 1284 (d + 326) |
| 120 | 659 | 227 (special_lw) | 32 | g | 2828.4 | 300.0 | 17.0 | 0 | 959 | 10 (idle_ground) | 242 | g | 2543.4 | 300.0 | 0.0 | progress 1285 (d + 326) |
| 121 | 660 | 227 (special_lw) | 33 | g | 2811.4 | 300.0 | 17.0 | 0 | 960 | 10 (idle_ground) | 243 | g | 2543.4 | 300.0 | 0.0 | progress 1286 (d + 326) |
| 122 | 661 | 227 (special_lw) | 34 | g | 2794.4 | 300.0 | 17.0 | 0 | 961 | 10 (idle_ground) | 244 | g | 2543.4 | 300.0 | 0.0 | progress 1287 (d + 326) |
| 123 | 662 | 227 (special_lw) | 35 | g | 2777.4 | 300.0 | 17.0 | 0 | 962 | 10 (idle_ground) | 245 | g | 2543.4 | 300.0 | 0.0 | progress 1288 (d + 326) |
| 124 | 663 | 227 (special_lw) | 36 | g | 2760.4 | 300.0 | 17.0 | 0 | 963 | 10 (idle_ground) | 246 | g | 2543.4 | 300.0 | 0.0 | progress 1289 (d + 326) |
| 125 | 664 | 227 (special_lw) | 37 | g | 2743.4 | 300.0 | 17.0 | 0 | 964 | 10 (idle_ground) | 247 | g | 2543.4 | 300.0 | 0.0 | progress 1290 (d + 326) |
| 126 | 665 | 227 (special_lw) | 38 | g | 2726.4 | 300.0 | 17.0 | 0 | 965 | 10 (idle_ground) | 248 | g | 2543.4 | 300.0 | 0.0 | progress 1291 (d + 326) |
| 127 | 666 | 227 (special_lw) | 39 | g | 2709.4 | 300.0 | 17.0 | 0 | 966 | 10 (idle_ground) | 249 | g | 2543.4 | 300.0 | 0.0 | progress 1292 (d + 326) |
| 128 | 667 | 227 (special_lw) | 40 | g | 2692.4 | 300.0 | 17.0 | 0 | 967 | 10 (idle_ground) | 250 | g | 2543.4 | 300.0 | 0.0 | progress 1293 (d + 326) |
| 129 | 668 | 227 (special_lw) | 41 | g | 2675.4 | 300.0 | 17.0 | 0 | 968 | 10 (idle_ground) | 251 | g | 2543.4 | 300.0 | 0.0 | progress 1294 (d + 326) |
| 130 | 669 | 227 (special_lw) | 42 | g | 2658.4 | 300.0 | 17.0 | 0 | 969 | 10 (idle_ground) | 252 | g | 2543.4 | 300.0 | 0.0 | progress 1295 (d + 326) |
| 131 | 670 | 227 (special_lw) | 43 | g | 2641.4 | 300.0 | 17.0 | 0 | 970 | 10 (idle_ground) | 253 | g | 2543.4 | 300.0 | 0.0 | progress 1296 (d + 326) |
| 132 | 671 | 227 (special_lw) | 44 | g | 2624.4 | 300.0 | 17.0 | 0 | 971 | 10 (idle_ground) | 254 | g | 2543.4 | 300.0 | 0.0 | progress 1297 (d + 326) |
| 133 | 672 | 227 (special_lw) | 45 | g | 2607.4 | 300.0 | 17.0 | 0 | 972 | 10 (idle_ground) | 255 | g | 2543.4 | 300.0 | 0.0 | progress 1298 (d + 326) |

- **Same at matching phases:** the group's translation and velocity (exactly equal: the period is 300), grounded on line 19, 300.0 above the group, facing −1,
  jumps_used 0, live mask 322 (target 2 broken).
- **Different:** status (227 special_lw, mid-run, timer 12..45, against 10 idle_ground, timer 222..255), horizontal position (x 3,065.0 → 2,607.4, between 64 and 522
  units right of the next cycle's 2,543.4) and horizontal motion (ground velocity 13.6 to 17.0, against 0.0). The first cycle also has hitlag 5..1 at 639..643.
- The next cycle's successes show that the clear's 326-tick exit works from idle, standing at x 2,543.4, at these phases. They say nothing about a fighter in
  special_lw at x 2,607..3,065 moving left, and part B shows that from that state no take-off started before 717. The next cycle's outcome is **not** applied to
  the first cycle.

## 8. Part F: conclusions

1. **Leaving later than the clear never beats B (the later side is forced for these exits): SUPPORTED for the clear's exit only.** The clear's exit departed at d
   for all 300 later d (717..1,016). 84 reached the baseline's progress at exactly d + 326, which is d − 716 ticks after B, and 216 broke nothing within the
   budget (part C). 0 beat B. The generic exit never departed at d in the later window, so for it the later side is untested. "Forced" is in-probe: one open-loop exit, shifted in time.
2. **The earlier post-break window was not tested: SUPPORTED.** 0 of 154 rows with d in 639..715 departed at d. Every measured departure is at 716 or later (part A),
   and the report's curve shows `nd` for every one. The run's "earlier side" count of 12 is all pre-break rows (569..575, 590..594), and none of them broke a target.
3. **Whether the fighter could act before 716 in the clear's own state:**
   - Take-off before 716: NOT OBSERVED. In 154 of 154 rows, the special_lw run that contains d ended at exactly 716, and no status 20 started before 717. That
     includes 77 rows with the clear's own take-off word at d (part B). **SUPPORTED** for these 154 input streams. That no input at all could do it is
     **UNKNOWN**: only two exits were tried, the clear's and one random stream.
   - Other effects: **SUPPORTED** that inputs changed the fighter's state inside the run (x from 644 on for d 639..652; 26 rows with status-228 hops that returned
     to the group), but none ended the run early.
4. **Whether an earlier take-off after the on-group break could plausibly beat B, and by how many ticks at most: UNKNOWN.** It is not possible in the clear's own
   state for the recorded inputs (item 3), so it needs a different prefix: one that breaks target 2 and leaves the fighter on the group in a state from which a
   take-off starts before 717. No such prefix is in this run. Bounds, given A to E:
   - With the clear's exit (326 ticks from departure to progress in all 85 successes, and no shorter exit observed), a take-off at d′ in 639..715 would reach
     progress at d′ + 326, a gain of 716 − d′, **at most 77 ticks** (d′ = 639, phase 100).
   - Mapping the next cycle's phase results onto the first cycle would give gains of 44..77 (phases 100..133), none for phases 134..160 (no break in the next cycle)
     and 1..16 (phases 161..176). This mapping is **NOT SUPPORTED** as evidence: the first cycle's state differs in status, x position and horizontal motion (part E).
   - The run also shows that target 2 can break earlier. 60 pre-break rows break target 2 first, the earliest at 583 (d 549, the clear's exit), but none of them
     departed at d and none reached the baseline's progress within its budget. Nothing in the run shows a faster route from such a state.
   - Whether any exit shorter than 326 ticks exists from any of these states is **UNKNOWN** (the probe plays open-loop exits only).

**Smallest follow-up that would settle item 4 (described only; not built or run):**

1. **Offline, zero ticks (first):** scan the trajectories already recorded: this run's 947 traces and the band's verified `_r1` traces. For each trajectory where the
   on-group target (read from the record, as the probe does) breaks while the fighter is on the moving group's line, list the first tick after that break at which a
   take-off starts (status-20 onset by the D rule) while the fighter is still grounded on the group, with its phase, x and status runs. Report the earliest such tick
   overall and per phase. Use the existing tool functions, no new rule, and no record value as a literal. This answers whether any recorded prefix offers a take-off
   after the break and before 716. If none does, item 4 cannot be settled from recorded data and stays UNKNOWN, and no native run is justified on this evidence.
2. **Native, only if step 1 finds such states, and only with Nicolas's explicit go:** a re-prefixed departure probe. For each found prefix (its words up to its
   free tick f), play the clear's exit and the generic exit from every d in f..715, one fresh process per candidate from tick 0, with the verify flags and the
   full tick contract, and value each row by its progress tick against B, exactly as this probe does. At most 77 departure ticks × 2 exits per prefix. At this run's
   measured ~1.35 s of native time per candidate, a few prefixes take a few minutes. No claims. A gain counts only as evidence for run 3 and the segment optimiser.

## 9. Constraints (restated, not relaxed)

- No native RNG seed inspection, logging, control, comparison or hashing.
- Native changes PORT-only and default-off. This analysis made none.
- Process restart resets the episode. The soft reset is not built.
- Submit tick T, one update, consumed_tick = T, input_tick = T + 1, checked every tick (the run recorded 0 contract failures).
- Canonical words are replay truth (Track 1 btt_s9_b8_v1 = MultiDiscrete([9,8])).
- TAS and human recordings are never read. None were read here.
- No hardcoded routes, waypoints, cids, coordinates, target ids, directions, orders, periods or census numbers in selection or rules. The ticks and coordinates in this
  record are observations, not rules; the follow-up above reads every such value from the records.
- No claims. Every claimed clear is verified by exact replay from tick 0, twice, in fresh processes. This record claims nothing.
- New native runs need Nicolas's explicit go.

## 10. How this was produced

Read-only Python over the gzip JSON traces, using the probe's tick convention (`reply_at`) and the status table classifier. No lab or repository file was changed
apart from this record and one backup line in `docs/project_handoff.md`. The scratch scripts are outside the repository. Line endings: LF, checked with
`tr -cd '\r' < file | wc -c` (0).
