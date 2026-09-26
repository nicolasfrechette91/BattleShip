"""M7m decision rule and analysis (pure: reads evaluation records, never runs the game).

The rule is docs/rl_sweep_consolidation_m7m_decision_rule.json, written once by rule_document() (frozen before any
training, the pilot included; its sha256 is pinned in the campaign manifest) and applied once to the complete n = 3
paired campaign. Episode facts reuse the M7l definitions (rl/m7l_analysis.py: R, L, static targets, deterministic
collapse), parameterised by this rule's own registered values.
"""
from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import m7l_analysis as la
import m7m_anchor as ma

RL_DIR = Path(__file__).resolve().parent
REPO_ROOT = RL_DIR.parent
RULE_DOC = REPO_ROOT / "docs" / "rl_sweep_consolidation_m7m_decision_rule.json"
RULE_SCHEMA = "m7m_decision_rule_v1"
ARMS = ("E", "K")
OUTCOMES = ("no_decision", "consolidated", "r_gain_with_static_loss", "reproduced_not_consolidated",
            "curriculum_progress_without_tick0_gain", "null")


def rule_document() -> Dict[str, Any]:
    return {
        "schema": RULE_SCHEMA, "milestone": "M7m",
        "design": "docs/rl_sweep_consolidation_m7m_design.md (section 7), approved by the user 2026-09-26",
        "question": ("After +1,536,000 policy-controlled transitions from the same Phase K reward-v2 checkpoint, does "
                     "training with anchored backward starts cut from the one registered sweep (arm E) make normal "
                     "tick-0 play break all seven right targets by consumed tick 2699 more often than the same training "
                     "with tick-0 starts only (arm K), without losing static targets?"),
        "frozen": "before any training (the integration pilot included); applied once to the complete n = 3 paired "
                  "campaign; never re-decided; the pilot is never an input",
        "parameters": {
            "seeds": [0, 1, 2], "episodes_per_seed": 100, "moving_target_id": ma.MOVING_TARGET_ID,
            "right_ids": list(ma.RIGHT_IDS), "static_right_ids": list(ma.STATIC_RIGHT_IDS), "left_ids": list(ma.LEFT_IDS),
            "deadline_consumed_tick": ma.DEADLINE_CONSUMED_TICK, "L_static_right_min": 5, "collapse_share_min": "1/2",
            "consolidated_R_min": 5, "consolidated_pairs_min": 2, "static_loss_max_per_episode": "1/2",
            "reproduced_R_min": 1, "reproduced_seeds_min": 2, "progress_window_index": len(ma.WINDOWS) - 1,
            "progress_runs_min": 2, "evaluation_reruns_max": 1,
        },
        "primary_sample": ("per run, the final checkpoint's stochastic evaluation: exactly the 100 counted episodes of "
                           "the registered Phase K protocol (seed 12345, frozen VecNormalize statistics, stochastic "
                           "actions, 5 workers with standby, btt_eval_metrics_v1 with SSB64_RL_TARGET_DIAG=1), every "
                           "one a normal tick-0 start (no prefix label, input_tick 0 reset, verified by "
                           "m7h_verify.verify_eval_tick0); episodes beyond the 100th are never counted"),
        "definitions": {
            "R": "episodes whose btt_eval_metrics_v1 first-break table holds all seven right targets {0,2,3,4,5,7,9}, "
                 "the latest at consumed tick <= 2699 (a later fall or horizon end does not undo it)",
            "S": "static targets broken, summed over the 100 episodes (every native target except ID 2)",
            "L": "target 2 broken at consumed tick <= 2699 and >= 5 static right targets broken (reported)",
            "seven_right": "all seven right targets broken at any tick (reported)",
            "collapse": "M7e: longest run of one joint action / episode length of the deterministic play >= 1/2",
            "verified_clear": "a native clear whose exact native replay reproduces the clear (m7g_k_run.verify_clears_in)",
        },
        "denominators": ("R_j and S_j per run over its 100 counted final stochastic episodes; pooled static means over "
                         "300 episodes per arm; exact rational arithmetic, never rounded"),
        "ties": ("R_E > R_K and sum R_E > sum R_K are strict (equal counts are no gain); every >= threshold and the "
                 "static guard are inclusive"),
        "incomplete_evaluations": ("a label with fewer than its registered episodes, a lifecycle-failure row, an "
                                   "unclean metrics record or a failed tick-0 / row verification is moved aside "
                                   "(preserved) and re-run once from the same checkpoint (evaluation only); still "
                                   "incomplete or unverified -> gate 0 (no_decision)"),
        "gates": [
            {"gate": 0, "outcome": "no_decision",
             "condition": "any integrity failure: a run not verified (training verification, warm-start lineage, "
                          "continuation, policy-only accounting), manifest drift, a final or curve label not complete "
                          "and verified after its one re-run, a counted episode that is not a tick-0 start, or a native "
                          "clear candidate that fails its native replay"},
            {"gate": 1, "outcome": "consolidated",
             "condition": "(1a) #{j : R_E_j >= 5 and R_E_j > R_K_j} >= 2 AND (1b) S_E / 300 >= S_K / 300 - 1/2"},
            {"gate": "1'", "outcome": "r_gain_with_static_loss", "condition": "(1a) holds and (1b) fails"},
            {"gate": 2, "outcome": "reproduced_not_consolidated",
             "condition": "#{j : R_E_j >= 1} >= 2 AND sum_j R_E_j > sum_j R_K_j"},
            {"gate": 3, "outcome": "curriculum_progress_without_tick0_gain",
             "condition": "the E schedule reached the final window [1, 60] (window index 8) or completed in >= 2 E runs"},
            {"gate": 4, "outcome": "null", "condition": "none of the above"},
        ],
        "precedence": "gate 0, then 1, 1', 2, 3, 4: the first that holds is the outcome",
        "responses": {
            "no_decision": "report the integrity failure; no conclusion",
            "consolidated": "the anchored backward starts consolidated this sweep into tick-0 play (one anchor)",
            "r_gain_with_static_loss": "tick-0 sweeps increased, but at a static-target cost beyond the guard",
            "reproduced_not_consolidated": "the sweep reappears in tick-0 play but below the consolidation threshold",
            "curriculum_progress_without_tick0_gain": ("the schedule advanced through its windows, but normal tick-0 "
                                                       "play shows no registered gain; window progress is a curriculum "
                                                       "diagnostic, not evidence that the earlier behaviour was learned"),
            "null": "no registered effect of the anchored starts at this budget",
        },
        "interpretation": {
            "pointer": ("pointer movement is a curriculum-progress diagnostic only: a block can pass through block-to-"
                        "block variation or motion inherited from the anchor prefix; reaching an earlier window is never "
                        "reported as proof that the earlier behaviour was learned"),
            "anchored_successes": ("successes from anchored starts (training) are reported separately from normal "
                                   "tick-0 performance and never enter R"),
            "feasibility": ("F1-F5 are feasibility evidence only; the late-cut target-2 breaks of F5 (cuts 828 and "
                            "837, carried by the anchor's own up-B) do not demonstrate policy initiation of the up-B"),
            "anchor": "the sweep stays a replay-verified M7l training event; one anchor, so no claim about how often "
                      "seeds discover a usable sweep",
            "route": "'right-side sweep before crossing' is a working route hypothesis, not a requirement of a clear",
        },
        "in_flight_outcomes": ("an anchored outcome is counted only toward the block of the window in which its episode "
                               "started, and only while that window is current; episodes that started under an earlier "
                               "window and finish after the pointer moved are logged as stale and never counted; "
                               "lifecycle failures and aborted episodes are logged as excluded; outcomes are ingested "
                               "in parent order (vector step, then environment index) before that step's draws"),
        "reported_never_gating": ["L", "seven_right at any tick", "target-2 breaks and ticks", "falls",
                                  "deterministic collapse", "left entries and left-target breaks", "verified clears",
                                  "pointer progression and blocks", "anchored successes by window (training)",
                                  "tick-0 training sweeps", "prefix replay costs", "curve points"],
    }


def write_rule(path: Path = RULE_DOC) -> str:
    """Write-once: an existing rule must be byte-identical."""
    data = (json.dumps(rule_document(), indent=1) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"{path.name} exists with different content; the rule is frozen")
    else:
        path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def load_rule(path: Path = RULE_DOC) -> Dict[str, Any]:
    raw = Path(path).read_bytes()
    rule = json.loads(raw)
    if rule.get("schema") != RULE_SCHEMA:
        raise ValueError(f"{path}: schema {rule.get('schema')} != {RULE_SCHEMA}")
    if rule != json.loads(json.dumps(rule_document())):
        raise ValueError(f"{path}: differs from the code's rule document")
    rule["_sha256"] = hashlib.sha256(raw).hexdigest()
    return rule


def params(rule: Mapping[str, Any]) -> Dict[str, Any]:
    return la.params(rule)


def decide(inputs: Mapping[str, Any], rule: Mapping[str, Any]) -> Dict[str, Any]:
    """inputs: {"E": {seed: ArmSeed}, "K": {seed: ArmSeed}, "integrity": [..],
    "schedule": {seed: {"window_index": k, "complete": bool}}} (E runs' final schedule state)."""
    P = params(rule)
    seeds = P["seeds"]
    n = int(P["episodes_per_seed"])
    integ = list(inputs.get("integrity") or [])
    E, K = inputs.get("E") or {}, inputs.get("K") or {}
    for s in seeds:
        for arm, d in (("E", E), ("K", K)):
            a = d.get(s)
            if a is None:
                integ.append(f"{arm} s{s}: no final label")
            elif a.n != n:
                integ.append(f"{arm} s{s}: {a.n} counted episodes, not {n}")
    if integ:
        return {"outcome": "no_decision", "gate": 0, "integrity": integ, "primary": None,
                "response": rule["responses"]["no_decision"]}
    RE, RK = {s: E[s].R for s in seeds}, {s: K[s].R for s in seeds}
    pairs = [s for s in seeds if RE[s] >= int(P["consolidated_R_min"]) and RE[s] > RK[s]]
    g1a = len(pairs) >= int(P["consolidated_pairs_min"])
    SE, SK = sum(E[s].S for s in seeds), sum(K[s].S for s in seeds)
    pooled = n * len(seeds)
    g1b = Fraction(SE, pooled) >= Fraction(SK, pooled) - la.frac(P["static_loss_max_per_episode"])
    rep_seeds = [s for s in seeds if RE[s] >= int(P["reproduced_R_min"])]
    g2 = len(rep_seeds) >= int(P["reproduced_seeds_min"]) and sum(RE.values()) > sum(RK.values())
    sched = inputs.get("schedule") or {}
    prog = [s for s in seeds if (sched.get(s) or {}).get("complete")
            or int((sched.get(s) or {}).get("window_index", -1)) >= int(P["progress_window_index"])]
    g3 = len(prog) >= int(P["progress_runs_min"])
    if g1a and g1b:
        outcome, gate = "consolidated", 1
    elif g1a:
        outcome, gate = "r_gain_with_static_loss", "1'"
    elif g2:
        outcome, gate = "reproduced_not_consolidated", 2
    elif g3:
        outcome, gate = "curriculum_progress_without_tick0_gain", 3
    else:
        outcome, gate = "null", 4
    return {"outcome": outcome, "gate": gate, "primary": outcome in ("consolidated",),
            "gates": {"1a": {"R_E": RE, "R_K": RK, "pairs": pairs, "holds": g1a},
                      "1b": {"S_E": SE, "S_K": SK, "pooled_episodes": pooled,
                             "mean_diff": str(Fraction(SE - SK, pooled)), "holds": g1b},
                      "2": {"seeds_R_E_ge_1": rep_seeds, "sum_R_E": sum(RE.values()), "sum_R_K": sum(RK.values()),
                            "holds": g2},
                      "3": {"runs_reaching_final_window_or_complete": prog, "schedule": sched, "holds": g3,
                            "note": rule["interpretation"]["pointer"]}},
            "response": rule["responses"][outcome], "integrity": []}


def _arm(R: int, S: int = 450, n: int = 100) -> la.ArmSeed:
    return la.ArmSeed(n=n, t2=0, S=S, S_right=S, L=0, R=R, T=None, falls=0, native_clears=0, verified_clears=0,
                      stochastic_verified_clears=0, left_entries=0, left_target_episodes=0)


def self_test() -> int:
    rule = json.loads(json.dumps(rule_document()))
    ok = True

    def case(E: Dict[int, la.ArmSeed], K: Dict[int, la.ArmSeed], want: str, sched: Optional[Dict[int, Any]] = None,
             integ: Optional[List[str]] = None) -> None:
        nonlocal ok
        d = decide({"E": E, "K": K, "schedule": sched or {}, "integrity": integ or []}, rule)
        if d["outcome"] != want:
            ok = False
            print("FAIL", want, "->", d["outcome"], d.get("gates"))

    z = {s: _arm(0) for s in (0, 1, 2)}
    case({0: _arm(5), 1: _arm(5), 2: _arm(0)}, {0: _arm(4), 1: _arm(4), 2: _arm(0)}, "consolidated")
    case({0: _arm(5), 1: _arm(5), 2: _arm(0)}, {0: _arm(5), 1: _arm(4), 2: _arm(0)}, "reproduced_not_consolidated")
    case({0: _arm(5, S=400), 1: _arm(5, S=400), 2: _arm(0, S=400)}, {0: _arm(0, S=450), 1: _arm(0, S=450),
                                                                    2: _arm(0, S=450)}, "consolidated")      # -0.5 incl.
    case({0: _arm(5, S=399), 1: _arm(5, S=400), 2: _arm(0, S=400)}, {0: _arm(0, S=450), 1: _arm(0, S=450),
                                                                    2: _arm(0, S=450)}, "r_gain_with_static_loss")
    case({0: _arm(1), 1: _arm(1), 2: _arm(0)}, {0: _arm(1), 1: _arm(1), 2: _arm(0)}, "null")                 # tie
    case({0: _arm(1), 1: _arm(1), 2: _arm(0)}, {0: _arm(1), 1: _arm(0), 2: _arm(0)}, "reproduced_not_consolidated")
    case(z, z, "curriculum_progress_without_tick0_gain", sched={0: {"window_index": 8}, 1: {"complete": True}})
    case(z, z, "null", sched={0: {"window_index": 7}, 1: {"complete": True}})
    case(z, z, "no_decision", integ=["x"])
    case({0: _arm(0, n=99), 1: _arm(0), 2: _arm(0)}, z, "no_decision")
    print("m7m_analysis self-test", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(self_test())
