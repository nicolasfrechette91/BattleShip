"""M7n analysis: the decision rule of the v3-versus-v1 observation comparison (docs/rl_observation_v3_m7n_decision_rule_v2.json)
in exact integers / fractions, on the per-label quantities of rl/m7l_analysis.label_inputs (reused unchanged: verified
clears, T, target 2, L, R, falls, deterministic facts) and the gate-2 inputs of rl/m7n_crossing (replay-verified
qualified crossings and left-target breaks). Pure: no game, no training, no file writes.

    python rl/m7n_analysis.py self-test      # every gate, outcome, boundary, tie, integrity, incomplete and undefined case

Arms: v1 = the reproduced Phase K control, v3 = btt_policy_obs_v3_entities; seeds 0-2 paired by seed number.
Every parameter is read from the registered JSON (its sha256 is pinned in the campaign manifest), never from
constants here; decide() refuses a rule document of another schema. The superseded v1 rule stays byte-identical at
docs/rl_observation_v3_m7n_decision_rule.json (RULE_DOC_V1) and is never used for a decision.

Pre-launch corrections (2026-09-26, user review): X needs a replay-verified qualified crossing or left-target break
(m7n_crossing.CrossingInputs) instead of a raw left entry; one v3 clear with no control clear decides gate 1 on its
own; T is None (undefined) when every stochastic episode is a verified clear, D / G are None when an operand is, and a
gate whose inputs are undefined is inapplicable (reported, never deciding).
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
RULE_DOC = REPO_ROOT / "docs" / "rl_observation_v3_m7n_decision_rule_v2.json"
RULE_DOC_V1 = REPO_ROOT / "docs" / "rl_observation_v3_m7n_decision_rule.json"
RULE_SCHEMA = "m7n_decision_rule_v2"
ARMS = ("v1", "v3")
OUTCOMES = {0: "invalid", 1: "success", 2: "success", 3: "success", 4: "failure", 5: "failure", 6: "inconclusive"}
NAMES = {1: "first_clear", 2: "ceiling_broken", 3: "better_targets", 4: "worse", 5: "no_learning", 6: "no_benefit"}

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
    """The rule's parameters, typed; a superset of what m7l_analysis.episode_facts / label_inputs read."""
    p = dict(rule["parameters"])
    for k in ("right_ids", "static_right_ids", "left_ids", "seeds"):
        p[k] = tuple(int(x) for x in p[k])
    return p


# -- quantities ---------------------------------------------------------------------------------------------------


def x_of(c: Optional[CrossingInputs]) -> Optional[int]:
    """X: a replay-verified qualified wall crossing or left-target break in the final stochastic episodes (None when
    the crossing verification of the label is missing)."""
    return None if c is None else int(c.X)


def _sub(a: Optional[Fraction], b: Optional[Fraction]) -> Optional[Fraction]:
    return None if a is None or b is None else a - b


def quantities(inputs: Mapping[str, Any], P: Mapping[str, Any]) -> Dict[str, Any]:
    seeds = P["seeds"]
    v1, v3, v3i = inputs["v1"], inputs["v3"], inputs["v3_initial"]
    xs = inputs.get("crossings") or {}
    q: Dict[str, Any] = {"seeds": list(seeds)}
    q["K"] = {a: {s: inputs[a][s].verified_clears for s in seeds} for a in ARMS}
    q["K_sum"] = {a: sum(q["K"][a].values()) for a in ARMS}
    q["X"] = {a: {s: x_of((xs.get(a) or {}).get(s)) for s in seeds} for a in ARMS}
    q["crossings"] = {a: {s: ((xs.get(a) or {}).get(s).to_json() if (xs.get(a) or {}).get(s) is not None else None)
                          for s in seeds} for a in ARMS}
    q["T"] = {a: {s: inputs[a][s].T for s in seeds} for a in ARMS}
    q["T_initial_v3"] = {s: v3i[s].T for s in seeds}
    q["D"] = {s: _sub(v3[s].T, v1[s].T) for s in seeds}
    q["G"] = {s: _sub(v3[s].T, v3i[s].T) for s in seeds}
    q["undefined"] = [f"T[{a}][{s}]" for a in ARMS for s in seeds if inputs[a][s].T is None] + \
        [f"T[v3_initial][{s}]" for s in seeds if v3i[s].T is None] + \
        [f"D[{s}]" for s in seeds if q["D"][s] is None] + [f"G[{s}]" for s in seeds if q["G"][s] is None]
    q["T2"] = {a: {s: inputs[a][s].t2 for s in seeds} for a in ARMS}
    q["T2_pooled"] = {a: sum(inputs[a][s].t2 for s in seeds) for a in ARMS}
    q["L"] = {a: {s: inputs[a][s].L for s in seeds} for a in ARMS}
    q["R"] = {a: {s: inputs[a][s].R for s in seeds} for a in ARMS}
    q["falls"] = {a: {s: inputs[a][s].falls for s in seeds} for a in ARMS}
    q["left_entries_raw"] = {a: {s: inputs[a][s].left_entries for s in seeds} for a in ARMS}
    q["left_target_episodes_raw"] = {a: {s: inputs[a][s].left_target_episodes for s in seeds} for a in ARMS}
    return q


def decide(inputs: Mapping[str, Any], rule: Mapping[str, Any]) -> Dict[str, Any]:
    """inputs = {"v1": {seed: ArmSeed}, "v3": {seed: ArmSeed}, "v3_initial": {seed: ArmSeed},
    "crossings": {"v1": {seed: CrossingInputs}, "v3": {seed: CrossingInputs}},
    "integrity": [problems], "incomplete": [reasons]}. Gate 0 (integrity) first, then incompleteness, then gates 1-6
    in order; the first applicable gate whose condition holds decides; every gate is evaluated and reported."""
    if rule.get("schema") != RULE_SCHEMA:
        raise ValueError(f"rule schema {rule.get('schema')}")
    P = params(rule)
    n = int(P["episodes_per_seed"])
    seeds = P["seeds"]
    integrity = list(inputs.get("integrity") or [])
    out: Dict[str, Any] = {"rule_sha256": rule.get("_sha256"), "integrity": integrity}
    xs = inputs.get("crossings") or {}
    for s in seeds:  # the control's labels are registered and reproduced: a change here is an integrity problem
        a = (inputs.get("v1") or {}).get(s)
        if a is None or a.n != n:
            integrity.append(f"v1 s{s}: {'missing' if a is None else f'{a.n} episodes'}")
        c = (xs.get("v1") or {}).get(s)
        if c is None:
            integrity.append(f"v1 s{s}: control crossing verification missing")
        elif c.problems or c.exact != c.candidates:
            integrity.append(f"v1 s{s}: crossing verification {c.problems or 'inexact'}")
    for s in seeds:
        c = (xs.get("v3") or {}).get(s)
        if c is not None and (c.problems or c.exact != c.candidates):
            integrity.append(f"v3 s{s}: crossing verification {c.problems or 'inexact'}")
    if integrity:
        return dict(out, gate=0, name="integrity", outcome="invalid", decided=False, integrity=integrity,
                    response=rule["integrity_gate"]["action"], quantities=None)
    incomplete = list(inputs.get("incomplete") or [])
    for arm in ("v3", "v3_initial"):
        for s in seeds:
            a = (inputs.get(arm) or {}).get(s)
            if a is None or a.n != n:
                incomplete.append(f"{arm} s{s}: {'missing' if a is None else f'{a.n} stochastic episodes'} (need {n})")
    for s in seeds:
        if (xs.get("v3") or {}).get(s) is None:
            incomplete.append(f"v3 s{s}: crossing verification missing")
    if incomplete:
        return dict(out, gate=None, name="incomplete", outcome="incomplete", decided=False, incomplete=incomplete,
                    response=rule["incomplete"]["action"], quantities=None)
    for a in ARMS + ("v3_initial",):
        for s in seeds:
            arm = inputs[a][s]
            if arm.T is None and arm.stochastic_verified_clears != arm.n:
                raise ValueError(f"{a} s{s}: T undefined although {arm.n - arm.stochastic_verified_clears} stochastic "
                                 "episodes are not verified clears")
    q = quantities(inputs, P)
    thr = frac(P["targets_diff_min"])
    need = int(P["no_learning_seeds_min"])
    guard = q["K_sum"]["v1"] >= 1 and q["K_sum"]["v3"] == 0     # the control-clear guard: v3 cannot be selected
    d_defined = all(q["D"][s] is not None for s in seeds)
    g_defined = [s for s in seeds if q["G"][s] is not None]
    inapplicable: Dict[str, str] = {}
    if not d_defined:
        why = "D undefined in seed(s) " + ", ".join(str(s) for s in seeds if q["D"][s] is None) + " (an all-clear label)"
        inapplicable["3_better_targets"] = why
        inapplicable["4_worse"] = why
    if len(g_defined) < need:
        inapplicable["5_no_learning"] = f"G defined in {len(g_defined)} seed(s), fewer than {need}"
    g = {
        1: (q["K_sum"]["v3"] >= 1 and q["K_sum"]["v1"] == 0) or all(q["K"]["v3"][s] > q["K"]["v1"][s] for s in seeds),
        2: not guard and sum(int(q["X"]["v3"][s] or 0) for s in seeds) >= int(P["ceiling_seeds_min"])
        and all(q["X"]["v1"][s] == 0 for s in seeds),
        3: not guard and d_defined and all(q["D"][s] >= thr for s in seeds),
        4: d_defined and all(q["D"][s] <= -thr for s in seeds),
        5: len(g_defined) >= need and sum(1 for s in g_defined if q["G"][s] <= 0) >= need,
    }
    gate = next((k for k in (1, 2, 3, 4, 5) if g[k]), 6)
    g[6] = gate == 6
    spec = next(x for x in rule["gates_in_order"] if int(x["gate"]) == gate)
    return dict(out, gate=gate, name=NAMES[gate], outcome=OUTCOMES[gate], decided=True, control_clear_guard=guard,
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


# -- self-test (synthetic inputs) ------------------------------------------------------------------------------------


def _arm(T: Any, *, K: int = 0, left_entries: int = 0, left_breaks: int = 0, t2: int = 0, n: int = 100,
         all_clear: bool = False) -> ArmSeed:
    if all_clear:
        return ArmSeed(n=n, t2=t2, S=0, S_right=0, L=0, R=0, T=None, falls=0, native_clears=K or n, verified_clears=K or n,
                       stochastic_verified_clears=n, left_entries=left_entries, left_target_episodes=left_breaks)
    return ArmSeed(n=n, t2=t2, S=0, S_right=0, L=0, R=0, T=None if T is None else Fraction(str(T)), falls=0,
                   native_clears=K, verified_clears=K, stochastic_verified_clears=0, left_entries=left_entries,
                   left_target_episodes=left_breaks)


def _xc(*, candidates: int = 0, exact: Optional[int] = None, qualified: int = 0, left_breaks: int = 0,
        unqualified: int = 0, problems: Sequence[str] = ()) -> CrossingInputs:
    return CrossingInputs(candidates=candidates, exact=candidates if exact is None else exact,
                          qualified_crossings=qualified, verified_left_target_episodes=left_breaks,
                          unqualified_left_entries=unqualified, problems=list(problems))


NONE3 = [_xc(), _xc(), _xc()]


def self_test(rule_path: Path = RULE_DOC) -> int:
    rule = load_rule(rule_path)
    fails: List[str] = []

    def run(v1: Sequence[ArmSeed], v3: Sequence[ArmSeed], v3i: Optional[Sequence[ArmSeed]] = None,
            integrity: Sequence[str] = (), incomplete: Sequence[str] = (),
            x1: Optional[Sequence[Optional[CrossingInputs]]] = None,
            x3: Optional[Sequence[Optional[CrossingInputs]]] = None) -> Dict[str, Any]:
        v3i = v3i or [_arm("3")] * 3
        x1 = NONE3 if x1 is None else x1
        x3 = NONE3 if x3 is None else x3
        return decide({"v1": dict(enumerate(v1)), "v3": dict(enumerate(v3)), "v3_initial": dict(enumerate(v3i)),
                       "crossings": {"v1": {s: x for s, x in enumerate(x1) if x is not None},
                                     "v3": {s: x for s, x in enumerate(x3) if x is not None}},
                       "integrity": list(integrity), "incomplete": list(incomplete)}, rule)

    def expect(name: str, d: Mapping[str, Any], gate: Any, outcome: str, extra: bool = True) -> None:
        ok = d.get("gate") == gate and d["outcome"] == outcome and extra
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: gate {d.get('gate')} {d['outcome']} (want {gate} {outcome})"
              + ("" if extra else " [extra check failed]"))
        if not ok:
            fails.append(name)

    C = [_arm("472/100"), _arm("475/100"), _arm("427/100")]                       # the Phase K control finals
    same = [_arm("472/100"), _arm("475/100"), _arm("427/100")]
    QX = _xc(candidates=1, qualified=1)                 # one replay-verified qualified crossing
    LX = _xc(candidates=1, left_breaks=1)               # one replay-verified left-target break
    UX = _xc(candidates=1, unqualified=1)               # an exact but unqualified left entry (off-stage fall)
    # gate 0 and incompleteness come first, whatever the data says
    expect("integrity first", run(C, [_arm("9", K=3)] * 3, integrity=["x"]), 0, "invalid")
    expect("incomplete v3 final (99 episodes)", run(C, [_arm("9", n=99), _arm("9"), _arm("9")]), None, "incomplete")
    expect("incomplete v3 initial", run(C, [_arm("9")] * 3, v3i=[_arm("3", n=60)] * 3), None, "incomplete")
    expect("incomplete flag", run(C, [_arm("9")] * 3, incomplete=["run 2 stopped"]), None, "incomplete")
    expect("incomplete: v3 crossing verification missing", run(C, [_arm("9")] * 3, x3=[_xc(), None, _xc()]), None, "incomplete")
    expect("control label changed -> integrity", run([_arm("4", n=99)] + C[1:], [_arm("9")] * 3), 0, "invalid")
    expect("control crossing verification missing -> integrity", run(C, [_arm("9")] * 3, x1=[_xc(), None, _xc()]), 0, "invalid")
    expect("inexact v3 crossing candidate -> integrity", run(C, [_arm("6", left_entries=1)] * 3, x3=[_xc(candidates=1, exact=0), _xc(), _xc()]), 0, "invalid")
    expect("inexact control crossing candidate -> integrity", run(C, [_arm("6")] * 3, x1=[_xc(candidates=1, exact=0, problems=["e: replay not exact"]), _xc(), _xc()]), 0, "invalid")
    # gate 1: clears (a single seed carries the first-clear condition)
    expect("one v3 clear, none in v1", run(C, [_arm("5", K=1), _arm("5"), _arm("5")]), 1, "success")
    expect("single-seed first clear in seed 1 with worse targets elsewhere",
           run(C, [_arm("3"), _arm("4", K=1), _arm("3")], v3i=[_arm("4")] * 3), 1, "success")
    expect("clear tie 1 = 1 is not gate 1 (falls to 6)", run([_arm("4", K=1)] + C[1:], [_arm("4", K=1), _arm("4"), _arm("4")]), 6, "inconclusive")
    expect("v3 more clears in every seed", run([_arm("4", K=1)] * 3, [_arm("4", K=2)] * 3), 1, "success")
    expect("v1-only clear blocks gate 3 (guard)", run([_arm("4", K=1)] + C[1:], [_arm("6"), _arm("6"), _arm("6")]), 6, "inconclusive")
    expect("v1-only clear blocks gate 2 (guard)", run([_arm("4", K=1)] + C[1:], [_arm("4", left_entries=1), _arm("4", left_breaks=1), _arm("4")], x3=[QX, LX, _xc()]), 6, "inconclusive")
    expect("v1-only clear, v3 worse -> still worse", run([_arm("6", K=1), _arm("6"), _arm("6")], [_arm("4"), _arm("4"), _arm("4")], v3i=[_arm("1")] * 3), 4, "failure")
    # gate 1 with undefined T (all-clear labels): decided by K alone, no fabricated number
    d = run(C, [_arm(None, all_clear=True), _arm("5"), _arm("5")])
    expect("all-clear v3 label (T undefined), no control clear", d, 1, "success",
           d["quantities"]["T"]["v3"]["0"] is None and "T[v3][0]" in d["quantities"]["undefined"] and d["quantities"]["D"]["0"] is None)
    d = run([_arm(None, all_clear=True)] * 3, [_arm(None, all_clear=True)] * 3, v3i=[_arm(None, all_clear=True)] * 3)
    expect("all-clear labels in both arms, equal clears -> inconclusive tie, gates 3-5 inapplicable", d, 6, "inconclusive",
           set(d["inapplicable"]) == {"3_better_targets", "4_worse", "5_no_learning"} and d["quantities"]["D"]["0"] is None
           and d["quantities"]["G"]["0"] is None)
    d = run([_arm("4", K=1)] + C[1:], [_arm(None, all_clear=True), _arm("5"), _arm("5")])
    expect("all-clear v3 seed 0 against a control clear in seed 0 (not gate 1 per seed; 3-4 inapplicable)", d, 6, "inconclusive",
           set(d["inapplicable"]) == {"3_better_targets", "4_worse"} and d["gates"]["1_first_clear"] is False)
    d = run(C, same, v3i=[_arm(None, all_clear=True), _arm(None, all_clear=True), _arm("472/100")])
    expect("undefined G in two seeds -> gate 5 inapplicable", d, 6, "inconclusive", "5_no_learning" in d["inapplicable"])
    d = run(C, same, v3i=[_arm(None, all_clear=True), _arm("475/100"), _arm("427/100")])
    expect("undefined G in one seed, G = 0 in the other two -> no learning", d, 5, "failure", not d["inapplicable"])
    # gate 2: the ceiling (replay-verified qualified crossings / left-target breaks only)
    expect("off-stage left entry in every seed (exact, unqualified) is not gate 2",
           run(C, [_arm("4", left_entries=1)] * 3, x3=[UX, UX, UX]), 6, "inconclusive")
    expect("raw left-entry counts without a qualified crossing never gate",
           run(C, [_arm("4", left_entries=3), _arm("4", left_entries=2), _arm("4")], x3=[_xc(candidates=3, unqualified=3), _xc(candidates=2, unqualified=2), _xc()]), 6, "inconclusive")
    expect("qualified landing in 2 seeds, control none", run(C, [_arm("4", left_entries=1), _arm("4", left_entries=1), _arm("4")], x3=[QX, QX, _xc()]), 2, "success")
    expect("left-target break verified in 2 seeds", run(C, [_arm("4", left_breaks=1), _arm("4"), _arm("4", left_breaks=1)], x3=[LX, _xc(), LX]), 2, "success")
    expect("one qualified crossing + one left-target break", run(C, [_arm("4", left_entries=1), _arm("4", left_breaks=1), _arm("4")], x3=[QX, LX, _xc()]), 2, "success")
    expect("qualified crossing in 1 seed only", run(C, [_arm("4", left_entries=1), _arm("4"), _arm("4")], x3=[QX, _xc(), _xc()]), 6, "inconclusive")
    expect("a control candidate that does not qualify does not block gate 2",
           run([_arm("472/100", left_entries=1)] + C[1:], [_arm("4", left_entries=1), _arm("4", left_entries=1), _arm("4")], x1=[UX, _xc(), _xc()], x3=[QX, QX, _xc()]), 2, "success")
    expect("a control qualified crossing blocks gate 2",
           run([_arm("472/100", left_entries=1)] + C[1:], [_arm("4", left_entries=1), _arm("4", left_entries=1), _arm("4")], x1=[QX, _xc(), _xc()], x3=[QX, QX, _xc()]), 6, "inconclusive")
    expect("a control left-target break blocks gate 2",
           run([_arm("472/100", left_breaks=1)] + C[1:], [_arm("4", left_entries=1), _arm("4", left_entries=1), _arm("4")], x1=[LX, _xc(), _xc()], x3=[QX, QX, _xc()]), 6, "inconclusive")
    # gate 3 / 4 boundaries: D exactly +1/2 and -1/2 in every seed
    up = [_arm(Fraction("472/100") + Fraction(1, 2)), _arm(Fraction("475/100") + Fraction(1, 2)), _arm(Fraction("427/100") + Fraction(1, 2))]
    expect("D exactly +1/2 everywhere", run(C, up), 3, "success")
    up_short = [up[0], up[1], _arm(Fraction("427/100") + Fraction(49, 100))]
    expect("D +1/2, +1/2, +49/100", run(C, up_short), 6, "inconclusive")
    down = [_arm(Fraction("472/100") - Fraction(1, 2)), _arm(Fraction("475/100") - Fraction(1, 2)), _arm(Fraction("427/100") - Fraction(1, 2))]
    expect("D exactly -1/2 everywhere", run(C, down, v3i=[_arm("1")] * 3), 4, "failure")
    expect("D -1/2, -1/2, -49/100 with learning", run(C, [down[0], down[1], _arm(Fraction("427/100") - Fraction(49, 100))], v3i=[_arm("1")] * 3), 6, "inconclusive")
    expect("seed disagreement in sign", run(C, [_arm("6"), _arm("3"), _arm("6")]), 6, "inconclusive")
    # gate 5: v3's own learning (G <= 0 in >= 2 seeds); exactly 0 counts as no learning
    expect("no learning in 2 seeds", run(C, same, v3i=[_arm("472/100"), _arm("475/100"), _arm("1")]), 5, "failure")
    expect("no learning in 1 seed only", run(C, same, v3i=[_arm("472/100"), _arm("1"), _arm("1")]), 6, "inconclusive")
    expect("G exactly 0 in every seed", run(C, same, v3i=same), 5, "failure")
    expect("worse takes precedence over no learning", run(C, down, v3i=down), 4, "failure")
    expect("better takes precedence over no learning", run(C, up, v3i=up), 3, "success")
    expect("clear takes precedence over everything", run(C, [_arm("1", K=1), _arm("1"), _arm("1")], v3i=[_arm("3")] * 3), 1, "success")
    expect("gate 2 takes precedence over worse", run(C, [_arm("1", left_entries=1), _arm("1", left_entries=1), _arm("1")], v3i=[_arm("3")] * 3, x3=[QX, QX, _xc()]), 2, "success")
    expect("identical arms", run(C, same), 6, "inconclusive")
    try:
        decide({"v1": {}, "v3": {}, "v3_initial": {}, "integrity": []}, {"schema": "other"})
        fails.append("wrong schema accepted")
    except ValueError:
        print("[PASS] a rule of another schema is refused")
    try:
        run(C, [_arm(None), _arm("5"), _arm("5")])       # T None without an all-clear label is a defect, never silent
        fails.append("undefined T without all clears accepted")
    except ValueError:
        print("[PASS] T undefined without an all-clear label is refused")
    d = run(C, up)
    ok = d["gates"]["1_first_clear"] is False and d["gates"]["3_better_targets"] is True and \
        d["quantities"]["D"]["0"] == "1/2" and d["rule_sha256"] == rule["_sha256"] and d["inapplicable"] == {} and \
        d["quantities"]["X"]["v1"]["0"] == 0 and d["quantities"]["crossings"]["v3"]["0"]["candidates"] == 0
    print(f"[{'PASS' if ok else 'FAIL'}] every gate reported; exact fractions; X and crossings carried; rule digest carried")
    if not ok:
        fails.append("report")
    print(f"self-test: {'PASS' if not fails else 'FAIL ' + str(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["self-test"]:
        raise SystemExit(self_test())
    print(__doc__)
    raise SystemExit(2)
