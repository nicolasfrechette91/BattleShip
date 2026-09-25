# RL M7j: route-aware reward `btt_reward_v3` — offline check, frozen contract, opt-in implementation

Status (2026-09-25): **offline check done; contract frozen and registered; implemented opt-in; tests pass; Stage 0
integration pilot run; no learning run.** Nothing is committed, pushed or branched. `btt_reward_v2` is unchanged and
remains the reward of every existing profile. The M7i anchor pilot
([proposal](rl_consolidation_m7i_proposal.md)) is **paused**, not rejected; nothing here combines v3 with it.

Machine-readable registration: [`rl_reward_v3_m7j.json`](rl_reward_v3_m7j.json).

## 0. Summary

- **The candidate ranks outcomes the way the route needs**, and it has no farming, ordering or multi-target loophole
  (section 3.4). Under v2, a premature crossing that strands Mario with all three left targets (5.4) beats a clean
  right sweep (3.4). Under v3 the sweep wins (≥ 6.4) and the premature crossing scores exactly as under v2.
- **One deliberate property changes.** After a *qualified* landing on the left floor, falling off before tick 2,600
  scores higher than idling to the horizon. The M7b rule "a fall never outscores surviving" still holds everywhere
  else. This is kept as registered, because it makes attempts at the last left target cheap. A real game trajectory
  shows it (section 3.4).
- **No trajectory has ever combined a sweep with a crossing or a landing.**
  - Right sweeps by a policy: **3 ever**. Two came from tick 0 (M7a pilot training, at tick 2,348, then a fall;
    M7h F s2 evaluation, at tick 3,570) and one from an M7h archive-prefix start (tick 3,237).
  - A *qualified* landing has never happened in any trajectory, not even the TAS. Only constructed test trajectories
    exercise it.
- **The sweep bonus is not encountered often enough to guide learning from tick 0.**
  - 0 sweeps in 10,596 tick-0 v2 training episodes, and 1 in 8,965 tick-0 evaluation episodes.
  - 0 early sweeps (by tick 2,699) in any evaluation episode.
  - Target 2 is the bottleneck: it is missing in 127 of the 140 six-of-seven-right evaluation episodes.
- **Exact consequence: v3 ≡ v2 until the first sweep.**
  - Every v3 term is gated by the sweep, so a v3 run and a v2 run with the same seed are bit-identical until one
    happens.
  - For seeds 0–2 with the Phase K settings the v3 outcome is already known: it *is* the historical v2 control,
    whose training never broke more than 6 targets in an episode.
  - Stage 0 confirmed this at 102,400 transitions (section 6.1).
- **Recommendation.** Do not spend a v2-vs-v3 learning campaign from tick 0 now; it is predicted identical. Register
  v3 (done). The next learning experiment is the **staged right-side timing experiment** (section 7), which must
  first raise the early-sweep rate.

## 1. Verified starting point

| Item | Value |
| --- | --- |
| Parent `main` | `15f7850` = `origin/main` (M7h committed and pushed) |
| Submodules | decomp `3c7fd5d0` (`rl-main`), libultraship `805f1950` (`m6/raphnet-bypass`), torch `3aa9c97` — unchanged |
| Executable | `build-us/Release/BattleShip.exe` sha256 `1e7c62a0…` (no rebuild, no native change) |
| Uncommitted before M7j | `docs/rl_consolidation_m7i_proposal.md` (M7i rev 2), `docs/rl_frontier_curriculum_m7h_results.{md,json}`, `docs/rl_frontier_curriculum_m7h_analysis_n3.json` — untouched here |
| M7h decision | gate 4 `discovered_not_consolidated` (record `73e13aa2…`); 0 crossings / clears in 2,955 tick-0 evaluation episodes; obs v1 stays selected |
| Reward code before M7j | `rl/btt_rewards.py` (v1, v2), `btt_parallel.M7RewardWrapper` |

## 2. The frozen contract `btt_reward_v3`

Identity: `btt_reward_v3`, rule `btt_route_rule_v3`. The canonical JSON is `btt_rewards.REWARD_V3.to_json()`, whose
sorted, compact form has sha256 `d9447d471b95dd59533dfd87192e8eff5e059a6fd42c8bc380e3e27ee6037196`.
The contract is opt-in: only a profile with `contracts.reward = "btt_reward_v3"` uses it.

**Per step, in this order** (`rl/btt_reward_v3.py`):

1. **v2 base terms, unchanged.**
   - +1.0 per newly broken target (the `targets_remaining` count);
   - −0.001 per consumed native tick;
   - +10.0 once on the native clear.
   - The count must equal the bits that turned off in the diagnostic's `remaining_mask`, and no bit may turn back
     on. Native state is authoritative; a disagreement raises an error and is never repaired.
2. **Right sweep (one-time).** On the first step whose reply shows all seven right targets {0, 2, 3, 4, 5, 7, 9}
   broken:

   ```
   sweep_term = 3.0 + 2.0 * (3600 - n) / 3600,    n = consumed_tick + 1
   ```

   - `consumed_tick` counts from 0 at the tick-0 reset, so n = ticks consumed through that step (1..3,600).
   - The timing part is 2 × 3,599 / 3,600 for a sweep on the first tick, and exactly 0 on the step that consumes
     tick 3,599 (the horizon's last step).
   - n outside 1..3,600 is an error.
   - Several targets on one tick pay +1 each and the sweep once.
3. **Region events** (live steps only: `fighter_valid == 1` and `btt_active == 1`). The geometry is the native
   collision data; tests compare it with the pinned line table.
   - **Entry:** consecutive live steps (P, E) with x_P ≥ −2,100 > x_E. The tick-0 reset observation is the first
     predecessor. y_c is y interpolated at x = −2,100. Classes:
     - `over_wall` if y_c ≥ 2,999 (the ledge top, 3,000, minus 1);
     - `under_stage` if y_c ≤ −2,849 (the underside, −2,850, plus 1);
     - `through_face` otherwise (physically impossible; counted as an anomaly, never rewarded);
     - `unpaired` for a first live left step without a live predecessor (never rewarded).
   - **Qualified entry:** `over_wall`, *and* the sweep is complete in that entry step's reply. A premature crossing is
     never qualified.
   - **Exit:** x_P < −2,100 ≤ x_E. It ends the left visit's qualification.
   - **Landing:** a live grounded step (`ground_air_state == 0`) on line 3, the only left-side floor:
     |y + 1,950| ≤ 1 and −3,901 ≤ x ≤ −2,699.
   - **crossing_term = +2.0** on the first landing inside a qualified left visit, once per episode. Nothing is paid for
     a second landing, a repeated crossing, another surface, a landing after an unqualified entry, or a landing on the
     native-failure step itself.
4. **Failure term** (only on the `btt_native_failure_v1` step):
   - **−1.0** if a qualified landing happened on an *earlier* step;
   - otherwise **−5.0** (v2).
   - Clears, horizon truncations, interruptions, startup, transport and lifecycle failures, and administrative
     endings never reach this term, exactly as in v2.

`total = ((v2 base total + failure_term) + sweep_term) + crossing_term`. A step without a route term is therefore
bit-identical to its v2 reward.

**Scope rules (strict configuration).**
- v3 needs `contracts.observation = btt_policy_obs_v1`, a horizon of 3,600 and no `[curriculum]` table.
- It adds `SSB64_RL_TARGET_DIAG=1` to the derived native flags. The target identity is read diagnostically by the
  reward only and never enters the policy observation.
- Altered values, other ids and resumes across contracts are refused.
- Native RNG state is never read.

## 3. Offline check (no gameplay changed)

Evidence lives in `runs/m7j/offline/final/` (git-ignored): `census.json`, `ranking.json` and `replay.json`, produced by
`python rl/m7j_offline.py all`. The first attempt, `final_try1`, is kept; it differs only in an exactness flag for the
TAS.

### 3.1 Census of every recorded episode

**Tick-0 evaluation: 8,965 episodes.** These are Phase K (6 runs × 985) plus its random baseline (100), and M7h F
(3 × 985). Every record carries target identity and the first left entry.
- 0 left entries, so no landing is possible and the failure term is v2's.
- v3 − v2 is exactly the sweep term.
- **1 sweep:** M7h F s2 final stochastic `9a130d1f`, completed by target 2 on consumed tick 3,570, horizon.
  v2 3.400 → v3 6.416.
- 8,964 episodes are unchanged (v3 = v2).
- Early sweeps (by tick 2,699): 0.
- Target 2 broken: 69.
- Six static right targets done: 129 (75 of them by tick 2,700).
- Of the 140 six-of-seven-right episodes, 127 lack target 2.

**Training rows: 14,388.** A trajectory with fewer than seven targets cannot sweep, so its v3 reward equals its v2
reward on every step.

| Source | Rows | Tick-0 rows | Max targets | Rows with ≥ 7 targets (with prefix) |
| --- | --- | --- | --- | --- |
| M7a pilot (v1) | 371 | 371 | 7 | 1 |
| M7d (v1 1,539 / v2 881) | 2,420 | 2,420 | 6 | 0 |
| M7e (v2) | 2,604 | 2,604 | 6 | 0 |
| Phase K (v2) | 5,231 | 5,231 | 6 | 0 |
| M7h F (v2, curriculum) | 3,762 | 1,880 | 7 | 4 |

- Tick-0 v2 training episodes: 881 + 2,604 + 5,231 + 1,880 = **10,596**, with **0 sweeps**.
- All five rows with ≥ 7 targets were replayed (section 3.2).
- **M7i feasibility review episodes (558):** none broke target 2, so v3 = v2 on all of them.

### 3.2 Replay set (pre-declared; 18 episodes; all exact)

Each episode was replayed from tick 0 in a fresh process with the diagnostic on. All 18 reproduced their recorded
native action digest and consumed ticks. The TAS equals M7f's recorded trace and stops at the clear on row 447 of 468.
v2 and v3 were computed on the same replies.

| Episode | Why | End | v2 | v3 | v3 events |
| --- | --- | --- | --- | --- | --- |
| TAS | the 7.43 s route | clear | 19.553 | **24.354** | sweep at 358 (target 0, fireball); over-wall entry at 359, qualified; **no landing** |
| M7h F s2 final `9a130d1f` | late seven-right (tick 0) | horizon | 3.400 | **6.416** | sweep at 3,570 |
| M7a pilot `50bbb545` | only tick-0 training sweep | fall | −1.005 | **2.690** | sweep at 2,348, then a standard −5 fall |
| M7h s2 `9052fc6d` | prefix start, 7 targets | horizon | 3.400 | **6.601** | sweep at 3,237 (full trajectory; the training return was rebased) |
| M7h s1 `83112a8c` | the verified crossing and landing | fall | −2.221 | −2.221 | over-wall entry at 2,816 (y_c 4,114), **premature** (target 2 alive); line-3 landing at 3,004, unqualified; −5 |
| M7h s1 `438d5fcb` | crossing, airborne only | fall | −4.534 | −4.534 | over-wall, premature |
| M7h s2 `56a1af09` | off-stage entry | fall | −2.171 | −2.171 | `under_stage` (y_c −8,401) |
| M7h s1 `79be8064` / `d9c5249d` / `67d3898c` | reproduced left starts + left target | fall | −1.222 / −1.145 / −1.143 | same | entry in the prefix, premature; 7 targets include a left one, so no sweep |
| M7h F s0/s1/s2 final deterministic (3), first stochastic (3), first fall (2) | ordinary partial runs | 6 horizon / 2 fall | as recorded | same | none (v2 return = recorded evaluation return) |

### 3.3 Which event combinations have been observed together

| Combination | In a policy trajectory | Elsewhere |
| --- | --- | --- |
| Right sweep | 3 (above) | TAS |
| Early sweep (by tick 2,699) | 1 (M7a pilot, v1-era training; fell 656 ticks later) | TAS |
| Sweep + any left entry | **never** | TAS only |
| Qualified (post-sweep) over-wall entry | **never** | TAS only |
| Qualified landing on line 3 (+2) | **never** | **never**, not even the TAS; constructed tests only |
| Post-landing fall (−1) | **never** | constructed tests only |
| Premature over-wall entry + line-3 landing | 1 (`83112a8c`) | both user fixtures (validation only) |
| Over-wall entry + left target | 3 (entry inside a reproduced prefix) | TAS, lower fixture |
| Under-stage entry | 1 (`56a1af09`) | — |
| Sweep + left target, or a clear | **never** | TAS |

Every v3-specific behaviour past the sweep is therefore supported only by synthetic unit cases and by the
constructed game test trajectories. They must not be read as observed policy behaviour.

### 3.4 Ranking and loopholes

Closed forms (`ranking.json`; "never observed" rows are hypothetical by construction):

| Outcome | v2 | v3 | Kind |
| --- | --- | --- | --- |
| stay right, 6 right targets, survive | 2.400 | 2.400 | observed class |
| sweep at ~1,500, survive right | 3.400 | 7.567 | never observed |
| sweep at 3,570, survive | 3.400 | 6.416 | observed once |
| premature crossing (6 right) + landing + fall (`83112a8c`) | −2.221 | −2.221 | observed |
| premature crossing, 6 right + 3 left, survive (stranded) | **5.400** | 5.400 | never observed |
| sweep at ~1,500, crossing, fall **before** landing at 1,800 | 0.200 | 4.367 | never observed |
| sweep at ~1,500, crossing, landing, fall at 1,900 | 0.100 | 10.267 | never observed |
| sweep at ~1,500, crossing, landing, survive | 3.400 | 9.567 | never observed |
| sweep at ~1,500, crossing, landing, clear at 2,400 | 17.600 | 23.767 | never observed |

**Inequalities** (checked over the whole tick range in `ranking.json` and in `m7j_tests u_ranking`):
- (a) A sweep followed by survival on the right beats any stranded premature crossing: min 6.4 > 5.4. Under v2 it is
  the reverse (3.4 < 5.4).
- (b) After a sweep, crossing + landing + a later fall beats staying right.
- (c) After a sweep, crossing and falling *without* a landing is worse than staying right. Reckless crossing is not
  rewarded.
- (d) A premature crossing scores exactly as under v2.
- (e) Without a qualified landing, no fall outscores surviving with the same targets.
- (f) The sweep's value decreases strictly with its tick, by at most 2.0.

**Loophole cases** (synthetic, `m7j_offline.loophole_cases`, all pass):
- a sweep re-reported on later steps pays once;
- the last right target and a left target on one tick pay one sweep and +1 each;
- repeated landings pay once;
- if the sweep completes while Mario is already left after a premature entry, there is no landing bonus and the fall
  is −5;
- an under-stage entry followed by a line-3 landing pays no bonus;
- the ledge top and the moving platform are not a landing;
- a landing on the failure step does not count;
- a sweep on the entry step qualifies;
- the landing latch survives an exit.

**The one registered property change: post-landing falls.** After a qualified landing, a fall on any step before
tick 2,600 scores more than idling to the horizon (0.001 · t + 1 < 3.6). Both outcomes have the same targets and
neither clears.
- A game-backed constructed trajectory shows it: TAS prefix of 410 rows, then stick right. It sweeps at 358, enters
  at 359 (qualified), lands at 444 (+2) and falls at 661 (−1): v3 **14.139** (v2 3.338). The same landing followed by
  idling to the horizon gives **12.201**.
- It is kept because −1 makes attempts at the last left target (target 1 lies below line 3, so the attempt must leave
  the floor) cheap. A reward that preferred idling would discourage the only action that can clear.

### 3.5 Classifier validation on the user fixtures (validation evidence only)

A one-off, read-only check outside `rl/` fed the recorded positions of the two fixtures through the classifier, with
target masks left full. It lives in `runs/m7j/offline/fixture_check/`, sha256 `41914a63…`.
- **Upper fixture:** the ledge step-off gives y_c = **3,000.0** exactly, classified `over_wall`. This is the boundary
  the 1-unit tolerance is for.
- **Lower fixture:** y_c = 4,356.65.
- Both land on line 3 (at 666 and 1,292), and both are unqualified (no sweep).
- The fixtures are never read by the repository tests or code, following the M7g-a isolation rule. They are not
  demonstrations, starts, prefixes, training data or route instructions.

### 3.6 Is the sweep bonus encountered often enough to help? No.

- **Rate.** At the historical tick-0 v2 rate (0 / 10,596; one-sided 95 % upper bound ≈ 2.8 × 10⁻⁴ per episode) and
  about 870 finished episodes per 3,072,000-transition Phase K run, a run expects at most about 0.25 sweeps.
- **Budget to learn from it.** Seeing just 20 sweeps per seed would take about 70,000 episodes. That is roughly
  250 M transitions, or about 45 h per seed at the measured 1,540 transitions/s.
- **Better warm starts do not fix it.** The best existing checkpoint (M7h F s2 final) swept in 1 of 100 evaluation
  episodes, at tick 3,570. The best early-static-six checkpoint (M7h F s0 final: 20 of 100 by tick 2,700) never
  broke target 2.
- **Conclusion.** The crossing bonus cannot guide current policies, and the sweep bonus cannot either. The problem is
  frequency, not magnitude: a bigger sweep bonus would be encountered just as rarely.

### 3.7 Decision on the numbers

**Frozen unchanged:** +3, 0–2 timing, +2, −1 and −5.

- Nothing observed contradicts their ranking properties.
- No crossing or landing combination has ever occurred, so no offline evidence could justify other values.
- Any later change needs a new contract id, registered before training.

## 4. Implementation (opt-in; v2 default of every profile)

**New files:**

| File | Content |
| --- | --- |
| `rl/btt_reward_v3.py` | pure v3 arithmetic: `RouteRewardState`, the entry and landing classifiers, the timing, closed forms, offline rescoring, self-test |
| `rl/m7j_reward_env.py` | `M7RouteRewardWrapper`: the worker wrapper (raw-reply shadow and one non-consuming `observe` per reset; requires the diagnostic flag and a 3,600-tick horizon; refuses a prefix rebase) |
| `rl/m7j_offline.py` | census, replay set, ranking and loopholes |
| `rl/m7j_tests.py` | 9 unit + 9 game cases |
| `rl/m7j_run.py` | Stage 0 `gate` / `pilot` / `verify-pilot` |
| `rl/configs/m7j/m7j_v3_pilot_s0.toml` | the Stage 0 profile: Phase K `m7g_s0_v1` + `reward = "btt_reward_v3"`, 102,400 transitions |

**Inherited edits** (161 insertions, 18 deletions):
- `btt_rewards.py`:
  - `RouteRewardContract` and `REWARD_V3`;
  - `reward_extra_env`;
  - the route block is enforced on read;
  - the v1/v2 arithmetic refuses a route contract.
- `experiment_config.py`: accepts v3; derived diagnostic flag; the v3 scope rules.
- `btt_parallel.py`:
  - `make_reward_wrapper` dispatch;
  - `M7RewardWrapper` refuses v3;
  - the `reward_v3` record is added to episode rows and artifact labels (v3 only).
- `m7_evaluation.py`: v3 evaluations boot with the diagnostic flag and record it.
- `m7g_k_tests.py`: `m7j/` joins the later-milestone profile exclusion.
- `m7g_k_campaign_tests.py`: the "no training profile sets the diagnostic flag" invariant now exempts v3 profiles
  only. The reward reads the flag; the recorder is still never built in training.

Unchanged:
- native code, decomp, submodules and the executable;
- Track 1, obs v1, stepping, reset, horizon and canonical actions;
- the v1 and v2 JSON;
- every historical profile fingerprint (tested).

## 5. Verification (commands and outcomes, 2026-09-25)

**Housekeeping:**
- `git diff --check`: clean.
- All new and edited files use LF with no trailing whitespace.

**M7j tests** (`python rl/m7j_tests.py all`): **18 / 18** on the final code (`runs/m7j/_tests_20260925T135639Z`):
9 unit and 9 game cases. The game cases cover:
  - TAS v3 (diagnostic on) vs v2 (off): identical observations including `host_frame`; the rewards differ on step
    358 only; 24.35356;
  - both constructed trajectories: the +2 once, the −1 fall, and the differing steps exactly {358, 444, 661};
  - a worker-path fall (−5.432, `reward_v3` in the row and the label);
  - a horizon run (−3.6);
  - `83112a8c` through a v3 worker: digest equal, −2.221, premature;
  - wiring refusals;
  - a PPO smoke (N = 2, 15,360 transitions, final evaluation with the diagnostic);
  - resume v3 → v3 allowed, v3 → v2 refused.
- **Transient failure:** the first `game` run was 8 / 9. `g_ppo_smoke_v3` reported `leak_free: false` because two
  non-BattleShip processes were still in the test job object at the trainer's end check. It passed alone and in
  three later full runs. A per-case probe with a 2 s delay found no lingering process after any case. The root cause
  is not proven; the likely cause is a timing race in the end-of-run job check.

**Inherited regressions:**

| Suite | Result |
| --- | --- |
| `m7b_config_tests` | 16 / 16 |
| `m7b_smoke` (v1/v2 TAS, fall, truncation, config parity, v2 PPO smoke, resume) | **7 / 7** |
| `m7_smoke unit` | 8 / 8 |
| `m7c_standby_tests unit` | 4 / 4 |
| `m7g_obs_tests unit` | 8 / 8 |
| `m7g_k_tests unit` | 6 / 6 (5 / 6 before the exclusion edit) |
| `m7g_k_campaign_tests unit` | 13 / 13 (11 / 13 before the two edits above) |
| `m7h_tests` | 13 / 13 |
| `m7h_campaign_tests unit` | 15 / 15 |
| `m7g_tests unit` | **8 / 9** |

**The `m7g_tests` failure predates M7j.** Its `unit_training_isolation` fails on `m7h_campaign_tests.py`,
`m7h_matrix.py` and `m7h_tests.py`. Their forbidden-input guard strings (for example `"fixtures/m7g"`) match the M7g-a
pattern. The same three files match at `HEAD 15f7850`. No M7j file matches.

**Stage 0:** see section 6.1.

## 6. Registered controlled experiment

### 6.1 Stage 0 — integration pilot (the smallest training that verifies integration)

**Setup:**
- `python rl/m7j_run.py pilot` runs the launch gate, then `train_m7.py` on `m7j_v3_pilot_s0.toml`, then
  `verify-pilot`.
- 102,400 transitions (20 rollouts), seed 0, N = 5 with standby, tick-0.
- **Registered expectation:** no sweep can occur, so the final set equals Phase K `m7g_s0_v1` `ckpt_000102400` and
  M7e s0 `ckpt_000102400`. The rows equal the twin's on the M7h R1 keys and in return.

**Result: PASS** (`runs/m7j/_pilot/verification_20260925T135513Z.json`; launch gate passed at 16.4 GiB commit,
5.0 GiB physical).
- **P1:** the final policy / `obs_rms` digests are `5cec5fc4…` / `050acde9…`, equal to Phase K `m7g_s0_v1` and M7e s0
  at 102,400. v3 training is bit-identical to the v2 control.
- **P2:** 30 of 30 rows are equal on the keys and returns. All 30 carry a `reward_v3` record with no sweep, no
  qualified landing and zero route terms.
- **P3:** the run completed leak-free on exe `1e7c62a0` and recorded v3 with its route block and the diagnostic flag.
  Its compatibility view differs from the twin's only in the reward and the flags.
- **Throughput:** 1,077 transitions/s end to end, against 1,070–1,097 for the three v2 R1 runs of the same size. The
  diagnostic and the extra `observe` cost nothing measurable.
- **Verifier fix.** The first verification record (`verification_20260925T135419Z.json`, kept) refused P2 with 30 vs
  31 rows. That was a verifier defect: it filtered the twin by `sb3_num_timesteps_at_end`, which admits an episode
  finished in rollout 21. It now uses the M7h R1 rule (`sb3_num_timesteps_seen ≤ 102,400`, the registered 30 rows).
  The run was not repeated or changed.

### 6.2 The v2-vs-v3 comparison (registered protocol; **not recommended to launch now**)

**Design:**
- **Arms:** v2 (Phase K v1 body) and v3 (the same body, reward v3). Everything else is identical: obs v1, Track 1,
  tick-0 starts, M7e/Phase K PPO, N = 5 with standby, 3,072,000 transitions, and the Phase K tick-0 evaluation
  protocol with evaluation metrics.
- **Seeds 3, 4 and 5.** Seeds 0–2 are already decided (v3 = the historical control, section 0).
- **Twin rule:**
  - Train v3 first.
  - If a v3 run records no sweep during training, its v2 twin is identical by construction. It is verified only by a
    102,400-transition digest check (as Stage 0), not re-trained.
  - Otherwise the v2 twin is trained in full.
- **Primary endpoints:**
  - sweep events during training;
  - tick-0 final stochastic early-sweep rate E (sweep by tick 2,699);
  - sweep rate S.
- **Secondary endpoints:** target-2 rate, static-six completion tick, T, falls. Crossings, landings and clears are
  reported.
- **Pre-registered prediction:** no sweep in any v3 run, so each pair is identical and the outcome is
  **"not encountered"**. This routes to section 7.
- **Cost:**
  - about 33 min of training plus about 36 min of evaluation per v3 run, so about 3.5 h for three seeds;
  - plus about 3 min per twin check;
  - about 7 h if every twin must be trained.

**Budget needed to test learning of v3 from tick 0:** infeasible at current competence (section 3.6). About 250 M
transitions per seed would be needed just to see 20 sweeps.

## 7. Proposed next learning experiment: staged right-side timing

The route needs, in order:
1. all seven right targets early;
2. an over-wall crossing;
3. a left-floor landing;
4. the three left targets.

Stage 1 is not being learned: 0 early sweeps in 8,965 evaluation episodes, with target 2 the bottleneck. The proposal
stages the problem instead of waiting for the crossing reward to be discovered. It is not implemented or registered
as a contract here.

**Stage R1 — right-side timing (reward only; tick-0; nothing else changes).**
- **Contract:** a new id, `btt_reward_v3_rt` (name provisional), equal to v3 plus a dense, one-time timing credit
  on each right target's first break:

  ```
  +c * (3600 - n) / 3600    per right target,    c = 2/7
  ```

  so the seven credits sum to at most 2.0.
- **Why it can work where v3 cannot:** every episode breaks 3–6 right targets, so the arm diverges from v2 at once
  and PPO sees a timing gradient in every rollout. Under v2 the per-tick cost cannot reward speed in horizon-length
  episodes; only γ discounting does.
- **Why the staging needs no contract switch:** v3's crossing, landing and fall terms stay active. If early sweeps
  appear, the crossing stage needs no contract switch.
- **Comparison:** v3_rt vs the historical Phase K v1 control (v2 on seeds 0–2, reusable after a Stage-0-style
  identity check). At this competence v3 ≡ v2, so the control also stands for v3.
- **Gate to stage R2:** early sweeps in at least 5 of 100 final stochastic tick-0 episodes in at least 2 of 3 seeds.
- **Before any launch:** an offline check (the same census and replays, and loopholes of the per-target credit) and
  its own registration.
- **Cost:** about 3.5 h (three new runs plus evaluation).

**Stage R2 — crossing (only after the R1 gate).** Continue the same contract. The endpoints become:
- qualified crossings;
- qualified landings;
- left targets;
- clears (all verified natively by replay from tick 0).

**Known risk.** Timing credit may speed up the six static targets without producing target 2, which the static-six
data suggests is the harder half. R1's secondary endpoint (the target-2 rate) detects this. A target-2-specific
mechanism would then need the user's decision.

## 8. Open decisions for the user

1. Accept the frozen `btt_reward_v3`, including the post-landing −1 property.
2. Whether to run section 6.2 anyway, as a confirmation of the "not encountered" prediction (~3.5 h), or to skip it.
3. Whether to proceed with section 7 (offline check and registration of `btt_reward_v3_rt`) in a new session.
4. Whether to fix the pre-existing `m7g_tests unit_training_isolation` failure: M7h's guard strings trip the M7g-a
   pattern.
5. Committing: nothing is committed. The M7h results files, the M7i proposal and all M7j files are uncommitted.
