# Action-hold reachability probe (no training): registered, run and decided 2026-09-27 / 28

Follow-up to [`rl_learning_setup_review_2026-09-27.md`](rl_learning_setup_review_2026-09-27.md) section 6, on the user's
authorisation of a bounded no-training probe. **Action persistence is a hypothesis** about the trained policies' zero
first-event rate; this probe tests only whether temporally correlated *random* Track 1 inputs reach the region the
crossing needs from a normal tick-0 start. No policy, no PPO, no reward or network change, no production action
contract. Nothing was committed, pushed or branched.

Registration (write-once, before any episode): [`rl_action_hold_probe_registration.json`](rl_action_hold_probe_registration.json)
(sha256 `ebae3a66…`). Decision (write-once, applied once): [`rl_action_hold_probe_decision.json`](rl_action_hold_probe_decision.json).
Tool: `rl/tools/action_hold_probe.py` (outside every fingerprinted training set; reuses the M7n prefix-feasibility
staging, the M7n qualified-crossing analyser and the M7f exact stepping replay). Outputs: `runs/probes/action_hold/`
(`results.jsonl`, `run.log`, `run_attempts.jsonl`, `summary.json`, `episodes/kNN/epNNN.json.gz` with every raw reply,
`replays/verdicts.json`).

## 1. What was registered

| item | registered value |
| --- | --- |
| conditions | hold length k in {1, 4, 8, 16}; 100 fresh-process normal tick-0 episodes per k (400 total); horizon 3,600 ticks |
| episode identity | exact list of 400 (k, i, seed, process index); seed = sha256(`action_hold|k|i`)[:8], one NumPy generator per episode, Python-side only |
| sampling | uniform over the 72 Track 1 combinations (`btt_s9_b8_v1`) at each decision boundary: a = integers(0, 72), stick = a // 8, button = a % 8 |
| hold | the native (buttons, stick_x, stick_y) triple submitted for up to k consecutive ticks; stops immediately on native EpisodeEnded or a `btt_native_failure_v1` detection; the last hold clipped to min(k, 3600 - t) |
| recording | every tick is one `step` request; consumed_tick == t and the reply's input_tick == t + 1 are checked on every tick (a violation raises and stops the run); every raw reply kept; canonical native rows give the M7 `native_action_digest`; no hidden steps, no ignored termination, no altered button edges |
| stages (cut 0) | S1 approach: live x <= -1200. S2 over-ledge: live y >= 3000 and x <= -1200. S3: raw `over_wall` entry (`btt_reward_v3.classify_entry` at x = -2100). S4: `btt_qualified_crossing_v1`. S5: target 1, 6 or 8 broken. Elevated step: live y >= 2400 |
| threshold per k | S2 in >= 3 of 100 episodes OR S3 in >= 1 episode, counted only after an exact replay reproduces the stage |
| reading | some k > 1 meets it -> temporally correlated random actions can reach the relevant region under this probe (exploration reachability only; not a qualified crossing, not a learned success, not evidence that PPO will learn a crossing). None meets it -> no foothold under the tested hold lengths; Track 1 crossing controllability is established by the validated fixtures and is not what the probe tests |
| metrics per k | end reasons, targets (mean, histogram, per-target ids), falls, max live y, min live x, elevated episodes / steps, S1-S5, candidates and reproduced candidates, mean reward v2 return, decisions and realised hold lengths, wall time |
| executable / flags | `build-us/Release/BattleShip.exe` sha256 `748dbad9…` (the M7n / M7o executable); `SSB64_RL_NO_RENDER`, `SSB64_RAPHNET_DISABLE`, `SSB64_RL_SPATIAL`, `SSB64_RL_ENTITY`, `SSB64_RL_TARGET_DIAG` = 1 (read-only diagnostics) |
| exclusions | crossing fixtures and TAS not read, replayed or used; no native RNG inspection; no policy |
| stop conditions | any episode exception cancels the pool and exits 1; a running BattleShip process or a refused M7h launch gate before launch; a leftover process after the run |

**Historical k = 1 baseline not reused** (`runs/m7g_k/_eval/random_baseline`, 100 episodes): its diagnostics lacked
`SSB64_RL_SPATIAL` / `SSB64_RL_ENTITY`, it preserved no raw replies and recorded no height, so S2 and elevated steps
cannot be computed from it, and its sampling used SB3's evaluation RNG rather than the registered generators. The
registered k = 1 condition was run instead; the historical figures (3.23 targets, 30 falls, min live x -1650, 0 left
entries) are quoted as context only.

## 2. Run

`python rl/tools/action_hold_probe.py run --workers 3`, 2026-09-28 00:21 -> 00:38 UTC, 17.0 min, one attempt, 400 / 400
episodes, 0 failures, 0 recording-contract violations, 0 leftover processes (at most 3 game processes), launch gate
passed (17.5 GiB available commit, 6.0 GiB physical, 117 GiB disk). Realised holds: every hold of k ticks except the
clipped final hold of the horizon episodes and the hold cut by a native fall (29 / 23 / 31 short holds at k = 4 / 8 / 16,
none at k = 1). `replay` found 0 candidates (nothing met the threshold), so no replay ran (`replays/verdicts.json`).

## 3. Result per hold length (100 episodes each)

| k | clear / fall / horizon | targets mean | targets histogram 0..5 | max live y, max / median | best y with x <= -1200 (near the wall), max / median | episodes with y >= 3000 anywhere | elevated episodes (steps, y >= 2400) | S1 approach | S2 | S3 | S4 | S5 | mean v2 return | decisions / episode |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0 / 29 / 71 | 3.28 | 1, 4, 9, 43, 38, 5 | 4,914 / 917 | 1,807 / -585 | 2 | 4 (230) | 85 | 0 | 0 | 0 | 0 | -1.29 | 3,116 |
| 4 | 0 / 36 / 64 | 3.19 | 1, 7, 11, 40, 35, 6 | 4,673 / 910 | 985 / -644 | 1 | 5 (210) | 80 | 0 | 0 | 0 | 0 | -1.61 | 751 |
| 8 | 0 / 33 / 67 | 3.12 | 4, 4, 9, 46, 33, 4 | 2,570 / 980 | 1,123 / -568 | 0 | 1 (14) | 83 | 0 | 0 | 0 | 0 | -1.61 | 385 |
| 16 | 0 / 31 / 69 | 2.97 | 3, 6, 14, 46, 30, 1 | 3,099 / 765 | 1,292 / -535 | 1 | 5 (93) | 84 | 0 | 0 | 0 | 0 | -1.69 | 195 |

Per-target break counts over 100 episodes (ids; left targets are 1, 6, 8):

| k | 0 | 2 (moving) | 3 | 4 | 5 | 7 | 9 | 1 / 6 / 8 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 95 | 3 | 10 | 84 | 40 | 4 | 92 | 0 / 0 / 0 |
| 4 | 89 | 3 | 14 | 87 | 36 | 4 | 86 | 0 / 0 / 0 |
| 8 | 90 | 1 | 6 | 88 | 36 | 4 | 87 | 0 / 0 / 0 |
| 16 | 85 | 2 | 9 | 87 | 28 | 4 | 82 | 0 / 0 / 0 |

Left region (x < -2100) entries: 0 in all 400 episodes. Min live x: -1650 (the main floor's end at the wall foot) in
every condition. Qualified crossings: 0. Left-target breaks: 0.

The registered k = 1 condition agrees with the historical random baseline where the two are comparable (3.28 vs 3.23
targets, 29 vs 30 falls, min live x -1650 in both, 0 left entries in both).

## 4. Decision (applied once, `rl_action_hold_probe_decision.json`)

No hold length met the threshold: S2 = 0 and S3 = 0 for k = 1, 4, 8 and 16. **Outcome: no foothold under the tested
hold lengths.** By the registered reading, temporally correlated random Track 1 inputs of 4, 8 or 16 ticks do not reach
the over-ledge region or produce a raw over-wall entry from a normal tick-0 start any more than per-tick random inputs
do. Track 1 crossing controllability is not in question: the two validated fixtures established it, and the probe did not
test it.

What the probe measured beyond the rule (descriptive, decides nothing): longer holds reach the wall foot as often
(S1 80-85 %), break slightly fewer targets (3.28 -> 2.97) and fall about as often (29-36); the best height reached near
the wall was 1,807 units at k = 1 and 985-1,292 at k >= 4, all more than 1,700 units below the wall top; the few
episodes above y 3000 (2 / 1 / 0 / 1) were on the right side of the stage (the highest, 4,914, at k = 1).

## 5. What this does and does not establish

- It does **not** support the hypothesis that action persistence alone opens the route for random exploration: with
  uniform random actions, holding for 4-16 ticks changed neither the reach towards the ledge nor the height near the
  wall.
- It says nothing about a *learned* policy under a hold-k contract; a random walk with correlated inputs is not a
  policy, and the crossing needs a takeoff from L1 or the platform far to the right followed by a long airborne traverse,
  which uniform random inputs of any tested hold length did not produce. That limitation of the probe was known when it
  was registered; it is the reason the reading was restricted to reachability.
- It does not reopen crossing controllability (validated fixtures) and does not change the measured findings of the
  review (critic non-anticipation, per-tick switching, v3 first-layer saturation), which stay documented as they are.

## 6. No learning comparison is proposed

The registered condition for proposing a hold-k learning comparison was a pass; the probe did not pass, so none is
proposed and none is designed here. For the record, and because the review's first version under-stated it: a
decision-period change would not have been isolated by keeping every PPO setting. At hold k the same 3,072,000 native
ticks are 3,072,000 / k decisions, the rollout of 5 x 1,024 decisions spans k times more game time, gamma and lambda
per decision stretch the tick horizons by k, the summed k-tick reward changes the per-decision reward scale, and
truncation inside a hold has to be defined. Any future comparison of a decision period would have to choose which of
these time scales it matches (native ticks, decisions, or tick horizons) and would need a control matched on that
choice rather than the M7n runs alone.

## 7. Open items after this probe (not a proposal)

The measured, unresolved items from the review stand: the first left-side event has never occurred in tick-0 play, the
critic does not anticipate breaks, and the v3 first layer is saturated for a cause that has not been isolated. Which of
them to address next, and whether to address any of them before revisiting the route question with a different kind of
probe, is a separate decision.
