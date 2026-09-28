#!/usr/bin/env python3
"""M7p: the single bounded geometry-scaling diagnostic (registered, run once, analysed once).

One fresh seed-0 run of rl/configs/m7p/m7p_geo4_s0.toml (btt_policy_obs_v3_geo4 = v3 with ONLY the segment_geometry
block scaled by 1/4; reward v2, Track 1, PPO, network, N = 5 standby, tick-0 starts unchanged), capped at 307,200
transitions, against the M7n seed-0 run at the same transition count (ckpt_000307200 and its 60-episode curve label).

    python rl/m7p_geo4_diag.py register        # write-once registration (contract, control identity, plan, criteria)
    python rl/m7p_geo4_diag.py control-check   # fresh 102,400-transition reproduction of the M7n s0 profile on this code
    python rl/m7p_geo4_diag.py run             # guarded training + engineering checks + 60 + 5 tick-0 evaluation
    python rl/m7p_geo4_diag.py analyze         # paired measurements under each arm's own contract + the frozen decision

Observations for the paired measurements are rebuilt from the registered raw-reply sources under EACH checkpoint's own
contract (v3 for the control, geo4 for the experimental arm); nothing scaled is ever fed to the other arm's network.
A failed attempt is preserved (report + run under _partial); nothing is fixed and relaunched automatically.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import experiment_config as ec  # noqa: E402
import m7d_run as dr  # noqa: E402
import m7h_guard as g  # noqa: E402
import m7n_obs as mn  # noqa: E402
import m7n_status_table as st  # noqa: E402
import m7p_obs_geo4 as mg  # noqa: E402

REPO_ROOT = RL_DIR.parent
PROFILE = REPO_ROOT / "rl" / "configs" / "m7p" / "m7p_geo4_s0.toml"
CONTROL_PROFILE = REPO_ROOT / "rl" / "configs" / "m7o" / "r1" / "m7o_r1_s0.toml"   # = the M7n s0 v3 profile at 102,400
ROOT = REPO_ROOT / "runs" / "m7p" / "diag"
REG = REPO_ROOT / "docs" / "rl_geometry_scale_diag_registration.json"
DECISION = REPO_ROOT / "docs" / "rl_geometry_scale_diag_decision.json"
REPORT = ROOT / "diag_report.json"
ANALYSIS = ROOT / "analysis.json"
M7N_S0 = REPO_ROOT / "runs" / "m7n" / "campaign" / "m7n_s0_v3"
M7N_S0_CURVE = REPO_ROOT / "runs" / "m7n" / "campaign" / "_eval" / "m7n_s0_v3" / "curve_t000307200" / "stochastic" / "evaluation.json"
CAP = 307_200
EXPECTED_N_UPDATES = 600
CHECKPOINTS = ["ckpt_000000000", "ckpt_000102400", "ckpt_000204800", "final"]
CONTROL_CHECKPOINTS = {"ckpt_000000000": "checkpoints/ckpt_000000000", "ckpt_000102400": "checkpoints/ckpt_000102400",
                       "ckpt_000204800": "checkpoints/ckpt_000204800", "final": "checkpoints/ckpt_000307200"}
EVAL = {"stochastic": 60, "deterministic": 5}
MAX_PROCESSES = 10
SAMPLE_SOURCES = [REPO_ROOT / "runs" / "m7n" / "feasibility" / "prefix" / "traces" / "907d762b.json.gz",
                  REPO_ROOT / "runs" / "m7n" / "feasibility" / "prefix" / "traces" / "e404fde0.json.gz"] + \
                 [REPO_ROOT / "runs" / "probes" / "action_hold" / "episodes" / "k01" / f"ep{i:03d}.json.gz" for i in range(8)]
CRITERIA = {
    "regression_band_targets": 0.5,
    "saturation_reduction_actor": 0.15, "saturation_reduction_critic": 0.10,
    "discrimination_retention_ratio": 0.5,
    "optimization_last_updates": 20, "clip_fraction_max": 0.20, "explained_variance_min": 0.50, "approx_kl_max": 0.03,
}
PLAN = {
    "sample": "33,997 states rebuilt from the registered raw-reply sources (population A: the two M7n final-episode traces, "
              "policy play; population B: eight action-hold-probe k = 1 episodes, random play), under EACH arm's own contract",
    "checkpoints": "0, 102,400, 204,800 and 307,200 transitions of both arms (control = M7n s0 checkpoints)",
    "1_saturation": "actor and critic layer 1 (and 2): sat95 (abs tanh > 0.95), sat99, mean derivative 1 - h^2, share of units "
                    "saturated in > 90 % of states, of which stuck at one sign, two-sided, effectively constant (std < 0.05); "
                    "reported for the whole sample and separately for populations A and B",
    "2_sensitivity": "recorded physically valid pairs, identical indices in both arms: (a) target events = the 43 consecutive-tick "
                     "pairs across a target break vs 3,000 sampled consecutive no-break pairs (median abs dV, median KL, hidden "
                     "distances); (b) action progress = up-B early (tics 5-10) vs late (20-30) pairs within 150 units (587) vs "
                     "early-vs-early controls (800), and jump-squat tic 0 vs 2 at the same place (140) vs tic 0 vs 0 (174); "
                     "(c) block ablation KL (agent block zeroed; targets block zeroed; zero = the contracts' own absent value)",
    "3_optimization": "per-update SB3 train/* statistics of the 60 updates (approx_kl, clip_fraction, value_loss, explained_variance, "
                      "entropy) for both arms; gradient measurement available for both = first-layer weight-row change per "
                      "102,400-transition interval from the saved checkpoints; UNAVAILABLE for both = true gradient norms and "
                      "per-parameter update sizes (SB3 does not log them; the historical control cannot be re-instrumented)",
    "4_regression": "60 stochastic tick-0 episodes of the final set at evaluation seed 12345 with btt_eval_metrics_v1 vs the M7n s0 "
                    "60-episode curve label at 307,200 (3.5667 targets); stop-only band 0.5 targets; falls, clears, left entries "
                    "and 5 deterministic episodes reported",
    "5_outcomes": {
        "engineering_failure": "any E check fails (exit, accounting, fresh construction, rows, parameters, contracts, resources, "
                               "evaluation integrity): stop and report; nothing relaunched",
        "regression": "gameplay: 60-episode mean targets < control - 0.5; or optimization: over the last 20 updates mean "
                      "clip_fraction > 0.20 or mean explained_variance < 0.50 or mean approx_kl > 0.03 or any non-finite loss",
        "discrimination_lost": "no regression, but at 307,200 any of: break-pair median abs dV, break-pair median KL, up-B progress "
                               "median KL, agent-block ablation KL, targets-block ablation KL falls below 0.5 x the control's value, "
                               "or up-B progress KL is not above the up-B control-pair KL",
        "diagnostic_pass": "no regression, discrimination preserved, AND saturation reduced: actor L1 sat95 <= control - 0.15 AND "
                           "critic L1 sat95 <= control - 0.10 on the whole sample at 307,200",
        "inconclusive": "no regression and discrimination preserved but saturation not reduced by the registered margins",
    },
    "never": ["a pass read as improved crossing or clear performance", "a second seed, a rescaled factor, a longer budget or a "
              "relaunch decided from these results", "scaled observations fed to the control network"],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def log(msg: str) -> None:
    print(f"[m7p_diag {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(p: Path, d: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")


def code_fingerprint() -> Dict[str, Any]:
    import m7o_control_check as cc

    base = cc.code_fingerprint()
    h = hashlib.sha256(base["sha256"].encode())
    files = sorted((RL_DIR / "configs" / "m7p").rglob("*.toml"))
    for f in files:
        h.update(f.relative_to(REPO_ROOT).as_posix().encode("utf-8"))
        h.update(f.read_bytes())
    return {"sha256": h.hexdigest(), "files": base["files"] + len(files), "m7o_control_check_fingerprint": base["sha256"]}


def identity() -> Dict[str, Any]:
    import m7n_pilot as npi

    exp = ec.load_experiment(PROFILE)
    m7n = ec.load_experiment(REPO_ROOT / "rl" / "configs" / "m7n" / "m7n_s0_v3.toml")
    pol, rms = npi.fresh_digests(exp)
    curve = json.loads(M7N_S0_CURVE.read_text(encoding="utf-8"))
    eps = curve.get("episodes") or []
    return {
        "profile": ec.repo_relative(PROFILE), "profile_sha256": exp.source.sha256, "semantic_fingerprint": exp.semantic_fingerprint,
        "compatibility_fingerprint": exp.compatibility_fingerprint, "run_name": exp.name,
        "compatibility_differences_vs_m7n_s0_v3": sorted(ec.compare_compatibility(exp.compatibility_view(), m7n.compatibility_view())),
        "total_transitions": int(exp.values["run.total_transitions"]), "base_seed": int(exp.values["run.base_seed"]),
        "observation": exp.values["contracts.observation"], "observation_digest": mg.contract_digest(),
        "observation_contract": mg.contract_description(), "v3_digest": mn.contract_digest(),
        "action_class_table_sha256": st.load_table()["sha256"], "reward": exp.reward.contract, "native_flags": dict(exp.extra_env),
        "executable_sha256": sha256_file(exp.executable), "code": code_fingerprint(),
        "expected_initial_policy_digest": pol, "expected_initial_obs_rms_digest": rms,
        "control": {"run": ec.repo_relative(M7N_S0),
                    "initial_digests": list(dr.checkpoint_digests(M7N_S0 / "checkpoints" / "ckpt_000000000")),
                    "ckpt_000307200_digests": list(dr.checkpoint_digests(M7N_S0 / "checkpoints" / "ckpt_000307200")),
                    "rollouts_sha256": sha256_file(M7N_S0 / "metrics" / "rollouts.jsonl"),
                    "curve_307200": {"path": ec.repo_relative(M7N_S0_CURVE), "sha256": sha256_file(M7N_S0_CURVE), "episodes": len(eps),
                                     "mean_targets": round(sum(e["targets_broken"] for e in eps) / len(eps), 4) if eps else None},
                    "control_check_profile": ec.repo_relative(CONTROL_PROFILE)},
        "sample_sources": [{"path": ec.repo_relative(p), "sha256": sha256_file(p)} for p in SAMPLE_SOURCES],
    }


def cmd_register(_: argparse.Namespace) -> int:
    if REG.is_file():
        log(f"registration exists and is frozen: {ec.repo_relative(REG)}")
        return 1
    reg = {"schema": "m7p_geo4_diag_registration_v1", "utc": utc_now(),
           "purpose": "one bounded diagnostic of a single geometry-scaling change; never a campaign; the run's model is never reused",
           "only_change": {"key": mg.CHANGED_KEY, "length_columns": list(mg.CHANGED_LENGTH_COLUMNS),
                           "length_scale": f"{mn.LENGTH_SCALE:g} -> {mg.SEGMENT_LENGTH_SCALE:g}",
                           "velocity_columns": list(mg.CHANGED_VELOCITY_COLUMNS),
                           "velocity_scale": f"{mn.VELOCITY_SCALE:g} -> {mg.SEGMENT_VELOCITY_SCALE:g}", "factor": mg.GEOMETRY_SCALE_FACTOR,
                           "unchanged": "segment_kind flags (present / floor / ceiling / walls / one-way / moving), agent (positions, "
                                        "floor_dist, diamond / 2,000; velocities / 50), targets, projectiles, action_class, masking, "
                                        "key order, shapes, stale and displacement rules, native flags, network, PPO, reward v2, Track 1"},
           "cap_transitions": CAP, "expected_n_updates": EXPECTED_N_UPDATES, "checkpoints": CHECKPOINTS,
           "control_checkpoints": CONTROL_CHECKPOINTS, "evaluation": EVAL, "max_processes": MAX_PROCESSES,
           "criteria": CRITERIA, "plan": PLAN, "identity": identity(),
           "control_reuse_rule": "the M7n s0 profile must reproduce bit-exactly for 102,400 transitions on this code and executable "
                                 "(control-check); a mismatch stops the diagnostic; no replacement control is trained",
           "on_failure": "stop and report; the attempt is preserved; no automatic fix and relaunch"}
    write_json(REG, reg)
    log(f"registered -> {ec.repo_relative(REG)} (code {reg['identity']['code']['sha256'][:12]}, geo4 digest {mg.contract_digest()[:12]})")
    return 0


def _drift(reg: Dict[str, Any]) -> List[str]:
    now = identity()
    p = []
    for k in ("profile_sha256", "semantic_fingerprint", "observation_digest", "v3_digest", "action_class_table_sha256",
              "executable_sha256", "expected_initial_policy_digest", "expected_initial_obs_rms_digest", "sample_sources"):
        if now.get(k) != reg["identity"].get(k):
            p.append(f"{k} changed since the registration")
    if now["code"]["sha256"] != reg["identity"]["code"]["sha256"]:
        p.append(f"code fingerprint {now['code']['sha256'][:12]} != registered {reg['identity']['code']['sha256'][:12]}")
    for k in ("initial_digests", "ckpt_000307200_digests", "rollouts_sha256"):
        if now["control"][k] != reg["identity"]["control"][k]:
            p.append(f"control {k} changed")
    if now["control"]["curve_307200"]["sha256"] != reg["identity"]["control"]["curve_307200"]["sha256"]:
        p.append("the control curve label changed")
    return p


def cmd_control_check(_: argparse.Namespace) -> int:
    import m7o_control_check as cc
    from m7_runtime import install_kill_on_close_job, list_processes_named

    reg = json.loads(REG.read_text(encoding="utf-8"))
    drift = _drift(reg)
    if drift:
        for d in drift:
            log(f"BLOCKED {d}")
        return 1
    if list_processes_named():
        log("BattleShip already running; refusing to start")
        return 2
    install_kill_on_close_job()
    gate = g.launch_gate()
    if not gate["ok"]:
        log(f"launch gate refused {gate['problems']}")
        return 2
    exp = ec.load_experiment(CONTROL_PROFILE)
    out = ROOT / "_control" / stamp()
    run_dir = out / exp.name
    t0 = time.perf_counter()
    res = g.train_guarded(config=CONTROL_PROFILE, run_dir=run_dir, log_path=out / "_guard" / "logs" / f"{exp.name}.log",
                          monitor_path=out / "_guard" / "monitor" / f"{exp.name}.jsonl", probe_path=out / "_guard" / "probe" / f"{exp.name}.jsonl",
                          contract=exp.reward, horizon=int(exp.values["environment.horizon"]), partial_root=out / "_partial", output_root=out)
    rec: Dict[str, Any] = {"schema": "m7p_control_check_v1", "utc": utc_now(), "registration_sha256": sha256_file(REG),
                           "code": code_fingerprint(), "out": ec.repo_relative(out), "launch_gate": gate,
                           "training": {k: res.get(k) for k in ("exit_code", "stop_kind", "wall_s", "leftover_battleship_pids")}}
    if res.get("exit_code") != 0 or res.get("stop_kind") or res.get("leftover_battleship_pids"):
        rec.update(ok=False, problems=[f"control training did not complete cleanly: {rec['training']}"])
    else:
        ver = dr.verify_training_run(run_dir, exp, fresh=True)
        cmp = cc.compare(0, run_dir)
        rec.update(verification={"ok": ver["ok"], "problems": ver["problems"][:10]}, compare=cmp,
                   ok=ver["ok"] and cmp["ok"], problems=(ver["problems"][:3] if not ver["ok"] else []) + cmp["problems"])
    rec["wall_s"] = round(time.perf_counter() - t0, 1)
    rec["rule"] = "PASS = the M7n s0 run is the matched control; FAIL = stop, no replacement control is trained"
    write_json(ROOT / "_control" / "control_check.json", rec)
    write_json(out / "control_check.json", rec)
    log(f"control check {'PASS' if rec['ok'] else 'FAIL ' + str(rec['problems'][:2])} in {rec['wall_s'] / 60:.1f} min")
    return 0 if rec["ok"] else 1


def _artifact_first_ticks(eval_dir: Path) -> List[Optional[int]]:
    out = []
    for f in sorted(eval_dir.glob("*/workers/*/artifacts/*/actions.jsonl")):
        first = f.read_text(encoding="utf-8").splitlines()[:1]
        out.append(json.loads(first[0]).get("consumed_tick") if first else None)
    return out


def cmd_run(_: argparse.Namespace) -> int:
    from dataclasses import replace

    import numpy as np

    import m7_evaluation as ev
    import m7_trainer as tr
    import m7h_verify as mv
    from m7_runtime import install_kill_on_close_job, list_processes_named
    from m7_trainer import M7PPO

    if not REG.is_file():
        log("no registration: run `register` first")
        return 1
    reg = json.loads(REG.read_text(encoding="utf-8"))
    drift = _drift(reg)
    if drift:
        for d in drift:
            log(f"BLOCKED {d}")
        return 1
    cc_rec = ROOT / "_control" / "control_check.json"
    if not cc_rec.is_file() or not json.loads(cc_rec.read_text(encoding="utf-8")).get("ok") \
            or json.loads(cc_rec.read_text(encoding="utf-8")).get("code", {}).get("sha256") != reg["identity"]["code"]["sha256"]:
        log("BLOCKED: no passing control check on the registered code")
        return 1
    exp = ec.load_experiment(PROFILE)
    run_dir = ROOT / exp.name
    if run_dir.exists() or REPORT.is_file():
        log("a report or run directory exists: the diagnostic is never relaunched; a failed attempt stays preserved")
        return 1
    if list_processes_named():
        log("BattleShip already running; refusing to start")
        return 2
    install_kill_on_close_job()
    report: Dict[str, Any] = {"schema": "m7p_geo4_diag_report_v1", "registration_sha256": sha256_file(REG),
                              "control_check_sha256": sha256_file(cc_rec), "started_utc": utc_now(), "checks": {}, "problems": []}
    gate = g.launch_gate()
    report["launch_gate"] = gate
    if not gate["ok"]:
        log(f"launch gate refused {gate['problems']}")
        report["status"] = "gate_refused"
        write_json(REPORT, report)
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
    checks["E1_exit_clean"] = {"exit_code": res.get("exit_code"), "stop_kind": res.get("stop_kind"), "leftover": res.get("leftover_battleship_pids")}
    if res.get("exit_code") != 0 or res.get("stop_kind") or res.get("leftover_battleship_pids"):
        problems.append(f"E1: {checks['E1_exit_clean']}")
        report["status"] = "engineering_failure"
        write_json(REPORT, report)
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
    checks["E2_accounting"] = {"sb3_num_timesteps": steps, "n_updates": n_updates, "sets": sorted(sets),
                               "user_config": summ.get("user_config"), "leak_free": (summ.get("cleanup") or {}).get("leak_free")}
    if steps != CAP or n_updates != EXPECTED_N_UPDATES or sorted(sets) != sorted(CHECKPOINTS):
        problems.append(f"E2: {checks['E2_accounting']}")
    for name, entry in sets.items():
        vn = entry["vecnormalize"]
        if vn.get("norm_obs") or vn.get("norm_reward") or vn.get("obs_rms_counts"):
            problems.append(f"E2: {name} VecNormalize {vn}")
    init = list(dr.checkpoint_digests(run_dir / "checkpoints" / "ckpt_000000000"))
    checks["E3_fresh_initial"] = {"fresh": (ver["checks"].get("initial_policy") or {}).get("matches_fresh_construction"),
                                  "equals_m7n_s0_initial": init == reg["identity"]["control"]["initial_digests"],
                                  "note": "same seed, architecture and space shapes: the initial parameters are expected to equal the M7n "
                                          "s0 initial set (recorded, not required)"}
    if not checks["E3_fresh_initial"]["fresh"]:
        problems.append(f"E3: {checks['E3_fresh_initial']}")
    eps = ver["checks"]["episodes"]
    checks["E4_rows_valid"] = {"rows": eps["rows"], "row_problem_count": eps["row_problem_count"], "end_reasons": eps["end_reasons"]}
    if eps["rows"] < 1 or eps["row_problem_count"]:
        problems.append(f"E4: {checks['E4_rows_valid']}")
    d0, d1 = dr.checkpoint_digests(run_dir / "checkpoints" / "ckpt_000000000")[0], dr.checkpoint_digests(run_dir / "final")[0]
    model = M7PPO.load(str(run_dir / "final" / "model.zip"), device="cpu")
    finite = all(np.isfinite(p.detach().cpu().numpy()).all() for p in model.policy.parameters())
    checks["E5_updates_happened"] = {"changed": d0 != d1, "finite": finite}
    if d0 == d1 or not finite:
        problems.append("E5: parameters unchanged or not finite")
    meta = json.loads((run_dir / "final" / "checkpoint.json").read_text(encoding="utf-8"))
    c = meta.get("contracts") or {}
    flags = dict(rj.get("m6_flags") or {})
    checks["E6_contracts"] = {"observation": c.get("policy_observation_contract"),
                              "digest_ok": c.get("policy_observation_contract_sha256") == mg.contract_digest(),
                              "derived_from": c.get("policy_observation_derived_from"),
                              "table_ok": c.get("action_class_table_sha256") == st.load_table()["sha256"],
                              "flags_ok": all(flags.get(k) == v for k, v in mg.ENTITY_EXTRA_ENV),
                              "network": (rj.get("policy_network") or {}).get("network_id")}
    if c.get("policy_observation_contract") != mg.OBS_CONTRACT or not checks["E6_contracts"]["digest_ok"] \
            or not checks["E6_contracts"]["table_ok"] or not checks["E6_contracts"]["flags_ok"]:
        problems.append(f"E6: {checks['E6_contracts']}")
    checks["E7_resources"] = report["training"]["monitor"] | {"commit_drawn_gib": res.get("commit_drawn_gib")}
    if (mon.get("max_battleship_processes") or 0) > MAX_PROCESSES or mon.get("hard_alerts"):
        problems.append(f"E7: {checks['E7_resources']}")
    # -- evaluation of the final set (tick 0, frozen, metrics on) ---------------------------------------------------
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
    checks["E8_evaluation"] = {"ok": vev["ok"] and t0c["ok"], "problems": (vev["problems"] + t0c["problems"])[:10],
                               "first_consumed_ticks_all_zero": all(t == 0 for t in ticks), "wall_s": round(time.perf_counter() - t1, 1),
                               "leftover": list_processes_named(), "stochastic_episodes": len(sto), "deterministic_episodes": len(det),
                               "observation_note": result.get("observation_note")}
    if not checks["E8_evaluation"]["ok"] or not checks["E8_evaluation"]["first_consumed_ticks_all_zero"] or list_processes_named() \
            or len(sto) != EVAL["stochastic"] or len(det) != EVAL["deterministic"]:
        problems.append(f"E8: {checks['E8_evaluation']['problems'][:3]}")
    mean_t = sum(e["targets_broken"] for e in sto) / len(sto) if sto else None
    ref = reg["identity"]["control"]["curve_307200"]["mean_targets"]
    sd = (sum((e["targets_broken"] - mean_t) ** 2 for e in sto) / max(1, len(sto) - 1)) ** 0.5 if sto else None
    report["regression_check"] = {"diag_mean_targets_60": None if mean_t is None else round(mean_t, 4), "control_curve_307200_mean": ref,
                                  "difference": None if mean_t is None else round(mean_t - ref, 4), "band": CRITERIA["regression_band_targets"],
                                  "diag_sd": None if sd is None else round(sd, 3),
                                  "standard_error_of_difference_approx": None if sd is None else round(sd * (2 / 60) ** 0.5, 3),
                                  "falls": sum(1 for e in sto if e["end_reason"] == "fall"), "clears": sum(1 for e in sto if e.get("cleared")),
                                  "deterministic_targets": sorted({e["targets_broken"] for e in det}),
                                  "left_entries": sum(1 for e in sto if (e.get("eval_metrics") or {}).get("first_left_entry")),
                                  "targets_histogram": {str(k): sum(1 for e in sto if e["targets_broken"] == k) for k in range(11)},
                                  "gameplay_regression": mean_t is not None and mean_t < ref - CRITERIA["regression_band_targets"],
                                  "note": "stop-only regression check with sampling uncertainty; never a benefit claim"}
    rows, _ = dr.jsonl_rows(run_dir / "metrics" / "episodes.jsonl")
    report["descriptive_not_a_check"] = {"training_episodes": len(rows),
                                         "mean_targets": round(float(np.mean([r["targets_broken"] for r in rows])), 3) if rows else None,
                                         "falls": sum(1 for r in rows if r["end_reason"] == "fall"),
                                         "throughput": summ.get("throughput"), "wall": summ.get("wall")}
    report["finished_utc"] = utc_now()
    report["engineering_ok"] = not problems
    report["status"] = "trained_and_evaluated" if not problems else "engineering_failure"
    write_json(REPORT, report)
    log(f"run {'OK' if not problems else 'ENGINEERING FAILURE'}: {problems[:3]}; regression check {report['regression_check']}")
    return 0 if not problems else 1


# -- analysis --------------------------------------------------------------------------------------------------------


def _rebuild(make_builder: Any) -> Tuple[Any, Any, Dict[str, Any]]:
    import numpy as np

    import m7g_spatial as ms
    import m7n_entity as ne

    cls = st.ActionClassifier(st.load_table(), "mario")
    X: List[Any] = []
    meta: List[Tuple[Any, ...]] = []
    for p in SAMPLE_SOURCES:
        d = json.load(gzip.open(p, "rt", encoding="utf-8"))
        tag = ("A:" if "traces" in p.parts else "B:") + p.stem
        initial, steps = d["initial"], d["steps"]
        sp = ms.spatial_of(initial, expect_lines=True)
        en = ne.entity_of(initial)
        b = make_builder(sp.lines or (), cls)

        def add(reply, sp, en, tick):
            obs, stale = b.build(reply["observation"], sp, en)
            o = reply["observation"]
            g2 = sp.group(2)
            X.append(mn.flatten(obs))
            meta.append((tag, tick, float(o["position_x"]), float(o["position_y"]), int(o["ground_air_state"]),
                         int(o["fighter_status_id"]), cls.index(int(o["fighter_status_id"])), int(en.fighter.status_total_tics),
                         int(o["targets_remaining"]), float(g2.translate[1]) if g2 else float("nan"),
                         int(o["fighter_valid"] == 1 and o["btt_active"] == 1), int(stale)))

        add(initial, sp, en, 0)
        for s in steps:
            sp = ms.spatial_of(s, expect_lines=False)
            en = ne.entity_of(s)
            add(s, sp, en, int(s["consumed_tick"]) + 1)
    Xa = np.stack(X).astype(np.float32)
    tags = np.array([m[0] for m in meta])
    num = np.array([m[1:] for m in meta], dtype=np.float64)
    F = ["tick", "x", "y", "ga", "status_id", "class_idx", "status_tics", "targets_remaining", "platform_y", "live", "stale"]
    return Xa, tags, {f: num[:, i] for i, f in enumerate(F)}


def _pairs(tags: Any, col: Dict[str, Any], X: Any) -> Dict[str, List[Tuple[int, int]]]:
    """Recorded-pair definitions (indices; identical for both arms because they depend on native state only)."""
    import numpy as np

    IDLE, SQUAT, SPECIAL_HI = 0, 2, 13
    tick, tr, x, y, cl, tics, live = col["tick"], col["targets_remaining"], col["x"], col["y"], col["class_idx"], col["status_tics"], col["live"] == 1
    stale = col["stale"] == 1
    n = len(X)
    same_next = np.array([i + 1 < n and tags[i + 1] == tags[i] and tick[i + 1] == tick[i] + 1 for i in range(n)])
    breaks = [(i, i + 1) for i in range(n - 1) if same_next[i] and tr[i + 1] < tr[i] and live[i] and live[i + 1]]
    consec = [(i, i + 1) for i in range(n - 1) if same_next[i] and tr[i + 1] == tr[i] and live[i] and live[i + 1] and not stale[i + 1]]
    rng = np.random.default_rng(0)
    consec_s = [consec[k] for k in rng.choice(len(consec), 3000, replace=False)]
    sh = np.where(live & (cl == SPECIAL_HI))[0]
    upb, upb_ctl = [], []
    for a in sh:
        if not (5 <= tics[a] <= 10):
            continue
        cand = sh[(np.abs(x[sh] - x[a]) < 150) & (np.abs(y[sh] - y[a]) < 150) & (tags[sh] != tags[a])]
        for j in cand:
            if 20 <= tics[j] <= 30 and len(upb) < 800:
                upb.append((int(a), int(j)))
            elif 5 <= tics[j] <= 10 and len(upb_ctl) < 800:
                upb_ctl.append((int(a), int(j)))
    sq = np.where(live & (cl == SQUAT))[0]
    prog, prog_ctl = [], []
    for a in sq:
        if tics[a] != 0:
            continue
        cand = sq[(np.abs(x[sq] - x[a]) < 40) & (np.abs(y[sq] - y[a]) < 5) & (tr[sq] == tr[a]) & (np.abs(tick[sq] - tick[a]) > 5)]
        for j in cand:
            if tics[j] == 2 and len(prog) < 600:
                prog.append((int(a), int(j)))
            elif tics[j] == 0 and len(prog_ctl) < 600:
                prog_ctl.append((int(a), int(j)))
    return {"break": breaks, "consecutive_control": consec_s, "upb_progress": upb, "upb_control": upb_ctl,
            "squat_progress": prog, "squat_control": prog_ctl}


def _net_outputs(model: Any, X: Any) -> Dict[str, Any]:
    import numpy as np
    import torch

    pol = model.policy
    with torch.no_grad():
        xt = torch.tensor(X)
        z1p = pol.mlp_extractor.policy_net[0](xt); h1p = torch.tanh(z1p); z2p = pol.mlp_extractor.policy_net[2](h1p); h2p = torch.tanh(z2p)
        z1v = pol.mlp_extractor.value_net[0](xt); h1v = torch.tanh(z1v); z2v = pol.mlp_extractor.value_net[2](h1v); h2v = torch.tanh(z2v)
        logits = pol.action_net(h2p)
        V = pol.value_net(h2v).squeeze(-1)
        lps = torch.log_softmax(logits[:, :9], -1)
        lpb = torch.log_softmax(logits[:, 9:], -1)
    return {k: v.numpy().astype(np.float64) for k, v in dict(z1p=z1p, h1p=h1p, h2p=h2p, z1v=z1v, h1v=h1v, h2v=h2v, lps=lps, lpb=lpb, V=V).items()}


def _sat(z: Any) -> Dict[str, float]:
    import numpy as np

    h = np.tanh(z)
    a = np.abs(h)
    fs = (a > 0.95).mean(0)
    pos = (h > 0).mean(0)
    sign_const = (pos > 0.99) | (pos < 0.01)
    return {"mean_abs_z": float(np.abs(z).mean()), "p90_abs_z": float(np.percentile(np.abs(z), 90)), "p99_abs_z": float(np.percentile(np.abs(z), 99)),
            "sat95": float((a > 0.95).mean()), "sat99": float((a > 0.99).mean()), "mean_deriv": float((1 - h ** 2).mean()),
            "median_deriv": float(np.median(1 - h ** 2)), "units_sat95_gt90": float((fs > 0.9).mean()),
            "units_stuck_sign_const": float((sign_const & (fs > 0.9)).mean()), "units_two_sided": float((~sign_const & (fs > 0.9)).mean()),
            "units_effectively_constant": float((h.std(0) < 0.05).mean())}


def _kl(o: Dict[str, Any], i: Any, j: Any) -> Any:
    import numpy as np

    ps, pb = np.exp(o["lps"][i]), np.exp(o["lpb"][i])
    return (ps * (o["lps"][i] - o["lps"][j])).sum(-1) + (pb * (o["lpb"][i] - o["lpb"][j])).sum(-1)


def _pair_stats(o: Dict[str, Any], pairs: Sequence[Tuple[int, int]]) -> Optional[Dict[str, float]]:
    import numpy as np

    if not pairs:
        return None
    i = np.array([p[0] for p in pairs]); j = np.array([p[1] for p in pairs])
    return {"n": len(pairs), "dh1_pi": float(np.median(np.linalg.norm(o["h1p"][i] - o["h1p"][j], axis=1))),
            "dh2_pi": float(np.median(np.linalg.norm(o["h2p"][i] - o["h2p"][j], axis=1))),
            "dh1_vf": float(np.median(np.linalg.norm(o["h1v"][i] - o["h1v"][j], axis=1))),
            "kl": float(np.median(_kl(o, i, j))), "kl_p90": float(np.percentile(_kl(o, i, j), 90)),
            "dV": float(np.median(np.abs(o["V"][i] - o["V"][j])))}


def _ablation_kl(model: Any, X: Any, o: Dict[str, Any], a: int, b: int) -> float:
    import numpy as np
    import torch

    Xa = X.copy(); Xa[:, a:b] = 0.0
    pol = model.policy
    with torch.no_grad():
        h = torch.tanh(pol.mlp_extractor.policy_net[2](torch.tanh(pol.mlp_extractor.policy_net[0](torch.tensor(Xa)))))
        la = pol.action_net(h)
        qs = torch.log_softmax(la[:, :9], -1).numpy().astype(np.float64); qb = torch.log_softmax(la[:, 9:], -1).numpy().astype(np.float64)
    ps, pb = np.exp(o["lps"]), np.exp(o["lpb"])
    return float(((ps * (o["lps"] - qs)).sum(-1) + (pb * (o["lpb"] - qb)).sum(-1)).mean())


def _row_change(models: Sequence[Any], net: str) -> List[float]:
    import numpy as np

    W = [getattr(m.policy.mlp_extractor, net)[0].weight.detach().numpy().astype(np.float64) for m in models]
    return [float(np.median(np.linalg.norm(W[k + 1] - W[k], axis=1))) for k in range(len(W) - 1)]


def cmd_analyze(_: argparse.Namespace) -> int:
    import numpy as np

    from m7_trainer import M7PPO

    reg = json.loads(REG.read_text(encoding="utf-8"))
    if not REPORT.is_file():
        log("no report: run the diagnostic first")
        return 1
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    if DECISION.is_file():
        log(f"decision exists and is frozen: {ec.repo_relative(DECISION)}")
        return 1
    exp = ec.load_experiment(PROFILE)
    run_dir = ROOT / exp.name
    arms = {"control_v3": {"root": M7N_S0, "paths": CONTROL_CHECKPOINTS, "make_builder": lambda l, c: mn.EntityObservationBuilder(l, c),
                           "contract": mn.OBS_CONTRACT, "digest": mn.contract_digest()},
            "diag_geo4": {"root": run_dir, "paths": {k: ("final" if k == "final" else f"checkpoints/{k}") for k in CHECKPOINTS},
                          "make_builder": mg.make_builder, "contract": mg.OBS_CONTRACT, "digest": mg.contract_digest()}}
    analysis: Dict[str, Any] = {"schema": "m7p_geo4_diag_analysis_v1", "utc": utc_now(), "registration_sha256": sha256_file(REG),
                                "report_sha256": sha256_file(REPORT), "arms": {}}
    pairs = None
    for arm, spec in arms.items():
        X, tags, col = _rebuild(spec["make_builder"])
        isA = np.char.startswith(tags, "A:")
        if pairs is None:
            pairs = _pairs(tags, col, X)
        # every checkpoint's contract must match the arm
        out: Dict[str, Any] = {"contract": spec["contract"], "contract_digest": spec["digest"], "sample_states": int(len(X)),
                               "population_A": int(isA.sum()), "population_B": int((~isA).sum()),
                               "input_block_l2_mean": {n: float(np.linalg.norm(X[:, a:b], axis=1).mean()) for n, a, b in
                                                       (("agent", 20, 48), ("segment_geometry", 76, 332), ("targets", 556, 606))},
                               "checkpoints": {}}
        models = []
        for lab, rel in spec["paths"].items():
            ck = spec["root"] / rel
            meta = json.loads((ck / "checkpoint.json").read_text(encoding="utf-8"))
            c = meta.get("contracts") or {}
            if c.get("policy_observation_contract") != spec["contract"] or c.get("policy_observation_contract_sha256") != spec["digest"]:
                raise SystemExit(f"{ck}: contract {c.get('policy_observation_contract')} / digest mismatch for arm {arm}")
            m = M7PPO.load(str(ck / "model.zip"), device="cpu")
            models.append(m)
            o = _net_outputs(m, X)
            rec = {"num_timesteps": int(m.num_timesteps), "policy_digest": dr.checkpoint_digests(ck)[0]}
            for net, z1, z2 in (("actor", o["z1p"], np.arctanh(np.clip(o["h2p"], -0.999999, 0.999999))), ("critic", o["z1v"], np.arctanh(np.clip(o["h2v"], -0.999999, 0.999999)))):
                rec[net] = {"L1_all": _sat(z1), "L1_A": _sat(z1[isA]), "L1_B": _sat(z1[~isA]), "L2_all": _sat(z2)}
            rec["pairs"] = {k: _pair_stats(o, v) for k, v in pairs.items()}
            rec["ablation_kl"] = {"agent_block": _ablation_kl(m, X, o, 20, 48), "targets_block": _ablation_kl(m, X, o, 556, 606),
                                  "segment_geometry_block": _ablation_kl(m, X, o, 76, 332)}
            rec["policy_entropy_nats"] = float((-(np.exp(o["lps"]) * o["lps"]).sum(-1) - (np.exp(o["lpb"]) * o["lpb"]).sum(-1)).mean())
            rec["W1_norm"] = {"actor": float(np.linalg.norm(m.policy.mlp_extractor.policy_net[0].weight.detach().numpy())),
                              "critic": float(np.linalg.norm(m.policy.mlp_extractor.value_net[0].weight.detach().numpy()))}
            out["checkpoints"][lab] = rec
        out["W1_row_change_per_interval"] = {"actor": _row_change(models, "policy_net"), "critic": _row_change(models, "value_net"),
                                             "intervals": list(zip(list(spec["paths"])[:-1], list(spec["paths"])[1:]))}
        rows = [json.loads(l) for l in (spec["root"] / "metrics" / "rollouts.jsonl").read_text(encoding="utf-8").splitlines()][:60]
        tm = [r["train_metrics"] for r in rows]
        last = tm[-CRITERIA["optimization_last_updates"]:]

        def mean(key, seq):
            return float(np.mean([t[key] for t in seq]))

        out["optimization_60_updates"] = {
            "approx_kl_mean": mean("train/approx_kl", tm), "clip_fraction_mean": mean("train/clip_fraction", tm),
            "value_loss_mean": mean("train/value_loss", tm), "explained_variance_first10_last10": [mean("train/explained_variance", tm[:10]), mean("train/explained_variance", tm[-10:])],
            "entropy_first_last": [-tm[0]["train/entropy_loss"], -tm[-1]["train/entropy_loss"]],
            "last20": {"clip_fraction_mean": mean("train/clip_fraction", last), "explained_variance_mean": mean("train/explained_variance", last),
                       "approx_kl_mean": mean("train/approx_kl", last), "all_finite": bool(all(np.isfinite(t["train/loss"]) for t in last))},
            "training_targets_by_rollout_quintile": [float(np.mean([r["targets_mean"] for r in rows[k * 12:(k + 1) * 12] if r.get("targets_mean") is not None] or [np.nan])) for k in range(5)],
            "gradient_norms": "UNAVAILABLE for both arms (SB3 logs no gradient norm; the historical control cannot be re-instrumented)"}
        analysis["arms"][arm] = out
        log(f"{arm}: analysed {len(spec['paths'])} checkpoints on {len(X)} states")
    analysis["pairs_n"] = {k: len(v) for k, v in pairs.items()}
    # -- decision (frozen criteria) ----------------------------------------------------------------------------------
    C = CRITERIA
    ctl = analysis["arms"]["control_v3"]["checkpoints"]["final"]
    dia = analysis["arms"]["diag_geo4"]["checkpoints"]["final"]
    opt = analysis["arms"]["diag_geo4"]["optimization_60_updates"]["last20"]
    eng_ok = bool(report.get("engineering_ok"))
    gameplay_regression = bool((report.get("regression_check") or {}).get("gameplay_regression"))
    optimization_regression = (opt["clip_fraction_mean"] > C["clip_fraction_max"] or opt["explained_variance_mean"] < C["explained_variance_min"]
                               or opt["approx_kl_mean"] > C["approx_kl_max"] or not opt["all_finite"])
    r = C["discrimination_retention_ratio"]
    disc = {"break_dV": dia["pairs"]["break"]["dV"] >= r * ctl["pairs"]["break"]["dV"],
            "break_kl": dia["pairs"]["break"]["kl"] >= r * ctl["pairs"]["break"]["kl"],
            "upb_progress_kl": dia["pairs"]["upb_progress"]["kl"] >= r * ctl["pairs"]["upb_progress"]["kl"],
            "upb_progress_above_control_pairs": dia["pairs"]["upb_progress"]["kl"] > dia["pairs"]["upb_control"]["kl"],
            "agent_ablation_kl": dia["ablation_kl"]["agent_block"] >= r * ctl["ablation_kl"]["agent_block"],
            "targets_ablation_kl": dia["ablation_kl"]["targets_block"] >= r * ctl["ablation_kl"]["targets_block"]}
    sat_reduced = {"actor": dia["actor"]["L1_all"]["sat95"] <= ctl["actor"]["L1_all"]["sat95"] - C["saturation_reduction_actor"],
                   "critic": dia["critic"]["L1_all"]["sat95"] <= ctl["critic"]["L1_all"]["sat95"] - C["saturation_reduction_critic"]}
    if not eng_ok:
        outcome = "engineering_failure"
    elif gameplay_regression or optimization_regression:
        outcome = "regression"
    elif not all(disc.values()):
        outcome = "discrimination_lost"
    elif all(sat_reduced.values()):
        outcome = "diagnostic_pass"
    else:
        outcome = "inconclusive"
    analysis["decision"] = {"outcome": outcome, "engineering_ok": eng_ok, "gameplay_regression": gameplay_regression,
                            "optimization_regression": bool(optimization_regression), "discrimination_checks": disc,
                            "saturation_reduced": sat_reduced, "criteria": C,
                            "paired_at_307200": {
                                "actor_sat95": [ctl["actor"]["L1_all"]["sat95"], dia["actor"]["L1_all"]["sat95"]],
                                "critic_sat95": [ctl["critic"]["L1_all"]["sat95"], dia["critic"]["L1_all"]["sat95"]],
                                "actor_mean_deriv": [ctl["actor"]["L1_all"]["mean_deriv"], dia["actor"]["L1_all"]["mean_deriv"]],
                                "critic_mean_deriv": [ctl["critic"]["L1_all"]["mean_deriv"], dia["critic"]["L1_all"]["mean_deriv"]],
                                "break_dV": [ctl["pairs"]["break"]["dV"], dia["pairs"]["break"]["dV"]],
                                "break_kl": [ctl["pairs"]["break"]["kl"], dia["pairs"]["break"]["kl"]],
                                "upb_progress_kl": [ctl["pairs"]["upb_progress"]["kl"], dia["pairs"]["upb_progress"]["kl"]],
                                "upb_control_kl": [ctl["pairs"]["upb_control"]["kl"], dia["pairs"]["upb_control"]["kl"]],
                                "agent_ablation_kl": [ctl["ablation_kl"]["agent_block"], dia["ablation_kl"]["agent_block"]],
                                "targets_ablation_kl": [ctl["ablation_kl"]["targets_block"], dia["ablation_kl"]["targets_block"]],
                                "regression_check": report.get("regression_check")},
                            "meaning": {"diagnostic_pass": "the rescale lowered saturation without losing the tested discrimination or "
                                                           "destabilising optimisation at 307,200 transitions in ONE seed; not evidence of "
                                                           "better gameplay, crossings or clears; a larger comparison becomes eligible as a "
                                                           "separate decision",
                                        "other": "no larger comparison is justified by this diagnostic"}}
    write_json(ANALYSIS, analysis)
    write_json(DECISION, {"schema": "m7p_geo4_diag_decision_v1", "utc": utc_now(), "registration_sha256": sha256_file(REG),
                          "analysis_sha256": sha256_file(ANALYSIS), "decision": analysis["decision"]})
    log(f"decision: {outcome} -> {ec.repo_relative(DECISION)} (write-once)")
    print(json.dumps(analysis["decision"]["paired_at_307200"], indent=1, default=str))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["register", "control-check", "run", "analyze"])
    args = ap.parse_args(argv)
    return {"register": cmd_register, "control-check": cmd_control_check, "run": cmd_run, "analyze": cmd_analyze}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
