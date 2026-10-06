"""M9-g2: the probe runner (frozen-snapshot tests on a slot subset, curtailed), the attempt (the pause, the strip test, the re-checks, the move), the
T0 tape and the close audit on the same runner.

The runner is g1's free-running evaluation loop (rl/m9_eval.EvalRunner) over a `G2Arena`, with three additions: a test state per PART (the strip, or one
landing) that passes at the 10th clear and fails at the 11th non-clear, cancellation of a decided part's remaining episodes (staged, parked or active:
closed and recorded as abandoned), and a decision function that samples the frozen policy by keyed inverse CDF (`rl/m9_g2_policy.FrozenPolicy.sample_word`
on `<action key prefix>|<tick>`) or replays the open-loop tape by tick index. Every record goes through the metadata-enforcing writers.

`run_attempt` is decision R3-R6: training's four playing slots stay parked; the six preparing slots are drained, their parked starts withdrawn and recorded,
the current weights frozen to disk (the digest recorded), the strip test run, then every landing behind the frontier re-checked in parallel (fail fast), the
frontier updated, the slots handed back settled. Probe transitions never enter PPO; the attempt's native ticks are charged to the training budget.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import m8_rd_cells as mcell
import m9_artifacts as A
import m9_curriculum as CU
import m9_g2_arena as AR
import m9_g2_contract as G
import m9_g2_frontier as F
import m9_g2_policy as PO
import m9_sticky as S
import m9_vec as V

PROBE_CONTRACT = "m9_g2_probe_v1"


# -- jobs ------------------------------------------------------------------------------------------------------------------------------


def _start(i: int, tau: int, lineage: str, region: str) -> CU.Start:
    return CU.Start(int(i), region, int(tau), lineage, int(tau) <= G.SHARED_PREFIX, -1)


def strip_jobs(pointer: int, a: int, lengths: Mapping[str, int], n: int = G.TEST_EPISODES) -> List[V.StartJob]:
    jobs: List[V.StartJob] = []
    for k in range(n):
        tau, lineage, _shared = F.strip_start(pointer, a, k, lengths)
        jobs.append(V.StartJob(k, _start(k, tau, lineage, "probe_strip"), G.probe_label(pointer, a, "strip", k), driver="policy", kind="probe_strip", tier=0,
                               job_id=f"probe-{int(pointer)}-{int(a)}-strip-{k:02d}", extra={"part": "strip", "k": k, "pointer": int(pointer), "a": int(a), "landing": None,
                                                                                            "akey": G.probe_action_key(pointer, a, "strip", k, 0)[:-2]}))
    return jobs


def recheck_jobs(pointer: int, a: int, landings: Sequence[int], n: int = G.TEST_EPISODES) -> List[V.StartJob]:
    """Every landing's test, interleaved by k so that the landings progress in parallel."""
    jobs: List[V.StartJob] = []
    for k in range(n):
        for lam in sorted(landings, reverse=True):
            jobs.append(V.StartJob(len(jobs), _start(len(jobs), lam, G.TRUNK, "probe_landing"), G.probe_label(pointer, a, lam, k), driver="policy", kind="probe_recheck", tier=0,
                                   job_id=f"probe-{int(pointer)}-{int(a)}-{int(lam)}-{k:02d}", extra={"part": int(lam), "k": k, "pointer": int(pointer), "a": int(a), "landing": int(lam),
                                                                                                    "akey": G.probe_action_key(pointer, a, lam, k, 0)[:-2]}))
    return jobs


def audit_jobs(landings: Sequence[int], *, n: int = G.AUDIT_EPISODES, n_unp: int = G.AUDIT_UNPERTURBED, n_det: int = G.AUDIT_DETERMINISTIC, tick0_n: int = G.TICK0_EPISODES) -> List[V.StartJob]:
    """The close audit in priority order: sticky at the audited landings (interleaved by k), tick 0 sticky, unperturbed, deterministic, tick-0 deterministic."""
    jobs: List[V.StartJob] = []

    def add(**kw: Any) -> None:
        tau = kw.pop("tau_")
        jobs.append(V.StartJob(len(jobs), _start(len(jobs), tau, G.TRUNK, "audit"), **kw))

    lams = sorted(landings, reverse=True)
    for k in range(n):
        for lam in lams:
            add(tau_=lam, label=G.reach_label(lam, k), driver="policy", kind="audit_sticky", tier=0, job_id=f"audit_sticky-{lam}-{k:02d}",
                extra={"part": f"sticky:{lam}", "landing": lam, "k": k, "mode": "sticky", "akey": G.audit_action_key("sticky", lam, k, 0)[:-2]})
    for k in range(tick0_n):
        add(tau_=0, label=G.tick0_label(k), driver="policy", kind="tick0_sticky", tier=1, job_id=f"tick0_sticky-{k:02d}",
            extra={"part": "tick0", "landing": 0, "k": k, "mode": "sticky", "akey": G.audit_action_key("sticky", 0, k, 0)[:-2]})
    for k in range(n_unp):
        for lam in lams:
            add(tau_=lam, label=None, driver="policy", kind="audit_unperturbed", tier=2, job_id=f"audit_unperturbed-{lam}-{k:02d}",
                extra={"part": f"unperturbed:{lam}", "landing": lam, "k": k, "mode": "unperturbed", "akey": G.audit_action_key("unperturbed", lam, k, 0)[:-2]})
    for k in range(n_det):
        for lam in lams:
            add(tau_=lam, label=None, driver="policy", deterministic=True, kind="audit_det", tier=3, job_id=f"audit_det-{lam}-{k:02d}",
                extra={"part": f"det:{lam}", "landing": lam, "k": k, "mode": None, "akey": None})
        add(tau_=0, label=None, driver="policy", deterministic=True, kind="tick0_det", tier=3, job_id=f"tick0_det-{k:02d}", extra={"part": "tick0_det", "landing": 0, "k": k, "mode": None, "akey": None})
    return jobs


# -- the source with cancellation ---------------------------------------------------------------------------------------------------


class ProbeSource:
    """A fixed list in priority order; a cancelled part's remaining jobs are skipped; a job whose staging died is staged again with the same id (g1's F1)."""

    requeue_on_lifecycle = True

    def __init__(self, jobs: Sequence[V.StartJob]):
        self.jobs = list(jobs)
        self.i = 0
        self._back: List[V.StartJob] = []
        self.cancelled: set = set()
        self.skipped: List[str] = []

    def cancel(self, part: Any) -> None:
        self.cancelled.add(part)

    def next_job(self, arena: Any) -> Optional[V.StartJob]:
        while self._back:
            j = self._back.pop()
            if j.extra.get("part") in self.cancelled:
                self.skipped.append(j.job_id)
                continue
            return j
        while self.i < len(self.jobs):
            j = self.jobs[self.i]
            self.i += 1
            if j.extra.get("part") in self.cancelled:
                self.skipped.append(j.job_id)
                continue
            return j
        return None

    def unget(self, job: V.StartJob) -> None:
        self._back.append(job)

    def remaining(self) -> int:
        return len(self.jobs) - self.i + len(self._back)


class TestState:
    """One curtailed test: pass at the 10th clear, fail at the 11th non-clear."""

    def __init__(self, part: Any, *, pass_at: int = G.TEST_PASS, fail_at: int = G.TEST_FAIL_NONCLEARS, episodes: int = G.TEST_EPISODES):
        self.part, self.pass_at, self.fail_at, self.episodes = part, int(pass_at), int(fail_at), int(episodes)
        self.clears = 0
        self.non_clears = 0
        self.decided: Optional[str] = None
        self.outcomes: List[str] = []
        self.returns: List[float] = []
        self.start_values: List[float] = []
        self.start_entropies: List[float] = []
        self.abandoned: List[Dict[str, Any]] = []

    def record(self, cleared: bool, ret: float, stats: Optional[Mapping[str, Any]]) -> Optional[str]:
        self.outcomes.append("c" if cleared else "x")
        self.returns.append(float(ret))
        if stats:
            self.start_values.append(float(stats.get("v", 0.0)))
            self.start_entropies.append(float(stats.get("h", 0.0)))
        self.clears += int(bool(cleared))
        self.non_clears += int(not cleared)
        if self.decided is None:
            if self.clears >= self.pass_at:
                self.decided = "passed"
            elif self.non_clears >= self.fail_at:
                self.decided = "failed"
        return self.decided

    @property
    def passed(self) -> bool:
        return self.decided == "passed"

    def to_json(self) -> Dict[str, Any]:
        n = len(self.returns)
        mv = sum(self.start_values) / len(self.start_values) if self.start_values else None
        mr = sum(self.returns) / n if n else None
        return {"part": self.part, "clears": self.clears, "non_clears": self.non_clears, "episodes": n, "decided": self.decided, "passed": self.passed, "outcomes": "".join(self.outcomes),
                "mean_return": round(mr, 4) if mr is not None else None, "mean_start_value": round(mv, 4) if mv is not None else None,
                "calibration_gap": round(mv - mr, 4) if (mv is not None and mr is not None) else None,
                "mean_start_entropy": round(sum(self.start_entropies) / len(self.start_entropies), 4) if self.start_entropies else None, "abandoned": list(self.abandoned)}


# -- the recorder ---------------------------------------------------------------------------------------------------------------------


class ProbeRecorder:
    def __init__(self, jsonl: Path, *, phase: str, now: Callable[[], float] = time.monotonic, extra: Optional[Mapping[str, Any]] = None, artifacts_root: Optional[Path] = None,
                 artifacts_for: str = "clears", tables: Optional[Mapping[str, Any]] = None):
        self.path = Path(jsonl)
        self.phase, self.now, self.t0 = phase, now, now()
        self.extra = dict(extra or {})
        self.artifacts_root = Path(artifacts_root) if artifacts_root is not None else None
        self.artifacts_for = artifacts_for
        self.tables = tables
        self.records: List[Dict[str, Any]] = []
        self.clears: List[Dict[str, Any]] = []
        self.start_stats: Dict[str, Dict[str, Any]] = {}

    def on_episode(self, ctx: V.EpisodeCtx, rec: Dict[str, Any]) -> Dict[str, Any]:
        j = ctx.job
        st = self.start_stats.get(j.job_id) or {}
        row = dict(rec, phase=self.phase, eval_kind=j.kind, part=j.extra.get("part"), landing=j.extra.get("landing"), k=j.extra.get("k"), mode=j.extra.get("mode"),
                   start_value=st.get("v"), start_entropy=st.get("h"), start_top_word_p=st.get("top_word_p"), t_wall_s=round(self.now() - self.t0, 2), **self.extra)
        self.records.append(row)
        A.append_jsonl(self.path, A.stamp(row))
        if rec["clear"]:
            self.clears.append({"id": rec["episode"], "words": ctx.words(), "online": ctx.online(ctx.final), "tau": ctx.tau, "kind": j.kind, "tier": j.tier, "part": j.extra.get("part"),
                                "landing": j.extra.get("landing"), "k": j.extra.get("k")})
        if self.artifacts_root is not None and (self.artifacts_for == "all" or rec["clear"]):
            rows = [(*mcell.TRIPLES[w], i) for i, w in enumerate(ctx.words())]
            A.write_episode_artifact(self.artifacts_root, rec["episode"], rows,
                                     {"lineage": ctx.lineage, "tau": ctx.tau, "kind": j.kind, "part": j.extra.get("part"), "landing": j.extra.get("landing"), "k": j.extra.get("k"),
                                      "label": rec["label"], "driver": j.driver, "deterministic": j.deterministic, "sticky_mask_hex": rec["sticky_mask_hex"], "sampled_hex": rec["sampled_hex"],
                                      "native_action_digest": rec["native_action_digest"], "chain_final": rec["chain_final"], "prefix_sha256": rec["prefix_sha256"], "prefix_words": ctx.tau, **self.extra},
                                     status="clear" if rec["clear"] else rec["end_reason"],
                                     terminal={"end_reason": rec["end_reason"], "ticks": rec["ticks"], "targets_broken": rec["t"], "completion": rec.get("result") or {}},
                                     labels={"phase": self.phase, "m9_kind": j.kind}, preservation_reason="manual")
        return row


# -- the runner -----------------------------------------------------------------------------------------------------------------------


class ProbeRunner:
    """Free-running episodes over a G2Arena. `policy` has stats / argmax_word / sample_word (rl/m9_g2_policy.FrozenPolicy or the synthetic stand-in);
    `tests` maps a part to its TestState (None = no curtailment: T0, the close audit); `fail_fast` cancels every part when one fails (the re-checks)."""

    def __init__(self, arena: AR.G2Arena, tables: Mapping[str, Any], recorder: ProbeRecorder, *, policy: Any = None, tests: Optional[Mapping[Any, TestState]] = None, fail_fast: bool = False,
                 now: Callable[[], float] = time.monotonic, flatten: Callable[[Mapping[str, Any]], Any] = PO.flatten_obs):
        self.arena, self.tables, self.rec, self.policy, self.now, self.flatten = arena, tables, recorder, policy, now, flatten
        self.tape = S.Tape(tables[G.TRUNK].words)
        self.tests = dict(tests) if tests is not None else None
        self.fail_fast = fail_fast
        self.stop: Optional[V.CapStop] = None
        self.steps = 0
        self.lifecycle_requeued = 0
        self.late_steps = 0
        self.abandoned: List[Dict[str, Any]] = []

    def _decide(self, ctxs: Sequence[V.EpisodeCtx]) -> List[int]:
        out: List[int] = []
        for c in ctxs:
            j = c.job
            if j.driver == "tape":
                out.append(self.tape.word(c.tick))
                continue
            if j.driver != "policy":
                raise RuntimeError(f"unexpected driver {j.driver!r}")
            if self.policy is None:
                raise RuntimeError("a policy episode needs a policy")
            flat = self.flatten(c.obs)
            if not c.sub:
                self.rec.start_stats[j.job_id] = dict(self.policy.stats(flat))
            if j.deterministic:
                out.append(int(self.policy.argmax_word(flat)))
            else:
                out.append(int(self.policy.sample_word(flat, f"{j.extra['akey']}|{c.tick}")))
        return out

    def _cancel(self, part: Any, why: str) -> None:
        arena = self.arena
        src: ProbeSource = arena.source                              # type: ignore[assignment]
        src.cancel(part)
        for slot in list(arena.slots):
            job = arena.job[slot]
            if job is None or job.extra.get("part") != part or arena.state[slot] not in ("ready", "active"):
                continue
            ctx = arena.active.get(slot)
            rec = {"episode": job.job_id, "part": part, "k": job.extra.get("k"), "state": arena.state[slot], "policy_ticks": len(ctx.sub) if ctx else 0, "why": why}
            self.abandoned.append(rec)
            if self.tests is not None and part in self.tests:
                self.tests[part].abandoned.append(rec)
            arena.close_slot(slot)
        # a start still staging for a cancelled part is closed when it becomes ready (the staged reply is consumed first)

    def _all_decided(self) -> bool:
        return self.tests is not None and all(t.decided is not None for t in self.tests.values())

    def _after_outcome(self, part: Any, decided: Optional[str]) -> None:
        if decided is None:
            return
        if decided == "failed" and self.fail_fast:
            for p, t in self.tests.items():                          # type: ignore[union-attr]
                if t.decided is None:
                    t.decided = "cancelled"
                self._cancel(p, "fail_fast")
        else:
            self._cancel(part, decided)

    def run(self) -> Dict[str, Any]:
        arena = self.arena
        need: List[V.EpisodeCtx] = []
        try:
            while True:
                events = arena.pump(0.02)
                for slot, kind, payload in events:
                    ctx = arena.active.get(slot)
                    if kind == "closed":
                        continue
                    if ctx is None:
                        if kind == "stepped":
                            arena.budget.step(1)                     # the late reply of an abandoned episode: its tick is consumed
                            self.late_steps += 1
                        continue
                    if kind == "stepped":
                        arena.budget.step(1)
                        self.steps += 1
                        r = ctx.apply(payload)
                        if r["terminated"] or r["truncated"]:
                            final = payload["final"]
                            ctx.final = final
                            row = self.rec.on_episode(ctx, ctx.record(final))
                            arena.release(slot)
                            part = ctx.job.extra.get("part")
                            if self.tests is not None and part in self.tests:
                                decided = self.tests[part].record(bool(row["clear"]), float(row["return"]), self.rec.start_stats.get(ctx.job.job_id))
                                self._after_outcome(part, decided)
                        else:
                            need.append(ctx)
                    elif kind in ("step_failed", "died"):
                        if kind == "step_failed" and payload.get("kind") == "mismatch":
                            raise V.IntegrityStop(f"a probe step failed an integrity check: {payload.get('mismatch')}", payload)
                        if kind == "step_failed" and payload.get("kind") == "error":
                            raise V.CapStop(f"a worker reported an error while stepping a probe: {payload.get('error')} {str(payload.get('trace', ''))[-500:]}", valid=False)
                        if kind != "died":
                            arena.lifecycle_failures.append({"episode": ctx.job.job_id, "outcome": payload.get("outcome", kind), "message": str(payload)[:200], "slot": slot, "phase": "probe_step"})
                        if len(arena.lifecycle_failures) > arena.lifecycle_limit:
                            raise V.CapStop(f"more than {arena.lifecycle_limit} lifecycle failures in an attempt", valid=False)
                        arena.release(slot)
                        if kind == "died":
                            arena.state[slot] = "dead"
                        self.lifecycle_requeued += 1
                        arena.source.unget(ctx.job)
                        arena.source_done = False
                    else:
                        raise RuntimeError(f"unexpected event {kind} from slot {slot}")
                while arena.ready:
                    slot = arena.ready.popleft()
                    job = arena.job[slot]
                    if job is not None and getattr(arena.source, "cancelled", None) and job.extra.get("part") in arena.source.cancelled:
                        rec = {"episode": job.job_id, "part": job.extra.get("part"), "k": job.extra.get("k"), "state": "ready", "policy_ticks": 0, "why": "cancelled_after_staging"}
                        self.abandoned.append(rec)
                        if self.tests is not None and job.extra.get("part") in self.tests:
                            self.tests[job.extra["part"]].abandoned.append(rec)
                        arena.close_slot(slot)
                        continue
                    need.append(arena.activate(slot))
                if need:
                    batch, need = need, []
                    for c, w in zip(batch, self._decide(batch)):
                        arena.send_step(c, w)
                if self._all_decided() and not arena.active and arena.staging_count() == 0 and not arena.ready:
                    break                                            # every part decided; stages of cancelled parts were allowed to finish (their prefix ticks count)
                if not arena.active and arena.staging_count() == 0 and not arena.ready and arena.source_done:
                    break
        except V.CapStop as exc:
            self.stop = exc
        finally:
            arena.close_unfinished()
        return {"stop": None if self.stop is None else {"reason": self.stop.reason, "valid": self.stop.valid}, "episodes": len(self.rec.records), "steps": self.steps,
                "late_steps": self.late_steps, "ticks": {"prefix": arena.budget.prefix, "policy": arena.budget.policy, "total": arena.budget.consumed, "cap": arena.budget.cap},
                "lifecycle_requeued": self.lifecycle_requeued, "abandoned": len(self.abandoned), "arena": arena.summary(),
                "tests": {str(p): t.to_json() for p, t in (self.tests or {}).items()}}


# -- the attempt ---------------------------------------------------------------------------------------------------------------------------


def run_attempt(*, frontier: F.Frontier, train_arena: AR.G2Arena, pool: Any, tables: Mapping[str, Any], train_budget: AR.G2TickBudget, lengths: Mapping[str, int],
                snapshot: Callable[[Path], Dict[str, Any]], make_policy: Callable[[Path, str], Any], attempt_root: Path, probes_jsonl: Path, attempts_jsonl: Path, withdrawn_jsonl: Path,
                now: Callable[[], float], guard: Callable[[], None], log: Callable[[str], None], episodes_before: int, num_timesteps: int, artifacts_root: Optional[Path] = None,
                flatten: Callable[[Mapping[str, Any]], Any] = PO.flatten_obs) -> Dict[str, Any]:
    """One attempt at the current pointer (decision R3-R6). Returns the attempt record; raises what the probes raise (a cap, an integrity stop) after
    recording the attempt as INTERRUPTED and settling the slots."""
    t0 = now()
    rec = frontier.begin_attempt(episodes_before=episodes_before)
    pointer, a = int(rec["pointer"]), int(rec["a"])
    rec.update({"num_timesteps": int(num_timesteps), "t_start_s": round(t0, 2)})
    log(f"attempt {rec['n']} (a = {a}) at pointer {pointer}: trigger {rec['trigger'].get('clears')} of {rec['trigger'].get('clears', 0) + rec['trigger'].get('non_clears', 0)}")
    # 1. pause: drain the staging slots, withdraw the parked starts, settle
    train_arena.paused = True
    train_arena.drain_staging()
    withdrawn = train_arena.withdraw_parked("attempt", {"attempt": rec["n"], "pointer": pointer})
    train_arena.wait_settled()
    for w in withdrawn:
        A.append_jsonl(withdrawn_jsonl, A.stamp(w))
    probe_slots = [s for s in train_arena.slots if train_arena.state[s] == "idle" and pool.alive(s)]
    parked = [s for s in train_arena.slots if train_arena.state[s] == "active"]
    rec.update({"withdrawn": len(withdrawn), "probe_slots": probe_slots, "parked_slots": parked})
    if len(probe_slots) < 1:
        raise V.CapStop("no live slot is free for the attempt", valid=False)
    # 2. the frozen snapshot
    adir = Path(attempt_root) / f"a{rec['n']:03d}"
    adir.mkdir(parents=True, exist_ok=True)
    snap = snapshot(adir / "snapshot_policy.pth")
    rec["snapshot"] = dict(snap)
    policy = make_policy(Path(snap["path"]), str(snap["sha256"]))
    strip_state = TestState("strip")
    recheck_states: Dict[int, TestState] = {}
    result = "INTERRUPTED"
    failed_landing: Optional[int] = None
    runs: List[Dict[str, Any]] = []
    extra = {"attempt": rec["n"], "a": a, "pointer": pointer, "session": frontier.session}
    recorder = ProbeRecorder(probes_jsonl, phase="probe", now=now, extra=extra, artifacts_root=artifacts_root, artifacts_for="clears")
    probe_arena: Optional[AR.G2Arena] = None

    def arena_for(jobs: Sequence[V.StartJob]) -> AR.G2Arena:
        remaining = max(0, train_budget.cap - train_budget.total())
        return AR.G2Arena(pool, tables, ProbeSource(jobs), AR.G2TickBudget(remaining), slots=probe_slots, now=now, guard=guard, lifecycle_limit=G.PROBE_LIFECYCLE_LIMIT, log=log)

    try:
        # 3. the strip test
        probe_arena = arena_for(strip_jobs(pointer, a, lengths))
        runner = ProbeRunner(probe_arena, tables, recorder, policy=policy, tests={"strip": strip_state}, now=now, flatten=flatten)
        res = runner.run()
        runs.append(dict(res, part="strip"))
        probe_arena.wait_settled()
        train_budget.charge_probe(probe_arena.budget.prefix, probe_arena.budget.policy)
        if res["stop"] is not None:
            raise V.CapStop(res["stop"]["reason"], valid=res["stop"]["valid"])
        if not strip_state.passed:
            result = "FAILED_STRIP"
        else:
            # 4. the re-checks, in parallel, fail fast
            lams = F.landings_behind(pointer, frontier.landings)
            if lams:
                recheck_states = {lam: TestState(lam) for lam in lams}
                probe_arena = arena_for(recheck_jobs(pointer, a, lams))
                runner = ProbeRunner(probe_arena, tables, recorder, policy=policy, tests=recheck_states, fail_fast=True, now=now, flatten=flatten)
                res = runner.run()
                runs.append(dict(res, part="rechecks"))
                probe_arena.wait_settled()
                train_budget.charge_probe(probe_arena.budget.prefix, probe_arena.budget.policy)
                if res["stop"] is not None:
                    raise V.CapStop(res["stop"]["reason"], valid=res["stop"]["valid"])
                failed = [lam for lam, t in recheck_states.items() if t.decided != "passed"]
                if failed:
                    failed_landing = max(lam for lam in failed if recheck_states[lam].decided == "failed") if any(recheck_states[lam].decided == "failed" for lam in failed) else max(failed)
                    result = "BLOCKED_BY_RECHECK"
                else:
                    result = "MOVED"
            else:
                result = "MOVED"
    finally:
        try:
            if probe_arena is not None:
                probe_arena.close_unfinished()
                probe_arena.wait_settled(use_guard=False, max_wall_s=120.0)
                if result == "INTERRUPTED":
                    train_budget.charge_probe(probe_arena.budget.prefix, probe_arena.budget.policy)
        finally:
            train_arena.paused = False
            frontier.finish_attempt(rec, result, strip=strip_state.to_json(), rechecks={lam: t.to_json() for lam, t in recheck_states.items()}, failed_landing=failed_landing)
            rec.update({"runs": runs, "wall_s": round(now() - t0, 2), "probe_episodes": len(recorder.records), "probe_clears": len(recorder.clears), "policy_decisions": getattr(policy, "decisions", None)})
            rec["clears_for_verification"] = _verification_picks(rec, recorder.clears)
            A.append_jsonl(attempts_jsonl, A.stamp({k: v for k, v in rec.items() if k != "clears_for_verification"}))
            log(f"attempt {rec['n']}: {result} (strip {strip_state.clears}/{strip_state.clears + strip_state.non_clears}; rechecks "
                f"{ {k: (t.clears, t.non_clears) for k, t in recheck_states.items()} }) -> pointer {frontier.pointer}; held {frontier.held()}; stalled {frontier.stalled}")
    return rec


def _verification_picks(rec: Mapping[str, Any], clears: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """One keyed clear per passed test (decision 8): index = floor(u * n) over that test's clears in record order."""
    picks: List[Dict[str, Any]] = []
    parts: List[Any] = []
    if rec.get("strip_passed"):
        parts.append("strip")
    for lam_s, t in dict(rec.get("rechecks") or {}).items():
        if t.get("passed"):
            parts.append(int(lam_s))
    for part in parts:
        mine = [c for c in clears if c.get("part") == part]
        if not mine:
            continue
        u = S.uniform(G.verify_pick_key(rec["pointer"], rec["a"], part))
        c = mine[min(len(mine) - 1, int(u * len(mine)))]
        picks.append(dict(c, pick_of=len(mine)))
    return picks


def contract_description() -> Dict[str, Any]:
    return {"contract": PROBE_CONTRACT, "test": {"episodes": G.TEST_EPISODES, "pass": G.TEST_PASS, "fail_nonclears": G.TEST_FAIL_NONCLEARS}, "rechecks": "parallel, fail fast",
            "cancellation": "a decided part's remaining episodes are closed and recorded as abandoned", "sampling": "keyed inverse CDF on <akey>|<tick>; argmax for deterministic",
            "tape": "T_clear words by tick index, neutral after the end"}
