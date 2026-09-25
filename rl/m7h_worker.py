"""M7h worker side: the explicit, recorded prefix phase (constructed only when the curriculum is enabled).

CurriculumWorkerWrapper is the outermost wrapper of a training worker (around M7WorkerWrapper). It changes nothing
that reset() or step() return; it only

  * keeps an EpisodeTrace of every row from tick 0 and, when an episode ends, attaches the M7h episode report to that
    step's info (for the parent's archive) and adds an `m7h` block to the episode summary row;
  * exposes run_prefix_phase(spec), a control method the parent calls through the worker's env_method protocol after
    an automatic reset. It refuses unless the episode is fresh (reset done, nothing stepped, nothing recorded), then
    submits the archived Track 1 actions one per native tick through M7BattleShipBTTEnv.step() (the same request
    path, fall detection, timing and horizon counter as a policy step), records every one in the episode's own
    recorder and digest, checks consumed ticks and the archived end observation, rebases the reward reference on the
    post-prefix observation, and returns the post-prefix policy observation.

reset() itself is untouched: it still returns the proven tick-0 observation and consumes nothing.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import gymnasium as gym

from battleship_client import StepState
from battleship_process import EpisodeFailure
from btt_learning import Track1PolicyWrapper, policy_observation, track1_indices, track1_to_m3
from btt_parallel import M7RewardWrapper, M7WorkerWrapper, WorkerSpec, build_worker_env
from run_artifacts import EpisodeStatus, PreservationReason
import m7h_curriculum as mc

REPORT_KEY = "m7h_report"          # step info key carrying the finished episode's report to the parent
ROW_KEY = "m7h"                    # block added to the episode summary (-> metrics/episodes.jsonl)
LABEL_KEY = mc.START_LABEL         # recorder label: the start record (prefix boundary, provenance); see mc.prefix_rows


def _find(env: Any, cls: type) -> Any:
    cur = env
    while isinstance(cur, gym.Wrapper):
        if isinstance(cur, cls):
            return cur
        cur = cur.env
    raise mc.CurriculumError(f"{cls.__name__} not found in the worker stack")


class CurriculumWorkerWrapper(gym.Wrapper):
    def __init__(self, env: M7WorkerWrapper, *, settings: Mapping[str, Any], run_id: str, rank: int,
                 failure_log: Optional[Path] = None):
        super().__init__(env)
        if not isinstance(env, M7WorkerWrapper):
            raise mc.CurriculumError("the curriculum wraps the M7 worker stack only")
        self.settings = mc.check_registered(settings)
        self.run_id = run_id
        self.rank = int(rank)
        self.inner = env
        self.base = env.base                 # m7_worker's close path reads .base
        self.recording = env.recording
        self.tracker = env.tracker
        self.reward: M7RewardWrapper = _find(env.env, M7RewardWrapper)
        self.track1: Track1PolicyWrapper = _find(env.env, Track1PolicyWrapper)
        self.failure_log = failure_log
        self.trace: Optional[mc.EpisodeTrace] = None
        self.start: Dict[str, Any] = {}
        self.stats: Dict[str, Any] = {"resets": 0, "prefix_phases": 0, "prefix_ticks": 0, "prefix_wall_s": 0.0,
                                      "prefix_lifecycle_failures": 0, "reports": 0, "reset_contract_violations": 0,
                                      "classes": {}}

    # -- Gymnasium API (results unchanged) --------------------------------------------------------------

    def reset(self, **kwargs: Any):
        observation, info = self.env.reset(**kwargs)
        lo = self.base.last_observe
        tick0 = mc.observation_dict(lo.observation)
        ok = int(lo.step_count) == 0 and int(tick0["input_tick"]) == 0 and int(getattr(self.base, "_steps", -1)) == 0
        if not ok:
            self.stats["reset_contract_violations"] += 1
        self.trace = mc.EpisodeTrace(reset_observation=tick0, reset_step_count=int(lo.step_count))
        self.start = {"contract": mc.CONTRACT_ID, "kind": mc.START_TICK0, "prefix_length": 0,
                      "reset_contract": {"input_tick": int(tick0["input_tick"]), "step_count": int(lo.step_count),
                                         "consumed_by_reset": 0, "ok": ok}}
        self.stats["resets"] += 1
        return observation, info

    def step(self, action: Any):
        stick, button = track1_indices(action)
        before = self.base.last_step_result
        observation, reward, terminated, truncated, info = self.env.step(action)
        result = self.base.last_step_result
        if self.trace is not None:
            if result is not None and result is not before:
                self.trace.add_row(mc.encode_track1(stick, button), mc.track1_triple(mc.encode_track1(stick, button)),
                                   result.consumed_tick, result.observation, prefix=False)
            else:
                self.trace.failed = True
        if terminated or truncated:
            summary = info.get("m7_episode")
            if summary is not None and self.trace is not None:
                report = self.trace.report(start=self.start, summary=summary, run_id=self.run_id, rank=self.rank)
                summary[ROW_KEY] = self._row(summary, report)
                info[REPORT_KEY] = report
                self.stats["reports"] += 1
                if report["class"]:
                    self.stats["classes"][report["class"]] = self.stats["classes"].get(report["class"], 0) + 1
        return observation, reward, terminated, truncated, info

    def close(self):
        return self.env.close()

    # -- the prefix phase (env_method) --------------------------------------------------------------------

    def run_prefix_phase(self, spec: Mapping[str, Any]) -> Dict[str, Any]:
        t0 = time.perf_counter()
        if spec.get("contract") != mc.CONTRACT_ID or spec.get("run_id") != self.run_id:
            raise mc.CurriculumError(f"prefix spec of {spec.get('run_id')!r} / {spec.get('contract')!r} offered to "
                                     f"run {self.run_id!r}")
        prefix = bytes(spec["prefix"])
        length = len(prefix)
        if not 1 <= length <= int(self.settings["max_prefix_ticks"]):
            raise mc.CurriculumError(f"prefix length {length} outside 1..{self.settings['max_prefix_ticks']}")
        if mc.prefix_digest(prefix) != spec["prefix_digest"]:
            raise mc.CurriculumError("prefix bytes do not match the archived digest")
        self._require_fresh()
        recorder = self.recording.recorder
        # Marked before the first prefix row: whatever ends this phase (completion, a lifecycle failure, a hard
        # failure that closes the worker), an artifact holding a prefix row always carries the label.
        recorder.labels[LABEL_KEY] = {"contract": mc.CONTRACT_ID, "kind": mc.START_PREFIX_IN_PROGRESS,
                                      "prefix_length_planned": length, "prefix_digest": spec["prefix_digest"],
                                      "cell": list(spec["cell"]), "source": dict(spec["source"])}
        last_m3, last_result = None, None
        try:
            for i, a in enumerate(prefix):
                stick, button = mc.decode_track1(a)
                obs_m3, _placeholder, terminated, truncated, info = self.base.step(track1_to_m3((stick, button)))
                result = self.base.last_step_result
                native = info.get("native_action")
                if (info.get("consumed_tick") != i or terminated or truncated or result is None or native is None
                        or result.state != StepState.WAITING_FOR_ACTION):
                    raise mc.CurriculumError(
                        f"prefix step {i}: consumed_tick {info.get('consumed_tick')}, terminated {terminated}, "
                        f"truncated {truncated}, state {getattr(result, 'state_name', None)} (exact replay violated)")
                triple = (int(native.buttons), int(native.stick_x), int(native.stick_y))
                if triple != mc.track1_triple(a):
                    raise mc.CurriculumError(f"prefix step {i}: native {triple} is not Track 1 action {a}")
                recorder.record_step(*triple, result)
                self.tracker.note_prefix_step(native, i)
                self.trace.add_row(a, triple, result.consumed_tick, result.observation, prefix=True)
                last_m3, last_result = obs_m3, result
        except EpisodeFailure as exc:
            return self._prefix_lifecycle_failure(exc, spec, t0)
        end = mc.observation_dict(last_result.observation)
        diffs = mc.observation_diffs(end, spec["end_observation"])
        if diffs:
            raise mc.CurriculumError(f"prefix end observation differs from the archive: {diffs}")
        reference = self.reward.rebase_for_policy_phase(last_m3)
        policy_obs = policy_observation(last_m3)
        self.track1._last_policy_observation = policy_obs
        self.trace.prefix_length = length
        wall = time.perf_counter() - t0
        start = {"contract": mc.CONTRACT_ID, "kind": mc.START_PREFIX, "prefix_length": length,
                 "prefix_digest": spec["prefix_digest"], "cell": list(spec["cell"]), "source": dict(spec["source"]),
                 "lineage_left_exposed": bool(spec["lineage_left_exposed"]),
                 "prefix_targets_broken": mc.TARGETS_TOTAL - int(end["targets_remaining"]),
                 "reward_reference_targets_remaining": reference,
                 "reset_contract": dict(self.start.get("reset_contract") or {}),
                 "tick0_observation": dict(self.trace.reset_observation), "prefix_end_observation": end,
                 "prefix_host_frame_equal": end.get("host_frame") == spec["end_observation"].get("host_frame"),
                 "prefix_wall_s": round(wall, 4)}
        recorder.labels[LABEL_KEY] = start
        self.start = start
        self.stats["prefix_phases"] += 1
        self.stats["prefix_ticks"] += length
        self.stats["prefix_wall_s"] = round(self.stats["prefix_wall_s"] + wall, 4)
        return {"observation": policy_obs, "start": start}

    def _require_fresh(self) -> None:
        b = self.base
        rec = self.recording.recorder
        lo = b.last_observe
        p: List[str] = []
        if b.phase != "active":
            p.append(f"base phase {b.phase}")
        if getattr(b, "_steps", None) != 0:
            p.append(f"base steps {getattr(b, '_steps', None)}")
        if self.inner.step_in_episode != 0:
            p.append(f"policy steps {self.inner.step_in_episode}")
        if rec is None or not rec.active or rec.action_count != 0:
            p.append(f"recorder {'missing' if rec is None else (rec.status.value, rec.action_count)}")
        if lo is None or int(lo.step_count) != 0 or int(lo.observation.input_tick) != 0:
            p.append("the last observe is not the tick-0 reset observation")
        if self.trace is None or self.trace.rows != 0 or self.start.get("kind") != mc.START_TICK0:
            p.append(f"trace rows {None if self.trace is None else self.trace.rows}, start {self.start.get('kind')}")
        if self.reward.episode_steps != 0:
            p.append(f"reward steps {self.reward.episode_steps}")
        if p:
            raise mc.CurriculumError("run_prefix_phase refused (the episode is not fresh): " + "; ".join(p))

    def _prefix_lifecycle_failure(self, exc: EpisodeFailure, spec: Mapping[str, Any], t0: float) -> Dict[str, Any]:
        """The process died during the prefix: finish that episode as failed (preserved), then an ordinary
        non-consuming reset; the parent receives a tick-0 start of kind tick0_after_prefix_lifecycle_failure."""
        self.stats["prefix_lifecycle_failures"] += 1
        outcome = getattr(getattr(exc, "outcome", None), "value", str(exc))
        rec = self.recording.recorder
        failed = {"kind": mc.START_PREFIX_FAILED, "prefix_length_planned": len(bytes(spec["prefix"])),
                  "rows_before_failure": self.trace.rows if self.trace else None, "outcome": outcome,
                  "source": dict(spec.get("source") or {})}
        if rec is not None and rec.active:
            rec.labels[LABEL_KEY] = failed
            rec.preserve(PreservationReason.MANUAL, f"m7h: prefix-phase lifecycle failure ({outcome})")
            self.recording._close_recorder(EpisodeStatus.FAILED, note=f"m7h prefix-phase lifecycle failure: {outcome}")
        summary = self.tracker.pop_summary()        # never leaks into the next policy step's info
        if self.failure_log is not None:
            self.failure_log.parent.mkdir(parents=True, exist_ok=True)
            with open(self.failure_log, "a", encoding="utf-8", newline="\n") as fp:
                fp.write(json.dumps({"failed": failed, "summary": summary}, default=str) + "\n")
        observation, _info = self.reset()
        self.start = dict(self.start, kind=mc.START_TICK0_AFTER_FAILURE, failed_prefix=failed)
        return {"observation": observation, "start": self.start, "failed_summary": summary,
                "wall_s": round(time.perf_counter() - t0, 4)}

    # -- records ----------------------------------------------------------------------------------------

    def _row(self, summary: Mapping[str, Any], report: Mapping[str, Any]) -> Dict[str, Any]:
        tr = self.trace
        assert tr is not None
        s = self.start
        steps = int(summary.get("steps") or 0)
        last = tr.last_observation or {}
        total = mc.TARGETS_TOTAL - int(last["targets_remaining"]) if last.get("btt_active") == 1 else None
        return {"contract": mc.CONTRACT_ID, "start_kind": s.get("kind"), "prefix_length": int(s.get("prefix_length", 0)),
                "prefix_digest": s.get("prefix_digest"), "cell": s.get("cell"),
                "source_episode_id": (s.get("source") or {}).get("episode_id"),
                "lineage_left_exposed": bool(s.get("lineage_left_exposed", False)),
                "prefix_targets_broken": s.get("prefix_targets_broken", 0), "prefix_wall_s": s.get("prefix_wall_s"),
                "prefix_host_frame_equal": s.get("prefix_host_frame_equal"),
                "reset_contract": s.get("reset_contract"), "policy_steps": steps, "rows": tr.rows,
                "rows_equal_prefix_plus_policy": tr.rows == int(s.get("prefix_length", 0)) + steps,
                "first_row_consumed_tick": 0 if tr.rows and tr.consumed_ok else None,
                "consumed_ticks_ok": tr.consumed_ok, "trace_failed": tr.failed,
                "full_digest_agrees": report["full_digest"] == summary.get("native_action_digest"),
                "targets_broken_policy": summary.get("targets_broken"), "targets_broken_total": total,
                "class": report["class"], "prefix_left_steps": tr.prefix_left_steps,
                "first_policy_left_step": tr.first_policy_left_step, "new_cells_reported": len(tr.first_reach),
                "min_x_at_high_y_policy": tr.min_x_high["policy"], "min_x_at_high_y_prefix": tr.min_x_high["prefix"]}

    # -- delegation for m7_worker's direct calls ----------------------------------------------------------

    def worker_report(self) -> Dict[str, Any]:
        r = self.inner.worker_report()
        r["m7h"] = dict(self.stats, classes=dict(self.stats["classes"]))
        return r

    def error_context(self) -> Dict[str, Any]:
        ctx = self.inner.error_context()
        ctx["m7h"] = {"trace_rows": None if self.trace is None else self.trace.rows, "start": self.start.get("kind")}
        return ctx


class CurriculumWorkerFactory:
    """Picklable (spawn-safe) factory: the unchanged M7 worker stack plus the curriculum wrapper outermost."""

    def __init__(self, spec: WorkerSpec, settings: Mapping[str, Any]):
        self.spec = spec
        self.settings = dict(settings)

    def __call__(self) -> CurriculumWorkerWrapper:
        inner = build_worker_env(self.spec)
        log = Path(self.spec.worker_dir) / "m7h_prefix_failures.jsonl"
        return CurriculumWorkerWrapper(inner, settings=self.settings, run_id=self.spec.run_id, rank=self.spec.rank,
                                       failure_log=log)
