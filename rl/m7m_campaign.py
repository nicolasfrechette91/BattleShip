#!/usr/bin/env python3
"""M7m campaign driver: the bounded paired comparison of anchored backward starts (arm E) against tick-0 starts (arm K),
both warm-started from the pinned Phase K reward-v2 finals.

Design: docs/rl_sweep_consolidation_m7m_design.md. Registration: docs/rl_sweep_consolidation_m7m_manifest.json and
docs/rl_sweep_consolidation_m7m_decision_rule.json (frozen before any training). Campaign outputs: runs/m7m/campaign;
pilot outputs: runs/m7m/pilot (separate; never campaign inputs). Everything else is read only.

    python rl/m7m_campaign.py manifest              # write the rule (write-once) and the manifest; refused once frozen
    python rl/m7m_campaign.py pilot                 # the registered integration pilot (E then K, +40,960 each) + checks
    python rl/m7m_campaign.py train [--dry-run]     # E0, K0, E1, K1, E2, K2, each behind the launch gate
    python rl/m7m_campaign.py evaluate              # curve points + final, tick-0 only (1,980 episodes)
    python rl/m7m_campaign.py verify-clears | census | status
    python rl/m7m_campaign.py analyze [--dry-run]   # the registered rule, recorded once (never re-decided)
    python rl/m7m_campaign.py all                   # pilot -> train -> evaluate -> verify-clears -> analyze

Stops (registered): a failed launch gate, a monitor hard alert, the in-run memory policy, manifest drift, a provenance
mismatch, a process leak, a failed pilot check, a failed training verification, an evaluation label that fails its one
re-run. A stopped run directory is moved to _partial by the guard and kept; nothing is resumed, relaunched or extended.
Native RNG state is never inspected, logged, validated, controlled, compared or hashed.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import pickle
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
import m7m_analysis as mn  # noqa: E402
import m7m_anchor as ma  # noqa: E402
import m7m_matrix as mm  # noqa: E402

REPO_ROOT = RL_DIR.parent
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_INTERRUPTED = 0, 1, 2, 130
NOT_COUNTED_ENDS = ("lifecycle_failure", "aborted")

GATE_FN: Optional[Callable[[], Dict[str, Any]]] = None      # test stand-ins only
LAUNCHER: Optional[Callable[..., Dict[str, Any]]] = None
SLEEP: Callable[[float], None] = time.sleep


def log(message: str) -> None:
    print(f"[m7m-campaign {time.strftime('%H:%M:%S')}] {message}", flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_jsonl(p: Path) -> List[Dict[str, Any]]:
    if not Path(p).is_file():
        return []
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]


# -- state ------------------------------------------------------------------------------------------------------------


def state_file() -> Path:
    return mm.state_dir() / "state.json"


def load_state() -> Dict[str, Any]:
    if state_file().is_file():
        return mm.read_json(state_file())
    return {"schema": "battleship_m7m_campaign_state_v1", "milestone": mm.MILESTONE, "created_utc": utc_now(),
            "pilot": {}, "runs": {}, "evaluations": {}, "clears": {}, "decisions": {}, "events": []}


def save_state(state: Dict[str, Any]) -> None:
    state["updated_utc"] = utc_now()
    mm.write_json(state_file(), state)


def event(state: Dict[str, Any], kind: str, **data: Any) -> None:
    state.setdefault("events", []).append(dict(kind=kind, utc=utc_now(), **data))
    save_state(state)


# -- the manifest ----------------------------------------------------------------------------------------------------


def frozen_manifest_path() -> Path:
    return mm.state_dir() / "manifest.json"


def load_manifest(*, freeze: bool) -> Dict[str, Any]:
    fp = frozen_manifest_path()
    if fp.is_file():
        man = mm.read_json(fp)
        if mm.MANIFEST_DOC.is_file() and mm.read_json(mm.MANIFEST_DOC) != man:
            raise mm.MatrixError(f"{ec.repo_relative(mm.MANIFEST_DOC)} differs from the frozen copy")
        return man
    if not mm.MANIFEST_DOC.is_file():
        raise mm.MatrixError(f"{ec.repo_relative(mm.MANIFEST_DOC)} missing: run 'python rl/m7m_campaign.py manifest'")
    man = mm.read_json(mm.MANIFEST_DOC)
    if freeze:
        mm.write_json(fp, man)
    return man


def cmd_manifest(args: argparse.Namespace) -> int:
    if frozen_manifest_path().is_file() and not args.out:
        log(f"refused: the campaign froze its manifest at {ec.repo_relative(frozen_manifest_path())}; never rebuilt")
        return EXIT_USAGE
    rule_sha = mn.write_rule()
    man = mm.build_manifest()
    out = Path(args.out) if args.out else mm.MANIFEST_DOC
    mm.write_json(out, man)
    log(f"rule {rule_sha[:12]}; manifest -> {ec.repo_relative(out)} ok={man['ok']} code {man['code']['sha256'][:12]} "
        f"({man['code']['files']} files)")
    for p in man["problems"]:
        log(f"  PROBLEM {p}")
    return EXIT_OK if man["ok"] else EXIT_FAILED


# -- resources --------------------------------------------------------------------------------------------------------


def wait_for_launch_gate(tag: str) -> Dict[str, Any]:
    readings: List[Dict[str, Any]] = []
    last: Dict[str, Any] = {}
    for i in range(mm.LAUNCH_GATE_READINGS):
        last = (GATE_FN or g.launch_gate)()
        m = last.get("measurement") or {}
        readings.append({"utc": utc_now(), "ok": last["ok"], "problems": last["problems"],
                         "measurement": {k: m.get(k) for k in ("avail_commit_gib", "avail_phys_gib", "disk_free_gib",
                                                              "cpu_mean_pct", "battleship_pids", "listeners")}})
        if last["ok"]:
            return {"ok": True, "tag": tag, "readings": readings, "problems": []}
        if i < mm.LAUNCH_GATE_READINGS - 1:
            log(f"{tag}: launch gate reading {i + 1} failed {last['problems']}; re-measuring in "
                f"{mm.LAUNCH_GATE_RETRY_S:.0f} s")
            SLEEP(mm.LAUNCH_GATE_RETRY_S)
    return {"ok": False, "tag": tag, "readings": readings, "problems": last.get("problems")}


# -- run verification (pilot and campaign) ---------------------------------------------------------------------------


def run_identity(spec: mm.RunSpec, manifest: Mapping[str, Any]) -> List[str]:
    from btt_rewards import REWARD_V2
    from m7_runtime import portable_path

    rj = mm.read_json(spec.run_dir / "run.json")
    p: List[str] = []
    if (rj.get("executable") or {}).get("sha256") != (manifest.get("executable") or {}).get("sha256"):
        p.append("run.json executable differs from the manifest")
    rev, mrev = rj.get("revisions") or {}, manifest.get("revisions") or {}
    if rev.get("head") != mrev.get("head") or {s["path"]: s["commit"] for s in rev.get("submodules") or []} != \
            mrev.get("submodules"):
        p.append("run.json revisions differ from the manifest")
    if (rj.get("contracts") or {}).get("policy_observation_contract") != "btt_policy_obs_v1":
        p.append("run.json observation contract")
    if (rj.get("ppo") or {}).get("policy") != "MlpPolicy" or rj.get("policy_network") is not None:
        p.append("run.json policy / network")
    if rj.get("reward_contract") != REWARD_V2.to_json():
        p.append("run.json reward contract is not btt_reward_v2")
    if dict(rj.get("m6_flags") or {}) != dict(mm.M6_FLAGS, **mm.DIAG_FLAG):
        p.append(f"run.json native flags {rj.get('m6_flags')}")
    cfg = rj.get("config") or {}
    if cfg.get("anchor_curriculum") != ma.registered_table(tick0_probability=spec.tick0_probability,
                                                          observation_table_sha256=mm.OBS_TABLE_SHA256) \
            or cfg.get("curriculum") is not None:
        p.append(f"run.json curriculum tables {cfg.get('anchor_curriculum')} / {cfg.get('curriculum')}")
    lin = rj.get("lineage") or []
    warm = mm.read_json(spec.warm_start / "checkpoint.json")
    if len(lin) != 1:
        p.append(f"lineage has {len(lin)} segments (a warm start has exactly one)")
    else:
        seg = lin[0]
        wsc = seg.get("warm_start_change") or {}
        acc = (wsc.get("accepted_diffs") or {}).get("environment.extra_env") or {}
        want_req = dict(acc.get("checkpoint") or {}, **mm.DIAG_FLAG)
        if seg.get("checkpoint") != portable_path(spec.warm_start) or seg.get("run_id") != f"m7g_s{spec.seed}_v1" \
                or int(seg.get("num_timesteps") or -1) != mm.WARM_START_T or seg.get("files") != warm.get("files"):
            p.append(f"lineage segment is not the pinned warm start: {seg.get('checkpoint')} {seg.get('run_id')} "
                     f"{seg.get('num_timesteps')}")
        if sorted(wsc.get("accepted_diffs") or {}) != ["environment.extra_env"] or acc.get("requested") != want_req \
                or dict(acc.get("checkpoint") or {}) != mm.M6_FLAGS:
            p.append(f"warm-start change is not exactly the diagnostic flag: {wsc}")
    return p


def continuation(spec: mm.RunSpec) -> Dict[str, Any]:
    """Actual PPO updates and continuation of optimizer, timesteps and statistics from the warm start."""
    import m7_evaluation as me
    from m7_trainer import M7PPO

    rollouts = spec.additional // mm.ROLLOUT
    fin = spec.run_dir / "final"
    meta = mm.read_json(fin / "checkpoint.json")
    model = M7PPO.load(str(fin / "model.zip"), device="cpu")
    steps = sorted({int(v["step"]) for v in model.policy.optimizer.state_dict()["state"].values()})
    with open(fin / "vecnormalize.pkl", "rb") as fp:
        vn = pickle.load(fp)
    with open(spec.warm_start / "vecnormalize.pkl", "rb") as fp:
        warm_count = float(pickle.load(fp).obs_rms.count)
    warm = next(w for w in mm.read_json(mm.PLAN_DOC)["warm_starts"] if int(w["seed"]) == spec.seed)
    ro = read_jsonl(spec.run_dir / "metrics" / "rollouts.jsonl")
    got = {"num_timesteps": meta.get("num_timesteps"), "n_updates": meta.get("n_updates"), "adam_steps": steps,
           "policy_digest": me.policy_parameter_digest(model), "obs_rms_count": float(vn.obs_rms.count),
           "rollout_records": len(ro), "rollouts_with_train_metrics": sum(1 for r in ro if r.get("train_metrics")),
           "last_rollout_num_timesteps": ro[-1].get("num_timesteps") if ro else None}
    want = {"num_timesteps": spec.total, "n_updates": mm.WARM_N_UPDATES + rollouts * mm.N_EPOCHS,
            "adam_steps": [mm.WARM_ADAM_STEP + rollouts * mm.N_EPOCHS * mm.MINIBATCHES],
            "obs_rms_count": warm_count + 5 + spec.additional, "rollout_records": rollouts,
            "rollouts_with_train_metrics": rollouts, "last_rollout_num_timesteps": spec.total}
    p = [f"{k}: {got[k]} != {want[k]}" for k in want if not (
        abs(got[k] - want[k]) < 1e-6 if k == "obs_rms_count" else got[k] == want[k])]
    if got["policy_digest"] == warm["policy_parameter_digest"]:
        p.append("the policy parameters equal the warm start (no PPO update)")
    return {"got": got, "want": want, "warm_policy_digest": warm["policy_parameter_digest"], "problems": p, "ok": not p}


def accounting(spec: mm.RunSpec) -> Dict[str, Any]:
    return accounting_dir(spec.run_dir, arm=spec.arm, base_seed=spec.base_seed, p0=spec.tick0_probability,
                          additional=spec.additional, pilot=spec.pilot)


def accounting_dir(run_dir: Path, *, arm: str, base_seed: int, p0: float, additional: int, pilot: bool,
                   n_envs: int = 5) -> Dict[str, Any]:
    """Policy-only accounting, E/K start behaviour and the schedule re-simulated from its own log (draws, outcomes,
    blocks, the in-flight rule) against the final checkpoint's schedule state."""
    sel = read_jsonl(run_dir / "curriculum" / "selection.jsonl")
    rows, _ = dr.jsonl_rows(run_dir / "metrics" / "episodes.jsonl")
    fin = mm.read_json(run_dir / "final" / "anchor_schedule.json")
    p: List[str] = []
    init = [e for e in sel if e.get("event") == "initial_reset"]
    if len(init) != 1 or init[0].get("envs") != n_envs:
        p.append(f"initial resets {init}")
    sched = ma.AnchorSchedule(base_seed, tick0_probability=p0)
    draws_bad = sched_bad = 0
    selects = outcomes = 0
    pending: Dict[tuple, Dict[str, Any]] = {}
    delivered = anchored_selects = 0
    prefix_ticks = 0
    for e in sel:
        ev = e.get("event")
        if ev == "outcome":
            outcomes += 1
            o = ma.Outcome(kind=e["kind"], tau=int(e["tau"]), window_index=e.get("window_index"),
                           success=bool(e["success"]), end_reason=e.get("end_reason"),
                           counted_end=e.get("end_reason") not in NOT_COUNTED_ENDS)
            if json.loads(json.dumps(sched.ingest(o))) != e.get("schedule"):
                sched_bad += 1
        elif ev == "select":
            selects += 1
            kind, tau, k, draws = sched.draw()
            if kind != e["kind"] or draws != {x: e[x] for x in ("u1", "u2") if x in e} or \
                    (kind == ma.START_ANCHOR and (tau != e.get("tau") or k != e.get("window_index"))):
                draws_bad += 1
            if kind == ma.START_ANCHOR:
                anchored_selects += 1
                pending[(e["vec_step"], e["env"])] = e
        elif ev == "delivered":
            delivered += 1
            s = pending.pop((e["vec_step"], e["env"]), None)
            if s is None or (e["kind"] == ma.START_ANCHOR and e.get("prefix_length") != s.get("tau")):
                p.append(f"delivery without its anchored draw: {e}")
            if e["kind"] == ma.START_ANCHOR:
                prefix_ticks += int(e["prefix_length"])
    if draws_bad or sched_bad:
        p.append(f"re-simulated schedule disagrees with the log: {draws_bad} draws, {sched_bad} schedule events")
    st, fs = sched.state_json(), fin.get("schedule") or {}
    for k in ("k", "complete", "blocks", "block_n", "block_s", "draws", "counts"):
        if json.loads(json.dumps(st[k])) != fs.get(k):
            p.append(f"final schedule state {k}: log {st[k]} != checkpoint {fs.get(k)}")
    if pending:
        p.append(f"{len(pending)} anchored draws never delivered")
    kinds: Dict[str, int] = {}
    steps_sum = 0
    for r in rows:
        o, h = r.get("m7m") or {}, r.get("m7h") or {}
        kinds[str(o.get("kind"))] = kinds.get(str(o.get("kind")), 0) + 1
        steps_sum += int(r.get("steps") or 0)
        if not o or int(h.get("prefix_length") or 0) != int(o.get("tau") or 0) or not h.get("rows_equal_prefix_plus_policy"):
            p.append(f"row {r.get('episode_id')}: m7m {o.get('kind')} tau {o.get('tau')} / m7h prefix "
                     f"{h.get('prefix_length')} rows_equal {h.get('rows_equal_prefix_plus_policy')}")
    if outcomes != len(rows):
        p.append(f"{outcomes} logged outcomes != {len(rows)} rows")
    if not (additional - n_envs * ma.HORIZON <= steps_sum <= additional):
        p.append(f"finished-episode policy steps {steps_sum} outside [{additional - n_envs * ma.HORIZON}, {additional}]")
    rep = fin.get("stats") or {}
    if int(rep.get("prefix_ticks") or 0) != prefix_ticks:
        p.append(f"prefix ticks {rep.get('prefix_ticks')} != logged deliveries {prefix_ticks}")
    if arm == "K" and (anchored_selects or delivered or prefix_ticks or kinds.get(ma.START_ANCHOR)):
        p.append(f"K arm anchored: draws {anchored_selects}, deliveries {delivered}, prefix ticks {prefix_ticks}")
    if arm == "E" and pilot and not (delivered >= 1 and kinds.get(ma.START_ANCHOR, 0) >= 1):
        p.append("E pilot: no anchored start delivered and finished")
    return {"selects": selects, "anchored_draws": anchored_selects, "deliveries": delivered, "outcomes": outcomes,
            "rows": len(rows), "row_kinds": kinds, "policy_steps_finished": steps_sum, "prefix_ticks": prefix_ticks,
            "prefix_dispatch_wall_s": rep.get("dispatch_wall_s"), "prefix_dispatches": rep.get("prefix_dispatches"),
            "max_dispatch_wall_s": rep.get("max_dispatch_wall_s"), "schedule": {k: st[k] for k in (
                "k", "pointer", "complete", "blocks", "counts")},
            "problems": p[:30], "ok": not p}


def verify_run(spec: mm.RunSpec, exp: ec.Experiment, manifest: Mapping[str, Any]) -> Dict[str, Any]:
    ver = dr.verify_training_run(spec.run_dir, exp, fresh=False, expected_start=mm.WARM_START_T)
    extra: List[str] = []
    ver["m7m_identity"] = run_identity(spec, manifest)
    extra += ver["m7m_identity"]
    for name, fn in (("continuation", continuation), ("accounting", accounting)):
        try:
            r = fn(spec)
        except Exception as exc:  # noqa: BLE001 - a verification that cannot run fails
            r = {"problems": [f"{type(exc).__name__}: {exc}"], "ok": False}
        ver[name] = r
        extra += [f"{name}: {x}" for x in r["problems"]]
    if extra:
        ver["problems"].extend(extra)
        ver["ok"] = False
    return ver


def _guarded_launch(*, spec: mm.RunSpec, exp: ec.Experiment, **_: Any) -> Dict[str, Any]:
    tag = f"{spec.name}__{stamp()}"
    gr = mm.guard_root(spec.pilot)
    default = mm.PILOT_ROOT if spec.pilot else mm.DEFAULT_ROOT
    return g.train_guarded(config=spec.config_path, run_dir=spec.run_dir, log_path=gr / "logs" / f"{tag}.log",
                           monitor_path=gr / "monitor" / f"{tag}.jsonl", probe_path=gr / "probe" / f"{tag}.jsonl",
                           contract=exp.reward, horizon=int(exp.values["environment.horizon"]),
                           partial_root=mm.partial_root(spec.pilot),
                           output_root=None if mm.root(spec.pilot) == default else spec.run_dir.parent)


def launch_and_verify(state: Dict[str, Any], spec: mm.RunSpec, manifest: Mapping[str, Any], *, gate: Dict[str, Any],
                      book: Dict[str, Any]) -> bool:
    """One guarded launch, then the full verification. Returns True only for a verified run."""
    exp = mm.load_run(spec)
    book["launch_gate"] = gate
    log(f"{spec.name}: launching (arm {spec.arm}, pair {spec.seed}, +{spec.additional:,} policy transitions from "
        f"{ec.repo_relative(spec.warm_start)})")
    t0 = time.perf_counter()
    res = (LAUNCHER or _guarded_launch)(spec=spec, exp=exp, manifest=manifest)
    book.setdefault("attempts", []).append({
        "utc": utc_now(), "wall_s": round(time.perf_counter() - t0, 1), "exit_code": res.get("exit_code"),
        "stop_kind": res.get("stop_kind"), "moved_to": res.get("moved_to"),
        "probe": {k: (res.get("probe") or {}).get(k) for k in ("min_avail_commit_gib", "min_avail_phys_gib",
                                                                "max_commit_used_gib")},
        "commit_drawn_gib": res.get("commit_drawn_gib"), "leftover_battleship_pids": res.get("leftover_battleship_pids"),
        "monitor": {k: (res.get("monitor") or {}).get(k) for k in (
            "max_battleship_processes", "max_battleship_listeners", "hard_alerts", "soft_alert_count", "episodes_seen",
            "episode_ends", "lifecycle_failures")},
        "log": ec.repo_relative(Path(res["log"])) if res.get("log") else None})
    if res.get("stop_kind"):
        book["status"] = "stopped"
        event(state, "run_stopped", run=spec.name, stop_kind=res["stop_kind"], moved_to=res.get("moved_to"))
        log(f"{spec.name}: STOPPED ({res['stop_kind']}); preserved at {res.get('moved_to')}")
        return False
    if res.get("exit_code") != 0:
        book["status"] = "failed"
        save_state(state)
        log(f"{spec.name}: trainer exit {res.get('exit_code')}; the directory stays (partial); see the guard log")
        return False
    if res.get("leftover_battleship_pids"):
        book["status"] = "failed"
        event(state, "process_leak", run=spec.name, pids=res["leftover_battleship_pids"])
        log(f"{spec.name}: BattleShip processes left after the run {res['leftover_battleship_pids']}")
        return False
    ver = verify_run(spec, exp, manifest)
    mm.write_json(mm.state_dir() / "verify" / f"{spec.name}.json", ver)
    book.update(status="verified" if ver["ok"] else "verification_failed", verification=ver["problems"][:20],
                accounting={k: (ver.get("accounting") or {}).get(k) for k in (
                    "anchored_draws", "deliveries", "rows", "row_kinds", "policy_steps_finished", "prefix_ticks",
                    "prefix_dispatch_wall_s", "schedule")},
                continuation=(ver.get("continuation") or {}).get("got"))
    save_state(state)
    log(f"{spec.name}: {'verified' if ver['ok'] else 'verification FAILED ' + str(ver['problems'][:3])}")
    return bool(ver["ok"])


# -- the pilot --------------------------------------------------------------------------------------------------------


def cmd_pilot(args: argparse.Namespace) -> int:  # noqa: ARG001
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    state = load_state()
    if (state.get("pilot") or {}).get("ok"):
        log("the pilot already passed; it runs once")
        return EXIT_OK
    if (state.get("pilot") or {}).get("status") in ("failed", "stopped"):
        log(f"the pilot {state['pilot']['status']}; the campaign stops (one pilot, never relaunched)")
        return EXIT_FAILED
    manifest = load_manifest(freeze=True)
    drift = mm.manifest_drift(manifest)
    if drift:
        log(f"BLOCKED manifest drift {drift}")
        return EXIT_FAILED
    pilot = state.setdefault("pilot", {})
    pilot.setdefault("runs", {})
    pilot["status"] = "running"
    report: Dict[str, Any] = {"registered_cap": mm.PILOT_TRANSITIONS, "runs": {}, "started_utc": utc_now()}
    for spec in mm.pilot_matrix():
        book = pilot["runs"].setdefault(spec.name, {"status": "pending"})
        if book.get("status") == "verified" and book.get("evaluation_ok"):
            continue
        if spec.run_dir.exists():
            pilot["status"] = "failed"
            event(state, "pilot_directory_exists", run=spec.name)
            log(f"{spec.name}: a pilot directory already exists (never relaunched); stopping")
            return EXIT_FAILED
        leftover = dr.system_state(label=f"before {spec.name}")["battleship_pids"]
        gate = wait_for_launch_gate(spec.name)
        if leftover or not gate["ok"]:
            pilot["status"] = "stopped"
            event(state, "pilot_gate_refused", run=spec.name, gate=gate, leftover=leftover)
            log(f"{spec.name}: launch gate refused {gate['problems']} / leftover {leftover}; stopping")
            return EXIT_FAILED
        ok = launch_and_verify(state, spec, manifest, gate=gate, book=book)
        if ok:
            exp = mm.load_run(spec)
            plan = mm.evaluation_plan(spec, exp)[0]
            r = evaluate_label(state, spec, exp, plan, manifest)
            v = r.get("verification") or {}
            book["evaluation_ok"] = bool(r.get("ran") and v.get("ok"))
            book["evaluation"] = {"problems": r.get("provenance_problems") or v.get("problems"),
                                  "tick0": v.get("tick0")}
            ok = book["evaluation_ok"]
        report["runs"][spec.name] = dict(book)
        save_state(state)
        if not ok:
            pilot["status"] = "failed"
            event(state, "pilot_failed", run=spec.name)
            mm.write_json(mm.root(True) / "pilot_report.json", report)
            log(f"{spec.name}: pilot check FAILED; the campaign stops")
            return EXIT_FAILED
    report["finished_utc"] = utc_now()
    report["ok"] = True
    mm.write_json(mm.root(True) / "pilot_report.json", report)
    pilot.update(status="passed", ok=True, report=ec.repo_relative(mm.root(True) / "pilot_report.json"),
                 report_sha256=mm.sha256_file(mm.root(True) / "pilot_report.json"))
    event(state, "pilot_passed")
    log("pilot passed (E and K): PPO updates, continuation, policy-only accounting, start behaviour, evaluation smoke")
    return EXIT_OK


# -- campaign training ------------------------------------------------------------------------------------------------


def run_status(spec: mm.RunSpec, state: Mapping[str, Any]) -> str:
    st = ((state.get("runs") or {}).get(spec.name) or {}).get("status")
    if st == "verified":
        return "verified"
    if st in ("stopped", "failed", "verification_failed", "gate_refused"):
        return st
    if not spec.run_dir.exists():
        return "absent"
    summ = spec.run_dir / "training_summary.json"
    if summ.is_file() and mm.read_json(summ).get("status") == "completed":
        return "completed_unverified"
    return "partial"


def train_plan(state: Mapping[str, Any]) -> List[Dict[str, Any]]:
    plan, blocked = [], False
    for spec in mm.matrix():
        st = run_status(spec, state)
        if st == "verified":
            plan.append({"run": spec.name, "status": st, "action": "skip"})
            continue
        if blocked:
            plan.append({"run": spec.name, "status": st, "action": "wait"})
            continue
        action = {"absent": "train", "completed_unverified": "verify"}.get(
            st, f"STOP: {spec.name} is {st} (preserved; never resumed or relaunched)")
        plan.append({"run": spec.name, "status": st, "action": action})
        blocked = True
    return plan


def preflight(state: Mapping[str, Any], manifest: Mapping[str, Any]) -> Dict[str, Any]:
    p: List[str] = list(mm.manifest_drift(manifest))
    if not (state.get("pilot") or {}).get("ok"):
        p.append("the integration pilot has not passed")
    for s in mm.matrix():
        exp = mm.load_run(s)
        bad = [k for k, ok in mm.arm_checks(s, exp).items() if not ok]
        r = (manifest.get("runs") or {}).get(s.name) or {}
        if bad:
            p.append(f"{s.name}: {bad}")
        if (r.get("source_sha256"), r.get("semantic_fingerprint"), r.get("compatibility_fingerprint")) != \
                (exp.source.sha256, exp.semantic_fingerprint, exp.compatibility_fingerprint):
            p.append(f"{s.name}: profile differs from the manifest")
    for s in mm.SEEDS:
        w = mm.warm_start_identity(s)
        if not w["ok"] or w["files_sha256"] != ((manifest.get("warm_starts") or {}).get(str(s)) or {}).get("files_sha256"):
            p.append(f"warm start s{s}: {w['problems'] or 'differs from the manifest'}")
    return {"problems": p, "ok": not p}


def cmd_train(args: argparse.Namespace) -> int:
    from m7_runtime import install_kill_on_close_job

    state = load_state()
    manifest = load_manifest(freeze=False)
    pf = preflight(state, manifest)
    plan = train_plan(state)
    if args.dry_run:
        print(json.dumps({"plan": plan, "preflight": pf}, indent=1, default=str), flush=True)
        log(f"dry run: nothing launched; blocking problems {len(pf['problems'])}")
        return EXIT_OK if pf["ok"] else EXIT_FAILED
    if not pf["ok"]:
        for p in pf["problems"]:
            log(f"BLOCKED {p}")
        event(state, "train_blocked", problems=pf["problems"][:20])
        return EXIT_FAILED
    install_kill_on_close_job()
    event(state, "train_invocation", plan=plan)
    handled: set = set()
    while True:
        step = next((s for s in train_plan(state) if s["action"] != "skip"), None)
        if step is None:
            log("every campaign run is verified")
            return EXIT_OK
        spec = mm.run_by_name(step["run"])
        if step["action"].startswith(("STOP", "wait")) or spec.name in handled:
            log(f"{spec.name}: {step['action']}; stopping")
            return EXIT_FAILED
        handled.add(spec.name)
        book = state["runs"].setdefault(spec.name, {"status": "pending"})
        if step["action"] == "verify":
            ver = verify_run(spec, mm.load_run(spec), manifest)
            mm.write_json(mm.state_dir() / "verify" / f"{spec.name}.json", ver)
            book.update(status="verified" if ver["ok"] else "verification_failed", verification=ver["problems"][:20])
            save_state(state)
            if not ver["ok"]:
                return EXIT_FAILED
            continue
        drift = mm.manifest_drift(manifest)
        leftover = dr.system_state(label=f"before {spec.name}")["battleship_pids"]
        if drift or leftover:
            event(state, "blocked_before_launch", run=spec.name, drift=drift, leftover=leftover)
            log(f"{spec.name}: drift {drift} / leftover {leftover}; stopping")
            return EXIT_FAILED
        gate = wait_for_launch_gate(spec.name)
        if not gate["ok"]:
            book.update(status="gate_refused", launch_gate=gate)
            event(state, "launch_gate_refused", run=spec.name, gate=gate)
            log(f"{spec.name}: launch gate refused {gate['problems']}; stopping")
            return EXIT_FAILED
        if not launch_and_verify(state, spec, manifest, gate=gate, book=book):
            return EXIT_FAILED


# -- evaluation (tick-0 only) -----------------------------------------------------------------------------------------


def checkpoint_for(spec: mm.RunSpec, label: str, t: int) -> Path:
    return spec.run_dir / "final" if label == "final" else spec.run_dir / "checkpoints" / f"ckpt_{t:09d}"


def checkpoint_provenance(ckpt: Path, spec: mm.RunSpec, exp: ec.Experiment, planned_t: int,
                          manifest: Mapping[str, Any]) -> List[str]:
    import m7_trainer as tr
    from m7_evaluation import CheckpointError, read_checkpoint_set

    try:
        meta = read_checkpoint_set(ckpt, expected_contracts=tr.run_contracts(tr.config_from_experiment(exp)))
    except (CheckpointError, OSError, ValueError) as exc:
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
    if (meta.get("seeds") or {}).get("base_seed") != spec.base_seed:
        p.append(f"base_seed {(meta.get('seeds') or {}).get('base_seed')} != {spec.base_seed}")
    if (meta.get("executable") or {}).get("sha256") != (manifest.get("executable") or {}).get("sha256"):
        p.append("executable sha256 differs from the manifest")
    rev, mrev = meta.get("revisions") or {}, manifest.get("revisions") or {}
    if rev.get("head") != mrev.get("head") or {s["path"]: s["commit"] for s in rev.get("submodules") or []} != \
            mrev.get("submodules"):
        p.append("revisions differ from the manifest")
    if (meta.get("ppo") or {}).get("policy") != "MlpPolicy" or meta.get("policy_network") is not None:
        p.append("policy / network identity")
    lc = meta.get("lifecycle") or {}
    if (lc.get("standby_preboot"), lc.get("standby_count")) != (True, 1):
        p.append(f"lifecycle {lc}")
    if meta.get("interruption"):
        p.append("an interrupted set is never evaluated")
    if set(meta.get("extra_files") or {}) != {"anchor_schedule.json"}:
        p.append(f"extra files {sorted(meta.get('extra_files') or {})} (expected the anchor schedule state)")
    return p


def run_eval_label(state: Dict[str, Any], key: str, out_dir: Path, fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    import m7g_k_run as kr   # measurement only (preconditions)
    from m7_runtime import BATTLESHIP_IMAGE, wait_until_no_process

    done = out_dir / "evaluation_summary.json"
    if done.is_file():
        return mm.read_json(done)
    if out_dir.exists():
        aside = out_dir.with_name(out_dir.name + "__incomplete_" + stamp())
        out_dir.rename(aside)
        event(state, "incomplete_evaluation_moved_aside", key=key, to=ec.repo_relative(aside))
    pre = kr.preconditions(f"before evaluation {key}")
    if pre["problems"]:
        raise mm.MatrixError(f"evaluation {key}: preconditions failed: {pre['problems']}")
    book = state.setdefault("evaluations", {}).setdefault(key, {})
    book["attempts"] = int(book.get("attempts") or 0) + 1
    save_state(state)
    monitor = dr.Monitor(out=mm.state_dir() / "monitor" / "evaluation.jsonl", root_pid=os.getpid()).start()
    t0 = time.perf_counter()
    try:
        result = fn()
    finally:
        mon = monitor.stop()
    leftover = wait_until_no_process(BATTLESHIP_IMAGE, timeout=30.0)
    book.update(wall_s=round(time.perf_counter() - t0, 1), finished_utc=utc_now(), leak_free=not leftover,
                monitor_hard_alerts=mon.get("hard_alerts"), max_battleship_processes=mon.get("max_battleship_processes"),
                out_dir=ec.repo_relative(out_dir))
    save_state(state)
    if mon.get("hard_alerts") or leftover:
        raise mm.MatrixError(f"evaluation {key}: monitor alerts {mon.get('hard_alerts')} / leaked {leftover}")
    return result


def evaluate_label(state: Dict[str, Any], spec: mm.RunSpec, exp: ec.Experiment, plan: Mapping[str, Any],
                   manifest: Mapping[str, Any]) -> Dict[str, Any]:
    import m7_evaluation as ev
    import m7_trainer as tr
    import m7g_k_run as kr
    import m7h_verify as mv

    key = f"{spec.name}:{plan['label']}"
    ckpt = checkpoint_for(spec, plan["label"], int(plan["num_timesteps"]))
    prov = checkpoint_provenance(ckpt, spec, exp, int(plan["num_timesteps"]), manifest)
    if prov:
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
    for mode, r in (res.get("modes") or {}).items():
        if dict(r.get("extra_env") or {}) != dict(mm.M6_FLAGS, **mm.DIAG_FLAG):
            ver["problems"].append(f"{mode}: evaluation flags {r.get('extra_env')}")
    t0 = mv.verify_eval_tick0(out)
    ver["tick0"] = {k: t0[k] for k in ("ok", "problems", "artifacts", "rows")}
    ver["problems"].extend(f"tick0: {x}" for x in t0["problems"])
    ver["ok"] = not ver["problems"]
    mm.write_json(mm.state_dir() / "verify_eval" / f"{spec.name}__{plan['label']}.json", ver)
    state["evaluations"][key].update(verification=ver["problems"][:20], ok=ver["ok"], tick0_ok=t0["ok"],
                                     checkpoint=ec.repo_relative(ckpt), num_timesteps=int(plan["num_timesteps"]))
    save_state(state)
    return {"key": key, "checkpoint": ec.repo_relative(ckpt), "provenance_problems": [], "ran": True, "verification": ver}


def post_training_gate() -> Optional[Dict[str, Any]]:
    manifest = load_manifest(freeze=False)
    drift = mm.manifest_drift(manifest)
    if drift:
        for p in drift:
            log(f"BLOCKED {p}")
        return None
    return manifest


def cmd_evaluate(args: argparse.Namespace) -> int:  # noqa: ARG001
    from m7_runtime import install_kill_on_close_job

    state = load_state()
    manifest = post_training_gate()
    if manifest is None:
        return EXIT_FAILED
    install_kill_on_close_job()
    reruns = int(mn.rule_document()["parameters"]["evaluation_reruns_max"])
    for spec in mm.matrix():
        if run_status(spec, state) != "verified":
            log(f"{spec.name}: training not verified; evaluation stops")
            return EXIT_FAILED
        exp = mm.load_run(spec)
        for plan in mm.evaluation_plan(spec, exp):
            key = f"{spec.name}:{plan['label']}"
            while True:
                b = (state.get("evaluations") or {}).get(key) or {}
                if b.get("ok") and b.get("tick0_ok"):
                    break
                if int(b.get("attempts") or 0) > reruns:
                    log(f"{key}: not verified after {b.get('attempts')} attempts; stopping")
                    return EXIT_FAILED
                r = evaluate_label(state, spec, exp, plan, manifest)
                if r["provenance_problems"]:
                    event(state, "provenance_refused", key=key, problems=r["provenance_problems"][:5])
                    log(f"{key}: provenance REFUSED {r['provenance_problems'][:3]}")
                    return EXIT_FAILED
                v = r["verification"]
                log(f"{key}: {'verified' if v['ok'] else 'PROBLEMS ' + str(v['problems'][:3])}")
                if not v["ok"]:
                    out = spec.eval_dir / plan["label"]
                    aside = out.with_name(out.name + "__failed_" + stamp())
                    out.rename(aside)
                    event(state, "failed_evaluation_moved_aside", key=key, to=ec.repo_relative(aside),
                          problems=v["problems"][:5])
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
    for spec in mm.matrix():
        exp = mm.load_run(spec)
        for plan in mm.evaluation_plan(spec, exp):
            key = f"{spec.name}:{plan['label']}"
            if key in (state.get("clears") or {}):
                continue
            doc = kr.verify_clears_in(spec.eval_dir / plan["label"], spec.clears_dir / plan["label"],
                                      executable=exp.executable, extra_env=dict(exp.extra_env))
            state.setdefault("clears", {})[key] = {"candidates": doc["candidates"], "verified": doc["verified"]}
            save_state(state)
            if doc["candidates"]:
                log(f"{key}: {doc['verified']}/{doc['candidates']} clears verified")
                ok &= doc["verified"] == doc["candidates"]
        key = f"{spec.name}:training"
        if key in (state.get("clears") or {}):
            continue
        rows, _ = dr.jsonl_rows(spec.run_dir / "metrics" / "episodes.jsonl")
        tc = [r for r in rows if r.get("cleared")]
        recs = []
        for k, r in enumerate(tc):
            rec = {"episode_id": r["episode_id"], "artifact_dir": r.get("artifact_dir"), "verified": None,
                   "start_kind": (r.get("m7m") or {}).get("kind")}
            if r.get("artifact_dir"):
                art = Path(r["artifact_dir"])
                art = art if art.is_absolute() else REPO_ROOT / art
                rr = dr.replay_one(art, spec.clears_dir / "training" / f"replay_{k:03d}", executable=exp.executable,
                                   extra_env=dict(exp.extra_env), index=9600 + k)
                rec["verified"] = bool(rr.get("ok") and (rr.get("checks") or {}).get("completion_clocks")
                                       and (rr.get("checks") or {}).get("native_clear"))
                rec["checks"] = rr.get("checks")
            recs.append(rec)
        state.setdefault("clears", {})[key] = {"candidates": len(tc), "records": recs}
        save_state(state)
        if tc:
            log(f"{spec.name}: {len(tc)} native clears in training; replay results {[r['verified'] for r in recs]}")
    return EXIT_OK if ok else EXIT_FAILED


def census() -> Dict[str, Any]:
    rows, missing, executed = [], [], 0
    for spec in mm.matrix():
        exp = mm.load_run(spec)
        for p in mm.evaluation_plan(spec, exp):
            s = spec.eval_dir / p["label"] / "evaluation_summary.json"
            got = {"deterministic": 0, "stochastic": 0}
            if s.is_file():
                doc = mm.read_json(s)
                got = {m: len(((doc.get("modes") or {}).get(m) or {}).get("episodes") or []) for m in got}
            complete = got == {"deterministic": int(p["deterministic_episodes"]), "stochastic": int(p["stochastic_episodes"])}
            executed += sum(got.values())
            rows.append({"run": spec.name, "label": p["label"], "executed": got, "complete": complete})
            if not complete:
                missing.append(f"{spec.name}:{p['label']} executed {got}")
    return {"plan": mm.census_plan(), "rows": rows, "executed_episodes": executed, "missing": missing,
            "complete": not missing}


def cmd_census(args: argparse.Namespace) -> int:  # noqa: ARG001
    c = census()
    log(f"planned {c['plan']['episodes']} ({c['plan']['arithmetic']}); executed {c['executed_episodes']}; missing "
        f"{len(c['missing'])}")
    return EXIT_OK if c["complete"] else EXIT_FAILED


# -- analysis ---------------------------------------------------------------------------------------------------------


def label_curve(eval_dir: Path, labels: Sequence[str], P: Mapping[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for lab in labels:
        rows = la.read_label(eval_dir / lab)
        if not rows["stochastic"]:
            continue
        f = [la.episode_facts(e, P)[0] for e in rows["stochastic"]]
        n = len(f)
        out.append({"label": lab, "stochastic": n, "R": sum(x["R"] for x in f), "L": sum(x["L"] for x in f),
                    "seven_right": sum(x["seven_right"] for x in f), "t2": sum(x["t2"] for x in f),
                    "static_mean": round(sum(x["static_all"] for x in f) / n, 4),
                    "targets_mean": round(sum(x["targets"] for x in f) / n, 4), "falls": sum(x["fall"] for x in f),
                    "left_entries": sum(x["left_entry"] for x in f),
                    "deterministic_R": sum(la.episode_facts(e, P)[0]["R"] for e in rows["deterministic"])})
    return out


def training_facts(spec: mm.RunSpec) -> Dict[str, Any]:
    """Training-time facts; anchored successes are kept apart from normal tick-0 starts (never an input of R)."""
    rows, _ = dr.jsonl_rows(spec.run_dir / "metrics" / "episodes.jsonl")
    fin = mm.read_json(spec.run_dir / "final" / "anchor_schedule.json")
    summ = mm.read_json(spec.run_dir / "training_summary.json")
    sel = read_jsonl(spec.run_dir / "curriculum" / "selection.jsonl")
    tick0 = [r for r in rows if (r.get("m7m") or {}).get("kind") != ma.START_ANCHOR]
    anch = [r for r in rows if (r.get("m7m") or {}).get("kind") == ma.START_ANCHOR]

    def agg(rs: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        o = [r["m7m"] for r in rs]
        return {"episodes": len(rs), "success_by_2699": sum(1 for x in o if x["success"]),
                "seven_right_any_tick": sum(1 for x in o if x["seven_right"]),
                "t2_by_policy": sum(1 for x in o if x["t2_policy"]), "falls": sum(1 for x in o if x["fall"]),
                "left_target_episodes": sum(1 for x in o if x["left_ids"]),
                "clears": sum(1 for r in rs if r.get("cleared")), "policy_steps": sum(int(r["steps"]) for r in rs)}

    by_window: Dict[str, Any] = {}
    for r in anch:
        k = str(r["m7m"]["window_index"])
        w = by_window.setdefault(k, {"window": list(ma.WINDOWS[int(k)][1:]), "episodes": 0, "successes": 0})
        w["episodes"] += 1
        w["successes"] += int(r["m7m"]["success"])
    moves = [{"vec_step": e["vec_step"], "transitions_after_warm_start": e["vec_step"] * 5,
              "block": e["schedule"]["block"]} for e in sel
             if e.get("event") == "outcome" and (e.get("schedule") or {}).get("block")]
    st = fin.get("schedule") or {}
    stats = fin.get("stats") or {}
    return {"episodes": len(rows), "tick0_starts": agg(tick0), "anchored_starts": agg(anch),
            "anchored_by_window": dict(sorted(by_window.items(), key=lambda kv: int(kv[0]))),
            "schedule": {"final_window_index": st.get("k"), "final_pointer": st.get("pointer"),
                         "complete": st.get("complete"), "blocks": len(st.get("blocks") or []),
                         "blocks_passed": sum(1 for b in st.get("blocks") or [] if b["passed"]),
                         "counts": st.get("counts"), "block_events": moves,
                         "min_pointer_reached": ma.min_pointer_reached(st) if st else None},
            "prefix_costs": {"prefix_ticks": stats.get("prefix_ticks"), "dispatches": stats.get("prefix_dispatches"),
                             "dispatch_wall_s": stats.get("dispatch_wall_s"),
                             "max_dispatch_wall_s": stats.get("max_dispatch_wall_s"),
                             "never_counted_as_transitions": True},
            "starts": stats.get("starts"), "notable_kept": stats.get("notable_kept"),
            "throughput": summ.get("throughput"), "wall": summ.get("wall"), "cleanup": summ.get("cleanup")}


def build_report(state: Mapping[str, Any], manifest: Mapping[str, Any]) -> Dict[str, Any]:
    rule = mn.load_rule()
    P = mn.params(rule)
    pending: List[str] = []
    integrity: List[str] = []
    for spec in mm.matrix():
        st = run_status(spec, state)
        if st in ("verification_failed", "stopped", "failed", "gate_refused", "partial"):
            integrity.append(f"{spec.name}: training {st}")
        elif st != "verified":
            pending.append(f"{spec.name}: training not finished ({st})")
    c = census()
    if not c["complete"]:
        pending.append(f"census incomplete: {c['missing'][:2]}")
    for spec in mm.matrix():
        for plan in mm.evaluation_plan(spec, mm.load_run(spec)):
            key = f"{spec.name}:{plan['label']}"
            ev = (state.get("evaluations") or {}).get(key) or {}
            if "tick0_ok" not in ev:
                pending.append(f"{key}: evaluation not verified")
            elif not ev["tick0_ok"] or not ev.get("ok"):
                integrity.append(f"{key}: evaluation verification failed")
            cl = (state.get("clears") or {}).get(key)
            if cl is None:
                pending.append(f"{key}: clear verification not run")
            elif cl["verified"] != cl["candidates"]:
                integrity.append(f"{key}: {cl['verified']}/{cl['candidates']} native clears verified")
        tcl = (state.get("clears") or {}).get(f"{spec.name}:training")
        if tcl is None:
            pending.append(f"{spec.name}: training clear verification not run")
        elif any(r.get("verified") is False for r in tcl.get("records") or []):
            integrity.append(f"{spec.name}: a training clear failed its native replay")
    inputs: Dict[str, Any] = {"E": {}, "K": {}, "schedule": {}, "integrity": integrity}
    per_seed: Dict[str, Any] = {}
    labels = [p["label"] for p in mm.evaluation_plan(mm.matrix()[0], mm.load_run(mm.matrix()[0]))]
    for j in mm.SEEDS:
        entry: Dict[str, Any] = {}
        ref = mm.HISTORICAL / "_eval" / f"m7g_s{j}_v1" / "final"
        if (ref / "stochastic" / "evaluation.json").is_file():
            a0, _p0 = la.label_inputs(ref, None, P)
            entry["warm_start_reference"] = {"label": ec.repo_relative(ref), "final_stochastic": a0.to_json(),
                                             "final_deterministic": la.deterministic_facts(ref, P)}
        for arm in mm.ARMS:
            spec = mm.RunSpec(j, arm)
            label_dir = spec.eval_dir / "final"
            if not (label_dir / "stochastic" / "evaluation.json").is_file():
                continue
            cd = spec.clears_dir / "final" / "clear_verification.json"
            a, probs = la.label_inputs(label_dir, mm.read_json(cd) if cd.is_file() else None, P)
            inputs[arm][j] = a
            integrity.extend(f"{arm} s{j}: {x}" for x in probs)
            e = {"final_stochastic": a.to_json(), "t2_timing": la.t2_timing(a.t2_ticks),
                 "final_deterministic": la.deterministic_facts(label_dir, P),
                 "curve": label_curve(spec.eval_dir, labels, P)}
            if spec.run_dir.is_dir() and (spec.run_dir / "final" / "anchor_schedule.json").is_file():
                e["training"] = training_facts(spec)
                if arm == "E":
                    s = e["training"]["schedule"]
                    inputs["schedule"][j] = {"window_index": s["final_window_index"], "complete": s["complete"]}
            e["training_attempts"] = ((state.get("runs") or {}).get(spec.name) or {}).get("attempts")
            entry[arm] = e
        per_seed[str(j)] = entry
    m7l = {k: (mm.sha256_file(REPO_ROOT / k) == v if (REPO_ROOT / k).is_file() else False)
           for k, v in ((manifest.get("evidence") or {}).get("m7l_preserved") or {}).items()}
    evals = {k: {x: v.get(x) for x in ("wall_s", "leak_free", "attempts", "max_battleship_processes")}
             for k, v in (state.get("evaluations") or {}).items()}
    return {"inputs": inputs, "per_seed": per_seed, "census": {k: c[k] for k in ("plan", "executed_episodes", "missing",
                                                                                "complete")},
            "clears": state.get("clears"), "evaluations": evals, "m7l_evidence_unchanged": m7l,
            "pilot": state.get("pilot"), "integrity": integrity, "pending": pending}


def cmd_analyze(args: argparse.Namespace) -> int:
    state = load_state()
    manifest = post_training_gate()
    if manifest is None:
        return EXIT_FAILED
    rule = mn.load_rule()
    if rule["_sha256"] != (manifest.get("decision_rule") or {}).get("sha256"):
        log("BLOCKED the decision rule differs from the registered one in the manifest")
        return EXIT_FAILED
    if "n3" in (state.get("decisions") or {}) and not args.dry_run:
        log(f"the decision is already recorded ({state['decisions']['n3']['outcome']}); never re-decided")
        return EXIT_USAGE
    rep = build_report(state, manifest)
    if rep["pending"]:
        log(f"not ready to decide (nothing recorded): {len(rep['pending'])} pending, first {rep['pending'][:3]}")
        if args.dry_run:
            print(json.dumps({"pending": rep["pending"], "integrity": rep["integrity"]}, indent=1, default=str))
            return EXIT_OK
        return EXIT_FAILED
    d = mn.decide(rep["inputs"], rule)
    doc = {"decision": d, "per_seed": rep["per_seed"], "census": rep["census"], "clears": rep["clears"],
           "evaluations": rep["evaluations"], "m7l_evidence_unchanged": rep["m7l_evidence_unchanged"],
           "pilot": rep["pilot"], "manifest_sha256": mm.sha256_file(frozen_manifest_path()),
           "rule_sha256": rule["_sha256"], "utc": utc_now()}
    if args.dry_run:
        print(json.dumps(d, indent=1, default=str))
        return EXIT_OK
    out = mm.state_dir() / "analysis_n3.json"
    mm.write_json(out, doc)
    state.setdefault("decisions", {})["n3"] = {"outcome": d["outcome"], "gate": d["gate"], "gates": d.get("gates"),
                                               "response": d["response"], "utc": utc_now(),
                                               "report": ec.repo_relative(out)}
    save_state(state)
    log(f"decision at n = 3: {d['outcome']} (gate {d['gate']}): {d['response']}")
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:  # noqa: ARG001
    state = load_state()
    log(f"pilot: {(state.get('pilot') or {}).get('status')}")
    for spec in mm.matrix():
        log(f"{spec.order_index} {spec.name}: {run_status(spec, state)}")
    log(f"evaluations verified: {sum(1 for v in (state.get('evaluations') or {}).values() if v.get('ok'))}; "
        f"decisions: {state.get('decisions')}")
    return EXIT_OK


def cmd_all(args: argparse.Namespace) -> int:  # noqa: ARG001
    for name, fn, ns in (("pilot", cmd_pilot, argparse.Namespace()),
                         ("train", cmd_train, argparse.Namespace(dry_run=False)),
                         ("evaluate", cmd_evaluate, argparse.Namespace()),
                         ("verify-clears", cmd_verify_clears, argparse.Namespace()),
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
    sub.add_parser("pilot")
    for name in ("train", "preflight"):
        t = sub.add_parser(name)
        t.add_argument("--dry-run", action="store_true")
    sub.add_parser("evaluate")
    sub.add_parser("verify-clears")
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
    fn = {"manifest": cmd_manifest, "pilot": cmd_pilot, "train": cmd_train, "preflight": cmd_train,
          "evaluate": cmd_evaluate, "verify-clears": cmd_verify_clears, "census": cmd_census, "analyze": cmd_analyze,
          "status": cmd_status, "all": cmd_all}[args.command]
    try:
        return fn(args)
    except mm.MatrixError as exc:
        log(f"ERROR {exc}")
        return EXIT_FAILED
    except KeyboardInterrupt:
        log("interrupted")
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
