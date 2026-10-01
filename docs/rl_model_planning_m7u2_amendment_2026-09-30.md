# M7u2 amendment 1: goal overlap restored to "allowed and recorded" (2026-09-30)

**Status.** A minimal, user-authorised amendment made before any M7u2 native tick. Nothing native has run.
It changes goal *selection* only. Eligibility, rarity, the frozen model, the planner, the P / RC / scrambled controls, the
decision thresholds and every budget are unchanged.

**Preserved.** The previous preparation record is kept byte-identically as
`docs/rl_model_planning_m7u2_implementation_preparation_r0.md` (sha256 `f062a467…`). The three pre-amendment source files
(`rl/m7u2_{goals,gate,tests}.py`) are kept in the D: source snapshot under `prepared_reference/`. They were rebuilt by
reversing the amendment edits and are byte-identical to the hashes the preparation record had pinned
(`43c172b1…`, `dfc35c23…`, `8e14c54f…`).

## 1. What was wrong

The proposal (§3.3) selected **one goal per episode**: the eligible τ with the smallest `sha256(m7u2|goal|e|τ)`,
episodes in `sha256(m7u2|goal|e)` order, first 24. It allowed overlapping boxes (it noted only 2 of 66 pairs overlapped
in the m7u1 data).

Preparation added a stricter rule at the user's request to treat overlapping boxes as non-independent evidence: no two
registered goals' ±150 boxes may intersect, with a fallback to the episode's next sha-ordered τ, otherwise skip. That
rule over-restricted the registration. The intended requirement was narrower:

- prevent **exact duplicate goal definitions**;
- keep **one goal per source episode** and **deterministic hash ordering**;
- **allow** overlapping boxes, **record** them, and describe the resulting goals as **correlated**.

## 2. The amended rule (`rl/m7u2_goals.py`)

Unchanged: the pool, eligibility (τ ∈ [32, 96], valid, airborne, not the fatal-fall tick, rise ≥ 300, ≤ 1 of 92 reference
episodes reach the ±150 box within 128 input ticks), the sha orders, one goal per episode, N_GOALS = 24, π(k) =
(k + 12) mod 24, INCOMPLETE when fewer than 24.

| step | before the amendment | amended |
| --- | --- | --- |
| per episode | the first sha-ordered τ whose box intersects no registered box | **the first sha-ordered eligible τ whose goal definition is not an exact duplicate of a registered goal's** |
| exact duplicate | (not separately tested) | the same box centre (x, y), compared exactly (no tolerance). The fallback is the episode's next sha-ordered τ; if every eligible τ duplicates, the episode is skipped and recorded |
| overlapping boxes | refused (fallback or skip) | **allowed**; recorded; never affects selection |
| INCOMPLETE text | "non-overlapping eligible goals" | "distinct eligible goals" |

Selection still takes only the pool and the fixed reference: `select_goals` has no outcome argument (a test pins its
signature). Goal selection never inspects planner outcomes.

**Overlap record** (`goals.json` and `state.json`, key `overlap`; the final `decision` carries `goal_overlap`):
every overlapping pair among the registered goals (registered indices, entries, |dx|, |dy|; two boxes overlap when both
centre offsets are ≤ 300), the number of pairs out of 276, each goal's overlap count, the **correlated groups**
(connected components of the overlap graph) and the number of goals outside any group. Its stated reading: *goals whose
boxes overlap are correlated trials, not independent evidence.*

The gate's rule (PASS / NULL / INCONCLUSIVE) counts each goal as one paired trial and is **unchanged**. The correlation is
reported beside it. It does not change a threshold. A result must be read with the group structure in view.

`contract_digest()` changed (`78a6cd1d…` to `691d9abd…`); the contract name `m7u2_tick0_goal_v1` is kept because no data
has ever been produced under either text.

## 3. Supply estimate, corrected

The preparation record's availability table (0.26 / 0.58 / 0.77 / 0.99 for the overlap-gated rule) described a selection
algorithm that is **no longer implemented** and is withdrawn. For the amended rule the pool supplies one goal per
episode that has at least one eligible point, so the supply is essentially the number of such episodes out of 360. A
binomial model on the per-episode yield gives (this is an approximation: it treats episodes as independent, takes the
yield from 12 / 92 leave-one-out episodes, and ignores that an exact duplicate can only cost an episode that has no
other eligible τ, which is rare):

| per-episode yield | P(at least 24 of 360) |
| --- | ---: |
| 7.6 % (lower 95 % bound) | 0.78 |
| 9 % | 0.95 |
| 10 % | 0.99 |
| 13 % (measured 12 / 92) | 1.00 |

These agree with the proposal's figures (0.78 / 0.95 / 1.00). They are estimates, not a guarantee. Fewer than 24 distinct
eligible goals is still **INCOMPLETE**, with no second pool, no relaxed eligibility and no retry.

## 4. Files changed

All were untracked preparation files; no tracked file changed.

| file | change | sha256 before | sha256 after |
| --- | --- | --- | --- |
| `rl/m7u2_goals.py` | the selection rule and record; `overlap_report`; contract text | `43c172b1…` | `da4c6041ab0c…` |
| `rl/m7u2_gate.py` | the decision carries `goal_overlap` (one added statement) | `dfc35c23…` | `621bf45df953…` |
| `rl/m7u2_tests.py` | the goal-selection case rewritten for the amended rule; the e2e summary keys | `8e14c54f…` | `a8360765d1a4…` |
| `rl/m7u2_rule.py` | none | `0243b751…` | `0243b751…` |
| `docs/rl_model_planning_m7u2_implementation.md` | amended; the withdrawn table replaced | `f062a467…` | see the record |
| `docs/rl_model_planning_m7u2_tick0_proposal_2026-09-30.md` | none | `30d8da9c…` | `30d8da9c…` |

No m7u1 file changed; the import-isolation test still checks them against HEAD.

## 5. Tests on the final code

`python rl/m7u2_tests.py unit`: **13 / 13 passed** (80 s). The goal-selection case now uses a fixed ten-episode world with
roles set against the registered sha order, and asserts:

- the registered entries and τ: `c006, c009, c001, c008, c005, c007` at τ `70, 45, 60, 60, 50, 90`;
- one goal per episode; no two goals with the same (x, y);
- **c005's box overlaps c008's and both register**; the pair, each goal's count, the correlated group `[[3, 4]]`, the
  4 goals outside any group and the 15 possible pairs are recorded, checked against a brute-force count;
- **c004's only τ is an exact duplicate of c008** and is passed over then skipped; **c007's sha-first τ 40 duplicates
  c008** and c007 registers τ 90;
- a point one unit away is a different definition and registers;
- episode and τ sha ordering, and permutation invariance;
- a shortfall (7 wanted, 6 available) is INCOMPLETE, keeps the skip and overlap record, and is not filled;
- the missing / extra pool episode, 129 words and off-record reset row refusals, the signature without an outcome input,
  and the production constants.

`python rl/m7u2_tests.py e2e` (505 s) ran `run_gate` through every phase at production counts over the synthetic
stand-in: P1 354 ticks, the pool exactly 360 episodes and 46,080 ticks, 1,328 eligible points in 99 episodes, **24 goals
with 0 duplicate passes and 8 overlapping pairs in 6 correlated groups**, 72 tick-0 trials, 3 exact replays, the rule
applied once, the frozen digest unchanged. The synthetic world says nothing about Mario; its NULL is meaningless.

Approval tests use temporary records and are independent of whether the real approval record exists (re-run with a real
record present before launch; see the implementation record).
