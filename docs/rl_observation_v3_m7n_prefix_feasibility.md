# M7n follow-up: feasibility of learning a crossing from the agent's own early-sweep states (no training)

Written 2026-09-27 after the recorded M7n decision (gate 3 `better_targets`, v3 selected; never re-decided) and the
sweeps addendum. Observation v3, reward v2, Track 1 and the PPO settings stay fixed. Nothing was trained, no new tick-0
evaluation was run, no production file changed: the harness is `rl/tools/m7n_prefix_feasibility.py` (outside the
fingerprinted M7n set; `manifest_drift` still none), its outputs live under `runs/m7n/feasibility/prefix/`, and the two
registrations were written once, before any check: `docs/rl_observation_v3_m7n_prefix_sources.json` (sha256
`fa72f62f…`) and `docs/rl_observation_v3_m7n_prefix_feasibility_plan.json` (`49ef543d…`). Standing restrictions kept:
process restart per episode, non-consuming tick-0 reset, native action timing, canonical action artifacts, non-PORT
behaviour untouched, native RNG never inspected, fixtures and TAS never used (the two validated crossings are cited below
as timing references only).

**Sources (user authorisation 2026-09-27: explicit action-prefix restarts after a normal tick-0 reset only).** The two
final stochastic tick-0 evaluation episodes of the M7n campaign that completed the seven right targets early, both
replay-verified in the sweeps addendum and again here (exact, every raw reply kept):

| source | run | sweep tick | actions left | artifact (preserved) |
| --- | --- | --- | --- | --- |
| `…907d762b` | m7n_s1_v3 final | 1678 | 1921 | `runs/m7n/campaign/_eval/m7n_s1_v3/final/stochastic/workers/w01/artifacts/episode_20260927T032209Z_907d762b` |
| `…e404fde0` | m7n_s2_v3 final | 1692 | 1907 | `runs/m7n/campaign/_eval/m7n_s2_v3/final/stochastic/workers/w04/artifacts/episode_20260927T042929Z_e404fde0` |

Cut semantics are M7m's: a cut τ replays rows 0..τ−1 after the tick-0 reset, the policy's first action is for input
tick τ, the horizon counts from the reset, prefix steps earn nothing. The v3 policy observation at τ is built by feeding
every prefix reply to the worker's own `EntityObservationBuilder`, so displacements, sticky projectile slots and the
action-class history are exactly what the policy would have seen had it played the prefix.

## 1. Candidate starting states (from the exact traces, `runs/m7n/feasibility/prefix/candidate_states.json`)

Nine cuts were chosen from the traces before the check and registered. Positions in world units; velocity per tick;
"remaining" = 3600 − τ. Every state has the three left targets (1, 6, 8) standing and the seven right targets broken.

| source | τ | remaining | position (x, y) | contact | velocity (air x, y) | action class (id / tics) | jumps used | platform (y, vy) | inherited effects |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 907d762b | 1679 | 1921 | (3145, 2119) | airborne | (−13.3, +65.4) | special_hi 226 / 17 (up-B rising) | 2 of 2 | 2134, −17.3 | rising up-B momentum, no jumps left, one own fireball in flight |
| 907d762b | 1880 | 1720 | (2140, −450) | grounded L1 (raised right step; the validated lower crossing's takeoff surface) | (0, 0) | special_n 223 / 25 (fireball) | 0 | 3281, +4.3 | none (at rest); two own fireballs in flight |
| 907d762b | 2160 | 1440 | (−597, −2550) | grounded L4 (main floor, left of centre) | (0, 0) | special_n 223 / 18 | 0 | 3124, +11.4 | none; one fireball |
| 907d762b | 2440 | 1160 | (1845, −1445) | airborne, just left L2 | (0, +55.1) | airborne 22 / 0 (jump start) | 1 | 2849, +15.9 | a jump initiated in the prefix's last row |
| e404fde0 | 1693 | 1907 | (2600, 1874) | airborne | (+13.3, +65.4) | special_hi 226 / 17 | 2 of 2 | 1904, −15.4 | rising up-B momentum, no jumps left, one fireball |
| e404fde0 | 1893 | 1707 | (2890, 3596) | grounded on the moving platform at its top (the validated upper crossing's takeoff surface) | (0, 0) | shield 154 / 3 | 0 | 3296, −1.6 | none; platform about to descend |
| e404fde0 | 2493 | 1107 | (2523, 3596) | grounded on the moving platform at its top | (0, 0) | idle_ground 189 / 55 | 0 | 3296, −1.6 | none |
| e404fde0 | 2693 | 907 | (−245, 3914) | airborne, left of centre, above the wall top | (−22.7, −2.7) | special_hi 226 / 23 (up-B apex) | 2 of 2 | 2032, +16.5 | inherited height with no jump or up-B left; drifting left 23 / tick |
| e404fde0 | 2813 | 787 | (−99, −2550) | grounded L4 (centre) | (0, 0) | landing 59 / 18 | 0 | 3177, −9.5 | none |

Height alone is not usefulness: the two apex states (τ 1679 / 1693 rising, τ 2693 at y 3914) carry no jump or up-B and
sit 2,500–4,300 units right of the wall; the platform-top states are 5,300 units right of the ledge (the validated upper
crossing needed 198 ticks from its platform takeoff to the left entry); the L1 state is the validated lower takeoff
surface (181 ticks takeoff → entry in the fixture).

## 2. Foothold check (registered plan, then run: 9 cuts × 25 stochastic continuations = 225 episodes)

Frozen policies: the source seed's own v3 final (`m7n_s1_v3/final` policy digest `5ba7793f…`, `m7n_s2_v3/final`
`763b164b…`, files pinned in the plan), stochastic sampling, per-episode seed `sha256("m7n_prefix|<source>|<τ>|<k>")`.
Every episode: fresh process, tick-0 observe, exact prefix (consumed ticks, prefix digest and the post-prefix
observation and target mask checked against the registration), then policy actions to a native end or the horizon.
All 225 ran (0 integrity failures, 0 leaks, 11.5 min with 3 processes; prefix 5.2 s and 8.9 s per episode on average).

Stages after the cut (registered before running; the corrected M7n verifier for S4):
S1 approach = a live step with x ≤ −1200 (the ledge's right end; the wall's face is at x −1800, the main floor L4 ends
there); S2 over-ledge = y ≥ 3000 with x ≤ −1200, policy-initiated iff the last grounded step before it is at or after τ;
S3 = an `over_wall` entry; S4 = `btt_qualified_crossing_v1`; S5 = a left-target break.

| source | τ | remaining | S1 approach | S2 over-ledge (policy) | S3 over-wall | S4 qualified | S5 left break | falls | horizon | best y near the wall (x ≤ −1200) | mean v2 return of the policy phase |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 907d762b | 1679 | 1921 | 12 / 25 | 0 (0) | 0 | 0 | 0 | 4 | 21 | −389 | −2.57 |
| 907d762b | 1880 | 1720 | 12 / 25 | 0 (0) | 0 | 0 | 0 | 6 | 19 | +570 | −2.69 |
| 907d762b | 2160 | 1440 | 8 / 25 | 0 (0) | 0 | 0 | 0 | 3 | 22 | +2271 | −2.02 |
| 907d762b | 2440 | 1160 | 6 / 25 | 0 (0) | 0 | 0 | 0 | 2 | 23 | +2159 | −1.50 |
| e404fde0 | 1693 | 1907 | 1 / 25 | 0 (0) | 0 | 0 | 0 | 0 | 25 | +11 | −1.91 |
| e404fde0 | 1893 | 1707 | 8 / 25 | 0 (0) | 0 | 0 | 0 | 0 | 25 | +1599 | −1.71 |
| e404fde0 | 2493 | 1107 | 2 / 25 | 0 (0) | 0 | 0 | 0 | 0 | 25 | +767 | −1.11 |
| e404fde0 | 2693 | 907 | 0 / 25 | 0 (0) | 0 | 0 | 0 | 0 | 25 | — | −0.91 |
| e404fde0 | 2813 | 787 | 1 / 25 | 0 (0) | 0 | 0 | 0 | 1 grounded | 25 | −633 | −0.79 |
| **pooled** | | | **50 / 225** | **0 / 225** | **0** | **0** | **0** | 15 | 210 | 2271 | |

**Registered outcome: INCONCLUSIVE** (approaches without passage): GO needed policy-initiated S2 ≥ 3 / 25 at some cut
or any policy-initiated S4; STOP needed pooled S1 ≤ 2 and S2 = 0.

What the 50 approaches are (per-episode trajectories in `foothold/work/*/episode.json.gz`): the policy walks to the
foot of the wall (grounded at x ≈ −1650, the floor's end, in 37 of 50), stays 30–100 steps there and jumps or up-Bs at
the face (near the wall above the floor the action classes are `airborne` 812 steps, `special_hi` 753, `special_n` 83,
`special_lw` 80, `attack_air` 10). The best climb reached y 2271 at x −1544 (907d762b τ 2160, k 10, tick 3573, mid up-B),
730 below the wall top and under the overhang (underside y 2700); median best height near the wall is below the
floor+2,000 line in every seed-1 cut. No episode was ever above y 3000 left of x −1200, so nothing to classify as a
takeoff, passage, landing or break; the one fall after an approach (2 in seed 1) was an off-stage fall on the left face.
The two apex cuts (1679, 1693) and the drifting cut (2693) produced no passage: inherited height without a jump left
ends in a descent to the floor. Seed 2's finals (deterministic play collapsed at tick 0) approached far less (12 / 125)
than seed 1's (38 / 100).

Distinguishing the stages the user asked for: **movement toward a possible takeoff** exists and is policy-initiated
(50 / 225, from grounded and airborne cuts alike); **policy-initiated takeoff toward the ledge** was not observed (the
attempts start from the wall foot, y −2550, and top out ≥ 730 short); **over-wall passage, qualified landing and
left-target breaks**: 0 / 225. Nothing here was inherited from the prefix: every approach began 450–1,100 ticks after the
cut, after the inherited motion had ended.

## 3. Avoiding M7m: what the prefix already accomplished

The prefix delivers the complete right sweep and a position; it delivers no crossing progress. Every cut is at or after
the sweep, so a "success" from these starts can never be a sweep, and an over-ledge passage within the inherited
up-B (τ 1679 / 1693, the first ~30 airborne ticks) or the inherited drift (τ 2693) would have been counted as inherited
by the registered rule; none occurred. There is no curriculum pointer here, so no easier cut can dominate a block; the
per-cut denominators above are the whole evidence.

## 4. The unchanged reward after the sweep (btt_reward_v2, frozen)

Measured on the sources' own post-sweep segments (replayed exactly): 907d762b earned −6.297 after the sweep (1,297
ticks × −0.001 and the −5 off-stage fall on the right), e404fde0 earned −1.907 (1,907 ticks, no event); the 225
continuations earned between −0.79 and −2.69 on average per cut, i.e. exactly the tick cost plus falls (15 × −5 pooled).
What v2 pays for after the sweep: +1 per left target (1, 6, 8), +10 for the clear, −5 for a native fall, −0.001 per
tick. **Before the first left-target break there is no positive signal at all**: an approach, a takeoff, an over-wall
passage and a landing on the left floor are all reward-neutral, and the only non-zero events on the way are falls (−5).
That is measured. The following is hypothesis, not measurement: under PPO with γ 0.999 the critic can only value the
crossing after the chain approach → passage → landing → break has paid at least once; with 0 passages in 225 attempts
from favourable states, the expected number of first payments in a 1,536,000-transition run with ~250 anchored
episodes is below one even before the landing and the break are required, and the fall penalty makes the wall foot a
mildly negative place to explore. Nothing in this document proposes changing the reward.

## 5. Recommendation: stop; no bounded training experiment is supported

The concrete blocker: **no policy-initiated over-ledge passage in 225 continuations from nine registered post-sweep
states (0 %), with 50 approaches (22 %) that all attempt the wall from its foot and top out at least 730 units below
the wall top.** The frozen v3 finals have wall-directed behaviour but not a climbable route from where they go; the
validated crossings took off from L1 or the platform far to the right and traversed at height, and neither policy
attempted that from those very surfaces (τ 1880 on L1: 12 approaches to the wall foot, 0 takeoffs toward the ledge;
τ 1893 / 2493 on the platform top: 10 approaches, 0 passages). A prefix-restart training run would therefore start from
states in which the discovery rate of the first rewarded event is unmeasurably small under an unchanged v2, and a
matched v3 continuation control would most likely record the same zero; time remaining in the sources is not a reason
to spend a campaign.

For completeness, the experiment that WOULD have been proposed on a GO, so the cost is on record: two seed pairs
(E_j, K_j for j = 1, 2), each warm-started from `m7n_s{j}_v3/final` (policy, Adam state, no statistics; v3 has none),
E with p = 1/2 anchored starts drawn uniformly from the registered cuts of its own seed's source, K tick-0 only through
the same machinery; +1,536,000 policy transitions per run (4 runs, 6,144,000; ~25 min training each at ~1,040 tr/s
plus ~5 min of prefix per E run at 5.2 s per anchored episode × ~250 episodes, ~45 min evaluation each; ~5 h total);
decision on normal tick-0 evaluation only (qualified crossings, left-target breaks, native-verified clears, early-sweep
retention R and L, falls, deterministic collapse), anchored outcomes reported separately; it would also have required an
opt-in v3 variant of the M7m prefix machinery (the anchor curriculum is registered for observation v1 and one anchor;
the v3 wrapper's builder must be fed the prefix replies), roughly 500–800 lines behind a new profile table, plus a
pilot. None of this is recommended now.

What would change the assessment (diagnostics, not training, each needing its own registration): a scripted
controllability probe of the wall from the wall foot and from L1 under Track 1 inputs (can any input sequence from
(−1650, −2550) or from L1 reach y ≥ 3000 left of x −1200 within the remaining horizon?), and a check of whether the v3
policies ever reach the platform top with jumps left and time left in normal tick-0 play. If the wall cannot be climbed
from its foot under Track 1, the approach behaviour observed here is a dead end and the route question precedes any
curriculum.
