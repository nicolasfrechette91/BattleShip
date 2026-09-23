"""M7f permanent regression fixtures for the btt_target_identity_v1 diagnostic.

Unit cases (no game):
    unit_contract      m7f_targets self-test (strict parser, mask/events derivation, invariant checks)
    unit_manifest      m7f_manifest self-test
    unit_analysis      m7f_analysis self-test
    unit_nonport       m7f_nonport_view self-test + the edited decomp files' non-PORT view vs the pinned rl-main revision
    unit_mapping       docs/rl_target_identity_m7f_mapping.json equals the frozen native table below
Game cases (fresh BattleShip processes, private runtime directories, never more than one at a time):
    game_tas_diag            TAS through stepping with the diagnostic: frozen order/ticks, mapping, clear, result JSON
    game_default_wire        diagnostic unset: status/observe/step key sets and result JSON exactly as before M7f
    game_diag_required       a process without the flag fails the M7f reader clearly (never guessed)
    game_native_diag         native 468-row replay with the diagnostic: checksum + ten identified breaks
    game_fixture_replay      one historical six-target artifact reproduced exactly, with its target IDs
    game_fall_teardown       a historical fall stepped on through End/BossDefeat/Set until the scene unloads:
                             no anomaly; the link cross-check is skipped only after the scene task ended

Usage: python rl/m7f_tests.py [unit|game|<case> ...] [--root runs/m7f/_tests_<utc>]
Exit 0 all pass, 1 any failure.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import m7f_targets as mt  # noqa: E402

REPO_ROOT = RL_DIR.parent
DECOMP_PINNED = "91d7b6b75e97f46c10ce2f09ac68abe1799213b6"

# Measured natively (RLTargetDiag records of the post-M7f executable, identical in every validated process).
FROZEN_MAPPING = [
    {"id": 0, "animated": 0, "spawn": [-1350.0, -2250.0, 0.0], "region": "central"},
    {"id": 1, "animated": 0, "spawn": [-3450.0, -2550.0, 0.0], "region": "left_of_wall"},
    {"id": 2, "animated": 1, "spawn": [2700.0, 2100.0, 0.0], "region": "upper_right_moving"},
    {"id": 3, "animated": 0, "spawn": [4950.0, -1800.0, 0.0], "region": "right"},
    {"id": 4, "animated": 0, "spawn": [4.999999873689376e-06, -900.0, 0.0], "region": "central"},
    {"id": 5, "animated": 0, "spawn": [1.9999999494757503e-05, 300.0, 0.0], "region": "central"},
    {"id": 6, "animated": 0, "spawn": [-3300.0, 3300.0, 0.0], "region": "left_of_wall"},
    {"id": 7, "animated": 0, "spawn": [0.0, 1650.0, 0.0], "region": "central"},
    {"id": 8, "animated": 0, "spawn": [-3300.0, 600.0, 0.0], "region": "left_of_wall"},
    {"id": 9, "animated": 0, "spawn": [1650.0, -2250.0, 0.0], "region": "central"},
]
TAS_ORDER = [9, 4, 5, 2, 7, 3, 0, 6, 8, 1]
TAS_TICKS = [51, 87, 142, 163, 275, 316, 358, 368, 432, 446]
TAS_MOVING_BREAK_POS = [2700.0, 3000.0, 0.0]
# Reply key sets of the pre-M7f executable (protocol 1) with both M6 flags; the default wire must keep them exactly.
STATUS_KEYS = {"protocol", "op", "ok", "state", "state_name", "can_step", "step_count", "no_render", "raphnet_disabled"}
OBSERVE_KEYS = {"protocol", "op", "ok", "state", "state_name", "can_step", "step_count", "observation"}
STEP_KEYS = {"protocol", "op", "ok", "step_schema", "state", "state_name", "step_count", "consumed_tick", "observation"}
RESULT_KEYS = {"result_schema", "outcome", "targets_broken", "completion_time_passed", "completion_input_tick",
               "time_passed_final", "input_cursor_final", "host_frames"}
FIXTURE = ("runs/m7e/_eval/m7e_s0_v2/curve_t001228800/stochastic/workers/w02/artifacts/episode_20260923T014311Z_3e92f774",
           [9, 3, 0, 4, 7, 5], [41, 213, 644, 1599, 2383, 3105], [1, 2, 6, 8])
FLAGS = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1"}


class CheckFailed(AssertionError):
    pass


def check(cond: bool, message: str) -> None:
    if not cond:
        raise CheckFailed(message)


class Suite:
    def __init__(self, root: Path):
        self.root = root

    def dir(self, name: str) -> Path:
        d = self.root / name
        d.mkdir(parents=True, exist_ok=False)
        return d


# -- unit -------------------------------------------------------------------------------------------------


def unit_contract(s: Suite) -> Dict[str, Any]:
    check(mt.self_test() == 0, "m7f_targets self-test failed")
    return {"self_test": "PASS"}


def unit_manifest(s: Suite) -> Dict[str, Any]:
    import m7f_manifest

    check(m7f_manifest.self_test() == 0, "m7f_manifest self-test failed")
    return {"self_test": "PASS"}


def unit_analysis(s: Suite) -> Dict[str, Any]:
    import m7f_analysis

    check(m7f_analysis.self_test() == 0, "m7f_analysis self-test failed")
    return {"self_test": "PASS"}


def unit_nonport(s: Suite) -> Dict[str, Any]:
    import m7f_nonport_view as nv

    check(nv.self_test() == 0, "m7f_nonport_view self-test failed")
    res = [nv.compare(f, DECOMP_PINNED) for f in ("decomp/src/sc/sc1pmode/sc1pbonusstage.c",
                                                   "decomp/src/it/itground/ittarget.c")]
    check(all(r["nonport_identical"] for r in res), f"non-PORT view changed: {res}")
    return {"files": res}


def unit_mapping(s: Suite) -> Dict[str, Any]:
    doc = json.loads((REPO_ROOT / "docs" / "rl_target_identity_m7f_mapping.json").read_text(encoding="utf-8"))
    got = [{k: t[k] for k in ("id", "animated", "spawn", "region")} for t in doc["targets"]]
    check(got == FROZEN_MAPPING, f"mapping document differs from the frozen native table: {got}")
    regions = [mt.region_of(mt.TargetRecord(t["id"], t["animated"], tuple(t["spawn"]), 0, 0, 0, (0.0, 0.0, 0.0)))
               for t in FROZEN_MAPPING]
    check(regions == [t["region"] for t in FROZEN_MAPPING], "region rule disagrees with the frozen labels")
    return {"targets": len(got)}


# -- game -------------------------------------------------------------------------------------------------


def _no_battleship() -> None:
    from m7_runtime import list_processes_named

    others = list_processes_named()
    check(not others, f"BattleShip already running: {others}")


def game_tas_diag(s: Suite) -> Dict[str, Any]:
    import m7f_trace as tr

    _no_battleship()
    t = tr.run_stepping_trace("tas_diag", tr.DEFAULT_EXE, tr.tas_actions(), s.dir("game_tas_diag"),
                              extra_env={**FLAGS, mt.DIAG_ENV: "1"})
    mt.require_diag_status(t["status"])
    chk = mt.check_trace(t["initial"], t["steps"])
    check(chk.ok, f"diagnostic invalid: {chk.problems[:5]}")
    check(mt.mapping_of(chk.initial) == FROZEN_MAPPING, f"mapping {mt.mapping_of(chk.initial)}")
    order = [e["target_id"] for e in chk.events]
    check(order == TAS_ORDER, f"TAS order {order}")
    check(mt.break_ticks(chk.events) == TAS_TICKS, f"TAS ticks {mt.break_ticks(chk.events)}")
    moving = [e for e in chk.events if e["target_id"] == 2][0]
    check(moving["break_pos"] == TAS_MOVING_BREAK_POS, f"moving target broke at {moving['break_pos']}")
    check(t["submitted"] == 447 and t["unsent"] == 21 and t["final_state"] == "EpisodeEnded" and t["exit_code"] == 0,
          f"frozen clear contract {t['submitted']}/{t['unsent']}/{t['final_state']}/{t['exit_code']}")
    last = t["steps"][-1]
    check((last["consumed_tick"], last["observation"]["input_tick"], last["observation"]["time_passed"],
           last["step_count"]) == (446, 447, 446, 447), "446/447/446/447")
    ti = mt.parse_targets((t["result"] or {}).get(mt.RESULT_KEY))
    check(ti.remaining_mask == 0 and ti.break_count == 10 and ti.anomaly_flags == 0, "result target_identity")
    check(set(t["result"]) == RESULT_KEYS | {mt.RESULT_KEY}, f"result keys {sorted(t['result'])}")
    return {"order": order, "ticks": mt.break_ticks(chk.events), "snapshots_checked": chk.snapshots_checked}


def game_default_wire(s: Suite) -> Dict[str, Any]:
    import m7f_trace as tr

    _no_battleship()
    t = tr.run_stepping_trace("tas_default", tr.DEFAULT_EXE, tr.tas_actions(), s.dir("game_default_wire"),
                              extra_env=dict(FLAGS))
    check(set(t["status"]) == STATUS_KEYS, f"status keys {sorted(t['status'])}")
    check(set(t["initial"]) == OBSERVE_KEYS, f"observe keys {sorted(t['initial'])}")
    bad = [i for i, r in enumerate(t["steps"]) if set(r) != STEP_KEYS]
    check(not bad, f"step reply keys differ at {bad[:5]}: {sorted(t['steps'][bad[0]]) if bad else ''}")
    check(set(t["result"] or {}) == RESULT_KEYS, f"result keys {sorted(t['result'] or {})}")
    try:
        mt.require_diag_status(t["status"])
        raise CheckFailed("default status unexpectedly advertises the diagnostic")
    except mt.TargetContractError:
        pass
    return {"steps": len(t["steps"]), "result": t["result"]}


def game_diag_required(s: Suite) -> Dict[str, Any]:
    import m7f_trace as tr

    _no_battleship()
    got: Dict[str, Any] = {}

    def probe(ep: Any) -> None:
        st = ep.client.request("status")
        ob = ep.client.request("observe")
        for label, fn in (("status", lambda: mt.require_diag_status(st)),
                          ("observe", lambda: mt.parse_targets(ob.get(mt.REPLY_KEY)))):
            try:
                fn()
                got[label] = "accepted"
            except mt.TargetContractError as exc:
                got[label] = f"rejected: {exc}"

    tr.run_stepping_trace("no_diag", tr.DEFAULT_EXE, [], s.dir("game_diag_required"), extra_env=dict(FLAGS),
                          on_ready=probe)
    check(all(v.startswith("rejected") for v in got.values()) and len(got) == 2, f"reader outcome {got}")
    return got


def game_native_diag(s: Suite) -> Dict[str, Any]:
    import m7f_trace as tr

    _no_battleship()
    nat = tr.native_tas_replay(tr.DEFAULT_EXE, s.dir("game_native_diag"), diag=True)
    check(nat["exit_code"] == 0 and nat["complete_line"] and nat["checksum_line"],
          f"native replay: exit {nat['exit_code']} lines {nat['replay_lines']}")
    res = nat["result"] or {}
    check((res.get("targets_broken"), res.get("completion_time_passed"), res.get("completion_input_tick")) ==
          (10, 446, 447), f"native result {res}")
    ti = mt.parse_targets(res.get(mt.RESULT_KEY))
    order = [r.id for r in sorted(ti.records, key=lambda r: r.break_order)]
    ticks = sorted(r.break_input_tick - 1 for r in ti.records)
    check(order == TAS_ORDER and ticks == TAS_TICKS and ti.anomaly_flags == 0, f"native order {order} ticks {ticks}")
    check(mt.mapping_of(ti) == FROZEN_MAPPING, "native mapping differs")
    return {"order": order, "checksum": "0x93E9EFB4", "wall_s": nat["wall_s"]}


def game_fixture_replay(s: Suite) -> Dict[str, Any]:
    import m7f_replay as rp

    _no_battleship()
    rel, ids, ticks, remaining = FIXTURE
    art = REPO_ROOT / rel
    md = json.loads((art / "metadata.json").read_text(encoding="utf-8"))
    labels = md.get("labels") or {}
    seq = {"digest": labels["native_action_digest"], "artifact_dir": rel, "strata": ["fixture"], "rows": [],
           "expected": {"targets": 6, "length": md["action_count"], "end_reason": labels.get("end_reason"),
                        "break_ticks": ticks, "last_consumed_tick": md["action_count"] - 1}}
    work = s.dir("game_fixture_replay")
    b = rp.boot(work, 0, 0)
    try:
        rec, _raw = rp.replay_sequence(seq, b, rp.sha256_file(rp.EXECUTABLE))
    finally:
        rp.dispose(b)
    check(rec["ok"], f"replay not exact: {[k for k, v in rec['checks'].items() if not v]} {rec.get('diag_problems')}")
    got = [e["target_id"] for e in rec["events"]]
    check(got == ids and rec["final_remaining_ids"] == remaining, f"ids {got} remaining {rec['final_remaining_ids']}")
    return {"ids": got, "remaining": rec["final_remaining_ids"], "stepping_s": rec["stepping_s"]}


FALL_FIXTURE = "runs/m7d/_eval/m7d_s0_v1/final/deterministic/workers/w00/artifacts/episode_20260922T181810Z_41b8dbcd"


def game_fall_teardown(s: Suite) -> Dict[str, Any]:
    """A historical fall, then neutral steps through End (5) / BossDefeat (6) / Set (7) until the scene task ends
    and the next action can no longer be consumed. Every reply must stay anomaly-free; the item-link cross-check may
    be skipped (link_checked 0) only once the scene task has ejected its objects, never during Go."""
    from battleship_client import BattleShipClient, BattleShipError
    from battleship_process import BattleShipEpisode, LaunchConfig
    from m7_runtime import PortCandidates, prepare_worker_runtime
    from run_artifacts import read_artifact

    import m7f_trace as tr

    _no_battleship()
    work = s.dir("game_fall_teardown")
    prepare_worker_runtime(work / "runtime", tr.DEFAULT_EXE)
    port, _ = PortCandidates(0).claim()
    cfg = LaunchConfig(executable=tr.DEFAULT_EXE, working_dir=work / "runtime", run_root=work / "episodes", port=port,
                       startup_timeout=30.0, ready_timeout=90.0, request_timeout=5.0,
                       extra_env={**FLAGS, mt.DIAG_ENV: "1"})
    (work / "episodes").mkdir()
    acts = read_artifact(REPO_ROOT / FALL_FIXTURE).actions
    replies: List[Dict[str, Any]] = []
    hung_after = None
    with BattleShipEpisode(cfg, index=0) as ep:
        ep.start()
        tr._capture_requests(ep.client, replies)
        initial = ep.client.request("observe")
        replies.clear()
        for a in acts:
            ep.client.step(a.buttons, a.stick_x, a.stick_y)
        fall_at = len(replies)
        for extra in range(400):
            try:
                ep.client.step(0, 0, 0)
            except (BattleShipError, OSError):
                hung_after = extra
                break
    chk = mt.check_trace(initial, replies)
    statuses = [r["observation"]["game_status"] for r in replies[fall_at - 1:]]
    skipped = [i for i, r in enumerate(replies) if r["targets"]["link_checked"] == 0]
    check(hung_after is not None, "the scene never ended within 400 neutral steps after the fall")
    check(chk.ok, f"diagnostic invalid through the teardown: {chk.problems[:5]}")
    check(all(r["targets"]["anomaly_flags"] == 0 for r in replies), "an anomaly flag was raised")
    check(skipped and all(replies[i]["observation"]["game_status"] != mt.GAME_STATUS_GO for i in skipped),
          f"link cross-check skipped at {skipped[:5]} (must be after play stopped, and at least once)")
    return {"fall_steps": fall_at, "neutral_steps_until_unload": hung_after,
            "status_sequence_after_fall": sorted(set(statuses)), "replies_with_link_check_skipped": len(skipped),
            "final_remaining_ids": chk.final.remaining_ids if chk.final else None}


UNIT_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "unit_contract": unit_contract, "unit_manifest": unit_manifest, "unit_analysis": unit_analysis,
    "unit_nonport": unit_nonport, "unit_mapping": unit_mapping,
}
GAME_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "game_tas_diag": game_tas_diag, "game_default_wire": game_default_wire, "game_diag_required": game_diag_required,
    "game_native_diag": game_native_diag, "game_fixture_replay": game_fixture_replay,
    "game_fall_teardown": game_fall_teardown,
}
ALL_CASES = {**UNIT_CASES, **GAME_CASES}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cases", nargs="*", help="case names, 'unit' or 'game' (default: all)")
    ap.add_argument("--root", default=None)
    args = ap.parse_args(argv)
    names: List[str] = []
    for c in args.cases or list(ALL_CASES):
        names += list(UNIT_CASES) if c == "unit" else list(GAME_CASES) if c == "game" else [c]
    unknown = [n for n in names if n not in ALL_CASES]
    if unknown:
        ap.error(f"unknown cases {unknown}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = Path(args.root) if args.root else REPO_ROOT / "runs" / "m7f" / f"_tests_{stamp}"
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if any(n in GAME_CASES for n in names):
        from m7_runtime import install_kill_on_close_job

        install_kill_on_close_job()
    suite = Suite(root)
    results: Dict[str, Any] = {}
    for name in names:
        t0 = time.perf_counter()
        try:
            details = ALL_CASES[name](suite)
            results[name] = {"status": "PASS", "seconds": round(time.perf_counter() - t0, 1), "details": details}
        except Exception as exc:
            results[name] = {"status": "FAIL", "seconds": round(time.perf_counter() - t0, 1),
                             "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-2000:]}
        print(f"{results[name]['status']}  {name}  ({results[name]['seconds']} s)"
              + (f"  {results[name].get('error')}" if results[name]["status"] != "PASS" else ""), flush=True)
    ok = all(r["status"] == "PASS" for r in results.values())
    (root / "m7f_tests_results.json").write_text(json.dumps({"schema": "battleship_m7f_tests_v1", "utc": stamp,
                                                             "results": results, "ok": ok}, indent=1) + "\n",
                                                 encoding="utf-8", newline="\n")
    print(f"m7f_tests: {sum(r['status'] == 'PASS' for r in results.values())}/{len(results)} PASS -> {root}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
