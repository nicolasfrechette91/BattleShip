#!/usr/bin/env python3
"""M7g Phase K orchestrator: the v1-versus-v2 observation comparison (matrix rl/m7g_k_matrix.py, rule
rl/m7g_k_analysis.py, design docs/rl_obs_v2_experiment_proposal_m7g.md revision 2).

    python rl/m7g_k_run.py manifest                     # docs/rl_obs_v2_phase_k_manifest_m7g.json
    python rl/m7g_k_run.py resources                    # the resource gate: commit AND physical, gated separately
    python rl/m7g_k_run.py preflight                    # every pre-launch check; launches nothing, writes nothing
    python rl/m7g_k_run.py pilot [--dry-run] [--arm A]  # control reproduction (v1, 102,400), then v2 pilot (204,800)
    python rl/m7g_k_run.py train [--dry-run]            # the six runs, sequential, registered order
    python rl/m7g_k_run.py train --extension            # seeds 3 and 4, both arms: only after an n = 3 gate-6 decision
    python rl/m7g_k_run.py train --restart-partial RUN  # a partial RUN is moved aside intact, RUN restarts from scratch
    python rl/m7g_k_run.py train --resume RUN           # continue RUN's own lineage (a recorded protocol deviation)
    python rl/m7g_k_run.py evaluate [--dry-run]         # post-hoc plan with the btt_eval_metrics_v1 recorder
    python rl/m7g_k_run.py verify-clears                # native re-validation of every cleared episode
    python rl/m7g_k_run.py census [--extension]
    python rl/m7g_k_run.py analyze                      # the rule; records the decision (gate 6 -> extension)
    python rl/m7g_k_run.py status

Before launching anything, every training or evaluation step verifies: the run's arm, seed, profile sources and
fingerprints, observation and network identity, the frozen manifest (executable sha256, parent and submodule
revisions, the code fingerprint of rl/*.py and the profiles), the untrained-policy digests (after the run), checkpoint
provenance (evaluation), the resource gate and output isolation. `--dry-run` performs all of it and launches nothing.

Resume and partial runs (explicit, never silent):
  * a run directory without a completed training_summary.json is a PARTIAL run: `train` stops and names the two
    options; `--restart-partial RUN` moves the directory intact to runs/m7g_k/_partial/RUN__<utc> (never deleted) and
    trains RUN again from scratch with the same seed (the pre-registered default: the comparison keeps uninterrupted,
    seeded runs); `--resume RUN` continues RUN's own lineage from its latest checkpoint set as the segment RUN_r<k>
    (M7d resume guard) and is recorded as a protocol deviation that the analysis reports;
  * a completed but unverified run directory is verified, never retrained;
  * an evaluation label is atomic: a complete evaluation_summary.json is never redone; a partial label directory is
    renamed <label>__incomplete_<utc> and the label is re-run;
  * the extension (seeds 3, 4) is refused unless `analyze` recorded an n = 3 decision that requires it.

The resource gate (both, separately): available system COMMIT >= 6.0 GiB - commit limit minus current commit charge
(GlobalMemoryStatusEx.ullAvailPageFile; M7e measured a 4.96 GiB commit at N=5 with standby and its campaign drew
5.46 GiB) AND available PHYSICAL memory >= 2.5 GiB (ullAvailPhys; measured working set 1.59 GiB), plus free disk
>= 10 GiB, system CPU <= 40 %, no BattleShip process, no listener in the M7 port blocks, no SSB64_* variable.

Reused unchanged from rl/m7d_run.py: Monitor, train_once, system_state, memory_status, process_table,
user_config_fingerprint, verify_training_run, verify_evaluation, evaluation_settings, latest_checkpoint,
_lineage_dirs, replay_one, checkpoint_digests, inspect_vecnormalize. Standard library at module level (spawn workers
re-import this file). No native RNG state anywhere.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import shutil
import signal
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import experiment_config as ec  # noqa: E402  (no torch)
import m7d_run as dr  # noqa: E402  (no torch at module level)
import m7g_k_matrix as km  # noqa: E402  (no torch at module level)

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_INTERRUPTED = 0, 1, 2, 130
REPO_ROOT = km.REPO_ROOT

# -- the resource gate ------------------------------------------------------------------------------------------------
EXPECTED_WORKING_SET_GIB = 1.61        # estimate: M7e measured 1.59 GiB + the v2 parent's ~12 MiB
EXPECTED_COMMIT_GIB = 5.0              # estimate: M7e measured 4.96 GiB + v2
REQUIRED_AVAIL_COMMIT_GIB = 6.0        # the "6 GiB gate": available system commit
REQUIRED_AVAIL_PHYS_GIB = 2.5          # available physical memory (gated separately)
REQUIRED_FREE_DISK_GIB = 10.0
MAX_IDLE_CPU_PCT = 40.0
GIB = 2 ** 30

# -- test hooks (never set by the commands) -----------------------------------------------------------------------------
LAUNCHER: Optional[Callable[..., Dict[str, Any]]] = None       # default dr.train_once
EVALUATE_FN: Optional[Callable[..., Dict[str, Any]]] = None    # default m7_evaluation.evaluate_checkpoint
REPLAY_FN: Optional[Callable[..., Dict[str, Any]]] = None       # default m7d_run.replay_one


def log(message: str) -> None:
    print(f"[m7g-k {datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# -- state ------------------------------------------------------------------------------------------------------------


def state_file() -> Path:
    return km.state_dir() / "state.json"


def load_state() -> Dict[str, Any]:
    if state_file().is_file():
        return km.read_json(state_file())
    return {"schema": "battleship_m7g_k_state_v1", "milestone": km.MILESTONE, "phase": km.PHASE,
            "created_utc": utc_now(), "runs": {}, "evaluations": {}, "decisions": {}, "events": []}


def save_state(state: Dict[str, Any]) -> None:
    state["updated_utc"] = utc_now()
    km.write_json(state_file(), state)


def event(state: Dict[str, Any], kind: str, **data: Any) -> None:
    state.setdefault("events", []).append(dict(kind=kind, utc=utc_now(), **data))
    save_state(state)


# -- the manifest and its drift -----------------------------------------------------------------------------------------


def frozen_manifest_path() -> Path:
    return km.state_dir() / "manifest.json"


def current_identity() -> Dict[str, Any]:
    """What the manifest must still describe at launch time."""
    exe = km.load_run(km.matrix()[0]).executable_fingerprint()
    profiles = {}
    for s in km.matrix(include_extension=True) + km.pilot_specs():
        e = km.load_run(s)
        profiles[s.name] = (e.source.sha256, e.semantic_fingerprint, e.compatibility_fingerprint)
    return {"executable_sha256": exe.get("sha256"), "revisions": km.revisions(),
            "code_sha256": km.code_fingerprint()["sha256"], "profiles": profiles}


def manifest_drift(manifest: Mapping[str, Any], cur: Optional[Mapping[str, Any]] = None) -> List[str]:
    cur = cur or current_identity()
    problems: List[str] = []
    if not manifest.get("ok"):
        problems.append(f"the manifest reports problems: {manifest.get('problems')}")
    if cur["executable_sha256"] != (manifest.get("executable") or {}).get("sha256"):
        problems.append(f"executable sha256 {str(cur['executable_sha256'])[:16]}... != manifest "
                        f"{str((manifest.get('executable') or {}).get('sha256'))[:16]}...")
    rev, mrev = cur["revisions"], manifest.get("revisions") or {}
    if rev.get("head") != mrev.get("head"):
        problems.append(f"parent HEAD {rev.get('head')} != manifest {mrev.get('head')}")
    if rev.get("submodules") != mrev.get("submodules"):
        problems.append(f"submodule revisions {rev.get('submodules')} != manifest {mrev.get('submodules')}")
    if rev.get("submodules_differ_from_index"):
        problems.append(f"submodules differ from the recorded gitlinks: {rev['submodules_differ_from_index']}")
    if cur["code_sha256"] != (manifest.get("code") or {}).get("sha256"):
        problems.append("the Python code or a Phase K profile changed since the manifest (code fingerprint)")
    for name, triple in cur["profiles"].items():
        r = (manifest.get("runs") or {}).get(name)
        if r is None or (r["source_sha256"], r["semantic_fingerprint"], r["compatibility_fingerprint"]) != tuple(triple):
            problems.append(f"{name}: profile source / fingerprints differ from the manifest")
    return problems


def load_manifest(*, freeze: bool) -> Dict[str, Any]:
    """The frozen manifest (runs/m7g_k/_matrix/manifest.json). Created from docs/ on the first real launch."""
    fp = frozen_manifest_path()
    if fp.is_file():
        return km.read_json(fp)
    if not km.MANIFEST_DOC.is_file():
        raise km.MatrixError(f"{ec.repo_relative(km.MANIFEST_DOC)} missing: run 'python rl/m7g_k_run.py manifest'")
    man = km.read_json(km.MANIFEST_DOC)
    if freeze:
        km.write_json(fp, man)
    return man


# -- the resource gate ------------------------------------------------------------------------------------------------


def measure_resources(*, cpu_samples: int = 3, cpu_interval: float = 1.0) -> Dict[str, Any]:
    """Reads the machine; launches nothing."""
    from m7_runtime import cpu_utilisation, system_cpu_times

    prev = system_cpu_times()
    cpu: List[float] = []
    for _ in range(max(1, cpu_samples)):
        time.sleep(cpu_interval)
        now = system_cpu_times()
        cpu.append(round(cpu_utilisation(prev, now), 1))
        prev = now
    st = dr.system_state(label="resource gate")
    mem = st.get("memory") or {}
    return {"utc": utc_now(), "cpu_samples_pct": cpu, "cpu_mean_pct": round(sum(cpu) / len(cpu), 1),
            "avail_commit_gib": mem.get("avail_commit_gib"), "commit_limit_gib": mem.get("commit_limit_gib"),
            "commit_used_gib": mem.get("commit_used_gib"), "avail_phys_gib": mem.get("avail_phys_gib"),
            "total_phys_gib": mem.get("total_phys_gib"), "disk_free_gib": st["disk_free_gib"],
            "battleship_pids": st["battleship_pids"], "listeners": st["listening_ports_in_blocks"],
            "ssb64_environment_variables": st["ssb64_environment_variables"],
            "user_config_sha256": (st.get("user_config") or {}).get("sha256")}


def evaluate_resources(m: Mapping[str, Any]) -> Dict[str, Any]:
    """Pure: the gate's verdict on one measurement. Commit and physical memory are TWO separate gates; a missing
    reading fails its gate (never assumed sufficient)."""
    def gate(value: Any, required: float, what: str, measure: str, basis: str) -> Dict[str, Any]:
        ok = value is not None and float(value) >= required
        return {"what": what, "measure": measure, "available_gib": value, "required_gib": required, "ok": ok,
                "basis": basis}

    commit = gate(m.get("avail_commit_gib"), REQUIRED_AVAIL_COMMIT_GIB, "available system commit",
                  "commit limit - current commit charge (GlobalMemoryStatusEx.ullAvailPageFile, system-wide)",
                  f"expected commitment about {EXPECTED_COMMIT_GIB} GiB at N=5 with standby [E]; M7e measured 4.96 "
                  "GiB and its campaign drew 5.46 GiB incl. the orchestrator; a system-managed pagefile can grow, so "
                  "the gate is conservative")
    physical = gate(m.get("avail_phys_gib"), REQUIRED_AVAIL_PHYS_GIB, "available physical memory",
                    "GlobalMemoryStatusEx.ullAvailPhys",
                    f"expected working set about {EXPECTED_WORKING_SET_GIB} GiB [E] (M7e measured 1.59 GiB) plus room "
                    "for the orchestrator and the page cache")
    problems: List[str] = []
    for g in (commit, physical):
        if not g["ok"]:
            problems.append(f"{g['what']} {g['available_gib']} GiB < {g['required_gib']} GiB")
    if m.get("disk_free_gib") is None or float(m["disk_free_gib"]) < REQUIRED_FREE_DISK_GIB:
        problems.append(f"free disk {m.get('disk_free_gib')} GiB < {REQUIRED_FREE_DISK_GIB} GiB")
    if m.get("cpu_mean_pct") is None or float(m["cpu_mean_pct"]) > MAX_IDLE_CPU_PCT:
        problems.append(f"system CPU {m.get('cpu_mean_pct')} % > {MAX_IDLE_CPU_PCT} %")
    if m.get("battleship_pids"):
        problems.append(f"BattleShip already running: {m['battleship_pids']}")
    if m.get("listeners"):
        problems.append(f"ports occupied in the M7 blocks: {m['listeners']}")
    if m.get("ssb64_environment_variables"):
        problems.append(f"SSB64_* variables set: {m['ssb64_environment_variables']}")
    return {"measurement": dict(m), "commit_gate": commit, "physical_gate": physical,
            "both_memory_gates_required": True, "problems": problems, "ok": not problems}


def resource_gate(**kw: Any) -> Dict[str, Any]:
    return evaluate_resources(measure_resources(**kw))


def preconditions(label: str) -> Dict[str, Any]:
    st = dr.system_state(label=label)
    problems: List[str] = []
    if st["battleship_pids"]:
        problems.append(f"BattleShip.exe already running: {st['battleship_pids']}")
    if st["battleship_listeners"]:
        problems.append(f"BattleShip listeners in the port blocks: {st['battleship_listeners']}")
    if st["disk_free_gib"] < dr.MIN_FREE_DISK_GIB:
        problems.append(f"free disk {st['disk_free_gib']} GiB")
    if st["ssb64_environment_variables"]:
        problems.append(f"SSB64_* variables set in the orchestrator environment: {st['ssb64_environment_variables']}")
    st["problems"] = problems
    return st


# -- training preflight and post-run verification -------------------------------------------------------------------------


def run_status(spec: km.RunSpec, state: Mapping[str, Any]) -> str:
    """verified | completed_unverified | partial | absent (from the directory, then the state)."""
    rs = (state.get("runs") or {}).get(spec.name) or {}
    if rs.get("status") == "verified":
        return "verified"
    if not spec.run_dir.exists():
        return "absent"
    summary = spec.run_dir / "training_summary.json"
    if summary.is_file() and km.read_json(summary).get("status") == "completed":
        return "completed_unverified"
    return "partial"


def preflight_run(spec: km.RunSpec, exp: ec.Experiment, manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """Identity and provenance checks of one run before its training launches (no process, no file)."""
    checks = km.arm_checks(spec, exp)
    problems = [f"{spec.name}: {k}" for k, ok in checks.items() if not ok]
    r = (manifest.get("runs") or {}).get(spec.name)
    if r is None:
        problems.append(f"{spec.name}: not in the manifest")
    else:
        if (r["source_sha256"], r["semantic_fingerprint"], r["compatibility_fingerprint"]) != \
                (exp.source.sha256, exp.semantic_fingerprint, exp.compatibility_fingerprint):
            problems.append(f"{spec.name}: profile differs from the manifest")
        if (r["seed"], r["arm"], r["observation"], r["policy"]) != (spec.seed, spec.arm, km.OBSERVATION[spec.arm],
                                                                    km.POLICY[spec.arm]):
            problems.append(f"{spec.name}: manifest identity {r['seed']}/{r['arm']}/{r['observation']}/{r['policy']}")
        if not r.get("expected_initial_policy_digest"):
            problems.append(f"{spec.name}: the manifest has no expected untrained-policy digest")
    return {"run": spec.name, "seed": spec.seed, "arm": spec.arm, "checks": checks, "problems": problems,
            "ok": not problems}


def phase_k_identity(run_dir: Path, spec: km.RunSpec, manifest: Mapping[str, Any]) -> List[str]:
    """Observation / network / executable / revision identity recorded by the trainer itself."""
    problems: List[str] = []
    run_json = km.read_json(run_dir / "run.json")
    contracts = run_json.get("contracts") or {}
    if contracts.get("policy_observation_contract") != km.OBSERVATION[spec.arm]:
        problems.append(f"run.json observation {contracts.get('policy_observation_contract')}")
    if (run_json.get("ppo") or {}).get("policy") != km.POLICY[spec.arm] or \
            (run_json.get("ppo") or {}).get("policy_class") != km.POLICY_CLASS[spec.arm]:
        problems.append(f"run.json policy {(run_json.get('ppo') or {}).get('policy')}")
    pn = run_json.get("policy_network")
    if spec.arm == "v2":
        if not pn or pn.get("parameters") != km.PARAMETERS["v2"] or pn.get("network_id") != km.V2_NETWORK_ID \
                or (pn.get("observation") or {}).get("contract_sha256") != km.V2_CONTRACT_SHA256:
            problems.append(f"run.json v2 network identity {pn}")
        if contracts.get("policy_observation_contract_sha256") != km.V2_CONTRACT_SHA256:
            problems.append("run.json v2 contract digest")
    elif pn is not None:
        problems.append("a v1 run recorded a v2 network block")
    if (run_json.get("executable") or {}).get("sha256") != (manifest.get("executable") or {}).get("sha256"):
        problems.append("run.json executable sha256 differs from the manifest")
    rev, mrev = run_json.get("revisions") or {}, manifest.get("revisions") or {}
    subs = {s["path"]: s["commit"] for s in rev.get("submodules") or []}
    if rev.get("head") != mrev.get("head") or subs != mrev.get("submodules"):
        problems.append("run.json revisions differ from the manifest")
    final = run_dir / "final"
    if (final / "checkpoint.json").is_file():
        vn = dr.inspect_vecnormalize(final / "vecnormalize.pkl")
        want = ["segment_geometry", "state", "target_geometry"] if spec.arm == "v2" else None
        if vn.get("norm_obs_keys") != want:
            problems.append(f"final statistics keys {vn.get('norm_obs_keys')} != {want}")
    return problems


def verify_run(spec: km.RunSpec, exp: ec.Experiment, run_dir: Path, manifest: Mapping[str, Any], *,
               fresh: bool, expected_start: int = 0) -> Dict[str, Any]:
    r = (manifest.get("runs") or {}).get(spec.name) or {}
    expected = (r.get("expected_initial_policy_digest"), r.get("expected_initial_obs_rms_digest")) \
        if r.get("expected_initial_policy_digest") else None
    ver = dr.verify_training_run(run_dir, exp, fresh=fresh, expected_start=expected_start, expected_initial=expected)
    extra = phase_k_identity(run_dir, spec, manifest)
    ver["phase_k_identity"] = extra
    if extra:
        ver["problems"].extend(extra)
        ver["ok"] = False
    return ver


def historical_baseline(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Fingerprint of runs/ outside the Phase K tree (never for a redirected test root)."""
    if km.matrix_root() != km.DEFAULT_MATRIX_ROOT:
        return None
    path = km.state_dir() / "snapshots" / "historical_before.json"
    if not path.is_file():
        log("fingerprinting the historical run tree (runs/ outside runs/m7g_k, junctions not followed)")
        km.write_json(path, km.historical_snapshot(exclude=(km.matrix_root(),)))
        event(state, "historical_snapshot_before", path=ec.repo_relative(path))
    return km.read_json(path)


# -- training -----------------------------------------------------------------------------------------------------------


def move_partial_aside(spec: km.RunSpec, state: Dict[str, Any]) -> Path:
    dest = km.partial_root() / f"{spec.name}__{stamp()}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    spec.run_dir.rename(dest)
    event(state, "partial_run_moved_aside", run=spec.name, to=ec.repo_relative(dest),
          policy="kept intact, never deleted; the run restarts from scratch with the same seed")
    return dest


def train_plan(specs: Sequence[km.RunSpec], state: Mapping[str, Any], args: argparse.Namespace) -> List[Dict[str, Any]]:
    """For each run in order: what `train` would do (and why it would stop)."""
    plan: List[Dict[str, Any]] = []
    blocked = False
    for spec in specs:
        st = run_status(spec, state)
        if st == "verified":
            plan.append({"run": spec.name, "status": st, "action": "skip"})
            continue
        if blocked:
            plan.append({"run": spec.name, "status": st, "action": "wait (an earlier run is not verified)"})
            continue
        if st == "completed_unverified":
            action = "verify the completed directory (never retrained)"
        elif st == "partial":
            if getattr(args, "restart_partial", None) == spec.name:
                action = "move the partial directory aside intact, then train from scratch"
            elif getattr(args, "resume", None) == spec.name:
                action = "resume its own lineage from the latest checkpoint set (protocol deviation)"
            else:
                action = ("STOP: partial run directory; choose --restart-partial " + spec.name
                          + " (default policy) or --resume " + spec.name)
        else:
            action = "train from scratch"
        if getattr(args, "only", None) and args.only != spec.name:
            action = f"STOP: out of order ({spec.name} is the next run; --only {args.only} refused)"
        plan.append({"run": spec.name, "status": st, "action": action})
        blocked = True
    return plan


def cmd_train(args: argparse.Namespace) -> int:
    ext = bool(getattr(args, "extension", False))
    state = load_state()
    if ext:
        n3 = (state.get("decisions") or {}).get("n3") or {}
        if not n3.get("extension_required"):
            log(f"the extension is refused: no recorded n = 3 decision requires it (recorded: gate {n3.get('gate')})")
            return EXIT_USAGE
        specs = km.extension_specs()
    else:
        specs = km.matrix()
    manifest = load_manifest(freeze=not args.dry_run)
    drift = manifest_drift(manifest)
    plan = train_plan(specs, state, args)
    report: Dict[str, Any] = {"dry_run": bool(args.dry_run), "extension": ext, "plan": plan, "manifest_drift": drift,
                              "preflight": {}, "directory_plan": km.check_directory_plan()}
    for spec in specs:
        report["preflight"][spec.name] = preflight_run(spec, km.load_run(spec), manifest)
    pre_problems = [p for pf in report["preflight"].values() for p in pf["problems"]]
    report["resources"] = None if args.skip_resource_gate else resource_gate(cpu_samples=args.cpu_samples)
    blocking = drift + pre_problems + report["directory_plan"]["problems"] + \
        ([] if report["resources"] is None else report["resources"]["problems"])
    report["blocking_problems"] = blocking
    if args.dry_run:
        print(json.dumps(report, indent=1, default=str), flush=True)
        log(f"dry run: nothing launched, nothing written; blocking problems {len(blocking)}")
        return EXIT_OK if not blocking else EXIT_FAILED
    if blocking:
        for p in blocking:
            log(f"BLOCKED {p}")
        return EXIT_FAILED
    launcher = LAUNCHER or dr.train_once
    before = historical_baseline(state)
    if "user_config_before" not in state:
        state["user_config_before"] = dr.user_config_fingerprint()
        save_state(state)
    event(state, "resource_gate", gate=report["resources"])
    handled: set = set()
    while True:
        # Re-plan after every verified run: runs proceed strictly in the registered order, one at a time.
        step = next((s for s in train_plan(specs, state, args) if s["action"] not in ("skip",)), None)
        if step is None:
            log("every run of this matrix is verified")
            return EXIT_OK
        spec = km.run_by_name(step["run"])
        if spec.name in handled:      # --restart-partial / --resume apply once; a second failure stops here
            log(f"{spec.name}: not verified after this invocation's attempt; stopping")
            return EXIT_FAILED
        handled.add(spec.name)
        exp = km.load_run(spec)
        rs = state["runs"].setdefault(spec.name, {"status": "pending", "lineage": [], "deviations": []})
        action = step["action"]
        if action.startswith(("STOP", "wait")):
            log(f"{spec.name}: {action}")
            return EXIT_USAGE if action.startswith("STOP") else EXIT_OK
        if getattr(args, "only", None):
            args.only = None          # --only names the next run; later runs follow in order in the same invocation
        resume_from: Optional[Path] = None
        segment_dir = spec.run_dir
        run_id: Optional[str] = None
        if action.startswith("verify"):
            ver = verify_run(spec, exp, spec.run_dir, manifest, fresh=True)
            km.write_json(km.state_dir() / "verify" / f"{spec.name}.json", ver)
            rs.update(status="verified" if ver["ok"] else "verification_failed", verification=ver["problems"])
            save_state(state)
            if not ver["ok"]:
                log(f"{spec.name}: verification FAILED {ver['problems'][:3]}")
                return EXIT_FAILED
            continue
        if action.startswith("move"):
            move_partial_aside(spec, state)
        elif action.startswith("resume"):
            ckpt = dr.latest_checkpoint(spec, state)
            if ckpt is None:
                raise km.MatrixError(f"{spec.name}: no checkpoint set to resume from")
            guard = km.mm.resume_guard(spec, ckpt, exp, matrix_root=km.matrix_root())
            k = len(rs.get("lineage") or []) + 1
            run_id = f"{spec.name}_r{k}"
            segment_dir = km.matrix_root() / run_id
            resume_from = ckpt
            rs.setdefault("deviations", []).append({"kind": "lineage_resumed", "utc": utc_now(), "segment": run_id,
                                                    "from": ec.repo_relative(ckpt), "guard": guard})
            event(state, "protocol_deviation_lineage_resumed", run=spec.name, segment=run_id)
        pre = preconditions(f"before {segment_dir.name}")
        if pre["problems"]:
            rs.update(status="blocked", blocked=pre["problems"])
            save_state(state)
            log(f"{spec.name}: preconditions failed: {pre['problems']}")
            return EXIT_FAILED
        log(f"=== {spec.order_index} {segment_dir.name}: seed {spec.seed}, arm {spec.arm} ({km.OBSERVATION[spec.arm]}), "
            f"{spec.total_transitions:,} transitions")
        rs.update(status="running", started_utc=utc_now(), seed=spec.seed, arm=spec.arm,
                  semantic_fingerprint=exp.semantic_fingerprint)
        save_state(state)
        result = launcher(config=spec.config_path, run_dir=segment_dir, contract=exp.reward,
                          horizon=int(exp.values["environment.horizon"]), run_id=run_id, resume_from=resume_from,
                          output_root=None if km.matrix_root() == km.DEFAULT_MATRIX_ROOT else segment_dir.parent,
                          log_path=km.state_dir() / "logs" / f"{segment_dir.name}.log",
                          monitor_path=km.state_dir() / "monitor" / f"{segment_dir.name}.jsonl")
        seg = {"run_dir": ec.repo_relative(segment_dir), "resume_from": ec.repo_relative(resume_from) if resume_from
               else None, "result": result}
        if resume_from:
            rs.setdefault("lineage", []).append(seg)
        else:
            rs["segment"] = seg
        rs["max_battleship_processes"] = (result.get("monitor") or {}).get("max_battleship_processes")
        if result.get("exit_code") != 0 or result.get("stop_reason"):
            rs.update(status="interrupted" if result.get("exit_code") == EXIT_INTERRUPTED else "failed",
                      finished_utc=utc_now())
            save_state(state)
            log(f"{segment_dir.name}: trainer exit {result.get('exit_code')} stop {result.get('stop_reason')}; the matrix "
                f"stops. The directory is kept as a PARTIAL run: --restart-partial {spec.name} (default) or --resume "
                f"{spec.name}")
            return EXIT_FAILED
        ver = verify_run(spec, exp, segment_dir, manifest, fresh=resume_from is None,
                         expected_start=0 if resume_from is None else
                         int(km.read_json(Path(resume_from) / "checkpoint.json")["num_timesteps"]))
        if before is not None:
            hist = km.compare_snapshots(before, km.historical_snapshot(exclude=(km.matrix_root(),)))
            ver["historical_tree"] = {k: v for k, v in hist.items() if k != "added"}
            if not hist["identical"]:
                ver["problems"].append("the historical run tree changed")
                ver["ok"] = False
        post = dr.system_state(label=f"after {segment_dir.name}")
        if post["battleship_pids"]:
            time.sleep(10)
            post = dr.system_state(label=f"after {segment_dir.name} (+10 s)")
        if post["battleship_pids"] or post["user_config"].get("sha256") != state["user_config_before"].get("sha256"):
            ver["problems"].append(f"postconditions: leaks {post['battleship_pids']} / user configuration changed")
            ver["ok"] = False
        summary = km.read_json(segment_dir / "training_summary.json")
        rs["throughput"] = {"end_to_end_tr_per_s": (summary.get("throughput") or {}).get("end_to_end_transitions_per_s"),
                            "learn_s": (summary.get("wall") or {}).get("learn_s"),
                            "memory": {k: v for k, v in (summary.get("memory") or {}).items() if k != "workers"}}
        km.write_json(km.state_dir() / "verify" / f"{segment_dir.name}.json", ver)
        rs.update(status="verified" if ver["ok"] else "verification_failed", finished_utc=utc_now(),
                  verification=ver["problems"])
        save_state(state)
        log(f"{segment_dir.name}: {'VERIFIED' if ver['ok'] else 'VERIFICATION FAILED'} {ver['problems'][:3]}")
        if not ver["ok"]:
            return EXIT_FAILED
    return EXIT_OK


# -- evaluation ---------------------------------------------------------------------------------------------------------


def phase_k_settings(exp: ec.Experiment) -> Any:
    """The profile's evaluation settings with the evaluation-only metrics recorder (adds SSB64_RL_TARGET_DIAG=1); the
    observation is always the checkpoint's own (EvaluationSettings.observation None)."""
    return replace(dr.evaluation_settings(exp), eval_metrics=True, observation=None)


def lineage_names(spec: km.RunSpec, state: Mapping[str, Any]) -> List[str]:
    rs = (state.get("runs") or {}).get(spec.name) or {}
    return [spec.name] + [Path(seg["run_dir"]).name for seg in rs.get("lineage") or []]


def checkpoint_provenance(ckpt: Path, spec: km.RunSpec, exp: ec.Experiment, planned_t: int,
                          manifest: Mapping[str, Any], state: Mapping[str, Any]) -> List[str]:
    """Is this checkpoint set exactly the planned point of this run (arm, seed, profile, executable, revisions)?"""
    import m7_trainer as tr
    from m7_evaluation import CheckpointError, read_checkpoint_set

    try:
        meta = read_checkpoint_set(ckpt, expected_contracts=tr.run_contracts(tr.config_from_experiment(exp)))
    except CheckpointError as exc:
        return [f"{ckpt.name}: {exc}"]
    p: List[str] = []
    if meta.get("run_id") not in lineage_names(spec, state):
        p.append(f"run_id {meta.get('run_id')!r} is not {spec.name} (or its recorded lineage)")
    if meta.get("num_timesteps") is None or int(meta["num_timesteps"]) != int(planned_t):
        p.append(f"num_timesteps {meta.get('num_timesteps')} != planned {planned_t}")
    block = meta.get("experiment") or {}
    if (block.get("semantic_fingerprint"), block.get("compatibility_fingerprint")) != \
            (exp.semantic_fingerprint, exp.compatibility_fingerprint):
        p.append("experiment fingerprints differ from the profile")
    if (meta.get("seeds") or {}).get("base_seed") != spec.seed:
        p.append(f"base_seed {(meta.get('seeds') or {}).get('base_seed')} != {spec.seed}")
    if (meta.get("executable") or {}).get("sha256") != (manifest.get("executable") or {}).get("sha256"):
        p.append("executable sha256 differs from the manifest")
    rev = meta.get("revisions") or {}
    mrev = manifest.get("revisions") or {}
    if rev.get("head") != mrev.get("head") or {s["path"]: s["commit"] for s in rev.get("submodules") or []} != \
            mrev.get("submodules"):
        p.append("revisions differ from the manifest")
    if (meta.get("ppo") or {}).get("policy") != km.POLICY[spec.arm]:
        p.append(f"ppo.policy {(meta.get('ppo') or {}).get('policy')} != {km.POLICY[spec.arm]}")
    pn = meta.get("policy_network")
    if spec.arm == "v2" and (not pn or pn.get("parameters") != km.PARAMETERS["v2"]
                             or pn.get("network_id") != km.V2_NETWORK_ID):
        p.append(f"v2 network identity {pn}")
    if spec.arm == "v1" and pn is not None:
        p.append("a v1 checkpoint carries a v2 network block")
    lc = meta.get("lifecycle") or {}
    if (lc.get("standby_preboot"), lc.get("standby_count")) != (True, 1):
        p.append(f"lifecycle {lc}")
    return p


def verify_metrics(result: Mapping[str, Any], *, arm: Optional[str]) -> List[str]:
    """Every evaluated episode carries a clean btt_eval_metrics_v1 record from the diagnostic-enabled workers."""
    p: List[str] = []
    for mode, r in (result.get("modes") or {}).items():
        flags = r.get("extra_env") or {}
        if flags.get("SSB64_RL_TARGET_DIAG") != "1":
            p.append(f"{mode}: evaluation flags {flags}")
        if arm is not None and (flags.get("SSB64_RL_SPATIAL") == "1") != (arm == "v2"):
            p.append(f"{mode}: spatial flag {flags.get('SSB64_RL_SPATIAL')} for arm {arm}")
        rows = r.get("episodes") or []
        if r.get("eval_metrics_recorded") != len(rows):
            p.append(f"{mode}: {r.get('eval_metrics_recorded')} metric records for {len(rows)} episodes")
        for e in rows:
            m = e.get("eval_metrics") or {}
            if not m.get("ok"):
                p.append(f"{mode} {e.get('episode_id')}: metrics not ok {m.get('target_diag', {}).get('problems')} "
                         f"{m.get('consistency')} {m.get('recorder_problems')}")
    return p[:50]


def run_label(state: Dict[str, Any], key: str, out_dir: Path, fn: Callable[[], Dict[str, Any]], *,
              monitor_path: Optional[Path] = None, book: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One evaluation label under the monitor; atomic (complete summaries reused, partial directories moved aside).
    `book` / `monitor_path`: where its bookkeeping goes (default: the campaign's; the pilot keeps its own)."""
    done = out_dir / "evaluation_summary.json"
    if done.is_file():
        return km.read_json(done)
    if out_dir.exists():
        aside = out_dir.with_name(out_dir.name + "__incomplete_" + stamp())
        out_dir.rename(aside)
        event(state, "incomplete_evaluation_moved_aside", key=key, to=ec.repo_relative(aside))
    pre = preconditions(f"before evaluation {key}")
    if pre["problems"]:
        raise km.MatrixError(f"evaluation {key}: preconditions failed: {pre['problems']}")
    monitor = dr.Monitor(out=monitor_path or km.state_dir() / "monitor" / "evaluation.jsonl", root_pid=os.getpid()).start()
    t0 = time.perf_counter()
    try:
        result = fn()
    finally:
        mon = monitor.stop()
    post = dr.system_state(label=f"after evaluation {key}")
    ev = (state.setdefault("evaluations", {}) if book is None else book).setdefault(key, {})
    ev.update(wall_s=round(time.perf_counter() - t0, 1), finished_utc=utc_now(), monitor=mon,
              leak_free=not post["battleship_pids"], out_dir=ec.repo_relative(out_dir))
    save_state(state)
    if mon["hard_alerts"] or post["battleship_pids"]:
        raise km.MatrixError(f"evaluation {key}: monitor alerts {mon['hard_alerts']} / leaked {post['battleship_pids']}")
    return result


def resolve_checkpoint(spec: km.RunSpec, state: Mapping[str, Any], label: str, t: int) -> Path:
    for d in (reversed(dr._lineage_dirs(spec, state)) if label == "final" else dr._lineage_dirs(spec, state)):
        c = d / "final" if label == "final" else d / "checkpoints" / f"ckpt_{t:09d}"
        if (c / "checkpoint.json").is_file():
            return c
    raise km.MatrixError(f"{spec.name}: checkpoint for {label} (t={t}) not found in its lineage")


def evaluate_run_label(state: Dict[str, Any], spec: km.RunSpec, exp: ec.Experiment, plan: Mapping[str, Any],
                       manifest: Mapping[str, Any], *, dry_run: bool = False, monitor_path: Optional[Path] = None,
                       book: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    import m7_evaluation as ev
    import m7_trainer as tr

    key = f"{spec.name}:{plan['label']}"
    ckpt = resolve_checkpoint(spec, state, plan["label"], int(plan["num_timesteps"]))
    prov = checkpoint_provenance(ckpt, spec, exp, int(plan["num_timesteps"]), manifest, state)
    if prov or dry_run:
        return {"key": key, "checkpoint": ec.repo_relative(ckpt), "provenance_problems": prov, "ran": False}
    evaluate = EVALUATE_FN or ev.evaluate_checkpoint
    out = spec.eval_dir / plan["label"]
    settings = phase_k_settings(exp)
    cfg = tr.config_from_experiment(exp)
    res = run_label(state, key, out, lambda: evaluate(
        ckpt, out, settings=settings, deterministic_episodes=int(plan["deterministic_episodes"]),
        stochastic_episodes=int(plan["stochastic_episodes"]), expected_contracts=tr.run_contracts(cfg),
        label=plan["label"], preserve_all=True), monitor_path=monitor_path, book=book)
    ver = dr.verify_evaluation(res, exp.reward, int(exp.values["environment.horizon"]), plan)
    mp = verify_metrics(res, arm=spec.arm)
    if mp:
        ver["problems"].extend(mp)
        ver["ok"] = False
    if res.get("policy_observation_contract", km.OBSERVATION[spec.arm]) != km.OBSERVATION[spec.arm]:
        ver["problems"].append(f"evaluated under {res.get('policy_observation_contract')}")
        ver["ok"] = False
    (state["evaluations"] if book is None else book)[key].update(verification=ver, checkpoint=ec.repo_relative(ckpt),
                                                                 num_timesteps=int(plan["num_timesteps"]))
    save_state(state)
    return {"key": key, "checkpoint": ec.repo_relative(ckpt), "provenance_problems": [], "ran": True,
            "verification": ver}


def evaluate_random_baseline(state: Dict[str, Any], *, episodes: int = km.RANDOM_BASELINE_EPISODES) -> Dict[str, Any]:
    import m7_evaluation as ev

    exp = km.load_run(km.matrix()[0])
    out = km.eval_root() / "random_baseline"
    settings = phase_k_settings(exp)
    res = run_label(state, "random_baseline", out, lambda: ev.evaluate_random(out, settings=settings, episodes=episodes))
    mp = verify_metrics(res, arm=None)
    state["evaluations"]["random_baseline"]["verification"] = {"problems": mp, "ok": not mp}
    save_state(state)
    return res


def cmd_evaluate(args: argparse.Namespace) -> int:
    state = load_state()
    manifest = load_manifest(freeze=False)
    drift = manifest_drift(manifest)
    ext = bool((state.get("decisions") or {}).get("n3", {}).get("extension_required"))
    specs = km.matrix(include_extension=ext)
    only = set(args.only.split(",")) if args.only else None
    labels = set(args.labels.split(",")) if args.labels else None
    if drift:
        for p in drift:
            log(f"BLOCKED {p}")
        return EXIT_FAILED
    if not args.dry_run:
        import torch

        from m7_runtime import install_kill_on_close_job

        torch.set_num_threads(1)
        install_kill_on_close_job()
        pre = preconditions("before the Phase K evaluation")
        if pre["problems"]:
            log(f"preconditions failed: {pre['problems']}")
            return EXIT_FAILED
        if not args.skip_random and only is None:
            evaluate_random_baseline(state)
    report: List[Dict[str, Any]] = []
    for spec in specs:
        if only and spec.name not in only:
            continue
        if ((state.get("runs") or {}).get(spec.name) or {}).get("status") != "verified":
            report.append({"run": spec.name, "skipped": "training not verified"})
            continue
        exp = km.load_run(spec)
        for plan in km.evaluation_plan(spec, exp):
            if labels and plan["label"] not in labels and not (plan["label"].startswith("curve") and "curve" in labels):
                continue
            r = evaluate_run_label(state, spec, exp, plan, manifest, dry_run=args.dry_run)
            report.append(r)
            if r["provenance_problems"]:
                log(f"{r['key']}: provenance REFUSED {r['provenance_problems'][:3]}")
                if not args.dry_run:
                    return EXIT_FAILED
            elif r.get("ran") and not r["verification"]["ok"]:
                log(f"{r['key']}: PROBLEMS {r['verification']['problems'][:3]}")
                return EXIT_FAILED
    if args.dry_run:
        print(json.dumps({"dry_run": True, "labels": report}, indent=1, default=str), flush=True)
    return EXIT_OK


# -- clear verification -------------------------------------------------------------------------------------------------


def verify_clears_in(label_dir: Path, out_dir: Path, *, executable: Path, extra_env: Mapping[str, str]) -> Dict[str, Any]:
    """Every cleared episode of one evaluation label (deduplicated by native action digest) replayed natively on a
    fresh process from tick 0; completion_time_passed and completion_input_tick compared as two values."""
    replay = REPLAY_FN or dr.replay_one
    seen: Dict[str, Dict[str, Any]] = {}
    for mode in ("stochastic", "deterministic"):
        f = label_dir / mode / "evaluation.json"
        if not f.is_file():
            continue
        for e in km.read_json(f).get("episodes") or []:
            if e.get("cleared") and str(e.get("native_action_digest")) not in seen:
                seen[str(e["native_action_digest"])] = e
    records = []
    for k, (digest, e) in enumerate(sorted(seen.items())):
        work = out_dir / f"replay_{k:03d}_{digest[:8]}"
        if work.exists():
            raise km.MatrixError(f"{work} exists (never overwritten)")
        art = Path(e["artifact_dir"])
        art = art if art.is_absolute() else REPO_ROOT / art
        rec = replay(art, work, executable=executable, extra_env=dict(extra_env), index=9500 + k)
        clocks = (rec.get("completion_time_passed"), rec.get("completion_input_tick"))
        records.append({"native_action_digest": digest, "episode_id": e.get("episode_id"),
                        "recorded_clocks": [e.get("completion_time_passed"), e.get("completion_input_tick")],
                        "replayed_clocks": list(clocks), "checks": rec.get("checks"),
                        "verified": bool(rec.get("ok") and (rec.get("checks") or {}).get("completion_clocks")
                                         and (rec.get("checks") or {}).get("native_clear")
                                         and list(clocks) == [e.get("completion_time_passed"),
                                                              e.get("completion_input_tick")])})
    doc = {"label_dir": ec.repo_relative(label_dir), "utc": utc_now(), "clears": records,
           "verified": sum(1 for r in records if r["verified"]), "candidates": len(records)}
    if records:
        out_dir.mkdir(parents=True, exist_ok=True)
        km.write_json(out_dir / "clear_verification.json", doc)
    return doc


def cmd_verify_clears(args: argparse.Namespace) -> int:
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    state = load_state()
    ext = bool((state.get("decisions") or {}).get("n3", {}).get("extension_required"))
    ok = True
    for spec in km.matrix(include_extension=ext):
        if args.only and spec.name not in args.only.split(","):
            continue
        exp = km.load_run(spec)
        if not spec.eval_dir.is_dir():
            continue
        for label_dir in sorted(p for p in spec.eval_dir.iterdir() if p.is_dir() and "__incomplete_" not in p.name):
            doc = verify_clears_in(label_dir, spec.clears_dir / label_dir.name, executable=exp.executable,
                                   extra_env=dict(exp.extra_env))
            if doc["candidates"]:
                log(f"{spec.name}:{label_dir.name}: {doc['verified']}/{doc['candidates']} clears verified")
                ok &= doc["verified"] == doc["candidates"]
    return EXIT_OK if ok else EXIT_FAILED


# -- census, analysis, pilot, status --------------------------------------------------------------------------------------


def census(*, include_extension: bool) -> Dict[str, Any]:
    plan = km.evaluation_census_plan(include_extension=include_extension)
    rows, missing = [], []
    executed = 0
    for spec in km.matrix(include_extension=include_extension):
        exp = km.load_run(spec)
        for p in km.evaluation_plan(spec, exp):
            s = spec.eval_dir / p["label"] / "evaluation_summary.json"
            got = {"deterministic": 0, "stochastic": 0}
            if s.is_file():
                doc = km.read_json(s)
                got = {m: len(((doc.get("modes") or {}).get(m) or {}).get("episodes") or []) for m in got}
            complete = got == {"deterministic": int(p["deterministic_episodes"]),
                               "stochastic": int(p["stochastic_episodes"])}
            executed += sum(got.values())
            rows.append({"run": spec.name, "label": p["label"], "executed": got, "complete": complete})
            if not complete:
                missing.append(f"{spec.name}:{p['label']} executed {got}")
    rb = km.eval_root() / "random_baseline" / "evaluation_summary.json"
    n_rb = len(((km.read_json(rb).get("modes") or {}).get("random") or {}).get("episodes") or []) if rb.is_file() else 0
    if n_rb != km.RANDOM_BASELINE_EPISODES:
        missing.append(f"random_baseline executed {n_rb}")
    return {"plan": plan, "rows": rows, "executed_episodes": executed + n_rb, "missing": missing,
            "complete": not missing}


def cmd_census(args: argparse.Namespace) -> int:
    c = census(include_extension=args.extension)
    log(f"planned {c['plan']['total_episodes']} ({c['plan']['arithmetic']}); executed {c['executed_episodes']}; "
        f"missing {len(c['missing'])}")
    return EXIT_OK if c["complete"] else EXIT_FAILED


def cmd_analyze(args: argparse.Namespace) -> int:
    import m7g_k_analysis as ka

    state = load_state()
    n3 = (state.get("decisions") or {}).get("n3")
    ext = bool(n3 and n3.get("extension_required"))
    if ext:
        missing = [s.name for s in km.extension_specs() if ((state.get("runs") or {}).get(s.name) or {}).get(
            "status") != "verified"]
        if missing:
            log(f"the extension is required but not complete: {missing}")
            return EXIT_FAILED
    rep = ka.build_report(state, include_extension=ext)
    key = "n5" if ext else "n3"
    if key in (state.get("decisions") or {}):
        log(f"the {key} decision is already recorded (gate {state['decisions'][key]['gate']}); it is never re-decided")
        return EXIT_USAGE
    out = km.state_dir() / f"analysis_{key}.json"
    km.write_json(out, rep)
    d = rep["decision"]
    state.setdefault("decisions", {})[key] = {"gate": d["gate"], "branch": d["branch"], "response": d["response"],
                                              "extension_required": d["extension_required"] and key == "n3",
                                              "utc": utc_now(), "report": ec.repo_relative(out)}
    save_state(state)
    log(f"decision at {key}: gate {d['gate']} ({d['branch']}): {d['response']}")
    return EXIT_OK


def control_reproduction(pilot_dir: Path, m7e_dir: Path, *, t: int = 102_400) -> Dict[str, Any]:
    """Pilot v1 vs M7e seed 0 at `t` transitions: checkpoint digests and every finished training episode row."""
    p: List[str] = []
    ours = dr.checkpoint_digests(pilot_dir / "final")
    ref = dr.checkpoint_digests(m7e_dir / "checkpoints" / f"ckpt_{t:09d}")
    if ours != ref:
        p.append(f"final digests {ours[0][:16]}/{ours[1][:16]} != M7e ckpt_{t:09d} {ref[0][:16]}/{ref[1][:16]}")
    keys = ("rank", "worker_episode", "end_reason", "steps", "targets_broken", "native_action_digest")
    rows_a, _ = dr.jsonl_rows(pilot_dir / "metrics" / "episodes.jsonl")
    rows_b, _ = dr.jsonl_rows(m7e_dir / "metrics" / "episodes.jsonl")
    a = [tuple(r.get(k) for k in keys) for r in rows_a]
    b = [tuple(r.get(k) for k in keys) for r in rows_b if int(r.get("sb3_num_timesteps_seen") or 0) <= t][:len(a)]
    if a != b:
        p.append(f"training episode rows differ ({len(a)} vs {len(b)}; first difference at "
                 f"{next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), None)})")
    return {"t": t, "pilot_digests": list(ours), "m7e_digests": list(ref), "episode_rows_compared": len(a),
            "problems": p, "ok": not p}


PILOT_MIN_THROUGHPUT_RATIO = 0.5    # v2 below 50 % of the v1 pilot's throughput blocks the comparison (report sec. 5)
PILOT_EVALUATION = {"label": "final", "deterministic_episodes": 5, "stochastic_episodes": 20}


def pilot_v2_gate(pilot_state: Mapping[str, Any]) -> List[str]:
    """v2 launches only after the v1 control passed: run verified, exact M7e reproduction, its evaluation verified."""
    v1 = pilot_state.get("m7g_pilot_s0_v1") or {}
    p: List[str] = []
    if (pilot_state.get("control_reproduction") or {}).get("ok") is not True:
        p.append(f"v2 refused: the v1 control reproduction is not recorded as passed "
                 f"({(pilot_state.get('control_reproduction') or {}).get('problems')})")
    if v1.get("status") != "verified" or not v1.get("passed"):
        p.append(f"v2 refused: the v1 pilot is not recorded as passed (status {v1.get('status')!r})")
    return p


def pilot_training_record(spec: km.RunSpec, result: Mapping[str, Any], mem_before: Mapping[str, Any]) -> Dict[str, Any]:
    """Measured cost of one pilot run: throughput (end to end and per rollout), memory (trainer-side process peaks
    and the monitor's system-wide readings against the pre-launch reading), BattleShip process peaks."""
    import m7_trainer as tr

    path = spec.run_dir / "training_summary.json"
    if not path.is_file():
        return {"available": False}
    s = km.read_json(path)
    row = tr.comparison_row(s)
    rolls, _ = dr.jsonl_rows(spec.run_dir / "metrics" / "rollouts.jsonl")
    walls = [float(r["collect_s"]) + float(r["optimize_wall_s"]) for r in rolls]
    first = walls[:20]
    mon = result.get("monitor") or {}
    commit_max = (mon.get("commit_used_gib") or {}).get("max")
    phys_min = (mon.get("avail_phys_gib") or {}).get("min")
    lc = s.get("lifecycle") or {}
    return {
        "available": True, "wall_s_trainer_process": result.get("wall_s"),
        "transitions": row["transitions"], "rollouts": row["rollouts"], "learn_s": row["learn_s"],
        "end_to_end_transitions_per_s": row["end_to_end_transitions_per_s"],
        "collection_transitions_per_s": row["collection_transitions_per_s"],
        "collect_s": row["collect_s"], "optimize_wall_s": row["optimize_wall_s"],
        "rollout_wall_s_mean": round(sum(walls) / len(walls), 4) if walls else None,
        "first20_rollouts": {"n": len(first), "wall_s": round(sum(first), 3),
                             "transitions_per_s": round(len(first) * int(s["config"]["n_envs"]) * int(s["config"]["n_steps"])
                                                        / sum(first), 1) if first else None},
        "episodes_finished": row["episodes_finished"], "end_reasons": row["end_reasons"],
        "targets_mean": row["targets_mean"], "targets_max": row["targets_max"], "clears": row["clears"],
        "memory": {"parent_peak_working_set_mib": row["parent_peak_working_set_mib"],
                   "parent_peak_private_mib": row["parent_peak_private_mib"],
                   "worker_peak_working_set_mib_max": row["worker_peak_working_set_mib_max"],
                   "game_peak_working_set_mib_max": row["game_peak_working_set_mib_max"],
                   "game_private_mib_max": row["game_private_mib_max"],
                   "system_before": {k: mem_before.get(k) for k in ("commit_used_gib", "avail_commit_gib",
                                                                    "avail_phys_gib")},
                   "system_commit_used_gib_max": commit_max, "system_avail_phys_gib_min": phys_min,
                   "system_avail_commit_gib_min": (mon.get("avail_commit_gib") or {}).get("min"),
                   "commit_drawn_gib": None if commit_max is None or mem_before.get("commit_used_gib") is None
                   else round(commit_max - float(mem_before["commit_used_gib"]), 3),
                   "physical_drawn_gib": None if phys_min is None or mem_before.get("avail_phys_gib") is None
                   else round(float(mem_before["avail_phys_gib"]) - phys_min, 3),
                   "monitor_interval_s": mon.get("interval_s"), "monitor_samples": mon.get("samples")},
        "processes": {"monitor_max_battleship": mon.get("max_battleship_processes"),
                      "monitor_max_listeners": mon.get("max_battleship_listeners"),
                      "lifecycle_expected_max": lc.get("expected_max_game_processes"),
                      "lifecycle_observed_max_concurrent_per_worker": lc.get("observed_max_concurrent_per_worker"),
                      "limit": km.MAX_GAME_PROCESSES},
        "monitor_alerts": {"hard": mon.get("hard_alerts"), "soft_count": mon.get("soft_alert_count"),
                           "cold_fallbacks_after_first": mon.get("cold_fallbacks_after_first"),
                           "startup_failures": mon.get("startup_failures"),
                           "lifecycle_failures": mon.get("lifecycle_failures")},
    }


def pilot_checkpoints(spec: km.RunSpec, exp: ec.Experiment, manifest: Mapping[str, Any],
                      state: Mapping[str, Any]) -> Dict[str, Any]:
    """Every checkpoint set of a pilot run (untrained, mid-run, final): provenance at its planned point, plus the arm's
    model and statistics identity with the set loaded read-only."""
    import pickle

    import m7_evaluation as ev
    from m7_trainer import M7PPO

    total = spec.total_transitions
    points = [(f"ckpt_{t:09d}", spec.run_dir / "checkpoints" / f"ckpt_{t:09d}", t)
              for t in dr.checkpoint_labels(total, int(exp.values["checkpoint.interval"]))]
    points.append(("final", spec.run_dir / "final", total))
    out: Dict[str, Any] = {}
    for name, d, t in points:
        if not (d / "checkpoint.json").is_file():
            out[name] = {"num_timesteps": t, "problems": [f"{name}: checkpoint set missing"]}
            continue
        p = checkpoint_provenance(d, spec, exp, t, manifest, state)
        try:
            model = M7PPO.load(str(d / ev.MODEL_FILE), device="cpu")
            ev.check_model_identity(model, km.OBSERVATION[spec.arm])
            with open(d / ev.VECNORM_FILE, "rb") as fp:
                ev.check_vecnormalize_identity(pickle.load(fp), km.OBSERVATION[spec.arm])
        except Exception as exc:  # noqa: BLE001 - any failure to load or identify the set is a problem, recorded
            p.append(f"{name}: identity {type(exc).__name__}: {exc}")
        meta = km.read_json(d / "checkpoint.json")
        out[name] = {"num_timesteps": t, "n_updates": meta.get("n_updates"), "digests": list(dr.checkpoint_digests(d)),
                     "problems": p}
    return out


def pilot_evaluation_digest(label_dir: Path) -> Dict[str, Any]:
    """What the small post-hoc evaluation recorded per mode (btt_eval_metrics_v1; no claim is drawn from it)."""
    s = label_dir / "evaluation_summary.json"
    if not s.is_file():
        return {"available": False}
    out: Dict[str, Any] = {"available": True}
    for mode, r in (km.read_json(s).get("modes") or {}).items():
        rows = r.get("episodes") or []
        ms = [e.get("eval_metrics") or {} for e in rows]
        ends: Dict[str, int] = {}
        for e in rows:
            ends[str(e.get("end_reason"))] = ends.get(str(e.get("end_reason")), 0) + 1
        tb = [int(e.get("targets_broken") or 0) for e in rows]
        out[mode] = {"episodes": len(rows), "metrics_ok": sum(1 for m in ms if m.get("ok")),
                     "targets_mean": round(sum(tb) / len(tb), 4) if tb else None, "targets_max": max(tb, default=None),
                     "end_reasons": ends, "clears": sum(1 for e in rows if e.get("cleared")),
                     "left_entries": sum(1 for m in ms if m.get("first_left_entry")),
                     "seven_or_more": sum(1 for m in ms if m.get("seven_or_more_targets")),
                     "moving_target_2_broken": sum(1 for m in ms if m.get("moving_target_broken")),
                     "broken_id_sets": sorted({tuple(m.get("broken_ids") or []) for m in ms})[:20]}
    return out


def pilot_historical_snapshot() -> Optional[Dict[str, Any]]:
    """Fingerprint of runs/ outside runs/m7g_k (the pilot must leave every existing result byte-identical)."""
    if km.matrix_root() != km.DEFAULT_MATRIX_ROOT:
        return None
    log("fingerprinting runs/ outside runs/m7g_k (existing results; junctions not followed)")
    return km.historical_snapshot(exclude=(km.matrix_root(),))


def cmd_pilot(args: argparse.Namespace) -> int:
    """The smallest safe game-backed step before the comparison (campaign report section 5). v1 (the control) runs
    first; any v1 failure - above all a control reproduction that is not exact - stops before its evaluation and
    before v2. `--arm v2` alone launches only after a recorded passed v1. Pilot logs, monitors, verification records,
    evaluation bookkeeping and snapshots stay below runs/m7g_k/_pilot; the campaign state keeps only state["pilot"]
    (the analysis requires the recorded control reproduction)."""
    state = load_state()
    manifest = load_manifest(freeze=False)
    drift = manifest_drift(manifest)
    arms = (args.arm,) if getattr(args, "arm", None) else tuple(a for a, _ in km.PILOT_ORDER)
    specs = [s for s in km.pilot_specs() if s.arm in arms]
    pf = {s.name: preflight_run(s, km.load_run(s), manifest) for s in specs}
    gate = None if args.skip_resource_gate else resource_gate(cpu_samples=args.cpu_samples)
    exists = [s.name for s in specs if s.run_dir.exists()]
    order = [] if "v1" in arms else pilot_v2_gate(state.get("pilot") or {})
    blocking = drift + [p for v in pf.values() for p in v["problems"]] + ([] if gate is None else gate["problems"]) \
        + [f"{n}: pilot directory exists (never overwritten)" for n in exists] + order
    proot = km.pilot_root()
    plan = {"dry_run": bool(args.dry_run), "arms": list(arms),
            "runs": [{"run": s.name, "arm": s.arm, "transitions": s.total_transitions, "config": ec.repo_relative(
                s.config_path), "run_dir": ec.repo_relative(s.run_dir), "eval_dir": ec.repo_relative(s.eval_dir),
                      "clears_dir": ec.repo_relative(s.clears_dir),
                      "log": ec.repo_relative(proot / "_logs" / f"{s.name}.log"),
                      "monitor": ec.repo_relative(proot / "_monitor" / f"{s.name}.jsonl")} for s in specs],
            "manifest": {"executable_sha256": (manifest.get("executable") or {}).get("sha256"),
                         "revisions": manifest.get("revisions"), "code_sha256": (manifest.get("code") or {}).get("sha256"),
                         "drift": drift},
            "after_v1": "control reproduction against runs/m7e/m7e_s0_v2 at 102,400 (digests + episode rows); a "
                        "mismatch stops here (no evaluation, no v2)",
            "after_each": "verification, every checkpoint set's provenance and identity, throughput / memory / process "
                          "peaks, a small post-hoc evaluation of the final set (5 deterministic + 20 stochastic, "
                          "btt_eval_metrics_v1) and clear verification",
            "v2_throughput_floor": f"{PILOT_MIN_THROUGHPUT_RATIO:.0%} of the v1 pilot",
            "preflight": pf, "resources": gate, "blocking_problems": blocking}
    if args.dry_run:
        print(json.dumps(plan, indent=1, default=str), flush=True)
        log(f"pilot dry run: nothing launched; blocking problems {len(blocking)}")
        return EXIT_OK if not blocking else EXIT_FAILED
    if blocking:
        for p in blocking:
            log(f"BLOCKED {p}")
        return EXIT_FAILED
    launcher = LAUNCHER or dr.train_once
    pilot_state = state.setdefault("pilot", {})
    pilot_state.setdefault("invocations", []).append({"utc": utc_now(), "arms": list(arms), "resources": gate})
    save_state(state)
    before = pilot_historical_snapshot()

    def finish(failure: Optional[str]) -> int:
        """Every exit after a launch: existing results re-fingerprinted, state and the pilot record written."""
        if failure:
            log(failure)
        if before is not None:
            hist = km.compare_snapshots(before, pilot_historical_snapshot())
            pilot_state.setdefault("historical_tree", []).append(
                {"arms": list(arms), "files": before["files"], "bytes": before["bytes"],
                 **{k: v for k, v in hist.items() if k != "added"}})
            if not hist["identical"]:
                log(f"existing results under runs/ changed: {hist['changed'][:3]} {hist['removed'][:3]} "
                    f"{hist['mtime_changed'][:3]}")
                failure = failure or "existing results under runs/ changed"
        save_state(state)
        km.write_json(proot / "pilot_record.json", pilot_state)
        return EXIT_FAILED if failure else EXIT_OK

    for spec in specs:
        if spec.arm == "v2" and pilot_v2_gate(pilot_state):
            return finish(f"{spec.name}: {pilot_v2_gate(pilot_state)}")
        exp = km.load_run(spec)
        mem0 = dr.memory_status()
        log(f"=== pilot {spec.name}: seed {spec.seed}, arm {spec.arm} ({km.OBSERVATION[spec.arm]}), "
            f"{spec.total_transitions:,} transitions")
        pilot_state[spec.name] = {"status": "running", "started_utc": utc_now(), "memory_before": mem0}
        save_state(state)
        result = launcher(config=spec.config_path, run_dir=spec.run_dir, contract=exp.reward,
                          horizon=int(exp.values["environment.horizon"]), run_id=None, resume_from=None,
                          output_root=None if km.matrix_root() == km.DEFAULT_MATRIX_ROOT else spec.run_dir.parent,
                          log_path=proot / "_logs" / f"{spec.name}.log",
                          monitor_path=proot / "_monitor" / f"{spec.name}.jsonl")
        rec = pilot_state[spec.name]
        rec.update(finished_utc=utc_now(), exit_code=result.get("exit_code"), stop_reason=result.get("stop_reason"),
                   wall_s=result.get("wall_s"), log=result.get("log"), monitor_log=result.get("monitor_log"))
        if result.get("exit_code") != 0 or result.get("stop_reason"):
            rec.update(status="failed", monitor=result.get("monitor"))
            return finish(f"{spec.name}: trainer exit {result.get('exit_code')} stop {result.get('stop_reason')}")
        ver = verify_run(spec, exp, spec.run_dir, manifest, fresh=True)
        km.write_json(proot / "_verify" / f"{spec.name}.json", ver)
        rec.update(status="verified" if ver["ok"] else "verification_failed", problems=list(ver["problems"]),
                   verification=ec.repo_relative(proot / "_verify" / f"{spec.name}.json"))
        rec["training"] = pilot_training_record(spec, result, mem0)
        if spec.arm == "v1":
            cr = control_reproduction(spec.run_dir, REPO_ROOT / "runs" / "m7e" / "m7e_s0_v2")
            pilot_state["control_reproduction"] = cr
            if not cr["ok"]:
                return finish(f"{spec.name}: CONTROL REPRODUCTION FAILED {cr['problems']}; stopped before any "
                            "evaluation and before v2")
            log(f"{spec.name}: control reproduction exact (digests {cr['pilot_digests'][0][:16]}/"
                f"{cr['pilot_digests'][1][:16]}, {cr['episode_rows_compared']} episode rows)")
        if not ver["ok"]:
            return finish(f"{spec.name}: VERIFICATION FAILED {ver['problems'][:3]}")
        rec["checkpoints"] = pilot_checkpoints(spec, exp, manifest, state)
        cp = [x for c in rec["checkpoints"].values() for x in c["problems"]]
        peak = (rec["training"].get("processes") or {}).get("monitor_max_battleship")
        if peak is None or int(peak) > km.MAX_GAME_PROCESSES:
            cp.append(f"peak BattleShip processes {peak} (limit {km.MAX_GAME_PROCESSES})")
        if cp:
            rec["problems"].extend(cp)
            return finish(f"{spec.name}: checkpoint / process problems {cp[:3]}")
        if spec.arm == "v2":
            v1t = ((pilot_state.get("m7g_pilot_s0_v1") or {}).get("training") or {})
            v2t = rec["training"]
            ratios = {"end_to_end": None, "first20_rollouts": None}
            if v1t.get("end_to_end_transitions_per_s"):
                ratios["end_to_end"] = round(v2t["end_to_end_transitions_per_s"] / v1t["end_to_end_transitions_per_s"], 4)
            if (v1t.get("first20_rollouts") or {}).get("transitions_per_s"):
                ratios["first20_rollouts"] = round(v2t["first20_rollouts"]["transitions_per_s"] /
                                                   v1t["first20_rollouts"]["transitions_per_s"], 4)
            low = [k for k, r in ratios.items() if r is None or r < PILOT_MIN_THROUGHPUT_RATIO]
            rec["throughput_vs_v1"] = {"ratios": ratios, "floor": PILOT_MIN_THROUGHPUT_RATIO, "blocker": bool(low)}
            if low:
                rec["problems"].append(f"v2 throughput below {PILOT_MIN_THROUGHPUT_RATIO:.0%} of v1: {ratios}")
                return finish(f"{spec.name}: THROUGHPUT BLOCKER {ratios}")
        save_state(state)
        # A small post-hoc evaluation of the trained final set: the evaluation path, the metrics recorder and clear
        # verification exercised on a real trained policy of this arm (no claim is drawn from it).
        import torch

        from m7_runtime import install_kill_on_close_job

        torch.set_num_threads(1)
        install_kill_on_close_job()
        small = dict(PILOT_EVALUATION, num_timesteps=spec.total_transitions)
        r = evaluate_run_label(state, spec, exp, small, manifest, monitor_path=proot / "_monitor" / "evaluation.jsonl",
                               book=pilot_state.setdefault("evaluations", {}))
        clears = verify_clears_in(spec.eval_dir / "final", spec.clears_dir / "final", executable=exp.executable,
                                  extra_env=dict(exp.extra_env))
        rec["evaluation"] = {"provenance_problems": r["provenance_problems"], "verification": r.get("verification"),
                             "digest": pilot_evaluation_digest(spec.eval_dir / "final"),
                             "clears": {k: clears[k] for k in ("verified", "candidates")}}
        if r["provenance_problems"] or not (r.get("verification") or {}).get("ok") \
                or clears["verified"] != clears["candidates"]:
            return finish(f"{spec.name}: evaluation problems {r['provenance_problems'][:3]} "
                        f"{((r.get('verification') or {}).get('problems') or [])[:3]} clears {clears['verified']}/"
                        f"{clears['candidates']}")
        rec["passed"] = True
        save_state(state)
        log(f"{spec.name}: PASSED ({rec['training']['end_to_end_transitions_per_s']} tr/s end to end, peak "
            f"{rec['training']['processes']['monitor_max_battleship']} BattleShip processes)")
    return finish(None)


def cmd_manifest(args: argparse.Namespace) -> int:
    man = km.build_manifest()
    out = Path(args.out) if args.out else km.MANIFEST_DOC
    km.write_json(out, man)
    log(f"manifest -> {ec.repo_relative(out)} ok={man['ok']} ({len(man['runs'])} runs incl. extension and pilot)")
    for p in man["problems"]:
        log(f"  PROBLEM {p}")
    return EXIT_OK if man["ok"] else EXIT_FAILED


def cmd_resources(args: argparse.Namespace) -> int:
    g = resource_gate(cpu_samples=args.cpu_samples)
    c, ph = g["commit_gate"], g["physical_gate"]
    log(f"commit:   {c['available_gib']} GiB available, required {c['required_gib']} -> {'ok' if c['ok'] else 'FAIL'}")
    log(f"physical: {ph['available_gib']} GiB available, required {ph['required_gib']} -> {'ok' if ph['ok'] else 'FAIL'}")
    for p in g["problems"]:
        log(f"  UNSAFE {p}")
    if args.out:
        km.write_json(Path(args.out), g)
    return EXIT_OK if g["ok"] else EXIT_FAILED


def cmd_preflight(args: argparse.Namespace) -> int:
    args.dry_run = True
    return cmd_train(args)


def cmd_status(args: argparse.Namespace) -> int:  # noqa: ARG001
    state = load_state()
    for spec in km.matrix(include_extension=True):
        rs = (state.get("runs") or {}).get(spec.name) or {}
        log(f"{spec.order_index} {spec.name}: {run_status(spec, state)} {rs.get('deviations') or ''}")
    log(f"decisions: {state.get('decisions')}")
    return EXIT_OK


def _raise_keyboard_interrupt(signum, frame):  # noqa: ARG001
    raise KeyboardInterrupt(f"signal {signum}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    m = sub.add_parser("manifest")
    m.add_argument("--out", default=None)
    r = sub.add_parser("resources")
    r.add_argument("--cpu-samples", type=int, default=3)
    r.add_argument("--out", default=None)
    for name in ("train", "preflight"):
        t = sub.add_parser(name)
        t.add_argument("--dry-run", action="store_true")
        t.add_argument("--extension", action="store_true")
        t.add_argument("--only", default=None, help="must be the next run in the registered order")
        t.add_argument("--restart-partial", default=None)
        t.add_argument("--resume", default=None)
        t.add_argument("--skip-resource-gate", action="store_true")
        t.add_argument("--cpu-samples", type=int, default=3)
    p = sub.add_parser("pilot")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--arm", choices=("v1", "v2"), default=None,
                   help="one arm only (v2 only after a recorded passed v1 control); default v1 then v2")
    p.add_argument("--skip-resource-gate", action="store_true")
    p.add_argument("--cpu-samples", type=int, default=3)
    e = sub.add_parser("evaluate")
    e.add_argument("--dry-run", action="store_true")
    e.add_argument("--only", default=None)
    e.add_argument("--labels", default=None)
    e.add_argument("--skip-random", action="store_true")
    v = sub.add_parser("verify-clears")
    v.add_argument("--only", default=None)
    c = sub.add_parser("census")
    c.add_argument("--extension", action="store_true")
    sub.add_parser("analyze")
    sub.add_parser("status")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _raise_keyboard_interrupt)
    fn = {"manifest": cmd_manifest, "resources": cmd_resources, "preflight": cmd_preflight, "train": cmd_train,
          "pilot": cmd_pilot, "evaluate": cmd_evaluate, "verify-clears": cmd_verify_clears, "census": cmd_census,
          "analyze": cmd_analyze, "status": cmd_status}[args.command]
    try:
        return fn(args)
    except km.MatrixError as exc:
        log(f"ERROR {exc}")
        return EXIT_FAILED
    except KeyboardInterrupt:
        log("interrupted")
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
