#!/usr/bin/env python3
"""M2: process-restart episode management for BattleShip Mario Break the Targets.

One BattleShip OS process runs exactly one M1c episode. This module owns that
process from launch to exit and nothing else: it never resets, saves or
restores game state, and it never touches the wire protocol (that is
BattleShipClient in rl/battleship_client.py). A fresh episode is, by
definition,

    a new BattleShip process
    + isolated per-episode files (save, result JSON, process log)
    + a new M1d connection
    + native state WaitingForAction with can_step and step_count == 0

and a second episode is always a second process. The only reset mechanism is
"terminate or dispose the old process, then launch a new one". There is no
in-process reset, no native reset command and no save state.

Lifecycle of one episode::

    config = LaunchConfig(executable=Path("build-us/Release/BattleShip.exe"))
    with BattleShipEpisode(config, index=1) as episode:
        fresh = episode.start()              # launch, wait for transport, wait for fresh state
        result = episode.client.step(0, 0, 0)
        ...                                  # step until result.state == StepState.EPISODE_ENDED
        done = episode.finish(result)        # close client, wait for the native clean exit, load result JSON
    # leaving the block terminates/kills anything still alive; cleanup is idempotent

Startup is two-staged and never a fixed sleep: stage 1 retries the loopback
connection while watching the process, stage 2 polls the non-consuming M1d
`status` until the native state is fresh. Only `Inactive` is tolerated while
booting; anything else that is not the fresh state is refused.

Standard library only.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from battleship_client import (  # noqa: E402
    DEFAULT_HOST,
    BattleShipClient,
    BattleShipError,
    ConnectionClosed,
    NativeStepError,
    ProtocolError,
    Status,
    StepResult,
    StepState,
)

# Frozen M1a result schema (port/rl/rl_result.cpp). Values are validated by the
# caller against its own expectations; this module checks shape and types only,
# plus agreement with the terminal M1c observation of the same update.
RESULT_SCHEMA = 1
RESULT_INT_FIELDS = (
    "targets_broken",
    "completion_time_passed",
    "completion_input_tick",
    "time_passed_final",
    "input_cursor_final",
    "host_frames",
)

# Inherited shell state that must never reach the child. A configured replay
# takes precedence over interactive stepping and disables the transport
# (rl_boot.cpp); a frame cap ends the process early (port.cpp SSB64_MAX_FRAMES
# debug aid). A caller that wants the frame cap on purpose passes it through
# LaunchConfig.extra_env; SSB64_BTT_INPUT can never be passed through.
CHILD_ENV_REMOVED = ("SSB64_BTT_INPUT", "SSB64_MAX_FRAMES")


class EpisodeOutcome(str, Enum):
    """How an episode ended. COMPLETED requires every condition in finish()."""

    COMPLETED = "completed"
    STARTUP_FAILURE = "startup_failure"  # process gone (or never started) before a fresh episode existed
    STARTUP_TIMEOUT = "startup_timeout"  # alive, but the M1d transport never became reachable
    READINESS_TIMEOUT = "readiness_timeout"  # connected, still not fresh at the readiness deadline
    NOT_FRESH = "not_fresh"  # connected to a state that can never become a fresh episode
    PREMATURE_EXIT = "premature_exit"  # fresh episode established, process exited before EpisodeEnded
    EPISODE_TIMEOUT = "episode_timeout"  # alive, but a request deadline expired mid-episode
    TRANSPORT_FAILURE = "transport_failure"  # alive, but the connection failed mid-episode
    REQUEST_REJECTED = "request_rejected"  # alive, the server rejected a request (protocol or native code)
    EXIT_TIMEOUT = "exit_timeout"  # terminal result collected, process still alive at the exit deadline
    EXIT_FAILURE = "exit_failure"  # terminal result collected, process exited with a non-zero code
    RESULT_INVALID = "result_invalid"  # exited 0, but the native result JSON is missing or malformed
    CLEANUP_FAILURE = "cleanup_failure"  # terminate and kill both left the process alive


class EpisodeFailure(Exception):
    """One classified lifecycle failure with the diagnostics needed to look into it."""

    def __init__(
        self,
        outcome: EpisodeOutcome,
        message: str,
        *,
        episode: Optional["BattleShipEpisode"] = None,
        exit_code: Optional[int] = None,
    ):
        super().__init__(message)
        self.outcome = outcome
        self.message = message
        self.exit_code = exit_code
        self.diagnostics: Dict[str, Any] = episode.diagnostics() if episode is not None else {}
        if exit_code is not None:
            self.diagnostics["exit_code"] = exit_code

    def __str__(self) -> str:
        lines = [f"{self.outcome.value}: {self.message}"]
        lines += [f"  {key}: {value}" for key, value in self.diagnostics.items() if value is not None]
        return "\n".join(lines)


class ResultInvalid(ValueError):
    """The native result JSON is missing, unreadable or not the frozen M1a shape."""


@dataclass(frozen=True)
class LaunchConfig:
    """Everything needed to launch one episode. Paths are never hard-coded here."""

    executable: Path
    arguments: Sequence[str] = ()  # extra argv after the executable (BattleShip itself takes none)
    working_dir: Optional[Path] = None  # default: the executable's directory (runtime assets live there)
    run_root: Optional[Path] = None  # parent of the per-episode directories; default: a fresh temp dir
    port: Optional[int] = None  # loopback port; default: ask the OS for a free one per episode
    host: str = DEFAULT_HOST
    startup_timeout: float = 60.0  # stage 1: process start -> transport reachable
    ready_timeout: float = 180.0  # stage 2: transport reachable -> fresh WaitingForAction
    request_timeout: float = 30.0  # per M1d request; a hung game becomes episode_timeout, not a hang
    exit_timeout: float = 30.0  # terminal result collected -> process exit (SSB64_RL_EXIT_ON_END)
    terminate_timeout: float = 10.0  # abort path: wait after terminate()
    kill_timeout: float = 10.0  # abort path: wait after kill()
    poll_interval: float = 0.05
    extra_env: Mapping[str, str] = field(default_factory=dict)  # applied before the mandatory M2 settings


@dataclass(frozen=True)
class EpisodePaths:
    directory: Path
    save_path: Path
    result_path: Path
    log_path: Path  # child stdout + stderr


@dataclass(frozen=True)
class EpisodeExit:
    """A completed episode: clean exit plus the validated native result."""

    exit_code: int
    result: Dict[str, Any]
    result_path: Path
    terminal: StepResult


# -- ports ---------------------------------------------------------------------


def _exclusive_probe_socket() -> socket.socket:
    """A socket whose bind() fails whenever another socket holds the port.

    A connect probe is not usable for this: on Windows a closed loopback port
    can answer with silence (a timeout) rather than a refusal. An exclusive
    bind is unambiguous: it succeeds only if nothing is bound there. On
    Windows SO_EXCLUSIVEADDRUSE also defeats SO_REUSEADDR binders; on POSIX
    SO_REUSEADDR keeps a TIME_WAIT leftover from counting as busy while a
    listener still does.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    if exclusive is not None:
        probe.setsockopt(socket.SOL_SOCKET, exclusive, 1)
    else:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    return probe


def loopback_port_is_free(port: int, host: str = DEFAULT_HOST) -> bool:
    """True only if nothing is bound to host:port right now (a stale BattleShip would be)."""
    probe = _exclusive_probe_socket()
    try:
        probe.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def allocate_loopback_port(host: str = DEFAULT_HOST) -> int:
    """Ask the OS for a free loopback port and hand it back with nothing bound.

    The reservation socket is closed before the child starts, so BattleShip
    can bind the port. The window between closing it and the native bind is
    unavoidable; the native side reports a bind failure in its log and the
    launch then fails as startup_timeout.
    """
    reservation = _exclusive_probe_socket()
    try:
        reservation.bind((host, 0))
        return int(reservation.getsockname()[1])
    finally:
        reservation.close()


# -- environment ---------------------------------------------------------------


def build_child_env(config: LaunchConfig, port: int, paths: EpisodePaths) -> Dict[str, str]:
    """A copy of this process's environment with the M2 episode settings.

    The parent environment is never mutated. extra_env is applied first so the
    mandatory settings always win, and SSB64_BTT_INPUT is removed last so no
    inherited or extra value can activate native replay mode.
    """
    env = os.environ.copy()
    for key in CHILD_ENV_REMOVED:
        env.pop(key, None)
    env.update({str(k): str(v) for k, v in config.extra_env.items()})
    env["SSB64_RL_BTT"] = "1"
    env["SSB64_RL_STEP"] = "1"
    env["SSB64_RL_PORT"] = str(port)
    env["SSB64_SAVE_PATH"] = str(paths.save_path)
    env["SSB64_RL_RESULT_PATH"] = str(paths.result_path)
    env["SSB64_RL_EXIT_ON_END"] = "1"
    env.pop("SSB64_BTT_INPUT", None)
    return env


# -- result JSON ---------------------------------------------------------------


def load_result_json(path: Path, terminal: Optional[StepResult] = None) -> Dict[str, Any]:
    """Read the native result and check its frozen M1a shape (not its values).

    With `terminal`, the completion fields must agree with the terminal M1c
    observation: both are sampled from the post-update in which the last
    target broke. The two clocks are compared each to its own counterpart and
    never to each other.
    """
    try:
        with open(path, encoding="utf-8") as fp:
            data = json.load(fp)
    except FileNotFoundError as exc:
        raise ResultInvalid(f"result JSON was not written: {path}") from exc
    except (OSError, ValueError) as exc:
        raise ResultInvalid(f"result JSON unreadable: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ResultInvalid(f"result JSON is not an object: {path}")
    if data.get("result_schema") != RESULT_SCHEMA:
        raise ResultInvalid(f"result_schema is {data.get('result_schema')!r}, expected {RESULT_SCHEMA}")
    if not isinstance(data.get("outcome"), str):
        raise ResultInvalid(f"outcome is {data.get('outcome')!r}, expected a string")
    for key in RESULT_INT_FIELDS:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ResultInvalid(f"{key} is {value!r}, expected an integer")
    if terminal is not None:
        o = terminal.observation
        if data["completion_time_passed"] != o.time_passed:
            raise ResultInvalid(
                f"completion_time_passed {data['completion_time_passed']} disagrees with the terminal "
                f"observation time_passed {o.time_passed}"
            )
        if data["completion_input_tick"] != o.input_tick:
            raise ResultInvalid(
                f"completion_input_tick {data['completion_input_tick']} disagrees with the terminal "
                f"observation input_tick {o.input_tick}"
            )
    return data


def describe_error(exc: BaseException) -> str:
    if isinstance(exc, ProtocolError):  # includes NativeStepError
        code = f" native_code={exc.native_code}" if exc.native_code is not None else ""
        return f"{exc.error}{code}: {exc.message}"
    return f"{type(exc).__name__}: {exc}"


# -- one process, one episode ---------------------------------------------------


class BattleShipEpisode:
    """Owns one BattleShip OS process for one episode. Not thread-safe.

    Use as a context manager (or call close() in a finally block): leaving the
    block guarantees the process is gone, whatever happened inside.
    """

    def __init__(self, config: LaunchConfig, index: int = 0):
        self.config = config
        self.index = index
        self.paths: Optional[EpisodePaths] = None
        self.port: Optional[int] = None
        self.process: Optional[subprocess.Popen] = None
        self.client: Optional[BattleShipClient] = None
        self.fresh_status: Optional[Status] = None
        self.exit_code: Optional[int] = None
        self.cleanup_action: Optional[str] = None
        self.timeline: Dict[str, float] = {}  # monotonic timestamps of lifecycle events
        self._closed = False

    # -- context manager ---------------------------------------------------------

    def __enter__(self) -> "BattleShipEpisode":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- queries -------------------------------------------------------------------

    @property
    def pid(self) -> Optional[int]:
        return self.process.pid if self.process is not None else None

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "episode": self.index,
            "executable": str(self.config.executable),
            "working_dir": str(self._working_dir()),
            "episode_dir": str(self.paths.directory) if self.paths else None,
            "log_file": str(self.paths.log_path) if self.paths else None,
            "result_file": str(self.paths.result_path) if self.paths else None,
            "port": self.port,
            "pid": self.pid,
            "exit_code": self.process.returncode if self.process is not None else None,
        }

    def seconds(self, start: str, end: str) -> Optional[float]:
        if start in self.timeline and end in self.timeline:
            return self.timeline[end] - self.timeline[start]
        return None

    # -- lifecycle -------------------------------------------------------------------

    def start(self) -> Status:
        """launch() + wait_for_transport() + wait_for_fresh_episode()."""
        self.launch()
        self.wait_for_transport()
        return self.wait_for_fresh_episode()

    def launch(self) -> None:
        """Preflight, then start a NEW BattleShip process for this episode."""
        if self.process is not None:
            raise RuntimeError("launch() may be called once per BattleShipEpisode")
        if self._closed:
            raise RuntimeError("this episode was already closed")
        executable = Path(self.config.executable)
        if not executable.is_file():
            raise EpisodeFailure(EpisodeOutcome.STARTUP_FAILURE, f"executable not found: {executable}", episode=self)
        working_dir = self._working_dir()
        if not working_dir.is_dir():
            raise EpisodeFailure(
                EpisodeOutcome.STARTUP_FAILURE, f"working directory not found: {working_dir}", episode=self
            )

        self.paths = self._make_paths()
        if self.config.port is None:
            self.port = allocate_loopback_port(self.config.host)
        else:
            self.port = int(self.config.port)
            if not loopback_port_is_free(self.port, self.config.host):
                raise EpisodeFailure(
                    EpisodeOutcome.STARTUP_FAILURE,
                    f"port {self.port} already accepts connections; refusing to launch beside it",
                    episode=self,
                )
        env = build_child_env(self.config, self.port, self.paths)

        # The child inherits the log handle; ours is closed right after the
        # spawn. No pipes: nothing has to be drained.
        with open(self.paths.log_path, "wb") as log:
            try:
                self.process = subprocess.Popen(
                    [str(executable), *map(str, self.config.arguments)],
                    cwd=str(working_dir),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            except OSError as exc:
                raise EpisodeFailure(
                    EpisodeOutcome.STARTUP_FAILURE, f"cannot start {executable}: {exc}", episode=self
                ) from exc
        self.timeline["launched"] = time.monotonic()

    def wait_for_transport(self) -> None:
        """Stage 1: retry the loopback connection until the startup deadline,
        failing at once if the process exits first."""
        self._require_launched()
        assert self.process is not None and self.port is not None
        deadline = time.monotonic() + self.config.startup_timeout
        client = BattleShipClient(port=self.port, host=self.config.host, timeout=self.config.request_timeout)
        while True:
            code = self.process.poll()
            if code is not None:
                raise EpisodeFailure(
                    EpisodeOutcome.STARTUP_FAILURE,
                    f"BattleShip exited with code {code} before the transport was reachable",
                    episode=self,
                    exit_code=code,
                )
            try:
                client.connect()
            except ConnectionClosed:
                if time.monotonic() >= deadline:
                    raise EpisodeFailure(
                        EpisodeOutcome.STARTUP_TIMEOUT,
                        f"transport 127.0.0.1:{self.port} not reachable after {self.config.startup_timeout:g} s "
                        "(process still alive; a native bind failure is reported in ssb64.log)",
                        episode=self,
                    ) from None
                time.sleep(self.config.poll_interval)
                continue
            self.client = client
            self.timeline["transport"] = time.monotonic()
            return

    def wait_for_fresh_episode(self) -> Status:
        """Stage 2: poll the non-consuming status until the episode is fresh.

        Fresh means state WaitingForAction, can_step true, step_count 0.
        Inactive is tolerated while the game boots. Any other state is refused
        immediately as not_fresh: nothing here sends an action, recovers or
        resets.
        """
        self._require_launched()
        assert self.process is not None and self.client is not None
        deadline = time.monotonic() + self.config.ready_timeout
        while True:
            try:
                status = self.client.status()
            except BattleShipError as exc:
                raise self._classify_before_fresh(exc) from exc
            if status.state == StepState.WAITING_FOR_ACTION and status.can_step and status.step_count == 0:
                self.fresh_status = status
                self.timeline["fresh"] = time.monotonic()
                return status
            if status.state != StepState.INACTIVE:
                raise EpisodeFailure(
                    EpisodeOutcome.NOT_FRESH,
                    f"native state {status.state_name} can_step={status.can_step} step_count={status.step_count} "
                    "can never become a fresh episode",
                    episode=self,
                )
            code = self.process.poll()
            if code is not None:
                raise EpisodeFailure(
                    EpisodeOutcome.STARTUP_FAILURE,
                    f"BattleShip exited with code {code} while still {status.state_name}",
                    episode=self,
                    exit_code=code,
                )
            if time.monotonic() >= deadline:
                raise EpisodeFailure(
                    EpisodeOutcome.READINESS_TIMEOUT,
                    f"still {status.state_name} after {self.config.ready_timeout:g} s; never reached fresh "
                    "WaitingForAction with step_count 0",
                    episode=self,
                )
            time.sleep(self.config.poll_interval)

    def classify_step_failure(self, exc: BattleShipError) -> EpisodeFailure:
        """Explain a request that failed after the fresh episode was established.

        A process that is shutting down may still be alive for a moment after
        the connection drops, so an EOF or a native `stopping` error waits a
        bounded time for the exit code before deciding between premature_exit
        and a live-process failure.
        """
        stopping = isinstance(exc, NativeStepError) and exc.error == "stopping"
        dropped = isinstance(exc, ConnectionClosed)
        timed_out = dropped and isinstance(exc.__cause__, (socket.timeout, TimeoutError))
        grace = self.config.exit_timeout if (stopping or (dropped and not timed_out)) else 0.0
        code = self._wait_exit(grace)
        detail = describe_error(exc)
        if code is not None:
            return EpisodeFailure(
                EpisodeOutcome.PREMATURE_EXIT,
                f"BattleShip exited with code {code} before the terminal EpisodeEnded result was collected ({detail})",
                episode=self,
                exit_code=code,
            )
        if timed_out:
            return EpisodeFailure(
                EpisodeOutcome.EPISODE_TIMEOUT,
                f"no reply within the {self.config.request_timeout:g} s request deadline; process still alive ({detail})",
                episode=self,
            )
        if dropped or stopping:
            return EpisodeFailure(
                EpisodeOutcome.TRANSPORT_FAILURE, f"connection failed while the process is alive ({detail})", episode=self
            )
        return EpisodeFailure(EpisodeOutcome.REQUEST_REJECTED, detail, episode=self)

    def finish(self, terminal: StepResult) -> EpisodeExit:
        """After the terminal EpisodeEnded step result: close the client, wait
        for the native clean exit (SSB64_RL_EXIT_ON_END=1), require exit code
        0 and a valid result JSON. No shutdown command is sent."""
        if terminal.state != StepState.EPISODE_ENDED:
            raise ValueError(f"finish() requires the terminal EpisodeEnded step result, got {terminal.state_name}")
        self._require_launched()
        assert self.process is not None and self.paths is not None
        if self.client is not None:
            self.client.close()
        code = self._wait_exit(self.config.exit_timeout)
        if code is None:
            raise EpisodeFailure(
                EpisodeOutcome.EXIT_TIMEOUT,
                f"process still alive {self.config.exit_timeout:g} s after the terminal result was collected",
                episode=self,
            )
        self.timeline["exited"] = time.monotonic()
        self.exit_code = code
        if code != 0:
            raise EpisodeFailure(
                EpisodeOutcome.EXIT_FAILURE, f"process exited with code {code}, expected 0", episode=self, exit_code=code
            )
        try:
            result = load_result_json(self.paths.result_path, terminal)
        except ResultInvalid as exc:
            raise EpisodeFailure(EpisodeOutcome.RESULT_INVALID, str(exc), episode=self, exit_code=code) from exc
        return EpisodeExit(exit_code=code, result=result, result_path=self.paths.result_path, terminal=terminal)

    def close(self) -> str:
        """Idempotent cleanup: close the client, then make sure the process is gone.

        Returns what was needed: not_launched, already_exited, terminated or
        killed. Raises EpisodeFailure(cleanup_failure) only if kill() left the
        process alive.
        """
        if self._closed:
            return self.cleanup_action or "not_launched"
        self._closed = True
        if self.client is not None:
            self.client.close()
        process = self.process
        if process is None:
            self.cleanup_action = "not_launched"
            return self.cleanup_action
        if process.poll() is not None:
            self.cleanup_action = "already_exited"
        else:
            self._signal(process.terminate)
            if self._wait_exit(self.config.terminate_timeout) is not None:
                self.cleanup_action = "terminated"
            else:
                self._signal(process.kill)
                if self._wait_exit(self.config.kill_timeout) is not None:
                    self.cleanup_action = "killed"
                else:
                    self.cleanup_action = "still_alive"
        self.exit_code = process.returncode
        self.timeline.setdefault("exited", time.monotonic())
        if self.cleanup_action == "still_alive":
            raise EpisodeFailure(
                EpisodeOutcome.CLEANUP_FAILURE,
                f"pid {process.pid} survived terminate() and kill()",
                episode=self,
            )
        return self.cleanup_action

    # -- internals -------------------------------------------------------------------

    def _working_dir(self) -> Path:
        if self.config.working_dir is not None:
            return Path(self.config.working_dir)
        return Path(self.config.executable).resolve().parent

    def _make_paths(self) -> EpisodePaths:
        if self.config.run_root is not None:
            run_root = Path(self.config.run_root)
            run_root.mkdir(parents=True, exist_ok=True)
        else:
            run_root = Path(tempfile.mkdtemp(prefix="battleship_m2_"))
        # mkdtemp makes the per-episode directory unique even if the same index
        # is launched again after a failure.
        directory = Path(tempfile.mkdtemp(prefix=f"episode_{self.index:03d}_", dir=str(run_root)))
        return EpisodePaths(
            directory=directory,
            save_path=directory / "ssb64_save.bin",
            result_path=directory / "result.json",
            log_path=directory / "battleship_stdout.log",
        )

    def _require_launched(self) -> None:
        if self.process is None:
            raise RuntimeError("launch() has not been called")

    def _wait_exit(self, timeout: float) -> Optional[int]:
        assert self.process is not None
        try:
            return self.process.wait(timeout=max(timeout, 0.0))
        except subprocess.TimeoutExpired:
            return None

    @staticmethod
    def _signal(action: Any) -> None:
        try:
            action()
        except OSError:
            pass  # already gone; the following wait() reports it

    def _classify_before_fresh(self, exc: BattleShipError) -> EpisodeFailure:
        code = self._wait_exit(self.config.exit_timeout if isinstance(exc, ConnectionClosed) else 0.0)
        detail = describe_error(exc)
        if code is not None:
            return EpisodeFailure(
                EpisodeOutcome.STARTUP_FAILURE,
                f"BattleShip exited with code {code} before a fresh episode was established ({detail})",
                episode=self,
                exit_code=code,
            )
        return EpisodeFailure(
            EpisodeOutcome.TRANSPORT_FAILURE,
            f"status request failed before a fresh episode was established; process still alive ({detail})",
            episode=self,
        )
