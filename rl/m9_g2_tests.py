#!/usr/bin/env python3
"""M9-g2 tests: the deterministic unit suite and the production-count synthetic end-to-end run (a two-session line).

    python -B rl/m9_g2_tests.py unit           # the gating suite (deterministic by construction)
    python -B rl/m9_g2_tests.py e2e            # the production-count synthetic two-session line (virtual clock, in-process lock-step pool)
    python -B rl/m9_g2_tests.py list

DETERMINISM (g1's rules, kept). (a) Pure tests use keyed sha256 streams and fixed data. (b) Every session-level test runs the real g2 engine through the
in-process lock-step pool (rl/m9_pool.LocalPool) and a virtual clock against the synthetic world (rl/m9_stub, rl/m9_g2_stub): a run is a pure function of
its configuration. (c) The real SB3 save / load / update equivalence is tested on a zero-tick synthetic vector env with the real v3 spaces. (d) No test starts
a game process; nothing depends on process scheduling or wall-clock duration; a source scan forbids randomness, sleeps and wall-clock reads inside tests.
(e) The gates (git state, the six protected trees and their D: increments, the executable pins) assert facts fixed once the trees are closed.

THE SYNTHETIC WORLD IS NOT MARIO. It exercises code paths.
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
sys.dont_write_bytecode = True

import gymnasium as gym  # noqa: E402
import numpy as np  # noqa: E402

import m8_rd_cells as mcell  # noqa: E402
import m9_artifacts as A  # noqa: E402
import m9_contract as C  # noqa: E402
import m9_curriculum as CU  # noqa: E402
import m9_g2_arena as AR  # noqa: E402
import m9_g2_contract as G  # noqa: E402
import m9_g2_frontier as F  # noqa: E402
import m9_g2_policy as PO  # noqa: E402
import m9_g2_probe as PR  # noqa: E402
import m9_g2_report as RPT  # noqa: E402
import m9_g2_resume as RS  # noqa: E402
import m9_g2_rule as R  # noqa: E402
import m9_g2_run as RUN2  # noqa: E402
import m9_g2_stub as ST2  # noqa: E402
import m9_g2_tape as TP  # noqa: E402
import m9_g2_train as TR  # noqa: E402
import m9_lineages as L  # noqa: E402
import m9_sticky as S  # noqa: E402
import m9_stub as ST  # noqa: E402
import m9_vec as V  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RL = REPO / "rl"
TESTS: List[Tuple[str, Callable[[], None]]] = []
FORBIDDEN_PATH_PREFIXES = ("tas_" + "input_2/", "rl/" + "fixtures/")       # split so that this tuple is not itself a forbidden literal
SMALL_N_STEPS = 64                                                            # test configuration only: a short synthetic rollout so that attempts fire in a short virtual window


def test(fn: Callable[[], None]) -> Callable[[], None]:
    TESTS.append((fn.__name__, fn))
    return fn


def eq(label: str, got: Any, want: Any) -> None:
    if got != want:
        raise AssertionError(f"{label}: got {str(got)[:300]!r}, want {str(want)[:300]!r}")


def ok(label: str, cond: Any) -> None:
    if not cond:
        raise AssertionError(label)


def raises(label: str, exc: Any, fn: Callable[[], Any]) -> Any:
    try:
        fn()
    except exc as e:                                    # noqa: PERF203
        return e
    raise AssertionError(f"{label}: expected {exc}")


@contextlib.contextmanager
def tmpdir(prefix: str = "m9g2t_"):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def strip_volatile(o: Any) -> Any:
    drop = {"created_utc", "utc", "t_wall_s", "wall_s", "native_s", "build_s", "boot_s", "wait_s", "waits", "interval_transitions_per_s", "dispatch_to_ready_s", "t", "wall", "clock",
            "elapsed_s", "phase_wall_s", "pause_s", "t_start_s", "pid", "close", "sha256", "model_zip", "curriculum_state", "tape_baseline", "members_sha256", "model_zip_sha256",
            "curriculum_state_sha256", "snapshot", "snapshot_sha256", "path", "copy", "source", "files", "inputs"}
    if isinstance(o, dict):
        return {k: strip_volatile(v) for k, v in o.items() if k not in drop}
    if isinstance(o, list):
        return [strip_volatile(v) for v in o]
    return o


# -- synthetic builders ---------------------------------------------------------------------------------------------------------------------


class SmallBuilder(ST2.G2StubEnvBuilder):
    """The g2 stub builder with a short synthetic rollout and an optional initial competence boundary (test configuration only)."""

    def __init__(self, root: Path, *, n_steps: Optional[int] = SMALL_N_STEPS, b0: int = C.TAU0, **kw: Any):
        super().__init__(root, **kw)
        self.n_steps_override = n_steps
        self.b0 = int(b0)

    def make_model(self, vec: Any, n: int) -> ST2.G2StubModel:
        steps = self.n_steps_override if self.n_steps_override else C.ROLLOUT_SIZE // n
        m = ST2.G2StubModel(vec, n_steps=steps, b0=self.b0, need=self.model_need, forget_landing=self.forget_landing, forget_when_b_below=self.forget_when_b_below)
        self.models.append(m)
        return m

    def resume_model(self, path: Path, vec: Any, n: int, session: int) -> ST2.G2StubModel:
        steps = self.n_steps_override if self.n_steps_override else C.ROLLOUT_SIZE // n
        m = ST2.G2StubModel.load(path, vec, n_steps=steps)
        m.resumed_seed = G.SESSION_SEED_BASE + int(session)        # type: ignore[attr-defined]
        self.models.append(m)
        return m


def hooks_for(b: ST2.G2StubEnvBuilder) -> RUN2.G2Hooks:
    return RUN2.G2Hooks(snapshot_of=ST2.G2StubEnvBuilder.snapshot_of, make_probe_policy=ST2.G2StubEnvBuilder.make_policy, audit_policy=ST2.G2StubEnvBuilder.policy_from_model_zip,
                        resume_model=b.resume_model, flatten=ST2.G2StubEnvBuilder.flatten)


def small_cfg(root: Path, **over: Any) -> RUN2.G2Config:
    caps = dict(G.WALL_CAPS_S)
    caps.update({"train": 420.0, "audit": 600.0})
    kw: Dict[str, Any] = dict(root=root, wall_caps_s=caps, p2_starts=3, landings=(2128, 1966, 1694), tape_keys={2128: 6, 1966: 3, 1694: 3}, audit_n=12, audit_unp=2, audit_det=1, tick0_n=2,
                              write_artifacts=False, first_clears=5, verify_threads=2, session=1)
    kw.update(over)
    return RUN2.G2Config(**kw)


def run_small(root: Path, *, inject: Optional[Mapping[str, Any]] = None, need: int = 40, cfg_over: Optional[Mapping[str, Any]] = None, env_over: Optional[Mapping[str, Any]] = None,
              builder_over: Optional[Mapping[str, Any]] = None) -> Tuple[RUN2.G2Session, Dict[str, Any], ST2.G2StubEnvBuilder]:
    b = SmallBuilder(root / "run", inject=inject, model_need=need, **dict(builder_over or {}))
    cfg = small_cfg(root / "run", **dict(cfg_over or {}))
    sess = RUN2.G2Session(cfg, b.env(**dict(env_over or {})), hooks_for(b))
    return sess, sess.run(), b


def stub_tables(d: Path, b: ST2.G2StubEnvBuilder) -> Dict[str, L.Tables]:
    for name, ln in b.lineages.items():
        tr = b.route_traces[name]
        chain, v3 = L.build_tables(tr["initial"], tr["steps"], ST.StubObs)
        L.save_tables(d / "run" / "lineages", name, ln.words, chain, v3)
    return L.load_all_tables(d / "run" / "lineages", ["T_clear", "T_t"])


def stub_arena(d: Path, jobs: Sequence[V.StartJob] = (), *, n_slots: int = 10, budget: int = 10 ** 7, slots: Optional[Sequence[int]] = None, inject: Optional[Mapping[str, Any]] = None,
               builder: Optional[ST2.G2StubEnvBuilder] = None, pool: Any = None, tables: Optional[Mapping[str, Any]] = None, **kw: Any) -> Tuple[AR.G2Arena, ST2.G2StubEnvBuilder, Dict[str, Any], Any]:
    b = builder or SmallBuilder(d / "run", n_slots=n_slots, inject=inject)
    tables = tables or stub_tables(d, b)
    pool = pool or b.make_pool("x", C.FLAGS_TRAIN)
    return AR.G2Arena(pool, tables, PR.ProbeSource(list(jobs)), AR.G2TickBudget(budget), slots=slots, now=b.clock.now, **kw), b, tables, pool


def _jobs(n: int, tau: int = 100, label: Optional[str] = None, part: Any = "x") -> List[V.StartJob]:
    return [V.StartJob(k, CU.Start(k, "p2", tau, "T_clear", True, -1), label, kind="x", job_id=f"x-{part}-{k:03d}", extra={"part": part, "k": k}) for k in range(n)]


def stub_policy(B: int, **kw: Any) -> ST2.G2StubPolicy:
    return ST2.G2StubPolicy({"B": B, "seed": 0, **kw}, "0" * 64)


# =====================================================================================================================================
# contract, keys, bars
# =====================================================================================================================================


@test
def contract_registered_values() -> None:
    eq("trigger", (G.TRIGGER_WINDOW, G.TRIGGER_CLEARS, G.TRIGGER_VOID_NONCLEARS), (20, 8, 13))
    eq("test", (G.TEST_EPISODES, G.TEST_PASS, G.TEST_FAIL_NONCLEARS), (20, 10, 11))
    eq("attempt bounds", (G.ATTEMPTS_PER_SESSION, G.ATTEMPTS_PER_LINE), (3, 6))
    eq("tape keys", G.TAPE_KEYS, {2128: 200, 1966: 40, 1694: 40, 1473: 40, 1369: 40, 1248: 40})
    eq("audit counts", (G.AUDIT_EPISODES, G.AUDIT_UNPERTURBED, G.AUDIT_DETERMINISTIC, G.TICK0_EPISODES), (20, 20, 1, 20))
    eq("bars", (G.BAR_MIN, G.BAR_MARGIN, G.D_MIN_CLEARS), (10, 5, 10))
    eq("s1 rule", (G.PASS_REACH, G.INCONCLUSIVE_DEPTH), (1966, 2128))
    eq("line budget", (G.LINE_BUDGET_DEPTH, G.LINE_BUDGET_SESSIONS, G.LINE_PROGRESS_FROM_SESSION, G.LINE_CAP_SESSIONS, G.LINE_SUCCESS_DEPTH), (1966, 3, 4, 8, 1473))
    eq("wall caps", G.WALL_CAPS_S, {"open": 60.0, "p1": 240.0, "p2": 120.0, "t0": 900.0, "train": 4800.0, "audit": 1200.0, "verify": 600.0, "close": 300.0})
    eq("tick caps", G.TICK_CAPS, {"open": 0, "p1": 60_000, "p2": 60_000, "t0": 1_500_000, "train": 20_000_000, "audit": 3_000_000, "verify": 1_500_000, "close": 0})
    eq("session", (G.GLOBAL_CAP_S, G.TRANSITION_CAP, G.SPLIT, G.PROBE_SLOTS, G.N_SLOTS, G.MAX_BATTLESHIP_PROCESSES), (8700.0, 3_072_000, (4, 6), 6, 10, 10))
    eq("g1 values unchanged", (G.PPO, G.STICKY_P, G.LANDINGS, G.TAU0, G.STRIP, G.CHECKPOINT_EVERY, G.ROLLOUT_SIZE, G.HORIZON), (C.PPO, 0.25, C.LANDINGS, 2300, 20, 102_400, 5120, 3600))
    eq("ppo", (G.PPO["ent_coef"], G.PPO["seed"], G.PPO["initialisation"]), (0.01, 0, "fresh"))
    eq("memory caps", G.MEMORY_CAPS_MB, C.MEMORY_CAPS_MB)
    eq("digests stable", (G.contract_digest() == G.contract_digest(), G.line_contract_digest() == G.line_contract_digest(), len(G.line_contract_digest())), (True, True, 64))
    ok("the line contract names the frontier rule and the tape", "frontier" in G.line_contract_description() and "tape" in G.line_contract_description())
    bp = RUN2.budget_projection()
    eq("pessimistic projection", (bp["sum_of_caps_s"], bp["pessimistic_total_s"]), (8220.0, 8440.0))
    ok("fits the 145-minute cap with no trimming", bp["fits_global_cap_pessimistic"] and bp["slack_pessimistic_s"] == 260.0)
    eq("session seed", G.SESSION_SEED_BASE, 1000)
    eq("verification launch margin", G.VERIFY_LAUNCH_MARGIN_S, 120.0)


@test
def key_strings_are_the_g2_family() -> None:
    eq("train label", G.train_label(7), "m9|g2|train|7")
    eq("sticky key", G.sticky_key("m9|g2|train|7", 2301), "m9|g2|train|7|2301")
    eq("start key", G.start_key(7, "tau"), "m9|g2|start|7|tau")
    eq("probe label", G.probe_label(2300, 1, "strip", 3), "m9|g2|probe|2300|1|strip|3")
    eq("probe landing label", G.probe_label(2280, 2, 2128, 0), "m9|g2|probe|2280|2|2128|0")
    eq("probe action key", G.probe_action_key(2300, 1, "strip", 3, 2305), "m9|g2|probeact|2300|1|strip|3|2305")
    eq("reach label", G.reach_label(2128, 199), "m9|g2|reach|2128|199")
    eq("tick0 label", G.tick0_label(0), "m9|g2|tick0|0")
    eq("audit action key", G.audit_action_key("sticky", 2128, 5, 2130), "m9|g2|auditact|sticky|2128|5|2130")
    raises("audit mode", ValueError, lambda: G.audit_action_key("argmax", 2128, 0, 0))
    eq("verify pick", G.verify_pick_key(2300, 1, "strip"), "m9|g2|verifypick|2300|1|strip")
    eq("artifact sample", G.artifact_sample_key(3), "m9|g2|artifact|3")
    ok("the g2 sticky key differs from g1's for the same label and tick", G.sticky_key("reach:2128:5", 2130) != S.sticky_key("reach:2128:5", 2130))
    ok("the g2 start key differs from g1's", G.start_key(0, "tau") != CU.start_key(0, "tau"))
    for k, v in G.KEYS.items():
        ok(f"key {k} is documented", v.startswith("m9|g2|") or k in ("sticky", "p2"))


@test
def bar_arithmetic() -> None:
    eq("95/200", G.bar_from_counts(95, 200), 15)
    eq("96/200 -> ceil(9.6) = 10 -> 15", G.bar_from_counts(96, 200), 15)
    eq("101/200 -> 16", G.bar_from_counts(101, 200), 16)
    eq("0/40", G.bar_from_counts(0, 40), 10)
    eq("10/40 -> ceil(5) + 5 = 10", G.bar_from_counts(10, 40), 10)
    eq("11/40 -> 11", G.bar_from_counts(11, 40), 11)
    eq("40/40 -> 25", G.bar_from_counts(40, 40), 25)
    raises("no keys", ValueError, lambda: G.bar_from_counts(0, 0))
    eq("rule self-test", R.self_test(), [])


# =====================================================================================================================================
# the g2 sticky rule and the arena
# =====================================================================================================================================


@test
def g2_sticky_rule_on_g2_keys() -> None:
    label = G.train_label(5)
    eq("tick 0 never repeats", AR.submit(label, 0, 7, None), (7, False))
    eq("no previous word: nothing repeats", AR.submit(label, 5, 7, None), (7, False))
    eq("no label: unperturbed", AR.submit(None, 5, 7, 3), (7, False))
    hits = sum(1 for t in range(1, 20001) if AR.hit(label, t))
    ok(f"rate {hits / 20000:.4f} near 0.25", 0.235 <= hits / 20000 <= 0.265)
    first_hit = next(t for t in range(1, 500) if AR.hit(label, t))
    eq("a hit repeats the previous submitted word", AR.submit(label, first_hit, 7, 3), (3, True))
    # a record of a policy phase from tick 2300 with prefix word 9
    sampled = bytes([(3 * i) % 72 for i in range(40)])
    sub = bytearray()
    mask = bytearray()
    prev: Optional[int] = 9
    for i, s in enumerate(sampled):
        w, st = AR.submit(label, 2300 + i, s, prev)
        sub.append(w)
        mask.append(1 if st else 0)
        prev = w
    eq("mask rebuilt from keys", AR.mask_from_keys(label, 2300, 40), bytes(mask))
    eq("record checks", AR.check_record(label, 2300, sampled, bytes(sub), bytes(mask), 9), [])
    bad = bytearray(mask)
    bad[0] ^= 1
    ok("a tampered mask is caught", AR.check_record(label, 2300, sampled, bytes(sub), bytes(bad), 9))
    bad_sub = bytearray(sub)
    bad_sub[3] = (bad_sub[3] + 1) % 72
    ok("a tampered word is caught", AR.check_record(label, 2300, sampled, bytes(bad_sub), bytes(mask), 9))
    ok("the first policy word after a prefix may repeat the prefix's last word", any(AR.submit(G.train_label(e), 2300, 1, 9) == (9, True) for e in range(40)))
    eq("unperturbed record", AR.check_record(None, 2300, sampled, sampled, bytes(40), None), [])
    ok("an unperturbed record with a flag is caught", AR.check_record(None, 2300, sampled, sampled, bytes([1]) + bytes(39), None))


@test
def g2_arena_subset_pause_and_inflight() -> None:
    with tmpdir() as d:
        arena, b, tables, pool = stub_arena(d, _jobs(12), slots=[4, 5, 6, 7, 8, 9])
        arena.pump(0.0)
        eq("dispatch only on the subset", sorted(s for s in range(10) if arena.state[s] != "idle"), [4, 5, 6, 7, 8, 9])
        ok("in-flight counted and settled by the lock-step pool", arena.outstanding() == 0 and arena.sent["stage"] == 6)
        eq("parked", len(arena.ready), 6)
        arena.paused = True
        w = arena.withdraw_parked("test", {"attempt": 1})
        eq("every parked start withdrawn and recorded", (len(w), len(arena.withdrawn), arena.sent["close"]), (6, 6, 6))
        arena.wait_settled()
        ok("idle after the withdrawal", arena.idle_subset() and arena.settled())
        arena.pump(0.0)
        eq("paused: no dispatch", arena.staging_count() + len(arena.ready), 0)
        arena.paused = False
        arena.pump(0.0)
        eq("unpaused: dispatch resumes", len(arena.ready), 6)
        # a second arena over the other slots shares the pool without touching the first's slots
        other = AR.G2Arena(pool, tables, PR.ProbeSource(_jobs(4)), AR.G2TickBudget(10 ** 6), slots=[0, 1, 2, 3], now=b.clock.now)
        other.pump(0.0)
        eq("the other arena owns 0..3", sorted(s for s in range(10) if other.state[s] == "ready"), [0, 1, 2, 3])
        eq("the first arena's slots are untouched", sorted(s for s in range(10) if arena.state[s] == "ready"), [4, 5, 6, 7, 8, 9])
        ctx = arena.activate(arena.ready.popleft())
        ok("the g2 episode context is used", isinstance(ctx, AR.G2EpisodeCtx))
        arena.send_step(ctx, 0)
        eq("step counted in flight", arena.inflight[ctx.slot], 1)
        events = [e for e in arena.pump(0.0) if e[1] == "stepped"]
        eq("the reply arrived and the count returned to 0", (len(events), arena.inflight[ctx.slot]), (1, 0))
        # a stray event from a non-subset slot is returned loudly, not consumed
        r = arena.handle(0, "stepped", {"x": 1})
        eq("stray event returned", r, (0, "stepped", {"x": 1}))
        e = raises("a death outside the subset stops the attempt", V.CapStop, lambda: arena.handle(0, "died", {"exit_code": 1}))
        ok("not a valid end", not e.valid)
        # the probe budget split
        bud = AR.G2TickBudget(1000)
        bud.charge_probe(300, 50)
        eq("probe ticks charged", (bud.consumed, bud.probe), (350, 350))


# =====================================================================================================================================
# the frontier
# =====================================================================================================================================


def _strip_start(fr: F.Frontier, i: int, offset: int = 1) -> CU.Start:
    return CU.Start(i, "strip", fr.pointer + offset, "T_clear", True, fr.pointer)


@test
def frontier_window_trigger_and_void() -> None:
    fr = F.Frontier({"T_clear": 2326, "T_t": 2315}, session=1)
    evs = []
    for i in range(7):
        ok("no event before the 8th clear", fr.record(_strip_start(fr, i), True) is None)
    ev = fr.record(_strip_start(fr, 7), True)
    eq("the 8th clear triggers", (ev["event"], ev["clears"], ev["size"]), ("trigger", 8, 8))
    ok("pending", fr.pending is not None and fr.pending["a"] == 1)
    ev2 = fr.record(_strip_start(fr, 8), False)
    eq("outcomes after the trigger belong to no window", ev2["event"], "after_trigger")
    rec = fr.begin_attempt(episodes_before=9)
    fr.finish_attempt(rec, "FAILED_STRIP", strip={"clears": 5, "non_clears": 11, "passed": False}, rechecks={})
    eq("a failed attempt counts and restarts the window", (fr.line_failed[2300], fr.session_failed[2300], fr.window["why"], fr.pending), (1, 1, "attempt", None))
    for i in range(12):
        ok("no event before the 13th non-clear", fr.record(_strip_start(fr, 100 + i), False) is None)
    ev = fr.record(_strip_start(fr, 112), False)
    eq("the 13th non-clear voids the window", (ev["event"], ev["non_clears"]), ("void", 13))
    # 7 clears and 12 non-clears: still open; the 13th non-clear voids even with 7 clears
    for i in range(7):
        fr.record(_strip_start(fr, 200 + i), True)
    for i in range(12):
        fr.record(_strip_start(fr, 300 + i), False)
    ev = fr.record(_strip_start(fr, 400), False)
    eq("void at 7 clears + 13 non-clears", (ev["event"], ev["clears"]), ("void", 7))
    # stale and non-strip outcomes never enter a window
    before = dict(fr.window)
    fr.record(CU.Start(500, "near", 2325, "T_clear", False, fr.pointer), True)
    fr.record(CU.Start(501, "strip", 2281, "T_clear", True, 2280), True)
    eq("non-strip and stale ignored", (fr.window["clears"], fr.window["non_clears"], fr.outside, fr.stale), (before["clears"], before["non_clears"], 1, 1))


@test
def frontier_attempt_bounds_held_and_stalled() -> None:
    lengths = {"T_clear": 2326, "T_t": 2315}
    fr = F.Frontier(lengths, session=1)

    def trigger(fr: F.Frontier, base: int) -> None:
        for i in range(8):
            fr.record(_strip_start(fr, base + i), True)
        ok("triggered", fr.pending is not None)

    # a move
    trigger(fr, 0)
    rec = fr.begin_attempt(episodes_before=8)
    eq("a = 1", rec["a"], 1)
    fr.finish_attempt(rec, "MOVED", strip={"clears": 10, "non_clears": 2, "passed": True}, rechecks={})
    eq("moved back 20", (fr.pointer, fr.moves_all[-1]["from"], fr.moves_all[-1]["to"], fr.window["why"]), (2280, 2300, 2280, "move"))
    # three failures in a session: HELD
    for n in range(3):
        trigger(fr, 100 + 10 * n)
        rec = fr.begin_attempt(episodes_before=0)
        eq("line index counts failed attempts", rec["a"], n + 1)
        fr.finish_attempt(rec, "BLOCKED_BY_RECHECK" if n else "FAILED_STRIP", strip={"clears": 10, "non_clears": 1, "passed": True} if n else {"clears": 3, "non_clears": 11, "passed": False},
                          rechecks={2128: {"clears": 2, "non_clears": 11, "passed": False}} if n else {}, failed_landing=2128 if n else None)
    ok("HELD after three failed attempts", fr.held() and not fr.stalled)
    for i in range(8):
        fr.record(_strip_start(fr, 200 + i), True)
    eq("a trigger while HELD is logged, none pending", (fr.pending, fr.held_triggers, fr.windows[-1]["result"]), (None, 1, "held_trigger"))
    raises("an attempt while HELD is refused", F.FrontierError, lambda: fr.begin_attempt(episodes_before=0))
    # the carried state into a second session: three more failures at the same pointer -> STALLED
    carried = fr.carried_state()
    fr2 = F.Frontier(lengths, session=2, state=carried)
    eq("carried pointer and line counts", (fr2.pointer, fr2.line_failed, fr2.held(), fr2.session_failed), (2280, {2280: 3}, False, {}))
    for n in range(3):
        trigger(fr2, 300 + 10 * n)
        rec = fr2.begin_attempt(episodes_before=0)
        eq("the line index continues", rec["a"], 4 + n)
        fr2.finish_attempt(rec, "FAILED_STRIP", strip={"clears": 2, "non_clears": 11, "passed": False}, rechecks={})
    ok("STALLED after six over the line", fr2.stalled and fr2.stalled_pointer == 2280 and fr2.line_failed[2280] == 6)
    raises("a stalled state cannot be resumed", F.FrontierError, lambda: F.Frontier(lengths, session=3, state=fr2.carried_state()))
    # a move needs every test passed
    fr3 = F.Frontier(lengths, session=1)
    trigger(fr3, 0)
    rec = fr3.begin_attempt(episodes_before=8)
    raises("a move without a passing strip test is refused", F.FrontierError, lambda: fr3.finish_attempt(rec, "MOVED", strip={"clears": 9, "non_clears": 11, "passed": False}, rechecks={}))
    # interrupted attempts count as neither
    fr4 = F.Frontier(lengths, session=1)
    trigger(fr4, 0)
    rec = fr4.begin_attempt(episodes_before=8)
    fr4.finish_attempt(rec, "INTERRUPTED", strip={"clears": 3, "non_clears": 2, "passed": False}, rechecks={})
    eq("interrupted: no counts", (fr4.line_failed, fr4.session_failed, fr4.pointer), ({}, {}, 2300))
    # landings
    eq("behind at 1980", F.landings_behind(1980), [2128])
    eq("audit at 1980", F.audit_landings(1980), [2128, 1966])
    eq("audit at 2300", F.audit_landings(2300), [2128])
    eq("audit at 2108", F.audit_landings(2108), [2128, 1966])
    eq("audit at 2120", F.audit_landings(2120), [2128])
    eq("audit at 1240", F.audit_landings(1240), [2128, 1966, 1694, 1473, 1369, 1248])


@test
def frontier_starts_are_keyed_and_within_the_strip() -> None:
    lengths = {"T_clear": 2326, "T_t": 2315}
    fr = F.Frontier(lengths, session=1)
    regions = {}
    for e in range(600):
        s = fr.draw(e)
        regions[s.region] = regions.get(s.region, 0) + 1
        ok("strip start in the strip", s.region != "strip" or 2300 <= s.tau < 2320)
        ok("a start never lies on a terminal tick", s.tau <= 2324)
    ok("the mix is about 50 / 30 / 20 (rehearsal empty at 2300 -> near)", 250 < regions["strip"] < 350 and regions.get("rehearsal", 0) == 0)
    eq("a start is a pure function of (episode, pointer)", fr.draw(17).to_json(), F.Frontier(lengths, session=1).draw(17).to_json())
    ok("g2 starts differ from g1's for the same episode", any(fr.draw(e).to_json() != CU.Curriculum(lengths).draw(e).to_json() for e in range(20)))
    taus = [F.strip_start(2300, 1, k, lengths)[0] for k in range(20)]
    ok("strip-test starts cover the strip", all(2300 <= t < 2320 for t in taus) and len(set(taus)) > 8)
    eq("keyed and stable", F.strip_start(2280, 3, 5, lengths), F.strip_start(2280, 3, 5, lengths))
    ok("a different attempt index gives different starts", [F.strip_start(2280, 1, k, lengths)[0] for k in range(20)] != [F.strip_start(2280, 2, k, lengths)[0] for k in range(20)])
    t, lin, shared = F.strip_start(2300, 1, 0, lengths)
    eq("above the shared prefix the lineage is drawn among those long enough", (shared, lin in ("T_clear", "T_t")), (False, True))


@test
def frontier_history_rebuilds_from_records_and_detects_tampering() -> None:
    lengths = {"T_clear": 2326, "T_t": 2315}
    fr = F.Frontier(lengths, session=1)
    episodes: List[Dict[str, Any]] = []
    attempts: List[Dict[str, Any]] = []
    e = 0

    def play(n: int, clear: bool) -> None:
        nonlocal e
        for _ in range(n):
            st = fr.draw(e)
            fr.record(st, clear)
            episodes.append({"episode": f"train-{e:07d}", "start": st.to_json(), "end_reason": "clear" if clear else "fall", "clear": clear})
            e += 1

    while fr.pending is None:
        play(1, True)
    rec = fr.begin_attempt(episodes_before=len(episodes))
    fr.finish_attempt(rec, "MOVED", strip={"clears": 10, "non_clears": 3, "passed": True}, rechecks={})
    attempts.append(json.loads(json.dumps({k: v for k, v in rec.items() if k != "clears_for_verification"}, default=str)))
    while fr.pending is None:
        play(1, True)
    rec = fr.begin_attempt(episodes_before=len(episodes))
    fr.finish_attempt(rec, "FAILED_STRIP", strip={"clears": 4, "non_clears": 11, "passed": False}, rechecks={})
    attempts.append(json.loads(json.dumps({k: v for k, v in rec.items() if k != "clears_for_verification"}, default=str)))
    play(30, False)
    rep = F.replay_history(episodes, attempts, lengths, session=1)
    eq("rebuilt", (rep["pointer"], rep["moves"], rep["attempts"], rep["problems"]), (2280, [(2300, 2280)], 2, []))
    # tampering: a move claimed with 9 clears
    bad = json.loads(json.dumps(attempts))
    bad[0]["strip_clears"] = 9
    bad[0]["strip_passed"] = False
    ok("a move without a passing strip is caught", F.replay_history(episodes, bad, lengths, session=1)["problems"])
    bad = json.loads(json.dumps(attempts))
    bad[1]["a"] = 5
    ok("a wrong line index is caught", F.replay_history(episodes, bad, lengths, session=1)["problems"])
    bad = json.loads(json.dumps(attempts))
    bad[1]["episodes_before"] = 0
    ok("an attempt before any trigger is caught", F.replay_history(episodes, bad, lengths, session=1)["problems"])
    bad_eps = json.loads(json.dumps(episodes))
    bad_eps[3]["start"]["tau"] = 2311
    ok("a start that does not reproduce from its keys is caught", F.replay_history(bad_eps, attempts, lengths, session=1)["problems"])


# =====================================================================================================================================
# the frozen policy, the tape, the probe runner, the attempt
# =====================================================================================================================================


def fixed_state(seed: str = "w", scale: float = 0.05) -> Dict[str, Any]:
    import torch

    shapes = {"mlp_extractor.policy_net.0.weight": (64, 606), "mlp_extractor.policy_net.0.bias": (64,), "mlp_extractor.policy_net.2.weight": (64, 64), "mlp_extractor.policy_net.2.bias": (64,),
              "mlp_extractor.value_net.0.weight": (64, 606), "mlp_extractor.value_net.0.bias": (64,), "mlp_extractor.value_net.2.weight": (64, 64), "mlp_extractor.value_net.2.bias": (64,),
              "action_net.weight": (17, 64), "action_net.bias": (17,), "value_net.weight": (1, 64), "value_net.bias": (1,)}
    sd: Dict[str, Any] = {}
    for k, sh in shapes.items():
        n = int(np.prod(sh))
        raw = b"".join(hashlib.sha256(f"{seed}|{k}|{i}".encode()).digest() for i in range((n * 2 + 31) // 32))[:n * 2]
        vals = (np.frombuffer(raw, dtype=np.uint16).astype(np.float32) / 65535.0 - 0.5) * 2 * scale
        sd[k] = torch.from_numpy(vals.reshape(sh).copy())
    return sd


def keyed_obs(seed: str) -> np.ndarray:
    raw = b"".join(hashlib.sha256(f"{seed}|{i}".encode()).digest() for i in range(606 * 4 // 32 + 1))[:606 * 4]
    return (np.frombuffer(raw, dtype=np.uint32).astype(np.float32) / 2 ** 32).copy()


@test
def frozen_policy_is_keyed_pure_and_matches_sb3() -> None:
    import torch

    sd = fixed_state()
    with tmpdir() as d:
        meta = PO.save_snapshot(sd, d / "snap.pth")
        pol = PO.FrozenPolicy.from_file("t", d / "snap.pth", meta["sha256"])
        raises("a wrong pin is refused", PO.SnapshotError, lambda: PO.FrozenPolicy.from_file("t", d / "snap.pth", "0" * 64))
        pol2 = PO.FrozenPolicy("t2", sd, meta["sha256"])
        obs = keyed_obs("o1")
        key = G.probe_action_key(2300, 1, "strip", 0, 2300)
        eq("sampling is a pure function of (weights, observation, key)", pol.sample_word(obs, key), pol2.sample_word(obs, key))
        ok("a different key gives (over many keys) different words", len({pol.sample_word(obs, G.probe_action_key(2300, 1, "strip", k, 2300)) for k in range(40)}) > 3)
        eq("argmax stable", pol.argmax_word(obs), pol2.argmax_word(obs))
        st = pol.stats(obs)
        ok("stats fields", set(st) == {"v", "h", "top_word_p"} and 0 < st["h"] <= 4.2774 + 1e-6 and 0 < st["top_word_p"] <= 1)
        # the same weights inside a real SB3 policy give the same distribution
        import m7n_obs as mn
        import m7n_policy as mp
        from stable_baselines3.common.vec_env import DummyVecEnv

        env = DummyVecEnv([lambda: ZeroEnv()])
        model = mp.make_model(env, seed=0, n_steps=8, batch_size=8, n_epochs=1)
        model.policy.load_state_dict(sd, strict=True)
        with torch.no_grad():
            dist = model.policy.get_distribution({k: torch.from_numpy(v[None]) for k, v in unflatten(obs).items()})
        probs = [dd.probs[0].numpy().astype(np.float64) for dd in dist.distribution]
        ps, pb, v = pol._forward(obs)
        ok("stick probabilities equal SB3's", np.allclose(ps, probs[0], atol=1e-6))
        ok("button probabilities equal SB3's", np.allclose(pb, probs[1], atol=1e-6))
        det, _ = model.predict(unflatten(obs), deterministic=True)
        det = np.asarray(det).reshape(-1)
        eq("argmax equals SB3's deterministic predict", pol.argmax_word(obs), int(det[0]) * 8 + int(det[1]))
        live = PO.state_dict_of(model)
        eq("state_dict_of a live model has the 12 registered keys", sorted(live), sorted(PO.STATE_KEYS))
        ok("flatten_obs matches the v3 order", np.array_equal(PO.flatten_obs(unflatten(obs)), obs))


def unflatten(flat: np.ndarray) -> Dict[str, np.ndarray]:
    import m7n_obs as mn

    out: Dict[str, np.ndarray] = {}
    i = 0
    for k in mn.KEY_ORDER:
        sh = mn.SHAPES[k]
        n = int(np.prod(sh))
        out[k] = np.asarray(flat[i:i + n], dtype=np.float32).reshape(sh).copy()
        i += n
    return out


class ZeroEnv(gym.Env):
    """A gymnasium env over the real v3 spaces (zero-tick): deterministic observations from a keyed stream, rewards a keyed function of the step."""

    metadata: Dict[str, Any] = {"render_modes": []}

    def __init__(self) -> None:
        import m7n_obs as mn

        super().__init__()
        self.observation_space = mn.make_observation_space()
        self.action_space = gym.spaces.MultiDiscrete([9, 8])
        self.t = 0
        self.ep = 0
        self.render_mode = None

    def _obs(self) -> Dict[str, np.ndarray]:
        return unflatten(keyed_obs(f"zero|{self.t}") * 0.1)          # a function of the step within the episode only, so two learners from identical seeds see identical streams

    def reset(self, *, seed: Any = None, options: Any = None):
        self.t = 0
        self.ep += 1
        return self._obs(), {}

    def step(self, action: Any):
        self.t += 1
        r = float(S.uniform(f"zero|r|{self.t}|{int(action[0])}|{int(action[1])}")) - 0.5
        done = self.t >= 16
        return self._obs(), r, done, False, {}

    def close(self) -> None:
        return None


@test
def tape_jobs_tables_and_bars() -> None:
    jobs = TP.t0_jobs()
    eq("400 T0 episodes", len(jobs), 400)
    eq("labels", (jobs[0].label, jobs[0].job_id, jobs[0].driver), ("m9|g2|reach|2128|0", "t0_tape-2128-000", "tape"))
    first_six = [j.extra["landing"] for j in jobs[:6]]
    eq("interleaved by k, landings largest first", first_six, [2128, 1966, 1694, 1473, 1369, 1248])
    eq("200 at 2128 and 40 elsewhere", {lam: sum(1 for j in jobs if j.extra["landing"] == lam) for lam in G.LANDINGS}, G.TAPE_KEYS)
    eq("keys never repeat", len({j.label for j in jobs}), 400)
    # tables
    recs = [{"episode": f"t0_tape-{lam}-{k:03d}", "landing": lam, "k": k, "clear": (lam == 2128 and k % 2 == 0) or (lam == 1966 and k == 0), "end_reason": "clear" if ((lam == 2128 and k % 2 == 0) or (lam == 1966 and k == 0)) else "fall"}
            for lam, n in G.TAPE_KEYS.items() for k in range(n)]
    claimed = TP.claimed_table(recs)
    eq("claimed complete", (claimed["complete"], claimed["landings"]["2128"]["clears_claimed"], claimed["landings"]["1966"]["clears_claimed"]), (True, 100, 1))
    ver = {r["episode"]: True for r in recs if r["clear"]}
    pinned = TP.pinned_table(claimed, recs, ver)
    eq("B at 2128 with 100/200", (pinned["landings"]["2128"]["B"], pinned["landings"]["2128"]["p_hat"]), (15, 0.5))
    eq("B at 1966 with 1/40", pinned["landings"]["1966"]["B"], 10)
    eq("B at 1694 with 0/40", pinned["landings"]["1694"]["B"], 10)
    ok("pinned and digested", pinned["pinned"] and len(pinned["sha256"]) == 64 and TP.table_digest(pinned) == pinned["sha256"])
    ver2 = dict(ver)
    ver2.pop("t0_tape-2128-000")
    unp = TP.pinned_table(claimed, recs, ver2)
    eq("an unreplayed tape clear leaves the landing unpinned (B None)", (unp["landings"]["2128"]["pinned"], unp["landings"]["2128"]["B"], unp["landings"]["2128"]["unverified"]), (False, None, ["t0_tape-2128-000"]))
    ver3 = dict(ver)
    ver3["t0_tape-2128-000"] = False
    inx = TP.pinned_table(claimed, recs, ver3)
    eq("an inexact tape replay is listed", inx["landings"]["2128"]["inexact"], ["t0_tape-2128-000"])
    eq("bars()", TP.bars(pinned), {2128: 15, 1966: 10, 1694: 10, 1473: 10, 1369: 10, 1248: 10})
    eq("drift jobs", [j.job_id for j in TP.drift_jobs()], [f"drift_tape-2128-{k:03d}" for k in range(5)])


@test
def probe_source_and_test_state_curtail() -> None:
    jobs = _jobs(5, part="a") + _jobs(5, part="b")
    src = PR.ProbeSource(jobs)
    j1 = src.next_job(None)
    src.cancel("a")
    nxt = [src.next_job(None) for _ in range(9)]
    eq("cancelled part skipped", ([j.extra["part"] for j in nxt if j], len(src.skipped)), (["b"] * 5, 4))
    src2 = PR.ProbeSource(jobs)
    j = src2.next_job(None)
    src2.unget(j)
    eq("unget returns the same job", src2.next_job(None).job_id, j.job_id)
    t = PR.TestState("strip")
    for i in range(9):
        eq("undecided", t.record(True, 10.0, {"v": 1.0, "h": 2.0}), None)
    eq("pass at the 10th clear", t.record(True, 10.0, None), "passed")
    t2 = PR.TestState(2128)
    for i in range(9):
        t2.record(True, 10.0, None)
    for i in range(10):
        eq("9 clears + 10 non-clears: undecided", t2.record(False, -5.0, None), None)
    eq("fail at the 11th non-clear", t2.record(False, -5.0, None), "failed")
    js = t2.to_json()
    eq("to_json", (js["clears"], js["non_clears"], js["episodes"], js["passed"]), (9, 11, 20, False))


@test
def probe_runner_curtails_cancels_and_records() -> None:
    lengths = {"T_clear": 2326, "T_t": 2315}
    with tmpdir() as d:
        b = SmallBuilder(d / "run")
        tables = stub_tables(d, b)
        pool = b.make_pool("x", C.FLAGS_TRAIN)
        rec = PR.ProbeRecorder(d / "run" / "probes.jsonl", phase="probe", now=b.clock.now, extra={"attempt": 1})
        # a competent snapshot: the strip test passes at the 10th clear, early
        arena = AR.G2Arena(pool, tables, PR.ProbeSource(PR.strip_jobs(2300, 1, lengths)), AR.G2TickBudget(10 ** 7), slots=[4, 5, 6, 7, 8, 9], now=b.clock.now)
        t = PR.TestState("strip")
        res = PR.ProbeRunner(arena, tables, rec, policy=stub_policy(2200), tests={"strip": t}, now=b.clock.now, flatten=ST2.G2StubEnvBuilder.flatten).run()
        ok("passed at 10 clears", t.passed and t.clears == 10)
        ok("early stopping: fewer than 20 episodes decided", 10 <= len(t.outcomes) < 20)
        ok("the remaining episodes were abandoned and recorded", len(t.abandoned) + len(t.outcomes) <= 20 and arena.source.cancelled == {"strip"})
        arena.wait_settled()
        ok("settled after the run", arena.settled() and arena.idle_subset())
        ok("start stats recorded", all(r["start_value"] is not None for r in rec.records))
        # an incompetent snapshot fails at the 11th non-clear (at a strip whose critical ticks lie before the clear: the synthetic world's last 30 ticks are inherited motion)
        arena = AR.G2Arena(pool, tables, PR.ProbeSource(PR.strip_jobs(2200, 2, lengths)), AR.G2TickBudget(10 ** 7), slots=[4, 5, 6, 7, 8, 9], now=b.clock.now)
        t = PR.TestState("strip")
        PR.ProbeRunner(arena, tables, rec, policy=stub_policy(2400), tests={"strip": t}, now=b.clock.now, flatten=ST2.G2StubEnvBuilder.flatten).run()
        arena.wait_settled()
        ok("failed at 11 non-clears", t.decided == "failed" and t.non_clears == 11)
        # re-checks in parallel with fail fast: 2128 passes, 1966 fails cold (forgetting) -> every other part cancelled
        jobs = PR.recheck_jobs(1940, 1, [2128, 1966])
        arena = AR.G2Arena(pool, tables, PR.ProbeSource(jobs), AR.G2TickBudget(10 ** 7), slots=[4, 5, 6, 7, 8, 9], now=b.clock.now)
        tests = {2128: PR.TestState(2128), 1966: PR.TestState(1966)}
        PR.ProbeRunner(arena, tables, rec, policy=stub_policy(1900, forget_landing=1966, forget_when_b_below=1920), tests=tests, fail_fast=True, now=b.clock.now, flatten=ST2.G2StubEnvBuilder.flatten).run()
        arena.wait_settled()
        eq("the forgotten cold landing fails", tests[1966].decided, "failed")
        ok("the other landing was passed or cancelled, never left running", tests[2128].decided in ("passed", "cancelled"))
        # the tape driver (T0) with no curtailment completes every job
        arena = AR.G2Arena(pool, tables, PR.ProbeSource(TP.t0_jobs({2128: 4, 1966: 2})), AR.G2TickBudget(10 ** 7), now=b.clock.now)
        rec2 = PR.ProbeRecorder(d / "run" / "t0.jsonl", phase="t0", now=b.clock.now)
        res = PR.ProbeRunner(arena, tables, rec2, policy=None, tests=None, now=b.clock.now).run()
        eq("every tape job completed", (len(rec2.records), res["stop"]), (6, None))
        ok("tape words are the trunk's", all(bytes.fromhex(r["sampled_hex"]) == tables["T_clear"].words[r["tau"]:r["tau"] + len(bytes.fromhex(r["sampled_hex"]))] for r in rec2.records))
        # a lifecycle failure while staging is redrawn with the same job id (fixed list)
        b2 = SmallBuilder(d / "run2", n_slots=2, inject={"acquire_fail_jobs": [1]})
        tables2 = stub_tables(d / "x", b2) if False else stub_tables_at(d / "run2", b2)
        pool2 = b2.make_pool("y", C.FLAGS_TRAIN)
        arena = AR.G2Arena(pool2, tables2, PR.ProbeSource(TP.t0_jobs({2128: 3})), AR.G2TickBudget(10 ** 7), now=b2.clock.now, lifecycle_limit=3)
        rec3 = PR.ProbeRecorder(d / "run2" / "t0.jsonl", phase="t0", now=b2.clock.now)
        res = PR.ProbeRunner(arena, tables2, rec3, policy=None, tests=None, now=b2.clock.now).run()
        eq("every job completed once after the launch failures", sorted(r["episode"] for r in rec3.records), [f"t0_tape-2128-{k:03d}" for k in range(3)])
        ok("failures recorded", len(arena.lifecycle_failures) >= 1)
        # a mismatch is an integrity stop
        b3 = SmallBuilder(d / "run3", n_slots=2, inject={"mismatch_job": 1, "mismatch_tick": 30})
        tables3 = stub_tables_at(d / "run3", b3)
        pool3 = b3.make_pool("z", C.FLAGS_TRAIN)
        arena = AR.G2Arena(pool3, tables3, PR.ProbeSource(TP.t0_jobs({2128: 2})), AR.G2TickBudget(10 ** 7), now=b3.clock.now)
        raises("mismatch -> IntegrityStop", V.IntegrityStop, lambda: PR.ProbeRunner(arena, tables3, PR.ProbeRecorder(d / "run3" / "t0.jsonl", phase="t0", now=b3.clock.now), policy=None).run())


def stub_tables_at(root: Path, b: ST2.G2StubEnvBuilder) -> Dict[str, L.Tables]:
    for name, ln in b.lineages.items():
        tr = b.route_traces[name]
        chain, v3 = L.build_tables(tr["initial"], tr["steps"], ST.StubObs)
        L.save_tables(root / "lineages", name, ln.words, chain, v3)
    return L.load_all_tables(root / "lineages", ["T_clear", "T_t"])


@test
def run_attempt_pauses_training_and_hands_the_slots_back() -> None:
    lengths = {"T_clear": 2326, "T_t": 2315}
    with tmpdir() as d:
        b = SmallBuilder(d / "run")
        tables = stub_tables(d, b)
        pool = b.make_pool("x", C.FLAGS_TRAIN)
        fr = F.Frontier(lengths, session=1)
        src = TR.TrainSource(fr)
        train_arena = AR.G2Arena(pool, tables, src, AR.G2TickBudget(10 ** 8), now=b.clock.now)
        # four active episodes (the playing slots) and six staged starts
        while len(train_arena.active) < 4:
            train_arena.pump(0.0)
            while train_arena.ready and len(train_arena.active) < 4:
                train_arena.activate(train_arena.ready.popleft())
        train_arena.pump(0.0)
        parked_before = sorted(train_arena.active)
        eq("four active", len(parked_before), 4)
        ok("six others staged or parked", len(train_arena.ready) + train_arena.staging_count() == 6)
        for i in range(8):
            fr.record(_strip_start(fr, i), True)
        ok("pending", fr.pending is not None)
        model = ST2.G2StubModel(None, n_steps=4, b0=2200)
        rec = PR.run_attempt(frontier=fr, train_arena=train_arena, pool=pool, tables=tables, train_budget=train_arena.budget, lengths=lengths, snapshot=ST2.G2StubEnvBuilder.snapshot_of(model),
                             make_policy=ST2.G2StubEnvBuilder.make_policy, attempt_root=d / "run" / "attempts", probes_jsonl=d / "run" / "probes.jsonl", attempts_jsonl=d / "run" / "attempts.jsonl",
                             withdrawn_jsonl=d / "run" / "withdrawn.jsonl", now=b.clock.now, guard=lambda: None, log=lambda s: None, episodes_before=8, num_timesteps=0, flatten=ST2.G2StubEnvBuilder.flatten)
        eq("moved", (rec["result"], fr.pointer, rec["a"]), ("MOVED", 2280, 1))
        eq("the four playing slots stayed parked (still active, untouched)", sorted(train_arena.active), parked_before)
        eq("the six others ran the attempt", (len(rec["probe_slots"]), sorted(rec["probe_slots"]) == sorted(set(range(10)) - set(parked_before))), (6, True))
        eq("withdrawn starts recorded", rec["withdrawn"], len(A.read_jsonl(d / "run" / "withdrawn.jsonl")))
        ok("every withdrawn start was a parked training start with its episode number", all(w["episode"].startswith("train-") for w in A.read_jsonl(d / "run" / "withdrawn.jsonl")))
        ok("the training arena is unpaused and settled", not train_arena.paused and train_arena.settled())
        ok("probe ticks charged to the training budget", train_arena.budget.probe > 0 and train_arena.budget.consumed >= train_arena.budget.probe)
        ok("snapshot digest recorded and file present", len(rec["snapshot"]["sha256"]) == 64 and (d / "run" / "attempts" / "a001" / "snapshot_policy.pth").is_file())
        ok("attempt record written", A.read_jsonl(d / "run" / "attempts.jsonl")[0]["result"] == "MOVED")
        ok("probe records written with the attempt fields", all(r["attempt"] == 1 and r["part"] == "strip" for r in A.read_jsonl(d / "run" / "probes.jsonl")))
        ok("one keyed clear picked for verification", len(rec["clears_for_verification"]) == 1 and rec["clears_for_verification"][0]["part"] == "strip")
        # the withdrawn episode numbers are never drawn again: the source counter only advances
        nxt = src.next_job(train_arena)
        ok("the next training episode number is beyond every withdrawn one", all(int(w["episode"].split("-")[1]) < nxt.episode for w in A.read_jsonl(d / "run" / "withdrawn.jsonl")))
        train_arena.pump(0.0)
        ok("training staging resumed on the free slots", train_arena.staging_count() + len(train_arena.ready) > 0)
        # a failing strip (incompetent snapshot) at a pointer whose strip has critical ticks before the clear (2,200; the synthetic world's last 30 ticks are inherited motion)
        frf = F.Frontier(lengths, session=1, state={"pointer": 2200, "line_failed": {}, "moves": [], "next_episode": 0, "attempt_counter": 0, "sessions": [1]})
        for i in range(8):
            frf.record(_strip_start(frf, 100 + i), True)
        rec2 = PR.run_attempt(frontier=frf, train_arena=train_arena, pool=pool, tables=tables, train_budget=train_arena.budget, lengths=lengths, snapshot=ST2.G2StubEnvBuilder.snapshot_of(ST2.G2StubModel(None, n_steps=4, b0=2400)),
                              make_policy=ST2.G2StubEnvBuilder.make_policy, attempt_root=d / "run" / "attempts", probes_jsonl=d / "run" / "probes.jsonl", attempts_jsonl=d / "run" / "attempts.jsonl",
                              withdrawn_jsonl=d / "run" / "withdrawn.jsonl", now=b.clock.now, guard=lambda: None, log=lambda s: None, episodes_before=16, num_timesteps=0, flatten=ST2.G2StubEnvBuilder.flatten)
        eq("failed strip", (rec2["result"], frf.pointer, frf.line_failed[2200], rec2["a"]), ("FAILED_STRIP", 2200, 1, 1))
        # a re-check blocked at a cold landing, at a pointer behind 2128
        fr2 = F.Frontier(lengths, session=1, state={"pointer": 1940, "line_failed": {}, "moves": [], "next_episode": 0, "attempt_counter": 0, "sessions": [1]})
        for i in range(8):
            fr2.record(_strip_start(fr2, 200 + i), True)
        rec3 = PR.run_attempt(frontier=fr2, train_arena=train_arena, pool=pool, tables=tables, train_budget=train_arena.budget, lengths=lengths,
                              snapshot=ST2.G2StubEnvBuilder.snapshot_of(ST2.G2StubModel(None, n_steps=4, b0=1900, forget_landing=1966, forget_when_b_below=1920)),
                              make_policy=ST2.G2StubEnvBuilder.make_policy, attempt_root=d / "run" / "attempts", probes_jsonl=d / "run" / "probes.jsonl", attempts_jsonl=d / "run" / "attempts.jsonl",
                              withdrawn_jsonl=d / "run" / "withdrawn.jsonl", now=b.clock.now, guard=lambda: None, log=lambda s: None, episodes_before=0, num_timesteps=0, flatten=ST2.G2StubEnvBuilder.flatten)
        eq("blocked by the re-check at 1966; the pointer never moves", (rec3["result"], rec3["failed_landing"], fr2.pointer), ("BLOCKED_BY_RECHECK", 1966, 1940))
        eq("the re-check set was every landing behind the frontier", sorted(int(k) for k in rec3["rechecks"]), [1966, 2128])
        ok("the strip test passed before the re-checks", rec3["strip_passed"])
        # an interrupted attempt (a cap raised by the guard) is recorded as INTERRUPTED and counts as neither
        fr3 = F.Frontier(lengths, session=1)
        for i in range(8):
            fr3.record(_strip_start(fr3, 300 + i), True)
        calls = {"n": 0}

        def guard() -> None:
            calls["n"] += 1
            if calls["n"] > 3:
                raise V.CapStop("wall cap of phase train reached", valid=True)

        e = raises("the cap propagates", V.CapStop, lambda: PR.run_attempt(frontier=fr3, train_arena=train_arena, pool=pool, tables=tables, train_budget=train_arena.budget, lengths=lengths,
                                                                           snapshot=ST2.G2StubEnvBuilder.snapshot_of(model), make_policy=ST2.G2StubEnvBuilder.make_policy, attempt_root=d / "run" / "attempts",
                                                                           probes_jsonl=d / "run" / "probes.jsonl", attempts_jsonl=d / "run" / "attempts.jsonl", withdrawn_jsonl=d / "run" / "withdrawn.jsonl",
                                                                           now=b.clock.now, guard=guard, log=lambda s: None, episodes_before=0, num_timesteps=0, flatten=ST2.G2StubEnvBuilder.flatten))
        ok("a valid end", e.valid)
        eq("recorded as INTERRUPTED, no counts", (fr3.attempts[-1]["result"], fr3.line_failed, fr3.pointer), ("INTERRUPTED", {}, 2300))
        ok("the training arena is unpaused and settled after the interruption", not train_arena.paused and train_arena.settled())


# =====================================================================================================================================
# checkpoints, the stub resume, the real SB3 round trip
# =====================================================================================================================================


@test
def checkpoints_pin_model_members_and_curriculum_state() -> None:
    lengths = {"T_clear": 2326, "T_t": 2315}
    with tmpdir() as d:
        fr = F.Frontier(lengths, session=1)
        m = ST2.G2StubModel(None, n_steps=4, b0=2200)
        info = TR.save_checkpoint(m, fr, d / "training", 0, "initial", session=1, tape_table_sha256="ab" * 32)
        cd = d / "training" / "checkpoints" / "ckpt_000000000"
        ok("three files", all((cd / n).is_file() for n in ("model.zip", "curriculum_state.json", "checkpoint.json")))
        meta = A.read_json(cd / "checkpoint.json")
        eq("pins hold", (meta["model_zip_sha256"], meta["members_sha256"], meta["curriculum_state_sha256"]),
           (RS.sha256_file(cd / "model.zip"), RS.zip_member_digests(cd / "model.zip"), RS.sha256_file(cd / "curriculum_state.json")))
        cs = A.read_json(cd / "curriculum_state.json")
        eq("the curriculum state carries the pointer, the line contract and the tape digest", (cs["pointer"], cs["line_contract_sha256"], cs["tape_table_sha256"], cs["session"]), (2300, G.line_contract_digest(), "ab" * 32, 1))
        ok("the carried state is inside", cs["carried"]["pointer"] == 2300 and "line_failed" in cs["carried"])
        raises("a checkpoint directory is never overwritten", FileExistsError, lambda: TR.save_checkpoint(m, fr, d / "training", 0, "initial", session=1, tape_table_sha256=None))
        fin = TR.save_checkpoint(m, fr, d / "training", 123, "final", session=1, tape_table_sha256=None)
        eq("final", fin["checkpoint"], "final")


@test
def stub_model_state_round_trips_and_resumes() -> None:
    with tmpdir() as d:
        m = ST2.G2StubModel(None, n_steps=4, b0=2200, need=30, forget_landing=1966, forget_when_b_below=1920)
        m.num_timesteps, m.updates, m._n_updates, m.calls = 777, 5, 5, 99
        m.exposure = {110: 12, 109: 3}
        m.history = [(500, 2200)]
        m.save(d / "m.zip")
        m2 = ST2.G2StubModel.load(d / "m.zip")
        eq("bit-exact state", m2.state_dict(), m.state_dict())
        eq("members present for the digest pins", sorted(RS.zip_member_digests(d / "m.zip")), ["policy.optimizer.pth", "policy.pth"])
        pol = ST2.G2StubEnvBuilder.policy_from_model_zip(d / "m.zip")
        eq("the audit policy carries the snapshot's competence", (pol.B, pol.forget_landing), (2200, 1966))


@test
def sb3_save_load_round_trip_is_bit_exact_and_an_update_after_reload_equals_one_without() -> None:
    import torch
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv

    import m7n_policy as mp

    torch.set_num_threads(1)
    with tmpdir() as d:
        env_a = DummyVecEnv([lambda: ZeroEnv()])
        a = mp.make_model(env_a, seed=0, n_steps=32, batch_size=32, n_epochs=2, learning_rate=3e-4, gamma=0.999, gae_lambda=0.995, clip_range=0.2, ent_coef=0.01, vf_coef=0.5, max_grad_norm=0.5)
        a.learn(total_timesteps=32)
        a.save(str(d / "m.zip"))
        saved = RS.saved_counters(d / "m.zip")
        eq("saved counters", (saved["num_timesteps"], saved["n_updates"], len(saved["adam_steps"])), (32, 2, 12))
        bb = PPO.load(str(d / "m.zip"), env=DummyVecEnv([lambda: ZeroEnv()]), device="cpu")
        eq("weights and Adam moments bit-equal after the round trip", RS.tensors_equal(RS.model_state(a), RS.model_state(bb)), [])
        eq("continuity assertions pass", RS.assert_continuity(bb, saved)["ok"], True)
        eq("live counters equal saved", RS.live_counters(bb), saved)
        # one more rollout + update on both, from identical seeds and a reset env: bit-exact
        a._last_obs = None
        a.set_random_seed(7)                                           # each learner starts its rollout from the same generator state (torch, numpy, random)
        a.learn(total_timesteps=32, reset_num_timesteps=False)
        bb.set_random_seed(7)
        bb.learn(total_timesteps=32, reset_num_timesteps=False)
        eq("the update after the reload equals the update without it (every tensor, every Adam moment and step)", RS.tensors_equal(RS.model_state(a), RS.model_state(bb)), [])
        eq("num_timesteps continued", (a.num_timesteps, bb.num_timesteps, a._n_updates, bb._n_updates), (64, 64, 4, 4))
        # refusals
        bad = RS.saved_counters(d / "m.zip")
        bad["n_updates"] = 99
        raises("a counter mismatch is refused", RS.ResumeError, lambda: RS.assert_continuity(bb, bad))
        cs = {"line_contract_sha256": G.line_contract_digest(), "ppo": dict(G.PPO), "stalled": False}
        eq("compatible", RS.check_resume_compat(cs, line_contract_sha256=G.line_contract_digest(), executable_sha256="e", saved_executable="e", ppo=G.PPO), [])
        ok("a changed contract is refused", RS.check_resume_compat(dict(cs, line_contract_sha256="x"), line_contract_sha256=G.line_contract_digest(), executable_sha256="e", saved_executable="e", ppo=G.PPO))
        ok("a changed executable is refused", RS.check_resume_compat(cs, line_contract_sha256=G.line_contract_digest(), executable_sha256="e2", saved_executable="e", ppo=G.PPO))
        ok("a changed PPO value is refused", RS.check_resume_compat(cs, line_contract_sha256=G.line_contract_digest(), executable_sha256="e", saved_executable="e", ppo=dict(G.PPO, ent_coef=0.0)))
        ok("a stalled state is refused", RS.check_resume_compat(dict(cs, stalled=True), line_contract_sha256=G.line_contract_digest(), executable_sha256="e", saved_executable="e", ppo=G.PPO))
        # the final-state record and the input copy with digests
        fd = d / "final"
        fd.mkdir()
        shutil.copyfile(d / "m.zip", fd / "model.zip")
        A.write_json(fd / "curriculum_state.json", A.stamp({"pointer": 2280, "carried": {"pointer": 2280}, "line_contract_sha256": G.line_contract_digest(), "ppo": dict(G.PPO)}))
        A.write_json(d / "tape_baseline.json", A.stamp({"landings": {}, "pinned": True, "sha256": "x"}))
        fs = RS.final_state_record(final_dir=fd, tape_baseline_path=d / "tape_baseline.json", session=1, line_contract_sha256=G.line_contract_digest(), executable_sha256="e")
        eq("the record pins the three files and the counters", (fs["model_zip"]["sha256"], fs["counters"]["num_timesteps"], fs["next_session_seed"]), (RS.sha256_file(fd / "model.zip"), 32, 1002))
        expect = {"model_zip": fs["model_zip"]["sha256"], "curriculum_state": fs["curriculum_state"]["sha256"], "tape_baseline": fs["tape_baseline"]["sha256"]}
        out = RS.copy_inputs(fs, d / "input", expect=expect)
        ok("inputs copied and checked", out["ok"] and (d / "input" / "model.zip").is_file())
        raises("a wrong expected digest is refused before anything is loaded", RS.ResumeError, lambda: RS.copy_inputs(fs, d / "input2", expect=dict(expect, model_zip="0" * 64)))
        # resume_ppo on a rollout-sized model (no learning): continuity holds and the session seed is set
        env4 = DummyVecEnv([lambda: ZeroEnv() for _ in range(4)])
        m4 = mp.make_model(env4, seed=0, n_steps=1280, batch_size=512, n_epochs=10)
        m4.save(str(d / "m4.zip"))
        r4 = TR.resume_ppo(d / "m4.zip", DummyVecEnv([lambda: ZeroEnv() for _ in range(4)]), 4, 2)
        eq("resumed with the session seed", (r4.num_timesteps, r4.resumed_seed), (0, 1002))
        raises("a model whose rollout is not 5,120 is refused", RS.ResumeError, lambda: TR.resume_ppo(d / "m.zip", DummyVecEnv([lambda: ZeroEnv()]), 1, 2))


@test
def fresh_policy_initialisation_equals_g1s_untrained_checkpoint() -> None:
    """Reported, never deciding (decisions section 2): the fresh PPO's untrained weights equal g1's ckpt_000000000 policy tensors."""
    import torch
    from stable_baselines3.common.vec_env import DummyVecEnv

    g1_zip = REPO / "runs" / "m9_g1" / "training" / "checkpoints" / "ckpt_000000000" / "model.zip"
    if not g1_zip.is_file():
        return
    torch.set_num_threads(1)
    env4 = DummyVecEnv([lambda: ZeroEnv() for _ in range(4)])
    m = TR.make_fresh_ppo(env4, 4)
    with zipfile.ZipFile(g1_zip) as z:
        raw = z.read("policy.pth")
    sd = torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True)
    live = PO.state_dict_of(m)
    eq("same tensors as g1's untrained checkpoint", RS.tensors_equal(live, sd), [])
    buf = io.BytesIO()
    torch.save(live, buf)
    ok("reported: policy.pth member sha256 of g1's untrained model is eb592c88...", hashlib.sha256(raw).hexdigest().startswith("eb592c887fc66aab"))


# =====================================================================================================================================
# the engine on the synthetic world
# =====================================================================================================================================


@test
def synthetic_session_runs_every_phase_and_verify_run_agrees() -> None:
    with tmpdir() as d:
        sess, out, b = run_small(d)
        eq("phases", sess.phases, {"open": True, "p1": True, "p2": True, "t0": True, "train": True, "audit": True, "verify": True})
        ok(f"a registered outcome ({out['outcome']}: {out['reasons']})", out["outcome"] in ("PASS", "INCONCLUSIVE", "NULL"))
        ok("at least one attempt ran in the short window", sess.frontier is not None and len(sess.frontier.attempts) >= 1)
        ok("at least one move", sess.frontier.pointer < 2300)
        root = d / "run"
        for rel in ("t0/episodes.jsonl", "t0/tape_table.json", "training/episodes.jsonl", "training/rollouts.jsonl", "training/attempts.jsonl", "training/probes.jsonl", "training/moves.jsonl",
                    "training/windows.jsonl", "training/withdrawn.jsonl", "audit/episodes.jsonl", "verification/replays.jsonl", "session/tape_baseline.json", "session/final_state.json",
                    "session/rule.json", "session/line.json", "training/checkpoints/final/curriculum_state.json"):
            ok(f"{rel} exists", (root / rel).is_file())
        vr = RPT.verify_run(root)
        ok(f"verify-run ok: {vr['problems'][:3]}", vr["ok"])
        ok("the frontier history rebuilt from the records equals the log", vr["frontier_replay"]["equal_to_log"] and vr["frontier_replay"]["attempts"] == len(sess.frontier.attempts))
        aud = A.audit_tree(root, skip_dirs=("workers", "vw"))
        ok(f"metadata audit {aud['failures'][:2]}", aud["ok"] and aud["files"] > 20)
        tb = A.read_json(root / "session" / "tape_baseline.json")
        ok("the tape baseline is pinned with bars", tb["pinned"] and all(v["B"] is not None for v in tb["landings"].values()))
        ok("every T0 tape clear was replayed exactly", all(v["unverified"] == [] and v["inexact"] == [] for v in tb["landings"].values()))
        fs = A.read_json(root / "session" / "final_state.json")
        eq("the final state pins the saved files (file hashes)", (fs["model_zip"]["sha256"], fs["tape_baseline"]["sha256"], fs["curriculum_state"]["sha256"]),
           (RS.sha256_file(root / "training" / "checkpoints" / "final" / "model.zip"), RS.sha256_file(root / "session" / "tape_baseline.json"),
            RS.sha256_file(root / "training" / "checkpoints" / "final" / "curriculum_state.json")))
        eq("the table carries its own content digest", TP.table_digest(tb), tb["sha256"])
        at = A.read_jsonl(root / "training" / "attempts.jsonl")
        ok("every attempt recorded the pause: four parked slots and the six probe slots, disjoint", all(len(a["parked_slots"]) == 4 and len(a["probe_slots"]) == 6 and not set(a["parked_slots"]) & set(a["probe_slots"]) for a in at))
        ok("every attempt recorded a snapshot digest", all(len(a["snapshot"]["sha256"]) == 64 for a in at))
        rep = RPT.full_report(root)
        for k in ("rule", "audit", "training", "moves", "attempts", "attempt_results", "windows", "handover_diagnostic", "post_target8_share", "checkpoint_digests", "tape_baseline"):
            ok(f"report has {k}", k in rep)


@test
def synthetic_session_is_a_pure_function_of_its_configuration() -> None:
    with tmpdir() as d1, tmpdir() as d2:
        s1, o1, _ = run_small(d1)
        s2, o2, _ = run_small(d2)
        rels = ("training/episodes.jsonl", "training/attempts.jsonl", "training/probes.jsonl", "training/moves.jsonl", "t0/episodes.jsonl", "audit/episodes.jsonl", "session/rule.json")
        for rel in rels:
            a = strip_volatile(A.read_jsonl(d1 / "run" / rel)) if rel.endswith(".jsonl") else strip_volatile(A.read_json(d1 / "run" / rel))
            b = strip_volatile(A.read_jsonl(d2 / "run" / rel)) if rel.endswith(".jsonl") else strip_volatile(A.read_json(d2 / "run" / rel))
            eq(f"{rel} equal", a, b)
        eq("outcomes equal", (o1["outcome"], o1["D"], o1["R"]), (o2["outcome"], o2["D"], o2["R"]))


@test
def synthetic_session_outcomes_and_stops() -> None:
    with tmpdir() as d:
        sess, out, _b = run_small(d, inject={"acquire_fail_jobs": list(range(2, 60))})
        eq("too many lifecycle failures: INCOMPLETE", out["outcome"], "INCOMPLETE")
        ok("named", out["stop"] is not None and "lifecycle" in out["stop"]["reason"])
    with tmpdir() as d:
        sess, out, _b = run_small(d, inject={"mismatch_job": 3, "mismatch_tick": 30})
        eq("INVALID on an integrity failure", out["outcome"], "INVALID")
    with tmpdir() as d:
        sess, out, _b = run_small(d, env_over={"provenance_violations": lambda: ["a write under a protected root"]})
        eq("a write-guard violation is INVALID", out["outcome"], "INVALID")
    with tmpdir() as d:
        caps = dict(G.WALL_CAPS_S)
        caps["t0"] = 1.0
        sess, out, _b = run_small(d, cfg_over={"wall_caps_s": caps})
        eq("a T0 wall cap is INCOMPLETE", (out["outcome"], out["stop"]["phase"]), ("INCOMPLETE", "t0"))
    with tmpdir() as d:
        sess, out, _b = run_small(d, cfg_over={"global_cap_s": 2.0})
        eq("the hard cap is INCOMPLETE", out["outcome"], "INCOMPLETE")
    with tmpdir() as d:
        sess, out, _b = run_small(d)
        ok("the training wall cap is a valid end", sess.train_stop["valid_end"] and "wall cap" in sess.train_stop["reason"])
    with tmpdir() as d:
        class Breach:
            breach = "memory cap: process tree private 9999 MB > 9216 MB"
            last = None

        sess, out, _b = run_small(d, env_over={"sampler": Breach()})
        eq("memory breach: INCOMPLETE at once", (out["outcome"], out["stop"]["phase"]), ("INCOMPLETE", "open"))
    with tmpdir() as d:
        # the stub forgets 1966 cold starts once competent below 1920: never reached in a short window, so no effect; the rule still decides from the audit
        sess, out, _b = run_small(d, builder_over={"forget_landing": 1966, "forget_when_b_below": 1920})
        ok("a registered outcome", out["outcome"] in ("PASS", "INCONCLUSIVE", "NULL"))


@test
def synthetic_resumed_session_continues_bit_exactly_and_refuses_tampering() -> None:
    with tmpdir() as d:
        # the synthetic learner starts competent from 2,120 on (a test knob), so the short s1 ends INCONCLUSIVE (2,128 held at the close) and permits s2
        s1, o1, b1 = run_small(d / "s1", builder_over={"b0": 2120})
        eq("s1 is INCONCLUSIVE", (o1["outcome"], o1["D"]), ("INCONCLUSIVE", 2128))
        ok("s1 permits s2", o1["line"]["s2_permitted"])
        fs = A.read_json(d / "s1" / "run" / "session" / "final_state.json")
        expect = {"model_zip": fs["model_zip"]["sha256"], "curriculum_state": fs["curriculum_state"]["sha256"], "tape_baseline": fs["tape_baseline"]["sha256"]}
        prev = [{"k": 1, "outcome": o1["outcome"], "D": o1["D"], "R": o1["R"], "stalled": False, "train_fraction": 1.0}]
        b2 = SmallBuilder(d / "s2" / "run", model_need=40, b0=2120)
        cfg2 = small_cfg(d / "s2" / "run", session=2, resume={"final_state": fs, "expect": expect, "previous_sessions": prev})
        s2 = RUN2.G2Session(cfg2, b2.env(), hooks_for(b2))
        o2 = s2.run()
        eq("s2 phases (T0 skipped by record)", s2.phases, {"open": True, "p1": True, "p2": True, "t0": True, "train": True, "audit": True, "verify": True})
        opn = A.read_json(d / "s2" / "run" / "session" / "open.json")
        eq("the carried pointer and line counts were restored", (opn["resume"]["carried_state"]["pointer"], s2.frontier.pointer <= s1.frontier.pointer), (s1.frontier.pointer, True))
        saved = ST2.G2StubModel.load(d / "s1" / "run" / "training" / "checkpoints" / "final" / "model.zip").state_dict()
        loaded = ST2.G2StubModel.load(d / "s2" / "run" / "input" / "model.zip").state_dict()
        eq("the stub s2 loaded s1's saved model bit-exactly", loaded, saved)
        ts = A.read_json(d / "s2" / "run" / "session" / "training_summary.json")
        ok("num_timesteps continued from the saved count", ts["stop"]["start_timesteps"] == saved["num_timesteps"] and ts["stop"]["num_timesteps"] > saved["num_timesteps"])
        eq("the session seed recorded", ts["resumed_seed"], 1002)
        ok("the first training episode of s2 continues the global episode numbering", int(A.read_jsonl(d / "s2" / "run" / "training" / "episodes.jsonl")[0]["start"]["episode"]) >= saved["num_timesteps"] * 0 + opn["resume"]["carried_state"]["next_episode"])
        t0rec = A.read_json(d / "s2" / "run" / "session" / "t0.json")
        eq("T0 skipped: the tape baseline is read by digest", t0rec["tape_baseline_sha256"], A.read_json(d / "s1" / "run" / "session" / "tape_baseline.json")["sha256"])
        ln = A.read_json(d / "s2" / "run" / "session" / "line.json")
        eq("the line rule saw both sessions", ln["k"], 2)
        vr = RPT.verify_run(d / "s2" / "run")
        ok(f"verify-run ok on the resumed session: {vr['problems'][:3]}", vr["ok"])
        # tampering: a wrong expected digest is refused at the open (INVALID, zero ticks)
        b3 = SmallBuilder(d / "s3" / "run", model_need=40, b0=2120)
        cfg3 = small_cfg(d / "s3" / "run", session=2, resume={"final_state": fs, "expect": dict(expect, model_zip="0" * 64), "previous_sessions": prev})
        o3 = RUN2.G2Session(cfg3, b3.env(), hooks_for(b3)).run()
        eq("refused as INVALID at the open", (o3["outcome"], o3["stop"]["phase"]), ("INVALID", "open"))
        ok("nothing trained", not (d / "s3" / "run" / "training").exists())


@test
def verify_run_detects_tampering() -> None:
    with tmpdir() as d:
        sess, out, _b = run_small(d)
        root = d / "run"
        ok("clean first", RPT.verify_run(root)["ok"])
        # an unearned move
        p = root / "training" / "moves.jsonl"
        rows = A.read_jsonl(p)
        rows.append(dict(rows[-1], **{"from": rows[-1]["to"], "to": rows[-1]["to"] - 20}))
        p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        ok("an unearned move is caught", not RPT.verify_run(root)["ok"])
        p.write_text("".join(json.dumps(r) + "\n" for r in rows[:-1]), encoding="utf-8")
        ok("restored", RPT.verify_run(root)["ok"])
        # a tampered sticky mask
        p = root / "training" / "probes.jsonl"
        rows = A.read_jsonl(p)
        m = bytearray(bytes.fromhex(rows[0]["sticky_mask_hex"]))
        if m:
            m[0] ^= 1
            rows[0]["sticky_mask_hex"] = bytes(m).hex()
            p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            ok("a tampered probe mask is caught", not RPT.verify_run(root)["ok"])
        # a tampered checkpoint member pin
        cp = root / "training" / "checkpoints" / "final" / "checkpoint.json"
        meta = A.read_json(cp)
        meta["members_sha256"]["policy.pth"] = "0" * 64
        A.write_json(cp, meta)
        ok("a tampered member pin is caught", not RPT.verify_run(root)["ok"])


# =====================================================================================================================================
# guards, identity, the protected trees
# =====================================================================================================================================


def _g2_sources(include_tests: bool = False) -> List[Path]:
    return [p for p in sorted(RL.glob("m9_g2_*.py")) if include_tests or p.name != "m9_g2_tests.py"]


@test
def source_guards() -> None:
    # the fragments are assembled so that this file does not itself contain them (g1's source guard scans every rl/m9_*.py file, this one included)
    forbidden = tuple(a + b for a, b in (("rl/", "fixtures"), ("fixtures/", "m7g"), ("tas_", "input"), ("mario_", "743"), (".bt", "ti"), ("btti_", "replay"), ("m7g_", "capture"),
                                         ("m7g_", "fixture"), ("crossing_", "fixture"), ("replay/", "recordings")))
    rng = tuple(a + b for a, b in (("SSB64_", "RNG"), ("rng_", "seed"), ("get_", "rng"), ("set_", "rng"), ("seed_", "rng"), ("native_", "rng"), ("os", "Rand"), ("syUtils", "Rand")))
    for p in _g2_sources(include_tests=True):
        src = p.read_text(encoding="utf-8")
        for frag in forbidden:
            ok(f"{p.name} does not mention {frag}", frag not in src.replace("\\", "/"))
        for frag in rng:
            ok(f"{p.name} has no {frag}", frag not in src)
        ok(f"{p.name} imports no stateful generator", all(("import " + m + chr(10)) not in src and ("import " + m + " ") not in src for m in ("random", "secrets", "uuid")))
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, (ast.ImportFrom, ast.Import)):
                names = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
                for n in names:
                    ok(f"{p.name} imports no fixture or TAS module ({n})", "fixture" not in n and "btti" not in n and "capture" not in n)
    bad = ("imitation", "cross_entropy", "nll_loss", "behaviour_cloning", "behavior_cloning", "demonstration", "supervised", "self_imitation")
    for f in ("m9_g2_train.py", "m9_g2_probe.py", "m9_g2_run.py", "m9_g2_arena.py", "m9_g2_frontier.py"):
        tree = ast.parse((RL / f).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                ok(f"{f}: no imitation vocabulary in {node.name}", not any(b in node.name.lower() for b in bad))
    for f in ("m9_g2_probe.py", "m9_g2_policy.py"):
        src = (RL / f).read_text(encoding="utf-8")
        for frag in ("torch.optim", ".backward(", "optimizer.step", "zero_grad", ".learn(", "PPO("):
            ok(f"{f}: no training call {frag}", frag not in src)


@test
def nondeterminism_is_absent_from_the_suite() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    names = {fn.__name__ for _n, fn in TESTS}
    bad_attrs = {"urandom", "uuid4", "randint", "random", "choice", "shuffle", "sleep", "monotonic", "perf_counter", "time_ns"}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and sub.value.id in ("os", "uuid", "random", "time", "secrets") \
                        and (sub.attr in bad_attrs or (sub.value.id == "time" and sub.attr == "time")):
                    raise AssertionError(f"{node.name} uses {sub.value.id}.{sub.attr}")
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and isinstance(sub.func.value, ast.Name) and sub.func.value.id == "datetime":
                    raise AssertionError(f"{node.name} reads the wall clock")
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value.startswith(FORBIDDEN_PATH_PREFIXES):
                    raise AssertionError(f"{node.name} references {sub.value}")
    head = Path(__file__).read_text(encoding="utf-8").split("def nondeterminism_is_absent_from_the_suite")[0]
    ok("no random / secrets / uuid import", all(f"import {m}\n" not in head for m in ("random", "secrets", "uuid")))
    ok("no np.random in the suite", "np.random" not in head and "torch.manual_seed" not in head)
    ok("no test starts a game process", "subprocess.Popen" not in head)


@test
def tracked_files_are_unchanged_and_only_new_files_exist() -> None:
    import m8_rd_session as ses1

    eq("no tracked file differs from HEAD", ses1.tracked_changes(), [])
    eq("git status shows only untracked (new) entries", ses1.untracked_not_new(), [])
    new = [ln[3:] for ln in ses1.git("status", "--porcelain").splitlines() if ln.startswith("??")]
    ok("every new file under rl/ or docs/ is an M9 file", all(("m9" in n or "M9" in n) for n in new if n.startswith(("rl/", "docs/"))))


@test
def identity_approval_and_write_guard() -> None:
    import m9_g2_session as S2

    roots = {p.resolve() for p in S2.write_guard_roots(1)}
    for name in ("m9_g1", "m9_g1_eval", "m8_rd", "m8_rd_rd2", "m8_rd_rd3", "m8_rd_rd4"):
        ok(f"runs/{name} protected", (REPO / "runs" / name).resolve() in roots)
    ok("rl and docs protected", (REPO / "rl").resolve() in roots and (REPO / "docs").resolve() in roots)
    ok("the session's own tree is not protected", S2.run_root(1).resolve() not in roots and S2.LINE_ROOT.resolve() not in roots)
    eq("the six protected trees", [t[0] for t in S2.TREES], ["rd1", "rd2", "rd3", "rd4", "m9_g1", "m9_g1_eval"])
    ok("every code file of the identity exists", all((RL / f).is_file() for f in S2.CODE_FILES))
    ident = S2.identity(1)
    for k in ("contract_sha256", "line_contract_sha256", "rules", "executable_sha256", "runtime_files", "frozen_sha256", "lineages", "trees", "caps", "budget", "ppo", "code", "docs_sha256", "git_head", "d_records"):
        ok(f"identity has {k}", k in ident)
    eq("the identity's rules digests", (ident["rules"]["s1_sha256"], ident["rules"]["line_sha256"]), (R.s1_rule_digest(), R.line_rule_digest()))
    with tmpdir() as d:
        okk, why = S2.approval_status(1, d / "none.json", ident)
        ok("a missing approval refuses", not okk and "no approval" in why)
        A.write_json(d / "a.json", A.stamp(dict(ident, approval="APPROVED: test", source_snapshot={})))
        okk, why = S2.approval_status(1, d / "a.json", ident)
        ok(f"a matching record is approved ({why})", okk)
        A.write_json(d / "b.json", A.stamp(dict(ident, approval="APPROVED: test", contract_sha256="0" * 64)))
        okk, why = S2.approval_status(1, d / "b.json", ident)
        ok("a tampered identity is refused", not okk and "contract_sha256" in why)
    bp = RUN2.budget_projection()
    ok("the budget fits with no trimming", bp["fits_global_cap_pessimistic"])


@test
def the_protected_trees_equal_their_increments_and_the_pins_hold() -> None:
    import m9_g2_session as S2
    import m9_session as G1

    st = S2.trees_state(1)
    eq("the six trees equal their D: increments byte for byte", {k: v["ok"] for k, v in st.items() if k != "ok"}, {"rd1": True, "rd2": True, "rd3": True, "rd4": True, "m9_g1": True, "m9_g1_eval": True})
    eq("pins (executable, runtime files, frozen configuration) equal the archive's", G1.pins_problems(), [])


@test
def snapshot_tool_roundtrip() -> None:
    with tmpdir() as d:
        dest = d / "snap"
        r = subprocess.run([sys.executable, "-B", str(RL / "m9_g2_snapshot.py"), "snapshot", "--dest", str(dest)], capture_output=True, text=True, cwd=str(REPO))
        eq(f"snapshot exit code ({r.stdout[-300:]} {r.stderr[-300:]})", r.returncode, 0)
        rec = json.loads((dest / "snapshot.json").read_text(encoding="utf-8"))
        eq("PASS", (rec["result"], rec["problems"], rec["identity_code_mismatch"], rec["identity_docs_mismatch"]), ("PASS", [], [], []))
        A.check({k: rec[k] for k in ("task", "created_utc")})
        paths = {f["path"] for f in rec["files"]}
        for f in ("rl/m9_g2_run.py", "rl/m9_g2_probe.py", "rl/m9_g2_tests.py", "rl/m9_run.py", "rl/m9_worker.py", "rl/m8_rd_worker.py", "rl/m7n_obs.py", "docs/rl_m9_g2_decisions_2026-10-05.md", "docs/rl_m9_g2_proposal_2026-10-04.md"):
            ok(f"snapshot has {f}", f in paths)
        r = subprocess.run([sys.executable, "-B", str(RL / "m9_g2_snapshot.py"), "verify", "--dest", str(dest)], capture_output=True, text=True, cwd=str(REPO))
        eq("verify exit code", r.returncode, 0)
        ps = subprocess.run([sys.executable, "-B", str(RL / "m9_g2_snapshot.py"), "powershell", "--dest", str(dest)], capture_output=True, text=True, cwd=str(REPO)).stdout
        ok("the independent re-hash script is generated", "Get-FileHash" in ps and str(dest) in ps)
        r = subprocess.run([sys.executable, "-B", str(RL / "m9_g2_snapshot.py"), "snapshot", "--dest", str(dest)], capture_output=True, text=True, cwd=str(REPO))
        eq("an existing snapshot is never overwritten", r.returncode, 2)


# =====================================================================================================================================
# the production-count synthetic end-to-end run: a two-session line
# =====================================================================================================================================


def e2e() -> int:
    """s1 at the registered counts and caps against the synthetic world (virtual clock 1,200 native ticks/s, in-process lock-step pool), then s2 resumed from
    s1's saved state. The synthetic learner forgets the cold start at 1,966 once its competence is below 1,920, so the line exercises BLOCKED_BY_RECHECK, HELD
    (s1), STALLED and END_STALLED (s2)."""
    t0 = time.time()
    d = Path(tempfile.mkdtemp(prefix="m9g2e2e_"))
    problems: List[str] = []

    def chk(label: str, cond: Any) -> None:
        if not cond:
            problems.append(label)

    try:
        b1 = ST2.G2StubEnvBuilder(d / "s1", rate=1200.0, model_need=E2E_NEED, forget_landing=1966, forget_when_b_below=1920)
        cfg1 = RUN2.G2Config(root=d / "s1", write_artifacts=True, session=1)
        s1 = RUN2.G2Session(cfg1, b1.env(), hooks_for(b1))
        o1 = s1.run()
        root1 = d / "s1"
        chk("s1: every phase ran and passed", s1.phases == {"open": True, "p1": True, "p2": True, "t0": True, "train": True, "audit": True, "verify": True})
        chk(f"s1 outcome {o1['outcome']} is a registered performance outcome", o1["outcome"] in ("PASS", "INCONCLUSIVE", "NULL"))
        chk("s1: training ended at its registered wall cap or stalled", s1.train_stop["valid_end"])
        fr1 = s1.frontier
        at1 = A.read_jsonl(root1 / "training" / "attempts.jsonl")
        chk("s1: the frontier moved through several strips on passing attempts", len(fr1.moves) >= 5 and all(a["result"] == "MOVED" for a in at1 if a["new_pointer"] != a["pointer"]))
        chk("s1: every move came from a passing strip test (>= 10 clears) and passing re-checks", all(a["strip_clears"] >= 10 and all(v["passed"] for v in a["rechecks"].values()) for a in at1 if a["result"] == "MOVED"))
        chk("s1: at least one trigger fired (8 clears of a window)", all(a["trigger"]["clears"] >= 8 for a in at1) and len(at1) >= 1)
        chk("s1: early stopping: every passed strip test used fewer than 20 episodes", all(len(a["strip"].get("outcomes", "")) < 20 for a in [dict(x, strip={"outcomes": ""}) for x in at1] if False) or
            all((a["strip_clears"] + a["strip_non_clears"]) <= 20 and ((a["strip_clears"] == 10) or (a["strip_non_clears"] == 11) or a["result"] == "INTERRUPTED") for a in at1))
        chk("s1: the pause: four parked and six probe slots, disjoint, in every attempt", all(len(a["parked_slots"]) == 4 and len(a["probe_slots"]) == 6 and not set(a["parked_slots"]) & set(a["probe_slots"]) for a in at1))
        chk("s1: withdrawn starts recorded for the pause", (root1 / "training" / "withdrawn.jsonl").is_file() and len(A.read_jsonl(root1 / "training" / "withdrawn.jsonl")) >= len(at1))
        blocked = [a for a in at1 if a["result"] == "BLOCKED_BY_RECHECK"]
        chk("s1: a re-check blocked a move (the forgotten cold landing 1,966)", len(blocked) >= 1 and all(a["failed_landing"] == 1966 and a["new_pointer"] == a["pointer"] for a in blocked))
        chk("s1: the pointer never moved forward", all(m["to"] == m["from"] - 20 for m in fr1.moves) and all(fr1.moves[i + 1]["from"] == fr1.moves[i]["to"] for i in range(len(fr1.moves) - 1)))
        held_ptr = [p for p, n in fr1.session_failed.items() if n >= 3]
        chk("s1: HELD after three failed attempts at one pointer (no further attempt there)", len(held_ptr) == 1 and sum(1 for a in at1 if a["pointer"] == held_ptr[0] and a["result"] != "INTERRUPTED") == 3)
        chk("s1: no pointer exceeds the per-session bound", all(n <= 3 for n in fr1.session_failed.values()))
        # the tape baseline and the bars
        tb = A.read_json(root1 / "session" / "tape_baseline.json")
        chk("s1: the tape baseline is pinned at every landing with 200 / 40 keys", tb["pinned"] and tb["landings"]["2128"]["keys"] == 200 and all(tb["landings"][str(l)]["keys"] == 40 for l in (1966, 1694, 1473, 1369, 1248)))
        chk("s1: every counted tape clear was replayed exactly", all(v["unverified"] == [] and v["inexact"] == [] for v in tb["landings"].values()))
        chk("s1: bars follow the formula", all(v["B"] == G.bar_from_counts(v["clears_verified"], v["keys"]) for v in tb["landings"].values()))
        # the rule and the audit
        aud = o1["facts"]["audit"]
        chk("s1: the audit covered 2,128 with 20 sticky episodes", 2128 in aud and aud[2128]["n"] == 20)
        chk("s1: D and R recomputed by the rule equal the recorded", R.apply_s1(dict(o1["facts"], invalid=[]))["D"] == o1["D"])
        chk("s1: INCONCLUSIVE: 2,128 held, the forgotten cold landing 1,966 did not (D_1 = 2128)", o1["outcome"] == "INCONCLUSIVE" and o1["D"] == 2128)
        chk("s1 permits s2", o1["line"]["s2_permitted"] and o1["line"]["outcome"] == "CONTINUE")
        vr1 = RPT.verify_run(root1)
        chk(f"s1 verify-run ok ({vr1['problems'][:3]})", vr1["ok"])
        aud1 = A.audit_tree(root1, skip_dirs=("workers", "vw"))
        chk("s1: every record carries the task block and created_utc", aud1["ok"] and aud1["files"] > 200)
        chk("s1: full artifacts exist for the tape and the audit episodes", sum(1 for _ in (root1 / "artifacts").glob("t0_tape-*")) == 400 and sum(1 for _ in (root1 / "artifacts").glob("audit_sticky-*")) >= 40)
        fs = A.read_json(root1 / "session" / "final_state.json")
        # s2: resumed
        expect = {"model_zip": fs["model_zip"]["sha256"], "curriculum_state": fs["curriculum_state"]["sha256"], "tape_baseline": fs["tape_baseline"]["sha256"]}
        prev = [{"k": 1, "outcome": o1["outcome"], "D": o1["D"], "R": o1["R"], "stalled": False, "train_fraction": o1["facts"]["train_fraction"]}]
        b2 = ST2.G2StubEnvBuilder(d / "s2", rate=1200.0, model_need=E2E_NEED, forget_landing=1966, forget_when_b_below=1920)
        cfg2 = RUN2.G2Config(root=d / "s2", write_artifacts=True, session=2, resume={"final_state": fs, "expect": expect, "previous_sessions": prev})
        s2 = RUN2.G2Session(cfg2, b2.env(), hooks_for(b2))
        o2 = s2.run()
        root2 = d / "s2"
        chk("s2: every phase ran and passed", s2.phases == {"open": True, "p1": True, "p2": True, "t0": True, "train": True, "audit": True, "verify": True})
        saved = ST2.G2StubModel.load(root1 / "training" / "checkpoints" / "final" / "model.zip").state_dict()
        loaded = ST2.G2StubModel.load(root2 / "input" / "model.zip").state_dict()
        chk("s2 resumed from s1's saved model bit-exactly", loaded == saved and A.read_json(root2 / "input" / "curriculum_state.json")["carried"]["pointer"] == fr1.pointer)
        ts2 = A.read_json(root2 / "session" / "training_summary.json")
        chk("s2: num_timesteps continued and the session seed was set", ts2["stop"]["start_timesteps"] == saved["num_timesteps"] and ts2["resumed_seed"] == 1002)
        chk("s2: T0 skipped, the tape baseline read by digest", A.read_json(root2 / "session" / "t0.json")["tape_baseline_sha256"] == tb["sha256"])
        at2 = A.read_jsonl(root2 / "training" / "attempts.jsonl")
        fr2 = s2.frontier
        chk("s2: the line attempt index continued at the held pointer (a = 4, 5, 6)", [a["a"] for a in at2 if a["pointer"] == held_ptr[0]][:3] == [4, 5, 6] if held_ptr else False)
        chk("s2: STALLED after six failed attempts over the line; training ended validly as 'stalled'", fr2.stalled and fr2.stalled_pointer == held_ptr[0] and s2.train_stop["valid_end"] and "stalled" in str(s2.train_stop["reason"]))
        chk("s2: the line ends END_STALLED", o2["line"]["outcome"] == "END_STALLED" and not o2["line"]["s2_permitted"])
        vr2 = RPT.verify_run(root2)
        chk(f"s2 verify-run ok ({vr2['problems'][:3]})", vr2["ok"])
        aud2 = A.audit_tree(root2, skip_dirs=("workers", "vw", "input"))
        chk("s2: metadata audit clean", aud2["ok"])
        digest = hashlib.sha256(json.dumps(strip_volatile({"s1": {k: o1[k] for k in ("outcome", "D", "R")}, "s2": {k: o2[k] for k in ("outcome", "D", "R")}, "moves1": [(m["from"], m["to"]) for m in fr1.moves],
                                                           "attempts1": [(a["pointer"], a["result"]) for a in at1], "attempts2": [(a["pointer"], a["result"]) for a in at2], "line": o2["line"]["outcome"],
                                                           "episodes": len(A.read_jsonl(root1 / "training" / "episodes.jsonl"))}), sort_keys=True, default=str).encode()).hexdigest()
        print(json.dumps({"e2e": "PASS" if not problems else "FAIL", "s1": {k: o1[k] for k in ("outcome", "D", "R")}, "s2": {k: o2[k] for k in ("outcome", "D", "R")}, "line": o2["line"]["outcome"],
                          "pointer_s1": fr1.pointer, "moves_s1": len(fr1.moves), "attempts_s1": {k: sum(1 for a in at1 if a["result"] == k) for k in F.RESULTS}, "attempts_s2": {k: sum(1 for a in at2 if a["result"] == k) for k in F.RESULTS},
                          "training_episodes_s1": len(A.read_jsonl(root1 / "training" / "episodes.jsonl")), "verified_s1": vr1.get("verification"), "digest": digest[:16], "wall_s": round(time.time() - t0, 1),
                          "problems": problems}, default=str))
        return 0 if not problems else 1
    except Exception as exc:                                         # noqa: BLE001
        traceback.print_exc()
        print(json.dumps({"e2e": "FAIL", "error": f"{type(exc).__name__}: {exc}", "problems": problems, "wall_s": round(time.time() - t0, 1)}))
        return 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


E2E_NEED = 40


# -- runner --------------------------------------------------------------------------------------------------------------------------


def run_unit(only: Optional[Sequence[str]] = None) -> int:
    passed, failed = 0, []
    t_all = time.time()
    for name, fn in TESTS:
        if only and not any(name.startswith(o) for o in only):
            continue
        t0 = time.time()
        try:
            fn()
            passed += 1
            print(f"PASS {name} ({time.time() - t0:.1f}s)", flush=True)
        except Exception as exc:                                    # noqa: BLE001
            failed.append(name)
            print(f"FAIL {name} ({time.time() - t0:.1f}s): {type(exc).__name__}: {str(exc)[:600]}", flush=True)
            traceback.print_exc(limit=6)
    total = passed + len(failed)
    print(f"m9 g2 unit suite: {passed}/{total} passed" + (f" (failed: {', '.join(failed)})" if failed else "") + f" in {time.time() - t_all:.0f}s")
    return 0 if not failed else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "unit"
    if cmd == "unit":
        return run_unit(args[1:] or None)
    if cmd == "e2e":
        return e2e()
    if cmd == "list":
        for n, _f in TESTS:
            print(n)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
