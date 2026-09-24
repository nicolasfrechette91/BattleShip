#!/usr/bin/env python3
"""M7g Phase K analysis: the pre-registered decision rule (revision 2) and the reported metrics.

    python rl/m7g_k_run.py analyze          # the report + the recorded decision (and whether gate 6 fires)
    python rl/m7g_k_analysis.py --self-test # every gate and branch on synthetic seed facts, no game

The rule is docs/rl_obs_v2_experiment_proposal_m7g.md section 6 (revision 2). decide() implements it literally:

  6.1 definitions  (per arm a and seed s, at `final` = 3,072,000 transitions)
      clear seed      >= 1 verified clear among the final evaluation's 200 episodes (100 stochastic + 100
                      deterministic); K_a = number of clear seeds
      c_{a,s}         verified clears among the 100 final stochastic episodes / 100
      B_{a,s}         min completion_time_passed over the final evaluation's verified clears
      ceiling seed    >= 1 crossing episode (native position_x < -2100 on a live step) or >= 1 break of target 1, 6 or 8
                      among the 100 final stochastic episodes; X_a = number of ceiling seeds
      x_{a,s}         fraction of the 100 final stochastic episodes that cross or break 1 / 6 / 8
      T_{a,s}         mean targets_broken over the final stochastic episodes that are NOT verified clears (undefined
                      when all 100 are; such a seed is excluded from gate 5)
      D_s             T_{v2,s} - T_{v1,s};  D-bar = unweighted mean of D_s over the seeds where T is defined in both arms
      m(n)            2 when n = 3, 3 when n = 5
      Arithmetic: exact rationals (fractions.Fraction) from the integer counts; thresholds inclusive; floats are used
      only for reporting.

  6.2 gates        0 pre-empts; then 1 -> 7, the first whose condition holds decides (see decide()).

Reward totals never enter a gate. Evaluation-only metrics come from btt_eval_metrics_v1 (rl/m7g_eval_metrics.py).
Standard library at module level; no PyTorch. No native RNG state anywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m7g_k_matrix as km  # noqa: E402  (no torch)

SCHEMA = "battleship_m7g_k_analysis_v1"
RULE_ID = km.DECISION_RULE["rule_id"]
ARMS = km.ARMS
TARGETS_TOTAL = 10
LEFT_TARGETS = (1, 6, 8)
MOVING_TARGET = 2
D_THRESHOLD = Fraction(1, 2)          # +0.5 targets (gate 5)
RATE_THRESHOLD = Fraction(1, 20)      # +0.05 (gates 2b, 4c)
CLEAR_SEED_MARGIN = 2                 # gate 2a
FINAL_LABEL = "final"


def majority(n: int) -> int:
    if n == 3:
        return 2
    if n == 5:
        return 3
    raise ValueError(f"the rule is defined for n = 3 or n = 5 seeds, not {n}")


# -- per (arm, seed) facts -----------------------------------------------------------------------------------------


@dataclass
class SeedFacts:
    """The 6.1 quantities of one arm at one seed, from its final evaluation (counts kept exact)."""

    stochastic_episodes: int = 0
    deterministic_episodes: int = 0
    verified_clears_stochastic: int = 0
    verified_clears_total: int = 0              # stochastic + deterministic
    unverified_clears: int = 0                  # a native clear whose re-validation is missing or failed
    best_clear_time: Optional[int] = None       # min completion_time_passed over verified clears
    best_clear_input_tick: Optional[int] = None  # its completion_input_tick (reported, never compared)
    ceiling_episodes: int = 0                   # stochastic episodes that cross or break 1 / 6 / 8
    incomplete_target_sum: int = 0              # targets over stochastic non-verified-clear episodes
    incomplete_episodes: int = 0
    metric_problems: List[str] = field(default_factory=list)

    @property
    def clear_seed(self) -> bool:
        return self.verified_clears_total >= 1

    @property
    def clear_rate(self) -> Fraction:
        return Fraction(self.verified_clears_stochastic, self.stochastic_episodes or 1)

    @property
    def ceiling_seed(self) -> bool:
        return self.ceiling_episodes >= 1

    @property
    def crossing_rate(self) -> Fraction:
        return Fraction(self.ceiling_episodes, self.stochastic_episodes or 1)

    @property
    def T(self) -> Optional[Fraction]:
        if self.incomplete_episodes == 0:
            return None
        return Fraction(self.incomplete_target_sum, self.incomplete_episodes)

    def as_json(self) -> Dict[str, Any]:
        d = asdict(self)
        d.update(clear_seed=self.clear_seed, clear_rate=float(self.clear_rate), ceiling_seed=self.ceiling_seed,
                 crossing_rate=float(self.crossing_rate), T=None if self.T is None else float(self.T),
                 T_exact=None if self.T is None else f"{self.T.numerator}/{self.T.denominator}")
        return d


def crosses_or_left_break(metrics: Mapping[str, Any]) -> bool:
    return metrics.get("first_left_entry") is not None or bool(set(metrics.get("broken_ids") or []) & set(LEFT_TARGETS))


def seed_facts(stochastic: Sequence[Mapping[str, Any]], deterministic: Sequence[Mapping[str, Any]],
               verified: Mapping[str, bool]) -> SeedFacts:
    """Rows are evaluator rows carrying `eval_metrics`; `verified` maps native_action_digest -> clear re-validated."""
    f = SeedFacts(stochastic_episodes=len(stochastic), deterministic_episodes=len(deterministic))
    for mode, rows in (("stochastic", stochastic), ("deterministic", deterministic)):
        for r in rows:
            m = r.get("eval_metrics")
            if m is None:
                f.metric_problems.append(f"{mode} episode {r.get('episode_id')}: no eval_metrics")
                continue
            if not m.get("ok"):
                f.metric_problems.append(f"{mode} episode {r.get('episode_id')}: eval_metrics not ok "
                                         f"({m.get('target_diag', {}).get('problems')} {m.get('consistency')})")
            cleared = bool(r.get("cleared"))
            ok_clear = cleared and verified.get(str(r.get("native_action_digest"))) is True
            if cleared and not ok_clear:
                f.unverified_clears += 1
            if ok_clear:
                f.verified_clears_total += 1
                t = int(r["completion_time_passed"])
                if f.best_clear_time is None or t < f.best_clear_time:
                    f.best_clear_time = t
                    f.best_clear_input_tick = r.get("completion_input_tick")
            if mode == "stochastic":
                if ok_clear:
                    f.verified_clears_stochastic += 1
                else:
                    f.incomplete_target_sum += int(r["targets_broken"])
                    f.incomplete_episodes += 1
                if crosses_or_left_break(m):
                    f.ceiling_episodes += 1
    return f


# -- the rule -----------------------------------------------------------------------------------------------------------


def _other(a: str) -> str:
    return "v1" if a == "v2" else "v2"


def _mean(xs: Iterable[Fraction]) -> Fraction:
    xs = list(xs)
    return sum(xs, Fraction(0)) / len(xs)


def decide(facts: Mapping[str, Mapping[int, SeedFacts]], *, integrity_problems: Sequence[str] = ()) -> Dict[str, Any]:
    """Revision 2 of the pre-registered rule. `facts[arm][seed]`; the seed set must be {0,1,2} or {0,1,2,3,4} and
    identical in both arms. Returns the deciding gate, its branch, the response and every intermediate quantity."""
    seeds = sorted(facts["v1"])
    if sorted(facts["v2"]) != seeds:
        raise ValueError(f"the arms have different seeds: {sorted(facts['v1'])} vs {sorted(facts['v2'])}")
    if seeds not in ([0, 1, 2], [0, 1, 2, 3, 4]):
        raise ValueError(f"seeds {seeds}: the rule is registered for seeds 0-2 (n = 3) or 0-4 (n = 5, the extension)")
    n = len(seeds)
    m = majority(n)
    q: Dict[str, Any] = {"n": n, "majority": m, "seeds": seeds}
    notes: List[str] = []
    K = {a: sum(1 for s in seeds if facts[a][s].clear_seed) for a in ARMS}
    X = {a: sum(1 for s in seeds if facts[a][s].ceiling_seed) for a in ARMS}
    q.update(K=K, X=X)
    tdef = [s for s in seeds if facts["v1"][s].T is not None and facts["v2"][s].T is not None]
    D = {s: facts["v2"][s].T - facts["v1"][s].T for s in tdef}
    Dbar = _mean(D.values()) if D else None
    q.update(D={s: float(d) for s, d in D.items()}, D_exact={s: f"{d.numerator}/{d.denominator}" for s, d in D.items()},
             D_bar=None if Dbar is None else float(Dbar),
             D_bar_exact=None if Dbar is None else f"{Dbar.numerator}/{Dbar.denominator}", T_defined_seeds=tdef)

    def result(gate: int, branch: str, response: str, **extra: Any) -> Dict[str, Any]:
        return dict({"rule_id": RULE_ID, "gate": gate, "branch": branch, "response": response, "quantities": q,
                     "notes": notes, "extension_required": False}, **extra)

    # gate 0: integrity
    if integrity_problems:
        return result(0, "integrity", "Stop. No gameplay conclusion from either arm. Diagnose, document under "
                      "docs/bugs/, fix, re-verify, then rerun.", problems=list(integrity_problems))
    # gate 1: a reproduced clear in one arm only
    for a in ARMS:
        if K[a] >= m and K[_other(a)] == 0:
            return result(1, f"clear_{a}", ("v2 becomes the Track 1 observation" if a == "v2" else
                                              "v1 stays the default; v2 is recorded as worse on clears")
                          + "; every verified clear and its checkpoint are preserved permanently", preferred=a)
    # gate 2: both arms clear
    if K["v1"] >= 1 and K["v2"] >= 1:
        if K["v2"] - K["v1"] >= CLEAR_SEED_MARGIN:
            return result(2, "a_more_clear_seeds_v2", "v2 preferred (consequences of gate 1)", preferred="v2")
        if K["v1"] - K["v2"] >= CLEAR_SEED_MARGIN:
            return result(2, "a_more_clear_seeds_v1", "v1 preferred (consequences of gate 1)", preferred="v1")
        cdiff = {s: facts["v2"][s].clear_rate - facts["v1"][s].clear_rate for s in seeds}
        cbar = _mean(cdiff.values())
        q.update(clear_rate_diff={s: float(v) for s, v in cdiff.items()}, clear_rate_diff_mean=float(cbar))
        if cbar >= RATE_THRESHOLD and all(v >= 0 for v in cdiff.values()):
            return result(2, "b_clear_rate_v2", "v2 preferred (consequences of gate 1)", preferred="v2")
        if -cbar >= RATE_THRESHOLD and all(v <= 0 for v in cdiff.values()):
            return result(2, "b_clear_rate_v1", "v1 preferred (consequences of gate 1)", preferred="v1")
        both = [s for s in seeds if facts["v1"][s].clear_seed and facts["v2"][s].clear_seed]
        q["both_clear_seeds"] = both
        if both:
            bt = {s: (facts["v2"][s].best_clear_time, facts["v1"][s].best_clear_time) for s in both}
            q["best_clear_times_v2_v1"] = bt
            if all(v2 < v1 for v2, v1 in bt.values()):
                return result(2, "c_faster_v2", "v2 preferred (consequences of gate 1)", preferred="v2")
            if all(v1 < v2 for v2, v1 in bt.values()):
                return result(2, "c_faster_v1", "v1 preferred (consequences of gate 1)", preferred="v1")
        return result(2, "d_tie", "tie: v1 stays the default (the cheaper observation), v2 stays available, and the single "
                      "fastest verified clear of either arm starts the next (clear-time) milestone", preferred=None)
    # gate 3: a single-seed (unreproduced) clear in one arm
    single_clear = [a for a in ARMS if 1 <= K[a] < m and K[_other(a)] == 0]
    if single_clear:
        a = single_clear[0]
        if n == 3:
            return result(3, f"single_seed_clear_{a}", "run the gate-6 extension (seeds 3 and 4, both arms), then "
                          "re-apply the table at n = 5", extension_required=True)
        notes.append(f"gate 3 at n = 5: {a} cleared, not reproduced ({K[a]} of 5 seeds); no adoption on clears; "
                     "clears preserved; continuing with gate 4")
    # gate 4: the ceiling
    for a in ARMS:
        if X[a] >= m and X[_other(a)] == 0:
            return result(4, f"a_ceiling_{a}" if a == "v2" else "b_ceiling_v1",
                          "v2 is adopted for Track 1; the ceiling is shown to be at least partly a perception limitation; "
                          "the frontier curriculum (M7f category D) is redesigned on v2" if a == "v2" else
                          "v1 stays the default; v2 is recorded as worse at the ceiling",
                          preferred=a)
    if X["v1"] >= 1 and X["v2"] >= 1:
        xdiff = {s: facts["v2"][s].crossing_rate - facts["v1"][s].crossing_rate for s in seeds}
        xbar = _mean(xdiff.values())
        q.update(crossing_rate_diff={s: float(v) for s, v in xdiff.items()}, crossing_rate_diff_mean=float(xbar))
        if xbar >= RATE_THRESHOLD and all(v >= 0 for v in xdiff.values()):
            return result(4, "c_crossing_rate_v2", "v2 is adopted for Track 1 (as gate 4a)", preferred="v2")
        if -xbar >= RATE_THRESHOLD and all(v <= 0 for v in xdiff.values()):
            return result(4, "c_crossing_rate_v1", "v1 stays the default; v2 is recorded as worse at the ceiling (as "
                          "gate 4b)", preferred="v1")
        notes.append("ceiling broken by both arms; continuing with gate 5")
    else:
        single_cross = [a for a in ARMS if 1 <= X[a] < m and X[_other(a)] == 0]
        if single_cross:
            a = single_cross[0]
            if n == 3:
                return result(4, f"d_single_seed_crossing_{a}", "run the gate-6 extension (seeds 3 and 4, both arms), "
                              "then re-apply the table at n = 5", extension_required=True)
            notes.append(f"gate 4d at n = 5: crossing not reproduced ({a}, {X[a]} of 5 seeds); continuing with gate 5")
    # gate 5: targets
    if D:
        if all(d > 0 for d in D.values()) and Dbar >= D_THRESHOLD:
            both_cross = any("both arms" in x for x in notes)
            return result(5, "a_targets_v2", "v2 is preferred on objective rank 2 and becomes the base observation of "
                          "the next milestone" + ("" if both_cross else "; the ceiling still needs an exploration "
                                                  "intervention (category D)"), preferred="v2")
        if all(d < 0 for d in D.values()) and Dbar <= -D_THRESHOLD:
            return result(5, "b_targets_v2_worse", "v2 is recorded as worse for this architecture; v1 stays the "
                          "default", preferred="v1")
    # gate 6: seed disagreement -> the one extension (n = 3 only)
    if n == 3 and D and any(d >= D_THRESHOLD for d in D.values()) and any(d <= -D_THRESHOLD for d in D.values()):
        return result(6, "seed_disagreement", "no aggregate claim: train exactly seeds 3 and 4 in both arms at "
                      "3,072,000 transitions with the same evaluation protocol (4 runs, 12,288,000 transitions, 3,940 "
                      "evaluation episodes), then re-apply gates 0-7 once at n = 5", extension_required=True)
    # gate 7
    return result(7, "no_benefit" if n == 3 else "inconclusive_after_5_seeds",
                  "v1 stays the default; v2 stays available, unchanged and documented; record "
                  + ("'no measurable benefit of structured perception at 3.072M transitions'" if n == 3 else
                     "'inconclusive after 5 seeds'") + "; the next milestone proceeds with category D on v1",
                  preferred=None)


# -- loading the evaluation tree ------------------------------------------------------------------------------------


def label_rows(spec: km.RunSpec, label: str) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for mode in ("stochastic", "deterministic"):
        p = spec.eval_dir / label / mode / "evaluation.json"
        out[mode] = list(km.read_json(p).get("episodes") or []) if p.is_file() else []
    return out


def clear_verification(spec: km.RunSpec) -> Dict[str, bool]:
    """native_action_digest -> re-validated (rl/m7g_k_run.py verify-clears), over every label of the run."""
    out: Dict[str, bool] = {}
    root = spec.clears_dir
    if root.is_dir():
        for f in sorted(root.glob("*/clear_verification.json")):
            for rec in km.read_json(f).get("clears") or []:
                out[str(rec["native_action_digest"])] = bool(rec.get("verified"))
    return out


def load_facts(specs: Sequence[km.RunSpec]) -> Tuple[Dict[str, Dict[int, SeedFacts]], List[str]]:
    facts: Dict[str, Dict[int, SeedFacts]] = {a: {} for a in ARMS}
    problems: List[str] = []
    for spec in specs:
        rows = label_rows(spec, FINAL_LABEL)
        plan = km.FINAL_EPISODES
        for mode in ("stochastic", "deterministic"):
            if len(rows[mode]) != plan[mode]:
                problems.append(f"{spec.name}: final {mode} has {len(rows[mode])} episodes, planned {plan[mode]}")
        f = seed_facts(rows["stochastic"], rows["deterministic"], clear_verification(spec))
        if f.unverified_clears:
            problems.append(f"{spec.name}: {f.unverified_clears} native clear(s) without a successful native "
                            "re-validation (a clear that does not reproduce is an integrity failure)")
        problems.extend(f"{spec.name}: {p}" for p in f.metric_problems[:5])
        facts[spec.arm][spec.seed] = f
    return facts, problems


# -- reported metrics 4-12 (never gating) ---------------------------------------------------------------------------


def _label_points(spec: km.RunSpec) -> List[Tuple[int, str]]:
    exp = km.load_run(spec)
    return [(int(p["num_timesteps"]), p["label"]) for p in km.evaluation_plan(spec, exp)]


def run_curves(spec: km.RunSpec) -> Dict[str, Any]:
    """Metrics 4-9 per evaluated point (stochastic episodes; the deterministic play reported beside them)."""
    points = []
    first_entry = first_left_break = None
    for t, label in _label_points(spec):
        rows = label_rows(spec, label)
        st = rows["stochastic"]
        if not st:
            continue
        ms = [r.get("eval_metrics") or {} for r in st]
        n = len(ms)
        entries = [m for m in ms if m.get("first_left_entry") is not None]
        any_entry = bool(entries) or any((r.get("eval_metrics") or {}).get("first_left_entry") for r in rows["deterministic"])
        left_ids = {tid: sum(1 for m in ms if tid in (m.get("broken_ids") or [])) for tid in LEFT_TARGETS}
        any_left = any(left_ids.values()) or any(set((r.get("eval_metrics") or {}).get("broken_ids") or []) & set(LEFT_TARGETS)
                                                 for r in rows["deterministic"])
        if any_entry and first_entry is None:
            first_entry = {"num_timesteps": t, "label": label}
        if any_left and first_left_break is None:
            first_left_break = {"num_timesteps": t, "label": label}
        points.append({"num_timesteps": t, "label": label, "stochastic_episodes": n,
                       "targets_mean": sum(int(r["targets_broken"]) for r in st) / n,
                       "left_entry_rate": len(entries) / n,
                       "left_entry_ticks": sorted(int(m["first_left_entry"]["consumed_tick"]) for m in entries),
                       "left_target_break_rate": {str(k): v / n for k, v in left_ids.items()},
                       "seven_target_episodes": sum(1 for m in ms if m.get("seven_or_more_targets")),
                       "moving_target_2_break_rate": sum(1 for m in ms if m.get("moving_target_broken")) / n,
                       "clears_native": sum(1 for r in st if r.get("cleared"))})
    return {"points": points, "first_left_entry_checkpoint": first_entry,
            "first_left_target_break_checkpoint": first_left_break}


def collapse_share(spec: km.RunSpec) -> Optional[Dict[str, Any]]:
    """Metric 11 (M7e definition): max run of one joint action / length of the final deterministic play."""
    rows = label_rows(spec, FINAL_LABEL)["deterministic"]
    if not rows or not rows[0].get("artifact_dir"):
        return None
    import m7e_idle_analysis as ia

    d = Path(rows[0]["artifact_dir"])
    d = d if d.is_absolute() else km.REPO_ROOT / d
    acts = [json.loads(line) for line in (d / "actions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    st = ia.analyse_actions(acts)
    share = st.max_run / float(st.ticks) if st.ticks else None
    return {"max_run": st.max_run, "length": st.ticks, "collapse_share": share,
            "collapsed": share is not None and share >= 0.5}


def sign_agreement(curves: Mapping[str, Mapping[int, Mapping[str, Any]]], seeds: Sequence[int]) -> Dict[str, Any]:
    """Metric 10: per evaluated point, the sign of v2 - v1 mean targets in each seed."""
    out: Dict[str, Any] = {}
    for s in seeds:
        a = {p["label"]: p["targets_mean"] for p in (curves["v1"].get(s) or {}).get("points", [])}
        b = {p["label"]: p["targets_mean"] for p in (curves["v2"].get(s) or {}).get("points", [])}
        out[str(s)] = {lab: (0 if b[lab] == a[lab] else (1 if b[lab] > a[lab] else -1)) for lab in a if lab in b}
    labels = sorted({lab for v in out.values() for lab in v})
    return {"per_seed": out, "all_seeds_agree": {lab: len({out[str(s)].get(lab) for s in seeds}) == 1 for lab in labels}}


# -- the report -------------------------------------------------------------------------------------------------------


def integrity(state: Mapping[str, Any], specs: Sequence[km.RunSpec]) -> List[str]:
    """Gate-0 facts recorded by the driver (never inferred here)."""
    problems: List[str] = []
    runs = state.get("runs") or {}
    for spec in specs:
        rs = runs.get(spec.name) or {}
        if rs.get("status") != "verified":
            problems.append(f"{spec.name}: training status {rs.get('status')!r} (must be verified)")
        if rs.get("max_battleship_processes", 0) and int(rs["max_battleship_processes"]) > km.MAX_GAME_PROCESSES:
            problems.append(f"{spec.name}: {rs['max_battleship_processes']} BattleShip processes")
    control = (state.get("pilot") or {}).get("control_reproduction") or {}
    if control.get("ok") is not True:
        problems.append(f"the v1 control reproduction (pilot) is not recorded as passed: {control.get('problems')}")
    for key, ev in (state.get("evaluations") or {}).items():
        v = ev.get("verification") or {}
        if v and not v.get("ok"):
            problems.append(f"evaluation {key}: {v.get('problems', [])[:2]}")
    try:
        dc = subprocess.run(["git", "diff", "--check"], cwd=str(km.REPO_ROOT), capture_output=True, text=True,
                            timeout=120, check=False)
        if dc.returncode != 0:
            problems.append(f"git diff --check failed: {(dc.stdout or dc.stderr)[:300]}")
    except (OSError, subprocess.TimeoutExpired) as exc:
        problems.append(f"git diff --check could not run: {exc}")
    return problems


def build_report(state: Mapping[str, Any], *, include_extension: bool) -> Dict[str, Any]:
    specs = km.matrix(include_extension=include_extension)
    seeds = sorted({s.seed for s in specs})
    facts, load_problems = load_facts(specs)
    problems = integrity(state, specs) + load_problems
    decision = decide(facts, integrity_problems=problems)
    curves: Dict[str, Dict[int, Any]] = {a: {} for a in ARMS}
    collapse: Dict[str, Dict[int, Any]] = {a: {} for a in ARMS}
    for spec in specs:
        curves[spec.arm][spec.seed] = run_curves(spec)
        collapse[spec.arm][spec.seed] = collapse_share(spec)
    throughput = {s.name: ((state.get("runs") or {}).get(s.name) or {}).get("throughput") for s in specs}
    return {"schema": SCHEMA, "rule_id": RULE_ID, "n": len(seeds), "seeds": seeds,
            "decision": decision,
            "facts": {a: {s: facts[a][s].as_json() for s in sorted(facts[a])} for a in ARMS},
            "reported_metrics": {"curves_4_to_9": curves, "sign_agreement_10": sign_agreement(curves, seeds),
                                 "deterministic_collapse_11": collapse, "throughput_12": throughput},
            "reward_note": "diagnostic returns are never used to rank arms or checkpoints"}


# -- self-test: every gate and branch on synthetic facts --------------------------------------------------------------


def _facts(**kw: Any) -> SeedFacts:
    """A synthetic final evaluation: T given as (target sum, incomplete episodes)."""
    f = SeedFacts(stochastic_episodes=100, deterministic_episodes=100)
    for k, v in kw.items():
        setattr(f, k, v)
    return f


def _plain(t_sum: int, n: int = 100, **kw: Any) -> SeedFacts:
    return _facts(incomplete_target_sum=t_sum, incomplete_episodes=n, **kw)


def self_test() -> int:
    bad: List[str] = []

    def expect(r: Mapping[str, Any], gate: int, branch: str, name: str, ext: Optional[bool] = None) -> None:
        if r["gate"] != gate or r["branch"] != branch or (ext is not None and r["extension_required"] != ext):
            bad.append(f"{name}: got gate {r['gate']} {r['branch']} ext {r['extension_required']}")

    def arms(v1: Sequence[SeedFacts], v2: Sequence[SeedFacts]) -> Dict[str, Dict[int, SeedFacts]]:
        return {"v1": dict(enumerate(v1)), "v2": dict(enumerate(v2))}

    base = [_plain(400), _plain(400), _plain(400)]

    def clear(**kw: Any) -> SeedFacts:
        d = dict(verified_clears_total=1, verified_clears_stochastic=1, best_clear_time=446)
        d.update(kw)
        return _plain(400, 99, **d)
    # gate 0
    expect(decide(arms(base, base), integrity_problems=["x"]), 0, "integrity", "g0")
    # gate 1 (v2 clears 2 of 3, v1 none) and its mirror
    expect(decide(arms(base, [clear(), clear(), _plain(400)])), 1, "clear_v2", "g1_v2")
    expect(decide(arms([clear(), clear(), clear()], base)), 1, "clear_v1", "g1_v1")
    # gate 2a/2b/2c/2d
    expect(decide(arms([clear(), _plain(400), _plain(400)], [clear(), clear(), clear()])), 2, "a_more_clear_seeds_v2", "g2a")
    two = [clear(), clear(), _plain(400)]
    r = decide(arms([clear(verified_clears_stochastic=1), clear(verified_clears_stochastic=1), _plain(400)],
                    [clear(verified_clears_stochastic=11), clear(verified_clears_stochastic=6), _plain(400)]))
    expect(r, 2, "b_clear_rate_v2", "g2b")   # mean diff (10 + 5 + 0) / 300 = 0.05 exactly: inclusive
    r = decide(arms([clear(verified_clears_stochastic=1), clear(verified_clears_stochastic=1), _plain(400)],
                    [clear(verified_clears_stochastic=10), clear(verified_clears_stochastic=6), _plain(400)]))
    if r["branch"] == "b_clear_rate_v2":
        bad.append("g2b_just_below_threshold_accepted")   # (9 + 5) / 300 < 0.05
    expect(decide(arms(two, [clear(best_clear_time=400), clear(best_clear_time=430), _plain(400)])), 2, "c_faster_v2", "g2c")
    expect(decide(arms(two, [clear(best_clear_time=400), clear(best_clear_time=446), _plain(400)])), 2, "d_tie", "g2d")
    # gate 3 at n = 3 -> extension; at n = 5 -> continue
    expect(decide(arms(base, [clear(), _plain(400), _plain(400)])), 3, "single_seed_clear_v2", "g3_n3", True)
    b5 = [_plain(400)] * 5
    r = decide(arms(b5, [clear(), _plain(400), _plain(400), _plain(400), _plain(400)]))
    expect(r, 7, "inconclusive_after_5_seeds", "g3_n5_continues")
    if not any("gate 3 at n = 5" in x for x in r["notes"]):
        bad.append("g3_n5_note")
    # gate 4a/4b/4c/4d
    cross = lambda k=1: _plain(400, ceiling_episodes=k)  # noqa: E731
    expect(decide(arms(base, [cross(), cross(), _plain(400)])), 4, "a_ceiling_v2", "g4a")
    expect(decide(arms([cross(), cross(), cross()], base)), 4, "b_ceiling_v1", "g4b")
    expect(decide(arms([cross(1), cross(1), cross(1)], [cross(6), cross(6), cross(6)])), 4, "c_crossing_rate_v2", "g4c")
    r = decide(arms([cross(1), cross(1), cross(1)], [cross(2), cross(2), cross(1)]))
    if r["gate"] == 4:
        bad.append("g4c_small_difference_must_continue")
    expect(decide(arms(base, [cross(), _plain(400), _plain(400)])), 4, "d_single_seed_crossing_v2", "g4d_n3", True)
    # gate 5: D exactly +0.5 is inclusive. 4.02 - 3.52 is exactly 1/2 but 0.49999999999999956 in float64, which is
    # why the rule is evaluated in exact rationals.
    if 402 / 100 - 352 / 100 >= 0.5:
        bad.append("float_counterexample_no_longer_holds")
    expect(decide(arms([_plain(352)] * 3, [_plain(402)] * 3)), 5, "a_targets_v2", "g5a_exact_half")
    expect(decide(arms([_plain(380), _plain(380), _plain(380)], [_plain(430), _plain(430), _plain(430)])), 5,
           "a_targets_v2", "g5a_half")
    expect(decide(arms([_plain(430)] * 3, [_plain(380)] * 3)), 5, "b_targets_v2_worse", "g5b")
    r = decide(arms([_plain(380)] * 3, [_plain(429), _plain(430), _plain(430)]))     # D-bar = 149/300 < 1/2
    if r["gate"] == 5:
        bad.append("g5a_below_threshold_accepted")
    r = decide(arms([_plain(380), _plain(380), _plain(380)], [_plain(500), _plain(500), _plain(379)]))
    if r["gate"] == 5:
        bad.append("g5a_requires_every_seed_positive")
    # gate 5 with an undefined T (all verified clears) excludes that seed
    allclear = _facts(verified_clears_total=100, verified_clears_stochastic=100, best_clear_time=446)
    r = decide(arms([allclear, _plain(380), _plain(380)], [allclear, _plain(430), _plain(430)]))
    if r["quantities"]["T_defined_seeds"] != [1, 2]:
        bad.append("undefined_T_excluded")
    # gate 6 at n = 3; never at n = 5
    expect(decide(arms([_plain(400)] * 3, [_plain(460), _plain(340), _plain(400)])), 6, "seed_disagreement", "g6", True)
    r = decide(arms([_plain(400)] * 5, [_plain(460), _plain(340), _plain(400), _plain(400), _plain(400)]))
    expect(r, 7, "inconclusive_after_5_seeds", "g6_never_at_n5")
    # gate 7
    expect(decide(arms(base, base)), 7, "no_benefit", "g7")
    # seed sets
    for seeds_bad in ([0, 1], [0, 1, 2, 3], [1, 2, 3]):
        try:
            decide({"v1": {s: _plain(400) for s in seeds_bad}, "v2": {s: _plain(400) for s in seeds_bad}})
            bad.append(f"seeds_{seeds_bad}_accepted")
        except ValueError:
            pass
    # seed facts from rows: unverified clears, T over non-clears, ceiling from metrics
    rows = [{"episode_id": "a", "cleared": True, "native_action_digest": "d1", "completion_time_passed": 446,
             "completion_input_tick": 447, "targets_broken": 10,
             "eval_metrics": {"ok": True, "first_left_entry": {"consumed_tick": 359}, "broken_ids": list(range(10))}},
            {"episode_id": "b", "cleared": False, "native_action_digest": "d2", "targets_broken": 5,
             "eval_metrics": {"ok": True, "first_left_entry": None, "broken_ids": [0, 1, 2, 3, 4]}},
            {"episode_id": "c", "cleared": False, "native_action_digest": "d3", "targets_broken": 3,
             "eval_metrics": {"ok": True, "first_left_entry": None, "broken_ids": [0, 2, 3]}}]
    f = seed_facts(rows, [], {"d1": True})
    if (f.verified_clears_total, f.ceiling_episodes, f.T, f.best_clear_time) != (1, 2, Fraction(8, 2), 446):
        bad.append(f"seed_facts {f.as_json()}")
    f2 = seed_facts(rows, [], {})
    if f2.unverified_clears != 1 or f2.T != Fraction(18, 3):
        bad.append("unverified_clear_counts_as_incomplete_and_flagged")
    total = 27
    print(f"m7g_k_analysis self-test: {'PASS' if not bad else 'FAIL'} ({total} checks, {len(bad)} failed) {bad}")
    return 0 if not bad else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
