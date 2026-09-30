# M7u preparation: implementation record (2026-09-29)

**Status.** Preparation only, as authorised: opt-in Python implementation, offline unit tests, the compute benchmark
and read-only clock-consistency checks. **Nothing launched BattleShip, collected or consumed a native tick, replayed an
episode, or trained on recorded data.** No gate approval record exists, and nothing was committed or pushed. The native
gate `m7u1` remains separately unauthorised; `python rl/m7u_gate.py run` refuses without an approval record.

**2026-09-30 update.** The user authorised gate `m7u1` once, as configured in §11. Before the approval record was
written, the driver gained evidence recording only (§9, item 9), verified behaviour-neutral. The approved sources are
kept in a verified D: source snapshot named in the approval record `docs/rl_model_planning_m7u_gate_approval.json`.

**2026-09-30, second update.** That first attempt stopped at the standalone preflight
(`docs/rl_model_planning_m7u_gate_report_2026-09-30.md`): `unit_approval_refusal` required the repository's approval
record to be absent. The user authorised a test-only repair (§9, item 10). It changes only that test, and so only the
code identity of `rl/m7u_tests.py`. A new snapshot and a superseding approval record follow; the first record is kept
as `docs/rl_model_planning_m7u_gate_approval_r1_superseded.json`.

**Unchanged:**
- the selected baseline: v3 + reward v2 (Track 1 PPO);
- the schema defaults (v1 / v1);
- every existing contract, profile and file outside the new `m7u` files;
- M7t: stopped before final acceptance;
- all historical outcomes;
- the user's replay work.

Design: `docs/rl_model_planning_m7u_proposal_2026-09-29.md` (revision 2, committed in `ad89c0a`).

**Scope label, carried by every M7u record.** Local control after the agent's own supplied recorded prefix. A reach is
a rising airborne point 64 ticks from a start state taken from this run's own behaviour episodes. It is never reported
as a landing, a crossing or a policy-controlled reach from tick 0. `rl/m7u_rule.py` rejects those words in the decision
summary.

## 0. State

| item | value |
| --- | --- |
| parent | `main` at `ad89c0a` = `origin/main`. New untracked files only (§1); no tracked file modified |
| submodules | `decomp e4f06348`, `libultraship 805f1950`, `torch 3aa9c97`, unchanged. No native change: every field comes from the existing `SSB64_RL_SPATIAL` / `ENTITY` / `INPUT` diagnostics |
| environment block | the unchanged v4 profile `rl/configs/m7q/m7q_pilot_s0.toml`, read-only: 5 workers + 1 standby each, horizon 3,600, no-render + Raphnet bypass, the three diagnostics, reward v2 recorded only |
| compute | torch 2.14.0+cpu, 6 threads, 6 cores |

## 1. Files (all new)

| file | role |
| --- | --- |
| `rl/m7u_state.py` | native row (`m7u_native_state_v1`, 50 fields from one raw reply), bookkeeping history (`m7u_bookkeeping_v1`), clock track (`m7u_clock_track_v1`) with its disagreement check, static world (pinned stage table), numpy reference segment rows. NumPy only |
| `rl/m7u_model.py` | vocabularies and masks, torch featurisation (the single production path), batched bookkeeping, `DynamicsEnsemble` (E = 3), losses, training, rollout, persistence |
| `rl/m7u_planner.py` | segment sampler, fixed-draw streams, candidates, retention, scoring, controllers P / RC / S / collect. No transport import |
| `rl/m7u_goals.py` | held-out split, exact pooled chance q, rising-airborne goal selection, scrambled pairing |
| `rl/m7u_rule.py` | `m7u1_control_rule_v2`, null readings, scope wording check, self-test |
| `rl/m7u_analysis.py` | reported diagnostics: attribution, witness test, calibration, held-out accuracy, ambiguity flags |
| `rl/m7u_worker.py` | worker stack (probe below the recorder, trial wrapper above v4), sidecar `m7u_states.npz`, environment settings |
| `rl/m7u_gate.py` | driver: preflight, approval refusal, D: coverage over the base and **every** discovered increment, ledger, wall and memory caps, phases, rule |
| `rl/m7u_tests.py` | 17 unit cases and the offline `e2e` mode |
| `rl/tools/m7u_bench.py` | benchmark `m7u_bench_v1` |
| `rl/tools/m7u_track_check.py` | read-only clock-track check on existing captures |
| `docs/rl_model_planning_m7u_implementation.md` | this record |

Outputs of the tools and tests are Git-ignored:
- `logs/m7u_bench/bench.json`;
- `logs/m7u_track_check/track_check.json`;
- test outputs in the session scratchpad.

Nothing is written under `runs/`: the tools refuse it.

## 2. Controller state: what is encoding, what is learned (review point 1)

Native controller words stay the replay truth.
- The unchanged M4 recorder stores every submitted word as a canonical native word from tick 0, prefix words included.
- Exact replays resubmit the artifact's canonical words: `artifact_track1_words`.
- The planner only chooses Track 1 indices. The unchanged `Track1PolicyWrapper` turns them into native words.

| quantity | kind | representation | evidence |
| --- | --- | --- | --- |
| the submitted word | **controller truth** | exact: one-hot stick 9 + button 8 for a_t | M4 artifact |
| previous words a_{t-1..t-3} | **bookkeeping** (words only) | exact one-hots in the input; in imagination they are the plan's own words | same function for recorded and imagined sequences (§4) |
| held buttons (the game's latched `button_hold`, after its R → A+Z fold) | **not model state** | stored in rows for verification; NaN in imagined rows; never an input or target | on all captured live ticks, latched hold = fold(submitted word): **27,521 / 27,521**, so it carries nothing beyond the word window. The fold appears only in this data test (`unit_rows_and_encoding`), never in the model or planner |
| fresh edges and releases (the game's latched `button_tap` / `button_release`, 7 contract bits each) | **learned native state** | input features of the current row; targets of H5 (14 Bernoulli). They carry what words alone cannot: OR-accumulation during hitlag, the hit tick clearing edges (`ftmain.c:4157`), Turn re-injection (`ftcommonturn.c:34-37`) | word-level edge ≠ latched tap mask on **1 of 27,393** captured non-hitlag ticks; hitlag ticks differ by design |
| stick tap counters `tap_stick_x/y` | **learned native state** | 5-level class (1 / 2 / 3 / 4-253 / 254), H5 categorical, including the game's forced 254 resets; levels of the two previous ticks from bookkeeping | covers the jump-squat entry condition (proposal §3) |
| Z timer `tics_since_last_z` | **learned native state** | 12-level class (0-10, 11+), H5 categorical | Z-cancel boundary |

**Consistency.** Imagined edges are not asserted from the words: no latch, fold, band or reset rule exists in the model
or planner. They are learned predictions, decoded by argmax. Their errors appear as realized model error on executed
words and in the MODEL attribution. The word window itself is always exact.

## 3. All 72 words, and what the projectile-free model leaves ambiguous (review point 2)

**Nothing is masked or suppressed.**
- Segments draw stick 9 × button 8 uniformly.
- 20,000 RC ticks contain all 72 words and all 8 buttons.
- 20 decisions' candidates contain all 72 words.
- B (fireball, up-B, tornado) is always available.

The model predicts Mario's own dynamics in every status, including the fireball and tornado statuses. Projectiles are
neither an input nor a prediction in m7u1.

**What omitted projectile and persistent state can make ambiguous:**

| omitted | can make ambiguous | flag recorded per trial (`m7u_analysis.ambiguity_flags`) |
| --- | --- | --- |
| live owned projectiles | a target broken by a fireball. An up-B passing that spot then has no hitlag (5-6 ticks of frozen position) that the model would have predicted, or the reverse | `projectile`; `break_without_attack` (a live bit cleared while Mario's attack is inactive) |
| `is_expend_tornado` beyond the bookkeeping bit | the B-tap rise of a second air tornado in one airtime | `second_air_tornado` |
| shield health and shield internals | shield size and a break after long cumulative shielding | `shield` |
| conditionally covered statuses (Turn flip timing, Squat entry path, jab 1-3 / down-tilt follow-ups) | the hidden flags of those moves | `conditional_status` |

**Effect on a NULL.**
- The rule counts native outcomes only, so flagged trials count like any other.
- The diagnostics report MODEL / PLAN attribution twice: over all P failures, and over P failures without any flag.
- If the MODEL share collapses once flagged trials are removed, the omitted state is the likely cause, not the approach.
- If it persists, the omission does not explain the null.
- Rising-point goals rarely need these mechanics, so flags are expected to be uncommon. That is a prediction, reported
  as measured.

## 4. Controls, exactly (review point 3)

- **Stream per goal.** Key `m7u1|0|goal|k`, shared by P, RC and S of goal k (common random numbers). Collection
  episodes use `m7u1|0|collect|<entry>`. Each decision's generator is PCG64, seeded with
  sha256(`m7u|cand|` + key + `|` + decision index)[:8] (little-endian).
- **Fixed draw block per decision**, identical whatever the arm or state:
  - 64 refill segments;
  - 15 mutation positions + 15 replacement segments;
  - (N − 16) fresh plans × 64 segments.

  A segment is (stick 9, button 8, tap | hold, length {1, 2, 4, 8, 16, 32}), and its expansion equals
  `rl/m7r_commit.tick_word` for all 576 options.
- **Candidates:**
  - 0 = the retained plan shifted by 4 words, extended with refill segments (at a trial's first decision: refill
    alone);
  - 1-15 = candidate 0 with one segment resampled (index ⌊u·n⌋), re-extended with the unused refill segments;
  - 16..N-1 = fresh plans.

  All are truncated to H = 64.
- **Retention and execution.** The chosen candidate becomes the retained plan. Its first 4 words are submitted, one
  native tick each. The next decision comes after exactly 4 controlled ticks, and a word is refused while a decision is
  due.
- **P:** argmin over candidates of the mean member cost + 1.0 × its population std, ties to the lowest index.
  - Member cost = min over τ < min(64, remaining budget, predicted fall) of Chebyshev distance / 150 + 1 · grounded
    + 0.1 · (τ+1)/64.
  - The cost is 10 when a fall is predicted within the horizon with no reach before it, or when no τ is valid.
- **RC:** candidate 0 at every decision; **no model is evaluated**. `choose` refuses any other index, and a test
  checks that RC decisions never reach the model. Its word stream is regenerated offline and must equal every
  collection episode (a driver integrity check).
- **S:** P's rule commanded to π(g) = goal (k + 20) mod 40, scored on g. Reaching π(g) ends nothing.

## 5. Driver: ledger, caps and outcomes (review points 4 and 5)

**Native-tick ledger.** Before every request, the driver refuses any phase that would exceed its cap.

| phase | cap |
| --- | ---: |
| P1: the 2 shortest pinned Track 1 artifacts (3,361 + 2,560 words) | 5,921 |
| collection, 92 × 3,600 | 331,200 |
| storage check (1 training episode replayed) | 3,600 |
| **evaluation prefixes**, 120 × ≤ 600 (own held-out words, itemised) | 72,000 |
| evaluation controlled ticks, 120 × 96 | 11,520 |
| success replays (≤ 6 P + 2 RC + 2 S) × 696, prefixes included | 6,960 |
| **total** | **431,201** |

**Wall caps**, from launch (the start of P1, the first native process; the zero-tick preflight precedes it):

| phase | cap |
| --- | ---: |
| P1 | 180 s |
| collection | 600 s |
| storage | 120 s |
| goals + training | 900 s |
| evaluation | 1,500 s |
| replays + analysis | 300 s |
| **global** | **3,600 s** |

Main-process private memory ≤ 3,072 MB (sampled).

**Outcomes:**
- **INCOMPLETE:** any tick, wall or memory cap, or too few goal candidates. It is not a performance result; there is
  no retry and no extension.
- **INVALID:** any integrity failure (below). The rule never sees a partial run.

**Integrity checks:**
- P1 words identical;
- every episode's reset world equals the pinned stage table (digest);
- every collection episode's words equal the RC regeneration;
- every sidecar equals the streamed rows;
- the clock track is consistent on training episodes and equal on held-out ones;
- the storage replay is exact;
- per-trial start-state identity (every field, exact);
- the platform matches the track during evaluation;
- model parameters are unchanged through evaluation;
- every replayed success is exact: action digest, every row field, reach tick;
- the ledger stays within budget.

The driver never commits, pushes or deletes, and needs `docs/rl_model_planning_m7u_gate_approval.json`, which does not
exist.

## 6. Test results

`python rl/m7u_tests.py unit`: **17 / 17 passed** (final code; report path in §9).

| case | result |
| --- | --- |
| expansion and coverage | 576 / 576 options equal M7r; RC 72 / 72 words; candidates 72 / 72 |
| streams and retention | deterministic fixed-shape draws at N 64 / 32; identical candidates across P / RC / S; RC forced to 0; candidate 0 continues the retained plan; decision-due refusal; RC regeneration = controller loop |
| score | best candidate, fall cost, contact penalty, budget cut |
| rows and encoding | hold = fold(word) 27,521 / 27,521; word edge vs latched tap mismatch 1 / 27,393 (reported) |
| world and track | 11 / 11 capture reset worlds = pinned; 3,601 ticks consistent; a planted platform disagreement is caught |
| featurisation equivalence (27,521 rows) | vs the unchanged v3 / v4 builders: agent 0.0, targets 0.0, class 0.0, torch history = numpy history 0.0, segments 2.4e-7; bookkeeping status tics ≠ native on 15 rows (same-status re-entries, by design, identical in training and imagination) |
| model | caps enforced; every imagined status / ground-air / contact combination is a recorded one; live flags monotone; clock +1; echo fields NaN; synthetic fit lowers its loss; save / load round trip |
| import isolation | planner / model / state / goals / rule / analysis import no transport or env module; the worker imports no torch |
| goals | exact q = brute force; deterministic selection; constraints; derangement; incomplete on too few candidates; 92 → 80 / 12 split |
| rule | self-test, including PASS / NULL disjointness |
| ledger and clock | refusal before exceeding; phase, global and memory caps |
| driver collection + single env | ledger = ticks; RC streams; sidecars; a cap one tick short stops first; exact single-env replay; a wrong replay word is refused before sending |
| driver evaluation | prefixes itemised and guarded; start identity; S scored on g; RC never reaches the model; budget / reach ends; a wrong expected start row is INVALID |
| gate stops | P1 mismatch → INVALID; collection wall cap → INCOMPLETE |
| real v4 stack on a capture | the real `EntityObsV4Wrapper` + M7u wrappers stream rows equal to the recorded replies; a trial ends as `goal_reached` on the first valid reach |
| worker stack assembly | documented layer order, with the native class substituted so nothing can launch |
| approval refusal | no record exists; `approval_status` refuses |

`python rl/m7u_tests.py e2e` (final code, 289 s) runs `run_gate` through every phase at production counts over the
synthetic stand-in: 92 episodes, 12 held out, 40 goals × 3 arms, replays, rule. Fake horizon 700, N = 17, 40 optimizer
steps. It exercises the driver's glue; its outcome says nothing about Mario.
- **Phases:** P1 → collection (92 episodes) → integrity (RC regeneration, sidecars, clock track, held-out track) →
  storage replay → goals (1,253 candidates, 64 in the tail, 28 filled) → training → 120 trials → diagnostics → 10 exact
  replays → rule.
- **Integrity problems:** none.
- **Ledger:** P1 700, collection 64,400, storage 700, evaluation prefixes 37,191 and controlled 5,994 (itemised),
  replays 3,676.
- **Diagnostics computed:**
  - MODEL share, and the share over unflagged failures;
  - witness share;
  - calibration AUROC, executed and held-out;
  - held-out one-step and open-loop errors.

  They are all meaningless on the synthetic world.
- **Rule:** returned a valid outcome class.
- **Scheduling:** most P / S decisions were planned one at a time, which confirmed correction 1 of §9.
- **After the evidence amendment (§9, item 9):** rerun on the amended code. Goals digest, model parameters, all 120
  trials' decision logs and reach ticks, outcomes, ledger and the 10 replays are identical to the run above; the
  evidence files are written and checked (split separation, supplied prefixes, predictions only where the model ran).
  Wall 565 s instead of 289 s: the machine was loaded (about 1.2 cores used by other applications), and every phase
  slowed, collection included, which records nothing new.

`python rl/m7u_gate.py preflight` (final code; zero native ticks) refuses for exactly one reason: **no approval record**.
Everything else passes:
- unit suite 17 / 17;
- rule self-test;
- benchmark choice N 64 / S 6,000;
- track check ok;
- D: coverage of all 391,625 `runs/` files with 0 uncovered (base + `_incr_m7r` + `_incr_m7s`; `_incr_m7t_logs` is
  skipped because it has no top-level record — its sources are under `logs/`);
- no BattleShip process;
- executable present;
- `runs/m7u` absent.

Test outputs (scratchpad; not preserved): `m7u_unit_final/m7u_unit.json`, `m7u_e2e_final/m7u_e2e.json` and the e2e
driver state.

## 7. Read-only clock-track check

`python rl/tools/m7u_track_check.py` over the 11 traces of `runs/m7q/_equiv/input_all`, read, not replayed. The 8 Track 1
policy / random episodes and the 3 TAS host-mode traces are all used only as read-only validation evidence.

| measure | result |
| --- | --- |
| verdict | **ok** |
| distinct word sequences | 9 |
| ticks covered | 3,601 |
| valid rows compared | 28,873 |
| disagreements (platform translate / speed, moving target position) | 0 |
| moving target minus platform, maximum deviation from +600 | 0.00024 |
| reset worlds equal to the pinned table | 11 / 11 |

The gate repeats the check on its own training episodes before training.

## 8. Benchmark `m7u_bench_v1`

`python rl/tools/m7u_bench.py --timed 200 --warmup 20`, run 2026-09-30T03:38Z on an otherwise idle machine. An
earlier start was stopped and discarded because a concurrent `git status --ignored` walk overlapped it. Record:
`logs/m7u_bench/bench.json`, sha256 `65bd6a0a…`, 404 s.

**Setup.**
- Machine: Intel64 Family 6 Model 158 (6 cores), Windows 11 26200, Python 3.13.2, torch 2.14.0+cpu, **6 threads**.
- Model: the pinned architecture at its vocabulary caps (S 160, V3 128, V4 64), E = 3, 892,761 parameters.
- Weights: seeded random and discarded.
- Training steps: synthetic tensors.
- Captures: used read-only, for featurisation / shape / forward timing only.

**Exact accounting** (linear layers; embedding gathers excluded):

| quantity | N = 64 | N = 32 |
| --- | ---: | ---: |
| MACs per transition (one member) | 292,800 | 292,800 |
| forward FLOP per transition | 585,600 | 585,600 |
| transitions per decision (3 × N × 64) | 12,288 | 6,144 |
| transitions per controlled native tick (one decision per 4) | 3,072 | 1,536 |
| forward FLOP per decision | 7.20 G | 3.60 G |
| planning decisions in the gate, maximum (40 × 2 arms × 96 / 4) | 1,920 | 1,920 |
| planning FLOP in the gate, maximum | 13.8 T | 6.9 T |
| training FLOP (forward + backward ≈ 3 × forward; 3 × 1,024 per step; 6,000 steps) | 32.4 T | — |

**Measured** (200 timed after 20 warm-up):

| measurement | median | p95 |
| --- | ---: | ---: |
| complete planning decision, N = 64, alone (generation + featurisation + 12,288 rollout transitions + scoring + choice) | 0.316 s | 0.319 s |
| complete planning decisions, N = 64, batch of 5 | 0.694 s | 0.782 s |
| complete planning decision, N = 32, alone | 0.253 s | 0.261 s |
| complete planning decisions, N = 32, batch of 5 | 0.475 s | 0.488 s |
| featurisation only, 960 / 480 rows (one rollout step at N = 64 / 32, batch 5) | 5.5 / 3.6 ms | — |
| training step, batch 1,024 × 3 members, Adam, synthetic tensors | 33.7 ms | 35.6 ms |
| transition building (featurisation + bookkeeping + targets), per transition, on capture rows | 14.4 µs | — |
| peak private memory of the benchmark process | 833 MB (cap 3,072) | — |

**Choice** (the permitted values only; each projection ≤ 720 s):

| candidates N | planning, revision 2 rule (batched p95 × 1,920 / 5) | planning, unbatched (p95 alone × 1,920), used | fits |
| ---: | ---: | ---: | --- |
| **64** | 300.1 s | **613.1 s** | **yes → chosen** |
| 32 | 187.5 s | 501.1 s | yes |

| training steps S | projection (median step × S + 92 × 3,600 transitions built) | fits |
| ---: | ---: | --- |
| **6,000** | **207.0 s** | **yes → chosen** |
| 4,500 | 156.4 s | yes |
| 3,000 | 105.9 s | yes |

**End-to-end projection.**
- Native throughputs come from records, ×0.8 safety: 5 workers 1,231 → 985 ticks/s (M7s phase A); single worker
  529 → 423 ticks/s (M7s P1, including starts).
- Allowances:

  | allowance | value |
  | --- | --- |
  | restart per episode per worker | 3 s |
  | single-process start | 3 s |
  | vector close | 30 s |
  | single close | 10 s |
  | goal selection | 30 s |
  | rule and records | 30 s |

- Analysis is projected as 42 single-decision latencies plus held-out transition building.

| phase | projected | cap |
| --- | ---: | ---: |
| P1 (5,921 ticks, 2 starts) | 30.0 s | 180 s |
| collection (331,200 ticks max, 92 restarts / 5 workers) | 421.6 s | 600 s |
| storage (3,600 ticks) | 21.5 s | 120 s |
| goals + training (S 6,000) | 237.0 s | 900 s |
| evaluation (83,520 ticks, 120 restarts / 5, 1,920 unbatched decisions) | 799.9 s | 1,500 s |
| diagnostics + replays (6,960 ticks, 10 starts) | 191.8 s | 300 s |
| **total** | **1,701.7 s (28.4 min)** | **3,600 s** |

**Verdict: it fits.** No budget was expanded. Native throughput with the M7u wrappers (row extraction and sidecars)
was not measurable without a native run. The 0.8 factor and the caps cover it; a miss ends the run INCOMPLETE.

## 9. Corrections and deviations found in implementation

1. **Planning projection.** Revision 2's rule (p95 batched latency × 1,920 / 5) assumed 5-way batching. The evaluation
   cannot guarantee it: trials enter control at different ticks after prefixes of different lengths. The offline e2e run
   confirmed mostly unbatched decisions. The choice therefore uses the larger of the batched and unbatched projections
   (p95 single decision × 1,920). The permitted choices and the 720 s limit are unchanged.
2. **Model input.** Dense 338 + 2 × 16 status embeddings = **370** trunk inputs (revision 2: 356). The 14 latched
   tap / release bits were added as state (§2), and H5 gained the matching 14 Bernoulli outputs. The echo fields
   (stick, hold) were removed from the input, as revision 2 specified.
3. **Static world** from the pinned stage table (`rl/m7g_spatial.EXPECTED_LINES`, static target centres), checked against
   every episode's reset reply by digest. Captures: 11 / 11 equal.
4. **Clock start.** The 60-minute cap starts at launch (P1). The zero-tick preflight, whose unit suite and coverage walk
   take minutes, precedes it and launches nothing.
5. **Performance.** Lookup tables replaced per-call one-hot and tap-level construction, row composition was vectorised,
   and rollouts run under `inference_mode`: 0.41 → 0.31 s per N = 64 rollout. Outputs are unchanged (the equivalence
   tests pass). 6 torch threads measured fastest (1 / 2 / 6 threads: 0.34 / 0.32 / 0.31 s).
6. **Status tics** come from bookkeeping (ticks since the status id changed). This equals native `status_total_tics`
   except on same-status re-entries (15 / 27,521 captured rows). The same value is used in training and imagination.
7. **Backup coverage** reuses `m7s_gate.combined_coverage` unchanged, with increments discovered from `D:\`: every
   folder whose top-level verification record's source lies under `runs/`. `_incr_m7t_logs` is listed as skipped. The
   stale `BACKUP_INCREMENTS` constant of `m7s_gate` is untouched.
8. **Diagnostics wiring.** Held-out accuracy, calibration and the unflagged MODEL share (§3) were added to the
   driver's diagnostics phase after the benchmark. They are forward passes only: a few seconds in the e2e run, inside
   the analysis allowance. They change none of the measured quantities.
9. **Evidence recording (pre-approval amendment, 2026-09-30).** The authorisation asks for per-tick model inputs,
   predictions and candidate-selection records. The prepared driver kept only each decision's chosen index and the
   number of members predicting a reach. Added to `rl/m7u_gate.py` and checked in `rl/m7u_tests.py`, recording only:
   no computation, stream, choice, cap or configuration value changed.
   - `_gate/collection.json`: every collection episode with its split, stream key, artifact, sidecar and end.
   - `_gate/model_inputs_train.npz` and `_gate/model_inputs_heldout.npz`, separate files: dense features, status
     indices and one-step targets exactly as training and the held-out checks consume them, each with episode id and
     tick.
   - `_gate/trials/<entry>.npz` (120 files): native rows and canonical words from tick 0 (the supplied prefix is
     words[:t]), bookkeeping histories, and every decision's candidate words, root row and history, and chosen index.
     P and S also record the scores, predicted reach ticks, and every member's predicted x, y, airborne flag and fall
     tick for every candidate. RC records no prediction because it evaluates no model.
   - `_gate/model_inputs_trials.npz`: the model inputs of every recorded trial transition, prefixes included.

   Cost: 0.08 ms per decision (0.03 % of a 316 ms decision). Size: about 1 GB at production scale (training inputs
   about 470 MB), written uncompressed for a predictable write time. The unit suite stays 17 / 17, and the e2e rerun
   reproduces every decision (§6). The pre-amendment files and the diff are kept in the source snapshot.
10. **Approval test repair (user-authorised, 2026-09-30).** `unit_approval_refusal` asserted that the repository's
    approval record did not exist, so preflight, which runs the unit suite, could never pass once the gate was
    approved. It now runs the unchanged production `approval_status()` against an isolated temporary record, and
    restores the module paths afterwards.
    - **Refused:** a missing record, a PENDING record, and an APPROVED record with an altered choice, tick budget,
      memory cap, rule digest or code hash.
    - **Never accepted:** an unreadable record (it raises).
    - **Accepted:** an APPROVED record with the current identity.
    - **Checks:** the repository's record is verified untouched. The suite passes 17 / 17 with the real record present.
      The test fails, as required, against four mutated checks: always accept, always refuse, never accept a valid
      record, and ignore code hashes.
    - **Nothing else changed:** no production check, configuration, model, control, rule or budget.

## 10. Remaining risks

- **No native execution of the M7u stack yet.** The real stack was assembled with the native class substituted, and the
  real v4 wrapper ran on recorded replies. The first native contact would be the gate's own P1, which stops the run
  (INVALID) on any mismatch.
- **Throughput assumptions.** The projections rest on recorded M7s throughputs (×0.8 safety) and fixed per-episode
  restart allowances, not on M7u measurements. The caps stop the run if these are wrong (INCOMPLETE, not a result).
- **Planning-time variance.** Real weights, and states far from the capture states used here, could change decode
  timings slightly. The evaluation cap has headroom (§8).
- **Vocabulary caps.** If random-segment data reaches more than 159 statuses, 128 floor / contact combinations or 64
  hitlag / flag combinations, training raises: INVALID, nothing merged silently. Captures reach 49 / 14 / 17.
- **One-step training only.** Compounding error over 64 ticks is the main scientific risk. It is read as MODEL
  attribution in a null.
- **Omitted state** (§3) and the conditional coverage of the proposal's §3 table.
- **Goal availability.** If fewer than 30 rising airborne candidates exist in the 12 held-out episodes, the run is
  INCOMPLETE. This was not measurable before collection.
- **Synthetic-only driver glue.** The e2e run used a synthetic world. The real run can still differ in lifecycle
  details (standby promotion timing, a cold fallback), which the M7 infrastructure handles, but which are untested with
  the M7u wrappers.

## 11. Proposed gate configuration (for review; not authorised)

Everything below is what `python rl/m7u_gate.py approval-template` would print for a reviewer. The file
`docs/rl_model_planning_m7u_gate_approval.json` was **not** created during preparation.

**Status 2026-09-30:** authorised once by the user, unchanged, with the evidence recording of §9 item 9. The approval
record freezes the code identity of the amended files.

| item | value |
| --- | --- |
| gate / scope | `m7u1`: local control after the agent's own supplied recorded prefix |
| identity | executable `30a3913b…` (the M7q v4 build, unchanged); environment profile `rl/configs/m7q/m7q_pilot_s0.toml` `121e1d48…` (read-only); state contract `7c291133…`; planner `e1f9bc8f…`; rule `m7u1_control_rule_v2` `ae372b19…`; pinned world `ca1ac287…`; bench record `65bd6a0a…`; track check `9a25a66d…`; code hashes as `identity()` prints them |
| seed | 0 (Python-side only; the native RNG is never inspected) |
| data | 92 RC behaviour episodes from normal tick-0 starts; 80 train, 12 held out (sha256 split) |
| goals | 40 rising airborne points: h = 64, Δy ≥ 300, pooled q ≤ 0.02 (fill by lowest q, recorded); start t ∈ [60, 600]; ≤ 4 per held-out episode, ≥ 32 ticks apart; frozen before training; π(k) = (k + 20) mod 40 |
| trial | fresh process → the held-out episode's own words 0 … t−1 (recorded) → start identity on every stored field → ≤ 96 controlled ticks → the first valid reach of g (±150, airborne, live, not the fatal-fall tick) ends it |
| arms | P (trained ensemble, commanded g); RC (candidate 0, no model); S (trained ensemble, commanded π(g), scored on g); shared stream per goal |
| model | E = 3. Trunk 370 → 256 → 256, heads H1-H7 (§4 of the proposal, §2 here). Vocabulary caps 160 / 128 / 64. Adam 3e-4, batch 1,024 per member, **S = 6,000**, one-step teacher-forced loss, episode bootstrap |
| planner | **N = 64**, H = 64, execute 4 then replan, 15 mutants, 64 refill segments, 48 fresh plans; cost: Chebyshev / 150 + 1 · grounded + 0.1 · τ / 64, fall 10; score mean + 1.0 · std |
| rule | PASS: n_P ≥ 10, b_R − c_R ≥ 8 and b_S − c_S ≥ 6. NULL: b_R − c_R ≤ 2 or b_S − c_S ≤ 0. Otherwise INCONCLUSIVE. Plus INVALID / INCOMPLETE. Readings of a NULL use the MODEL share (all and unflagged) and the witness share |
| native ticks | ≤ 431,201 (itemised in §5) |
| wall | 60 min from launch, per-phase caps as in §5; projected 28.4 min |
| memory | ≤ 3,072 MB private in the main process; the benchmark peaked at 833 MB |
| preflight before any launch | 17 / 17 unit cases; rule self-test; the benchmark `fits`; the track check `ok`; D: coverage over the base and every runs/ increment; no BattleShip process; executable present; `runs/m7u/gate` absent; an APPROVED record matching `identity()` |
| after the run | a new verified D: increment for `runs/m7u` (outside the cap), as for every earlier gate |

**What a PASS would establish, and what it would not** (unchanged from the proposal, §8). On one seed, learned one-step
predictions searched by a fixed planner reached rare rising airborne points 64 ticks away from own-prefix native states.
They did so more often than the same machinery choosing without predictions and than the same planner commanded
elsewhere, with exact replays. That is **not** a landing, a crossing, a reach from tick 0, or a replicated result.

**Decision requested:** approve, amend or decline gate `m7u1` as configured above. The preparation step authorises
nothing further.
