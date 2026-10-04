"""M9-g1: the reach evaluation (frozen final policy), the paired tape control, the unperturbed diagnostic, the fine grid and the tick-0 reading.

Job families (every one an episode from a fresh process; staged at its landing state by the same staging as training):

    reach         20 stochastic episodes WITH sticky actions (p = 0.25, evaluation keys) at each landing state: the decision
    reach_tape    the paired open-loop tape control (T_clear's words from the landing state) under the IDENTICAL keyed draws (same label)
    reach_det     one deterministic (argmax), unperturbed episode per landing state (reported)
    unperturbed   20 stochastic episodes WITHOUT stickiness at each landing state: the backward depth with no stickiness (decision 2; diagnostic only)
    tick0         20 stochastic sticky episodes from the ordinary tick-0 reset, and tick0_det / tick0_unperturbed (reported; a clear is a discovery)
    fine          10 stochastic sticky episodes every 25 ticks from 2,300 to 50 below the final frontier, at most 40 points (descriptive: R_fine)

Priority order (the evaluation wall cap may leave the tail undone, never the decision): reach and its tape first, from the last landing back, then the
deterministic episodes, tick 0, the unperturbed diagnostic, the fine grid. Landings below 1,248 are evaluated only if the training frontier reached them.
`aggregate` turns records into the rows the rule reads. All episodes use the TRUNK lineage (T_clear): its own words are the start state.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

import m8_rd_cells as mcell
import m9_artifacts as A
import m9_contract as C
import m9_curriculum as CU
import m9_sticky as S
import m9_vec as V

EVAL_CONTRACT = "m9_eval_v1"
TRUNK = C.TAPE_LINEAGE
KINDS = ("reach", "reach_tape", "reach_det", "unperturbed", "tick0", "tick0_det", "tick0_unperturbed", "fine", "reach_mid")


def _start(episode: int, tau: int, region: str) -> CU.Start:
    return CU.Start(int(episode), region, int(tau), TRUNK, int(tau) <= C.SHARED_PREFIX, -1)


def deeper_landings(all_starts: Sequence[int], pointer_final: int, registered: Sequence[int] = C.LANDINGS) -> List[int]:
    """Landings below the registered ones that the training frontier reached (pointer <= landing); tick 0 is evaluated separately."""
    lo = min(registered)
    return sorted((t for t in all_starts if 0 < t < lo and t >= pointer_final), reverse=True)


def landing_jobs(landings: Sequence[int], *, tape: bool, n: int = C.EVAL_EPISODES, base: int = 0) -> List[V.StartJob]:
    out: List[V.StartJob] = []
    for lam in sorted(landings, reverse=True):
        for k in range(n):
            label = S.eval_label("reach", lam, k)
            if tape:
                out.append(V.StartJob(base + len(out), _start(base + len(out), lam, "landing"), label, driver="tape", kind="reach_tape", tier=0,
                                      job_id=f"reach_tape-{lam}-{k:02d}", extra={"landing": lam, "k": k}))
            else:
                out.append(V.StartJob(base + len(out), _start(base + len(out), lam, "landing"), label, driver="policy", kind="reach", tier=0,
                                      job_id=f"reach-{lam}-{k:02d}", extra={"landing": lam, "k": k}))
    return out


def tick0_tape_jobs(n: int = C.EVAL_EPISODES) -> List[V.StartJob]:
    return [V.StartJob(k, _start(k, 0, "tick0"), S.eval_label("tick0", 0, k), driver="tape", kind="reach_tape", tier=0, job_id=f"reach_tape-0-{k:02d}",
                       extra={"landing": 0, "k": k}) for k in range(n)]


def p4_jobs(landings: Sequence[int] = C.LANDINGS, n: int = C.EVAL_EPISODES) -> List[V.StartJob]:
    """P4: the tape at the six landing states and at tick 0, 20 episodes each, with the evaluation's keys."""
    jobs = landing_jobs(landings, tape=True, n=n)
    jobs += tick0_tape_jobs(n)
    return jobs


def evaluation_jobs(landings: Sequence[int], fine_points: Sequence[int], *, tape_landings: Sequence[int] = (), n: int = C.EVAL_EPISODES,
                    tick0_n: int = C.TICK0_EPISODES, fine_n: int = C.FINE_GRID_EPISODES) -> List[V.StartJob]:
    """The evaluation phase's jobs in priority order. `landings` = the registered six plus any deeper landing the frontier reached; the tape runs here only
    for the deeper ones (P4 ran the registered six and tick 0 before training, with the same keys)."""
    jobs: List[V.StartJob] = []
    jobs += landing_jobs(landings, tape=False, n=n)
    jobs += landing_jobs(tape_landings, tape=True, n=n)
    for lam in sorted(landings, reverse=True):
        jobs.append(V.StartJob(len(jobs), _start(len(jobs), lam, "landing"), None, driver="policy", deterministic=True, kind="reach_det", tier=1,
                               job_id=f"reach_det-{lam}", extra={"landing": lam, "k": 0}))
    for k in range(tick0_n):
        jobs.append(V.StartJob(len(jobs), _start(len(jobs), 0, "tick0"), S.eval_label("tick0", 0, k), driver="policy", kind="tick0", tier=1,
                               job_id=f"tick0-{k:02d}", extra={"landing": 0, "k": k}))
    jobs.append(V.StartJob(len(jobs), _start(len(jobs), 0, "tick0"), None, driver="policy", deterministic=True, kind="tick0_det", tier=1, job_id="tick0_det",
                           extra={"landing": 0, "k": 0}))
    for lam in sorted(landings, reverse=True):
        for k in range(n):
            jobs.append(V.StartJob(len(jobs), _start(len(jobs), lam, "landing"), None, driver="policy", kind="unperturbed", tier=2, job_id=f"unperturbed-{lam}-{k:02d}",
                                   extra={"landing": lam, "k": k}))
    for k in range(tick0_n):
        jobs.append(V.StartJob(len(jobs), _start(len(jobs), 0, "tick0"), None, driver="policy", kind="tick0_unperturbed", tier=2, job_id=f"tick0_unperturbed-{k:02d}",
                               extra={"landing": 0, "k": k}))
    for tau in fine_points:
        for k in range(fine_n):
            jobs.append(V.StartJob(len(jobs), _start(len(jobs), tau, "fine"), S.eval_label("fine", tau, k), driver="policy", kind="fine", tier=3,
                                   job_id=f"fine-{tau}-{k:02d}", extra={"landing": tau, "k": k}))
    return jobs


def fine_grid(pointer_final: int, start: int = C.TAU0, step: int = C.FINE_GRID_STEP, max_points: int = C.FINE_GRID_MAX_POINTS) -> List[int]:
    """Every 25 ticks from 2,300 down to 50 below the final frontier, at most 40 points."""
    out: List[int] = []
    t = int(start)
    floor = max(0, int(pointer_final) - 50)
    while t >= floor and len(out) < max_points:
        out.append(t)
        t -= step
    return out


# -- recording and running -----------------------------------------------------------------------------------------------------------


class EvalRecorder:
    """Every evaluation or tape episode keeps its compact record and a full M4-form artifact; every clear is kept for the verification."""

    def __init__(self, run_dir: Path, tables: Mapping[str, Any], *, phase: str, now: Callable[[], float] = time.monotonic, write_artifacts: bool = True):
        self.dir = Path(run_dir)
        self.tables = tables
        self.phase = phase
        self.now = now
        self.t0 = now()
        self.write_artifacts = write_artifacts
        self.records: List[Dict[str, Any]] = []
        self.clears: List[Dict[str, Any]] = []
        self.completed: Dict[str, Dict[str, Any]] = {}

    def on_episode(self, ctx: V.EpisodeCtx, rec: Dict[str, Any]) -> None:
        j = ctx.job
        rec = dict(rec, phase=self.phase, eval_kind=j.kind, landing=j.extra.get("landing"), k=j.extra.get("k"), t_wall_s=round(self.now() - self.t0, 2))
        self.records.append(rec)
        self.completed[j.job_id] = rec
        A.append_jsonl(self.dir / "episodes.jsonl", A.stamp(rec))
        if rec["clear"]:
            self.clears.append({"id": rec["episode"], "words": ctx.words(), "online": ctx.online(ctx.final), "tau": ctx.tau, "kind": j.kind, "tier": j.tier,
                                "landing": j.extra.get("landing")})
        if self.write_artifacts:
            rows = [(*mcell.TRIPLES[w], i) for i, w in enumerate(ctx.words())]
            A.write_episode_artifact(self.dir.parent / "artifacts", rec["episode"], rows,
                                     {"lineage": ctx.lineage, "tau": ctx.tau, "kind": j.kind, "landing": j.extra.get("landing"), "k": j.extra.get("k"), "label": rec["label"],
                                      "driver": j.driver, "deterministic": j.deterministic, "sticky_mask_hex": rec["sticky_mask_hex"], "sampled_hex": rec["sampled_hex"],
                                      "native_action_digest": rec["native_action_digest"], "chain_final": rec["chain_final"], "prefix_sha256": rec["prefix_sha256"],
                                      "prefix_words": ctx.tau},
                                     status="clear" if rec["clear"] else rec["end_reason"],
                                     terminal={"end_reason": rec["end_reason"], "ticks": rec["ticks"], "targets_broken": rec["t"], "completion": rec.get("result") or {}},
                                     labels={"phase": self.phase, "m9_kind": j.kind}, preservation_reason="manual")


class EvalRunner:
    """Free-running evaluation over an arena: each parked start becomes active at once, every active episode is stepped as its reply arrives, and the
    policy is evaluated in a batch over the episodes that need an action."""

    def __init__(self, arena: V.Arena, tables: Mapping[str, Any], recorder: EvalRecorder, *, models: Optional[Mapping[str, Any]] = None,
                 now: Callable[[], float] = time.monotonic, requeue: Optional[Callable[[V.StartJob], None]] = None):
        self.arena, self.tables, self.rec, self.models, self.now = arena, tables, recorder, dict(models or {}), now
        self.tape = S.Tape(tables[TRUNK].words)
        self.stop: Optional[V.CapStop] = None
        self.requeue = requeue
        self.lifecycle_requeued = 0
        self.steps = 0

    def _decide(self, ctxs: Sequence[V.EpisodeCtx]) -> List[int]:
        words: Dict[int, int] = {}
        groups: Dict[Tuple[str, bool], List[V.EpisodeCtx]] = {}
        for c in ctxs:
            if c.job.driver == "tape":
                words[id(c)] = self.tape.word(c.tick)
            elif c.job.driver == "random":
                words[id(c)] = int(S.uniform(f"m9|g1|random|{c.job.job_id}|{c.tick}") * 72) % 72
            else:
                groups.setdefault((str(c.job.extra.get("model", "final")), bool(c.job.deterministic)), []).append(c)
        for (tag, det), grp in groups.items():
            model = self.models.get(tag)
            if model is None:
                raise RuntimeError(f"a policy episode needs the model {tag!r}")
            batch = {k: np.stack([np.asarray(c.obs[k], dtype=np.float32) for c in grp]) for k in grp[0].obs}
            acts, _ = model.predict(batch, deterministic=det)
            for c, a in zip(grp, acts):
                words[id(c)] = int(a[0]) * 8 + int(a[1])
        return [words[id(c)] for c in ctxs]

    def run(self) -> Dict[str, Any]:
        arena = self.arena
        need: List[V.EpisodeCtx] = []
        try:
            while True:
                events = arena.pump(0.02)
                for slot, kind, payload in events:
                    ctx = arena.active.get(slot)
                    if kind == "closed" or ctx is None:
                        continue
                    if kind == "stepped":
                        arena.budget.step(1)
                        self.steps += 1
                        r = ctx.apply(payload)
                        if r["terminated"] or r["truncated"]:
                            final = payload["final"]
                            ctx.final = final
                            self.rec.on_episode(ctx, ctx.record(final))
                            arena.release(slot)
                        else:
                            need.append(ctx)
                    elif kind in ("step_failed", "died"):
                        if kind == "step_failed" and payload.get("kind") == "mismatch":
                            raise V.IntegrityStop(f"an evaluation step failed an integrity check: {payload.get('mismatch')}", payload)
                        if kind == "step_failed" and payload.get("kind") == "error":
                            raise V.CapStop(f"a worker reported an error while stepping: {payload.get('error')} {str(payload.get('trace', ''))[-500:]}", valid=False)
                        if kind != "died":                          # a worker death was already counted by the arena when the event arrived
                            arena.lifecycle_failures.append({"episode": ctx.job.job_id, "outcome": payload.get("outcome", kind), "message": str(payload)[:200], "slot": slot,
                                                             "phase": "step"})
                        if len(arena.lifecycle_failures) > arena.lifecycle_limit:
                            raise V.CapStop(f"more than {arena.lifecycle_limit} lifecycle failures", valid=False)
                        arena.release(slot)
                        if kind == "died":
                            arena.state[slot] = "dead"
                        self.lifecycle_requeued += 1
                        arena.source.unget(ctx.job)
                        arena.source_done = False
                while arena.ready:
                    need.append(arena.activate(arena.ready.popleft()))
                if need:
                    batch, need = need, []
                    for c, w in zip(batch, self._decide(batch)):
                        arena.send_step(c, w)
                if not arena.active and arena.staging_count() == 0 and not arena.ready and arena.source_done:
                    break
        except V.CapStop as exc:
            self.stop = exc
        return {"stop": None if self.stop is None else {"reason": self.stop.reason, "valid": self.stop.valid}, "episodes": len(self.rec.records), "steps": self.steps,
                "ticks": {"prefix": arena.budget.prefix, "policy": arena.budget.policy, "total": arena.budget.consumed, "cap": arena.budget.cap},
                "lifecycle_requeued": self.lifecycle_requeued, "arena": arena.summary()}


# -- aggregation ------------------------------------------------------------------------------------------------------------------------


def aggregate(records: Sequence[Mapping[str, Any]], verified: Optional[Mapping[str, bool]] = None) -> Dict[str, Any]:
    """Rows for the rule. `verified` maps an episode id to the exactness of its replay (absent = not verified). Policy rows count only verified clears
    toward `verified`; `clears` is the claimed count."""
    ver = dict(verified or {})
    reach: Dict[int, Dict[str, Any]] = {}
    unp: Dict[int, Dict[str, Any]] = {}
    fine: Dict[int, Dict[str, Any]] = {}
    tick0: Dict[str, Dict[str, Any]] = {}
    det: Dict[int, Dict[str, Any]] = {}

    def row(d: Dict[Any, Dict[str, Any]], key: Any) -> Dict[str, Any]:
        return d.setdefault(key, {"n": 0, "clears": 0, "verified": 0, "tape_n": 0, "tape_clears": 0, "tape_verified": 0})

    for r in records:
        kind, lam = r["eval_kind"], r.get("landing")
        clear = bool(r["clear"])
        ok = bool(ver.get(r["episode"], False)) and clear
        if kind == "reach":
            x = row(reach, lam)
            x["n"] += 1
            x["clears"] += int(clear)
            x["verified"] += int(ok)
        elif kind == "reach_tape":
            x = row(reach, lam)
            x["tape_n"] += 1
            x["tape_clears"] += int(clear)
            x["tape_verified"] += int(ok)
        elif kind == "unperturbed":
            x = row(unp, lam)
            x["n"] += 1
            x["clears"] += int(clear)
            x["verified"] += int(ok)
        elif kind == "fine":
            x = row(fine, lam)
            x["n"] += 1
            x["clears"] += int(clear)
            x["verified"] += int(ok)
        elif kind in ("tick0", "tick0_unperturbed"):
            x = tick0.setdefault(kind, {"n": 0, "clears": 0, "verified": 0})
            x["n"] += 1
            x["clears"] += int(clear)
            x["verified"] += int(ok)
        elif kind in ("reach_det", "tick0_det"):
            det[lam if kind == "reach_det" else 0] = {"clear": clear, "end": r["end_reason"], "ticks": r["ticks"], "t": r["t"]}
    return {"reach": reach, "unperturbed": unp, "fine": fine, "tick0": tick0, "deterministic": det}


def contract_description() -> Dict[str, Any]:
    return {"contract": EVAL_CONTRACT, "kinds": list(KINDS), "episodes_per_landing": C.EVAL_EPISODES, "sticky_p": C.STICKY_P, "lineage": TRUNK,
            "fine_grid": [C.FINE_GRID_STEP, C.FINE_GRID_EPISODES, C.FINE_GRID_MAX_POINTS], "priority": "reach and tape from the last landing back, deterministic, "
            "tick 0, unperturbed, fine grid", "deeper_landings": "a landing below 1,248 is evaluated only if the final frontier is at or below it"}
