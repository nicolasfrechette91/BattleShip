"""M9-g1: the reported readings (never deciding) and the read-only post-run verification of a recorded gate. Pure file readers over `runs/m9_g1/`
(zero native ticks)."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import m9_artifacts as A
import m9_contract as C
import m9_curriculum as CU
import m9_eval as E
import m9_lineages as L
import m9_rule as R
import m9_sticky as S

REPORT_CONTRACT = "m9_report_v1"


def _read(p: Path) -> Any:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _rows(p: Path) -> List[Dict[str, Any]]:
    return A.read_jsonl(p)


def sha256_file(p: Path) -> str:
    return L.sha256_file(Path(p))


def tables_of(root: Path) -> Dict[str, L.Tables]:
    return L.load_all_tables(Path(root) / "lineages", [e["name"] for e in C.LINEAGES])


def check_episode_records(rows: Sequence[Mapping[str, Any]], tables: Mapping[str, L.Tables]) -> List[str]:
    """The sticky mask of every episode reproduces from its keys, the submitted words obey the rule, the words digest equals the recorded one."""
    import m8_rd_cells as mcell

    problems: List[str] = []
    for r in rows:
        tb = tables[r["lineage"]]
        tau = int(r["tau"])
        sampled, sub, mask = bytes.fromhex(r["sampled_hex"]), bytes.fromhex(r["submitted_hex"]), bytes.fromhex(r["sticky_mask_hex"])
        prev = tb.words[tau - 1] if tau > 0 else None
        for p in S.check_record(r.get("label"), tau, sampled, sub, mask, prev):
            problems.append(f"{r['episode']}: {p}")
        words = tb.words[:tau] + sub
        if mcell.words_digest(words) != r["native_action_digest"]:
            problems.append(f"{r['episode']}: native action digest differs from the recorded words")
        if hashlib_sha(tb.words[:tau]) != r["prefix_sha256"]:
            problems.append(f"{r['episode']}: prefix digest differs from the lineage's words")
        if len(problems) > 20:
            break
    return problems


def hashlib_sha(b: bytes) -> str:
    import hashlib

    return hashlib.sha256(b).hexdigest()


def replay_curriculum(rows: Sequence[Mapping[str, Any]], tables: Mapping[str, L.Tables]) -> Dict[str, Any]:
    """Rebuild the pointer's whole history from the completion-ordered training records alone, and re-derive every start from its keys."""
    lengths = {n: len(t.words) for n, t in tables.items()}
    cur = CU.Curriculum(lengths)
    problems: List[str] = []
    for r in rows:
        st = r["start"]
        ref = CU.Curriculum(lengths, tau0=int(st["pointer"]))
        got = ref.draw(int(st["episode"]))
        if got.to_json() != {k: st[k] for k in ("episode", "region", "tau", "lineage", "shared", "pointer")}:
            problems.append(f"{r['episode']}: the start does not reproduce from its keys")
            if len(problems) > 20:
                break
        if r["end_reason"] in ("clear", "fall", "horizon", "ended"):
            cur.record(CU.Start(int(st["episode"]), st["region"], int(st["tau"]), st["lineage"], bool(st["shared"]), int(st["pointer"])), bool(r["clear"]))
    return {"pointer": cur.pointer, "moves": cur.moves, "blocks": cur.blocks, "state": cur.state(), "problems": problems}


def verify_run(root: Path) -> Dict[str, Any]:
    root = Path(root)
    problems: List[str] = []
    out: Dict[str, Any] = {"root": str(root)}
    sd = root / "session"
    state = _read(sd / "state.json") if (sd / "state.json").is_file() else None
    if state is None or not state.get("done"):
        problems.append("the session did not finish (no done state)")
    rule = _read(sd / "rule.json") if (sd / "rule.json").is_file() else None
    if rule is None:
        problems.append("no rule.json")
    aud = A.audit_tree(root, skip_dirs=("workers", "vw"))
    out["metadata_audit"] = {"files": aud["files"], "jsonl_lines": aud["jsonl_lines"], "failures": aud["failures"][:10]}
    problems += [f"metadata: {f}" for f in aud["failures"][:5]]
    try:
        tables = tables_of(root)
    except Exception as exc:                                       # noqa: BLE001
        tables = {}
        problems.append(f"lineage tables: {type(exc).__name__}: {exc}")
    for e in C.LINEAGES:
        reg_p = root / "lineages" / e["name"] / "registration.json"
        if reg_p.is_file():
            reg = _read(reg_p)
            for n, h in (reg.get("table_sha256") or {}).items():
                if sha256_file(root / "lineages" / e["name"] / n) != h:
                    problems.append(f"lineage {e['name']}: {n} differs from its registered digest")
    cps = root / "training" / "checkpoints"
    n_cp = 0
    if cps.is_dir():
        for d in sorted(cps.iterdir()):
            meta = _read(d / "checkpoint.json")
            if sha256_file(d / "model.zip") != meta["model_zip_sha256"]:
                problems.append(f"checkpoint {d.name}: model.zip differs from its pinned digest")
            n_cp += 1
    out["checkpoints"] = n_cp
    tr_rows = _rows(root / "training" / "episodes.jsonl")
    ev_rows = _rows(root / "eval" / "episodes.jsonl")
    p4_rows = _rows(root / "p4" / "episodes.jsonl")
    if tables:
        for name, rows in (("training", tr_rows), ("eval", ev_rows), ("p4", p4_rows)):
            ps = check_episode_records(rows, tables)
            out[f"{name}_records"] = {"episodes": len(rows), "problems": ps[:5]}
            problems += [f"{name}: {p}" for p in ps[:5]]
        if tr_rows:
            rep = replay_curriculum(tr_rows, tables)
            logged = _rows(root / "training" / "pointer.jsonl")
            same = [(m["from"], m["to"]) for m in rep["moves"]] == [(r["from"], r["to"]) for r in logged]
            out["pointer_replay"] = {"pointer": rep["pointer"], "moves": len(rep["moves"]), "logged_moves": len(logged), "equal_to_log": same, "problems": rep["problems"][:5]}
            if not same:
                problems.append("the pointer history rebuilt from the episode records differs from the logged one")
            problems += [f"pointer replay: {p}" for p in rep["problems"][:5]]
            summ = _read(sd / "training_summary.json") if (sd / "training_summary.json").is_file() else None
            if summ is not None and summ.get("pointer_final") != rep["pointer"]:
                problems.append(f"the final pointer {summ.get('pointer_final')} differs from the rebuilt {rep['pointer']}")
            for m in logged:
                if m["clears"] < C.BLOCK_PASS:
                    problems.append(f"a step back at block {m['block']} with only {m['clears']} clears")
    ver_rows = _rows(root / "verification" / "replays.jsonl")
    verified = {r["id"]: bool(r["exact"]) for r in ver_rows}
    clears = [r for r in ev_rows + p4_rows if r["clear"]]
    unverified = [r["episode"] for r in clears if r["episode"] not in verified]
    out["verification"] = {"replays": len(ver_rows), "inexact": [i for i, ok in verified.items() if not ok], "clears_in_p4_and_eval": len(clears),
                           "clears_without_a_replay": len(unverified)}
    if out["verification"]["inexact"]:
        problems.append(f"inexact replays: {out['verification']['inexact'][:5]}")
    if rule is not None and state is not None:
        facts = dict(rule.get("facts") or {})
        agg = E.aggregate(p4_rows + ev_rows, verified)
        reach = {int(k): v for k, v in agg["reach"].items() if int(k) != 0}
        rerun = R.apply({"invalid": rule.get("diagnostics_invalid", []) if rule.get("outcome") == "INVALID" else [], "phases": facts.get("phases", {}), "training": facts.get("training", {}),
                         "reach": reach, "landings": facts.get("landings"), "unperturbed": {int(k): v for k, v in agg["unperturbed"].items() if int(k) != 0},
                         "fine": {int(k): v for k, v in agg["fine"].items()}})
        out["rule_recomputed"] = {"outcome": rerun["outcome"], "R": rerun["R"], "recorded_outcome": rule.get("outcome"), "recorded_R": rule.get("R")}
        if rule.get("outcome") not in ("INVALID",) and (rerun["outcome"] != rule.get("outcome") or rerun["R"] != rule.get("R")):
            problems.append(f"the rule recomputed from the records ({rerun['outcome']}, R {rerun['R']}) differs from the recorded ({rule.get('outcome')}, R {rule.get('R')})")
    out["problems"] = problems
    out["ok"] = not problems
    return out


def _median(xs: Sequence[float]) -> Optional[float]:
    s = sorted(xs)
    return None if not s else (s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2)


def full_report(root: Path) -> Dict[str, Any]:
    root = Path(root)
    sd = root / "session"
    out: Dict[str, Any] = {"report": REPORT_CONTRACT, "scope": C.SCOPE}
    rule = _read(sd / "rule.json") if (sd / "rule.json").is_file() else None
    out["rule"] = None if rule is None else {k: rule.get(k) for k in ("outcome", "R", "crossing_learned", "route_mastered_ticks", "reasons", "stop", "split", "diagnostics",
                                                                   "R_if_every_claimed_clear_were_verified")}
    ev_rows = _rows(root / "eval" / "episodes.jsonl")
    p4_rows = _rows(root / "p4" / "episodes.jsonl")
    ver = {r["id"]: bool(r["exact"]) for r in _rows(root / "verification" / "replays.jsonl")}
    agg = E.aggregate(p4_rows + ev_rows, ver)
    out["reach"] = {str(k): v for k, v in sorted(agg["reach"].items(), key=lambda kv: -int(kv[0]))}
    out["unperturbed"] = {str(k): v for k, v in sorted(agg["unperturbed"].items(), key=lambda kv: -int(kv[0]))}
    out["fine_grid"] = {str(k): v for k, v in sorted(agg["fine"].items(), key=lambda kv: -int(kv[0]))}
    out["tick0"] = agg["tick0"]
    out["deterministic"] = {str(k): v for k, v in agg["deterministic"].items()}
    tr = _rows(root / "training" / "episodes.jsonl")
    ro = _rows(root / "training" / "rollouts.jsonl")
    out["training"] = {"episodes": len(tr), "clears": sum(1 for r in tr if r["clear"]), "ends": {k: sum(1 for r in tr if r["end_reason"] == k) for k in sorted({r["end_reason"] for r in tr})}}
    if ro:
        last = ro[-1]
        out["training"].update({"rollouts": len(ro), "num_timesteps": last["num_timesteps"], "wall_s": last["wall_s"], "pointer_final": last["pointer"], "moves": last["moves"],
                                "median_transitions_per_s": _median([r["interval_transitions_per_s"] for r in ro]),
                                "ep_return_mean_recent_first_last": [ro[0]["ep_return_mean_recent"], last["ep_return_mean_recent"]],
                                "entropy_loss_first_last": [ro[min(1, len(ro) - 1)]["update_metrics_of_the_previous_rollout"].get("entropy_loss"),
                                                            last["update_metrics_of_the_previous_rollout"].get("entropy_loss")],
                                "explained_variance_first_last": [ro[min(1, len(ro) - 1)]["update_metrics_of_the_previous_rollout"].get("explained_variance"),
                                                                  last["update_metrics_of_the_previous_rollout"].get("explained_variance")],
                                "prefix_ticks": last["prefix_ticks"], "policy_ticks": last["policy_ticks"], "staged": last["staged"], "wait_s": last["wait_s"]})
    ptr = _rows(root / "training" / "pointer.jsonl")
    out["pointer_trace"] = [{"t_wall_s": m["t_wall_s"], "from": m["from"], "to": m["to"], "block": m["block"], "clears": m["clears"]} for m in ptr]
    blocks = _rows(root / "training" / "blocks.jsonl")
    out["blocks"] = {"total": len(blocks), "passed": sum(1 for b in blocks if b["moved"]), "by_pointer": {}}
    for b in blocks:
        d = out["blocks"]["by_pointer"].setdefault(str(b["pointer"]), [0, 0])
        d[0] += 1
        d[1] += int(b["moved"])
    hold: Dict[str, Dict[str, List[int]]] = {}
    for r in tr:
        if r["start"]["region"] == "strip" and r["start"]["pointer"] == r.get("pointer_now", r["start"]["pointer"]) and r.get("mid_hold") is not None:
            d = hold.setdefault(str(r["start"]["pointer"]), {"mid_hold": [0, 0], "at_change": [0, 0]})
            c = d["mid_hold" if r["mid_hold"] else "at_change"]
            c[0] += 1
            c[1] += int(r["clear"])
    out["handover_diagnostic"] = hold
    if ptr and out["training"].get("wall_s"):
        mastered = C.TAU0 - int(ptr[-1]["to"])
        out["backward_rate"] = {"route_ticks_mastered": mastered, "per_training_hour": round(mastered / (out["training"]["wall_s"] / 3600.0), 1),
                                "note": "a projection to tick 0 from this rate is an extrapolation, never a result"}
    for name in ("p1", "p2", "p3", "p4", "verification", "close", "training_summary", "eval_run"):
        p = sd / f"{name}.json"
        if p.is_file():
            d = _read(p)
            out[name] = {k: v for k, v in d.items() if k not in ("lineages", "starts", "created_utc", "task")} if name in ("p1", "p2") else {k: d[k] for k in list(d)[:14] if k not in ("task",)}
    cp = root / "training" / "checkpoints.json"
    if cp.is_file():
        out["checkpoint_digests"] = [{k: c.get(k) for k in ("checkpoint", "num_timesteps", "model_zip_sha256", "wall_s")} for c in (_read(cp).get("checkpoints") or [])] + \
            [{k: (_read(cp).get("final") or {}).get(k) for k in ("checkpoint", "num_timesteps", "model_zip_sha256")}]
    ms = sd / "memory_summary.json"
    if ms.is_file():
        out["memory"] = _read(ms)
    return out
