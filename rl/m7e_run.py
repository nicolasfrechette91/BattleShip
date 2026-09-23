#!/usr/bin/env python3
"""M7e Phase B orchestrator: the bounded reward-v2 extension (matrix in rl/m7e_matrix.py).

    python rl/m7e_run.py manifest                  # resolved experiment matrix -> docs/rl_extended_training_m7e_manifest.json
    python rl/m7e_run.py resources                 # the Phase 4 resource gate (physical working set vs commit)
    python rl/m7e_run.py train                     # the three runs, sequential, seeds 0 -> 1 -> 2; verified runs are skipped
    python rl/m7e_run.py train --resume <run>      # continue <run>'s OWN lineage from its latest checkpoint set
    python rl/m7e_run.py evaluate                  # random baseline + every run's post-hoc evaluation plan
    python rl/m7e_run.py census                    # planned versus executed evaluation sessions and episodes
    python rl/m7e_run.py replay                    # best objective-ranked artifact per run (+ every clear), native stepping
    python rl/m7e_run.py regressions               # the relevant permanent M7/M7e chain + the 468-row TAS revalidation
    python rl/m7e_run.py status

Training goes through the unchanged M7 trainer (`python rl/train_m7.py
--config rl/configs/m7e/<run>.toml`, one fresh Python process per run, its own
kill-on-close job object), strictly one run at a time - never two PPO
experiments simultaneously. While a run trains, the unchanged M7d monitor
samples every 15 s: BattleShip process count (hard limit 10), the trainer's
worker processes and their thread counts, listening loopback ports in the M7
port blocks and their owners, physical memory and commit, system CPU, free
disk, the user's BattleShip.cfg.json fingerprint, and every new row of
metrics/episodes.jsonl (reward-contract closed form, one-time v2 penalty,
target / tick ranges, startup modes, anomalies). A hard alert (more than 10
BattleShip processes, user configuration changed, disk below 5 GiB, a
reward-contract or episode invariant violated) stops the run and the matrix -
gate 8 of the pre-registered decision gates. After every run the directory is
verified and the historical run tree is re-fingerprinted, so runs/m7d and the
M7a-M7c results are proven byte-identical.

Evaluation runs only after training has completely shut down, in this process
(never inside learn()): frozen per-run VecNormalize statistics, the proposal's
fixed evaluation seed 12345, 5 workers with the standby lifecycle, every
episode's canonical artifact preserved.

Reused unchanged from rl/m7d_run.py (the M7d infrastructure is not
duplicated): the live Monitor, train_once, stop_trainer, system_state,
memory_status, listening_ports, user_config_fingerprint, process_table,
jsonl_rows, validate_episode_row, verify_training_run, verify_artifacts,
verify_evaluation, inspect_vecnormalize, checkpoint_digests,
evaluation_settings, replay_one, random_cross_check, objective_from_labels,
eval_row_as_summary, latest_checkpoint. Only the matrix identity, the state
tree, the evaluation plan and the M7e-specific reporting live here.

Standard library at module level only: evaluation spawn workers re-import this
file as __mp_main__. No native RNG state is introduced, inspected, logged,
validated, controlled, compared or hashed here.
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import experiment_config as ec  # noqa: E402  (no torch)
import m7d_run as dr  # noqa: E402  (no torch at module level)
import m7e_matrix as em  # noqa: E402  (no torch at module level)

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_INTERRUPTED = 0, 1, 2, 130
REPO_ROOT = em.REPO_ROOT
STATE_FILE = em.STATE_DIR / "state.json"
MIN_FREE_DISK_GIB = dr.MIN_FREE_DISK_GIB
TARGETS_TOTAL = dr.TARGETS_TOTAL

# -- the resource gate's requirements, reconciled with the committed proposal (section 8) ------------------------------
# The proposal's "peak memory about 1.7 GB" is a PHYSICAL WORKING SET figure. Measured directly from
# runs/m7d/m7d_s0_v2/training_summary.json (the paired M7d reward-v2 run at seed 0, N=5 with standby):
#
#   working set : parent 290.9 MiB + 5 workers x 46.2-46.5 MiB (231.5 MiB) + 10 games x 110.6 MiB (1,106 MiB)
#                 = 1,628.4 MiB = 1.59 GiB  -> the proposal's 1.7 GB figure, confirmed
#   private     : parent 437.6 MiB + 5 workers x 189.4-190.8 MiB (950.0 MiB) + 10 games x 369.7 MiB (3,697 MiB)
#                 = 5,077.6 MiB = 4.96 GiB  -> the COMMIT requirement, which the proposal does not state
#
# 4.96 GiB is above the 4.4-4.6 GiB band quoted for the N=5 standby commitment: that band follows from the M7c
# figures for the games (3.7 GiB) and the parent (0.45 GiB) but understates the trainer's five worker processes,
# whose private bytes are 189-191 MiB each, not the 46 MiB of their working set. The gate below uses the measured
# 4.96 GiB, not the band. Physical and committed memory are gated SEPARATELY.
EXPECTED_WORKING_SET_GIB = 1.7       # measured 1.59 GiB; the proposal's stated figure is used as the headline
EXPECTED_COMMIT_GIB = 4.96           # measured from the M7d reward-v2 seed-0 run, not the 4.4-4.6 GiB band
REQUIRED_AVAIL_PHYS_GIB = 2.5        # the expected working set plus room for the orchestrator and the page cache
REQUIRED_AVAIL_COMMIT_GIB = 5.5      # the expected commitment plus a margin; the pagefile is system-managed
REQUIRED_FREE_DISK_GIB = 10.0        # about 1.4 GB of M7e output, against the 5 GiB monitor hard stop
MAX_IDLE_CPU_PCT = 40.0              # "sufficiently idle for a controlled run"


def log(message: str) -> None:
    print(f"[m7e {datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# -- state -------------------------------------------------------------------------------------------------------------


def load_state() -> Dict[str, Any]:
    if STATE_FILE.is_file():
        return em.read_json(STATE_FILE)
    return {"schema": "battleship_m7e_state_v1", "milestone": em.MILESTONE, "phase": em.PHASE,
            "created_utc": utc_now(), "runs": {}, "evaluations": {}, "events": []}


def save_state(state: Dict[str, Any]) -> None:
    state["updated_utc"] = utc_now()
    em.write_json(STATE_FILE, state)


def event(state: Dict[str, Any], kind: str, **data: Any) -> None:
    state.setdefault("events", []).append(dict(kind=kind, utc=utc_now(), **data))
    save_state(state)


# -- preconditions and the resource gate -------------------------------------------------------------------------------


def _check_manifest_current() -> Dict[str, Any]:
    """The saved manifest must describe exactly the profiles on disk (sources and fingerprints)."""
    if not em.MANIFEST_DOC.is_file():
        raise em.MatrixError(f"{ec.repo_relative(em.MANIFEST_DOC)} missing: run 'python rl/m7e_run.py manifest' first")
    saved = em.read_json(em.MANIFEST_DOC)
    if not saved.get("ok"):
        raise em.MatrixError(f"the saved manifest reports problems: {saved.get('problems')}")
    for spec in em.matrix():
        exp = em.load_run(spec)
        r = saved["runs"][spec.name]
        if (r["source_sha256"], r["semantic_fingerprint"], r["compatibility_fingerprint"]) != \
                (exp.source.sha256, exp.semantic_fingerprint, exp.compatibility_fingerprint):
            raise em.MatrixError(f"{spec.name}: profile changed since the manifest was written")
    exe = em.load_run(em.matrix()[0]).executable_fingerprint()
    if exe.get("sha256") != saved["executable"].get("sha256"):
        raise em.MatrixError("the executable changed since the manifest was written")
    return saved


def _preconditions(label: str) -> Dict[str, Any]:
    st = dr.system_state(label=label)
    problems: List[str] = []
    if st["battleship_pids"]:
        problems.append(f"BattleShip.exe already running: {st['battleship_pids']}")
    if st["battleship_listeners"]:
        problems.append(f"BattleShip listeners in the port blocks: {st['battleship_listeners']}")
    if st["disk_free_gib"] < MIN_FREE_DISK_GIB:
        problems.append(f"free disk {st['disk_free_gib']} GiB")
    if st["ssb64_environment_variables"]:
        problems.append(f"SSB64_* variables set in the orchestrator environment: {st['ssb64_environment_variables']}")
    st["problems"] = problems
    return st


def resource_gate(*, label: str = "resource gate", cpu_samples: int = 3, cpu_interval: float = 1.0) -> Dict[str, Any]:
    """Phase 4: physical working set and private/committed memory are gated SEPARATELY, plus CPU, disk, ports and
    stray processes. Nothing is closed automatically; unsafe values are reported for the user to act on."""
    from m7_runtime import cpu_utilisation, list_processes_named, system_cpu_times

    prev = system_cpu_times()
    cpu: List[float] = []
    for _ in range(max(1, cpu_samples)):
        time.sleep(cpu_interval)
        now = system_cpu_times()
        cpu.append(round(cpu_utilisation(prev, now), 1))
        prev = now
    st = dr.system_state(label=label)
    mem = st.get("memory") or {}
    table = dr.process_table()
    python_procs = [p for p in table if str(p.get("image", "")).lower() in ("python.exe", "pythonw.exe")]
    cpu_mean = round(sum(cpu) / len(cpu), 1) if cpu else None
    gate = {
        "label": label, "utc": utc_now(), "cpu_samples_pct": cpu, "cpu_mean_pct": cpu_mean,
        "physical": {"total_gib": mem.get("total_phys_gib"), "available_gib": mem.get("avail_phys_gib"),
                     "load_pct": mem.get("load_pct"),
                     "expected_working_set_gib": EXPECTED_WORKING_SET_GIB,
                     "required_available_gib": REQUIRED_AVAIL_PHYS_GIB,
                     "basis": "proposal section 8: parent 306 MB + 5 workers x 48.5 MB + 10 game processes x "
                              "110.6 MiB = about 1.7 GB of working set; measured 1,628.4 MiB = 1.59 GiB in the "
                              "paired M7d reward-v2 seed-0 run"},
        "commit": {"limit_gib": mem.get("commit_limit_gib"), "used_gib": mem.get("commit_used_gib"),
                   "available_gib": mem.get("avail_commit_gib"),
                   "expected_commitment_gib": EXPECTED_COMMIT_GIB,
                   "required_available_gib": REQUIRED_AVAIL_COMMIT_GIB,
                   "basis": "measured from runs/m7d/m7d_s0_v2/training_summary.json: parent 437.6 MiB + 5 "
                            "workers x 189.4-190.8 MiB (950.0 MiB) + 10 games x 369.7 MiB (3,697 MiB) = 5,077.6 "
                            "MiB = 4.96 GiB. This is above the 4.4-4.6 GiB band quoted for N=5 with standby, which "
                            "understates the five worker processes' private bytes; the gate uses the measurement. "
                            "The proposal's 1.7 GB figure is working set, not commit",
                   "pagefile": "system-managed on this machine; the commit limit grows under pressure, which is how "
                               "M7d completed with 0.35-1.0 GiB of available commit at its lowest"},
        "disk_free_gib": st["disk_free_gib"], "required_free_disk_gib": REQUIRED_FREE_DISK_GIB,
        "battleship_processes": st["battleship_pids"],
        "listening_ports_in_blocks": st["listening_ports_in_blocks"],
        "python_processes": [{"pid": p["pid"], "image": p["image"]} for p in python_procs],
        "user_config": st["user_config"], "ssb64_environment_variables": st["ssb64_environment_variables"],
        "sequential_only": "one PPO experiment at a time; the three runs are sized against the same headroom",
    }
    problems: List[str] = []
    advice: List[str] = []
    if mem.get("avail_phys_gib") is not None and mem["avail_phys_gib"] < REQUIRED_AVAIL_PHYS_GIB:
        problems.append(f"available physical memory {mem['avail_phys_gib']} GiB < {REQUIRED_AVAIL_PHYS_GIB} GiB "
                        f"(expected working set {EXPECTED_WORKING_SET_GIB} GB)")
    if mem.get("avail_commit_gib") is not None and mem["avail_commit_gib"] < REQUIRED_AVAIL_COMMIT_GIB:
        problems.append(f"available commit {mem['avail_commit_gib']} GiB < {REQUIRED_AVAIL_COMMIT_GIB} GiB "
                        f"(expected commitment about {EXPECTED_COMMIT_GIB} GiB at N=5 with standby)")
    if st["disk_free_gib"] < REQUIRED_FREE_DISK_GIB:
        problems.append(f"free disk {st['disk_free_gib']} GiB < {REQUIRED_FREE_DISK_GIB} GiB")
    if cpu_mean is not None and cpu_mean > MAX_IDLE_CPU_PCT:
        problems.append(f"system CPU {cpu_mean} % > {MAX_IDLE_CPU_PCT} %: the machine is not idle enough for a "
                        f"controlled run")
    if st["battleship_pids"]:
        problems.append(f"BattleShip.exe already running: {st['battleship_pids']}")
    if st["listening_ports_in_blocks"]:
        problems.append(f"ports occupied in the M7 blocks: {st['listening_ports_in_blocks']}")
    if st["ssb64_environment_variables"]:
        problems.append(f"SSB64_* variables set in this environment: {st['ssb64_environment_variables']}")
    if problems:
        advice.append("nothing is closed automatically: free the resources above (typically by closing browsers, "
                      "IDEs, emulators or other game processes) and re-run 'python rl/m7e_run.py resources'")
    gate["problems"] = problems
    gate["advice"] = advice
    gate["ok"] = not problems
    _ = list_processes_named  # imported for parity with the M7d preflight; process table above is authoritative
    return gate


# -- commands ----------------------------------------------------------------------------------------------------------


def cmd_manifest(args: argparse.Namespace) -> int:
    out = Path(args.out) if args.out else em.MANIFEST_DOC
    man = em.build_manifest(with_trainer_view=not args.no_trainer_view)
    em.write_json(out, man)
    log(f"manifest -> {ec.repo_relative(out)} ok={man['ok']}")
    for name, r in man["runs"].items():
        log(f"  {name}: seed {r['seed']} semantic {r['semantic_fingerprint'][:16]}... "
            f"compat {r['compatibility_fingerprint'][:16]}... {r['checkpoint_sets']} checkpoint sets, "
            f"{r['rollouts']} rollouts")
    cen = man["evaluation_protocol"]["census"]
    log(f"  evaluation census: {cen['arithmetic']['per_seed']} per seed; {cen['arithmetic']['three_seeds']}; "
        f"{cen['arithmetic']['plus_random_baseline']} (reconciles={cen['reconciles']})")
    if man["problems"]:
        for p in man["problems"]:
            log(f"  PROBLEM {p}")
    return EXIT_OK if man["ok"] else EXIT_FAILED


def cmd_resources(args: argparse.Namespace) -> int:
    gate = resource_gate(label=args.label, cpu_samples=args.cpu_samples)
    em.STATE_DIR.mkdir(parents=True, exist_ok=True)
    out = em.STATE_DIR / "resources" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    em.write_json(out, gate)
    p, c = gate["physical"], gate["commit"]
    log(f"CPU {gate['cpu_mean_pct']} % (samples {gate['cpu_samples_pct']})")
    log(f"physical: {p['available_gib']} GiB available of {p['total_gib']} GiB, load {p['load_pct']} %; "
        f"expected working set {p['expected_working_set_gib']} GB, required {p['required_available_gib']} GiB")
    log(f"commit:   {c['available_gib']} GiB available ({c['used_gib']} of {c['limit_gib']} GiB charged); "
        f"expected commitment {c['expected_commitment_gib']} GiB, required {c['required_available_gib']} GiB")
    log(f"disk {gate['disk_free_gib']} GiB free; BattleShip processes {len(gate['battleship_processes'])}; "
        f"ports in blocks {len(gate['listening_ports_in_blocks'])}; python processes "
        f"{len(gate['python_processes'])}")
    log(f"user config sha256 {(gate['user_config'] or {}).get('sha256', '?')[:16]}...")
    for x in gate["problems"]:
        log(f"  UNSAFE {x}")
    for x in gate["advice"]:
        log(f"  {x}")
    log(f"resource gate -> {ec.repo_relative(out)} ok={gate['ok']}")
    return EXIT_OK if gate["ok"] else EXIT_FAILED


def cmd_train(args: argparse.Namespace) -> int:
    manifest = _check_manifest_current()
    em.STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    if not (em.STATE_DIR / "manifest.json").is_file():
        em.write_json(em.STATE_DIR / "manifest.json", manifest)
    snap_dir = em.STATE_DIR / "snapshots"
    before_path = snap_dir / "historical_before.json"
    if not before_path.is_file():
        log("fingerprinting the historical run tree (runs/, the M7e tree excluded, junctions not followed)")
        em.write_json(before_path, em.historical_snapshot(exclude=(em.MATRIX_ROOT,)))
        event(state, "historical_snapshot_before", path=ec.repo_relative(before_path))
    before = em.read_json(before_path)
    log(f"historical baseline: {before['files']} files, {before['bytes']} bytes, "
        f"aggregate {before['aggregate_sha256'][:16]}...")
    if "user_config_before" not in state:
        state["user_config_before"] = dr.user_config_fingerprint()
        save_state(state)
    if not args.skip_resource_gate:
        gate = resource_gate(label="before the M7e training campaign")
        event(state, "resource_gate", gate={k: v for k, v in gate.items() if k != "listening_ports_in_blocks"})
        if not gate["ok"]:
            log(f"resource gate FAILED: {gate['problems']}")
            for a in gate["advice"]:
                log(f"  {a}")
            return EXIT_FAILED
        log(f"resource gate ok: {gate['physical']['available_gib']} GiB physical available, "
            f"{gate['commit']['available_gib']} GiB commit available, CPU {gate['cpu_mean_pct']} %")
    specs = em.matrix()
    if args.resume:
        specs = [em.run_by_name(args.resume)]
    elif args.only:
        specs = [em.run_by_name(args.only)]
    for spec in specs:
        rs = state["runs"].setdefault(spec.name, {"status": "pending", "lineage": []})
        if rs.get("status") == "verified":
            log(f"{spec.name}: already verified, skipped")
            continue
        exp = em.load_run(spec)
        resume_from = None
        segment_dir = spec.run_dir
        run_id = None
        if args.resume:
            ckpt = dr.latest_checkpoint(spec, state)
            if ckpt is None:
                raise em.MatrixError(f"{spec.name}: no checkpoint set to resume from")
            guard = em.resume_guard(spec, ckpt, exp)
            k = len(rs.get("lineage") or []) + 1
            run_id = f"{spec.name}_r{k}"
            segment_dir = em.MATRIX_ROOT / run_id
            resume_from = ckpt
            event(state, "resume_guard_passed", run=spec.name, guard=guard, new_segment=run_id,
                  interruption="recorded: this segment continues the run's own lineage only")
        elif spec.run_dir.exists():
            summary = spec.run_dir / "training_summary.json"
            if summary.is_file() and em.read_json(summary).get("status") == "completed":
                log(f"{spec.name}: completed run directory found; verifying it")
                ver = dr.verify_training_run(spec.run_dir, exp, expected_initial=_expected_initial(spec.name))
                em.write_json(em.STATE_DIR / "verify" / f"{spec.name}.json", ver)
                rs.update(status="verified" if ver["ok"] else "verification_failed", verification=ver["problems"])
                save_state(state)
                if not ver["ok"]:
                    log(f"{spec.name}: verification FAILED: {ver['problems']}")
                    return EXIT_FAILED
                continue
            raise em.MatrixError(f"{spec.name}: {ec.repo_relative(spec.run_dir)} exists without a completed summary; "
                                 f"inspect it and continue with 'train --resume {spec.name}' (never overwritten)")
        pre = _preconditions(f"before {segment_dir.name}")
        if pre["problems"]:
            rs.update(status="blocked", blocked=pre["problems"])
            save_state(state)
            log(f"{spec.name}: preconditions failed: {pre['problems']}")
            return EXIT_FAILED
        log(f"=== {spec.order_index}/{len(em.matrix())} {segment_dir.name}: seed {spec.seed}, "
            f"{exp.reward.contract}, {int(exp.values['run.total_transitions']):,} transitions, "
            f"semantic {exp.semantic_fingerprint[:16]}...")
        rs.update(status="running", started_utc=utc_now(), preconditions=pre, seed=spec.seed,
                  reward_contract=exp.reward.contract,
                  total_transitions=int(exp.values["run.total_transitions"]),
                  source_sha256=exp.source.sha256, semantic_fingerprint=exp.semantic_fingerprint,
                  compatibility_fingerprint=exp.compatibility_fingerprint)
        save_state(state)
        result = dr.train_once(config=spec.config_path, run_dir=segment_dir, contract=exp.reward,
                               horizon=int(exp.values["environment.horizon"]), run_id=run_id, resume_from=resume_from,
                               log_path=em.STATE_DIR / "logs" / f"{segment_dir.name}.log",
                               monitor_path=em.STATE_DIR / "monitor" / f"{segment_dir.name}.jsonl")
        post = dr.system_state(label=f"after {segment_dir.name}")
        if post["battleship_pids"]:
            time.sleep(10)
            post = dr.system_state(label=f"after {segment_dir.name} (+10 s)")
        seg = {"run_dir": ec.repo_relative(segment_dir),
               "resume_from": ec.repo_relative(resume_from) if resume_from else None,
               "result": result, "postconditions": post}
        if resume_from:
            rs.setdefault("lineage", []).append(seg)
        else:
            rs["segment"] = seg
        if result["exit_code"] != 0 or result["stop_reason"]:
            rs.update(status="interrupted" if result["exit_code"] == EXIT_INTERRUPTED else "failed",
                      finished_utc=utc_now())
            save_state(state)
            log(f"{segment_dir.name}: trainer exit {result['exit_code']} stop {result['stop_reason']}; matrix "
                f"stopped (evidence kept; resume with 'train --resume {spec.name}' after diagnosis - never "
                f"substituted by another run and never silently restarted)")
            return EXIT_FAILED
        ver = dr.verify_training_run(segment_dir, exp, fresh=resume_from is None,
                                     expected_start=0 if resume_from is None else
                                     int(em.read_json(Path(resume_from) / "checkpoint.json")["num_timesteps"]),
                                     expected_initial=_expected_initial(spec.name))
        after = em.historical_snapshot(exclude=(em.MATRIX_ROOT,))
        hist = em.compare_snapshots(before, after)
        ver["historical_tree"] = hist
        if not hist["identical"]:
            ver["problems"].append(f"historical run tree changed: {hist}")
            ver["ok"] = False
        if post["battleship_pids"] or post["battleship_listeners"]:
            ver["problems"].append(f"leak after the run: {post['battleship_pids']} {post['battleship_listeners']}")
            ver["ok"] = False
        if post["user_config"].get("sha256") != state["user_config_before"].get("sha256"):
            ver["problems"].append("user configuration changed")
            ver["ok"] = False
        em.write_json(em.STATE_DIR / "verify" / f"{segment_dir.name}.json", ver)
        rs.update(status="verified" if ver["ok"] else "verification_failed", finished_utc=utc_now(),
                  verification=ver["problems"])
        save_state(state)
        mon = result["monitor"]
        log(f"{segment_dir.name}: {'VERIFIED' if ver['ok'] else 'VERIFICATION FAILED'} in {result['wall_s']} s "
            f"({result['wall_s'] / 60:.1f} min, "
            f"{int(exp.values['run.total_transitions']) / max(result['wall_s'], 1e-9):.1f} transitions/s); "
            f"max BattleShip {mon['max_battleship_processes']}; problems {ver['problems'][:3]}")
        if not ver["ok"]:
            return EXIT_FAILED
    return EXIT_OK


def _expected_initial(name: str):
    if not em.MANIFEST_DOC.is_file():
        return None
    r = (em.read_json(em.MANIFEST_DOC).get("runs") or {}).get(name) or {}
    if not r.get("expected_initial_policy_digest"):
        return None
    return r["expected_initial_policy_digest"], r["expected_initial_obs_rms_digest"]


# -- evaluation --------------------------------------------------------------------------------------------------------


def resolve_checkpoint(spec: em.RunSpec, state: Mapping[str, Any], label: str, t: int) -> Path:
    """The checkpoint set an evaluated point refers to, across a resumed lineage."""
    if label == "final":
        for d in reversed(dr._lineage_dirs(spec, state)):
            if (d / "final" / "checkpoint.json").is_file():
                return d / "final"
        raise em.MatrixError(f"{spec.name}: no final checkpoint set")
    name = f"ckpt_{t:09d}"
    for d in dr._lineage_dirs(spec, state):
        p = d / "checkpoints" / name
        if (p / "checkpoint.json").is_file():
            return p
    raise em.MatrixError(f"{spec.name}: checkpoint set {name} not found in the lineage")


def _run_evaluation(state: Dict[str, Any], key: str, fn: Callable[[], Dict[str, Any]], out_dir: Path) -> Dict[str, Any]:
    """Run one evaluation set under the monitor. A complete set (evaluation_summary.json) is never redone; a partial
    directory left by an aborted attempt is kept, renamed <dir>__incomplete_<utc>, and the set is re-run."""
    done = out_dir / "evaluation_summary.json"
    if done.is_file():
        return em.read_json(done)
    if out_dir.exists():
        aside = out_dir.with_name(out_dir.name + "__incomplete_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        out_dir.rename(aside)
        event(state, "incomplete_evaluation_moved_aside", key=key, to=ec.repo_relative(aside))
    pre = _preconditions(f"before evaluation {key}")
    if pre["problems"]:
        raise em.MatrixError(f"evaluation {key}: preconditions failed: {pre['problems']}")
    monitor = dr.Monitor(out=em.STATE_DIR / "monitor" / "evaluation.jsonl", root_pid=os.getpid()).start()
    t0 = time.perf_counter()
    try:
        result = fn()
    finally:
        mon = monitor.stop()
    post = dr.system_state(label=f"after evaluation {key}")
    if post["battleship_pids"]:
        time.sleep(10)
        post = dr.system_state(label=f"after evaluation {key} (+10 s)")
    ev_state = state.setdefault("evaluations", {}).setdefault(key, {})
    ev_state.update(wall_s=round(time.perf_counter() - t0, 1), finished_utc=utc_now(), monitor=mon,
                    leak_free=not post["battleship_pids"], out_dir=ec.repo_relative(out_dir))
    if mon["hard_alerts"] or post["battleship_pids"]:
        save_state(state)
        raise em.MatrixError(f"evaluation {key}: monitor alerts {mon['hard_alerts']} / leaked {post['battleship_pids']}")
    save_state(state)
    return result


def cmd_evaluate(args: argparse.Namespace) -> int:
    import torch

    import m7_evaluation as ev
    from btt_parallel import m7_contracts
    from m7_runtime import install_kill_on_close_job

    torch.set_num_threads(1)   # evaluation inference in this process; recorded, identical for every model
    install_kill_on_close_job()
    state = load_state()
    only = set(args.only.split(",")) if args.only else None
    labels = set(args.labels.split(",")) if args.labels else None
    # Training must be completely shut down before any evaluation starts.
    pre = _preconditions("before the M7e evaluation census")
    if pre["problems"]:
        log(f"evaluation preconditions failed: {pre['problems']}")
        return EXIT_FAILED
    unverified = [s.name for s in em.matrix() if ((state.get("runs") or {}).get(s.name) or {}).get("status")
                  != "verified"]
    if unverified and not args.allow_unverified:
        log(f"training not verified for {unverified}; evaluation is post-hoc only (use --allow-unverified to "
            f"evaluate what exists)")
        return EXIT_FAILED
    if not args.skip_random and only is None:
        exp0 = em.load_run(em.matrix()[0])
        out = em.EVAL_ROOT / "random_baseline"
        settings = dr.evaluation_settings(exp0)
        res = _run_evaluation(state, "random_baseline",
                              lambda: ev.evaluate_random(out, settings=settings,
                                                         episodes=em.RANDOM_BASELINE_EPISODES), out)
        cross = dr.random_cross_check(res)
        state["evaluations"]["random_baseline"]["cross_check_m7a"] = cross
        save_state(state)
        a = res["modes"]["random"]["aggregate"]
        log(f"random baseline: targets mean {a['targets_mean']} falls {a['falls']} horizon {a['horizon_truncations']}; "
            f"identical to the M7a baseline: {cross.get('identical_episodes')}/{cross.get('compared')}")
    for spec in em.matrix():
        if only and spec.name not in only:
            continue
        rs = (state.get("runs") or {}).get(spec.name) or {}
        if rs.get("status") != "verified" and not args.allow_unverified:
            log(f"{spec.name}: training not verified (status {rs.get('status')}); evaluation skipped")
            continue
        exp = em.load_run(spec)
        settings = dr.evaluation_settings(exp)
        horizon = int(exp.values["environment.horizon"])
        for plan in em.evaluation_plan(spec, exp):
            if labels and plan["label"] not in labels and not (plan["label"].startswith("curve") and "curve" in labels):
                continue
            key = f"{spec.name}:{plan['label']}"
            ckpt = resolve_checkpoint(spec, state, plan["label"], int(plan["num_timesteps"]))
            out = em.EVAL_ROOT / spec.name / plan["label"]
            t0 = time.perf_counter()
            res = _run_evaluation(state, key, lambda: ev.evaluate_checkpoint(
                ckpt, out, settings=settings, deterministic_episodes=int(plan["deterministic_episodes"]),
                stochastic_episodes=int(plan["stochastic_episodes"]),
                expected_contracts=m7_contracts(horizon, exp.reward), label=plan["label"], preserve_all=True), out)
            ver = dr.verify_evaluation(res, exp.reward, horizon, plan)
            state["evaluations"][key].update(verification=ver, checkpoint=ec.repo_relative(ckpt),
                                             planned_deterministic=int(plan["deterministic_episodes"]),
                                             planned_stochastic=int(plan["stochastic_episodes"]),
                                             num_timesteps=int(plan["num_timesteps"]))
            save_state(state)
            agg = {m: (res["modes"][m]["aggregate"]) for m in res["modes"]}
            log(f"{key}: " + "; ".join(f"{m} targets {a.get('targets_mean')} clears {a.get('clears')} "
                                       f"falls {a.get('falls')} horizon {a.get('horizon_truncations')}"
                                       for m, a in agg.items())
                + f" ({time.perf_counter() - t0:.0f} s)"
                + ("" if ver["ok"] else " PROBLEMS " + str(ver["problems"][:3])))
            if not ver["ok"]:
                return EXIT_FAILED
    return EXIT_OK


def census() -> Dict[str, Any]:
    """Planned versus executed evaluation sessions and episodes; completion fails if any planned set is missing."""
    state = load_state()
    plan = em.evaluation_census_plan()
    rows: List[Dict[str, Any]] = []
    missing: List[str] = []
    executed_ep = {"deterministic": 0, "stochastic": 0, "random": 0}
    executed_sessions = 0
    for spec in em.matrix():
        exp = em.load_run(spec)
        for p in em.evaluation_plan(spec, exp):
            key = f"{spec.name}:{p['label']}"
            out = em.EVAL_ROOT / spec.name / p["label"]
            summary = out / "evaluation_summary.json"
            row: Dict[str, Any] = {"key": key, "run": spec.name, "label": p["label"],
                                   "num_timesteps": int(p["num_timesteps"]),
                                   "planned": {"deterministic": int(p["deterministic_episodes"]),
                                               "stochastic": int(p["stochastic_episodes"])},
                                   "present": summary.is_file()}
            if summary.is_file():
                doc = em.read_json(summary)
                got = {m: len((doc.get("modes") or {}).get(m, {}).get("episodes") or [])
                       for m in ("deterministic", "stochastic")}
                row["executed"] = got
                row["complete"] = got["deterministic"] == int(p["deterministic_episodes"]) \
                    and got["stochastic"] == int(p["stochastic_episodes"])
                for m in got:
                    executed_ep[m] += got[m]
                executed_sessions += sum(1 for m in got if got[m] > 0)
                if not row["complete"]:
                    missing.append(f"{key}: executed {got} != planned {row['planned']}")
            else:
                row["executed"] = {"deterministic": 0, "stochastic": 0}
                row["complete"] = False
                missing.append(f"{key}: no evaluation_summary.json")
            rows.append(row)
    rb = em.EVAL_ROOT / "random_baseline" / "evaluation_summary.json"
    rb_rows = 0
    if rb.is_file():
        doc = em.read_json(rb)
        rb_rows = len((doc.get("modes") or {}).get("random", {}).get("episodes") or [])
        executed_ep["random"] = rb_rows
        executed_sessions += 1
    if rb_rows != em.RANDOM_BASELINE_EPISODES:
        missing.append(f"random_baseline: executed {rb_rows} != planned {em.RANDOM_BASELINE_EPISODES}")
    total_exec = sum(executed_ep.values())
    return {"schema": "battleship_m7e_census_v1", "utc": utc_now(), "plan": plan, "rows": rows,
            "planned_sessions": plan["sessions"]["total"], "executed_sessions": executed_sessions,
            "planned_episodes": plan["total_episodes"], "executed_episodes": total_exec,
            "executed_by_mode": executed_ep, "missing": missing, "complete": not missing,
            "state_evaluations": sorted((state.get("evaluations") or {}).keys())}


def cmd_census(args: argparse.Namespace) -> int:
    cen = census()
    out = Path(args.out) if args.out else em.STATE_DIR / "census.json"
    em.write_json(out, cen)
    log(f"planned {cen['planned_episodes']} episodes in {cen['planned_sessions']} sessions; "
        f"executed {cen['executed_episodes']} in {cen['executed_sessions']} "
        f"({cen['executed_by_mode']})")
    for m in cen["missing"][:20]:
        log(f"  MISSING {m}")
    log(f"census -> {ec.repo_relative(out)} complete={cen['complete']}")
    return EXIT_OK if cen["complete"] else EXIT_FAILED


# -- replay of preserved artifacts through interactive native stepping -------------------------------------------------


def run_artifacts(spec: em.RunSpec, state: Mapping[str, Any]) -> List[Path]:
    dirs = [d / "workers" for d in dr._lineage_dirs(spec, state)] + [spec.eval_dir]
    out: List[Path] = []
    for root in dirs:
        if root.is_dir():
            out.extend(p.parent for p in root.rglob("metadata.json") if p.parent.parent.name == "artifacts")
    return sorted(out)


def _summary_break_ticks(spec: em.RunSpec, episode_id: str) -> Optional[List[int]]:
    for f in (spec.eval_dir.rglob("evaluation.json") if spec.eval_dir.is_dir() else []):
        for e in em.read_json(f).get("episodes") or []:
            if e.get("episode_id") == episode_id:
                return e.get("target_break_ticks")
    for d in dr._lineage_dirs(spec, state_or_empty()):
        p = d / "metrics" / "episodes.jsonl"
        if p.is_file():
            rows, _ = dr.jsonl_rows(p)
            for e in rows:
                if e.get("episode_id") == episode_id:
                    return e.get("target_break_ticks")
    return None


def state_or_empty() -> Dict[str, Any]:
    try:
        return load_state()
    except (OSError, ValueError):
        return {"runs": {}}


def cmd_replay(args: argparse.Namespace) -> int:
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    state = load_state()
    ok = True
    for spec in em.matrix():
        if args.only and spec.name not in args.only.split(","):
            continue
        exp = em.load_run(spec)
        arts = run_artifacts(spec, state)
        metas = []
        for a in arts:
            md = em.read_json(a / "metadata.json")
            metas.append((dr.objective_from_labels(md), str(a), md))
        if not metas:
            log(f"{spec.name}: no preserved artifact")
            continue
        metas.sort(key=lambda x: x[0], reverse=True)
        chosen = [metas[0]] + [m for m in metas[1:] if m[0][0] == 1]    # the best + every preserved clear
        out_dir = spec.replay_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        records = []
        for k, (key, path, md) in enumerate(chosen):
            work = out_dir / f"replay_{k:02d}_{Path(path).name[-8:]}"
            if work.exists():
                raise em.MatrixError(f"{work} exists (never overwritten)")
            rec = dr.replay_one(Path(path), work, executable=exp.executable, extra_env=dict(exp.extra_env),
                                index=9000 + k,
                                expected_break_ticks=_summary_break_ticks(spec, md.get("episode_id")))
            rec["objective_key"] = list(key)
            rec["is_clear_candidate"] = bool(key[0] == 1)
            records.append(rec)
            ok &= rec["ok"]
            log(f"{spec.name}: replay {md.get('episode_id')} objective {key}: ok={rec['ok']} {rec['checks']}")
        em.write_json(out_dir / "replay.json", {"run": spec.name, "artifacts_considered": len(metas),
                                                "replayed": records, "utc": utc_now(),
                                                "clears_verified": sum(1 for r in records
                                                                       if r.get("is_clear_candidate") and r["ok"]),
                                                "clear_candidates": sum(1 for r in records
                                                                        if r.get("is_clear_candidate"))})
    return EXIT_OK if ok else EXIT_FAILED


# -- the relevant permanent regression chain ---------------------------------------------------------------------------

# Sequential, one suite at a time, zero BattleShip.exe required before and after each, with the user configuration
# fingerprinted around every suite. M7e changes only the transition budget, so the relevant chain is the M7 stack
# plus everything that carries native replay truth: the frozen contracts and lifecycle (m7b/m7c), the M7 vector
# stack, the M6 flags M7e trains under, the interactive M1e/M2 stepping paths and the authoritative 468-row native
# replay with its checksum. Suites that need a hand-launched process (rl/m1e_replay_regression.py) are listed and
# reported, never silently skipped.
REGRESSION_CHAIN = (
    ("m7e_matrix", ["rl/m7e_matrix.py", "--test"], 900),
    ("m7e_analysis", ["rl/m7e_analysis.py", "--test"], 900),
    ("m7e_idle_analysis", ["rl/m7e_idle_analysis.py", "--test"], 1800),
    ("m7b_config_tests", ["rl/m7b_config_tests.py"], 1800),
    ("m7c_standby_tests_unit", ["rl/m7c_standby_tests.py", "unit"], 1800),
    ("m7_smoke_unit", ["rl/m7_smoke.py", "unit"], 1800),
    ("m7_smoke_native_replay", ["rl/m7_smoke.py", "isolation_boot_replay"], 1800),
    ("m7b_smoke", ["rl/m7b_smoke.py"], 3600),
    ("m6_equivalence", ["rl/m6_equivalence_regression.py"], 1800),
    ("m6_raphnet_bypass", ["rl/m6_raphnet_bypass_regression.py"], 3600),
    ("m2_restart_regression", ["rl/m2_restart_regression.py"], 1800),
    ("m2_lifecycle_smoke", ["rl/m2_lifecycle_smoke.py"], 1800),
)


def cmd_regressions(args: argparse.Namespace) -> int:
    import subprocess

    out_root = Path(args.root) if args.root else REPO_ROOT / "runs" / (
        "_m7e_regressions_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    out_root.mkdir(parents=True, exist_ok=True)
    only = set(args.only.split(",")) if args.only else None
    uc_before = dr.user_config_fingerprint()
    results: Dict[str, Any] = {}
    ok = True
    for name, argv, timeout in REGRESSION_CHAIN:
        if only and name not in only:
            continue
        pre = dr.system_state(label=f"before {name}")
        if pre["battleship_pids"]:
            log(f"{name}: BattleShip already running {pre['battleship_pids']}; chain stopped")
            results[name] = {"status": "BLOCKED", "battleship_before": pre["battleship_pids"]}
            ok = False
            break
        t0 = time.perf_counter()
        cmd = [sys.executable, "-u", str(REPO_ROOT / argv[0])] + argv[1:]
        rc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout, check=False)
        wall = round(time.perf_counter() - t0, 1)
        (out_root / f"{name}.log").write_text((rc.stdout or "") + (rc.stderr or ""), encoding="utf-8", newline="\n")
        post = dr.system_state(label=f"after {name}")
        uc = dr.user_config_fingerprint()
        entry = {"status": "PASS" if rc.returncode == 0 else "FAIL", "exit_code": rc.returncode, "wall_s": wall,
                 "command": " ".join(argv), "battleship_after": post["battleship_pids"],
                 "listeners_after": post["listening_ports_in_blocks"],
                 "user_config_sha256_unchanged": uc.get("sha256") == uc_before.get("sha256"),
                 "user_config_mtime_unchanged": uc.get("mtime_ns") == uc_before.get("mtime_ns"),
                 "tail": [ln for ln in (rc.stdout or "").strip().splitlines()[-4:]]}
        if post["battleship_pids"]:
            entry["status"] = "FAIL"
            entry["problem"] = "BattleShip processes left running"
        if not entry["user_config_sha256_unchanged"]:
            entry["status"] = "FAIL"
            entry["problem"] = "user configuration content changed"
        results[name] = entry
        ok &= entry["status"] == "PASS"
        log(f"{name}: {entry['status']} exit {rc.returncode} in {wall} s; processes left "
            f"{len(post['battleship_pids'])}; cfg sha256 unchanged {entry['user_config_sha256_unchanged']}")
        if entry["status"] != "PASS" and not args.keep_going:
            break
    try:
        dc = subprocess.run(["git", "diff", "--check"], cwd=str(REPO_ROOT), capture_output=True, text=True,
                            timeout=120, check=False)
        results["git_diff_check"] = {"status": "PASS" if dc.returncode == 0 else "FAIL",
                                    "exit_code": dc.returncode,
                                    "output": ((dc.stdout or "") + (dc.stderr or "")).strip()[:2000]}
        ok &= dc.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        results["git_diff_check"] = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
        ok = False
    record = {"schema": "battleship_m7e_regressions_v1", "milestone": em.MILESTONE, "phase": em.PHASE,
              "utc": utc_now(), "root": ec.repo_relative(out_root), "results": results,
              "user_config_before": uc_before, "user_config_after": dr.user_config_fingerprint(),
              "not_run_here": {"m1e_replay_regression":
                               "needs a hand-launched BattleShip in build-us/Release (see its docstring); run and "
                               "report it separately"},
              "passed": sum(1 for v in results.values() if v.get("status") == "PASS"),
              "suites": len(results), "ok": ok}
    em.write_json(out_root / "results.json", record)
    em.write_json(em.STATE_DIR / "regressions.json", record)
    log(f"regression chain: {record['passed']}/{record['suites']} PASS -> {ec.repo_relative(out_root)}")
    return EXIT_OK if ok else EXIT_FAILED


def cmd_status(args: argparse.Namespace) -> int:  # noqa: ARG001
    state = load_state()
    for spec in em.matrix():
        rs = (state.get("runs") or {}).get(spec.name) or {}
        log(f"{spec.order_index} {spec.name}: {rs.get('status', 'pending')} {rs.get('verification') or ''}")
    evs = state.get("evaluations") or {}
    log(f"evaluations recorded: {len(evs)}")
    for k, v in sorted(evs.items()):
        log(f"  {k}: {v.get('wall_s')} s ok={((v.get('verification') or {}).get('ok'))}")
    return EXIT_OK


def _raise_keyboard_interrupt(signum, frame):  # noqa: ARG001 - signal handler signature
    raise KeyboardInterrupt(f"signal {signum}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("manifest")
    m.add_argument("--out", default=None)
    m.add_argument("--no-trainer-view", action="store_true")
    r = sub.add_parser("resources")
    r.add_argument("--label", default="M7e resource gate")
    r.add_argument("--cpu-samples", type=int, default=3)
    t = sub.add_parser("train")
    t.add_argument("--only", default=None, help="one run name (default: the whole matrix in order)")
    t.add_argument("--resume", default=None, help="continue this run's own lineage from its latest checkpoint set")
    t.add_argument("--skip-resource-gate", action="store_true",
                   help="the gate was recorded separately by 'resources' immediately before")
    e = sub.add_parser("evaluate")
    e.add_argument("--only", default=None, help="comma-separated run names")
    e.add_argument("--labels", default=None, help="comma-separated labels: initial, final, curve (default: all)")
    e.add_argument("--skip-random", action="store_true")
    e.add_argument("--allow-unverified", action="store_true")
    c = sub.add_parser("census")
    c.add_argument("--out", default=None)
    rp = sub.add_parser("replay")
    rp.add_argument("--only", default=None)
    rg = sub.add_parser("regressions")
    rg.add_argument("--root", default=None)
    rg.add_argument("--only", default=None, help="comma-separated suite names")
    rg.add_argument("--keep-going", action="store_true", help="continue after a failing suite")
    sub.add_parser("status")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _raise_keyboard_interrupt)
    fn = {"manifest": cmd_manifest, "resources": cmd_resources, "train": cmd_train, "evaluate": cmd_evaluate,
          "census": cmd_census, "replay": cmd_replay, "regressions": cmd_regressions,
          "status": cmd_status}[args.command]
    try:
        return fn(args)
    except em.MatrixError as exc:
        log(f"ERROR {exc}")
        return EXIT_FAILED
    except KeyboardInterrupt:
        log("interrupted")
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
