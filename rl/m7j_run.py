#!/usr/bin/env python3
"""M7j driver: the Stage 0 btt_reward_v3 integration pilot and its verification (no learning test here).

    python rl/m7j_run.py gate            # the registered launch gate (memory, disk, CPU, ports); launches nothing
    python rl/m7j_run.py pilot           # gate, then rl/train_m7.py on rl/configs/m7j/m7j_v3_pilot_s0.toml, then verify
    python rl/m7j_run.py verify-pilot    # verification only (never modifies the run)

Stage 0 (docs/rl_reward_v3_m7j.md): 102,400 transitions of btt_reward_v3 from tick 0 with the Phase K v1 control's
seed and settings. Its historical twin (runs/m7g_k/m7g_s0_v1, btt_reward_v2) never broke more than 6 targets in an
episode, so no step of this pilot can carry a v3 route term, and the pilot must reproduce the twin exactly:
  P1 the final set's policy-parameter and obs_rms digests equal m7g_s0_v1 ckpt_000102400 (and M7e s0 ckpt_000102400);
  P2 the episode rows equal the twin's rows up to 102,400 transitions on the registered row keys (M7h R1 keys) and in
     return; every row carries a reward_v3 record with no sweep, no qualified landing and v3 return == v2 return;
  P3 the run is completed and leak-free, used exe 1e7c62a0, recorded btt_reward_v3 (route block) and the diagnostic
     flag, and its compatibility view differs from the twin's only in contracts.reward_resolved and extra_env.
Any failure is an integration defect of v3, not a learning result.
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

PROFILE = RL_DIR / "configs" / "m7j" / "m7j_v3_pilot_s0.toml"
RUN_DIR = REPO_ROOT / "runs" / "m7j" / "m7j_v3_pilot_s0"
TWIN = REPO_ROOT / "runs" / "m7g_k" / "m7g_s0_v1"
TWIN_PROFILE = RL_DIR / "configs" / "m7g" / "m7g_s0_v1.toml"
M7E_TWIN_CKPT = REPO_ROOT / "runs" / "m7e" / "m7e_s0_v2" / "checkpoints" / "ckpt_000102400"
EXPECTED_EXE_SHA = "1e7c62a05a9397fb4ef1d404d85a793cd01c4dbdc187068e3a63890cb5cbeb97"
ROW_KEYS = ("rank", "worker_episode", "end_reason", "steps", "targets_broken", "native_action_digest")   # M7h R1
PILOT_TRANSITIONS = 102_400
OUT = REPO_ROOT / "runs" / "m7j" / "_pilot"


def read_json(p: Path) -> Any:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def rows(run_dir: Path) -> List[Dict[str, Any]]:
    p = run_dir / "metrics" / "episodes.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def cmd_gate(_a: argparse.Namespace) -> int:
    import m7h_guard as g

    r = g.launch_gate()
    print(json.dumps(r, indent=1, default=str))
    return 0 if r["ok"] else 1


def verify_pilot(run_dir: Path = RUN_DIR) -> Dict[str, Any]:
    import experiment_config as ec
    import m7d_run as dr
    from btt_rewards import REWARD_V3

    p: List[str] = []
    summ = read_json(run_dir / "training_summary.json")
    if summ.get("status") != "completed" or not summ["cleanup"]["leak_free"]:
        p.append(f"P3 status {summ.get('status')} leak_free {summ['cleanup']['leak_free']}")
    if summ["timesteps"]["sb3_num_timesteps"] != PILOT_TRANSITIONS:
        p.append(f"P3 timesteps {summ['timesteps']}")
    rj = read_json(run_dir / "run.json")
    if rj["executable"]["sha256"] != EXPECTED_EXE_SHA:
        p.append(f"P3 executable {rj['executable']['sha256']}")
    if rj["reward_contract"] != REWARD_V3.to_json() or rj["m6_flags"].get("SSB64_RL_TARGET_DIAG") != "1":
        p.append("P3 run.json reward contract / diagnostic flag")
    diff = ec.compare_compatibility(ec.load_experiment(PROFILE).compatibility_view(),
                                    ec.load_experiment(TWIN_PROFILE).compatibility_view())
    if set(diff) != {"contracts.reward_resolved", "environment.extra_env"}:
        p.append(f"P3 compatibility view differs in {sorted(diff)}")
    ours = dr.checkpoint_digests(run_dir / "final")
    twin = dr.checkpoint_digests(TWIN / "checkpoints" / "ckpt_000102400")
    m7e = dr.checkpoint_digests(M7E_TWIN_CKPT) if M7E_TWIN_CKPT.is_dir() else None
    if ours != twin:
        p.append(f"P1 final digests {ours} != Phase K m7g_s0_v1 ckpt_000102400 {twin}")
    if m7e is not None and ours != m7e:
        p.append(f"P1 final digests != M7e s0 ckpt_000102400 {m7e}")
    a = sorted(rows(run_dir), key=lambda r: (r["rank"], r["worker_episode"]))
    # The M7h R1 rule (rl/m7h_run.py cmd_r1): twin rows whose sb3_num_timesteps_seen <= 102,400 (30 rows for seed 0).
    # sb3_num_timesteps_at_end would also admit an episode that ended in rollout 21, after the last compared update.
    b = sorted([r for r in rows(TWIN) if int(r.get("sb3_num_timesteps_seen") or 0) <= PILOT_TRANSITIONS],
               key=lambda r: (r["rank"], r["worker_episode"]))
    ka = [tuple(r.get(k) for k in ROW_KEYS) + (round(r["return"], 9),) for r in a]
    kb = [tuple(r.get(k) for k in ROW_KEYS) + (round(r["return"], 9),) for r in b]
    if ka != kb:
        p.append(f"P2 rows: pilot {len(ka)}, twin {len(kb)}, equal {ka == kb}")
    v3_bad = [r["episode_id"] for r in a if r.get("end_reason") in ("fall", "horizon", "clear") and (
        not r.get("reward_v3") or r["reward_v3"]["right_sweep"] is not None or r["reward_v3"]["qualified_landing"] is not None
        or abs(r["reward_v3"]["term_totals"]["sweep_term"]) + abs(r["reward_v3"]["term_totals"]["crossing_term"]) != 0.0)]
    if v3_bad:
        p.append(f"P2 rows with a v3 route event or no reward_v3 record: {v3_bad[:5]}")
    return {"contract": "m7j_stage0_pilot_verification_v1", "run_dir": str(run_dir.relative_to(REPO_ROOT)).replace("\\", "/"),
            "ok": not p, "problems": p, "final_digests": list(ours), "twin_digests": list(twin),
            "m7e_digests": list(m7e) if m7e else None, "rows": len(ka), "twin_rows": len(kb),
            "rows_with_v3_record": sum(1 for r in a if r.get("reward_v3")),
            "throughput_e2e": summ["throughput"]["end_to_end_transitions_per_s"], "wall_s": summ.get("wall_s"),
            "verified_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def cmd_verify(a: argparse.Namespace) -> int:
    r = verify_pilot(Path(a.run) if a.run else RUN_DIR)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"verification_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    out.write_text(json.dumps(r, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(r, indent=1))
    print(f"written {out}")
    return 0 if r["ok"] else 1


def cmd_pilot(a: argparse.Namespace) -> int:
    import m7h_guard as g

    if RUN_DIR.exists():
        print(f"{RUN_DIR} exists (never overwritten); run verify-pilot or move it aside", file=sys.stderr)
        return 2
    gate = g.launch_gate()
    if not gate["ok"]:
        print(f"launch gate refused: {gate['problems']}", file=sys.stderr)
        return 3
    OUT.mkdir(parents=True, exist_ok=True)
    log = OUT / f"pilot_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.log"
    (OUT / "launch_gate.json").write_text(json.dumps(gate, indent=1, default=str) + "\n", encoding="utf-8")
    with open(log, "w", encoding="utf-8") as fp:
        rc = subprocess.call([sys.executable, str(RL_DIR / "train_m7.py"), "--config", str(PROFILE)], cwd=str(REPO_ROOT),
                             stdout=fp, stderr=subprocess.STDOUT)
    print(f"train_m7 exit {rc}; log {log}")
    if rc != 0:
        return rc
    return cmd_verify(argparse.Namespace(run=None))


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gate")
    sub.add_parser("pilot")
    v = sub.add_parser("verify-pilot")
    v.add_argument("--run", default=None)
    a = p.parse_args(argv)
    return {"gate": cmd_gate, "pilot": cmd_pilot, "verify-pilot": cmd_verify}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
