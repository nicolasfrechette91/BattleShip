# Decisions (2026-10-13)

## General
- The speed-discovery line is paused after sd2 (my decision, following docs/rl_m8_sd2_review_2026-10-13.md). If it continues, a v5 selection proposal with an offline evaluation comes first.
- November order: the second-character line (Donkey Kong) first; g4 on Mario afterwards.

## g4 proposal (docs/rl_m9_g4_proposal_2026-10-13.md), questions 1–18
1. Contract: N1, with fall and horizon both at −1.0.
2. Warm start from s5's final state; a fresh-start control only if g4-s1 collapses.
3. Carry the Adam state bit for bit; report the first updates' KL and explained variance.
4. Frontier at session start: verify the carried pointer and step forward only, with re-checks capped at three landings.
5. Rollback plus keep-best (keep-best alone only if preparation must be cut).
6. Trigger: clear rate below 0.40 over 100 episodes, checked every 50.
7. Audit keys: fresh.
8. Probe budget: 30 % as written, selection probe reserved, regression probes before attempts.
9. Budget pace: 100 ticks per session.
10. END_SUCCESS at tick 0, line capped at 8 sessions with a written review to renew.
11. Register the full landing scale (16 landings and tick 0).
12. One contract change only; the sticky gap is reported, not trained on.
13. Session length 80 min for s1.
14. Part B: three passes for s1–s2, then one pass if both ran clean.
15. Protected trees at the close: only those the session reads, PROVIDED the post-run independent re-hash still covers every increment.
16. Tape below 1,248 and at tick 0: measure when first needed.
17. The g3 checkpoint evaluation: skip.
18. Priority: after the second-character line (see General).

## Generalization audit (docs/rl_generalization_audit_2026-10-13.md), questions 1–15
1. First character: Donkey Kong.
2. Approved in principle for November: SSB64_RL_FKIND in port/rl/rl_boot.cpp (default off, range-checked, no decomp edit), and the optional status fields reported only when it is set.
3. The registered executable is archived in D:/BattleShip_exe_archive/2026-10-13_30a3913b/ (this session).
4. The decomp edits from commit e4bc8e24c outside #ifdef PORT (sc1pbonusstage.c:13-14 and :381): fix in November behind #ifdef PORT, and check that the PORT build's executable hash is unchanged.
5. The census rule is not retroactive: frozen registered rules and identity samples (C2, C3) stand, with disclosure. For new lines, landing ticks derived at P1 from the agent's own route by a registered generic rule are acceptable, with no tick literal in code.
6. E6: dropped for new stages.
7. CELL_SIZE: keep 300 for Donkey Kong; revisit if his census shows problems.
8. Milestones for new stages: target levels and the clear only.
9. Spatial capacity: raise only when a chosen character needs it (Donkey Kong fits).
10. Module layout: one generic, task-parameterised module family.
11. Names: task id ssb64_us_donkey_kong_btt_v1, stage btt_donkey_kong; run trees and increments carry a character segment.
12. Line endings: until a .gitattributes fix (November, with a check), clone with core.autocrlf=false.
13. Order: the character line first.
14. Horizon: keep 3,600 ticks until the new stage's first clear, then decide.
15. Replay browser: read the top-level task block; overrides only for rd1–rd4.

## Disclosure for the video
- The search's E6 eligibility rule (rd2 to sd2) used a hard-coded copy of Mario's floor table and Mario's jump heights to prune cells too low to recover from. It is not a route or waypoint, and no TAS or human input was used, but it is stage-specific knowledge and should be stated.
