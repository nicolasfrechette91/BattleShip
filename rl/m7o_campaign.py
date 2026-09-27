"""M7o campaign driver: the controlled three-seed exploration-credit comparison. Arm exp = btt_policy_obs_v3_entities +
btt_reward_v2 + btt_explore_cells_v1 (fresh models, empty tables); arm ctl = the M7n v3 runs (same profiles without the
table), reused only while their R1 reproduction and record verification pass.

Registered settings and rule: docs/rl_exploration_credit_m7o_manifest.json, docs/rl_exploration_credit_m7o_decision_rule.json.
Everything is written below runs/m7o/campaign; runs/m7n, the pilots and every other run tree are read only.

    python rl/m7o_campaign.py manifest                  # build the manifest (docs/); refused once the campaign froze it
    python rl/m7o_campaign.py control-check             # R1 (3 x 102,400) + record verification, bound to the manifest
    python rl/m7o_campaign.py train --dry-run           # = preflight
    python rl/m7o_campaign.py train                     # exp s0, s1, s2 in order, each behind the launch gate
    python rl/m7o_campaign.py evaluate [--dry-run]      # the M7n protocol, plain v2 workers, 985 episodes per run
    python rl/m7o_campaign.py verify-clears | verify-crossings | census | status
    python rl/m7o_campaign.py analyze [--dry-run]       # the frozen rule, recorded once (never re-decided)
    python rl/m7o_campaign.py all                       # train -> evaluate -> verify-clears -> verify-crossings -> analyze

Stop policy (registered): a failed launch gate, a monitor hard alert, the in-run memory policy, a provenance mismatch, a
process leak, a failed verification, an unbound control or a manifest drift stops the campaign. A stopped run is moved to
_partial by the guard and kept; nothing is fixed, resumed or relaunched here. Native RNG state is never inspected.
"""
from __future__ import annotations

import argparse
import json
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

import btt_explore_cells as xp  # noqa: E402
import experiment_config as ec  # noqa: E402
import m7d_run as dr  # noqa: E402
import m7h_guard as g  # noqa: E402
import m7l_analysis as la  # noqa: E402
import m7n_crossing as xc  # noqa: E402
import m7n_obs as mn  # noqa: E402
import m7n_policy as mnp  # noqa: E402
import m7n_status_table as st  # noqa: E402
import m7o_analysis as oa  # noqa: E402
import m7o_matrix as om  # noqa: E402

REPO_ROOT = RL_DIR.parent
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_INTERRUPTED = 0, 1, 2, 130
GATE_FN: Optional[Callable[[], Dict[str, Any]]] = None
LAUNCHER: Optional[Callable[..., Dict[str, Any]]] = None
SLEEP: Callable[[float], None] = time.sleep
N_SLOTS = om.PROCESS_COUNT


def log(message: str) -> None:
    print(f"[m7o-campaign {time.strftime('%H:%M:%S')}] {message}", flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# -- state -----------------------------------------------------------------------------------------------------------------


def state_file() -> Path:
    return om.state_dir() / "state.json"


def load_state() -> Dict[str, Any]:
    if state_file().is_file():
        return om.read_json(state_file())
    return {"schema": "battleship_m7o_campaign_state_v1", "milestone": om.MILESTONE, "created_utc": utc_now(), "control": {"mode": "m7n_v3"},
            "runs": {}, "evaluations": {}, "clears": {}, "crossings": {}, "decisions": {}, "events": []}


def save_state(state: Dict[str, Any]) -> None:
    state["updated_utc"] = utc_now()
    om.write_json(state_file(), state)


def event(state: Dict[str, Any], kind: str, **data: Any) -> None:
    state.setdefault("events", []).append(dict(kind=kind, utc=utc_now(), **data))
    save_state(state)


# -- manifest ----------------------------------------------------------------------------------------------------------------


def frozen_manifest_path() -> Path:
    return om.state_dir() / "manifest.json"


def load_manifest(*, freeze: bool) -> Dict[str, Any]:
    fp = frozen_manifest_path()
    if fp.is_file():
        man = om.read_json(fp)
        if om.MANIFEST_DOC.is_file() and om.read_json(om.MANIFEST_DOC) != man:
            raise om.MatrixError(f"{ec.repo_relative(om.MANIFEST_DOC)} differs from the frozen copy")
        return man
    if not om.MANIFEST_DOC.is_file():
        raise om.MatrixError(f"{ec.repo_relative(om.MANIFEST_DOC)} missing: run 'python rl/m7o_campaign.py manifest'")
    man = om.read_json(om.MANIFEST_DOC)
    if freeze:
        om.write_json(fp, man)
    return man


def cmd_manifest(args: argparse.Namespace) -> int:
    if frozen_manifest_path().is_file() and not args.out:
        log(f"refused: the campaign froze its manifest at {ec.repo_relative(frozen_manifest_path())}; never rebuilt")
        return EXIT_USAGE
    man = om.build_manifest()
    out = Path(args.out) if args.out else om.MANIFEST_DOC
    om.write_json(out, man)
    log(f"manifest -> {ec.repo_relative(out)} ok={man['ok']} code {man['code']['sha256'][:12]} ({man['code']['files']} files; control-check "
        f"fingerprint {man['code']['control_check_sha256'][:12]}) rule {man['decision_rule']['sha256'][:12]} control bound="
        f"{man['control']['status']['bound_to_this_manifest']}")
    for p in man["problems"]:
        log(f"  PROBLEM {p}")
    return EXIT_OK if man["ok"] else EXIT_FAILED


# -- resources -----------------------------------------------------------------------------------------------------------------


def wait_for_launch_gate(tag: str) -> Dict[str, Any]:
    readings: List[Dict[str, Any]] = []
    last: Dict[str, Any] = {}
    for i in range(om.LAUNCH_GATE_READINGS):
        last = (GATE_FN or g.launch_gate)()
        readings.append({"utc": utc_now(), "ok": last["ok"], "problems": last["problems"],
                         "measurement": {k: (last.get("measurement") or {}).get(k) for k in (
                             "avail_commit_gib", "avail_phys_gib", "disk_free_gib", "cpu_mean_pct", "battleship_pids", "listeners")}})
        if last["ok"]:
            return {"ok": True, "tag": tag, "readings": readings, "problems": []}
        if i < om.LAUNCH_GATE_READINGS - 1:
            log(f"{tag}: launch gate reading {i + 1} failed {last['problems']}; re-measuring in {om.LAUNCH_GATE_RETRY_S:.0f} s")
            SLEEP(om.LAUNCH_GATE_RETRY_S)
    return {"ok": False, "tag": tag, "readings": readings, "problems": last.get("problems")}


# -- the control ---------------------------------------------------------------------------------------------------------------


def control_check_problems(manifest: Mapping[str, Any]) -> List[str]:
    """Why the M7n v3 runs may not be reused now (empty = they may): a PASSED R1 record on exactly the manifest's control-check
    fingerprint and executable, a PASSED record verification on the manifest's rule, and the control files unchanged."""
    p: List[str] = []
    cc, cv = om.control_check_record(), om.control_verify_record()
    code = (manifest.get("code") or {}).get("control_check_sha256")
    exe = (manifest.get("executable") or {}).get("sha256")
    if cc is None:
        p.append("the R1 control check has not run: python rl/m7o_campaign.py control-check")
    else:
        if not cc.get("ok"):
            p.append(f"the R1 control check FAILED ({(cc.get('problems') or [])[:3]}); the control is not reused; stop and diagnose")
        if (cc.get("code") or {}).get("sha256") != code:
            p.append(f"the R1 check ran on code {str((cc.get('code') or {}).get('sha256'))[:12]}, the manifest pins {str(code)[:12]}: rerun it")
        if cc.get("executable_sha256") != exe:
            p.append("the R1 check ran on another executable")
    if cv is None:
        p.append("the control record verification has not run")
    else:
        if not cv.get("ok"):
            p.append(f"the control record verification FAILED ({(cv.get('problems') or [])[:3]})")
        if cv.get("rule_sha256") != (manifest.get("decision_rule") or {}).get("sha256"):
            p.append("the control record verification ran under another rule")
    for s, want in ((manifest.get("control") or {}).get("seeds") or {}).items():
        now = om.control_identity(int(s))
        keys = ("final_checkpoint_json_sha256", "final_digests", "initial_digests", "rows_sha256", "evaluation_sha256", "crossing_doc_sha256")
        if not now["ok"] or any(now.get(k) != want.get(k) for k in keys):
            p.append(f"control seed {s} changed since the manifest or no longer verifies: {now['problems'][:2]}")
    return p


def cmd_control_check(args: argparse.Namespace) -> int:
    import m7o_control_check as cc
    import m7o_control_verify as cv

    manifest = load_manifest(freeze=False)
    drift = om.manifest_drift(manifest)
    if drift:
        for p in drift:
            log(f"BLOCKED {p}")
        return EXIT_FAILED
    if args.dry_run:
        log("dry run: R1 (3 x 102,400 fresh M7n-profile runs vs the M7n ckpt_000102400) -> record verification")
        return EXIT_OK
    rc1 = 0 if args.record_only else cc.main(["--seeds", args.seeds])
    rc2 = cv.main()
    state = load_state()
    rec1, rec2 = om.control_check_record() or {}, om.control_verify_record() or {}
    state.setdefault("control", {})["check"] = {"r1": {k: rec1.get(k) for k in ("utc", "ok", "out", "executable_sha256")} | {
        "code_sha256": (rec1.get("code") or {}).get("sha256")}, "verify": {k: rec2.get(k) for k in ("utc", "ok", "rule_sha256")}}
    event(state, "control_check", r1_ok=rec1.get("ok"), verify_ok=rec2.get("ok"), exit=(rc1, rc2))
    bound = control_check_problems(manifest)
    log(f"control check exits {rc1}/{rc2}; bound to the manifest: {'yes' if not bound else bound[:2]}")
    return EXIT_OK if rc1 == 0 and rc2 == 0 and not bound else EXIT_FAILED


# -- training --------------------------------------------------------------------------------------------------------------------


def run_status(spec: om.RunSpec, state: Mapping[str, Any]) -> str:
    if (((state.get("runs") or {}).get(spec.name) or {}).get("status")) == "verified":
        return "verified"
    if not spec.run_dir.exists():
        return "absent"
    summ = spec.run_dir / "training_summary.json"
    if summ.is_file() and om.read_json(summ).get("status") == "completed":
        return "completed_unverified"
    return "partial"


def train_plan(specs: Sequence[om.RunSpec], state: Mapping[str, Any]) -> List[Dict[str, Any]]:
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
            action = "STOP: a partial run directory exists (preserved; never resumed or relaunched)"
        else:
            action = "train from scratch"
        if (((state.get("runs") or {}).get(spec.name) or {}).get("status")) in ("stopped", "failed", "verification_failed", "gate_refused"):
            action = f"STOP: {spec.name} was {state['runs'][spec.name]['status']} (preserved; not relaunched)"
        plan.append({"run": spec.name, "status": stt, "action": action})
        blocked = True
    return plan


def preflight_run(spec: om.RunSpec, exp: ec.Experiment, manifest: Mapping[str, Any]) -> Dict[str, Any]:
    checks = om.arm_checks(spec, exp)
    p = [f"{spec.name}: {k}" for k, ok in checks.items() if not ok]
    r = (manifest.get("runs") or {}).get(spec.name)
    if r is None:
        p.append(f"{spec.name}: not in the manifest")
    else:
        if (r["source_sha256"], r["semantic_fingerprint"], r["compatibility_fingerprint"]) != (exp.source.sha256, exp.semantic_fingerprint,
                                                                                                 exp.compatibility_fingerprint):
            p.append(f"{spec.name}: profile differs from the manifest")
        if not r.get("expected_initial_policy_digest"):
            p.append(f"{spec.name}: no expected untrained-model digest in the manifest")
        if not (r.get("m7n_proof") or {}).get("ok"):
            p.append(f"{spec.name}: the M7n comparison proof failed")
    for rank in range(N_SLOTS):   # fresh runs only: no table may pre-exist
        if (spec.run_dir / "workers" / f"w{rank:02d}" / "explore_table.json").exists():
            p.append(f"{spec.name}: a novelty table already exists for slot {rank}")
    return {"run": spec.name, "checks": checks, "problems": p, "ok": not p}


def run_identity(run_dir: Path, manifest: Mapping[str, Any]) -> List[str]:
    from btt_rewards import REWARD_V2

    rj = om.read_json(run_dir / "run.json")
    p: List[str] = []
    if (rj.get("executable") or {}).get("sha256") != (manifest.get("executable") or {}).get("sha256"):
        p.append("run.json executable differs from the manifest")
    rev, mrev = rj.get("revisions") or {}, manifest.get("revisions") or {}
    if rev.get("head") != mrev.get("head") or {s["path"]: s["commit"] for s in rev.get("submodules") or []} != mrev.get("submodules"):
        p.append("run.json revisions differ from the manifest")
    c = rj.get("contracts") or {}
    if c.get("policy_observation_contract") != mn.OBS_CONTRACT or c.get("policy_observation_contract_sha256") != mn.contract_digest():
        p.append("run.json observation contract / digest")
    if c.get("action_class_table_sha256") != st.load_table()["sha256"]:
        p.append("run.json action-class table")
    if c.get("exploration_contract") != xp.CONTRACT_ID or c.get("exploration_settings") != xp.ExploreContract().to_json():
        p.append(f"run.json exploration contract {c.get('exploration_contract')} / {c.get('exploration_settings')}")
    net = rj.get("policy_network") or {}
    if (rj.get("ppo") or {}).get("policy") != mnp.POLICY or net.get("network_id") != mnp.NETWORK_ID:
        p.append("run.json policy / network")
    if rj.get("reward_contract") != REWARD_V2.to_json():
        p.append("run.json reward contract is not btt_reward_v2")
    if dict(rj.get("m6_flags") or {}) != om.V3_FLAGS:
        p.append(f"run.json native flags {rj.get('m6_flags')}")
    if rj.get("lineage"):
        p.append(f"not a fresh model: lineage {rj.get('lineage')}")
    if (rj.get("config") or {}).get("curriculum") is not None or (run_dir / "curriculum").exists():
        p.append("a curriculum trace")
    return p


def tables_identity(run_dir: Path) -> Dict[str, Any]:
    out = {}
    for rank in range(N_SLOTS):
        f = run_dir / "workers" / f"w{rank:02d}" / "explore_table.json"
        if f.is_file():
            t = xp.ExploreTable.load(f)
            out[str(rank)] = {"sha256": om.sha256_file(f), "episodes": t.episodes, "cells": len(t.counts)}
    return out


def exploration_checks(run_dir: Path) -> List[str]:
    """The experimental arm's exploration provenance: every row carries its record, five slot tables whose episode counts
    sum to the rows, every slot's first episode starts from an empty table, the checkpoint copies are consistent."""
    p: List[str] = []
    rows, _ = dr.jsonl_rows(run_dir / "metrics" / "episodes.jsonl")
    missing = sum(1 for r in rows if not r.get("explore"))
    if missing:
        p.append(f"{missing} rows without an exploration record")
    tables = tables_identity(run_dir)
    if len(tables) != N_SLOTS:
        p.append(f"{len(tables)} slot tables (need {N_SLOTS})")
    if sum(t["episodes"] for t in tables.values()) != len(rows):
        p.append(f"table episodes {sum(t['episodes'] for t in tables.values())} != rows {len(rows)}")
    firsts: Dict[int, Dict[str, Any]] = {}
    for r in rows:
        k = int(r["rank"])
        if k not in firsts or int(r["worker_episode"]) < int(firsts[k]["worker_episode"]):
            firsts[k] = r
    for k, r in sorted(firsts.items()):
        x = r.get("explore") or {}
        if int(r["worker_episode"]) != 1 or x.get("table_episodes_before") != 0:
            p.append(f"slot {k}: first episode {r['worker_episode']} started with table_episodes_before {x.get('table_episodes_before')}")
    for x in (r.get("explore") or {} for r in rows):
        if x and not (0.0 <= float(x.get("bonus", -1)) <= xp.CAP + 1e-9):
            p.append("a row's bonus is outside [0, cap]")
            break
    fin = run_dir / "final"
    for rank in range(N_SLOTS):
        f = fin / f"explore_table_w{rank:02d}.json"
        if not f.is_file():
            p.append(f"final set lacks the table copy of slot {rank}")
        elif xp.ExploreTable.load(f).episodes != (tables.get(str(rank)) or {}).get("episodes"):
            p.append(f"final set table copy of slot {rank} differs from the worker table")
    return p


def verify_run(spec: om.RunSpec, exp: ec.Experiment, manifest: Mapping[str, Any]) -> Dict[str, Any]:
    r = (manifest.get("runs") or {}).get(spec.name) or {}
    expected = (r.get("expected_initial_policy_digest"), r.get("expected_initial_obs_rms_digest"))
    ver = dr.verify_training_run(spec.run_dir, exp, fresh=True, expected_initial=expected)
    ident = run_identity(spec.run_dir, manifest)
    xchk = exploration_checks(spec.run_dir)
    init = list(dr.checkpoint_digests(spec.run_dir / "checkpoints" / "ckpt_000000000"))
    ctl_init = ((manifest.get("control") or {}).get("seeds") or {}).get(str(spec.seed), {}).get("initial_digests")
    if ctl_init and init != ctl_init:
        ident.append(f"ckpt_000000000 {init} != the M7n initial set {ctl_init}")
    ver["m7o_identity"], ver["exploration"] = ident, xchk
    ver["tables"] = tables_identity(spec.run_dir)
    if ident or xchk:
        ver["problems"].extend(ident + xchk)
        ver["ok"] = False
    return ver


def _guarded_launch(*, spec: om.RunSpec, exp: ec.Experiment, **_: Any) -> Dict[str, Any]:
    tag = f"{spec.name}__{stamp()}"
    guard = om.guard_root()
    return g.train_guarded(config=spec.config_path, run_dir=spec.run_dir, log_path=guard / "logs" / f"{tag}.log",
                           monitor_path=guard / "monitor" / f"{tag}.jsonl", probe_path=guard / "probe" / f"{tag}.jsonl",
                           contract=exp.reward, horizon=int(exp.values["environment.horizon"]), partial_root=om.partial_root(),
                           output_root=spec.run_dir.parent if om.root() != om.DEFAULT_ROOT else None)


def cmd_train(args: argparse.Namespace) -> int:
    state = load_state()
    specs = om.matrix()
    manifest = load_manifest(freeze=not args.dry_run)
    drift = om.manifest_drift(manifest)
    plan = train_plan(specs, state)
    report: Dict[str, Any] = {"dry_run": bool(args.dry_run), "plan": plan, "manifest_drift": drift,
                              "control_check": control_check_problems(manifest),
                              "preflight": {s.name: preflight_run(s, om.load_run(s), manifest) for s in specs},
                              "directory_plan": om.check_directory_plan(), "approval": (manifest.get("authority") or {}).get("approval")}
    first = next((s for s in plan if s["action"] != "skip"), None)
    need_gate = first is not None and first["action"].startswith("train")
    report["resources"] = wait_for_launch_gate("preflight") if need_gate and not args.skip_resource_gate else None
    blocking = drift + report["control_check"] + [p for pf in report["preflight"].values() for p in pf["problems"]] + \
        report["directory_plan"]["problems"] + ([] if report["resources"] is None else report["resources"]["problems"] or [])
    if not str(report["approval"] or "").startswith("APPROVED"):
        blocking.append("the manifest's authority.approval is not APPROVED")
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
        spec = om.run_by_name(step["run"])
        action = step["action"]
        if action.startswith(("STOP", "wait")):
            log(f"{spec.name}: {action}")
            return EXIT_FAILED if action.startswith("STOP") else EXIT_OK
        if spec.name in handled:
            log(f"{spec.name}: not verified after this invocation's attempt; stopping")
            return EXIT_FAILED
        handled.add(spec.name)
        exp = om.load_run(spec)
        rs = state["runs"].setdefault(spec.name, {"status": "pending", "attempts": []})
        if action.startswith("verify"):
            ver = verify_run(spec, exp, manifest)
            om.write_json(om.state_dir() / "verify" / f"{spec.name}.json", ver)
            rs.update(status="verified" if ver["ok"] else "verification_failed", verification=ver["problems"][:20], tables=ver.get("tables"))
            save_state(state)
            if not ver["ok"]:
                log(f"{spec.name}: verification FAILED {ver['problems'][:3]}")
                return EXIT_FAILED
            continue
        drift = om.manifest_drift(manifest)
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
        log(f"{spec.name}: launching (seed {spec.seed}, {om.TOTAL_TRANSITIONS:,} policy transitions, {mn.OBS_CONTRACT} + {xp.CONTRACT_ID})")
        t0 = time.perf_counter()
        res = launcher(spec=spec, exp=exp, manifest=manifest)
        attempt = {"utc": utc_now(), "wall_s": round(time.perf_counter() - t0, 1), "exit_code": res.get("exit_code"), "stop_kind": res.get("stop_kind"),
                   "moved_to": res.get("moved_to"),
                   "probe": {k: (res.get("probe") or {}).get(k) for k in ("min_avail_commit_gib", "min_avail_phys_gib", "samples_physical_below_launch_gate",
                                                                           "max_commit_used_gib")},
                   "commit_drawn_gib": res.get("commit_drawn_gib"), "leftover_battleship_pids": res.get("leftover_battleship_pids"),
                   "monitor": {k: (res.get("monitor") or {}).get(k) for k in ("max_battleship_processes", "max_battleship_listeners", "hard_alerts",
                                                                              "soft_alert_count", "episodes_seen", "episode_ends", "lifecycle_failures")},
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
        om.write_json(om.state_dir() / "verify" / f"{spec.name}.json", ver)
        rs.update(status="verified" if ver["ok"] else "verification_failed", verification=ver["problems"][:20], tables=ver.get("tables"))
        save_state(state)
        if not ver["ok"]:
            log(f"{spec.name}: verification FAILED {ver['problems'][:3]}")
            return EXIT_FAILED
        log(f"{spec.name}: verified")


# -- evaluation (tick-0 only, plain v2 workers) --------------------------------------------------------------------------------


def checkpoint_for(spec: om.RunSpec, label: str, t: int) -> Path:
    return spec.run_dir / "final" if label == "final" else spec.run_dir / "checkpoints" / f"ckpt_{t:09d}"


def checkpoint_provenance(ckpt: Path, spec: om.RunSpec, exp: ec.Experiment, planned_t: int, manifest: Mapping[str, Any]) -> List[str]:
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
    if (block.get("semantic_fingerprint"), block.get("compatibility_fingerprint")) != (exp.semantic_fingerprint, exp.compatibility_fingerprint):
        p.append("experiment fingerprints differ from the profile")
    if (meta.get("seeds") or {}).get("base_seed") != spec.seed:
        p.append(f"base_seed {(meta.get('seeds') or {}).get('base_seed')} != {spec.seed}")
    if (meta.get("executable") or {}).get("sha256") != (manifest.get("executable") or {}).get("sha256"):
        p.append("executable sha256 differs from the manifest")
    rev, mrev = meta.get("revisions") or {}, manifest.get("revisions") or {}
    if rev.get("head") != mrev.get("head") or {s["path"]: s["commit"] for s in rev.get("submodules") or []} != mrev.get("submodules"):
        p.append("revisions differ from the manifest")
    if (meta.get("ppo") or {}).get("policy") != mnp.POLICY or (meta.get("policy_network") or {}).get("network_id") != mnp.NETWORK_ID:
        p.append("policy / network identity")
    if (meta.get("vecnormalize") or {}).get("norm_obs") is not False:
        p.append("vecnormalize norm_obs is not False")
    if (meta.get("contracts") or {}).get("exploration_contract") != xp.CONTRACT_ID:
        p.append("checkpoint contracts lack the exploration contract")
    lc = meta.get("lifecycle") or {}
    if (lc.get("standby_preboot"), lc.get("standby_count")) != (True, 1):
        p.append(f"lifecycle {lc}")
    if meta.get("lineage") or meta.get("interruption"):
        p.append("lineage / interruption present")
    return p


def run_eval_label(state: Dict[str, Any], key: str, out_dir: Path, fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    import m7g_k_run as kr
    from m7_runtime import BATTLESHIP_IMAGE, wait_until_no_process

    done = out_dir / "evaluation_summary.json"
    if done.is_file():
        return om.read_json(done)
    if out_dir.exists():
        aside = out_dir.with_name(out_dir.name + "__incomplete_" + stamp())
        out_dir.rename(aside)
        event(state, "incomplete_evaluation_moved_aside", key=key, to=ec.repo_relative(aside))
    pre = kr.preconditions(f"before evaluation {key}")
    if pre["problems"]:
        raise om.MatrixError(f"evaluation {key}: preconditions failed: {pre['problems']}")
    monitor = dr.Monitor(out=om.state_dir() / "monitor" / "evaluation.jsonl", root_pid=os.getpid()).start()
    t0 = time.perf_counter()
    try:
        result = fn()
    finally:
        mon = monitor.stop()
    leftover = wait_until_no_process(BATTLESHIP_IMAGE, timeout=30.0)
    state.setdefault("evaluations", {}).setdefault(key, {}).update(
        wall_s=round(time.perf_counter() - t0, 1), finished_utc=utc_now(), leak_free=not leftover, monitor_hard_alerts=mon.get("hard_alerts"),
        max_battleship_processes=mon.get("max_battleship_processes"), out_dir=ec.repo_relative(out_dir))
    save_state(state)
    if mon.get("hard_alerts") or leftover:
        raise om.MatrixError(f"evaluation {key}: monitor alerts {mon.get('hard_alerts')} / leaked {leftover}")
    return result


def evaluate_label(state: Dict[str, Any], spec: om.RunSpec, exp: ec.Experiment, plan: Mapping[str, Any], manifest: Mapping[str, Any], *,
                   dry_run: bool = False) -> Dict[str, Any]:
    import m7_evaluation as ev
    import m7_trainer as tr
    import m7g_k_run as kr
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
        ckpt, out, settings=settings, deterministic_episodes=int(plan["deterministic_episodes"]), stochastic_episodes=int(plan["stochastic_episodes"]),
        expected_contracts=tr.run_contracts(cfg), label=plan["label"], preserve_all=True))
    ver = dr.verify_evaluation(res, exp.reward, int(exp.values["environment.horizon"]), plan)
    ver["problems"].extend(kr.verify_metrics(res, arm=None))
    want_flags = dict(om.V3_FLAGS, **om.DIAG_FLAG)
    for mode, r in (res.get("modes") or {}).items():
        if dict(r.get("extra_env") or {}) != want_flags:
            ver["problems"].append(f"{mode}: evaluation flags {r.get('extra_env')}")
        if any(e.get("explore") is not None for e in r.get("episodes") or []):
            ver["problems"].append(f"{mode}: an evaluation row carries an exploration record (the credit must never run in evaluation)")
    if res.get("policy_observation_contract") != mn.OBS_CONTRACT:
        ver["problems"].append(f"evaluated under {res.get('policy_observation_contract')}")
    t0 = mv.verify_eval_tick0(out)
    ver["tick0"] = {k: t0[k] for k in ("ok", "problems", "artifacts", "rows")}
    ver["problems"].extend(f"tick0: {x}" for x in t0["problems"])
    ver["ok"] = not ver["problems"]
    om.write_json(om.state_dir() / "verify_eval" / f"{spec.name}__{plan['label']}.json", ver)
    state["evaluations"][key].update(verification=ver["problems"][:20], ok=ver["ok"], tick0_ok=t0["ok"], checkpoint=ec.repo_relative(ckpt),
                                     num_timesteps=int(plan["num_timesteps"]))
    save_state(state)
    return {"key": key, "checkpoint": ec.repo_relative(ckpt), "provenance_problems": [], "ran": True, "verification": ver}


def post_training_gate() -> Optional[Dict[str, Any]]:
    manifest = load_manifest(freeze=False)
    drift = om.manifest_drift(manifest)
    if drift:
        for p in drift:
            log(f"BLOCKED {p}")
        return None
    return manifest


def tables_unchanged_check(state: Dict[str, Any], spec: om.RunSpec) -> List[str]:
    """After evaluation: the training tables must be byte-identical to the state recorded at training verification."""
    before = ((state.get("runs") or {}).get(spec.name) or {}).get("tables") or {}
    now = tables_identity(spec.run_dir)
    p = [f"{spec.name}: slot {k} table changed after training ({before.get(k)} -> {now.get(k)})" for k in set(before) | set(now)
         if (before.get(k) or {}).get("sha256") != (now.get(k) or {}).get("sha256")]
    eval_tables = list(spec.eval_dir.rglob("explore_table*.json"))
    if eval_tables:
        p.append(f"{spec.name}: {len(eval_tables)} novelty table(s) under the evaluation root")
    state.setdefault("tables_after_evaluation", {})[spec.name] = {"ok": not p, "problems": p, "utc": utc_now()}
    save_state(state)
    return p


def cmd_evaluate(args: argparse.Namespace) -> int:
    state = load_state()
    manifest = post_training_gate()
    if manifest is None:
        return EXIT_FAILED
    if not args.dry_run:
        from m7_runtime import install_kill_on_close_job

        install_kill_on_close_job()
    report: List[Dict[str, Any]] = []
    for spec in om.matrix():
        if ((state.get("runs") or {}).get(spec.name) or {}).get("status") != "verified":
            report.append({"run": spec.name, "skipped": "training not verified"})
            if not args.dry_run:
                log(f"{spec.name}: training not verified; evaluation stops")
                return EXIT_FAILED
            continue
        exp = om.load_run(spec)
        for plan in om.evaluation_plan(spec, exp):
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
        if not args.dry_run:
            p = tables_unchanged_check(state, spec)
            if p:
                log(f"{spec.name}: {p[:2]}; the campaign stops")
                event(state, "tables_changed_after_training", run=spec.name, problems=p)
                return EXIT_FAILED
    if args.dry_run:
        print(json.dumps({"dry_run": True, "labels": report}, indent=1, default=str), flush=True)
    return EXIT_OK


# -- clears and crossings ------------------------------------------------------------------------------------------------------


def cmd_verify_clears(args: argparse.Namespace) -> int:  # noqa: ARG001
    import m7g_k_run as kr
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    state = load_state()
    if post_training_gate() is None:
        return EXIT_FAILED
    ok = True
    for spec in om.matrix():
        if not spec.eval_dir.is_dir():
            continue
        exp = om.load_run(spec)
        for label_dir in sorted(p for p in spec.eval_dir.iterdir() if p.is_dir() and "__incomplete_" not in p.name):
            key = f"{spec.name}:{label_dir.name}"
            if key in (state.get("clears") or {}):
                continue
            doc = kr.verify_clears_in(label_dir, spec.clears_dir / label_dir.name, executable=exp.executable, extra_env=dict(exp.extra_env))
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
                rr = dr.replay_one(art, spec.clears_dir / "training" / f"replay_{k:03d}", executable=exp.executable, extra_env=dict(exp.extra_env),
                                   index=9600 + k)
                rec["verified"] = bool(rr.get("ok") and (rr.get("checks") or {}).get("completion_clocks") and (rr.get("checks") or {}).get("native_clear"))
                rec["checks"] = rr.get("checks")
            recs.append(rec)
        state.setdefault("clears", {})[f"{spec.name}:training"] = {"candidates": len(tc), "records": recs}
        save_state(state)
        if tc:
            log(f"{spec.name}: {len(tc)} native clears during training (training behaviour, never an outcome); replays {[r['verified'] for r in recs]}")
    return EXIT_OK if ok else EXIT_FAILED


def cmd_verify_crossings(args: argparse.Namespace) -> int:  # noqa: ARG001
    from m7_runtime import BATTLESHIP_IMAGE, install_kill_on_close_job, wait_until_no_process

    install_kill_on_close_job()
    state = load_state()
    if post_training_gate() is None:
        return EXIT_FAILED
    ok = True
    for spec in om.matrix():
        key = f"{spec.name}:final"
        if key in (state.get("crossings") or {}):
            continue
        exp = om.load_run(spec)
        label_dir = spec.eval_dir / "final"
        if not (label_dir / "stochastic" / "evaluation.json").is_file():
            log(f"{key}: no final evaluation; crossing verification stops")
            return EXIT_FAILED
        docp = spec.clears_dir / "final" / "crossing_verification.json"
        if docp.is_file():
            raise om.MatrixError(f"{ec.repo_relative(docp)} exists without a state entry (never overwritten)")
        t0 = time.perf_counter()
        doc = xc.verify_crossings_in(label_dir, spec.clears_dir / "final", executable=exp.executable, extra_env=dict(exp.extra_env, **om.DIAG_FLAG),
                                     index_base=9800 + 20 * spec.seed)
        leftover = wait_until_no_process(BATTLESHIP_IMAGE, timeout=30.0)
        rec = {k: doc[k] for k in ("candidates", "exact", "qualified_crossings", "verified_left_target_episodes", "unqualified_left_entries", "X", "ok")}
        rec.update(arm="exp", seed=spec.seed, problems=list(doc["problems"])[:10], doc=ec.repo_relative(docp), wall_s=round(time.perf_counter() - t0, 1),
                   leak_free=not leftover)
        state.setdefault("crossings", {})[key] = rec
        save_state(state)
        log(f"{key}: {doc['candidates']} candidate(s), {doc['exact']} exact, {doc['qualified_crossings']} qualified crossing(s), "
            f"{doc['verified_left_target_episodes']} left-target break(s), X = {doc['X']}" + ("" if doc["ok"] else f" PROBLEMS {doc['problems'][:2]}"))
        if leftover:
            event(state, "process_leak", key=key, pids=leftover)
            return EXIT_FAILED
        ok &= bool(doc["ok"])
    cv = (om.control_verify_record() or {}).get("seeds") or {}
    for s in om.SEEDS:      # the control's M7n documents, re-read with the same code path; nothing is replayed (no candidates)
        c = om.ControlRun(s)
        docp = c.clears_dir / "final" / "crossing_verification.json"
        ci, probs = xc.crossing_inputs(c.eval_dir / "final", om.read_json(docp) if docp.is_file() else None)
        want = (cv.get(str(s)) or {}).get("crossing", {}).get("inputs") or {}
        rec = {"arm": "ctl", "seed": s, "doc": ec.repo_relative(docp), "problems": probs[:10], "ok": not probs and bool(ci) and ci.to_json() == want}
        if ci:
            rec.update({k: ci.to_json()[k] for k in ("candidates", "exact", "qualified_crossings", "verified_left_target_episodes", "X")})
        state.setdefault("crossings", {})[f"{c.name}:final"] = rec
        save_state(state)
        if not rec["ok"]:
            log(f"{c.name}:final: control crossing inputs {rec} != the control verification record {want}; integrity")
            ok = False
    return EXIT_OK if ok else EXIT_FAILED


# -- census, analysis ------------------------------------------------------------------------------------------------------------


def census() -> Dict[str, Any]:
    rows, missing, executed = [], [], 0
    for spec in om.matrix():
        exp = om.load_run(spec)
        for p in om.evaluation_plan(spec, exp):
            s = spec.eval_dir / p["label"] / "evaluation_summary.json"
            got = {"deterministic": 0, "stochastic": 0}
            if s.is_file():
                doc = om.read_json(s)
                got = {m: len(((doc.get("modes") or {}).get(m) or {}).get("episodes") or []) for m in got}
            complete = got == {"deterministic": int(p["deterministic_episodes"]), "stochastic": int(p["stochastic_episodes"])}
            executed += sum(got.values())
            rows.append({"run": spec.name, "label": p["label"], "executed": got, "complete": complete})
            if not complete:
                missing.append(f"{spec.name}:{p['label']} executed {got}")
    return {"plan": om.census_plan(), "rows": rows, "executed_episodes": executed, "missing": missing, "complete": not missing}


def cmd_census(args: argparse.Namespace) -> int:  # noqa: ARG001
    c = census()
    log(f"planned {c['plan']['episodes']} ({c['plan']['arithmetic']}); executed {c['executed_episodes']}; missing {len(c['missing'])}")
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
                    "targets_max": max(f["targets"] for f in facts), "t2": sum(f["t2"] for f in facts), "L": sum(f["L"] for f in facts),
                    "R": sum(f["R"] for f in facts), "falls": sum(f["fall"] for f in facts), "clears_native": sum(f["cleared"] for f in facts + det),
                    "left_entries": sum(f["left_entry"] for f in facts), "left_target_episodes": sum(1 for f in facts if f["left_ids"]),
                    "seven_right": sum(f["seven_right"] for f in facts), "deterministic_targets": sorted({f["targets"] for f in det})})
    return out


def training_facts(run_dir: Path) -> Dict[str, Any]:
    summ = om.read_json(run_dir / "training_summary.json") if (run_dir / "training_summary.json").is_file() else {}
    rows, _ = dr.jsonl_rows(run_dir / "metrics" / "episodes.jsonl")
    out: Dict[str, Any] = {"episodes": len(rows), "falls": sum(1 for r in rows if r.get("end_reason") == "fall"),
                           "clears": sum(1 for r in rows if r.get("cleared")),
                           "mean_targets": round(sum(int(r["targets_broken"]) for r in rows) / len(rows), 4) if rows else None,
                           "throughput": summ.get("throughput"), "wall": summ.get("wall"), "cleanup": summ.get("cleanup"), "status": summ.get("status")}
    by: Dict[int, List[float]] = {}
    for r in sorted(rows, key=lambda r: (int(r["rank"]), int(r["worker_episode"]))):
        by.setdefault(int(r["rank"]), []).append(float((r.get("explore") or {}).get("bonus", 0.0)))
    xs = [r.get("explore") or {} for r in rows]
    q: Dict[str, Any] = {"bonus_total": round(sum(float(x.get("bonus", 0)) for x in xs), 4), "voided_total": round(sum(float(x.get("voided", 0)) for x in xs), 4),
                         "capped_total": round(sum(float(x.get("capped", 0)) for x in xs), 4), "cap_hits": sum(1 for x in xs if x.get("cap_hit")),
                         "cells_credited_total": sum(int(x.get("cells_credited", 0)) for x in xs),
                         "contract_return_total": round(sum(float(r["return"]) for r in rows), 4),
                         "learner_return_total": round(sum(float((r.get("explore") or {}).get("learner_return", r["return"])) for r in rows), 4),
                         "target_reward_total": sum(int(r["targets_broken"]) for r in rows), "per_slot": {}}
    for k, seq in by.items():
        n = len(seq)
        qn = max(1, n // 4)
        q["per_slot"][str(k)] = {"episodes": n, "first_quarter_mean": round(sum(seq[:qn]) / qn, 4), "last_quarter_mean": round(sum(seq[-qn:]) / qn, 4),
                                 "max": round(max(seq), 4) if seq else None, "zero_episodes": sum(1 for b in seq if b == 0.0),
                                 "deciles": [round(sum(seq[i * n // 10:(i + 1) * n // 10]) / max(1, (i + 1) * n // 10 - i * n // 10), 4) for i in range(10)]}
    sets = {}
    for d in sorted((run_dir / "checkpoints").glob("ckpt_*")) + [run_dir / "final"]:
        eps = {}
        for rank in range(N_SLOTS):
            f = d / f"explore_table_w{rank:02d}.json"
            if f.is_file():
                t = xp.ExploreTable.load(f)
                eps[str(rank)] = {"episodes": t.episodes, "cells": len(t.counts)}
        if eps:
            sets[d.name] = eps
    q["tables_by_set"] = sets
    out["exploration"] = q
    return out


def build_report(state: Mapping[str, Any], manifest: Mapping[str, Any]) -> Dict[str, Any]:
    rule = oa.load_rule()
    P = oa.params(rule)
    pending: List[str] = []
    integrity: List[str] = list(control_check_problems(manifest))
    incomplete: List[str] = []
    specs = om.matrix()
    for spec in specs:
        stt = ((state.get("runs") or {}).get(spec.name) or {}).get("status")
        if stt == "verification_failed":
            integrity.append(f"{spec.name}: training verification failed")
        elif stt in ("stopped", "failed", "gate_refused"):
            incomplete.append(f"{spec.name}: training {stt} (preserved, never resumed)")
        elif stt != "verified":
            pending.append(f"{spec.name}: training not finished ({stt})")
        tc = ((state.get("tables_after_evaluation") or {}).get(spec.name) or {})
        if tc and not tc.get("ok"):
            integrity.append(f"{spec.name}: novelty tables changed after training: {tc.get('problems')}")
    c = census()
    if not c["complete"]:
        pending.append(f"census incomplete: {len(c['missing'])} labels ({c['missing'][:2]})")
    for spec in specs:
        for plan in om.evaluation_plan(spec, om.load_run(spec)):
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
    inputs: Dict[str, Any] = {"ctl": {}, "exp": {}, "exp_initial": {}, "crossings": {"ctl": {}, "exp": {}}, "integrity": integrity, "incomplete": incomplete}
    per_seed: Dict[str, Any] = {}
    labels = [p["label"] for p in om.evaluation_plan(specs[0], om.load_run(specs[0]))]
    cv = (om.control_verify_record() or {}).get("seeds") or {}
    for spec in specs:
        s = spec.seed
        ctl = om.ControlRun(s)
        entry: Dict[str, Any] = {}
        for arm, label_dir, cd in (("ctl", ctl.eval_dir / "final", ctl.clears_dir / "final" / "clear_verification.json"),
                                   ("exp", spec.eval_dir / "final", spec.clears_dir / "final" / "clear_verification.json"),
                                   ("exp_initial", spec.eval_dir / "initial", spec.clears_dir / "initial" / "clear_verification.json")):
            if not (label_dir / "stochastic" / "evaluation.json").is_file():
                continue
            a, probs = la.label_inputs(label_dir, om.read_json(cd) if cd.is_file() else None, P)
            inputs[arm][s] = a
            integrity.extend(f"{arm} s{s}: {x}" for x in probs)
            entry[arm] = {"stochastic": a.to_json(), "t2_timing": la.t2_timing(a.t2_ticks), "deterministic": la.deterministic_facts(label_dir, P)}
        for arm, label_dir, out_dir, key in (("ctl", ctl.eval_dir / "final", ctl.clears_dir / "final", f"{ctl.name}:final"),
                                             ("exp", spec.eval_dir / "final", spec.clears_dir / "final", f"{spec.name}:final")):
            if not (label_dir / "stochastic" / "evaluation.json").is_file():
                continue
            docp = out_dir / "crossing_verification.json"
            if not docp.is_file():
                pending.append(f"{key}: crossing verification not run")
                continue
            doc = om.read_json(docp)
            ci, probs = xc.crossing_inputs(label_dir, doc)
            inputs["crossings"][arm][s] = ci
            integrity.extend(f"{arm} s{s}: {x}" for x in probs)
            entry.setdefault(arm, {})["crossings"] = dict(ci.to_json(), doc=ec.repo_relative(docp), records=[
                {k: r.get(k) for k in ("episode_id", "reasons", "qualified_crossing", "verified_left_target_break", "unqualified_left_entry")}
                | {"exact": (r.get("exact") or {}).get("ok"), "route": ((r.get("analysis") or {}).get("route") or {}).get("identity"),
                   "entries": [{k2: e.get(k2) for k2 in ("consumed_tick", "class", "y_c", "sweep_complete_at_entry", "qualified")}
                               | {"landing": (e.get("landing") or {}).get("surface")} for e in (r.get("analysis") or {}).get("entries") or []],
                   "left_target_breaks": (r.get("analysis") or {}).get("left_target_breaks")} for r in doc.get("records") or []])
            entry[arm]["X"] = ci.X
            if arm == "ctl":
                want = (cv.get(str(s)) or {}).get("crossing", {}).get("inputs") or {}
                if ci.to_json() != want:
                    integrity.append(f"ctl s{s}: gate-2 inputs {ci.to_json()} differ from the control verification record {want}")
                rec_m7n = ((manifest.get("control") or {}).get("seeds") or {}).get(str(s), {}).get("m7n_inputs") or {}
                if rec_m7n and inputs["ctl"].get(s) is not None and inputs["ctl"][s].to_json() != rec_m7n.get("final"):
                    integrity.append(f"ctl s{s}: final inputs differ from the M7n analysis record")
        if "exp" in entry:
            entry["exp"]["curve"] = label_curve(spec.eval_dir, labels, P)
        if "ctl" in entry:
            entry["ctl"]["curve"] = label_curve(ctl.eval_dir, labels, P)
        entry["training_exp"] = training_facts(spec.run_dir) if spec.run_dir.is_dir() else None
        entry["training_attempts_exp"] = ((state.get("runs") or {}).get(spec.name) or {}).get("attempts")
        entry["tables_after_evaluation"] = (state.get("tables_after_evaluation") or {}).get(spec.name)
        per_seed[str(s)] = entry
    evals = {k: {x: v.get(x) for x in ("wall_s", "leak_free", "max_battleship_processes")} for k, v in (state.get("evaluations") or {}).items()}
    return {"inputs": inputs, "per_seed": per_seed, "census": {k: c[k] for k in ("plan", "executed_episodes", "missing", "complete")},
            "clears": state.get("clears"), "crossings": state.get("crossings"), "evaluations": evals, "integrity": integrity, "incomplete": incomplete,
            "pending": pending}


def cmd_analyze(args: argparse.Namespace) -> int:
    state = load_state()
    manifest = post_training_gate()
    if manifest is None:
        return EXIT_FAILED
    rule = oa.load_rule()
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
        print(json.dumps({"pending": rep["pending"], "integrity": rep["integrity"], "incomplete": rep["incomplete"]}, indent=1, default=str))
        return EXIT_OK
    d = oa.decide(rep["inputs"], rule)
    doc = {"decision": d, "per_seed": rep["per_seed"], "census": rep["census"], "clears": rep["clears"], "crossings": rep["crossings"],
           "evaluations": rep["evaluations"], "manifest_sha256": om.sha256_file(frozen_manifest_path()), "utc": utc_now()}
    if args.dry_run:
        print(json.dumps(d, indent=1, default=str))
        return EXIT_OK
    out = om.state_dir() / "analysis_n3.json"
    om.write_json(out, doc)
    state.setdefault("decisions", {})["n3"] = {"outcome": d["outcome"], "gate": d.get("gate"), "name": d.get("name"), "decided": d.get("decided"),
                                               "gates": d.get("gates"), "target_regression": d.get("target_regression"), "response": d["response"],
                                               "utc": utc_now(), "report": ec.repo_relative(out)}
    save_state(state)
    log(f"decision at n = 3: {d['outcome']} (gate {d.get('gate')} {d.get('name')}): {d['response']}")
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:  # noqa: ARG001
    state = load_state()
    log(f"control: {(state.get('control') or {}).get('check')}")
    for spec in om.matrix():
        log(f"{spec.order_index} {spec.name}: {run_status(spec, state)}")
    log(f"evaluations verified: {sum(1 for v in (state.get('evaluations') or {}).values() if v.get('ok'))}; crossings: {len(state.get('crossings') or {})}; "
        f"decisions: {state.get('decisions')}")
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
    c.add_argument("--record-only", action="store_true", help="record an existing passing R1 run; the record verification always reruns")
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
    fn = {"manifest": cmd_manifest, "control-check": cmd_control_check, "train": cmd_train, "preflight": cmd_train, "evaluate": cmd_evaluate,
          "verify-clears": cmd_verify_clears, "verify-crossings": cmd_verify_crossings, "census": cmd_census, "analyze": cmd_analyze,
          "status": cmd_status, "all": cmd_all}[args.command]
    try:
        return fn(args)
    except om.MatrixError as exc:
        log(f"ERROR {exc}")
        return EXIT_FAILED
    except KeyboardInterrupt:
        log("interrupted")
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
