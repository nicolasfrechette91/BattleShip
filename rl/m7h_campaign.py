"""M7h campaign driver: frontier-restart curriculum (arm F) against the plain-v1 control (arm C).

Design and rule: docs/rl_frontier_curriculum_m7h_proposal.md (revision 2); registered settings and rule:
docs/rl_frontier_curriculum_m7h_manifest.json and docs/rl_frontier_curriculum_m7h_decision_rule.json. Everything is
written below runs/m7h/campaign; the historical control (runs/m7g_k), the gate tree (runs/m7h/_gate) and every other
run tree are read only.

    python rl/m7h_campaign.py manifest                   # build the manifest (docs/); refused once a campaign froze it
    python rl/m7h_campaign.py control-check              # R1-R3 re-run on this code (about 45 min; trains 3 x 102,400)
    python rl/m7h_campaign.py train --dry-run            # = preflight: plan, drift, control check, profiles, gate
    python rl/m7h_campaign.py train                      # F s0, s1, s2 in order, each behind the launch gate
    python rl/m7h_campaign.py evaluate [--dry-run]       # tick-0 post-hoc protocol, 985 episodes per run
    python rl/m7h_campaign.py verify-clears | verify-entries | census | analyze | status
    python rl/m7h_campaign.py prove-rows [--replays N]   # readiness: the prefix-row identification proof

Launch policy: strictly sequential; the registered launch gate (available commit >= 10 GiB AND available physical >=
4 GiB, disk, CPU, no game process, free ports) before every run; the in-run memory policy (commit only: warn 4, stop 3,
kill 1 GiB) through m7h_guard; a stopped run is moved to _partial (never deleted) and restarted from scratch by a later
invocation; a curriculum run is never resumed; the extension only after a recorded n = 3 decision requiring it; the
control-retrain branch only after a failed control check and an explicit user decision.
"""
from __future__ import annotations

import argparse
import hashlib
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
import m7h_analysis as ma  # noqa: E402
import m7h_curriculum as mc  # noqa: E402
import m7h_guard as g  # noqa: E402
import m7h_matrix as hm  # noqa: E402
import m7h_verify as mv  # noqa: E402

REPO_ROOT = RL_DIR.parent
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_INTERRUPTED = 0, 1, 2, 130
READINESS = REPO_ROOT / "runs" / "m7h" / "_readiness"
GATE_TREE = REPO_ROOT / "runs" / "m7h" / "_gate"
CONTROL_RECORD = "control_check.json"

# Stand-ins for tests (never set in a real invocation): nothing is trained, evaluated or replayed through them.
LAUNCHER: Optional[Callable[..., Dict[str, Any]]] = None
EVALUATE_FN: Optional[Callable[..., Dict[str, Any]]] = None
CONTROL_CHECK_FN: Optional[Callable[..., Dict[str, Any]]] = None
GATE_FN: Optional[Callable[[], Dict[str, Any]]] = None
REPLAY_FN: Optional[Callable[..., Dict[str, Any]]] = None


def log(message: str) -> None:
    print(f"[m7h-campaign {time.strftime('%H:%M:%S')}] {message}", flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# -- state ------------------------------------------------------------------------------------------------------------


def state_file() -> Path:
    return hm.state_dir() / "state.json"


def load_state() -> Dict[str, Any]:
    if state_file().is_file():
        return hm.read_json(state_file())
    return {"schema": "battleship_m7h_campaign_state_v1", "milestone": hm.MILESTONE, "created_utc": utc_now(),
            "control": {"mode": "historical"}, "runs": {}, "evaluations": {}, "entries": {}, "clears": {},
            "decisions": {}, "events": []}


def save_state(state: Dict[str, Any]) -> None:
    state["updated_utc"] = utc_now()
    hm.write_json(state_file(), state)


def event(state: Dict[str, Any], kind: str, **data: Any) -> None:
    state.setdefault("events", []).append(dict(kind=kind, utc=utc_now(), **data))
    save_state(state)


def control_mode(state: Mapping[str, Any]) -> str:
    return ((state.get("control") or {}).get("mode")) or "historical"


# -- the manifest ----------------------------------------------------------------------------------------------------


def frozen_manifest_path() -> Path:
    return hm.state_dir() / "manifest.json"


def load_manifest(*, freeze: bool) -> Dict[str, Any]:
    fp = frozen_manifest_path()
    if fp.is_file():
        return hm.read_json(fp)
    if not hm.MANIFEST_DOC.is_file():
        raise hm.MatrixError(f"{ec.repo_relative(hm.MANIFEST_DOC)} missing: run 'python rl/m7h_campaign.py manifest'")
    man = hm.read_json(hm.MANIFEST_DOC)
    if freeze:
        hm.write_json(fp, man)
    return man


def cmd_manifest(args: argparse.Namespace) -> int:
    if frozen_manifest_path().is_file() and not args.out:
        log(f"refused: the campaign froze its manifest at {ec.repo_relative(frozen_manifest_path())}; it is never rebuilt")
        return EXIT_USAGE
    man = hm.build_manifest()
    out = Path(args.out) if args.out else hm.MANIFEST_DOC
    hm.write_json(out, man)
    log(f"manifest -> {ec.repo_relative(out)} ok={man['ok']} code {man['code']['sha256'][:12]} ({man['code']['files']} files)")
    for p in man["problems"]:
        log(f"  PROBLEM {p}")
    return EXIT_OK if man["ok"] else EXIT_FAILED


# -- amendments to the frozen manifest (post-training verification only) -----------------------------------------------
#
# The frozen manifest is never rebuilt. An amendment is a separate dated record that names the frozen manifest (sha256),
# its code fingerprint, the new code fingerprint and, per changed file, the hashes before and after. It is honoured
# only by the post-training commands (evaluate, verify-clears, verify-entries, analyze) and only when every other
# identity still equals the manifest (executable, HEAD, submodules, decision rule, every profile) and every changed file
# is one of AMENDABLE_FILES. train and control-check keep the strict hm.manifest_drift. The first honoured use freezes
# the record next to the manifest; a later change of the docs copy is refused.

AMENDMENT_DOC = REPO_ROOT / "docs" / "rl_frontier_curriculum_m7h_amendment_1.json"
AMENDMENT_SCHEMA = "m7h_manifest_amendment_v1"
AMENDABLE_FILES = ("rl/m7h_verify.py", "rl/m7h_campaign.py")   # evaluation verification and this driver's drift gate


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def manifest_file_sha256() -> Optional[str]:
    fp = frozen_manifest_path() if frozen_manifest_path().is_file() else hm.MANIFEST_DOC
    return _sha256_bytes(fp.read_bytes()) if fp.is_file() else None


def frozen_amendment_path() -> Path:
    return hm.state_dir() / "amendments" / AMENDMENT_DOC.name


def amendment_problems(manifest: Mapping[str, Any], code_now: Mapping[str, Any], am: Mapping[str, Any]) -> List[str]:
    """Why this amendment does not cover the difference between the manifest's code and code_now (empty = it does)."""
    code = manifest.get("code") or {}
    p: List[str] = []
    if am.get("schema") != AMENDMENT_SCHEMA:
        p.append(f"schema {am.get('schema')!r}")
    if am.get("manifest_sha256") != manifest_file_sha256():
        p.append("it names another manifest (sha256)")
    if am.get("original_code_sha256") != code.get("sha256"):
        p.append("its original code fingerprint is not the manifest's")
    if am.get("amended_code_sha256") != code_now.get("sha256"):
        p.append(f"its amended code fingerprint is not the current one ({str(code_now.get('sha256'))[:12]})")
    ctl = am.get("control_record") or {}
    if not control_record_path().is_file() or ctl.get("sha256") != _sha256_bytes(control_record_path().read_bytes()):
        p.append("the control record differs from the one the amendment reuses")
    before, now = code.get("per_file") or {}, code_now.get("per_file") or {}
    changed = sorted(k for k in set(before) | set(now) if before.get(k) != now.get(k))
    declared = am.get("files") or {}
    if changed != sorted(declared):
        p.append(f"changed files {changed} != amended files {sorted(declared)}")
    for k in sorted(set(changed) | set(declared)):
        if k not in AMENDABLE_FILES:
            p.append(f"{k} may not be amended (only {list(AMENDABLE_FILES)})")
        d = declared.get(k) or {}
        if (d.get("before"), d.get("after")) != (before.get(k), now.get(k)):
            p.append(f"{k}: the amendment's hashes are not the manifest's and the current file's")
    return p


def evaluation_drift(manifest: Mapping[str, Any], *, state: Optional[Dict[str, Any]] = None
                     ) -> Tuple[List[str], Optional[Dict[str, Any]]]:
    """The drift gate of the post-training commands: (problems, honoured amendment or None). Every identity must equal
    the manifest; a code-fingerprint difference is excused only by a registered amendment of AMENDABLE_FILES. With a
    state (a real run, not a dry run), the first honoured use freezes the amendment and records an event."""
    cur = hm.current_identity()
    strict = hm.manifest_drift(manifest, cur)
    if not strict:
        return [], None
    others = hm.manifest_drift(manifest, dict(cur, code_sha256=(manifest.get("code") or {}).get("sha256")))
    if others or not AMENDMENT_DOC.is_file():
        return strict + ([] if others else [f"no amendment ({ec.repo_relative(AMENDMENT_DOC)}) covers the code change"]), None
    raw = AMENDMENT_DOC.read_bytes()
    fz = frozen_amendment_path()
    if fz.is_file() and fz.read_bytes() != raw:
        return strict + [f"{ec.repo_relative(AMENDMENT_DOC)} differs from the copy frozen at its first use"], None
    am = json.loads(raw.decode("utf-8"))
    p = amendment_problems(manifest, hm.code_fingerprint(), am)
    if p:
        return strict + [f"amendment {am.get('amendment')}: {x}" for x in p], None
    info = {"amendment": am.get("amendment"), "date": am.get("date"), "sha256": _sha256_bytes(raw),
            "path": ec.repo_relative(AMENDMENT_DOC), "files": sorted(am.get("files") or {}),
            "original_code_sha256": am.get("original_code_sha256"), "amended_code_sha256": am.get("amended_code_sha256")}
    if state is not None and not fz.is_file():
        fz.parent.mkdir(parents=True, exist_ok=True)
        fz.write_bytes(raw)
        event(state, "amendment_frozen", frozen=ec.repo_relative(fz), **info)
    return [], info


# -- resources --------------------------------------------------------------------------------------------------------


def launch_gate() -> Dict[str, Any]:
    return (GATE_FN or g.launch_gate)()


# -- the control check (R1-R3 on the frozen code) --------------------------------------------------------------------


def control_record_path() -> Path:
    return hm.control_root() / CONTROL_RECORD


def control_check_problems(manifest: Mapping[str, Any], state: Mapping[str, Any]) -> List[str]:
    """Why the historical control may not be reused now (empty = it may): a passed R1-R3 record for exactly the
    manifest's code, executable and submodules, and the historical control files unchanged since the manifest."""
    if control_mode(state) == "retrained":
        return []
    p: List[str] = []
    rec = hm.read_json(control_record_path()) if control_record_path().is_file() else None
    code = (manifest.get("code") or {}).get("sha256")
    if rec is None:
        p.append("the R1-R3 control check has not run on this code: python rl/m7h_campaign.py control-check")
    else:
        if not rec.get("ok"):
            p.append(f"the R1-R3 control check FAILED ({rec.get('problems')}); the control is not reused (a retrain "
                     f"needs an explicit decision: train --retrain-control)")
        if rec.get("code_sha256") != code:
            p.append(f"the control check ran on code {str(rec.get('code_sha256'))[:12]}, the manifest is {str(code)[:12]}: "
                     f"re-run control-check")
        if rec.get("executable_sha256") != (manifest.get("executable") or {}).get("sha256"):
            p.append("the control check ran on another executable")
        if (rec.get("revisions") or {}).get("submodules") != (manifest.get("revisions") or {}).get("submodules"):
            p.append("the control check ran on other submodule revisions")
    for s, want in ((manifest.get("historical_control") or {}).get("seeds") or {}).items():
        now = hm.historical_identity(int(s))
        keys = ("final_checkpoint_json_sha256", "final_digests", "final_evaluation_sha256", "rule_inputs")
        if not now["ok"] or any(now.get(k) != want.get(k) for k in keys):
            p.append(f"historical control seed {s} changed since the manifest or no longer verifies: {now['problems'][:2]}")
    return p


def _run_r_checks(out: Path, seeds: Sequence[int]) -> Dict[str, Any]:
    import m7h_run as hr

    ns = argparse.Namespace(seeds=",".join(str(s) for s in seeds), base=out)
    rc = {"r1": hr.cmd_r1(ns), "r2": hr.cmd_r2(ns), "r3": hr.cmd_r3(ns)}
    results = {}
    for f in sorted((out / "results").glob("r*.json")):
        results[f.stem] = {k: v for k, v in hm.read_json(f).items() if k in ("check", "seed", "ok", "problems",
                                                                              "final_digests", "rows_compared", "compared",
                                                                              "per_seed", "wall_s")}
    problems = [f"{k}: exit {v}" for k, v in rc.items() if v != 0] + \
        [f"{k}: {r['problems'][:2]}" for k, r in results.items() if not r.get("ok")]
    want = {f"r1_s{s}" for s in seeds} | {f"r2_s{s}" for s in seeds} | {"r3"}
    if not want <= set(results):
        problems.append(f"missing results {sorted(want - set(results))}")
    return {"exit_codes": rc, "results": results, "problems": problems, "ok": not problems}


def cmd_control_check(args: argparse.Namespace) -> int:
    state = load_state()
    manifest = load_manifest(freeze=False)
    drift = hm.manifest_drift(manifest)
    if drift:
        for p in drift:
            log(f"BLOCKED {p}")
        log("rebuild the manifest (before the first launch only), then run the control check on that code")
        return EXIT_FAILED
    code = manifest["code"]["sha256"]
    out = hm.control_root() / f"code_{code[:12]}__{stamp()}"
    if args.dry_run:
        log(f"dry run: R1 (3 x 102,400 transitions, curriculum off) -> R2 (600 episodes) -> R3 into {ec.repo_relative(out)}")
        return EXIT_OK
    try:
        res = (CONTROL_CHECK_FN or _run_r_checks)(out, [int(s) for s in args.seeds.split(",")])
    except RuntimeError as exc:          # e.g. the launch gate refused an R1 run: not a reproduction result
        log(f"control check NOT completed (nothing recorded; not a failed reproduction): {exc}")
        return EXIT_FAILED
    rec = {"schema": "m7h_control_check_v1", "utc": utc_now(), "code_sha256": code,
           "executable_sha256": manifest["executable"]["sha256"], "revisions": manifest["revisions"],
           "out": ec.repo_relative(out), **res}
    hm.write_json(out / CONTROL_RECORD, rec)
    hm.write_json(control_record_path(), rec)
    state.setdefault("control", {})["check"] = {k: rec[k] for k in ("utc", "code_sha256", "ok", "out")}
    event(state, "control_check", ok=rec["ok"], code_sha256=code, out=rec["out"])
    log(f"control check {'PASS' if rec['ok'] else 'FAIL'} {rec['problems'][:3]}")
    return EXIT_OK if rec["ok"] else EXIT_FAILED


# -- training ---------------------------------------------------------------------------------------------------------


def run_status(spec: hm.RunSpec, state: Mapping[str, Any]) -> str:
    """verified | completed_unverified | partial | absent."""
    if (((state.get("runs") or {}).get(spec.name) or {}).get("status")) == "verified":
        return "verified"
    if not spec.run_dir.exists():
        return "absent"
    summ = spec.run_dir / "training_summary.json"
    if summ.is_file() and hm.read_json(summ).get("status") == "completed":
        return "completed_unverified"
    return "partial"


def train_plan(specs: Sequence[hm.RunSpec], state: Mapping[str, Any], args: argparse.Namespace) -> List[Dict[str, Any]]:
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
            action = ("move the partial directory aside intact, then train from scratch"
                      if getattr(args, "restart_partial", None) == spec.name else
                      f"STOP: partial run directory; --restart-partial {spec.name} moves it to _partial and restarts "
                      f"from scratch (a curriculum run is never resumed)")
        else:
            action = "train from scratch"
        if getattr(args, "only", None) and args.only != spec.name:
            action = f"STOP: out of order ({spec.name} is the next run; --only {args.only} refused)"
        plan.append({"run": spec.name, "status": st, "action": action})
        blocked = True
    return plan


def preflight_run(spec: hm.RunSpec, exp: ec.Experiment, manifest: Mapping[str, Any]) -> Dict[str, Any]:
    checks = hm.arm_checks(spec, exp)
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


def move_partial_aside(spec: hm.RunSpec, state: Dict[str, Any]) -> Path:
    dest = hm.partial_root() / f"{spec.name}__{stamp()}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    spec.run_dir.rename(dest)
    event(state, "partial_run_moved_aside", run=spec.name, to=ec.repo_relative(dest),
          policy="kept intact, never deleted; restarted from scratch with the same seed; never resumed")
    return dest


def _guarded_launch(*, spec: hm.RunSpec, exp: ec.Experiment, **_: Any) -> Dict[str, Any]:
    tag = f"{spec.name}__{stamp()}"
    return g.train_guarded(config=spec.config_path, run_dir=spec.run_dir, log_path=hm.guard_root() / "logs" / f"{tag}.log",
                           monitor_path=hm.guard_root() / "monitor" / f"{tag}.jsonl",
                           probe_path=hm.guard_root() / "probe" / f"{tag}.jsonl", contract=exp.reward,
                           horizon=int(exp.values["environment.horizon"]), partial_root=hm.partial_root(),
                           output_root=None if hm.root() == hm.DEFAULT_ROOT else spec.run_dir.parent)


def run_identity(run_dir: Path, spec: hm.RunSpec, manifest: Mapping[str, Any]) -> List[str]:
    rj = hm.read_json(run_dir / "run.json")
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
    if rj.get("lineage"):
        p.append(f"not a fresh model: lineage {rj.get('lineage')}")
    cur = (rj.get("config") or {}).get("curriculum")
    if spec.curriculum and cur != mc.REGISTERED:
        p.append(f"run.json curriculum {cur}")
    if not spec.curriculum and cur is not None:
        p.append("a curriculum-off run recorded a curriculum")
    return p


def control_path_clean(run_dir: Path) -> List[str]:
    """R1 (c) / (d) for a curriculum-off campaign run (C3, C4 or a retrained C): no curriculum trace anywhere."""
    rows = mv.jsonl(run_dir / "metrics" / "episodes.jsonl")
    p = []
    if any("m7h" in r for r in rows):
        p.append("episode rows carry an m7h block")
    if (run_dir / "curriculum").exists():
        p.append("a curriculum directory exists")
    if any(mc.START_LABEL in (m.get("labels") or {}) for _a, m in mv.artifacts_of(run_dir)):
        p.append("an artifact carries m7h_start")
    fin = run_dir / "final" / "checkpoint.json"
    if fin.is_file() and any(k in hm.read_json(fin) for k in ("extra_files", "interruption")):
        p.append("the final set carries extra files or an interruption block")
    return p


def verify_run(spec: hm.RunSpec, exp: ec.Experiment, manifest: Mapping[str, Any]) -> Dict[str, Any]:
    r = (manifest.get("runs") or {}).get(spec.name) or {}
    expected = (r.get("expected_initial_policy_digest"), r.get("expected_initial_obs_rms_digest"))
    ver = dr.verify_training_run(spec.run_dir, exp, fresh=True, expected_initial=expected)
    ident = run_identity(spec.run_dir, spec, manifest)
    ver["m7h_identity"] = ident
    if spec.curriculum:
        cur = mv.verify_curriculum_run(spec.run_dir, run_id=spec.name, horizon=hm.HORIZON, n_envs=hm.PROCESS_COUNT)
        ver["curriculum_verification"] = {k: cur[k] for k in ("ok", "problems", "violations", "counts", "archive",
                                                               "checkpoint_sets")}
        extra = [] if cur["ok"] else [f"curriculum: {x}" for x in cur["problems"][:5]]
    else:
        extra = [f"control path: {x}" for x in control_path_clean(spec.run_dir)]
    if ident or extra:
        ver["problems"].extend(ident + extra)
        ver["ok"] = False
    return ver


def cmd_train(args: argparse.Namespace) -> int:
    if getattr(args, "resume", None):
        log("refused: a curriculum campaign run is never resumed; a stopped run is restarted from scratch "
            "(--restart-partial NAME)")
        return EXIT_USAGE
    state = load_state()
    if getattr(args, "retrain_control", False) and control_mode(state) != "retrained":
        rec = hm.read_json(control_record_path()) if control_record_path().is_file() else None
        if rec is None or rec.get("ok"):
            log("refused: the control is retrained only after a FAILED control check (none recorded)")
            return EXIT_USAGE
        if args.dry_run:
            log("dry run: would record the user decision to retrain the control (order C0, F0, F1, C1, C2, F2)")
        else:
            state["control"] = {"mode": "retrained", "decided_utc": utc_now(), "failed_check": rec.get("out")}
            event(state, "control_retrain_decision", failed_check=rec.get("out"))
    ext = bool(getattr(args, "extension", False))
    n3 = (state.get("decisions") or {}).get("n3") or {}
    if ext and not n3.get("extension_required"):
        log(f"the extension is refused: no recorded n = 3 decision requires it (recorded: gate {n3.get('gate')})")
        return EXIT_USAGE
    specs = hm.extension_specs(control_mode(state)) if ext else hm.matrix(control=control_mode(state))
    manifest = load_manifest(freeze=not args.dry_run)
    drift = hm.manifest_drift(manifest)
    plan = train_plan(specs, state, args)
    report: Dict[str, Any] = {"dry_run": bool(args.dry_run), "extension": ext, "control": control_mode(state),
                              "plan": plan, "manifest_drift": drift, "control_check": control_check_problems(manifest, state),
                              "preflight": {s.name: preflight_run(s, hm.load_run(s), manifest) for s in specs},
                              "directory_plan": hm.check_directory_plan()}
    report["resources"] = None if args.skip_resource_gate else launch_gate()
    blocking = drift + report["control_check"] + [p for pf in report["preflight"].values() for p in pf["problems"]] + \
        report["directory_plan"]["problems"] + ([] if report["resources"] is None else report["resources"]["problems"])
    report["blocking_problems"] = blocking
    if args.dry_run:
        print(json.dumps(report, indent=1, default=str), flush=True)
        log(f"dry run: nothing launched, nothing written; blocking problems {len(blocking)}")
        return EXIT_OK if not blocking else EXIT_FAILED
    if blocking:
        for p in blocking:
            log(f"BLOCKED {p}")
        return EXIT_FAILED
    event(state, "train_invocation", plan=plan, resources=report["resources"])
    launcher = LAUNCHER or _guarded_launch
    handled: set = set()
    first = True
    while True:
        step = next((s for s in train_plan(specs, state, args) if s["action"] != "skip"), None)
        if step is None:
            log("every run of this matrix is verified")
            return EXIT_OK
        spec = hm.run_by_name(step["run"])
        spec = next(s for s in specs if s.name == spec.name)
        action = step["action"]
        if action.startswith(("STOP", "wait")):
            log(f"{spec.name}: {action}")
            return EXIT_USAGE if action.startswith("STOP") else EXIT_OK
        if spec.name in handled:
            log(f"{spec.name}: not verified after this invocation's attempt; stopping")
            return EXIT_FAILED
        handled.add(spec.name)
        if getattr(args, "only", None):
            args.only = None
        exp = hm.load_run(spec)
        rs = state["runs"].setdefault(spec.name, {"status": "pending", "attempts": []})
        if action.startswith("verify"):
            ver = verify_run(spec, exp, manifest)
            hm.write_json(hm.state_dir() / "verify" / f"{spec.name}.json", ver)
            rs.update(status="verified" if ver["ok"] else "verification_failed", verification=ver["problems"][:20])
            save_state(state)
            if not ver["ok"]:
                log(f"{spec.name}: verification FAILED {ver['problems'][:3]}")
                return EXIT_FAILED
            continue
        if action.startswith("move"):
            move_partial_aside(spec, state)
        if not first and not args.skip_resource_gate:        # the launch gate before EVERY launch
            gate = launch_gate()
            if not gate["ok"]:
                event(state, "launch_gate_refused", run=spec.name, gate=gate)
                log(f"{spec.name}: launch gate refused {gate['problems']}; stopping (re-run train later)")
                return EXIT_FAILED
        first = False
        log(f"{spec.name}: launching (arm {spec.arm}, seed {spec.seed}, {hm.TOTAL_TRANSITIONS:,} policy transitions)")
        t0 = time.perf_counter()
        res = launcher(spec=spec, exp=exp, manifest=manifest)
        attempt = {"utc": utc_now(), "wall_s": round(time.perf_counter() - t0, 1), "exit_code": res.get("exit_code"),
                   "stop_kind": res.get("stop_kind"), "moved_to": res.get("moved_to"),
                   "probe": {k: (res.get("probe") or {}).get(k) for k in ("min_avail_commit_gib", "min_avail_phys_gib",
                                                                           "samples_physical_below_launch_gate")},
                   "commit_drawn_gib": res.get("commit_drawn_gib"),
                   "max_battleship_processes": (res.get("monitor") or {}).get("max_battleship_processes")}
        rs.setdefault("attempts", []).append(attempt)
        if res.get("stop_kind"):
            rs["status"] = "stopped"
            event(state, "run_stopped", run=spec.name, stop_kind=res["stop_kind"], moved_to=res.get("moved_to"))
            log(f"{spec.name}: STOPPED ({res['stop_kind']}); preserved at {res.get('moved_to')}; restart from scratch "
                f"with a later 'train' after the launch gate passes")
            return EXIT_INTERRUPTED
        if res.get("exit_code") != 0:
            rs["status"] = "failed"
            save_state(state)
            log(f"{spec.name}: trainer exit {res.get('exit_code')}; the directory stays (partial); see the guard log")
            return EXIT_FAILED
        ver = verify_run(spec, exp, manifest)
        hm.write_json(hm.state_dir() / "verify" / f"{spec.name}.json", ver)
        rs.update(status="verified" if ver["ok"] else "verification_failed", verification=ver["problems"][:20],
                  curriculum_ok=(ver.get("curriculum_verification") or {}).get("ok"))
        save_state(state)
        if not ver["ok"]:
            log(f"{spec.name}: verification FAILED {ver['problems'][:3]}")
            return EXIT_FAILED
        log(f"{spec.name}: verified")


# -- evaluation (tick-0 only) ------------------------------------------------------------------------------------------


def checkpoint_provenance(ckpt: Path, spec: hm.RunSpec, exp: ec.Experiment, planned_t: int,
                          manifest: Mapping[str, Any]) -> List[str]:
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
    if (meta.get("ppo") or {}).get("policy") != "MlpPolicy" or meta.get("policy_network") is not None:
        p.append("policy / network identity")
    lc = meta.get("lifecycle") or {}
    if (lc.get("standby_preboot"), lc.get("standby_count")) != (True, 1):
        p.append(f"lifecycle {lc}")
    if meta.get("interruption"):
        p.append("an interrupted set is never evaluated")
    extra = set((meta.get("extra_files") or {}))
    if spec.curriculum and planned_t > 0 and not {"curriculum_archive.json", "curriculum_prefixes.bin"} <= extra:
        p.append(f"a curriculum set without its archive: {sorted(extra)}")
    if not spec.curriculum and extra:
        p.append(f"a curriculum-off set with extra files {sorted(extra)}")
    return p


def run_eval_label(state: Dict[str, Any], key: str, out_dir: Path, fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    """One label under the monitor; atomic: a complete summary is reused, a partial directory is moved aside."""
    import m7g_k_run as kr   # measurement only (preconditions); nothing of the Phase K state is touched

    done = out_dir / "evaluation_summary.json"
    if done.is_file():
        return hm.read_json(done)
    if out_dir.exists():
        aside = out_dir.with_name(out_dir.name + "__incomplete_" + stamp())
        out_dir.rename(aside)
        event(state, "incomplete_evaluation_moved_aside", key=key, to=ec.repo_relative(aside))
    pre = kr.preconditions(f"before evaluation {key}")
    if pre["problems"]:
        raise hm.MatrixError(f"evaluation {key}: preconditions failed: {pre['problems']}")
    monitor = dr.Monitor(out=hm.state_dir() / "monitor" / "evaluation.jsonl", root_pid=os.getpid()).start()
    t0 = time.perf_counter()
    try:
        result = fn()
    finally:
        mon = monitor.stop()
    post = dr.system_state(label=f"after evaluation {key}")
    state.setdefault("evaluations", {}).setdefault(key, {}).update(
        wall_s=round(time.perf_counter() - t0, 1), finished_utc=utc_now(), leak_free=not post["battleship_pids"],
        monitor_hard_alerts=mon.get("hard_alerts"), out_dir=ec.repo_relative(out_dir))
    save_state(state)
    if mon.get("hard_alerts") or post["battleship_pids"]:
        raise hm.MatrixError(f"evaluation {key}: monitor alerts {mon.get('hard_alerts')} / leaked {post['battleship_pids']}")
    return result


def checkpoint_for(spec: hm.RunSpec, label: str, t: int) -> Path:
    return spec.run_dir / "final" if label == "final" else spec.run_dir / "checkpoints" / f"ckpt_{t:09d}"


def evaluate_label(state: Dict[str, Any], spec: hm.RunSpec, exp: ec.Experiment, plan: Mapping[str, Any],
                   manifest: Mapping[str, Any], *, dry_run: bool = False) -> Dict[str, Any]:
    import m7_evaluation as ev
    import m7_trainer as tr
    import m7g_k_run as kr   # pure helpers only: phase_k_settings, verify_metrics

    key = f"{spec.name}:{plan['label']}"
    ckpt = checkpoint_for(spec, plan["label"], int(plan["num_timesteps"]))
    prov = checkpoint_provenance(ckpt, spec, exp, int(plan["num_timesteps"]), manifest)
    if prov or dry_run:
        return {"key": key, "checkpoint": ec.repo_relative(ckpt), "provenance_problems": prov, "ran": False}
    evaluate = EVALUATE_FN or ev.evaluate_checkpoint
    out = spec.eval_dir / plan["label"]
    settings = kr.phase_k_settings(exp)
    cfg = tr.config_from_experiment(exp)
    res = run_eval_label(state, key, out, lambda: evaluate(
        ckpt, out, settings=settings, deterministic_episodes=int(plan["deterministic_episodes"]),
        stochastic_episodes=int(plan["stochastic_episodes"]), expected_contracts=tr.run_contracts(cfg),
        label=plan["label"], preserve_all=True))
    ver = dr.verify_evaluation(res, exp.reward, int(exp.values["environment.horizon"]), plan)
    ver["problems"].extend(kr.verify_metrics(res, arm=None))
    for mode, r in (res.get("modes") or {}).items():
        if dict(r.get("extra_env") or {}) != dict(hm.M6_FLAGS, **hm.EVAL_METRICS_FLAG):
            ver["problems"].append(f"{mode}: evaluation flags {r.get('extra_env')}")
    t0 = mv.verify_eval_tick0(out)
    ver["tick0"] = {k: t0[k] for k in ("ok", "problems", "artifacts", "rows")}
    ver["problems"].extend(f"tick0: {x}" for x in t0["problems"])
    ver["ok"] = not ver["problems"]
    state["evaluations"][key].update(verification=ver["problems"][:20], ok=ver["ok"], tick0_ok=t0["ok"],
                                     checkpoint=ec.repo_relative(ckpt), num_timesteps=int(plan["num_timesteps"]))
    save_state(state)
    return {"key": key, "checkpoint": ec.repo_relative(ckpt), "provenance_problems": [], "ran": True, "verification": ver}


def _specs_for_now(state: Mapping[str, Any]) -> List[hm.RunSpec]:
    n3 = (state.get("decisions") or {}).get("n3") or {}
    return hm.matrix(control=control_mode(state), include_extension=bool(n3.get("extension_required")))


def post_training_gate(state: Dict[str, Any], *, dry_run: bool = False
                       ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """(manifest, honoured amendment) when the post-training drift gate passes, else (None, None) after logging."""
    manifest = load_manifest(freeze=False)
    drift, am = evaluation_drift(manifest, state=None if dry_run else state)
    if drift:
        for p in drift:
            log(f"BLOCKED {p}")
        return None, None
    if am:
        log(f"drift gate: amendment {am['amendment']} ({am['date']}) honoured for {am['files']}; code "
            f"{am['original_code_sha256'][:12]} -> {am['amended_code_sha256'][:12]}")
    return manifest, am


def cmd_evaluate(args: argparse.Namespace) -> int:
    state = load_state()
    manifest, _am = post_training_gate(state, dry_run=args.dry_run)
    if manifest is None:
        return EXIT_FAILED
    if not args.dry_run:
        from m7_runtime import install_kill_on_close_job

        install_kill_on_close_job()
    only = set(args.only.split(",")) if args.only else None
    labels = set(args.labels.split(",")) if args.labels else None
    report: List[Dict[str, Any]] = []
    for spec in _specs_for_now(state):
        if only and spec.name not in only:
            continue
        if ((state.get("runs") or {}).get(spec.name) or {}).get("status") != "verified":
            report.append({"run": spec.name, "skipped": "training not verified"})
            continue
        exp = hm.load_run(spec)
        for plan in hm.evaluation_plan(spec, exp):
            if labels and plan["label"] not in labels and not (plan["label"].startswith("curve") and "curve" in labels):
                continue
            r = evaluate_label(state, spec, exp, plan, manifest, dry_run=args.dry_run)
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


def cmd_verify_clears(args: argparse.Namespace) -> int:
    import m7g_k_run as kr   # verify_clears_in writes only into the given out_dir
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    state = load_state()
    if post_training_gate(state)[0] is None:
        return EXIT_FAILED
    ok = True
    saved = kr.REPLAY_FN
    kr.REPLAY_FN = REPLAY_FN or saved
    try:
        for spec in _specs_for_now(state):
            if args.only and spec.name not in args.only.split(",") or not spec.eval_dir.is_dir():
                continue
            exp = hm.load_run(spec)
            for label_dir in sorted(p for p in spec.eval_dir.iterdir() if p.is_dir() and "__incomplete_" not in p.name):
                if (spec.clears_dir / label_dir.name / "clear_verification.json").is_file():
                    continue
                doc = kr.verify_clears_in(label_dir, spec.clears_dir / label_dir.name, executable=exp.executable,
                                          extra_env=dict(exp.extra_env))
                state.setdefault("clears", {})[f"{spec.name}:{label_dir.name}"] = {
                    "candidates": doc["candidates"], "verified": doc["verified"]}
                save_state(state)
                if doc["candidates"]:
                    log(f"{spec.name}:{label_dir.name}: {doc['verified']}/{doc['candidates']} clears verified")
                    ok &= doc["verified"] == doc["candidates"]
    finally:
        kr.REPLAY_FN = saved
    return EXIT_OK if ok else EXIT_FAILED


def cmd_verify_entries(args: argparse.Namespace) -> int:
    """Section 4: per F run, the first genuine new policy entry and up to 5 more replayed from tick 0 (g_s)."""
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    state = load_state()
    if post_training_gate(state)[0] is None:
        return EXIT_FAILED
    for spec in _specs_for_now(state):
        if not spec.curriculum or (args.only and spec.name not in args.only.split(",")):
            continue
        if ((state.get("runs") or {}).get(spec.name) or {}).get("status") != "verified":
            continue
        if spec.entries_dir.exists():
            aside = spec.entries_dir.with_name(spec.entries_dir.name + "__incomplete_" + stamp())
            spec.entries_dir.rename(aside)
        exp = hm.load_run(spec)
        res = mv.verify_left_entries(spec.run_dir, out_dir=spec.entries_dir, executable=exp.executable,
                                     extra_env=dict(hm.M6_FLAGS, **hm.EVAL_METRICS_FLAG))
        hm.write_json(spec.entries_dir / "entries.json", res)
        state.setdefault("entries", {})[spec.name] = {k: res[k] for k in ("genuine_episodes_recorded", "replayed",
                                                                          "verified", "g")}
        save_state(state)
        log(f"{spec.name}: {res['verified']}/{res['replayed']} genuine entries verified (recorded "
            f"{res['genuine_episodes_recorded']}); g = {res['g']}")
    return EXIT_OK


# -- census, analysis ---------------------------------------------------------------------------------------------------


def census(state: Mapping[str, Any], *, include_extension: bool) -> Dict[str, Any]:
    control = control_mode(state)
    rows, missing, executed = [], [], 0
    for spec in hm.matrix(control=control, include_extension=include_extension):
        exp = hm.load_run(spec)
        for p in hm.evaluation_plan(spec, exp):
            s = spec.eval_dir / p["label"] / "evaluation_summary.json"
            got = {"deterministic": 0, "stochastic": 0}
            if s.is_file():
                doc = hm.read_json(s)
                got = {m: len(((doc.get("modes") or {}).get(m) or {}).get("episodes") or []) for m in got}
            complete = got == {"deterministic": int(p["deterministic_episodes"]), "stochastic": int(p["stochastic_episodes"])}
            executed += sum(got.values())
            rows.append({"run": spec.name, "label": p["label"], "executed": got, "complete": complete})
            if not complete:
                missing.append(f"{spec.name}:{p['label']} executed {got}")
    plan = hm.census_plan(control=control, include_extension=include_extension)
    return {"plan": plan, "rows": rows, "executed_episodes": executed, "missing": missing, "complete": not missing}


def cmd_census(args: argparse.Namespace) -> int:
    c = census(load_state(), include_extension=args.extension)
    log(f"planned {c['plan']['episodes']} ({c['plan']['arithmetic']}); executed {c['executed_episodes']}; missing "
        f"{len(c['missing'])}")
    return EXIT_OK if c["complete"] else EXIT_FAILED


def _clear_doc(clears_dir: Path) -> Optional[Dict[str, Any]]:
    f = clears_dir / "final" / "clear_verification.json"
    return hm.read_json(f) if f.is_file() else None


def training_diagnostics(spec: hm.RunSpec) -> Dict[str, Any]:
    """Reported, never gating: section-4 classes, archive size, the lowest x at y >= 3000, L and prefix cost."""
    rows = mv.jsonl(spec.run_dir / "metrics" / "episodes.jsonl")
    m = [r.get("m7h") or {} for r in rows]
    Ls = sorted(int(x.get("prefix_length") or 0) for x in m if x.get("start_kind") == mc.START_PREFIX)
    classes: Dict[str, int] = {}
    for x in m:
        if x.get("class"):
            classes[x["class"]] = classes.get(x["class"], 0) + 1
    lows = [float(x["min_x_at_high_y_policy"]) for x in m if x.get("min_x_at_high_y_policy") is not None]
    summ = hm.read_json(spec.run_dir / "training_summary.json") if (spec.run_dir / "training_summary.json").is_file() else {}
    cur = summ.get("curriculum") or {}
    return {"episodes": len(rows), "falls": sum(1 for r in rows if r.get("end_reason") == "fall"), "classes": classes,
            "starts": cur.get("starts"), "archive": cur.get("archive"),
            "lowest_x_at_y_ge_3000_policy": min(lows) if lows else None,
            "prefix_L": {"starts": len(Ls), "min": Ls[0] if Ls else None, "median": Ls[len(Ls) // 2] if Ls else None,
                         "max": Ls[-1] if Ls else None, "mean": round(sum(Ls) / len(Ls), 1) if Ls else None},
            "prefix_cost": {k: cur.get(k) for k in ("prefix_ticks", "dispatch_wall_s", "dispatch_steps",
                                                    "max_dispatch_wall_s")},
            "left_episodes_kept": cur.get("left_episodes_kept")}


def build_report(state: Mapping[str, Any], manifest: Mapping[str, Any], *, include_extension: bool) -> Dict[str, Any]:
    """The rule inputs, plus two lists: `pending` (a step not done yet: a run not trained, an evaluation, a clear or
    entry verification not run; analyze then refuses and records nothing) and `integrity` (gate 0: a violation of a
    registered condition in finished work)."""
    control = control_mode(state)
    specs = hm.matrix(control=control, include_extension=include_extension)
    pending: List[str] = []
    integrity: List[str] = list(control_check_problems(manifest, state))
    for spec in specs:
        st = ((state.get("runs") or {}).get(spec.name) or {}).get("status")
        if st == "verification_failed":
            integrity.append(f"{spec.name}: training verification failed")
        elif st != "verified":
            pending.append(f"{spec.name}: training not finished ({st})")
    c = census(state, include_extension=include_extension)
    if not c["complete"]:
        pending.append(f"census incomplete: {len(c['missing'])} labels ({c['missing'][:2]})")
    names = {s.name for s in specs}
    for spec in specs:
        for plan in hm.evaluation_plan(spec, hm.load_run(spec)):
            ev = (state.get("evaluations") or {}).get(f"{spec.name}:{plan['label']}") or {}
            if "tick0_ok" not in ev:
                pending.append(f"{spec.name}:{plan['label']}: evaluation not verified")
            elif not ev["tick0_ok"] or not ev.get("ok", False):
                integrity.append(f"{spec.name}:{plan['label']}: evaluation verification failed (tick-0 {ev['tick0_ok']})")
    inputs: Dict[str, Any] = {"C": {}, "F": {}, "g": {}, "integrity": integrity}
    per_seed: Dict[str, Any] = {}
    for s in sorted({x.seed for x in specs}):
        f = next((x for x in specs if x.seed == s and x.arm == "F"), None)
        cspec = next((x for x in specs if x.seed == s and x.arm == "C"), None)
        if cspec is None:                                  # the historical control (seeds 0-2)
            h = hm.HistoricalControl(s)
            c_dir, c_clears = h.eval_dir / "final", h.clears_dir
            t0 = mv.verify_eval_tick0(c_dir)             # tick-0 by construction; checked all the same
            integrity += [f"C s{s} (historical): {x}" for x in t0["problems"]]
        else:
            c_dir, c_clears = cspec.eval_dir / "final", cspec.clears_dir
        for arm, label_dir, clears in (("C", c_dir, c_clears), ("F", f.eval_dir / "final" if f else None,
                                                                 f.clears_dir if f else None)):
            if label_dir is None or not (label_dir / "stochastic" / "evaluation.json").is_file():
                continue                                   # pending already recorded by the census
            doc = _clear_doc(clears)
            inputs[arm][s], probs = ma.rule_inputs(label_dir, doc)
            for x in probs:
                (pending if doc is None and "clear verification" in x else integrity).append(f"{arm} s{s}: {x}")
        if f is not None:
            ent = (state.get("entries") or {}).get(f.name)
            if ent is None:
                pending.append(f"{f.name}: the genuine-entry verification has not run")
            inputs["g"][s] = int((ent or {}).get("g") or 0)
            per_seed[str(s)] = {"C": inputs["C"][s].to_json() if s in inputs["C"] else None,
                                "F": inputs["F"][s].to_json() if s in inputs["F"] else None, "g": inputs["g"][s],
                                "training_F": training_diagnostics(f) if f.run_dir.is_dir() else None}
    return {"inputs": inputs, "per_seed": per_seed, "census": {k: c[k] for k in ("plan", "executed_episodes", "missing",
                                                                                 "complete")},
            "control": control, "integrity": integrity, "pending": pending, "runs": sorted(names)}


def cmd_analyze(args: argparse.Namespace) -> int:  # noqa: ARG001
    state = load_state()
    manifest, am = post_training_gate(state)
    if manifest is None:
        return EXIT_FAILED
    rule = ma.load_rule()
    if rule["_sha256"] != (manifest.get("decision_rule") or {}).get("sha256"):
        log("BLOCKED the decision rule differs from the registered one in the manifest")
        return EXIT_FAILED
    n3 = (state.get("decisions") or {}).get("n3")
    ext = bool(n3 and n3.get("extension_required"))
    key = "n5" if ext else "n3"
    if key in (state.get("decisions") or {}):
        log(f"the {key} decision is already recorded (gate {state['decisions'][key]['gate']}); it is never re-decided")
        return EXIT_USAGE
    rep = build_report(state, manifest, include_extension=ext)
    if rep["pending"]:
        log(f"not ready to decide at {key} (nothing recorded): {len(rep['pending'])} pending, first {rep['pending'][:3]}")
        return EXIT_FAILED
    d = (ma.decide_n5 if ext else ma.decide_n3)(rep["inputs"], rule)
    out = hm.state_dir() / f"analysis_{key}.json"
    hm.write_json(out, {"decision": d, "per_seed": rep["per_seed"], "census": rep["census"], "control": rep["control"],
                        "amendments": [am] if am else [], "utc": utc_now()})
    state.setdefault("decisions", {})[key] = {"gate": d["gate"], "branch": d["branch"], "response": d["response"],
                                              "extension_required": d["extension_required"] and key == "n3",
                                              "notes": d["notes"], "utc": utc_now(), "report": ec.repo_relative(out),
                                              "amendments": [am["amendment"]] if am else []}
    save_state(state)
    log(f"decision at {key}: gate {d['gate']} ({d['branch']}): {d['response']}")
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:  # noqa: ARG001
    state = load_state()
    log(f"control: {control_mode(state)}; check {(state.get('control') or {}).get('check')}")
    for spec in hm.matrix(control=control_mode(state), include_extension=True):
        log(f"{spec.order_index} {spec.name}: {run_status(spec, state)}")
    log(f"decisions: {state.get('decisions')}")
    return EXIT_OK


# -- readiness: the prefix-row identification proof ---------------------------------------------------------------------


def cmd_prove_rows(args: argparse.Namespace) -> int:
    """Every prefix-row view of every recorded curriculum episode of the gate (E4, E5, the E7 and stopped partial runs,
    the E3 failure artifact) agrees with the one rule mc.prefix_rows; then N episodes are replayed from tick 0 in fresh
    processes: the observation after row L-1 equals the delivered o_L and the left-region facts on each side of L equal
    the worker's."""
    from m7_runtime import install_kill_on_close_job

    out = Path(args.out) if args.out else READINESS / "prove_rows"
    if out.exists():
        raise SystemExit(f"{out} exists (never overwritten)")
    runs = {"e4": (GATE_TREE / "e4" / "m7h_e4_on_s0", True), "e5a": (GATE_TREE / "e5" / "m7h_e5a", True),
            "e5b": (GATE_TREE / "e5" / "m7h_e5b", True)}
    for d in sorted((GATE_TREE / "_partial").iterdir()) if (GATE_TREE / "_partial").is_dir() else []:
        if d.is_dir() and (d / "run.json").is_file():
            runs[d.name] = (d, False)
    res: Dict[str, Any] = {"runs": {}, "e3": {}, "replays": [], "utc": utc_now()}
    ok = True
    for name, (d, complete) in runs.items():
        rid = hm.read_json(d / "run.json")["run_id"]
        v = mv.verify_curriculum_run(d, run_id=rid, complete=complete)
        res["runs"][name] = {k: v[k] for k in ("ok", "problems", "counts", "violations")}
        ok &= v["ok"]
    recs = [mv.boundary_record(a, m) for a, m in mv.artifacts_of(GATE_TREE / "e3")]
    res["e3"] = {"artifacts": len(recs), "kinds": sorted({(r["kind"], r["status"]) for r in recs}),
                 "problems": [r for r in recs if r["problems"]]}
    ok &= not res["e3"]["problems"]
    # replays: curriculum starts stratified by L, tick-0 starts, and in-flight (aborted) curriculum episodes
    if args.replays:
        install_kill_on_close_job()
        src = GATE_TREE / "e4" / "m7h_e4_on_s0"
        rows = {r["episode_id"]: r for r in mv.jsonl(src / "metrics" / "episodes.jsonl")}
        arts = mv.artifacts_of(src)
        pref = sorted([(a, m) for a, m in arts if ((m.get("labels") or {}).get(mc.START_LABEL) or {}).get("kind")
                       == mc.START_PREFIX], key=lambda am: am[1]["labels"][mc.START_LABEL]["prefix_length"])
        tick0 = [(a, m) for a, m in arts if mc.START_LABEL not in (m.get("labels") or {})]
        n_pref = max(1, args.replays - 4)
        pick = [pref[round(i * (len(pref) - 1) / max(1, n_pref - 1))] for i in range(min(n_pref, len(pref)))]
        pick += tick0[:2]
        coop = next((d for n, (d, _c) in runs.items() if "cooperative" in n), None)
        if coop is not None:
            pick += [(a, m) for a, m in mv.artifacts_of(coop) if m.get("status") == "aborted"
                     and (m.get("labels") or {}).get(mc.START_LABEL)][:2]
        exe = hm.REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
        for k, (a, meta) in enumerate(pick):
            acts = [(r["buttons"], r["stick_x"], r["stick_y"], r["consumed_tick"]) for r in mv.artifact_rows(a)]
            b = mv.boundary_record(a, meta)
            st = (meta.get("labels") or {}).get(mc.START_LABEL) or {}
            r = (REPLAY_FN or mv.replay_boundary)(acts, L=b["L"], work=out / f"replay_{k:02d}", executable=exe,
                                                 extra_env=dict(hm.M6_FLAGS, **hm.EVAL_METRICS_FLAG), index=9800 + k,
                                                 expected_digest=(meta.get("labels") or {}).get("native_action_digest"),
                                                 boundary_observation=st.get("prefix_end_observation"),
                                                 final_observation=meta.get("final_observation"))
            row = (rows.get(meta.get("episode_id")) or {}).get("m7h") or {}
            if row:
                if r["prefix_left_steps"] != int(row.get("prefix_left_steps") or 0) or \
                        r["first_policy_left_step"] != row.get("first_policy_left_step"):
                    r["problems"].append(f"left facts {r['prefix_left_steps']}/{r['first_policy_left_step']} != worker "
                                         f"{row.get('prefix_left_steps')}/{row.get('first_policy_left_step')}")
                    r["ok"] = False
            res["replays"].append({"episode_id": meta.get("episode_id"), "status": meta.get("status"), "kind": b["kind"],
                                   "L": b["L"], "rows": b["rows"], **r})
            ok &= r["ok"]
    res["ok"] = bool(ok)
    hm.write_json(out / "prove_rows.json", res)
    log(f"prove-rows: {'PASS' if ok else 'FAIL'}; runs {sum(v['ok'] for v in res['runs'].values())}/{len(res['runs'])}, "
        f"replays {sum(1 for r in res['replays'] if r['ok'])}/{len(res['replays'])} -> {ec.repo_relative(out)}")
    return EXIT_OK if ok else EXIT_FAILED


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
        t.add_argument("--extension", action="store_true")
        t.add_argument("--only", default=None, help="must be the next run in the registered order")
        t.add_argument("--restart-partial", default=None)
        t.add_argument("--resume", default=None, help="always refused (a curriculum run is never resumed)")
        t.add_argument("--retrain-control", action="store_true",
                       help="record the user decision to retrain arm C (only after a failed control check)")
        t.add_argument("--skip-resource-gate", action="store_true", help="tests / dry runs only")
    e = sub.add_parser("evaluate")
    e.add_argument("--dry-run", action="store_true")
    e.add_argument("--only", default=None)
    e.add_argument("--labels", default=None)
    for name in ("verify-clears", "verify-entries"):
        v = sub.add_parser(name)
        v.add_argument("--only", default=None)
    cs = sub.add_parser("census")
    cs.add_argument("--extension", action="store_true")
    sub.add_parser("analyze")
    sub.add_parser("status")
    pr = sub.add_parser("prove-rows")
    pr.add_argument("--replays", type=int, default=12)
    pr.add_argument("--out", default=None)
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "preflight":
        args.dry_run = True
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _raise_keyboard_interrupt)
    fn = {"manifest": cmd_manifest, "control-check": cmd_control_check, "train": cmd_train, "preflight": cmd_train,
          "evaluate": cmd_evaluate, "verify-clears": cmd_verify_clears, "verify-entries": cmd_verify_entries,
          "census": cmd_census, "analyze": cmd_analyze, "status": cmd_status, "prove-rows": cmd_prove_rows}[args.command]
    try:
        return fn(args)
    except hm.MatrixError as exc:
        log(f"ERROR {exc}")
        return EXIT_FAILED
    except KeyboardInterrupt:
        log("interrupted")
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
