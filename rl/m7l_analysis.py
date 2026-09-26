"""M7l analysis: the registered decision rule of the target-2 reward experiment (docs/rl_target2_m7l_decision_rule.json)
in exact integers / fractions, and the per-label quantities it reads. Pure: no game, no training, no file writes.

    python rl/m7l_analysis.py self-test      # every gate, outcome and inequality boundary on synthetic inputs

Arms: C = the historical Phase K v1 control (btt_reward_v2), T = btt_reward_v3_t2; seeds 0-2 paired by seed number.
Every parameter (target-ID sets, the tick deadline, thresholds) is read from the registered JSON (its sha256 is pinned
in the campaign manifest), never from constants here; decide() refuses a rule document of another schema.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import sys
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
REPO_ROOT = RL_DIR.parent
RULE_DOC = REPO_ROOT / "docs" / "rl_target2_m7l_decision_rule.json"
RULE_SCHEMA = "m7l_decision_rule_v1"
ARMS = ("C", "T")


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


# -- one episode ---------------------------------------------------------------------------------------------------


def episode_facts(e: Mapping[str, Any], P: Mapping[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """The registered per-episode facts of one tick-0 evaluation row (btt_eval_metrics_v1 identity and break ticks)."""
    em = e.get("eval_metrics") or {}
    p: List[str] = []
    if not em.get("ok") or em.get("contract") != "btt_eval_metrics_v1":
        p.append(f"episode {e.get('episode_id')}: no clean btt_eval_metrics_v1 record")
    fb = {int(k): int(v) for k, v in (em.get("first_break_tick") or {}).items()}
    broken = {int(i) for i in em.get("broken_ids") or []}
    mid = int(P["moving_target_id"])
    t2_tick = fb.get(mid)
    if set(fb) != broken or len(broken) != int(e.get("targets_broken", -1)):
        p.append(f"episode {e.get('episode_id')}: break ticks {sorted(fb)} / broken ids {sorted(broken)} / targets "
                 f"{e.get('targets_broken')} disagree")
    if bool(em.get("moving_target_broken")) != (t2_tick is not None) or em.get("moving_target_break_tick") != t2_tick \
            or int(em.get("moving_target_id", mid)) != mid:
        p.append(f"episode {e.get('episode_id')}: moving-target fields disagree with the break table")
    deadline = int(P["deadline_consumed_tick"])
    right = P["right_ids"]
    s_right = len(broken & set(P["static_right_ids"]))
    f = {
        "episode_id": e.get("episode_id"), "end_reason": e.get("end_reason"), "cleared": bool(e.get("cleared")),
        "targets": int(e.get("targets_broken", 0)), "t2": t2_tick is not None, "t2_tick": t2_tick,
        "static_all": len(broken - {mid}), "static_right": s_right,
        "L": t2_tick is not None and t2_tick <= deadline and s_right >= int(P["L_static_right_min"]),
        "R": all(i in fb for i in right) and max(fb[i] for i in right) <= deadline,
        "seven_right": all(i in fb for i in right),
        "sweep_tick": max(fb[i] for i in right) if all(i in fb for i in right) else None,
        "left_entry": em.get("first_left_entry") is not None,
        "left_ids": sorted(broken & set(P["left_ids"])),
        "fall": e.get("end_reason") == "fall",
        "native_action_digest": e.get("native_action_digest"),
    }
    return f, p


# -- one arm-seed (a final label) ------------------------------------------------------------------------------------


@dataclass
class ArmSeed:
    n: int                              # stochastic episodes counted (registered: 100)
    t2: int                             # episodes with native target 2 broken (any tick, any end)
    S: int                              # static targets broken, summed (every target except ID 2)
    S_right: int                        # the six static right targets broken, summed (reported)
    L: int
    R: int
    T: Optional[Fraction]               # mean targets over stochastic episodes that are not verified clears
    falls: int
    native_clears: int                  # stochastic + deterministic native clears of the label
    verified_clears: int
    stochastic_verified_clears: int
    left_entries: int
    left_target_episodes: int
    left_target_breaks: Dict[str, int] = field(default_factory=dict)
    seven_right: int = 0
    t2_ticks: List[int] = field(default_factory=list)
    t2_falls: int = 0

    def to_json(self) -> Dict[str, Any]:
        d = asdict(self)
        return {k: (str(v) if isinstance(v, Fraction) else v) for k, v in d.items()}

    @staticmethod
    def from_json(d: Mapping[str, Any]) -> "ArmSeed":
        d = dict(d)
        d["T"] = None if d.get("T") is None else Fraction(d["T"])
        return ArmSeed(**d)


def read_label(label_dir: Path) -> Dict[str, List[Dict[str, Any]]]:
    out = {}
    for mode in ("stochastic", "deterministic"):
        f = Path(label_dir) / mode / "evaluation.json"
        out[mode] = (json.loads(f.read_text(encoding="utf-8")).get("episodes") or []) if f.is_file() else []
    return out


def label_inputs(label_dir: Path, clear_doc: Optional[Mapping[str, Any]], P: Mapping[str, Any], *,
                 episodes: Optional[int] = None) -> Tuple[ArmSeed, List[str]]:
    """The registered quantities of one final label (the 100 stochastic episodes; clears over all 200) and the
    integrity problems found while computing them."""
    episodes = int(P["episodes_per_seed"]) if episodes is None else episodes
    rows = read_label(label_dir)
    p: List[str] = []
    if len(rows["stochastic"]) != episodes:
        p.append(f"{Path(label_dir).name}/stochastic: {len(rows['stochastic'])} episodes (planned {episodes})")
    verified = {str(r["native_action_digest"]) for r in (clear_doc or {}).get("clears") or [] if r.get("verified")}
    native = [e for e in rows["stochastic"] + rows["deterministic"] if e.get("cleared")]
    for e in native:
        if str(e.get("native_action_digest")) not in verified:
            p.append(f"{Path(label_dir).name}: native clear {e.get('episode_id')} has no passed clear verification")
    is_v = lambda e: bool(e.get("cleared")) and str(e.get("native_action_digest")) in verified  # noqa: E731
    facts = []
    for e in rows["stochastic"]:
        f, fp = episode_facts(e, P)
        facts.append(f)
        p.extend(fp)
    rest = [e for e in rows["stochastic"] if not is_v(e)]
    left_breaks = {str(i): sum(1 for f in facts if i in f["left_ids"]) for i in P["left_ids"]}
    a = ArmSeed(n=len(facts), t2=sum(f["t2"] for f in facts), S=sum(f["static_all"] for f in facts),
                S_right=sum(f["static_right"] for f in facts), L=sum(f["L"] for f in facts),
                R=sum(f["R"] for f in facts),
                T=Fraction(sum(int(e["targets_broken"]) for e in rest), len(rest)) if rest else None,
                falls=sum(f["fall"] for f in facts), native_clears=len(native),
                verified_clears=sum(1 for e in native if is_v(e)),
                stochastic_verified_clears=sum(1 for e in rows["stochastic"] if is_v(e)),
                left_entries=sum(f["left_entry"] for f in facts),
                left_target_episodes=sum(1 for f in facts if f["left_ids"]), left_target_breaks=left_breaks,
                seven_right=sum(f["seven_right"] for f in facts),
                t2_ticks=sorted(int(f["t2_tick"]) for f in facts if f["t2"]),
                t2_falls=sum(1 for f in facts if f["t2"] and f["fall"]))
    return a, p


def deterministic_facts(label_dir: Path, P: Mapping[str, Any]) -> Dict[str, Any]:
    """Reported, never gating: the final deterministic play (100 episodes) and its collapse share (the M7e definition:
    the longest run of one joint action / the episode length of the play; collapsed iff >= 1/2)."""
    import m7e_idle_analysis as ia

    rows = read_label(label_dir)["deterministic"]
    if not rows:
        return {"episodes": 0}
    facts = [episode_facts(e, P)[0] for e in rows]
    digests = {e.get("native_action_digest") for e in rows}
    out: Dict[str, Any] = {"episodes": len(rows), "distinct_action_digests": len(digests),
                           "targets": sorted({f["targets"] for f in facts}), "end_reasons": sorted({f["end_reason"] for f in facts}),
                           "t2": sum(f["t2"] for f in facts), "L": sum(f["L"] for f in facts), "R": sum(f["R"] for f in facts),
                           "native_clears": sum(f["cleared"] for f in facts),
                           "left_entries": sum(f["left_entry"] for f in facts)}
    art = rows[0].get("artifact_dir")
    if art:
        d = Path(art)
        d = d if d.is_absolute() else REPO_ROOT / d
        acts = [json.loads(x) for x in (d / "actions.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        st = ia.analyse_actions(acts)
        share = Fraction(st.max_run, st.ticks) if st.ticks else None
        out["collapse"] = {"max_run": st.max_run, "length": st.ticks,
                           "collapse_share": None if share is None else round(float(share), 4),
                           "collapsed": share is not None and share >= frac(P["collapse_share_min"])}
    return out


def t2_timing(ticks: Sequence[int]) -> Dict[str, Any]:
    t = sorted(int(x) for x in ticks)
    return {"n": len(t), "ticks": t, "median": statistics.median(t) if t else None,
            "min": t[0] if t else None, "max": t[-1] if t else None,
            "by_deadline": sum(1 for x in t if x <= 2699)}


# -- the rule --------------------------------------------------------------------------------------------------------


def quantities(inputs: Mapping[str, Mapping[int, ArmSeed]], P: Mapping[str, Any]) -> Dict[str, Any]:
    seeds = P["seeds"]
    A = {a: inputs[a] for a in ARMS}
    q: Dict[str, Any] = {"seeds": list(seeds)}
    q["n"] = {a: {s: A[a][s].n for s in seeds} for a in ARMS}
    q["t2"] = {a: {s: A[a][s].t2 for s in seeds} for a in ARMS}
    q["gain_episodes"] = {s: A["T"][s].t2 - A["C"][s].t2 for s in seeds}
    q["seeds_with_gain"] = [s for s in seeds if q["gain_episodes"][s] >= int(P["gain_min_episodes"])]
    q["pooled_t2"] = {a: sum(A[a][s].t2 for s in seeds) for a in ARMS}
    q["pooled_n"] = {a: sum(A[a][s].n for s in seeds) for a in ARMS}
    q["pooled_rate"] = {a: Fraction(q["pooled_t2"][a], q["pooled_n"][a]) for a in ARMS}
    q["pooled_S"] = {a: sum(A[a][s].S for s in seeds) for a in ARMS}
    q["static_mean"] = {a: Fraction(q["pooled_S"][a], q["pooled_n"][a]) for a in ARMS}
    q["static_diff"] = q["static_mean"]["T"] - q["static_mean"]["C"]
    q["L"] = {a: {s: A[a][s].L for s in seeds} for a in ARMS}
    q["R"] = {a: {s: A[a][s].R for s in seeds} for a in ARMS}
    q["pooled_L"] = {a: sum(A[a][s].L for s in seeds) for a in ARMS}
    q["seeds_with_R"] = {a: [s for s in seeds if A[a][s].R >= int(P["relevance_R_min_per_seed"])] for a in ARMS}
    return q


def decide(inputs: Mapping[str, Any], rule: Mapping[str, Any]) -> Dict[str, Any]:
    """Gate 0 (integrity) -> gate 1 (learned: 1a seeds with a gain, 1b pooled ratio) -> gate 2 (no static loss) ->
    gate 3 (first-clear relevance, secondary). Every condition is evaluated and reported; the outcome is the first
    registered outcome whose conditions hold."""
    if rule.get("schema") != RULE_SCHEMA:
        raise ValueError(f"rule schema {rule.get('schema')}")
    P = params(rule)
    integrity = list(inputs.get("integrity") or [])
    out: Dict[str, Any] = {"rule_sha256": rule.get("_sha256"), "integrity": integrity}
    if integrity:
        o = rule["outcomes"]["no_decision"]
        return dict(out, outcome="no_decision", gate=0, primary=None, response=o["response"], quantities=None)
    for a in ARMS:
        for s in P["seeds"]:
            if inputs[a][s].n != int(P["episodes_per_seed"]):
                raise ValueError(f"{a} s{s}: {inputs[a][s].n} episodes reach decide() (integrity must stop this)")
    q = quantities(inputs, P)
    g1a = len(q["seeds_with_gain"]) >= int(P["gain_seeds_min"])
    g1b = q["pooled_t2"]["T"] * q["pooled_n"]["C"] >= int(P["pooled_ratio_min"]) * q["pooled_t2"]["C"] * q["pooled_n"]["T"]
    g2 = q["static_diff"] >= -frac(P["static_loss_max_per_episode"])
    g3 = len(q["seeds_with_R"]["T"]) >= int(P["relevance_R_seeds_min"]) \
        or q["pooled_L"]["T"] >= int(P["relevance_L_pooled_min"])
    gates = {"1a_seed_gain": g1a, "1b_pooled_ratio": g1b, "1_learned": g1a and g1b, "2_no_static_loss": g2,
             "primary": g1a and g1b and g2, "3_first_clear_relevance": g3}
    if not gates["1_learned"]:
        key = "not_learned"
    elif not g2:
        key = "learned_with_static_loss"
    elif not g3:
        key = "learned_not_early"
    else:
        key = "first_clear_relevant"
    o = rule["outcomes"][key]
    return dict(out, outcome=key, gate=o["gate"], primary=gates["primary"], gates=gates, response=o["response"],
                claims=o.get("claims"), quantities=_json(q))


def _json(v: Any) -> Any:
    if isinstance(v, Fraction):
        return str(v)
    if isinstance(v, Mapping):
        return {str(k): _json(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json(x) for x in v]
    return v


# -- self-test (synthetic inputs) --------------------------------------------------------------------------------------


def _arm(t2: int, S: int = 450, L: int = 0, R: int = 0, n: int = 100) -> ArmSeed:
    return ArmSeed(n=n, t2=t2, S=S, S_right=S, L=L, R=R, T=Fraction(S + t2, n), falls=0, native_clears=0,
                   verified_clears=0, stochastic_verified_clears=0, left_entries=0, left_target_episodes=0)


def self_test(rule_path: Path = RULE_DOC) -> int:
    rule = load_rule(rule_path)
    fails: List[str] = []

    def run(c: Sequence[ArmSeed], t: Sequence[ArmSeed], integrity: Sequence[str] = ()) -> Dict[str, Any]:
        return decide({"C": dict(enumerate(c)), "T": dict(enumerate(t)), "integrity": list(integrity)}, rule)

    def expect(name: str, d: Mapping[str, Any], outcome: str) -> None:
        ok = d["outcome"] == outcome
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {d['outcome']} (want {outcome})")
        if not ok:
            fails.append(name)

    C = [_arm(1), _arm(0), _arm(2)]                                             # the registered control counts
    expect("integrity first", run(C, [_arm(50)] * 3, ["x"]), "no_decision")
    expect("no gain", run(C, [_arm(1), _arm(0), _arm(2)]), "not_learned")
    # 1a boundary: exactly +5 in two seeds; pooled 6+5+2 = 13 >= 9
    expect("gain exactly 5 in two seeds", run(C, [_arm(6), _arm(5), _arm(2)]), "learned_not_early")
    expect("gain 4 and 5", run(C, [_arm(5), _arm(5), _arm(2)]), "not_learned")
    expect("gain in one seed only", run(C, [_arm(30), _arm(0), _arm(2)]), "not_learned")
    # 1b boundary: C pooled 3 -> T pooled >= 9 (exactly 9 passes, 8 fails) with two seed gains of >= 5
    expect("pooled exactly 3x", run([_arm(0), _arm(0), _arm(4)], [_arm(5), _arm(5), _arm(2)]), "learned_not_early")
    expect("pooled zero control", run([_arm(0), _arm(0), _arm(0)], [_arm(5), _arm(5), _arm(0)]), "learned_not_early")
    expect("pooled ratio boundary fail", run([_arm(0), _arm(0), _arm(5)], [_arm(5), _arm(5), _arm(4)]), "not_learned")
    # gate 2 boundary: a loss of exactly 1/2 per episode (150 over 300) passes, 151 fails
    Cs = [_arm(1, S=450), _arm(0, S=450), _arm(2, S=450)]
    expect("static loss exactly 1/2", run(Cs, [_arm(10, S=400), _arm(10, S=400), _arm(2, S=400)]), "learned_not_early")
    expect("static loss above 1/2", run(Cs, [_arm(10, S=400), _arm(10, S=400), _arm(2, S=399)]), "learned_with_static_loss")
    # gate 3: pooled L >= 5 or R >= 1 in >= 1 seed
    expect("L pooled 5", run(C, [_arm(10, L=2), _arm(10, L=2), _arm(2, L=1)]), "first_clear_relevant")
    expect("L pooled 4", run(C, [_arm(10, L=2), _arm(10, L=2), _arm(2)]), "learned_not_early")
    expect("R in one seed", run(C, [_arm(10), _arm(10), _arm(2, R=1)]), "first_clear_relevant")
    expect("relevance without learning", run(C, [_arm(1, L=9, R=3), _arm(0), _arm(2)]), "not_learned")
    try:
        run(C, [_arm(10, n=99), _arm(10), _arm(2)])
        fails.append("an incomplete label reached decide()")
        print("[FAIL] an incomplete label reached decide()")
    except ValueError:
        print("[PASS] an incomplete label is refused by decide()")
    # episode facts on a constructed row
    P = params(rule)
    em = {"contract": "btt_eval_metrics_v1", "ok": True, "first_break_tick": {"0": 10, "3": 20, "4": 30, "5": 40, "7": 50,
                                                                           "2": 2699}, "broken_ids": [0, 3, 4, 5, 7, 2],
          "moving_target_broken": True, "moving_target_break_tick": 2699, "moving_target_id": 2, "first_left_entry": None}
    f, fp = episode_facts({"episode_id": "x", "targets_broken": 6, "end_reason": "horizon", "eval_metrics": em}, P)
    ok = not fp and f["L"] and not f["R"] and f["static_all"] == 5 and f["static_right"] == 5
    em2 = dict(em, first_break_tick=dict(em["first_break_tick"], **{"9": 2699}), broken_ids=em["broken_ids"] + [9])
    f2, fp2 = episode_facts({"episode_id": "y", "targets_broken": 7, "end_reason": "horizon", "eval_metrics": em2}, P)
    ok &= not fp2 and f2["R"] and f2["L"] and f2["sweep_tick"] == 2699
    em3 = dict(em2, first_break_tick=dict(em2["first_break_tick"], **{"9": 2700}))
    f3, _ = episode_facts({"episode_id": "z", "targets_broken": 7, "end_reason": "horizon", "eval_metrics": em3}, P)
    ok &= not f3["R"] and f3["L"]
    em4 = dict(em, first_break_tick=dict(em["first_break_tick"], **{"2": 2700}), moving_target_break_tick=2700)
    f4, _ = episode_facts({"episode_id": "w", "targets_broken": 6, "end_reason": "horizon", "eval_metrics": em4}, P)
    ok &= not f4["L"]
    print(f"[{'PASS' if ok else 'FAIL'}] episode facts: L / R at the 2,699 boundary, static counts")
    if not ok:
        fails.append("episode facts")
    print(f"self-test: {'PASS' if not fails else 'FAIL ' + str(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["self-test"]:
        raise SystemExit(self_test())
    print(__doc__)
    raise SystemExit(2)
