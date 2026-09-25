# RL M7h: frontier-restart curriculum — results (n = 3)

Status (2026-09-25): **results record.** This document summarizes the frozen M7h decision and its verified
artifacts. It does not re-decide, amend the registered rule or edit any run artifact.

**Sources:**
- The decision record is copied byte-identically to
  [`rl_frontier_curriculum_m7h_analysis_n3.json`](rl_frontier_curriculum_m7h_analysis_n3.json).
- Every other number comes from the files listed in section 2 and in the companion
  [`rl_frontier_curriculum_m7h_results.json`](rl_frontier_curriculum_m7h_results.json).

**Design and registration:**
- [proposal (revision 2)](rl_frontier_curriculum_m7h_proposal.md)
- [gate report](rl_frontier_curriculum_m7h_gate.md)
- [readiness report](rl_frontier_curriculum_m7h_readiness.md)
- [manifest](rl_frontier_curriculum_m7h_manifest.json)
- [decision rule](rl_frontier_curriculum_m7h_decision_rule.json)
- [amendment 1](rl_frontier_curriculum_m7h_amendment_1.json)

## 1. Decision (frozen, unchanged)

**Gate 4, `discovered_not_consolidated`.** It was recorded 2026-09-25T02:13:51Z by `analyze` under rule
`98d1d55d…`, honouring amendment 1, with 0 integrity problems and no notes.

> Registered response: "record it; next: a separately registered consolidation proposal built on F and the agent's own
> verified discoveries (never the fixtures); no budget extension". `extension_required`: false.

| Quantity | Value |
| --- | --- |
| K_F, K_C (seeds with a verified clear) | 0, 0 |
| X_F, X_C (seeds with a final stochastic crossing) | 0, 0 |
| G (seeds with a verified `genuine_new_policy_entry` in F training) | **2** (g = 0 / 1 / 1) |
| T_F, final stochastic, seeds 0 / 1 / 2 | 49/10, 109/25, 477/100 |
| T_C, historical Phase K v1 | 118/25, 19/4, 427/100 |
| D_s = T_F − T_C | +9/50, −39/100, +1/2 (D̄ = 29/300) |
| φ_F / φ_C (final stochastic falls) | 2 / 0 / 2 and 1 / 1 / 0 (Φ_F = 1/75, Φ_C = 1/150) |

Gate conditions:

| Gate | Condition | Result |
| --- | --- | --- |
| 0 | integrity problems = 0 | passed |
| 1 | K_F ≥ 2 | false |
| 2 | K_F ≤ 1 and X_F ≥ 2 | false |
| 3 | K_F = 1 or X_F = 1 | false |
| **4** | **G ≥ 2** | **true** |

## 2. Execution identity

| Item | Value |
| --- | --- |
| Manifest (frozen; the docs copy is byte-identical) | `9d5e0c155317b5177ccad350910db9dab59ea3b4f40b20dbc6b0249def7b03ea` |
| Decision rule | `98d1d55d43d106da186c81074a5cc4d6078b4a6b97e4d816f694bb8f5919d2c9` |
| **Training code** (76 files; the R1–R3 control check and all three F runs, including their curriculum verification) | `8f9a911263e01402c4f645cd30119638aa2bdefa43d1e4f5aa2ba8bd48e9c0a7` |
| **Evaluation / verification code** (amendment 1: `evaluate`, `verify-clears`, `verify-entries`, `analyze`) | `fd61fcae463c38ba8f5620efc8beb4d3fe830db23c3128cb53e658a29e43ae0d` |
| Amendment 1 record (frozen copy in `_matrix/amendments/`, byte-identical) | `d8a229114045ce20f84f00eb26a64bd91166698b41bc4e5fa48bd9cf1b67cbcc` |
| Executable `build-us/Release/BattleShip.exe` | `1e7c62a05a9397fb4ef1d404d85a793cd01c4dbdc187068e3a63890cb5cbeb97` |
| Parent HEAD during execution | `78e56f4c6aeddaf730eb8c81dd3dea94529870c9`, with the M7h files staged but not yet committed (`run.json` records the dirty file list) |
| Submodules | decomp `3c7fd5d0`, libultraship `805f1950`, torch `3aa9c97` |
| Control record `_control/control_check.json` (R1–R3 passed; historical control reused) | `ba6499abeef8d99d3ba11af9e3e81debfeaf3c7d253ba781b5546d0d4b799609` |
| Decision record `_matrix/analysis_n3.json` | `73e13aa2cbaf336c35d245be814fa1481e5694f14c751ecda48cec3d1aa18f59` |
| `final/checkpoint.json`, F seeds 0 / 1 / 2 | `63d9eab1…`, `3915a4bd…`, `50625f2f…` (full values in the JSON) |
| Where the code lives now | parent commit `15f7850`: its M7h code fingerprint (`m7h_matrix.code_fingerprint()`, 76 files) equals the **amended** `fd61fcae` |

## 3. What ran

- **Arms.** F is `m7h_f_s{0,1,2}`: v1 plus `btt_curriculum_frontier_v1`, with p0 = 1/2, the M7f cell key,
  w = 1/√(1 + visits), 1 ≤ L ≤ 3,000 and a 60-tick failure window. C is the historical Phase K `m7g_s{0,1,2}_v1`,
  reused because R1–R3 passed (2026-09-24 18:32–19:13Z).
- **Budget.** 3,072,000 policy transitions per run. Prefix ticks are not budgeted.
- **Evaluation.** Tick-0 only, following the Phase K protocol: `initial` (100 + 100), 9 curve points (60 + 5) and
  `final` (100 + 100), with `SSB64_RL_TARGET_DIAG=1` in the evaluation workers only.

## 4. Training (arm F)

| | Seed 0 | Seed 1 | Seed 2 |
| --- | --- | --- | --- |
| Wall time | 3,472.8 s | 3,280.3 s | 3,333.3 s |
| Commit drawn; minimum available commit; minimum available physical | 5.839; 10.014; 3.333 GiB | 5.193; 12.438; 5.592 GiB | 5.142; 12.646; 5.609 GiB |
| Finished episodes (falls) | 1,280 (373) | 1,234 (308) | 1,248 (328) |
| Starts: tick0_initial / tick0 / archive_prefix | 5 / 631 / 649 | 5 / 643 / 591 | 5 / 602 / 646 |
| Archive cells / eligible | 4,249 / 2,937 | 4,564 / 3,112 | 4,806 / 3,015 |
| Prefix L: median / mean / max | 993 / 1,087 / 2,947 | 1,207 / 1,368 / 2,997 | 1,341 / 1,416.5 / 2,994 |
| Prefix ticks; dispatch wall time | 705,805; 543.2 s | 808,440; 596.1 s | 915,915; 670.1 s |
| Left-region classes | — | genuine 2, prefix_reproduced 15, policy_reentry_exposed_lineage 1 | genuine 1 |
| Lowest x at y ≥ 3,000 (policy rows) | −1,023.5 | −4,936.2 | −875.4 |

- **Integrity.** All three runs are `verified`, with curriculum verification ok, 0 archive digest mismatches, 0
  consumed-tick mismatches, and a maximum of 10 game processes.
- **Physical memory.** Seed 0 spent 1,391 probe samples below 4 GiB of available physical memory; the in-run stop policy
  acts on commit. Both of the other runs stayed above it.

## 5. Tick-0 evaluation

**Census and verification.**
- 2,955 of 2,955 episodes (3 runs × 985).
- 33 of 33 labels ok, all tick-0, all leak-free, 0 monitor hard alerts; 2.68 h of evaluation wall time.

**Outcomes in every label:**
- 0 clear candidates, so 0 native clears and 0 verified clears;
- 0 left-region entries;
- 0 breaks of left targets 1, 6 and 8.

**Final checkpoint, stochastic (100 episodes):**

| Seed | T_F | Distribution | φ_F | T_C | φ_C |
| --- | --- | --- | --- | --- | --- |
| 0 | 4.90 | 3: 2, 4: 31, 5: 42, 6: 25 | 2 | 4.72 | 1 |
| 1 | 4.36 | 4: 64, 5: 36 | 0 | 4.75 | 1 |
| 2 | 4.77 | 4: 34, 5: 56, 6: 9, **7: 1** | 2 | 4.27 | 0 |

**F deterministic results (100 episodes each):** 2, 4 and 1 targets. F seed 2's deterministic play is collapsed, with a
share of 0.54; seeds 0 and 1 are not collapsed (0.016 and 0.20).

**Target 2 and seven-target episodes:**
- Target-2 breaks across all F labels: 3, 5 and 5.
- **One seven-target episode** (F seed 2, final): all seven right-side targets including the moving target 2, with no
  left entry.

## 6. Training-only left-region entries (the G quantity)

**Verification.** The entries were verified by `verify-entries`: exact fresh-process replays from tick 0, with no live
left step on a prefix row and the first live left step on a policy row. The records are
`_entries/m7h_f_s{0,1,2}/entries.json`: seed 0 has 0 recorded; seed 1 has 2 recorded, 2 replayed and 2 verified; seed 2
has 1 recorded, 1 replayed and 1 verified.

**Descriptive detail.** The positions below come from M7h's own descriptive replay, `runs/m7h/_report/entry_traces_v2/`
(digest-equal, not a registered metric).

| Episode | Transitions | Start | First policy left row and position | What happened |
| --- | --- | --- | --- | --- |
| **s1 `83112a8c`** | 1,525,760 | archive prefix, L = 2,605 | row 2,816 at (−2,119.2, 4,136.0), airborne, status 224 | **A genuine crossing over the wall.** 308 policy left rows. It **landed on the left-side floor**: 24 grounded rows at y −1,950, rows 3,004–3,027, x −2,782.6 → −2,723.4. Its leftmost point was x −4,608.8. It broke no left target (4 targets remaining throughout) and fell (row 3,220). |
| s1 `438d5fcb` | 2,570,240 | archive prefix, L = 254 | row 314 at (−2,112.8, 4,085.9), status 225 | over the wall, airborne only (134 left rows); fell at row 533 |
| **s2 `56a1af09`** | 1,935,360 | archive prefix, L = 2,873 | row 3,145 at (−2,104.1, **−8,412.2**) | **An off-stage entry.** It is 5,562 units below the main solid's underside (y −2,850), so Mario passed *under* the stage while falling. It had 26 airborne left rows (y −9,616 … −8,412) and fell at row 3,170. The registered metric counts it as genuine. |

**No tick-0 start produced a left entry in training.** All three genuine entries came from archive-prefix starts, and
all 18 seed-1 left-region episodes ended in a fall.

**Sensitivity note (not a re-decision).**
- The registered entry metric (a live step with x < −2,100 on a policy row) does not separate over-wall crossings from
  under-stage entries. Only seed 1's entries are wall crossings.
- G = 2 therefore rests on seed 2's off-stage entry. With G = 1, gate 4 would not have fired. Gate 5 would then have
  reached null (gate 6), because D₁ < 0 blocks 5(a) and D₀, D₂ > 0 block 5(c).
- The decision stands as registered. The consolidation proposal that follows relies only on seed 1's crossing.

## 7. Amendment 1 (verifier repair)

- **Trigger.** The first `evaluate` stopped at `m7h_f_s0:curve_t000307200` with "66 artifacts for 65 evaluation rows".
  The evaluator leaves an episode that finishes on the quota-meeting vector step out of the rows, but still writes its
  artifact. The original verifier required artifacts to equal rows.
- **Repair.**
  - `verify_eval_tick0` now accepts the counted rows plus the recorded excess episodes.
  - It checks the identity of every excess episode against the worker ledgers.
  - It keeps every tick-0 check, and adds contiguous consumed ticks and the native digest.
- **Scope.** Only `rl/m7h_verify.py` (`2c7b3f8a…` → `355dde58…`) and `rl/m7h_campaign.py` (`ba770d24…` → `ca08ccfa…`)
  changed, taking the code from `8f9a9112` to `fd61fcae`. It is honoured only by `evaluate`, `verify-clears`,
  `verify-entries` and `analyze`; `train` and `control-check` stay strict.
- **Evidence.** In `runs/m7h/_amendment/`:
  - tests 16 / 16;
  - 69 labels scanned, 6,189 artifacts, 0 refused, exactly 4 excess episodes;
  - two labels re-evaluated with every episode equal.
- **Control.** The R1–R3 control record was reused unchanged. The record was frozen on first use.

## 8. Post-decision descriptive facts (not registered metrics)

These come from later read-only review replays (`runs/review/m7i_proposal_evidence/`). They never feed the M7h rule.

- **Left-target breaks from reproduced left starts.** Two seed-1 prefix-reproduced training episodes broke left targets
  under policy control from starts already on the left side, then fell:
  - `79be8064` broke target 8;
  - `d9c5249d` broke target 6.
- **Tick-0 heights.** No final tick-0 stochastic episode of any seed reached y ≥ 3,000 (300 of 300 replayed; highest
  y 2,811). Neither did seed 1's curves at 1,536,000, 2,150,400 and 2,764,800 (180 of 180; highest y 2,272).

## 9. Re-verifying this record

**Hashes.** The hashes in the JSON are over the files' LF bytes as written. With `core.autocrlf=true`, a fresh Windows
checkout may convert the docs copies to CRLF. Compare with `git show <commit>:<path> | sha256sum`.

**Code fingerprint.** `m7h_matrix.code_fingerprint()` hashes every non-test `rl/*.py`, so it changes as soon as any new
`rl/*.py` exists, for example M7i's modules. Re-verify M7h from a checkout of `15f7850`, where it equals `fd61fcae`.

**The run artifacts.** They live in the git-ignored `runs/m7h/`: `campaign/`, `_report/`, `_amendment/`, `_gate/` and
`_readiness/`. None of them was modified by this summary.
