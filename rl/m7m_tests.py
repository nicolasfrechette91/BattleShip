#!/usr/bin/env python3
"""M7m tests: the anchored backward curriculum's registration, schedule, opt-in config and warm start (no learning).

Unit cases (no game):
    unit_anchor              the pure module's self-test; the registered anchor, plan and F1 table load and agree with
                             the code (digest, breaks, masks, plan); a tampered anchor or table is refused
    unit_schedule            windows, clipping, draws inside the window, stale / excluded outcomes, block moves,
                             completion and the tick-0 transition; K (p0 = 1) never anchors; state is JSON-serialisable
    unit_config_optin        every M7m profile validates; E and K differ only in name / notes / tick0_probability; the
                             table derives the diagnostic flag; missing keys, other values, run.mode = train, reward v3,
                             observation v2 and [curriculum] + [anchor_curriculum] are refused; a profile without the
                             table resolves exactly as before (all 46 pre-M7m profiles, recorded baseline)
    unit_warm_start          M7Run._source_checkpoint on the real Phase K finals accepts exactly the diagnostic-flag
                             difference (recorded) with 1,536,000 additional transitions; a curriculum-trained source
                             (M7h), any other extra_env difference and a table-less diag-flag resume are refused
Game case (fresh BattleShip processes below runs/m7m/_tests; frozen actions, no PPO, no learning):
    game_vec_anchor          AnchorVecEnv over two AnchorWorkerWrapper workers (standby lifecycle), neutral actions:
                             anchored starts are delivered equal to the table, rewards / dones pass through untouched,
                             every finished row validates under the prefix-aware m7d validator, policy steps + prefix
                             rows = rows, and the vector steps seen for an anchored episode equal its policy steps only

Usage: python rl/m7m_tests.py [unit|game|all|<case> ...]
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

import m7m_anchor as ma  # noqa: E402

TEST_ROOT = REPO_ROOT / "runs" / "m7m" / "_tests"
PROFILES = sorted((REPO_ROOT / "rl" / "configs" / "m7m").glob("*.toml"))
BASELINE_NOTE = "profile identities recorded before the M7m edits (scratchpad baseline, 46 profiles, byte-identical after)"


class CheckFailed(AssertionError):
    pass


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise CheckFailed(msg)


def refused(fn: Callable[[], Any], exc: Any = Exception) -> bool:
    try:
        fn()
    except exc:
        return True
    return False


def table_sha() -> str:
    import experiment_config as ec

    return ec.load_experiment(PROFILES[0]).anchor_curriculum["observation_table_sha256"]


# -- unit ----------------------------------------------------------------------------------------------------------------


def unit_anchor(out: Path) -> Dict[str, Any]:  # noqa: ARG001
    check(ma.self_test() == 0, "m7m_anchor self-test")
    a = ma.load_anchor()
    check(a.native_digest == ma.ANCHOR_NATIVE_DIGEST and len(a.actions) == ma.ANCHOR_ROWS, "anchor identity")
    check(a.record["source"]["reward_contract"] == "btt_reward_v3_t2" and "start states ONLY" in a.record["permitted_use"],
          "anchor provenance / permitted use")
    plan = json.loads((REPO_ROOT / "docs" / "rl_sweep_consolidation_m7m_feasibility_plan.json").read_text(encoding="utf-8"))
    check(plan["plan"] == json.loads(json.dumps(ma.registered_plan())), "registered plan == code")
    t = ma.load_observation_table(table_sha())
    check(len(t) == ma.MAX_CUT and all(t[x - 1]["broken_mask"] == ma.broken_mask_at(x) for x in range(1, ma.MAX_CUT + 1)),
          "table masks")
    check(t[0]["input_tick"] == 1 and t[ma.MAX_CUT - 1]["input_tick"] == ma.MAX_CUT, "table rows = o_tau (input tick tau)")
    bad = copy.deepcopy(a.record)
    h = bytearray(bytes.fromhex(bad["trajectory"]["track1_actions_hex"]))
    h[500] = (h[500] + 1) % 72
    bad["trajectory"]["track1_actions_hex"] = bytes(h).hex()
    check(refused(lambda: ma.anchor_from_record(bad), ma.AnchorError), "a tampered anchor was accepted")
    check(refused(lambda: ma.load_observation_table("0" * 64), ma.AnchorError), "a wrong table sha was accepted")
    check(refused(lambda: a.prefix(0), ma.AnchorError) and refused(lambda: a.prefix(1021), ma.AnchorError),
          "cuts outside 1..1020 accepted")
    return {"anchor": a.native_digest[:16], "table_rows": len(t)}


def unit_schedule(out: Path) -> Dict[str, Any]:  # noqa: ARG001
    s = ma.AnchorSchedule(7, tick0_probability=ma.TICK0_PROBABILITY_E)
    kinds = {}
    for _ in range(2000):
        kind, tau, k, _d = s.draw()
        kinds[kind] = kinds.get(kind, 0) + 1
        if kind == ma.START_ANCHOR:
            check(k == 0 and 901 <= tau <= 1020, f"draw {tau} outside W0")
    check(800 < kinds.get(ma.START_ANCHOR, 0) < 1200, f"draw balance {kinds}")
    moves = []
    for k in range(len(ma.WINDOWS)):
        lo, hi = ma.WINDOWS[k][1:]
        for i in range(10):                                   # one failing block first
            s.ingest(ma.Outcome(ma.START_ANCHOR, hi, k, i < 4, "horizon", True))
        check(s.k == k and not s.complete, f"failed block moved W{k}")
        s.ingest(ma.Outcome(ma.START_ANCHOR, hi, max(0, k - 1) if k else 99, True, "horizon", True))   # stale
        for i in range(10):
            s.ingest(ma.Outcome(ma.START_ANCHOR, lo, k, i < 5, "fall", True))
        moves.append(s.pointer())
        if not s.complete:
            kind, tau, kk, _d = s.draw()
            while kind != ma.START_ANCHOR:
                kind, tau, kk, _d = s.draw()
            check(kk == k + 1 and ma.WINDOWS[k + 1][1] <= tau <= ma.WINDOWS[k + 1][2], "draw after a move")
    check(s.complete and moves[-1] is None and s.counts["stale"] == len(ma.WINDOWS), f"completion {moves} {s.counts}")
    check(all(s.draw()[0] in (ma.START_TICK0, ma.START_TICK0_COMPLETE) for _ in range(200)), "tick-0 transition")
    json.dumps(s.state_json())
    k = ma.AnchorSchedule(7, tick0_probability=ma.TICK0_PROBABILITY_K)
    check(all(k.draw()[0] == ma.START_TICK0 for _ in range(5000)), "K anchored")
    check(refused(lambda: ma.AnchorSchedule(1, tick0_probability=0.3), ma.AnchorError), "unregistered p0 accepted")
    return {"pointer_sequence": moves, "counts": s.counts}


def unit_config_optin(out: Path) -> Dict[str, Any]:
    import experiment_config as ec

    check(len(PROFILES) == 6, f"{len(PROFILES)} M7m profiles")
    exps = {p.stem: ec.load_experiment(p) for p in PROFILES}
    for name, exp in exps.items():
        check(exp.mode == "resume" and exp.anchor_curriculum is not None, f"{name}: mode / table")
        check(dict(exp.extra_env).get("SSB64_RL_TARGET_DIAG") == "1", f"{name}: diag flag not derived")
        ma.check_table(exp.anchor_curriculum)
        check(exp.reward.contract == "btt_reward_v2" and exp.values["contracts.observation"] == "btt_policy_obs_v1",
              f"{name}: reward / observation")
    for j in range(3):
        e, k = exps[f"m7m_e_s{j}"], exps[f"m7m_k_s{j}"]
        diff = {p for p in set(e.values) | set(k.values) if e.values.get(p) != k.values.get(p)}
        check(diff == {"run.name", "run.notes", "anchor_curriculum.tick0_probability"}, f"pair {j}: {diff}")
        check(e.values["run.base_seed"] == k.values["run.base_seed"] == 100 + j, f"pair {j}: seeds")
        pk = ec.load_experiment(REPO_ROOT / "rl" / "configs" / "m7g" / f"m7g_s{j}_v1.toml")
        d2 = {p for p in set(e.values) | set(pk.values) if e.values.get(p) != pk.values.get(p)}
        check(all(p.startswith(("run.", "resume.source_checkpoint", "anchor_curriculum.")) for p in d2),
              f"pair {j} vs Phase K: {sorted(d2)}")
    src = PROFILES[0].read_text(encoding="utf-8")

    def problems_of(text: str) -> List[str]:
        p = out / "variant.toml"
        p.write_text(text, encoding="utf-8")
        try:
            ec.load_experiment(p)
            return []
        except ec.ConfigError as exc:
            return [str(exc)]

    variants = {
        "missing key": src.replace("block_successes = 5\n", ""),
        "other window": src.replace("window = 120\n", "window = 100\n"),
        "p0 0.3": src.replace("tick0_probability = 0.5", "tick0_probability = 0.3"),
        "mode train": src.replace('mode = "resume"', 'mode = "train"').replace(
            'source_checkpoint = "runs/m7g_k/m7g_s0_v1/final"', 'source_checkpoint = ""'),
        "reward v3": src.replace('reward = "btt_reward_v2"', 'reward = "btt_reward_v3"'),
        "with curriculum": src + ('\n[curriculum]\ncontract = "btt_curriculum_frontier_v1"\ntick0_probability = 0.5\n'
                                  'max_prefix_ticks = 3000\npre_fall_exclusion_ticks = 60\ncell_size = 300\n'),
        "empty table": src[:src.index("[anchor_curriculum]")] + "[anchor_curriculum]\n",
    }
    res = {k: problems_of(v) for k, v in variants.items()}
    check(all(res.values()), f"variants accepted: {[k for k, v in res.items() if not v]}")
    check(not problems_of(src), "the unmodified profile was refused")
    return {"profiles": list(exps), "refused_variants": list(res), "defaults": BASELINE_NOTE}


def unit_warm_start(out: Path) -> Dict[str, Any]:
    import experiment_config as ec
    import m7_trainer as mt

    got = {}
    for p in PROFILES:
        exp = ec.load_experiment(p)
        cfg = mt.config_from_experiment(exp, output_root=out / "never_created")
        check(cfg.total_timesteps == 1_536_000 and cfg.anchor_curriculum == exp.anchor_curriculum, f"{p.stem}: config")
        meta = mt.M7Run(cfg)._source_checkpoint()
        wsc = meta.get("_warm_start_change") or {}
        acc = (wsc.get("accepted_diffs") or {}).get("environment.extra_env") or {}
        check(int(meta["num_timesteps"]) == 3_072_000 and acc.get("requested", {}).get("SSB64_RL_TARGET_DIAG") == "1"
              and "SSB64_RL_TARGET_DIAG" not in (acc.get("checkpoint") or {}), f"{p.stem}: accepted {wsc}")
        check(cfg.to_json().get("anchor_curriculum") == exp.anchor_curriculum, f"{p.stem}: config record")
        got[p.stem] = sorted(wsc["accepted_diffs"])
    check(not (out / "never_created").exists(), "the warm-start check created a run directory")
    exp = ec.load_experiment(PROFILES[0])
    run = mt.M7Run(mt.config_from_experiment(exp, output_root=out / "never_created"))
    base_meta = mt.read_checkpoint_set(REPO_ROOT / "runs" / "m7g_k" / "m7g_s0_v1" / "final")
    cur = copy.deepcopy(base_meta)
    cur["experiment"]["curriculum"] = {"contract": "btt_curriculum_frontier_v1"}
    check(refused(lambda: run._accept_warm_start(cur, {}), mt.CheckpointError), "a curriculum source was accepted")
    compat = {"environment.extra_env": {"checkpoint": {"SSB64_RL_NO_RENDER": "1"},
                                        "requested": {"SSB64_RL_NO_RENDER": "1", "SSB64_RL_TARGET_DIAG": "1",
                                                      "SSB64_RL_SPATIAL": "1"}}}
    check(run._accept_warm_start(copy.deepcopy(base_meta), compat) == compat, "an extra flag was accepted")
    other = {"ppo.learning_rate": {"checkpoint": 3e-4, "requested": 1e-4}}
    check(run._accept_warm_start(copy.deepcopy(base_meta), dict(other)) == other, "another difference was accepted")
    m7h_final = REPO_ROOT / "runs" / "m7h" / "campaign" / "m7h_f_s0" / "final"
    m7h_refused = None
    if m7h_final.is_dir():
        text = PROFILES[0].read_text(encoding="utf-8").replace("runs/m7g_k/m7g_s0_v1/final", "runs/m7h/campaign/m7h_f_s0/final")
        pth = out / "m7h_source.toml"
        pth.write_text(text, encoding="utf-8")
        try:
            e2 = ec.load_experiment(pth)
            mt.M7Run(mt.config_from_experiment(e2, output_root=out / "never_created"))._source_checkpoint()
            m7h_refused = False
        except (mt.CheckpointError, ec.ConfigError, ValueError):
            m7h_refused = True
        check(m7h_refused, "a warm start from the M7h curriculum run was accepted")
    # without the table, the diagnostic-flag difference is refused exactly as before (resume semantics unchanged)
    plain = mt.M7Run(mt.config_from_experiment(exp, output_root=out / "never_created"))
    plain.config.anchor_curriculum = None
    check(refused(plain._source_checkpoint, mt.CheckpointError), "a table-less diag-flag resume was accepted")
    return {"accepted": got, "m7h_source_refused": m7h_refused}


# -- game ----------------------------------------------------------------------------------------------------------------


def game_vec_anchor(out: Path) -> Dict[str, Any]:
    import numpy as np

    from btt_parallel import RunCoordinator, WorkerSpec, initial_coordination_state
    from btt_rewards import REWARD_V2
    from m7_runtime import install_kill_on_close_job, list_processes_named, prepare_worker_runtime, remove_worker_runtime
    from m7_vec_env import M7SubprocVecEnv
    from m7d_run import validate_episode_row
    from m7m_vec import AnchorVecEnv
    from m7m_worker import AnchorWorkerFactory

    install_kill_on_close_job()
    check(not list_processes_named(), "BattleShip already running")
    seed = next(s for s in range(1000) if ma.AnchorSchedule(s, tick0_probability=0.5).draw()[0] == ma.START_ANCHOR)
    settings = ma.registered_table(tick0_probability=ma.TICK0_PROBABILITY_E, observation_table_sha256=table_sha())
    root = out / "game_vec_anchor"
    coord = root / "coord"
    run_id = "m7m_test_vec"
    RunCoordinator.create(coord, initial_coordination_state(run_id, "test", 0))
    env_flags = (("SSB64_RL_NO_RENDER", "1"), ("SSB64_RAPHNET_DISABLE", "1"), ("SSB64_RL_TARGET_DIAG", "1"))
    specs = []
    for r in range(2):
        wdir = root / f"w{r:02d}"
        prepare_worker_runtime(wdir / "runtime", REPO_ROOT / "build-us" / "Release" / "BattleShip.exe")
        specs.append(WorkerSpec(rank=5 + r, run_id=run_id, role="test", worker_dir=str(wdir), coordination_dir=str(coord),
                                executable=str(REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"), horizon=ma.HORIZON,
                                base_seed=0, extra_env=env_flags, reward_contract=REWARD_V2, experiment=None,
                                standby_preboot=True, standby_count=1))
    venv = M7SubprocVecEnv([AnchorWorkerFactory(s, settings) for s in specs], step_timeout=600.0)
    cur = AnchorVecEnv(venv, settings=settings, run_id=run_id, seed=seed, log_dir=root / "curriculum")
    rows: List[Dict[str, Any]] = []
    seen_steps = [0, 0]
    ret = [0.0, 0.0]
    problems: List[str] = []
    anchored_rows = []
    summaries: List[Dict[str, Any]] = []
    vec_steps = 0
    try:
        cur.reset()
        actions = np.zeros((2, 2), dtype=np.int64)
        t0 = time.perf_counter()
        while len(anchored_rows) < 2 and time.perf_counter() - t0 < 420:
            cur.step_async(actions)
            _obs, rews, dones, infos = cur.step_wait()
            vec_steps += 1
            for i in range(2):
                seen_steps[i] += 1
                ret[i] += float(rews[i])
                if dones[i]:
                    s = infos[i].get("m7_episode") or {}
                    summaries.append(s)
                    p = validate_episode_row(s, REWARD_V2, ma.HORIZON)
                    problems += p
                    m7h, m7m = s.get("m7h") or {}, s.get("m7m") or {}
                    row = {"env": i, "kind": m7m.get("kind"), "tau": m7m.get("tau"), "steps": s.get("steps"),
                           "vec_steps_seen": seen_steps[i], "return": s.get("return"), "rewards_seen": round(ret[i], 6),
                           "prefix_length": m7h.get("prefix_length"), "rows": m7h.get("rows"),
                           "rows_equal": m7h.get("rows_equal_prefix_plus_policy"), "end": s.get("end_reason"),
                           "success": m7m.get("success"), "problems": p}
                    rows.append(row)
                    if row["kind"] == ma.START_ANCHOR:
                        anchored_rows.append(row)
                    seen_steps[i], ret[i] = 0, 0.0
    finally:
        cur.close()
        for s in specs:
            remove_worker_runtime(Path(s.worker_dir) / "runtime")
    rep = cur.report()
    # the files the trainer writes (rows, final schedule state), then the campaign's accounting check on them
    (root / "metrics").mkdir(parents=True, exist_ok=True)
    with open(root / "metrics" / "episodes.jsonl", "w", encoding="utf-8", newline="\n") as fp:
        for s in summaries:
            fp.write(json.dumps(s, default=str) + "\n")
    (root / "final").mkdir(parents=True, exist_ok=True)
    cur.write_state(root / "final")
    import m7m_campaign as mc

    acct = mc.accounting_dir(root, arm="E", base_seed=seed, p0=0.5, additional=vec_steps * 2, pilot=True, n_envs=2)
    check(acct["ok"], f"accounting on the real log: {acct['problems']}")
    sel = root / "curriculum" / "selection.jsonl"
    lines = sel.read_text(encoding="utf-8").splitlines()
    i = next(k for k, x in enumerate(lines) if '"event":"select"' in x)
    rec = json.loads(lines[i])
    rec["u1"] = 0.999 if rec["u1"] < 0.5 else 0.001
    sel.write_text("\n".join(lines[:i] + [json.dumps(rec, separators=(",", ":"))] + lines[i + 1:]) + "\n", encoding="utf-8")
    bad = mc.accounting_dir(root, arm="E", base_seed=seed, p0=0.5, additional=vec_steps * 2, pilot=True, n_envs=2)
    check(not bad["ok"], "a tampered draw passed the accounting check")
    check(not list_processes_named(), "leftover BattleShip")
    check(not problems, f"row problems {problems[:3]}")
    check(len(anchored_rows) >= 1, f"no anchored episode finished: {rows}")
    for r in rows:
        check(r["steps"] == r["vec_steps_seen"] and abs(r["return"] - r["rewards_seen"]) < 1e-6 and r["rows_equal"],
              f"episode accounting {r}")
    for r in anchored_rows:
        check(901 <= r["tau"] <= 1020 and r["prefix_length"] == r["tau"] and r["rows"] == r["tau"] + r["steps"],
              f"anchored accounting {r}")
    check(rep["delivered_equals_table"] >= len(anchored_rows) and rep["invariant_checks"] >= 1, f"report {rep}")
    return {"seed": seed, "episodes": rows, "accounting": {k: acct[k] for k in ("selects", "anchored_draws", "deliveries",
                                                                              "outcomes", "rows", "prefix_ticks")},
            "tampered_draw_refused": True, "delivered_equals_table": rep["delivered_equals_table"],
            "prefix_ticks": rep["prefix_ticks"], "dispatch_wall_s": rep["dispatch_wall_s"], "starts": rep["starts"]}


def unit_campaign(out: Path) -> Dict[str, Any]:  # noqa: ARG001
    import m7m_analysis as mn
    import m7m_matrix as mm

    check(mn.self_test() == 0, "rule self-test")
    rule = mn.load_rule()
    specs = mm.matrix() + mm.pilot_matrix()
    bad = {s.name: [k for k, ok in mm.arm_checks(s, mm.load_run(s)).items() if not ok] for s in specs}
    check(not any(bad.values()), f"arm checks {bad}")
    pairs = [mm.pair_proof(mm.RunSpec(j, "E"), mm.RunSpec(j, "K")) for j in mm.SEEDS] + [mm.pair_proof(*mm.pilot_matrix())]
    check(all(p["ok"] for p in pairs), f"pairs {pairs}")
    pk = [mm.phase_k_proof(s, mm.load_run(s)) for s in specs]
    check(all(p["ok"] for p in pk), f"Phase K proofs {[p for p in pk if not p['ok']]}")
    ws = {j: mm.warm_start_identity(j) for j in mm.SEEDS}
    check(all(w["ok"] for w in ws.values()), f"warm starts {ws}")
    plans = {s.name: [(p["label"], p["num_timesteps"], p["deterministic_episodes"], p["stochastic_episodes"])
                      for p in mm.evaluation_plan(s, mm.load_run(s))] for s in specs}
    check(plans["m7m_e_s0"] == [("curve_t003584000", 3584000, 5, 60), ("curve_t004096000", 4096000, 5, 60),
                                ("final", 4608000, 100, 100)] and plans["m7m_pilot_k_s0"] == [("final", 3112960, 1, 5)],
          f"plans {plans}")
    check(mm.census_plan()["episodes"] == 1980, "census")
    check([s.name for s in mm.matrix()] == ["m7m_e_s0", "m7m_k_s0", "m7m_e_s1", "m7m_k_s1", "m7m_e_s2", "m7m_k_s2"],
          "order")
    fp = mm.code_fingerprint()
    check(all(k in fp["per_file"] for k in ("docs/rl_sweep_consolidation_m7m_anchor.json",
                                            "docs/rl_sweep_consolidation_m7m_anchor_observations.json",
                                            "docs/rl_sweep_consolidation_m7m_decision_rule.json")), "evidence in code")
    return {"rule_sha256": rule["_sha256"][:16], "code_files": fp["files"], "warm_starts": {j: w["n_updates"] for j, w in
                                                                                         ws.items()}}


UNIT: Dict[str, Callable[[Path], Dict[str, Any]]] = {
    "unit_campaign": unit_campaign,
    "unit_anchor": unit_anchor, "unit_schedule": unit_schedule, "unit_config_optin": unit_config_optin,
    "unit_warm_start": unit_warm_start,
}
GAME: Dict[str, Callable[[Path], Dict[str, Any]]] = {"game_vec_anchor": game_vec_anchor}


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
