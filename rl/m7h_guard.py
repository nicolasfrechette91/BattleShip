"""M7h orchestrator side: the registered resource gates and the in-run memory policy (user approval 2026-09-24).

  launch gate      available system commit >= 10 GiB AND available physical >= 4 GiB (separately), plus the Phase K
                   checks (free disk, idle CPU, no BattleShip process, no listener in the port blocks, no SSB64_*)
  in-run policy    a 2-s probe of GlobalMemoryStatusEx: warn below 4 GiB available commit; below 3 GiB write
                   coordination/STOP_REQUEST.json (the trainer stops after the current vector step); if the trainer
                   has not exited 30 s later, CTRL_BREAK (its KeyboardInterrupt path); below 1 GiB, or 240 s after
                   CTRL_BREAK, kill it (its kill-on-close job object removes workers and games)
  after a stop     a provenance scan of what exists (complete checkpoint sets, .incomplete directories, the
                   interrupted set's component provenance, rows, artifacts, leftovers) written as stop_record.json,
                   then the run directory is moved to <partial_root>/<name>__<utc> - never deleted

The m7d_run Monitor (15-s heavy sampling, hard alerts) runs alongside, unchanged. DrillOverride exists only for the E7
drill: it simulates a level once the run has logged N rollouts; every simulated sample is marked as such.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import m7d_run as dr  # noqa: E402
from m7_runtime import BATTLESHIP_IMAGE, list_processes_named, wait_until_no_process  # noqa: E402

REPO_ROOT = RL_DIR.parent
LAUNCH_COMMIT_GIB = 10.0
LAUNCH_PHYSICAL_GIB = 4.0
LAUNCH_DISK_GIB = 10.0
LAUNCH_MAX_CPU_PCT = 40.0
STOP_REQUEST_FILE = "STOP_REQUEST.json"          # = m7_trainer.STOP_REQUEST_FILE (kept import-free of torch)
IGNORE_STOP_ENV = "M7_TEST_IGNORE_STOP_REQUEST"  # = m7_trainer.IGNORE_STOP_ENV
LEVELS = ("ok", "warn", "stop", "emergency")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def log(msg: str) -> None:
    print(f"[m7h_guard] {msg}", flush=True)


@dataclass(frozen=True)
class MemoryPolicy:
    warn_gib: float = 4.0
    stop_gib: float = 3.0
    emergency_gib: float = 1.0
    probe_interval_s: float = 2.0
    escalate_after_s: float = 30.0
    kill_grace_s: float = 240.0


REGISTERED_POLICY = MemoryPolicy()


@dataclass(frozen=True)
class DrillOverride:
    """E7 only: from the moment the run has logged `after_rollouts` rollouts, the probe reports `level`."""
    level: str
    after_rollouts: int
    ignore_stop_request: bool = False
    escalate_after_s: Optional[float] = None


def level_of(avail_commit_gib: Optional[float], policy: MemoryPolicy) -> str:
    if avail_commit_gib is None:
        return "stop"                                  # an unreadable probe is never assumed safe
    if avail_commit_gib < policy.emergency_gib:
        return "emergency"
    if avail_commit_gib < policy.stop_gib:
        return "stop"
    if avail_commit_gib < policy.warn_gib:
        return "warn"
    return "ok"


def worst(a: str, b: str) -> str:
    return a if LEVELS.index(a) >= LEVELS.index(b) else b


# -- launch gate --------------------------------------------------------------------------------------------------


def launch_gate() -> Dict[str, Any]:
    """Measure the machine (launches nothing) and evaluate the registered launch gate on that reading."""
    import m7g_k_run as kr

    return evaluate_launch(kr.measure_resources())


def evaluate_launch(m: Mapping[str, Any]) -> Dict[str, Any]:
    """The registered launch gate on one reading. Both memory gates are required and evaluated separately: available
    commit >= 10 GiB AND available physical >= 4 GiB (inclusive; a missing reading fails). Physical memory is gated
    only here, at launch; the in-run policy (level_of) watches available commit only."""
    p: List[str] = []
    commit_ok = m.get("avail_commit_gib") is not None and float(m["avail_commit_gib"]) >= LAUNCH_COMMIT_GIB
    physical_ok = m.get("avail_phys_gib") is not None and float(m["avail_phys_gib"]) >= LAUNCH_PHYSICAL_GIB
    if not commit_ok:
        p.append(f"available commit {m.get('avail_commit_gib')} GiB < {LAUNCH_COMMIT_GIB} GiB")
    if not physical_ok:
        p.append(f"available physical {m.get('avail_phys_gib')} GiB < {LAUNCH_PHYSICAL_GIB} GiB")
    if m.get("disk_free_gib") is None or float(m["disk_free_gib"]) < LAUNCH_DISK_GIB:
        p.append(f"free disk {m.get('disk_free_gib')} GiB < {LAUNCH_DISK_GIB} GiB")
    if m.get("cpu_mean_pct") is None or float(m["cpu_mean_pct"]) > LAUNCH_MAX_CPU_PCT:
        p.append(f"system CPU {m.get('cpu_mean_pct')} % > {LAUNCH_MAX_CPU_PCT} %")
    if m.get("battleship_pids"):
        p.append(f"BattleShip already running: {m['battleship_pids']}")
    if m.get("listeners"):
        p.append(f"ports occupied in the M7 blocks: {m['listeners']}")
    if m.get("ssb64_environment_variables"):
        p.append(f"SSB64_* variables set: {m['ssb64_environment_variables']}")
    return {"measurement": dict(m), "thresholds": {"commit_gib": LAUNCH_COMMIT_GIB, "physical_gib": LAUNCH_PHYSICAL_GIB,
                                                   "disk_gib": LAUNCH_DISK_GIB, "max_cpu_pct": LAUNCH_MAX_CPU_PCT},
            "commit_ok": commit_ok, "physical_ok": physical_ok, "problems": p, "ok": not p}


# -- the in-run probe ---------------------------------------------------------------------------------------------


def rollouts_logged(run_dir: Path) -> int:
    rows, _ = dr.jsonl_rows(Path(run_dir) / "metrics" / "rollouts.jsonl")
    return len(rows)


class MemoryProbe(threading.Thread):
    def __init__(self, policy: MemoryPolicy, run_dir: Path, out: Path, drill: Optional[DrillOverride] = None):
        super().__init__(daemon=True, name="m7h-memory-probe")
        self.policy, self.run_dir, self.out, self.drill = policy, Path(run_dir), Path(out), drill
        self._stop_event = threading.Event()
        self.samples = 0
        self.min_avail_commit: Optional[float] = None
        self.min_avail_phys: Optional[float] = None
        self.phys_below_launch = 0           # reported only: the in-run policy never reads physical memory
        self.max_commit_used: Optional[float] = None
        self.crossings: List[Dict[str, Any]] = []
        self.current: Dict[str, Any] = {"level": "ok", "simulated": False, "sample": None}
        self.out.parent.mkdir(parents=True, exist_ok=True)

    def run(self) -> None:
        last_level = "ok"
        while not self._stop_event.is_set():
            mem = dr.memory_status()
            avail = mem.get("avail_commit_gib")
            level, simulated = level_of(avail, self.policy), False
            if self.drill is not None and rollouts_logged(self.run_dir) >= self.drill.after_rollouts:
                level, simulated = worst(level, self.drill.level), True
            self.samples += 1
            if avail is not None:
                self.min_avail_commit = avail if self.min_avail_commit is None else min(self.min_avail_commit, avail)
            ph = mem.get("avail_phys_gib")
            if ph is not None:
                self.min_avail_phys = ph if self.min_avail_phys is None else min(self.min_avail_phys, ph)
                self.phys_below_launch += int(ph < LAUNCH_PHYSICAL_GIB)
            used = mem.get("commit_used_gib")
            if used is not None:
                self.max_commit_used = used if self.max_commit_used is None else max(self.max_commit_used, used)
            rec = {"t": utc(), "level": level, "simulated": simulated, "memory": mem}
            self.current = {"level": level, "simulated": simulated, "sample": rec}
            if level != last_level:
                self.crossings.append(rec)
                last_level = level
                if level != "ok":
                    log(f"memory level {level}{' (SIMULATED, E7 drill)' if simulated else ''}: "
                        f"available commit {avail} GiB")
            with open(self.out, "a", encoding="utf-8", newline="\n") as fp:
                fp.write(json.dumps(rec, separators=(",", ":")) + "\n")
            self._stop_event.wait(self.policy.probe_interval_s)

    def stop(self) -> Dict[str, Any]:
        self._stop_event.set()
        self.join(timeout=10)
        return {"samples": self.samples, "interval_s": self.policy.probe_interval_s,
                "min_avail_commit_gib": self.min_avail_commit, "min_avail_phys_gib": self.min_avail_phys,
                "samples_physical_below_launch_gate": self.phys_below_launch,
                "max_commit_used_gib": self.max_commit_used, "crossings": self.crossings,
                "policy": asdict(self.policy), "drill": asdict(self.drill) if self.drill else None}


def write_stop_request(run_dir: Path, record: Dict[str, Any]) -> Path:
    path = Path(run_dir) / "coordination" / STOP_REQUEST_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return path


# -- the guarded trainer -------------------------------------------------------------------------------------------


def train_guarded(*, config: Path, run_dir: Path, log_path: Path, monitor_path: Path, probe_path: Path,
                  contract: Any, horizon: int, partial_root: Path, run_id: Optional[str] = None,
                  output_root: Optional[Path] = None, policy: MemoryPolicy = REGISTERED_POLICY,
                  drill: Optional[DrillOverride] = None, extra_env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    cmd = [sys.executable, "-u", str(RL_DIR / "train_m7.py"), "--config", str(config)]
    if run_id:
        cmd += ["--run-id", run_id]
    if output_root:
        cmd += ["--output-root", str(output_root)]
    env = dict(os.environ)
    env.update(extra_env or {})
    if drill is not None and drill.ignore_stop_request:
        env[IGNORE_STOP_ENV] = "1"
    escalate_after = drill.escalate_after_s if drill is not None and drill.escalate_after_s else policy.escalate_after_s
    log_path.parent.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    mem_before = dr.memory_status()
    events: List[Dict[str, Any]] = []
    kind: Optional[str] = None
    requested = escalated = killed = None
    t0 = time.perf_counter()
    started = utc()
    with open(log_path, "a", encoding="utf-8", newline="\n") as lf:
        lf.write(f"# {started} {' '.join(cmd)}\n")
        lf.flush()
        proc = subprocess.Popen(cmd, cwd=str(REPO_ROOT), stdout=lf, stderr=subprocess.STDOUT, creationflags=flags,
                                env=env)
        log(f"trainer pid {proc.pid}: {Path(config).name} run {run_id or Path(run_dir).name}")
        monitor = dr.Monitor(out=monitor_path, root_pid=proc.pid, run_dir=run_dir, contract=contract,
                             horizon=horizon).start()
        probe = MemoryProbe(policy, run_dir, probe_path, drill)
        probe.start()
        try:
            while proc.poll() is None:
                time.sleep(0.25)
                now = time.monotonic()
                cur = probe.current
                if monitor.hard_alerts and kind is None:
                    kind = "monitor_hard_alert"
                    events.append({"t": utc(), "event": kind, "alerts": list(monitor.hard_alerts)})
                    events.append({"t": utc(), "event": "stop_trainer", "result": dr.stop_trainer(proc)})
                    break
                if cur["level"] == "emergency" and killed is None:
                    kind = "emergency_kill"
                    proc.kill()
                    killed = now
                    events.append({"t": utc(), "event": kind, "sample": cur["sample"]})
                    break
                if cur["level"] == "stop" and requested is None:
                    kind = "cooperative_stop"
                    requested = now
                    path = write_stop_request(run_dir, {"reason": "low_commit", "policy": asdict(policy),
                                                        "sample": cur["sample"], "simulated": cur["simulated"],
                                                        "requested_utc": utc()})
                    events.append({"t": utc(), "event": "stop_request_written", "path": str(path),
                                   "simulated": cur["simulated"]})
                if requested is not None and escalated is None and now - requested > escalate_after:
                    kind = "fallback_ctrl_break"
                    escalated = now
                    proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
                    events.append({"t": utc(), "event": "ctrl_break_sent", "after_s": round(escalate_after, 1)})
                if escalated is not None and killed is None and now - escalated > policy.kill_grace_s:
                    kind = "fallback_kill"
                    proc.kill()
                    killed = now
                    events.append({"t": utc(), "event": "kill_after_grace"})
                    break
        except KeyboardInterrupt:
            kind = "orchestrator_interrupt"
            events.append({"t": utc(), "event": kind, "stop_trainer": dr.stop_trainer(proc)})
        rc = proc.wait()
        mon = monitor.stop()
        probe_report = probe.stop()
    leftovers = wait_until_no_process(BATTLESHIP_IMAGE, timeout=30.0)
    result = {"command": cmd, "pid": proc.pid, "exit_code": rc, "started_utc": started, "finished_utc": utc(),
              "wall_s": round(time.perf_counter() - t0, 1), "stop_kind": kind, "events": events,
              "memory_before": mem_before, "probe": probe_report, "monitor": mon,
              "commit_drawn_gib": (None if probe_report["max_commit_used_gib"] is None
                                   or mem_before.get("commit_used_gib") is None
                                   else round(probe_report["max_commit_used_gib"] - mem_before["commit_used_gib"], 3)),
              "leftover_battleship_pids": leftovers, "log": str(log_path), "monitor_log": str(monitor_path),
              "probe_log": str(probe_path)}
    if kind is not None:
        result["provenance"] = scan_run(Path(run_dir))
        record = dict(result, record="m7h_stop_record_v1")
        (Path(run_dir) / "stop_record.json").write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")
        result["moved_to"] = move_to_partial(Path(run_dir), Path(partial_root))
    return result


# -- provenance of what a stop left behind ---------------------------------------------------------------------------


def scan_run(run_dir: Path) -> Dict[str, Any]:
    from m7_evaluation import CheckpointError, read_checkpoint_set

    out: Dict[str, Any] = {"run_dir": str(run_dir)}
    sets = []
    candidates = sorted((run_dir / "checkpoints").glob("ckpt_*")) if (run_dir / "checkpoints").is_dir() else []
    candidates += [run_dir / "final", run_dir / "interrupted"]
    for d in candidates:
        if not d.is_dir():
            continue
        try:
            meta = read_checkpoint_set(d)
            inter = meta.get("interruption") or {}
            sets.append({"label": d.name, "complete_and_hash_valid": True, "num_timesteps": meta.get("num_timesteps"),
                         "n_updates": meta.get("n_updates"), "extra_files": meta.get("extra_files"),
                         "interruption": inter or None})
        except CheckpointError as exc:
            sets.append({"label": d.name, "complete_and_hash_valid": False, "problem": str(exc)})
    out["checkpoint_sets"] = sets
    out["incomplete_dirs"] = [str(p) for base in (run_dir, run_dir / "checkpoints") if base.is_dir()
                              for p in base.glob(".*.incomplete")]
    summ = run_dir / "training_summary.json"
    if summ.is_file():
        s = json.loads(summ.read_text(encoding="utf-8"))
        out["training_summary"] = {"status": s.get("status"), "stop": s.get("stop"),
                                   "leak_free": (s.get("cleanup") or {}).get("leak_free")}
    else:
        out["training_summary"] = None
    ep = run_dir / "metrics" / "episodes.jsonl"
    rows, offset = dr.jsonl_rows(ep)
    out["episode_rows"] = {"complete": len(rows), "torn_tail_bytes": (ep.stat().st_size - offset) if ep.is_file() else 0}
    arts = {"total": 0, "aborted": 0, "aborted_with_m7h_start": 0, "failed": 0}
    wroot = run_dir / "workers"
    if wroot.is_dir():
        for w in sorted(wroot.iterdir()):
            adir = w / "artifacts"
            if not adir.is_dir():
                continue
            for a in adir.iterdir():
                meta_path = a / "metadata.json"
                if not meta_path.is_file():
                    continue
                arts["total"] += 1
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("status") == "aborted":
                    arts["aborted"] += 1
                    if (meta.get("labels") or {}).get("m7h_start"):
                        arts["aborted_with_m7h_start"] += 1
                elif meta.get("status") == "failed":
                    arts["failed"] += 1
    out["artifacts"] = arts
    req = run_dir / "coordination" / STOP_REQUEST_FILE
    out["stop_request"] = json.loads(req.read_text(encoding="utf-8")) if req.is_file() else None
    out["battleship_processes"] = list_processes_named(BATTLESHIP_IMAGE)
    return out


def move_to_partial(run_dir: Path, partial_root: Path) -> Optional[str]:
    partial_root.mkdir(parents=True, exist_ok=True)
    target = partial_root / f"{run_dir.name}__{stamp()}"
    for i in range(20):
        try:
            os.rename(run_dir, target)
            log(f"moved {run_dir} -> {target} (never deleted)")
            return str(target)
        except PermissionError:
            time.sleep(0.5)
    log(f"could not move {run_dir} to {partial_root}; left in place")
    return None
