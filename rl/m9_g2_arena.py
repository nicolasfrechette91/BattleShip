"""M9-g2: the g2 episode context (the g1 sticky rule on g2 keys) and the g2 arena (a slot subset, a pause, in-flight accounting).

Everything here is a thin layer over rl/m9_vec (imported unchanged):

* `G2EpisodeCtx` is `m9_vec.EpisodeCtx` with `choose` applying rl/m9_sticky's rule (p = 0.25, nothing repeats at tick 0, the first policy word after a
  prefix may repeat the prefix's last word) on the g2 key `<label>|<tick>` (decisions R1). The SUBMITTED word is the record; the sampled word and the mask
  are metadata; `mask_from_keys` and `check_record` rebuild and check a record from its keys.
* `G2Arena` is `m9_vec.Arena` restricted to a subset of the pool's slots (the six preparing slots run an attempt while the four playing slots stay parked),
  with a `paused` flag (no dispatch while an attempt runs), in-flight command counts per slot (a slot is handed over only when every command sent to it has
  been answered, so no reply of a probe can reach the training vector), `withdraw_parked` (parked training starts are closed and recorded) and
  `activate` building a `G2EpisodeCtx`.
* `G2TickBudget` adds the probe split to `m9_vec.TickBudget`.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import m9_contract as C
import m9_g2_contract as G
import m9_sticky as S
import m9_vec as V

ARENA_CONTRACT = "m9_g2_arena_v1"


# -- the sticky rule on g2 keys ------------------------------------------------------------------------------------------------------


def hit(label: str, tick: int, p: float = C.STICKY_P) -> bool:
    return S.uniform(G.sticky_key(label, tick)) < p


def submit(label: Optional[str], tick: int, sampled: int, prev: Optional[int], p: float = C.STICKY_P) -> Tuple[int, bool]:
    """g1's rule (rl/m9_sticky.submit) with the g2 key: (submitted word, sticky flag)."""
    if label is None or prev is None or tick < 1:
        return int(sampled), False
    if hit(label, tick, p):
        return int(prev), True
    return int(sampled), False


def mask_from_keys(label: str, first_tick: int, n: int, p: float = C.STICKY_P) -> bytes:
    return bytes(1 if (t >= 1 and hit(label, t, p)) else 0 for t in range(first_tick, first_tick + n))


def check_record(label: Optional[str], first_tick: int, sampled: bytes, submitted: bytes, mask: bytes, prev_word: Optional[int], p: float = C.STICKY_P) -> List[str]:
    """Problems of one recorded policy phase under the g2 keys (the logic of rl/m9_sticky.check_record)."""
    problems: List[str] = []
    n = len(submitted)
    if not (len(sampled) == n == len(mask)):
        return [f"lengths differ: sampled {len(sampled)} submitted {n} mask {len(mask)}"]
    if label is None:
        if any(mask):
            problems.append("an unperturbed episode carries sticky flags")
        if sampled != submitted:
            problems.append("an unperturbed episode submitted a word the policy did not sample")
        return problems
    want = mask_from_keys(label, first_tick, n, p)
    if want != mask:
        problems.append(f"sticky mask not reproducible from its keys (first difference at index {next(i for i in range(n) if want[i] != mask[i])})")
    prev = prev_word
    for i in range(n):
        if mask[i]:
            if prev is None or submitted[i] != prev:
                problems.append(f"sticky tick {first_tick + i} did not repeat the previous submitted word")
                break
        elif submitted[i] != sampled[i]:
            problems.append(f"tick {first_tick + i} submitted a word other than the sampled one without a sticky flag")
            break
        prev = submitted[i]
    return problems


# -- the episode context ----------------------------------------------------------------------------------------------------------


class G2EpisodeCtx(V.EpisodeCtx):
    def choose(self, sampled: int) -> int:
        word, sticky = submit(self.job.label, self.tick, int(sampled), self.prev_word)
        self.sampled.append(int(sampled))
        self.sub.append(word)
        self.mask.append(1 if sticky else 0)
        self.prev_word = word
        return word


class G2TickBudget(V.TickBudget):
    def __init__(self, cap: int):
        super().__init__(cap)
        self.probe = 0

    def charge_probe(self, prefix: int, policy: int) -> None:
        """Native ticks of an attempt (already consumed in the probe arena's own budget) charged to this phase's cap."""
        self.consumed += int(prefix) + int(policy)
        self.probe += int(prefix) + int(policy)


# -- the arena ------------------------------------------------------------------------------------------------------------------------


class G2Arena(V.Arena):
    """`m9_vec.Arena` over a subset of the pool's slots, with a pause and in-flight accounting. With `slots=None` the subset is every slot."""

    def __init__(self, pool: Any, tables: Mapping[str, Any], source: Any, budget: V.TickBudget, *, slots: Optional[Sequence[int]] = None, **kw: Any):
        super().__init__(pool, tables, source, budget, **kw)
        self.slots: List[int] = sorted(range(pool.n) if slots is None else slots)
        self.subset: Set[int] = set(self.slots)
        self.paused = False
        self.inflight: Dict[int, int] = {s: 0 for s in range(pool.n)}
        self.withdrawn: List[Dict[str, Any]] = []
        self.sent = {"stage": 0, "step": 0, "close": 0}

    # -- accounting --

    def alive_slots(self) -> int:
        return sum(1 for i in self.slots if self.pool.alive(i))

    def staging_count(self) -> int:
        return sum(1 for i in self.slots if self.state[i] == "staging")

    def process_count(self) -> int:
        return sum(1 for i in self.slots if self.state[i] in ("staging", "ready", "active"))

    def outstanding(self) -> int:
        return sum(self.inflight[i] for i in self.slots)

    def settled(self) -> bool:
        return self.outstanding() == 0

    def _send(self, slot: int, message: Tuple[Any, ...]) -> None:
        self.inflight[slot] += 1
        self.sent[message[0]] = self.sent.get(message[0], 0) + 1
        self.pool.send(slot, message)

    # -- dispatch (g1's, restricted to the subset and the pause) --

    def dispatch(self) -> None:
        if self.source_done or self.paused:
            return
        for slot in self.slots:
            if self.state[slot] != "idle" or not self.pool.alive(slot):
                continue
            if self.max_staging is not None and self.staging_count() + len(self.ready) >= self.max_staging:
                break
            if self.max_procs is not None and self.process_count() >= self.max_procs:
                break
            job = self.source.next_job(self)
            if job is None:
                self.source_done = True
                break
            if not self.budget.can_stage(job.start.tau):
                self.source.unget(job)
                self.source_done = True
                break
            self.budget.reserve(job.start.tau)
            self.job[slot] = job
            self.state[slot] = "staging"
            self.t_dispatch[slot] = self.now()
            self.dispatched += 1
            self._send(slot, ("stage", {"episode": job.job_id, "lineage": job.start.lineage, "tau": int(job.start.tau), "label": job.label}))

    def handle(self, slot: int, kind: str, payload: Dict[str, Any]) -> Optional[Tuple[int, str, Dict[str, Any]]]:
        if kind not in ("died", "fatal") and self.inflight.get(slot, 0) > 0:
            self.inflight[slot] -= 1
        if slot not in self.subset:
            if kind in ("died", "fatal"):
                # a worker outside this arena's subset died while this arena owned the pool's polling (an attempt): the other arena cannot learn of it
                # in time, so the session stops here (INCOMPLETE), never silently
                raise V.CapStop(f"a worker outside the arena's slots is {kind} during an attempt (slot {slot}): {str(payload)[:200]}", valid=False)
            # a reply from a slot this arena does not own (never expected once the slots are settled): reported to the caller, never consumed
            self.stale_events += 1
            return slot, kind, payload
        return super().handle(slot, kind, payload)

    def pump(self, timeout: float) -> List[Tuple[int, str, Dict[str, Any]]]:
        """g1's pump, with one change: every event of a polled batch is handled before a stop raised by one of them propagates, so no already-received
        reply is lost (the in-flight counts and the slot states stay exact, and the slots can settle after the stop)."""
        if self.guard:
            self.guard()
        self.dispatch()
        out: List[Tuple[int, str, Dict[str, Any]]] = []
        first: Optional[BaseException] = None
        for slot, kind, payload in self.pool.poll(timeout):
            try:
                r = self.handle(slot, kind, payload)
            except (V.CapStop, V.IntegrityStop) as exc:
                if first is None:
                    first = exc
                continue
            if r is not None:
                out.append(r)
        if first is not None:
            raise first
        if self.budget.exhausted():
            raise V.CapStop("native tick cap", valid=True)
        self.dispatch()
        return out

    def activate(self, slot: int) -> V.EpisodeCtx:
        payload = self.ready_payload.pop(slot)
        job = self.job[slot]
        assert job is not None
        ctx = G2EpisodeCtx(job, slot, payload, self.tables[payload["lineage"]].words)
        self.state[slot] = "active"
        self.active[slot] = ctx
        return ctx

    def send_step(self, ctx: V.EpisodeCtx, sampled_word: int) -> int:
        word = ctx.choose(sampled_word)
        self._send(ctx.slot, ("step", {"word": word}))
        return word

    def close_slot(self, slot: int) -> None:
        """Close whatever the slot holds (a parked start or an active episode): the worker releases its BattleShip; the slot is idle for this arena."""
        self.active.pop(slot, None)
        if slot in self.ready:
            self.ready.remove(slot)
        self.ready_payload.pop(slot, None)
        self.job[slot] = None
        if self.state[slot] != "dead":
            self.state[slot] = "idle"
        if self.pool.alive(slot):
            try:
                self._send(slot, ("close", {}))
            except (OSError, BrokenPipeError):
                pass

    def close_unfinished(self) -> None:
        for slot in self.slots:
            if self.state[slot] in ("ready", "active", "staging") and self.pool.alive(slot):
                self.close_slot(slot)

    # -- the pause --

    def drain_staging(self, timeout: float = 0.2) -> None:
        """Pump until no subset slot is staging (every stage command has replied). Dispatch is paused by the caller."""
        while self.staging_count() > 0:
            leftovers = self.pump(timeout)
            if leftovers:
                raise RuntimeError(f"unexpected events while draining the staging slots: {[(s, k) for s, k, _p in leftovers][:4]}")

    def withdraw_parked(self, reason: str, note: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """Close every parked (READY) start of the subset; each is recorded as withdrawn (its episode number is never drawn again)."""
        out: List[Dict[str, Any]] = []
        for slot in list(self.ready):
            job = self.job[slot]
            payload = self.ready_payload.get(slot) or {}
            rec = {"episode": job.job_id if job else None, "tau": int(job.start.tau) if job else None, "lineage": job.start.lineage if job else None,
                   "start": job.start.to_json() if job is not None and hasattr(job.start, "to_json") else None, "slot": slot, "reason": reason,
                   "prefix_ticks_consumed": int(payload.get("ticks", 0)), **dict(note)}
            out.append(rec)
            self.withdrawn.append(rec)
            self.close_slot(slot)
        return out

    def wait_settled(self, timeout: float = 0.2, *, use_guard: bool = True, max_wall_s: Optional[float] = None) -> None:
        """Pump until every command sent to a subset slot has been answered. With `use_guard` False (the cleanup of an interrupted attempt) the phase guard is
        not consulted and the wait is bounded by `max_wall_s` of the arena's clock; a slot whose worker is dead is not waited for."""
        t0 = self.now()
        while True:
            pending = [s for s in self.slots if self.inflight[s] > 0 and self.pool.alive(s)]
            if not pending:
                return
            for slot, kind, payload in self.pool.poll(timeout):
                try:
                    self.handle(slot, kind, payload)
                except V.CapStop:
                    if use_guard:
                        raise
            if use_guard and self.guard:
                self.guard()
            if max_wall_s is not None and self.now() - t0 > max_wall_s:
                return

    def idle_subset(self) -> bool:
        return all(self.state[s] in ("idle", "dead") for s in self.slots)

    def summary(self) -> Dict[str, Any]:
        sm = super().summary()
        sm.update({"slots": list(self.slots), "withdrawn": len(self.withdrawn), "sent": dict(self.sent), "outstanding": self.outstanding()})
        return sm


def contract_description() -> Dict[str, Any]:
    return {"contract": ARENA_CONTRACT, "sticky": "rl/m9_sticky's rule on the key <label>|<tick>", "subset": "an arena owns a subset of the pool's slots",
            "pause": "no dispatch while paused; parked starts withdrawn and recorded; slots handed over only when settled (no command unanswered)"}
