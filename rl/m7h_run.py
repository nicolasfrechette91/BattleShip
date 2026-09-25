"""M7h review gate driver: the bounded engineering checks E1-E7 and the curriculum-off reproduction checks R1-R3.

    python rl/m7h_run.py gate                    # the registered launch gate (10 GiB commit / 4 GiB physical)
    python rl/m7h_run.py e1                      # unit tests (rl/m7h_tests.py), no game
    python rl/m7h_run.py r1 [--seeds 0,1,2]      # curriculum off, 102,400 transitions vs M7e ckpt_000102400
    python rl/m7h_run.py r2 [--seeds 0,1,2]      # re-evaluate the historical v1 finals, 600 episodes vs Phase K
    python rl/m7h_run.py r3                      # rule inputs recomputed from R2 vs the Phase K values
    python rl/m7h_run.py e4 | e5 | e2 | e3 | e6 | e7

Everything is written below runs/m7h/_gate (git-ignored); each check writes results/<check>.json. No run directory is
ever overwritten; a stopped run is moved to runs/m7h/_gate/_partial by the guard. This driver never starts the
three-seed curriculum campaign.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import experiment_config as ec  # noqa: E402
import m7d_run as dr  # noqa: E402
import m7h_curriculum as mc  # noqa: E402
import m7h_guard as g  # noqa: E402

REPO_ROOT = RL_DIR.parent
GATE = REPO_ROOT / "runs" / "m7h" / "_gate"
PROFILES = RL_DIR / "configs" / "m7h" / "gate"
RESULTS = GATE / "results"
EXE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
EXPECTED_EXE_SHA = "1e7c62a05a9397fb4ef1d404d85a793cd01c4dbdc187068e3a63890cb5cbeb97"
M7E_ROWS_AT_102400 = {0: 30, 1: 27, 2: 29}
ROW_KEYS = ("rank", "worker_episode", "end_reason", "steps", "targets_broken", "native_action_digest")
PHASE_K_T = {0: Fraction(472, 100), 1: Fraction(475, 100), 2: Fraction(427, 100)}
PHASE_K_FALLS = {0: 1, 1: 1, 2: 0}
EPS = 1e-4


def utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg: str) -> None:
    print(f"[m7h_run] {msg}", flush=True)


def write_result(name: str, data: Mapping[str, Any], results: Optional[Path] = None) -> Path:
    results = RESULTS if results is None else Path(results)
    results.mkdir(parents=True, exist_ok=True)
    p = results / f"{name}.json"
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, p)
    log(f"{name}: {'PASS' if data.get('ok') else 'FAIL'} -> {p.relative_to(REPO_ROOT)}")
    return p


def rows_of(run_dir: Path) -> List[Dict[str, Any]]:
    rows, _ = dr.jsonl_rows(run_dir / "metrics" / "episodes.jsonl")
    return rows


def read_json(p: Path) -> Any:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def artifacts_of(run_dir: Path) -> List[Tuple[Path, Dict[str, Any]]]:
    out = []
    for w in sorted((run_dir / "workers").iterdir()) if (run_dir / "workers").is_dir() else []:
        adir = w / "artifacts"
        if adir.is_dir():
            for a in sorted(adir.iterdir()):
                if (a / "metadata.json").is_file():
                    out.append((a, read_json(a / "metadata.json")))
    return out


def artifact_rows(a: Path) -> List[Dict[str, Any]]:
    return [json.loads(ln) for ln in (a / "actions.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]


def guarded(profile: Path, *, run_id: Optional[str] = None, drill: Optional[g.DrillOverride] = None,
            extra_env: Optional[Dict[str, str]] = None, base: Optional[Path] = None,
            output_root: Optional[Path] = None) -> Dict[str, Any]:
    """One guarded training run. `base` (default runs/m7h/_gate) holds logs, monitor, probe and _partial;
    `output_root` overrides the profile's run.output_root (the campaign's control check writes its own tree)."""
    base = GATE if base is None else Path(base)
    exp = ec.load_experiment(profile)
    name = run_id or exp.name
    run_dir = (exp.output_root if output_root is None else Path(output_root)) / name
    if run_dir.exists():
        raise RuntimeError(f"{run_dir} exists (never overwritten; move it aside first)")
    gate = g.launch_gate()
    if not gate["ok"]:
        raise RuntimeError(f"launch gate refused: {gate['problems']}")
    res = g.train_guarded(config=profile, run_dir=run_dir, run_id=run_id, log_path=base / "logs" / f"{name}.log",
                          monitor_path=base / "monitor" / f"{name}.jsonl", probe_path=base / "probe" / f"{name}.jsonl",
                          contract=exp.reward, horizon=int(exp.values["environment.horizon"]),
                          partial_root=base / "_partial", drill=drill, extra_env=extra_env,
                          output_root=None if output_root is None else Path(output_root))
    res["launch_gate"] = gate
    res["run_dir"] = str(run_dir)
    return res


def run_identity(run_dir: Path) -> Dict[str, Any]:
    rj = read_json(run_dir / "run.json")
    return {"executable_sha256": rj["executable"]["sha256"], "revisions": rj.get("revisions"),
            "executable_ok": rj["executable"]["sha256"] == EXPECTED_EXE_SHA}


# -- R1 ---------------------------------------------------------------------------------------------------------------


def _base(args: argparse.Namespace) -> Path:
    return Path(getattr(args, "base", None) or GATE)


def cmd_r1(args: argparse.Namespace) -> int:
    ok_all = True
    root = _base(args)
    for s in [int(v) for v in args.seeds.split(",")]:
        prof = PROFILES / f"m7h_r1_s{s}.toml"
        exp = ec.load_experiment(prof)
        base = ec.load_experiment(RL_DIR / "configs" / "m7g" / f"m7g_s{s}_v1.toml")
        run = guarded(prof, base=root, output_root=None if root == GATE else root / "r1")
        rd = Path(run["run_dir"])
        p: List[str] = []
        if exp.compatibility_view() != base.compatibility_view():
            p.append("compatibility view differs from Phase K m7g_s{s}_v1")
        summ = read_json(rd / "training_summary.json")
        if summ.get("status") != "completed" or not summ["cleanup"]["leak_free"]:
            p.append(f"status {summ.get('status')} leak_free {summ['cleanup']['leak_free']}")
        ours = dr.checkpoint_digests(rd / "final")
        ref = dr.checkpoint_digests(REPO_ROOT / "runs" / "m7e" / f"m7e_s{s}_v2" / "checkpoints" / "ckpt_000102400")
        if ours != ref:
            p.append(f"final digests {ours} != M7e ckpt_000102400 {ref}")
        rows = rows_of(rd)
        ref_rows = [r for r in rows_of(REPO_ROOT / "runs" / "m7e" / f"m7e_s{s}_v2")
                    if int(r.get("sb3_num_timesteps_seen") or 0) <= 102_400]
        a = [tuple(r.get(k) for k in ROW_KEYS) for r in rows]
        b = [tuple(r.get(k) for k in ROW_KEYS) for r in ref_rows]
        if len(a) != len(b) or len(a) != M7E_ROWS_AT_102400[s] or a != b:
            p.append(f"rows: ours {len(a)}, M7e {len(b)} (registered {M7E_ROWS_AT_102400[s]}), equal {a == b}")
        # (c) and (d): no curriculum component, record or file
        rj = read_json(rd / "run.json")
        offs = {
            "row_m7h_keys": sum(1 for r in rows if "m7h" in r),
            "run_json_config_curriculum": "curriculum" in (rj.get("config") or {}),
            "experiment_summary_curriculum": "curriculum" in ((rj.get("experiment") or {})),
            "compat_view_curriculum_keys": [k for k in (rj.get("compatibility_view") or {}) if k.startswith("curriculum")],
            "summary_curriculum_or_stop": [k for k in ("curriculum", "stop") if k in summ],
            "summary_m7h_worker_blocks": json.dumps(summ).count('"m7h":'),
            "curriculum_dir": (rd / "curriculum").exists(),
            "final_set_extra_or_interruption": [k for k in ("extra_files", "interruption")
                                                if k in read_json(rd / "final" / "checkpoint.json")],
            "artifacts_with_m7h_start": sum(1 for _a, m in artifacts_of(rd) if (m.get("labels") or {}).get("m7h_start")),
            "incomplete_dirs": [str(x) for x in list(rd.glob(".*.incomplete")) + list((rd / "checkpoints").glob(".*.incomplete"))],
        }
        bad = {k: v for k, v in offs.items() if v}
        if bad:
            p.append(f"curriculum traces on the control path: {bad}")
        ident = run_identity(rd)
        if not ident["executable_ok"]:
            p.append(f"executable {ident['executable_sha256']}")
        ok = not p
        ok_all &= ok
        write_result(f"r1_s{s}", {"check": "R1", "seed": s, "ok": ok, "problems": p, "final_digests": list(ours),
                                  "m7e_digests": list(ref), "rows_compared": len(a), "rows_registered": M7E_ROWS_AT_102400[s],
                                  "control_path": offs, "identity": ident, "run": run,
                                  "learn_s": (summ.get("wall") or {}).get("learn_s"),
                                  "throughput": summ.get("throughput")}, root / "results")
    return 0 if ok_all else 1


# -- R2 / R3 -----------------------------------------------------------------------------------------------------------


def cmd_r2(args: argparse.Namespace) -> int:
    import m7_evaluation as ev
    import m7_trainer as tr
    import m7g_k_matrix as km
    import m7g_k_run as kr
    from m7_runtime import install_kill_on_close_job, list_processes_named

    install_kill_on_close_job()
    ok_all = True
    root = _base(args)
    km.configure_root(None)
    for s in [int(v) for v in args.seeds.split(",")]:
        spec = next(x for x in km.matrix() if x.name == f"m7g_s{s}_v1")
        exp = km.load_run(spec)
        ckpt = REPO_ROOT / "runs" / "m7g_k" / f"m7g_s{s}_v1" / "final"
        ref_dir = REPO_ROOT / "runs" / "m7g_k" / "_eval" / f"m7g_s{s}_v1" / "final"
        out = root / "r2" / f"m7g_s{s}_v1_final"
        if out.exists():
            raise RuntimeError(f"{out} exists (never overwritten)")
        if list_processes_named():
            raise RuntimeError("BattleShip already running")
        cfg = tr.config_from_experiment(exp)
        t0 = time.perf_counter()
        ev.evaluate_checkpoint(ckpt, out, settings=kr.phase_k_settings(exp), deterministic_episodes=100,
                               stochastic_episodes=100, expected_contracts=tr.run_contracts(cfg), label="final",
                               preserve_all=True)
        wall = time.perf_counter() - t0
        p: List[str] = []
        compared = {}
        for mode in ("stochastic", "deterministic"):
            ours = {(e["rank"], e["worker_episode"]): e for e in read_json(out / mode / "evaluation.json")["episodes"]}
            ref = {(e["rank"], e["worker_episode"]): e for e in read_json(ref_dir / mode / "evaluation.json")["episodes"]}
            if set(ours) != set(ref) or len(ours) != 100:
                p.append(f"{mode}: keys differ ({len(ours)} vs {len(ref)})")
            diff = [k for k in ref if k in ours and any(ours[k].get(f) != ref[k].get(f) for f in
                    ("native_action_digest", "targets_broken", "end_reason", "eval_metrics"))]
            if diff:
                p.append(f"{mode}: {len(diff)} episodes differ, first {diff[:3]}")
            compared[mode] = {"episodes": len(ours), "equal": len(ours) - len(diff)}
        leftover = list_processes_named()
        if leftover:
            p.append(f"leftover BattleShip {leftover}")
        ok = not p
        ok_all &= ok
        write_result(f"r2_s{s}", {"check": "R2", "seed": s, "ok": ok, "problems": p, "compared": compared,
                                  "checkpoint": str(ckpt.relative_to(REPO_ROOT)), "out": ec.repo_relative(out),
                                  "wall_s": round(wall, 1)}, root / "results")
    return 0 if ok_all else 1


def rule_inputs(label_dir: Path) -> Dict[str, Any]:
    sto = read_json(label_dir / "stochastic" / "evaluation.json")["episodes"]
    det = read_json(label_dir / "deterministic" / "evaluation.json")["episodes"]
    clears = [e for e in sto + det if e.get("cleared")]
    non_clear = [e for e in sto if not e.get("cleared")]
    return {"k": int(bool(clears)), "native_clears": len(clears),
            "chi": int(any((e.get("eval_metrics") or {}).get("first_left_entry") for e in sto)),
            "T": Fraction(sum(int(e["targets_broken"]) for e in non_clear), len(non_clear)) if non_clear else None,
            "falls": sum(1 for e in sto if e.get("end_reason") == "fall")}


def cmd_r3(args: argparse.Namespace) -> int:
    p, per = [], {}
    root = _base(args)
    for s in (0, 1, 2):
        r = rule_inputs(root / "r2" / f"m7g_s{s}_v1_final")
        ph = rule_inputs(REPO_ROOT / "runs" / "m7g_k" / "_eval" / f"m7g_s{s}_v1" / "final")
        want = {"k": 0, "chi": 0, "T": PHASE_K_T[s], "falls": PHASE_K_FALLS[s]}
        got = {k: r[k] for k in want}
        if got != want or {k: ph[k] for k in want} != want:
            p.append(f"seed {s}: R2 {got}, Phase K recorded {({k: ph[k] for k in want})}, registered {want}")
        per[s] = {"r2": {k: str(v) for k, v in got.items()}, "registered": {k: str(v) for k, v in want.items()}}
    write_result("r3", {"check": "R3", "ok": not p, "problems": p, "per_seed": per}, root / "results")
    return 0 if not p else 1


# -- E4 ---------------------------------------------------------------------------------------------------------------


def cmd_e4(_args: argparse.Namespace) -> int:
    prof = PROFILES / "m7h_e4_on_s0.toml"
    exp = ec.load_experiment(prof)
    obs_log = GATE / "e4_observations.npy"
    if obs_log.exists():
        raise RuntimeError(f"{obs_log} exists")
    from m7h_vec import OBS_LOG_ENV

    run = guarded(prof, extra_env={OBS_LOG_ENV: str(obs_log)})
    if run.get("stop_kind"):
        write_result("e4", {"check": "E4", "ok": False, "problems": [f"the guard stopped the run: {run['stop_kind']}"],
                            "run": run})
        return 1
    return 0 if check_e4(Path(run["run_dir"]), obs_log, run) else 1


def check_e4(rd: Path, obs_log: Path, run: Mapping[str, Any]) -> bool:
    import numpy as np
    from stable_baselines3.common.running_mean_std import RunningMeanStd

    from m7_evaluation import read_checkpoint_set
    from m7h_vec import policy_observation_from_dict

    p: List[str] = []
    summ = read_json(rd / "training_summary.json")
    cur = summ.get("curriculum") or {}
    if summ.get("status") != "completed" or not summ["cleanup"]["leak_free"]:
        p.append(f"status {summ.get('status')}")
    rows = rows_of(rd)
    m = [r.get("m7h") or {} for r in rows]
    counts = {"rows": len(rows), "prefix_starts": sum(1 for x in m if x.get("start_kind") == mc.START_PREFIX),
              "tick0_starts": sum(1 for x in m if x.get("start_kind") == mc.START_TICK0)}
    # reset contract, rows, ticks, digests
    bad = {"missing_m7h": sum(1 for x in m if not x),
           "reset_contract": sum(1 for x in m if not (x.get("reset_contract") or {}).get("ok")),
           "first_row_not_tick0": sum(1 for x in m if x.get("rows") and x.get("first_row_consumed_tick") != 0),
           "consumed_ticks": sum(1 for x in m if not x.get("consumed_ticks_ok")),
           "digest_disagrees": sum(1 for x in m if not x.get("full_digest_agrees")),
           "rows_ne_prefix_plus_policy": sum(1 for r, x in zip(rows, m) if r["end_reason"] != "lifecycle_failure"
                                             and not x.get("rows_equal_prefix_plus_policy")),
           "over_horizon": sum(1 for x in m if (x.get("rows") or 0) > 3600),
           "horizon_not_3600": sum(1 for r, x in zip(rows, m) if r["end_reason"] == "horizon" and x.get("rows") != 3600)}
    # rewards: return = sum over policy steps only; prefix breaks unrewarded
    rew_bad, total_bad = 0, 0
    for r, x in zip(rows, m):
        want = -0.001 * int(x.get("policy_steps", 0)) + 1.0 * int(r["targets_broken"]) + \
            (10.0 if r.get("cleared") else 0.0) + (-5.0 if r["end_reason"] == "fall" else 0.0)
        if abs(float(r["return"]) - want) > 1e-6:
            rew_bad += 1
        if x.get("targets_broken_total") is not None and \
                x["targets_broken_total"] != int(x.get("prefix_targets_broken") or 0) + int(r["targets_broken"]):
            total_bad += 1
    bad.update(return_formula=rew_bad, total_ne_prefix_plus_policy=total_bad)
    # PPO transitions per episode = vector steps between automatic resets (prefix steps are never transitions)
    log_rows = [json.loads(ln) for ln in (rd / "curriculum" / "selection.jsonl").read_text(encoding="utf-8").splitlines()]
    by_id = {r["episode_id"]: r for r in rows}
    last = {}
    steps_bad = steps_checked = 0
    for ev in log_rows:
        if ev.get("event") in ("ingest", "no_report"):          # every episode end of that env
            prev = last.get(ev["env"], 0)
            row = by_id.get(ev.get("episode_id"))
            # a lifecycle-failure step is a PPO step the tracker never sees (no tick consumed): excluded
            if row is not None and row["end_reason"] != "lifecycle_failure":
                steps_checked += 1
                if int(row["m7h"]["policy_steps"]) != ev["vec_step"] - prev:
                    steps_bad += 1
            last[ev["env"]] = ev["vec_step"]
    bad["policy_steps_ne_vec_steps"] = steps_bad
    # 50/50: every selection draw after an automatic reset
    selects = [ev for ev in log_rows if ev.get("event") == "select"]
    u_below = sum(1 for ev in selects if ev["u1"] < 0.5)
    bad["select_outside_auto_reset"] = sum(1 for ev in selects if ev["vec_step"] == 0)
    # the observation log vs VecNormalize (each returned observation exactly once)
    batches = []
    with open(obs_log, "rb") as fp:
        while True:
            try:
                batches.append(np.load(fp, allow_pickle=False))
            except (EOFError, ValueError):
                break
    rms = RunningMeanStd(shape=(15,))
    for b in batches:
        rms.update(b)
    fin = rd / "final"
    import pickle
    with open(fin / "vecnormalize.pkl", "rb") as fh:
        vn = pickle.load(fh)
    meta = read_checkpoint_set(fin)
    obs_ok = (np.array_equal(rms.mean, vn.obs_rms.mean) and np.array_equal(rms.var, vn.obs_rms.var)
              and rms.count == vn.obs_rms.count and abs(vn.obs_rms.count - (EPS + 5 + meta["num_timesteps"])) < 1e-6)
    if not obs_ok:
        p.append(f"VecNormalize statistics differ from the returned observations (count {vn.obs_rms.count}, "
                 f"batches {len(batches)})")
    # delivered observation of every curriculum start = archived end observation, never the tick-0 observation
    arts = {m_["episode_id"]: (a, m_) for a, m_ in artifacts_of(rd)}
    delivered_checked = delivered_bad = 0
    starts_by_env: Dict[int, List[Dict[str, Any]]] = {}
    for ev in log_rows:
        if ev.get("event") in ("delivered", "ingest"):
            starts_by_env.setdefault(ev["env"], []).append(ev)
    for env, evs in starts_by_env.items():
        for k, ev in enumerate(evs):
            if ev["event"] != "delivered" or ev["kind"] != mc.START_PREFIX:
                continue
            nxt = next((e for e in evs[k + 1:] if e["event"] == "ingest"), None)
            if nxt is None or nxt["episode_id"] not in arts:
                continue
            _a, meta_a = arts[nxt["episode_id"]]
            start = (meta_a.get("labels") or {}).get("m7h_start") or {}
            row_obs = batches[ev["vec_step"]][env]
            end_p = policy_observation_from_dict(start["prefix_end_observation"])
            tick0_p = policy_observation_from_dict(start["tick0_observation"])
            delivered_checked += 1
            if not np.array_equal(row_obs, end_p) or np.array_equal(row_obs, tick0_p):
                delivered_bad += 1
    bad["delivered_ne_archived_end"] = delivered_bad
    # artifacts: tick-0 initial observation, contiguous consumed ticks, prefix boundary, digests
    art_bad = {"initial_not_tick0": 0, "ticks_not_contiguous": 0, "prefix_digest": 0, "full_digest": 0}
    art_prefix = 0
    for a, meta_a in artifacts_of(rd):
        acts = artifact_rows(a)
        if (meta_a.get("initial_observation") or {}).get("input_tick") != 0:
            art_bad["initial_not_tick0"] += 1
        if [x["consumed_tick"] for x in acts] != list(range(len(acts))):
            art_bad["ticks_not_contiguous"] += 1
        lab = meta_a.get("labels") or {}
        if mc.native_digest((x["buttons"], x["stick_x"], x["stick_y"], x["consumed_tick"]) for x in acts) != \
                lab.get("native_action_digest"):
            art_bad["full_digest"] += 1
        st = lab.get("m7h_start")
        if st and st.get("kind") == mc.START_PREFIX:
            art_prefix += 1
            L = int(st["prefix_length"])
            if mc.native_digest((x["buttons"], x["stick_x"], x["stick_y"], x["consumed_tick"]) for x in acts[:L]) != \
                    st["prefix_digest"]:
                art_bad["prefix_digest"] += 1
    bad.update({f"artifact_{k}": v for k, v in art_bad.items()})
    stat_bad = {"invariant_checks_zero": cur.get("invariant_checks", 0) == 0,
                "delivered_count_ne_dispatches": cur.get("delivered_equals_archived_end") != cur.get("prefix_dispatches"),
                "lifecycle_failures": cur.get("lifecycle_failures", 0) > 0}
    p += [f"{k}: {v}" for k, v in bad.items() if v]
    p += [k for k, v in stat_bad.items() if v]
    if counts["prefix_starts"] < 5:
        p.append(f"too few curriculum starts to exercise the path: {counts}")
    # the inherited training verification (row invariants, artifacts 0..n-1 from a tick-0 observation, sets, lifecycle)
    ver = dr.verify_training_run(rd, ec.load_experiment(PROFILES / "m7h_e4_on_s0.toml"))
    if ver["problems"]:
        p.append(f"verify_training_run: {ver['problems'][:3]}")
    ok = not p
    write_result("e4", {"check": "E4", "ok": ok, "problems": p, "counts": counts, "violations": bad,
                        "verify_training_run": {"problems": ver["problems"],
                                                "artifacts": {k: v for k, v in (ver["checks"].get("artifacts") or {}).items()
                                                              if k != "problems"},
                                                "episodes": ver["checks"].get("episodes")},
                        "selection": {"draws": len(selects), "u1_below_half": u_below,
                                      "share_tick0": round(u_below / max(1, len(selects)), 4)},
                        "policy_steps_checked": steps_checked, "delivered_checked": delivered_checked,
                        "artifacts": {"total": len(arts), "curriculum": art_prefix},
                        "observation_log": {"batches": len(batches), "rows": sum(len(b) for b in batches),
                                            "obs_rms_count": float(vn.obs_rms.count), "exact": obs_ok},
                        "curriculum": cur, "run": run, "identity": run_identity(rd)})
    return ok


# -- E5 ---------------------------------------------------------------------------------------------------------------


def _deterministic_rows(rd: Path) -> List[Dict[str, Any]]:
    keep = ROW_KEYS + ("return", "cleared", "target_break_ticks", "last_consumed_tick")
    out = []
    for r in rows_of(rd):
        x = {k: r.get(k) for k in keep}
        m7h = dict(r.get("m7h") or {})
        for k in ("prefix_wall_s", "source_episode_id"):
            m7h.pop(k, None)
        x["m7h"] = m7h
        out.append(x)
    return out


IDENTITY_KEYS = ("episode_id", "source_episode_id", "run_id")   # unique by construction (uuid ids, run names)


def _archive_view(rd: Path, label: str) -> Dict[str, Any]:
    """The archive without identity (episode ids are timestamp + uuid4; run names differ by construction) and without
    the wall-clock statistics; everything behavioural (cells, prefixes, digests, visits, selections, eligibility,
    lineage, end observations, the selector state) is kept."""
    d = read_json(rd / label / "curriculum_archive.json")
    for e in d["entries"]:
        e["source"] = {k: v for k, v in e["source"].items() if k not in IDENTITY_KEYS}
    d.pop("stats", None)
    return {k: v for k, v in d.items() if k not in IDENTITY_KEYS}


def _log_view(path: Path) -> List[Dict[str, Any]]:
    from m7h_tests import strip_timing

    return [{k: v for k, v in r.items() if k not in IDENTITY_KEYS} for r in strip_timing(path)]


def cmd_e5(args: argparse.Namespace) -> int:
    prof = PROFILES / "m7h_e5_on_s0.toml"
    if args.compare_only:
        prev = read_json(RESULTS / "e5.json")
        runs = prev["runs"]
    else:
        runs = [guarded(prof, run_id=n) for n in ("m7h_e5a", "m7h_e5b")]
    a, b = (Path(r["run_dir"]) for r in runs)
    p: List[str] = []
    da, db = dr.checkpoint_digests(a / "final"), dr.checkpoint_digests(b / "final")
    if da != db:
        p.append(f"final digests differ {da} {db}")
    if _deterministic_rows(a) != _deterministic_rows(b):
        p.append("episode rows differ")
    if _archive_view(a, "final") != _archive_view(b, "final"):
        p.append("archives differ")
    if _log_view(a / "curriculum" / "selection.jsonl") != _log_view(b / "curriculum" / "selection.jsonl"):
        p.append("selection logs differ")
    if (a / "final" / "curriculum_prefixes.bin").read_bytes() != (b / "final" / "curriculum_prefixes.bin").read_bytes():
        p.append("archived prefix bytes differ")
    e4 = GATE / "e4" / "m7h_e4_on_s0" / "checkpoints" / "ckpt_000051200"
    e4_eq = None
    if e4.is_dir():
        e4_eq = dr.checkpoint_digests(e4) == da
        if not e4_eq:
            p.append("E4 ckpt_000051200 differs from the E5 final (same seed and settings, longer budget)")
    ok = not p
    write_result("e5", {"check": "E5", "ok": ok, "problems": p, "final_digests": list(da), "rows": len(rows_of(a)),
                        "e4_ckpt_000051200_equal": e4_eq, "archive_cells": len(read_json(a / "final" /
                                                                                       "curriculum_archive.json")["entries"]),
                        "selection_log_rows": len(_log_view(a / "curriculum" / "selection.jsonl")),
                        "identity_fields_excluded": list(IDENTITY_KEYS) + ["dispatch_wall_s", "prefix_wall_s",
                                                                           "archive wall-clock stats"],
                        "runs": runs})
    return 0 if ok else 1


# -- E2 ---------------------------------------------------------------------------------------------------------------


def cmd_e2(_args: argparse.Namespace) -> int:
    import m7_evaluation as ev
    import m7_trainer as tr
    from m7_runtime import install_kill_on_close_job
    from m7h_tests import unit_isolation_guard

    install_kill_on_close_job()
    p: List[str] = []
    static = unit_isolation_guard()
    rd = GATE / "e4" / "m7h_e4_on_s0"
    d = read_json(rd / "final" / "curriculum_archive.json")
    archive = mc.Archive.from_json(d, (rd / "final" / "curriculum_prefixes.bin").read_bytes())
    rows = {r["episode_id"]: r for r in rows_of(rd)}
    arts = {m_["episode_id"]: a for a, m_ in artifacts_of(rd)}
    prov = {"entries": len(archive.entries), "other_run": 0, "source_not_a_row": 0, "full_digest_ne_row": 0,
            "prefix_digest_ne_artifact": 0, "artifact_checked": 0}
    for e in archive.entries.values():
        src = e.source
        if src.get("run_id") != "m7h_e4_on_s0":
            prov["other_run"] += 1
        row = rows.get(src.get("episode_id"))
        if row is None:
            prov["source_not_a_row"] += 1
            continue
        if row["native_action_digest"] != src.get("full_digest"):
            prov["full_digest_ne_row"] += 1
        a = arts.get(src.get("episode_id"))
        if a is not None:
            acts = artifact_rows(a)[:e.length]
            prov["artifact_checked"] += 1
            if mc.native_digest((x["buttons"], x["stick_x"], x["stick_y"], x["consumed_tick"]) for x in acts) != e.digest:
                prov["prefix_digest_ne_artifact"] += 1
    p += [f"provenance {k}: {v}" for k, v in prov.items() if k not in ("entries", "artifact_checked") and v]
    if prov["artifact_checked"] != prov["entries"]:
        p.append(f"only {prov['artifact_checked']} of {prov['entries']} entries had a preserved source artifact")
    # evaluation never constructs the curriculum: a small post-hoc evaluation of the E4 final set
    exp = ec.load_experiment(PROFILES / "m7h_e4_on_s0.toml")
    out = GATE / "e2" / "e4_final_eval"
    if not (out / "evaluation_summary.json").is_file():     # evaluated once; a complete output is re-checked only
        if out.exists():
            raise RuntimeError(f"{out} exists but is incomplete")
        cfg = tr.config_from_experiment(exp)
        ev.evaluate_checkpoint(rd / "final", out, settings=dr.evaluation_settings(exp), deterministic_episodes=5,
                               stochastic_episodes=5, expected_contracts=tr.run_contracts(cfg), label="e2",
                               preserve_all=True)
    eva = {"artifacts": 0, "with_m7h_start": 0, "initial_not_tick0": 0, "first_row_not_tick0": 0}
    for mode in ("stochastic", "deterministic"):
        for a in sorted((out / mode / "workers").glob("w*/artifacts/*")):
            meta = read_json(a / "metadata.json")
            eva["artifacts"] += 1
            eva["with_m7h_start"] += int(bool((meta.get("labels") or {}).get("m7h_start")))
            eva["initial_not_tick0"] += int((meta.get("initial_observation") or {}).get("input_tick") != 0)
            acts = artifact_rows(a)
            eva["first_row_not_tick0"] += int(bool(acts) and acts[0]["consumed_tick"] != 0)
        rep = read_json(out / mode / "evaluation.json")
        keyed = [e for e in rep.get("episodes") or [] if any(k.startswith("m7h") for k in e)]
        if keyed:
            p.append(f"{mode}: {len(keyed)} evaluation episode rows carry an m7h key")
    p += [f"evaluation {k}: {v}" for k, v in eva.items() if k != "artifacts" and v]
    if eva["artifacts"] != 10:
        p.append(f"evaluation artifacts {eva['artifacts']} != 10")
    ok = not p
    write_result("e2", {"check": "E2", "ok": ok, "problems": p, "static_guard": static, "provenance": prov,
                        "evaluation": eva})
    return 0 if ok else 1


# -- E3 ---------------------------------------------------------------------------------------------------------------


def _e3_env(rank: int, run_id: str, exp: Any, standby_fault: Optional[Dict[str, Any]], root: Path) -> Any:
    from btt_parallel import RunCoordinator, WorkerSpec, initial_coordination_state
    from m7_runtime import prepare_worker_runtime
    from m7h_worker import CurriculumWorkerFactory

    coord = root / "coord"
    if not coord.exists():
        RunCoordinator.create(coord, initial_coordination_state(run_id, "test", 0))
    wdir = root / f"w{rank:02d}"
    prepare_worker_runtime(wdir / "runtime", EXE)
    spec = WorkerSpec(rank=rank, run_id=run_id, role="test", worker_dir=str(wdir), coordination_dir=str(coord),
                      executable=str(EXE), horizon=3600, base_seed=0, extra_env=tuple(exp.extra_env),
                      reward_contract=exp.reward, experiment=exp.summary(),
                      port_block_base=int(exp.values["environment.port_block_base"]),
                      port_block_size=int(exp.values["environment.port_block_size"]),
                      standby_preboot=True, standby_count=1, standby_fault=standby_fault)
    return CurriculumWorkerFactory(spec, exp.curriculum)()


def cmd_e3(args: argparse.Namespace) -> int:
    import numpy as np

    import m7f_trace as tr
    from m7_runtime import install_kill_on_close_job, kill_pid, list_processes_named, remove_worker_runtime
    from m7h_vec import policy_observation_from_dict

    install_kill_on_close_job()
    src = GATE / "e4" / "m7h_e4_on_s0"
    exp = ec.load_experiment(PROFILES / "m7h_e4_on_s0.toml")
    arch = mc.Archive.from_json(read_json(src / "final" / "curriculum_archive.json"),
                                (src / "final" / "curriculum_prefixes.bin").read_bytes())
    eligible = sorted(arch.eligible(), key=lambda e: (e.length, e.inserted_seq))
    limit = int(args.limit)
    if len(eligible) <= limit:
        chosen = list(eligible)
    else:
        idx = sorted({round(i * (len(eligible) - 1) / (limit - 1)) for i in range(limit)})
        chosen = [eligible[i] for i in idx]
    root = GATE / "e3"
    if root.exists():
        raise RuntimeError(f"{root} exists")
    root.mkdir(parents=True)
    # rank 2: every standby launch (even generations) fails fast (the existing startup_timeout fault: 0.3 s bound),
    # so every reset after its first is a cold fallback; it takes every 8th entry, ranks 0 / 1 share the rest
    faults = {0: None, 1: None, 2: {"generations": list(range(2, 4000, 2)), "startup_timeout_attempts": [1, 2, 3, 4, 5]}}
    rest = [e for i, e in enumerate(chosen) if i % 8 != 0]
    shares = {0: rest[0::2], 1: rest[1::2], 2: chosen[::8]}
    results: Dict[int, List[Dict[str, Any]]] = {r: [] for r in range(3)}
    errors: List[str] = []

    def work(rank: int) -> None:
        env = _e3_env(rank, "m7h_e4_on_s0", exp, faults[rank], root)
        try:
            for e in shares[rank]:
                env.reset()
                mode = (env.base.current_startup or {}).get("mode")
                spec = mc.prefix_spec(e, "m7h_e4_on_s0")
                t0 = time.perf_counter()
                reply = env.run_prefix_phase(spec)
                wall = time.perf_counter() - t0
                rec = env.recording.recorder
                ok = (reply["start"]["kind"] == mc.START_PREFIX and reply["start"]["prefix_length"] == e.length
                      and np.array_equal(reply["observation"], policy_observation_from_dict(e.end_observation))
                      and rec.action_count == e.length
                      and [a.consumed_tick for a in rec.actions] == list(range(e.length)))
                results[rank].append({"cell": list(e.cell), "L": e.length, "startup_mode": mode, "ok": bool(ok),
                                      "host_frame_equal": reply["start"]["prefix_host_frame_equal"],
                                      "wall_s": round(wall, 4), "ticks_per_s": round(e.length / wall, 1)})
        except Exception as exc:  # noqa: BLE001
            errors.append(f"rank {rank}: {type(exc).__name__}: {exc}")
        finally:
            env.close()
            remove_worker_runtime(root / f"w{rank:02d}" / "runtime")

    threads = [threading.Thread(target=work, args=(r,)) for r in range(3)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - t0
    flat = [x for r in range(3) for x in results[r]]
    p: List[str] = list(errors)
    if sum(1 for x in flat if not x["ok"]) or len(flat) != len(chosen):
        p.append(f"{sum(1 for x in flat if not x['ok'])} failed of {len(flat)} (chosen {len(chosen)})")
    modes: Dict[str, int] = {}
    for x in flat:
        modes[str(x["startup_mode"])] = modes.get(str(x["startup_mode"]), 0) + 1
    if modes.get("cold_fallback", 0) < 10:
        p.append(f"fewer than 10 cold-fallback starts: {modes}")
    # negative controls on a separate worker: a corrupted end observation, and a process killed mid-prefix
    neg: Dict[str, Any] = {}
    env = _e3_env(3, "m7h_e4_on_s0", exp, None, root)
    try:
        longest = max(eligible, key=lambda e: e.length)
        env.reset()
        spec = mc.prefix_spec(longest, "m7h_e4_on_s0")
        spec["end_observation"] = dict(spec["end_observation"], position_x=spec["end_observation"]["position_x"] + 1.0)
        try:
            env.run_prefix_phase(spec)
            neg["mismatch"] = "NOT DETECTED"
            p.append("a corrupted end observation was accepted")
        except mc.CurriculumError as exc:
            neg["mismatch"] = f"refused: {str(exc)[:160]}"
        env.reset()                                           # a fresh episode after the refused one
        pid = env.base.episode.pid
        timer = threading.Timer(0.3, kill_pid, args=(pid,))
        timer.start()
        reply = env.run_prefix_phase(mc.prefix_spec(longest, "m7h_e4_on_s0"))
        timer.cancel()
        fresh = env.base.last_observe
        neg["lifecycle"] = {"kind": reply["start"]["kind"], "killed_pid": pid, "failed_summary_end":
                            (reply.get("failed_summary") or {}).get("end_reason"),
                            "fresh_tick0": int(fresh.observation.input_tick) == 0 and int(fresh.step_count) == 0,
                            "new_pid": env.base.episode.pid,
                            "failure_log_lines": len((root / "w03" / "m7h_prefix_failures.jsonl").read_text().splitlines())
                            if (root / "w03" / "m7h_prefix_failures.jsonl").is_file() else 0}
        if reply["start"]["kind"] != mc.START_TICK0_AFTER_FAILURE or not neg["lifecycle"]["fresh_tick0"]:
            p.append(f"lifecycle-failure path: {neg['lifecycle']}")
    finally:
        env.close()
        remove_worker_runtime(root / "w03" / "runtime")
    # 20 finished curriculum episodes re-replayed from tick 0 as full trajectories (M7f tooling)
    reps = []
    arts = [(a, m_) for a, m_ in artifacts_of(src) if ((m_.get("labels") or {}).get("m7h_start") or {}).get("kind")
            == mc.START_PREFIX and m_.get("status") in ("terminal", "truncated")][:20]
    for k, (a, meta) in enumerate(arts):
        acts, _m = tr.artifact_actions(a)
        work_dir = root / "replays" / f"r{k:02d}"
        trace = tr.run_stepping_trace(f"e3_{k}", EXE, acts, work_dir, extra_env=dict(exp.extra_env), index=k)
        final = trace["steps"][-1]["observation"] if trace["steps"] else None
        want = meta.get("final_observation") or {}
        same_final = final is not None and all(final.get(f) == want.get(f) for f in mc.OBSERVATION_FIELDS if f != "host_frame")
        ok = (trace["consumed_tick_mismatch"] is None and trace["unsent"] == 0
              and trace["action_digest"] == meta["labels"]["native_action_digest"] and same_final)
        reps.append({"episode_id": meta["episode_id"], "L": meta["labels"]["m7h_start"]["prefix_length"],
                     "rows": len(acts), "ok": ok})
        remove_worker_runtime(work_dir / "runtime")
        shutil.rmtree(work_dir / "episodes", ignore_errors=True)
    if len(reps) < 20 or not all(r["ok"] for r in reps):
        p.append(f"full-trajectory replays: {sum(r['ok'] for r in reps)} of {len(reps)} exact (20 required)")
    leftover = list_processes_named()
    if leftover:
        p.append(f"leftover BattleShip {leftover}")
    lens = [x["L"] for x in flat]
    ok = not p
    write_result("e3", {"check": "E3", "ok": ok, "problems": p, "entries_eligible": len(eligible), "replayed": len(flat),
                        "exact": sum(1 for x in flat if x["ok"]), "startup_modes": modes,
                        "L": {"min": min(lens, default=None), "max": max(lens, default=None),
                              "mean": round(sum(lens) / len(lens), 1) if lens else None},
                        "host_frame_equal": sum(1 for x in flat if x["host_frame_equal"]),
                        "ticks_per_s_median": sorted(x["ticks_per_s"] for x in flat)[len(flat) // 2] if flat else None,
                        "wall_s": round(wall, 1), "negative_controls": neg, "full_trajectory_replays": reps,
                        "per_entry": flat})
    return 0 if ok else 1


# -- E6 ---------------------------------------------------------------------------------------------------------------


def cmd_e6(_args: argparse.Namespace) -> int:
    e4 = read_json(RESULTS / "e4.json")
    r1 = read_json(RESULTS / "r1_s0.json")
    e3 = read_json(RESULTS / "e3.json") if (RESULTS / "e3.json").is_file() else {}
    s_on = read_json(GATE / "e4" / "m7h_e4_on_s0" / "training_summary.json")
    s_off = read_json(GATE / "r1" / "m7h_r1_s0" / "training_summary.json")
    tp_on = (s_on.get("throughput") or {}).get("end_to_end_transitions_per_s")
    tp_off = (s_off.get("throughput") or {}).get("end_to_end_transitions_per_s")
    ratio = tp_on / tp_off if tp_on and tp_off else None
    cur = s_on.get("curriculum") or {}
    rows = rows_of(GATE / "e4" / "m7h_e4_on_s0")
    walls = [float(r["m7h"]["prefix_wall_s"]) for r in rows if (r.get("m7h") or {}).get("prefix_wall_s")]
    ticks = [int(r["m7h"]["prefix_length"]) for r in rows if (r.get("m7h") or {}).get("start_kind") == mc.START_PREFIX]
    rate = sum(ticks) / sum(walls) if walls and ticks else None
    naive_min = 3_072_000 / tp_on / 60 if tp_on else None
    base_min = 3_072_000 / tp_off / 60 if tp_off else None
    worst_min = base_min + 740 * 3000 / rate / 60 if base_min and rate else None
    p: List[str] = []
    if ratio is None or ratio < 0.5:
        p.append(f"throughput ratio {ratio}")
    if naive_min is None or naive_min > 75:
        p.append(f"projected training {naive_min} min > 75")
    ok = not p
    write_result("e6", {"check": "E6", "ok": ok, "problems": p,
                        "throughput": {"curriculum_on": tp_on, "curriculum_off_r1_s0": tp_off,
                                       "ratio": round(ratio, 4) if ratio else None},
                        "prefix": {"starts": len(ticks), "ticks": sum(ticks), "mean_L": round(sum(ticks) / len(ticks), 1)
                                   if ticks else None, "worker_ticks_per_s": round(rate, 1) if rate else None,
                                   "dispatch_wall_s": cur.get("dispatch_wall_s"), "dispatch_steps": cur.get("dispatch_steps"),
                                   "stall_per_dispatch_s": round(cur["dispatch_wall_s"] / cur["dispatch_steps"], 4)
                                   if cur.get("dispatch_steps") else None,
                                   "max_dispatch_wall_s": cur.get("max_dispatch_wall_s"),
                                   "e3_ticks_per_s_median": e3.get("ticks_per_s_median")},
                        "projection_min_per_3072000": {"scaled_e4": round(naive_min, 1) if naive_min else None,
                                                       "base_r1": round(base_min, 1) if base_min else None,
                                                       "worst_case_740x3000": round(worst_min, 1) if worst_min else None,
                                                       "note": "scaled_e4 uses the young E4 archive; worst_case adds 740 "
                                                               "starts of 3,000 ticks at the measured worker rate"},
                        "memory": {"curriculum_on": {k: e4["run"].get(k) for k in ("commit_drawn_gib",)} |
                                   {"min_avail_commit_gib": e4["run"]["probe"]["min_avail_commit_gib"],
                                    "min_avail_phys_gib": e4["run"]["probe"]["min_avail_phys_gib"]},
                                   "curriculum_off_r1_s0": {"commit_drawn_gib": r1["run"].get("commit_drawn_gib"),
                                                            "min_avail_commit_gib": r1["run"]["probe"]["min_avail_commit_gib"],
                                                            "min_avail_phys_gib": r1["run"]["probe"]["min_avail_phys_gib"]}},
                        "parent_peak_private_mib": {"on": ((s_on.get("memory") or {}).get("parent") or {}).get("peak_private_mib"),
                                                    "off": ((s_off.get("memory") or {}).get("parent") or {}).get("peak_private_mib")}})
    return 0 if ok else 1


# -- E7 ---------------------------------------------------------------------------------------------------------------


def _load_pickle(p: Path) -> Any:
    import pickle

    with open(p, "rb") as fh:
        return pickle.load(fh)


def check_drill(kind: str, res: Mapping[str, Any]) -> Tuple[bool, List[str], Dict[str, Any]]:
    import m7_trainer as tr
    from m7_evaluation import policy_parameter_digest

    p: List[str] = []
    prov = res.get("provenance") or {}
    moved = Path(res["moved_to"]) if res.get("moved_to") else None
    sets = {s["label"]: s for s in prov.get("checkpoint_sets") or []}
    facts: Dict[str, Any] = {"stop_kind": res.get("stop_kind"), "exit_code": res.get("exit_code"),
                             "moved_to": res.get("moved_to"), "sets": list(sets),
                             "incomplete_dirs": prov.get("incomplete_dirs"), "artifacts": prov.get("artifacts"),
                             "episode_rows": prov.get("episode_rows"), "leftovers": res.get("leftover_battleship_pids")}
    for lab in ("ckpt_000000000", "ckpt_000051200"):
        if not (sets.get(lab) or {}).get("complete_and_hash_valid"):
            p.append(f"periodic set {lab} not complete/hash-valid")
    if res.get("leftover_battleship_pids") or prov.get("battleship_processes"):
        p.append("BattleShip processes left")
    if moved is None or not moved.is_dir():
        p.append("run directory not moved to _partial")
    if not (moved and (moved / "stop_record.json").is_file()):
        p.append("stop_record.json missing")
    want_kind = {"cooperative": "cooperative_stop", "fallback": "fallback_ctrl_break", "emergency": "emergency_kill"}[kind]
    if res.get("stop_kind") != want_kind:
        p.append(f"stop kind {res.get('stop_kind')} != {want_kind}")
    if kind in ("cooperative", "fallback"):
        inter = (sets.get("interrupted") or {})
        block = inter.get("interruption") or {}
        facts["interruption"] = block
        if not inter.get("complete_and_hash_valid"):
            p.append("interrupted set missing or invalid")
        if block.get("completed_update_checkpoint") is not False:
            p.append("interrupted set not labelled completed_update_checkpoint = false")
        nt = block.get("num_timesteps") or {}
        vn = block.get("vecnormalize") or {}
        if moved is not None and inter.get("complete_and_hash_valid"):
            model = tr.M7PPO.load(str(moved / "interrupted" / "model.zip"), device="cpu")
            file_digest = policy_parameter_digest(model)
            stats = _load_pickle(moved / "interrupted" / "vecnormalize.pkl").obs_rms
            boundary = _load_pickle(moved / "interrupted" / tr.BOUNDARY_OBS_RMS_FILE)
            facts["file_checks"] = {
                "policy_digest_file_eq_record": file_digest == block["policy_parameters"]["digest"],
                "obs_rms_count": float(stats.count), "expected_count": EPS + 5 + nt.get("at_stop", -1),
                "boundary_count": float(boundary.count), "boundary_expected": EPS + 5 + (nt.get("at_last_completed_update") or -1)}
            fc = facts["file_checks"]
            if not fc["policy_digest_file_eq_record"]:
                p.append("model.zip digest differs from the recorded policy digest")
            if abs(fc["obs_rms_count"] - fc["expected_count"]) > 1e-6 or abs(fc["boundary_count"] - fc["boundary_expected"]) > 1e-6:
                p.append(f"statistics counts {fc}")
        if not (nt.get("partial_rollout_steps") or 0) > 0:
            p.append(f"no partial rollout recorded: {nt}")
        if vn.get("state") != "advanced_through_partial_rollout":
            p.append(f"vecnormalize state {vn.get('state')}")
        if (prov.get("artifacts") or {}).get("aborted", 0) < 1:
            p.append("no in-flight episode preserved as aborted")
        status = (prov.get("training_summary") or {}).get("status")
        if kind == "cooperative":
            if block.get("kind") != "stopped" or status != "stopped" or res.get("exit_code") != 130:
                p.append(f"cooperative: kind {block.get('kind')} status {status} exit {res.get('exit_code')}")
            pol = block.get("policy_parameters") or {}
            if pol.get("state") != "last_completed_update" or not pol.get("equals_update_boundary_digest"):
                p.append(f"cooperative stop policy state {pol}")
        else:
            if block.get("kind") != "interrupted" or status != "interrupted":
                p.append(f"fallback: kind {block.get('kind')} status {status}")
            pol = block.get("policy_parameters") or {}
            want = "last_completed_update" if block.get("phase_at_stop") == "collect" else "possibly_mid_update"
            if pol.get("state") != want:
                p.append(f"fallback policy state {pol.get('state')} for phase {block.get('phase_at_stop')}")
            if not any(e.get("event") == "ctrl_break_sent" for e in res.get("events") or []):
                p.append("CTRL_BREAK was not sent")
    else:
        if (sets.get("interrupted") or sets.get("final")):
            p.append("an interrupted/final set exists after an emergency kill")
        if prov.get("training_summary") is not None:
            p.append("a training summary exists after an emergency kill")
        if res.get("exit_code") in (0, 130):
            p.append(f"exit code {res.get('exit_code')} after a kill")
    return not p, p, facts


def cmd_e7(args: argparse.Namespace) -> int:
    prof = PROFILES / "m7h_e7_on_s0.toml"
    drills = {"cooperative": g.DrillOverride("stop", 12),
              "fallback": g.DrillOverride("stop", 12, ignore_stop_request=True, escalate_after_s=15.0),
              "emergency": g.DrillOverride("emergency", 12)}
    out: Dict[str, Any] = {}
    ok_all = True
    for name in args.drills.split(","):
        res = guarded(prof, run_id=f"m7h_e7_{name}", drill=drills[name])
        ok, p, facts = check_drill(name, res)
        ok_all &= ok
        out[name] = {"ok": ok, "problems": p, "facts": facts, "events": res.get("events"),
                     "probe_crossings": (res.get("probe") or {}).get("crossings")}
        log(f"E7 {name}: {'PASS' if ok else 'FAIL'} {p}")
    write_result("e7", {"check": "E7", "ok": ok_all, "drills": out,
                        "note": "the probe level was SIMULATED after 12 logged rollouts (DrillOverride); the real "
                                "memory probe ran throughout and every simulated sample is marked"})
    return 0 if ok_all else 1


# -- E1 / gate -----------------------------------------------------------------------------------------------------------


def cmd_e1(_args: argparse.Namespace) -> int:
    import subprocess

    out = RESULTS / "e1_unit_detail.json"
    rc = subprocess.run([sys.executable, str(RL_DIR / "m7h_tests.py"), "--out", str(out)], cwd=str(REPO_ROOT)).returncode
    d = read_json(out)
    write_result("e1", {"check": "E1", "ok": rc == 0, "passed": d["passed"], "total": d["total"],
                        "tests": [{k: r[k] for k in ("test", "ok")} for r in d["results"]]})
    return rc


def cmd_gate(_args: argparse.Namespace) -> int:
    gate = g.launch_gate()
    print(json.dumps(gate, indent=1, default=str))
    return 0 if gate["ok"] else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("gate", "e1", "r3", "e4", "e2", "e6"):
        sub.add_parser(name)
    sp = sub.add_parser("e5")
    sp.add_argument("--compare-only", action="store_true", help="re-compare the two recorded E5 runs (no training)")
    for name in ("r1", "r2"):
        sp = sub.add_parser(name)
        sp.add_argument("--seeds", default="0,1,2")
    sp = sub.add_parser("e3")
    sp.add_argument("--limit", default="200")
    sp = sub.add_parser("e7")
    sp.add_argument("--drills", default="cooperative,fallback,emergency")
    args = ap.parse_args(argv)
    return {"gate": cmd_gate, "e1": cmd_e1, "r1": cmd_r1, "r2": cmd_r2, "r3": cmd_r3, "e4": cmd_e4, "e5": cmd_e5,
            "e2": cmd_e2, "e3": cmd_e3, "e6": cmd_e6, "e7": cmd_e7}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
