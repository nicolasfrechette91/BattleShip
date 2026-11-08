#!/usr/bin/env python3
"""DECISIVE 2 revision (owner 2026-11-08): demotion judged on a rolling window, replayed on run 2 and on run 3's night. Zero native
ticks, read-only.

    python -B tools/analysis/run3_design/d2_rolling_replay.py [--lab C:/BattleShip_lab] [--out logs/run3_design]   (the night: <lab>/crossing_2026-11-06_run3)

Rule replayed: a group is demoted while its LAST 1,000 dispatches (run 2 then run 3, in ingest order) hold 0 bursts that broke a target
(b), 0 new earliest arrivals (e) and >= 75 % falls; it exits when that stops holding. Checked after each of the group's own dispatches
(the only thing that changes its window). The current rule (whole history) is replayed alongside for comparison.

Per-dispatch counters, as the selector defines them (tools/frs/run3_select.py on_ingest; run 2 as tools/frs/run3_load.run2_history):
    fall  outcome == fall
    b     a burst that broke a target (run 2: breaks_after_start non-empty; run 3: advanced)
    u     useful break: next-level arrival <= the bound (level 9: a claimed clear <= the bound)
    e     a kept cell at a deeper level earlier than every alive cell of its group before the burst (level 9: a claimed clear faster
          than every earlier claim)
The night's per-dispatch counters are rebuilt from its dispatches.jsonl and cells.jsonl over the start archive (runs 1 + 2 merged) and
checked against the run's own per-group totals (summary.json) before anything is reported; run 2's are checked against the plan's
history (run3_load.run2_history).

A FALSE demotion: a group, after the rule would have demoted it, produced a useful break (u) or a new earliest arrival (e) by one of
its own dispatches. Also counted: the arrivals of a new earliest cell (from any dispatch) into a group while it is demoted (each would
queue 3 trigger draws under the proposed second clause).
"""
import bisect
import collections
import json
from pathlib import Path

import _common as C
import run3_load as L
import run3_select as rs

WIN, FALLS, MIN_N = 1000, 0.75, 1000
a = C.parse(__doc__)
night = Path(a.lab / "crossing_2026-11-06_run3")


def glab(g):
    return rs.glabel(g)


def gk_of(niches, r):
    return (int(r["level"]), int(r["key"][3]), rs.niche_label(niches.of(r)))


# -- run 2, dispatch by dispatch (run3_load.run2_history with the per-dispatch rows kept) --------------------------------------------
R1 = L.read_run(a.lab / "crossing_2026-10-15", 1)
R2 = L.read_run(a.lab / "crossing_2026-10-15_run2", 2, run1_rows=len(R1["rows"]), run1_utc_start=R1["summary"].get("utc_start"))
nx = L.NicheIndex([R1, R2])


def run2_sequence(bound2, bound_night):
    cur, hist, groups = {}, collections.defaultdict(list), collections.defaultdict(list)

    def put(cid, r):
        old = cur.get(cid)
        if old is not None:
            lst = groups[gk_of(nx, old)]
            del lst[bisect.bisect_left(lst, (int(old["tick"]), cid))]
        cur[cid] = r
        hist[cid].append(r)
        bisect.insort(groups[gk_of(nx, r)], (int(r["tick"]), cid))

    for r in R1["rows"]:
        put(int(r["cid"]), r)
    claims1 = [int(d["claimed"]["completion_input_tick"]) for d in R1["dispatches"]
               if d.get("outcome") == "clear" and (d.get("claimed") or {}).get("completion_input_tick") is not None]
    best_claim = min(claims1) if claims1 else 10 ** 9
    ev_by_n = collections.defaultdict(list)
    for r in R2["rows"]:
        ev_by_n[int(r["origin"]["n"])].append(r)
    seq = []
    for d in R2["dispatches"]:
        cid = int(d["cid"])
        rep = next((x for x in reversed(hist.get(cid, [])) if int(x["tick"]) == int(d["start_tick"])), None) or cur.get(cid)
        if rep is None:
            continue
        g = gk_of(nx, rep)
        lv = g[0]
        nxt = (d.get("levels") or {}).get(str(lv + 1))
        ct = (d.get("claimed") or {}).get("completion_input_tick")

        def useful(bound):
            return int(ct is not None and int(ct) <= bound) if lv == rs.TARGETS_TOTAL - 1 else int(nxt is not None and int(nxt) <= bound)

        e, landed = 0, []
        for r in ev_by_n.get(int(d["n"]), []):
            g2 = gk_of(nx, r)
            if not groups[g2] or int(r["tick"]) < groups[g2][0][0]:
                landed.append([glab(g2), int(r["tick"])])
                if int(r["level"]) > lv:
                    e = 1
        if lv == rs.TARGETS_TOTAL - 1 and ct is not None and int(ct) < best_claim:
            e, best_claim = 1, int(ct)
        seq.append({"run": 2, "n": int(d["n"]), "g": g, "fall": int(d.get("outcome") == "fall"), "b": int(bool(d.get("breaks_after_start"))),
                    "u": useful(bound2), "u_night": useful(bound_night), "e": e, "landed": landed})
        for r in ev_by_n.get(int(d["n"]), []):
            put(int(r["cid"]), r)
    return seq, cur


plan_night = json.loads((night / "plan.json").read_text(encoding="utf-8"))
BOUND_NIGHT = int(plan_night["e7"]["bound_max_L"])
BOUND_RUN2 = 1220
seq2, final2 = run2_sequence(BOUND_RUN2, BOUND_NIGHT)
tot2 = collections.defaultdict(collections.Counter)
for x in seq2:
    t = tot2[glab(x["g"])]
    t.update({"n": 1, "fall": x["fall"], "b": x["b"], "bu": x["u_night"], "e": x["e"]})
planned = plan_night["run3"]["history"]["groups"]
diff2 = {gl: [dict(tot2.get(gl, {})), h] for gl, h in planned.items() if {k: int(tot2.get(gl, {}).get(k, 0)) for k in h} != h}
print(f"run 2: {len(seq2)} dispatches attributed; per-group totals equal to the night plan's history: {not diff2}")
if diff2:
    raise SystemExit(f"run 2 sequence does not reproduce the plan's history: {list(diff2.items())[:3]}")

# -- the night, dispatch by dispatch --------------------------------------------------------------------------------------------------
rd = night / "run"
groups = collections.defaultdict(list)
where = {}
for cid, r in final2.items():
    if int(r["level"]) < rs.TARGETS_TOTAL and r.get("key"):
        g = gk_of(nx, r)
        bisect.insort(groups[g], (int(r["tick"]), int(cid)))
        where[int(cid)] = (g, int(r["tick"]))
kept_by_n = collections.defaultdict(list)
for r in C.rows(rd / "cells.jsonl"):
    if r.get("ev") in (rs.NEW, rs.REPLACED):
        kept_by_n[int(r["origin"]["n"])].append((int(r["cid"]), int(r["level"]), int(r["tick"]), r["group"]))
disp = sorted(C.bursts(rd), key=lambda x: int(x["n"]))
best_claim = plan_night["run3"].get("best_claim")
best_claim = int(best_claim) if best_claim is not None else None
G_BY_LABEL = {}


def g_of_label(s):
    if s not in G_BY_LABEL:
        lv, mask, niche = s.split("|", 2)
        G_BY_LABEL[s] = (int(lv), int(mask), niche)
    return G_BY_LABEL[s]


seq3 = []
for d in disp:
    n = int(d["n"])
    g = g_of_label(d["group"])
    lv = g[0]
    claimed = (d.get("claimed") or {}).get("completion_input_tick") if d.get("outcome") == "clear" else None
    if lv >= rs.TARGETS_TOTAL - 1:
        u = int(claimed is not None and int(claimed) <= BOUND_NIGHT)
    else:
        nxt = (d.get("levels") or {}).get(str(lv + 1))
        u = int(nxt is not None and int(nxt) <= BOUND_NIGHT)
    e, landed = 0, []
    kept = kept_by_n.get(n, [])
    for cid, clv, tick, glabel in kept:
        g2 = g_of_label(glabel)
        lst = groups.get(g2)
        if (not lst or tick < lst[0][0]) and clv > lv:
            e = 1
        if not lst or tick < lst[0][0]:
            landed.append([glabel, tick])
    if claimed is not None and (best_claim is None or int(claimed) < best_claim):
        best_claim = int(claimed)
        if lv >= rs.TARGETS_TOTAL - 1:
            e = 1
    seq3.append({"run": 3, "n": n, "g": g, "fall": int(d.get("outcome") == "fall"), "b": int(bool(d.get("advanced"))), "u": u, "e": e,
                 "landed": landed})
    for cid, clv, tick, glabel in kept:
        old = where.pop(cid, None)
        if old is not None:
            lst = groups[old[0]]
            i = bisect.bisect_left(lst, (old[1], cid))
            if i < len(lst) and lst[i] == (old[1], cid):
                del lst[i]
        if clv < rs.TARGETS_TOTAL:
            g2 = g_of_label(glabel)
            bisect.insort(groups[g2], (tick, cid))
            where[cid] = (g2, tick)
summary = json.loads((rd / "summary.json").read_text(encoding="utf-8"))
final_tab = {r["group"]: r["run3"] for r in summary["run3"]["selection"].get("table", [])} if summary["run3"]["selection"].get("table") else {}
if not final_tab:
    recs = [json.loads(x) for x in (rd / "hourly.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    final_tab = {r["group"]: r["run3"] for r in recs[-1]["groups"]}
tot3 = collections.defaultdict(collections.Counter)
for x in seq3:
    tot3[glab(x["g"])].update({"n": 1, "fall": x["fall"], "b": x["b"], "bu": x["u"], "e": x["e"]})
diff3 = {gl: [dict(tot3.get(gl, {})), h] for gl, h in final_tab.items() if {k: int(tot3.get(gl, {}).get(k, 0)) for k in ("n", "fall", "b", "bu", "e")}
         != {k: int(h.get(k, 0)) for k in ("n", "fall", "b", "bu", "e")}}
print(f"night: {len(seq3)} dispatches; per-group run 3 totals equal to the run's own: {not diff3} ({len(final_tab)} groups compared)")
if diff3:
    for gl, (mine, theirs) in list(diff3.items())[:6]:
        print("  ", gl, "replay", mine, "run", theirs)
    raise SystemExit("the night's per-dispatch rebuild does not reproduce the run's totals")


# -- the rule, replayed -----------------------------------------------------------------------------------------------------------------
def replay(seq, rolling, bound):
    win = collections.defaultdict(collections.deque)
    cum = collections.defaultdict(collections.Counter)
    dem, events, after = set(), [], collections.defaultdict(lambda: collections.Counter())
    landed_while = collections.Counter()
    first_after = {}
    for i, x in enumerate(seq):
        first = {}
        for gl, t in x["landed"]:                    # one queued cell per demoted group per burst: its earliest, if eligible
            first[gl] = min(t, first.get(gl, t))
        for gl, t in first.items():
            if g_of_label(gl) in dem and t <= bound:
                landed_while[gl] += 1
        g = x["g"]
        if g in dem:
            a_ = after[glab(g)]
            a_.update({"n": 1, "b": x["b"], "u": x["u"], "e": x["e"]})
            if (x["u"] or x["e"]) and glab(g) not in first_after:
                first_after[glab(g)] = {"run": x["run"], "n": x["n"], "u": x["u"], "e": x["e"]}
        w, c = win[g], cum[g]
        w.append((x["fall"], x["b"], x["e"]))
        if len(w) > WIN:
            w.popleft()
        c.update({"n": 1, "fall": x["fall"], "b": x["b"], "e": x["e"]})
        if rolling:
            now = len(w) >= WIN and sum(t[1] for t in w) == 0 and sum(t[2] for t in w) == 0 and sum(t[0] for t in w) >= FALLS * len(w)
        else:
            now = c["n"] >= MIN_N and c["b"] == 0 and c["e"] == 0 and c["fall"] >= FALLS * c["n"]
        if now != (g in dem):
            (dem.add if now else dem.discard)(g)
            events.append({"kind": "demoted" if now else "exit", "group": glab(g), "run": x["run"], "n": x["n"], "group_dispatches": c["n"],
                           "window_falls": sum(t[0] for t in w), "cause": None if now else ("b" if x["b"] else "e" if x["e"] else "falls<75%")})
    return {"events": events, "demoted_at_end": sorted(glab(g) for g in dem), "after_demotion": {k: dict(v) for k, v in after.items()},
            "false_demotions": first_after, "new_earliest_landings_while_demoted": dict(landed_while)}


out = {"window": WIN, "fall_rate": FALLS, "bound_run2": BOUND_RUN2, "bound_night": BOUND_NIGHT,
       "run2_alone": {"rolling": replay([dict(x, u=x["u"]) for x in seq2], True, BOUND_RUN2),
                      "whole_history": replay([dict(x, u=x["u"]) for x in seq2], False, BOUND_RUN2)},
       "night": {"rolling": replay([dict(x, u=x["u_night"]) for x in seq2] + seq3, True, BOUND_NIGHT),
                 "whole_history": replay([dict(x, u=x["u_night"]) for x in seq2] + seq3, False, BOUND_NIGHT)}}
for part in ("run2_alone", "night"):
    for rule in ("rolling", "whole_history"):
        R = out[part][rule]
        print(f"\n== {part} / {rule}: {len(R['events'])} events, demoted at the end {R['demoted_at_end']}")
        for ev in R["events"]:
            print("  ", ev)
        print("   after demotion (own dispatches while demoted):", R["after_demotion"])
        print("   FALSE demotions (u or e while demoted):", R["false_demotions"] or "none")
        print("   bursts landing a new earliest eligible cell in a demoted group (3 trigger draws each):",
              R["new_earliest_landings_while_demoted"] or "none")
C.dump(a, "d2_rolling_replay.json", out)
