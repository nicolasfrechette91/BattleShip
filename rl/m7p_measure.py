"""M7p offline measurements (supporting diagnostics, never gating): actor / critic saturation and recorded-pair sensitivity of
both arms at the registered checkpoints, on the fixed 33,997-state sample rebuilt under EACH arm's own observation contract.

Uses the functions of rl/m7p_geo4_diag.py (the diagnostic's registered procedure). Read only towards every run tree; writes
runs/m7p/campaign/_matrix/measurements.json (redirectable root). Nothing here alters training or selects checkpoints.

    python rl/m7p_measure.py [--arms exp,ctl] [--labels initial,final,...]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import experiment_config as ec  # noqa: E402
import m7d_run as dr  # noqa: E402
import m7e_matrix as em  # noqa: E402
import m7n_obs as mn  # noqa: E402
import m7p_geo4_diag as dg  # noqa: E402
import m7p_matrix as pm  # noqa: E402
import m7p_obs_geo4 as mg  # noqa: E402


def log(msg: str) -> None:
    print(f"[m7p_measure {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def checkpoint_labels() -> List[Dict[str, Any]]:
    pts = em.evaluated_points()
    out = [{"label": "initial", "t": 0, "exp_rel": "checkpoints/ckpt_000000000", "ctl_rel": "checkpoints/ckpt_000000000"}]
    for t in pts:
        if t in (0, pm.TOTAL_TRANSITIONS):
            continue
        out.append({"label": f"curve_t{t:09d}", "t": t, "exp_rel": f"checkpoints/ckpt_{t:09d}", "ctl_rel": f"checkpoints/ckpt_{t:09d}"})
    out.append({"label": "final", "t": pm.TOTAL_TRANSITIONS, "exp_rel": "final", "ctl_rel": "final"})   # both arms save the last set as `final`
    return out


def measure_checkpoint(model: Any, X: Any, isA: Any, pairs: Dict[str, Any]) -> Dict[str, Any]:
    import numpy as np

    o = dg._net_outputs(model, X)
    rec: Dict[str, Any] = {"num_timesteps": int(model.num_timesteps)}
    for net, z1, h2 in (("actor", o["z1p"], o["h2p"]), ("critic", o["z1v"], o["h2v"])):
        z2 = np.arctanh(np.clip(h2, -0.999999, 0.999999))
        rec[net] = {"L1_all": dg._sat(z1), "L1_A": dg._sat(z1[isA]), "L1_B": dg._sat(z1[~isA]), "L2_all": dg._sat(z2)}
    rec["pairs"] = {k: dg._pair_stats(o, v) for k, v in pairs.items()}
    rec["ablation_kl"] = {"agent_block": dg._ablation_kl(model, X, o, 20, 48), "targets_block": dg._ablation_kl(model, X, o, 556, 606),
                          "segment_geometry_block": dg._ablation_kl(model, X, o, 76, 332)}
    rec["policy_entropy_nats"] = float((-(np.exp(o["lps"]) * o["lps"]).sum(-1) - (np.exp(o["lpb"]) * o["lpb"]).sum(-1)).mean())
    rec["W1_norm"] = {"actor": float(np.linalg.norm(model.policy.mlp_extractor.policy_net[0].weight.detach().numpy())),
                      "critic": float(np.linalg.norm(model.policy.mlp_extractor.value_net[0].weight.detach().numpy()))}
    return rec


def measure(arms: Sequence[str], labels: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    import numpy as np

    from m7_trainer import M7PPO

    doc: Dict[str, Any] = {"schema": "m7p_measurements_v1", "utc": pm.utc_now(), "plan": pm.measurement_plan(), "arms": {}}
    want = set(labels) if labels else None
    pairs = None
    for arm in arms:
        if arm == "exp":
            X, tags, col = dg._rebuild(mg.make_builder)
            contract, digest = mg.OBS_CONTRACT, mg.contract_digest()
        else:
            X, tags, col = dg._rebuild(lambda l, c: mn.EntityObservationBuilder(l, c))
            contract, digest = mn.OBS_CONTRACT, mn.contract_digest()
        isA = np.char.startswith(tags, "A:")
        if pairs is None:
            pairs = dg._pairs(tags, col, X)
            doc["pairs_n"] = {k: len(v) for k, v in pairs.items()}
        doc["arms"][arm] = {"contract": contract, "contract_digest": digest, "sample_states": int(len(X)), "population_A": int(isA.sum()),
                            "population_B": int((~isA).sum()),
                            "input_block_l2_mean": {n: float(np.linalg.norm(X[:, a:b], axis=1).mean()) for n, a, b in
                                                    (("agent", 20, 48), ("segment_geometry", 76, 332), ("targets", 556, 606))}, "runs": {}}
        for spec in pm.matrix():
            run_dir = spec.run_dir if arm == "exp" else pm.ControlRun(spec.seed).run_dir
            name = spec.name if arm == "exp" else pm.ControlRun(spec.seed).name
            out: Dict[str, Any] = {"run_dir": ec.repo_relative(run_dir), "checkpoints": {}}
            models: List[Any] = []
            for lab in checkpoint_labels():
                if want and lab["label"] not in want:
                    continue
                ck = run_dir / (lab["exp_rel"] if arm == "exp" else lab["ctl_rel"])
                if not (ck / "model.zip").is_file():
                    out["checkpoints"][lab["label"]] = {"missing": ec.repo_relative(ck)}
                    continue
                meta = json.loads((ck / "checkpoint.json").read_text(encoding="utf-8"))
                c = meta.get("contracts") or {}
                if c.get("policy_observation_contract") != contract or c.get("policy_observation_contract_sha256") != digest:
                    raise RuntimeError(f"{ck}: contract {c.get('policy_observation_contract')} / digest mismatch for arm {arm}")
                m = M7PPO.load(str(ck / "model.zip"), device="cpu")
                models.append(m)
                rec = measure_checkpoint(m, X, isA, pairs)
                rec["policy_digest"] = dr.checkpoint_digests(ck)[0]
                out["checkpoints"][lab["label"]] = rec
            if len(models) >= 2:
                out["W1_row_change_per_interval"] = {"actor": dg._row_change(models, "policy_net"), "critic": dg._row_change(models, "value_net")}
            doc["arms"][arm]["runs"][name] = out
            log(f"{arm} {name}: {len(out['checkpoints'])} checkpoints measured")
    return doc


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arms", default="ctl,exp")
    ap.add_argument("--labels", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    doc = measure([a for a in args.arms.split(",") if a], [l for l in args.labels.split(",")] if args.labels else None)
    out = Path(args.out) if args.out else pm.state_dir() / "measurements.json"
    pm.write_json(out, doc)
    log(f"-> {ec.repo_relative(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
