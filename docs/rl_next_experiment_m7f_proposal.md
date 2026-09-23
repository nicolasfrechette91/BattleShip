# Next controlled experiment after M7f — proposal

Status: proposal only. Nothing here was implemented or trained in M7f. Evidence: `docs/rl_target_ceiling_m7f.md`
(machine-readable `docs/rl_target_ceiling_m7f.json`).

## Selected category: **D — curriculum / route-diversity intervention**

Working name: **frontier-restart curriculum** (`btt_curriculum_frontier_v1`): during training only, some episodes start
from states the agent itself has rarely reached, re-entered exactly by replaying the canonical native action prefix
that reached them; full-task evaluation from tick 0 remains the only measure of success.

## Why D (the evidence that decides it)

1. **The ceiling is spatial.** The three never-broken targets are exactly the three left of the tall wall (IDs 1, 6,
   8), and Mario never went further left than x = -1650 (the wall face) in any of 3,074 replayed sequences / 5,797
   historical rows — every seed, checkpoint, contract, budget, policy mode, random play and the bias sample.
2. **The region beyond the wall has never produced a single reward.** 0 left-target breaks anywhere, so PPO has no
   gradient toward it. Only 14 sequences (0.46 %) even reached wall-top height, none closer to the wall than x = -357
   at that height, none ever standing on the wall-top ledge.
3. **More randomness already failed to get there.** The untrained, near-maximum-entropy initial policies (300
   episodes) and random play were exactly as confined as the trained ones, although they reached the greatest heights
   (y 4645). The M7e extension (3x the budget) improved targets inside the region (+0.653) but moved nothing across it.
4. **The binding problem is coverage of states, not information about targets.** The remaining set is nearly
   constant (`{1, 2, 6, 8}` in 90 % of six-target rows), so the aggregate `targets_remaining` plus position already
   pins it; memory cannot recall, and a mask cannot show, a region the agent has never visited.
5. **The simulation is exactly reproducible from tick 0.** 3,074 of 3,074 historical sequences replayed exactly in
   fresh processes (every consumed tick, observation, target event), across two executables, cold and parked starts,
   and three host modes. Any state the agent reaches can therefore be re-entered exactly by replaying its action
   prefix — no save state, teleport, gameplay change or hidden reset is needed.

A start-state curriculum over the agent's own frontier attacks points 1-3 directly and needs no route knowledge.

## Why not the other categories

* **A (remaining-target identity in the observation)**: identity is almost fully determined already (point 4), and
  no observation can create reward from an unvisited region. Would add a new observation contract without addressing
  the measured constraint.
* **B (recurrent policy)**: same argument; subset ambiguity is low (13 subsets reach >= 5 targets, all inside one
  confinement, and the remaining four are the same set in 90 % of six-target rows).
* **C (exploration / entropy, one PPO variable)**: the maximum-entropy end of that axis (untrained and random
  policies) is measured and is equally confined (point 3). A single PPO knob such as `ent_coef` would move the policy
  toward behaviour that never crossed the wall; it may reduce the late-training collapse but is not expected to break
  the ceiling. Kept as a candidate for a later, separate experiment.
* **E (additional unchanged-v2 training)**: prohibited by M7e's registered gate-3 response, and the checkpoint
  trajectory shows no later checkpoint acquiring any previously unseen target.
* **F (another diagnosis)**: the ceiling's composition is fully identified with direct native evidence. The one
  remaining unknown — whether the left region is reachable with Track 1 actions — is answered as a cheap preflight
  gate inside this proposal (Phase A below), without training and without approximating the TAS.

## Design

**Unchanged**: `btt_s9_b8_v1` (MultiDiscrete([9, 8])), the 15-value `btt_policy_obs_v1` (no target identity, no
diagnostic field enters the policy), `btt_reward_v2` (+1 per target, -0.001 per step, +10 clear, -5 native failure),
the PPO hyperparameters of M7e, N=5 with standby, the 3,600-tick horizon, fall = `native_failure`, fresh process per
episode, tick-0 non-consuming reset observation, VecNormalize observation-only.

**Archive (training orchestration only, never a policy input).** Cells are coarse bins of the existing observation:
`(floor(position_x / 300), floor(position_y / 300), targets_remaining)`. For each cell the archive keeps the shortest
canonical native action prefix (from tick 0) that reached it and a visit count. It is seeded **only** from the agent's
own training episodes of the same run — never from the TAS, never from hand-written routes, never from target order.
The M7f diagnostic is not used by the curriculum.

**Episode start.** With probability `p0 = 0.5` an episode starts at tick 0 exactly as today. Otherwise a cell is drawn
with weight `1 / sqrt(1 + visits)`, a fresh process replays the cell's prefix natively through the M1c path
(one action per native tick, consumed ticks checked, exactly as `rl/m7f_replay.py` does), and the policy acts from
there for the remaining `3600 - len(prefix)` ticks. Every curriculum episode is therefore a legal full-task trajectory
(prefix + policy suffix); prefix steps are not policy transitions, earn no reward and do not count toward the
transition budget. A prefix that ends in a native failure or a clear is never archived. The environment's reset
contract is untouched (fresh process, non-consuming tick-0 observation): a curriculum start is a separately declared,
training-only start distribution built on top of it, recorded per episode (`start_prefix_digest`, prefix length), not
a hidden reset action.

**Identity.** A new curriculum identity `btt_curriculum_frontier_v1` recorded in the experiment configuration and
every checkpoint; the TOML schema gains the curriculum block as a semantic field; resume across curricula is
refused. The native executable and the protocol are unchanged (`SSB64_RL_TARGET_DIAG` stays off in training).

**Controlled comparison.** Fresh models, seeds 0 / 1 / 2, 3,072,000 policy transitions each — the same budget, seeds,
PPO, lifecycle and evaluation schedule as M7e, whose three runs are the control arm (the curriculum is the only
difference). Pre-register every gate before any data exists, as M7d / M7e did.

## Evaluation (full task is authoritative)

* Only tick-0, full-task episodes are evaluated, post hoc, frozen statistics, the M7e protocol (100 stochastic + 100
  deterministic at the final checkpoint, curve points every 307,200). Curriculum starts never enter an evaluation.
* Every evaluation episode is additionally replayed once with `SSB64_RL_TARGET_DIAG=1` (M7f tooling) to report per-ID
  break rates, the left-region entry rate (x < -2100) and wall-top ledge visits — diagnostic only.
* Primary outcome: final stochastic mean targets vs M7e, per seed and pooled (bootstrap CIs as M7d / M7e).
* Ceiling outcomes: any full-task evaluation episode breaking a left-of-wall target; any episode with >= 7 targets;
  any verified clear.
* Guard metrics: falls, deterministic collapse, tail fraction, entropy — the curriculum must not buy targets with
  instability.

## Phase A gate (before any training; cheap, no model)

Feasibility of crossing with Track 1 from the frontier, measured without learning: build the archive from the stored
M7d/M7e replayable episodes (their own frontier cells, not the TAS), then run uniformly random Track 1 suffixes from the
highest-frontier cells for a fixed budget (e.g. 2,000 episodes) with the target diagnostic on.

* If any such episode enters x < -2100 or stands on the wall-top ledge: reachability shown; proceed to training.
* If none does: stop and report — the barrier is not crossable by Track 1 exploration from the agent's frontier, and
  the next question becomes the action contract (a new, separately versioned Track), not the learner.

## Pre-registered decision gates (to be finalised before Phase B)

1. Curriculum works: >= 1 full-task evaluation episode breaks a left target or reaches 7 targets in >= 2 of 3 seeds.
2. Target gain: pooled final stochastic mean targets exceeds M7e's 4.58 with a bootstrap CI excluding 0.
3. No regression: falls, deterministic collapse and tail fraction not worse than M7e beyond their noise.
4. Null: no left-region entry in any full-task evaluation — report; do not extend the budget silently.

## Explicit non-goals

No reward v3, no target-order or route hints, no TAS prefix or TAS-derived cell, no new observation field for the
policy, no change to native gameplay, stepping or reset semantics, no RNG handling.

## Post-analysis project decision (addendum, recorded after this proposal)

The recommendation above is the M7f evidence-based result and is kept as written. This addendum records a later
project decision about sequencing; it changes no M7f diagnostic result, and nothing here was re-measured or
re-validated.

* **Reported by the user (not yet repository-validated):** both wall crossings are achievable using only the existing
  `btt_s9_b8_v1` Track 1 actions — (1) the precise lower-platform jump, and (2) the moving-platform-assisted upper
  crossing. This rules out a known action-space impossibility and answers the feasibility question the Phase A gate
  above was designed to probe. It is not a repository-validated fact until canonical Track 1 sequences for the
  crossings are captured and replayed.
* **Next milestone, first step:** capture and validate one Track 1-only, tick-0 fixture for each crossing (fresh
  process, canonical native actions, exact consumed-tick reproduction, native evidence of reaching x < -2100 by that
  crossing).
* **Use restriction:** those fixtures are validation evidence only — never PPO demonstrations, curriculum start
  states, archive seeds (the archive stays seeded only from the agent's own episodes), reward shaping or any other
  training signal.
* **Order of work:** because the project decided that the agent should perceive visible stage information, a
  structured observation v2 (a new, separately versioned observation contract, compared under controlled conditions
  against the frozen 15-value `btt_policy_obs_v1`) will be designed and compared **before** the frontier curriculum
  is launched. This supersedes the "no new observation field for the policy" non-goal above only for that separate
  observation-v2 experiment; the curriculum itself, when it runs, keeps the observation fixed as specified.
* **Status of category D:** deferred, not erased. It remains the recorded M7f recommendation and a candidate after
  the observation-v2 comparison. Once validated, the crossing fixtures answer only the action-space part of its
  Phase A gate (a Track 1 crossing exists); whether exploration from the agent's own frontier reaches a crossing
  remains that gate's question.
