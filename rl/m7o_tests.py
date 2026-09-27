#!/usr/bin/env python3
"""M7o tests: the exploration credit (btt_explore_cells_v1), its profile table and its worker wiring.

    unit_module        rl/btt_explore_cells.py self-test (grid, eligibility, pending / banking / voiding, cap, counts, persistence)
    unit_config        the [exploration] table: accepted on the M7o profiles, refused with another value, a missing key, obs v1,
                       reward v3, a curriculum table or run.mode resume; fingerprints differ from the M7n profile only there
    unit_defaults      a profile without the table builds the plain M7RewardWrapper (historical defaults unchanged)
    unit_fixture_accounting   verifier test on the two human crossing fixtures (validation-only): the accounting rules hold on a
                       recorded trace (pending credit banks at the ledge-top landing, the terminal fall voids the flight after
                       the last landing, banked credit is never undone); their totals select nothing
    unit_trace_equivalence    the production module over a recorded policy trace equals the offline simulator's accounting
    unit_rule          the frozen M7o decision rule self-test
    unit_matrix        the campaign matrix, control identity and the driver report / plan on a temporary root
    game_wrapper       one real worker (v3 stack + exploration wrapper) driven by random Track 1 actions until two episodes end:
                       info keys, learner reward = v2 + banked, the table file written and reloaded on a second worker

Usage: python rl/m7o_tests.py [unit|game|<case> ...] [--root runs/m7o/_tests/<utc>]
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import btt_explore_cells as xp  # noqa: E402
import experiment_config as ec  # noqa: E402

REPO_ROOT = RL_DIR.parent
PILOT_PROFILE = REPO_ROOT / "rl" / "configs" / "m7o" / "pilot" / "m7o_pilot_s0.toml"
M7N_PROFILE = REPO_ROOT / "rl" / "configs" / "m7n" / "m7n_s0_v3.toml"


class Failure(AssertionError):
    pass


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise Failure(msg)


class Suite:
    def __init__(self, root: Path):
        self.root = root

    def dir(self, name: str) -> Path:
        d = self.root / name
        d.mkdir(parents=True, exist_ok=True)
        return d


def unit_module(s: Suite) -> Dict[str, Any]:
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = xp.self_test()
    lines = buf.getvalue().splitlines()
    check(rc == 0, "module self-test failed: " + " | ".join(l for l in lines if "FAIL" in l))
    return {"cases": sum(1 for l in lines if l.startswith("[PASS]"))}


def _load_text(text: str) -> ec.Experiment:
    t = Path(tempfile.mkdtemp()) / "x.toml"
    t.write_text(text, encoding="utf-8")
    return ec.load_experiment(t)


def unit_config(s: Suite) -> Dict[str, Any]:
    import m7_trainer as tr

    exp = ec.load_experiment(PILOT_PROFILE)
    check(exp.exploration == xp.ExploreContract().to_json(), f"pilot table {exp.exploration}")
    cfg = tr.config_from_experiment(exp)
    check(cfg.exploration == exp.exploration, "trainer config carries the table")
    c = tr.run_contracts(cfg)
    check(c.get("exploration_contract") == xp.CONTRACT_ID and c.get("exploration_settings") == exp.exploration, "run contracts")
    m7n = ec.load_experiment(M7N_PROFILE)
    va, vb = exp.values, m7n.values
    diff = sorted(k for k in set(va) | set(vb) if va.get(k) != vb.get(k))
    check(all(k.startswith("exploration.") or k in ("run.name", "run.notes", "run.output_root", "run.total_transitions") for k in diff),
          f"pilot differs from the M7n profile in {diff}")
    check(exp.semantic_fingerprint != m7n.semantic_fingerprint, "semantic fingerprint differs")
    raw = PILOT_PROFILE.read_text(encoding="utf-8")
    rejected = {}
    for label, bad in (("beta", raw.replace("beta = 0.05", "beta = 0.1")), ("cap", raw.replace("cap = 1.0", "cap = 2.0")),
                       ("missing_key", raw.replace('decay = "harmonic"\n', "")),
                       ("obs_v1", raw.replace('observation = "btt_policy_obs_v3_entities"', 'observation = "btt_policy_obs_v1"')),
                       ("reward_v3", raw.replace('reward = "btt_reward_v2"', 'reward = "btt_reward_v3"')),
                       ("resume", raw.replace('mode = "train"', 'mode = "resume"')),
                       ("empty_table", raw[:raw.index("[exploration]")] + "[exploration]\n")):
        try:
            _load_text(bad)
            rejected[label] = False
        except Exception:  # noqa: BLE001 - any refusal is the expected outcome
            rejected[label] = True
    check(all(rejected.values()), f"not refused: {[k for k, v in rejected.items() if not v]}")
    return {"rejected": sorted(rejected), "semantic_fingerprint": exp.semantic_fingerprint[:12]}


def unit_defaults(s: Suite) -> Dict[str, Any]:
    """Without the table, make_reward_wrapper builds exactly M7RewardWrapper (historical defaults unchanged)."""
    import btt_parallel as bp
    from btt_rewards import REWARD_V2

    import gymnasium as gym

    class _Base(gym.Env):
        max_episode_steps = 3600

    spec = bp.WorkerSpec(rank=0, run_id="t", role="test", worker_dir=str(s.dir("defaults")), coordination_dir=str(s.dir("coord")),
                         executable="x", reward_contract=REWARD_V2)
    w = bp.make_reward_wrapper(_Base(), spec, None)
    check(type(w) is bp.M7RewardWrapper, f"default wrapper {type(w).__name__}")
    check(spec.exploration is None, "WorkerSpec default exploration None")
    return {"wrapper": type(w).__name__}


def _fixture_rows(path: Path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    tr = doc["evidence"]["trajectory"]
    fi = {k: i for i, k in enumerate(tr["fields"])}
    return doc, [(r[fi["consumed_tick"]], r[fi["position_x"]], r[fi["position_y"]], r[fi["ground_air_state"]], r[fi["fighter_status_id"]])
                 for r in tr["rows"]]


def _run_rows(rows, *, fall_at_end: bool, table: Optional[xp.ExploreTable] = None, jumps: Optional[List[Any]] = None):
    import m7n_status_table as st

    cls = st.ActionClassifier(st.load_table(), "mario")
    table = table if table is not None else xp.ExploreTable(rank=0)
    first = rows[0]
    reset = {"fighter_valid": 1, "btt_active": 1, "position_x": 0.0, "position_y": -2550.0, "ground_air_state": 0}
    ep = xp.ExploreEpisode.start(reset, [9600, -9600, 9600, -9600], table)
    steps = []
    n = len(rows)
    for i, r in enumerate(rows):
        t, x, y, ga, status = r[:5]
        live = x is not None
        obs = {"fighter_valid": 1 if live else 0, "btt_active": 1 if live else 0, "position_x": x, "position_y": y,
               "ground_air_state": ga, "fighter_status_id": status}
        last = i == n - 1
        steps.append(ep.step(obs, cls.name(int(status)) if live else "unmapped", consumed_tick=t,
                             native_failure=bool(fall_at_end and last), episode_end=last))
    return ep, steps


def unit_fixture_accounting(s: Suite) -> Dict[str, Any]:
    """Verifier test only (the fixtures are validation material): the accounting rules on two recorded crossings."""
    out = {}
    for f in sorted((REPO_ROOT / "rl" / "fixtures" / "m7g").glob("*.json")):
        doc, rows = _fixture_rows(f)
        fall = doc["evidence"]["terminal"]["kind"] == "native_failure"
        ep, steps = _run_rows(rows, fall_at_end=fall)
        rec = ep.record()
        entry = (doc["evidence"].get("first_left_entry") or {}).get("consumed_tick")
        ledge_landing = next((st_.landing for st_, r in zip(steps, rows) if st_.landing and r[2] >= 2999.0 and r[1] <= -1200.0), False)
        check(rec["bonus"] > 0 and rec["cells_visited"] > 10, f"{f.name}: no credit on a recorded crossing")
        check(ledge_landing, f"{f.name}: the ledge-top landing did not bank pending flight credit")
        check(abs(rec["banked_ground"] + rec["banked_air"] - rec["bonus"]) < 1e-9 and rec["bonus"] <= xp.CAP + 1e-9, f"{f.name}: totals")
        if fall:
            check(rec["voided"] > 0, f"{f.name}: the terminal fall voided nothing")
            banked_before = sum(st_.banked for st_ in steps[:-1])
            check(abs(banked_before - rec["bonus"]) < 1e-9, f"{f.name}: the fall changed banked credit")
        out[f.name[:24]] = {"bonus": rec["bonus"], "voided": rec["voided"], "landings": rec["landings"], "cells": rec["cells_visited"],
                            "entry_tick": entry, "fall": fall}
    return out


def unit_trace_equivalence(s: Suite) -> Dict[str, Any]:
    """The production module on a recorded policy trace (a replayed M7n episode) equals an independent, minimal
    re-implementation of the contract (guards the module against accidental rule drift)."""
    import gzip
    import math

    import m7n_status_table as st

    traces = sorted((REPO_ROOT / "runs" / "m7o" / "offline" / "replays" / "traces").glob("final_00*.json.gz"))[:5]
    check(traces, "no replayed traces (run rl/tools/m7o_offline.py replay first)")
    cls = st.ActionClassifier(st.load_table(), "mario")
    checked = 0
    table = xp.ExploreTable(rank=0)
    for tp in traces:
        with gzip.open(tp, "rt", encoding="utf-8") as fp:
            d = json.load(fp)
        rows = [(r[0], r[1], r[2], r[3], r[4]) for r in d["rows"]]
        counts_before = dict(table.counts)
        ep, _steps = _run_rows(rows, fall_at_end=d["fall"], table=table)
        # independent re-implementation
        size = 800.0
        visited = {(0, -4)}
        pending, total, voided = [], 0.0, 0.0
        for i, (t, x, y, ga, status) in enumerate(rows):
            last = i == len(rows) - 1
            if d["fall"] and last:
                voided += sum(a for a in pending)
                pending = []
                break
            live = x is not None
            if not live or cls.name(int(status)) in xp.INELIGIBLE_CLASSES:
                if last:
                    voided += sum(pending)
                continue
            grounded = int(ga) == 0
            if grounded and pending:
                for a in pending:
                    paid = min(a, max(0.0, xp.CAP - total))
                    total += paid
                pending = []
            c = (math.floor(x / size), math.floor(y / size))
            if c not in visited:
                visited.add(c)
                a = xp.BETA / (1.0 + counts_before.get(c, 0))
                if grounded:
                    total += min(a, max(0.0, xp.CAP - total))
                else:
                    pending.append(a)
            if last:
                voided += sum(pending)
        rec = ep.record()
        check(abs(ep.banked_total - total) < 1e-9 and abs(ep.voided_total - voided) < 1e-9 and rec["cells_visited"] == len(visited),
              f"{tp.name}: module {ep.banked_total}/{ep.voided_total}/{rec['cells_visited']} vs reference {total}/{voided}/{len(visited)}")
        checked += 1
    return {"traces_checked": checked, "table_episodes": table.episodes}


def game_wrapper(s: Suite) -> Dict[str, Any]:
    """One real worker with the exploration wrapper (spawned here, in-process), random actions, 400 steps."""
    import numpy as np

    import btt_parallel as bp
    import m7n_obs as mn
    import m7_trainer as tr
    from m7_runtime import install_kill_on_close_job, prepare_worker_runtime

    install_kill_on_close_job()
    exp = ec.load_experiment(PILOT_PROFILE)
    cfg = tr.config_from_experiment(exp)
    root = s.dir("game_wrapper")
    wdir = root / "workers" / "w00"
    prepare_worker_runtime(wdir / "runtime", Path(cfg.executable))
    coord = root / "coordination"
    bp.RunCoordinator.create(coord, bp.initial_coordination_state("m7o_test", "test", None))
    spec = bp.WorkerSpec(rank=0, run_id="m7o_test", role="test", worker_dir=str(wdir), coordination_dir=str(coord),
                         executable=str(cfg.executable), horizon=cfg.horizon, base_seed=0, extra_env=tuple(cfg.extra_env),
                         reward_contract=cfg.reward, experiment=cfg.experiment_summary(), exploration=cfg.exploration,
                         standby_preboot=False, standby_count=0)
    env = mn.M7nWorkerFactory(spec)()
    rng = np.random.default_rng(0)
    totals = {"learner": 0.0, "v2": 0.0, "banked": 0.0}
    episodes = 0
    from m7o_explore_env import M7ExploreRewardWrapper

    def _find(e: Any) -> Any:
        while e is not None:
            if isinstance(e, M7ExploreRewardWrapper):
                return e
            e = getattr(e, "env", None)
        return None

    xw = _find(env)
    check(xw is not None, "the exploration wrapper is not in the v3 stack")
    try:
        obs, info = env.reset()
        check(xw.episode is not None and xw.episode.size == 800.0 and xw.map_bounds == [9600, -9600, 9600, -9600],
              f"reset state {xw.map_bounds} {xw.episode and xw.episode.size}")
        for k in range(7500):                      # until two episodes end (random play falls often; horizon 3,600)
            if episodes >= 2:
                break
            a = np.array([rng.integers(0, 9), rng.integers(0, 8)])
            obs, r, term, trunc, info = env.step(a)
            xt, terms = xw.last_explore_step, xw.last_terms
            check(xt is not None and terms is not None, "the wrapper recorded no step")
            check(abs(float(r) - (float(terms.total) + float(xt.banked))) < 1e-9, f"learner reward {r} != v2 {terms.total} + banked {xt.banked}")
            totals["learner"] += float(r)
            totals["v2"] += float(terms.total)
            totals["banked"] += float(xt.banked)
            if term or trunc:
                episodes += 1
                rec = xw.last_record
                check(rec is not None and rec["schema"] == xp.RECORD_SCHEMA and 0.0 <= rec["bonus"] <= xp.CAP + 1e-9, "episode record")
                summ = info.get("m7_episode") or {}
                check(summ.get("explore", {}).get("bonus") == rec["bonus"], f"summary carries the record {list(summ)[:12]}")
                check(abs(float(summ.get("return")) - float(rec["contract_return"])) < 1e-6, "row return stays the contract return")
                obs, info = env.reset()
                check(xw.table.episodes == episodes, "table advances per episode")
    finally:
        env.close()
    table_file = wdir / "explore_table.json"
    check(table_file.is_file(), "table file written")
    t = xp.ExploreTable.load(table_file)
    check(t.episodes == episodes and t.rank == 0, f"table episodes {t.episodes} rank {t.rank}")
    # a second worker on the same directory continues the slot's table (resume semantics)
    env2 = mn.M7nWorkerFactory(spec)()
    try:
        xw2 = _find(env2)
        check(xw2 is not None and xw2.table.episodes == episodes and xw2.table.rank == 0, "reconstructed worker reloaded the table")
    finally:
        env2.close()
    check(abs(totals["learner"] - totals["v2"] - totals["banked"]) < 1e-6, "totals")
    return {"steps": k, "episodes": episodes, **{k: round(v, 4) for k, v in totals.items()}, "table_cells": len(t.counts)}


def unit_rule(s: Suite) -> Dict[str, Any]:
    """The frozen M7o rule: schema, every synthetic case, precedence flags."""
    import io
    from contextlib import redirect_stdout

    import m7o_analysis as oa

    rule = oa.load_rule()
    check(rule["schema"] == "m7o_decision_rule_v1" and len(rule["gates_in_order"]) == 7, "rule document")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = oa.self_test()
    lines = buf.getvalue().splitlines()
    check(rc == 0, "rule self-test failed: " + " | ".join(l for l in lines if "FAIL" in l))
    P = oa.params(rule)
    check(P["seeds"] == (0, 1, 2) and P["targets_diff_min"] == "1/2" and P["regression_seeds_min"] == 2 and P["ceiling_seeds_min"] == 2, f"parameters {P}")
    return {"rule_sha256": rule["_sha256"], "cases": sum(1 for l in lines if l.startswith("[PASS]"))}


def unit_matrix(s: Suite) -> Dict[str, Any]:
    """The campaign matrix: three fresh experimental runs, registered values, the M7n proof, plan, census, directories,
    the control identity, and the driver's report / plan logic on a temporary root (nothing launched)."""
    import m7o_campaign as oc
    import m7o_matrix as om

    specs = om.matrix()
    check([x.name for x in specs] == ["m7o_s0_x1", "m7o_s1_x1", "m7o_s2_x1"] and [x.seed for x in specs] == [0, 1, 2], "matrix")
    for spec in specs:
        exp = om.load_run(spec)
        bad = [k for k, ok in om.arm_checks(spec, exp).items() if not ok]
        check(not bad, f"{spec.name}: {bad}")
        check(om.m7n_proof(spec, exp)["ok"], f"{spec.name}: M7n proof")
        plan = om.evaluation_plan(spec, exp)
        check(len(plan) == 11 and sum(int(p["deterministic_episodes"]) + int(p["stochastic_episodes"]) for p in plan) == 985
              and all(p["exploration_in_evaluation"] is False and p["starts"] == "tick0_only" for p in plan), "plan")
    check(om.census_plan()["episodes"] == 2955, "census")
    for sd in (0, 1, 2):
        ci = om.control_identity(sd)
        check(ci["ok"] and ci["m7n_inputs"]["X"] == 0, f"control {sd}: {ci['problems']}")
    saved = om.root()
    root = s.dir("driver_root") / "campaign"
    try:
        om.configure_root(root)
        man = om.build_manifest(with_digests=False)
        check(man["ok"], f"temp manifest {man['problems'][:3]}")
        st = oc.load_state()
        rep = oc.build_report(st, man)
        check(rep["pending"] and all(a.T is not None for a in rep["inputs"]["ctl"].values())
              and {sd: c.X for sd, c in rep["inputs"]["crossings"]["ctl"].items()} == {0: 0, 1: 0, 2: 0}, "report on an empty root")
        plan = oc.train_plan(specs, st)
        check(plan[0]["action"] == "train from scratch" and plan[1]["action"].startswith("wait"), f"plan {plan}")
        check(om.check_directory_plan()["ok"], "temp directory plan")
    finally:
        om.configure_root(saved if saved != om.DEFAULT_ROOT else None)
    return {"runs": [x.name for x in specs]}


UNIT_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "unit_module": unit_module, "unit_config": unit_config, "unit_defaults": unit_defaults,
    "unit_fixture_accounting": unit_fixture_accounting, "unit_trace_equivalence": unit_trace_equivalence,
    "unit_rule": unit_rule, "unit_matrix": unit_matrix,
}
GAME_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {"game_wrapper": game_wrapper}
ALL_CASES = {**UNIT_CASES, **GAME_CASES}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cases", nargs="*")
    ap.add_argument("--root", default=None)
    args = ap.parse_args(argv)
    names: List[str] = []
    for c in args.cases or list(ALL_CASES):
        names += list(UNIT_CASES) if c == "unit" else list(GAME_CASES) if c == "game" else [c]
    root = Path(args.root) if args.root else REPO_ROOT / "runs" / "m7o" / "_tests" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root.mkdir(parents=True, exist_ok=True)
    suite = Suite(root)
    results = []
    ok = 0
    for name in names:
        t0 = time.perf_counter()
        try:
            details = ALL_CASES[name](suite)
            status = "PASS"
            ok += 1
        except Exception as exc:  # noqa: BLE001
            details = {"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-1500:]}
            status = "FAIL"
        print(f"{status}  {name}  ({time.perf_counter() - t0:.1f} s)" + ("" if status == "PASS" else f"  {details['error']}"), flush=True)
        results.append({"case": name, "status": status, "details": details})
    (root / "results.json").write_text(json.dumps(results, indent=1, default=str) + "\n", encoding="utf-8")
    print(f"m7o_tests: {ok}/{len(names)} PASS -> {root}")
    return 0 if ok == len(names) else 1


if __name__ == "__main__":
    sys.exit(main())
