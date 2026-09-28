"""Offline comparison (M7p wall-top census follow-up, 2026-09-28) of the L1 flights of the seed-1 geo4 final policy from the existing census traces + canonical actions.
Pure file reading; no native process. Output: JSON + printed tables."""
import gzip, json, math, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "rl"))
CENSUS = ROOT / "runs/m7p/addendum/walltop_census/census.json"
REG = ROOT / "docs/rl_geometry_scale_m7p_walltop_census_registration.json"
OUT = ROOT / "runs/m7p/addendum/walltop_census/flight_comparison.json"
STICK = {(0, 0): "N", (80, 0): "R", (80, 80): "UR", (0, 80): "U", (-80, 80): "UL", (-80, 0): "L", (-80, -80): "DL", (0, -80): "D", (80, -80): "DR"}
BTN = {0: "-", 32768: "A", 16384: "B", 8: "Cu", 2: "Cl", 32: "L", 16: "R", 8192: "Z"}
tbl = json.load(open(ROOT / "rl/data/m7n_action_classes_v1.json"))
NAMES = {int(k): v for k, v in tbl["common_names"].items()}
NAMES.update({int(k): v for k, v in tbl["characters"]["mario"]["names"].items()})
def sname(i): return NAMES.get(i, str(i)).replace("nFTCommonStatus", "").replace("nFTMarioStatus", "M.")

census = json.load(open(CENSUS)); reg = json.load(open(REG))
regmap = {e["episode_id"]: e for e in reg["episodes"]}
def trace_path(e):
    return ROOT / e["addendum_trace"]["path"] if e["source"] == "addendum_trace" else ROOT / f"runs/m7p/addendum/walltop_census/replays/{e['order']:03d}_{e['episode_id'][-8:]}/trace.json.gz"
def actions(e):
    rows = [json.loads(l) for l in (ROOT / e["artifact_dir"] / "actions.jsonl").read_text().splitlines()]
    return {int(r["consumed_tick"]): (STICK[(r["stick_x"], r["stick_y"])], BTN.get(r["buttons"], str(r["buttons"]))) for r in rows}

LEDGE_CORNER = (-1200.0, 3000.0)

def flight_rows(steps, acts, t0, t1):
    by = {int(s["consumed_tick"]): s for s in steps}
    rows = []
    for t in range(t0, t1 + 1):
        s = by.get(t)
        if s is None: continue
        o, f = s["observation"], s["spatial"]["fighter"]
        rows.append({"t": t, "x": round(float(o["position_x"]), 1), "y": round(float(o["position_y"]), 1),
                     "vx": round(float(o["air_velocity_x"]), 1), "vy": round(float(o["air_velocity_y"]), 1),
                     "face": int(o["facing_direction"]), "st": int(o["fighter_status_id"]), "name": sname(int(o["fighter_status_id"])),
                     "air": int(o["ground_air_state"]), "j": int(o["jumps_used"]), "floor": f["floor_line_id"], "ceil": f["ceil_line_id"],
                     "lwall": f["lwall_line_id"], "rwall": f["rwall_line_id"], "fdist": round(float(f["floor_dist"]), 1),
                     "act": acts.get(t, ("?", "?"))})
    return rows

def analyse_flight(rows, takeoff_t, land_t):
    """rows cover takeoff tick .. landing tick (or end)."""
    r0 = rows[0]
    def first(pred):
        return next((r for r in rows if pred(r)), None)
    squat = first(lambda r: "JumpSquat" in r["name"])
    jump1 = first(lambda r: r["air"] == 1 and r["j"] >= 1)
    dj = first(lambda r: r["j"] >= 2)
    upb = first(lambda r: r["st"] in (225, 226))
    attacks = [r for r in rows if "Attack" in r["name"] and r["air"] == 1]
    air = [r for r in rows if r["air"] == 1]
    apex = max(air, key=lambda r: r["y"]) if air else None
    near = min(air, key=lambda r: math.hypot(r["x"] - LEDGE_CORNER[0], r["y"] - LEDGE_CORNER[1])) if air else None
    coll = [r for r in air if r["rwall"] in (12, 13) or r["ceil"] == 9 or r["lwall"] == 17]
    # x and y when the fighter first reaches x <= -1100 (ledge approach) and the state there
    approach = first(lambda r: r["air"] == 1 and r["x"] <= -1100.0)
    upb_win = [r["act"][0] for r in rows if upb and upb["t"] - 2 <= r["t"] <= upb["t"] + 12]
    def stick_hist(rs): return dict(Counter(r["act"][0] for r in rs))
    seg = lambda a, b: [r for r in rows if a is not None and b is not None and a["t"] <= r["t"] < b["t"]]  # noqa
    return {"takeoff": {k: r0[k] for k in ("t", "x", "y", "vx", "vy", "face", "name", "j", "floor", "act")},
            "jump_squat_t": squat and squat["t"], "first_jump_t": jump1 and jump1["t"], "double_jump_t": dj and dj["t"], "up_b_t": upb and upb["t"],
            "dt_first_jump": jump1 and jump1["t"] - takeoff_t, "dt_double_jump": dj and dj["t"] - takeoff_t, "dt_up_b": upb and upb["t"] - takeoff_t,
            "dt_dj_to_upb": (upb and dj) and upb["t"] - dj["t"],
            "state_at_double_jump": dj and {k: dj[k] for k in ("x", "y", "vx", "vy", "face", "act")},
            "state_at_up_b": upb and {k: upb[k] for k in ("x", "y", "vx", "vy", "face", "j", "act")},
            "up_b_below_ledge_top": upb and round(3000.0 - upb["y"], 1),
            "aerial_attacks": [(r["t"], r["name"]) for r in attacks][:6], "n_aerial_attack_ticks": len(attacks),
            "stick_upb_window": "".join(s + " " for s in upb_win).strip(),
            "stick_hist_jump_to_dj": stick_hist(seg(jump1, dj)), "stick_hist_dj_to_upb": stick_hist(seg(dj, upb)),
            "stick_hist_after_upb": stick_hist([r for r in rows if upb and r["t"] >= upb["t"]]),
            "apex": apex and {k: apex[k] for k in ("t", "x", "y", "vx", "vy", "name", "j")},
            "approach_x_le_-1100": approach and {k: approach[k] for k in ("t", "x", "y", "vx", "vy", "name", "j", "rwall", "ceil", "act")},
            "closest_to_ledge_corner": near and {k: near[k] for k in ("t", "x", "y", "vx", "vy", "name", "j", "rwall", "ceil", "floor", "fdist", "act")}
            | {"dist": round(math.hypot(near["x"] - LEDGE_CORNER[0], near["y"] - LEDGE_CORNER[1]), 1)},
            "first_collision": coll[0] and {k: coll[0][k] for k in ("t", "x", "y", "vx", "vy", "name", "j", "rwall", "ceil", "lwall")} if coll else None,
            "collision_ticks": len(coll), "collision_lines": {f"rwall{a}_ceil{b}_lwall{c}": n for (a, b, c), n in Counter((r["rwall"], r["ceil"], r["lwall"]) for r in coll).items()},
            "landing": rows[-1]["air"] == 0 and {k: rows[-1][k] for k in ("t", "x", "y", "name", "floor")},
            "airborne_ticks": len(air), "max_y": apex and apex["y"], "min_x": min(r["x"] for r in air) if air else None}

flights = []
for row in census["episodes"]:
    if not row["l1_takeoffs"]: continue
    e = regmap[row["episode_id"]]
    steps = json.load(gzip.open(trace_path(e), "rt"))["steps"]
    acts = actions(e)
    for sg in row["l1_takeoffs"]:
        t0 = sg["takeoff"]["consumed_tick"]
        t1 = sg["landing"]["consumed_tick"] if sg["landing"] else int(steps[-1]["consumed_tick"])
        rows = flight_rows(steps, acts, t0, t1)
        a = analyse_flight(rows, t0, t1)
        a.update({"episode": row["episode_id"], "short": row["episode_id"][-8:], "landed": sg["to"] or sg["ends"], "high": sg["max_y"] >= 2800,
                  "targets_left": None})
        a["rows"] = rows if sg["max_y"] >= 2800 else None
        flights.append(a)

json.dump({"flights": flights}, open(OUT, "w"), indent=1, default=str)
high = sorted([f for f in flights if f["high"]], key=lambda f: -f["max_y"])
low = [f for f in flights if not f["high"]]
print(f"{len(flights)} L1 flights; {len(high)} high, {len(low)} other\n")
keys = ["short", "landed", "takeoff", "dt_first_jump", "dt_double_jump", "dt_up_b", "dt_dj_to_upb", "state_at_double_jump", "state_at_up_b", "up_b_below_ledge_top",
        "n_aerial_attack_ticks", "aerial_attacks", "stick_upb_window", "stick_hist_jump_to_dj", "stick_hist_dj_to_upb", "stick_hist_after_upb", "apex", "approach_x_le_-1100",
        "closest_to_ledge_corner", "first_collision", "collision_ticks", "collision_lines", "landing", "airborne_ticks", "min_x"]
for f in high:
    print("=" * 100)
    for k in keys: print(f"{k:24s} {json.dumps(f[k], default=str)}")
print("\n=== compact check over the other", len(low), "flights ===")
def q(vals):
    v = sorted(x for x in vals if x is not None); n = len(v)
    return (v[0], v[n // 4], v[n // 2], v[3 * n // 4], v[-1]) if v else None
for k in ("dt_double_jump", "dt_up_b", "dt_dj_to_upb", "up_b_below_ledge_top", "max_y", "min_x", "airborne_ticks", "n_aerial_attack_ticks"):
    print(f"{k:22s} high: {[f[k] for f in high]}  others quartiles: {q([f[k] for f in low])}")
print("takeoff x high:", [f["takeoff"]["x"] for f in high], " others:", q([f["takeoff"]["x"] for f in low]))
print("takeoff face high:", [f["takeoff"]["face"] for f in high], " others:", Counter(f["takeoff"]["face"] for f in low))
print("up_b x high:", [f["state_at_up_b"] and f["state_at_up_b"]["x"] for f in high], " others:", q([f["state_at_up_b"] and f["state_at_up_b"]["x"] for f in low]))
print("up_b y high:", [f["state_at_up_b"] and f["state_at_up_b"]["y"] for f in high], " others:", q([f["state_at_up_b"] and f["state_at_up_b"]["y"] for f in low]))
print("up_b vy high:", [f["state_at_up_b"] and f["state_at_up_b"]["vy"] for f in high], " others:", q([f["state_at_up_b"] and f["state_at_up_b"]["vy"] for f in low]))
print("no up-B among others:", sum(1 for f in low if f["up_b_t"] is None), " no dj:", sum(1 for f in low if f["double_jump_t"] is None))
print("others landed:", Counter(f["landed"] for f in low))
