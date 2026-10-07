"""M9-g3: the replenishing controlled frontier `m9_g3_frontier_v1` (pure, standard library only): g2's frontier (the pointer, g1's start distribution
on g3 keys, the curtailed trigger window, the frozen-test attempts, the move, the carried state, the rebuild from records) with the attempt bounds
(HELD per session, STALLED over the line) replaced by the spacing rule.

Rule (decision 2; stop review 3.1):

    trigger     among counted strip outcomes since the latest of (the session open, the last move, the last attempt at this pointer, the last deferred
                trigger), the 8th clear fires the trigger; the 13th non-clear voids the window; outcomes after a trigger and before its attempt belong to
                no window (`after_trigger`) but count toward the spacing
    spacing     let f be the number of failed attempts at the current pointer since the last move (the pointer never returns to a pointer it left, so f is
                the line-wide failed count at the pointer). An attempt may run only if at least need(f) = min(320, 20 x 2^(f-1)) counted strip outcomes
                at the pointer have completed since the last failed attempt (need(0) = 0) AND the trigger has fired. A trigger inside the spacing is
                logged `deferred_trigger`, no attempt runs, the window restarts.
    attempt     as g2: at the next rollout boundary, a frozen snapshot, the strip test (pass at the 10th clear, fail at the 11th non-clear), then the
                re-check of every registered landing >= pointer + 20 in parallel; the pointer moves back 20 ticks iff every test passes; a failed re-check
                only blocks the move
    no bounds   no HELD and no STALLED; per-pointer attempt counts are recorded and reported, never bounding. An interrupted attempt counts as neither
                pass nor fail (f and the outcome count unchanged).

`replay_history` rebuilds the pointer, the windows, the deferred triggers, the spacing state and every attempt from the training records alone and
names an attempt inside its spacing or a move without a passing strip test and every re-check.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import m9_contract as C
import m9_curriculum as CU
import m9_g2_frontier as F2
import m9_g3_contract as G
import m9_sticky as S

FRONTIER_CONTRACT = G.FRONTIER_RULE_ID
RESULTS = F2.RESULTS                                 # MOVED, FAILED_STRIP, BLOCKED_BY_RECHECK, INTERRUPTED
FAILED_RESULTS = ("FAILED_STRIP", "BLOCKED_BY_RECHECK")
FrontierError = F2.FrontierError
landings_behind = F2.landings_behind
audit_landings = F2.audit_landings


def strip_start(pointer: int, attempt: int, k: int, lengths: Mapping[str, int], order: Sequence[str] = ("T_clear", "T_t")) -> Tuple[int, str, bool]:
    """The keyed start of strip-test episode k on g3 keys: tau uniform over the strip, the lineage as g1's R2."""
    key = G.probe_label(pointer, attempt, "strip", k)
    tau = int(pointer) + min(G.STRIP - 1, int(S.uniform(key + "|tau") * G.STRIP))
    if tau <= C.SHARED_PREFIX:
        return tau, order[0], True
    valid = [n for n in order if int(lengths[n]) >= tau + C.MIN_WORDS_AFTER_START]
    if not valid:
        raise FrontierError(f"no lineage holds a start at {tau}")
    u = S.uniform(key + "|lineage")
    return tau, valid[min(len(valid) - 1, int(u * len(valid)))], False


class Frontier(F2.Frontier):
    """g2's frontier on g3 keys, with the spacing rule instead of the attempt bounds."""

    def __init__(self, lengths: Mapping[str, int], *, session: int = 1, landings: Sequence[int] = G.LANDINGS, state: Optional[Mapping[str, Any]] = None, **kw: Any):
        self.since_failed = 0                        # counted strip outcomes at the pointer since the last failed attempt
        self.deferred = 0                            # deferred triggers (this session)
        super().__init__(lengths, session=session, landings=landings, state=state, **kw)

    # -- state --

    def _restore(self, st: Mapping[str, Any]) -> None:
        fid = st.get("frontier")
        if fid is not None and fid != FRONTIER_CONTRACT:
            raise FrontierError(f"the carried state is {fid!r}, not {FRONTIER_CONTRACT}: another line's state is never resumed")
        if st.get("stalled"):
            raise FrontierError("the carried state carries a STALLED flag: not a g3 state")
        super()._restore(st)
        self.since_failed = int(st.get("since_failed", 0))

    def held(self) -> bool:
        """No HELD state exists in g3."""
        return False

    def f(self) -> int:
        """Consecutive failed attempts at the current pointer since the last move (= the line-wide failed count at the pointer)."""
        return int(self.line_failed.get(self.pointer, 0))

    def need(self) -> int:
        return G.spacing_need(self.f())

    def spacing_ok(self) -> bool:
        return self.since_failed >= self.need()

    def spacing_state(self) -> Dict[str, Any]:
        return {"f": self.f(), "need": self.need(), "have": int(self.since_failed), "ok": self.spacing_ok()}

    def state(self) -> Dict[str, Any]:
        base = super().state()
        for k in ("held", "stalled", "stalled_pointer", "held_triggers", "bounds"):
            base.pop(k, None)
        base.update({"frontier": FRONTIER_CONTRACT, "spacing": self.spacing_state(), "deferred_triggers": int(self.deferred),
                     "spacing_rule": {"unit": G.SPACING_UNIT, "cap": G.SPACING_CAP}, "attempts_per_pointer": {str(k): v for k, v in sorted(self.line_failed.items())}})
        return base

    def carried_state(self) -> Dict[str, Any]:
        """What a later session restores: the pointer, the failed attempts per pointer over the line (f), the outcomes since the last failed attempt, the
        moves, the global counters."""
        return {"frontier": FRONTIER_CONTRACT, "pointer": self.pointer, "line_failed": {str(k): v for k, v in sorted(self.line_failed.items())}, "since_failed": int(self.since_failed),
                "moves": list(self.moves_all), "next_episode": self.next_episode, "attempt_counter": self.attempt_counter, "sessions": list(self.sessions_seen),
                "landings": list(self.landings)}

    # -- starts (g1's distribution on g3 keys) --

    def draw(self, episode: int) -> CU.Start:
        rng = self.ranges()
        u_region = S.uniform(G.start_key(episode, "region")) * 100.0
        acc = 0.0
        pick = self.weights[-1][0]
        for r, w in self.weights:
            acc += w
            if u_region < acc:
                pick = r
                break
        order = [r for r, _w in self.weights]
        i = order.index(pick)
        while rng[order[i]] is None and i > 0:
            i -= 1
        region = order[i]
        lo, hi = rng[region]                                                    # type: ignore[misc]
        u = S.uniform(G.start_key(episode, "tau"))
        tau = lo + min(hi - lo, int(u * (hi - lo + 1)))
        if tau <= self.shared_prefix:
            lineage, shared = self.order[0], True
        else:
            valid = [n for n in self.order if self.lengths[n] >= tau + C.MIN_WORDS_AFTER_START]
            if not valid:
                raise FrontierError(f"no lineage holds a start at {tau}")
            u2 = S.uniform(G.start_key(episode, "lineage"))
            lineage, shared = valid[min(len(valid) - 1, int(u2 * len(valid)))], False
        self.draws += 1
        self.next_episode = max(self.next_episode, int(episode) + 1)
        return CU.Start(int(episode), region, int(tau), lineage, shared, self.pointer)

    # -- outcomes, the window and the spacing --

    def record(self, start: CU.Start, cleared: bool) -> Optional[Dict[str, Any]]:
        """One finished training episode. Returns an event record for the log when the window changed state (trigger, deferred_trigger, void), the
        `after_trigger` marker, or None."""
        if start.region != "strip":
            self.outside += 1
            return None
        if start.pointer != self.pointer:
            self.stale += 1
            self.stale_clears += int(bool(cleared))
            return None
        self.counted += 1
        self.since_failed += 1                       # every counted strip outcome at the pointer is practice at the strip
        if self.pending is not None:
            self.after_trigger += 1
            return {"event": "after_trigger", "pointer": self.pointer, "clear": bool(cleared)}
        w = self.window
        w["outcomes"].append(1 if cleared else 0)
        w["clears"] += int(bool(cleared))
        w["non_clears"] += int(not cleared)
        if w["clears"] >= G.TRIGGER_CLEARS:
            sp = self.spacing_state()
            w["result"] = "trigger" if sp["ok"] else "deferred_trigger"
            self.windows.append(w)
            ev = {"event": w["result"], "pointer": self.pointer, "clears": w["clears"], "non_clears": w["non_clears"], "size": len(w["outcomes"]), "window": len(self.windows) - 1, "spacing": sp}
            if sp["ok"]:
                self.pending = {"pointer": self.pointer, "window": len(self.windows) - 1, "clears": w["clears"], "non_clears": w["non_clears"], "a": self.next_attempt_index(), "spacing": sp}
            else:
                self.deferred += 1
            self.window = self._new_window(w["result"])
            return ev
        if w["non_clears"] >= G.TRIGGER_VOID_NONCLEARS:
            w["result"] = "void"
            self.windows.append(w)
            ev = {"event": "void", "pointer": self.pointer, "clears": w["clears"], "non_clears": w["non_clears"], "size": len(w["outcomes"]), "window": len(self.windows) - 1}
            self.window = self._new_window("void")
            return ev
        return None

    # -- attempts --

    def begin_attempt(self, *, episodes_before: int, _force: bool = False) -> Dict[str, Any]:
        """The attempt the pending trigger earned; refused inside the spacing. `_force` is the rebuild's way of continuing past a recorded violation."""
        if self.pending is None:
            raise FrontierError("no pending trigger")
        if not self.spacing_ok() and not _force:
            raise FrontierError(f"an attempt inside its spacing: {self.spacing_state()}")
        self.attempt_counter += 1
        a = self.next_attempt_index()
        rec = {"n": self.attempt_counter, "a": a, "pointer": self.pointer, "session": self.session, "trigger": dict(self.pending), "episodes_before": int(episodes_before),
               "rechecks_planned": landings_behind(self.pointer, self.landings), "line_failed_before": self.line_failed.get(self.pointer, 0),
               "session_failed_before": self.session_failed.get(self.pointer, 0), "spacing": self.spacing_state(), "result": None}
        self.pending = None
        self.after_trigger = 0
        return rec

    def finish_attempt(self, rec: Dict[str, Any], result: str, *, strip: Mapping[str, Any], rechecks: Mapping[int, Mapping[str, Any]], failed_landing: Optional[int] = None) -> Dict[str, Any]:
        if result not in RESULTS:
            raise FrontierError(f"unknown attempt result {result!r}")
        p = int(rec["pointer"])
        if p != self.pointer:
            raise FrontierError("the pointer changed during an attempt")
        rec.update({"result": result, "strip_clears": int(strip.get("clears", 0)), "strip_non_clears": int(strip.get("non_clears", 0)), "strip_passed": bool(strip.get("passed")),
                    "rechecks": {str(k): dict(v) for k, v in rechecks.items()}, "failed_landing": failed_landing, "new_pointer": p})
        if result == "MOVED":
            if not strip.get("passed") or any(not v.get("passed") for v in rechecks.values()) or set(int(k) for k in rechecks) != set(rec["rechecks_planned"]):
                raise FrontierError("a move without a passing strip test and every re-check")
            new = max(0, p - G.STRIP)
            rec["new_pointer"] = new
            move = {"from": p, "to": new, "attempt": rec["n"], "a": rec["a"], "session": self.session, "after_failed_attempts": self.line_failed.get(p, 0)}
            self.moves.append(move)
            self.moves_all.append(move)
            self.pointer = new
            self.since_failed = 0
            self.window = self._new_window("move")
        elif result in FAILED_RESULTS:
            self.line_failed[p] = self.line_failed.get(p, 0) + 1
            self.session_failed[p] = self.session_failed.get(p, 0) + 1          # recorded and reported, never bounding
            self.since_failed = 0
            self.window = self._new_window("attempt")
        else:                                           # INTERRUPTED: neither pass nor fail; f and the outcome count are unchanged; the window restarts
            self.window = self._new_window("interrupted")
        rec.update({"line_failed_after": self.line_failed.get(p, 0), "session_failed_after": self.session_failed.get(p, 0), "spacing_after": self.spacing_state()})
        self.attempts.append(rec)
        return rec


# -- the rebuild from records (verify-run) ---------------------------------------------------------------------------------------------------


def replay_history(episodes: Sequence[Mapping[str, Any]], attempts: Sequence[Mapping[str, Any]], lengths: Mapping[str, int], *, session: int, state: Optional[Mapping[str, Any]] = None,
                   landings: Sequence[int] = G.LANDINGS) -> Dict[str, Any]:
    """Rebuild the pointer, the windows, the deferred triggers, the spacing state and the attempt history from the completion-ordered training records and
    the attempt records alone, and re-derive every start from its keys. An attempt with `episodes_before == i` is applied before training episode i."""
    fr = Frontier(lengths, session=session, landings=landings, state=state)
    problems: List[str] = []
    by_before: Dict[int, List[Mapping[str, Any]]] = {}
    for a in attempts:
        by_before.setdefault(int(a["episodes_before"]), []).append(a)
    moves: List[Tuple[int, int]] = []
    triggers = 0
    schedule: List[Dict[str, Any]] = []

    def apply_attempts(i: int) -> None:
        nonlocal triggers
        for a in by_before.get(i, []):
            if fr.pending is None:
                problems.append(f"attempt {a['n']}: no trigger was pending")
                fr.pending = {"pointer": fr.pointer, "a": fr.next_attempt_index(), "forced": True}
            if int(a["pointer"]) != fr.pointer:
                problems.append(f"attempt {a['n']}: pointer {a['pointer']} differs from the rebuilt {fr.pointer}")
            if int(a["a"]) != fr.next_attempt_index():
                problems.append(f"attempt {a['n']}: line attempt index {a['a']} differs from the rebuilt {fr.next_attempt_index()}")
            sp = fr.spacing_state()
            if not sp["ok"]:
                problems.append(f"attempt {a['n']}: inside its spacing (f {sp['f']}, need {sp['need']}, have {sp['have']})")
            rec_sp = dict(a.get("spacing") or {})
            if rec_sp and any(rec_sp.get(k) != sp[k] for k in ("f", "need", "have")):
                problems.append(f"attempt {a['n']}: the recorded spacing {rec_sp} differs from the rebuilt {sp}")
            rec = fr.begin_attempt(episodes_before=i, _force=True)
            triggers += 1
            rechecks = {int(k): v for k, v in dict(a.get("rechecks") or {}).items()}
            try:
                fr.finish_attempt(rec, str(a["result"]), strip={"clears": a.get("strip_clears", 0), "non_clears": a.get("strip_non_clears", 0), "passed": a.get("strip_passed")},
                                  rechecks=rechecks, failed_landing=a.get("failed_landing"))
            except FrontierError as exc:
                problems.append(f"attempt {a['n']}: {exc}")
            schedule.append({"n": int(a["n"]), "pointer": int(a["pointer"]), "a": int(a["a"]), "f": sp["f"], "need": sp["need"], "have": sp["have"], "result": a["result"]})
            if a["result"] == "MOVED":
                if int(a.get("strip_clears", 0)) < G.TEST_PASS or any(int(v.get("clears", 0)) < G.TEST_PASS for v in rechecks.values()):
                    problems.append(f"attempt {a['n']}: a move with fewer than {G.TEST_PASS} clears in a test")
                moves.append((int(a["pointer"]), int(a["new_pointer"])))
            if len(problems) > 20:
                return

    for i, r in enumerate(episodes):
        apply_attempts(i)
        st = r["start"]
        ref = Frontier(lengths, session=session, landings=landings, state={"pointer": int(st["pointer"])})
        got = ref.draw(int(st["episode"]))
        if got.to_json() != {k: st[k] for k in ("episode", "region", "tau", "lineage", "shared", "pointer")}:
            problems.append(f"{r['episode']}: the start does not reproduce from its keys")
        if r["end_reason"] in ("clear", "fall", "horizon", "ended"):
            fr.record(CU.Start(int(st["episode"]), st["region"], int(st["tau"]), st["lineage"], bool(st["shared"]), int(st["pointer"])), bool(r["clear"]))
        if len(problems) > 20:
            break
    apply_attempts(len(episodes))
    return {"pointer": fr.pointer, "moves": moves, "attempts": len(fr.attempts), "triggers": triggers, "deferred_triggers": fr.deferred, "windows": len(fr.windows),
            "schedule": schedule, "state": fr.state(), "problems": problems}


def contract_description() -> Dict[str, Any]:
    return dict(G.frontier_description(), start_distribution=CU.contract_description() | {"keys": G.KEYS["start"]})


def contract_digest() -> str:
    return hashlib.sha256(json.dumps(contract_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
