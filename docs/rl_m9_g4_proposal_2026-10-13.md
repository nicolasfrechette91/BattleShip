# M9-g4 proposal (2026-10-13)

## 1. Summary

**Part 1 (offline attractor test).** The stop review's threshold reproduces exactly. Recomputed from the recorded events of every g3 training
episode (the undiscounted v2 return matches every recorded return to 1.8e-15, and the stop review's 50 per-bin class means match to 0.000), the
clear probability below which waiting until the horizon beats attempting is **0.202 in s5 and 0.213 in s6** (0.20-0.23 in every g3 session; 0.16-0.27
per s6 bin; 0.246 at the cleaner decision point "target 8 just broken"). Under v2, waiting beat attempting at the bin's own clear rate in **13 of
s6's 30 bins** (bins 4, 14, 17-20, 22, 23, 26-30: the trough and the second decline) and in **none of s5's 20 bins**.

Thirty-two alternative contracts were recomputed on the same trajectories. The result has a simple structure (section 2.4): with a per-tick cost
c, a failure penalty P (falls, and the horizon when it is terminal) and discount gamma, failing later is better than failing earlier exactly when
P > c gamma / (1 - gamma), and waiting until the horizon is the latest possible failure. v2 sits at P = 5 against c gamma / (1 - gamma) = 0.999,
so it rewards survival over failure by design (its own docstring says an early fall can never outscore surviving to the horizon). Consequently:

- **The horizon as a failure alone halves the threshold (0.11-0.12) but does not remove it**: the horizon's -5 arrives about 1,800 ticks after
  the handover and is discounted to about 0.16, a fall's to about 0.5.
- **A per-tick cost alone** removes it only at c >= about 0.0075, where an early fall becomes better than a late one (by +0.65): reckless.
- **Shorter horizons alone make it worse** (0.22-0.27) and cut 9-53 % of s5's clears.
- **The neutral point removes it without a reckless incentive.** "N1" (fall penalty -1, horizon a terminal failure with the same -1, nothing
  else changed) gives a threshold of -0.045 / -0.021 (waiting never better, even than a fall, at the decision point in 29 of 29 s6 bins), makes
  every failure worth -1 whatever its timing (early minus late fall: -0.0003), leaves **every clear's return exactly unchanged** (s5's clear
  values shift 0.000; the speed incentive is identical), and keeps the margin of a clear over the best non-clear outcome at 7.24 (v2: 7.39). A
  warm start of s5's critic under N1 sees a pessimistic mismatch with the same share of negative advantages as under v2 (47.4 % against 47.6 %),
  while the other neutral variant (N5: step cost 0.005 with a -5 horizon) starts optimistic (58.5 % negative): the direction the stop review
  linked to s6's first dip.

What offline recomputation cannot show: whether the policy would have stayed out of the attractor under N1 (the policy and critic would change),
the value SB3 bootstrapped at each horizon (terminal observations are not saved), and what first pushed s6's clear rate under the threshold.

**Part 2 (proposed g4).** A new resumable line `m9_g4` = g3's replenishing controlled frontier, with **one contract change**, the reward /
termination contract N1 (provisionally `btt_reward_v2n`), plus registered procedures the owner listed as starting points:

1. warm start from s5's final state, bit for bit, with the frontier pointer verified at session start by a generic init probe;
2. triggered regression probes: a free training statistic triggers, a frozen probe decides, a rollback to the last certified state follows;
3. keep-best selection at session end by a registered rule, then a close audit on fresh keys;
4. all probes capped at 30 % of the training wall;
5. a budget rebased on D = 1,694 at about 100 ticks of depth per counted session, along the whole trunk's landing scale (16 landings and tick 0,
   derived by the registered generic rule from the agent's own route; it reproduces the six registered landings exactly).

The final success criterion (clears from tick 0, no prefix, unperturbed and sticky) is reached by a separate, already-defined claim gate
(`rl/m9_claim.py`) once the line's depth reaches tick 0. Realistic pace: about 17 counted sessions from 1,694 to tick 0 at the pace of
g3's budget; the line is capped at 8 with a written review to renew. The sticky-versus-unperturbed gap is measured and kept out of g4's single
change. Preparation: two or three preparation sessions, an independent pre-launch review, then Part B and the launch on another day.

**Status and scope. Design only. Zero native ticks: no game process, no suite, preflight, launcher, training or evaluation was started. No
tracked file was modified; nothing under `runs/` or on D: was written; no commit, push, branch or pull request.** The only new files are this
proposal and the Git-ignored working files under `logs/m9_g4_design/` (listed in the table below). Nothing here is decided: every choice below is
a recommendation for the owner, and the numbered questions of section 7 must be answered before any preparation.

| item | value |
| --- | --- |
| checkout | `C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\BattleShip`, branch `main`; HEAD = `origin/main` = the remote's `main` = `3b351d451f9560279ac5cd6041f647d0298ab8e9` ("Add the project handoff"); `git status --porcelain --untracked-files=all` empty and nothing staged at the start (checked after the owner committed the handoff, the checklist and the runbook update) |
| read | `CLAUDE.md`; `docs/project_handoff.md`; `docs/rl_runbook.md`; `docs/rl_by_hand_session_checklist.md`; in full `docs/rl_m9_g3_stop_review_2026-10-10.md`, `docs/rl_m9_g3_progression_fix_2026-10-08.md`, `docs/rl_m9_g3_resume_k_prep_decisions_2026-10-08.md` and the six results records `docs/rl_m9_g3_s{1..6}_results_*.md`; the g3 code (`rl/m9_g3_*.py`, contract, frontier, rule, train, probe headers and functions), the reward v2 definition (`rl/btt_rewards.py`), the episode reward and termination code (`rl/m9_vec.py`), the obs v3 time feature (`rl/m7n_obs.py`), `rl/m9_contract.py`, `rl/m9_g2_contract.py`, `rl/m9_g2_resume.py`, `rl/m9_claim.py` (header); the stop review's working files `logs/m9_g3_stop_review/*.py` and `out/`; the landing derivation in `docs/rl_m9_policy_proposal_2026-10-03.md` |
| evidence read (Git-ignored, read-only) | `runs/m9_g3/s{1..6}/training/{episodes,rollouts}.jsonl` (19,695 training episodes), `runs/m9_g3/s{1..6}/audit/episodes.jsonl`, `runs/m9_g3/s5/training/checkpoints/final/model.zip` (pin `382dde88...`), `runs/m9_g3/s5/lineages/T_clear/{v3.bin,words.bin}`, `runs/m9_g3/s5/input/tape_baseline.json`, `runs/m8_rd_rd4/routes/T_clear/trace.json.gz` (the agent's own verified route). No human recording, no TAS, no fixture |
| method | offline Python (`python -B -X utf8`, `sys.dont_write_bytecode`); one policy loaded weight-only with `torch.optim.Optimizer.__init__` replaced by a function that raises; no RNG of any kind used; no native RNG seed inspected, logged, controlled, compared or hashed |
| files written | Created (new files only): this proposal; `logs/m9_g4_design/a_attractor.py`, `b_warmstart.py`, `c_landings.py`, `d_trigger.py`; outputs `logs/m9_g4_design/out/attractor.json`, `attractor_table.txt`, `a_attractor_stdout.txt`, `warmstart_and_sticky.json`, `b_warmstart_stdout.txt`, `landings.json`, `c_landings_stdout.txt`, `trigger_calibration.json`, `trigger_calibration_table.txt`, `trigger_calibration_drawdown.json`, `trigger_calibration_drawdown_table.txt`, `d_trigger_stdout.txt`, `d_trigger_drawdown_stdout.txt` (`logs/` is Git-ignored). No tracked file modified, nothing under `runs/` or on D: written, no compiled module written, zero native ticks. `git status --porcelain --untracked-files=all` at the end shows only `?? docs/rl_m9_g4_proposal_2026-10-13.md`. |

**What this proposal does not claim.** It does not claim that N1 prevents the collapse, that the attractor caused s6's collapse, or anything
about other seeds, budgets or recipes. It changes no registered g3 outcome (s6 NULL, line END_BUDGET_1694 stand) and authorises nothing.

## 2. Part 1: the offline attractor test

### 2.1 Method

- **Data.** Every training episode of g3 s1-s6 (19,695): start tick `tau`, policy ticks `n`, `end_reason` (clear / fall / horizon), the recorded
  target breaks `[input tick, id]`, the start region, the left-floor tick, the completion wall time. Every horizon episode ends at input tick
  3,600 (the horizon counts from the reset).
- **Event model.** Policy step i consumes tick tau + i; a break recorded at input tick T is rewarded on step T - tau - 1; a clear or fall on
  the last step n - 1; every step costs -c. The registered horizon is a truncation: SB3 adds gamma V(terminal observation) to the last reward
  (`TimeLimit.truncated`, `rl/m9_vec.py`). The terminal observations are not saved, so that bootstrap is a parameter V_T (0 in the stop
  review's convention; +-3 as sensitivity).
- **Validation.** The undiscounted v2 return recomputed from the events equals the recorded `return` of all 19,695 episodes (max error 1.8e-15),
  and the step and target terms equal the recorded `reward_terms`. With the stop review's own binning (20 rollouts per bin, T_clear lineage) the
  per-bin discounted class means G_clear / G_fall / G_horizon and counts of s5 and s6 equal `logs/m9_g3_stop_review/out/q4_drift.json` exactly
  (max difference 0.000 over 50 bins). **The ~0.2 threshold is reproduced; Part 1 proceeded.**
- **The threshold.** Over a set of episodes with discounted class means Gc, Gf, Gh (gamma 0.999, from the handover), attempting with clear
  probability p is worth p Gc + (1 - p) Gf and waiting Gh, so waiting is better below **p\* = (Gh - Gf) / (Gc - Gf)**. p\* <= 0 means waiting is
  no better than even a failed attempt ("never better"). Computed per session, per start region, per 102,400-transition bin, and at two decision
  points that remove most of the composition effect (horizon episodes and falls differ in where they were): **after target 8** (continuation from
  the step after the reply that showed target 8 broken; only target 1 and the clear remain) and **on the left floor** (from the first left-floor
  reply). These two labels come from the records and serve this analysis only; nothing proposed below uses them.
- **"Dominated."** In a bin, s6's waiting is dominated at its realized rate when p_all Gc + (1 - p_all) Gf > Gh, with p_all = clears / all
  episodes of the bin (the stop review's clear rate); dominated at any rate when Gh <= Gf.
- **Shorter horizons** relabel the recorded trajectories: an episode longer than the limit is cut there and becomes a horizon ending; later breaks
  are dropped. The trajectory before the cut is the recorded one.
- **Side effects on s5** (the healthy session): the shift of clear, fall and horizon returns against v2; the margin of a clear over the best
  non-clear class; the value of a clear 60 ticks shorter (median s5 clear, 506 ticks; no targets); the value of an early fall minus a late one
  (s5's 5th-percentile and median fall lengths, 265 and 676 ticks, no targets; > 0 means an earlier failure is rewarded: reckless); s5 clears
  the horizon would cut; the rank correlation of all s5 returns with v2's.
- **Warm-start mismatch** (section 2.5): s5's final critic V(tau) on the agent's own trunk observations against each contract's return of the
  episodes a warm start resembles most.

Working files: `logs/m9_g4_design/a_attractor.py` (all of the above), `b_warmstart.py` (sections 2.5 and 3.8), `c_landings.py` (section 3.9),
`d_trigger.py` (section 3.5); outputs under `logs/m9_g4_design/out/`.

### 2.2 Results

p\* columns: s5 and s6 sessions; s6 at the after-target-8 decision point. "s6 bins att > wait": bins (of 30) where attempting beat waiting at
the bin's realized clear rate. "after-8 bins wait <= fall": bins (of 29 with all three classes) where waiting was no better than even a fall.
s5 columns: clears cut by the horizon (of 1,462); mean shift of s5's clear returns against v2; early minus median fall (> 0 = reckless); the
margin of a clear over the best non-clear class (v2: 7.39); Spearman correlation of all s5 returns with v2's. "60 t" = value of a clear 60
ticks shorter (v2: 0.411).

| # | contract | p\* s5 | p\* s6 | p\* s6 after 8 | s6 bins att > wait | after-8 bins wait <= fall | s5 clears cut | s5 clear shift | early - median fall | clear margin | Spearman | 60 t |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| R0 | **v2 as registered** (truncation, V_T = 0) | **0.202** | **0.213** | **0.246** | **17** | 0 | 0 | 0 | -1.036 | 7.39 | 1 | 0.411 |
| R0- | v2, V_T = -3 | 0.144 | 0.157 | 0.142 | 21 | 0 | 0 | 0 | -1.036 | 7.92 | 0.999 | 0.411 |
| R0+ | v2, V_T = +3 | 0.260 | 0.270 | 0.349 | 9 | 0 | 0 | 0 | -1.036 | 6.85 | 1.000 | 0.411 |
| H5 | horizon = terminal failure, -5 | 0.106 | 0.120 | 0.073 | 26 | 4 | 0 | 0 | -1.036 | 8.28 | 0.995 | 0.411 |
| C2 | step cost 0.002 | 0.166 | 0.178 | 0.222 | 19 | 0 | 0 | -0.40 | -0.777 | 7.80 | 0.999 | 0.448 |
| C3 | step cost 0.003 | 0.130 | 0.142 | 0.198 | 24 | 0 | 0 | -0.81 | -0.519 | 8.22 | 0.996 | 0.485 |
| C5 | step cost 0.005 | 0.059 | 0.074 | 0.153 | 28 | 0 | 0 | -1.61 | -0.001 | 9.06 | 0.973 | 0.560 |
| C7.5 | step cost 0.0075 | -0.025 | -0.007 | 0.098 | 30 | 0 | 0 | -2.62 | **+0.645** | 9.86 | 0.913 | 0.653 |
| C10 | step cost 0.010 | -0.105 | -0.084 | 0.046 | 30 | 5 | 0 | -3.63 | **+1.292** | 10.09 | 0.874 | 0.746 |
| S3000 | horizon at input tick 3,000 | 0.221 | 0.231 | 0.265 | 9 | 0 | 199 | -0.42 | -1.036 | 7.86 | 0.987 | 0.411 |
| S2700 | horizon at 2,700 | 0.238 | 0.245 | 0.272 | 5 | 0 | 408 | -1.05 | -1.036 | 8.29 | 0.951 | 0.411 |
| S2400 | horizon at 2,400 | 0.244 | 0.250 | 0.281 | 2 | 0 | 774 | -2.54 | -1.036 | 9.06 | 0.812 | 0.411 |
| B1200 | 1,200-tick policy budget | 0.226 | 0.237 | 0.266 | 9 | 0 | 139 | -0.26 | -1.036 | 7.65 | 0.993 | 0.411 |
| B900 | 900-tick policy budget | 0.244 | 0.250 | 0.272 | 5 | 0 | 326 | -0.76 | -1.036 | 8.03 | 0.972 | 0.411 |
| B600 | 600-tick policy budget | 0.261 | 0.268 | 0.283 | 2 | 0 | 625 | -1.84 | -1.036 | 8.66 | 0.899 | 0.411 |
| H5+C3 | terminal -5, cost 0.003 | 0.035 | 0.050 | 0.029 | 30 | 5 | 0 | -0.81 | -0.519 | 9.12 | 0.981 | 0.485 |
| H5+C4 | terminal -5, cost 0.004 | 0.000 | 0.017 | 0.008 | 30 | 9 | 0 | -1.21 | -0.260 | 9.53 | 0.959 | 0.522 |
| **N5** | terminal -5, cost 0.005 (neutral) | -0.034 | -0.016 | -0.013 | 30 | 29 | 0 | -1.61 | -0.001 | 9.63 | 0.947 | 0.560 |
| H5+C6 | terminal -5, cost 0.006 | -0.067 | -0.048 | -0.034 | 30 | 29 | 0 | -2.02 | **+0.257** | 9.72 | 0.914 | 0.597 |
| H5+S2700 | terminal -5 at 2,700 | 0.031 | 0.051 | 0.026 | 26 | 4 | 408 | -1.69 | -1.036 | 10.54 | 0.875 | 0.411 |
| H5+S2400 | terminal -5 at 2,400 | -0.012 | 0.008 | 0.009 | 29 | 9 | 774 | -4.20 | -1.036 | 11.99 | 0.667 | 0.411 |
| H5+B900 | terminal -5 after 900 | 0.053 | 0.060 | 0.026 | 26 | 4 | 326 | -1.21 | -1.036 | 10.06 | 0.930 | 0.411 |
| F2.5 | fall -2.5 (truncation) | 0.077 | 0.094 | 0.122 | 26 | 0 | 0 | 0 | -0.389 | 7.39 | 0.986 | 0.411 |
| F1 | fall -1 (truncation, V_T = 0) | -0.020 | 0.003 | 0.027 | 30 | 0 | 0 | 0 | -0.000 | 7.24 | 0.951 | 0.411 |
| **N1** | **fall -1, horizon terminal -1** | **-0.045** | **-0.021** | **-0.018** | **30** | **29** | **0** | **0** | **-0.000** | **7.24** | **0.948** | **0.411** |
| N1x | N1 with the exact 0.999 | -0.045 | -0.021 | -0.018 | 30 | 29 | 0 | 0 | 0.000 | 7.24 | 0.947 | 0.411 |
| N0 | no cost, no penalty, terminal 0 | -0.049 | -0.023 | -0.019 | 30 | 29 | 0 | +0.40 | 0.000 | 6.64 | 0.944 | 0.373 |
| V1 | reward v1 (no fall penalty) | -0.097 | -0.069 | -0.049 | 30 | 29 | 0 | 0 | **+0.259** | 6.74 | 0.914 | 0.411 |
| CB20 | clear bonus 20 | 0.123 | 0.130 | 0.148 | 25 | 0 | 0 | +5.97 | -1.036 | 13.36 | 0.999 | 0.784 |
| G.9995 | gamma 0.9995 + terminal -5 | 0.042 | 0.054 | 0.030 | 29 | 5 | 0 | +1.79 | -0.489 | 11.51 | 0.983 | 0.284 |
| G.9998 | gamma 0.9998 + terminal -5 (neutral) | -0.021 | -0.010 | -0.013 | 30 | 28 | 0 | +3.25 | -0.000 | 14.29 | 0.929 | 0.164 |
| G1 | gamma 1 + terminal -5 | -0.076 | -0.066 | -0.051 | 30 | 29 | 0 | +4.45 | **+0.411** | 16.16 | 0.800 | 0.060 |

Further readings (`out/attractor.json`):

- **v2 per region and per session.** p\* by start region: s5 strip / near / rehearsal 0.196 / 0.204 / 0.239; s6 0.205 / 0.215 / 0.238; per
  session s1-s6: 0.222, 0.230, 0.230, 0.220, 0.202, 0.213. The threshold is a stable property of the contract. The clear rates were 0.43-0.60 in
  s1-s5 and 0.244 in s6: s6 sat near the threshold for the whole session (0.244 against 0.213), and its strip (0.184) under it.
- **The trough bins.** Under v2 the 13 s6 bins where waiting beat attempting at the realized rate had clear rates 0.03-0.23 against p\* of
  0.18-0.27. Measured at the success rate among non-horizon episodes instead (clears / (clears + falls), an optimistic estimate of an attempt's
  success because waiting episodes may come from states where attempts fail more), waiting still won in 8 of 30 bins. At the after-8 decision
  point, waiting won in 12 of 29 bins at the realized rate and in 6 at the optimistic rate.
- **Under N1** attempting beat waiting in 30 of 30 s6 bins at both rates, and waiting was worse than a fall at the after-8 point in 29 of 29
  bins (on the floor: 25 of 30; in the 5 other bins the horizon episodes had broken more targets after the landing than the falls, 0.28-0.58
  against 0.10-0.47 on average: a target-count composition effect of 0.04-0.10, not timing). Under **H5** alone waiting still won in bins
  27-30. Under **F1** (no horizon change) p\* at the after-8 point stays positive (+0.027) and waiting was never worse than a fall (0 of 29)
  with V_T = 0: F1 is neutral only if the critic bootstraps the horizon at about -1, which cannot be checked offline.

### 2.3 Answers, candidate by candidate

| question | v2 (R0) | horizon as failure (H5) | per-tick cost (C2-C10) | shorter horizons (S, B) | combinations | N1 (recommended) |
| --- | --- | --- | --- | --- | --- | --- |
| threshold | 0.20-0.21 (0.25 after 8) | 0.11-0.12 (0.07) | 0.17 -> -0.08 as c grows; <= 0 from c ~ 0.0075 | 0.22-0.27: **higher** | H5 + c 0.003-0.004: 0.00-0.05; N5 and G.9998: < 0; H5 + S2400: ~0 | -0.045 / -0.021 (-0.018 after 8) |
| s6's waiting dominated? | no in 13 of 30 bins | no in 4 bins (27-30) | yes in all bins only from c 0.0075 | no in 21-28 bins | at the realized rate in all bins for H5 with c >= 0.003; worse than even a fall after 8 only for N5 (29 of 29) and G.9998 (28) | **yes in 30 of 30; worse than a fall in 29 of 29 after 8** |
| s5's successes | reference | unchanged | clear values fall by 0.4-3.6 | 9-53 % of s5's clears cut | N5 lowers clears by 1.6; G.9998 raises them by 3.3 and flattens the speed incentive (0.16 per 60 ticks) | **unchanged, exactly** (speed incentive identical) |
| reckless failure? | no (later falls better by 1.04) | no | **yes from c ~ 0.0075** (+0.65, +1.29) | no | yes for H5+C6 (+0.26), G1 (+0.41), V1 (+0.26) | no: every failure worth -1 +- 0.001 whatever its timing |

### 2.4 Why the family behaves this way (closed form)

For a non-clear ending at step n with penalty P (a fall, or the horizon when it is terminal), per-step cost c and discount gamma, and the same
targets broken, the discounted return is `-c (1 - gamma^n) / (1 - gamma) - P gamma^(n-1)`. Failing at n2 instead of n1 < n2 changes it by
`(gamma^n1 - gamma^n2) (P / gamma - c / (1 - gamma))`. Hence:

- **P > c gamma / (1 - gamma)** (v2: 5 > 0.999): a later failure is always better, and waiting to the horizon (the latest failure, which v2
  does not even penalise) beats falling; p\* > 0. This is v2's registered design intent, stated in `rl/btt_rewards.py`.
- **P < c gamma / (1 - gamma)** (C7.5, C10, V1, H5+C6, G1): an earlier failure is better: waiting is beaten, but so is a careful attempt by a
  quick fall when p is small. Reckless.
- **P = c gamma / (1 - gamma)**: every failure is worth -P whatever its timing; waiting equals failing; attempting beats both for any p > 0.
  This is the only point of the family where "waiting is never better than attempting" holds without rewarding an earlier failure. It can be
  reached by changing P (N1: P = 0.999, about 1), c (N5: c = 0.005 with P = 5) or gamma (G.9998); N1 is the only one that leaves every clear's
  return, the per-tick cost and the PPO values untouched.
- With truncation instead of a terminal horizon, waiting is worth `-(1 - gamma^n) + gamma^n V_T`, which depends on the critic's extrapolation to
  a clock value (`time_passed / 3,600` is in observation v3) that no training transition ever starts from. A terminal horizon removes that
  dependence; with a time-aware observation it is also the consistent treatment of a time limit that is part of the task (the success criterion
  is a clear within 3,600 ticks).

### 2.5 Warm-start critic mismatch (s5's final critic, `out/warmstart_and_sticky.json`)

s5's final critic V(tau) on the 2,327 trunk observations rebuilt from the agent's recorded rd4 replies (0 digest mismatches against
`runs/m9_g3/s5/lineages/T_clear/v3.bin`; the recorded audit start values reproduced to 4.6e-5), against each contract's discounted return of the
episodes a warm start resembles most. Cells: mean of (G - V(tau)), RMS, share negative.

| contract | s5 last four bins (458 episodes, T_clear) | of which falls (160) | s6 bin 1 (113; the first 102,400 transitions after s5's final) |
| --- | --- | --- | --- |
| v2 (R0) | +0.60, 4.63, 47.6 % | -4.31 | +0.66, 4.81, 59.3 % |
| H5 | +0.53, 4.67, 47.8 % | -4.31 | +0.57, 4.85, 60.2 % |
| C5 | -1.33, 5.14, 58.5 % | -6.33 | -1.35, 5.37, 63.7 % |
| F1 | +1.29, 4.08, 47.4 % | -2.33 | +1.45, 4.36, 54.9 % |
| **N1** | **+1.28, 4.09, 47.4 %** | **-2.33** | **+1.43, 4.36, 54.9 %** |
| N5 | -1.39, 5.22, 58.5 % | -6.33 | -1.44, 5.45, 63.7 % |
| N0 | +1.94, 4.10, 43.2 % | -1.33 | +2.15, 4.42, 31.9 % |

Under N1 the inherited critic is pessimistic on failure-heavy starts (by about 2 on falls) and exact on clears, with a smaller RMS error than v2's
own and the same share of negative advantages. N5 and C5 start with an optimistic critic everywhere (58-64 % negative): the direction the stop
review found after s6's move (78 % negative in bins 2 and 4). **No critic warm-up phase is proposed for N1.** These are handover values only.

### 2.6 Limits of an offline recomputation

1. **The trajectories are held fixed.** Under another contract the policy and the critic would change, and with them the clear rates, the episode
   lengths and the class means. The thresholds describe the incentive at the recorded behaviour, not the behaviour a contract would produce.
2. **The horizon bootstrap is unknown.** SB3 added gamma V(terminal observation) to every horizon episode; those observations are not saved.
   v2's numbers use V_T = 0 (the stop review's convention); V_T = +-3 moves p\* by +-0.06 and the count of s6 bins from 17 to 9 or 21.
3. **Class means mix states.** Horizon and fall episodes differ in where they were and what they had broken. The after-8 decision point removes
   most of this but rests on descriptive labels and on the episodes that reached that point.
4. **"Waiting" is not an action.** The policy is stochastic (84-92 % of the maximum entropy) and horizon-waiting emerges per state; per-state
   advantages (GAE lambda 0.995, per-minibatch normalisation, the entropy term) cannot be reconstructed because per-tick observations of the
   agent's episodes are not saved.
5. **Circularity.** The bins where waiting won are, by construction, bins with low clear rates and many horizon endings. The analysis shows that
   v2's incentive was consistent with the drift; it does not show that the incentive caused it. What first pushed the 1,760 strip under the
   threshold, when s5's 1,800 strip recovered from the same first-hundred rate, remains undetermined.
6. **Shorter horizons are relabellings.** The policy never knew of an earlier cut; its clock feature is `time_passed / 3,600` either way.
7. **One run each.** s5 and s6 are single runs of one seed; nothing is claimed about other seeds or budgets.
8. **The warm-start table** uses one critic on handover states only.

**Cannot be determined offline:** whether N1 prevents the collapse (it needs training); the bootstrap values actually used; whether N1's smaller
clear-versus-fall contrast (9.26 -> 7.24 in s5's class means, -22 %) slows learning or raises the fall rate; the cause of the sticky / unperturbed
gap (section 3.8).

## 3. The proposed design: line `m9_g4`

### 3.1 What changes against g3, and what does not

| element | g3 (registered) | g4 (proposed) | kind |
| --- | --- | --- | --- |
| reward / termination | `btt_reward_v2`: +1 per target, -0.001 per policy tick, +10 clear, -5 fall; horizon = truncation (bootstrapped) | **N1** (`btt_reward_v2n`, name provisional): the same, except **-1 on a fall** and the horizon (input tick 3,600 from the reset, unchanged) **a terminal failure with -1**, no bootstrap. Generic rule: every non-clear ending carries the same terminal penalty P = c gamma / (1 - gamma) (0.999 with the registered c and gamma; -1 within 0.001 per episode, question 1) | **the one contract change** |
| observation, action, sticky p, PPO values, gamma, lambda, entropy 0.01, network, rollout 5,120, 4 + 6 slots, start regions 50 / 30 / 20, strip 20, trigger 8 of 20, strip test 10 of 20, spacing 20 x 2^(f-1) cap 320, 80-minute wall, 3,072,000-transition cap, the 145-minute session cap | as g3 | unchanged | |
| start of the line | fresh (s1) or the predecessor's final state | **warm start**: s5's final state bit for bit (weights and Adam state), imported across lines by pin | procedure |
| the pointer at a session start | carried | **verified by the init probe** (section 3.4) | procedure |
| regressions within a session | none | **triggered regression probe, rollback to the last certified state** (section 3.5) | procedure |
| the state a session hands on and audits | the final state | **the selected state** (keep-best, section 3.6) | procedure |
| close audit keys | the g2 `reach` family, identical every session (paired with the tape) | **fresh keys per session** (section 3.6) | procedure |
| probe budget | none (s5 spent 22.8 % on attempts) | **30 %** of the training wall, all probes (section 3.7) | procedure |
| re-check set of an attempt | every landing behind the pointer | the two nearest landings behind the pointer and the route's last landing (2,128), at most three tests (section 3.4) | procedure |
| landing scale | six landings 2,128-1,248 | the whole trunk by the same generic rule: 16 landings and tick 0 (section 3.9) | registration |
| per-session rule and line rule | `m9_g3_s1_rule_v1`, `m9_g3_line_rule_v1` (absolute depths) | `m9_g4_session_rule_v1`, `m9_g4_line_rule_v1`, rebased (section 4) | rules |

Every g4 rule is generic and stage-agnostic: the landings come from the agent's own route by a rule that names no position or target; the
trigger, probes, certification and selection read clear counts only. No native RNG seed is involved anywhere; every draw is a Python-side keyed
sha256 uniform on the new `m9|g4|...` family.

### 3.2 The reward / termination contract

Per policy step: +1 per newly broken target, -0.001, +10 once on the native clear, -P once on the native failure, and -P once on the step whose
reply reaches input tick 3,600, which ends the episode as a **termination** (SB3 `done` with `TimeLimit.truncated` false; no bootstrap). The
record keeps `end_reason: horizon`. Lifecycle failures stay truncations with reward 0, as now. Prefix breaks earn nothing (rebased at the handover,
as now). Implementation lives in a g4 subclass of `rl/m9_vec.EpisodeCtx` (the inherited `rl/btt_rewards.py` and `rl/m9_vec.py` stay untouched; the
contract is registered by value and fingerprint in `rl/m9_g4_contract.py`). Unit tests pin: any failure at any n returns -P +- 0.001 plus its
discounted targets; every clear returns exactly its v2 value; the horizon step is terminal.

### 3.3 Warm start or fresh start

| | warm start (recommended) | fresh start |
| --- | --- | --- |
| state | s5's final `model.zip` (`382dde88...`, members `f3e0dc32...` / `e3a78f5b...`), Adam state carried; frontier state from `curriculum_state.json` (`147467ca...`), pointer then verified by the init probe; depth reference D_start = 1,694 (s5's registered PASS) | seed 0, the initial weights of g1 / g2 / g3-s1 (`eb592c88...`), pointer TAU0 = 2,300, no init probe; D_start none |
| what it can support | "Under N1, training continued from g3's best registered state [kept / lost] its landing competence and [moved / did not move] the depth past 1,694 within the budget." A one-session contrast with s6 (same starting state, v2, collapsed), n = 1 each with different draws: suggestive, not an attribution | "With N1 and the same recipe, the policy reached depth X by counted session k", against g3's v2 trajectory from identical initial weights (D by session: none, 2,128, 2,128, 1,966, 1,694, none): a one-change comparison, n = 1 each |
| what it cannot support | that the contract alone caused any difference; that the recipe learns from scratch | anything about g3's state; it costs about five sessions to return to 1,694 |
| cost | none extra | about 5 sessions (13-15 hours of sessions) before new ground |

Recommendation: the g4 line warm-starts. A fresh-start control is a separate line, proposed only if the warm start collapses (to separate "the
contract" from "the inherited state") or later for a from-scratch claim (question 2).

### 3.4 The frontier at session start, and the re-check set

**Init probe (`m9_g4_frontier_init_v1`).** At the open of every session whose carried pointer is earlier than TAU0 (the warm start and every
resume), before training, on fresh keys `m9|g4|init|s<k>|<part>|<j>`, with the frozen initial policy:

1. Run the frozen strip test at the carried pointer and the re-checks of section "re-check set" below, in parallel, each curtailed as in g3
   (pass at the 10th clear of at most 20, fail at the 11th non-clear).
2. If all pass, the pointer stays; the initial state becomes **certification 0**.
3. If the strip test fails, the pointer steps **forward** (later) by one strip and the strip test is repeated there; if a re-check at landing L
   fails, the pointer jumps forward to the first grid point from which L is no longer behind (the strip containing L). Repeat until every test
   passes, at most to TAU0. The landings' tests already passed are not repeated.
4. The outcome (`INIT_KEPT`, `INIT_STEPPED_FORWARD` by n strips, `INIT_AT_TAU0`) is recorded; it never ends a session.

For s5's state the likely case is one strip test at 1,780 plus re-checks at 2,128 and 1,966 (s6's first attempt at the same pointer from almost
the same weights passed 10 / 19, 10 / 12 and 10 / 17), about 70 s. The rule never moves the pointer backward at the open: backward moves stay
earned by a training trigger and a frozen test, the lesson of g1's lucky moves. (Alternatives in question 4.)

**Re-check set.** Every frozen test that guards the past (the init probe, an attempt's re-checks, a regression probe, the selection probe) tests
**the two nearest registered landings behind the pointer and the route's last landing** (2,128, the final drop that g1 and s6 lost first), at
most three tests. g3's "every landing behind" costs about 20 episodes per landing and would reach 13 landings near tick 0. The close audit still
measures every landing D needs.

### 3.5 Training-time safety: trigger, frozen regression probe, rollback

- **Trigger (training statistic, free; `m9_g4_regression_v1`).** NR = the clear rate of the last 100 completed training episodes that started in
  the near or rehearsal region (route already passed), checked every 50 such episodes; the trigger fires when NR < 0.40. The window restarts after
  a move, a rollback or a probe. Offline calibration on g3 (`out/trigger_calibration*.txt`):

  | rule | s1 | s2 | s3 | s4 | s5 | s6 (first firing) |
  | --- | ---: | ---: | ---: | ---: | ---: | --- |
  | **NR < 0.40, window 100, every 50** | 0 | 0 | 0 | 0 | 0 | 13 (523.6 s) |
  | NR < 0.35, window 100, two checks | 0 | 0 | 0 | 0 | 0 | 6 (689.4 s) |
  | NR < 0.45, window 60 | 0 | 0 | 6 | 1 | 0 | 23 (358.7 s) |
  | horizon share of transitions > 0.40, window 60 | 0 | 0 | 2 | 6 | 1 | 23 (415.2 s) |
  | drawdown 0.20 from the peak since the last move | 0 | 0 | 1 | 1 | 0 | 2 (2,418.8 s) |

  The recommended rule never fired in five sessions whose pointers ran from 2,300 to 1,780, and fired in s6 at 524 s, inside the first decline
  (285-680 s). The statistic is a clear rate, so the contract change does not alter its meaning. What a probe would have found at 524 s is not
  known (no s6 checkpoint was evaluated).
- **Regression probe (frozen, decides).** At the next rollout boundary: a frozen snapshot, the re-check set (or, while no landing is behind the
  pointer, the strip test at pointer + 20, the last passed strip), keys `m9|g4|regr|s<k>|<n>|<part>|<j>`. Pass: the current state becomes a new
  certification and the trigger re-arms. Fail: **rollback**.
- **Certification.** A state is certified when its frozen snapshot passed the re-check set on fresh keys: the init probe, every MOVED attempt
  (strip test and re-checks), every passing regression probe. Each certification writes a **full** checkpoint `cert_<n>` (model.zip with the
  Adam state, curriculum state); g3's attempt snapshots held the policy weights only.
- **Rollback.** Restore the latest certification's model, Adam state, pointer, spacing counters and windows; keep the attempt history and the
  per-pointer failed-attempt counts (they are history; the spacing at a restored pointer uses its line-wide count); discard the rollout buffer;
  withdraw staged starts; continue. `num_timesteps` keeps counting.
- **Limit.** At most two rollbacks per session. A third confirmed regression ends training with the registered valid end `REGRESSION_LIMIT`
  (the session counts, as a transition-cap end does) and the session goes to selection with the latest certification.

### 3.6 Keep-best selection and the fresh-keys close audit

- **Selection rule `m9_g4_select_v1` (registered before the line starts).** After training ends (any valid end), the frozen final policy takes
  the re-check set on keys `m9|g4|select|s<k>|<part>|<j>` (the selection probe). Pass: the selected state is the final state, which becomes a
  certification. Fail: the selected state is the latest certification. Nothing else is ever compared, so there are at most two candidates and one
  binary test.
- **The selected state** is what the close audit measures, what the registered outcome is computed from, and what the next session resumes from.
- **Close audit on fresh keys** `m9|g4|audit|s<k>|<sticky or unperturbed>|<landing>|<j>`, never used by any probe: at every registered landing
  behind the selected pointer plus the first beyond it, 20 sticky + 20 unperturbed + 1 deterministic; tick 0: 20 sticky + 1 deterministic. D
  (10 of 20 sticky at the landing and every later one) decides; R with g2-s1's reused tape bar (B = 15 at 2,128, 10 elsewhere; unpaired, from
  p_hat) is reported. Because the selection used only probe keys, the audit measures the selected state without the winner's curse of a
  best-of-many choice; the remaining optimism is that a certification can itself be a lucky pass (a 20-episode test at p = 0.4 passes about
  25 % of the time).
- The pairing with g3's audits and the tape (identical keys) is lost; question 7 offers a paired audit as an extra.

### 3.7 Probe budget

All probe wall (init, attempts, regression, selection) counts against **30 % of the training phase's wall cap, 1,440 s of 4,800 s** (s5's
attempts used 1,094 s, 22.8 %; s6's 188 s). Rules: the selection probe's worst case (about 120 s) is reserved from the start; a regression probe
has priority over an attempt at the same boundary; a probe that cannot fit its worst case (about 80 s for an attempt with re-checks) is deferred
and logged `deferred_budget`; spacing and deferral counts are unchanged by it. Probes pause training as in g3 (the 4 playing slots parked, 6 probe
slots).

### 3.8 The sticky versus unperturbed gap

Evidence (`out/warmstart_and_sticky.json`; close audits, sticky / unperturbed clears of 20; the action keys of the two modes differ, so the
comparison is unpaired):

| landing | s1 | s2 | s3 | s4 | s5 | s6 | pooled s2-s5 | Fisher two-sided |
| ---: | --- | --- | --- | --- | --- | --- | --- | ---: |
| 2,128 | 8 / 10 | 13 / 13 | 15 / 13 | 14 / 17 | 17 / 17 | 1 / 4 | 59 / 80 vs 60 / 80 | 1.00 |
| 1,966 | - | 3 / 4 | 9 / 6 | 13 / 8 | 12 / 5 | 0 / 0 | 37 / 80 vs 23 / 80 | 0.033 |
| 1,694 | - | - | - | - | 10 / 5 | 2 / 1 | 10 / 20 vs 5 / 20 (s5) | 0.19 |

- There is no gap on the short final segment (2,128, 198 ticks to the end) and a gap on the longer ones (1,966: 360 ticks; 1,694: 632 ticks).
  The deterministic episode cleared from 2,128 in s5 and never from 1,966 or 1,694.
- On the trunk states the s5 final policy's own probability of repeating the previous word is 0.006-0.015 per tick (uniform: 0.014), while the
  agent's route holds its word on 74-86 % of ticks; sticky actions raise the repetition to about 0.26. Its entropy there is 75-88 % of the maximum.
  This is consistent with, and does not establish, the reading that the policy relies on the sticky mechanism's persistence for held inputs on
  long segments (trunk states are the policy's own states only at the handover).
- Proposal: keep g4 a one-change line: training and the deciding audit stay sticky (p = 0.25). The unperturbed and deterministic audits are
  reported every session. The final claim requires both modes (section 3.9). If the unperturbed count at the line's deepest landing stays below
  10 of 20 while sticky passes, at the k = 4 review or at END_SUCCESS, a separate "unperturbed consolidation" (for example a registered share of
  training episodes at p = 0) is proposed then (question 12).

### 3.9 Landing scale, budget and milestones

**Landing scale** (`out/landings.json`): the registered rule "first tick of every grounded segment of the shared trunk", applied to the recorded
replies of the agent's own rd4 route (`ground_air_state`), reproduces the six registered landings exactly and gives ten earlier ones:

**2,128 · 1,966 · 1,694 · 1,473 · 1,369 · 1,248 · 1,192 · 1,061 · 841 · 753 · 682 · 508 · 375 · 269 · 174 · 58**, then tick 0.

(`docs/rl_m9_policy_proposal_2026-10-03.md` section 5.5 speaks of "22 earlier landings"; its section 1.1 counts 22 alternating segments before
1,248, which is consistent with 10 grounded-segment starts plus airborne segments. The preparation registers the list with a test against the
trace and the six; question 11.)

**Budget, rebased on D_start = 1,694** at the pace of g3's own budget (from 2,300 to 1,694 by k = 6: about 100 ticks of depth per counted
session; the line actually reached 1,694 at k = 5): at every even counted session k, D_k must be at or before **M_k = the latest landing at or
before D_start - 100 k**:

| counted session k | 2 | 4 | 6 | 8 |
| --- | --- | --- | --- | --- |
| M_k (warm start, D_start 1,694) | 1,473 (the crossing) | 1,248 | 1,061 | 841 |
| M_k (a fresh start; as g3) | 2,128 | 1,966 | 1,694 | 1,473 |

**The path to the final criterion.** Tick 0 lies 1,694 ticks back: about 17 counted sessions at the g3 pace, so the line is capped at 8 (END_CAP)
with a written review to renew it. When the line's D reaches tick 0 (at least 10 of 20 sticky clears from tick 0 and from every landing),
END_SUCCESS makes the **final-claim gate** proposable: `rl/m9_claim.py` (defined in g1, never run) from the tick-0 reset with no prefix, at least
50 of 100 unperturbed and 50 of 100 sticky clears, sticky at least 25 above the open-loop tape on the same keys, every clear replayed exactly from
tick 0. The lineage stays rd4's 2,326-tick trunk; a shorter route (sd2's 1,885) is a later, separate question.

### 3.10 Session envelope

As g3 (80-minute training wall, 3,072,000 transitions, 145-minute session cap, audit 1,200 s, verification 600 s), plus an init phase (cap 300 s,
1,500,000 ticks) and a selection phase (cap 300 s, 1,500,000 ticks), both inside the 145-minute cap; the probe wall inside training is bounded by
section 3.7. The close compares only the trees the session reads (rd4's routes, g3-s5's state, g4's predecessors); the post-run tool re-hashes
every increment (question 15). The audit grows with depth (about 41 episodes per landing; at 13 landings roughly 850 s or more): the audit cap
is revisited at the k = 4 review.

## 4. Outcomes and line-ending conditions

### 4.1 Per-session outcome `m9_g4_session_rule_v1` (first match wins)

D_ref = the line's depth before the session (D_start = 1,694 for the first warm-start session; the previous counted session's D afterwards).

| outcome | condition |
| --- | --- |
| **INVALID** | any integrity failure: an inexact replay of a counted clear, a pin or executable drift, a changed protected tree, a write outside the session tree, an attempt inside its spacing, a move without a passing strip test and re-check set, a rollback to a state that is not a recorded certification, a selection that does not follow `m9_g4_select_v1`, a probe started beyond its budget, the warm-start input not at its pins |
| **INCOMPLETE** | P1, P2 or the tape drift check not passed; the init probe not completed; training ended before a valid end (valid: wall cap, native-tick cap, transition cap, REGRESSION_LIMIT); the selection probe not completed; the close audit incomplete at a landing D needs; an unverified audit clear that could change D |
| **PROGRESS** | D_k earlier than D_ref |
| **HELD** | D_k = D_ref |
| **REGRESSED** | D_k later than D_ref, or none while D_ref is a landing |
| **NULL** | D_k none and D_ref none (a fresh line only) |

Reported, never deciding: R_k, the unperturbed and deterministic audits, tick 0, init outcome, certifications, triggers, regression probes,
rollbacks, the selection, the probe share, the trigger-to-test gaps.

### 4.2 Line outcome `m9_g4_line_rule_v1` (checked at every session close, in this order)

k counts the sessions whose training reached at least half its wall or ended at a valid end; an INCOMPLETE session below that does not count.

| # | line outcome | condition | consequence |
| ---: | --- | --- | --- |
| 1 | **SUSPENDED** | the session is INVALID | repair and a new approval before any next session |
| 2 | **SUSPENDED** | two consecutive sessions INCOMPLETE | a written review before any next session |
| 3 | **END_SUCCESS** | D_k = 0 (tick 0) | the line ends; the final-claim gate becomes proposable |
| 4 | **END_REGRESSION** | two consecutive counted sessions REGRESSED | the line ends |
| 5 | **END_BUDGET_1473** | k = 2 and D_2 later than 1,473 | the line ends |
| 6 | **END_BUDGET_1248** | k = 4 and D_4 later than 1,248 | the line ends |
| 7 | **END_BUDGET_1061** | k = 6 and D_6 later than 1,061 | the line ends |
| 8 | **END_BUDGET_841** | k = 8 and D_8 later than 841 | the line ends |
| 9 | **END_NO_PROGRESS** | k >= 4 and D_k not earlier than D_{k-2} | the line ends |
| 10 | **END_CAP** | k = 8 without END_SUCCESS | the line ends; renewal only by a written review and a new decision |
| 11 | **CONTINUE** | none of the above | session k + 1 is proposable, with its own approval |

(For a fresh-start line, rows 5-8 read END_BUDGET_2128 / 1966 / 1694 / 1473 at k = 2 / 4 / 6 / 8.) Nothing follows any outcome automatically.

### 4.3 Within-session events (none ends the line by itself)

| event | effect |
| --- | --- |
| INIT_KEPT / INIT_STEPPED_FORWARD (n strips) / INIT_AT_TAU0 | sets the starting pointer; reported |
| MOVED, FAILED_STRIP, BLOCKED_BY_RECHECK, INTERRUPTED, deferred_trigger | as g3 (re-check set of section 3.4) |
| deferred_budget | an attempt or regression probe postponed by the 30 % cap |
| TRIGGER, REGRESSION_PROBE_PASSED (a certification) / ROLLBACK_1, ROLLBACK_2 | section 3.5 |
| REGRESSION_LIMIT | a third confirmed regression: training ends (a valid end); the session counts |
| SELECTED_FINAL / SELECTED_CERTIFIED_<n> | section 3.6 |

### 4.4 What the first session's outcomes would mean

- **PROGRESS or HELD with no rollback and a low horizon share:** the warm start under N1 kept the competence s6 lost under v2 from the same state.
  Consistent with the attractor hypothesis; n = 1, not a proof.
- **Rollbacks, then HELD:** a regression still occurred under N1 and the safety net held the line's state; the attractor was not the only mechanism.
- **REGRESSED despite the selection:** the certification was a lucky pass or the regression came before any certification after the init; read
  the trigger and probe records before any next session.
- **INIT_STEPPED_FORWARD:** the inherited pointer was not reproducible on fresh keys; the line starts later than 1,780 at no cost to its rules.
- **A first REGRESSED by one landing (D_1 = 1,966):** D_start = 1,694 was measured at exactly the bar (10 of 20), so an unchanged policy measures
  1,694 or 1,966 with roughly even odds on fresh keys. One REGRESSED session does not end the line (END_REGRESSION needs two in a row).

## 5. Reuse and preparation plan

### 5.1 Reused unchanged (imported, never edited)

`rl/m9_contract.py`, `m9_g2_contract.py`, `m9_g3_contract.py` (values read by import); `m9_curriculum.py`; `m9_g3_frontier.Frontier`, `strip_start`
and the spacing (subclassed); `m9_g2_arena`, `m9_pool`, `m9_worker`, `m9_sticky`, `m9_obs`, `m9_lineages`; `m9_g2_probe.ProbeRunner` (its known
`no_episode` race stays benign); the job builders of `m9_g3_probe` (new keys); `m9_g2_resume` helpers (member digests, counters, continuity);
`m9_eval_policy.PinnedPolicy`; `m9_verify`; `m9_claim` (the final gate); `rl/tools/runs_backup.py`; `m8_rd_session` (readiness, coverage, trees);
the g3 snapshot and predecessor-discovery patterns; `m9_g2_stub` for the e2e world.

### 5.2 New code (`rl/m9_g4_*.py`)

| module | content |
| --- | --- |
| `m9_g4_contract.py` | the N1 contract by value and fingerprint; line contract `m9_g4_line_contract_v1`; keys `m9|g4|...`; the landing scale; the budget; caps; the probe budget |
| `m9_g4_vec.py` | the EpisodeCtx subclass: N1 reward, terminal horizon |
| `m9_g4_frontier.py` | init probe rule, re-check set, certification and rollback state over g3's frontier; `replay_history` extended to init, rollbacks and selection |
| `m9_g4_train.py` | the callback: trigger statistic, regression probe, rollback, certification checkpoints, probe budget, REGRESSION_LIMIT, the selection probe |
| `m9_g4_probe.py` | init, regression and selection jobs on g4 keys; the fresh-keys audit jobs |
| `m9_g4_rule.py` | `m9_g4_session_rule_v1`, `m9_g4_line_rule_v1`, `m9_g4_select_v1`, self-tests |
| `m9_g4_run.py`, `m9_g4_session.py` | the session (open with the cross-line warm-start import by pin and its refusals; init; train; selection; audit; verification; close); `status`, `preflight`, `approval-template`, `run`, `verify-run`, `report`, `check-results-record`, `fingerprint`, all `--session k` required, generic in k from the start |
| `m9_g4_snapshot.py`, `m9_g4_report.py` | as g3, generic in k |
| `m9_g4_tests.py` | unit (the N1 neutrality and clear-identity facts, the terminal horizon, the init stepping, the trigger, rollback restore and limit, selection, budget, rules, the landing-scale test, git and progression gates on temporary layouts) and e2e on the stub world with forced regressions and a failing selection probe |

### 5.3 New tools (`tools/m9_g4/`, tracked, every tool `--session k` for any k >= 1)

From the sd2 model: `launch_detached.ps1` (HEAD check), `check_launch.py`, `wait_session.py`, `write_approval.py`, `three_passes.py`,
`copy_launch_evidence.py`, `post_run_checks.py` **with the base-backup classify-and-skip fix and its six tests** (`docs/rl_m8_sd2_review_2026-10-13.md`
section 1.4), `machine_sampler.py`, `independent_increment_check.ps1`. Each tool names the increment suffix it expects (`_incr_m9_g4_s<k>`).

### 5.4 Launch path and names (`docs/rl_by_hand_session_checklist.md` conventions)

| item | name |
| --- | --- |
| proposal / decisions / preparation records | `docs/rl_m9_g4_proposal_2026-10-13.md` (this); `docs/rl_m9_g4_decisions_<date>.md`; `docs/rl_m9_g4_prep_<date>.md` with its launch section |
| code, fingerprint | `rl/m9_g4_*.py` + `tools/m9_g4/*`; fingerprint over both, printed by `python -B -X utf8 rl/m9_g4_session.py fingerprint` |
| run tree | `runs/m9_g4/s<k>/` |
| logs | Part B `logs/m9_g4_s<k>_run/partB/` (as sd2) or `logs/m9_g4_s<k>_prep/` (as g3), fixed by the preparation; launch and post-run `logs/m9_g4_s<k>_run/` |
| snapshot / increment | `D:/BattleShip_source_snapshots/<date>_m9_g4_s<k>`; `D:/BattleShip_runs_backup/<date>_incr_m9_g4_s<k>` (exactly one per session) |
| approval / results | `docs/rl_m9_g4_s<k>_approval.json`; `docs/rl_m9_g4_s<k>_results_<YYYY-MM-DD>.md`, first line `# M9-g4-s<k> results (<YYYY-MM-DD>)`, a `## ` section, final newline, checked by `check-results-record` |
| date | one date for everything dated: the local date when Part B starts |

Part B for a g4 session: B0 (hashes, clean tree, fingerprint, LF), B1 (the g4 three passes, then every existing suite: g3, g2, g1, g1 evaluation,
rd1-rd4, sd1, sd2 units and e2e, all rule self-tests; g1 stays 62 / 63 with only `identity_names_every_registered_pin`, its count of unlisted
`rl/m9_*.py` files grows with g4), B2 (`approval-template` digests), B3 / B5 / B6 (dry-run preflight refusing solely for the approval), B4
(independent re-hash of the protected trees, including `runs/m9_g3/s5` against `2026-10-09_incr_m9_g3_s5`), B7 (budget and the computed line
consequence), B8 / B9 (machine, one interpreter), the authorisation file; Part C snapshot, approval, the full preflight once, launch, the
two-minute check, wait; Part D verify-run, evidence copy, the increment, post-run checks, the results record, commit.

### 5.5 Preparation effort and order

1. The owner's answers to section 7, recorded in `docs/rl_m9_g4_decisions_<date>.md` (one short session).
2. Preparation (two or three Opus / Fable sessions): the modules, tests and tools above; the landing-scale registration; the tape at the earlier
   landings deferred to the first session that needs it (question 16). g3's unit passes took 15-35 minutes on this machine and its e2e 15-17; a
   three-pass round about 2 hours.
3. An independent pre-launch review of the new launch path (it caught a defect at g3-s2, g3-s3 and sd2).
4. Part B and the launch on a different day (Sonnet-class for scoped execution); about 3-4.5 h of Part B, 2-2.5 h of session, 1-3 h after it.

## 6. Risks

| # | risk | mitigation |
| ---: | --- | --- |
| 1 | the attractor is not the (only) mechanism: N1 removes the incentive but the policy still collapses (forgetting, critic dynamics, entropy) | rollback to certified states; keep-best; END_REGRESSION; the s6 comparison in the records |
| 2 | N1's clear-versus-fall contrast is 22 % smaller: careful play may be learned more slowly, falls may rise | reported per session; the budget ends a slow line; N5 is the alternative with an unchanged contrast but an optimistic warm-start critic |
| 3 | the warm-start critic is pessimistic on failures (+2 on falls) | measured offline as a milder and opposite-signed transient than s6's; the trigger watches the first windows |
| 4 | rollback and selection are new code paths (model, Adam and frontier restore mid-training) | stub e2e with forced regressions; verify-run rebuilds every certification and rollback; the pre-launch review; question 5 allows keep-best only |
| 5 | 20-episode probes are noisy: a certification can be a lucky pass, a sound state can fail a probe | registered once; the fresh-keys audit decides the outcome; at most two rollbacks |
| 6 | the absolute NR trigger may fire more often once the rehearsal region spans the crossing (a lower base rate) | a false alarm costs one probe (about 60-75 s) and re-arms; the 30 % cap bounds the total; reported per session |
| 7 | the budget pace (100 ticks per session) may be too fast for the crossing (1,520-1,693, the up-B flight and the platform phase) | END_BUDGET_1473 at k = 2 is an honest stop; question 9 offers a later first check |
| 8 | the sticky / unperturbed gap widens on longer segments and blocks the final claim | reported every session; a later, separate consolidation line |
| 9 | by-hand operation: each session is a full day; operator slips (increment names, `--source`, pinned documents) | `tools/m9_g4/` checks and refusals; the checklist; question 14 |
| 10 | the close phase and the audit grow with every protected tree and landing | question 15; the audit cap revisited at k = 4 |
| 11 | n = 1 per arm: no statistical attribution of any outcome to the contract | stated in every record's scope label |
| 12 | machine memory events (`node` processes of 17-46 GB were seen) end a session INCOMPLETE | the checklist's machine preparation; readiness refusals are stops |

## 7. Open questions for the owner

1. **The contract change.** Options: (a) N1, fall -1 and horizon terminal -1; (b) N5, step cost 0.005 and horizon terminal -5; (c) F1, fall -1
   only, horizon left a truncation (one value, but neutral only if the critic bootstraps the horizon near -1); (d) H5, horizon terminal -5 only
   (halves the threshold); (e) keep v2. Sub-question: register P as -1.0 (readable; timing effect at most 0.001) or the exact 0.999. **Recommend
   (a) with -1.0**: with (b), the only options that remove the threshold without rewarding an earlier failure; (a) alone also leaves every
   clear's return, the step cost and every PPO value unchanged, and starts the warm start with a pessimistic rather than optimistic critic.
2. **Warm or fresh.** (a) warm start from s5 as the g4 line; (b) fresh start as the g4 line; (c) both, the fresh one as a separate control line
   later. **Recommend (a)**, with (c) only if g4-s1 collapses or a from-scratch claim is wanted.
3. **Warm-start optimizer.** (a) weights and Adam state bit for bit (as every g3 resume; closest to the s6 contrast); (b) weights only, fresh Adam.
   **Recommend (a).**
4. **Frontier at session start.** (a) verify the carried pointer, step forward on failure (section 3.4); (b) set it from a fresh landing-chain
   depth measurement (D_0 at 1,694 is a coin flip at 10 of 20); (c) scan backward while strip tests pass; (d) no probe. **Recommend (a).** Also
   confirm the capped re-check set (two nearest landings behind plus 2,128) for every guarding test.
5. **Regression handling.** (a) rollback within the session (limit two, then REGRESSION_LIMIT) plus keep-best selection at the end; (b) keep-best
   only (simpler code; the time after a collapse is lost); (c) rollback only. Sub-question: should a REGRESSED session's state be skipped by the
   next session (line-level keep-best)? **Recommend (a) without line-level keep-best**; if preparation must be cut, (b).
6. **The trigger.** (a) NR < 0.40 over the last 100 near / rehearsal episodes, checked every 50 (0 firings in s1-s5, 524 s in s6); (b) the same
   with two consecutive checks at 0.35 (689 s); (c) a drawdown rule (fired in s3 and s4, late in s6); (d) a horizon-share rule (fired in s3-s5);
   (e) periodic probes. **Recommend (a).**
7. **Audit keys.** (a) fresh keys per session; (b) the g2 `reach` family, paired with g3's audits and the tape; (c) both (about 4 more minutes).
   **Recommend (a)**, following your principle; (c) if the comparison with s1-s6 matters for the video.
8. **Probe budget.** Confirm 30 % of the training wall cap (1,440 s), all probes counted, the selection probe reserved, regression before
   attempts. **Recommend as written.**
9. **Budget pace.** (a) 100 ticks of depth per counted session from D_start = 1,694, checks at k = 2, 4, 6, 8 (1,473, 1,248, 1,061, 841); (b) one
   landing per two sessions (1,473, 1,369, 1,248, 1,192); (c) as (a) with the first check at k = 3 for the crossing. **Recommend (a).**
10. **END_SUCCESS and the cap.** (a) END_SUCCESS at tick 0 and END_CAP at k = 8, renewable by a written review; (b) END_SUCCESS at 1,248 and a
    new line for the right side; (c) END_SUCCESS at 1,473 as g3. **Recommend (a).**
11. **The landing scale.** (a) register the 16 landings plus tick 0 given by the generic rule (it reproduces the six); (b) keep the six and decide
    later. **Recommend (a)**, with the test against the trace.
12. **Sticky versus unperturbed.** (a) one change only: sticky training and deciding audit, unperturbed reported, both required by the final
    claim, a consolidation line proposed if the gap persists at the k = 4 review; (b) a registered share of unperturbed training episodes from
    g4-s1. **Recommend (a).**
13. **Session length.** (a) 80 minutes and 3,072,000 transitions (closest to s6); (b) longer sessions (for example 160 minutes inside a raised cap)
    to amortise Part B. **Recommend (a)** for s1, revisited at the k = 4 review.
14. **Part B per session.** (a) three passes every session (current practice); (b) three passes when the fingerprint changed, one otherwise.
    **Recommend (a)** for g4-s1 and s2, then (b) if both ran clean.
15. **Protected trees at the close.** (a) all trees (g3's close took 344-563 s with 9-12 trees, against a 300 s figure); (b) the trees the
    session reads, with every increment re-hashed by the post-run tool. **Recommend (b).**
16. **Tape below 1,248 and at tick 0.** (a) measure once, in the first session whose audit needs it (reported R only); (b) never (D-only line).
    **Recommend (a).**
17. **The g3 checkpoint evaluation** (stop review section 5, 4-8 M ticks). (a) skip; (b) run before g4. **Recommend (a)**: the init probe and
    the s6 contrast give part of its information, and it cannot change g3's outcome.
18. **Priority.** (a) g4 next; (b) the speed line's v5 offline evaluation first; (c) the generalisation audit first. **Recommend (a)** if the
    November goal is the tick-0 policy for the video, (b) if a faster single clear matters more.
