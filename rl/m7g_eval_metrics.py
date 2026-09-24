"""M7g Phase K: per-episode evaluation metrics `btt_eval_metrics_v1` (evaluation only).

Recorded for every evaluation episode when the evaluator enables it (m7_evaluation.EvaluationSettings.eval_metrics),
from native facts only:

  first_left_entry      the first live post-update observation (fighter_valid 1, btt_active 1) whose position_x is
                        below LEFT_BOUNDARY_X = -2100.0: the left boundary M7g-a derived from the collision data
                        (minimum x of the main solid polygon, validated on both crossing fixtures) and M7f's
                        WALL_LEFT_FACE_X. Same rule and same fields as the M7g-a crossing evidence: step index,
                        consumed tick, input tick, time_passed, x, y, ground_air_state, fighter_status_id
  target_breaks         every break reported by the M7f diagnostic btt_target_identity_v1 (SSB64_RL_TARGET_DIAG=1),
                        derived from consecutive remaining masks exactly as m7f_targets.check_trace does (same
                        parse, same per-reply checks, same event fields), in native break order;
                        first_break_tick[id] = consumed tick of that target's break
  seven_or_more_targets targets_broken >= 7
  moving target ID 2    whether it broke and the consumed tick of its break
  clear                 cleared natively (M4: EpisodeEnded with targets_remaining 0) and the two completion clocks,
                        completion_time_passed and completion_input_tick, kept as TWO values (the 7.43 TAS: 446 and
                        447 - never collapsed, never decremented), cross-checked against the diagnostic's final break
                        record; clear_verified stays None ("pending") until the Phase K driver re-validates the
                        canonical actions natively on a fresh process (rl/m7g_k_run.py verify-clears)
  termination           end_reason, termination_reason, truncation_reason, last_consumed_tick

Nothing here is an observation, a reward or a policy input. The recorder sits inside the evaluation worker, between
EpisodeStatsWrapper and M7WorkerWrapper; it passes observations, rewards, actions and infos through unchanged, reads
the raw step replies through an instance-level shadow of the episode client's `request` (the pattern of
rl/m7g_obs.SpatialObsV2Wrapper), issues one extra non-consuming `observe` per reset for the tick-0 target table,
and adds one key, `eval_metrics`, to the episode summary through M7EpisodeTracker.extend_pending_summary. Training
workers never build it: no training profile sets SSB64_RL_TARGET_DIAG and the trainer never enables it.

The crossing fixtures of M7g-a are NOT read by this module; the tests use them as validation evidence only.

Self-test (no game): python rl/m7g_eval_metrics.py --self-test
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import gymnasium as gym

import m7f_targets as mt

CONTRACT = "btt_eval_metrics_v1"
TARGETS_TOTAL = mt.TARGET_COUNT
LEFT_BOUNDARY_X = mt.WALL_LEFT_FACE_X          # -2100.0 = M7g-a derive_regions()["left_boundary_x"] (tested)
LEFT_TARGET_IDS = (1, 6, 8)                    # the three targets left of the wall (M7f region table)
MOVING_TARGET_ID = 2                           # the target carried by the moving platform (M7f: animated)
SEVEN_TARGETS = 7
DIAG_ENV = mt.DIAG_ENV                         # SSB64_RL_TARGET_DIAG
DIAG_FLAG: Tuple[Tuple[str, str], ...] = ((DIAG_ENV, "1"),)
POINT_FIELDS = ("step_index", "consumed_tick", "input_tick", "time_passed", "x", "y", "ground_air_state",
                "fighter_status_id")


class EvalMetricsError(RuntimeError):
    """The recorder cannot pair its raw replies with the episode (a wiring defect, never a gameplay fact)."""


def with_diag_flag(extra_env: Sequence[Tuple[str, str]]) -> Tuple[Tuple[str, str], ...]:
    """The evaluation flags plus SSB64_RL_TARGET_DIAG=1 (read-only diagnostic, proven gameplay-neutral in M7f)."""
    flags = dict(extra_env)
    flags[DIAG_ENV] = "1"
    return tuple(flags.items())


def _point(i: int, reply: Mapping[str, Any]) -> Dict[str, Any]:
    """The M7g-a crossing-evidence point of one step reply (same keys, same sources as that evidence)."""
    o = reply.get("observation") or {}
    return {"step_index": i, "consumed_tick": reply.get("consumed_tick"), "input_tick": o.get("input_tick"),
            "time_passed": o.get("time_passed"), "x": o.get("position_x"), "y": o.get("position_y"),
            "ground_air_state": o.get("ground_air_state"), "fighter_status_id": o.get("fighter_status_id")}


# -- m7f_targets.check_trace, one reply at a time -----------------------------------------------------------------


class IncrementalTargetTrace:
    """m7f_targets.check_trace(initial, steps), fed one step reply at a time: the same parse, the same per-reply
    checks (check_snapshot), the same event derivation from consecutive remaining masks and, at finish(), the same
    whole-episode order checks. A parse failure stops the derivation exactly where check_trace returns early.
    Equivalence with check_trace is a tested property (self_test, rl/m7g_k_campaign_tests.py)."""

    def __init__(self, initial_reply: Mapping[str, Any]):
        self.chk = mt.TraceCheck()
        self.prev: Optional[mt.TargetSnapshot] = None
        self._static0: Optional[str] = None
        self._seen_orders: Dict[int, int] = {}
        self._stopped = False
        self._index = 0
        try:
            prev = mt.parse_targets(initial_reply.get(mt.REPLY_KEY))
        except mt.TargetContractError as exc:
            self.chk.fail(f"initial: {exc}")
            self._stopped = True
            return
        self.chk.initial = prev
        mt.check_snapshot("initial", prev, initial_reply.get("observation") or {}, self.chk)
        if prev.remaining_mask != mt.FULL_MASK or prev.break_count != 0:
            self.chk.fail(f"initial: remaining_mask 0x{prev.remaining_mask:x} break_count {prev.break_count} (expected "
                          "all ten active, none broken)")
        self._static0 = mt.static_signature(prev)
        self.prev = prev

    def step(self, reply: Mapping[str, Any]) -> List[Dict[str, Any]]:
        i = self._index
        self._index += 1
        if self._stopped:
            return []
        chk = self.chk
        where = f"step {i}"
        try:
            snap = mt.parse_targets(reply.get(mt.REPLY_KEY))
        except mt.TargetContractError as exc:
            chk.fail(f"{where}: {exc}")
            self._stopped = True
            self.prev = None      # check_trace returns before recording a final snapshot
            return []
        prev = self.prev
        assert prev is not None
        obs = reply.get("observation") or {}
        consumed = reply.get("consumed_tick")
        mt.check_snapshot(where, snap, obs, chk)
        if mt.static_signature(snap) != self._static0:
            chk.fail(f"{where}: static target table changed (IDs / spawn positions / animated flags)")
        if snap.remaining_mask & ~prev.remaining_mask:
            chk.fail(f"{where}: target(s) {mt.mask_ids(snap.remaining_mask & ~prev.remaining_mask)} became active again")
        for r_prev, r in zip(prev.records, snap.records):
            if r_prev.break_order and (r_prev.break_order, r_prev.break_input_tick, r_prev.break_time_passed,
                                       r_prev.break_pos) != (r.break_order, r.break_input_tick,
                                                             r.break_time_passed, r.break_pos):
                chk.fail(f"{where}: break record of target {r.id} changed after its break")
        new: List[Dict[str, Any]] = []
        cleared = prev.remaining_mask & ~snap.remaining_mask
        if cleared:
            ids = mt.mask_ids(cleared)
            chk.mask_changes.append({"step_index": i, "consumed_tick": consumed, "input_tick": obs.get("input_tick"),
                                     "remaining_mask": snap.remaining_mask, "cleared_ids": ids})
            for tid in ids:
                rec = snap.records[tid]
                ev = {"target_id": tid, "consumed_tick": consumed, "input_tick": obs.get("input_tick"),
                      "step_index": i, "break_order": rec.break_order,
                      "native_break_input_tick": rec.break_input_tick,
                      "native_break_time_passed": rec.break_time_passed, "break_pos": list(rec.break_pos)}
                if rec.break_input_tick != obs.get("input_tick") or consumed is None or \
                        rec.break_input_tick != consumed + 1:
                    chk.fail(f"{where}: target {tid} native break_input_tick {rec.break_input_tick} vs consumed "
                             f"{consumed} / input_tick {obs.get('input_tick')}")
                if rec.break_time_passed != obs.get("time_passed"):
                    chk.fail(f"{where}: target {tid} native break_time_passed {rec.break_time_passed} vs "
                             f"observation time_passed {obs.get('time_passed')}")
                if rec.break_order in self._seen_orders:
                    chk.fail(f"{where}: break_order {rec.break_order} reused by targets "
                             f"{self._seen_orders[rec.break_order]} and {tid}")
                self._seen_orders[rec.break_order] = tid
                chk.events.append(ev)
                new.append(ev)
        self.prev = snap
        return new

    def finish(self) -> mt.TraceCheck:
        chk = self.chk
        if self._stopped:
            return chk        # check_trace returned early: no final snapshot, no order checks
        chk.final = self.prev
        orders = [e["break_order"] for e in chk.events]
        if orders != sorted(orders):
            chk.fail(f"events are not in native break order: {orders}")
        by_tick: Dict[Any, List[Dict[str, Any]]] = {}
        for e in chk.events:
            by_tick.setdefault(e["consumed_tick"], []).append(e)
        for tick, evs in by_tick.items():
            if len(evs) > 1 and [e["target_id"] for e in sorted(evs, key=lambda e: e["break_order"])] != \
                    sorted(e["target_id"] for e in evs):
                chk.fail(f"same-tick breaks at {tick} not in ascending ID order: "
                         f"{[(e['target_id'], e['break_order']) for e in evs]}")
        return chk


# -- one episode ---------------------------------------------------------------------------------------------------


class EpisodeMetrics:
    """The metrics of one episode, fed the tick-0 observe reply and then every step reply in order."""

    def __init__(self, initial_reply: Mapping[str, Any], *, left_boundary_x: float = LEFT_BOUNDARY_X):
        self.left_x = float(left_boundary_x)
        self.targets = IncrementalTargetTrace(initial_reply)
        self.steps = 0
        self.first_left: Optional[Dict[str, Any]] = None
        self.left_steps = 0
        self.min_x: Optional[float] = None
        self.last_consumed: Optional[int] = None
        self.problems: List[str] = []

    def step(self, reply: Mapping[str, Any]) -> None:
        i = self.steps
        self.steps += 1
        self.last_consumed = reply.get("consumed_tick")
        o = reply.get("observation") or {}
        if o.get("fighter_valid") == 1 and o.get("btt_active") == 1:      # the M7g-a "live" filter
            x = float(o["position_x"])
            if self.min_x is None or x < self.min_x:
                self.min_x = x
            if x < self.left_x:
                self.left_steps += 1
                if self.first_left is None:
                    self.first_left = _point(i, reply)
        self.targets.step(reply)

    def note(self, problem: str) -> None:
        if len(self.problems) < 20:
            self.problems.append(problem)

    def finish(self, summary: Mapping[str, Any]) -> Dict[str, Any]:
        """The btt_eval_metrics_v1 record, cross-checked against the worker's own episode summary."""
        chk = self.targets.finish()
        events = list(chk.events)
        diag_ok = chk.ok
        broken_ids = [int(e["target_id"]) for e in events]
        first_break: Dict[str, int] = {}
        for e in events:
            first_break.setdefault(str(e["target_id"]), int(e["consumed_tick"]))
        moving = next((e for e in events if e["target_id"] == MOVING_TARGET_ID), None)
        tb = summary.get("targets_broken")
        cleared = bool(summary.get("cleared"))
        ctp, cit = summary.get("completion_time_passed"), summary.get("completion_input_tick")
        last = events[-1] if events else None
        consistency: Dict[str, Optional[bool]] = {
            "steps_equal_summary": summary.get("steps") == self.steps,
            "last_consumed_tick_equal_summary": summary.get("last_consumed_tick") == self.last_consumed,
            "targets_broken_equal_breaks": (tb == len(events)) if diag_ok else None,
            "break_ticks_equal_summary": (list(summary.get("target_break_ticks") or []) == mt.break_ticks(events))
            if diag_ok and summary.get("target_break_ticks") is not None else None,
            "clear_is_all_targets": (cleared == (tb == TARGETS_TOTAL and len(events) == TARGETS_TOTAL))
            if diag_ok else None,
        }
        if cleared:
            consistency["completion_input_tick_is_last_consumed_plus_1"] = (
                cit is not None and self.last_consumed is not None and int(cit) == int(self.last_consumed) + 1)
            consistency["completion_clocks_equal_final_break"] = (
                last is not None and cit == last["native_break_input_tick"] and ctp == last["native_break_time_passed"]
            ) if diag_ok else None
        ok = diag_ok and not self.problems and all(v is not False for v in consistency.values())
        return {
            "contract": CONTRACT,
            "left_boundary_x": self.left_x,
            "steps_recorded": self.steps,
            "first_left_entry": self.first_left,
            "left_region_steps": self.left_steps,
            "min_live_x": self.min_x,
            "target_diag": {"contract": mt.CONTRACT_ID, "ok": diag_ok, "problems": chk.problems[:10],
                            "final_remaining_mask": chk.final.remaining_mask if chk.final else None},
            "target_breaks": [{k: e[k] for k in ("target_id", "consumed_tick", "input_tick", "break_order",
                                                 "native_break_input_tick", "native_break_time_passed")}
                              for e in events],
            "broken_ids": broken_ids,
            "first_break_tick": first_break,
            "left_targets_broken": [t for t in broken_ids if t in LEFT_TARGET_IDS],
            "moving_target_id": MOVING_TARGET_ID,
            "moving_target_broken": moving is not None,
            "moving_target_break_tick": None if moving is None else int(moving["consumed_tick"]),
            "targets_broken": tb,
            "seven_or_more_targets": isinstance(tb, int) and tb >= SEVEN_TARGETS,
            "cleared_native": cleared,
            "completion_time_passed": ctp,
            "completion_input_tick": cit,
            "clear_verified": None,
            "clear_verification": "pending: native re-validation by the Phase K driver" if cleared else "not_applicable",
            "end_reason": summary.get("end_reason"),
            "termination_reason": summary.get("termination_reason"),
            "truncation_reason": summary.get("truncation_reason"),
            "last_consumed_tick": self.last_consumed,
            "consistency": consistency,
            "recorder_problems": list(self.problems),
            "ok": bool(ok),
        }


def metrics_from_trace(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]],
                       summary: Mapping[str, Any], *, left_boundary_x: float = LEFT_BOUNDARY_X) -> Dict[str, Any]:
    """Offline: the same record from a complete raw trace (tick-0 observe reply + every step reply)."""
    m = EpisodeMetrics(initial, left_boundary_x=left_boundary_x)
    for r in steps:
        m.step(r)
    return m.finish(summary)


# -- the worker wrapper -----------------------------------------------------------------------------------------------


class EvalMetricsWrapper(gym.Wrapper):
    """Between EpisodeStatsWrapper and M7WorkerWrapper of an evaluation worker. Transparent: observations, rewards,
    actions and infos are passed through unchanged; at the end of every episode the tracker's pending summary gains
    `eval_metrics`. keep_trace=True (tests only) also keeps the raw replies for offline comparison."""

    def __init__(self, env: Any, *, base: Any, tracker: Any, keep_trace: bool = False):
        super().__init__(env)
        self.base = base
        self.tracker = tracker
        self.keep_trace = keep_trace
        self.metrics: Optional[EpisodeMetrics] = None
        self.last_record: Optional[Dict[str, Any]] = None
        self.initial_reply: Optional[Dict[str, Any]] = None
        self.trace: List[Dict[str, Any]] = []
        self._client: Any = None
        self._last_step_reply: Optional[Dict[str, Any]] = None
        self.episodes_recorded = 0

    def _capture(self, client: Any) -> None:
        if self._client is client:
            return
        original = client.request

        def request(op: str, **payload: Any) -> Dict[str, Any]:
            reply = original(op, **payload)
            if op == "step":
                self._last_step_reply = reply
            return reply

        client.request = request
        self._client = client

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        observation, info = self.env.reset(seed=seed, options=options)
        episode = self.base.episode
        if episode is None or episode.client is None:
            raise EvalMetricsError("no active episode after reset")
        self._capture(episode.client)
        reply = episode.client.request("observe")          # non-consuming: no tick, no clock
        reset_obs = dataclasses.asdict(self.base.last_observe.observation)
        if reply.get("ok") is not True or reply.get("observation") != reset_obs:
            raise EvalMetricsError(f"the metrics re-observe does not match the reset observation "
                                   f"({reply.get('observation')} vs {reset_obs})")
        self.metrics = EpisodeMetrics(reply)
        self.initial_reply = reply if self.keep_trace else None
        self.trace = []
        self._last_step_reply = None
        return observation, info

    def step(self, action: Any):
        self._last_step_reply = None
        observation, reward, terminated, truncated, info = self.env.step(action)
        m = self.metrics
        reply = self._last_step_reply
        result = self.base.last_step_result
        if m is not None:
            if info.get("truncation_reason") == "episode_failure":
                m.note("lifecycle failure: the last action was not consumed")
            elif reply is None or result is None or reply.get("step_count") != result.step_count:
                m.note("no raw step reply paired with the step result")
            else:
                m.step(reply)
                if self.keep_trace:
                    self.trace.append(reply)
        if (terminated or truncated) and m is not None:
            def build(summary: Mapping[str, Any]) -> Dict[str, Any]:
                self.last_record = m.finish(summary)
                return {"eval_metrics": self.last_record}

            if self.tracker.extend_pending_summary(build):
                self.episodes_recorded += 1
            self.metrics = None
        return observation, reward, terminated, truncated, info


class EvalMetricsWorkerFactory:
    """Top-level, picklable (spawn-safe) factory: the inner M7 worker factory's stack (v1 or v2) with
    EvalMetricsWrapper inserted directly inside M7WorkerWrapper. The inner spec must carry SSB64_RL_TARGET_DIAG=1."""

    def __init__(self, inner: Any):
        self.inner = inner
        self.spec = inner.spec   # the worker loop reads factory.spec.rank

    def __call__(self) -> Any:
        if dict(self.spec.extra_env).get(DIAG_ENV) != "1":
            raise ValueError(f"evaluation metrics need {DIAG_ENV}=1 in the worker flags")
        worker = self.inner()
        worker.env = EvalMetricsWrapper(worker.env, base=worker.base, tracker=worker.tracker)
        return worker


# -- self-test (no game) ----------------------------------------------------------------------------------------------


def _synthetic_trace(breaks_at: Mapping[int, Sequence[int]], n: int, xs: Optional[Sequence[float]] = None
                     ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """A synthetic episode in the m7f self-test format (+ positions): breaks_at[consumed tick] = target ids."""
    brk: Dict[int, Tuple[int, int]] = {}
    mask = mt.FULL_MASK
    order = 0

    def obs(t_in: int, remaining: int, x: float) -> Dict[str, Any]:
        return dict(mt._obs(t_in, remaining), fighter_valid=1, position_x=x, position_y=0.0, ground_air_state=0,
                    fighter_status_id=10)

    init = {"observation": obs(0, 10, 0.0), mt.REPLY_KEY: mt._synthetic(mt.FULL_MASK, {}, 0)}
    steps = []
    for t in range(n):
        for tid in sorted(breaks_at.get(t, ())):
            mask &= ~(1 << tid)
            order += 1
            brk[tid] = (order, t + 1)
        x = float(xs[t]) if xs is not None else 0.0
        steps.append({"consumed_tick": t, "observation": obs(t + 1, mt.popcount(mask), x),
                      mt.REPLY_KEY: mt._synthetic(mask, dict(brk), t + 1)})
    return init, steps


def _events_key(events: Sequence[Mapping[str, Any]]) -> List[Tuple[Any, ...]]:
    return [(e["target_id"], e["consumed_tick"], e["input_tick"], e["break_order"], e["native_break_input_tick"],
             e["native_break_time_passed"]) for e in events]


def equivalent_to_check_trace(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Run both derivations on one trace: events, problems, masks and final snapshot must be identical."""
    ref = mt.check_trace(initial, steps)
    inc = IncrementalTargetTrace(initial)
    for r in steps:
        inc.step(r)
    got = inc.finish()
    same = (_events_key(ref.events) == _events_key(got.events) and ref.problems == got.problems
            and ref.mask_changes == got.mask_changes and ref.final == got.final and ref.initial == got.initial)
    return {"identical": same, "events": len(ref.events), "problems": len(ref.problems)}


def self_test() -> int:
    bad: List[str] = []

    def expect(cond: bool, name: str) -> None:
        if not cond:
            bad.append(name)

    # 1. incremental == check_trace on clean and on every m7f violation kind (resurrection, pairing, count, anomaly,
    #    wrong native tick, same-tick order, parse failure mid-episode, missing initial object)
    init, steps = _synthetic_trace({5: [4], 9: [1, 7]}, 12)
    variants: Dict[str, Tuple[Mapping[str, Any], List[Mapping[str, Any]]]] = {"clean": (init, steps)}
    s = [dict(x) for x in steps]
    s[7] = {**steps[7], mt.REPLY_KEY: mt._synthetic(mt.FULL_MASK, {}, 8)}
    variants["resurrection"] = (init, s)
    s = [dict(x) for x in steps]
    s[3] = {**steps[3], mt.REPLY_KEY: {**steps[3][mt.REPLY_KEY], "input_tick": 99}}
    variants["pairing"] = (init, s)
    s = [dict(x) for x in steps]
    s[6] = {**steps[6], "observation": {**steps[6]["observation"], "targets_remaining": 10}}
    variants["count"] = (init, s)
    s = [dict(x) for x in steps]
    s[2] = {**steps[2], mt.REPLY_KEY: mt._synthetic(mt.FULL_MASK, {}, 3, anomalies=1 << 2)}
    variants["anomaly"] = (init, s)
    s = [dict(x) for x in steps]
    s[5] = {**steps[5], mt.REPLY_KEY: mt._synthetic(mt.FULL_MASK & ~(1 << 4), {4: (1, 42)}, 6)}
    variants["native_tick"] = (init, s[:6])
    s = [dict(x) for x in steps]
    s[4] = {k: v for k, v in steps[4].items() if k != mt.REPLY_KEY}
    variants["parse_failure_mid_episode"] = (init, s)
    variants["no_initial_object"] = ({"observation": init["observation"]}, steps)
    swapped = {4: (1, 6), 1: (3, 10), 7: (2, 10)}
    s = [dict(x) for x in steps]
    for k in range(9, 12):
        s[k] = {**steps[k], mt.REPLY_KEY: mt._synthetic(steps[k][mt.REPLY_KEY]["remaining_mask"], swapped, k + 1)}
    variants["same_tick_order"] = (init, s)
    for name, (i0, st) in variants.items():
        r = equivalent_to_check_trace(i0, st)
        expect(r["identical"], f"equivalence_{name}")
    expect(mt.check_trace(*variants["clean"]).ok and not mt.check_trace(*variants["pairing"]).ok, "variants_meaningful")
    # 2. the record: left entry (first live x < -2100), breaks, first-break ticks, target 2, seven targets
    xs = [0.0] * 20
    xs[8], xs[9], xs[10] = -2100.0, -2100.5, -2300.0       # exactly -2100 is NOT left of the boundary
    init, steps = _synthetic_trace({3: [2], 5: [0, 3, 4], 7: [5, 6, 7], 12: [9]}, 20, xs)
    summary = {"steps": 20, "last_consumed_tick": 19, "targets_broken": 8, "cleared": False,
               "target_break_ticks": [3, 5, 5, 5, 7, 7, 7, 12], "end_reason": "horizon",
               "truncation_reason": "max_episode_steps"}
    rec = metrics_from_trace(init, steps, summary)
    expect(rec["first_left_entry"] is not None and rec["first_left_entry"]["step_index"] == 9
           and rec["first_left_entry"]["consumed_tick"] == 9 and rec["left_region_steps"] == 2, f"left {rec['first_left_entry']}")
    expect(rec["broken_ids"] == [2, 0, 3, 4, 5, 6, 7, 9] and rec["first_break_tick"]["2"] == 3
           and rec["moving_target_broken"] and rec["moving_target_break_tick"] == 3, f"breaks {rec['broken_ids']}")
    expect(rec["left_targets_broken"] == [6] and rec["seven_or_more_targets"] and rec["ok"], f"record {rec['consistency']}")
    # a summary that disagrees with the diagnostic is flagged (never silently accepted)
    wrong = dict(summary, targets_broken=7, target_break_ticks=[3, 5, 5, 5, 7, 7, 7])
    rec_w = metrics_from_trace(init, steps, wrong)
    expect(not rec_w["ok"] and rec_w["consistency"]["targets_broken_equal_breaks"] is False, "inconsistency_flagged")
    # 3. a clear: 446/447 semantics (last consumed 446, completion_input_tick 447, time_passed 446) and all ten
    init, steps = _synthetic_trace({100: [0, 1, 2, 3, 4], 300: [5, 6, 7, 8], 446: [9]}, 447)
    clear = {"steps": 447, "last_consumed_tick": 446, "targets_broken": 10, "cleared": True,
             "completion_time_passed": 446, "completion_input_tick": 447,
             "target_break_ticks": [100] * 5 + [300] * 4 + [446], "end_reason": "clear",
             "termination_reason": "native_clear"}
    rec_c = metrics_from_trace(init, steps, clear)
    expect(rec_c["ok"] and rec_c["cleared_native"] and (rec_c["completion_time_passed"], rec_c["completion_input_tick"])
           == (446, 447) and rec_c["clear_verified"] is None and rec_c["consistency"]
           ["completion_input_tick_is_last_consumed_plus_1"], f"clear {rec_c['consistency']}")
    collapsed = dict(clear, completion_input_tick=446)      # a collapsed clock must fail the consistency check
    expect(not metrics_from_trace(init, steps, collapsed)["ok"], "collapsed_clock_flagged")
    # 4. no diagnostic: left entry still recorded, targets flagged, record not ok
    init0, steps0 = _synthetic_trace({}, 5, [0.0, -2200.0, 0.0, 0.0, 0.0])
    rec0 = metrics_from_trace({"observation": init0["observation"]},
                              [{k: v for k, v in r.items() if k != mt.REPLY_KEY} for r in steps0],
                              {"steps": 5, "last_consumed_tick": 4, "targets_broken": 0, "cleared": False})
    expect(rec0["first_left_entry"]["consumed_tick"] == 1 and not rec0["target_diag"]["ok"] and not rec0["ok"],
           "no_diag")
    # 5. a dead fighter left of the wall is not an entry (the live filter)
    init1, steps1 = _synthetic_trace({}, 3, [0.0, -2500.0, 0.0])
    steps1[1] = {**steps1[1], "observation": {**steps1[1]["observation"], "fighter_valid": 0}}
    expect(metrics_from_trace(init1, steps1, {"steps": 3, "last_consumed_tick": 2, "targets_broken": 0})
           ["first_left_entry"] is None, "live_filter")
    print(f"m7g_eval_metrics self-test: {'PASS' if not bad else 'FAIL'} ({len(variants)} equivalence variants + 8 "
          f"record checks, {len(bad)} failed) {bad}")
    return 0 if not bad else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
