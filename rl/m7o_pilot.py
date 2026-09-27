#!/usr/bin/env python3
"""M7o pilot: ONE capped, registered training run of the exploration credit (v3 + reward v2 + btt_explore_cells_v1),
go / no-go for the three-seed comparison. Its model is never reused.

    python rl/m7o_pilot.py register     # freezes the cap, the checks and the identities (write-once) BEFORE any launch
    python rl/m7o_pilot.py run          # the pilot (rl/configs/m7o/pilot/m7o_pilot_s0.toml), then the checks
    python rl/m7o_pilot.py status

Frozen: cap 307,200 policy transitions (60 rollouts of 5,120, 600 PPO updates), checkpoints ckpt_000000000 /
ckpt_000102400 / ckpt_000204800 / final, then a tick-0 evaluation of the final set: 60 stochastic + 5 deterministic
episodes (the M7n curve-point protocol, seed 12345, metrics on). Checks (all engineering; the target comparison is a
regression diagnostic with sampling uncertainty, never proof of benefit):

    P1  trainer exit 0 under the M7h guard, no stop, no leftover game process
    P2  accounting: sb3_num_timesteps == 307,200, n_updates == 600, the four checkpoint sets, VecNormalize statistics-free
    P3  ckpt_000000000 == the fresh construction of the profile (policy + VecNormalize digests) == m7n_s0_v3's initial set
    P4  every training row validates (btt_reward_v2 closed form on `return`; the explore record consistent; m7d validators)
    P5  parameters changed and finite
    P6  contracts: v3 observation digest, action-class table, both diagnostic flags, exploration_contract recorded
    P7  resources: <= 10 game processes, no hard alert
    P8  exploration accounting: every episode bonus <= 1.0 and >= 0; ground + air == bonus; learner_return == return + bonus;
        the per-slot tables exist for the 5 slots, episode counts sum to the row count, every checkpoint set from 102,400 on
        carries the table copies; a slot's table episodes never decrease across sets
    P9  decay: mean bonus of the last 25 % of episodes per slot < 30 % of the first 25 % (pooled over slots); at least one
        episode with voided > 0 or capped > 0 is not required (reported)
    P10 evaluation of the final set from tick 0 (60 + 5, metrics on) verifies (tick-0 starts, counts, metrics, no leak)
    R   regression diagnostic, stop-only: the 60 stochastic episodes' mean targets must not be below the M7n seed-0
        curve point at 307,200 (3.5667 over 60) by more than 0.5; not a benefit claim in either direction

Any failed check = no-go: stop and report; no extension, no retune, no second pilot seed. An inconclusive regression
diagnostic (within the band) passes the gate on the engineering checks alone.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import btt_explore_cells as xp  # noqa: E402
import experiment_config as ec  # noqa: E402
import m7d_run as dr  # noqa: E402
import m7h_guard as g  # noqa: E402
import m7n_obs as mn  # noqa: E402
import m7n_status_table as st  # noqa: E402

REPO_ROOT = RL_DIR.parent
PROFILE = REPO_ROOT / "rl" / "configs" / "m7o" / "pilot" / "m7o_pilot_s0.toml"
ROOT = REPO_ROOT / "runs" / "m7o" / "pilot"
REGISTRATION = REPO_ROOT / "docs" / "rl_exploration_credit_m7o_pilot_registration.json"
REPORT = ROOT / "pilot_report.json"
M7N_S0 = REPO_ROOT / "runs" / "m7n" / "campaign" / "m7n_s0_v3"
M7N_S0_CURVE = REPO_ROOT / "runs" / "m7n" / "campaign" / "_eval" / "m7n_s0_v3" / "curve_t000307200" / "stochastic" / "evaluation.json"
CAP = 307_200
EXPECTED_N_UPDATES = 600
CHECKPOINTS = ["ckpt_000000000", "ckpt_000102400", "ckpt_000204800", "final"]
EVAL = {"stochastic": 60, "deterministic": 5}
MAX_PROCESSES = 10
REGRESSION_BAND = 0.5
DECAY_RATIO_MAX = 0.30


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def log(msg: str) -> None:
    print(f"[m7o_pilot {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def identity() -> Dict[str, Any]:
    import m7n_pilot as npi
    import m7o_control_check as cc

    exp = ec.load_experiment(PROFILE)
    v = exp.values
    pol, rms = npi.fresh_digests(exp)
    curve = json.loads(M7N_S0_CURVE.read_text(encoding="utf-8"))
    eps = curve.get("episodes") or []
    return {"profile": ec.repo_relative(PROFILE), "profile_sha256": exp.source.sha256, "semantic_fingerprint": exp.semantic_fingerprint,
            "compatibility_fingerprint": exp.compatibility_fingerprint, "run_name": exp.name,
            "total_transitions": int(v["run.total_transitions"]), "base_seed": int(v["run.base_seed"]),
            "observation": v["contracts.observation"], "observation_digest": mn.contract_digest(),
            "action_class_table_sha256": st.load_table()["sha256"], "reward": exp.reward.contract, "exploration": exp.exploration,
            "exploration_contract": xp.contract_description(), "native_flags": dict(exp.extra_env),
            "executable_sha256": sha256_file(exp.executable), "code": cc.code_fingerprint(),
            "expected_initial_policy_digest": pol, "expected_initial_obs_rms_digest": rms,
            "m7n_s0_initial_digests": list(dr.checkpoint_digests(M7N_S0 / "checkpoints" / "ckpt_000000000")),
            "m7n_s0_curve_307200": {"path": ec.repo_relative(M7N_S0_CURVE), "sha256": sha256_file(M7N_S0_CURVE), "episodes": len(eps),
                                    "mean_targets": round(sum(e["targets_broken"] for e in eps) / len(eps), 4) if eps else None},
            "revisions": dr.git_revisions() if hasattr(dr, "git_revisions") else None}


def cmd_register(_: argparse.Namespace) -> int:
    if REGISTRATION.is_file():
        log(f"registration exists and is frozen: {ec.repo_relative(REGISTRATION)}")
        return 1
    reg = {"schema": "m7o_pilot_registration_v1", "utc": utc_now(), "purpose": "go / no-go for the M7o comparison; the pilot's "
           "model, optimizer state and tables are never reused", "cap_transitions": CAP, "expected_n_updates": EXPECTED_N_UPDATES,
           "checkpoints": CHECKPOINTS, "evaluation": EVAL, "max_processes": MAX_PROCESSES, "regression_band": REGRESSION_BAND,
           "decay_ratio_max": DECAY_RATIO_MAX, "checks": [l.strip() for l in __doc__.splitlines() if l.strip()[:3] in
                                                          ("P1 ", "P2 ", "P3 ", "P4 ", "P5 ", "P6 ", "P7 ", "P8 ", "P9 ", "P10", "R  ")],
           "on_failure": "no-go: stop and report; no extension, no retune, no second pilot seed",
           "on_inconclusive_regression": "passes on the engineering checks; the diagnostic is reported with its sampling uncertainty",
           "identity": identity()}
    REGISTRATION.write_text(json.dumps(reg, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    log(f"registered -> {ec.repo_relative(REGISTRATION)} (code {reg['identity']['code']['sha256'][:12]})")
    return 0


def _registration_drift(reg: Dict[str, Any]) -> List[str]:
    now = identity()
    p = []
    for k in ("profile_sha256", "semantic_fingerprint", "observation_digest", "action_class_table_sha256", "executable_sha256",
              "expected_initial_policy_digest", "expected_initial_obs_rms_digest", "exploration", "m7n_s0_initial_digests"):
        if now.get(k) != reg["identity"].get(k):
            p.append(f"{k} changed since the registration")
    if now["code"]["sha256"] != reg["identity"]["code"]["sha256"]:
        p.append(f"code fingerprint {now['code']['sha256'][:12]} != registered {reg['identity']['code']['sha256'][:12]}")
    if now["m7n_s0_curve_307200"]["sha256"] != reg["identity"]["m7n_s0_curve_307200"]["sha256"]:
        p.append("the M7n reference curve file changed")
    return p


def _policy_digest(ckpt: Path) -> str:
    return dr.checkpoint_digests(ckpt)[0]


def _artifact_first_ticks(eval_dir: Path) -> List[Optional[int]]:
    out = []
    for f in sorted(eval_dir.glob("*/workers/*/artifacts/*/actions.jsonl")):
        first = f.read_text(encoding="utf-8").splitlines()[:1]
        out.append(json.loads(first[0]).get("consumed_tick") if first else None)
    return out


def _write(report: Dict[str, Any]) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")


def cmd_run(_: argparse.Namespace) -> int:
    import m7_evaluation as ev
    import m7_trainer as tr
    from m7_runtime import install_kill_on_close_job, list_processes_named

    if not REGISTRATION.is_file():
        log("no registration: run `register` first")
        return 1
    reg = json.loads(REGISTRATION.read_text(encoding="utf-8"))
    drift = _registration_drift(reg)
    if drift:
        for d in drift:
            log(f"BLOCKED {d}")
        return 1
    exp = ec.load_experiment(PROFILE)
    run_dir = ROOT / exp.name
    if run_dir.exists() or REPORT.is_file():
        log("a pilot report or run directory exists: a completed pilot is never relaunched; a failed attempt must be preserved "
            "(report renamed pilot_report_attempt<n>.json, run under _partial) before a re-registered attempt runs")
        return 1
    if list_processes_named():
        log("BattleShip already running; refusing to start")
        return 2
    install_kill_on_close_job()
    report: Dict[str, Any] = {"schema": "m7o_pilot_report_v1", "registration_sha256": sha256_file(REGISTRATION),
                              "started_utc": utc_now(), "checks": {}, "problems": []}
    gate = g.launch_gate()
    report["launch_gate"] = gate
    if not gate["ok"]:
        log(f"launch gate refused {gate['problems']}")
        report["status"] = "gate_refused"
        _write(report)
        return 2
    tag = f"{exp.name}__{stamp()}"
    guard = ROOT / "_guard"
    t0 = time.perf_counter()
    res = g.train_guarded(config=PROFILE, run_dir=run_dir, log_path=guard / "logs" / f"{tag}.log",
                          monitor_path=guard / "monitor" / f"{tag}.jsonl", probe_path=guard / "probe" / f"{tag}.jsonl",
                          contract=exp.reward, horizon=int(exp.values["environment.horizon"]), partial_root=ROOT / "_partial")
    mon = res.get("monitor") or {}
    report["training"] = {k: res.get(k) for k in ("exit_code", "stop_kind", "moved_to", "wall_s", "commit_drawn_gib",
                                                  "leftover_battleship_pids", "log", "monitor_log", "probe")}
    report["training"]["monitor"] = {k: mon.get(k) for k in (
        "max_battleship_processes", "max_battleship_listeners", "hard_alerts", "soft_alert_count", "episodes_seen", "episode_ends",
        "lifecycle_failures", "max_commit_used_gib", "min_avail_commit_gib", "min_avail_phys_gib", "samples")}
    report["training"]["wall_total_s"] = round(time.perf_counter() - t0, 1)
    checks, problems = report["checks"], report["problems"]
    checks["P1_exit_clean"] = {"exit_code": res.get("exit_code"), "stop_kind": res.get("stop_kind"), "leftover": res.get("leftover_battleship_pids")}
    if res.get("exit_code") != 0 or res.get("stop_kind") or res.get("leftover_battleship_pids"):
        problems.append(f"P1: {checks['P1_exit_clean']}")
        report["status"] = "failed"
        _write(report)
        return 1
    expected = (reg["identity"]["expected_initial_policy_digest"], reg["identity"]["expected_initial_obs_rms_digest"])
    ver = dr.verify_training_run(run_dir, exp, fresh=True, expected_initial=expected)
    checks["verification"] = {"ok": ver["ok"], "problems": ver["problems"][:20]}
    if not ver["ok"]:
        problems.append(f"verification: {ver['problems'][:3]}")
    summ = json.loads((run_dir / "training_summary.json").read_text(encoding="utf-8"))
    rj = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    sets = ver["checks"]["checkpoint_sets"]
    n_updates = (sets.get("final") or {}).get("n_updates")
    steps = (summ.get("timesteps") or {}).get("sb3_num_timesteps")
    checks["P2_accounting"] = {"sb3_num_timesteps": steps, "n_updates": n_updates, "sets": sorted(sets),
                               "user_config": summ.get("user_config"), "leak_free": (summ.get("cleanup") or {}).get("leak_free")}
    if steps != CAP or n_updates != EXPECTED_N_UPDATES or sorted(sets) != sorted(CHECKPOINTS):
        problems.append(f"P2: {checks['P2_accounting']}")
    for name, entry in sets.items():
        vn = entry["vecnormalize"]
        if vn.get("norm_obs") or vn.get("norm_reward") or vn.get("obs_rms_counts"):
            problems.append(f"P2: {name} VecNormalize {vn}")
    init = list(dr.checkpoint_digests(run_dir / "checkpoints" / "ckpt_000000000"))
    checks["P3_fresh_initial"] = {"fresh": (ver["checks"].get("initial_policy") or {}).get("matches_fresh_construction"),
                                  "equals_m7n_s0_initial": init == reg["identity"]["m7n_s0_initial_digests"]}
    if not (checks["P3_fresh_initial"]["fresh"] and checks["P3_fresh_initial"]["equals_m7n_s0_initial"]):
        problems.append(f"P3: {checks['P3_fresh_initial']}")
    eps = ver["checks"]["episodes"]
    checks["P4_rows_valid"] = {"rows": eps["rows"], "row_problem_count": eps["row_problem_count"], "end_reasons": eps["end_reasons"]}
    if eps["rows"] < 1 or eps["row_problem_count"]:
        problems.append(f"P4: {checks['P4_rows_valid']}")
    import numpy as np
    from m7_trainer import M7PPO

    d0, d1 = _policy_digest(run_dir / "checkpoints" / "ckpt_000000000"), _policy_digest(run_dir / "final")
    model = M7PPO.load(str(run_dir / "final" / "model.zip"), device="cpu")
    finite = all(np.isfinite(p.detach().cpu().numpy()).all() for p in model.policy.parameters())
    checks["P5_updates_happened"] = {"changed": d0 != d1, "finite": finite}
    if d0 == d1 or not finite:
        problems.append("P5: parameters unchanged or not finite")
    meta = json.loads((run_dir / "final" / "checkpoint.json").read_text(encoding="utf-8"))
    c = meta.get("contracts") or {}
    flags = dict(rj.get("m6_flags") or {})
    checks["P6_contracts"] = {"observation": c.get("policy_observation_contract"),
                              "digest_ok": c.get("policy_observation_contract_sha256") == mn.contract_digest(),
                              "table_ok": c.get("action_class_table_sha256") == st.load_table()["sha256"],
                              "flags_ok": all(flags.get(k) == v for k, v in mn.ENTITY_EXTRA_ENV),
                              "exploration_contract": c.get("exploration_contract"), "exploration_settings": c.get("exploration_settings")}
    if c.get("policy_observation_contract") != mn.OBS_CONTRACT or not checks["P6_contracts"]["digest_ok"] or not checks["P6_contracts"]["table_ok"] \
            or not checks["P6_contracts"]["flags_ok"] or c.get("exploration_contract") != xp.CONTRACT_ID \
            or c.get("exploration_settings") != exp.exploration:
        problems.append(f"P6: {checks['P6_contracts']}")
    checks["P7_resources"] = report["training"]["monitor"] | {"commit_drawn_gib": res.get("commit_drawn_gib")}
    if (mon.get("max_battleship_processes") or 0) > MAX_PROCESSES or mon.get("hard_alerts"):
        problems.append(f"P7: {checks['P7_resources']}")
    # -- P8 / P9: exploration accounting and decay -----------------------------------------------------------------
    rows, _ = dr.jsonl_rows(run_dir / "metrics" / "episodes.jsonl")
    xr = [(r, r.get("explore") or {}) for r in rows]
    p8: List[str] = []
    if any(not x for _, x in xr):
        p8.append(f"{sum(1 for _, x in xr if not x)} rows without an explore record")
    for r, x in xr:
        b = float(x.get("bonus", -1))
        if not (0.0 <= b <= xp.CAP + 1e-9) or abs(float(x.get("banked_ground", 0)) + float(x.get("banked_air", 0)) - b) > 1e-5:
            p8.append(f"rank {r['rank']} ep {r['worker_episode']}: bonus {b}")
        if abs(float(x.get("learner_return", 0)) - (float(r["return"]) + b)) > 1e-5:
            p8.append(f"rank {r['rank']} ep {r['worker_episode']}: learner_return")
    tables = {}
    for rank in range(5):
        tp = run_dir / "workers" / f"w{rank:02d}" / "explore_table.json"
        if tp.is_file():
            t = xp.ExploreTable.load(tp)
            tables[rank] = {"episodes": t.episodes, "cells": len(t.counts)}
        else:
            p8.append(f"no table for slot {rank}")
    if sum(v["episodes"] for v in tables.values()) != len(rows):
        p8.append(f"table episodes {sum(v['episodes'] for v in tables.values())} != rows {len(rows)}")
    set_tables = {}
    prev = {}
    for name in ("ckpt_000102400", "ckpt_000204800", "final"):
        d = run_dir / ("final" if name == "final" else f"checkpoints/{name}")
        eps_by_rank = {}
        for rank in range(5):
            f = d / f"explore_table_w{rank:02d}.json"
            if f.is_file():
                eps_by_rank[rank] = xp.ExploreTable.load(f).episodes
        set_tables[name] = eps_by_rank
        if len(eps_by_rank) != 5:
            p8.append(f"{name}: {len(eps_by_rank)} table copies")
        if any(eps_by_rank.get(k, 0) < prev.get(k, 0) for k in prev):
            p8.append(f"{name}: a slot's table episodes decreased")
        prev = eps_by_rank
    checks["P8_exploration_accounting"] = {"rows": len(rows), "tables": tables, "set_tables": set_tables, "problems": p8[:10],
                                          "bonus_total": round(sum(float(x.get("bonus", 0)) for _, x in xr), 4),
                                          "voided_total": round(sum(float(x.get("voided", 0)) for _, x in xr), 4),
                                          "capped_total": round(sum(float(x.get("capped", 0)) for _, x in xr), 4),
                                          "cap_hits": sum(1 for _, x in xr if x.get("cap_hit")),
                                          "contract_return_total": round(sum(float(r["return"]) for r in rows), 4)}
    if p8:
        problems.append(f"P8: {p8[:3]}")
    by_rank: Dict[int, List[float]] = {}
    for r, x in sorted(xr, key=lambda rx: (int(rx[0]["rank"]), int(rx[0]["worker_episode"]))):
        by_rank.setdefault(int(r["rank"]), []).append(float(x.get("bonus", 0)))
    first, last = [], []
    for seq in by_rank.values():
        q = max(1, len(seq) // 4)
        first += seq[:q]
        last += seq[-q:]
    ratio = (sum(last) / len(last)) / (sum(first) / len(first)) if first and sum(first) > 0 else None
    checks["P9_decay"] = {"first_quarter_mean": round(sum(first) / len(first), 4) if first else None,
                          "last_quarter_mean": round(sum(last) / len(last), 4) if last else None, "ratio": None if ratio is None else round(ratio, 4),
                          "per_rank_episodes": {k: len(v) for k, v in by_rank.items()}}
    if ratio is None or ratio >= DECAY_RATIO_MAX:
        problems.append(f"P9: decay ratio {ratio}")
    # -- P10: evaluation of the final set ---------------------------------------------------------------------------
    from dataclasses import replace

    import m7h_verify as mv

    settings = replace(dr.evaluation_settings(exp), eval_metrics=True, observation=None)
    cfg = tr.config_from_experiment(exp)
    out = ROOT / "_eval" / exp.name / "final"
    t1 = time.perf_counter()
    result = ev.evaluate_checkpoint(run_dir / "final", out, settings=settings, deterministic_episodes=EVAL["deterministic"],
                                    stochastic_episodes=EVAL["stochastic"], expected_contracts=tr.run_contracts(cfg), label="final",
                                    preserve_all=True)
    plan = {"deterministic_episodes": EVAL["deterministic"], "stochastic_episodes": EVAL["stochastic"]}
    vev = dr.verify_evaluation(result, exp.reward, int(exp.values["environment.horizon"]), plan)
    t0c = mv.verify_eval_tick0(out)
    ticks = _artifact_first_ticks(out)
    sto = result["modes"]["stochastic"]["episodes"]
    det = result["modes"]["deterministic"]["episodes"]
    checks["P10_evaluation"] = {"ok": vev["ok"] and t0c["ok"], "problems": (vev["problems"] + t0c["problems"])[:10],
                                "first_consumed_ticks_all_zero": all(t == 0 for t in ticks), "wall_s": round(time.perf_counter() - t1, 1),
                                "leftover": list_processes_named(), "stochastic_episodes": len(sto), "deterministic_episodes": len(det)}
    if not checks["P10_evaluation"]["ok"] or not checks["P10_evaluation"]["first_consumed_ticks_all_zero"] or list_processes_named() \
            or len(sto) != EVAL["stochastic"] or len(det) != EVAL["deterministic"]:
        problems.append(f"P10: {checks['P10_evaluation']['problems'][:3]}")
    mean_t = sum(e["targets_broken"] for e in sto) / len(sto) if sto else None
    ref = reg["identity"]["m7n_s0_curve_307200"]["mean_targets"]
    sd = (sum((e["targets_broken"] - mean_t) ** 2 for e in sto) / max(1, len(sto) - 1)) ** 0.5 if sto else None
    checks["R_regression_diagnostic"] = {"pilot_mean_targets_60": None if mean_t is None else round(mean_t, 4), "m7n_s0_curve_307200_mean": ref,
                                         "difference": None if mean_t is None else round(mean_t - ref, 4), "band": REGRESSION_BAND,
                                         "pilot_sd": None if sd is None else round(sd, 3),
                                         "standard_error_of_difference_approx": None if sd is None else round(sd * (2 / 60) ** 0.5, 3),
                                         "falls": sum(1 for e in sto if e["end_reason"] == "fall"), "clears": sum(1 for e in sto if e.get("cleared")),
                                         "deterministic_targets": sorted({e["targets_broken"] for e in det}),
                                         "left_entries": sum(1 for e in sto if (e.get("eval_metrics") or {}).get("first_left_entry")),
                                         "note": "stop-only regression diagnostic with sampling uncertainty; never a benefit claim"}
    if mean_t is not None and mean_t < ref - REGRESSION_BAND:
        problems.append(f"R: pilot mean targets {mean_t:.3f} below the M7n curve point {ref} by more than {REGRESSION_BAND}")
    rows_tr = rows
    report["descriptive_not_a_check"] = {"training_episodes": len(rows_tr),
                                         "mean_targets": round(float(np.mean([r["targets_broken"] for r in rows_tr])), 3) if rows_tr else None,
                                         "falls": sum(1 for r in rows_tr if r["end_reason"] == "fall"),
                                         "throughput": summ.get("throughput"), "wall": summ.get("wall"),
                                         "bonus_curve_by_rank": {k: [round(b, 3) for b in v] for k, v in by_rank.items()}}
    report["finished_utc"] = utc_now()
    report["status"] = "passed" if not problems else "failed"
    report["ok"] = not problems
    _write(report)
    log(f"pilot {'GO (passed)' if report['ok'] else 'NO-GO (failed)'}: {problems[:3]}")
    return 0 if report["ok"] else 1


def cmd_status(_: argparse.Namespace) -> int:
    print(json.dumps({"registration": REGISTRATION.is_file(), "report": json.loads(REPORT.read_text(encoding="utf-8")).get("status")
                      if REPORT.is_file() else None}, indent=1))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["register", "run", "status"])
    args = ap.parse_args(argv)
    return {"register": cmd_register, "run": cmd_run, "status": cmd_status}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
