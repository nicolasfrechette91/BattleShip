"""M7o analysis: the decision rule of the exploration-credit comparison (docs/rl_exploration_credit_m7o_decision_rule.json)
in exact integers / fractions, on rl/m7l_analysis.label_inputs (clears, T, L, R, target 2, falls) and the gate-2 inputs
of rl/m7n_crossing (replay-verified qualified crossings / left-target breaks). Pure: no game, no training, no writes.

    python rl/m7o_analysis.py self-test

Arms: exp = m7o_s{s}_x1 (v3 + v2 + btt_explore_cells_v1), ctl = the M7n v3 runs m7n_s{s}_v3; seeds 0-2 paired.
Discovery (gates 1-2) precedes target regression (gate 3): when both hold, the outcome is the discovery outcome with
target_regression = true and the label suffix "_with_target_regression"; every gate is evaluated and reported.
"""
from __future__ import annotations

import hashlib
import json
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import m7l_analysis as la
import m7n_crossing as xc

RL_DIR = Path(__file__).resolve().parent
REPO_ROOT = RL_DIR.parent
RULE_DOC = REPO_ROOT / "docs" / "rl_exploration_credit_m7o_decision_rule.json"
RULE_SCHEMA = "m7o_decision_rule_v1"
ARMS = ("ctl", "exp")
OUTCOMES = {0: "invalid", 1: "success_discovery", 2: "success_discovery", 3: "failure_regression", 4: "inconclusive_targets_up",
            5: "failure_no_learning", 6: "inconclusive"}
NAMES = {1: "first_clear", 2: "ceiling_broken", 3: "target_regression", 4: "targets_up_no_discovery", 5: "no_learning",
         6: "no_discovery_no_regression"}

ArmSeed = la.ArmSeed
CrossingInputs = xc.CrossingInputs


def load_rule(path: Path = RULE_DOC) -> Dict[str, Any]:
    raw = Path(path).read_bytes()
    rule = json.loads(raw)
    if rule.get("schema") != RULE_SCHEMA:
        raise ValueError(f"{path}: schema {rule.get('schema')} != {RULE_SCHEMA}")
    rule["_sha256"] = hashlib.sha256(raw).hexdigest()
    return rule


def frac(v: Any) -> Fraction:
    return Fraction(str(v))


def params(rule: Mapping[str, Any]) -> Dict[str, Any]:
    p = dict(rule["parameters"])
    for k in ("right_ids", "static_right_ids", "left_ids", "seeds"):
        p[k] = tuple(int(x) for x in p[k])
    return p


def x_of(c: Optional[CrossingInputs]) -> Optional[int]:
    return None if c is None else int(c.X)


def _sub(a: Optional[Fraction], b: Optional[Fraction]) -> Optional[Fraction]:
    return None if a is None or b is None else a - b


def quantities(inputs: Mapping[str, Any], P: Mapping[str, Any]) -> Dict[str, Any]:
    seeds = P["seeds"]
    ctl, exp, expi = inputs["ctl"], inputs["exp"], inputs["exp_initial"]
    xs = inputs.get("crossings") or {}
    q: Dict[str, Any] = {"seeds": list(seeds)}
    q["K"] = {a: {s: inputs[a][s].verified_clears for s in seeds} for a in ARMS}
    q["K_sum"] = {a: sum(q["K"][a].values()) for a in ARMS}
    q["X"] = {a: {s: x_of((xs.get(a) or {}).get(s)) for s in seeds} for a in ARMS}
    q["crossings"] = {a: {s: ((xs.get(a) or {}).get(s).to_json() if (xs.get(a) or {}).get(s) is not None else None) for s in seeds}
                      for a in ARMS}
    q["T"] = {a: {s: inputs[a][s].T for s in seeds} for a in ARMS}
    q["T_initial_exp"] = {s: expi[s].T for s in seeds}
    q["D"] = {s: _sub(exp[s].T, ctl[s].T) for s in seeds}
    q["G"] = {s: _sub(exp[s].T, expi[s].T) for s in seeds}
    q["undefined"] = [f"T[{a}][{s}]" for a in ARMS for s in seeds if inputs[a][s].T is None] + \
        [f"T[exp_initial][{s}]" for s in seeds if expi[s].T is None] + [f"D[{s}]" for s in seeds if q["D"][s] is None] + \
        [f"G[{s}]" for s in seeds if q["G"][s] is None]
    for k in ("t2", "L", "R", "falls", "seven_right", "left_entries", "left_target_episodes"):
        q[k] = {a: {s: getattr(inputs[a][s], k) for s in seeds} for a in ARMS}
    q["t2_pooled"] = {a: sum(inputs[a][s].t2 for s in seeds) for a in ARMS}
    q["L_pooled"] = {a: sum(inputs[a][s].L for s in seeds) for a in ARMS}
    q["R_pooled"] = {a: sum(inputs[a][s].R for s in seeds) for a in ARMS}
    return q


def decide(inputs: Mapping[str, Any], rule: Mapping[str, Any]) -> Dict[str, Any]:
    """inputs = {"ctl": {seed: ArmSeed}, "exp": {seed: ArmSeed}, "exp_initial": {seed: ArmSeed},
    "crossings": {"ctl": {seed: CrossingInputs}, "exp": {seed: CrossingInputs}}, "integrity": [...], "incomplete": [...]}."""
    if rule.get("schema") != RULE_SCHEMA:
        raise ValueError(f"rule schema {rule.get('schema')}")
    P = params(rule)
    n = int(P["episodes_per_seed"])
    seeds = P["seeds"]
    integrity = list(inputs.get("integrity") or [])
    out: Dict[str, Any] = {"rule_sha256": rule.get("_sha256"), "integrity": integrity}
    xs = inputs.get("crossings") or {}
    for s in seeds:   # the control's labels are verified records: anything off is integrity
        a = (inputs.get("ctl") or {}).get(s)
        if a is None or a.n != n:
            integrity.append(f"ctl s{s}: {'missing' if a is None else f'{a.n} episodes'}")
        c = (xs.get("ctl") or {}).get(s)
        if c is None:
            integrity.append(f"ctl s{s}: control crossing verification missing")
        elif c.problems or c.exact != c.candidates:
            integrity.append(f"ctl s{s}: crossing verification {c.problems or 'inexact'}")
    for s in seeds:
        c = (xs.get("exp") or {}).get(s)
        if c is not None and (c.problems or c.exact != c.candidates):
            integrity.append(f"exp s{s}: crossing verification {c.problems or 'inexact'}")
    if integrity:
        return dict(out, gate=0, name="integrity", outcome="invalid", decided=False, integrity=integrity,
                    response=rule["integrity_gate"]["action"], quantities=None)
    incomplete = list(inputs.get("incomplete") or [])
    for arm in ("exp", "exp_initial"):
        for s in seeds:
            a = (inputs.get(arm) or {}).get(s)
            if a is None or a.n != n:
                incomplete.append(f"{arm} s{s}: {'missing' if a is None else f'{a.n} stochastic episodes'} (need {n})")
    for s in seeds:
        if (xs.get("exp") or {}).get(s) is None:
            incomplete.append(f"exp s{s}: crossing verification missing")
    if incomplete:
        return dict(out, gate=None, name="incomplete", outcome="incomplete", decided=False, incomplete=incomplete,
                    response=rule["incomplete"]["action"], quantities=None)
    for a in ARMS + ("exp_initial",):
        for s in seeds:
            arm = inputs[a][s]
            if arm.T is None and arm.stochastic_verified_clears != arm.n:
                raise ValueError(f"{a} s{s}: T undefined although not every stochastic episode is a verified clear")
    q = quantities(inputs, P)
    thr = frac(P["targets_diff_min"])
    need_reg, need_nl = int(P["regression_seeds_min"]), int(P["no_learning_seeds_min"])
    guard = q["K_sum"]["ctl"] >= 1 and q["K_sum"]["exp"] == 0
    d_def = [s for s in seeds if q["D"][s] is not None]
    g_def = [s for s in seeds if q["G"][s] is not None]
    inapplicable: Dict[str, str] = {}
    if len(d_def) < need_reg:
        inapplicable["3_target_regression"] = f"D defined in {len(d_def)} seed(s), fewer than {need_reg}"
    if len(d_def) < len(seeds):
        inapplicable["4_targets_up_no_discovery"] = "D undefined in seed(s) " + ", ".join(str(s) for s in seeds if q["D"][s] is None)
    if len(g_def) < need_nl:
        inapplicable["5_no_learning"] = f"G defined in {len(g_def)} seed(s), fewer than {need_nl}"
    g = {
        1: (q["K_sum"]["exp"] >= 1 and q["K_sum"]["ctl"] == 0) or all(q["K"]["exp"][s] > q["K"]["ctl"][s] for s in seeds),
        2: not guard and sum(int(q["X"]["exp"][s] or 0) for s in seeds) >= int(P["ceiling_seeds_min"])
        and all(q["X"]["ctl"][s] == 0 for s in seeds),
        3: len(d_def) >= need_reg and sum(1 for s in d_def if q["D"][s] <= -thr) >= need_reg,
        4: not guard and len(d_def) == len(seeds) and all(q["D"][s] >= thr for s in seeds),
        5: len(g_def) >= need_nl and sum(1 for s in g_def if q["G"][s] <= 0) >= need_nl,
    }
    gate = next((k for k in (1, 2, 3, 4, 5) if g[k]), 6)
    g[6] = gate == 6
    outcome = OUTCOMES[gate]
    regression = bool(g[3])
    if gate in (1, 2) and regression:
        outcome = outcome + "_with_target_regression"
    spec = next(x for x in rule["gates_in_order"] if x["gate"] == gate)
    return dict(out, gate=gate, name=NAMES[gate], outcome=outcome, decided=True, control_clear_guard=guard,
                target_regression=regression, discovery=gate in (1, 2),
                gates={f"{k}_{NAMES[k]}": bool(v) for k, v in g.items()}, inapplicable=inapplicable,
                response=spec["action"], condition=spec["condition"], quantities=_json(q))


def _json(v: Any) -> Any:
    if isinstance(v, Fraction):
        return str(v)
    if isinstance(v, Mapping):
        return {str(k): _json(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json(x) for x in v]
    return v


# -- self-test -------------------------------------------------------------------------------------------------------


def _arm(T: Any, *, K: int = 0, n: int = 100, all_clear: bool = False, **kw: Any) -> ArmSeed:
    base = dict(n=n, t2=0, S=0, S_right=0, L=0, R=0, falls=0, left_entries=0, left_target_episodes=0)
    base.update(kw)
    if all_clear:
        return ArmSeed(T=None, native_clears=K or n, verified_clears=K or n, stochastic_verified_clears=n, **base)
    return ArmSeed(T=None if T is None else Fraction(str(T)), native_clears=K, verified_clears=K, stochastic_verified_clears=0, **base)


def _xc(*, candidates: int = 0, exact: Optional[int] = None, qualified: int = 0, left_breaks: int = 0, unqualified: int = 0,
        problems: Sequence[str] = ()) -> CrossingInputs:
    return CrossingInputs(candidates=candidates, exact=candidates if exact is None else exact, qualified_crossings=qualified,
                          verified_left_target_episodes=left_breaks, unqualified_left_entries=unqualified, problems=list(problems))


NONE3 = [_xc(), _xc(), _xc()]


def self_test(rule_path: Path = RULE_DOC) -> int:
    rule = load_rule(rule_path)
    fails: List[str] = []

    def run(ctl, exp, expi=None, integrity=(), incomplete=(), xc_=None, xe=None):
        expi = expi or [_arm("3")] * 3
        xc_ = NONE3 if xc_ is None else xc_
        xe = NONE3 if xe is None else xe
        return decide({"ctl": dict(enumerate(ctl)), "exp": dict(enumerate(exp)), "exp_initial": dict(enumerate(expi)),
                       "crossings": {"ctl": {s: x for s, x in enumerate(xc_) if x is not None},
                                     "exp": {s: x for s, x in enumerate(xe) if x is not None}},
                       "integrity": list(integrity), "incomplete": list(incomplete)}, rule)

    def expect(name, d, gate, outcome, extra=True):
        ok = d.get("gate") == gate and d["outcome"] == outcome and extra
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: gate {d.get('gate')} {d['outcome']} (want {gate} {outcome})" + ("" if extra else " [extra]"))
        if not ok:
            fails.append(name)

    C = [_arm("138/25"), _arm("553/100"), _arm("559/100")]     # the M7n v3 finals (the control)
    same = [_arm("138/25"), _arm("553/100"), _arm("559/100")]
    QX, LX, UX = _xc(candidates=1, qualified=1), _xc(candidates=1, left_breaks=1), _xc(candidates=1, unqualified=1)
    half = Fraction(1, 2)
    up = [_arm(a.T + half) for a in C]
    down = [_arm(a.T - half) for a in C]
    expect("integrity first", run(C, [_arm("9", K=3)] * 3, integrity=["x"]), 0, "invalid")
    expect("control label short -> integrity", run([_arm("5", n=99)] + C[1:], [_arm("9")] * 3), 0, "invalid")
    expect("control crossing doc missing -> integrity", run(C, [_arm("9")] * 3, xc_=[_xc(), None, _xc()]), 0, "invalid")
    expect("inexact exp candidate -> integrity", run(C, [_arm("6", left_entries=1)] * 3, xe=[_xc(candidates=1, exact=0), _xc(), _xc()]), 0, "invalid")
    expect("incomplete exp final", run(C, [_arm("9", n=99), _arm("9"), _arm("9")]), None, "incomplete")
    expect("incomplete exp initial", run(C, [_arm("9")] * 3, expi=[_arm("3", n=60)] * 3), None, "incomplete")
    expect("incomplete exp crossing doc", run(C, [_arm("9")] * 3, xe=[_xc(), None, _xc()]), None, "incomplete")
    expect("incomplete flag", run(C, [_arm("9")] * 3, incomplete=["run stopped"]), None, "incomplete")
    expect("one exp clear, control none -> discovery", run(C, [_arm("6", K=1), _arm("6"), _arm("6")]), 1, "success_discovery")
    expect("single-seed clear with worse targets elsewhere -> discovery, regression flagged", run(C, [_arm("3"), _arm("4", K=1), _arm("3")], expi=[_arm("4")] * 3), 1, "success_discovery_with_target_regression")
    d = run(C, [_arm("4", K=1), _arm("4"), _arm("4")])
    expect("clear AND regression in >= 2 seeds -> discovery with the regression flag", d, 1, "success_discovery_with_target_regression",
           d["target_regression"] is True and d["gates"]["3_target_regression"] is True)
    expect("clear tie 1 = 1 is not gate 1", run([_arm("5", K=1)] + C[1:], [_arm("6", K=1), _arm("6"), _arm("6")]), 6, "inconclusive")
    expect("exp more clears in every seed", run([_arm("5", K=1)] * 3, [_arm("5", K=2)] * 3), 1, "success_discovery")
    expect("control-only clear blocks gate 2 (guard)", run([_arm("5", K=1)] + C[1:], [_arm("6", left_entries=1)] * 3, xe=[QX, QX, QX]), 6, "inconclusive")
    expect("control-only clear blocks gate 4 (guard)", run([_arm("5", K=1)] + C[1:], up), 6, "inconclusive")
    expect("control-only clear, exp regressed -> regression", run([_arm("6", K=1), _arm("6"), _arm("6")], [_arm("4")] * 3), 3, "failure_regression")
    expect("qualified crossing in 2 seeds, control none -> discovery", run(C, [_arm("6", left_entries=1)] * 3, xe=[QX, QX, _xc()]), 2, "success_discovery")
    expect("left-target break in 2 seeds -> discovery", run(C, [_arm("6", left_target_episodes=1)] * 3, xe=[LX, _xc(), LX]), 2, "success_discovery")
    expect("one crossing + one break", run(C, [_arm("6")] * 3, xe=[QX, LX, _xc()]), 2, "success_discovery")
    expect("crossing in 1 seed only", run(C, [_arm("6")] * 3, xe=[QX, _xc(), _xc()]), 6, "inconclusive")
    expect("off-stage entries are not crossings", run(C, [_arm("6", left_entries=1)] * 3, xe=[UX, UX, UX]), 6, "inconclusive")
    expect("control unqualified entry does not block", run(C, [_arm("6")] * 3, xc_=[UX, _xc(), _xc()], xe=[QX, QX, _xc()]), 2, "success_discovery")
    expect("control qualified crossing blocks gate 2", run(C, [_arm("6")] * 3, xc_=[QX, _xc(), _xc()], xe=[QX, QX, _xc()]), 6, "inconclusive")
    d = run(C, [_arm("4")] * 3, xe=[QX, QX, _xc()])
    expect("crossings AND regression -> discovery with the regression flag", d, 2, "success_discovery_with_target_regression", d["target_regression"])
    expect("D exactly -1/2 in 2 seeds -> regression", run(C, [down[0], down[1], C[2]]), 3, "failure_regression")
    expect("D -1/2 in 1 seed only is not regression", run(C, [down[0], C[1], C[2]]), 6, "inconclusive")
    expect("D -49/100 in every seed is not regression", run(C, [_arm(a.T - Fraction(49, 100)) for a in C]), 6, "inconclusive")
    expect("regression precedes targets-up and no-learning", run(C, down, expi=down), 3, "failure_regression")
    expect("D exactly +1/2 everywhere -> targets up, inconclusive", run(C, up), 4, "inconclusive_targets_up")
    expect("D +1/2, +1/2, +49/100 -> not gate 4", run(C, [up[0], up[1], _arm(C[2].T + Fraction(49, 100))]), 6, "inconclusive")
    expect("no learning in 2 seeds", run(C, same, expi=[C[0], C[1], _arm("1")]), 5, "failure_no_learning")
    expect("no learning in 1 seed only", run(C, same, expi=[C[0], _arm("1"), _arm("1")]), 6, "inconclusive")
    expect("G exactly 0 everywhere -> no learning", run(C, same, expi=same), 5, "failure_no_learning")
    expect("identical arms -> inconclusive (G > 0)", run(C, same), 6, "inconclusive")
    d = run(C, [_arm(None, all_clear=True), _arm("6"), _arm("6")])
    expect("all-clear exp label -> discovery by K, T null", d, 1, "success_discovery", d["quantities"]["T"]["exp"]["0"] is None and d["quantities"]["D"]["0"] is None)
    d = run([_arm(None, all_clear=True)] * 3, [_arm(None, all_clear=True)] * 3, expi=[_arm(None, all_clear=True)] * 3)
    expect("all-clear tie -> inconclusive, gates 3-5 inapplicable", d, 6, "inconclusive",
           set(d["inapplicable"]) == {"3_target_regression", "4_targets_up_no_discovery", "5_no_learning"})
    d = run(C, [_arm(None, all_clear=True), down[1], down[2]], expi=[_arm("3")] * 3)
    expect("all-clear seed with regression in the other two -> discovery with flag", d, 1, "success_discovery_with_target_regression",
           d["target_regression"] and "4_targets_up_no_discovery" in d["inapplicable"])
    try:
        decide({"ctl": {}, "exp": {}, "exp_initial": {}, "integrity": []}, {"schema": "other"})
        fails.append("wrong schema accepted")
    except ValueError:
        print("[PASS] another rule schema is refused")
    try:
        run(C, [_arm(None), _arm("5"), _arm("5")])
        fails.append("undefined T without all clears accepted")
    except ValueError:
        print("[PASS] T undefined without an all-clear label is refused")
    d = run(C, up)
    ok = d["gates"]["1_first_clear"] is False and d["gates"]["4_targets_up_no_discovery"] is True and d["quantities"]["D"]["0"] == "1/2" \
        and d["rule_sha256"] == rule["_sha256"] and d["inapplicable"] == {} and d["target_regression"] is False and d["discovery"] is False
    print(f"[{'PASS' if ok else 'FAIL'}] every gate reported; exact fractions; flags; rule digest carried")
    if not ok:
        fails.append("report")
    print(f"self-test: {'PASS' if not fails else 'FAIL ' + str(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["self-test"]:
        raise SystemExit(self_test())
    print(__doc__)
    raise SystemExit(2)
