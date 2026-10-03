"""M8-rd4: claim-path safety for a session that starts from INHERITED frontier states (pure; the frozen claims engine `m8_rd_claims` is imported, never edited).

The frozen engine (rl/m8_rd_claims.py) labels a burst's events over its post-prefix part and registers candidates (`t`, `l0`, `left`, `clear`); a verification replays a candidate from tick 0 and
evaluates every milestone on the WHOLE trajectory. That is exact for a session that starts from tick 0, and it needs two guards once the archive holds states on the wall top and left of the wall:

1. WALL-TOP CONTINUATIONS (found in rd3, decisions I15). The engine checks an `l0` candidate against the FIRST line-0 tick of the whole replayed trajectory; a burst that continues from a prefix that
   already stood on line 0 would fail that check - a false INVALID. rd3's `suppress_wall_top_label` (rl/m8_rd3_run.py) removes the label before the commit; rd4 reuses it unchanged.
   Nothing else in `evaluate_replay` compares a whole-trajectory first event with a claimed one (`left` and `clear` candidates are checked by the native action digest, every consumed tick,
   the break table and, for a clear, the four facts; `t` candidates by the break table and the count), so a burst that continues from an inherited LEFT-OF-WALL prefix cannot be a false
   INVALID: its candidate carries its inherited `left_live` and is replayed like any other.

2. VERIFICATION CAPACITY. A burst that starts left of the wall has `left_live` at its first tick, so EVERY return to the (growing) set of left-of-wall cells registers a `left` candidate, and
   rd3's plan would replay them all in discovery order until a cap: hundreds of candidates cannot be verified in the 400,000-tick / 6-minute caps, and the close identity replays share them, so
   a session that found nothing would end INCOMPLETE and one that found a crossing late in discovery order would miss it. The qualifying events of the ladder above the wall top need events
   the burst scanner already records: a qualified crossing needs a LANDING on the left floor (`left_floor`, a grounded live tick on floor line 3: the analyser's valid left-side landing is
   exactly that), a left-target break needs `left_break`, a clear needs `clear`. A candidate without any of the three cannot raise m. So:

       pool(crossing)    = `left` candidates with a `left_floor` event       (can reach level 2)
       pool(left_target) = `left` candidates with a `left_break` event       (can reach level 3)
       pool(clear)       = `clear` candidates, and any with a `clear` event  (can reach level 4)

   are replayed first, in discovery order, round-robin over the unsatisfied milestones (the order of rd3's plan within a pool); the maximum-targets candidate is still first; the INCOMPLETE test
   ("a candidate that could raise m left unverified at a cap") reads only these pools. The remaining `left` candidates (a live step left of the wall and nothing more: an unqualified entry)
   are replayed only AFTER every pool is empty or satisfied, at most `INFO_REPLAY_MAX` of them (descriptive facts, as rd3's three), and never decide INCOMPLETE. Every candidate is still
   registered and stored (candidates_T.jsonl.gz): nothing is discarded, only the order and the descriptive allowance change. No registered measure (m, t, the mechanism check, the
   thresholds, the selection, the cell key) reads this plan.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import m8_rd_claims as mclaims

CLAIMS4_CONTRACT = "m8_rd4_claims_v1"
LEVEL = {"crossing": 2, "left_target": 3, "clear": 4}
RAISE_EVENT = {"crossing": "left_floor", "left_target": "left_break", "clear": "clear"}
POOL_ORDER = ("clear", "left_target", "crossing")
INFO_REPLAY_MAX = 6                                  # descriptive replays of unqualified left entries after the pools (rd3 replayed 3)


def contract_digest() -> str:
    import hashlib
    import json

    d = {"contract": CLAIMS4_CONTRACT, "base": mclaims.CLAIMS_CONTRACT, "base_digest": mclaims.contract_digest(),
         "pools": {k: RAISE_EVENT[k] for k in POOL_ORDER}, "order": "max-t candidate first; then the unsatisfied milestones round-robin, each pool in discovery order; "
                                                                      "descriptive left entries only after every pool is empty or satisfied",
         "info_replay_max": INFO_REPLAY_MAX, "incomplete_reads": "only the can-raise pools of the unsatisfied milestones"}
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def events_of(cand: Mapping[str, Any]) -> frozenset:
    """The first-event names a registered candidate carries (left_live, left_floor, left_break, clear, l0)."""
    return frozenset(k for k, v in (cand.get("first") or {}).items() if v is not None)


def raises(cand: Mapping[str, Any]) -> List[str]:
    """The milestones a candidate can raise, by the events it carries (a candidate of kind `clear` can raise the clear)."""
    ev = events_of(cand)
    out = [name for name in POOL_ORDER if RAISE_EVENT[name] in ev]
    if cand.get("kind") == "clear" and "clear" not in out:
        out.append("clear")
    return out


def is_descriptive(cand: Mapping[str, Any]) -> bool:
    """A `left` candidate that can raise nothing: an unqualified entry (a live step left of the wall, no landing, no left target, no clear)."""
    return cand.get("kind") == "left" and not raises(cand)


def pool_sizes(ledger: mclaims.ArmLedger, T: int) -> Dict[str, Any]:
    """The registered candidates by what they can raise (for the verification record)."""
    cands = [c for c, _n in ledger.within(T, "left")] + [c for c, _n in ledger.within(T, "clear")]
    return {"left": sum(1 for c in cands if c["kind"] == "left"), "clear_kind": sum(1 for c in cands if c["kind"] == "clear"),
            "can_raise": {k: sum(1 for c in cands if k in raises(c)) for k in POOL_ORDER}, "descriptive": sum(1 for c in cands if is_descriptive(c)),
            "t": len(ledger.within(T, "t")), "l0": len(ledger.within(T, "l0"))}


def plan_replays4(ledger: mclaims.ArmLedger, T: int, done: Mapping[int, Mapping[str, Any]], batch: int = 3, *, info_max: int = INFO_REPLAY_MAX
                  ) -> Tuple[List[Tuple[Dict[str, Any], int]], Dict[str, Any]]:
    """The next replays (<= `batch`): the maximum-targets candidate first; then, for each unsatisfied milestone, the first can-raise candidate not yet replayed (round-robin, discovery order);
    then, only when no pool has a candidate left to start, descriptive left entries up to `info_max` in total. Also reports which milestones are satisfied and how many can-raise
    candidates remain unreplayed per unsatisfied milestone (the INCOMPLETE test reads those)."""
    exact_reps = [r for r in done.values() if r["exact"]]
    satisfied = {name: any(mclaims.levels_of(r)[name] for r in exact_reps) for name in POOL_ORDER}
    todo: List[Tuple[Dict[str, Any], int]] = []
    seen: set = set()
    t, tc, tn = ledger.t_within(T)
    if tc is not None and tc["cid"] not in done:
        todo.append((tc, tn))
        seen.add(tc["cid"])
    cands = {c["cid"]: (c, n) for kind in ("left", "clear") for c, n in ledger.within(T, kind)}
    remaining: Dict[str, int] = {}
    pools: Dict[str, List[Tuple[Dict[str, Any], int]]] = {}
    for name in POOL_ORDER:
        if satisfied[name]:
            remaining[name] = 0
            continue
        pool = sorted(((c, n) for c, n in cands.values() if name in raises(c) and c["cid"] not in done), key=lambda cn: cn[0]["cid"])
        remaining[name] = len(pool)
        pools[name] = pool
    for rank in range(max((len(p) for p in pools.values()), default=0)):
        for pool in pools.values():
            if rank < len(pool) and pool[rank][0]["cid"] not in seen and len(todo) < batch:
                todo.append(pool[rank])
                seen.add(pool[rank][0]["cid"])
    info_all = sorted(((c, n) for c, n in cands.values() if is_descriptive(c)), key=lambda cn: cn[0]["cid"])
    info_used = sum(1 for c, _n in info_all if c["cid"] in done)
    pools_open = any(remaining[name] > 0 for name in pools)
    if not pools_open and len(todo) < batch:
        for c, n in info_all:
            if info_used >= info_max or len(todo) >= batch:
                break
            if c["cid"] not in done and c["cid"] not in seen:
                todo.append((c, n))
                seen.add(c["cid"])
                info_used += 1
    return todo[:batch], {"satisfied": satisfied, "remaining": remaining, "t": t, "descriptive_total": len(info_all), "descriptive_replayed": sum(1 for c, _n in info_all if c["cid"] in done),
                          "descriptive_allowance": info_max}


def max_m_unverified(info: Mapping[str, Any]) -> int:
    """The highest ladder level an unreplayed can-raise candidate of an unsatisfied milestone could still reach (0 when none is left)."""
    return max((LEVEL[name] for name, n in info["remaining"].items() if n > 0 and not info["satisfied"][name]), default=0)
