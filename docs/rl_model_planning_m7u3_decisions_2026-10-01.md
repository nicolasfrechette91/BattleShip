# M7u3: the user's design decisions, and how the preparation implements them (2026-10-01)

**Status: zero-native-tick preparation only.** This document records the decisions that amend
`docs/rl_model_planning_m7u3_proposal_2026-10-01.md` (sha256 `4590c0b4…`, **byte-identical**: it was not edited). The
proposal's design stands except where a decision below says otherwise. Nothing here authorises a native run, an
approval record, a source snapshot, a commit or a push.

**Scope label**, carried by every M7u3 record: *refit-versus-frozen test of planner-controlled reach of rare
behaviour-drawn airborne points from the normal tick-0 reset (one seed, one refit, 24 non-overlapping goals); not a
landing, wall-top reach, crossing, target result or clear.*

**Arms and notation.** The proposal wrote F / R / S for the comparisons and also W_R for the refit's witness acceptance.
The implementation uses unambiguous codes: **PF** = P_frozen (the m7u1 model), **PR** = P_refit, **RC** = the no-model
control, **SR** = S_refit (the refit commanded π(g), scored on g). P_retrain is not an arm. Witness acceptance counts are
W_frozen, W_refit and W_retrain.

## 1. The eight decisions

| # | decision (the user's words, condensed) | how the preparation implements it |
| ---: | --- | --- |
| 1 | **Training pool 540 episodes × 192 words**, Python seed 1. Recompute every native-tick, wall-time and memory projection and cap; keep the hard wall cap at 60 minutes. If it can't be kept under a pessimistic projection, stop and report; trim nothing else. | `rl/m7u3_goals.py` / `rl/m7u3_gate.py`: entries `t000..t539`, 108 per worker, stream key `m7u3|1|train|t###`, ≤ 192 words. The goal pool stays 540 × 128 (`g000..g539`, seed 2). Ledger **197,839** native ticks (§3). The **60-minute global cap is kept**; the pessimistic projection is **3,516 s (58.6 min)**, margin **84 s**. It fits; the margin is thin and is reported as such (§3). |
| 2 | **PASS** requires P_refit to beat P_frozen, RC and S_refit, each by the exact one-sided sign test at p ≤ 0.05, as proposed. | `m7u3_rule.apply`: an intersection-union of three exact sign tests, decided in exact integer arithmetic. No multiplicity correction. |
| 3 | **NULL**: P_refit's net paired gain over P_frozen is ≤ 1 goal, as proposed. | `b_PF − c_PF ≤ 1`. PASS and NULL are disjoint (p ≤ 0.05 needs a net gain ≥ 5); the rule self-test enumerates this. |
| 4 | **P_retrain** is an offline diagnostic model only: no native arm, no planner trials. Same architecture, same 6,000 steps, M7u1's training data only, training seed 1. Train it during this preparation, pin its parameter digest; the gate verifies the digest unchanged. | **Trained** (`rl/m7u3_refit.py retrain`): file sha256 `47d51b1b17a9461413c250e56e6c8f3c0bb0b5edba0debc5658ea5b6998ed62b`, parameter digest `13fa9cdbd143249a90c57b576b131c7ebd0edbbc0141f9cbbec19d4f58c916d7`, 316 s. It differs from the frozen model. The gate loads it with both pins checked, uses forward passes only, and checks its digest before the goal pool, before and after evaluation and after analysis. A test pins that no arm uses it. |
| 5 | **No S_frozen** arm. 24 goals. One stream per goal per arm. Overlap margin of 300 units, as proposed. | Arms PF, PR, RC, SR; 96 trials; stream `m7u3|3|goal|k` shared by the four arms. Selection requires Chebyshev distance **> 300** between every pair of goals; the 276 pairs are checked by brute force and the minimum is recorded. |
| 6 | If the **identity retrain** (the refit pipeline without the new pool) does not reproduce the frozen M7u1 parameters bit-exactly, stop, report, do not work around. | **It reproduces them bit-exactly.** Seed 0, empty pool, 6,000 steps, 6 threads: parameter digest `0e70af78f1bec21039fa65f6f35ed180d69b31a02dd482480b946aced1bc0156` = the frozen digest; **max \|Δparameter\| = 0.0; 0 of 685,092 elements differ.** The rebuilt per-transition inputs and targets equal M7u1's saved `model_inputs_train.npz` array for array, the vocabulary is 61 / 16 / 28 and the clock track is `16318edf…`. Record: `logs/m7u3_prep/identity_retrain.json`. No work-around was needed or tried. |
| 7 | Register **P_frozen vs RC on the fresh independent goals as a separate replication readout of M7u2**, with the M7u2 PASS thresholds applied in independent units; report it beside M7u3 without changing M7u3's decision. | `m7u3_rule.replication_readout` (see §2.2). |
| 8 | **Registered model diagnostic**, reported beside the decision, never altering it: open-loop position error strictly from the reset row on the fresh goal pool; median and per-episode paired differences at 16 / 32 / 64 / 96 for P_refit vs P_frozen and for P_retrain vs P_frozen; pre-declare the interpretation before any native data; also model acceptance of goal-pool recorded paths and the model / planning attribution with the M7u2 definitions. | `rl/m7u3_analysis.py` and `m7u3_rule.model_reading` (see §2.3). |

## 2. Pre-declared interpretations (fixed before any native data exists)

These are part of the rule code (`rl/m7u3_rule.py`) and are hash-pinned by the approval record. They are **reported beside
the decision and can never alter it.** No quantity from §2 enters `apply()`; a test checks that its source does not
reference them.

### 2.1 Arms, the decision, and the proposal's readings

Unchanged from proposal §5-§6, with notation PF / PR / RC / SR. For X ∈ {PF, RC, SR}: b_X = #(PR ∧ ¬X), c_X = #(¬PR ∧ X),
p_X the exact one-sided sign probability. INCONCLUSIVE names each blocker (*primary not significant*: b_PF − c_PF ≥ 2 and
p_PF > 0.05; *not model-attributable*: p_RC > 0.05; *undirected*: p_SR > 0.05). The proposal's §6 readings of a NULL or
INCONCLUSIVE outcome (no model gain from rest; model gain, no reach gain; regression; not model-attributable; undirected)
are implemented as written, with O = the relative change of the median strict 64-tick from-reset error of the refit
against the frozen model on the goal pool, and ΔW = W_refit − W_frozen.

### 2.2 Replication readout of M7u2 (decision 7)

M7u2's PASS needed three conditions: n_P ≥ 6, b_R − c_R ≥ 6 against RC, and b_S − c_S ≥ 5 against a scrambled-command control
of the **frozen** model. M7u3 has no S_frozen arm (decision 5), so the third condition **cannot be evaluated**. The readout
therefore applies the two evaluable conditions to P_frozen versus RC on the 24 independent goals (one unit per goal):

| label | condition |
| --- | --- |
| `MEETS_EVALUABLE_M7U2_PASS_CONDITIONS` | n_PF ≥ 6 and b − c ≥ 6 (b = PF only, c = RC only) |
| `NULL_VS_RC` | b − c ≤ 1 (M7u2's NULL condition against RC) |
| `INCONCLUSIVE` | otherwise |

The record states *"not evaluable: M7u2's b_S − c_S ≥ 5 condition (no S_frozen arm)"* and the exact one-sided sign
probability. A `MEETS…` label is therefore a **partial** replication (two of M7u2's three conditions); this is my reading of
decision 7 given decision 5, and it is the one point of this document I would like you to confirm or change.

### 2.3 Model diagnostic and its reading (decision 8)

**Measure (D2).** For each model (frozen, refit, retrain) and each episode of a set that **no model was fitted on**, roll the
episode's own recorded words from its **reset row** (one rollout per episode; never an early-window mixture of starts) and
take the Chebyshev error of the ensemble-mean position at h ∈ {16, 32, 64, 96}. An episode enters horizon h when it has at
least h words and a valid row at h, a condition that depends on the episode alone, so the set is identical for every model.
Two sets: **(a) the 540 goal-pool episodes**, collected after the refit is frozen (the registered diagnostic), and **(b) the
360 preserved M7u2 pool episodes** (forward passes only, a cross-check and a second sample). The frozen model's figures on (b)
must reproduce the proposal's §1.2 (median 153 / 333 / 714 / 908); a mismatch is reported as an analysis defect.

**Reported** per model and horizon: median, p90, share above the ±150 box; and, for refit-vs-frozen and retrain-vs-frozen, the
**median per-episode paired difference** (negative = the first model is better) and the **share of episodes where it is better**.

**Interpretation, pre-declared.** With (all positive = lower error than the frozen model):

- red_refit(h) = 1 − median(refit) / median(frozen); red_retrain(h) = 1 − median(retrain) / median(frozen) (the
  retrain-variation reference: it differs from the frozen model only by the training seed);
- better_refit(h), better_retrain(h) = the share of episodes where that model's error is below the frozen model's.

At the primary horizon **h = 64** (the other horizons are reported, not used for the label except in the last clause):

- **FLOOR** = median(refit) ≤ 0.8 × median(frozen) (a reduction of at least 20 %, the proposal's O ≤ −0.20);
- **BEYOND** = red_refit > max(red_retrain, 0) **and** better_refit ≥ better_retrain **and** red_refit(h) > red_retrain(h)
  at no fewer than 3 of the 4 horizons.

| label | condition |
| --- | --- |
| `MODEL_GAIN_BEYOND_RETRAIN_VARIATION` | FLOOR and BEYOND |
| `MODEL_GAIN_WITHIN_RETRAIN_VARIATION` | FLOOR and not BEYOND |
| `MODEL_REGRESSION` | median(refit) ≥ 1.2 × median(frozen) |
| `NO_MODEL_GAIN` | otherwise |

**Caveat carried with the label:** one retrain is **one draw** of retrain variation, not an interval, so
`MODEL_GAIN_BEYOND_RETRAIN_VARIATION` means "larger than the one observed retrain difference", not "outside the retrain
distribution". The 20 % floor and the 3-of-4 clause are the only thresholds; both are fixed here.

**Also reported (decision 8, M7u2 definitions, unchanged code `rl/m7u_analysis.py`):**

- model acceptance of the goal-pool recorded paths from the reset row (W_frozen, W_refit, W_retrain and the paired
  frozen-vs-refit table; M7u2's W was 1 of 24);
- MODEL / PLAN attribution of each P arm's failures with its own model (all failures, and failures without an ambiguity
  flag), PREDICTED / UNPREDICTED successes;
- cross-attribution (proposal D4): the same executed words from the same decision states through the other model.

## 3. Recomputed budgets and caps (decision 1)

Ledger (the gate refuses any request that would exceed a phase cap or the total, before it is sent):

| phase | native ticks (cap) | change from the proposal |
| --- | ---: | --- |
| P1: m7u1 `g26_P` 171 + `g14_P` 183, M7u2 `g14_P` 49 + `g03_P` 60 | 463 | none |
| training pool, 540 × 192 | **103,680** | 69,120 → 103,680 |
| refit training | 0 | none |
| goal pool, 540 × 128 | 69,120 | none |
| goal selection | 0 | none |
| evaluation, 24 goals × 4 arms × 128 | 12,288 | none |
| success replays, every success of every arm, ≤ 96 × 128 | 12,288 | none |
| **total** | **197,839** | 163,279 → 197,839 |

Wall time, per-episode model per worker (a 2.24 s restart plus its ticks at 108.9 ticks per second; fitted to m7u1's
collection and the M7u2 pool and reproduced within 0.3 s). The pessimistic column keeps the proposal's assumptions: pools
+35 %, training at the readiness ceiling, planning at 0.5 s per decision unbatched, 48 success replays.

| phase | projected | pessimistic | cap | proposal's pessimistic |
| --- | ---: | ---: | ---: | ---: |
| P1 | 20 s | 40 s | 120 s | 40 s |
| training pool, 108 × (2.24 + 192 / 108.9) | 432 s | **584 s** | 750 s | 400 s |
| refit: 6,000 × 58 ms + build / load | 388 s | **635 s** | 900 s | 600 s |
| goal pool, 108 × (2.24 + 128 / 108.9) | 369 s | 498 s | 750 s | 500 s |
| goal selection | 1 s | 5 s | 120 s | 5 s |
| evaluation, ≤ 2,304 planning decisions | 613 s | 1,220 s | 1,500 s | 1,220 s |
| diagnostics + success replays | 280 s | 534 s | 900 s | 534 s |
| **global** | **2,103 s (35.1 min)** | **3,516 s (58.6 min)** | **3,600 s** | 3,299 s |

- **The 60-minute cap is kept.** The pessimistic stack fits, with an **84 s (2.3 %) margin**. This is the thinnest margin of any
  gate so far (M7u2: 1,357 s projected against 2,400 s). The projected (non-pessimistic) total leaves 1,497 s.
- **Where the pessimism is concentrated:** the training pool (+184 s against the proposal), the refit's build and load (+35 s),
  and the replay allowance (48 replays at 8 s; every one of the 96 trials succeeding would need about 770 s). A pessimistic
  stack that is 2.4 % slower than the one above ends the run INCOMPLETE; the evaluation results would be saved but the rule
  would not be applied. I did not trim anything to widen the margin (decision 1).
- **Per-phase caps** were raised only where the pessimistic figure exceeded the proposal's cap (training pool 600 → 750 s,
  goal pool unchanged at 750 s); the global cap is unchanged. The phase caps sum to more than the global cap, as in
  the proposal.
- **Memory:** unchanged caps (main process 3,072 MB private; whole tree 9,216 MB private and 4,096 MB working set; system
  ≥ 1,024 MB available and ≥ 2,048 MB free commit). The refit builds about 345,000 transitions (240,964 + 103,680) against
  M7u1's 241,000; the measured projection is in the implementation record.

## 4. What the preparation changed relative to the proposal's file list

- **A sixth new file**, `rl/m7u3_analysis.py` (the diagnostics), so that `rl/m7u3_gate.py` does not carry them. It reuses
  `rl/m7u_analysis.py` for every definition the proposal says is unchanged, with one exception: `m7u3_analysis.accuracy` is a
  bounded-memory, batched re-implementation of `m7u_analysis.heldout_accuracy` (same definitions, same sha-ordered start
  ticks). Measuring the diagnostics showed that m7u1's function takes about 41 s and about 0.9 GB of transient memory on the
  46,000-transition M7u2 pool and the gate calls it seven times; the replacement takes 3.8 s and chunks the forward pass. A unit
  case checks it against `heldout_accuracy` and against the recorded m7u1 held-out and M7u2 figures on recorded data (121.35 /
  289.52 / 644.63 and 106.15 / 298.45 / 559.36, equal to the recorded values).
- **Preparation outputs live under `logs/m7u3_prep/`**, not `runs/`: the preflight requires `runs/m7u3` to be absent and
  walks every `runs/` file against the D: backup, so a file written there would make the preflight refuse for a second reason.
  `logs/` is Git-ignored. The P_retrain model file is **a single copy** there until a later session snapshots it.
- **Distinct pool-entry names** so that the two pools and the evaluation entries cannot be confused: training pool `t000..t539`,
  goal pool `g000..g539`, evaluation entries `e{k}_{PF|PR|RC|SR}`.

## 5. Constraints kept (guide and handoff)

No native RNG inspection, logging, control, comparison or hashing (seeds are Python-side stream keys only); the exact submit /
consume / input tick contract (non-consuming reset, one word = one native update, consumed T → input T + 1, no hidden neutral
step); canonical controller words as replay truth; Track 1 `btt_s9_b8_v1` unchanged (all 72 combinations reachable); human
recordings and the TAS are validation-only (P1 replays only the project's own planner artifacts); no native or submodule change
(executable `30a3913b…`); non-PORT decomp and byte matching untouched; no M7u1 / M7u2 file, record or evidence edited; nothing
committed or pushed.
