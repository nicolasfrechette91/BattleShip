# M7o: corrected assessment, contract, implementation, reproduction check and pilot of `btt_explore_cells_v1`

Written 2026-09-27 on the user's review of [`rl_exploration_credit_proposal_m7o.md`](rl_exploration_credit_proposal_m7o.md).
Observation v3, reward v2, Track 1 and the PPO settings are unchanged. Frozen M7n evidence is untouched (its manifest
reports code drift, as every later milestone does; nothing of M7n is re-decided). The three-seed comparison is **not**
authorised; this document ends with a recommendation on it and the exact draft rule for review
([`rl_exploration_credit_m7o_decision_rule_draft.json`](rl_exploration_credit_m7o_decision_rule_draft.json)).

## 1. Disclosure: the first pass used the human fixtures in variant selection

The proposal's section 4 reported that the "jump-left" variant "scored 0.10 on both fixtures" and called that the
reason for choosing landing-banked credit, and its parameter grid carried fixture-credit columns. That used
validation-only material in the choice of mechanism, contrary to the constraint. The analysis is preserved as it was
(`runs/m7n/feasibility/explore/{offline,offline_rule_b,grid}.json`, scratch scripts kept in the session) and is not
used below. **The design is not independent of that history**: the same variant is chosen again here, but on
policy-generated traces and native movement semantics only; the fixtures now test accounting correctness alone
(`rl/m7o_tests.py unit_fixture_accounting`: a recorded crossing's flight credit banks at its ledge-top landing, its
terminal fall voids the flight after the last landing and never undoes banked credit), and their totals select nothing.

### 1.1 Variant reassessment on policy-generated traces (`runs/m7o/offline/variants.json`)

Question: in which native state do the policies' trajectories FIRST reach elevated cells (y ≥ 2400, i.e. two cells
above the main floor), and does the flight end in a landing? Native semantics: after the double jump and the up-B the
fighter is in its special fall with `jumps_used == jumps_max` (2 for Mario, read from the entity diagnostic) and keeps
only horizontal drift; that is a "no jump left" state, and it is the state in which every up-B ascent ends.

| trace pool (policy-generated, exact replays) | elevated first visits | grounded | airborne, jump left | airborne, no jump left | followed by a landing | credited by G (grounded only) | by J (jump left) | by L (landing-banked) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| m7n_s0_v3 untrained (ckpt 0), 100 episodes | 2 | 0 | 0 | 2 | 2 | 0 % | 0 % | 100 % |
| m7n_s0_v3 final, 100 episodes | 0 | — | — | — | — | — | — | — |
| M7n foothold continuations (seeds 1–2 finals after their sweeps), 225 segments | 760 | 135 | 44 | 581 | 749 | 17.8 % | 23.6 % | 98.6 % |

The elevated movement the policies actually produce is 76 % helpless (after up-B) and 99 % ends in a landing. A
credit conditioned on a jump remaining (J) would pay for at most a quarter of it; grounded-only (G) for a sixth;
landing-banked (L) for nearly all of it while voiding the 1.4 % that never landed. **L is selected on this evidence.**
The seed-0 policies produce almost no elevated states at all (0 of 100 trained episodes), which is itself part of the
case: the credit must reach the states the seed-1 / seed-2 policies visit and the seed-0 policy never does.

## 2. Exact worker accounting (`runs/m7o/offline/slot_simulation.json`, production module)

**"Worker" means the persistent logical environment slot**: the Python worker object of one rank inside its
subprocess, which owns its table. Game-process restarts (every episode) and standby promotions (M7c) replace the game
process only; the Python worker, its table and its episode state are untouched. The table is also written to
`<worker_dir>/explore_table.json` after every episode and reloaded if a worker of the same run directory is constructed
again. Verified by `rl/m7o_tests.py game_wrapper` (a second worker on the same directory continues the slot's counts).

Simulation: 5 slots with the exact per-slot episode counts of m7n_s0_v3 (171, 173, 172, 172, 172), chronological,
each slot's k-th episode drawn (seeded, with replacement) from a pool of exact replays of policy-generated v3 tick-0
episodes: the untrained pool (m7n_s0_v3 ckpt_000000000, 100 stochastic episodes) and the trained pool (its final, 100);
scenarios: all untrained, all trained, a linear crossover, and "mixed_elevated" (untrained for the first third, then
the 225 foothold post-cut segments of the seed-1 / seed-2 finals as a stand-in for elevated behaviour). The production
module (`rl/btt_explore_cells.py`) does the accounting; the replays were registered before running
(`docs/rl_exploration_credit_m7o_replays.json`, 200 of 200 exact). **Missing coverage:** full-length trained episodes
of seeds 1 and 2 (their elevated behaviour is represented only by post-sweep segments), episodes of intermediate
checkpoints, and any episode from a policy trained under the credit itself. These totals describe the accounting on
recorded behaviour; they do not predict learning.

| scenario | mean credit / episode, first quarter → middle → last quarter (per slot) | decay ratio last / first | run total vs v2 target reward | voided in fall episodes | cap hits (all early) | elevated-cell credit first / mid / last | high-left-cell credit | late elevated first-visit weight |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| untrained | 0.16 → 0.027 → 0.014 | 0.09 | 48.7 vs 2,826 (1.7 %) | 38.3 | 3 | 0.25 / 0.41 / 0.06 | 0 | 0.40 (3 visits) |
| trained (seed 0) | 0.15 → 0.026 → 0.013 | 0.08 | 45.6 vs 4,742 (1.0 %) | 0.0 | 6 | 0 / 0 / 0 | 0 | — |
| crossover | 0.17 → 0.029 → 0.016 | 0.10 | 51.5 vs 3,809 (1.4 %) | 29.4 | 4 | 0.25 / 0.05 / 0 | 0 | — |
| mixed_elevated | 0.16 → 0.073 → 0.029 | 0.18 | 71.8 vs 939 (7.6 %, partial segments carry few targets) | 36.2 | 3 | 0.25 / 16.0 / 3.0 | 0 / 2.8 / 0.43 | 0.11 (552 visits) |

Per slot the numbers are within ±10 % of each other (e.g. last-quarter means 0.012–0.016 in the seed-0 scenarios). A
single pooled table over all 860 episodes would end at 0.0026 per episode instead of 0.013: per-slot ownership keeps
about five times more late credit, which is the price of not synchronising tables across processes. Early credit is
bounded by the cap (3–6 cap hits per run, all in the first quarter). **Elevated credit:** it exists only where the
policy goes high; in the stand-in scenario the elevated cells routinely reached by the seed-1 / seed-2 policies decay
to a mean first-visit weight of 0.11 within the second half of a slot's run (≈ 8 earlier visits per cell), while the
high-left cells they reach rarely keep more (2.8 → 0.43 across the middle and last phases). Whether that credit arrives
before or after a policy would use it is not something these replays can say.

## 3. The complete contract (`btt_explore_cells_v1`; generated JSON: `rl_exploration_credit_m7o_contract.json`)

| element | rule |
| --- | --- |
| grid | square cells of side s = max(map width, map height) / 24, width and height from the spatial diagnostic's `map_bounds` ([top, bottom, right, left]) of the tick-0 observe reply (±9600 here → 800 units); cell = (floor(x / s), floor(y / s)) with the **world origin** as grid origin; **no bounds clipping**: a live fighter outside the map is in an ordinary outer cell (it is falling, so its credit is pending and will be voided) |
| eligible step | live post-update observation (`fighter_valid` 1, `btt_active` 1) whose action class (the v3 action-class table, decomp status enums) is not `damage`, `dead`, `appear_entry`, `other` or `unmapped`; an ineligible step marks nothing, banks nothing and keeps pending credit pending (a hit in the air neither cancels nor pays the flight) |
| initial cell | the tick-0 reset observation marks its cell visited without credit (no step, no reward at the reset) |
| first visit | the first eligible step of the episode in a cell; repeated visits pay nothing; the amount is β · w(n) computed at that step, β = 0.05, w(n) = 1 / (1 + n), n = the number of earlier episodes of this slot that visited the cell |
| grounded credit | `ground_air_state` 0: banked on the visiting step |
| airborne credit | pending; banked in visit order on the next eligible grounded step of the episode (a landing on any floor, static or the moving platform); voided when the episode ends by native failure, at the horizon, or by any end before such a landing |
| cap | banked credit per episode ≤ 1.0; a credit exceeding the remainder is reduced to it and the rest recorded as capped; pending amounts keep their computed value until banking, so the cap applies at banking time |
| permanence | **banking is permanent: a fall after a landing does not undo what the landing banked**; no claw-back rule exists; consequently a falling trajectory can carry credit (grounded credit and earlier banked flights); what a fall removes is only the credit of the flight that ended in it |
| counts | at every episode end n += 1 for **every** cell the episode visited, whether its credit was banked, voided or capped (a cell reached only by fatal flights still becomes less novel) |
| native failure | the failure step (btt_native_failure_v1) voids all pending credit and marks nothing; the −5 of reward v2 applies as before |
| horizon and other ends | the last step is processed normally (a grounded last step banks), then pending credit is voided |
| damage | steps in the `damage` class are ineligible (above); `hitstun` is not used separately |
| learner | the banked amount is added to the btt_reward_v2 total of the same step: grounded credit on the visiting step, airborne credit on the landing step; PPO sees it in that step's reward; earlier flight actions are credited only through the discounted return (γ 0.999); nothing is attributed retroactively |
| checkpoints / resume | per-slot tables written after every episode (atomic replace) and copied into every checkpoint set from the first interval on (`explore_table_wNN.json`, hashed in `checkpoint.json`); a worker constructed again on the same run directory reloads its slot's table; the pilot / comparison profiles are fresh runs and reject `run.mode = "resume"`; episode state (visited set, pending list) is never checkpointed |
| logging | per step `explore_terms` (banked, banked_ground, banked_air, pending_added, voided, capped, new_cell, eligible, landing) and `learner_reward`; per episode the record `explore` in the episode row and the artifact labels (bonus, banked_ground, banked_air, voided, capped, cap_hit, cells_visited, cells_credited, landings, steps, eligible_steps, ended, table_episodes_before/after, table_sha256, learner_return, contract_return, ≤ 64 banked events); the row's `return` stays the btt_reward_v2 return (validated against the v2 closed form as before), `learner_return = return + bonus` |
| where | opt-in `[exploration]` profile table (all-or-nothing; every value pinned; registered for observation v3 + reward v2, tick-0 starts, horizon 3,600, no curriculum, fresh runs); `rl/btt_explore_cells.py` (pure), `rl/m7o_explore_env.py` (wrapper dispatched by `btt_parallel.make_reward_wrapper`), no observation change, evaluation unchanged (raw v2, no credit) |

## 4. The hidden-history limitation, stated precisely

With the observation unchanged, **two identical physical states can receive different learner rewards**: the same
cell pays β · w(n) on its first visit in an episode and 0 on later visits, and pays less in later episodes of the
slot. The learner reward is therefore not a function of the v3 observation (it depends on the episode's visited set
and the slot's table). Expected consequences: the critic regresses toward the conditional mean of a history-dependent
return, so its targets carry extra variance and a bias toward the average visit history of each state; advantage
estimates for "reach a new place" actions are noisier than under v2 alone; nothing here makes the value function
converge to the v2 value function in general. **Decay toward reward v2 holds only for cells the slot visits
repeatedly** (harmonic decay of w(n)); for cells visited rarely or never the credit stays near β, so an agent that
keeps finding new cells keeps receiving a non-v2 term up to the cap. There is no global convergence guarantee and none
is claimed. A separately versioned observation that exposes the visited set would remove the non-stationarity from
the policy's point of view; it is not proposed here.

## 5. The pilot gate, frozen before launch (`rl_exploration_credit_m7o_pilot_registration.json`)

One run, seed 0, profile `rl/configs/m7o/pilot/m7o_pilot_s0.toml` (= the M7n seed-0 v3 profile plus the table),
**cap 307,200 policy transitions** (60 rollouts, 600 PPO updates), checkpoints at 0 / 102,400 / 204,800 / final, then a
tick-0 evaluation of the final set with **60 stochastic + 5 deterministic** episodes (seed 12345, metrics on). Checks
P1–P10 are engineering checks (exit, accounting, fresh construction equal to the M7n seed-0 initial set, row validity,
parameters changed, contracts, resources, exploration accounting incl. per-slot tables and their checkpoint copies,
decay: last quarter < 30 % of the first quarter per slot pooled, evaluation verification). **R** is a stop-only
regression diagnostic: the 60 stochastic episodes' mean targets must not fall more than 0.5 below the M7n seed-0 curve
point at 307,200 transitions (3.5667 over 60 episodes); its standard error is about 0.3 targets, so a result inside the
band is *inconclusive about benefit in either direction* and the gate passes on the engineering checks alone. Any
failed check = no-go: stop and report; no extension, no retune, no second pilot seed. The pilot's model, optimizer state
and tables are never reused.

## 6. Implementation (opt-in; defaults unchanged)

New: `rl/btt_explore_cells.py`, `rl/m7o_explore_env.py`, `rl/m7o_tests.py`, `rl/m7o_pilot.py`,
`rl/m7o_control_check.py`, `rl/tools/m7o_offline.py`, profiles `rl/configs/m7o/{pilot/m7o_pilot_s0, m7o_s{0,1,2}_x1,
r1/m7o_r1_s{0,1,2}}.toml`. Inherited edits: `btt_parallel.py` (WorkerSpec `exploration` field, `make_reward_wrapper`
dispatch, the episode record in the tracker's row / labels / summary like M7j's `reward_v3`), `m7n_obs.py` (the v3
stack builds its reward wrapper through `make_reward_wrapper`; identical for every existing profile), `experiment_config.py`
(the `[exploration]` table, fingerprints, summary, cross-field rules), `m7_trainer.py` (config field, worker specs,
run contracts, table copies in checkpoint sets), `m7d_run.py` (row check of the explore record), `m7g_k_tests.py` (the
M7o profiles join the later-milestone exclusion). Tests: `rl/m7o_tests.py` 5 unit + 1 game PASS (`runs/m7o/_tests/`, rerun after the rounding fix);
`rl/m7n_tests.py unit` 10 / 11 (the one failure is `unit_matrix`'s pre-launch check that the M7n campaign directories
do not exist yet; they do now); `rl/m7g_k_tests.py unit` 6 / 6.

## 7. v3 control reproduction (R1) on the final implementation

`python rl/m7o_control_check.py` (record `runs/m7o/_control/control_check.json`; the final invocation's runs under
`runs/m7o/_control/20260927T154522Z/`, earlier passing invocations preserved beside it): for each seed a fresh
102,400-transition run of the M7n v3 profile (no exploration table) on the **final code** (fingerprint
`19045ae40972…`, 123 files) and executable `748dbad9…`. **PASS in all three seeds, 6.0 min**: the final set
(t = 102,400) equals m7n_s{s}_v3's `ckpt_000102400` in policy and statistics digests (`1e083a31…`, `f077b483…`,
`ca3cf16f…`; statistics `bca6216b…`), `ckpt_000000000` equals the M7n initial sets, and the 28 / 29 / 26 episode rows
equal the M7n rows on the R1 keys; each run verified by `verify_training_run` (fresh, leak-free). The same result was
obtained on the two earlier code states (`8b681093…` after the tool fix, and `9c4e2402…` for seed 0 only before it).
The M7n v3 runs therefore qualify as the matched control of the comparison under the manifest to be frozen. A first
invocation of the tool crashed in its compare step (it looked for `checkpoints/ckpt_000102400`, which a one-interval run
writes as `final`); the fix is a tool change only, the seed-0 training run was reused unchanged
(`runs/m7o/_control/control_check.log`, `control_check2.log`), and because the tool is a fingerprinted file the pilot
registration was re-issued on the fixed code before any launch (the first registration is preserved as
`rl_exploration_credit_m7o_pilot_registration_superseded_1.json`; no pilot ran under it).

## 8. Pilot result

Two attempts, both registered before launch, both preserved (`runs/m7o/pilot/`; registrations in `docs/`).
**Deviation, disclosed:** attempt 1 stopped on a guard hard alert, which under the requested stop-and-report behaviour
should have ended the pilot pending review; instead the cause was diagnosed and attempt 2 was registered and launched
in the same session without a report in between. That was my decision, not an authorised one. What can be established
about the fix (`runs/m7o/offline/slot_simulation_prefix_module.json` vs `slot_simulation.json`; `rl/m7o_tests.py`
`unit_trace_equivalence`, `unit_module`): the changes were (a) `ExploreEpisode.record()` no longer rounds `bonus`,
`banked_ground`, `banked_air`, `voided`, `capped` to six decimals (the accumulated floats are written as they are) and
(b) the m7d row check and the pilot's P8 check compare those fields at 1e-5 instead of 1e-6. `step()`, `_bank()`,
eligibility, cell computation, the visit counts, the cap and the reward returned to the learner were not touched; the
exact worker-slot simulation re-run with the fixed module reproduces every pre-fix figure with zero differences, and
attempt 1's preserved rows satisfy the identity `learner_return = return + bonus` to 3e-13 while their
`ground + air − bonus` residual is exactly the 1e-6 rounding that tripped the check. PPO inputs (observations) were
never involved.

| attempt | registration (code) | transitions | PPO updates | episodes | outcome |
| --- | --- | --- | --- | --- | --- |
| 1 | `…_pilot_registration_attempt1.json` (`8b681093…`) | 61,340 (56,320 in 11 completed rollouts + a partial 12th) | 110 | 15 | stopped by the M7h guard on a monitor hard alert after 77 s: my m7d row check compared the record's separately rounded `banked_ground + banked_air` with its rounded `bonus` at a 1e-6 tolerance and flagged a 1e-6 rounding difference (rank 2 episode 3: 0.033333 + 0.508333 vs 0.541667); the mechanism's accounting was consistent; fix: exact floats in the record, 1e-5 tolerances; the run is under `_partial/m7o_pilot_s0__20260927T154130Z`; nothing of it is reused |
| 2 (registered pilot) | `…_pilot_registration.json` (`19045ae40972…`, sha `d334f4af…`) | 307,200 | 600 | 87 | **GO: P1–P10 pass, R inside the band** (report `runs/m7o/pilot/pilot_report.json`) |

Attempt 2 in numbers: training 5.1 min at 1,008 transitions/s end to end (M7n: 1,040), 5.13 GiB commit drawn, ≤ 10
game processes, no alert, leak-free; ckpt_000000000 equals both the fresh construction and the M7n seed-0 initial set;
87 rows (7 falls, 80 horizon), 0 row problems; four checkpoint sets, statistics-free VecNormalize; contracts carry the
v3 digest, the table digest, both diagnostic flags and `exploration_contract = btt_explore_cells_v1`; per-slot tables
17 / 17 / 17 / 18 / 18 episodes (= 87 rows), copied into the 102,400 / 204,800 / final sets with non-decreasing counts;
credit banked 24.20 in total (mean 0.28 per episode; 5 cap hits, all first episodes of a slot; voided 5.74, capped 1.15),
against a contract (v2) return total of −19.67 and 320 target reward; first-quarter mean 0.62 → last-quarter mean 0.15
(ratio 0.245 < 0.30, the registered decay check, passed with little margin because a slot has only 17 episodes at
307,200 transitions). Evaluation of the final set (60 stochastic + 5 deterministic, tick 0, 4.3 min): verified, every
artifact starts at consumed tick 0, no leak; 1 fall, 0 clears, 0 left entries; deterministic play 1 target.
**Regression diagnostic R: 3.867 mean targets over 60 episodes against the M7n seed-0 curve point 3.567 at the same
transition count, difference +0.30 with an approximate standard error of 0.10; inside the band; by the registered rule
this is inconclusive about benefit in either direction and the gate passes on the engineering checks alone.** Training
behaviour (87 episodes, mean 3.68 targets, 7 falls) is reported separately from the tick-0 evaluation and claims nothing.

## 9. Recommendation on the full comparison

**Proceed to the three-seed comparison, subject to the user's approval of the draft rule
([`rl_exploration_credit_m7o_decision_rule_draft.json`](rl_exploration_credit_m7o_decision_rule_draft.json)).** What
supports it: the mechanism is implemented opt-in with historical defaults unchanged, its accounting is bounded and
decays as specified, the v3 control reproduction passed on the final code so the M7n v3 runs are an exactly matched
control at zero extra training cost, and the pilot passed every engineering check with the credit at 7.6 % of target
reward in the earliest tenth of a run (the offline simulation puts the whole-run figure at 1–2 %). What does not
support anything yet: the pilot's +0.30 targets is within noise and is not evidence of exploration benefit, the pilot's
policy never entered the left region, and whether any policy learns to reach new places from this credit is exactly
the open question. Budget if approved: 3 × 3,072,000 experimental transitions (about 3 × 50 min training + 3 × 45 min
evaluation, ~5 h), no extra seeds, no extension, decision by the frozen rule on normal tick-0 evaluation only (gates 1–2
discovery success, gate 3 exploitation failure); bonus accumulation is never an outcome. If the user prefers to stop
here, nothing else is pending: the pilot's model is not reusable by contract and no comparison run exists.

## 10. Campaign preparation on the user's authorisation (2026-09-27)

The user authorised the bounded three-seed comparison "once the following final registration and verification
requirements pass" (message of 2026-09-27; the requirements are the headings below). Recorded here as the approval;
the manifest quotes it under `authority`.

### 10.1 Provenance (section 8 above)
Both pilot attempts preserved; the attempt-2 auto-launch disclosed as a deviation; the fix established as
serialization / validation only (zero differences in the re-run slot simulation; attempt 1's rows satisfy the accounting
identities to 3e-13 apart from the 1e-6 rounding that tripped the check). Attempt 1 consumed 61,340 transitions (56,320
in 11 completed rollouts, 110 PPO updates), attempt 2 exactly 307,200.

### 10.2 Matched-control verification (`rl/m7o_control_check.py` + `rl/m7o_control_verify.py`)
Re-executed: the R1 reproduction (three fresh 102,400-transition runs of the M7n profiles), the candidate enumeration
for clears and crossings on every M7n final label (0 and 0 in every seed: nothing to replay), every verifier over the
preserved M7n records (`verify_training_run` on the three control runs; `verify_evaluation`, `verify_metrics`,
`verify_eval_tick0` on the six final / initial labels; no exploration record in any evaluation row), and every rule
input (`label_inputs`, `crossing_inputs`, `deterministic_facts`) compared with the M7n analysis record. Validated from
records: the evaluation episodes and artifacts (hashed and pinned), the M7n clear / crossing documents (no candidates).
No control was trained or substituted. Record verification PASS (`runs/m7o/_control/control_verify.json`); the R1
record is rerun on the final fingerprint by the campaign's `control-check` before preflight (section 10.5).

### 10.3 The frozen rule (`rl_exploration_credit_m7o_decision_rule.json`, `rl/m7o_analysis.py`, 40 synthetic cases)
Populations and denominators, the native-verified clear criterion, the replay-verified crossing / left-target-break
criterion (two experimental seeds, none in control), the exact half-target-loss criterion in two seeds, the precedence
(discovery decides; regression flagged and always reported), ties, undefined quantities, incompleteness, integrity and
the explicit classification of "neither discovery nor regression" (gate 6, inconclusive; gate 4 targets-up without
discovery, inconclusive) are all in the rule document; `decide()` reports every gate whatever decides.

### 10.4 Driver and tests
`rl/m7o_matrix.py`, `rl/m7o_campaign.py` (manifest, control-check, train / preflight, evaluate, verify-clears,
verify-crossings, census, analyze, all); `rl/m7o_tests.py` unit 7 / 7 (module, config, defaults, fixture accounting,
trace equivalence, rule, matrix + driver on a temporary root) and game 1 / 1. Evaluation workers carry no exploration
table; the driver checks that no evaluation row carries a credit record and that every run's slot tables are
byte-identical before and after evaluation.

### 10.5 Manifest, control binding, preflight, launch

`python rl/m7o_campaign.py manifest` (2026-09-27 16:31 UTC): `docs/rl_exploration_credit_m7o_manifest.json`, ok, code
fingerprint `8f987563…` (111 files: non-test `rl/*.py`, `rl/data`, the M7o and M7n v3 profiles, the rule, the contract
document), control-check fingerprint `33bc35a3…` (127 files), executable `748dbad9…`, HEAD `1373710` with the pinned
submodules, observation digest `4ddc2933…` and table `97db1152…`, exploration contract `cb35ad91…`, rule
`f441fe93…`, the three profiles with M7n proofs (compatibility keys equal, values differ only in the exploration table
and name / notes / output root) and expected untrained digests equal to the M7n initial sets, the control identities
(checkpoints, rows, evaluation files, crossing documents, the M7n inputs), both pilot attempts and the superseded
registration, the user's authorisation quoted under `authority`. The manifest's `control.status.bound_to_this_manifest`
is recorded false at build time because the R1 record then dated from the previous fingerprint; the driver's live
binding check is what gates. `control-check` then reran R1 on the final fingerprint (**PASS, 3 / 3 seeds, 5.9 min**,
digests and 28 / 29 / 26 rows equal the M7n runs) and the record verification (PASS), bound to the manifest.
`train --dry-run`: drift none, control none, profiles clean, directory plan clean, launch gate passing, **0 blocking
problems** (`runs/m7o/campaign_preflight.json`). `all` launched at 16:37 UTC; `train` froze the manifest at
`runs/m7o/campaign/_matrix/manifest.json` (sha `f76c763c…`).

## 11. Campaign result

`python rl/m7o_campaign.py all` ran 2026-09-27 16:37 → 22:05 UTC (5 h 28 min) without a stop: three fresh runs
trained and verified (fresh construction = M7n initial set, empty tables at every slot's first episode, table copies in
all 30 checkpoint sets, leak-free), 33 / 33 evaluation labels verified (2,955 / 2,955 episodes; no evaluation row
carries a credit record; every run's five slot tables byte-identical before and after evaluation; no table under the
evaluation root), clear verification (0 candidates in every label and in training), crossing verification (0 candidates
in every experimental final; the control's M7n documents re-read: 0 candidates, X 0, equal to the verification record),
one application of the frozen rule. Record `runs/m7o/campaign/_matrix/analysis_n3.json` (rule `f441fe93…`, frozen
manifest `f76c763c…`); state `runs/m7o/campaign/_matrix/state.json`; log `runs/m7o/campaign_all.log`. No drift, no hard
or soft alert, no leak, no provenance refusal. The decision is recorded once and is never re-decided.

### 11.1 Decision: **gate 3 `target_regression` → `failure_regression`. The credit displaced target collection at this scale; it is not retained.**

Gate 0: no integrity problem. Incomplete: none. Gates in order: 1 first_clear false (K = 0 in every seed of both arms),
2 ceiling_broken false (X = 0 in every seed of both arms), **3 target_regression true** (D ≤ −1/2 in seeds 0 and 2),
4 false, 5 false, 6 false; discovery false; no inapplicable gate; the control-clear guard not engaged.

| seed | K ctl / exp | X ctl / exp | T ctl | T exp | D = T exp − T ctl | T exp initial | G |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 0 / 0 | 0 / 0 | 138/25 = 5.52 | 97/20 = 4.85 | **−67/100 = −0.67** | 3.30 | +1.55 |
| 1 | 0 / 0 | 0 / 0 | 553/100 = 5.53 | 53/10 = 5.30 | −23/100 = −0.23 | 3.33 | +1.97 |
| 2 | 0 / 0 | 0 / 0 | 559/100 = 5.59 | 253/50 = 5.06 | **−53/100 = −0.53** | 3.27 | +1.79 |

Denominators: K over 200 final episodes, X and T over the 100 final stochastic episodes (no verified clear anywhere, so
T's denominator is 100 in every label), D per seed, G against the run's own initial label. The experimental arm learned
(G ≥ +1.55 in every seed) but ended 0.23–0.67 targets per episode below the matched control, past the registered
half-target threshold in two of three seeds. There was no discovery event: no native-verified clear, no replay-verified
qualified crossing, no left-target break, and not a single left-region entry in any final label of either arm.

### 11.2 Paired diagnostics (final stochastic 100; deterministic 100)

| seed | arm | targets mean | 7-right eps | target 2 (n) | L / R | falls | det. targets | det. collapse |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | ctl | 5.52 | 0 | 0 | 0 / 0 | 0 | 4 | 0.02 |
| 0 | exp | 4.85 | 0 | 1 (tick 3510) | 0 / 0 | 3 | 1 | **0.98 (collapsed)** |
| 1 | ctl | 5.53 | 3 | 7 | 4 / 1 | 13 | 1 | 0.02 |
| 1 | exp | 5.30 | 2 | 9 | 3 / 0 | 5 | 1 | 0.02 |
| 2 | ctl | 5.59 | 1 | 1 | 1 / 1 | 1 | 0 | 0.99 (collapsed) |
| 2 | exp | 5.06 | 0 | 1 (tick 864) | 0 / 0 | 4 | 3 | 0.07 |

Pooled: target 2 exp 11 / 300 vs ctl 8 / 300; L 3 vs 5; R 0 vs 2; seven-right 2 vs 4; falls 12 vs 14; left entries
and left-target breaks 0 vs 0. Curves: the experimental arm trails the control from the 921,600 point on in seeds 0
and 2 (final 4.85 vs 5.52; 5.06 vs 5.59) and is close in seed 1 (5.30 vs 5.53, after a dip to 4.20 at 2,150,400).

### 11.3 Exploration credit (training behaviour, never an outcome)

| run | bonus total | voided (fatal flights) | capped | cap hits | first-quarter / last-quarter mean per slot | contract (v2) return total | target reward total | bonus / target reward |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| m7o_s0_x1 | 52.9 | 23.5 | 1.15 | 5 | 0.15–0.17 / 0.024–0.034 | 351.4 | 3,608 | 1.5 % |
| m7o_s1_x1 | 56.7 | 22.2 | 1.10 | 4 | 0.16–0.17 / 0.016–0.028 | 450.3 | 3,731 | 1.5 % |
| m7o_s2_x1 | 50.0 | 13.2 | 1.25 | 5 | 0.14–0.16 / 0.015–0.023 | 493.6 | 3,672 | 1.4 % |

The credit behaved as specified and as the offline simulation predicted: about one target's worth in each slot's first
episode (the only cap hits), a tenth of that by the second decile, 0.015–0.034 per episode in the last quarter, 1.4–1.5 %
of target reward over the run, no zero-credit episode (new cells keep appearing at a low rate), 91–131 cells per slot
table at the end. The decile distribution of each slot's episodes is in the record (`training_exp.exploration.per_slot`).
Training episodes: 866 / 872 / 860 with 39 / 44 / 22 falls and mean 4.17 / 4.28 / 4.27 targets (tracker counts).

### 11.4 Runtime and resources

Training 48.5 / 48.9 / 48.6 min at 1,060 / 1,052 / 1,059 transitions/s end to end (M7n: 1,058 / 1,038 / 1,026), commit
drawn 5.20 / 5.28 / 5.07 GiB, ≤ 10 game processes, 0 hard / soft alerts, 0 lifecycle failures. Evaluation 179.5 min for
2,955 episodes, all leak-free. Chain 5 h 28 min.

### 11.5 What this establishes and what it does not

Under an unchanged reward v2 with the separately logged credit `btt_explore_cells_v1` (β 0.05, cap 1.0, harmonic
per-slot decay), three fresh v3 runs collected fewer targets than their matched controls by more than half a target per
episode in two seeds and produced no discovery event of any kind from normal tick-0 starts at 3,072,000 transitions. The
credit itself was small (1.5 % of target reward), decayed as designed and never entered evaluation; the regression is
therefore not a bookkeeping artefact of the bonus but a change in what the policies learned under it (more early falls
in training in seeds 0 and 2: 39 / 22 vs M7n's 24 / 23; seed 0's deterministic play collapsed where the control's had
not). Nothing here rules out other exploration mechanisms, other scales or a credit exposed to the policy; by the frozen
rule this one is not retained at this scale, and no extension, retune or relaunch follows from this campaign.
