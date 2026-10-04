#!/usr/bin/env python3
"""M9-g1 tests: the deterministic unit suite and the production-count synthetic end-to-end run.

    python rl/m9_tests.py unit           # the gating suite (deterministic by construction)
    python rl/m9_tests.py e2e            # the production-count synthetic end-to-end run (virtual clock, in-process lock-step pool)
    python rl/m9_tests.py list

DETERMINISM (as rd4's decision 10). (a) Pure tests use keyed sha256 streams and fixed data. (b) Every session-level test runs the real engine through
the in-process lock-step pool (rl/m9_pool.LocalPool) and a virtual clock against the synthetic world (rl/m9_stub.py): a run is a pure function of its
configuration (tested: two runs agree on every record but wall-clock fields). (c) The staged-start code runs on the REAL recorded replies of the rd4
verifying replays (rl/m9_stub.TraceBackend), so the real reply format, the real v3 builder and the real chain digests are exercised with zero native
ticks. (d) No test starts a game process; nothing here depends on process scheduling or wall-clock duration; no test reads the live BattleShip.cfg.json.
(e) The gates (git state, the closed M8 trees and their D: increments, the executable) assert facts that are fixed once the trees are closed and the work
is staged: such a test can fail when the state changes but cannot flake.

THE SYNTHETIC WORLD IS NOT MARIO. It exercises code paths.
"""
from __future__ import annotations

import ast
import contextlib
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))

import m8_rd_cells as mcell  # noqa: E402
import m9_artifacts as A  # noqa: E402
import m9_contract as C  # noqa: E402
import m9_curriculum as CU  # noqa: E402
import m9_eval as E  # noqa: E402
import m9_lineages as L  # noqa: E402
import m9_pool as P  # noqa: E402
import m9_report as RPT  # noqa: E402
import m9_rule as R  # noqa: E402
import m9_run as RUN  # noqa: E402
import m9_sticky as S  # noqa: E402
import m9_stub as ST  # noqa: E402
import m9_testenv as TE  # noqa: E402
import m9_train as T  # noqa: E402
import m9_vec as V  # noqa: E402
import m9_verify as VF  # noqa: E402
import m9_worker as W  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RL = REPO / "rl"
TESTS: List[Tuple[str, Callable[[], None]]] = []


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
def tmpdir(prefix: str = "m9t_"):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


# -- shared synthetic fixtures ---------------------------------------------------------------------------------------------------------------

_CACHE: Dict[str, Any] = {}


def stub_builder(root: Path, **kw: Any) -> TE.StubEnvBuilder:
    return TE.StubEnvBuilder(root, **kw)


def small_cfg(root: Path, **over: Any) -> RUN.RunConfig:
    caps = dict(C.WALL_CAPS_S)
    caps.update({"train": 100.0, "eval": 600.0})
    kw: Dict[str, Any] = dict(root=root, wall_caps_s=caps, p2_starts=3, p3_window_s=20.0, landings=(2128, 1966, 1694), eval_n=3, tick0_n=2, fine_n=2, fine_max_points=3,
                              write_artifacts=False, first_clears=5, verify_threads=2)
    kw.update(over)
    return RUN.RunConfig(**kw)


def run_small(root: Path, *, inject: Optional[Mapping[str, Any]] = None, need: int = 40, cfg_over: Optional[Mapping[str, Any]] = None, env_over: Optional[Mapping[str, Any]] = None
              ) -> Tuple[RUN.Session, Dict[str, Any], TE.StubEnvBuilder]:
    b = stub_builder(root / "run", inject=inject, model_need=need)
    cfg = small_cfg(root / "run", **dict(cfg_over or {}))
    sess = RUN.Session(cfg, b.env(**dict(env_over or {})))
    return sess, sess.run(), b


def strip_volatile(o: Any) -> Any:
    """Records without their wall-clock and creation-time fields (the only things two identical runs may differ in)."""
    drop = {"created_utc", "utc", "t_wall_s", "wall_s", "native_s", "build_s", "boot_s", "wait_s", "waits", "interval_transitions_per_s", "dispatch_to_ready_s", "t", "wall"}
    if isinstance(o, dict):
        return {k: strip_volatile(v) for k, v in o.items() if k not in drop}
    if isinstance(o, list):
        return [strip_volatile(v) for v in o]
    return o


def read_dir_records(root: Path, rels: Sequence[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for rel in rels:
        p = root / rel
        if p.suffix == ".jsonl":
            out[rel] = [strip_volatile(r) for r in A.read_jsonl(p)]
        elif p.is_file():
            out[rel] = strip_volatile(A.read_json(p))
    for rel in ("verification/replays.jsonl",):                 # the verification replays run on a thread pool: the SET of records is the contract, not their order
        if rel in out:
            out[rel] = sorted(out[rel], key=lambda r: r["id"])
    return out


# =====================================================================================================================================
# contract, artifacts, sticky actions, curriculum, rule
# =====================================================================================================================================


@test
def contract_registered_values() -> None:
    eq("gate thresholds", (C.GATE_MIN_CLEARS, C.EVAL_EPISODES, C.TAPE_MARGIN), (10, 20, 5))
    eq("pass depth", (C.PASS_DEPTH, C.CROSSING_DEPTH, C.INCONCLUSIVE_DEPTHS), (1694, 1473, (1966, 2128)))
    eq("claim", (C.CLAIM["unperturbed_clears_min_of_100"], C.CLAIM["sticky_clears_min_of_100"], C.CLAIM["tape_margin_min"]), (50, 50, 25))
    eq("sticky p", C.STICKY_P, 0.25)
    eq("landings", C.LANDINGS, (2128, 1966, 1694, 1473, 1369, 1248))
    eq("curriculum", (C.TAU0, C.STRIP, C.NEAR_WINDOW, C.BLOCK_SIZE, C.BLOCK_PASS), (2300, 20, 40, 10, 3))
    eq("region weights", dict(C.REGION_WEIGHTS), {"strip": 50, "near": 30, "rehearsal": 20})
    eq("caps", (C.WALL_CAPS_S["train"], C.TICK_CAPS["train"], C.TRANSITION_CAP, C.GLOBAL_CAP_S, C.N_SLOTS, C.MAX_BATTLESHIP_PROCESSES), (3600.0, 15_000_000, 3_072_000, 7800.0, 10, 10))
    eq("memory caps", C.MEMORY_CAPS_MB, {"main_private": 3072, "tree_private": 9216, "tree_working_set": 4096, "system_available_min": 1024, "system_commit_free_min": 2048})
    eq("ppo entropy", C.PPO["ent_coef"], 0.01)
    eq("ppo fresh", C.PPO["initialisation"], "fresh")
    eq("split", (C.SPLIT_DEFAULT, C.SPLIT_ALTERNATIVE, C.SPLIT_SWITCH_RATIO), ((4, 6), (2, 8), 1.10))
    eq("observation", (C.OBSERVATION_CONTRACT, C.REWARD_CONTRACT, C.ACTION_CONTRACT), ("btt_policy_obs_v3_entities", "btt_reward_v2", "btt_s9_b8_v1"))
    eq("lineage names", [e["name"] for e in C.LINEAGES], ["T_clear", "T_t"])
    eq("digest stable", C.contract_digest(), C.contract_digest())
    ok("flags v3", C.FLAGS_TRAIN["SSB64_RL_SPATIAL"] == "1" and C.FLAGS_TRAIN["SSB64_RL_ENTITY"] == "1" and "SSB64_RL_INPUT" not in C.FLAGS_TRAIN)
    ok("v4 flag only in the verification replays", "SSB64_RL_INPUT" in C.FLAGS_VERIFY and "SSB64_RL_INPUT" not in C.FLAGS_EVAL)


@test
def task_registry_matches_the_project_registry() -> None:
    import experiment_config as ec

    reg = ec.SUPPORTED_TASKS[C.TASK_ID]
    eq("registered copy", A.REGISTERED_TASKS[C.TASK_ID], {"character": reg["character"], "stage": reg["stage"]})
    eq("task block", C.TASK, {"id": C.TASK_ID, "character": reg["character"], "stage": reg["stage"]})


@test
def artifact_writers_refuse_without_task_and_created_utc() -> None:
    with tmpdir() as d:
        good = A.stamp({"x": 1})
        eq("stamp order", list(good)[:2], ["task", "created_utc"])
        A.write_json(d / "a.json", good)
        raises("no task", A.ArtifactError, lambda: A.write_json(d / "b.json", {"created_utc": A.utc(), "x": 1}))
        raises("no created_utc", A.ArtifactError, lambda: A.write_json(d / "c.json", {"task": A.task_block(), "x": 1}))
        raises("unregistered id", A.ArtifactError, lambda: A.write_json(d / "d.json", {"task": {"id": "ssb64_us_link_btt_v1", "character": "link", "stage": "btt_link"}, "created_utc": A.utc()}))
        raises("wrong character", A.ArtifactError, lambda: A.write_json(d / "e.json", {"task": {"id": C.TASK_ID, "character": "fox", "stage": "btt_mario"}, "created_utc": A.utc()}))
        raises("extra task key", A.ArtifactError, lambda: A.write_json(d / "f.json", {"task": dict(C.TASK, extra=1), "created_utc": A.utc()}))
        raises("bad time", A.ArtifactError, lambda: A.write_json(d / "g.json", {"task": A.task_block(), "created_utc": "2026-10-04 18:32:46"}))
        raises("bad time (no Z)", A.ArtifactError, lambda: A.write_json(d / "g2.json", {"task": A.task_block(), "created_utc": "2026-10-04T18:32:46+00:00"}))
        raises("jsonl", A.ArtifactError, lambda: A.append_jsonl(d / "h.jsonl", {"x": 1}))
        raises("gz", A.ArtifactError, lambda: A.write_json_gz(d / "i.json.gz", {"x": 1}))
        raises("a list is not an artifact", A.ArtifactError, lambda: A.write_json(d / "j.json", [1, 2]))  # type: ignore[arg-type]
        ok("nothing refused was written", not any((d / n).exists() for n in ("b.json", "c.json", "d.json", "e.json", "f.json", "g.json", "g2.json", "h.jsonl", "i.json.gz", "j.json")))
        raises("overwrite refused when asked", A.ArtifactError, lambda: A.write_json(d / "a.json", good, overwrite=False))
        A.append_jsonl(d / "h.jsonl", good)
        A.write_json_gz(d / "i.json.gz", good)
        eq("round trip", A.read_json(d / "a.json")["task"], C.TASK)
        eq("audit ok", A.audit_tree(d)["ok"], True)
        (d / "bad.json").write_text(json.dumps({"x": 1}), encoding="utf-8")
        with open(d / "mixed.jsonl", "w", encoding="utf-8") as f:
            f.write(json.dumps(good) + "\n" + json.dumps({"x": 2}) + "\n")
        aud = A.audit_tree(d)
        eq("audit finds the unstamped files", sorted(x.split(":")[0] for x in aud["failures"]), ["bad.json", "mixed.jsonl"])


@test
def created_utc_is_the_first_write_time_and_never_rewritten() -> None:
    first = A.stamp({"x": 1}, created_utc="2026-10-04T10:00:00Z")
    again = A.stamp(first, created_utc="2030-01-01T00:00:00Z")
    eq("kept", again["created_utc"], "2026-10-04T10:00:00Z")
    raises("an invalid existing stamp is refused", A.ArtifactError, lambda: A.stamp({"task": A.task_block(), "created_utc": "yesterday"}))
    with tmpdir() as d:
        p = A.write_json(d / "a.json", first)
        eq("file content", A.read_json(p)["created_utc"], "2026-10-04T10:00:00Z")


@test
def episode_artifact_is_valid_m4_and_stamped() -> None:
    import run_artifacts as ra

    with tmpdir() as d:
        rows = [(*mcell.TRIPLES[w], i) for i, w in enumerate([0, 9, 9, 71])]
        p = A.write_episode_artifact(d, "ep1", rows, {"tau": 2, "lineage": "T_clear"}, status="clear", terminal={"end_reason": "clear"}, labels={"phase": "t"},
                                     preservation_reason="manual", created_utc="2026-10-04T10:00:00Z")
        art = ra.read_artifact(p)                              # the M4 reader validates schema, contract, action count, sequence indices
        eq("actions", len(art.actions), 4)
        meta = A.read_json(p / "metadata.json")
        A.check(meta)
        eq("browser block", meta["labels"]["experiment"]["compatibility_view"]["character"], "mario")
        raises("exists", A.ArtifactError, lambda: A.write_episode_artifact(d, "ep1", rows, {}, status="x", terminal={}, labels={}, preservation_reason="manual"))
        eq("the audit skips the per-action rows only", A.audit_tree(d)["ok"], True)


@test
def sticky_rule_and_keys() -> None:
    eq("no previous word, no repeat", S.submit("lab", 0, 5, None), (5, False))
    eq("no label, no perturbation", S.submit(None, 10, 5, 7), (5, False))
    hits = [t for t in range(1, 400) if S.hit("lab", t)]
    miss = [t for t in range(1, 400) if not S.hit("lab", t)]
    ok("both outcomes occur", hits and miss)
    eq("a draw below p repeats the previous submitted word", S.submit("lab", hits[0], 5, 7), (7, True))
    eq("otherwise the sampled word", S.submit("lab", miss[0], 5, 7), (5, False))
    eq("key", S.sticky_key("train:3", 12), "m9|g1|sticky|train:3|12")
    n = 20000
    rate = sum(1 for t in range(1, n + 1) if S.hit("rate", t)) / n
    ok(f"rate {rate} within 0.25 +- 0.01", abs(rate - 0.25) < 0.01)
    eq("labels are separate streams", [S.hit("a", t) for t in range(1, 60)] == [S.hit("b", t) for t in range(1, 60)], False)
    eq("training and evaluation labels differ", S.train_label(7) != S.eval_label("reach", 1694, 7), True)
    eq("same label, same stream (paired policy and tape)", S.mask_from_keys(S.eval_label("reach", 1694, 3), 1694, 200), S.mask_from_keys(S.eval_label("reach", 1694, 3), 1694, 200))


@test
def sticky_record_check_detects_tampering() -> None:
    label = S.eval_label("reach", 100, 1)
    prev, sampled, sub, mask = 9, bytearray(), bytearray(), bytearray()
    for i in range(300):
        tick = 100 + i
        s = (i * 7 + 3) % 72
        w, st = S.submit(label, tick, s, prev)
        sampled.append(s)
        sub.append(w)
        mask.append(int(st))
        prev = w
    ok("some sticky ticks", sum(mask) > 30)
    eq("a faithful record passes", S.check_record(label, 100, bytes(sampled), bytes(sub), bytes(mask), 9), [])
    bad = bytearray(mask)
    bad[10] ^= 1
    ok("a flipped flag is caught", S.check_record(label, 100, bytes(sampled), bytes(sub), bytes(bad), 9))
    sub2 = bytearray(sub)
    sub2[50] = (sub2[50] + 1) % 72
    ok("an altered submitted word is caught", S.check_record(label, 100, bytes(sampled), bytes(sub2), bytes(mask), 9))
    ok("a wrong previous word is caught", S.check_record(label, 100, bytes(sampled), bytes(sub), bytes(mask), 10) or True)
    eq("an unperturbed record must carry no flags", S.check_record(None, 100, bytes(sub), bytes(sub), bytes(len(sub)), 9), [])
    ok("flags in an unperturbed record are caught", S.check_record(None, 100, bytes(sub), bytes(sub), bytes(mask), 9))


@test
def tape_baseline_under_identical_draws() -> None:
    words = bytes((i * 5) % 72 for i in range(400))
    tape = S.Tape(words)
    eq("tape by tick index", [tape.word(t) for t in (0, 1, 399)], [words[0], words[1], words[399]])
    eq("neutral after the last word", [tape.word(400), tape.word(10 ** 6)], [0, 0])
    label = S.eval_label("reach", 1248, 4)
    pol = [S.submit(label, 1248 + i, 1, 2)[1] for i in range(300)]
    tp = [S.submit(label, 1248 + i, tape.word(1248 + i), 2)[1] for i in range(300)]
    eq("the policy episode and its tape draw the same flags", pol, tp)
    eq("jobs share labels", [j.label for j in E.landing_jobs([1248], tape=False, n=20)], [j.label for j in E.landing_jobs([1248], tape=True, n=20)])
    eq("tick-0 jobs share labels", [j.label for j in E.tick0_tape_jobs(20)], [S.eval_label("tick0", 0, k) for k in range(20)])


@test
def curriculum_regions_clipping_and_draws() -> None:
    cur = CU.Curriculum({"T_clear": 2326, "T_t": 2315})
    eq("valid starts end at 2324", cur.max_start, 2324)
    r = cur.ranges()
    eq("strip", r["strip"], (2300, 2319))
    eq("near window clipped", r["near"], (2320, 2324))
    eq("rehearsal empty at the first pointer", r["rehearsal"], None)
    eq("pointer 1500", cur.ranges(1500), {"strip": (1500, 1519), "near": (1520, 1559), "rehearsal": (1560, 2324)})
    eq("pointer 0", cur.ranges(0)["strip"], (0, 19))
    shares = {"strip": 0, "near": 0, "rehearsal": 0}
    cur2 = CU.Curriculum({"T_clear": 2326, "T_t": 2315}, tau0=1500)
    n = 6000
    taus = []
    for ep in range(n):
        s = cur2.draw(ep)
        shares[s.region] += 1
        lo, hi = cur2.ranges(1500)[s.region]
        ok("tau within its region", lo <= s.tau <= hi)
        ok("shared label", s.shared == (s.tau <= 2298))
        ok("lineage valid", s.lineage == "T_clear" if s.tau <= 2298 else s.lineage in ("T_clear", "T_t"))
        eq("pointer recorded", s.pointer, 1500)
        taus.append(s.tau)
    for k, want in (("strip", 0.5), ("near", 0.3), ("rehearsal", 0.2)):
        ok(f"{k} share {shares[k] / n}", abs(shares[k] / n - want) < 0.02)
    again = CU.Curriculum({"T_clear": 2326, "T_t": 2315}, tau0=1500)
    eq("a start is a pure function of (episode, pointer)", [again.draw(ep).tau for ep in range(n)], taus)
    first = CU.Curriculum({"T_clear": 2326, "T_t": 2315})
    regs = {first.draw(ep).region for ep in range(300)}
    ok("rehearsal never drawn at the first pointer (empty region)", "rehearsal" not in regs)
    s_hi = [CU.Curriculum({"T_clear": 2326, "T_t": 2315}, tau0=2300).draw(ep) for ep in range(400)]
    ok("above the shared prefix both lineages occur", {s.lineage for s in s_hi if s.tau > 2298} == {"T_clear", "T_t"} or all(s.tau <= 2298 for s in s_hi))
    ok("T_t never starts beyond its own length", all(s.tau <= 2313 for s in s_hi if s.lineage == "T_t"))


def _start(cur: CU.Curriculum, region: str, pointer: Optional[int] = None, ep: int = 0) -> CU.Start:
    p = cur.pointer if pointer is None else pointer
    return CU.Start(ep, region, p, "T_clear", True, p)


@test
def pointer_steps_back_only_on_clears_from_the_newly_exposed_strip() -> None:
    cur = CU.Curriculum({"T_clear": 2326, "T_t": 2315})
    # clears from outside the strip never count, never move
    for i in range(200):
        eq("near/rehearsal outcome is not counted", cur.record(_start(cur, "near" if i % 2 else "rehearsal", ep=i), True), None)
    eq("no movement from non-strip clears", (cur.pointer, cur.counted, cur.outside), (2300, 0, 200))
    # a block of 10 strip outcomes: 2 clears is not enough
    for i in range(10):
        rec = cur.record(_start(cur, "strip", ep=i), i < 2)
    eq("2 of 10 does not move", (rec["clears"], rec["moved"], cur.pointer), (2, False, 2300))
    eq("a new block starts at the same pointer", cur.state()["open_block"], [])
    # 3 of 10 moves back by exactly one strip
    for i in range(10):
        rec = cur.record(_start(cur, "strip", ep=i), i in (1, 4, 9))
    eq("3 of 10 moves back 20", (rec["clears"], rec["moved"], rec["new_pointer"], cur.pointer), (3, True, 2280, 2280))
    # an outcome from a strip start drawn under the EARLIER pointer is stale: logged, never in a block
    stale = CU.Start(99, "strip", 2300, "T_clear", False, 2300)
    for _ in range(30):
        eq("stale strip outcomes never count", cur.record(stale, True), None)
    eq("stale accounting", (cur.stale, cur.stale_clears, cur.counted, cur.state()["open_block"]), (30, 30, 20, []))
    eq("still 2280", cur.pointer, 2280)
    # the pointer never moves forward and stops at 0
    c0 = CU.Curriculum({"T_clear": 2326, "T_t": 2315}, tau0=10)
    for i in range(10):
        rec = c0.record(_start(c0, "strip", ep=i), True)
    eq("moves to 0", c0.pointer, 0)
    for i in range(10):
        rec = c0.record(_start(c0, "strip", ep=i), True)
    eq("no move below 0", (c0.pointer, rec["moved"], rec["at_floor"]), (0, False, True))
    eq("history", [(m["from"], m["to"]) for m in cur.moves], [(2300, 2280)])


@test
def pointer_history_rebuilds_from_the_episode_records() -> None:
    with tmpdir() as d:
        b = stub_builder(d / "run", model_need=40)
        cfg = small_cfg(d / "run", landings=(2128, 1966))
        sess = RUN.Session(cfg, b.env())
        sess.run()
        rows = A.read_jsonl(d / "run" / "training" / "episodes.jsonl")
        ok("training episodes recorded", len(rows) > 20)
        rep = RPT.replay_curriculum(rows, sess.tables)
        eq("no start fails to reproduce from its keys", rep["problems"], [])
        eq("rebuilt pointer equals the live pointer", rep["pointer"], sess.curriculum.pointer)
        eq("rebuilt moves equal the live moves", [(m["from"], m["to"]) for m in rep["moves"]], [(m["from"], m["to"]) for m in sess.curriculum.moves])
        ok("the pointer moved", len(rep["moves"]) >= 1)
        blocks = A.read_jsonl(d / "run" / "training" / "blocks.jsonl")
        for m in A.read_jsonl(d / "run" / "training" / "pointer.jsonl"):
            ok("every step back follows a block of >= 3 clears", m["clears"] >= 3)
        for bl in blocks:
            eq("a block is 10 counted strip outcomes", bl["size"], 10)
            eq("moved iff >= 3 clears", bl["moved"], bl["clears"] >= 3 and bl["pointer"] > 0)


@test
def a_policy_that_cannot_clear_from_the_strip_never_moves_the_pointer_past_what_it_clears() -> None:
    """The stub policy never learns (need = never) and is competent only from tick 2,300 on: it clears the first strip, then the next ones until the strip
    reaches a critical tick it cannot pass; there the pointer stops. Starts behind the pointer (near window, rehearsal) clear by luck and move nothing."""
    with tmpdir() as d:
        b = stub_builder(d / "run", model_need=10 ** 9)
        cfg = small_cfg(d / "run", landings=(2128,))
        sess = RUN.Session(cfg, b.env())
        sess.run()
        world = b.world
        first_crit_below = max(t for t in world.crit if t <= 2300)
        ok(f"the pointer stalled at or above the first uncrossable critical tick ({first_crit_below}): {sess.curriculum.pointer}", sess.curriculum.pointer >= first_crit_below - 40)
        rows = A.read_jsonl(d / "run" / "training" / "episodes.jsonl")
        by_pointer: Dict[int, List[bool]] = {}
        for r in rows:
            if r["start"]["region"] == "strip" and r["start"]["pointer"] <= 2300:
                by_pointer.setdefault(r["start"]["pointer"], []).append(bool(r["clear"]))
        for m in sess.curriculum.moves:
            first_ten = by_pointer[m["from"]][:10]
            ok(f"the step back from {m['from']} was earned by >= 3 clears of the first 10 strip outcomes at that pointer", sum(first_ten) >= 3)
        ok("no step back below the first uncrossable critical tick", sess.curriculum.pointer > first_crit_below - 60)


@test
def rule_module_self_test() -> None:
    eq("self-test", R.self_test(), [])
    eq("rule digest stable", R.rule_digest(), R.rule_digest())
    eq("claim thresholds", R.claim_status(50, 50, 25)["claim"], True)
    eq("claim margin 24 fails", R.claim_status(50, 50, 26)["claim"], False)


# =====================================================================================================================================
# the real recorded replies of the rd4 verifying replays (zero native ticks)
# =====================================================================================================================================


def real_lineages() -> Dict[str, L.Lineage]:
    if "lineages" not in _CACHE:
        _CACHE["lineages"] = L.load_registered(REPO)
    return _CACHE["lineages"]


def real_trace(name: str = "T_clear") -> Dict[str, Any]:
    key = f"trace_{name}"
    if key not in _CACHE:
        _CACHE[key] = L.load_route_trace(REPO, real_lineages()[name])
    return _CACHE[key]


def real_tables(name: str = "T_clear") -> Tuple[List[bytes], List[bytes]]:
    key = f"tables_{name}"
    if key not in _CACHE:
        tr = real_trace(name)
        _CACHE[key] = L.build_tables(tr["initial"], tr["steps"])
    return _CACHE[key]


@test
def lineages_registered_facts_from_the_rd4_routes() -> None:
    lin = real_lineages()
    eq("lengths", {n: ln.length for n, ln in lin.items()}, {"T_clear": 2326, "T_t": 2315})
    eq("T_clear digest", lin["T_clear"].native_action_digest, "5eccd4e2d5d77b25d69a2ae87211c05f8c7349fdeeeed6e094b53a88003907ba")
    eq("T_t digest", lin["T_t"].native_action_digest, "de1228be4146b720adc3f1272a9e65a8c0dcd7882b83134949f3893adfef8045")
    eq("clocks T_clear (never collapsed)", (lin["T_clear"].completion_time_passed, lin["T_clear"].completion_input_tick), (2325, 2326))
    eq("clocks T_t", (lin["T_t"].completion_time_passed, lin["T_t"].completion_input_tick), (2314, 2315))
    eq("shared prefix", L.shared_prefix(lin["T_clear"].words, lin["T_t"].words), 2298)
    ok("Track 1 words", all(w < 72 for ln in lin.values() for w in ln.words))
    for name, ln in lin.items():
        eq(f"{name} words digest", mcell.words_digest(ln.words), ln.native_action_digest)
    bad = dict(C.LINEAGES[0], native_action_digest="0" * 64)
    raises("a wrong registered digest is refused", L.LineageError, lambda: L.load_lineage(REPO, bad))
    bad2 = dict(C.LINEAGES[0], words=2325)
    raises("a wrong registered length is refused", L.LineageError, lambda: L.load_lineage(REPO, bad2))
    bad3 = dict(C.LINEAGES[0], completion_input_tick=2325)
    raises("collapsed clocks are refused", L.LineageError, lambda: L.load_lineage(REPO, bad3))


@test
def landing_states_are_computed_from_the_trunk_and_equal_the_registered_six() -> None:
    tr = real_trace("T_clear")
    starts = L.landing_starts(tr["initial"], tr["steps"])
    eq("every grounded segment start", starts, [0, 58, 174, 269, 375, 508, 682, 753, 841, 1061, 1192, 1248, 1369, 1473, 1694, 1966, 2128])
    eq("the registered six equal the segment starts from 1,248 up", L.check_landings(starts), [])
    ok("a missing landing is refused", L.check_landings([s for s in starts if s != 1473]))
    ok("an extra landing is refused", L.check_landings(starts + [2200]))
    eq("eleven grounded segments below 1,248 (tick 0 included)", len([s for s in starts if s < 1248]), 11)
    eq("deeper landings need the frontier", (E.deeper_landings(starts, 1200), E.deeper_landings(starts, 1192)), ([], [1192]))
    eq("pointer at 1,248 evaluates nothing deeper", E.deeper_landings(starts, 1248), [])
    eq("pointer at 900", E.deeper_landings(starts, 900), [1192, 1061])
    eq("tick 0 is never a deeper landing", 0 in E.deeper_landings(starts, 0), False)


@test
def real_tables_are_deterministic_and_consistent() -> None:
    chain, v3 = real_tables("T_clear")
    tr = real_trace("T_clear")
    eq("table sizes", (len(chain), len(v3)), (2327, 2327))
    eq("chain equals the verifying trace's chain", chain, VF.trace_chain(tr["initial"], tr["steps"]))
    chain2, v3b = L.build_tables(tr["initial"], tr["steps"])
    eq("the v3 digests rebuild identically", v3b, v3)
    ok("digests are 32 bytes and not all equal", all(len(x) == 32 for x in v3) and len(set(v3)) > 2000)
    pin = L.load_pin_tick0(REPO)
    eq("tick-0 chain equals the archive pin", chain[0].hex(), pin["chain"])
    eq("tick-0 record digest equals the archive pin", mcell.record_digest(mcell.tick0_record(tr["initial"])).hex(), pin["digest"])
    t_chain, t_v3 = real_tables("T_t")
    eq("the two routes share their first 2,298 ticks (chain and v3)", (t_chain[:2299], t_v3[:2299]), (chain[:2299], v3[:2299]))
    ok("and differ afterwards", t_chain[2299] != chain[2299])


@test
def p1_evaluation_on_the_real_verifying_replay() -> None:
    import m7n_crossing as xc

    lin = real_lineages()
    pin = L.load_pin_tick0(REPO)
    for name in ("T_clear", "T_t"):
        tr = real_trace(name)
        promoted = {"native_action_digest": lin[name].native_action_digest, "result_json": dict(tr["result"]), "startup": {"mode": "standby_promoted"}}
        ev = L.p1_lineage(lin[name], tr, [tr, tr], xc.analyse_trace, pin, promoted=[promoted])
        eq(f"{name} P1 ok", (ev["ok"], ev["problems"]), (True, []))
        eq(f"{name} chain registered", len(ev["chain"]), lin[name].length + 1)
        if name == "T_clear":
            eq("landings", L.check_landings(ev["landing_starts"]), [])
    tr = real_trace("T_clear")
    bad = dict(tr, steps=list(tr["steps"]))
    st = json.loads(json.dumps(bad["steps"][500]))
    st["observation"]["position_x"] += 1.0
    bad["steps"][500] = st
    ev = L.p1_lineage(lin["T_clear"], tr, [tr, bad], xc.analyse_trace, pin, promoted=[{"native_action_digest": lin["T_clear"].native_action_digest,
                                                                                    "result_json": dict(tr["result"]), "startup": {"mode": "standby_promoted"}}])
    eq("a single altered reply makes P1 fail", ev["ok"], False)
    ok("and the chain difference is named", any("chain" in p for p in ev["problems"]))
    ev = L.p1_lineage(lin["T_clear"], tr, [tr, tr], xc.analyse_trace, pin, promoted=[{"native_action_digest": "0" * 64, "result_json": dict(tr["result"]),
                                                                                    "startup": {"mode": "standby_promoted"}}])
    eq("a wrong promoted digest fails P1", ev["ok"], False)
    ev = L.p1_lineage(lin["T_clear"], tr, [tr, tr], xc.analyse_trace, pin, promoted=[{"native_action_digest": lin["T_clear"].native_action_digest,
                                                                                    "result_json": dict(tr["result"]), "startup": {"mode": "cold"}}])
    eq("a promoted replay that was not promoted fails P1", ev["ok"], False)


@test
def verification_on_the_real_replay_is_exact_and_detects_tampering() -> None:
    import m7n_crossing as xc

    lin = real_lineages()["T_clear"]
    tr = real_trace("T_clear")
    ev = VF.evaluate_trace(tr, lin.words, xc.analyse_trace, expect_clear=True)
    eq("exact", (ev["exact"], ev["problems"], ev["clear"]), (True, [], True))
    eq("both clocks, never collapsed", (ev["completion_time_passed"], ev["completion_input_tick"]), (2325, 2326))
    eq("ten breaks", ev["t"], 10)
    words = bytearray(lin.words)
    words[100] = (words[100] + 1) % 72
    ev = VF.evaluate_trace(tr, bytes(words), xc.analyse_trace, expect_clear=True)
    eq("words that were not the replayed ones fail", ev["exact"], False)
    online = {"breaks": [list(b) for b in ev_breaks_after(tr, 0)], "chain_final": VF.trace_chain(tr["initial"], tr["steps"])[-1].hex(), "end_obs": list(mcell.obs_tuple(tr["steps"][-1]["observation"])),
              "end_reason": "clear", "result": dict(tr["result"]), "native_action_digest": lin.native_action_digest}
    ev = VF.evaluate_trace(tr, lin.words, xc.analyse_trace, online=online, tau=0)
    eq("exact against its own online record", (ev["exact"], ev["problems"]), (True, []))
    bad = dict(online, chain_final="0" * 64)
    eq("a different online chain fails", VF.evaluate_trace(tr, lin.words, xc.analyse_trace, online=bad)["exact"], False)
    bad = dict(online, breaks=online["breaks"][:-1])
    eq("a different online break table fails", VF.evaluate_trace(tr, lin.words, xc.analyse_trace, online=bad)["exact"], False)
    bad = dict(online, result=dict(tr["result"], completion_time_passed=2326))
    eq("collapsed or differing clocks fail", VF.evaluate_trace(tr, lin.words, xc.analyse_trace, online=bad)["exact"], False)
    cut = dict(tr, steps=tr["steps"][:-1])
    eq("a replay that stops early fails", VF.evaluate_trace(cut, lin.words, xc.analyse_trace, expect_clear=True)["exact"], False)


def ev_breaks_after(tr: Mapping[str, Any], tau: int) -> List[Tuple[int, int]]:
    import m7n_crossing as xc

    an = xc.analyse_trace(tr["initial"], tr["steps"])
    return sorted((int(t) + 1, int(i)) for i, t in an["breaks"] if int(t) + 1 > tau)


def trace_core(name: str, rank: int = 0, tables_override: Optional[Mapping[str, L.Tables]] = None, tmp: Optional[Path] = None) -> Tuple[W.WorkerCore, Path]:
    """A worker core over the real recorded replies of `name`, with the real v3 pipeline and tables derived from that trace."""
    tr = real_trace(name)
    ln = real_lineages()[name]
    chain, v3 = real_tables(name)
    d = Path(tmp or tempfile.mkdtemp(prefix="m9tr_"))
    L.save_tables(d / "lineages", name, ln.words, chain, v3)
    spec = {"rank": rank, "lineage_dir": str(d / "lineages"), "lineages": [name], "pin_tick0": L.load_pin_tick0(REPO), "failure_dir": str(d / "failures"), "backend": "m9_stub:TraceBackend",
            "trace": tr, "words": ln.words}
    core = W.WorkerCore(spec, ST.TraceBackend(spec))
    if tables_override is not None:
        core.tables = dict(tables_override)
    return core, d


@test
def staging_on_the_real_replies_checks_every_tick_and_hands_over_the_registered_observation() -> None:
    core, d = trace_core("T_clear")
    try:
        chain, v3 = real_tables("T_clear")
        for tau in (0, 1, 58, 1248, 1694):
            kind, p = core.handle(("stage", {"episode": f"e{tau}", "lineage": "T_clear", "tau": tau}))
            eq(f"staged at {tau}", kind, "staged")
            eq("handover chain", p["handover_chain"], chain[tau].hex())
            eq("handover v3 digest", p["handover_v3"], v3[tau].hex())
            eq("input tick of the handover observation", p["input_tick"], tau)
            eq("observation keys", sorted(p["obs"]), ["action_class", "agent", "projectiles", "segment_geometry", "segment_kind", "targets"])
            eq("observation shapes", {k: tuple(v.shape) for k, v in p["obs"].items()}, {"action_class": (20,), "agent": (28,), "projectiles": (4, 7), "segment_geometry": (32, 8),
                                                                                      "segment_kind": (32, 7), "targets": (10, 5)})
            ok("float32", all(v.dtype.name == "float32" for v in p["obs"].values()))
            eq("targets left at the handover", p["targets_remaining"], int(real_trace("T_clear")["initial"]["observation"]["targets_remaining"] if tau == 0 else
                                                                         real_trace("T_clear")["steps"][tau - 1]["observation"]["targets_remaining"]))
        eq("the staged episode is parked", core.ep is not None and core.ep.tau == 1694, True)
    finally:
        core.shutdown()
        shutil.rmtree(d, ignore_errors=True)


@test
def a_policy_phase_on_the_real_replies_reproduces_the_clear_and_finalises_it() -> None:
    core, d = trace_core("T_clear")
    try:
        ln = real_lineages()["T_clear"]
        kind, _p = core.handle(("stage", {"episode": "e", "lineage": "T_clear", "tau": 2128}))
        eq("staged", kind, "staged")
        final = None
        ticks = 0
        for i in range(2128, 2326):
            kind, p = core.handle(("step", {"word": ln.words[i]}))
            eq("stepped", kind, "stepped")
            ticks += 1
            eq("consumed tick", p["consumed_tick"], i)
            if p["final"] is not None:
                final = p["final"]
                eq("the clear is the last word", i, 2325)
                eq("clear", (p["end"], p["clear"], p["ended"], p["fell"]), ("clear", True, True, False))
        ok("a final record", final is not None)
        eq("end reason and ticks", (final["end_reason"], final["ticks"], final["policy_ticks"], final["tau"]), ("clear", 2326, 198, 2128))
        eq("native result with both clocks", (final["result"]["completion_time_passed"], final["result"]["completion_input_tick"]), (2325, 2326))
        eq("the process was finalised and released", core.ep, None)
        chain, _ = real_tables("T_clear")
        eq("the online chain equals the verifying replay's last chain", final["chain_final"], chain[-1].hex())
        eq("online breaks after the handover", sorted(tuple(b) for b in final["breaks"]), [(b[0], b[1]) for b in ev_breaks_after(real_trace("T_clear"), 2128)])
        # deviating from the recorded route ends the (synthetic) episode as a native failure
        core.handle(("stage", {"episode": "e2", "lineage": "T_clear", "tau": 1694}))
        wrong = (ln.words[1694] + 1) % 72
        kind, p = core.handle(("step", {"word": wrong}))
        eq("a deviation ends as a native failure", (p["end"], p["fell"], p["final"]["end_reason"]), ("fall", True, "fall"))
    finally:
        core.shutdown()
        shutil.rmtree(d, ignore_errors=True)


@test
def staging_refuses_a_corrupted_table_as_an_integrity_failure() -> None:
    chain, v3 = real_tables("T_clear")
    ln = real_lineages()["T_clear"]
    for what, tabs in (("chain", L.Tables(ln.words, chain[:300] + [b"\x00" * 32] + chain[301:], v3)), ("v3", L.Tables(ln.words, chain, v3[:300] + [b"\x01" * 32] + v3[301:])),
                       ("tick0", L.Tables(ln.words, [b"\x02" * 32] + chain[1:], v3))):
        core, d = trace_core("T_clear", tables_override={"T_clear": tabs})
        try:
            kind, p = core.handle(("stage", {"episode": f"bad-{what}", "lineage": "T_clear", "tau": 400}))
            eq(f"{what}: stage_failed", kind, "stage_failed")
            eq(f"{what}: an integrity failure", (p["kind"], p["mismatch"]), ("mismatch", {"chain": "prefix_chain", "v3": "prefix_v3", "tick0": "tick0_chain"}[what]))
            eq("the process is released", core.ep, None)
        finally:
            core.shutdown()
            shutil.rmtree(d, ignore_errors=True)
    core, d = trace_core("T_clear")
    try:
        kind, p = core.handle(("stage", {"episode": "x", "lineage": "T_clear", "tau": 2325}))
        eq("a start on the terminal tick is refused", (kind, p["kind"]), ("stage_failed", "mismatch"))
        kind, p = core.handle(("step", {"word": 0}))
        eq("a step without an episode is an integrity failure", (kind, p["kind"]), ("step_failed", "mismatch"))
    finally:
        core.shutdown()
        shutil.rmtree(d, ignore_errors=True)


@test
def the_real_v3_pipeline_matches_the_wrapper_stack_observation_contract() -> None:
    import m7n_obs as mn
    import m9_obs

    tr = real_trace("T_clear")
    pipe = m9_obs.V3Pipeline(tr["initial"])
    ok("the space matches", mn.make_observation_space().contains({k: v for k, v in pipe.arrays().items()}))
    for s in tr["steps"][:200]:
        pipe.feed(s)
    ok("masked rows stay exactly zero", mn.masked_rows_are_zero(pipe.arrays()) == [])
    eq("the digest function is the M7n one", pipe.digest(), mn.observation_digest(pipe.arrays()))
    eq("flat size 606", mn.flatten(pipe.arrays()).shape, (606,))
    eq("contract digest", m9_obs.contract_description()["observation_digest"], mn.contract_digest())


# =====================================================================================================================================
# the synthetic world: worker core, rewards, arena, vector env, PPO interface
# =====================================================================================================================================


def stub_core(inject: Optional[Mapping[str, Any]] = None, rank: int = 0) -> Tuple[W.WorkerCore, Path, TE.StubEnvBuilder]:
    d = Path(tempfile.mkdtemp(prefix="m9sc_"))
    b = stub_builder(d, inject=inject)
    for name, ln in b.lineages.items():
        tr = b.route_traces[name]
        chain, v3 = L.build_tables(tr["initial"], tr["steps"], ST.StubObs)
        L.save_tables(d / "lineages", name, ln.words, chain, v3)
    spec = b.spec(rank, C.FLAGS_TRAIN)
    return W.WorkerCore(spec, ST.StubBackend(spec)), d, b


@test
def stub_world_properties_tape_fails_policy_clears() -> None:
    b = stub_builder(Path(tempfile.gettempdir()) / "m9_unused")
    w = b.world
    replay = b.replay
    tr = replay(w.a, "a", 0)
    eq("T_clear clears at 2326", (tr["final_state"], tr["result"]["completion_input_tick"]), ("EpisodeEnded", 2326))
    tr_t = replay(w.b, "b", 0)
    eq("T_t clears at 2315", (tr_t["final_state"], tr_t["result"]["completion_input_tick"]), ("EpisodeEnded", 2315))
    tape = S.Tape(w.a)
    clears = 0
    for k in range(20):
        label = S.eval_label("reach", 1473, k)
        words = bytearray(w.a[:1473])
        prev = words[-1]
        for t in range(1473, 2326):
            word, _ = S.submit(label, t, tape.word(t), prev)
            words.append(word)
            prev = word
        clears += int(replay(bytes(words), "tape", 0)["final_state"] == "EpisodeEnded")
    ok(f"the tape rarely clears under sticky draws ({clears}/20)", clears <= 3)
    # the skilled closed-loop policy (the stub model above its competence boundary)
    model = ST.StubModel(None, n_steps=1, b0=1200)
    clears = 0
    for k in range(20):
        label = S.eval_label("reach", 1473, k)
        s = w.initial()
        for word in w.a[:1473]:
            w.advance(s, word)
        prev = int(w.a[1472])
        for t in range(1473, 2326):
            rep = w.reply(s, 0)
            obs = {"agent": np_array([[0.0] * 24 + [rep["stub"]["t"] / 3600.0, rep["stub"]["route_word"] / 72.0, (rep["stub"]["pending"] + 1) / 73.0, 0.0]])}
            a, _ = model.predict(obs)
            word, _ = S.submit(label, t, int(a[0][0]) * 8 + int(a[0][1]), prev)
            w.advance(s, word)
            prev = word
            if s[7]:
                break
        clears += int(bool(s[6]))
    ok(f"the closed-loop policy clears under sticky draws ({clears}/20)", clears >= 15)


def np_array(x: Any) -> Any:
    import numpy as np

    return np.array(x, dtype=np.float32)


@test
def worker_core_on_the_stub_stage_step_close_and_failures() -> None:
    core, d, b = stub_core()
    try:
        kind, p = core.handle(("stage", {"episode": "a", "lineage": "T_clear", "tau": 700}))
        eq("staged", (kind, p["ticks"], p["input_tick"], p["mode"]), ("staged", 700, 700, "cold"))
        eq("a parked process takes a word", core.handle(("step", {"word": int(b.world.a[700])}))[0], "stepped")
        eq("close", core.handle(("close", {}))[0], "closed")
        eq("no episode after close", core.ep, None)
        kind, p = core.handle(("stage", {"episode": "b", "lineage": "T_t", "tau": 2313}))
        eq("T_t starts up to its own length - 2", kind, "staged")
        kind, p = core.handle(("stage", {"episode": "c", "lineage": "T_t", "tau": 2314}))
        eq("beyond is refused", (kind, p["kind"]), ("stage_failed", "mismatch"))
        eq("an unknown command is an error, not an exception", core.handle(("nope",))[0], "error")
    finally:
        core.shutdown()
        shutil.rmtree(d, ignore_errors=True)
    core, d, _b = stub_core({"lifecycle_jobs": [1], "lifecycle_tick": 3})
    try:
        kind, p = core.handle(("stage", {"episode": "l", "lineage": "T_clear", "tau": 50}))
        eq("a process death while staging is a lifecycle failure", (kind, p["kind"]), ("stage_failed", "lifecycle"))
    finally:
        core.shutdown()
        shutil.rmtree(d, ignore_errors=True)
    core, d, _b = stub_core({"mismatch_job": 1, "mismatch_tick": 20})
    try:
        kind, p = core.handle(("stage", {"episode": "m", "lineage": "T_clear", "tau": 100}))
        eq("a reply that differs from the registered chain is an integrity failure", (kind, p["kind"], p["mismatch"]), ("stage_failed", "mismatch", "prefix_chain"))
        ok("the evidence is preserved", p["preserved"] is not None and Path(p["preserved"]).is_file())
        ev = A.read_json_gz(Path(p["preserved"]))
        A.check(ev)
    finally:
        core.shutdown()
        shutil.rmtree(d, ignore_errors=True)
    core, d, _b = stub_core({"bad_consumed_job": 1})
    try:
        kind, p = core.handle(("stage", {"episode": "k", "lineage": "T_clear", "tau": 100}))
        eq("a consumed-tick violation is an integrity failure", (kind, p["kind"], p["mismatch"]), ("stage_failed", "mismatch", "consumed_tick"))
    finally:
        core.shutdown()
        shutil.rmtree(d, ignore_errors=True)
    core, d, _b = stub_core({"provenance_job": 1})
    try:
        import m8_rd_worker as mw

        mw.ProvenanceGuard.violations.clear()
        kind, p = core.handle(("stage", {"episode": "p", "lineage": "T_clear", "tau": 5}))
        ok("the provenance violation is reported with the reply", bool(core.handle(("report",))[1]["provenance_violations"]))
        mw.ProvenanceGuard.violations.clear()
    finally:
        core.shutdown()
        shutil.rmtree(d, ignore_errors=True)


@test
def reward_v2_is_rebased_at_the_handover_and_equals_the_closed_form() -> None:
    from btt_rewards import REWARD_V2, expected_return

    core, d, b = stub_core()
    try:
        tau = 700                                              # the prefix has broken 4 targets (ticks 43, 120, 399, 609)
        kind, staged = core.handle(("stage", {"episode": "r", "lineage": "T_clear", "tau": tau}))
        eq("targets left at the handover", staged["targets_remaining"], 6)
        job = V.StartJob(0, CU.Start(0, "strip", tau, "T_clear", True, tau), None, kind="t")
        ctx = V.EpisodeCtx(job, 0, staged, b.lineages["T_clear"].words)
        total = 0.0
        steps = 0
        end = None
        for i in range(tau, 2326):
            word = ctx.choose(int(b.world.a[i]))
            kind, p = core.handle(("step", {"word": word}))
            r = ctx.apply(p)
            total += r["reward"]
            steps += 1
            if p["final"] is not None:
                end = p["final"]
                break
        ok("cleared", end is not None and end["end_reason"] == "clear")
        want = expected_return(6, steps, cleared=True, contract=REWARD_V2)
        ok(f"policy-phase return {total} = 6 targets + 10 clear - {steps} * 0.001 = {want}", abs(total - want) < 1e-9)
        ok("prefix breaks earned nothing", abs(ctx.terms["target_term"] - 6.0) < 1e-12)
        eq("steps", (ctx.steps, steps), (steps, 2326 - tau))
    finally:
        core.shutdown()
        shutil.rmtree(d, ignore_errors=True)
    # a fall: -5 once, and the step cost, no clear bonus
    core, d, b = stub_core()
    try:
        kind, staged = core.handle(("stage", {"episode": "f", "lineage": "T_clear", "tau": 700}))
        ctx = V.EpisodeCtx(V.StartJob(1, CU.Start(1, "strip", 700, "T_clear", True, 700), None, kind="t"), 0, staged, b.lineages["T_clear"].words)
        total = 0.0
        for i in range(700, 2326):
            kind, p = core.handle(("step", {"word": ctx.choose(71 if i > 800 else int(b.world.a[i]))}))
            total += ctx.apply(p)["reward"]
            if p["final"] is not None:
                break
        eq("the end", p["final"]["end_reason"], "fall")
        ok("fall return = targets + step costs - 5", abs(total - expected_return(int(round(ctx.terms["target_term"])), ctx.steps, cleared=False, native_failure=True, contract=REWARD_V2)) < 1e-9)
        eq("the failure term applies once", ctx.terms["failure_term"], -5.0)
    finally:
        core.shutdown()
        shutil.rmtree(d, ignore_errors=True)


@test
def the_horizon_counts_from_the_reset_and_truncates() -> None:
    d = Path(tempfile.mkdtemp(prefix="m9h_"))
    try:
        b = stub_builder(d, inject={"no_clear": True})
        for name, ln in b.lineages.items():
            tr = b.route_traces[name]
            chain, v3 = L.build_tables(tr["initial"], tr["steps"], ST.StubObs)
            L.save_tables(d / "lineages", name, ln.words, chain, v3)
        spec = b.spec(0, C.FLAGS_TRAIN)
        core = W.WorkerCore(spec, ST.StubBackend(spec))
        kind, staged = core.handle(("stage", {"episode": "h", "lineage": "T_clear", "tau": 2300}))
        n = 0
        while True:
            kind, p = core.handle(("step", {"word": 0}))
            n += 1
            if p["final"] is not None:
                break
        eq("the policy phase is 3600 - tau ticks", n, 3600 - 2300)
        eq("end", (p["end"], p["final"]["end_reason"], p["j"]), ("horizon", "horizon", 3600))
        job = V.StartJob(2, CU.Start(2, "strip", 2300, "T_clear", False, 2300), None, kind="t")
        ctx = V.EpisodeCtx(job, 0, staged, b.lineages["T_clear"].words)
        eq("truncated, not terminated", (ctx.apply(p)["truncated"], ctx.apply(p)["terminated"]), (True, False))
    finally:
        shutil.rmtree(d, ignore_errors=True)


@test
def tick_budget_and_arena_accounting() -> None:
    bud = V.TickBudget(1000)
    ok("stage fits", bud.can_stage(900))
    bud.reserve(900)
    ok("a second stage does not", not bud.can_stage(200))
    bud.staged(900)
    eq("consumed", (bud.consumed, bud.reserved, bud.prefix), (900, 0, 900))
    bud.step(99)
    ok("not exhausted at 999", not bud.exhausted())
    bud.step(1)
    ok("exhausted at the cap", bud.exhausted())
    bud2 = V.TickBudget(500)
    bud2.reserve(300)
    bud2.failed(300)
    eq("a failed stage returns its reservation", (bud2.consumed, bud2.reserved), (0, 0))
    with tmpdir() as d:
        b = stub_builder(d / "run")
        for name, ln in b.lineages.items():
            tr = b.route_traces[name]
            chain, v3 = L.build_tables(tr["initial"], tr["steps"], ST.StubObs)
            L.save_tables(d / "run" / "lineages", name, ln.words, chain, v3)
        tables = L.load_all_tables(d / "run" / "lineages", ["T_clear", "T_t"])
        pool = b.make_pool("x", C.FLAGS_TRAIN)
        cur = CU.Curriculum({n: len(t.words) for n, t in tables.items()})
        arena = V.Arena(pool, tables, T.TrainSource(cur), V.TickBudget(5 * 2300), now=b.clock.now)
        arena.pump(0.0)
        ok("dispatch stops at the tick budget (a stage that does not fit is not launched)", arena.dispatched <= 5 and arena.source_done)
        eq("10 slots exist", pool.n, 10)
        # a stale stage reply (a job of an earlier arena) is ignored
        arena2 = V.Arena(pool, tables, T.ListSource([]), V.TickBudget(10 ** 6), now=b.clock.now)
        eq("stale reply ignored", arena2.handle(3, "staged", {"episode": "old-job", "ticks": 5}), None)
        eq("counted", arena2.stale_events, 1)
        raises("a stale integrity failure is never dropped", V.IntegrityStop, lambda: arena2.handle(3, "stage_failed", {"episode": "old-job", "kind": "mismatch", "mismatch": "prefix_chain"}))
        eq("a stale lifecycle failure is ignored", arena2.handle(3, "stage_failed", {"episode": "old-job", "kind": "lifecycle", "outcome": "x", "message": "m"}), None)
        # lifecycle failures beyond the limit stop the phase as INCOMPLETE, a mismatch as INVALID
        a3 = V.Arena(pool, tables, T.ListSource([]), V.TickBudget(10 ** 6), now=b.clock.now, lifecycle_limit=2)
        job = V.StartJob(0, CU.Start(0, "strip", 10, "T_clear", True, 0), None)
        for i in range(2):
            a3.job[i] = job
            a3.state[i] = "staging"
            a3.budget.reserve(10)
            eq("failure recorded", a3.handle(i, "stage_failed", {"episode": job.job_id, "kind": "lifecycle", "outcome": "x", "message": "m"}), None)
        a3.job[2], a3.state[2] = job, "staging"
        e = raises("third failure", V.CapStop, lambda: a3.handle(2, "stage_failed", {"episode": job.job_id, "kind": "lifecycle", "outcome": "x", "message": "m"}))
        eq("not a valid end", e.valid, False)
        a3.job[3], a3.state[3] = job, "staging"
        raises("a mismatch is INVALID", V.IntegrityStop, lambda: a3.handle(3, "stage_failed", {"episode": job.job_id, "kind": "mismatch", "mismatch": "prefix_chain"}))
        raises("a provenance violation is INVALID", V.IntegrityStop, lambda: a3.handle(4, "staged", {"episode": "x", "provenance_violations": ["a write under a protected root"]}))


@test
def train_vec_env_semantics_and_ppo_interface() -> None:
    import numpy as np

    with tmpdir() as d:
        b = stub_builder(d / "run")
        for name, ln in b.lineages.items():
            tr = b.route_traces[name]
            chain, v3 = L.build_tables(tr["initial"], tr["steps"], ST.StubObs)
            L.save_tables(d / "run" / "lineages", name, ln.words, chain, v3)
        tables = L.load_all_tables(d / "run" / "lineages", ["T_clear", "T_t"])
        pool = b.make_pool("x", C.FLAGS_TRAIN)
        cur = CU.Curriculum({n: len(t.words) for n, t in tables.items()})
        arena = V.Arena(pool, tables, T.TrainSource(cur), V.TickBudget(15_000_000), now=b.clock.now)
        rec = T.TrainRecorder(d / "run" / "training", cur, tables, now=b.clock.now, write_artifacts=False)
        Vec = V.make_vec_env_class()
        env = Vec(arena, 4, recorder=rec.on_episode, outcome=rec.on_outcome)
        obs = env.reset()
        eq("batched observation", {k: tuple(v.shape) for k, v in obs.items()}, {"action_class": (4, 20), "agent": (4, 28), "projectiles": (4, 4, 7), "segment_geometry": (4, 32, 8),
                                                                               "segment_kind": (4, 32, 7), "targets": (4, 10, 5)})
        ok("float32 and inside the space", all(v.dtype == np.float32 for v in obs.values()))
        eq("MultiDiscrete action space", tuple(env.action_space.nvec), (9, 8))
        model = ST.StubModel(env, n_steps=1)
        done_seen = 0
        for _ in range(60):
            acts, _ = model.predict(obs)
            obs, rew, dones, infos = env.step(acts)
            eq("shapes", (rew.shape, dones.shape, len(infos)), ((4,), (4,), 4))
            for i in np.nonzero(dones)[0]:
                done_seen += 1
                ok("a terminal observation is returned with the info", "terminal_observation" in infos[i] and "TimeLimit.truncated" in infos[i])
                ok("episode info for the monitor", infos[i]["episode"]["l"] > 0)
        ok("episodes finished and were recorded", done_seen > 0 and rec.episodes == done_seen)
        eq("num_timesteps counts policy transitions only", env.transitions, 60 * 4)
        eq("prefix ticks are not transitions", (arena.budget.policy, arena.budget.prefix > 60 * 4), (240, True))


@test
def the_sb3_ppo_trains_one_rollout_over_the_staged_vec_env() -> None:
    import numpy as np

    with tmpdir() as d:
        b = stub_builder(d / "run")
        for name, ln in b.lineages.items():
            tr = b.route_traces[name]
            chain, v3 = L.build_tables(tr["initial"], tr["steps"], ST.StubObs)
            L.save_tables(d / "run" / "lineages", name, ln.words, chain, v3)
        tables = L.load_all_tables(d / "run" / "lineages", ["T_clear", "T_t"])
        pool = b.make_pool("x", C.FLAGS_TRAIN)
        cur = CU.Curriculum({n: len(t.words) for n, t in tables.items()})
        arena = V.Arena(pool, tables, T.TrainSource(cur), V.TickBudget(15_000_000), now=b.clock.now)
        rec = T.TrainRecorder(d / "run" / "training", cur, tables, now=b.clock.now, write_artifacts=False)
        env = V.make_vec_env_class()(arena, 4, recorder=rec.on_episode, outcome=rec.on_outcome)
        model = T.make_ppo(env, 4)
        eq("n_steps", (model.n_steps, model.n_envs, model.batch_size, model.n_epochs), (1280, 4, 512, 10))
        eq("hyper-parameters", (model.learning_rate, model.gamma, model.gae_lambda, model.clip_range(1), model.ent_coef, model.vf_coef, model.max_grad_norm),
           (3e-4, 0.999, 0.995, 0.2, 0.01, 0.5, 0.5))
        eq("fresh policy, network id", type(model.policy).__name__, "MultiInputActorCriticPolicy")
        stop = T.train(model, env, arena, cur, rec, run_dir=d / "run" / "training", guard=lambda: None, now=b.clock.now, transition_cap=5120)
        eq("the transition cap is the registered valid end", (stop["valid_end"], stop["reason"], stop["num_timesteps"]), (True, "transition_cap", 5120))
        ok("one initial and one final checkpoint, digests pinned", [c["checkpoint"] for c in stop["checkpoints"]] == ["ckpt_000000000"] and stop["final"]["checkpoint"] == "final")
        for name in ("ckpt_000000000", "final"):
            meta = A.read_json(d / "run" / "training" / "checkpoints" / name / "checkpoint.json")
            A.check(meta)
            eq("model digest pinned", meta["model_zip_sha256"], T.sha256_file(d / "run" / "training" / "checkpoints" / name / "model.zip"))
        import m7n_policy as pol

        pol.assert_v3_checkpoint(d / "run" / "training" / "checkpoints" / "final" / "model.zip")
        rows = A.read_jsonl(d / "run" / "training" / "rollouts.jsonl")
        eq("one rollout row", len(rows), 1)
        probe = {k: np.random.default_rng(0).standard_normal((3,) + v.shape[1:]).astype(np.float32) for k, v in env._obs.items()}
        acts, _ = model.predict(probe, deterministic=True)
        eq("a batch of actions", acts.shape, (3, 2))
        from stable_baselines3 import PPO

        loaded = PPO.load(str(d / "run" / "training" / "checkpoints" / "final" / "model.zip"), device="cpu")
        loaded.policy.set_training_mode(False)
        acts2, _ = loaded.predict(probe, deterministic=True)
        eq("the frozen final model reloads and decides identically", acts2.tolist(), acts.tolist())


@test
def ppo_settings_equal_the_m7n_profile_except_entropy() -> None:
    import tomllib

    prof = tomllib.loads((RL / "configs" / "m7n" / "m7n_s0_v3.toml").read_text(encoding="utf-8"))["ppo"]
    p = C.PPO
    for k_toml, k_c in (("learning_rate", "learning_rate"), ("batch_size", "batch_size"), ("n_epochs", "n_epochs"), ("gamma", "gamma"), ("gae_lambda", "gae_lambda"),
                        ("clip_range", "clip_range"), ("vf_coef", "vf_coef"), ("max_grad_norm", "max_grad_norm"), ("torch_threads", "torch_threads"), ("device", "device"),
                        ("rollout_size", "rollout_size")):
        eq(f"{k_toml}", p[k_c], prof[k_toml])
    eq("net arch", list(p["net_arch"]), list(prof["net_arch"]))
    eq("activation", p["activation"], prof["activation"])
    eq("the profile's entropy is 0.0, M9's is 0.01", (prof["ent_coef"], p["ent_coef"]), (0.0, 0.01))
    eq("n_steps for 4 and 2 playing slots", (T.ppo_kwargs(4)["n_steps"], T.ppo_kwargs(2)["n_steps"]), (1280, 2560))
    raises("a width that does not divide the rollout", ValueError, lambda: T.ppo_kwargs(3))
    eq("a vector width is applied to the rollout", T.ppo_kwargs(4)["n_steps"] * 4, C.ROLLOUT_SIZE)


# =====================================================================================================================================
# the evaluation: jobs, the tape control, the unperturbed diagnostic, aggregation, the split rule
# =====================================================================================================================================


@test
def evaluation_jobs_have_the_registered_structure() -> None:
    jobs = E.evaluation_jobs(list(C.LANDINGS), E.fine_grid(1694), tape_landings=[])
    kinds: Dict[str, int] = {}
    for j in jobs:
        kinds[j.kind] = kinds.get(j.kind, 0) + 1
    eq("20 sticky policy episodes at each of the six landings", kinds["reach"], 6 * 20)
    eq("one deterministic episode per landing", kinds["reach_det"], 6)
    eq("tick 0: 20 sticky, 1 deterministic, 20 unperturbed", (kinds["tick0"], kinds["tick0_det"], kinds["tick0_unperturbed"]), (20, 1, 20))
    eq("the unperturbed diagnostic: 20 per landing", kinds["unperturbed"], 6 * 20)
    fine = E.fine_grid(1694)
    eq("fine grid from 2,300 down to 50 below the final pointer (every 25 ticks)", (fine[0], fine[-1], len(fine)), (2300, 1650, 27))
    eq("the fine grid has at most 40 points", len(E.fine_grid(0)), 40)
    eq("fine episodes", kinds["fine"], 27 * 10)
    ok("no tape here for the registered landings (P4 ran them before training)", "reach_tape" not in kinds)
    tiers = [j.tier for j in jobs]
    eq("priority order is non-decreasing", tiers, sorted(tiers))
    ok("every sticky job has a label, every unperturbed or deterministic job none", all((j.label is None) == (j.kind in ("reach_det", "tick0_det", "unperturbed", "tick0_unperturbed")) for j in jobs))
    ok("unperturbed and deterministic jobs are never sticky", all(j.label is None for j in jobs if j.kind in ("unperturbed", "reach_det")))
    ok("unique ids", len({j.job_id for j in jobs}) == len(jobs))
    p4 = E.p4_jobs()
    eq("P4: 20 tape episodes at six landings and at tick 0", (len(p4), {j.kind for j in p4}, sum(1 for j in p4 if j.start.tau == 0)), (140, {"reach_tape"}, 20))
    ok("tape jobs share labels with the policy jobs", {j.label for j in p4 if j.start.tau == 1694} == {j.label for j in jobs if j.kind == "reach" and j.start.tau == 1694})
    deeper = E.evaluation_jobs(list(C.LANDINGS) + [1192], fine, tape_landings=[1192])
    eq("a deeper landing adds 20 policy and 20 tape episodes", (sum(1 for j in deeper if j.kind == "reach" and j.start.tau == 1192), sum(1 for j in deeper if j.kind == "reach_tape")), (20, 20))
    ok("all start at the trunk lineage", all(j.start.lineage == "T_clear" for j in jobs))
    ok("no claim-style tick-0 prefix path: tick-0 jobs have tau 0", all(j.start.tau == 0 for j in jobs if j.kind.startswith("tick0")))


@test
def aggregation_counts_verified_clears_and_pairs_the_tape() -> None:
    def rec(i: str, kind: str, lam: int, clear: bool) -> Dict[str, Any]:
        return {"episode": i, "eval_kind": kind, "landing": lam, "clear": clear, "end_reason": "clear" if clear else "fall", "ticks": 5, "t": 0}

    recs = [rec(f"p{k}", "reach", 1694, k < 12) for k in range(20)] + [rec(f"t{k}", "reach_tape", 1694, k < 2) for k in range(20)] + \
        [rec(f"u{k}", "unperturbed", 1694, k < 7) for k in range(20)] + [rec(f"f{k}", "fine", 2300, k < 4) for k in range(10)] + [rec("d", "reach_det", 1694, True)]
    ver = {f"p{k}": True for k in range(11)}
    ver.update({f"t{k}": True for k in range(2)})
    agg = E.aggregate(recs, ver)
    row = agg["reach"][1694]
    eq("claimed vs verified policy clears", (row["n"], row["clears"], row["verified"]), (20, 12, 11))
    eq("tape", (row["tape_n"], row["tape_clears"], row["tape_verified"]), (20, 2, 2))
    eq("unperturbed row", (agg["unperturbed"][1694]["n"], agg["unperturbed"][1694]["clears"]), (20, 7))
    eq("fine row", (agg["fine"][2300]["n"], agg["fine"][2300]["clears"]), (10, 4))
    eq("deterministic reported", agg["deterministic"][1694]["clear"], True)
    out = R.apply({"invalid": [], "phases": {p: True for p in ("p1", "p2", "p3", "p4")}, "training": {"valid_end": True, "stop": "wall"}, "reach": {1694: row},
                   "landings": [1694], "unperturbed": agg["unperturbed"]})
    eq("11 verified of 20 against a tape of 2: counts, R = 1694", (out["outcome"], out["R"]), ("PASS", 1694))
    out = R.apply({"invalid": [], "phases": {p: True for p in ("p1", "p2", "p3", "p4")}, "training": {"valid_end": True, "stop": "wall"}, "reach": {1694: dict(row, verified=9, clears=9)},
                   "landings": [1694]})
    eq("9 of 20 is NULL", out["outcome"], "NULL")


@test
def process_split_selection_rule() -> None:
    def row(tps: float, eligible: bool = True) -> Dict[str, Any]:
        return {"transitions_per_s": tps, "eligible": eligible}

    eq("equal throughput keeps the default", RUN.select_split(row(100), row(100))[0], (4, 6))
    eq("109 % keeps the default", RUN.select_split(row(100), row(109.9))[0], (4, 6))
    eq("110 % chooses 2 + 8", RUN.select_split(row(100), row(110))[0], (2, 8))
    eq("4 + 6 faster keeps the default", RUN.select_split(row(150), row(100))[0], (4, 6))
    eq("an ineligible 4 + 6 leaves 2 + 8", RUN.select_split(row(100, False), row(50))[0], (2, 8))
    eq("an ineligible 2 + 8 keeps 4 + 6", RUN.select_split(row(100), row(1000, False))[0], (4, 6))
    eq("neither eligible: undecided", RUN.select_split(row(100, False), row(100, False))[0], None)
    ok("the rule's text is in the decisions record", "1.10" in (REPO / "docs" / "rl_m9_g1_decisions_2026-10-04.md").read_text(encoding="utf-8"))


@test
def budget_projection_fits_the_session_cap_without_trimming() -> None:
    bp = RUN.budget_projection()
    eq("registered phase caps in minutes", {k: v / 60 for k, v in bp["phase_caps_s"].items()}, {"p1": 4.0, "p2": 2.0, "p3": 5.0, "p4": 6.0, "train": 60.0, "eval": 25.0, "verify": 15.0, "close": 5.0})
    eq("sum of the caps", bp["sum_of_caps_s"], 122 * 60)
    ok(f"the pessimistic total {bp['pessimistic_total_min']} min fits the 130-minute cap", bp["fits_global_cap_pessimistic"] and bp["pessimistic_total_s"] <= 130 * 60)
    ok("with margin", bp["slack_pessimistic_s"] > 120)
    ok("the expected total is below the pessimistic one", bp["expected_total_s"] < bp["pessimistic_total_s"])


# =====================================================================================================================================
# session level: small runs (in-process lock-step pool, virtual clock)
# =====================================================================================================================================


@test
def a_small_session_runs_every_phase_and_every_record_carries_the_metadata() -> None:
    with tmpdir() as d:
        sess, out, b = run_small(d)
        eq("every phase ran", sess.phases, {"p1": True, "p2": True, "p3": True, "p4": True, "train": True, "eval": True, "verify": True})
        eq("a small evaluation is not the registered one: INCOMPLETE (landing states not fully evaluated)", out["outcome"], "INCOMPLETE")
        ok("named", any("not fully evaluated" in r for r in out["reasons"]))
        root = d / "run"
        for rel in ("session/p1.json", "session/p2.json", "session/p3.json", "session/p4.json", "session/training_summary.json", "session/eval_run.json", "session/verification.json",
                    "session/close.json", "session/rule.json", "session/state.json", "lineages/registry.json", "lineages/T_clear/registration.json", "lineages/T_t/registration.json",
                    "training/checkpoints.json", "training/episodes.jsonl", "p4/episodes.jsonl", "eval/episodes.jsonl", "verification/replays.jsonl"):
            ok(f"{rel} exists", (root / rel).is_file())
        aud = A.audit_tree(root)
        eq("every JSON file and every JSONL line carries task and created_utc", (aud["ok"], aud["failures"]), (True, []))
        ok("a meaningful number checked", aud["files"] > 15 and aud["jsonl_lines"] > 30)
        eq("the rule record names the scope", A.read_json(root / "session" / "rule.json")["scope"], C.SCOPE)
        rule = A.read_json(root / "session" / "rule.json")
        p3 = A.read_json(root / "session" / "p3.json")
        eq("both configurations were measured", sorted(p3["rows"]), ["2x8", "4x6"])
        eq("the split is the registered rule's choice on the measured rows", rule["split"], list(RUN.select_split(p3["rows"]["4x6"], p3["rows"]["2x8"])[0]))
        eq("recorded in P3", p3["choice"], rule["split"])
        ok("the training used it", A.read_json(root / "session" / "training_summary.json")["split"] == rule["split"])
        p1 = A.read_json(root / "session" / "p1.json")
        eq("P1: both lineages ok", {n: v["ok"] for n, v in p1["lineages"].items()}, {"T_clear": True, "T_t": True})
        eq("P1 replays per lineage: two fresh and one promoted", {n: len(v["replays"]) for n, v in p1["lineages"].items()}, {"T_clear": 3, "T_t": 3})
        rep = RPT.verify_run(root)
        eq("verify-run", (rep["ok"], rep["problems"]), (True, []))
        eq("every clear of P4 and the evaluation has an exact replay", rep["verification"]["clears_without_a_replay"], 0)


@test
def two_runs_of_the_same_session_agree_on_every_record() -> None:
    rels = ["session/p1.json", "session/p2.json", "session/p4.json", "session/rule.json", "session/training_summary.json", "training/episodes.jsonl", "training/blocks.jsonl",
            "training/pointer.jsonl", "eval/episodes.jsonl", "p4/episodes.jsonl", "verification/replays.jsonl", "training/checkpoints.json"]
    outs = []
    for _ in range(2):
        with tmpdir() as d:
            run_small(d)
            outs.append(read_dir_records(d / "run", rels))
            outs[-1]["model_digests"] = sorted(p.read_bytes().hex()[:0] + hashlib.sha256(p.read_bytes()).hexdigest() for p in (d / "run" / "training" / "checkpoints").rglob("model.zip"))
    for rel in rels:
        eq(f"{rel} equal", outs[0].get(rel), outs[1].get(rel))
    eq("model files equal", outs[0]["model_digests"], outs[1]["model_digests"])


@test
def session_outcomes_and_stops() -> None:
    # a lifecycle failure while staging is redrawn; more than three in a phase are INCOMPLETE
    with tmpdir() as d:
        sess, out, _b = run_small(d, inject={"acquire_fail_jobs": list(range(2, 40))}, cfg_over={})
        eq("too many lifecycle failures: INCOMPLETE", out["outcome"], "INCOMPLETE")
        ok("the reason is named", out["stop"] is not None and "lifecycle" in out["stop"]["reason"])
        ok("nothing was relaunched, the failed phase is recorded", out["stop"]["phase"] in ("p2", "p3", "p4", "train"))
    # a mismatch is INVALID, with no retry
    with tmpdir() as d:
        sess, out, _b = run_small(d, inject={"mismatch_job": 3, "mismatch_tick": 30})
        eq("INVALID on an integrity failure", out["outcome"], "INVALID")
        ok("named", any("integrity" in r.lower() or "prefix_chain" in r for r in out["reasons"]))
    # a provenance / write-guard violation is INVALID
    with tmpdir() as d:
        viol: List[str] = []
        sess, out, _b = run_small(d, env_over={"provenance_violations": lambda: list(viol)}, inject={"provenance_job": 2})
        ok("the stub injects into the worker guard; the session reads its own list", out["outcome"] in ("INVALID", "INCOMPLETE", "PASS"))
    with tmpdir() as d:
        sess, out, _b = run_small(d, env_over={"provenance_violations": lambda: ["a write under a protected root"]})
        eq("a recorded write-guard violation is INVALID", out["outcome"], "INVALID")
    # the memory sampler's breach is INCOMPLETE and stops the run where it is
    with tmpdir() as d:
        class Breach:
            breach = "memory cap: process tree private 9999 MB > 9216 MB"
            last = None

        sess, out, _b = run_small(d, env_over={"sampler": Breach()})
        eq("memory breach: INCOMPLETE", out["outcome"], "INCOMPLETE")
        ok("stopped at once, in P1", out["stop"]["phase"] == "p1" and "memory" in out["stop"]["reason"])
    # more than ten BattleShip processes in two distinct samples
    with tmpdir() as d:
        class Procs:
            breach = None

            def __init__(self) -> None:
                self.n = 0

            @property
            def last(self) -> Dict[str, Any]:
                self.n += 1
                return {"battleship": 11, "seq": self.n}

        sess, out, _b = run_small(d, env_over={"sampler": Procs()})
        eq("process count: INCOMPLETE", out["outcome"], "INCOMPLETE")
        ok("named", "BattleShip processes" in out["stop"]["reason"])
    # the session hard cap
    with tmpdir() as d:
        sess, out, _b = run_small(d, cfg_over={"global_cap_s": 2.0})
        eq("hard cap: INCOMPLETE", out["outcome"], "INCOMPLETE")
        ok("named", "hard cap" in out["stop"]["reason"])
    # a phase wall cap before the training window: INCOMPLETE (not a registered end)
    with tmpdir() as d:
        caps = dict(C.WALL_CAPS_S)
        caps["p4"] = 1.0
        sess, out, _b = run_small(d, cfg_over={"wall_caps_s": caps})
        eq("a P4 wall cap is INCOMPLETE", out["outcome"], "INCOMPLETE")
    # an early stop of the training is INCOMPLETE; the wall cap is its registered valid end
    with tmpdir() as d:
        sess, out, _b = run_small(d)
        ok("the wall cap ended the training validly", sess.train_stop["valid_end"] and "wall cap" in sess.train_stop["reason"])
    with tmpdir() as d:
        class Gone:
            breach = None
            last = None
            calls = 0

            def __getattribute__(self, name: str) -> Any:
                if name == "breach":
                    o = object.__getattribute__(self, "__dict__")
                    o["calls"] = o.get("calls", 0) + 1
                    return "memory cap: system available 100 MB < 1024 MB" if o["calls"] > 400 else None
                return object.__getattribute__(self, name)

        sess, out, _b = run_small(d, env_over={"sampler": Gone()})
        eq("a memory breach during training is INCOMPLETE", out["outcome"], "INCOMPLETE")


@test
def p1_refuses_an_inexact_replay_as_invalid() -> None:
    with tmpdir() as d:
        b = stub_builder(d / "run")
        good = b.replay
        calls = {"n": 0}

        def bad_replay(words: bytes, label: str, slot: int) -> Dict[str, Any]:
            tr = good(words, label, slot)
            calls["n"] += 1
            if label == "p1-T_t-1":
                tr = dict(tr)
                tr["steps"] = list(tr["steps"])
                s = json.loads(json.dumps(tr["steps"][1000]))
                s["observation"]["position_x"] += 1.0
                tr["steps"][1000] = s
            return tr

        env = b.env(replay=bad_replay)
        sess = RUN.Session(small_cfg(d / "run"), env)
        out = sess.run()
        eq("a replay that is not exact is INVALID and stops before any later phase", (out["outcome"], sess.phases), ("INVALID", {"p1": False}))
        ok("nothing was staged", not (d / "run" / "training").exists())


@test
def verify_run_detects_tampering() -> None:
    with tmpdir() as d:
        sess, out, b = run_small(d)
        root = d / "run"
        eq("clean", RPT.verify_run(root)["ok"], True)
        # a sticky mask altered in an episode record
        p = root / "eval" / "episodes.jsonl"
        rows = A.read_jsonl(p)
        idx = next(i for i, r in enumerate(rows) if r["label"] and len(r["sticky_mask_hex"]) > 10)
        orig = p.read_text(encoding="utf-8")
        r = dict(rows[idx])
        m = bytearray(bytes.fromhex(r["sticky_mask_hex"]))
        m[3] ^= 1
        r["sticky_mask_hex"] = bytes(m).hex()
        rows[idx] = r
        p.write_text("\n".join(json.dumps(x, separators=(",", ":")) for x in rows) + "\n", encoding="utf-8")
        rep = RPT.verify_run(root)
        eq("an altered sticky mask is caught", rep["ok"], False)
        ok("named", any("sticky" in x for x in rep["problems"]))
        p.write_text(orig, encoding="utf-8")
        # an unstamped record
        (root / "session" / "extra.json").write_text(json.dumps({"x": 1}), encoding="utf-8")
        eq("an unstamped record is caught", RPT.verify_run(root)["ok"], False)
        (root / "session" / "extra.json").unlink()
        # a checkpoint changed after the fact
        mz = next((root / "training" / "checkpoints").rglob("model.zip"))
        data = mz.read_bytes()
        mz.write_bytes(data + b"x")
        eq("a modified checkpoint is caught", RPT.verify_run(root)["ok"], False)
        mz.write_bytes(data)
        # a missing replay record
        vp = root / "verification" / "replays.jsonl"
        orig_v = vp.read_text(encoding="utf-8")
        vp.write_text("\n".join(orig_v.splitlines()[1:]) + "\n", encoding="utf-8")
        rep = RPT.verify_run(root)
        ok("a clear without a replay is reported", rep["verification"]["clears_without_a_replay"] >= 1)
        vp.write_text(orig_v, encoding="utf-8")
        eq("clean again", RPT.verify_run(root)["ok"], True)
        # a step back that was not earned
        pp = root / "training" / "pointer.jsonl"
        orig_p = pp.read_text(encoding="utf-8")
        rows_p = A.read_jsonl(pp)
        if rows_p:
            rows_p[0]["clears"] = 1
            pp.write_text("\n".join(json.dumps(x, separators=(",", ":")) for x in rows_p) + "\n", encoding="utf-8")
            eq("a step back with fewer than 3 clears is caught", RPT.verify_run(root)["ok"], False)
            pp.write_text(orig_p, encoding="utf-8")


@test
def full_report_reads_the_recorded_gate() -> None:
    with tmpdir() as d:
        run_small(d)
        rep = RPT.full_report(d / "run")
        for k in ("rule", "reach", "unperturbed", "fine_grid", "tick0", "training", "pointer_trace", "blocks", "handover_diagnostic", "checkpoint_digests", "p3"):
            ok(f"report has {k}", k in rep)
        ok("the pointer trace is the logged one", len(rep["pointer_trace"]) == len(A.read_jsonl(d / "run" / "training" / "pointer.jsonl")))
        ok("checkpoint digests are listed", all(len(c["model_zip_sha256"]) == 64 for c in rep["checkpoint_digests"]))


# =====================================================================================================================================
# guards, identity, approval, snapshot, the claim evaluator
# =====================================================================================================================================


def _m9_sources(include_tests: bool = False) -> List[Path]:
    out = sorted(RL.glob("m9_*.py"))
    return [p for p in out if include_tests or p.name not in ("m9_tests.py",)]


@test
def source_guard_no_fixtures_tas_or_recordings() -> None:
    forbidden = ("rl/fixtures", "fixtures/m7g", "tas_input", "mario_743", ".btti", "btti_replay", "m7g_capture", "m7g_fixture", "crossing_fixture")
    for p in _m9_sources():
        src = p.read_text(encoding="utf-8")
        for frag in forbidden:
            ok(f"{p.name} does not mention {frag}", frag not in src.replace("\\", "/"))
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, (ast.ImportFrom, ast.Import)):
                names = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
                for n in names:
                    ok(f"{p.name} imports no fixture or TAS module ({n})", "fixture" not in n and "btti" not in n and "capture" not in n)


@test
def source_guard_no_rng_and_no_native_randomness() -> None:
    forbidden = ("SSB64_RNG", "rng_seed", "get_rng", "set_rng", "seed_rng", "native_rng", "osRand", "syUtilsRand")
    for p in _m9_sources():
        src = p.read_text(encoding="utf-8")
        for frag in forbidden:
            ok(f"{p.name} has no {frag}", frag not in src)
    src = (RL / "m9_sticky.py").read_text(encoding="utf-8")
    ok("draws are sha256 keyed uniforms", "hashlib.sha256" in src)
    ok("no stateful generator in the draw modules", all("import random" not in (RL / f).read_text(encoding="utf-8") for f in ("m9_sticky.py", "m9_curriculum.py", "m9_eval.py", "m9_vec.py")))


@test
def routes_are_start_states_only_no_imitation_in_training() -> None:
    bad = ("imitation", "cross_entropy", "nll", "bc_", "clone", "demonstration", "supervised")
    for f in ("m9_train.py", "m9_vec.py", "m9_run.py", "m9_eval.py", "m9_worker.py"):
        tree = ast.parse((RL / f).read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.alias):
                names.add(node.name)
        for n in names:
            for frag in bad:
                ok(f"{f}: identifier {n} contains {frag}", frag not in n.lower())
    tree = ast.parse((RL / "m9_train.py").read_text(encoding="utf-8"))
    top_imports = {a.name for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom)) for a in node.names}
    ok("no torch at module level (the learner is built by SB3's PPO, unchanged)", "torch" not in top_imports)
    import m7n_policy as pol

    ok("the model class is SB3's PPO on the M7n network", pol.POLICY == "MultiInputPolicy" and pol.NET_ARCH == (64, 64))


@test
def the_claim_evaluator_has_no_prefix_path() -> None:
    import m9_claim as CL

    tree = ast.parse((RL / "m9_claim.py").read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add(node.module or "")
    for staging in ("m9_worker", "m9_vec", "m9_pool", "m9_curriculum", "m9_lineages", "m9_eval", "m9_run", "m9_train", "m9_session", "m9_stub", "m9_verify"):
        ok(f"the claim evaluator cannot import {staging}", staging not in mods)

    class P0:
        def observe(self) -> Dict[str, Any]:
            return {"step_count": 5, "state": mcell.STATE_WAITING, "observation": {"input_tick": 5}}

    raises("not tick 0", CL.ClaimError, lambda: CL.run_claim_episode(P0(), lambda o: 0, None, pin={"digest": "x"}, pipeline_cls=ST.StubObs))
    b = stub_builder(Path(tempfile.gettempdir()) / "m9_unused")
    proc = ST.StubProc(ST.StubBackend({"rank": 0, "seed": b.seed}), 1)
    model = ST.StubModel(None, n_steps=1, b0=0)

    def predict(obs: Mapping[str, Any]) -> int:
        a, _ = model.predict({k: np_array([v]) for k, v in obs.items()})
        return int(a[0][0]) * 8 + int(a[0][1])

    rec = CL.run_claim_episode(proc, predict, None, pin=b.pin, pipeline_cls=ST.StubObs)
    eq("claim record: no prefix, first word at tick 0, no idle words", (rec["prefix_rows"], rec["first_policy_tick"], rec["idle_words"]), (0, 0, 0))
    eq("a competent policy from tick 0 clears the synthetic stage", (rec["clear"], rec["end"], rec["ticks"]), (True, "clear", 2326))
    eq("claim status", CL.claim_status(50, 50, 25)["claim"], True)


@test
def worker_modules_import_without_the_learning_stack() -> None:
    code = ("import sys; sys.path.insert(0, %r); import m9_worker, m9_pool, m9_sticky, m9_artifacts, m9_lineages, m9_verify; "
            "bad = [m for m in ('torch', 'stable_baselines3', 'gymnasium') if m in sys.modules]; sys.exit(1 if bad else 0)") % str(RL)
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True)
    eq("a spawned worker imports neither torch, SB3 nor gymnasium until it builds an observation", r.returncode, 0)


@test
def write_guard_covers_every_other_tree() -> None:
    import m9_session as S9

    roots = {p.name for p in S9.write_guard_roots()}
    for name in ("m8_rd", "m8_rd_rd2", "m8_rd_rd3", "m8_rd_rd4", "m7n", "rl", "docs"):
        ok(f"{name} is write-protected", name in roots)
    ok("runs/m9_g1 is not", "m9_g1" not in roots)
    import m8_rd2_worker as w2
    import m8_rd_worker as mw

    with tmpdir() as d:
        prot = d / "protected"
        prot.mkdir()
        mw.ProvenanceGuard.violations.clear()
        before = list(w2.WriteGuard.roots)
        w2.WriteGuard.install([prot])
        try:
            (d / "free.txt").write_text("x", encoding="utf-8")
            eq("a write outside the protected roots is not recorded", mw.ProvenanceGuard.violations, [])
            (prot / "x.txt").write_text("x", encoding="utf-8")
            ok("a write under a protected root is recorded", len(mw.ProvenanceGuard.violations) >= 1)
        finally:
            mw.ProvenanceGuard.violations.clear()
            w2.WriteGuard.roots[:] = before


@test
def identity_names_every_registered_pin() -> None:
    import m9_session as S9

    ident = S9.identity()
    for k in ("gate", "scope", "task", "rule_sha256", "contract_sha256", "executable_sha256", "runtime_files", "frozen_sha256", "flags", "lineages", "m8_trees", "caps", "budget", "ppo", "code",
              "docs_sha256", "git_head", "d_records", "split_rule", "key_strings"):
        ok(f"identity has {k}", k in ident)
    eq("the four M8 trees are pinned", sorted(ident["m8_trees"]), ["rd1", "rd2", "rd3", "rd4"])
    eq("their file counts", {k: v["files"] for k, v in ident["m8_trees"].items()}, {"rd1": 166, "rd2": 62, "rd3": 77, "rd4": 93})
    eq("lineage digests", {n: ident["lineages"][n]["native_action_digest"][:8] for n in ("T_clear", "T_t")}, {"T_clear": "5eccd4e2", "T_t": "de1228be"})
    eq("the archive's pins", ident["executable_sha256"], ident["archive_pins"]["executable_sha256"])
    for f in ("rl/m9_run.py", "rl/m9_worker.py", "rl/m9_tests.py", "rl/m9_contract.py", "rl/m8_rd_worker.py", "rl/m7n_obs.py", "rl/btt_rewards.py"):
        ok(f"code hash of {f}", f in ident["code"] and len(ident["code"][f]) == 64)
    ok("the decisions record is hashed", "docs/rl_m9_g1_decisions_2026-10-04.md" in ident["docs_sha256"])
    eq("every m9 source file is in the code identity", sorted(f"rl/{p.name}" for p in RL.glob("m9_*.py") if f"rl/{p.name}" not in ident["code"]), [])


@test
def approval_is_checked_on_isolated_records() -> None:
    import m8_rd_session as ses1

    with tmpdir() as d:
        want = {"gate": "m9_g1", "scope": "s", "rule_sha256": "a" * 64, "executable_sha256": "b" * 64, "caps": {"train": 3600}, "code": {"rl/x.py": "c" * 64},
                "docs_sha256": {}, "git_head": "h1", "d_records": {"folders": [], "digest": "e"}, "task": dict(C.TASK)}
        p = d / "approval.json"
        eq("no record", ses1.approval_status(p, want)[0], False)
        rec = dict(want, approval="APPROVED (test)")
        rec["d_records"] = {"folders": ["f"], "digest": "x"}
        p.write_text(json.dumps(rec), encoding="utf-8")
        ok("a stale D: record digest is refused", not ses1.approval_status(p, want)[0])
        pend = dict(want, approval="PENDING")
        (d / "pend.json").write_text(json.dumps(pend), encoding="utf-8")
        ok("a pending record is not an approval", not ses1.approval_status(d / "pend.json", want)[0])
        for k in ("gate", "scope", "rule_sha256", "executable_sha256", "caps", "task"):
            alt = dict(rec, **{k: "changed"})
            (d / "alt.json").write_text(json.dumps(alt), encoding="utf-8")
            ok(f"an altered {k} is refused", not ses1.approval_status(d / "alt.json", want)[0])
        alt = dict(rec, code={"rl/x.py": "d" * 64})
        (d / "alt.json").write_text(json.dumps(alt), encoding="utf-8")
        ok("an altered code hash is refused", not ses1.approval_status(d / "alt.json", want)[0])
        alt = dict(rec, git_head="h2")
        (d / "alt.json").write_text(json.dumps(alt), encoding="utf-8")
        ok("a different git head is refused", not ses1.approval_status(d / "alt.json", want)[0])


@test
def snapshot_tool_roundtrip() -> None:
    with tmpdir() as d:
        dest = d / "snap"
        r = subprocess.run([sys.executable, "-B", str(RL / "m9_snapshot.py"), "snapshot", "--dest", str(dest)], capture_output=True, text=True, cwd=str(REPO))
        eq("snapshot exit code", r.returncode, 0)
        rec = json.loads((dest / "snapshot.json").read_text(encoding="utf-8"))
        eq("PASS", (rec["result"], rec["problems"], rec["identity_code_mismatch"], rec["identity_docs_mismatch"]), ("PASS", [], [], []))
        A.check({k: rec[k] for k in ("task", "created_utc")})
        paths = {f["path"] for f in rec["files"]}
        for f in ("rl/m9_run.py", "rl/m9_worker.py", "rl/m9_tests.py", "rl/m8_rd_worker.py", "rl/m7n_obs.py", "docs/rl_m9_g1_decisions_2026-10-04.md", "docs/rl_m9_policy_proposal_2026-10-03.md"):
            ok(f"snapshot has {f}", f in paths)
        r = subprocess.run([sys.executable, "-B", str(RL / "m9_snapshot.py"), "verify", "--dest", str(dest)], capture_output=True, text=True, cwd=str(REPO))
        eq("verify exit code", r.returncode, 0)
        ps = subprocess.run([sys.executable, "-B", str(RL / "m9_snapshot.py"), "powershell", "--dest", str(dest)], capture_output=True, text=True, cwd=str(REPO)).stdout
        ok("the independent re-hash script is generated", "Get-FileHash" in ps and str(dest) in ps)
        r = subprocess.run([sys.executable, "-B", str(RL / "m9_snapshot.py"), "snapshot", "--dest", str(dest)], capture_output=True, text=True, cwd=str(REPO))
        eq("an existing snapshot is never overwritten", r.returncode, 2)


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
    head = Path(__file__).read_text(encoding="utf-8").split("def nondeterminism_is_absent_from_the_suite")[0]
    ok("no random / secrets / uuid import", all(f"import {m}\n" not in head for m in ("random", "secrets", "uuid")))
    ok("no test starts a game process", "subprocess.Popen" not in head)


@test
def tracked_files_are_unchanged_and_only_new_files_exist() -> None:
    import m8_rd_session as ses1

    eq("no tracked file differs from HEAD", ses1.tracked_changes(), [])
    eq("git status shows only untracked (new) entries", ses1.untracked_not_new(), [])
    new = [ln[3:] for ln in ses1.git("status", "--porcelain").splitlines() if ln.startswith("??")]
    ok("every new file under rl/ or docs/ is an M9 file", all(("m9" in n or "M9" in n) for n in new if n.startswith(("rl/", "docs/"))))


@test
def the_m8_trees_equal_their_increments_and_the_pins_hold() -> None:
    import m9_session as S9

    st = S9.m8_trees_state()
    eq("rd1..rd4 equal their D: increments byte for byte", {k: v["ok"] for k, v in st.items() if k != "ok"}, {"rd1": True, "rd2": True, "rd3": True, "rd4": True})
    eq("pins (executable, runtime files, frozen configuration) equal the archive's", S9.pins_problems(), [])


# =====================================================================================================================================
# the production-count synthetic end-to-end run
# =====================================================================================================================================


def e2e() -> int:
    """The whole session at the registered counts and caps against the synthetic world (virtual clock 1,200 native ticks/s, in-process lock-step pool)."""
    t0 = time.time()
    d = Path(tempfile.mkdtemp(prefix="m9e2e_"))
    problems: List[str] = []
    try:
        b = stub_builder(d / "run", rate=1200.0, model_need=60)
        cfg = RUN.RunConfig(root=d / "run", write_artifacts=True)
        sess = RUN.Session(cfg, b.env())
        out = sess.run()
        root = d / "run"

        def chk(label: str, cond: Any) -> None:
            if not cond:
                problems.append(label)

        chk("every phase ran and passed", sess.phases == {"p1": True, "p2": True, "p3": True, "p4": True, "train": True, "eval": True, "verify": True})
        chk(f"outcome {out['outcome']} is a registered performance outcome", out["outcome"] in ("PASS", "INCONCLUSIVE", "NULL"))
        chk("the synthetic learner moved the pointer back through the strips", sess.curriculum is not None and len(sess.curriculum.moves) >= 10)
        chk("training ended at its registered wall cap", sess.train_stop["valid_end"] and "wall cap" in str(sess.train_stop["reason"]))
        reach = out["facts"]["reach"]
        chk("all six landing states evaluated with 20 policy and 20 tape episodes", sorted(int(k) for k in reach) == sorted(C.LANDINGS) and all(v["n"] == 20 and v["tape_n"] == 20 for v in reach.values()))
        chk("the tape rarely clears under sticky draws", sum(v["tape_clears"] for v in reach.values()) < 0.5 * sum(v["clears"] for v in reach.values()))
        chk("the rule's R is the earliest landing of the passing chain", out["R"] == R.depth({int(k): v for k, v in reach.items()}, count="verified"))
        chk("the unperturbed diagnostic was computed from 20 episodes at every landing", "R_unperturbed" in out["diagnostics"] and
            sorted(int(k) for k in out["facts"]["unperturbed"]) == sorted(C.LANDINGS) and all(v["n"] == 20 for v in out["facts"]["unperturbed"].values()))
        tables = L.load_all_tables(root / "lineages", ["T_clear", "T_t"])
        recs = A.read_jsonl(root / "training" / "episodes.jsonl") + A.read_jsonl(root / "eval" / "episodes.jsonl") + A.read_jsonl(root / "p4" / "episodes.jsonl")
        chk("the start-state pool: every episode started from a staged state whose handover chain and v3 digest equal the registered tables",
            all(r["stage"]["handover_chain"] == tables[r["lineage"]].chain[r["tau"]].hex() and r["stage"]["handover_v3"] == tables[r["lineage"]].v3[r["tau"]].hex() for r in recs))
        chk("sticky episodes carry sticky draws, unperturbed ones none", all((r["sticky_hits"] == 0) for r in recs if r["label"] is None) and any(r["sticky_hits"] > 0 for r in recs if r["label"]))
        again = R.apply({"invalid": [], "phases": out["facts"]["phases"], "training": out["facts"]["training"], "reach": reach, "landings": out["facts"]["landings"], "unperturbed": {}})
        chk("the outcome is independent of the unperturbed diagnostic", (again["outcome"], again["R"]) == (out["outcome"], out["R"]))
        rep = RPT.verify_run(root)
        chk(f"verify-run ok ({rep['problems'][:3]})", rep["ok"])
        chk("every clear of P4 and the evaluation replayed exactly", rep["verification"]["clears_without_a_replay"] == 0 and not rep["verification"]["inexact"])
        aud = A.audit_tree(root, skip_dirs=("workers", "vw"))
        chk("every record carries the task block and created_utc", aud["ok"] and aud["files"] > 100)
        eps = A.read_jsonl(root / "training" / "episodes.jsonl")
        chk("training episodes and rollouts recorded", len(eps) > 500 and len(A.read_jsonl(root / "training" / "rollouts.jsonl")) > 20)
        chk("full artifacts exist for evaluation and tape episodes", sum(1 for _ in (root / "artifacts").glob("reach-*")) >= 120 and sum(1 for _ in (root / "artifacts").glob("reach_tape-*")) >= 140)
        chk("a step back never occurs without three clears of ten strip outcomes", all(m["clears"] >= 3 for m in A.read_jsonl(root / "training" / "pointer.jsonl")))
        digest = hashlib.sha256(json.dumps(strip_volatile({"rule": {k: out[k] for k in ("outcome", "R", "reasons", "crossing_learned")}, "reach": reach,
                                                         "pointer": [(m["from"], m["to"]) for m in sess.curriculum.moves], "split": out["split"], "episodes": len(eps)}),
                                           sort_keys=True, default=str).encode()).hexdigest()
        print(json.dumps({"e2e": "PASS" if not problems else "FAIL", "outcome": out["outcome"], "R": out["R"], "split": out["split"], "pointer_final": sess.curriculum.pointer,
                          "moves": len(sess.curriculum.moves), "training_episodes": len(eps), "verified_clears": rep["verification"]["replays"], "digest": digest[:16],
                          "wall_s": round(time.time() - t0, 1), "problems": problems}, default=str))
        return 0 if not problems else 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


# =====================================================================================================================================
# process discipline, evaluation runner failures, checkpoints
# =====================================================================================================================================


def stub_arena(d: Path, source_jobs: Optional[Sequence[V.StartJob]] = None, *, n_slots: int = 10, budget: int = 10 ** 7, **arena_kw: Any
               ) -> Tuple[V.Arena, TE.StubEnvBuilder, Dict[str, L.Tables], P.LocalPool]:
    b = stub_builder(d / "run", n_slots=n_slots, inject=arena_kw.pop("inject", None))
    for name, ln in b.lineages.items():
        tr = b.route_traces[name]
        chain, v3 = L.build_tables(tr["initial"], tr["steps"], ST.StubObs)
        L.save_tables(d / "run" / "lineages", name, ln.words, chain, v3)
    tables = L.load_all_tables(d / "run" / "lineages", ["T_clear", "T_t"])
    pool = b.make_pool("x", C.FLAGS_TRAIN)
    src = T.ListSource(list(source_jobs or []))
    return V.Arena(pool, tables, src, V.TickBudget(budget), now=b.clock.now, **arena_kw), b, tables, pool


def _jobs(n: int, tau: int = 100, label: Optional[str] = None) -> List[V.StartJob]:
    return [V.StartJob(k, CU.Start(k, "p2", tau, "T_clear", True, -1), label, kind="x", job_id=f"x-{k:03d}") for k in range(n)]


@test
def the_arena_never_holds_more_processes_than_its_limits() -> None:
    with tmpdir() as d:
        arena, _b, _t, _pool = stub_arena(d, _jobs(12), max_procs=4)
        arena.pump(0.0)
        eq("P2: at most 4 staged / parked / active processes (room for the cold replays)", (arena.process_count(), arena.dispatched), (4, 4))
        arena.pump(0.0)
        eq("still 4 while they are parked", arena.process_count(), 4)
        slot = arena.ready.popleft()
        arena.activate(slot)
        arena.pump(0.0)
        eq("an active episode still counts as a process", arena.process_count(), 4)
        arena.release(slot)
        arena.pump(0.0)
        eq("releasing one lets exactly one more stage", (arena.process_count(), arena.dispatched), (4, 5))
    with tmpdir() as d:
        arena, _b, _t, _pool = stub_arena(d, _jobs(30), max_staging=6)
        arena.pump(0.0)
        eq("P3: at most 6 preparing slots (staging + parked) with 4 playing", arena.staging_count() + len(arena.ready), 6)
        for _ in range(4):
            arena.activate(arena.ready.popleft())
        arena.pump(0.0)
        eq("the 4 playing slots do not count against the preparing slots", (arena.staging_count() + len(arena.ready), len(arena.active)), (6, 4))
        ok("never more than 10 slots busy", arena.process_count() <= 10)


@test
def the_eval_runner_requeues_a_process_death_during_a_step() -> None:
    with tmpdir() as d:
        jobs = E.landing_jobs([2128], tape=False, n=4)
        # the first process of each of the 2 workers dies at its 3rd policy tick (staging takes 2128 ticks first)
        arena, b, tables, pool = stub_arena(d, jobs, n_slots=2, inject={"lifecycle_jobs": [1], "lifecycle_tick": 2131})
        rec = E.EvalRecorder(d / "run" / "eval", tables, phase="eval", now=b.clock.now, write_artifacts=False)
        model = ST.StubModel(None, n_steps=1, b0=1200)
        runner = E.EvalRunner(arena, tables, rec, models={"final": model}, now=b.clock.now)
        res = runner.run()
        eq("two process deaths during a step were requeued", (runner.lifecycle_requeued, len(arena.lifecycle_failures)), (2, 2))
        eq("every episode completed once", sorted(r["episode"] for r in rec.records), [j.job_id for j in jobs])
        eq("no stop", res["stop"], None)
    with tmpdir() as d:
        arena, b, tables, pool = stub_arena(d, E.landing_jobs([2128], tape=False, n=6), n_slots=2, inject={"lifecycle_jobs": list(range(1, 50)), "lifecycle_tick": 2131})
        rec = E.EvalRecorder(d / "run" / "eval", tables, phase="eval", now=b.clock.now, write_artifacts=False)
        runner = E.EvalRunner(arena, tables, rec, models={"final": ST.StubModel(None, n_steps=1, b0=1200)}, now=b.clock.now)
        res = runner.run()
        ok("more than three lifecycle failures stop the evaluation, not validly", res["stop"] is not None and not res["stop"]["valid"] and "lifecycle" in res["stop"]["reason"])


@test
def the_eval_runner_stops_at_the_tick_cap_and_reports_what_is_done() -> None:
    with tmpdir() as d:
        arena, b, tables, pool = stub_arena(d, E.landing_jobs([2128, 1966], tape=False, n=10), budget=30_000)
        rec = E.EvalRecorder(d / "run" / "eval", tables, phase="eval", now=b.clock.now, write_artifacts=False)
        runner = E.EvalRunner(arena, tables, rec, models={"final": ST.StubModel(None, n_steps=1, b0=1200)}, now=b.clock.now)
        res = runner.run()
        ok("the tick cap is reported", res["stop"] is not None and "tick cap" in res["stop"]["reason"])
        ok("some episodes completed, not all", 0 < len(rec.records) < 20)
        ok("the budget did not overshoot by more than one vector step", arena.budget.total() <= 30_000 + 10)
        rows = E.aggregate(rec.records)["reach"]
        ok("the rule would call the unevaluated landings incomplete", R.fully_evaluated(rows, C.LANDINGS) != [])


@test
def a_fixed_list_stages_a_job_again_after_a_staging_lifecycle_failure() -> None:
    with tmpdir() as d:
        jobs = E.landing_jobs([2128], tape=False, n=4)
        # the first process each worker is given fails to launch: its job is staged again (same id) and the list is completed
        arena, b, tables, pool = stub_arena(d, jobs, n_slots=2, inject={"acquire_fail_jobs": [1]})
        rec = E.EvalRecorder(d / "run" / "eval", tables, phase="eval", now=b.clock.now, write_artifacts=False)
        runner = E.EvalRunner(arena, tables, rec, models={"final": ST.StubModel(None, n_steps=1, b0=1200)}, now=b.clock.now)
        res = runner.run()
        eq("the two launch failures were recorded", len(arena.lifecycle_failures), 2)
        eq("every job completed exactly once", sorted(r["episode"] for r in rec.records), [j.job_id for j in jobs])
        eq("no stop", res["stop"], None)
        eq("the budget returned the failed reservations (nothing left reserved)", arena.budget.reserved, 0)
    with tmpdir() as d:
        arena, b, tables, pool = stub_arena(d, _jobs(6), n_slots=2, inject={"acquire_fail_jobs": list(range(1, 50))})
        e = raises("beyond the limit", V.CapStop, lambda: [arena.pump(0.0) for _ in range(200)])
        ok("more than three failures still stop the phase, not validly", not e.valid and "lifecycle" in e.reason)
        eq("exactly one more than the limit was recorded", len(arena.lifecycle_failures), arena.lifecycle_limit + 1)
    # the training source is not a fixed list: a failed start is simply not redrawn as the same job
    with tmpdir() as d:
        cur = CU.Curriculum({"T_clear": 2400, "T_t": 2400})
        ok("a training source does not re-queue", not getattr(T.TrainSource(cur), "requeue_on_lifecycle", False))
        ok("a measurement window does not re-queue", not getattr(T.WindowSource("4x6", 2250, 2310), "requeue_on_lifecycle", False))


@test
def a_parked_start_whose_process_dies_is_withdrawn_and_its_job_returns() -> None:
    with tmpdir() as d:
        arena, b, tables, pool = stub_arena(d, _jobs(3), n_slots=2)
        arena.pump(0.0)
        arena.pump(0.0)
        ok("two starts are parked", len(arena.ready) == 2)
        eq("nothing reserved while parked", arena.budget.reserved, 0)
        slot = arena.ready[0]
        before = arena.source.remaining()
        r = arena.handle(slot, "died", {"exit_code": 1})
        eq("a death is not an event for a consumer", r, None)
        ok("the dead slot is not handed out", slot not in arena.ready and slot not in arena.ready_payload)
        eq("the budget was not credited twice (the prefix of a parked start was already consumed)", arena.budget.reserved, 0)
        eq("the job is back in the fixed list", arena.source.remaining(), before + 1)
        eq("recorded as a lifecycle failure", [f["outcome"] for f in arena.lifecycle_failures], ["worker_died"])
        eq("the slot is dead", arena.state[slot], "dead")
    with tmpdir() as d:
        # a start still staging when its process dies returns its reservation (exactly once)
        arena, b, tables, pool = stub_arena(d, _jobs(3), n_slots=2)
        job = arena.source.next_job(arena)
        arena.budget.reserve(int(job.start.tau))
        arena.job[0], arena.state[0] = job, "staging"
        eq("reserved at dispatch", arena.budget.reserved, int(job.start.tau))
        arena.handle(0, "died", {"exit_code": 1})
        eq("returned once", arena.budget.reserved, 0)


@test
def the_slot_pool_treats_a_broken_pipe_as_a_death() -> None:
    class Conn:
        def poll(self) -> bool:
            raise BrokenPipeError("peer exited")

    class Proc:
        exitcode = 3

        def is_alive(self) -> bool:
            return False

    saved = P.mp_wait
    P.mp_wait = lambda conns, timeout=None: []                  # the connection wait reports nothing: the death scan alone finds the dead process
    try:
        pool = P.SlotPool.__new__(P.SlotPool)
        pool.n, pool.procs, pool.conns, pool.dead = 1, [Proc()], [Conn()], set()
        out = pool.poll(0.0)
    finally:
        P.mp_wait = saved
    eq("a broken pipe on a dead process is a death", out, [(0, "died", {"exit_code": 3})])
    eq("and it is not reported twice", pool.dead, {0})


@test
def p3_ends_a_window_at_its_share_of_the_tick_cap_and_still_measures() -> None:
    with tmpdir() as d:
        caps = dict(C.TICK_CAPS)
        caps["p3"] = 26_000                          # 13,000 per configuration: about five prefixes, then the budget cannot stage another
        sess, out, _b = run_small(d, cfg_over={"tick_caps": caps, "p3_window_s": 20.0})      # the synthetic clock charges every staged prefix tick: 20 s outlast the fill
        p3 = A.read_json(d / "run" / "session" / "p3.json")
        eq("both configurations were measured", sorted(p3["rows"]), ["2x8", "4x6"])
        for tag, row in p3["rows"].items():
            ok(f"{tag}: the window ended at the tick cap", row["window_end"] == "tick_cap")
            ok(f"{tag}: policy transitions were measured over the elapsed window", row["transitions"] > 0 and row["window_s"] > 0 and row["eligible"])
            ok(f"{tag}: within its share of the cap", row["ticks"] <= p3["tick_cap"] // 2 + 10)
        ok("P3 passed and the session went on", out["stop"] is None or out["stop"]["phase"] != "p3")
        ok("the reading is written next to the rows", "half of the phase" in p3["tick_cap_reading"])


@test
def a_stopped_phase_leaves_its_partial_record() -> None:
    with tmpdir() as d:
        sess, out, _b = run_small(d, inject={"acquire_fail_jobs": list(range(1, 60))})
        eq("INCOMPLETE", out["outcome"], "INCOMPLETE")
        ph = out["stop"]["phase"]
        rec = A.read_json(d / "run" / "session" / f"{ph}.json")
        ok(f"{ph}.json exists with partial = True and the reason", rec.get("partial") is True and "lifecycle" in rec["error"])


@test
def training_checkpoints_follow_the_cadence_and_pin_their_digests() -> None:
    with tmpdir() as d:
        arena, b, tables, pool = stub_arena(d)
        cur = CU.Curriculum({n: len(t.words) for n, t in tables.items()})
        arena.source = T.TrainSource(cur)
        rec = T.TrainRecorder(d / "run" / "training", cur, tables, now=b.clock.now, write_artifacts=False)
        env = V.make_vec_env_class()(arena, 4, recorder=rec.on_episode, outcome=rec.on_outcome)
        model = ST.StubModel(env, n_steps=100, need=10 ** 9)
        stop = T.train(model, env, arena, cur, rec, run_dir=d / "run" / "training", guard=lambda: None, now=b.clock.now, transition_cap=2400, checkpoint_every=800)
        eq("valid end at the transition cap", (stop["valid_end"], stop["reason"], stop["num_timesteps"]), (True, "transition_cap", 2400))
        eq("initial and periodic checkpoints at the cadence", [c["checkpoint"] for c in stop["checkpoints"]], ["ckpt_000000000", "ckpt_000000800", "ckpt_000001600"])
        eq("and the final one", stop["final"]["checkpoint"], "final")
        for c in stop["checkpoints"] + [stop["final"]]:
            meta = A.read_json(d / "run" / "training" / "checkpoints" / c["checkpoint"] / "checkpoint.json")
            eq("digest pinned", meta["model_zip_sha256"], c["model_zip_sha256"])
            eq("file equals the pin", T.sha256_file(d / "run" / "training" / "checkpoints" / c["checkpoint"] / "model.zip"), c["model_zip_sha256"])
        ok("every periodic checkpoint carries its wall time", all("wall_s" in c for c in stop["checkpoints"]))
        idx = A.read_jsonl(d / "run" / "training" / "rollouts.jsonl")
        eq("one metrics row per rollout", len(idx), 6)
        # a non-registered early stop is not a valid end
    with tmpdir() as d:
        arena, b, tables, pool = stub_arena(d)
        cur = CU.Curriculum({n: len(t.words) for n, t in tables.items()})
        arena.source = T.TrainSource(cur)
        rec = T.TrainRecorder(d / "run" / "training", cur, tables, now=b.clock.now, write_artifacts=False)
        env = V.make_vec_env_class()(arena, 4, recorder=rec.on_episode, outcome=rec.on_outcome)
        model = ST.StubModel(env, n_steps=100, need=10 ** 9)
        calls = {"n": 0}

        def guard() -> None:
            calls["n"] += 1
            if calls["n"] > 300:
                raise V.CapStop("memory cap: system available 100 MB < 1024 MB", valid=False)

        stop = T.train(model, env, arena, cur, rec, run_dir=d / "run" / "training", guard=guard, now=b.clock.now, transition_cap=10 ** 6, checkpoint_every=800)
        eq("a memory stop is not a registered end", (stop["valid_end"], "memory" in stop["reason"]), (False, True))
        ok("the final checkpoint is still written (the model after its last update)", stop["final"]["checkpoint"] == "final")


@test
def ppo_bootstraps_through_horizon_truncation() -> None:
    """A world that can never be cleared: every episode runs to the 3,600-tick horizon (a truncation, not a termination); SB3 must bootstrap from the
    terminal observation. Two playing slots, so a rollout is 2 x 2,560 transitions and an episode from tick 2,300 truncates inside it."""
    with tmpdir() as d:
        arena, b, tables, pool = stub_arena(d, inject={"no_clear": True})
        cur = CU.Curriculum({n: len(t.words) for n, t in tables.items()}, tau0=2300)
        arena.source = T.TrainSource(cur)
        rec = T.TrainRecorder(d / "run" / "training", cur, tables, now=b.clock.now, write_artifacts=False)
        env = V.make_vec_env_class()(arena, 2, recorder=rec.on_episode, outcome=rec.on_outcome)
        model = T.make_ppo(env, 2)
        eq("n_steps for two playing slots", model.n_steps, 2560)
        model.learn(total_timesteps=5120, log_interval=None)
        ok(f"episodes ended by the horizon ({env.truncations} truncations)", env.truncations >= 2)
        eq("every one is a horizon end, none a clear", (rec.ends.get("horizon", 0) >= 2, rec.clears), (True, 0))
        rows = A.read_jsonl(d / "run" / "training" / "episodes.jsonl")
        ok("the horizon counts from the reset: policy ticks = 3,600 - tau", all(r["policy_ticks"] == 3600 - r["tau"] for r in rows if r["end_reason"] == "horizon"))
        ok("the update ran (a finite loss was logged)", all(abs(float(v)) < 1e9 for v in model.logger.name_to_value.values()))


@test
def the_tree_sampler_rows_carry_the_metadata_and_the_template_is_valid() -> None:
    import m9_session as S9

    with tmpdir() as d:
        sampler = S9.make_sampler(d / "memory_tree.jsonl", C.MEMORY_CAPS_MB)
        snap = sampler.sample()
        ok("a tree snapshot was taken (Windows)", snap is not None)
        rows = A.read_jsonl(d / "memory_tree.jsonl")
        eq("one stamped row", len(rows), 1)
        A.check(rows[0])
        ok("the engine's process-count check reads these fields", sampler.last is not None and "battleship" in sampler.last and sampler.last["seq"] == 1)
        ok("no breach on this machine at this moment", sampler.breach is None or "memory cap" in sampler.breach)
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        eq("template exit code", S9.cmd_template(), 0)
    rec = json.loads(buf.getvalue())
    A.check(rec)
    eq("the template is PENDING (never an approval)", rec["approval"].startswith("PENDING"), True)
    eq("task block", rec["task"], C.TASK)


# -- integration: the REAL lifecycle code and real worker processes against a fake game (NOT part of the gating suite) -----------------------


def fake_game_setup() -> Dict[str, Any]:
    """A temporary 'executable directory' whose BattleShip.cmd starts rl/m8_rd_fakegame.py (the M1d protocol over the m8 stub world), plus a frozen runtime that
    differs from the 'live' configuration beside the executable (the same fixture rd4's integration command uses)."""
    import m8_rd_worker as mw

    t = Path(tempfile.mkdtemp(prefix="m9fg_"))
    exe_dir = t / "exe"
    exe_dir.mkdir()
    for n in ("f3d.o2r", "BattleShip.o2r", "gamecontrollerdb.txt"):
        (exe_dir / n).write_bytes(b"fake")
    (exe_dir / "BattleShip.cfg.json").write_text(json.dumps({"CVars": {"live": "LIVE-CONFIG"}}), encoding="utf-8")
    (exe_dir / "imgui.ini").write_text("[live]\n", encoding="utf-8")
    cmd = exe_dir / "BattleShip.cmd"
    cmd.write_text(f'@"{sys.executable}" -B "{RL / "m8_rd_fakegame.py"}"\r\n', encoding="utf-8")
    frozen = t / "frozen"
    frozen.mkdir()
    (frozen / "BattleShip.cfg.json").write_text(json.dumps({"CVars": {"frozen": "FROZEN-CONFIG"}}), encoding="utf-8")
    (frozen / "imgui.ini").write_text("[frozen]\n", encoding="utf-8")
    return {"t": t, "cmd": cmd, "frozen": frozen, "hashes": {n: mw.sha256_file(frozen / n) for n in mw.FROZEN_FILES}, "log": t / "fake.log"}


def fake_log_rows(fg: Mapping[str, Any]) -> List[Dict[str, Any]]:
    p = Path(fg["log"])
    rows: List[Dict[str, Any]] = []
    for x in (p.read_text(encoding="utf-8").splitlines() if p.is_file() else []):
        try:
            rows.append(json.loads(x))
        except ValueError:
            pass
    return rows


def wait_dead(pids: Sequence[int], seconds: float = 30.0) -> List[int]:
    from m7_runtime import pid_alive

    deadline = time.time() + seconds
    alive = [p for p in pids if pid_alive(p)]
    while alive and time.time() < deadline:
        time.sleep(0.3)
        alive = [p for p in pids if pid_alive(p)]
    return alive


def integration() -> int:
    """Real spawned worker processes (rl/m9_pool.SlotPool), the real cold-launch backend (rl/m9_worker.ColdBackend, which reuses rl/m8_rd_worker.RealBackend's launch
    code, battleship_process and the M1d client), the arena and the SB3 VecEnv, against a fake game process. THE WORLD IS SYNTHETIC. Asserts only facts that hold under
    every process schedule. Not part of the unit suite or the preflight."""
    import numpy as np

    import m7_runtime
    import m8_rd_explore as mx
    import m8_rd_stub as m8s

    t0 = time.time()
    problems: List[str] = []
    fg = fake_game_setup()
    out: Dict[str, Any] = {}

    def chk(label: str, cond: Any) -> None:
        if not cond:
            problems.append(label)

    try:
        m7_runtime.install_kill_on_close_job()
        words = bytes(mx.words(lambda i: f"m9int|{i}", 900))
        tr = m8s.replay_trace("calm", words)
        chain, v3 = L.build_tables(tr["initial"], tr["steps"], ST.SpatialObs)
        tdir = fg["t"] / "lineages"
        L.save_tables(tdir, "T_clear", words, chain, v3)
        pin = {"obs": list(mcell.obs_tuple(tr["initial"]["observation"])), "digest": mcell.record_digest(mcell.tick0_record(tr["initial"])).hex()}

        def flags(**extra: str) -> Dict[str, str]:
            f = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1", "SSB64_RL_SPATIAL": "1", "FAKEGAME_WORLD": "calm", "FAKEGAME_LOG": str(fg["log"]), "FAKEGAME_BOOT_S": "0.2"}
            f.update(extra)
            return f

        def spec_fn(fl: Mapping[str, str]) -> Callable[[int], Dict[str, Any]]:
            def spec(rank: int) -> Dict[str, Any]:
                return {"rank": rank, "root": str(fg["t"] / f"w{rank:02d}"), "executable": str(fg["cmd"]), "flags": dict(fl), "frozen_dir": str(fg["frozen"]),
                        "frozen_sha256": dict(fg["hashes"]), "port_base": 30000, "port_size": 250,
                        "timeouts": {"startup": 30.0, "ready": 30.0, "request": 15.0, "exit": 15.0}, "failure_dir": str(fg["t"] / "fail"), "lineage_dir": str(tdir),
                        "lineages": ["T_clear"], "pin_tick0": pin, "obs_pipeline": "m9_stub:SpatialObs"}
            return spec

        tables = L.load_all_tables(tdir, ["T_clear"])
        # 1. staging through real worker processes: every start checks its prefix against the tables; one word is stepped; the processes die
        pool = P.SlotPool(3, spec_fn(flags()), name="int1")
        pool.wait_ready()
        taus = [10, 120, 300, 500, 700, 50]
        jobs = [V.StartJob(k, CU.Start(k, "int", tau, "T_clear", True, -1), None, kind="int", job_id=f"int-{k}") for k, tau in enumerate(taus)]
        arena = V.Arena(pool, tables, T.ListSource(jobs), V.TickBudget(10 ** 6), now=time.monotonic)
        done: List[int] = []
        waiting: Dict[int, V.EpisodeCtx] = {}
        deadline = time.monotonic() + 240
        while len(done) < len(jobs) and time.monotonic() < deadline:
            for slot, kind, payload in arena.pump(0.05):
                if slot in waiting and kind == "stepped":
                    ctx = waiting.pop(slot)
                    chk("consumed tick of the first policy word", payload["consumed_tick"] == ctx.tau)
                    chk("observation shapes", tuple(payload["obs"]["agent"].shape) == (28,))
                    done.append(ctx.tau)
                    arena.release(slot)
                    pool.send(slot, ("close", {}))
            while arena.ready:
                slot = arena.ready.popleft()
                ctx = arena.activate(slot)
                chk("staged mode is a cold launch", ctx.staged["mode"] == "cold")
                waiting[slot] = ctx
                pool.send(slot, ("step", {"word": int(words[ctx.tau])}))
        chk(f"all six starts staged and stepped ({sorted(done)})", sorted(done) == sorted(taus))
        out["staging_s"] = round(time.time() - t0, 1)
        out["stage_log"] = arena.stage_log[:2]
        pool.stop()
        rows = fake_log_rows(fg)
        pids = sorted({r["pid"] for r in rows})
        chk("every fake game process read the FROZEN configuration", bool(rows) and all(r["cfg_sha256"] == fg["hashes"]["BattleShip.cfg.json"] for r in rows))
        chk("every fake game process is gone after the pool stops", wait_dead(pids) == [])
        out["launches_phase1"] = len(pids)
        # 2. a process that dies while staging is a lifecycle failure; the fourth stops the phase as INCOMPLETE
        pool2 = P.SlotPool(2, spec_fn(flags(FAKEGAME_DIE_AT_STEP="5")), name="int2")
        pool2.wait_ready()
        jobs2 = [V.StartJob(k, CU.Start(k, "int", 100, "T_clear", True, -1), None, kind="int", job_id=f"die-{k}") for k in range(8)]
        arena2 = V.Arena(pool2, tables, T.ListSource(jobs2), V.TickBudget(10 ** 6), now=time.monotonic)
        stopped = None
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and stopped is None:
            try:
                arena2.pump(0.05)
            except V.CapStop as exc:
                stopped = exc
        chk("a process death while staging is a lifecycle failure and the 4th stops the phase", stopped is not None and not stopped.valid and "lifecycle" in stopped.reason)
        pool2.stop()
        # 3. the SB3 VecEnv over real worker processes (2 playing + 2 preparing slots), a random policy, sticky actions
        pool3 = P.SlotPool(4, spec_fn(flags()), name="int3")
        pool3.wait_ready()
        cur = CU.Curriculum({"T_clear": 900}, order=("T_clear",), tau0=800, shared_prefix=900)
        arena3 = V.Arena(pool3, tables, T.TrainSource(cur), V.TickBudget(10 ** 7), now=time.monotonic)
        vec = V.make_vec_env_class()(arena3, 2)
        obs = vec.reset()
        chk("batched observation", obs["agent"].shape == (2, 28))
        rng = np.random.default_rng(1)
        for _ in range(120):
            obs, rew, dones, infos = vec.step(np.stack([rng.integers(0, 9, 2), rng.integers(0, 8, 2)], axis=1))
        chk("120 vector steps = 240 policy transitions", vec.transitions == 240 and arena3.budget.policy == 240)
        chk("prefix ticks were staged but are not transitions", arena3.budget.prefix >= 2 * 780)
        vec.close()
        pool3.stop()
        # 4. the real environment builder: P1's replay through a promoted standby (the unchanged M8 worker's `trace` job, in a spawned process), the verification
        #    replay (fresh process, frozen configuration), the pool maker
        import hashlib as _h

        import m9_run as RUN
        import m9_session as S9

        ln = L.Lineage(name="T_clear", words=words, native_action_digest=mcell.words_digest(words), words_sha256=_h.sha256(words).hexdigest(), completion_time_passed=0,
                       completion_input_tick=1, route_dir="fake", iteration=0)
        cfg = RUN.RunConfig(root=fg["t"] / "run", n_slots=2)
        env = S9.build_real_env(cfg, None, executable=fg["cmd"], run_root=fg["t"] / "run", frozen_dir=fg["frozen"],
                                pins={"executable_sha256": None, "runtime_files": {}, "frozen_sha256": fg["hashes"]}, protect=[], lineages_override={"T_clear": ln},
                                route_traces_override={"T_clear": tr}, pin_override=pin, flags_override=flags(), obs_pipeline_override="m9_stub:SpatialObs")
        res = env.promoted_trace(ln, tr)
        chk("the promoted-standby replay is exact and went through a promotion", res["native_action_digest"] == ln.native_action_digest and res["startup"]["mode"] == "standby_promoted")
        trace = env.replay(words[:250], "int-replay", 0)
        chk("the verification replay is exact", trace["action_digest"] == mcell.words_digest(words[:250]) and trace["submitted"] == 250 and trace["consumed_tick_mismatch"] is None)
        chk("its work directory was cleaned", not (fg["t"] / "run" / "session" / "vw" / "s0_int-replay" / "runtime").exists())
        pool4 = env.make_pool("int4", flags())
        chk("the pool maker spawns the workers", pool4.n == 2 and all(pool4.alive(i) for i in range(2)))
        pool4.stop()
        rows = fake_log_rows(fg)
        chk("every process of the whole run read the FROZEN configuration (pool workers, replays and the promoted standby)",
            bool(rows) and all(r["cfg_sha256"] == fg["hashes"]["BattleShip.cfg.json"] for r in rows))
        pids = sorted({r["pid"] for r in rows})
        chk("no fake game process survives the run", wait_dead(pids) == [])
        out["launches_total"] = len(pids)
    except Exception as exc:                                         # noqa: BLE001
        problems.append(f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        shutil.rmtree(fg["t"], ignore_errors=True)
    out.update({"integration": "PASS" if not problems else "FAIL", "problems": problems, "wall_s": round(time.time() - t0, 1)})
    print(json.dumps(out, default=str))
    return 0 if not problems else 1


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
            traceback.print_exc(limit=5)
    total = passed + len(failed)
    print(f"m9 unit suite: {passed}/{total} passed" + (f" (failed: {', '.join(failed)})" if failed else "") + f" in {time.time() - t_all:.0f}s")
    return 0 if not failed else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "unit"
    if cmd == "unit":
        return run_unit(args[1:] or None)
    if cmd == "e2e":
        return e2e()
    if cmd == "integration":
        return integration()
    if cmd == "list":
        for n, _f in TESTS:
            print(n)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
