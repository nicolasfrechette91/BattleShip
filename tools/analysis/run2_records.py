#!/usr/bin/env python3
"""Run 2 (crossing search run 2, 2026-10-16) as data, from the repository's committed records only (read-only).

    python -B tools/analysis/run2_records.py [--out docs/analysis/run2/run2_records.json]

The raw lab folder (C:/BattleShip_lab/crossing_2026-10-15_run2) is not in the repository; for it see run2_lab.py. Every
dataset below names its record and section. Three evidence levels, carried in each dataset's "evidence" field:

    recorded   a number the run's own record states (the lab measured it)
    derived    plain arithmetic on recorded numbers of the same run (sums, shares, differences)
    inferred   combines run 2's numbers with costs measured in OTHER runs, or rests on a stated assumption

`checks` holds consistency tests between a record's tables and its own totals; a failing check is reported, never hidden.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mdrecords as m  # noqa: E402

RUN2 = "frs_crossing_search_run2_2026-10-15.md"
STRAT = "frs_strategy_2026-10-16.md"
ROUTE = "frs_route_insight_2026-10-16.md"
ANOM = "frs_anomaly_inventory_2026-10-16.md"
PCOST = "frs_prefix_cost_2026-10-14.md"
DEFAULT_OUT = m.REPO / "docs" / "analysis" / "run2" / "run2_records.json"
N_WORKERS = 5


def hourly(t2: str) -> Dict[str, Any]:
    rows = m.table_after(t2, "Per hour of the search phase")
    keys = {"dispatches": "dispatches", "breaks": "broke a target", "falls": "falls", "clears_claimed": "clears claimed", "new_cells": "new cells",
            "replacements": "replacements", "ticks": "ticks"}
    data = [{"hour": int(m.num(r["hour"])), **{k: m.num(r[c]) for k, c in keys.items()}} for r in rows]
    checks_m = m.sentence(t2, r"per UTC hour ([\d, ]+)\s*\|")
    return {"evidence": "recorded", "source": m.source(RUN2, "Progress over time", "hour 8 is the search's last 46 minutes"), "rows": data,
            "checks_per_utc_hour": {"evidence": "recorded", "values": m.ints(checks_m.group(1)),
                                    "source": m.source(RUN2, "The run (checks of inherited cells)", "UTC hours from the launch, so the first one includes the open")}}


def totals(t2: str) -> Dict[str, Any]:
    run = {m.strip_md(r["item"]): r["value"] for r in m.table_after(t2, "## The run")}
    d = run["dispatches"]
    tk = run["ticks"]
    th = run["throughput"]
    oc = run["outcomes"]
    ce = run["cells"]
    ch = run["checks of inherited cells"]
    tm = run["time"]
    out = {
        "dispatches": m.ints(d)[0],
        "dispatches_per_level": dict(zip(["9", "8", "7", "6"], [m.ints(x)[1] for x in re.findall(r"level 9: [\d,]+|8: [\d,]+|7: [\d,]+|6: [\d,]+", d)])),
        "ticks": dict(zip(["all", "prefix", "burst", "checks", "verification", "reference", "anchor"],
                          [m.ints(x)[0] for x in re.findall(r"[\d,]{5,}", tk)][:7])),
        "jobs_per_hour": m.ints(th)[0], "ticks_per_job": m.ints(th)[3], "burst_words_per_job": m.ints(th)[4],
        "continued": m.ints(th)[5], "boundaries": m.ints(th)[6],
        "falls": m.ints(oc)[0], "clears_claimed": m.ints(re.search(r"([\d,]+) clears claimed", oc).group(1))[0],
        "bursts_broke_target": m.ints(re.search(r"([\d,]+) bursts broke", oc).group(1))[0],
        "cells_at_close": m.ints(ce)[0], "cells_inherited": m.ints(ce)[1], "cells_new": m.ints(ce)[2],
        "replacements": m.ints(re.search(r"([\d,]+) replacements", ce).group(1))[0],
        "later_arrivals": m.ints(re.search(r"([\d,]+) later arrivals", ce).group(1))[0],
        "beyond_bound": m.ints(re.search(r"([\d,]+) reaches beyond the bound", ce).group(1))[0],
        "eligible_never_drawn": m.ints(re.search(r"\(([\d,]+) of them never checked", ce).group(1))[0],
        "checks": m.ints(ch)[0], "check_worker_s": m.ints(re.search(r"([\d,]+) s of lent-worker time", ch).group(1))[0],
        "wall_s": m.ints(re.search(r"([\d,]+) s wall", tm).group(1))[0],
        "search_s": m.ints(re.search(r"search ([\d,]+) s", tm).group(1))[0],
    }
    return {"evidence": "recorded", "source": m.source(RUN2, "The run"), "values": out}


def best_timeline(t2: str) -> Dict[str, Any]:
    rows = m.table_after(t2, "The best verified clear over the run")
    data = []
    for r in rows:
        best = m.ints(r["best"])
        el = m.strip_md(r["elapsed"])
        mins = sum(int(a) * (60 if u == "h" else 1) for a, u in re.findall(r"(\d+)\s*(h|min)", el))
        data.append({"best": best[0], "time_passed": best[1], "previous": int(m.num(r["previous"])), "gain": int(m.num(r["gain"])),
                     "dispatch": m.ints(r["dispatch, cell, k"])[0], "cell": m.ints(r["dispatch, cell, k"])[1], "start_tick": int(m.num(r["start tick"])),
                     "elapsed_min": mins})
    return {"evidence": "recorded", "source": m.source(RUN2, "Progress over time (best verified clear)"), "start_best": 1429,
            "start_note": "run 1's best verified clear, imported at the open", "rows": sorted(data, key=lambda x: x["elapsed_min"])}


def earliest_per_level(t2: str) -> Dict[str, Any]:
    rows = m.table_after(t2, "The earliest arrival per level")
    data = []
    for r in rows:
        imp = [{"tick": int(a.replace(",", "")), "dispatch": int(b.replace(",", ""))} for a, b in re.findall(r"([\d,]+) at ([\d,]+) \(", r["run 2 improvements (tick at dispatch, UTC)"])]
        data.append({"level": int(m.num(r["level"])), "run1": int(m.num(r["run 1"])), "improvements": imp, "end": int(m.num(r["earliest at the stop"])),
                     "lead_on_reference": int(m.num(r["lead on the reference"]))})
    return {"evidence": "recorded", "source": m.source(RUN2, "Progress over time (earliest arrival per level)"), "rows": data}


def level9_groups(ts: str, t2: str) -> Dict[str, Any]:
    s = m.sentence(ts, r"group with target 6 left \(mask\s+64\) took ([\d,]+) for 0 breaks and ([\d,]+) falls, the group with target 1 left ([\d,]+) for (\d+) clears, "
                       r"the group with target 8 left ([\d,]+) for (\d+)")
    v = [int(x.replace(",", "")) for x in s.groups()]
    r2 = m.sentence(t2, r"the mask-64 group holds .*?received ([\d,]+) level-9 dispatches.*?mask-2 group received ([\d,]+) for (\d+) claimed clears and the mask-256 group ([\d,]+) for (\d+)")
    w = [int(x.replace(",", "")) for x in r2.groups()]
    cells = m.sentence(t2, r"([\d,]+) cells with target 1 left \(mask 2\), ([\d,]+) with target 8 left \(mask 256\) and ([\d,]+) with target 6 left")
    c = [int(x.replace(",", "")) for x in cells.groups()]
    return {"evidence": "recorded", "source": m.source(STRAT, "5. The search's limits", "all level-9 dispatches per group of remaining target"),
            "rows": [{"group": "target 6 left (mask 64)", "dispatches": v[0], "clears": 0, "falls": v[1], "cells_seed579": c[2]},
                     {"group": "target 1 left (mask 2)", "dispatches": v[2], "clears": v[3], "cells_seed579": c[0]},
                     {"group": "target 8 left (mask 256)", "dispatches": v[4], "clears": v[5], "cells_seed579": c[1]}],
            "seed579_only": {"evidence": "recorded", "source": m.source(RUN2, "What limited progress", "dispatches from seed 579's descendants only"),
                             "dispatches": {"mask 64": w[0], "mask 2": w[1], "mask 256": w[3]}, "clears": {"mask 64": 0, "mask 2": w[2], "mask 256": w[4]}}}


def chain(ts: str) -> Dict[str, Any]:
    rows = m.table_after(ts, "The 1,245's chain is 12 kept cells")
    data = []
    for r in rows:
        link = m.strip_md(r["link"])
        if " to " in link:
            continue                                            # links 1 to 4: run 1, no per-link numbers in run 2's terms
        created = m.strip_md(r["created at"])
        first = m.strip_md(r["first dispatched at"])

        def counter(cell: str) -> int:  # "run 2: 14,659 (about 22,000 dispatches later)" -> 14659; "14,661" -> 14661
            return m.ints(re.sub(r"^run \d+:\s*", "", cell))[0]
        data.append({"link": int(link), "level_tick": m.strip_md(r["level, tick"]), "created_run": "run 1" if created.startswith("run 1") else "run 2",
                     "created_at": counter(created), "first_dispatch_run": "run 2", "first_dispatched_at": counter(first),
                     "dispatches": int(m.num(r["dispatches"]))})
    return {"evidence": "recorded", "source": m.source(STRAT, "5. The search's limits (the 1,245's chain)",
                                                      "dispatch counters; link 5 was created in run 1 (its counter is run 1's)"), "rows": data}


def bests_breaks(tr: str) -> Dict[str, Any]:
    rows = m.table_after(tr, "### 3.4 The verified bests")
    parsed: Dict[str, List[Dict[str, Any]]] = {}
    order = []
    for r in rows:
        name = m.strip_md(r["clear"])
        key = m.ints(name)[0]
        label = f"{key:,}"
        body = r["breaks (tick: target, class, status class, floor)"]
        base: List[Dict[str, Any]] = []
        ref = re.match(r"(?:same as|as) the ([\d,]+) (?:to|with) ([\d,]+)", body)
        if ref and m.ints(ref.group(1))[0] != key:
            src = parsed[f"{m.ints(ref.group(1))[0]:,}"]
            cut = m.ints(ref.group(2))[0]
            base = [b for b in src if b["tick"] <= cut]
        if body.startswith("as the"):
            # the reference: the splice's breaks with the last ticks listed after "with"
            src = parsed[f"{m.ints(ref.group(1))[0]:,}"]
            new_ticks = m.ints(body.split("with", 1)[1])
            base = [dict(b) for b in src]
            for b, t in zip(base[-len(new_ticks):], new_ticks):
                b["tick"] = t
            parsed[label] = base
            order.append({"clear": label, "source": name})
            continue
        for tick, target, cls in re.findall(r"([\d,]+): (\d) (A0|A1|A2|G)\b", body):
            base.append({"tick": int(tick.replace(",", "")), "target": int(target), "class": cls})
        parsed[label] = sorted(base, key=lambda b: b["tick"])
        order.append({"clear": label, "source": name})
    for k, v in parsed.items():
        if len(v) != 10 or len({b["target"] for b in v}) != 10:
            raise m.RecordError(f"clear {k}: {len(v)} breaks parsed")
    per_target = {}
    for t in range(10):
        ticks = {k: next(b["tick"] for b in v if b["target"] == t) for k, v in parsed.items()}
        best = min(ticks, key=lambda k: ticks[k])
        per_target[str(t)] = {"earliest": ticks[best], "in_clear": best, "per_clear": ticks}
    return {"evidence": "recorded", "source": m.source(ROUTE, "3.4 The verified bests, break by break"), "clears": order, "breaks": parsed,
            "per_target_earliest_among_bests": {"evidence": "derived", "values": per_target,
                                                "note": "earliest break of each target among these verified clears only, not over every trajectory"}}


def orders(ts: str) -> Dict[str, Any]:
    full = m.table_after(ts, "5 complete orders")
    l7 = m.table_after(ts, "**Level 7**")
    complete = [{"order": m.strip_md(r["complete order"]), "fastest": m.ints(r["fastest clock"])[0], "fastest_source": m.strip_md(r["fastest clock"]),
                 "clears": m.ints(r["verified clears with it"])[0], "composite": int(m.num(r["composite"]))} for r in full]
    level7 = []
    for r in l7:
        o = m.strip_md(r["order prefix"])
        level7.append({"prefix": re.sub(r"\s*\(.*\)$", "", o), "note": (re.search(r"\((.*)\)$", o) or [None, ""])[1],
                       "fastest_arrival": m.ints(r["fastest arrival"])[0], "fastest_source": m.strip_md(r["fastest arrival"]),
                       "composite": int(m.num(r["composite"])), "trajectories": int(m.num(r["trajectories"])),
                       "dispatches": m.ints(r["dispatches from states with exactly this prefix"])[0]})
    counts = m.sentence(ts, r"180 distinct order prefixes exist .*?: ([\d,]+) at level 4, ([\d,]+) at level 5, ([\d,]+) at level 6, ([\d,]+) at level 7,\s*([\d,]+) at level 8, "
                            r"([\d,]+) at level 9 and \*\*(\d+) complete orders\*\*")
    return {"evidence": "recorded", "source": m.source(STRAT, "3. Target orders explored", "archive and lab together, not run 2 alone"),
            "complete": complete, "level7": level7, "prefixes_per_level": dict(zip(["4", "5", "6", "7", "8", "9", "10"], [int(x.replace(",", "")) for x in counts.groups()]))}


def segments(ts: str) -> Dict[str, Any]:
    rows = m.table_after(ts, "**The 1,245 order, segment by segment**")
    data = []
    for r in rows:
        pair = m.strip_md(r["pair"])
        if pair == "sum":
            continue
        data.append({"pair": pair.replace("->", "→"), "clear": int(m.num(r["clear"])), "best": int(m.num(r["best"])), "where": m.strip_md(r["where"]),
                     "n": int(m.num(r["n"])), "median": int(m.num(r["median"])), "room": int(m.num(r["room (best)"]))})
    return {"evidence": "recorded", "source": m.source(STRAT, "2. Fastest observed transitions", "best = fastest observed anywhere (archive, frontier, probe, runs 1 and 2)"),
            "rows": data}


def signals(t2: str) -> Dict[str, Any]:
    rows = m.table_after(t2, "## Effects of the signals")
    data, sig = [], ""
    for r in rows:
        sig = m.strip_md(r["signal"]) or sig
        data.append({"signal": sig, "bucket": m.strip_md(r["bucket"]), "jobs": int(m.num(r["jobs"])), "broke": m.ints(r["broke a target (share)"])[0],
                     "share_pct": float(re.search(r"\(([\d.]+) %\)", r["broke a target (share)"]).group(1)), "new_cells_per_job": float(r["new cells per job"])})
    return {"evidence": "recorded", "source": m.source(RUN2, "Effects of the signals"), "rows": data}


def anomalies(ta: str) -> Dict[str, Any]:
    rows = m.table_after(ta, "### 3.5 Ranked flagged events")
    data = [{"rank": int(m.num(r["rank"])), "test": m.strip_md(r["test"]), "record": m.strip_md(r["record (trace), tick"]), "extreme": m.strip_md(r["how extreme"]),
             "shows": m.strip_md(r["what the data shows"]), "run2": "crossing_2026-10-15_run2" in r["record (trace), tick"]} for r in rows]
    return {"evidence": "recorded", "source": m.source(ANOM, "3.5 Ranked flagged events", "an offline scan of 510 traces; nothing flagged is a finding until replayed"),
            "rows": data}


def per_tick_costs(tp: str) -> Dict[str, Any]:
    rows = m.table_after(tp, "### 2.3 Per tick: round trip against native update")
    rt = m.first(rows, "quantity", "step round trip under load")
    rt2 = m.first(rows, "quantity", "same, sd2")
    smoke = float(re.search(r"([\d.]+) ms mean", rt["value"]).group(1))
    sd2 = float(re.search(r"([\d.]+) ms mean", rt2["value"]).group(1))
    frame = m.sentence(tp, r"the native frame \(event pump, scheduler, controller read, game update, capture\) is about ([\d.]+) ms")
    return {"evidence": "recorded", "source": m.source(PCOST, "2.3 Per tick", "measured in sd2 and the lab smoke run, NOT in run 2"),
            "step_ms_low": sd2, "step_ms_high": smoke, "native_frame_ms": float(frame.group(1))}


def worker_time_model(tot: Dict[str, Any], cost: Dict[str, Any]) -> Dict[str, Any]:
    """Per-job worker seconds in run 2: the totals are run 2's, the per-tick costs are sd2's / the smoke's (inferred)."""
    v = tot["values"]
    worker_s = N_WORKERS * v["wall_s"]
    job_s = (worker_s - v["check_worker_s"]) / v["dispatches"]
    burst = v["burst_words_per_job"]
    prefix = v["ticks_per_job"] - burst
    out = {}
    for tag, ms in (("low", cost["step_ms_low"]), ("high", cost["step_ms_high"])):
        stepping = v["ticks_per_job"] * ms / 1000.0
        native = v["ticks_per_job"] * cost["native_frame_ms"] / 1000.0
        out[tag] = {"per_job_s": round(job_s, 3), "prefix_stepping_s": round(prefix * ms / 1000.0, 3), "burst_stepping_s": round(burst * ms / 1000.0, 3),
                    "of_which_native_frames_s": round(native, 3), "rest_s": round(job_s - stepping, 3)}
    shares = {"checks_share_of_worker_time": round(v["check_worker_s"] / worker_s, 4), "worker_s": worker_s, "job_s": round(job_s, 3)}
    return {"evidence": "inferred", "assumptions": [
        f"{N_WORKERS} worker slots busy for the whole wall time (the record's 28,505 s); checks used {v['check_worker_s']:,} of those worker-seconds",
        f"a stepped tick costs {cost['step_ms_low']} to {cost['step_ms_high']} ms under lab load (sd2 and the smoke run, docs/{PCOST} 2.3), not measured in run 2",
        f"the native game frame is about {cost['native_frame_ms']} ms of that tick (same record)",
        "'rest' = standby boot wait, close, result transfer, ingest, selection and verification borrow, which no record splits for run 2"],
        "derived_shares": shares, "range": out}


def build() -> Dict[str, Any]:
    t2, ts, tr, ta, tp = m.read(RUN2), m.read(STRAT), m.read(ROUTE), m.read(ANOM), m.read(PCOST)
    data: Dict[str, Any] = {"generated_by": "tools/analysis/run2_records.py", "inputs": [f"docs/{d}" for d in (RUN2, STRAT, ROUTE, ANOM, PCOST)]}
    data["hourly"] = hourly(t2)
    data["totals"] = totals(t2)
    data["best_timeline"] = best_timeline(t2)
    data["earliest_per_level"] = earliest_per_level(t2)
    data["level9_groups"] = level9_groups(ts, t2)
    data["chain_1245"] = chain(ts)
    data["bests_breaks"] = bests_breaks(tr)
    data["orders"] = orders(ts)
    data["segments_1245"] = segments(ts)
    data["signals"] = signals(t2)
    data["anomalies"] = anomalies(ta)
    data["per_tick_costs"] = per_tick_costs(tp)
    data["worker_time"] = worker_time_model(data["totals"], data["per_tick_costs"])
    data["checks"] = consistency(data)
    return data


def consistency(d: Dict[str, Any]) -> List[Dict[str, Any]]:
    v = d["totals"]["values"]
    rows = d["hourly"]["rows"]
    out = []

    def chk(name: str, got: Any, want: Any) -> None:
        out.append({"check": name, "got": got, "want": want, "ok": got == want})

    for col, tot in (("dispatches", "dispatches"), ("new_cells", "cells_new"), ("replacements", "replacements"), ("breaks", "bursts_broke_target"),
                     ("falls", "falls"), ("clears_claimed", "clears_claimed")):
        chk(f"hourly {col} sums to the run total", int(sum(r[col] for r in rows)), v[tot])
    chk("dispatches per level sum to the total", sum(v["dispatches_per_level"].values()), v["dispatches"])
    chk("the level-9 groups sum to the level-9 dispatches", sum(g["dispatches"] for g in d["level9_groups"]["rows"]), v["dispatches_per_level"]["9"])
    t = v["ticks"]
    chk("tick categories sum to all ticks", t["prefix"] + t["burst"] + t["checks"] + t["verification"] + t["reference"] + t["anchor"], t["all"])
    chk("checks per UTC hour sum to the checks", sum(d["hourly"]["checks_per_utc_hour"]["values"]), v["checks"])
    chk("inherited + new cells = cells at close", v["cells_inherited"] + v["cells_new"], v["cells_at_close"])
    segs = d["segments_1245"]["rows"]
    chk("the 1,245's segments sum to 1,245", sum(s["clear"] for s in segs), 1245)
    chk("the 1,245's best-segment room sums to 580", sum(s["room"] for s in segs), 580)
    b = d["bests_breaks"]["breaks"]
    chk("each verified best's last break is its clock", all(v2[-1]["tick"] == int(k.replace(",", "")) for k, v2 in b.items()), True)
    return out


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    data = build()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    bad = [c for c in data["checks"] if not c["ok"]]
    print(f"wrote {a.out}: {len(data) - 3} datasets, {len(data['checks'])} consistency checks, {len(bad)} failing")
    for c in bad:
        print(f"  FAIL {c['check']}: got {c['got']}, record says {c['want']}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
