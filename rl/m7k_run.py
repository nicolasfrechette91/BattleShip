#!/usr/bin/env python3
"""M7k driver: the bounded btt_reward_v3_t2 integration pilot and its verification (not a learning test).

    python rl/m7k_run.py gate
    python rl/m7k_run.py pilot [--transitions 102400]     # gate, train_m7 on rl/configs/m7k/m7k_v3t2_pilot_s0.toml, verify
    python rl/m7k_run.py verify-pilot

The pilot has the Phase K control's seed and settings (runs/m7g_k/m7g_s0_v1, btt_reward_v2; equal to v3 there because
that run never swept). btt_reward_v3_t2 differs from it only on a step that breaks target 2. Registered checks:
  V1 every pilot row's return equals the btt_reward_v3_t2 closed form of its own reward record;
  V2 before the first rollout that contains a target-2 break, the pilot is the control: the same rows (M7h R1 keys,
     sb3_num_timesteps_seen order) with the same returns; the first row that differs in actions ends after that
     rollout (a policy update can only change later actions);
  V3 a row with a target-2 break that is still action-identical to its control row differs in return by exactly its
     moving-target credit (from the record), nothing else;
  V4 no target-2 break at all -> the final set equals the control's checkpoint at the same transition count;
  V5 completed, leak-free (see the M7k teardown note), exe 1e7c62a0, v3_t2 + the diagnostic flag recorded,
     compatibility view differs from the control's only in the reward and the flags.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

RL_DIR = Path(__file__).resolve().parent
REPO_ROOT = RL_DIR.parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

PROFILE = RL_DIR / "configs" / "m7k" / "m7k_v3t2_pilot_s0.toml"


def twin(seed: int) -> Path:
    return REPO_ROOT / "runs" / "m7g_k" / f"m7g_s{seed}_v1"


def twin_profile(seed: int) -> Path:
    return RL_DIR / "configs" / "m7g" / f"m7g_s{seed}_v1.toml"
EXPECTED_EXE_SHA = "1e7c62a05a9397fb4ef1d404d85a793cd01c4dbdc187068e3a63890cb5cbeb97"
ROW_KEYS = ("rank", "worker_episode", "end_reason", "steps", "targets_broken", "native_action_digest")
ROLLOUT = 5120
OUT = REPO_ROOT / "runs" / "m7k" / "_pilot"


def read_json(p: Path) -> Any:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def rows(run_dir: Path) -> List[Dict[str, Any]]:
    p = run_dir / "metrics" / "episodes.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def run_dir_for(transitions: int, seed: int = 0) -> Path:
    return REPO_ROOT / "runs" / "m7k" / f"m7k_v3t2_pilot_s{seed}_t{transitions:07d}"


def t2_step_global(row: Dict[str, Any]) -> Optional[int]:
    """Transitions counted at the vector step that broke target 2 (sb3_num_timesteps_seen is the count at the
    episode's last vector step; every vector step adds n_envs = 5)."""
    mt = (row.get("reward_v3") or {}).get("moving_target")
    if not mt:
        return None
    return int(row["sb3_num_timesteps_seen"]) - 5 * (int(row["steps"]) - 1 - int(mt["consumed_tick"]))


def verify(run_dir: Path, transitions: int, seed: int = 0) -> Dict[str, Any]:
    import btt_reward_t2 as t2
    import experiment_config as ec
    import m7d_run as dr
    from btt_rewards import REWARD_V3_T2

    p: List[str] = []
    summ = read_json(run_dir / "training_summary.json")
    rj = read_json(run_dir / "run.json")
    if summ.get("status") != "completed" or summ["timesteps"]["sb3_num_timesteps"] != transitions:
        p.append(f"V5 status {summ.get('status')} timesteps {summ['timesteps']}")
    if rj["executable"]["sha256"] != EXPECTED_EXE_SHA or rj["reward_contract"] != REWARD_V3_T2.to_json() \
            or rj["m6_flags"].get("SSB64_RL_TARGET_DIAG") != "1":
        p.append("V5 run.json identity")
    diff = ec.compare_compatibility(ec.load_experiment(run_dir / "experiment.toml").compatibility_view(),
                                    ec.load_experiment(twin_profile(seed)).compatibility_view())
    if set(diff) != {"contracts.reward_resolved", "environment.extra_env"}:
        p.append(f"V5 compatibility view differs in {sorted(diff)}")
    pilot = sorted(rows(run_dir), key=lambda r: (int(r["sb3_num_timesteps_seen"]), r["rank"]))
    twin_rows = sorted([r for r in rows(twin(seed)) if int(r.get("sb3_num_timesteps_seen") or 0) <= transitions],
                  key=lambda r: (int(r["sb3_num_timesteps_seen"]), r["rank"]))
    # V1 closed forms
    v1_bad = []
    for r in pilot:
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
    # V2 / V3 identity until the first target-2 rollout
    t2_rows = [(t2_step_global(r), r) for r in pilot if t2_step_global(r) is not None]
    first_t2 = min((g for g, _ in t2_rows), default=None)
    first_t2_rollout_end = None if first_t2 is None else ((first_t2 - 1) // ROLLOUT + 1) * ROLLOUT
    tw = {(r["rank"], r["worker_episode"]): r for r in twin_rows}
    first_action_diff = None
    compared = 0
    for r in pilot:
        k = (r["rank"], r["worker_episode"])
        c = tw.get(k)
        same_actions = c is not None and all(r.get(x) == c.get(x) for x in ROW_KEYS)
        if not same_actions:
            if first_action_diff is None or int(r["sb3_num_timesteps_seen"]) < int(first_action_diff["sb3_num_timesteps_seen"]):
                first_action_diff = r
            continue
        compared += 1
        credit = ((r.get("reward_v3") or {}).get("moving_target") or {}).get("moving_target_term", 0.0)
        extra = (r["reward_v3"] or {}).get("right_sweep")
        if extra is not None:
            p.append(f"V3 {r['episode_id']}: a sweep in the pilot (the control never swept); unexpected")
        if abs((r["return"] - c["return"]) - credit) > 1e-9:
            p.append(f"V3 {r['episode_id']}: return {r['return']} vs control {c['return']} (credit {credit})")
    if first_action_diff is not None:
        if first_t2_rollout_end is None or int(first_action_diff["sb3_num_timesteps_at_end"]) < first_t2_rollout_end:
            p.append(f"V2 actions diverged at {first_action_diff['episode_id']} (at_end "
                     f"{first_action_diff['sb3_num_timesteps_at_end']}) before any target-2 rollout ({first_t2_rollout_end})")
    if len(pilot) < len(twin_rows) and first_t2 is None:
        p.append(f"V2 pilot has {len(pilot)} rows, control {len(twin_rows)}")
    ours = dr.checkpoint_digests(run_dir / "final")
    ref_dir = twin(seed) / "checkpoints" / f"ckpt_{transitions:09d}"
    twin_dig = dr.checkpoint_digests(ref_dir) if ref_dir.is_dir() else None
    if first_t2 is None and ours != twin_dig:
        p.append(f"V4 no target-2 break but final digests {ours} != control {twin_dig}")
    return {"contract": "m7k_pilot_verification_v1", "run_dir": str(run_dir.relative_to(REPO_ROOT)).replace("\\", "/"),
            "seed": seed, "transitions": transitions, "ok": not p, "problems": p, "rows": len(pilot),
            "control_rows": len(twin_rows),
            "rows_action_identical_to_control": compared,
            "target2_rows": [{"episode_id": r["episode_id"], "consumed_tick": r["reward_v3"]["moving_target"]["consumed_tick"],
                              "credit": r["reward_v3"]["moving_target"]["moving_target_term"], "global_transitions": g}
                             for g, r in sorted(t2_rows, key=lambda x: x[0])],
            "first_target2_rollout_end": first_t2_rollout_end,
            "first_action_divergence": None if first_action_diff is None else {
                "episode_id": first_action_diff["episode_id"], "sb3_num_timesteps_at_end": first_action_diff["sb3_num_timesteps_at_end"]},
            "final_digests": list(ours), "control_digests": list(twin_dig) if twin_dig else None,
            "final_equals_control": twin_dig is not None and ours == twin_dig,
            "cleanup": summ["cleanup"], "throughput_e2e": summ["throughput"]["end_to_end_transitions_per_s"],
            "verified_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def cmd_verify(a: argparse.Namespace) -> int:
    r = verify(run_dir_for(a.transitions, a.seed), a.transitions, a.seed)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"verification_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    out.write_text(json.dumps(r, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in r.items() if k != "cleanup"}, indent=1))
    print(f"written {out}")
    return 0 if r["ok"] else 1


def cmd_gate(_a: argparse.Namespace) -> int:
    import m7h_guard as g

    r = g.launch_gate()
    print(json.dumps({k: r[k] for k in ("ok", "problems")} | {"measurement": {k: r["measurement"].get(k) for k in
                                                                               ("avail_commit_gib", "avail_phys_gib", "battleship_pids")}}))
    return 0 if r["ok"] else 1


def cmd_pilot(a: argparse.Namespace) -> int:
    import experiment_config as ec
    import m7h_guard as g

    rd = run_dir_for(a.transitions, a.seed)
    if rd.exists():
        print(f"{rd} exists (never overwritten)", file=sys.stderr)
        return 2
    gate = g.launch_gate()
    if not gate["ok"]:
        print(f"launch gate refused: {gate['problems']}", file=sys.stderr)
        return 3
    OUT.mkdir(parents=True, exist_ok=True)
    base = ec.load_experiment(PROFILE)
    values = dict(base.values, **{"run.name": rd.name, "run.total_transitions": int(a.transitions),
                                  "run.base_seed": int(a.seed)})
    cfg = OUT / f"{rd.name}.toml"
    cfg.write_text(ec.to_toml_text(values, header=f"derived by rl/m7k_run.py from {PROFILE.name}: only run.name and "
                                                  f"run.total_transitions changed"), encoding="utf-8", newline="\n")
    (OUT / f"launch_gate_{rd.name}.json").write_text(json.dumps(gate, indent=1, default=str) + "\n", encoding="utf-8")
    log = OUT / f"{rd.name}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.log"
    with open(log, "w", encoding="utf-8") as fp:
        rc = subprocess.call([sys.executable, str(RL_DIR / "train_m7.py"), "--config", str(cfg)], cwd=str(REPO_ROOT),
                             stdout=fp, stderr=subprocess.STDOUT)
    print(f"train_m7 exit {rc}; log {log}")
    return rc if rc else cmd_verify(a)


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gate")
    for name in ("pilot", "verify-pilot"):
        s = sub.add_parser(name)
        s.add_argument("--transitions", type=int, default=102400)
        s.add_argument("--seed", type=int, default=0, choices=(0, 1, 2))
    a = p.parse_args(argv)
    return {"gate": cmd_gate, "pilot": cmd_pilot, "verify-pilot": cmd_verify}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
