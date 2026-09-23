"""M7f: full-trace capture and executable-equivalence comparison.

Captures what a BattleShip executable does with a fixed action sequence, at the finest granularity the RL bridge
exposes, so a pre-change and a post-change executable (or one executable with the M7f target diagnostic on and off)
can be compared field by field:

  * stepping traces: a fresh process, the raw `status` and `observe` replies, then one raw `step` reply per submitted
    action (every top-level key, the full 17-field observation), the terminal result JSON and exit code on a clear;
  * native replay: the authoritative 468-row `tas_input_2/mario_743.btti` replay (SSB64_BTT_INPUT, no stepping), the
    result JSON and the completion / checksum lines of the port log.

Comparisons ignore exactly one top-level key, `targets` (the opt-in M7f diagnostic), plus the status-only mode booleans
that a newer executable may add; everything else (state, step_count, consumed_tick, all 17 observation fields including
host_frame, result JSON, exit codes, log lines) must be identical.

This module launches BattleShip; it never trains, never touches runs/m7d or runs/m7e, and writes only below --out.

Usage:
    python rl/m7f_trace.py capture --exe build-us/Release/BattleShip.exe --out runs/m7f/_equiv/pre [--diag]
    python rl/m7f_trace.py compare runs/m7f/_equiv/pre runs/m7f/_equiv/post_off
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

REPO_ROOT = RL_DIR.parent
DEFAULT_EXE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
TAS_PATH = REPO_ROOT / "tas_input_2" / "mario_743.btti"
PORT_LOG = Path(os.environ.get("APPDATA", "")) / "BattleShip" / "ssb64.log"

TARGET_DIAG_ENV = "SSB64_RL_TARGET_DIAG"
DIAG_KEY = "targets"
DIAG_RESULT_KEY = "target_identity"  # the additive trailing object of a clear's result JSON (diagnostic on)
# Host modes of the M6 equivalence regression; the historical M7d/M7e runs used the last one.
MODES: Dict[str, Dict[str, str]] = {
    "normal": {},
    "no_render": {"SSB64_RL_NO_RENDER": "1"},
    "no_render_raphnet": {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1"},
}
HISTORICAL_MODE = "no_render_raphnet"
# Status keys that only report per-process modes; a newer executable may add one (M7f adds `target_diag`).
STATUS_MODE_KEYS = ("no_render", "raphnet_disabled", "target_diag")

# Pinned historical artifacts (native action traces, canonical replay truth) covering horizon and fall endings,
# six-target episodes of every M7e seed, same-tick double breaks, a deterministic collapse and random play.
FIXTURE_ARTIFACTS: Tuple[Tuple[str, str], ...] = (
    ("m7e_s0_best6", "runs/m7e/_eval/m7e_s0_v2/curve_t001228800/stochastic/workers/w02/artifacts/"
                     "episode_20260923T014311Z_3e92f774"),
    ("m7e_s1_best6", "runs/m7e/_eval/m7e_s1_v2/curve_t000614400/stochastic/workers/w04/artifacts/"
                     "episode_20260923T021450Z_a76a9bac"),
    ("m7e_s2_best6", "runs/m7e/_eval/m7e_s2_v2/curve_t001536000/stochastic/workers/w01/artifacts/"
                     "episode_20260923T025637Z_f7f43030"),
    ("m7d_s0v1_det_fall", "runs/m7d/_eval/m7d_s0_v1/final/deterministic/workers/w00/artifacts/"
                          "episode_20260922T181810Z_41b8dbcd"),
    ("m7d_s0v1_fall6_double", "runs/m7d/_eval/m7d_s0_v1/final/stochastic/workers/w03/artifacts/"
                              "episode_20260922T182432Z_e5c67c95"),
    ("m7d_s2v2_double56", "runs/m7d/_eval/m7d_s2_v2/curve_t000307200/stochastic/workers/w00/artifacts/"
                          "episode_20260922T201628Z_abba56eb"),
    ("m7e_s2_final_det", "runs/m7e/_eval/m7e_s2_v2/final/deterministic/workers/w00/artifacts/"
                         "episode_20260923T030653Z_0138a5e0"),
    ("random_six", "runs/m7e/_eval/random_baseline/random/workers/w00/artifacts/episode_20260923T012518Z_d58d4a9d"),
)

Action = Tuple[int, int, int, Optional[int]]  # buttons, stick_x, stick_y, expected consumed_tick (or None)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def log(message: str) -> None:
    print(f"[m7f_trace] {message}", flush=True)


# -- action sources ---------------------------------------------------------------------------------


def tas_actions() -> List[Action]:
    from btti_replay import read_btti_rows

    return [(r.buttons, r.stick_x, r.stick_y, i) for i, r in enumerate(read_btti_rows(str(TAS_PATH)))]


def artifact_actions(artifact_dir: Path) -> Tuple[List[Action], Dict[str, Any]]:
    from run_artifacts import read_artifact

    art = read_artifact(artifact_dir)
    return [(a.buttons, a.stick_x, a.stick_y, a.consumed_tick) for a in art.actions], art.metadata


def action_digest(actions: Iterable[Action], consumed: Iterable[int]) -> str:
    """native_action_digest of the M7 tracker: sha256 over 'buttons,stick_x,stick_y,consumed_tick\\n' lines."""
    h = hashlib.sha256()
    for (b, x, y, _), t in zip(actions, consumed):
        h.update(f"{b},{x},{y},{t}\n".encode("ascii"))
    return h.hexdigest()


# -- stepping trace ---------------------------------------------------------------------------------


def _capture_requests(client: Any, sink: List[Dict[str, Any]]) -> None:
    """Record every raw reply the client receives (instance attribute shadows the method; no inherited change)."""
    original = client.request

    def request(op: str, **payload: Any) -> Dict[str, Any]:
        reply = original(op, **payload)
        sink.append(reply)
        return reply

    client.request = request


def run_stepping_trace(label: str, executable: Path, actions: Sequence[Action], work: Path, *,
                       extra_env: Mapping[str, str], index: int = 0, rank: int = 0,
                       stop_at_end: bool = True,
                       on_ready: Optional[Callable[[Any], None]] = None) -> Dict[str, Any]:
    """Launch a fresh process (private runtime dir, M2 lifecycle), capture raw replies for status, observe and one
    step per action. A clear is finished natively (exit code + result JSON); anything else is terminated."""
    from battleship_client import StepState
    from battleship_process import BattleShipEpisode, LaunchConfig
    from m7_runtime import PortCandidates, prepare_worker_runtime

    work = Path(work).resolve()
    runtime = work / "runtime"
    prepare_worker_runtime(runtime, executable)
    port, _busy = PortCandidates(rank).claim()
    (work / "episodes").mkdir(parents=True, exist_ok=True)
    cfg = LaunchConfig(executable=Path(executable), working_dir=runtime, run_root=work / "episodes", port=port,
                       startup_timeout=30.0, ready_timeout=90.0, request_timeout=15.0, exit_timeout=30.0,
                       extra_env=dict(extra_env))
    trace: Dict[str, Any] = {"label": label, "executable": str(executable), "extra_env": dict(extra_env),
                             "actions_available": len(actions)}
    replies: List[Dict[str, Any]] = []
    episode = BattleShipEpisode(cfg, index=index)
    with episode:
        t0 = time.perf_counter()
        fresh = episode.start()
        trace["startup_s"] = round(time.perf_counter() - t0, 3)
        trace["fresh"] = {"state": fresh.state_name, "step_count": fresh.step_count, "can_step": fresh.can_step}
        client = episode.client
        if on_ready is not None:
            on_ready(episode)
        _capture_requests(client, replies)
        trace["status"] = client.request("status")
        trace["initial"] = client.request("observe")
        steps: List[Dict[str, Any]] = []
        mismatch = None
        last = None
        t1 = time.perf_counter()
        for i, (b, x, y, expected) in enumerate(actions):
            result = client.step(b, x, y)
            reply = replies[-1]
            steps.append(reply)
            if expected is not None and result.consumed_tick != expected and mismatch is None:
                mismatch = {"index": i, "consumed_tick": result.consumed_tick, "expected": expected}
            last = result
            if stop_at_end and result.state == StepState.EPISODE_ENDED:
                break
        trace["stepping_s"] = round(time.perf_counter() - t1, 3)
        trace["steps"] = steps
        trace["submitted"] = len(steps)
        trace["unsent"] = len(actions) - len(steps)
        trace["consumed_tick_mismatch"] = mismatch
        trace["final_state"] = last.state_name if last is not None else None
        if last is not None and last.state == StepState.EPISODE_ENDED:
            done = episode.finish(last)
            trace["exit_code"] = done.exit_code
            trace["result"] = dict(done.result)
        else:
            trace["exit_code"] = None
            trace["result"] = None
    trace["cleanup"] = episode.cleanup_action
    trace["pid"] = episode.pid
    trace["action_digest"] = action_digest(actions[:len(trace["steps"])],
                                           [s["consumed_tick"] for s in trace["steps"]])
    return trace


# -- native replay ----------------------------------------------------------------------------------


def native_tas_replay(executable: Path, work: Path, *, diag: bool = False, max_frames: int = 1500) -> Dict[str, Any]:
    """The authoritative 468-row replay: SSB64_BTT_INPUT, no stepping, no exit-on-end, SSB64_MAX_FRAMES so the input
    is exhausted and the checksum line is logged. Private cwd (archives from the executable directory). Must be the
    only BattleShip process: the port log is one shared file truncated per process."""
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
    env.update({"SSB64_RL_BTT": "1", "SSB64_BTT_INPUT": str(TAS_PATH), "SSB64_MAX_FRAMES": str(max_frames),
                "SSB64_SAVE_PATH": str(out / "save.bin"), "SSB64_RL_RESULT_PATH": str(out / "result.json")})
    if diag:
        env[TARGET_DIAG_ENV] = "1"
    t0 = time.perf_counter()
    r = subprocess.run([str(executable)], cwd=str(runtime), env=env, timeout=300, check=False,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wall = round(time.perf_counter() - t0, 2)
    text = PORT_LOG.read_text(encoding="utf-8", errors="replace") if PORT_LOG.is_file() else ""
    keep = ("BTT Replay", "input exhausted", "SSB64 RL:")
    lines = [ln.strip() for ln in text.splitlines() if any(k in ln for k in keep)]
    result_path = out / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else None
    return {"executable": str(executable), "diag": diag, "exit_code": r.returncode, "wall_s": wall,
            "complete_line": any("COMPLETE input_tick=447 time_passed=446" in ln for ln in lines),
            "checksum_line": any("frames=468" in ln and "actual_checksum=0x93E9EFB4" in ln for ln in lines),
            "replay_lines": [ln for ln in lines if "BTT Replay" in ln or "input exhausted" in ln],
            "rl_lines": [ln for ln in lines if "SSB64 RL:" in ln],
            "result": result}


# -- comparison -------------------------------------------------------------------------------------


def _strip(reply: Optional[Mapping[str, Any]], ignore: Sequence[str]) -> Optional[Dict[str, Any]]:
    if reply is None:
        return None
    return {k: v for k, v in reply.items() if k not in ignore}


def _typed_equal(a: Any, b: Any) -> bool:
    """Equality that also requires identical JSON types (1 != 1.0 != True)."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_typed_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_typed_equal(x, y) for x, y in zip(a, b))
    return a == b


def compare_stepping(ref: Mapping[str, Any], cand: Mapping[str, Any], *,
                     ignore: Sequence[str] = (DIAG_KEY,),
                     ignore_result: Sequence[str] = (DIAG_RESULT_KEY,)) -> Dict[str, Any]:
    """Every reply except the ignored top-level keys, and the result JSON except the ignored keys, must be identical
    in value and JSON type. Pass ignore=() and ignore_result=() for a strict comparison."""
    problems: List[str] = []
    rs, cs = _strip(ref.get("status"), ignore + STATUS_MODE_KEYS), _strip(cand.get("status"), ignore + STATUS_MODE_KEYS)
    if not _typed_equal(rs, cs):
        problems.append(f"status differs: {rs} vs {cs}")
    for k in STATUS_MODE_KEYS[:2]:
        if (ref.get("status") or {}).get(k) != (cand.get("status") or {}).get(k):
            problems.append(f"status.{k} differs")
    if not _typed_equal(_strip(ref.get("initial"), ignore), _strip(cand.get("initial"), ignore)):
        problems.append("initial observe differs")
    rsteps, csteps = ref.get("steps") or [], cand.get("steps") or []
    if len(rsteps) != len(csteps):
        problems.append(f"step count {len(rsteps)} vs {len(csteps)}")
    first = None
    for i, (a, b) in enumerate(zip(rsteps, csteps)):
        if not _typed_equal(_strip(a, ignore), _strip(b, ignore)):
            first = i
            sa, sb = _strip(a, ignore), _strip(b, ignore)
            keys = sorted(set(sa) | set(sb))
            detail = {k: (sa.get(k), sb.get(k)) for k in keys if not _typed_equal(sa.get(k), sb.get(k))}
            problems.append(f"step {i} differs: {json.dumps(detail)[:600]}")
            break
    for k in ("submitted", "unsent", "final_state", "exit_code", "action_digest", "consumed_tick_mismatch"):
        if ref.get(k) != cand.get(k):
            problems.append(f"{k}: {ref.get(k)!r} vs {cand.get(k)!r}")
    ra, ca = _strip(ref.get("result"), ignore_result), _strip(cand.get("result"), ignore_result)
    if not _typed_equal(ra, ca):
        problems.append(f"result JSON differs: {ra} vs {ca}")
    return {"label": ref.get("label"), "identical": not problems, "problems": problems, "first_divergent_step": first,
            "steps_compared": min(len(rsteps), len(csteps))}


def compare_native(ref: Mapping[str, Any], cand: Mapping[str, Any], *,
                   ignore_result_keys: Sequence[str] = (DIAG_RESULT_KEY,)) -> Dict[str, Any]:
    problems = []
    for k in ("exit_code", "complete_line", "checksum_line", "replay_lines"):
        if ref.get(k) != cand.get(k):
            problems.append(f"{k}: {ref.get(k)!r} vs {cand.get(k)!r}")
    ra = {k: v for k, v in (ref.get("result") or {}).items() if k not in ignore_result_keys}
    ca = {k: v for k, v in (cand.get("result") or {}).items() if k not in ignore_result_keys}
    if not _typed_equal(ra, ca):
        problems.append(f"result differs: {ra} vs {ca}")
    return {"identical": not problems, "problems": problems}


# -- capture sets -----------------------------------------------------------------------------------


def write_trace(path: Path, trace: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fp:
        json.dump(trace, fp, separators=(",", ":"))


def read_trace(path: Path) -> Dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as fp:
        return json.load(fp)


def capture_set(executable: Path, out: Path, *, diag: bool, modes: Sequence[str], fixtures: bool,
                native: bool, repeat_tag: str = "") -> Dict[str, Any]:
    """Capture the standard comparison set into `out`: the TAS through stepping in each host mode, the pinned
    fixture artifacts in the historical mode, and the native 468-row replay."""
    from m7_runtime import file_fingerprint, list_processes_named

    out = Path(out).resolve()
    if out.exists():
        raise SystemExit(f"output directory exists: {out}")
    out.mkdir(parents=True)
    user_cfg = REPO_ROOT / "build-us" / "Release" / "BattleShip.cfg.json"
    summary: Dict[str, Any] = {"schema": "battleship_m7f_trace_set_v1", "executable": str(executable),
                               "executable_sha256": sha256_file(Path(executable)), "diag": diag,
                               "modes": list(modes), "fixtures": fixtures, "native": native,
                               "user_config_before": file_fingerprint(user_cfg), "traces": {}}
    diag_env = {TARGET_DIAG_ENV: "1"} if diag else {}
    index = 0
    tas = tas_actions()
    for mode in modes:
        label = f"tas_{mode}{repeat_tag}"
        log(f"{label}: stepping {len(tas)} TAS rows")
        tr = run_stepping_trace(label, executable, tas, out / "work" / label, extra_env={**MODES[mode], **diag_env},
                                index=index)
        index += 1
        write_trace(out / f"{label}.json.gz", tr)
        summary["traces"][label] = {k: tr.get(k) for k in ("submitted", "unsent", "final_state", "exit_code",
                                                          "action_digest", "consumed_tick_mismatch", "startup_s",
                                                          "stepping_s")}
    if fixtures:
        for name, rel in FIXTURE_ARTIFACTS:
            acts, md = artifact_actions(REPO_ROOT / rel)
            label = f"fx_{name}{repeat_tag}"
            log(f"{label}: stepping {len(acts)} recorded actions")
            tr = run_stepping_trace(label, executable, acts, out / "work" / label,
                                    extra_env={**MODES[HISTORICAL_MODE], **diag_env}, index=index)
            index += 1
            tr["artifact"] = rel
            tr["recorded_digest"] = (md.get("labels") or {}).get("native_action_digest")
            write_trace(out / f"{label}.json.gz", tr)
            summary["traces"][label] = {k: tr.get(k) for k in ("submitted", "unsent", "final_state", "exit_code",
                                                              "action_digest", "consumed_tick_mismatch",
                                                              "recorded_digest")}
            summary["traces"][label]["digest_matches_record"] = tr["action_digest"] == tr["recorded_digest"]
    if native:
        log("native 468-row replay")
        nat = native_tas_replay(executable, out / "work" / f"native{repeat_tag}", diag=diag)
        (out / f"native{repeat_tag}.json").write_text(json.dumps(nat, indent=1) + "\n", encoding="utf-8")
        summary["traces"][f"native{repeat_tag}"] = {k: nat.get(k) for k in ("exit_code", "complete_line",
                                                                            "checksum_line", "wall_s")}
    summary["user_config_after"] = file_fingerprint(user_cfg)
    summary["leftover_battleship"] = list_processes_named()
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    return summary


def compare_sets(ref_dir: Path, cand_dir: Path) -> Dict[str, Any]:
    ref_dir, cand_dir = Path(ref_dir), Path(cand_dir)
    report: Dict[str, Any] = {"reference": str(ref_dir), "candidate": str(cand_dir), "comparisons": {}}
    for p in sorted(ref_dir.glob("*.json.gz")):
        q = cand_dir / p.name
        if not q.is_file():
            report["comparisons"][p.name] = {"identical": False, "problems": ["missing in candidate"]}
            continue
        report["comparisons"][p.name] = compare_stepping(read_trace(p), read_trace(q))
    for p in sorted(ref_dir.glob("native*.json")):
        q = cand_dir / p.name
        if q.is_file():
            report["comparisons"][p.name] = compare_native(json.loads(p.read_text(encoding="utf-8")),
                                                           json.loads(q.read_text(encoding="utf-8")))
    report["all_identical"] = bool(report["comparisons"]) and all(c["identical"] for c in report["comparisons"].values())
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--diag", action="store_true", help=f"launch with {TARGET_DIAG_ENV}=1")
    c.add_argument("--modes", default=",".join(MODES))
    c.add_argument("--no-fixtures", action="store_true")
    c.add_argument("--no-native", action="store_true")
    c.add_argument("--repeat-tag", default="")
    k = sub.add_parser("compare")
    k.add_argument("reference", type=Path)
    k.add_argument("candidate", type=Path)
    k.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "capture":
        from m7_runtime import install_kill_on_close_job

        install_kill_on_close_job()
        modes = [m for m in args.modes.split(",") if m]
        unknown = [m for m in modes if m not in MODES]
        if unknown:
            ap.error(f"unknown modes {unknown}")
        s = capture_set(args.exe.resolve(), args.out, diag=args.diag, modes=modes, fixtures=not args.no_fixtures,
                        native=not args.no_native, repeat_tag=args.repeat_tag)
        print(json.dumps({k: v for k, v in s.items() if k != "traces"}, indent=1))
        print(json.dumps(s["traces"], indent=1))
        return 0
    rep = compare_sets(args.reference, args.candidate)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    for name, c in rep["comparisons"].items():
        print(f"{'IDENTICAL' if c['identical'] else 'DIFFERENT'}  {name}  {'; '.join(c['problems'])[:400]}")
    print("ALL IDENTICAL" if rep["all_identical"] else "DIFFERENCES FOUND")
    return 0 if rep["all_identical"] else 1


if __name__ == "__main__":
    sys.exit(main())
