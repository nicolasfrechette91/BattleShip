#!/usr/bin/env python3
"""M7l tests: the target-2 reward experiment's registration, validators and driver (no learning claims).

Unit cases (no game):
    unit_route_rows          every real v3 / v3_t2 training row (M7j, M7k pilots) passes the route-aware
                             m7d_run.validate_episode_row; tampered records / returns / credits fail; every Phase K v2
                             row still passes unchanged; the evaluation summary carries the route record
    unit_rule                the registered rule's self-test (every gate and inclusive boundary) and the control's
                             registered values recomputed from runs/m7g_k
    unit_profiles            arm checks, the Phase K difference proof (reward + its flag only), no fixture / TAS path,
                             the M7g isolation pattern does not match any M7l file
    unit_equivalence         the M7k V1-V5 control-equivalence checks reproduce the M7k pilot verdicts (s0 identical,
                             s2 one credited target-2 break then divergence)
    unit_driver              launch-gate re-readings, the train plan's stop rules, the control-check refusal, the
                             directory plan, route/metric cross-check (stand-ins; nothing launched)
Game cases (fresh BattleShip processes, private directories below runs/m7l/_tests):
    game_route_evaluation    the M7k s2 pilot final checkpoint (v3_t2) evaluated under the Phase K settings (2 + 6
                             episodes): route rows verify, metrics clean, tick-0, record == metrics
    game_guarded_training    a 20,480-transition v3_t2 run through the M7h guard with the monitor validating route rows:
                             no hard alert, no monitor sample error, training verification passes

Usage: python rl/m7l_tests.py [unit|game|all|<case> ...]
Exit 0 all pass, 1 any failure.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List

RL_DIR = Path(__file__).resolve().parent
REPO_ROOT = RL_DIR.parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

TEST_ROOT = REPO_ROOT / "runs" / "m7l" / "_tests"
PILOT = {s: REPO_ROOT / "runs" / "m7k" / f"m7k_v3t2_pilot_s{s}_t0204800" for s in (0, 2)}


class CheckFailed(AssertionError):
    pass


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise CheckFailed(msg)


def rows(run_dir: Path) -> List[Dict[str, Any]]:
    return [json.loads(x) for x in (run_dir / "metrics" / "episodes.jsonl").read_text(encoding="utf-8").splitlines()
            if x.strip()]


# -- unit -------------------------------------------------------------------------------------------------------------


def unit_route_rows(out: Path) -> Dict[str, Any]:
    import m7d_run as dr
    from btt_rewards import REWARD_V2, REWARD_V3, REWARD_V3_T2

    counts = {}
    for name, rd, c in (("m7k_s0", PILOT[0], REWARD_V3_T2), ("m7k_s2", PILOT[2], REWARD_V3_T2),
                        ("m7j_s0", REPO_ROOT / "runs" / "m7j" / "m7j_v3_pilot_s0", REWARD_V3)):
        rr = rows(rd)
        bad = [x for r in rr for x in dr.validate_episode_row(r, c, 3600)]
        check(not bad, f"{name}: real route rows rejected: {bad[:3]}")
        counts[name] = len(rr)
    r = next(x for x in rows(PILOT[2]) if (x.get("reward_v3") or {}).get("moving_target"))
    for label, mutate in (("return", lambda t: t.__setitem__("return", t["return"] + 0.01)),
                          ("credit", lambda t: t["reward_v3"]["moving_target"].__setitem__("moving_target_term", 1.0)),
                          ("dropped credit", lambda t: t["reward_v3"].__setitem__("moving_target", None)),
                          ("no record", lambda t: t.pop("reward_v3")),
                          ("steps", lambda t: t["reward_v3"].__setitem__("steps", 3599)),
                          ("penalty", lambda t: t.__setitem__("failure_penalty_total", -5.0))):
        t = copy.deepcopy(r)
        mutate(t)
        check(bool(dr.validate_episode_row(t, REWARD_V3_T2, 3600)), f"tampered {label} accepted")
    check(bool(dr.validate_episode_row(r, REWARD_V3, 3600)), "a v3_t2 row accepted under v3")
    fall = next(x for x in rows(PILOT[2]) if x["end_reason"] == "fall")
    check(not dr.validate_episode_row(fall, REWARD_V3_T2, 3600), "a v3_t2 fall row rejected")
    v2 = rows(REPO_ROOT / "runs" / "m7g_k" / "m7g_s0_v1")
    check(sum(len(dr.validate_episode_row(x, REWARD_V2, 3600)) for x in v2) == 0, "Phase K v2 rows rejected")
    ev = {"rank": 0, "worker_episode": 9, "end_reason": r["end_reason"], "targets_broken": r["targets_broken"],
          "length": r["steps"], "raw_return": r["return"], "cleared": False, "termination_reason": None,
          "failure_penalty_terms": 0, "target_break_ticks": r["target_break_ticks"], "startup_mode": r["startup_mode"],
          "reward_v3": r["reward_v3"]}
    s = dr.eval_row_as_summary(ev, REWARD_V3_T2)
    check(s.get("reward_v3") == r["reward_v3"] and not dr.validate_episode_row(s, REWARD_V3_T2, 3600),
          "evaluation summary lost the route record")
    ev2 = dict(ev)
    ev2.pop("reward_v3")
    check("reward_v3" not in dr.eval_row_as_summary(ev2, REWARD_V2), "a v2 evaluation summary gained a key")
    return {"rows": counts, "phase_k_v2_rows": len(v2)}


def unit_rule(out: Path) -> Dict[str, Any]:
    import m7l_analysis as la
    import m7l_matrix as lm

    check(la.self_test() == 0, "rule self-test failed")
    ident = {s: lm.historical_identity(s) for s in (0, 1, 2)}
    bad = {s: h["problems"] for s, h in ident.items() if not h["ok"]}
    check(not bad, f"historical control identity: {bad}")
    return {s: {k: h[k] for k in ("final_digests", "rows_at_102400")} | {"t2": h["decision_inputs"]["t2"]}
            for s, h in ident.items()}


def unit_profiles(out: Path) -> Dict[str, Any]:
    import m7l_matrix as lm

    res = {}
    for spec in lm.matrix():
        exp = lm.load_run(spec)
        checks = lm.arm_checks(spec, exp)
        check(all(checks.values()), f"{spec.name}: {[k for k, v in checks.items() if not v]}")
        proof = lm.phase_k_proof(spec, exp)
        check(proof["ok"], f"{spec.name}: {proof}")
        res[spec.name] = proof["compatibility_differences"]
    # the fixture-isolation scan itself is rl/m7g_tests.py unit_training_isolation (run in the regression suite); here
    # only the registered forbidden-input list of the profiles
    files = sorted((RL_DIR / "configs" / "m7l").rglob("*.toml"))
    off = [p.name for p in files if lm.hm._forbidden_in(p.read_text(encoding="utf-8"))]
    check(not off, f"M7l profiles name a forbidden input: {off}")
    plan = lm.check_directory_plan()
    check(not plan["problems"], f"directory plan: {plan['problems']}")
    return {"differences": res, "files_scanned": len(files)}


def unit_equivalence(out: Path) -> Dict[str, Any]:
    import m7l_campaign as lc

    r0 = lc.control_equivalence(PILOT[0], 0, total=204_800)
    check(r0["ok"] and r0["final_equals_control"] and not r0["target2_training_events"]
          and r0["rows_action_identical_to_control"] == r0["rows"] == 63, f"s0: {r0}")
    r2 = lc.control_equivalence(PILOT[2], 2, total=204_800)
    ev = r2["target2_training_events"]
    check(r2["ok"] and len(ev) == 1 and ev[0]["consumed_tick"] == 2055 and ev[0]["global_transitions"] == 123_085
          and r2["first_action_divergence"]["sb3_num_timesteps_at_end"] == 128_000 and not r2["final_equals_control"],
          f"s2: {r2}")
    return {"s0": {k: r0[k] for k in ("rows", "rows_action_identical_to_control")},
            "s2": {k: r2[k] for k in ("rows", "rows_action_identical_to_control", "first_target2_rollout_end")}}


def unit_driver(out: Path) -> Dict[str, Any]:
    import m7l_campaign as lc
    import m7l_matrix as lm

    saved = (lc.GATE_FN, lc.SLEEP)
    root = out / "driver_root"
    try:
        seq = iter([{"ok": False, "problems": ["available physical 3.9 GiB < 4.0 GiB"], "measurement": {}},
                    {"ok": True, "problems": [], "measurement": {}}])
        slept: List[float] = []
        lc.GATE_FN, lc.SLEEP = (lambda: next(seq)), slept.append
        g = lc.wait_for_launch_gate("t")
        check(g["ok"] and len(g["readings"]) == 2 and slept == [lm.LAUNCH_GATE_RETRY_S], f"gate retry {g}")
        lc.GATE_FN = lambda: {"ok": False, "problems": ["x"], "measurement": {}}
        slept.clear()
        g = lc.wait_for_launch_gate("t")
        check(not g["ok"] and len(g["readings"]) == lm.LAUNCH_GATE_READINGS and len(slept) == lm.LAUNCH_GATE_READINGS - 1,
              f"gate refusal {g}")
        lm.configure_root(root)
        st = lc.load_state()
        plan = lc.train_plan(lm.matrix(), st)
        check([p["action"].split()[0] for p in plan] == ["train", "wait", "wait"], f"plan {plan}")
        spec = lm.matrix()[0]
        spec.run_dir.mkdir(parents=True)
        plan = lc.train_plan(lm.matrix(), st)
        check(plan[0]["action"].startswith("STOP"), f"a partial directory must stop the campaign: {plan}")
        st["runs"] = {spec.name: {"status": "verified"}, lm.matrix()[1].name: {"status": "stopped"}}
        plan = lc.train_plan(lm.matrix(), st)
        check(plan[0]["action"] == "skip" and plan[1]["action"].startswith("STOP"), f"stopped run relaunched: {plan}")
        man = {"code": {"sha256": "x"}, "executable": {"sha256": "y"}, "revisions": {}, "decision_rule": {"sha256": "z"},
               "historical_control": {"seeds": {}}}
        p = lc.control_check_problems(man)
        check(any("has not run" in x for x in p), f"missing control check accepted: {p}")
        res = {"modes": {"stochastic": {"episodes": [
            {"episode_id": "a", "reward_v3": {"moving_target": {"consumed_tick": 7}, "broken_ids": [2]},
             "eval_metrics": {"moving_target_break_tick": 7, "broken_ids": [2]}},
            {"episode_id": "b", "reward_v3": {"moving_target": None, "broken_ids": [2]},
             "eval_metrics": {"moving_target_break_tick": 7, "broken_ids": [2]}}]}}}
        rp = lc.route_metric_problems(res)
        check(len(rp) == 1 and " b:" in rp[0], f"route/metric cross-check {rp}")
    finally:
        lc.GATE_FN, lc.SLEEP = saved
        lm.configure_root(None)
    return {"ok": True}


# -- game -------------------------------------------------------------------------------------------------------------


def game_route_evaluation(out: Path) -> Dict[str, Any]:
    import experiment_config as ec
    import m7_evaluation as ev
    import m7_trainer as tr
    import m7d_run as dr
    import m7g_k_run as kr
    import m7h_verify as mv
    import m7l_campaign as lc
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    exp = ec.load_experiment(PILOT[2] / "experiment.toml")
    cfg = tr.config_from_experiment(exp)
    dest = out / "route_eval"
    res = ev.evaluate_checkpoint(PILOT[2] / "final", dest, settings=kr.phase_k_settings(exp), deterministic_episodes=2,
                                 stochastic_episodes=6, expected_contracts=tr.run_contracts(cfg), label="final",
                                 preserve_all=True)
    plan = {"deterministic_episodes": 2, "stochastic_episodes": 6}
    ver = dr.verify_evaluation(res, exp.reward, 3600, plan)
    check(ver["ok"], f"route evaluation rows: {ver['problems'][:3]}")
    mp = kr.verify_metrics(res, arm=None)
    check(not mp, f"metrics: {mp[:3]}")
    rp = lc.route_metric_problems(res)
    check(not rp, f"record vs metrics: {rp}")
    t0 = mv.verify_eval_tick0(dest)
    check(t0["ok"], f"tick-0: {t0['problems'][:3]}")
    flags = {m: r.get("extra_env") for m, r in res["modes"].items()}
    check(all(f == {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1", "SSB64_RL_TARGET_DIAG": "1"}
              for f in flags.values()), f"flags {flags}")
    eps = [e for r in res["modes"].values() for e in r["episodes"]]
    return {"episodes": len(eps), "returns": [round(e["raw_return"], 4) for e in eps],
            "t2": sum(1 for e in eps if e["eval_metrics"]["moving_target_broken"])}


def game_guarded_training(out: Path) -> Dict[str, Any]:
    import experiment_config as ec
    import m7d_run as dr
    import m7h_guard as g
    import m7l_matrix as lm

    base = ec.load_experiment(lm.CONFIG_DIR / "m7l_t2_s0.toml")
    name = "m7l_test_guarded_t2"
    values = dict(base.values, **{"run.name": name, "run.total_transitions": 20_480, "run.mode": "pilot",
                                  "run.output_root": str(out), "checkpoint.interval": 10_240})
    cfg = out / f"{name}.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(ec.to_toml_text(values, header="derived by rl/m7l_tests.py (game_guarded_training): run fields and "
                                                  "a 20,480-transition budget only"), encoding="utf-8", newline="\n")
    exp = ec.load_experiment(cfg)
    import m7l_campaign as lc

    gate = lc.wait_for_launch_gate("game_guarded_training")      # the registered gate with its re-readings
    check(gate["ok"], f"launch gate {gate['problems']}")
    res = g.train_guarded(config=cfg, run_dir=out / name, log_path=out / "guard" / f"{name}.log",
                          monitor_path=out / "guard" / f"{name}_monitor.jsonl", probe_path=out / "guard" / f"{name}_probe.jsonl",
                          contract=exp.reward, horizon=3600, partial_root=out / "_partial", output_root=out)
    mon = res["monitor"]
    check(res["exit_code"] == 0 and res["stop_kind"] is None, f"guarded run {res.get('exit_code')} {res.get('stop_kind')}")
    check(not mon["hard_alerts"], f"hard alerts {mon['hard_alerts']}")
    errs = [x for x in mon["soft_alerts"] if "monitor sample error" in x]
    check(not errs, f"monitor sample errors {errs[:2]}")
    check(mon["episodes_seen"] > 0, "the monitor saw no episode row")
    ver = dr.verify_training_run(out / name, exp, fresh=True)
    check(ver["ok"], f"training verification {ver['problems'][:3]}")
    rr = rows(out / name)
    check(all(r.get("reward_v3", {}).get("reward_contract") == "btt_reward_v3_t2" for r in rr), "rows without v3_t2 record")
    return {"episodes": len(rr), "monitor_episodes": mon["episodes_seen"], "leftover": res["leftover_battleship_pids"],
            "t2": sum(1 for r in rr if r["reward_v3"].get("moving_target"))}


UNIT: Dict[str, Callable[[Path], Dict[str, Any]]] = {
    "unit_route_rows": unit_route_rows, "unit_rule": unit_rule, "unit_profiles": unit_profiles,
    "unit_equivalence": unit_equivalence, "unit_driver": unit_driver}
GAME: Dict[str, Callable[[Path], Dict[str, Any]]] = {
    "game_route_evaluation": game_route_evaluation, "game_guarded_training": game_guarded_training}


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cases", nargs="*", default=["unit"])
    a = ap.parse_args(argv)
    names: List[str] = []
    for c in a.cases:
        names += list(UNIT) if c in ("unit", "all") else []
        names += list(GAME) if c in ("game", "all") else []
        names += [c] if c in UNIT or c in GAME else []
    out = TEST_ROOT / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out.mkdir(parents=True, exist_ok=False)
    results: Dict[str, Any] = {}
    for n in names:
        t0 = time.perf_counter()
        try:
            detail = {**UNIT, **GAME}[n](out)
            results[n] = {"ok": True, "detail": detail}
        except Exception as exc:  # noqa: BLE001
            results[n] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-2000:]}
        results[n]["wall_s"] = round(time.perf_counter() - t0, 1)
        print(f"[{'PASS' if results[n]['ok'] else 'FAIL'}] {n} ({results[n]['wall_s']} s) "
              f"{results[n].get('detail') if results[n]['ok'] else results[n]['error']}", flush=True)
    (out / "results.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    ok = all(r["ok"] for r in results.values())
    print(f"{sum(r['ok'] for r in results.values())}/{len(results)} passed -> {out.relative_to(REPO_ROOT)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
