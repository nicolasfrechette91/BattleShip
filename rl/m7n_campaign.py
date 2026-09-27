"""M7n campaign driver: the controlled three-seed observation comparison. Arm v3 = btt_policy_obs_v3_entities (fresh
models), arm v1 = the historical Phase K control (btt_policy_obs_v1), both under btt_reward_v2 and Track 1.

Registered settings and rule: docs/rl_observation_v3_m7n_manifest.json and docs/rl_observation_v3_m7n_decision_rule.json.
Everything is written below runs/m7n/campaign; the historical control (runs/m7g_k), the pilot trees and every other
run tree are read only.

    python rl/m7n_campaign.py manifest                  # build the manifest (docs/); refused once the campaign froze it
    python rl/m7n_campaign.py control-check             # R1 (3 x 102,400, reward v2), R2 (600 episodes), R3 (inputs)
    python rl/m7n_campaign.py train --dry-run           # = preflight: plan, drift, control check, profiles, gate
    python rl/m7n_campaign.py train                     # v3 s0, s1, s2 in order, each behind the launch gate
    python rl/m7n_campaign.py evaluate [--dry-run]      # tick-0 post-hoc Phase K protocol, 985 episodes per run
    python rl/m7n_campaign.py verify-clears | census | status
    python rl/m7n_campaign.py verify-crossings          # gate-2 inputs: both arms' finals, every candidate replayed
    python rl/m7n_campaign.py analyze [--dry-run]       # the registered rule, recorded once (never re-decided)
    python rl/m7n_campaign.py all                       # train -> evaluate -> verify-clears -> verify-crossings -> analyze

Stop policy (registered): a failed launch gate (after its re-readings), a monitor hard alert, the in-run memory policy,
a provenance mismatch, a process leak, a failed verification, a failed or unbound control check or a manifest drift
stops the campaign. A stopped run directory is moved to _partial by the guard and kept; nothing is resumed or
relaunched here. Native RNG state is never inspected, logged, validated, controlled, compared or hashed.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import experiment_config as ec  # noqa: E402
import m7d_run as dr  # noqa: E402
import m7h_guard as g  # noqa: E402
import m7l_analysis as la  # noqa: E402
import m7n_analysis as na  # noqa: E402
import m7n_crossing as xc  # noqa: E402
import m7n_matrix as nm  # noqa: E402
import m7n_obs as mn  # noqa: E402
import m7n_policy as mnp  # noqa: E402
import m7n_status_table as st  # noqa: E402

REPO_ROOT = RL_DIR.parent
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_INTERRUPTED = 0, 1, 2, 130

# Stand-ins for tests (never set in a real invocation).
GATE_FN: Optional[Callable[[], Dict[str, Any]]] = None
LAUNCHER: Optional[Callable[..., Dict[str, Any]]] = None
SLEEP: Callable[[float], None] = time.sleep


def log(message: str) -> None:
    print(f"[m7n-campaign {time.strftime('%H:%M:%S')}] {message}", flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# -- state ------------------------------------------------------------------------------------------------------------


def state_file() -> Path:
    return nm.state_dir() / "state.json"


def load_state() -> Dict[str, Any]:
    if state_file().is_file():
        return nm.read_json(state_file())
    return {"schema": "battleship_m7n_campaign_state_v1", "milestone": nm.MILESTONE, "created_utc": utc_now(),
            "control": {"mode": "historical"}, "runs": {}, "evaluations": {}, "clears": {}, "decisions": {}, "events": []}


def save_state(state: Dict[str, Any]) -> None:
    state["updated_utc"] = utc_now()
    nm.write_json(state_file(), state)


def event(state: Dict[str, Any], kind: str, **data: Any) -> None:
    state.setdefault("events", []).append(dict(kind=kind, utc=utc_now(), **data))
    save_state(state)


# -- the manifest ----------------------------------------------------------------------------------------------------


def frozen_manifest_path() -> Path:
    return nm.state_dir() / "manifest.json"


def load_manifest(*, freeze: bool) -> Dict[str, Any]:
    fp = frozen_manifest_path()
    if fp.is_file():
        man = nm.read_json(fp)
        if nm.MANIFEST_DOC.is_file() and nm.read_json(nm.MANIFEST_DOC) != man:
            raise nm.MatrixError(f"{ec.repo_relative(nm.MANIFEST_DOC)} differs from the frozen copy")
        return man
    if not nm.MANIFEST_DOC.is_file():
        raise nm.MatrixError(f"{ec.repo_relative(nm.MANIFEST_DOC)} missing: run 'python rl/m7n_campaign.py manifest'")
    man = nm.read_json(nm.MANIFEST_DOC)
    if freeze:
        nm.write_json(fp, man)
    return man


def cmd_manifest(args: argparse.Namespace) -> int:
    if frozen_manifest_path().is_file() and not args.out:
        log(f"refused: the campaign froze its manifest at {ec.repo_relative(frozen_manifest_path())}; never rebuilt")
        return EXIT_USAGE
    man = nm.build_manifest()
    out = Path(args.out) if args.out else nm.MANIFEST_DOC
    nm.write_json(out, man)
    log(f"manifest -> {ec.repo_relative(out)} ok={man['ok']} code {man['code']['sha256'][:12]} ({man['code']['files']} "
        f"files; control-check fingerprint {man['code']['control_check_sha256'][:12]}) rule {man['decision_rule']['sha256'][:12]} "
        f"control bound={man['historical_control']['control_check']['bound_to_this_manifest']}")
    for p in man["problems"]:
        log(f"  PROBLEM {p}")
    return EXIT_OK if man["ok"] else EXIT_FAILED


# -- resources --------------------------------------------------------------------------------------------------------


def wait_for_launch_gate(tag: str) -> Dict[str, Any]:
    readings: List[Dict[str, Any]] = []
    last: Dict[str, Any] = {}
    for i in range(nm.LAUNCH_GATE_READINGS):
        last = (GATE_FN or g.launch_gate)()
        readings.append({"utc": utc_now(), "ok": last["ok"], "problems": last["problems"],
                         "measurement": {k: (last.get("measurement") or {}).get(k) for k in (
                             "avail_commit_gib", "avail_phys_gib", "disk_free_gib", "cpu_mean_pct", "battleship_pids",
                             "listeners", "ssb64_environment_variables")}})
        if last["ok"]:
            return {"ok": True, "tag": tag, "readings": readings, "problems": []}
        if i < nm.LAUNCH_GATE_READINGS - 1:
            log(f"{tag}: launch gate reading {i + 1} failed {last['problems']}; re-measuring in "
                f"{nm.LAUNCH_GATE_RETRY_S:.0f} s")
            SLEEP(nm.LAUNCH_GATE_RETRY_S)
    return {"ok": False, "tag": tag, "readings": readings, "problems": last.get("problems")}


# -- the control check -----------------------------------------------------------------------------------------------


def control_check_problems(manifest: Mapping[str, Any]) -> List[str]:
    """Why the historical control may not be reused now (empty = it may): a PASSED record on exactly the manifest's
    control-check code fingerprint and executable, and the historical control files unchanged since the manifest."""
    p: List[str] = []
    rec = nm.control_record()
    code = (manifest.get("code") or {}).get("control_check_sha256")
    exe = (manifest.get("executable") or {}).get("sha256")
    if rec is None:
        p.append("the control check has not run: python rl/m7n_campaign.py control-check")
    else:
        if not rec.get("ok"):
            p.append(f"the control check FAILED ({(rec.get('problems') or [])[:3]}); the control is not reused; stop and diagnose")
        if (rec.get("code") or {}).get("sha256") != code:
            p.append(f"the control check ran on code {str((rec.get('code') or {}).get('sha256'))[:12]}, the manifest "
                     f"pins {str(code)[:12]}: rerun it")
        if rec.get("executable_sha256") != exe:
            p.append("the control check ran on another executable")
        if not (rec.get("r4") or {}).get("ok"):
            p.append("the control check has no passing R4 (the corrected gate-2 inputs of the control): rerun it")
    for s, want in ((manifest.get("historical_control") or {}).get("seeds") or {}).items():
        now = nm.historical_identity(int(s))
        keys = ("final_checkpoint_json_sha256", "final_digests", "initial_digests", "ckpt_000102400_digests",
                "rows_at_102400_sha256", "final_evaluation_sha256", "decision_inputs")
        if not now["ok"] or any(now.get(k) != want.get(k) for k in keys):
            p.append(f"historical control seed {s} changed since the manifest or no longer verifies: {now['problems'][:2]}")
    return p


def cmd_control_check(args: argparse.Namespace) -> int:
    import m7n_control_check as cc

    manifest = load_manifest(freeze=False)
    drift = nm.manifest_drift(manifest)
    if drift:
        for p in drift:
            log(f"BLOCKED {p}")
        return EXIT_FAILED
    if args.dry_run:
        log("dry run: R1 (3 x 102,400, reward v2) -> R2 (600 episodes) -> R1 vs Phase K pins -> R3 -> R4 (gate-2 inputs)")
        return EXIT_OK
    if args.record_only:
        # a check already run by rl/m7n_control_check.py on the final code: record it in the campaign state iff it binds
        rc = 0 if (nm.control_record() or {}).get("ok") else 1
    else:
        rc = cc.main(["--seeds", args.seeds])
    state = load_state()
    rec = nm.control_record() or {}
    state.setdefault("control", {})["check"] = {k: rec.get(k) for k in ("utc", "ok", "out", "executable_sha256")} | {
        "code_sha256": (rec.get("code") or {}).get("sha256")}
    event(state, "control_check", ok=rec.get("ok"), problems=(rec.get("problems") or [])[:5], exit=rc)
    bound = control_check_problems(manifest)
    log(f"control check exit {rc}; bound to the manifest: {'yes' if not bound else bound[:2]}")
    return EXIT_OK if rc == 0 and not bound else EXIT_FAILED


# -- training ---------------------------------------------------------------------------------------------------------


def run_status(spec: nm.RunSpec, state: Mapping[str, Any]) -> str:
    if (((state.get("runs") or {}).get(spec.name) or {}).get("status")) == "verified":
        return "verified"
    if not spec.run_dir.exists():
        return "absent"
    summ = spec.run_dir / "training_summary.json"
    if summ.is_file() and nm.read_json(summ).get("status") == "completed":
        return "completed_unverified"
    return "partial"


def train_plan(specs: Sequence[nm.RunSpec], state: Mapping[str, Any]) -> List[Dict[str, Any]]:
    plan: List[Dict[str, Any]] = []
    blocked = False
    for spec in specs:
        stt = run_status(spec, state)
        if stt == "verified":
            plan.append({"run": spec.name, "status": stt, "action": "skip"})
            continue
        if blocked:
            plan.append({"run": spec.name, "status": stt, "action": "wait (an earlier run is not verified)"})
            continue
        if stt == "completed_unverified":
            action = "verify the completed directory (never retrained)"
        elif stt == "partial":
            action = "STOP: a partial run directory exists (preserved; this milestone never resumes or relaunches)"
        else:
            action = "train from scratch"
        if (((state.get("runs") or {}).get(spec.name) or {}).get("status")) in ("stopped", "failed",
                                                                               "verification_failed", "gate_refused"):
            action = f"STOP: {spec.name} was {state['runs'][spec.name]['status']} (preserved; not relaunched)"
        plan.append({"run": spec.name, "status": stt, "action": action})
        blocked = True
    return plan


def preflight_run(spec: nm.RunSpec, exp: ec.Experiment, manifest: Mapping[str, Any]) -> Dict[str, Any]:
    checks = nm.arm_checks(spec, exp)
    p = [f"{spec.name}: {k}" for k, ok in checks.items() if not ok]
    r = (manifest.get("runs") or {}).get(spec.name)
    if r is None:
        p.append(f"{spec.name}: not in the manifest")
    else:
        if (r["source_sha256"], r["semantic_fingerprint"], r["compatibility_fingerprint"]) != \
                (exp.source.sha256, exp.semantic_fingerprint, exp.compatibility_fingerprint):
            p.append(f"{spec.name}: profile differs from the manifest")
        if not r.get("expected_initial_policy_digest"):
            p.append(f"{spec.name}: no expected untrained-model digest in the manifest")
        if not (r.get("phase_k_proof") or {}).get("ok"):
            p.append(f"{spec.name}: the Phase K comparison proof failed")
    return {"run": spec.name, "checks": checks, "problems": p, "ok": not p}


def run_identity(run_dir: Path, manifest: Mapping[str, Any]) -> List[str]:
    from btt_rewards import REWARD_V2

    rj = nm.read_json(run_dir / "run.json")
    p: List[str] = []
    if (rj.get("executable") or {}).get("sha256") != (manifest.get("executable") or {}).get("sha256"):
        p.append("run.json executable differs from the manifest")
    rev, mrev = rj.get("revisions") or {}, manifest.get("revisions") or {}
    if rev.get("head") != mrev.get("head") or {s["path"]: s["commit"] for s in rev.get("submodules") or []} != \
            mrev.get("submodules"):
        p.append("run.json revisions differ from the manifest")
    c = rj.get("contracts") or {}
    if c.get("policy_observation_contract") != mn.OBS_CONTRACT or c.get("policy_observation_contract_sha256") != mn.contract_digest():
        p.append("run.json observation contract / digest")
    if c.get("action_class_table_sha256") != st.load_table()["sha256"]:
        p.append("run.json action-class table")
    net = rj.get("policy_network") or {}
    if (rj.get("ppo") or {}).get("policy") != mnp.POLICY or net.get("network_id") != mnp.NETWORK_ID:
        p.append("run.json policy / network")
    if rj.get("reward_contract") != REWARD_V2.to_json():
        p.append("run.json reward contract is not btt_reward_v2")
    if dict(rj.get("m6_flags") or {}) != nm.V3_FLAGS:
        p.append(f"run.json native flags {rj.get('m6_flags')}")
    if rj.get("lineage"):
        p.append(f"not a fresh model: lineage {rj.get('lineage')}")
    if (rj.get("config") or {}).get("curriculum") is not None or (run_dir / "curriculum").exists():
        p.append("a curriculum trace")
    return p


def verify_run(spec: nm.RunSpec, exp: ec.Experiment, manifest: Mapping[str, Any]) -> Dict[str, Any]:
    r = (manifest.get("runs") or {}).get(spec.name) or {}
    expected = (r.get("expected_initial_policy_digest"), r.get("expected_initial_obs_rms_digest"))
    ver = dr.verify_training_run(spec.run_dir, exp, fresh=True, expected_initial=expected)
    ident = run_identity(spec.run_dir, manifest)
    ver["m7n_identity"] = ident
    if ident:
        ver["problems"].extend(ident)
        ver["ok"] = False
    return ver


def _guarded_launch(*, spec: nm.RunSpec, exp: ec.Experiment, **_: Any) -> Dict[str, Any]:
    tag = f"{spec.name}__{stamp()}"
    return g.train_guarded(config=spec.config_path, run_dir=spec.run_dir, log_path=nm.guard_root() / "logs" / f"{tag}.log",
                           monitor_path=nm.guard_root() / "monitor" / f"{tag}.jsonl",
                           probe_path=nm.guard_root() / "probe" / f"{tag}.jsonl", contract=exp.reward,
                           horizon=int(exp.values["environment.horizon"]), partial_root=nm.partial_root(),
                           output_root=None if nm.root() == nm.DEFAULT_ROOT else spec.run_dir.parent)


def cmd_train(args: argparse.Namespace) -> int:
    state = load_state()
    specs = nm.matrix()
    manifest = load_manifest(freeze=not args.dry_run)
    drift = nm.manifest_drift(manifest)
    plan = train_plan(specs, state)
    report: Dict[str, Any] = {"dry_run": bool(args.dry_run), "plan": plan, "manifest_drift": drift,
                              "control_check": control_check_problems(manifest),
                              "preflight": {s.name: preflight_run(s, nm.load_run(s), manifest) for s in specs},
                              "directory_plan": nm.check_directory_plan(),
                              "approval": (manifest.get("authority") or {}).get("approval")}
    first = next((s for s in plan if s["action"] != "skip"), None)
    need_gate = first is not None and first["action"].startswith("train")
    report["resources"] = wait_for_launch_gate("preflight") if need_gate and not args.skip_resource_gate else None
    blocking = drift + report["control_check"] + [p for pf in report["preflight"].values() for p in pf["problems"]] + \
        report["directory_plan"]["problems"] + ([] if report["resources"] is None else report["resources"]["problems"] or [])
    appr = nm.approval_status((manifest.get("decision_rule") or {}).get("sha256") or "")
    report["approval_now"] = appr["approval"]
    if not str(report["approval"] or "").startswith("APPROVED"):
        blocking.append(f"the manifest's authority.approval is not APPROVED: {report['approval']}")
    pinned = ((manifest.get("authority") or {}).get("approval_record") or {}).get("sha256")
    if not str(appr["approval"]).startswith("APPROVED") or (appr.get("record") or {}).get("sha256") != pinned:
        blocking.append(f"the approval record does not authorise this manifest now: {appr['approval']}")
    report["blocking_problems"] = blocking
    if args.dry_run:
        print(json.dumps(report, indent=1, default=str), flush=True)
        log(f"dry run: nothing launched, nothing written; blocking problems {len(blocking)}")
        return EXIT_OK if not blocking else EXIT_FAILED
    if blocking:
        for p in blocking:
            log(f"BLOCKED {p}")
        event(state, "train_blocked", problems=blocking[:20])
        return EXIT_FAILED
    event(state, "train_invocation", plan=plan, resources=report["resources"])
    launcher = LAUNCHER or _guarded_launch
    handled: set = set()
    first_launch = True
    while True:
        step = next((s for s in train_plan(specs, state) if s["action"] != "skip"), None)
        if step is None:
            log("every run of this matrix is verified")
            return EXIT_OK
        spec = nm.run_by_name(step["run"])
        action = step["action"]
        if action.startswith(("STOP", "wait")):
            log(f"{spec.name}: {action}")
            return EXIT_FAILED if action.startswith("STOP") else EXIT_OK
        if spec.name in handled:
            log(f"{spec.name}: not verified after this invocation's attempt; stopping")
            return EXIT_FAILED
        handled.add(spec.name)
        exp = nm.load_run(spec)
        rs = state["runs"].setdefault(spec.name, {"status": "pending", "attempts": []})
        if action.startswith("verify"):
            ver = verify_run(spec, exp, manifest)
            nm.write_json(nm.state_dir() / "verify" / f"{spec.name}.json", ver)
            rs.update(status="verified" if ver["ok"] else "verification_failed", verification=ver["problems"][:20])
            save_state(state)
            if not ver["ok"]:
                log(f"{spec.name}: verification FAILED {ver['problems'][:3]}")
                return EXIT_FAILED
            continue
        drift = nm.manifest_drift(manifest)
        if drift:
            event(state, "drift_before_launch", run=spec.name, drift=drift)
            log(f"{spec.name}: manifest drift {drift}; stopping")
            return EXIT_FAILED
        leftover = dr.system_state(label=f"before {spec.name}")["battleship_pids"]
        if leftover:
            event(state, "process_before_launch", run=spec.name, pids=leftover)
            log(f"{spec.name}: BattleShip already running {leftover}; stopping")
            return EXIT_FAILED
        if not first_launch and not args.skip_resource_gate:
            gate = wait_for_launch_gate(spec.name)
            rs["launch_gate"] = gate
            if not gate["ok"]:
                rs["status"] = "gate_refused"
                event(state, "launch_gate_refused", run=spec.name, gate=gate)
                log(f"{spec.name}: launch gate refused {gate['problems']}; stopping")
                return EXIT_FAILED
        elif report["resources"] is not None:
            rs["launch_gate"] = report["resources"]
        first_launch = False
        log(f"{spec.name}: launching (seed {spec.seed}, {nm.TOTAL_TRANSITIONS:,} policy transitions, {mn.OBS_CONTRACT})")
        t0 = time.perf_counter()
        res = launcher(spec=spec, exp=exp, manifest=manifest)
        attempt = {"utc": utc_now(), "wall_s": round(time.perf_counter() - t0, 1), "exit_code": res.get("exit_code"),
                   "stop_kind": res.get("stop_kind"), "moved_to": res.get("moved_to"),
                   "probe": {k: (res.get("probe") or {}).get(k) for k in ("min_avail_commit_gib", "min_avail_phys_gib",
                                                                           "samples_physical_below_launch_gate",
                                                                           "max_commit_used_gib")},
                   "commit_drawn_gib": res.get("commit_drawn_gib"),
                   "leftover_battleship_pids": res.get("leftover_battleship_pids"),
                   "monitor": {k: (res.get("monitor") or {}).get(k) for k in (
                       "max_battleship_processes", "max_battleship_listeners", "hard_alerts", "soft_alert_count",
                       "episodes_seen", "episode_ends", "lifecycle_failures")},
                   "log": ec.repo_relative(Path(res["log"])) if res.get("log") else None}
        rs.setdefault("attempts", []).append(attempt)
        if res.get("stop_kind"):
            rs["status"] = "stopped"
            event(state, "run_stopped", run=spec.name, stop_kind=res["stop_kind"], moved_to=res.get("moved_to"))
            log(f"{spec.name}: STOPPED ({res['stop_kind']}); preserved at {res.get('moved_to')}; the campaign stops")
            return EXIT_INTERRUPTED
        if res.get("exit_code") != 0:
            rs["status"] = "failed"
            save_state(state)
            log(f"{spec.name}: trainer exit {res.get('exit_code')}; the directory stays (partial); see the guard log")
            return EXIT_FAILED
        if res.get("leftover_battleship_pids"):
            rs["status"] = "failed"
            event(state, "process_leak", run=spec.name, pids=res["leftover_battleship_pids"])
            log(f"{spec.name}: BattleShip processes left after the run {res['leftover_battleship_pids']}; stopping")
            return EXIT_FAILED
        ver = verify_run(spec, exp, manifest)
        nm.write_json(nm.state_dir() / "verify" / f"{spec.name}.json", ver)
        rs.update(status="verified" if ver["ok"] else "verification_failed", verification=ver["problems"][:20])
        save_state(state)
        if not ver["ok"]:
            log(f"{spec.name}: verification FAILED {ver['problems'][:3]}")
            return EXIT_FAILED
        log(f"{spec.name}: verified")


# -- evaluation (tick-0 only) ------------------------------------------------------------------------------------------


def checkpoint_for(spec: nm.RunSpec, label: str, t: int) -> Path:
    return spec.run_dir / "final" if label == "final" else spec.run_dir / "checkpoints" / f"ckpt_{t:09d}"


def checkpoint_provenance(ckpt: Path, spec: nm.RunSpec, exp: ec.Experiment, planned_t: int,
                          manifest: Mapping[str, Any]) -> List[str]:
    """Is this checkpoint set exactly the planned point of this run (arm, seed, profile, executable, revisions,
    the v3 network identity, the standby lifecycle)?"""
    import m7_trainer as tr
    from m7_evaluation import CheckpointError, read_checkpoint_set

    try:
        meta = read_checkpoint_set(ckpt, expected_contracts=tr.run_contracts(tr.config_from_experiment(exp)))
    except CheckpointError as exc:
        return [f"{ckpt.name}: {exc}"]
    p: List[str] = []
    if meta.get("run_id") != spec.name:
        p.append(f"run_id {meta.get('run_id')!r} is not {spec.name}")
    if int(meta.get("num_timesteps", -1)) != int(planned_t):
        p.append(f"num_timesteps {meta.get('num_timesteps')} != planned {planned_t}")
    block = meta.get("experiment") or {}
    if (block.get("semantic_fingerprint"), block.get("compatibility_fingerprint")) != \
            (exp.semantic_fingerprint, exp.compatibility_fingerprint):
        p.append("experiment fingerprints differ from the profile")
    if (meta.get("seeds") or {}).get("base_seed") != spec.seed:
        p.append(f"base_seed {(meta.get('seeds') or {}).get('base_seed')} != {spec.seed}")
    if (meta.get("executable") or {}).get("sha256") != (manifest.get("executable") or {}).get("sha256"):
        p.append("executable sha256 differs from the manifest")
    rev, mrev = meta.get("revisions") or {}, manifest.get("revisions") or {}
    if rev.get("head") != mrev.get("head") or {s["path"]: s["commit"] for s in rev.get("submodules") or []} != \
            mrev.get("submodules"):
        p.append("revisions differ from the manifest")
    if (meta.get("ppo") or {}).get("policy") != mnp.POLICY or (meta.get("policy_network") or {}).get("network_id") != mnp.NETWORK_ID:
        p.append("policy / network identity")
    if (meta.get("vecnormalize") or {}).get("norm_obs") is not False:
        p.append("vecnormalize norm_obs is not False")
    lc = meta.get("lifecycle") or {}
    if (lc.get("standby_preboot"), lc.get("standby_count")) != (True, 1):
        p.append(f"lifecycle {lc}")
    if meta.get("lineage") or meta.get("interruption"):
        p.append("lineage / interruption present")
    return p


def run_eval_label(state: Dict[str, Any], key: str, out_dir: Path, fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    import m7g_k_run as kr   # measurement only (preconditions)
    from m7_runtime import BATTLESHIP_IMAGE, wait_until_no_process

    done = out_dir / "evaluation_summary.json"
    if done.is_file():
        return nm.read_json(done)
    if out_dir.exists():
        aside = out_dir.with_name(out_dir.name + "__incomplete_" + stamp())
        out_dir.rename(aside)
        event(state, "incomplete_evaluation_moved_aside", key=key, to=ec.repo_relative(aside))
    pre = kr.preconditions(f"before evaluation {key}")
    if pre["problems"]:
        raise nm.MatrixError(f"evaluation {key}: preconditions failed: {pre['problems']}")
    monitor = dr.Monitor(out=nm.state_dir() / "monitor" / "evaluation.jsonl", root_pid=os.getpid()).start()
    t0 = time.perf_counter()
    try:
        result = fn()
    finally:
        mon = monitor.stop()
    leftover = wait_until_no_process(BATTLESHIP_IMAGE, timeout=30.0)
    state.setdefault("evaluations", {}).setdefault(key, {}).update(
        wall_s=round(time.perf_counter() - t0, 1), finished_utc=utc_now(), leak_free=not leftover,
        monitor_hard_alerts=mon.get("hard_alerts"), max_battleship_processes=mon.get("max_battleship_processes"),
        out_dir=ec.repo_relative(out_dir))
    save_state(state)
    if mon.get("hard_alerts") or leftover:
        raise nm.MatrixError(f"evaluation {key}: monitor alerts {mon.get('hard_alerts')} / leaked {leftover}")
    return result


def evaluate_label(state: Dict[str, Any], spec: nm.RunSpec, exp: ec.Experiment, plan: Mapping[str, Any],
                   manifest: Mapping[str, Any], *, dry_run: bool = False) -> Dict[str, Any]:
    import m7_evaluation as ev
    import m7_trainer as tr
    import m7g_k_run as kr   # pure helpers only: phase_k_settings, verify_metrics
    import m7h_verify as mv

    key = f"{spec.name}:{plan['label']}"
    ckpt = checkpoint_for(spec, plan["label"], int(plan["num_timesteps"]))
    prov = checkpoint_provenance(ckpt, spec, exp, int(plan["num_timesteps"]), manifest)
    if prov or dry_run:
        return {"key": key, "checkpoint": ec.repo_relative(ckpt), "provenance_problems": prov, "ran": False}
    out = spec.eval_dir / plan["label"]
    settings = kr.phase_k_settings(exp)
    cfg = tr.config_from_experiment(exp)
    res = run_eval_label(state, key, out, lambda: ev.evaluate_checkpoint(
        ckpt, out, settings=settings, deterministic_episodes=int(plan["deterministic_episodes"]),
        stochastic_episodes=int(plan["stochastic_episodes"]), expected_contracts=tr.run_contracts(cfg),
        label=plan["label"], preserve_all=True))
    ver = dr.verify_evaluation(res, exp.reward, int(exp.values["environment.horizon"]), plan)
    ver["problems"].extend(kr.verify_metrics(res, arm=None))
    want_flags = dict(nm.V3_FLAGS, **nm.DIAG_FLAG)
    for mode, r in (res.get("modes") or {}).items():
        if dict(r.get("extra_env") or {}) != want_flags:
            ver["problems"].append(f"{mode}: evaluation flags {r.get('extra_env')}")
    if res.get("policy_observation_contract") != mn.OBS_CONTRACT:
        ver["problems"].append(f"evaluated under {res.get('policy_observation_contract')}")
    t0 = mv.verify_eval_tick0(out)
    ver["tick0"] = {k: t0[k] for k in ("ok", "problems", "artifacts", "rows")}
    ver["problems"].extend(f"tick0: {x}" for x in t0["problems"])
    ver["ok"] = not ver["problems"]
    nm.write_json(nm.state_dir() / "verify_eval" / f"{spec.name}__{plan['label']}.json", ver)
    state["evaluations"][key].update(verification=ver["problems"][:20], ok=ver["ok"], tick0_ok=t0["ok"],
                                     checkpoint=ec.repo_relative(ckpt), num_timesteps=int(plan["num_timesteps"]))
    save_state(state)
    return {"key": key, "checkpoint": ec.repo_relative(ckpt), "provenance_problems": [], "ran": True, "verification": ver}


def post_training_gate() -> Optional[Dict[str, Any]]:
    manifest = load_manifest(freeze=False)
    drift = nm.manifest_drift(manifest)
    if drift:
        for p in drift:
            log(f"BLOCKED {p}")
        return None
    return manifest


def cmd_evaluate(args: argparse.Namespace) -> int:
    state = load_state()
    manifest = post_training_gate()
    if manifest is None:
        return EXIT_FAILED
    if not args.dry_run:
        from m7_runtime import install_kill_on_close_job

        install_kill_on_close_job()
    report: List[Dict[str, Any]] = []
    for spec in nm.matrix():
        if ((state.get("runs") or {}).get(spec.name) or {}).get("status") != "verified":
            report.append({"run": spec.name, "skipped": "training not verified"})
            if not args.dry_run:
                log(f"{spec.name}: training not verified; evaluation stops")
                return EXIT_FAILED
            continue
        exp = nm.load_run(spec)
        for plan in nm.evaluation_plan(spec, exp):
            ev_state = (state.get("evaluations") or {}).get(f"{spec.name}:{plan['label']}") or {}
            if ev_state.get("ok") and ev_state.get("tick0_ok"):
                continue
            r = evaluate_label(state, spec, exp, plan, manifest, dry_run=args.dry_run)
            report.append({k: v for k, v in r.items() if k != "verification"})
            if r["provenance_problems"]:
                log(f"{r['key']}: provenance REFUSED {r['provenance_problems'][:3]}")
                if not args.dry_run:
                    event(state, "provenance_refused", key=r["key"], problems=r["provenance_problems"][:5])
                    return EXIT_FAILED
            elif r.get("ran"):
                v = r["verification"]
                log(f"{r['key']}: {'verified' if v['ok'] else 'PROBLEMS ' + str(v['problems'][:3])}")
                if not v["ok"]:
                    return EXIT_FAILED
    if args.dry_run:
        print(json.dumps({"dry_run": True, "labels": report}, indent=1, default=str), flush=True)
    return EXIT_OK


# -- clears -------------------------------------------------------------------------------------------------------------


def cmd_verify_clears(args: argparse.Namespace) -> int:  # noqa: ARG001
    import m7g_k_run as kr
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    state = load_state()
    if post_training_gate() is None:
        return EXIT_FAILED
    ok = True
    for spec in nm.matrix():
        if not spec.eval_dir.is_dir():
            continue
        exp = nm.load_run(spec)
        for label_dir in sorted(p for p in spec.eval_dir.iterdir() if p.is_dir() and "__incomplete_" not in p.name):
            key = f"{spec.name}:{label_dir.name}"
            if key in (state.get("clears") or {}):
                continue
            doc = kr.verify_clears_in(label_dir, spec.clears_dir / label_dir.name, executable=exp.executable,
                                      extra_env=dict(exp.extra_env))
            state.setdefault("clears", {})[key] = {"candidates": doc["candidates"], "verified": doc["verified"]}
            save_state(state)
            if doc["candidates"]:
                log(f"{key}: {doc['verified']}/{doc['candidates']} clears verified")
                ok &= doc["verified"] == doc["candidates"]
        rows, _ = dr.jsonl_rows(spec.run_dir / "metrics" / "episodes.jsonl")
        tc = [r for r in rows if r.get("cleared")]
        recs = []
        for k, r in enumerate(tc):
            rec = {"episode_id": r["episode_id"], "artifact_dir": r.get("artifact_dir"), "verified": None}
            if r.get("artifact_dir"):
                art = Path(r["artifact_dir"])
                art = art if art.is_absolute() else REPO_ROOT / art
                rr = dr.replay_one(art, spec.clears_dir / "training" / f"replay_{k:03d}", executable=exp.executable,
                                   extra_env=dict(exp.extra_env), index=9600 + k)
                rec["verified"] = bool(rr.get("ok") and (rr.get("checks") or {}).get("completion_clocks")
                                       and (rr.get("checks") or {}).get("native_clear"))
                rec["checks"] = rr.get("checks")
            recs.append(rec)
        state.setdefault("clears", {})[f"{spec.name}:training"] = {"candidates": len(tc), "records": recs}
        save_state(state)
        if tc:
            log(f"{spec.name}: {len(tc)} native clears during training; replay results {[r['verified'] for r in recs]}")
    return EXIT_OK if ok else EXIT_FAILED


# -- gate-2 inputs: crossings and left-target breaks, both arms ---------------------------------------------------------


def control_crossing_dir(seed: int) -> Path:
    return nm.clears_root() / "control" / nm.HistoricalControl(seed).name / "final"


def crossing_jobs() -> List[Dict[str, Any]]:
    """One job per final label of both arms: v3 under its own evaluation flags + the target diagnostic, the control
    under the M6 flags + the target diagnostic; the same executable, the same criterion, the same code."""
    exe = nm.load_run(nm.matrix()[0]).executable
    jobs = []
    for spec in nm.matrix():
        exp = nm.load_run(spec)
        jobs.append({"key": f"{spec.name}:final", "arm": "v3", "seed": spec.seed, "label_dir": spec.eval_dir / "final",
                     "out_dir": spec.clears_dir / "final", "executable": exp.executable,
                     "flags": dict(exp.extra_env, **nm.DIAG_FLAG), "index_base": 9800 + 20 * spec.seed})
    for s in nm.SEEDS:
        h = nm.HistoricalControl(s)
        jobs.append({"key": f"{h.name}:final", "arm": "v1", "seed": s, "label_dir": h.eval_dir / "final",
                     "out_dir": control_crossing_dir(s), "executable": exe,
                     "flags": dict(nm.M6_FLAGS, **nm.DIAG_FLAG), "index_base": 9900 + 20 * s})
    return jobs


def cmd_verify_crossings(args: argparse.Namespace) -> int:  # noqa: ARG001
    from m7_runtime import BATTLESHIP_IMAGE, install_kill_on_close_job, wait_until_no_process

    install_kill_on_close_job()
    state = load_state()
    if post_training_gate() is None:
        return EXIT_FAILED
    ok = True
    for job in crossing_jobs():
        key = job["key"]
        if key in (state.get("crossings") or {}):
            continue
        if not (job["label_dir"] / "stochastic" / "evaluation.json").is_file():
            log(f"{key}: no final evaluation; crossing verification stops")
            return EXIT_FAILED
        docp = job["out_dir"] / "crossing_verification.json"
        if docp.is_file():
            raise nm.MatrixError(f"{ec.repo_relative(docp)} exists without a state entry (never overwritten)")
        t0 = time.perf_counter()
        doc = xc.verify_crossings_in(job["label_dir"], job["out_dir"], executable=job["executable"], extra_env=job["flags"],
                                     index_base=int(job["index_base"]))
        leftover = wait_until_no_process(BATTLESHIP_IMAGE, timeout=30.0)
        rec = {k: doc[k] for k in ("candidates", "exact", "qualified_crossings", "verified_left_target_episodes",
                                   "unqualified_left_entries", "X", "ok")}
        rec.update(arm=job["arm"], seed=job["seed"], problems=list(doc["problems"])[:10], doc=ec.repo_relative(docp),
                   wall_s=round(time.perf_counter() - t0, 1), leak_free=not leftover)
        state.setdefault("crossings", {})[key] = rec
        save_state(state)
        log(f"{key}: {doc['candidates']} candidate(s), {doc['exact']} exact, {doc['qualified_crossings']} qualified crossing(s), "
            f"{doc['verified_left_target_episodes']} left-target break(s), X = {doc['X']}"
            + ("" if doc["ok"] else f" PROBLEMS {doc['problems'][:2]}") + (f" LEAK {leftover}" if leftover else ""))
        if leftover:
            event(state, "process_leak", key=key, pids=leftover)
            return EXIT_FAILED
        ok &= bool(doc["ok"])
    r4 = ((nm.control_record() or {}).get("r4") or {}).get("per_seed") or {}
    for s in nm.SEEDS:
        key = f"{nm.HistoricalControl(s).name}:final"
        got = (state.get("crossings") or {}).get(key) or {}
        want = r4.get(str(s)) or {}
        if (got.get("candidates"), got.get("X")) != (want.get("candidates"), want.get("X")):
            log(f"{key}: gate-2 inputs (candidates {got.get('candidates')}, X {got.get('X')}) differ from the control "
                f"check's R4 ({want.get('candidates')}, {want.get('X')}); integrity")
            ok = False
    return EXIT_OK if ok else EXIT_FAILED


# -- census, analysis -------------------------------------------------------------------------------------------------


def census() -> Dict[str, Any]:
    rows, missing, executed = [], [], 0
    for spec in nm.matrix():
        exp = nm.load_run(spec)
        for p in nm.evaluation_plan(spec, exp):
            s = spec.eval_dir / p["label"] / "evaluation_summary.json"
            got = {"deterministic": 0, "stochastic": 0}
            if s.is_file():
                doc = nm.read_json(s)
                got = {m: len(((doc.get("modes") or {}).get(m) or {}).get("episodes") or []) for m in got}
            complete = got == {"deterministic": int(p["deterministic_episodes"]), "stochastic": int(p["stochastic_episodes"])}
            executed += sum(got.values())
            rows.append({"run": spec.name, "label": p["label"], "executed": got, "complete": complete})
            if not complete:
                missing.append(f"{spec.name}:{p['label']} executed {got}")
    return {"plan": nm.census_plan(), "rows": rows, "executed_episodes": executed, "missing": missing,
            "complete": not missing}


def cmd_census(args: argparse.Namespace) -> int:  # noqa: ARG001
    c = census()
    log(f"planned {c['plan']['episodes']} ({c['plan']['arithmetic']}); executed {c['executed_episodes']}; missing "
        f"{len(c['missing'])}")
    return EXIT_OK if c["complete"] else EXIT_FAILED


def label_curve(eval_dir: Path, labels: Sequence[str], P: Mapping[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for lab in labels:
        rows = la.read_label(eval_dir / lab)
        sto = rows["stochastic"]
        if not sto:
            continue
        facts = [la.episode_facts(e, P)[0] for e in sto]
        det = [la.episode_facts(e, P)[0] for e in rows["deterministic"]]
        n = len(facts)
        out.append({"label": lab, "stochastic": n, "targets_mean": round(sum(f["targets"] for f in facts) / n, 4),
                    "targets_max": max(f["targets"] for f in facts), "t2": sum(f["t2"] for f in facts),
                    "L": sum(f["L"] for f in facts), "R": sum(f["R"] for f in facts),
                    "falls": sum(f["fall"] for f in facts), "clears_native": sum(f["cleared"] for f in facts + det),
                    "left_entries": sum(f["left_entry"] for f in facts),
                    "left_target_episodes": sum(1 for f in facts if f["left_ids"]),
                    "seven_right": sum(f["seven_right"] for f in facts),
                    "deterministic_targets": sorted({f["targets"] for f in det})})
    return out


def training_facts(run_dir: Path) -> Dict[str, Any]:
    summ = nm.read_json(run_dir / "training_summary.json") if (run_dir / "training_summary.json").is_file() else {}
    rows, _ = dr.jsonl_rows(run_dir / "metrics" / "episodes.jsonl")
    return {"episodes": len(rows), "falls": sum(1 for r in rows if r.get("end_reason") == "fall"),
            "clears": sum(1 for r in rows if r.get("cleared")),
            "mean_targets": round(sum(int(r["targets_broken"]) for r in rows) / len(rows), 4) if rows else None,
            "throughput": summ.get("throughput"), "wall": summ.get("wall"), "cleanup": summ.get("cleanup"),
            "status": summ.get("status")}


def build_report(state: Mapping[str, Any], manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """The rule inputs (v1 finals, v3 finals, v3 initials), `pending` (steps not done: analyze refuses and records
    nothing), `integrity` (gate 0) and `incomplete` (no decision)."""
    rule = na.load_rule()
    P = na.params(rule)
    pending: List[str] = []
    integrity: List[str] = list(control_check_problems(manifest))
    incomplete: List[str] = []
    specs = nm.matrix()
    for spec in specs:
        stt = ((state.get("runs") or {}).get(spec.name) or {}).get("status")
        if stt == "verification_failed":
            integrity.append(f"{spec.name}: training verification failed")
        elif stt in ("stopped", "failed", "gate_refused"):
            incomplete.append(f"{spec.name}: training {stt} (preserved, never resumed)")
        elif stt != "verified":
            pending.append(f"{spec.name}: training not finished ({stt})")
    c = census()
    if not c["complete"]:
        pending.append(f"census incomplete: {len(c['missing'])} labels ({c['missing'][:2]})")
    for spec in specs:
        for plan in nm.evaluation_plan(spec, nm.load_run(spec)):
            key = f"{spec.name}:{plan['label']}"
            evs = (state.get("evaluations") or {}).get(key) or {}
            if "tick0_ok" not in evs:
                pending.append(f"{key}: evaluation not verified")
            elif not evs["tick0_ok"] or not evs.get("ok", False):
                integrity.append(f"{key}: evaluation verification failed (tick-0 {evs['tick0_ok']})")
            cl = (state.get("clears") or {}).get(key)
            if cl is None:
                pending.append(f"{key}: clear verification not run")
            elif cl["verified"] != cl["candidates"]:
                integrity.append(f"{key}: {cl['verified']}/{cl['candidates']} native clears verified")
    inputs: Dict[str, Any] = {"v1": {}, "v3": {}, "v3_initial": {}, "crossings": {"v1": {}, "v3": {}},
                              "integrity": integrity, "incomplete": incomplete}
    r4 = ((nm.control_record() or {}).get("r4") or {}).get("per_seed") or {}
    per_seed: Dict[str, Any] = {}
    labels = [p["label"] for p in nm.evaluation_plan(specs[0], nm.load_run(specs[0]))]
    for spec in specs:
        s = spec.seed
        h = nm.HistoricalControl(s)
        entry: Dict[str, Any] = {}
        sources = (
            ("v1", h.eval_dir / "final", h.clears_dir / "final" / "clear_verification.json"),
            ("v3", spec.eval_dir / "final", spec.clears_dir / "final" / "clear_verification.json"),
            ("v3_initial", spec.eval_dir / "initial", spec.clears_dir / "initial" / "clear_verification.json"),
        )
        for arm, label_dir, cd in sources:
            if not (label_dir / "stochastic" / "evaluation.json").is_file():
                continue
            a, probs = la.label_inputs(label_dir, nm.read_json(cd) if cd.is_file() else None, P)
            inputs[arm][s] = a
            integrity.extend(f"{arm} s{s}: {x}" for x in probs)
            entry[arm] = {"stochastic": a.to_json(), "t2_timing": la.t2_timing(a.t2_ticks),
                          "deterministic": la.deterministic_facts(label_dir, P)}
        for arm, label_dir, out_dir, key in (("v1", h.eval_dir / "final", control_crossing_dir(s), f"{h.name}:final"),
                                             ("v3", spec.eval_dir / "final", spec.clears_dir / "final", f"{spec.name}:final")):
            if not (label_dir / "stochastic" / "evaluation.json").is_file():
                continue
            docp = out_dir / "crossing_verification.json"
            if not docp.is_file():
                pending.append(f"{key}: crossing verification not run")
                continue
            doc = nm.read_json(docp)
            ci, probs = xc.crossing_inputs(label_dir, doc)
            inputs["crossings"][arm][s] = ci
            integrity.extend(f"{arm} s{s}: {x}" for x in probs)
            entry.setdefault(arm, {})["crossings"] = dict(ci.to_json(), doc=ec.repo_relative(docp), records=[
                {k: r.get(k) for k in ("episode_id", "reasons", "qualified_crossing", "verified_left_target_break",
                                       "unqualified_left_entry")}
                | {"exact": (r.get("exact") or {}).get("ok"), "route": ((r.get("analysis") or {}).get("route") or {}).get("identity"),
                   "entries": [{k2: e.get(k2) for k2 in ("consumed_tick", "class", "y_c", "sweep_complete_at_entry", "qualified")}
                               | {"landing": (e.get("landing") or {}).get("surface")} for e in (r.get("analysis") or {}).get("entries") or []],
                   "left_target_breaks": (r.get("analysis") or {}).get("left_target_breaks")}
                for r in doc.get("records") or []])
            entry[arm]["X"] = ci.X
            if arm == "v1":
                want = r4.get(str(s)) or {}
                if (ci.candidates, ci.X) != (want.get("candidates"), want.get("X")):
                    integrity.append(f"v1 s{s}: gate-2 inputs ({ci.candidates}, X {ci.X}) differ from the control check's R4 "
                                     f"({want.get('candidates')}, {want.get('X')})")
        if "v3" in entry:
            entry["v3"]["curve"] = label_curve(spec.eval_dir, labels, P)
        if "v1" in entry:
            entry["v1"]["curve"] = label_curve(h.eval_dir, labels, P)
        entry["training_v3"] = training_facts(spec.run_dir) if spec.run_dir.is_dir() else None
        entry["training_attempts_v3"] = ((state.get("runs") or {}).get(spec.name) or {}).get("attempts")
        per_seed[str(s)] = entry
    evals = {k: {x: v.get(x) for x in ("wall_s", "leak_free", "max_battleship_processes")}
             for k, v in (state.get("evaluations") or {}).items()}
    return {"inputs": inputs, "per_seed": per_seed, "census": {k: c[k] for k in ("plan", "executed_episodes", "missing",
                                                                                "complete")},
            "clears": state.get("clears"), "evaluations": evals, "integrity": integrity, "incomplete": incomplete,
            "pending": pending}


def cmd_analyze(args: argparse.Namespace) -> int:
    state = load_state()
    manifest = post_training_gate()
    if manifest is None:
        return EXIT_FAILED
    rule = na.load_rule()
    if rule["_sha256"] != (manifest.get("decision_rule") or {}).get("sha256"):
        log("BLOCKED the decision rule differs from the registered one in the manifest")
        return EXIT_FAILED
    if "n3" in (state.get("decisions") or {}) and not args.dry_run:
        log(f"the n3 decision is already recorded ({state['decisions']['n3']['outcome']}); it is never re-decided")
        return EXIT_USAGE
    rep = build_report(state, manifest)
    if rep["pending"] and not args.dry_run:
        log(f"not ready to decide (nothing recorded): {len(rep['pending'])} pending, first {rep['pending'][:3]}")
        return EXIT_FAILED
    if rep["pending"]:
        log(f"dry run with {len(rep['pending'])} pending items: {rep['pending'][:3]}")
        print(json.dumps({"pending": rep["pending"], "integrity": rep["integrity"], "incomplete": rep["incomplete"]},
                         indent=1, default=str))
        return EXIT_OK
    d = na.decide(rep["inputs"], rule)
    doc = {"decision": d, "per_seed": rep["per_seed"], "census": rep["census"], "clears": rep["clears"],
           "evaluations": rep["evaluations"], "manifest_sha256": nm.sha256_file(frozen_manifest_path()),
           "utc": utc_now()}
    if args.dry_run:
        print(json.dumps(d, indent=1, default=str))
        return EXIT_OK
    out = nm.state_dir() / "analysis_n3.json"
    nm.write_json(out, doc)
    state.setdefault("decisions", {})["n3"] = {"outcome": d["outcome"], "gate": d.get("gate"), "name": d.get("name"),
                                               "decided": d.get("decided"), "gates": d.get("gates"),
                                               "response": d["response"], "utc": utc_now(),
                                               "report": ec.repo_relative(out)}
    save_state(state)
    log(f"decision at n = 3: {d['outcome']} (gate {d.get('gate')} {d.get('name')}): {d['response']}")
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:  # noqa: ARG001
    state = load_state()
    log(f"control check: {(state.get('control') or {}).get('check')}")
    for spec in nm.matrix():
        log(f"{spec.order_index} {spec.name}: {run_status(spec, state)}")
    log(f"evaluations verified: {sum(1 for v in (state.get('evaluations') or {}).values() if v.get('ok'))}; "
        f"crossing labels: {len(state.get('crossings') or {})}; decisions: {state.get('decisions')}")
    return EXIT_OK


def cmd_all(args: argparse.Namespace) -> int:  # noqa: ARG001
    for name, fn, ns in (("train", cmd_train, argparse.Namespace(dry_run=False, skip_resource_gate=False)),
                         ("evaluate", cmd_evaluate, argparse.Namespace(dry_run=False)),
                         ("verify-clears", cmd_verify_clears, argparse.Namespace()),
                         ("verify-crossings", cmd_verify_crossings, argparse.Namespace()),
                         ("analyze", cmd_analyze, argparse.Namespace(dry_run=False))):
        log(f"=== {name}")
        rc = fn(ns)
        if rc != EXIT_OK:
            log(f"=== {name} ended with exit {rc}; the campaign stops here")
            return rc
    return EXIT_OK


# -- CLI --------------------------------------------------------------------------------------------------------------


def _raise_keyboard_interrupt(signum, frame):  # noqa: ARG001
    raise KeyboardInterrupt(f"signal {signum}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    m = sub.add_parser("manifest")
    m.add_argument("--out", default=None)
    c = sub.add_parser("control-check")
    c.add_argument("--seeds", default="0,1,2")
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--record-only", action="store_true", help="record an existing passing rl/m7n_control_check.py run")
    for name in ("train", "preflight"):
        t = sub.add_parser(name)
        t.add_argument("--dry-run", action="store_true")
        t.add_argument("--skip-resource-gate", action="store_true", help="tests / dry runs only")
    e = sub.add_parser("evaluate")
    e.add_argument("--dry-run", action="store_true")
    sub.add_parser("verify-clears")
    sub.add_parser("verify-crossings")
    sub.add_parser("census")
    a = sub.add_parser("analyze")
    a.add_argument("--dry-run", action="store_true")
    sub.add_parser("status")
    sub.add_parser("all")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "preflight":
        args.dry_run = True
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _raise_keyboard_interrupt)
    fn = {"manifest": cmd_manifest, "control-check": cmd_control_check, "train": cmd_train, "preflight": cmd_train,
          "evaluate": cmd_evaluate, "verify-clears": cmd_verify_clears, "verify-crossings": cmd_verify_crossings,
          "census": cmd_census, "analyze": cmd_analyze,
          "status": cmd_status, "all": cmd_all}[args.command]
    try:
        return fn(args)
    except nm.MatrixError as exc:
        log(f"ERROR {exc}")
        return EXIT_FAILED
    except KeyboardInterrupt:
        log("interrupted")
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
