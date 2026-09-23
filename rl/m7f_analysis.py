"""M7f Phase G: six-target ceiling analysis from the target-identity replays.

Joins every historical row of the replay manifest (docs/rl_target_ceiling_m7f_manifest.json) to the replay record of
its canonical action sequence (runs/m7f/replay/records_*.jsonl, one record per native action digest) and computes,
per population, weighted by historical rows (identical sequences count once per row that produced them):

  per-target break / miss probability (Wilson 95 % CI), break order and break-tick distributions, first-break shares,
  pairwise co-occurrence, broken / remaining subsets, six-target subsets, target-to-target transitions and time gaps,
  the last target before a long no-progress tail, region visitation (from the replayed positions), checkpoint
  trajectories, and seed / mode / milestone contrasts.

Only a record with ok == true (every historical field reproduced and the diagnostic valid on every reply) is used;
the analysis refuses to run if any selected sequence is missing or not ok.

Outputs docs/rl_target_ceiling_m7f.json. Self-test: python rl/m7f_analysis.py --self-test
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import m7f_targets as mt  # noqa: E402

REPO_ROOT = RL_DIR.parent
MANIFEST = REPO_ROOT / "docs" / "rl_target_ceiling_m7f_manifest.json"
REPLAY = REPO_ROOT / "runs" / "m7f" / "replay"
MAPPING = REPO_ROOT / "docs" / "rl_target_identity_m7f_mapping.json"
OUT = REPO_ROOT / "docs" / "rl_target_ceiling_m7f.json"
IDS = list(range(mt.TARGET_COUNT))
EARLY_TARGET_TICK = 600      # m7e_idle_analysis.EARLY_TARGET_TICK
LONG_TAIL_TICKS = 1800       # m7e_idle_analysis.M7D_IDLE_TAIL_TICKS
FINAL_TRANSITIONS = 3072000  # M7e budget; M7d final is 1,024,000


def wilson(k: int, n: int, z: float = 1.959964) -> Tuple[Optional[float], Optional[float]]:
    if n <= 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)


def _q(xs: Sequence[float], q: float) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return float(s[lo] + (s[hi] - s[lo]) * (k - lo))


# -- data -----------------------------------------------------------------------------------------------


def load(manifest: Path = MANIFEST, replay: Path = REPLAY, *,
         allow_partial: bool = False) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """One entry per historical row with its replayed identity outcome. allow_partial (preview only, never written
    to docs) skips sequences not replayed yet; divergent records always abort."""
    man = json.loads(Path(manifest).read_text(encoding="utf-8"))
    recs: Dict[str, Dict[str, Any]] = {}
    for p in sorted(Path(replay).glob("records_*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                recs[r["digest"]] = r
    missing = [s["digest"] for s in man["sequences"] if s["digest"] not in recs]
    bad = [d for d, r in recs.items() if not r.get("ok")]
    if bad or (missing and not allow_partial):
        raise SystemExit(f"replay incomplete or divergent: {len(missing)} missing, {len(bad)} not ok "
                         f"(first: {(missing + bad)[:3]}); diagnose before analysing")
    rows: List[Dict[str, Any]] = []
    seen_rows = set()
    for s in man["sequences"]:
        if s["digest"] not in recs:
            continue
        r = recs[s["digest"]]
        episode = episode_from_record(r)
        episode["actions_summary"] = actions_summary(s["artifact_dir"])
        for row in s["rows"]:
            key = (row["row_file"], row["episode_id"])
            if key in seen_rows:
                continue
            seen_rows.add(key)
            rows.append({**row, "digest": s["digest"], "strata": s["strata"], **episode})
    import hashlib

    doc_map = json.loads(MAPPING.read_text(encoding="utf-8"))
    expected_map = json.dumps([{k: t[k] for k in ("id", "animated", "spawn", "region")} for t in doc_map["targets"]],
                              sort_keys=True, separators=(",", ":"))
    expected_sha = hashlib.sha256(expected_map.encode()).hexdigest()
    seen_maps = sorted({r["mapping_sha256"] for r in recs.values()})
    meta = {"records": len(recs), "sequences": len(man["sequences"]), "rows_joined": len(rows),
            "executable_sha256": sorted({r["executable_sha256"] for r in recs.values()}),
            "mapping_sha256": seen_maps,
            "mapping_equals_published_table": seen_maps == [expected_sha],
            "mapping": [{k: t[k] for k in ("id", "animated", "spawn", "region")} for t in doc_map["targets"]],
            "snapshots_checked": sum(r.get("snapshots_checked", 0) for r in recs.values()),
            "host_frame_equal_final": sum(1 for r in recs.values() if r.get("host_frame_equal_final")),
            "population": man["population"], "strata": man["strata"]}
    return rows, meta


def episode_from_record(r: Mapping[str, Any]) -> Dict[str, Any]:
    events = sorted(r["events"], key=lambda e: e["break_order"])
    length = r["expected"]["length"]
    ticks = [e["consumed_tick"] for e in events]
    tail = length - (ticks[-1] + 1) if ticks else length
    pos = r.get("positions") or {}
    return {
        "order": [e["target_id"] for e in events],
        "ticks": ticks,
        "broken": sorted(e["target_id"] for e in events),
        "remaining": r["final_remaining_ids"],
        "length": length,
        "end": r["expected"]["end_reason"],
        "tail": tail,
        "early_then_stagnant": bool(ticks) and ticks[0] <= EARLY_TARGET_TICK and tail >= LONG_TAIL_TICKS,
        "last_before_half": bool(ticks) and ticks[-1] < 0.5 * length,
        "positions": pos,
    }


# -- metrics --------------------------------------------------------------------------------------------


def metrics(rows: Sequence[Mapping[str, Any]], regions: Mapping[int, str]) -> Dict[str, Any]:
    n = len(rows)
    out: Dict[str, Any] = {"rows": n, "unique_sequences": len({r["digest"] for r in rows})}
    if n == 0:
        return out
    out["targets_histogram"] = dict(sorted(Counter(len(r["broken"]) for r in rows).items()))
    out["mean_targets"] = round(statistics.fmean(len(r["broken"]) for r in rows), 4)
    per_id = {}
    for i in IDS:
        hit = [r for r in rows if i in r["broken"]]
        k = len(hit)
        ticks = [r["ticks"][r["order"].index(i)] for r in hit]
        ranks = [r["order"].index(i) + 1 for r in hit]
        lo, hi = wilson(k, n)
        per_id[str(i)] = {
            "region": regions[i], "break_rate": round(k / n, 4), "break_ci95": [lo, hi],
            "miss_rate": round(1 - k / n, 4), "episodes_breaking": k,
            "first_break_share": round(sum(1 for r in rows if r["order"][:1] == [i]) / n, 4),
            "mean_order_rank": round(statistics.fmean(ranks), 3) if ranks else None,
            "tick_min": min(ticks) if ticks else None, "tick_p10": _q(ticks, 0.1), "tick_median": _q(ticks, 0.5),
            "tick_p90": _q(ticks, 0.9),
            "rule_of_three_upper": round(3 / n, 4) if k == 0 else None,
        }
    out["per_target"] = per_id
    miss_rank = sorted(IDS, key=lambda i: (-per_id[str(i)]["miss_rate"], i))
    out["most_missed_order"] = miss_rank
    co = [[round(sum(1 for r in rows if i in r["broken"] and j in r["broken"]) / n, 4) for j in IDS] for i in IDS]
    out["cooccurrence"] = co
    out["broken_subsets_top"] = [{"ids": list(k), "rows": v} for k, v in
                                 Counter(tuple(r["broken"]) for r in rows).most_common(12)]
    out["remaining_subsets_top"] = [{"ids": list(k), "rows": v} for k, v in
                                    Counter(tuple(r["remaining"]) for r in rows).most_common(12)]
    six = [r for r in rows if len(r["broken"]) == 6]
    out["six_target"] = {"rows": len(six), "subsets": [{"broken": list(k), "rows": v} for k, v in
                                                      Counter(tuple(r["broken"]) for r in six).most_common()],
                         "never_in_six": [i for i in IDS if all(i not in r["broken"] for r in six)] if six else None}
    five_plus = [r for r in rows if len(r["broken"]) >= 5]
    out["distinct_subsets_5plus"] = len({tuple(r["broken"]) for r in five_plus})
    trans: Counter = Counter()
    gaps: Dict[str, List[int]] = defaultdict(list)
    for r in rows:
        prev, prev_t = "start", -1
        for i, t in zip(r["order"], r["ticks"]):
            key = f"{prev}->{i}"
            trans[key] += 1
            gaps[key].append(t - prev_t if prev != "start" else t)
            prev, prev_t = i, t
    out["transitions_top"] = [{"transition": k, "rows": v, "gap_median": _q(gaps[k], 0.5)}
                              for k, v in trans.most_common(20)]
    all_gaps = [g for k, v in gaps.items() if not k.startswith("start") for g in v]
    out["gap_between_breaks"] = {"n": len(all_gaps), "p10": _q(all_gaps, 0.1), "median": _q(all_gaps, 0.5),
                                 "p90": _q(all_gaps, 0.9)}
    for flag in ("early_then_stagnant", "last_before_half"):
        sel = [r for r in rows if r[flag]]
        out[flag] = {"rows": len(sel), "rate": round(len(sel) / n, 4),
                     "last_target": dict(Counter(r["order"][-1] for r in sel if r["order"]).most_common()),
                     "remaining_top": [{"ids": list(k), "rows": v} for k, v in
                                       Counter(tuple(r["remaining"]) for r in sel).most_common(5)]}
    left = [i for i in IDS if regions[i] == "left_of_wall"]
    moving = [i for i in IDS if regions[i] == "upper_right_moving"]
    right = [i for i in IDS if regions[i] == "right"]
    central = [i for i in IDS if regions[i] == "central"]
    out["region_rates"] = {
        "any_left": round(sum(1 for r in rows if set(r["broken"]) & set(left)) / n, 4),
        "all_left": round(sum(1 for r in rows if set(left) <= set(r["broken"])) / n, 4),
        "moving": round(sum(1 for r in rows if set(moving) & set(r["broken"])) / n, 4),
        "right": round(sum(1 for r in rows if set(right) & set(r["broken"])) / n, 4),
        "all_central": round(sum(1 for r in rows if set(central) <= set(r["broken"])) / n, 4),
        "all_central_and_right": round(sum(1 for r in rows if set(central + right) <= set(r["broken"])) / n, 4),
    }
    pos = [r["positions"] for r in rows if r.get("positions")]
    if pos:
        entered = [p for p in pos if (p.get("region_steps") or {}).get("left_of_wall", 0) > 0]
        out["visitation"] = {
            "rows_with_positions": len(pos),
            "entered_left_of_wall": round(len(entered) / len(pos), 4),
            "entered_left_rows": len(entered),
            "entered_left_but_no_left_target": sum(1 for r in rows if r.get("positions") and
                                                   (r["positions"].get("region_steps") or {}).get("left_of_wall", 0) > 0
                                                   and not set(r["broken"]) & set(left)),
            "left_steps_median_when_entered": _q([p["region_steps"]["left_of_wall"] for p in entered], 0.5),
            "first_tick_left_median": _q([p["first_tick_left_of_wall"] for p in entered], 0.5),
            "left_max_y_median": _q([p["left_of_wall_max_y"] for p in entered if p.get("left_of_wall_max_y") is not None], 0.5),
            "min_x_p10": _q([p["min_x"] for p in pos if p.get("min_x") is not None], 0.1),
            "min_x_median": _q([p["min_x"] for p in pos if p.get("min_x") is not None], 0.5),
            "max_x_median": _q([p["max_x"] for p in pos if p.get("max_x") is not None], 0.5),
            "max_y_median": _q([p["max_y"] for p in pos if p.get("max_y") is not None], 0.5),
            "entered_right_block": round(sum(1 for p in pos if p["region_steps"].get("right", 0) > 0) / len(pos), 4),
            # the tall wall's top is y 3000 (its ledge spans x -2100..-1200); its right face is x -1800, where a
            # standing Mario's origin stops at x -1650
            "reached_wall_top_height": round(sum(1 for p in pos if (p.get("max_y") or -1e9) >= 2990.0) / len(pos), 4),
            "touched_wall_face": round(sum(1 for p in pos if (p.get("min_x") or 1e9) <= -1640.0) / len(pos), 4),
            "min_x_min": min((p["min_x"] for p in pos if p.get("min_x") is not None), default=None),
            "max_y_max": max((p["max_y"] for p in pos if p.get("max_y") is not None), default=None),
            "max_y_p90": _q([p["max_y"] for p in pos if p.get("max_y") is not None], 0.9),
            "wall_column_visits": round(sum(1 for p in pos if p["region_steps"].get("wall_column", 0) > 0) / len(pos), 4),
            "region_step_share": {k: round(sum(p["region_steps"].get(k, 0) for p in pos) /
                                           max(1, sum(sum(p["region_steps"].values()) for p in pos)), 4)
                                  for k in ("left_of_wall", "wall_column", "central", "right")},
        }
    acts = [r["actions_summary"] for r in rows if r.get("actions_summary")]
    if acts:
        out["action_use"] = {
            "b_share_median": _q([a["b_share"] for a in acts], 0.5),
            "up_b_presses_median": _q([a["up_b_presses"] for a in acts], 0.5),
            "rows_with_up_b": round(sum(1 for a in acts if a["up_b_presses"] > 0) / len(acts), 4),
            "jump_button_share_median": _q([a["jump_share"] for a in acts], 0.5),
        }
    return out


B_BUTTON, JUMP_BUTTONS = 0x4000, (0x0008, 0x0002)  # B; C-up / C-left (Track 1 jump buttons)


def actions_summary(artifact_dir: str) -> Dict[str, Any]:
    """Descriptive use of B (Mario's fireball / specials) and jumps in a canonical action sequence. A new press is a
    step whose button differs from the previous step's; up-B is a new B press with stick_y >= 53 (upward)."""
    n = b = jumps = up_b = 0
    prev = 0
    with open(REPO_ROOT / artifact_dir / "actions.jsonl", encoding="utf-8") as fp:
        for line in fp:
            a = json.loads(line)
            n += 1
            btn = a["buttons"]
            if btn == B_BUTTON:
                b += 1
                if prev != B_BUTTON and a["stick_y"] >= 53:
                    up_b += 1
            if btn in JUMP_BUTTONS:
                jumps += 1
            prev = btn
    return {"steps": n, "b_share": round(b / n, 4) if n else 0.0, "up_b_presses": up_b,
            "jump_share": round(jumps / n, 4) if n else 0.0}


def population(rows: Sequence[Mapping[str, Any]], **where: Any) -> List[Mapping[str, Any]]:
    def ok(r: Mapping[str, Any]) -> bool:
        for k, v in where.items():
            if callable(v):
                if not v(r.get(k)):
                    return False
            elif r.get(k) != v:
                return False
        return True

    return [r for r in rows if ok(r)]


def analyse(rows: Sequence[Mapping[str, Any]], meta: Mapping[str, Any], regions: Mapping[int, str]) -> Dict[str, Any]:
    res: Dict[str, Any] = {"schema": "battleship_m7f_ceiling_analysis_v1", "contract": mt.CONTRACT_ID,
                           "meta": dict(meta), "regions": {str(i): regions[i] for i in IDS}, "populations": {}}
    P = res["populations"]

    def add(name: str, sel: Sequence[Mapping[str, Any]], note: str = "") -> None:
        P[name] = {"note": note, **metrics(sel, regions)}

    ev = dict(source="evaluation")
    for m in ("m7e", "m7d"):
        runs = sorted({r["run"] for r in rows if r["milestone"] == m and r["run"] != "random_baseline"})
        for run in runs:
            for mode in ("stochastic", "deterministic"):
                add(f"{run}/final/{mode}", population(rows, milestone=m, run=run, set="final", mode=mode, **ev))
    add("m7e/final/stochastic/pooled", population(rows, milestone="m7e", set="final", mode="stochastic", **ev))
    add("m7d_v2/final/stochastic/pooled", population(rows, milestone="m7d", set="final", mode="stochastic",
                                                     reward_contract="btt_reward_v2", **ev))
    add("m7d_v1/final/stochastic/pooled", population(rows, milestone="m7d", set="final", mode="stochastic",
                                                     reward_contract="btt_reward_v1", **ev))
    add("m7e/initial/stochastic/pooled", population(rows, milestone="m7e", set="initial", mode="stochastic", **ev),
        "the untrained policies (initial checkpoint, near-maximal entropy) of the three M7e seeds")
    add("m7e/curve/stochastic/pooled", population(rows, milestone="m7e", set_kind="curve", mode="stochastic", **ev),
        "all nine intermediate checkpoints of the three M7e seeds")
    add("training_replayable", population(rows, source="training"),
        "preserved training artifacts only (a biased subset: new-best and periodic preservation)")
    # checkpoint trajectory (M7e stochastic): initial, 9 curve points, final
    traj: Dict[str, Any] = {}
    for seed in (0, 1, 2):
        run = f"m7e_s{seed}_v2"
        points = []
        for set_label in ["initial"] + sorted({r["set"] for r in rows if r["run"] == run and r["set_kind"] == "curve"}) \
                + ["final"]:
            sel = population(rows, milestone="m7e", run=run, set=set_label, mode="stochastic", **ev)
            t = 0 if set_label == "initial" else (FINAL_TRANSITIONS if set_label == "final"
                                                   else int(set_label.split("_t")[1]))
            m_ = metrics(sel, regions)
            points.append({"set": set_label, "transitions": t, "rows": m_["rows"],
                           "mean_targets": m_.get("mean_targets"),
                           "break_rate": {i: m_["per_target"][str(i)]["break_rate"] for i in IDS} if sel else None,
                           "max_targets": max((len(r["broken"]) for r in sel), default=None)})
        first_seen = {}
        for i in IDS:
            first_seen[str(i)] = next((p["transitions"] for p in points if p["break_rate"] and p["break_rate"][i] > 0),
                                      None)
        det = [{"set": s, "ids": population(rows, milestone="m7e", run=run, set=s, mode="deterministic", **ev)[0]["broken"]
                if population(rows, milestone="m7e", run=run, set=s, mode="deterministic", **ev) else None}
               for s in ["initial"] + sorted({r["set"] for r in rows if r["run"] == run and r["set_kind"] == "curve"})
               + ["final"]]
        traj[run] = {"stochastic_points": points, "first_checkpoint_breaking": first_seen,
                     "deterministic_ids_by_point": det}
    res["m7e_checkpoint_trajectory"] = traj
    add("six_target_all_rows", [r for r in rows if len(r["broken"]) == 6],
        "every replayable six-target row (evaluation + preserved training), weighted by rows")
    add("selection_bias_sample", [r for r in rows if "selection_bias_sample" in r["strata"]],
        "rows of the deterministic hash sample of otherwise unselected replayable sequences")
    add("random_baseline_kept", population(rows, run="random_baseline"), "the 3 kept random rows per milestone")
    uniq: Dict[str, Mapping[str, Any]] = {}
    for r in rows:
        uniq.setdefault(r["digest"], r)
    add("all_replayed_unique", list(uniq.values()), "every replayed sequence once (unweighted)")
    ever = sorted({i for r in rows for i in r["broken"]})
    res["reachability"] = {"ids_ever_broken": ever, "ids_never_broken": [i for i in IDS if i not in ever],
                           "unique_sequences": len(uniq),
                           "per_id_unique_sequences_breaking": {str(i): sum(1 for r in uniq.values() if i in r["broken"])
                                                                for i in IDS}}
    res["hypothesis"] = hypothesis(res, regions)
    res["tas_reference"] = tas_reference()
    return res


def tas_reference() -> Dict[str, Any]:
    """The 7.43 TAS on the same descriptors (447 consumed rows); its target order and positions come from the M7f
    validation (docs/rl_target_identity_m7f_validation.json / mapping)."""
    from btti_replay import read_btti_rows

    rows = read_btti_rows(str(REPO_ROOT / "tas_input_2" / "mario_743.btti"))[:447]
    b = [i for i, r in enumerate(rows) if r.buttons == B_BUTTON]
    up_b = [i for i in b if (i == 0 or rows[i - 1].buttons != B_BUTTON) and rows[i].stick_y >= 53]
    val = json.loads((REPO_ROOT / "docs" / "rl_target_identity_m7f_validation.json").read_text(encoding="utf-8"))
    return {"order": val["tas"]["order"], "ticks": [e["consumed_tick"] for e in val["tas"]["events"]],
            "b_presses": len(b), "b_ticks": b, "up_b_ticks": up_b, "steps": len(rows),
            "note": "Mario climbs to the wall's top ledge (y 3000 at tick 316), crosses over the wall top at y "
                    "~3400-3500 (ticks 340-358) and descends on the left side (min x -4071); several targets break "
                    "while Mario is far from them (projectiles)"}


def hypothesis(res: Mapping[str, Any], regions: Mapping[int, str]) -> Dict[str, Any]:
    P = res["populations"]
    left = [i for i in IDS if regions[i] == "left_of_wall"]
    moving = [i for i in IDS if regions[i] == "upper_right_moving"]
    fin = P["m7e/final/stochastic/pooled"]
    six = P["six_target_all_rows"]
    allu = P["all_replayed_unique"]
    ranks = fin["most_missed_order"]
    out = {
        "left_ids": left, "moving_ids": moving,
        "q1_left_among_most_missed": {"most_missed_order_m7e_final": ranks,
                                      "left_ids_are_top3_missed": sorted(ranks[:3]) == sorted(left) if len(left) == 3
                                      else None,
                                      "left_miss_rates": {i: fin["per_target"][str(i)]["miss_rate"] for i in left}},
        "q2_all_three_left_ever": {"rows_all_left_any_population": None,
                                   "unique_sequences_breaking_any_left": sum(
                                       allu["per_target"][str(i)]["episodes_breaking"] for i in left),
                                   "all_left_rate_unique": allu["region_rates"]["all_left"]},
        "q3_six_dominated_by_central_right": six.get("six_target"),
        "q4_additional_missed": {"moving_miss_rate_m7e_final": {i: fin["per_target"][str(i)]["miss_rate"]
                                                                for i in moving},
                                 "never_in_six": (six.get("six_target") or {}).get("never_in_six")},
        "q7_distinct_5plus_subsets_all": allu.get("distinct_subsets_5plus"),
    }
    return out


def render_tables(res: Mapping[str, Any]) -> str:
    """Markdown tables generated from the analysis JSON (embedded verbatim in docs/rl_target_ceiling_m7f.md)."""
    P = res["populations"]
    reg = res["regions"]
    out: List[str] = []

    def pct(x: Optional[float]) -> str:
        return "-" if x is None else f"{100 * x:.1f}"

    cols = ["m7e_s0_v2/final/stochastic", "m7e_s1_v2/final/stochastic", "m7e_s2_v2/final/stochastic",
            "m7e/final/stochastic/pooled", "m7d_v2/final/stochastic/pooled", "m7d_v1/final/stochastic/pooled",
            "selection_bias_sample", "all_replayed_unique"]
    heads = ["M7e s0", "M7e s1", "M7e s2", "M7e pooled", "M7d v2", "M7d v1", "bias sample", "all unique"]
    out.append("Per-target break rate, % of rows (95 % Wilson CI for the M7e pooled column):\n")
    out.append("| ID | region | " + " | ".join(heads) + " |")
    out.append("| --- | --- | " + " | ".join("---" for _ in heads) + " |")
    for i in IDS:
        cells = []
        for c in cols:
            pt = (P.get(c) or {}).get("per_target", {}).get(str(i))
            if not pt:
                cells.append("-")
                continue
            s = pct(pt["break_rate"])
            if c == "m7e/final/stochastic/pooled":
                s += f" [{pct(pt['break_ci95'][0])}, {pct(pt['break_ci95'][1])}]"
            cells.append(s)
        out.append(f"| {i} | {reg[str(i)]} | " + " | ".join(cells) + " |")
    out.append("| rows | | " + " | ".join(str((P.get(c) or {}).get("rows", "-")) for c in cols) + " |")
    out.append("| mean targets | | " + " | ".join(str((P.get(c) or {}).get("mean_targets", "-")) for c in cols) + " |")
    out.append("")
    out.append("Region rates and visitation (% of rows):\n")
    keys = [("any left-of-wall target", "region_rates", "any_left"), ("moving target (2)", "region_rates", "moving"),
            ("right target (3)", "region_rates", "right"), ("all five central", "region_rates", "all_central"),
            ("central five + right", "region_rates", "all_central_and_right"),
            ("entered x < -2100", "visitation", "entered_left_of_wall"),
            ("touched wall face (x <= -1640)", "visitation", "touched_wall_face"),
            ("reached wall-top height (y >= 2990)", "visitation", "reached_wall_top_height"),
            ("entered right block (x > 2100)", "visitation", "entered_right_block")]
    out.append("| measure | " + " | ".join(heads) + " |")
    out.append("| --- | " + " | ".join("---" for _ in heads) + " |")
    for label, sec, k in keys:
        out.append(f"| {label} | " + " | ".join(pct(((P.get(c) or {}).get(sec) or {}).get(k)) for c in cols) + " |")
    out.append("| min x over all rows | " + " | ".join(str(((P.get(c) or {}).get("visitation") or {}).get("min_x_min", "-"))
                                                   for c in cols) + " |")
    out.append("| max y over all rows | " + " | ".join(
        str(round(((P.get(c) or {}).get("visitation") or {}).get("max_y_max") or 0, 1)) for c in cols) + " |")
    out.append("")
    six = P["six_target_all_rows"]["six_target"]
    out.append(f"Six-target rows ({P['six_target_all_rows']['rows']} rows, "
               f"{P['six_target_all_rows']['unique_sequences']} unique sequences): subsets "
               + ", ".join(f"{s['broken']} x {s['rows']}" for s in six["subsets"])
               + f"; never broken in a six-target row: {six['never_in_six']}.\n")
    out.append("Most common broken subsets (M7e final stochastic, pooled):\n")
    out.append("| broken IDs | rows |")
    out.append("| --- | --- |")
    for s in P["m7e/final/stochastic/pooled"]["broken_subsets_top"][:10]:
        out.append(f"| {s['ids']} | {s['rows']} |")
    out.append("")
    out.append("Checkpoint trajectory, M7e stochastic (mean targets; break rate % of IDs 2 and 3; max targets):\n")
    out.append("| transitions | " + " | ".join(f"s{k} mean / ID2 / ID3 / max" for k in (0, 1, 2)) + " |")
    out.append("| --- | --- | --- | --- |")
    trajs = [res["m7e_checkpoint_trajectory"][f"m7e_s{k}_v2"]["stochastic_points"] for k in (0, 1, 2)]
    for j in range(max(len(t) for t in trajs)):
        row = []
        for t in trajs:
            p = t[j] if j < len(t) else None
            if not p or not p["break_rate"]:
                row.append("-")
            else:
                row.append(f"{p['mean_targets']} / {pct(p['break_rate'][2])} / {pct(p['break_rate'][3])} / "
                           f"{p['max_targets']}")
        out.append(f"| {trajs[0][j]['transitions'] if j < len(trajs[0]) else '-'} | " + " | ".join(row) + " |")
    out.append("")
    out.append("Deterministic (argmax) policies, IDs broken at each evaluation point:\n")
    for k in (0, 1, 2):
        det = res["m7e_checkpoint_trajectory"][f"m7e_s{k}_v2"]["deterministic_ids_by_point"]
        out.append(f"- M7e s{k}: " + "; ".join(f"{d['set']} {d['ids']}" for d in det))
    for run in ("m7d_s0_v1", "m7d_s0_v2", "m7d_s1_v1", "m7d_s1_v2", "m7d_s2_v1", "m7d_s2_v2"):
        p = P.get(f"{run}/final/deterministic")
        if p and p.get("rows"):
            out.append(f"- {run} final: {p['broken_subsets_top'][0]['ids']} ({p['rows']} rows)")
    out.append("")
    return "\n".join(out)


def regions_from_mapping(path: Path = MAPPING) -> Dict[int, str]:
    m = json.loads(Path(path).read_text(encoding="utf-8"))
    return {int(t["id"]): t["region"] for t in m["targets"]}


# -- self-test ----------------------------------------------------------------------------------------------


def self_test() -> int:
    bad = []
    regions = {0: "central", 1: "left_of_wall", 2: "upper_right_moving", 3: "right", 4: "central", 5: "central",
               6: "left_of_wall", 7: "central", 8: "left_of_wall", 9: "central"}
    rec = {"events": [{"target_id": 9, "consumed_tick": 50, "break_order": 1},
                      {"target_id": 4, "consumed_tick": 90, "break_order": 2}],
           "expected": {"length": 3600, "end_reason": "horizon"}, "final_remaining_ids": [0, 1, 2, 3, 5, 6, 7, 8],
           "positions": {"region_steps": {"left_of_wall": 0, "wall_column": 0, "central": 3600, "right": 0},
                         "min_x": -100.0, "max_x": 100.0, "max_y": 0.0, "first_tick_left_of_wall": None}}
    ep = episode_from_record(rec)
    if ep["order"] != [9, 4] or ep["tail"] != 3600 - 91 or not ep["early_then_stagnant"] or not ep["last_before_half"]:
        bad.append("episode")
    rows = [{**ep, "digest": "a"}, {**ep, "digest": "a"}]
    m = metrics(rows, regions)
    if m["per_target"]["9"]["break_rate"] != 1.0 or m["per_target"]["1"]["break_rate"] != 0.0 or \
            m["region_rates"]["any_left"] != 0.0 or m["unique_sequences"] != 1 or m["rows"] != 2:
        bad.append("metrics")
    if m["transitions_top"][0]["transition"] not in ("start->9", "9->4"):
        bad.append("transitions")
    lo, hi = wilson(0, 100)
    if lo != 0.0 or not (0.03 < hi < 0.04):
        bad.append("wilson")
    print(f"m7f_analysis self-test: {'PASS' if not bad else 'FAIL'} (4 cases) {bad}")
    return 0 if not bad else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--replay", type=Path, default=REPLAY)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--preview", type=Path, default=None,
                    help="partial-data preview written to this path (never the docs); refuses divergent records")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.preview is not None:
        rows, meta = load(replay=args.replay, allow_partial=True)
        res = analyse(rows, meta, regions_from_mapping())
        args.preview.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8", newline="\n")
        args.preview.with_suffix(".tables.md").write_text(render_tables(res), encoding="utf-8", newline="\n")
        print(json.dumps({"preview_rows": len(rows), "hypothesis": res["hypothesis"]}, indent=1))
        return 0
    rows, meta = load(replay=args.replay)
    res = analyse(rows, meta, regions_from_mapping())
    args.out.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8", newline="\n")
    args.out.with_suffix(".tables.md").write_text(render_tables(res), encoding="utf-8", newline="\n")
    print(json.dumps({"rows": len(rows), "meta": {k: v for k, v in meta.items() if k not in ("population", "strata")},
                      "hypothesis": res["hypothesis"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
