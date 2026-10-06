"""M9-g2: the read-only post-run verification (`verify_run`) and the reported readings (`full_report`) of a recorded session. Pure file readers over
`runs/m9_g2/s<k>/` (zero native ticks).

`verify_run` re-derives: every training, probe, T0 and audit record's sticky mask from its keys and its words digest from the registered prefix and the
submitted words; every training start from its keys; the pointer, window and attempt history from the records alone (rl/m9_g2_frontier.replay_history);
the move / attempt bounds; every checkpoint's pinned digests; the tape table and its digest; D, R and the s1 rule from the records; the metadata audit.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import m8_rd_cells as mcell
import m9_artifacts as A
import m9_contract as C
import m9_g2_arena as AR
import m9_g2_contract as G
import m9_g2_frontier as F
import m9_g2_rule as R
import m9_g2_tape as TP
import m9_lineages as L

REPORT_CONTRACT = "m9_g2_report_v1"


def _read(p: Path) -> Any:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _rows(p: Path) -> List[Dict[str, Any]]:
    return A.read_jsonl(p)


def sha256_file(p: Path) -> str:
    return L.sha256_file(Path(p))


def tables_of(root: Path) -> Dict[str, L.Tables]:
    return L.load_all_tables(Path(root) / "lineages", [e["name"] for e in C.LINEAGES])


def check_records(rows: Sequence[Mapping[str, Any]], tables: Mapping[str, L.Tables], *, tape: bool = False) -> List[str]:
    """The g2 sticky mask of every episode reproduces from its keys, the words obey the rule, the words digest and the prefix digest match the lineage."""
    problems: List[str] = []
    tp = None
    for r in rows:
        tb = tables[r["lineage"]]
        tau = int(r["tau"])
        sampled, sub, mask = bytes.fromhex(r["sampled_hex"]), bytes.fromhex(r["submitted_hex"]), bytes.fromhex(r["sticky_mask_hex"])
        prev = tb.words[tau - 1] if tau > 0 else None
        for p in AR.check_record(r.get("label"), tau, sampled, sub, mask, prev):
            problems.append(f"{r['episode']}: {p}")
        words = tb.words[:tau] + sub
        if mcell.words_digest(words) != r["native_action_digest"]:
            problems.append(f"{r['episode']}: native action digest differs from the recorded words")
        if hashlib.sha256(tb.words[:tau]).hexdigest() != r["prefix_sha256"]:
            problems.append(f"{r['episode']}: prefix digest differs from the lineage's words")
        if tape or r.get("driver") == "tape":
            import m9_sticky as S

            tp = tp or S.Tape(tables[G.TRUNK].words)
            for i, w in enumerate(sampled):
                if w != tp.word(tau + i):
                    problems.append(f"{r['episode']}: tape word {tau + i} is not the trunk's")
                    break
        if len(problems) > 20:
            break
    return problems


def audit_rows(records: Sequence[Mapping[str, Any]], verified: Mapping[str, bool]) -> Dict[str, Any]:
    """The close audit's rows per landing: sticky {n, clears, verified}; unperturbed {n, clears}; det; tick0."""
    sticky: Dict[int, Dict[str, Any]] = {}
    unp: Dict[int, Dict[str, Any]] = {}
    det: Dict[int, Dict[str, Any]] = {}
    tick0: Dict[str, Dict[str, Any]] = {}
    for r in records:
        kind, lam, clear = r["eval_kind"], int(r["landing"]), bool(r["clear"])
        ok = clear and bool(verified.get(r["episode"], False))
        if kind == "audit_sticky":
            x = sticky.setdefault(lam, {"n": 0, "clears": 0, "verified": 0, "ends": {}, "start_value": None, "start_entropy": None, "returns": []})
            x["n"] += 1
            x["clears"] += int(clear)
            x["verified"] += int(ok)
            x["ends"][r["end_reason"]] = x["ends"].get(r["end_reason"], 0) + 1
            x["returns"].append(float(r["return"]))
            if r.get("start_value") is not None:
                x["start_value"], x["start_entropy"] = r["start_value"], r["start_entropy"]
        elif kind == "audit_unperturbed":
            x = unp.setdefault(lam, {"n": 0, "clears": 0, "verified": 0})
            x["n"] += 1
            x["clears"] += int(clear)
            x["verified"] += int(ok)
        elif kind == "audit_det":
            det[lam] = {"clear": clear, "verified": ok, "end": r["end_reason"], "ticks": r["ticks"], "t": r["t"]}
        elif kind in ("tick0_sticky", "tick0_det"):
            x = tick0.setdefault(kind, {"n": 0, "clears": 0, "verified": 0})
            x["n"] += 1
            x["clears"] += int(clear)
            x["verified"] += int(ok)
    for x in sticky.values():
        rs = x.pop("returns")
        x["mean_return"] = round(sum(rs) / len(rs), 4) if rs else None
        x["calibration_gap"] = round(float(x["start_value"]) - x["mean_return"], 4) if (x["start_value"] is not None and x["mean_return"] is not None) else None
    return {"sticky": sticky, "unperturbed": unp, "deterministic": det, "tick0": tick0}


def post_target8_share(train_rows: Sequence[Mapping[str, Any]], window: int = 100) -> List[Dict[str, Any]]:
    """Per window of training episodes: the share of post-target-8 policy ticks that belong to clearing episodes (proposal 4.4; reported only). A start
    at or after the trunk's target-8 break (2,066) is post-target-8 from its handover; otherwise from target 8's recorded break tick."""
    out: List[Dict[str, Any]] = []
    for i in range(0, len(train_rows), window):
        chunk = train_rows[i:i + window]
        tot = win = 0
        for r in chunk:
            tau, end_tick = int(r["tau"]), int(r["ticks"])
            t8 = None
            if tau >= 2066:
                t8 = tau
            else:
                for b in r.get("breaks") or []:
                    if int(b[1]) == 8:
                        t8 = int(b[0])
                        break
            if t8 is None:
                continue
            n = max(0, end_tick - max(t8, tau))
            tot += n
            win += n if r["clear"] else 0
        out.append({"episodes": [i, i + len(chunk)], "post_target8_ticks": tot, "in_clearing_episodes": win, "share": round(win / tot, 4) if tot else None})
    return out


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
    aud = A.audit_tree(root, skip_dirs=("workers", "vw", "derived", "input"))
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
    # checkpoints
    cps = root / "training" / "checkpoints"
    n_cp = 0
    if cps.is_dir():
        import m9_g2_resume as RS

        for d in sorted(cps.iterdir()):
            meta = _read(d / "checkpoint.json")
            if sha256_file(d / "model.zip") != meta["model_zip_sha256"]:
                problems.append(f"checkpoint {d.name}: model.zip differs from its pinned digest")
            if RS.zip_member_digests(d / "model.zip") != meta.get("members_sha256"):
                problems.append(f"checkpoint {d.name}: a zip member differs from its pinned digest")
            if sha256_file(d / "curriculum_state.json") != meta.get("curriculum_state_sha256"):
                problems.append(f"checkpoint {d.name}: curriculum_state.json differs from its pinned digest")
            n_cp += 1
    out["checkpoints"] = n_cp
    tr_rows = _rows(root / "training" / "episodes.jsonl")
    pr_rows = _rows(root / "training" / "probes.jsonl")
    t0_rows = _rows(root / "t0" / "episodes.jsonl")
    au_rows = _rows(root / "audit" / "episodes.jsonl")
    at_rows = _rows(root / "training" / "attempts.jsonl")
    summ = _read(sd / "training_summary.json") if (sd / "training_summary.json").is_file() else None
    opn = _read(sd / "open.json") if (sd / "open.json").is_file() else {}
    session_k = int(opn.get("session", 1))
    if tables:
        for name, rows in (("training", tr_rows), ("probes", pr_rows), ("t0", t0_rows), ("audit", au_rows)):
            ps = check_records(rows, tables)
            out[f"{name}_records"] = {"episodes": len(rows), "problems": ps[:5]}
            problems += [f"{name}: {p}" for p in ps[:5]]
        lengths = {n: len(t.words) for n, t in tables.items()}
        carried = (opn.get("resume") or {}).get("carried_state")
        rep = F.replay_history(tr_rows, at_rows, lengths, session=session_k, state=carried)
        moves_logged = [(m["from"], m["to"]) for m in _rows(root / "training" / "moves.jsonl")]
        same = rep["moves"] == moves_logged
        out["frontier_replay"] = {"pointer": rep["pointer"], "moves": len(rep["moves"]), "logged_moves": len(moves_logged), "equal_to_log": same, "attempts": rep["attempts"], "problems": rep["problems"][:5]}
        if not same:
            problems.append("the move history rebuilt from the records differs from the logged one")
        problems += [f"frontier replay: {p}" for p in rep["problems"][:5]]
        if summ is not None and summ.get("pointer_final") != rep["pointer"]:
            problems.append(f"the final pointer {summ.get('pointer_final')} differs from the rebuilt {rep['pointer']}")
        # every probe episode belongs to a recorded attempt, with the keyed start
        by_attempt = {int(a["n"]): a for a in at_rows}
        for r in pr_rows:
            a = by_attempt.get(int(r["attempt"]))
            if a is None:
                problems.append(f"{r['episode']}: no attempt record")
                continue
            if r["part"] == "strip":
                tau, lineage, _sh = F.strip_start(int(a["pointer"]), int(a["a"]), int(r["k"]), lengths)
                if int(r["tau"]) != tau or r["lineage"] != lineage:
                    problems.append(f"{r['episode']}: the strip start does not reproduce from its keys")
            elif int(r["tau"]) != int(r["part"]) or r["lineage"] != G.TRUNK:
                problems.append(f"{r['episode']}: a re-check start is not the trunk's landing")
            if r["label"] != G.probe_label(int(a["pointer"]), int(a["a"]), r["part"], int(r["k"])):
                problems.append(f"{r['episode']}: label differs from the key scheme")
            if len(problems) > 30:
                break
        for a in at_rows:
            if a["result"] == "MOVED":
                if int(a.get("strip_clears", 0)) < G.TEST_PASS or any(int(v.get("clears", 0)) < G.TEST_PASS for v in dict(a.get("rechecks") or {}).values()):
                    problems.append(f"attempt {a['n']}: a move without {G.TEST_PASS} clears in every test")
                if set(int(k) for k in dict(a.get("rechecks") or {})) != set(F.landings_behind(int(a["pointer"]))):
                    problems.append(f"attempt {a['n']}: the re-check set is not every landing behind the frontier")
    # verification and the tape
    ver_rows = _rows(root / "verification" / "replays.jsonl")
    verified = {r["id"]: bool(r["exact"]) for r in ver_rows}
    inexact = [i for i, ok in verified.items() if not ok]
    if inexact:
        problems.append(f"inexact replays: {inexact[:5]}")
    tape_pin = _read(sd / "tape_baseline.json") if (sd / "tape_baseline.json").is_file() else None
    claimed_rec = _read(root / "t0" / "tape_table.json") if (root / "t0" / "tape_table.json").is_file() else None
    if tape_pin is not None and t0_rows and claimed_rec is not None:
        keys = {int(k): int(v["keys"]) for k, v in dict(claimed_rec["landings"]).items()}
        claimed = TP.claimed_table(t0_rows, keys)
        again = TP.pinned_table(claimed, t0_rows, verified)
        if TP.table_digest(tape_pin) != tape_pin.get("sha256"):
            problems.append("the pinned tape table's digest differs from its content")
        if TP.table_digest(again) != tape_pin.get("sha256"):
            problems.append("the pinned tape table does not re-derive from the T0 records and the replays")
        out["tape"] = {"sha256": tape_pin.get("sha256"), "bars": {k: v.get("B") for k, v in dict(tape_pin["landings"]).items()}, "pinned": tape_pin.get("pinned")}
    # the rule from the records
    if rule is not None and state is not None:
        agg = audit_rows(au_rows, verified)
        facts = dict(rule.get("facts") or {})
        bars = {int(k): v for k, v in dict(facts.get("bars") or {}).items()}
        rerun = R.apply_s1({"invalid": rule.get("reasons", []) if rule.get("outcome") == "INVALID" else [], "phases": facts.get("phases", {}), "training": facts.get("training", {}),
                            "audit": {int(k): {kk: v[kk] for kk in ("n", "clears", "verified")} for k, v in agg["sticky"].items()}, "bars": bars, "pointer_final": facts.get("pointer_final"),
                            "audit_n": facts.get("audit_n"), "unperturbed_n": facts.get("unperturbed_n"), "unperturbed": agg["unperturbed"], "tick0": agg["tick0"], "deterministic": agg["deterministic"]})
        out["rule_recomputed"] = {"outcome": rerun["outcome"], "D": rerun["D"], "R": rerun["R"], "recorded": {k: rule.get(k) for k in ("outcome", "D", "R")}}
        if rule.get("outcome") != "INVALID" and (rerun["outcome"], rerun["D"], rerun["R"]) != (rule.get("outcome"), rule.get("D"), rule.get("R")):
            problems.append(f"the rule recomputed from the records ({rerun['outcome']}, D {rerun['D']}, R {rerun['R']}) differs from the recorded ({rule.get('outcome')}, {rule.get('D')}, {rule.get('R')})")
        clears = [r for r in au_rows if r["clear"] and r["eval_kind"] == "audit_sticky"] + [r for r in t0_rows if r["clear"]]
        out["verification"] = {"replays": len(ver_rows), "inexact": inexact, "tier0_clears": len(clears), "tier0_without_replay": sum(1 for r in clears if r["episode"] not in verified)}
    out["problems"] = problems
    out["ok"] = not problems
    return out


def _median(xs: Sequence[float]) -> Optional[float]:
    s = sorted(xs)
    return None if not s else (s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2)


def full_report(root: Path) -> Dict[str, Any]:
    root = Path(root)
    sd = root / "session"
    out: Dict[str, Any] = {"report": REPORT_CONTRACT, "scope": G.SCOPE}
    for name in ("rule", "line", "open", "p1", "p2", "t0", "training_summary", "audit_run", "verification", "close", "tape_baseline", "final_state", "memory_summary"):
        p = sd / f"{name}.json"
        if p.is_file():
            d = _read(p)
            out[name] = {k: v for k, v in d.items() if k not in ("task", "created_utc", "scope", "lineages", "starts")} if name in ("p1", "p2", "open") else {k: v for k, v in d.items() if k not in ("task", "created_utc", "scope")}
    ver = {r["id"]: bool(r["exact"]) for r in _rows(root / "verification" / "replays.jsonl")}
    au = _rows(root / "audit" / "episodes.jsonl")
    out["audit"] = audit_rows(au, ver)
    tr = _rows(root / "training" / "episodes.jsonl")
    ro = _rows(root / "training" / "rollouts.jsonl")
    out["training"] = {"episodes": len(tr), "clears": sum(1 for r in tr if r["clear"]), "ends": {k: sum(1 for r in tr if r["end_reason"] == k) for k in sorted({r["end_reason"] for r in tr})}}
    if ro:
        last = ro[-1]
        ents = [r["update_metrics_of_the_previous_rollout"].get("entropy_loss") for r in ro if r["update_metrics_of_the_previous_rollout"].get("entropy_loss") is not None]
        out["training"].update({"rollouts": len(ro), "num_timesteps": last["num_timesteps"], "wall_s": last["wall_s"], "pointer_final": last["pointer"], "moves": last["moves"], "attempts": last["attempts"],
                                "median_transitions_per_s": _median([r["interval_transitions_per_s"] for r in ro]), "pause_s": last.get("pause_s"), "probe_ticks": last.get("probe_ticks"),
                                "ep_return_mean_recent_first_last": [ro[0]["ep_return_mean_recent"], last["ep_return_mean_recent"]],
                                "entropy_loss_first_min_last": [ents[0] if ents else None, min(ents) if ents else None, ents[-1] if ents else None],
                                "explained_variance_last": last["update_metrics_of_the_previous_rollout"].get("explained_variance"), "prefix_ticks": last["prefix_ticks"], "policy_ticks": last["policy_ticks"],
                                "staged": last["staged"], "wait_s": last["wait_s"], "withdrawn": last.get("withdrawn")})
    out["moves"] = _rows(root / "training" / "moves.jsonl")
    at = _rows(root / "training" / "attempts.jsonl")
    out["attempts"] = [{k: a.get(k) for k in ("n", "a", "pointer", "result", "new_pointer", "strip_clears", "strip_non_clears", "rechecks", "failed_landing", "held_after", "stalled_after", "wall_s",
                                              "withdrawn", "probe_episodes", "trigger", "num_timesteps")} | {"snapshot_sha256": (a.get("snapshot") or {}).get("sha256")} for a in at]
    out["attempt_results"] = {k: sum(1 for a in at if a["result"] == k) for k in F.RESULTS}
    out["windows"] = {k: sum(1 for w in _rows(root / "training" / "windows.jsonl") if w["event"] == k) for k in ("trigger", "void", "held_trigger")}
    hold: Dict[str, Dict[str, List[int]]] = {}
    for r in tr:
        if r["start"]["region"] == "strip" and r["start"]["pointer"] == r.get("pointer_now", r["start"]["pointer"]) and r.get("mid_hold") is not None:
            d = hold.setdefault(str(r["start"]["pointer"]), {"mid_hold": [0, 0], "at_change": [0, 0]})
            c = d["mid_hold" if r["mid_hold"] else "at_change"]
            c[0] += 1
            c[1] += int(r["clear"])
    out["handover_diagnostic"] = hold
    out["post_target8_share"] = post_target8_share(tr)
    cp = root / "training" / "checkpoints.json"
    if cp.is_file():
        d = _read(cp)
        out["checkpoint_digests"] = [{k: c.get(k) for k in ("checkpoint", "num_timesteps", "model_zip_sha256", "members_sha256", "curriculum_state_sha256", "wall_s", "pointer")} for c in (d.get("checkpoints") or [])] + \
            [{k: (d.get("final") or {}).get(k) for k in ("checkpoint", "num_timesteps", "model_zip_sha256", "members_sha256", "curriculum_state_sha256", "pointer")}]
    return out
