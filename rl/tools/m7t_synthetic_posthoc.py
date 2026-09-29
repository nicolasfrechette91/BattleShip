#!/usr/bin/env python3
"""Post-hoc diagnostics of the registered M7t synthetic prerequisite run (rl/tools/m7t_synthetic_prereq.py).

NEVER decides anything: the registered outcome is results.json / tests. This tool only reads the run directory,
re-simulates recorded words with the harness's own world (zero native ticks, no optimizer step) and loads the saved
networks for forward passes. `--memory` is the one exception: a bounded supplemental memory measurement (1,000
optimizer steps per arm on synthetic seed 0 data plus one evaluation batch), needed because the registered run's
in-process memory probe returned zeros.

    python rl/tools/m7t_synthetic_posthoc.py --run DIR            # writes DIR/posthoc.json
    python rl/tools/m7t_synthetic_posthoc.py --run DIR --memory   # writes DIR/memory_supplement.json
"""
from __future__ import annotations

import argparse
import ctypes
import gzip
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "rl" / "tools"))
sys.path.insert(0, str(REPO / "rl"))

import m7t_synthetic_prereq as m  # noqa: E402


class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def mem() -> Dict[str, float]:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    fn = k32.K32GetProcessMemoryInfo
    fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    fn.restype = wintypes.BOOL
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    if not fn(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        return {"error": ctypes.get_last_error()}
    return {"working_set_mb": pmc.WorkingSetSize / 2 ** 20, "peak_working_set_mb": pmc.PeakWorkingSetSize / 2 ** 20,
            "private_mb": pmc.PagefileUsage / 2 ** 20, "peak_private_mb": pmc.PeakPagefileUsage / 2 ** 20}


def trajectory(words: List[int], starts=None) -> Dict[str, np.ndarray]:
    s0 = m.start_state(1) if starts is None else m.start_state(1, *starts)
    r = m.initial_record(s0)
    rows = [r]
    for w in words:
        r, _ = m.advance(r, np.array([w], np.int64))
        rows.append(r)
    return {k: np.concatenate([rw[k] for rw in rows]) for k in m.REC}


def posthoc(run: Path) -> Dict[str, Any]:
    torch = m.torch_mod()
    res = json.loads((run / "results.json").read_text(encoding="utf-8"))
    out: Dict[str, Any] = {"tool": "m7t_synthetic_posthoc_v1", "never_decides": True, "seeds": {}}
    for key, sres in res["seeds"].items():
        seed = int(key)
        ev = json.load(gzip.open(run / f"s{seed}_episodes.json.gz", "rt", encoding="utf-8"))
        so: Dict[str, Any] = {}
        # 1. rare-goal returns by arm; path diversity among T returns
        for arm in ("T", "S", "init"):
            eps = ev[f"{arm}_rare"]
            so[f"{arm}_rare"] = {"n": len(eps), "success": int(sum(e["success"] for e in eps)),
                                 "ends": {x: int(sum(e["end"] == x for e in eps)) for x in ("reached", "budget", "dead")}}
        succ = [e for e in ev["T_rare"] if e["success"]]
        pref = {tuple(e["words"][:60]) for e in succ}
        so["T_rare_success_distinct_60tick_prefixes"] = len(pref)
        so["T_rare_reach_ticks"] = sorted(e["reach"] for e in succ)
        # 2. OFF / MODEL flag timing on successful healthy episodes (false alarms)
        healthy = [e for e in ev["T_rare"] + ev["T_S2"] if e["success"]]
        so["healthy_first_OFF_tick"] = sorted(e["flags"]["OFF"] for e in healthy if e["flags"]["OFF"] is not None)
        so["healthy_first_MODEL_tick"] = sorted(e["flags"]["MODEL"] for e in healthy if e["flags"]["MODEL"] is not None)
        # 3. which support features dominate at the first OFF flag of healthy episodes
        sd = m.SeedData(seed, m.REG["data"]["episodes"], m.HORIZON, m.REG["data"]["phase_a"], m.REG["data"]["held_out"])
        rng = np.random.default_rng(m.seed_int("support", seed))
        ref_rows = rng.choice(sd.train_rows, size=min(m.REG["diagnostics"]["support_reference"], len(sd.train_rows)),
                              replace=False)
        ref = ((sd.obs(ref_rows) - sd.mean) / sd.std)[:, m.SUPPORT_COLS]
        names = [f"class{k}" for k in range(23)] + [f"agent{k}" for k in range(45) if k != 24]
        contrib: Dict[str, float] = {}
        for e in healthy[:20]:
            t = e["flags"]["OFF"]
            if t is None:
                continue
            tr = trajectory(e["words"])
            ob = m.build_obs({k: v[t:t + 1] for k, v in tr.items()})
            q = ((ob - sd.mean) / sd.std)[:, m.SUPPORT_COLS][0]
            nn = ref[np.argmin(((ref - q) ** 2).sum(1))]
            d2 = (q - nn) ** 2
            for k in np.argsort(-d2)[:3]:
                contrib[names[k]] = contrib.get(names[k], 0.0) + float(d2[k] / d2.sum())
        so["off_flag_top_features_share"] = dict(sorted(contrib.items(), key=lambda kv: -kv[1])[:8])
        # 4. failures: did T sit near the goal with a collapsed distance? (false arrival)
        fails = [e for e in ev["T_rare"] + ev["T_S2"] if not e["success"]]
        so["T_failures"] = {"n": len(fails), "min_d_le_30": int(sum(min(e["dg"]) <= 30 for e in fails)),
                            "false_arrival_flagged": int(sum(e["flags"]["FALSE_ARRIVAL"] is not None for e in fails))}
        # 5. S2: would T have reached later? distance of the final position to the goal cell (cells)
        s2 = []
        for e in ev["T_S2"]:
            tr = trajectory(e["words"])
            gi, gj, gc = m.code_to_cell(e["goal"])
            s2.append({"success": e["success"], "budget": e["budget"], "final_cell_dx": int(tr["x"][-1] // m.CELL_X - gi),
                       "final_cell_dy": int(np.clip(tr["y"][-1], 0, 63) // m.CELL_Y - gj), "min_dg": round(min(e["dg"]), 1),
                       "goal_contact": gc})
        so["S2_T_episodes"] = s2
        # 6. S1 underestimates by goal contact class and height
        nets = m.make_nets(torch, sd.mean, sd.std)
        nets.load_state_dict(torch.load(run / f"s{seed}_T.pt"))
        truth, _ = m.bfs(m.start_state(1))
        goals = [int(c) for c in sd.goal_nodes if int(c) in truth and truth[int(c)] > 0]
        with torch.no_grad():
            z0 = nets.z(torch.from_numpy(m.build_obs(m.initial_record(m.start_state(1)))))
            dd = nets.d(z0, nets.w(torch.from_numpy(m.goal_feats(np.array(goals))))).numpy()
        tv = np.array([truth[c] for c in goals], float)
        under = dd < 0.8 * tv
        cells = [m.code_to_cell(c) for c in goals]
        so["S1_under_by_contact"] = {
            "air": [int(sum(u for u, c in zip(under, cells) if c[2] == m.AIR)), int(sum(c[2] == m.AIR for c in cells))],
            "ground": [int(sum(u for u, c in zip(under, cells) if c[2] != m.AIR)),
                       int(sum(c[2] != m.AIR for c in cells))]}
        so["S1_under_median_ratio"] = float(np.median(dd[under] / tv[under])) if under.any() else None
        # 7. S3: T's distance from the no-jump state against truth
        so["S3_ratio_d_b_over_truth_b"] = sorted(round(p["d_b"] / min(p["truth_b"], m.HORIZON), 3)
                                                for p in sres["S3"]["pairs"])
        so["S3_d_a_over_truth_a"] = sorted(round(p["d_a"] / max(p["truth_a"], 1), 3) for p in sres["S3"]["pairs"])
        # 8. behaviour crossings (explains a missing OFF plant start)
        so["behaviour_left_or_walltop_episodes"] = int(sum(
            any(c is not None and (c[2] == 0 or c[0] * m.CELL_X < m.WALL_X0) for c in cl) for cl in sd.cells))
        # 9. per-goal single-episode reach counts behind K
        E = [m.cell_to_code(tuple(c)) for c in sres["E"]]
        per_ep = [len({m.cell_to_code(c) for c in sd.cells[e][1:] if c is not None} & set(E)) for e in sd.others]
        so["K_distribution_top5"] = sorted(per_ep, reverse=True)[:5]
        so["episodes_reaching_any_E"] = int(sum(v > 0 for v in per_ep))
        out["seeds"][key] = so
        print(f"seed {seed} done", flush=True)
    return out


def memory_supplement(run: Path) -> Dict[str, Any]:
    torch = m.torch_mod()
    out: Dict[str, Any] = {"tool": "m7t_synthetic_posthoc_v1 --memory", "start": mem()}
    t0 = time.perf_counter()
    sd = m.SeedData(0, m.REG["data"]["episodes"], m.HORIZON, m.REG["data"]["phase_a"], m.REG["data"]["held_out"])
    out["after_data"] = mem()
    truth, _ = m.bfs(m.start_state(1))
    out["after_bfs"] = mem()
    torch.manual_seed(m.seed_int("init", 0) % (2 ** 31))
    init = m.make_nets(torch, sd.mean, sd.std)
    st = {k: v.clone() for k, v in init.state_dict().items()}
    timing = {}
    for arm in ("T", "S"):
        log: List[Dict[str, Any]] = []
        nets, info = m.train_arm(torch, arm, sd, st, 1000, 3600, log)
        timing[arm] = {"ms_per_step": 1000 * info["s_per_step"], "cpu_s_per_step": info["cpu_s"] / info["steps_done"]}
        out[f"after_train_{arm}"] = mem()
    rng = np.random.default_rng(m.seed_int("support", 0))
    ref_rows = rng.choice(sd.train_rows, size=50000, replace=False)
    ref = torch.from_numpy(((sd.obs(ref_rows) - sd.mean) / sd.std)[:, m.SUPPORT_COLS])

    def ref_support(ob):
        q = torch.from_numpy(((ob - sd.mean) / sd.std)[:, m.SUPPORT_COLS])
        return torch.cdist(q, ref).min(dim=1).values.numpy()

    goals = [int(c) for c in sd.goal_nodes[:20]]
    te = time.perf_counter()
    m.run_episodes(torch, nets, sd, goals, [m.HORIZON] * len(goals), ref_support)
    out["eval_batch_20_s"] = time.perf_counter() - te
    out["after_eval"] = mem()
    out["timing_1000_steps"] = timing
    out["wall_s"] = time.perf_counter() - t0
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--memory", action="store_true")
    a = ap.parse_args()
    if a.memory:
        rep = memory_supplement(a.run)
        (a.run / "memory_supplement.json").write_text(json.dumps(rep, indent=1, default=float), encoding="utf-8")
    else:
        rep = posthoc(a.run)
        (a.run / "posthoc.json").write_text(json.dumps(rep, indent=1, default=float), encoding="utf-8")
    print(json.dumps(rep, indent=1, default=float)[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
