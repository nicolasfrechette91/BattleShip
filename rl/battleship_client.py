#!/usr/bin/env python3
"""Minimal standard-library client for the BattleShip M1d stepping transport.

BattleShip exposes the frozen M1c one-action / one-native-tick stepping
primitive over a loopback TCP socket when it is launched with::

    SSB64_RL_BTT=1 SSB64_RL_STEP=1 SSB64_RL_PORT=<port>

This module speaks protocol version 1 (newline-delimited JSON, documented in
port/rl/rl_transport.cpp and docs/rl_transport_m1d.md) and nothing else: no
reward, no reset, no process management, no Gymnasium, no action
discretisation. Integers stay integers, floats are the values the game
reported, and every native M1c return code is surfaced verbatim.

Typical use::

    from battleship_client import BattleShipClient, Button

    with BattleShipClient(port=5555) as client:
        client.wait_until_can_step(timeout=60.0)
        result = client.step(buttons=Button.NONE, stick_x=0, stick_y=0)
        assert result.observation.input_tick == result.consumed_tick + 1

Only the standard library is used.
"""

from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass, fields
from enum import IntEnum
from typing import Any, Dict, Optional

PROTOCOL_VERSION = 1
DEFAULT_HOST = "127.0.0.1"


class Button(IntEnum):
    """Native N64 button word values (RL_BUTTON_* in port/rl/rl.h).

    A step accepts 0 or exactly one of the permitted bits. START and the
    D-pad are listed only so their rejection can be exercised: the server
    (M1c rlStepValidateAction) rejects them.
    """

    NONE = 0x0000
    A = 0x8000
    B = 0x4000
    Z = 0x2000
    START = 0x1000  # always rejected
    DPAD_UP = 0x0800  # always rejected
    DPAD_DOWN = 0x0400  # always rejected
    DPAD_LEFT = 0x0200  # always rejected
    DPAD_RIGHT = 0x0100  # always rejected
    L = 0x0020
    R = 0x0010
    C_UP = 0x0008
    C_DOWN = 0x0004
    C_LEFT = 0x0002
    C_RIGHT = 0x0001


class StepState(IntEnum):
    """RLStepState (port/rl/rl.h)."""

    DISABLED = 0
    INACTIVE = 1
    WAITING_FOR_ACTION = 2
    ACTION_READY = 3
    ACTION_CONSUMED = 4
    OBSERVATION_READY = 5
    EPISODE_ENDED = 6
    STOPPING = 7


# RL_STEP_ERR_* codes, surfaced verbatim in NativeStepError.native_code.
NATIVE_ERROR_NAMES = {
    -1: "null",
    -2: "disabled",
    -3: "invalid_action",
    -4: "not_ready",
    -5: "busy",
    -6: "episode_ended",
    -7: "stopping",
    -8: "main_thread",
}


class BattleShipError(Exception):
    """Base class for every error raised by this module."""


class ConnectionClosed(BattleShipError, ConnectionError):
    """BattleShip closed the connection (EOF) or the socket failed."""


class ProtocolError(BattleShipError):
    """The server answered ok=false. `error` is the wire error name."""

    def __init__(self, response: Dict[str, Any]):
        self.response = response
        self.op = response.get("op")
        self.error = response.get("error", "unknown")
        self.message = response.get("message", "")
        self.native_code: Optional[int] = response.get("native_code")
        super().__init__(f"{self.error}: {self.message}")


class NativeStepError(ProtocolError):
    """An M1c return code (RL_STEP_ERR_*), unchanged, in `native_code`."""


@dataclass(frozen=True)
class Observation:
    """RLObservation (M1b), field for field, native types preserved."""

    observation_schema: int
    host_frame: int
    input_tick: int
    time_passed: int
    game_status: int
    btt_active: int
    targets_remaining: int
    fighter_valid: int
    position_x: float
    position_y: float
    air_velocity_x: float
    air_velocity_y: float
    ground_velocity_x: float
    facing_direction: int
    ground_air_state: int
    fighter_status_id: int
    jumps_used: int

    @classmethod
    def from_wire(cls, data: Dict[str, Any]) -> "Observation":
        expected = {f.name for f in fields(cls)}
        got = set(data)
        if got != expected:
            raise BattleShipError(
                "observation fields differ from schema: "
                f"missing={sorted(expected - got)} extra={sorted(got - expected)}"
            )
        return cls(**data)


@dataclass(frozen=True)
class StepResult:
    """RLStepResult for one accepted action: observation.input_tick == consumed_tick + 1."""

    state: StepState
    state_name: str
    step_count: int
    consumed_tick: int
    observation: Observation


@dataclass(frozen=True)
class Status:
    """Non-consuming state query. It carries no observation: the only
    observation the transport forwards is the paired result of a step."""

    state: StepState
    state_name: str
    can_step: bool
    step_count: int


def _wire_int(name: str, value: Any) -> int:
    # bool is an int subclass; the wire rejects it, so reject it here too.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    return int(value)


class BattleShipClient:
    """One connection to one BattleShip process. Not thread-safe."""

    def __init__(self, port: int, host: str = DEFAULT_HOST, timeout: Optional[float] = None):
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._buffer = b""

    # -- connection ---------------------------------------------------------

    def connect(self, retry_timeout: float = 0.0) -> None:
        """Connect. With retry_timeout > 0, keep retrying a refused connection
        for that many seconds (the game takes a few seconds to boot)."""
        deadline = time.monotonic() + retry_timeout
        while True:
            try:
                self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
                self._buffer = b""
                return
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise ConnectionClosed(f"cannot connect to {self.host}:{self.port}: {exc}") from exc
                time.sleep(0.1)

    def close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def __enter__(self) -> "BattleShipClient":
        if not self.connected:
            self.connect()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- wire ----------------------------------------------------------------

    def send_raw_line(self, line: str) -> None:
        """Send one raw line verbatim (a newline is appended). For tests."""
        if self._sock is None:
            raise ConnectionClosed("not connected")
        try:
            self._sock.sendall(line.encode("utf-8") + b"\n")
        except OSError as exc:
            self.close()
            raise ConnectionClosed(f"send failed: {exc}") from exc

    def recv_response(self) -> Dict[str, Any]:
        """Read one response line and parse it. Does not raise on ok=false."""
        if self._sock is None:
            raise ConnectionClosed("not connected")
        while b"\n" not in self._buffer:
            try:
                chunk = self._sock.recv(4096)
            except OSError as exc:
                self.close()
                raise ConnectionClosed(f"recv failed: {exc}") from exc
            if not chunk:
                self.close()
                raise ConnectionClosed("BattleShip closed the connection")
            self._buffer += chunk
        line, _, self._buffer = self._buffer.partition(b"\n")
        try:
            response = json.loads(line.decode("utf-8"))
        except ValueError as exc:
            raise BattleShipError(f"unparseable response: {line!r}") from exc
        if not isinstance(response, dict):
            raise BattleShipError(f"response is not an object: {line!r}")
        if response.get("protocol") != PROTOCOL_VERSION:
            raise BattleShipError(f"unexpected protocol in response: {response.get('protocol')!r}")
        return response

    def raw_request(self, line: str) -> Dict[str, Any]:
        """Send a raw line and return the parsed reply without raising on ok=false."""
        self.send_raw_line(line)
        return self.recv_response()

    def request(self, op: str, **payload: Any) -> Dict[str, Any]:
        """Send {"protocol": 1, "op": op, **payload} and raise on ok=false."""
        message: Dict[str, Any] = {"protocol": PROTOCOL_VERSION, "op": op}
        message.update(payload)
        response = self.raw_request(json.dumps(message, separators=(",", ":")))
        if response.get("ok") is not True:
            if response.get("native_code") is not None:
                raise NativeStepError(response)
            raise ProtocolError(response)
        return response

    # -- operations ------------------------------------------------------------

    def ping(self) -> None:
        self.request("ping")

    def status(self) -> Status:
        r = self.request("status")
        return Status(
            state=StepState(r["state"]),
            state_name=r["state_name"],
            can_step=bool(r["can_step"]),
            step_count=r["step_count"],
        )

    def step(self, buttons: int, stick_x: int, stick_y: int) -> StepResult:
        """Submit one raw M1c action and return its paired result.

        Values are sent as given (no clamping, scaling or discretisation).
        The server validates ranges and the button rule; a rejection becomes
        NativeStepError (M1c code) or ProtocolError here.
        """
        r = self.request(
            "step",
            buttons=_wire_int("buttons", buttons),
            stick_x=_wire_int("stick_x", stick_x),
            stick_y=_wire_int("stick_y", stick_y),
        )
        return StepResult(
            state=StepState(r["state"]),
            state_name=r["state_name"],
            step_count=r["step_count"],
            consumed_tick=r["consumed_tick"],
            observation=Observation.from_wire(r["observation"]),
        )

    def wait_until_can_step(self, timeout: Optional[float] = None, poll_interval: float = 0.05) -> Status:
        """Poll status until an action can be submitted (BTT reached its first
        input tick). This waits for boot only, never for a step: a step's
        result is delivered by the step call itself."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            status = self.status()
            if status.can_step:
                return status
            if status.state in (StepState.DISABLED, StepState.EPISODE_ENDED, StepState.STOPPING):
                raise BattleShipError(f"stepping is not possible: state={status.state_name}")
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(f"still {status.state_name} after {timeout} s")
            time.sleep(poll_interval)
