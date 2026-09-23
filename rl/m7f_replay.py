"""M7f Phase F: diagnostic replay of the selected historical action sequences with target identity.

Every selected sequence (docs/rl_target_ceiling_m7f_manifest.json) is resubmitted from tick 0 to a fresh BattleShip
process running the post-M7f executable with SSB64_RL_TARGET_DIAG=1 plus the historical host flags (no-render, Raphnet
bypass), using its canonical native actions (actions.jsonl). The replay must reproduce the historical row exactly:
action count, every consumed tick, last consumed tick, the native action digest, terminal/truncation classification,
targets broken, target_break_ticks, and the final observation (every historical-schema field; host_frame reported).
Target identity is then read from the diagnostic and validated on every reply (m7f_targets.check_trace).

Parallelism: --workers shard processes (default 5). Each shard steps one game and pre-boots the next one while
stepping (one active + at most one standby per worker, so at most 2 x workers <= 10 BattleShip processes). The first
divergence anywhere writes a STOP file; every shard stops before its next sequence (the analysis must not proceed on
a divergent replay).

Outputs below --out (default runs/m7f/replay): run.json (provenance: executable sha256, contract, flags, manifest
sha256), records_<shard>.jsonl (one compact record per sequence), divergent/<digest>.json.gz (full raw trace of any
divergent or invalid replay). Nothing else is kept: runtime and episode directories are removed after each sequence.
Resumable: sequences already recorded are skipped.

Usage:
    python rl/m7f_replay.py run [--strata a,b] [--limit N] [--workers 5]
    python rl/m7f_replay.py status
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import m7f_targets as mt  # noqa: E402

REPO_ROOT = RL_DIR.parent
DEFAULT_MANIFEST = REPO_ROOT / "docs" / "rl_target_ceiling_m7f_manifest.json"
DEFAULT_OUT = REPO_ROOT / "runs" / "m7f" / "replay"
EXECUTABLE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
HOST_FLAGS = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1"}  # the historical M7d/M7e host modes
TARGETS_TOTAL = 10
HORIZON = 3600
MAX_PROCESSES = 10


def utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# -- one sequence -----------------------------------------------------------------------------------


class Booted:
    """A launched process parked at tick 0 (fresh WaitingForAction), or the error that prevented it."""

    def __init__(self, episode: Any = None, runtime: Optional[Path] = None, error: Optional[str] = None,
                 startup_s: float = 0.0):
        self.episode, self.runtime, self.error, self.startup_s = episode, runtime, error, startup_s


def boot(work: Path, rank: int, index: int) -> Booted:
    from battleship_process import BattleShipEpisode, LaunchConfig
    from m7_runtime import PortCandidates, prepare_worker_runtime

    runtime = work / f"rt_{index:05d}"
    t0 = time.perf_counter()
    try:
        prepare_worker_runtime(runtime, EXECUTABLE)
        port, _busy = PortCandidates(rank).claim()
        cfg = LaunchConfig(executable=EXECUTABLE, working_dir=runtime, run_root=work / "episodes", port=port,
                           startup_timeout=30.0, ready_timeout=90.0, request_timeout=15.0, exit_timeout=30.0,
                           extra_env={**HOST_FLAGS, mt.DIAG_ENV: "1"})
        (work / "episodes").mkdir(parents=True, exist_ok=True)
        ep = BattleShipEpisode(cfg, index=index)
        ep.start()
        return Booted(ep, runtime, None, time.perf_counter() - t0)
    except Exception as exc:  # recorded as a lifecycle failure of that sequence, never silently retried
        return Booted(None, runtime, f"{type(exc).__name__}: {exc}", time.perf_counter() - t0)


def dispose(b: Booted) -> None:
    from m7_runtime import remove_worker_runtime

    if b.episode is not None:
        try:
            b.episode.close()
        finally:
            ep_dir = b.episode.paths.directory if b.episode.paths else None
            if ep_dir is not None and Path(ep_dir).exists():
                shutil.rmtree(ep_dir, ignore_errors=True)
    if b.runtime is not None:
        try:
            remove_worker_runtime(b.runtime)
        except Exception:
            pass


def position_summary(steps: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Where Mario went, from the existing observation fields only (position_x/y of each post-update, fighter_valid).
    Regions use the same stage-geometry boundaries as the target labels (m7f_targets)."""
    xs, ys = [], []
    region_steps = {"left_of_wall": 0, "wall_column": 0, "central": 0, "right": 0}
    first_left = None
    left_max_y = None
    for s in steps:
        o = s["observation"]
        if o.get("fighter_valid") != 1:
            continue
        x, y = float(o["position_x"]), float(o["position_y"])
        xs.append(x)
        ys.append(y)
        if x < mt.WALL_LEFT_FACE_X:
            region_steps["left_of_wall"] += 1
            left_max_y = y if left_max_y is None else max(left_max_y, y)
            if first_left is None:
                first_left = s["consumed_tick"]
        elif x <= mt.WALL_RIGHT_FACE_X:
            region_steps["wall_column"] += 1
        elif x < mt.RIGHT_BLOCK_X:
            region_steps["central"] += 1
        else:
            region_steps["right"] += 1
    at_break = {}
    by_tick = {s["consumed_tick"]: s["observation"] for s in steps}
    for e in events:
        o = by_tick.get(e["consumed_tick"])
        if o is not None:
            at_break[str(e["target_id"])] = [float(o["position_x"]), float(o["position_y"])]
    return {"min_x": min(xs) if xs else None, "max_x": max(xs) if xs else None,
            "min_y": min(ys) if ys else None, "max_y": max(ys) if ys else None,
            "region_steps": region_steps, "first_tick_left_of_wall": first_left,
            "left_of_wall_max_y": left_max_y, "mario_at_break": at_break,
            "final": [xs[-1], ys[-1]] if xs else None}


def replay_sequence(seq: Mapping[str, Any], b: Booted, exe_sha: str) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Returns (record, raw_trace_if_problem)."""
    from battleship_client import Observation, StepState
    from btt_parallel import is_native_failure
    from m7d_run import _obs_equal
    from run_artifacts import read_artifact

    import m7f_trace as tr

    art = read_artifact(REPO_ROOT / seq["artifact_dir"])
    acts = art.actions
    rec: Dict[str, Any] = {"digest": seq["digest"], "artifact_dir": seq["artifact_dir"], "strata": seq["strata"],
                           "rows": seq["rows"], "expected": seq["expected"], "executable_sha256": exe_sha,
                           "contract": mt.CONTRACT_ID, "startup_s": round(b.startup_s, 3)}
    if b.error is not None:
        rec.update({"ok": False, "lifecycle_error": b.error, "checks": {"booted": False}})
        return rec, None
    client = b.episode.client
    replies: List[Dict[str, Any]] = []
    tr._capture_requests(client, replies)
    status = client.request("status")
    mt.require_diag_status(status)
    initial = client.request("observe")
    rec["pid"] = b.episode.pid
    rec["fresh"] = {"state": initial.get("state_name"), "step_count": initial.get("step_count"),
                    "input_tick": initial["observation"]["input_tick"]}
    steps: List[Dict[str, Any]] = []
    mismatch = None
    t0 = time.perf_counter()
    for a in acts:
        res = client.step(a.buttons, a.stick_x, a.stick_y)
        steps.append(replies[-1])
        if res.consumed_tick != a.consumed_tick:
            mismatch = {"sequence_index": a.sequence_index, "consumed_tick": res.consumed_tick,
                        "recorded": a.consumed_tick}
            break
        if res.state == StepState.EPISODE_ENDED:
            break
    rec["stepping_s"] = round(time.perf_counter() - t0, 3)
    chk = mt.check_trace(initial, steps)
    exp = seq["expected"]
    last = steps[-1] if steps else None
    final_obs = last["observation"] if last else initial["observation"]
    failures = [i for i, s in enumerate(steps)
                if is_native_failure(Observation.from_wire(s["observation"]), StepState(s["state"]))]
    first_failure = failures[0] if failures else None
    if exp["end_reason"] == "fall":
        terminal_ok = first_failure is not None and first_failure == len(steps) - 1
    elif exp["end_reason"] == "horizon":
        terminal_ok = first_failure is None and len(steps) == HORIZON and last["state_name"] == "WaitingForAction"
    else:  # clear: none exist historically; still checked if one appears
        terminal_ok = last is not None and last["state_name"] == "EpisodeEnded"
    digest = tr.action_digest([(a.buttons, a.stick_x, a.stick_y, None) for a in acts[:len(steps)]],
                              [s["consumed_tick"] for s in steps])
    drops, prev = [], initial["observation"]["targets_remaining"]
    for s in steps:
        cur = s["observation"]["targets_remaining"]
        drops.extend([s["consumed_tick"]] * max(0, prev - cur))
        prev = cur
    obs_eq = _obs_equal(Observation.from_wire(final_obs), art.metadata.get("final_observation"))
    init_eq = _obs_equal(Observation.from_wire(initial["observation"]), art.metadata.get("initial_observation"))
    checks = {
        "fresh_tick0": rec["fresh"]["state"] == "WaitingForAction" and rec["fresh"]["step_count"] == 0
                       and rec["fresh"]["input_tick"] == 0,
        "action_count": len(steps) == len(acts) == exp["length"],
        "consumed_ticks": mismatch is None,
        "last_consumed_tick": last is not None and last["consumed_tick"] == exp["last_consumed_tick"],
        "action_digest": digest == seq["digest"],
        "terminal_classification": terminal_ok,
        "targets_broken": TARGETS_TOTAL - final_obs["targets_remaining"] == exp["targets"],
        "break_ticks_counts": drops == exp["break_ticks"],
        "break_ticks_ids": mt.break_ticks(chk.events) == exp["break_ticks"],
        "initial_observation": init_eq["equal"],
        "final_observation": obs_eq["equal"],
        "diag_valid": chk.ok,
    }
    rec["checks"] = checks
    rec["ok"] = all(checks.values())
    rec["host_frame_equal_final"] = obs_eq.get("host_frame_equal")
    rec["mismatch"] = mismatch
    rec["first_failure_step"] = first_failure
    rec["final_state"] = last["state_name"] if last else None
    rec["final_observation"] = final_obs
    rec["mapping_sha256"] = hashlib.sha256(mt.static_signature(chk.initial).encode()).hexdigest() \
        if chk.initial else None
    rec["events"] = chk.events
    rec["mask_changes"] = chk.mask_changes
    rec["final_remaining_mask"] = chk.final.remaining_mask if chk.final else None
    rec["final_remaining_ids"] = chk.final.remaining_ids if chk.final else None
    rec["diag_problems"] = chk.problems
    rec["snapshots_checked"] = chk.snapshots_checked
    rec["positions"] = position_summary(steps, chk.events)
    if not rec["ok"]:
        return rec, {"status": status, "initial": initial, "steps": steps, "record": rec}
    return rec, None


# -- shard worker -------------------------------------------------------------------------------------


def shard_main(args: argparse.Namespace) -> int:
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    out = args.out.resolve()
    man = json.loads(args.manifest.read_text(encoding="utf-8"))
    seqs = select_sequences(man, args.strata, args.limit)
    mine = [s for i, s in enumerate(seqs) if i % args.workers == args.shard]
    rec_path = out / f"records_{args.shard:02d}.jsonl"
    done = recorded_digests(out)
    todo = [s for s in mine if s["digest"] not in done]
    exe_sha = json.loads((out / "run.json").read_text(encoding="utf-8"))["executable_sha256"]
    work = out / "work" / f"w{args.shard:02d}"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    stop = out / "STOP"
    rank = args.shard
    pending: Dict[str, Any] = {}

    def prefetch(index: int) -> None:
        pending["booted"] = boot(work, rank, index)

    idx = 0
    thread: Optional[threading.Thread] = None
    current = boot(work, rank, idx) if todo else None
    for n, seq in enumerate(todo):
        if stop.exists():
            break
        if n + 1 < len(todo):  # pre-boot the next process while this one steps (one standby per worker)
            idx += 1
            pending.clear()
            thread = threading.Thread(target=prefetch, args=(idx,), daemon=True)
            thread.start()
        try:
            rec, raw = replay_sequence(seq, current, exe_sha)
        except Exception as exc:
            rec, raw = {"digest": seq["digest"], "artifact_dir": seq["artifact_dir"], "ok": False,
                        "exception": f"{type(exc).__name__}: {exc}", "checks": {}}, None
        finally:
            dispose(current)
        rec["shard"] = args.shard
        rec["utc"] = utc()
        with open(rec_path, "a", encoding="utf-8", newline="\n") as fp:
            fp.write(json.dumps(rec, separators=(",", ":")) + "\n")
        if not rec.get("ok"):
            if raw is not None:
                (out / "divergent").mkdir(exist_ok=True)
                with gzip.open(out / "divergent" / f"{seq['digest']}.json.gz", "wt", encoding="utf-8") as fp:
                    json.dump(raw, fp)
            stop.write_text(json.dumps({"digest": seq["digest"], "shard": args.shard, "utc": utc(),
                                        "checks": rec.get("checks"), "error": rec.get("lifecycle_error")
                                        or rec.get("exception")}) + "\n", encoding="utf-8")
        if thread is not None:
            thread.join()
            current = pending.get("booted")
            thread = None
        else:
            current = None
    if current is not None:
        dispose(current)
    if thread is not None:
        thread.join()
        if pending.get("booted") is not None:
            dispose(pending["booted"])
    shutil.rmtree(work, ignore_errors=True)
    return 0


# -- orchestrator ----------------------------------------------------------------------------------------


def select_sequences(man: Mapping[str, Any], strata: Optional[Sequence[str]], limit: Optional[int]) -> List[Dict[str, Any]]:
    seqs = list(man["sequences"])
    if strata:
        seqs = [s for s in seqs if set(s["strata"]) & set(strata)]
    seqs.sort(key=lambda s: (-int(s["actions"]), s["digest"]))  # long first, balanced round-robin
    return seqs[:limit] if limit else seqs


def recorded_digests(out: Path) -> Dict[str, bool]:
    done = {}
    for p in sorted(Path(out).glob("records_*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done[r["digest"]] = bool(r.get("ok"))
    return done


def run_main(args: argparse.Namespace) -> int:
    from m7_runtime import file_fingerprint, install_kill_on_close_job, list_processes_named

    install_kill_on_close_job()
    if args.workers * 2 > MAX_PROCESSES:
        raise SystemExit(f"--workers {args.workers} would allow {args.workers * 2} BattleShip processes (max {MAX_PROCESSES})")
    others = list_processes_named()
    if others:
        raise SystemExit(f"refusing to start: BattleShip already running {others}")
    leaked_env = sorted(k for k in os.environ if k.upper().startswith("SSB64_"))
    if leaked_env:
        raise SystemExit(f"refusing to start: SSB64_* variables in the orchestrator environment {leaked_env}")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if (out / "STOP").exists():
        raise SystemExit(f"{out / 'STOP'} exists: a previous divergence must be diagnosed before continuing")
    man = json.loads(args.manifest.read_text(encoding="utf-8"))
    seqs = select_sequences(man, args.strata, args.limit)
    run_path = out / "run.json"
    exe_sha = sha256_file(EXECUTABLE)
    run = json.loads(run_path.read_text(encoding="utf-8")) if run_path.is_file() else {
        "schema": "battleship_m7f_replay_run_v1", "created_utc": utc(), "contract": mt.CONTRACT_ID,
        "executable": EXECUTABLE.relative_to(REPO_ROOT).as_posix(), "executable_sha256": exe_sha,
        "flags": {**HOST_FLAGS, mt.DIAG_ENV: "1"}, "manifest": args.manifest.resolve().relative_to(REPO_ROOT).as_posix(),
        "manifest_sha256": sha256_file(args.manifest), "sessions": []}
    if run["executable_sha256"] != exe_sha:
        raise SystemExit(f"executable changed since this replay root was created ({run['executable_sha256'][:12]} -> "
                         f"{exe_sha[:12]}); use a new --out")
    user_cfg = REPO_ROOT / "build-us" / "Release" / "BattleShip.cfg.json"
    session = {"started_utc": utc(), "strata": args.strata, "limit": args.limit, "workers": args.workers,
               "selected": len(seqs), "already_recorded": len(recorded_digests(out)),
               "user_config_before": file_fingerprint(user_cfg)}
    run_path.write_text(json.dumps(run, indent=1) + "\n", encoding="utf-8", newline="\n")
    t0 = time.perf_counter()
    procs = []
    for k in range(args.workers):
        cmd = [sys.executable, "-B", str(Path(__file__).resolve()), "shard", "--shard", str(k), "--workers",
               str(args.workers), "--out", str(out), "--manifest", str(args.manifest.resolve())]
        if args.strata:
            cmd += ["--strata", ",".join(args.strata)]
        if args.limit:
            cmd += ["--limit", str(args.limit)]
        log = open(out / f"shard_{k:02d}.log", "a", encoding="utf-8")
        procs.append((subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(REPO_ROOT)), log))
    peak = 0
    while any(p.poll() is None for p, _ in procs):
        time.sleep(5)
        live = list_processes_named() or []
        peak = max(peak, len(live))
        if len(live) > MAX_PROCESSES:
            (out / "STOP").write_text(json.dumps({"reason": f"{len(live)} BattleShip processes > {MAX_PROCESSES}",
                                                  "utc": utc()}) + "\n", encoding="utf-8")
        done = recorded_digests(out)
        print(f"[m7f_replay] {utc()} recorded {len(done)} ok {sum(done.values())} live {len(live)} "
              f"elapsed {time.perf_counter() - t0:.0f}s", flush=True)
    for p, log in procs:
        log.close()
    done = recorded_digests(out)
    session.update({"finished_utc": utc(), "wall_s": round(time.perf_counter() - t0, 1),
                    "shard_exit_codes": [p.returncode for p, _ in procs], "peak_battleship_processes": peak,
                    "recorded_total": len(done), "ok_total": sum(done.values()), "stopped": (out / "STOP").exists(),
                    "user_config_after": file_fingerprint(user_cfg), "leftover_battleship": list_processes_named()})
    run["sessions"].append(session)
    run_path.write_text(json.dumps(run, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(session, indent=1))
    return 0 if not session["stopped"] and session["ok_total"] == session["recorded_total"] else 1


def probe_main(args: argparse.Namespace) -> int:
    """Re-replay the recorded sequences whose position summary reached `--min-max-y` (or listed `--digests`) and keep
    their per-step trajectory (consumed_tick, x, y, ground_air_state, fighter_status_id, remaining_mask), one process
    at a time. The replay must again reproduce the historical row exactly; the trajectory is read from the existing
    observation fields only."""
    from m7_runtime import install_kill_on_close_job, list_processes_named

    install_kill_on_close_job()
    if list_processes_named():
        raise SystemExit("refusing to start: BattleShip already running")
    out = args.out.resolve()
    recs: Dict[str, Dict[str, Any]] = {}
    for p in sorted(out.glob("records_*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                recs[r["digest"]] = r
    if args.digests:
        chosen = [recs[d] for d in args.digests]
    else:
        chosen = sorted((r for r in recs.values() if (r.get("positions") or {}).get("max_y") is not None
                         and r["positions"]["max_y"] >= args.min_max_y), key=lambda r: -r["positions"]["max_y"])
    man = {s["digest"]: s for s in json.loads(args.manifest.read_text(encoding="utf-8"))["sequences"]}
    probe_dir = out / "probe"
    probe_dir.mkdir(exist_ok=True)
    work = probe_dir / "work"
    exe_sha = json.loads((out / "run.json").read_text(encoding="utf-8"))["executable_sha256"]
    summary = []
    for n, r in enumerate(chosen):
        b = boot(work, 0, n)
        traj: List[List[Any]] = []
        try:
            seq = man[r["digest"]]
            client = b.episode.client
            orig_step = client.step

            def step_and_record(buttons: int, stick_x: int, stick_y: int, _orig=orig_step):
                res = _orig(buttons, stick_x, stick_y)
                o = res.observation
                traj.append([res.consumed_tick, round(float(o.position_x), 2), round(float(o.position_y), 2),
                             int(o.ground_air_state), int(o.fighter_status_id), int(o.targets_remaining)])
                return res

            client.step = step_and_record
            rec, _raw = replay_sequence(seq, b, exe_sha)
        finally:
            dispose(b)
        on_ledge = [t for t in traj if t[2] >= 2990.0 and -2100.0 <= t[1] <= -1200.0 and t[3] == 0]
        entry = {"digest": r["digest"], "ok": rec["ok"], "max_y": r["positions"]["max_y"],
                 "steps_y_ge_2990": sum(1 for t in traj if t[2] >= 2990.0),
                 "grounded_on_wall_top_ledge": len(on_ledge), "min_x": min(t[1] for t in traj),
                 "x_at_max_y": max(traj, key=lambda t: t[2])[1], "rows": seq["rows"][:3]}
        summary.append(entry)
        with gzip.open(probe_dir / f"{r['digest']}.json.gz", "wt", encoding="utf-8") as fp:
            json.dump({"record_ok": rec["ok"], "trajectory": traj}, fp)
        print(json.dumps(entry), flush=True)
    shutil.rmtree(work, ignore_errors=True)
    (probe_dir / "summary.json").write_text(json.dumps({"min_max_y": args.min_max_y, "probed": summary}, indent=1)
                                            + "\n", encoding="utf-8", newline="\n")
    return 0 if all(e["ok"] for e in summary) else 1


COMPARE_KEYS = ("ok", "checks", "events", "mask_changes", "final_remaining_mask", "final_remaining_ids",
                "final_observation", "final_state", "first_failure_step", "mapping_sha256", "positions",
                "host_frame_equal_final")


def _load_records(root: Path) -> Dict[str, Dict[str, Any]]:
    recs: Dict[str, Dict[str, Any]] = {}
    for p in sorted(Path(root).glob("records_*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                recs[r["digest"]] = r
    return recs


def compare_main(args: argparse.Namespace) -> int:
    """Two replay roots (e.g. two diagnostic builds) must agree on every outcome field for every common sequence."""
    a, b = _load_records(args.out), _load_records(args.other)
    common = sorted(set(a) & set(b))
    diffs = []
    for d in common:
        bad = [k for k in COMPARE_KEYS if a[d].get(k) != b[d].get(k)]
        if bad:
            diffs.append({"digest": d, "fields": bad})
    rep = {"reference": str(args.out), "candidate": str(args.other),
           "reference_executable": sorted({r.get("executable_sha256") for r in a.values()}),
           "candidate_executable": sorted({r.get("executable_sha256") for r in b.values()}),
           "common_sequences": len(common), "differing": len(diffs), "first_differences": diffs[:20],
           "fields_compared": list(COMPARE_KEYS)}
    print(json.dumps(rep, indent=1))
    if args.json:
        args.json.write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0 if common and not diffs else 1


def status_main(args: argparse.Namespace) -> int:
    done = recorded_digests(args.out.resolve())
    print(json.dumps({"recorded": len(done), "ok": sum(done.values()), "stop": (args.out / "STOP").exists()}))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "shard", "status", "probe", "compare"):
        p = sub.add_parser(name)
        p.add_argument("--out", type=Path, default=DEFAULT_OUT)
        p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
        p.add_argument("--strata", type=lambda s: [x for x in s.split(",") if x], default=None)
        p.add_argument("--limit", type=int, default=None)
        p.add_argument("--workers", type=int, default=5)
        if name == "shard":
            p.add_argument("--shard", type=int, required=True)
        if name == "probe":
            p.add_argument("--min-max-y", type=float, default=2990.0)
            p.add_argument("--digests", type=lambda s: [x for x in s.split(",") if x], default=None)
        if name == "compare":
            p.add_argument("--other", type=Path, required=True)
            p.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)
    if args.cmd == "compare":
        return compare_main(args)
    if args.cmd == "run":
        return run_main(args)
    if args.cmd == "shard":
        return shard_main(args)
    if args.cmd == "probe":
        return probe_main(args)
    return status_main(args)


if __name__ == "__main__":
    sys.exit(main())
