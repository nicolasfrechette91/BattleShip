#!/usr/bin/env python3
"""M7: parent side of the parallel BattleShip vector environment (Stable-Baselines3 SubprocVecEnv subclass).

M7SubprocVecEnv keeps SB3's SubprocVecEnv semantics (synchronous stepping,
auto-reset in the worker, terminal_observation, TimeLimit.truncated, seeds
passed at the next reset) and changes only what M7 needs:

- workers run btt_parallel.m7_worker (spawn start method, top-level picklable
  WorkerFactory, one BattleShip process at most per worker);
- every receive is bounded (poll with a timeout); a worker that raised sends
  a WorkerFailure and the parent raises M7WorkerFailure with the rank,
  command, episode context and traceback instead of freezing;
- close() is bounded: pending replies are drained with a timeout, every live
  worker is asked to close (which disposes its BattleShip process and returns
  a final report), stragglers are terminated, and any game process a dead or
  terminated worker left behind is killed by pid (image name checked);
- per-vector-step timing: step wall time, per-worker service time (the
  worker's own env.step) and reset time, from which the synchronous-vector
  stall (time a worker waited for the slowest one) is accumulated.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import sys
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from stable_baselines3.common.vec_env import SubprocVecEnv
from stable_baselines3.common.vec_env.base_vec_env import VecEnv, VecEnvIndices
from stable_baselines3.common.vec_env.subproc_vec_env import _stack_obs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from btt_parallel import LatencyHistogram, WorkerFactory, WorkerFailure, m7_worker  # noqa: E402
from m7_runtime import BATTLESHIP_IMAGE, kill_pid, pid_alive  # noqa: E402


class M7VecEnvError(RuntimeError):
    pass


class M7WorkerFailure(M7VecEnvError):
    def __init__(self, failure: WorkerFailure):
        self.failure = failure
        self.rank = failure.rank
        super().__init__(failure.describe() + "\n--- worker traceback ---\n" + failure.traceback)


class M7WorkerDied(M7VecEnvError):
    def __init__(self, rank: int, exitcode: Optional[int], detail: str):
        self.rank = rank
        self.exitcode = exitcode
        super().__init__(f"worker rank {rank} died without a reply (exit code {exitcode}): {detail}")


class M7WorkerTimeout(M7VecEnvError):
    def __init__(self, rank: int, timeout: float, command: str):
        self.rank = rank
        super().__init__(f"worker rank {rank} did not answer '{command}' within {timeout:g} s")


class StepTiming:
    """Accumulated per-vector-step timing (parent side)."""

    def __init__(self, n_envs: int):
        self.n_envs = n_envs
        self.vec_steps = 0
        self.wall_s = 0.0
        self.wall_hist = LatencyHistogram()
        self.reset_steps = 0            # vector steps in which at least one worker restarted its process
        self.reset_steps_wall_s = 0.0
        self.service_s = [0.0] * n_envs  # each worker's own env.step time
        self.reset_s = [0.0] * n_envs    # each worker's auto-reset (process restart or promotion) time
        self.idle_s = [0.0] * n_envs     # each worker's wait for the slowest worker + IPC
        self.resets = [0] * n_envs
        # M7c: parts of the reset time that the standby lifecycle exposes or removes
        self.standby_wait_s = [0.0] * n_envs   # exposed wait for a standby still starting at reset
        self.retire_s = [0.0] * n_envs         # closing + reaping the retired active process at reset
        self.promotion_s = [0.0] * n_envs      # installing a ready standby (re-verification included)
        self.reset_modes: Dict[str, int] = {}
        self.reset_hist = LatencyHistogram()   # every worker reset (promotion or cold launch)

    def add(self, wall: float, infos: Sequence[Dict[str, Any]], reset_infos: Sequence[Dict[str, Any]]) -> None:
        self.vec_steps += 1
        self.wall_s += wall
        self.wall_hist.add(wall)
        any_reset = False
        for i in range(self.n_envs):
            svc = float(infos[i].get("m7_service_s", 0.0) or 0.0)
            ri = reset_infos[i] or {}
            rst = float(ri.get("m7_reset_s", 0.0) or 0.0)
            self.service_s[i] += svc
            self.reset_s[i] += rst
            self.idle_s[i] += max(0.0, wall - svc - rst)
            if rst > 0:
                self.resets[i] += 1
                any_reset = True
                self.reset_hist.add(rst)
                self.standby_wait_s[i] += float(ri.get("m7_standby_wait_s", 0.0) or 0.0)
                self.retire_s[i] += float(ri.get("m7_retire_s", 0.0) or 0.0)
                self.promotion_s[i] += float(ri.get("m7_promotion_s", 0.0) or 0.0)
                mode = ri.get("m7_startup_mode") or "unknown"
                self.reset_modes[mode] = self.reset_modes.get(mode, 0) + 1
        if any_reset:
            self.reset_steps += 1
            self.reset_steps_wall_s += wall

    def to_json(self) -> Dict[str, Any]:
        return {
            "vec_steps": self.vec_steps,
            "wall_s": round(self.wall_s, 4),
            "wall_ms": LatencyHistogram.summary(self.wall_hist.to_json()),
            "reset_vec_steps": self.reset_steps,
            "reset_vec_steps_wall_s": round(self.reset_steps_wall_s, 4),
            "per_worker_service_s": [round(v, 4) for v in self.service_s],
            "per_worker_reset_s": [round(v, 4) for v in self.reset_s],
            "per_worker_idle_s": [round(v, 4) for v in self.idle_s],
            "per_worker_resets": list(self.resets),
            "per_worker_standby_wait_s": [round(v, 4) for v in self.standby_wait_s],
            "per_worker_retire_s": [round(v, 4) for v in self.retire_s],
            "per_worker_promotion_s": [round(v, 4) for v in self.promotion_s],
            "reset_modes": dict(self.reset_modes),
            "reset_ms": LatencyHistogram.summary(self.reset_hist.to_json()),
        }


class M7SubprocVecEnv(SubprocVecEnv):
    def __init__(self, factories: Sequence[WorkerFactory], *, start_method: str = "spawn",
                 step_timeout: float = 900.0, start_timeout: float = 180.0, close_timeout: float = 60.0):
        self.waiting = False
        self.closed = False
        self.ranks = [int(f.spec.rank) for f in factories]
        self.step_timeout = float(step_timeout)
        self.close_timeout = float(close_timeout)
        self.interrupt_at_step: Optional[int] = None  # test hook: raise KeyboardInterrupt inside step_wait
        self._step_calls = 0
        self._pending: set = set()
        self._t_step = 0.0
        self.game_pids: List[Optional[int]] = [None] * len(factories)
        self.standby_pids: List[Optional[int]] = [None] * len(factories)   # M7c: last standby pid each worker reported
        self.close_report: Optional[Dict[str, Any]] = None
        self.timing = StepTiming(len(factories))
        ctx = mp.get_context(start_method)
        self.remotes, self.work_remotes = zip(*[ctx.Pipe() for _ in factories], strict=True)
        self.processes = []
        for work_remote, remote, factory in zip(self.work_remotes, self.remotes, factories, strict=True):
            process = ctx.Process(target=m7_worker, args=(work_remote, remote, factory), daemon=True,
                                  name=f"m7-worker-{factory.spec.rank}")
            process.start()
            self.processes.append(process)
            work_remote.close()
        self._alive = [True] * len(factories)
        try:
            self.remotes[0].send(("get_spaces", None))
            observation_space, action_space = self._recv(0, "get_spaces", start_timeout)
            VecEnv.__init__(self, len(factories), observation_space, action_space)
        except BaseException:
            self.close()
            raise

    # -- bounded receive -----------------------------------------------------------------------------

    def _recv(self, i: int, command: str, timeout: Optional[float] = None) -> Any:
        remote = self.remotes[i]
        limit = self.step_timeout if timeout is None else float(timeout)
        try:
            if not remote.poll(limit):
                raise M7WorkerTimeout(self.ranks[i], limit, command)
            message = remote.recv()
        except (EOFError, ConnectionResetError, BrokenPipeError, OSError) as exc:
            self._alive[i] = False
            self._pending.discard(i)
            self.processes[i].join(timeout=5)
            raise M7WorkerDied(self.ranks[i], self.processes[i].exitcode, f"{command}: {type(exc).__name__}") from exc
        self._pending.discard(i)
        if isinstance(message, WorkerFailure):
            self._alive[i] = False
            raise M7WorkerFailure(message)
        return message

    def _send(self, i: int, message: Any) -> None:
        try:
            self.remotes[i].send(message)
        except (BrokenPipeError, EOFError, OSError) as exc:
            self._alive[i] = False
            raise M7WorkerDied(self.ranks[i], self.processes[i].exitcode, f"send {message[0]}: {exc}") from exc

    def _note_pids(self, reset_infos: Sequence[Dict[str, Any]], infos: Optional[Sequence[Dict[str, Any]]] = None) -> None:
        for i, info in enumerate(reset_infos):
            if info and info.get("pid"):
                self.game_pids[i] = int(info["pid"])
            if info and info.get("m7_standby_pid_reported"):
                self.standby_pids[i] = info.get("m7_standby_pid")
        for i, info in enumerate(infos or ()):
            if info and info.get("m7_standby_pid_reported"):
                self.standby_pids[i] = info.get("m7_standby_pid")

    # -- VecEnv API -------------------------------------------------------------------------------------

    def step_async(self, actions: np.ndarray) -> None:
        self._t_step = time.perf_counter()
        for i, action in enumerate(actions):
            self._send(i, ("step", action))
            self._pending.add(i)
        self.waiting = True

    def step_wait(self):
        self._step_calls += 1
        if self.interrupt_at_step is not None and self._step_calls == self.interrupt_at_step:
            raise KeyboardInterrupt("M7 test hook: interrupt inside step_wait with replies pending")
        results = [self._recv(i, "step") for i in range(len(self.remotes))]
        self.waiting = False
        obs, rews, dones, infos, reset_infos = zip(*results, strict=True)
        self.reset_infos = list(reset_infos)
        self._note_pids(self.reset_infos, infos)
        self.timing.add(time.perf_counter() - self._t_step, infos, self.reset_infos)
        return _stack_obs(obs, self.observation_space), np.stack(rews), np.stack(dones), infos

    def reset(self):
        for i, remote in enumerate(self.remotes):
            self._send(i, ("reset", (self._seeds[i], self._options[i])))
            self._pending.add(i)
        results = [self._recv(i, "reset") for i in range(len(self.remotes))]
        obs, reset_infos = zip(*results, strict=True)
        self.reset_infos = list(reset_infos)
        self._note_pids(self.reset_infos)
        self._reset_seeds()
        self._reset_options()
        return _stack_obs(obs, self.observation_space)

    def _call(self, command: str, payload: Any, indices: VecEnvIndices) -> List[Any]:
        target = self._get_indices(indices)
        for i in target:
            self._send(i, (command, payload))
            self._pending.add(i)
        return [self._recv(i, command) for i in target]

    def get_attr(self, attr_name: str, indices: VecEnvIndices = None) -> List[Any]:
        return self._call("get_attr", attr_name, indices)

    def set_attr(self, attr_name: str, value: Any, indices: VecEnvIndices = None) -> None:
        self._call("set_attr", (attr_name, value), indices)

    def has_attr(self, attr_name: str) -> bool:
        return all(self._call("has_attr", attr_name, None))

    def env_method(self, method_name: str, *method_args, indices: VecEnvIndices = None, **method_kwargs) -> List[Any]:
        return self._call("env_method", (method_name, method_args, method_kwargs), indices)

    def env_method_each(self, method_name: str, calls: Mapping[int, Tuple[Sequence[Any], Mapping[str, Any]]]
                        ) -> Dict[int, Any]:
        """M7h: one env_method per listed worker, each with its own arguments. Every command is sent before any reply
        is awaited (the workers run in parallel); replies are collected in index order. Unused by M7a-M7g."""
        order = sorted(int(i) for i in calls)
        for i in order:
            args, kwargs = calls[i]
            self._send(i, ("env_method", (method_name, tuple(args), dict(kwargs))))
            self._pending.add(i)
        return {i: self._recv(i, "env_method") for i in order}

    def env_is_wrapped(self, wrapper_class, indices: VecEnvIndices = None) -> List[bool]:
        return self._call("is_wrapped", wrapper_class, indices)

    def drain_pending(self, timeout: Optional[float] = None) -> List[int]:
        """Collect (and drop) replies still outstanding, e.g. after an interrupt inside step_wait."""
        lost = []
        for i in sorted(self._pending):
            try:
                self._recv(i, "drain", self.close_timeout if timeout is None else timeout)
            except M7VecEnvError:
                lost.append(self.ranks[i])
        self._pending.clear()
        self.waiting = False
        return lost

    def close(self) -> None:
        if self.closed:
            return
        t0 = time.perf_counter()
        report: Dict[str, Any] = {"ranks": {}, "drain_lost": [], "forced_terminations": [], "orphan_games_killed": []}
        report["drain_lost"] = self.drain_pending()
        for i, rank in enumerate(self.ranks):
            entry: Dict[str, Any] = {"alive_before_close": self._alive[i]}
            if self._alive[i]:
                try:
                    self._send(i, ("close", None))
                    reply = self._recv(i, "close", self.close_timeout)
                    entry["closed_cleanly"] = isinstance(reply, tuple) and reply[0] == "closed"
                    entry["worker_report"] = reply[1] if isinstance(reply, tuple) else None
                except M7VecEnvError as exc:
                    entry["closed_cleanly"] = False
                    entry["close_error"] = str(exc).splitlines()[0]
            report["ranks"][rank] = entry
        for i, process in enumerate(self.processes):
            process.join(timeout=self.close_timeout)
            if process.is_alive():
                process.terminate()
                process.join(timeout=10)
                report["forced_terminations"].append(self.ranks[i])
            report["ranks"][self.ranks[i]]["exitcode"] = process.exitcode
        # A worker that died or was terminated cannot have closed its game(s): kill them by pid
        # (active and, M7c, the last standby it reported; image name checked against pid reuse).
        for i, rank in enumerate(self.ranks):
            entry = report["ranks"][rank]
            if entry.get("closed_cleanly"):
                continue
            for role, pid in (("active", self.game_pids[i]), ("standby", self.standby_pids[i])):
                if pid is not None and pid_alive(pid) and kill_pid(pid, expected_image=BATTLESHIP_IMAGE):
                    report["orphan_games_killed"].append({"rank": rank, "pid": pid, "role": role})
        for remote in self.remotes:
            try:
                remote.close()
            except OSError:
                pass
        report["close_s"] = round(time.perf_counter() - t0, 3)
        self.close_report = report
        self.closed = True

    def worker_reports(self) -> Dict[int, Optional[Dict[str, Any]]]:
        if not self.close_report:
            return {}
        return {rank: entry.get("worker_report") for rank, entry in self.close_report["ranks"].items()}
