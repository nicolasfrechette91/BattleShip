"""M9-g3: the probe jobs on g3 keys, the attempt (g2's `run_attempt` with the g3 frontier, the g3 job builders and the g3 verification-pick key), the
close-audit jobs and the tape drift jobs. The runner itself (`ProbeSource`, `TestState`, `ProbeRecorder`, `ProbeRunner`) is rl/m9_g2_probe's, imported
unchanged: it is key-agnostic (every key reaches it through a job's `extra["akey"]` and label).

Reading (decisions record R-probe): `rl/m9_g2_probe.run_attempt` cannot take the g3 frontier unchanged, because it builds its jobs through module-level
functions on g2 keys and picks its verification clears with the g2 key; it is copied here with those four references changed and nothing else.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import m9_artifacts as A
import m9_curriculum as CU
import m9_g2_arena as AR
import m9_g2_policy as PO
import m9_g2_probe as PR2
import m9_g2_tape as TP
import m9_g3_contract as G
import m9_g3_frontier as F
import m9_sticky as S
import m9_vec as V

PROBE_CONTRACT = "m9_g3_probe_v1"
ProbeSource = PR2.ProbeSource
TestState = PR2.TestState
ProbeRecorder = PR2.ProbeRecorder
ProbeRunner = PR2.ProbeRunner


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
    """The close audit in priority order: sticky at the audited landings (interleaved by k; the sticky labels are the reused tape's `m9|g2|reach` family so the
    episodes pair with it), tick 0 sticky, unperturbed, deterministic, tick-0 deterministic. Action keys are g3's."""
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


def drift_jobs(landing: int = G.DRIFT_LANDING, n: int = G.DRIFT_KEYS) -> List[V.StartJob]:
    """The drift check of the reused tape: the first n tape keys at the landing, on the reused table's own labels (g2's `drift_jobs`, unchanged)."""
    return TP.drift_jobs(landing, n)


# -- the attempt ---------------------------------------------------------------------------------------------------------------------------


def run_attempt(*, frontier: F.Frontier, train_arena: AR.G2Arena, pool: Any, tables: Mapping[str, Any], train_budget: AR.G2TickBudget, lengths: Mapping[str, int],
                snapshot: Callable[[Path], Dict[str, Any]], make_policy: Callable[[Path, str], Any], attempt_root: Path, probes_jsonl: Path, attempts_jsonl: Path, withdrawn_jsonl: Path,
                now: Callable[[], float], guard: Callable[[], None], log: Callable[[str], None], episodes_before: int, num_timesteps: int, artifacts_root: Optional[Path] = None,
                flatten: Callable[[Mapping[str, Any]], Any] = PO.flatten_obs) -> Dict[str, Any]:
    """One attempt at the current pointer (g2 decisions R3-R6 under the g3 frontier). Returns the attempt record; raises what the probes raise (a cap, an
    integrity stop) after recording the attempt as INTERRUPTED and settling the slots. Refused by the frontier inside its spacing."""
    t0 = now()
    rec = frontier.begin_attempt(episodes_before=episodes_before)
    pointer, a = int(rec["pointer"]), int(rec["a"])
    rec.update({"num_timesteps": int(num_timesteps), "t_start_s": round(t0, 2)})
    log(f"attempt {rec['n']} (a = {a}) at pointer {pointer}: trigger {rec['trigger'].get('clears')} of {rec['trigger'].get('clears', 0) + rec['trigger'].get('non_clears', 0)}; spacing {rec['spacing']}")
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
                f"{ {k: (t.clears, t.non_clears) for k, t in recheck_states.items()} }) -> pointer {frontier.pointer}; spacing {frontier.spacing_state()}")
    return rec


def _verification_picks(rec: Mapping[str, Any], clears: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """One keyed clear per passed test (g2 decision 8, g3 decision 10): index = floor(u * n) over that test's clears in record order, on the g3 key."""
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
    return dict(PR2.contract_description(), contract=PROBE_CONTRACT, runner="rl/m9_g2_probe (unchanged)", keys={k: G.KEYS[k] for k in ("probe_label", "probe_action", "reach_label", "audit_action", "verify_pick")},
                drift={"landing": G.DRIFT_LANDING, "keys": G.DRIFT_KEYS, "labels": G.KEYS["reach_label"]})
