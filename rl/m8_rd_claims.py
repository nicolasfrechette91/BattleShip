"""M8-rd: candidate labelling, the comparison-point truncation (amendment 1), and replay verification of claims (pure).

Design: proposal sections 7.4 and 11.2-11.3 as amended by docs/rl_m8_rd_amendment_2026-10-02.md.

Every finished job (an archive iteration of arm T, or a control episode of arm C) is committed to its arm's ledger in
ingestion order. The ledger's cumulative native-tick position is the sum of the ticks of the jobs committed before; a job's
event at absolute tick j therefore sits at cumulative position `cum_before + j`. After both arms finish, the comparison
point is T = the cumulative tick count the slower arm reached, and only events at positions <= T count for either arm
(a job that straddles T is cut: its counted words are the first T - cum_before).

Candidates (the trajectories whose claims are verified by an exact replay from tick 0):
    t        for each number of targets broken, the strictly shorter trajectories that first reached it (the shortest at
             that t wins within any comparison point)
    l0       the first trajectory with a grounded live tick on floor line 0 (the wall top)
    left     every trajectory with a live step left of x = -2100, a landing on a left-side floor, or a left-target break
    clear    every trajectory that cleared the stage
A replay is evaluated for ALL milestones at once and credits each one it satisfies, whatever kind of candidate it was.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import m8_rd_cells as mcell

CLAIMS_CONTRACT = "m8_rd_claims_v1"
LADDER = ("none", "L0", "crossing", "left_target", "clear")          # m = 0 .. 4
MILESTONES = LADDER[1:]
MIN_ARM_TICKS = 1_500_000                  # amendment 1: fewer than this in either arm is INCOMPLETE
ARM_TICK_CAP = 3_000_000                   # amendment 1: each arm is capped here
KIND_FOR_MILESTONE = {"clear": ("clear",), "left_target": ("left",), "crossing": ("left",), "L0": ("l0",)}


def ladder_index(name: str) -> int:
    return LADDER.index(name)


def contract_digest() -> str:
    d = {"contract": CLAIMS_CONTRACT, "ladder": list(LADDER), "min_arm_ticks": MIN_ARM_TICKS, "arm_tick_cap": ARM_TICK_CAP,
         "comparison_point": "T = min(ticks of arm T, ticks of arm C); an event counts iff cum_before + j <= T; a job "
                             "straddling T is cut at T - cum_before words",
         "candidates": {"t": "strictly shorter trajectory per t level, in discovery order",
                        "l0": "first grounded live tick on floor line 0", "left": "live x < -2100, a left-floor landing or a "
                        "left-target break in the post-prefix part", "clear": "native EpisodeEnded with 0 targets left"},
         "replay": "all milestones credited by every replay; verified in discovery order per milestone until one qualifies",
         "equal": ["native action digest", "every consumed tick", "break table (id, tick) vs the online table",
                   "claimed event tick", "milestone predicate re-derived by the registered analyser"],
         "clear_facts": ["end reason clear", "native result outcome == clear", "ten broken targets", "completion clocks"]}
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# -- the per-arm ledger ------------------------------------------------------------------------------------------------------


class ArmLedger:
    """Committed jobs of one arm in ingestion order, with their candidates."""

    def __init__(self, arm: str):
        self.arm = arm
        self.ticks = 0
        self.jobs = 0
        self.cut_jobs = 0
        self.candidates: List[Dict[str, Any]] = []
        self.t_records: Dict[int, List[int]] = {}       # t -> candidate ids, strictly shorter each time
        self.l0_cid: Optional[int] = None
        self.max_t_online = 0
        self.job_log: List[Tuple[int, int, int]] = []   # (cum_before, ticks, t at the end of the counted words)

    def commit(self, ticks: int) -> int:
        """Reserve the job's cumulative start; returns cum_before."""
        before = self.ticks
        self.ticks += int(ticks)
        self.jobs += 1
        return before

    def _add(self, cand: Dict[str, Any]) -> int:
        cand["cid"] = len(self.candidates)
        self.candidates.append(cand)
        return cand["cid"]

    def register(self, *, cum_before: int, iteration: int, words: bytes, prefix_len: int, labels: Mapping[str, Any],
                 breaks: Sequence[Tuple[int, int]], end_reason: str, t_end: int) -> List[int]:
        """Register the candidates of one job. `words` = the full trajectory from tick 0 (prefix + burst); `labels` =
        BurstScanner.labels() over the post-prefix part (absolute ticks j); `breaks` = [(j, id)] of the whole trajectory."""
        self.job_log.append((int(cum_before), len(words), int(t_end)))
        self.max_t_online = max(self.max_t_online, int(t_end))
        first = labels["first"]
        made: List[int] = []
        brk = [(int(j), int(i)) for j, i in breaks]
        # t: every level first reached in the post-prefix part, kept only when strictly shorter than the best so far
        for j, t in labels["t_events"]:
            recs = self.t_records.setdefault(int(t), [])
            if recs and int(j) >= len(self.candidates[recs[-1]]["words"]):
                continue
            cid = self._add({"kind": "t", "arm": self.arm, "iteration": iteration, "cum_before": cum_before,
                             "event_j": int(j), "t": int(t), "words": bytes(words[:j]),
                             "breaks": [b for b in brk if b[0] <= j], "first": {}})
            recs.append(cid)
            made.append(cid)
        if first.get("l0") is not None and self.l0_cid is None:
            j = int(first["l0"])
            self.l0_cid = self._add({"kind": "l0", "arm": self.arm, "iteration": iteration, "cum_before": cum_before,
                                     "event_j": j, "t": None, "words": bytes(words[:j]),
                                     "breaks": [b for b in brk if b[0] <= j], "first": {"l0": j}})
            made.append(self.l0_cid)
        left_events = [first[k] for k in ("left_live", "left_floor", "left_break") if first.get(k) is not None]
        if left_events:
            made.append(self._add({"kind": "left", "arm": self.arm, "iteration": iteration, "cum_before": cum_before,
                                   "event_j": int(min(left_events)), "t": None, "words": bytes(words), "breaks": brk,
                                   "first": {k: v for k, v in first.items() if v is not None}}))
        if first.get("clear") is not None:
            made.append(self._add({"kind": "clear", "arm": self.arm, "iteration": iteration, "cum_before": cum_before,
                                   "event_j": int(first["clear"]), "t": mcell.TARGETS_TOTAL, "words": bytes(words),
                                   "breaks": brk, "first": {k: v for k, v in first.items() if v is not None}}))
        return made

    # -- within the comparison point ---------------------------------------------------------------------------------------------

    @staticmethod
    def counted_len(cand: Mapping[str, Any], T: int) -> Optional[int]:
        """Words of the candidate that lie within the first T cumulative ticks, or None when its event does not."""
        if cand["cum_before"] + cand["event_j"] > T:
            return None
        return min(len(cand["words"]), T - cand["cum_before"])

    def within(self, T: int, kind: str) -> List[Tuple[Dict[str, Any], int]]:
        out = []
        for c in self.candidates:
            if c["kind"] == kind:
                n = self.counted_len(c, T)
                if n is not None:
                    out.append((c, n))
        return out

    def t_within(self, T: int) -> Tuple[int, Optional[Dict[str, Any]], Optional[int]]:
        """(t, the shortest candidate that reached it within T, its counted length); (0, None, None) when no target broke."""
        for t in range(mcell.TARGETS_TOTAL, 0, -1):
            best = None
            for cid in self.t_records.get(t, []):
                c = self.candidates[cid]
                if self.counted_len(c, T) is not None:
                    best = c
            if best is not None:
                return t, best, self.counted_len(best, T)
        return 0, None, None

    def online_t_within(self, T: int) -> int:
        """The online maximum number of targets broken within T (the t of the registered candidates, for cross-checks)."""
        return self.t_within(T)[0]


# -- replay evaluation (pure given a trace and an analyser) --------------------------------------------------------------------


Analyser = Callable[[Mapping[str, Any], Sequence[Mapping[str, Any]]], Mapping[str, Any]]


def first_l0_tick(steps: Sequence[Mapping[str, Any]]) -> Optional[int]:
    """j (= input_tick) of the first grounded live tick on floor line 0 in a replay's raw replies."""
    for r in steps:
        o, sp = r["observation"], r["spatial"]
        if mcell.is_live(o) and int(o["ground_air_state"]) == 0 and int(sp["fighter"]["floor_line_id"]) == mcell.L0_FLOOR_LINE:
            return int(o["input_tick"])
    return None


def clear_facts(trace: Mapping[str, Any], n_breaks: int) -> Dict[str, Any]:
    """The M7d four-fact clear: end reason clear, the native result's outcome, ten broken targets, both completion clocks."""
    res = trace.get("result") or {}
    last = (trace.get("steps") or [{}])[-1]
    lo = last.get("observation") or {}
    end_clear = (trace.get("final_state") == "EpisodeEnded" and int(lo.get("btt_active", 0)) == 1
                 and int(lo.get("targets_remaining", 1)) == 0)
    flag = res.get("outcome") == "clear"
    ten = n_breaks == mcell.TARGETS_TOTAL and res.get("targets_broken") == mcell.TARGETS_TOTAL
    clocks = (isinstance(res.get("completion_time_passed"), int) and isinstance(res.get("completion_input_tick"), int))
    return {"end_reason_clear": bool(end_clear), "cleared_flag": bool(flag), "ten_targets": bool(ten),
            "completion_clock": bool(clocks), "all": bool(end_clear and flag and ten and clocks),
            "completion_time_passed": res.get("completion_time_passed"), "completion_input_tick": res.get("completion_input_tick")}


def evaluate_replay(trace: Mapping[str, Any], cand: Mapping[str, Any], counted: int, analyse: Analyser) -> Dict[str, Any]:
    """Evaluate one fresh-process replay of `cand`'s first `counted` words. A replay is EXACT only if its native action
    digest, every consumed tick and its break table equal the online record (and, for l0, the claimed event tick); an inexact
    replay makes the session INVALID (never just uncounted)."""
    words = bytes(cand["words"][:counted])
    steps = trace.get("steps") or []
    initial = trace["initial"]
    problems: List[str] = []
    if trace.get("consumed_tick_mismatch") is not None:
        problems.append(f"consumed_tick mismatch {trace['consumed_tick_mismatch']}")
    if trace.get("unsent"):
        problems.append(f"{trace['unsent']} word(s) not submitted")
    if len(steps) != len(words):
        problems.append(f"{len(steps)} replies for {len(words)} words")
    expected_digest = mcell.words_digest(words)
    if trace.get("action_digest") != expected_digest:
        problems.append("native action digest differs from the candidate's words")
    for i, r in enumerate(steps):
        if int(r["consumed_tick"]) != i or int(r["observation"]["input_tick"]) != i + 1:
            problems.append(f"tick {i}: consumed {r['consumed_tick']} input_tick {r['observation']['input_tick']}")
            break
    an = analyse(initial, steps)
    replay_breaks = sorted((int(t) + 1, int(i)) for i, t in an["breaks"])           # (j, id)
    online_breaks = sorted((int(j), int(i)) for j, i in cand["breaks"] if int(j) <= counted)
    if replay_breaks != online_breaks:
        problems.append(f"break table differs: replay {replay_breaks[:6]} online {online_breaks[:6]}")
    l0 = first_l0_tick(steps)
    if cand["kind"] == "l0" and l0 != cand["event_j"]:
        problems.append(f"first wall-top landing at {l0}, claimed {cand['event_j']}")
    if cand["kind"] == "t" and len(replay_breaks) != cand["t"]:
        problems.append(f"{len(replay_breaks)} targets broken, claimed {cand['t']}")
    facts = clear_facts(trace, len(replay_breaks))
    if cand["kind"] == "clear" and not facts["all"] and counted == len(cand["words"]):
        problems.append(f"the claimed clear does not hold: {facts}")
    exact = not problems
    return {"cid": cand["cid"], "arm": cand["arm"], "kind": cand["kind"], "counted": counted, "exact": exact,
            "problems": problems, "t": len(replay_breaks), "breaks": [list(b) for b in replay_breaks],
            "l0": l0 is not None, "l0_tick": l0, "crossing": bool(an.get("qualified_crossing")),
            "left_target": bool(an.get("left_target_break")), "left_target_breaks": [list(b) for b in an.get("left_target_breaks", [])],
            "clear": bool(facts["all"]) and counted == len(cand["words"]), "clear_facts": facts,
            "first_qualified_entry": (an.get("first_qualified_entry") or {}).get("consumed_tick"),
            "route": an.get("route"), "terminal": an.get("terminal")}


def levels_of(rep: Mapping[str, Any]) -> Dict[str, bool]:
    return {"L0": bool(rep["l0"]), "crossing": bool(rep["crossing"]), "left_target": bool(rep["left_target"]),
            "clear": bool(rep["clear"])}


def milestone_level(replays: Sequence[Mapping[str, Any]]) -> int:
    """m: the highest ladder level whose predicate holds for some exact replay."""
    m = 0
    for r in replays:
        if not r["exact"]:
            continue
        for name, ok in levels_of(r).items():
            if ok:
                m = max(m, ladder_index(name))
    return m


def plan_replays(ledger: ArmLedger, T: int, done: Mapping[int, Mapping[str, Any]], batch: int = 3
                 ) -> Tuple[List[Tuple[Dict[str, Any], int]], Dict[str, Any]]:
    """The next replays to run for one arm (<= `batch`): for each unsatisfied milestone, in discovery order, the first
    candidate not yet replayed; the max-t candidate first. Also reports which milestones are satisfied and which still have
    unreplayed candidates."""
    exact_reps = [r for r in done.values() if r["exact"]]
    satisfied = {name: any(levels_of(r)[name] for r in exact_reps) for name in MILESTONES}
    todo: List[Tuple[Dict[str, Any], int]] = []
    seen: set = set()
    t, tc, tn = ledger.t_within(T)
    if tc is not None and tc["cid"] not in done:
        todo.append((tc, tn))
        seen.add(tc["cid"])
    remaining: Dict[str, int] = {}
    pools: Dict[str, List[Tuple[Dict[str, Any], int]]] = {}
    for name in reversed(MILESTONES):                     # clear, left_target, crossing, L0
        if satisfied[name]:
            remaining[name] = 0
            continue
        pool = [(c, n) for kind in KIND_FOR_MILESTONE[name] for c, n in ledger.within(T, kind) if c["cid"] not in done]
        pool.sort(key=lambda cn: cn[0]["cid"])
        remaining[name] = len(pool)
        pools[name] = pool
    # the batch is filled round-robin over the unsatisfied milestones, each pool in discovery order (milestones that share a
    # pool, crossing and left_target, therefore advance through it together)
    for rank in range(max((len(p) for p in pools.values()), default=0)):
        for pool in pools.values():
            if rank < len(pool) and pool[rank][0]["cid"] not in seen and len(todo) < batch:
                todo.append(pool[rank])
                seen.add(pool[rank][0]["cid"])
    return todo[:batch], {"satisfied": satisfied, "remaining": remaining, "t": t}
