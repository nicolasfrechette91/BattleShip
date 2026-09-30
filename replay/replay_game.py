#!/usr/bin/env python3
"""BattleShip process and replay engine for the replay viewer.

One replay = one fresh BattleShip process at native tick 0, the same reset
training uses (rl/battleship_process.py: new process, WaitingForAction,
step_count 0). Rows of actions.jsonl are submitted one per native tick
through the frozen protocol-1 loopback transport (rl/battleship_client.py).
Restarting or jumping backwards launches a new process; there is no
in-process reset and no save state.

Launch settings (all existing, opt-in native knobs; no native change):

    SSB64_RL_BTT=1 SSB64_RL_STEP=1 SSB64_RL_PORT=<OS ephemeral port>
    SSB64_SAVE_PATH / SSB64_RL_RESULT_PATH   private per launch
    SSB64_RAPHNET_DISABLE=1                  process-local, as in training
    windowed:  SSB64_FREEZE_PACING=0 + OpenGL backend in the PRIVATE config
               -> one paced present per tick (60 ticks/s cap), no DXGI frame drops
    --check:   SSB64_RL_NO_RENDER=1 (training's headless host mode)

SSB64_RL_EXIT_ON_END is deliberately NOT set: after a clear the window stays
open on the final frame. Every other inherited SSB64_* variable is stripped
from the child environment.

The process runs with cwd = a private runtime directory made by
rl/m7_runtime.prepare_worker_runtime under replay/_local/sessions/, so the
user's build-us/Release/BattleShip.cfg.json, imgui.ini and logs are never
written. The configuration copy is the episode's recorded runtime config when
it still exists (else the executable directory's), with only Window.* changed.

Windows only in practice (BattleShip RL tooling is Windows-first); nothing is
written below runs/.
"""

from __future__ import annotations

import collections
import datetime as _dt
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

import replay_win32 as win32
from replay_episode import (REPO_ROOT, Episode, ReplayTracker, Row, Verdict, compare, format_verdict)
from replay_history import FrameHistory, HistoryConfig, SavedFrame, bgrx_to_rgb

from battleship_client import BattleShipClient, BattleShipError, ConnectionClosed, StepState  # noqa: E402
from battleship_process import allocate_loopback_port  # noqa: E402
from m7_runtime import pid_alive, prepare_worker_runtime, remove_worker_runtime  # noqa: E402
from m7g_fixture import gameplay_config  # noqa: E402

DEFAULT_EXE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
LOCAL_DIR = REPO_ROOT / "replay" / "_local"
SESSIONS_DIR = LOCAL_DIR / "sessions"
VERDICTS_FILE = LOCAL_DIR / "verdicts.jsonl"
STATE_FILE = LOCAL_DIR / "viewer_state.json"
CONFIG_NAME = "BattleShip.cfg.json"
OPENGL_BACKEND = {"Id": 1, "Name": "OpenGL"}  # libultraship WindowBackend::FAST3D_SDL_OPENGL
NATIVE_TICK_S = 1.0 / 60.0
CAPTURE_SETTLE_S = 0.002  # see CaptureWorker
# After a gap (the previous tick's copy was dropped or never taken) a stale read cannot be recognized by comparing
# with that copy, so the read waits past every stale window seen (all ended within the 2 ms settle; 0 stale reads in
# 2,161 audited 1x ticks) with 3x margin, and still ends near 11 ms, inside CAPTURE_SAFE_S.
CAPTURE_SETTLE_UNVERIFIED_S = 0.006
CAPTURE_STALE_RETRIES = 4  # a stale copy was always fresh on the first retry (measured)
# Frame k stays on screen until >= ~16.3 ms after its step reply (vsync'ed, paced presents). Measured against
# slow-stepped reference frames: every 1x copy read within 25 ms was correct, every copy read after 30 ms wrong.
CAPTURE_SAFE_S = 0.016
CAPTURE_READ_S = 0.006  # a window read takes ~5 ms (960x720)
SPEEDS = (0.25, 0.5, 1.0, 2.0, 4.0)
MAX_RENDERED_SPEED = 1.0  # the port paces every rendered present to >= 1/60 s (see README)


class ReplayRuntimeError(RuntimeError):
    """BattleShip could not be launched or stopped answering."""


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def repo_relative(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# -- viewer state (window geometry) -----------------------------------------------------------------


def load_state() -> Dict[str, Any]:
    try:
        with open(STATE_FILE, encoding="utf-8") as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(update: Dict[str, Any]) -> None:
    state = load_state()
    state.update(update)
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fp:
        json.dump(state, fp, indent=2)
    os.replace(tmp, STATE_FILE)


# -- sessions ------------------------------------------------------------------------------------------


def cleanup_stale_sessions() -> List[str]:
    """Remove session directories whose viewer process is gone (a crashed or killed viewer)."""
    removed = []
    if not SESSIONS_DIR.is_dir():
        return removed
    for d in SESSIONS_DIR.iterdir():
        if not d.is_dir():
            continue
        try:
            owner = json.loads((d / "session.json").read_text(encoding="utf-8")).get("viewer_pid")
        except (OSError, ValueError):
            owner = None
        if owner is None:  # session.json not written yet (a session being created) or unreadable: the name has the pid
            m = re.match(r"\d{8}T\d{6}Z_(\d+)_", d.name)
            owner = int(m.group(1)) if m else None
        if owner is not None and pid_alive(int(owner)):
            continue
        try:
            remove_session_dir(d)
            removed.append(d.name)
        except OSError:
            pass
    return removed


def remove_session_dir(d: Path) -> None:
    rt = d / "rt"
    if rt.exists():
        deadline = time.monotonic() + 15.0
        while True:
            try:
                remove_worker_runtime(rt)  # junction first, never its target
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)
    shutil.rmtree(d, ignore_errors=True)


def new_session_dir(episode_id: str, tag: str = "") -> Path:
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    d = SESSIONS_DIR / f"{stamp}_{os.getpid()}_{episode_id[-8:]}{'_' + tag if tag else ''}"
    d.mkdir(parents=True)
    with open(d / "session.json", "w", encoding="utf-8", newline="\n") as fp:
        json.dump({"viewer_pid": os.getpid(), "episode_id": episode_id, "created_utc": utc_now()}, fp, indent=2)
    return d


# -- configuration -------------------------------------------------------------------------------------


def recorded_runtime_config(ep: Episode) -> Optional[Path]:
    """The private config copy the recorded episode's process ran with, if it still exists (read-only)."""
    startup = ep.labels.get("startup")
    rt = startup.get("runtime_dir") if isinstance(startup, dict) else None
    if not rt:
        return None
    p = Path(rt)
    if not p.is_absolute():
        p = REPO_ROOT / p
    p = p / CONFIG_NAME
    return p if p.is_file() else None


@dataclass
class Geometry:
    width: int = 960
    height: int = 720
    x: Optional[int] = None
    y: Optional[int] = None


def write_runtime_config(runtime_dir: Path, base: Path, *, headless: bool, geometry: Geometry) -> Dict[str, Any]:
    """Private config = base config with only Window.* changed (backend, size, position)."""
    doc = json.loads(Path(base).read_bytes().decode("utf-8-sig"))
    if not headless:
        window = doc.setdefault("Window", {})
        window["Backend"] = dict(OPENGL_BACKEND)
        window["Width"] = int(geometry.width)
        window["Height"] = int(geometry.height)
        if geometry.x is not None and geometry.y is not None:
            window["PositionX"] = int(geometry.x)
            window["PositionY"] = int(geometry.y)
        window.setdefault("Fullscreen", {})["Enabled"] = False
    target = runtime_dir / CONFIG_NAME
    with open(target, "w", encoding="utf-8", newline="\n") as fp:
        json.dump(doc, fp, indent=4)
    return {"base": repo_relative(base), "gameplay": gameplay_config(target)["effective_gameplay_cvars"]}


# -- one BattleShip process ----------------------------------------------------------------------------


class GameProcess:
    """Launches (and relaunches) BattleShip for one viewer session. Not thread-safe."""

    def __init__(self, executable: Path, session_dir: Path, *, headless: bool, base_config: Path,
                 geometry: Optional[Geometry] = None, request_timeout: float = 15.0):
        self.executable = Path(executable).resolve()
        self.session_dir = session_dir
        self.headless = headless
        self.base_config = base_config
        self.geometry = geometry or Geometry()
        self.request_timeout = request_timeout
        self.runtime_dir = session_dir / "rt"
        self.process: Optional[subprocess.Popen] = None
        self.client: Optional[BattleShipClient] = None
        self.port: Optional[int] = None
        self.launches = 0
        self.stripped_env: List[str] = []
        self.config_info: Dict[str, Any] = {}
        self.hwnd: Optional[int] = None

    @property
    def pid(self) -> Optional[int]:
        return self.process.pid if self.process is not None else None

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _env(self, launch_dir: Path) -> Dict[str, str]:
        env = {}
        self.stripped_env = []
        for k, v in os.environ.items():
            if k.upper().startswith("SSB64_"):
                self.stripped_env.append(k)
            else:
                env[k] = v
        env.update({
            "SSB64_RL_BTT": "1",
            "SSB64_RL_STEP": "1",
            "SSB64_RL_PORT": str(self.port),
            "SSB64_SAVE_PATH": str(launch_dir / "ssb64_save.bin"),
            "SSB64_RL_RESULT_PATH": str(launch_dir / "result.json"),
            "SSB64_RAPHNET_DISABLE": "1",
        })
        if self.headless:
            env["SSB64_RL_NO_RENDER"] = "1"
        else:
            env["SSB64_FREEZE_PACING"] = "0"
        return env

    def launch(self, *, startup_timeout: float = 60.0, ready_timeout: float = 120.0) -> Dict[str, Any]:
        """Start a new process and wait for the fresh tick-0 state. Returns the tick-0 observation."""
        self.close()
        if not self.runtime_dir.exists():
            prepare_worker_runtime(self.runtime_dir, self.executable)
        self.config_info = write_runtime_config(self.runtime_dir, self.base_config, headless=self.headless,
                                                geometry=self.geometry)
        self.launches += 1
        launch_dir = self.session_dir / f"launch_{self.launches:03d}"
        launch_dir.mkdir()
        self.port = allocate_loopback_port()
        env = self._env(launch_dir)
        self.process = subprocess.Popen([str(self.executable)], cwd=str(self.runtime_dir), env=env,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
        self.hwnd = None
        client = BattleShipClient(port=self.port, timeout=self.request_timeout)
        deadline = time.monotonic() + startup_timeout
        while True:
            if self.process.poll() is not None:
                raise ReplayRuntimeError(f"BattleShip exited with code {self.process.returncode} during startup")
            try:
                client.connect()
                break
            except ConnectionClosed:
                if time.monotonic() >= deadline:
                    raise ReplayRuntimeError(f"transport 127.0.0.1:{self.port} not reachable after {startup_timeout:g} s")
                time.sleep(0.05)
        self.client = client
        deadline = time.monotonic() + ready_timeout
        while True:
            st = client.status()
            if st.state == StepState.WAITING_FOR_ACTION and st.can_step and st.step_count == 0:
                break
            if st.state != StepState.INACTIVE:
                raise ReplayRuntimeError(f"not a fresh episode: state {st.state_name} step_count {st.step_count}")
            if self.process.poll() is not None:
                raise ReplayRuntimeError(f"BattleShip exited with code {self.process.returncode} while booting")
            if time.monotonic() >= deadline:
                raise ReplayRuntimeError(f"still {st.state_name} after {ready_timeout:g} s")
            time.sleep(0.05)
        obs = client.observe()
        if obs.step_count != 0 or obs.observation.input_tick != 0:
            raise ReplayRuntimeError(f"tick-0 observe is not fresh: step_count {obs.step_count} "
                                     f"input_tick {obs.observation.input_tick}")
        return asdict(obs.observation)

    def step(self, row: Row) -> Tuple[str, int, int, Dict[str, Any]]:
        assert self.client is not None
        try:
            r = self.client.step(row.buttons, row.stick_x, row.stick_y)
        except BattleShipError as exc:
            if self.process is not None:
                try:
                    self.process.wait(2.0)  # a closed game window shuts down within moments
                except subprocess.TimeoutExpired:
                    pass
            code = self.process.poll() if self.process is not None else None
            if code is not None or getattr(exc, "error", None) == "stopping":
                raise ReplayRuntimeError(
                    f"BattleShip stopped while replaying tick {row.sequence_index} (was its window closed?); "
                    f"press Restart or reopen the episode. [{exc}]") from exc
            raise ReplayRuntimeError(f"step {row.sequence_index} failed: {exc}") from exc
        return r.state_name, r.step_count, r.consumed_tick, asdict(r.observation)

    def window(self) -> Optional[int]:
        if self.headless or not self.alive:
            return None
        if not win32.is_window(self.hwnd):
            self.hwnd = win32.find_process_window(self.pid)
        return self.hwnd

    def remember_geometry(self) -> None:
        """Keep the game window where the user put it across restarts."""
        rect = win32.client_rect_on_screen(self.window())
        if rect and not win32.is_minimized(self.hwnd) and rect[2] >= 160 and rect[3] >= 120:
            self.geometry = Geometry(width=rect[2], height=rect[3], x=rect[0], y=rect[1])
            save_state({"game_window": asdict(self.geometry)})

    def set_idle(self, idle: bool) -> None:
        if not self.headless and self.alive:
            win32.set_priority(self.pid, idle)

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None
        p, self.process = self.process, None
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    pass
        self.hwnd = None


# -- verdict log ---------------------------------------------------------------------------------------


def record_verdict(ep: Episode, tracker: ReplayTracker, verdict: Verdict, *, mode: str,
                   exe: Dict[str, Any]) -> None:
    """Append one line to replay/_local/verdicts.jsonl (read by replay_index.py)."""
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    line = {
        "utc": utc_now(),
        "episode_dir": repo_relative(ep.directory),
        "episode_id": ep.episode_id,
        "verdict": verdict.word,
        "mode": mode,
        "steps": tracker.steps,
        "end": tracker.end_kind,
        "targets_broken": tracker.targets_broken,
        "failures": [f"{c.name}: expected {c.expected}, got {c.got}" for c in verdict.failures()],
        "trajectory": tracker.trajectory.as_dict(),
        "executable": exe,
    }
    with open(VERDICTS_FILE, "a", encoding="utf-8", newline="\n") as fp:
        fp.write(json.dumps(line, separators=(",", ":")) + "\n")


def executable_identity(exe: Path) -> Dict[str, Any]:
    st = exe.stat()
    return {"path": repo_relative(exe), "size": st.st_size, "sha256": sha256_file(exe)}


# -- headless check --------------------------------------------------------------------------------------


def check_episode(ep: Episode, *, executable: Path = DEFAULT_EXE, keep_session: bool = False,
                  log: Callable[[str], None] = print, cleanup: bool = True, session_tag: str = "",
                  on_game: Optional[Callable[["GameProcess"], None]] = None,
                  on_step: Optional[Callable[[Row, ReplayTracker], None]] = None) -> Tuple[Verdict, ReplayTracker]:
    """Replay every row in a no-render process as fast as possible and compare with metadata.json.

    on_game(game) runs before the launch, on_step(row, tracker) after every step (TargetPrepass: markers and
    cancellation). cleanup=False leaves stale-session removal to the caller that owns the viewer."""
    if cleanup:
        cleanup_stale_sessions()
    session = new_session_dir(ep.episode_id, session_tag)
    base = recorded_runtime_config(ep) or (executable.resolve().parent / CONFIG_NAME)
    game = GameProcess(executable, session, headless=True, base_config=base)
    tracker = ReplayTracker(ep)
    rows = ep.replay_rows
    try:
        if on_game is not None:
            on_game(game)
        t0 = time.monotonic()
        tracker.feed_initial(game.launch())
        log(f"launched pid {game.pid} (headless, config base {game.config_info['base']}, "
            f"gameplay {game.config_info['gameplay']}) in {time.monotonic() - t0:.1f} s")
        if game.stripped_env:
            log(f"note: stripped inherited {', '.join(sorted(game.stripped_env))} from the child environment")
        t0 = time.monotonic()
        for row in rows:
            tracker.feed_step(row, *game.step(row))
            if on_step is not None:
                on_step(row, tracker)
            if tracker.ended:
                break
        log(f"stepped {tracker.steps} rows in {time.monotonic() - t0:.1f} s")
    finally:
        game.close()
        if not keep_session:
            remove_session_dir(session)
    return compare(tracker), tracker


class _Cancelled(Exception):
    pass


class TargetPrepass(threading.Thread):
    """Timeline markers: the ticks where targets break, from a headless replay started at load.

    The same no-render replay as --check, in its own fresh process (IDLE priority, own session directory), so the
    viewer window opens at once and the windowed game is never touched. The ticks describe this replay, which is
    what the viewer will show; nothing is compared or recorded here.
    """

    def __init__(self, ep: Episode, *, executable: Path = DEFAULT_EXE):
        super().__init__(name="target-prepass", daemon=True)
        self.ep = ep
        self.executable = Path(executable)
        self.state = "running"  # running | done | failed | cancelled
        self.break_ticks: List[int] = []  # the row of each break (repeated when several break on one tick)
        self.error: Optional[str] = None
        self.seconds: Optional[float] = None
        self._cancel = threading.Event()
        self._game: Optional[GameProcess] = None
        self._broken: Optional[int] = None

    def cancel(self) -> None:
        self._cancel.set()
        game = self._game
        process = game.process if game is not None else None
        if process is not None and process.poll() is None:
            process.terminate()  # a pending launch or step fails at once; check_episode then cleans up

    def _on_game(self, game: GameProcess) -> None:
        self._game = game
        if self._cancel.is_set():
            raise _Cancelled()

    def _on_step(self, row: Row, tracker: ReplayTracker) -> None:
        if self._cancel.is_set():
            raise _Cancelled()
        if self._broken is None:  # first step: the tick-0 count, and keep the pre-pass out of the playback's way
            win32.set_priority(self._game.pid if self._game else None, True)
            init = tracker.initial or {}
            self._broken = self.ep.targets_total - int(init.get("targets_remaining", self.ep.targets_total))
        broken = tracker.targets_broken or 0
        if broken > self._broken:
            self.break_ticks.extend([row.sequence_index] * (broken - self._broken))
        self._broken = broken

    def run(self) -> None:
        t0 = time.monotonic()
        try:
            check_episode(self.ep, executable=self.executable, log=lambda _msg: None, cleanup=False,
                          session_tag="markers", on_game=self._on_game, on_step=self._on_step)
            self.state = "done"
        except Exception as exc:  # noqa: BLE001 - markers are optional; the viewer shows why they are missing
            if self._cancel.is_set():
                self.state = "cancelled"
            else:
                self.error = f"{type(exc).__name__}: {exc}"
                self.state = "failed"
        finally:
            self.seconds = time.monotonic() - t0


# -- saved-frame capture -------------------------------------------------------------------------------------


class CaptureWorker(threading.Thread):
    """Copies game frames into the history off the stepping thread.

    Timing argument: the step reply of tick k arrives after the game presented frame k, and the port paces
    presents at least 1/60 s apart (libultraship SyncFramerateWithTime), so frame k stays on the window for at
    least ~16.3 ms after the reply even though the stepping thread submits tick k+1 at once. The copy waits
    CAPTURE_SETTLE_S (an immediate copy was the previous tick's image on ~2-3 % of 1x ticks: SwapBuffers returns
    before the new frame is visible), reads the window (~5 ms), re-reads if the copy still equals the previous
    tick's, and downscales afterwards. When there is no copy of the previous tick to compare with (after a dropped
    copy or a gap), it waits CAPTURE_SETTLE_UNVERIFIED_S instead, past any stale window. A copy is stored only if its
    read finished within CAPTURE_SAFE_S of the reply, or before tick k+1 was submitted at all; anything later could
    show tick k+1 and is dropped (counted in engine.late_drops), never stored under the wrong tick. The port's pacer
    (libultraship gfx_sdl2.cpp SyncFramerateWithTime) re-bases on the actual present time, so a late frame k is
    never followed early by frame k+1.
    """

    def __init__(self, engine: "ReplayEngine"):
        super().__init__(name="replay-capture", daemon=True)
        self.engine = engine
        self.jobs: "queue.Queue[Any]" = queue.Queue()
        self._last: Optional[Tuple[int, bytes]] = None  # (tick, BGRX) of the previous copy

    def submit(self, job: Tuple[int, Optional[Row], Dict[str, Any], Optional[int], int, float]) -> None:
        self.jobs.put(job)

    def reset(self) -> None:
        """A new process: the previous copy is no longer the previous tick of this one."""
        self.jobs.put("reset")

    def stop(self) -> None:
        self.jobs.put(None)
        self.join(5.0)

    def run(self) -> None:
        win32.raise_current_thread_priority()  # the read must land inside the frame's on-screen window
        capturer = win32.WindowCapturer(win32.COLORONCOLOR if self.engine.history_config.filter == "nearest"
                                        else win32.HALFTONE)
        try:
            while True:
                job = self.jobs.get()
                if job is None:
                    return
                if job == "reset":
                    self._last = None
                    continue
                try:
                    self._copy(capturer, *job)
                except OSError:
                    self._last = None
        finally:
            capturer.close()

    def _copy(self, capturer: win32.WindowCapturer, tick: int, row: Optional[Row], obs: Dict[str, Any],
              targets: Optional[int], hwnd: int, t_ready: float) -> None:
        e = self.engine
        scale = e.history_config.scale
        prev = self._last
        verified = prev is not None and prev[0] == tick - 1  # the previous tick's copy exists: stale reads show
        settle = CAPTURE_SETTLE_S if verified else CAPTURE_SETTLE_UNVERIFIED_S
        wait = t_ready + settle - time.perf_counter()
        if wait > 0:
            time.sleep(wait)
        elif e._last_submit[0] > tick and -wait > CAPTURE_SAFE_S - settle - CAPTURE_READ_S:
            # Behind (a hiccup queued several frames): this read could not finish in time; skip it at once so the
            # following frames are caught again instead of every queued one arriving late.
            e.late_drops += 1
            self._last = None
            return
        shot = capturer.capture(hwnd, scale)
        if shot is not None and verified and shot[2] == prev[1]:
            e.stale_retries += 1
            for _ in range(CAPTURE_STALE_RETRIES):
                time.sleep(0.001)
                again = capturer.capture(hwnd, scale)
                if again is not None and again[2] != prev[1]:
                    shot = again
                    break
        if shot is None:
            self._last = None
            return
        t_read = capturer.last_read_time  # the window pixels were read by then; downscaling came after
        next_tick, next_submitted = e._last_submit
        if next_tick > tick and next_submitted < t_read and t_read - t_ready > CAPTURE_SAFE_S:
            e.late_drops += 1  # tick k+1 may already be on screen: never store a doubtful image
            self._last = None
            return
        width, height, bgrx = shot
        self._last = (tick, bgrx)
        e.history.put(SavedFrame(tick, width, height, bgrx_to_rgb(bgrx), row, obs, targets))
        e.capture_ms.append((t_read - t_ready) * 1000.0)


# -- interactive engine --------------------------------------------------------------------------------


class ReplayEngine(threading.Thread):
    """Owns the game process and the replay cursor; driven by commands from the UI thread.

    Commands: play, pause, toggle, step, speed(v), restart, jump(tick), quit.
    `jump(N)` stops with native tick N consumed (the frame on screen is the
    post-update of tick N); a target behind the cursor restarts the process
    and fast-forwards from tick 0 ("rebuilding"). Fast-forward and playback
    share the port's rendered-present cap of 60 ticks/s (see README: >1x needs
    a native change).

    With a history, the frame of every tick shown (and of the last
    `history.capacity` ticks of a fast-forward) is copied from the game window
    right after the tick returns, together with that tick's HUD data; the UI
    shows stored frames for instant steps back (replay_history.py).
    """

    def __init__(self, ep: Episode, *, executable: Path = DEFAULT_EXE, speed: float = 1.0, play: bool = False,
                 start_tick: Optional[int] = None, geometry: Optional[Geometry] = None, keep_session: bool = False,
                 log: Callable[[str], None] = print, on_end: Optional[Callable[[Verdict], None]] = None,
                 history: Optional[HistoryConfig] = None):
        super().__init__(name="replay-engine", daemon=True)
        self.ep = ep
        self.rows = ep.replay_rows
        self.executable = Path(executable)
        self.keep_session = keep_session
        self.log = log
        self.on_end = on_end
        self.history_config = history if history is not None else HistoryConfig()
        self.history: Optional[FrameHistory] = (FrameHistory(self.history_config.frames)
                                                if self.history_config.enabled else None)
        self._worker: Optional[CaptureWorker] = None  # started in run() when the history is on
        self._last_submit: Tuple[int, float] = (-2, 0.0)  # (row, perf_counter) of the latest step request
        self.stale_retries = 0
        self.late_drops = 0
        self._rebuilding = False
        self._rebuild_to: Optional[int] = None  # tick being rebuilt to (shown while the fresh process boots)
        self.capture_ms: Deque[float] = collections.deque(maxlen=120)
        self.commands: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        self._lock = threading.Lock()
        self._speed = float(speed)
        self._playing = bool(play)
        self._jump_to: Optional[int] = None  # cursor target (rows consumed)
        self._initial_jump = start_tick
        self._geometry = geometry
        self.cursor = 0
        self.tracker = ReplayTracker(ep)
        self.verdict: Optional[Verdict] = None
        self.game: Optional[GameProcess] = None
        self.phase = "booting"
        self.message = ""
        self.error: Optional[str] = None
        self.exe_identity: Dict[str, Any] = {}
        self._times: Deque[float] = collections.deque(maxlen=31)
        self._next_due: Optional[float] = None
        self._last_row: Optional[Row] = None
        self._quit = False
        self._mismatch_logged = False
        self.finished = threading.Event()

    # -- UI side ------------------------------------------------------------------------------------------

    def send(self, command: str, value: Any = None) -> None:
        self.commands.put((command, value))

    @property
    def speed(self) -> float:
        return self._speed

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            obs = self.tracker.last or self.tracker.initial or {}
            return {
                "phase": self.phase,
                "cursor": self.cursor,
                "rows": len(self.rows),
                "last_row": self._last_row,
                "observation": dict(obs),
                "targets_broken": self.tracker.targets_broken,
                "targets_total": self.ep.targets_total,
                "speed": self._speed,
                "achieved_tps": self._achieved_tps(),
                "jump_to": self._jump_to,
                "message": self.message,
                "error": self.error,
                "end_kind": self.tracker.end_kind,
                "verdict": self.verdict.word if self.verdict else None,
                "verdict_lines": self.verdict.lines() if self.verdict else [],
                "verdict_detail": self.verdict,  # the Verdict (immutable once set): every check, for the result view
                "mismatch": self.tracker.first_mismatch,
                "pid": self.game.pid if self.game else None,
                "hwnd": self.game.hwnd if self.game else None,
                "live_tick": self.cursor - 1,  # -1 = tick-0 state
                "rebuilding": self._rebuilding,
                "rebuild_to": self._rebuild_to,
            }

    def game_window(self) -> Optional[int]:
        game = self.game
        return game.window() if game is not None else None

    # -- engine thread ------------------------------------------------------------------------------------

    def _achieved_tps(self) -> Optional[float]:
        if len(self._times) < 5 or time.perf_counter() - self._times[-1] > 0.25:
            return None
        return (len(self._times) - 1) / (self._times[-1] - self._times[0])

    def _set(self, **kw: Any) -> None:
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def run(self) -> None:
        session = None
        try:
            cleanup_stale_sessions()
            session = new_session_dir(self.ep.episode_id)
            self.exe_identity = executable_identity(self.executable)
            base = recorded_runtime_config(self.ep) or (self.executable.resolve().parent / CONFIG_NAME)
            self.game = GameProcess(self.executable, session, headless=False, base_config=base,
                                    geometry=self._geometry)
            if self.history is not None:
                self._worker = CaptureWorker(self)
                self._worker.start()
                # Three busy threads (stepping, capture, Tk): with CPython's default 5 ms GIL switch interval the
                # stepping thread could wait past a 16.7 ms tick (measured: 56 instead of 60 ticks/s).
                sys.setswitchinterval(0.001)
            self._launch()
            info = self.game.config_info
            self.log(f"config base {info['base']}; gameplay settings {info['gameplay']}")
            if self.game.stripped_env:
                self.log(f"note: stripped inherited {', '.join(sorted(self.game.stripped_env))} from the child env")
            if self._initial_jump is not None:
                self._request_jump(int(self._initial_jump))
            self._loop()
        except Exception as exc:  # noqa: BLE001 - reported to the UI and the console
            self._set(error=f"{type(exc).__name__}: {exc}", phase="error")
            self.log(f"ERROR: {type(exc).__name__}: {exc}")
        finally:
            if self._worker is not None:
                self._worker.stop()
            if self.game is not None:
                self.game.remember_geometry()
                self.game.close()
            if session is not None and not self.keep_session:
                try:
                    remove_session_dir(session)
                except OSError as exc:
                    self.log(f"note: could not remove {session}: {exc}")
            self.finished.set()

    def _launch(self) -> None:
        assert self.game is not None
        self._set(phase="booting", message="starting BattleShip (fresh process, tick 0)")
        if self.game.launches:
            self.game.remember_geometry()
        tracker = ReplayTracker(self.ep)
        t0 = time.monotonic()
        self._last_submit = (-2, 0.0)
        if self._worker is not None:
            self._worker.reset()
        tracker.feed_initial(self.game.launch())
        with self._lock:
            self.tracker = tracker
            self._mismatch_logged = False
            self.cursor = 0
            self.verdict = None
            self._last_row = None
            self._times.clear()
            self._next_due = None
            self.error = None
            self.message = f"fresh process pid {self.game.pid} ready in {time.monotonic() - t0:.1f} s"
        self._update_phase()
        self._capture(-1, None)  # the tick-0 state

    def _update_phase(self) -> None:
        with self._lock:
            if self._jump_to is None:  # no pending jump: nothing is being rebuilt (_request_jump re-sets it)
                self._rebuilding = False
                self._rebuild_to = None
            if self.error:
                self.phase = "error"
            elif self.tracker.ended:
                self.phase = "ended"
            elif self._jump_to is not None:
                self.phase = "jumping"
            else:
                self.phase = "playing" if self._playing else "paused"
            busy = self.phase in ("playing", "jumping")
        if self.game is not None:
            self.game.set_idle(not busy)

    def _loop(self) -> None:
        """Serve commands until quit. A BattleShip failure (e.g. its window was closed) is not fatal: the engine
        stays in phase "error" and Restart or Jump launches a fresh process."""
        while not self._quit:
            try:
                self._iteration()
            except ReplayRuntimeError as exc:
                self._set(error=str(exc), _playing=False, _jump_to=None, _rebuilding=False, message="")
                self._update_phase()
                self.log(f"ERROR: {exc}")

    def _iteration(self) -> None:
        """One pass of the engine loop: a jump step, a paced play step, or waiting for a command."""
        with self._lock:
            jumping = self._jump_to is not None
            playing = self._playing and not self.tracker.ended and not self.error
        if jumping:
            self._drain_commands(block=False)
            if self._jump_to is not None and not self._quit:
                if self.cursor >= self._jump_to or self.tracker.ended:
                    self._set(_jump_to=None, _playing=False, _rebuilding=False, message="")  # the tick is shown
                    self._update_phase()
                else:
                    self._step_one(paced=False)
            return
        if not playing:
            self._drain_commands(block=True, timeout=0.5)
            return
        # Below 1x Python spaces the steps; at >= 1x it submits as soon as the previous tick returns and the
        # port's present pacing sets the rate (60 ticks/s).
        period = NATIVE_TICK_S / self._speed if self._speed < MAX_RENDERED_SPEED else 0.0
        now = time.perf_counter()
        if self._next_due is None or now - self._next_due > max(period, NATIVE_TICK_S):
            self._next_due = now
        wait = self._next_due - now
        if wait > 0.0005:
            # time.sleep is high-resolution on Windows (CPython >= 3.11); a queue timeout is not.
            time.sleep(min(wait, 0.02))
            self._drain_commands(block=False)
            return
        self._drain_commands(block=False)
        with self._lock:
            still = self._playing and self._jump_to is None and not self.tracker.ended and not self.error
        if self._next_due is None:  # a command (speed, play) reset the schedule: re-evaluate
            return
        if still and not self._quit:
            self._next_due += period
            self._step_one(paced=True)

    def _drain_commands(self, *, block: bool, timeout: float = 0.0) -> None:
        try:
            cmd = self.commands.get(block=block, timeout=timeout if block else None)
        except queue.Empty:
            return
        while True:
            self._handle_command(*cmd)
            try:
                cmd = self.commands.get_nowait()
            except queue.Empty:
                return

    def _handle_command(self, command: str, value: Any) -> None:
        ended = self.tracker.ended
        if command == "quit":
            self._quit = True
        elif self.error and command in ("play", "toggle", "step"):
            self._set(message="BattleShip is not running: press Restart (or Jump) to launch a fresh process")
        elif command in ("play", "pause", "toggle"):
            playing = {"play": True, "pause": False}.get(command, not self._playing)
            if playing and ended:
                self._set(message="episode ended: restart or jump back")
                playing = False
            self._set(_playing=playing, _jump_to=None)
            self._next_due = None
            self._update_phase()
        elif command == "step":
            self._set(_playing=False, _jump_to=None)
            self._update_phase()
            if ended:
                self._set(message="episode ended: restart or jump back")
            else:
                self.game.set_idle(False)
                self._step_one(paced=False)
                self._update_phase()
        elif command == "speed":
            v = float(value)
            msg = f"speed {v:g}x"
            if v > MAX_RENDERED_SPEED:
                msg += " requested; rendered playback is capped at 1x (60 ticks/s) by the port's present pacing"
            self._set(_speed=v, message=msg)
            self._next_due = None
        elif command == "restart":
            playing = self._playing
            self._set(_jump_to=None)
            self._launch()
            self._set(_playing=playing)
            self._update_phase()
        elif command == "jump":
            self._request_jump(int(value))

    def _request_jump(self, tick: int) -> None:
        """Show tick N (rows 0..N consumed); N = -1 is the tick-0 state. Behind the cursor this is a rebuild:
        a fresh process fast-forwarded to N."""
        n = len(self.rows)
        target = max(0, min(int(tick) + 1, n))  # rows consumed after the jump
        rebuild = target < self.cursor or (self.tracker.ended and target != self.cursor) or bool(self.error)
        # The target is registered before a relaunch, so the phase goes booting -> jumping without ever looking
        # like "paused at the tick-0 state" in between.
        self._set(_jump_to=target, _playing=False, _rebuilding=rebuild, _rebuild_to=target - 1 if rebuild else None)
        if rebuild:
            self._launch()
        verb = "rebuilding to" if rebuild else "fast-forward to"
        self._set(message=f"{verb} tick {target - 1}" + (": fresh process + fast-forward" if rebuild else ""))
        self._update_phase()

    def _should_capture(self, tick: int, paced: bool) -> bool:
        if self.history is None:
            return False
        if self._jump_to is not None:  # fast-forward: keep only the last `capacity` ticks before the target
            return tick > (self._jump_to - 1) - self.history.capacity
        if self.history_config.capture == "always":
            return True
        return not paced or self._speed <= 0.5  # "slow": single steps and slow playback only

    def _capture(self, tick: int, row: Optional[Row]) -> None:
        """Hand the frame now on screen (the post-update of `tick`) and its HUD data to the capture thread."""
        if self.history is None or self._worker is None or self.game is None:
            return
        hwnd = self.game.window()
        if hwnd is None:
            return
        with self._lock:
            obs = dict(self.tracker.last or self.tracker.initial or {})
            targets = self.tracker.targets_broken
        self._worker.submit((tick, row, obs, targets, hwnd, time.perf_counter()))

    def _step_one(self, *, paced: bool) -> None:
        assert self.game is not None
        if self.cursor >= len(self.rows) or self.tracker.ended:
            return
        row = self.rows[self.cursor]
        self._last_submit = (row.sequence_index, time.perf_counter())  # read by the capture thread
        reply = self.game.step(row)
        now = time.perf_counter()
        with self._lock:
            self.tracker.feed_step(row, *reply)
            self.cursor += 1
            self._last_row = row
            if self._times and now - self._times[-1] > 0.25:
                self._times.clear()
            self._times.append(now)
        if self._should_capture(row.sequence_index, paced):
            self._capture(row.sequence_index, row)
        if self.tracker.first_mismatch and not self._mismatch_logged:
            self._mismatch_logged = True
            self._set(message="")  # the UI shows the mismatch with the verdict (snapshot "mismatch")
            self.log(f"DESYNC detected at {self.tracker.first_mismatch}")
        if self.tracker.ended:
            self._finish()

    def _finish(self) -> None:
        verdict = compare(self.tracker)
        with self._lock:
            self.verdict = verdict
            self._playing = False
            self._jump_to = None
            self.message = ""  # the UI shows the verdict once (badge) and the end in the status line
        self._update_phase()
        self.log(format_verdict(self.ep, self.tracker, verdict))
        try:
            record_verdict(self.ep, self.tracker, verdict, mode="windowed", exe=self.exe_identity)
        except OSError as exc:
            self.log(f"note: verdict not recorded: {exc}")
        if self.on_end is not None:
            self.on_end(verdict)
