#!/usr/bin/env python3
"""M7r control-learning gate driver (design: docs/rl_temporal_control_design_2026-09-28.md, revision 3, section 5).

    python rl/m7r_gate.py status
    python rl/m7r_gate.py preflight                 # no game: profiles, unit suite, analysis self-test, backup, approval
    python rl/m7r_gate.py approval-template         # prints the approval record to review (never writes it)
    python rl/m7r_gate.py run                       # BLOCKED unless preflight passes, including an APPROVED record

`run` executes, in order, recording the measured wall time of every phase in runs/m7r/gate/_gate/state.json:
  P1 live d = 1 identity: the eight pinned Track 1 artifacts driven through the commit worker stack with d = 1
     options must reproduce their canonical native words exactly (27,521 ticks);
  P2 training: m7r_s{0,1,2}_{commit,tick} with rl/train_m7.py (307,200 native ticks each), each run verified (60
     rollouts of exactly 5,120 ticks and 100 gradient steps; C's sidecars pass the expansion check);
  P3 evaluation: per run, ckpt_000000000 20 stochastic; final 30 stochastic + 10 deterministic; tick-0 starts,
     seed 12345, gate traces + btt_eval_metrics_v1 on, every episode preserved;
  P4 verification: expansion check of every C evaluation episode; exact tick-0 replay of the first 2 final stochastic
     episodes per run (canonical words, digest, per-tick trace rows); discovery candidates (qualified crossing,
     left-target break, clear) replayed and verified;
  P5 analysis: rl/m7r_analysis.decide on the recorded measures (applied once).
Budget: training 1,843,200 + evaluation <= 1,296,000 native ticks; verification replays <= 142,721.
The native RNG is never inspected; the driver never commits, pushes or deletes evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m7r_analysis as ma  # noqa: E402
import m7r_commit as mc  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
RL = REPO_ROOT / "rl"
GATE_ROOT = REPO_ROOT / "runs" / "m7r" / "gate"
STATE_DIR = GATE_ROOT / "_gate"
EVAL_ROOT = GATE_ROOT / "_eval"
APPROVAL = REPO_ROOT / "docs" / "rl_commit_m7r_gate_approval.json"
BACKUP_ROOT = Path(r"D:\BattleShip_runs_backup\2026-09-28")
EXECUTABLE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
SEEDS = (0, 1, 2)
ARMS = ("commit", "tick")
TRAIN_TICKS = 307_200
ROLLOUT_TICKS = 5_120
GRADIENT_STEPS = 100
EVAL_PLAN = {"untrained": {"checkpoint": "checkpoints/ckpt_000000000", "stochastic": 20, "deterministic": 0},
             "final": {"checkpoint": "final", "stochastic": 30, "deterministic": 10}}
REPLAYS_PER_RUN = 2
DISCOVERY_REPLAYS_MAX = 20   # clears + candidates over all seeds (design section 5: at most 20 = 72,000 ticks)
TICK_BUDGET = {"training": 6 * TRAIN_TICKS, "evaluation_max": 6 * 60 * 3600,
               "identity_check": 27_521, "replays_max": 6 * REPLAYS_PER_RUN * 3600 + DISCOVERY_REPLAYS_MAX * 3600}
PINNED = RL.parent / "runs" / "m7q" / "_equiv" / "input_all"


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def profile(seed: int, arm: str) -> Path:
    return RL / "configs" / "m7r" / f"m7r_s{seed}_{arm}.toml"


def run_name(seed: int, arm: str) -> str:
    return f"m7r_s{seed}_{arm}"


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# -- identity of what an approval covers ---------------------------------------------------------------------------


def identity() -> Dict[str, Any]:
    files = sorted([*(RL / "configs" / "m7r").glob("*.toml"),
                    *(RL / f for f in ("m7r_commit.py", "m7r_worker.py", "m7r_ppo.py", "m7r_analysis.py",
                                       "m7r_gate.py", "m7r_tests.py", "m7_trainer.py", "m7_evaluation.py",
                                       "experiment_config.py", "m7q_obs.py"))])
    return {"rule": ma.RULE_ID, "action_contract": mc.CONTRACT, "action_contract_sha256": mc.contract_digest(),
            "executable_sha256": sha256_file(EXECUTABLE) if EXECUTABLE.is_file() else None,
            "code": {f.relative_to(REPO_ROOT).as_posix(): sha256_file(f) for f in files},
            "tick_budget": TICK_BUDGET, "eval_plan": EVAL_PLAN}


def approval_status() -> Tuple[bool, str]:
    if not APPROVAL.is_file():
        return False, f"no approval record at {APPROVAL.relative_to(REPO_ROOT)} (the gate is not authorised)"
    rec = json.loads(APPROVAL.read_text(encoding="utf-8"))
    if not str(rec.get("approval", "")).startswith("APPROVED"):
        return False, f"approval record says {rec.get('approval')!r}"
    want = identity()
    diffs = [k for k in ("rule", "action_contract_sha256", "executable_sha256") if rec.get(k) != want[k]]
    diffs += [f"code:{f}" for f, h in want["code"].items() if (rec.get("code") or {}).get(f) != h]
    if diffs:
        return False, f"approval record does not match the current identity: {diffs[:8]}"
    return True, "approved"


# -- preflight -------------------------------------------------------------------------------------------------------


def backup_coverage() -> Dict[str, Any]:
    out = subprocess.run([sys.executable, str(RL / "tools" / "runs_backup.py"), "check-coverage", "--dest",
                          str(BACKUP_ROOT)], capture_output=True, text=True, cwd=REPO_ROOT)
    try:
        doc = json.loads(out.stdout)
    except ValueError:
        doc = {"ok": False, "reason": (out.stdout + out.stderr)[-500:]}
    return doc


def game_processes() -> List[int]:
    from m7_runtime import BATTLESHIP_IMAGE, list_processes_named

    return list(list_processes_named(BATTLESHIP_IMAGE))


def preflight(*, run_unit: bool = True) -> Dict[str, Any]:
    import experiment_config as ec

    problems: List[str] = []
    rep: Dict[str, Any] = {"utc": utc()}
    for s in SEEDS:
        for arm in ARMS:
            try:
                exp = ec.load_experiment(profile(s, arm))
                if exp.values["run.total_transitions"] != TRAIN_TICKS:
                    problems.append(f"{profile(s, arm).name}: total_transitions {exp.values['run.total_transitions']}")
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{profile(s, arm).name}: {exc}")
    existing = [run_name(s, a) for s in SEEDS for a in ARMS if (GATE_ROOT / run_name(s, a)).exists()]
    if existing:
        problems.append(f"gate run directories already exist (never overwritten): {existing}")
    if run_unit:
        r = subprocess.run([sys.executable, str(RL / "m7r_tests.py"), "unit"], capture_output=True, text=True,
                           cwd=REPO_ROOT)
        rep["unit_suite"] = r.stdout.strip().splitlines()[-1:] if r.stdout else [r.stderr[-300:]]
        if r.returncode != 0:
            problems.append("m7r unit suite failed")
        r = subprocess.run([sys.executable, str(RL / "m7r_analysis.py"), "self-test"], capture_output=True, text=True,
                           cwd=REPO_ROOT)
        rep["analysis_self_test"] = r.stdout.strip().splitlines()[-1:]
        if r.returncode != 0:
            problems.append("analysis self-test failed")
    cov = backup_coverage()
    rep["backup"] = {k: cov.get(k) for k in ("ok", "reason", "record", "source_files", "uncovered")}
    if not cov.get("ok"):
        problems.append(f"backup prerequisite not met: {cov.get('reason')}")
    procs = game_processes()
    if procs:
        problems.append(f"BattleShip already running: {procs}")
    if not EXECUTABLE.is_file():
        problems.append(f"missing executable {EXECUTABLE}")
    ok, why = approval_status()
    rep["approval"] = why
    if not ok:
        problems.append(why)
    rep["problems"] = problems
    rep["ok"] = not problems
    return rep


# -- P1 live d = 1 identity ------------------------------------------------------------------------------------------


def identity_check(work: Path) -> Dict[str, Any]:
    """The eight pinned Track 1 artifacts through the commit worker stack with d = 1 options (game processes)."""
    import m7f_trace as mt
    import m7q_obs as mq
    from btt_parallel import RunCoordinator, WorkerSpec, initial_coordination_state
    from btt_rewards import REWARD_V2
    from m7_runtime import prepare_worker_runtime
    from run_artifacts import read_artifact

    import m7r_worker as mrw

    results = []
    flags = (("SSB64_RL_NO_RENDER", "1"), ("SSB64_RAPHNET_DISABLE", "1")) + tuple(mq.ENTITY_EXTRA_ENV)
    for k, p in enumerate(sorted(PINNED.glob("fx_*.json.gz"))):
        tr = mt.read_trace(p)
        pinned_dir = REPO_ROOT / tr["artifact"]
        pinned = [(a.consumed_tick, a.buttons, a.stick_x, a.stick_y) for a in read_artifact(pinned_dir).actions]
        wdir = work / f"w{k:02d}"
        prepare_worker_runtime(wdir / "runtime", EXECUTABLE)
        coord = wdir / "coordination"
        RunCoordinator.create(coord, initial_coordination_state("m7r_identity", "test", None))
        spec = WorkerSpec(rank=k % 5, run_id="m7r_identity", role="test", worker_dir=str(wdir),
                          coordination_dir=str(coord), executable=str(EXECUTABLE), extra_env=flags,
                          reward_contract=REWARD_V2, preserve_all=True)
        env = mrw.build_worker_env_m7r(spec, commit=True, gate_trace=False)
        track1 = {tuple(int(v) for v in mc.native_word((s, b))): (s, b) for s in range(9) for b in range(8)}
        t0 = time.perf_counter()
        try:
            env.reset()
            for _t, b, sx, sy in pinned:
                s_, b_ = track1[(b, sx, sy)]
                _o, _r, term, trunc, _i = env.step([s_, b_, 0, 0])
                if term or trunc:
                    break
        finally:
            env.close()
        written = sorted((wdir / "artifacts").iterdir())
        new = [(a.consumed_tick, a.buttons, a.stick_x, a.stick_y) for a in read_artifact(written[-1]).actions]
        results.append({"artifact": tr["artifact"], "ticks": len(pinned), "identical": new == pinned,
                        "wall_s": round(time.perf_counter() - t0, 2)})
    return {"ok": all(r["identical"] for r in results), "artifacts": results}


# -- P2 training ------------------------------------------------------------------------------------------------------


def train_one(seed: int, arm: str) -> Dict[str, Any]:
    t0 = time.perf_counter()
    r = subprocess.run([sys.executable, str(RL / "train_m7.py"), "--config", str(profile(seed, arm))], cwd=REPO_ROOT)
    wall = time.perf_counter() - t0
    return {"run": run_name(seed, arm), "exit": r.returncode, "wall_s": round(wall, 1),
            "verification": verify_training(seed, arm)}


def verify_training(seed: int, arm: str) -> Dict[str, Any]:
    root = GATE_ROOT / run_name(seed, arm)
    problems: List[str] = []
    summary = json.loads((root / "training_summary.json").read_text(encoding="utf-8")) \
        if (root / "training_summary.json").is_file() else {}
    if summary.get("status") != "completed":
        problems.append(f"training status {summary.get('status')!r}")
    rows = [json.loads(line) for line in (root / "metrics" / "rollouts.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()] if (root / "metrics" / "rollouts.jsonl").is_file() else []
    if len(rows) != TRAIN_TICKS // ROLLOUT_TICKS:
        problems.append(f"{len(rows)} rollout rows, expected {TRAIN_TICKS // ROLLOUT_TICKS}")
    accounting = []
    for k, row in enumerate(rows):
        if row.get("num_timesteps") != (k + 1) * ROLLOUT_TICKS:
            problems.append(f"rollout {k + 1}: num_timesteps {row.get('num_timesteps')}")
        if arm == "commit":
            a = row.get("commit_accounting") or {}
            if a.get("native_ticks") != ROLLOUT_TICKS or a.get("gradient_steps") != GRADIENT_STEPS:
                problems.append(f"rollout {k + 1}: accounting {a.get('native_ticks')} ticks / {a.get('gradient_steps')} steps")
            accounting.append({k2: a.get(k2) for k2 in ("decisions", "tau_mean", "idle_replies", "gradient_steps",
                                                         "optimizer_samples", "end_reasons", "d_usage", "mode_usage")})
        else:
            n_up = (row.get("train_metrics") or {}).get("train/n_updates")
            if n_up is not None and int(n_up) != (k + 1) * 10:
                problems.append(f"rollout {k + 1}: n_updates {n_up} (10 epochs x 10 minibatches expected)")
            accounting.append({"decisions": ROLLOUT_TICKS, "tau_mean": 1.0, "idle_replies": 0,
                               "gradient_steps": GRADIENT_STEPS, "optimizer_samples": ROLLOUT_TICKS * 10})
    sidecars = expansion_checks(root / "workers", allow_rollout_cut=True) if arm == "commit" else None
    if sidecars and sidecars["problems"]:
        problems.append(f"training sidecars: {sidecars['problems'][:3]}")
    return {"ok": not problems, "problems": problems, "accounting": accounting, "sidecars": sidecars}


def expansion_checks(root: Path, *, allow_rollout_cut: bool) -> Dict[str, Any]:
    from run_artifacts import read_artifact

    checked, problems = 0, []
    for side in sorted(root.rglob(mc.SIDECAR_FILE)):
        art = read_artifact(side.parent)
        rows = [(a.consumed_tick, a.buttons, a.stick_x, a.stick_y) for a in art.actions]
        p = mc.check_expansion(mc.read_sidecar(side), rows, allow_rollout_cut=allow_rollout_cut)
        checked += 1
        problems += [f"{side.parent.name}: {x}" for x in p[:3]]
    return {"checked": checked, "problems": problems}


# -- P3 evaluation ------------------------------------------------------------------------------------------------------


def evaluate_run(seed: int, arm: str) -> Dict[str, Any]:
    from dataclasses import replace

    import experiment_config as ec
    from m7_evaluation import EvaluationSettings, evaluate_checkpoint
    from m7_trainer import config_from_experiment, run_contracts

    cfg = config_from_experiment(ec.load_experiment(profile(seed, arm)))
    settings = EvaluationSettings(executable=str(EXECUTABLE), horizon=cfg.horizon, n_workers=cfg.n_envs, seed=12345,
                                  extra_env=tuple(cfg.extra_env), reward=cfg.reward, standby_preboot=cfg.standby_preboot,
                                  standby_count=cfg.standby_count, standby_wait_timeout=cfg.standby_wait_timeout,
                                  observation=cfg.observation, eval_metrics=True, gate_trace=True,
                                  port_block_base=cfg.port_block_base, port_block_size=cfg.port_block_size)
    out = {}
    for label, plan in EVAL_PLAN.items():
        t0 = time.perf_counter()
        res = evaluate_checkpoint(GATE_ROOT / run_name(seed, arm) / plan["checkpoint"],
                                  EVAL_ROOT / run_name(seed, arm) / label, settings=replace(settings),
                                  deterministic_episodes=plan["deterministic"], stochastic_episodes=plan["stochastic"],
                                  expected_contracts=run_contracts(cfg), label=f"{run_name(seed, arm)}_{label}",
                                  preserve_all=True)
        out[label] = {"wall_s": round(time.perf_counter() - t0, 1),
                      "episodes": {m: len(r["episodes"]) for m, r in res["modes"].items()}}
    return out


def episode_rows(seed: int, arm: str, label: str, mode: str) -> List[Dict[str, Any]]:
    f = EVAL_ROOT / run_name(seed, arm) / label / mode / "evaluation.json"
    return list(json.loads(f.read_text(encoding="utf-8")).get("episodes") or []) if f.is_file() else []


def measures_of(seed: int, arm: str, label: str) -> Tuple[Dict[str, List[Any]], List[str]]:
    import m7r_worker as mrw

    vals: Dict[str, List[Any]] = {m: [] for m in ma.MEASURES}
    problems = []
    for e in episode_rows(seed, arm, label, "stochastic"):
        art = Path(e["artifact_dir"])
        art = art if art.is_absolute() else REPO_ROOT / art
        f = art / mrw.GATE_TRACE_FILE
        if not f.is_file():
            problems.append(f"{e.get('episode_id')}: no gate trace")
            continue
        doc = ma.read_trace(f)
        m = ma.episode_measures(doc["rows"], doc["classes"])
        if m["T"] != int(e.get("targets_broken", -1)):
            problems.append(f"{e.get('episode_id')}: trace T {m['T']} != recorded {e.get('targets_broken')}")
        for k in ma.MEASURES:
            vals[k].append(m[k])
    return vals, problems


# -- P4 verification ---------------------------------------------------------------------------------------------------


def replay_check(seed: int, arm: str, work: Path) -> Dict[str, Any]:
    import m7f_trace as mt
    import m7q_status_table as st2
    import m7r_worker as mrw

    import experiment_config as ec
    from m7_trainer import config_from_experiment

    cfg = config_from_experiment(ec.load_experiment(profile(seed, arm)))
    flags = dict(cfg.extra_env)
    from m7g_eval_metrics import DIAG_ENV

    flags[DIAG_ENV] = "1"
    classifier = st2.ActionClassifier(st2.load_table(), "mario")
    out = []
    for k, e in enumerate(episode_rows(seed, arm, "final", "stochastic")[:REPLAYS_PER_RUN]):
        art = Path(e["artifact_dir"])
        art = art if art.is_absolute() else REPO_ROOT / art
        acts, _meta = mt.artifact_actions(art)
        tr = mt.run_stepping_trace(f"m7r_replay_{seed}_{arm}_{k}", EXECUTABLE, acts, work / f"{run_name(seed, arm)}_{k}",
                                   extra_env=flags, index=9700 + 10 * seed + k)
        rows = [mrw.trace_row(-1, None, tr["initial"], classifier)]
        for (b, sx, sy, t), r in zip(acts, tr["steps"]):
            from types import SimpleNamespace

            rows.append(mrw.trace_row(t, SimpleNamespace(buttons=b, stick_x=sx, stick_y=sy), r, classifier))
        recorded = ma.read_trace(art / mrw.GATE_TRACE_FILE)["rows"]
        out.append({"episode_id": e.get("episode_id"), "digest_equal": tr.get("action_digest") == e.get("native_action_digest"),
                    "consumed_tick_mismatch": tr.get("consumed_tick_mismatch"), "unsent": tr.get("unsent"),
                    "trace_rows_equal": rows == recorded})
    return {"ok": all(r["digest_equal"] and r["trace_rows_equal"] and r["consumed_tick_mismatch"] is None
                      for r in out), "replays": out}


def discovery(seed: int, work: Path, budget: Dict[str, int]) -> Dict[str, Any]:
    """Qualified crossings / left-target breaks (btt_qualified_crossing_v1) and clears in C's final label.
    `budget["left"]` is the shared count of discovery replays still allowed (DISCOVERY_REPLAYS_MAX over all seeds);
    clears are replayed first; anything beyond the cap is recorded as not replayed (never counted as a discovery)."""
    import m7n_crossing as mx
    from m7g_k_run import verify_clears_in

    import m7q_obs as mq
    from m7g_eval_metrics import DIAG_ENV

    label_dir = EVAL_ROOT / run_name(seed, "commit") / "final"
    # the evaluation's own read-only diagnostics (v4 flags + the target diagnostic); gameplay is unaffected by them
    flags = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1", **dict(mq.ENTITY_EXTRA_ENV), DIAG_ENV: "1"}
    events, not_replayed = [], []
    n_clears = len({str(e.get("native_action_digest")) for mode in ("stochastic", "deterministic")
                    for e in episode_rows(seed, "commit", "final", mode) if e.get("cleared")})
    if n_clears <= budget["left"]:
        clears = verify_clears_in(label_dir, work / f"clears_{seed}", executable=EXECUTABLE, extra_env=flags)
        budget["left"] -= len(clears["clears"])
        events += [{"seed": seed, "episode_id": c["episode_id"], "clear": True} for c in clears["clears"] if c["verified"]]
    else:
        clears = {"skipped_cap": n_clears}
        not_replayed.append(f"{n_clears} clears (replay cap)")
    for mode in ("stochastic", "deterministic"):
        for k, c in enumerate(mx.candidates(episode_rows(seed, "commit", "final", mode))):
            if budget["left"] <= 0:
                not_replayed.append(f"{mode}:{c['episode_id']} (replay cap)")
                continue
            budget["left"] -= 1
            rec = mx.replay_candidate(c, work / f"cand_{seed}_{mode}_{k:02d}", executable=EXECUTABLE, extra_env=flags,
                                      index=9800 + 20 * seed + k)
            if rec["qualified_crossing"] or rec["verified_left_target_break"]:
                events.append({"seed": seed, "mode": mode, "episode_id": rec["episode_id"],
                               "qualified_crossing": rec["qualified_crossing"],
                               "left_target_break": rec["verified_left_target_break"]})
    return {"events": events, "clears": clears, "not_replayed": not_replayed}


# -- run -----------------------------------------------------------------------------------------------------------------


def cmd_run() -> int:
    from m7_runtime import install_kill_on_close_job

    pf = preflight()
    if not pf["ok"]:
        print(json.dumps(pf, indent=1))
        print("refused: preflight problems (see above); nothing was launched")
        return 2
    install_kill_on_close_job()
    state: Dict[str, Any] = {"started_utc": utc(), "identity": identity(), "preflight": pf, "phases": {}}
    write_json(STATE_DIR / "state.json", state)
    t0 = time.perf_counter()
    state["phases"]["identity_check"] = identity_check(STATE_DIR / "identity")
    state["phases"]["identity_check"]["wall_s"] = round(time.perf_counter() - t0, 1)
    write_json(STATE_DIR / "state.json", state)
    if not state["phases"]["identity_check"]["ok"]:
        print("invalid: the live d = 1 identity check failed; stopping")
        return 3
    state["phases"]["training"] = {}
    for s in SEEDS:
        for arm in ARMS:
            r = train_one(s, arm)
            state["phases"]["training"][run_name(s, arm)] = r
            write_json(STATE_DIR / "state.json", state)
    state["phases"]["evaluation"] = {}
    for s in SEEDS:
        for arm in ARMS:
            state["phases"]["evaluation"][run_name(s, arm)] = evaluate_run(s, arm)
            write_json(STATE_DIR / "state.json", state)
    t1 = time.perf_counter()
    ver: Dict[str, Any] = {"expansion": {}, "replays": {}, "discovery": {}}
    budget = {"left": DISCOVERY_REPLAYS_MAX}
    for s in SEEDS:
        ver["expansion"][run_name(s, "commit")] = expansion_checks(EVAL_ROOT / run_name(s, "commit"),
                                                                    allow_rollout_cut=False)
        for arm in ARMS:
            ver["replays"][run_name(s, arm)] = replay_check(s, arm, STATE_DIR / "replays")
        ver["discovery"][str(s)] = discovery(s, STATE_DIR / "discovery", budget)
    ver["wall_s"] = round(time.perf_counter() - t1, 1)
    state["phases"]["verification"] = ver
    write_json(STATE_DIR / "state.json", state)
    print(json.dumps(analyse(state), indent=1)[:4000])
    return 0


def analyse(state: Mapping[str, Any]) -> Dict[str, Any]:
    problems: List[str] = []
    ph = state.get("phases") or {}
    for name, r in (ph.get("training") or {}).items():
        if r.get("exit") != 0 or not (r.get("verification") or {}).get("ok"):
            problems.append(f"{name}: training not verified {((r.get('verification') or {}).get('problems') or [])[:2]}")
    ver = ph.get("verification") or {}
    for name, r in (ver.get("expansion") or {}).items():
        problems += [f"{name}: {p}" for p in r.get("problems", [])[:3]]
    for name, r in (ver.get("replays") or {}).items():
        if not r.get("ok"):
            problems.append(f"{name}: replay not exact")
    seeds: Dict[str, Any] = {}
    for s in SEEDS:
        g = {}
        for key, (arm, label) in {"C_final": ("commit", "final"), "C_untrained": ("commit", "untrained"),
                                  "F_final": ("tick", "final")}.items():
            vals, p = measures_of(s, arm, label)
            problems += p
            g[key] = vals
        seeds[str(s)] = g
    events = [e for d in (ver.get("discovery") or {}).values() for e in d.get("events", [])]
    complete = bool(ph.get("training")) and len(ph.get("training")) == 6 and len(ph.get("evaluation") or {}) == 6
    decision = ma.decide({"integrity": {"ok": not problems, "problems": problems}, "complete": complete,
                          "discovery": {"C_final": events}, "seeds": seeds})
    decision["walls"] = {"training": {k: v.get("wall_s") for k, v in (ph.get("training") or {}).items()},
                         "evaluation": ph.get("evaluation"), "verification_s": ver.get("wall_s"),
                         "identity_check_s": (ph.get("identity_check") or {}).get("wall_s")}
    write_json(STATE_DIR / "analysis.json", decision)
    return decision


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("status", "preflight", "approval-template", "run"))
    ap.add_argument("--skip-unit", action="store_true", help="preflight only: do not run the unit suite")
    a = ap.parse_args(argv)
    if a.command == "approval-template":
        print(json.dumps(dict(identity(), approval="PENDING (replace with 'APPROVED: <text>' only after review)"),
                         indent=1))
        return 0
    if a.command == "preflight":
        rep = preflight(run_unit=not a.skip_unit)
        print(json.dumps(rep, indent=1))
        return 0 if rep["ok"] else 1
    if a.command == "status":
        st = STATE_DIR / "state.json"
        print(json.dumps({"state": json.loads(st.read_text(encoding="utf-8")) if st.is_file() else None,
                          "approval": approval_status()[1], "tick_budget": TICK_BUDGET}, indent=1)[:4000])
        return 0
    return cmd_run()


if __name__ == "__main__":
    sys.exit(main())
