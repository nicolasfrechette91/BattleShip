#!/usr/bin/env python3
"""Zero-break demotion (owner 2026-11-11, before night 3), replayed on the real sequences: every group's per-dispatch (fall, b, e) codes of
run 2, run 3 night 1 and night 2 in ingest order, as the plan inheriting both nights builds them (tools/frs/run3_load.load), through the
selector's own rule (tools/frs/run3_select.demotion_next) with the run3_select_v3 thresholds (demoted at falls >= 75 %, exit below 70 %)
and with the zero-break rule (both thresholds 0: the window of 1,000 full with 0 breaks and 0 e, whatever the falls; exit when a break or
an e enters the window). Zero native ticks, read-only.

    python -B tools/analysis/run3_design/d2_zero_break_replay.py [--lab C:/BattleShip_lab] [--out logs/run3_design]

Check before anything is reported: each night's per-group dispatch count fits inside the group's sequence (night 2's own events are
checked against its log by d2_hysteresis_replay.py). Reports, per group: dispatches, whole-history break rate, longest run of dispatches
without a break or an e, the events of each rule in each run, the status at the end (= the next night's start status), whether the group
has an eligible cell in night 3's plan, and the window-size sensitivity of the zero-break rule.
False demotions, two definitions: STRICT, a zero-break demotion followed later in the same sequence by any break or e of that group (an
exit); USEFUL (d2_rolling_replay.py's definition, at night 3's bound 934 as the plan's D1 window values count it, u + e per dispatch), a
useful break (next-level arrival <= 934; level 9: a claimed clear <= 934) or an e while demoted (the exit dispatch included). Caveat: the
sequences were generated under the older rules' allocation, so a demoted group's later dispatches are what it got while NOT demoted; the
replay says when the rule would have fired, not what the search would have done next.
"""
import json
from pathlib import Path

import _common as C
import run3_load as L
import run3_select as rs

a = C.parse(__doc__)
RUN1, RUN2 = a.lab / "crossing_2026-10-15", a.lab / "crossing_2026-10-15_run2"
NIGHTS = [a.lab / "crossing_2026-11-06_run3", a.lab / "crossing_2026-11-10_run3b"]
PLAN3 = a.lab / "crossing_2026-11-11_run3c" / "plan.json"
BOUND = 934                                   # the next plan's bound (959 - 24 - 1); the codes do not depend on it
WIN = 1000
RULES = (("v3_falls", 0.75, 0.70), ("zero_break", 0.0, 0.0))

D = L.load(RUN1, RUN2, BOUND, inherit=NIGHTS)
tails = D["history"]["tails"]
uwin = D["history"]["windows"]                # per dispatch u + e at THIS bound (rule a)
close = []
for d in NIGHTS:
    rec = [json.loads(x) for x in (d / "run" / "hourly.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()][-1]
    close.append({g["group"]: int((g.get("run3") or {}).get("n", 0)) for g in rec["groups"]})
eligible = {}
if PLAN3.is_file():
    eligible = {r["group"]: int(r["eligible"]) for r in json.loads(PLAN3.read_text(encoding="utf-8"))["run3"]["start"]}


def replay(codes, enter, exit_rate, win=WIN):
    w, falls, b, e, st, ev = [], 0, 0, 0, False, []
    for i, c in enumerate(codes):
        w.append(c)
        falls, b, e = falls + (c & 1), b + ((c >> 1) & 1), e + ((c >> 2) & 1)
        if len(w) > win:
            o = w.pop(0)
            falls, b, e = falls - (o & 1), b - ((o >> 1) & 1), e - ((o >> 2) & 1)
        nxt = rs.demotion_next(st, len(w), falls, b, e, win, enter, exit_rate)
        if nxt != st:
            ev.append((i, "demoted" if nxt else "exit", falls, c))
        st = nxt
    return ev, st, falls


def longest_quiet(codes):
    best = cur = 0
    for c in codes:
        cur = 0 if c & 6 else cur + 1
        best = max(best, cur)
    return best


out = {"rules": {n: {"enter": en, "exit": ex} for n, en, ex in RULES}, "bound": BOUND, "groups": {}, "checks": {}}
count_ok = True
for gl, t in sorted(tails.items()):
    codes = [int(ch) for ch in t]
    n2, n1 = close[1].get(gl, 0), close[0].get(gl, 0)
    cut1, cut2 = len(codes) - n2 - n1, len(codes) - n2            # run 2 | night 1 | night 2
    count_ok &= cut1 >= 0
    seg = lambda i: "run2" if i < cut1 else ("night1" if i < cut2 else "night2")
    nb = sum((c >> 1) & 1 for c in codes)
    ne = sum((c >> 2) & 1 for c in codes)
    row = {"n": len(codes), "run2": cut1, "night1": n1, "night2": n2, "b": nb, "e": ne, "fall": sum(c & 1 for c in codes),
           "b_run3": sum((c >> 1) & 1 for c in codes[cut1:]), "b_rate": round(nb / len(codes), 5) if codes else None,
           "longest_without_b_or_e": longest_quiet(codes), "eligible_night3": eligible.get(gl)}
    uw = [int(ch) for ch in uwin.get(gl, "")]
    assert len(uw) == len(codes), gl
    row["u934_or_e"] = sum(1 for v in uw if v)
    for name, en, ex in RULES:
        ev, st, falls = replay(codes, en, ex)
        false = [(i, j) for (i, k, _f, _c), (j, k2, _f2, _c2) in zip(ev, ev[1:]) if k == "demoted" and k2 == "exit"]
        spans = [(i, j) for (i, k, _f, _c), (j, _k2, _f2, _c2) in zip(ev, ev[1:] + [(len(codes) - 1, "end", 0, 0)]) if k == "demoted"]
        useful = [(i, x) for i, j in spans for x in range(i + 1, j + 1) if uw[x]]
        row[name] = {"events": [{"i": i, "run": seg(i), "kind": k, "falls": f, "code": c} for i, k, f, c in ev], "end_demoted": st, "end_falls": falls,
                     "false_demotions": [{"demoted_at": i, "run": seg(i), "exit_at": j, "exit_run": seg(j), "gap": j - i, "exit_code": codes[j],
                                          "exit_u934_or_e": uw[j]} for i, j in false],
                     "false_demotions_useful_934": [{"demoted_at": i, "at": x, "run": seg(x), "code": codes[x], "u_plus_e": uw[x]} for i, x in useful]}
    out["groups"][gl] = row
out["checks"]["night_counts_fit_sequences"] = count_ok

changed = {gl: r for gl, r in out["groups"].items() if r["v3_falls"]["end_demoted"] != r["zero_break"]["end_demoted"]}
false_all = [(gl, f) for gl, r in out["groups"].items() for f in r["zero_break"]["false_demotions"]]
false_useful = [(gl, f) for gl, r in out["groups"].items() for f in r["zero_break"]["false_demotions_useful_934"]]
out["summary"] = {"groups": len(out["groups"]), "end_status_changed": sorted(changed), "zero_break_false_demotions": len(false_all),
                  "zero_break_false_demotions_useful_934": len(false_useful),
                  "zero_break_events": sum(len(r["zero_break"]["events"]) for r in out["groups"].values()),
                  "v3_events": sum(len(r["v3_falls"]["events"]) for r in out["groups"].values()),
                  "demoted_at_end": {n: sorted(gl for gl, r in out["groups"].items() if r[n]["end_demoted"]) for n, _e, _x in RULES}}
sens = {}                                     # the zero-break rule's window size: false demotions and the night-3 start set
for win in (1000, 1250, 1500, 1750, 2000, 2500):
    fd, dem = [], []
    for gl, t in sorted(tails.items()):
        ev, st, _f = replay([int(ch) for ch in t], 0.0, 0.0, win)
        fd += [gl for (_i, k, _a, _b), (_j, k2, _c, _d) in zip(ev, ev[1:]) if k == "demoted" and k2 == "exit"]
        if st and eligible.get(gl):
            dem.append(gl)
    sens[win] = {"false_demotions": fd, "demoted_at_night3_start_with_eligible": dem}
out["window_sensitivity"] = sens
C.dump(a, "d2_zero_break_replay.json", out)
print(f"checks: {out['checks']}")
print(f"groups {len(out['groups'])}; events v3 {out['summary']['v3_events']}, zero-break {out['summary']['zero_break_events']}; "
      f"zero-break false demotions: strict {len(false_all)}, useful at 934 {len(false_useful)}")
print("group | n (run 2 / night 1 / night 2) | b (run 3) | e | b rate | longest without b/e | eligible night 3 | v3 events / end | zero-break events / end | false")
for gl, r in out["groups"].items():
    v, z = r["v3_falls"], r["zero_break"]
    if not (v["events"] or z["events"]):
        continue
    zs = ", ".join(f"{x['kind'][0]}@{x['i']}({x['run']})" for x in z["events"][:6]) + (" ..." if len(z["events"]) > 6 else "")
    print(f"{gl} | {r['n']} ({r['run2']} / {r['night1']} / {r['night2']}) | {r['b']} ({r['b_run3']}) | {r['e']} | {r['b_rate']} | {r['longest_without_b_or_e']} | "
          f"{r['eligible_night3']} | {len(v['events'])} / {v['end_demoted']} | {len(z['events'])} [{zs}] / {z['end_demoted']} | {len(z['false_demotions'])}")
print("\nend status changed (v3 -> zero-break):")
for gl, r in changed.items():
    print(f"  {gl}: {r['v3_falls']['end_demoted']} -> {r['zero_break']['end_demoted']}  (n {r['n']}, b {r['b']}, eligible night 3 {r['eligible_night3']}, "
          f"window falls {r['zero_break']['end_falls']})")
for gl, f in false_all:
    print(f"  strict false demotion {gl}: {f}")
for gl, f in false_useful:
    print(f"  USEFUL false demotion {gl}: {f}")
print("\nzero-break window size | false demotions (groups) | demoted at night 3's start, with an eligible cell")
for win, s in sens.items():
    print(f"  {win} | {len(s['false_demotions'])} {s['false_demotions']} | {s['demoted_at_night3_start_with_eligible']}")
print("\nwhole-history break rate of the groups with an eligible cell in night 3's plan (P(0 breaks in 1,000) = (1 - rate)^1000):")
for gl, r in out["groups"].items():
    if r["eligible_night3"]:
        p0 = (1 - r["b_rate"]) ** 1000 if r["b_rate"] is not None else None
        print(f"  {gl}: n {r['n']}, b {r['b']} (run 3 {r['b_run3']}), rate {r['b_rate']}, P0 {p0:.2e}, longest without b/e {r['longest_without_b_or_e']}")
