#!/usr/bin/env python3
"""M7o: verification of the matched control's RECORDS (the M7n v3 runs), complementing the R1 reproduction of
rl/m7o_control_check.py. Read-only towards runs/m7n; writes runs/m7o/_control/control_verify.json.

For each seed s (m7n_s{s}_v3):
  V1  identity: the final and initial checkpoint sets exist, load, and their digests are recorded; the run's
      training verification (rl/m7d_run.verify_training_run, fresh, against the M7n profile) passes again;
  V2  evaluation records: the final (100 + 100) and initial (100 stochastic) labels re-verified from the preserved
      records: rl/m7d_run.verify_evaluation on the summaries, rl/m7g_k_run.verify_metrics, rl/m7h_verify.verify_eval_tick0
      (artifacts, tick-0 starts), evaluation flags, no exploration record in any row; every label file hashed;
  V3  clear evidence: candidates re-enumerated from the rows (cleared episodes); none exist in any M7n v3 label; a
      candidate without a passing replay record would be a problem (re-execution would then be required);
  V4  crossing evidence: candidates re-enumerated from the final stochastic rows with the corrected criterion
      (rl/m7n_crossing.candidates); the preserved crossing_verification.json of M7n must list exactly that candidate
      set, be exact and give X; none exist, so nothing is replayed;
  V5  rule inputs recomputed (rl/m7l_analysis.label_inputs with the M7o rule's parameters, rl/m7n_crossing.crossing_inputs)
      for the final and initial labels and compared with the M7n recorded analysis (runs/m7n/campaign/_matrix/analysis_n3.json).

What is RE-EXECUTED here: candidate enumeration, every verifier over the preserved files, every input computation.
What is VALIDATED FROM RECORDS: the episodes themselves (their artifacts and rows), the M7n clear / crossing documents
(there are no candidates, hence no replays to repeat). The R1 training reproduction is the separate check.

    python rl/m7o_control_verify.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import experiment_config as ec  # noqa: E402
import m7d_run as dr  # noqa: E402
import m7l_analysis as la  # noqa: E402
import m7n_crossing as xc  # noqa: E402
import m7o_analysis as oa  # noqa: E402

REPO_ROOT = RL_DIR.parent
M7N = REPO_ROOT / "runs" / "m7n" / "campaign"
ANALYSIS = M7N / "_matrix" / "analysis_n3.json"
RECORD = REPO_ROOT / "runs" / "m7o" / "_control" / "control_verify.json"
SEEDS = (0, 1, 2)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def log(msg: str) -> None:
    print(f"[m7o_verify {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run_dir(s: int) -> Path:
    return M7N / f"m7n_s{s}_v3"


def eval_dir(s: int) -> Path:
    return M7N / "_eval" / f"m7n_s{s}_v3"


def clears_dir(s: int) -> Path:
    return M7N / "_clears" / f"m7n_s{s}_v3"


def verify_label(s: int, label: str, exp: Any, plan_counts: Dict[str, int], out: Dict[str, Any]) -> List[str]:
    import m7g_k_run as kr
    import m7h_verify as mv

    p: List[str] = []
    d = eval_dir(s) / label
    summ = d / "evaluation_summary.json"
    if not summ.is_file():
        return [f"{label}: evaluation_summary.json missing"]
    res = json.loads(summ.read_text(encoding="utf-8"))
    ver = dr.verify_evaluation(res, exp.reward, int(exp.values["environment.horizon"]),
                               {"deterministic_episodes": plan_counts["deterministic"], "stochastic_episodes": plan_counts["stochastic"]})
    p += [f"{label}: {x}" for x in ver["problems"]]
    p += [f"{label}: metrics: {x}" for x in kr.verify_metrics(res, arm=None)]
    t0 = mv.verify_eval_tick0(d)
    p += [f"{label}: tick0: {x}" for x in t0["problems"]]
    files = {}
    for mode in ("stochastic", "deterministic"):
        f = d / mode / "evaluation.json"
        if f.is_file():
            files[mode] = sha256_file(f)
            rows = json.loads(f.read_text(encoding="utf-8")).get("episodes") or []
            if any(r.get("explore") is not None for r in rows):
                p.append(f"{label}/{mode}: an evaluation row carries an exploration record")
            if len(rows) != plan_counts[mode]:
                p.append(f"{label}/{mode}: {len(rows)} rows, planned {plan_counts[mode]}")
    files["summary"] = sha256_file(summ)
    out[label] = {"files_sha256": files, "tick0_ok": t0["ok"], "verify_ok": ver["ok"], "artifacts": t0.get("artifacts"), "rows": t0.get("rows"),
                  "policy_observation_contract": res.get("policy_observation_contract"), "extra_env": res.get("extra_env")}
    return p


def main() -> int:
    rule = oa.load_rule()
    P = oa.params(rule)
    an = json.loads(ANALYSIS.read_text(encoding="utf-8"))
    rec: Dict[str, Any] = {"schema": "m7o_control_verify_v1", "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "rule_sha256": rule["_sha256"], "analysis_n3_sha256": sha256_file(ANALYSIS), "seeds": {}, "problems": []}
    t0 = time.perf_counter()
    for s in SEEDS:
        prof = REPO_ROOT / "rl" / "configs" / "m7n" / f"m7n_s{s}_v3.toml"
        exp = ec.load_experiment(prof)
        seed: Dict[str, Any] = {"run": f"m7n_s{s}_v3", "profile_sha256": exp.source.sha256, "labels": {}}
        p: List[str] = []
        # V1 identity + training verification
        rd = run_dir(s)
        seed["final_digests"] = list(dr.checkpoint_digests(rd / "final"))
        seed["initial_digests"] = list(dr.checkpoint_digests(rd / "checkpoints" / "ckpt_000000000"))
        seed["final_checkpoint_json_sha256"] = sha256_file(rd / "final" / "checkpoint.json")
        seed["rows_sha256"] = sha256_file(rd / "metrics" / "episodes.jsonl")
        ver = dr.verify_training_run(rd, exp, fresh=True)
        seed["training_verification"] = {"ok": ver["ok"], "problems": ver["problems"][:10]}
        p += [f"training verification: {x}" for x in ver["problems"][:5]]
        # V2 evaluation records
        p += verify_label(s, "final", exp, {"stochastic": 100, "deterministic": 100}, seed["labels"])
        p += verify_label(s, "initial", exp, {"stochastic": 100, "deterministic": 100}, seed["labels"])
        # V3 clear evidence
        clears = 0
        for label in ("final", "initial"):
            rows = la.read_label(eval_dir(s) / label)
            cand = [e for m in ("stochastic", "deterministic") for e in rows[m] if e.get("cleared")]
            clears += len(cand)
            cd = clears_dir(s) / label / "clear_verification.json"
            if cand:
                doc = json.loads(cd.read_text(encoding="utf-8")) if cd.is_file() else None
                if doc is None or doc.get("verified") != len(cand):
                    p.append(f"{label}: {len(cand)} native clear candidates without a complete passing replay record")
        seed["clear_candidates"] = clears
        # V4 crossing evidence (final stochastic; the rule's population)
        cands = xc.candidates(la.read_label(eval_dir(s) / "final")["stochastic"])
        xd = clears_dir(s) / "final" / "crossing_verification.json"
        doc = json.loads(xd.read_text(encoding="utf-8")) if xd.is_file() else None
        ci, cp = xc.crossing_inputs(eval_dir(s) / "final", doc)
        p += [f"crossing: {x}" for x in cp]
        seed["crossing"] = {"candidates_re_enumerated": len(cands), "document": ec.repo_relative(xd) if xd.is_file() else None,
                            "document_sha256": sha256_file(xd) if xd.is_file() else None, "inputs": ci.to_json() if ci else None,
                            "replays_needed_now": len(cands)}
        # V5 rule inputs
        a_fin, pf = la.label_inputs(eval_dir(s) / "final", None, P)
        a_ini, pi = la.label_inputs(eval_dir(s) / "initial", None, P)
        p += [f"inputs final: {x}" for x in pf] + [f"inputs initial: {x}" for x in pi]
        rec_fin = an["per_seed"][str(s)]["v3"]["stochastic"]
        rec_ini = an["per_seed"][str(s)]["v3_initial"]["stochastic"]
        if a_fin.to_json() != rec_fin:
            p.append(f"final inputs differ from the M7n analysis: {a_fin.to_json()} vs {rec_fin}")
        if a_ini.to_json() != rec_ini:
            p.append(f"initial inputs differ from the M7n analysis: {a_ini.to_json()} vs {rec_ini}")
        if ci is not None and ci.X != an["per_seed"][str(s)]["v3"]["X"]:
            p.append(f"X {ci.X} differs from the M7n analysis {an['per_seed'][str(s)]['v3']['X']}")
        seed["inputs"] = {"final": a_fin.to_json(), "initial": a_ini.to_json(), "X": ci.X if ci else None,
                          "deterministic_final": la.deterministic_facts(eval_dir(s) / "final", P)}
        seed["problems"] = p
        seed["ok"] = not p
        rec["seeds"][str(s)] = seed
        rec["problems"] += [f"seed {s}: {x}" for x in p]
        log(f"seed {s}: {'PASS' if not p else 'FAIL ' + str(p[:2])} (T final {a_fin.T}, X {ci.X if ci else None}, clears {clears}, crossing candidates {len(cands)})")
    rec["ok"] = not rec["problems"]
    rec["wall_s"] = round(time.perf_counter() - t0, 1)
    rec["re_executed"] = ["candidate enumeration (clears, crossings)", "verify_evaluation / verify_metrics / verify_eval_tick0 over every final and initial label",
                          "verify_training_run over every control run", "label_inputs / crossing_inputs / deterministic_facts"]
    rec["validated_from_records"] = ["the evaluation episodes and artifacts (hashed)", "the M7n crossing documents (0 candidates: no replay to repeat)",
                                     "the M7n clear documents (0 candidates)"]
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    RECORD.write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8")
    log(f"control record verification {'PASS' if rec['ok'] else 'FAIL'} in {rec['wall_s']:.0f} s")
    return 0 if rec["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
