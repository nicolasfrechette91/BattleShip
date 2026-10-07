#!/usr/bin/env python3
"""M9-g3 tests: the deterministic unit suite and the production-count synthetic end-to-end run (a two-session line with a reused tape baseline).

    python -B rl/m9_g3_tests.py unit           # the gating suite (deterministic by construction)
    python -B rl/m9_g3_tests.py e2e            # the production-count synthetic two-session line (virtual clock, in-process lock-step pool)
    python -B rl/m9_g3_tests.py list

DETERMINISM (g1's and g2's rules, kept). (a) Pure tests use keyed sha256 streams and fixed data. (b) Every session-level test runs the real g3 engine through
the in-process lock-step pool (rl/m9_pool.LocalPool) and a virtual clock against the synthetic world (rl/m9_stub, rl/m9_g2_stub): a run is a pure function of
its configuration. (c) The real SB3 save / load equivalence is tested on a zero-tick synthetic vector env with the real v3 spaces. (d) No test starts a game
process; nothing depends on process scheduling or wall-clock duration; a source scan forbids randomness, sleeps and wall-clock reads inside tests. (e) The
gates (git state with the one authorised edit, the seven protected trees and their D: increments, the executable and tape pins) assert facts fixed once
the trees are closed.

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

import m9_artifacts as A  # noqa: E402
import m9_contract as C  # noqa: E402
import m9_curriculum as CU  # noqa: E402
import m9_g2_arena as AR  # noqa: E402
import m9_g2_contract as G2  # noqa: E402
import m9_g2_frontier as F2  # noqa: E402
import m9_g2_policy as PO  # noqa: E402
import m9_g2_resume as RS  # noqa: E402
import m9_g2_rule as R2  # noqa: E402
import m9_g2_stub as ST2  # noqa: E402
import m9_g2_tape as TP  # noqa: E402
import m9_g3_contract as G  # noqa: E402
import m9_g3_frontier as F  # noqa: E402
import m9_g3_probe as PR  # noqa: E402
import m9_g3_report as RPT  # noqa: E402
import m9_g3_rule as R  # noqa: E402
import m9_g3_run as RUN3  # noqa: E402
import m9_g3_train as TR  # noqa: E402
import m9_lineages as L  # noqa: E402
import m9_sticky as S  # noqa: E402
import m9_stub as ST  # noqa: E402
import m9_vec as V  # noqa: E402
import m9_verify as VF  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RL = REPO / "rl"
TESTS: List[Tuple[str, Callable[[], None]]] = []
FORBIDDEN_PATH_PREFIXES = ("tas_" + "input_2/", "rl/" + "fixtures/")       # split so that this tuple is not itself a forbidden literal
SMALL_N_STEPS = 64                                                            # test configuration only: a short synthetic rollout so that attempts fire in a short virtual window
SMALL_TAPE_KEYS = {2128: 6, 1966: 3, 1694: 3}                                 # test configuration only: the small synthetic tape (the production table has 200 / 40)
E2E_NEED = 40


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
def tmpdir(prefix: str = "m9g3t_"):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def strip_volatile(o: Any) -> Any:
    drop = {"created_utc", "utc", "t_wall_s", "wall_s", "native_s", "build_s", "boot_s", "wait_s", "waits", "interval_transitions_per_s", "dispatch_to_ready_s", "t", "wall", "clock",
            "elapsed_s", "phase_wall_s", "pause_s", "t_start_s", "pid", "close", "sha256", "model_zip", "curriculum_state", "tape_baseline", "members_sha256", "model_zip_sha256",
            "curriculum_state_sha256", "snapshot", "snapshot_sha256", "path", "copy", "source", "files", "inputs", "file_sha256", "root", "stage"}
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


def hooks_for(b: ST2.G2StubEnvBuilder) -> RUN3.G3Hooks:
    return RUN3.G3Hooks(snapshot_of=ST2.G2StubEnvBuilder.snapshot_of, make_probe_policy=ST2.G2StubEnvBuilder.make_policy, audit_policy=ST2.G2StubEnvBuilder.policy_from_model_zip,
                        resume_model=b.resume_model, flatten=ST2.G2StubEnvBuilder.flatten)


def stub_tables_at(root: Path, b: ST2.G2StubEnvBuilder) -> Dict[str, L.Tables]:
    for name, ln in b.lineages.items():
        tr = b.route_traces[name]
        chain, v3 = L.build_tables(tr["initial"], tr["steps"], ST.StubObs)
        L.save_tables(root / "lineages", name, ln.words, chain, v3)
    return L.load_all_tables(root / "lineages", ["T_clear", "T_t"])


def stub_tables(d: Path, b: ST2.G2StubEnvBuilder) -> Dict[str, L.Tables]:
    return stub_tables_at(d / "run", b)


def synthetic_tape(d: Path, keys: Mapping[int, int] = SMALL_TAPE_KEYS, *, rate: float = 1200.0, n_slots: int = C.N_SLOTS) -> Dict[str, Any]:
    """A pinned tape table measured on the synthetic world by the g2 tape machinery (T0 jobs, the probe runner, exact replays of every claimed clear, the
    pinned table): the stand-in for g2-s1's reused table. Returns the reuse spec and the records path."""
    b = ST2.G2StubEnvBuilder(d / "tape", rate=rate, n_slots=n_slots)
    tables = stub_tables_at(d / "tape", b)
    pool = b.make_pool("tape", C.FLAGS_EVAL)
    jobs = TP.t0_jobs(dict(keys))
    arena = AR.G2Arena(pool, tables, PR.ProbeSource(jobs), AR.G2TickBudget(10 ** 9), now=b.clock.now)
    rec = PR.ProbeRecorder(d / "tape" / "episodes.jsonl", phase="t0", now=b.clock.now)
    res = PR.ProbeRunner(arena, tables, rec, policy=None, tests=None, now=b.clock.now, flatten=ST2.G2StubEnvBuilder.flatten).run()
    arena.wait_settled()
    pool.stop()
    if res["stop"] is not None or len(rec.records) != len(jobs):
        raise RuntimeError(f"the synthetic tape did not complete: {res['stop']}")
    claimed = TP.claimed_table(rec.records, dict(keys))
    vjobs = [VF.VerifyJob(c["id"], c["words"], c["online"], tau=c["tau"], tier=0, group="t0") for c in rec.clears]
    verified: Dict[str, bool] = {}
    VF.run_plan(vjobs, b.replay, ST.stub_analyse, tick_cap=10 ** 9, wall_cap_s=10 ** 6, threads=2, now=b.clock.now, on_result=lambda j, r: verified.__setitem__(j.id, bool(r["exact"])))
    pinned = TP.pinned_table(claimed, rec.records, verified)
    if not pinned["pinned"]:
        raise RuntimeError("the synthetic tape is not pinned")
    p = d / "tape" / "tape_baseline.json"
    A.write_json(p, A.stamp(dict(pinned)), overwrite=False)
    return {"path": str(p), "file_sha256": RS.sha256_file(p), "content_sha256": pinned["sha256"], "records": str(d / "tape" / "episodes.jsonl"), "keys": dict(keys), "table": pinned}


def small_cfg(root: Path, tape: Mapping[str, Any], **over: Any) -> RUN3.G3Config:
    caps = dict(G.WALL_CAPS_S)
    caps.update({"train": 420.0, "audit": 600.0})
    kw: Dict[str, Any] = dict(root=root, wall_caps_s=caps, p2_starts=3, landings=(2128, 1966, 1694), tape_keys=dict(tape["keys"]), audit_n=12, audit_unp=2, audit_det=1, tick0_n=2,
                              write_artifacts=False, first_clears=5, verify_threads=2, session=1,
                              tape_reuse={"path": tape["path"], "file_sha256": tape["file_sha256"], "content_sha256": tape["content_sha256"]}, tape_source_records=Path(tape["records"]))
    kw.update(over)
    return RUN3.G3Config(**kw)


def run_small(root: Path, *, tape: Optional[Mapping[str, Any]] = None, inject: Optional[Mapping[str, Any]] = None, need: int = 40, cfg_over: Optional[Mapping[str, Any]] = None,
              env_over: Optional[Mapping[str, Any]] = None, builder_over: Optional[Mapping[str, Any]] = None) -> Tuple[RUN3.G3Session, Dict[str, Any], ST2.G2StubEnvBuilder, Dict[str, Any]]:
    tape = tape or synthetic_tape(root)
    b = SmallBuilder(root / "run", inject=inject, model_need=need, **dict(builder_over or {}))
    cfg = small_cfg(root / "run", tape, **dict(cfg_over or {}))
    sess = RUN3.G3Session(cfg, b.env(**dict(env_over or {})), hooks_for(b))
    return sess, sess.run(), b, tape


def stub_policy(B: int, **kw: Any) -> ST2.G2StubPolicy:
    return ST2.G2StubPolicy({"B": B, "seed": 0, **kw}, "0" * 64)


def _strip_start(fr: F.Frontier, i: int, offset: int = 1) -> CU.Start:
    return CU.Start(i, "strip", fr.pointer + offset, "T_clear", True, fr.pointer)


def _trigger(fr: F.Frontier, base: int, *, clear: bool = True) -> Optional[Dict[str, Any]]:
    """Feed clears until the window fires (a trigger or a deferred trigger); returns the event."""
    ev = None
    for i in range(G.TRIGGER_CLEARS):
        ev = fr.record(_strip_start(fr, base + i), clear)
    return ev


# =====================================================================================================================================
# contract, keys, spacing
# =====================================================================================================================================


@test
def contract_registered_values() -> None:
    eq("gate, line, rule ids", (G.GATE, G.LINE_ID, G.FRONTIER_RULE_ID, G.S1_RULE_ID, G.LINE_RULE_ID, G.TAPE_RULE_ID), ("m9_g3", "m9_g3_line", "m9_g3_frontier_v1", "m9_g3_s1_rule_v1", "m9_g3_line_rule_v1", "m9_g2_tape_baseline_v1"))
    eq("the one change: spacing unit 20, cap 320", (G.SPACING_UNIT, G.SPACING_CAP), (20, 320))
    eq("need(f)", [G.spacing_need(f) for f in range(8)], [0, 20, 40, 80, 160, 320, 320, 320])
    eq("line budget", (G.LINE_BUDGET, G.LINE_SUCCESS_DEPTH, G.LINE_CAP_SESSIONS, G.LINE_PROGRESS_FROM_SESSION), ({2: 2128, 4: 1966, 6: 1694}, 1473, 8, 4))
    # everything else is read from g2 / g1, unchanged
    eq("trigger and test as g2", (G.TRIGGER_WINDOW, G.TRIGGER_CLEARS, G.TRIGGER_VOID_NONCLEARS, G.TEST_EPISODES, G.TEST_PASS, G.TEST_FAIL_NONCLEARS), (20, 8, 13, 20, 10, 11))
    eq("thresholds as g2", (G.PASS_REACH, G.INCONCLUSIVE_DEPTH, G.D_MIN_CLEARS, G.BAR_MIN, G.BAR_MARGIN, G.AUDIT_EPISODES, G.AUDIT_UNPERTURBED, G.AUDIT_DETERMINISTIC, G.TICK0_EPISODES), (1966, 2128, 10, 10, 5, 20, 20, 1, 20))
    eq("PPO is g2's (g1's with ent_coef 0.01, seed 0, fresh)", (G.PPO, G.PPO["ent_coef"], G.PPO["seed"], G.PPO["initialisation"]), (G2.PPO, 0.01, 0, "fresh"))
    eq("curriculum constants as g1", (G.TAU0, G.STRIP, C.NEAR_WINDOW, C.REGION_WEIGHTS, G.STICKY_P, G.LANDINGS, G.SHARED_PREFIX, G.TRUNK), (2300, 20, 40, (("strip", 50), ("near", 30), ("rehearsal", 20)), 0.25, (2128, 1966, 1694, 1473, 1369, 1248), 2298, "T_clear"))
    eq("the envelope: 80 minutes of training under a 145-minute cap; T0 is the drift check", (G.WALL_CAPS_S["train"], G.GLOBAL_CAP_S, G.WALL_CAPS_S["t0"], G.TICK_CAPS["t0"], G.TRANSITION_CAP), (4800.0, 8700.0, 240.0, 60_000, 3_072_000))
    eq("the other caps as g2", ({k: v for k, v in G.WALL_CAPS_S.items() if k != "t0"}, {k: v for k, v in G.TICK_CAPS.items() if k != "t0"}), ({k: v for k, v in G2.WALL_CAPS_S.items() if k != "t0"}, {k: v for k, v in G2.TICK_CAPS.items() if k != "t0"}))
    eq("split and slots as g2", (G.SPLIT, G.PROBE_SLOTS, G.N_SLOTS, G.MAX_BATTLESHIP_PROCESSES, G.MEMORY_CAPS_MB, G.VERIFY_LAUNCH_MARGIN_S), ((4, 6), 6, 10, 10, G2.MEMORY_CAPS_MB, 120.0))
    eq("the reused tape pins", (G.TAPE_REUSE["file_sha256"][:16], G.TAPE_REUSE["content_sha256"][:16], G.TAPE_REUSE["measured_with_executable_sha256"][:16], G.TAPE_REUSE["keys"], G.DRIFT_LANDING, G.DRIFT_KEYS),
       ("81fa52c21078b2c2", "d915fab920554774", "30a3913b32c44353", {2128: 200, 1966: 40, 1694: 40, 1473: 40, 1369: 40, 1248: 40}, 2128, 5))
    fd = G.frontier_description()
    ok("no attempt bounds in the frontier description", "per_session" not in json.dumps(fd) and "per_line" not in json.dumps(fd) and fd["attempts"]["spacing"]["unit"] == 20 and fd["attempts"]["spacing"]["cap"] == 320)
    ok("the g3 digests differ from g2's and are stable", G.contract_digest() != G2.contract_digest() and G.line_contract_digest() != G2.line_contract_digest() and G.line_contract_digest() == G.line_contract_digest())
    ok("the description names g2's and g1's digests", G.description()["g2_line_contract_sha256"] == G2.line_contract_digest() and G.description()["g1_contract_sha256"] == C.contract_digest())
    bp = RUN3.budget_projection()
    ok("the pessimistic budget fits the 145-minute cap with no trimming", bp["fits_global_cap_pessimistic"] and bp["pessimistic_total_s"] == 7780.0 and bp["slack_pessimistic_s"] == 920.0)
    eq("the rule self-test passes", R.self_test(), [])


@test
def key_strings_are_the_g3_family_except_the_reach_label() -> None:
    for k, v in G.KEYS.items():
        if k in ("reach_label", "p2", "sticky"):
            continue
        ok(f"{k} is a g3 key", v.startswith("m9|g3|"))
    eq("the reach label is the reused tape's g2 family (pairing)", (G.KEYS["reach_label"], G.reach_label(2128, 7)), ("m9|g2|reach|<landing>|<k>", "m9|g2|reach|2128|7"))
    eq("train label", G.train_label(5), "m9|g3|train|5")
    eq("probe keys", (G.probe_label(2280, 2, "strip", 3), G.probe_label(2280, 2, 2128, 3), G.probe_action_key(2280, 2, "strip", 3, 2290)), ("m9|g3|probe|2280|2|strip|3", "m9|g3|probe|2280|2|2128|3", "m9|g3|probeact|2280|2|strip|3|2290"))
    eq("audit keys", (G.audit_action_key("sticky", 2128, 4, 2200), G.tick0_label(2), G.verify_pick_key(2280, 1, "strip"), G.artifact_sample_key(9)), ("m9|g3|auditact|sticky|2128|4|2200", "m9|g3|tick0|2", "m9|g3|verifypick|2280|1|strip", "m9|g3|artifact|9"))
    raises("an unknown audit mode is refused", ValueError, lambda: G.audit_action_key("x", 2128, 0, 0))
    ok("g3 train keys differ from g2's", G.train_label(5) != G2.train_label(5) and G.start_key(5, "tau") != G2.start_key(5, "tau") and G.probe_label(2280, 1, "strip", 0) != G2.probe_label(2280, 1, "strip", 0))


# =====================================================================================================================================
# the frontier: the window (as g2), the spacing rule (the one change)
# =====================================================================================================================================


@test
def frontier_window_trigger_and_void_as_g2() -> None:
    fr = F.Frontier({"T_clear": 2326, "T_t": 2315}, session=1)
    for i in range(7):
        ok("no event before the 8th clear", fr.record(_strip_start(fr, i), True) is None)
    ev = fr.record(_strip_start(fr, 7), True)
    eq("the 8th clear triggers (f = 0: no spacing)", (ev["event"], ev["clears"], ev["size"], ev["spacing"]), ("trigger", 8, 8, {"f": 0, "need": 0, "have": 8, "ok": True}))
    ok("pending", fr.pending is not None and fr.pending["a"] == 1)
    ev2 = fr.record(_strip_start(fr, 8), False)
    eq("outcomes after the trigger belong to no window but count toward the spacing", (ev2["event"], fr.since_failed), ("after_trigger", 9))
    rec = fr.begin_attempt(episodes_before=9)
    fr.finish_attempt(rec, "FAILED_STRIP", strip={"clears": 5, "non_clears": 11, "passed": False}, rechecks={})
    eq("a failed attempt counts, resets the outcome counter and restarts the window", (fr.line_failed[2300], fr.session_failed[2300], fr.window["why"], fr.pending, fr.since_failed), (1, 1, "attempt", None, 0))
    for i in range(12):
        ok("no event before the 13th non-clear", fr.record(_strip_start(fr, 100 + i), False) is None)
    ev = fr.record(_strip_start(fr, 112), False)
    eq("the 13th non-clear voids the window", (ev["event"], ev["non_clears"]), ("void", 13))
    for i in range(7):
        fr.record(_strip_start(fr, 200 + i), True)
    for i in range(12):
        fr.record(_strip_start(fr, 300 + i), False)
    ev = fr.record(_strip_start(fr, 400), False)
    eq("void at 7 clears + 13 non-clears", (ev["event"], ev["clears"]), ("void", 7))
    before = dict(fr.window)
    fr.record(CU.Start(500, "near", 2325, "T_clear", False, fr.pointer), True)
    fr.record(CU.Start(501, "strip", 2281, "T_clear", True, 2280), True)
    eq("non-strip and stale ignored (and never counted toward the spacing)", (fr.window["clears"], fr.window["non_clears"], fr.outside, fr.stale, fr.since_failed), (before["clears"], before["non_clears"], 1, 1, 33))


@test
def frontier_spacing_replenishes_attempts_and_never_freezes() -> None:
    lengths = {"T_clear": 2326, "T_t": 2315}
    fr = F.Frontier(lengths, session=1)
    _trigger(fr, 0)
    rec = fr.begin_attempt(episodes_before=8)
    eq("a = 1 and no spacing at f = 0", (rec["a"], rec["spacing"]), (1, {"f": 0, "need": 0, "have": 8, "ok": True}))
    fr.finish_attempt(rec, "MOVED", strip={"clears": 10, "non_clears": 2, "passed": True}, rechecks={})
    eq("moved back 20; the move records the failed attempts it followed", (fr.pointer, fr.moves_all[-1]["from"], fr.moves_all[-1]["to"], fr.moves_all[-1]["after_failed_attempts"], fr.since_failed), (2280, 2300, 2280, 0, 0))
    # consecutive failures: the schedule 20, 40, 80, 160, 320, 320, 320 and the deferred triggers inside each spacing
    schedule: List[Tuple[int, int, int]] = []
    deferred_total = 0
    e = 1000
    for n in range(7):
        ev = None
        while fr.pending is None:
            ev = fr.record(_strip_start(fr, e), True)
            e += 1
            if ev is not None and ev["event"] == "deferred_trigger":
                deferred_total += 1
                ok("a deferred trigger is inside its spacing", ev["spacing"]["have"] < ev["spacing"]["need"] and not ev["spacing"]["ok"])
                ok("no attempt pending after a deferred trigger; the window restarted", fr.pending is None and fr.window["why"] == "deferred_trigger" and fr.window["clears"] == 0)
        rec = fr.begin_attempt(episodes_before=e)
        schedule.append((rec["spacing"]["f"], rec["spacing"]["need"], rec["spacing"]["have"]))
        eq("the line attempt index is f + 1", rec["a"], rec["spacing"]["f"] + 1)
        fr.finish_attempt(rec, "BLOCKED_BY_RECHECK" if n % 2 else "FAILED_STRIP", strip={"clears": 10, "non_clears": 1, "passed": True} if n % 2 else {"clears": 3, "non_clears": 11, "passed": False},
                          rechecks={2128: {"clears": 2, "non_clears": 11, "passed": False}} if n % 2 else {}, failed_landing=2128 if n % 2 else None)
        ok("never HELD, never STALLED, no stalled pointer", not fr.held() and not fr.stalled and fr.stalled_pointer is None)
        eq("the counter resets after a failed attempt", fr.since_failed, 0)
    eq("the replenishment schedule as it ran: f, need, have (the attempt runs exactly when the need is met)", schedule, [(0, 0, 8), (1, 20, 24), (2, 40, 40), (3, 80, 80), (4, 160, 160), (5, 320, 320), (6, 320, 320)])
    ok("triggers inside the spacing were deferred (never an attempt)", deferred_total >= 100 and fr.deferred == deferred_total)
    eq("after seven failures the frontier is still live: f = 7, need = 320 (the cap), nothing frozen", (fr.f(), fr.need(), fr.line_failed[2280], fr.held(), fr.stalled), (7, 320, 7, False, False))
    # an attempt inside its spacing is refused even with a pending trigger forced in
    fr.pending = {"pointer": fr.pointer, "a": fr.next_attempt_index(), "forced": True}
    raises("an attempt inside its spacing is refused", F.FrontierError, lambda: fr.begin_attempt(episodes_before=e))
    fr.pending = None
    # the attempt after the cap: 320 more outcomes, then it runs; a pass resets f and the counter at the new pointer
    while fr.pending is None:
        fr.record(_strip_start(fr, e), True)
        e += 1
    rec = fr.begin_attempt(episodes_before=e)
    eq("the attempt after the cap: f = 7, need 320, have 320", (rec["spacing"]["f"], rec["spacing"]["need"], rec["spacing"]["have"], rec["a"]), (7, 320, 320, 8))
    fr.finish_attempt(rec, "MOVED", strip={"clears": 10, "non_clears": 0, "passed": True}, rechecks={})
    eq("a move after seven failures resets f at the new pointer", (fr.pointer, fr.f(), fr.need(), fr.since_failed, fr.moves_all[-1]["after_failed_attempts"]), (2260, 0, 0, 0, 7))
    # INTERRUPTED: neither pass nor fail; f and the counter unchanged; the window restarts
    _trigger(fr, 5000)
    rec = fr.begin_attempt(episodes_before=e)
    fr.finish_attempt(rec, "FAILED_STRIP", strip={"clears": 3, "non_clears": 11, "passed": False}, rechecks={})
    for i in range(10):
        fr.record(_strip_start(fr, 6000 + i), False)
    for i in range(30):
        fr.record(_strip_start(fr, 6100 + i), True)
    ok("pending after 20+ outcomes at f = 1", fr.pending is not None and fr.since_failed == 40)
    rec = fr.begin_attempt(episodes_before=e)
    fr.finish_attempt(rec, "INTERRUPTED", strip={"clears": 3, "non_clears": 2, "passed": False}, rechecks={})
    eq("interrupted: f and the counter unchanged, the window restarted", (fr.f(), fr.since_failed, fr.window["why"], fr.line_failed[2260]), (1, 40, "interrupted", 1))
    # a move needs every test passed
    fr3 = F.Frontier(lengths, session=1)
    _trigger(fr3, 0)
    rec = fr3.begin_attempt(episodes_before=8)
    raises("a move without a passing strip test is refused", F.FrontierError, lambda: fr3.finish_attempt(rec, "MOVED", strip={"clears": 9, "non_clears": 11, "passed": False}, rechecks={}))
    eq("landings as g2", (F.landings_behind(1980), F.audit_landings(1980), F.audit_landings(2300), F.audit_landings(2108), F.audit_landings(1240)), ([2128], [2128, 1966], [2128], [2128, 1966], [2128, 1966, 1694, 1473, 1369, 1248]))


@test
def frontier_state_is_carried_across_sessions_with_the_spacing() -> None:
    lengths = {"T_clear": 2326, "T_t": 2315}
    fr = F.Frontier(lengths, session=1)
    _trigger(fr, 0)
    rec = fr.begin_attempt(episodes_before=8)
    fr.finish_attempt(rec, "MOVED", strip={"clears": 10, "non_clears": 2, "passed": True}, rechecks={})
    e = 100
    for n in range(3):
        while fr.pending is None:
            fr.record(_strip_start(fr, e), True)
            e += 1
        rec = fr.begin_attempt(episodes_before=e)
        fr.finish_attempt(rec, "FAILED_STRIP", strip={"clears": 3, "non_clears": 11, "passed": False}, rechecks={})
    for i in range(33):
        fr.record(_strip_start(fr, 9000 + i), False)
    eq("state before the carry", (fr.pointer, fr.f(), fr.need(), fr.since_failed), (2280, 3, 80, 33))
    carried = fr.carried_state()
    eq("the carried state names the g3 frontier and the spacing counter", (carried["frontier"], carried["since_failed"], carried["line_failed"]), ("m9_g3_frontier_v1", 33, {"2280": 3}))
    ok("no HELD / STALLED in the carried state", "stalled" not in carried and "held" not in carried)
    fr2 = F.Frontier(lengths, session=2, state=carried)
    eq("carried: pointer, f, need, have, the line attempt index", (fr2.pointer, fr2.f(), fr2.need(), fr2.since_failed, fr2.next_attempt_index(), fr2.session_failed), (2280, 3, 80, 33, 4, {}))
    deferred = 0
    i = 0
    while fr2.pending is None:
        ev = fr2.record(_strip_start(fr2, 9100 + i), True)
        deferred += int(ev is not None and ev["event"] == "deferred_trigger")
        i += 1
    # windows of 8 clears fire at 41, 49, 57, 65, 73 (deferred: inside the spacing of 80) and at 81 (the trigger): the 33 carried outcomes count
    eq("the spacing continues across the session boundary: the carried 33 outcomes count toward the need of 80", (deferred, fr2.since_failed, fr2.pending["spacing"]), (5, 81, {"f": 3, "need": 80, "have": 81, "ok": True}))
    rec = fr2.begin_attempt(episodes_before=0)
    eq("the attempt index continues (a = 4)", rec["a"], 4)
    st = fr2.state()
    ok("the state has the spacing and no bounds", st["spacing"]["f"] == 3 and "bounds" not in st and "held" not in st and "stalled" not in st and st["frontier"] == "m9_g3_frontier_v1")
    # another line's state is refused
    raises("a g2 carried state is refused", F.FrontierError, lambda: F.Frontier(lengths, session=2, state=dict(carried, frontier="m9_g2_frontier_v1")))
    raises("a STALLED flag is refused", F.FrontierError, lambda: F.Frontier(lengths, session=2, state=dict(carried, stalled=True)))


@test
def frontier_starts_are_keyed_g3_and_within_the_strip() -> None:
    lengths = {"T_clear": 2326, "T_t": 2315}
    fr = F.Frontier(lengths, session=1)
    regions: Dict[str, int] = {}
    for e in range(600):
        s = fr.draw(e)
        regions[s.region] = regions.get(s.region, 0) + 1
        ok("strip start in the strip", s.region != "strip" or 2300 <= s.tau < 2320)
        ok("a start never lies on a terminal tick", s.tau <= 2324)
    ok("the mix is about 50 / 30 / 20 (rehearsal empty at 2300 -> near)", 250 < regions["strip"] < 350 and regions.get("rehearsal", 0) == 0)
    eq("a start is a pure function of (episode, pointer)", fr.draw(17).to_json(), F.Frontier(lengths, session=1).draw(17).to_json())
    ok("g3 starts differ from g2's and g1's for the same episodes", any(fr.draw(e).to_json() != F2.Frontier(lengths, session=1).draw(e).to_json() for e in range(20))
       and any(fr.draw(e).to_json() != CU.Curriculum(lengths).draw(e).to_json() for e in range(20)))
    taus = [F.strip_start(2300, 1, k, lengths)[0] for k in range(20)]
    ok("strip-test starts cover the strip", all(2300 <= t < 2320 for t in taus) and len(set(taus)) > 8)
    eq("keyed and stable", F.strip_start(2280, 3, 5, lengths), F.strip_start(2280, 3, 5, lengths))
    ok("a different attempt index gives different starts", [F.strip_start(2280, 1, k, lengths)[0] for k in range(20)] != [F.strip_start(2280, 2, k, lengths)[0] for k in range(20)])
    ok("g3 strip starts differ from g2's", [F.strip_start(2280, 1, k, lengths)[0] for k in range(20)] != [F2.strip_start(2280, 1, k, lengths)[0] for k in range(20)])


@test
def frontier_history_rebuilds_and_names_an_attempt_inside_its_spacing() -> None:
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

    def attempt(result: str) -> None:
        while fr.pending is None:
            play(1, True)
        rec = fr.begin_attempt(episodes_before=len(episodes))
        if result == "MOVED":
            fr.finish_attempt(rec, "MOVED", strip={"clears": 10, "non_clears": 3, "passed": True}, rechecks={})
        else:
            fr.finish_attempt(rec, "FAILED_STRIP", strip={"clears": 4, "non_clears": 11, "passed": False}, rechecks={})
        attempts.append(json.loads(json.dumps({k: v for k, v in rec.items() if k != "clears_for_verification"}, default=str)))

    attempt("MOVED")
    attempt("FAILED_STRIP")
    attempt("FAILED_STRIP")
    attempt("MOVED")
    play(30, False)
    rep = F.replay_history(episodes, attempts, lengths, session=1)
    eq("rebuilt", (rep["pointer"], rep["moves"], rep["attempts"], rep["problems"], [(s["f"], s["need"]) for s in rep["schedule"]]), (2260, [(2300, 2280), (2280, 2260)], 4, [], [(0, 0), (0, 0), (1, 20), (2, 40)]))
    ok("the deferred triggers are rebuilt", rep["deferred_triggers"] == fr.deferred and rep["deferred_triggers"] >= 1)
    bad = json.loads(json.dumps(attempts))
    bad[0]["strip_clears"] = 9
    bad[0]["strip_passed"] = False
    ok("a move without a passing strip is caught", F.replay_history(episodes, bad, lengths, session=1)["problems"])
    bad = json.loads(json.dumps(attempts))
    bad[1]["a"] = 5
    ok("a wrong line index is caught", F.replay_history(episodes, bad, lengths, session=1)["problems"])
    bad = json.loads(json.dumps(attempts))
    bad[2]["episodes_before"] = bad[1]["episodes_before"] + 3                # the third attempt moved to 3 outcomes after the second: inside its spacing of 20
    probs = F.replay_history(episodes, bad, lengths, session=1)["problems"]
    ok(f"an attempt inside its spacing is caught ({probs[:2]})", any("inside its spacing" in p for p in probs))
    bad = json.loads(json.dumps(attempts))
    bad[2]["spacing"]["have"] = 999
    ok("a recorded spacing that differs from the rebuilt is caught", any("recorded spacing" in p for p in F.replay_history(episodes, bad, lengths, session=1)["problems"]))
    bad = json.loads(json.dumps(attempts))
    bad[1]["episodes_before"] = 0
    ok("an attempt before any trigger is caught", F.replay_history(episodes, bad, lengths, session=1)["problems"])
    bad_eps = json.loads(json.dumps(episodes))
    bad_eps[3]["start"]["tau"] = 2311
    ok("a start that does not reproduce from its keys is caught", F.replay_history(bad_eps, attempts, lengths, session=1)["problems"])


# =====================================================================================================================================
# the rules
# =====================================================================================================================================


@test
def rules_self_test_and_the_line_never_ends_on_attempts() -> None:
    eq("self-test", R.self_test(), [])
    eq("s1 NULL continues the line", R.apply_line([{"k": 1, "outcome": "NULL", "D": None, "train_fraction": 1.0}])["outcome"], "CONTINUE")
    huge = [{"k": 1, "outcome": "INCONCLUSIVE", "D": 2128, "train_fraction": 1.0, "attempts": 10 ** 6, "failed_attempts": {"2280": 10 ** 6}, "stalled": True, "held": True}]
    eq("attempt counts, HELD and STALLED are never read", R.apply_line(huge)["outcome"], "CONTINUE")
    src = (RL / "m9_g3_rule.py").read_text(encoding="utf-8")
    ok("the line rule's code reads no attempt count", "failed_attempts" not in src.split("def apply_line")[1].split("def _row")[0] and "stalled" not in src.split("def apply_line")[1].split("def _row")[0].lower().replace("stalled flag", ""))
    eq("the s1 rule id and digest", (R.apply_s1({"invalid": ["x"]})["rule"], len(R.s1_rule_digest())), ("m9_g3_s1_rule_v1", 64))


# =====================================================================================================================================
# probes, the attempt
# =====================================================================================================================================


@test
def probe_jobs_are_keyed_g3_and_the_audit_pairs_with_the_reused_tape() -> None:
    lengths = {"T_clear": 2326, "T_t": 2315}
    sj = PR.strip_jobs(2280, 2, lengths)
    eq("20 strip jobs on g3 labels and action keys", (len(sj), sj[0].label, sj[0].extra["akey"], sj[0].job_id), (20, "m9|g3|probe|2280|2|strip|0", "m9|g3|probeact|2280|2|strip|0", "probe-2280-2-strip-00"))
    rj = PR.recheck_jobs(1940, 1, [2128, 1966])
    eq("re-check jobs interleaved by k, trunk landings", ([j.extra["landing"] for j in rj[:4]], rj[0].label, rj[0].start.tau), ([2128, 1966, 2128, 1966], "m9|g3|probe|1940|1|2128|0", 2128))
    aj = PR.audit_jobs([2128, 1966], n=20, n_unp=20, n_det=1, tick0_n=20)
    sticky = [j for j in aj if j.kind == "audit_sticky"]
    eq("audit sticky labels are the reused tape's g2 family; action keys are g3's", (sticky[0].label, sticky[0].extra["akey"], len(sticky)), ("m9|g2|reach|2128|0", "m9|g3|auditact|sticky|2128|0", 40))
    t0 = [j for j in aj if j.kind == "tick0_sticky"]
    eq("tick-0 labels are g3's", (t0[0].label, len(t0)), ("m9|g3|tick0|0", 20))
    eq("counts as g2", ({k: sum(1 for j in aj if j.kind == k) for k in ("audit_sticky", "tick0_sticky", "audit_unperturbed", "audit_det", "tick0_det")}), ({"audit_sticky": 40, "tick0_sticky": 20, "audit_unperturbed": 40, "audit_det": 2, "tick0_det": 1}))
    dj = PR.drift_jobs()
    eq("drift jobs: 5 tape keys at 2,128 on the reused labels", ([j.job_id for j in dj], dj[0].label, dj[0].driver, dj[0].start.tau), ([f"drift_tape-2128-{k:03d}" for k in range(5)], "m9|g2|reach|2128|0", "tape", 2128))


@test
def run_attempt_moves_fails_blocks_interrupts_and_refuses_inside_the_spacing() -> None:
    lengths = {"T_clear": 2326, "T_t": 2315}
    with tmpdir() as d:
        b = SmallBuilder(d / "run")
        tables = stub_tables(d, b)
        pool = b.make_pool("x", C.FLAGS_TRAIN)
        fr = F.Frontier(lengths, session=1)
        src = TR.TrainSource(fr)
        train_arena = AR.G2Arena(pool, tables, src, AR.G2TickBudget(10 ** 8), now=b.clock.now)
        while len(train_arena.active) < 4:
            train_arena.pump(0.0)
            while train_arena.ready and len(train_arena.active) < 4:
                train_arena.activate(train_arena.ready.popleft())
        train_arena.pump(0.0)
        parked_before = sorted(train_arena.active)
        eq("four active", len(parked_before), 4)
        _trigger(fr, 0)
        model = ST2.G2StubModel(None, n_steps=4, b0=2200)
        kw = dict(train_arena=train_arena, pool=pool, tables=tables, train_budget=train_arena.budget, lengths=lengths, make_policy=ST2.G2StubEnvBuilder.make_policy, attempt_root=d / "run" / "attempts",
                  probes_jsonl=d / "run" / "probes.jsonl", attempts_jsonl=d / "run" / "attempts.jsonl", withdrawn_jsonl=d / "run" / "withdrawn.jsonl", now=b.clock.now, guard=lambda: None, log=lambda s: None,
                  num_timesteps=0, flatten=ST2.G2StubEnvBuilder.flatten)
        rec = PR.run_attempt(frontier=fr, snapshot=ST2.G2StubEnvBuilder.snapshot_of(model), episodes_before=8, **kw)
        eq("moved", (rec["result"], fr.pointer, rec["a"], rec["spacing"]["f"]), ("MOVED", 2280, 1, 0))
        eq("the four playing slots stayed parked", sorted(train_arena.active), parked_before)
        eq("the six others ran the attempt", (len(rec["probe_slots"]), sorted(rec["probe_slots"]) == sorted(set(range(10)) - set(parked_before))), (6, True))
        ok("the training arena is unpaused and settled; probe ticks charged", not train_arena.paused and train_arena.settled() and train_arena.budget.probe > 0)
        ok("the attempt record carries the spacing before and after", A.read_jsonl(d / "run" / "attempts.jsonl")[0]["spacing"] == {"f": 0, "need": 0, "have": 8, "ok": True} and "spacing_after" in A.read_jsonl(d / "run" / "attempts.jsonl")[0])
        ok("probe records on g3 labels", all(r["label"].startswith("m9|g3|probe|2300|1|strip|") for r in A.read_jsonl(d / "run" / "probes.jsonl")))
        ok("one keyed clear picked for verification", len(rec["clears_for_verification"]) == 1 and rec["clears_for_verification"][0]["part"] == "strip")
        nxt = src.next_job(train_arena)
        ok("withdrawn episode numbers are never drawn again", all(int(w["episode"].split("-")[1]) < nxt.episode for w in A.read_jsonl(d / "run" / "withdrawn.jsonl")))
        train_arena.pump(0.0)
        # a failing strip at 2,180 (every keyed start faces critical ticks before the clear; the world's last critical tick is 2,211) with an incompetent snapshot: FAILED_STRIP, f = 1, need 20
        frf = F.Frontier(lengths, session=1, state={"frontier": "m9_g3_frontier_v1", "pointer": 2180, "line_failed": {}, "since_failed": 0, "moves": [], "next_episode": 0, "attempt_counter": 0, "sessions": [1]})
        _trigger(frf, 100)
        rec2 = PR.run_attempt(frontier=frf, snapshot=ST2.G2StubEnvBuilder.snapshot_of(ST2.G2StubModel(None, n_steps=4, b0=2400)), episodes_before=16, **kw)
        eq("failed strip: f = 1, need 20, counter reset", (rec2["result"], frf.pointer, frf.line_failed[2180], rec2["a"], frf.spacing_state()), ("FAILED_STRIP", 2180, 1, 1, {"f": 1, "need": 20, "have": 0, "ok": False}))
        # a second trigger inside the spacing is deferred; run_attempt is refused (no pending); after 20 outcomes it runs (a = 2)
        ev = _trigger(frf, 200)
        eq("deferred inside the spacing", (ev["event"], frf.pending), ("deferred_trigger", None))
        raises("no attempt without a pending trigger", F.FrontierError, lambda: PR.run_attempt(frontier=frf, snapshot=ST2.G2StubEnvBuilder.snapshot_of(model), episodes_before=24, **kw))
        i = 300
        while frf.pending is None:                                   # windows of 8 clears fire at 8 and 16 (deferred) and at 24 (the trigger)
            frf.record(_strip_start(frf, i), True)
            i += 1
        ok("the spacing met, the next trigger is pending with a = 2", frf.pending["a"] == 2 and frf.since_failed == 24 and frf.deferred == 2)
        rec2b = PR.run_attempt(frontier=frf, snapshot=ST2.G2StubEnvBuilder.snapshot_of(ST2.G2StubModel(None, n_steps=4, b0=2400)), episodes_before=40, **kw)
        eq("the replenished attempt ran on the next line index and failed again: f = 2, need 40", (rec2b["result"], rec2b["a"], frf.spacing_state()), ("FAILED_STRIP", 2, {"f": 2, "need": 40, "have": 0, "ok": False}))
        ok("the probe labels of the second attempt carry a = 2", any(r["label"].startswith("m9|g3|probe|2180|2|strip|") for r in A.read_jsonl(d / "run" / "probes.jsonl")))
        # a re-check blocked at the forgotten cold landing 1,966
        fr2 = F.Frontier(lengths, session=1, state={"frontier": "m9_g3_frontier_v1", "pointer": 1940, "line_failed": {}, "since_failed": 0, "moves": [], "next_episode": 0, "attempt_counter": 0, "sessions": [1]})
        _trigger(fr2, 200)
        rec3 = PR.run_attempt(frontier=fr2, snapshot=ST2.G2StubEnvBuilder.snapshot_of(ST2.G2StubModel(None, n_steps=4, b0=1900, forget_landing=1966, forget_when_b_below=1920)), episodes_before=0, **kw)
        eq("blocked by the re-check at 1966; the pointer never moves; f = 1", (rec3["result"], rec3["failed_landing"], fr2.pointer, fr2.f()), ("BLOCKED_BY_RECHECK", 1966, 1940, 1))
        eq("the re-check set was every landing behind the frontier", sorted(int(k) for k in rec3["rechecks"]), [1966, 2128])
        ok("the strip test passed before the re-checks", rec3["strip_passed"])
        # an interrupted attempt counts as neither
        fr3 = F.Frontier(lengths, session=1)
        _trigger(fr3, 300)
        calls = {"n": 0}

        def guard() -> None:
            calls["n"] += 1
            if calls["n"] > 3:
                raise V.CapStop("wall cap of phase train reached", valid=True)

        e = raises("the cap propagates", V.CapStop, lambda: PR.run_attempt(frontier=fr3, snapshot=ST2.G2StubEnvBuilder.snapshot_of(model), episodes_before=0, **dict(kw, guard=guard)))
        ok("a valid end", e.valid)
        eq("recorded as INTERRUPTED: no counts, the spacing unchanged", (fr3.attempts[-1]["result"], fr3.line_failed, fr3.pointer, fr3.since_failed), ("INTERRUPTED", {}, 2300, 8))
        ok("the training arena is unpaused and settled after the interruption", not train_arena.paused and train_arena.settled())


# =====================================================================================================================================
# checkpoints, the real SB3 round trip
# =====================================================================================================================================


@test
def checkpoints_pin_members_and_carry_the_g3_identity_and_spacing() -> None:
    lengths = {"T_clear": 2326, "T_t": 2315}
    with tmpdir() as d:
        fr = F.Frontier(lengths, session=1)
        m = ST2.G2StubModel(None, n_steps=4, b0=2200)
        TR.save_checkpoint(m, fr, d / "training", 0, "initial", session=1, tape_table_sha256="ab" * 32)
        cd = d / "training" / "checkpoints" / "ckpt_000000000"
        ok("three files", all((cd / n).is_file() for n in ("model.zip", "curriculum_state.json", "checkpoint.json")))
        meta = A.read_json(cd / "checkpoint.json")
        eq("pins hold", (meta["model_zip_sha256"], meta["members_sha256"], meta["curriculum_state_sha256"]),
           (RS.sha256_file(cd / "model.zip"), RS.zip_member_digests(cd / "model.zip"), RS.sha256_file(cd / "curriculum_state.json")))
        eq("the checkpoint record carries the g3 identity and the spacing", (meta["gate"], meta["frontier_rule"], meta["line_contract_sha256"], meta["spacing"]), ("m9_g3", "m9_g3_frontier_v1", G.line_contract_digest(), {"f": 0, "need": 0, "have": 0, "ok": True}))
        cs = A.read_json(cd / "curriculum_state.json")
        eq("the curriculum state carries the pointer, the g3 line contract, the frontier rule and the tape digest", (cs["pointer"], cs["line_contract_sha256"], cs["frontier_rule"], cs["tape_table_sha256"], cs["session"]), (2300, G.line_contract_digest(), "m9_g3_frontier_v1", "ab" * 32, 1))
        ok("the carried state is inside with the spacing counter", cs["carried"]["pointer"] == 2300 and cs["carried"]["since_failed"] == 0 and "line_failed" in cs["carried"] and "stalled" not in cs["carried"])
        ok("a resume compat check accepts the g3 state", RS.check_resume_compat(cs, line_contract_sha256=G.line_contract_digest(), executable_sha256="e", saved_executable="e", ppo=G.PPO) == [])
        ok("a resume compat check refuses the g2 line contract", RS.check_resume_compat(cs, line_contract_sha256=G2.line_contract_digest(), executable_sha256="e", saved_executable="e", ppo=G.PPO))
        raises("a checkpoint directory is never overwritten", FileExistsError, lambda: TR.save_checkpoint(m, fr, d / "training", 0, "initial", session=1, tape_table_sha256=None))
        fin = TR.save_checkpoint(m, fr, d / "training", 123, "final", session=1, tape_table_sha256=None)
        eq("final", fin["checkpoint"], "final")


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
        return unflatten(keyed_obs(f"zero|{self.t}") * 0.1)

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
def frozen_policy_keyed_on_g3_keys_and_sb3_round_trip() -> None:
    import torch
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv

    import m7n_policy as mp

    torch.set_num_threads(1)
    sd = fixed_state()
    with tmpdir() as d:
        meta = PO.save_snapshot(sd, d / "snap.pth")
        pol = PO.FrozenPolicy.from_file("t", d / "snap.pth", meta["sha256"])
        obs = keyed_obs("o1")
        key = G.probe_action_key(2300, 1, "strip", 0, 2300)
        eq("sampling is a pure function of (weights, observation, key) on g3 keys", pol.sample_word(obs, key), PO.FrozenPolicy("t2", sd, meta["sha256"]).sample_word(obs, key))
        ok("g3 and g2 keys give (over many keys) different draws", [pol.sample_word(obs, G.probe_action_key(2300, 1, "strip", k, 2300)) for k in range(40)] != [pol.sample_word(obs, G2.probe_action_key(2300, 1, "strip", k, 2300)) for k in range(40)])
        # the real SB3 round trip through the unchanged g2 resume machinery
        env_a = DummyVecEnv([lambda: ZeroEnv()])
        a = mp.make_model(env_a, seed=0, n_steps=32, batch_size=32, n_epochs=2, learning_rate=3e-4, gamma=0.999, gae_lambda=0.995, clip_range=0.2, ent_coef=0.01, vf_coef=0.5, max_grad_norm=0.5)
        a.learn(total_timesteps=32)
        a.save(str(d / "m.zip"))
        saved = RS.saved_counters(d / "m.zip")
        bb = PPO.load(str(d / "m.zip"), env=DummyVecEnv([lambda: ZeroEnv()]), device="cpu")
        eq("weights and Adam moments bit-equal after the round trip", RS.tensors_equal(RS.model_state(a), RS.model_state(bb)), [])
        eq("continuity assertions pass", RS.assert_continuity(bb, saved)["ok"], True)
        a._last_obs = None
        a.set_random_seed(7)
        a.learn(total_timesteps=32, reset_num_timesteps=False)
        bb.set_random_seed(7)
        bb.learn(total_timesteps=32, reset_num_timesteps=False)
        eq("the update after the reload equals the update without it", RS.tensors_equal(RS.model_state(a), RS.model_state(bb)), [])
        env4 = DummyVecEnv([lambda: ZeroEnv() for _ in range(4)])
        m4 = mp.make_model(env4, seed=0, n_steps=1280, batch_size=512, n_epochs=10)
        m4.save(str(d / "m4.zip"))
        r4 = TR.resume_ppo(d / "m4.zip", DummyVecEnv([lambda: ZeroEnv() for _ in range(4)]), 4, 2)
        eq("resumed with the session seed", (r4.num_timesteps, r4.resumed_seed), (0, 1002))


@test
def fresh_policy_initialisation_equals_g1s_untrained_checkpoint() -> None:
    """Reported, never deciding (stop review 3.2): the fresh PPO's untrained weights equal g1's ckpt_000000000 policy tensors (and so g2-s1's)."""
    import torch
    from stable_baselines3.common.vec_env import DummyVecEnv

    g1_zip = REPO / "runs" / "m9_g1" / "training" / "checkpoints" / "ckpt_000000000" / "model.zip"
    if not g1_zip.is_file():
        return
    torch.set_num_threads(1)
    m = TR.make_fresh_ppo(DummyVecEnv([lambda: ZeroEnv() for _ in range(4)]), 4)
    with zipfile.ZipFile(g1_zip) as z:
        raw = z.read("policy.pth")
    sd = torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True)
    eq("same tensors as g1's untrained checkpoint", RS.tensors_equal(PO.state_dict_of(m), sd), [])
    ok("reported: policy.pth member sha256 of g1's untrained model is eb592c88...", hashlib.sha256(raw).hexdigest().startswith("eb592c887fc66aab"))


# =====================================================================================================================================
# the engine on the synthetic world
# =====================================================================================================================================


@test
def synthetic_session_reuses_the_tape_runs_every_phase_and_verify_run_agrees() -> None:
    with tmpdir() as d:
        sess, out, b, tape = run_small(d)
        eq("phases", sess.phases, {"open": True, "p1": True, "p2": True, "t0": True, "train": True, "audit": True, "verify": True})
        ok(f"a registered outcome ({out['outcome']}: {out['reasons']})", out["outcome"] in ("PASS", "INCONCLUSIVE", "NULL"))
        ok("at least one attempt ran and the pointer moved", sess.frontier is not None and len(sess.frontier.attempts) >= 1 and sess.frontier.pointer < 2300)
        root = d / "run"
        for rel in ("input/tape_baseline.json", "t0/drift.jsonl", "training/episodes.jsonl", "training/rollouts.jsonl", "training/attempts.jsonl", "training/probes.jsonl", "training/moves.jsonl",
                    "training/windows.jsonl", "training/withdrawn.jsonl", "audit/episodes.jsonl", "verification/replays.jsonl", "session/final_state.json", "session/rule.json", "session/line.json",
                    "session/open.json", "session/t0.json", "training/checkpoints/final/curriculum_state.json"):
            ok(f"{rel} exists", (root / rel).is_file())
        ok("no tape was measured", not (root / "t0" / "episodes.jsonl").exists() and not (root / "t0" / "tape_table.json").exists() and not (root / "session" / "tape_baseline.json").exists())
        opn = A.read_json(root / "session" / "open.json")
        eq("the open verified the reused table by digest", (opn["tape_reuse"]["file_sha256"], opn["tape_reuse"]["content_sha256"], opn["tape_reuse"]["pinned"]), (tape["file_sha256"], tape["content_sha256"], True))
        t0 = A.read_json(root / "session" / "t0.json")
        eq("T0 is the drift check: five episodes, no problem, no measurement", (t0["ok"], t0["reused"], t0["measured"], t0["drift"]["episodes"], t0["drift"]["problems"]), (True, True, False, 5, []))
        ok("the drift rows compared the native action digests with the source records", all(r["source_native_action_digest"] == r["native_action_digest"] for r in t0["drift"]["rows"]))
        vr = RPT.verify_run(root)
        ok(f"verify-run ok: {vr['problems'][:3]}", vr["ok"])
        ok("the frontier history rebuilt from the records equals the log", vr["frontier_replay"]["equal_to_log"] and vr["frontier_replay"]["attempts"] == len(sess.frontier.attempts))
        aud = A.audit_tree(root, skip_dirs=("workers", "vw", "input"))
        ok(f"metadata audit {aud['failures'][:2]}", aud["ok"] and aud["files"] > 20)
        fs = A.read_json(root / "session" / "final_state.json")
        eq("the final state pins the saved files, the reused tape among them", (fs["model_zip"]["sha256"], fs["tape_baseline"]["sha256"], fs["curriculum_state"]["sha256"], fs["gate"], fs["frontier_rule"]),
           (RS.sha256_file(root / "training" / "checkpoints" / "final" / "model.zip"), tape["file_sha256"], RS.sha256_file(root / "training" / "checkpoints" / "final" / "curriculum_state.json"), "m9_g3", "m9_g3_frontier_v1"))
        at = A.read_jsonl(root / "training" / "attempts.jsonl")
        ok("every attempt recorded the pause and the spacing", all(len(a["parked_slots"]) == 4 and len(a["probe_slots"]) == 6 and not set(a["parked_slots"]) & set(a["probe_slots"]) and "spacing" in a for a in at))
        ok("audit sticky labels are the reused tape's family", all(r["label"].startswith("m9|g2|reach|") for r in A.read_jsonl(root / "audit" / "episodes.jsonl") if r["eval_kind"] == "audit_sticky"))
        rule = A.read_json(root / "session" / "rule.json")
        eq("the rule record carries the g3 rule and the frontier readings", (rule["rule"], "attempts_per_pointer" in rule["frontier"], rule["line"]["outcome"]), ("m9_g3_s1_rule_v1", True, A.read_json(root / "session" / "line.json")["outcome"]))
        ok("the line never ends on s1", rule["line"]["outcome"] == "CONTINUE" and rule["line"]["s2_permitted"])
        rep = RPT.full_report(root)
        for k in ("rule", "audit", "training", "moves", "attempts", "attempt_results", "attempt_yield", "replenishment_schedule", "windows", "deferred_triggers", "trigger_to_test_gap",
                  "per_landing_against_tape", "pointer_over_time", "throughput_by_pointer", "handover_diagnostic", "post_target8_share", "checkpoint_digests", "tape_baseline"):
            ok(f"report has {k}", k in rep)


@test
def synthetic_session_is_a_pure_function_of_its_configuration() -> None:
    with tmpdir() as d1, tmpdir() as d2:
        s1, o1, _, _ = run_small(d1)
        s2, o2, _, _ = run_small(d2)
        rels = ("training/episodes.jsonl", "training/attempts.jsonl", "training/probes.jsonl", "training/moves.jsonl", "training/windows.jsonl", "t0/drift.jsonl", "audit/episodes.jsonl", "session/rule.json")
        for rel in rels:
            a = strip_volatile(A.read_jsonl(d1 / "run" / rel)) if rel.endswith(".jsonl") else strip_volatile(A.read_json(d1 / "run" / rel))
            b = strip_volatile(A.read_jsonl(d2 / "run" / rel)) if rel.endswith(".jsonl") else strip_volatile(A.read_json(d2 / "run" / rel))
            eq(f"{rel} equal", a, b)
        eq("outcomes equal", (o1["outcome"], o1["D"], o1["R"]), (o2["outcome"], o2["D"], o2["R"]))


@test
def synthetic_session_outcomes_and_stops() -> None:
    with tmpdir() as d:
        tape = synthetic_tape(d)
        sess, out, _b, _ = run_small(d / "a", tape=tape, inject={"acquire_fail_jobs": list(range(2, 60))})
        eq("too many lifecycle failures: INCOMPLETE", out["outcome"], "INCOMPLETE")
        sess, out, _b, _ = run_small(d / "b", tape=tape, inject={"mismatch_job": 3, "mismatch_tick": 30})
        eq("INVALID on an integrity failure", out["outcome"], "INVALID")
        sess, out, _b, _ = run_small(d / "c", tape=tape, env_over={"provenance_violations": lambda: ["a write under a protected root"]})
        eq("a write-guard violation is INVALID", out["outcome"], "INVALID")
        sess, out, _b, _ = run_small(d / "d", tape=tape, cfg_over={"global_cap_s": 2.0})
        eq("the hard cap is INCOMPLETE", out["outcome"], "INCOMPLETE")
        sess, out, _b, _ = run_small(d / "e", tape=tape)
        ok("the training wall cap is a valid end", sess.train_stop["valid_end"] and "wall cap" in sess.train_stop["reason"])

        class Breach:
            breach = "memory cap: process tree private 9999 MB > 9216 MB"
            last = None

        sess, out, _b, _ = run_small(d / "f", tape=tape, env_over={"sampler": Breach()})
        eq("memory breach: INCOMPLETE at once", (out["outcome"], out["stop"]["phase"]), ("INCOMPLETE", "open"))
        # the reused tape: a wrong registered digest is INVALID at the open with nothing trained
        sess, out, _b, _ = run_small(d / "g", tape=dict(tape, file_sha256="0" * 64))
        eq("a tape digest mismatch is INVALID at the open", (out["outcome"], out["stop"]["phase"]), ("INVALID", "open"))
        ok("nothing trained", not (d / "g" / "run" / "training").exists())
        sess, out, _b, _ = run_small(d / "h", tape=dict(tape, content_sha256="0" * 64))
        eq("a content digest mismatch is INVALID at the open", (out["outcome"], out["stop"]["phase"]), ("INVALID", "open"))
        # a table whose recorded outcome differs from what the world reproduces: the drift check is INVALID (the table is re-digested so the open accepts it)
        tb = json.loads(Path(tape["path"]).read_text(encoding="utf-8"))
        oc = tb["landings"]["2128"]["outcomes"]
        oc["0"] = "f" if oc["0"] != "f" else "h"
        tb["sha256"] = TP.table_digest(tb)
        p = d / "tape_drifted" / "tape_baseline.json"
        A.write_json(p, A.stamp({k: v for k, v in tb.items() if k not in ("task", "created_utc")}), overwrite=False)
        drifted = dict(tape, path=str(p), file_sha256=RS.sha256_file(p), content_sha256=tb["sha256"])
        sess, out, _b, _ = run_small(d / "i", tape=drifted)
        eq("a tape drift is INVALID at T0 with nothing trained", (out["outcome"], out["stop"]["phase"]), ("INVALID", "t0"))
        ok("the drift record names the key", "key 0" in json.dumps(A.read_json(d / "i" / "run" / "session" / "t0.json")["drift"]["problems"]) and not (d / "i" / "run" / "training").exists())
        # a session without a tape is INVALID at the open
        sess, out, _b, _ = run_small(d / "j", tape=tape, cfg_over={"tape_reuse": None})
        eq("no tape: INVALID at the open", (out["outcome"], out["stop"]["phase"]), ("INVALID", "open"))


@test
def synthetic_resumed_session_carries_the_spacing_and_the_line_never_ends_on_attempts() -> None:
    with tmpdir() as d:
        tape = synthetic_tape(d)
        # the synthetic learner starts competent from 2,120 on and forgets the cold start at 1,966 once competent below 1,920: s1 ends INCONCLUSIVE with blocked attempts
        s1, o1, b1, _ = run_small(d / "s1", tape=tape, builder_over={"b0": 2120, "forget_landing": 1966, "forget_when_b_below": 1920})
        eq("s1 is INCONCLUSIVE", (o1["outcome"], o1["D"]), ("INCONCLUSIVE", 2128))
        ok("s1 permits s2", o1["line"]["s2_permitted"] and o1["line"]["outcome"] == "CONTINUE")
        fs = A.read_json(d / "s1" / "run" / "session" / "final_state.json")
        cs1 = A.read_json(d / "s1" / "run" / "training" / "checkpoints" / "final" / "curriculum_state.json")
        expect = {"model_zip": fs["model_zip"]["sha256"], "curriculum_state": fs["curriculum_state"]["sha256"], "tape_baseline": fs["tape_baseline"]["sha256"]}
        prev = [{"k": 1, "outcome": o1["outcome"], "D": o1["D"], "R": o1["R"], "train_fraction": 1.0}]
        b2 = SmallBuilder(d / "s2" / "run", model_need=40, b0=2120, forget_landing=1966, forget_when_b_below=1920)
        cfg2 = small_cfg(d / "s2" / "run", tape, session=2, resume={"final_state": fs, "expect": expect, "previous_sessions": prev}, tape_reuse=None)
        s2 = RUN3.G3Session(cfg2, b2.env(), hooks_for(b2))
        o2 = s2.run()
        eq("s2 phases (the drift check ran again on the carried table)", s2.phases, {"open": True, "p1": True, "p2": True, "t0": True, "train": True, "audit": True, "verify": True})
        opn = A.read_json(d / "s2" / "run" / "session" / "open.json")
        eq("the carried pointer, f and the spacing counter were restored", (opn["resume"]["carried_state"]["pointer"], opn["resume"]["carried_state"]["line_failed"], opn["resume"]["carried_state"]["since_failed"]),
           (s1.frontier.pointer, cs1["carried"]["line_failed"], cs1["carried"]["since_failed"]))
        saved = ST2.G2StubModel.load(d / "s1" / "run" / "training" / "checkpoints" / "final" / "model.zip").state_dict()
        loaded = ST2.G2StubModel.load(d / "s2" / "run" / "input" / "model.zip").state_dict()
        eq("the stub s2 loaded s1's saved model bit-exactly", loaded, saved)
        ts = A.read_json(d / "s2" / "run" / "session" / "training_summary.json")
        ok("num_timesteps continued from the saved count; the session seed recorded", ts["stop"]["start_timesteps"] == saved["num_timesteps"] and ts["stop"]["num_timesteps"] > saved["num_timesteps"] and ts["resumed_seed"] == 1002)
        t0rec = A.read_json(d / "s2" / "run" / "session" / "t0.json")
        eq("the tape baseline is the carried one, read by digest; the drift check ran", (t0rec["tape_baseline_sha256"], t0rec["drift"]["episodes"]), (tape["content_sha256"], 5))
        at1 = A.read_jsonl(d / "s1" / "run" / "training" / "attempts.jsonl")
        at2 = A.read_jsonl(d / "s2" / "run" / "training" / "attempts.jsonl")
        # the short synthetic window does not reach the forgotten landing (the production-count e2e does): the carry is checked on whatever s1 left
        p_carried = int(cs1["carried"]["pointer"])
        first2 = [a for a in at2 if int(a["pointer"]) == p_carried]
        f1 = int(cs1["carried"]["line_failed"].get(str(p_carried), 0))
        ok("s2's first attempt at the carried pointer continues the line index (a = f + 1) and f", not first2 or (first2[0]["a"] == f1 + 1 and first2[0]["spacing"]["f"] == f1))
        ok("every attempt in s2 ran at or past its need and the need follows the schedule", all(a["spacing"]["have"] >= a["spacing"]["need"] and a["spacing"]["need"] == G.spacing_need(a["spacing"]["f"]) for a in at2))
        ok("s2 continued the attempt numbering and the episode numbering", (not at2 or at2[0]["n"] == len(at1) + 1) and int(A.read_jsonl(d / "s2" / "run" / "training" / "episodes.jsonl")[0]["start"]["episode"]) >= cs1["carried"]["next_episode"])
        ln = A.read_json(d / "s2" / "run" / "session" / "line.json")
        eq("the line rule saw both sessions and continued (k = 2, D_2 = 2128)", (ln["k"], ln["outcome"]), (2, "CONTINUE"))
        ok("no STALLED anywhere", not s2.frontier.stalled and "stalled" not in json.dumps(A.read_json(d / "s2" / "run" / "session" / "rule.json")["line"]))
        vr = RPT.verify_run(d / "s2" / "run")
        ok(f"verify-run ok on the resumed session: {vr['problems'][:3]}", vr["ok"])
        # tampering: a wrong expected digest is refused at the open (INVALID, zero ticks); a g2 curriculum state is refused
        b3 = SmallBuilder(d / "s3" / "run", model_need=40, b0=2120)
        cfg3 = small_cfg(d / "s3" / "run", tape, session=2, resume={"final_state": fs, "expect": dict(expect, model_zip="0" * 64), "previous_sessions": prev}, tape_reuse=None)
        o3 = RUN3.G3Session(cfg3, b3.env(), hooks_for(b3)).run()
        eq("refused as INVALID at the open", (o3["outcome"], o3["stop"]["phase"]), ("INVALID", "open"))
        ok("nothing trained", not (d / "s3" / "run" / "training").exists())


@test
def verify_run_detects_tampering() -> None:
    with tmpdir() as d:
        sess, out, _b, _ = run_small(d)
        root = d / "run"
        ok("clean first", RPT.verify_run(root)["ok"])
        p = root / "training" / "moves.jsonl"
        rows = A.read_jsonl(p)
        rows.append(dict(rows[-1], **{"from": rows[-1]["to"], "to": rows[-1]["to"] - 20}))
        p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        ok("an unearned move is caught", not RPT.verify_run(root)["ok"])
        p.write_text("".join(json.dumps(r) + "\n" for r in rows[:-1]), encoding="utf-8")
        ok("restored", RPT.verify_run(root)["ok"])
        p = root / "training" / "probes.jsonl"
        rows = A.read_jsonl(p)
        m = bytearray(bytes.fromhex(rows[0]["sticky_mask_hex"]))
        if m:
            m[0] ^= 1
            rows[0]["sticky_mask_hex"] = bytes(m).hex()
            p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            ok("a tampered probe mask is caught", not RPT.verify_run(root)["ok"])
        p = root / "input" / "tape_baseline.json"
        tb = A.read_json(p)
        tb["landings"]["2128"]["B"] = 99
        A.write_json(p, tb)
        ok("a tampered reused tape table is caught", not RPT.verify_run(root)["ok"])
        cp = root / "training" / "checkpoints" / "final" / "checkpoint.json"
        meta = A.read_json(cp)
        meta["members_sha256"]["policy.pth"] = "0" * 64
        A.write_json(cp, meta)
        ok("a tampered member pin is caught", not RPT.verify_run(root)["ok"])


# =====================================================================================================================================
# guards, identity, the protected trees, metadata
# =====================================================================================================================================


def _g3_sources(include_tests: bool = False) -> List[Path]:
    return [p for p in sorted(RL.glob("m9_g3_*.py")) if include_tests or p.name != "m9_g3_tests.py"]


@test
def source_guards() -> None:
    # the fragments are assembled so that this file does not itself contain them (g1's source guard scans every rl/m9_*.py file, this one included)
    forbidden = tuple(a + b for a, b in (("rl/", "fixtures"), ("fixtures/", "m7g"), ("tas_", "input"), ("mario_", "743"), (".bt", "ti"), ("btti_", "replay"), ("m7g_", "capture"),
                                         ("m7g_", "fixture"), ("crossing_", "fixture"), ("replay/", "recordings")))
    rng = tuple(a + b for a, b in (("SSB64_", "RNG"), ("rng_", "seed"), ("get_", "rng"), ("set_", "rng"), ("seed_", "rng"), ("native_", "rng"), ("os", "Rand"), ("syUtils", "Rand")))
    for p in _g3_sources(include_tests=True):
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
    for f in ("m9_g3_train.py", "m9_g3_probe.py", "m9_g3_run.py", "m9_g3_frontier.py"):
        tree = ast.parse((RL / f).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                ok(f"{f}: no imitation vocabulary in {node.name}", not any(b in node.name.lower() for b in bad))
    for f in ("m9_g3_probe.py",):
        src = (RL / f).read_text(encoding="utf-8")
        for frag in ("torch.optim", ".backward(", "optimizer.step", "zero_grad", ".learn(", "PPO("):
            ok(f"{f}: no training call {frag}", frag not in src)
    # the g3 frontier carries no HELD / STALLED logic
    fsrc = (RL / "m9_g3_frontier.py").read_text(encoding="utf-8")
    ok("no attempt bound, no held_trigger event and no stalled assignment in the g3 frontier", "ATTEMPTS_PER_SESSION" not in fsrc and "ATTEMPTS_PER_LINE" not in fsrc and '"held_trigger"' not in fsrc
       and "self.stalled = True" not in fsrc and "self.stalled, self.stalled_pointer = True" not in fsrc)
    # the authorised edit of rl/m9_eval_tests.py is at its pinned digest and spells no forbidden literal
    import m9_g3_session as S3

    for rel, pin in S3.AUTHORISED_TRACKED_EDITS.items():
        src = (REPO / rel).read_text(encoding="utf-8")
        eq(f"{rel} is at its pinned post-edit digest", S3.sha256_file(REPO / rel), pin["sha256_after"])
        for frag in forbidden + rng:
            ok(f"{rel} does not mention {frag}", frag not in src.replace("\\", "/") or frag == "replay/" + "recordings")


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
def tracked_files_are_unchanged_except_the_authorised_edit_and_only_new_files_exist() -> None:
    import m8_rd_session as ses1
    import m9_g3_session as S3

    probs, info = S3.git_problems()
    eq(f"git state: {probs}", probs, [])
    committed = "rl/m9_eval_tests.py" not in info["tracked_changes"] and S3.sha256_file(REPO / "rl/m9_eval_tests.py") == S3.AUTHORISED_TRACKED_EDITS["rl/m9_eval_tests.py"]["sha256_after"]
    eq("the authorised edit is committed (HEAD carries it), or it is the only tracked change, at its pinned digest", {k: v["at_pinned_digest"] for k, v in info["tracked_changes"].items()}, {} if committed else {"rl/m9_eval_tests.py": True})
    new = [ln[3:] for ln in ses1.git("status", "--porcelain").splitlines() if ln.startswith("??")]
    ok("every new file under rl/ or docs/ is an M9 file", all(("m9" in n or "M9" in n) for n in new if n.startswith(("rl/", "docs/"))))


@test
def identity_approval_write_guard_and_the_reused_tape() -> None:
    import m9_g3_session as S3

    roots = {p.resolve() for p in S3.write_guard_roots(1)}
    for name in ("m9_g2", "m9_g1", "m9_g1_eval", "m8_rd", "m8_rd_rd2", "m8_rd_rd3", "m8_rd_rd4"):
        ok(f"runs/{name} protected", (REPO / "runs" / name).resolve() in roots)
    ok("rl and docs protected", (REPO / "rl").resolve() in roots and (REPO / "docs").resolve() in roots)
    ok("the session's own tree is not protected", S3.run_root(1).resolve() not in roots and S3.LINE_ROOT.resolve() not in roots)
    eq("the seven protected trees", [t[0] for t in S3.TREES], ["rd1", "rd2", "rd3", "rd4", "m9_g1", "m9_g1_eval", "m9_g2_s1"])
    ok("every code file of the identity exists", all((RL / f).is_file() for f in S3.CODE_FILES))
    eq("the reused tape passes its checks", S3.tape_reuse_problems(), [])
    ident = S3.identity(1)
    for k in ("contract_sha256", "line_contract_sha256", "rules", "spacing", "line_budget", "tape_reuse", "authorised_tracked_edits", "executable_sha256", "runtime_files", "frozen_sha256", "lineages", "trees",
              "caps", "budget", "ppo", "code", "docs_sha256", "git_head", "d_records", "g2_line_contract_sha256"):
        ok(f"identity has {k}", k in ident)
    eq("the identity's rule digests", (ident["rules"]["s1_sha256"], ident["rules"]["line_sha256"], ident["spacing"]["need"]["5"]), (R.s1_rule_digest(), R.line_rule_digest(), 320))
    ok("the identity pins the authorised edit", ident["code"]["rl/m9_eval_tests.py"] == S3.AUTHORISED_TRACKED_EDITS["rl/m9_eval_tests.py"]["sha256_after"])
    with tmpdir() as d:
        okk, why = S3.approval_status(1, d / "none.json", ident)
        ok("a missing approval refuses", not okk and "no approval" in why)
        A.write_json(d / "a.json", A.stamp(dict(ident, approval="APPROVED: test", source_snapshot={})))
        okk, why = S3.approval_status(1, d / "a.json", ident)
        ok(f"a matching record is approved ({why})", okk)
        A.write_json(d / "b.json", A.stamp(dict(ident, approval="APPROVED: test", contract_sha256="0" * 64)))
        okk, why = S3.approval_status(1, d / "b.json", ident)
        ok("a tampered identity is refused", not okk and "contract_sha256" in why)
    bp = RUN3.budget_projection()
    ok("the budget fits with no trimming", bp["fits_global_cap_pessimistic"])


@test
def the_protected_trees_equal_their_increments_and_the_pins_hold() -> None:
    import m9_g3_session as S3
    import m9_session as G1

    st = S3.trees_state(1)
    eq("the seven trees equal their D: increments byte for byte", {k: v["ok"] for k, v in st.items() if k != "ok"}, {"rd1": True, "rd2": True, "rd3": True, "rd4": True, "m9_g1": True, "m9_g1_eval": True, "m9_g2_s1": True})
    eq("the g2-s1 tree's registered facts", (st["m9_g2_s1"]["files"], st["m9_g2_s1"]["bytes"], st["m9_g2_s1"]["manifest_sha256"][:16]), (9779, 988807605, "4ad2c3dc240ef1bb"))
    eq("pins (executable, runtime files, frozen configuration) equal the archive's", G1.pins_problems(), [])


@test
def metadata_is_enforced_by_the_writers() -> None:
    with tmpdir() as d:
        raises("a record without the task block is refused", A.ArtifactError, lambda: A.write_json(d / "x.json", {"created_utc": A.utc(), "a": 1}))
        raises("a record without created_utc is refused", A.ArtifactError, lambda: A.write_json(d / "y.json", {"task": dict(G.TASK), "a": 1}))
        raises("a jsonl row without the task block is refused", A.ArtifactError, lambda: A.append_jsonl(d / "z.jsonl", {"created_utc": A.utc()}))
        ok("nothing written", not (d / "x.json").exists() and not (d / "y.json").exists() and not (d / "z.jsonl").exists())
        A.write_json(d / "ok.json", A.stamp({"a": 1}))
        eq("the stamp carries the registered task block", A.read_json(d / "ok.json")["task"], {"id": "ssb64_us_mario_btt_v1", "character": "mario", "stage": "btt_mario"})
        aud = A.audit_tree(d)
        ok("audit clean", aud["ok"] and aud["files"] == 1)
        (d / "bad.json").write_text("{\"a\": 1}", encoding="utf-8")
        ok("the audit finds an unstamped file", not A.audit_tree(d)["ok"])


@test
def snapshot_tool_roundtrip() -> None:
    with tmpdir() as d:
        dest = d / "snap"
        r = subprocess.run([sys.executable, "-B", str(RL / "m9_g3_snapshot.py"), "snapshot", "--dest", str(dest)], capture_output=True, text=True, cwd=str(REPO))
        eq(f"snapshot exit code ({r.stdout[-300:]} {r.stderr[-300:]})", r.returncode, 0)
        rec = json.loads((dest / "snapshot.json").read_text(encoding="utf-8"))
        eq("PASS", (rec["result"], rec["problems"], rec["identity_code_mismatch"], rec["identity_docs_mismatch"], rec["authorised_edit_mismatch"]), ("PASS", [], [], [], []))
        A.check({k: rec[k] for k in ("task", "created_utc")})
        paths = {f["path"] for f in rec["files"]}
        for f in ("rl/m9_g3_run.py", "rl/m9_g3_probe.py", "rl/m9_g3_tests.py", "rl/m9_g2_run.py", "rl/m9_run.py", "rl/m9_worker.py", "rl/m8_rd_worker.py", "rl/m7n_obs.py", "rl/m9_eval_tests.py",
                  "docs/rl_m9_g2_stop_review_2026-10-06.md"):
            ok(f"snapshot has {f}", f in paths)
        r = subprocess.run([sys.executable, "-B", str(RL / "m9_g3_snapshot.py"), "verify", "--dest", str(dest)], capture_output=True, text=True, cwd=str(REPO))
        eq("verify exit code", r.returncode, 0)
        ps = subprocess.run([sys.executable, "-B", str(RL / "m9_g3_snapshot.py"), "powershell", "--dest", str(dest)], capture_output=True, text=True, cwd=str(REPO)).stdout
        ok("the independent re-hash script is generated", "Get-FileHash" in ps and str(dest) in ps)
        r = subprocess.run([sys.executable, "-B", str(RL / "m9_g3_snapshot.py"), "snapshot", "--dest", str(dest)], capture_output=True, text=True, cwd=str(REPO))
        eq("an existing snapshot is never overwritten", r.returncode, 2)


# =====================================================================================================================================
# the production-count synthetic end-to-end run: a two-session line with a reused tape baseline
# =====================================================================================================================================


def e2e() -> int:
    """A pinned tape table measured on the synthetic world at the registered counts (200 / 40 keys, every clear replayed) stands in for g2-s1's; then s1 at
    the registered counts and caps (virtual clock 1,200 native ticks/s, in-process lock-step pool, the tape reused by digest, the drift check), then s2 resumed
    from s1's saved state. The synthetic learner forgets the cold start at 1,966 once its competence is below 1,920, so the line exercises BLOCKED_BY_RECHECK
    over and over: the attempts replenish with the spacing 20, 40, 80, 160, 320, 320, ... and nothing freezes or ends the line on attempt counts."""
    t0 = time.time()
    d = Path(tempfile.mkdtemp(prefix="m9g3e2e_"))
    problems: List[str] = []

    def chk(label: str, cond: Any) -> None:
        if not cond:
            problems.append(label)

    try:
        tape = synthetic_tape(d, dict(G.TAPE_KEYS))
        chk("tape: 200 / 40 keys, pinned, every clear replayed", tape["table"]["pinned"] and {int(k): v["keys"] for k, v in tape["table"]["landings"].items()} == dict(G.TAPE_KEYS)
            and all(v["unverified"] == [] and v["inexact"] == [] for v in tape["table"]["landings"].values()))
        spec = {"path": tape["path"], "file_sha256": tape["file_sha256"], "content_sha256": tape["content_sha256"]}
        b1 = ST2.G2StubEnvBuilder(d / "s1", rate=1200.0, model_need=E2E_NEED, forget_landing=1966, forget_when_b_below=1920)
        cfg1 = RUN3.G3Config(root=d / "s1", write_artifacts=True, session=1, tape_reuse=spec, tape_source_records=Path(tape["records"]))
        s1 = RUN3.G3Session(cfg1, b1.env(), hooks_for(b1))
        o1 = s1.run()
        root1 = d / "s1"
        chk("s1: every phase ran and passed", s1.phases == {"open": True, "p1": True, "p2": True, "t0": True, "train": True, "audit": True, "verify": True})
        chk(f"s1 outcome {o1['outcome']} is a registered performance outcome", o1["outcome"] in ("PASS", "INCONCLUSIVE", "NULL"))
        chk("s1: training ended at its registered wall cap", s1.train_stop["valid_end"] and "wall cap" in str(s1.train_stop["reason"]))
        fr1 = s1.frontier
        at1 = A.read_jsonl(root1 / "training" / "attempts.jsonl")
        opn1 = A.read_json(root1 / "session" / "open.json")
        t01 = A.read_json(root1 / "session" / "t0.json")
        chk("s1: the tape was reused by digest (file and content), never measured", opn1["tape_reuse"]["file_sha256"] == spec["file_sha256"] and opn1["tape_reuse"]["content_sha256"] == spec["content_sha256"]
            and not (root1 / "t0" / "episodes.jsonl").exists() and (root1 / "input" / "tape_baseline.json").is_file())
        chk("s1: the drift check ran five keys with no problem and matched the source digests", t01["drift"]["episodes"] == 5 and t01["drift"]["problems"] == [] and all(r["source_native_action_digest"] == r["native_action_digest"] for r in t01["drift"]["rows"]))
        chk("s1: the frontier moved through several strips on passing attempts", len(fr1.moves) >= 5 and all(a["result"] == "MOVED" for a in at1 if a["new_pointer"] != a["pointer"]))
        chk("s1: every move came from a passing strip test (>= 10 clears) and passing re-checks", all(a["strip_clears"] >= 10 and all(v["passed"] for v in a["rechecks"].values()) for a in at1 if a["result"] == "MOVED"))
        chk("s1: every attempt followed a trigger (8 clears of a window)", all(a["trigger"]["clears"] >= 8 for a in at1) and len(at1) >= 1)
        chk("s1: early stopping of the strip tests", all((a["strip_clears"] + a["strip_non_clears"]) <= 20 and ((a["strip_clears"] == 10) or (a["strip_non_clears"] == 11) or a["result"] == "INTERRUPTED") for a in at1))
        chk("s1: the pause: four parked and six probe slots, disjoint, in every attempt", all(len(a["parked_slots"]) == 4 and len(a["probe_slots"]) == 6 and not set(a["parked_slots"]) & set(a["probe_slots"]) for a in at1))
        chk("s1: withdrawn starts recorded for the pause", (root1 / "training" / "withdrawn.jsonl").is_file() and len(A.read_jsonl(root1 / "training" / "withdrawn.jsonl")) >= len(at1))
        blocked1 = [a for a in at1 if a["result"] == "BLOCKED_BY_RECHECK"]
        chk("s1: a re-check blocked a move (the forgotten cold landing 1,966), the pointer unmoved", len(blocked1) >= 1 and all(a["failed_landing"] == 1966 and a["new_pointer"] == a["pointer"] for a in blocked1))
        chk("s1: the pointer never moved forward", all(m["to"] == m["from"] - 20 for m in fr1.moves) and all(fr1.moves[i + 1]["from"] == fr1.moves[i]["to"] for i in range(len(fr1.moves) - 1)))
        # the replenishment: every attempt at or past its need; the need follows the schedule; consecutive failures raise f; triggers inside the spacing were deferred
        chk("s1: every attempt ran at or past its spacing need", all(a["spacing"]["have"] >= a["spacing"]["need"] for a in at1))
        chk("s1: the need follows 20 x 2^(f-1) capped at 320", all(a["spacing"]["need"] == G.spacing_need(a["spacing"]["f"]) for a in at1))
        fails_by_ptr: Dict[int, List[Dict[str, Any]]] = {}
        for a in at1:
            if a["result"] in F.FAILED_RESULTS:
                fails_by_ptr.setdefault(int(a["pointer"]), []).append(a)
        chk("s1: consecutive failures at a pointer raise f by one each (f = 0, 1, 2, ...)", all([x["spacing"]["f"] for x in v] == list(range(len(v))) for v in fails_by_ptr.values()))
        wins1 = A.read_jsonl(root1 / "training" / "windows.jsonl")
        deferred1 = [w for w in wins1 if w["event"] == "deferred_trigger"]
        chk("s1: triggers inside a spacing were deferred (logged, no attempt, have < need)", (len(blocked1) < 2) or (len(deferred1) >= 1 and all(w["spacing"]["have"] < w["spacing"]["need"] for w in deferred1)))
        chk("s1: no HELD and no STALLED state exists", not fr1.held() and not fr1.stalled and "held" not in fr1.state() and "stalled" not in fr1.state())
        tb = A.read_json(root1 / "input" / "tape_baseline.json")
        chk("s1: the reused table is pinned at every landing with 200 / 40 keys and the bars by formula", tb["pinned"] and tb["landings"]["2128"]["keys"] == 200 and all(tb["landings"][str(l)]["keys"] == 40 for l in (1966, 1694, 1473, 1369, 1248))
            and all(v["B"] == G.bar_from_counts(v["clears_verified"], v["keys"]) for v in tb["landings"].values()))
        aud = o1["facts"]["audit"]
        chk("s1: the audit covered 2,128 with 20 sticky episodes on the reused tape's labels", 2128 in aud and aud[2128]["n"] == 20 and all(r["label"].startswith("m9|g2|reach|") for r in A.read_jsonl(root1 / "audit" / "episodes.jsonl") if r["eval_kind"] == "audit_sticky"))
        chk("s1: D and R recomputed by the rule equal the recorded", R.apply_s1(dict(o1["facts"], invalid=[]))["D"] == o1["D"])
        chk("s1: INCONCLUSIVE: 2,128 held, the forgotten cold landing 1,966 did not (D_1 = 2128)", o1["outcome"] == "INCONCLUSIVE" and o1["D"] == 2128)
        chk("s1 permits s2 (the line never ends on attempt counts or on s1 alone)", o1["line"]["s2_permitted"] and o1["line"]["outcome"] == "CONTINUE")
        vr1 = RPT.verify_run(root1)
        chk(f"s1 verify-run ok ({vr1['problems'][:3]})", vr1["ok"])
        aud1 = A.audit_tree(root1, skip_dirs=("workers", "vw", "input"))
        chk("s1: every record carries the task block and created_utc", aud1["ok"] and aud1["files"] > 100)
        chk("s1: full artifacts exist for the drift and the audit episodes", sum(1 for _ in (root1 / "artifacts").glob("drift_tape-*")) == 5 and sum(1 for _ in (root1 / "artifacts").glob("audit_sticky-*")) >= 40)
        fs = A.read_json(root1 / "session" / "final_state.json")
        cs1 = A.read_json(root1 / "training" / "checkpoints" / "final" / "curriculum_state.json")
        # s2: resumed, the spacing carried
        expect = {"model_zip": fs["model_zip"]["sha256"], "curriculum_state": fs["curriculum_state"]["sha256"], "tape_baseline": fs["tape_baseline"]["sha256"]}
        prev = [{"k": 1, "outcome": o1["outcome"], "D": o1["D"], "R": o1["R"], "train_fraction": o1["facts"]["train_fraction"]}]
        b2 = ST2.G2StubEnvBuilder(d / "s2", rate=1200.0, model_need=E2E_NEED, forget_landing=1966, forget_when_b_below=1920)
        cfg2 = RUN3.G3Config(root=d / "s2", write_artifacts=True, session=2, resume={"final_state": fs, "expect": expect, "previous_sessions": prev}, tape_source_records=Path(tape["records"]))
        s2 = RUN3.G3Session(cfg2, b2.env(), hooks_for(b2))
        o2 = s2.run()
        root2 = d / "s2"
        chk("s2: every phase ran and passed", s2.phases == {"open": True, "p1": True, "p2": True, "t0": True, "train": True, "audit": True, "verify": True})
        saved = ST2.G2StubModel.load(root1 / "training" / "checkpoints" / "final" / "model.zip").state_dict()
        loaded = ST2.G2StubModel.load(root2 / "input" / "model.zip").state_dict()
        opn2 = A.read_json(root2 / "session" / "open.json")
        chk("s2 resumed from s1's saved model bit-exactly with the carried pointer, f and spacing counter", loaded == saved and opn2["resume"]["carried_state"]["pointer"] == fr1.pointer
            and opn2["resume"]["carried_state"]["line_failed"] == cs1["carried"]["line_failed"] and opn2["resume"]["carried_state"]["since_failed"] == cs1["carried"]["since_failed"])
        ts2 = A.read_json(root2 / "session" / "training_summary.json")
        chk("s2: num_timesteps continued and the session seed was set", ts2["stop"]["start_timesteps"] == saved["num_timesteps"] and ts2["resumed_seed"] == 1002)
        chk("s2: the tape baseline carried by digest; the drift check ran again", A.read_json(root2 / "session" / "t0.json")["tape_baseline_sha256"] == tb["sha256"] and A.read_json(root2 / "session" / "t0.json")["drift"]["episodes"] == 5)
        at2 = A.read_jsonl(root2 / "training" / "attempts.jsonl")
        fr2 = s2.frontier
        p_blk = int(blocked1[-1]["pointer"]) if blocked1 else None
        f_carried = int(cs1["carried"]["line_failed"].get(str(p_blk), 0)) if p_blk is not None else 0
        at2_ptr = [a for a in at2 if p_blk is not None and int(a["pointer"]) == p_blk]
        chk("s2: the line attempt index and f continue at the carried pointer", bool(at2_ptr) and at2_ptr[0]["a"] == f_carried + 1 and at2_ptr[0]["spacing"]["f"] == f_carried)
        chk("s2: every attempt ran at or past its spacing need; the need follows the schedule", all(a["spacing"]["have"] >= a["spacing"]["need"] and a["spacing"]["need"] == G.spacing_need(a["spacing"]["f"]) for a in at2))
        all_at = at1 + at2
        capped = [a for a in all_at if a["spacing"]["need"] == G.SPACING_CAP]
        chk("the spacing reached the 320 cap and an attempt ran after a 320-outcome wait", len(capped) >= 1 and all(a["spacing"]["have"] >= 320 for a in capped))
        n_fail_ptr = sum(1 for a in all_at if p_blk is not None and int(a["pointer"]) == p_blk and a["result"] in F.FAILED_RESULTS)
        chk("more than six failed attempts at one pointer over the line, and the frontier is still live (g2 would have STALLED at six)", n_fail_ptr >= 6 and not fr2.stalled and not fr2.held())
        chk("s2: the line continues (k = 2, D_2 = 2128): no attempt count ends it", o2["line"]["outcome"] == "CONTINUE" and o2["line"]["s2_permitted"] and o2["line"]["k"] == 2)
        wins2 = A.read_jsonl(root2 / "training" / "windows.jsonl")
        deferred2 = [w for w in wins2 if w["event"] == "deferred_trigger"]
        chk("s2: deferred triggers inside the spacings", len(deferred2) >= 1 and all(w["spacing"]["have"] < w["spacing"]["need"] for w in deferred2))
        vr2 = RPT.verify_run(root2)
        chk(f"s2 verify-run ok ({vr2['problems'][:3]})", vr2["ok"])
        aud2 = A.audit_tree(root2, skip_dirs=("workers", "vw", "input"))
        chk("s2: metadata audit clean", aud2["ok"])
        rep2 = RPT.full_report(root2)
        chk("s2: the report carries the g3 readings", all(k in rep2 for k in ("replenishment_schedule", "trigger_to_test_gap", "attempt_yield", "deferred_triggers", "per_landing_against_tape")))
        digest = hashlib.sha256(json.dumps(strip_volatile({"s1": {k: o1[k] for k in ("outcome", "D", "R")}, "s2": {k: o2[k] for k in ("outcome", "D", "R")}, "moves1": [(m["from"], m["to"]) for m in fr1.moves],
                                                           "attempts1": [(a["pointer"], a["result"], a["spacing"]["f"], a["spacing"]["need"]) for a in at1],
                                                           "attempts2": [(a["pointer"], a["result"], a["spacing"]["f"], a["spacing"]["need"]) for a in at2], "line": o2["line"]["outcome"],
                                                           "episodes": len(A.read_jsonl(root1 / "training" / "episodes.jsonl")), "deferred": [len(deferred1), len(deferred2)]}), sort_keys=True, default=str).encode()).hexdigest()
        print(json.dumps({"e2e": "PASS" if not problems else "FAIL", "s1": {k: o1[k] for k in ("outcome", "D", "R")}, "s2": {k: o2[k] for k in ("outcome", "D", "R")}, "line": o2["line"]["outcome"],
                          "pointer_s1": fr1.pointer, "moves_s1": len(fr1.moves), "attempts_s1": {k: sum(1 for a in at1 if a["result"] == k) for k in F.RESULTS}, "attempts_s2": {k: sum(1 for a in at2 if a["result"] == k) for k in F.RESULTS},
                          "schedule": [(a["pointer"], a["spacing"]["f"], a["spacing"]["need"], a["spacing"]["have"], a["result"]) for a in all_at if a["spacing"]["f"] >= 1], "deferred": [len(deferred1), len(deferred2)],
                          "failed_at_blocked_pointer": n_fail_ptr, "training_episodes_s1": len(A.read_jsonl(root1 / "training" / "episodes.jsonl")), "verified_s1": vr1.get("verification"),
                          "digest": digest[:16], "wall_s": round(time.time() - t0, 1), "problems": problems}, default=str))
        return 0 if not problems else 1
    except Exception as exc:                                         # noqa: BLE001
        traceback.print_exc()
        print(json.dumps({"e2e": "FAIL", "error": f"{type(exc).__name__}: {exc}", "problems": problems, "wall_s": round(time.time() - t0, 1)}))
        return 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


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
    print(f"m9 g3 unit suite: {passed}/{total} passed" + (f" (failed: {', '.join(failed)})" if failed else "") + f" in {time.time() - t_all:.0f}s")
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
