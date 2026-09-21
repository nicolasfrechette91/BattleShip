"""M6 follow-up: regression of the process-local Raphnet adapter bypass.

SSB64_RAPHNET_DISABLE=1 makes libultraship's ControlDeck::PreInitRaphnet skip
native Raphnet N64 USB adapter support for the process (no hidapi open, no
per-read USB poll) without reading, registering or writing the
gControllers.Raphnet.Enabled console variable. The port keeps the variable
only while interactive stepping is effective (SSB64_RL_STEP=1 and no
SSB64_BTT_INPUT); otherwise rlConfigInit() removes it from the process
environment before the game boots and logs that it was ignored.

This script proves three things with fresh, sequential processes on the
executable under test:

1. Precedence and mode combinations (one process each):
     ordinary_launch_no_flag              no RL variables, frame cap
     ordinary_launch_with_flag            flag present, must be ignored
     rl_step_no_flag                      M2 stepping, full 7.43 s replay
     rl_step_raphnet_disabled             M2 stepping + flag (visible host)
     rl_step_no_render_raphnet_disabled   M2 stepping + no-render + flag
     native_replay_no_flag                SSB64_BTT_INPUT, frame cap (checksum run)
     native_replay_with_flag              as above + flag, must be ignored
     native_replay_all_flags              replay + step + no-render + flag + port
   Stepping processes must report the expected `no_render` /
   `raphnet_disabled` status booleans and reproduce the frozen contract
   (447 actions, last consumed_tick 446, completion_time_passed 446,
   completion_input_tick 447, step_count 447, targets 0, EpisodeEnded,
   exit 0, 21 rows unsent). Native replays must log COMPLETE
   input_tick=447 time_passed=446, the 468-row checksum 0x93E9EFB4 when the
   frame cap lets the input run out, and write the result JSON 10/446/447.

2. Adapter evidence: the libultraship log appended by each process. A
   bypassed process must append no adapter-open line; every other process
   must behave like the reference ordinary launch (adapter opened when one
   is attached to the machine, not opened when none is). The port log must
   carry the matching `raphnet_disabled=` value and the ignored / effective
   line.

3. Configuration persistence: the config file the processes use
   (<executable dir>/BattleShip.cfg.json, the portable app directory) is
   backed up before the first launch; after every process its bytes are
   hashed and its JSON compared (whole file, CVars, CVars.gControllers, the
   gControllers.Raphnet key). Any change fails the run, the changed file is
   kept beside the report, and the backup is restored.

Usage:
    python rl/m6_raphnet_bypass_regression.py
    python rl/m6_raphnet_bypass_regression.py --out m6_raphnet_bypass.json --run-dir <dir>

Exit codes: 0 PASS, 1 failure, 2 bad input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from battleship_client import BattleShipError, StepResult, StepState  # noqa: E402
from battleship_process import BattleShipEpisode, EpisodeFailure, LaunchConfig  # noqa: E402
from btti_replay import ReplayFormatError, ReplayRow, read_btti_rows  # noqa: E402
from m1e_replay_regression import (  # noqa: E402
    COMPLETION_CONSUMED_TICK,
    COMPLETION_INPUT_TICK,
    COMPLETION_STEPS,
    COMPLETION_TIME_PASSED,
    SOURCE_ROWS,
    RegressionFailure,
    check_completion,
    check_step,
)
from m2_restart_regression import EXPECTED_RESULT, describe_regression_failure  # noqa: E402
from m6_equivalence_regression import (  # noqa: E402
    NO_RENDER_ENV,
    RAPHNET_DISABLE_ENV,
    STATUS_FLAGS,
    count_battleship_processes,
    read_status_flags,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXECUTABLE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
DEFAULT_REPLAY = REPO_ROOT / "tas_input_2" / "mario_743.btti"
CONFIG_NAME = "BattleShip.cfg.json"
LUS_LOG_RELATIVE = Path("logs") / "BattleShip.log"

EXIT_PASS = 0
EXIT_FAILED = 1
EXIT_BAD_INPUT = 2

REPLAY_COMPLETE_LINE = f"SSB64 BTT Replay: COMPLETE input_tick={COMPLETION_INPUT_TICK} time_passed={COMPLETION_TIME_PASSED}"
REPLAY_CHECKSUM_LINE = f"SSB64 BTT Replay: input exhausted frames={SOURCE_ROWS} actual_checksum=0x93E9EFB4"
IGNORED_ORDINARY = f"{RAPHNET_DISABLE_ENV}=1 ignored: SSB64_RL_BTT is not set"
IGNORED_REPLAY = f"{RAPHNET_DISABLE_ENV}=1 ignored: SSB64_BTT_INPUT is set"
EFFECTIVE_LINE = f"{RAPHNET_DISABLE_ENV}=1 effective"
NO_RENDER_IGNORED = f"{NO_RENDER_ENV}=1 ignored"
# The libultraship Release log carries the adapter transport's warning-level
# diagnostics; an INFO line is not written at that level, so "opened" is the
# presence of the transport's Open() diagnostic.
ADAPTER_OPEN_MARKERS = ("[raphnet-diag] Open(", "hid_open_path OK")


def log(message: str) -> None:
    print(message, flush=True)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def default_port_log() -> Optional[Path]:
    """port_log() writes <SDL pref path>/ssb64.log, truncated per process (port/port.cpp)."""
    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        return Path(appdata) / "BattleShip" / "ssb64.log" if appdata else None
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "BattleShip" / "ssb64.log"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "BattleShip" / "ssb64.log"


# -- config snapshot ---------------------------------------------------------------------------------


@dataclass
class ConfigSnapshot:
    path: Path
    sha256: str
    size: int
    data: Any

    @classmethod
    def take(cls, path: Path) -> "ConfigSnapshot":
        raw = path.read_bytes()
        return cls(path=path, sha256=hashlib.sha256(raw).hexdigest(), size=len(raw), data=json.loads(raw.decode("utf-8")))

    def raphnet_key(self) -> Any:
        return self.data.get("CVars", {}).get("gControllers", {}).get("Raphnet", "<absent>")

    def compare(self, other: "ConfigSnapshot") -> Dict[str, Any]:
        cv_a, cv_b = self.data.get("CVars", {}), other.data.get("CVars", {})
        return {
            "sha256_before": self.sha256, "sha256_after": other.sha256, "size_before": self.size, "size_after": other.size,
            "bytes_identical": self.sha256 == other.sha256,
            "json_identical": self.data == other.data,
            "cvars_identical": cv_a == cv_b,
            "gcontrollers_identical": cv_a.get("gControllers") == cv_b.get("gControllers"),
            "raphnet_key_before": self.raphnet_key(), "raphnet_key_after": other.raphnet_key(),
            "raphnet_key_unchanged": self.raphnet_key() == other.raphnet_key(),
            "window_identical": self.data.get("Window") == other.data.get("Window"),
        }


# -- log capture --------------------------------------------------------------------------------------


class AppendedLog:
    """Text a process wrote to a log file: the bytes appended after mark() for an appending (rotating)
    sink, or the whole file for a sink that truncates the file per process (port_log)."""

    def __init__(self, path: Optional[Path], truncated_per_process: bool = False) -> None:
        self.path = path
        self.truncated_per_process = truncated_per_process
        self.offset = 0

    def mark(self) -> None:
        self.offset = self.path.stat().st_size if self.path is not None and self.path.exists() else 0

    def read(self) -> str:
        if self.path is None or not self.path.exists():
            return ""
        raw = self.path.read_bytes()
        if self.truncated_per_process or len(raw) < self.offset:  # whole file / rotated
            self.offset = 0
        return raw[self.offset:].decode("utf-8", "replace")


def adapter_opened(lus_text: str) -> bool:
    return any(marker in line for line in lus_text.splitlines() for marker in ADAPTER_OPEN_MARKERS)


# -- cases --------------------------------------------------------------------------------------------


@dataclass
class CaseResult:
    name: str
    env: Dict[str, str]
    kind: str  # "native" (hand-launched, waits for exit) or "step" (M2 episode)
    exit_code: Optional[int] = None
    wall_s: Optional[float] = None
    status_flags: Optional[Dict[str, bool]] = None
    port_log_lines: List[str] = field(default_factory=list)
    lus_adapter_opened: Optional[bool] = None
    lus_raphnet_line_count: int = 0
    replay: Dict[str, Any] = field(default_factory=dict)
    stepping: Dict[str, Any] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)
    ok: bool = False
    failure: Optional[str] = None

    def summary(self) -> Dict[str, Any]:
        return {k: v for k, v in vars(self).items()}


class Harness:
    def __init__(self, args: argparse.Namespace, rows: Sequence[ReplayRow], run_root: Path) -> None:
        self.exe = Path(args.exe).resolve()
        self.exe_dir = self.exe.parent
        self.rows = rows
        self.replay_path = Path(args.replay).resolve()
        self.run_root = run_root
        self.args = args
        self.config_path = self.exe_dir / CONFIG_NAME
        self.port_log = AppendedLog(Path(args.port_log) if args.port_log else default_port_log(), truncated_per_process=True)
        self.lus_log = AppendedLog(self.exe_dir / LUS_LOG_RELATIVE)
        self.before: Optional[ConfigSnapshot] = None
        self.backup: Optional[Path] = None
        self.reference_adapter_opened: Optional[bool] = None

    # -- config ---------------------------------------------------------------

    def snapshot_and_backup(self) -> None:
        if not self.config_path.is_file():
            raise RegressionFailure(f"config file not found: {self.config_path} (the processes would create one; refusing to test)")
        self.before = ConfigSnapshot.take(self.config_path)
        self.backup = self.run_root / f"{CONFIG_NAME}.backup"
        shutil.copy2(self.config_path, self.backup)
        if sha256_of(self.backup) != self.before.sha256:
            raise RegressionFailure("config backup does not match the original")
        log(f"config {self.config_path}: {self.before.size} bytes sha256 {self.before.sha256[:16]}..., "
            f"gControllers.Raphnet = {self.before.raphnet_key()!r}; backup at {self.backup}")

    def check_config(self, case: CaseResult) -> None:
        assert self.before is not None and self.backup is not None
        after = ConfigSnapshot.take(self.config_path)
        case.config = self.before.compare(after)
        if not case.config["bytes_identical"]:
            kept = self.run_root / f"{CONFIG_NAME}.after_{case.name}"
            shutil.copy2(self.config_path, kept)
            shutil.copy2(self.backup, self.config_path)
            case.config["changed_file_kept_at"] = str(kept)
            case.config["restored_from_backup"] = sha256_of(self.config_path) == self.before.sha256
            raise RegressionFailure(f"{case.name}: {CONFIG_NAME} changed on disk (json_identical={case.config['json_identical']}, "
                                    f"cvars_identical={case.config['cvars_identical']}, "
                                    f"raphnet_key {case.config['raphnet_key_before']!r} -> {case.config['raphnet_key_after']!r}); "
                                    f"changed file kept at {kept}, backup restored")

    # -- launching ------------------------------------------------------------

    def child_env(self, extra: Dict[str, str]) -> Dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("SSB64_")}
        env.update(extra)
        return env

    def collect_logs(self, case: CaseResult) -> None:
        port_text = self.port_log.read()
        case.port_log_lines = [line for line in port_text.splitlines()
                               if "SSB64 RL:" in line and "enabled episode" in line
                               or "SSB64 RL Raphnet" in line or "SSB64 RL NoRender" in line
                               or "SSB64 RL Step:" in line and "precedence" in line
                               or "SSB64 BTT Replay" in line]
        lus_text = self.lus_log.read()
        case.lus_adapter_opened = adapter_opened(lus_text)
        case.lus_raphnet_line_count = sum(1 for line in lus_text.splitlines() if "raphnet" in line.lower())

    def run_native(self, case: CaseResult, timeout_s: float) -> None:
        """Hand-launched process: waits for the process to exit on its own (frame cap or M1a exit)."""
        self.port_log.mark()
        self.lus_log.mark()
        stdout_path = self.run_root / f"{case.name}.stdout.log"
        t0 = time.perf_counter()
        with open(stdout_path, "wb") as out:
            proc = subprocess.Popen([str(self.exe)], cwd=str(self.exe_dir), env=self.child_env(case.env),
                                    stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
            try:
                case.exit_code = proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=30)
                raise RegressionFailure(f"{case.name}: process did not exit within {timeout_s:.0f} s; killed")
        case.wall_s = time.perf_counter() - t0
        time.sleep(0.5)  # let the rotating sink flush
        self.collect_logs(case)

    def run_step_episode(self, case: CaseResult, index: int, expect_flags: Dict[str, bool]) -> None:
        """M2 episode: the full replay through the raw M1d client, frozen contract asserted."""
        self.port_log.mark()
        self.lus_log.mark()
        config = LaunchConfig(executable=self.exe, run_root=self.run_root, startup_timeout=self.args.startup_timeout,
                              ready_timeout=self.args.ready_timeout, request_timeout=self.args.request_timeout,
                              exit_timeout=self.args.exit_timeout, extra_env=dict(case.env))
        episode = BattleShipEpisode(config, index=index)
        t0 = time.perf_counter()
        with episode:
            fresh = episode.start()
            if not (fresh.state == StepState.WAITING_FOR_ACTION and fresh.can_step and fresh.step_count == 0):
                raise RegressionFailure(f"{case.name}: episode is not fresh: {fresh.state_name}")
            case.status_flags = read_status_flags(episode)
            for name in STATUS_FLAGS:
                if case.status_flags[name] != expect_flags[name]:
                    raise RegressionFailure(f"{case.name}: status.{name}={case.status_flags[name]}, expected {expect_flags[name]}")
            client = episode.client
            assert client is not None
            previous = None
            terminal: Optional[StepResult] = None
            submitted = 0
            for row_index, row in enumerate(self.rows):
                try:
                    result = client.step(row.buttons, row.stick_x, row.stick_y)
                except BattleShipError as exc:
                    raise episode.classify_step_failure(exc) from exc
                submitted += 1
                check_step(row_index, result, previous)
                previous = result.observation
                if result.observation.targets_remaining == 0:
                    check_completion(row_index, result)
                    terminal = result
                    break
            if terminal is None:
                raise RegressionFailure(f"{case.name}: all {len(self.rows)} rows consumed without completion")
            done = episode.finish(terminal)
            case.exit_code = done.exit_code
            o = terminal.observation
            case.stepping = {
                "actions_submitted": submitted, "rows_unsent": len(self.rows) - submitted,
                "last_consumed_tick": terminal.consumed_tick, "completion_time_passed": o.time_passed,
                "completion_input_tick": o.input_tick, "final_step_count": terminal.step_count,
                "targets_remaining": o.targets_remaining, "final_state": terminal.state_name,
                "host_frame_final": o.host_frame, "result_json": dict(done.result),
            }
            checks = [
                (submitted == COMPLETION_STEPS, f"actions submitted {submitted}"),
                (terminal.consumed_tick == COMPLETION_CONSUMED_TICK, f"last consumed_tick {terminal.consumed_tick}"),
                (o.time_passed == COMPLETION_TIME_PASSED, f"completion_time_passed {o.time_passed}"),
                (o.input_tick == COMPLETION_INPUT_TICK, f"completion_input_tick {o.input_tick}"),
                (terminal.step_count == COMPLETION_STEPS, f"final step_count {terminal.step_count}"),
                (terminal.state == int(StepState.EPISODE_ENDED), f"final state {terminal.state_name}"),
                (done.exit_code == 0, f"exit code {done.exit_code}"),
                (len(self.rows) - submitted == SOURCE_ROWS - COMPLETION_STEPS, f"rows unsent {len(self.rows) - submitted}"),
                (all(done.result.get(k) == v for k, v in EXPECTED_RESULT.items()), f"result JSON {done.result}"),
            ]
            for ok, message in checks:
                if not ok:
                    raise RegressionFailure(f"{case.name}: frozen contract violated: {message}")
        case.wall_s = time.perf_counter() - t0
        time.sleep(0.5)
        self.collect_logs(case)

    # -- expectations ---------------------------------------------------------

    def expect_port_line(self, case: CaseResult, needle: str, present: bool = True) -> None:
        found = any(needle in line for line in case.port_log_lines)
        if found != present:
            raise RegressionFailure(f"{case.name}: port log line {needle!r} {'missing' if present else 'unexpectedly present'}; "
                                    f"lines: {case.port_log_lines}")

    def expect_adapter(self, case: CaseResult, bypassed: bool) -> None:
        if bypassed:
            if case.lus_adapter_opened:
                raise RegressionFailure(f"{case.name}: libultraship opened the adapter although the bypass was expected")
            return
        if self.reference_adapter_opened is None:
            self.reference_adapter_opened = case.lus_adapter_opened
            return
        if case.lus_adapter_opened != self.reference_adapter_opened:
            raise RegressionFailure(f"{case.name}: adapter opened={case.lus_adapter_opened}, but the reference ordinary "
                                    f"launch had {self.reference_adapter_opened}")

    def expect_native_replay(self, case: CaseResult, checksum_line: bool, result_path: Path) -> None:
        self.expect_port_line(case, REPLAY_COMPLETE_LINE)
        if checksum_line:
            self.expect_port_line(case, REPLAY_CHECKSUM_LINE)
        if not result_path.is_file():
            raise RegressionFailure(f"{case.name}: result JSON not written: {result_path}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        case.replay = {"result_json": result, "complete_line": True, "checksum_line": checksum_line or None}
        for key, expected in EXPECTED_RESULT.items():
            if result.get(key) != expected:
                raise RegressionFailure(f"{case.name}: result JSON {key} is {result.get(key)!r}, expected {expected!r}")
        if case.exit_code != 0:
            raise RegressionFailure(f"{case.name}: exit code {case.exit_code}")


def run_cases(h: Harness, report: Dict[str, Any]) -> None:
    replay_env = {"SSB64_RL_BTT": "1", "SSB64_BTT_INPUT": str(h.replay_path)}
    frame_cap = {"SSB64_MAX_FRAMES": str(h.args.ordinary_frames)}
    replay_cap = {"SSB64_MAX_FRAMES": str(h.args.replay_frames)}

    def run(case: CaseResult, body) -> None:
        log(f"[{case.name}] {case.kind}: env {case.env}")
        try:
            body(case)
            h.check_config(case)
            case.ok = True
        finally:
            report["cases"].append(case.summary())
            log(f"  {case.name}: {'PASS' if case.ok else 'FAIL'} exit={case.exit_code} wall={case.wall_s and round(case.wall_s, 2)} s "
                f"adapter_opened={case.lus_adapter_opened} status={case.status_flags} config_bytes_identical="
                f"{case.config.get('bytes_identical')} raphnet_key={case.config.get('raphnet_key_after')!r}")
            for line in case.port_log_lines:
                if "SSB64 RL Raphnet" in line or "enabled episode" in line or "COMPLETE" in line or "checksum" in line:
                    log(f"    port log: {line.strip()}")

    # 1. ordinary launch, no flag: the reference for "adapter as configured"
    def ordinary_no_flag(case: CaseResult) -> None:
        h.run_native(case, h.args.native_timeout)
        h.expect_port_line(case, "SSB64 RL Raphnet", present=False)
        h.expect_port_line(case, "enabled episode", present=False)
        h.expect_adapter(case, bypassed=False)
    run(CaseResult("ordinary_launch_no_flag", dict(frame_cap), "native"), ordinary_no_flag)

    # 2. ordinary launch, flag present: ignored, adapter as configured
    def ordinary_with_flag(case: CaseResult) -> None:
        h.run_native(case, h.args.native_timeout)
        h.expect_port_line(case, IGNORED_ORDINARY)
        h.expect_port_line(case, EFFECTIVE_LINE, present=False)
        h.expect_adapter(case, bypassed=False)
    run(CaseResult("ordinary_launch_with_flag", {**frame_cap, RAPHNET_DISABLE_ENV: "1"}, "native"), ordinary_with_flag)

    # 3-5. interactive stepping
    def stepping(expect_flags: Dict[str, bool], index: int):
        def body(case: CaseResult) -> None:
            h.run_step_episode(case, index, expect_flags)
            h.expect_port_line(case, f"raphnet_disabled={1 if expect_flags['raphnet_disabled'] else 0}")
            h.expect_port_line(case, EFFECTIVE_LINE, present=expect_flags["raphnet_disabled"])
            h.expect_port_line(case, "ignored", present=False)
            h.expect_adapter(case, bypassed=expect_flags["raphnet_disabled"])
        return body
    run(CaseResult("rl_step_no_flag", {}, "step"),
        stepping({"no_render": False, "raphnet_disabled": False}, 6300))
    run(CaseResult("rl_step_raphnet_disabled", {RAPHNET_DISABLE_ENV: "1"}, "step"),
        stepping({"no_render": False, "raphnet_disabled": True}, 6301))
    run(CaseResult("rl_step_no_render_raphnet_disabled", {NO_RENDER_ENV: "1", RAPHNET_DISABLE_ENV: "1"}, "step"),
        stepping({"no_render": True, "raphnet_disabled": True}, 6302))

    # 6. native replay, no flag: checksum run (frame cap lets the 468 rows run out)
    def native_replay(flag_env: Dict[str, str], expect_ignored: Optional[str], checksum: bool, timeout: float):
        def body(case: CaseResult) -> None:
            result_path = h.run_root / f"{case.name}.result.json"
            case.env["SSB64_RL_RESULT_PATH"] = str(result_path)
            h.run_native(case, timeout)
            h.expect_port_line(case, "step=0 transport_port=0 no_render=0 raphnet_disabled=0")
            if expect_ignored is None:
                h.expect_port_line(case, "SSB64 RL Raphnet", present=False)
            else:
                h.expect_port_line(case, expect_ignored)
            h.expect_port_line(case, EFFECTIVE_LINE, present=False)
            h.expect_native_replay(case, checksum_line=checksum, result_path=result_path)
            h.expect_adapter(case, bypassed=False)
        return body
    run(CaseResult("native_replay_no_flag", {**replay_env, **replay_cap}, "native"),
        native_replay({}, None, True, h.args.replay_timeout))
    run(CaseResult("native_replay_with_flag", {**replay_env, **replay_cap, RAPHNET_DISABLE_ENV: "1"}, "native"),
        native_replay({}, IGNORED_REPLAY, True, h.args.replay_timeout))

    # 8. every flag together: the replay keeps precedence over all of them
    all_flags = {**replay_env, "SSB64_RL_EXIT_ON_END": "1", "SSB64_RL_STEP": "1", NO_RENDER_ENV: "1",
                 RAPHNET_DISABLE_ENV: "1", "SSB64_RL_PORT": str(h.args.precedence_port)}

    def all_flags_body(case: CaseResult) -> None:
        native_replay({}, IGNORED_REPLAY, False, h.args.replay_timeout)(case)
        h.expect_port_line(case, NO_RENDER_IGNORED)
        h.expect_port_line(case, "the replay keeps precedence")
    run(CaseResult("native_replay_all_flags", all_flags, "native"), all_flags_body)


def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exe", default=str(DEFAULT_EXECUTABLE))
    parser.add_argument("--replay", default=str(DEFAULT_REPLAY))
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--out", default=None, help="JSON report path")
    parser.add_argument("--port-log", default=None, help="port_log() file (default: <SDL pref path>/BattleShip/ssb64.log)")
    parser.add_argument("--ordinary-frames", type=int, default=300, help="SSB64_MAX_FRAMES for the ordinary launches")
    parser.add_argument("--replay-frames", type=int, default=1500, help="SSB64_MAX_FRAMES for the checksum replay runs")
    parser.add_argument("--precedence-port", type=int, default=52103)
    parser.add_argument("--native-timeout", type=float, default=120.0)
    parser.add_argument("--replay-timeout", type=float, default=180.0)
    parser.add_argument("--startup-timeout", type=float, default=60.0)
    parser.add_argument("--ready-timeout", type=float, default=180.0)
    parser.add_argument("--request-timeout", type=float, default=30.0)
    parser.add_argument("--exit-timeout", type=float, default=30.0)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        rows = read_btti_rows(args.replay)
    except (OSError, ReplayFormatError) as exc:
        log(f"M6 RAPHNET ERROR: cannot use replay: {exc}")
        return EXIT_BAD_INPUT
    if len(rows) != SOURCE_ROWS:
        log(f"M6 RAPHNET ERROR: {args.replay} has {len(rows)} rows, expected {SOURCE_ROWS}")
        return EXIT_BAD_INPUT
    exe = Path(args.exe)
    if not exe.is_file():
        log(f"M6 RAPHNET ERROR: executable not found: {exe}")
        return EXIT_BAD_INPUT
    run_root = Path(args.run_dir) if args.run_dir else Path(tempfile.mkdtemp(prefix="battleship_m6_raphnet_"))
    run_root.mkdir(parents=True, exist_ok=True)
    h = Harness(args, rows, run_root)
    before = count_battleship_processes(exe)
    log(f"M6 Raphnet bypass regression: {exe} ; processes before: {before}; port log {h.port_log.path}; "
        f"libultraship log {h.lus_log.path}; run_dir={run_root}")
    report: Dict[str, Any] = {
        "tool": "rl/m6_raphnet_bypass_regression.py", "executable": str(exe.resolve()),
        "executable_sha256": sha256_of(exe), "replay": Path(args.replay).name, "flag": RAPHNET_DISABLE_ENV,
        "config_path": str(h.config_path), "cases": [], "result": None, "failure": None,
    }
    failure: Optional[str] = None
    try:
        h.snapshot_and_backup()
        assert h.before is not None
        report["config_before"] = {"sha256": h.before.sha256, "size": h.before.size, "raphnet_key": h.before.raphnet_key()}
        run_cases(h, report)
    except RegressionFailure as exc:
        failure = describe_regression_failure(exc) if getattr(exc, "row", None) is not None else str(exc)
    except EpisodeFailure as exc:
        failure = f"lifecycle failure {exc.outcome.value}: {exc}"
    except BattleShipError as exc:
        failure = f"client error: {exc}"
    finally:
        if h.before is not None and h.config_path.is_file():
            final = ConfigSnapshot.take(h.config_path)
            report["config_after_all"] = h.before.compare(final)
    after = count_battleship_processes(exe)
    leaked = before is not None and after is not None and after > before
    report["process_count"] = {"before": before, "after": after, "leaked": leaked}
    if failure is None and leaked:
        failure = f"{exe.name} count rose from {before} to {after}"
    report["reference_adapter_opened"] = h.reference_adapter_opened
    report["result"] = "PASS" if failure is None else "FAIL"
    report["failure"] = failure
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        log(f"report written to {args.out}")
    passed = sum(1 for c in report["cases"] if c["ok"])
    if failure is None:
        cfg = report.get("config_after_all", {})
        log(f"M6 RAPHNET BYPASS PASS: {passed}/{len(report['cases'])} cases; config bytes identical after every process "
            f"(sha256 {cfg.get('sha256_after', '')[:16]}...), gControllers.Raphnet {cfg.get('raphnet_key_after')!r} unchanged; "
            f"reference adapter opened={h.reference_adapter_opened}; processes before={before} after={after}")
        return EXIT_PASS
    log(f"M6 RAPHNET BYPASS FAIL ({passed}/{len(report['cases'])} cases passed): {failure}")
    return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
