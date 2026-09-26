"""M7m worker side: the M7h recorded prefix phase, fed from the ONE registered anchor instead of this run's archive.

Constructed only when a profile has an [anchor_curriculum] table (opt-in; every other profile builds exactly the
workers it built before). AnchorWorkerWrapper is the outermost wrapper of a training worker, like M7h's
CurriculumWorkerWrapper, whose recorded prefix machinery it reuses (the episode trace, the fresh-episode check, the
prefix-boundary label `m7h_start` and its kinds, the lifecycle-failure path and the `m7h` summary block that the m7d
validators already read). It changes nothing that reset() or step() return. Differences from M7h:

  * run_prefix_phase accepts only a spec of this run whose prefix is anchor rows 0..tau-1 of the registered anchor
    (docs/rl_sweep_consolidation_m7m_anchor.json; pinned digest) for 1 <= tau <= 1020, and checks the post-prefix
    observation and target table against the registered F1 observation table;
  * it reads the target table of every step reply (the M7f diagnostic, SSB64_RL_TARGET_DIAG=1, read-only and
    gameplay-neutral) and, when an episode ends, attaches its sweep outcome (m7m_anchor.sweep_outcome) to the step info
    and to the episode summary (key `m7m`). The reward is untouched: btt_reward_v2 through M7RewardWrapper, rebased at
    the post-prefix observation so prefix breaks earn nothing.

The anchor supplies start states only: its actions are replayed as a prefix and never used as training targets.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import gymnasium as gym

import m7f_targets as ft
import m7h_curriculum as mc
import m7m_anchor as ma
from battleship_client import StepState
from battleship_process import EpisodeFailure
from btt_learning import Track1PolicyWrapper, policy_observation, track1_to_m3
from btt_parallel import M7RewardWrapper, M7WorkerWrapper, WorkerSpec, build_worker_env
from m7h_worker import LABEL_KEY, CurriculumWorkerWrapper, _find

OUTCOME_KEY = "m7m_outcome"        # step info key carrying the finished episode's sweep outcome to the parent
ROW_KEY = "m7m"                    # block added to the episode summary (-> metrics/episodes.jsonl)
DIAG_FLAG = ("SSB64_RL_TARGET_DIAG", "1")


def anchor_source(anchor: ma.Anchor) -> Dict[str, Any]:
    """The provenance recorded with every anchored start."""
    src = (anchor.record or {}).get("source") or {}
    return {"anchor_id": anchor.anchor_id, "run_id": src.get("run_id"), "episode_id": src.get("episode_id"),
            "native_action_digest": anchor.native_digest, "discovered_under": src.get("reward_contract"),
            "use": "start state only (explicit native action-prefix replay after a tick-0 reset)"}


class AnchorWorkerWrapper(CurriculumWorkerWrapper):
    def __init__(self, env: M7WorkerWrapper, *, settings: Mapping[str, Any], run_id: str, rank: int,
                 extra_env: Mapping[str, str], failure_log: Optional[Path] = None):
        gym.Wrapper.__init__(self, env)          # CurriculumWorkerWrapper.__init__ pins the M7h settings; not called
        if not isinstance(env, M7WorkerWrapper):
            raise ma.AnchorError("the anchor curriculum wraps the M7 worker stack only")
        if dict(extra_env).get(DIAG_FLAG[0]) != DIAG_FLAG[1]:
            raise ma.AnchorError("the anchor curriculum needs SSB64_RL_TARGET_DIAG=1 in every worker process")
        self.settings = ma.check_table(settings)
        self.anchor = ma.load_anchor()
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
                                      "classes": {}, "outcomes": 0, "successes": 0, "missing_target_tables": 0}
        self._client: Any = None
        self._last_reply: Optional[Dict[str, Any]] = None
        self._mask = 0
        self._first: Dict[int, int] = {}
        self._tau = 0
        self._window: Optional[int] = None

    # -- target identity (read-only) ------------------------------------------------------------------------

    def _capture(self, client: Any) -> None:
        """Keep the raw reply of every step request (instance attribute shadows the method; the M7j pattern)."""
        if self._client is client:
            return
        original = client.request

        def request(op: str, **payload: Any) -> Dict[str, Any]:
            reply = original(op, **payload)
            if op == "step":
                self._last_reply = reply
            return reply

        client.request = request
        self._client = client

    def _note_targets(self, consumed_tick: int) -> None:
        reply = self._last_reply
        if reply is None or reply.get("targets") is None:
            self.stats["missing_target_tables"] += 1
            raise ma.AnchorError(f"step reply of consumed tick {consumed_tick} has no target table")
        mask = ft.parse_targets(reply["targets"]).broken_mask
        if mask & self._mask != self._mask:
            raise ma.AnchorError(f"tick {consumed_tick}: a broken target became unbroken")
        for i in ft.mask_ids(mask & ~self._mask):
            self._first[int(i)] = int(consumed_tick)
        self._mask = mask
        self._last_reply = None

    # -- Gymnasium API (results unchanged) --------------------------------------------------------------

    def reset(self, **kwargs: Any):
        observation, info = super().reset(**kwargs)
        self.start["contract"] = ma.CONTRACT_ID
        episode = getattr(self.base, "episode", None)
        if episode is None or episode.client is None:
            raise ma.AnchorError("no active episode client after reset")
        self._capture(episode.client)
        self._last_reply = None
        self._mask, self._first, self._tau, self._window = 0, {}, 0, None
        return observation, info

    def step(self, action: Any):
        before = self.base.last_step_result
        observation, reward, terminated, truncated, info = super().step(action)
        result = self.base.last_step_result
        if result is not None and result is not before:
            self._note_targets(int(result.consumed_tick))
        if terminated or truncated:
            summary = info.get("m7_episode")
            if summary is not None:
                out = ma.sweep_outcome(tau=self._tau, first_break_ticks=self._first, end_reason=summary.get("end_reason"),
                                       policy_steps=int(summary.get("steps") or 0))
                out.update(contract=ma.CONTRACT_ID, kind=self.start.get("kind"), window_index=self._window,
                           episode_id=summary.get("episode_id"))
                summary[ROW_KEY] = out
                info[OUTCOME_KEY] = out
                self.stats["outcomes"] += 1
                self.stats["successes"] += int(out["success"])
        return observation, reward, terminated, truncated, info

    # -- the prefix phase (env_method) --------------------------------------------------------------------

    def run_prefix_phase(self, spec: Mapping[str, Any]) -> Dict[str, Any]:
        t0 = time.perf_counter()
        if spec.get("contract") != ma.CONTRACT_ID or spec.get("run_id") != self.run_id \
                or spec.get("anchor_id") != self.anchor.anchor_id:
            raise ma.AnchorError(f"anchor spec {spec.get('contract')!r} / {spec.get('run_id')!r} / "
                                 f"{spec.get('anchor_id')!r} offered to run {self.run_id!r}")
        prefix = bytes(spec["prefix"])
        tau = ma.check_cut(len(prefix))
        if int(spec["tau"]) != tau or prefix != self.anchor.prefix(tau) or mc.prefix_digest(prefix) != spec["prefix_digest"]:
            raise ma.AnchorError(f"cut {spec.get('tau')}: the prefix is not anchor rows 0..{tau - 1}")
        self._require_fresh()
        recorder = self.recording.recorder
        source = anchor_source(self.anchor)
        # Marked before the first prefix row (the M7h rule): an artifact holding a prefix row always carries the label.
        recorder.labels[LABEL_KEY] = {"contract": ma.CONTRACT_ID, "kind": mc.START_PREFIX_IN_PROGRESS,
                                      "prefix_length_planned": tau, "prefix_digest": spec["prefix_digest"], "cell": None,
                                      "source": source}
        last_m3, last_result = None, None
        try:
            for i, a in enumerate(prefix):
                stick, button = mc.decode_track1(a)
                obs_m3, _placeholder, terminated, truncated, info = self.base.step(track1_to_m3((stick, button)))
                result = self.base.last_step_result
                native = info.get("native_action")
                if (info.get("consumed_tick") != i or terminated or truncated or result is None or native is None
                        or result.state != StepState.WAITING_FOR_ACTION):
                    raise ma.AnchorError(
                        f"prefix step {i}: consumed_tick {info.get('consumed_tick')}, terminated {terminated}, "
                        f"truncated {truncated}, state {getattr(result, 'state_name', None)} (exact replay violated)")
                triple = (int(native.buttons), int(native.stick_x), int(native.stick_y))
                if triple != mc.track1_triple(a):
                    raise ma.AnchorError(f"prefix step {i}: native {triple} is not Track 1 action {a}")
                recorder.record_step(*triple, result)
                self.tracker.note_prefix_step(native, i)
                self.trace.add_row(a, triple, result.consumed_tick, result.observation, prefix=True)
                self._note_targets(i)
                last_m3, last_result = obs_m3, result
        except EpisodeFailure as exc:
            return self._prefix_lifecycle_failure(exc, spec, t0)
        end = mc.observation_dict(last_result.observation)
        diffs = mc.observation_diffs(end, spec["end_observation"])
        if diffs:
            raise ma.AnchorError(f"cut {tau}: post-prefix observation differs from the registered table: {diffs}")
        if self._mask != int(spec["broken_mask"]) or self._mask != ma.broken_mask_at(tau):
            raise ma.AnchorError(f"cut {tau}: broken mask {self._mask:#x} != registered {int(spec['broken_mask']):#x}")
        reference = self.reward.rebase_for_policy_phase(last_m3)
        policy_obs = policy_observation(last_m3)
        self.track1._last_policy_observation = policy_obs
        self.trace.prefix_length = tau
        wall = time.perf_counter() - t0
        start = {"contract": ma.CONTRACT_ID, "kind": mc.START_PREFIX, "prefix_length": tau,
                 "prefix_digest": spec["prefix_digest"], "cell": None, "source": source,
                 "lineage_left_exposed": False, "anchor_id": self.anchor.anchor_id, "tau": tau,
                 "window_index": int(spec["window_index"]), "pointer": int(spec["pointer"]),
                 "standing_right": list(ma.standing_right(tau)),
                 "prefix_targets_broken": mc.TARGETS_TOTAL - int(end["targets_remaining"]),
                 "prefix_broken_mask": self._mask,
                 "reward_reference_targets_remaining": reference,
                 "reset_contract": dict(self.start.get("reset_contract") or {}),
                 "tick0_observation": dict(self.trace.reset_observation), "prefix_end_observation": end,
                 "prefix_host_frame_equal": end.get("host_frame") == spec["end_observation"].get("host_frame"),
                 "prefix_wall_s": round(wall, 4)}
        recorder.labels[LABEL_KEY] = start
        self.start = start
        self._tau, self._window = tau, int(spec["window_index"])
        self.stats["prefix_phases"] += 1
        self.stats["prefix_ticks"] += tau
        self.stats["prefix_wall_s"] = round(self.stats["prefix_wall_s"] + wall, 4)
        return {"observation": policy_obs, "start": start}

    def worker_report(self) -> Dict[str, Any]:
        r = self.inner.worker_report()
        r["m7m"] = dict(self.stats, classes=dict(self.stats["classes"]))
        return r


def prefix_spec(anchor: ma.Anchor, table: Any, *, tau: int, window_index: int, run_id: str) -> Dict[str, Any]:
    """What the parent sends to a worker's run_prefix_phase (plain, picklable)."""
    tau = ma.check_cut(tau)
    row = dict(table[tau - 1])
    mask = int(row.pop("broken_mask"))
    return {"contract": ma.CONTRACT_ID, "run_id": run_id, "anchor_id": anchor.anchor_id, "tau": tau,
            "prefix": anchor.prefix(tau), "prefix_digest": anchor.prefix_digest(tau), "end_observation": row,
            "broken_mask": mask, "window_index": int(window_index), "pointer": ma.WINDOWS[int(window_index)][0]}


class AnchorWorkerFactory:
    """Picklable (spawn-safe) factory: the unchanged M7 worker stack plus the anchor wrapper outermost."""

    def __init__(self, spec: WorkerSpec, settings: Mapping[str, Any]):
        self.spec = spec
        self.settings = dict(settings)

    def __call__(self) -> AnchorWorkerWrapper:
        inner = build_worker_env(self.spec)
        log = Path(self.spec.worker_dir) / "m7m_prefix_failures.jsonl"
        return AnchorWorkerWrapper(inner, settings=self.settings, run_id=self.spec.run_id, rank=self.spec.rank,
                                   extra_env=dict(self.spec.extra_env), failure_log=log)
