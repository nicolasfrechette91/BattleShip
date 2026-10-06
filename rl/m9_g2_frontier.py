"""M9-g2: the controlled frontier `m9_g2_frontier_v1` (pure, standard library only): the pointer, the start distribution (g1's, on g2 keys), the
curtailed trigger window, the attempts with their bounds (HELD per session, STALLED over the line), the move, the state record and its rebuild from records.

Rule (decision 1; proposal 2.2; decisions R2, R4, R6):

    trigger     among counted strip outcomes since the latest of (the session open, the last move, the last attempt at this pointer), the 8th clear fires the
                trigger; the 13th non-clear voids the window and a new one begins; outcomes after a trigger and before its attempt belong to no window
    attempt     at the next rollout boundary: a frozen snapshot, a strip test (20 sticky episodes from keyed starts over the strip, pass at the 10th clear,
                fail at the 11th non-clear), then a re-check of every registered landing >= pointer + 20 (the trunk's own state, the same test, in parallel);
                the pointer moves back 20 ticks iff every test passes; a failed re-check only blocks the move
    bounds      every decided attempt counts; 3 failed attempts at one pointer in one session: HELD (no further attempt there this session); 6 over the line:
                STALLED (training ends validly; the line ends)

The start distribution and the stale rule are g1's (`rl/m9_curriculum.Curriculum`, subclassed: ranges, regions, lineage choice unchanged; the keys are g2's and
the block rule is replaced by the window). `verify-run` rebuilds the pointer and attempt history from the training records alone (`replay_history`).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import m9_contract as C
import m9_curriculum as CU
import m9_g2_contract as G
import m9_sticky as S

FRONTIER_CONTRACT = G.FRONTIER_RULE_ID
RESULTS = ("MOVED", "FAILED_STRIP", "BLOCKED_BY_RECHECK", "INTERRUPTED")


class FrontierError(RuntimeError):
    pass


def landings_behind(pointer: int, landings: Sequence[int] = G.LANDINGS) -> List[int]:
    """The registered landings the frontier has fully passed (landing >= pointer + 20), largest first: the re-check set."""
    return sorted((lam for lam in landings if lam >= int(pointer) + G.STRIP), reverse=True)


def audit_landings(pointer: int, landings: Sequence[int] = G.LANDINGS) -> List[int]:
    """The close audit's landings: every landing behind the frontier plus the first landing beyond it (decision R8)."""
    behind = landings_behind(pointer, landings)
    beyond = [lam for lam in sorted(landings, reverse=True) if lam < int(pointer) + G.STRIP]
    return behind + beyond[:1]


def strip_start(pointer: int, attempt: int, k: int, lengths: Mapping[str, int], order: Sequence[str] = ("T_clear", "T_t")) -> Tuple[int, str, bool]:
    """The keyed start of strip-test episode k: tau uniform over the strip, the lineage as g1's R2."""
    key = G.probe_label(pointer, attempt, "strip", k)
    tau = int(pointer) + min(G.STRIP - 1, int(S.uniform(key + "|tau") * G.STRIP))
    if tau <= C.SHARED_PREFIX:
        return tau, order[0], True
    valid = [n for n in order if int(lengths[n]) >= tau + C.MIN_WORDS_AFTER_START]
    if not valid:
        raise FrontierError(f"no lineage holds a start at {tau}")
    u = S.uniform(key + "|lineage")
    return tau, valid[min(len(valid) - 1, int(u * len(valid)))], False


class Frontier(CU.Curriculum):
    """The g2 curriculum: g1's start distribution on g2 keys; the window, the attempts and the bounds instead of the blocks."""

    def __init__(self, lengths: Mapping[str, int], *, session: int = 1, landings: Sequence[int] = G.LANDINGS, state: Optional[Mapping[str, Any]] = None, **kw: Any):
        super().__init__(lengths, tau0=int(state["pointer"]) if state else G.TAU0, **kw)
        self.session = int(session)
        self.landings = tuple(landings)
        self.window: Dict[str, Any] = self._new_window("session_open")
        self.windows: List[Dict[str, Any]] = []
        self.attempts: List[Dict[str, Any]] = []
        self.line_failed: Dict[int, int] = {}
        self.session_failed: Dict[int, int] = {}
        self.pending: Optional[Dict[str, Any]] = None
        self.after_trigger = 0
        self.held_triggers = 0
        self.stalled = False
        self.stalled_pointer: Optional[int] = None
        self.next_episode = 0
        self.attempt_counter = 0
        self.moves_all: List[Dict[str, Any]] = []
        self.sessions_seen: List[int] = [self.session]
        if state:
            self._restore(state)

    # -- state --

    def _new_window(self, why: str) -> Dict[str, Any]:
        return {"pointer": self.pointer, "why": why, "clears": 0, "non_clears": 0, "outcomes": []}

    def _restore(self, st: Mapping[str, Any]) -> None:
        if int(st.get("pointer", -1)) != self.pointer:
            raise FrontierError("pointer mismatch while restoring")
        self.line_failed = {int(k): int(v) for k, v in dict(st.get("line_failed") or {}).items()}
        self.stalled = bool(st.get("stalled"))
        self.stalled_pointer = st.get("stalled_pointer")
        self.next_episode = int(st.get("next_episode", 0))
        self.attempt_counter = int(st.get("attempt_counter", 0))
        self.moves_all = [dict(m) for m in (st.get("moves") or [])]
        self.sessions_seen = sorted(set(int(x) for x in (st.get("sessions") or [])) | {self.session})
        if self.stalled:
            raise FrontierError("the line is stalled: no session may resume it")

    def held(self) -> bool:
        return self.session_failed.get(self.pointer, 0) >= G.ATTEMPTS_PER_SESSION

    def line_attempts_at(self, pointer: Optional[int] = None) -> int:
        p = self.pointer if pointer is None else int(pointer)
        return self.line_failed.get(p, 0) + sum(1 for a in self.attempts if a["pointer"] == p and a["result"] == "MOVED")

    def next_attempt_index(self) -> int:
        """a: the line-wide attempt index at the current pointer (1-based): failed attempts over the line at it, plus one."""
        return self.line_failed.get(self.pointer, 0) + 1

    def state(self) -> Dict[str, Any]:
        base = super().state()
        base.update({"frontier": FRONTIER_CONTRACT, "session": self.session, "sessions": list(self.sessions_seen), "pointer": self.pointer, "moves": list(self.moves_all),
                     "moves_this_session": list(self.moves), "attempts_this_session": [self._attempt_summary(a) for a in self.attempts], "line_failed": {str(k): v for k, v in sorted(self.line_failed.items())},
                     "session_failed": {str(k): v for k, v in sorted(self.session_failed.items())}, "held": self.held(), "stalled": self.stalled, "stalled_pointer": self.stalled_pointer,
                     "next_episode": self.next_episode, "attempt_counter": self.attempt_counter, "window": {k: v for k, v in self.window.items() if k != "outcomes"} | {"size": len(self.window["outcomes"])},
                     "windows": len(self.windows), "after_trigger": self.after_trigger, "held_triggers": self.held_triggers, "pending_trigger": self.pending is not None,
                     "landings": list(self.landings), "bounds": {"per_session": G.ATTEMPTS_PER_SESSION, "per_line": G.ATTEMPTS_PER_LINE}})
        return base

    @staticmethod
    def _attempt_summary(a: Mapping[str, Any]) -> Dict[str, Any]:
        return {k: a.get(k) for k in ("n", "a", "pointer", "session", "result", "new_pointer", "strip_clears", "strip_non_clears", "failed_landing", "episodes_before")}

    def carried_state(self) -> Dict[str, Any]:
        """What a later session restores (decision R14): the pointer, the line attempt counts, the moves, STALLED, the global counters."""
        return {"frontier": FRONTIER_CONTRACT, "pointer": self.pointer, "line_failed": {str(k): v for k, v in sorted(self.line_failed.items())}, "moves": list(self.moves_all),
                "stalled": self.stalled, "stalled_pointer": self.stalled_pointer, "next_episode": self.next_episode, "attempt_counter": self.attempt_counter,
                "sessions": list(self.sessions_seen), "landings": list(self.landings)}

    # -- starts (g1's distribution on g2 keys) --

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

    # -- outcomes and the window --

    def record(self, start: CU.Start, cleared: bool) -> Optional[Dict[str, Any]]:
        """One finished training episode. Returns an event record for the log when the window changed state (trigger, void, held_trigger), else None."""
        if start.region != "strip":
            self.outside += 1
            return None
        if start.pointer != self.pointer:
            self.stale += 1
            self.stale_clears += int(bool(cleared))
            return None
        self.counted += 1
        if self.pending is not None:
            self.after_trigger += 1
            return {"event": "after_trigger", "pointer": self.pointer, "clear": bool(cleared)}
        w = self.window
        w["outcomes"].append(1 if cleared else 0)
        w["clears"] += int(bool(cleared))
        w["non_clears"] += int(not cleared)
        if w["clears"] >= G.TRIGGER_CLEARS:
            w["result"] = "held_trigger" if (self.held() or self.stalled) else "trigger"
            self.windows.append(w)
            ev = {"event": w["result"], "pointer": self.pointer, "clears": w["clears"], "non_clears": w["non_clears"], "size": len(w["outcomes"]), "window": len(self.windows) - 1}
            if w["result"] == "trigger":
                self.pending = {"pointer": self.pointer, "window": len(self.windows) - 1, "clears": w["clears"], "non_clears": w["non_clears"], "a": self.next_attempt_index()}
            else:
                self.held_triggers += 1
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

    def begin_attempt(self, *, episodes_before: int) -> Dict[str, Any]:
        """The attempt the pending trigger earned. Returns its record skeleton; `finish_attempt` closes it."""
        if self.pending is None:
            raise FrontierError("no pending trigger")
        if self.held() or self.stalled:
            raise FrontierError("an attempt while HELD or STALLED")
        self.attempt_counter += 1
        a = self.next_attempt_index()
        rec = {"n": self.attempt_counter, "a": a, "pointer": self.pointer, "session": self.session, "trigger": dict(self.pending), "episodes_before": int(episodes_before),
               "rechecks_planned": landings_behind(self.pointer, self.landings), "line_failed_before": self.line_failed.get(self.pointer, 0),
               "session_failed_before": self.session_failed.get(self.pointer, 0), "result": None}
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
            move = {"from": p, "to": new, "attempt": rec["n"], "a": rec["a"], "session": self.session}
            self.moves.append(move)
            self.moves_all.append(move)
            self.pointer = new
            self.window = self._new_window("move")
        elif result in ("FAILED_STRIP", "BLOCKED_BY_RECHECK"):
            self.line_failed[p] = self.line_failed.get(p, 0) + 1
            self.session_failed[p] = self.session_failed.get(p, 0) + 1
            if self.line_failed[p] >= G.ATTEMPTS_PER_LINE:
                self.stalled, self.stalled_pointer = True, p
            self.window = self._new_window("attempt")
        else:                                           # INTERRUPTED: neither pass nor fail; the window restarts all the same
            self.window = self._new_window("interrupted")
        rec.update({"held_after": self.held(), "stalled_after": self.stalled, "line_failed_after": self.line_failed.get(p, 0), "session_failed_after": self.session_failed.get(p, 0)})
        self.attempts.append(rec)
        return rec


# -- the rebuild from records (verify-run) --------------------------------------------------------------------------------------------


def replay_history(episodes: Sequence[Mapping[str, Any]], attempts: Sequence[Mapping[str, Any]], lengths: Mapping[str, int], *, session: int, state: Optional[Mapping[str, Any]] = None,
                   landings: Sequence[int] = G.LANDINGS) -> Dict[str, Any]:
    """Rebuild the pointer, the windows and the attempt history from the completion-ordered training records and the attempt records alone, and re-derive every
    start from its keys. An attempt with `episodes_before == i` is applied before training episode i."""
    fr = Frontier(lengths, session=session, landings=landings, state=state)
    problems: List[str] = []
    by_before: Dict[int, List[Mapping[str, Any]]] = {}
    for a in attempts:
        by_before.setdefault(int(a["episodes_before"]), []).append(a)
    moves: List[Tuple[int, int]] = []
    triggers = 0

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
            if fr.held() and a["result"] in ("MOVED", "FAILED_STRIP", "BLOCKED_BY_RECHECK"):
                problems.append(f"attempt {a['n']}: an attempt while HELD")
            if fr.stalled:
                problems.append(f"attempt {a['n']}: an attempt after STALLED")
            rec = fr.begin_attempt(episodes_before=i)
            triggers += 1
            rechecks = {int(k): v for k, v in dict(a.get("rechecks") or {}).items()}
            try:
                fr.finish_attempt(rec, str(a["result"]), strip={"clears": a.get("strip_clears", 0), "non_clears": a.get("strip_non_clears", 0), "passed": a.get("strip_passed")},
                                  rechecks=rechecks, failed_landing=a.get("failed_landing"))
            except FrontierError as exc:
                problems.append(f"attempt {a['n']}: {exc}")
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
    for p, n in fr.line_failed.items():
        if n > G.ATTEMPTS_PER_LINE:
            problems.append(f"pointer {p}: {n} failed attempts over the line (bound {G.ATTEMPTS_PER_LINE})")
    for p, n in fr.session_failed.items():
        if n > G.ATTEMPTS_PER_SESSION:
            problems.append(f"pointer {p}: {n} failed attempts in the session (bound {G.ATTEMPTS_PER_SESSION})")
    return {"pointer": fr.pointer, "moves": moves, "attempts": len(fr.attempts), "triggers": triggers, "windows": len(fr.windows), "state": fr.state(), "problems": problems}


def contract_description() -> Dict[str, Any]:
    return dict(G.frontier_description(), start_distribution=CU.contract_description() | {"keys": G.KEYS["start"]})


def contract_digest() -> str:
    return hashlib.sha256(json.dumps(contract_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
