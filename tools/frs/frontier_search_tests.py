#!/usr/bin/env python3
"""Zero-tick tests of the frontier continuation search (tools/frs/frontier_search.py). No game process is started: the real lab
import and the real trail-lead probe outputs are read (never written) for the start-rule and prefix checks; the synthetic stub
world (rl/m8_rd_stub) stands in for the game in the round, verification and end-to-end checks; the guard checks run in child
processes (an audit hook cannot be removed). The test process never arms the lab guard and writes only under temporary folders,
which it removes.

    python -B tools/frs/frontier_search_tests.py                 every test
    python -B tools/frs/frontier_search_tests.py real            the real-import checks only (reads <lab root>/import and the probe folder)
    python -B tools/frs/frontier_search_tests.py stub            the synthetic checks only
    python -B tools/frs/frontier_search_tests.py only <name>     the tests whose name contains <name>
    ... [--lab-root DIR] [--probe DIR]                           the lab root and probe folder of the real checks (default C:/BattleShip_lab, newest trail_probe_*)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

assert sys.flags.dont_write_bytecode, "run with python -B"

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RL = REPO / "rl"
sys.path.insert(0, str(RL))
sys.path.insert(0, str(HERE))

import frs_archive as fa  # noqa: E402
import frs_guard as g  # noqa: E402
import frs_run as fr  # noqa: E402
import frs_tests as T  # noqa: E402
import frs_verify as fv  # noqa: E402
import frs_worker as fw  # noqa: E402
import frontier_search as fs  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_stub as stub  # noqa: E402
import trail_probe as tp  # noqa: E402
import trail_probe_tests as tpt  # noqa: E402

# The owner's expectation from the probe record (docs/frs_trail_probe_2026-10-14.md) on the sd2 import: test literals only, never read by the search.
EXPECTED_STARTS = 136
EXPECTED_PER_LEVEL = {"1": 4, "2": 9, "3": 68, "4": 35, "5": 10, "6": 1, "7": 2, "8": 5, "9": 2}
EXPECTED_FRONTIER_TICKS = {8: (1482, 1489), 9: (1816,)}

TESTS: List[Tuple[str, str, Callable[[], Optional[Dict[str, Any]]]]] = []
CREATED: List[Path] = []
LAB = Path(g.DEFAULT_LAB_ROOT)
PROBE: Optional[Path] = None
_REAL: Dict[str, Any] = {}


def real(fn: Callable[[], Optional[Dict[str, Any]]]) -> Callable[[], Optional[Dict[str, Any]]]:
    TESTS.append(("real", fn.__name__, fn))
    return fn


def synthetic(fn: Callable[[], Optional[Dict[str, Any]]]) -> Callable[[], Optional[Dict[str, Any]]]:
    TESTS.append(("stub", fn.__name__, fn))
    return fn


def check(cond: Any, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def tmpdir(tag: str) -> Path:
    p = Path(tempfile.mkdtemp(prefix=f"frontier_{tag}_"))
    CREATED.append(p)
    return p


def read_jsonl(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def real_import() -> Dict[str, Any]:
    """The real import and the real probe outputs, loaded once per test session (read-only)."""
    if not _REAL:
        imp = LAB / "import"
        check((imp / "import_manifest.json").is_file(), f"no lab import at {imp}")
        probe_dir = PROBE or fs.default_probe(LAB)
        check(probe_dir is not None, f"no trail-lead probe output folder under {LAB}")
        lab, meta, R = fs.load_all(LAB)
        probe = fs.read_probe(probe_dir)
        S = fs.build_search_plan(lab, R, probe, fs.Params())
        _REAL.update({"lab": lab, "meta": meta, "R": R, "probe": probe, "S": S})
    return _REAL


# =============================================================================================================================================
# the real import and the real probe outputs (zero native ticks)
# =============================================================================================================================================


@real
def real_start_rule_on_probe_outputs() -> Dict[str, Any]:
    X = real_import()
    lab, R, probe, S = X["lab"], X["R"], X["probe"], X["S"]
    p, beam = S["plan"], S["beam"]
    init = beam.initial()
    arrival = {int(k): int(v) for k, v in R["arrival"].items()}
    check(p["starts"] == len(init) == EXPECTED_STARTS, f"{p['starts']} starts, expected {EXPECTED_STARTS}")
    per = {lv: d["starts"] for lv, d in p["per_level"].items()}
    check(per == EXPECTED_PER_LEVEL, f"starts per level {per}, expected {EXPECTED_PER_LEVEL}")
    for lv, ticks in EXPECTED_FRONTIER_TICKS.items():
        have = sorted({s.tick for s in init if s.level == lv})
        check(all(t in have for t in ticks), f"level {lv}: the probe's frontier states {ticks} are among the starts ({have})")
    check(all(s.level < mcell.TARGETS_TOTAL and s.tick < arrival[s.level] and s.lead == arrival[s.level] - s.tick > 0 for s in init), "every start is strictly ahead at a live level")
    check(all(s.words is not None and len(s.words) == s.tick and s.digest == mcell.words_digest(s.words) for s in init), "a start's words are its tick")
    check(len({s.digest for s in init}) == len(init) and len({s.sid for s in init}) == len(init), "one start per distinct prefix")
    check(all(s.seed is not None and s.key is None and not s.alive() for s in init), "an initial start carries its seed and no key before the native seed")
    check([s.order() for s in init] == sorted(s.order() for s in init), "ordered by (level desc, lead desc)")
    check(init[0].level == max(s.level for s in init) and all(init[i].level >= init[i + 1].level for i in range(len(init) - 1)), "deepest first")
    st = p["stats"]
    check(st["ahead"] == EXPECTED_STARTS + st["same_words"] and st["clears_excluded"] >= 0 and st["bursts_rederived"] > 0, f"the stats {st}")
    check(st["level_arrivals"] == st["ahead"] + st["behind_or_equal"] + st["clears_excluded"], "every level arrival is classified")
    check(p["probe"]["start_set_digest"] == probe["plan"]["start_set_digest"] and p["route"]["digest"] == R["meta"]["native_action_digest"], "the probe's identity is recorded")
    check(p["arrival_by_level"] == {str(k): v for k, v in arrival.items()}, "the arrival ticks per level are the reference's")
    check(p["seed_ticks"] == sum(s.tick for s in init), "the seed cost is the sum of the arrival ticks")
    check(fs.ARM == {"segment_words": 120, "max_segments": 4, "window": 20}, f"the arm is the lab's CONT arm, got {fs.ARM}")
    S2 = fs.build_search_plan(lab, R, probe, fs.Params())
    check(S2["plan"]["start_set_digest"] == p["start_set_digest"] and [s.digest for s in S2["beam"].initial()] == [s.digest for s in init], "the plan is deterministic")
    rows = [fs.start_row(s) for s in init]
    check(all("words_hex" not in json.dumps(r) and r["seed"]["n"] >= 1 and r["seed"]["base_words"] + r["seed"]["n"] == r["tick"] for r in rows), "starts rows carry lengths and digests, not words")
    dig_now = fr.code_digest(fr.code_manifest())
    check(dig_now == p["probe"]["lab_code_digest"], f"the lab code digest {dig_now[:16]} is the probe's {str(p['probe']['lab_code_digest'])[:16]}")
    fit = p["throughput_fit"]
    check(fit["jobs"] > 0 and fit["wall_s_fixed"] > 0 and fit["wall_s_per_tick"] > 0 and 0 < fit["efficiency"] <= 1.0, f"the throughput fit {fit}")
    proj = fs.projection(fit, beam, fs.Params(), 5, 6.0)
    check(proj["available"] and proj["dispatches_per_h"] > 0 and proj["seed_ticks"] == p["seed_ticks"], f"the projection {proj}")
    deep = {lv: [(d["tick"], d["lead"]) for d in p["per_level"][str(lv)]["top"]] for lv in sorted(EXPECTED_FRONTIER_TICKS)}
    return {"starts": p["starts"], "per_level": per, "deep": deep, "seed_ticks": p["seed_ticks"], "stats": st, "lab_code_digest": dig_now[:16],
            "projection": {k: proj[k] for k in ("dispatches_per_h", "ticks_per_h", "rounds_per_h_base", "dispatches_over_wall")}}


@real
def real_prefixes_reproduce_recorded_reaches() -> Dict[str, Any]:
    X = real_import()
    lab, R, probe, S = X["lab"], X["R"], X["probe"], X["S"]
    P, beam = S["P"], S["beam"]
    by_pair = {int(s["pair"]): s for s in P["starts"]}
    rows = {(int(r["pair"]), str(r["arm"]), int(r["k"])): r for r in probe["rows"]}
    checked = 0
    for s in beam.initial():
        o, sd = s.origin, s.seed
        st, rec, row = by_pair[o["pair"]], probe["starts"][o["pair"]], rows[(o["pair"], o["arm"], o["k"])]
        base = bytes(st[o["arm"]]["words"])
        # the base prefix is the probe's recorded start (digest, length, chain), rebuilt from the import by the probe's own rule
        check(sd["base"] == base and mcell.words_digest(base) == rec[o["arm"]]["words_digest"] == mcell.words_digest(sd["base"]), f"start {s.sid}: the base prefix digest")
        check(len(base) == int(rec[o["arm"]]["words"]) == int(row["start_tick"]) == o["start_tick"], f"start {s.sid}: the base prefix length")
        check(bytes(sd["chain"]).hex() == rec[o["arm"]]["chain"] and bytes(sd["end_digest"]).hex() == rec[o["arm"]]["end_digest"], f"start {s.sid}: the base record digests")
        if o["arm"] == tp.LEAD:
            check(base == lab.cell_words(lab.cells[o["cid"]]) and len(base) == int(lab.cells[o["cid"]].L), f"start {s.sid}: a lead base is the cell's stored prefix")
        else:
            check(base == bytes(R["words"][:len(base)]), f"start {s.sid}: a control base is the route's words")
        # the recorded burst re-derives from the probe's key family and iteration; the prefix is the base plus the burst up to the arrival
        burst = bytes.fromhex(row["words_hex"])
        check(fa.stream_words(sd["draw_id"], sd["k"], len(burst)) == burst and sd["draw_id"] == row["draw_id"] == st["draw_id"] and sd["k"] == o["k"], f"start {s.sid}: the burst re-derives")
        check(s.words == base + burst[:sd["n"]] and len(s.words) == s.tick and 1 <= sd["n"] <= len(burst), f"start {s.sid}: the prefix is the base plus the burst to the arrival")
        # the recorded reading: the row reached this level at this tick, strictly ahead of the route, and every continuation before it was a go
        check(int(row["levels"][str(s.level)]) == s.tick and s.tick < int(R["arrival"][s.level]) and row["pace"][str(s.level)] == s.lead, f"start {s.sid}: the recorded arrival")
        check(all(d["go"] for d in row["decisions"] if int(d["words"]) < sd["n"]), f"start {s.sid}: the continuations before the arrival were go")
        check(row["prefix_level_ok"] and row["tick0_equal"] is True and row["outcome"] not in fs.BAD_OUTCOMES, f"start {s.sid}: the probe row is a clean job")
        checked += 1
    # the route's own arrival at each level is never a start (a start is strictly earlier)
    route_ticks = {int(v) for v in R["arrival"].values()}
    check(all(not (s.tick in route_ticks and s.words == bytes(R["words"][:s.tick])) for s in beam.initial()), "no start is the route's own state at its arrival")
    return {"checked": checked, "pairs": len({s.origin['pair'] for s in beam.initial()}), "arms": sorted({s.origin['arm'] for s in beam.initial()})}


# =============================================================================================================================================
# the round logic on stub results (zero native ticks)
# =============================================================================================================================================


def mask_of(level: int) -> int:
    return (1 << (mcell.TARGETS_TOTAL - level)) - 1


def key_of(x: int, level: int, y: int = 0) -> Tuple[int, int, str, int, int]:
    return (x, y, "A2", mask_of(level), -1)


def reach(j: int, key: Tuple[Any, ...], terminal: bool = False) -> Tuple[Any, ...]:
    return (j, key, (j,) * len(mcell.OBS_FIELDS), bytes([j % 256]) * 32, bytes([(j + 1) % 256]) * 32, terminal)


def words_for(tick: int, tag: int) -> bytes:
    return bytes((tag * 31 + i) % len(mcell.TRIPLES) for i in range(tick))


@synthetic
def round_logic_on_stub_results() -> Dict[str, Any]:
    arrival = {lv: 100 * lv for lv in range(mcell.TARGETS_TOTAL + 1)}
    p = fs.Params(bursts=2, frontier=4, share=0.5, bonus=1, retire_after=3, candidates="reaches", reserve=3)
    check(p.keep() == 2 and p.bursts_for(0) == 2 and p.bursts_for(1) == 3 and fs.Params(bonus=0).bursts_for(5) == fs.Params.bursts, "keep slots and the bonus arithmetic")
    for bad in (dict(bursts=0), dict(frontier=0), dict(share=1.0), dict(share=-0.1), dict(candidates="x"), dict(bonus=-1), dict(retire_after=-1)):
        try:
            fs.Params(**bad).check()
            raise AssertionError(f"params {bad} were accepted")
        except fs.SearchError:
            pass
    beam = fs.Beam("arch", arrival, p)
    # refusals of new_start: words are the tick, the level is live, the tick is strictly ahead
    for words, lv, t in ((words_for(10, 1), 2, 11), (words_for(10, 1), mcell.TARGETS_TOTAL, 10), (words_for(200, 1), 2, 200), (words_for(250, 1), 2, 250)):
        try:
            beam.new_start(words, lv, t, {"kind": "x"})
            raise AssertionError(f"new_start accepted level {lv} tick {t} with {len(words)} words")
        except fs.SearchError:
            pass
    # a parent at level 2, tick 150 (lead 50): its burst reaches ahead and behind, breaks at 170 (level 3) and 260 (level 4)
    parent, fresh = beam.new_start(words_for(150, 7), 2, 150, {"kind": "probe"})
    check(fresh and parent.lead == 50 and beam.place(parent, key_of(0, 2), (0,) * 17, b"\x01" * 32, b"\x02" * 32) == fs.HELD and parent.alive(), "the parent is placed")
    check(parent.draw_id("arch") == f"arch|frontier|{parent.digest}", "the draw id is the archive id, the key family and the prefix digest")
    burst = words_for(150, 9)
    res = {"words": burst, "breaks_all": [(50, 0), (120, 1), (170, 2), (260, 3)],
           "reaches": [reach(160, key_of(1, 2)), reach(170, key_of(2, 3)), reach(199, key_of(3, 2)), reach(205, key_of(4, 2)), reach(260, key_of(5, 4)),
                       reach(280, key_of(6, 4), terminal=True), reach(290, key_of(7, mcell.TARGETS_TOTAL))]}
    cands, c = beam.candidates(parent, res, 1, 0)
    got = sorted((s.level, s.tick, s.lead) for s in cands)
    check(got == [(2, 160, 40), (2, 199, 1), (3, 170, 130), (4, 260, 140)], f"reaches ahead of pace at their level: {got}")
    check(c["reaches"] == 7 and c["ahead"] == 4 and c["held"] == 4 and c["terminal"] == 1 and parent.children == 4 and parent.deepest_child == 4, f"the counts {c}")
    check(all(s.words == parent.words + burst[:s.tick - 150] and s.origin == {"kind": "burst", "parent": parent.sid, "round": 1, "k": 0} for s in cands), "a candidate's prefix")
    check(all(s.end == (s.tick,) * 17 and s.end_digest == bytes([s.tick % 256]) * 32 and s.key[3] == mask_of(s.level) for s in cands), "a candidate's end record is the reach's")
    # mode breaks: only the level arrivals
    beam_b = fs.Beam("arch", arrival, fs.Params(candidates="breaks", frontier=4))
    pb, _f = beam_b.new_start(words_for(150, 7), 2, 150, {"kind": "probe"})
    beam_b.place(pb, key_of(0, 2), (0,) * 17, b"\x01" * 32, b"\x02" * 32)
    cb, _c = beam_b.candidates(pb, res, 1, 0)
    check(sorted((s.level, s.tick) for s in cb) == [(3, 170), (4, 260)], "mode breaks keeps the level arrivals only")
    # key dedup: a later arrival at a held key is dropped, an earlier one supersedes the holder (whose prefix is freed, key kept)
    s160 = next(s for s in cands if s.tick == 160)
    later, fresh = beam.new_start(words_for(165, 3), 2, 165, {"kind": "burst"})
    check(fresh and beam.place(later, key_of(1, 2), (1,) * 17, b"\x03" * 32, b"\x04" * 32) == fs.LATER and not later.alive() and later.words is None and s160.alive(), "a later arrival is dropped")
    earlier, fresh = beam.new_start(words_for(155, 4), 2, 155, {"kind": "burst"})
    check(fresh and beam.place(earlier, key_of(1, 2), (1,) * 17, b"\x03" * 32, b"\x04" * 32) == fs.SUPERSEDES and earlier.alive() and not s160.alive()
          and s160.superseded == earlier.sid and s160.words is not None and beam.holder[key_of(1, 2)] == earlier.sid, "an earlier arrival supersedes the holder")
    check(beam.sweep() == 1 and s160.words is None and later.words is None, "the sweep frees the superseded prefix")
    # a later arrival at a held key inside a burst keeps no state at all
    n_before = len(beam.starts)
    _c2, cc = beam.candidates(parent, {"words": burst, "breaks_all": [], "reaches": [reach(165, key_of(1, 2))]}, 2, 1)
    check(cc["later"] == 1 and cc["ahead"] == 1 and len(beam.starts) == n_before, "a later arrival inside a burst is dropped before any state is kept")
    same, fresh = beam.new_start(words_for(155, 4), 2, 155, {"kind": "burst"})
    check(not fresh and same is earlier and beam.counts["same_words"] == 1, "the same words are the same state")
    check(beam.best[2]["tick"] == 150 and beam.best[3]["lead"] == 130 and beam.best[4]["lead"] == 140, f"best lead per level {beam.best}")
    try:
        beam.place(fs.Start(99, 3, 170, 130, "d", {}, b"x" * 170), key_of(8, 2), (), b"", b"")
        raise AssertionError("a key of another level was accepted")
    except fs.SearchError:
        pass
    # selection: the share keeps the previous frontier's best, then the candidates by (level desc, lead desc), then the rest, then the reserve
    beam2 = fs.Beam("arch", arrival, p)

    def mk(level: int, tick: int, tag: int) -> fs.Start:
        s, _f = beam2.new_start(words_for(tick, tag), level, tick, {"kind": "t", "tag": tag})
        beam2.place(s, key_of(tag, level), (0,) * 17, b"\x01" * 32, b"\x02" * 32)
        return s

    A, B, C, D = mk(3, 200, 1), mk(2, 150, 2), mk(2, 190, 3), mk(1, 10, 4)
    prev = beam2.select([A, B, C, D], [])
    check(prev == [A.sid, B.sid, C.sid, D.sid] and all(beam2.starts[i].selected == 1 for i in prev), f"the first frontier is the top F by order: {prev}")
    E, F, G = mk(4, 395, 5), mk(3, 180, 6), mk(2, 140, 7)
    nxt = beam2.select([E, F, G], prev)
    check(nxt == [E.sid, F.sid, A.sid, B.sid], f"share keeps A and B, the candidates E and F fill the rest: {nxt}")
    check(sorted(s.sid for s in beam2.reserve()) == sorted([G.sid, C.sid, D.sid]), "the rest is the reserve")
    again = beam2.select([], nxt)
    check(again == nxt, "with no candidate the previous frontier continues")
    beam2.p.reserve = 2
    check(beam2.evict() == 1 and D.words is None and D.alive() and beam2.holder[key_of(4, 1)] == D.sid, "eviction frees the worst reserve prefix but keeps its key")
    dup, fresh = beam2.new_start(words_for(12, 8), 1, 12, {"kind": "t"})
    check(beam2.place(dup, key_of(4, 1), (0,) * 17, b"\x01" * 32, b"\x02" * 32) == fs.LATER, "an evicted state's key still refuses later arrivals")
    # a start without words is never selected; retirement after R dispatches without a break; the switch off
    E.since_break = 3
    F.since_break = 2
    retired = beam2.retire(5)
    check([s.sid for s in retired] == [E.sid] and not E.alive() and "without a break" in E.retired and F.alive(), f"retirement {retired}")
    check(beam2.sweep() == 1 and E.words is None, "the sweep frees the retired prefix")
    nxt2 = beam2.select([], nxt)
    check(E.sid not in nxt2 and nxt2[0] == F.sid and len(nxt2) == 4 and G.sid in nxt2, f"the retired start leaves, the reserve fills: {nxt2}")
    beam2.p.retire_after = 0
    F.since_break = 99
    check(beam2.retire(6) == [], "retirement off")
    st = beam2.stats()
    check(st["retired"] == 1 and st["evicted"] == 1 and st["frontier"] == 4 and st["deepest_level"] == 4, f"stats {st}")
    pl = beam2.per_level(nxt2)
    check(list(pl)[0] == "3" and pl["3"]["starts"] == 2 and pl["3"]["best_lead"] == 120, f"per level {pl}")
    return {"candidates": got, "frontier": nxt, "after_retire": nxt2, "counts": beam.counts}


# =============================================================================================================================================
# the guard refusals
# =============================================================================================================================================


@synthetic
def guard_refusals() -> Dict[str, Any]:
    lab = tmpdir("lab")
    (lab / "import").mkdir()
    (lab / "import" / "import_manifest.json").write_text("{}", encoding="utf-8")
    probe = lab / "probe_x"                                             # not trail_probe_*: the default lookup must find nothing
    (probe / "run").mkdir(parents=True)
    for f in fs.PROBE_FILES:
        (probe / f).write_text("", encoding="utf-8")
    bad_out = [REPO / "frontier_x", REPO / "runs" / "frontier_x", REPO / "logs" / "frontier_x", lab / "runs" / "x", lab.parent / "elsewhere_x",
               Path("D:/BattleShip_runs_backup/x"), Path("D:/BattleShip_source_snapshots/x"), Path("D:/BattleShip_exe_archive/x")]
    for b in bad_out:
        try:
            g.validate_run_dir(b, lab)
            raise AssertionError(f"output folder {b} was accepted")
        except g.LabRootError:
            pass
    check(g.validate_run_dir(lab / "frontier_2026-01-01", lab) == lab / "frontier_2026-01-01", "an output folder inside the lab root is accepted")
    try:
        g.LabFS(lab).write_text(REPO / "logs" / f"frontier_guard_{os.getpid()}.tmp", "must never exist")
        raise AssertionError("LabFS wrote outside the lab root")
    except g.LabRootError:
        pass
    try:
        fs.read_probe(lab / "import")
        raise AssertionError("a folder without the probe's files was accepted")
    except fs.SearchError:
        pass
    exits = {}
    base = ["plan", "--lab-root", str(lab), "--probe", str(probe)]
    for argv in (base + ["--out", str(REPO / "frontier_x")], base + ["--out", str(lab / "runs" / "x")], ["plan", "--lab-root", str(REPO / "lab_x")],
                 base + ["--workers", "6"], base + ["--bursts", "0"], base + ["--frontier", "0"], base + ["--share", "1.5"], base + ["--max-wall-min", "0"],
                 ["plan", "--lab-root", str(lab), "--probe", str(REPO / "runs" / "x")], ["plan", "--lab-root", str(lab), "--probe", str(lab.parent / "elsewhere")],
                 ["plan", "--lab-root", str(lab), "--probe", str(lab / "import")], ["plan", "--lab-root", str(lab)]):
        try:
            fs.main(argv)
            raise AssertionError(f"main accepted {argv}")
        except SystemExit as exc:
            exits[" ".join(argv[1:])[-70:]] = str(exc)[:80]
    check(not g.LabGuard.installed, "the refusals happened before the guard was armed in this process")
    st = g.guard_selftest(lab)                                        # a child process arms the guard on the real checkout and evidence roots
    check(st["ok"], f"the guard self-test on the temporary lab root: {json.dumps(st, default=str)[:600]}")
    return {"refused_outputs": len(bad_out), "main_refusals": len(exits), "guard_child": st["child"]}


# =============================================================================================================================================
# the verification verdicts (stub traces)
# =============================================================================================================================================


@synthetic
def verification_verdicts() -> Dict[str, Any]:
    words, claim = T.stub_clear("easy")
    cand = {"round": 2, "sid": 5, "k": 1, "level": 8, "start_tick": 10, "lead": 3, "words": words, "claim": claim}
    t = claim["completion_input_tick"]
    rows = {}
    rows["ok"] = fs.clear_row(cand, fv.verify_twice(T.stub_replay(), stub.analyse, words, claim, "c1", 0), t + 1)
    rows["same"] = fs.clear_row(cand, fv.verify_twice(T.stub_replay(), stub.analyse, words, claim, "c2", 0), t)
    rows["slower"] = fs.clear_row(cand, fv.verify_twice(T.stub_replay(), stub.analyse, words, claim, "c3", 0), t - 5)
    rows["tamper"] = fs.clear_row(cand, fv.verify_twice(T.stub_replay(tamper_second=True), stub.analyse, words, claim, "c4", 0), t + 1)
    rows["error"] = fs.clear_row(cand, fv.verify_twice(T.stub_replay(fail=10), stub.analyse, words, claim, "c5", 0), t + 1)
    rows["clock"] = fs.clear_row(cand, fv.verify_twice(T.stub_replay(), stub.analyse, words, dict(claim, completion_input_tick=t - 1), "c6", 0), t + 1)
    rows["chain"] = fs.clear_row(cand, fv.verify_twice(T.stub_replay(), stub.analyse, words, dict(claim, chain="0" * 64), "c7", 0), t + 1)
    r = rows["ok"]
    check(r["verdict"] == fv.VERIFIED and r["faster_than_reference"] and r["gain_vs_reference"] == 1 and r["chain_r1"] == r["chain_r2"] == claim["chain"]
          and r["clocks_r1"] == r["clocks_r2"] == [t, t - 1] and r["breaks_r1"] == r["breaks_r2"] and r["words_digest"] == claim["words_digest"]
          and r["words_hex"] == words.hex() and r["round"] == 2 and r["sid"] == 5, f"VERIFIED row {r['reasons']}")
    check(rows["same"]["verdict"] == fv.VERIFIED and not rows["same"]["faster_than_reference"] and rows["same"]["gain_vs_reference"] == 0, "a clear at the reference's tick is not faster")
    check(rows["slower"]["verdict"] == fv.VERIFIED and not rows["slower"]["faster_than_reference"] and rows["slower"]["gain_vs_reference"] == -5, "a slower verified clear")
    check(rows["tamper"]["verdict"] == fv.NONDETERMINISTIC and not rows["tamper"]["faster_than_reference"] and rows["tamper"]["gain_vs_reference"] is None
          and rows["tamper"]["chain_r1"] != rows["tamper"]["chain_r2"], "two replays that disagree are NONDETERMINISTIC and never a clear")
    check(rows["error"]["verdict"] == fv.ERROR and not rows["error"]["faster_than_reference"] and rows["error"]["chain_r1"] is None, "a replay that cannot run is ERROR")
    check(rows["clock"]["verdict"] == fv.NONDETERMINISTIC and rows["chain"]["verdict"] == fv.NONDETERMINISTIC, "a claim the replay does not reproduce is never a clear")
    return {"clear_ticks": t, "verdicts": {k: v["verdict"] for k, v in rows.items()}}


# =============================================================================================================================================
# the synthetic end-to-end run (stub world; a synthetic probe output, then the engine in a guarded child with real spawned workers)
# =============================================================================================================================================


def synthetic_probe(lab: Path, per_start: int) -> Dict[str, Any]:
    """A trail-lead probe output folder made IN the stub world: the synthetic import (trail_probe_tests.build_synthetic_import), the probe's own
    plan and starts, and per_start dispatches per start and arm run in-process with the lab worker's job on the stub backend, written in the
    probe's dispatches.jsonl format (tp.summarise_result). THE WORLD IS SYNTHETIC."""
    info = tpt.build_synthetic_import(lab / "import")
    out = lab / "trail_probe_syn"
    L = tp.plan_and_write(lab, out, stub.analyse)
    lab_a, R, P = L["lab"], L["R"], L["P"]
    arrival = {int(k): int(v) for k, v in R["arrival"].items()}
    trail_by_key = {fa.norm_key(lab_a.cells[cid].key): int(jr) for cid, jr in P["first"].items()}
    pin = dict(L["meta"]["pin_tick0"])
    ctx = T.stub_ctx("easy", ask=lambda payload: bool(lab_a.continuation_decision(payload["reaches"])["go"]))
    run_dir = out / "run"
    run_dir.mkdir()
    rows: List[Dict[str, Any]] = []
    for k in range(per_start):
        for st in P["starts"]:
            for arm in (tp.LEAD, tp.CONTROL):
                sp = st[arm]
                L0 = len(sp["words"])
                want = L0 + min(tp.ARM["segment_words"] * tp.ARM["max_segments"], mcell.HORIZON - L0)
                job = {"kind": fw.JOB_KIND, "iteration": k, "cell": st["cid"], "rep": tuple(st["rep"] if arm == tp.LEAD else st["control_rep"]),
                       "words": bytes(sp["words"]), "end": tuple(sp["end"]), "end_digest": bytes(sp["end_digest"]), "chain": bytes(sp["chain"]),
                       "terminal": bool(sp["terminal"]), "pin": pin, "archive_id": st["draw_id"], "allowance": want, **tp.ARM}
                res = fw.run_job(ctx, job)
                check(res.get("ok"), f"synthetic probe job failed: {json.dumps(res, default=str)[:300]}")
                row = tp.summarise_result(res, st, arm, k, arrival, trail_by_key, lab_a)
                row["cont"] = []
                rows.append(row)
    with open(run_dir / "dispatches.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":"), default=str) + "\n")
    (run_dir / "config.json").write_text(json.dumps({"lab_code_digest": fr.code_digest(fr.code_manifest()), "n_workers": 1}), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps({"phase_wall_s": {"dispatch": 10.0}, "work": {"jobs": len(rows)}}), encoding="utf-8")
    ahead = sum(1 for r in rows for lv, t in r["levels"].items() if int(lv) < mcell.TARGETS_TOTAL and t < arrival[int(lv)])
    return {"import": info, "out": out, "rows": len(rows), "ahead": ahead, "advanced": sum(1 for r in rows if r["advanced"]), "leads": L["P"]["plan"]["leads"]}


RUN_CHILD = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, {rl!r}); sys.path.insert(0, {here!r})
import frs_guard as g
lab = Path({lab!r})
g.LabGuard.install(lab)
import frs_machine as fm, frs_run as fr, m8_rd_stub as stub, frontier_search as fs
out = Path({out!r}); run_dir = out / {run_name!r}; probe = Path({probe!r})
params = fs.Params(**{params!r})
L = fs.plan_and_write(lab, probe, out, params, stub.analyse)
env = fr.LabEnv(worker_spec=lambda rank: {{"rank": rank, "backend": "m8_rd_stub:StubBackend", "world": "easy", "inject": {{}},
                                           "failure_dir": str(run_dir / "failures"), "guard": g.LabGuard.spec()}},
                replay=lambda words, label, slot: stub.replay_trace("easy", words, label), analyse=stub.analyse,
                readiness=lambda: {{"ok": True, "problems": []}}, battleship_pids=lambda: [], snapshot=fm.tree_snapshot, import_problems=lambda: [],
                wait_no_battleship=lambda t: [], code_manifest=fr.code_manifest, backend="stub", sample_s=0.25, row_every_s=0.5,
                caps=dict(fm.CAPS_MB, main_private=1e9))
cfg = fs.SearchConfig(lab_root=lab, out=out, run_dir=run_dir, probe_dir=probe, n_workers=2, max_ticks={max_ticks!r}, max_wall_s={max_wall!r},
                      expect_code={expect!r}, stop_grace_s=10.0, verify_floor_s=5.0, verify_s_per_clear=2.0, write_reserve_s=2.0, progress_every_s=2.0)
code = fs.Search(cfg, env, L["lab"], L["meta"], L["R"], L["S"], params).run()
print(json.dumps({{"code": code, "violations": g.LabGuard.violations[:3], "starts": L["S"]["plan"]["starts"]}}))
'''


def run_child(code: str, timeout: float = 600.0) -> Dict[str, Any]:
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=timeout, cwd=str(HERE))
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise AssertionError(f"child failed: {(r.stderr or r.stdout)[-2500:]}")


def child_code(lab: Path, out: Path, probe: Path, run_name: str, params: Dict[str, Any], *, max_ticks: int = 10 ** 9, max_wall: float = 300.0,
               expect: Optional[str] = None) -> str:
    return RUN_CHILD.format(rl=str(RL), here=str(HERE), lab=str(lab), out=str(out), run_name=run_name, probe=str(probe), params=params, max_ticks=max_ticks,
                            max_wall=max_wall, expect=expect)


@synthetic
def stub_end_to_end() -> Dict[str, Any]:
    lab = tmpdir("lab")
    info = synthetic_probe(lab, per_start=3)
    check(info["ahead"] > 0, f"the synthetic probe recorded no level arrival ahead of its route: {info}")
    probe, out = info["out"], lab / "frontier_test"
    params = {"bursts": 4, "frontier": 8, "share": 0.25, "bonus": 2, "retire_after": 8, "candidates": "reaches", "reserve": 60, "max_rounds": 10}
    # the plan refuses to overwrite a different start set, accepts the same one again; its starts carry no words
    out.mkdir()
    (out / "plan.json").write_text(json.dumps({"start_set_digest": "0" * 64}), encoding="utf-8")
    try:
        fs.plan_and_write(lab, probe, out, fs.Params(**params), stub.analyse)
        raise AssertionError("a different saved start set was overwritten")
    except fs.SearchError:
        pass
    (out / "plan.json").unlink()
    L = fs.plan_and_write(lab, probe, out, fs.Params(**params), stub.analyse)
    L2 = fs.plan_and_write(lab, probe, out, fs.Params(**params), stub.analyse)
    p = L["S"]["plan"]
    check(p["starts"] > 0 and p["start_set_digest"] == L2["S"]["plan"]["start_set_digest"] and len(read_jsonl(out / "starts.jsonl")) == p["starts"], "the plan is deterministic")
    check("words_hex" not in (out / "starts.jsonl").read_text(encoding="utf-8"), "starts.jsonl carries no words")
    expect = fr.code_digest(fr.code_manifest())
    # the wrong lab code digest is refused at open (nothing launched)
    res0 = run_child(child_code(lab, out, probe, "run_badcode", params, expect="0" * 64))
    check(res0["code"] == 2 and any(f.name.startswith("refused_") for f in out.iterdir()) and not (out / "run_badcode").exists(), f"a wrong lab code digest is refused: {res0}")
    # the run
    res = run_child(child_code(lab, out, probe, "run", params, expect=expect))
    check(res["code"] == 0 and not res["violations"], f"the synthetic run: {res}")
    run_dir = out / "run"
    s = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    rows = read_jsonl(run_dir / "dispatches.jsonl")
    rounds = read_jsonl(run_dir / "rounds.jsonl")
    check(s["status"] == "COMPLETED" and s["work"]["rounds"] == params["max_rounds"] and s["stop"]["reason"].endswith("rounds done"), f"{s['status']} {s['stop']}")
    check(s["reference"]["ok"] is True and s["integrity"]["guard_violations_main"] == [] and s["integrity"]["battleship_left"] == []
          and s["integrity"]["lab_code_changed_during_run"] == [] and s["integrity"]["lab_code_digest_end"] == expect, f"{s['reference']} {s['integrity']}")
    # the seed: every initial start re-derived natively (the recorded words played, a break at the recorded tick), keys settled
    seeds = [r for r in rows if r["kind"] == "seed"]
    check(len(seeds) == p["starts"] == s["seed"]["starts"] and all(r["seed"]["ok"] and r["seed"]["n"] == r["seed"]["played"] for r in seeds), f"every seed reproduced: {s['seed']}")
    check(s["seed"]["ok"] == len(seeds) and s["seed"]["dropped"] == 0 and s["seed"]["held"] + s["seed"]["supersedes"] + s["seed"]["later"] == len(seeds), f"the seed stats {s['seed']}")
    check(all(r["prefix_level_ok"] and r["tick0_equal"] is True for r in rows), "every prefix reproduced its level and the tick-0 pin")
    check(rounds[0]["kind"] == "seed" and rounds[0]["frontier_out"] <= params["frontier"] and rounds[0]["distinct_keys"] == s["seed"]["held"]
          and s["seed"]["held"] + s["seed"]["later"] + s["seed"]["supersedes"] == len(seeds), f"round 0 {rounds[0]}")
    # the rounds: B bursts per frontier start (+ bonus for a break record), candidates ahead of pace, the next frontier at most F with the kept share
    bursts = [r for r in rows if r["kind"] == "burst"]
    check(len(rounds) == params["max_rounds"] + 1 and sum(r["jobs"] for r in rounds[1:]) == len(bursts) == s["work"]["burst_jobs"], "every burst is in a round")
    frontiers = {int(f.stem.split("_")[1]): read_jsonl(f) for f in (run_dir / "frontier").glob("round_*.jsonl")}
    check(sorted(frontiers) == list(range(1, params["max_rounds"] + 2)), f"a frontier file per round: {sorted(frontiers)}")
    arrival = {int(k): int(v) for k, v in p["arrival_by_level"].items()}
    by_sid: Dict[int, Dict[str, Any]] = {}
    for rnd, members in frontiers.items():
        check(len(members) <= params["frontier"] and all(m["has_words"] and m["key"] and m["lead"] == arrival[m["level"]] - m["tick"] > 0 and len(m["words_hex"]) == 2 * m["tick"]
                                                        for m in members), f"frontier {rnd}")
        check([(-m["level"], -m["lead"], m["tick"], m["digest"]) for m in members] == sorted((-m["level"], -m["lead"], m["tick"], m["digest"]) for m in members), f"frontier {rnd} ordered")
        for m in members:
            by_sid.setdefault(m["sid"], m)
    for rnd in range(1, params["max_rounds"] + 1):
        rr = rounds[rnd]
        members = {m["sid"]: m for m in frontiers[rnd]}
        mine = [r for r in bursts if r["round"] == rnd]
        check(rr["frontier_in"] == len(members) and all(r["sid"] in members for r in mine), f"round {rnd}: every burst is from its frontier")
        per_sid: Dict[int, List[Dict[str, Any]]] = {}
        for r in mine:
            per_sid.setdefault(r["sid"], []).append(r)
        for sid, rs in per_sid.items():
            n_bonus = sum(1 for r in rs if r["bonus"])
            check(len(rs) - n_bonus == params["bursts"] and n_bonus in (0, params["bonus"]), f"round {rnd} start {sid}: {len(rs)} bursts ({n_bonus} bonus)")
            if n_bonus:
                check(any(r["advanced"] for r in bursts if r["sid"] == sid and r["round"] < rnd), f"round {rnd} start {sid}: a bonus needs a break record")
        for sid in members:
            ks = [r["k"] for r in bursts if r["sid"] == sid]
            check(sorted(ks) == list(range(len(ks))), f"round {rnd} start {sid}: a start's iterations are 0..n-1, never repeated (rows land in completion order): {ks}")
        check(rr["frontier_out"] <= params["frontier"] and rr["kept_from_previous"] <= fs.Params(**params).keep() + max(0, params["frontier"] - rr["candidates"]), f"round {rnd} {rr}")
        check(rr["kept_from_previous"] >= min(fs.Params(**params).keep(), rr["previous_alive"]), f"round {rnd}: the share of the previous frontier is kept")
    # a candidate's prefix is its parent's words plus its own burst to the reach (checked on the frontier members whose parent sits in a frontier file)
    checked = 0
    rows_by = {(r["round"], r["sid"], r["k"]): r for r in bursts}
    for m in by_sid.values():
        o = m["origin"]
        if o.get("kind") == "burst" and o["parent"] in by_sid:
            parent = by_sid[o["parent"]]
            r = rows_by[(o["round"], o["parent"], o["k"])]
            check(m["words_hex"] == parent["words_hex"] + r["words_hex"][:2 * (m["tick"] - parent["tick"])], f"start {m['sid']}: the prefix is the parent's plus the burst")
            checked += 1
    check(checked > 0, "at least one child start was checked against its parent")
    # clears: every candidate verified twice in fresh processes, identical replays, compared with the reference; progress.md names them
    vrows = read_jsonl(run_dir / "verifications.jsonl") if (run_dir / "verifications.jsonl").is_file() else []
    claimed = [r for r in bursts if r["outcome"] == "clear"]
    check(len(vrows) == len(claimed) == s["clears"]["candidates"] >= 1, f"a verified clear is needed: {len(vrows)} of {len(claimed)} claimed")
    check(all(v["verdict"] == fv.VERIFIED and v["chain_r1"] == v["chain_r2"] and v["clocks_r1"] == v["clocks_r2"] and v["reference_completion_input_tick"] == arrival[mcell.TARGETS_TOTAL]
              for v in vrows), "stub clears replay identically")
    check(s["clears"]["verified"] == len(vrows) and s["unverified"] == [] and s["clears"]["best_verified"]["completion_input_tick"] == min(v["completion_input_tick"] for v in vrows), f"{s['clears']}")
    for v in vrows:
        r = rows_by[(v["round"], v["sid"], v["k"])]
        parent = by_sid[v["sid"]]
        check(v["completion_input_tick"] == r["claimed"]["completion_input_tick"] == r["ticks"] and v["words"] == r["ticks"]
              and v["words_hex"] == parent["words_hex"] + r["words_hex"], "the verified clock is the in-run claim and the words are the start's plus the burst")
        check(v["faster_than_reference"] == (v["completion_input_tick"] < arrival[mcell.TARGETS_TOTAL]) and v["gain_vs_reference"] == arrival[mcell.TARGETS_TOTAL] - v["completion_input_tick"], "the comparison")
    prog = (run_dir / "progress.md").read_text(encoding="utf-8")
    check(prog.startswith("# Frontier continuation search: progress (") and "Final." in prog and "VERIFIED" in prog and f"| {vrows[0]['round']}, {vrows[0]['sid']}, {vrows[0]['k']} |" in prog, "progress.md")
    check((run_dir / "report.md").read_text(encoding="utf-8").startswith("# Frontier continuation search run (") and (run_dir / "config.json").is_file()
          and (run_dir / "memory.jsonl").is_file() and (run_dir / "reference.json").is_file() and (run_dir / "state.json").is_file(), "the run folder")
    check(s["memory"]["projection"].get("rows", 0) >= 0 and s["throughput"]["jobs_per_h"] > 0, "the memory projection and the throughput")
    # a tick cap stops the dispatches cleanly (exit 0, status TICK_CAP, the pending clears verified at the close, summary written)
    cap = p["seed_ticks"] + 3 * (max(arrival.values()) + fs.ARM["segment_words"] * fs.ARM["max_segments"]) + 10
    res2 = run_child(child_code(lab, out, probe, "run_cap", params, max_ticks=cap, expect=expect))
    s2 = json.loads((out / "run_cap" / "summary.json").read_text(encoding="utf-8"))
    check(res2["code"] == 0 and s2["status"] == "TICK_CAP" and s2["work"]["ticks_total"] <= cap and s2["seed"]["ok"] == p["starts"] and s2["work"]["burst_jobs"] >= 1
          and s2["work"]["queued_left"] > 0 and s2["unverified"] == [] and s2["integrity"]["battleship_left"] == [], f"the tick cap: {s2['status']} {s2['work']} {s2['unverified']}")
    check(s2["clears"]["candidates"] == len(read_jsonl(out / "run_cap" / "verifications.jsonl")) if (out / "run_cap" / "verifications.jsonl").is_file() else s2["clears"]["candidates"] == 0,
          "every pending clear of a capped run is verified at the close")
    check("Final." in (out / "run_cap" / "progress.md").read_text(encoding="utf-8"), "the capped run's final progress")
    # a wall cap stops cleanly too (the deadline is reached during the seed or the first round)
    res3 = run_child(child_code(lab, out, probe, "run_wall", params, max_wall=25.0, expect=expect))
    s3 = json.loads((out / "run_wall" / "summary.json").read_text(encoding="utf-8"))
    check(res3["code"] == 0 and s3["status"] == "WALL_CAP" and s3["elapsed_s"] < 25.0 + 60.0 and s3["integrity"]["battleship_left"] == [], f"the wall cap: {s3['status']} {s3['elapsed_s']}")
    # a second run into the same run folder is refused (never overwritten): the engine refuses at open, nothing is launched
    res4 = run_child(child_code(lab, out, probe, "run", params, expect=expect))
    check(res4["code"] == 2, f"an existing run folder is refused: {res4}")
    return {"synthetic": {k: info[k] for k in ("rows", "ahead", "advanced", "leads")}, "starts": p["starts"], "seeded": s["seed"]["ok"], "rounds": s["work"]["rounds"],
            "bursts": len(bursts), "advanced": s["work"]["advanced"], "clears_verified": s["clears"]["verified"], "best": s["clears"]["best_verified"]["completion_input_tick"],
            "reference": arrival[mcell.TARGETS_TOTAL], "cap_bursts": s2["work"]["burst_jobs"], "wall_rounds": s3["work"]["rounds"], "children_checked": checked}


# =============================================================================================================================================


def main(argv: Sequence[str]) -> int:
    global LAB, PROBE
    args = list(argv[1:])
    for flag in ("--lab-root", "--probe"):
        if flag in args:
            i = args.index(flag)
            if flag == "--lab-root":
                LAB = Path(args[i + 1])
            else:
                PROBE = Path(args[i + 1])
            del args[i:i + 2]
    sel = args[0] if args else "all"
    pick = [t for t in TESTS if sel == "all" or t[0] == sel or (sel == "only" and len(args) > 1 and args[1] in t[1])]
    passed = 0
    t_all = time.perf_counter()
    for kind, name, fn in pick:
        t0 = time.perf_counter()
        try:
            info = fn()
            passed += 1
            extra = json.dumps(info, default=str, separators=(",", ":"))[:500] if info else ""
            print(f"PASS {name} ({time.perf_counter() - t0:.1f} s) {extra}", flush=True)
        except Exception as exc:  # noqa: BLE001 - reported per test
            print(f"FAIL {name} ({time.perf_counter() - t0:.1f} s): {type(exc).__name__}: {exc}"[:3000], flush=True)
            print(traceback.format_exc()[-2500:], flush=True)
    for p in CREATED:
        shutil.rmtree(p, ignore_errors=True)
    print(f"frontier search tests: {passed}/{len(pick)} passed in {time.perf_counter() - t_all:.0f} s")
    return 0 if passed == len(pick) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
