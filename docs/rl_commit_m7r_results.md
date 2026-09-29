# M7r control-learning gate: results (2026-09-28)

Design: `docs/rl_temporal_control_design_2026-09-28.md` (rev 3, sections 5 and 8). Implementation:
`docs/rl_commit_m7r_implementation.md`. Approval: `docs/rl_commit_m7r_gate_approval.json` (sha256 `6b02e9b8…`).
Gate records (Git-ignored): `runs/m7r/gate/_gate/` — `state.json` (`bf1e39be…`), `analysis.json` (`f9f19745…`),
`driver.log`, and the post-hoc descriptive tables `descriptive_posthoc.json` (`641a4e3e…`, script beside it; never a
decision input).

**Registered outcome (`m7r_gate_rule_v1`, applied once): 5, inconclusive.** ST1 and PR1 improved together in 0 of 3
seeds: PR1 improved in all three seeds, ST1 in none. No discovery, no regression, no no-learning. Per design section 8,
outcome 5 means *revise, not rerun*: C is neither rejected nor eligible for a larger campaign.

## 1. Execution

| phase | result | native ticks | measured wall |
| --- | --- | ---: | ---: |
| driver preflight | profiles, unit suite 13/13, analysis self-test, backup coverage 377,359 / 0 uncovered, no game process, approval matches | 0 | ~55 s |
| P1 live `d = 1` identity | 8 / 8 pinned Track 1 artifacts reproduced word for word through the commit worker stack | 27,521 | 52.0 s |
| P2 training | 6 / 6 completed, 60 rollouts × 5,120 ticks each, 100 gradient steps per rollout, 0 process leaks | **1,843,200** (cap 1,843,200) | C 243.6 / 229.8 / 249.0 s; F 292.0 / 290.2 / 292.5 s |
| P3 evaluation | 360 episodes (per run 20 untrained stochastic + 30 final stochastic + 10 final deterministic), tick 0, every episode preserved with a gate trace | **1,224,075** (cap 1,296,000) | 1,258.5 s in total (untrained 62-77 s, final 118-151 s per run) |
| P4 verification | see section 2 | 41,882 replays + 0 discovery (cap with identity: 142,721; used 69,403) | 73.6 s |
| total | launch 22:05:59Z, analysis written 22:56:43Z | | ≈ 51 min |

End-to-end training throughput: C 1,317 / 1,401 / 1,287 ticks/s, F 1,087 / 1,095 / 1,086 ticks/s (C makes about 7.5×
fewer policy calls). Measured estimate for planning only: one 307,200-tick run ≈ 4 min (C) / 5 min (F) of training plus
≈ 3-4 min for a 60-episode evaluation on this machine.

One driver change was made before approval, not during the run: `DISCOVERY_REPLAYS_MAX = 20` enforces the documented
72,000-tick discovery-replay bound (implementation record, section 7). It never bound: there were 0 candidates.

## 2. Integrity (all pass; `analysis.json` integrity problems: none)

- P1 identity: every pinned artifact's canonical native words equal (3,361 + 2,560 + 6 × 3,600 ticks).
- Training: every rollout row `num_timesteps` = k × 5,120; C `commit_accounting` 5,120 native ticks and 100 gradient
  steps in every rollout; F SB3 `n_updates` = 10 per rollout. 32 preserved C training sidecars pass the expansion check
  (rollout cuts allowed).
- Evaluation: 180 C evaluation sidecars pass the expansion check with no rollout cut; every episode's gate-trace T
  equals its recorded `targets_broken`.
- Exact replays: 12 / 12 (2 final stochastic episodes per run) from tick 0 on fresh processes: native action digest
  equal, per-tick gate-trace rows equal, no consumed-tick mismatch, 0 unsent.
- Discovery: 0 candidates (left entry or left-target break) and 0 clears in C's finals, so nothing to replay.
- No BattleShip process remained. The D: backup and its PASS record were not touched. The native RNG was never
  inspected; seed 12345 and base seeds 0-2 are Python-side sampling seeds only.

## 3. Per-seed comparison (stochastic evaluation; 90 % percentile bootstrap, 10,000 resamples)

Groups: C final 30, F final 30, C untrained 20 episodes; every measure defined in every episode.
"Improves" = both lower bounds > 0.

| seed | measure | C final | F final | C untrained | Δ vs F [90 % CI] | Δ vs untrained [90 % CI] | improves |
| --- | --- | ---: | ---: | ---: | --- | --- | --- |
| 0 | **ST1** | 0.298 | 0.097 | 0.319 | +0.202 [+0.187, +0.217] | −0.021 [−0.046, +0.003] | no |
| 0 | **PR1** | 0.287 | 0.037 | 0.230 | +0.250 [+0.242, +0.257] | +0.057 [+0.045, +0.069] | yes |
| 0 | RE1 | 1.90 | 1.60 | 2.45 | +0.30 [−0.03, +0.63] | −0.55 [−0.88, −0.20] | (supporting) |
| 1 | **ST1** | 0.269 | 0.142 | 0.296 | +0.127 [+0.113, +0.141] | −0.028 [−0.050, −0.006] | no |
| 1 | **PR1** | 0.308 | 0.055 | 0.232 | +0.253 [+0.246, +0.261] | +0.076 [+0.065, +0.087] | yes |
| 1 | RE1 | 1.70 | 1.87 | 2.35 | −0.17 [−0.43, +0.10] | −0.65 [−0.98, −0.32] | (supporting) |
| 2 | **ST1** | 0.330 | 0.224 | 0.309 | +0.106 [+0.093, +0.119] | +0.021 [−0.002, +0.043] | no |
| 2 | **PR1** | 0.249 | 0.057 | 0.231 | +0.192 [+0.186, +0.198] | +0.018 [+0.007, +0.029] | yes |
| 2 | RE1 | 1.67 | 1.60 | 2.40 | +0.07 [−0.17, +0.30] | −0.73 [−1.03, −0.43] | (supporting) |

Target guardrail (mean T, stochastic): C final 3.83 / 3.87 / 4.03; F final 3.73 / 3.43 / 3.23; C untrained
3.15 / 2.95 / 3.10. No seed meets the no-learning condition (C final ≤ C untrained) or the regression condition
(C final ≤ F final − ½).

## 4. What the policies did (descriptive, post hoc)

- **Targets and reach.** Every final broke only right-side targets, mostly ids 0, 4, 5, 9 (C finals: 4 targets in
  26 / 22 / 23 of 30 episodes), with 3 and 7 occasionally; target 2 was never broken by any final. **No episode of
  either arm, trained or untrained (360 episodes), entered the left region or broke a left target (1, 6, 8).** C
  finals almost never fell (2 falls in 90 episodes; C untrained 19 in 60). The T advantage of C over F is therefore a
  right-side count, which the design says is never sufficient to select C.
- **Presses (PR1 denominator).** Per final stochastic episode, C made 255 / 258 / 308 move presses of which
  73 / 79 / 76 changed status; F made 2,210 / 1,948 / 2,054 presses of which 82 / 106 / 117 changed status. C's
  higher PR1 is mainly structural (it issues 7-9× fewer presses), already present untrained (0.23 in all seeds vs
  F final 0.04-0.06); the learning-attributable part is the Δ vs untrained, +0.018 to +0.076. F's PR1 did not rise
  with training (untrained 0.049 / 0.046 / 0.048), consistent with H1.
- **Steering (ST1).** C's coherence advantage over F is a property of the contract (untrained C 0.30-0.32 vs F final
  0.10-0.22) and did not grow with training. Training raised C's airborne time instead: 22-24 airborne segments of
  at least 40 ticks per episode in C finals vs 13-14 untrained, with unchanged coherence per segment. F learned some
  coherence (0.08 → 0.10 / 0.14 / 0.22).
- **Floors (RE1).** No arm reached more floor lines after training; the untrained C policy reached the most because it
  fell more.
- **Options.** Training: 41,008 / 38,295 / 43,711 decisions (mean option 7.49 / 8.02 / 7.03 ticks; F 307,200 each);
  idle replies 5,772 / 4,935 / 5,509, none stored; optimizer samples ≈ 0.38-0.44 M vs F 3.07 M at the same 6,000
  gradient steps. Ends over all C training decisions: max length 70.4 %, class change 19.3 %, apex 6.3 %, ground/air
  2.1 %, target break 0.6 %, rollout cut 0.64 %, hitlag end 0.4 %, episode end 0.2 %. The seeds learned different
  styles from uniform initial usage: seed 0 81 % hold (d = 32 / 4 / 1 / 16 most used), seed 1 66 % hold with d = 16 in
  39 % of decisions, seed 2 61 % tap with d = 2 most used. Final stochastic episodes: 440 / 414 / 497 decisions, mean
  option 8.2 / 8.4 / 7.2 ticks.
- **Deterministic finals.** F collapsed to 1-11 presses per episode and 1 / 1 / 0 targets. C kept acting
  (87-270 presses) and scored 2 / 3 / 2.

Hypothesis readings (design 1.5): H1 consistent (F PR1 low and not learned); H2 consistent but confounded (C's ST1 is
structural); H3 partly (higher PR1, modest learned gain); H4 not supported (no wider floor reach); H5 not testable here,
and no left-side event occurred in either arm.

## 5. Caveats

- PR1 measures press timing only. A press accepted a tick later (Turn re-injection, post-hitlag delivery) counts as
  ineffective and a same-tick animation end counts as effective; both arms are affected, and the within-contract Δ vs
  untrained is the fair learning signal. PR1 is a ratio: C's effective presses per episode are not higher than F's.
- 30 stochastic final episodes per run; the bootstrap resamples episodes within one training seed and does not
  describe training-seed variance. The gate is exploratory.
- Equal native ticks and gradient steps mean unequal samples per step (by decision 4): C optimised on about 13 % of F's
  samples with smaller minibatches.
- 307,200 ticks is short; M7p showed an early lead reversing later (geo4). Nothing here speaks to long-run ranking.
- The boundary class table is validated for Mario only.
- New files under `runs/m7r/` (gate outputs) are not in the D: backup; the incremental backup is needed before any
  later run (the driver's coverage check enforces it). The D: copy is same-machine only.

## 6. Recommendation (the next step needs its own authorisation)

No larger C campaign and no rerun of this gate (design section 8). The evidence says the contract changes the form of
input (fewer, sustained presses, no deterministic collapse) mostly by construction, learning adds only a modest press-
timing gain, and the binding problem is unchanged: **zero left-side entries in 360 tick-0 episodes in either arm**.
The recommended next step is a **design-only review of approach D (goal-conditioned, reach-directed exploration whose
goals come from the agent's own reached states, never waypoints, fixtures or TAS)**, which the design reserved for
"C improves control without improving reach". It would start with a read-only analysis of the existing M7r records:
how close each episode's trajectory gets to the wall and the left region, and what C and F do in long airborne
segments. v3 + reward v2 stays selected; v4 and C stay opt-in (not selected, not rejected).
