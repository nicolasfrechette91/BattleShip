# M7o proposal: a reusable count-based novelty credit over controllable spatial cells (`btt_explore_cells_v1`)

Written 2026-09-27 after the accepted M7n feasibility stop. Observation v3, Track 1, reward v2 and the PPO settings stay
fixed. This is a proposal with offline evidence; nothing was implemented in production code, nothing trained, no
frozen evidence or fingerprint touched (offline analysis under `runs/m7n/feasibility/explore/`, scripts in the
session scratchpad; the frozen M7n manifest still reports no drift).

## 0. What the evidence asks for

The 225 post-sweep continuations show the frozen v3 policies (a) do move toward the wall (50 approaches) but only along
the floor to the wall foot, where their jumps top out 730 below the wall top, (b) leave elevated positions (platform
top, L1) that both validated crossings used as takeoffs, and (c) receive no positive v2 event after the sweep until a
left target breaks. The two sources' own post-sweep segments earned −6.30 and −1.91. So the missing signal is for
*reaching new places while remaining in play*, especially elevated and left-of-centre places, not for any particular
route. A per-surface landing bonus was considered and rejected: on this stage the only never-landed surfaces (the ledge
top L0 and the left floor L3) are reached at the very end of a crossing, i.e. the credit would be as sparse as the
left-target break it precedes by 30–150 ticks. A credit over spatial cells pays along the way.

## 1. The mechanism and the exact proposed contract

**`btt_explore_cells_v1`** (separately versioned exploration term, added to the frozen `btt_reward_v2` per step;
never a change to v2's arithmetic or record):

| element | definition (nothing Mario-, target- or route-specific) |
| --- | --- |
| cell | the live position (`position_x`, `position_y`) floored to a square grid of side `map_extent / 24`, where `map_extent` is the width of the stage's `map_bounds` reported by the read-only spatial diagnostic (`btt_spatial_v1`); on this stage ±9600 → 800 units, roughly four collision-box heights of the character |
| eligible state | a live post-update observation (`fighter_valid` 1, `btt_active` 1) whose action class (v3's `btt_action_class_table_v1`, derived from the decomp status enums) is not `damage`, `dead`, `appear_entry`, `other` or `unmapped` |
| first visit | the first eligible step of the episode inside a cell (per-episode visited set) |
| grounded credit | `ground_air_state` 0: banked immediately, `β · w(n)` |
| airborne credit | `ground_air_state` ≠ 0: held *pending*; banked at the next grounded eligible step of the episode (a landing on any floor, static or moving); every pending credit is **voided** when the episode ends by native failure, by the horizon or by any end before a landing |
| rarity weight | `w(n) = 1 / (1 + n)`, `n` = number of earlier episodes of this worker's run in which the cell was visited (first visits only; the table persists across episodes of the run and is saved with every checkpoint set) |
| scale | `β = 0.05` per novel cell |
| cap | at most `1.0` banked per episode (one target's worth, a tenth of the clear bonus); once reached, further credits of the episode are 0 |
| resets | the per-episode visited set and the pending list are cleared at every `reset()`; the run table starts empty in a fresh run and is never imported from another run, the pilot or a checkpoint of another run; no prefix or curriculum phase exists in this proposal (tick-0 starts only) |
| total | `reward = btt_reward_v2 total + explore term`; the v2 terms, `episode_return_v2` and the v2 closed-form validation stay exactly as recorded today; the explore term is logged per step (`banked`, `pending_added`, `voided`) and per episode (`bonus`, `banked_ground`, `banked_air`, `voided`, `cells_new`, `cells_visited`, `cap_hit`, `table_size`) under a separate key |

Why this shape: grounded credit is safe because a grounded state is stable by definition; airborne credit is where the
traverse happens, so it must count, but only if the flight ends in a landing, which removes the incentive to leap into
novelty and die; the harmonic decay per worker turns the credit off where the policy already goes and leaves it on
where it does not; the cap and the scale keep the term small next to targets (+1 each) and the clear (+10), and the
fall penalty (−5) outweighs any episode's bonus.

## 2. Resistance to exploitation (each case measured offline in section 4 where a number is given)

- **Falls.** Pending airborne credits are voided on native failure (m7l_t2_s1, 24 falls: 7.4 voided, 0.8 banked before
  the fatal flights). The −5 stays. Grounded credits earned before the fatal flight are kept: the agent is not punished
  for having explored earlier, only for never landing.
- **Repeated visits and oscillation.** A cell pays once per episode; bouncing between two surfaces or hovering pays 0
  after the first visit; the run decay removes the payment for cells visited every episode within ~20 episodes.
- **Passive platform riding.** Riding through the platform's few cells pays the first time only and decays like any
  other cell; measured share of credit banked while grounded on the platform: 0.0–0.4 %.
- **Surface segmentation.** Cells, not surfaces, so collinear floor pieces cannot be farmed; a stage with more floor
  segments changes nothing.
- **Teardown / stale replies.** Non-live observations are ignored (v3's own stale rule); nothing is credited there.
- **Bound.** ≤ 1.0 per episode by contract; measured steady state after ~40 episodes: 0.02–0.04 per episode (≈ 0.5 % of
  the target reward); over 100 episodes 8.6–9.9 in total against 354–489 of target reward (2.0–2.5 %).
- **Not assumed:** a landing is not progress by itself; it only banks the flight that reached new cells.

## 3. Policy information

The term depends on the per-episode visited set and the run table, neither of which the policy observes. **No
observation change is proposed**: v3 stays byte-identical. Consequences, stated plainly: the exploration return is not
a function of the v3 observation, so the value target carries extra variance and the critic averages over the
unobserved history; because the credit decays to ~0 on the policy's own habitual cells, the objective converges to v2's
as the run proceeds, which is the intent (a temporary pressure, not a new goal). The explicit alternative, a
separately versioned v3.1 with a visited-cell mask, is not proposed here and would be a distinct decision.

## 4. Offline feasibility on existing traces (no game, no training)

Populations: 600 exact replays of the Phase K v1 finals and M7l finals (six labels × 100, in run order, per-tick rows
with contact and platform flags), the two M7n sources (full replies, jumps), the 225 M7n foothold continuations
(post-cut rows), and the two human crossing fixtures, used **only** to test that a genuine crossing is credited
(never to select parameters). Parameters were selected on the population and policy-discovered criteria (small and
decaying steady state, credit on elevated / left-of-centre states rather than the wall foot); the full 36-point grid
is in `runs/m7n/feasibility/explore/grid.json`.

| quantity (chosen contract) | value |
| --- | --- |
| mean bonus, episodes 1–5 / 20–40 / 81–100 of a 100-episode label | 0.59–0.71 / 0.065–0.085 / 0.019–0.039 |
| episodes over 0.5 / with zero bonus, per 100 | 3–5 (all early) / 0 |
| bonus over target reward, per label | 2.0–2.5 % |
| voided in fall episodes | 7.4 (24 falls) · 0.9 · 0.8 · 1.15 · 0 · 0.2 |
| share banked while grounded on the platform / at the wall foot | 0.0–0.4 % / 7–16 % (7 wall-foot cells, all common) |
| distinct cells after 600 episodes | 142 (41 visited by ≥ 50 episodes, 63 by < 5); high left-of-centre cells: 1 |
| source e404fde0 (platform route), primed by the 600 | 0.336, of which 0.327 after the sweep: 11 elevated-right cells, 2 high-left cells |
| source 907d762b (wall-foot approach), primed | 0.014, 0.001 after the sweep: the wall-foot approach earns nothing new |
| foothold platform cuts (1693 / 1893 / 2493), primed, mean per continuation | 0.10–0.11 (max 0.45); credit falls in elevated-right (2.1 per 25) and high-left (0.33–0.55 per 25) cells |
| foothold wall cuts (1679 / 1880), primed | 0.010 / 0.011; wall-foot credit 0.00; approach episodes earn less than non-approach ones |
| foothold drift cut 2693 (helpless at height, left of centre) | 0.017 mean, all of it high-left, banked on the later floor landing |
| fixture verifier test (validation only): lower crossing | 0.716 = 0.004 before takeoff + 0.213 takeoff → entry + 0.500 after entry; its terminal fall voided 0.65 of pending flight credit |
| fixture verifier test: upper crossing | 0.537 = 0.009 + 0.303 + 0.225; no fall, nothing voided |

Useful behaviour that would be credited: jumping and up-B from the platform top toward the left (the elevated-right and
high-left cells), drifting left at height and landing, standing on the ledge top, the left floor. Undesirable behaviour
that would not: jumping at the wall foot (cells already common), riding the platform, oscillating, leaping off toward
new cells and dying. A rejected variant is on record: crediting only "controllable" airborne states (a jump still
available) scored 0.10 on both fixtures because Mario's traverse is helpless after up-B, so it would have missed the
very movement we want; landing-banked credit is the corrected rule.

**Remaining uncertainty.** (1) The population is v1 behaviour; v3 policies jump higher from the platform, so early
credit will be larger in the elevated-right cells and will decay there faster than the table suggests. (2) Per-worker
tables see ~170 episodes each in a 3,072,000-transition run, so the steady state may be 2–3× the pooled figure (still
≤ ~6 % of target reward). (3) Whether the credit changes behaviour is exactly what the experiment measures; zero
crossings in 225 continuations bound nothing about discovery under a different reward.

## 5. One bounded pilot and comparison (proposal; each needs its own approval)

**Implementation (opt-in, defaults unchanged, ~700–1,000 lines):** a pure module `rl/btt_explore_cells.py` (cells,
table, per-episode state, record, self-test), an `[exploration]` profile table with pinned choices (`contract`, `beta`,
`cap`, `grid_divisor`, `decay`), a reward wrapper variant dispatched like M7j's route wrapper (`make_reward_wrapper`),
the per-worker table saved in every checkpoint set, the episode-summary / artifact-label key, m7d validator awareness
(the v2 closed form is checked on the v2 part), tests, and the profiles `rl/configs/m7o/m7o_s{0,1,2}_x1.toml` = the
M7n v3 profiles plus the table. Any edit changes the fingerprinted set, so the frozen M7n / M7l / M7m manifests will
report drift as usual (their evidence is untouched).

**Control.** The three M7n v3 runs (fresh, v3, reward v2, 3,072,000, seeds 0–2) match the experimental profiles in
everything but the added table. Reuse is conditional on a v3 reproduction check registered like M7n's R1: three fresh
102,400-transition runs of the M7n profiles on the final code must equal `m7n_s{0,1,2}_v3/checkpoints/ckpt_000102400`
in policy digests and episode rows; if any seed differs, three fresh v3 control runs are trained instead (+5.5 h).

**Pilot (go / no-go, one run, its model discarded):** seed 0, the experimental profile capped at 307,200 transitions
(60 rollouts, ~5 min), then the standard 307,200 curve evaluation (60 stochastic + 5 deterministic, tick 0). Registered
checks: every per-episode bonus ≤ 1.0; the run table grows and the mean bonus of episodes 61–86 is < 30 % of episodes
1–25; voided equals the pending amount at each fall; the v2 closed form validates on the v2 part of every row; no leak,
no hard alert; end-to-end throughput within 10 % of M7n's 1,040 transitions/s; stochastic targets at 307,200 not below
the M7n seed-0 curve point (3.57) by more than 0.5. Any failed check = no-go and a diagnosis, not a retune.

**Comparison.** Three fresh experimental runs, seeds 0–2, 3,072,000 transitions each, tick-0 starts only, the M7n
evaluation protocol (11 labels, 985 episodes per run, clears verified natively, gate-2 candidates verified by
`btt_qualified_crossing_v1`), one application of a rule frozen before launch:

| gate | condition | outcome |
| --- | --- | --- |
| 0 | integrity (control reproduction, verification, drift, provenance) | invalid, stop |
| — | fewer than three verified runs or short labels | incomplete |
| 1 | a native-verified clear in the experimental arm with none in the control, or strictly more in every seed | **success (discovery)** |
| 2 | X = 1 (qualified crossing or left-target break, replay-verified) in ≥ 2 experimental seeds and 0 in every control seed | **success (discovery)** |
| 3 | D = T_exp − T_ctl ≤ −1/2 in ≥ 2 seeds | **failure (exploitation)**; the credit displaced target collection |
| 4 | D ≥ +1/2 in every seed | success (targets), not the mechanism's purpose |
| 5 | G ≤ 0 in ≥ 2 seeds | failure (no learning) |
| 6 | anything else | inconclusive |

Reported, never gating: bonus per episode over the run (must decay), cells discovered per run, early-sweep retention
(R and seven-right counts), target 2, falls, deterministic collapse, unqualified left entries, prefix costs (none).
Bonus accumulation is not an outcome. **Budget:** 9,216,000 experimental transitions + 307,200 pilot + 307,200 for the
reproduction check; **runtime** ≈ 15 min pilot + 10 min check + 3 × (50 min training + 45 min evaluation) ≈ 5.5 h,
~5.2 GiB commit per run, ≤ 10 game processes. **Stops:** integrity, provenance, drift, hard alert, leak, resource stop,
pilot no-go; no early stop on results, no extension, no extra seeds, no re-decision.

## 6. Recommendation

**Proceed, in two approvals: first the opt-in implementation with its self-tests and the registered pilot; only on a
pilot go, the three-seed comparison against the reproduced M7n v3 control.** The offline evidence supports the
mechanism's shape (bounded, decaying, credits elevated and left-of-centre movement and not the wall foot, voids fatal
flights, leaves v2 intact); it does not show that the policies will learn from it, and that is the question the
comparison is built to answer with normal tick-0 evaluation as the only basis for a claim.
