"""M7h analysis: the registered revision-2 decision rule (docs/rl_frontier_curriculum_m7h_decision_rule.json) in exact
fractions, and the rule inputs of one final evaluation label. Pure: no game, no training, no file writes.

    python rl/m7h_analysis.py self-test      # every gate, branch and inequality boundary at n = 3 and n = 5

The thresholds are read from the registered JSON (its sha256 is pinned in the campaign manifest), never from constants
here; decide() refuses a rule document of another schema.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
REPO_ROOT = RL_DIR.parent
RULE_DOC = REPO_ROOT / "docs" / "rl_frontier_curriculum_m7h_decision_rule.json"
RULE_SCHEMA = "m7h_decision_rule_v1"
ARMS = ("C", "F")


def load_rule(path: Path = RULE_DOC) -> Dict[str, Any]:
    raw = Path(path).read_bytes()
    rule = json.loads(raw)
    if rule.get("schema") != RULE_SCHEMA:
        raise ValueError(f"{path}: schema {rule.get('schema')} != {RULE_SCHEMA}")
    rule["_sha256"] = hashlib.sha256(raw).hexdigest()
    return rule


def frac(v: Any) -> Fraction:
    return Fraction(str(v))


def _gate(rule: Mapping[str, Any], n: str, number: int) -> Dict[str, Any]:
    return next(g for g in rule[n]["gates"] if g["gate"] == number)


# -- rule inputs ----------------------------------------------------------------------------------------------------


@dataclass
class ArmSeed:
    k: int                      # a verified clear among the 200 final episodes
    c: Fraction                 # verified clears among the 100 stochastic / 100
    chi: int                    # a live left step in the 100 stochastic
    x: Fraction                 # stochastic episodes with a live left step / 100
    T: Optional[Fraction]       # mean targets over stochastic episodes that are not verified clears
    phi: int                    # stochastic episodes ending in a fall
    native_clears: int = 0
    verified_clears: int = 0

    def to_json(self) -> Dict[str, Any]:
        d = asdict(self)
        return {k: (str(v) if isinstance(v, Fraction) else v) for k, v in d.items()}


def rule_inputs(label_dir: Path, clear_doc: Optional[Mapping[str, Any]], *, episodes: int = 100
                ) -> Tuple[ArmSeed, List[str]]:
    """The section-7.1 quantities of one final label (stochastic + deterministic evaluation.json) and the integrity
    problems found while computing them."""
    label_dir = Path(label_dir)
    p: List[str] = []
    rows = {}
    for mode in ("stochastic", "deterministic"):
        f = label_dir / mode / "evaluation.json"
        rows[mode] = json.loads(f.read_text(encoding="utf-8")).get("episodes") or [] if f.is_file() else []
        if len(rows[mode]) != episodes:
            p.append(f"{label_dir.name}/{mode}: {len(rows[mode])} episodes (planned {episodes})")
    sto, det = rows["stochastic"], rows["deterministic"]
    verified = {str(r["native_action_digest"]) for r in (clear_doc or {}).get("clears") or [] if r.get("verified")}
    native = [e for e in sto + det if e.get("cleared")]
    for e in native:
        if str(e.get("native_action_digest")) not in verified:
            p.append(f"{label_dir.name}: native clear {e.get('episode_id')} has no passed clear verification")
    is_v = lambda e: bool(e.get("cleared")) and str(e.get("native_action_digest")) in verified  # noqa: E731
    left = [e for e in sto if (e.get("eval_metrics") or {}).get("first_left_entry")]
    for e in sto:
        if not (e.get("eval_metrics") or {}).get("ok"):
            p.append(f"{label_dir.name}: episode {e.get('episode_id')} has no clean btt_eval_metrics_v1 record")
            break
    rest = [e for e in sto if not is_v(e)]
    T = Fraction(sum(int(e["targets_broken"]) for e in rest), len(rest)) if rest else None
    return ArmSeed(k=int(any(is_v(e) for e in sto + det)), c=Fraction(sum(1 for e in sto if is_v(e)), episodes),
                   chi=int(bool(left)), x=Fraction(len(left), episodes), T=T,
                   phi=sum(1 for e in sto if e.get("end_reason") == "fall"), native_clears=len(native),
                   verified_clears=sum(1 for e in native if is_v(e))), p


# -- quantities ------------------------------------------------------------------------------------------------------


def quantities(inputs: Mapping[str, Any], seeds: Sequence[int]) -> Dict[str, Any]:
    A: Mapping[str, Mapping[int, ArmSeed]] = {a: inputs[a] for a in ARMS}
    n = len(seeds)
    q: Dict[str, Any] = {"n": n, "seeds": list(seeds)}
    for a in ARMS:
        q[f"K_{a}"] = sum(A[a][s].k for s in seeds)
        q[f"X_{a}"] = sum(A[a][s].chi for s in seeds)
        q[f"Phi_{a}"] = Fraction(sum(A[a][s].phi for s in seeds), 100 * n)
    q["S_T"] = [s for s in seeds if A["C"][s].T is not None and A["F"][s].T is not None]
    q["D"] = {s: A["F"][s].T - A["C"][s].T for s in q["S_T"]}
    q["Dbar"] = sum(q["D"].values(), Fraction(0)) / len(q["S_T"]) if q["S_T"] else None
    q["G"] = sum(int(inputs.get("g", {}).get(s, 0)) for s in seeds if s in inputs.get("g", {}))
    q["c"] = {a: {s: A[a][s].c for s in seeds} for a in ARMS}
    q["x"] = {a: {s: A[a][s].x for s in seeds} for a in ARMS}
    return q


def _targets(q: Mapping[str, Any], g: Mapping[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    """Gate 5 at n = 3 / gate 4 at n = 5: the branch that applies (a, b, c, otherwise) or None when S_T is empty."""
    if not q["S_T"]:
        return None, {"S_T": []}
    D, Dbar = q["D"], q["Dbar"]
    dmin, dworse, fmax = frac(g["targets_dbar_min"]), frac(g["targets_dbar_worse"]), frac(g["falls_phi_diff_max"])
    diff = q["Phi_F"] - q["Phi_C"]
    allpos, allneg = all(v > 0 for v in D.values()), all(v < 0 for v in D.values())
    cond = {"all_D_positive": allpos, "all_D_negative": allneg, "Dbar": str(Dbar), "Dbar_ge_min": Dbar >= dmin,
            "Dbar_le_worse": Dbar <= dworse, "Phi_diff": str(diff), "Phi_diff_le_max": diff <= fmax}
    if allpos and Dbar >= dmin:
        return ("a" if diff <= fmax else "b"), cond
    if allneg and Dbar <= dworse:
        return "c", cond
    return "otherwise", cond


def _paired(KF: int, KC: int, perF: Mapping[int, Fraction], perC: Mapping[int, Fraction], seeds: Sequence[int],
            g: Mapping[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    """n = 5 gates 1 (clears) and 2 (crossings): a, b, c_adopt, c_worse, c_record, d_record or None."""
    amin, dmin = int(g["adopt_min"]), frac(g["delta_min"])
    cond: Dict[str, Any] = {"K_F": KF, "K_C": KC}
    if KF >= amin and KC == 0:
        return "a", cond
    if KC >= amin and KF == 0:
        return "b", cond
    if KF >= 1 and KC >= 1:
        delta = sum((perF[s] - perC[s] for s in seeds), Fraction(0)) / len(seeds)
        cond.update(Delta=str(delta), all_F_ge_C=all(perF[s] >= perC[s] for s in seeds),
                    all_F_le_C=all(perF[s] <= perC[s] for s in seeds))
        if delta >= dmin and cond["all_F_ge_C"]:
            return "c_adopt", cond
        if delta <= -dmin and cond["all_F_le_C"]:
            return "c_worse", cond
        return "c_record", cond
    if (KF in (1, 2) and KC == 0) or (KC in (1, 2) and KF == 0):
        return "d_record", cond
    return None, cond


def _result(n: str, gate: int, branch: str, response: str, q: Mapping[str, Any], conditions: Mapping[str, Any],
            notes: List[str], rule: Mapping[str, Any], problems: Sequence[str] = (), extension: bool = False
            ) -> Dict[str, Any]:
    def plain(v: Any) -> Any:
        if isinstance(v, Fraction):
            return str(v)
        if isinstance(v, dict):
            return {str(k): plain(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [plain(x) for x in v]
        return v
    return {"n": n, "gate": gate, "branch": branch, "response": response, "extension_required": bool(extension),
            "quantities": plain(dict(q)), "conditions": plain(dict(conditions)), "notes": list(notes),
            "problems": list(problems), "rule_sha256": rule.get("_sha256")}


def decide_n3(inputs: Mapping[str, Any], rule: Mapping[str, Any]) -> Dict[str, Any]:
    seeds = rule["n3"]["seeds"]
    q = quantities(inputs, seeds)
    problems = list(inputs.get("integrity") or [])
    cond: Dict[str, Any] = {"gate0_integrity_problems": len(problems)}
    notes: List[str] = []
    if problems:
        return _result("n3", 0, "integrity", _gate(rule, "n3", 0)["response"], q, cond, notes, rule, problems)
    g1, g2, g4, g5 = (_gate(rule, "n3", k) for k in (1, 2, 4, 5))
    cond["gate1_K_F_ge_min"] = q["K_F"] >= int(g1["clears_min"])
    if cond["gate1_K_F_ge_min"]:
        return _result("n3", 1, "clears", g1["response"], q, cond, notes, rule)
    cond["gate2_K_F_le_1_and_X_F_ge_min"] = q["K_F"] <= 1 and q["X_F"] >= int(g2["crossings_min"])
    if cond["gate2_K_F_le_1_and_X_F_ge_min"]:
        if q["K_F"] == 1:
            notes.append("a single verified clear in F is recorded (precedence: gate 2)")
        return _result("n3", 2, "crossings", g2["response"], q, cond, notes, rule)
    cond["gate3_K_F_eq_1_or_X_F_eq_1"] = q["K_F"] == 1 or q["X_F"] == 1
    if cond["gate3_K_F_eq_1_or_X_F_eq_1"]:
        return _result("n3", 3, "extension", _gate(rule, "n3", 3)["response"], q, cond, notes, rule, extension=True)
    cond["gate4_G_ge_min"] = q["G"] >= int(g4["discovery_min"])
    if cond["gate4_G_ge_min"]:
        return _result("n3", 4, "discovered_not_consolidated", g4["response"], q, cond, notes, rule)
    branch, tc = _targets(q, g5)
    cond["gate5"] = dict(tc, branch=branch)
    if branch in ("a", "c"):
        return _result("n3", 5, f"targets_{branch}", g5["branches"][branch]["response"], q, cond, notes, rule)
    if branch == "b":
        notes.append(g5["branches"]["b"]["response"])
    return _result("n3", 6, "null", _gate(rule, "n3", 6)["response"], q, cond, notes, rule)


def decide_n5(inputs: Mapping[str, Any], rule: Mapping[str, Any]) -> Dict[str, Any]:
    seeds = rule["n5"]["seeds"]
    q = quantities(inputs, seeds)
    problems = list(inputs.get("integrity") or [])
    cond: Dict[str, Any] = {"gate0_integrity_problems": len(problems)}
    notes: List[str] = []
    if problems:
        return _result("n5", 0, "integrity", _gate(rule, "n5", 0)["response"], q, cond, notes, rule, problems)
    for number, K, per, name, what in ((1, "K", "c", "clears", "clear"), (2, "X", "x", "crossings", "crossing")):
        g = _gate(rule, "n5", number)
        branch, c = _paired(q[f"{K}_F"], q[f"{K}_C"], q[per]["F"], q[per]["C"], seeds, g)
        cond[f"gate{number}_{name}"] = dict(c, branch=branch)
        if branch in ("a", "b"):
            return _result("n5", number, f"{name}_{branch}", g["branches"][branch]["response"], q, cond, notes, rule)
        if branch == "c_adopt":
            return _result("n5", number, f"{name}_c_adopt", g["branches"]["c"]["adopt"], q, cond, notes, rule)
        if branch == "c_worse":
            return _result("n5", number, f"{name}_c_worse", g["branches"]["c"]["worse"], q, cond, notes, rule)
        if branch == "c_record":
            notes.append(f"{name} in both arms")
        if branch == "d_record":
            k = q[f"{K}_F"] if q[f"{K}_F"] else q[f"{K}_C"]
            notes.append(f"{what} not reproduced ({k} of 5, arm {'F' if q[f'{K}_F'] else 'C'})")
    g3 = _gate(rule, "n5", 3)
    cond["gate3_G_ge_min"] = q["G"] >= int(g3["discovery_min"])
    if cond["gate3_G_ge_min"]:
        return _result("n5", 3, "discovered_not_consolidated", g3["response"], q, cond, notes, rule)
    g4 = _gate(rule, "n5", 4)
    branch, tc = _targets(q, g4)
    cond["gate4"] = dict(tc, branch=branch)
    g5_n3 = _gate(rule, "n3", 5)["branches"]
    if branch in ("a", "c"):
        return _result("n5", 4, f"targets_{branch}", g5_n3[branch]["response"], q, cond, notes, rule)
    if branch == "b":
        notes.append(g5_n3["b"]["response"])
    return _result("n5", 5, "null", _gate(rule, "n5", 5)["response"], q, cond, notes, rule)


# -- self-test --------------------------------------------------------------------------------------------------------


def _arm(k=0, c="0", chi=0, x="0", T="4", phi=0) -> ArmSeed:
    return ArmSeed(k=k, c=Fraction(c), chi=chi, x=Fraction(x), T=None if T is None else Fraction(T), phi=phi)


def _inputs(C: Mapping[int, ArmSeed], F: Mapping[int, ArmSeed], g: Optional[Mapping[int, int]] = None,
            integrity: Sequence[str] = ()) -> Dict[str, Any]:
    return {"C": dict(C), "F": dict(F), "g": dict(g or {}), "integrity": list(integrity)}


def self_test(rule: Optional[Mapping[str, Any]] = None) -> int:
    rule = rule or load_rule()
    failures: List[str] = []
    s3, s5 = (0, 1, 2), (0, 1, 2, 3, 4)
    C3 = {0: _arm(T="472/100", phi=1), 1: _arm(T="475/100", phi=1), 2: _arm(T="427/100", phi=0)}   # known control

    def f3(**over: Any) -> Dict[int, ArmSeed]:
        return {s: _arm(**{k: (v[s] if isinstance(v, (list, tuple)) else v) for k, v in over.items()}) for s in s3}

    def expect(name: str, res: Mapping[str, Any], gate: int, branch: str, ext: bool = False) -> None:
        if (res["gate"], res["branch"], res["extension_required"]) != (gate, branch, ext):
            failures.append(f"{name}: got gate {res['gate']} {res['branch']} ext {res['extension_required']}, "
                            f"want {gate} {branch} ext {ext}")

    T = ["522/100", "525/100", "477/100"]           # D = 1/2 in every seed
    expect("integrity", decide_n3(_inputs(C3, f3(T=T), integrity=["x"]), rule), 0, "integrity")
    expect("K_F=2", decide_n3(_inputs(C3, f3(k=[1, 1, 0], T=T)), rule), 1, "clears")
    expect("K_F=3", decide_n3(_inputs(C3, f3(k=1, T=T)), rule), 1, "clears")
    r = decide_n3(_inputs(C3, f3(k=[1, 0, 0], chi=[1, 1, 0], T=T)), rule)
    expect("K_F=1,X_F=2 precedence", r, 2, "crossings")
    if not any("single verified clear" in x for x in r["notes"]):
        failures.append("precedence: the single clear was not recorded")
    expect("K_F=0,X_F=2", decide_n3(_inputs(C3, f3(chi=[0, 1, 1], T=T)), rule), 2, "crossings")
    expect("K_F=1,X_F=0", decide_n3(_inputs(C3, f3(k=[0, 0, 1], T=T)), rule), 3, "extension", True)
    expect("K_F=0,X_F=1", decide_n3(_inputs(C3, f3(chi=[0, 1, 0], T=T)), rule), 3, "extension", True)
    expect("K_F=1,X_F=1", decide_n3(_inputs(C3, f3(k=[1, 0, 0], chi=[1, 0, 0], T=T)), rule), 3, "extension", True)
    expect("G=2", decide_n3(_inputs(C3, f3(T=T), g={0: 1, 1: 1, 2: 0}), rule), 4, "discovered_not_consolidated")
    expect("G=1 -> targets", decide_n3(_inputs(C3, f3(T=T, phi=[1, 1, 3]), g={0: 1}), rule), 5, "targets_a")
    # Phi_C = 2/300; Phi_F - Phi_C <= 1/10 inclusive: Phi_F = 32/300 -> diff exactly 1/10 -> 5(a)
    expect("5a at both boundaries", decide_n3(_inputs(C3, f3(T=T, phi=[10, 10, 12])), rule), 5, "targets_a")
    r = decide_n3(_inputs(C3, f3(T=T, phi=[10, 10, 13])), rule)       # diff 1/10 + 1/300 -> 5(b) -> gate 6
    expect("5b -> null", r, 6, "null")
    if not any("more targets with more falls" in x for x in r["notes"]):
        failures.append("5(b) was not recorded")
    expect("D=0 in a seed blocks 5a", decide_n3(_inputs(C3, f3(T=["522/100", "475/100", "577/100"])), rule), 6, "null")
    expect("Dbar just below 1/2", decide_n3(_inputs(C3, f3(T=["522/100", "525/100", "476/100"])), rule), 6, "null")
    expect("5c at the boundary", decide_n3(_inputs(C3, f3(T=["422/100", "425/100", "377/100"])), rule), 5, "targets_c")
    expect("5c blocked by D=0", decide_n3(_inputs(C3, f3(T=["472/100", "375/100", "277/100"])), rule), 6, "null")
    expect("mixed signs -> null", decide_n3(_inputs(C3, f3(T=["600/100", "400/100", "500/100"])), rule), 6, "null")
    # n = 5 (C seeds 3, 4 new)
    C5 = {**C3, 3: _arm(T="4"), 4: _arm(T="4")}
    T5 = ["522/100", "525/100", "477/100", "9/2", "9/2"]

    def f5(**over: Any) -> Dict[int, ArmSeed]:
        return {s: _arm(**{k: (v[s] if isinstance(v, (list, tuple)) else v) for k, v in over.items()}) for s in s5}

    def c5(**over: Any) -> Dict[int, ArmSeed]:
        base = {s: ArmSeed(**asdict(C5[s])) for s in s5}        # copies: the control fixture is never mutated
        for k, v in over.items():
            for s in s5:
                setattr(base[s], k, (Fraction(v[s]) if k in ("c", "x", "T") and v[s] is not None else v[s])
                        if isinstance(v, (list, tuple)) else v)
        return base

    expect("n5 integrity", decide_n5(_inputs(c5(), f5(T=T5), integrity=["x"]), rule), 0, "integrity")
    expect("n5 clears a", decide_n5(_inputs(c5(), f5(k=[1, 1, 1, 0, 0], c=["1/100"] * 3 + ["0"] * 2, T=T5)), rule),
           1, "clears_a")
    expect("n5 clears b", decide_n5(_inputs(c5(k=[1, 1, 1, 0, 0], c=["1/100"] * 3 + ["0"] * 2), f5(T=T5)), rule),
           1, "clears_b")
    expect("n5 clears c adopt (Delta = 1/20)",
           decide_n5(_inputs(c5(k=[1, 0, 0, 0, 0], c=["1/100", "0", "0", "0", "0"]),
                             f5(k=[1, 1, 1, 1, 0], c=["6/100", "6/100", "6/100", "8/100", "0"], T=T5)), rule),
           1, "clears_c_adopt")
    expect("n5 clears c worse",
           decide_n5(_inputs(c5(k=[1, 1, 1, 1, 0], c=["6/100", "6/100", "6/100", "8/100", "0"]),
                             f5(k=[1, 0, 0, 0, 0], c=["1/100", "0", "0", "0", "0"], T=T5)), rule),
           1, "clears_c_worse")
    r = decide_n5(_inputs(c5(k=[1, 0, 0, 0, 0], c=["1/100", "0", "0", "0", "0"]),
                          f5(k=[1, 0, 0, 0, 0], c=["1/100", "0", "0", "0", "0"], chi=[1, 1, 1, 0, 0], x=["1/100"] * 3 + ["0"] * 2,
                             T=T5)), rule)
    expect("n5 clears c record -> crossings a", r, 2, "crossings_a")
    if "clears in both arms" not in r["notes"]:
        failures.append("n5: 'clears in both arms' not recorded")
    r = decide_n5(_inputs(c5(), f5(k=[1, 1, 0, 0, 0], c=["1/100", "1/100", "0", "0", "0"], T=T5)), rule)
    if not any("clear not reproduced (2 of 5" in x for x in r["notes"]):
        failures.append(f"n5: clear-not-reproduced note missing {r['notes']}")
    expect("n5 d record -> targets a", r, 4, "targets_a")
    expect("n5 crossings b", decide_n5(_inputs(c5(chi=[1, 1, 1, 0, 0], x=["1/100"] * 3 + ["0"] * 2), f5(T=T5)), rule),
           2, "crossings_b")
    expect("n5 G=3", decide_n5(_inputs(c5(), f5(T=["4"] * 5), g={0: 1, 1: 1, 3: 1}), rule), 3,
           "discovered_not_consolidated")
    expect("n5 G=2 not enough -> null", decide_n5(_inputs(c5(), f5(T=["4"] * 5), g={0: 1, 1: 1}), rule), 5, "null")
    expect("n5 targets c", decide_n5(_inputs(c5(), f5(T=["422/100", "425/100", "377/100", "7/2", "7/2"])), rule), 4,
           "targets_c")
    # the thresholds come from the document
    tampered = json.loads(json.dumps({k: v for k, v in rule.items() if k != "_sha256"}))
    next(g for g in tampered["n3"]["gates"] if g["gate"] == 1)["clears_min"] = 3
    r = decide_n3(_inputs(C3, f3(k=[1, 1, 0], T=T)), tampered)
    if r["gate"] == 1:
        failures.append("decide_n3 ignored the rule document's clears_min")
    ok = not failures
    print(f"m7h_analysis self-test: {'PASS' if ok else 'FAIL'} ({len(failures)} failed) {failures}")
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["self-test"]:
        sys.exit(self_test())
    print(__doc__)
    sys.exit(2)
