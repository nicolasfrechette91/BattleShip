"""M7g: capture or import a user-produced Track 1 action sequence (crossing-fixture candidate).

The game cannot record live Break-the-Targets input natively (M7g Phase B audit), so capture happens on the client
side of the existing M1c/M1d stepping protocol: this tool launches a FRESH BattleShip process (visible window by
default, private runtime directory = a byte copy of the user configuration), reads the user's keyboard or XInput
gamepad once per native tick, maps the held keys to exactly one of the 72 Track 1 (`btt_s9_b8_v1`) actions, submits
it, and records it. Every recorded action is therefore a Track 1 action by construction; the native triple sent is
the frozen table image, never an analog value. The first recorded action consumes native tick 0; there is no hidden
prefix (a resumed session replays its prefix from tick 0 in the same fresh process and records it as part of the
sequence).

While stepping, physical input never reaches the simulation (the injected action overwrites all four controller
slots every tick), but the visible game window still reacts to hotkeys: Ctrl+R resets the game and the Esc menu can
change tap-jump / auto Z-cancel. Keep keyboard focus on THIS console window (the tool reads the keyboard globally).
A capture only becomes a fixture after `rl/m7g_crossing.py build` has replayed it headless in fresh processes and
found the identical native trajectory (a changed setting during capture would show up as a mismatch).

Keyboard (default; override with --keymap FILE.json):
  stick     arrow keys (8 directions; opposite keys cancel)
  buttons   X = A    C = B    Space = C-up    V = C-left    A = L    S = R    Z = Z   (most recently pressed wins)
  control   P = pause/resume   . = advance one tick while paused   [ / ] = slower / faster   Ctrl+Q = save and quit
XInput gamepad (--input xinput): left stick or D-pad = stick (8 sectors, deadzone 50 %); A = A, B = B, Y = C-up,
  X = C-left, LB = L, RB = R, left trigger = Z; Start = pause, right-stick click = advance, Back = save and quit.

Usage:
  python rl/m7g_capture.py play [--label NAME] [--input keyboard|xinput] [--realtime] [--tick-ms MS]
                                [--resume DRAFT --at TICK] [--max-ticks N]
  python rl/m7g_capture.py import <source> --out DRAFT.json      (script / JSON / .btti / artifact; exact Track 1)
  python rl/m7g_capture.py export-script <draft-or-fixture.json> [--out FILE.txt]
Outputs of `play`: runs/m7g/capture/<utc>_<label>/{session.jsonl (autosave), draft.json, draft.txt,
capture_trace.json.gz}. Then: python rl/m7g_crossing.py build <draft.json> --crossing ... --source <the draft's
source kind, printed at the end: user_recorded for a live capture, imported for a continuation of an imported prefix>
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import m7g_fixture as fx  # noqa: E402

REPO_ROOT = RL_DIR.parent
EXE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
CAPTURE_ROOT = REPO_ROOT / "runs" / "m7g" / "capture"
TOOL = "rl/m7g_capture.py"

# stick index from (dx, dy) in {-1, 0, 1}^2 -- the btt_s9_b8_v1 stick table order
STICK_FROM_DIR = {(0, 0): 0, (1, 0): 1, (1, 1): 2, (0, 1): 3, (-1, 1): 4, (-1, 0): 5, (-1, -1): 6, (0, -1): 7,
                  (1, -1): 8}
BUTTON_INDEX = {"none": 0, "A": 1, "B": 2, "C-up": 3, "C-left": 4, "L": 5, "R": 6, "Z": 7}

VK = {"LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28, "SPACE": 0x20, "PERIOD": 0xBE, "COMMA": 0xBC,
      "LBRACKET": 0xDB, "RBRACKET": 0xDD, "CTRL": 0x11, "SHIFT": 0x10, "ENTER": 0x0D, "TAB": 0x09,
      "SEMICOLON": 0xBA, "SLASH": 0xBF, "MINUS": 0xBD, "EQUALS": 0xBB,
      **{chr(c): c for c in range(ord("A"), ord("Z") + 1)}, **{str(d): 0x30 + d for d in range(10)},
      **{f"NUM{d}": 0x60 + d for d in range(10)}}

DEFAULT_KEYMAP: Dict[str, Dict[str, str]] = {
    "stick": {"left": "LEFT", "right": "RIGHT", "up": "UP", "down": "DOWN"},
    "buttons": {"A": "X", "B": "C", "C-up": "SPACE", "C-left": "V", "L": "A", "R": "S", "Z": "Z"},
    "controls": {"pause": "P", "advance": "PERIOD", "slower": "LBRACKET", "faster": "RBRACKET", "quit": "CTRL+Q"},
}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# -- input: pure mapping functions (unit-tested) ------------------------------------------------------------

@dataclass
class Controls:
    stick: int = 0
    button: int = 0
    pause_toggle: bool = False
    advance: bool = False
    slower: bool = False
    faster: bool = False
    quit: bool = False
    disconnected: bool = False  # the input device is gone: the capture pauses instead of recording neutral ticks

    @property
    def action(self) -> Tuple[int, int]:
        return self.stick, self.button


def validate_keymap(keymap: Mapping[str, Mapping[str, str]]) -> Dict[str, Dict[str, str]]:
    km = {k: dict(keymap.get(k) or {}) for k in ("stick", "buttons", "controls")}
    if set(km["stick"]) != {"left", "right", "up", "down"}:
        raise ValueError("keymap.stick needs exactly left/right/up/down")
    if set(km["buttons"]) != set(BUTTON_INDEX) - {"none"}:
        raise ValueError(f"keymap.buttons needs exactly {sorted(set(BUTTON_INDEX) - {'none'})}")
    if set(km["controls"]) != {"pause", "advance", "slower", "faster", "quit"}:
        raise ValueError("keymap.controls needs exactly pause/advance/slower/faster/quit")
    used: List[str] = []
    for section in km.values():
        for key in section.values():
            for part in key.split("+"):
                if part not in VK:
                    raise ValueError(f"unknown key name {part!r}")
            used.append(key)
    if len(used) != len(set(used)):
        raise ValueError("keymap binds one key to two functions")
    return km


class ButtonPriority:
    """Track 1 has one button per tick: of the held button keys, the most recently pressed one wins."""

    def __init__(self) -> None:
        self.order: List[str] = []

    def update(self, held: Iterable[str]) -> str:
        held = list(held)
        self.order = [b for b in self.order if b in held] + [b for b in held if b not in self.order]
        return self.order[-1] if self.order else "none"


def keyboard_controls(down: Set[str], prev: Set[str], keymap: Mapping[str, Mapping[str, str]],
                      priority: ButtonPriority) -> Controls:
    """Map the set of held key names to Controls. Combos like 'CTRL+Q' need all parts held; control keys fire on the
    press edge only."""

    def held(key: str) -> bool:
        return all(p in down for p in key.split("+"))

    def pressed(key: str) -> bool:
        return held(key) and not all(p in prev for p in key.split("+"))

    st = keymap["stick"]
    dx = int(held(st["right"])) - int(held(st["left"]))
    dy = int(held(st["up"])) - int(held(st["down"]))
    button = priority.update([b for b, k in keymap["buttons"].items() if held(k)])
    c = keymap["controls"]
    return Controls(stick=STICK_FROM_DIR[(dx, dy)], button=BUTTON_INDEX[button], pause_toggle=pressed(c["pause"]),
                    advance=pressed(c["advance"]), slower=pressed(c["slower"]), faster=pressed(c["faster"]),
                    quit=pressed(c["quit"]))


XI = {"DPAD_UP": 0x0001, "DPAD_DOWN": 0x0002, "DPAD_LEFT": 0x0004, "DPAD_RIGHT": 0x0008, "START": 0x0010,
      "BACK": 0x0020, "LTHUMB": 0x0040, "RTHUMB": 0x0080, "LB": 0x0100, "RB": 0x0200, "A": 0x1000, "B": 0x2000,
      "X": 0x4000, "Y": 0x8000}
XI_BUTTONS = {"A": "A", "B": "B", "Y": "C-up", "X": "C-left", "LB": "L", "RB": "R"}


def xinput_stick(lx: int, ly: int, dpad_bits: int, deadzone: float = 0.5) -> int:
    """8-sector quantisation of the left stick (D-pad wins when pressed) to a Track 1 stick index."""
    dx = int(bool(dpad_bits & XI["DPAD_RIGHT"])) - int(bool(dpad_bits & XI["DPAD_LEFT"]))
    dy = int(bool(dpad_bits & XI["DPAD_UP"])) - int(bool(dpad_bits & XI["DPAD_DOWN"]))
    if dx or dy:
        return STICK_FROM_DIR[(dx, dy)]
    if math.hypot(lx, ly) < deadzone * 32767:
        return 0
    sector = int(round(math.degrees(math.atan2(ly, lx)) / 45.0)) % 8  # 0 = right, counter-clockwise
    return (1, 2, 3, 4, 5, 6, 7, 8)[sector]


def xinput_controls(lx: int, ly: int, bits: int, lt: int, prev_bits: int, priority: ButtonPriority) -> Controls:
    held = [name for x, name in XI_BUTTONS.items() if bits & XI[x]] + (["Z"] if lt > 100 else [])
    edge = bits & ~prev_bits
    return Controls(stick=xinput_stick(lx, ly, bits), button=BUTTON_INDEX[priority.update(held)],
                    pause_toggle=bool(edge & XI["START"]), advance=bool(edge & XI["RTHUMB"]),
                    quit=bool(edge & XI["BACK"]))


# -- input providers ---------------------------------------------------------------------------------------

class KeyboardInput:
    name = "keyboard"

    def __init__(self, keymap: Optional[Mapping[str, Mapping[str, str]]] = None) -> None:
        self.keymap = validate_keymap(keymap or DEFAULT_KEYMAP)
        self.watch = sorted({p for s in self.keymap.values() for k in s.values() for p in k.split("+")})
        self.user32 = ctypes.windll.user32
        self.prev: Set[str] = set()
        self.priority = ButtonPriority()

    def poll_quit(self) -> bool:
        return self.poll().quit

    def poll(self) -> Controls:
        down = {k for k in self.watch if self.user32.GetAsyncKeyState(VK[k]) & 0x8000}
        c = keyboard_controls(down, self.prev, self.keymap, self.priority)
        self.prev = down
        _drain_console()
        return c


class _XInputGamepad(ctypes.Structure):
    _fields_ = [("wButtons", ctypes.c_ushort), ("bLeftTrigger", ctypes.c_ubyte), ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short), ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short),
                ("sThumbRY", ctypes.c_short)]


class _XInputState(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_uint), ("Gamepad", _XInputGamepad)]


class XInputInput:
    name = "xinput"

    def __init__(self, index: int = 0) -> None:
        self.dll = None
        for lib in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                self.dll = getattr(ctypes.windll, lib)
                break
            except OSError:
                continue
        if self.dll is None:
            raise RuntimeError("no XInput DLL available")
        self.index = index
        self.prev_bits = 0
        self.priority = ButtonPriority()
        if self._state() is None:
            raise RuntimeError(f"no XInput controller connected at index {index}")

    def _state(self) -> Optional[_XInputState]:
        st = _XInputState()
        return st if self.dll.XInputGetState(self.index, ctypes.byref(st)) == 0 else None

    def poll_quit(self) -> bool:
        return self.poll().quit

    def poll(self) -> Controls:
        st = self._state()
        if st is None:  # disconnected: never record neutral ticks; the loop pauses and warns
            self.prev_bits = 0xFFFF  # after a reconnect, a held Start/Back must be released before it counts
            self.priority = ButtonPriority()
            return Controls(disconnected=True)
        g = st.Gamepad
        c = xinput_controls(g.sThumbLX, g.sThumbLY, g.wButtons, g.bLeftTrigger, self.prev_bits, self.priority)
        self.prev_bits = g.wButtons
        _drain_console()
        return c


class ScriptedInput:
    """Deterministic provider for tests: a list of Controls consumed one poll at a time, then quit."""
    name = "scripted"

    def __init__(self, controls: Sequence[Controls]) -> None:
        self.controls = list(controls)
        self.i = 0

    def poll_quit(self) -> bool:
        return False  # the script describes live play only; the prefix never consumes it

    def poll(self) -> Controls:
        if self.i >= len(self.controls):
            return Controls(quit=True)
        c = self.controls[self.i]
        self.i += 1
        return c


def _drain_console() -> None:
    try:
        import msvcrt

        while msvcrt.kbhit():
            msvcrt.getwch()
    except Exception:
        pass


# -- the capture loop ------------------------------------------------------------------------------------

@dataclass
class Session:
    out: Path
    seq: List[Tuple[int, int]] = field(default_factory=list)
    replies: List[Dict[str, Any]] = field(default_factory=list)
    initial: Optional[Dict[str, Any]] = None
    status: Optional[Dict[str, Any]] = None
    end_reason: str = "quit"
    pauses: int = 0
    advances: int = 0
    prefix_replayed: int = 0
    step_ms: List[float] = field(default_factory=list)


def _hud(i: int, reply: Mapping[str, Any], min_x: float, tick_ms: float, paused: bool, geo: fx.StageGeometry) -> str:
    o = reply.get("observation") or {}
    x, y = float(o.get("position_x", 0.0)), float(o.get("position_y", 0.0))
    ga = "G" if o.get("ground_air_state") == 0 else "A"
    surf = fx.classify_ground(geo, o) or ""
    left = " LEFT-OF-WALL" if x < geo.derived["left_boundary_x"] else ""
    return (f"tick {reply.get('consumed_tick', i):5d}  x {x:9.1f}  y {y:8.1f}  {ga} {surf:<16s} targets "
            f"{o.get('targets_remaining')}  min_x {min_x:8.1f}  {tick_ms:5.0f} ms/tick{'  PAUSED' if paused else ''}{left}")


def capture(provider: Any, out: Path, *, mode: str = "normal", realtime: bool = False,
            resume: Optional[Tuple[Path, int]] = None, max_ticks: Optional[int] = None, tick_ms: float = 0.0,
            hud_every: int = 30, executable: Path = EXE, quiet: bool = False,
            poll_interval_s: float = 0.005) -> Dict[str, Any]:
    """Run one capture session in a fresh process; returns the session summary (draft path etc.)."""
    from battleship_client import StepState
    from battleship_process import BattleShipEpisode, LaunchConfig
    from m7_runtime import PortCandidates, file_fingerprint, portable_path, prepare_worker_runtime
    from m7g_crossing import DIAG, MODES, USER_CONFIG, write_json

    out = Path(out).resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"output directory exists and is not empty: {out}")
    out.mkdir(parents=True, exist_ok=True)
    say = (lambda m: None) if quiet else (lambda m: print(m, flush=True))
    geo = fx.decode_stage_geometry()
    prefix: List[Tuple[int, int]] = []
    resumed_from = None
    if resume is not None:
        rpath, at = resume
        full, rmeta = fx.load_sequence(Path(rpath))
        if not 0 <= at <= len(full):
            raise SystemExit(f"--at {at} outside 0..{len(full)}")
        prefix = full[:at]
        resumed_from = {"path": portable_path(rpath), "track1_digest": fx.track1_digest(full), "length": len(full),
                        "prefix_length": at, "source_kind": rmeta.get("source_kind") or "imported"}
    env = {**MODES[mode], **DIAG, **({"SSB64_FREEZE_PACING": "0"} if realtime else {})}
    runtime = out / "runtime"
    prepare_worker_runtime(runtime, executable)
    port, _ = PortCandidates(0).claim()
    cfg = LaunchConfig(executable=Path(executable), working_dir=runtime, run_root=out / "episodes", port=port,
                       startup_timeout=30.0, ready_timeout=90.0, request_timeout=30.0, exit_timeout=30.0,
                       extra_env=env)
    s = Session(out=out)
    started = utc_stamp()
    cfg_before = file_fingerprint(USER_CONFIG)
    gameplay_cfg = fx.gameplay_config(runtime / "BattleShip.cfg.json")  # the private copy this process runs with
    autosave = open(out / "session.jsonl", "w", encoding="utf-8", newline="\n")
    autosave.write(json.dumps({"format": fx.CAPTURE_LOG_FORMAT, "action_contract": fx.track1_contract(),
                               "started_utc": started, "mode": mode, "realtime": realtime, "input": provider.name,
                               "resumed_from": resumed_from, "gameplay_config": gameplay_cfg}) + "\n")
    autosave.flush()
    episode = BattleShipEpisode(cfg, index=0)
    min_x = float("inf")
    paused = False
    last_hud = -1
    left_announced = False
    platform_announced = False
    prev_mask = None
    error: Optional[BaseException] = None
    try:
        with episode:
            fresh = episode.start()
            client = episode.client
            original = client.request

            def request(op: str, **payload: Any) -> Dict[str, Any]:
                reply = original(op, **payload)
                if op == "step":
                    s.replies.append(reply)
                return reply

            client.request = request
            s.status = client.request("status")
            s.initial = client.request("observe")
            io = s.initial.get("observation") or {}
            if not (fresh.can_step and fresh.step_count == 0 and io.get("input_tick") == 0):
                raise RuntimeError(f"process not fresh at tick 0: {fresh} observe input_tick {io.get('input_tick')}")
            prev_mask = (s.initial.get("targets") or {}).get("remaining_mask")
            say(f"[m7g_capture] fresh process pid {episode.pid}, tick 0 ready; mode {mode}"
                f"{' realtime' if realtime else ''}; input {provider.name}")
            if prefix:
                say(f"[m7g_capture] replaying the {len(prefix)}-action prefix from tick 0 ...")
            pending_prefix = list(prefix)
            while True:
                if pending_prefix:
                    if provider.poll_quit():  # only quit is honoured during the prefix; nothing else is recorded
                        s.end_reason = "quit"
                        break
                    action = pending_prefix.pop(0)
                    s.prefix_replayed += 1
                    if not pending_prefix:  # hand-over: never start live play at game speed without notice
                        paused = True
                        s.pauses += 1
                        say(f"[m7g_capture] prefix replayed to tick {len(prefix)}; PAUSED (P = play, . = one tick)")
                else:
                    c = provider.poll()
                    if c.quit:
                        s.end_reason = "quit"
                        break
                    if c.disconnected:
                        if not paused:
                            paused = True
                            s.pauses += 1
                            say(f"[m7g_capture] input device disconnected at tick {len(s.seq)}: PAUSED (reconnect, "
                                "then Start to resume)")
                        time.sleep(poll_interval_s)
                        continue
                    if c.slower:
                        tick_ms = min(500.0, max(10.0, tick_ms * 1.5 if tick_ms else 20.0))
                    if c.faster:
                        tick_ms = 0.0 if tick_ms <= 10.0 else tick_ms / 1.5
                    if c.pause_toggle:
                        paused = not paused
                        s.pauses += int(paused)
                        say(f"[m7g_capture] {'PAUSED (. = one tick, P = resume)' if paused else 'resumed'} at tick "
                            f"{len(s.seq)}")
                    if paused and not c.advance:
                        time.sleep(poll_interval_s)
                        continue
                    if paused:
                        s.advances += 1
                    action = c.action
                if max_ticks is not None and len(s.seq) >= max_ticks:
                    s.end_reason = "max_ticks"
                    break
                t0 = time.perf_counter()
                b, x, y = fx.track1_to_native([action])[0]
                result = client.step(b, x, y)
                reply = s.replies[-1]
                i = len(s.seq)
                if result.consumed_tick != i or result.step_count != i + 1:
                    raise RuntimeError(f"tick misalignment at action {i}: consumed {result.consumed_tick} "
                                       f"step_count {result.step_count}")
                s.seq.append(action)
                o = reply.get("observation") or {}
                autosave.write(json.dumps({"i": i, "s": action[0], "b": action[1], "consumed_tick": i,
                                           "prefix": i < s.prefix_replayed, "x": o.get("position_x"),
                                           "y": o.get("position_y")}) + "\n")
                autosave.flush()
                if o.get("fighter_valid") == 1:
                    min_x = min(min_x, float(o["position_x"]))
                mask = (reply.get("targets") or {}).get("remaining_mask")
                if prev_mask is not None and mask is not None and mask != prev_mask:
                    say(f"[m7g_capture] tick {i}: target(s) {fx_ids(prev_mask & ~mask)} broken")
                prev_mask = mask
                if not left_announced and o.get("fighter_valid") == 1 and \
                        float(o["position_x"]) < geo.derived["left_boundary_x"]:
                    left_announced = True
                    say(f"[m7g_capture] tick {i}: NATIVE LEFT-OF-WALL ENTRY at x {o['position_x']:.1f} "
                        f"y {o['position_y']:.1f}")
                if not platform_announced and fx.classify_ground(geo, o) == "moving_platform":
                    platform_announced = True
                    say(f"[m7g_capture] tick {i}: standing on the moving platform (y {o['position_y']:.1f})")
                elapsed = (time.perf_counter() - t0) * 1000.0
                s.step_ms.append(elapsed)
                if i - last_hud >= hud_every or paused:
                    say(_hud(i, reply, min_x, elapsed, paused, geo))
                    last_hud = i
                if result.state == StepState.EPISODE_ENDED:
                    s.end_reason = "clear"
                    try:  # the recorded clear is kept even if the native exit/result handshake fails
                        done = episode.finish(result)
                        say(f"[m7g_capture] CLEAR at tick {i} (exit {done.exit_code})")
                    except Exception as exc:
                        s.end_reason = f"clear (finish failed: {type(exc).__name__}: {exc})"
                        say(f"[m7g_capture] CLEAR at tick {i}; native finish failed: {exc}")
                    break
                if fx.is_fall(reply):
                    s.end_reason = "native_failure"
                    say(f"[m7g_capture] fall (native failure) at tick {i}; the sequence ends with the falling tick")
                    break
                if not pending_prefix and tick_ms > 0:
                    wait = tick_ms / 1000.0 - (time.perf_counter() - t0)
                    if wait > 0:
                        time.sleep(wait)
    except KeyboardInterrupt:
        s.end_reason = "keyboard_interrupt"
    except Exception as exc:  # window closed, connection lost, misalignment...: keep what was recorded, then raise
        s.end_reason = f"error: {type(exc).__name__}: {exc}"
        error = exc
    finally:
        autosave.close()
    summary = finish_session(s, provider, mode=mode, realtime=realtime, resumed_from=resumed_from, started=started,
                             executable=executable, geo=geo, gameplay_cfg=gameplay_cfg)
    summary["user_config_unchanged"] = cfg_before.get("sha256") == file_fingerprint(USER_CONFIG).get("sha256")
    summary["cleanup"] = episode.cleanup_action
    write_json(out / "summary.json", summary)
    say(f"[m7g_capture] {len(s.seq)} actions ({s.prefix_replayed} replayed prefix), end: {s.end_reason}; "
        f"crossed: {summary['evidence']['crossed']}; draft -> {summary['draft']}")
    if error is not None:
        raise error
    return summary


def fx_ids(mask: int) -> List[int]:
    return [i for i in range(10) if mask & (1 << i)]


def finish_session(s: Session, provider: Any, *, mode: str, realtime: bool, resumed_from: Optional[Dict[str, Any]],
                   started: str, executable: Path, geo: fx.StageGeometry,
                   gameplay_cfg: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    from m7_runtime import portable_path, repository_revisions, sha256_file
    from m7g_crossing import write_gz, write_json

    out = s.out
    # A step reply is captured before its action is appended; an interrupt between the two must not leave a reply
    # without an action in the draft (the capture-vs-replay match would then fail forever).
    s.replies = s.replies[:len(s.seq)]
    trace = {"status": s.status, "initial": s.initial, "steps": s.replies, "mode": mode, "realtime": realtime}
    write_gz(out / "capture_trace.json.gz", trace)
    ms = sorted(s.step_ms)
    summary: Dict[str, Any] = {"actions": len(s.seq), "end_reason": s.end_reason, "prefix_replayed": s.prefix_replayed,
                               "pauses": s.pauses, "advances": s.advances,
                               "step_ms_median": round(ms[len(ms) // 2], 2) if ms else None}
    if not s.seq or s.initial is None:
        summary.update({"draft": None, "evidence": {"crossed": False}})
        return summary
    ev = fx.crossing_evidence(geo, s.initial, s.replies)
    cls = fx.classify_crossing(ev, geo)
    capture_info = {"trajectory_digest": fx.trajectory_digest(s.initial, s.replies),
                    "trajectory_digest_with_host_frame": fx.trajectory_digest(s.initial, s.replies,
                                                                              include_host_frame=True),
                    "targets_digest": fx.targets_digest(s.initial, s.replies),
                    "crossed": ev["crossed"], "first_left_entry": ev["first_left_entry"], "min_x": ev["min_x"],
                    "classification": cls, "end_reason": s.end_reason, "mode": mode, "realtime": realtime,
                    "executable_sha256": sha256_file(Path(executable)), "revisions": repository_revisions(),
                    "started_utc": started, "ended_utc": utc_stamp(), "prefix_replayed": s.prefix_replayed,
                    "pauses": s.pauses, "frame_advances": s.advances, "gameplay_config": gameplay_cfg}
    source = {"kind": fx.capture_source_kind(provider.name, resumed_from), "tool": TOOL, "input": provider.name,
              "resumed_from": resumed_from}
    if hasattr(provider, "keymap"):
        source["keymap"] = provider.keymap
    draft = fx.make_draft(s.seq, source, session={"capture": capture_info})
    write_json(out / "draft.json", draft)
    (out / "draft.txt").write_text(fx.format_script(s.seq, header=[
        f"captured {started} by {TOOL} ({provider.name}, {mode}{', realtime' if realtime else ''})",
        f"track1_digest {draft['sequence']['track1_digest']}", f"end {s.end_reason}; crossed {ev['crossed']}"]),
        encoding="utf-8", newline="\n")
    summary.update({"draft": portable_path(out / "draft.json"), "script": portable_path(out / "draft.txt"),
                    "track1_digest": draft["sequence"]["track1_digest"],
                    "native_action_digest": draft["sequence"]["native_action_digest"],
                    "trajectory_digest": capture_info["trajectory_digest"], "evidence": ev, "classification": cls})
    return summary


# -- CLI ---------------------------------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("play", help="live capture in a fresh visible process")
    p.add_argument("--label", default="capture")
    p.add_argument("--input", choices=("keyboard", "xinput"), default="keyboard")
    p.add_argument("--keymap", type=Path)
    p.add_argument("--mode", choices=("normal", "no_render", "no_render_raphnet"), default="normal",
                   help="host mode (a human needs 'normal', the visible window)")
    p.add_argument("--realtime", action="store_true",
                   help="SSB64_FREEZE_PACING=0: skip the parked idle present (about 60 instead of 30 ticks/s)")
    p.add_argument("--tick-ms", type=float, default=0.0, help="minimum wall time per tick (slow motion)")
    p.add_argument("--resume", type=Path, help="draft/fixture/script whose first --at actions are replayed first")
    p.add_argument("--at", type=int)
    p.add_argument("--max-ticks", type=int)
    p.add_argument("--out", type=Path)
    i = sub.add_parser("import", help="convert a sequence into a draft (exact Track 1 or rejected)")
    i.add_argument("source", type=Path)
    i.add_argument("--out", type=Path, required=True)
    i.add_argument("--note", default="")
    e = sub.add_parser("export-script", help="write the btt_track1_script_v1 text of a draft or fixture")
    e.add_argument("source", type=Path)
    e.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    if args.cmd in ("import", "export-script") and args.out is not None and args.out.exists():
        # never overwrite: --out naming a captured draft (or any existing file) would destroy the recording
        raise SystemExit(f"refusing to overwrite existing file {args.out}")
    out_arg = getattr(args, "out", None)
    if out_arg is not None and fx.recording_dir_of(out_arg.parent if args.cmd != "play" else out_arg) is not None:
        raise SystemExit(f"refusing to write {out_arg} inside the capture recording "
                         f"{fx.recording_dir_of(out_arg.parent if args.cmd != 'play' else out_arg)}")
    if args.cmd == "import":
        seq, meta = fx.load_sequence(args.source)
        from m7_runtime import portable_path

        origin = {k: v for k, v in meta.items() if k not in ("document", "capture_header")}
        origin["path"] = portable_path(args.source)
        draft = fx.make_draft(seq, {"kind": "imported", "tool": TOOL, "imported_from": origin, "note": args.note})
        from m7g_crossing import write_json

        write_json(args.out, draft)
        print(json.dumps({"draft": str(args.out), "length": len(seq), **{k: draft["sequence"][k] for k in
                                                                         ("track1_digest", "native_action_digest")}},
                         indent=1))
        return 0
    if args.cmd == "export-script":
        seq, _meta = fx.load_sequence(args.source)
        text = fx.format_script(seq, header=[f"exported from {args.source}"])
        if args.out:
            args.out.write_text(text, encoding="utf-8", newline="\n")
        else:
            sys.stdout.write(text)
        return 0
    from m7_runtime import install_kill_on_close_job, list_processes_named

    install_kill_on_close_job()
    leaked = sorted(k for k in os.environ if k.upper().startswith("SSB64_"))
    if leaked:
        raise SystemExit(f"SSB64_* variables in the environment would leak into the child: {leaked}")
    if list_processes_named():
        raise SystemExit(f"close the running BattleShip processes first: {list_processes_named()}")
    if (args.resume is None) != (args.at is None):
        ap.error("--resume and --at go together")
    keymap = json.loads(fx.read_text_file(args.keymap)) if args.keymap else None
    provider = KeyboardInput(keymap) if args.input == "keyboard" else XInputInput()
    out = args.out or CAPTURE_ROOT / f"{utc_stamp()}_{args.label}"
    print(__doc__.split("Usage:")[0])
    print(f"[m7g_capture] output: {out}\n[m7g_capture] keep focus on this console; Ctrl+Q saves and quits")
    summary = capture(provider, out, mode=args.mode, realtime=args.realtime,
                      resume=(args.resume, args.at) if args.resume else None, max_ticks=args.max_ticks,
                      tick_ms=args.tick_ms)
    print(json.dumps({k: summary.get(k) for k in ("actions", "end_reason", "draft", "script", "track1_digest",
                                                  "classification", "user_config_unchanged")}, indent=1))
    if summary.get("draft"):
        kind = json.loads((REPO_ROOT / summary["draft"]).read_text(encoding="utf-8"))["source"]["kind"]
        print(f"next: python rl/m7g_crossing.py build {summary['draft']} "
              f"--crossing lower_precision|upper_moving_platform --source {kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
