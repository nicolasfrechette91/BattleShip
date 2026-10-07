"""M9-g3: the read-only post-run verification (`verify_run`) and the reported readings (`full_report`) of a recorded g3 session. Pure file readers over
`runs/m9_g3/s<k>/` (zero native ticks).

`verify_run` re-derives: every training, probe, drift and audit record's sticky mask from its keys and its words digest from the registered prefix and the
submitted words (g2's `check_records`, unchanged); every training start from its keys; the pointer, window, deferred-trigger, spacing and attempt history
from the records alone (rl/m9_g3_frontier.replay_history: an attempt inside its spacing and a move without a passing strip test and every re-check are
named); every checkpoint's pinned digests and g3 identity; the reused tape table (its content digest, the file digest recorded at the open, the drift
rows against the table); D, R and the s1 rule from the records; the metadata audit.

`full_report` adds the g3 readings (decision 8): the trigger-to-test gap per attempt, the attempt yield, the replenishment schedule as it ran, the deferred
triggers, the pointer over training time, the throughput by pointer, the per-landing clears against the reused tape, the entropy and calibration readings.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import m9_artifacts as A
import m9_contract as C
import m9_g2_report as RPT2
import m9_g2_tape as TP
import m9_g3_contract as G
import m9_g3_frontier as F
import m9_g3_rule as R

REPORT_CONTRACT = "m9_g3_report_v1"
check_records = RPT2.check_records
audit_rows = RPT2.audit_rows
post_target8_share = RPT2.post_target8_share
tables_of = RPT2.tables_of
sha256_file = RPT2.sha256_file


def _read(p: Path) -> Any:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _rows(p: Path) -> List[Dict[str, Any]]:
    return A.read_jsonl(p)


def _median(xs: Sequence[float]) -> Optional[float]:
    s = sorted(xs)
    return None if not s else (s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2)


def verify_run(root: Path) -> Dict[str, Any]:
    root = Path(root)
    problems: List[str] = []
    out: Dict[str, Any] = {"root": str(root), "report": REPORT_CONTRACT}
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
    # checkpoints: pins and the g3 identity
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
            cs = _read(d / "curriculum_state.json")
            if cs.get("frontier_rule") != G.FRONTIER_RULE_ID or cs.get("line_contract_sha256") != G.line_contract_digest():
                problems.append(f"checkpoint {d.name}: the curriculum state does not carry the g3 frontier rule and line contract")
            if "since_failed" not in dict(cs.get("carried") or {}):
                problems.append(f"checkpoint {d.name}: the carried state has no spacing counter")
            n_cp += 1
    out["checkpoints"] = n_cp
    tr_rows = _rows(root / "training" / "episodes.jsonl")
    pr_rows = _rows(root / "training" / "probes.jsonl")
    dr_rows = _rows(root / "t0" / "drift.jsonl")
    au_rows = _rows(root / "audit" / "episodes.jsonl")
    at_rows = _rows(root / "training" / "attempts.jsonl")
    summ = _read(sd / "training_summary.json") if (sd / "training_summary.json").is_file() else None
    opn = _read(sd / "open.json") if (sd / "open.json").is_file() else {}
    session_k = int(opn.get("session", 1))
    if tables:
        for name, rows in (("training", tr_rows), ("probes", pr_rows), ("drift", dr_rows), ("audit", au_rows)):
            ps = check_records(rows, tables)
            out[f"{name}_records"] = {"episodes": len(rows), "problems": ps[:5]}
            problems += [f"{name}: {p}" for p in ps[:5]]
        lengths = {n: len(t.words) for n, t in tables.items()}
        carried = (opn.get("resume") or {}).get("carried_state")
        rep = F.replay_history(tr_rows, at_rows, lengths, session=session_k, state=carried)
        moves_logged = [(m["from"], m["to"]) for m in _rows(root / "training" / "moves.jsonl")]
        same = rep["moves"] == moves_logged
        out["frontier_replay"] = {"pointer": rep["pointer"], "moves": len(rep["moves"]), "logged_moves": len(moves_logged), "equal_to_log": same, "attempts": rep["attempts"],
                                  "deferred_triggers": rep["deferred_triggers"], "schedule": rep["schedule"], "problems": rep["problems"][:5]}
        if not same:
            problems.append("the move history rebuilt from the records differs from the logged one")
        problems += [f"frontier replay: {p}" for p in rep["problems"][:5]]
        if summ is not None and summ.get("pointer_final") != rep["pointer"]:
            problems.append(f"the final pointer {summ.get('pointer_final')} differs from the rebuilt {rep['pointer']}")
        if summ is not None and (summ.get("spacing_final") or {}).get("have") != rep["state"]["spacing"]["have"]:
            problems.append("the final spacing counter differs from the rebuilt")
        deferred_logged = sum(1 for w in _rows(root / "training" / "windows.jsonl") if w.get("event") == "deferred_trigger")
        if deferred_logged != rep["deferred_triggers"]:
            problems.append(f"{deferred_logged} deferred triggers logged, {rep['deferred_triggers']} rebuilt")
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
        for r in au_rows:
            if r.get("eval_kind") == "audit_sticky" and r.get("label") != G.reach_label(int(r["landing"]), int(r["k"])):
                problems.append(f"{r['episode']}: the audit label is not the reused tape's family")
                break
    # verification and the reused tape
    ver_rows = _rows(root / "verification" / "replays.jsonl")
    verified = {r["id"]: bool(r["exact"]) for r in ver_rows}
    inexact = [i for i, ok in verified.items() if not ok]
    if inexact:
        problems.append(f"inexact replays: {inexact[:5]}")
    tape_p = root / "input" / "tape_baseline.json"
    tape_pin = _read(tape_p) if tape_p.is_file() else None
    if tape_pin is None:
        problems.append("no reused tape table under input/")
    else:
        reuse = dict(opn.get("tape_reuse") or {})
        if TP.table_digest(tape_pin) != tape_pin.get("sha256"):
            problems.append("the reused tape table's digest differs from its content")
        if reuse and sha256_file(tape_p) != reuse.get("file_sha256"):
            problems.append("the reused tape table's file digest differs from the one recorded at the open")
        if not tape_pin.get("pinned"):
            problems.append("the reused tape table is not pinned")
        exp = dict((tape_pin.get("landings") or {}).get(str(G.DRIFT_LANDING), {}).get("outcomes") or {})
        for r in dr_rows:
            got = "c" if r["clear"] else str(r["end_reason"])[0]
            if exp.get(str(int(r["k"]))) != got:
                problems.append(f"drift key {r['k']}: outcome {got} differs from the table's {exp.get(str(int(r['k'])))}")
        out["tape"] = {"sha256": tape_pin.get("sha256"), "file_sha256": sha256_file(tape_p), "equals_registered_reuse": sha256_file(tape_p) == G.TAPE_REUSE["file_sha256"] and tape_pin.get("sha256") == G.TAPE_REUSE["content_sha256"],
                       "bars": {k: v.get("B") for k, v in dict(tape_pin["landings"]).items()}, "pinned": tape_pin.get("pinned"), "drift_episodes": len(dr_rows)}
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
        clears = [r for r in au_rows if r["clear"] and r["eval_kind"] == "audit_sticky"]
        out["verification"] = {"replays": len(ver_rows), "inexact": inexact, "tier0_clears": len(clears), "tier0_without_replay": sum(1 for r in clears if r["episode"] not in verified)}
        ln = _read(sd / "line.json") if (sd / "line.json").is_file() else None
        if ln is not None:
            again = R.apply_line(list(ln.get("sessions") or []))
            out["line_recomputed"] = {"outcome": again["outcome"], "recorded": ln.get("outcome")}
            if again["outcome"] != ln.get("outcome"):
                problems.append(f"the line rule recomputed ({again['outcome']}) differs from the recorded ({ln.get('outcome')})")
    out["problems"] = problems
    out["ok"] = not problems
    return out


def gap_readings(tr_rows: Sequence[Mapping[str, Any]], at_rows: Sequence[Mapping[str, Any]], window: int = 60) -> List[Dict[str, Any]]:
    """The trigger-to-test gap per attempt (decision 8, reported only): the trigger window's displayed rate, the live rate over the preceding `window` counted
    strip outcomes at that pointer (completion order, before the attempt), the frozen test's rate, and the spacing state."""
    out: List[Dict[str, Any]] = []
    for a in at_rows:
        p = int(a["pointer"])
        before = int(a["episodes_before"])
        prior = [r for r in tr_rows[:before] if r["start"]["region"] == "strip" and int(r["start"]["pointer"]) == p and r["end_reason"] in ("clear", "fall", "horizon", "ended")]
        live = prior[-window:]
        trig = dict(a.get("trigger") or {})
        tn = int(trig.get("clears", 0)) + int(trig.get("non_clears", 0))
        sn = int(a.get("strip_clears", 0)) + int(a.get("strip_non_clears", 0))
        out.append({"n": int(a["n"]), "pointer": p, "a": int(a["a"]), "result": a["result"], "spacing": a.get("spacing"),
                    "window_rate": round(int(trig.get("clears", 0)) / tn, 3) if tn else None, "window": f"{trig.get('clears')} of {tn}",
                    "live_rate_before": round(sum(1 for r in live if r["clear"]) / len(live), 3) if live else None, "live_n": len(live),
                    "test_rate": round(int(a.get("strip_clears", 0)) / sn, 3) if sn else None, "test": f"{a.get('strip_clears')} of {sn}",
                    "gap_window_minus_test": round(int(trig.get("clears", 0)) / tn - int(a.get("strip_clears", 0)) / sn, 3) if (tn and sn) else None,
                    "strip_calibration_gap": (dict(a.get("runs", [{}])[0] if a.get("runs") else {}).get("tests") or {}).get("strip", {}).get("calibration_gap")})
    return out


def full_report(root: Path) -> Dict[str, Any]:
    root = Path(root)
    sd = root / "session"
    out: Dict[str, Any] = {"report": REPORT_CONTRACT, "scope": G.SCOPE, "gate": G.GATE}
    for name in ("rule", "line", "open", "p1", "p2", "t0", "training_summary", "audit_run", "verification", "close", "final_state", "memory_summary"):
        p = sd / f"{name}.json"
        if p.is_file():
            d = _read(p)
            out[name] = {k: v for k, v in d.items() if k not in ("task", "created_utc", "scope", "lineages", "starts")} if name in ("p1", "p2", "open") else {k: v for k, v in d.items() if k not in ("task", "created_utc", "scope")}
    tape_p = root / "input" / "tape_baseline.json"
    if tape_p.is_file():
        tb = _read(tape_p)
        out["tape_baseline"] = {"sha256": tb.get("sha256"), "file_sha256": sha256_file(tape_p), "landings": {k: {kk: v.get(kk) for kk in ("keys", "clears_verified", "p_hat", "B", "pinned")} for k, v in dict(tb["landings"]).items()}}
    ver = {r["id"]: bool(r["exact"]) for r in _rows(root / "verification" / "replays.jsonl")}
    au = _rows(root / "audit" / "episodes.jsonl")
    out["audit"] = audit_rows(au, ver)
    bars = {k: v.get("B") for k, v in dict(out.get("tape_baseline", {}).get("landings") or {}).items()}
    p_hat = {k: v.get("p_hat") for k, v in dict(out.get("tape_baseline", {}).get("landings") or {}).items()}
    out["per_landing_against_tape"] = {str(lam): {"sticky_verified": v["verified"], "sticky_claimed": v["clears"], "n": v["n"], "tape_p_hat": p_hat.get(str(lam)), "tape_expected_of_20": round(20 * float(p_hat[str(lam)]), 1) if p_hat.get(str(lam)) is not None else None,
                                                  "B": bars.get(str(lam)), "meets_D_bar": v["verified"] >= G.D_MIN_CLEARS, "meets_R_bar": (bars.get(str(lam)) is not None and v["verified"] >= bars[str(lam)]),
                                                  "ends": v["ends"], "calibration_gap": v.get("calibration_gap"), "start_entropy": v.get("start_entropy")}
                                      for lam, v in sorted(out["audit"]["sticky"].items(), reverse=True)}
    tr = _rows(root / "training" / "episodes.jsonl")
    ro = _rows(root / "training" / "rollouts.jsonl")
    out["training"] = {"episodes": len(tr), "clears": sum(1 for r in tr if r["clear"]), "ends": {k: sum(1 for r in tr if r["end_reason"] == k) for k in sorted({r["end_reason"] for r in tr})}}
    if ro:
        last = ro[-1]
        ents = [r["update_metrics_of_the_previous_rollout"].get("entropy_loss") for r in ro if r["update_metrics_of_the_previous_rollout"].get("entropy_loss") is not None]
        evs = [r["update_metrics_of_the_previous_rollout"].get("explained_variance") for r in ro if r["update_metrics_of_the_previous_rollout"].get("explained_variance") is not None]
        kls = [r["update_metrics_of_the_previous_rollout"].get("approx_kl") for r in ro if r["update_metrics_of_the_previous_rollout"].get("approx_kl") is not None]
        out["training"].update({"rollouts": len(ro), "num_timesteps": last["num_timesteps"], "wall_s": last["wall_s"], "pointer_final": last["pointer"], "moves": last["moves"], "attempts": last["attempts"],
                                "median_transitions_per_s": _median([r["interval_transitions_per_s"] for r in ro]), "pause_s": last.get("pause_s"), "probe_ticks": last.get("probe_ticks"),
                                "ep_return_mean_recent_first_last": [ro[0]["ep_return_mean_recent"], last["ep_return_mean_recent"]],
                                "entropy_loss_first_min_last": [ents[0] if ents else None, min(ents) if ents else None, ents[-1] if ents else None],
                                "entropy_fraction_of_max_first_min_last": [round(-e / 4.2767, 4) for e in (ents[0], min(ents), ents[-1])] if ents else None,
                                "explained_variance_first_last": [evs[0] if evs else None, evs[-1] if evs else None], "approx_kl_median": _median(kls) if kls else None,
                                "prefix_ticks": last["prefix_ticks"], "policy_ticks": last["policy_ticks"], "staged": last["staged"], "wait_s": last["wait_s"], "withdrawn": last.get("withdrawn"),
                                "deferred_triggers": last.get("deferred_triggers"), "spacing_final": last.get("spacing")})
        out["pointer_over_time"] = [{"wall_s": r["wall_s"], "num_timesteps": r["num_timesteps"], "pointer": r["pointer"], "spacing": r.get("spacing"), "transitions_per_s": r["interval_transitions_per_s"]} for r in ro]
        by_ptr: Dict[int, List[float]] = {}
        for r in ro:
            by_ptr.setdefault(int(r["pointer"]), []).append(float(r["interval_transitions_per_s"]))
        out["throughput_by_pointer"] = {str(p): {"rollouts": len(v), "median_transitions_per_s": _median(v), "min": min(v), "max": max(v)} for p, v in sorted(by_ptr.items(), reverse=True)}
    out["moves"] = _rows(root / "training" / "moves.jsonl")
    at = _rows(root / "training" / "attempts.jsonl")
    out["attempts"] = [{k: a.get(k) for k in ("n", "a", "pointer", "result", "new_pointer", "strip_clears", "strip_non_clears", "rechecks", "failed_landing", "spacing", "spacing_after", "wall_s",
                                              "withdrawn", "probe_episodes", "trigger", "num_timesteps", "episodes_before")} | {"snapshot_sha256": (a.get("snapshot") or {}).get("sha256")} for a in at]
    out["attempt_results"] = {k: sum(1 for a in at if a["result"] == k) for k in F.RESULTS}
    decided = sum(1 for a in at if a["result"] != "INTERRUPTED")
    out["attempt_yield"] = {"attempts": len(at), "decided": decided, "moves": sum(1 for a in at if a["result"] == "MOVED"), "moves_per_decided_attempt": round(sum(1 for a in at if a["result"] == "MOVED") / decided, 3) if decided else None,
                            "per_pointer": {str(p): {"attempts": sum(1 for a in at if int(a["pointer"]) == p), "failed": sum(1 for a in at if int(a["pointer"]) == p and a["result"] in F.FAILED_RESULTS),
                                                     "moved": any(int(a["pointer"]) == p and a["result"] == "MOVED" for a in at)} for p in sorted({int(a["pointer"]) for a in at}, reverse=True)}}
    out["replenishment_schedule"] = [{"n": a["n"], "pointer": a["pointer"], "a": a["a"], "f": (a.get("spacing") or {}).get("f"), "need": (a.get("spacing") or {}).get("need"), "have": (a.get("spacing") or {}).get("have"),
                                      "result": a["result"], "f_after": (a.get("spacing_after") or {}).get("f"), "need_after": (a.get("spacing_after") or {}).get("need")} for a in at]
    wins = _rows(root / "training" / "windows.jsonl")
    out["windows"] = {k: sum(1 for w in wins if w["event"] == k) for k in ("trigger", "deferred_trigger", "void")}
    out["deferred_triggers"] = [{"t_wall_s": w.get("t_wall_s"), "pointer": w.get("pointer"), "clears": w.get("clears"), "size": w.get("size"), "spacing": w.get("spacing")} for w in wins if w["event"] == "deferred_trigger"]
    out["trigger_to_test_gap"] = gap_readings(tr, at)
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
        out["checkpoint_digests"] = [{k: c.get(k) for k in ("checkpoint", "num_timesteps", "model_zip_sha256", "members_sha256", "curriculum_state_sha256", "wall_s", "pointer", "spacing")} for c in (d.get("checkpoints") or [])] + \
            [{k: (d.get("final") or {}).get(k) for k in ("checkpoint", "num_timesteps", "model_zip_sha256", "members_sha256", "curriculum_state_sha256", "pointer", "spacing")}]
    return out
