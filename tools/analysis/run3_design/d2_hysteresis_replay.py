#!/usr/bin/env python3
"""Demotion hysteresis (owner 2026-11-11), replayed on the real sequences: every group's per-dispatch (fall, b, e) codes of run 2, run 3
night 1 and night 2 in ingest order, as the plan builds them (tools/frs/run3_load.load with both nights inherited), through the selector's
own rule (tools/frs/run3_select.demotion_next) with the exit threshold at 0.75 (the 2026-11-08 rule) and 0.70 (the hysteresis). Zero
native ticks, read-only.

    python -B tools/analysis/run3_design/d2_hysteresis_replay.py [--lab C:/BattleShip_lab] [--out logs/run3_design]

Checks before anything is reported: the old rule's events inside night 2 for the flipping group equal the night's own logged events
(kind and window falls, in order; hourly.jsonl), and each night's per-group dispatch count equals the night's close record.
Reports: per group and rule, the events in each run and the status at the end (the next night's start status).
"""
import json
from pathlib import Path

import _common as C
import run3_load as L
import run3_select as rs

a = C.parse(__doc__)
RUN1, RUN2 = a.lab / "crossing_2026-10-15", a.lab / "crossing_2026-10-15_run2"
NIGHTS = [a.lab / "crossing_2026-11-06_run3", a.lab / "crossing_2026-11-10_run3b"]
BOUND = 934                                   # the next plan's bound (959 - 24 - 1); the codes do not depend on it
WIN, ENTER = 1000, 0.75
FLIP = "9|256|326:2-6-1"

D = L.load(RUN1, RUN2, BOUND, inherit=NIGHTS)
tails = D["history"]["tails"]
close = []
for d in NIGHTS:
    rec = [json.loads(x) for x in (d / "run" / "hourly.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()][-1]
    close.append({g["group"]: int((g.get("run3") or {}).get("n", 0)) for g in rec["groups"]})
logged = [(e["kind"], e["window"]["fall"]) for r in (json.loads(x) for x in (NIGHTS[1] / "run" / "hourly.jsonl").read_text(encoding="utf-8").splitlines() if x.strip())
          for e in r["demotions"] if e["group"] == FLIP]


def replay(codes, exit_rate):
    w, falls, b, e, st, ev = [], 0, 0, 0, False, []
    for i, c in enumerate(codes):
        w.append(c)
        falls, b, e = falls + (c & 1), b + ((c >> 1) & 1), e + ((c >> 2) & 1)
        if len(w) > WIN:
            o = w.pop(0)
            falls, b, e = falls - (o & 1), b - ((o >> 1) & 1), e - ((o >> 2) & 1)
        nxt = rs.demotion_next(st, len(w), falls, b, e, WIN, ENTER, exit_rate)
        if nxt != st:
            ev.append((i, "demoted" if nxt else "exit", falls))
        st = nxt
    return ev, st, falls


out = {"groups": {}, "checks": {}}
for gl, t in sorted(tails.items()):
    codes = [int(ch) for ch in t]
    n2, n1 = close[1].get(gl, 0), close[0].get(gl, 0)
    cut1, cut2 = len(codes) - n2 - n1, len(codes) - n2            # run 2 | night 1 | night 2
    row = {"n": len(codes), "night1": n1, "night2": n2}
    for name, rate in (("rule_2026_11_08", ENTER), ("hysteresis", 0.70)):
        ev, st, falls = replay(codes, rate)
        part = lambda lo, hi: [(k, f) for i, k, f in ev if lo <= i < hi]
        row[name] = {"run2": len(part(0, cut1)), "night1": len(part(cut1, cut2)), "night2": part(cut2, len(codes)), "end_demoted": st, "end_falls": falls}
    out["groups"][gl] = row

g = out["groups"][FLIP]
out["checks"]["old_rule_equals_logged_night2"] = g["rule_2026_11_08"]["night2"] == logged
out["checks"]["logged_night2"] = logged
C.dump(a, "d2_hysteresis_replay.json", out)
print(f"checks: old rule == night 2's logged events for {FLIP}: {out['checks']['old_rule_equals_logged_night2']} ({len(logged)} events)")
print("group | n (night 1 / 2) | events 2026-11-08 rule: run 2 / night 1 / night 2 | hysteresis: run 2 / night 1 / night 2 | end status old -> new (falls)")
for gl, r in out["groups"].items():
    o, h = r["rule_2026_11_08"], r["hysteresis"]
    if o["run2"] + o["night1"] + len(o["night2"]) + h["run2"] + h["night1"] + len(h["night2"]) == 0 and not (o["end_demoted"] or h["end_demoted"]):
        continue
    print(f"{gl} | {r['n']} ({r['night1']} / {r['night2']}) | {o['run2']} / {o['night1']} / {len(o['night2'])} | {h['run2']} / {h['night1']} / {len(h['night2'])} | "
          f"{o['end_demoted']} -> {h['end_demoted']} ({h['end_falls']})")
