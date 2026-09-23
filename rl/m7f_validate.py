"""M7f Phase D: validate the btt_target_identity_v1 diagnostic and prove the pre/post executable equivalence.

Inputs are capture sets written by rl/m7f_trace.py (same actions, same host modes):
    pre_build   pre-change executable (sha256 57d61fe0...), before any M7f source edit
    pre_copy    the preserved runnable copy of that executable (runs/m7f/_exe/pre_m7f)
    post_off    post-change executable, diagnostic off
    post_on     post-change executable, SSB64_RL_TARGET_DIAG=1
    post_on_r2  the same again (repeatability)
plus a game-backed parked-start check run here (a process parked at tick 0 before its first step, which is what a
standby process is), and the non-PORT source check.

Writes docs/rl_target_identity_m7f_validation.json and docs/rl_target_identity_m7f_mapping.json.
It never trains and never writes below runs/m7d or runs/m7e.

Usage:
    python rl/m7f_validate.py --equiv runs/m7f/_equiv [--skip-parked]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import m7f_targets as mt  # noqa: E402
import m7f_trace as tr  # noqa: E402

REPO_ROOT = RL_DIR.parent
DOC_VALIDATION = REPO_ROOT / "docs" / "rl_target_identity_m7f_validation.json"
DOC_MAPPING = REPO_ROOT / "docs" / "rl_target_identity_m7f_mapping.json"

# The frozen TAS facts (docs/rl_replay_regression_m1e.md, docs/rl_learning_m5.md).
TAS_BREAK_TICKS = [51, 87, 142, 163, 275, 316, 358, 368, 432, 446]
TAS_RETURN = 19.553
PRE_EXE_SHA = "57d61fe0b2a602659e0a1685a58266f652e8ce2ad35f767ace54943da23fc56b"
DECOMP_PINNED = "91d7b6b75e97f46c10ce2f09ac68abe1799213b6"
PARKED_SECONDS = 12.0


def _traces(set_dir: Path) -> Dict[str, Dict[str, Any]]:
    return {p.name[:-len(".json.gz")]: tr.read_trace(p) for p in sorted(Path(set_dir).glob("*.json.gz"))}


def _native(set_dir: Path) -> Optional[Dict[str, Any]]:
    p = Path(set_dir) / "native.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


# -- policy observation / reward recomputation --------------------------------------------------------


def policy_bytes_digest(trace: Mapping[str, Any]) -> Tuple[str, int]:
    """sha256 over the float32 bytes of btt_policy_obs_v1 for the initial observation and every step."""
    from btt_learning import POLICY_FIELDS

    h = hashlib.sha256()
    n = 0
    for reply in [trace["initial"]] + list(trace["steps"]):
        obs = reply["observation"]
        vec = [float(obs[name]) for name in POLICY_FIELDS]
        h.update(struct.pack("<%df" % len(vec), *vec))
        n += 1
    return h.hexdigest(), n


def returns(trace: Mapping[str, Any]) -> Dict[str, float]:
    """Episode return under btt_reward_v1 and v2, step by step exactly as the M5/M7 wrappers apply them."""
    import math

    from battleship_client import Observation, StepState
    from btt_parallel import is_native_failure
    from btt_rewards import REWARD_V1, REWARD_V2, reward_step

    out = {}
    for contract in (REWARD_V1, REWARD_V2):
        prev_obs = trace["initial"]["observation"]
        prev = prev_obs["targets_remaining"] if prev_obs["btt_active"] == 1 else None
        terms = []
        for reply in trace["steps"]:
            obs = reply["observation"]
            state = StepState(reply["state"])
            cur = obs["targets_remaining"] if obs["btt_active"] == 1 else None
            failure = is_native_failure(Observation.from_wire(obs), state)
            terms.append(reward_step(prev, cur, clear=state == StepState.EPISODE_ENDED, native_failure=failure,
                                     contract=contract).total)
            prev = cur if cur is not None else prev
            if failure:
                break
        out[contract.contract] = round(math.fsum(terms), 6)
    return out


def targets_drop_ticks(trace: Mapping[str, Any]) -> List[int]:
    """target_break_ticks exactly as the M7 tracker derives them (targets_remaining drops per consumed tick)."""
    ticks, prev = [], trace["initial"]["observation"]["targets_remaining"]
    for reply in trace["steps"]:
        cur = reply["observation"]["targets_remaining"]
        ticks.extend([reply["consumed_tick"]] * max(0, prev - cur))
        prev = cur
    return ticks


def historical_row(artifact_rel: str) -> Optional[Dict[str, Any]]:
    """The evaluation row that produced a fixture artifact (for raw_return and target_break_ticks)."""
    art = REPO_ROOT / artifact_rel
    mode_dir = art.parent.parent.parent.parent  # .../<mode>/workers/wNN/artifacts/<id>
    ev = mode_dir / "evaluation.json"
    if not ev.is_file():
        return None
    for row in json.loads(ev.read_text(encoding="utf-8")).get("episodes") or []:
        if row.get("episode_id") == art.name:
            return row
    return None


# -- the parked-start (standby) check -------------------------------------------------------------------


def parked_capture(out: Path) -> Dict[str, Dict[str, Any]]:
    """Launch fresh processes with the diagnostic on, leave each parked at tick 0 for PARKED_SECONDS (a standby
    process is exactly that: booted early, parked in WaitingForAction, used later), then step."""
    exe = tr.DEFAULT_EXE
    env = {**tr.MODES[tr.HISTORICAL_MODE], mt.DIAG_ENV: "1"}
    park = lambda _ep: time.sleep(PARKED_SECONDS)  # noqa: E731
    got = {}
    got["tas_no_render_raphnet"] = tr.run_stepping_trace("parked_tas", exe, tr.tas_actions(), out / "tas",
                                                         extra_env=env, on_ready=park)
    name, rel = tr.FIXTURE_ARTIFACTS[0]
    acts, _md = tr.artifact_actions(REPO_ROOT / rel)
    got[f"fx_{name}"] = tr.run_stepping_trace(f"parked_{name}", exe, acts, out / name, extra_env=env, on_ready=park)
    for k, v in got.items():
        tr.write_trace(out / f"{k}.json.gz", v)
    return got


# -- main validation ----------------------------------------------------------------------------------


def validate(equiv: Path, *, run_parked: bool) -> Dict[str, Any]:
    from m7_runtime import file_fingerprint, list_processes_named

    equiv = Path(equiv)
    report: Dict[str, Any] = {"schema": "battleship_m7f_target_validation_v1", "contract": mt.CONTRACT_ID,
                              "equiv_root": str(equiv.relative_to(REPO_ROOT).as_posix()), "checks": {}}
    checks = report["checks"]
    user_cfg = REPO_ROOT / "build-us" / "Release" / "BattleShip.cfg.json"
    report["user_config_before"] = file_fingerprint(user_cfg)

    summaries = {name: json.loads((equiv / name / "summary.json").read_text(encoding="utf-8"))
                 for name in ("pre_build", "pre_copy", "post_off", "post_on", "post_on_r2")
                 if (equiv / name / "summary.json").is_file()}
    report["executables"] = {k: {"sha256": v["executable_sha256"], "diag": v["diag"], "path": v["executable"]}
                             for k, v in summaries.items()}
    pre_sha = summaries["pre_build"]["executable_sha256"]
    post_sha = summaries["post_on"]["executable_sha256"]
    checks["pre_exe_is_m7e_exe"] = pre_sha == PRE_EXE_SHA
    checks["post_exe_differs"] = post_sha != pre_sha and summaries["post_off"]["executable_sha256"] == post_sha

    # 1. Equivalence of whole reply sequences.
    eq = {}
    eq["pre_build_vs_pre_copy"] = tr.compare_sets(equiv / "pre_build", equiv / "pre_copy")
    strict = {}
    pre_t, off_t = _traces(equiv / "pre_build"), _traces(equiv / "post_off")
    for label in pre_t:
        strict[label] = tr.compare_stepping(pre_t[label], off_t[label], ignore=(), ignore_result=())
        # the default status must not even carry the new key
        strict[label]["status_keys_equal"] = set(pre_t[label]["status"]) == set(off_t[label]["status"])
    strict["native"] = tr.compare_native(_native(equiv / "pre_build"), _native(equiv / "post_off"), ignore_result_keys=())
    eq["pre_build_vs_post_off_strict"] = {"comparisons": strict,
                                          "all_identical": all(c["identical"] and c.get("status_keys_equal", True)
                                                               for c in strict.values())}
    eq["pre_build_vs_post_on_excluding_diag"] = tr.compare_sets(equiv / "pre_build", equiv / "post_on")
    on_t, r2_t = _traces(equiv / "post_on"), _traces(equiv / "post_on_r2")
    rep = {label: tr.compare_stepping(on_t[label], r2_t[label], ignore=(), ignore_result=()) for label in on_t}
    eq["post_on_vs_post_on_r2_including_diag"] = {"comparisons": rep, "all_identical": all(c["identical"]
                                                                                          for c in rep.values())}
    report["equivalence"] = {k: {"all_identical": v["all_identical"],
                                 "problems": {n: c["problems"] for n, c in v["comparisons"].items() if not c["identical"]}}
                             for k, v in eq.items()}
    for k, v in eq.items():
        checks[f"equivalence_{k}"] = v["all_identical"]

    # 2. Diagnostic validity in every diag-on trace, mapping stability across processes.
    per_trace: Dict[str, Any] = {}
    signatures = set()
    diag_sets = {"post_on": on_t, "post_on_r2": r2_t}
    parked = {}
    if run_parked:
        out = equiv / "parked_on"
        if out.exists():
            parked = _traces(out)
        else:
            parked = parked_capture(out)
        diag_sets["parked_on"] = parked
    for set_name, traces in diag_sets.items():
        for label, t in traces.items():
            mt.require_diag_status(t["status"])
            chk = mt.check_trace(t["initial"], t["steps"])
            signatures.add(mt.static_signature(chk.initial) if chk.initial else None)
            per_trace[f"{set_name}/{label}"] = {
                "ok": chk.ok, "problems": chk.problems, "snapshots_checked": chk.snapshots_checked,
                "events": [(e["target_id"], e["consumed_tick"], e["input_tick"], e["native_break_time_passed"])
                           for e in chk.events],
                "final_remaining_ids": chk.final.remaining_ids if chk.final else None,
                "break_ticks_from_ids": mt.break_ticks(chk.events),
                "break_ticks_from_counts": targets_drop_ticks(t),
            }
    report["diagnostic_traces"] = per_trace
    checks["all_diag_traces_valid"] = all(v["ok"] for v in per_trace.values())
    checks["break_ticks_ids_equal_counts"] = all(v["break_ticks_from_ids"] == v["break_ticks_from_counts"]
                                                 for v in per_trace.values())
    checks["mapping_identical_across_processes"] = len(signatures) == 1 and None not in signatures
    report["processes_with_mapping"] = len(per_trace)

    # 3. TAS: ten events, frozen ticks, clear, native replay agreement, host modes.
    tas = mt.check_trace(on_t["tas_no_render_raphnet"]["initial"], on_t["tas_no_render_raphnet"]["steps"])
    tas_events = [{"target_id": e["target_id"], "consumed_tick": e["consumed_tick"], "input_tick": e["input_tick"],
                   "break_order": e["break_order"], "native_break_input_tick": e["native_break_input_tick"],
                   "native_break_time_passed": e["native_break_time_passed"], "break_pos": e["break_pos"]}
                  for e in tas.events]
    report["tas"] = {"events": tas_events, "order": [e["target_id"] for e in tas_events],
                     "final_remaining": tas.final.remaining_ids if tas.final else None}
    checks["tas_ten_unique_breaks"] = len(tas.events) == 10 and len({e["target_id"] for e in tas.events}) == 10
    checks["tas_break_ticks_frozen"] = mt.break_ticks(tas.events) == TAS_BREAK_TICKS
    checks["tas_clear_zero_active"] = bool(tas.final and tas.final.remaining_mask == 0 and
                                           on_t["tas_no_render_raphnet"]["final_state"] == "EpisodeEnded")
    checks["tas_input_tick_is_consumed_plus_one"] = all(e["input_tick"] == e["consumed_tick"] + 1 ==
                                                       e["native_break_input_tick"] for e in tas.events)
    checks["tas_break_time_passed_is_consumed"] = all(e["native_break_time_passed"] == e["consumed_tick"]
                                                      for e in tas.events)
    modes_same = all(tr._typed_equal([s.get(mt.REPLY_KEY) for s in on_t[f"tas_{m}"]["steps"]],
                                     [s.get(mt.REPLY_KEY) for s in on_t["tas_normal"]["steps"]])
                     and tr._typed_equal(on_t[f"tas_{m}"]["initial"].get(mt.REPLY_KEY),
                                         on_t["tas_normal"]["initial"].get(mt.REPLY_KEY))
                     for m in tr.MODES)
    checks["tas_diag_identical_across_host_modes"] = modes_same
    nat_on = _native(equiv / "post_on")
    nat_ti = (nat_on or {}).get("result", {}).get(mt.RESULT_KEY)
    native_ok = False
    if nat_ti is not None:
        snap = mt.parse_targets(nat_ti)
        by_id_native = {r.id: (r.break_order, r.break_input_tick, r.break_time_passed) for r in snap.records}
        by_id_step = {e["target_id"]: (e["break_order"], e["native_break_input_tick"], e["native_break_time_passed"])
                      for e in tas_events}
        native_ok = (snap.remaining_mask == 0 and snap.break_count == 10 and snap.anomaly_flags == 0 and
                     by_id_native == by_id_step and mt.static_signature(snap) in signatures)
        report["tas"]["native_replay_target_identity"] = nat_ti
    checks["tas_native_replay_matches_stepping"] = native_ok
    checks["native_checksum_post_on"] = bool(nat_on and nat_on["checksum_line"] and nat_on["complete_line"])
    checks["native_checksum_post_off"] = bool(_native(equiv / "post_off") and _native(equiv / "post_off")["checksum_line"])

    # 4. Fixtures: historical break ticks, rewards, policy observation, canonical actions.
    fixtures = {}
    for name, rel in tr.FIXTURE_ARTIFACTS:
        label = f"fx_{name}"
        row = historical_row(rel) or {}
        pre, post = pre_t[label], on_t[label]
        chk = mt.check_trace(post["initial"], post["steps"])
        pol_pre, n_pre = policy_bytes_digest(pre)
        pol_post, n_post = policy_bytes_digest(post)
        ret_pre, ret_post = returns(pre), returns(post)
        contract = "btt_reward_v1" if "_v1" in rel else "btt_reward_v2"
        fixtures[label] = {
            "artifact": rel, "episode_id": row.get("episode_id"), "historical_targets": row.get("targets_broken"),
            "historical_break_ticks": row.get("target_break_ticks"), "historical_end": row.get("end_reason"),
            "historical_raw_return": row.get("raw_return"), "contract": contract,
            "break_ticks_diag": mt.break_ticks(chk.events),
            "ids_in_order": [e["target_id"] for e in chk.events],
            "final_remaining_ids": chk.final.remaining_ids if chk.final else None,
            "policy_obs_sha256_pre": pol_pre, "policy_obs_sha256_post": pol_post, "policy_vectors": n_post,
            "returns_pre": ret_pre, "returns_post": ret_post,
            "action_digest_post": post["action_digest"], "recorded_digest": post.get("recorded_digest"),
        }
        f = fixtures[label]
        f["checks"] = {
            "diag_valid": chk.ok,
            "break_ticks_equal_history": f["break_ticks_diag"] == f["historical_break_ticks"],
            "targets_equal_history": len(chk.events) == f["historical_targets"],
            "policy_obs_identical": pol_pre == pol_post and n_pre == n_post,
            "returns_identical": ret_pre == ret_post,
            "return_equals_history": (f["historical_raw_return"] is not None and
                                      abs(ret_post[contract] - f["historical_raw_return"]) < 1e-9),
            "actions_equal_record": f["action_digest_post"] == f["recorded_digest"],
        }
    report["fixtures"] = fixtures
    for key in ("diag_valid", "break_ticks_equal_history", "targets_equal_history", "policy_obs_identical",
                "returns_identical", "return_equals_history", "actions_equal_record"):
        checks[f"fixtures_{key}"] = all(f["checks"][key] for f in fixtures.values())
    tas_pol_pre, _ = policy_bytes_digest(pre_t["tas_no_render_raphnet"])
    tas_pol_post, _ = policy_bytes_digest(on_t["tas_no_render_raphnet"])
    tas_ret = returns(on_t["tas_no_render_raphnet"])
    report["tas"]["returns"] = tas_ret
    checks["tas_policy_obs_identical"] = tas_pol_pre == tas_pol_post
    checks["tas_return_19_553_v1_v2"] = abs(tas_ret["btt_reward_v1"] - TAS_RETURN) < 1e-9 and \
        abs(tas_ret["btt_reward_v2"] - TAS_RETURN) < 1e-9
    tas_off = off_t["tas_no_render_raphnet"]
    checks["tas_frozen_contract"] = (tas_off["submitted"] == 447 and tas_off["unsent"] == 21 and
                                     tas_off["steps"][-1]["consumed_tick"] == 446 and
                                     tas_off["steps"][-1]["observation"]["input_tick"] == 447 and
                                     tas_off["steps"][-1]["observation"]["time_passed"] == 446 and
                                     tas_off["steps"][-1]["step_count"] == 447 and tas_off["exit_code"] == 0)

    # 5. Parked (standby-like) start equals an immediate start, everything included.
    if parked:
        pc = {k: tr.compare_stepping(on_t[k], parked[k], ignore=(), ignore_result=()) for k in parked}
        report["parked_vs_immediate"] = {k: {"identical": v["identical"], "problems": v["problems"]} for k, v in pc.items()}
        checks["parked_start_identical_including_diag"] = all(v["identical"] for v in pc.values())

    # 6. Non-PORT source view of the edited decomp files.
    import m7f_nonport_view as nv

    nonport = [nv.compare(f, DECOMP_PINNED) for f in ("decomp/src/sc/sc1pmode/sc1pbonusstage.c",
                                                       "decomp/src/it/itground/ittarget.c")]
    report["nonport_view"] = nonport
    checks["nonport_view_identical"] = all(r["nonport_identical"] for r in nonport)

    report["user_config_after"] = file_fingerprint(user_cfg)
    checks["user_config_unchanged"] = report["user_config_before"]["sha256"] == report["user_config_after"]["sha256"]
    report["leftover_battleship"] = list_processes_named()
    checks["no_leftover_process"] = not report["leftover_battleship"]
    report["all_passed"] = all(checks.values())
    report["failed_checks"] = [k for k, v in checks.items() if not v]
    return report


def mapping_doc(report: Mapping[str, Any], equiv: Path) -> Dict[str, Any]:
    on_t = _traces(Path(equiv) / "post_on")
    chk = mt.check_trace(on_t["tas_no_render_raphnet"]["initial"], on_t["tas_no_render_raphnet"]["steps"])
    tas_by_id = {e["target_id"]: e for e in chk.events}
    moving_breaks = []
    for label, t in on_t.items():
        c = mt.check_trace(t["initial"], t["steps"])
        for e in c.events:
            if chk.initial.records[e["target_id"]].animated:
                moving_breaks.append({"trace": label, "consumed_tick": e["consumed_tick"], "break_pos": e["break_pos"]})
    rows = []
    for m in mt.mapping_of(chk.initial):
        e = tas_by_id.get(m["id"], {})
        rows.append({**m, "tas_break_order": e.get("break_order"), "tas_break_consumed_tick": e.get("consumed_tick"),
                     "tas_break_pos": e.get("break_pos")})
    return {"schema": "battleship_m7f_target_mapping_v1", "contract": mt.CONTRACT_ID,
            "source": "native: RLTargetDiag records of the post-M7f executable (spawn loop of "
                      "sc1PBonusStageMakeTargets); identical in every validated process",
            "executable_sha256": report["executables"]["post_on"]["sha256"],
            "id_rule": "target ID = spawn loop index of sc1PBonusStageMakeTargets = stage-file target DObjDesc "
                       "index - 1 (entry 0 is the skipped root)",
            "stage_geometry": {"wall_left_face_x": mt.WALL_LEFT_FACE_X, "wall_right_face_x": mt.WALL_RIGHT_FACE_X,
                               "right_block_x": mt.RIGHT_BLOCK_X, "player_spawn": [0, -2547],
                               "source": "decomp/src/relocData/124_GRBonus1MarioFile2.c MPVertexData / MPMapObjData"},
            "region_rules": {"left_of_wall": "spawn x < -2100", "central": "-1800 < spawn x < 2100",
                             "right": "spawn x > 2100 and not animated", "upper_right_moving": "animated == 1"},
            "targets": rows, "moving_target_break_positions": moving_breaks,
            "processes_agreeing": report["processes_with_mapping"]}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--equiv", type=Path, default=REPO_ROOT / "runs" / "m7f" / "_equiv")
    ap.add_argument("--skip-parked", action="store_true")
    ap.add_argument("--no-docs", action="store_true")
    args = ap.parse_args(argv)
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    report = validate(args.equiv.resolve(), run_parked=not args.skip_parked)
    if not args.no_docs:
        DOC_VALIDATION.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n")
        DOC_MAPPING.write_text(json.dumps(mapping_doc(report, args.equiv.resolve()), indent=1) + "\n",
                               encoding="utf-8", newline="\n")
    for k, v in report["checks"].items():
        print(f"{'PASS' if v else 'FAIL'}  {k}")
    print(f"TAS order: {report['tas']['order']}")
    print("ALL PASSED" if report["all_passed"] else f"FAILED: {report['failed_checks']}")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
