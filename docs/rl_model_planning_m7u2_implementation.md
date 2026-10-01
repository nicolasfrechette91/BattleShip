# M7u2 preparation: implementation record (2026-09-30)

**Amendment 1 (2026-09-30, user-authorised, before any native tick).** Goal selection now only prevents *exact
duplicate* goal definitions and allows, records and describes overlapping boxes as correlated; it no longer refuses
overlap. See `docs/rl_model_planning_m7u2_amendment_2026-09-30.md`. This record is updated accordingly (§1, §3, §7-§11).
The previous text is preserved byte-identically as `docs/rl_model_planning_m7u2_implementation_preparation_r0.md`.

**Update (2026-10-01 UTC):** gate `m7u2` was authorised after amendment 1 and run once: **PASS** (P 7 / RC 0 / S 0 of
24). See `docs/rl_model_planning_m7u2_gate_results_2026-09-30.md`. The remainder of this record describes the preparation
and is kept as written.

**Status: zero-native-tick preparation only, as authorised.**
- **Implemented:** the isolated driver, goal selection, the rule, offline tests, accounting and the approval template.
- **Not done:** nothing launched BattleShip, collected the pool, replayed an episode, took an optimizer step, created
  an approval record or ran the gate. Nothing was committed or pushed.
- **Unchanged:** m7u1's PASS and its scope (local control after self-generated supplied prefixes, one seed), and every
  committed m7u1 file. A test checks that the m7u1 files equal HEAD.

**What m7u2 is.** A proposed test of rare airborne-point reach initiated from the normal tick-0 reset, with the frozen
m7u1 model on one seed. It claims no landing, crossing, target or clear. Design:
`docs/rl_model_planning_m7u2_tick0_proposal_2026-09-30.md`. The user accepted its 360 × 128-tick behaviour pool as the
goal source, on condition that none of those episodes trains the model, tunes the planner or alters a threshold.

## 0. State

| item | value |
| --- | --- |
| parent | `main` = `origin/main` = `1a68a7b`. New untracked files only (§1); no tracked file modified |
| submodules | `decomp e4f06348`, `libultraship 805f1950`, `torch 3aa9c97`; no native change |
| reused unchanged | `rl/m7u_{state,model,planner,goals,rule,analysis,worker,gate,tests}.py`. m7u2 imports their generic parts: ledger, clock, single-env replay, batch planning, decision records, transition saving, worker stack, synthetic stand-in |

## 1. Files (all new)

| file | role |
| --- | --- |
| `rl/m7u2_goals.py` | pool registration (c000..c359), eligibility, the fixed chance reference (`Reference`), deterministic selection that prevents exact duplicate definitions and records overlaps, rise-event census (reported only). NumPy only |
| `rl/m7u2_rule.py` | `m7u2_tick0_rule_v1`, null readings, wording check, self-test |
| `rl/m7u2_gate.py` | driver: frozen-model loading and pins, the optimizer guard, decision reproduction, launch readiness, identity and approval, preflight, the tick-0 drive loop, P1, pool, goals, evaluation, diagnostics, replays, rule |
| `rl/m7u2_tests.py` | 13 offline unit cases and the production-count offline e2e |
| `docs/rl_model_planning_m7u2_tick0_proposal_2026-09-30.md` | the accepted proposal (from the previous step) |
| this record | |

## 2. Pinned identity

Preflight and `load_frozen` refuse on any mismatch.

| pin | value |
| --- | --- |
| model file `runs/m7u/gate/_gate/model.pt` | sha256 `a4bd30e5…` |
| parameter digest | `0e70af78…` |
| vocabulary / members | 61 / 16 / 28; 3 |
| clock track, rebuilt from the 80 preserved m7u1 training sidecars | `16318edf…`; must cover input ticks 0..192 (128 controlled + 64 imagined) |
| planner / state contracts | `e1f9bc8f…` / `7c291133…` (m7u1, unchanged) |
| stage table | `ca1ac287…` |
| executable | `30a3913b…` |
| m7u1 records read | `state.json` `29f0d70f…`, `goals.json` `8e14e9f8…`, `collection.json` `46d17d50…` |
| tick-0 reset row (identical in all 92 m7u1 episodes) | `0bf8dbd7…` |
| chance reference (92 m7u1 episodes, input ticks 1..128) | `4337cc35…` |
| P1 artifacts | m7u1 `g26_P` (171 words, reach 171, digest `3b3bd402…`) and `g14_P` (183, reach 183, `33087dc8…`) |
| rule / goal contract | `m7u2_tick0_rule_v1` `ad809816…` / `m7u2_tick0_goal_v1` `78a6cd1d…` |

## 3. Goal source and selection (`rl/m7u2_goals.py`)

**Pool.** Exactly 360 behaviour episodes from the normal reset, named c000..c359 in advance and spread 72 per worker.
- **Behaviour:** candidate 0 of the fixed-draw stream `m7u2|0|collect|c###` (N = 64), the m7u1 behaviour.
- **Length:** at most 128 words, ended by the base environment's 128-step horizon, a Python-side truncation, or
  earlier by a fall.
- **Checks:**
  - every reset row equals the tick-0 record;
  - every word stream equals its offline regeneration;
  - every sidecar equals the streamed rows;
  - the entry set must be exactly c000..c359 (refused otherwise).
- **Use:** the pool is read only by goal selection and one reported accuracy diagnostic (forward passes). No code
  path trains, tunes or sets a threshold from it.

**Eligibility** (unchanged from the proposal):
- τ ∈ [32, 96];
- the row at τ is valid and airborne, and is not the fatal-fall tick;
- y_τ − y_spawn ≥ 300;
- at most 1 of the 92 reference episodes makes a valid airborne reach of the ±150 box within input ticks 1..128.

**Selection** (deterministic, from the pool and the reference only; `select_goals` has no outcome argument, and a test
pins its signature):
1. Episodes are taken in the order of sha256(`m7u2|goal|<entry>`).
2. Within an episode, its eligible τ are tried in the order of sha256(`m7u2|goal|<entry>|<τ>`).
3. **The first τ whose goal definition is not an exact duplicate of an already registered goal is registered.** The
   definition is the box centre (x, y), compared exactly. In practice that is the episode's sha-first τ. A passed-over τ
   is recorded with the goal it duplicated.
4. An episode whose every eligible τ duplicates a registered goal is skipped and recorded.
5. The first 24 registrations are the goals: one per episode, so no source episode and no goal definition appears twice.
6. **Overlapping boxes are allowed.** Overlapping pairs among the registered goals, each goal's overlap count and the
   correlated groups are recorded (`goals.json`, `state.json`, and `goal_overlap` in the decision). Overlapping goals are
   described as correlated trials, not independent evidence. Overlap never affects selection or a threshold.
7. Fewer than 24 is **INCOMPLETE**: no fill, no relaxation and no second pool.

π(k) = (k + 12) mod 24, an involutive derangement.

**Amendment 1 (user-requested, before any data).** The preparation's overlap-gated rule is replaced by the narrower
duplicate prevention above, which keeps the proposal's single sha-first τ per episode. Its availability table described
the removed rule and is withdrawn (amendment record §3). Supply is now essentially the number of pool episodes that have an
eligible point; a binomial approximation on the per-episode yield gives P(at least 24 of 360) of 0.78 at the 7.6 % lower
bound, 0.95 at 9 %, 0.99 at 10 % and 1.00 at the measured 13 % (12 / 92). These are estimates (independent episodes, yield
from the leave-one-out count, rare exact-duplicate skips ignored), not a guarantee.

## 4. Trials, controls and tick-0 semantics (`rl/m7u2_gate.py`)

**Entries.** Every evaluation entry is validated before anything launches:
- `t = 0`, an empty prefix, the tick-0 record as the start row, the 128-word budget;
- the scored goal is g itself.

Any other entry raises before the first reset (tested: a prefix length, a prefix, an archived start row, a longer
budget, another scored goal). No prefix or archived start can reach evaluation.

**Tick semantics.**
- The m7u1 probe checks the start state only when the step counter k equals t, which never happens for t = 0. So the
  m7u2 drive loop checks each reset row against the tick-0 record **before the first word**; a mismatch is INVALID with
  zero ticks consumed (tested).
- After every step, the record's k and the row's input_tick must equal the number of words submitted (consumed tick
  T → input tick T + 1). The first decision is at consumed tick 0.

**Controls**, the m7u1 machinery unchanged:
- **P:** commanded g.
- **RC:** candidate 0 at every decision; no model is evaluated; its words regenerate offline from the goal stream.
- **S:** P's rule commanded π(g). The worker probe scores and ends every arm on g only. A test drives words that pass
  through π(g)'s box: scored on a far g they end only at the budget; scored on π(g) they end at its first reach.
- **Streams:** `m7u2|0|goal|k`, shared by the three arms of a goal and distinct from every pool stream.
- **Planner:** N = 64, H = 64, execute 4 words then replan, 15 mutants, 64 refill segments, 48 fresh plans, the m7u1
  cost and score.

## 5. The frozen model

**Locked at load:**
- `load_frozen` checks the file, parameter digest, vocabulary, members, clock track and track coverage;
- it switches off every parameter's gradient and sets eval mode.

**Guarded during the run:**
- `cmd_run` runs the whole gate inside `no_optimizer()`: constructing any `torch.optim` optimizer raises an integrity
  stop (tested).
- The parameter digest is checked before evaluation, after evaluation and after analysis.
- A source scan in the tests rejects `um.train(`, `.backward(`, `um.losses(`, `optim.Adam`, `optim.SGD` and `.step()`
  in the driver.

**Reproduction.** Preflight re-scores 32 fixed recorded m7u1 decisions. The chosen candidate must be identical and
every score within 1e-3. Measured: 32 / 32, max |Δ| 3.5e-5 (from m7u1's batched planning).

## 6. Ledger, caps, readiness and replays

| phase | native ticks (cap) | wall cap |
| --- | ---: | ---: |
| P1: m7u1 `g26_P` + `g14_P` replayed from tick 0; words, every stored row field, reach tick and action digest equal | 354 | 120 s |
| pool, 360 × 128 | 46,080 | 600 s |
| goal selection | 0 | 120 s |
| evaluation, 24 × 3 × 128 (all controlled; no prefix) | 9,216 | 1,200 s |
| success replays (≤ 6 P + 2 RC + 2 S, first successes in registered order) × 128, plus analysis | 1,280 | 300 s |
| **total** | **56,930** | **2,400 s** |

- **Enforcement:** the ledger refuses any request before it would exceed a phase or the total.
- **Memory:** main-process private memory ≤ 3,072 MB.
- **Projection:** 1,357 s at the readiness ceiling (p95 0.5 s per decision), about 1,200 s at the measured 0.39 s.
  Every phase is inside its cap.
- **Readiness**, at the end of preflight (zero ticks; a refusal consumes nothing):
  - at least 4,096 MB available and 10,240 MB free commit;
  - a 40-decision timing probe from the tick-0 row with p95 ≤ 0.5 s.
- **Outcomes:** a cap or goal-availability stop is INCOMPLETE; an integrity failure is INVALID; there is no retry or
  extension.

## 7. Test results

`python rl/m7u2_tests.py unit` on the final code: **13 / 13 passed**. Approval is tested on isolated temporary
records, so the suite stays valid after a real approval exists.

| case | covers | result |
| --- | --- | --- |
| rule and scramble | rule self-test (boundaries, PASS / NULL disjointness over every count triple, partial lists INVALID, INCOMPLETE), thresholds, π(k) = (k + 12) mod 24 an involutive derangement | pass; rule `ad809816…` |
| goal selection rules | reference count = brute force; τ window, rise, airborne; exact duplicates prevented (c004's only τ skipped; c007's τ 40 passed over, τ 90 registered); overlapping non-duplicate goals both register (c005 / c008) and the pair, counts and correlated group are recorded and match a brute-force count; a point one unit away is not a duplicate; episode and τ sha order; one goal per episode; permutation-invariant; too few → INCOMPLETE with the skip record; missing / extra pool episode, 129 words, or reset row off the record → refused; signature has no outcome input; production constants | pass |
| goals on m7u1 data | the 92 tick-0 rows identical; tick-0 and reference digests equal their pins; leave-one-out yield reproduces the proposal (12 / 92) | pass |
| frozen-model integrity | pins; gradients off, eval mode; a tampered file and wrong parameter / track pins refused; no optimizer under the guard, guard removed after; forward passes leave the digest unchanged; 32 / 32 decisions reproduce (max \|Δ\| 3.5e-5); no training call in the driver | pass |
| readiness and tick-0 timing probe | slow planning, low memory, low commit and unknown memory refused; a ready machine accepted; the real probe from the tick-0 row runs | pass (probe 0.40 s) |
| tick-0 drive | 9 trials from the tick-0 reset: start row = record; input_tick = words; ≤ 128 words; RC = candidate 0 from consumed tick 0; first decision at tick 0; a reset row off the record stops with 0 ticks; prefix, archived start, longer budget or another scored goal refused before launch | pass |
| scrambled-goal scoring | S commanded π(g), sharing the goal stream with P; words through π(g)'s box end only at the budget when scored on g, and at the first reach when scored on π(g) | pass (box entered at tick 30) |
| pool and caps | production pool configuration exactly c000..c359, 72 per worker; ≤ 128 words, behaviour stream regenerated; pool cap one tick short stops first; wall cap; memory cap | pass |
| replay accounting | ≤ 6 / 2 / 2 first successes in registered order; budget 10 × 128; differing row, reach tick, digest or a short replay rejected | pass |
| gate stops | P1 mismatch → INVALID before the pool; too few goals → INCOMPLETE with exactly the pool consumed and no evaluation or replay ticks; pool wall cap → INCOMPLETE | pass |
| approval refusal and acceptance | missing, PENDING, altered tick budget / N / frozen-model digest / caps / rule / pool / code hash refused; unreadable raises; valid accepted; repository path untouched | pass |
| accounting | the ledger, P1 = 171 + 183, caps, replays, readiness, and the wall projection inside every phase cap | pass (projection 1,357 s) |
| import isolation | goal and rule modules import no torch or transport; every m7u1 file equals HEAD | pass |

`python rl/m7u2_tests.py e2e` (final code, 309 s) ran `run_gate` through every phase **at production counts** over the
synthetic stand-in, with the real frozen ensemble planning at N = 17. The world is synthetic, so the outcome (NULL)
says nothing about Mario.

| phase | result |
| --- | --- |
| P1 | 354 ticks |
| pool | exactly 360 episodes, 46,080 ticks |
| goals | 1,328 eligible points in 99 episodes; 0 duplicate passes, 0 skipped; 24 registered; 8 overlapping pairs in 6 correlated groups (synthetic) |
| evaluation | 72 trials, 9,165 ticks, all from the tick-0 record |
| replays | 1 exact replay, 77 ticks = the ledger |
| rule | applied once |

The frozen digest was unchanged throughout.

The e2e passes were rerun on the amended code (505 s). The pre-amendment preparation's first attempt, on m7u1's
1-D-ish stand-in, had stopped **INCOMPLETE** (only 9 non-overlapping goals), which was the then-registered behaviour. It
is the reason for the richer test-only world, which is kept.

## 8. Preflight (zero native ticks)

`python rl/m7u2_gate.py preflight` on the **amended final code** launched nothing and consumed zero native ticks (before
any approval record existed). It **refused for exactly one reason: no approval record.** Everything else passed:
- unit suite 13 / 13 and the rule self-test (`ad809816…`);
- frozen-model pins and decision reproduction 32 / 32;
- D: coverage of all 393,911 `runs/` files, 0 uncovered, over the base and 3 increments;
- no BattleShip process; executable pinned; `runs/m7u2` absent;
- readiness: 6,134 MB available, 14,909 MB free commit, timing probe median 0.321 s, p95 0.339 s.

## 9. Approval template (regenerated after the amendment)

`python rl/m7u2_gate.py approval-template` prints the following. Against the preparation's template (preserved in the r0
record) exactly four identity entries differ: `goal_contract_sha256` (`78a6cd1d…` to `691d9abd…`) and the code hashes of
`rl/m7u2_goals.py`, `rl/m7u2_gate.py` and `rl/m7u2_tests.py`. Every budget, cap, rule, pool, seed and model entry is
identical.

```json
{
 "gate": "m7u2",
 "scope": "proposed test of rare airborne-point reach initiated from the normal tick-0 reset (frozen m7u1 model, one seed); not a landing, crossing, target or clear",
 "rule": "m7u2_tick0_rule_v1",
 "rule_sha256": "ad809816dc22df4effd64a139f893d94038ae949aa507192151d377873f2d7c7",
 "goal_contract": "m7u2_tick0_goal_v1",
 "goal_contract_sha256": "691d9abd90ec27d14bffff2b0ebc4d42f604a13aa529fac1885982427caff829",
 "planner_sha256": "e1f9bc8fe4606a8eb2092da109b7ac00a356aaa15a2c5a734b2cd6413a44fa3b",
 "state_sha256": "7c29113386d327edef77ecbc9e00b984c3f4e3c1acf00c742daaa6f42e98e6b7",
 "frozen_model": {
  "model_sha256": "a4bd30e51d379e57c070b6728f494f8abf52814efade2ae67ac39186e082e6fd",
  "parameter_digest": "0e70af78f1bec21039fa65f6f35ed180d69b31a02dd482480b946aced1bc0156",
  "vocab": {
   "S": 61,
   "V3": 16,
   "V4": 28
  },
  "members": 3,
  "track_sha256": "16318edf0902749a267db9b89903f163df90df16713d441ef42b192aea6c6534"
 },
 "m7u1_sources": {
  "m7u1_state_sha256": "29f0d70f1043207ec64ae7049c61cdeb694f6ead5fd6ae18c390eebbb5bd91cd",
  "m7u1_goals_sha256": "8e14e9f8f6bcb4a3992d615f5ed5d1df70b3bcd4f195ce34f13d690211acc636",
  "m7u1_collection_sha256": "46d17d5092b5dbf7aa24563e9633228c8c97e863ee495c9bdc887a8e39c467e0",
  "reference_digest": "4337cc35beebb23e342c11a2490ae72ed57495b9eb856e0d4f9eb9bc81ab912b",
  "tick0_row_digest": "0bf8dbd7b03ab2e418a98c2cb9e20208f4fb1597023c12686a3d5921d5e67686"
 },
 "world_digest": "ca1ac287141d02c112eee70263c59b773af0054de690da68f0ee248dc91f72e4",
 "p1": {
  "g26_P": {
   "words": 171,
   "reach_tick": 171,
   "native_action_digest": "3b3bd40209cd8e0ed1a9415746d37bba5458cd1144aabad2a06c6b41bf518928"
  },
  "g14_P": {
   "words": 183,
   "reach_tick": 183,
   "native_action_digest": "33087dc8a6e98bb1f9b716c92736906871f46bf64f17d27cea64cb61ae4a0d30"
  }
 },
 "executable_sha256": "30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee",
 "code": {
  "rl/m7u2_goals.py": "da4c6041ab0c4cd30de9299d91860701e94cac8eb37f93891d5cd449e95f4e3f",
  "rl/m7u2_rule.py": "0243b7510a376e01f20bf853af54dcf69b8409349bbcd324acedb1df497f4f86",
  "rl/m7u2_gate.py": "621bf45df9537b4ac96e48842a592abf72553d0b97e1132ed535eee4d3517f07",
  "rl/m7u2_tests.py": "a8360765d1a4e753cce0a83566c6b6b26412786f797219259cc97e2a0a59714e",
  "rl/m7u_state.py": "99f76adad72257cf14f919519f6208ec90aaf92f2fc010d2bb1bd74b2066ff67",
  "rl/m7u_model.py": "e7fe97402a1ffe5477be168035b00c468c32f073690b73efc6eccc95202d0b11",
  "rl/m7u_planner.py": "43efee2ef275d271d410383182fb89a2cf61d572bc9d4446a17828b6413835bf",
  "rl/m7u_goals.py": "506e48df5a198440e4c1429964421f18fd355ef6bf676b6bd9249c58aa4de014",
  "rl/m7u_rule.py": "2ab8e269bbbbe7b3b21c5fe56499ca9657086f35a30ce2313d220c6425163002",
  "rl/m7u_analysis.py": "247375f6aa8a09e3b547f83965af8d90bff205dc8314e5d44914abc295106607",
  "rl/m7u_worker.py": "2302d27d439da9ee7cbf38c5b02c256ad70be33b3412e0397f97b66bba2e5b36",
  "rl/m7u_gate.py": "b3acb99607c14542d8217b1c19dad0e58715ca70d087f22e7073f8c37a3fd709",
  "rl/m7u_tests.py": "ad2a92e952d769226d74fe89b7594d601442fba4e973f8e78354c81294560455",
  "rl/btt_parallel.py": "e34187b3c19b6bf806cc8e31fd85018acb6a2e83ca3c93922c93887d52b64f75",
  "rl/battleship_env.py": "11397c73322f90f4505d675a2a878aef36835e8309a1eedf0e749fb24b85ae42",
  "rl/run_artifacts.py": "bcab944115d893bf6c447ad285d25f94a73111e2df1b273fdd5efbd1453cac5c",
  "rl/m7_vec_env.py": "f067a3fd6085b9d78f27dea0b72cbd76fe7b797f132a14e548515d9d76e62f86",
  "rl/m7_runtime.py": "3dc56722c924065356e6134174d5e2c4724c0f495ee8c4e0eed027dfd2d9c452",
  "rl/m7n_obs.py": "00f671ee0416134d696a8f080ab1a494a662a7e22f4a21f5f65f21c2906d135b",
  "rl/m7q_obs.py": "08188058f790bbf344c298542b5d2bee9b4e533dc54fe8eb9182f4df82e49b38",
  "rl/m7q_input.py": "9bd6fc098f7606675fbd398b142d0950f2dfd16949bdfadbf4f4d21d0578433a",
  "rl/m7g_spatial.py": "d95269b65648942594c2f9b598629c76dafb1fd839f08babc2621085f0e0b17c",
  "rl/m7n_entity.py": "21121f4656262c363802d33e7e6112883fe0976fb33aaf0f22c5371fab0d6d53",
  "rl/m7q_status_table.py": "c6ee3de5d8f75e3e61c264d2dfc1586093539e4bca67e5ee74dbf3a2806b6423",
  "rl/m7r_commit.py": "82d643997e3b589dbea89105419b0cfbfa134f811b7c63216f52fff762329588",
  "rl/experiment_config.py": "03ab722bfa89ac71fadd96dfa1e02f4c5b1dd15f59e3fdd2bb408c56bc34bf90",
  "rl/m7_trainer.py": "d0d889fd3729ac775c9c70a6823e4d7ff0e0666b0c6f0f4063b55f707cd08886",
  "rl/m7f_trace.py": "99399e16718a9e5a5f4d4eb3ce6c4b00bb62e6f9483522b03946b52180cb9190",
  "rl/btt_learning.py": "4f23ecd086639d6750f0e96e1fa085316cc0cff44dcc60bee913cf6c17b6a8b6",
  "rl/m7s_gate.py": "4bff49b4d3c7a882ae3c0bc13f4494ad45832adf07fede69e2517b7e81967859",
  "rl/tools/runs_backup.py": "c4de9b0ab69849341a129e9e99263a28d7fdfccb292e4cfebe8e6221039db71c",
  "rl/configs/m7q/m7q_pilot_s0.toml": "121e1d4877f365d71a673f2cdbec920c3fddf1fd83d529c6c752e9e716a49ade"
 },
 "n_candidates": 64,
 "gate_seed": 0,
 "pool": [
  360,
  128
 ],
 "n_goals": 24,
 "budget": 128,
 "tick_budget": {
  "p1": 354,
  "pool": 46080,
  "eval_control": 9216,
  "replays": 1280,
  "total": 56930
 },
 "wall_caps_s": {
  "p1": 120,
  "pool": 600,
  "goals": 120,
  "evaluation": 1200,
  "replays_analysis": 300
 },
 "global_cap_s": 2400,
 "memory_cap_mb": 3072,
 "readiness": {
  "min_available_mb": 4096,
  "min_commit_free_mb": 10240,
  "probe_decisions": 40,
  "probe_warmup": 5,
  "probe_p95_max_s": 0.5
 },
 "replays": {
  "P": 6,
  "RC": 2,
  "S": 2
 },
 "repro": {
  "decisions": 32,
  "tolerance": 0.001
 },
 "approval": "PENDING (a reviewer replaces this with APPROVED <name> <date>)"
}
```

## 10. Remaining risks

- **Goal availability is the main risk.** A binomial approximation puts the chance of at least 24 distinct eligible
  goals from 360 episodes at 1.00 at the measured yield, 0.99 at 10 %, 0.95 at 9 % and 0.78 at the 7.6 % lower bound (§3;
  an estimate only). A shortfall ends the run INCOMPLETE, by design, with the pool's ticks spent and nothing extended.
- **Native paths not yet exercised:**
  - the 128-step horizon on pool episodes;
  - t = 0 trial entries;
  - many short episodes per worker (72 restarts each).

  P1 replays m7u1 artifacts through the same stack but covers neither. The first native contact is the gate itself;
  any mismatch is INVALID.
- **Pool wall time** is dominated by restarts: projected about 300 s against a 600 s cap. In m7u1 the collection
  phase was the tightest (541 / 600 s).
- **Machine load.** Planning time is load-sensitive. The readiness probe refuses a slow machine before launch but
  cannot prevent later contention.
- **Model risk from rest.**
  - Open-loop drift from tick 0 is larger than mid-episode (proposal §2).
  - m7u1's free grounded starts reached only 2 / 9.
  - A NULL is a plausible outcome; its reading is reported, not decided.
- **Chance reference.** "≤ 1 of 92" is a coarse rarity estimate; the paired RC arm measures each goal's chance
  directly.
- **Synthetic e2e.** It uses a test-only world with a richer airtime. It exercises the glue at production counts; its
  outcome says nothing about Mario.
- **Correlated goals.** Overlapping boxes are allowed. If goals overlap, their trials are correlated, so the count of
  independent trials is smaller than 24. The overlaps are recorded and reported; the registered thresholds are unchanged.
- **Scope.** One seed and one frozen model. A PASS would not establish a landing, the wall top, a crossing, targets, a
  clear, speed, longer goals or replication.

## 11. Gate configuration (authorised by the user's message of 2026-09-30, once, after amendment 1)

| item | value |
| --- | --- |
| gate / scope | `m7u2`: rare airborne-point reach initiated from the normal tick-0 reset, frozen m7u1 model, one seed |
| model | m7u1 ensemble, frozen (§2, §5); no optimizer, no update |
| pool | exactly 360 behaviour episodes c000..c359, ≤ 128 words, from the normal reset |
| goals | 24, by the selection in §3; INCOMPLETE if fewer |
| trials | 24 × P / RC / S from the normal tick-0 reset, ≤ 128 words, success = first valid reach of g |
| planner | N = 64, H = 64, execute 4 then replan, m7u1 cost and score |
| rule | PASS: n_P ≥ 6 ∧ b_R − c_R ≥ 6 ∧ b_S − c_S ≥ 5. NULL: b_R − c_R ≤ 1 ∨ b_S − c_S ≤ 0. Otherwise INCONCLUSIVE. Plus INVALID / INCOMPLETE |
| budget | ≤ 56,930 native ticks (P1 354 + pool 46,080 + evaluation 9,216 + replays 1,280); 40 min total, per-phase caps in §6; 3 GB memory |
| after the run | a verified D: increment for `runs/m7u2`, as for every gate |

**Authorisation.** The user authorised one minimal amendment (amendment 1) followed by one bounded native run of exactly
this configuration (seed 0, the frozen m7u1 model, N = 64, 360 × 128 behaviour episodes, 24 deterministically selected
goals, evaluation from normal tick 0, 128-update horizon, zero optimizer steps, at most 56,930 native updates including
the 354-update identity check and at most 1,280 success-replay updates, 40 min, the phase caps and 3 GB). Fewer than 24
distinct eligible goals ends the run INCOMPLETE; an integrity failure is INVALID; there is no extra pool, relaxed
eligibility, retry, extension or post-approval repair. The approval record is `docs/rl_model_planning_m7u2_gate_approval.json`
and names the verified D: source snapshot. Nothing further is authorised: no commit, push, video, larger campaign or
automatic follow-up.
