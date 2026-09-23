"""M7g-b Phase J: gameplay equivalence and native-invariant validation of the spatial diagnostic / observation v2.

Reuses the M7f trace machinery (rl/m7f_trace.py: fresh process per trace, raw replies of status / observe / every
step, native 468-row replay) and compares against the M7f reference sets captured with executable 10e8e15d
(runs/m7f/_equiv/post_off: diagnostics off; post_on: SSB64_RL_TARGET_DIAG=1), read-only.

    capture  --out DIR --variant spatial|spatial_diag   TAS in every host mode + the 8 pinned historical Track 1
                                                        artifacts (historical mode) + the native replay, with
                                                        SSB64_RL_SPATIAL=1 (and the M7f diagnostic for spatial_diag)
    compare  REF CAND                                   every reply / result / native line identical except the
                                                        additive `spatial` object and `spatial_diag` status key
    validate DIR [DIR ...]                              parse every spatial object; native invariants; static table;
                                                        live mask vs M7f remaining_mask; offline v2 observations
                                                        (v1 state bytes, determinism across modes / repeats)

Writes only below --out / --json. Never trains, never touches historical runs or the M7g-a fixtures.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import numpy as np  # noqa: E402

import m7f_trace as mt  # noqa: E402
import m7g_obs as mo  # noqa: E402
import m7g_spatial as ms  # noqa: E402
from btt_learning import policy_observation  # noqa: E402

REPO_ROOT = RL_DIR.parent
M7F_OFF = REPO_ROOT / "runs" / "m7f" / "_equiv" / "post_off"
M7F_ON = REPO_ROOT / "runs" / "m7f" / "_equiv" / "post_on"
VARIANTS = {"spatial": {ms.SPATIAL_ENV: "1"},
            "spatial_diag": {ms.SPATIAL_ENV: "1", mt.TARGET_DIAG_ENV: "1"}}
IGNORED_REPLY_KEYS = (ms.REPLY_KEY, ms.STATUS_KEY)


def native_replay_env(executable: Path, work: Path, extra: Mapping[str, str], *, max_frames: int = 1500
                      ) -> Dict[str, Any]:
    """rl/m7f_trace.py native_tas_replay with extra environment variables (the spatial flag, which the replay must
    ignore: it needs interactive stepping)."""
    from m7_runtime import list_processes_named, prepare_worker_runtime

    work = Path(work).resolve()
    others = list_processes_named()
    if others:
        raise RuntimeError(f"native replay needs to be the only BattleShip process (port log is shared): {others}")
    runtime = work / "runtime"
    prepare_worker_runtime(runtime, executable)
    out = work / "out"
    out.mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("SSB64_")}
    env.update({"SSB64_RL_BTT": "1", "SSB64_BTT_INPUT": str(mt.TAS_PATH), "SSB64_MAX_FRAMES": str(max_frames),
                "SSB64_SAVE_PATH": str(out / "save.bin"), "SSB64_RL_RESULT_PATH": str(out / "result.json")})
    env.update(extra)
    t0 = time.perf_counter()
    r = subprocess.run([str(executable)], cwd=str(runtime), env=env, timeout=300, check=False,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wall = round(time.perf_counter() - t0, 2)
    text = mt.PORT_LOG.read_text(encoding="utf-8", errors="replace") if mt.PORT_LOG.is_file() else ""
    keep = ("BTT Replay", "input exhausted", "SSB64 RL:")
    lines = [ln.strip() for ln in text.splitlines() if any(k in ln for k in keep)]
    spatial_lines = [ln.strip() for ln in text.splitlines() if "SSB64 RL Spatial" in ln]
    result_path = out / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else None
    return {"executable": str(executable), "extra_env": dict(extra), "diag": mt.TARGET_DIAG_ENV in extra,
            "exit_code": r.returncode, "wall_s": wall,
            "complete_line": any("COMPLETE input_tick=447 time_passed=446" in ln for ln in lines),
            "checksum_line": any("frames=468" in ln and "actual_checksum=0x93E9EFB4" in ln for ln in lines),
            "replay_lines": [ln for ln in lines if "BTT Replay" in ln or "input exhausted" in ln],
            "rl_lines": [ln for ln in lines if "SSB64 RL:" in ln], "spatial_log_lines": spatial_lines,
            "result": result}


def capture(executable: Path, out: Path, variant: str, *, modes: Sequence[str] = tuple(mt.MODES),
            fixtures: bool = True, native: bool = True, repeat_tag: str = "") -> Dict[str, Any]:
    from m7_runtime import file_fingerprint, list_processes_named

    out = Path(out).resolve()
    if out.exists():
        raise SystemExit(f"output directory exists: {out}")
    out.mkdir(parents=True)
    extra = VARIANTS[variant]
    user_cfg = REPO_ROOT / "build-us" / "Release" / "BattleShip.cfg.json"
    summary: Dict[str, Any] = {"schema": "battleship_m7g_spatial_trace_set_v1", "executable": str(executable),
                               "executable_sha256": mt.sha256_file(Path(executable)), "variant": variant,
                               "extra_env": extra, "modes": list(modes), "fixtures": fixtures, "native": native,
                               "user_config_before": file_fingerprint(user_cfg), "traces": {}}
    index = 0
    tas = mt.tas_actions()
    for mode in modes:
        label = f"tas_{mode}{repeat_tag}"
        mt.log(f"{label}: stepping {len(tas)} TAS rows ({variant})")
        tr = mt.run_stepping_trace(label, executable, tas, out / "work" / label, extra_env={**mt.MODES[mode], **extra},
                                   index=index)
        index += 1
        mt.write_trace(out / f"{label}.json.gz", tr)
        summary["traces"][label] = {k: tr.get(k) for k in ("submitted", "unsent", "final_state", "exit_code",
                                                          "action_digest", "startup_s", "stepping_s")}
    if fixtures:
        for name, rel in mt.FIXTURE_ARTIFACTS:
            acts, md = mt.artifact_actions(REPO_ROOT / rel)
            label = f"fx_{name}{repeat_tag}"
            mt.log(f"{label}: stepping {len(acts)} recorded actions ({variant})")
            tr = mt.run_stepping_trace(label, executable, acts, out / "work" / label,
                                       extra_env={**mt.MODES[mt.HISTORICAL_MODE], **extra}, index=index)
            index += 1
            tr["artifact"] = rel
            tr["recorded_digest"] = (md.get("labels") or {}).get("native_action_digest")
            mt.write_trace(out / f"{label}.json.gz", tr)
            summary["traces"][label] = {k: tr.get(k) for k in ("submitted", "unsent", "final_state", "exit_code",
                                                              "action_digest", "recorded_digest", "stepping_s")}
    if native:
        mt.log(f"native 468-row replay with {extra}")
        nat = native_replay_env(Path(executable), out / "work" / f"native{repeat_tag}", extra)
        (out / f"native{repeat_tag}.json").write_text(json.dumps(nat, indent=1) + "\n", encoding="utf-8")
        summary["traces"][f"native{repeat_tag}"] = {k: nat.get(k) for k in ("exit_code", "complete_line",
                                                                            "checksum_line", "spatial_log_lines")}
    summary["user_config_after"] = file_fingerprint(user_cfg)
    summary["leftover_battleship"] = list_processes_named()
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    return summary


def _strip_all(reply: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    return None if reply is None else {k: v for k, v in reply.items() if k not in IGNORED_REPLY_KEYS}


def _tagged(name: str, tag: str) -> str:
    """tas_normal.json.gz + _r2 -> tas_normal_r2.json.gz (the capture's --repeat-tag naming)."""
    for ext in (".json.gz", ".json"):
        if name.endswith(ext):
            return name[:-len(ext)] + tag + ext
    return name + tag


def compare(ref_dir: Path, cand_dir: Path, tag: str = "") -> Dict[str, Any]:
    """Every reference reply equals the candidate reply minus the additive spatial keys (value AND JSON type); status
    replies, result JSON, exit codes and digests likewise; native replays identical (result JSON strictly). `tag` is
    the candidate set's repeat tag (its file names carry it; the trace labels are not compared)."""
    ref_dir, cand_dir = Path(ref_dir), Path(cand_dir)
    report: Dict[str, Any] = {"reference": str(ref_dir), "candidate": str(cand_dir), "ignored_keys":
                              list(IGNORED_REPLY_KEYS), "comparisons": {}}
    for p in sorted(ref_dir.glob("*.json.gz")):
        q = cand_dir / _tagged(p.name, tag)
        if not q.is_file():
            report["comparisons"][p.name] = {"identical": False, "problems": ["missing in candidate"]}
            continue
        ref, cand = mt.read_trace(p), mt.read_trace(q)
        cand = {**cand, "label": ref.get("label")}
        problems: List[str] = []
        if not mt._typed_equal(ref.get("status"), _strip_all(cand.get("status"))):
            problems.append("status differs")
        if cand.get("status", {}).get(ms.STATUS_KEY) is not True:
            problems.append("candidate status lacks spatial_diag")
        r = mt.compare_stepping(ref, {**cand, "status": ref.get("status"),
                                      "initial": _strip_all(cand.get("initial")),
                                      "steps": [_strip_all(s) for s in cand.get("steps") or []]},
                                ignore=(), ignore_result=())
        problems += r["problems"]
        missing = sum(1 for s in [cand.get("initial")] + list(cand.get("steps") or []) if ms.REPLY_KEY not in s)
        if missing:
            problems.append(f"{missing} candidate replies without a spatial object")
        report["comparisons"][p.name] = {"identical": not problems, "problems": problems,
                                         "steps_compared": r["steps_compared"]}
    for p in sorted(ref_dir.glob("native*.json")):
        q = cand_dir / _tagged(p.name, tag)
        if q.is_file():
            report["comparisons"][p.name] = mt.compare_native(json.loads(p.read_text(encoding="utf-8")),
                                                              json.loads(q.read_text(encoding="utf-8")),
                                                              ignore_result_keys=())
    report["all_identical"] = bool(report["comparisons"]) and all(c["identical"] for c in
                                                                   report["comparisons"].values())
    return report


# -- validation -------------------------------------------------------------------------------------------------

def v2_observations(trace: Mapping[str, Any]) -> Tuple[List[Dict[str, np.ndarray]], List[bool], Dict[str, Any]]:
    """Offline v2 observations of one raw trace with the production builder (reset observe + every step)."""
    initial = trace["initial"]
    snap0 = ms.spatial_of(initial, expect_lines=True)
    builder = mo.SpatialObservationBuilder(snap0.lines or ())
    obs_list: List[Dict[str, np.ndarray]] = []
    stale: List[bool] = []
    state_mismatch = 0
    for i, reply in enumerate([initial] + list(trace.get("steps") or [])):
        snap = snap0 if i == 0 else ms.spatial_of(reply, expect_lines=False)
        state = policy_observation(reply["observation"])
        obs, st = builder.build(state, reply["observation"], snap)
        if obs[mo.STATE_KEY].tobytes() != state.tobytes():
            state_mismatch += 1
        obs_list.append(obs)
        stale.append(st)
    return obs_list, stale, {"state_bytes_mismatch": state_mismatch, "segments": builder.segment_count}


def validate_trace(trace: Mapping[str, Any], *, remaining_check: bool) -> Dict[str, Any]:
    """Native invariants of every spatial object in one trace (see m7g_spatial.check_snapshot)."""
    problems: List[str] = []
    initial = trace["initial"]
    snap0 = ms.spatial_of(initial, expect_lines=True)
    table = ms.expected_table_problems(snap0.lines or ())
    if table:
        problems.append(f"static table: {table}")
    static_targets = {i: snap0.target_positions[i] for i in range(ms.TARGET_COUNT)
                      if i != ms.MOVING_TARGET_ID and snap0.target_live_mask & (1 << i)}
    prev = None
    prev_obs = None
    counts = {"replies": 0, "live": 0, "not_live": 0, "on_platform": 0, "carry_checked": 0, "target2_live": 0,
              "mask_vs_m7f": 0, "contact_rwall13": 0}
    max_t2 = 0.0
    replies = [initial] + list(trace.get("steps") or [])
    for i, reply in enumerate(replies):
        snap = snap0 if i == 0 else ms.spatial_of(reply, expect_lines=False)
        obs = reply["observation"]
        counts["replies"] += 1
        counts["live" if snap.live else "not_live"] += 1
        for msg in ms.check_snapshot(snap, obs, prev=prev, prev_observation=prev_obs, static_targets=static_targets):
            problems.append(f"reply {i} (tick {obs['input_tick']}): {msg}")
        if snap.live:
            ty = snap.groups[ms.PLATFORM_GROUP].translate[1]
            if snap.target_live_mask & (1 << ms.MOVING_TARGET_ID):
                counts["target2_live"] += 1
                max_t2 = max(max_t2, abs(snap.target_positions[ms.MOVING_TARGET_ID][1] - (ty + 600.0)))
            f = snap.fighter
            if ms.on_platform(snap, obs):
                counts["on_platform"] += 1
                counts["carry_checked"] += int(ms.on_platform(prev, prev_obs))
            if f.valid and f.mask_curr & ms.CONTACT_RWALL and f.rwall_line_id == 13:
                counts["contact_rwall13"] += 1
        if remaining_check and "targets" in reply:
            counts["mask_vs_m7f"] += 1
            rm = int(reply["targets"]["remaining_mask"])
            if snap.live and snap.target_live_mask != rm:
                problems.append(f"reply {i}: live mask {snap.target_live_mask} != M7f remaining_mask {rm}")
        prev, prev_obs = snap, obs
    return {"problems": problems[:50], "problem_count": len(problems), "counts": counts,
            "max_target2_offset_deviation": max_t2}


def trace_group(name: str) -> str:
    """Traces that must give identical v2 observations: the TAS in every host mode and repeat; each historical
    artifact across repeats (a repeat tag is `_r<n>`)."""
    base = name[:-len(".json.gz")] if name.endswith(".json.gz") else name
    base = re.sub(r"_r\d+$", "", base)
    return "tas" if base.startswith("tas_") else base


def validate(dirs: Sequence[Path]) -> Dict[str, Any]:
    report: Dict[str, Any] = {"sets": {}, "v2_determinism": {}}
    chains: Dict[str, Dict[str, str]] = {}
    space = mo.make_observation_space()
    for d in dirs:
        d = Path(d)
        summary = json.loads((d / "summary.json").read_text(encoding="utf-8"))
        diag = summary.get("variant") == "spatial_diag"
        sets: Dict[str, Any] = {}
        for p in sorted(d.glob("*.json.gz")):
            tr = mt.read_trace(p)
            v = validate_trace(tr, remaining_check=diag)
            obs_list, stale, meta = v2_observations(tr)
            chain = hashlib.sha256("".join(mo.observation_digest(o) for o in obs_list).encode("ascii")).hexdigest()
            chains.setdefault(trace_group(p.name), {})[f"{d.name}/{p.name}"] = chain
            sets[p.name] = {**v, "v2_steps": len(obs_list), "v2_stale": sum(stale),
                            "v2_contained": all(space.contains(o) for o in obs_list), **meta, "v2_digest_chain": chain}
        report["sets"][str(d)] = sets
    for group, runs in chains.items():
        report["v2_determinism"][group] = {"runs": len(runs), "identical": len(set(runs.values())) == 1,
                                           "chains": runs}
    report["all_valid"] = all(s["problem_count"] == 0 and s["state_bytes_mismatch"] == 0 and s["v2_contained"]
                              for sets in report["sets"].values() for s in sets.values()) and \
        all(g["identical"] for g in report["v2_determinism"].values())
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--exe", type=Path, default=mt.DEFAULT_EXE)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--variant", choices=sorted(VARIANTS), required=True)
    c.add_argument("--modes", default=",".join(mt.MODES))
    c.add_argument("--no-fixtures", action="store_true")
    c.add_argument("--no-native", action="store_true")
    c.add_argument("--repeat-tag", default="")
    k = sub.add_parser("compare")
    k.add_argument("reference", type=Path)
    k.add_argument("candidate", type=Path)
    k.add_argument("--tag", default="", help="the candidate set's --repeat-tag")
    k.add_argument("--json", type=Path)
    v = sub.add_parser("validate")
    v.add_argument("dirs", type=Path, nargs="+")
    v.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "capture":
        s = capture(a.exe, a.out, a.variant, modes=[m for m in a.modes.split(",") if m], fixtures=not a.no_fixtures,
                    native=not a.no_native, repeat_tag=a.repeat_tag)
        print(json.dumps({k: s[k] for k in ("executable_sha256", "variant", "leftover_battleship")}, indent=1))
        return 0 if not s["leftover_battleship"] and s["user_config_before"] == s["user_config_after"] else 1
    if a.cmd == "compare":
        r = compare(a.reference, a.candidate, a.tag)
        for name, cmp in r["comparisons"].items():
            print(("IDENTICAL " if cmp["identical"] else "DIFFERENT ") + f" {name}  " + "; ".join(cmp["problems"][:3]))
        print("ALL IDENTICAL" if r["all_identical"] else "DIFFERENCES FOUND")
        if a.json:
            a.json.write_text(json.dumps(r, indent=1) + "\n", encoding="utf-8")
        return 0 if r["all_identical"] else 1
    r = validate(a.dirs)
    for d, sets in r["sets"].items():
        for name, s in sets.items():
            print(f"{'OK ' if s['problem_count'] == 0 and s['state_bytes_mismatch'] == 0 else 'BAD'} {Path(d).name}/"
                  f"{name}: replies {s['counts']['replies']} live {s['counts']['live']} platform "
                  f"{s['counts']['on_platform']} t2dev {s['max_target2_offset_deviation']:.6f} "
                  f"problems {s['problem_count']} {s['problems'][:2]}")
    for g, dd in r["v2_determinism"].items():
        print(f"v2 determinism {g}: runs {dd['runs']} identical {dd['identical']}")
    print("ALL VALID" if r["all_valid"] else "VALIDATION PROBLEMS")
    if a.json:
        a.json.write_text(json.dumps(r, indent=1) + "\n", encoding="utf-8")
    return 0 if r["all_valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
