#!/usr/bin/env python3
"""D1 A/B replay: the same input rows on two executables, compared tick by tick. NATIVE: it boots the game; run it only with the
owner's go.

A = the pinned lab executable (BattleShip.exe 30a3913b: bare sinf/cosf go to the host CRT on MSVC).
B = the same files with BattleShip.exe built with -DSSB64_MSVC_LIBULTRA_TRIG=ON (bare sinf/cosf go to libultra, as on the N64).

Routes: the lab best 1,245 (run 2 verifications, by words digest), the registered 1,885 (lab import reference) and the 468-row
scripted baseline (tas_input_2/mario_743.btti, its raw rows). Every replay is a fresh process from tick 0 with the verify flags
(rl/m8_rd_session.FLAGS_VERIFY) through rl/m7f_trace.run_stepping_trace, the path rl/frs_verify uses; submission stops after a
fall. A runs once, B runs twice (B's own determinism). The baseline also gets one native text replay per executable (the M1e path).

Per route it reports: the first tick whose m8_rd record differs (A vs B), the fields that differ there and by how many float32
ulps, the largest position difference over the route, the first ticks the difference reaches 1, 10 and 300 units, the first tick a
discrete field (status, ground/air, jumps, targets) differs, how many live ticks change m8_rd_cell_v1 key, both outcomes,
completion clocks and break lists. Reads no native RNG. Writes only below --out, which must not exist.

    python -B tools/audit/trig_ab_replay.py --exe-a C:/BattleShip_lab/import/exe/BattleShip.exe \
        --exe-b C:/BattleShip_lab/probes/trig_ab_2026-11-04_exe_b/BattleShip.exe --out C:/BattleShip_lab/probes/trig_ab_2026-11-04

    python -B tools/audit/trig_ab_replay.py --self-test      (zero ticks: the comparison on stored traces)

Exit code 0: done (whatever the verdicts); 2: refused or a replay could not run.
"""
from __future__ import annotations

import argparse
import copy
import gzip
import json
import math
import struct
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "rl"))

import frs_verify as fv  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_claims as mclaims  # noqa: E402
import m8_rd_worker as mw  # noqa: E402

LAB = Path("C:/BattleShip_lab")
RUN2_VERIFICATIONS = LAB / "crossing_2026-10-15_run2" / "run" / "verifications.jsonl"
BEST_1245_DIGEST = "1519833e8569ff7f6f27852727597dfac5a184d50c8580f9544e22b254828f14"
STORED_TRACES = {"best_1245": LAB / "crossing_2026-10-15_run2" / "run" / "traces" / "clear_n36236_c8692_k0_r1.json.gz",
                 "ref_1885": LAB / "import" / "reference" / "trace.json.gz"}
DISCRETE = ("fighter_status_id", "ground_air_state", "jumps_used", "targets_remaining", "facing_direction", "game_status")
Action = Tuple[int, int, int, int]


# -- routes ------------------------------------------------------------------------------------------------------------------------------


def words_to_actions(words: bytes) -> List[Action]:
    return [(*mcell.TRIPLES[w], i) for i, w in enumerate(words)]


def load_routes() -> Dict[str, Dict[str, Any]]:
    import m7f_trace as tr

    best = None
    with open(RUN2_VERIFICATIONS, encoding="utf-8") as f:
        for ln in f:
            r = json.loads(ln)
            if r.get("words_digest") == BEST_1245_DIGEST:
                best = r
    if best is None:
        raise SystemExit(f"refused: no verification with words digest {BEST_1245_DIGEST[:12]} in {RUN2_VERIFICATIONS}")
    w1245 = bytes.fromhex(best["words_hex"])
    if mcell.words_digest(w1245) != BEST_1245_DIGEST or len(w1245) != 1245:
        raise SystemExit("refused: the 1,245 words do not reproduce their digest")
    ref = fv.load_reference(LAB / "import" / "reference", fv.real_analyse)
    if ref["problems"]:
        raise SystemExit(f"refused: reference problems {ref['problems']}")
    return {"best_1245": {"actions": words_to_actions(w1245), "expect": 1245},
            "ref_1885": {"actions": words_to_actions(ref["words"]), "expect": 1885},
            "baseline_468": {"actions": tr.tas_actions(), "expect": 447}}


# -- replay ------------------------------------------------------------------------------------------------------------------------------


def frozen_for(exe: Path, frozen: Mapping[str, Any]) -> Dict[str, Any]:
    """The lab pins with the executable's own hash (B differs from A only in BattleShip.exe)."""
    out = copy.deepcopy(dict(frozen))
    out["exe_copy_sha256"]["BattleShip.exe"] = mw.sha256_file(exe)
    return out


def replay(exe: Path, frozen: Mapping[str, Any], actions: Sequence[Action], work: Path, label: str, slot: int) -> Dict[str, Any]:
    import m7f_trace as tr

    bad = fv.frozen_exe_problems(exe.parent, frozen)
    if bad:
        raise RuntimeError(f"pin drift beside {exe}: {bad}")
    acts = fv.StopAfterFailure(list(actions))
    w = work / label
    try:
        return tr.run_stepping_trace(label, exe, acts, w, extra_env=dict(fv.FLAGS_VERIFY), index=9100 + slot, rank=8 + slot,
                                     on_ready=acts.on_ready)
    finally:
        mw.remove_tree_retry(w / "runtime", runtime=True)
        mw.remove_tree_retry(w / "episodes")


# -- comparison --------------------------------------------------------------------------------------------------------------------------


def ulp32(x: float) -> float:
    a = abs(float(x))
    if a == 0.0 or not math.isfinite(a):
        return float("nan")
    b = struct.unpack("<I", struct.pack("<f", a))[0]
    return struct.unpack("<f", struct.pack("<I", b + 1))[0] - a


def leaf_diffs(a: Any, b: Any, path: str = "") -> List[Tuple[str, Any, Any]]:
    """Exact differences between two JSON values (type-strict: 1 != 1.0), as (path, a, b)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out: List[Tuple[str, Any, Any]] = []
        for k in sorted(set(a) | set(b)):
            out += leaf_diffs(a.get(k), b.get(k), f"{path}.{k}" if path else str(k))
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += leaf_diffs(x, y, f"{path}[{i}]")
        return out
    if a != b or type(a) is not type(b):
        return [(path, a, b)]
    return []


def describe(path: str, a: Any, b: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = {"field": path, "a": a, "b": b}
    if isinstance(a, float) and isinstance(b, float):
        u = ulp32(max(abs(a), abs(b)))
        d["abs"] = abs(a - b)
        d["ulps"] = round(abs(a - b) / u, 2) if u == u else None
    return d


def outcome(trace: Mapping[str, Any]) -> Dict[str, Any]:
    steps = trace.get("steps") or []
    br = fv.breaks_of(trace, fv.real_analyse)
    facts = mclaims.clear_facts(trace, len(br))
    last = steps[-1] if steps else None
    fell = last is not None and mcell.is_native_failure(last["observation"], last["state"])
    ticks_ok = all(int(s["consumed_tick"]) == i and int(s["observation"]["input_tick"]) == i + 1 for i, s in enumerate(steps))
    return {"outcome": "clear" if facts["all"] else "fall" if fell else "ended_other", "ticks": len(steps), "ticks_ok": ticks_ok,
            "completion_input_tick": facts["completion_input_tick"], "completion_time_passed": facts["completion_time_passed"],
            "breaks": br, "final_chain": fv.chain_of(trace["initial"], steps).hex(), "startup_s": trace.get("startup_s")}


def compare(a: Mapping[str, Any], b: Mapping[str, Any]) -> Dict[str, Any]:
    """A vs B tick by tick. Tick numbers are input ticks (step i is input tick i + 1; the observe reply is tick 0)."""
    clf = mcell.Classifier()
    ra = [mcell.tick0_record(a["initial"])] + [mcell.record_of(s) for s in a["steps"]]
    rb = [mcell.tick0_record(b["initial"])] + [mcell.record_of(s) for s in b["steps"]]
    oa = [a["initial"]] + list(a["steps"])
    ob = [b["initial"]] + list(b["steps"])
    n = min(len(ra), len(rb))
    first = None
    first_entity = None
    first_discrete = None
    reach = {1.0: None, 10.0: None, 300.0: None}
    max_d, max_tick = 0.0, None
    record_diff_ticks = 0
    key_live, key_diff, first_key = 0, 0, None
    for t in range(n):
        if mcell.record_digest(ra[t]) != mcell.record_digest(rb[t]):
            record_diff_ticks += 1
            if first is None:
                first = t
        if first_entity is None and oa[t].get("entity") != ob[t].get("entity"):
            first_entity = t
        o1, o2 = oa[t]["observation"], ob[t]["observation"]
        if first_discrete is None and any(o1[k] != o2[k] for k in DISCRETE):
            first_discrete = t
        d = math.hypot(float(o1["position_x"]) - float(o2["position_x"]), float(o1["position_y"]) - float(o2["position_y"]))
        if d > max_d:
            max_d, max_tick = d, t
        for thr in reach:
            if reach[thr] is None and d >= thr:
                reach[thr] = t
        if t > 0:
            k1 = mcell.cell_key(o1, oa[t]["spatial"], clf)
            k2 = mcell.cell_key(o2, ob[t]["spatial"], clf)
            if k1 is not None or k2 is not None:
                key_live += 1
                if k1 != k2:
                    key_diff += 1
                    if first_key is None:
                        first_key = t
    at_first = []
    if first is not None:
        at_first = [describe(p, x, y) for p, x, y in leaf_diffs(ra[first], rb[first])][:24]
    return {"compared_ticks": n, "len_a": len(ra), "len_b": len(rb), "first_record_diff_tick": first,
            "fields_at_first_diff": at_first, "record_diff_ticks": record_diff_ticks, "first_entity_diff_tick": first_entity,
            "first_discrete_diff_tick": first_discrete, "max_position_diff": max_d, "max_position_diff_tick": max_tick,
            "first_tick_position_diff_ge": {str(k): v for k, v in reach.items()}, "live_ticks": key_live,
            "live_ticks_cell_key_differs": key_diff, "first_cell_key_diff_tick": first_key}


def same_replay(x: Mapping[str, Any], y: Mapping[str, Any]) -> bool:
    return outcome(x) == {**outcome(y), "startup_s": outcome(x)["startup_s"]} and compare(x, y)["first_record_diff_tick"] is None


# -- self-test (zero ticks) --------------------------------------------------------------------------------------------------------------


def self_test() -> int:
    ok = True
    for name, path in STORED_TRACES.items():
        with gzip.open(path, "rt", encoding="utf-8") as f:
            t = json.load(f)
        c = compare(t, t)
        good = c["first_record_diff_tick"] is None and c["live_ticks_cell_key_differs"] == 0 and c["max_position_diff"] == 0.0
        u = copy.deepcopy(t)
        i = 500
        x = float(u["steps"][i - 1]["observation"]["position_x"])
        u["steps"][i - 1]["observation"]["position_x"] = x + ulp32(x)
        c2 = compare(t, u)
        good2 = (c2["first_record_diff_tick"] == i and c2["record_diff_ticks"] == 1 and c2["first_discrete_diff_tick"] is None
                 and c2["fields_at_first_diff"][0]["field"] == "o.position_x" and c2["fields_at_first_diff"][0]["ulps"] == 1.0)
        o = outcome(t)
        good3 = o["outcome"] == "clear" and o["completion_input_tick"] == {"best_1245": 1245, "ref_1885": 1885}[name]
        print(f"self-test {name}: identical={good} injected_1ulp_at_{i}={good2} outcome={o['outcome']}@{o['completion_input_tick']}"
              f" ok={good3}")
        ok = ok and good and good2 and good3
    print("self-test", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# -- main --------------------------------------------------------------------------------------------------------------------------------


def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exe-a", type=Path)
    ap.add_argument("--exe-b", type=Path)
    ap.add_argument("--frozen", type=Path, default=LAB / "import" / "frozen_runtime.json")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not (a.exe_a and a.exe_b and a.out):
        print("refused: --exe-a, --exe-b and --out are required", file=sys.stderr)
        return 2
    out = a.out.resolve()
    if out.exists() or ROOT in out.parents:
        print(f"refused: {out} exists or lies inside the checkout", file=sys.stderr)
        return 2
    import m7_runtime
    import m7f_trace as tr

    if m7_runtime.list_processes_named():
        print("refused: a BattleShip process is running", file=sys.stderr)
        return 2
    frozen = json.loads(a.frozen.read_text(encoding="utf-8"))
    fa = frozen_for(a.exe_a, frozen)
    fb = frozen_for(a.exe_b, frozen)
    if fa["exe_copy_sha256"]["BattleShip.exe"] != frozen["exe_copy_sha256"]["BattleShip.exe"]:
        print("refused: --exe-a is not the pinned lab executable", file=sys.stderr)
        return 2
    if fb["exe_copy_sha256"]["BattleShip.exe"] == fa["exe_copy_sha256"]["BattleShip.exe"]:
        print("refused: --exe-b is the same file as --exe-a", file=sys.stderr)
        return 2
    routes = load_routes()
    out.mkdir(parents=True)
    work = out / "work"
    summary: Dict[str, Any] = {"exe_a": str(a.exe_a), "exe_b": str(a.exe_b), "sha_a": fa["exe_copy_sha256"]["BattleShip.exe"],
                               "sha_b": fb["exe_copy_sha256"]["BattleShip.exe"], "flags": fv.FLAGS_VERIFY, "routes": {},
                               "utc_start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    slot = 0
    for name, r in routes.items():
        traces = {}
        for lab, exe, fz in (("A", a.exe_a, fa), ("B1", a.exe_b, fb), ("B2", a.exe_b, fb)):
            t0 = time.perf_counter()
            traces[lab] = replay(exe, fz, r["actions"], work, f"{name}_{lab}", slot % 4)
            slot += 1
            fv.save_trace(out / "traces" / f"{name}_{lab}.json.gz", traces[lab])
            print(f"{name} {lab}: {outcome(traces[lab])['outcome']} {len(traces[lab]['steps'])} steps "
                  f"{time.perf_counter() - t0:.1f} s", flush=True)
        row: Dict[str, Any] = {"rows": len(r["actions"]), "A": outcome(traces["A"]), "B": outcome(traces["B1"]),
                               "B_deterministic": same_replay(traces["B1"], traces["B2"]), "A_vs_B": compare(traces["A"], traces["B1"])}
        if name in STORED_TRACES:
            with gzip.open(STORED_TRACES[name], "rt", encoding="utf-8") as f:
                stored = json.load(f)
            row["A_equals_stored_trace"] = compare(stored, traces["A"])["first_record_diff_tick"] is None \
                and outcome(stored)["final_chain"] == row["A"]["final_chain"]
        summary["routes"][name] = row
        print(json.dumps({name: {k: row[k] for k in row if k != "A_vs_B"} | {"first_record_diff_tick":
                                                                               row["A_vs_B"]["first_record_diff_tick"]}}, default=str),
              flush=True)
    summary["native_text_replay"] = {}
    for lab, exe in (("A", a.exe_a), ("B", a.exe_b)):
        summary["native_text_replay"][lab] = tr.native_tas_replay(exe, work / f"native_{lab}")
        print(f"native text replay {lab}: complete={summary['native_text_replay'][lab]['complete_line']} "
              f"checksum={summary['native_text_replay'][lab]['checksum_line']}", flush=True)
    summary["utc_end"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(out / "summary.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, indent=1, default=str)
        f.write("\n")
    mw.remove_tree_retry(work)
    print(f"wrote {out / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
