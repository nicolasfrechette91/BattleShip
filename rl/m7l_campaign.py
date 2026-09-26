"""M7l campaign driver: the controlled three-seed target-2 reward experiment. Arm T = btt_reward_v3_t2 (fresh models),
arm C = the historical Phase K v1 control (btt_reward_v2).

Proposal: docs/rl_target2_m7k.md section 10. Registered settings and rule: docs/rl_target2_m7l_manifest.json and
docs/rl_target2_m7l_decision_rule.json. Everything is written below runs/m7l/campaign; the historical control
(runs/m7g_k) and every other run tree are read only.

    python rl/m7l_campaign.py manifest                  # build the manifest (docs/); refused once the campaign froze it
    python rl/m7l_campaign.py control-check             # R1 (3 x 102,400, reward v2), R2 (600 episodes), R3 (inputs)
    python rl/m7l_campaign.py train --dry-run           # = preflight: plan, drift, control check, profiles, gate
    python rl/m7l_campaign.py train                     # T s0, s1, s2 in order, each behind the launch gate
    python rl/m7l_campaign.py evaluate [--dry-run]      # tick-0 post-hoc Phase K protocol, 985 episodes per run
    python rl/m7l_campaign.py verify-clears | replay | census | status
    python rl/m7l_campaign.py analyze [--dry-run]       # the registered rule, recorded once (never re-decided)
    python rl/m7l_campaign.py all                       # train -> evaluate -> verify-clears -> replay -> analyze

Stop policy (registered): a failed launch gate (after its registered re-readings), a monitor hard alert, the in-run
memory policy, a provenance mismatch, a process leak, a failed verification or a manifest drift stops the campaign.
A stopped run directory is moved to _partial by the guard and kept; nothing is resumed or relaunched here.
Native RNG state is never inspected, logged, validated, controlled, compared or hashed.
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
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import experiment_config as ec  # noqa: E402
import m7d_run as dr  # noqa: E402
import m7h_guard as g  # noqa: E402
import m7l_analysis as la  # noqa: E402
import m7l_matrix as lm  # noqa: E402

REPO_ROOT = RL_DIR.parent
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_INTERRUPTED = 0, 1, 2, 130
CONTROL_RECORD = "control_check.json"
REPLAY_WORKERS = 4

# Stand-ins for tests (never set in a real invocation).
GATE_FN: Optional[Callable[[], Dict[str, Any]]] = None
LAUNCHER: Optional[Callable[..., Dict[str, Any]]] = None
SLEEP: Callable[[float], None] = time.sleep


def log(message: str) -> None:
    print(f"[m7l-campaign {time.strftime('%H:%M:%S')}] {message}", flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# -- state ------------------------------------------------------------------------------------------------------------


def state_file() -> Path:
    return lm.state_dir() / "state.json"


def load_state() -> Dict[str, Any]:
    if state_file().is_file():
        return lm.read_json(state_file())
    return {"schema": "battleship_m7l_campaign_state_v1", "milestone": lm.MILESTONE, "created_utc": utc_now(),
            "control": {"mode": "historical"}, "runs": {}, "evaluations": {}, "clears": {}, "replays": {},
            "decisions": {}, "events": []}


def save_state(state: Dict[str, Any]) -> None:
    state["updated_utc"] = utc_now()
    lm.write_json(state_file(), state)


def event(state: Dict[str, Any], kind: str, **data: Any) -> None:
    state.setdefault("events", []).append(dict(kind=kind, utc=utc_now(), **data))
    save_state(state)


# -- the manifest ----------------------------------------------------------------------------------------------------


def frozen_manifest_path() -> Path:
    return lm.state_dir() / "manifest.json"


def load_manifest(*, freeze: bool) -> Dict[str, Any]:
    fp = frozen_manifest_path()
    if fp.is_file():
        man = lm.read_json(fp)
        if lm.MANIFEST_DOC.is_file() and lm.read_json(lm.MANIFEST_DOC) != man:
            raise lm.MatrixError(f"{ec.repo_relative(lm.MANIFEST_DOC)} differs from the frozen copy")
        return man
    if not lm.MANIFEST_DOC.is_file():
        raise lm.MatrixError(f"{ec.repo_relative(lm.MANIFEST_DOC)} missing: run 'python rl/m7l_campaign.py manifest'")
    man = lm.read_json(lm.MANIFEST_DOC)
    if freeze:
        lm.write_json(fp, man)
    return man


def cmd_manifest(args: argparse.Namespace) -> int:
    if frozen_manifest_path().is_file() and not args.out:
        log(f"refused: the campaign froze its manifest at {ec.repo_relative(frozen_manifest_path())}; never rebuilt")
        return EXIT_USAGE
    man = lm.build_manifest()
    out = Path(args.out) if args.out else lm.MANIFEST_DOC
    lm.write_json(out, man)
    log(f"manifest -> {ec.repo_relative(out)} ok={man['ok']} code {man['code']['sha256'][:12]} ({man['code']['files']} "
        f"files) rule {man['decision_rule']['sha256'][:12]}")
    for p in man["problems"]:
        log(f"  PROBLEM {p}")
    return EXIT_OK if man["ok"] else EXIT_FAILED


# -- resources --------------------------------------------------------------------------------------------------------


def wait_for_launch_gate(tag: str) -> Dict[str, Any]:
    """The registered launch gate: a failed reading is re-measured after LAUNCH_GATE_RETRY_S, at most
    LAUNCH_GATE_READINGS readings; ok only on a passing reading."""
    readings: List[Dict[str, Any]] = []
    last: Dict[str, Any] = {}
    for i in range(lm.LAUNCH_GATE_READINGS):
        last = (GATE_FN or g.launch_gate)()
        readings.append({"utc": utc_now(), "ok": last["ok"], "problems": last["problems"],
                         "measurement": {k: (last.get("measurement") or {}).get(k) for k in (
                             "avail_commit_gib", "avail_phys_gib", "disk_free_gib", "cpu_mean_pct", "battleship_pids",
                             "listeners", "ssb64_environment_variables")}})
        if last["ok"]:
            return {"ok": True, "tag": tag, "readings": readings, "problems": []}
        if i < lm.LAUNCH_GATE_READINGS - 1:
            log(f"{tag}: launch gate reading {i + 1} failed {last['problems']}; re-measuring in "
                f"{lm.LAUNCH_GATE_RETRY_S:.0f} s")
            SLEEP(lm.LAUNCH_GATE_RETRY_S)
    return {"ok": False, "tag": tag, "readings": readings, "problems": last.get("problems")}


# -- the control check -----------------------------------------------------------------------------------------------


def control_record_path() -> Path:
    return lm.control_root() / CONTROL_RECORD


def r3_inputs(out: Path, seeds: Sequence[int]) -> Dict[str, Any]:
    """R3: the M7l decision inputs recomputed from the R2 re-evaluation and from the historical records; they must equal
    each other and the rule's registered control values (deterministic facts included)."""
    rule = la.load_rule()
    P = la.params(rule)
    known = rule["known_control_values"]
    p: List[str] = []
    per: Dict[str, Any] = {}
    for s in seeds:
        h = lm.HistoricalControl(s)
        cd = h.clears_dir / "final" / "clear_verification.json"
        hist, hp = la.label_inputs(h.eval_dir / "final", lm.read_json(cd) if cd.is_file() else None, P)
        r2, rp = la.label_inputs(out / "r2" / f"{h.name}_final", None, P)
        want = {k: (known.get(k) or {}).get(str(s)) for k in ("t2", "t2_ticks", "S", "S_right", "L", "R", "falls",
                                                                "native_clears", "left_entries", "left_target_episodes")}
        want["T"] = known["T_incomplete"][str(s)]
        got_r2 = {k: getattr(r2, k) for k in want if k != "T"} | {"T": str(r2.T)}
        got_h = {k: getattr(hist, k) for k in want if k != "T"} | {"T": str(hist.T)}
        det_h = la.deterministic_facts(h.eval_dir / "final", P)
        det_r2 = la.deterministic_facts(out / "r2" / f"{h.name}_final", P)
        if hp or rp:
            p.append(f"seed {s}: problems computing inputs: historical {hp[:2]} R2 {rp[:2]}")
        if got_r2 != want or got_h != want or r2.to_json() != hist.to_json():
            p.append(f"seed {s}: R2 {got_r2} / historical {got_h} / registered {want}")
        if det_h != det_r2:
            p.append(f"seed {s}: deterministic facts differ: {det_h} vs {det_r2}")
        per[str(s)] = {"r2": r2.to_json(), "historical": hist.to_json(), "registered": want,
                       "deterministic": det_r2}
    return {"check": "R3", "ok": not p, "problems": p, "per_seed": per}


def r1_phase_k(out: Path, seeds: Sequence[int], manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """R1 (M7l addition): the R1 finals against the manifest's pinned Phase K ckpt_000102400 digests and rows."""
    p: List[str] = []
    per: Dict[str, Any] = {}
    for s in seeds:
        rd = out / "r1" / f"m7h_r1_s{s}"
        pin = ((manifest.get("historical_control") or {}).get("seeds") or {}).get(str(s)) or {}
        if not (rd / "final" / "checkpoint.json").is_file():
            p.append(f"seed {s}: no R1 final set")
            continue
        got = list(dr.checkpoint_digests(rd / "final"))
        rows, _ = dr.jsonl_rows(rd / "metrics" / "episodes.jsonl")
        keys = lm.hm.R_CONDITIONS["R1"]["row_keys"]
        rsha = lm.canonical_sha256([[r.get(k) for k in keys] for r in rows])
        ok = got == pin.get("ckpt_000102400_digests") and len(rows) == pin.get("rows_at_102400") and \
            rsha == pin.get("rows_at_102400_sha256")
        if not ok:
            p.append(f"seed {s}: digests {got} vs {pin.get('ckpt_000102400_digests')}, rows {len(rows)} vs "
                     f"{pin.get('rows_at_102400')}, row sha equal {rsha == pin.get('rows_at_102400_sha256')}")
        per[str(s)] = {"final_digests": got, "pinned": pin.get("ckpt_000102400_digests"), "rows": len(rows),
                       "rows_sha256_equal": rsha == pin.get("rows_at_102400_sha256")}
    return {"check": "R1_phase_k", "ok": not p, "problems": p, "per_seed": per}


def cmd_control_check(args: argparse.Namespace) -> int:
    import m7h_run as hr

    state = load_state()
    manifest = load_manifest(freeze=False)
    drift = lm.manifest_drift(manifest)
    if drift:
        for p in drift:
            log(f"BLOCKED {p}")
        return EXIT_FAILED
    seeds = [int(s) for s in args.seeds.split(",")]
    code = manifest["code"]["sha256"]
    out = lm.control_root() / f"code_{code[:12]}__{stamp()}"
    if args.dry_run:
        log(f"dry run: R1 (3 x 102,400, reward v2) -> R2 (600 episodes) -> R3 into {ec.repo_relative(out)}")
        return EXIT_OK
    t0 = time.perf_counter()
    rc: Dict[str, int] = {}
    gates: List[Dict[str, Any]] = []
    try:
        for s in seeds:
            gate = wait_for_launch_gate(f"control R1 s{s}")
            gates.append(gate)
            if not gate["ok"]:
                raise RuntimeError(f"launch gate refused before R1 s{s}: {gate['problems']}")
            rc[f"r1_s{s}"] = hr.cmd_r1(argparse.Namespace(seeds=str(s), base=out))
        for s in seeds:
            rc[f"r2_s{s}"] = hr.cmd_r2(argparse.Namespace(seeds=str(s), base=out))
    except RuntimeError as exc:
        log(f"control check NOT completed (nothing recorded; not a failed reproduction): {exc}")
        return EXIT_FAILED
    results = {}
    for f in sorted((out / "results").glob("r*.json")):
        results[f.stem] = {k: v for k, v in lm.read_json(f).items() if k in (
            "check", "seed", "ok", "problems", "final_digests", "m7e_digests", "rows_compared", "rows_registered",
            "compared", "wall_s", "learn_s", "throughput")}
    r1pk = r1_phase_k(out, seeds, manifest)
    r3 = r3_inputs(out, seeds)
    lm.write_json(out / "results" / "r1_phase_k.json", r1pk)
    lm.write_json(out / "results" / "r3_m7l.json", r3)
    problems = [f"{k}: exit {v}" for k, v in rc.items() if v != 0] + \
        [f"{k}: {r['problems'][:2]}" for k, r in results.items() if not r.get("ok")] + \
        [f"R1 vs Phase K: {x}" for x in r1pk["problems"]] + [f"R3: {x}" for x in r3["problems"]]
    want = {f"r1_s{s}" for s in seeds} | {f"r2_s{s}" for s in seeds}
    if not want <= set(results):
        problems.append(f"missing results {sorted(want - set(results))}")
    rec = {"schema": "m7l_control_check_v1", "utc": utc_now(), "code_sha256": code,
           "executable_sha256": manifest["executable"]["sha256"], "revisions": manifest["revisions"],
           "manifest_sha256": lm.sha256_file(lm.MANIFEST_DOC), "rule_sha256": manifest["decision_rule"]["sha256"],
           "out": ec.repo_relative(out), "seeds": seeds, "exit_codes": rc, "results": results, "r1_phase_k": r1pk,
           "r3": {k: r3[k] for k in ("ok", "problems", "per_seed")}, "launch_gates": gates,
           "wall_s": round(time.perf_counter() - t0, 1), "problems": problems, "ok": not problems}
    lm.write_json(out / CONTROL_RECORD, rec)
    lm.write_json(control_record_path(), rec)
    state.setdefault("control", {})["check"] = {k: rec[k] for k in ("utc", "code_sha256", "ok", "out")}
    event(state, "control_check", ok=rec["ok"], code_sha256=code, out=rec["out"], problems=problems[:5])
    log(f"control check {'PASS' if rec['ok'] else 'FAIL'} in {rec['wall_s'] / 60:.1f} min {problems[:3]}")
    return EXIT_OK if rec["ok"] else EXIT_FAILED


def control_check_problems(manifest: Mapping[str, Any]) -> List[str]:
    """Why the historical control may not be reused now (empty = it may): a passed record for exactly the manifest's
    code, executable, submodules and rule, and the historical control files unchanged since the manifest."""
    p: List[str] = []
    rec = lm.read_json(control_record_path()) if control_record_path().is_file() else None
    code = (manifest.get("code") or {}).get("sha256")
    if rec is None:
        p.append("the control check has not run on this code: python rl/m7l_campaign.py control-check")
    else:
        if not rec.get("ok"):
            p.append(f"the control check FAILED ({rec.get('problems')[:3]}); the control is not reused and no T run starts")
        if rec.get("code_sha256") != code:
            p.append(f"the control check ran on code {str(rec.get('code_sha256'))[:12]}, the manifest is {str(code)[:12]}")
        if rec.get("executable_sha256") != (manifest.get("executable") or {}).get("sha256"):
            p.append("the control check ran on another executable")
        if (rec.get("revisions") or {}).get("submodules") != (manifest.get("revisions") or {}).get("submodules"):
            p.append("the control check ran on other submodule revisions")
        if rec.get("rule_sha256") != (manifest.get("decision_rule") or {}).get("sha256"):
            p.append("the control check ran under another decision rule")
    for s, want in ((manifest.get("historical_control") or {}).get("seeds") or {}).items():
        now = lm.historical_identity(int(s))
        keys = ("final_checkpoint_json_sha256", "final_digests", "initial_digests", "ckpt_000102400_digests",
                "rows_at_102400_sha256", "final_evaluation_sha256", "decision_inputs")
        if not now["ok"] or any(now.get(k) != want.get(k) for k in keys):
            p.append(f"historical control seed {s} changed since the manifest or no longer verifies: {now['problems'][:2]}")
    return p


# -- training ---------------------------------------------------------------------------------------------------------


def run_status(spec: lm.RunSpec, state: Mapping[str, Any]) -> str:
    """verified | completed_unverified | partial | absent."""
    if (((state.get("runs") or {}).get(spec.name) or {}).get("status")) == "verified":
        return "verified"
    if not spec.run_dir.exists():
        return "absent"
    summ = spec.run_dir / "training_summary.json"
    if summ.is_file() and lm.read_json(summ).get("status") == "completed":
        return "completed_unverified"
    return "partial"


def train_plan(specs: Sequence[lm.RunSpec], state: Mapping[str, Any]) -> List[Dict[str, Any]]:
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
            action = "STOP: a partial run directory exists (preserved; this milestone never resumes or relaunches)"
        else:
            action = "train from scratch"
        if (((state.get("runs") or {}).get(spec.name) or {}).get("status")) in ("stopped", "failed",
                                                                               "verification_failed"):
            action = f"STOP: {spec.name} was {state['runs'][spec.name]['status']} (preserved; not relaunched)"
        plan.append({"run": spec.name, "status": st, "action": action})
        blocked = True
    return plan


def preflight_run(spec: lm.RunSpec, exp: ec.Experiment, manifest: Mapping[str, Any]) -> Dict[str, Any]:
    checks = lm.arm_checks(spec, exp)
    p = [f"{spec.name}: {k}" for k, ok in checks.items() if not ok]
    r = (manifest.get("runs") or {}).get(spec.name)
    if r is None:
        p.append(f"{spec.name}: not in the manifest")
    else:
        if (r["source_sha256"], r["semantic_fingerprint"], r["compatibility_fingerprint"]) != \
                (exp.source.sha256, exp.semantic_fingerprint, exp.compatibility_fingerprint):
            p.append(f"{spec.name}: profile differs from the manifest")
        if not r.get("expected_initial_policy_digest") or not r.get("initial_model_equals_control_untrained_model"):
            p.append(f"{spec.name}: no expected untrained-model digest equal to the control's in the manifest")
        if not (r.get("phase_k_proof") or {}).get("ok"):
            p.append(f"{spec.name}: the Phase K comparison proof failed")
    return {"run": spec.name, "checks": checks, "problems": p, "ok": not p}


def run_identity(run_dir: Path, spec: lm.RunSpec, manifest: Mapping[str, Any]) -> List[str]:
    from btt_rewards import REWARD_V3_T2

    rj = lm.read_json(run_dir / "run.json")
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
    if rj.get("reward_contract") != REWARD_V3_T2.to_json():
        p.append("run.json reward contract is not the registered btt_reward_v3_t2")
    if dict(rj.get("m6_flags") or {}) != dict(lm.M6_FLAGS, **lm.DIAG_FLAG):
        p.append(f"run.json native flags {rj.get('m6_flags')}")
    if rj.get("lineage"):
        p.append(f"not a fresh model: lineage {rj.get('lineage')}")
    if (rj.get("config") or {}).get("curriculum") is not None or (run_dir / "curriculum").exists():
        p.append("a curriculum trace")
    return p


def control_equivalence(run_dir: Path, seed: int, total: int = lm.TOTAL_TRANSITIONS) -> Dict[str, Any]:
    """The M7k registered checks (rl/m7k_run.py V1-V5) over the full run against its historical control: every row
    equals its btt_reward_v3_t2 closed form; before the first rollout that contains a target-2 break the run IS the
    control (same rows, same returns); an action-identical row differs in return by exactly its credit; with no
    target-2 break at all the final set equals the control's final set; the compatibility views differ only in the
    reward and its flag."""
    import btt_reward_t2 as t2
    import m7k_run as kv

    h = lm.HistoricalControl(seed)
    p: List[str] = []
    diff = sorted(ec.compare_compatibility(ec.load_experiment(run_dir / "experiment.toml").compatibility_view(),
                                           ec.load_experiment(h.config_path).compatibility_view()))
    if diff != ["contracts.reward_resolved", "environment.extra_env"]:
        p.append(f"V5 compatibility view differs in {diff}")
    ours = sorted(kv.rows(run_dir), key=lambda r: (int(r["sb3_num_timesteps_seen"]), r["rank"]))
    ctl = sorted([r for r in kv.rows(h.run_dir) if int(r.get("sb3_num_timesteps_seen") or 0) <= total],
                 key=lambda r: (int(r["sb3_num_timesteps_seen"]), r["rank"]))
    v1_bad = []
    for r in ours:
        rv = r.get("reward_v3") or {}
        if not rv:
            v1_bad.append((r["episode_id"], "no record"))
            continue
        want = t2.expected_return_v3_t2(moving_target_consumed_tick=(rv.get("moving_target") or {}).get("consumed_tick"),
                                        targets_broken=r["targets_broken"], steps=r["steps"], cleared=r["cleared"],
                                        native_failure=r["end_reason"] == "fall",
                                        sweep_consumed_tick=(rv.get("right_sweep") or {}).get("consumed_tick"),
                                        qualified_landing=rv.get("qualified_landing") is not None)
        if abs(r["return"] - want) > 1e-9:
            v1_bad.append((r["episode_id"], r["return"], want))
    if v1_bad:
        p.append(f"V1 {len(v1_bad)} rows disagree with the closed form: {v1_bad[:3]}")
    t2_rows = [(kv.t2_step_global(r), r) for r in ours if kv.t2_step_global(r) is not None]
    first_t2 = min((x for x, _ in t2_rows), default=None)
    first_end = None if first_t2 is None else ((first_t2 - 1) // kv.ROLLOUT + 1) * kv.ROLLOUT
    tw = {(r["rank"], r["worker_episode"]): r for r in ctl}
    first_div = None
    identical = 0
    for r in ours:
        c = tw.get((r["rank"], r["worker_episode"]))
        if c is None or any(r.get(x) != c.get(x) for x in kv.ROW_KEYS):
            if first_div is None or int(r["sb3_num_timesteps_seen"]) < int(first_div["sb3_num_timesteps_seen"]):
                first_div = r
            continue
        identical += 1
        credit = ((r.get("reward_v3") or {}).get("moving_target") or {}).get("moving_target_term", 0.0)
        if abs((r["return"] - c["return"]) - credit) > 1e-9:
            p.append(f"V3 {r['episode_id']}: return {r['return']} vs control {c['return']} (credit {credit})")
    if first_div is not None and (first_end is None or int(first_div["sb3_num_timesteps_at_end"]) < first_end):
        p.append(f"V2 actions diverged at {first_div['episode_id']} (at_end {first_div['sb3_num_timesteps_at_end']}) "
                 f"before any target-2 rollout ({first_end})")
    if first_t2 is None and len(ours) != len(ctl):
        p.append(f"V2 no target-2 break but {len(ours)} rows vs control {len(ctl)}")
    fin = list(dr.checkpoint_digests(run_dir / "final"))
    ref = h.run_dir / "final" if total == lm.TOTAL_TRANSITIONS else h.run_dir / "checkpoints" / f"ckpt_{total:09d}"
    ctl_fin = list(dr.checkpoint_digests(ref))
    if first_t2 is None and fin != ctl_fin:
        p.append(f"V4 no target-2 break but final digests {fin} != control {ctl_fin}")
    return {"contract": "m7l_control_equivalence_v1", "control": h.name, "ok": not p, "problems": p[:20],
            "rows": len(ours), "control_rows": len(ctl), "rows_action_identical_to_control": identical,
            "target2_training_events": [{"episode_id": r["episode_id"], "consumed_tick":
                                         r["reward_v3"]["moving_target"]["consumed_tick"],
                                         "credit": r["reward_v3"]["moving_target"]["moving_target_term"],
                                         "global_transitions": x, "end_reason": r["end_reason"]}
                                        for x, r in sorted(t2_rows, key=lambda y: y[0])],
            "first_target2_rollout_end": first_end,
            "first_action_divergence": None if first_div is None else {
                "episode_id": first_div["episode_id"], "sb3_num_timesteps_at_end": first_div["sb3_num_timesteps_at_end"]},
            "final_digests": fin, "control_final_digests": ctl_fin, "final_equals_control": fin == ctl_fin}


def verify_run(spec: lm.RunSpec, exp: ec.Experiment, manifest: Mapping[str, Any]) -> Dict[str, Any]:
    r = (manifest.get("runs") or {}).get(spec.name) or {}
    expected = (r.get("expected_initial_policy_digest"), r.get("expected_initial_obs_rms_digest"))
    ver = dr.verify_training_run(spec.run_dir, exp, fresh=True, expected_initial=expected)
    ident = run_identity(spec.run_dir, spec, manifest)
    eq = control_equivalence(spec.run_dir, spec.seed)
    ver["m7l_identity"] = ident
    ver["control_equivalence"] = eq
    extra = ident + [f"control equivalence: {x}" for x in eq["problems"]]
    if extra:
        ver["problems"].extend(extra)
        ver["ok"] = False
    return ver


def _guarded_launch(*, spec: lm.RunSpec, exp: ec.Experiment, **_: Any) -> Dict[str, Any]:
    tag = f"{spec.name}__{stamp()}"
    return g.train_guarded(config=spec.config_path, run_dir=spec.run_dir, log_path=lm.guard_root() / "logs" / f"{tag}.log",
                           monitor_path=lm.guard_root() / "monitor" / f"{tag}.jsonl",
                           probe_path=lm.guard_root() / "probe" / f"{tag}.jsonl", contract=exp.reward,
                           horizon=int(exp.values["environment.horizon"]), partial_root=lm.partial_root(),
                           output_root=None if lm.root() == lm.DEFAULT_ROOT else spec.run_dir.parent)


def cmd_train(args: argparse.Namespace) -> int:
    state = load_state()
    specs = lm.matrix()
    manifest = load_manifest(freeze=not args.dry_run)
    drift = lm.manifest_drift(manifest)
    plan = train_plan(specs, state)
    report: Dict[str, Any] = {"dry_run": bool(args.dry_run), "plan": plan, "manifest_drift": drift,
                              "control_check": control_check_problems(manifest),
                              "preflight": {s.name: preflight_run(s, lm.load_run(s), manifest) for s in specs},
                              "directory_plan": lm.check_directory_plan()}
    first = next((s for s in plan if s["action"] != "skip"), None)
    need_gate = first is not None and first["action"].startswith("train")
    report["resources"] = wait_for_launch_gate("preflight") if need_gate and not args.skip_resource_gate else None
    blocking = drift + report["control_check"] + [p for pf in report["preflight"].values() for p in pf["problems"]] + \
        report["directory_plan"]["problems"] + ([] if report["resources"] is None else report["resources"]["problems"] or [])
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
        spec = lm.run_by_name(step["run"])
        action = step["action"]
        if action.startswith(("STOP", "wait")):
            log(f"{spec.name}: {action}")
            return EXIT_FAILED if action.startswith("STOP") else EXIT_OK
        if spec.name in handled:
            log(f"{spec.name}: not verified after this invocation's attempt; stopping")
            return EXIT_FAILED
        handled.add(spec.name)
        exp = lm.load_run(spec)
        rs = state["runs"].setdefault(spec.name, {"status": "pending", "attempts": []})
        if action.startswith("verify"):
            ver = verify_run(spec, exp, manifest)
            lm.write_json(lm.state_dir() / "verify" / f"{spec.name}.json", ver)
            rs.update(status="verified" if ver["ok"] else "verification_failed", verification=ver["problems"][:20])
            save_state(state)
            if not ver["ok"]:
                log(f"{spec.name}: verification FAILED {ver['problems'][:3]}")
                return EXIT_FAILED
            continue
        drift = lm.manifest_drift(manifest)
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
        log(f"{spec.name}: launching (seed {spec.seed}, {lm.TOTAL_TRANSITIONS:,} policy transitions, btt_reward_v3_t2)")
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
                       "episodes_seen", "episode_ends", "cold_fallbacks_after_first", "startup_failures",
                       "lifecycle_failures", "cpu_util", "avail_commit_gib", "avail_phys_gib")},
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
        lm.write_json(lm.state_dir() / "verify" / f"{spec.name}.json", ver)
        eq = ver.get("control_equivalence") or {}
        rs.update(status="verified" if ver["ok"] else "verification_failed", verification=ver["problems"][:20],
                  target2_training_events=len(eq.get("target2_training_events") or []),
                  first_action_divergence=eq.get("first_action_divergence"))
        save_state(state)
        if not ver["ok"]:
            log(f"{spec.name}: verification FAILED {ver['problems'][:3]}")
            return EXIT_FAILED
        log(f"{spec.name}: verified ({len(eq.get('target2_training_events') or [])} target-2 events in training)")


# -- evaluation (tick-0 only) ------------------------------------------------------------------------------------------


def checkpoint_for(spec: lm.RunSpec, label: str, t: int) -> Path:
    return spec.run_dir / "final" if label == "final" else spec.run_dir / "checkpoints" / f"ckpt_{t:09d}"


def checkpoint_provenance(ckpt: Path, spec: lm.RunSpec, exp: ec.Experiment, planned_t: int,
                          manifest: Mapping[str, Any]) -> List[str]:
    import m7h_campaign as hc   # the M7h check is pure (reads the set; spec duck-typed: name, seed, curriculum=False)

    p = hc.checkpoint_provenance(ckpt, spec, exp, planned_t, manifest)
    try:
        meta = lm.read_json(ckpt / "checkpoint.json")
        if (meta.get("contracts") or {}).get("reward_contract") != "btt_reward_v3_t2":
            p.append(f"reward contract {(meta.get('contracts') or {}).get('reward_contract')}")
    except (OSError, ValueError) as exc:
        p.append(f"{ckpt.name}: {exc}")
    return p


def run_eval_label(state: Dict[str, Any], key: str, out_dir: Path, fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    """One label under the monitor; atomic: a complete summary is reused, a partial directory is moved aside (kept)."""
    import m7g_k_run as kr   # measurement only (preconditions)
    from m7_runtime import BATTLESHIP_IMAGE, wait_until_no_process

    done = out_dir / "evaluation_summary.json"
    if done.is_file():
        return lm.read_json(done)
    if out_dir.exists():
        aside = out_dir.with_name(out_dir.name + "__incomplete_" + stamp())
        out_dir.rename(aside)
        event(state, "incomplete_evaluation_moved_aside", key=key, to=ec.repo_relative(aside))
    pre = kr.preconditions(f"before evaluation {key}")
    if pre["problems"]:
        raise lm.MatrixError(f"evaluation {key}: preconditions failed: {pre['problems']}")
    monitor = dr.Monitor(out=lm.state_dir() / "monitor" / "evaluation.jsonl", root_pid=os.getpid()).start()
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
        raise lm.MatrixError(f"evaluation {key}: monitor alerts {mon.get('hard_alerts')} / leaked {leftover}")
    return result


def route_metric_problems(res: Mapping[str, Any]) -> List[str]:
    """Every evaluation row carries its v3_t2 record, and its moving-target tick and broken IDs equal btt_eval_metrics_v1."""
    p: List[str] = []
    for mode, r in (res.get("modes") or {}).items():
        for e in r.get("episodes") or []:
            rv, em = e.get("reward_v3"), e.get("eval_metrics") or {}
            if not isinstance(rv, dict):
                p.append(f"{mode} {e.get('episode_id')}: no reward_v3 record")
                continue
            mt = (rv.get("moving_target") or {}).get("consumed_tick")
            if mt != em.get("moving_target_break_tick") or sorted(rv.get("broken_ids") or []) != \
                    sorted(em.get("broken_ids") or []):
                p.append(f"{mode} {e.get('episode_id')}: reward record ({mt}, {rv.get('broken_ids')}) != metrics "
                         f"({em.get('moving_target_break_tick')}, {em.get('broken_ids')})")
    return p[:20]


def evaluate_label(state: Dict[str, Any], spec: lm.RunSpec, exp: ec.Experiment, plan: Mapping[str, Any],
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
    for mode, r in (res.get("modes") or {}).items():
        if dict(r.get("extra_env") or {}) != dict(lm.M6_FLAGS, **lm.DIAG_FLAG):
            ver["problems"].append(f"{mode}: evaluation flags {r.get('extra_env')}")
    ver["problems"].extend(route_metric_problems(res))
    t0 = mv.verify_eval_tick0(out)
    ver["tick0"] = {k: t0[k] for k in ("ok", "problems", "artifacts", "rows")}
    ver["problems"].extend(f"tick0: {x}" for x in t0["problems"])
    ver["ok"] = not ver["problems"]
    lm.write_json(lm.state_dir() / "verify_eval" / f"{spec.name}__{plan['label']}.json", ver)
    state["evaluations"][key].update(verification=ver["problems"][:20], ok=ver["ok"], tick0_ok=t0["ok"],
                                     checkpoint=ec.repo_relative(ckpt), num_timesteps=int(plan["num_timesteps"]))
    save_state(state)
    return {"key": key, "checkpoint": ec.repo_relative(ckpt), "provenance_problems": [], "ran": True, "verification": ver}


def post_training_gate() -> Optional[Dict[str, Any]]:
    manifest = load_manifest(freeze=False)
    drift = lm.manifest_drift(manifest)
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
    for spec in lm.matrix():
        if ((state.get("runs") or {}).get(spec.name) or {}).get("status") != "verified":
            report.append({"run": spec.name, "skipped": "training not verified"})
            if not args.dry_run:
                log(f"{spec.name}: training not verified; evaluation stops")
                return EXIT_FAILED
            continue
        exp = lm.load_run(spec)
        for plan in lm.evaluation_plan(spec, exp):
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
    import m7g_k_run as kr   # verify_clears_in writes only into the given out_dir
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    state = load_state()
    if post_training_gate() is None:
        return EXIT_FAILED
    ok = True
    for spec in lm.matrix():
        if not spec.eval_dir.is_dir():
            continue
        exp = lm.load_run(spec)
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
        # training-time native clears (reported; replayed when an artifact was preserved)
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


# -- spatial replays (secondary, descriptive) ------------------------------------------------------------------------


def replay_items(label_dir: Path) -> List[Dict[str, Any]]:
    d = lm.read_json(label_dir / "stochastic" / "evaluation.json")
    items = []
    for e in sorted(d.get("episodes") or [], key=lambda x: x.get("order", 0)):
        em = e.get("eval_metrics") or {}
        items.append({"episode_id": e["episode_id"], "artifact_dir": e["artifact_dir"],
                      "reference_digest": e.get("native_action_digest"),
                      "recorded_breaks": [(int(b["target_id"]), int(b["consumed_tick"])) for b in em.get("target_breaks") or []]})
    return items


def replay_label(name: str, label_dir: Path, out: Path, *, index_base: int) -> Dict[str, Any]:
    """Exact spatial replays of every final stochastic episode (fresh process each; read-only diagnostics)."""
    import gzip
    from concurrent.futures import ProcessPoolExecutor, as_completed

    import m7k_target2 as t2m
    from m7_runtime import sha256_file

    if sha256_file(t2m.EXECUTABLE) != t2m.EXPECTED_EXE_SHA:
        raise lm.MatrixError("executable differs from the registered build")
    items = replay_items(label_dir)
    tdir = out / "traces"
    tdir.mkdir(parents=True, exist_ok=True)
    done = {p.name.split(".")[0] for p in tdir.glob("*.json.gz")}
    todo = [(i, it) for i, it in enumerate(items) if it["episode_id"] not in done]
    ctx = multiprocessing.get_context("spawn")
    counter = ctx.Value("i", 0)
    failures: List[Dict[str, Any]] = []
    locks: List[float] = []
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=REPLAY_WORKERS, mp_context=ctx, initializer=t2m._init_worker,
                             initargs=(counter,)) as ex:
        futs = {ex.submit(t2m.replay_one, it, str(out / "work"), index_base + i): it for i, it in todo}
        for n, fut in enumerate(as_completed(futs), 1):
            it = futs[fut]
            try:
                r = fut.result()
                t2m.write_json(tdir / f"{it['episode_id']}.json.gz", r, gz=True)
                ex_ = r["exact"]
                cl = r.get("runtime_cleanup") or {}
                if cl.get("locked_s"):
                    locks.append(cl["locked_s"])
                if not (ex_["digest_equal"] and ex_["consumed_tick_mismatch"] is None and ex_["unsent"] == 0
                        and ex_["breaks_equal_recorded"] in (None, True)):
                    failures.append({"episode_id": it["episode_id"], "exact": ex_})
                if cl.get("error"):
                    failures.append({"episode_id": it["episode_id"], "runtime_cleanup": cl})
            except Exception as exc:  # noqa: BLE001 - recorded, never hidden
                failures.append({"episode_id": it["episode_id"], "error": f"{type(exc).__name__}: {exc}"})
    feats = []
    for it in items:
        f = tdir / f"{it['episode_id']}.json.gz"
        if f.is_file():
            with gzip.open(f, "rt", encoding="utf-8") as fp:
                feats.append(t2m.episode_features(json.load(fp)))
    n = len(feats)
    closest = sorted(x["closest"]["distance"] for x in feats if x.get("closest"))
    summary = {"run": name, "label_dir": ec.repo_relative(label_dir), "requested": len(items), "replayed_now": len(todo),
               "traces": n, "failures": failures, "runtime_locked_s": {"n": len(locks), "max": max(locks) if locks else None},
               "wall_s": round(time.perf_counter() - t0, 1),
               "zone": {"x": list(t2m.ZONE_X), "y_min": t2m.ZONE_Y_MIN},
               "zone_visit_episodes": sum(1 for x in feats if x["zone_ticks"] > 0),
               "zone_visit_rate": None if not n else round(sum(1 for x in feats if x["zone_ticks"] > 0) / n, 4),
               "zone_ticks_total": sum(x["zone_ticks"] for x in feats),
               "platform_contact_episodes": sum(1 for x in feats if x["platform_ticks"] > 0),
               "closest_approach": {"median": closest[len(closest) // 2] if closest else None,
                                    "within_600": sum(1 for d in closest if d <= 600.0),
                                    "within_1000": sum(1 for d in closest if d <= 1000.0)},
               "t2_breaks": sum(1 for x in feats if x["t2_broken"]),
               "t2_break_details": [dict(x["t2_break"], episode_id=x["episode_id"], end=x["end"]) for x in feats
                                    if x.get("t2_break")]}
    lm.write_json(out / "features.json", feats)
    lm.write_json(out / "summary.json", summary)
    return summary


def cmd_replay(args: argparse.Namespace) -> int:  # noqa: ARG001
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    state = load_state()
    if post_training_gate() is None:
        return EXIT_FAILED
    labels = [(s.name, s.eval_dir / "final", s.replays_dir) for s in lm.matrix()] + \
        [(lm.HistoricalControl(s).name, lm.HistoricalControl(s).eval_dir / "final",
          lm.replays_root() / lm.HistoricalControl(s).name) for s in lm.SEEDS]
    for k, (name, label_dir, out) in enumerate(labels):
        if (state.get("replays") or {}).get(name, {}).get("complete"):
            continue
        if not (label_dir / "stochastic" / "evaluation.json").is_file():
            log(f"{name}: no final evaluation; replays stop")
            return EXIT_FAILED
        s = replay_label(name, label_dir, out, index_base=40000 + 1000 * k)
        state.setdefault("replays", {})[name] = {k2: s[k2] for k2 in (
            "requested", "traces", "zone_visit_episodes", "zone_visit_rate", "platform_contact_episodes",
            "closest_approach", "t2_breaks", "wall_s")} | {"failures": len(s["failures"]),
                                                          "complete": s["traces"] == s["requested"]}
        save_state(state)
        log(f"{name}: {s['traces']}/{s['requested']} replays, {len(s['failures'])} problem(s), zone visits "
            f"{s['zone_visit_episodes']}, {s['wall_s']:.0f} s")
    return EXIT_OK


# -- census, analysis -------------------------------------------------------------------------------------------------


def census() -> Dict[str, Any]:
    rows, missing, executed = [], [], 0
    for spec in lm.matrix():
        exp = lm.load_run(spec)
        for p in lm.evaluation_plan(spec, exp):
            s = spec.eval_dir / p["label"] / "evaluation_summary.json"
            got = {"deterministic": 0, "stochastic": 0}
            if s.is_file():
                doc = lm.read_json(s)
                got = {m: len(((doc.get("modes") or {}).get(m) or {}).get("episodes") or []) for m in got}
            complete = got == {"deterministic": int(p["deterministic_episodes"]), "stochastic": int(p["stochastic_episodes"])}
            executed += sum(got.values())
            rows.append({"run": spec.name, "label": p["label"], "executed": got, "complete": complete})
            if not complete:
                missing.append(f"{spec.name}:{p['label']} executed {got}")
    return {"plan": lm.census_plan(), "rows": rows, "executed_episodes": executed, "missing": missing,
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
        out.append({"label": lab, "stochastic": n, "t2": sum(f["t2"] for f in facts),
                    "t2_rate": round(sum(f["t2"] for f in facts) / n, 4),
                    "targets_mean": round(sum(f["targets"] for f in facts) / n, 4),
                    "static_mean": round(sum(f["static_all"] for f in facts) / n, 4),
                    "L": sum(f["L"] for f in facts), "R": sum(f["R"] for f in facts),
                    "falls": sum(f["fall"] for f in facts), "clears_native": sum(f["cleared"] for f in facts + det),
                    "left_entries": sum(f["left_entry"] for f in facts),
                    "left_target_episodes": sum(1 for f in facts if f["left_ids"]),
                    "deterministic_targets": sorted({f["targets"] for f in det}),
                    "deterministic_t2": sum(f["t2"] for f in det)})
    return out


def training_facts(run_dir: Path) -> Dict[str, Any]:
    summ = lm.read_json(run_dir / "training_summary.json") if (run_dir / "training_summary.json").is_file() else {}
    rows, _ = dr.jsonl_rows(run_dir / "metrics" / "episodes.jsonl")
    t2 = [r for r in rows if ((r.get("reward_v3") or {}).get("moving_target"))]
    bins: Dict[str, int] = {}
    for r in t2:
        b = (int(r["sb3_num_timesteps_seen"]) - 1) // 307_200
        k = f"{b * 307_200}-{(b + 1) * 307_200}"
        bins[k] = bins.get(k, 0) + 1
    return {"episodes": len(rows), "falls": sum(1 for r in rows if r.get("end_reason") == "fall"),
            "clears": sum(1 for r in rows if r.get("cleared")),
            "target2_events": len(t2), "target2_events_by_transitions": bins,
            "target2_ticks": sorted(int(r["reward_v3"]["moving_target"]["consumed_tick"]) for r in t2),
            "credit_total": round(sum(float(r["reward_v3"]["moving_target"]["moving_target_term"]) for r in t2), 4),
            "sweeps": sum(1 for r in rows if (r.get("reward_v3") or {}).get("right_sweep")),
            "over_wall_entries": sum(int(((r.get("reward_v3") or {}).get("entry_counts") or {}).get("over_wall", 0))
                                     for r in rows),
            "qualified_landings": sum(1 for r in rows if (r.get("reward_v3") or {}).get("qualified_landing")),
            "throughput": summ.get("throughput"), "wall": summ.get("wall"), "cleanup": summ.get("cleanup"),
            "status": summ.get("status")}


def build_report(state: Mapping[str, Any], manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """The rule inputs, `pending` (steps not done: analyze refuses and records nothing) and `integrity` (gate 0)."""
    rule = la.load_rule()
    P = la.params(rule)
    pending: List[str] = []
    integrity: List[str] = list(control_check_problems(manifest))
    specs = lm.matrix()
    for spec in specs:
        st = ((state.get("runs") or {}).get(spec.name) or {}).get("status")
        if st in ("verification_failed", "stopped", "failed", "gate_refused"):
            integrity.append(f"{spec.name}: training {st}")
        elif st != "verified":
            pending.append(f"{spec.name}: training not finished ({st})")
    c = census()
    if not c["complete"]:
        pending.append(f"census incomplete: {len(c['missing'])} labels ({c['missing'][:2]})")
    for spec in specs:
        for plan in lm.evaluation_plan(spec, lm.load_run(spec)):
            key = f"{spec.name}:{plan['label']}"
            ev = (state.get("evaluations") or {}).get(key) or {}
            if "tick0_ok" not in ev:
                pending.append(f"{key}: evaluation not verified")
            elif not ev["tick0_ok"] or not ev.get("ok", False):
                integrity.append(f"{key}: evaluation verification failed (tick-0 {ev['tick0_ok']})")
            cl = (state.get("clears") or {}).get(key)
            if cl is None:
                pending.append(f"{key}: clear verification not run")
            elif cl["verified"] != cl["candidates"]:
                integrity.append(f"{key}: {cl['verified']}/{cl['candidates']} native clears verified")
    for name in [s.name for s in specs] + [lm.HistoricalControl(s).name for s in lm.SEEDS]:
        if not ((state.get("replays") or {}).get(name) or {}).get("traces"):
            pending.append(f"{name}: spatial replays not run")
    inputs: Dict[str, Any] = {"C": {}, "T": {}, "integrity": integrity}
    per_seed: Dict[str, Any] = {}
    labels = [p["label"] for p in lm.evaluation_plan(specs[0], lm.load_run(specs[0]))]
    for spec in specs:
        s = spec.seed
        h = lm.HistoricalControl(s)
        cd_c = h.clears_dir / "final" / "clear_verification.json"
        entry: Dict[str, Any] = {}
        for arm, label_dir, doc in (
                ("C", h.eval_dir / "final", lm.read_json(cd_c) if cd_c.is_file() else None),
                ("T", spec.eval_dir / "final", (lm.read_json(spec.clears_dir / "final" / "clear_verification.json")
                                               if (spec.clears_dir / "final" / "clear_verification.json").is_file()
                                               else None))):
            if not (label_dir / "stochastic" / "evaluation.json").is_file():
                continue
            a, probs = la.label_inputs(label_dir, doc, P)
            inputs[arm][s] = a
            integrity.extend(f"{arm} s{s}: {x}" for x in probs)
            entry[arm] = {"final_stochastic": a.to_json(), "t2_timing": la.t2_timing(a.t2_ticks),
                          "final_deterministic": la.deterministic_facts(label_dir, P),
                          "curve": label_curve(label_dir.parent, labels, P),
                          "replays": (state.get("replays") or {}).get(spec.name if arm == "T" else h.name)}
        entry["training_T"] = training_facts(spec.run_dir) if spec.run_dir.is_dir() else None
        entry["training_attempts_T"] = ((state.get("runs") or {}).get(spec.name) or {}).get("attempts")
        entry["control_equivalence_T"] = {k: v for k, v in (lm.read_json(lm.state_dir() / "verify" / f"{spec.name}.json")
                                                           .get("control_equivalence") or {}).items()
                                          if k != "target2_training_events"} \
            if (lm.state_dir() / "verify" / f"{spec.name}.json").is_file() else None
        per_seed[str(s)] = entry
    evals = {k: {x: v.get(x) for x in ("wall_s", "leak_free", "max_battleship_processes")}
             for k, v in (state.get("evaluations") or {}).items()}
    return {"inputs": inputs, "per_seed": per_seed, "census": {k: c[k] for k in ("plan", "executed_episodes", "missing",
                                                                                "complete")},
            "clears": state.get("clears"), "evaluations": evals, "integrity": integrity, "pending": pending}


def cmd_analyze(args: argparse.Namespace) -> int:
    state = load_state()
    manifest = post_training_gate()
    if manifest is None:
        return EXIT_FAILED
    rule = la.load_rule()
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
        print(json.dumps({"pending": rep["pending"], "integrity": rep["integrity"]}, indent=1, default=str))
        return EXIT_OK
    d = la.decide(rep["inputs"], rule)
    doc = {"decision": d, "per_seed": rep["per_seed"], "census": rep["census"], "clears": rep["clears"],
           "evaluations": rep["evaluations"], "manifest_sha256": lm.sha256_file(frozen_manifest_path()),
           "utc": utc_now()}
    if args.dry_run:
        print(json.dumps(d, indent=1, default=str))
        return EXIT_OK
    out = lm.state_dir() / "analysis_n3.json"
    lm.write_json(out, doc)
    state.setdefault("decisions", {})["n3"] = {"outcome": d["outcome"], "gate": d["gate"], "primary": d["primary"],
                                               "gates": d.get("gates"), "response": d["response"], "utc": utc_now(),
                                               "report": ec.repo_relative(out)}
    save_state(state)
    log(f"decision at n = 3: {d['outcome']} (gate {d['gate']}, primary {d['primary']}): {d['response']}")
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:  # noqa: ARG001
    state = load_state()
    log(f"control check: {(state.get('control') or {}).get('check')}")
    for spec in lm.matrix():
        log(f"{spec.order_index} {spec.name}: {run_status(spec, state)}")
    log(f"evaluations verified: {sum(1 for v in (state.get('evaluations') or {}).values() if v.get('ok'))}; "
        f"replays: {sorted((state.get('replays') or {}))}; decisions: {state.get('decisions')}")
    return EXIT_OK


def cmd_all(args: argparse.Namespace) -> int:
    for name, fn, ns in (("train", cmd_train, argparse.Namespace(dry_run=False, skip_resource_gate=False)),
                         ("evaluate", cmd_evaluate, argparse.Namespace(dry_run=False)),
                         ("verify-clears", cmd_verify_clears, argparse.Namespace()),
                         ("replay", cmd_replay, argparse.Namespace()),
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
    for name in ("train", "preflight"):
        t = sub.add_parser(name)
        t.add_argument("--dry-run", action="store_true")
        t.add_argument("--skip-resource-gate", action="store_true", help="tests / dry runs only")
    e = sub.add_parser("evaluate")
    e.add_argument("--dry-run", action="store_true")
    sub.add_parser("verify-clears")
    sub.add_parser("replay")
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
          "evaluate": cmd_evaluate, "verify-clears": cmd_verify_clears, "replay": cmd_replay, "census": cmd_census,
          "analyze": cmd_analyze, "status": cmd_status, "all": cmd_all}[args.command]
    try:
        return fn(args)
    except lm.MatrixError as exc:
        log(f"ERROR {exc}")
        return EXIT_FAILED
    except KeyboardInterrupt:
        log("interrupted")
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
