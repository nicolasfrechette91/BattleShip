"""M9-g1: exact replay verification (pure given a replay function; standard library only).

A claim is a clear, and a counted clear is verified by a fresh-process replay of the COMPLETE canonical words from tick 0 (the lineage
prefix, then the submitted policy-phase words: the replay re-draws nothing). `evaluate_trace` compares the replay's raw replies with the
online record of the episode, and with the registered facts for a lineage:

    native action digest of the words      every consumed tick 0..n-1 and every input tick i + 1 (a contiguous, fresh episode)
    break table                            the replay analyser's table equals the online one after the handover
    chain digest                           the per-tick record chain at the last tick equals the online chain (the whole state, every tick)
    end observation                        equal in every field but host_frame
    for a clear                            the four clear facts (end reason clear, native outcome clear, ten targets, completion clocks) and
                                           both completion clocks, never collapsed, equal to the online result's

An inexact replay of a counted clear is INVALID (never merely uncounted). `run_plan` runs a priority-ordered list of replays on a
bounded thread pool under a tick cap and a wall cap; what the caps leave unverified is reported, never assumed.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import m8_rd_cells as mcell
import m8_rd_claims as mclaims

VERIFY_CONTRACT = "m9_verify_v1"
Analyser = Callable[[Mapping[str, Any], Sequence[Mapping[str, Any]]], Mapping[str, Any]]
ReplayFn = Callable[[bytes, str, int], Dict[str, Any]]           # (words, label, thread slot) -> a trace in the rl/m7f_trace format


def trace_chain(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> List[bytes]:
    """chain[0] = the tick-0 chain digest, chain[i + 1] = the chain digest after the reply of consumed tick i."""
    h = mcell.chain_start(mcell.tick0_record(initial))
    out = [h]
    for s in steps:
        h = mcell.chain_next(h, mcell.record_digest(mcell.record_of(s)))
        out.append(h)
    return out


def record_digests(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> List[bytes]:
    return [mcell.record_digest(mcell.record_of(s)) for s in steps]


def evaluate_trace(trace: Mapping[str, Any], words: bytes, analyse: Analyser, *, online: Optional[Mapping[str, Any]] = None,
                   tau: int = 0, expect_clear: bool = False) -> Dict[str, Any]:
    """Evaluate one replay of `words` against the online record (see the module docstring). `exact` is False on any problem."""
    words = bytes(words)
    problems: List[str] = []
    steps = list(trace.get("steps") or [])
    initial = trace["initial"]
    n = len(steps)
    if trace.get("consumed_tick_mismatch") is not None:
        problems.append(f"consumed_tick mismatch {trace['consumed_tick_mismatch']}")
    if n != len(words):
        problems.append(f"{n} replies for {len(words)} words (the replay ended early or took fewer words)")
    if trace.get("unsent"):
        problems.append(f"{trace['unsent']} word(s) not submitted")
    want_digest = mcell.words_digest(words[:n])
    if trace.get("action_digest") != want_digest:
        problems.append("native action digest differs from the words")
    for i, r in enumerate(steps):
        if int(r["consumed_tick"]) != i or int(r["observation"]["input_tick"]) != i + 1:
            problems.append(f"tick {i}: consumed {r['consumed_tick']} input_tick {r['observation']['input_tick']}")
            break
    an = analyse(initial, steps)
    replay_breaks = sorted((int(t) + 1, int(i)) for i, t in an["breaks"])
    facts = mclaims.clear_facts(trace, len(replay_breaks))
    out: Dict[str, Any] = {"exact": False, "problems": problems, "words": len(words), "ticks": n, "native_action_digest": trace.get("action_digest"),
                           "breaks": [list(b) for b in replay_breaks], "t": len(replay_breaks), "clear": bool(facts["all"]), "clear_facts": facts,
                           "completion_time_passed": facts.get("completion_time_passed"), "completion_input_tick": facts.get("completion_input_tick"),
                           "chain_final": None, "final_state": trace.get("final_state")}
    if steps:
        chain = trace_chain(initial, steps)
        out["chain_final"] = chain[-1].hex()
    if online is not None:
        after = [(j, i) for j, i in replay_breaks if j > tau]
        want_breaks = sorted((int(j), int(i)) for j, i in online.get("breaks", []))
        if after != want_breaks:
            problems.append(f"break table after the handover differs: replay {after[:6]} online {want_breaks[:6]}")
        if online.get("chain_final") and out["chain_final"] != online["chain_final"]:
            problems.append("chain digest at the last tick differs from the online chain")
        if online.get("end_obs") is not None and steps:
            diffs = mcell.obs_diffs(mcell.obs_tuple(steps[-1]["observation"]), tuple(online["end_obs"]))
            if diffs:
                problems.append(f"end observation differs: {sorted(diffs)[:6]}")
        if online.get("native_action_digest") and online["native_action_digest"] != trace.get("action_digest"):
            problems.append("native action digest differs from the online episode's")
        if online.get("end_reason") == "clear" or expect_clear:
            if not facts["all"]:
                problems.append(f"the claimed clear does not hold: {facts}")
            res = online.get("result") or {}
            if res:
                if res.get("completion_time_passed") != facts.get("completion_time_passed") or res.get("completion_input_tick") != facts.get("completion_input_tick"):
                    problems.append("completion clocks differ from the online result")
            if facts.get("completion_input_tick") is not None and facts.get("completion_time_passed") is not None \
                    and facts["completion_input_tick"] == facts["completion_time_passed"]:
                problems.append("the two completion clocks collapsed into one value")
    elif expect_clear and not facts["all"]:
        problems.append(f"the expected clear does not hold: {facts}")
    out["exact"] = not problems
    return out


# -- the plan -------------------------------------------------------------------------------------------------------------------


class VerifyJob:
    def __init__(self, job_id: str, words: bytes, online: Mapping[str, Any], *, tau: int, tier: int, group: str, meta: Optional[Mapping[str, Any]] = None):
        self.id, self.words, self.online, self.tau, self.tier, self.group = job_id, bytes(words), dict(online), int(tau), int(tier), group
        self.meta = dict(meta or {})


def run_plan(jobs: Sequence[VerifyJob], replay: ReplayFn, analyse: Analyser, *, tick_cap: int, wall_cap_s: float, threads: int,
             now: Callable[[], float] = time.monotonic, on_result: Optional[Callable[[VerifyJob, Mapping[str, Any]], None]] = None,
             check: Optional[Callable[[], None]] = None) -> Dict[str, Any]:
    """Run the replays in (tier, input order) on `threads` workers. A job is launched only if its words fit the remaining tick budget
    (reserved at launch) and the wall cap has not passed; the rest is reported as unverified. Every result is passed to `on_result`."""
    ordered = sorted(enumerate(jobs), key=lambda p: (p[1].tier, p[0]))
    t0 = now()
    lock = threading.Lock()
    used = 0
    results: Dict[str, Dict[str, Any]] = {}
    skipped: List[str] = []
    errors: List[Dict[str, Any]] = []
    free_slots = list(range(threads))
    futures: Dict[Future, Tuple[VerifyJob, int]] = {}

    def work(job: VerifyJob, slot: int) -> Dict[str, Any]:
        trace = replay(job.words, f"{job.id}", slot)
        res = evaluate_trace(trace, job.words, analyse, online=job.online, tau=job.tau, expect_clear=job.online.get("end_reason") == "clear")
        res.update({"id": job.id, "tier": job.tier, "group": job.group, "tau": job.tau})
        return res

    def drain(block: bool) -> None:
        nonlocal used
        done = [f for f in futures if f.done()]
        if block and not done and futures:
            while not any(f.done() for f in futures):
                time.sleep(0.02)
                if check:
                    check()
            done = [f for f in futures if f.done()]
        for f in done:
            job, slot = futures.pop(f)
            free_slots.append(slot)
            try:
                res = f.result()
            except Exception as exc:                         # noqa: BLE001 - a replay that could not run is reported, never an exact one
                errors.append({"id": job.id, "error": f"{type(exc).__name__}: {exc}"[:300]})
                continue
            results[job.id] = res
            if on_result:
                on_result(job, res)

    with ThreadPoolExecutor(max_workers=max(1, threads)) as pool:
        for _idx, job in ordered:
            if check:
                check()
            while not free_slots:
                drain(True)
            if now() - t0 > wall_cap_s or used + len(job.words) > tick_cap:
                skipped.append(job.id)
                continue
            used += len(job.words)
            slot = free_slots.pop(0)
            futures[pool.submit(work, job, slot)] = (job, slot)
            drain(False)
        while futures:
            drain(True)
    bad = [r["id"] for r in results.values() if not r["exact"]]
    return {"replays": len(results), "exact": len(results) - len(bad), "inexact": bad, "skipped_unverified": skipped, "errors": errors,
            "ticks": used, "wall_s": round(now() - t0, 2), "results": results}


def contract_description() -> Dict[str, Any]:
    return {"contract": VERIFY_CONTRACT, "equal": ["native action digest of the words", "every consumed tick 0..n-1 and input tick i + 1", "break table after the handover",
                                                   "chain digest at the last tick", "end observation but host_frame",
                                                   "clear facts and both completion clocks (never collapsed)"],
            "inexact_clear": "INVALID", "plan": "priority tiers in input order; tick budget reserved at launch; wall cap stops launches"}
