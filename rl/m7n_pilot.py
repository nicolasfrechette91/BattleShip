"""M7n: the capped integration pilot of btt_policy_obs_v3_entities (registration frozen BEFORE launch; one run; never a
campaign input; never used to tune anything).

    python rl/m7n_pilot.py register     # freeze docs/rl_observation_v3_m7n_pilot_registration.json (cap, checks, identity)
    python rl/m7n_pilot.py run          # launch gate -> guarded training (+40,960) -> verification -> evaluation smoke
    python rl/m7n_pilot.py status

What the pilot verifies (registered pass / fail checks, all required):
    P1  the trainer exits 0 under the M7h guard; no BattleShip process left; the user configuration untouched
    P2  exact accounting: sb3_num_timesteps == 40,960, n_updates == 8 rollouts x 10 epochs = 80, checkpoint sets
        ckpt_000000000 / ckpt_000020480 / final present, hash-verified, statistics frozen-loadable with norm_obs False
    P3  ckpt_000000000 equals a fresh construction from the profile (policy digest and VecNormalize digest)
    P4  every training episode row validates against btt_reward_v2 (rl/m7d_run.validate_episode_row); rows > 0
    P5  the policy parameters changed between ckpt_000000000 and final (PPO updates happened) and are finite
    P6  the run's contracts record btt_policy_obs_v3_entities with this code's digest, the action-class table digest
        and both native flags; run.json records the v3 network identity
    P7  resources: at most 10 BattleShip processes at any sample, no hard alert, peak commit drawn and working set recorded
    P8  evaluation smoke of the final set from tick 0 (5 deterministic + 5 stochastic, seed 12345, metrics on):
        rl/m7d_run.verify_evaluation passes, every preserved artifact's first action consumed tick 0, no stale step
        outside a fall's terminal reply
Pilot performance (targets, returns) is recorded but is NOT a check and never informs the representation, the reward,
the budget or the decision rule.
"""
from __future__ import annotations

import argparse
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

REPO_ROOT = RL_DIR.parent
PROFILE = RL_DIR / "configs" / "m7n" / "pilot" / "m7n_pilot_s0.toml"
EXE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
ROOT = REPO_ROOT / "runs" / "m7n" / "pilot"
REGISTRATION = REPO_ROOT / "docs" / "rl_observation_v3_m7n_pilot_registration.json"
REPORT = ROOT / "pilot_report.json"
CAP = 40_960
ROLLOUT = 5_120
EPOCHS = 10
SMOKE = {"deterministic": 5, "stochastic": 5}
MAX_PROCESSES = 10


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def log(msg: str) -> None:
    print(f"[m7n_pilot] {msg}", flush=True)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def code_fingerprint() -> Dict[str, Any]:
    from m7n_control_check import code_fingerprint as cf

    return cf()


def fresh_digests(exp: ec.Experiment) -> Tuple[str, str]:
    """The (policy, VecNormalize) digests a fresh v3 model of this profile must have (the trainer's construction:
    VecNormalize(norm_obs False) around the v3 Dict space, then M7PPO with the profile's PPO values and seed)."""
    import gymnasium as gym
    import numpy as np
    import torch
    from stable_baselines3.common.vec_env import DummyVecEnv

    import m7_trainer as tr
    from btt_learning import make_track1_action_space
    from m7_evaluation import obs_rms_digest, policy_parameter_digest

    class _Spaces(gym.Env):
        def __init__(self) -> None:
            self.observation_space = mn.make_observation_space()
            self.action_space = make_track1_action_space()

        def reset(self, *, seed=None, options=None):
            super().reset(seed=seed)
            return {k: np.zeros(s, np.float32) for k, s in mn.SHAPES.items()}, {}

        def step(self, action):
            return {k: np.zeros(s, np.float32) for k, s in mn.SHAPES.items()}, 0.0, False, False, {}

    cfg = tr.config_from_experiment(exp)
    threads = torch.get_num_threads()
    torch.set_num_threads(int(cfg.torch_threads))
    try:
        vecnorm = tr.make_vecnormalize(cfg, DummyVecEnv([_Spaces for _ in range(cfg.n_envs)]))
        model = tr.make_model(cfg, vecnorm)
        return policy_parameter_digest(model), obs_rms_digest(vecnorm)
    finally:
        torch.set_num_threads(threads)


def identity() -> Dict[str, Any]:
    exp = ec.load_experiment(PROFILE)
    v = exp.values
    pol, rms = fresh_digests(exp)
    return {"profile": ec.repo_relative(PROFILE), "profile_sha256": exp.source.sha256,
            "semantic_fingerprint": exp.semantic_fingerprint, "compatibility_fingerprint": exp.compatibility_fingerprint,
            "run_name": exp.name, "total_transitions": int(v["run.total_transitions"]), "base_seed": int(v["run.base_seed"]),
            "observation": v["contracts.observation"], "observation_digest": mn.contract_digest(),
            "action_class_table_sha256": st.load_table()["sha256"], "reward": exp.reward.contract,
            "native_flags": dict(exp.extra_env), "executable_sha256": sha256_file(EXE), "code": code_fingerprint(),
            "expected_initial_policy_digest": pol, "expected_initial_obs_rms_digest": rms,
            "revisions": dr.git_revisions() if hasattr(dr, "git_revisions") else None}


def cmd_register(_: argparse.Namespace) -> int:
    if REGISTRATION.is_file():
        log(f"registration exists and is frozen: {ec.repo_relative(REGISTRATION)}")
        return 1
    ident = identity()
    if ident["total_transitions"] != CAP:
        log(f"profile total {ident['total_transitions']} != registered cap {CAP}")
        return 1
    reg = {"schema": "m7n_pilot_registration_v1", "utc": utc_now(), "cap_transitions": CAP,
           "rollouts": CAP // ROLLOUT, "expected_n_updates": CAP // ROLLOUT * EPOCHS,
           "checkpoints": ["ckpt_000000000", "ckpt_000020480", "final"], "smoke_episodes": SMOKE,
           "evaluation_seed": 12345, "max_game_processes": MAX_PROCESSES,
           "launch_gate": {"commit_gib": g.LAUNCH_COMMIT_GIB, "physical_gib": g.LAUNCH_PHYSICAL_GIB},
           "checks": ["P1_exit_clean", "P2_accounting", "P3_fresh_initial", "P4_rows_valid", "P5_updates_happened",
                      "P6_contracts", "P7_resources", "P8_evaluation_smoke"],
           "never_used_for": ["tuning the representation", "the reward", "the budget", "decision thresholds",
                              "campaign warm starts"], "identity": ident}
    REGISTRATION.write_text(json.dumps(reg, indent=1) + "\n", encoding="utf-8", newline="\n")
    log(f"registered {ec.repo_relative(REGISTRATION)} sha256 {sha256_file(REGISTRATION)[:16]}")
    return 0


def _registration_drift(reg: Dict[str, Any]) -> List[str]:
    now = identity()
    keys = ("profile_sha256", "semantic_fingerprint", "compatibility_fingerprint", "total_transitions", "base_seed",
            "observation", "observation_digest", "action_class_table_sha256", "reward", "native_flags",
            "executable_sha256", "expected_initial_policy_digest", "expected_initial_obs_rms_digest")
    p = [f"{k}: registered {reg['identity'][k]!r} != now {now[k]!r}" for k in keys if reg["identity"][k] != now[k]]
    if reg["identity"]["code"]["sha256"] != now["code"]["sha256"]:
        p.append("code fingerprint changed since registration")
    return p


def _policy_digest(ckpt: Path) -> str:
    return dr.checkpoint_digests(ckpt)[0]


def _artifact_first_ticks(eval_dir: Path) -> List[Optional[int]]:
    ticks: List[Optional[int]] = []
    for mode in ("deterministic", "stochastic"):
        ev = json.loads((eval_dir / mode / "evaluation.json").read_text(encoding="utf-8"))
        for e in ev["episodes"]:
            a = e.get("artifact_dir")
            if not a:
                ticks.append(None)
                continue
            d = Path(a)
            d = d if d.is_absolute() else REPO_ROOT / d
            rows = [json.loads(x) for x in (d / "actions.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
            ticks.append(rows[0].get("consumed_tick") if rows else None)
    return ticks


def cmd_run(_: argparse.Namespace) -> int:
    import m7_evaluation as ev
    import m7_trainer as tr
    from m7_runtime import install_kill_on_close_job, list_processes_named

    if not REGISTRATION.is_file():
        log("no registration: run `register` first (the cap and checks are frozen before any launch)")
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
        log("the pilot ran already (one pilot, never relaunched): see runs/m7n/pilot")
        return 1
    if list_processes_named():
        log("BattleShip already running; refusing to start")
        return 2
    install_kill_on_close_job()
    report: Dict[str, Any] = {"schema": "m7n_pilot_report_v1", "registration_sha256": sha256_file(REGISTRATION),
                              "started_utc": utc_now(), "checks": {}, "problems": []}
    gate = g.launch_gate()
    report["launch_gate"] = gate
    if not gate["ok"]:
        log(f"launch gate refused {gate['problems']}")
        report["status"] = "gate_refused"
        _write(report)
        return 2
    # -- guarded training ----------------------------------------------------------------------------------------
    tag = f"{exp.name}__{stamp()}"
    guard = ROOT / "_guard"
    t0 = time.perf_counter()
    res = g.train_guarded(config=PROFILE, run_dir=run_dir, log_path=guard / "logs" / f"{tag}.log",
                          monitor_path=guard / "monitor" / f"{tag}.jsonl", probe_path=guard / "probe" / f"{tag}.jsonl",
                          contract=exp.reward, horizon=int(exp.values["environment.horizon"]),
                          partial_root=ROOT / "_partial")
    report["training"] = {k: res.get(k) for k in ("exit_code", "stop_kind", "moved_to", "wall_s", "commit_drawn_gib",
                                                  "leftover_battleship_pids", "log", "monitor_log", "probe")}
    mon = res.get("monitor") or {}
    report["training"]["monitor"] = {k: mon.get(k) for k in (
        "max_battleship_processes", "max_battleship_listeners", "hard_alerts", "soft_alert_count", "episodes_seen",
        "episode_ends", "lifecycle_failures", "max_commit_used_gib", "min_avail_commit_gib", "min_avail_phys_gib",
        "max_root_working_set_mib", "max_root_private_mib", "max_game_working_set_mib", "max_game_private_mib",
        "samples")}
    report["training"]["wall_total_s"] = round(time.perf_counter() - t0, 1)
    checks = report["checks"]
    problems = report["problems"]
    checks["P1_exit_clean"] = {"exit_code": res.get("exit_code"), "stop_kind": res.get("stop_kind"),
                               "leftover": res.get("leftover_battleship_pids")}
    if res.get("exit_code") != 0 or res.get("stop_kind") or res.get("leftover_battleship_pids"):
        problems.append(f"P1: {checks['P1_exit_clean']}")
        report["status"] = "failed"
        _write(report)
        return 1
    # -- verification --------------------------------------------------------------------------------------------
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
    if steps != CAP or n_updates != reg["expected_n_updates"] or sorted(sets) != sorted(reg["checkpoints"]):
        problems.append(f"P2: {checks['P2_accounting']}")
    for name, entry in sets.items():
        vn = entry["vecnormalize"]
        if vn.get("norm_obs") or vn.get("norm_reward") or vn.get("obs_rms_counts"):
            problems.append(f"P2: {name} VecNormalize {vn}")
    checks["P3_fresh_initial"] = ver["checks"].get("initial_policy")
    if not (checks["P3_fresh_initial"] or {}).get("matches_fresh_construction"):
        problems.append("P3: ckpt_000000000 is not the fresh construction")
    eps = ver["checks"]["episodes"]
    checks["P4_rows_valid"] = {"rows": eps["rows"], "row_problem_count": eps["row_problem_count"], "end_reasons": eps["end_reasons"],
                               "startup_modes": eps["startup_modes"]}
    if eps["rows"] < 1 or eps["row_problem_count"]:
        problems.append(f"P4: {checks['P4_rows_valid']}")
    d0 = _policy_digest(run_dir / "checkpoints" / "ckpt_000000000")
    d1 = _policy_digest(run_dir / "final")
    import numpy as np
    from m7_trainer import M7PPO

    model = M7PPO.load(str(run_dir / "final" / "model.zip"), device="cpu")
    finite = all(np.isfinite(p.detach().cpu().numpy()).all() for p in model.policy.parameters())
    checks["P5_updates_happened"] = {"initial_digest": d0[:16], "final_digest": d1[:16], "changed": d0 != d1, "finite": finite,
                                     "rollouts_logged": g.rollouts_logged(run_dir)}
    if d0 == d1 or not finite:
        problems.append("P5: parameters unchanged or not finite")
    meta = json.loads((run_dir / "final" / "checkpoint.json").read_text(encoding="utf-8"))
    c = meta.get("contracts") or {}
    net = (rj.get("policy_network") or {})
    checks["P6_contracts"] = {"observation": c.get("policy_observation_contract"),
                              "digest_ok": c.get("policy_observation_contract_sha256") == mn.contract_digest(),
                              "table_ok": c.get("action_class_table_sha256") == st.load_table()["sha256"],
                              "flags": dict(rj.get("m6_flags") or {}) if isinstance(rj.get("m6_flags"), dict) else rj.get("m6_flags"),
                              "network_id": net.get("network_id"), "parameters": net.get("parameters")}
    flags_ok = all(dict(rj.get("m6_flags") or {}).get(k) == v for k, v in mn.ENTITY_EXTRA_ENV) \
        if isinstance(rj.get("m6_flags"), dict) else None
    if c.get("policy_observation_contract") != mn.OBS_CONTRACT or not checks["P6_contracts"]["digest_ok"] \
            or not checks["P6_contracts"]["table_ok"] or net.get("network_id") != "btt_policy_net_v3_multiinput_mlp64" \
            or flags_ok is False:
        problems.append(f"P6: {checks['P6_contracts']}")
    checks["P7_resources"] = report["training"]["monitor"] | {"commit_drawn_gib": res.get("commit_drawn_gib"),
                                                                "probe": res.get("probe")}
    if (mon.get("max_battleship_processes") or 0) > MAX_PROCESSES or mon.get("hard_alerts"):
        problems.append(f"P7: {checks['P7_resources']}")
    # -- evaluation smoke ----------------------------------------------------------------------------------------
    from dataclasses import replace

    settings = replace(dr.evaluation_settings(exp), eval_metrics=True, observation=None)
    cfg = tr.config_from_experiment(exp)
    out = ROOT / "_eval" / exp.name / "final_smoke"
    t1 = time.perf_counter()
    result = ev.evaluate_checkpoint(run_dir / "final", out, settings=settings, deterministic_episodes=SMOKE["deterministic"],
                                    stochastic_episodes=SMOKE["stochastic"], expected_contracts=tr.run_contracts(cfg),
                                    label="final_smoke", preserve_all=True)
    plan = {"deterministic_episodes": SMOKE["deterministic"], "stochastic_episodes": SMOKE["stochastic"]}
    vev = dr.verify_evaluation(result, exp.reward, int(exp.values["environment.horizon"]), plan)
    ticks = _artifact_first_ticks(out)
    rows = [e for m in ("deterministic", "stochastic") for e in result["modes"][m]["episodes"]]
    checks["P8_evaluation_smoke"] = {"ok": vev["ok"], "problems": vev["problems"][:10], "first_consumed_ticks": ticks,
                                     "wall_s": round(time.perf_counter() - t1, 1),
                                     "targets": [e.get("targets_broken") for e in rows], "ends": [e.get("end_reason") for e in rows],
                                     "leftover": list_processes_named(), "observation_note": result.get("observation_note")}
    if not vev["ok"] or any(t != 0 for t in ticks) or list_processes_named():
        problems.append(f"P8: {checks['P8_evaluation_smoke']['problems'][:3]} ticks {ticks}")
    # -- descriptive (never a check) ------------------------------------------------------------------------------
    rows_tr, _ = dr.jsonl_rows(run_dir / "metrics" / "episodes.jsonl")
    report["descriptive_not_a_check"] = {
        "training_episodes": len(rows_tr), "mean_targets": round(float(np.mean([r["targets_broken"] for r in rows_tr])), 3) if rows_tr else None,
        "throughput": summ.get("throughput"), "wall": summ.get("wall")}
    report["finished_utc"] = utc_now()
    report["status"] = "passed" if not problems else "failed"
    report["ok"] = not problems
    _write(report)
    log(f"pilot {'PASSED' if report['ok'] else 'FAILED'}: {problems[:3]}")
    return 0 if report["ok"] else 1


def _write(report: Dict[str, Any]) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")


def cmd_status(_: argparse.Namespace) -> int:
    if REPORT.is_file():
        r = json.loads(REPORT.read_text(encoding="utf-8"))
        print(json.dumps({k: r.get(k) for k in ("status", "ok", "problems", "started_utc", "finished_utc")}, indent=1))
    else:
        print("no pilot report")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("register", "run", "status"))
    args = ap.parse_args(argv)
    return {"register": cmd_register, "run": cmd_run, "status": cmd_status}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
